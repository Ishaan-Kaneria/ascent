"""Netlify Functions (netlify/functions/*.mjs) with the network stubbed out."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

FN = Path(__file__).resolve().parents[1] / "netlify" / "functions"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")

STUB = r"""
const calls = [];
globalThis.fetch = async (url, opts = {}) => {
  url = String(url); calls.push({ url, method: opts.method || "GET", body: opts.body });
  const ok = (body) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  if (url.includes("user.info")) return ok({ status: "OK", result: [{ handle: "me", rating: 1234, maxRating: 1300, rank: "pupil" }] });
  if (url.includes("user.status")) return ok({ status: "OK", result: [
    { id: 3, creationTimeSeconds: NOW - 60, verdict: "OK", author: { participantType: "PRACTICE" },
      problem: { contestId: 1903, index: "C", name: "Theofanis' Nightmare", rating: 1400 } },
    { id: 2, creationTimeSeconds: NOW - 120, verdict: "WRONG_ANSWER", author: { participantType: "PRACTICE" },
      problem: { contestId: 1903, index: "C", name: "Theofanis' Nightmare", rating: 1400 } },
    { id: 1, creationTimeSeconds: NOW - 9e5, verdict: "OK", author: { participantType: "PRACTICE" },
      problem: { contestId: 100001, index: "A", name: "gym problem" } } ] });
  if (url.includes("leetcode.com/graphql")) return ok({ data: {
    matchedUser: { submitStatsGlobal: { acSubmissionNum: [{ difficulty: "All", count: 50 }, { difficulty: "Easy", count: 30 }] } },
    userContestRanking: { rating: 1610.4, attendedContestsCount: 3, topPercentage: 40.1 },
    recentAcSubmissionList: [{ id: "77", title: "Two Sum", titleSlug: "two-sum", timestamp: String(NOW - 30) }] } });
  if (url.endsWith("/build-info.json")) return ok(INFO);
  if (url.startsWith("https://api.netlify.com/build_hooks/")) return new Response("", { status: 200 });
  throw new Error("unexpected fetch " + url);
};
"""


def run(script: str, now: int = 1_800_000_000, info: dict | None = None) -> dict:
    full = (f"const NOW = {now}; const INFO = {json.dumps(info or {})};" + STUB +
            "globalThis.setTimeout = (f) => f(); Date.now = () => NOW * 1000;"  # no 2 s gap; fixed clock
            + script)
    out = subprocess.run([node, "--input-type=module", "-e", full], capture_output=True, text=True, cwd=FN)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_live_returns_trimmed_codeforces_and_leetcode():
    res = run("""
      const { default: handler } = await import('./live.mjs');
      const r = await handler(new Request('https://x.netlify.app/api/live?cf=me&lc=me2'));
      console.log(JSON.stringify({ status: r.status, cdn: r.headers.get('netlify-cdn-cache-control'), body: await r.json(), calls }));
    """)
    assert res["status"] == 200 and "s-maxage=60" in res["cdn"]
    cf, lc = res["body"]["cf"], res["body"]["lc"]
    assert cf["rating"] == 1234 and cf["max_rating"] == 1300
    assert [s["id"] for s in cf["submissions"]] == [3, 2]  # gym submission dropped
    assert cf["submissions"][0] == {"id": 3, "t": 1_800_000_000 - 60, "v": "OK", "pt": "PRACTICE", "cid": 1903,
                                    "idx": "C", "name": "Theofanis' Nightmare", "rating": 1400}
    assert lc["profile"]["contest_rating"] == 1610.4 and lc["recent"][0]["slug"] == "two-sum"
    assert all(c["method"] == "GET" for c in res["calls"] if "codeforces" in c["url"])


def test_live_rejects_bad_handles():
    res = run("""
      const { default: handler } = await import('./live.mjs');
      const a = await handler(new Request('https://x/api/live?cf=' + encodeURIComponent('a b<script>')));
      const b = await handler(new Request('https://x/api/live'));
      console.log(JSON.stringify([a.status, b.status, calls.length]));
    """)
    assert res == [400, 400, 0]


def test_live_reports_upstream_errors_without_failing():
    res = run("""
      globalThis.fetch = async () => new Response(JSON.stringify({ status: "FAILED", comment: "handle: User not found" }));
      const { default: handler } = await import('./live.mjs');
      const r = await handler(new Request('https://x/api/live?cf=ghost'));
      console.log(JSON.stringify({ status: r.status, body: await r.json() }));
    """)
    assert res["status"] == 200 and "User not found" in res["body"]["cf"]["error"]


def test_autobuild_triggers_only_on_new_activity():
    now = 1_800_000_000
    script = """
      process.env.NETLIFY_BUILD_HOOK = 'https://api.netlify.com/build_hooks/abc';
      process.env.URL = 'https://ascent-cp.netlify.app';
      process.env.AUTOBUILD_MIN_HOURS = '0';
      const { default: run } = await import('./autobuild.mjs');
      await run();
      console.log(JSON.stringify(calls.filter(c => c.url.includes('build_hooks')).length));
    """
    # built before the new submissions -> rebuild
    assert run(script, now, {"generated_at": now - 3600, "handle": "me", "lc_handle": "me2", "cf_rating": 1234}) == 1
    # built after everything, rating unchanged -> nothing to do
    assert run(script, now, {"generated_at": now, "handle": "me", "lc_handle": "me2", "cf_rating": 1234}) == 0
    # only a rating change (contest finished) -> rebuild
    assert run(script, now, {"generated_at": now, "handle": "me", "lc_handle": "", "cf_rating": 1200}) == 1


def test_autobuild_rations_deploys_by_default():
    now = 1_800_000_000
    script = """
      process.env.NETLIFY_BUILD_HOOK = 'https://api.netlify.com/build_hooks/abc';
      process.env.URL = 'https://ascent-cp.netlify.app';
      delete process.env.AUTOBUILD_MIN_HOURS;
      const { default: run } = await import('./autobuild.mjs');
      await run();
      console.log(JSON.stringify(calls.filter(c => c.url.includes('build_hooks')).length));
    """
    info = {"handle": "me", "lc_handle": "", "cf_rating": 1000}
    # new activity, but the last build was 10 h ago: wait (default gap 72 h)
    assert run(script, now, {**info, "generated_at": now - 10 * 3600}) == 0
    # new activity and the last build was 4 days ago: rebuild
    assert run(script, now, {**info, "generated_at": now - 4 * 86400}) == 1


def test_autobuild_does_nothing_without_hook():
    res = run("""
      delete process.env.NETLIFY_BUILD_HOOK;
      const { default: run } = await import('./autobuild.mjs');
      await run();
      console.log(JSON.stringify(calls.length));
    """)
    assert res == 0


def test_autobuild_ignores_stale_activity():
    res = run("""
      const { shouldRebuild } = await import('./autobuild.mjs');
      const cf = { submissions: [{ t: 100, v: 'OK' }], rating: 1000 };
      console.log(JSON.stringify([await shouldRebuild({ generated_at: 50, cf_rating: 1000 }, cf, null, 100 + 2 * 86400, 0),
                                  await shouldRebuild({ generated_at: 50, cf_rating: 1000 }, cf, null, 200, 0)]));
    """)
    assert res[0]["rebuild"] is False and res[1]["rebuild"] is True
