import json, sys
P=json.load(open(sys.argv[1])); out=sys.argv[2]
def pw(k):
    p=P[k]
    return {"paired_assumed_wk_0.1R":p['wk_paired_0p1'],"paired_assumed_wk_0.2R":p['wk_paired_0p2'],
            "unpaired_wk_0.1R":p['wk_unpaired_0p1'],"unpaired_wk_0.2R":p['wk_unpaired_0p2'],
            "MDE_by_1231_if_start_1017_paired/unpaired":[p['mde_by_1231_paired'],p['mde_by_1231_unpaired']]}
TF="15m/30m/1h + 4h only where the per-signal 20x check passes (setup B: longer-tf-first on ties, then widest stop first, no switching)"
J={}
J["headline"]=("Pick traders for measurement, not for expected profit: 10 Sonnet traders in wave 1 (6 core + 4 DeepSeek, one per family, all 5-year long share 0.47-0.52, none in a BH-negative-direction cell, "
 "4.9-7.3 rule trades/day, maximum pairwise same-bar signal overlap 0.28) plus 2 Opus twins (N10_HA_PSAR, F7_RF_TRIPLE). Add 6-8 more in wave 2 (16-18 Sonnet + up to 3 twins, about 20 seats in total), not 30. "
 "Per trader, a paired AI-minus-rule test started 10/17 can see about 0.07-0.09R per decision by 12/31 (0.10-0.12R unpaired). That covers the break-even hurdle (0.2R at 15m) in about 2 weeks per trader. "
 "AI value of 0.05R is only visible pooled across the cohort, which is correlated. The choice of strategy hardly changes expected P&L (5-year cells differ by about 0.012% per notional); it changes how fast and how cleanly the AI's own effect can be measured.")
J["recommended_count_and_why"]={
 "wave1":"10 Sonnet traders + 2 Opus twins (12 seats), from 10/17, for 1-2 weeks of pilot, then keep running",
 "wave2":"+6 to +8 Sonnet (+1 Opus twin on S4_BB_BBP if cost allows), about 10/31. Total 16-18 Sonnet + 2-3 Opus (<= 20 seats)",
 "why_not_30":[
  "Power per trader does not grow with the number of traders. Each extra trader only adds to the pooled cohort test. Cohort decisions are correlated (same coins, same bar closes; deff 3-9 per DS13), so going from 10 to 18 traders lowers the pooled paired MDE by 12/31 only from about 0.043-0.074R to about 0.034-0.058R (sel_tp/power.py arithmetic, deff 3/9).",
  "Test power needs high-frequency strategies (5-7 trades/day), and those cost more calls. The chosen wave 1 makes about 1.1-1.5x the calls of a median trader (cost_model setup-B ignore-P3 5y 9.3 median-equivalents for the 6 core picks; live ignore-P2 about 11.4 for all 10). Each Opus twin on a busy strategy costs about 2.4x per call, including model-scoped cache writes (verify2_cost_model). 18 traders + 3 twins therefore cost about as much as 30 median traders, which fits $500 only with new signals ignored while holding and event or held-timeframe-bar-close checks (C9, verified).",
  "Exit decisions are part of what the AI adds. Thinning hold checks to event-only so that 30 traders fit removes the AI's exit opportunities, so it lowers the power of the exit component. 16-18 traders with held-timeframe bar-close checks plus 1.0R move wakes is the better trade.",
  "Multiple testing: with about 18 traders judged at once, a single trader's verdict at BH q 0.05 needs roughly 1.3x the single-test MDE (about 1.7x the weeks). More seats on overlapping strategies add more noise than information.",
  "After removing anti-edge, all-short, silent and nested definitions, only about 18-20 distinct families with >= 4.5 trades/day remain (sel_tp/power.json, ov15_exact.json). Seats 21-30 would go to near-duplicates or to < 4 trades/day strategies, which need 9-11+ weeks for 0.1R."],
 "gate_between_waves":"Start wave 2 only if, after 7-10 days of wave 1: the per-call cost measured from usage fields is <= ~$12 per heavy trader-month at the chosen thinking effort; AI no-answer within the 20 s deadline is < 5%; the paired log is complete (every signal shown to the AI has its rule-alone replay and side-flip). The paired-difference sd measured in week 2 also replaces the assumption below."}
