from ascent import analyzer
from ascent.sources.codeforces import parse_statement_html

# A statement written for this test in Codeforces style (not copied from CF).
STATEMENT = r"""
You are given an array $$$a$$$ of $$$n$$$ integers. In one operation you may choose an index and
replace $$$a_i$$$ with $$$a_i \oplus x$$$. Find the minimum number of operations to make the
array non-decreasing.
Input
The first line contains $$$t$$$ ($$$1 \le t \le 10^4$$$) - the number of test cases.
Each test case contains $$$n$$$ and $$$x$$$ ($$$1 \le n \le 2 \cdot 10^5$$$, $$$0 \le x < 2^{30}$$$),
then $$$a_1, \ldots, a_n$$$ ($$$0 \le a_i \le 10^{9}$$$).
It is guaranteed that the sum of $$$n$$$ over all test cases does not exceed $$$2 \cdot 10^5$$$.
Output
For each test case print the answer, or -1 if it is impossible. If there are multiple answers, print any.
Note
In the first test case nothing needs to be done.
"""


def test_split_sections():
    s = analyzer.split_sections(STATEMENT)
    assert {"legend", "input", "output", "note"} <= set(s)
    assert "print any" in s["output"]


def test_constraints_parse_latex():
    c = analyzer.parse_constraints(analyzer.split_sections(STATEMENT))
    assert c.bounds["n"] == 200000
    assert c.bounds["t"] == 10000
    assert c.bounds["a_i"] == 1e9
    assert c.sums["n"] == 200000
    assert "n log n" in c.complexity


def test_constraint_classes():
    for bound, expect in [("18", "2^n"), ("5000", "n^2"), ("400", "n^3"), ("10^{18}", "huge")]:
        c = analyzer.parse_constraints({"input": f"$$$1 \\le n \\le {bound}$$$"})
        assert expect in c.complexity, (bound, c.complexity)


def test_lexicon_context_and_section_weight():
    s = analyzer.split_sections(STATEMENT)
    scores, hits = analyzer.lexicon_scan(s)
    by_sig = {h.signal: h for h in hits}
    assert by_sig["print_any"].section == "output"
    assert by_sig["print_any"].weight == 2.4  # output weight 1.2, boosted x2 in output
    assert "xor" in by_sig and "min_ops" in by_sig
    assert scores["constructive algorithms"] > 0 and scores["bitmasks"] > 0
    assert "print any" in by_sig["print_any"].snippet


def test_same_phrase_in_story_counts_less_than_in_output():
    out_scores, _ = analyzer.lexicon_scan({"output": "If there are multiple answers, print any."})
    story_scores, _ = analyzer.lexicon_scan({"legend": "If there are multiple answers, print any."})
    assert out_scores["constructive algorithms"] > story_scores["constructive algorithms"]


def test_interactive_detected():
    pred = analyzer.predict_tags({"legend": "This is an interactive problem.", "output": "After each query do not forget to flush the output."})
    assert next(iter(pred)) == "interactive"


def test_hidden_idea():
    pred = analyzer.predict_tags(analyzer.split_sections(STATEMENT))
    assert analyzer.hidden_idea(["bitmasks", "greedy"], pred) < 0.5   # on the surface
    assert analyzer.hidden_idea(["number theory", "games"], pred) > 0.5  # not on the surface


def test_verdict_rejects_below_level():
    meta = {"rating": 1000, "rating_source": "official", "tags": ["greedy"], "solved_count": 20000, "contest_id": 1900}
    res = analyzer.analyze("CF:1900A", analyzer.split_sections(STATEMENT), meta, level=1300, expected_solved=20000)
    assert res.verdict == "SKIP"
    assert any("BELOW your level" in why for _, why in res.breakdown)


def test_verdict_accepts_good_zone_problem():
    meta = {"rating": 1500, "rating_source": "official", "tags": ["number theory", "constructive algorithms"],
            "solved_count": 4000, "contest_id": 1900, "trick": 0.6}
    res = analyzer.analyze("CF:1900C", analyzer.split_sections(STATEMENT), meta, level=1300,
                           weak_tags=["number theory"], expected_solved=4000)
    assert res.verdict == "TRAIN ON IT", res.breakdown


def test_april_fools_skipped():
    meta = {"rating": 1500, "tags": ["*special"], "contest_name": "April Fools Day Contest 2024", "contest_id": 1952}
    assert analyzer.analyze("CF:1952C", None, meta, level=1300).verdict == "SKIP"


def test_naive_bayes_learns_tag_words():
    docs = []
    for i in range(120):
        docs.append(({"legend": f"a tree with vertices rooted subtree item{i}"}, ["trees"]))
        docs.append(({"legend": f"count strings modulo palindrome item{i}"}, ["strings"]))
    nb = analyzer.NaiveBayes().fit([(analyzer.features(s), t) for s, t in docs])
    lo = nb.log_odds(analyzer.features({"legend": "given a rooted tree, answer for every subtree"}))
    assert lo["trees"] > lo["strings"]
    restored = analyzer.NaiveBayes.from_json(nb.to_json())
    assert restored.n_docs == nb.n_docs


def test_evaluate_runs():
    docs = [({"legend": "rooted tree subtree vertices"}, ["trees"]) for _ in range(30)] + \
           [({"legend": "string palindrome characters"}, ["strings"]) for _ in range(30)]
    res = analyzer.evaluate(docs)
    assert res["docs"] == 60 and res["lexicon+nb"] is not None


def test_parse_cf_statement_html():
    html = """<html><body><div class="problem-statement">
      <div class="header"><div class="title">C. Test</div><div class="time-limit">2 seconds</div></div>
      <div><p>You are given a rooted tree with $$$n$$$ vertices.</p></div>
      <div class="input-specification"><div class="section-title">Input</div><p>$$$1 \\le n \\le 2 \\cdot 10^5$$$</p></div>
      <div class="output-specification"><div class="section-title">Output</div><p>Print any valid answer.</p></div>
      <div class="sample-tests"><pre>3</pre></div>
      <div class="note"><div class="section-title">Note</div><p>Explanation.<br>More.</p></div>
    </div><div>outside</div></body></html>"""
    s = parse_statement_html(html)
    assert "rooted tree" in s["legend"]
    assert s["input"].startswith("$$$1")
    assert "Print any" in s["output"]
    assert "outside" not in " ".join(s.values())
    assert "C. Test" in s["header"]


def test_large_k_is_a_value_not_a_size():
    c = analyzer.parse_constraints({"input": r"$$$1 \le n \le 2 \cdot 10^5$$$, $$$1 \le k \le 10^{18}$$$"})
    assert c.max_size == 200000 and c.max_value == 1e18
    assert "n log n" in c.complexity


def test_choose_an_index_is_not_combinatorics():
    scores, hits = analyzer.lexicon_scan({"legend": "Choose an index i and increase a_i by one."})
    assert "binom" not in {h.signal for h in hits}
