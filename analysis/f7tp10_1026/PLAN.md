# 레인지 필터 3중 일치 1시간 (커스텀값 80 · 9.0) · 고정 익절 +10% — 3패 분석과 보완 계획

Written 2026-10-26 before any five-year number of `study.py` was seen. Known before this file: the league's own five-year replay
of the account (analysis/review1024/league/out/fivey.json: 2020 326 trades win 77 %; 2021-2023 754 trades win 74 % bust;
2024-2026.09 464 trades win 72 % bust) and the forward reads below (10/13-10/25).

## Forward (the league window) — parity and the three losses

- The signals recomputed here (ds_defs F7_RF_TRIPLE 1h, rf_period 80, rf_mult 9.0, full series) and the league's own sizing
  check (paperbot.sizing.size_position, 30x, margin 30 %, stop at least 1 ATR inside liquidation, loss at the stop <= 15 %)
  give the same 19 trades as the league export (analysis/review1024/league/trades_norm.csv: entry hour, coin, side, exit
  reason, net ROE within 0.003; exit minute within 5 minutes on 5-minute bars), plus the next three (10/24 15:00, 10/25
  00:00 wins; 10/25 07:00 open at the data's end).
- Loss 1, 10/18 07:00 KST (Sunday) BTC short, -25 %: the signal bar was 3.3 x ATR long (a flush bar); ATR 0.35 % of price, so
  the 2-ATR stop was 0.7 % away; never in profit (best -4.8 %), stopped in 3.6 h; price reached the take-profit level within the
  next 24 h (the side was right, the stop too near after a flush bar).
- Loss 2, 10/20 15:00 BTC short, -33 %: the 4h judge was 보류 (down 2, up 1) — no 4h downtrend; best +10.0 % (a hair under the
  take-profit) then up through the stop in 8 h; price did not come back.
- Loss 3, 10/22 06:00 BTC long, -35 %: a chase — 96 % of the 7-day range, 90 % of the 24-hour range, RSI 74, 2.3 ATR above the
  4h EMA20; the 추세판단 봇's own entry checks refuse it three ways; best +1.1 %, stopped in 4.6 h.
- The wins: 11 of the 19 wins were also chase entries and 6 failed the 4h EMA-distance check: in this month a +0.47 % move
  came first even from stretched entries. Three losses cannot separate causes; the five-year run decides.

## Arms (fixed now)

Windows (entry time, UTC): 2020-03..12 · 2021-2023 (the period the custom numbers were chosen on) · 2024-01..2026-09
(confirm) · 2026-10. Each window: $1,000, one wallet, one position, every coin's signals, the order of simultaneous signals as
the league (coin order) or the 추세판단 봇 (score: 4-of-4 judge + distance to the 1h EMA20).

| arm | entries | exit | size |
|---|---|---|---|
| L0 | the league as it is | stop 2 ATR, TP net +10 % | 30x, margin 30 %, league sizing check |
| A | L0 + no flush bar (signal bar range <= 2 ATR: the trend bot's ``big_bar_atr``) | as L0 | as L0 |
| B | L0 + the 4h judge on the trade's side (3 of 4; 보류 refused) | as L0 | as L0 |
| C | L0 + the trend bot's entry checks (trendjudge.check: 4h side / strength / 끝물 / EMA distance / RSI) + no chase | as L0 | as L0 |
| D | A + B + C (the 보완판: one fix per loss) | as L0 | as L0 |
| E | L0 | stop 3 ATR, TP net +10 % | as L0 |
| L1 | C + the trend bot's time blocks (KST weekend, NYSE open 22-23 KST, macro +-30 min) | as L0 | as L0 |
| T0 | L1 (the member inside the 추세판단 봇, 보류 allowed as live) | the bot's: -50 % net, ladder 10@11 · 12@15 · +5, JUDGE / REV before the first lock | BTC 40x / others 30x, margin 40 % |
| T1 | L1 | stop 2 ATR, TP net +10 % | BTC 40x / others 30x, margin 40 % |
| TD | T0 + A + B (strict 4h side) | as T0 | as T0 |

Coin-flip twin of L0, D, T0, TD: the same signal stream and gates, the side drawn at random (100 seeds).

Verdict rules (fixed now): a fix is "better" only if it beats L0 on 2021-2023 AND on 2024-2026.09 in end wallet and mean net
ROE; it "works" only if, in addition, its 2024-2026.09 end wallet is above $1,000 and above 95 of its 100 coin-flip twins.
The 10/2026 window is only read, never used to choose.