def item(key,name,why,risks,dup,cv,tpd_extra=""):
    p=P[key]
    return {"strategy":name,"timeframes":TF if not name.startswith("N23") else TF+"; 4h is this trader's distinguishing part (BTC/ETH only, about 0.06 4h trades/day)",
            "why":why,
            "trades_per_day_estimate":f"{p['tpd']} rule trades/day (5y, one position, setup B; tf mix "+", ".join(f"{k} {v:.0%}" for k,v in p['mix'].items())+f"). 5y net {p['netR']}R/trade, gross {p['gross']:+.3f}R. An AI that skips more trades less but makes more decisions."+tpd_extra,
            "weeks_to_detect_0.1R_0.2R":pw(key),"risks":risks,"duplicate_family_note":dup,"custom_value_candidates":cv}
UNIV="No strategy-specific custom value has evidence (CV1/CV9: walk-forward search loses in money units). Use only the universal code rules in design_implications."
W1=[
 item("C:N04_ST_KLINGER","N04_ST_KLINGER (supertrend + Klinger volume)",
  "The highest decision rate of all allowed strategies: 7.28 rule trades/day from 50/24/10 signals/day (15m/30m/1h), so skip choices are always available. Family: volume-confirmed trend. 5y gross about 0 at every tf (+0.006/+0.001/+0.002R) and long share 0.48: a clean zero-edge baseline with no anti-edge. Low overlap with every other pick (<= 0.14).",
  ["Heaviest call load: about 45 calls/day in ignore-P3 (5y), occupancy 0.88. Needs the per-bar-close bundled entry call and a daily cap.","Live every-signal 15m -0.20+-0.11 (n105), negative in all 3 runs. The verifiers say this is what chance predicts at -cost, not evidence that it is worse."],
  "Supertrend cousins (N01/N02/N23/S2) overlap it by only 0.11-0.14 at 15m. No nested definitions.",UNIV),
 item("C:N10_HA_PSAR","N10_HA_PSAR (Heikin-Ashi + PSAR)",
  "The best-supported core base (the only one to beat its same-side peers in all 3 runs at 15m/30m; low confidence) with a high decision rate (6.31/day; 24/10/4 signals/day). 5y gross +0.002/+0.011/+0.004R. Independent simulator puts 30m at B (+0.0135R, verify_costs). Mixed side (5y long 0.52). The natural anchor for the Opus twin.",
  ["Live v4 relative excess about 0 (n11). The support is weak and partly a matter of simulator boundaries.","Its 30m cell has 'little exit room' (AI-upside note), so the AI's value has to come from skips. That is fine for measurement, because skips are the cleanest paired component."],
  "Overlaps N23_HA_ST 0.42 (N23 is kept to wave 2 and flagged as correlated) and F7_RF_TRIPLE 0.26.",UNIV+" N10@30m: nothing to tune; keep the default."),
 item("C:S2_ST_ROC","S2_ST_ROC (supertrend + rate of change)",
  "6.58 trades/day (49/24/10 signals/day). The best 5y net per trade of the core under setup B (-0.112R). Gross +0.010R at 15m and positive in both 5y halves at A (noise-level). Long 0.48. The supertrend-momentum representative.",
  ["Heavy calls (about 42/day ignore-P3).","Live 15m -0.16+-0.20 (n105): uninformative."],
  "Overlaps N01_ST_EMA 0.32 and N23 0.24 (both wave 2 at most). Not nested.",UNIV),
 item("C:N18_VWMA_MACD","N18_VWMA_MACD (VWMA + MACD)",
  "6.39 trades/day (53/24/10 signals/day). MACD family. It also covers N06_MACD_ORB, because 98% of N06's signals are N18 signals. 5y gross +0.012/+0.011/-0.007R, long 0.50. The only strategy whose live context effect survived BH (low-efficiency-ratio signals worse, CF11), which gives a pre-specified skip hypothesis to check against the AI.",
  ["Live 30m -0.79 (L--) and long share 0.35 in the falling market. Live direction luck, not 5y behaviour.","The exits lens wanted to drop N18 30m. The verifier refuted that (5y ranks it no worse than the others)."],
  "Absorbs N06_MACD_ORB (do not staff N06). Overlaps N02 0.30, N09 0.30, S4 0.275.",
  ["Shadow-only (②′) filter: skip signals with a low efficiency ratio. Live BH survivor, 5y size about +0.03R (35x smaller than live). It must pass the 5y-sized gate and is not expected to matter.",UNIV]),
 item("C:S4_BB_BBP","S4_BB_BBP (Bollinger squeeze + BBP)",
  "The volatility-breakout family, distinct from the trend picks. It has the largest favourable moves of the 36 (about 35% of signals reach +1R), so this is the trader where AI exit decisions (giveback before the ladder arms, early profit, breakeven) happen most often and can be measured against the code-exit twin. 5.39 trades/day, long 0.49.",
  ["5y gross -0.013R at 15m (not BH-significant). The positive v4 live result was mostly shorts in the sell-off.","Per-strategy headroom rankings do not replicate (AIH-6). Large MFE is a structural reason to expect more exit decisions, not evidence of capturable value."],
  "Overlaps N18 0.275, F12_MSS 0.26 and the session breakouts F15_LON_BRK 0.37 (excluded). Not nested.",UNIV),
 item("C:N25_DST_CCI","N25_DST_CCI (double supertrend + CCI, reversion-type)",
  "The only core mean-reversion strategy with enough frequency (5.50/day) and no anti-edge. N17_KC_RSI, the busier reversion strategy, has BH-significant NEGATIVE gross. Reversion entries buy dips and sell rips in either market, so they give the cohort counter-trend behaviour (5y long 0.47; live 0.61 in the falling market) and keep the test from being one trend bet.",
  ["5y gross about 0 (+0.002/-0.013/+0.007R). Live 15m -0.37+-0.15 (L--), which the verifiers say carries no information.","Reversion strategies are exposed to trend days: one strong trend week can dominate its paired result. Report it by regime."],
  "Overlaps V45_AMB 0.245 and F3_BOS_ZONE 0.225 (both excluded), F6 0.16. The family stand-in for N17/V45/OBV_B.",UNIV),
 item("D:F7_RF_TRIPLE","F7_RF_TRIPLE (Range Filter + HA triple agreement, DeepSeek)",
  "6.64 trades/day from a very large signal supply (63/30/13 per day), which gives the most skip alternatives per slot. 5y gross +0.006/+0.012/+0.012R; 30m gross t 2.0 (on the 5-year-only shortlist, verify_fiveyear). Long 0.50. Second Opus-twin anchor: a different family from N10, high frequency, DeepSeek.",
  ["DeepSeek: 1.5 live days only, and DeepSeek pooled gross is slightly negative (t -1.8..-2.1). F7 itself is not.","Live 15m long share 0.38 in the falling market."],
  "Absorbs F7_RF_ONLY (58% nested; graded D anyway, do not staff). Overlaps DOGE 0.30, N10 0.26, S4 0.22.",UNIV),
 item("D:F9_FVG","F9_FVG (fair-value-gap retrace, ICT structure family, DeepSeek)",
  "The structure/ICT family representative. 5.98 trades/day. 15m 5y gross +0.016R, positive in both halves (t 2.56, verify_fiveyear shortlist). It covers two nested definitions (F13_FVG_PD 99.5%, F10_M2022 99.8% inside F9_FVG), so one trader stands for three. Long 0.50; very low overlap with every other pick (<= 0.11).",
  ["Gross 30m/1h about 0. Its 15m direction content is 6-10x smaller than the cost.","Live long 0.27 (falling market)."],
  "Absorbs F13_FVG_PD and F10_M2022. F9_IFVG/F9_OB/F9_BREAKER are separate streams of the same family: do not staff them alongside (F9_IFVG is in reserve).",UNIV),
 item("D:F6_VWAP_CROSS","F6_VWAP_CROSS (daily VWAP cross, DeepSeek)",
  "The largest signal supply of all (59/37/20 signals/day), so skip/selection skill gets the most chances. 5.19 trades/day. A distinct information type (session VWAP). The DeepSeek lens's own exploratory pick: its 5y period ranks are consistent (11/3/6 at 15m), the only DeepSeek consistency found. Long 0.50, and the largest 1h/4h share of trades (27%), which feeds the 1h state-exit test.",
  ["30m 5y gross about 0 and live 30m -0.14+-0.12. The live 15m support is the sell-off half only.","High signal supply makes entry calls expensive unless bundled per bar close."],
  "F6_VWAP_FAIL (same family) is not staffed. Overlaps N01 0.27, F12_MSS 0.24, and N20 0.32 (excluded).",UNIV),
 item("D:F16_FIB382","F16_FIB382 (Fibonacci 38.2% retrace, DeepSeek)",
  "The strongest 5-year direction evidence of any 15m cell: gross +0.026R, BH q 0.006, positive in both halves (still about 6x smaller than the cost). The pullback family. With F16_FIB500 (only 18% shared signals, q 0.020) it can later form a near-independent replication pair. Long 0.50. It is in wave 1 despite a lower rate (4.89/day) because it is the cleanest 'does the AI add on top of a small real directional tilt' case.",
  ["Lowest decision rate in wave 1 (about 7.7 weeks to 0.1R paired).","Live 15m -0.40+-0.26 (n18) and long 0.33 (falling market): uninformative."],
  "F16_FIB618 is nested in F10_OTE (97%, excluded). FIB500 shares 18% (wave 2). FIB764 is negative.",UNIV)]
