"""조합 성과: the pure numbers (numpy only, no database), so every figure on the screen can be checked by hand.

    curve_numbers   one equity curve (time, value; the first point is the start): return, P&L, max drawdown (share of
                    the peak and dollars, the peak and the trough), time under water (share of the time, longest
                    stretch), recovery (days from the trough back to the old peak, or not yet)
    day_ends        the value at each Korea-time midnight (and now): the daily P&L and the daily return
    daily_numbers   from the daily P&L: worst / best day, share of winning days, daily volatility, Sharpe-like and
                    Sortino-like ratios (DAILY, not annualised), Calmar-like (return / max drawdown)
    trade_numbers   closed trades: count, win rate, average trade, profit factor (gross win / gross loss), payoff
                    (average win / average loss), longest losing run
    hourly          the value at each full hour; returns or changes between them
    weights         똑같이 / 직접 % / 변동 적은 쪽에 더 (inverse volatility) / 위험 똑같이 (equal risk contribution)
    corr            Pearson correlation of every pair with the number of points (None under the minimum or flat)

Everything is descriptive ('설명용, 판정 아님'). A curve's drawdown is measured from the running peak with the start as
the first peak (a curve that only fell has its drawdown from the start).
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Optional, Sequence

import numpy as np

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
KST_MS = 9 * HOUR_MS
EPS = 1e-9
MIN_VOL_POINTS = 12          # hourly returns a unit needs before its volatility decides a weight
MIN_RATIO_DAYS = 5           # days before the daily volatility, Sharpe-like, Sortino-like and Calmar-like are shown
SHRINK = 0.2                 # risk parity: covariance pulled this far toward its diagonal (few points are noisy)


def r(x, n: int = 6):
    """A JSON-safe rounded float (None for None / NaN / infinity)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, n) if math.isfinite(v) else None


def kst_day(ms: int) -> str:
    return dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def kst_midnight_after(ms: int) -> int:
    """The first Korea-time midnight strictly after ``ms``."""
    return (int(ms) + KST_MS) // DAY_MS * DAY_MS + DAY_MS - KST_MS


# ---------------------------------------------------------------- one curve
def curve_numbers(ts: Sequence[int], eq: Sequence[float], cap: float) -> dict:
    """Numbers of one curve. ``cap`` is the starting value (also the first peak)."""
    t = np.asarray(ts, dtype=np.int64)
    e = np.asarray(eq, dtype=np.float64)
    out = {"start": r(cap, 2), "end": None, "ret": None, "pnl": None, "mdd_pct": 0.0, "mdd_usd": 0.0,
           "mdd_peak_ts": None, "mdd_trough_ts": None, "recovered": None, "recovery_days": None,
           "under_water_share": 0.0, "longest_under_water_days": 0.0, "days_since_peak": 0.0, "points": int(len(e))}
    if not len(e) or not cap or cap <= 0:
        return out
    peak = np.maximum.accumulate(np.maximum(e, cap))
    dd_usd = peak - e
    dd = np.where(peak > 0, dd_usd / peak, 0.0)
    out.update(end=r(e[-1], 2), ret=r(e[-1] / cap - 1), pnl=r(e[-1] - cap, 2))
    i = int(np.argmax(dd))
    if dd[i] > EPS:
        top = peak[i]
        at = np.nonzero(e[: i + 1] >= top - EPS)[0]
        j = int(at[-1]) if len(at) else 0            # the peak it fell from (the start when it never rose)
        after = np.nonzero(e[i:] >= top - EPS)[0]
        rec = int(after[0]) + i if len(after) else None
        out.update(mdd_pct=r(dd[i]), mdd_usd=r(float(dd_usd.max()), 2), mdd_peak_ts=int(t[j]) if len(at) else int(t[0]),
                   mdd_trough_ts=int(t[i]), recovered=rec is not None,
                   recovery_days=r((t[rec] - t[i]) / DAY_MS, 3) if rec is not None else None)
    # time under water, weighted by time (the closed-trade basis has uneven gaps)
    if len(t) > 1:
        dur = np.diff(t).astype(np.float64)
        under = dd[:-1] > EPS
        total = dur.sum()
        out["under_water_share"] = r(float(dur[under].sum() / total) if total > 0 else 0.0, 4)
        longest, run_start = 0.0, None
        for k in range(len(e)):
            if dd[k] > EPS and run_start is None:
                run_start = int(t[k - 1]) if k else int(t[k])
            elif dd[k] <= EPS and run_start is not None:
                longest = max(longest, float(t[k] - run_start))
                run_start = None
        if run_start is not None:
            longest = max(longest, float(t[-1] - run_start))
        out["longest_under_water_days"] = r(longest / DAY_MS, 3)
        at_peak = np.nonzero(dd <= EPS)[0]
        out["days_since_peak"] = r((t[-1] - t[int(at_peak[-1])]) / DAY_MS, 3) if len(at_peak) else r((t[-1] - t[0]) / DAY_MS, 3)
    return out


