#!/usr/bin/env python3
"""verify2: independent replay of every SUBMITTED house signal (v3b, v4) through the repo PaperEngine with exit rules
applied by an outside driver (no engine subclass). Own code; imports rb_analyze/analyze.py loaders only.

    python3 -I vr.py <export_dir> <rb_dir> <repo> <out_csv>
"""
import sys
sys.dont_write_bytecode = True
import site
sys.path.append(site.getusersitepackages())
import bisect, math, os, time
import numpy as np
import pandas as pd

MIN = 60_000
TFMS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
TFS = ["5m", "15m", "30m", "1h", "4h"]
RULES = ["base", "CUT05", "CUT05C", "NP4", "NP8", "BE05", "TP1", "DEEP4", "OPP", "OPPH"]
G = {}


def drive(d, rule):
    from paperbot.daily3 import make_signal
    from paperbot.engine import PaperEngine
    from paperbot.ladder import roe_price, tighten
    S = G["S"]
    sym = d["symbol"]
    ss = G["ss"].get(sym)
    tl = G["tl"]
    i0 = bisect.bisect_left(tl, d["bar_close"])
    if ss is None or i0 >= len(tl) or tl[i0] - d["bar_close"] > 5 * MIN:
        return {"st": "NOBARS"}
    sig = make_signal(d)
    e = PaperEngine(S, G["br"], symbol_specs=G["sp"], book="v2")
    e.submit(sig)
    tf = TFMS[d["timeframe"]]
    opp = G["opp"].get((rule, d["strategy"], sym, -int(d["side"]), d["timeframe"]), []) if rule in ("OPP", "OPPH") else []
    oppt = [o[0] for o in opp]
    path = {}
    entered = False
    for ts, bars, fund in ss[i0:]:
        p = e.position
        # OPP: opposite signal whose bar closed at or before this 1m bar's open -> close at its reference price
        if p is not None and opp:
            k = bisect.bisect_right(oppt, d["bar_close"])
            if k < len(opp) and opp[k][0] <= ts:
                e._close_market(opp[k][1], ts, "OPP")
                break
        e.step({s: b for s, b in bars.items() if s in G["br"]}, fund)
        if e.trades:
            break
        p = e.position
        if p is None:
            if not e.pending:
                break
            continue
        bar = bars.get(sym)
        side = p.side
        dist0 = abs(p.entry_price - p.stop_initial)
        refp = float(p.signal.meta.get("ref_price", p.entry_price))
        refdist = abs(refp - p.stop_initial)
        mfe = side * (p.mfe_price - p.entry_price) / dist0
        el = bar.close_time + 1 - d["bar_close"]     # time since the signal bar close
        cur = side * (bar.close - p.entry_price) / dist0
        if el % tf == 0:
            kb = el // tf
            if kb in (1, 2, 4, 8) and f"u{kb}" not in path:
                path[f"u{kb}"] = cur
                path[f"m{kb}"] = mfe
                path[f"l{kb}"] = p.lock_roe is not None
        if not entered:
            entered = True
            if rule == "CUT05":       # PREREG: reference - side x 0.5 x stop distance at entry
                p.stop_price = tighten(side, p.stop_price, refp - side * 0.5 * refdist)
            if rule == "TP1":
                p.tp_price = refp + side * refdist
            continue
        if rule == "BE05" and mfe >= 0.5:
            fu = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
            p.stop_price = tighten(side, p.stop_price, roe_price(side, p.entry_price, p.leverage, 0.0,
                                                                 S.round_trip_cost, fu))
        if rule in ("NP4", "NP8") and el % tf == 0 and el // tf >= (4 if rule == "NP4" else 8):
            if p.lock_roe is None and mfe < 0.3:
                e._close_market(bar.close, bar.close_time, rule)
                break
        if rule == "CUT05C" and el % tf == 0 and cur <= -0.5:     # AI-visible: act at a tf bar close
            e._close_market(bar.close, bar.close_time, rule)
            break
        if rule == "DEEP4" and el == 4 * tf and cur <= -0.5:       # AIH-3 state rule
            e._close_market(bar.close, bar.close_time, rule)
            break
    out = {}
    if e.trades:
        t = e.trades[0]
        dd = abs(t.entry_price - t.stop_initial)
        out = {"st": "TRADED", "R": t.pnl / (t.qty * dd), "ex": t.exit_reason, "lev": t.leverage,
               "mfe": t.side * (t.mfe_price - t.entry_price) / dd, "pnl": t.pnl,
               "cost": (t.fees + t.funding) / (t.qty * dd), "hold": (t.exit_time - t.entry_time) / MIN}
    elif e.position is not None:
        p = e.position
        last = e._last_mark.get(sym, p.entry_price)
        px = last * (1 - p.side * S.slippage_frac)
        net = p.side * p.qty * (px - p.entry_price) - p.entry_fee - p.qty * px * S.taker_fee - p.funding_paid
        dd = abs(p.entry_price - p.stop_initial)
        out = {"st": "OPEN", "R": net / (p.qty * dd), "ex": "OPEN_END", "lev": p.leverage,
               "mfe": p.side * (p.mfe_price - p.entry_price) / dd, "pnl": net}
    else:
        out = {"st": "REJ"}
    if rule == "base":
        out.update(path)
    return out


