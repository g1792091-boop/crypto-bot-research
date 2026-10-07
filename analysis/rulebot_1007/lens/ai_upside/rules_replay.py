#!/usr/bin/env python3
"""Every SUBMITTED signal (v3b, v4) alone through the repo's PaperEngine on live_bars, base + the pre-declared
discretionary-proxy rules of PREREG.md, plus a per-signal path record (time to +xR, MAE before +0.5R, unrealized R
at k timeframe bars, max MFE and when).

    python3 -I rules_replay.py <export_dir> <rb_analyze_dir> <repo> <out_dir> [--procs 4]

Read-only on everything except <out_dir>. Imports analyze.py (rb_analyze) for its loaders, unchanged.
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
import math  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN = 60_000
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN, "1d": 1440 * MIN}
TF_ORDER = ["5m", "15m", "30m", "1h", "4h", "1d"]
RULES = ["base", "BE05", "BE10", "NP4", "NP8", "TP1", "CUT05", "OPP", "OPPH"]
THR = [0.3, 0.5, 1.0, 1.5, 2.0]
KBARS = [1, 2, 4, 8]

_G: dict = {}


def make_engine_cls():
    from paperbot.engine import PaperEngine
    from paperbot.ladder import roe_price, tighten

    class RuleEngine(PaperEngine):
        """PaperEngine + one discretionary-proxy rule, applied outside the engine's own logic (engine.py unchanged)."""

        def setup(self, rule: str, tf_ms: int, opp: list | None, record: bool):
            self.rule = rule
            self.tf_ms = tf_ms
            self.opp = opp or []          # [(bar_close, ref_price, ref_time)] sorted, opposite side, same symbol
            self.record = record
            self.rec = {}
            self._had_pos = False

        def step(self, bars, funding=None):
            p = self.position
            if p is not None and self.rule in ("OPP", "OPPH") and self.opp:
                ts0 = min(b.open_time for b in bars.values()) if bars else None
                k = bisect.bisect_right([o[0] for o in self.opp], p.signal.ts + 1)   # strictly after the entry signal
                if k < len(self.opp) and ts0 is not None and self.opp[k][0] <= ts0:
                    bc, ref, rt = self.opp[k]
                    self._close(ref * (1 - p.side * self.s.slippage_frac), int(rt) if rt == rt else ts0, "OPP",
                                maker=False)
            had = self.position is not None
            super().step(bars, funding)
            p = self.position
            if p is None:
                return
            entry_bar = not had
            bar = bars.get(p.symbol)
            if bar is None:
                return
            side = p.side
            dist = abs(p.entry_price - p.stop_initial)
            if not dist:
                return
            mfe_R = side * (p.mfe_price - p.entry_price) / dist
            t_rel = bar.close_time + 1 - p.entry_time
            if self.record:
                r = self.rec
                r.setdefault("mfe_path_max", -9)
                if mfe_R > r["mfe_path_max"] + 1e-12:
                    r["mfe_path_max"] = mfe_R
                    r["t_max_mfe_min"] = t_rel / MIN
                for th in THR:
                    if mfe_R >= th and f"t_mfe{th}_min" not in r:
                        r[f"t_mfe{th}_min"] = t_rel / MIN
                        r[f"mae_before_{th}_R"] = side * (p.mae_price - p.entry_price) / dist
                cur = side * (bar.close - p.entry_price) / dist
                for kb in KBARS:
                    if f"unr_{kb}bar_R" not in r and t_rel >= kb * self.tf_ms:
                        r[f"unr_{kb}bar_R"] = cur
                        r[f"mfe_{kb}bar_R"] = mfe_R
                        r[f"lock_{kb}bar"] = p.lock_roe is not None
                if p.lock_roe is not None and "t_lock_min" not in r:
                    r["t_lock_min"] = t_rel / MIN
            rule = self.rule
            rt = self.s.round_trip_cost
            if entry_bar:
                if rule == "TP1":
                    ref = p.signal.meta.get("ref_price")
                    ref = float(ref) if ref is not None else p.entry_price
                    p.tp_price = ref + side * 1.0 * abs(ref - p.stop_initial)
                elif rule == "CUT05":
                    p.stop_price = tighten(side, p.stop_price, p.entry_price - side * 0.5 * dist)
                return
            if rule in ("BE05", "BE10"):
                th = 0.5 if rule == "BE05" else 1.0
                if mfe_R >= th:
                    fund = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
                    be = roe_price(side, p.entry_price, p.leverage, 0.0, rt, fund)
                    p.stop_price = tighten(side, p.stop_price, be)
            elif rule in ("NP4", "NP8"):
                nb = 4 if rule == "NP4" else 8
                if p.lock_roe is None and mfe_R < 0.3 and t_rel >= nb * self.tf_ms:
                    self._close_market(bar.close, bar.close_time, rule)

    return RuleEngine


