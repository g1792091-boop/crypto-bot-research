# Adversarial verification of the "data" audit (audit_data/)

Nothing under /home/user/crypto-bot-research was modified. No Astral tool was called: my task did not authorise it, so
Astral-based claims were checked only against the auditor's recorded raw responses (audit_data/astral/calls.jsonl).
Heavy jobs: at most 2 processes at a time.

## Scripts and outputs (this directory)

| file | what it does |
|---|---|
| v_qa.py -> v_qa_summary.csv, v_flags.csv | independent bar QA of all 8 CSVs (dup, monotonic, NaN, OHLC, zero volume/range, gaps, wick flags with the task's definitions) |
| v_impact.py -> h15.npy, h5.npy, v_top_pf_drop.csv | trades that exit on a flagged bar; PF of the top combos with those trades removed |
| v_liq.py, v_liqfix.py -> v_liqfix.csv | where the leverage-layer liquidations come from; recount with a "stop fired before liquidation" fix |
| v_gap.py | ATR after the 2026-04-22 gap; trades that span a gap; missing funding |
| v_xframe.py | 5m resampled to 15m vs the 15m file |
| v_wick.py -> v_wick_15m.csv, v_wick.log; v_wick5.py -> v_wick5.log | independent re-run of the wick-shift sensitivity (15m: 3 exits x 5 deltas; 5m: 3 exits x 3 deltas) |
| v_fwd5.py | forward_ALL_5m_v45 reproduction; V4.5 AM+B 64-bar drift with flagged/gap windows removed |
| make_w2.py, w2/ | my own cleaning variant, not the auditor's: EVERY bar's wick winsorised at 2 x ATR14(prev) beyond the body (626 15m + 142 5m clips), full 15m IS and 5m ALL grids re-run with an untouched copy of bt/ |

## Results by finding

### Raw QA (confirmed_ok list)
Independent code reproduces every count: all files have 40,000 rows, 0 duplicates, 0 non-monotonic steps, 0 NaN,
0 OHLC-inconsistent bars and 0 zero-volume bars. BCH has 27 zero-range bars. Gaps and missing bars are BTC 2/97, ETH
3/98, SOL 2/97, LTC 3/118, BCH 16/113, ETH 5m 4/238 and SOL 5m 1/1. Flagged wick bars are 11/12/16/18/42 on 15m and
4/6/8 on 5m (117 in total), the same as the auditor's. No file has stale-feed runs (at most 3 consecutive unchanged
closes, no identical consecutive OHLC rows).
The missing UTC day is 2026-04-22 (2026-04-21 23:45 -> 2026-04-23 00:00), not "2026-04-23" as the handoff says.
Gap moves are BTC +2.43, ETH +2.03, SOL +0.98, LTC -0.14 and BCH +2.63%.

### DATA-1 (outlier wicks): numbers confirmed, severity and bias direction overstated
- ETH 2025-12-13 23:15: low wick 11.37% (38.1 ATR). The other four symbols' wicks on the same bar are 0.055-0.086%.
  ETH 2026-05-17 23:30: 9.68%, while the others show 0.77-1.27%. SOL 2026-08-23 04:30 upper wick 9.13% (15m) and
  9.77% (5m 04:40). All match the auditor.
- 15m: 4,447 trades exit on a flagged bar (TP 2,089, SL 1,992, TRAIL 323, LOCK 43), net +901.9 pct-points.
  Suspect-only: 2,491 trades, net +23.5. 5m: 61 trades (+20.8), suspect-only 34 (+14.8). All match.
- Top-10 by PF with exit-on-flag trades dropped: S6 F_sl2.0_tp3.0 0.928 -> 0.919. Max over 364 combos is 0.919 and
  0 combos have PF >= 1. Matches.
- Nuance the auditor missed on bias direction: in the auditor's own reruns, cleaning RAISES PF on average (mean dPF
  +0.0005 suspect / +0.0012 allflag; PF goes up for 51% of combos). Only the top-10 falls (mean dPF -0.0016 / -0.0073).
  The +902 net comes almost entirely from MARKET-WIDE wicks (real events such as 2025-10-10). The probable bad prints
  net +23.5, which is about zero. So "outlier wicks make results look better" holds only for the best combos, and
  only by <= 0.04 PF.
