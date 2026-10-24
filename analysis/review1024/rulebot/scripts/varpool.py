#!/usr/bin/env python3
"""Every nightly-shadow exit / leverage variant (docs/observation-shadows*.md, paperbot/obsshadows.py) applied to a
list of signals, each signal alone on a fresh $5,000 account through the repo's own engine and the run's 1m bars.

    python3 varpool.py <extracted_dir> <signals_csv> <synth|real> <out_csv> [--repo REPO] [--procs 4]

synth: <signals_csv> = randpool.csv (a long and a short entry at every bar close): the coin-flip pool per variant,
       the luck baseline for the shadow variants.
real:  <signals_csv> = analyze.py's replay_signals.csv: every SUBMITTED signal of the current run (house exits only;
       the reel and the 5m coin flips have their own exits and are left out), with the leverage group the live
       account used (the replay's tier). This judges each strategy x variant on EVERY signal, not only the trades a
       one-position account took.

Variants, exactly as obsshadows.trade_shadows builds them: base, lock15 / lock20 / lock30 (first lock), timestop
(N bars without a lock), lev10 / lev20 (20% margin), lev30 / lev40 / lev50 (30 / 40 / 40% margin), stopw1.5 /
stopw2.5 / stopw3 (k ATR stop at the base trade's leverage), tp1R / tp1.5R / tp2R / tp3R (fixed take-profit, no
ladder), ladder_cap2R (ladder + 2R), lev20m20 .. lev50m50 (margin = leverage %). 'quality' needs the signal's
recorded strength and is not rebuilt here (it is read from d3_shadows.csv for the real trades only).

pnl_equity = ROE x the variant's margin share (obsshadows.pnl_equity) = net P&L / the fresh $5,000 wallet.
Reads the export and the repository only; runs the repo's engine code, never anything from the export.
"""
from __future__ import annotations

import argparse
import bisect
import importlib.util
import os
import sys
import time

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO = "/home/user/crypto-bot-research"
_G: dict = {}


