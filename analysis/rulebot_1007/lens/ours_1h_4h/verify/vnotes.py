"""Verifier: numbers behind a sample of the analyst's strategy notes, from own tables.
    python3 -I vnotes.py <v_cards.csv> <v_cells_1h_4h.csv> <out_real_dir> <export_dir>"""
import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
CA, CE, O, E = sys.argv[1:5]
C = pd.read_csv(CA); C = C[C.res == "tfbars"]
X = pd.read_csv(CE); X = X[X.res == "tfbars"]
AS = pd.read_csv(O + "/account_stats.csv"); AS = AS[AS.kind == "strategy"]
SF = pd.read_csv(O + "/coinflip_sideflip.csv"); SF = SF[(SF.level == "strategy_tf") & (SF.kind == "strategy")]
SR = pd.read_csv(O + "/sizing_rejections.csv"); SR["strategy"] = SR.account_id.str.split("@").str[0]; SR["tf"] = SR.account_id.str.split("@").str[1]
RP = pd.read_csv(O + "/replay_signals.csv", low_memory=False); RP = RP[RP.kind == "strategy"]
LT = pd.read_csv(O + "/luck_concentration.csv")
RUN = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
sample = [("N23_HA_ST", "4h"), ("N22_VORTEX_PSAR", "4h"), ("N09_ALLIG_AROON", "4h"), ("S6_EMA_DMI_ADX", "4h"),
          ("N02_ST_KST", "4h"), ("S4_BB_BBP", "4h"), ("V39_ALL", "4h"), ("N24_DMI", "4h"), ("N20_EMA9_CHOP", "4h"),
          ("N18_VWMA_MACD", "4h"), ("OBV_B", "4h"), ("N17_KC_RSI", "4h"), ("N03_ADX_GC", "4h"), ("S3_CMO_SANDWICH", "4h"),
          ("N05_PSAR_POC", "4h"), ("N03_ADX_GC", "1h"), ("N13_3OUTSIDE", "1h"), ("N24_DMI", "1h"), ("N22_VORTEX_PSAR", "1h"),
          ("N23_HA_ST", "1h"), ("N25_DST_CCI", "1h"), ("S2_ST_ROC", "1h"), ("N06_MACD_ORB", "1h"), ("N20_EMA9_CHOP", "1h"),
          ("N18_VWMA_MACD", "1h"), ("DOGE", "1h"), ("N04_ST_KLINGER", "1h"), ("N16_BBRSI", "1h"), ("N17_KC_RSI", "1h"),
          ("S1_EMA_RSI_CHOP", "1h"), ("N07_ICHI_CMO", "1h"), ("S4_BB_BBP", "1h"), ("OBV_B", "1h"), ("N12_ICHI_AO", "1h")]
for s, tf in sample:
    c = C[(C.strategy == s) & (C.tf == tf)]
    x = X[(X.strategy == s) & (X.tf == tf)]
    a = AS[(AS.strategy == s) & (AS.timeframe == tf)]
    acct = " ".join(f"{RUN[r.run]}:{int(r.n)}/{r.mean_R:+.2f}/{r.pnl_sum:+.0f}" for r in a.itertuples())
    f = SF[(SF.strategy == s) & (SF.timeframe == tf)]
    fl = f"flip {f.excess_R.iloc[0]:+.2f} n{int(f.n_pairs.iloc[0])} p{f.p_better.iloc[0]:.3f}" if len(f) else "flip -"
    rej = SR[(SR.strategy == s) & (SR.tf == tf)].symbol.str.replace("USDT", "").value_counts().to_dict()
    rp = RP[(RP.strategy == s) & (RP.timeframe == tf)]
    rrej = rp[rp.status == "REJECTED_SIZING"].symbol.str.replace("USDT", "").value_counts().to_dict()
    lk = LT[LT.account_id == f"{s}@{tf}"]
    if len(c) == 0:
        print(s, tf, "no 5y rows"); continue
    c = c.iloc[0]; x = x.iloc[0]
    print(f"{s} {tf} grade {c.grade} | 5y n {int(c.fy_n)} net {c.fy_mean_R:+.3f} t {c.fy_t_R:+.1f} (IS {c.fy_is_mean_R:+.3f}, CF {c.fy_cf_mean_R:+.3f}) "
          f"gross {c.fy_gross_R:+.3f} t {c.fy_gross_t:+.1f} (IS t {c.fy_is_gross_t:.2f} CF t {c.fy_cf_gross_t:.2f}) q72 {c.gross_q72:.3f} | "
          f"sized {x.sized_share:.2f} = {x.sized_per_day:.2f}/d | yrs {x.years_pos}/{x.years} | win {x.win:.1f} payoff {x.payoff:.2f} hold {x.median_hold_h:.1f}h | "
          f"live es n {int(c.es_n)} {c.es_mean_R:+.3f} [{c.es_lo:+.2f},{c.es_hi:+.2f}] G{int(c.es_G)} runs {c.es_v3a_n:.0f}/{c.es_v3b_n:.0f}/{c.es_v4_n:.0f} = {c.es_v3a_R:+.2f}/{c.es_v3b_R:+.2f}/{c.es_v4_R:+.2f} | "
          f"acct {acct} | {fl} | rej acct {rej} replay {rrej} | coins BTC {x.get('n_BTCUSD', np.nan)}/{x.get('R_BTCUSD', np.nan):+.3f} ETH {x.get('n_ETHUSD', np.nan)}/{x.get('R_ETHUSD', np.nan):+.3f}")
    if len(lk):
        print("   luck:", lk.drop(columns=[c for c in lk.columns if c in ("version","kind","group","exits","strategy","timeframe","account_id")]).round(2).to_dict("records"))
