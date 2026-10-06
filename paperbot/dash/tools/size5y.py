"""한 번에 잃는 크기 규칙 (5년 자료): the same 5-year entries and exits of the 36 under other position-size rules.
Offline generator for paperbot/dash/data/size5y.json (served by paperbot/dash/more/size5y.py, drawn by
screens/analysis-size.js). Pre-registered in docs/size5y.md before any run; every constant below is that document's.
Read-only research: the engines are imported, never changed; nothing touches a bot database.

    python -m paperbot.dash.tools.size5y --signals <signal cache dir> [--out paperbot/dash/data/size5y.json] \
        [--work <checkpoint dir>]

One worker process. ``--work``: one checkpoint file per (timeframe, strategy) and per (timeframe, coin-flip seed) with
the trade path, so a killed run resumes; a run with other constants uses its own sub folder (``config_key``).

Step 1, the path (``path_cell``): rules_bt.simulate under research/power/power.py's quality_v1 shim (the v4 rule),
2 ATR stop and the ladder, in 30-day $5,000 accounts that never cross a split edge, with the engine's bust rule off
while the path is made (a bust under one rule must not cut the trade list of another). Every accepted sizing
decision is recorded (``recorder``), so each trade has its fill, first stop, ATR and quality group; its net return
per dollar of notional is R / leverage (fees, slippage and funding included), or, for a trade the engine closed at the
liquidation price, recomputed at the gap open as the engine fills a gapped stop.

Step 2, the rules (``Sizer``, ``account``): every trade again, sized at the rule account's own equity:
  v4    paperbot.sizing.size_position with the v4 settings (the shim's own Settings) and the trade's group
  r05 / r1 / r2   size so that hitting the first stop loses 0.5 / 1 / 2 % of equity (size_position's loss formula),
        leverage = the first of the group's v4 candidates the bracket and the stop-inside-liquidation check allow,
        margin = notional / leverage capped at 50 % of equity (the size shrinks to fit)
  half  the v4 candidates with half the leverage and the same margin share (half the position)
P&L = notional x return, at most the margin; a rule whose liquidation price the raw exit price (a gap open) passes
loses the margin. Bust: equity under $10 stops the account. Accounts: one 5-year account, one per split, and the
30-day accounts of the path (the paper's shape). The 30-day v4 accounts must equal the engine's own finals (parity).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import replace
from typing import Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RULES_DIR = os.path.join(ROOT, "research", "paper_rules")
POWER_DIR = os.path.join(ROOT, "research", "power")
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "size5y.json")

VERSION = 1
TFS = ("15m", "30m", "1h", "4h")
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")     # rules_bt.COINS (entry priority order)
NS_DAY = 86_400 * 10 ** 9
KST_NS = 9 * 3600 * 10 ** 9
START = "2021-03-01"                      # KST midnight
END_UTC = "2026-09-30"                    # UTC midnight = the cache's end (last 15m bar 2026-09-29 23:45 UTC)
SPLITS = (("p1", "2021-03-01", "2023-01-01"), ("p2", "2023-01-01", "2025-01-01"), ("p3", "2025-01-01", None))
SPLIT_KO = {"full": "5년 (2021-03 ~ 2026-09)", "p1": "2021-03 ~ 2022-12", "p2": "2023 ~ 2024", "p3": "2025-01 ~ 2026-09"}
WINDOW_DAYS, MIN_TAIL_DAYS = 30, 10
INITIAL = 5000.0
BUST_BELOW = 10.0
MIN_NOTIONAL = 5.0
K_STOP = 2.0
RULE = "quality_v1"
SEED = 20261006
FLIP_SEEDS = (1, 2, 3)
RULES = ("v4", "r05", "r1", "r2", "half")
RISK = {"r05": 0.005, "r1": 0.01, "r2": 0.02}
RULE_KO = {"v4": "지금 v4", "r05": "손절 = 잔고 0.5%", "r1": "손절 = 잔고 1%", "r2": "손절 = 잔고 2%", "half": "배수 절반"}
RULE_SHORT = {"v4": "지금 v4", "r05": "0.5% 규칙", "r1": "1% 규칙", "r2": "2% 규칙", "half": "배수 절반"}
MARGIN_CAP = 0.50
PARITY_TOL = 0.01
# compact metric rows (the page reads them by these names)
M_KEYS = ("mult", "cagr", "mdd", "worst_month", "pos_months", "calmar", "bust", "taken", "skipped", "bust_at")
W_KEYS = ("windows", "bust", "pos", "median", "worst")
L_KEYS = ("loss_med", "loss_max", "losses")


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def day_ns(s: str) -> int:
    return int(np.datetime64(s, "ns").astype(np.int64))


def kst_ns(s: str) -> int:
    """Midnight of day ``s`` in Korea time, as UTC nanoseconds."""
    return day_ns(s) - KST_NS


def span() -> tuple[int, int]:
    return kst_ns(START), day_ns(END_UTC)


def split_bounds() -> list:
    """[(key, t0, t1)] of the three splits (KST midnights; the last ends with the data)."""
    t_end = span()[1]
    return [(k, kst_ns(a), kst_ns(b) if b else t_end) for k, a, b in SPLITS]


# ---------------------------------------------------------------- windows and months (pure)
def windows(start_ns: int, end_ns: int, days: int = WINDOW_DAYS, min_tail_days: int = MIN_TAIL_DAYS) -> list:
    """Consecutive [w0, w1) of ``days`` inside [start, end); a last piece of at least ``min_tail_days`` is kept."""
    step, out, w0 = days * NS_DAY, [], int(start_ns)
    while w0 + step <= end_ns:
        out.append((w0, w0 + step))
        w0 += step
    if end_ns - w0 >= min_tail_days * NS_DAY:
        out.append((w0, int(end_ns)))
    return out


def split_windows(splits: Optional[list] = None) -> list:
    """[(split key, w0, w1)] over every split, never crossing a split's edges."""
    out = []
    for key, a, b in (splits or split_bounds()):
        out += [(key, w0, w1) for w0, w1 in windows(a, b)]
    return out


