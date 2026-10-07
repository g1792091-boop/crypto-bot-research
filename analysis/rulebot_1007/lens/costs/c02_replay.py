#!/usr/bin/env python3
"""Every SUBMITTED signal of the runs with live_bars (v3b, v4), replayed alone through the repo's engine under
several EXECUTION assumptions (the signal, the 1m live bars, the ladder exits and the funding stay the same).

    python3 -I c02_replay.py <export_dir> <rb_analyze_dir> <repo> <ticks.csv> <exec_coin.csv> <out_csv> [procs]

Scenarios (leverage pinned to the base replay's leverage with obsshadows.SameLeveragePolicy, except ``base``):
  base        the live rules (taker 5 bp + 2 bp slippage both sides) = the pipeline's replay (parity checked)
  pin         base costs, pinned leverage (control: must equal base)
  zero        no fees, no slippage (the ladder's lock prices then carry no cost cushion): the gross edge
  fee         taker fees, no slippage
  real        taker fees + per-coin measured slippage: entry = mean order-book walk at the paper size
              (fill_costs slip_best, ref already = ask/bid), exit = mean real stop-market slip (d3_stop_slips)
  mk_touch    maker entry: post-only limit one tick inside the reference (= the other side of the spread), valid
              one bar of the signal's timeframe from the first full minute after the signal was ready, filled
              only when a later 1m bar trades THROUGH it; maker 2 bp, no entry slippage; stop kept at the
              original price; exits as base (taker + 2 bp)
  mk10/mk25   the same, limit 0.10 / 0.25 ATR better than the reference, stop kept at the original price
  mk25_shift  limit 0.25 ATR better, stop 2 ATR from the limit price (the nightly d3 'limit' shadow's definition)
  w25 / w30   initial stop 2.5 / 3 ATR (same leverage; no 15% / liquidation-buffer checks, as the d3 stopw shadows)
An unfilled limit order is a signal with no trade (contributes 0). Unresolved (open at the last bar) trades are
marked to the last close with exit costs (flag ``marked``).
"""
import bisect
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN = 60_000
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
G: dict = {}
SCEN = ["base", "pin", "zero_lad", "fee_lad", "real_lad", "zero", "fee", "real", "mk_fee_only", "real_bnb", "mk_touch",
        "mk10", "mk25", "mk25_shift", "w25", "w30"]


def setup(export_dir, rb_dir, repo):
    sys.path.insert(0, repo)
    sys.path.insert(0, rb_dir)
    import analyze as A  # noqa: E402  (read-only import of the validated pipeline)
    return A


