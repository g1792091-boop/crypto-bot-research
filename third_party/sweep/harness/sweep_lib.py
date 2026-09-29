"""sweep_lib.py -- harness for the pre-registered strategy x timeframe sweep.

The decision rules live in ../PREREG.md (sha256 in ../PREREG.sha256).  This module implements
exactly those definitions; the functions below are what the Discover / Combine / Holdout agents
call.  All numbers are FRACTIONS (0.0014 = 0.14 %) unless a column name ends in _pct.

Main entry points
-----------------
load(tf, sym, split)                    -> bars DataFrame (ts UTC open time, open/high/low/close/volume)
load_panel(tf, split)                   -> {sym: bars}
REGISTRY[name](df_chart, frames_by_tf)  -> (long_bool, short_bool)  signal known at bar t close,
                                           entry at bar t+1 open
compute_signals(panel, tf)              -> {name: {sym: int8 array (+1 long, -1 short, 0)}}
gate(tf, split='is')                    -> DataFrame, one row per (strategy, H)  (raw p; no Holm)
apply_gate(cells_all_tfs)               -> adds family / Holm / survive columns (PREREG gate rule)
exits(tf, strategy, H, panel, sigs)     -> per-exit pooled stats + common-shift null (B=300) and
                                           max-statistic p over the 5 exits
select_exits(exit_rows)                 -> per surviving (strategy, tf) the carried exit
holdout_confirm(...)                    -> PREREG holdout rule
controls(tf, panel)                     -> planted-drift power / zero-edge false-pass on a panel
truncation_test(df, tf, names)          -> look-ahead test rows
synth_ohlcv / synth_panel               -> synthetic data for tests
"""
from __future__ import annotations

import math
import os
import re
import sys
import time
import warnings
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "vendor")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

import fg_indicators as fg  # noqa: E402
import pine_indicators as pi  # noqa: E402
import strategies as S  # noqa: E402
import ports12  # noqa: E402
import doge_strategy as ds  # noqa: E402
from engine import CostCfg, ExitCfg, run_backtest  # noqa: E402

SWEEP = os.path.dirname(HERE)
DATA_ROOT = os.environ.get("SWEEP_DATA", os.path.join(SWEEP, "data"))

# ---------------------------------------------------------------------------------------------
# protocol constants (PREREG.md sections 1-3)
# ---------------------------------------------------------------------------------------------
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TFS = ("5m", "15m", "30m", "1h", "4h", "1d")
HS = (4, 16, 64)
HTF_OF = {"5m": "15m", "15m": "1h", "30m": "2h", "1h": "4h", "4h": "1d", "1d": "1w"}
RESAMPLE_RULE = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h",
                 "1d": "1D", "1w": "W-MON"}
WINDOWS = {
    "is": dict(start="2021-08-01", end="2024-07-01"),      # signals with bar time in [start, end)
    "oos": dict(start="2024-07-01", end="2025-08-07"),
    "final": dict(start="2025-08-07", end="2026-09-30"),   # through 2026-09-29 inclusive
}
FEE_SIDE = 0.0005
SLIP_SIDE = 0.0002
FUNDING_8H = 0.0001
RT_COST = 2.0 * (FEE_SIDE + SLIP_SIDE)   # 0.0014
HURDLE_K = 0.091
B_GATE = 600
B_EXIT = 300
ALPHA = 0.05
MIN_N = 100
MIN_SIG_COIN = 10
SEED = 20260929
PF_EXIT = 1.2
PF_HOLDOUT = 1.1
MIN_TRADES = 100
MIN_COINS_POS = 4
EXIT_CAP_MULT = 4   # max_hold of the non-time exits = 4*H bars

_TF_RE = re.compile(r"^(\d+)(m|min|h|d|w)$")


def tf_minutes(tf: str) -> int:
    """'5m'->5, '15m'->15, '1h'->60, '2h'->120, '4h'->240, '1d'->1440, '1w'->10080.
    (run.py's int(tf.rstrip('m')) breaks for 1h/4h/1d; this replaces it.)"""
    m = _TF_RE.match(str(tf).strip().lower())
    if not m:
        raise ValueError(f"unparseable timeframe {tf!r}")
    k, u = int(m.group(1)), m.group(2)
    return k * {"m": 1, "min": 1, "h": 60, "d": 1440, "w": 10080}[u]


def infer_tf(df: pd.DataFrame) -> str:
    if "tf" in df.attrs and df.attrs["tf"]:
        return df.attrs["tf"]
    d = pd.to_datetime(df["ts"], utc=True).diff().dt.total_seconds().div(60).dropna()
    med = float(d.median())
    for tf in ("5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"):
        if abs(med - tf_minutes(tf)) < 0.5:
            return tf
    raise ValueError(f"cannot infer timeframe (median spacing {med} min)")


def warmup_bars(tf: str) -> int:
    """PREREG: drop the first max(300 bars, 30 days) of each coin's loaded series; 1d: 200 bars."""
    if tf == "1d":
        return 200
    return int(max(300, math.ceil(30 * 1440 / tf_minutes(tf))))


def cost_h(H: int, tf: str) -> float:
    """round-trip taker cost + pro-rata funding for an H-bar hold."""
    return RT_COST + FUNDING_8H * (H * tf_minutes(tf) / 480.0)


# ---------------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------------
def read_ohlcv(path: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    cols = {c.lower(): c for c in d.columns}
    ts_col = cols.get("timestamp", cols.get("ts", cols.get("t", cols.get("time", d.columns[0]))))
    out = pd.DataFrame({"ts": pd.to_datetime(d[ts_col], utc=True)})
    for k in ("open", "high", "low", "close", "volume"):
        src = cols.get(k)
        if src is None:
            if k == "volume":
                out[k] = 0.0
                continue
            raise ValueError(f"{path}: missing column {k}")
        out[k] = d[src].astype(float).to_numpy()
    out = out.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
    return out


def _resolve_path(tf: str, sym: str, split: str, root: Optional[str] = None) -> str:
    d = os.path.join(root or DATA_ROOT, split)
    s = sym.replace("/", "")
    base = s[:-3] if s.upper().endswith("USD") else s
    cands = []
    for name in (s, s.lower(), s.upper(), base.lower(), base.upper()):
        cands += [f"{name}-{tf}.csv", f"{name}-{tf}-ohlcv.csv", f"{name}_{tf}.csv"]
    for c in cands:
        p = os.path.join(d, c)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"no file for {sym} {tf} in {d} (tried {cands[:3]}...)")


def _utc_ns(s) -> np.ndarray:
    s = pd.to_datetime(pd.Series(s), utc=True)
    return s.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[ns]")


