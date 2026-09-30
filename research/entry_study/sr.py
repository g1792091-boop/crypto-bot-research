"""Support / resistance levels and features for the entry study, part A.

Implements PREREG_ENTRY.md section 2 (fixed; hash in PREREG_ENTRY.sha256). Nothing here looks
at outcomes. Every level of signal bar ``i`` uses only bars whose close is at or before the
close of bar ``i`` (tested in tests/test_entry_sr.py by replacing every later bar with garbage).

Levels (per signal bar i, c = close[i]):
  L1 swing   bar j is a swing high if high[j] == max(high[j-5 .. j+5]) (ties count; j needs the
             full 11-bar window), usable only from bar j+5 on (j + 5 <= i). The 10 most recent
             swing highs and the 10 most recent swing lows with j in the last 300 bars
             (i-299 <= j).
  L2 day     high / low of the chart bars whose open time falls on the UTC calendar day before
             the signal bar's day (NaN when that day has no bars).
  L3 week    same for the Monday-00:00-UTC week before the signal bar's week.
  L4 round   multiples of step = 5 * 10 ** (floor(log10(c)) - 1): only the nearest ones matter.
             Each level is the float nearest to the exact decimal multiple (0.3, not
             6 * 0.05 = 0.30000000000000004), so it ties exactly with a price quoted at 0.3.
  L5 volume  last 200 bars INCLUDING bar i, 50 equal price bins over [min low, max high] of
             those bars; each bar's volume goes to the bin of its typical price (h + l + c) / 3.
             POC = centre of the max-volume bin (ties: lowest bin). Value area: start at the POC
             bin, add the adjacent bin on the side with more volume (tie: upper side; an
             exhausted side is skipped) until the included volume >= 70% of the total;
             VAH / VAL = outer edges of the value area. Levels: POC, VAH, VAL.
  L6 HTF     L1 on the next timeframe up (5m->30m, 15m->1h, 30m->4h, 1h->4h, 4h->1d). The HTF
             bars are the CHART bars resampled with the locked backtest's
             ``sweep_lib.resample_ohlcv`` (UTC, open-labelled, left-closed). An HTF bar counts
             only once it has closed (open + HTF length) at or before the signal bar's close;
             "j + 5" and "last 300 bars" are counted in closed HTF bars.

Side conventions (a level exactly at c): "ahead" is inclusive, "behind" is strict. So for a
long, ahead = levels >= c and behind = levels < c; for a short, ahead = levels <= c and
behind = levels > c. A level at the close has not been passed yet.

Features (s = side, a = ATR14 of the signal bar, L = leverage):
  room                 distance from c to the nearest level ahead / a, capped at 10 (10 if none)
  floor                distance from c to the nearest level behind / a, capped at 10 (10 if none;
                       cannot happen in practice: L4 always gives a level on both sides)
  room_type/floor_type family (1..6 = L1..L6) of that nearest level; ties go to the lower family
  room_kind/floor_kind finer code, see KIND
  level_before_lock    1 if the nearest level ahead is strictly closer than the first-lock price,
                       the price where net ROE = first_lock + trigger_gap = +12%:
                       lock = fill * (1 + s * (0.12 / L + round_trip)), round_trip = 0.0014.
                       The fill is not known at the signal bar: the signal bar close is used as
                       the fill (fill = c, no slippage term), funding is ignored.
  support_before_stop  1 if the nearest level behind is strictly closer than the stop
                       c - s * 2 * a (i.e. distance < 2a: the stop sits behind that level)
  breakout             1 if a level was passed in the trade direction by the signal bar's close:
                       long  close[i-1] <= X < close[i], short close[i] < X <= close[i-1] for a
                       level X of bar i (equivalently: the nearest level behind lies at or
                       beyond the previous close).
Leverage: by default ``leverage_at_close`` = research/strategy_profiles/profiles._sizer with
atr / close of the signal bar (causal). The outcome itself sizes with atr / next-bar open; pass
that as ``lev`` to features_for to use the traded leverage instead.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (os.path.join(ROOT, "research", "strategy_profiles"), os.path.join(ROOT, "research", "paper_rules"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import profiles as PR  # noqa: E402  (paper v3 sizing lookup)
import rules_bt as RB  # noqa: E402
from paperbot import sweepsig  # noqa: E402
from paperbot.ladder import roe_price  # noqa: E402

# ------------------------------------------------------------------ constants (PREREG section 2)
PIVOT_K = 5            # j-5 .. j+5
PIVOT_LOOKBACK = 300   # swing bar within the last 300 bars
PIVOT_KEEP = 10        # 10 most recent highs and 10 most recent lows
VP_BARS = 200
VP_BINS = 50
VP_SHARE = 0.70
CAP = 10.0
K_STOP = PR.K_STOP                                           # 2 ATR
ROUND_TRIP = RB.SETTINGS.round_trip_cost                     # 2 * (0.0005 + 0.0002)
LOCK_ROE = RB.LADDER.first_lock + RB.LADDER.trigger_gap      # 0.12: first lock arms here
HTF = {"5m": "30m", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d"}
FAMILIES = ("L1", "L2", "L3", "L4", "L5", "L6")
FAMILY_NAME = {1: "swing", 2: "prior_day", 3: "prior_week", 4: "round", 5: "volume_profile", 6: "htf_swing"}
KIND = {11: "swing_high", 12: "swing_low", 21: "prior_day_high", 22: "prior_day_low",
        31: "prior_week_high", 32: "prior_week_low", 40: "round", 51: "poc", 52: "vah", 53: "val",
        61: "htf_swing_high", 62: "htf_swing_low"}
REDUCTIONS = ("up_ge", "up_gt", "dn_le", "dn_lt")
DAY_NS = 86_400 * 10**9
MIN_NS = 60 * 10**9
DEFAULT_SIG_DIR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/paper_rules/signals"
DEFAULT_SWEEP = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/sweepdata"

_SW = np.lib.stride_tricks.sliding_window_view


def _lib():
    os.environ.setdefault("SWEEP_DATA", DEFAULT_SWEEP)
    return sweepsig.lib()


def ts_ns(ts) -> np.ndarray:
    """Bar open times as int64 ns UTC (accepts int64 ns or anything pandas parses)."""
    a = np.asarray(ts)
    if a.dtype.kind in "iu":
        return a.astype(np.int64)
    s = pd.to_datetime(pd.Series(ts), utc=True)
    return s.dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)


# ------------------------------------------------------------------ L1 / L6: swing points
def pivot_flags(h: np.ndarray, l: np.ndarray, k: int = PIVOT_K) -> tuple[np.ndarray, np.ndarray]:
    """is_high[j]: high[j] == max(high[j-k .. j+k]); is_low likewise with min. Needs the full window."""
    n = len(h)
    ph = np.zeros(n, bool)
    pl = np.zeros(n, bool)
    w = 2 * k + 1
    if n >= w:
        ph[k:n - k] = h[k:n - k] >= _SW(h, w).max(axis=1)
        pl[k:n - k] = l[k:n - k] <= _SW(l, w).min(axis=1)
    return ph, pl


def recent_pivots(piv_idx: np.ndarray, piv_val: np.ndarray, last: np.ndarray, k: int = PIVOT_K,
                  lookback: int = PIVOT_LOOKBACK, keep: int = PIVOT_KEEP) -> np.ndarray:
    """(m, keep) prices of the ``keep`` most recent pivots usable when bar ``last`` has closed:
    pivot j is usable iff j + k <= last, and kept iff j >= last - lookback + 1. NaN = none.
    Column keep-1 is the most recent."""
    m = len(last)
    out = np.full((m, keep), np.nan)
    if len(piv_idx) == 0 or m == 0:
        return out
    cnt = np.searchsorted(piv_idx, last - k, side="right")             # pivots with j <= last - k
    pos = cnt[:, None] - keep + np.arange(keep)[None, :]
    ok = pos >= 0
    pos = np.clip(pos, 0, len(piv_idx) - 1)
    ok &= piv_idx[pos] >= (last - lookback + 1)[:, None]
    out[ok] = piv_val[pos[ok]]
    return out


def swing_matrix(h: np.ndarray, l: np.ndarray, last: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Recent swing highs and lows as one (m, 2*keep) matrix plus the kind (1 = high, 2 = low)."""
    ph, pl = pivot_flags(h, l)
    ih, il = np.flatnonzero(ph), np.flatnonzero(pl)
    hi = recent_pivots(ih, h[ih], last)
    lo = recent_pivots(il, l[il], last)
    kinds = np.r_[np.full(PIVOT_KEEP, 1), np.full(PIVOT_KEEP, 2)]
    return np.concatenate([hi, lo], axis=1), kinds


