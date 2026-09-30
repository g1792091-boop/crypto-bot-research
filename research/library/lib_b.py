"""Library round B: the same 80 entries, 5 exits and three-window gauntlet on 5m and 30m bars
(research/library/PREREG_LIBRARY_B.md).

    SWEEP_DATA=<rebuilt sweep data> python3 research/library/lib_b.py run <scratch_dir>

Holdout (2020-01..2021-07): 5m from data/pre2021/*-5m*.csv.gz, 30m resampled from the 15m files with the
backtest session's resample_ohlcv. Signals are computed once per coin and window; trades are evaluated
one exit at a time to keep memory bounded.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

import lib as LB  # noqa: E402

TFS_B = ("5m", "30m")


def pre_panel_b(L, tf: str) -> dict[str, pd.DataFrame]:
    out = {}
    for coin, stem in LB.PRE_COINS.items():
        if tf == "5m":
            files = sorted(glob.glob(os.path.join(LB.ROOT, "data", "pre2021", f"{stem}-5m*.csv.gz")))
            if not files:
                continue
            d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
        else:
            p = os.path.join(LB.ROOT, "data", "pre2021", f"{stem}-15m.csv.gz")
            if not os.path.exists(p):
                continue
            d = L.resample_ohlcv(pd.read_csv(p), tf)
        d["ts"] = pd.to_datetime(d["ts"], utc=True)
        d = d.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
        d = d[d["ts"] < LB.PRE[1] + pd.Timedelta(days=10)].reset_index(drop=True)
        d.attrs["tf"] = tf
        out[coin] = d[["ts", "open", "high", "low", "close", "volume"]]
    return out


def run(scratch: str) -> None:
    L = LB.SR.lib()
    import fg_indicators as fg
    import pine_indicators as pi
    os.makedirs(scratch, exist_ok=True)
    exits = [(name, L.ExitCfg(name=name, mode=mode, sl_atr=sl, tp_atr=tp if tp else 1e4, trail_atr=tr), LB.MAX_HOLD)
             for name, mode, sl, tp, tr in LB.EXITS]
    rows = []
    for tf in TFS_B:
        cache = []
        for split in ("is", "oos", "final", "pre"):
            t0 = time.time()
            panel = pre_panel_b(L, tf) if split == "pre" else L.load_panel(tf, split)
            for coin, df in panel.items():
                df.attrs["tf"] = tf
                lo_, hi_ = LB.pre_window(L, df, tf) if split == "pre" else L.signal_window(df, tf, split, LB.MAX_HOLD)
                if hi_ <= lo_:
                    continue
                atr = fg.atr(df, 14).to_numpy(float)
                ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy()
                cache.append((split, coin, df, atr, ts, lo_, hi_, LB.entries(df, fg, pi)))
            print(f"{tf} {split}: signals {time.time() - t0:.0f}s", flush=True)
        for xname, cfg, mh in exits:
            t0 = time.time()
            parts = []
            for split, coin, df, atr, ts, lo_, hi_, ent in cache:
                for ename, (lg, sh) in ent.items():
                    t = L.run_backtest(df, atr, lg, sh, cfg, L._cost(tf, mh), lo_, hi_)
                    if len(t):
                        parts.append(pd.DataFrame({
                            "net": t["net"].to_numpy(np.float64), "mae": t["mae"].to_numpy(np.float32),
                            "sl_dist": t["sl_dist"].to_numpy(np.float32),
                            "entry_ts": ts[t["entry_idx"].to_numpy(int)], "exit_ts": ts[t["exit_idx"].to_numpy(int)],
                            "symbol": coin, "entry": ename, "exit": xname, "split": split}))
            tt = pd.concat(parts, ignore_index=True)
            del parts
            for col in ("symbol", "entry", "exit", "split"):
                tt[col] = tt[col].astype("category")
            tt["tf"] = pd.Categorical([tf] * len(tt))
            rows.extend(LB.config_rows(tt))
            print(f"{tf} {xname}: {len(tt)} trades, {len(rows)} configs so far, {time.time() - t0:.0f}s", flush=True)
            del tt
        del cache
    res = LB.select(pd.DataFrame(rows))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_b")
    os.makedirs(out, exist_ok=True)
    res.to_csv(os.path.join(out, "results.csv"), index=False)
    summary = {"configs": len(res), "stage1": int(res["stage1"].sum()), "stage1_top": int(res["stage1_top"].sum()),
               "stage2": int(res["stage2"].sum()), "stage3": int(res["stage3"].sum()),
               "candidate_20x": int(res["candidate_20x"].sum())}
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    pd.set_option("display.width", 280)
    cols = ["tf", "entry", "exit", "is_n", "is_win_pct", "is_rr", "is_mean_pct", "is_p", "is_coins_pos", "cf_n",
            "cf_mean_pct", "cf_pf", "cf_p", "cf_coins_pos", "pre_n", "pre_mean_pct", "pre_pf", "pre_p", "pre_coins_pos",
            "max_lev", "stage2", "stage3", "candidate_20x"]
    print(res[res["stage1_top"]].sort_values("is_p")[cols].round(4).to_string())
    print(json.dumps(summary))


if __name__ == "__main__":
    run(sys.argv[2])