def month_edges(t0: int, t1: int) -> tuple[list, list]:
    """KST calendar months over [t0, t1): (labels 'YYYY-MM', the end of each month in UTC ns; the last is t1)."""
    labels, ends = [], []
    d = np.datetime64(int(t0 + KST_NS), "ns").astype("datetime64[M]")
    while True:
        nxt = int((d + 1).astype("datetime64[ns]").astype(np.int64)) - KST_NS
        labels.append(str(d))
        if nxt >= t1:
            ends.append(int(t1))
            break
        ends.append(nxt)
        d = d + 1
    return labels, ends


def at_edges(times: np.ndarray, eq_after: np.ndarray, edges: list, e0: float) -> np.ndarray:
    """Equity at each edge: after the last trade that closed before it (``e0`` before any)."""
    times = np.asarray(times, np.int64)
    idx = np.searchsorted(times, np.asarray(edges, np.int64), side="left") - 1
    eq = np.asarray(eq_after, float)
    return np.where(idx >= 0, eq[np.clip(idx, 0, max(len(eq) - 1, 0))] if len(eq) else e0, e0).astype(float)


# ---------------------------------------------------------------- statistics (pure)
def max_drawdown(eq: np.ndarray, e0: float) -> float:
    """Deepest fall from a running peak (the start counts as the first peak); 0 when it never falls."""
    x = np.concatenate(([e0], np.asarray(eq, float)))
    peak = np.maximum.accumulate(x)
    return float(np.max(1.0 - x / peak)) if len(x) else 0.0


def cagr(mult: float, years: float) -> Optional[float]:
    if years <= 0:
        return None
    if mult <= 0:
        return -1.0
    return float(mult ** (1.0 / years) - 1.0)


def metrics(times, eq_after, e0: float, t0: int, t1: int, bust: bool, taken: int, skipped: int,
            bust_at: Optional[int] = None) -> dict:
    """The page's numbers of one account over [t0, t1) from its closed trades (``times``, equity after each)."""
    eq_after = np.asarray(eq_after, float)
    end = float(eq_after[-1]) if len(eq_after) else e0
    mult = end / e0
    years = (t1 - t0) / (365.25 * NS_DAY)
    mdd = max_drawdown(eq_after, e0)
    _labels, ends = month_edges(t0, t1)
    me = at_edges(times, eq_after, ends, e0)
    prev = np.concatenate(([e0], me[:-1]))
    mret = me / prev - 1.0
    g = cagr(mult, years)
    return {"mult": mult, "cagr": g, "mdd": mdd, "worst_month": float(mret.min()) if len(mret) else None,
            "pos_months": float(np.mean(mret > 1e-12)) if len(mret) else None,
            "calmar": (g / mdd) if (g is not None and mdd > 1e-12) else None, "bust": int(bool(bust)),
            "taken": int(taken), "skipped": int(skipped), "bust_at": bust_at, "months": me}