J["wave1"]=W1
W2=[
 item("C:N23_HA_ST","N23_HA_ST (Heikin-Ashi + supertrend)",
  "7.01 trades/day, the second highest decision rate. Its 4h cell is the only one with BH-surviving 5y gross (+0.099R gross, net +0.008..+0.024R), so it is the one trader where '4h where 20x sizes' is a deliberate test.",
  ["Overlaps N10_HA_PSAR 0.42: in the cohort test, treat N10+N23 as one cluster.","4h at 20x is executable on only about 19-26% of 4h bars (BTC, ETH in quiet weeks). When volatility returns, the 4h part disappears."],
  "Correlated with N10 (0.42), N01 (0.335), S2 (0.24).",["4h entries where the per-signal 20x + 1 ATR liquidation check passes (5y borderline-B cell; not a tuned value).",UNIV]),
 item("D:F4_FAN","F4_FAN (EMA ribbon alignment, DeepSeek)",
  "5.90 trades/day. The best setup-B net of all 79 definitions (-0.108R/trade), with gross positive at every tf (+0.014/+0.009/+0.009). Long 0.50.",
  ["Same family as F4_PULL, which is worse than the coin flip. F4_FAN is a different stream (no overlap >= 0.15 with F4_PULL).","Not BH-tested per cell. 'Best net' is about 0.01R better than the median: noise-level."],
  "Overlaps N01 0.22, N18 0.21, N23 0.20.",UNIV),
 item("C:N22_VORTEX_PSAR","N22_VORTEX_PSAR (Vortex + PSAR)",
  "6.34 trades/day, gross about 0 (+0.002/+0.004/+0.008), long 0.51. A distinct indicator family.",
  ["Overlaps N10 0.21 and F12_MSS 0.26, so it partly duplicates wave-1 exposure."],"Covers F12_MSS_DISP partly (0.40). Overlaps N07 0.29.",UNIV),
 item("D:F12_MSS","F12_MSS (market-structure shift, DeepSeek)",
  "5.79 trades/day. The reversal-structure family. Covers F12_MSS_DISP (100% nested). Gross about 0, long 0.50.",
  ["DeepSeek: 1.5 live days.","Overlaps N22 0.26 and S4 0.26."],"Absorbs F12_MSS_DISP.",UNIV),
 item("C:N02_ST_KST","N02_ST_KST (supertrend + KST)",
  "5.64 trades/day. 15m 5y gross +0.018R (P1 +0.015 / P2 +0.024; B in the cost lens, reproduced).",
  ["Overlaps N18 0.30 (wave 1).","B grades sit at noise level (about 3 of 105 cells expected by chance)."],"Supertrend cousin of S2/N04/N01/N23.",UNIV),
 item("C:V39_ALL","V39_ALL (composite V3.9)",
  "5.12 trades/day, gross +0.010/+0.012 at 15m/30m, A grade in multi_tf (noise-level), net -0.114R (second-best core).",
  ["Composite rules may duplicate the components' signals (max overlap 0.19 with N23)."],"Low overlap (<= 0.19).",UNIV),
 item("D:F16_FIB500","F16_FIB500 (Fibonacci 50% retrace, DeepSeek)",
  "4.99 trades/day. 15m gross +0.022R, BH q 0.020. It shares only 18% of signals with F16_FIB382, so it is close to an independent replication of 'AI on top of a small real tilt'.",
  ["Slow (about 7.7 weeks to 0.1R paired); in wave 2 it cannot reach 0.1R alone by 12/31 (MDE about 0.094R)."],"Pairs with FIB382; FIB618 nested in F10_OTE.",UNIV),
 item("C:N01_ST_EMA","N01_ST_EMA (supertrend + EMA)",
  "5.01 trades/day. The only allowed strategy with a per-cell BH-significant exit-style result (fixed tp1R at 15m, research/exitstyle), so it gives one pre-registered custom-value test on an AI trader.",
  ["Overlaps S2 0.32 and N23 0.335.","Live v3a 15m -0.47, opposite sign to the later runs."],"Supertrend cousin.",
  ["Shadow ②′: tp1R at 15m (5y exitstyle BH per cell; live tp1R/1.5R mostly 'no gain'). Adopt only through the gate, and never mid-test for the judged AI trader.",UNIV])]