def load(tf: str, sym: str, split: str, root: Optional[str] = None, path: Optional[str] = None) -> pd.DataFrame:
    """Bars of one coin/timeframe/split.  Bars at or after the split's window END are dropped at
    load time (holdout discipline: an 'is' load never returns a bar >= 2024-07-01)."""
    p = path or _resolve_path(tf, sym, split, root)
    df = read_ohlcv(p)
    end = pd.Timestamp(WINDOWS[split]["end"], tz="UTC")
    keep = df["ts"] < end
    n_drop = int((~keep).sum())
    if n_drop:
        warnings.warn(f"{p}: dropped {n_drop} bars at/after {end} (split {split})")
        df = df.loc[keep].reset_index(drop=True)
    m = tf_minutes(tf)
    dmin = df["ts"].diff().dt.total_seconds().div(60)
    df.attrs.update(tf=tf, sym=sym.upper(), split=split, path=p, dropped_after_end=n_drop,
                    gaps=int((dmin.dropna() != m).sum()),
                    misaligned=int(((df["ts"].astype("int64") // 60_000_000_000) % m != 0).sum()) if m <= 1440 else 0)
    return df


def load_panel(tf: str, split: str, coins: Sequence[str] = COINS, root: Optional[str] = None) -> Dict[str, pd.DataFrame]:
    out = {}
    for c in coins:
        try:
            out[c] = load(tf, c, split, root)
        except FileNotFoundError as e:
            warnings.warn(str(e))
    return out


def resample_ohlcv(df: pd.DataFrame, tf_out: str) -> pd.DataFrame:
    """Standard OHLCV aggregation, UTC, open-labelled, left-closed bins; empty bins dropped;
    partial bins kept.  1w bins are Monday 00:00 UTC based (Binance weekly)."""
    rule = RESAMPLE_RULE[tf_out]
    x = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["ts"], utc=True)))[["open", "high", "low", "close", "volume"]]
    agg = x.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    agg = agg.dropna(subset=["close"])
    agg.index.name = "ts"
    out = agg.reset_index()
    out.attrs["tf"] = tf_out
    return out


def htf_close_ns(ts_open, htf: str) -> np.ndarray:
    return _utc_ns(ts_open) + np.timedelta64(tf_minutes(htf), "m")


def signal_window(df: pd.DataFrame, tf: str, split: str, H: int = 0) -> Tuple[int, int]:
    """Admissible signal-bar positions [lo, hi):
       bar time >= window start, index >= warmup_bars(tf), and bar t+1+H exists inside the
       window (df is already truncated at the window end by load())."""
    ts = _utc_ns(df["ts"])
    start = np.datetime64(pd.Timestamp(WINDOWS[split]["start"]).tz_localize(None), "ns")
    end = np.datetime64(pd.Timestamp(WINDOWS[split]["end"]).tz_localize(None), "ns")
    n_in = int(np.searchsorted(ts, end, side="left"))      # bars with ts < end
    i0 = int(np.searchsorted(ts, start, side="left"))
    lo = max(i0, warmup_bars(tf))
    hi = n_in - 1 - int(H)
    return lo, max(lo, hi)


# ---------------------------------------------------------------------------------------------
# strategy registry
# ---------------------------------------------------------------------------------------------
def _as_bool(x, n: int) -> np.ndarray:
    if isinstance(x, pd.Series):
        x = x.astype("boolean").fillna(False).to_numpy(dtype=bool) if x.dtype != bool else x.to_numpy()
    a = np.asarray(x)
    if a.dtype != bool:
        a = np.nan_to_num(a.astype(float), nan=0.0) != 0.0
    if a.shape != (n,):
        raise ValueError(f"signal shape {a.shape} != ({n},)")
    return a


def _clean(L, Sh, n: int) -> Tuple[np.ndarray, np.ndarray]:
    L = _as_bool(L, n)
    Sh = _as_bool(Sh, n) & ~L
    return L, Sh


EXACT19 = ["S2_ST_ROC", "S5_DONCHIAN_MFI", "S6_EMA_DMI_ADX", "N01_ST_EMA", "N02_ST_KST", "N03_ADX_GC",
           "N07_ICHI_CMO", "N08_ICHI_WR", "N09_ALLIG_AROON", "N10_HA_PSAR", "N12_ICHI_AO", "N14_ICHI_RSI",
           "N17_KC_RSI", "N18_VWMA_MACD", "N21_ST_RSI_ADX", "N22_VORTEX_PSAR", "N23_HA_ST", "N24_DMI",
           "N25_DST_CCI"]
APPROX12 = list(ports12.PORTS12.keys())


def _wrap_exact(fn):
    def f(df, frames=None):
        return fn(df)
    f.__name__ = fn.__name__
    return f


def _wrap_port(fn):
    def f(df, frames=None):
        p = fn(df)
        return p["L"], p["S"]
    f.__name__ = fn.__name__
    return f


# ---- V4.5 exact AM+B with generalised confirmed-HTF mapping ---------------------------------
def v45_htf_components(dfc: pd.DataFrame, dfh: pd.DataFrame, htf: str, mapping: str = "closed"):
    """HTF ST(14,6) direction and STC(12,26,50) mapped onto chart bars.
    mapping='closed' (the protocol): the HTF value used on a chart bar is that of the last HTF bar
    whose CLOSE time (bin open + HTF length) <= the chart bar's OPEN time.
    mapping='current' is a deliberately look-ahead canary (uses the HTF bar containing the chart
    bar, with that HTF bar's final values) and must FAIL the truncation test."""
    f_ = S._f
    h15, l15, c15 = f_(dfh["high"]), f_(dfh["low"]), f_(dfh["close"])
    n = len(dfc)
    if len(c15) == 0:
        return np.zeros(n), np.full(n, np.nan)
    _l15, d15 = pi.exchange_supertrend(h15, l15, c15, 14, 6.0)
    stc15 = pi.stc(c15, 12, 26, 50, 0.5)
    ts5_open = _utc_ns(dfc["ts"])
    if mapping == "closed":
        key = htf_close_ns(dfh["ts"], htf)
    elif mapping == "current":
        key = _utc_ns(dfh["ts"])
    else:
        raise ValueError(mapping)
    idx = np.searchsorted(key, ts5_open, side="right") - 1
    valid = idx >= 0
    idx_c = np.clip(idx, 0, len(c15) - 1)
    d15m = np.where(valid, d15[idx_c], 0)
    stc15m = np.where(valid, stc15[idx_c], np.nan)
    return d15m, stc15m


def v45_signals_gen(dfc: pd.DataFrame, dfh: pd.DataFrame, htf: str, mapping: str = "closed") -> dict:
    """strategies.v45_signals with the 15-minute constant generalised to any HTF (see
    v45_htf_components for the causal mapping)."""
    f_ = S._f
    h5, l5, c5 = f_(dfc["high"]), f_(dfc["low"]), f_(dfc["close"])
    _lm, dm = pi.exchange_supertrend(h5, l5, c5, 14, 6.0)
    _ls, dsx = pi.exchange_supertrend(h5, l5, c5, 14, 3.0)
    d15m, stc15m = v45_htf_components(dfc, dfh, htf, mapping)
    st_main_bull, st_main_bear = dm == 1, dm == -1
    st_str_bull, st_str_bear = dsx == 1, dsx == -1
    opposite = (st_main_bull & st_str_bear) | (st_main_bear & st_str_bull)
    same = (st_main_bull & st_str_bull) | (st_main_bear & st_str_bear)
    f15_bull, f15_bear = d15m == 1, d15m == -1
    _ml, _ms, hist = pi.pine_macd(c5, 12, 26, 9)
    hp = pi.shift1(hist)
    with np.errstate(invalid="ignore"):
        weak_neg = (hist < 0.0) & (hist > hp)
        weak_pos = (hist > 0.0) & (hist < hp)
    ao, ac = pi.ao_ac(h5, l5, 5, 34, 5)
    aop, acp = pi.shift1(ao), pi.shift1(ac)
    with np.errstate(invalid="ignore"):
        ao_below, ao_above, ac_below, ac_above = ao < 0, ao > 0, ac < 0, ac > 0
        ao_up, ao_down, ac_up, ac_down = ao > aop, ao < aop, ac > acp, ac < acp
    chop = pi.chop_angle(h5, l5, c5, 34, 30, 25.0)
    with np.errstate(invalid="ignore"):
        chop_bull, chop_bear = chop >= 0.71, chop <= -0.71
    stc5 = pi.stc(c5, 12, 26, 50, 0.5)
    with np.errstate(invalid="ignore"):
        ready = np.isfinite(stc5) & np.isfinite(stc15m)
        stc_long_ok = ready & ~(stc5 >= 75.0) & ~(stc15m >= 75.0)
        stc_short_ok = ready & ~(stc5 <= 25.0) & ~(stc15m <= 25.0)
    raw = pi.pine_stoch(c5, h5, l5, 14)
    k33 = pi.pine_sma(raw, 3); d33 = pi.pine_sma(k33, 3)
    k43 = pi.pine_sma(raw, 4); d43 = pi.pine_sma(k43, 3)
    kr, dr = pi.stoch_rsi_kd(c5, 14, 14, 5, 3)
    with np.errstate(invalid="ignore"):
        g = [pi.crossover(k, d) & ((k <= 50) | (d <= 50)) for k, d in ((k33, d33), (k43, d43), (kr, dr))]
        dd = [pi.crossunder(k, d) & ((k >= 50) | (d >= 50)) for k, d in ((k33, d33), (k43, d43), (kr, dr))]
    any_long_now = np.logical_or.reduce(g) & weak_neg
    any_short_now = np.logical_or.reduce(dd) & weak_pos
    f15_long = f15_bull & stc_long_ok
    f15_short = f15_bear & stc_short_ok
    opp_long, opp_short = f15_long & opposite, f15_short & opposite
    same_long, same_short = f15_long & same, f15_short & same
    return {
        "AMIX_L": opp_long & any_long_now, "AMIX_S": opp_short & any_short_now,
        "ASAME_L": same_long & ac_below & any_long_now, "ASAME_S": same_short & ac_above & any_short_now,
        "B_L": opp_long & chop_bear & any_long_now, "B_S": opp_short & chop_bull & any_short_now,
        "C_L": opp_long & chop_bear & ac_below & ac_up & ao_below & ao_down,
        "C_S": opp_short & chop_bull & ac_above & ac_down & ao_above & ao_up,
    }


def v45_amb(df, frames=None, mapping: str = "closed"):
    """V4.5 exact AM+B on the chart TF with the confirmed next-TF frame (HTF_OF).  The HTF frame is
    taken from frames[htf] when supplied, otherwise resampled from the chart bars (identical
    OHLC when both derive from the same 5m bars)."""
    tf = infer_tf(df)
    htf = HTF_OF[tf]
    dfh = frames.get(htf) if frames else None
    if dfh is None:
        dfh = resample_ohlcv(df, htf)
    s = v45_signals_gen(df, dfh, htf, mapping=mapping)
    long = s["B_L"] & ~s["C_L"]
    short = s["B_S"] & ~s["C_S"]
    return long, short & ~long


# ---- DOGE strategy (friend's Astral #5864), lengths scaled by TF ratio ----------------------
DOGE_LEN_KEYS = ["ema_fast", "ema_slow", "ema_trend", "ema_short", "stoch_rsi_len", "stoch_len", "k_smooth",
                 "d_smooth", "rsi_len", "chop_len"]


def doge_params(tf: str) -> dict:
    """Same rule as doge/t_robust/run_tf.py scaled_params: length / ratio, round half up, min 2."""
    ratio = tf_minutes(tf) / 5.0
    p = {}
    for k in DOGE_LEN_KEYS:
        p[k] = max(2, int(math.floor(ds.DEFAULT[k] / ratio + 0.5))) if ratio > 1 else ds.DEFAULT[k]
    return p


def doge_entries(df: pd.DataFrame, tf: Optional[str] = None) -> Tuple[np.ndarray, np.ndarray]:
    tf = tf or infer_tf(df)
    p = doge_params(tf)
    d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["ts"], utc=True)))[["open", "high", "low", "close", "volume"]]
    ind = ds.compute_indicators(d, p)
    sig = ds.compute_signals(d, ind, p)
    return np.asarray(sig["long_entry"].to_numpy(), bool), np.asarray(sig["short_entry"].to_numpy(), bool)