def curve_metrics(curve: np.ndarray, e0: float, t0: int, t1: int) -> dict:
    """The same numbers from a monthly equity curve (pooled accounts: the drawdown is monthly)."""
    curve = np.asarray(curve, float)
    mult = float(curve[-1] / e0) if len(curve) else 1.0
    prev = np.concatenate(([e0], curve[:-1]))
    mret = curve / prev - 1.0
    mdd = max_drawdown(curve, e0)
    g = cagr(mult, (t1 - t0) / (365.25 * NS_DAY))
    return {"mult": mult, "cagr": g, "mdd": mdd, "worst_month": float(mret.min()) if len(mret) else None,
            "pos_months": float(np.mean(mret > 1e-12)) if len(mret) else None,
            "calmar": (g / mdd) if (g is not None and mdd > 1e-12) else None}


# ---------------------------------------------------------------- engines (imported read-only)
def _rb():
    for d in (RULES_DIR, POWER_DIR):
        if d not in sys.path:
            sys.path.insert(0, d)
    import rules_bt as RB  # noqa: PLC0415  (research/paper_rules/rules_bt.py, unchanged)
    return RB


def _power():
    _rb()
    import power as PW  # noqa: PLC0415  (research/power/power.py, unchanged)
    return PW


def _lib():
    from paperbot import sweepsig
    return sweepsig.lib()


@contextlib.contextmanager
def path_mode(RB):
    """While the path is made: accounts start at $5,000 and the bust rule is off (rules_bt.py itself is unchanged)."""
    old = RB.INITIAL, RB.BUST_BELOW
    RB.INITIAL, RB.BUST_BELOW = INITIAL, -math.inf
    try:
        yield
    finally:
        RB.INITIAL, RB.BUST_BELOW = old


@contextlib.contextmanager
def recorder(RB, out: list):
    """Wraps whatever rules_bt.size_position is now (the quality_v1 shim) and keeps every accepted decision with its
    inputs: (equity, side, entry, stop, atr, group, leverage, qty, margin, liq). One accepted decision = one trade."""
    inner = RB.size_position

    def rec(settings, equity, side, entry, stop, requested, brackets, **kw):
        d = inner(settings, equity, side, entry, stop, requested, brackets, **kw)
        if d.ok:
            out.append((float(equity), int(side), float(entry), float(stop), float(kw.get("atr") or 0.0), str(d.tier),
                        int(d.leverage), float(d.qty), float(d.margin), float(d.liq_price)))
        return d

    RB.size_position = rec
    try:
        yield
    finally:
        RB.size_position = inner


def v4_settings(RB):
    """The settings the quality_v1 shim sizes with (research/power/power.py leverage_rule)."""
    from paperbot.config import V3_BEST_FALLS_TO_NORMAL, V3_QUALITY_TIERS
    return replace(RB.SETTINGS, leverage_rule="quality_v1", tiers=V3_QUALITY_TIERS, max_margin_frac=MARGIN_CAP,
                   best_falls_to_normal=V3_BEST_FALLS_TO_NORMAL)


