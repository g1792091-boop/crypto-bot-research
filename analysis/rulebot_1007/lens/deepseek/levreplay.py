#!/usr/bin/env python3
"""Every ds200 SUBMITTED signal of paper v4 replayed alone at FIXED leverage L (margin = L % of equity, the owners'
"margin = leverage %" rule), house exits (2 ATR stop + ROE ladder), on the run's own live_bars, through the repo's
engine via the validated pipeline's functions (analyze.py is imported from its path, never edited).

    python3 -I levreplay.py <analyze.py> <export_root> <repo> <out_dir> [--levs 10,20,30,40,50] [--procs 4]

Writes <out_dir>/lev_replay_signals.csv (one row per signal x leverage) and lev_replay_summary.csv.
Parity check: L = 30 reproduces the pipeline's replay R for signals the pipeline replayed at 30x.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def load_analyze(path):
    spec = importlib.util.spec_from_file_location("rb_analyze_mod", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rb_analyze_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analyze")
    ap.add_argument("export_root")
    ap.add_argument("repo")
    ap.add_argument("out_dir")
    ap.add_argument("--levs", default="10,20,30,40,50")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--kinds", default="ds200")
    a = ap.parse_args()
    sys.path.insert(0, a.repo)
    an = load_analyze(a.analyze)
    from paperbot.config import Tier, v3_settings
    run = an.Run(a.export_root, "current")
    rule, taker = an.detect_rule(run), an.implied_taker(run)
    brackets, _ = an.make_brackets(None)
    specs = an.infer_specs(run.trades)
    rates, finfo = an.infer_funding(run.trades, run.bars)
    ts_list, ssteps = an.build_steps(run.bars, rates)
    acc = run.accounts.set_index("account_id")
    kinds = set(a.kinds.split(","))
    strength = an.load_ctx_strength(run.ctx_path)
    sub = run.sig[run.sig["status"] == "SUBMITTED"]
    sigs = []
    for r in sub.itertuples(index=False):
        aid = f"{r.strategy}@{r.timeframe}"
        if acc["kind"].get(aid, an.infer_kind(aid)) not in kinds:
            continue
        d = {"sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy,
             "symbol": r.symbol, "side": int(r.side), "atr": an.fnum(r.atr), "ref_price": an.fnum(r.ref_price),
             "ref_time": int(r.ref_time) if r.ref_time == r.ref_time else None,
             "delay_ms": int(r.delay_ms) if r.delay_ms == r.delay_ms else None}
        ctx = strength.get(int(r.id))
        d["data"] = {"ctx": ctx} if ctx else {}
        sigs.append(d)
    print(f"signals {len(sigs)}, rule {rule}, taker {taker}, funding {finfo}", flush=True)
    rows = []
    for L in [int(x) for x in a.levs.split(",")]:
        S = v3_settings(taker_fee=taker, min_leverage=5, min_margin_frac=0.05, max_margin_frac=0.50,
                        tiers=(Tier("best", L / 100, (L,)), Tier("normal", L / 100, (L,))))
        an._G.clear()
        an._G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, settings=S, brackets=brackets, specs=specs, flip=False)
        idx = list(range(len(sigs)))
        import multiprocessing as mp
        chunks = [idx[k::a.procs * 4] for k in range(a.procs * 4)]
        with mp.get_context("fork").Pool(a.procs) as pool:
            parts = pool.map(an._replay_chunk, chunks)
        res = pd.DataFrame([x for p in parts for x in p])
        res["lev_fixed"] = L
        rows.append(res)
        print(L, res["status"].value_counts().to_dict(), flush=True)
    R = pd.concat(rows, ignore_index=True)
    os.makedirs(a.out_dir, exist_ok=True)
    R.to_csv(os.path.join(a.out_dir, "lev_replay_signals.csv"), index=False)


if __name__ == "__main__":
    main()