def doge_long(df, frames=None):
    L, _s = doge_entries(df)
    return L, np.zeros(len(df), bool)


def doge_short(df, frames=None):
    _l, Sh = doge_entries(df)
    return np.zeros(len(df), bool), Sh


REGISTRY: Dict[str, callable] = {}
META: Dict[str, dict] = {}
for _k in EXACT19:
    REGISTRY[_k] = _wrap_exact(S.CANDIDATES_15M[_k])
    META[_k] = dict(group="fingrad_exact", approx=False, prev_examined=False, note="")
for _k in APPROX12:
    REGISTRY[_k] = _wrap_port(ports12.PORTS12[_k])
    META[_k] = dict(group="fingrad_approx", approx=True, prev_examined=False,
                    note="spec-based approximate port (ports12.py, variant 0); not checkable against source")
REGISTRY["V39_ALL"] = _wrap_exact(S.v39_all)
META["V39_ALL"] = dict(group="pine", approx=False, prev_examined=False, note="V3.9 single-TF chart logic as ported")
REGISTRY["OBV_S"] = _wrap_exact(S.obv_s)
META["OBV_S"] = dict(group="pine", approx=False, prev_examined=False, note="")
REGISTRY["OBV_B"] = _wrap_exact(S.obv_b)
META["OBV_B"] = dict(group="pine", approx=False, prev_examined=False, note="")
REGISTRY["V45_AMB"] = v45_amb
META["V45_AMB"] = dict(group="v45", approx=False, prev_examined=True,
                       note="previously examined: V4.5 exact AM+B on BTC/ETH/SOL 5m from 2025-03")
REGISTRY["DOGE_L"] = doge_long
META["DOGE_L"] = dict(group="doge", approx=False, prev_examined=True,
                      note="previously examined: DOGE strategy on all DOGE history and 7 coins from 2025-03; "
                           "entries only (friend's TSL/signal exits not used)")
REGISTRY["DOGE_S"] = doge_short
META["DOGE_S"] = dict(group="doge", approx=False, prev_examined=True,
                      note="previously examined (mirrored short of the DOGE strategy)")
NAMES = list(REGISTRY.keys())


def canary_lookahead(df, frames=None):
    """Deliberate look-ahead (uses close[t+1]); must FAIL the truncation test."""
    c = df["close"].to_numpy(float)
    nxt = np.append(c[1:], np.nan)
    with np.errstate(invalid="ignore"):
        return nxt > c, nxt < c


def canary_v45_current(df, frames=None):
    return v45_amb(df, frames, mapping="current")


CANARIES = {"CANARY_LOOKAHEAD": canary_lookahead, "CANARY_V45_CURRENT_HTF": canary_v45_current}


# ---------------------------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------------------------
def compute_signals(panel: Dict[str, pd.DataFrame], tf: str, names: Optional[Sequence[str]] = None,
                    frames: Optional[Dict[str, Dict[str, pd.DataFrame]]] = None, strict: bool = True,
                    timings: Optional[list] = None, verbose: bool = False) -> Dict[str, Dict[str, np.ndarray]]:
    """{name: {sym: int8 array}} with +1 = long signal, -1 = short signal on that bar's close."""
    names = list(names or NAMES)
    out: Dict[str, Dict[str, np.ndarray]] = {n: {} for n in names}
    for sym, df in panel.items():
        df.attrs["tf"] = tf
        fr = frames.get(sym) if frames else None
        for name in names:
            t0 = time.time()
            try:
                L, Sh = REGISTRY[name](df, fr)
                L, Sh = _clean(L, Sh, len(df))
            except Exception as exc:  # noqa: BLE001
                if strict:
                    raise
                warnings.warn(f"{name} {sym} {tf}: {exc!r}")
                continue
            out[name][sym] = L.astype(np.int8) - Sh.astype(np.int8)
            dt = time.time() - t0
            if timings is not None:
                timings.append(dict(tf=tf, sym=sym, strategy=name, bars=len(df), sec=dt,
                                    n_sig=int(np.abs(out[name][sym]).sum())))
            if verbose:
                print(f"  {tf} {sym} {name:18s} bars={len(df)} sig={int(np.abs(out[name][sym]).sum())} {dt:.1f}s", flush=True)
    return out


def save_signals(path: str, sigs: Dict[str, Dict[str, np.ndarray]]):
    np.savez_compressed(path, **{f"{n}__{c}": a for n, d in sigs.items() for c, a in d.items()})


def load_signals(path: str) -> Dict[str, Dict[str, np.ndarray]]:
    z = np.load(path)
    out: Dict[str, Dict[str, np.ndarray]] = {}
    for k in z.files:
        n, c = k.split("__")
        out.setdefault(n, {})[c] = z[k]
    return out


# ---------------------------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------------------------
def _circ_corr(d: np.ndarray, R: np.ndarray, N: int) -> np.ndarray:
    """c[k] = sum_u d[u] r[(u+k) mod N] (R = rfft(r, N))  == statistic when d is rolled by k."""
    D = np.fft.rfft(d, N)
    return np.fft.irfft(np.conj(D) * R, N)


