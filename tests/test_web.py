"""The website's brain (ascent/web/brain.js) must score exactly like analyzer.py."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ascent import analyzer
from ascent.dashboard import _brain_constants

from .test_analyzer import STATEMENT

WEB = Path(__file__).resolve().parents[1] / "ascent" / "web"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")

CASES = [
    # (meta, statement?, level, weak, expected_solved, status, p_solve)
    ({"rating": 1000, "rating_source": "official", "tags": ["greedy"], "solved_count": 20000, "contest_id": 1900}, True, 1300, [], 20000, None, None),
    ({"rating": 1500, "rating_source": "official", "tags": ["number theory", "constructive algorithms"], "solved_count": 4000,
      "contest_id": 1900, "trick": 0.6}, True, 1300, ["number theory"], 4000, None, 0.3),
    ({"rating": 1600, "rating_source": "estimated", "tags": ["dp"], "solved_count": 300, "contest_id": 2000, "trick": 0.1},
     False, 1300, ["dp"], 3000, "attempted", 0.05),
    ({"rating": 1400, "rating_source": "official", "tags": ["*special", "geometry"], "solved_count": 50000, "contest_id": 650,
      "contest_name": "April Fools Day Contest"}, False, 1300, [], 5000, None, 0.9),
    ({"rating": 1900, "rating_source": "zerotrac", "tags": [], "solved_count": None}, False, 1500, [], None, "solved", None),
    ({"rating": None, "tags": ["implementation"], "solved_count": 10}, True, None, [], None, None, None),
]


def run_node(script: str) -> str:
    return subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, cwd=WEB).stdout


def test_lexicon_patterns_compile_in_js():
    out = run_node(f"""const B=require('./brain.js'); B.init({json.dumps(_brain_constants())}); console.log('ok')""")
    assert out.strip() == "ok"


def test_js_and_python_scores_agree():
    payload = []
    for meta, use_stmt, level, weak, exp, status, p in CASES:
        sections = analyzer.split_sections(STATEMENT) if use_stmt else None
        py = analyzer.analyze("X", sections, meta, level=level, weak_tags=weak, expected_solved=exp,
                              status=status, p_solve=p)
        ratio = (meta["solved_count"] / exp) if exp and meta.get("solved_count") is not None else None
        payload.append({"meta": meta, "sections": sections, "ctx": {"level": level, "weak_tags": weak, "ratio": ratio,
                                                                    "status": status, "p_solve": p},
                        "py": {"score": py.score, "verdict": py.verdict, "points": sorted(x for x, _ in py.breakdown),
                               "hidden": py.hidden_idea, "story": py.story_ratio, "words": py.words}})
    script = f"""
const B = require('./brain.js'); B.init({json.dumps(_brain_constants())});
const cases = {json.dumps(payload)};
console.log(JSON.stringify(cases.map(c => {{ const r = B.analyze(c.meta, c.sections, c.ctx);
  return {{score: r.score, verdict: r.verdict, points: r.breakdown.map(x => x[0]).sort((a,b)=>a-b),
          hidden: r.hidden_idea, story: r.story_ratio, words: r.words}}; }})));"""
    js = json.loads(run_node(script))
    for c, j in zip(payload, js):
        assert j == c["py"], (c["meta"], j, c["py"])


def test_js_constraints_match_python():
    sections = analyzer.split_sections(STATEMENT)
    py = analyzer.parse_constraints(sections)
    script = f"""const B=require('./brain.js'); B.init({json.dumps(_brain_constants())});
console.log(JSON.stringify(B.parseConstraints({json.dumps(sections)})));"""
    js = json.loads(run_node(script))
    assert js["bounds"] == py.bounds and js["complexity"] == py.complexity and js["max_size"] == py.max_size


def test_js_split_sections_matches_python():
    script = f"""const B=require('./brain.js'); console.log(JSON.stringify(B.splitSections({json.dumps(STATEMENT)})));"""
    assert json.loads(run_node(script)) == analyzer.split_sections(STATEMENT)