J["wave2"]=W2
J["opus_twins"]={
 "picks":[{"twin_of":"N10_HA_PSAR","when":"wave 1","why":"Core, mixed-side, best-supported base, 6.3 decisions/day."},
          {"twin_of":"F7_RF_TRIPLE","when":"wave 1","why":"Different family and source (DeepSeek), largest skip choice set, 6.6/day."},
          {"twin_of":"S4_BB_BBP","when":"wave 2, only if the measured cost allows","why":"The exit-heavy trader: tests whether Opus manages exits differently, not just entries."}],
 "design":"A twin sees exactly the Sonnet trader's wake moments and screens (design v2 6-2). Its account is separate, and its comparison is paired per decision: Opus R minus Sonnet R on the same signals, both also scored against the rule-alone replay. To save cost, wake twins on entry decisions plus held-timeframe bar closes only (no 0.5R move wakes).",
 "power":"Rough arithmetic: about 490 decisions per pair by 12/31. If the models disagree on about 30% of decisions, the per-pair MDE is about 0.07R per decision (about 0.23R per disagreement); pooled over 3 pairs, about 0.04-0.05R. A null result means 'no large model difference', not 'equal'.",
 "cost":"Opus costs about 2.4x Sonnet per call including model-scoped cache writes (verify2_cost_model). On these busy strategies each twin costs about 3-4 median-trader equivalents. That is why there are 2 twins first and a third only after the pilot."}