def gate_shifts(tf: str, H: int, n_min: int, B: int = B_GATE, lag: Optional[int] = None) -> np.ndarray:
    """Common random shifts, uniform integers in [lag+1, n_min-lag-1] (lag defaults to H);
    seeded by (SEED, tf minutes, H) so every agent draws identical shifts."""
    lag = H if lag is None else lag
    lo_k, hi_k = lag + 1, n_min - lag - 1
    if hi_k < lo_k:
        return np.zeros(0, dtype=np.int64)
    rng = np.random.default_rng([SEED, tf_minutes(tf), int(H), int(lag)])
    return rng.integers(lo_k, hi_k, size=B, endpoint=True)


def _prep_returns(panel: Dict[str, pd.DataFrame], tf: str, split: str, H: int) -> dict:
    prep = {}
    for c, df in panel.items():
        o = df["open"].to_numpy(float)
        lo, hi = signal_window(df, tf, split, H)
        N = hi - lo
        if N < 2 * H + 4:
            continue
        t = np.arange(lo, hi)
        r = o[t + 1 + H] / o[t + 1] - 1.0
        # self-normalised forward return (diagnostic, PREREG A1): r / sqrt(sum of squared 1-bar
        # open-to-open log returns inside the same forward window [t+1, t+1+H])
        lr2 = np.concatenate([[0.0], np.cumsum(np.diff(np.log(o)) ** 2)])
        rv = np.sqrt(lr2[t + 1 + H] - lr2[t + 1])
        with np.errstate(divide="ignore", invalid="ignore"):
            rn = np.where(rv > 0, np.log1p(r) / rv, 0.0)
        prep[c] = dict(lo=lo, hi=hi, N=N, r=r, R=np.fft.rfft(r, N), rv=rv, rn=rn, RN=np.fft.rfft(rn, N))
    return prep


def _cell_stats(dsig: Dict[str, np.ndarray], prep: dict, shifts: np.ndarray, all_shifts: Optional[np.ndarray],
                r_override: Optional[Dict[str, np.ndarray]] = None) -> dict:
    """Pooled signed forward-return mean and common-shift null for one strategy (one H)."""
    B = len(shifts)
    null_sum = np.zeros(B)
    null_vn = np.zeros(B)
    obs_vn = 0.0
    null_all = np.zeros(len(all_shifts)) if all_shifts is not None else None
    obs_sum = 0.0
    n = 0
    per = {}
    xs = []
    nl = ns = 0
    sl_sum = ss_sum = 0.0
    for c, pr in prep.items():
        if c not in dsig:
            continue
        d = dsig[c][pr["lo"]:pr["hi"]].astype(float)
        cnt = int(np.abs(d).sum())
        if cnt == 0:
            per[c] = (0, np.nan)
            continue
        if r_override is None:
            r, R, rn, RN = pr["r"], pr["R"], pr["rn"], pr["RN"]
        else:
            r = r_override[c]
            with np.errstate(divide="ignore", invalid="ignore"):
                rn = np.where(pr["rv"] > 0, np.log1p(r) / pr["rv"], 0.0)
            if all_shifts is None and cnt * B <= 4_000_000:
                R = RN = None
            else:
                R = np.fft.rfft(r, pr["N"])
                RN = np.fft.rfft(rn, pr["N"])
        s = float(d @ r)
        obs_sum += s
        n += cnt
        per[c] = (cnt, s / cnt)
        m = d != 0
        x = d[m] * r[m]
        xs.append(x)
        lm = d > 0
        nl += int(lm.sum()); ns += int((d < 0).sum())
        sl_sum += float(r[lm].sum()); ss_sum += float(-r[d < 0].sum())
        obs_vn += float(d @ rn)
        if null_all is None and cnt * B <= 4_000_000:
            # sparse direct gather (exact): statistic for roll k = sum_u d[u] r[(u+k) mod N]
            u = np.flatnonzero(d)
            w = d[u]
            pos = (u[None, :] + shifts[:, None]) % pr["N"]
            null_sum += (r[pos] * w).sum(axis=1)
            null_vn += (rn[pos] * w).sum(axis=1)
        else:
            D = np.fft.rfft(d, pr["N"])
            cc = np.fft.irfft(np.conj(D) * R, pr["N"])
            null_sum += cc[shifts]
            if null_all is not None:
                null_all += cc[all_shifts]
            null_vn += np.fft.irfft(np.conj(D) * RN, pr["N"])[shifts]
    out = dict(n=n, n_long=nl, n_short=ns, per=per)
    if n == 0:
        out.update(fwd=np.nan, fwd_long=np.nan, fwd_short=np.nan, null_mean=np.nan, null_sd=np.nan, z=np.nan,
                   p=np.nan, p_emp600=np.nan, p_emp_all=np.nan, t_naive=np.nan, fwd_vn=np.nan, z_vn=np.nan,
                   p_vn=np.nan)
        return out
    fwd = obs_sum / n
    nm = null_sum / n
    mu = float(nm.mean())
    sd = float(nm.std(ddof=1)) if B > 1 else np.nan
    z = (fwd - mu) / sd if sd and sd > 0 else np.nan
    x = np.concatenate(xs)
    t_naive = float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else np.nan
    out.update(fwd=fwd, fwd_long=(sl_sum / nl if nl else np.nan), fwd_short=(ss_sum / ns if ns else np.nan),
               null_mean=mu, null_sd=sd, z=z, p=float(norm.sf(z)) if np.isfinite(z) else np.nan,
               p_emp600=float((1 + (nm >= fwd).sum()) / (B + 1)), t_naive=t_naive)
    fv = obs_vn / n
    nv = null_vn / n
    sdv = float(nv.std(ddof=1)) if B > 1 else np.nan
    zv = (fv - float(nv.mean())) / sdv if sdv and sdv > 0 else np.nan
    out.update(fwd_vn=fv, z_vn=zv, p_vn=float(norm.sf(zv)) if np.isfinite(zv) else np.nan)
    if null_all is not None and len(null_all):
        na = null_all / n
        out["p_emp_all"] = float((1 + (na >= fwd).sum()) / (len(na) + 1))
        out["null_sd_all"] = float(na.std(ddof=1))
    else:
        out["p_emp_all"] = np.nan
    return out


def gate_from_signals(panel: Dict[str, pd.DataFrame], sigs: Dict[str, Dict[str, np.ndarray]], tf: str,
                      split: str = "is", Hs: Sequence[int] = HS, B: int = B_GATE, names: Optional[Sequence[str]] = None,
                      all_shift_null: bool = True) -> pd.DataFrame:
    names = list(names or sigs.keys())
    rows = []
    for H in Hs:
        prep = _prep_returns(panel, tf, split, H)
        if not prep:
            continue
        n_min = min(p["N"] for p in prep.values())
        shifts = gate_shifts(tf, H, n_min, B)
        all_shifts = np.arange(H + 1, n_min - H) if all_shift_null else None
        e_abs = float(np.mean(np.abs(np.concatenate([p["r"] for p in prep.values()]))))
        ch = cost_h(H, tf)
        mu_star = ch + HURDLE_K * e_abs
        for name in names:
            st = _cell_stats(sigs[name], prep, shifts, all_shifts)
            per = st.pop("per")
            n10 = [c for c, (k, m) in per.items() if k >= MIN_SIG_COIN]
            sp = int(sum(1 for c in n10 if per[c][1] > 0))
            meta = META.get(name, dict(group="other", approx=False, prev_examined=False, note=""))
            row = dict(strategy=name, tf=tf, H=H, split=split, group=meta["group"], approx=meta["approx"],
                       prev_examined=meta["prev_examined"], **st, cost_H=ch, E_abs_r=e_abs, mu_star=mu_star,
                       net_time=st["fwd"] - ch if np.isfinite(st["fwd"]) else np.nan,
                       fwd_minus_hurdle=st["fwd"] - mu_star if np.isfinite(st["fwd"]) else np.nan,
                       symbols_pos=sp, n_coins_ge10=len(n10), n_coins=len(prep), n_min=n_min, B=len(shifts))
            for c in COINS:
                k, m = per.get(c, (0, np.nan))
                row[f"n_{c}"] = k
                row[f"fwd_{c}"] = m
            rows.append(row)
    return pd.DataFrame(rows)