def half_settings(s4):
    from paperbot.config import Tier
    tiers = tuple(Tier(t.name, t.margin_frac, tuple(max(1, lev // 2) for lev in t.leverages)) for t in s4.tiers)
    return replace(s4, tiers=tiers, min_leverage=min(lev for t in tiers for lev in t.leverages))


def trade_returns(side, fill, R, lev, reason_liq, o_exit, held, fee: float, slip: float, f_bar: float):
    """(net return per dollar of notional, raw exit price before slippage) of each path trade. R / leverage, except
    where the engine capped the loss at the margin (R = -1: liquidation, or a gap past it): there the market exit is
    the gap open, filled with slippage as the engine fills a gapped stop."""
    side, fill, R, lev, o_exit, held = (np.asarray(x, float) for x in (side, fill, R, lev, o_exit, held))
    capped = np.asarray(reason_liq, bool) | (R <= -1.0 + 1e-12)
    x_gap = o_exit * (1 - side * slip)
    u_gap = x_gap / fill
    ret_gap = side * (u_gap - 1) - fee * (1 + u_gap) - f_bar * held
    ret = np.where(capped, ret_gap, R / lev)
    u = (ret + side + fee + f_bar * held) / (side - fee)
    raw = np.where(capped, o_exit, u * fill / (1 - side * slip))
    return ret, raw


def path_cell(RB, PW, L, bars: dict, sigs: dict, tf: str, wins: list, seed0: int) -> dict:
    """The v4 trade path over ``wins`` ([(split, w0, w1)]): arrays per trade plus the engine's final per window."""
    warm = L.warmup_bars(tf)
    S = RB.SETTINGS
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    cols = {k: [] for k in ("w", "coin", "side", "t_in", "t_out", "fill", "stop", "atr", "best", "lev0", "margin0",
                            "eq0", "R", "liq", "ret", "raw")}
    finals = np.zeros(len(wins))
    for wi, (_sk, w0, w1) in enumerate(wins):
        b = {c: (max(int(np.searchsorted(bars[c]["ts"], w0)), int(warm)), int(np.searchsorted(bars[c]["ts"], w1)))
             for c in bars}
        rec: list = []
        with path_mode(RB), PW.leverage_rule(RULE, tf, seed0 + wi), recorder(RB, rec):
            r = RB.simulate(bars, sigs, b, K_STOP, tf, L, keep_trades=True)
        finals[wi] = r["final"]
        t = r["trade_table"]
        if len(t) != len(rec):
            raise RuntimeError(f"{tf} window {wi}: {len(t)} trades but {len(rec)} sizing decisions")
        if not len(t):
            continue
        coin = t["coin"].to_numpy(int)
        i = t["i"].to_numpy(int)
        ej = t["exit_j"].to_numpy(int)
        a = np.array(rec, dtype=object)
        side = t["side"].to_numpy(int)
        fill = a[:, 2].astype(float)
        lev = t["lev"].to_numpy(int)
        R = t["R"].to_numpy(float)
        liq = (t["reason"] == "liquidation").to_numpy(bool)
        o_exit = np.array([bars[COINS[p]]["o"][j] for p, j in zip(coin, ej)], float)
        ret, raw = trade_returns(side, fill, R, lev, liq, o_exit, ej - i, S.taker_fee, S.slippage_frac, f_bar)
        cols["w"].append(np.full(len(t), wi))
        cols["coin"].append(coin)
        cols["side"].append(side)
        cols["t_in"].append(np.array([bars[COINS[p]]["ts"][k + 1] for p, k in zip(coin, i)], np.int64))
        cols["t_out"].append(np.array([bars[COINS[p]]["ts"][j] for p, j in zip(coin, ej)], np.int64))
        cols["fill"].append(fill)
        cols["stop"].append(a[:, 3].astype(float))
        cols["atr"].append(a[:, 4].astype(float))
        cols["best"].append(a[:, 5] == "best")
        cols["lev0"].append(lev)
        cols["margin0"].append(a[:, 8].astype(float))
        cols["eq0"].append(a[:, 0].astype(float))
        cols["R"].append(R)
        cols["liq"].append(liq)
        cols["ret"].append(ret)
        cols["raw"].append(raw)
    out = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in cols.items()}
    out["finals"] = finals
    return out


# ---------------------------------------------------------------- the rules (step 2)
class Sizer:
    """Notional, margin and liquidation price of one entry under each rule (None = cannot be entered)."""

    def __init__(self, settings, brackets, min_notional: float = MIN_NOTIONAL):
        from paperbot.margin import liquidation_price
        from paperbot.sizing import size_position
        self.s4 = settings
        self.sh = half_settings(settings)
        self.br = brackets
        self.mn = float(min_notional)
        self._size, self._liq = size_position, liquidation_price

    def per_unit_loss(self, side: int, entry: float, stop: float) -> float:
        """size_position's loss at the stop per unit of quantity (distance, exit slippage, both fees)."""
        s = self.s4
        exit_px = stop * (1 - side * s.slippage_frac)
        return abs(entry - stop) + abs(stop - exit_px) + entry * s.taker_fee + exit_px * s.taker_fee

    def size(self, rule: str, equity: float, side: int, entry: float, stop: float, atr: float, best: bool):
        group = "best" if best else "normal"
        if rule in ("v4", "half"):
            d = self._size(self.s4 if rule == "v4" else self.sh, equity, side, entry, stop, group, self.br, atr=atr,
                           min_notional=self.mn)
            return (d.qty * entry, d.margin, d.liq_price) if d.ok else None
        r = RISK[rule]
        if equity <= 0 or (entry - stop) * side <= 0:
            return None
        qty0 = r * equity / self.per_unit_loss(side, entry, stop)
        s = self.s4
        buffer = max(s.liq_buffer_min_frac * entry, s.liq_buffer_atr_mult * atr)
        for _tier, lev in s.tier_chain(group):
            qty = qty0
            margin = qty * entry / lev
            if margin > s.max_margin_frac * equity:
                qty = s.max_margin_frac * equity * lev / entry
                margin = qty * entry / lev
            notional = qty * entry
            if notional < self.mn:
                continue
            bracket = self.br.for_notional(notional)
            if lev > bracket.max_leverage:
                continue
            liq = self._liq(side, qty, entry, margin, bracket)
            if (stop - liq) * side < buffer:
                continue
            return notional, margin, liq
        return None


def account(tr: dict, rule: str, sizer: Sizer, seg: np.ndarray, initial: float = INITIAL,
            bust_below: float = BUST_BELOW) -> dict:
    """One rule over the path's trades in order; a new account (``initial``) wherever ``seg`` changes. Returns per
    trade: taken, refused (no size fits while the account is alive), equity before, P&L; and per segment the time
    of the bust (the closing time of the trade that took it under ``bust_below``). Sizes use the equity before the
    trade only."""
    n = len(tr["ret"])
    taken = np.zeros(n, bool)
    refused = np.zeros(n, bool)
    e_before = np.zeros(n)
    pnl = np.zeros(n)
    busts: dict = {}
    cur, E, dead = None, initial, False
    side, fill, stop, atr, best = tr["side"], tr["fill"], tr["stop"], tr["atr"], tr["best"]
    ret, raw = tr["ret"], tr["raw"]
    for k in range(n):
        if seg[k] != cur:
            cur, E, dead = seg[k], initial, False
        if dead:
            continue
        sz = sizer.size(rule, E, int(side[k]), float(fill[k]), float(stop[k]), float(atr[k]), bool(best[k]))
        if sz is None:
            refused[k] = True
            continue
        notional, margin, liq = sz
        sd = int(side[k])
        if (raw[k] - liq) * sd <= 0:                  # the exit price passed this rule's liquidation price
            p = -margin
        else:
            p = max(notional * float(ret[k]), -margin)
        taken[k], e_before[k], pnl[k] = True, E, p
        E += p
        if E < bust_below:
            dead = True
            busts[int(cur)] = int(tr["t_out"][k])
    return {"taken": taken, "refused": refused, "e_before": e_before, "pnl": pnl, "busts": busts}


def seg_equity(res: dict, sel: np.ndarray, initial: float = INITIAL) -> np.ndarray:
    """Equity after each taken trade of one account (the trades selected by ``sel``, in order)."""
    m = sel & res["taken"]
    return initial + np.cumsum(res["pnl"][m])


# ---------------------------------------------------------------- one cell: every rule, every account
def cell_summary(tr: dict, wins: list, sizer: Sizer, rules=RULES) -> dict:
    """{rule: {full, p1.., w30, loss, months_full, months_split}} plus the v4 parity check against the engine."""
    t0, t1 = span()
    sb = split_bounds()
    n = len(tr["ret"])
    w = tr["w"].astype(int) if n else np.zeros(0, int)
    wkey = [sk for sk, _a, _b in wins]
    split_of = np.array([[k for k, _a, _b in sb].index(wkey[i]) for i in w], int) if n else np.zeros(0, int)
    _lab, full_edges = month_edges(t0, t1)
    out: dict = {"trades": int(n)}
    parity = None
    for rule in rules:
        r: dict = {}
        res = account(tr, rule, sizer, np.zeros(n, int))
        m = res["taken"]
        eq = seg_equity(res, np.ones(n, bool))
        times = tr["t_out"][m]
        r["full"] = metrics(times, eq, INITIAL, t0, t1, bool(res["busts"]), int(m.sum()), int(res["refused"].sum()),
                            res["busts"].get(0))
        lose = m & (res["pnl"] < 0)
        frac = -res["pnl"][lose] / res["e_before"][lose]
        r["loss"] = [float(np.median(frac)) if len(frac) else None, float(frac.max()) if len(frac) else None,
                     int(lose.sum())]
        # splits
        res_s = account(tr, rule, sizer, split_of)
        for si, (sk, a, b) in enumerate(sb):
            sel = split_of == si
            ms = sel & res_s["taken"]
            r[sk] = metrics(tr["t_out"][ms], seg_equity(res_s, sel), INITIAL, a, b, si in res_s["busts"],
                            int(ms.sum()), int((sel & res_s["refused"]).sum()), res_s["busts"].get(si))
        # 30-day accounts
        res_w = account(tr, rule, sizer, w)
        fin = np.full(len(wins), INITIAL)
        for wi in np.unique(w):
            sel = w == wi
            e = seg_equity(res_w, sel)
            fin[wi] = e[-1] if len(e) else INITIAL
        wr = fin / INITIAL - 1.0
        r["w30"] = [len(wins), int(len(res_w["busts"])), float(np.mean(wr > 1e-12)) if len(wins) else None,
                    float(np.median(wr)) if len(wins) else None, float(wr.min()) if len(wins) else None]
        if rule == "v4":
            parity = parity_check(tr, res_w, fin, len(wins))
        out[rule] = r
    out["parity"] = parity
    return out


def parity_check(tr: dict, res_w: dict, fin: np.ndarray, n_win: int) -> dict:
    """The 30-day v4 accounts re-sized here vs the engine's own finals, on windows whose path equity stayed >= $10
    (the path ran with the bust rule off; below $10 the engine would have stopped)."""
    w = tr["w"].astype(int) if len(tr["ret"]) else np.zeros(0, int)
    low = set()
    if len(w):
        eq_after = tr["eq0"] + tr["R"] * tr["margin0"]
        low = set(int(x) for x in np.unique(w[eq_after < BUST_BELOW]))
    finals = tr["finals"]
    ok = [i for i in range(n_win) if i not in low]
    diff = float(np.max(np.abs(fin[ok] - finals[ok]))) if ok else 0.0
    skipped_trades = int((~res_w["taken"][np.isin(w, ok)]).sum()) if len(w) else 0
    return {"max_diff": diff, "windows": len(ok), "low_windows": len(low), "skipped": skipped_trades}


# ---------------------------------------------------------------- checkpoints
def config_key() -> str:
    cfg = dict(v=VERSION, start=START, end=END_UTC, splits=SPLITS, win=(WINDOW_DAYS, MIN_TAIL_DAYS), init=INITIAL,
               bust=BUST_BELOW, k=K_STOP, rule=RULE, seed=SEED, seeds=FLIP_SEEDS, rules=RULES, risk=RISK,
               cap=MARGIN_CAP, mn=MIN_NOTIONAL)
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:10]


def _save(path: str, arrays: dict) -> None:
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **arrays)
    os.replace(tmp, path)


def _load(path: str) -> dict:
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def cached_path(path: str, make) -> dict:
    if not os.path.exists(path):
        _save(path, make())
    return _load(path)


# ---------------------------------------------------------------- the run
def load_tf(sig_dir: str, tf: str) -> dict:
    out = {}
    for c in COINS:
        with np.load(os.path.join(sig_dir, f"sig_{tf}_{c}.npz")) as z:
            out[c] = {k: z[k] for k in z.files}
    return out


def strategy_names(bars: dict) -> list:
    RB = _rb()
    names = RB.strategy_names(_lib())
    have = set(k[3:] for k in bars[COINS[0]] if k.startswith("s__"))
    return [n for n in names if n in have]


def flip_rate(bars: dict, names: list, lo_ns: int) -> float:
    """Median over the strategies of signals per bar per coin (bars from ``lo_ns`` on)."""
    rates = []
    for n in names:
        tot = cnt = 0
        for c in COINS:
            lo = int(np.searchsorted(bars[c]["ts"], lo_ns))
            s = bars[c]["s__" + n][lo:]
            tot += int(np.count_nonzero(s))
            cnt += len(s)
        rates.append(tot / max(cnt, 1))
    return float(np.median(rates))


def run(sig_dir: str, out: str, work: str, only_tfs=TFS, limit: Optional[int] = None) -> dict:
    RB, PW, L = _rb(), _power(), _lib()
    work = os.path.join(work, config_key())
    os.makedirs(work, exist_ok=True)
    wins = split_windows()
    t_start = time.time()
    sizer = Sizer(v4_settings(RB), RB.BRACKETS, MIN_NOTIONAL)
    cells, flips, rates = [], {}, {}
    for tf in only_tfs:
        bars = load_tf(sig_dir, tf)
        names = strategy_names(bars)[:limit] if limit else strategy_names(bars)
        rates[tf] = flip_rate(bars, strategy_names(bars), span()[0])
        for si, name in enumerate(strategy_names(bars)):
            if name not in names:
                continue
            sg = {c: bars[c]["s__" + name] for c in COINS}
            tr = cached_path(os.path.join(work, f"path_{tf}_{name}.npz"),
                             lambda: path_cell(RB, PW, L, bars, sg, tf, wins, SEED + 1000 * si))
            sp = os.path.join(work, f"sum_{tf}_{name}.json")
            if os.path.exists(sp):
                with open(sp, encoding="utf-8") as f:
                    summ = _from_json(json.load(f))
            else:
                summ = cell_summary(tr, wins, sizer)
                _dump(summ, sp)
            check_parity(summ, f"{tf} {name}")
            cells.append({"s": name, "tf": tf, **summ})
            log(tf, name, summ["trades"], "trades", f"{time.time() - t_start:.0f}s")
        for sd in FLIP_SEEDS:
            tr = cached_path(os.path.join(work, f"flip_{tf}_{sd}.npz"),
                             lambda: path_cell(RB, PW, L, bars, RB.random_signals(bars, None, rates[tf], sd, tf, L), tf,
                                               wins, SEED + 7919 * sd))
            sp = os.path.join(work, f"sumflip_{tf}_{sd}.json")
            if os.path.exists(sp):
                with open(sp, encoding="utf-8") as f:
                    summ = _from_json(json.load(f))
            else:
                summ = cell_summary(tr, wins, sizer)
                _dump(summ, sp)
            check_parity(summ, f"{tf} flip {sd}")
            flips[(tf, sd)] = summ
            log(tf, "flip", sd, summ["trades"], "trades", f"{time.time() - t_start:.0f}s")
    doc = assemble(cells, flips, rates, len(wins), time.time() - t_start)
    write_json(doc, out)
    return doc


def check_parity(summ: dict, what: str) -> None:
    p = summ.get("parity") or {}
    if p.get("max_diff") is not None and p["max_diff"] > PARITY_TOL:
        raise RuntimeError(f"parity: {what} re-sized v4 30-day accounts differ from the engine by {p['max_diff']:.4f}")


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return [_jsonable(v) for v in x.tolist()]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def _from_json(d: dict) -> dict:
    for rule in RULES:
        if rule in d:
            for k, v in d[rule].items():
                if isinstance(v, dict) and "months" in v:
                    v["months"] = np.asarray(v["months"], float)
    return d


def _dump(d: dict, path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_jsonable(d), f)
    os.replace(tmp, path)


# ---------------------------------------------------------------- the page's file
def _s(x, k=4):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, k) if math.isfinite(v) else None


