#!/usr/bin/env python3
"""verify3: own per-signal replay of every SUBMITTED house signal (v3b, v4) with exit-rule variants driven from
outside the repo engine.  python3 -I v3rep.py <export_dir> <rb_dir> <repo> <out_csv>"""
import sys, site
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import bisect, dataclasses
import numpy as np, pandas as pd

MIN = 60_000
TFMS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN, "5m": 5 * MIN}
ORDER = ["5m", "15m", "30m", "1h", "4h"]
G = {}


def sim(d, rule="base", S=None):
    from paperbot.daily3 import make_signal
    from paperbot.engine import PaperEngine
    from paperbot.ladder import roe_price, tighten
    S = S or G["S"]
    sym, tl = d["symbol"], G["tl"]
    ss = G["ss"].get(sym)
    i0 = bisect.bisect_left(tl, d["bar_close"])
    if ss is None or i0 >= len(tl) or tl[i0] - d["bar_close"] > 5 * MIN:
        return {"st": "NOBARS"}
    e = PaperEngine(S, G["br"], symbol_specs=G["sp"], book="v3")
    e.submit(make_signal(d))
    tf = TFMS[d["timeframe"]]
    opp = G["opp"].get((rule, d["strategy"], sym, -d["side"], d["timeframe"]), []) if rule in ("OPP", "OPPH") else []
    oi = bisect.bisect_right([o[0] for o in opp], d["bar_close"])
    rec, first = {}, True
    for ts, bars, fund in ss[i0:]:
        p = e.position
        if p is not None and oi < len(opp) and opp[oi][0] <= ts:
            e._close_market(opp[oi][1], ts, "OPP")
            break
        e.step({s: b for s, b in bars.items() if s in G["br"]}, fund)
        if e.trades:
            break
        p = e.position
        if p is None:
            if not e.pending:
                break
            continue
        bar = bars[sym]
        side = p.side
        dist = abs(p.entry_price - p.stop_initial)
        ref = float(p.signal.meta.get("ref_price", p.entry_price))
        mfe = side * (p.mfe_price - p.entry_price) / dist
        cur = side * (bar.close - p.entry_price) / dist
        el = bar.close_time + 1 - d["bar_close"]
        atk = el % tf == 0
        if atk and el // tf in (2, 4):
            rec[f"u{el // tf}"] = cur
        if first:
            first = False
            if rule == "CUT05":
                p.stop_price = tighten(side, p.stop_price, ref - side * 0.5 * abs(ref - p.stop_initial))
            elif rule == "TP1":
                p.tp_price = ref + side * abs(ref - p.stop_initial)
            continue
        if rule == "BE05" and mfe >= 0.5:
            fu = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
            p.stop_price = tighten(side, p.stop_price, roe_price(side, p.entry_price, p.leverage, 0.0,
                                                                 S.round_trip_cost, fu))
        elif rule in ("NP4", "NP8") and atk and el // tf >= int(rule[2]) and p.lock_roe is None and mfe < 0.3:
            e._close_market(bar.close, bar.close_time, rule)
            break
        elif rule == "CUT05C" and atk and cur <= -0.5:
            e._close_market(bar.close, bar.close_time, rule)
            break
        elif rule in ("X2", "X4") and atk and el // tf == int(rule[1]):
            e._close_market(bar.close, bar.close_time, rule)
            break
    if e.trades:
        t = e.trades[0]
        dd = abs(t.entry_price - t.stop_initial)
        o = {"st": "T", "R": t.pnl / (t.qty * dd), "ex": t.exit_reason, "lev": t.leverage,
             "mfe": t.side * (t.mfe_price - t.entry_price) / dd, "eq": t.pnl / S.initial_equity,
             "hold": (t.exit_time - t.entry_time) / MIN}
    elif e.position is not None:
        p = e.position
        px = e._last_mark.get(sym, p.entry_price) * (1 - p.side * S.slippage_frac)
        net = p.side * p.qty * (px - p.entry_price) - p.entry_fee - p.qty * px * S.taker_fee - p.funding_paid
        dd = abs(p.entry_price - p.stop_initial)
        o = {"st": "U", "R": net / (p.qty * dd), "ex": "OPEN", "lev": p.leverage,
             "mfe": p.side * (p.mfe_price - p.entry_price) / dd, "eq": net / S.initial_equity}
    else:
        o = {"st": "REJ"}
    if rule == "base":
        o.update(rec)
    return o


