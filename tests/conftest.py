"""Test fixtures.

Everything here is SYNTHETIC data shaped exactly like the Codeforces API
responses (problemset.problems, contest.list, user.status, user.rating). It
exists only to test the logic offline; it is not anyone's real history.
"""
from __future__ import annotations

import random
import time

import pytest

LETTER_BASE = {"A": 900, "B": 1200, "C": 1500, "D": 1800, "E": 2100, "F": 2400}
TAG_POOL = ["greedy", "math", "dp", "constructive algorithms", "binary search", "number theory",
            "graphs", "dfs and similar", "trees", "data structures", "strings", "sortings",
            "two pointers", "bitmasks", "combinatorics", "implementation", "brute force", "dsu",
            "probabilities", "games", "interactive", "shortest paths", "hashing"]


def make_catalog(n_contests: int = 400, seed: int = 1):
    rng = random.Random(seed)
    contests, problems, stats = [], [], []
    for i in range(n_contests):
        cid = 1500 + i
        kind = ["Div. 2", "Div. 3", "Educational Codeforces Round", "Div. 1"][i % 4]
        name = f"Codeforces Round {i} ({kind})" if "Educational" not in kind else f"Educational Codeforces Round {i} (Rated for Div. 2)"
        contests.append({"id": cid, "name": name, "type": "CF", "phase": "FINISHED",
                         "durationSeconds": 7200, "startTimeSeconds": 1_600_000_000 + i * 86400})
        offset = {"Div. 2": 0, "Div. 3": -300, "Div. 1": 600}.get(kind, 0) if "Educational" not in kind else 0
        for letter, base in LETTER_BASE.items():
            r = max(800, min(3500, round((base + offset + rng.gauss(0, 150)) / 100) * 100))
            tags = rng.sample(TAG_POOL, rng.randint(1, 3))
            unrated = i >= n_contests - 3  # newest contests not yet rated
            p = {"contestId": cid, "index": letter, "name": f"Problem {cid}{letter}", "type": "PROGRAMMING", "tags": tags}
            if not unrated:
                p["rating"] = r
            problems.append(p)
            stats.append({"contestId": cid, "index": letter,
                          "solvedCount": int(30000 * 10 ** (-(r - 800) / 700) * rng.uniform(0.7, 1.3))})
    return contests, problems, stats


def submission(sid, problem, t, verdict="OK", ptype="PRACTICE", rel=2147483647):
    return {"id": sid, "contestId": problem["contestId"], "creationTimeSeconds": t,
            "relativeTimeSeconds": rel, "problem": problem,
            "author": {"participantType": ptype, "members": [{"handle": "test_user"}]},
            "programmingLanguage": "C++20 (GCC 13-64)", "verdict": verdict}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ASCENT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_cf(monkeypatch):
    """Patch the Codeforces client with synthetic data. Returns a mutable dict
    so tests can set the user's submissions / rating history."""
    from ascent.sources import codeforces as cf
    contests, problems, stats = make_catalog()
    state = {"contests": contests, "problems": problems, "stats": stats, "subs": [], "rating": []}
    monkeypatch.setattr(cf, "contests", lambda: state["contests"])
    monkeypatch.setattr(cf, "problemset", lambda: (state["problems"], state["stats"]))
    monkeypatch.setattr(cf, "user_status", lambda h, known_ids=None: list(reversed(state["subs"])))
    monkeypatch.setattr(cf, "user_rating", lambda h: state["rating"])
    return state


def easy_history(state, n=150, max_rating=1000, now=None):
    """A user who only ever solves easy problems: the case that must NOT be
    told they are ready."""
    now = now or time.time()
    easy = [p for p in state["problems"] if p.get("rating") and p["rating"] <= max_rating][:n]
    subs = [submission(10_000 + i, p, int(now - (n - i) * 3600)) for i, p in enumerate(easy)]
    state["subs"] = subs
    state["rating"] = [{"contestId": 1500 + i, "contestName": f"Round {i}", "handle": "test_user", "rank": 9000,
                        "ratingUpdateTimeSeconds": int(now - (12 - i) * 7 * 86400),
                        "oldRating": 0 if i == 0 else 950 + (i - 1) * 5, "newRating": 950 + i * 5} for i in range(12)]
    return easy
