"""Skill estimation.

Model: the Codeforces rating definition. A participant rated R solves a problem
rated D in contest with probability

    p(R, D) = 1 / (1 + 10 ** ((D - R) / 400))

Each attempted problem is an observation with a graded outcome y in [0, 1]
(see difficulty.Outcome.quality). Practice solves are converted to
contest-equivalent difficulty D - practice_discount, because a problem without a
clock is genuinely easier. Old evidence decays with a half-life. The posterior
over R is computed on a grid with a Gaussian prior centred on your official
contest rating (when you have one).

Why this does not inflate on easy problems. A plain logistic model has a known
flaw: hundreds of solves with zero failures keep pushing the estimate upward,
because nobody attempts (and fails) problems far above them. So the *success*
term of the likelihood is capped: a solve of a D-rated problem is evidence that
R is at least about D + SOLVE_CEILING, and says nothing about whether R is 200 or
1000 above that. Failures use the full curve and pull the estimate down.
Result: solving 300 problems rated 800 does NOT make you 1600. Only solving
problems near and above your level raises the estimate (see tests/test_skill.py).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .difficulty import Outcome

GRID = list(range(600, 3601, 10))
SOLVE_CEILING = 200  # a solve at D is informative only up to R = D + 200


def p_solve(r: float, d: float) -> float:
    return 1.0 / (1.0 + 10 ** ((d - r) / 400))


@dataclass
class Estimate:
    mean: float
    sd: float
    evidence: float          # effective number of observations

    @property
    def low(self) -> float:   # conservative (mean - 1 sd)
        return self.mean - self.sd

    def __str__(self) -> str:
        return f"{self.mean:.0f} ± {self.sd:.0f}"


def observations(outcomes: list[Outcome], *, practice_discount: int, half_life_days: float,
                 now: float | None = None, tag: str | None = None) -> list[tuple[float, float, float]]:
    """(effective difficulty, y, weight) per outcome."""
    now = now or time.time()
    obs = []
    for o in outcomes:
        if not o.rating:
            continue
        if tag is not None and tag not in o.tags:
            continue
        d = o.rating - (0 if o.in_contest else practice_discount)
        age_days = max(0.0, (now - (o.solve_time or o.first_time)) / 86400)
        w = 0.5 ** (age_days / half_life_days)
        w *= 1.5 if o.in_contest else 1.0
        if tag is not None:  # a problem with many tags is weaker evidence per tag
            n = max(1, len([t for t in o.tags if not t.startswith("*")]))
            w /= math.sqrt(n)
        obs.append((d, o.quality, w))
    return obs


def posterior(obs: list[tuple[float, float, float]], prior_mean: float, prior_sd: float) -> Estimate:
    logp = []
    for r in GRID:
        lp = -((r - prior_mean) ** 2) / (2 * prior_sd ** 2)
        for d, y, w in obs:
            if y > 0:
                ps_ = min(1 - 1e-9, max(1e-9, p_solve(min(r, d + SOLVE_CEILING), d)))
                lp += w * y * math.log(ps_)
            if y < 1:
                pf = min(1 - 1e-9, max(1e-9, p_solve(r, d)))
                lp += w * (1 - y) * math.log(1 - pf)
        logp.append(lp)
    m = max(logp)
    ps = [math.exp(v - m) for v in logp]
    z = sum(ps)
    mean = sum(r * p for r, p in zip(GRID, ps)) / z
    var = sum((r - mean) ** 2 * p for r, p in zip(GRID, ps)) / z
    return Estimate(mean, math.sqrt(var), sum(w for _, _, w in obs))


def overall(outcomes: list[Outcome], *, contest_rating: int | None, n_contests: int,
            practice_discount: int, half_life_days: float, now: float | None = None) -> Estimate:
    if contest_rating and n_contests >= 6:
        prior = (contest_rating, 200.0)
    elif contest_rating:
        prior = (contest_rating, 300.0)
    else:
        prior = (1000.0, 400.0)
    obs = observations(outcomes, practice_discount=practice_discount,
                       half_life_days=half_life_days, now=now)
    return posterior(obs, *prior)


def by_tag(outcomes: list[Outcome], tags: list[str], base: Estimate, *, practice_discount: int,
           half_life_days: float, now: float | None = None) -> dict[str, Estimate]:
    """Per-tag skill, shrunk towards the overall estimate (prior sd 200)."""
    out = {}
    for t in tags:
        obs = observations(outcomes, practice_discount=practice_discount,
                           half_life_days=half_life_days, now=now, tag=t)
        out[t] = posterior(obs, base.mean, 200.0)
    return out


def frontier(outcomes: list[Outcome], *, window_days: int = 120, min_attempts: int = 5,
             now: float | None = None) -> int | None:
    """Highest 100-wide rating band where, in the window, you attempted at least
    `min_attempts` problems and solved >= 50% of them cleanly (quality >= 0.8).
    A blunt, model-free sanity check on the posterior."""
    now = now or time.time()
    bands: dict[int, list[float]] = {}
    for o in outcomes:
        if o.rating and now - o.first_time <= window_days * 86400:
            bands.setdefault(o.rating // 100 * 100, []).append(1.0 if o.quality >= 0.8 else 0.0)
    good = [b for b, v in bands.items() if len(v) >= min_attempts and sum(v) / len(v) >= 0.5]
    return max(good) if good else None
