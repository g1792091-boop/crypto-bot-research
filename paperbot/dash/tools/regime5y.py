"""장세 스위치 (5년 자료): does a locked strategy lose mainly because it runs in the wrong kind of market? Offline
generator for paperbot/dash/data/regime5y.json (served by paperbot/dash/more/regime5y.py, drawn by
screens/analysis-regime.js). Pre-registered in docs/regime5y.md before any result was looked at; every constant below
is that document's. Read-only research: the engines are imported, never changed; nothing touches a bot database.

    python -m paperbot.dash.tools.regime5y --signals <signal cache dir> [--out paperbot/dash/data/regime5y.json] \
        [--work <checkpoint dir>]

One worker process. ``--work``: one checkpoint file per (timeframe, strategy) and per (timeframe, coin-flip job), so a
killed run resumes; a run with other constants uses its own sub folder (``config_key``).

What (docs/regime5y.md):
- Regimes per coin and bar from data up to that bar's close (``regimes``): 급변 (ATR% in the top 20% of its own
  trailing 365-day window, at least 180 days of history), then 추세 (ADX14 >= 25 and |EMA50 slope over 10 bars| >= 0.5
  ATR), then 횡보 (ADX14 < 20), else 보통; nothing known yet = 모름. A trade's regime is its signal bar's.
- Accounts: rules_bt.simulate (keep_trades) with research/power/power.py's quality_v1 shim, $5,000, 2 ATR stop, fresh
  every 30 days, windows never cross a period boundary (``windows``). Periods: pick 2021-07..2022-12, A 2023-24,
  B 2025-01..2026-09.
- Rule per strategy x timeframe: R = the regimes (>= 30 pick-period trades) whose pick-period mean net R beats the
  cell's pick-period mean (``choose_rule``); empty or all four = no rule.
- Test (``cell_test``): on A+B, (mean in R - mean outside R) of the strategy minus the same for coin flips (median
  signal rate of the 36, seeds 1-3) under the same R; one-sided z; Benjamini-Hochberg q 0.05 over every tested cell;
  a survivor also has a positive gap in A and in B separately.
- Shown too (descriptive): per regime trades / win rate / mean net R / dollar P&L, and the switched accounts (only R
  signals kept, re-simulated) in A and B next to the base account and the coin flips with the same switch.
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
from typing import Iterable, Optional, Sequence

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RULES_DIR = os.path.join(ROOT, "research", "paper_rules")
POWER_DIR = os.path.join(ROOT, "research", "power")
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "regime5y.json")

VERSION = 1
TFS = ("15m", "30m", "1h", "4h")
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")     # rules_bt.COINS (entry priority order)
# regimes (docs/regime5y.md)
ADX_N, EMA_N, SLOPE_BARS = 14, 50, 10
ADX_TREND, ADX_RANGE, SLOPE_MIN = 25.0, 20.0, 0.5
VOL_Q, VOL_DAYS, VOL_MIN_DAYS = 0.80, 365, 180
UNKNOWN, TREND, RANGE, SHOCK, NORMAL = 0, 1, 2, 3, 4
REGIMES = (TREND, RANGE, SHOCK, NORMAL)
RKEY = {UNKNOWN: "unknown", TREND: "trend", RANGE: "range", SHOCK: "shock", NORMAL: "normal"}
RKO = {UNKNOWN: "모름", TREND: "추세장", RANGE: "횡보장", SHOCK: "급변장", NORMAL: "보통"}
# periods and accounts
PERIODS = (("pick", "2021-07-01", "2023-01-01"), ("a", "2023-01-01", "2025-01-01"), ("b", "2025-01-01", "2026-09-30"))
PERIOD_KO = {"pick": "고르는 기간 2021-07 ~ 2022-12", "a": "확인 A 2023 ~ 2024", "b": "확인 B 2025-01 ~ 2026-09"}
WINDOW_DAYS, MIN_TAIL_DAYS = 30, 10
INITIAL = 5000.0
K_STOP = 2.0
RULE = "quality_v1"
SEED = 20261006
# rule choice and test
MIN_PICK = 30
MIN_TEST = 20
FDR_Q = 0.05
FLIP_SEEDS = (1, 2, 3)

NS_DAY = 86_400 * 10 ** 9


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def day_ns(s: str) -> int:
    return int(np.datetime64(s, "ns").astype(np.int64))


# ---------------------------------------------------------------- regimes (pure, causal)
def rma(x: np.ndarray, n: int, start: int = 0) -> np.ndarray:
    """Wilder's moving average of x[start:]: the first value (index start + n - 1) is the plain mean of n values, then
    y = y_prev + (x - y_prev) / n. NaN before. Causal: y[t] uses x up to t only."""
    import pandas as pd
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    first = start + n - 1
    if first >= len(x):
        return out
    s = np.full(len(x) - first, np.nan)
    s[0] = float(np.mean(x[start:first + 1]))
    s[1:] = x[first + 1:]
    out[first:] = pd.Series(s).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()
    return out


def adx_atr(h: np.ndarray, lo: np.ndarray, c: np.ndarray, n: int = ADX_N) -> tuple[np.ndarray, np.ndarray]:
    """(ADX, ATR) by Wilder. Bar 0 has no previous close, so the true range, +DM and -DM start at bar 1."""
    h, lo, c = (np.asarray(v, float) for v in (h, lo, c))
    N = len(c)
    tr, pdm, mdm = np.zeros(N), np.zeros(N), np.zeros(N)
    if N < 2:
        return np.full(N, np.nan), np.full(N, np.nan)
    pc = c[:-1]
    tr[1:] = np.maximum.reduce([h[1:] - lo[1:], np.abs(h[1:] - pc), np.abs(lo[1:] - pc)])
    up, dn = h[1:] - h[:-1], lo[:-1] - lo[1:]
    pdm[1:] = np.where((up > dn) & (up > 0), up, 0.0)
    mdm[1:] = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = rma(tr, n, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100.0 * rma(pdm, n, 1) / atr
        mdi = 100.0 * rma(mdm, n, 1) / atr
        dx = 100.0 * np.abs(pdi - mdi) / (pdi + mdi)
    dx = np.where(np.isfinite(dx), dx, np.nan)
    ok = np.nonzero(np.isfinite(dx))[0]
    adx = np.full(N, np.nan)
    if len(ok):
        s0 = int(ok[0])
        d = np.nan_to_num(dx, nan=0.0)        # a flat stretch (+DI = -DI = 0) counts as no direction
        adx = rma(d, n, s0)
    return adx, atr


def ema(x: np.ndarray, n: int) -> np.ndarray:
    """EMA seeded with the first value, NaN for the first n - 1 bars (not settled)."""
    import pandas as pd
    out = pd.Series(np.asarray(x, float)).ewm(span=n, adjust=False).mean().to_numpy()
    out[:n - 1] = np.nan
    return out


def vol_threshold(atrp: np.ndarray, bars_per_day: float, days: int = VOL_DAYS, min_days: int = VOL_MIN_DAYS,
                  q: float = VOL_Q) -> np.ndarray:
    """The ``q`` quantile of ATR% over the trailing ``days`` of bars, this bar included; NaN under ``min_days``."""
    import pandas as pd
    w = max(2, int(round(days * bars_per_day)))
    mp = max(2, int(round(min_days * bars_per_day)))
    return pd.Series(np.asarray(atrp, float)).rolling(w, min_periods=mp).quantile(q).to_numpy()


def indicators(h, lo, c) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(ADX14, EMA50 slope over 10 bars in ATR units, ATR%) per bar, each from bars 0..t only."""
    adx, atr = adx_atr(h, lo, c)
    e = ema(c, EMA_N)
    c = np.asarray(c, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        slope = np.full(len(c), np.nan)
        slope[SLOPE_BARS:] = (e[SLOPE_BARS:] - e[:-SLOPE_BARS]) / atr[SLOPE_BARS:]
        atrp = atr / c
    return adx, slope, atrp


def label_codes(adx, slope, atrp, vq) -> np.ndarray:
    """The regime of each bar (급변 > 추세 > 횡보 > 보통; 모름 where any input is missing). ``vq``: the ATR% threshold
    per bar (an array) or one number (the live view's fixed threshold)."""
    adx, slope, atrp = (np.asarray(x, float) for x in (adx, slope, atrp))
    vq = np.broadcast_to(np.asarray(vq, float), adx.shape)
    known = np.isfinite(adx) & np.isfinite(slope) & np.isfinite(atrp) & np.isfinite(vq)
    code = np.full(len(adx), NORMAL, np.int8)
    code[np.nan_to_num(adx, nan=99.0) < ADX_RANGE] = RANGE
    code[(np.nan_to_num(adx) >= ADX_TREND) & (np.abs(np.nan_to_num(slope)) >= SLOPE_MIN)] = TREND
    code[np.nan_to_num(atrp) >= np.nan_to_num(vq, nan=np.inf)] = SHOCK
    code[~known] = UNKNOWN
    return code


def regimes(h, lo, c, tf_min: int, vol_days: int = VOL_DAYS, vol_min_days: int = VOL_MIN_DAYS) -> dict:
    """{code: int8 per bar, adx, slope, atrp, vol_q}. Each value at bar t uses bars 0..t only."""
    adx, slope, atrp = indicators(h, lo, c)
    vq = vol_threshold(atrp, 1440.0 / tf_min, vol_days, vol_min_days)
    return {"code": label_codes(adx, slope, atrp, vq), "adx": adx, "slope": slope, "atrp": atrp, "vol_q": vq}


# ---------------------------------------------------------------- windows (pure)
def windows(start_ns: int, end_ns: int, days: int = WINDOW_DAYS, min_tail_days: int = MIN_TAIL_DAYS) -> list:
    """Consecutive [w0, w1) of ``days`` inside [start, end); a last piece of at least ``min_tail_days`` is kept."""
    span, out, w0 = days * NS_DAY, [], int(start_ns)
    while w0 + span <= end_ns:
        out.append((w0, w0 + span))
        w0 += span
    if end_ns - w0 >= min_tail_days * NS_DAY:
        out.append((w0, int(end_ns)))
    return out


def period_windows(periods=PERIODS) -> list:
    """[(period key, w0, w1)] over every period, never crossing a period's edges."""
    out = []
    for key, a, b in periods:
        out += [(key, w0, w1) for w0, w1 in windows(day_ns(a), day_ns(b))]
    return out


def bounds_for(bars: dict, w0: int, w1: int, warmup: int) -> dict:
    return {c: (max(int(np.searchsorted(bars[c]["ts"], w0)), int(warmup)), int(np.searchsorted(bars[c]["ts"], w1)))
            for c in bars}


# ---------------------------------------------------------------- money of one window (pure)
def window_pnl(R: np.ndarray, mf: np.ndarray, initial: float = INITIAL) -> np.ndarray:
    """Dollar P&L of each trade of a compounding account: R = P&L / margin, mf = margin / equity before."""
    g = np.asarray(R, float) * np.asarray(mf, float)
    if not len(g):
        return np.zeros(0)
    eq = initial * np.concatenate(([1.0], np.cumprod(1.0 + g)[:-1]))
    return eq * g


# ---------------------------------------------------------------- statistics (pure)
def summary(R: np.ndarray, pnl: Optional[np.ndarray] = None) -> list:
    """[trades, win rate, mean net R, dollar P&L sum, variance of R] (None where there is nothing)."""
    R = np.asarray(R, float)
    n = int(len(R))
    if not n:
        return [0, None, None, 0.0 if pnl is not None else None, None]
    return [n, float((R > 0).mean()), float(R.mean()), None if pnl is None else float(np.sum(pnl)),
            float(R.var(ddof=1)) if n > 1 else None]


def by_regime(reg: np.ndarray, R: np.ndarray, pnl: np.ndarray) -> dict:
    reg = np.asarray(reg)
    return {RKEY[k]: summary(R[reg == k], pnl[reg == k]) for k in (*REGIMES, UNKNOWN) if (reg == k).any()}


def choose_rule(reg: np.ndarray, R: np.ndarray, min_n: int = MIN_PICK) -> Optional[list]:
    """R chosen on the pick period's trades only: the regimes with >= ``min_n`` trades whose mean net R is above the
    mean of all the period's trades (regime known). None = no rule (nothing qualifies, or all four would)."""
    reg, R = np.asarray(reg), np.asarray(R, float)
    known = reg != UNKNOWN
    if not known.any():
        return None
    overall = float(R[known].mean())
    pick = [k for k in REGIMES if (reg == k).sum() >= min_n and float(R[reg == k].mean()) > overall]
    if not pick or len(pick) == len(REGIMES):
        return None
    return pick


def gap(reg: np.ndarray, R: np.ndarray, rule: Sequence[int]) -> dict:
    """Mean net R inside the rule's regimes minus outside (regime known): {gap, var, n_in, n_out}."""
    reg, R = np.asarray(reg), np.asarray(R, float)
    inside = np.isin(reg, list(rule))
    outside = (~inside) & (reg != UNKNOWN)
    a, b = R[inside], R[outside]
    if len(a) < 2 or len(b) < 2:
        return {"gap": None, "var": None, "n_in": int(len(a)), "n_out": int(len(b))}
    return {"gap": float(a.mean() - b.mean()), "var": float(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)),
            "n_in": int(len(a)), "n_out": int(len(b))}


