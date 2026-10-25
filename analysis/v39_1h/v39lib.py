"""Shared loading and replay code of the V3.9 1h study (analysis/v39_1h).

Reads a rule-bot export folder (analysis/live1019/rb_export.py zip, extracted with
analysis/review1024/rulebot/scripts/extract_zip.py) and the repository's own engine code. Nothing is written into the
repository except by the scripts' explicit output folder, and no .pyc files (sys.dont_write_bytecode).
"""
from __future__ import annotations

import importlib.util
import json
import os
import site
import sys
from dataclasses import replace

sys.dont_write_bytecode = True
_us = site.getusersitepackages()
if _us not in sys.path:
    sys.path.append(_us)
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ACCOUNT = "V39_ALL@1h"
STRATEGY, TF = "V39_ALL", "1h"
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
KST = 9 * HOUR


def kst(ms) -> str:
    return pd.Timestamp(int(ms) + KST, unit="ms").strftime("%m-%d %H:%M")


def load_analyze():
    """analysis/rulebot_1007/scripts/analyze.py (bracket table, funding inference, settings) as a module."""
    name = "rb_analyze_1007"
    if name in sys.modules:
        return sys.modules[name]
    p = os.path.join(REPO, "analysis", "rulebot_1007", "scripts", "analyze.py")
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


class _T:
    def __init__(self, trades):
        self.trades = trades


class Window:
    """The export's current run, restricted to what this account needs. ``cut_ms``: drop every bar, signal and trade
    at or after this time (to rerun the study as of an earlier export)."""

    def __init__(self, export_dir: str, cut_ms: int | None = None):
        AZ = load_analyze()
        cur = os.path.join(export_dir, "current")
        tr = pd.read_csv(os.path.join(cur, "trades.csv"), low_memory=False)
        sig = pd.read_csv(os.path.join(cur, "signal_log.csv"), low_memory=False)
        bars = pd.read_csv(os.path.join(cur, "live_bars.csv"))
        out = pd.read_csv(os.path.join(cur, "outcomes.csv"), low_memory=False)
        if cut_ms is not None:
            tr = tr[tr["exit_time"] < cut_ms]
            sig = sig[sig["bar_close"] < cut_ms]
            bars = bars[bars["ts"] + MIN <= cut_ms]
            out = out[out["sig_ts"] + 1 < cut_ms]
        self.export_dir, self.cut_ms = export_dir, cut_ms
        self.taker = AZ.implied_taker(_T(tr))
        self.S = AZ.replay_settings("quality_v1", self.taker)
        self.brackets, _ = AZ.make_brackets(None)
        self.specs = AZ.infer_specs(tr)
        self.rates, self.funding_info = AZ.infer_funding(tr, bars)
        self.trades = tr[tr["account_id"] == ACCOUNT].sort_values("entry_time").reset_index(drop=True)
        self.outcomes = out[out["account_id"] == ACCOUNT].reset_index(drop=True)
        self.bars = bars.sort_values(["ts", "symbol"]).reset_index(drop=True)
        self.end_ms = int(self.bars["ts"].max()) + MIN
        self.start_ms = int(self.bars["ts"].min())
        s = sig[(sig["strategy"] == STRATEGY) & (sig["timeframe"] == TF)]
        self.signal_rows = s.copy()
        ids = set(int(x) for x in s["id"])
        ctx = {}
        with open(os.path.join(cur, "signal_ctx.jsonl")) as fh:
            for line in fh:
                d = json.loads(line)
                if int(d.get("id", -1)) in ids:
                    ctx[int(d["id"])] = d.get("ctx")
        self.ctx = ctx
        from paperbot.daily3 import make_signal
        from paperbot.levrule import signal_group
        self.sigs = []
        for r in s[s["status"] == "SUBMITTED"].itertuples(index=False):
            d = {"sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy,
                 "symbol": r.symbol, "side": int(r.side), "atr": float(r.atr), "ref_price": float(r.ref_price),
                 "ref_time": int(r.ref_time), "delay_ms": int(r.delay_ms)}
            c = ctx.get(int(r.id))
            d["data"] = {"ctx": c} if c else {}
            d["best"] = signal_group(make_signal(d))["group"] == "best"
            self.sigs.append(d)
        prio = {s_: k for k, s_ in enumerate(self.S.symbol_priority)}
        self.sigs.sort(key=lambda d: (d["bar_close"], prio.get(d["symbol"], 99)))
        self.late = s[s["status"] != "SUBMITTED"]
        self.A = self._arrays()

    # ------------------------------------------------------------------ bars
    def _arrays(self) -> dict:
        A = {}
        for sym, g in self.bars.groupby("symbol"):
            ts = g["ts"].to_numpy(np.int64)
            a = {"ts": ts}
            for k, c in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
                a[k] = g[c].to_numpy(float)
            for k, c, fb in (("mo", "mark_open", "o"), ("mh", "mark_high", "h"), ("ml", "mark_low", "l"),
                             ("mc", "mark_close", "c")):
                v = g[c].to_numpy(float)
                a[k] = np.where(np.isfinite(v), v, a[fb])
            f = np.zeros(len(ts))
            for t, rates in self.rates.items():
                if sym in rates:
                    j = np.searchsorted(ts, t)
                    if j < len(ts) and ts[j] == t:
                        f[j] += rates[sym]
            a["fund"] = f
            a["src_live"] = np.ones(len(ts), bool)
            A[sym] = a
        return A

    def extend(self, minute_npz_dir: str) -> dict:
        """Append public 1m bars (fetch_bars.py minute) after the export's last minute (hours after the last exits).
        Funding after the export is not known (0). Returns {symbol: minutes added}."""
        added = {}
        for sym, a in self.A.items():
            p = os.path.join(minute_npz_dir, f"{sym}.npz")
            if not os.path.exists(p):
                continue
            z = np.load(p)
            k = z["ts"] > a["ts"][-1]
            if not k.any():
                added[sym] = 0
                continue
            for key in ("o", "h", "l", "c", "mo", "mh", "ml", "mc"):
                a[key] = np.r_[a[key], z[key][k]]
            a["ts"] = np.r_[a["ts"], z["ts"][k]]
            a["fund"] = np.r_[a["fund"], np.zeros(int(k.sum()))]
            a["src_live"] = np.r_[a["src_live"], np.zeros(int(k.sum()), bool)]
            added[sym] = int(k.sum())
        return added

    def steps(self):
        """PaperEngine steps (ts, {symbol: Bar}, {symbol: funding rate}) over the export's live bars."""
        from paperbot.daily3 import _bar_of
        cols = list(self.bars.columns)
        by_ts: dict = {}
        for row in self.bars.itertuples(index=False):
            r = dict(zip(cols, row))
            for k in ("mark_open", "mark_high", "mark_low", "mark_close", "volume", "close_time"):
                v = r.get(k)
                if v is not None and isinstance(v, float) and v != v:
                    r[k] = None
            by_ts.setdefault(int(r["ts"]), {})[r["symbol"]] = _bar_of(r)
        return [(t, by_ts[t], dict(self.rates.get(t, {}))) for t in sorted(by_ts)]

    def entry_index(self, sym: str, t: int) -> int:
        """Index of the minute bar opening at ``t`` (or the first after it)."""
        return int(np.searchsorted(self.A[sym]["ts"], t))


