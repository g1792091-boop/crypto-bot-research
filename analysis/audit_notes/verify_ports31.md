# Adversarial verification of the "ports31" audit (19 FINGRAD 31-set ports)

Verifier scratch dir: this directory. Code copied from /home/user/crypto-bot-research/bt (unmodified) into ./bt;
data read from /home/user/crypto-bot-research/data (sha-verified by orchestrator). Nothing under
/home/user/crypto-bot-research was modified. All numbers below come from scripts in this directory
(outputs in ./out). Written independently of the auditor's scripts (only their N21-window
*definition* was read so the same variant could be re-derived).

Scripts: vlib.py (harness = delivered engine.run_backtest + analyze.pooled/apply_rule, IS window,
5 symbols, 13 exits; fwd_drift uses forward.py convention open[i+1] -> open[i+1+h]),
trunc_v.py, n24_v.py, st_v.py, n21_v.py, n21w_v.py, n14_v.py, mirror_v.py, ind_v.py, minor_v.py,
sticky_v.py, fwd_v.py, fwd_adj.py, window_v.py, misc_v.py, p5m_v.py, placebo_v.py.

Harness sanity: my forward drift reproduces delivered forward_IS_all5.csv exactly
(S2 11,195 sig, -0.10744%; N01 3,805, -0.13199%; N24 5,254, +0.09448%), and my pooled
delivered-port rows reproduce pooled_IS_15m_all5.csv (N24 2,436 / PF 0.819; S2 4,322 / 0.722).

## 1. Look-ahead (auditor: none) -> CONFIRMED
* trunc_v.py BTC 15m: 19 ports x 120 cut points (half random, half AT a full-data signal bar or
  the bar before it, seed 20260929). Signals on df.iloc[:t+1] vs full data over the whole prefix
  0..t: 0 mismatches at t, 0 prefix mismatches, for all 19. SOL 15m, 60 points: also 0.
* Static reading: no shift(-k)/center/bfill; Ichimoku spans shift(+26); Donchian shift(1);
  fg_fast aroon/cci use trailing sliding windows only.

## 2. Indicator correctness (auditor: standard to ~1e-10) -> CONFIRMED
ind_v.py: my own loop implementations (Pine rma seed, Pine ta.supertrend, Pine CCI/WR/
Vortex/MFI/CMO/KST/VWMA/AO, Ichimoku) vs fg on BTC and SOL, bars >= 1000:
ATR/RSI/+DI/-DI/ADX max diff <= 1.4e-12; CCI/WR/Vortex/Tenkan/Kijun/AO/CMO/KST exactly 0;
MFI 7.5e-13; VWMA 2.9e-11. Supertrend direction (10,6),(10,3),(20,6): 0 disagreements in
39,000 bars on both symbols.
* Aroon: FINGRAD = 25-bar window (0 disagreements vs my 25-window ref); vs Pine 26-bar window
  ~4,800-4,980 value disagreements / 39,000 bars (12.5%).
* Ichimoku: span A matches offset 26 exactly; vs TradingView visual offset 25 differs on 28.5k bars.
* PSAR: FINGRAD vs my port of Pine's published ta.sar reference: direction differs on 3.41% (BTC)
  / 3.03% (SOL) of bars; SAR value differs on 14.3%.
* MFI: my exact-window reference equals FINGRAD to 7.5e-13, so any TA-Lib discrepancy the
  auditor saw is not a FINGRAD formula error (info only).

