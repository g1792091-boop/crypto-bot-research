"""Own scenario table: monthly $ for N Sonnet traders (+5 Opus twins) from my 5y daily call arrays and live v4 rates.
python3 -I v_scen.py <v5y_daily.npz> <live_mine.csv> <out_csv>"""
import sys, itertools, json
sys.path.insert(0, "/root/.local/lib/python3.11/site-packages")
import numpy as np, pandas as pd
Z = np.load(sys.argv[1]); LIVE = pd.read_csv(sys.argv[2]); OUT = sys.argv[3]
CNT = ["entry", "trades", "switch", "p1_sw", "p1_ign", "p2_sw", "p2_ign", "mv05", "mv10", "otf_sw", "otf_ign", "held_min"]
RARE = {"N14_ICHI_RSI", "N15_KC_AO", "S1_EMA_RSI_CHOP", "N21_ST_RSI_ADX"}
PR = {"sonnet": dict(i=2, o=10, cr=.2, cw=2.5), "opus": dict(i=4, o=20, cr=.2, cw=5), "haiku45": dict(i=1, o=5, cr=.1, cw=1.25)}
# token bases: analyst (screens_measure mid) vs mine (v_screen heuristic mid, journal 20 lines)
TOK = {"analyst": dict(cached=5058, market=3651, unc_e=1435, unc_h=1137),
       "mine": dict(cached=7236, market=5622, unc_e=1980, unc_h=1826)}
THINK = {"low": (300, 100), "mid": (800, 300), "high": (2000, 800)}; ANS = (100, 45)
def price(model, kind, tb, think):
    p = PR[model]; t = TOK[tb]; out = ANS[kind] + THINK[think][kind]
    return (t["cached"] * p["cr"] + (t["unc_e"] if kind == 0 else t["unc_h"]) * p["i"] + out * p["o"]) / 1e6
# market-bundle writes/day (v_cache.py, live v4 timestamps, pre-warmed 'serial' case); burst case ~ every call
WR_S = {"P4": {10: 110, 20: 122, 30: 125}, "P2": {10: 59, 20: 65, 30: 70}, "P3": {10: 86, 20: 103, 30: 113}, "P1": {10: 110, 20: 122, 30: 125}}
WR_O = {"P4": 90, "P2": 53, "P3": 59, "P1": 90}
def EH(a, mode, pol, mv="mv05"):
    g = lambda k: a[CNT.index(k)] if isinstance(a, np.ndarray) else a[k]
    if mode == "switch":
        E = g("entry") + g("switch"); H = {"P1": g("p1_sw"), "P2": g("p2_sw"), "P3": g(mv) + g("otf_sw"), "P4": g("p2_sw") + g(mv) + g("otf_sw")}[pol]
    else:
        E = g("entry"); H = {"P1": g("p1_ign"), "P2": g("p2_ign"), "P3": g(mv) + g("otf_ign"), "P4": g("p2_ign") + g(mv) + g("otf_ign")}[pol]
    return E, H
strats = sorted(set(k.split("|")[0] for k in Z.files)); pool = [s for s in strats if s not in RARE]
rng = np.random.default_rng(11); SUB = {n: [list(rng.choice(pool, n, replace=False)) for _ in range(100)] for n in (10, 20, 30)}
rows = []
for n, setup, pol, mode in itertools.product((10, 20, 30), "AB", ("P1", "P2", "P3", "P4"), ("switch", "ignore")):
    arr = {s: Z[f"{s}|{setup}|feas"] for s in pool}
    eh = {s: EH(arr[s], mode, pol) for s in pool}
    lv = LIVE[(LIVE.run == "v4") & (LIVE.kind == "strategy") & (LIVE.setup == setup)].set_index("strategy")
    for tb, think, opus_writes in (("analyst", "mid", False), ("analyst", "mid", True), ("mine", "mid", True), ("mine", "low", True), ("mine", "high", True)):
        ce, ch = price("sonnet", 0, tb, think), price("sonnet", 1, tb, think)
        coe, coh = price("opus", 0, tb, think), price("opus", 1, tb, think)
        mk = TOK[tb]["market"]
        res = []
        for sub in SUB[n]:
            E = sum(eh[s][0] for s in sub); H = sum(eh[s][1] for s in sub)
            means = sorted(sub, key=lambda s: (eh[s][0] + eh[s][1]).mean()); mid5 = means[n // 2 - 2: n // 2 + 3]
            E5 = sum(eh[s][0] for s in mid5); H5 = sum(eh[s][1] for s in mid5)
            ws = WR_S[pol][n] * mk * (PR["sonnet"]["cw"] - PR["sonnet"]["cr"]) / 1e6
            wo = (WR_O[pol] * mk * (PR["opus"]["cw"] - PR["opus"]["cr"]) / 1e6) if opus_writes else 0
            son = E * ce + H * ch + ws; op = E5 * coe + H5 * coh + wo; c = son + op
            roll = np.convolve(c, np.ones(30), "valid")
            # live v4 basis (mean only)
            Ls = [s for s in sub if s in lv.index]
            le = sum(EH(lv.loc[s], mode, pol, "mv0.5_cd0")[0] for s in Ls) * n / max(len(Ls), 1)
            lh = sum(EH(lv.loc[s], mode, pol, "mv0.5_cd0")[1] for s in Ls) * n / max(len(Ls), 1)
            l5 = [s for s in mid5 if s in lv.index]
            le5 = sum(EH(lv.loc[s], mode, pol, "mv0.5_cd0")[0] for s in l5) * 5 / max(len(l5), 1)
            lh5 = sum(EH(lv.loc[s], mode, pol, "mv0.5_cd0")[1] for s in l5) * 5 / max(len(l5), 1)
            live = 30 * (le * ce + lh * ch + ws + le5 * coe + lh5 * coh + wo)
            res.append([30 * c.mean(), 30 * np.percentile(c, 90), roll.max(), (E + H).mean(), 30 * son.mean(), 30 * op.mean(), live])
        r = np.median(np.array(res), 0)
        rows.append(dict(n=n, setup=setup, policy=pol, mode=mode, tokens=tb, thinking=think, opus_cache_writes=opus_writes,
                         calls_day=round(r[3]), mean_month=round(r[0]), p90_day_x30=round(r[1]), max_30d=round(r[2]),
                         sonnet_part=round(r[4]), opus5_part=round(r[5]), live_v4_mean_month=round(r[6]),
                         p90_ratio=round(r[1] / r[0], 3), max30_ratio=round(r[2] / r[0], 3)))
df = pd.DataFrame(rows); df.to_csv(OUT, index=False)
pd.set_option("display.width", 250)
sel = df[(df.thinking == "mid") & (df.n == 30) & (df.setup == "B")]
print(sel.drop(columns=["n", "setup", "thinking"]).to_string(index=False))
print(df[["p90_ratio", "max30_ratio"]].describe().round(3).to_string())
print(json.dumps({"price_sonnet_entry_analyst": price("sonnet", 0, "analyst", "mid"), "price_sonnet_entry_mine": price("sonnet", 0, "mine", "mid"),
                  "price_sonnet_hold_mine": price("sonnet", 1, "mine", "mid"), "price_opus_entry_mine": price("opus", 0, "mine", "mid"),
                  "price_opus_hold_mine": price("opus", 1, "mine", "mid")}))
