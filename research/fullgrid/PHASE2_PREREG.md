# Full grid, phase 2: checks on the candidates (pre-registered)

Written 2026-10-10 22:10 KST while the full-grid run was computing (grid stage 50 / 2322), before any result of it was
seen. Pinned by `PHASE2_PREREG.sha256`. Changes after results go to `DEVIATIONS.md` with the reason, never here.

Owners 2026-10-10: "추가로 보면 좋을 부분" (cost, years, coins, worst stretch, overlap) and "횡보에 좋은 매매법 + 추세에
좋은 매매법을 합치면" (a role-split team by market state).

## 0. What this is and is not

* Everything here runs on the **candidates** of PREREG.md 6.4 (`confirm.json` rows with `pass`), with the same data,
  engine and leverage table as the run (`run.py`, `kernel.py`, `exchange.json`; the data checked against the run's
  `data_build.json` sha256 per coin before anything is computed; a mismatch stops the checks).
* Sections 1-6 are **descriptive**: they never add, remove or reorder candidates (PREREG 6.5). They decide how much to
  trust and how much to bet. Section 7 is a separate pre-registered test whose passing teams are only proposed as new
  paper accounts in the 후보 리그. Section 8 is a forward monitor.
* No candidate -> sections 1-8 report "후보 없음" and stop. `--all-picks` runs 1-6 on every pick, marked "참고용
  (통과 못 함)", never a candidate.
* DeepSeek rows follow D11: labels and counts, no money figures, unless `FULLGRID_DS_MONEY=1`.
* Unit of a trade: P&L as a fraction of the equity it was sized on (`run.cell_trades` "x"; every signal counts, no
  position limit), unless an item says "account" (`kernel.account`: $5,000, one position at a time over the six coins,
  compounding, bust below $10, the live sizing).

## 1. Cost twice (and three times)

* The kernel's settings vector with the taker fee, the maker fee, the slippage fraction and the round-trip cost the
  ladder uses each multiplied by 2 (and, separately, by 3). Funding is real data and stays. Same exit, same signals.
