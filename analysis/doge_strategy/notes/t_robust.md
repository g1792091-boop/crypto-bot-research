# Strategy 5864: generalisation and parameter sensitivity (t_robust)

Scratch dir: `/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/doge/t_robust`
- Nothing under `/home/user/crypto-bot-research` was modified (`git status` is clean).
- No Astral tools were called. Everything is local, using the validated port and the DATA agent's files.
- Total compute: about 5 minutes. The coin run took 9 s, the timeframe run 12 s, and the sensitivity run about 105 s on each of 2 processes.

## 0. Bottom line

1. **DOGE is not special, and the strategy has no edge on any coin.**
   - Setup: the identical strategy on 7 coins, 5m bars, 2025-03-26..2026-09-28.
   - Zero cost, long only: 1 of 7 coins has gross > 0 (SOL +0.0045%/trade, t 0.36). DOGE is -0.0029% and ranks 3rd of 7.
   - Pooled over 7 coins (3,908 trades): -0.0065%/trade, day-cluster t -1.09.
   - Realistic cost: 0 of 21 coin×side cells are net positive (range -0.136% to -0.175%/trade). Best-case maker cost: also 0 of 21.
   - Long+short is no better. Pooled gross is -0.0095%/trade (t -2.22), so if anything it is slightly worse than zero before costs.
2. **No timeframe is net positive.**
   - Setup: DOGE 15m, 30m and 1h, with bar lengths /3, /6, /12 and the TSL either sqrt-scaled or unscaled; 2021-08..2026-09.
   - At realistic cost 0 of 42 cells are net positive. The least-bad is 1h long under Astral's coarse TSL model: -0.065% (unscaled TSL) or -0.086% (sqrt TSL) per trade. Its gross is +0.076% / +0.056% with t 1.15 / 0.81 on about 430 trades over 5 years.
   - When the same stops are walked through the real 5m path, 1h gross falls to -0.110..+0.021%.
3. **The parameter landscape is a flat plateau at about zero gross, which is about -0.13% net.** It is neither a knife-edge nor a profitable plateau.
   - One-at-a-time ±15/±30% perturbations (70 distinct sets): gross is +0.001..+0.020%/trade (PF real 0.35..0.46) in the 67 changed runs with ≥847 trades (some rounding duplicates).
   - The other 3 sets are small samples: 136 trades at -0.014%, 155 at +0.047% (t 0.82) and 4 at +0.53%. Only the 4-trade set is net positive.
   - Joint ±20% cloud (300 draws): median gross +0.003%, 5–95% range -0.033..+0.028%.
     - 0 of 300 are net positive at realistic cost.
     - 0 of 300 have gross day-cluster t > 2.
     - 3.3% are positive even at best-case maker cost.
   - The original sits at the 83rd percentile of the cloud (92nd among draws with ≥500 trades). Its margin over the median, about +0.01%/trade, is 1/14 of the cost.
4. **First half vs second half (original parameters):**
   - Gross is +0.028%/trade (t 2.22 naive, 1.84 day-cluster, n 1,100) from 2021-08 to 2024-03, then -0.003% (n 1,114) from 2024-03 to 2026-09.
   - Net at realistic cost: -0.112% and -0.143%.
   - Across 319 parameter sets, first-half performance does not predict second-half performance: Spearman -0.016, p 0.78. The top 10% by first half average -0.018% in the second half, which is worse than the rest.
5. **The friend's 15-day result comes from the period, not from a parameter knife-edge.**
   - In that window, 60% of random ±20% neighbours also have PF > 1, and 32% have PF ≥ 1.27.
   - None of those neighbours is net positive over 5 years.
   - In the same window BTC (PF 1.37) and LTC (1.33) did as well as DOGE. ETH (0.60) and SOL (0.38) did not.

## 1. Setup

**Engine**
- `doge_strategy.py` is a copy of `../port/doge_strategy.py` (sha 800660e7..., kept as `doge_strategy_orig.py`) with a single change: `_seeded_recursion` uses `scipy.signal.lfilter` instead of a Python loop. This is a speed change only.
- `check_patch.py` verifies it:
  - The maximum absolute difference is 0.0 on every indicator column over 542k bars.
  - The 2,214 full-history trades are identical.
  - The saved window reproduces exactly: 40 trades, PF 1.272255111704368, TR 0.3729606%, maxDD -0.4128%.
- **No port bug found.**

