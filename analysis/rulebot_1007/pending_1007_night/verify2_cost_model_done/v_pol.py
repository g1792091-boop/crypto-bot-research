"""Policy totals (calls per trader-day) from a per-strategy count table. python3 -I v_pol.py <csv> [mvcol]"""
import sys; sys.path.insert(0, "/root/.local/lib/python3.11/site-packages")
import sys, pandas as pd, numpy as np
df = pd.read_csv(sys.argv[1]); mv = sys.argv[2] if len(sys.argv) > 2 else "mv0.5_cd0"
RARE = {"N14_ICHI_RSI", "N15_KC_AO", "S1_EMA_RSI_CHOP", "N21_ST_RSI_ADX"}
for c in ["entry", "switch", "p1_sw", "p2_sw", "p1_ign", "p2_ign", mv, "otf_sw", "otf_ign", "opp_samecoin", "trades"]:
    if c not in df: df[c] = 0
df = df.fillna(0)
df["sw_P1"] = df.entry + df.switch + df.p1_sw; df["sw_P2"] = df.entry + df.switch + df.p2_sw
df["sw_P3"] = df.entry + df.switch + df[mv] + df.otf_sw; df["sw_P4"] = df.sw_P2 + df[mv] + df.otf_sw
df["ig_P1"] = df.entry + df.p1_ign; df["ig_P2"] = df.entry + df.p2_ign
df["ig_P3"] = df.entry + df[mv] + df.otf_ign; df["ig_P4"] = df.ig_P2 + df[mv] + df.otf_ign
df["dsg_P4"] = df.entry + df.opp_samecoin + df.p2_ign + df[mv] + df.otf_ign   # design-v2 style: only held-coin signals wake
df = df[~df.strategy.isin(RARE)]
grp = [c for c in ("run", "kind") if c in df] + ["setup"]
cols = ["occupancy", "entry", "trades", "switch", "sw_P1", "sw_P2", "sw_P3", "sw_P4", "ig_P1", "ig_P2", "ig_P3", "ig_P4", "dsg_P4", mv]
print(df.groupby(grp)[cols].median().round(2).to_string())
print("mean over strategies"); print(df.groupby(grp)[["occupancy", "sw_P4", "ig_P2", "ig_P3"]].mean().round(2).to_string())