def gate(tf: str, split: str = "is", names: Optional[Sequence[str]] = None, panel=None, sigs=None,
         Hs: Sequence[int] = HS, B: int = B_GATE, cache: Optional[str] = None, verbose: bool = False,
         timings: Optional[list] = None) -> pd.DataFrame:
    """PREREG gate statistics for every strategy x H at one timeframe (raw p; Holm is applied by
    apply_gate() over the whole family)."""
    panel = panel if panel is not None else load_panel(tf, split)
    if sigs is None:
        if cache and os.path.exists(cache):
            sigs = load_signals(cache)
        else:
            sigs = compute_signals(panel, tf, names, verbose=verbose, timings=timings)
            if cache:
                save_signals(cache, sigs)
    return gate_from_signals(panel, sigs, tf, split, Hs, B, names)


def holm(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * p[i]))
        adj[i] = run
    return adj


def sympos_ok(symbols_pos, n_coins_ge10):
    sp = np.asarray(symbols_pos, int)
    n10 = np.asarray(n_coins_ge10, int)
    return (sp >= MIN_COINS_POS) | ((n10 > 0) & (sp * 10 >= 6 * n10))


def apply_gate(cells: pd.DataFrame, alpha: float = ALPHA) -> pd.DataFrame:
    """PREREG gate over the full family (all strategies x TFs x H with n >= 100).
    gate_pass_spec : the orchestrator's rule verbatim (Holm on p, fwd >= mu*, symbols, n)
    gate_pass      : DECISION column = gate_pass_spec AND Holm-adjusted p_vn < alpha (amendment A1,
                     same family; see PREREG section 4.2)."""
    c = cells.copy()
    fam = (c["n"] >= MIN_N) & np.isfinite(c["p"]) & np.isfinite(c["p_vn"])
    c["in_family"] = fam
    c["m_family"] = int(fam.sum())
    c["p_holm"] = np.nan
    c["p_vn_holm"] = np.nan
    if fam.any():
        c.loc[fam, "p_holm"] = holm(c.loc[fam, "p"].to_numpy())
        c.loc[fam, "p_vn_holm"] = holm(c.loc[fam, "p_vn"].to_numpy())
    c["sympos_ok"] = sympos_ok(c["symbols_pos"], c["n_coins_ge10"])
    c["gate_pass_spec"] = fam & (c["p_holm"] < alpha) & (c["fwd"] >= c["mu_star"]) & c["sympos_ok"] & (c["n"] >= MIN_N)
    c["gate_pass"] = c["gate_pass_spec"] & (c["p_vn_holm"] < alpha)
    return c


# ---------------------------------------------------------------------------------------------
# exit stage
# ---------------------------------------------------------------------------------------------
def exit_set(H: int) -> List[Tuple[str, ExitCfg, int]]:
    """(name, ExitCfg, max_hold bars).  Non-time exits are capped at EXIT_CAP_MULT*H bars."""
    cap = EXIT_CAP_MULT * H
    return [
        ("TIME_H", ExitCfg(name="TIME_H", mode="FIXED", sl_atr=1e4, tp_atr=1e4), H),
        ("ATR_SL2_TP3", ExitCfg(name="ATR_SL2_TP3", mode="FIXED", sl_atr=2.0, tp_atr=3.0), cap),
        ("ATR_SL3_TP6", ExitCfg(name="ATR_SL3_TP6", mode="FIXED", sl_atr=3.0, tp_atr=6.0), cap),
        ("TRAIL_SL3_TR3", ExitCfg(name="TRAIL_SL3_TR3", mode="TRAIL", sl_atr=3.0, trail_atr=3.0), cap),
        ("TIME_H_SL3", ExitCfg(name="TIME_H_SL3", mode="FIXED", sl_atr=3.0, tp_atr=1e4), H),
    ]


def _cost(tf: str, max_hold: int) -> CostCfg:
    return CostCfg(fee_side=FEE_SIDE, slip_side=SLIP_SIDE, funding_8h=FUNDING_8H, bar_minutes=tf_minutes(tf),
                   max_hold=int(max_hold), warmup=warmup_bars(tf))


def _run_exits_panel(panel, dsig, tf, split, H, atrs, windows, shift: int = 0, exits=None):
    """One pass of all exits over all coins.  shift>0 rolls each coin's signal array inside its
    admissible window [lo, hi) by `shift` bars (common shift)."""
    exits = exits or exit_set(H)
    res = {e[0]: [] for e in exits}
    for c, df in panel.items():
        if c not in dsig or c not in windows:
            continue
        lo, hi = windows[c]
        d = dsig[c]
        if shift:
            d = d.copy()
            d[lo:hi] = np.roll(d[lo:hi], shift)
        L, Sh = d > 0, d < 0
        for name, cfg, mh in exits:
            t = run_backtest(df, atrs[c], L, Sh, cfg, _cost(tf, mh), lo, hi)
            if len(t):
                t = t.assign(symbol=c)
                res[name].append(t)
    return {k: (pd.concat(v, ignore_index=True) if v else pd.DataFrame()) for k, v in res.items()}


def pooled_stats(tr: pd.DataFrame, panel: Dict[str, pd.DataFrame]) -> dict:
    if len(tr) == 0:
        return dict(trades=0, pf=np.nan, exp_net=np.nan, sum_net=0.0, wr=np.nan, symbols_pos=0, symbols=0,
                    months_pos=0, months=0, avg_hold=np.nan, exp_gross=np.nan)
    net = tr["net"].to_numpy(float)
    wins = net > 0
    gp, gl = net[wins].sum(), -net[~wins].sum()
    per_sym = tr.groupby("symbol")["net"].sum()
    ets = pd.Series(pd.NaT, index=tr.index, dtype="datetime64[ns, UTC]")
    for c, g in tr.groupby("symbol"):
        ets.loc[g.index] = panel[c]["ts"].to_numpy()[g["entry_idx"].to_numpy()]
    mon = tr.groupby(ets.dt.strftime("%Y-%m"))["net"].sum()
    return dict(trades=len(tr), pf=float(gp / gl) if gl > 0 else np.inf, exp_net=float(net.mean()),
                sum_net=float(net.sum()), wr=float(wins.mean()), exp_gross=float(tr["gross"].mean()),
                symbols_pos=int((per_sym > 0).sum()), symbols=int(len(per_sym)),
                months_pos=int((mon > 0).sum()), months=int(len(mon)), avg_hold=float(tr["hold"].mean()),
                n_long=int((tr["side"] > 0).sum()), n_short=int((tr["side"] < 0).sum()))