def calmar_like(ret: Optional[float], mdd_pct: Optional[float]) -> Optional[float]:
    return r(ret / mdd_pct, 4) if ret is not None and mdd_pct and mdd_pct > EPS else None


# ---------------------------------------------------------------- days
def day_ends(ts: Sequence[int], eq: Sequence[float], start: int, now: int, cap: float) -> dict:
    """The value at each Korea-time midnight after ``start`` (and at ``now`` for the day going on): {"days": [KST
    dates], "end": [values], "pnl": [daily P&L], "ret": [daily return], "partial_last": bool}."""
    t = np.asarray(ts, dtype=np.int64)
    e = np.asarray(eq, dtype=np.float64)
    ends, labels = [], []
    m = kst_midnight_after(start)
    while m <= now:
        ends.append(m)
        labels.append(kst_day(m - 1))
        m += DAY_MS
    partial = not ends or ends[-1] < now
    if partial:
        ends.append(int(now))
        labels.append(kst_day(now))
    vals = []
    for x in ends:
        k = int(np.searchsorted(t, x, side="right")) - 1
        vals.append(float(e[k]) if k >= 0 and len(e) else float(cap))
    prev = np.r_[cap, vals[:-1]] if vals else np.zeros(0)
    pnl = np.asarray(vals) - prev if vals else np.zeros(0)
    ret = np.where(prev > 0, pnl / np.where(prev > 0, prev, 1.0), 0.0) if vals else np.zeros(0)
    return {"days": labels, "end": vals, "pnl": pnl.tolist(), "ret": ret.tolist(), "partial_last": bool(partial)}


def daily_numbers(daily: dict, ret_total: Optional[float], mdd_pct: Optional[float],
                  min_days: int = MIN_RATIO_DAYS) -> dict:
    """Daily numbers. The volatility and the three ratios need ``min_days`` days (two days give a 'ratio' of +-0.71
    whatever happened): before that they are None and ``ratio_min_days`` says from when."""
    pnl = np.asarray(daily.get("pnl") or [], dtype=np.float64)
    rr = np.asarray(daily.get("ret") or [], dtype=np.float64)
    n = len(pnl)
    labels = daily.get("days") or []
    out = {"days": n, "partial_last": bool(daily.get("partial_last")),
           "partial_day": labels[-1] if daily.get("partial_last") and labels else None,   # the day still going on
           "worst_day": None, "best_day": None,
           "win_days": None, "win_days_n": None, "daily_vol": None, "sharpe_like": None, "sortino_like": None,
           "calmar_like": calmar_like(ret_total, mdd_pct) if n >= min_days else None, "ratio_min_days": min_days}
    if not n:
        return out
    days = daily.get("days") or [""] * n
    i, j = int(np.argmin(pnl)), int(np.argmax(pnl))
    out["worst_day"] = {"day": days[i], "pnl": r(pnl[i], 2), "ret": r(rr[i])}
    out["best_day"] = {"day": days[j], "pnl": r(pnl[j], 2), "ret": r(rr[j])}
    out["win_days_n"] = int((pnl > EPS).sum())
    out["win_days"] = r(out["win_days_n"] / n, 4)
    if n >= max(2, min_days):
        sd = float(np.std(rr, ddof=1))
        out["daily_vol"] = r(sd)
        if sd > EPS:
            out["sharpe_like"] = r(float(np.mean(rr)) / sd, 4)
        neg = np.minimum(rr, 0.0)
        down = math.sqrt(float(np.mean(neg * neg)))
        if down > EPS:
            out["sortino_like"] = r(float(np.mean(rr)) / down, 4)
    return out