def make_exec_engine():
    from dataclasses import replace  # noqa: F401
    from paperbot.engine import PaperEngine
    from paperbot.models import Position

    class ExecEngine(PaperEngine):
        """PaperEngine whose ENTRY uses its own slippage and fee rate (maker entries, measured slippage).
        A copy of PaperEngine._try_enter with only those two numbers changed."""
        entry_slip = None
        entry_fee = None
        exit_slip = None
        exit_fee = None

        def _close(self, price, ts, reason, maker):
            """PaperEngine._close with the exit's slippage / taker fee replaced (the ladder's lock prices and the
            sizing keep the settings' 14 bp round trip, so the price path stays the base one)."""
            p = self.position
            if not maker and self.exit_slip is not None:
                raw = price / (1 - p.side * self.s.slippage_frac)
                price = raw * (1 - p.side * self.exit_slip)
            gross = p.side * p.qty * (price - p.entry_price)
            if gross < -p.margin:
                self._liquidate(ts)
                return
            fee_rate = self.s.maker_fee if maker else (self.s.taker_fee if self.exit_fee is None else self.exit_fee)
            exit_fee = p.qty * price * fee_rate
            self.wallet += gross - exit_fee
            self._finish(price, ts, reason, exit_fee)

        def _try_enter(self, sig, bar):
            from dataclasses import replace as _rep
            side = sig.side
            raw = float(sig.meta.get("ref_price", bar.open))
            slip = self.s.slippage_frac if self.entry_slip is None else self.entry_slip
            fee_rate = self.s.taker_fee if self.entry_fee is None else self.entry_fee
            fill = raw * (1 + side * slip)
            if "stop_dist" in sig.meta:
                sig = _rep(sig, stop_price=raw - side * float(sig.meta["stop_dist"]))
            spec = self.specs.get(sig.symbol, {})
            dec = self.policy.size(self.wallet, sig, fill, self.brackets[sig.symbol], spec)
            if not dec.ok:
                self._record(sig, "REJECTED", "sizing", bar.open_time, reasons=dec.reasons, fill=fill)
                return False
            notional = dec.qty * fill
            fee = notional * fee_rate
            self.wallet -= fee
            tp = math.nan if self.s.tp_mode == "ladder" else self.policy.take_profit(sig, fill, dec)
            self.position = Position(
                signal=sig, symbol=sig.symbol, side=side, qty=dec.qty,
                entry_price=fill, entry_time=bar.open_time, leverage=dec.leverage,
                tier=dec.tier, margin=dec.margin, margin_initial=dec.margin,
                stop_price=sig.stop_price, tp_price=tp, liq_price=dec.liq_price,
                entry_fee=fee, mae_price=fill, mfe_price=fill, stop_initial=sig.stop_price)
            self._record(sig, "ENTERED", "ok", bar.open_time, tier=dec.tier, leverage=dec.leverage,
                         margin=dec.margin, fill=fill, downgrades=dec.reasons)
            return True

    return ExecEngine


def run_engine(S, sig, ss, i0, policy=None, entry_slip=None, entry_fee=None, exit_slip=None, exit_fee=None):
    E = G["ExecEngine"]
    e = E(S, G["brackets"], symbol_specs=G["specs"], book="lens", policy=policy)
    e.entry_slip, e.entry_fee, e.exit_slip, e.exit_fee = entry_slip, entry_fee, exit_slip, exit_fee
    e.submit(sig)
    for k in range(i0, len(ss)):
        ts, bars, fund = ss[k]
        e.step(bars, fund)
        if e.trades:
            t = e.trades[0]
            return {"status": "TRADED", "exit_reason": t.exit_reason, "leverage": t.leverage,
                    "entry_price": t.entry_price, "exit_price": t.exit_price, "stop_initial": t.stop_initial,
                    "qty": t.qty, "pnl": t.pnl,
                    "fees": t.fees, "funding": t.funding, "roe": t.roe, "entry_time": t.entry_time,
                    "exit_time": t.exit_time, "marked": 0}
        if e.position is None and not e.pending:
            return {"status": "REJECTED"}
    p = e.position
    if p is None:
        return {"status": "REJECTED"}
    last = e._last_mark.get(sig.symbol, p.entry_price)
    xs = S.slippage_frac if exit_slip is None else exit_slip
    xf = S.taker_fee if exit_fee is None else exit_fee
    px = last * (1 - p.side * xs)
    net = p.side * p.qty * (px - p.entry_price) - p.entry_fee - p.qty * px * xf - p.funding_paid
    return {"status": "TRADED", "exit_reason": "OPEN", "leverage": p.leverage, "entry_price": p.entry_price,
            "exit_price": px, "stop_initial": p.stop_initial, "qty": p.qty, "pnl": net,
            "fees": p.entry_fee + p.qty * px * xf,
            "funding": p.funding_paid, "roe": net / p.margin_initial, "entry_time": p.entry_time,
            "exit_time": ss[-1][0], "marked": 1}


def limit_fill(d, ss, i_start, limit):
    side = int(d["side"])
    until = d["bar_close"] + TF_MS[d["timeframe"]]
    sym = d["symbol"]
    for k in range(i_start, len(ss)):
        ts = ss[k][0]
        if ts >= until:
            break
        b = ss[k][1].get(sym)
        if b is None:
            continue
        if (b.low < limit) if side > 0 else (b.high > limit):
            return k
    return None


