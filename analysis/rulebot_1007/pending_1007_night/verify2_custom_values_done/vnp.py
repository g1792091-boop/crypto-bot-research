"""All 36 cells: R2-selected streams evaluated in net % per notional with own day-cluster bootstrap (and a
week-cluster bootstrap). Uses the analyst's wf_R2 day arrays (reproduced on 4 cells by vwf.py).
usage: python3 -I vnp.py <scratchpad>"""
import sys, os, json
sys.path.append("/root/.local/lib/python3.11/site-packages")
import numpy as np

SCR = sys.argv[1]
WF = os.path.join(SCR, "lens2/custom_values/work/wf_R2")
HERE = os.path.dirname(os.path.abspath(__file__))
STR = ["S2_ST_ROC", "N23_HA_ST", "N24_DMI", "N10_HA_PSAR", "S4_BB_BBP", "N06_MACD_ORB", "OBV_B", "F6_VWAP_CROSS",
       "F9_FVG", "N17_KC_RSI", "N16_BBRSI", "F5_BOX"]
cells = [f"{s}_{tf}" for s in STR for tf in ("15m", "30m", "1h")]
KEYS = ["s4_w26|naive", "s4_w13|naive", "s1_w1|naive", "s4_w26|naive_F", "s4_w13|naive_F", "s4_w26|naive_S",
        "s4_w26|naive_P", "s4_w26|gate_100_0.05_2.0", "s4_w26|gate_100_0.15_2.0"]
DEF = 3
acc = {k: {x: [] for x in ("n", "P", "S", "dn", "dP", "dS")} for k in KEYS}
for c in cells:
    z = np.load(os.path.join(WF, c + ".npz"))
    Dn, DP, DS = z["Dn"].astype(float), z["DP"].astype(float), z["DS"].astype(float)
    keys = list(z["sel_keys"])
    nd = Dn.shape[0]
    ar = np.arange(nd)
    wk = ar // 7
    for k in KEYS:
        cd = z["sel"][keys.index(k)].astype(int)[wk]
        acc[k]["n"].append(Dn[ar, cd]); acc[k]["P"].append(DP[ar, cd]); acc[k]["S"].append(DS[ar, cd])
        acc[k]["dn"].append(Dn[:, DEF]); acc[k]["dP"].append(DP[:, DEF]); acc[k]["dS"].append(DS[:, DEF])
rng = np.random.default_rng(5)
Wd = np.stack([np.bincount(rng.integers(0, nd, nd), minlength=nd) for _ in range(1000)]).astype(float)
nwk = nd // 7
Ww = np.stack([np.repeat(np.bincount(rng.integers(0, nwk, nwk), minlength=nwk), 7) for _ in range(1000)]).astype(float)
res = {}
half = np.arange(nd) < 1050  # 2024-07-01 is day 1064? computed below
olo = np.datetime64("2021-08-02")
split = (np.datetime64("2024-07-01") - olo).astype(int)
half = np.arange(nd) < split
for k in KEYS:
    a = {x: np.stack(v, 1) for x, v in acc[k].items()}  # days x cells
    out = {}
    for unit, num, den in (("netpct_pp", "P", "dP"), ("R2", "S", "dS")):
        pt = a[num].sum() / a["n"].sum() - a[den].sum() / a["dn"].sum()
        pa = a[num][half].sum() / a["n"][half].sum() - a[den][half].sum() / a["dn"][half].sum()
        pb = a[num][~half].sum() / a["n"][~half].sum() - a[den][~half].sum() / a["dn"][~half].sum()
        sc = 100 if unit == "netpct_pp" else 1
        o = {"delta": round(pt * sc, 5), "halfA": round(pa * sc, 5), "halfB": round(pb * sc, 5)}
        for nm, Wt in (("ci_day", Wd), ("ci_week", Ww)):
            b = (Wt @ a[num]).sum(1) / (Wt @ a["n"]).sum(1) - (Wt @ a[den]).sum(1) / (Wt @ a["dn"]).sum(1)
            o[nm] = [round(float(x) * sc, 5) for x in np.percentile(b, [2.5, 97.5])]
        out[unit] = o
    out["default_netpct_per_trade"] = round(float(a["dP"].sum() / a["dn"].sum() * 100), 5)
    res[k] = out
    print(k, out, flush=True)
json.dump(res, open(os.path.join(HERE, "vnp.json"), "w"), indent=1)