* Per candidate: mean per trade and trade count in the select and the test period at x1 (the run's), x2 and x3.
* Label (test period): **"비용 2배에도 남음"** when the x2 mean > 0; **"비용 3배에도 남음"** when the x3 mean > 0 too;
  else **"비용에 약함"**.

## 2. Years

* Calendar years by the signal bar's close (UTC): 2020 (the extra period), 2021, ..., 2026 (to 2026-09-30).
* Per year: n, mean, win share, sum. Years with n >= 20 are counted.
* Labels: "플러스인 해 k / m" (k counted years with mean > 0 of m counted years); **"한 해 몰림"** when the total sum
  over 2021-2026 is > 0 and one year's sum is more than 60% of it; **"꾸준함"** when k / m >= 0.7 and not "한 해 몰림".

## 3. Coins and sides

* Per coin (6) and per side (long, short), 2021-01-01 .. 2026-10-01: n, mean, sum.
* Labels: **"코인 고름"** when the mean is > 0 on at least 4 of the coins with n >= 20; **"한 코인 몰림"** when the total
  sum is > 0 and one coin's sum is more than 60% of it; **"한쪽 방향만"** when one side has n >= 30 and mean <= 0 while the
  total mean is > 0.

## 4. Worst stretch (account, live sizing)

* Account over 2021-01-01 .. 2026-10-01 and over the test period alone.
* Longest run of losing trades; worst calendar month (UTC) wallet change; maximum drawdown at closes; longest time
  under water (days from a peak to the first close back at or above it; "회복 못 함" with the days so far when the end
  comes first); bust yes / no.

## 5. Overlap with the rule bot

* An entry = (coin, side, signal bar close). A candidate entry **overlaps** another set when that set has an entry on
  the same coin and side whose signal bar close is within one bar (of the candidate's timeframe) of it.
* Per candidate, 2021-01 .. 2026-09: the share of its entries overlapping (a) its own cell's default numbers (the rule
  bot's account for that strategy and timeframe) and (b) any of the 36 core strategies at default numbers on the same
  timeframe. (The rule bot's DeepSeek accounts are not compared; noted in the report.)

## 6. Candidates together (basket overlap)

* For every pair of candidates, 2021-01 .. 2026-09: (a) entry overlap as in 5, both directions averaged, with the
  coarser of the two timeframes as the window; (b) correlation of daily sums of trade P&L (UTC day of the signal close,
  days where either traded); (c) bad-day overlap as in docs/combo5y.md (each side's worst 5% of losing days; the share
  of one side's worst days that are also the other's worst, both directions averaged; about 5% when unrelated).
* Labels: **"거의 같은 매매"** when (a) >= 50% or (b) >= 0.7; the basket's monthly figures come from `sizing.py`
  (equal split, already registered there).

## 7. Role-split teams by market state (a test)

Question: does a team of a candidate that earns in one market state and another that earns in a different one beat
each of them alone, both of them always on, and the same team with coin-flip sides?

* Market state of a trade = the signal bar's 장세 on the strategy's own chart (`regimes.py`, `paperbot.dash.tools.
  regime5y`: 급변장 / 추세장 / 횡보장 / 보통, from data up to that bar only); "모름" trades are left out of 7.
* **Home states** H(c) of a candidate, from the **select period only**: states with >= 30 select trades whose mean is
  > 0 and > the candidate's mean over all its select trades. H empty, or H = every state with >= 30 trades -> no role.
* **Persistence** (test period), per candidate with a role: d = mean(test trades in H) - mean(test trades outside H);
  d_flip = the same with every trade's side replaced by a coin flip (sha256 of "flip|" + candidate id + signal close,
  as candleague.league.flip_side; the P&L of the flipped side read from the same outcome table). Reported with a
  one-sided week-block bootstrap p for d > 0 (2,000 resamples of UTC weeks, both groups together), BH 10% over the
  candidates with a role. "유지" = BH pass and d - d_flip > 0 and >= 20 test trades in H and >= 20 outside.
* **Teams**: every unordered pair (A, B) of candidates with roles and H(A) and H(B) disjoint. Team trades = A's trades
  in H(A) plus B's trades in H(B).
* **Test** (test period, weekly sums of trade P&L, UTC weeks from Monday): team mean weekly sum > 0 with a one-sided
  week-block bootstrap p (2,000 resamples), BH 10% over all teams; and the team's test total is greater than (i) A's
  total, (ii) B's total, (iii) A + B always on, (iv) the team with flipped sides (same switch); and >= 30 team trades.
  A team passing all of it is **"역할 분담 팀 통과"**.
* Passing teams are proposed to the owners as new paper accounts in the 후보 리그 (both members, each trading only in
  its home states). Nothing goes to money from this test.
* Fewer than two candidates with a role -> "팀을 만들 수 없음".

## 8. Forward monitor in the 후보 리그 (expected range)

* Per candidate, from its **test-period** trades: 10,000 bootstrap resamples (seed sha256 of its id) of the mean of n
  trades for n = 10, 20, 30, 50, 100; the 5th percentile and the median are stored with the candidate.
* In the league, at each of those trade counts, the candidate's forward mean per trade (P&L as a fraction of the
  wallet before the trade) is shown against the band: "예상 범위 안" or **"예상보다 아래 (하위 5% 밑)"**; the first time
  it is below, one [후보 리그] Telegram notice. With many candidates about 1 in 20 is expected below by chance alone;
  the report says so. This is a warning light, not a verdict (the league's judging rule, CONTRACT.md 2, is unchanged).

## 9. Seeds and order

Bootstrap seeds: sha256 of the item's tag (as `run._seed`). Candidates in `confirm.json` order. Every number is
written to `phase2.json` and `teams.json`; the Korean reports are made from those files.
