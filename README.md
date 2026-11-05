# ascent

**An evidence-based trainer for Codeforces and DSA.** It pulls your *real*
submissions, estimates your skill so that easy problems don't inflate it, and
picks real problems **above** your level, weighted toward your weakest topics.
It only says you're ready when every evidence gate passes.

Built for one goal: **Codeforces Expert (1600+) and passing quant / big-tech OAs.**

```
$ ascent readiness
Codeforces 1600
NOT READY: 2/7 gates pass. Fix the failing gates below; there are no shortcuts.

FAIL  Volume at 1600+
      have: 17 clean solves in 120 days
      need: >= 40 problems rated >= 1600, <= 3 wrong attempts, no editorial
      do:   `ascent recommend --mode core` until this hits 40.
...
```

## Principles

1. **No fabricated data.** Every problem it recommends comes from the live
   Codeforces catalog with an official rating. Unrated problems get an
   *estimated* rating, always labelled `(est.)`. Every number about you comes
   from your own submissions or from events you logged yourself.
2. **No easy wins.** Recommendations never go below your level. Solving 300
   problems rated 800 does **not** raise your skill estimate (there's a test
   for exactly this: `tests/test_skill.py`).
3. **No black boxes.** The skill model, the difficulty estimates, the analyzer
   and the readiness thresholds are written out below and live in a few short,
   readable files.
4. **No third-party dependencies.** Pure Python standard library + SQLite.

## Quick start

```bash
git clone https://github.com/<you>/ascent && cd ascent
pip install -e .            # Python 3.10+
ascent init --cf YOUR_CF_HANDLE --lc YOUR_LC_HANDLE --target 1600 --minutes 120
ascent sync                 # first run downloads the catalog (~1 min)
ascent today                # your plan for today
ascent dashboard            # writes ~/.ascent/dashboard.html
```

## Daily loop

```bash
ascent today                       # 1 due review + graded new problems, sized to your time budget
ascent start 1903C                 # start the clock BEFORE reading the statement
# ... solve, submit on Codeforces ...
ascent stop 1903C                  # or: --editorial  /  --gave-up
ascent sync                        # pulls verdicts, wrong attempts, contest results
```

Rules the tool assumes you follow (they are what make the data honest):
- Start the timer before reading. Get stuck for 45 minutes, take one hint.
  Only then read the editorial, and **log it** (`--editorial`). An editorial
  solve counts at roughly a quarter of a clean solve.
- Do every rated round you can, plus virtual contests. Live and virtual
  rounds are timed automatically; nothing else measures speed under pressure.
- Re-solve what `ascent review` puts in front of you (after 7, 21 and 60 days).

## Commands

| Command | What it does |
|---|---|
| `init` | handles, target rating, minutes per day |
| `sync [--refresh] [--rebuild]` | pull Codeforces + LeetCode data; `--rebuild` recreates the DB from the APIs + your journal |
| `stats` | 7/30/90-day volume, average rating solved, solve quality |
| `skill` | overall + per-topic skill (with uncertainty and evidence) |
| `recommend [-n N] [--mode core\|weak\|tricky\|stretch] [--tag dp] [--lc]` | problems above your level |
| `today [--minutes M]` | a plan that fits your time budget |
| `start / stop / log / mark` | timers, manual attempts, non-API problems (GfG, CSES, ...) |
| `review [--done ID --clean]` | spaced-repetition queue for problems you struggled with |
| `readiness [--target 1600] [--profile oa]` | the evidence gates (see below) |
| `sheet import\|list\|progress\|next` | track any external sheet (CP31, Striver A2Z, your own) |
| `analyze ID [--file stmt.txt] \| --train N \| --evaluate` | **problem analyzer** (see below) |
| `dashboard [-o file.html]` | self-contained HTML dashboard (works offline, light/dark) |

## How it works

### Skill model (`ascent/skill.py`)
Codeforces defines a rating so that a person rated *R* solves a problem rated
*D* in contest with probability `1 / (1 + 10^((D - R) / 400))`. Each problem you
attempt becomes one data point:

