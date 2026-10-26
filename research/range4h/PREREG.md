# 레인지 봇에 4시간 신호 더하기 — 미리 정한 것 (2026-10-26, 결과 보기 전에 커밋)

두 분 10-26: "레인지 필터 3중 일치 지금 1시간봉 봇 돌아가고 있잖아 혹시 거기다가 레인지 필터 3중 일치 4시간봉도 추가하면 어떨까
… 규칙봇에서 돌아가는 레인지랑 커스텀값봇에서 돌아가는 레인지랑 둘다 성과가 좋더라고".

## Question

Does adding the F7_RF_TRIPLE 4-hour signal as a second source of the running 레인지 봇 (one position, same structure) make it
better than the 1-hour source alone?

## Machinery (unchanged code)

- analysis/f7tp10_1026/hunt.py `run` with F1 = FINAL_KO.md's structure (the live bot's, checked trade for trade by livepar.py):
  pullback 0.2 x ATR14 of the signal's own frame from the signal close, wait 1 h, entry at the next 5m open after the touch,
  coin 1h V3.9 supertrend (10, 3) and BTC 1h supertrend on the side, liquidation room check, one signal at a time (commit),
  KST weekend / NYSE open +-30 / macro +-30 blocked, BTC 40x / others 30x, margin 40 %, TP net +10 %, stop net ROE -50 %,
  one position over the six coins. hunt.py's own "sources": several sources together share the one position.
- 5-year world: research/opentime/rangebot.py `world` (the 5m bars 2020-01 .. 2026-10-24 and the blocks recomputed over the
  whole range; its parity check reproduced the published numbers of F1). Position function: sim.run_position (original).
- Per trade wallet return = 0.40 x max(net ROE, -1); months are KST months, a fresh wallet each month (otcommon.period_metrics).

## Arms

| arm | sources |
|---|---|
| R0 | 1h 찾은 값 80 / 9.0 — the bot as it runs (baseline) |
| R1 | 1h 80 / 9.0 + 4h 찾은 값 50 / 4.5 (hunt.py `4h_c`, the candidate league's 4h numbers) |
| R2 | 1h 80 / 9.0 + 4h 기본값 (hunt.py `4h_d`, the rule bot's default numbers) |
| R3, R4 | 4h 50 / 4.5 alone, 4h defaults alone — descriptive only, no verdict |

A 4h set-up uses the engine as it is: its pullback is 0.2 x the 4h ATR14, the trend checks are the same 1h checks.

## Decision rule (as research/opentime)

- Periods: choose 2021-01 .. 2023-12, check 2024-01 .. 2026-09; October 2026 (to 10-24) and the two live windows (rule bot
  10/06 ~ 10/25, league window of pick.py) are reported, never part of the verdict.
- Score: median month multiple; equal (1e-12) -> log growth.
- R1 / R2 "helps" only if it beats R0 in BOTH choose and check. Otherwise the recommendation is not to add it.
- Also reported (descriptive): trades, win %, months up, worst month, worst trade (wallet %), mean per trade, by month.

## Already seen before this file

hunt.py stage D (f7x/hunt.log, 10-26) ran 1h + 4h (both numbers) on the OLDER entry (pullback 0.25 ATR, wait 2 h), on the live
windows, October and 2025-01 .. 2026-09 months only: adding 4h was about the same as 1h alone (rule bot window x3.61 vs x3.60).
Nothing with F1 + 4h and nothing of 2021-2023 was run before this file.
