"""Pull real data from Codeforces / LeetCode / zerotrac into the local DB."""
from __future__ import annotations

import json
import math
import sqlite3
import time

from . import db, difficulty, ml
from .config import Config
from .sources import codeforces as cf
from .sources import leetcode as lc

DAY = 86400


def refresh_catalog(conn: sqlite3.Connection, log=print) -> None:
    """Codeforces problem set + contests, plus derived estimates/trickiness."""
    log("Fetching Codeforces contest list ...")
    contests = cf.contests()
    db.upsert_many(conn, "contests", ({
        "id": c["id"], "name": c["name"], "kind": cf.contest_kind(c["name"]),
        "start_time": c.get("startTimeSeconds"), "duration": c.get("durationSeconds")} for c in contests))
    kinds = {c["id"]: cf.contest_kind(c["name"]) for c in contests}
    starts = {c["id"]: c.get("startTimeSeconds") for c in contests}

    log("Fetching Codeforces problem set ...")
    problems, stats = cf.problemset()
    solved = {(s["contestId"], s["index"]): s["solvedCount"] for s in stats}
    rows = []
    for p in problems:
        cid = p.get("contestId")
        if cid is None or cid >= 100000:
            continue
        rows.append({
            "pid": f"CF:{cid}{p['index']}", "platform": "CF", "contest_id": cid, "idx": p["index"],
            "name": p["name"], "rating": p.get("rating"),
            "rating_source": "official" if p.get("rating") else None,
            "tags": json.dumps(p.get("tags", [])), "solved_count": solved.get((cid, p["index"])),
            "lc_difficulty": None, "url": f"https://codeforces.com/problemset/problem/{cid}/{p['index']}",
            "trick": None, "kind": kinds.get(cid, "other")})

    model = difficulty.fit_unrated_model([r for r in rows if r["rating"]])
    if model:
        db.set_meta(conn, "unrated_model", model.to_json())

    log("Training rating model (held-out evaluation) ...")
    rm = ml.train_rating_model([{**r, "tags": json.loads(r["tags"]), "start_time": starts.get(r["contest_id"])}
                                for r in rows])
    use_ml = bool(rm and rm.metrics and rm.metrics["mae"] < rm.metrics["baseline_mae"])
    if rm:
        rm.metrics["used_for_estimates"] = use_ml
        db.set_meta(conn, "rating_model", rm.to_json())
        if rm.metrics:
            log(f"  held-out MAE {rm.metrics['mae']} (baseline {rm.metrics['baseline_mae']}) on "
                f"{rm.metrics['test_problems']} problems; within 200: {rm.metrics['within_200']:.0%}")
    for r in rows:
        kind = r.pop("kind")
        resid = 0.0
        if model and r["rating"] and r["solved_count"] is not None:
            pred = model.predict(kind, r["idx"], r["solved_count"])
            resid = (r["rating"] - pred) if pred else 0.0
        elif not r["rating"]:
            est = None
            if use_ml:
                est = rm.predict(kind, r["idx"], r["solved_count"], starts.get(r["contest_id"]), json.loads(r["tags"]))
            elif model:
                est = model.predict(kind, r["idx"], r["solved_count"])
            if est:
                r["rating"], r["rating_source"] = est, "estimated"
        r["trick"] = difficulty.trickiness(r["rating"], json.loads(r["tags"]), resid)
    db.upsert_many(conn, "problems", rows)
    db.set_meta(conn, "catalog_at", int(time.time()))
    conn.commit()
    log(f"  {len(rows)} problems, {sum(1 for r in rows if r['rating_source'] == 'estimated')} with estimated ratings")


def sync_cf(conn: sqlite3.Connection, cfg: Config, *, refresh: bool = False, log=print) -> None:
    if not cfg.cf_handle:
        return
    last = int(db.get_meta(conn, "catalog_at", "0"))
    if refresh or time.time() - last > DAY:
        refresh_catalog(conn, log)

    log(f"Fetching submissions for {cfg.cf_handle} ...")
    known = {int(r["sid"][3:]) for r in conn.execute("SELECT sid FROM submissions WHERE platform='CF'")}
    subs = cf.user_status(cfg.cf_handle, known_ids=known)
    rows, probs = [], []
    for s in subs:
        p = s["problem"]
        cid = p.get("contestId")
        if cid is None or cid >= 100000:
            continue
        pid = f"CF:{cid}{p['index']}"
        rel = s.get("relativeTimeSeconds")
        rows.append({"sid": f"CF:{s['id']}", "platform": "CF", "pid": pid, "time": s["creationTimeSeconds"],
                     "verdict": s.get("verdict"), "participant_type": s["author"].get("participantType"),
                     "relative_time": rel if rel is not None and rel < 10 ** 8 else None,
                     "language": s.get("programmingLanguage")})
        probs.append((pid, cid, p["index"], p.get("name"), p.get("rating"),
                      "official" if p.get("rating") else None, json.dumps(p.get("tags", [])),
                      f"https://codeforces.com/problemset/problem/{cid}/{p['index']}"))
    db.upsert_many(conn, "submissions", rows)
    conn.executemany("INSERT OR IGNORE INTO problems(pid, platform, contest_id, idx, name, rating, rating_source,"
                     " tags, url) VALUES (?, 'CF', ?, ?, ?, ?, ?, ?, ?)", probs)
    log(f"  {len(rows)} submissions ({len(rows) - len(known & {int(r['sid'][3:]) for r in rows})} new)")

    log("Fetching rating history ...")
    hist = cf.user_rating(cfg.cf_handle)
    db.upsert_many(conn, "rating_history", ({
        "platform": "CF", "contest_id": str(h["contestId"]), "contest_name": h["contestName"],
        "time": h["ratingUpdateTimeSeconds"], "old_rating": h["oldRating"], "new_rating": h["newRating"],
        "rank": h["rank"]} for h in hist))
    conn.commit()
    log(f"  {len(hist)} rated contests")