J["reserve"]=[
 {"strategy":"F9_IFVG","note":"5.36/day, 15m gross t 2.6 both halves. Same family as F9_FVG but a different stream; swap in if F9_FVG has a pipeline issue."},
 {"strategy":"F3_HHHL / F3_BOS","note":"6.2/5.8 per day, structure family. 15m gross -0.012/-0.006 (not BH). Live 68% short."},
 {"strategy":"F14_SMT","note":"5.9/day, BTC-relative divergence (unique information). 5y long 0.42-0.46 and live 0.35, so a mild short tilt. Gross negative but not BH. LF4: do not staff for its side-flip rank."},
 {"strategy":"DOGE (friend's strategy)","note":"3.90/day, A-grade gross (+0.009/+0.011/+0.018), best 1h/4h net. Slow (8.7 weeks to 0.1R paired). Owner's choice for any wave-2 slot."},
 {"strategy":"N09_ALLIG_AROON / N12_ICHI_AO / N07_ICHI_CMO","note":"4.0-4.5/day with positive 5y gross. N12 lost to the live coin flip (two-sided p 0.057). Ichimoku: pick at most one."},
 {"strategy":"N16_BBRSI / F1_RSI_DIV","note":"Reversion and divergence stand-ins (4.1/5.0 per day). Gross slightly negative, not BH. Overlap 0.29 with each other."},
 {"strategy":"OBV_S, N13_3OUTSIDE, F6_VWAP_FAIL, F10_OTE (covers F16_FIB618), F9_BREAKER","note":"Allowed but slower or redundant."},
 {"strategy":"N24_DMI","note":"Only as a regime-labelled extra after a rising-market stretch, paired with a long-heavy trader. 5y long 0.18-0.21. It has a per-cell BH exit-style result (tp1.5R/2R)."}]