# ------------------------------------------------------------------ L2 / L3: prior day / week
def period_key(ts: np.ndarray, unit: str) -> np.ndarray:
    day = ts // DAY_NS
    if unit == "day":
        return day
    if unit == "week":
        return (day + 3) // 7          # 1970-01-01 was a Thursday: weeks start Monday 00:00 UTC
    raise ValueError(unit)


def prior_period_hl(ts: np.ndarray, h: np.ndarray, l: np.ndarray, at: np.ndarray, unit: str) -> np.ndarray:
    """(m, 2) [high, low] of the chart bars in the period (UTC day or Monday week) before the one
    of bar ``at``; NaN when that period has no bars."""
    key = period_key(ts, unit)
    start = np.r_[0, np.flatnonzero(np.diff(key)) + 1]
    uk = key[start]
    hi = np.maximum.reduceat(h, start)
    lo = np.minimum.reduceat(l, start)
    q = key[at] - 1
    pos = np.clip(np.searchsorted(uk, q), 0, len(uk) - 1)
    found = uk[pos] == q
    out = np.full((len(at), 2), np.nan)
    out[found, 0] = hi[pos[found]]
    out[found, 1] = lo[pos[found]]
    return out


# ------------------------------------------------------------------ L4: round numbers
def _round_exp(c: np.ndarray) -> np.ndarray:
    """floor(log10(c)), checked against exact powers of ten (NaN for c <= 0 / NaN)."""
    c = np.asarray(c, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        e = np.floor(np.log10(c))
        e = np.where(10.0 ** (e + 1) <= c, e + 1, e)
        e = np.where(10.0 ** e > c, e - 1, e)
    return np.where(np.isfinite(e), e, np.nan)


def round_step(c: np.ndarray) -> np.ndarray:
    """5 * 10 ** (floor(log10(c)) - 1), with the exponent checked against exact powers of ten."""
    return 5.0 * 10.0 ** (_round_exp(c) - 1)


def _round_px(k: np.ndarray, e: np.ndarray) -> np.ndarray:
    """The k-th multiple of step = 5 * 10**(e-1) as the float nearest to the exact decimal k * step.

    Prices are decimals, so the level "0.3" must be the float 0.3 (what a close of 0.3 parses to),
    not 6 * 0.05 = 0.30000000000000004: otherwise a swing high / prior-day level at 0.3 no longer
    ties with the round number (the tie rule picks the lower family) and a previous close exactly
    on 0.3 no longer counts for ``breakout``. k * 5 and 10**|e-1| (<= 10**22) are exact floats,
    so one multiplication or one division gives the correctly rounded decimal."""
    p = e - 1
    with np.errstate(over="ignore", invalid="ignore"):
        big = (k * 5.0) * 10.0 ** np.where(p >= 0, p, 0.0)
        small = (k * 5.0) / 10.0 ** np.where(p < 0, -p, 0.0)
    return np.where(p >= 0, big, small)


def round_nearest(c: np.ndarray) -> dict:
    """Nearest round-number level >= c, > c, <= c, < c (a close on a multiple counts as on it).

    Levels are the exact decimal multiples of the step (see _round_px). A close is "on" a multiple
    when it equals that decimal's float, i.e. the close was quoted as that round number."""
    c = np.asarray(c, float)
    e = _round_exp(c)
    with np.errstate(divide="ignore", invalid="ignore"):
        kr = np.round(c / (5.0 * 10.0 ** (e - 1)))      # index of the nearest multiple
    m0 = _round_px(kr, e)                               # |c - m0| <= step / 2, so m-1 < c < m+1
    m_dn = _round_px(kr - 1.0, e)
    m_up = _round_px(kr + 1.0, e)
    return {"up_ge": np.where(m0 >= c, m0, m_up),
            "up_gt": np.where(m0 > c, m0, m_up),
            "dn_le": np.where(m0 <= c, m0, m_dn),
            "dn_lt": np.where(m0 < c, m0, m_dn)}


# ------------------------------------------------------------------ L5: volume profile
def volume_profile(h, l, c, v, at: np.ndarray, bars: int = VP_BARS, bins: int = VP_BINS,
                   share: float = VP_SHARE, chunk: int = 4096) -> np.ndarray:
    """(m, 3) [POC, VAH, VAL] of the ``bars`` bars ending at (and including) each bar in ``at``.
    NaN when fewer bars exist, the price range is zero or there is no volume. NaN volume = 0."""
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    v = np.nan_to_num(np.asarray(v, float), nan=0.0)
    out = np.full((len(at), 3), np.nan)
    if len(h) < bars:
        return out
    tp = (h + l + c) / 3.0
    TPw, Vw, Lw, Hw = _SW(tp, bars), _SW(v, bars), _SW(l, bars), _SW(h, bars)
    sel = np.flatnonzero(at >= bars - 1)
    for s0 in range(0, len(sel), chunk):
        ss = sel[s0:s0 + chunk]
        r = at[ss] - (bars - 1)
        m = len(r)
        lo, hi = Lw[r].min(axis=1), Hw[r].max(axis=1)
        width = (hi - lo) / bins
        good = np.isfinite(width) & (width > 0)
        wsafe = np.where(good, width, 1.0)
        b = np.floor((TPw[r] - lo[:, None]) / wsafe[:, None])
        b = np.clip(np.nan_to_num(b, nan=0.0), 0, bins - 1).astype(np.int64)
        hist = np.bincount((b + bins * np.arange(m)[:, None]).ravel(), weights=Vw[r].ravel(),
                           minlength=m * bins).reshape(m, bins)
        total = hist.sum(axis=1)
        good &= total > 0
        poc = hist.argmax(axis=1)
        rows = np.arange(m)
        lo_b, hi_b = poc.copy(), poc.copy()
        acc = hist[rows, poc].copy()
        target = share * total * (1.0 - 1e-12)
        for _ in range(bins - 1):
            need = acc < target
            if not need.any():
                break
            up = np.where(hi_b < bins - 1, hist[rows, np.minimum(hi_b + 1, bins - 1)], -1.0)
            dn = np.where(lo_b > 0, hist[rows, np.maximum(lo_b - 1, 0)], -1.0)
            go_up = need & (up >= dn) & (hi_b < bins - 1)
            go_dn = need & ~go_up & (lo_b > 0)
            hi_b += go_up
            lo_b -= go_dn
            acc += np.where(go_up, up, 0.0) + np.where(go_dn, dn, 0.0)
        res = np.stack([lo + (poc + 0.5) * width, lo + (hi_b + 1) * width, lo + lo_b * width], axis=1)
        res[~good] = np.nan
        out[ss] = res
    return out


# ------------------------------------------------------------------ higher timeframe bars
def htf_bars(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """The chart bars resampled to the next timeframe up with the locked backtest's resampler."""
    x = pd.DataFrame({"ts": pd.to_datetime(ts_ns(df["ts"]), utc=True)})
    for k in ("open", "high", "low", "close", "volume"):
        x[k] = np.asarray(df[k], float) if k in df else 0.0
    return _lib().resample_ohlcv(x, HTF[tf])


# ------------------------------------------------------------------ nearest levels
def nearest(vals: np.ndarray, kinds: np.ndarray, c: np.ndarray, chunk: int = 32_768) -> dict:
    """For each row, the nearest level >= c, > c, <= c and < c among the columns of ``vals``
    (NaN = no level), with the kind of that column (first column wins a tie)."""
    m = len(c)
    kinds = np.asarray(kinds)
    out = {}
    for name in REDUCTIONS:
        out[name] = np.full(m, np.nan)
        out[name + "_kind"] = np.zeros(m, np.int16)
    for s0 in range(0, m, chunk):
        sl = slice(s0, min(m, s0 + chunk))
        vv = vals[sl]
        rows = np.arange(len(vv))
        d = vv - c[sl, None]
        for name, dist in (("up_ge", np.where(d >= 0, d, np.inf)), ("up_gt", np.where(d > 0, d, np.inf)),
                           ("dn_le", np.where(d <= 0, -d, np.inf)), ("dn_lt", np.where(d < 0, -d, np.inf))):
            j = dist.argmin(axis=1)
            has = np.isfinite(dist[rows, j])
            out[name][sl] = np.where(has, vv[rows, j], np.nan)
            out[name + "_kind"][sl] = np.where(has, kinds[j], 0)
    return out


def levels_for(df: pd.DataFrame, tf: str, htf_df: pd.DataFrame | None = None, at=None,
               keep_raw: bool = False) -> dict:
    """Nearest level of each family (L1..L6) above / below the close of every bar in ``at``
    (default: all bars). Returns arrays of shape (m, 6), columns in FAMILIES order:
    up_ge, up_gt, dn_le, dn_lt (prices) and <name>_kind (KIND codes, 0 = none), plus
    at, close, prev_close. ``df`` needs ts, high, low, close, volume; ``htf_df`` defaults to
    htf_bars(df, tf)."""
    ts = ts_ns(df["ts"])
    if len(ts) > 1 and not (np.diff(ts) > 0).all():
        raise ValueError("bar times must be strictly increasing")
    h = np.asarray(df["high"], float)
    l = np.asarray(df["low"], float)
    c = np.asarray(df["close"], float)
    v = np.asarray(df["volume"], float) if "volume" in df else np.zeros(len(c))
    n = len(c)
    if tf not in HTF:
        raise ValueError(f"no higher timeframe defined for {tf}")
    at = np.arange(n) if at is None else np.asarray(at, np.int64)
    m = len(at)
    cc = c[at]
    prev = np.where(at > 0, c[np.maximum(at - 1, 0)], np.nan)

    fams = {}
    # L1
    sw, sk = swing_matrix(h, l, at)
    fams[1] = (sw, 10 + sk)
    # L2, L3
    fams[2] = (prior_period_hl(ts, h, l, at, "day"), np.array([21, 22]))
    fams[3] = (prior_period_hl(ts, h, l, at, "week"), np.array([31, 32]))
    # L5
    fams[5] = (volume_profile(h, l, c, v, at), np.array([51, 52, 53]))
    # L6
    if htf_df is None:
        htf_df = htf_bars(df, tf)
    hclose = ts_ns(htf_df["ts"]) + int(_lib().tf_minutes(HTF[tf])) * MIN_NS
    chart_close = ts[at] + int(_lib().tf_minutes(tf)) * MIN_NS
    last = np.searchsorted(hclose, chart_close, side="right") - 1   # last HTF bar closed by then
    hw, hk = swing_matrix(np.asarray(htf_df["high"], float), np.asarray(htf_df["low"], float), last)
    fams[6] = (hw, 60 + hk)

    res = {"at": at, "close": cc, "prev_close": prev, "tf": tf, "htf": HTF.get(tf)}
    for name in REDUCTIONS:
        res[name] = np.full((m, 6), np.nan)
        res[name + "_kind"] = np.zeros((m, 6), np.int16)
    for f, (vals, kinds) in fams.items():
        nr = nearest(vals, kinds, cc)
        for name in REDUCTIONS:
            res[name][:, f - 1] = nr[name]
            res[name + "_kind"][:, f - 1] = nr[name + "_kind"]
    rn = round_nearest(cc)
    for name in REDUCTIONS:
        res[name][:, 3] = rn[name]
        res[name + "_kind"][:, 3] = np.where(np.isfinite(rn[name]), 40, 0)
    if keep_raw:
        res["raw"] = {f: vals for f, (vals, _) in fams.items()}
    return res


# ------------------------------------------------------------------ leverage
_SIZER = None


def leverage_at_close(side, atr, close) -> np.ndarray:
    """Paper v3 leverage (profiles._sizer, i.e. size_position tiers) from side and atr / close of
    the signal bar. 0 where sizing fails; NaN where atr is not positive / finite."""
    global _SIZER
    if _SIZER is None:
        _SIZER = PR._sizer()
    side = np.asarray(side, int)
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.asarray(atr, float) / np.asarray(close, float)
    out = np.full(len(side), np.nan)
    ok = np.isfinite(frac) & (frac > 0)
    if ok.any():
        pairs = np.stack([side[ok].astype(float), frac[ok]], axis=1)
        uq, inv = np.unique(pairs, axis=0, return_inverse=True)
        lv = np.array([_SIZER(int(s), float(f))[0] for s, f in uq], float)
        out[ok] = lv[inv.ravel()]
    return out


def _atr(df: pd.DataFrame) -> np.ndarray:
    if "atr" in df:
        return np.asarray(df["atr"], float)
    _lib()
    import fg_indicators as fg  # vendor module of the locked backtest (ATR14, Wilder RMA)
    x = pd.DataFrame({k: np.asarray(df[k], float) for k in ("open", "high", "low", "close")})
    return fg.atr(x, 14).to_numpy(float)


# ------------------------------------------------------------------ features
def features_for(df: pd.DataFrame, tf: str, htf_df, sig_idx, side, lev=None, *, levels: dict | None = None,
                 atr=None) -> dict:
    """PREREG section 2 features for the signal bars ``sig_idx`` with sides ``side`` (+1 / -1).

    lev    leverage per signal; default leverage_at_close (atr / close of the signal bar).
    levels output of levels_for for these bars or a superset (default: computed here).
    atr    ATR14 per chart bar; default df['atr'] if present, else the backtest's fg.atr(df, 14).
    Returns a dict of arrays aligned with sig_idx (NaN where a feature is undefined)."""
    sig_idx = np.asarray(sig_idx, np.int64)
    s = np.asarray(side, int)
    if len(s) != len(sig_idx) or not np.isin(s, (-1, 1)).all():
        raise ValueError("side must be +1/-1, one per signal")
    if levels is None:
        levels = levels_for(df, tf, htf_df, at=np.unique(sig_idx))
    at = levels["at"]
    row = np.searchsorted(at, sig_idx)
    if len(sig_idx) and (row.max() >= len(at) or (at[np.minimum(row, len(at) - 1)] != sig_idx).any()):
        raise ValueError("levels do not cover every signal bar")
    a_all = _atr(df) if atr is None else np.asarray(atr, float)
    a = a_all[sig_idx]
    c = levels["close"][row]
    prev = levels["prev_close"][row]
    a_ok = np.isfinite(a) & (a > 0)
    if lev is None:
        lev = leverage_at_close(s, a, c)
    lev = np.asarray(lev, float)
    lev_ok = np.isfinite(lev) & (lev > 0)
    m = len(sig_idx)
    long = (s == 1)[:, None]

    ahead_px = np.where(long, levels["up_ge"][row], levels["dn_le"][row])
    ahead_kd = np.where(long, levels["up_ge_kind"][row], levels["dn_le_kind"][row])
    behind_px = np.where(long, levels["dn_lt"][row], levels["up_gt"][row])
    behind_kd = np.where(long, levels["dn_lt_kind"][row], levels["up_gt_kind"][row])
    sc = (s * 1.0)[:, None]
    d_ahead = sc * (ahead_px - c[:, None])            # >= 0, NaN = none of that family
    d_behind = sc * (c[:, None] - behind_px)          # > 0

    rows = np.arange(m)
    out = {"sig_idx": sig_idx, "side": s.astype(np.int8), "close": c, "atr": a, "lev": lev}
    pooled = {}
    for tag, d, px, kd in (("ahead", d_ahead, ahead_px, ahead_kd), ("behind", d_behind, behind_px, behind_kd)):
        di = np.where(np.isnan(d), np.inf, d)
        j = di.argmin(axis=1) if m else np.zeros(0, int)
        has = np.isfinite(di[rows, j]) if m else np.zeros(0, bool)
        dist = np.where(has, d[rows, j], np.nan)
        pooled[tag] = (dist, has)
        out[f"{tag}_px"] = np.where(has, px[rows, j], np.nan)
        out[f"{tag}_type"] = np.where(has, j + 1, 0).astype(np.int8)
        out[f"{tag}_kind"] = np.where(has, kd[rows, j], 0).astype(np.int16)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[f"dist_{tag}_atr"] = np.where(a_ok, dist / a, np.nan)
            for f in range(6):
                out[f"{tag}_{FAMILIES[f]}"] = np.where(a_ok, d[:, f] / a, np.nan)

    with np.errstate(divide="ignore", invalid="ignore"):
        for name, tag in (("room", "ahead"), ("floor", "behind")):
            dist, has = pooled[tag]
            val = np.where(has, np.minimum(dist / a, CAP), CAP)
            out[name] = np.where(a_ok, val, np.nan)
            out[name + "_type"] = out[f"{tag}_type"]
            out[name + "_kind"] = out[f"{tag}_kind"]

        # first lock: net ROE +12% with fill = signal close (proxy), no funding
        lock_px = np.where(lev_ok, roe_price(s, c, np.where(lev_ok, lev, 1.0), LOCK_ROE, ROUND_TRIP), np.nan)
        lock_dist = np.abs(lock_px - c)
        dist_a, has_a = pooled["ahead"]
        lbl = has_a & (dist_a < lock_dist)
        out["lock_px"] = lock_px
        out["lock_dist_atr"] = np.where(a_ok, lock_dist / a, np.nan)
        out["level_before_lock"] = np.where(lev_ok, lbl.astype(float), np.nan)

        stop_px = c - s * K_STOP * a
        dist_b, has_b = pooled["behind"]
        sbs = has_b & (dist_b < K_STOP * a)
        out["stop_px"] = np.where(a_ok, stop_px, np.nan)
        out["support_before_stop"] = np.where(a_ok, sbs.astype(float), np.nan)

    bpx = out["behind_px"]
    brk = np.where(s == 1, bpx >= prev, bpx <= prev) & np.isfinite(bpx)
    out["breakout"] = np.where(np.isfinite(prev), brk.astype(float), np.nan)
    return out


# ------------------------------------------------------------------ data helper (periods 1 and 2)
def chart_from_cache(tf: str, coin: str, sig_dir: str = DEFAULT_SIG_DIR, sweep: str = DEFAULT_SWEEP):
    """Chart bars of the paper_rules signal cache with volume joined by ts from the full CSV.
    Returns (df with ts int64 ns, open, high, low, close, volume, atr; the npz as a dict)."""
    z = np.load(os.path.join(sig_dir, f"sig_{tf}_{coin}.npz"))
    zd = {k: z[k] for k in z.files}
    csv = pd.read_csv(os.path.join(sweep, "full", f"{coin.lower()}-{tf}.csv"), usecols=["ts", "volume"])
    vts = ts_ns(csv["ts"])
    pos = np.clip(np.searchsorted(vts, zd["ts"]), 0, len(vts) - 1)
    hit = vts[pos] == zd["ts"]
    vol = np.where(hit, csv["volume"].to_numpy(float)[pos], np.nan)
    df = pd.DataFrame({"ts": zd["ts"], "open": zd["o"], "high": zd["h"], "low": zd["l"], "close": zd["c"],
                       "volume": vol, "atr": zd["atr"]})
    df.attrs["tf"] = tf
    df.attrs["volume_missing"] = int((~hit).sum())
    return df, zd


def _time(tf: str = "5m", coin: str = "BTCUSD") -> None:
    t0 = time.time()
    df, z = chart_from_cache(tf, coin)
    t1 = time.time()
    lv = levels_for(df, tf)
    t2 = time.time()
    nsig = 0
    for key in (k for k in z if k.startswith("s__")):
        sg = z[key]
        idx = np.flatnonzero(sg)
        idx = idx[idx < len(sg) - 1]
        features_for(df, tf, None, idx, sg[idx].astype(int), levels=lv)
        nsig += len(idx)
    t3 = time.time()
    print(f"{tf} {coin}: {len(df)} bars, volume missing {df.attrs['volume_missing']}; load {t1 - t0:.1f}s, "
          f"levels {t2 - t1:.1f}s, features for {nsig} signals {t3 - t2:.1f}s", flush=True)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "time":
        _time(*(sys.argv[2:4]))
    else:
        print(__doc__)