def load_analyze(repo: str):
    p = os.path.join(repo, "analysis", "rulebot_1007", "scripts", "analyze.py")
    spec = importlib.util.spec_from_file_location("rb_analyze_1007", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["rb_analyze_1007"] = m
    spec.loader.exec_module(m)
    return m


def _one(d: dict) -> list[dict]:
    from dataclasses import replace
    from paperbot import obsshadows as OS
    from paperbot.daily3 import make_signal
    G = _G
    sym = d["symbol"]
    ss = G["ssteps"].get(sym)
    if ss is None or sym not in G["brackets"]:
        return []
    i0 = bisect.bisect_left(G["ts_list"], d["bar_close"])
    if i0 >= len(G["ts_list"]) or G["ts_list"][i0] - d["bar_close"] > 5 * 60_000:
        return []
    vs, vf, br, sp = G["vs"], G["vf"], G["brackets"], G["specs"]
    sig = make_signal(d)
    out = []

    def row(v, tr, resolved, extra=None):
        r = {"sig_id": d["sig_id"], "variant": v}
        if tr is not None:
            dist = abs(tr.entry_price - tr.stop_initial) if tr.stop_initial else np.nan
            r.update(status="DONE", roe=tr.roe, leverage=tr.leverage, exit_reason=tr.exit_reason,
                     pnl_equity=OS.pnl_equity(tr.roe, tr.leverage, (extra or vf[v])),
                     R=tr.pnl / (tr.qty * dist) if dist else np.nan, exit_time=tr.exit_time,
                     hold_min=(tr.exit_time - tr.entry_time) / 60_000)
        else:
            r["status"] = "NOENTRY" if resolved else "OPEN"
        out.append(r)
        return tr

    base_lev = None
    for v in OS.VARIANTS:
        tstop = None
        if v == "timestop":
            n = OS.TIME_STOP_BARS.get(d["timeframe"])
            if n is None:
                continue
            tstop = n * OS.TF_MS[d["timeframe"]]
        tr, res = OS.run_alone(vs[v], br, sp, sig, ss, i0, time_stop_ms=tstop)
        row(v, tr, res)
        if v == "base" and tr is not None:
            base_lev = int(round(float(tr.leverage)))
    for v in OS.FIXED_LEVERAGE3:
        tr, res = OS.run_alone(vs[v], br, sp, sig, ss, i0)
        row(v, tr, res)
    if base_lev in vf["base"]:
        for v, k in OS.STOP_WIDTHS.items():
            pol = OS.SameLeveragePolicy(vs[v], base_lev)
            tr, res = OS.run_alone(vs[v], br, sp, make_signal(d, stop_atr=k), ss, i0, policy=pol)
            row(v, tr, res)
        for v in OS.TP_VARIANTS:
            pol = (OS.SameLeveragePolicy if v in OS.TP_LADDER else OS.NoTakeProfitPolicy)(vs[v], base_lev)
            tr, res, _ = OS.run_alone_tp(vs[v], br, sp, sig, ss, i0, OS.TP_R[v], policy=pol)
            row(v, tr, res, vf["base"])
    msig = sig if sig.tier == "best" else replace(sig, tier="best")
    for v in OS.MARGIN_LEVERAGE4:
        tr, res = OS.run_alone(vs[v], br, sp, msig, ss, i0)
        row(v, tr, res)
    return out


def _chunk(idx: list[int]) -> list[dict]:
    res = []
    for i in idx:
        res.extend(_one(_G["sigs"][i]))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("extracted_dir")
    ap.add_argument("signals_csv")
    ap.add_argument("mode", choices=["synth", "real"])
    ap.add_argument("out_csv")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args(argv)
    sys.path.insert(0, a.repo)
    from paperbot import obsshadows as OS
    AZ = load_analyze(a.repo)
    t0 = time.time()
    run = AZ.Run(a.extracted_dir, "current")
    taker = AZ.implied_taker(run)
    settings = AZ.replay_settings("quality_v1", taker)
    brackets, _ = AZ.make_brackets(None)
    specs = AZ.infer_specs(run.trades)
    rates, _ = AZ.infer_funding(run.trades, run.bars)
    ts_list, ssteps = AZ.build_steps(run.bars, rates)
    names = list(OS.VARIANTS) + list(OS.VARIANTS3) + list(OS.VARIANTS4)
    vs = {v: OS.variant_settings(settings, v) for v in names}
    vf = {v: OS.rule_margin_fracs(x) for v, x in vs.items()}
    S = pd.read_csv(a.signals_csv, low_memory=False)
    sigs = []
    if a.mode == "synth":
        S = S[S["status"] == "TRADED"]
        for r in S.itertuples(index=False):
            sigs.append({"sig_id": int(r.sig_id), "bar_close": int(r.bar_close), "timeframe": r.timeframe,
                         "strategy": "SYNTH", "symbol": r.symbol, "side": int(r.side), "atr": float(r.atr),
                         "ref_price": float(r.ref_price), "ref_time": int(r.bar_close) + 10_000, "delay_ms": 10_000})
    else:
        S = S[(S["run"] == "current") & (S["status"] == "TRADED") & ~S["kind"].isin(["reel"])
              & (S["timeframe"] != "5m")]
        for r in S.itertuples(index=False):
            d = {"sig_id": int(r.sig_id), "bar_close": int(r.bar_close), "timeframe": r.timeframe,
                 "strategy": r.strategy, "symbol": r.symbol, "side": int(r.side), "atr": float(r.atr),
                 "ref_price": float(r.ref_price), "ref_time": int(r.bar_close) + 10_000, "delay_ms": 10_000}
            if isinstance(r.tier, str) and r.tier in ("best", "normal"):
                d["data"] = {"lev_group": r.tier}
            sigs.append(d)
    _G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, brackets=brackets, specs=specs, vs=vs, vf=vf)
    idx = list(range(len(sigs)))
    print(f"{len(sigs)} signals x {len(names)} variants ...", flush=True)
    if a.procs > 1:
        import multiprocessing as mp
        chunks = [idx[j::a.procs * 8] for j in range(a.procs * 8)]
        with mp.get_context("fork").Pool(a.procs) as pool:
            parts = pool.map(_chunk, chunks)
        res = [x for p in parts for x in p]
    else:
        res = _chunk(idx)
    R = pd.DataFrame(res)
    R.to_csv(a.out_csv, index=False)
    print(R.groupby("variant")["status"].value_counts().unstack(fill_value=0).to_string())
    print(f"done in {time.time() - t0:.1f}s -> {a.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