def z_test(s: dict, f: dict) -> tuple[Optional[float], Optional[float]]:
    """One-sided z and p of (strategy gap - coin-flip gap) > 0."""
    if s["gap"] is None or f["gap"] is None:
        return None, None
    se = math.sqrt(max(s["var"] + f["var"], 0.0))
    if se <= 0:
        return None, None
    z = (s["gap"] - f["gap"]) / se
    return z, 0.5 * math.erfc(z / math.sqrt(2.0))


def bh(pvals: Sequence[float]) -> list:
    """Benjamini-Hochberg q-values (same order as ``pvals``)."""
    p = np.asarray(pvals, float)
    m = len(p)
    if not m:
        return []
    order = np.argsort(p)
    q = p[order] * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(q, 1.0)
    return out.tolist()


def cell_test(base: dict, flips: dict, rule: Optional[list], min_n: int = MIN_TEST) -> dict:
    """base / flips: {period: (reg, R)} trades of the strategy's base account and the pooled coin flips.
    The pre-registered test on A+B plus the same gap in A and in B (see the module note)."""
    if rule is None:
        return {"status": "norule"}
    cat = lambda d, ks: (np.concatenate([d[k][0] for k in ks]), np.concatenate([d[k][1] for k in ks]))  # noqa: E731
    s_ab, f_ab = gap(*cat(base, ("a", "b")), rule), gap(*cat(flips, ("a", "b")), rule)
    per = {}
    for k in ("a", "b"):
        s, f = gap(*base[k], rule), gap(*flips[k], rule)
        per[k] = {"s": s["gap"], "f": f["gap"], "n_in": s["n_in"], "n_out": s["n_out"],
                  "diff": None if s["gap"] is None or f["gap"] is None else s["gap"] - f["gap"]}
    out = {"s": s_ab["gap"], "f": f_ab["gap"], "n_in": s_ab["n_in"], "n_out": s_ab["n_out"], "per": per}
    if s_ab["n_in"] < min_n or s_ab["n_out"] < min_n:
        return {**out, "status": "small"}
    z, p = z_test(s_ab, f_ab)
    if p is None:
        return {**out, "status": "small"}
    return {**out, "status": "tested", "z": z, "p": p}


