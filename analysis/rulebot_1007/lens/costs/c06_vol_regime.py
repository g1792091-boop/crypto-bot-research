#!/usr/bin/env python3
"""How quiet is the live market? The 2 ATR house stop as % of price over five years vs now.

    python3 -I c06_vol_regime.py <signals_dir with sig_15m_<COIN>USD.npz> <c04_replay_rows_rb.csv> <out_dir>

The npz cache (15m bars + ATR14 + the 36 strategies' signals, 2021-05..2026-09) is read with allow_pickle=False.
15m: the cache's own ATR. 30m / 1h / 4h: 15m bars resampled, ATR14 as Wilder's RMA of the true range.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

PAPER_RT_BPS = 14.0


def rma_atr(df, n=14):
    pc = df["c"].shift(1)
    tr = pd.concat([df["h"] - df["l"], (df["h"] - pc).abs(), (df["l"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def main():
    sdir, rows_csv, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    recs = []
    sig_recs = []
    for f in sorted(glob.glob(os.path.join(sdir, "sig_15m_*USD.npz"))):
        coin = os.path.basename(f).split("_")[2].replace(".npz", "")
        z = np.load(f, allow_pickle=False)
        df = pd.DataFrame({"ts": pd.to_datetime(z["ts"]), "o": z["o"], "h": z["h"], "l": z["l"], "c": z["c"],
                           "atr": z["atr"]}).set_index("ts")
        anysig = np.zeros(len(df), bool)
        for k in z.files:
            if k.startswith("s__"):
                anysig |= z[k] != 0
        df["anysig"] = anysig
        for tf, rule in (("15m", None), ("30m", "30min"), ("1h", "1h"), ("4h", "4h")):
            if rule is None:
                d = df.copy()
                d["stop_pct"] = 2 * d["atr"] / d["c"] * 100
            else:
                d = df.resample(rule, label="left", closed="left").agg({"o": "first", "h": "max", "l": "min",
                                                                         "c": "last", "anysig": "max"}).dropna()
                d["stop_pct"] = 2 * rma_atr(d) / d["c"] * 100
            d = d.dropna(subset=["stop_pct"])
            d["anysig"] = d["anysig"].astype(float).fillna(0).astype(bool)
            d["coin"], d["tf"] = coin, tf
            d["year"] = d.index.year
            d["ym"] = d.index.strftime("%Y-%m")
            recs.append(d[["coin", "tf", "year", "ym", "stop_pct", "anysig"]])
    A = pd.concat(recs)
    q = A.groupby(["tf", "coin"])["stop_pct"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).unstack()
    q.columns = [f"q{int(c * 100)}" for c in q.columns]
    q["sig_bar_median"] = A[A["anysig"]].groupby(["tf", "coin"])["stop_pct"].median()
    qa = A.groupby("tf")["stop_pct"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).unstack()
    qa.columns = [f"q{int(c * 100)}" for c in qa.columns]
    qa["sig_bar_median"] = A[A["anysig"]].groupby("tf")["stop_pct"].median()
    qa["coin"] = "ALL"
    yr = A.groupby(["tf", "year"])["stop_pct"].median().unstack()
    last = A[A["ym"] >= "2026-08"].groupby(["tf"])["stop_pct"].median()

    # live (replay base rows, every signal v3b + v4): median stop % per tf x coin, and its 5-year percentile
    R = pd.read_csv(rows_csv, usecols=["run", "scenario", "grp", "timeframe", "symbol", "stop_frac_own", "status"])
    R = R[(R["scenario"] == "base") & (R["status"] == "TRADED") & R["grp"].isin(["core36", "ds200"])]
    R["coin"] = R["symbol"].str.replace("USDT", "USD")
    live = R.groupby(["timeframe", "coin"])["stop_frac_own"].median() * 100
    live_all = R.groupby("timeframe")["stop_frac_own"].median() * 100
    rows = []
    for (tf, coin), v in live.items():
        x = A[(A["tf"] == tf) & (A["coin"] == coin)]["stop_pct"].to_numpy()
        sig = A[(A["tf"] == tf) & (A["coin"] == coin) & A["anysig"]]["stop_pct"].to_numpy()
        rows.append({"tf": tf, "coin": coin, "live_median_stop_pct": v,
                     "fiveyear_median_stop_pct": float(np.median(x)) if len(x) else np.nan,
                     "fiveyear_sigbar_median_stop_pct": float(np.median(sig)) if len(sig) else np.nan,
                     "live_percentile_in_5y": float((x < v).mean() * 100) if len(x) else np.nan,
                     "paper_cost_R_live": PAPER_RT_BPS / (v * 100),
                     "paper_cost_R_5y_median": PAPER_RT_BPS / (np.median(x) * 100) if len(x) else np.nan})
    for tf, v in live_all.items():
        x = A[A["tf"] == tf]["stop_pct"].to_numpy()
        rows.append({"tf": tf, "coin": "ALL", "live_median_stop_pct": v, "fiveyear_median_stop_pct": float(np.median(x)),
                     "fiveyear_sigbar_median_stop_pct": float(np.median(A[(A["tf"] == tf) & A["anysig"]]["stop_pct"])),
                     "live_percentile_in_5y": float((x < v).mean() * 100),
                     "paper_cost_R_live": PAPER_RT_BPS / (v * 100),
                     "paper_cost_R_5y_median": PAPER_RT_BPS / (np.median(x) * 100)})
    L = pd.DataFrame(rows)
    L.to_csv(os.path.join(out, "c06_live_vs_5y_stop.csv"), index=False)
    pd.concat([q.reset_index(), qa.reset_index()]).to_csv(os.path.join(out, "c06_5y_stop_quantiles.csv"), index=False)
    yr.to_csv(os.path.join(out, "c06_5y_stop_median_by_year.csv"))
    # share of 5-year bars (all coins) where paper cost <= 0.10R / 0.15R, i.e. stop >= 1.4% / 0.93%
    share = A.groupby("tf")["stop_pct"].agg(share_cost_le_010R=lambda s: (s >= 1.4).mean(),
                                            share_cost_le_015R=lambda s: (s >= 14 / 15).mean())
    share.to_csv(os.path.join(out, "c06_share_cheap_regime.csv"))
    pd.set_option("display.width", 250)
    print(pd.concat([q.reset_index(), qa.reset_index()]).round(3).to_string(index=False))
    print(yr.round(3))
    print("last 2 months median", last.round(3).to_dict())
    print(L.round(3).to_string(index=False))
    print(share.round(3))


if __name__ == "__main__":
    main()