def run_one(d: dict, rule: str, record: bool) -> dict:
    from paperbot.daily3 import make_signal
    G = _G
    sym = d["symbol"]
    ss = G["ssteps"].get(sym)
    ts_list = G["ts_list"]
    i0 = bisect.bisect_left(ts_list, d["bar_close"])
    out = {}
    if ss is None or i0 >= len(ts_list) or (ts_list[i0] - d["bar_close"]) / MIN > 5:
        return {"status": "NO_BARS"}
    sig = make_signal(d)
    S = G["settings"]
    E = G["cls"](S, G["brackets"], symbol_specs=G["specs"], book="rule")
    opp = None
    if rule in ("OPP", "OPPH"):
        opp = G["opp"].get((d["strategy"], sym, -int(d["side"]), d["timeframe"] if rule == "OPP" else "H" + d["timeframe"]), [])
    E.setup(rule, TF_MS[d["timeframe"]], opp, record)
    E.submit(sig)
    resolved = False
    tr = None
    for ts, bars, funding in ss[i0:]:
        E.step({s: b for s, b in bars.items() if s in G["brackets"]}, funding)
        if E.trades:
            tr = E.trades[0]
            resolved = True
            break
        if E.position is None and not E.pending:
            resolved = True
            break
    if tr is not None:
        dist = abs(tr.entry_price - tr.stop_initial)
        out.update(status="TRADED", exit_reason=tr.exit_reason, R=tr.pnl / (tr.qty * dist), roe=tr.roe, pnl=tr.pnl,
                   leverage=tr.leverage, entry_time=tr.entry_time, exit_time=tr.exit_time,
                   hold_min=(tr.exit_time - tr.entry_time) / MIN,
                   mfe_R=tr.side * (tr.mfe_price - tr.entry_price) / dist,
                   mae_R=tr.side * (tr.mae_price - tr.entry_price) / dist,
                   cost_R=(tr.fees + tr.funding) / (tr.qty * dist), qty=tr.qty, entry_price=tr.entry_price,
                   stop_initial=tr.stop_initial)
    elif resolved:
        out["status"] = "REJECTED"
    else:
        p = E.position
        out["status"] = "UNRESOLVED"
        if p is not None:
            last = E._last_mark.get(sym, p.entry_price)
            px = last * (1 - p.side * S.slippage_frac)
            net = p.side * p.qty * (px - p.entry_price) - p.entry_fee - p.qty * px * S.taker_fee - p.funding_paid
            dist = abs(p.entry_price - p.stop_initial)
            out.update(R=net / (p.qty * dist), pnl=net, roe=net / p.margin_initial, leverage=p.leverage,
                       entry_time=p.entry_time, exit_time=ts_list[-1] + MIN - 1,
                       hold_min=(ts_list[-1] + MIN - p.entry_time) / MIN,
                       mfe_R=p.side * (p.mfe_price - p.entry_price) / dist,
                       mae_R=p.side * (p.mae_price - p.entry_price) / dist, qty=p.qty, entry_price=p.entry_price,
                       stop_initial=p.stop_initial, exit_reason="OPEN_END")
    if record:
        out.update({f"p_{k}": v for k, v in E.rec.items()})
    return out


def do_signal(i: int) -> dict:
    d = _G["sigs"][i]
    row = {k: d[k] for k in ("sig_id", "bar_close", "timeframe", "strategy", "symbol", "side", "atr", "ref_price")}
    for rule in RULES:
        o = run_one(d, rule, record=(rule == "base"))
        if rule == "base":
            for k, v in o.items():
                row[k if k.startswith("p_") else f"base_{k}"] = v
        else:
            for k in ("status", "R", "exit_reason", "hold_min", "pnl"):
                row[f"{rule}_{k}"] = o.get(k)
    return row


def do_chunk(idx):
    return [do_signal(i) for i in idx]


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
    import analyze as A  # noqa: E402  (rb_analyze/analyze.py, imported unchanged)
    os.makedirs(a.out_dir, exist_ok=True)
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
        rule = A.detect_rule(run)
        taker = A.implied_taker(run)
        S = A.replay_settings(rule, taker)
        rates, finfo = A.infer_funding(run.trades, run.bars)
        ts_list, ssteps = A.build_steps(run.bars, rates)
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        # opposite-signal index from the whole signal log (any status)
        sg = run.sig.copy()
        opp = {}
        for r in sg.itertuples(index=False):
            if not (r.ref_price == r.ref_price):
                continue
            tup = (int(r.bar_close), float(r.ref_price), float(r.ref_time) if r.ref_time == r.ref_time else float("nan"))
            opp.setdefault((r.strategy, r.symbol, int(r.side), r.timeframe), []).append(tup)
            ti = TF_ORDER.index(r.timeframe) if r.timeframe in TF_ORDER else 99
            for tf in TF_ORDER[:ti + 1]:      # a signal on tf X counts as "same or higher" for every tf <= X
                opp.setdefault((r.strategy, r.symbol, int(r.side), "H" + tf), []).append(tup)
        for k in opp:
            opp[k] = sorted(set(opp[k]))
        sub = run.sig[run.sig["status"] == "SUBMITTED"]
        sigs = []
        for r in sub.itertuples(index=False):
            aid = f"{r.strategy}@{r.timeframe}"
            if acc["exits"].get(aid, "house") == "reel":
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
        _G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, settings=S, brackets=brackets, specs=specs,
                  opp=opp, cls=make_engine_cls())
        idx = list(range(len(sigs)))
        import multiprocessing as mp
        chunks = [idx[k::a.procs * 4] for k in range(a.procs * 4)]
        with mp.get_context("fork").Pool(a.procs) as pool:
            res = [x for p in pool.map(do_chunk, chunks) for x in p]
        R = pd.DataFrame(res).sort_values("sig_id")
        R.insert(0, "run", run.name)
        R["account_id"] = R["strategy"] + "@" + R["timeframe"]
        R["kind"] = R["account_id"].map(acc["kind"]).fillna(R["account_id"].map(A.infer_kind))
        R["last_ts"] = ts_list[-1]
        parts.append(R)
        print(f"{run.name}: {len(sigs)} signals x {len(RULES)} rules in {time.time() - t0:.1f}s", flush=True)
    R = pd.concat(parts, ignore_index=True)
    R.to_csv(os.path.join(a.out_dir, "rules_signals.csv"), index=False)
    print("wrote", len(R))


if __name__ == "__main__":
    main()
