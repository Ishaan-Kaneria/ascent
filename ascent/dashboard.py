"""Self-contained HTML dashboard (no external scripts, works offline)."""
from __future__ import annotations

import html
import json
import time
from collections import Counter

from .readiness import cf_gates, verdict
from .recommend import recommend
from .state import State


def build_data(conn, st: State) -> dict:
    target = st.cfg.target_rating
    gates = cf_gates(st, target)
    recs = recommend(conn, st, 8)
    solved_cf = [o for o in st.cf_outcomes if o.solved and o.rating]
    bands = Counter(o.rating // 100 * 100 for o in solved_cf)
    ov = st.overall()
    tags = sorted(((t, e) for t, e in st.tag_skills().items() if e.evidence >= 1),
                  key=lambda kv: kv[1].mean)
    now = st.now
    last90 = sum(1 for o in st.outcomes.values() if o.solved and o.solve_time and now - o.solve_time <= 90 * 86400)
    streak, day = 0, now
    while st.daily.get(time.strftime("%Y-%m-%d", time.localtime(day)), 0) > 0:
        streak += 1
        day -= 86400
    due = conn.execute("SELECT r.*, p.name, p.rating, p.url FROM reviews r LEFT JOIN problems p ON p.pid=r.pid"
                       " WHERE due_at IS NOT NULL AND due_at <= ? ORDER BY due_at LIMIT 10", (now,)).fetchall()
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "handle": st.cfg.cf_handle, "lc_handle": st.cfg.lc_handle, "target": target,
        "cf_rating": st.cf_rating, "cf_max": st.cf_max, "lc_rating": st.lc_rating,
        "skill": round(ov.mean), "skill_sd": round(ov.sd), "level": st.level(),
        "solved90": last90, "streak": streak,
        "history": [{"t": h["time"], "r": h["new_rating"], "name": h["contest_name"]} for h in st.cf_history],
        "lc_history": [{"t": h["time"], "r": h["new_rating"], "name": h["contest_name"]} for h in st.lc_history],
        "daily": st.daily,
        "bands": [{"band": b, "n": bands[b]} for b in sorted(bands)],
        "tags": [{"tag": t, "mean": round(e.mean), "sd": round(e.sd), "ev": round(e.evidence, 1)} for t, e in tags],
        "gates": [g.__dict__ for g in gates], "verdict": verdict(gates),
        "recs": [r.__dict__ for r in recs],
        "reviews": [dict(r) for r in due],
    }


def render(data: dict) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", html.escape(
        f"ascent: {data['handle'] or 'dashboard'}"))


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--s1:#2a78d6;--good:#0ca30c;--crit:#d03b3b;--warn:#fab219;
--q0:#ebeae5;--q1:#b7d3f6;--q2:#86b6ef;--q3:#3987e5;--q4:#1c5cab;--q5:#0d366b}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;
--q0:#262624;--q1:#104281;--q2:#1c5cab;--q3:#2a78d6;--q4:#5598e7;--q5:#9ec5f4}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;
--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--q0:#262624;--q1:#104281;--q2:#1c5cab;--q3:#2a78d6;--q4:#5598e7;--q5:#9ec5f4}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:0 0 12px}.sub{color:var(--ink2);margin:0 0 20px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr))}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;min-width:0}
.wide{grid-column:1/-1}.tiles{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin-bottom:16px}
.tile .v{font-size:28px;font-weight:650;font-variant-numeric:tabular-nums}.tile .l{color:var(--ink2);font-size:12px}
svg{display:block;width:100%;height:auto;overflow:visible}text{fill:var(--muted);font-size:11px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}td,th{text-align:left;padding:7px 6px;border-top:1px solid var(--grid);vertical-align:top}
th{color:var(--ink2);font-weight:550;font-size:12px;border-top:0}a{color:var(--s1)}
.pass{color:var(--good);font-weight:600;white-space:nowrap}.fail{color:var(--crit);font-weight:600;white-space:nowrap}.muted{color:var(--ink2);font-size:12px}
.verdict{padding:10px 12px;border-radius:8px;border:1px solid var(--border);margin-bottom:12px;font-weight:600}
.scroll{overflow-x:auto}#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--border);
border-radius:6px;padding:6px 8px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.15);display:none;z-index:9;max-width:260px}
.legend{display:flex;gap:4px;align-items:center;color:var(--ink2);font-size:11px;margin-top:6px}.legend i{width:11px;height:11px;border-radius:2px;display:inline-block}
.toggle{float:right;background:none;border:1px solid var(--border);color:var(--ink2);border-radius:6px;padding:4px 8px;cursor:pointer}
</style></head><body><main>
<button class="toggle" id="theme" aria-label="Toggle theme">theme</button>
<h1 id="h"></h1><p class="sub" id="sub"></p>
<div class="tiles" id="tiles"></div>
<div class="grid">
<section class="card wide"><h2>Readiness for <span id="tgt"></span></h2><div class="verdict" id="verdict"></div><div class="scroll"><table id="gates"></table></div></section>
<section class="card"><h2>Codeforces rating</h2><div id="rating"></div></section>
<section class="card"><h2>Solved problems by rating</h2><div id="bands"></div></section>
<section class="card wide"><h2>Activity: problems solved per day</h2><div class="scroll"><div id="heat" style="min-width:680px"></div></div></section>
<section class="card wide"><h2>Topic skill (contest-equivalent, vs overall)</h2><div id="tags"></div></section>
<section class="card wide"><h2>Today's problems</h2><div class="scroll"><table id="recs"></table></div></section>
<section class="card wide"><h2>Reviews due</h2><div class="scroll"><table id="reviews"></table></div></section>
</div></main><div id="tip"></div>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg", $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const tip = $("tip");
function showTip(e, h){ tip.innerHTML = h; tip.style.display = "block";
  const x = Math.min(e.clientX + 12, innerWidth - tip.offsetWidth - 8); tip.style.left = x + "px"; tip.style.top = (e.clientY + 12) + "px"; }
