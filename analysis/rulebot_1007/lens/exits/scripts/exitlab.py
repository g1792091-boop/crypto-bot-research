#!/usr/bin/env python3
"""Exit / stop / leverage what-ifs for every SUBMITTED house-exit signal of the runs that have live_bars.

    python3 -I exitlab.py <export_dir> <out_csv> [--repo REPO] [--procs 4] [--runs run-20261005T183457Z,current]
                          [--analyze /path/to/rb_analyze/analyze.py] [--no-flip] [--limit N]

Every signal is run ALONE on a fresh $5,000 account through the repo's own PaperEngine (imported, never modified)
on the run's live_bars (1m last + mark). The v3b run's bars are EXTENDED with the v4 run's bars (v3b ended 10/06 03:31
KST, v4 starts 03:35), so v3b signals get >= 36 h of horizon. A position still open at the last bar is marked to the
last close with exit costs (status OPEN_END), so every variant is evaluated on the same signal set (no outcome-based
selection; the mark is an unbiased estimate of the final value if prices are a martingale).

Variants: the obsshadows ones (re-implemented on the same engine calls: lock15/20/30, timestop, lev10, lev20m20 ...,
stopw*, tp*R, ladder_cap2R) plus custom exit rules on an engine subclass (XEngine) that only overrides the lock
raise: ROE-ladder geometry at another leverage at the SAME size (geoL), lock updates only at the timeframe's bar
close (*_bar), R-unit ladders (RL_arm_lock_step), breakeven moves (be*), time stops and max holds. All custom exits
use the base trade's leverage and margin share (SameLeveragePolicy): same qty as the base, only the exit differs.

Helpers copied from rb_analyze/analyze.py (Run loading, funding inference, steps, brackets, specs, settings).
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import math
import os
import site
import sys
import time

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN, HOUR = 60_000, 3_600_000
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
EQ0 = 5000.0
INFERRED_BRACKETS = {
    "BTCUSDT": [(1e12, 50, 0.004, 0.0)],
    "ETHUSDT": [(1e12, 50, 0.004, 0.0)],
    "SOLUSDT": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGEUSDT": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCHUSDT": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTCUSDT": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}

# ----------------------------------------------------------------------------------------------- variants
# kind: house (engine as is, maybe other settings / policy), tp (run_alone_tp-like), x (XEngine custom rule)
VARIANTS: dict[str, dict] = {
    "base": {"kind": "house"},
    "lock15": {"kind": "house", "lock": 0.15},
    "lock20": {"kind": "house", "lock": 0.20},
    "lock30": {"kind": "house", "lock": 0.30},
    "timestop": {"kind": "house", "time": "house"},
    "lev10": {"kind": "house", "levvar": "lev10"},
    "lev20m20": {"kind": "house", "levvar": "lev20m20"},
    "lev30m30": {"kind": "house", "levvar": "lev30m30"},
    "lev40m40": {"kind": "house", "levvar": "lev40m40"},
    "lev50m50": {"kind": "house", "levvar": "lev50m50"},
    "stopw1.5": {"kind": "house", "stopw": 1.5},
    "stopw2.5": {"kind": "house", "stopw": 2.5},
    "stopw3": {"kind": "house", "stopw": 3.0},
    "tp1R": {"kind": "tp", "k": 1.0, "ladder": False},
    "tp1.5R": {"kind": "tp", "k": 1.5, "ladder": False},
    "tp2R": {"kind": "tp", "k": 2.0, "ladder": False},
    "tp3R": {"kind": "tp", "k": 3.0, "ladder": False},
    "ladder_cap2R": {"kind": "tp", "k": 2.0, "ladder": True},
    # ROE-ladder geometry of another leverage at the SAME size (isolates the exit from sizing / liquidation)
    "geo10": {"kind": "x", "ladder": ("geo", 10)},
    "geo20": {"kind": "x", "ladder": ("geo", 20)},
    "geo50": {"kind": "x", "ladder": ("geo", 50)},
    # lock raised only when the timeframe's bar closes (AI design 3-4), effective from the next minute
    "base_bar": {"kind": "x", "ladder": ("roe",), "bar_only": True},
    "geo20_bar": {"kind": "x", "ladder": ("geo", 20), "bar_only": True},
    # R-unit ladders: arm when MFE >= arm R, lock lockR, then +step R per step R of MFE (gross price R of the 2ATR dist)
    "RL0.5_0.25": {"kind": "x", "ladder": ("R", 0.5, 0.25, 0.25)},
    "RL1_0.5": {"kind": "x", "ladder": ("R", 1.0, 0.5, 0.5)},
    "RL1_0.75": {"kind": "x", "ladder": ("R", 1.0, 0.75, 0.25)},
    "RL1.5_1": {"kind": "x", "ladder": ("R", 1.5, 1.0, 0.5)},
    "RL2_1": {"kind": "x", "ladder": ("R", 2.0, 1.0, 0.5)},
    "RL1_0.5_bar": {"kind": "x", "ladder": ("R", 1.0, 0.5, 0.5), "bar_only": True},
    "RL1.5_1_bar": {"kind": "x", "ladder": ("R", 1.5, 1.0, 0.5), "bar_only": True},
    # breakeven (stop to the net-zero price once MFE >= trigger R) with a fixed take-profit, no ladder
    "be1_tp1.5": {"kind": "tp", "k": 1.5, "ladder": False, "be": 1.0},
    "be1_tp2": {"kind": "tp", "k": 2.0, "ladder": False, "be": 1.0},
    "be1_tp3": {"kind": "tp", "k": 3.0, "ladder": False, "be": 1.0},
    "be0.5_tp1": {"kind": "tp", "k": 1.0, "ladder": False, "be": 0.5},
    "be1_RL1.5_1": {"kind": "x", "ladder": ("R", 1.5, 1.0, 0.5), "be": 1.0},
    # time stops: house = TIME_STOP_BARS bars and the lock never armed; neg = at that bar if unrealized R < 0;
    # max = market exit at 2 x TIME_STOP_BARS bars whatever happens (house ladder otherwise)
    "time_neg": {"kind": "house", "time": "neg"},
    "time_max2x": {"kind": "house", "time": "max2x"},
    "tp1R_max2x": {"kind": "tp", "k": 1.0, "ladder": False, "time": "max2x"},
    "tp2R_max2x": {"kind": "tp", "k": 2.0, "ladder": False, "time": "max2x"},
}
TIME_STOP_BARS = {"5m": 14, "15m": 12, "30m": 10, "1h": 8, "4h": 6}

_G: dict = {}


def jload(s):
    if isinstance(s, dict):
        return s
    try:
        v = json.loads(s) if isinstance(s, str) and s else {}
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def infer_kind(aid: str) -> str:
    s = aid.split("@")[0]
    if s.startswith("RANDOM_"):
        return "random"
    if s.startswith("REEL"):
        return "reel"
    if s[:1] == "F" and "_" in s and s.split("_")[0][1:].isdigit():
        return "ds200"
    return "strategy"


def read(path):
    return pd.read_csv(path) if os.path.exists(path) else None


def load_ctx_strength(path: str) -> dict:
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ctx = d.get("ctx")
            if isinstance(ctx, dict) and "strength" in ctx:
                out[int(d.get("id"))] = {"strength": ctx["strength"]}
    return out


def implied_taker(t) -> float:
    g = t[t["exit_reason"].isin(["SL", "LOCK", "TIME"])]
    v = (g["fees"] / (g["qty"] * (g["entry_price"] + g["exit_price"]))).median()
    return float(round(v, 7)) if v == v else 0.0005


def infer_specs(trades) -> dict:
    out = {}
    for s, g in trades.groupby("symbol"):
        q = g["qty"].to_numpy(float)
        step = 0.0
        for k in range(-2, 9):
            if np.all(np.abs(q * 10.0 ** k - np.round(q * 10.0 ** k)) < 1e-6 * np.maximum(1, q * 10.0 ** k)):
                step = 10.0 ** -k
                break
        out[s] = {"qty_step": step, "min_notional": 5.0}
    return out


def infer_funding(trades, bars, period_h: int = 8) -> dict:
    """analyze.infer_funding (copied): {ts: {symbol: rate}} solved from the trades' recorded funding."""
    P = period_h * HOUR
    mk = {}
    for r in bars.itertuples(index=False):
        m = r.mark_open if r.mark_open == r.mark_open else r.open
        mk[(int(r.ts), r.symbol)] = float(m)
    f = trades[trades["funding"] != 0]
    items = []
    for r in f.itertuples(index=False):
        fts = [x for x in range((int(r.entry_time) // P + 1) * P, int(r.exit_time) + 1, P) if x > r.entry_time]
        if fts:
            items.append((r.symbol, int(r.side), float(r.qty), float(r.funding), fts))
    known: dict = {}
    for _ in range(4):
        cand = collections.defaultdict(list)
        for sym, side, qty, fund, fts in items:
            unk = [ft for ft in fts if (ft, sym) not in known]
            if len(unk) != 1 or (unk[0], sym) not in mk:
                continue
            rest = sum(side * qty * mk.get((ft, sym), np.nan) * known[(ft, sym)] for ft in fts if ft != unk[0])
            cand[(unk[0], sym)].append((fund - rest) / (side * qty * mk[(unk[0], sym)]))
        if not cand:
            break
        for k, v in cand.items():
            known[k] = float(np.median(v))
    rates: dict = {}
    for (ft, sym), rate in known.items():
        if rate == rate:
            rates.setdefault(ft, {})[sym] = rate
    return rates


def build_steps(bars, funding):
    from paperbot.daily3 import _bar_of
    from paperbot.obsshadows import symbol_steps
    bars = bars.sort_values(["ts", "symbol"])
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
    steps = [(t, by_ts[t], dict(funding.get(t, {}))) for t in ts_list]
    syms = sorted(bars["symbol"].unique())
    return ts_list, {s: symbol_steps(steps, s) for s in syms}


def make_brackets():
    from paperbot.margin import BracketTier, Brackets
    return {s: Brackets([BracketTier(*t) for t in tiers]) for s, tiers in INFERRED_BRACKETS.items()}


# ----------------------------------------------------------------------------------------------- engine subclass
def make_xengine():
    from paperbot.engine import PaperEngine
    from paperbot.ladder import net_roe, roe_price, tighten

    class XEngine(PaperEngine):
        """PaperEngine whose lock raise follows ``xr`` (only _raise_lock and step are overridden)."""

        def __init__(self, *a, xr=None, tf_ms=None, **k):
            super().__init__(*a, **k)
            self.xr = xr or {}
            self.tf_ms = tf_ms
            self._cur_close = None

        def step(self, bars, funding=None):
            self._cur_close = max(b.close_time for b in bars.values()) if bars else None
            super().step(bars, funding)

        def _raise_lock(self, p):
            xr = self.xr
            if xr.get("bar_only") and self._cur_close is not None and (self._cur_close + 1) % self.tf_ms != 0:
                return
            fund = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
            rt = self.s.round_trip_cost
            dist = abs(p.entry_price - p.stop_initial)
            mfe_R = p.side * (p.mfe_price - p.entry_price) / dist if dist else 0.0
            cand = None
            lad = xr.get("ladder", ("roe",))
            if lad[0] in ("roe", "geo"):
                L = p.leverage if lad[0] == "roe" else lad[1]
                best = net_roe(p.side, p.entry_price, p.mfe_price, L, rt, fund)
                lock = self.s.ladder.lock_for(best)
                if lock is not None and (p.lock_roe is None or lock > p.lock_roe + 1e-12):
                    cand = roe_price(p.side, p.entry_price, L, lock, rt, fund)
                    p.lock_roe = lock
            elif lad[0] == "R":
                arm, lock0, stp = lad[1], lad[2], lad[3]
                if mfe_R >= arm - 1e-12:
                    lockR = lock0 + stp * math.floor((mfe_R - arm) / stp + 1e-9)
                    if p.lock_roe is None or lockR > p.lock_roe + 1e-12:
                        cand = p.entry_price + p.side * lockR * dist
                        p.lock_roe = lockR
            # lad[0] == "none": no ladder
            be = xr.get("be")
            if be is not None and mfe_R >= be - 1e-12:
                bep = roe_price(p.side, p.entry_price, p.leverage, 0.0, rt, fund)     # net-zero price
                c2 = bep if cand is None else tighten(p.side, cand, bep)
                cand = c2
                if p.lock_roe is None:
                    p.lock_roe = 0.0
            if cand is not None:
                p.stop_price = tighten(p.side, p.stop_price, cand)

    return XEngine


# ----------------------------------------------------------------------------------------------- one simulation
def _mark(e, S, sym):
    p = e.position
    last = e._last_mark.get(sym, p.entry_price)
    px = last * (1 - p.side * S.slippage_frac)
    exit_fee = p.qty * px * S.taker_fee
    gross = p.side * p.qty * (px - p.entry_price)
    net = gross - p.entry_fee - exit_fee - p.funding_paid
    return dict(entry_price=p.entry_price, stop_initial=p.stop_initial, qty=p.qty, leverage=p.leverage,
                margin=p.margin_initial, pnl=net, fees=p.entry_fee + exit_fee, funding=p.funding_paid,
                exit_reason="OPEN_END", exit_time=np.nan, entry_time=p.entry_time, mfe_price=p.mfe_price,
                side=p.side, lock=p.lock_roe)


def _rec(tr):
    return dict(entry_price=tr.entry_price, stop_initial=tr.stop_initial, qty=tr.qty, leverage=tr.leverage,
                margin=tr.margin, pnl=tr.pnl, fees=tr.fees, funding=tr.funding, exit_reason=tr.exit_reason,
                exit_time=tr.exit_time, entry_time=tr.entry_time, mfe_price=tr.mfe_price, side=tr.side,
                lock=tr.lock_roe)


def simulate(S, brackets, specs, sig, ss, i0, policy=None, xr=None, tf_ms=None, tp_k=None, time_mode=None,
             tf=None):
    """Returns (status, record): status CLOSED / NOT_ENTERED / OPEN_END."""
    from paperbot.obsshadows import tp_price
    XE = _G["XEngine"]
    e = XE(S, brackets, symbol_specs=specs, book="x", policy=policy, xr=xr, tf_ms=tf_ms)
    e.submit(sig)
    tp = None
    nbars = TIME_STOP_BARS.get(tf, 12)
    tstop_ms = nbars * tf_ms if time_mode else None
    if time_mode == "max2x":
        tstop_ms = 2 * nbars * tf_ms
    sym = sig.symbol
    for k_ in range(i0, len(ss)):
        ts, bars, funding = ss[k_]
        if tp_k is not None:
            p = e.position
            bar = bars.get(p.symbol) if p is not None else None
            rate = (funding or {}).get(p.symbol) if p is not None else None
            if rate is not None and bar is not None:
                e._apply_funding(rate, bar.m_open)
            if p is not None and tp is not None and bar is not None and (bar.open - tp) * p.side >= 0 \
                    and (bar.m_open - p.liq_price) * p.side > 0:
                e._close_market(bar.open, bar.open_time, "TP")
                return "CLOSED", _rec(e.trades[0])
            entered_before = p is not None
            e.step(bars, {})
        else:
            e.step(bars, funding)
        if e.trades:
            return "CLOSED", _rec(e.trades[0])
        p = e.position
        if p is None:
            if not e.pending:
                return "NOT_ENTERED", {}
            continue
        bar = bars.get(p.symbol)
        if tp_k is not None:
            if tp is None:
                tp = tp_price(p, tp_k, None if bar is None else bar.open)
            entry_bar = not entered_before
            if bar is not None and not (entry_bar and "ref_price" in p.signal.meta):
                if (bar.high >= tp) if p.side > 0 else (bar.low <= tp):
                    e._close_market(tp, bar.close_time, "TP")
                    return "CLOSED", _rec(e.trades[0])
        if tstop_ms is not None and bar is not None and ts + MIN >= p.entry_time + tstop_ms:
            go = False
            if time_mode == "house":
                go = p.lock_roe is None
            elif time_mode == "neg":
                go = (bar.close - p.entry_price) * p.side < 0
            elif time_mode == "max2x":
                go = True
            if go:
                e._close_market(bar.close, bar.close_time, "TIME")
                return "CLOSED", _rec(e.trades[0])
            elif time_mode in ("neg", "house"):
                tstop_ms = None          # one check at the N-th bar only
    if e.position is None:
        return ("NOT_ENTERED", {}) if not e.pending else ("NO_BARS", {})
    return "OPEN_END", _mark(e, S, sym)


def run_signal(d: dict, flip: bool = False) -> list[dict]:
    from paperbot.daily3 import make_signal
    from paperbot.obsshadows import SameLeveragePolicy, NoTakeProfitPolicy, variant_settings
    from dataclasses import replace
    G = _G
    S = G["settings"]
    sym = d["symbol"]
    ss = G["ssteps"].get(sym)
    ts_list = G["ts_list"]
    i0 = bisect.bisect_left(ts_list, d["bar_close"])
    base_out = {k: d[k] for k in ("run", "sig_id", "bar_close", "timeframe", "strategy", "symbol", "atr", "ref_price",
                                  "kind", "acct_status")}
    base_out["side"] = int(d["side"]) * (-1 if flip else 1)
    base_out["flip"] = int(flip)
    if ss is None or i0 >= len(ts_list) or (ts_list[i0] - d["bar_close"]) > 5 * MIN:
        return [dict(base_out, variant="base", status="NO_BARS")]
    dd = dict(d)
    if flip:
        dd["side"] = -int(d["side"])
    tf = d["timeframe"]
    tf_ms = TF_MIN[tf] * MIN
    sig = make_signal(dd)
    rows = []
    # base first: its leverage fixes the SameLeveragePolicy of the exit variants
    st, rec = simulate(S, G["brackets"], G["specs"], sig, ss, i0, tf_ms=tf_ms, tf=tf)
    if flip and rec:
        pass
    rows.append(dict(base_out, variant="base", status=st, **rec))
    if st not in ("CLOSED", "OPEN_END"):
        return rows
    lev = int(rec["leverage"])
    base_lev_group = None
    for name, v in VARIANTS.items():
        if name == "base":
            continue
        try:
            kind = v["kind"]
            s2, sg, pol, xr, tpk, tm = S, sig, None, None, None, v.get("time")
            if kind == "house":
                if "lock" in v:
                    s2 = replace(S, ladder_first_lock=v["lock"])
                elif "levvar" in v:
                    s2 = variant_settings(S, v["levvar"]) if v["levvar"] != "lev10" else variant_settings(S, "lev10")
                elif "stopw" in v:
                    sg = make_signal(dd, stop_atr=v["stopw"])
                    pol = SameLeveragePolicy(S, lev)
            elif kind == "tp":
                tpk = v["k"]
                if v.get("ladder"):
                    pol = SameLeveragePolicy(S, lev)
                    if "be" in v:
                        xr = {"ladder": ("roe",), "be": v["be"]}
                else:
                    s2 = replace(S, tp_mode="ladder")      # ladder mode so XEngine._raise_lock runs (BE only)
                    pol = NoTakeProfitPolicy(S, lev)
                    xr = {"ladder": ("none",), "be": v.get("be")}
            elif kind == "x":
                pol = SameLeveragePolicy(S, lev)
                xr = {k: v[k] for k in ("ladder", "bar_only", "be") if k in v}
            st2, rec2 = simulate(s2, G["brackets"], G["specs"], sg, ss, i0, policy=pol, xr=xr, tf_ms=tf_ms,
                                 tp_k=tpk, time_mode=tm, tf=tf)
            rows.append(dict(base_out, variant=name, status=st2, **rec2))
        except Exception as exc:  # noqa: BLE001
            rows.append(dict(base_out, variant=name, status=f"ERROR {type(exc).__name__}: {exc}"))
    return rows


def _chunk(idx):
    out = []
    for i in idx:
        d = _G["sigs"][i]
        out += run_signal(d, flip=False)
        if _G["flip"]:
            out += run_signal(d, flip=True)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("out_csv")
    ap.add_argument("--repo", default="/home/user/crypto-bot-research")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--runs", default="run-20261005T183457Z,current")
    ap.add_argument("--no-flip", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tfs", default="15m,30m,1h,4h")
    a = ap.parse_args(argv)
    sys.path.insert(0, a.repo)
    from paperbot.config import v3_settings
    _G["XEngine"] = make_xengine()
    brackets = make_brackets()
    names = a.runs.split(",")
    R = {}
    for n in names:
        p = os.path.join(a.export_dir, n)
        R[n] = {"sig": read(os.path.join(p, "signal_log.csv")), "acc": read(os.path.join(p, "accounts.csv")),
                "trades": read(os.path.join(p, "trades.csv")), "bars": read(os.path.join(p, "live_bars.csv")),
                "out": read(os.path.join(p, "outcomes.csv")), "ctx": os.path.join(p, "signal_ctx.jsonl")}
    allbars = pd.concat([R[n]["bars"] for n in names], ignore_index=True).drop_duplicates(["ts", "symbol"])
    rates = {}
    for n in names:
        for ts, d in infer_funding(R[n]["trades"], R[n]["bars"]).items():
            rates.setdefault(ts, {}).update(d)
    t0 = time.time()
    ts_list, ssteps = build_steps(allbars, rates)
    print(f"steps {len(ts_list)} from {pd.Timestamp(ts_list[0], unit='ms')} to {pd.Timestamp(ts_list[-1], unit='ms')}"
          f" UTC; funding instants {len(rates)}; {time.time()-t0:.1f}s", flush=True)
    specs = infer_specs(pd.concat([R[n]["trades"] for n in names]))
    taker = implied_taker(pd.concat([R[n]["trades"] for n in names]))
    S = v3_settings(taker_fee=taker)
    print(f"taker {taker} rule {S.leverage_rule} rt {S.round_trip_cost}", flush=True)
    tfs = set(a.tfs.split(","))
    sigs = []
    for n in names:
        sig = R[n]["sig"]
        acc = R[n]["acc"]
        exits = {r.account_id: jload(r.data).get("exits", "house") for r in acc.itertuples()}
        kinds = dict(zip(acc["account_id"], acc["kind"]))
        strength = load_ctx_strength(R[n]["ctx"])
        o = R[n]["out"][["account_id", "sig_ts", "symbol", "status"]].drop_duplicates(["account_id", "sig_ts", "symbol"])
        ost = {(r.account_id, int(r.sig_ts), r.symbol): r.status for r in o.itertuples()}
        sub = sig[(sig["status"] == "SUBMITTED") & sig["timeframe"].isin(tfs)]
        for r in sub.itertuples(index=False):
            aid = f"{r.strategy}@{r.timeframe}"
            if exits.get(aid, "house") != "house":
                continue
            atr, ref = fnum(r.atr), fnum(r.ref_price)
            if not (atr == atr and atr > 0 and ref == ref):
                continue
            d = {"run": n, "sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe,
                 "strategy": r.strategy, "symbol": r.symbol, "side": int(r.side), "atr": atr, "ref_price": ref,
                 "ref_time": int(r.ref_time) if r.ref_time == r.ref_time else None,
                 "delay_ms": int(r.delay_ms) if r.delay_ms == r.delay_ms else None,
                 "kind": kinds.get(aid, infer_kind(aid)),
                 "acct_status": ost.get((aid, int(r.bar_close) - 1, r.symbol))}
            ctx = strength.get(int(r.id))
            d["data"] = {"ctx": ctx} if ctx else {}
            sigs.append(d)
    if a.limit:
        sigs = sigs[: a.limit]
    print(f"signals {len(sigs)} ({collections.Counter((s['run'], s['timeframe']) for s in sigs)})", flush=True)
    _G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, settings=S, brackets=brackets, specs=specs,
              flip=not a.no_flip)
    t1 = time.time()
    idx = list(range(len(sigs)))
    if a.procs > 1 and len(idx) > 50:
        import multiprocessing as mp
        chunks = [idx[k::a.procs * 8] for k in range(a.procs * 8)]
        with mp.get_context("fork").Pool(a.procs) as pool:
            parts = pool.map(_chunk, chunks)
        res = [x for p in parts for x in p]
    else:
        res = _chunk(idx)
    print(f"simulated {len(res)} rows in {time.time()-t1:.1f}s", flush=True)
    df = pd.DataFrame(res)
    df["bars_end"] = ts_list[-1] + MIN
    df.to_csv(a.out_csv, index=False)
    print(df.groupby(["variant", "status"]).size().unstack(1).fillna(0).astype(int).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