def finish_tests(cells: list, q: float = FDR_Q) -> dict:
    """BH over every tested cell; a survivor also has a positive gap in A and in B. Writes q / survivor in place."""
    tested = [c for c in cells if c["test"]["status"] == "tested"]
    for c, qv in zip(tested, bh([c["test"]["p"] for c in tested])):
        t = c["test"]
        t["q"] = qv
        both = all((t["per"][k]["diff"] or 0) > 0 and t["per"][k]["diff"] is not None for k in ("a", "b"))
        t["bh"] = qv <= q
        t["survivor"] = bool(qv <= q and both)
    for c in cells:
        c["test"].setdefault("survivor", False)
    return {"cells": len(cells), "tested": len(tested), "bh_pass": sum(1 for c in tested if c["test"]["bh"]),
            "survivors": sum(1 for c in cells if c["test"]["survivor"]),
            "small": sum(1 for c in cells if c["test"]["status"] == "small"),
            "norule": sum(1 for c in cells if c["test"]["status"] == "norule")}


def mask_signals(sig: np.ndarray, code: np.ndarray, rule: Sequence[int]) -> np.ndarray:
    """The switch: keep a signal only when its bar's regime is in ``rule`` (모름 is never in a rule)."""
    keep = np.isin(code, list(rule))
    return np.where(keep, sig, 0).astype(np.int8)


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
def v4_account(RB):
    """rules_bt accounts start at $5,000 while the block runs (rules_bt.py itself is unchanged)."""
    old = RB.INITIAL
    RB.INITIAL = INITIAL
    try:
        yield
    finally:
        RB.INITIAL = old


