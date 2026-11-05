"""Problem difficulty: official ratings, estimates for unrated problems,
a 'trickiness' signal, and per-attempt personal difficulty.

Everything here is a transparent heuristic or a small regression fitted on the
real Codeforces catalog. Estimated values are always labelled as estimates.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass

# Tags that rarely name an algorithm: a problem whose tags are a subset of
# these and that sits at >= 1400 usually hinges on an observation.
OBSERVATION_TAGS = {"math", "greedy", "constructive algorithms", "brute force",
                    "implementation", "sortings"}
TRICKY_TAGS = {"constructive algorithms": 1.0, "interactive": 1.0, "games": 0.9,
               "probabilities": 0.6, "combinatorics": 0.5, "bitmasks": 0.4}


def index_rank(idx: str) -> float:
    """'A' -> 0, 'B' -> 1, 'C1' -> 2, 'C2' -> 2.5, 'F' -> 5."""
    m = re.match(r"([A-Z])(\d*)", idx or "A")
    base = ord(m.group(1)) - ord("A")
    sub = int(m.group(2)) if m.group(2) else 1
    return base + 0.5 * (sub - 1)


def _letter(idx: str) -> str:
    return (idx or "A")[0]


@dataclass
class UnratedModel:
    """rating ~ group_mean + slope * (log1p(solved) - group_mean_log_solved),
    where group = (contest kind, problem letter). Fitted on rated problems."""
    group_mean: dict
    group_log: dict
    slope: float
    global_by_letter: dict

    def predict(self, kind: str, idx: str, solved_count: int | None) -> int | None:
        g = (kind, _letter(idx))
        if g in self.group_mean:
            r = self.group_mean[g]
            if solved_count is not None:
                r += self.slope * (math.log1p(solved_count) - self.group_log[g])
        elif _letter(idx) in self.global_by_letter:
            r = self.global_by_letter[_letter(idx)]
        else:
            return None
        return int(min(3500, max(800, round(r / 100) * 100)))

    def expected_solved(self, kind: str, idx: str, rating: int) -> float | None:
        """Typical solve count for a problem of this rating in this contest slot."""
        g = (kind, _letter(idx))
        if g not in self.group_mean or self.slope >= 0:
            return None
        return math.expm1(self.group_log[g] + (rating - self.group_mean[g]) / self.slope)

    def to_json(self) -> str:
        return json.dumps({"gm": [[k[0], k[1], v] for k, v in self.group_mean.items()],
                           "gl": [[k[0], k[1], v] for k, v in self.group_log.items()],
                           "slope": self.slope, "gbl": self.global_by_letter})

    @classmethod
    def from_json(cls, s: str) -> "UnratedModel":
        d = json.loads(s)
        return cls({(a, b): v for a, b, v in d["gm"]}, {(a, b): v for a, b, v in d["gl"]},
                   d["slope"], d["gbl"])


def fit_unrated_model(rows: list[dict]) -> UnratedModel | None:
    """rows: dicts with kind, idx, rating, solved_count (rated problems only)."""
    groups: dict = defaultdict(list)
    by_letter: dict = defaultdict(list)
    for r in rows:
        if r.get("rating") and r.get("solved_count") is not None:
            groups[(r["kind"], _letter(r["idx"]))].append((r["rating"], math.log1p(r["solved_count"])))
            by_letter[_letter(r["idx"])].append(r["rating"])
    groups = {g: v for g, v in groups.items() if len(v) >= 5}
    if not groups:
        return None
    gm = {g: sum(x for x, _ in v) / len(v) for g, v in groups.items()}
    gl = {g: sum(y for _, y in v) / len(v) for g, v in groups.items()}
    # Pooled within-group slope of rating on log(solved).
    num = den = 0.0
    for g, v in groups.items():
        for x, y in v:
            num += (y - gl[g]) * (x - gm[g])
            den += (y - gl[g]) ** 2
    slope = num / den if den else 0.0
    gbl = {k: sum(v) / len(v) for k, v in by_letter.items() if len(v) >= 5}
    return UnratedModel(gm, gl, slope, gbl)


def trickiness(rating: int | None, tags: list[str], residual: float = 0.0) -> float:
    """0..1. Higher = more likely to need a non-obvious idea.

    * tag prior: constructive / interactive / games etc.
    * 'no named algorithm' problems at 1400+ (tags only math/greedy/...)
    * residual: how much fewer people solved it than its group predicts
      (positive residual = rated harder than its solve count suggests is
      NOT tricky; negative = fewer solvers than expected = tricky)
    """
    tags = [t for t in tags if not t.startswith("*")]
    score = max([TRICKY_TAGS.get(t, 0.0) for t in tags] or [0.0]) * 0.5
    if rating and rating >= 1400 and tags and set(tags) <= OBSERVATION_TAGS:
        score += 0.3
    score += max(0.0, min(0.3, -residual / 400 * 0.3))
    return round(min(1.0, score), 3)


# ---------------------------------------------------------------------------
# Personal difficulty: how a solve actually went for *you*.
# ---------------------------------------------------------------------------

@dataclass
class Outcome:
    pid: str
    rating: int | None
    tags: list[str]
    solved: bool
    first_time: int            # first submission (unix)
    solve_time: int | None     # first AC (unix)
    wrong: int                 # rejected submissions before first AC (or total if unsolved)
    in_contest: bool           # solved/attempted live (CONTESTANT) or VIRTUAL
    minutes: float | None      # contest minutes or logged/timer minutes
    editorial: bool

    @property
    def quality(self) -> float:
        """Graded outcome in [0, 1] used by the skill model."""
        if not self.solved:
            return 0.0
        if self.editorial:
            return 0.25
        q = 1.0
        if self.wrong >= 5:
            q = 0.6
        elif self.wrong >= 2:
            q = 0.8
        if self.minutes is not None:
            if self.minutes > 90:
                q = min(q, 0.6)
            elif self.minutes > 45:
                q = min(q, 0.8)
        return q

    @property
    def grade(self) -> str:
        if not self.solved:
            return "unsolved"
        if self.editorial:
            return "editorial"
        q = self.quality
        return "clean" if q >= 1.0 else ("struggled" if q >= 0.8 else "hard-fought")


IGNORED_VERDICTS = {"COMPILATION_ERROR", "SKIPPED", "TESTING", "PARTIAL", None}
