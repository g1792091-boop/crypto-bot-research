#!/usr/bin/env python3
"""Synthetic coin-flip pool: a long AND a short entry at EVERY bar close of every coin and timeframe (15m / 30m / 1h /
4h) of the paper v4 run, each replayed alone through the repo's own paper engine with the house exits (2 ATR stop +
lock ladder), the run's leverage rule, fees and funding. This is what a coin-flip account would have earned at any
moment of the same 16 days, with thousands of trades instead of the 3 RANDOM accounts per timeframe.

    python3 randpool.py <extracted_dir> <base_dir> <out_csv> [--repo REPO] [--procs 4]

<extracted_dir>  the export extracted (run folders; only current/ is used)
<base_dir>       analyze.py output of the same export (only for nothing; kept for symmetry) -- may be '-'
<out_csv>        one row per synthetic entry

ATR: the bot's ATR is Wilder's RMA(14) of the timeframe's true range (fg_indicators.atr). It is rebuilt here from the
run's 1m bars, seeded with the first ATR the bot itself logged for that coin and timeframe (signal_log.atr) and then
carried forward with the same recursion. Every later logged ATR is used to check the rebuilt one (printed). Bars before
the seed are not used.

Reads the export and the repository only. Runs the repo's engine code (paperbot.*) and
analysis/rulebot_1007/scripts/analyze.py (the 10/07 replay helpers); never anything from the export.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO = "/home/user/crypto-bot-research"
MIN, HOUR = 60_000, 3_600_000
TF_MS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": HOUR, "4h": 4 * HOUR}


def load_analyze(repo: str):
    p = os.path.join(repo, "analysis", "rulebot_1007", "scripts", "analyze.py")
    spec = importlib.util.spec_from_file_location("rb_analyze_1007", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["rb_analyze_1007"] = m          # so worker functions pickle by name (fork pool)
    spec.loader.exec_module(m)
    return m


def tf_bars(b1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Complete timeframe bars from 1m bars (bins aligned to the epoch, as Binance)."""
    span = TF_MS[tf]
    b = b1.copy()
    b["bin"] = (b["ts"] // span) * span
    g = b.groupby("bin")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "n": g["ts"].size()})
    out = out[out["n"] == span // MIN].reset_index().rename(columns={"bin": "open_ts"})
    out["close_ts"] = out["open_ts"] + span
    return out


def rebuilt_atr(bars: pd.DataFrame, logged: pd.Series) -> tuple[np.ndarray, dict]:
    """ATR per bar (NaN before the seed). logged: {bar close ts: atr} from the bot."""
    h, lo, c = bars["high"].to_numpy(float), bars["low"].to_numpy(float), bars["close"].to_numpy(float)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    atr = np.full(len(bars), np.nan)
    closes = bars["close_ts"].to_numpy(np.int64)
    idx = {int(t): i for i, t in enumerate(closes)}
    seeds = [idx[int(t)] for t in logged.index if int(t) in idx]
    info = {"seed": None, "checked": 0, "med_rel_err": np.nan, "p95_rel_err": np.nan}
    if not seeds:
        return atr, info
    s = min(seeds)
    atr[s] = float(logged.loc[closes[s]])
    for i in range(s + 1, len(bars)):
        atr[i] = (atr[i - 1] * 13.0 + tr[i]) / 14.0
    chk = [(abs(atr[idx[int(t)]] / v - 1)) for t, v in logged.items() if int(t) in idx and idx[int(t)] > s]
    if chk:
        info.update(seed=int(closes[s]), checked=len(chk), med_rel_err=float(np.median(chk)),
                    p95_rel_err=float(np.percentile(chk, 95)))
    return atr, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("extracted_dir")
    ap.add_argument("base_dir")
    ap.add_argument("out_csv")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args(argv)
    sys.path.insert(0, a.repo)
    AZ = load_analyze(a.repo)
    t0 = time.time()
    run = AZ.Run(a.extracted_dir, "current")
    bars = run.bars.sort_values(["ts", "symbol"])
    sig = run.sig
    taker = AZ.implied_taker(run)
    settings = AZ.replay_settings("quality_v1", taker)
    brackets, _ = AZ.make_brackets(None)
    specs = AZ.infer_specs(run.trades)
    rates, finfo = AZ.infer_funding(run.trades, run.bars)
    ts_list, ssteps = AZ.build_steps(run.bars, rates)
    last_ts = ts_list[-1]
    syms = sorted(bars["symbol"].unique())
    sigs, checks = [], []
    k = 0
    opens = {s: g.set_index("ts")["open"] for s, g in bars.groupby("symbol")}
    for tf in TF_MS:
        lg = sig[(sig["timeframe"] == tf) & sig["atr"].notna()].groupby(["symbol", "bar_close"])["atr"].first()
        for s in syms:
            if s not in brackets:
                continue
            tb = tf_bars(bars[bars["symbol"] == s][["ts", "open", "high", "low", "close"]], tf)
            logged = lg.loc[s] if s in lg.index.get_level_values(0) else pd.Series(dtype=float)
            atr, info = rebuilt_atr(tb, logged)
            info.update(tf=tf, symbol=s, bars=len(tb))
            checks.append(info)
            op = opens[s]
            for B, v in zip(tb["close_ts"].to_numpy(np.int64), atr):
                if not (v == v and v > 0) or B >= last_ts - TF_MS[tf]:
                    continue
                ref = op.get(int(B))
                if ref is None or ref != ref:
                    continue
                for side in (1, -1):
                    sigs.append({"sig_id": k, "bar_close": int(B), "timeframe": tf, "strategy": "SYNTH",
                                 "symbol": s, "side": side, "atr": float(v), "ref_price": float(ref),
                                 "ref_time": int(B) + 10_000, "delay_ms": 10_000})
                    k += 1
    C = pd.DataFrame(checks)
    print("ATR rebuild check (relative error vs the bot's logged ATR after the seed):")
    print(C.groupby("tf")[["checked", "med_rel_err", "p95_rel_err"]].agg({"checked": "sum", "med_rel_err": "median",
                                                                           "p95_rel_err": "max"}).to_string())
    AZ._G.clear()
    AZ._G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, settings=settings, brackets=brackets, specs=specs,
                 flip=False)
    idx = list(range(len(sigs)))
    if a.procs > 1:
        import multiprocessing as mp
        chunks = [idx[j::a.procs * 4] for j in range(a.procs * 4)]
        with mp.get_context("fork").Pool(a.procs) as pool:
            parts = pool.map(AZ._replay_chunk, chunks)
        res = [x for p in parts for x in p]
    else:
        res = AZ._replay_chunk(idx)
    R = pd.DataFrame(res).sort_values("sig_id")
    tr = R["status"] == "TRADED"
    risk = R["qty"] * (R["entry_price"] - R["stop_initial"]).abs()
    R["gross_R"] = np.where(tr, (R["pnl"] + R["fees"] + R["funding"]) / risk, np.nan)
    R["cost_R"] = np.where(tr, (R["fees"] + R["funding"]) / risk, np.nan)
    keep = ["sig_id", "bar_close", "timeframe", "symbol", "side", "atr", "ref_price", "status", "entry_time",
            "exit_time", "exit_reason", "leverage", "roe", "pnl", "fees", "funding", "R", "gross_R", "cost_R",
            "stop_frac", "hold_min", "margin"]
    R = R[[c for c in keep if c in R.columns]]
    os.makedirs(os.path.dirname(os.path.abspath(a.out_csv)), exist_ok=True)
    R.to_csv(a.out_csv, index=False)
    C.to_csv(os.path.splitext(a.out_csv)[0] + "_atrcheck.csv", index=False)
    print(f"synthetic entries {len(R)}: " + " ".join(f"{k}:{v}" for k, v in R["status"].value_counts().items()))
    print(R[tr].groupby(["timeframe", "side"])["R"].agg(["size", "mean"]).round(4).to_string())
    print(f"done in {time.time() - t0:.1f}s -> {a.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
