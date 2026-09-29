"""Grid runner: strategies x exit configs x symbols on one window (IS or OOS)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

import fg_indicators as fg
import strategies as S
from engine import CostCfg, ExitCfg, default_exit_configs, run_backtest, summarize

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
OUT = os.path.join(os.path.dirname(HERE), "results")
SPLIT = pd.Timestamp("2026-05-08T00:00:00Z")


def load_csv(path: str, bar_minutes: int) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    ts_col = cols.get("timestamp", cols.get("t", list(df.columns)[0]))
    df = df.rename(columns={ts_col: "ts", cols.get("open", "open"): "open", cols.get("high", "high"): "high",
                            cols.get("low", "low"): "low", cols.get("close", "close"): "close",
                            cols.get("volume", "volume"): "volume"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    # gap report
    d = df["ts"].diff().dt.total_seconds().div(60).fillna(bar_minutes)
    gaps = int((d != bar_minutes).sum() - 0)
    df.attrs["gaps"] = gaps
    df.attrs["gap_minutes_max"] = float(d.max())
    df["open_time"] = (df["ts"].astype("int64") // 10**6)
    return df


def synth(n=40000, seed=7, bar_minutes=15):
    rng = np.random.default_rng(seed)
    close = 60000 * np.exp(np.cumsum(rng.normal(0, 0.0025, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.0015, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0015, n)))
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.0003, n))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    vol = rng.uniform(10, 300, n)
    ts = pd.date_range("2025-08-07T09:45:00Z", periods=n, freq=f"{bar_minutes}min")
    df = pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": vol})
    df["open_time"] = (df["ts"].astype("int64") // 10**6)
    return df


def window_bounds(df: pd.DataFrame, window: str):
    ts_ns = df["ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    split_idx = int(np.searchsorted(ts_ns, np.datetime64(SPLIT.tz_convert("UTC").tz_localize(None))))
    if window == "IS":
        return 0, split_idx
    if window == "OOS":
        return split_idx, len(df)
    return 0, len(df)


def run_symbol(sym: str, df: pd.DataFrame, strategies: dict, cfgs, cost: CostCfg, window: str, save_trades: bool):
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    lo, hi = window_bounds(df, window)
    rows = []
    trade_frames = []
    for sname, fn in strategies.items():
        t0 = time.time()
        try:
            long_sig, short_sig = fn(df)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{sym}] {sname}: signal error {exc!r}", file=sys.stderr)
            continue
        long_sig = np.asarray(long_sig, dtype=bool)
        short_sig = np.asarray(short_sig, dtype=bool)
        both = long_sig & short_sig
        short_sig = short_sig & ~both
        n_sig = int((long_sig | short_sig)[max(lo, cost.warmup):hi].sum())
        for cfg in cfgs:
            trades = run_backtest(df, atr, long_sig, short_sig, cfg, cost, lo, hi)
            summ = summarize(trades)
            summ.update(dict(symbol=sym, strategy=sname, exit=cfg.name, window=window, signals=n_sig))
            rows.append(summ)
            if save_trades and len(trades):
                t = trades.copy()
                t["symbol"] = sym; t["strategy"] = sname; t["exit"] = cfg.name; t["window"] = window
                t["entry_ts"] = df["ts"].to_numpy()[t["entry_idx"].to_numpy()]
                t["exit_ts"] = df["ts"].to_numpy()[t["exit_idx"].to_numpy()]
                trade_frames.append(t)
        print(f"  [{sym}] {sname:16s} signals={n_sig:5d}  ({time.time() - t0:.1f}s)", flush=True)
    return rows, trade_frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="IS", choices=["IS", "OOS", "ALL"])
    ap.add_argument("--symbols", default="BTCUSD,ETHUSD,SOLUSD,LTCUSD,BCHUSD")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--strategies", default="ALL")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    bar_minutes = int(args.tf.rstrip("m"))
    cost = CostCfg(fee_side=args.fee, bar_minutes=bar_minutes)
    cfgs = default_exit_configs()
    all_rows, all_trades = [], []
    for sym in args.symbols.split(","):
        if args.synthetic:
            df = synth()
        else:
            path = os.path.join(DATA, f"{sym.lower()}-{args.tf}-ohlcv.csv")
            if not os.path.exists(path):
                print(f"missing {path}", file=sys.stderr)
                continue
            df = load_csv(path, bar_minutes)
            print(f"{sym}: {len(df)} bars {df['ts'].iloc[0]} -> {df['ts'].iloc[-1]}  gaps={df.attrs['gaps']} maxgap={df.attrs['gap_minutes_max']:.0f}min")
        if args.tf == "5m":
            # V4.5 needs the confirmed 15m frame as well
            p15 = os.path.join(DATA, f"{sym.lower()}-15m-ohlcv.csv")
            df15 = load_csv(p15, 15)
            strategies = {
                "V45_EXACT_AMB": (lambda d, d15=df15: S.v45_exact_amb(d, d15)),
                "V45_ANY": (lambda d, d15=df15: S.v45_any(d, d15)),
                "V45_EXACT_AMB_G1": (lambda d, d15=df15: S.v45_exact_amb_g1(d, d15)),
            }
            if args.strategies != "ALL":
                strategies.update({k: S.CANDIDATES_15M[k] for k in args.strategies.split(",") if k in S.CANDIDATES_15M})
            cost.max_hold = 3000
        else:
            strategies = S.CANDIDATES_15M if args.strategies == "ALL" else {k: S.CANDIDATES_15M[k] for k in args.strategies.split(",")}
        rows, tf = run_symbol(sym, df, strategies, cfgs, cost, args.window, save_trades=True)
        all_rows += rows
        all_trades += tf
    res = pd.DataFrame(all_rows)
    tag = f"_{args.tag}" if args.tag else ""
    res.to_csv(os.path.join(OUT, f"summary_{args.window}_{args.tf}{tag}.csv"), index=False)
    if all_trades:
        pd.concat(all_trades).to_csv(os.path.join(OUT, f"trades_{args.window}_{args.tf}{tag}.csv"), index=False)
    print("saved", len(res), "rows")


if __name__ == "__main__":
    main()
