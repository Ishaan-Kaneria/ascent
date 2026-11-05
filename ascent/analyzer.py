"""Problem analyzer: reads a statement and judges whether it is worth YOUR time.

It is a small, fully explainable model. No external LLM, nothing hidden:

1. Signal lexicon. About 45 hand-written patterns ("modulo 998244353",
   "print any", "lexicographically smallest", "play optimally", "flush", ...)
   that point at techniques. Each hit is weighted by the SECTION it appears in
   (story / input / output / notes): "print any" in the output section means a
   constructive problem; "graph" in the story may just be flavour. Every hit is
   reported with its context snippet.
2. Constraint parser. Reads bounds like 1 <= n <= 2*10^5 and infers the
   intended complexity (n <= 20 means 2^n; n <= 5000 means n^2; values up to 1e18
   mean math or log-time ideas). These are the standard rules of thumb.
3. Naive Bayes, trained on real statements. `ascent analyze --train N`
   downloads N real Codeforces statements, learns which words/sections/
   constraints co-occur with each OFFICIAL tag, and blends that with the
   lexicon. `--evaluate` reports held-out precision, so you know how good it
   actually is instead of trusting it blindly.
4. Quality verdict. Combines the above with the solve count (relative to what
   is normal for that contest slot), rating calibration, trickiness, your
   level and weak topics into a 0-100 score with an itemised breakdown and a
   verdict: TRAIN ON IT / OK / SKIP.

"Hidden idea": when the official tags are things the statement gives no
surface hint of (e.g. reads like an array task, is actually constructive or
number theory), the problem tests insight, which is exactly the OA/quant skill.
"""
from __future__ import annotations

import json
import math
import random
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field

SECTION_WEIGHT = {"legend": 1.0, "input": 0.8, "output": 1.2, "note": 0.3,
                  "samples": 0.0, "header": 0.0}

