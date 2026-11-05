(function () {
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const me = D.me;
Brain.init(D.brain);

/* ---------- helpers ---------- */
const $ = id => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function el(tag, attrs, parent) { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; }
function svgIn(host, w, h, fixed) { const s = el("svg", { viewBox: `0 0 ${w} ${h}`, width: fixed ? w : "100%", role: "img" }); $(host).innerHTML = ""; $(host).appendChild(s); return s; }
const widthOf = (id, min) => Math.max(min, Math.round($(id).clientWidth || min));
const tip = $("tip");
function showTip(e, html) { tip.innerHTML = html; tip.style.display = "block";
  const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 10), y = Math.min(e.clientY + 14, innerHeight - tip.offsetHeight - 10);
  tip.style.left = x + "px"; tip.style.top = y + "px"; }
const hideTip = () => { tip.style.display = "none"; };
function hover(node, html) { node.addEventListener("mousemove", e => showTip(e, typeof html === "function" ? html() : html)); node.addEventListener("mouseleave", hideTip); }
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };

const RANKS = [[0, "Newbie", "#8c8c8c"], [1200, "Pupil", "#3aa84a"], [1400, "Specialist", "#03a89e"], [1600, "Expert", "#3b6fe0"],
  [1900, "Candidate Master", "#a64ee0"], [2100, "Master", "#ff9a1f"], [2300, "International Master", "#ff8c00"],
  [2400, "Grandmaster", "#e5383b"], [2600, "International Grandmaster", "#e5383b"], [3000, "Legendary Grandmaster", "#b0001a"]];
const rankOf = r => { let x = RANKS[0]; for (const k of RANKS) if (r >= k[0]) x = k; return x; };

