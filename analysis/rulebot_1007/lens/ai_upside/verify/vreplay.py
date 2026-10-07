#!/usr/bin/env python3
"""Independent verification replay (verifier's own code; does not import the lens scripts).

Every SUBMITTED, non-reel signal of v3b and v4 alone through paperbot.engine.PaperEngine on live_bars, with
rule variants implemented by overriding _try_enter / _handle_exit (a different hook than the lens used),
fixed leverage variants and late entries, plus a per-signal path record.

    python3 -I vreplay.py <export_dir> <rb_analyze_dir> <repo> <out_csv> [--procs 4]
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import site  # noqa: E402
_us = site.getusersitepackages()
if _us not in sys.path:
    sys.path.append(_us)

import argparse  # noqa: E402
import bisect  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN = 60_000
TF_MS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
TFS = ["15m", "30m", "1h", "4h", "1d"]
G: dict = {}


def engine_cls():
    from paperbot.engine import PaperEngine
    from paperbot.ladder import roe_price, tighten

    class V(PaperEngine):
        rule = "base"
        tf_ms = 0
        opp_list: list = []
        rec = None

        def _try_enter(self, sig, bar):
            ok = super()._try_enter(sig, bar)
            if ok:
                p = self.position
                p._vdist = abs(p.entry_price - p.stop_initial)
                p._vbars = 0
                if self.rule == "CUT05i":
                    p.stop_price = tighten(p.side, p.stop_price, p.entry_price - p.side * 0.5 * p._vdist)
            return ok

        def step(self, bars, funding=None):
            p = self.position
            if p is not None and self.rule in ("OPP", "OPPH"):
                t_open = min(b.open_time for b in bars.values()) if bars else None
                for bc, ref, rt in self.opp_list:
                    if bc <= p.signal.ts + 1:
                        continue
                    if t_open is not None and bc <= t_open:
                        self._close(ref * (1 - p.side * self.s.slippage_frac), t_open, self.rule, maker=False)
                    break
            super().step(bars, funding)

        def _handle_exit(self, bar, entry_bar):
            super()._handle_exit(bar, entry_bar)
            p = self.position
            if p is None:
                return
            d = p._vdist
            s = p.side
            t_rel = bar.close_time + 1 - p.entry_time
            mfe = s * (p.mfe_price - p.entry_price) / d
            if self.rec is not None:
                self._vrec(p, bar, t_rel, mfe)
            r = self.rule
            if entry_bar:
                if r == "TP1":
                    ref = float(p.signal.meta.get("ref_price", p.entry_price))
                    p.tp_price = ref + s * abs(ref - p.stop_initial)
                elif r == "CUT05":
                    p.stop_price = tighten(s, p.stop_price, p.entry_price - s * 0.5 * d)
                return
            if r in ("BE05", "BE10"):
                if mfe >= (0.5 if r == "BE05" else 1.0):
                    f = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
                    p.stop_price = tighten(s, p.stop_price,
                                           roe_price(s, p.entry_price, p.leverage, 0.0, self.s.round_trip_cost, f))
            elif r in ("NP4", "NP8"):
                nb = 4 if r == "NP4" else 8
                if t_rel >= nb * self.tf_ms and mfe < 0.3 and p.lock_roe is None:
                    self._close(bar.close * (1 - s * self.s.slippage_frac), bar.close_time, r, maker=False)

        def _vrec(self, p, bar, t_rel, mfe):
            rec = self.rec
            s, d = p.side, p._vdist
            px = bar.close * (1 - s * self.s.slippage_frac)
            net = s * p.qty * (px - p.entry_price) - p.entry_fee - p.qty * px * self.s.taker_fee - p.funding_paid
            now_R = net / (p.qty * d)
            gross_R = s * (bar.close - p.entry_price) / d
            mae = s * (p.mae_price - p.entry_price) / d
            if mfe > rec.get("mfe_max", -99) + 1e-12:
                rec["mfe_max"] = mfe
                rec["t_mfe_max"] = t_rel / MIN
            for th in (0.2, 0.3, 0.5, 1.0):
                if mfe >= th and f"t_{th}" not in rec:
                    rec[f"t_{th}"] = t_rel / MIN
                    rec[f"mae_before_{th}"] = mae
            for k in (1, 2, 4, 8):
                if f"now{k}" not in rec and t_rel >= k * self.tf_ms:
                    rec[f"now{k}"] = now_R
                    rec[f"gross{k}"] = gross_R
                    rec[f"mfe{k}"] = mfe
                    rec[f"lock{k}"] = p.lock_roe is not None
            if p.lock_roe is not None and "t_lock" not in rec:
                rec["t_lock"] = t_rel / MIN
                rec["mfe_at_lock"] = mfe

    return V


def run_variant(d, rule, S=None, record=False, i0=None, ref=None, bar_close=None):
    from paperbot.daily3 import make_signal
    sym = d["symbol"]
    ss = G["ss"].get(sym)
    ts_list = G["ts"]
    if i0 is None:
        i0 = bisect.bisect_left(ts_list, d["bar_close"])
    if ss is None or i0 >= len(ts_list):
        return {"st": "NO_BARS"}
    dd = dict(d)
    if bar_close is not None:
        dd["bar_close"] = bar_close
    sig = make_signal(dd, ref=ref)
    S = S or G["S"]
    E = G["V"](S, G["br"], symbol_specs=G["specs"], book="v")
    E.rule = rule
    E.tf_ms = TF_MS[d["timeframe"]]
    if rule in ("OPP", "OPPH"):
        key = (d["strategy"], sym, -d["side"])
        E.opp_list = G["opp_same" if rule == "OPP" else "opp_high"].get(key + (d["timeframe"],), [])
    if record:
        E.rec = {}
    E.submit(sig)
    out = {}
    done = False
    for ts, bars, fund in ss[i0:]:
        E.step({s: b for s, b in bars.items() if s in G["br"]}, fund)
        if E.trades:
            t = E.trades[0]
            dist = abs(t.entry_price - t.stop_initial)
            out = {"st": "TRADED", "R": t.pnl / (t.qty * dist), "exit": t.exit_reason, "lev": t.leverage,
                   "pnl": t.pnl, "hold": (t.exit_time - t.entry_time) / MIN,
                   "mfe": t.side * (t.mfe_price - t.entry_price) / dist,
                   "mae": t.side * (t.mae_price - t.entry_price) / dist,
                   "sf": dist / t.entry_price, "lock": t.lock_roe, "margin": t.margin, "qty": t.qty,
                   "entry": t.entry_price, "entry_time": t.entry_time}
            done = True
            break
        if E.position is None and not E.pending:
            out = {"st": "REJECTED"}
            done = True
            break
    if not done:
        p = E.position
        if p is None:
            out = {"st": "REJECTED"}
        else:
            last = E._last_mark.get(sym, p.entry_price)
            px = last * (1 - p.side * S.slippage_frac)
            net = p.side * p.qty * (px - p.entry_price) - p.entry_fee - p.qty * px * S.taker_fee - p.funding_paid
            dist = abs(p.entry_price - p.stop_initial)
            out = {"st": "OPEN", "R": net / (p.qty * dist), "exit": "OPEN_END", "lev": p.leverage, "pnl": net,
                   "hold": (ts_list[-1] + MIN - p.entry_time) / MIN,
                   "mfe": p.side * (p.mfe_price - p.entry_price) / dist,
                   "mae": p.side * (p.mae_price - p.entry_price) / dist, "sf": dist / p.entry_price,
                   "lock": p.lock_roe, "margin": p.margin_initial, "qty": p.qty, "entry": p.entry_price,
                   "entry_time": p.entry_time}
    if record:
        out.update({f"p_{k}": v for k, v in E.rec.items()})
    return out


RULES = ["CUT05", "CUT05i", "NP4", "NP8", "BE05", "BE10", "TP1", "OPP", "OPPH"]


def one(i):
    d = G["sigs"][i]
    row = {k: d[k] for k in ("sig_id", "bar_close", "timeframe", "strategy", "symbol", "side")}
    b = run_variant(d, "base", record=True)
    row.update({f"base_{k}" if not k.startswith("p_") else k: v for k, v in b.items()})
    if b.get("st") not in ("TRADED", "OPEN"):
        return row
    for r in RULES:
        o = run_variant(d, r)
        for k in ("st", "R", "exit", "hold", "pnl"):
            row[f"{r}_{k}"] = o.get(k)
    for L, SL in G["SL"].items():
        o = run_variant(d, "base", S=SL)
        for k in ("st", "R", "exit", "lev", "pnl"):
            row[f"L{L}_{k}"] = o.get(k)
    ts_list = G["ts"]
    for k in (1, 2, 4):
        bc = d["bar_close"] + k * TF_MS[d["timeframe"]]
        j = bisect.bisect_left(ts_list, bc)
        if j >= len(ts_list) or ts_list[j] - bc > 5 * MIN:
            continue
        bar = G["ss"][d["symbol"]][j][1].get(d["symbol"])
        if bar is None:
            continue
        o = run_variant(d, "base", i0=j, ref=bar.open, bar_close=bc)
        for kk in ("st", "R", "exit"):
            row[f"LATE{k}_{kk}"] = o.get(kk)
    return row


def chunk(ix):
    return [one(i) for i in ix]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("rb_dir")
    ap.add_argument("repo")
    ap.add_argument("out_csv")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    sys.path.insert(0, a.repo)
    sys.path.append(a.rb_dir)
    import analyze as A  # pipeline loaders (validated); unchanged
    from paperbot.config import Tier
    names = A.discover(a.export_dir)
    runs = [A.Run(a.export_dir, n) for n in names]
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
            SL[L] = S.__class__(**{**S.__dict__, "tiers": (Tier("best", m, (L,)), Tier("normal", m, (L,))),
                                   "min_margin_frac": min(0.2, m), "max_margin_frac": max(0.5, m)})
        rates, _ = A.infer_funding(run.trades, run.bars)
        ts_list, ss = A.build_steps(run.bars, rates)
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        # opposite-signal lists (signal_log, any status)
        sl = run.sig[run.sig["ref_price"].notna()].copy()
        opp_same, opp_high = {}, {}
        for r in sl.itertuples(index=False):
            rt = float(r.ref_time) if r.ref_time == r.ref_time else float("nan")
            tup = (int(r.bar_close), float(r.ref_price), rt)
            opp_same.setdefault((r.strategy, r.symbol, int(r.side), r.timeframe), []).append(tup)
            if r.timeframe in TFS:
                for tf in TFS[:TFS.index(r.timeframe) + 1]:
                    opp_high.setdefault((r.strategy, r.symbol, int(r.side), tf), []).append(tup)
        for D in (opp_same, opp_high):
            for k in D:
                D[k] = sorted(set(D[k]))
        sub = run.sig[run.sig["status"] == "SUBMITTED"]
        sigs = []
        for r in sub.itertuples(index=False):
            aid = f"{r.strategy}@{r.timeframe}"
            if r.timeframe not in TF_MS or acc["exits"].get(aid, "house") == "reel":
                continue
            atr, ref = A.fnum(r.atr), A.fnum(r.ref_price)
            if not (atr == atr and atr > 0 and ref == ref):
                continue
            d = {"sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe,
                 "strategy": r.strategy, "symbol": r.symbol, "side": int(r.side), "atr": atr, "ref_price": ref,
                 "ref_time": int(r.ref_time) if r.ref_time == r.ref_time else None,
                 "delay_ms": int(r.delay_ms) if r.delay_ms == r.delay_ms else None}
            ctx = strength.get(int(r.id))
            d["data"] = {"ctx": ctx} if ctx else {}
            sigs.append(d)
        if a.limit:
            sigs = sigs[:a.limit]
        G.clear()
        G.update(sigs=sigs, ss=ss, ts=ts_list, S=S, SL=SL, br=br, specs=specs, V=engine_cls(),
                 opp_same=opp_same, opp_high=opp_high)
        import multiprocessing as mp
        ix = list(range(len(sigs)))
        chunks = [ix[k::a.procs * 4] for k in range(a.procs * 4)]
        with mp.get_context("fork").Pool(a.procs) as pool:
            res = [x for p in pool.map(chunk, chunks) for x in p]
        R = pd.DataFrame(res).sort_values("sig_id")
        R.insert(0, "run", run.name)
        aid = R["strategy"] + "@" + R["timeframe"]
        R["kind"] = aid.map(acc["kind"]).fillna(aid.map(A.infer_kind))
        R["last_ts"] = ts_list[-1]
        parts.append(R)
        print(run.name, len(sigs), f"{time.time() - t0:.1f}s", flush=True)
    R = pd.concat(parts, ignore_index=True)
    R.to_csv(a.out_csv, index=False)
    print("rows", len(R))


if __name__ == "__main__":
    main()
