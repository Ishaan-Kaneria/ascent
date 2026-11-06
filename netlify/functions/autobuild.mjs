// Scheduled hourly: rebuild the site ONLY when there is something
// new since the last build (a new submission, an LC accepted problem, or a
// rating change after a contest). The full rebuild retrains the models and
// recomputes readiness; the page itself already shows new solves live.
//
// Netlify's Free plan counts every production deploy (15 of 300 monthly
// credits, so about 20 deploys a month), so rebuilds are rationed: at most one every
// AUTOBUILD_MIN_HOURS (default 72, about 10 a month). The page shows new solves
// live without any deploy; only the slower-moving numbers (skill estimate,
// readiness gates, trained models) wait for a rebuild.
//
// Settings in Netlify (Site configuration -> Environment variables):
//   NETLIFY_BUILD_HOOK  = the URL of a build hook (Build & deploy -> Build hooks). Required;
//                         without it this function only logs and does nothing.
//   AUTOBUILD_MIN_HOURS = optional, minimum hours between rebuilds (default 72).

import { codeforces, leetcode } from "./live.mjs";

const DAY = 86400;

export async function shouldRebuild(info, cfData, lcData, now = Math.floor(Date.now() / 1000), minHours = 72) {
  const since = info.generated_at || 0;
  const reasons = [];
  if (now - since < minHours * 3600) {
    return { rebuild: false, reasons: [`last build ${((now - since) / 3600).toFixed(1)} h ago (< ${minHours} h)`] };
  }
  if (cfData && !cfData.error) {
    const fresh = cfData.submissions.filter(s => s.t > since && s.v && s.v !== "TESTING");
    if (fresh.length) reasons.push(`${fresh.length} new Codeforces submission(s)`);
    if (info.cf_rating != null && cfData.rating != null && cfData.rating !== info.cf_rating) {
      reasons.push(`Codeforces rating ${info.cf_rating} -> ${cfData.rating}`);
    }
  }
  if (lcData && !lcData.error) {
    const fresh = lcData.recent.filter(s => s.t > since);
    if (fresh.length) reasons.push(`${fresh.length} new LeetCode accepted problem(s)`);
  }
  // A build that keeps failing must not burn build minutes forever: only act on
  // activity from the last day.
  const newest = Math.max(0, ...(cfData && !cfData.error ? cfData.submissions.map(s => s.t) : []),
                          ...(lcData && !lcData.error ? lcData.recent.map(s => s.t) : []));
  const stale = now - newest > DAY;
  return { rebuild: reasons.length > 0 && !stale, reasons };
}

export default async () => {
  const hook = process.env.NETLIFY_BUILD_HOOK;
  const site = process.env.URL;
  if (!hook) { console.log("autobuild: NETLIFY_BUILD_HOOK is not set; nothing to do"); return; }
  if (!site) { console.log("autobuild: site URL unknown; nothing to do"); return; }
  const minHours = Number(process.env.AUTOBUILD_MIN_HOURS ?? 72);
  const info = await (await fetch(new URL("/build-info.json", site), { cache: "no-store" })).json();
  const age = Math.floor(Date.now() / 1000) - (info.generated_at || 0);
  if (age < minHours * 3600) { console.log(`autobuild: last build ${(age / 3600).toFixed(1)} h ago; waiting for ${minHours} h`); return; }
  const wrap = (p) => p.then(v => v, e => ({ error: String(e && e.message || e) }));
  const [c, l] = await Promise.all([info.handle ? wrap(codeforces(info.handle)) : null,
                                    info.lc_handle ? wrap(leetcode(info.lc_handle)) : null]);
  const { rebuild, reasons } = await shouldRebuild(info, c, l, undefined, minHours);
  if (c && c.error) console.log("autobuild: codeforces:", c.error);
  if (l && l.error) console.log("autobuild: leetcode:", l.error);
  if (!rebuild) { console.log("autobuild: up to date"); return; }
  const r = await fetch(hook, { method: "POST", body: "{}" });
  console.log(`autobuild: triggered rebuild (${reasons.join(", ")}): HTTP ${r.status}`);
};

// Checking is cheap (no deploy); hourly is plenty given the minimum gap above.
export const config = { schedule: "@hourly" };
