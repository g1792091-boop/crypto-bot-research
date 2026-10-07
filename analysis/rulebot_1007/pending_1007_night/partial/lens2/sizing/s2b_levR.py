"""Q3: same signals, same 2 ATR stop, leverage 10..50 changes only the ROE-ladder price levels (and liquidation).
Mean net R, gross R, cost R, exit mix, gap-liquidations per tf x L, all signals and K-executable-at-L signals;
week-block bootstrap CI of the paired difference vs 20x.
    python3 -I -B s2b_levR.py <workdir> <lev_dir> <out_dir>"""
import os, sys
sys.dont_write_bytecode = True
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
LEV, OUT = sys.argv[2], sys.argv[3]
rng = np.random.default_rng(7)
rows = []
for tf in ("15m", "30m", "1h", "4h"):
    d = pd.read_pickle(os.path.join(LEV, f"lev_{tf}.pkl"))
    wk = (d.ts.values // (7 * 86400 * 10**9))
    uw, inv = np.unique(wk, return_inverse=True)
    done = np.ones(len(d), bool)
    for L in (10, 20, 30, 40, 50):
        done &= d[f"rs_K{L}"].values < 3
    for scope in ("all", "exec20", "exec50"):
        s = done.copy()
        if scope == "exec20": s &= d.okK20.values
        if scope == "exec50": s &= d.okK50.values
        if s.sum() < 100: continue
        base = d["R_K20"].values[s]
        for L in (10, 20, 30, 40, 50):
            Rv = d[f"R_K{L}"].values[s]; g = d[f"gR_K{L}"].values[s]; rs = d[f"rs_K{L}"].values[s]
            diff = Rv - base
            # week-cluster bootstrap of the mean paired difference
            sums = np.bincount(inv[s], weights=diff, minlength=len(uw)); cnt = np.bincount(inv[s], minlength=len(uw))
            keep = cnt > 0; sums, cnt = sums[keep], cnt[keep]
            bs = []
            for _ in range(400):
                k = rng.integers(0, len(sums), len(sums)); bs.append(sums[k].sum() / cnt[k].sum())
            lo, hi = np.quantile(bs, [.025, .975])
            rows.append(dict(tf=tf, scope=scope, L=L, n=int(s.sum()), mean_R=Rv.mean(), mean_gross_R=g.mean(),
                             mean_cost_R=(g - Rv).mean(), win=(Rv > 0).mean(), sl_share=(rs == 0).mean(),
                             lock_share=(rs == 1).mean(), liq_gap_share=(rs == 2).mean(),
                             mean_win_R=Rv[Rv > 0].mean(), mean_loss_R=Rv[Rv <= 0].mean(),
                             diff_vs20=diff.mean(), diff_lo=lo, diff_hi=hi,
                             liqM_share=(d[f"rs_M{L}"].values[s] == 2).mean()))
out = pd.DataFrame(rows)
out.to_csv(os.path.join(OUT, "s2b_lev_R.csv"), index=False)
pd.set_option("display.width", 250)
print(out.round(4).to_string(index=False))