**Conventions (Astral's, as replicated by the PORT agent)**
- `fill='on_close'`.
- `tsl_eval='astral'`: O→H→L; the watermark is raised by the high first; the fill is at the bar close.
- No re-entry on a TSL-exit bar.
- Indicators are seeded at the slice start.
- Warmup is ceil(1.1 × longest EMA) bars (660 for 5m).
- Long only as designed. The short and both sides use the port's exact mirror, as in the t_short agent.

**Costs** (`robust_lib.COSTS`), additive per trade on the zero-cost gross:

| scenario | per trade |
|---|---|
| zero | 0 (Astral default) |
| real | 0.05% taker fee + 0.02% slippage per side, plus 0.01%/8h funding pro rata = 0.14% round trip + funding. Same as the t_history and t_short agents. With 0.015% slippage every net figure improves by 0.01% and no sign changes. |
| best | 0.02% maker on both sides, no slippage, no funding = 0.04% round trip. This is a lower bound, since stop exits are taker orders in reality. |

**Statistics** (`robust_lib.stats`)
- `mean` is % per trade.
- `t` is the naive t. `tc` is the day-clustered t (clusters are UTC entry days, pooled across coins where relevant).
- PF is Σwin%/Σloss% per trade. It is not Astral's $ PF, but the two differ only slightly.
- "Compounded 25%" compounds 25% of equity per trade.

**Data** (`../data`, sha256 prefixes match the DATA agent's MANIFEST)

| file | sha256 prefix |
|---|---|
| doge 5m | 6d87c81730b546c9 |
| btc | d167deed62f52ad1 |
| eth | 481d232c0a6c3a62 |
| sol | ed5e5d20c45e1a3c |
| xrp | a3ade09fd171dba1 |
| ltc | 41d13151c2d27380 |
| bch | e53248299f4bb18f |

**Windows**
- Coins: 2025-03-26 00:00..2026-09-28 23:55. This is the common continuous start, because SOL, XRP and LTC lack 2025-03-25. Every coin is sliced identically, and trades start 2025-03-28 07:00.
- DOGE timeframes and sensitivity: 2021-08-01..2026-09-28, the clean start per the DATA agent.
  - The tick-safe subset (entries ≥ 2022-06-01) is also reported.
  - The half split is at 2024-03-01 15:27, the midpoint of the tradable span.

## 2. Part 1: other coins (`run_coins.py` → `out_coins.txt`, `coins_summary.csv`, `coins_trades.csv`)

- Window 2025-03-26..2026-09-28, 5m, Astral conventions.
- "gross H1 / H2" splits at 2025-12-27.
- The median 5m range gives the scale for the fixed 0.35%/0.20% trailing-stop distances.

#### Long only (as designed)

| coin | n | win 0-cost | gross %/tr (day-cl t) | PF 0-cost | win real | net real %/tr | PF real | compounded 25% real | net best-case %/tr | gross H1 / H2 | buy&hold | median 5m range |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DOGE | 667 | 45.3% | -0.0029 (-0.21) | 0.976 | 30.6% | -0.1431 | 0.319 | -21.3% | -0.0429 | -0.0103 / +0.0058 | -48.8% | 0.285% |
| BTC | 371 | 42.6% | -0.0037 (-0.35) | 0.955 | 23.2% | -0.1440 | 0.189 | -12.5% | -0.0437 | -0.0255 / +0.0167 | -2.7% | 0.225% |
| ETH | 550 | 42.9% | -0.0076 (-0.65) | 0.928 | 27.5% | -0.1478 | 0.246 | -18.4% | -0.0476 | -0.0042 / -0.0123 | +40.3% | 0.280% |
| SOL | 529 | 46.1% | +0.0045 (+0.36) | 1.042 | 30.6% | -0.1357 | 0.299 | -16.4% | -0.0355 | +0.0208 / -0.0135 | -10.8% | 0.306% |
| XRP | 496 | 46.4% | -0.0021 (-0.18) | 0.981 | 32.1% | -0.1424 | 0.277 | -16.2% | -0.0421 | +0.0095 / -0.0197 | -33.4% | 0.289% |
| LTC | 533 | 44.3% | -0.0194 (-1.40) | 0.842 | 29.3% | -0.1597 | 0.247 | -19.2% | -0.0594 | -0.0148 / -0.0258 | -22.2% | 0.275% |
| BCH | 762 | 40.6% | -0.0118 (-0.95) | 0.913 | 29.7% | -0.1521 | 0.330 | -25.2% | -0.0518 | -0.0154 / -0.0076 | -1.5% | 0.194% |

#### Short only (mirror)

| coin | n | win 0-cost | gross %/tr (day-cl t) | PF 0-cost | win real | net real %/tr | PF real | compounded 25% real | net best-case %/tr | gross H1 / H2 |
|---|---|---|---|---|---|---|---|---|---|---|
| DOGE | 780 | 44.7% | +0.0071 (+0.49) | 1.063 | 30.6% | -0.1331 | 0.335 | -22.9% | -0.0329 | +0.0354 / -0.0242 |
| BTC | 292 | 39.7% | -0.0136 (-1.06) | 0.858 | 26.4% | -0.1539 | 0.190 | -10.6% | -0.0536 | -0.0369 / +0.0051 |
| ETH | 452 | 46.7% | +0.0004 (+0.03) | 1.004 | 29.6% | -0.1398 | 0.298 | -14.6% | -0.0396 | +0.0030 / -0.0020 |
| SOL | 534 | 43.1% | -0.0111 (-0.73) | 0.909 | 30.0% | -0.1514 | 0.282 | -18.3% | -0.0511 | -0.0200 / -0.0001 |
| XRP | 480 | 42.9% | -0.0343 (-2.88) | 0.734 | 27.7% | -0.1745 | 0.204 | -18.9% | -0.0743 | -0.0223 / -0.0484 |
| LTC | 499 | 43.9% | -0.0271 (-1.18) | 0.803 | 31.1% | -0.1673 | 0.256 | -18.9% | -0.0671 | -0.0454 / -0.0038 |
| BCH | 762 | 42.5% | -0.0174 (-1.42) | 0.867 | 32.3% | -0.1576 | 0.281 | -26.0% | -0.0574 | -0.0136 / -0.0209 |

#### Long + short (one position at a time)

| coin | n | win 0-cost | gross %/tr (day-cl t) | PF 0-cost | win real | net real %/tr | PF real | compounded 25% real | net best-case %/tr |
|---|---|---|---|---|---|---|---|---|---|
| DOGE | 1447 | 45.0% | +0.0025 (+0.24) | 1.021 | 30.6% | -0.1377 | 0.327 | -39.3% | -0.0375 |
| BTC | 663 | 41.3% | -0.0080 (-0.95) | 0.909 | 24.6% | -0.1484 | 0.189 | -21.8% | -0.0480 |
| ETH | 1002 | 44.6% | -0.0040 (-0.44) | 0.964 | 28.4% | -0.1442 | 0.270 | -30.3% | -0.0440 |
| SOL | 1063 | 44.6% | -0.0033 (-0.34) | 0.971 | 30.3% | -0.1436 | 0.290 | -31.7% | -0.0433 |
| XRP | 976 | 44.7% | -0.0179 (-2.12) | 0.850 | 29.9% | -0.1582 | 0.239 | -32.0% | -0.0579 |
| LTC | 1032 | 44.1% | -0.0232 (-1.86) | 0.822 | 30.1% | -0.1634 | 0.251 | -34.4% | -0.0632 |
| BCH | 1524 | 41.5% | -0.0146 (-1.67) | 0.890 | 31.0% | -0.1548 | 0.306 | -44.6% | -0.0546 |

#### Pooled over coins (day clusters across coins)

| side | coins | n | win 0 | gross %/tr (t) | net real %/tr | PF real | net best %/tr (t) |
|---|---|---|---|---|---|---|---|
| long | all 7 | 3908 | 43.9% | -0.0065 (-1.09) | -0.1468 | 0.283 | -0.0465 (-7.81) |
| long | ex-DOGE | 3241 | 43.6% | -0.0073 (-1.23) | -0.1475 | 0.275 | -0.0473 (-8.02) |
| short | all 7 | 3799 | 43.6% | -0.0125 (-2.15) | -0.1527 | 0.274 | -0.0525 (-9.06) |
| both | all 7 | 7707 | 43.7% | -0.0095 (-2.22) | -0.1497 | 0.278 | -0.0495 (-11.64) |

**Other trailing-stop models (long, gross %/trade)**
- The 5m "fill at stop" variants are more flattering: DOGE +0.0070 (O→H→L) and +0.0324 (O→L→H). No coin has t > 2 under any model.
- The PORT agent showed that on DOGE, a 1m-path walk is worse than all of these 5m models. On 05-13..09-28: Astral +0.015%, 5m O→H→L +0.027%, 1m walk -0.031% / 0.000% (`../port/sub1m_check.csv`).

| coin | astral | ohl_stop | olh_stop |
|---|---|---|---|
| BCH | -0.0118 | -0.0066 | +0.0087 |
| BTC | -0.0037 | -0.0190 | +0.0012 |
| DOGE | -0.0029 | +0.0070 | +0.0324 |
| ETH | -0.0076 | -0.0075 | +0.0134 |
| LTC | -0.0194 | -0.0310 | +0.0038 |
| SOL | +0.0045 | +0.0093 | +0.0372 |
| XRP | -0.0021 | -0.0162 | +0.0029 |

**The friend's window on every coin** (`run_coins_window.py` → `out_coins_window.txt`)
- Slice 2026-09-11..09-28, indicators restart at the slice start, zero cost, Astral metrics.

| coin | long n / WR / PF / TR | short n / WR / PF | both n / WR / PF / TR |
|---|---|---|---|
| DOGE | 40 / 55.0% / 1.272 / +0.373% | 20 / 25% / 0.378 | 60 / 45.0% / 0.898 / -0.239% |
| BTC | 18 / 55.6% / 1.370 / +0.096% | 4 / 25% / 0.925 | 22 / 50% / 1.248 / +0.089% |
| ETH | 25 / 32.0% / 0.604 / -0.326% | 7 / 57% / 1.100 | 32 / 37.5% / 0.679 / -0.312% |
| SOL | 30 / 23.3% / 0.376 / -0.798% | 13 / 54% / 2.260 | 43 / 32.6% / 0.617 / -0.563% |
| XRP | 34 / 52.9% / 0.959 / -0.040% | 10 / 40% / 0.266 | 44 / 50% / 0.776 / -0.296% |
| LTC | 28 / 53.6% / 1.331 / +0.245% | 10 / 40% / 3.750 | 38 / 50% / 1.760 / +0.685% |
| BCH | 42 / 42.9% / 0.831 / -0.248% | 12 / 25% / 0.446 | 54 / 38.9% / 0.698 / -0.670% |

**Reading**
- DOGE's +0.373% in that window is one draw from a noisy cross-section. With realistic cost, every coin/side in the window is net negative except LTC short (+0.035%, 10 trades).
- On the 18-month window DOGE long is -0.003%/trade. On DOGE's own 5-year history it is +0.013% (t 1.32, see Part 3). Neither is distinguishable from zero.

## 3. Part 2: timeframes (`run_tf.py` → `out_tf.txt`, `tf_summary.csv`, `tf_trades.csv`; `tf_years.py` → `out_tf_years.txt`)

**Construction**
- DOGE 5m 2021-08-01..2026-09-28 is resampled with open-labelled, left-closed bins. Our 15m and 1h closes equal the DATA agent's files on 100% of bins.
- Every bar length is divided by the ratio, rounded half-up, with a minimum of 2.
- The TSL distances and watermarks are multiplied by sqrt(ratio) ("sqrt"), or kept at 0.35/0.20 and 0.25/0.375 ("unscaled").
- Warmup is ceil(1.1 × longest EMA).

Resulting parameters (EMA fast/slow/trend/short, StochRSI rsi/minmax/K/D, RSI, CHOP; TSL distance % / watermark %):

| TF | lengths | TSL (sqrt) |
|---|---|---|
| 5m | 63/156/600/21, 70/70/4/3, 26, 14 | 0.350/0.200 wm 0.250/0.375 |
| 15m | 21/52/200/7, 23/23/2/2, 9, 5 | 0.606/0.346 wm 0.433/0.650 |
| 30m | 11/26/100/4, 12/12/2/2, 4, 2 | 0.857/0.490 wm 0.612/0.919 |
| 1h | 5/13/50/2, 6/6/2/2, 2, 2 | 1.212/0.693 wm 0.866/1.299 |

**TSL evaluation models**
- `astral`: Astral's coarse model on the TF bar, with the fill at the TF-bar close. This is what Astral would report.
- `walk5_ohl` / `walk5_olh`: the stop is walked through the real 5m bars inside each TF bar, with the fill at the stop price. Within each 5m bar the order is O→H→L or O→L→H→C. This is the more realistic bracket.
- For the 5m row, `ohl_stop` and `olh_stop` are the same orderings applied to the 5m bars themselves.

Mean %/trade. t is day-clustered. H1 / H2 split at the midpoint of the history.

| TF | TSL | side | TSL model | n | win 0 | gross %/tr (t) | PF 0 | net real %/tr | PF real | comp. 25% real | net best %/tr (t) | net real H1 / H2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 5m | orig | long | astral | 2214 | 46.6% | +0.0126 (+1.32) | 1.097 | -0.1276 | 0.402 | -50.7% | -0.0274 (-2.87) | -0.111 / -0.144 |
| 5m | orig | long | ohl_stop | 2214 | 49.8% | +0.0495 (+4.63) | 1.467 | -0.0907 | 0.513 | -39.6% | +0.0095 (+0.88) | -0.070 / -0.112 |
| 5m | orig | long | olh_stop | 2214 | 46.8% | +0.0360 (+3.76) | 1.279 | -0.1042 | 0.508 | -43.9% | -0.0040 (-0.42) | -0.096 / -0.113 |
| 5m | orig | both | astral | 4561 | 45.8% | +0.0091 (+1.47) | 1.071 | -0.1311 | 0.381 | -77.6% | -0.0309 (-5.01) | -0.122 / -0.139 |
| 15m | sqrt | long | astral | 1138 | 45.4% | +0.0126 (+0.75) | 1.060 | -0.1278 | 0.565 | -30.6% | -0.0274 (-1.63) | -0.108 / -0.147 |
| 15m | sqrt | long | walk5_ohl | 1138 | 45.4% | -0.0067 (-0.48) | 0.960 | -0.1472 | 0.415 | -34.3% | -0.0467 (-3.30) | -0.127 / -0.167 |
| 15m | sqrt | long | walk5_olh | 1138 | 45.1% | +0.0296 (+1.87) | 1.163 | -0.1110 | 0.579 | -27.2% | -0.0104 (-0.66) | -0.101 / -0.121 |
| 15m | unscaled | long | astral | 1139 | 49.1% | +0.0077 (+0.49) | 1.041 | -0.1326 | 0.507 | -31.5% | -0.0323 (-2.05) | -0.114 / -0.151 |
| 15m | unscaled | long | walk5_ohl | 1139 | 51.3% | +0.0498 (+3.87) | 1.464 | -0.0906 | 0.513 | -22.8% | +0.0098 (+0.76) | -0.085 / -0.096 |
| 15m | unscaled | long | walk5_olh | 1139 | 48.6% | +0.0403 (+3.06) | 1.306 | -0.1001 | 0.528 | -24.8% | +0.0003 (+0.02) | -0.107 / -0.093 |
| 30m | sqrt | long | astral | 841 | 42.0% | -0.0252 (-0.88) | 0.920 | -0.1662 | 0.585 | -29.6% | -0.0652 (-2.28) | -0.168 / -0.164 |
| 30m | sqrt | long | walk5_ohl | 841 | 42.6% | -0.0787 (-4.28) | 0.693 | -0.2196 | 0.353 | -37.0% | -0.1187 (-6.45) | -0.200 / -0.238 |
| 30m | sqrt | long | walk5_olh | 841 | 42.7% | -0.0032 (-0.13) | 0.988 | -0.1442 | 0.580 | -26.2% | -0.0432 (-1.84) | -0.141 / -0.147 |
| 30m | unscaled | long | astral | 841 | 43.5% | -0.0227 (-0.87) | 0.917 | -0.1634 | 0.546 | -29.2% | -0.0627 (-2.39) | -0.179 / -0.149 |
| 30m | unscaled | long | walk5_ohl | 841 | 52.7% | +0.0418 (+3.02) | 1.370 | -0.0988 | 0.480 | -18.8% | +0.0018 (+0.13) | -0.106 / -0.092 |
| 30m | unscaled | long | walk5_olh | 841 | 46.8% | +0.0035 (+0.27) | 1.024 | -0.1372 | 0.398 | -25.1% | -0.0365 (-2.85) | -0.153 / -0.122 |
| 1h | sqrt | long | astral | 430 | 43.0% | +0.0558 (+0.81) | 1.146 | -0.0860 | 0.816 | -9.1% | +0.0158 (+0.23) | -0.083 / -0.089 |
| 1h | sqrt | long | walk5_ohl | 430 | 42.1% | -0.1098 (-3.15) | 0.693 | -0.2518 | 0.429 | -23.8% | -0.1498 (-4.30) | -0.296 / -0.206 |
| 1h | sqrt | long | walk5_olh | 430 | 42.1% | -0.0055 (-0.12) | 0.985 | -0.1476 | 0.668 | -14.8% | -0.0455 (-0.99) | -0.218 / -0.075 |
| 1h | unscaled | long | astral | 431 | 47.3% | +0.0761 (+1.15) | 1.235 | -0.0651 | 0.839 | -7.0% | +0.0361 (+0.55) | -0.055 / -0.076 |
| 1h | unscaled | long | walk5_ohl | 431 | 49.2% | +0.0208 (+1.28) | 1.177 | -0.1205 | 0.391 | -12.2% | -0.0192 (-1.18) | -0.118 / -0.123 |
| 1h | unscaled | long | walk5_olh | 431 | 43.6% | -0.0152 (-0.83) | 0.902 | -0.1564 | 0.351 | -15.5% | -0.0552 (-3.03) | -0.162 / -0.150 |

The "both" rows are in `out_tf.txt` and `tf_summary.csv`; none is net positive.

**Reading**
- 0 of 42 cells (TF × TSL scaling × side × TSL model) are net positive at realistic cost. Every first half and every second half is negative too.
- At best-case maker cost, 8 of 42 cells are slightly positive, with max t 0.88. Each one needs either Astral's fill-at-close or a favourable-first stop path.
- **1h looks best only under Astral's coarse model.** Filling at the close of a 1h bar after the stop was touched is very generous: walking the same stops through the 5m bars moves 1h sqrt from +0.056% to -0.110% / -0.006%.
- In `out_tf_years.txt`, 1h sqrt Astral-model gross by year is +0.17, +0.16, -0.08, -0.01, -0.03, +0.24% (2021..2026). Only 8 of 126 (TF×model×year) cells are net positive, all with ≤ 201 trades.
- **Tight fixed stops on coarse bars manufacture gross.**
  - 5m `ohl_stop` shows +0.0495%/trade with day-cluster t 4.63, and 15m unscaled `walk5_ohl` shows +0.0498% (t 3.87). The stop is tightened by a bar's high and then filled at that tightened stop by the same bar's low.
  - The PORT agent's 1m check shows this is an artifact at 5m: +0.027% becomes -0.031% / 0.000% with 1m paths.
  - Anyone who backtests this family with "fill at stop, high first" will see a false t ≈ 4.

## 4. Part 3: parameter sensitivity (`run_sens.py` → `sens_oat.csv`, `sens_cloud_{0,1}.csv`; `analyze_sens.py` → `out_sens.txt`, `sens_all_sets.csv`)

DOGE 5m, long, Astral model, 2021-08-01..2026-09-28. Each set is also run on the friend's Astral window (09-11..09-28 slice, zero cost).

**Original parameters**

| sample | n | win 0 | gross %/tr (t / day-cl t) | PF 0 | net real %/tr | PF real | compounded 25% real | net best %/tr |
|---|---|---|---|---|---|---|---|---|
| full 2021-08-03..2026-09-28 | 2214 | 46.6% | +0.0126 (1.52 / 1.32) | 1.0975 | -0.1276 | 0.402 | -50.7% | -0.0274 |
| first half (to 2024-03-01) | 1100 | 46.5% | +0.0280 (2.22 / 1.84) | 1.223 | -0.1122 | 0.462 | -26.6% | -0.0120 |
| second half | 1114 | 46.6% | -0.0026 (-0.24 / -0.23) | 0.981 | -0.1428 | 0.346 | -32.8% | -0.0426 |
| tick-safe (≥ 2022-06-01) | 1862 | 46.4% | +0.0103 (1.16 / 1.02) | 1.082 | -0.1299 | 0.384 | -45.4% | -0.0297 |
| friend window (Astral slice) | 40 | 55.0% | +0.0374 | 1.2723 | — | — | +0.373% (0 cost) | — |

The friend-window row is identical to Astral: 40 / 0.55 / 1.2723 / +0.3730%. The full-history numbers equal the t_history agent's.

**One-at-a-time** (each of 18 parameters × 0.70 / 0.85 / 1.15 / 1.30; full table in `out_sens.txt`)
- 70 of the 72 runs change the parameter set. D-smoothing at ±15% rounds back to 3.
- Gross per trade:
  - The 67 changed runs with ≥847 trades all lie between +0.0012% and +0.0204%. The median of all 70 is +0.0122% and the base is +0.0126%.
  - Exceptions, all small samples:
    - `chop_max` -30% (43.3): 136 trades at -0.014%.
    - `rsi_min` +15% (59.8): 155 trades at +0.047% (day-cluster t 0.82), net real -0.093%.
    - `rsi_min` +30% (67.6): **4 trades** at +0.53%.
- Only the 4-trade set is net positive. PF real is 0.355..0.457 for the ≥847-trade runs and 0.635 for the 155-trade set.
- The largest day-cluster t is 1.85 (`tsl_d1` +30%, 0.455%).
- Per-parameter ranges of gross (min..max):

  | group | parameter | gross range %/trade |
  |---|---|---|
  | EMA lengths | fast | 0.0125..0.0140 |
  | | slow | 0.0104..0.0146 |
  | | trend | 0.0116..0.0133 |
  | | short | 0.0108..0.0128 |
  | StochRSI | RSI length | 0.0072..0.0122 |
  | | min/max window | 0.0012..0.0090 |
  | | K smoothing | 0.0060..0.0073 |
  | | D smoothing | 0.0095..0.0126 |
  | RSI | length | 0.0107..0.0125 |
  | CHOP | length | 0.0098..0.0128 |
  | thresholds | spread | 0.0116..0.0140 |
  | | k_max | 0.0091..0.0165 |
  | TSL | d1 | 0.0091..0.0179 |
  | | d23 | 0.0123..0.0128 |
  | | wm1 | 0.0118..0.0134 |

- Every one of these ranges is 1/7 of the 0.14% cost or less.
- **Design redundancies found:**
  1. `tsl_wm2` (0.375%) has no effect at all: all four perturbations give identical trades, because stages 2 and 3 both use 0.20%. The "3-stage" trailing stop is really 2-stage.
  2. `rsi_min` at 44.2 and at 36.4 give identical trade lists (3,100 trades). No tradable bar that meets the other entry conditions has RSI26 between 36.4 and 44.2, so the RSI filter only acts above about 44. At 52 it removes 886 of those 3,100 trades.
  3. `spread_min`, `ema_fast` and `tsl_d23` perturbations leave the friend window's 40 trades unchanged.

**Joint cloud** (300 draws, every parameter × U(0.8, 1.2) independently, seed 20260929)

| metric | original | q05 | q25 | median | q75 | q95 | original's percentile |
|---|---|---|---|---|---|---|---|
| trades | 2214 | 90 | 400 | 1426 | 2952 | 4514 | 67.5 |
| gross %/trade | +0.0126 | -0.0328 | -0.0037 | +0.0029 | +0.0093 | +0.0277 | 83.0 |
| day-cluster t (gross) | 1.32 | -1.02 | -0.29 | 0.25 | 0.69 | 1.44 | 92.7 |
| PF 0-cost | 1.0975 | 0.853 | 0.974 | 1.023 | 1.066 | 1.161 | 86.0 |
| net real %/trade | -0.1276 | -0.1729 | -0.1438 | -0.1373 | -0.1308 | -0.1125 | 83.0 |
| PF real | 0.402 | 0.325 | 0.354 | 0.383 | 0.432 | 0.580 | 63.0 |
| compounded 25% real | -50.7% | -78.6% | -62.6% | -38.9% | -12.4% | -3.0% | 35.0 (fewer trades lose less) |
| friend window PF | 1.272 | 0.322 | 0.730 | 1.099 | 1.395 | 2.025 | 68.6 |
| friend window TR | +0.373% | -0.53% | -0.17% | +0.09% | +0.31% | +0.73% | 79.7 |

Shares of the 300 draws:

| condition | share |
|---|---|
| gross > 0 | 64% |
| gross day-cluster t > 2 | 0% |
| net real > 0 | **0%** (maximum -0.025%) |
| net best-case > 0 | 3.3% |
| friend-window PF > 1 | 59.7% |
| friend-window PF ≥ 1.2723 | 32.3% |
| friend-window WR ≥ 55% | 31% |

- Among the 217 draws with ≥500 trades: gross q05/q50/q95 is -0.011/+0.003/+0.015%, the maximum is +0.023% (t 1.42), and the maximum net real is -0.118%.
- The 83 draws with <500 trades are mostly high `rsi_min` (median factor 1.14).

**Persistence across halves** (319 sets with ≥100 trades in each half)

| measure | value |
|---|---|
| Spearman(first-half gross, second-half gross) | -0.016 (p 0.78) |
| top 10% by first half | +0.047% → -0.018% in the second half (the rest: +0.014% → -0.007%) |
| best single set by first half | +0.097% → -0.042% |
| sets net positive at realistic cost in either half | 0 |

- Friend-window PF vs full-history gross: Spearman +0.32 (p 3e-8). The top 10% by window PF (median PF 1.77) still average +0.005% gross and -0.135% net over 5 years, the same as the rest (+0.004% / -0.136%).
- An in-sample OLS of cloud gross on the 18 factors gives R² 0.09. Only `stoch_len` (+0.008% per +20%, t 3.5) and `tsl_wm1` (+0.005%, t 2.0) stand out. Both are in-sample with 18 tests, and each effect is ≤ 1/17 of the cost.

**Verdict**
- The original parameters sit on a broad, flat plateau whose height is about 0 before costs and about -0.13%/trade after realistic costs.
- They are at the upper edge of that plateau (83rd–92nd percentile), but the gap is about 0.01%/trade.
- It is not a knife-edge: small changes do not collapse it. It is also not a profitable plateau: no neighbour pays for costs.
- The positive first half (+0.028%) did not persist (-0.003%), and parameter rankings carry no information from one half to the other.

## 5. Caveats

1. **Astral's coarse TSL model is the main model everywhere.** On DOGE it is *optimistic* relative to 1m paths (by 0.02–0.05%/trade in the PORT agent's check). Every real-money number is therefore probably somewhat worse than shown. The ohl/olh and 5m-walk variants are reported to show the model dependence.
2. **The coin window is only 18 months**, because BTC, ETH, SOL, XRP, LTC and BCH 5m data in `../data` start 2025-03-19. DOGE's 5-year history is used for Parts 2 and 3.
3. **The higher-timeframe versions follow the requested mechanical rule.** At 30m and 1h several lengths hit the minimum of 2 (1h: EMA_short 2, RSI 2, CHOP 2, K/D 2). These are therefore qualitatively different indicators; the result says nothing about every possible higher-timeframe strategy. The 5m-walk bracket still depends on the unknown order inside each 5m bar.
4. **Costs are additive per trade, and funding is always treated as a cost.** Per-trade PF is used, not Astral's $-compounded PF.
5. **The clean history starts 2021-08-01 and includes the 4-decimal tick era up to 2022-05.** The tick-safe subset is reported: gross +0.010%.
   - Two known bad bars remain unclipped: 2021-10-21 11:30/11:35 and 2026-05-17 23:40. Under the Astral fill-at-close model their effect is limited to trades open at that moment.
6. **The sensitivity study covers the long side only, on DOGE only.** Half-split and cloud statistics are exploratory. The one-at-a-time rows at ±30% on thresholds (RSI 36–68, CHOP 43–80) are large moves, and some give tiny samples; see the trade counts.
7. **The friend-window evaluation re-seeds the indicators at 09-11, as Astral does.** For parameter sets with a longer EMA trend the warmup is longer, so fewer bars are tradable.

## 6. Files

| file | content |
|---|---|
| `doge_strategy.py` | port copy with the lfilter speed patch (sha abb06574...); `doge_strategy_orig.py` is the unmodified port (800660e7...) |
| `check_patch.py` | patch equivalence and saved-window reproduction |
| `robust_lib.py` | loaders, resampler, cost scenarios, stats (day-clustered t) |
| `run_coins.py`, `out_coins.txt`, `coins_summary.csv`, `coins_trades.csv` | Part 1 |
| `run_coins_window.py`, `out_coins_window.txt`, `coins_window_0911_0928.csv` | the friend's window on each coin |
| `run_tf.py`, `out_tf.txt`, `tf_summary.csv`, `tf_trades.csv`, `tf_years.py`, `out_tf_years.txt` | Part 2 |
| `run_sens.py`, `sens_oat.csv`, `sens_cloud_0.csv`, `sens_cloud_1.csv`, `analyze_sens.py`, `out_sens.txt`, `sens_all_sets.csv` | Part 3 |
| `make_md.py`, `tables.md` | markdown tables generated from the CSVs |