J["exclude"]=[
 {"strategy":"N17_KC_RSI (all tf)","reason":"BH-significant NEGATIVE 5y gross at 15m (t -3.35), 30m (-2.97), 1h (-3.90). Live signals were 84-87% long in clustered bursts. It is the most frequent strategy, but it is an anti-edge, so it goes."},
 {"strategy":"N20_EMA9_CHOP","reason":"Structurally short-only (5y long share 0.00). Its live 'skill' is the falling market (LF4, F5)."},
 {"strategy":"N24_DMI","reason":"Short-heavy (5y long 0.18-0.21; live 0.10), a regime bet as test material. Kept in reserve."},
 {"strategy":"F11_RAID / F11_TSOUP / F13_RAID_PD","reason":"BH-negative 15m gross (F11_RAID t -4.01). Trade-level identical at 15m (F11_TSOUP shares about 71% of its 5y signals with F11_RAID and has the same anti-edge)."},
 {"strategy":"F17_Z / F17_Z_HL","reason":"BH-negative gross at 15m/1h/4h. Signal streams 94-100% the same."},
 {"strategy":"F15_ORB, F15_ASIA_SWEEP, F11_PO3, F1_PVT_DIV","reason":"BH-negative gross cells (F15_ORB@15m t -4.11; ASIA_SWEEP 15m/30m/1h; PO3 30m/1h; PVT_DIV 15m)."},
 {"strategy":"F4_PULL","reason":"Worse than the coin flip (two-sided q 0.056; 1h p 0.003). All-long during the decline. Regime-swinging by construction (DS10)."},
 {"strategy":"F15_OPEN0000 / F15_OPEN0930 / F15_LON_BRK / F15_ASIA_BRK","reason":"About 1-2 trades/day and identical streams across timeframes (session-clock strategies). Too few decisions; 16-20+ weeks for 0.2R."},
 {"strategy":"N06_MACD_ORB, F12_MSS_DISP, F13_FVG_PD, F10_M2022, F16_FIB618, F5_BOX_HTF, F7_RF_ONLY","reason":"Nested inside a staffed or excluded parent (98%, 100%, 99.5%, 99.8%, 97% (in F10_OTE), 100%, 58%)."},
 {"strategy":"F5_BOX family","reason":"2.7/1.4/0.6 trades/day, short-tilted (5y long 0.31-0.35). The 'watch' grade was refuted by the verifier."},
 {"strategy":"S3_CMO_SANDWICH, V45_AMB, OBV_B, F2_DEMARK, F9_OB, F8_VWICK, F3_BOS_ZONE","reason":"5y gross negative at all three AI timeframes (not individually BH, but consistent). Several also have low frequency (S3/V45 about 3/day)."},
 {"strategy":"N14_ICHI_RSI, N15_KC_AO, N21_ST_RSI_ADX, S1_EMA_RSI_CHOP, N11_BREAKAWAY, N03_ADX_GC, N08_ICHI_WR, S5_DONCHIAN_MFI, F4_PULL_RSI, F5_BOX_RSI","reason":"Near-silent (< 1.3 trades/day). 'Low cost drag' here means 'too few trades to judge'."},
 {"strategy":"N05_PSAR_POC, N19_FIB_CHOP, S6_EMA_DMI_ADX, N13_3OUTSIDE (not excluded, deprioritized)","reason":"About 3 trades/day (11-15 weeks to 0.1R unpaired). N19 is short-tilted (long 0.40); S6 overlaps N24 0.46."},
 {"strategy":"REEL5M_BB_MA200 and D01-D10","reason":"5m reel: steady loss, a control only. The D list has no rule baseline or 5y outcomes for most definitions, so no paired measurement is possible."}]
