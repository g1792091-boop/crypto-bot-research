#!/usr/bin/env python3
"""verify2: account-level switching re-simulation, own driver (close is done outside the engine before the step).
    python3 -I vsw.py <export_dir> <rb_dir> <repo> <out_csv>"""
import sys
sys.dont_write_bytecode = True
import site
sys.path.append(site.getusersitepackages())
import bisect, os, time
import numpy as np
import pandas as pd

MIN = 60_000
TFMS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
POLS = ["base", "ANY", "UNDER", "OPP"]
G = {}


def sim(aid):
    from paperbot.daily3 import make_signal
    from paperbot.engine import PaperEngine
    S = G["S"]
    tl, steps = G["tl"], G["steps"]
    bystep = {}
    for d in G["acc"][aid]:
        i = bisect.bisect_left(tl, d["bar_close"])
        if i < len(tl) and tl[i] - d["bar_close"] <= 5 * MIN:
            bystep.setdefault(i, []).append(make_signal(d))
    res = []
    if not bystep:
        return res
    for pol in POLS:
        e = PaperEngine(S, G["br"], symbol_specs=G["sp"], book=pol)
        nsw = 0
        sw_cost = 0.0
        for k in range(min(bystep), len(steps)):
            ts, bars, fund = steps[k]
            new = bystep.get(k, [])
            p = e.position
            if new and p is not None and pol != "base" and not e.halted:
                hb = bars.get(p.symbol)
                go = False
                if hb is not None:
                    if pol == "ANY":
                        go = True
                    elif pol == "UNDER":
                        go = p.side * (hb.open - p.entry_price) * p.qty - p.entry_fee - p.funding_paid \
                            - p.qty * hb.open * (S.taker_fee + S.slippage_frac) < 0
                    elif pol == "OPP":
                        go = any(s.symbol == p.symbol and s.side == -p.side for s in new)
                if go:
                    # only switch if the new signal has a bar now (the engine needs it)
                    if any(bars.get(s.symbol) is not None for s in new):
                        e._close_market(hb.open, ts, "SWITCH")
                        nsw += 1
            for s in new:
                e.submit(s)
            e.step({s: b for s, b in bars.items() if s in G["br"]}, fund)
        cost = sum(t.fees + S.slippage_frac * t.qty * (t.entry_price + t.exit_price) for t in e.trades
                   if t.exit_reason != "LIQ")
        res.append({"account_id": aid, "pol": pol, "eq": e.equity(), "n_trades": len(e.trades),
                    "closed_pnl": sum(t.pnl for t in e.trades), "n_switch": nsw, "cost": cost,
                    "open_end": e.position is not None})
    return res


def main():
    exp, rb, repo, outp = sys.argv[1:5]
    sys.path.insert(0, repo)
    sys.path.append(rb)
    import analyze as A
    runs = [A.Run(exp, n) for n in A.discover(exp)]
    allT = pd.concat([r.trades for r in runs if r.trades is not None and len(r.trades)], ignore_index=True)
    specs = A.infer_specs(allT)
    br, _ = A.make_brackets(None)
    out = []
    for run in runs:
        if run.bars is None or not len(run.bars):
            continue
        t0 = time.time()
        S = A.replay_settings(A.detect_rule(run), A.implied_taker(run))
        rates, _ = A.infer_funding(run.trades, run.bars)
        tl, _ss = A.build_steps(run.bars, rates)
        # whole-market steps (all symbols) for an account
        from paperbot.daily3 import _bar_of
        b = run.bars.sort_values(["ts", "symbol"])
        cols = list(b.columns)
        byts = {}
        for row in b.itertuples(index=False):
            r = dict(zip(cols, row))
            for kk in ("mark_open", "mark_high", "mark_low", "mark_close", "volume", "close_time"):
                v = r.get(kk)
                if isinstance(v, float) and v != v:
                    r[kk] = None
            byts.setdefault(int(r["ts"]), {})[r["symbol"]] = _bar_of(r)
        tl = sorted(byts)
        steps = [(t, byts[t], dict(rates.get(t, {}))) for t in tl]
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        by = {}
        for r in run.sig[run.sig["status"] == "SUBMITTED"].itertuples(index=False):
            aid = f"{r.strategy}@{r.timeframe}"
            if acc["exits"].get(aid, "house") == "reel" or r.timeframe not in TFMS:
                continue
            d = {"sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy,
                 "symbol": r.symbol, "side": int(r.side), "atr": A.fnum(r.atr), "ref_price": A.fnum(r.ref_price),
                 "ref_time": int(r.ref_time) if r.ref_time == r.ref_time else None,
                 "delay_ms": int(r.delay_ms) if r.delay_ms == r.delay_ms else None}
            if not (d["atr"] == d["atr"] and d["atr"] > 0 and d["ref_price"] == d["ref_price"]):
                continue
            c = strength.get(int(r.id))
            d["data"] = {"ctx": c} if c else {}
            by.setdefault(aid, []).append(d)
        G.clear()
        G.update(S=S, tl=tl, steps=steps, br=br, sp=specs, acc=by)
        import multiprocessing as mp
        with mp.get_context("fork").Pool(4) as pool:
            res = [x for p in pool.map(sim, sorted(by), chunksize=2) for x in p]
        D = pd.DataFrame(res)
        D.insert(0, "run", run.name)
        D["kind"] = D["account_id"].map(acc["kind"]).fillna(D["account_id"].map(A.infer_kind))
        D["tf"] = D["account_id"].str.split("@").str[-1]
        real = run.trades.groupby("account_id").agg(real_n=("pnl", "size"), real_pnl=("pnl", "sum"))
        D = D.merge(real, left_on="account_id", right_index=True, how="left")
        out.append(D)
        print(run.name, len(by), round(time.time() - t0, 1), flush=True)
    pd.concat(out, ignore_index=True).to_csv(outp, index=False)


if __name__ == "__main__":
    main()