# ---------------------------------------------------------------------- PaperEngine replay (the bot's own code)
def engine_replay(W: Window, settings=None, engine_cls=None, policy=None, stop_atr=None, steps=None):
    """The account as the paper bot runs it: every SUBMITTED V39_ALL@1h signal, one position, from $5,000."""
    from paperbot.daily3 import make_signal
    from paperbot.engine import PaperEngine
    S = settings or W.S
    cls = engine_cls or PaperEngine
    e = cls(S, W.brackets, symbol_specs=W.specs, book=ACCOUNT, policy=policy(S) if policy else None)
    by_bc: dict = {}
    for d in W.sigs:
        by_bc.setdefault(d["bar_close"], []).append(d)
    for ts, bars, fund in (steps or W.steps()):
        e.step(bars, fund)
        for d in by_bc.get(ts + MIN, []):
            e.submit(make_signal(d, stop_atr=stop_atr))
    return e


def trail_engine(trail_k: float, trail_start: float, ladder: bool = True):
    """A PaperEngine whose stop also trails the best price by k x the signal's ATR once the best net ROE reaches
    ``trail_start`` (and, ladder=False, without the stepped lock). Used only to check the kernel."""
    from paperbot.engine import PaperEngine
    from paperbot.ladder import net_roe, tighten

    class TrailEngine(PaperEngine):
        def _raise_lock(self, p):
            if ladder:
                super()._raise_lock(p)
            fund = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
            best = net_roe(p.side, p.entry_price, p.mfe_price, p.leverage, self.s.round_trip_cost, fund)
            if best >= trail_start - 1e-12:
                cand = p.mfe_price - p.side * trail_k * float(p.signal.atr)
                new = tighten(p.side, p.stop_price, cand)
                if new != p.stop_price:
                    p.stop_price = new
                    if p.lock_roe is None:
                        p.lock_roe = 0.0
    return TrailEngine


