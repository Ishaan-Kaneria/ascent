import json
import random
import time

from ascent import ml
from ascent.difficulty import Outcome

from .conftest import make_catalog


def test_solve_and_ridge_recover_coefficients():
    rng = random.Random(0)
    rows, y = [], []
    for _ in range(400):
        a, b = rng.uniform(-1, 1), rng.uniform(-1, 1)
        rows.append({"bias": 1.0, "a": a, "b": b})
        y.append(3 + 2 * a - 5 * b + rng.gauss(0, 0.01))
    w = ml.ridge(rows, y, ["bias", "a", "b"], lam=1e-6)
    assert abs(w["bias"] - 3) < 0.01 and abs(w["a"] - 2) < 0.01 and abs(w["b"] + 5) < 0.01


def test_logistic_learns_direction():
    rng = random.Random(1)
    rows, y = [], []
    for _ in range(600):
        x = rng.uniform(-3, 3)
        rows.append({"bias": 1.0, "x": x})
        y.append(1 if rng.random() < ml.sigmoid(2 * x - 0.5) else 0)
    w = ml.logistic(rows, y, ["bias", "x"], lam=0.1)
    assert 1.4 < w["x"] < 2.8 and -1.1 < w["bias"] < 0.1


def test_rating_model_trains_and_reports_held_out_metrics():
    contests, problems, stats = make_catalog()
    sc = {(s["contestId"], s["index"]): s["solvedCount"] for s in stats}
    kinds = {c["id"]: ("div3" if "Div. 3" in c["name"] else "div1" if "Div. 1" in c["name"]
                       else "edu" if "Educational" in c["name"] else "div2") for c in contests}
    starts = {c["id"]: c["startTimeSeconds"] for c in contests}
    rows = [{"contest_id": p["contestId"], "idx": p["index"], "rating": p.get("rating"), "kind": kinds[p["contestId"]],
             "solved_count": sc[(p["contestId"], p["index"])], "start_time": starts[p["contestId"]], "tags": p["tags"]}
            for p in problems]
    m = ml.train_rating_model(rows)
    assert m.metrics["test_problems"] > 100
    assert m.metrics["mae"] < 250
    restored = ml.RatingModel.from_json(m.to_json())
    assert restored.predict("div2", "C", 3000, starts[1600], ["dp"]) == m.predict("div2", "C", 3000, starts[1600], ["dp"])


def test_personal_model_beats_base_rate_on_learnable_history():
    rng = random.Random(3)
    now = time.time()
    outs = []
    for i in range(400):
        r = rng.choice(range(800, 2001, 100))
        p_clean = ml.sigmoid(-(r - 1250) / 120)
        clean = rng.random() < p_clean
        t = now - (400 - i) * 3600 * 6
        outs.append(Outcome(f"CF:{1000 + i}A", r, [rng.choice(["dp", "greedy", "math"])], clean or rng.random() < 0.3,
                            t, t if clean else None, 0 if clean else 6, False, None, False))
    m = ml.train_personal_model(outs, {}, contest_rating=1200, n_contests=10, practice_discount=250, half_life_days=90)
    assert m.metrics["status"] == "trained"
    assert m.metrics["brier"] < m.metrics["brier_base_rate"]
    assert m.weights["delta"] < 0  # harder relative to you -> less likely


def test_personal_model_refuses_with_too_little_data():
    m = ml.train_personal_model([], {}, contest_rating=None, n_contests=0, practice_discount=250, half_life_days=90)
    assert m.weights is None and "needs" in m.metrics["status"]