# ---------------------------------------------------------------- trades
def trade_numbers(pnls: Sequence[float]) -> dict:
    """``pnls`` in exit order (already scaled by the member's weight when they come from a combination)."""
    p = np.asarray(pnls, dtype=np.float64)
    n = len(p)
    out = {"trades": n, "wins": 0, "win_rate": None, "avg_trade": None, "profit_factor": None, "payoff": None,
           "avg_win": None, "avg_loss": None, "max_losing_streak": 0}
    if not n:
        return out
    win, loss = p[p > 0], p[p <= 0]
    out.update(wins=int(len(win)), win_rate=r(len(win) / n, 4), avg_trade=r(float(p.mean()), 4))
    gl = -float(loss.sum())
    if gl > EPS:
        out["profit_factor"] = r(float(win.sum()) / gl, 4)
    if len(win):
        out["avg_win"] = r(float(win.mean()), 4)
    if len(loss):
        out["avg_loss"] = r(float(loss.mean()), 4)
    if len(win) and len(loss) and float(loss.mean()) < -EPS:
        out["payoff"] = r(float(win.mean()) / -float(loss.mean()), 4)
    run = worst = 0
    for x in p:
        run = run + 1 if x <= 0 else 0
        worst = max(worst, run)
    out["max_losing_streak"] = worst
    return out