def forced_policy(lev_btc: int, lev_alt: int, frac):
    """An OwnerPolicy that skips the safety checks and uses a fixed leverage per coin group (margin share = leverage %
    when ``frac`` is None). Used only to check the kernel."""
    from paperbot.margin import liquidation_price
    from paperbot.policy import OwnerPolicy
    from paperbot.sizing import SizeDecision, _round_down

    class Forced(OwnerPolicy):
        def size(self, equity, sig, entry, brackets, spec):
            lev = lev_btc if sig.symbol == "BTCUSDT" else lev_alt
            f = lev / 100.0 if frac is None else frac
            qty = _round_down(equity * f * lev / entry, spec.get("qty_step", 0.0))
            notional = qty * entry
            margin = notional / lev
            liq = liquidation_price(sig.side, qty, entry, margin, brackets.for_notional(notional))
            return SizeDecision(True, "forced", lev, margin, qty, liq, 0.0, [])
    return Forced


# ---------------------------------------------------------------------- kernel account replay
def kernel_vectors(W: Window, settings=None):
    import sim
    S = sim.settings_vector(settings or W.S)
    br = {s: sim.bracket_array(b) for s, b in W.brackets.items()}
    return S, br


def kernel_account(W: Window, v, entry_fn=None, equity0: float = 5000.0, settings=None, specs=None,
                   sigs=None) -> pd.DataFrame:
    """The account replayed with the kernel: every SUBMITTED signal in order, one position at a time (a signal whose
    fill minute is at or before the open position's exit minute is skipped, as engine.step handles entries before
    exits), compounding from $5,000. ``entry_fn(d) -> (bar index, raw price) or None`` changes the entry (None:
    skipped); default = the paper entry (minute opening at the bar close, at the logged ref_price).
    ``settings`` / ``specs``: other costs or order sizes (the live plan); ``sigs``: the signals in another order
    (which of several simultaneous signals is taken first)."""
    import sim
    Sset = settings or W.S
    specs = specs or W.specs
    S, br = kernel_vectors(W, Sset)
    wallet = equity0
    busy_until = -1
    entered_at = -1
    rows = []
    for d in (sigs if sigs is not None else W.sigs):
        sym = d["symbol"]
        A = W.A[sym]
        if entry_fn is None:
            e = W.entry_index(sym, d["bar_close"])
            raw = d["ref_price"]
        else:
            x = entry_fn(d)
            if x is None:
                rows.append({"sig_id": d["sig_id"], "status": "NO_ENTRY"})
                continue
            e, raw = x
        if e >= len(A["ts"]):
            rows.append({"sig_id": d["sig_id"], "status": "NO_BARS"})
            continue
        t_fill = int(A["ts"][e])
        if t_fill <= busy_until or t_fill == entered_at:
            rows.append({"sig_id": d["sig_id"], "status": "SKIPPED"})
            continue
        pl = 0
        if v.same_lev:
            # "the trade's own leverage": what the rule gives this signal with the 2 ATR stop on this wallet
            fill = raw * (1 + d["side"] * Sset.slippage_frac)
            ok, lev, *_ = sim.size_rule(S, br[sym], wallet, d["side"], fill, raw - d["side"] * 2.0 * d["atr"],
                                        d["atr"], d["best"], specs[sym]["qty_step"], specs[sym]["min_notional"])
            pl = int(lev) if ok else 0
        r = sim.run_one(S, br[sym], A, e, raw, d["side"], d["atr"], d["best"], wallet, specs[sym], v, sym,
                        paper_lev=pl, paper_frac=pl / 100.0)
        if r["reason"] == "REJECTED":
            rows.append({"sig_id": d["sig_id"], "status": "REJECTED"})
            continue
        r.update(sig_id=d["sig_id"], status="ENTERED", symbol=sym, side=d["side"], equity_before=wallet)
        wallet += r["pnl"]
        r["equity_after"] = wallet
        busy_until = int(A["ts"][int(r["j"])]) if r["reason"] != "OPEN" else 2 ** 62
        entered_at = t_fill
        rows.append(r)
        if Sset.bust_below > 0 and wallet < min(Sset.bust_below, 0.1 * equity0):
            break
    return pd.DataFrame(rows)


def max_drawdown(equity: np.ndarray, start: float = 5000.0) -> float:
    e = np.r_[start, np.asarray(equity, float)]
    peak = np.maximum.accumulate(e)
    return float(np.max(1 - e / peak)) if len(e) else 0.0


def settings_with(S, **kw):
    return replace(S, **kw)