def exits(tf: str, strategy: str, H: int, panel: Dict[str, pd.DataFrame], sigs: Dict[str, Dict[str, np.ndarray]],
          split: str = "is", B: int = B_EXIT, return_trades: bool = False, verbose: bool = False):
    """PREREG exit stage for one (strategy, tf, H): 5 exits, one position per coin, realistic cost,
    common-shift null of net expectancy (B reps, shifts in [4H+1, n_min-4H-1]) and the
    studentised max-statistic p over the 5 exits."""
    dsig = sigs[strategy]
    atrs = {c: fg.atr(df, 14).to_numpy(float) for c, df in panel.items()}
    windows = {}
    for c, df in panel.items():
        lo, hi = signal_window(df, tf, split, 0)
        if hi - lo > 2 * EXIT_CAP_MULT * H + 4:
            windows[c] = (lo, hi)
    ex = exit_set(H)
    obs = _run_exits_panel(panel, dsig, tf, split, H, atrs, windows, 0, ex)
    rows = {k: pooled_stats(v, panel) for k, v in obs.items()}
    lag = EXIT_CAP_MULT * H
    n_min = min(hi - lo for lo, hi in windows.values()) if windows else 0
    shifts = gate_shifts(tf, H, n_min, B, lag=lag)
    null = np.full((len(shifts), len(ex)), np.nan)
    t0 = time.time()
    for b, k in enumerate(shifts):
        rb = _run_exits_panel(panel, dsig, tf, split, H, atrs, windows, int(k), ex)
        for j, (name, _cfg, _mh) in enumerate(ex):
            tr = rb[name]
            null[b, j] = float(tr["net"].mean()) if len(tr) else np.nan
        if verbose and (b + 1) % 50 == 0:
            print(f"    null {b + 1}/{len(shifts)} {time.time() - t0:.0f}s", flush=True)
    mu = np.nanmean(null, axis=0)
    sd = np.nanstd(null, axis=0, ddof=1)
    zn = (null - mu) / sd
    zmax = np.nanmax(zn, axis=1)
    out = []
    for j, (name, cfg, mh) in enumerate(ex):
        r = dict(strategy=strategy, tf=tf, H=H, exit=name, max_hold=mh, split=split, **rows[name])
        zo = (r["exp_net"] - mu[j]) / sd[j] if np.isfinite(r["exp_net"]) and sd[j] > 0 else np.nan
        r.update(null_mean=float(mu[j]), null_sd=float(sd[j]), z_exit=float(zo),
                 p_exit_single=float((1 + np.nansum(null[:, j] >= r["exp_net"])) / (len(shifts) + 1)) if np.isfinite(r["exp_net"]) else np.nan,
                 p_max=float((1 + np.sum(zmax >= zo)) / (len(shifts) + 1)) if np.isfinite(zo) else np.nan,
                 B=len(shifts))
        r["exit_pass"] = bool(r["trades"] >= MIN_TRADES and np.isfinite(r["pf"]) and r["pf"] >= PF_EXIT
                              and r["exp_net"] > 0 and r["symbols_pos"] >= MIN_COINS_POS
                              and np.isfinite(r["p_max"]) and r["p_max"] < ALPHA)
        meta = META.get(strategy, {})
        r.update(group=meta.get("group"), approx=meta.get("approx"), prev_examined=meta.get("prev_examined"))
        out.append(r)
    df_out = pd.DataFrame(out)
    if return_trades:
        return df_out, obs
    return df_out


def select_exits(exit_rows: pd.DataFrame) -> pd.DataFrame:
    """Per surviving (strategy, tf): the single passing exit with the highest pooled net
    expectancy; ties -> TIME_H, then smaller H."""
    p = exit_rows[exit_rows["exit_pass"]].copy()
    if p.empty:
        return p
    p["_time"] = (p["exit"] == "TIME_H").astype(int)
    p = p.sort_values(["strategy", "tf", "exp_net", "_time", "H"], ascending=[True, True, False, False, True])
    return p.groupby(["strategy", "tf"], as_index=False).head(1).drop(columns="_time")


def holdout_confirm(exit_row_oos: dict, gate_cell_oos: dict) -> dict:
    """PREREG holdout rule for a carried combo."""
    ok_net = bool(np.isfinite(exit_row_oos.get("exp_net", np.nan)) and exit_row_oos["exp_net"] > 0)
    ok_pf = bool(np.isfinite(exit_row_oos.get("pf", np.nan)) and exit_row_oos["pf"] >= PF_HOLDOUT)
    ok_p = bool(np.isfinite(gate_cell_oos.get("p", np.nan)) and gate_cell_oos["p"] < ALPHA
                and np.isfinite(gate_cell_oos.get("p_vn", np.nan)) and gate_cell_oos["p_vn"] < ALPHA)   # A1
    ok_c = bool(exit_row_oos.get("symbols_pos", 0) >= MIN_COINS_POS)
    return dict(net_ok=ok_net, pf_ok=ok_pf, gate_p_ok=ok_p, coins_ok=ok_c, confirmed=ok_net and ok_pf and ok_p and ok_c)


def persistence(is_cells: pd.DataFrame, oos_cells: pd.DataFrame, top: int = 10) -> dict:
    """Descriptive: Spearman of IS vs OOS (fwd - mu*) over all common cells; OOS values of the
    top-`top` IS cells by z."""
    k = ["strategy", "tf", "H"]
    m = is_cells[k + ["fwd_minus_hurdle", "z", "n"]].merge(
        oos_cells[k + ["fwd_minus_hurdle", "z", "n", "p", "fwd", "mu_star"]], on=k, suffixes=("_is", "_oos"))
    m = m[np.isfinite(m["fwd_minus_hurdle_is"]) & np.isfinite(m["fwd_minus_hurdle_oos"])]
    rho, pv = spearmanr(m["fwd_minus_hurdle_is"], m["fwd_minus_hurdle_oos"]) if len(m) > 2 else (np.nan, np.nan)
    topc = m.sort_values("z_is", ascending=False).head(top)
    return dict(n_cells=len(m), spearman=float(rho), spearman_p=float(pv), top=topc)


# ---------------------------------------------------------------------------------------------
# synthetic data
# ---------------------------------------------------------------------------------------------
def _freq(tf: str) -> str:
    return f"{tf_minutes(tf)}min"


def synth_ohlcv(n: int, tf: str, seed: int = 0, start: str = "2021-07-01", daily_vol: float = 0.035,
                n_sub: int = 6, gaps: int = 0, price0: float = 100.0, tail_df: float = 4.0,
                drift: float = 0.08) -> pd.DataFrame:
    """Synthetic OHLCV with stochastic volatility, fat tails and drifting trend regimes (so trend
    and oscillator strategies fire).  `gaps` random bars are deleted to exercise partial bins."""
    rng = np.random.default_rng(seed)
    m = tf_minutes(tf)
    sig = daily_vol * math.sqrt(m / 1440.0)
    hl = max(5.0, 3 * 1440.0 / m)
    phi = 0.5 ** (1.0 / hl)
    e = rng.normal(0, 0.45 * math.sqrt(1 - phi ** 2), n)
    lv = np.zeros(n)
    for i in range(1, n):
        lv[i] = phi * lv[i - 1] + e[i]
    seg = rng.geometric(1 / 150.0, size=n // 10 + 10)
    mu = np.repeat(rng.normal(0, drift * sig, len(seg)), seg)[:n]
    z = rng.standard_t(tail_df, size=(n, n_sub)) / math.sqrt(tail_df / (tail_df - 2.0))
    inc = (mu[:, None] / n_sub) + (sig * np.exp(lv))[:, None] * z / math.sqrt(n_sub)
    path = np.cumsum(inc.ravel()).reshape(n, n_sub)
    start_lvl = np.concatenate([[0.0], path[:-1, -1]])
    op = start_lvl
    cl = path[:, -1]
    hi = np.maximum(path.max(axis=1), op)
    lo = np.minimum(path.min(axis=1), op)
    px = lambda a: price0 * np.exp(a)  # noqa: E731
    vol = rng.lognormal(3, 0.5, n) * (1 + 3 * np.abs(cl - op) / sig)
    ts = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=n, freq=_freq(tf))
    df = pd.DataFrame({"ts": ts, "open": px(op), "high": px(hi), "low": px(lo), "close": px(cl), "volume": vol})
    if gaps:
        drop = rng.choice(np.arange(50, n - 50), size=gaps, replace=False)
        df = df.drop(index=drop).reset_index(drop=True)
    df.attrs["tf"] = tf
    return df


SYNTH_VOLS = dict(BTCUSD=0.030, ETHUSD=0.038, SOLUSD=0.055, XRPUSD=0.045, DOGEUSD=0.050, LTCUSD=0.043, BCHUSD=0.045)


def seasonal_mult(ts, amp: float = 0.5) -> np.ndarray:
    """Intraday volatility multiplier used by the synthetic panel (peak 15:00 UTC)."""
    h = pd.to_datetime(pd.Series(ts), utc=True)
    hh = (h.dt.hour + h.dt.minute / 60.0).to_numpy()
    return 1.0 + amp * np.cos(2 * np.pi * (hh - 15.0) / 24.0)


