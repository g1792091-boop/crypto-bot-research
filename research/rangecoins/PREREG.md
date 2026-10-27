# 레인지 봇에 코인 더하기 — 미리 정한 것 (2026-10-27, 결과 보기 전에 커밋)

두 분 10-27: "일단 비트랑 이더 솔라나 도지 ltc bch는 그대로 가고 거기서 내가 진입횟수를 더 원하니까 추가로 종목 추가해야 하는거
아니야??" (앞서: "지금 조건들은 완벽한거 같아서 더이상 건들면 안될꺼 같고 차라리 진입횟수를 늘리려면 코인종목을 늘리는게 맞지 않을까").

## Question

With the six coins kept and every rule of the running 레인지 봇 unchanged, does adding coins make the bot better (and how many more
entries does it give)?

## Machinery (unchanged code)

- analysis/f7tp10_1026/hunt.py `run` with F1 (research/opentime/rangebot.py `F1` = FINAL_KO.md's structure, the live bot's):
  F7_RF_TRIPLE 1h 80 / 9.0, pullback 0.2 x ATR14 (1h) from the signal close within 1 h, entry at the next 5m open after the touch,
  coin 1h V3.9 supertrend (10, 3) and BTC 1h supertrend on the side, liquidation room check, one signal at a time (commit),
  KST weekend / NYSE open +-30 / macro +-30 blocked, BTC 40x / every other coin 30x, margin 40 %, TP net +10 %, stop net ROE -50 %,
  one position over all the coins. Costs as sim.py for every coin (taker 0.05 %, slippage 0.02 % a side).
- Per-coin arrays: hunt_prep.job and trendcols.py (their own code, the coin list set to the new coins); the six coins' arrays and
  the blocks are the ones research/range4h used (same 5m bars, 2020-01 .. 2026-10-24).
- New coins' 5m bars: data.binance.vision USD-M monthly / daily klines and funding, the same conversion as
  analysis/v39_1h/fetch_bars.py `five` (checksums, volume-0 bars dropped) plus the volume column hunt_prep reads.
- Coin order (the tie-break when two coins touch on the same 5m bar, and which signal is taken first): the six as the bot's config
  (BTC, ETH, SOL, DOGE, LTC, BCH), then the new coins in the order below.
- Per trade wallet return = 0.40 x max(net ROE, -1); KST months, a fresh wallet each month (otcommon.period_metrics).

## Candidate coins (fixed now)

XRP, BNB, ADA, AVAX, LINK (USDT perpetuals). Chosen before any result as large, long-listed coins on Binance USD-M (5-year bars)
that WOO X Pro also lists (XRP is already traded there by the friend bot; the others to be checked in the WOO app before any switch).

## Arms

| arm | coins |
|---|---|
| C0 | the six (the bot as it runs; must equal research/range4h R0) |
| C5 | the six + XRP, BNB, ADA, AVAX, LINK |
| C1_<coin> | the six + that one coin (five arms) |
| CS | the six + every coin whose C1 arm beats C0 in the choose period (selection on 2021-2023 only) |

## Decision rule (as research/opentime, research/range4h)

- Periods: choose 2021-01 .. 2023-12, check 2024-01 .. 2026-09. October 2026 (to 10-24) and the two live windows are reported,
  never part of the verdict.
- Score: median month multiple; equal (1e-12) -> log growth (otcommon.beats).
- C5 "helps" only if it beats C0 in BOTH choose and check.
- CS: its coins are chosen on choose only; it "helps" only if it beats C0 in check. No coin chosen -> no CS verdict.
- Recommendation, in this order: C5 helps -> add the five. Else CS helps -> add the CS coins. Else -> keep the six.
- The C1 arms are read only through CS (a C1 arm that looks good in check alone is not a reason to add that coin).
- Also reported (descriptive): trades, entries per weekday, win %, months up, worst month, worst trade, mean per trade, trades by
  coin and how many six-coin trades an arm lost or gained against C0, the share of 1h bars where each coin fails the liquidation
  room check.

## Limits known before the run

5m bars (the bot uses 1m); WOO X Pro's own prices, funding and depth may differ from Binance's, most on the smaller coins; the
same cost for every coin.
