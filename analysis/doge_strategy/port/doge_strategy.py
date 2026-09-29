"""
Faithful Python port of Astral saved strategy 5864
("DOGEUSD EMA 15M Trend & 5M KDJ Crossover", working strategy 37530 / 38275).

Single entry point:  simulate(df, params=None, side='long', costs=None, fill='on_close',
                             tsl_eval='astral', warmup_bars=660, df_1m=None) -> trades DataFrame
Helper:              summarize(trades, sizing=0.25) -> dict
                     compute_indicators(df, params) -> DataFrame of all derived series
                     load_ohlcv(path) -> DataFrame indexed by UTC timestamp

Conventions (defaults) were inferred by replicating Astral's own backtests trade-by-trade
(see NOTES.md in this directory).  The defaults reproduce Astral exactly; the alternative
conventions are kept selectable so the sensitivity can be measured.

IMPORTANT Astral behaviour reproduced here:
  * Indicators are computed ONLY from the backtest's raw_data_start (no history before it).
    So pass df sliced to start exactly at the Astral backtest start.  Signals/trades are
    allowed from bar index `warmup_bars` (Astral: 660 = 1.1 x longest lookback 600).
  * Entry/exit orders fill at the close of the signal bar (fill_price_mode on_close).
  * Trailing stop ('tsl_only', evaluation on_entry_fill) becomes active on the bar AFTER
    the entry bar.  Per bar the coarse path is open -> high -> low: the watermark is
    raised with the bar high first, the stage/distance is chosen from the watermark's
    favourable excursion vs entry, stop = watermark - distance (tighten only), and the
    stop triggers if low <= stop.  The exit then FILLS AT THE BAR CLOSE
    ("strategy_bar_close_after_target_touch"), not at the stop price.
  * No new entry on a bar on which a protective (TSL) exit happened
    (same_bar_new_exposure_policy = suppress_after_protection_exit).
"""
from __future__ import annotations

import math
from copy import deepcopy

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------------------
# Parameters
# ----------------------------------------------------------------------------------------
DEFAULT = dict(
    # lengths (5m bars)
    ema_fast=63,        # "EMA_15M_21"
    ema_slow=156,       # "EMA_15M_52"
    ema_trend=600,      # "EMA_15M_200"
    ema_short=21,       # "EMA_5M_21"
    stoch_rsi_len=70,   # RSI length inside StochRSI
    stoch_len=70,       # MIN/MAX window of the RSI
    k_smooth=4,
    d_smooth=3,
    rsi_len=26,
    chop_len=14,
    # thresholds (long side; the short side mirrors them)
    spread_min=0.15,    # EMA_SPREAD_PCT > 0.15  (short: < -0.15)
    chop_max=61.8,      # CHOP_14 < 61.8 (both sides)
    k_max=45.0,         # K < 45            (short: K > 100-45 = 55)
    rsi_min=52.0,       # RSI_26 > 52       (short: RSI_26 < 100-52 = 48)
    # trailing stop stages: (distance as fraction of ENTRY_PRICE, until favourable watermark in %)
    tsl_stages=((0.0035, 0.25), (0.0020, 0.375), (0.0020, None)),
    use_tsl=True,
    use_signal_exit=True,
    # indicator conventions (Astral-matching defaults; see NOTES.md)
    ema_seed='first',        # 'first' (y0=x0, pandas adjust=False) | 'sma' (TA-Lib) | 'adjust'
    rsi_method='wilder_sma',  # 'wilder_sma' (TA-Lib) | 'wilder_first' | 'ewm_adjust' | 'ema' | 'sma'
    atr_method='sma',         # 'sma' (Astral: simple mean of TR) | 'wilder_sma' (TA-Lib) | 'wilder_first'
    tr0='hl',                # first-bar true range: 'hl' (high-low) | 'nan'
    minmax_minp='full',      # rolling MIN/MAX min_periods: 'full' | 'one'
    cross='le',              # CROSS_ABOVE(a,b): a>b and a[-1] <= b[-1]  ('le') | strict '<' ('lt')
    stage_boundary='ge',     # stage advances when favourable% >= threshold ('ge') or > ('gt')
    minmax_include_current=True,   # MIN/MAX windows include the current bar (Astral: yes)
    suppress_after_tsl=True,       # no new entry on a bar with a protective exit (Astral: yes)
    sub1m_path='ohl_stop',         # per-1m-bar path used by tsl_eval='sub1m' ('ohl_stop'|'olh_stop'|'astral')
)

