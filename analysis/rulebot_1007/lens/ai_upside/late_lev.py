#!/usr/bin/env python3
"""PREREG addendum: late entry of a signal (k = 1, 2, 4 bars of its timeframe later, fresh 2 ATR stop from the later
1m open) and fixed leverage 20/30/40/50x (margin = leverage %), every SUBMITTED signal alone, v3b and v4.

    python3 -I late_lev.py <export_dir> <rb_analyze_dir> <repo> <out_dir> [--procs 4]
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import site  # noqa: E402
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)

import argparse  # noqa: E402
import bisect  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN = 60_000
TF_MS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
LEVS = [20, 30, 40, 50]
LATES = [1, 2, 4]
_G: dict = {}


def alone(S, sig, ss, i0):
    from paperbot.daily3 import _alone
    from paperbot.engine import PaperEngine
    tr, resolved = _alone(S, _G["brackets"], _G["specs"], sig, ss, i0)
    if tr is not None:
        dist = abs(tr.entry_price - tr.stop_initial)
        return {"status": "TRADED", "R": tr.pnl / (tr.qty * dist), "exit": tr.exit_reason, "lev": tr.leverage,
                "roe": tr.roe, "eqret": tr.pnl / S.initial_equity}
    if resolved:
        return {"status": "REJECTED"}
    e = PaperEngine(S, _G["brackets"], symbol_specs=_G["specs"], book="mark")
    e.submit(sig)
    for ts, bars, fund in ss[i0:]:
        e.step(bars, fund)
    p = e.position
    if p is None:
        return {"status": "REJECTED"}
    last = e._last_mark.get(sig.symbol, p.entry_price)
    px = last * (1 - p.side * S.slippage_frac)
    net = p.side * p.qty * (px - p.entry_price) - p.entry_fee - p.qty * px * S.taker_fee - p.funding_paid
    dist = abs(p.entry_price - p.stop_initial)
    return {"status": "UNRESOLVED", "R": net / (p.qty * dist), "exit": "OPEN_END", "lev": p.leverage,
            "roe": net / p.margin_initial, "eqret": net / S.initial_equity}


def do(i):
    from paperbot.daily3 import make_signal
    d = _G["sigs"][i]
    ts_list = _G["ts_list"]
    ss = _G["ssteps"].get(d["symbol"])
    row = {k: d[k] for k in ("sig_id", "bar_close", "timeframe", "strategy", "symbol", "side")}
    i0 = bisect.bisect_left(ts_list, d["bar_close"])
    if ss is None or i0 >= len(ts_list):
        return row
    o = alone(_G["S"], make_signal(d), ss, i0)
    row.update({f"base_{k}": v for k, v in o.items()})
    for L in LEVS:
        o = alone(_G["SL"][L], make_signal(d), ss, i0)
        row.update({f"lev{L}_{k}": v for k, v in o.items()})
    for k in LATES:
        bc = d["bar_close"] + k * TF_MS[d["timeframe"]]
        j = bisect.bisect_left(ts_list, bc)
        if j >= len(ts_list) or ts_list[j] - bc > 5 * MIN:
            continue
        b = ss[j][1].get(d["symbol"])
        if b is None:
            continue
        d2 = dict(d)
        d2["bar_close"] = bc
        o = alone(_G["S"], make_signal(d2, ref=b.open), ss, j)
        row.update({f"late{k}_{kk}": v for kk, v in o.items()})
    return row


def chunk(idx):
    return [do(i) for i in idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("rb_dir")
    ap.add_argument("repo")
    ap.add_argument("out_dir")
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    sys.path.insert(0, a.repo)
    sys.path.append(a.rb_dir)
    import analyze as A  # noqa: E402
    from paperbot.config import Tier  # noqa: E402
    names = A.discover(a.export_dir)
    runs = [A.Run(a.export_dir, n) for n in names]
    allT = pd.concat([r.trades for r in runs if r.trades is not None and len(r.trades)], ignore_index=True)
    specs = A.infer_specs(allT)
    brackets, _ = A.make_brackets(None)
    parts = []
    for run in runs:
        if run.bars is None or not len(run.bars):
            continue
        t0 = time.time()
        taker = A.implied_taker(run)
        S = A.replay_settings(A.detect_rule(run), taker)
        SL = {}
        for L in LEVS:
            m = L / 100.0
            SL[L] = A.replay_settings(A.detect_rule(run), taker).__class__(
                **{**S.__dict__, "tiers": (Tier("best", m, (L,)), Tier("normal", m, (L,))),
                   "min_margin_frac": min(0.2, m), "max_margin_frac": max(0.5, m)})
        rates, _ = A.infer_funding(run.trades, run.bars)
        ts_list, ssteps = A.build_steps(run.bars, rates)
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        sub = run.sig[run.sig["status"] == "SUBMITTED"]
        sigs = []
        for r in sub.itertuples(index=False):
            aid = f"{r.strategy}@{r.timeframe}"
            if acc["exits"].get(aid, "house") == "reel" or r.timeframe not in TF_MS:
                continue
            d = {"sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy,
                 "symbol": r.symbol, "side": int(r.side), "atr": A.fnum(r.atr), "ref_price": A.fnum(r.ref_price),
                 "ref_time": int(r.ref_time) if r.ref_time == r.ref_time else None,
                 "delay_ms": int(r.delay_ms) if r.delay_ms == r.delay_ms else None}
            if not (d["atr"] == d["atr"] and d["atr"] > 0 and d["ref_price"] == d["ref_price"]):
                continue
            ctx = strength.get(int(r.id))
            d["data"] = {"ctx": ctx} if ctx else {}
            sigs.append(d)
        _G.clear()
        _G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, S=S, SL=SL, brackets=brackets, specs=specs)
        import multiprocessing as mp
        idx = list(range(len(sigs)))
        chunks = [idx[k::a.procs * 4] for k in range(a.procs * 4)]
        with mp.get_context("fork").Pool(a.procs) as pool:
            res = [x for p in pool.map(chunk, chunks) for x in p]
        R = pd.DataFrame(res)
        R.insert(0, "run", run.name)
        R["kind"] = (R["strategy"] + "@" + R["timeframe"]).map(acc["kind"]).fillna(
            (R["strategy"] + "@" + R["timeframe"]).map(A.infer_kind))
        parts.append(R)
        print(f"{run.name}: {len(sigs)} signals in {time.time() - t0:.1f}s", flush=True)
    R = pd.concat(parts, ignore_index=True)
    R.to_csv(os.path.join(a.out_dir, "late_lev_signals.csv"), index=False)
    # summaries
    RUNS = {"run-20261005T183457Z": "v3b", "current": "v4"}
    R["run_s"] = R["run"].map(RUNS)
    R["cl"] = R["run_s"] + "|" + (R["bar_close"] // (np.maximum(R["timeframe"].map(TF_MS), 60 * MIN))).astype(str)
    rng = np.random.default_rng(9)
    rows = []
    ok = lambda c: R[f"{c}_status"].isin(["TRADED", "UNRESOLVED"]) if f"{c}_status" in R else False  # noqa: E731
    for kind in ("strategy", "ds200"):
        for tf in ("15m", "30m", "1h", "4h"):
            base = R[(R["kind"] == kind) & (R["timeframe"] == tf)]
            for var in [f"late{k}" for k in LATES] + [f"lev{L}" for L in LEVS]:
                g = base[ok("base").loc[base.index] & ok(var).loc[base.index]]
                if var.startswith("lev"):
                    g = g[ok("lev20").loc[g.index] & ok("lev50").loc[g.index]]   # same signals for every leverage
                if len(g) < 10:
                    continue
                d = (g[f"{var}_R"] - g["base_R"]).to_numpy(float)
                u, inv = np.unique(g["cl"], return_inverse=True)
                sums = np.bincount(inv, weights=d)
                cnt = np.bincount(inv)
                idx = rng.integers(0, len(u), size=(4000, len(u)))
                bs = sums[idx].sum(1) / cnt[idx].sum(1)
                row = {"kind": kind, "tf": tf, "variant": var, "n": len(g), "clusters": len(u),
                       "mean_R_base": g["base_R"].mean(), "mean_R_variant": g[f"{var}_R"].mean(), "diff_R": d.mean(),
                       "ci_lo": np.percentile(bs, 2.5), "ci_hi": np.percentile(bs, 97.5),
                       "mean_eqret_variant_pct": 100 * g[f"{var}_eqret"].mean(),
                       "share_LOCK": (g[f"{var}_exit"] == "LOCK").mean()}
                for rs in ("v3b", "v4"):
                    gg = g[g["run_s"] == rs]
                    row[f"diff_{rs}"] = (gg[f"{var}_R"] - gg["base_R"]).mean() if len(gg) else np.nan
                    row[f"n_{rs}"] = len(gg)
                rows.append(row)
    Sm = pd.DataFrame(rows)
    Sm.to_csv(os.path.join(a.out_dir, "late_lev_summary.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(Sm.round(3).to_string())


if __name__ == "__main__":
    main()