def synth_panel(tf: str, n_days: int = 1096, seed: int = 0, rho: float = 0.75, start: str = "2021-07-01",
                coins: Sequence[str] = COINS, season_amp: float = 0.5) -> Dict[str, pd.DataFrame]:
    """Zero-drift multi-coin panel (open-to-open path only; high=low=close=next open) with a
    common factor (corr ~rho), common stochastic volatility, t(4) innovations.  For controls."""
    rng = np.random.default_rng(seed)
    m = tf_minutes(tf)
    n = int(n_days * 1440 // m)
    hl = max(5.0, 3 * 1440.0 / m)
    phi = 0.5 ** (1.0 / hl)
    from scipy.signal import lfilter
    lv = lfilter([1.0], [1.0, -phi], rng.normal(0, 0.45 * math.sqrt(1 - phi ** 2), n))
    f = rng.standard_t(4, n) / math.sqrt(2.0)
    ts = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=n, freq=_freq(tf))
    sm = seasonal_mult(ts, season_amp) if m < 1440 else np.ones(n)
    sm = sm / np.sqrt(np.mean(sm ** 2))
    out = {}
    for c in coins:
        sig = SYNTH_VOLS.get(c, 0.04) * math.sqrt(m / 1440.0)
        eps = rng.standard_t(4, n) / math.sqrt(2.0)
        r = sig * sm * np.exp(lv) * (math.sqrt(rho) * f + math.sqrt(1 - rho) * eps)
        o = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(r[:-1])]))
        cl = np.append(o[1:], o[-1])
        df = pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, cl), "low": np.minimum(o, cl), "close": cl,
                           "volume": 1.0})
        df.attrs["tf"] = tf
        out[c] = df
    return out


# ---------------------------------------------------------------------------------------------
# controls (planted drift / zero edge)
# ---------------------------------------------------------------------------------------------
def _rand_signals(kind: str, prep: dict, panel, n_target: int, rng) -> Dict[str, np.ndarray]:
    tot = sum(p["N"] for p in prep.values())
    rate = n_target / tot
    out = {}
    for c, p in prep.items():
        N = p["N"]
        d = np.zeros(len(panel[c]), np.int8)
        side = rng.choice(np.array([-1, 1], np.int8), size=N)
        if kind == "iid":
            m = rng.random(N) < rate
            seg = np.where(m, side, 0).astype(np.int8)
        elif kind == "burst4":
            st = rng.random(N) < rate / 4.0
            seg = np.zeros(N, np.int8)
            for j in range(4):
                idx = np.where(st)[0] + j
                idx = idx[idx < N]
                seg[idx] = side[idx - j]
        elif kind == "hourtimed":
            if "w_hour" not in p:
                w = seasonal_mult(panel[c]["ts"].to_numpy()[p["lo"]:p["hi"]]) ** 2
                p["w_hour"] = w / w.mean()
            prob = np.clip(rate * p["w_hour"], 0, 1)
            seg = np.where(rng.random(N) < prob, side, 0).astype(np.int8)
        elif kind == "voltimed":
            if "w_vol" not in p:
                o = panel[c]["open"].to_numpy(float)
                lr = np.diff(np.log(o), prepend=np.log(o[0]))
                rv = pd.Series(lr).rolling(48, min_periods=10).std().to_numpy()[p["lo"]:p["hi"]]
                w = np.nan_to_num(rv / np.nanmedian(rv), nan=1.0) ** 2
                p["w_vol"] = w / w.mean()
            prob = np.clip(rate * p["w_vol"], 0, 1)
            seg = np.where(rng.random(N) < prob, side, 0).astype(np.int8)
        else:
            raise ValueError(kind)
        d[p["lo"]:p["hi"]] = seg
        out[c] = d
    return out


def controls(tf: str, panel: Dict[str, pd.DataFrame], split: str = "is", Hs: Sequence[int] = HS, reps: int = 200,
             n_targets: Sequence[int] = (150, 500, 2000),
             kinds: Sequence[str] = ("iid", "burst4", "voltimed", "hourtimed"),
             B: int = B_GATE, m_family: int = 666, planted_mult: float = 1.5, seed: int = 1) -> pd.DataFrame:
    """Negative control: zero-edge random signals -> false-pass rates.
    Positive control: the same signals with every signal's H-bar forward return shifted by
    planted_mult * mu*_H in the signal direction -> detection power.
    'gate' = full PREREG rule with the first Holm step for a family of m_family cells
    (p < alpha/m, fwd >= mu*, symbols rule, n >= 100)."""
    rows = []
    rng = np.random.default_rng([seed, tf_minutes(tf)])
    p_holm1 = ALPHA / m_family
    for H in Hs:
        prep = _prep_returns(panel, tf, split, H)
        if not prep:
            continue
        n_min = min(p["N"] for p in prep.values())
        shifts = gate_shifts(tf, H, n_min, B)
        e_abs = float(np.mean(np.abs(np.concatenate([p["r"] for p in prep.values()]))))
        mu_star = cost_h(H, tf) + HURDLE_K * e_abs
        delta = planted_mult * mu_star
        for kind in kinds:
            for nt in n_targets:
                acc = []
                for _ in range(reps):
                    dsig = _rand_signals(kind, prep, panel, nt, rng)
                    res = {}
                    for lab, dl in (("null", 0.0), ("planted", delta)):
                        r_ov = None
                        if dl:
                            r_ov = {c: p["r"] + dl * dsig[c][p["lo"]:p["hi"]] for c, p in prep.items()}
                        st = _cell_stats(dsig, prep, shifts, None, r_override=r_ov)
                        per = st["per"]
                        n10 = [c for c, (k, m) in per.items() if k >= MIN_SIG_COIN]
                        sp = sum(1 for c in n10 if per[c][1] > 0)
                        ok_sym = bool(sympos_ok([sp], [len(n10)])[0])
                        passed = bool(np.isfinite(st["p"]) and st["p"] < p_holm1 and st["fwd"] >= mu_star
                                      and ok_sym and st["n"] >= MIN_N)
                        res[lab] = (st, passed)
                    s0, g0 = res["null"]
                    s1, g1 = res["planted"]
                    acc.append(dict(n=s0["n"], z0=s0["z"], p0=s0["p"], pe0=s0["p_emp600"], t0=s0["t_naive"],
                                    sd0=s0["null_sd"], fwd0=s0["fwd"], g0=g0, fwd1=s1["fwd"], p1=s1["p"], g1=g1,
                                    zv0=s0["z_vn"], pv0=s0["p_vn"], pv1=s1["p_vn"],
                                    g1v=bool(g1 and np.isfinite(s1["p_vn"]) and s1["p_vn"] < p_holm1),
                                    g0v=bool(g0 and np.isfinite(s0["p_vn"]) and s0["p_vn"] < p_holm1)))
                a = pd.DataFrame(acc)
                sdm = float(a["sd0"].median())
                rows.append(dict(
                    tf=tf, H=H, kind=kind, n_target=nt, reps=reps, n_mean=float(a["n"].mean()), mu_star=mu_star,
                    E_abs_r=e_abs, cost_H=cost_h(H, tf), delta=delta,
                    null_rate_p05=float((a["p0"] < 0.05).mean()), null_rate_p01=float((a["p0"] < 0.01).mean()),
                    null_rate_emp05=float((a["pe0"] < 0.05).mean()),
                    null_rate_holm1=float((a["p0"] < p_holm1).mean()), null_rate_gate=float(a["g0"].mean()),
                    null_rate_naive_t05=float((norm.sf(a["t0"]) < 0.05).mean()),
                    null_z_sd=float(a["z0"].std(ddof=1)), null_sd_median=sdm,
                    mde80_holm=(norm.isf(p_holm1) + norm.isf(0.2)) * sdm,
                    mde80_over_mu=(norm.isf(p_holm1) + norm.isf(0.2)) * sdm / mu_star,
                    power_gate=float(a["g1"].mean()), power_p05=float((a["p1"] < 0.05).mean()),
                    power_holm1=float((a["p1"] < p_holm1).mean()),
                    planted_frac_fwd_ge_mu=float((a["fwd1"] >= mu_star).mean()),
                    vn_null_rate_p05=float((a["pv0"] < 0.05).mean()), vn_null_rate_holm1=float((a["pv0"] < p_holm1).mean()),
                    vn_null_z_sd=float(a["zv0"].std(ddof=1)), null_rate_gate_and_vn=float(a["g0v"].mean()),
                    vn_power_p05=float((a["pv1"] < 0.05).mean()), power_gate_and_vn=float(a["g1v"].mean()),
                    null_max_z=float(a["z0"].max()), vn_null_max_z=float(a["zv0"].max())))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# look-ahead (truncation) test