def run_account(RB, PW, L, bars: dict, sigs: dict, code: dict, tf: str, wins: list, seed0: int,
                only: Optional[Iterable[str]] = None) -> dict:
    """The 30-day accounts over ``wins`` ([(period, w0, w1)]): {period: (regime, R, pnl, lev)} of their trades."""
    keep = set(only) if only else None
    acc: dict = {}
    warm = L.warmup_bars(tf)
    with v4_account(RB):
        for wi, (pk, w0, w1) in enumerate(wins):
            if keep and pk not in keep:
                continue
            b = bounds_for(bars, w0, w1, warm)
            with PW.leverage_rule(RULE, tf, seed0 + wi):
                r = RB.simulate(bars, sigs, b, K_STOP, tf, L, keep_trades=True)
            t = r["trade_table"]
            if not len(t):
                continue
            coin = t["coin"].to_numpy()
            i = t["i"].to_numpy()
            reg = np.array([code[COINS[p]][j] for p, j in zip(coin, i)], np.int8)
            R = t["R"].to_numpy(float)
            pnl = window_pnl(R, t["margin_frac"].to_numpy(float))
            acc.setdefault(pk, []).append((reg, R, pnl, t["lev"].to_numpy(int)))
    out = {}
    for pk, parts in acc.items():
        out[pk] = tuple(np.concatenate([p[k] for p in parts]) for k in range(4))
    return out