## 3. PORT-1 Supertrend(10,6.0) -> CONFIRMED numbers, severity lowered to low
st_v.py (wrapper maps multiplier 6.0 -> 3.0): every auditor number reproduced exactly.
| port | best PF 6.0 | best PF 3.0 | fwd64 6.0 (t) | fwd64 3.0 (t) |
|---|---|---|---|---|
| S2 | 0.722 | 0.769 | -0.107 (-4.14) | +0.040 (1.58) |
| N01 | 0.738 | 0.898 (2,212 tr, gross +0.038, net -0.069, 1/5 sym) | -0.132 (-3.05) | +0.069 (1.60) |
| N02 | 0.745 | 0.811 | -0.054 (-1.11) | +0.112 (2.22) |
| N23 | 0.746 | 0.823 | -0.133 (-5.35) | +0.014 (0.59) |
| N25 | 0.739 | 0.765 | -0.121 (-3.46) | +0.004 (0.10) |
Passes: 0 either way. N21 has 0 signals with 3.0 too.
Nuance: fg_indicators.py is a verbatim copy of FINGRAD and strategies.py's docstring says the
ports reproduce fingrad_bot/strategies/*.py; the previous session had the original zip, so 6.0
is more likely faithful than a porting slip. Unverifiable, not a demonstrated defect.

## 4. PORT-2 N24 asymmetry -> CONFIRMED, but bias direction is mixed, not "looks worse"
n24_v.py: -DI up-crosses with ADX<=25: 81.2% BTC, 81.2% ETH, 82.6% SOL, 86.1% LTC, 84.2% BCH
(full series; auditor's 1,622/1,320 BTC = from bar 1000). IS signals 907 long / 4,347 short
(82.7% short). Mirror test (mirror_v.py, additive reflection K-p): N24 1,622 (BTC) / 1,595 (ETH)
mismatches; all other ports 0-1 except N02 (19-41, ratio ROC) and N18 (28-35 = exactly the bars
where raw long and short both fire and the long-priority mask drops the short).
Variants (best exit F_sl2.0_tp3.0): delivered 2,436 tr PF 0.819 gross -0.019; symmetric ADX>=25
1,147 tr PF 0.899 gross +0.033 net -0.074 1/5 sym, mean PF over 13 exits 0.674 vs 0.646;
long-only 813 tr PF 0.788; short-only 2,146 tr PF 0.826; symmetric ADX<=25 PF 0.773. 0 passes.
NEW: the IS window is a deep bear market (buy&hold from bar 1000 to split: BTC -32.0%,
ETH -48.7%, SOL -54.0%, LTC -53.8%, BCH -23.1%; OOS: +3.7/+16.2/+31.7/+19.2/-32.8%).
N24's raw fwd64 = +0.094% (t 2.59) but market-drift-adjusted only +0.027% (t 0.75); the
non-overlapping subsample is -0.071% (t -1.00). The short-only half has fwd64 +0.123% (t 3.11),
i.e. the asymmetry harvests bear-market beta. The symmetric fix raises best-exit PF (+0.08) but
kills the drift (+0.047%, t 0.73). So the asymmetry is not simply "makes results look worse";
in a bullish period (stage A 1h/4h over 4.6 years) the delivered short-heavy N24 would be hurt.

## 5. PORT-3 N21 -> CONFIRMED empirically; "structurally impossible" overstated
n21_v.py: 3,249 ADX-cross-below-25 events (bars >= 1000, 5 symbols: 641/640/675/637/656).
RSI at those bars 30.44..68.41 (p5 40.6-42.4, p95 58.3-60.3). Co-occurrence with RSI<30 or >70:
0. Expected under independence: 1.36 long + 2.08 short. So zero is consistent with strong
anti-correlation plus a tiny base rate; it is not a mathematical impossibility (ADX is built from
high/low directional moves, RSI from closes; they can diverge), just "never happened / near-
impossible". Already disclosed in the handoff ("N14/N21 0 signals").
Windowed variant (n21w_v.py, all three conjuncts via recent(.,k)): k=3: 0 signals; k=6: 7 signals,
4 trades; k=12: 106 signals, 30 trades at F_sl2.0_tp3.0, PF 1.549, mean net +0.289%, t=1.12,
4/5 symbols positive, 15 L/15 S, other exits 0.21-1.34; k=24: 620 signals, 73 trades, best PF
0.935. Non-monotone in k -> noise. Fails the 100-trade minimum regardless.
Placebo: see section 10.

## 6. PORT-4 N14 -> CONFIRMED
n14_v.py: IS 0 signals; OOS 2 (ETH long 2026-09-04 12:45, LTC short 2026-09-13 05:30 UTC).
Handoff "0 in 14 months" is slightly wrong (true for the 9-month IS only).
My co-occurrence measure (recent(TK cross,3) & same-side RSI extreme): 49 observed vs 1,202
expected under independence (auditor's different measure: 27 vs 634). Same conclusion.

## 7. Minor findings
* PORT-5 stickiness CONFIRMED: N17 85% of IS signals have a signal on the previous bar; 55% of
  N17 trades at F_sl2.0_tp3.0 re-enter on the bar right after the exit. N18: 67% / 17%.
  Fresh-only: N17 PF 0.848 (+0.035), N18 0.747 (-0.004). 0 passes.
* PORT-6 Aroon CONFIRMED (above). TV Aroon(26-window) in N09: PF 0.774 vs 0.818 (dPF -0.044,
  slightly beyond the auditor's |dPF|<=0.04 but immaterial).
* PORT-7 PSAR CONFIRMED (3.41% BTC). Pine-SAR swaps: N10 0.791 vs 0.790, N22 0.810 vs 0.812.
* PORT-8 Ichimoku offset CONFIRMED. Offset 25: N07 -0.007, N08 -0.019, N12 -0.026.
* PORT-9 MFI: FINGRAD equals exact reference; info.
* PORT-10 N25 CONFIRMED: c_up & c_down co-occur 0 times on all 5 symbols; long ==
  c_up & ~(both ST down), short == c_down & ~(both ST up) exactly on all 5 symbols.
* PORT-11 CONFIRMED in magnitude, with caveats (fwd_v.py, fwd_adj.py): fwd64 IS pooled:
  N08 +0.230 (t 1.25), N03 +0.208 (0.86), S6 +0.136 (1.65), N09 +0.120 (1.90),
  N17 +0.119 (t 5.09 naive), N24 +0.094 (2.59). De-overlapped: N17 fresh +0.101 (t 1.59),
  non-overlapping +0.053 (t 0.62); N24 market-adjusted +0.027 (t 0.75). S6 non-overlap +0.253
  (t 2.24) is the strongest but is 1 of ~17x6 horizon tests. The handoff's "V4.5 is the only
  faint signal" is therefore not unique; the same overlap/market-drift caveats apply to V4.5.
* Extra (not in audit): N17 uses ATR14 for the Keltner width while fg.keltner_channel defaults
  to ATR10; ATR10 variant PF 0.812 vs 0.813 -> immaterial. Standard Williams Alligator (SMMA of
  hl2, offsets 8/5/3 into the past) in N09: 0.822 vs 0.818.

## 8. Auditor "confirmed OK" item that is WRONG
"Signals computed from 500+ bars of history are identical to full-history signals (0 mismatches
for all 19)". window_v.py, testing AT signal bars: N03_ADX_GC (EMA50/EMA200 cross + ADX)
signals are NOT reproduced from the last 500 bars in 50 of 220 cases (BTC 14/36, ETH 11/49,
SOL 9/55, LTC 8/36, BCH 8/44); W=1000 and W=1500: 0 mismatches. Cause: fg.ema is seeded with
the first close (ewm adjust=False), so EMA200 has not converged after 500 bars
((199/201)^300 ~ 5% of the seed error left). At W=300 S2/N01/N02/N25 also show 2-5/150 misses
on BTC. The auditor's sample (150 random windows x last 20 bars) contained only ~3 N03 signal
bars, which is why it missed this. Impact: live/backtest parity only (a live bot fed 500 klines
would trade N03 differently); no effect on the stage-1 backtest. Recommend >=1000 bars of history
for any live port.

## 9. 5m claim -> CONFIRMED
p5m_v.py (BTC/ETH/SOL 5m, window ALL, max_hold 3000 as in run.py): 221 combos, 0 passes, best
PF 0.808 (S6 F_sl2.0_tp3.0, 676 trades), max gross +0.0152%/trade.

## 10. Placebo for N21_W12
(placebo_v.py results appended below when finished)
placebo_v.py (seed 12345, 200 draws per design, random entry bars within the IS window, random
side, same engine/13 exits/pooling): observed best-of-13 PF 1.549.
* design A (count = signal episodes per symbol, median 29 trades/exit): placebo best-of-13 PF
  median 1.035, p90 1.633, p95 1.829; share >= 1.549: 13.0%.
* design B (count = W12 trades per symbol at the best exit, median 30): median 1.023, p90 1.677,
  p95 1.922; share >= 1.549: 15.5%.
-> auditor's p ~ 0.15 confirmed; N21_W12 is indistinguishable from random entries.

## Verdict summary
PORT-1 confirmed (numbers exact), severity medium -> low (unverifiable parameter, likely faithful).
PORT-2 partially confirmed: asymmetry and numbers exact, but "makes results look worse" is
  wrong/mixed: the short-heavy rule harvested the IS bear market's drift (fwd64 +0.094% raw vs
  +0.027% market-adjusted); matters for stage A over bull periods.
PORT-3 partially confirmed: 0 co-occurrences in 3,249 events exact; "structurally impossible"
  overstated (expected ~3.4 under independence; empirically never). Already disclosed in handoff.
PORT-4..11 confirmed (PORT-6 dPF -0.044 slightly above the stated 0.04).
Missed: 500-bar live-window parity claim false for N03 (50/220 signals differ; fine at 1,000 bars).
Missed (context): IS window is a -23% to -54% bear market; N18 absent from the mirror-test OK list
  (28-35 bars from the long-priority mask).
Headline "0 pass for the 31-set ports" survives every check.
