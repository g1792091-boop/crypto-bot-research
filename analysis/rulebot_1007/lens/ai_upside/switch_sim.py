#!/usr/bin/env python3
"""Account-level re-simulation of each account's own SUBMITTED signal stream through the repo's PaperEngine on
live_bars (v3b, v4), base (parity with the real account) and the pre-declared switching policies of PREREG.md.

    python3 -I switch_sim.py <export_dir> <rb_analyze_dir> <repo> <out_dir> [--procs 4]
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
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
POLICIES = ["base", "SW_ANY", "SW_UNDER", "SW_STALE", "SW_OPP"]
_G: dict = {}


def make_cls():
    from paperbot.engine import PaperEngine

    class SwitchEngine(PaperEngine):
        def setup(self, pol: str):
            self.pol = pol
            self.n_switch = 0
            self.switch_log = []

        def _should(self, p, ready, bars) -> bool:
            if self.pol == "SW_ANY":
                return True
            hb = bars.get(p.symbol)
            if hb is None:
                return False
            if self.pol == "SW_UNDER":
                px = hb.open * (1 - p.side * self.s.slippage_frac)
                net = p.side * p.qty * (px - p.entry_price) - p.entry_fee - p.qty * px * self.s.taker_fee - p.funding_paid
                return net < 0
            if self.pol == "SW_STALE":
                dist = abs(p.entry_price - p.stop_initial)
                mfe = p.side * (p.mfe_price - p.entry_price) / dist if dist else 0.0
                return (hb.open_time - p.entry_time) >= 4 * TF_MS[p.signal.timeframe] and mfe < 0.3
            if self.pol == "SW_OPP":
                return any(s.symbol == p.symbol and s.side == -p.side for s in ready)
            return False

        def _handle_entries(self, bars):
            p = self.position
            if p is not None and self.pending and self.pol != "base" and not self.halted:
                ready = [s for s in self.pending if bars.get(s.symbol) is not None and bars[s.symbol].open_time >= s.ts]
                if ready and self._should(p, ready, bars):
                    hb = bars.get(p.symbol)
                    if hb is not None:
                        self._close_market(hb.open, hb.open_time, "SWITCH")
                        self.n_switch += 1
            return super()._handle_entries(bars)

    return SwitchEngine


def sim_account(aid: str) -> list[dict]:
    from paperbot.daily3 import make_signal
    G = _G
    sigs = G["by_acc"][aid]
    steps, ts_list = G["steps"], G["ts_list"]
    by_step: dict = {}
    for d in sigs:
        i0 = bisect.bisect_left(ts_list, d["bar_close"])
        if i0 < len(ts_list) and (ts_list[i0] - d["bar_close"]) <= 5 * MIN:
            by_step.setdefault(i0, []).append(make_signal(d))
    out = []
    first = min(by_step) if by_step else len(ts_list)
    for pol in POLICIES:
        E = G["cls"](G["settings"], G["brackets"], symbol_specs=G["specs"], book=pol)
        E.setup(pol)
        for k in range(first, len(steps)):
            ts, bars, fund = steps[k]
            for s in by_step.get(k, []):
                E.submit(s)
            E.step({s: b for s, b in bars.items() if s in G["brackets"]}, fund)
        eq = E.equity()
        tr = E.trades
        out.append({"account_id": aid, "policy": pol, "final_equity": eq, "n_trades": len(tr),
                    "closed_pnl": sum(t.pnl for t in tr), "open_at_end": E.position is not None,
                    "n_switch": E.n_switch, "bust": E.bust,
                    "sum_R": sum(t.pnl / (t.qty * abs(t.entry_price - t.stop_initial)) for t in tr
                                 if t.stop_initial and t.entry_price != t.stop_initial),
                    "n_switch_exits": sum(1 for t in tr if t.exit_reason == "SWITCH"),
                    "R_switch_exits": sum(t.pnl / (t.qty * abs(t.entry_price - t.stop_initial)) for t in tr
                                          if t.exit_reason == "SWITCH")})
    return out


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
    from paperbot.daily3 import _bar_of  # noqa: E402
    names = A.discover(a.export_dir)
    runs = [A.Run(a.export_dir, n) for n in names]
    allT = pd.concat([r.trades for r in runs if r.trades is not None and len(r.trades)], ignore_index=True)
    specs = A.infer_specs(allT)
    brackets, _ = A.make_brackets(None)
    rows = []
    for run in runs:
        if run.bars is None or not len(run.bars):
            continue
        t0 = time.time()
        S = A.replay_settings(A.detect_rule(run), A.implied_taker(run))
        rates, _ = A.infer_funding(run.trades, run.bars)
        bars = run.bars.sort_values(["ts", "symbol"])
        cols = list(bars.columns)
        by_ts: dict = {}
        for row in bars.itertuples(index=False):
            r = dict(zip(cols, row))
            for k in ("mark_open", "mark_high", "mark_low", "mark_close", "volume", "close_time"):
                v = r.get(k)
                if v is not None and isinstance(v, float) and v != v:
                    r[k] = None
            by_ts.setdefault(int(r["ts"]), {})[r["symbol"]] = _bar_of(r)
        ts_list = sorted(by_ts)
        steps = [(t, by_ts[t], dict(rates.get(t, {}))) for t in ts_list]
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        sub = run.sig[run.sig["status"] == "SUBMITTED"]
        by_acc: dict = {}
        for r in sub.itertuples(index=False):
            aid = f"{r.strategy}@{r.timeframe}"
            if acc["exits"].get(aid, "house") == "reel" or r.timeframe == "5m":
                continue
            d = {"sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy,
                 "symbol": r.symbol, "side": int(r.side), "atr": A.fnum(r.atr), "ref_price": A.fnum(r.ref_price),
                 "ref_time": int(r.ref_time) if r.ref_time == r.ref_time else None,
                 "delay_ms": int(r.delay_ms) if r.delay_ms == r.delay_ms else None}
            if not (d["atr"] == d["atr"] and d["atr"] > 0 and d["ref_price"] == d["ref_price"]):
                continue
            ctx = strength.get(int(r.id))
            d["data"] = {"ctx": ctx} if ctx else {}
            by_acc.setdefault(aid, []).append(d)
        _G.clear()
        _G.update(by_acc=by_acc, steps=steps, ts_list=ts_list, settings=S, brackets=brackets, specs=specs,
                  cls=make_cls())
        aids = sorted(by_acc)
        import multiprocessing as mp
        with mp.get_context("fork").Pool(a.procs) as pool:
            res = [x for p in pool.map(sim_account, aids, chunksize=2) for x in p]
        D = pd.DataFrame(res)
        D.insert(0, "run", run.name)
        D["kind"] = D["account_id"].map(acc["kind"]).fillna(D["account_id"].map(A.infer_kind))
        D["timeframe"] = D["account_id"].str.split("@").str[-1]
        t = run.trades
        real = t.groupby("account_id").agg(real_trades=("pnl", "size"), real_closed_pnl=("pnl", "sum"))
        D = D.merge(real, left_on="account_id", right_index=True, how="left")
        rows.append(D)
        print(f"{run.name}: {len(aids)} accounts in {time.time() - t0:.1f}s", flush=True)
    D = pd.concat(rows, ignore_index=True)
    D.to_csv(os.path.join(a.out_dir, "switch_accounts.csv"), index=False)
    b = D[D["policy"] == "base"]
    print("parity base vs real: accounts", len(b), "same n_trades", int((b["n_trades"] == b["real_trades"].fillna(0)).sum()),
          "max |closed pnl diff|", float((b["closed_pnl"] - b["real_closed_pnl"].fillna(0)).abs().max()))


if __name__ == "__main__":
    main()