def empty4():
    return (np.zeros(0, np.int8), np.zeros(0), np.zeros(0), np.zeros(0, int))


# ---------------------------------------------------------------- checkpoints
def config_key() -> str:
    cfg = dict(v=VERSION, adx=(ADX_N, ADX_TREND, ADX_RANGE), ema=(EMA_N, SLOPE_BARS, SLOPE_MIN),
               vol=(VOL_Q, VOL_DAYS, VOL_MIN_DAYS), periods=PERIODS, win=(WINDOW_DAYS, MIN_TAIL_DAYS), init=INITIAL,
               k=K_STOP, rule=RULE, seed=SEED, pick=MIN_PICK, test=MIN_TEST, seeds=FLIP_SEEDS)
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:10]


def _save(path: str, arrays: dict) -> None:
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **arrays)
    os.replace(tmp, path)


def _pack(res: dict, prefix: str = "") -> dict:
    out = {}
    for pk, (reg, R, pnl, lev) in res.items():
        out.update({f"{prefix}{pk}__reg": reg, f"{prefix}{pk}__R": R, f"{prefix}{pk}__pnl": pnl, f"{prefix}{pk}__lev": lev})
    return out


def _unpack(z, prefix: str = "") -> dict:
    out = {}
    for pk, _a, _b in PERIODS:
        if f"{prefix}{pk}__R" in z:
            out[pk] = tuple(z[f"{prefix}{pk}__{k}"] for k in ("reg", "R", "pnl", "lev"))
    return out


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