J["design_implications"]=[
 "PAIRING (primary metric): for every signal shown to an AI trader (taken, skipped, or arriving while flat), store the rule-alone outcome of that same signal through the same code exits, scored in R at the default 2 ATR stop. AI contribution per decision = AI R (0 if skipped) minus rule-alone R. Never compare to the ② rule account's P&L: it is one-position and holds different signals. Decompose it into skip/entry, exit (AI exit vs the code-exit twin on the same entry: '원래대로 뒀다면'), and timing (near or late entries scored against the on-time entry). Report the mean, a day-block bootstrap or sign-flip p, the long share and the regime. Pre-register in a separate never-edited file with a hash (the earlier PREREG was edited).",
 "POWER BOOKKEEPING: replace the assumed paired sd (0.71 x sd_R, i.e. about 50% skip-driven differences) with the measured sd after week 2 and recompute each trader's weeks-to-MDE. Count AI no-answers (20 s deadline) as a separate category, excluded from the AI-vs-rule mean and reported. Cluster by day across traders; within one trader clustering is minor (MT3).",
 "COINS: per decision, also store (a) the side-flipped outcome at the same moment with the same exits, and (b) a same-side random-time coin drawn from a pool fixed in advance (same strategy timeframe, same coin, same UTC day). The pool definition changes results (N17 +0.39 vs +0.52), so fix it before 10/17. A trader counts only if it beats the rule-alone baseline and both coins. Do not use the live coin-flip accounts.",
 "TIE RULES (code): setup B, i.e. 15m/30m/1h, plus 4h only where stop + 1 ATR sits inside the 20x liquidation distance, checked per signal. On simultaneous signals: longer timeframe first, then widest stop % first (lowest cost in R; +0.014R core / +0.019R DeepSeek free 5y gain, verify2_multi_tf), then random. Never BTC-first coin order. No switching. New signals while holding are ignored except an opposite signal on the held coin. If switching is ever enabled, allow only switches to a higher timeframe and charge each one a round trip (0.2R at 15m).",
 "SIZING: fixed 1% risk per stop for every AI trader and its rule shadow. Leverage is chosen by code (highest of 30/20x that fits at 15m/30m, 20x at 1h, 20x at 4h with the per-signal liquidation check). Exits in price/R, not ROE, so leverage never moves the take-profit. Log confidence but do not map it to risk until confidence-vs-R Spearman > 0 over >= 200 shadow trades. Cap the cross-trader exposure per coin and direction (picks share 0.1-0.3 of signals, so several traders can hold the same trade).",
 "HOLD CHECKS: held-timeframe bar close + 1.0R move wake (not 0.5R) + opposite signal on the held coin + release events. This keeps the exit component measurable at about 20 traders. Event-only checks would leave too few exit decisions to measure.",
 "UNIVERSAL CODE RULES (shadow first, not AI discretion): 1h state exit (close a 1h position at bar 4 if <= -0.5R): post hoc, +0.012..+0.022R/signal, 14 clusters, so run it as a ②′ shadow. Bar-close lock updates at 15m/30m. Breakeven only after MFE >= +1R, with code computing the net-zero price. Wider ladder geometry at 1h (arm >= 1.5R or 10-20x geometry; consistent across 3 runs + 5y but CI > 0 only under 1h clusters). HTF-agreement filter at most as a tie-breaker (<= 0.01R, the only custom value positive in both units and halves). Avoid BCH/LTC at large notional.",
 "FREEZE: no custom-value adoption for any judged AI trader between 10/17 and 12/31 (X3, CV1: last week's best value loses out of sample, and some cells are significantly hurt). The weekly search runs in ②′ as a record. If anything is adopted, the paired baseline must switch to the same values on the same date.",
 "ROLL-OUT: replay pilot on stored v4 signals for the 10 wave-1 strategies (cost, latency, format), measuring tokens with count_tokens first. Pin effort and max_tokens per call type and set max_retries. Pre-warm or stagger the shared cache at bar closes (otherwise about +$280/month in cache writes)."]
J["what_would_change_my_mind"]=[
 "Measured paired-difference sd much lower than assumed (the AI follows the rule on most signals): power rises, and wave 2 could go to 20+ traders. Much higher (the AI skips almost everything or reverses exits often): keep 10-12 and move seats to the highest-supply strategies (N04, F7, F6, N23).",
 "Measured cost <= ~$8 per heavy trader-month with held-timeframe bar-close checks: 25-30 seats become affordable without event-only thinning. Above ~$15: stop at wave 1 + 2 twins.",
 "A sustained one-direction market for weeks: replace the most side-tilted picks in live use (live long share < 0.3) and weight verdicts by side-balanced R. If it trends up, N24_DMI becomes usable as a regime-paired test.",
 "If the owners' priority is a 12/31 real-money candidate rather than measuring AI value: drop the DeepSeek seats to 1-2 exploratory (DS14) and fill with core (N23, N02, V39, N09).",
 "If after 3-4 weeks the pooled wave-1 paired effect is <= 0 with MDE <= 0.08R: do not add wave 2. If it is >= +0.2R on several traders: strategy choice matters less; expand on cost grounds only.",
 "A pre-registered test confirming that per-strategy exit headroom replicates (AIH-6 says it does not), or a pre-registered confirmation of the 1h state exit: then weight exit-heavy traders (S4, N25) more and give 1h a larger share.",
 "If the per-signal 20x check admits almost no 4h signals once volatility rises: drop 4h from setup B entirely (it is 1-4% of trades) and N23 loses its special role."]