def _g(x, sig=4):
    """Significant digits (multiples run from near 0 to large)."""
    if x is None:
        return None
    v = float(x)
    if not math.isfinite(v):
        return None
    return float(f"{v:.{sig}g}")


def compact(m: dict) -> list:
    return [_g(m["mult"]), _s(m["cagr"]), _s(m["mdd"]), _s(m["worst_month"]), _s(m["pos_months"], 3),
            _s(m["calmar"], 3), int(m.get("bust", 0)), int(m.get("taken", 0)), int(m.get("skipped", 0)),
            None if m.get("bust_at") is None else int(m["bust_at"]) // 10 ** 6]


def pooled(rows: list, rule: str, periods=None) -> dict:
    """Sum of the accounts' monthly equity per period -> the curve and its numbers, plus counts over the accounts."""
    t0, t1 = span()
    out: dict = {}
    pers = [("full", t0, t1)] + [(k, a, b) for k, a, b in split_bounds()]
    for pk, a, b in pers:
        ms = [np.asarray(r[rule][pk]["months"], float) for r in rows]
        if not ms:
            continue
        curve = np.sum(ms, axis=0)
        e0 = INITIAL * len(ms)
        cm = curve_metrics(curve, e0, a, b)
        mults = np.array([r[rule][pk]["mult"] for r in rows], float)
        out[pk] = {"m": compact({**cm, "bust": 0, "taken": sum(r[rule][pk]["taken"] for r in rows),
                                 "skipped": sum(r[rule][pk]["skipped"] for r in rows)}),
                   "busts": int(sum(r[rule][pk]["bust"] for r in rows)), "n": len(rows),
                   "med_mult": _g(float(np.median(mults))), "up": int(np.sum(mults > 1.0 + 1e-9)),
                   "med_mdd": _s(float(np.median([r[rule][pk]["mdd"] for r in rows])))}
        if pk == "full":
            out[pk]["curve"] = [_g(x / e0) for x in curve]
    w = [r[rule]["w30"] for r in rows]
    out["w30"] = [int(sum(x[0] for x in w)), int(sum(x[1] for x in w)),
                  _s(float(np.average([x[2] or 0 for x in w], weights=[x[0] or 1 for x in w])), 3) if w else None,
                  _s(float(np.median([x[3] for x in w if x[3] is not None])), 4) if w else None,
                  _s(float(min(x[4] for x in w if x[4] is not None)), 4) if w else None]
    loss = [r[rule]["loss"] for r in rows if r[rule]["loss"][2]]
    out["loss_med"] = _s(float(np.median([x[0] for x in loss]))) if loss else None
    out["loss_max"] = _s(float(np.max([x[1] for x in loss]))) if loss else None
    return out


def assemble(cells: list, flips: dict, rates: dict, n_win: int, secs: float) -> dict:
    t0, t1 = span()
    labels, _ends = month_edges(t0, t1)
    pool: dict = {}
    for key in ("all", *TFS):
        rows = [c for c in cells if key == "all" or c["tf"] == key]
        if rows:
            pool[key] = {rule: pooled(rows, rule) for rule in RULES}
    fpool: dict = {}
    for key in ("all", *TFS):
        rows = [v for (tf, _sd), v in flips.items() if key == "all" or tf == key]
        if rows:
            fpool[key] = {rule: pooled(rows, rule) for rule in RULES}
    out_cells = []
    for c in cells:
        row = {"s": c["s"], "tf": c["tf"], "trades": c["trades"], "r": {}}
        for rule in RULES:
            r = c[rule]
            row["r"][rule] = {"full": compact(r["full"]), **{k: compact(r[k]) for k, _a, _b in SPLITS},
                              "w30": [r["w30"][0], r["w30"][1], _s(r["w30"][2], 3), _s(r["w30"][3]), _s(r["w30"][4])],
                              "loss": [_s(r["loss"][0]), _s(r["loss"][1]), r["loss"][2]],
                              "curve": [_g(x / INITIAL, 3) for x in r["full"]["months"]]}
        out_cells.append(row)
    par = [c["parity"] for c in cells] + [v["parity"] for v in flips.values()]
    par = [p for p in par if p]
    return {
        "version": VERSION, "label": "설명용, 판정 아님", "prereg": "docs/size5y.md",
        "generated_at": int(time.time() * 1000), "secs": round(secs, 1), "config": config_key(),
        "rules": [{"key": k, "ko": RULE_KO[k], "short": RULE_SHORT[k], "risk": RISK.get(k)} for k in RULES],
        "periods": [{"key": "full", "ko": SPLIT_KO["full"]}] + [{"key": k, "ko": SPLIT_KO[k]} for k, _a, _b in SPLITS],
        "m_keys": list(M_KEYS), "w_keys": list(W_KEYS), "l_keys": list(L_KEYS),
        "months": labels,
        "account": {"initial": INITIAL, "bust_below": BUST_BELOW, "window_days": WINDOW_DAYS, "stop_atr": K_STOP,
                    "leverage": RULE, "margin_cap": MARGIN_CAP, "windows": n_win, "flip_seeds": list(FLIP_SEEDS),
                    "start": START, "end": "2026-09-29"},
        "flip_rate": {tf: _s(r, 6) for tf, r in rates.items()},
        "parity": {"max_diff": _s(max((p["max_diff"] for p in par), default=0.0), 6),
                   "windows": int(sum(p["windows"] for p in par)), "low_windows": int(sum(p["low_windows"] for p in par)),
                   "skipped": int(sum(p["skipped"] for p in par))},
        "pooled": pool, "flips": fpool, "cells": out_cells,
    }


def write_json(doc: dict, out: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--signals", required=True)
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--work", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "size5y_work"))
    ap.add_argument("--tfs", default=",".join(TFS))
    ap.add_argument("--limit", type=int, default=None, help="first N strategies per timeframe (a quick look only)")
    a = ap.parse_args(argv)
    doc = run(a.signals, a.out, a.work, tuple(a.tfs.split(",")), a.limit)
    log("wrote", a.out, os.path.getsize(a.out), "bytes", json.dumps(doc["parity"]),
        json.dumps({r: doc["pooled"]["all"][r]["full"]["m"][:3] for r in RULES} if "all" in doc["pooled"] else {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