def sync_lc(conn: sqlite3.Connection, cfg: Config, *, refresh: bool = False, log=print) -> None:
    last = int(db.get_meta(conn, "zerotrac_at", "0"))
    if refresh or time.time() - last > 7 * DAY:
        log("Fetching zerotrac LeetCode problem ratings ...")
        zr = lc.zerotrac_ratings()
        conn.executemany(
            """INSERT INTO problems(pid, platform, contest_id, idx, name, rating, rating_source, url)
               VALUES (?, 'LC', ?, ?, ?, ?, 'zerotrac', ?)
               ON CONFLICT(pid) DO UPDATE SET rating=excluded.rating, rating_source='zerotrac',
                 name=excluded.name, contest_id=excluded.contest_id, idx=excluded.idx""",
            [(f"LC:{z['slug']}", int(z["id"]) if z["id"].isdigit() else None, z["index"], z["title"],
              int(round(z["rating"])), f"https://leetcode.com/problems/{z['slug']}/") for z in zr])
        db.set_meta(conn, "zerotrac_at", int(time.time()))
        conn.commit()
        log(f"  {len(zr)} rated LeetCode problems")
    if not cfg.lc_handle:
        return
    # Each part can fail on its own (LeetCode sometimes refuses automated
    # requests); one failure must not hide the others.
    errors = []
    log(f"Fetching LeetCode data for {cfg.lc_handle} ...")
    try:
        prof = lc.profile_summary(cfg.lc_handle)
        db.set_meta(conn, "lc_profile", json.dumps(prof))
        log(f"  profile: {prof['solved'].get('All', 0)} solved, contest rating {prof['contest_rating'] or 'none'}")
    except Exception as e:  # noqa: BLE001 - recorded and shown on the site
        errors.append(f"profile: {e}")
    try:
        hist = lc.contest_history(cfg.lc_handle)
        prev = 1500.0  # LeetCode's starting contest rating
        rows = []
        for h in hist:
            rows.append({"platform": "LC", "contest_id": h["contest"]["title"], "contest_name": h["contest"]["title"],
                         "time": h["contest"]["startTime"], "old_rating": int(round(prev)),
                         "new_rating": int(round(h["rating"])), "rank": h.get("ranking")})
            prev = h["rating"]
        db.upsert_many(conn, "rating_history", rows)
        log(f"  {len(hist)} LeetCode contests")
    except Exception as e:  # noqa: BLE001
        errors.append(f"contest history: {e}")
    try:
        seen = {r["sid"] for r in conn.execute("SELECT sid FROM submissions WHERE platform='LC'")}
        new = 0
        for s in lc.recent_accepted(cfg.lc_handle):
            if f"LC:{s['id']}" not in seen:
                db.journal(conn, {"type": "lc_ac", "sid": s["id"], "pid": f"LC:{s['titleSlug']}",
                                  "title": s["title"], "at": int(s["timestamp"])})
                new += 1
        log(f"  {new} new accepted problems journaled")
    except Exception as e:  # noqa: BLE001
        errors.append(f"recent accepted: {e}")
    conn.commit()
    if errors:
        parts = [e.split(": ", 1) for e in errors]
        msgs = {m for _, m in parts}
        if len(msgs) == 1:  # same root cause everywhere: say it once
            raise RuntimeError(f"{', '.join(w for w, _ in parts)}: {msgs.pop()}")
        raise RuntimeError("; ".join(errors))


def update_reviews(conn: sqlite3.Connection, outcomes, level: int) -> int:
    """Queue spaced-repetition re-solves for problems that didn't go cleanly."""
    have = {r["pid"] for r in conn.execute("SELECT pid FROM reviews")}
    added = 0
    for o in outcomes:
        if o.pid in have or not o.rating or o.rating < level - 200:
            continue
        if o.solved and o.quality < 0.8:
            reason, base = f"solved but {o.grade}", o.solve_time
        elif not o.solved:
            reason, base = "attempted, not solved", o.first_time
        else:
            continue
        conn.execute("INSERT INTO reviews(pid, stage, due_at, reason) VALUES (?, 0, ?, ?)",
                     (o.pid, base + 7 * DAY, reason))
        added += 1
    conn.commit()
    return added


def expected_solved(conn: sqlite3.Connection, pid: str) -> float | None:
    raw = db.get_meta(conn, "unrated_model")
    row = conn.execute("SELECT p.idx, p.rating, c.kind FROM problems p LEFT JOIN contests c ON c.id=p.contest_id"
                       " WHERE p.pid=?", (pid,)).fetchone()
    if not raw or not row or not row["rating"]:
        return None
    v = difficulty.UnratedModel.from_json(raw).expected_solved(row["kind"] or "other", row["idx"], row["rating"])
    return v if v and math.isfinite(v) else None
