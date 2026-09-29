"""Attach entry/exit timestamps and MAE/MFE to Gap-1's Option-B trade vectors (IS 618, OOS 1936).

Index convention (gap_1/work/prereg_b.py): i = signal bar, fill_j = maker fill bar, exit_j = exit bar,
all row indices of run.load_csv(<sym>-5m-ohlcv.csv). MAE is taken over bars fill_j..exit_j INCLUSIVE
(same convention as engine.py:122-124, i.e. conservative: includes the fill bar's pre-fill part and the
exit bar's post-fill part). MAE_ex excludes the exit bar (sensitivity)."""
import os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bt"))
from run import load_csv  # noqa: E402

G1 = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/gap_1"
SETS = {"B_IS": (f"{G1}/out/IS_validation_primary_trades.csv", f"{G1}/data_is"),
        "B_OOS": (f"{G1}/out/OOS_primary_primary_trades.csv", f"{G1}/data_oos")}
OUT = os.path.join(HERE, "..", "out")

for name, (tf, dd) in SETS.items():
    T = pd.read_csv(tf)
    rows = []
    maxdev = 0.0
    for sym, g in T.groupby("symbol"):
        d = load_csv(os.path.join(dd, f"{sym.lower()}-5m-ohlcv.csv"), 5)
        o, h, l, c = (d[x].to_numpy(float) for x in ("open", "high", "low", "close"))
        ts = d["ts"].to_numpy()
        for r in g.itertuples(index=False):
            # consistency: fill price must be min(o[fj], c[i]) (long) / max(o[fj], c[i]) (short)
            exp_fill = min(o[r.fill_j], c[r.i]) if r.side > 0 else max(o[r.fill_j], c[r.i])
            maxdev = max(maxdev, abs(exp_fill / r.fill_px - 1))
            a, b = r.fill_j, r.exit_j
            if r.side > 0:
                mae = l[a:b + 1].min() / r.fill_px - 1; mae_ex = l[a:b].min() / r.fill_px - 1
                mfe = h[a:b + 1].max() / r.fill_px - 1
            else:
                mae = -(h[a:b + 1].max() / r.fill_px - 1); mae_ex = -(h[a:b].max() / r.fill_px - 1)
                mfe = -(l[a:b + 1].min() / r.fill_px - 1)
            rows.append(dict(r._asdict(), entry_ts=pd.Timestamp(ts[a]), exit_ts=pd.Timestamp(ts[b]),
                             mae=mae, mae_ex=mae_ex, mfe=mfe, hold=b - a + 1))
    X = pd.DataFrame(rows).sort_values(["entry_ts", "symbol"]).reset_index(drop=True)
    X["entry_ts"] = pd.to_datetime(X["entry_ts"], utc=True); X["exit_ts"] = pd.to_datetime(X["exit_ts"], utc=True)
    X["strategy"] = name; X["exit"] = "maker64_nostop"; X["reason"] = "TIME"; X["sl_dist"] = np.inf
    X.to_csv(os.path.join(OUT, f"{name}_ledger.csv"), index=False)
    print(f"{name}: n={len(X)} mean net={X.net.mean()*100:+.4f}% sd={X.net.std()*100:.3f}% "
          f"fill-price max rel dev={maxdev:.2e}  span {X.entry_ts.min()} .. {X.exit_ts.max()}  "
          f"MAE<=-1.5%: {(X.mae <= -0.015).mean()*100:.1f}%  (excl. exit bar {(X.mae_ex <= -0.015).mean()*100:.1f}%)")