# (id, regex, {tag: weight}, sections where it counts double or None)
LEXICON: list[tuple[str, str, dict, set | None]] = [
    ("modulo", r"\bmodulo\b|998\s*244\s*353|10\^9\s*\+\s*7|1\s*000\s*000\s*007",
     {"combinatorics": 1.0, "dp": 0.6, "math": 0.5}, {"output"}),
    ("count_ways", r"\bnumber of (ways|pairs|subsequences|subarrays|arrays|permutations|sequences|strings)\b",
     {"combinatorics": 0.8, "dp": 0.6}, None),
    ("expected", r"\bexpected (value|number)\b|\bprobabilit", {"probabilities": 1.4, "math": 0.5, "dp": 0.4}, None),
    ("binom", r"\bfactorial|\bbinomial|\\binom|\bn choose k\b", {"combinatorics": 1.0, "math": 0.4}, None),
    ("print_any", r"(multiple|several|many) (possible )?(answers|solutions)|print any|output any|any of them",
     {"constructive algorithms": 1.0}, {"output"}),
    ("shown_exists", r"it can be (shown|proven|proved) that|always exists", {"constructive algorithms": 0.4, "math": 0.4}, None),
    ("report_impossible", r"(print|output) -1|\bimpossible\b|if (it is|there is) no (way|such|answer)",
     {"constructive algorithms": 0.4, "greedy": 0.3}, {"output"}),
    ("permutation", r"\bpermutation", {"constructive algorithms": 0.5, "math": 0.3, "greedy": 0.2}, None),
    ("min_ops", r"\bminimum (possible )?number of (operations|moves|steps|swaps|changes)\b",
     {"greedy": 0.8, "math": 0.3, "constructive algorithms": 0.3}, None),
    ("lex", r"\blexicographically (smallest|minimum|largest|maximum|minimal|maximal)",
     {"greedy": 1.0, "strings": 0.4}, None),
    ("subsequence", r"\bsubsequence", {"dp": 0.7, "greedy": 0.3}, None),
    ("subarray", r"\bsubarray|\bsubsegment|\bcontiguous", {"two pointers": 0.5, "data structures": 0.3, "dp": 0.3}, None),
    ("xor", r"\bxor\b|\bbitwise\b|\\oplus|\\&|\bbits?\b", {"bitmasks": 1.0, "math": 0.3}, None),
    ("pow2", r"\bpowers? of (two|2)\b|2\^\{?[ik]\b", {"bitmasks": 0.6, "math": 0.4}, None),
    ("number_theory", r"\bgcd\b|\blcm\b|greatest common divisor|least common multiple|\bdivisib|\bdivisors?\b|\bprimes?\b|\bcoprime",
     {"number theory": 1.0, "math": 0.5}, None),
    ("parity", r"\bparity\b|\beven\b|\bodd\b", {"math": 0.4, "constructive algorithms": 0.3}, None),
    ("digits", r"\bdigits?\b|decimal (representation|notation)", {"math": 0.5, "brute force": 0.3, "dp": 0.2}, None),
    ("tree", r"\btree\b|\brooted\b|\bleaf|\bleaves\b|\bsubtree", {"trees": 1.0, "dfs and similar": 0.6, "graphs": 0.3, "dp": 0.2}, None),
    ("graph", r"\bgraph\b|\bvertices\b|\bvertex\b|\bedges?\b", {"graphs": 0.8, "dfs and similar": 0.5}, None),
    ("shortest", r"shortest path|minimum (total )?(cost|time|distance) to (reach|travel|get)", {"shortest paths": 1.0, "graphs": 0.4}, None),
    ("components", r"connected components?|\bunion\b|\bmerg(e|ing)\b", {"dsu": 0.8, "graphs": 0.3}, None),
    ("cycle", r"\bcycles?\b", {"graphs": 0.5, "dfs and similar": 0.4}, None),
    ("grid", r"\bgrid\b|\bmatrix\b|\brows?\b.{0,20}\bcolumns?\b|\bcells?\b", {"implementation": 0.4, "dfs and similar": 0.3, "dp": 0.3, "brute force": 0.2}, None),
    ("queries", r"\bquer(y|ies)\b", {"data structures": 0.9, "binary search": 0.3}, {"input"}),
    ("range_update", r"\b(add|assign|update)\b.{0,40}\b(range|segment|from l to r|l to r)\b", {"data structures": 0.8}, None),
    ("string", r"\bstrings?\b|\bcharacters?\b|\blowercase\b", {"strings": 0.8}, None),
    ("palindrome", r"\bpalindrom", {"strings": 0.5, "dp": 0.3, "constructive algorithms": 0.2}, None),
    ("substring", r"\bsubstrings?\b", {"strings": 0.6, "hashing": 0.3, "two pointers": 0.2}, None),
    ("binary_string", r"binary string|consisting (only )?of (the )?(characters )?0 and 1|01-string", {"constructive algorithms": 0.4, "strings": 0.3, "greedy": 0.3}, None),
    ("brackets", r"\bbracket|\bparenthes", {"strings": 0.3, "data structures": 0.3, "dp": 0.3, "greedy": 0.2}, None),
    ("game", r"play(s)? optimally|\bwho (will )?wins?\b|moves? first|alice and bob take turns|\bturns?\b.{0,30}\bplayers?\b", {"games": 1.4, "math": 0.3}, None),
    ("interactive", r"\binteract|\bflush\b|\binteractor\b|\bask (at most|no more than)\b|\bqueries? to the jury", {"interactive": 2.5, "binary search": 0.4}, None),
    ("minmax", r"maximi[sz]e the minimum|minimi[sz]e the maximum|maximum possible minimum|minimum possible maximum", {"binary search": 1.2, "greedy": 0.3}, None),
    ("sorted", r"\bsorted\b|non-decreasing|non-increasing|\bascending\b|\bdescending\b", {"sortings": 0.6, "greedy": 0.3}, None),
    ("geometry", r"\bpolygon|\bangle\b|\bcircle|\bon the plane\b|\bcartesian\b|\bconvex\b", {"geometry": 1.2, "math": 0.3}, None),
    ("k_ops", r"\bat most k\b|\bexactly k\b|\bk operations\b", {"greedy": 0.3, "dp": 0.3, "binary search": 0.2}, None),
    ("segments", r"\bsegments?\b|\bintervals?\b", {"greedy": 0.4, "sortings": 0.4, "data structures": 0.3}, None),
    ("mex", r"\bmex\b|\\operatorname\{mex\}", {"constructive algorithms": 0.4, "greedy": 0.4, "data structures": 0.2}, None),
    ("median", r"\bmedian\b", {"binary search": 0.6, "sortings": 0.4}, None),
    ("simulate", r"\bsimulat|\bstep by step\b|\bfollowing (algorithm|process|procedure)\b", {"implementation": 0.8}, None),
    ("swap", r"\bswaps?\b|\bswapping\b", {"constructive algorithms": 0.4, "greedy": 0.4, "sortings": 0.3}, None),
    ("reverse", r"\brevers(e|ing)\b", {"constructive algorithms": 0.3, "strings": 0.2}, None),
    ("schedule", r"\bdays?\b|\bdeadlines?\b|\bschedul", {"greedy": 0.3, "sortings": 0.2}, None),
    ("max_sum", r"\bmaximum (possible )?(sum|total|value|score|beauty|cost)\b", {"greedy": 0.4, "dp": 0.4}, None),
]
_LEX = [(i, re.compile(p, re.I), w, s) for i, p, w, s in LEXICON]