function hideTip(){ tip.style.display = "none"; }
function el(tag, attrs, parent){ const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; }
function svg(w, h, host, fixed){ const s = el("svg", {viewBox:`0 0 ${w} ${h}`, role:"img"}); if (fixed) s.style.width = w + "px"; $(host).appendChild(s); return s; }
const widthOf = (host, min) => Math.max(min, Math.round($(host).clientWidth || min));
function empty(host, msg){ $(host).innerHTML = `<p class="muted">${msg}</p>`; }

$("theme").onclick = () => { const r = document.documentElement; const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches; r.dataset.theme = dark ? "light" : "dark"; };
$("h").textContent = D.handle ? `ascent · ${D.handle}` : "ascent";
$("sub").textContent = `Generated ${D.generated}. All numbers come from your real submissions.`;
$("tgt").textContent = D.target;
const tiles = [["CF rating", D.cf_rating ?? "-", D.cf_max ? `max ${D.cf_max}` : ""], ["Skill estimate", D.skill, `± ${D.skill_sd} (contest-equivalent)`],
  ["Training level", D.level, "recommendations start here"], ["Solved, 90 days", D.solved90, ""], ["Streak", D.streak, "days"]];
if (D.lc_rating) tiles.push(["LeetCode rating", Math.round(D.lc_rating), D.lc_handle]);
$("tiles").innerHTML = tiles.map(([l,v,s]) => `<div class="card tile"><div class="l">${esc(l)}</div><div class="v">${esc(v)}</div><div class="muted">${esc(s)}</div></div>`).join("");

// Readiness
$("verdict").textContent = D.verdict;
$("gates").innerHTML = "<tr><th>Gate</th><th>Status</th><th>You have</th><th>Required</th><th>Next action</th></tr>" + D.gates.map(g =>
  `<tr><td>${esc(g.name)}</td><td class="${g.passed?"pass":"fail"}">${g.passed?"✓ pass":"✗ fail"}</td><td>${esc(g.have)}</td><td class="muted">${esc(g.need)}</td><td class="muted">${esc(g.action)}</td></tr>`).join("");