def one(i):
    d = G["sigs"][i]
    row = {k: d[k] for k in ("sig_id", "bar_close", "timeframe", "strategy", "symbol", "side")}
    for rule in RULES:
        o = drive(d, rule)
        for k, v in o.items():
            row[f"{rule}_{k}" if k not in ("u1", "u2", "u4", "u8", "m1", "m2", "m4", "m8", "l1", "l2", "l4", "l8") else k] = v
    return row


def chunk(ix):
    return [one(i) for i in ix]


def main():
    exp, rb, repo, outp = sys.argv[1:5]
    sys.path.insert(0, repo)
    sys.path.append(rb)
    import analyze as A
    names = A.discover(exp)
    runs = [A.Run(exp, n) for n in names]
    allT = pd.concat([r.trades for r in runs if r.trades is not None and len(r.trades)], ignore_index=True)
    specs = A.infer_specs(allT)
    br, _ = A.make_brackets(None)
    parts = []
    for run in runs:
        if run.bars is None or not len(run.bars):
            continue
        t0 = time.time()
        S = A.replay_settings(A.detect_rule(run), A.implied_taker(run))
        rates, _ = A.infer_funding(run.trades, run.bars)
        tl, ss = A.build_steps(run.bars, rates)
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        opp = {}
        for r in run.sig.itertuples(index=False):
            if r.ref_price != r.ref_price:
                continue
            tup = (int(r.bar_close), float(r.ref_price))
            opp.setdefault(("OPP", r.strategy, r.symbol, int(r.side), r.timeframe), []).append(tup)
            for tf in TFS[:TFS.index(r.timeframe) + 1] if r.timeframe in TFS else []:
                opp.setdefault(("OPPH", r.strategy, r.symbol, int(r.side), tf), []).append(tup)
        for k in opp:
            opp[k] = sorted(set(opp[k]))
        sigs = []
        for r in run.sig[run.sig["status"] == "SUBMITTED"].itertuples(index=False):
            aid = f"{r.strategy}@{r.timeframe}"
            if acc["exits"].get(aid, "house") == "reel":
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
        G.update(S=S, ss=ss, tl=tl, br=br, sp=specs, opp=opp, sigs=sigs)
        import multiprocessing as mp
        ix = list(range(len(sigs)))
        ch = [ix[k::16] for k in range(16)]
        with mp.get_context("fork").Pool(4) as pool:
            res = [x for p in pool.map(chunk, ch) for x in p]
        R = pd.DataFrame(res)
        R.insert(0, "run", run.name)
        R["account_id"] = R["strategy"] + "@" + R["timeframe"]
        R["kind"] = R["account_id"].map(acc["kind"]).fillna(R["account_id"].map(A.infer_kind))
        parts.append(R)
        print(run.name, len(sigs), round(time.time() - t0, 1), flush=True)
    pd.concat(parts, ignore_index=True).to_csv(outp, index=False)


if __name__ == "__main__":
    main()