def run(sig_dir: str, out: str, work: str) -> dict:
    RB, PW, L = _rb(), _power(), _lib()
    work = os.path.join(work, config_key())
    os.makedirs(work, exist_ok=True)
    wins = period_windows()
    t_start = time.time()
    cells, regime_share, live_q, rates = [], {}, {}, {}
    for tf in TFS:
        bars = load_tf(sig_dir, tf)
        names = strategy_names(bars)
        code, share = {}, np.zeros(5, np.int64)
        lo_ns = day_ns(PERIODS[0][1])
        for c in COINS:
            b = bars[c]
            rg = regimes(b["h"], b["l"], b["c"], TF_MIN[tf])
            code[c] = rg["code"]
            lo = int(np.searchsorted(b["ts"], lo_ns))
            share += np.bincount(rg["code"][lo:], minlength=5)
            live_q.setdefault(tf, {})[c] = None if not np.isfinite(rg["vol_q"][-1]) else float(rg["vol_q"][-1])
        regime_share[tf] = {RKEY[k]: float(share[k] / max(share.sum(), 1)) for k in (*REGIMES, UNKNOWN)}
        rates[tf] = flip_rate(bars, names, lo_ns)
        # coin flips: base accounts, seeds 1-3 (checkpointed)
        flips_base = {}
        for sd in FLIP_SEEDS:
            p = os.path.join(work, f"flip_{tf}_{sd}.npz")
            if not os.path.exists(p):
                sg = RB.random_signals(bars, None, rates[tf], sd, tf, L)
                _save(p, _pack(run_account(RB, PW, L, bars, sg, code, tf, wins, SEED + 7919 * sd)))
            with np.load(p) as z:
                flips_base[sd] = _unpack(z)
        pooled = {pk: tuple(np.concatenate([flips_base[sd].get(pk, empty4())[k] for sd in FLIP_SEEDS]) for k in range(4))
                  for pk, _a, _b in PERIODS}
        switched_flips: dict = {}
        for si, name in enumerate(names):
            p = os.path.join(work, f"cell_{tf}_{name}.npz")
            sg = {c: bars[c]["s__" + name] for c in COINS}
            if not os.path.exists(p):
                base = run_account(RB, PW, L, bars, sg, code, tf, wins, SEED + 1000 * si)
                bp = base.get("pick", empty4())
                rule = choose_rule(bp[0], bp[1])
                arrays = _pack(base)
                arrays["rule"] = np.array(rule or [], np.int8)
                if rule:
                    sw = run_account(RB, PW, L, bars, {c: mask_signals(sg[c], code[c], rule) for c in COINS}, code, tf,
                                     wins, SEED + 1000 * si + 500, only=("a", "b"))
                    arrays.update(_pack(sw, "sw_"))
                _save(p, arrays)
            with np.load(p) as z:
                base, sw = _unpack(z), _unpack(z, "sw_")
                rule = [int(x) for x in z["rule"]] or None
            if rule:
                key = tuple(rule)
                if key not in switched_flips:
                    fp = os.path.join(work, f"flipsw_{tf}_{'-'.join(map(str, key))}.npz")
                    if not os.path.exists(fp):
                        arr = {}
                        for sd in FLIP_SEEDS:
                            fsg = RB.random_signals(bars, None, rates[tf], sd, tf, L)
                            res = run_account(RB, PW, L, bars, {c: mask_signals(fsg[c], code[c], rule) for c in COINS},
                                              code, tf, wins, SEED + 7919 * sd + 500, only=("a", "b"))
                            arr.update(_pack(res, f"s{sd}_"))
                        _save(fp, arr)
                    with np.load(fp) as z:
                        switched_flips[key] = {sd: _unpack(z, f"s{sd}_") for sd in FLIP_SEEDS}
            cells.append(cell_row(name, tf, base, sw, rule, pooled, flips_base,
                                  switched_flips.get(tuple(rule)) if rule else None))
        log(tf, "done", len(names), "strategies", f"{time.time() - t_start:.0f}s")
    head = finish_tests(cells)
    doc = assemble(cells, head, regime_share, live_q, rates, time.time() - t_start)
    write_json(doc, out)
    return doc