// Rating line (single series; crosshair + tooltip)
(function(){
  const H = D.history; if (H.length < 2) return empty("rating", "Fewer than two rated contests yet. Play rated rounds: they are the only thing that moves this.");
  const W = widthOf("rating", 300), Ht = 230, m = {l:40, r:12, t:10, b:24}, s = svg(W, Ht, "rating");
  const t0 = H[0].t, t1 = H[H.length-1].t, rs = H.map(h => h.r), lo = Math.floor((Math.min(...rs, D.target) - 100)/100)*100, hi = Math.ceil((Math.max(...rs, D.target) + 50)/100)*100;
  const X = t => m.l + (t - t0) / (t1 - t0 || 1) * (W - m.l - m.r), Y = r => m.t + (hi - r) / (hi - lo) * (Ht - m.t - m.b);
  for (let r = lo; r <= hi; r += (hi - lo > 800 ? 200 : 100)) { el("line", {x1:m.l, x2:W-m.r, y1:Y(r), y2:Y(r), stroke:"var(--grid)"}, s); el("text", {x:m.l-6, y:Y(r)+4, "text-anchor":"end"}, s).textContent = r; }
  el("line", {x1:m.l, x2:W-m.r, y1:Y(D.target), y2:Y(D.target), stroke:"var(--ink2)", "stroke-dasharray":"4 4"}, s);
  el("text", {x:W-m.r, y:Y(D.target)-4, "text-anchor":"end"}, s).textContent = `target ${D.target}`;
  el("path", {d:H.map((h,i) => (i?"L":"M") + X(h.t) + " " + Y(h.r)).join(""), fill:"none", stroke:"var(--s1)", "stroke-width":2, "stroke-linejoin":"round"}, s);
  const last = H[H.length-1]; el("circle", {cx:X(last.t), cy:Y(last.r), r:4, fill:"var(--s1)", stroke:"var(--surface)", "stroke-width":2}, s);
  const cross = el("line", {y1:m.t, y2:Ht-m.b, stroke:"var(--axis)", visibility:"hidden"}, s), dot = el("circle", {r:4, fill:"var(--s1)", stroke:"var(--surface)", "stroke-width":2, visibility:"hidden"}, s);
  const hit = el("rect", {x:m.l, y:m.t, width:W-m.l-m.r, height:Ht-m.t-m.b, fill:"transparent"}, s);
  hit.addEventListener("mousemove", e => { const b = s.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * W;
    let best = H[0]; for (const h of H) if (Math.abs(X(h.t) - px) < Math.abs(X(best.t) - px)) best = h;
    cross.setAttribute("x1", X(best.t)); cross.setAttribute("x2", X(best.t)); cross.setAttribute("visibility","visible");
    dot.setAttribute("cx", X(best.t)); dot.setAttribute("cy", Y(best.r)); dot.setAttribute("visibility","visible");
    showTip(e, `<b>${best.r}</b><br>${esc(best.name)}<br><span class="muted">${new Date(best.t*1000).toLocaleDateString()}</span>`); });
  hit.addEventListener("mouseleave", () => { hideTip(); cross.setAttribute("visibility","hidden"); dot.setAttribute("visibility","hidden"); });
})();

// Solved by rating band (bars)
(function(){
  const B = D.bands; if (!B.length) return empty("bands", "No rated solves yet.");
  const W = widthOf("bands", 300), Ht = 230, m = {l:34, r:8, t:10, b:24}, s = svg(W, Ht, "bands"), mx = Math.max(...B.map(b => b.n));
  const bw = (W - m.l - m.r) / B.length, Y = n => m.t + (1 - n / mx) * (Ht - m.t - m.b);
  [0, Math.round(mx/2), mx].forEach(v => { el("line", {x1:m.l, x2:W-m.r, y1:Y(v), y2:Y(v), stroke:"var(--grid)"}, s); el("text", {x:m.l-6, y:Y(v)+4, "text-anchor":"end"}, s).textContent = v; });
  B.forEach((b, i) => { const x = m.l + i * bw + 1, h = Ht - m.b - Y(b.n), w = Math.max(2, bw - 2), r = Math.min(4, w/2, h);
    const p = el("path", {d:`M${x} ${Ht-m.b} V${Y(b.n)+r} Q${x} ${Y(b.n)} ${x+r} ${Y(b.n)} H${x+w-r} Q${x+w} ${Y(b.n)} ${x+w} ${Y(b.n)+r} V${Ht-m.b} Z`,
      fill: b.band >= D.level ? "var(--s1)" : "var(--q2)"}, s);
    const hb = el("rect", {x:m.l + i*bw, y:m.t, width:bw, height:Ht-m.t-m.b, fill:"transparent"}, s);
    hb.addEventListener("mousemove", e => showTip(e, `<b>${b.n}</b> solved rated ${b.band}${b.band >= D.level ? "" : "<br><span class='muted'>below your level</span>"}`)); hb.addEventListener("mouseleave", hideTip);
    if (B.length <= 16 || i % 2 === 0) el("text", {x:m.l + i*bw + bw/2, y:Ht-8, "text-anchor":"middle"}, s).textContent = b.band; });
  $("bands").insertAdjacentHTML("beforeend", `<div class="legend"><i style="background:var(--s1)"></i> at/above level ${D.level} &nbsp; <i style="background:var(--q2)"></i> below level</div>`);
})();

