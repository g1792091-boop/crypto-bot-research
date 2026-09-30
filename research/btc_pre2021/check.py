"""BTC-only check of the best round-2 config on data never used for selection
(research/btc_pre2021/PREREG_BTC_PRE2021.md).

    python3 research/btc_pre2021/check.py

Config (unchanged from research/maker/): H3A_RETAIL_FADE, 1h bars, limit entry 0.25 ATR, stop 1.5 ATR,
target 3 ATR, 48-bar cap, maker entry/target, taker stop/time exit, same simulator.
"""

from __future__ import annotations

import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
for sub in ("research/search", "research/orderflow", "research/maker"):
    sys.path.insert(0, os.path.join(ROOT, sub))
warnings.filterwarnings("ignore")

import search as SR  # noqa: E402
import orderflow as OF  # noqa: E402
import maker as MK  # noqa: E402

START = pd.Timestamp("2020-10-01", tz="UTC")
END = pd.Timestamp("2021-08-01", tz="UTC")  # the earlier selection window starts here


def main() -> dict:
    L = SR.lib()
    import fg_indicators as fg
    df = pd.read_csv(os.path.join(ROOT, "data", "btc_pre2021", "btcusdt_1h.csv.gz"))
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df.attrs["tf"] = "1h"
    close_1h = pd.Series(df["close"].to_numpy(float), index=df["ts"] + pd.Timedelta("1h"))
    feats = OF.hourly_features("btc")
    sig = OF.to_chart(L, df, "1h", OF.hourly_conditions(feats, close_1h))["H3A_RETAIL_FADE"]
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = fg.atr(df, 14).to_numpy(float)
    start = int(np.searchsorted(df["ts"].values, START.to_datetime64()))
    end = int(np.searchsorted(df["ts"].values, END.to_datetime64())) - (MK.MAX_HOLD + MK.VALID_BARS)
    rows = MK.simulate(o, h, lo, c, atr, sig, 1.0, 0.25, 1.5, 3.0, start, end)
    t = pd.DataFrame(rows, columns=["signal_idx", "entry_idx", "exit_idx", "side", "net", "mae", "sl_dist", "reason"])
    ts = df["ts"].to_numpy()
    t["entry_ts"], t["exit_ts"], t["symbol"] = ts[t["entry_idx"]], ts[t["exit_idx"]], "BTCUSD"
    n_signals = int(np.abs(sig[start:end]).astype(bool).sum())
    out: dict = {"window": [str(START.date()), str(END.date())], "signals": n_signals, "trades": len(t)}
    if len(t):
        day = pd.to_datetime(t["entry_ts"], utc=True).dt.floor("D").to_numpy()
        m, p = SR.mean_test(t["net"].to_numpy(), day) if len(t) > 5 else (float(t["net"].mean()), float("nan"))
        wins, losses = t.loc[t["net"] > 0, "net"], t.loc[t["net"] <= 0, "net"]
        out.update({"mean_pct": 100 * m, "p_one_sided": p, "win_pct": 100 * float((t["net"] > 0).mean()),
                    "pf": float(wins.sum() / -losses.sum()) if len(losses) else None,
                    "sum_pct": 100 * float(t["net"].sum()), "long_share": float((t["side"] > 0).mean()),
                    "reasons": t["reason"].value_counts().to_dict(),
                    "by_month": {str(k): [int(v["size"]), round(100 * v["mean"], 3)] for k, v in
                                 t.groupby(pd.to_datetime(t["entry_ts"]).dt.to_period("M"))["net"].agg(["size", "mean"]).iterrows()},
                    "bh_hold_1x": float(np.prod(1 + t["net"])),
                    **{f"x20_{k}": v for k, v in SR.owners_book(t).items()}})
        # the same config's BTC-only numbers in the earlier windows, for comparison
        prev = os.path.join(os.environ.get("MAKER_TRADES", ""), "maker_trades.pkl")
        if os.path.exists(prev):
            pt = pd.read_pickle(prev)
            pt = pt[(pt["tf"] == "1h") & (pt["entry"] == "H3A_RETAIL_FADE") & (pt["exit"] == "X2_SL15_TP3@0.25")
                    & (pt["symbol"] == "BTCUSD")]
            for w, g in pt.groupby(np.where(pt["split"] == "is", "selection", "confirmation")):
                out[f"btc_{w}"] = {"trades": len(g), "mean_pct": 100 * float(g["net"].mean())}
    od = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(od, exist_ok=True)
    t.to_csv(os.path.join(od, "trades.csv"), index=False)
    with open(os.path.join(od, "result.json"), "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    main()
