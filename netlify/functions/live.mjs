// GET /api/live?cf=<codeforces handle>&lc=<leetcode handle>
//
// Live data for the dashboard, fetched server-side (browsers cannot call the
// LeetCode API directly). Read-only, public profile data only, and limited to
// a fixed set of upstream calls, so this is not an open proxy.
// Responses are cached at Netlify's edge for 60 s to stay polite to both APIs.

const CF_API = "https://codeforces.com/api/";
const LC_API = "https://leetcode.com/graphql";
const HANDLE = /^[A-Za-z0-9_.-]{1,40}$/;
const UA = "ascent-cp-trainer/1.0 (+https://github.com/Ishaan-Kaneria/ascent)";
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function cf(method, params) {
  const r = await fetch(`${CF_API}${method}?${new URLSearchParams(params)}`, { headers: { "User-Agent": UA } });
  let j;
  try { j = await r.json(); } catch { throw new Error(`Codeforces ${method}: HTTP ${r.status}`); }
  if (j.status !== "OK") throw new Error(`Codeforces ${method}: ${j.comment || `HTTP ${r.status}`}`);
  return j.result;
}

export async function codeforces(handle) {
  const info = (await cf("user.info", { handles: handle }))[0];
  await sleep(2100); // Codeforces asks for at most one call every two seconds
  const subs = await cf("user.status", { handle, from: 1, count: 100 });
  return {
    rating: info.rating ?? null, max_rating: info.maxRating ?? null, rank: info.rank ?? null,
    submissions: subs
      .filter(s => s.problem && s.problem.contestId && s.problem.contestId < 100000)
      .map(s => ({ id: s.id, t: s.creationTimeSeconds, v: s.verdict || null, pt: s.author && s.author.participantType,
                   cid: s.problem.contestId, idx: s.problem.index, name: s.problem.name, rating: s.problem.rating ?? null })),
  };
}

export async function leetcode(handle) {
  const query = `query($u: String!) {
    matchedUser(username: $u) { submitStatsGlobal { acSubmissionNum { difficulty count } } }
    userContestRanking(username: $u) { rating attendedContestsCount topPercentage }
    recentAcSubmissionList(username: $u, limit: 20) { id title titleSlug timestamp }
  }`;
  const r = await fetch(LC_API, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json", Origin: "https://leetcode.com",
               Referer: "https://leetcode.com/", "User-Agent": UA },
    body: JSON.stringify({ query, variables: { u: handle } }),
  });
  let j;
  try { j = await r.json(); } catch { throw new Error(`LeetCode: HTTP ${r.status}`); }
  if (j.errors) throw new Error(`LeetCode: ${j.errors.map(e => e.message).join("; ")}`);
  const d = j.data || {};
  if (!d.matchedUser) throw new Error(`LeetCode user '${handle}' not found`);
  const solved = Object.fromEntries(d.matchedUser.submitStatsGlobal.acSubmissionNum.map(x => [x.difficulty, x.count]));
  const cr = d.userContestRanking || {};
  return {
    profile: { solved, contest_rating: cr.rating ?? null, attended: cr.attendedContestsCount || 0, top_percentage: cr.topPercentage ?? null },
    recent: (d.recentAcSubmissionList || []).map(s => ({ id: s.id, slug: s.titleSlug, title: s.title, t: +s.timestamp })),
  };
}

const json = (body, status = 200, cache = true) => new Response(JSON.stringify(body), {
  status,
  headers: {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    ...(cache ? { "Netlify-CDN-Cache-Control": "public, s-maxage=60, stale-while-revalidate=60" } : {}),
  },
});

export default async (req) => {
  const u = new URL(req.url);
  const cfH = u.searchParams.get("cf") || "", lcH = u.searchParams.get("lc") || "";
  if ((cfH && !HANDLE.test(cfH)) || (lcH && !HANDLE.test(lcH)) || (!cfH && !lcH)) {
    return json({ error: "pass ?cf=<handle> and/or ?lc=<handle>" }, 400, false);
  }
  const out = { fetched_at: Math.floor(Date.now() / 1000) };
  const wrap = (p) => p.then(v => v, e => ({ error: String(e && e.message || e).slice(0, 300) }));
  const [c, l] = await Promise.all([cfH ? wrap(codeforces(cfH)) : null, lcH ? wrap(leetcode(lcH)) : null]);
  if (c) out.cf = c;
  if (l) out.lc = l;
  return json(out);
};

export const config = { path: "/api/live" };