ZERO_COSTS = dict(fee_side=0.0, slip_side=0.0, funding_8h=0.0, maker_exit=False, maker_fee=0.0002, model='additive')
ASTRAL_5_2 = dict(fee_side=0.0005, slip_side=0.0002, funding_8h=0.0, model='astral')   # commission_bps=5, slippage_bps=2
BINANCE_TAKER = dict(fee_side=0.0005, slip_side=0.00015, funding_8h=0.0001, maker_exit=False, maker_fee=0.0002)


def _p(params):
    p = deepcopy(DEFAULT)
    if params:
        p.update(params)
    return p


# ----------------------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------------------
def load_ohlcv(path: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    ts = 'timestamp' if 'timestamp' in d.columns else d.columns[0]
    d[ts] = pd.to_datetime(d[ts], utc=True)
    d = d.set_index(ts).sort_index()
    d.index.name = 'ts'
    return d[['open', 'high', 'low', 'close'] + (['volume'] if 'volume' in d.columns else [])].astype(float)


# ----------------------------------------------------------------------------------------
# Indicator primitives
# ----------------------------------------------------------------------------------------
def ema(x: pd.Series, n: int, seed: str = 'first') -> pd.Series:
    if seed == 'first':
        return x.ewm(span=n, adjust=False).mean()
    if seed == 'adjust':
        return x.ewm(span=n, adjust=True).mean()
    if seed == 'sma':
        return _seeded_recursion(x, n, 2.0 / (n + 1))
    raise ValueError(seed)


def _seeded_recursion(x: pd.Series, n: int, alpha: float, first_idx: int = 0) -> pd.Series:
    """TA-Lib style: NaN until first_idx+n-1, value there = mean(x[first_idx:first_idx+n]),
    then y_t = alpha*x_t + (1-alpha)*y_{t-1}."""
    v = x.to_numpy(dtype=float).copy()
    out = np.full(len(v), np.nan)
    s = first_idx + n - 1
    if s >= len(v):
        return pd.Series(out, index=x.index)
    y = np.nanmean(v[first_idx:s + 1])
    out[s] = y
    a = alpha
    for i in range(s + 1, len(v)):
        y = a * v[i] + (1 - a) * y
        out[i] = y
    return pd.Series(out, index=x.index)


def _rma(x: pd.Series, n: int, method: str, first_idx: int) -> pd.Series:
    if method == 'wilder_sma':
        return _seeded_recursion(x, n, 1.0 / n, first_idx)
    xs = x.copy()
    xs.iloc[:first_idx] = np.nan
    if method == 'wilder_first':
        return xs.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    if method == 'ewm_adjust':
        return xs.ewm(alpha=1.0 / n, adjust=True, min_periods=n).mean()
    if method == 'ema':
        return xs.ewm(span=n, adjust=False, min_periods=n).mean()
    if method == 'sma':
        return xs.rolling(n).mean()
    raise ValueError(method)


def rsi(x: pd.Series, n: int, method: str = 'wilder_sma') -> pd.Series:
    d = x.diff()
    g = d.clip(lower=0)
    l = (-d).clip(lower=0)
    ag = _rma(g, n, method, 1)
    al = _rma(l, n, method, 1)
    r = 100 - 100 / (1 + ag / al)
    r = r.where(al != 0, 100.0)
    r = r.where(ag.notna() & al.notna())
    return r


def atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int, method: str = 'wilder_sma', tr0: str = 'hl') -> pd.Series:
    c1 = c.shift()
    tr = pd.concat([h - l, (h - c1).abs(), (l - c1).abs()], axis=1).max(axis=1)
    if tr0 == 'hl':
        tr.iloc[0] = h.iloc[0] - l.iloc[0]
        first = 1 if method == 'wilder_sma' else 0   # TA-Lib ATR skips bar 0
    else:
        tr.iloc[0] = np.nan
        first = 1
    return _rma(tr, n, method, first)