def sim_signal(i):
    from dataclasses import replace
    from paperbot.daily3 import make_signal
    from paperbot.obsshadows import SameLeveragePolicy
    d = G["sigs"][i]
    sym, side, atr, ref = d["symbol"], int(d["side"]), d["atr"], d["ref_price"]
    ss = G["ssteps"][sym]
    i0 = bisect.bisect_left(G["ts_list"], d["bar_close"])
    base_out = {k: d[k] for k in ("run", "sig_id", "bar_close", "timeframe", "strategy", "symbol", "side", "kind",
                                  "atr", "ref_price")}
    rows = []
    if i0 >= len(ss) or (G["ts_list"][i0] - d["bar_close"]) > 5 * MIN:
        return [dict(base_out, scenario="base", status="NO_BARS")]
    S = G["settings"]
    sig = make_signal(d)
    b = run_engine(S, sig, ss, i0)
    rows.append(dict(base_out, scenario="base", **b))
    if b.get("status") != "TRADED":
        return rows
    lev = int(b["leverage"])
    pol = SameLeveragePolicy(S, lev)
    from dataclasses import replace as rep
    S_zero = rep(S, taker_fee=0.0, maker_fee=0.0, slippage_frac=0.0)
    S_fee = rep(S, slippage_frac=0.0)
    ex = G["exec_coin"].get(sym, {})
    S_real = rep(S, slippage_frac=float(ex.get("exit_slip", S.slippage_frac)))
    rows.append(dict(base_out, scenario="pin", **run_engine(S, sig, ss, i0, policy=pol)))
    # ladder re-optimised for the cheaper world (lock prices follow the settings' round trip)
    rows.append(dict(base_out, scenario="zero_lad", **run_engine(S_zero, sig, ss, i0, policy=pol)))
    rows.append(dict(base_out, scenario="fee_lad", **run_engine(S_fee, sig, ss, i0, policy=pol)))
    rows.append(dict(base_out, scenario="real_lad", **run_engine(S_real, sig, ss, i0, policy=pol,
                                                                 entry_slip=float(ex.get("entry_slip", S.slippage_frac)))))
    # the same price path as base (the ladder keeps the 14 bp round trip), only the charged costs differ
    rows.append(dict(base_out, scenario="zero", **run_engine(S, sig, ss, i0, policy=pol, entry_slip=0.0, entry_fee=0.0,
                                                             exit_slip=0.0, exit_fee=0.0)))
    rows.append(dict(base_out, scenario="fee", **run_engine(S, sig, ss, i0, policy=pol, entry_slip=0.0,
                                                            exit_slip=0.0)))
    rows.append(dict(base_out, scenario="real", **run_engine(S, sig, ss, i0, policy=pol,
                                                             entry_slip=float(ex.get("entry_slip", S.slippage_frac)),
                                                             exit_slip=float(ex.get("exit_slip", S.slippage_frac)))))
    # maker entry at the reference price itself (no price improvement, only the fee/slip difference), and the
    # BNB-discount taker (4.5 bp) with the real slippage
    rows.append(dict(base_out, scenario="mk_fee_only", **run_engine(S, sig, ss, i0, policy=pol, entry_slip=0.0,
                                                                    entry_fee=S.maker_fee)))
    rows.append(dict(base_out, scenario="real_bnb", **run_engine(S, sig, ss, i0, policy=pol,
                                                                 entry_slip=float(ex.get("entry_slip", S.slippage_frac)),
                                                                 entry_fee=0.00045, exit_fee=0.00045,
                                                                 exit_slip=float(ex.get("exit_slip", S.slippage_frac)))))
    # maker entries
    orig_stop = ref - side * 2.0 * atr
    tick = G["ticks"].get(sym, 0.0)
    i_start = i0 + 1          # the first full minute after the signal was ready (ref_time is 10-30 s into bar i0)
    for name, off_px, keep in (("mk_touch", tick, True), ("mk10", 0.10 * atr, True), ("mk25", 0.25 * atr, True),
                               ("mk25_shift", 0.25 * atr, False)):
        limit = ref - side * off_px
        k = limit_fill(d, ss, i_start, limit)
        if k is None:
            rows.append(dict(base_out, scenario=name, status="UNFILLED", limit=limit))
            continue
        d2 = dict(d)
        data = dict(d.get("data") or {})
        if keep:
            data["stop_dist"] = abs(limit - orig_stop)
        d2["data"] = data
        sig2 = replace(make_signal(d2, ref=limit), ts=ss[k][0] - 1)
        r = run_engine(S, sig2, ss, k, policy=pol, entry_slip=0.0, entry_fee=S.maker_fee)
        rows.append(dict(base_out, scenario=name, limit=limit, fill_delay_min=(ss[k][0] - d["bar_close"]) / MIN, **r))
    for name, k_atr in (("w25", 2.5), ("w30", 3.0)):
        sig3 = make_signal(d, stop_atr=k_atr)
        rows.append(dict(base_out, scenario=name, **run_engine(S, sig3, ss, i0, policy=pol)))
    return rows


