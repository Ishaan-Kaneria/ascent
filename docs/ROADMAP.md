# Roadmap: Codeforces ~1000 → Expert, LeetCode ~1500 → OA-ready

Each phase ends when **`ascent readiness --target X` passes all of its gates**,
not after a fixed number of weeks or problems. The time ranges assume about
2 focused hours a day plus contests. They are typical, not promised.

| Phase | Exit test | Typical time |
|---|---|---|
| 1. Pupil | `readiness --target 1200` | 1–2 months |
| 2. Specialist | `readiness --target 1400` | 2–4 months |
| 3. Expert | `readiness --target 1600` | 3–6 months |
| 4. OA profile (alongside 2–3) | `readiness --profile oa` | in parallel |

## Every phase: the same weekly shape
- **Rated rounds:** every Div. 2, Div. 3 and Educational round you can make.
  Upsolve at least one problem you couldn't do in-contest.
- **Virtual contests:** at least one a week if there's no rated round.
  Speed and consistency gates only move with timed rounds.
- **Daily:** `ascent today`. Timer on, log editorials honestly.
- **Weekly:** check `ascent skill`. The bottom 3 topics are your
  `--mode weak` problems for the week.

## Phase notes
1. **→ 1200.** Speed on A and B, and getting to the clean idea for C. Main
   topics: greedy, math, implementation, sortings, strings, constructive.
   Most people stall here because they keep solving 800s. Recommendations
   start above your level for exactly that reason.
2. **→ 1400.** Binary search on the answer, prefix sums and two pointers,
   number theory (gcd, divisors, sieve), bitmasks, first DP. Constructive
   problems around 1300–1500 are where the "trick" muscle is built.
3. **→ 1600.** DP (knapsack, intervals, on subsequences), graphs (BFS/DFS,
   DSU, trees), combinatorics with modular arithmetic, data structures
   (sets/maps, then segment tree basics). The Topic coverage gate makes sure
   none of these are skipped.
4. **OA profile.** Weekly and biweekly LeetCode contests to push your LC
   rating up from 1500. LC problems with zerotrac rating 1700+
   (`ascent recommend --lc`). For quant: probability, expected value,
   combinatorics, games. `ascent recommend --tag probabilities` (and
   `combinatorics`, `games`) once they unlock.

## When a sheet helps
Sheets like TLE Eliminators CP31 (sorted by rating) or Striver A2Z (sorted by
topic) are useful as a fixed order. Import your copy with `ascent sheet import`
and use `ascent sheet next`, which skips items below your level unless you ask
for them.