def rmax(x, n, minp, include_current=True):
    r = x.rolling(n, min_periods=(n if minp == 'full' else 1)).max()
    return r if include_current else r.shift()


def rmin(x, n, minp, include_current=True):
    r = x.rolling(n, min_periods=(n if minp == 'full' else 1)).min()
    return r if include_current else r.shift()


def cross_above(a: pd.Series, b: pd.Series, how: str = 'le') -> np.ndarray:
    a0, b0, a1, b1 = a.to_numpy(), b.to_numpy(), a.shift().to_numpy(), b.shift().to_numpy()
    with np.errstate(invalid='ignore'):
        prev = (a1 <= b1) if how == 'le' else (a1 < b1)
        return (a0 > b0) & prev


def cross_below(a: pd.Series, b: pd.Series, how: str = 'le') -> np.ndarray:
    a0, b0, a1, b1 = a.to_numpy(), b.to_numpy(), a.shift().to_numpy(), b.shift().to_numpy()
    with np.errstate(invalid='ignore'):
        prev = (a1 >= b1) if how == 'le' else (a1 > b1)
        return (a0 < b0) & prev


# ----------------------------------------------------------------------------------------
# Derived series + signals
# ----------------------------------------------------------------------------------------
def compute_indicators(df: pd.DataFrame, params=None) -> pd.DataFrame:
    p = _p(params)
    c, h, l = df['close'], df['high'], df['low']
    out = pd.DataFrame(index=df.index)
    out['ema_fast'] = ema(c, p['ema_fast'], p['ema_seed'])
    out['ema_slow'] = ema(c, p['ema_slow'], p['ema_seed'])
    out['ema_trend'] = ema(c, p['ema_trend'], p['ema_seed'])
    out['ema_short'] = ema(c, p['ema_short'], p['ema_seed'])
    out['spread_pct'] = (out['ema_fast'] - out['ema_slow']) / out['ema_slow'] * 100
    r70 = rsi(c, p['stoch_rsi_len'], p['rsi_method'])
    mn = rmin(r70, p['stoch_len'], p['minmax_minp'], p['minmax_include_current'])
    mx = rmax(r70, p['stoch_len'], p['minmax_minp'], p['minmax_include_current'])
    raw = (r70 - mn) / (mx - mn + 1e-6) * 100
    out['K'] = raw.rolling(p['k_smooth']).mean()
    out['D'] = out['K'].rolling(p['d_smooth']).mean()
    out['rsi26'] = rsi(c, p['rsi_len'], p['rsi_method'])
    a = atr(h, l, c, p['chop_len'], p['atr_method'], p['tr0'])
    rng = (rmax(h, p['chop_len'], p['minmax_minp'], p['minmax_include_current'])
           - rmin(l, p['chop_len'], p['minmax_minp'], p['minmax_include_current']))
    with np.errstate(divide='ignore', invalid='ignore'):
        out['chop'] = 100 * np.log(a * p['chop_len'] / rng) / np.log(p['chop_len'])
    # Astral derived series use fill='ffill' (only matters for NaN/inf gaps)
    out = out.replace([np.inf, -np.inf], np.nan).ffill()
    return out


def compute_signals(df: pd.DataFrame, ind: pd.DataFrame, params=None) -> pd.DataFrame:
    p = _p(params)
    c = df['close'].to_numpy()
    f, s, t, e21 = (ind[k].to_numpy() for k in ('ema_fast', 'ema_slow', 'ema_trend', 'ema_short'))
    sp, ch, K, D, r26 = (ind[k].to_numpy() for k in ('spread_pct', 'chop', 'K', 'D', 'rsi26'))
    xa = cross_above(ind['K'], ind['D'], p['cross'])
    xb = cross_below(ind['K'], ind['D'], p['cross'])
    with np.errstate(invalid='ignore'):
        long_entry = ((f > s) & (c > t) & (sp > p['spread_min']) & (ch < p['chop_max']) & xa
                      & (K < p['k_max']) & (r26 > p['rsi_min']) & (c > e21))
        long_exit = (f < s) | xb
        short_entry = ((f < s) & (c < t) & (sp < -p['spread_min']) & (ch < p['chop_max']) & xb
                       & (K > 100 - p['k_max']) & (r26 < 100 - p['rsi_min']) & (c < e21))
        short_exit = (f > s) | xa
    return pd.DataFrame(dict(long_entry=long_entry, long_exit=long_exit,
                             short_entry=short_entry, short_exit=short_exit), index=df.index)