- **Graded outcome** (`difficulty.Outcome.quality`):

  | Outcome | Credit |
  |---|---|
  | clean solve | 1.0 |
  | 2–4 wrong attempts, or 45–90 min | 0.8 |
  | 5+ wrong attempts, or 90+ min | 0.6 |
  | solved with editorial | 0.25 |
  | not solved | 0 |

- **Practice discount.** A practice solve counts as if the problem were rated
  250 lower (configurable), because no clock means it's easier.
  Live and virtual contest solves count at full rating and with 1.5× weight.
- **Recency.** Old evidence decays with a 90-day half-life.
- **Solve ceiling.** A solve at rating *D* is evidence that you're at least
  about *D* + 200, and nothing more. This fixes the classic flaw where hundreds
  of easy solves with no failures push a logistic estimate upward forever.
- **Prior.** Starts from your official contest rating (±200 after 6 rounds,
  otherwise ±300). The posterior is computed on a grid, so you get a mean and an sd.

Per-topic skill uses the same model on that topic's problems, pulled toward
your overall skill. A model-free check (`skill.frontier`) caps your
"training level" (where recommendations start). The frontier is the highest
100-point band where you've recently solved at least half your attempts cleanly.

### Difficulty (`ascent/difficulty.py`)
- **Official rating** when Codeforces has one.
- **Estimated rating** for unrated problems, from a regression fitted on the
  whole rated catalog. It looks at the contest type (Div. 1/2/3/4, Educational,
  Global) and the problem letter, then adjusts by how many people solved it
  compared with similar problems.
- **Trickiness (0 to 1).** Combines three signals:
  - topics that need a non-obvious idea (constructive, interactive, games, ...)
  - "no named algorithm" problems rated 1400+ (tagged only math, greedy and the like)
  - problems solved by fewer people than their rating predicts
- **Personal difficulty.** How it went *for you*: wrong attempts, minutes,
  editorial, live or practice.

### Recommendations (`ascent/recommend.py`)
Four bands relative to your training level *L*. Inside a band, the list climbs
in 100-point steps.

| Band | Range | Share | Purpose |
|---|---|---|---|
| core | L+100 … L+300 | 50% | where rating is gained |
| weak | L … L+200 | 20% | your 3 weakest topics |
| tricky | L+100 … L+300 | 15% | trickiness ≥ 0.5 (the OA/quant style) |
| stretch | L+300 … L+500 | 15% | |

- Each topic's priority = (how far it sits below your overall skill) + (a bonus
  if you've barely tried it) × how often it shows up in quant/OA work.
- Each topic unlocks at a rating (`state.TAG_TIERS`), so you aren't sent to
  flows at 1100.
- Excluded: problems you've already solved or attempted, April Fools and
  `*special` problems, more than one problem from the same contest, and contests
  older than #1000 (configurable).

### Readiness gates (`ascent/readiness.py`)
For a target *T* (default 1600), **all** of these must pass:

| Gate | Requirement |
|---|---|
| Contest results | rating ≥ T, or estimated median performance over your last 5 settled rounds ≥ T |
| Volume | ≥ 40 problems rated ≥ T solved cleanly in the last 120 days |
| Ceiling | ≥ 10 problems rated ≥ T+200 solved without the editorial |
| Topic coverage | ≥ 3 clean solves rated ≥ T−200 in **every** topic unlocked at T (18 topics for 1600) |
| Speed | ≥ 8 timed solves rated T±100, median ≤ 40 min (for T = 1600) |
| Skill estimate | conservative estimate (mean − 1 sd) ≥ T |
| Consistency | a T−100 problem solved in-contest in ≥ 3 of your last 5 live or virtual rounds |

`--profile oa` swaps in a quant/OA profile:
- the Codeforces 1600 practice gates (volume, ceiling, topics, speed)
- LeetCode contest rating ≥ 1850
- ≥ 30 LeetCode problems rated ≥ 1900 by zerotrac
- ≥ 4 clean solves rated 1500+ in each of probabilities, combinatorics, math,
  games and number theory

**These thresholds are my judgement, not official numbers from Codeforces or
any firm.** They're deliberately strict and easy to edit.

