"""Readiness: evidence-based gates. You are told you're ready only when EVERY
gate passes. Each gate reports what you have, what is required, and what to do.

Thresholds are deliberately demanding and live in one place (GATES below)
so you can see and argue with them. They are my judgement of what reliably
separates someone who *is* at a level from someone who got lucky once. They are
not official numbers from Codeforces or from any firm.
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass

from .state import State, core_tags

DAY = 86400


@dataclass
class Gate:
    name: str
    passed: bool
    have: str
    need: str
    action: str


def contest_of(pid: str) -> int:
    return int(re.match(r"CF:(\d+)", pid).group(1))


def speed_limit(target: int) -> int:
    """Median minutes per problem rated ~target that a person AT target manages
    in contest conditions."""
    if target <= 1200:
        return 25
    if target <= 1400:
        return 30
    if target <= 1600:
        return 40
    return 50


def _perf(h: dict) -> float:
    # Rough inversion of the Elo update: delta ~ (performance - old) / 4.
    return h["old_rating"] + 4 * (h["new_rating"] - h["old_rating"])


def cf_gates(st: State, target: int) -> list[Gate]:
    now = st.now
    cf = st.cf_outcomes
    gates: list[Gate] = []

    # 1. Contest results
    hist = st.cf_history
    settled = hist[6:]  # the first 6 rated rounds carry new-account bonuses
    recent = settled[-5:]
    med = statistics.median(_perf(h) for h in recent) if len(recent) >= 5 else None
    ok = bool(st.cf_rating and st.cf_rating >= target) or (med is not None and med >= target)
    gates.append(Gate(
        "Contest results", ok,
        f"rating {st.cf_rating or 'none'}; median perf (last 5, est.) {med:.0f}" if med is not None
        else f"rating {st.cf_rating or 'none'}; {len(settled)} settled rated rounds (need 5)",
        f"rating >= {target}, or median performance of last 5 rounds >= {target}",
        "Play every Div. 2 / Div. 3 / Educational round you can. Practice without contests does not count here."))

    # 2. Volume at the target level, recent, solved well
    at = [o for o in cf if o.solved and o.rating and o.rating >= target and o.quality >= 0.8
          and o.solve_time and now - o.solve_time <= 120 * DAY]
    gates.append(Gate(
        f"Volume at {target}+", len(at) >= 40, f"{len(at)} clean solves in 120 days",
        f">= 40 problems rated >= {target}, <= 3 wrong attempts, no editorial",
        f"`ascent recommend --mode core` until this hits 40."))

    # 3. Ceiling: you can occasionally do problems well above target
    above = [o for o in cf if o.solved and o.rating and o.rating >= target + 200 and not o.editorial]
    gates.append(Gate(
        f"Ceiling ({target + 200}+)", len(above) >= 10, f"{len(above)} solved without editorial",
        f">= 10 problems rated >= {target + 200}",
        "`ascent recommend --mode stretch`. Give each one at least 60 minutes before reading the editorial."))

    # 4. Topic coverage
    tags = core_tags(target)
    per_tag = defaultdict(int)
    for o in cf:
        if o.solved and o.rating and o.rating >= target - 200 and o.quality >= 0.8:
            for t in o.tags:
                per_tag[t] += 1
    missing = [t for t in tags if per_tag[t] < 3]
    gates.append(Gate(
        "Topic coverage", not missing,
        f"{len(tags) - len(missing)}/{len(tags)} topics covered" + (f"; missing: {', '.join(missing)}" if missing else ""),
        f">= 3 clean solves rated >= {target - 200} in every topic unlocked by {target}",
        f"`ascent recommend --tag \"{missing[0]}\"`" if missing else "Keep it up."))

    # 5. Speed under the clock
    band = [o.minutes for o in cf if o.solved and o.minutes is not None and o.rating
            and target - 100 <= o.rating <= target + 100 and not o.editorial]
    med_min = statistics.median(band) if band else None
    limit = speed_limit(target)
    gates.append(Gate(
        "Speed", len(band) >= 8 and med_min is not None and med_min <= limit,
        f"{len(band)} timed solves, median {med_min:.0f} min" if med_min is not None else "no timed solves",
        f">= 8 timed solves rated {target - 100}-{target + 100}, median <= {limit} min",
        "Use `ascent start <problem>` before reading a statement, and do virtual contests: they are timed automatically."))

    # 6. Model estimate (conservative)
    ov = st.overall()
    gates.append(Gate(
        "Skill estimate", ov.low >= target, f"{ov} (conservative {ov.low:.0f})",
        f"conservative estimate (mean - 1 sd) >= {target}",
        "Rises only with solves near/above your level and with fewer failures there. Easy solves are ignored."))

    # 7. Consistency in live/virtual rounds
    probs_by_contest = defaultdict(list)
    for o in cf:
        if o.in_contest:
            probs_by_contest[contest_of(o.pid)].append(o)
    rounds = sorted(probs_by_contest.items(), key=lambda kv: max(x.first_time for x in kv[1]))[-5:]
    good_rounds = sum(1 for _, os_ in rounds if any(o.solved and o.rating and o.rating >= target - 100 for o in os_))
    gates.append(Gate(
        "Consistency", len(rounds) >= 5 and good_rounds >= 3,
        f"{good_rounds}/{len(rounds)} recent live/virtual rounds with a {target - 100}+ solve",
        f"in >= 3 of your last 5 rounds (rated or virtual), solve a problem rated >= {target - 100} in-contest",
        "One good round is luck; three of five is a level."))
    return gates


def oa_gates(st: State) -> list[Gate]:
    """Quant / OA profile: CF 1600 practice gates + LeetCode + quant topics."""
    cfg = st.cfg
    gates = [g for g in cf_gates(st, 1600) if g.name.split()[0] in ("Volume", "Ceiling", "Topic", "Speed")]
    lc = st.lc_rating
    gates.append(Gate(
        "LeetCode contest rating", bool(lc and lc >= cfg.oa_lc_contest_rating),
        f"{lc:.0f}" if lc else "none", f">= {cfg.oa_lc_contest_rating}",
        "Weekly + biweekly contests. OAs are timed, so contests are the closest practice."))
    hard = [o for o in st.outcomes.values() if o.pid.startswith("LC:") and o.solved and o.rating
            and o.rating >= cfg.oa_lc_hard_rated_min]
    gates.append(Gate(
        f"LeetCode {cfg.oa_lc_hard_rated_min}+ solves", len(hard) >= cfg.oa_lc_hard_rated_count,
        f"{len(hard)}", f">= {cfg.oa_lc_hard_rated_count} problems with zerotrac rating >= {cfg.oa_lc_hard_rated_min}",
        "`ascent recommend --lc`"))
    quant = ["probabilities", "combinatorics", "math", "games", "number theory"]
    cnt = defaultdict(int)
    for o in st.cf_outcomes:
        if o.solved and o.rating and o.rating >= 1500 and o.quality >= 0.8:
            for t in o.tags:
                cnt[t] += 1
    miss = [t for t in quant if cnt[t] < 4]
    gates.append(Gate(
        "Quant topics", not miss, ", ".join(f"{t}:{cnt[t]}" for t in quant),
        ">= 4 clean solves rated >= 1500 in each of " + ", ".join(quant),
        f"`ascent recommend --tag \"{miss[0]}\"`" if miss else "Keep it up."))
    return gates


def verdict(gates: list[Gate]) -> str:
    passed = sum(g.passed for g in gates)
    if passed == len(gates):
        return f"READY: all {len(gates)} gates pass."
    return f"NOT READY: {passed}/{len(gates)} gates pass. Fix the failing gates below; there are no shortcuts."