# ----------------------------------------------------------------------------------------
# Trailing stop helpers
# ----------------------------------------------------------------------------------------
def _stage_dist(fav_pct: float, stages, boundary: str) -> tuple[float, int]:
    for k, (dist, until) in enumerate(stages):
        if until is None:
            return dist, k
        below = fav_pct < until if boundary == 'ge' else fav_pct <= until
        if below:
            return dist, k
    return stages[-1][0], len(stages) - 1


class _TSL:
    """Direction-aware trailing stop state. sgn=+1 long, -1 short."""

    def __init__(self, entry, sgn, stages, boundary):
        self.e, self.sgn, self.stages, self.b = entry, sgn, stages, boundary
        self.wm = entry
        d, self.stage = _stage_dist(0.0, stages, boundary)
        self.stop = entry - sgn * d * entry

    def update_wm(self, px):
        if self.sgn > 0:
            self.wm = max(self.wm, px)
        else:
            self.wm = min(self.wm, px)
        fav = self.sgn * (self.wm / self.e - 1) * 100
        d, self.stage = _stage_dist(fav, self.stages, self.b)
        new = self.wm - self.sgn * d * self.e
        self.stop = max(self.stop, new) if self.sgn > 0 else min(self.stop, new)   # tighten only

    def touched(self, px):
        return px <= self.stop if self.sgn > 0 else px >= self.stop


TSL_ALIASES = {'intrabar_pess': 'ohl_stop', 'intrabar_opt': 'olh_stop'}


def _tsl_bar(ts: _TSL, o, h, lo, c, mode):
    """Process one bar for an open position. Returns (hit, fill_price).
    Modes (long wording; short is mirrored):
      astral     : path O->H->L; watermark raised by the high first, trigger if low <= stop,
                   FILL AT BAR CLOSE (Astral 'strategy_bar_close_after_target_touch').
      ohl_stop   : same O->H->L trigger, fill at the stop price (or at the open if the open is
                   already through the stop).  alias 'intrabar_pess' (pessimistic TRIGGER
                   ordering: favourable extreme first tightens the stop before the adverse one).
      olh_stop   : path O->L->H->C: adverse extreme checked against the previous stop first, then
                   the high raises the stop, then the close is checked; fill at stop (or open on
                   gap).  alias 'intrabar_opt'.
      close_only : watermark from closes, trigger on close, fill at close.
    NOTE: which ordering is P&L-optimistic depends on the data; on DOGE 5m the 5m stop-fill
    variants are MORE favourable than 'astral', and all 5m variants are more favourable than a
    1-minute path walk (tsl_eval='sub1m').  See NOTES.md."""
    mode = TSL_ALIASES.get(mode, mode)
    sgn = ts.sgn
    fav_ext, adv_ext = (h, lo) if sgn > 0 else (lo, h)
    if mode == 'astral':
        ts.update_wm(fav_ext)
        if ts.touched(adv_ext):
            return True, c
        return False, None
    if mode == 'ohl_stop':
        if ts.touched(o):
            return True, o
        ts.update_wm(fav_ext)
        if ts.touched(adv_ext):
            return True, ts.stop
        return False, None
    if mode == 'olh_stop':
        if ts.touched(o):
            return True, o
        if ts.touched(adv_ext):
            return True, ts.stop
        ts.update_wm(fav_ext)
        if ts.touched(c):
            return True, ts.stop
        return False, None
    if mode == 'close_only':
        ts.update_wm(c)
        if ts.touched(c):
            return True, c
        return False, None
    raise ValueError(mode)