- My independent harsher cleaning (all wicks winsorised at 2 ATR): 15m 0/364 pass, max PF 0.885 (N08 F_sl2.0_tp3.0),
  0 combos with PF >= 1, 0 with exp > 0, family means unchanged to 3 decimals (F 0.698 -> 0.698, L50 0.358 -> 0.358,
  T 0.598 -> 0.600), top-10 mean dPF -0.018. 5m: 0/52 pass, max PF 0.7986 (was 0.7988).
- Verdict: partially confirmed; severity low; conclusion unchanged.

### DATA-2 (liquidations from bad prints): counts correct, but the causal attribution is wrong
- The totals reproduce from the summary: L5 37, L10 278, L20 1,526, L50 65,827; 5m L20 7, L50 623. The ETH 2025-12-13
  23:15 cluster has 69 of the 278 L10 liquidations. All 37 L5 liquidations are LTC exits at 2025-10-10 21:15/21:30/21:45.
- But engine.py:122-124 computes MAE over bars [entry .. exit bar] INCLUSIVE, using the full exit-bar low/high even
  after the stop has filled. leverage_layer (engine.py:173-177) then marks liquidation when mae <= -(1/L - 0.005).
  A stop placed inside the liquidation distance always fills first on a continuous path, and the engine itself fills
  it at the stop or at a better open. Such trades therefore cannot really be liquidated.
  - L5: 37 of 37 liquidated trades are SL exits whose realised gross (-0.32% .. -15.8%) is better than -19.5%.
  - ETH print: 69 of 69 are SL/TRAIL exits with median stop 0.465% and gross -1.64% .. +0.18%. All of them were
    closed by the stop long before -9.5%.
  - Share of liquidations that are this engine artefact: L10 179/278 (64%), L20 1,142/1,526 (75%),
    L50 41,654/65,827 (63%), 5m L50 534/623 (86%).
  - With the artefact removed: L5 0, L10 99, L20 384, L50 24,173. Remaining L10 liquidations on flagged bars: 0.
    The remaining 99 L10 liquidations are all LTC/SOL entries on 2025-10-10/11. Their stops are 10-18% wide because
    Wilder ATR14 blew up on the crash bar. That part IS data-driven (aggregate crash wick depth -> ATR).
  - eq_L50 is still ~0 after the fix (max 0.011 over 364 combos), and eq_L10 max stays 0.59. "50x -> ruin" holds.
- Verdict: partially confirmed. Bad prints do not by themselves cause liquidations; the engine convention does. The
  data component is small. Liquidation numbers are an upper bound for BOTH reasons.

### DATA-3 (spot vs perp, wick sensitivity): confirmed
My own harness (same idea, independent code) reproduces the family means exactly:
- 15m L50_sl15 at -10/-5/0/+5/+10 bp: 0.553/0.436/0.335/0.249/0.172.
- 15m F_sl2.0_tp3.0: 0.799/0.792/0.773/0.756/0.741.
- 15m T_sl1.5_tr2.5: 0.817/0.744/0.656/0.568/0.487.
- 15m max PF: 0.991 at -10bp (S6 F_sl2.0_tp3.0, 822 trades). 0 combos reach PF >= 1 at any delta.
- 5m L50_sl15: 0.444/0.201/0.064. 5m T: 0.859/0.590/0.260. 5m F: 0.839/0.782/0.688. 5m max 0.905/0.799/0.710.
Median ATR14/close is 0.37-0.53% on 15m and 0.24-0.31% on 5m. The ladder SL (0.30/0.40%) is therefore about 0.6-1.1x
the 15m ATR and about 1-1.6x the 5m ATR. Caveat: a symmetric +-delta shift of both wicks is a crude proxy, and
+-10bp (20bp of range, about 0.4-0.5 ATR on 15m) is large for a systematic difference. The direction is unknown.