def chunk(idx):
    out = []
    for i in idx:
        out.extend(sim_signal(i))
    return out


def main():
    export_dir, rb_dir, repo, ticks_csv, exec_csv, out_csv = sys.argv[1:7]
    procs = int(sys.argv[7]) if len(sys.argv) > 7 else 4
    A = setup(export_dir, rb_dir, repo)
    G["ExecEngine"] = make_exec_engine()
    tk = pd.read_csv(ticks_csv)
    ticks = dict(zip(tk["symbol"], tk["tick"]))
    ec = pd.read_csv(exec_csv)
    exec_coin = {r.symbol: {"entry_slip": r.entry_slip_bps / 1e4, "exit_slip": r.exit_slip_bps / 1e4}
                 for r in ec.itertuples()}
    allrows = []
    for name in ("run-20261005T183457Z", "current"):
        run = A.Run(export_dir, name)
        rule, taker = A.detect_rule(run), A.implied_taker(run)
        S = A.replay_settings(rule, taker)
        brackets, _ = A.make_brackets(None)
        specs = A.infer_specs(run.trades)
        rates, _ = A.infer_funding(run.trades, run.bars)
        ts_list, ssteps = A.build_steps(run.bars, rates)
        strength = A.load_ctx_strength(run.ctx_path)
        acc = run.accounts.set_index("account_id")
        sub = run.sig[run.sig["status"] == "SUBMITTED"]
        sigs = []
        for r in sub.itertuples(index=False):
            aid = f"{r.strategy}@{r.timeframe}"
            if acc["exits"].get(aid, "house") == "reel" or r.timeframe == "5m":
                continue
            atr, ref = A.fnum(r.atr), A.fnum(r.ref_price)
            if not (atr == atr and atr > 0 and ref == ref):
                continue
            kind = acc["kind"].get(aid, A.infer_kind(aid))
            d = {"run": name, "sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe,
                 "strategy": r.strategy, "symbol": r.symbol, "side": int(r.side), "atr": atr, "ref_price": ref,
                 "ref_time": int(r.ref_time) if r.ref_time == r.ref_time else None,
                 "delay_ms": int(r.delay_ms) if r.delay_ms == r.delay_ms else None, "kind": kind}
            ctx = strength.get(int(r.id))
            d["data"] = {"ctx": ctx} if ctx else {}
            sigs.append(d)
        G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, settings=S, brackets=brackets, specs=specs,
                 ticks=ticks, exec_coin=exec_coin)
        t0 = time.time()
        idx = list(range(len(sigs)))
        import multiprocessing as mp
        chunks = [idx[k::procs * 4] for k in range(procs * 4)]
        with mp.get_context("fork").Pool(procs) as pool:
            parts = pool.map(chunk, chunks)
        rows = [x for p in parts for x in p]
        print(name, rule, taker, "signals", len(sigs), "rows", len(rows), "s", round(time.time() - t0, 1), flush=True)
        allrows.extend(rows)
    R = pd.DataFrame(allrows)
    R.to_csv(out_csv, index=False)
    print("written", out_csv, len(R))


if __name__ == "__main__":
    main()