/* ---------- theme + tabs ---------- */
const saved = store.get("ascent-theme");
if (saved) document.documentElement.dataset.theme = saved;
$("theme").onclick = () => {
  const r = document.documentElement;
  const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  r.dataset.theme = dark ? "light" : "dark"; store.set("ascent-theme", r.dataset.theme); drawCharts();
};
const TABS = ["overview", "oracle", "train", "topics", "brain"];
function route() {
  const h = (location.hash || "#overview").slice(1).split("/")[0];
  const tab = TABS.includes(h) ? h : "overview";
  for (const t of TABS) { $("tab-" + t).classList.toggle("active", t === tab); }
  document.querySelectorAll(".tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === tab));
  if (tab === "oracle") { const pid = decodeURIComponent((location.hash.split("/")[1] || "")); if (pid && byPid[pid]) select(byPid[pid], false); }
  requestAnimationFrame(drawCharts);
}
addEventListener("hashchange", route);
addEventListener("keydown", e => { if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") { e.preventDefault(); location.hash = "#oracle"; setTimeout(() => $("q").focus(), 30); } });

/* ---------- catalog ---------- */
const SRC = ["official", "estimated", null];
const problems = [], byPid = {};
for (const r of D.cf) {
  const [cid, idx, name, rating, src, ti, solved, trick, kind, ratio, flags] = r;
  const p = { plat: "CF", id: `${cid}${idx}`, pid: `CF:${cid}${idx}`, cid, idx, name, rating: rating || null, source: SRC[src],
    tags: ti.map(i => D.tag_names[i]), solved, trick: trick / 100, kind: D.kinds[kind], ratio: ratio > 0 ? ratio : null,
    special: !!(flags & 1), status: flags & 4 ? "solved" : flags & 2 ? "attempted" : null,
    url: `https://codeforces.com/problemset/problem/${cid}/${idx}` };
  p.key = (p.id + " " + name).toLowerCase(); problems.push(p); byPid[p.pid] = p;
}
for (const r of D.lc) {
  const [slug, name, rating, num, st] = r;
  const p = { plat: "LC", id: slug, pid: "LC:" + slug, num, name, rating, source: "zerotrac", tags: [], solved: null, trick: 0,
    status: st === 2 ? "solved" : st === 1 ? "attempted" : null, url: `https://leetcode.com/problems/${slug}/` };
  p.key = (num + " " + slug + " " + name).toLowerCase(); problems.push(p); byPid[p.pid] = p;
}
const LC = D.leetcode || { level: 1500, level_assumed: true, recs: [], recent: [] };
const lcLevel = LC.level;

function evaluate(p, sections) {
  const meta = { rating: p.rating, rating_source: p.source, tags: p.tags, solved_count: p.solved, trick: p.trick,
    contest_id: p.cid, contest_name: p.special && !p.tags.includes("*special") ? "April Fools" : "" };
  const ctx = p.plat === "CF"
    ? { level: me.level, weak_tags: me.weak, ratio: p.ratio, status: p.status,
        p_solve: Brain.personalP(D.models.personal_w, me, p.rating, p.tags, p.trick, p.solved) }
    : { level: lcLevel, weak_tags: [], ratio: null, status: p.status, p_solve: null };
  const res = Brain.analyze(meta, sections, ctx);
  res.p_solve = ctx.p_solve;
  return res;
}

/* ---------- overview ---------- */
function renderHero() {
  const r = me.cf_rating, rk = rankOf(r || 0), passed = D.gates.filter(g => g.passed).length, total = D.gates.length;
  const C = 2 * Math.PI * 78, frac = total ? passed / total : 0;
  const delta = me.last_delta;
  $("hero").innerHTML = `
    <div class="ring" aria-label="${passed} of ${total} readiness gates passed">
      <svg viewBox="0 0 184 184"><defs><linearGradient id="rg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="var(--a1)"/><stop offset="1" stop-color="var(--a2)"/></linearGradient></defs>
        <circle cx="92" cy="92" r="78" fill="none" stroke="var(--grid)" stroke-width="12"/>
        <circle id="ring-fill" cx="92" cy="92" r="78" fill="none" stroke="url(#rg)" stroke-width="12" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C}" style="transition:stroke-dashoffset 1.2s cubic-bezier(.2,.8,.2,1)"/></svg>
      <div class="center"><div><div class="big grad" id="cnt">${r ?? "–"}</div><div class="lbl">${r ? "CF rating" : "unrated"} · ${passed}/${total} gates</div></div></div>
    </div>
    <div>
      <div class="who"><h1>${esc(D.handle || "you")}</h1>${r ? `<span class="rank" style="color:${rk[2]}">${rk[1]}</span>` : ""}
        ${delta != null ? `<span class="badge ${delta >= 0 ? "b-pass" : "b-fail"}">${delta >= 0 ? "▲" : "▼"} ${Math.abs(delta)} last round</span>` : ""}</div>
      <p class="hero-sub">${esc(D.verdict)}</p>
      <div class="stats">
        <div class="stat"><div class="l">Skill estimate</div><div class="v">${me.skill}</div><div class="s">± ${me.skill_sd}, contest-equivalent</div></div>
        <div class="stat"><div class="l">Training level</div><div class="v">${me.level}</div><div class="s">picks start here</div></div>
        <div class="stat"><div class="l">Solved · 90 days</div><div class="v">${me.solved90}</div><div class="s">${me.total_solved} all time</div></div>
        <div class="stat"><div class="l">Streak</div><div class="v">${me.streak}<span style="font-size:14px;color:var(--muted)"> d</span></div><div class="s">${me.contests} rated rounds</div></div>
        ${me.lc_rating ? `<div class="stat"><div class="l">LeetCode</div><div class="v">${Math.round(me.lc_rating)}</div><div class="s">${esc(D.lc_handle)}</div></div>` : ""}
      </div>
    </div>`;
  requestAnimationFrame(() => { const f = $("ring-fill"); if (f) f.style.strokeDashoffset = String(C * (1 - frac)); });
  if (r) { const node = $("cnt"), t0 = performance.now(); const tick = t => { const k = Math.min(1, (t - t0) / 900); node.textContent = Math.round(r * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(tick); }; requestAnimationFrame(tick); }
  $("tgt").textContent = `${D.target} (${rankOf(D.target)[1]})`;
  $("verdict").textContent = "Every gate must pass. Click a gate for the exact requirement and what to do next.";
  $("gates").innerHTML = D.gates.map(g => `<button class="gate" aria-expanded="false">
      <div class="row"><span class="badge ${g.passed ? "b-pass" : "b-fail"}">${g.passed ? "✓ PASS" : "✕ FAIL"}</span>${esc(g.name)}</div>
      <div class="have">${esc(g.have)}</div>
      <div class="more"><div><b>Required:</b> ${esc(g.need)}</div>${g.passed ? "" : `<div style="margin-top:6px"><b>Do:</b> ${esc(g.action)}</div>`}</div></button>`).join("");
  document.querySelectorAll(".gate").forEach(b => b.onclick = () => { b.classList.toggle("open"); b.setAttribute("aria-expanded", b.classList.contains("open")); });
  const ss = D.sync_status || {};
  const srcs = Object.entries(ss).map(([k, v]) => `<span class="src"><span class="badge ${v.ok ? "b-pass" : "b-fail"}">${v.ok ? "✓" : "✕"} ${esc(k)}</span></span>`).join("");
  $("foot").innerHTML = `Built ${esc(D.generated)} · ${problems.length.toLocaleString()} problems indexed${srcs ? " · " + srcs : ""}`;
}

function drawRating() {
  drawLine("chart-rating", D.history, { bands: true, target: D.target,
    empty: "Fewer than two rated rounds yet. Rated rounds are the only thing that moves this line." });
  if (D.history.length >= 2) $("rating-sub").textContent = `max ${me.cf_max} · target ${D.target} dashed`;
}
function drawLC() {
  drawLine("chart-lc", D.lc_history, { bands: false, target: null,
    empty: LC.handle ? "Fewer than two rated LeetCode contests yet. Weekly and biweekly contests calibrate your LeetCode level." : "Add your LeetCode handle to see this." });
}
function drawLine(host, H, opt) {
  if (H.length < 2) { $(host).innerHTML = `<p class="empty">${esc(opt.empty)}</p>`; return; }
  const W = widthOf(host, 300), Ht = 250, m = { l: 40, r: opt.bands ? 74 : 14, t: 10, b: 26 }, s = svgIn(host, W, Ht);
  const t0 = H[0].t, t1 = H[H.length - 1].t, rs = H.map(h => h.r);
  const lo = Math.floor((Math.min(...rs) - 100) / 100) * 100, hi = Math.ceil((Math.max(...rs, opt.target || 0) + 100) / 100) * 100;
  const X = t => m.l + (t - t0) / (t1 - t0 || 1) * (W - m.l - m.r), Y = r => m.t + (hi - r) / (hi - lo) * (Ht - m.t - m.b);
  for (let i = 0; opt.bands && i < RANKS.length; i++) {
    const a = Math.max(lo, RANKS[i][0]), b = Math.min(hi, i + 1 < RANKS.length ? RANKS[i + 1][0] : 5000);
    if (b <= a) continue;
    el("rect", { x: m.l, y: Y(b), width: W - m.l - m.r, height: Y(a) - Y(b), fill: RANKS[i][2], opacity: 0.08 }, s);
    el("text", { x: W - m.r + 8, y: (Y(a) + Y(b)) / 2 + 4, style: `fill:${RANKS[i][2]};font-weight:600` }, s).textContent = RANKS[i][1].replace("International ", "Intl. ").replace("Candidate Master", "Cand. Master");
  }
  const step = hi - lo > 1000 ? 200 : 100;
  for (let r = lo; r <= hi; r += step) { el("line", { x1: m.l, x2: W - m.r, y1: Y(r), y2: Y(r), stroke: "var(--grid)" }, s); el("text", { x: m.l - 8, y: Y(r) + 4, "text-anchor": "end" }, s).textContent = r; }
  if (opt.target) el("line", { x1: m.l, x2: W - m.r, y1: Y(opt.target), y2: Y(opt.target), stroke: "var(--ink-2)", "stroke-dasharray": "4 4" }, s);
  const color = r => opt.bands ? rankOf(r)[2] : "var(--data)";
  const path = el("path", { d: H.map((h, i) => (i ? "L" : "M") + X(h.t).toFixed(1) + " " + Y(h.r).toFixed(1)).join(""), fill: "none", stroke: "var(--ink)", "stroke-width": 2, "stroke-linejoin": "round" }, s);
  const len = path.getTotalLength ? path.getTotalLength() : 0;
  if (len) { path.style.strokeDasharray = len; path.style.strokeDashoffset = len; path.getBoundingClientRect(); path.style.transition = "stroke-dashoffset 1.2s ease"; path.style.strokeDashoffset = 0; }
  const last = H[H.length - 1];
  el("circle", { cx: X(last.t), cy: Y(last.r), r: 5, fill: color(last.r), stroke: "var(--bg)", "stroke-width": 2 }, s);
  const cross = el("line", { y1: m.t, y2: Ht - m.b, stroke: "var(--axis)", visibility: "hidden" }, s);
  const dot = el("circle", { r: 5, stroke: "var(--bg)", "stroke-width": 2, visibility: "hidden" }, s);
  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: Ht - m.t - m.b, fill: "transparent" }, s);
  hit.addEventListener("mousemove", e => {
    const b = s.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * W;
    let best = H[0]; for (const h of H) if (Math.abs(X(h.t) - px) < Math.abs(X(best.t) - px)) best = h;
    const i = H.indexOf(best), d = i ? best.r - H[i - 1].r : null;
    cross.setAttribute("x1", X(best.t)); cross.setAttribute("x2", X(best.t)); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", X(best.t)); dot.setAttribute("cy", Y(best.r)); dot.setAttribute("fill", color(best.r)); dot.setAttribute("visibility", "visible");
    showTip(e, `<b>${best.r}</b>${d != null ? ` <span class="${d >= 0 ? "up" : "down"}">${d >= 0 ? "+" : ""}${d}</span>` : ""}<br>${esc(best.name)}<br><span style="color:var(--muted)">${new Date(best.t * 1000).toLocaleDateString()}</span>`);
  });
  hit.addEventListener("mouseleave", () => { hideTip(); cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
}

function drawBands() {
  const B = D.bands, host = "chart-bands";
  if (!B.length) { $(host).innerHTML = `<p class="empty">No rated solves yet.</p>`; return; }
  const W = widthOf(host, 300), Ht = 250, m = { l: 34, r: 6, t: 10, b: 26 }, s = svgIn(host, W, Ht), mx = Math.max(...B.map(b => b.n));
  const bw = (W - m.l - m.r) / B.length, Y = n => m.t + (1 - n / mx) * (Ht - m.t - m.b);
  [0, Math.round(mx / 2), mx].forEach(v => { el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: "var(--grid)" }, s); el("text", { x: m.l - 8, y: Y(v) + 4, "text-anchor": "end" }, s).textContent = v; });
  B.forEach((b, i) => {
    const x = m.l + i * bw + 1, w = Math.max(2, bw - 2), top = Y(b.n), h = Ht - m.b - top, r = Math.min(4, w / 2, h);
    el("path", { d: `M${x} ${Ht - m.b}V${top + r}Q${x} ${top} ${x + r} ${top}H${x + w - r}Q${x + w} ${top} ${x + w} ${top + r}V${Ht - m.b}Z`, fill: b.band >= me.level ? "var(--data)" : "var(--data-soft)" }, s);
    const hb = el("rect", { x: m.l + i * bw, y: m.t, width: bw, height: Ht - m.t - m.b, fill: "transparent" }, s);
    hover(hb, `<b>${b.n}</b> solved at ${b.band}${b.band >= me.level ? "" : "<br><span style='color:var(--muted)'>below your level</span>"}`);
    if (B.length <= 14 || i % 2 === 0) el("text", { x: m.l + i * bw + bw / 2, y: Ht - 8, "text-anchor": "middle" }, s).textContent = b.band;
  });
  const lg = document.createElement("div"); lg.className = "legend";
  lg.innerHTML = `<span><i style="background:var(--data)"></i>at/above level ${me.level}</span><span><i style="background:var(--data-soft)"></i>below level</span>`;
  $(host).appendChild(lg);
}

function drawHeat() {
  const host = "chart-heat", cell = 13, gap = 3, weeks = 53, s = svgIn(host, weeks * (cell + gap) + 34, 7 * (cell + gap) + 22, true);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const start = new Date(today); start.setDate(start.getDate() - (weeks - 1) * 7 - today.getDay());
  const steps = ["var(--h0)", "var(--h1)", "var(--h2)", "var(--h3)", "var(--h4)", "var(--h5)"];
  const lvl = n => n === 0 ? 0 : n === 1 ? 1 : n <= 2 ? 2 : n <= 4 ? 3 : n <= 7 ? 4 : 5;
  ["Mon", "Wed", "Fri"].forEach((d, i) => el("text", { x: 0, y: 22 + (1 + 2 * i) * (cell + gap) - 4 }, s).textContent = d);
  let total = 0, active = 0;
  for (let d = new Date(start), i = 0; d <= today; d.setDate(d.getDate() + 1), i++) {
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`, n = D.daily[key] || 0;
    total += n; active += n > 0;
    const x = 34 + Math.floor(i / 7) * (cell + gap), y = 14 + d.getDay() * (cell + gap);
    if (d.getDate() === 1) el("text", { x, y: 9 }, s).textContent = d.toLocaleString(undefined, { month: "short" });
    const r = el("rect", { x, y, width: cell, height: cell, rx: 3, fill: steps[lvl(n)] }, s), label = d.toDateString();
    hover(r, `<b>${n}</b> solved<br><span style="color:var(--muted)">${label}</span>`);
  }
  $("heat-sub").textContent = `${total} problems on ${active} active days in the last year`;
  const lg = document.createElement("div"); lg.className = "legend";
  lg.innerHTML = `less ${steps.map(c => `<i style="background:${c};margin:0"></i>`).join(" ")} more`;
  $(host).appendChild(lg);
  const sc = $(host).parentElement; sc.scrollLeft = sc.scrollWidth;  // newest weeks visible on small screens
}

function drawTags() {
  const T = D.tags, host = "chart-tags";
  if (!T.length) { $(host).innerHTML = `<p class="empty">No topic evidence yet.</p>`; return; }
  const W = widthOf(host, 320), row = 26, m = { l: Math.min(170, W * 0.36), r: 50, t: 16, b: 22 }, Ht = m.t + m.b + T.length * row, s = svgIn(host, W, Ht);
  const lo = Math.floor((Math.min(...T.map(t => t.mean), me.skill) - 150) / 100) * 100, hi = Math.ceil((Math.max(...T.map(t => t.mean), me.skill) + 150) / 100) * 100;
  const X = v => m.l + (v - lo) / (hi - lo) * (W - m.l - m.r);
  const step = (hi - lo) / 100 > 8 ? 200 : 100;
  for (let v = lo; v <= hi; v += step) { el("line", { x1: X(v), x2: X(v), y1: m.t, y2: Ht - m.b, stroke: "var(--grid)" }, s); el("text", { x: X(v), y: Ht - 6, "text-anchor": "middle" }, s).textContent = v; }
  T.forEach((t, i) => {
    const y = m.t + i * row + 5, h = row - 10, w = Math.max(3, X(t.mean) - X(lo));
    el("text", { x: m.l - 10, y: y + h - 3, "text-anchor": "end", style: "fill:var(--ink-2)" }, s).textContent = t.tag;
    el("rect", { x: X(lo), y, width: w, height: h, rx: 4, fill: "var(--data)", opacity: t.ev < 3 ? 0.4 : 1 }, s);
    el("text", { x: X(lo) + w + 6, y: y + h - 3 }, s).textContent = t.mean;
    const hb = el("rect", { x: 0, y: y - 5, width: W, height: row, fill: "transparent" }, s);
    hover(hb, `<b>${esc(t.tag)}</b> ${t.mean} ± ${t.sd}<br>evidence ${t.ev}${t.ev < 3 ? " (thin)" : ""}${t.need != null ? `<br>training need ${t.need.toFixed(2)}` : "<br>locked at your level"}`);
  });
  el("line", { x1: X(me.skill), x2: X(me.skill), y1: m.t - 6, y2: Ht - m.b, stroke: "var(--ink)", "stroke-dasharray": "3 3" }, s);
  el("text", { x: X(me.skill) + 5, y: m.t - 4, style: "fill:var(--ink);font-weight:600" }, s).textContent = `overall ${me.skill}`;
}

function drawCharts() { if ($("tab-overview").classList.contains("active")) { drawRating(); drawBands(); drawHeat(); drawLC(); } if ($("tab-topics").classList.contains("active")) drawTags(); }
let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(drawCharts, 150); });

/* ---------- leetcode ---------- */
function renderLeetCode() {
  const st = (D.sync_status || {}).LeetCode, P = LC.profile;
  $("lc-sub").textContent = LC.handle ? `${LC.handle} · ${LC.tracked} solves tracked by ascent` : "No LeetCode handle configured.";
  $("lc-alert").innerHTML = st && !st.ok ? `<div class="alert" role="alert"><span>⚠</span><div><b>LeetCode sync failed on the last build.</b> Showing whatever was saved before.<br>
      <code>${esc(st.error)}</code><br><span style="color:var(--ink-2)">LeetCode sometimes refuses automated requests. Codeforces data and LeetCode problem ratings (zerotrac) are unaffected.</span></div></div>` : "";
  if (!LC.handle) { $("lc-card").innerHTML = `<p class="empty">Set <code>LC_HANDLE</code> in netlify.toml (or <code>ascent init --lc</code>) to track LeetCode.</p>`; return; }
  const rating = P && P.contest_rating ? Math.round(P.contest_rating) : (LC.rating ? Math.round(LC.rating) : null);
  const solved = P ? P.solved : null;
  const rows = solved ? [["Easy", solved.Easy || 0], ["Medium", solved.Medium || 0], ["Hard", solved.Hard || 0]] : [];
  const mx = Math.max(1, ...rows.map(r => r[1]));
  $("lc-card").innerHTML = `
    <div class="lc-top">
      <div><div class="l">Contest rating</div><div class="v ${rating ? "grad" : ""}">${rating ?? "1500"}</div><div class="sub">${rating ? (P && P.top_percentage ? `top ${P.top_percentage}% · ` : "") + (n => `${n} contest${n === 1 ? "" : "s"}`)(P ? P.attended : D.lc_history.length) : "starting rating: no rated contests yet"}</div></div>
      <div><div class="l">Solved</div><div class="v">${solved ? (solved.All || 0) : "–"}</div><div class="sub">${solved ? "all time (public profile)" : "profile not loaded"}</div></div>
    </div>
    ${rows.map(([n, v]) => `<div class="diff"><span>${n}</span><div class="t"><div style="width:${Math.round(v / mx * 100)}%"></div></div><span class="mono">${v}</span></div>`).join("")}
    ${LC.recent.length ? `<div class="sub" style="margin-top:14px">Recently accepted (tracked)</div><ul class="recent">${LC.recent.slice(0, 6).map(r => `<li><a href="https://leetcode.com/problems/${esc(r.pid.slice(3))}/" target="_blank" rel="noopener">${esc(r.name || r.pid.slice(3))}</a><span class="mono" style="color:var(--muted)">${r.rating && r.rating_source === "zerotrac" ? r.rating : "–"}</span></li>`).join("")}</ul>` : ""}`;
  $("lc-rating-sub").textContent = rating ? `now ${rating}` : "";
}

/* ---------- oracle ---------- */
function parseQuery(q) {
  let m = q.match(/codeforces\.com\/(?:problemset\/problem|contest)\/(\d+)\/(?:problem\/)?([a-z]\d?)/i);
  if (m) return { pid: `CF:${m[1]}${m[2].toUpperCase()}` };
  m = q.match(/leetcode\.com\/problems\/([a-z0-9-]+)/i);
  if (m) return { pid: "LC:" + m[1].toLowerCase() };
  m = q.match(/^\s*(?:cf\s*)?(\d{1,4})\s*([a-z]\d?)\s*$/i);
  if (m) return { pid: `CF:${m[1]}${m[2].toUpperCase()}` };
  return null;
}
function search(q) {
  q = q.trim().toLowerCase();
  if (!q) return [];
  const direct = parseQuery(q);
  if (direct && byPid[direct.pid]) return [byPid[direct.pid]];
  const toks = q.split(/\s+/);
  const out = [];
  for (const p of problems) {
    if (!toks.every(t => p.key.includes(t))) continue;
    let s = 0;
    const nm = p.name.toLowerCase();
    if (nm === q || p.id.toLowerCase() === q || String(p.num) === q) s += 100;
    if (nm.startsWith(q)) s += 30;
    if (String(p.cid) === q) s += 40;
    s += (p.cid || p.num || 0) / 1e5;
    out.push([s, p]);
  }
  return out.sort((a, b) => b[0] - a[0]).slice(0, 8).map(x => x[1]);
}
let sugg = [], active = -1;
const qEl = $("q"), sEl = $("suggest");
function renderSuggest() {
  sEl.innerHTML = sugg.map((p, i) => `<li role="option" aria-selected="${i === active}" data-i="${i}">
     <span class="plat">${p.plat}</span><span class="mono" style="color:var(--ink-2);flex:none">${esc(p.plat === "CF" ? p.id : "#" + (p.num ?? ""))}</span>
     <span class="s-name">${esc(p.name)}</span><span class="s-meta">${p.rating ?? "–"}${p.status === "solved" ? " · ✓" : ""}</span></li>`).join("");
  sEl.classList.toggle("open", sugg.length > 0);
  sEl.parentElement.setAttribute("aria-expanded", sugg.length > 0);
  sEl.querySelectorAll("li").forEach(li => li.onmousedown = e => { e.preventDefault(); pick(+li.dataset.i); });
}
function pick(i) { const p = sugg[i]; if (!p) return; qEl.value = `${p.plat === "CF" ? p.id : p.id} · ${p.name}`; sugg = []; renderSuggest(); select(p, true); }
qEl.addEventListener("input", () => {
  sugg = search(qEl.value); active = sugg.length ? 0 : -1; renderSuggest();
  if (!sugg.length && qEl.value.trim().length > 2) { sEl.innerHTML = `<li style="cursor:default;color:var(--muted)">No match in ${problems.length.toLocaleString()} indexed problems. LeetCode coverage is contest problems (zerotrac-rated) only.</li>`; sEl.classList.add("open"); }
});
qEl.addEventListener("keydown", e => {
  if (e.key === "ArrowDown") { active = Math.min(sugg.length - 1, active + 1); renderSuggest(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { active = Math.max(0, active - 1); renderSuggest(); e.preventDefault(); }
  else if (e.key === "Enter") { if (active >= 0) pick(active); e.preventDefault(); }
  else if (e.key === "Escape") { sugg = []; renderSuggest(); }
});
qEl.addEventListener("blur", () => setTimeout(() => { sEl.classList.remove("open"); }, 120));

const VCLASS = { "TRAIN ON IT": "v-train", OK: "v-ok", SKIP: "v-skip", "ALREADY SOLVED": "v-solved" };
const VICON = { "TRAIN ON IT": "✓", OK: "~", SKIP: "✕", "ALREADY SOLVED": "★" };

function gaugeSVG(score) {
  const r = 90, cx = 110, cy = 110, len = Math.PI * r;
  return `<svg viewBox="0 0 220 125" aria-hidden="true"><defs><linearGradient id="gg" x1="0" x2="1"><stop offset="0" stop-color="var(--crit)"/><stop offset=".5" stop-color="var(--warn)"/><stop offset="1" stop-color="var(--good)"/></linearGradient></defs>
    <path d="M${cx - r} ${cy} A${r} ${r} 0 0 1 ${cx + r} ${cy}" fill="none" stroke="var(--grid)" stroke-width="16" stroke-linecap="round"/>
    <path class="g-fill" d="M${cx - r} ${cy} A${r} ${r} 0 0 1 ${cx + r} ${cy}" fill="none" stroke="url(#gg)" stroke-width="16" stroke-linecap="round" stroke-dasharray="${len}" stroke-dashoffset="${len}" data-target="${len * (1 - score / 100)}" style="transition:stroke-dashoffset 1s cubic-bezier(.2,.8,.2,1)"/></svg>`;
}

function alternatives(p) {
  if (p.plat !== "CF") return problems.filter(x => x.plat === "LC" && !x.status && lcLevel && x.rating >= lcLevel + 100 && x.rating <= lcLevel + 300).slice(0, 60)
    .map(x => [evaluate(x).score, x]).sort((a, b) => b[0] - a[0]).slice(0, 3).map(x => x[1]);
  const tags = new Set(p.tags.filter(t => !t.startsWith("*")));
  const cand = problems.filter(x => x.plat === "CF" && x !== p && !x.status && !x.special && x.rating && x.rating >= me.level + 100 && x.rating <= me.level + 300
    && x.cid >= 1000 && x.tags.some(t => tags.has(t)));
  return cand.map(x => [evaluate(x).score + x.cid / 1e5, x]).sort((a, b) => b[0] - a[0]).slice(0, 3).map(x => x[1]);
}

function pickCard(p, res, label) {
  return `<button class="pick" data-pid="${esc(p.pid)}">
    <div class="top"><span class="bucket">${esc(label || p.plat)}</span><span class="mini-score">${res.score}</span></div>
    <div class="name">${esc(p.plat === "CF" ? p.id : "#" + p.num)} · ${esc(p.name)}</div>
    <div class="why">${esc((res.breakdown.find(b => b[0] > 0) || [0, ""])[1])}</div>
    <div class="foot"><span class="chip strong">${p.rating ?? "–"}${p.source === "estimated" ? " est." : ""}</span>${p.tags.filter(t => !t.startsWith("*")).slice(0, 3).map(t => `<span class="chip">${esc(t)}</span>`).join("")}</div></button>`;
}
function bindPicks(root) { root.querySelectorAll(".pick").forEach(b => b.onclick = () => { const p = byPid[b.dataset.pid]; if (p) { location.hash = "#oracle/" + encodeURIComponent(p.pid); window.scrollTo({ top: 0, behavior: "smooth" }); } }); }

function select(p, push) {
  if (push) history.replaceState(null, "", "#oracle/" + encodeURIComponent(p.pid));
  const res = evaluate(p);
  const alts = alternatives(p);
  const tags = p.tags.filter(t => !t.startsWith("*"));
  const pp = res.p_solve;
  $("result").innerHTML = `<div class="card result">
    <div class="gauge">${gaugeSVG(res.score)}<div class="score" id="g-score">${res.score}</div><div class="of" id="g-of">worth-it score / 100</div>
      <div class="verdict ${VCLASS[res.verdict]}" id="g-verdict">${VICON[res.verdict]} ${res.verdict}</div>
      ${pp != null ? `<div class="pbar"><div class="lbl"><span>Your clean-solve chance</span><b>${Math.round(pp * 100)}%</b></div><div class="track"><div class="fill" style="width:0" data-w="${Math.round(pp * 100)}%"></div></div></div>` : ""}
    </div>
    <div>
      <div class="ptitle"><span class="plat">${p.plat}</span><h2><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.plat === "CF" ? p.id : "#" + (p.num ?? ""))} · ${esc(p.name)} ↗</a></h2></div>
      <div class="chips">
        <span class="chip strong">${p.rating ? p.rating + (p.source === "estimated" ? " (estimated)" : p.source === "zerotrac" ? " (zerotrac)" : "") : "unrated"}</span>
        ${p.solved != null ? `<span class="chip">${p.solved.toLocaleString()} solvers</span>` : ""}
        ${p.trick >= 0.5 ? `<span class="chip">tricky ${p.trick.toFixed(2)}</span>` : ""}
        ${tags.map(t => `<span class="chip">${esc(t)}</span>`).join("")}
        ${p.status ? `<span class="chip strong">${p.status === "solved" ? "✓ you solved it" : "attempted, unsolved"}</span>` : ""}
      </div>
      <ul class="reasons" id="reasons">${reasonsHTML(res)}</ul>
      <details class="deep" id="deep"><summary>Deep analysis: paste the statement</summary>
        <p class="sub">The brain reads the words, notes which section each one appears in (story, input, output, notes), parses the constraints and re-scores. Nothing leaves your browser.</p>
        <textarea id="stmt" placeholder="Paste the full statement, including the Input / Output headings..."></textarea>
        <button class="btn" id="run">Analyze statement</button><div id="deep-out"></div></details>
      ${alts.length ? `<div class="section-head" style="margin-top:22px"><h3>Better use of the same time</h3><p class="sub">${p.plat === "CF" ? "Unsolved, in your growth zone, sharing a topic." : "Unsolved, contest-rated, in your growth zone."}</p></div><div class="pick-grid" id="alts">${alts.map(a => pickCard(a, evaluate(a), "alternative")).join("")}</div>` : ""}
    </div></div>`;
  requestAnimationFrame(() => {
    const g = document.querySelector(".g-fill"); if (g) g.style.strokeDashoffset = g.dataset.target;
    const f = document.querySelector(".pbar .fill"); if (f) f.style.width = f.dataset.w;
  });
  if ($("alts")) bindPicks($("alts"));
  $("run").onclick = () => deepAnalyze(p);
  $("picks-head").style.display = "none"; $("picks").style.display = "none";
  qEl.value = `${p.plat === "CF" ? p.id : p.id} · ${p.name}`;
}

function reasonsHTML(res) {
  return res.breakdown.map(([n, w]) => `<li><span class="pts ${n > 0 ? "pos" : n < 0 ? "neg" : "zero"}">${n > 0 ? "+" : ""}${n}</span><span>${esc(w)}</span></li>`).join("");
}

function updateTop(res, label) {
  $("g-score").textContent = res.score;
  $("g-of").textContent = label;
  const v = $("g-verdict"); v.className = "verdict " + VCLASS[res.verdict]; v.textContent = `${VICON[res.verdict]} ${res.verdict}`;
  const g = document.querySelector(".g-fill"); const len = Math.PI * 90; g.style.strokeDashoffset = String(len * (1 - res.score / 100));
  $("reasons").innerHTML = reasonsHTML(res);
}

function highlight(text, hits) {
  const spans = hits.filter(h => h.index != null).sort((a, b) => a.index - b.index);
  let out = "", pos = 0;
  for (const h of spans) {
    if (h.index < pos) continue;
    out += esc(text.slice(pos, h.index)) + `<mark title="${esc(h.signal)}">${esc(text.slice(h.index, h.index + h.match.length))}</mark>`;
    pos = h.index + h.match.length;
  }
  return out + esc(text.slice(pos));
}

function deepAnalyze(p) {
  const text = $("stmt").value;
  if (!text.trim()) return;
  const sections = Brain.splitSections(text);
  const res = evaluate(p, sections);
  const c = res.constraints;
  const pred = Object.entries(res.predicted).slice(0, 6), mx = pred.length ? pred[0][1] : 1;
  const bySec = {};
  for (const h of res.hits) (bySec[h.section] = bySec[h.section] || []).push(h);
  const blocks = Object.entries(sections).filter(([k]) => k !== "samples").map(([k, v]) => `<b>${esc(k)}</b>${highlight(Brain.normalize(v), bySec[k] || [])}`).join("");
  $("deep-out").innerHTML = `
    <div class="kv"><span>Intended complexity</span><span>${esc(c.complexity)}</span>
      <span>Bounds</span><span class="mono">${Object.entries(c.bounds).map(([k, v]) => `${esc(k)} ≤ ${v >= 1e6 ? v.toExponential(0) : v}`).join(", ") || "none parsed"}</span>
      <span>Hidden idea</span><span>${res.hidden_idea != null ? res.hidden_idea.toFixed(2) + " (0 = obvious from wording, 1 = nothing on the surface)" : "needs official tags"}</span>
      <span>Statement</span><span>${res.words} words${res.story_ratio != null ? `, ${Math.round(res.story_ratio * 100)}% story` : ""}</span></div>
    ${pred.length ? `<div class="hbars">${pred.map(([t, v]) => `<div class="hbar"><span>${esc(t)}</span><div class="t"><div style="width:${Math.round(v / mx * 100)}%"></div></div><span class="mono">${v.toFixed(1)}</span></div>`).join("")}</div>` : ""}
    <div class="stmt">${blocks || "<i>No sections found.</i>"}</div>`;
  updateTop(res, "re-scored with the statement");
}

function renderPicks() {
  const lo = me.level, hi = me.level + 500, seen = new Set();
  const cand = problems.filter(p => p.plat === "CF" && !p.status && !p.special && p.rating && p.rating >= lo && p.rating <= hi && p.cid >= (D.min_contest_id || 1000));
  const scored = cand.map(p => [evaluate(p).score + p.cid / 1e5, p]).sort((a, b) => b[0] - a[0]);
  const out = [];
  for (const [, p] of scored) { if (seen.has(p.cid)) continue; seen.add(p.cid); out.push(p); if (out.length >= 9) break; }
  $("picks").innerHTML = out.map(p => pickCard(p, evaluate(p), "top pick")).join("") || `<p class="empty">Run a sync to load the catalog.</p>`;
  bindPicks($("picks"));
}

/* ---------- train / topics / brain ---------- */
function renderTrain() {
  $("recs").innerHTML = D.recs.length ? D.recs.map(r => { const p = byPid[r.pid]; const res = p ? evaluate(p) : { score: "–", breakdown: [] };
    return `<button class="pick" data-pid="${esc(r.pid)}"><div class="top"><span class="bucket">${esc(r.bucket)}</span><span class="mini-score">${res.score}</span></div>
      <div class="name">${esc(r.pid.slice(3))} · ${esc(r.name)}</div><div class="why">${esc(r.reason)}</div>
      <div class="foot"><span class="chip strong">${r.rating}${r.rating_source === "estimated" ? " est." : ""}</span><span class="chip">~${r.est_minutes} min</span>${r.tags.slice(0, 2).map(t => `<span class="chip">${esc(t)}</span>`).join("")}</div></button>`; }).join("")
    : `<p class="empty">No recommendations yet: the catalog loads on the first sync.</p>`;
  bindPicks($("recs"));
  const lcCards = (LC.recs || []).map(r => byPid[r.pid]).filter(Boolean);
  $("lc-ladder-sub").textContent = `Contest-rated LeetCode problems (zerotrac) from ${lcLevel + 100} to ${lcLevel + 400}${LC.level_assumed ? ", using LeetCode's starting rating 1500 until you play a contest" : ` (your rating ${lcLevel})`}.`;
  $("lc-recs").innerHTML = lcCards.length ? lcCards.map(p => pickCard(p, evaluate(p), "leetcode")).join("") : `<p class="empty">LeetCode problem ratings not loaded on this build.</p>`;
  bindPicks($("lc-recs"));
  $("reviews").innerHTML = D.reviews.length ? `<table><tr><th>Problem</th><th>Rating</th><th>Why</th></tr>${D.reviews.map(r => `<tr><td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.pid)} · ${esc(r.name)}</a></td><td>${r.rating ?? "–"}</td><td style="color:var(--ink-2)">${esc(r.reason)}</td></tr>`).join("")}</table>`
    : `<p class="empty">Nothing due. Clean slate.</p>`;
}

function cmpRows(rows) {
  const mx = Math.max(...rows.map(r => r[1]));
  const best = Math.min(...rows.map(r => r[1]));
  return `<div class="cmp">${rows.map(([n, v]) => `<div class="row ${v === best ? "best" : ""}"><span>${esc(n)}</span><div class="bar"><div style="width:${Math.round(v / mx * 100)}%"></div></div><span class="mono">${v}</span></div>`).join("")}</div>`;
}
function renderModels() {
  const R = D.models.rating || {}, P = D.models.personal || {}, A = D.models.analyzer || {}, W = D.models.personal_w;
  const rating = R.mae != null ? `
      <div class="metric"><span class="v">${R.mae}</span><span class="sub">mean abs. error (rating points)</span></div>
      <div class="sub">${Math.round(R.within_200 * 100)}% of held-out problems predicted within ±200 · ${R.test_problems.toLocaleString()} test / ${R.train_problems.toLocaleString()} train</div>
      ${cmpRows([["ridge model", R.mae], ["group baseline", R.baseline_mae]])}
      <p class="note">Split: ${esc(R.split)}. Lower is better. ${R.used_for_estimates ? "It beat the baseline, so it estimates ratings for unrated problems." : "It did not beat the baseline, so the baseline is used."}</p>`
    : `<p class="empty">Trains on the next catalog sync.</p>`;
  const personal = P.brier != null ? `
      <div class="metric"><span class="v">${P.brier}</span><span class="sub">Brier score on your newest ${P.test} attempts</span></div>
      <div class="sub">accuracy ${Math.round(P.accuracy * 100)}% · trained on ${P.train} earlier attempts · clean-solve rate ${Math.round(P.test_clean_rate * 100)}%</div>
      ${cmpRows([["your model", P.brier], ["Elo formula", P.brier_elo], ["base rate", P.brier_base_rate]])}
      <p class="note">Brier = mean squared error of the probability; lower is better. Time split: it only learns from the past and is graded on the future.</p>
      ${W ? `<div class="kv">${Object.entries(W).map(([k, v]) => `<span>${esc(k)}</span><span class="mono">${v.toFixed(3)}</span>`).join("")}</div>` : ""}`
    : `<p class="empty">${esc(P.status || "not trained")}. It needs about 80 rated attempts with both clean and messy outcomes, and becomes trustworthy as your history grows.</p>`;
  const nbEval = A.nb_eval ? `<div class="kv"><span>precision@3, lexicon</span><span class="mono">${A.nb_eval.lexicon}</span><span>precision@3, lexicon + NB</span><span class="mono">${A.nb_eval["lexicon+nb"]}</span><span>statements</span><span class="mono">${A.nb_eval.docs}</span></div>`
    : `<p class="note">Topic-prediction accuracy is measured with <code>ascent analyze --train 300</code> then <code>--evaluate</code> (run locally; it downloads statements slowly, as Codeforces asks).</p>`;
  $("models").innerHTML = `
    <div class="card model"><h3><span class="badge b-pass">ML</span>Difficulty model</h3><p class="what">Predicts a problem's rating from contest type, letter, solve count, age and tags. Gives unrated problems a labelled estimate.</p>${rating}</div>
    <div class="card model"><h3><span class="badge b-pass">ML</span>Your solve model</h3><p class="what">Logistic regression on your own attempts: rating above you, your skill in its topics, trickiness, popularity. Powers "your clean-solve chance".</p>${personal}</div>
    <div class="card model"><h3><span class="badge b-pass">NLP</span>Statement reader</h3><p class="what">${A.signals} context-aware signals (where a phrase appears changes what it means) plus a constraint parser that infers the intended complexity.</p>${nbEval}
      <p class="note">The worth-it score combines these measured parts with transparent rules (every point is shown). "Worth it" has no ground truth, so no accuracy figure is claimed for it.</p></div>`;
}

/* ---------- boot ---------- */
renderHero(); renderLeetCode(); renderPicks(); renderTrain(); renderModels(); route();
})();