### DATA-4 (gaps): confirmed
ATR at the first post-gap bar vs the previous bar: BTC x1.42, ETH x1.27, SOL x1.10, LTC x1.02, BCH x1.56.
Gap-spanning trades: 15m 564/900,334 (0.063%), net +133.3, missing funding 6.23 pct-points, max wall/bar ratio 49.
5m: 71/95,982, net -31.9. max_hold is in bars (engine.py:65) and funding is by bar count (engine.py:128).

### DATA-5 (revisions / cross-pull): confirmed; one sub-claim unverifiable
5m->15m open match: BTC 98.75%, ETH 99.98%, SOL 100.00%. BTC mismatches: 2026-08-19 (96 bars, 17.6bp max open
diff, 5m/15m volume ratio 0.24) and 2026-08-26 (96 bars, ratio 4.03), plus 2026-09-28/29 (69.4bp close, 56.1bp high;
17:00 bar volume 369.2 vs 22.8). The Astral re-query record confirms the revised low (10:05 low 64330 vs file 64347.5).
The re-queried VOLUMES (3.37/10.95; ETH "1,673 ETH") are not in calls.jsonl, because add.py stores only OHLC. That
sub-claim cannot be checked from the records.

### DATA-6 (Astral history): history length corroborated; "clean ~5.3 yr" is overstated
The records support the claims about earliest bars and pre-2020 corruption (BTC 5m 2019-01-02 closes 3821/3975/3816/
3965; ETH 1h 2019-01 median open gap 1.96%, LTC 3.92%). 5m -> 1h and 5m -> 15m aggregate exactly for BTC 2020-07-01.
But I compared each "clean" sample against the 2025-26 distribution of the same metric (median |open/prev close - 1|
over 10 steps of 1h bars, one window per day from our 15m files):
- BTC 2020-04 (0.026%) sits at the 95.9th percentile and 2020-07 at the 95.0th. BTC 2021-01-04 (0.123%) is ABOVE the
  2025-26 maximum (0.085%).
- ETH 2020-02-20 sits at the 97.8th percentile.
- SOL 2021-07, 2022-07 and 2024-01 sit at the 99.5th, 98.6th and 97.8th percentiles.
- BTC 2021-07, 2022-01 and 2024-01 and ETH 2022-01 and 2024-01 look like 2025-26 (7th-46th percentile).
Each point is ONE 11-bar window. The evidence shows that pre-2020 is corrupt. It does not show that 2020-04 onwards
is clean. 2020 and stress days in 2021 (the Coinbase-premium era) still look noisier than any 2025-26 day. Fairer
wording: about 5.3 years exist; about 4.5 years from 2021 are likely usable for BTC/ETH; everything needs bar-level QA
before use. "Never-inspected" is also true only for this project: whoever designed V4.5 and the 31-strategy set
looked at an unknown period.

### DATA-7: confirmed
expected_sha256.txt has 10 lines, including ltcusd-5m and bchusd-5m, and those files do not exist. forward.py:44
hard-codes "-15m". forward_ALL_5m_v45.csv is reproduced exactly by forward.forward_stats on 5m (signals 563/550/528,
fwd64 0.0902/0.1403/0.1781).
V4.5 AM+B 64-bar drift without windows that contain a flagged bar or gap: BTC 0.090% (t 2.79), ETH 0.128% (t 2.69),
SOL 0.187% (t 3.19). It is not a data artefact.

## Missed by the auditor
1. The liquidation artefact above (engine.py:122-124 + 176). It dominates liquidation counts and invalidates the
   "bad print causes liquidation" narrative. It makes leverage results look WORSE and does not change the conclusion.
2. ATR contamination by spike wicks. The LTC 2025-10-10 crash bar pushes Wilder ATR so high that stops for the next
   day's entries are 10-25% wide (e.g. N10/N22 LTC trades held 1,000 bars with sl_dist 14-19%). The exit-on-flag
   analysis cannot see this. The auditor's full reruns do capture it.
3. The bias direction of wick cleaning is mixed (mean PF rises with cleaning). See DATA-1.
