"""DESCRIPTIVE: how much of fwd is market drift vs timing.  null_mean (from the gate's own common-shift null) =
the mean signed forward return of the same signals placed at random times (same long/short mix), i.e. the drift/beta
part.  fwd - null_mean = timing part.  Also the pooled buy-every-bar drift per (split, tf, H) from the bars."""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["SWEEP_DATA"] = os.path.join(HERE, "data")
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as L
S = os.path.dirname(HERE); O = os.path.join(HERE, "out")
IS = pd.read_csv(os.path.join(S, "combine", "out", "gate_all_is_applied.csv"))
OOS = pd.read_csv(os.path.join(O, "gate_all_oos_applied.csv"))
FIN = pd.read_csv(os.path.join(O, "gate_all_final_applied.csv"))
# pooled "long every admissible bar" drift from the OOS/FINAL bars (IS value from the IS gate: DOGE-free proxy not available
# without reading IS bars, so IS drift is taken as null_mean of the always-long-like cells is not used; we report OOS/FINAL only)
rows = []
for split in ("oos", "final"):
    for tf in L.TFS:
        panel = L.load_panel(tf, split)
        for H in L.HS:
            pr = L._prep_returns(panel, tf, split, H)
            r = np.concatenate([p["r"] for p in pr.values()])
            rows.append(dict(split=split, tf=tf, H=H, mean_r_all_bars_pct=100 * r.mean(), median_r_pct=100 * np.median(r),
                             E_abs_r_pct=100 * np.abs(r).mean(), share_r_pos=(r > 0).mean(), n=len(r)))
D = pd.DataFrame(rows)
D.to_csv(os.path.join(O, "market_drift_oos_final.csv"), index=False)
pd.set_option("display.width", 250)
print("Pooled long-every-bar drift (mean H-bar forward return over all admissible coin-bars):")
print(D.round(4).to_string())
out = []
for lab, g in (("IS", IS), ("OOS", OOS), ("FINAL", FIN)):
    f = g[g.n >= 100].copy()
    f["timing"] = f.fwd - f.null_mean
    f["long_share"] = f.n_long / f.n
    for tf in L.TFS:
        d = f[f.tf == tf]
        h = d[d.fwd >= d.mu_star]
        out.append(dict(split=lab, tf=tf, cells=len(d), cells_fwd_ge_mu=len(h),
                        median_long_share_of_hurdle_cells=h.long_share.median() if len(h) else np.nan,
                        median_null_mean_over_fwd_hurdle_cells=(h.null_mean / h.fwd).median() if len(h) else np.nan,
                        cells_timing_ge_mu=int((d.timing >= d.mu_star).sum()),
                        median_timing_over_mu=(d.timing / d.mu_star).median(), median_null_mean_over_mu=(d.null_mean / d.mu_star).median(),
                        mean_z=d.z.mean()))
T = pd.DataFrame(out)
T.to_csv(os.path.join(O, "drift_vs_timing_by_tf.csv"), index=False)
print("\nDrift vs timing, cells with n>=100 in that split:")
print(T.round(3).to_string())
# the cells people will ask about
K = ["strategy", "tf", "H"]
focus = [("N13_3OUTSIDE", "4h", 64), ("N13_3OUTSIDE", "4h", 16), ("DOGE_L", "1h", 64), ("N20_EMA9_CHOP", "5m", 4),
         ("N20_EMA9_CHOP", "5m", 16), ("N18_VWMA_MACD", "1d", 4), ("N23_HA_ST", "1d", 16), ("N07_ICHI_CMO", "4h", 4),
         ("N07_ICHI_CMO", "4h", 16), ("N03_ADX_GC", "30m", 4), ("DOGE_L", "15m", 64), ("DOGE_L", "30m", 64)]
fr = []
for lab, g in (("IS", IS), ("OOS", OOS), ("FINAL", FIN)):
    for s, tf, H in focus:
        r = g[(g.strategy == s) & (g.tf == tf) & (g.H == H)].iloc[0]
        fr.append(dict(split=lab, strategy=s, tf=tf, H=H, n=r.n, long_share=r.n_long / r.n if r.n else np.nan,
                       fwd_pct=100 * r.fwd, null_mean_pct=100 * r.null_mean, timing_pct=100 * (r.fwd - r.null_mean),
                       mu_star_pct=100 * r.mu_star, cost_pct=100 * r.cost_H, z=r.z, p=r.p, z_vn=r.z_vn, p_vn=r.p_vn,
                       null_sd_pct=100 * r.null_sd, mde80_onesided_pct=100 * 2.486 * r.null_sd,
                       symbols_pos=r.symbols_pos, n_coins_ge10=r.n_coins_ge10,
                       **{f"fwd_{c[:3]}_pct": 100 * r[f"fwd_{c}"] for c in L.COINS}))
F = pd.DataFrame(fr)
F.to_csv(os.path.join(O, "focus_cells_is_oos_final.csv"), index=False)
print("\nFocus cells:")
print(F[["split", "strategy", "tf", "H", "n", "long_share", "fwd_pct", "null_mean_pct", "timing_pct", "mu_star_pct", "z", "p", "z_vn", "p_vn",
         "mde80_onesided_pct", "symbols_pos", "n_coins_ge10"]].round(4).to_string())