# ----------------------------------------------------------------------------------------
# Simulator
# ----------------------------------------------------------------------------------------
def simulate(df: pd.DataFrame, params=None, side: str = 'long', costs: dict | None = None,
             fill: str = 'on_close', tsl_eval: str = 'astral', warmup_bars: int = 660,
             df_1m: pd.DataFrame | None = None, ind: pd.DataFrame | None = None,
             sig: pd.DataFrame | None = None, close_open_at_end: bool = True) -> pd.DataFrame:
    """Run the strategy on 5m OHLC `df` (indicators are computed from df's first row).

    side      : 'long' | 'short' | 'both' (one position at a time; first signal wins)
    costs     : dict(fee_side, slip_side, funding_8h, maker_exit, maker_fee) as fractions
                (0.0005 = 0.05%).  Applied additively to per-trade returns:
                net = gross - fee_in - fee_out - slip_in - slip_out - funding_8h*hours/8.
                maker_exit=True -> signal exits pay maker_fee and no slippage (TSL exits stay taker).
                model='astral' reproduces Astral's commission/slippage arithmetic exactly
                (fill = close*(1 +/- slip), commission = fee * filled notional, return on entry notional).
    fill      : 'on_close' (Astral) | 'next_open' (signal at close t -> fill at open t+1)
    tsl_eval  : 'astral' | 'ohl_stop' (='intrabar_pess') | 'olh_stop' (='intrabar_opt') | 'close_only' | 'sub1m'
                'sub1m' walks the 1m bars (df_1m) inside each 5m bar (5m bars are labelled by
                their OPEN time; verified against 1m aggregation) with params['sub1m_path']
                (default 'ohl_stop': O->H->L per minute, fill at stop or at the 1m open on
                gaps).  Signals are still evaluated on 5m closes only.  Minutes missing from the
                1m feed are skipped; a 5m bar with no 1m data falls back to 'ohl_stop' on 5m.
    warmup_bars : first bar index on which a signal may be acted on (Astral: 660).
    Returns one row per trade.
    """
    p = _p(params)
    cst = dict(ZERO_COSTS)
    if costs:
        cst.update(costs)
    if ind is None:
        ind = compute_indicators(df, p)
    if sig is None:
        sig = compute_signals(df, ind, p)
    idx = df.index
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ('open', 'high', 'low', 'close'))
    n = len(df)
    le, lx = sig['long_entry'].to_numpy(), sig['long_exit'].to_numpy()
    se, sx = sig['short_entry'].to_numpy(), sig['short_exit'].to_numpy()
    if side == 'long':
        se = np.zeros(n, bool)
    elif side == 'short':
        le = np.zeros(n, bool)
    elif side != 'both':
        raise ValueError(side)
    stages = p['tsl_stages']
    bar_sec = (idx[1] - idx[0]).total_seconds() if n > 1 else 300.0

    m1 = None
    if tsl_eval == 'sub1m':
        if df_1m is None:
            raise ValueError('sub1m needs df_1m')
        m1 = df_1m
        m1_bucket = m1.index.floor(pd.Timedelta(seconds=bar_sec))
        m1_pos = pd.Series(np.arange(len(m1)), index=m1.index).groupby(m1_bucket).agg(['first', 'last'])
        m1o, m1h, m1l, m1c = (m1[k].to_numpy(dtype=float) for k in ('open', 'high', 'low', 'close'))

    trades = []
    pos = 0            # +1 long, -1 short
    ts = None
    ent_i = ent_px = ent_sig_i = None
    mfe = mae = 0.0
    pend_exit = False  # next_open: exit at next bar open
    pend_entry = None  # next_open: (sgn, signal bar index)

    def close_trade(exit_i, exit_px, reason, stage):
        nonlocal pos, ts
        sgn = pos
        stop_px = ts.stop if ts is not None else np.nan
        wm = ts.wm if ts is not None else np.nan
        gross = sgn * (exit_px / ent_px - 1)
        hours = (idx[exit_i] - idx[ent_i]).total_seconds() / 3600.0
        fee_in, slip_in = cst['fee_side'], cst['slip_side']
        if reason == 'signal' and cst.get('maker_exit'):
            fee_out, slip_out = cst['maker_fee'], 0.0
        else:
            fee_out, slip_out = cst['fee_side'], cst['slip_side']
        fund = cst['funding_8h'] * hours / 8.0
        if cst.get('model', 'additive') == 'astral':
            # Astral: fills slipped in price, commission on filled notional, return on entry notional
            e_ = ent_px * (1 + sgn * slip_in)
            x_ = exit_px * (1 - sgn * slip_out)
            net = sgn * (x_ - e_) / e_ - fee_in - fee_out * x_ / e_ - fund
        else:
            net = gross - fee_in - fee_out - slip_in - slip_out - fund
        trades.append(dict(signal_ts=idx[ent_sig_i], entry_ts=idx[ent_i], exit_ts=idx[exit_i],
                           side='long' if sgn > 0 else 'short', entry_px=ent_px, exit_px=exit_px,
                           gross=gross, net=net, reason=reason, tsl_stage=stage,
                           hold_bars=exit_i - ent_i, mfe=mfe, mae=mae, stop_px=stop_px, watermark=wm))
        pos, ts = 0, None

    def open_trade(i_fill, px, sgn, sig_i):
        nonlocal pos, ts, ent_i, ent_px, ent_sig_i, mfe, mae
        pos, ent_i, ent_px, ent_sig_i = sgn, i_fill, px, sig_i
        ts = _TSL(px, sgn, stages, p['stage_boundary'])
        mfe = mae = 0.0

    for i in range(warmup_bars, n):
        tsl_exit_this_bar = False
        # A) next_open: orders decided at bar i-1 close execute at bar i open
        if pend_exit and pos != 0:
            close_trade(i, o[i], 'signal', ts.stage)
        pend_exit = False
        if pend_entry is not None:
            if pos == 0:
                open_trade(i, o[i], pend_entry[0], pend_entry[1])
            pend_entry = None
        # B) protective trailing stop inside bar i.  Active from the bar AFTER an on_close fill
        #    (Astral active_from = entry bar + 1) and from the fill bar itself for next_open.
        if pos != 0 and (i > ent_i or fill == 'next_open'):
            if p['use_tsl']:
                if tsl_eval == 'sub1m':
                    hit, fpx = False, None
                    key = idx[i]
                    if key in m1_pos.index:
                        a0, a1 = m1_pos.loc[key, 'first'], m1_pos.loc[key, 'last']
                        for j in range(a0, a1 + 1):
                            hit, fpx = _tsl_bar(ts, m1o[j], m1h[j], m1l[j], m1c[j], p['sub1m_path'])
                            if hit:
                                break
                    else:   # no 1m data for this bar: fall back to the 5m O->H->L stop-fill path
                        hit, fpx = _tsl_bar(ts, o[i], h[i], l[i], c[i], 'ohl_stop')
                else:
                    hit, fpx = _tsl_bar(ts, o[i], h[i], l[i], c[i], tsl_eval)
            else:
                hit = False
            # excursions from bar extremes (entry bar excluded for on_close fills)
            if pos > 0:
                mfe = max(mfe, h[i] / ent_px - 1); mae = min(mae, l[i] / ent_px - 1)
            else:
                mfe = max(mfe, 1 - l[i] / ent_px); mae = min(mae, 1 - h[i] / ent_px)
            if hit:
                close_trade(i, fpx, 'tsl', ts.stage)
                tsl_exit_this_bar = True
        # C) rules evaluated on bar i close
        if pos != 0 and p['use_signal_exit'] and (lx[i] if pos > 0 else sx[i]):
            if fill == 'on_close':
                close_trade(i, c[i], 'signal', ts.stage)
            else:
                pend_exit = True
        if not (tsl_exit_this_bar and p['suppress_after_tsl']):   # Astral: suppress_after_protection_exit
            want = 1 if le[i] else (-1 if se[i] else 0)
            if want != 0:
                if fill == 'on_close':
                    if pos == 0:
                        open_trade(i, c[i], want, i)
                elif pos == 0 or (pend_exit and want == -pos):
                    if i + 1 < n:
                        pend_entry = (want, i)
    if pos != 0 and close_open_at_end:
        close_trade(n - 1, c[n - 1], 'eod', ts.stage if ts else -1)
    cols = ['signal_ts', 'entry_ts', 'exit_ts', 'side', 'entry_px', 'exit_px', 'gross', 'net',
            'reason', 'tsl_stage', 'hold_bars', 'mfe', 'mae', 'stop_px', 'watermark']
    return pd.DataFrame(trades, columns=cols)