STOP = set("""a an the of to in and or is are be it that this for on with as by at from you your
we he she they his her its their there each all any can will would must may not no if then than
which who whom what when where how one two first second integer integers number numbers given
following line lines contains contain print output input test tests case cases example examples
note such only also some most least exactly between denote equal""".split())


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    t = text.replace("$$$", " ").replace("$", " ")
    t = re.sub(r"\\(le|leq)\b", "≤", t)
    t = re.sub(r"\\(ge|geq)\b", "≥", t)
    t = re.sub(r"\\(cdot|times)\b", "*", t)
    t = re.sub(r"\\(lt)\b", "<", t)
    t = re.sub(r"\\(ldots|dots|cdots)\b", "...", t)
    t = re.sub(r"\\,|\\ |\\!|~", " ", t)
    t = re.sub(r"\^\{\s*([0-9]+)\s*\}", r"^\1", t)
    t = t.replace("<=", "≤").replace(">=", "≥")
    return re.sub(r"[ \t]+", " ", t)


HEADINGS = {"input": "input", "output": "output", "interaction": "output", "note": "note",
            "notes": "note", "example": "samples", "examples": "samples", "sample input": "samples",
            "sample output": "samples", "explanation": "note"}


def split_sections(text: str) -> dict[str, str]:
    """Plain text (pasted statement) -> sections, using the usual headings."""
    sections: dict[str, list[str]] = defaultdict(list)
    cur = "legend"
    for line in text.splitlines():
        key = line.strip().rstrip(":").lower()
        if key in HEADINGS:
            cur = HEADINGS[key]
            continue
        sections[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

_NUM = r"(\d+(?:\.\d+)?\s*\*\s*10\^\d+|10\^\d+|\d[\d,]*)"
_BOUND = re.compile(r"([a-z](?:_\{?[a-z0-9]+\}?)?|\|[a-z]\|)\s*≤\s*" + _NUM, re.I)
_SUM = re.compile(r"sum of\s+([a-z|]+)\s+(?:over|for) all test cases.{0,40}?(?:≤|not exceed|at most)\s*" + _NUM, re.I)


def parse_number(s: str) -> float:
    s = s.replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\*10\^(\d+)", s)
    if m:
        return float(m.group(1)) * 10 ** int(m.group(2))
    m = re.fullmatch(r"10\^(\d+)", s)
    if m:
        return 10.0 ** int(m.group(1))
    return float(s)


SIZE_VARS = {"n", "m", "q", "|s|", "|t|"}  # 'k' counts as a size only when small


@dataclass
class Constraints:
    bounds: dict = field(default_factory=dict)   # var -> max bound
    sums: dict = field(default_factory=dict)     # var -> bound on sum over tests
    max_size: float | None = None
    max_value: float | None = None
    complexity: str = "unknown"
    tag_hints: dict = field(default_factory=dict)


def parse_constraints(sections: dict[str, str]) -> Constraints:
    text = normalize(" ".join(sections.get(k, "") for k in ("input", "legend", "output")))
    c = Constraints()
    for var, num in _BOUND.findall(text):
        v = var.lower().replace("{", "").replace("}", "")
        try:
            val = parse_number(num)
        except ValueError:
            continue
        c.bounds[v] = max(c.bounds.get(v, 0), val)
    for var, num in _SUM.findall(text):
        try:
            c.sums[var.lower()] = parse_number(num)
        except ValueError:
            pass
    is_size = lambda k, v: k in SIZE_VARS or (k == "k" and v <= 2 * 10 ** 6)
    sizes = [v for k, v in c.bounds.items() if is_size(k, v)]
    values = [v for k, v in c.bounds.items() if not is_size(k, v) and k != "t"]
    c.max_size = max(sizes) if sizes else None
    c.max_value = max(values) if values else None
    n = c.max_size
    if n is not None:
        if n <= 12:
            c.complexity, c.tag_hints = "O(n!) or O(2^n * n) - brute force is intended", {"brute force": 0.8, "bitmasks": 0.4}
        elif n <= 25:
            c.complexity, c.tag_hints = "O(2^n) - bitmask DP / meet-in-the-middle", {"bitmasks": 1.0, "dp": 0.5, "brute force": 0.5}
        elif n <= 500:
            c.complexity, c.tag_hints = "O(n^3) - interval / cubic DP is fine", {"dp": 0.6, "brute force": 0.3}
        elif n <= 5000:
            c.complexity, c.tag_hints = "O(n^2) - quadratic DP / all pairs", {"dp": 0.7, "brute force": 0.2}
        elif n <= 2 * 10 ** 6:
            c.complexity, c.tag_hints = "O(n log n) or O(n) - sort, binary search, greedy, data structures", {"greedy": 0.2, "sortings": 0.2, "binary search": 0.2}
        else:
            c.complexity, c.tag_hints = "n is huge - O(log n) / O(sqrt n) / closed form", {"math": 0.8, "number theory": 0.4, "binary search": 0.3}
    if c.max_value and c.max_value >= 1e12:
        c.tag_hints = {**c.tag_hints, "math": c.tag_hints.get("math", 0) + 0.4, "binary search": c.tag_hints.get("binary search", 0) + 0.3}
        c.complexity += "; values up to ~1e{:.0f}: needs 64-bit and no per-value loops".format(math.log10(c.max_value))
    return c


# ---------------------------------------------------------------------------
# Feature extraction + lexicon scoring
# ---------------------------------------------------------------------------

@dataclass
class Hit:
    signal: str
    section: str
    snippet: str
    weight: float


def lexicon_scan(sections: dict[str, str]) -> tuple[dict[str, float], list[Hit]]:
    scores: dict[str, float] = defaultdict(float)
    hits: list[Hit] = []
    for sec, raw in sections.items():
        sw = SECTION_WEIGHT.get(sec, 0.5)
        if sw == 0:
            continue
        text = normalize(raw)
        for sid, rx, weights, boost in _LEX:
            m = rx.search(text)
            if not m:
                continue
            w = sw * (2.0 if boost and sec in boost else 1.0)
            a, b = max(0, m.start() - 50), min(len(text), m.end() + 50)
            hits.append(Hit(sid, sec, ("..." if a else "") + text[a:b].replace("\n", " ").strip() + ("..." if b < len(text) else ""), w))
            for tag, tw in weights.items():
                scores[tag] += tw * w
    return dict(scores), hits


def features(sections: dict[str, str]) -> set[str]:
    """Binary features for Naive Bayes: section-prefixed words + lexicon ids + constraint class."""
    feats = set()
    for sec, raw in sections.items():
        if SECTION_WEIGHT.get(sec, 0.5) == 0:
            continue
        prefix = {"legend": "L", "input": "I", "output": "O", "note": "N"}.get(sec, "X")
        for w in re.findall(r"[a-z]{3,}", normalize(raw).lower()):
            if w not in STOP:
                feats.add(f"{prefix}:{w}")
                feats.add(f"*:{w}")
    _, hits = lexicon_scan(sections)
    feats |= {f"SIG:{h.signal}" for h in hits}
    feats |= {f"SIG:{h.signal}@{h.section}" for h in hits}
    c = parse_constraints(sections)
    if c.max_size is not None:
        feats.add(f"N:1e{int(math.log10(max(1, c.max_size)))}")
    if c.max_value is not None:
        feats.add(f"V:1e{int(math.log10(max(1, c.max_value)))}")
    return feats


# ---------------------------------------------------------------------------
# Naive Bayes (one-vs-rest Bernoulli, Laplace-smoothed, present features only)
# ---------------------------------------------------------------------------

class NaiveBayes:
    def __init__(self) -> None:
        self.n_docs = 0
        self.tag_docs: Counter = Counter()
        self.feat_docs: Counter = Counter()
        self.tag_feat: dict[str, Counter] = defaultdict(Counter)

    def fit(self, docs: list[tuple[set[str], list[str]]]) -> "NaiveBayes":
        for feats, tags in docs:
            self.n_docs += 1
            self.feat_docs.update(feats)
            for t in set(tags):
                self.tag_docs[t] += 1
                self.tag_feat[t].update(feats)
        return self

    def log_odds(self, feats: set[str]) -> dict[str, float]:
        out = {}
        N = self.n_docs
        for t, nt in self.tag_docs.items():
            if nt < 5 or N - nt < 5:
                continue
            lo = math.log(nt / (N - nt))
            tf = self.tag_feat[t]
            for f in feats:
                df = self.feat_docs.get(f, 0)
                if df < 3:  # too rare to be evidence
                    continue
                a = (tf.get(f, 0) + 1) / (nt + 2)
                b = (df - tf.get(f, 0) + 1) / (N - nt + 2)
                lo += math.log(a / b)
            out[t] = lo
        return out

    def to_json(self) -> str:
        keep = {f for f, c in self.feat_docs.items() if c >= 3}
        return json.dumps({"n_docs": self.n_docs, "tag_docs": self.tag_docs,
                           "feat_docs": {f: self.feat_docs[f] for f in keep},
                           "tag_feat": {t: {f: c for f, c in cnt.items() if f in keep}
                                        for t, cnt in self.tag_feat.items()}})

    @classmethod
    def from_json(cls, s: str) -> "NaiveBayes":
        d = json.loads(s)
        m = cls()
        m.n_docs = d["n_docs"]
        m.tag_docs = Counter(d["tag_docs"])
        m.feat_docs = Counter(d["feat_docs"])
        m.tag_feat = defaultdict(Counter, {t: Counter(c) for t, c in d["tag_feat"].items()})
        return m


def predict_tags(sections: dict[str, str], model: NaiveBayes | None = None) -> dict[str, float]:
    lex, _ = lexicon_scan(sections)
    c = parse_constraints(sections)
    scores = defaultdict(float, lex)
    for t, w in c.tag_hints.items():
        scores[t] += w
    if model and model.n_docs >= 150:
        n = max(1.0, math.sqrt(len(features(sections))))
        for t, lo in model.log_odds(features(sections)).items():
            scores[t] += max(0.0, lo) / n * 2  # damped: NB is overconfident
    return dict(sorted(scores.items(), key=lambda kv: -kv[1]))


def evaluate(docs: list[tuple[dict, list[str]]], folds: int = 5, seed: int = 7) -> dict:
    """Held-out precision@3 for lexicon-only vs lexicon+NB."""
    rng = random.Random(seed)
    docs = docs[:]
    rng.shuffle(docs)
    res = {"lexicon": [0, 0], "lexicon+nb": [0, 0]}
    for k in range(folds):
        test = docs[k::folds]
        train = [d for i, d in enumerate(docs) if i % folds != k]
        nb = NaiveBayes().fit([(features(s), t) for s, t in train])
        for s, tags in test:
            real = {t for t in tags if not t.startswith("*")}
            if not real:
                continue
            for name, model in (("lexicon", None), ("lexicon+nb", nb)):
                top = list(predict_tags(s, model))[:3]
                res[name][0] += len(set(top) & real)
                res[name][1] += len(top) or 1
    return {k: round(a / b, 3) if b else None for k, (a, b) in res.items()} | {"docs": len(docs)}


# ---------------------------------------------------------------------------
# Quality verdict
# ---------------------------------------------------------------------------

@dataclass
class Analysis:
    pid: str
    predicted: dict
    hits: list[Hit]
    constraints: Constraints | None
    story_ratio: float | None
    words: int
    hidden_idea: float | None
    score: int
    verdict: str
    breakdown: list[tuple[int, str]]


IMPL_ONLY = {"implementation", "brute force"}
LOW_OA_VALUE = {"geometry", "fft", "flows", "string suffix structures", "graph matchings", "2-sat"}


def hidden_idea(official: list[str], predicted: dict) -> float | None:
    real = [t for t in official if not t.startswith("*")]
    if not real or not predicted:
        return None
    top = max(predicted.values()) or 1.0
    surface = sum(min(1.0, predicted.get(t, 0) / (0.8 * top)) for t in real) / len(real)
    return round(1 - surface, 2)


def analyze(pid: str, sections: dict[str, str] | None, meta: dict, *, level: int | None,
            weak_tags: list[str] | None = None, model: NaiveBayes | None = None,
            expected_solved: float | None = None) -> Analysis:
    """meta: rating, rating_source, tags, solved_count, trick, kind, contest_id, contest_name."""
    pts: list[tuple[int, str]] = []
    tags = [t for t in meta.get("tags", []) if not t.startswith("*")]
    rating = meta.get("rating")

    predicted, hits, cons, story, words, hid = {}, [], None, None, 0, None
    if sections:
        predicted = predict_tags(sections, model)
        _, hits = lexicon_scan(sections)
        cons = parse_constraints(sections)
        lw = len(normalize(sections.get("legend", "")).split())
        fw = len(normalize(sections.get("input", "") + " " + sections.get("output", "")).split())
        words = lw + fw
        story = round(lw / words, 2) if words else None
        hid = hidden_idea(tags, predicted)

    # Legitimacy / calibration
    if "*special" in meta.get("tags", []) or "april fools" in (meta.get("contest_name") or "").lower():
        pts.append((-40, "special / April Fools problem: not representative of real contests"))
    if rating and meta.get("rating_source", "official") == "official":
        pts.append((10, f"official rating {rating}: calibrated by thousands of contestants"))
    elif rating:
        pts.append((3, f"rating {rating} is an ESTIMATE (unrated on Codeforces)"))
    else:
        pts.append((-10, "no rating and no reliable estimate"))

    # Solve-count health
    sc = meta.get("solved_count")
    if sc is not None and expected_solved:
        ratio = sc / expected_solved
        if ratio < 0.25:
            if (meta.get("trick") or 0) >= 0.5:
                pts.append((5, f"only {sc} solvers ({ratio:.0%} of normal for its slot): a genuinely tricky idea"))
            else:
                pts.append((-8, f"only {sc} solvers ({ratio:.0%} of normal): possibly obscure, ambiguous or heavy"))
        elif ratio > 3:
            pts.append((-5, f"{sc} solvers ({ratio:.1f}x normal for its slot): probably easier than its rating"))
        else:
            pts.append((8, f"{sc} solvers: a healthy solve count for its slot"))
    elif sc is not None:
        pts.append((0, f"{sc} solvers (no baseline to compare against yet)"))

    # Insight vs template
    if hid is not None:
        if hid >= 0.5:
            pts.append((15, f"hidden idea {hid:.2f}: the statement does not reveal its techniques ({', '.join(tags)}), so it trains insight"))
        elif hid <= 0.15:
            pts.append((0, f"hidden idea {hid:.2f}: the wording points straight at its techniques: good for drilling, less for insight"))
        else:
            pts.append((7, f"hidden idea {hid:.2f}: some of the idea is not on the surface"))
    trick = meta.get("trick") or 0
    if trick >= 0.5:
        pts.append((8, f"trickiness {trick:.2f}: observation-heavy (OA/quant style)"))

    # Educational density
    if tags and set(tags) <= IMPL_ONLY and words > 450:
        pts.append((-12, f"long ({words} words) implementation-only problem: tedious, little to learn"))
    elif story is not None and story > 0.75 and words > 350:
        pts.append((-4, f"{story:.0%} of the statement is story: lots of reading for the idea"))
    if set(tags) & LOW_OA_VALUE:
        pts.append((-6, f"topic(s) {', '.join(set(tags) & LOW_OA_VALUE)} are rare in OAs / quant interviews"))
    cid = meta.get("contest_id")
    if cid and cid < 700:
        pts.append((-5, "old problem (pre-2016): style differs from modern rounds and OAs"))

    # Fit for you
    if level and rating:
        d = rating - level
        if d < 0:
            pts.append((-30, f"rated {rating}, BELOW your level {level}: no training value for you"))
        elif d < 100:
            pts.append((5, f"at your level ({level}): warm-up / speed work only"))
        elif d <= 300:
            pts.append((20, f"+{d} above your level: the zone where you improve fastest"))
        elif d <= 500:
            pts.append((12, f"+{d} above your level: a stretch problem"))
        else:
            pts.append((-10, f"+{d} above your level: too far, you will likely just read the editorial"))
    if weak_tags and set(tags) & set(weak_tags):
        pts.append((10, f"covers your weak topic(s): {', '.join(set(tags) & set(weak_tags))}"))

    score = int(max(0, min(100, 40 + sum(p for p, _ in pts))))
    verdict = "TRAIN ON IT" if score >= 65 else ("OK" if score >= 45 else "SKIP")
    return Analysis(pid, predicted, hits, cons, story, words, hid, score, verdict,
                    sorted(pts, key=lambda x: -abs(x[0])))


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_model(conn: sqlite3.Connection) -> NaiveBayes | None:
    row = conn.execute("SELECT value FROM meta WHERE key='nb_model'").fetchone()
    return NaiveBayes.from_json(row["value"]) if row else None


def training_docs(conn: sqlite3.Connection) -> list[tuple[dict, list[str]]]:
    rows = conn.execute("""SELECT s.sections, p.tags FROM statements s JOIN problems p ON p.pid = s.pid""")
    return [(json.loads(r["sections"]), json.loads(r["tags"] or "[]")) for r in rows]


def train(conn: sqlite3.Connection) -> NaiveBayes:
    docs = training_docs(conn)
    nb = NaiveBayes().fit([(features(s), t) for s, t in docs])
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('nb_model', ?)", (nb.to_json(),))
    conn.commit()
    return nb
