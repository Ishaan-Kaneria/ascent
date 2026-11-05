/* ascent brain: the same scoring as ascent/analyzer.py, running in the browser.
 * Lexicon patterns and constants are exported from Python at build time, so
 * there is one source of truth; tests/test_web.py checks both agree. */
(function (root) {
  "use strict";

  const SIZE_VARS = new Set(["n", "m", "q", "|s|", "|t|"]);
  const HEADINGS = { input: "input", output: "output", interaction: "output", note: "note", notes: "note",
    example: "samples", examples: "samples", "sample input": "samples", "sample output": "samples", explanation: "note" };
  const NUM = String.raw`(\d+(?:\.\d+)?\s*\*\s*10\^\d+|10\^\d+|\d[\d,]*)`;
  const BOUND = new RegExp(String.raw`([a-z](?:_\{?[a-z0-9]+\}?)?|\|[a-z]\|)\s*≤\s*` + NUM, "gi");
  const SUM = new RegExp(String.raw`sum of\s+([a-z|]+)\s+(?:over|for) all test cases.{0,40}?(?:≤|not exceed|at most)\s*` + NUM, "gi");

  let LEX = [], SECTION_WEIGHT = {}, IMPL_ONLY = new Set(), LOW_OA = new Set();

  function init(brain) {
    LEX = brain.lexicon.map(([id, pat, w, boost]) => [id, new RegExp(pat, "i"), w, boost ? new Set(boost) : null]);
    SECTION_WEIGHT = brain.section_weight;
    IMPL_ONLY = new Set(brain.impl_only);
    LOW_OA = new Set(brain.low_oa);
  }

  function normalize(text) {
    let t = String(text).split("$$$").join(" ").split("$").join(" ");
    t = t.replace(/\\(le|leq)\b/g, "≤").replace(/\\(ge|geq)\b/g, "≥").replace(/\\(cdot|times)\b/g, "*")
      .replace(/\\(lt)\b/g, "<").replace(/\\(ldots|dots|cdots)\b/g, "...").replace(/\\,|\\ |\\!|~/g, " ")
      .replace(/\^\{\s*([0-9]+)\s*\}/g, "^$1");
    t = t.split("<=").join("≤").split(">=").join("≥");
    return t.replace(/[ \t]+/g, " ");
  }

  function splitSections(text) {
    const out = {}, order = [];
    let cur = "legend";
    for (const line of String(text).split(/\r?\n/)) {
      const key = line.trim().replace(/:$/, "").toLowerCase();
      if (key in HEADINGS) { cur = HEADINGS[key]; continue; }
      if (!(cur in out)) { out[cur] = []; order.push(cur); }
      out[cur].push(line);
    }
    const res = {};
    for (const k of order) { const v = out[k].join("\n").trim(); if (v) res[k] = v; }
    return res;
  }

  function parseNumber(s) {
    s = s.replace(/[, ]/g, "");
    let m = s.match(/^(\d+(?:\.\d+)?)\*10\^(\d+)$/);
    if (m) return parseFloat(m[1]) * Math.pow(10, +m[2]);
    m = s.match(/^10\^(\d+)$/);
    if (m) return Math.pow(10, +m[1]);
    const v = parseFloat(s);
    if (isNaN(v)) throw new Error("bad number");
    return v;
  }

  function parseConstraints(sections) {
    const text = normalize(["input", "legend", "output"].map(k => sections[k] || "").join(" "));
    const c = { bounds: {}, sums: {}, max_size: null, max_value: null, complexity: "unknown", tag_hints: {} };
    for (const m of text.matchAll(BOUND)) {
      const v = m[1].toLowerCase().replace(/[{}]/g, "");
      let val; try { val = parseNumber(m[2]); } catch (e) { continue; }
      c.bounds[v] = Math.max(c.bounds[v] || 0, val);
    }
    for (const m of text.matchAll(SUM)) { try { c.sums[m[1].toLowerCase()] = parseNumber(m[2]); } catch (e) {} }
    const isSize = (k, v) => SIZE_VARS.has(k) || (k === "k" && v <= 2e6);
    const sizes = [], values = [];
    for (const [k, v] of Object.entries(c.bounds)) {
      if (isSize(k, v)) sizes.push(v); else if (k !== "t") values.push(v);
    }
    c.max_size = sizes.length ? Math.max(...sizes) : null;
    c.max_value = values.length ? Math.max(...values) : null;
    const n = c.max_size;
    if (n !== null) {
      if (n <= 12) { c.complexity = "O(n!) or O(2^n * n) - brute force is intended"; c.tag_hints = { "brute force": 0.8, bitmasks: 0.4 }; }
      else if (n <= 25) { c.complexity = "O(2^n) - bitmask DP / meet-in-the-middle"; c.tag_hints = { bitmasks: 1.0, dp: 0.5, "brute force": 0.5 }; }
      else if (n <= 500) { c.complexity = "O(n^3) - interval / cubic DP is fine"; c.tag_hints = { dp: 0.6, "brute force": 0.3 }; }
      else if (n <= 5000) { c.complexity = "O(n^2) - quadratic DP / all pairs"; c.tag_hints = { dp: 0.7, "brute force": 0.2 }; }
      else if (n <= 2e6) { c.complexity = "O(n log n) or O(n) - sort, binary search, greedy, data structures"; c.tag_hints = { greedy: 0.2, sortings: 0.2, "binary search": 0.2 }; }
      else { c.complexity = "n is huge - O(log n) / O(sqrt n) / closed form"; c.tag_hints = { math: 0.8, "number theory": 0.4, "binary search": 0.3 }; }
    }
    if (c.max_value && c.max_value >= 1e12) {
      c.tag_hints = Object.assign({}, c.tag_hints, { math: (c.tag_hints.math || 0) + 0.4, "binary search": (c.tag_hints["binary search"] || 0) + 0.3 });
      c.complexity += "; values up to ~1e" + Math.round(Math.log10(c.max_value)) + ": needs 64-bit and no per-value loops";
    }
    return c;
  }

  function lexiconScan(sections) {
    const scores = {}, hits = [];
    for (const [sec, raw] of Object.entries(sections)) {
      const sw = sec in SECTION_WEIGHT ? SECTION_WEIGHT[sec] : 0.5;
      if (sw === 0) continue;
      const text = normalize(raw);
      for (const [id, rx, weights, boost] of LEX) {
        const m = rx.exec(text);
        if (!m) continue;
        const w = sw * (boost && boost.has(sec) ? 2.0 : 1.0);
        const a = Math.max(0, m.index - 50), b = Math.min(text.length, m.index + m[0].length + 50);
        hits.push({ signal: id, section: sec, weight: w, match: m[0], index: m.index,
          snippet: (a ? "..." : "") + text.slice(a, b).replace(/\n/g, " ").trim() + (b < text.length ? "..." : "") });
        for (const [tag, tw] of Object.entries(weights)) scores[tag] = (scores[tag] || 0) + tw * w;
      }
    }
    return { scores, hits };
  }

  function predictTags(sections) {
    const { scores } = lexiconScan(sections);
    const c = parseConstraints(sections);
    const s = Object.assign({}, scores);
    for (const [t, w] of Object.entries(c.tag_hints)) s[t] = (s[t] || 0) + w;
    return Object.fromEntries(Object.entries(s).sort((a, b) => b[1] - a[1]));
  }

  function hiddenIdea(official, predicted) {
    const real = official.filter(t => !t.startsWith("*"));
    const vals = Object.values(predicted);
    if (!real.length || !vals.length) return null;
    const top = Math.max(...vals) || 1.0;
    const surface = real.reduce((a, t) => a + Math.min(1, (predicted[t] || 0) / (0.8 * top)), 0) / real.length;
    return Math.round((1 - surface) * 100) / 100;
  }

  const pct = x => Math.round(x * 100) + "%";
  const words = s => s.split(/\s+/).filter(Boolean).length;

  /* meta: {rating, rating_source, tags, solved_count, trick, contest_id, contest_name}
   * ctx:  {level, weak_tags, ratio (solved / expected), status, p_solve} */
  function analyze(meta, sections, ctx) {
    ctx = ctx || {};
    const pts = [];
    const allTags = meta.tags || [];
    const tags = allTags.filter(t => !t.startsWith("*"));
    const rating = meta.rating || null;
    let predicted = {}, hits = [], cons = null, story = null, nwords = 0, hid = null;
    if (sections && Object.keys(sections).length) {
      predicted = predictTags(sections);
      hits = lexiconScan(sections).hits;
      cons = parseConstraints(sections);
      const lw = words(normalize(sections.legend || ""));
      const fw = words(normalize((sections.input || "") + " " + (sections.output || "")));
      nwords = lw + fw;
      story = nwords ? Math.round(lw / nwords * 100) / 100 : null;
      hid = hiddenIdea(tags, predicted);
    }
    if (allTags.includes("*special") || (meta.contest_name || "").toLowerCase().includes("april fools"))
      pts.push([-40, "special / April Fools problem: not representative of real contests"]);
    if (rating && meta.rating_source === "zerotrac") pts.push([10, `contest-calibrated rating ${rating} (zerotrac, from LeetCode contest results)`]);
    else if (rating && (meta.rating_source || "official") === "official") pts.push([10, `official rating ${rating}: calibrated by thousands of contestants`]);
    else if (rating) pts.push([3, `rating ${rating} is an ESTIMATE (unrated on Codeforces)`]);
    else pts.push([-10, "no rating and no reliable estimate"]);

    const sc = meta.solved_count;
    if (sc != null && ctx.ratio) {
      const r = ctx.ratio;
      if (r < 0.25) {
        if ((meta.trick || 0) >= 0.5) pts.push([5, `only ${sc} solvers (${pct(r)} of normal for its slot): a genuinely tricky idea`]);
        else pts.push([-8, `only ${sc} solvers (${pct(r)} of normal): possibly obscure, ambiguous or heavy`]);
      } else if (r > 3) pts.push([-5, `${sc} solvers (${r.toFixed(1)}x normal for its slot): probably easier than its rating`]);
      else pts.push([8, `${sc} solvers: a healthy solve count for its slot`]);
    } else if (sc != null) pts.push([0, `${sc} solvers (no baseline to compare against yet)`]);

    if (hid !== null) {
      if (hid >= 0.5) pts.push([15, `hidden idea ${hid.toFixed(2)}: the statement does not reveal its techniques (${tags.join(", ")}), so it trains insight`]);
      else if (hid <= 0.15) pts.push([0, `hidden idea ${hid.toFixed(2)}: the wording points straight at its techniques: good for drilling, less for insight`]);
      else pts.push([7, `hidden idea ${hid.toFixed(2)}: some of the idea is not on the surface`]);
    }
    const trick = meta.trick || 0;
    if (trick >= 0.5) pts.push([8, `trickiness ${trick.toFixed(2)}: observation-heavy (OA/quant style)`]);

    if (tags.length && tags.every(t => IMPL_ONLY.has(t)) && nwords > 450) pts.push([-12, `long (${nwords} words) implementation-only problem: tedious, little to learn`]);
    else if (story !== null && story > 0.75 && nwords > 350) pts.push([-4, `${pct(story)} of the statement is story: lots of reading for the idea`]);
    const low = tags.filter(t => LOW_OA.has(t));
    if (low.length) pts.push([-6, `topic(s) ${low.join(", ")} are rare in OAs / quant interviews`]);
    if (meta.contest_id && meta.contest_id < 700) pts.push([-5, "old problem (pre-2016): style differs from modern rounds and OAs"]);

    if (ctx.level && rating) {
      const d = rating - ctx.level;
      if (d < 0) pts.push([-30, `rated ${rating}, BELOW your level ${ctx.level}: no training value for you`]);
      else if (d < 100) pts.push([5, `at your level (${ctx.level}): warm-up / speed work only`]);
      else if (d <= 300) pts.push([20, `+${d} above your level: the zone where you improve fastest`]);
      else if (d <= 500) pts.push([12, `+${d} above your level: a stretch problem`]);
      else pts.push([-10, `+${d} above your level: too far, you will likely just read the editorial`]);
    }
    const weak = (ctx.weak_tags || []).filter(t => tags.includes(t)).sort();
    if (weak.length) pts.push([10, `covers your weak topic(s): ${weak.join(", ")}`]);
    const p = ctx.p_solve;
    if (p != null) {
      if (p < 0.08) pts.push([-5, `your model gives you ${pct(p)} to solve it cleanly: you would mostly be reading the editorial`]);
      else if (p <= 0.65) pts.push([5, `your model gives you ${pct(p)} to solve it cleanly: hard enough to learn from, but doable`]);
      else pts.push([0, `your model gives you ${pct(p)} to solve it cleanly`]);
    }
    if (ctx.status === "attempted") pts.push([6, "you attempted it and did not solve it: unfinished business"]);

    const score = Math.max(0, Math.min(100, 40 + pts.reduce((a, x) => a + x[0], 0)));
    let verdict = score >= 65 ? "TRAIN ON IT" : score >= 45 ? "OK" : "SKIP";
    if (ctx.status === "solved") verdict = "ALREADY SOLVED";
    pts.sort((a, b) => Math.abs(b[0]) - Math.abs(a[0]));
    return { score, verdict, breakdown: pts, predicted, hits, constraints: cons, story_ratio: story, words: nwords, hidden_idea: hid };
  }

  /* Personal model: same features as ascent/ml.py personal_features. */
  function personalP(model, me, rating, tags, trick, solved) {
    if (!model || !rating) return null;
    const real = tags.filter(t => !t.startsWith("*") && t in me.tag_means);
    const gap = real.length ? real.reduce((a, t) => a + me.tag_means[t] - me.overall_mean, 0) / real.length / 100 : 0;
    const x = { bias: 1, delta: (rating - me.overall_mean) / 100, tag_gap: gap, trick: trick || 0,
      pop: (Math.log1p(solved || 0) - 8) / 2, live: 0 };
    let z = 0;
    for (const k in x) z += (model[k] || 0) * x[k];
    return 1 / (1 + Math.exp(-z));
  }

  const api = { init, normalize, splitSections, parseConstraints, lexiconScan, predictTags, hiddenIdea, analyze, personalP };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Brain = api;
})(typeof window !== "undefined" ? window : globalThis);
