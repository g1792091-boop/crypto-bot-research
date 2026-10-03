"""Trendlines (pivot-to-pivot lines) and their features for the trendline entry study.

Implements PREREG_TRENDLINE.md sections 2 and 3 (fixed; hash in PREREG_TRENDLINE.sha256). Nothing
here looks at outcomes. Every feature of signal bar ``i`` uses only bars whose close is at or before
the close of bar ``i`` (tested in tests/test_entry_trendline.py by replacing every later bar with
garbage, and against a slow loop-by-loop reference on every bar).

Lines are drawn on the bar index (not on time), as chart programs do. a[t] = ATR14 of bar t (the
cache's Wilder ATR, column ``atr``).

Swing points (section 2-1): bar j is a swing low if low[j] == min(low[j-5 .. j+5]) and a swing high
  if high[j] == max(high[j-5 .. j+5]) (ties count; the full 11-bar window must exist), i.e.
  sr.pivot_flags. A swing is usable only once bar j+5 has closed (j + 5 <= i).

Support line at bar i (rising, section 2-2):
  B  = the most recent usable swing low; none if B < i - 299 (both points in the last 300 bars).
  A  = scanning the earlier swing lows with low[A] < low[B] from the most recent back (only
       A >= i - 299), the first one with
         slope    m = (low[B] - low[A]) / (B - A) and 0 < m / a[B] <= 0.5, and
         closes   close[t] >= y(t) - 0.25 * a[t] for every bar A < t < B,
       where y(t) = low[A] + m * (t - A). None if no such A.
  A missing ATR (start of the series) makes a candidate fail, so the line is "none".
  Because the conditions on A do not depend on i, A is found once per B (``A*(B)``), scanning
  only A >= B - 294 (an older A could never be inside the window of a bar that can use B), and the
  line of bar i is (A*(B), B) when A*(B) >= i - 299.
Resistance line (falling, section 2-3): the mirror image (high, A higher than B, -0.5 <= m / a[B] < 0,
  closes <= y(t) + 0.25 * a[t]). It is computed as the support line of the negated series
  (-high as lows, -close as closes), which is exact in floating point.
Break (section 2-4): the first bar B < t <= i whose close is beyond the line by more than 0.25 * a[t]
  (support: close[t] < y(t) - 0.25 a[t]; resistance: close[t] > y(t) + 0.25 a[t]) is the break bar.
  A line is "live" at i when it exists and has no break bar <= i. A new swing changes the line from
  the bar where it becomes usable; breaks and touches are always those of the line used at bar i.
Touches (section 2-4, live lines): bars A <= t <= i-1 with low[t] <= y(t) + 0.25 a[t] and
  close[t] >= y(t) - 0.25 a[t] (support; mirror for resistance); a run of consecutive touching bars
  counts once. The signal bar itself is not counted.

Features of a signal (section 3; s = +1 long / -1 short, c = close[i], a = a[i]):
  ahead line  = the line against the trade (long: resistance, short: support)
  behind line = the line behind the trade (long: support, short: resistance)
  tl_ahead      ahead line live: s * (y(i) - c) / a clipped to 0..10; else 10
  tl_behind     behind line live: s * (c - y(i)) / a clipped to 0..10; else 10
  tl_break_now  1 if the ahead line's break bar is i (long: resistance broken upward at i)   [T1]
  tl_against    1 if the ahead line is live and tl_ahead < 2                                 [T2]
  tl_support    1 if the behind line is live and tl_behind < 2                               [T3]
  tl_aligned    1 if the trend matches the side (trend up = only a live support line, down =
                only a live resistance line, both or neither = none)                         [T4]
  tl_touch_ahead / _behind   touch count of the live line (NaN if not live)
  tl_slope_ahead / _behind   m / a[B] of the live line, ATR per bar (NaN if not live)
  tl_age_ahead / _behind     i - A of the live line, bars (NaN if not live)
  tl_break_3 / tl_break_10   ahead line's break bar in i-2 .. i / i-9 .. i
  tl_trend      0 none, 1 up, 2 down, 3 both (descriptive)
All features are NaN when a[i] is missing or <= 0 (excluded from the tests).

Parameters for the candidate-only sensitivity table (PREREG section 7) live in ``Params``; the
pre-registered values are ``DEFAULT``. The break tolerance ``delta`` is used in every "closes beyond
the line" rule (between A and B, the break, and the close part of a touch); ``eps`` is only the touch
distance of the low / high.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import sr  # noqa: E402  (pivot_flags: the same swing definition as part A's L1)


# ------------------------------------------------------------------ constants (PREREG section 2)
@dataclass(frozen=True)
class Params:
    k: int = 5              # swing: k bars on each side, usable from j + k
    window: int = 300       # both points within the last `window` bars (i - window + 1 <= j)
    slope_max: float = 0.5  # |m| / a[B] <= slope_max
    delta: float = 0.25     # a close beyond the line by more than delta * a[t] breaks it
    eps: float = 0.25       # touch: low (high) within eps * a[t] of the line
    near: float = 2.0       # "close" for tl_against / tl_support, ATR (= the 2-ATR stop)
    cap: float = 10.0       # distance cap, ATR


DEFAULT = Params()
TREND_NAME = {0: "none", 1: "up", 2: "down", 3: "both"}
FEATURES = ("tl_ahead", "tl_behind", "tl_break_now", "tl_against", "tl_support", "tl_aligned",
            "tl_touch_ahead", "tl_touch_behind", "tl_slope_ahead", "tl_slope_behind", "tl_age_ahead",
            "tl_age_behind", "tl_break_3", "tl_break_10", "tl_trend")
_CHUNK = 4_000_000          # matrix cells per vectorised block


# ------------------------------------------------------------------ lines on one series
def _blocks(width: np.ndarray, cells: int = _CHUNK):
    """Row blocks [r0, r1) of rows with these widths (sorted ascending by the caller) so that a
    block's rows x its widest row stays <= cells (each block is padded only to its own widest row)."""
    m = len(width)
    if m == 0:
        return
    step = max(1, cells // max(1, int(np.max(width))))
    for r0 in range(0, m, step):
        yield r0, min(m, r0 + step)


def _support_lines(lo: np.ndarray, cl: np.ndarray, atr: np.ndarray, P: Params = DEFAULT) -> dict:
    """Rising support line of every bar (section 2-2 / 2-4) from lows ``lo``, closes ``cl``, ATR ``atr``.

    Returns arrays of length n: has (a line is in use at i), A, B (-1 if none), m (price per bar),
    slope (m / a[B]), y (line value at i), brk (break bar if it is <= i, else -1), touch (touch
    runs in A .. i-1)."""
    lo = np.asarray(lo, float)
    cl = np.asarray(cl, float)
    atr = np.asarray(atr, float)
    n = len(lo)
    K, W = int(P.k), int(P.window)
    out = dict(has=np.zeros(n, bool), A=np.full(n, -1, np.int64), B=np.full(n, -1, np.int64),
               m=np.full(n, np.nan), slope=np.full(n, np.nan), y=np.full(n, np.nan),
               brk=np.full(n, -1, np.int64), touch=np.full(n, -1, np.int64))
    if n == 0:
        return out
    piv = np.flatnonzero(sr.pivot_flags(lo, lo, K)[1])
    npv = len(piv)
    if npv < 2:
        return out
    # ---- A*(B) for every swing low B: candidate pairs (A, B), A in [B - (W - 1 - K), B)
    reach = W - 1 - K
    r0 = np.searchsorted(piv, piv - reach, side="left")
    cnt = np.arange(npv) - r0
    q_of = np.repeat(np.arange(npv), cnt)
    r_of = np.arange(len(q_of)) - np.repeat(np.cumsum(cnt) - cnt, cnt) + np.repeat(r0, cnt)
    Ap, Bp = piv[r_of], piv[q_of]
    keep = lo[Ap] < lo[Bp]
    Ap, Bp, q_of = Ap[keep], Bp[keep], q_of[keep]
    with np.errstate(divide="ignore", invalid="ignore"):
        m = (lo[Bp] - lo[Ap]) / (Bp - Ap)
        r = m / atr[Bp]
    keep = (r > 0) & (r <= P.slope_max)
    Ap, Bp, q_of, m = Ap[keep], Bp[keep], q_of[keep], m[keep]
    ok = np.zeros(len(Ap), bool)
    if len(Ap):
        gap = Bp - Ap
        order = np.argsort(gap, kind="stable")
        for b0, b1 in _blocks(gap[order]):
            sel = order[b0:b1]
            G = int(gap[sel].max())
            if G <= 1:
                ok[sel] = True
                continue
            offs = np.arange(1, G)
            t = Ap[sel, None] + offs[None, :]
            inside = offs[None, :] < gap[sel, None]
            tc = np.minimum(t, n - 1)
            y = lo[Ap[sel], None] + m[sel, None] * offs[None, :]
            good = cl[tc] >= y - P.delta * atr[tc]
            ok[sel] = (good | ~inside).all(axis=1)
    a_star = np.full(npv, -1, np.int64)
    m_star = np.full(npv, np.nan)
    if ok.any():
        qa, aa, ma = q_of[ok], Ap[ok], m[ok]
        o = np.lexsort((aa, qa))                     # by q, then A ascending: the last per q is the most recent A
        qa, aa, ma = qa[o], aa[o], ma[o]
        last = np.r_[qa[1:] != qa[:-1], True]
        a_star[qa[last]] = aa[last]
        m_star[qa[last]] = ma[last]

    # ---- the bars that use each line: i in [B + K, min(next swing usable - 1, A + W - 1, n - 1)]
    has_line = a_star >= 0
    start = piv + K
    nxt = np.r_[piv[1:] + K - 1, n - 1]
    end = np.minimum(np.minimum(nxt, a_star + W - 1), n - 1)
    use = has_line & (start <= end)
    qs = np.flatnonzero(use)
    if not len(qs):
        return out
    A_l, B_l, m_l, s_l, e_l = a_star[qs], piv[qs], m_star[qs], start[qs], end[qs]
    # ---- per line: break bar in (B, end] and touch runs over [A, end - 1], one matrix over [A, end]
    width = e_l - A_l + 1
    order = np.argsort(width, kind="stable")
    brk_l = np.full(len(qs), -1, np.int64)
    for b0, b1 in _blocks(width[order]):
        sel = order[b0:b1]
        Wd = int(width[sel].max())
        offs = np.arange(Wd)
        t = A_l[sel, None] + offs[None, :]
        inside = t <= e_l[sel, None]
        tc = np.minimum(t, n - 1)
        y = lo[A_l[sel], None] + m_l[sel, None] * offs[None, :]
        at = atr[tc]
        after_b = t > B_l[sel, None]
        broken = (cl[tc] < y - P.delta * at) & after_b & inside
        anyb = broken.any(axis=1)
        brk_l[sel] = np.where(anyb, A_l[sel] + broken.argmax(axis=1), -1)
        tch = (lo[tc] <= y + P.eps * at) & (cl[tc] >= y - P.delta * at) & inside
        runs = tch & ~np.concatenate([np.zeros((len(sel), 1), bool), tch[:, :-1]], axis=1)
        cum = np.cumsum(runs, axis=1)
        # bars i of these lines: touch(i) = runs over [A, i - 1] = cum[i - 1 - A]
        nb = e_l[sel] - s_l[sel] + 1
        rows = np.repeat(np.arange(len(sel)), nb)
        ii = np.repeat(s_l[sel], nb) + (np.arange(nb.sum()) - np.repeat(np.cumsum(nb) - nb, nb))
        aa = A_l[sel][rows]
        out["touch"][ii] = cum[rows, ii - 1 - aa]
    # ---- fill the per-bar arrays
    nb = e_l - s_l + 1
    line = np.repeat(np.arange(len(qs)), nb)
    ii = np.repeat(s_l, nb) + (np.arange(nb.sum()) - np.repeat(np.cumsum(nb) - nb, nb))
    out["has"][ii] = True
    out["A"][ii] = A_l[line]
    out["B"][ii] = B_l[line]
    out["m"][ii] = m_l[line]
    with np.errstate(divide="ignore", invalid="ignore"):
        out["slope"][ii] = m_l[line] / atr[B_l[line]]
    out["y"][ii] = lo[A_l[line]] + m_l[line] * (ii - A_l[line])
    bl = brk_l[line]
    out["brk"][ii] = np.where((bl >= 0) & (bl <= ii), bl, -1)
    return out


def lines_for(h, l, c, atr, P: Params = DEFAULT) -> dict:
    """Support and resistance lines of every bar: {'sup': ..., 'res': ...} (see _support_lines).
    Resistance = support of the negated series, mapped back to prices (y, m, slope negated)."""
    h, l, c, atr = (np.asarray(x, float) for x in (h, l, c, atr))
    sup = _support_lines(l, c, atr, P)
    res = _support_lines(-h, -c, atr, P)
    for k in ("m", "slope", "y"):
        res[k] = -res[k]
    return {"sup": sup, "res": res, "params": P}


def _cols(df) -> tuple:
    if isinstance(df, dict):
        return (np.asarray(df["h"], float), np.asarray(df["l"], float), np.asarray(df["c"], float),
                np.asarray(df["atr"], float) if "atr" in df else None)
    return (np.asarray(df["high"], float), np.asarray(df["low"], float), np.asarray(df["close"], float),
            np.asarray(df["atr"], float) if "atr" in df else None)


def bar_atr(df) -> np.ndarray:
    """The cache's ATR14 column, or the backtest's fg.atr(df, 14) (as sr._atr) when there is none."""
    h, l, c, a = _cols(df)
    if a is not None:
        return a
    if isinstance(df, dict):
        df = pd.DataFrame({"open": df["o"], "high": h, "low": l, "close": c})
    return sr._atr(df)


# ------------------------------------------------------------------ features
def features_for(df, sig_idx, side, *, lines: dict | None = None, atr=None, P: Params | None = None) -> dict:
    """Section 3 features for signal bars ``sig_idx`` with sides ``side`` (+1 / -1).

    df     DataFrame (high, low, close[, atr]) or a cache dict (h, l, c[, atr, o]).
    lines  lines_for(...) of the same series (default: computed here with P).
    atr    ATR14 per bar (default: the 'atr' column, else the backtest's fg.atr).
    Returns a dict of arrays aligned with sig_idx."""
    sig_idx = np.asarray(sig_idx, np.int64)
    s = np.asarray(side, int)
    if len(s) != len(sig_idx) or not np.isin(s, (-1, 1)).all():
        raise ValueError("side must be +1/-1, one per signal")
    h, l, c_all, _ = _cols(df)
    a_all = bar_atr(df) if atr is None else np.asarray(atr, float)
    if lines is None:
        lines = lines_for(h, l, c_all, a_all, P or DEFAULT)
    P = lines.get("params", DEFAULT) if P is None else P
    if len(sig_idx) and (sig_idx.min() < 0 or sig_idx.max() >= len(c_all)):
        raise ValueError("signal bar outside the series")
    i = sig_idx
    c = c_all[i]
    a = a_all[i]
    a_ok = np.isfinite(a) & (a > 0)
    long = s == 1
    sup, res = lines["sup"], lines["res"]

    def pick(key):
        return np.where(long, res[key][i], sup[key][i]), np.where(long, sup[key][i], res[key][i])

    (has_ah, has_bh), (brk_ah, brk_bh) = pick("has"), pick("brk")
    (y_ah, y_bh), (A_ah, A_bh) = pick("y"), pick("A")
    (sl_ah, sl_bh), (tc_ah, tc_bh) = pick("slope"), pick("touch")
    live_ah = has_ah & (brk_ah < 0)
    live_bh = has_bh & (brk_bh < 0)
    sup_live = sup["has"][i] & (sup["brk"][i] < 0)
    res_live = res["has"][i] & (res["brk"][i] < 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        d_ah = np.where(live_ah, np.clip(s * (y_ah - c) / a, 0.0, P.cap), P.cap)
        d_bh = np.where(live_bh, np.clip(s * (c - y_bh) / a, 0.0, P.cap), P.cap)
    trend = np.where(sup_live & res_live, 3, np.where(sup_live, 1, np.where(res_live, 2, 0)))
    f = {
        "tl_ahead": d_ah,
        "tl_behind": d_bh,
        "tl_break_now": (has_ah & (brk_ah == i)).astype(float),
        "tl_against": (live_ah & (d_ah < P.near)).astype(float),
        "tl_support": (live_bh & (d_bh < P.near)).astype(float),
        "tl_aligned": ((long & (trend == 1)) | (~long & (trend == 2))).astype(float),
        "tl_touch_ahead": np.where(live_ah, tc_ah, np.nan).astype(float),
        "tl_touch_behind": np.where(live_bh, tc_bh, np.nan).astype(float),
        "tl_slope_ahead": np.where(live_ah, sl_ah, np.nan),
        "tl_slope_behind": np.where(live_bh, sl_bh, np.nan),
        "tl_age_ahead": np.where(live_ah, i - A_ah, np.nan).astype(float),
        "tl_age_behind": np.where(live_bh, i - A_bh, np.nan).astype(float),
        "tl_break_3": (has_ah & (brk_ah >= 0) & (brk_ah >= i - 2)).astype(float),
        "tl_break_10": (has_ah & (brk_ah >= 0) & (brk_ah >= i - 9)).astype(float),
        "tl_trend": trend.astype(float),
    }
    out = {"sig_idx": sig_idx, "side": s.astype(np.int8), "close": c, "atr": a,
           "y_ahead": np.where(has_ah, y_ah, np.nan), "y_behind": np.where(has_bh, y_bh, np.nan),
           "live_ahead": live_ah, "live_behind": live_bh}
    for k in FEATURES:
        out[k] = np.where(a_ok, f[k], np.nan)
    return out


def params_dict(P: Params = DEFAULT) -> dict:
    return asdict(P)


# ------------------------------------------------------------------ timing helper (no outcomes)
def _time(tf: str = "5m", coin: str = "BTCUSD", sig_dir: str = sr.DEFAULT_SIG_DIR) -> None:
    import time
    t0 = time.time()
    z = dict(np.load(os.path.join(sig_dir, f"sig_{tf}_{coin}.npz")))
    t1 = time.time()
    ln = lines_for(z["h"], z["l"], z["c"], z["atr"])
    t2 = time.time()
    idx = np.arange(len(z["c"]))
    for s in (1, -1):
        features_for(z, idx, np.full(len(idx), s), lines=ln)
    t3 = time.time()
    print(f"{tf} {coin}: {len(idx)} bars; load {t1 - t0:.1f}s, lines {t2 - t1:.1f}s, features (all bars x 2 sides) "
          f"{t3 - t2:.1f}s", flush=True)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "time":
        _time(*(sys.argv[2:4]))
    else:
        print(__doc__)