def _s(x, k=4):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, k) if math.isfinite(v) else None


def compact(row: list) -> list:
    """[n, win, meanR, pnl] rounded (the variance is dropped for the page)."""
    n, w, m, p = row[:4]
    return [int(n), _s(w, 3), _s(m, 4), _s(p, 0)]


def flips_mean(per_seed: dict, pk: str) -> list:
    """Coin flips as one row: trades and P&L as the average per seed (one flip account's worth), win rate and mean
    net R over the pooled trades."""
    parts = [per_seed[sd].get(pk, empty4()) for sd in FLIP_SEEDS]
    R = np.concatenate([p[1] for p in parts])
    pnl = np.concatenate([p[2] for p in parts])
    row = summary(R, pnl)
    k = len(FLIP_SEEDS)
    return [round(row[0] / k, 1), _s(row[1], 3), _s(row[2], 4), _s((row[3] or 0.0) / k, 0)]


def cell_row(name, tf, base, sw, rule, pooled, flips_base, flips_sw) -> dict:
    full = tuple(np.concatenate([base.get(pk, empty4())[k] for pk, _a, _b in PERIODS]) for k in range(4))
    regs = {"all": {k: compact(v) for k, v in by_regime(full[0], full[1], full[2]).items()}}
    tot = {"all": compact(summary(full[1], full[2]))}
    for pk, _a, _b in PERIODS:
        b = base.get(pk, empty4())
        regs[pk] = {k: compact(v) for k, v in by_regime(b[0], b[1], b[2]).items()}
        tot[pk] = compact(summary(b[1], b[2]))
    bp = base.get("pick", empty4())
    known = bp[0] != UNKNOWN
    pick_mean = float(bp[1][known].mean()) if known.any() else None
    test = cell_test({k: base.get(k, empty4())[:2] for k in ("a", "b")}, {k: pooled[k][:2] for k in ("a", "b")}, rule)
    row = {"s": name, "tf": tf, "rule": [RKEY[k] for k in rule] if rule else None, "pick_mean": _s(pick_mean),
           "total": tot, "regimes": regs, "test": test}
    if rule:
        sw_rows, stops = {}, True
        for pk in ("a", "b"):
            b, s = base.get(pk, empty4()), sw.get(pk, empty4())
            srow = compact(summary(s[1], s[2]))
            sw_rows[pk] = {"base": compact(summary(b[1], b[2])), "switch": srow,
                           "flip_base": flips_mean(flips_base, pk), "flip_switch": flips_mean(flips_sw, pk)}
            stops = stops and srow[2] is not None and srow[2] > 0
        row["switch"] = sw_rows
        row["stops_losing"] = stops
        row["flip_stops_losing"] = all((sw_rows[pk]["flip_switch"][2] or -1) > 0 for pk in ("a", "b"))
    return row


def _round_test(t: dict) -> dict:
    out = {k: t[k] for k in ("status",) if k in t}
    for k in ("s", "f", "z", "p", "q"):
        if t.get(k) is not None:
            out[k] = _s(t[k], 5 if k in ("p", "q") else 4)
    for k in ("n_in", "n_out", "bh", "survivor"):
        if k in t:
            out[k] = t[k]
    if "per" in t:
        out["per"] = {pk: {kk: (_s(v, 4) if isinstance(v, float) else v) for kk, v in d.items()} for pk, d in t["per"].items()}
    return out