J["honest_warnings"]=[
 "Gross edge before costs is about zero for every pick (5y |gross| <= 0.026R). The AI must add about 0.2R per trade at 15m (0.11-0.16R at 30m, 0.08-0.12R at 1h) to break even, and nothing measured so far is within a factor of about 5 of that. The most likely result is AI minus rule about 0 to slightly negative, because of extra round trips.",
 "These picks maximise measurement speed and cleanness, not expected profit. 5-year cells differ by about 0.012% per notional, so the strategy choice matters little for P&L.",
 "The 'paired' weeks assume the paired-difference sd is 0.71 x the per-trade sd. That is an assumption to be replaced in week 2. The 'unpaired' column is the conservative bound and matches the verified 60-day MDE of about 0.13R at about 4.3 trades/day. All weeks are for 80% power and a single two-sided 5% test, with no BH adjustment (multiply weeks by about 1.7 for a BH-adjusted single-trader verdict among about 18).",
 "Trades/day are 5-year rule numbers for one position at a time under setup B. The live quiet market lengthens holds, and an AI that skips changes both trades and decisions. 15m stops are now about 1.5x tighter than the 5-year typical, so costs in R are higher.",
 "The 5-year long share of every pick is 0.47-0.52, but in the falling live market most of them signalled 27-42% long. The first weeks' results will carry a direction tilt. Report the side mix and coin baselines with every verdict.",
 "The four DeepSeek picks rest on the 5-year data and only 1.5 live days. The DeepSeek family's pooled gross is slightly negative. Their purpose is variety for measurement. DS14 would not put them in a 12/31 judged set.",
 "Picks share 0.1-0.28 of their 15m signals at the same bar (N10/N23 0.42 in wave 2). The cohort is partly one correlated bet on the same market moments, so resample by day across traders.",
 "AI-visible exit value is tiny in the evidence (1h state exit about +0.02R, post hoc). The rule-based exit gains are mostly intrabar code stops the AI cannot see. Do not expect the exit component to carry a trader.",
 "Even with perfect measurement, a 0.05R AI effect per trader cannot be confirmed by 12/31. Only the pooled cohort can see it, and it would still be far below break-even. A trader passing a 30-day check at < 0.3R is more likely luck than skill (LF8).",
 "Cost estimates are character-based. Thinking length (effort defaults: Sonnet high) can triple the bill. All prices must be re-checked and measured in the pilot."]
J["sources_and_method"]={"trades_per_day_and_net":"lens2/multi_tf/summ/per_strategy.csv (combo ALL|LTF, period all = setup B, 2021-08..2026-09)",
 "per_tf_gross_long_share_sd":"sel_tp/fy_side.json, built by sel_tp/fy_side.py from lens2/multi_tf/outc/*.npz (every signal, house exits)",
 "overlap":"sel_tp/ov15_exact.json, built by sel_tp/overlap.py: share of the smaller strategy's 15m signals with the same coin, bar and side",
 "power":"sel_tp/power.py: n = (2.8*sd/d)^2; sd = per-trade R sd of the setup-B timeframe mix; weeks = n/(7*tpd); paired sd = 0.71*sd (assumption); MDE by 12/31 uses 75 days (10/17 start), wave 2 uses 61 days",
 "anti_edges":"verify_fiveyear missed list (18 BH-negative gross cells); F4_PULL from verify_luck_flow",
 "calls":"lens2_cost_model strategy_notes, setup B ignore-P3/P2 (5y) and live v4 ignore-P2"}
json.dump(J,open(out,'w'),ensure_ascii=False,indent=1)
print(len(json.dumps(J,ensure_ascii=False)))
