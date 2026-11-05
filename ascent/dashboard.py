"""Builds the web app: one self-contained HTML file (works offline and on Netlify).

Everything the page needs is embedded at build time:
* your stats, readiness gates, recommendations, reviews
* the whole Codeforces catalog + zerotrac-rated LeetCode problems (compact)
* the brain: lexicon (exported from analyzer.py), trained model weights, and
  the models' measured held-out accuracy.
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter
from importlib import resources

from . import analyzer, db, difficulty, ml
from .readiness import cf_gates, verdict
from .recommend import recommend, tag_needs
from .state import State

KINDS = ml.KINDS


def _brain_constants() -> dict:
    return {
        "lexicon": [[i, p, w, sorted(s) if s else None] for i, p, w, s in analyzer.LEXICON],
        "section_weight": analyzer.SECTION_WEIGHT,
        "impl_only": sorted(analyzer.IMPL_ONLY),
        "low_oa": sorted(analyzer.LOW_OA_VALUE),
    }


def _catalog(conn, st: State) -> tuple[list, list, list]:
    raw = db.get_meta(conn, "unrated_model")
    um = difficulty.UnratedModel.from_json(raw) if raw else None
    tag_ix: dict[str, int] = {}
    cf_rows = []
    for r in conn.execute("""SELECT p.contest_id, p.idx, p.name, p.rating, p.rating_source, p.tags, p.solved_count,
                                    p.trick, c.kind, c.name AS cname FROM problems p
                             LEFT JOIN contests c ON c.id = p.contest_id
                             WHERE p.platform='CF' AND p.contest_id < 100000 ORDER BY p.contest_id DESC, p.idx"""):
        tags = json.loads(r["tags"] or "[]")
        ti = [tag_ix.setdefault(t, len(tag_ix)) for t in tags]
        kind = r["kind"] or "other"
        ratio = -1
        if um and r["rating"] and r["solved_count"] is not None:
            exp = um.expected_solved(kind, r["idx"], r["rating"])
            if exp and math.isfinite(exp) and exp > 0:
                ratio = round(r["solved_count"] / exp, 3)
        pid = f"CF:{r['contest_id']}{r['idx']}"
        special = "*special" in tags or "april fools" in (r["cname"] or "").lower()
        flags = (1 if special else 0) | (2 if pid in st.attempted else 0) | (4 if pid in st.solved else 0)
        src = {"official": 0, "estimated": 1}.get(r["rating_source"], 2)
        cf_rows.append([r["contest_id"], r["idx"], r["name"], r["rating"] or 0, src, ti, r["solved_count"],
                        round((r["trick"] or 0) * 100), KINDS.index(kind) if kind in KINDS else 7, ratio, flags])
    lc_rows = []
    for r in conn.execute("SELECT pid, name, rating, contest_id FROM problems WHERE platform='LC' AND rating_source='zerotrac'"
                          " ORDER BY contest_id DESC"):
        status = 2 if r["pid"] in st.solved else (1 if r["pid"] in st.attempted else 0)
        lc_rows.append([r["pid"][3:], r["name"], r["rating"], r["contest_id"], status])
    return cf_rows, lc_rows, list(tag_ix)


def build_data(conn, st: State, *, train_personal: bool = True) -> dict:
    target = st.cfg.target_rating
    gates = cf_gates(st, target)
    recs = recommend(conn, st, 8)
    solved_cf = [o for o in st.cf_outcomes if o.solved and o.rating]
    bands = Counter(o.rating // 100 * 100 for o in solved_cf)
    ov = st.overall()
    needs = tag_needs(st)
    tags = sorted(((t, e) for t, e in st.tag_skills().items() if e.evidence >= 1), key=lambda kv: kv[1].mean)
    now = st.now
    last90 = sum(1 for o in st.outcomes.values() if o.solved and o.solve_time and now - o.solve_time <= 90 * 86400)
    streak, day = 0, now
    if not st.daily.get(time.strftime("%Y-%m-%d", time.localtime(day))):
        day -= 86400  # today not started yet: the streak can still be alive
    while st.daily.get(time.strftime("%Y-%m-%d", time.localtime(day)), 0) > 0:
        streak += 1
        day -= 86400
    due = conn.execute("SELECT r.*, p.name, p.rating, p.url FROM reviews r LEFT JOIN problems p ON p.pid=r.pid"
                       " WHERE due_at IS NOT NULL AND due_at <= ? ORDER BY due_at LIMIT 10", (now,)).fetchall()

    # --- models ---
    rm_raw = db.get_meta(conn, "rating_model")
    rating_metrics = ml.RatingModel.from_json(rm_raw).metrics if rm_raw else {}
    personal = ml.PersonalModel(None, {"status": "not trained"})
    if train_personal:
        extra = {r["pid"]: {"trick": r["trick"], "solved_count": r["solved_count"]}
                 for r in conn.execute("SELECT pid, trick, solved_count FROM problems WHERE platform='CF'")}
        personal = ml.train_personal_model(
            st.cf_outcomes, extra, contest_rating=st.cf_rating, n_contests=len(st.cf_history),
            practice_discount=st.cfg.practice_discount, half_life_days=st.cfg.recency_half_life_days)
    nb = analyzer.load_model(conn)
    nb_eval = db.get_meta(conn, "nb_eval")

    cf_rows, lc_rows, tag_names = _catalog(conn, st)
    weak = [t for t, _ in sorted(needs.items(), key=lambda kv: -kv[1])[:4]]
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "handle": st.cfg.cf_handle, "lc_handle": st.cfg.lc_handle, "target": target,
        "min_contest_id": st.cfg.min_contest_id,
        "me": {"cf_rating": st.cf_rating, "cf_max": st.cf_max, "lc_rating": st.lc_rating,
               "skill": round(ov.mean), "skill_sd": round(ov.sd), "level": st.level(),
               "overall_mean": ov.mean, "tag_means": {t: e.mean for t, e in st.tag_skills().items()},
               "weak": weak, "solved90": last90, "streak": streak, "total_solved": len(st.solved),
               "contests": len(st.cf_history),
               "last_delta": (st.cf_history[-1]["new_rating"] - st.cf_history[-1]["old_rating"]) if st.cf_history else None},
        "history": [{"t": h["time"], "r": h["new_rating"], "name": h["contest_name"]} for h in st.cf_history],
        "lc_history": [{"t": h["time"], "r": h["new_rating"], "name": h["contest_name"]} for h in st.lc_history],
        "daily": st.daily,
        "bands": [{"band": b, "n": bands[b]} for b in sorted(bands)],
        "tags": [{"tag": t, "mean": round(e.mean), "sd": round(e.sd), "ev": round(e.evidence, 1),
                  "need": needs.get(t)} for t, e in tags],
        "gates": [g.__dict__ for g in gates], "verdict": verdict(gates),
        "recs": [r.__dict__ for r in recs],
        "reviews": [dict(r) for r in due],
        "models": {"rating": rating_metrics, "personal": personal.metrics, "personal_w": personal.weights,
                   "analyzer": {"signals": len(analyzer.LEXICON), "nb_docs": nb.n_docs if nb else 0,
                                "nb_eval": json.loads(nb_eval) if nb_eval else None}},
        "brain": _brain_constants(),
        "kinds": KINDS, "tag_names": tag_names, "cf": cf_rows, "lc": lc_rows,
    }


def _asset(name: str) -> str:
    return resources.files("ascent").joinpath("web", name).read_text(encoding="utf-8")


def render(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    title = f"ascent · {data['handle']}" if data.get("handle") else "ascent"
    page = _asset("index.html").replace("__TITLE__", title.replace("&", "&amp;").replace("<", "&lt;"))
    head, tail = page.split("__DATA__")  # data goes in last so nothing inside it is ever substituted
    head = (head.replace("/*__CSS__*/", _asset("app.css"))
            .replace("/*__BRAIN__*/", _asset("brain.js")))
    tail = tail.replace("/*__APP__*/", _asset("app.js"))
    return head + payload + tail