# ----------------------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------------------
def summarize(tr: pd.DataFrame, sizing: float = 0.25, col: str = 'net') -> dict:
    """Per-trade and equity statistics.  Equity compounds `sizing` x trade return
    (Astral: 25% of equity per trade, no leverage)."""
    if len(tr) == 0:
        return dict(n=0)
    r = tr[col].to_numpy()
    wins, losses = r[r > 0], r[r < 0]
    eq = np.cumprod(1 + sizing * r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    dd = (eq / peak - 1).min()
    sd = r.std(ddof=1) if len(r) > 1 else float('nan')
    return dict(
        n=len(r),
        win_rate=float((r > 0).mean()),
        mean_pct=float(r.mean() * 100),
        median_pct=float(np.median(r) * 100),
        sd_pct=float(sd * 100),
        t_stat=float(r.mean() / (sd / math.sqrt(len(r)))) if len(r) > 1 and sd > 0 else float('nan'),
        pf=float(wins.sum() / -losses.sum()) if len(losses) else float('inf'),
        total_ret_pct=float((eq[-1] - 1) * 100),
        max_dd_pct=float(dd * 100),
        avg_hold_bars=float(tr['hold_bars'].mean()),
        reasons=tr['reason'].value_counts().to_dict(),
        sizing=sizing, col=col,
    )


if __name__ == '__main__':
    import os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    df = load_ohlcv(os.path.join(here, 'dogeusd-5m-last40k.csv'))
    w = df.loc['2026-09-11':'2026-09-28 23:55']
    tr = simulate(w)
    print(summarize(tr, col='gross'))


# ----------------------------------------------------------------------------------------
# Astral-style account metrics (25% of equity per trade, $ PnL, mark-to-market drawdown)
# ----------------------------------------------------------------------------------------
def astral_metrics(tr: pd.DataFrame, df: pd.DataFrame | None = None, sizing: float = 0.25,
                   capital: float = 100000.0, col: str = 'net', start_ts=None, slip: float = 0.0) -> dict:
    """Replicates Astral's reported metrics: total_trades, win_rate (trade return > 0),
    profit_factor ($ gross wins / $ gross losses), average_trade_return (mean trade return),
    total_return (compounded, `sizing` of equity per trade), max_drawdown (mark-to-market
    at 5m closes if df given, else on closed-trade equity)."""
    if len(tr) == 0:
        return dict(total_trades=0)
    eq = capital
    pnl = []
    sizing = sizing * (1 + slip)   # Astral buys 25%-of-equity worth of shares at the unslipped close
    for r in tr[col].to_numpy():
        p = eq * sizing * r
        pnl.append(p)
        eq += p
    pnl = np.array(pnl)
    out = dict(total_trades=len(tr), win_rate=float((tr[col] > 0).mean()),
               profit_factor=float(pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else float('inf'),
               average_trade_return=float(tr[col].mean()), total_return=float(eq / capital - 1))
    if df is not None:
        # mark-to-market equity on bar closes
        c = df['close']
        if start_ts is not None:
            c = c.loc[start_ts:]
        eqs = pd.Series(np.nan, index=c.index)
        e = capital
        cur = 0
        k = 0
        rows = tr.reset_index(drop=True)
        ent = rows['entry_ts'].to_numpy(); ext = rows['exit_ts'].to_numpy()
        sgn = np.where(rows['side'] == 'long', 1.0, -1.0)
        cv = c.to_numpy(); ix = c.index.to_numpy()
        vals = np.empty(len(cv))
        for i in range(len(cv)):
            t = ix[i]
            while k < len(rows) and ext[k] < t:
                k += 1
            if k < len(rows) and ent[k] <= t < ext[k]:
                # open position: equity = pre-trade equity + unrealised on sizing fraction
                pre = capital * np.prod(1 + sizing * rows[col].to_numpy()[:k])
                vals[i] = pre * (1 + sizing * sgn[k] * (cv[i] / rows['entry_px'].iat[k] - 1))
            else:
                done = int(np.searchsorted(ext, t, side='right'))
                vals[i] = capital * np.prod(1 + sizing * rows[col].to_numpy()[:done])
        eqs[:] = vals
        out['max_drawdown'] = float((eqs / eqs.cummax() - 1).min())
    else:
        e = capital * np.cumprod(1 + sizing * tr[col].to_numpy())
        pk = np.maximum.accumulate(np.concatenate([[capital], e]))[1:]
        out['max_drawdown'] = float((e / pk - 1).min())
    return out