// Activity heatmap (last 53 weeks)
(function(){
  const cell = 12, gap = 2, s = svg(53*(cell+gap)+30, 7*(cell+gap)+20, "heat", true), today = new Date(); today.setHours(0,0,0,0);
  const start = new Date(today); start.setDate(start.getDate() - 52*7 - today.getDay());
  const steps = ["var(--q0)","var(--q1)","var(--q2)","var(--q3)","var(--q4)","var(--q5)"], lvl = n => n === 0 ? 0 : n === 1 ? 1 : n <= 2 ? 2 : n <= 4 ? 3 : n <= 7 ? 4 : 5;
  ["Mon","Wed","Fri"].forEach((d,i) => el("text", {x:0, y:20 + (1+2*i)*(cell+gap) - 3}, s).textContent = d);
  for (let d = new Date(start), i = 0; d <= today; d.setDate(d.getDate()+1), i++) {
    const key = d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0") + "-" + String(d.getDate()).padStart(2,"0"), n = D.daily[key] || 0;
    const x = 30 + Math.floor(i/7)*(cell+gap), y = 12 + d.getDay()*(cell+gap);
    if (d.getDate() === 1) el("text", {x, y:8}, s).textContent = d.toLocaleString(undefined, {month:"short"});
    const r = el("rect", {x, y, width:cell, height:cell, rx:2, fill:steps[lvl(n)]}, s), label = d.toDateString();
    r.addEventListener("mousemove", e => showTip(e, `<b>${n}</b> solved<br><span class="muted">${label}</span>`)); r.addEventListener("mouseleave", hideTip); }
  $("heat").insertAdjacentHTML("beforeend", `<div class="legend">less ${steps.map(c => `<i style="background:${c}"></i>`).join("")} more</div>`);
})();

// Topic skill bars with overall reference line
(function(){
  const T = D.tags; if (!T.length) return empty("tags", "No topic evidence yet.");
  const W = widthOf("tags", 600), row = 22, m = {l:170, r:60, t:8, b:20}, Ht = m.t + m.b + T.length*row, s = svg(W, Ht, "tags");
  const lo = Math.floor((Math.min(...T.map(t => t.mean), D.skill) - 150)/100)*100, hi = Math.ceil((Math.max(...T.map(t => t.mean), D.skill) + 150)/100)*100;
  const X = v => m.l + (v - lo) / (hi - lo) * (W - m.l - m.r);
  for (let v = lo; v <= hi; v += 100) { el("line", {x1:X(v), x2:X(v), y1:m.t, y2:Ht-m.b, stroke:"var(--grid)"}, s); el("text", {x:X(v), y:Ht-6, "text-anchor":"middle"}, s).textContent = v; }
  T.forEach((t, i) => { const y = m.t + i*row + 4, h = row - 8;
    el("text", {x:m.l - 8, y:y + h - 2, "text-anchor":"end", style:"fill:var(--ink2)"}, s).textContent = t.tag;
    const w = Math.max(2, X(t.mean) - X(lo)); el("rect", {x:X(lo), y, width:w, height:h, rx:3, fill: t.ev < 3 ? "var(--q2)" : "var(--s1)"}, s);
    el("text", {x:X(lo) + w + 6, y:y + h - 2}, s).textContent = t.mean;
    const hb = el("rect", {x:0, y:y-4, width:W, height:row, fill:"transparent"}, s);
    hb.addEventListener("mousemove", e => showTip(e, `<b>${esc(t.tag)}</b>: ${t.mean} ± ${t.sd}<br>evidence ${t.ev}${t.ev < 3 ? " (thin: unexplored)" : ""}`)); hb.addEventListener("mouseleave", hideTip); });
  el("line", {x1:X(D.skill), x2:X(D.skill), y1:m.t, y2:Ht-m.b, stroke:"var(--ink)", "stroke-dasharray":"3 3"}, s);
  el("text", {x:X(D.skill)+4, y:m.t+8, style:"fill:var(--ink)"}, s).textContent = `overall ${D.skill}`;
  $("tags").insertAdjacentHTML("beforeend", `<div class="legend"><i style="background:var(--s1)"></i> enough evidence &nbsp; <i style="background:var(--q2)"></i> thin evidence (&lt; 3)</div>`);
})();

$("recs").innerHTML = D.recs.length ? "<tr><th>Problem</th><th>Rating</th><th>Type</th><th>Why</th><th>Tags</th><th>~min</th></tr>" + D.recs.map(r =>
  `<tr><td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.pid.slice(3))} · ${esc(r.name)}</a></td><td>${r.rating}${r.rating_source === "estimated" ? " (est.)" : ""}</td><td>${esc(r.bucket)}</td><td>${esc(r.reason)}</td><td class="muted">${esc(r.tags.join(", "))}</td><td>${r.est_minutes}</td></tr>`).join("")
  : "<tr><td class='muted'>Run <code>ascent sync</code> to load the problem catalog.</td></tr>";
$("reviews").innerHTML = D.reviews.length ? "<tr><th>Problem</th><th>Rating</th><th>Why</th></tr>" + D.reviews.map(r =>
  `<tr><td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.pid)} · ${esc(r.name)}</a></td><td>${r.rating ?? "-"}</td><td class="muted">${esc(r.reason)}</td></tr>`).join("")
  : "<tr><td class='muted'>Nothing due.</td></tr>";
</script></body></html>
"""
