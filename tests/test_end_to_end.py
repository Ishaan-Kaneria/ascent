"""Full pipeline on synthetic API data: sync -> state -> recommend -> readiness -> dashboard."""
import json
import time

from ascent import db, readiness, sheets, sync
from ascent.config import Config
from ascent.dashboard import build_data, render
from ascent.recommend import recommend
from ascent.state import load

from .conftest import easy_history, submission


def setup(home, fake_cf):
    cfg = Config(cf_handle="test_user")
    cfg.save()
    conn = db.connect()
    sync.sync_cf(conn, cfg, refresh=True, log=lambda *_: None)
    return cfg, conn


def test_unrated_problems_get_labelled_estimates(home, fake_cf):
    cfg, conn = setup(home, fake_cf)
    rows = conn.execute("SELECT * FROM problems WHERE rating_source='estimated'").fetchall()
    assert len(rows) == 18  # 3 newest contests x 6 problems
    for r in rows:
        assert 800 <= r["rating"] <= 3500 and r["rating"] % 100 == 0
    a = {r["idx"]: r["rating"] for r in rows if r["contest_id"] == rows[0]["contest_id"]}
    assert a["A"] < a["D"]  # later problems estimated harder


def test_easy_only_user_is_not_ready_and_gets_harder_problems(home, fake_cf):
    easy_history(fake_cf)
    cfg, conn = setup(home, fake_cf)
    st = load(conn, cfg)
    assert len(st.solved) >= 100
    level = st.level()
    assert level < 1250, f"easy-only history inflated level to {level}"

    gates = readiness.cf_gates(st, 1600)
    assert not all(g.passed for g in gates)
    assert readiness.verdict(gates).startswith("NOT READY")
    # Not even Pupil-ready from easy volume alone
    assert not all(g.passed for g in readiness.cf_gates(st, 1200))

    recs = recommend(conn, st, 10, seed=1)
    assert recs
    for r in recs:
        assert r.rating >= level, "never below your level"
        assert r.pid not in st.solved
    assert len({r.pid.split(':')[1].rstrip('ABCDEF') for r in recs}) == len(recs), "one per contest"
    assert sum(1 for r in recs if r.rating >= level + 100) >= len(recs) * 0.7


def test_recommendation_never_suggests_special(home, fake_cf):
    p = fake_cf["problems"][-30]
    p["tags"] = ["*special"]
    fake_cf["contests"].append({"id": 99999, "name": "April Fools Day Contest", "phase": "FINISHED"})
    cfg, conn = setup(home, fake_cf)
    st = load(conn, cfg)
    for mode in ("core", "stretch", "weak", "tricky"):
        for r in recommend(conn, st, 20, mode=mode, seed=3):
            assert "*special" not in r.tags


def test_contest_timing_uses_gap_between_solves(home, fake_cf):
    now = int(time.time())
    probs = [p for p in fake_cf["problems"] if p["contestId"] == 1600]
    fake_cf["subs"] = [submission(1, probs[0], now - 5000, ptype="CONTESTANT", rel=600),
                       submission(2, probs[1], now - 4000, ptype="CONTESTANT", rel=1800),
                       submission(3, probs[2], now - 3000, "WRONG_ANSWER", ptype="CONTESTANT", rel=4000),
                       submission(4, probs[2], now - 2000, ptype="CONTESTANT", rel=4800)]
    cfg, conn = setup(home, fake_cf)
    st = load(conn, cfg)
    o = st.outcomes["CF:1600C"]
    assert o.in_contest and o.wrong == 1
    assert abs(o.minutes - 50) < 0.01  # (4800 - 1800) / 60, not 80 from contest start


def test_journal_rebuild_roundtrip(home, fake_cf):
    cfg, conn = setup(home, fake_cf)
    db.journal(conn, {"type": "timer_start", "pid": "CF:1600C", "at": 100})
    db.journal(conn, {"type": "attempt", "pid": "CF:1600C", "started_at": 100, "finished_at": 2500,
                      "minutes": 40, "editorial": True, "solved": True})
    db.journal(conn, {"type": "sheet_import", "name": "mine", "items": sheets.parse("1600C\n1601D\n")})
    conn.commit()
    before = load(conn, cfg).outcomes["CF:1600C"]
    conn.close()
    from ascent.config import db_path
    db_path().unlink()
    conn = db.connect()
    assert db.replay_journal(conn) == 3
    sync.sync_cf(conn, cfg, log=lambda *_: None)
    after = load(conn, cfg).outcomes["CF:1600C"]
    assert after.editorial and after.minutes == 40 and before.editorial
    assert conn.execute("SELECT COUNT(*) FROM sheets WHERE name='mine'").fetchone()[0] == 2


def test_sheet_next_skips_below_level(home, fake_cf):
    easy_history(fake_cf)
    cfg, conn = setup(home, fake_cf)
    st = load(conn, cfg)
    easy = [p for p in fake_cf["problems"] if p.get("rating") == 800][-3:]
    hard = [p for p in fake_cf["problems"] if p.get("rating") == 1500][:2]
    text = "\n".join(f"{p['contestId']}{p['index']}" for p in easy + hard)
    db.journal(conn, {"type": "sheet_import", "name": "s", "items": sheets.parse(text)})
    items, skipped = sheets.next_items(conn, "s", st.solved, st.level(), 10)
    assert all(i["rating"] >= st.level() for i in items)
    assert skipped == sum(1 for p in easy if f"CF:{p['contestId']}{p['index']}" not in st.solved)


def test_reviews_and_dashboard(home, fake_cf):
    easy_history(fake_cf)
    now = int(time.time())
    hard = next(p for p in fake_cf["problems"] if p.get("rating") == 1300)
    fake_cf["subs"] += [submission(90_001, hard, now - 10 * 86400, "WRONG_ANSWER")]
    cfg, conn = setup(home, fake_cf)
    st = load(conn, cfg)
    assert sync.update_reviews(conn, st.cf_outcomes, st.level()) >= 1
    data = build_data(conn, st)
    page = render(data)
    assert "<script>" in page and "</script>" in page
    assert json.loads(json.dumps(data))["verdict"].startswith("NOT READY")
    assert len(data["reviews"]) >= 1


def test_dashboard_writes_data_json_and_fingerprint_tracks_changes(home, fake_cf, capsys):
    from ascent.cli import main
    easy_history(fake_cf)
    setup(home, fake_cf)
    main(["dashboard", "-o", str(home / "site" / "index.html")])
    data = json.loads((home / "site" / "data.json").read_text())
    info = json.loads((home / "site" / "build-info.json").read_text())
    assert data["generated_at"] == info["generated_at"] and data["handle"] == info["handle"] == "test_user"
    assert len(data["cf"]) > 1000
    capsys.readouterr()
    main(["fingerprint"]); a = capsys.readouterr().out.strip()
    main(["fingerprint"]); b = capsys.readouterr().out.strip()
    assert a == b and len(a) == 16
    conn = db.connect()
    conn.execute("INSERT INTO submissions VALUES ('CF:1', 'CF', 'CF:1600A', 1, 'OK', 'PRACTICE', NULL, NULL)")
    conn.commit()
    main(["fingerprint"]); c = capsys.readouterr().out.strip()
    assert c != a