def late(d, k):
    tl = G["tl"]
    ss = G["ss"].get(d["symbol"])
    t2 = d["bar_close"] + k * TFMS[d["timeframe"]]
    i = bisect.bisect_left(tl, t2)
    if ss is None or i >= len(tl):
        return {"st": "NOBARS"}
    b = ss[i][1].get(d["symbol"]) if i < len(ss) else None
    j = bisect.bisect_left([x[0] for x in ss], t2) if b is None else i
    if j >= len(ss) or d["symbol"] not in ss[j][1]:
        return {"st": "NOBARS"}
    d2 = dict(d, bar_close=t2, ref_price=float(ss[j][1][d["symbol"]].open),
              ref_time=(d["ref_time"] + k * TFMS[d["timeframe"]]) if d["ref_time"] else None)
    return sim(d2)


RULES = ["base", "CUT05", "CUT05C", "NP4", "NP8", "BE05", "TP1", "OPP", "OPPH", "X2", "X4"]


def one(i):
    d = G["sigs"][i]
    row = {k: d[k] for k in ("sig_id", "bar_close", "timeframe", "strategy", "symbol", "side")}
    for r in RULES:
        for k, v in sim(d, r).items():
            row[f"{r}_{k}"] = v
    for k in (1, 4):
        for kk, v in late(d, k).items():
            row[f"late{k}_{kk}"] = v
    for L, S in G["SL"].items():
        for kk, v in sim(d, "base", S).items():
            if kk in ("st", "R", "eq", "lev"):
                row[f"lev{L}_{kk}"] = v
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
        S = A.replay_settings(A.detect_rule(run), A.implied_taker(run))
        SL = {L: dataclasses.replace(S, tiers=(Tier("best", L / 100, (L,)), Tier("normal", L / 100, (L,))))
              for L in (20, 30, 40)}
        rates, _ = A.infer_funding(run.trades, run.bars)
        tl, ss = A.build_steps(run.bars, rates)
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        opp = {}
        for r in run.sig.itertuples(index=False):
            if r.ref_price != r.ref_price or r.timeframe not in ORDER:
                continue
            tup = (int(r.bar_close), float(r.ref_price))
            opp.setdefault(("OPP", r.strategy, r.symbol, int(r.side), r.timeframe), []).append(tup)
            for tf in ORDER[:ORDER.index(r.timeframe) + 1]:
                opp.setdefault(("OPPH", r.strategy, r.symbol, int(r.side), tf), []).append(tup)
        opp = {k: sorted(set(v)) for k, v in opp.items()}
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
        G.update(S=S, SL=SL, ss=ss, tl=tl, br=br, sp=specs, opp=opp, sigs=sigs)
        import multiprocessing as mp
        ix = list(range(len(sigs)))
        with mp.get_context("fork").Pool(4) as pool:
            res = [x for p in pool.map(chunk, [ix[k::16] for k in range(16)]) for x in p]
        R = pd.DataFrame(res)
        R.insert(0, "run", "v3b" if run.name.startswith("run-20261005T18") else "v4")
        aid = R["strategy"] + "@" + R["timeframe"]
        R["kind"] = aid.map(acc["kind"]).fillna(aid.map(A.infer_kind))
        parts.append(R)
        print(run.name, len(sigs), flush=True)
    pd.concat(parts, ignore_index=True).to_csv(outp, index=False)


if __name__ == "__main__":
    main()
