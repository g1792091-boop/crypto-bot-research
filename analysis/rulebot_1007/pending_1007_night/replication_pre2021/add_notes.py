"""Add the interpretation and per-strategy recommendations to replication.json (numbers quoted come from the tables
written by repl_agg.py / write_out.py; see replication_KO.md for the per-number sources).  python3 -I -B add_notes.py <json>"""
import json
import sys

p = sys.argv[1]
d = json.load(open(p))
d["headline"] = ("None of the 4 BH-positive 5y cells replicates on 2020-01..2021-07 Binance futures data (F16_FIB382@15m +0.010R t 0.69, "
                 "F16_FIB500@15m +0.015R t 1.21, N23_HA_ST@4h -0.113R t -1.60 n 133, N20_EMA9_CHOP@5m flip-adjusted 0.000); "
                 "most BH-negative cells do (direction content: 12 of 18 BH-replicate, 2 nominal). F6_VWAP_CROSS@15m is the only "
                 "positive AI-timeframe cell that replicates (gross +0.018 t 2.72, direction +0.011 t 2.58). No cell is net positive. "
                 "F16@15m significance survives 5m-resolution exits on 2021-26 (t 3.89->4.49, 3.31->4.06).")
d["proves"] = [
    "The 5y positive direction cells are not confirmed out of sample in time (selection used 2021-08..2026-09 only); flip-adjusted direction content of all four is <= ~0 in 2020-21.",
    "Anti-edges (N17_KC_RSI 15m/30m/1h, F15_ASIA_SWEEP 15m/1h, F11_PO3 30m/1h, F17_Z 4h, F11 raid family in direction content) persist across regimes; N17 also on spot data.",
    "No rule cell is net positive even at the lower 2020-21 cost in R (wider stops).",
    "F16@15m 5y significance is not a bar-resolution artefact (5m exits raise t).",
]
d["does_not_prove"] = [
    "That F16 is wrong: pre sample = 25% of the 5y coin-days; power for t>=1.5 was ~0.62; gross difference z -1.0/-0.5 (direction content -1.85/-1.43).",
    "Regime: 2020-21 was a strong bull market with ~1.5x volatility; the house ladder earned on both sides (core 15m flip +0.024R), and 4h sizing admitted only 7.5% of signals (N23 133 rows, all in 2020).",
    "Anything about an AI's ability to add edge (only rule signals with house exits were tested).",
    "DeepSeek definitions had seen this period once before with their PREREG exits (deepseek200 'pre' split); house exits on it are new. Core 36 period-3 signals were used in research/entry_study, not in the AI selection.",
    "Funding is the constant 0.01%/8h (real funding: net R +0.001..+0.014 better); no mark-price data (liquidation on last price); no 1m history (5m is the finest resolution).",
]
d["recommendations"] = {
    "F16_FIB382 (15m, 1h)": "keep + flag: evidence is one period and one exit (DeepSeek PREREG exits give negative gross in all three periods); remove 'verified direction edge' wording",
    "F16_FIB500 (15m)": "keep + flag (same)",
    "N23_HA_ST (4h; 15m/30m/1h)": "keep + flag: drop the '4h core edge' rationale (sized-subset 4h contradicted in 2020; all-signal 4h ~+0.02 in both periods; net +0.007 with 5m exits)",
    "N20_EMA9_CHOP (5m)": "do not use the 5m result as evidence (flip-adjusted 0, spot -0.006); stays reserve",
    "F6_VWAP_CROSS": "keep (only positive cell whose direction replicates under BH; still net -0.12R pre, -0.17R 5y)",
    "F9_IFVG (15m)": "keep (nominal replication)",
    "F9_FVG (15m)": "keep (no change)",
    "N10_HA_PSAR (30m)": "keep (no change; 5y value data-sensitive: spot +0.002)",
    "N18_VWMA_MACD (15m)": "flag (5y +0.012 survives neither the period nor the spot-data check)",
    "S4_BB_BBP (1h)": "keep (uninformative)",
    "N25_DST_CCI": "flag 15m toward exclusion (no support in any data set; direction content -0.027 t -1.92); 1h keep",
    "F4_FAN (15m)": "flag",
    "V39_ALL (15m)": "flag; consider dropping from wave 2 (direction content -0.026 t -1.70, spot -0.006)",
    "N02_ST_KST (15m)": "flag (rule-account side of the Supertrend cluster anyway)",
    "N24_DMI (1h)": "consider excluding (pre -0.061 t -2.61 vs 5y +0.018)",
    "anti-edges N17_KC_RSI, F15_ASIA_SWEEP, F11_PO3, F17_Z(4h), F11_RAID/F13_RAID_PD/F11_TSOUP": "keep excluded; flipping them gains only +0.02..+0.06R direction, below cost",
    "F15_ORB (15m)": "keep excluded; its direction flips with the regime (5y -0.052, 2020-21 +0.055)",
}
json.dump(d, open(p, "w"), indent=1, ensure_ascii=False)
print("ok", len(d))
