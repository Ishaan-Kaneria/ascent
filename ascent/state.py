"""Builds the per-problem view of your history from the database."""
from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field

from . import skill
from .config import Config
from .difficulty import IGNORED_VERDICTS, Outcome

LIVE = {"CONTESTANT", "VIRTUAL", "OUT_OF_COMPETITION"}

# Topic tiers: a tag "unlocks" at a rating. Readiness for a target checks every
# tag unlocked at or below it. Quant weight reflects how often a topic shows up
# in quant / trading-firm OAs and interviews (probability, combinatorics and
# math-heavy reasoning more than geometry or heavy string structures).
TAG_TIERS: dict[str, tuple[int, float]] = {
    # tag: (unlock rating, quant weight)
    "implementation": (800, 0.6), "math": (800, 1.0), "greedy": (800, 1.0),
    "brute force": (800, 0.6), "constructive algorithms": (1000, 1.0),
    "sortings": (900, 0.7), "strings": (900, 0.7), "number theory": (1100, 0.9),
    "two pointers": (1200, 0.8), "binary search": (1200, 1.0), "bitmasks": (1300, 0.9),
    "dp": (1300, 1.0), "combinatorics": (1400, 1.0), "graphs": (1400, 0.8),
    "dfs and similar": (1400, 0.8), "trees": (1500, 0.8), "data structures": (1500, 0.8),
    "dsu": (1600, 0.7), "shortest paths": (1700, 0.7), "probabilities": (1700, 1.0),
    "games": (1700, 0.9), "interactive": (1700, 0.8), "hashing": (1800, 0.5),
    "divide and conquer": (1900, 0.6), "geometry": (2000, 0.4),
}


def core_tags(level: int) -> list[str]:
    return [t for t, (unlock, _) in TAG_TIERS.items() if unlock <= level]


@dataclass
class State:
    cfg: Config
    outcomes: dict[str, Outcome]
    solved: set[str]
    attempted: set[str]
    cf_rating: int | None
    cf_max: int | None
    cf_history: list[dict]
    lc_rating: float | None
    lc_history: list[dict]
    daily: dict[str, int]                   # 'YYYY-MM-DD' -> distinct problems solved
    now: float = field(default_factory=time.time)
    _overall: skill.Estimate | None = None
    _tags: dict | None = None

    @property
    def cf_outcomes(self) -> list[Outcome]:
        return [o for o in self.outcomes.values() if o.pid.startswith("CF:")]

    def overall(self) -> skill.Estimate:
        if self._overall is None:
            self._overall = skill.overall(
                self.cf_outcomes, contest_rating=self.cf_rating, n_contests=len(self.cf_history),
                practice_discount=self.cfg.practice_discount,
                half_life_days=self.cfg.recency_half_life_days, now=self.now)
        return self._overall

    def tag_skills(self) -> dict[str, skill.Estimate]:
        if self._tags is None:
            self._tags = skill.by_tag(
                self.cf_outcomes, list(TAG_TIERS), self.overall(),
                practice_discount=self.cfg.practice_discount,
                half_life_days=self.cfg.recency_half_life_days, now=self.now)
        return self._tags

    def level(self) -> int:
        """The rating recommendations are built around: the posterior mean,
        but never more than 150 above the model-free frontier when one exists."""
        est = self.overall().mean
        fr = skill.frontier(self.cf_outcomes, now=self.now)
        if fr is not None:
            est = min(est, fr + 150)
        return int(round(est / 50) * 50)


def load(conn: sqlite3.Connection, cfg: Config, now: float | None = None) -> State:
    now = now or time.time()
    probs = {r["pid"]: r for r in conn.execute("SELECT * FROM problems")}
    subs = defaultdict(list)
    for r in conn.execute("SELECT * FROM submissions ORDER BY time"):
        subs[r["pid"]].append(r)
    logs = defaultdict(list)
    for r in conn.execute("SELECT * FROM attempts ORDER BY finished_at"):
        logs[r["pid"]].append(r)
    manual = {r["pid"]: r["time"] for r in conn.execute("SELECT * FROM manual_solved")}

    # Time spent on a problem in a live/virtual contest ~ time since your
    # previous accepted problem in that same contest (not since contest start,
    # which would unfairly penalise later problems).
    live_minutes: dict[str, float] = {}
    by_contest = defaultdict(list)
    for pid, ss in subs.items():
        ac = next((s for s in ss if s["verdict"] == "OK"), None)
        if ac and ac["participant_type"] in LIVE and ac["relative_time"] is not None \
                and ac["relative_time"] < 10 ** 8 and pid.startswith("CF:"):
            cid = probs[pid]["contest_id"] if pid in probs else None
            by_contest[(cid, ac["participant_type"])].append((ac["relative_time"], pid))
    for acs in by_contest.values():
        acs.sort()
        prev = 0
        for rel, pid in acs:
            live_minutes[pid] = max(1.0, (rel - prev) / 60)
            prev = rel

    outcomes: dict[str, Outcome] = {}
    daily: dict[str, int] = defaultdict(int)
    for pid in set(subs) | set(logs) | set(manual):
        p = probs.get(pid)
        rating = p["rating"] if p else None
        tags = json.loads(p["tags"]) if p and p["tags"] else []
        ss = [s for s in subs.get(pid, []) if s["verdict"] not in IGNORED_VERDICTS]
        pl = logs.get(pid, [])
        first_ac = next((s for s in ss if s["verdict"] == "OK"), None)
        wrong = sum(1 for s in ss if s["verdict"] != "OK"
                    and (first_ac is None or s["time"] < first_ac["time"]))
        solved = first_ac is not None or pid in manual or any(l["solved"] for l in pl)
        times = [s["time"] for s in ss] + [l["started_at"] or l["finished_at"] for l in pl
                                           if (l["started_at"] or l["finished_at"])]
        if pid in manual:
            times.append(manual[pid])
        first_time = min(times) if times else int(now)
        if first_ac:
            solve_time = first_ac["time"]
        else:
            solve_time = manual.get(pid) or next((l["finished_at"] for l in pl if l["solved"]), None)
        in_contest = pid in live_minutes
        minutes = live_minutes.get(pid)
        logged = [l["minutes"] for l in pl if l["minutes"] is not None]
        if logged:  # an explicit log/timer is more precise than the contest estimate
            minutes = logged[-1]
        editorial = any(l["editorial"] for l in pl)
        outcomes[pid] = Outcome(pid, rating, tags, solved, first_time, solve_time, wrong,
                                in_contest, minutes, editorial)
        if solved and solve_time:
            daily[time.strftime("%Y-%m-%d", time.localtime(solve_time))] += 1

    hist = [dict(r) for r in conn.execute(
        "SELECT * FROM rating_history WHERE platform='CF' ORDER BY time")]
    lch = [dict(r) for r in conn.execute(
        "SELECT * FROM rating_history WHERE platform='LC' ORDER BY time")]
    cf_rating = hist[-1]["new_rating"] if hist else None
    cf_max = max((h["new_rating"] for h in hist), default=None)
    lc_rating = lch[-1]["new_rating"] if lch else None
    return State(cfg, outcomes, {p for p, o in outcomes.items() if o.solved},
                 set(outcomes), cf_rating, cf_max, hist, lc_rating, lch, dict(daily), now)