# ---------------------------------------------------------------- hours
def at_hours(ts: Sequence[int], eq: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(ts, dtype=np.int64)
    e = np.asarray(eq, dtype=np.float64)
    m = (t % HOUR_MS) == 0
    return t[m], e[m]


def returns(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    if len(v) < 2:
        return np.zeros(0)
    prev = v[:-1]
    return np.where(prev > 0, np.diff(v) / np.where(prev > 0, prev, 1.0), 0.0)


# ---------------------------------------------------------------- weights
WEIGHT_KO = {"eq": "똑같이", "custom": "직접 %", "invvol": "변동 적은 쪽에 더", "rp": "위험 똑같이"}


def erc(cov: np.ndarray, iters: int = 400, tol: float = 1e-12) -> Optional[np.ndarray]:
    """Equal risk contribution weights (each member's w_i * (Cov w)_i the same) by cyclical coordinate descent
    (Griveau-Billion, Richard and Roncalli 2013): each step solves a w_i^2 + c w_i - b = 0 for w_i > 0."""
    S = np.asarray(cov, dtype=np.float64)
    n = len(S)
    d = np.diag(S)
    if n == 0 or (d <= 0).any() or not np.isfinite(S).all():
        return None
    x = 1.0 / np.sqrt(d)
    x /= x.sum()
    b = 1.0 / n
    for _ in range(iters):
        old = x.copy()
        for i in range(n):
            c = float(S[i] @ x - S[i, i] * x[i])
            x[i] = (-c + math.sqrt(c * c + 4 * S[i, i] * b)) / (2 * S[i, i])
        if np.max(np.abs(x - old)) < tol:
            break
    if not np.isfinite(x).all() or (x <= 0).any():
        return None
    return x / x.sum()


def risk_shares(w: np.ndarray, cov: np.ndarray) -> Optional[list]:
    s = np.asarray(cov) @ np.asarray(w)
    tot = float(np.asarray(w) @ s)
    return [r(float(w[i] * s[i] / tot), 4) for i in range(len(w))] if tot > EPS else None


def weights(method: str, rets: list, custom: Optional[Sequence[float]] = None) -> dict:
    """{"w": [..], "used": method actually used, "note": why another one was used or None, "vol": [..] or None,
    "risk_share": [..] or None, "points": hourly returns used}. ``rets``: each unit's hourly returns on one common
    grid (the same length)."""
    k = len(rets)
    eq = [1.0 / k] * k if k else []
    out = {"w": eq, "used": "eq", "note": None, "vol": None, "risk_share": None, "points": 0}
    if method == "custom":
        p = [max(0.0, float(x)) for x in (custom or [])]
        if len(p) == k and sum(p) > EPS:
            out.update(w=[x / sum(p) for x in p], used="custom")
        else:
            out["note"] = "직접 넣은 %가 맞지 않아 똑같이 나눴습니다"
        return out
    if method not in ("invvol", "rp") or k < 2:
        return out
    R = np.vstack([np.asarray(x, dtype=np.float64) for x in rets]) if k else np.zeros((0, 0))
    n = R.shape[1] if R.ndim == 2 else 0
    out["points"] = int(n)
    if n < MIN_VOL_POINTS:
        out["note"] = f"변동을 잴 1시간 기록이 아직 {n}개뿐이라 ({MIN_VOL_POINTS}개부터) 똑같이 나눴습니다"
        return out
    sd = R.std(axis=1, ddof=1)
    out["vol"] = [r(x) for x in sd]
    if (sd <= EPS).any():
        out["note"] = "아직 한 번도 움직이지 않은 구성원이 있어 변동으로 나눌 수 없어 똑같이 나눴습니다"
        return out
    cov = np.cov(R, ddof=1)
    cov = (1 - SHRINK) * cov + SHRINK * np.diag(np.diag(cov))
    if method == "invvol":
        w = (1.0 / sd) / (1.0 / sd).sum()
        out.update(w=w.tolist(), used="invvol", risk_share=risk_shares(w, cov))
        return out
    w = erc(cov)
    if w is None:
        w = (1.0 / sd) / (1.0 / sd).sum()
        out.update(w=w.tolist(), used="invvol", note="위험을 똑같이 맞추는 계산이 풀리지 않아 변동 적은 쪽에 더 줬습니다",
                   risk_share=risk_shares(w, cov))
        return out
    out.update(w=w.tolist(), used="rp", risk_share=risk_shares(w, cov))
    return out


# ---------------------------------------------------------------- correlation
def corr(M: np.ndarray, min_n: int) -> tuple[list, int]:
    """(matrix with None where a pair cannot be measured, points). Rows = units, columns = the same days / hours."""
    M = np.asarray(M, dtype=np.float64)
    k = M.shape[0] if M.ndim == 2 else 0
    n = M.shape[1] if M.ndim == 2 else 0
    out = [[None] * k for _ in range(k)]
    if k == 0 or n < max(3, min_n):
        for i in range(k):
            out[i][i] = 1.0 if n else None
        return out, int(n)
    sd = M.std(axis=1)
    live = sd > EPS
    with np.errstate(invalid="ignore", divide="ignore"):
        C = np.corrcoef(M)
    for i in range(k):
        for j in range(k):
            if i == j:
                out[i][j] = 1.0 if live[i] else None
            elif live[i] and live[j] and np.isfinite(C[i, j]):
                out[i][j] = r(float(np.clip(C[i, j], -1, 1)), 3)
    return out, int(n)


def thin_index(n: int, keep: Sequence[int] = (), most: int = 600) -> np.ndarray:
    """At most ``most`` indices out of n, evenly spaced, always with the first, the last and ``keep``."""
    if n <= most:
        return np.arange(n)
    idx = set(np.linspace(0, n - 1, most).astype(int).tolist())
    idx.update(int(k) for k in keep if 0 <= int(k) < n)
    idx.update((0, n - 1))
    return np.asarray(sorted(idx))
