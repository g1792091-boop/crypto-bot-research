# Synthesis of the three AI-trader selection proposals (judge: the main session, 10/8 KST)

Files: resume/select_evidence.json, select_testpower.json, select_portfolio.json (all agents used the verified digest).

## What all three agree on (adopt)
- NOT 30 traders. Start with 10 (wave 1, D0 = 10/17 21:00 KST after a wave-0 replay test 10/14-15 and a 24h decision-only run), add up to 8 more ~10/31 only on OPERATIONAL gates (cost per call, non-response <5%, schema errors, complete paired logs), never on wave-1 results. Total <= ~18-20 seats incl. 2-3 non-judged Opus twins.
- Why not 30: only ~16-20 distinct, frequent, non-anti-edge streams exist; 17th-30th would be a duplicate, an anti-edge, or too rare (power ~0); cost ($510-775 for the 30-trader draft; 16-18 + twins ~ $250-420 by scaling, unmeasured); BH family cost; correlated luck.
- Selection among non-negative strategies is nearly arbitrary (5-year cells differ by ~0.012% per notional); choose for measurement speed, distinctness, frequency, and exclude anti-edges.
- Per-trader entry timeframe scope fixed in advance by the 5-year gross sign (e.g. S4 without 15m, F16_FIB382 15m+1h, N25 without 30m); 4h only where the per-signal check (stop + 1 ATR inside 20x liquidation) passes.
- Setup B: ties -> longer timeframe first, then widest stop first (+0.014R core / +0.019R DS), no switching; new signals while holding ignored except opposite signal on the held coin / higher-timeframe own signal.
- Sizing: flat 1% risk per stop (<=1.5% at 1h/4h), leverage chosen by code (20-30x in practice), exits in R/price not ROE, confidence logged but not used for size until shown informative (>=200 trades, Spearman>0). Reconcile with paperbot/policy.py RecommendedPolicy (1% risk, lowest leverage <=10x, 3 ATR buffer) which is the opposite leverage choice: owners must choose ONE sizing path.
- Verdict: pre-registered paired AI-minus-rule on every signal shown, vs side-flip and same-side random-time coins (pool fixed before D0), day/week-block CIs, long share shown, >=100 trades (>=40 per half). Day 30 is futility-only.
- Exposure caps per coin-direction across traders; -3R/day per trader; -15% review (futility stop of AI calls); book daily stop -12R; REJECTED_CAP logged with shadow.
- Freeze custom values for judged traders 10/17-12/31; weekly search runs in a shadow account as a record; adoption needs the money unit and a best-of-225 adjusted threshold (no adoption expected).
- Anti-edge exclusion list (last choice): N17_KC_RSI (15m/30m/1h), F15_ORB, F11_RAID/F11_TSOUP/F13_RAID_PD, F17_Z/F17_Z_HL, F15_ASIA_SWEEP, F11_PO3, F1_PVT_DIV@15m, F4_PULL (+_RSI). Also exclude short-only/short-heavy N20, N24 (reserve), near-silent N14/N15/N21/S1/N11/N03/N08/S5, nested duplicates (N06 in N18, F13_FVG_PD/F10_M2022 in F9_FVG, F12_MSS_DISP in F12_MSS, F16_FIB618 in F10_OTE, F7_RF_ONLY in F7_RF_TRIPLE, F5_BOX_HTF), F5_BOX family, REEL5M.
- Honest warnings: no strategy verified not to lose; AI must add ~0.2R/trade at 15m (0.11-0.16R 30m, 0.08-0.12R 1h) -- about 5-10x anything measured; most likely 12/31 result is "no trader passes" (which is a correct answer if the AI adds nothing); expected false passes ~0.03 at K=16 single window.

## Vote table (W1/W2/R/X = wave1/wave2/reserve/excluded) [TestPower | Evidence | Portfolio]
N10_HA_PSAR W1|W1|W1 ; F16_FIB382 W1|W1|W1 ; F9_FVG W1|W2|W1 ; N18_VWMA_MACD W1|W2|W1 ; S4_BB_BBP W1|X(veto)|W1 ; N25_DST_CCI W1|X|W1 ; F6_VWAP_CROSS W1|W1|W2 ; N23_HA_ST W2|R|W1 ; F4_FAN W2|W1|W2 ; V39_ALL W2|W1|W2 ; F7_RF_TRIPLE W1|R(veto)|W2 ; S2_ST_ROC W1|W2|X(cluster) ; N02_ST_KST W2|W1|X(cluster) ; DOGE R|W1|W2 ; N07_ICHI_CMO -|W2|W1 ; N13_3OUTSIDE -|W2|W2 ; N04_ST_KLINGER W1|W2|X ; F16_FIB500 W2|W1|X(merged) ; N01_ST_EMA W2|W2|X ; F9_IFVG R|W1|X ; N12_ICHI_AO -|W1|X ; N22_VORTEX_PSAR W2|R|X ; F12_MSS W2|X|X ; N09_ALLIG_AROON R|W2|R ; N24_DMI R|W2(1h)|X ; F15_ASIA_BRK X|R|W2 ; H3A_RETAIL_FADE (new information, design item 8): only Portfolio, conditional on limit-fill engine + L/S feed built by 10/30.

## Judge's recommended lists
Wave 1 (10, from 10/17): N10_HA_PSAR, F16_FIB382, F9_FVG, N18_VWMA_MACD, S4_BB_BBP, N25_DST_CCI, F6_VWAP_CROSS, N23_HA_ST, F4_FAN, V39_ALL.
  Families: HA/PSAR trend, Fibonacci pullback (only 5y BH-significant 15m cell), ICT FVG, MACD/volume, volatility breakout (exit-heavy test), mean reversion, VWAP (largest signal supply), Supertrend-HA (4h where 20x passes), EMA ribbon, composite.
Wave 2 (up to 8, ~10/31 on operational gates): F16_FIB500 (near-independent replication of F16_FIB382; one BH family), F7_RF_TRIPLE, S2_ST_ROC, N02_ST_KST, N07_ICHI_CMO, DOGE (owners' strategy, 1h-led, slow), N13_3OUTSIDE, + H3A_RETAIL_FADE only if its build passes by 10/30 (else N01_ST_EMA/N04).
Opus twins (not judged): N10_HA_PSAR and F16_FIB382; a third (S4_BB_BBP or N23_HA_ST) only if measured cost allows.
Cluster notes: N10/N23/S2/N01/N02/N04 are Supertrend/HA cousins (signals co-occur 87-98% in 4h windows); F16/F9 pullback cluster; F7/F4_FAN/F6 DeepSeek trend cluster -> cap 1 concurrent position per coin-side per cluster.

## Disagreements and how the judge resolves them
- Veto of S4/F7/N23 by the evidence proposal (one 5-year half of the one-position trader gross < -0.005R): the veto was built in-sample on the same 5 years; since choice is near-arbitrary, keep S4 (exit-heavy test) and N23 (only BH-surviving 4h cell, rarely tradable) but flag both as lower prior; F7 moves to wave 2.
- Single window to 12/26 (Portfolio) vs the design's two-stage day30/day60: recommend the single window with day 30 as futility only (owners decide; D1/D3/D21 still open).
- Number of judged traders K: 16 (Portfolio) vs ~18-20 seats total: K = number of judged Sonnet traders at wave-2 launch (fixed list); twins and rule records outside the family.
- Wave 2 timing: must start by 11/01 to have ~56 days; if it can't, those traders are exploratory (outside the 12/31 family).
