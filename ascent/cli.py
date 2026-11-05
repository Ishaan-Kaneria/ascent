"""ascent: command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import analyzer, db, readiness, sheets, sync
from .config import Config, db_path, home, journal_path
from .dashboard import build_data, render
from .recommend import recommend, recommend_lc, tag_needs
from .sources.http import FetchError
from .state import TAG_TIERS, load


def _ctx():
    cfg = Config.load()
    conn = db.connect()
    return cfg, conn


def _norm_pid(ref: str) -> str:
    return sheets.to_pid(ref)[0]


def _table(rows: list[list], header: list[str]) -> str:
    rows = [[str(c) for c in r] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(header)]
    line = lambda r: "  ".join(c.ljust(w[i]) for i, c in enumerate(r))
    return "\n".join([line(header), line(["-" * x for x in w])] + [line(r) for r in rows])


# --------------------------------------------------------------------------

def cmd_init(a):
    cfg = Config.load()
    if a.cf is not None: cfg.cf_handle = a.cf
    if a.lc is not None: cfg.lc_handle = a.lc
    if a.target: cfg.target_rating = a.target
    if a.minutes: cfg.daily_minutes = a.minutes
    cfg.save()
    print(f"Saved {Config.path()}\n  Codeforces: {cfg.cf_handle or '-'}   LeetCode: {cfg.lc_handle or '-'}\n"
          f"  target {cfg.target_rating}, {cfg.daily_minutes} min/day\nNext: ascent sync")


def cmd_sync(a):
    cfg, conn = _ctx()
    if a.rebuild:
        conn.close()
        db_path().unlink(missing_ok=True)
        conn = db.connect()
        n = db.replay_journal(conn)
        conn.commit()
        print(f"Rebuilt database; replayed {n} journal events.")
    ok = cf_ok = True
    for name, fn in (("Codeforces", sync.sync_cf), ("LeetCode", sync.sync_lc)):
        if (a.only and a.only != name.lower()[:2]):
            continue
        try:
            fn(conn, cfg, refresh=a.refresh)
        except (FetchError, RuntimeError, KeyError) as e:
            ok = False
            cf_ok = cf_ok and name != "Codeforces"
            print(f"! {name} sync failed: {e}", file=sys.stderr)
    st = load(conn, cfg)
    added = sync.update_reviews(conn, st.cf_outcomes, st.level())
    if added:
        print(f"Queued {added} problems for spaced-repetition review.")
    print("Done." if ok else "Done, with errors above (data from the failed sources was not updated).")
    if not cf_ok and a.strict:
        sys.exit(1)


def cmd_stats(a):
    cfg, conn = _ctx()
    st = load(conn, cfg)
    ov = st.overall()
    cf = st.cf_outcomes
    solved = [o for o in cf if o.solved]
    now = time.time()
    print(f"Codeforces {cfg.cf_handle or '-'}: rating {st.cf_rating or '-'} (max {st.cf_max or '-'}), "
          f"{len(st.cf_history)} rated contests")
    if st.lc_rating:
        print(f"LeetCode {cfg.lc_handle}: contest rating {st.lc_rating:.0f}, {len(st.lc_history)} contests")
    print(f"Skill estimate (contest-equivalent): {ov}   training level: {st.level()}")
    for days in (7, 30, 90):
        recent = [o for o in solved if o.solve_time and now - o.solve_time <= days * 86400]
        rated = [o.rating for o in recent if o.rating]
        avg = sum(rated) / len(rated) if rated else 0
        hard = sum(1 for r in rated if r >= st.level() + 100)
        print(f"  last {days:>2}d: {len(recent):>4} solved, avg rating {avg:>5.0f}, {hard} above level")
    grades = {}
    for o in solved:
        grades[o.grade] = grades.get(o.grade, 0) + 1
    print("  solve quality: " + ", ".join(f"{k} {v}" for k, v in sorted(grades.items())))


def cmd_skill(a):
    cfg, conn = _ctx()
    st = load(conn, cfg)
    ov = st.overall()
    needs = tag_needs(st)
    rows = []
    for t, e in sorted(st.tag_skills().items(), key=lambda kv: kv[1].mean):
        unlock = TAG_TIERS[t][0]
        rows.append([t, f"{e.mean:.0f}", f"±{e.sd:.0f}", f"{e.evidence:.1f}", f"{e.mean - ov.mean:+.0f}",
                     unlock, f"{needs[t]:.2f}" if t in needs else "locked"])
    print(f"Overall: {ov}  (prior from contest rating {st.cf_rating or 'none'})\n")
    print(_table(rows, ["topic", "est", "sd", "evidence", "vs overall", "unlocks", "need"]))
    print("\n'need' drives recommendations: gap below overall + bonus for unexplored topics.")


def _print_recs(recs):
    for r in recs:
        est = " (est.)" if r.rating_source == "estimated" else ""
        print(f"[{r.bucket:7}] {r.pid[3:]:>7}  {r.rating}{est:7}  {r.name}")
        print(f"           {r.url}\n           why: {r.reason}; ~{r.est_minutes} min; tags: {', '.join(r.tags) or '-'}")


def cmd_recommend(a):
    cfg, conn = _ctx()
    st = load(conn, cfg)
    if a.lc:
        recs = recommend_lc(conn, st, a.n, seed=a.seed)
        if not recs:
            print("Needs a LeetCode contest rating (set --lc in init and sync) and the zerotrac catalog.")
        _print_recs(recs)
        return
    if conn.execute("SELECT COUNT(*) FROM problems WHERE platform='CF' AND rating IS NOT NULL").fetchone()[0] == 0:
        print("No Codeforces catalog yet. Run `ascent sync` first.")
        return
    print(f"Training level {st.level()} (skill {st.overall()}). Nothing below your level is suggested.\n")
    _print_recs(recommend(conn, st, a.n, mode=a.mode, tag=a.tag, seed=a.seed))


def cmd_today(a):
    cfg, conn = _ctx()
    st = load(conn, cfg)
    budget = a.minutes or cfg.daily_minutes
    due = conn.execute("SELECT r.pid, r.reason, p.name, p.url, p.rating FROM reviews r LEFT JOIN problems p ON p.pid=r.pid"
                       " WHERE due_at IS NOT NULL AND due_at <= ? ORDER BY due_at", (time.time(),)).fetchall()
    plan, used = [], 0
    if due:
        r = due[0]
        plan.append(("review", r["pid"], r["name"], r["rating"], r["url"], 30, r["reason"]))
        used += 30
    for rec in recommend(conn, st, 10, seed=a.seed):
        if used + rec.est_minutes > budget and plan:
            continue
        plan.append((rec.bucket, rec.pid, rec.name, rec.rating, rec.url, rec.est_minutes, rec.reason))
        used += rec.est_minutes
        if used >= budget:
            break
    print(f"Plan for {time.strftime('%a %d %b')}: {budget} min budget, level {st.level()}\n")
    for b, pid, name, rating, url, mins, why in plan:
        print(f"  [{b:7}] {pid[3:]:>7}  {rating or '-'}  {name}  (~{mins} min)\n            {url}\n            {why}")
    print("\nRules: start a timer (`ascent start ID`) BEFORE reading; 45+ min stuck -> one hint; "
          "only then the editorial, and log it with --editorial.")


def cmd_start(a):
    cfg, conn = _ctx()
    pid = _norm_pid(a.problem)
    db.journal(conn, {"type": "timer_start", "pid": pid, "at": int(time.time())})
    conn.commit()
    print(f"Timer started for {pid}. When done: ascent stop {a.problem} [--editorial] [--gave-up]")


def cmd_stop(a):
    cfg, conn = _ctx()
    pid = _norm_pid(a.problem)
    row = conn.execute("SELECT started_at FROM timers WHERE pid=?", (pid,)).fetchone()
    if not row:
        print(f"No running timer for {pid}. Use `ascent log {a.problem} --minutes N` instead.")
        return
    now = int(time.time())
    mins = round((now - row["started_at"]) / 60, 1)
    db.journal(conn, {"type": "attempt", "pid": pid, "started_at": row["started_at"], "finished_at": now,
                      "minutes": mins, "editorial": a.editorial, "solved": not a.gave_up, "notes": a.notes})
    conn.commit()
    print(f"Logged {pid}: {mins} min{', editorial' if a.editorial else ''}{', not solved' if a.gave_up else ''}.")


def cmd_log(a):
    cfg, conn = _ctx()
    pid = _norm_pid(a.problem)
    now = int(time.time())
    db.journal(conn, {"type": "attempt", "pid": pid, "started_at": None, "finished_at": now,
                      "minutes": a.minutes, "editorial": a.editorial, "solved": not a.unsolved, "notes": a.notes})
    conn.commit()
    print(f"Logged {pid}.")


def cmd_mark(a):
    cfg, conn = _ctx()
    pid = _norm_pid(a.problem)
    db.journal(conn, {"type": "mark_solved", "pid": pid, "at": int(time.time())})
    conn.commit()
    print(f"Marked {pid} solved.")


def cmd_review(a):
    cfg, conn = _ctx()
    if a.done:
        pid = _norm_pid(a.done)
        db.journal(conn, {"type": "review_done", "pid": pid, "clean": a.clean})
        conn.commit()
        print(f"Review recorded for {pid} ({'clean: next interval' if a.clean else 'not clean: same interval again'}).")
        return
    rows = conn.execute("SELECT r.*, p.name, p.url, p.rating FROM reviews r LEFT JOIN problems p ON p.pid=r.pid"
                        " WHERE due_at IS NOT NULL ORDER BY due_at").fetchall()
    now = time.time()
    if not rows:
        print("Review queue empty.")
    for r in rows:
        when = "DUE" if r["due_at"] <= now else time.strftime("%d %b", time.localtime(r["due_at"]))
        print(f"{when:>6}  {r['pid']:<12} {r['rating'] or '-':>5}  {r['name'] or ''}  [{r['reason']}]  {r['url'] or ''}")


def cmd_readiness(a):
    cfg, conn = _ctx()
    st = load(conn, cfg)
    if a.profile == "oa":
        gates, title = readiness.oa_gates(st), "Quant / OA profile"
    else:
        t = a.target or cfg.target_rating
        gates, title = readiness.cf_gates(st, t), f"Codeforces {t}"
    print(f"{title}\n{readiness.verdict(gates)}\n")
    for g in gates:
        print(f"{'PASS' if g.passed else 'FAIL'}  {g.name}\n      have: {g.have}\n      need: {g.need}")
        if not g.passed:
            print(f"      do:   {g.action}")


def cmd_sheet(a):
    cfg, conn = _ctx()
    if a.action == "import":
        items = sheets.parse(Path(a.file).read_text(encoding="utf-8"))
        db.journal(conn, {"type": "sheet_import", "name": a.name, "items": items})
        conn.commit()
        print(f"Imported {len(items)} items into sheet '{a.name}'.")
        return
    if a.action == "list":
        for r in conn.execute("SELECT name, COUNT(*) n FROM sheets GROUP BY name"):
            print(f"{r['name']}: {r['n']} problems")
        return
    st = load(conn, cfg)
    if a.action == "progress":
        p = sheets.progress(conn, a.name, st.solved)
        print(f"{a.name}: {p['solved']}/{p['total']} solved")
        for sec, (s, t) in p["sections"].items():
            bar = "#" * round(20 * s / t) if t else ""
            print(f"  {sec[:30]:<30} {s:>4}/{t:<4} {bar}")
    elif a.action == "next":
        items, skipped = sheets.next_items(conn, a.name, st.solved, st.level(), a.n, a.include_easy)
        if skipped:
            print(f"(skipped {skipped} unsolved Codeforces items rated below your level {st.level()}; --include-easy to show)")
        for r in items:
            print(f"  {r['pid']:<14} {r['rating'] or '-':>5}  {r['title'] or r['pname'] or ''}  {r['url'] or ''}")


def cmd_analyze(a):
    cfg, conn = _ctx()
    if a.train is not None:
        _train(conn, cfg, a.train)
        return
    if a.evaluate:
        docs = analyzer.training_docs(conn)
        if len(docs) < 50:
            print(f"Only {len(docs)} cached statements; run `ascent analyze --train 300` first.")
            return
        res = analyzer.evaluate(docs)
        db.set_meta(conn, "nb_eval", json.dumps(res))
        conn.commit()
        print(json.dumps(res, indent=2))
        print("precision@3 = fraction of the top-3 predicted topics that are official tags (held-out, 5-fold).")
        return
    if not a.problem:
        print("usage: ascent analyze PROBLEM [--file statement.txt] | --train N | --evaluate")
        return
    pid = _norm_pid(a.problem)
    row = conn.execute("SELECT p.*, c.kind, c.name AS contest_name FROM problems p LEFT JOIN contests c"
                       " ON c.id = p.contest_id WHERE p.pid=?", (pid,)).fetchone()
    meta = dict(row) if row else {}
    meta["tags"] = json.loads(meta.get("tags") or "[]")
    sections = None
    if a.file:
        sections = analyzer.split_sections(Path(a.file).read_text(encoding="utf-8"))
    else:
        cached = conn.execute("SELECT sections FROM statements WHERE pid=?", (pid,)).fetchone()
        if cached:
            sections = json.loads(cached["sections"])
        elif pid.startswith("CF:") and row:
            try:
                from .sources import codeforces as cf
                sections = cf.fetch_statement(row["contest_id"], row["idx"])
                conn.execute("INSERT OR REPLACE INTO statements VALUES (?, ?, ?)",
                             (pid, int(time.time()), json.dumps(sections)))
                conn.commit()
            except FetchError as e:
                print(f"(statement not available: {e})\n")
    st = load(conn, cfg)
    needs = tag_needs(st)
    weak = [t for t, _ in sorted(needs.items(), key=lambda kv: -kv[1])[:4]]
    res = analyzer.analyze(pid, sections, meta, level=st.level() if st.cf_outcomes or st.cf_rating else None,
                           weak_tags=weak, model=analyzer.load_model(conn),
                           expected_solved=sync.expected_solved(conn, pid))
    _print_analysis(res, meta)


def _print_analysis(res, meta):
    print(f"{res.pid}  {meta.get('name') or ''}")
    print(f"rating {meta.get('rating') or '-'} ({meta.get('rating_source') or 'n/a'}), solvers {meta.get('solved_count') or '-'}, "
          f"official tags: {', '.join(meta.get('tags') or []) or '-'}\n")
    print(f"VERDICT: {res.verdict}  (score {res.score}/100)")
    for p, why in res.breakdown:
        print(f"  {p:+4d}  {why}")
    if res.constraints:
        c = res.constraints
        print(f"\nConstraints: {', '.join(f'{k} <= {v:.0f}' for k, v in c.bounds.items()) or 'none parsed'}")
        print(f"  -> intended complexity: {c.complexity}")
    if res.predicted:
        top = list(res.predicted.items())[:6]
        print("\nTopics the statement points to: " + ", ".join(f"{t} ({s:.1f})" for t, s in top))
        if res.hidden_idea is not None:
            print(f"Hidden-idea score: {res.hidden_idea:.2f} (0 = statement names its technique, 1 = nothing on the surface)")
    if res.hits:
        print("\nSignals found (section: context):")
        for h in res.hits[:12]:
            print(f"  [{h.signal}] {h.section}: {h.snippet[:110]}")
    if res.story_ratio is not None:
        print(f"\nStatement: {res.words} words, {res.story_ratio:.0%} story/legend")
    if not res.hits and not res.constraints:
        print("\n(No statement text analysed: verdict uses metadata only. Pass --file statement.txt to include it.)")


def _train(conn, cfg, n):
    from .sources import codeforces as cf
    have = {r["pid"] for r in conn.execute("SELECT pid FROM statements")}
    rows = conn.execute("""SELECT pid, contest_id, idx FROM problems WHERE platform='CF' AND rating_source='official'
                           AND contest_id >= ? AND contest_id < 100000 AND tags != '[]' ORDER BY contest_id DESC""",
                        (cfg.min_contest_id,)).fetchall()
    todo = [r for r in rows if r["pid"] not in have]
    # spread across the catalog rather than only the newest contests
    step = max(1, len(todo) // max(1, n))
    todo = todo[::step][:n]
    print(f"Fetching {len(todo)} statements (~{len(todo) * 2.2 / 60:.0f} min; Codeforces asks for <= 1 request / 2 s) ...")
    got = 0
    for i, r in enumerate(todo, 1):
        try:
            s = cf.fetch_statement(r["contest_id"], r["idx"])
            conn.execute("INSERT OR REPLACE INTO statements VALUES (?, ?, ?)", (r["pid"], int(time.time()), json.dumps(s)))
            got += 1
        except FetchError as e:
            print(f"  skip {r['pid']}: {e}")
        if i % 25 == 0:
            conn.commit()
            print(f"  {i}/{len(todo)}")
    conn.commit()
    nb = analyzer.train(conn)
    print(f"Fetched {got}. Model trained on {nb.n_docs} statements. Check it: ascent analyze --evaluate")


def cmd_dashboard(a):
    cfg, conn = _ctx()
    st = load(conn, cfg)
    out = Path(a.output or home() / "dashboard.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(build_data(conn, st)), encoding="utf-8")
    print(f"Wrote {out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ascent", description="Evidence-based Codeforces / DSA trainer.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="set handles and goals")
    s.add_argument("--cf"); s.add_argument("--lc"); s.add_argument("--target", type=int)
    s.add_argument("--minutes", type=int, help="training minutes per day")
    s.set_defaults(f=cmd_init)

    s = sub.add_parser("sync", help="pull your data from Codeforces / LeetCode")
    s.add_argument("--refresh", action="store_true", help="force re-download of problem catalogs")
    s.add_argument("--rebuild", action="store_true", help="drop the DB and rebuild from APIs + journal")
    s.add_argument("--only", choices=["co", "le"], help="co = Codeforces only, le = LeetCode only")
    s.add_argument("--strict", action="store_true", help="exit with an error if the Codeforces sync failed (for CI/hosting)")
    s.set_defaults(f=cmd_sync)

    sub.add_parser("stats", help="activity summary").set_defaults(f=cmd_stats)
    sub.add_parser("skill", help="overall + per-topic skill estimates").set_defaults(f=cmd_skill)

    s = sub.add_parser("recommend", help="problems above your level, weighted to weak topics")
    s.add_argument("-n", type=int, default=8)
    s.add_argument("--mode", default="mix", choices=["mix", "core", "weak", "tricky", "stretch"])
    s.add_argument("--tag", help="only this Codeforces tag, e.g. dp, 'binary search'")
    s.add_argument("--lc", action="store_true", help="LeetCode (zerotrac-rated) instead")
    s.add_argument("--seed", type=int, help="default: today's date (stable within a day)")
    s.set_defaults(f=cmd_recommend)

    s = sub.add_parser("today", help="a daily plan sized to your time budget")
    s.add_argument("--minutes", type=int); s.add_argument("--seed", type=int)
    s.set_defaults(f=cmd_today)

    s = sub.add_parser("start", help="start a timer on a problem"); s.add_argument("problem"); s.set_defaults(f=cmd_start)
    s = sub.add_parser("stop", help="stop the timer and log the attempt")
    s.add_argument("problem"); s.add_argument("--editorial", action="store_true")
    s.add_argument("--gave-up", action="store_true"); s.add_argument("--notes")
    s.set_defaults(f=cmd_stop)

    s = sub.add_parser("log", help="log an attempt manually")
    s.add_argument("problem"); s.add_argument("--minutes", type=float)
    s.add_argument("--editorial", action="store_true"); s.add_argument("--unsolved", action="store_true")
    s.add_argument("--notes"); s.set_defaults(f=cmd_log)

    s = sub.add_parser("mark", help="mark a non-API problem (GfG, CSES, old LC) solved")
    s.add_argument("problem"); s.set_defaults(f=cmd_mark)

    s = sub.add_parser("review", help="spaced-repetition queue")
    s.add_argument("--done", metavar="PROBLEM"); s.add_argument("--clean", action="store_true",
                                                                 help="re-solved cleanly without help")
    s.set_defaults(f=cmd_review)

    s = sub.add_parser("readiness", help="are you actually at the level? (evidence gates)")
    s.add_argument("--target", type=int); s.add_argument("--profile", choices=["cf", "oa"], default="cf")
    s.set_defaults(f=cmd_readiness)

    s = sub.add_parser("sheet", help="import / track external sheets (CP31, Striver A2Z, ...)")
    s.add_argument("action", choices=["import", "list", "progress", "next"])
    s.add_argument("name", nargs="?"); s.add_argument("file", nargs="?")
    s.add_argument("-n", type=int, default=5); s.add_argument("--include-easy", action="store_true")
    s.set_defaults(f=cmd_sheet)

    s = sub.add_parser("analyze", help="analyze a problem statement: topics, constraints, is it worth it?")
    s.add_argument("problem", nargs="?"); s.add_argument("--file", help="statement text file")
    s.add_argument("--train", type=int, metavar="N", help="download N statements and train the model")
    s.add_argument("--evaluate", action="store_true", help="held-out accuracy of the topic model")
    s.set_defaults(f=cmd_analyze)

    s = sub.add_parser("dashboard", help="write the HTML dashboard")
    s.add_argument("-o", "--output"); s.set_defaults(f=cmd_dashboard)

    a = p.parse_args(argv)
    if a.cmd == "sheet" and a.action in ("import", "progress", "next") and not a.name:
        p.error("sheet name required")
    if a.cmd == "sheet" and a.action == "import" and not a.file:
        p.error("sheet import NAME FILE")
    a.f(a)


if __name__ == "__main__":
    main()