def assemble(cells: list, head: dict, share: dict, live_q: dict, rates: dict, secs: float) -> dict:
    for c in cells:
        c["test"] = _round_test(c["test"])
    withrule = [c for c in cells if c.get("switch")]
    base_lose_ab = sum(1 for c in cells if all((c["total"][pk][2] or 0) <= 0 for pk in ("a", "b")))
    usd_up = lambda row: row is not None and (row[3] or 0) > 0  # noqa: E731  (the dollar P&L of the 30-day accounts)
    tested = [c for c in cells if c["test"].get("status") == "tested"]
    head = {**head, "with_rule": len(withrule), "stops_losing": sum(1 for c in withrule if c["stops_losing"]),
            "flip_stops_losing": sum(1 for c in withrule if c["flip_stops_losing"]),
            "survivors_stop_losing": sum(1 for c in withrule if c["stops_losing"] and c["test"]["survivor"]),
            "base_losing_both": base_lose_ab,
            "base_positive_both": sum(1 for c in cells if all((c["total"][pk][2] or 0) > 0 for pk in ("a", "b"))),
            # the same counts in dollars (descriptive; the pre-registered "손실이 멈췄나" is the per-trade mean above):
            # a mean net ROE above 0 can still lose dollars when the bigger trades lose
            "stops_losing_usd": sum(1 for c in withrule if all(usd_up(c["switch"][pk]["switch"]) for pk in ("a", "b"))),
            "flip_stops_losing_usd": sum(1 for c in withrule
                                         if all(usd_up(c["switch"][pk]["flip_switch"]) for pk in ("a", "b"))),
            "base_positive_both_usd": sum(1 for c in cells if all(usd_up(c["total"][pk]) for pk in ("a", "b"))),
            "p05": sum(1 for c in tested if (c["test"].get("p") if c["test"].get("p") is not None else 1.0) < 0.05)}
    return {
        "version": VERSION, "label": "설명용, 판정 아님", "prereg": "docs/regime5y.md",
        "generated_at": int(time.time() * 1000), "secs": round(secs, 1), "config": config_key(),
        "regimes": [{"key": RKEY[k], "ko": RKO[k]} for k in (TREND, RANGE, SHOCK, NORMAL, UNKNOWN)],
        "defs": {"adx_n": ADX_N, "adx_trend": ADX_TREND, "adx_range": ADX_RANGE, "ema_n": EMA_N, "slope_bars": SLOPE_BARS,
                 "slope_min": SLOPE_MIN, "vol_q": VOL_Q, "vol_days": VOL_DAYS, "vol_min_days": VOL_MIN_DAYS},
        "periods": [{"key": k, "from": a, "to": b, "ko": PERIOD_KO[k]} for k, a, b in PERIODS],
        "account": {"initial": INITIAL, "window_days": WINDOW_DAYS, "stop_atr": K_STOP, "leverage": RULE,
                    "min_pick": MIN_PICK, "min_test": MIN_TEST, "fdr_q": FDR_Q, "flip_seeds": list(FLIP_SEEDS)},
        "flip_rate": {tf: _s(r, 6) for tf, r in rates.items()},
        "share": {tf: {k: _s(v, 4) for k, v in d.items()} for tf, d in share.items()},
        "live_vol_q": {tf: {c: _s(v, 6) for c, v in d.items()} for tf, d in live_q.items()},
        "live_vol_q_asof": "2026-09-29",
        "head": head,
        "cells": cells,
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
    ap.add_argument("--work", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "regime5y_work"))
    a = ap.parse_args(argv)
    doc = run(a.signals, a.out, a.work)
    log("wrote", a.out, os.path.getsize(a.out), "bytes", json.dumps(doc["head"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
