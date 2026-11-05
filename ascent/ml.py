"""The trained part of the brain. Pure Python, no dependencies.

Two models, both trained during every build on REAL data, both evaluated on
held-out data so the site can show measured accuracy (not claimed accuracy):

1. RatingModel: predicts a Codeforces problem's difficulty rating from what is
   known about it: contest type, problem letter, how many people solved it,
   contest age and tags. Ridge regression. Trained on every officially-rated
   problem, evaluated on held-out *contests* (no leakage between problems of
   the same round), compared against the simple group-mean baseline. Used for
   problems Codeforces has not rated yet.

2. PersonalModel: predicts YOUR probability of solving a problem cleanly
   (no editorial, <= 3 wrong attempts, reasonable time). Logistic regression on
   your own attempts. Features: rating above your level, your skill in the
   problem's topics, trickiness, popularity. Evaluated on your most recent 25%
   of attempts (time split: it only sees the past), compared against the plain
   Elo formula and against always guessing your base rate.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field

from . import skill as skill_mod
from .difficulty import Outcome, fit_unrated_model

# ---------------------------------------------------------------------------
# Linear algebra helpers (small dense systems)
# ---------------------------------------------------------------------------


def solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            continue
        m[c], m[p] = m[p], m[c]
        piv = m[c][c]
        for k in range(c, n + 1):
            m[c][k] /= piv
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] for i in range(n)]


def ridge(rows: list[dict[str, float]], y: list[float], names: list[str], lam: float = 1.0) -> dict[str, float]:
    idx = {n: i for i, n in enumerate(names)}
    p = len(names)
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p
    for r, t in zip(rows, y):
        items = [(idx[k], v) for k, v in r.items() if k in idx]
        for i, vi in items:
            xty[i] += vi * t
            for j, vj in items:
                xtx[i][j] += vi * vj
    for i, n in enumerate(names):
        if n != "bias":
            xtx[i][i] += lam
    beta = solve(xtx, xty)
    return dict(zip(names, beta))


def dot(w: dict[str, float], x: dict[str, float]) -> float:
    return sum(w.get(k, 0.0) * v for k, v in x.items())


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def logistic(rows: list[dict[str, float]], y: list[int], names: list[str], lam: float = 1.0,
             iters: int = 25) -> dict[str, float]:
    """L2-regularised logistic regression by Newton's method."""
    idx = {n: i for i, n in enumerate(names)}
    p = len(names)
    w = [0.0] * p
    X = [[r.get(n, 0.0) for n in names] for r in rows]
    for _ in range(iters):
        g = [0.0] * p
        h = [[0.0] * p for _ in range(p)]
        for x, t in zip(X, y):
            z = sum(wi * xi for wi, xi in zip(w, x))
            pr = sigmoid(z)
            d = pr - t
            s = pr * (1 - pr)
            for i in range(p):
                if x[i]:
                    g[i] += d * x[i]
                    for j in range(p):
                        if x[j]:
                            h[i][j] += s * x[i] * x[j]
        for i, n in enumerate(names):
            if n != "bias":
                g[i] += lam * w[i]
                h[i][i] += lam
            h[i][i] += 1e-9
        step = solve(h, g)
        w = [wi - si for wi, si in zip(w, step)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return dict(zip(names, w))


# ---------------------------------------------------------------------------
# 1. Rating model
# ---------------------------------------------------------------------------

KINDS = ["div1", "div2", "div3", "div4", "edu", "global", "div12", "other"]


def _letter_rank(idx: str) -> int:
    return min(7, ord((idx or "A")[0]) - ord("A"))


def rating_features(kind: str, idx: str, solved: int | None, start_time: int | None, tags: list[str],
                    tag_vocab: list[str]) -> dict[str, float]:
    ls = math.log1p(solved or 0)
    lr = _letter_rank(idx)
    years = ((start_time or 1.6e9) - 1.42e9) / (365.25 * 86400)  # years since 2015
    x = {"bias": 1.0, f"kind={kind}": 1.0, f"letter={lr}": 1.0, "logsolved": ls,
         f"logsolved*kind={kind}": ls, "logsolved*letter": ls * lr / 7, "years": years,
         "years*logsolved": years * ls / 10, "ntags": len([t for t in tags if not t.startswith("*")])}
    for t in tags:
        if t in tag_vocab:
            x[f"tag={t}"] = 1.0
    return x


@dataclass
class RatingModel:
    weights: dict
    tag_vocab: list
    metrics: dict = field(default_factory=dict)

    def predict(self, kind, idx, solved, start_time, tags) -> int:
        r = dot(self.weights, rating_features(kind, idx, solved, start_time, tags, self.tag_vocab))
        return int(min(3500, max(800, round(r / 100) * 100)))

    def to_json(self) -> str:
        return json.dumps({"w": self.weights, "tags": self.tag_vocab, "metrics": self.metrics})

    @classmethod
    def from_json(cls, s: str) -> "RatingModel":
        d = json.loads(s)
        return cls(d["w"], d["tags"], d.get("metrics", {}))


def _names(rows):
    names = sorted({k for r in rows for k in r})
    return ["bias"] + [n for n in names if n != "bias"]


def train_rating_model(problems: list[dict], test_mod: int = 5) -> RatingModel | None:
    """problems: dicts with kind, idx, rating, solved_count, start_time, tags (list).
    Evaluation holds out every contest with contest_id % test_mod == 0."""
    rated = [p for p in problems if p.get("rating") and p.get("solved_count") is not None]
    if len(rated) < 200:
        return None
    tag_counts: dict[str, int] = {}
    for p in rated:
        for t in p["tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    vocab = sorted(t for t, c in tag_counts.items() if c >= 30)

    def feats(ps):
        return [rating_features(p["kind"], p["idx"], p["solved_count"], p.get("start_time"), p["tags"], vocab) for p in ps]

    train = [p for p in rated if p["contest_id"] % test_mod != 0]
    test = [p for p in rated if p["contest_id"] % test_mod == 0]
    metrics = {}
    if len(train) >= 100 and len(test) >= 50:
        Xtr = feats(train)
        w = ridge(Xtr, [p["rating"] for p in train], _names(Xtr), lam=3.0)
        m = RatingModel(w, vocab)
        base = fit_unrated_model(train)
        err, err_b, within, within_b = [], [], 0, 0
        for p in test:
            pr = m.predict(p["kind"], p["idx"], p["solved_count"], p.get("start_time"), p["tags"])
            pb = base.predict(p["kind"], p["idx"], p["solved_count"]) if base else None
            pb = pb if pb is not None else 1500
            err.append(abs(pr - p["rating"]))
            err_b.append(abs(pb - p["rating"]))
            within += abs(pr - p["rating"]) <= 200
            within_b += abs(pb - p["rating"]) <= 200
        n = len(test)
        metrics = {"test_problems": n, "train_problems": len(train),
                   "mae": round(sum(err) / n, 1), "baseline_mae": round(sum(err_b) / n, 1),
                   "within_200": round(within / n, 3), "baseline_within_200": round(within_b / n, 3),
                   "split": f"held-out contests (contest id % {test_mod} == 0)"}
    X = feats(rated)
    w = ridge(X, [p["rating"] for p in rated], _names(X), lam=3.0)
    return RatingModel(w, vocab, metrics)


# ---------------------------------------------------------------------------
# 2. Personal solve model
# ---------------------------------------------------------------------------

PERSONAL_FEATURES = ["bias", "delta", "tag_gap", "trick", "pop", "live"]


def personal_features(rating: int, tags: list[str], trick: float | None, solved_count: int | None,
                      level: float, overall_mean: float, tag_means: dict[str, float], live: bool = False) -> dict:
    real = [t for t in tags if not t.startswith("*") and t in tag_means]
    gap = sum(tag_means[t] - overall_mean for t in real) / len(real) / 100 if real else 0.0
    return {"bias": 1.0, "delta": (rating - level) / 100, "tag_gap": gap, "trick": trick or 0.0,
            "pop": (math.log1p(solved_count or 0) - 8) / 2, "live": 1.0 if live else 0.0}


@dataclass
class PersonalModel:
    weights: dict | None
    metrics: dict

    def p(self, x: dict) -> float | None:
        return sigmoid(dot(self.weights, x)) if self.weights else None


def _brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ys)


def _logloss(ps, ys):
    e = 1e-6
    return -sum(y * math.log(max(e, p)) + (1 - y) * math.log(max(e, 1 - p)) for p, y in zip(ps, ys)) / len(ys)


def train_personal_model(outcomes: list[Outcome], extra: dict[str, dict], *, contest_rating, n_contests,
                         practice_discount: int, half_life_days: float, min_attempts: int = 80) -> PersonalModel:
    """extra: pid -> {trick, solved_count}. Labels: clean solve (quality >= 0.8)."""
    obs = sorted([o for o in outcomes if o.rating], key=lambda o: o.first_time)
    if len(obs) < min_attempts:
        return PersonalModel(None, {"status": f"needs {min_attempts} rated attempts, have {len(obs)}",
                                    "attempts": len(obs)})

    def skills_at(train, now):
        ov = skill_mod.overall(train, contest_rating=contest_rating, n_contests=n_contests,
                               practice_discount=practice_discount, half_life_days=half_life_days, now=now)
        tags = sorted({t for o in train for t in o.tags if not t.startswith("*")})
        tg = skill_mod.by_tag(train, tags, ov, practice_discount=practice_discount,
                              half_life_days=half_life_days, now=now)
        return ov, {t: e.mean for t, e in tg.items()}

    def rows_for(os_, ov, tm):
        rows, ys = [], []
        for o in os_:
            e = extra.get(o.pid, {})
            rows.append(personal_features(o.rating, o.tags, e.get("trick"), e.get("solved_count"),
                                          ov.mean, ov.mean, tm, o.in_contest))
            ys.append(1 if o.quality >= 0.8 else 0)
        return rows, ys

    cut = int(len(obs) * 0.75)
    train, test = obs[:cut], obs[cut:]
    split_time = test[0].first_time
    ov, tm = skills_at(train, split_time)
    Xtr, ytr = rows_for(train, ov, tm)
    metrics: dict = {"attempts": len(obs), "train": len(train), "test": len(test),
                     "base_rate": round(sum(ytr) / len(ytr), 3), "split": "time: last 25% of attempts"}
    if 0 < sum(ytr) < len(ytr):
        w = logistic(Xtr, ytr, PERSONAL_FEATURES, lam=1.0)
        Xte, yte = rows_for(test, ov, tm)
        pm = [sigmoid(dot(w, x)) for x in Xte]
        pe = [skill_mod.p_solve(ov.mean, o.rating - (0 if o.in_contest else practice_discount)) for o in test]
        pb = [metrics["base_rate"]] * len(yte)
        metrics.update({
            "brier": round(_brier(pm, yte), 4), "brier_elo": round(_brier(pe, yte), 4),
            "brier_base_rate": round(_brier(pb, yte), 4), "logloss": round(_logloss(pm, yte), 4),
            "accuracy": round(sum((p >= 0.5) == bool(y) for p, y in zip(pm, yte)) / len(yte), 3),
            "test_clean_rate": round(sum(yte) / len(yte), 3)})
    # Deploy: refit on everything with current skills.
    now = time.time()
    ov_all, tm_all = skills_at(obs, now)
    Xall, yall = rows_for(obs, ov_all, tm_all)
    if not (0 < sum(yall) < len(yall)):
        metrics["status"] = "all attempts have the same outcome; cannot fit"
        return PersonalModel(None, metrics)
    metrics["status"] = "trained"
    return PersonalModel(logistic(Xall, yall, PERSONAL_FEATURES, lam=1.0), metrics)
