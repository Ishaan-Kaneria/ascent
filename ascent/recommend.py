"""Recommendations: real, unsolved problems from the live catalog, chosen above
your level and weighted toward your weakest topics.

Hard rules:
* Never below your level. The lowest band (weak-topic drills) starts AT your
  level; everything else starts at level + 100.
* Only problems with an official rating, or an estimate explicitly marked
  'estimated'.
* No April Fools / '*special' problems, at most one problem per contest.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import time
from dataclasses import dataclass

from .state import TAG_TIERS, State

BUCKETS = {
    # name: (low offset, high offset, share of the list, why)
    "core":    (100, 300, 0.50, "just above your level: where rating is gained"),
    "weak":    (0, 200, 0.20, "drills a weak topic"),
    "tricky":  (100, 300, 0.15, "observation-heavy: the OA/quant style"),
    "stretch": (300, 500, 0.15, "expect to struggle; that's the point"),
}
KIND_BONUS = {"div2": 0.4, "edu": 0.4, "div3": 0.3, "div12": 0.3, "global": 0.3,
              "div4": 0.0, "div1": -0.3, "other": -0.6}


@dataclass
class Rec:
    pid: str
    name: str
    rating: int
    rating_source: str
    tags: list[str]
    bucket: str
    reason: str
    url: str
    est_minutes: int
    p_solve: float


def _round_up(x: float) -> int:
    return int(math.ceil(x / 100) * 100)


def tag_needs(st: State) -> dict[str, float]:
    """Higher = more practice needed. Gap below overall skill, plus a bonus
    for topics you have barely touched (low evidence)."""
    level = st.level()
    ov = st.overall()
    needs = {}
    for t, est in st.tag_skills().items():
        unlock, _ = TAG_TIERS[t]
        if unlock > level + 200:
            continue
        gap = max(0.0, ov.mean - est.mean) / 100
        unexplored = 1.0 if est.evidence < 3 else (0.4 if est.evidence < 8 else 0.0)
        needs[t] = round(gap + unexplored, 3)
    return needs


def candidates(conn: sqlite3.Connection, st: State, lo: int, hi: int) -> list[dict]:
    rows = conn.execute(
        """SELECT p.*, c.kind AS kind, c.name AS contest_name FROM problems p
           LEFT JOIN contests c ON c.id = p.contest_id
           WHERE p.platform='CF' AND p.rating BETWEEN ? AND ?
             AND p.contest_id >= ? AND p.contest_id < 100000""",
        (lo, hi, st.cfg.min_contest_id)).fetchall()
    out = []
    for r in rows:
        if r["pid"] in st.attempted:
            continue
        tags = json.loads(r["tags"] or "[]")
        if "*special" in tags or "april fools" in (r["contest_name"] or "").lower():
            continue
        out.append({**dict(r), "tags": tags})
    return out


def recommend(conn: sqlite3.Connection, st: State, n: int = 8, *, mode: str = "mix",
              tag: str | None = None, seed: int | None = None) -> list[Rec]:
    level = st.level()
    needs = tag_needs(st)
    weakest = [t for t, _ in sorted(needs.items(), key=lambda kv: -kv[1])[:3]]
    rng = random.Random(seed if seed is not None else int(time.strftime("%Y%m%d")))
    max_cid = conn.execute("SELECT MAX(contest_id) FROM problems WHERE platform='CF' AND contest_id < 100000").fetchone()[0] or 1

    if mode == "mix":
        plan = []
        for b, (_, _, share, _) in BUCKETS.items():
            plan += [b] * max(1 if b in ("core", "weak") else 0, round(share * n))
        plan = (plan + ["core"] * n)[:n]
    else:
        plan = [mode] * n

    picked: list[Rec] = []
    used_pids: set[str] = set()
    used_contests: set[int] = set()
    seen_bucket: dict[str, int] = {}
    for b in plan:
        lo_off, hi_off, _, why = BUCKETS[b]
        lo, hi = max(800, _round_up(level + lo_off)), _round_up(level + hi_off)
        # Walk the band bottom-up (lo, lo+100, ..., hi, lo, ...) so a list is a
        # graded ladder rather than random ratings inside the band.
        k = seen_bucket.get(b, 0)
        seen_bucket[b] = k + 1
        steps = list(range(lo, hi + 1, 100))
        want = steps[k % len(steps)]
        full = candidates(conn, st, lo, hi)
        pool = [p for p in full if p["rating"] == want] or full
        focus = [tag] if tag else (weakest if b == "weak" else None)
        if focus:
            pool = [p for p in pool if set(p["tags"]) & set(focus)]
        if b == "tricky":
            pool = [p for p in pool if (p["trick"] or 0) >= 0.5]
        pool = [p for p in pool if p["pid"] not in used_pids and p["contest_id"] not in used_contests]
        if not pool:
            pool = [p for p in full if p["pid"] not in used_pids and p["contest_id"] not in used_contests
                    and (not focus or set(p["tags"]) & set(focus))
                    and (b != "tricky" or (p["trick"] or 0) >= 0.5)]
        if not pool:
            continue

        def score(p: dict) -> float:
            real = [t for t in p["tags"] if not t.startswith("*")]
            tag_part = sum(TAG_TIERS.get(t, (0, 0.3))[1] * (1 + needs.get(t, 0)) for t in real) / max(1, len(real))
            recency = p["contest_id"] / max_cid
            kind = KIND_BONUS.get(p["kind"] or "other", 0)
            if p["kind"] == "div4" and level >= 1400:
                kind -= 0.4
            return tag_part + 0.8 * (p["trick"] or 0) + 0.6 * recency + kind + rng.random() * 0.6

        best = max(pool, key=score)
        used_pids.add(best["pid"])
        used_contests.add(best["contest_id"])
        real_tags = [t for t in best["tags"] if not t.startswith("*")]
        reason = why
        hit = [t for t in real_tags if t in weakest]
        if b == "weak" and hit:
            est = st.tag_skills()[hit[0]]
            reason = f"weak topic '{hit[0]}' (your est. {est.mean:.0f}, evidence {est.evidence:.1f})"
        elif b == "tricky":
            reason += f" (trickiness {best['trick']:.2f})"
        delta = best["rating"] - level
        p = 1 / (1 + 10 ** ((best["rating"] - (level + st.cfg.practice_discount)) / 400))
        picked.append(Rec(best["pid"], best["name"], best["rating"], best["rating_source"] or "official",
                          real_tags, b, reason, best["url"], est_minutes=int(30 + max(0, delta) * 0.1),
                          p_solve=round(p, 2)))
    return picked


def recommend_lc(conn: sqlite3.Connection, st: State, n: int = 5, seed: int | None = None) -> list[Rec]:
    """LeetCode problems by zerotrac contest rating, above your LC contest rating."""
    if not st.lc_rating:
        return []
    base = st.lc_rating
    rng = random.Random(seed if seed is not None else int(time.strftime("%Y%m%d")))
    rows = [r for r in conn.execute(
        "SELECT * FROM problems WHERE platform='LC' AND rating_source='zerotrac' AND rating BETWEEN ? AND ?",
        (base + 100, base + 400)) if r["pid"] not in st.attempted]
    rng.shuffle(rows)
    out = []
    for r in sorted(rows[:n], key=lambda r: r["rating"]):
        out.append(Rec(r["pid"], r["name"], r["rating"], "zerotrac", [], "lc",
                       f"LC contest-rated {r['rating']} (you: {base:.0f})", r["url"], 40, 0.0))
    return out
