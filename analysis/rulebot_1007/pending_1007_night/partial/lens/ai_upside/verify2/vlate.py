#!/usr/bin/env python3
"""verify2: late entry (k bars) and fixed leverage (margin = lev%) paired replays, own code.
    python3 -I vlate.py <export_dir> <rb_dir> <repo> <out_csv>"""
import sys
sys.dont_write_bytecode = True
import site
sys.path.append(site.getusersitepackages())
import bisect, dataclasses, time
import pandas as pd

MIN = 60_000
TFMS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
G = {}


def run1(d, S):
    from paperbot.daily3 import make_signal, _alone
    sym = d["symbol"]
    ss = G["ss"].get(sym)
    tl = G["tl"]
    i0 = bisect.bisect_left(tl, d["bar_close"])
    if ss is None or i0 >= len(tl) or tl[i0] - d["bar_close"] > 5 * MIN:
        return None
    tr, res = _alone(S, G["br"], G["sp"], make_signal(d), ss, i0)
    if tr is None:
        return "REJ" if res else "OPEN"
    return tr.pnl / (tr.qty * abs(tr.entry_price - tr.stop_initial))


def one(i):
    d = G["sigs"][i]
    row = {k: d[k] for k in ("sig_id", "bar_close", "timeframe", "strategy", "symbol")}
    row["base"] = run1(d, G["S"])
    tf = TFMS[d["timeframe"]]
    for k in (1, 2, 4):
        bc = d["bar_close"] + k * tf
        j = bisect.bisect_left(G["tl"], bc)
        if j >= len(G["tl"]) or G["tl"][j] != bc:
            row[f"late{k}"] = None
            continue
        b = G["byts"][bc].get(d["symbol"])
        if b is None:
            row[f"late{k}"] = None
            continue
        d2 = dict(d, bar_close=bc, ref_price=b.open, ref_time=bc, delay_ms=0)
        row[f"late{k}"] = run1(d2, G["S"])
    for L, SL in G["SL"].items():
        row[f"lev{L}"] = run1(d, SL)
    return row


def chunk(ix):
    return [one(i) for i in ix]


def main():
    exp, rb, repo, outp = sys.argv[1:5]
    sys.path.insert(0, repo)
    sys.path.append(rb)
    import analyze as A
    from paperbot.config import Tier
    runs = [A.Run(exp, n) for n in A.discover(exp)]
    allT = pd.concat([r.trades for r in runs if r.trades is not None and len(r.trades)], ignore_index=True)
    specs = A.infer_specs(allT)
    br, _ = A.make_brackets(None)
    parts = []
    for run in runs:
        if run.bars is None or not len(run.bars):
            continue
        t0 = time.time()
        S = A.replay_settings(A.detect_rule(run), A.implied_taker(run))
        SL = {}
        for L in (20, 30, 40, 50):
            m = L / 100
            SL[L] = dataclasses.replace(S, tiers=tuple(Tier(t.name, m, (L,)) for t in S.tiers),
                                        min_margin_frac=min(S.min_margin_frac, m), max_margin_frac=max(S.max_margin_frac, m))
        rates, _ = A.infer_funding(run.trades, run.bars)
        tl, ss = A.build_steps(run.bars, rates)
        byts = {}
        for s, steps in ss.items():
            for ts, bars, f in steps:
                if s in bars:
                    byts.setdefault(ts, {})[s] = bars[s]
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        sigs = []
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
            sigs.append(d)
        G.clear()
        G.update(S=S, SL=SL, ss=ss, tl=tl, byts=byts, br=br, sp=specs, sigs=sigs)
        import multiprocessing as mp
        ix = list(range(len(sigs)))
        with mp.get_context("fork").Pool(4) as pool:
            res = [x for p in pool.map(chunk, [ix[k::16] for k in range(16)]) for x in p]
        R = pd.DataFrame(res)
        R.insert(0, "run", run.name)
        R["kind"] = (R["strategy"] + "@" + R["timeframe"]).map(acc["kind"])
        parts.append(R)
        print(run.name, len(sigs), round(time.time() - t0, 1), flush=True)
    pd.concat(parts, ignore_index=True).to_csv(outp, index=False)


if __name__ == "__main__":
    main()