### Problem analyzer (`ascent/analyzer.py`)
`ascent analyze 1903C` reads the statement and decides whether it's **worth
your time**:

1. **Signal lexicon.** About 45 patterns ("modulo 998244353", "print any",
   "lexicographically smallest", "play optimally", "flush", "maximize the
   minimum", ...). Each hit is weighted by **where** it appears (story, input,
   output, notes) and printed with its surrounding text. "print any" in the
   *output* section means constructive; the same words in the story count less.
2. **Constraint parser.** Reads `1 ≤ n ≤ 2·10^5`-style bounds, including the
   LaTeX Codeforces uses, and infers the intended complexity:

   | Bound | Intended approach |
   |---|---|
   | n ≤ 20 | 2^n |
   | n ≤ 5000 | n² |
   | n ≤ 2·10^5 | n log n |
   | values up to 1e18 | math, 64-bit, log-time |

3. **Naive Bayes trained on real statements.**
   - `ascent analyze --train 300` downloads 300 real statements and learns which
     words, sections and constraints go with each official tag.
   - `ascent analyze --evaluate` reports held-out precision@3, so you know how
     good the topic predictions actually are.
4. **Verdict (0–100).** Combines:
   - whether the rating is official or estimated
   - solve count compared with what's normal for that contest slot (very low:
     obscure or flawed; very high: easier than rated)
   - the **hidden-idea score**: are the official topics visible in the wording,
     or does the problem hide its idea? Hidden ideas train insight, which is
     what OAs test.
   - trickiness
   - tedium (long statements that are only implementation)
   - how much the topic matters for OAs
   - how far the rating sits from your level
   - whether it covers one of your weak topics

   Output is **TRAIN ON IT / OK / SKIP** with every point itemised.

Run `ascent analyze ID --file statement.txt` to analyze any statement text,
including ones from other judges.

### Sheets (CP31, Striver A2Z, ...)
ascent **does not ship** other people's curated sheets. Paste the links you
have, one per line or as CSV (see `examples/my_sheet.txt`):

```bash
ascent sheet import cp31 cp31.txt
ascent sheet progress cp31
ascent sheet next cp31        # skips items rated below your level; --include-easy to show them
```

Codeforces and LeetCode links are tracked from your real submissions. Other
sites are ticked off with `ascent mark <url>`.

### Data and the journal
State lives in `~/.ascent/` (set `ASCENT_HOME` to change it):
- `config.json`: your settings
- `journal.jsonl`: an append-only, plain-text log of everything an API can't
  give back (timers, editorial flags, sheet imports, LeetCode ACs)
- `ascent.db`: a SQLite cache

`ascent sync --rebuild` recreates the database from the APIs plus the journal.

## Automatic daily dashboard (GitHub Actions + Pages)

1. Fork or clone this repo.
2. In **Settings → Secrets and variables → Actions → Variables**, add
   `CF_HANDLE` (and optionally `LC_HANDLE`, `TARGET_RATING`).
3. In **Settings → Pages**, set the source to **GitHub Actions**.

`.github/workflows/daily.yml` then syncs every day, commits your journal to
`data/`, and publishes the dashboard to GitHub Pages. In a public repo, your
journal and dashboard are public too (your Codeforces history already is).

## Honest limitations

- **LeetCode.** Its public API only returns your ~20 most recent accepted
  submissions. ascent journals every AC it sees, so history builds up from the
  day you start syncing. Older solves can be added with `ascent mark`.
- **LeetCode difficulty.** Comes from zerotrac's contest-based ratings, which
  exist only for problems that appeared in contests.
- **Contest performance** is estimated from rating changes (`old + 4·Δ`) and
  is a rough figure. The first 6 rounds are excluded because of
  new-account bonuses.
- **Time spent in contest** is measured as the time since your previous AC in
  that round. Use the timer for exact numbers.
- **The analyzer** is a heuristic plus a small statistical model. Treat it as
  a well-informed second opinion and check `--evaluate` before trusting topic
  predictions.

## Development

```bash
pip install -e '.[dev]'
pytest
```

The tests run offline on **synthetic** data shaped like real API responses
(`tests/conftest.py`).

## License

MIT