# ---------------------------------------------------------------------------------------------
def _signals_one(fn, df, frames):
    L, Sh = fn(df, frames)
    return _clean(L, Sh, len(df))


def truncation_test(df: pd.DataFrame, tf: str, names: Optional[Sequence[str]] = None, n_even: int = 4,
                    n_at_signal: int = 3, seed: int = 0, include_canaries: bool = True,
                    min_start_frac: float = 0.35) -> pd.DataFrame:
    """For each registry entry: signals computed on df[:t+1] must equal the full-data signals on
    ALL bars 0..t (not only bar t), for several cut points t (evenly spaced, at signal bars, and
    for V4.5 at HTF-bin boundaries).  V4.5 is tested twice: HTF resampled from the truncated
    chart, and an explicit HTF frame truncated to bars whose close <= open time of bar t."""
    df = df.reset_index(drop=True).copy()
    df.attrs["tf"] = tf
    names = list(names or NAMES)
    fns = {n: REGISTRY[n] for n in names}
    if include_canaries:
        fns.update(CANARIES)
    rng = np.random.default_rng(seed)
    N = len(df)
    htf = HTF_OF[tf]
    htf_full = resample_ohlcv(df, htf)
    hclose = htf_close_ns(htf_full["ts"], htf)
    ts_open = _utc_ns(df["ts"])
    full = {}
    for n, fn in fns.items():
        fr = {htf: htf_full} if n in ("V45_AMB", "CANARY_V45_CURRENT_HTF") else None
        full[n] = _signals_one(fn, df, fr)
    base_cuts = list(np.linspace(int(N * min_start_frac), N - 2, n_even).astype(int))
    # HTF boundary cuts: chart bar opening exactly on an HTF close, and the bar before it
    on_b = np.where(np.isin(ts_open, hclose))[0]
    on_b = on_b[on_b > N * min_start_frac]
    hb = []
    if len(on_b):
        j = int(on_b[len(on_b) // 2])
        hb = [j, j - 1]
    rows = []
    for n, fn in fns.items():
        L0, S0 = full[n]
        sig_idx = np.where((L0 | S0)[int(N * min_start_frac):N - 1])[0] + int(N * min_start_frac)
        at_sig = list(rng.choice(sig_idx, size=min(n_at_signal, len(sig_idx)), replace=False)) if len(sig_idx) else []
        before_sig = [int(x) - 1 for x in at_sig[:2]]
        cuts = sorted(set(base_cuts + at_sig + before_sig + (hb if n in ("V45_AMB", "CANARY_V45_CURRENT_HTF") else [])))
        modes = ["resample", "explicit"] if n in ("V45_AMB", "CANARY_V45_CURRENT_HTF") else ["plain"]
        for mode in modes:
            L_ref, S_ref = L0, S0
            if mode == "resample":
                L_ref, S_ref = _signals_one(fn, df, None)
            for t in cuts:
                d_t = df.iloc[: t + 1].copy()
                d_t.attrs["tf"] = tf
                fr = None
                if mode == "explicit":
                    fr = {htf: htf_full.loc[hclose <= ts_open[t]].reset_index(drop=True)}
                t0 = time.time()
                try:
                    Lt, St = _signals_one(fn, d_t, fr)
                    err = ""
                except Exception as exc:  # noqa: BLE001
                    Lt = St = None
                    err = repr(exc)
                if Lt is None:
                    ok = False; mism = -1
                else:
                    eqL = Lt == L_ref[: t + 1]; eqS = St == S_ref[: t + 1]
                    ok = bool(eqL.all() and eqS.all())
                    bad = np.where(~(eqL & eqS))[0]
                    mism = int(bad[0]) if len(bad) else -1
                rows.append(dict(strategy=n, tf=tf, mode=mode, cut=int(t), cut_ts=str(df["ts"].iloc[t]),
                                 n_bars=N, sig_full=int((L_ref | S_ref).sum()),
                                 sig_prefix=int((L_ref[: t + 1] | S_ref[: t + 1]).sum()),
                                 sig_at_cut=bool(L_ref[t] or S_ref[t]), identical_prefix=ok, first_mismatch=mism,
                                 canary=n.startswith("CANARY"), error=err, sec=time.time() - t0))
    # component-level check of the HTF mapping (V4.5): mapped HTF ST direction and STC on the
    # prefix must be identical (a final-signal check alone rarely sees an HTF leak because the
    # signal is rare)
    for lab, mapping in (("V45_AMB", "closed"), ("CANARY_V45_CURRENT_HTF", "current")):
        if lab not in fns:
            continue
        ref_d, ref_s = v45_htf_components(df, htf_full, htf, mapping)
        ref_rd, ref_rs = v45_htf_components(df, resample_ohlcv(df, htf), htf, mapping)
        cuts = sorted(set(base_cuts + hb + [int(x) for x in rng.integers(int(N * min_start_frac), N - 1, 6)]))
        for mode in ("components_explicit", "components_resample"):
            for t in cuts:
                d_t = df.iloc[: t + 1].copy()
                if mode == "components_explicit":
                    h_t = htf_full.loc[hclose <= ts_open[t]].reset_index(drop=True)
                    rd, rs_ = ref_d, ref_s
                else:
                    h_t = resample_ohlcv(d_t, htf)
                    rd, rs_ = ref_rd, ref_rs
                dt_, st_ = v45_htf_components(d_t, h_t, htf, mapping)
                eq = (dt_ == rd[: t + 1]) & ((st_ == rs_[: t + 1]) | (np.isnan(st_) & np.isnan(rs_[: t + 1])))
                bad = np.where(~eq)[0]
                rows.append(dict(strategy=lab, tf=tf, mode=mode, cut=int(t), cut_ts=str(df["ts"].iloc[t]), n_bars=N,
                                 sig_full=int(np.isfinite(rs_).sum()), sig_prefix=int(np.isfinite(rs_[: t + 1]).sum()),
                                 sig_at_cut=False, identical_prefix=bool(eq.all()),
                                 first_mismatch=int(bad[0]) if len(bad) else -1, canary=lab.startswith("CANARY"),
                                 error="", sec=0.0))
    return pd.DataFrame(rows)


def htf_mapping_check(df: pd.DataFrame, tf: str) -> dict:
    """Every chart bar maps to the last HTF bar with close <= chart open; the next HTF bar (if
    any) closes after the chart open."""
    htf = HTF_OF[tf]
    h = resample_ohlcv(df, htf)
    hc = htf_close_ns(h["ts"], htf)
    to = _utc_ns(df["ts"])
    idx = np.searchsorted(hc, to, side="right") - 1
    ok_used = np.all(hc[idx[idx >= 0]] <= to[idx >= 0])
    nxt = idx + 1
    has = nxt < len(hc)
    ok_next = np.all(hc[nxt[has]] > to[has])
    wk = True
    if htf == "1w":
        wk = bool(np.all(pd.to_datetime(h["ts"], utc=True).dt.dayofweek == 0))
    return dict(tf=tf, htf=htf, chart_bars=len(df), htf_bars=len(h), used_closed_before_open=bool(ok_used),
                next_closes_after_open=bool(ok_next), weekly_bins_monday=wk,
                share_unmapped=float((idx < 0).mean()))
