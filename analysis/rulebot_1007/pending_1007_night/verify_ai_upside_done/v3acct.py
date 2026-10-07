"""verify3 account-level switching. python3 -I v3acct.py <export_dir> <rb_dir> <repo> <out_csv>"""
import sys, site
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import bisect
import numpy as np, pandas as pd

MIN = 60_000
TFMS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
G = {}
POL = ["base", "ANY", "UNDER"]


def acct(aid):
    from paperbot.daily3 import make_signal
    from paperbot.engine import PaperEngine
    S, steps, tl = G["S"], G["steps"], G["tl"]
    sigs = G["by"][aid]
    at = {}
    for d in sigs:
        at.setdefault(bisect.bisect_left(tl, d["bar_close"]), []).append(d)
    first = min(at)
    out = {"account_id": aid}
    for pol in POL:
        e = PaperEngine(S, G["br"], symbol_specs=G["sp"], book=pol)
        nsw = 0
        for i in range(first, len(steps)):
            ts, bars, fund = steps[i]
            for d in at.get(i, []):
                e.submit(make_signal(d))
            p = e.position
            if pol != "base" and p is not None and e.pending and any(s.ts < ts + MIN for s in e.pending):
                b = bars.get(p.symbol)
                if b is not None:
                    unr = p.side * p.qty * (b.open - p.entry_price) - p.entry_fee - p.funding_paid
                    if pol == "ANY" or unr < 0:
                        e._close_market(b.open, ts, "SW")
                        nsw += 1
            e.step(bars, fund)
        eq = e.wallet
        p = e.position
        if p is not None:
            px = e._last_mark.get(p.symbol, p.entry_price) * (1 - p.side * S.slippage_frac)
            eq += p.side * p.qty * (px - p.entry_price) - p.qty * px * S.taker_fee
        out[f"{pol}_eq"] = eq
        out[f"{pol}_n"] = len(e.trades)
        out[f"{pol}_sw"] = nsw
        if pol == "base":
            out["base_closed_pnl"] = sum(t.pnl for t in e.trades)
    return out


def main():
    exp, rb, repo, outp = sys.argv[1:5]
    sys.path.insert(0, repo)
    sys.path.append(rb)
    import analyze as A
    from paperbot.daily3 import _bar_of
    runs = [A.Run(exp, n) for n in A.discover(exp)]
    allT = pd.concat([r.trades for r in runs if r.trades is not None and len(r.trades)], ignore_index=True)
    specs = A.infer_specs(allT)
    br, _ = A.make_brackets(None)
    parts = []
    for run in runs:
        if run.bars is None or not len(run.bars):
            continue
        S = A.replay_settings(A.detect_rule(run), A.implied_taker(run))
        rates, _ = A.infer_funding(run.trades, run.bars)
        bars = run.bars.sort_values(["ts", "symbol"])
        cols = list(bars.columns)
        by_ts = {}
        for row in bars.itertuples(index=False):
            r = dict(zip(cols, row))
            for k in ("mark_open", "mark_high", "mark_low", "mark_close", "volume", "close_time"):
                v = r.get(k)
                if isinstance(v, float) and v != v:
                    r[k] = None
            if r["symbol"] in br:
                by_ts.setdefault(int(r["ts"]), {})[r["symbol"]] = _bar_of(r)
        tl = sorted(by_ts)
        steps = [(t, by_ts[t], dict(rates.get(t, {}))) for t in tl]
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        by = {}
        for r in run.sig[run.sig["status"] == "SUBMITTED"].itertuples(index=False):
            aid = f"{r.strategy}@{r.timeframe}"
            if r.timeframe not in TFMS or acc["exits"].get(aid, "house") == "reel":
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
        G.update(S=S, steps=steps, tl=tl, br=br, sp=specs, by=by)
        import multiprocessing as mp
        with mp.get_context("fork").Pool(4) as pool:
            res = pool.map(acct, sorted(by), chunksize=4)
        D = pd.DataFrame(res)
        D.insert(0, "run", "v3b" if run.name.startswith("run-20261005T18") else "v4")
        D["kind"] = D["account_id"].map(acc["kind"]).fillna(D["account_id"].map(A.infer_kind))
        D["tf"] = D["account_id"].str.split("@").str[1]
        T = run.trades
        real = T.groupby("account_id").agg(real_n=("pnl", "size"), real_pnl=("pnl", "sum"))
        D = D.merge(real, left_on="account_id", right_index=True, how="left")
        parts.append(D)
        print(run.name, len(D), flush=True)
    pd.concat(parts, ignore_index=True).to_csv(outp, index=False)


if __name__ == "__main__":
    main()
