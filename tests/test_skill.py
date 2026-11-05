import time

from ascent.difficulty import Outcome
from ascent.skill import frontier, overall

NOW = time.time()


def mk(r, solved=True, contest=False, wrong=0, i=0, editorial=False, minutes=None):
    return Outcome(f"CF:{1000 + i}A", r, ["greedy"], solved, NOW - 86400, NOW - 86400 if solved else None,
                   wrong, contest, minutes, editorial)


def est(outs, cr=1000, n=10):
    return overall(outs, contest_rating=cr, n_contests=n, practice_discount=250, half_life_days=90, now=NOW)


def test_easy_volume_does_not_inflate():
    """300 clean solves of 800s must not look like 1600. This is the core promise."""
    e = est([mk(800, i=i) for i in range(300)])
    assert e.mean < 1150
    assert e.low < 1100


def test_easy_volume_without_contests_stays_uncertain():
    e = est([mk(800, i=i) for i in range(300)], cr=None, n=0)
    assert e.mean < 1300 and e.sd > 200


def test_harder_solves_raise_estimate():
    base = est([mk(1000, i=i) for i in range(30)])
    harder = est([mk(1400, i=i) for i in range(30)])
    assert harder.mean > base.mean + 150


def test_failures_pull_down():
    good = est([mk(1400, i=i) for i in range(40)])
    with_fails = est([mk(1400, i=i) for i in range(40)] + [mk(1700, solved=False, i=100 + i) for i in range(20)])
    assert with_fails.mean < good.mean


def test_editorial_solves_count_little():
    clean = est([mk(1500, i=i) for i in range(30)])
    ed = est([mk(1500, editorial=True, i=i) for i in range(30)])
    assert ed.mean < clean.mean - 100


def test_contest_solves_worth_more_than_practice():
    practice = est([mk(1500, i=i) for i in range(20)])
    contest = est([mk(1500, contest=True, i=i) for i in range(20)])
    assert contest.mean > practice.mean


def test_quality_grades():
    assert mk(1500).quality == 1.0
    assert mk(1500, wrong=3).quality == 0.8
    assert mk(1500, wrong=6).quality == 0.6
    assert mk(1500, minutes=100).quality == 0.6
    assert mk(1500, editorial=True).quality == 0.25
    assert mk(1500, solved=False).quality == 0.0


def test_frontier():
    outs = [mk(1200, i=i) for i in range(6)] + [mk(1400, solved=False, i=50 + i) for i in range(6)]
    assert frontier(outs, now=NOW) == 1200
