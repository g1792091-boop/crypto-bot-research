"""Part 4: direct check of the required-edge numbers by injecting a favourable drift into real 5m paths.
Every trade's price path is multiplied by exp(mu * bars_since_start) in the trade's direction, where
mu per 5m bar = IR * sd_5m / sqrt(bars per year).  We find the IR at which E[ROE] after costs crosses 0."""
import json
import numpy as np
import pandas as pd
import common
from common import *
import sim

en = pd.read_csv(f"{OUT}/entries_5m.csv.gz")
sd5 = json.load(open(f"{OUT}/sd_1bar.json"))["5m"]
BPY = 365 * 288
cap = int(90 * 1440 / 5)
K = int(np.ceil(np.log2(cap + 1)))
sim.LEVS = [5, 10, 20, 25, 30, 40, 50]
IRS = [0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96]
data = {s: load(s, "5m") for s in COINS}
rows = []
for ir in IRS:
    mu = ir * sd5 / np.sqrt(BPY)
    recs, groups = None, []
    for sym in COINS:
        df = data[sym]
        tsec = df["ts"].values.astype("datetime64[s]").astype(np.int64)
        n = len(df)
        e_ = en[en.sym == sym]
        idx_all = np.searchsorted(tsec, e_["ts"].values)
        for sgn in (1, -1):
            m = e_["dir"].values == sgn
            if not m.any():
                continue
            sc = np.exp(sgn * mu * np.arange(n))
            o, h, l, c = (df[k].values.astype(float) * sc for k in ["open", "high", "low", "close"])
            mx, mn = build_sparse(h, l, K)
            idx = idx_all[m].astype(np.int64)
            r = sim.run_block(o, h, l, c, tsec, mx, mn, idx, np.full(m.sum(), sgn, dtype=np.int8), cap, 5)
            if recs is None:
                recs = {k: {kk: [vv] for kk, vv in v.items()} for k, v in r.items()}
            else:
                for k, v in r.items():
                    for kk, vv in v.items():
                        recs[k][kk].append(vv)
            groups.append(COINS.index(sym) * 100000 + tsec[idx] // (7 * 86400))
    recs = {k: {kk: np.concatenate(vv) for kk, vv in v.items()} for k, v in recs.items()}
    agg = pd.DataFrame(sim.aggregate("5m", "5m", recs, np.concatenate(groups), 5))
    agg["inj_ir"] = ir
    rows.append(agg[["inj_ir", "L", "variant", "pTP_adv", "pLIQ_adv", "pSTOP_adv", "EROE_adv", "EROE_se_adv", "mean_hours"]])
    print(f"IR={ir} done", flush=True)
res = pd.concat(rows, ignore_index=True)
res.to_csv(f"{OUT}/drift_injection_5m.csv", index=False)

base = pd.read_csv(f"{OUT}/bracket_zero_edge.csv")
base = base[(base.tf == "5m") & (base.res == "5m")].set_index(["L", "variant"])
out = []
for (L, var), g in res.groupby(["L", "variant"]):
    g = g.sort_values("inj_ir")
    x, y = g["inj_ir"].values, g["EROE_adv"].values
    k = np.where((y[:-1] < 0) & (y[1:] >= 0))[0]
    ir0 = float(x[k[0]] + (0 - y[k[0]]) * (x[k[0] + 1] - x[k[0]]) / (y[k[0] + 1] - y[k[0]])) if len(k) else np.nan
    pt = g["pTP_adv"].values
    ptp_at = float(np.interp(ir0, x, pt)) if np.isfinite(ir0) else np.nan
    out.append(dict(L=L, variant=var, breakeven_ir_injected=ir0, pTP_at_breakeven=ptp_at,
                    wald_estimate_ir=base.loc[(L, var), "req_ann_ir_adv"], pstar_tilt=base.loc[(L, var), "pstar_adv"],
                    EROE_at_IR2=float(np.interp(2, x, y)), EROE_at_IR1=float(np.interp(1, x, y))))
o = pd.DataFrame(out)
o.to_csv(f"{OUT}/drift_breakeven_5m.csv", index=False)
pd.set_option("display.width", 250)
print(res.round(4).to_string(index=False))
print(o.round(4).to_string(index=False))
