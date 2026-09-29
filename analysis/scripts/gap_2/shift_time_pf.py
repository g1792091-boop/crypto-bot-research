"""Circular-shift null for the TIME64 exit PF / net of specific real strategies (post-hoc check).
Shift each symbol's signal train (sides kept) by a common random offset inside the stage-1 window,
re-run the unchanged engine with TIME64, apply the unchanged rule."""
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, "bt")
import fg_indicators as fg, strategies as S
from engine import CostCfg, ExitCfg, run_backtest
from run import load_csv, window_bounds
from analyze import pooled, apply_rule
B = 200
cfg = ExitCfg(name="TIME64", mode="FIXED", sl_atr=1e4, tp_atr=1e4)
def load(tf, sym):
    df = load_csv(f"data/{sym.lower()}-{tf}-ohlcv.csv", int(tf[:-1])); return df
jobs = [("15m", "S6_EMA_DMI_ADX", ("BTCUSD","ETHUSD","SOLUSD","LTCUSD","BCHUSD")),
        ("15m", "N03_ADX_GC", ("BTCUSD","ETHUSD","SOLUSD","LTCUSD","BCHUSD")),
        ("5m", "V45_EXACT_AMB", ("BTCUSD","ETHUSD","SOLUSD"))]
rng = np.random.default_rng(7)
out = []
for tf, name, syms in jobs:
    data = []
    for s in syms:
        df = load(tf, s)
        if tf == "15m":
            lo, hi = window_bounds(df, "IS"); l, sh = S.CANDIDATES_15M[name](df)
        else:
            lo, hi = 0, len(df); l, sh = S.v45_exact_amb(df, load("15m", s))
        l = np.asarray(l, bool); sh = np.asarray(sh, bool) & ~l
        data.append((s, df, fg.atr(df, 14).to_numpy(float), l, sh, lo, hi))
    res = []
    for b in range(B + 1):
        tr = []
        for s, df, atr, l, sh, lo, hi in data:
            lo_e = max(lo, 1000); L = hi - lo_e
            if b == 0:
                L2, S2 = l, sh
            else:
                u = int(rng.integers(300, L - 300))
                L2 = l.copy(); S2 = sh.copy()
                L2[lo_e:hi] = np.roll(l[lo_e:hi], u); S2[lo_e:hi] = np.roll(sh[lo_e:hi], u)
            t = run_backtest(df, atr, L2, S2, cfg, CostCfg(bar_minutes=int(tf[:-1]), max_hold=64), lo, hi)
            if len(t):
                t = t.copy(); t["symbol"] = s; t["strategy"] = name; t["exit"] = "TIME64"
                t["entry_ts"] = df["ts"].to_numpy()[t["entry_idx"].to_numpy()]; tr.append(t)
        P = apply_rule(pooled(pd.concat(tr))).iloc[0]
        res.append((P.pf, P.exp_net_pct, P.trades, bool(P["pass"])))
    res = np.array(res, dtype=object)
    pf = res[:, 0].astype(float); net = res[:, 1].astype(float); ps = res[1:, 3].astype(bool)
    r = dict(tf=tf, strategy=name, obs_pf=pf[0], obs_net=net[0], obs_trades=int(res[0, 2]),
             null_pf_mean=pf[1:].mean(), null_pf_sd=pf[1:].std(ddof=1), p_pf=(1 + (pf[1:] >= pf[0]).sum()) / (B + 1),
             null_net_mean=net[1:].mean(), null_net_sd=net[1:].std(ddof=1), p_net=(1 + (net[1:] >= net[0]).sum()) / (B + 1),
             null_pass_rate=ps.mean(), null_pf_q95=np.quantile(pf[1:], 0.95))
    print(r, flush=True); out.append(r)
pd.DataFrame(out).to_csv("out/shift_time_pf.csv", index=False)
