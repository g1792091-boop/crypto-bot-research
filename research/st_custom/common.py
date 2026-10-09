"""Shared code of the Supertrend custom-value study (PREREG.md, hash in PREREG.sha256; PREREG_ADDENDUM_1.md).

Paths, constants, the grid, data loading, the locked signal code (param_defs, hash-checked against the pinned
DEFS_BC.sha256 as lens2_custom_values/cvlib.py did), memoised indicator calls, and the exit simulations:

  * house exit: copied from analysis/rulebot_1007/pending_1007_night/lens2_multi_tf_done/precompute.py (sizer, scan),
    generalised to a given entry price (MAKER) and a switchable ladder (STFLIP stop-only scan); with the ladder and the
    default arguments it is the same arithmetic as precompute.scan (checked in selfcheck.py).
  * TPSL: fixed take-profit / stop scan on 15m bars (no ladder).
Nothing outside research/st_custom and the scratch work folder is written.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import time

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

REPO = "/home/user/crypto-bot-research"
for _p in ("/root/.local/lib/python3.11/site-packages", REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from paperbot import sweepsig  # noqa: E402

sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path
import fg_fast  # noqa: E402
import fg_indicators as fg  # noqa: E402
import pine_indicators as pi  # noqa: E402
from paperbot.config import v3_settings  # noqa: E402
from paperbot.ladder import LadderSpec  # noqa: E402
from paperbot.margin import BracketTier, Brackets, liquidation_price  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
WORK = os.path.join(SCR, "st_custom_work")
BARS_DIR = os.path.join(WORK, "bars")
OUTC_DIR = os.path.join(WORK, "outcomes")
SIG_DIR = os.path.join(WORK, "signals")
TOT_DIR = os.path.join(WORK, "totals")
for _d in (OUT, WORK, BARS_DIR, OUTC_DIR, SIG_DIR, TOT_DIR):
    os.makedirs(_d, exist_ok=True)

PREREG = os.path.join(HERE, "PREREG.md")
PREREG_SHA = os.path.join(HERE, "PREREG.sha256")
ADDENDUM = os.path.join(HERE, "PREREG_ADDENDUM_1.md")
ADDENDUM_SHA256 = "203f8cfb23edc546253b50264bfb556cab9743c4e56738512356ab832e439737"  # as received 2026-10-09
PARAM_DIR = os.path.join(REPO, "research", "entry_study", "param_defs")
DEFS_MANIFEST = os.path.join(REPO, "research", "entry_study", "DEFS_BC.sha256")
DEFS_MANIFEST_PIN = "185dbcf858e93f694d0775e12925c1904373d0db002a4df7bf3cfcefa3d56044"

COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD", "XRPUSD")
TFS = ("15m", "30m")
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "4h": 240}
NS_MIN = 60 * 10**9
NS_WEEK = 7 * 86400 * 10**9
WEEK0 = int(pd.Timestamp("2019-12-30", tz="UTC").value)   # a Monday 00:00 UTC; week index = (ts - WEEK0) // NS_WEEK

PERIODS = {   # signal-bar open time in [start, end)
    "EXTRA": ("2020-01-01", "2021-01-01"),
    "SEARCH": ("2021-01-01", "2024-01-01"),
    "TEST": ("2024-01-01", "2026-09-30"),
}
PERIOD_ORDER = ("SEARCH", "TEST", "EXTRA")
WARM = 500          # PREREG: 500 bars of warm-up before each period start
SPILL = 4000        # bars computed after a period end (signals are causal; only STFLIP exits use them)
CRASH = {"2020-03": ("2020-03-01", "2020-04-01"), "2022-05": ("2022-05-01", "2022-06-01"),
         "2022-11": ("2022-11-01", "2022-12-01")}

# ------------------------------------------------------------------ house settings (paperbot config.v3_settings)
S = v3_settings()
LAD = LadderSpec(S.ladder_first_lock, S.ladder_step, S.ladder_trigger_gap)
K_STOP = 2.0
FUNDING_8H = 0.0001
F_BAR15 = FUNDING_8H * 15 / 480.0
TAKER, SLIP, MAKER = S.taker_fee, S.slippage_frac, S.maker_fee
EQUITY_SIZER = 5000.0
INFERRED_BRACKETS = {   # copied from lens2_multi_tf_done/precompute.py (fit to live trades' liquidation prices)
    "BTCUSD": [(1e12, 50, 0.004, 0.0)],
    "ETHUSD": [(1e12, 50, 0.004, 0.0)],
    "SOLUSD": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGEUSD": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCHUSD": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTCUSD": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}
# XRP was never traded live, so no fitted brackets exist: DEVIATIONS.md D3 (DOGE's table is used).
INFERRED_BRACKETS["XRPUSD"] = INFERRED_BRACKETS["DOGEUSD"]
BR = {c: Brackets([BracketTier(*t) for t in v]) for c, v in INFERRED_BRACKETS.items()}

# ------------------------------------------------------------------ grid (PREREG "Strategies and grid")
ST_ATR = (5, 7, 8, 10, 12, 14, 20)
ST_MULT = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0)
ROC_LEN = (5, 9, 14, 21, 28, 37, 50)
KST_SCALE = (0.5, 0.75, 1.0, 1.5, 2.0)
KST_SIG = (5, 9, 13)
KVO_SCALE = (0.5, 0.75, 1.0, 1.5)
KVO_SIG = (7, 13, 21)
STRATS = ("S2_ST_ROC", "N02_ST_KST", "N04_ST_KLINGER")
SHORT = {"S2_ST_ROC": "S2", "N02_ST_KST": "N02", "N04_ST_KLINGER": "N04"}


def round_len(x: float) -> int:
    """param_defs rule: round half up, min 2."""
    return max(2, int(math.floor(float(x) + 0.5)))


KST_ROC_BASE = (10, 15, 20, 30)
KVO_BASE = (34, 55)
KST_ROCS = tuple(tuple(round_len(v * s) for v in KST_ROC_BASE) for s in KST_SCALE)
KVO_LENS = tuple(tuple(round_len(v * s) for v in KVO_BASE) for s in KVO_SCALE)

DIMS = {  # per strategy: list of (name, values)
    "S2_ST_ROC": [("st_atr_len", ST_ATR), ("st_mult", ST_MULT), ("roc_len", ROC_LEN)],
    "N02_ST_KST": [("st_atr_len", ST_ATR), ("st_mult", ST_MULT), ("kst_scale", KST_SCALE), ("kst_signal_len", KST_SIG)],
    "N04_ST_KLINGER": [("st_atr_len", ST_ATR), ("st_mult", ST_MULT), ("kvo_scale", KVO_SCALE),
                       ("kvo_signal_len", KVO_SIG)],
}
SHAPE = {k: tuple(len(v) for _n, v in d) for k, d in DIMS.items()}
NCOMBO = {k: int(np.prod(s)) for k, s in SHAPE.items()}           # 343 / 735 / 588
DEFAULT_IDX = {"S2_ST_ROC": (3, 6, 1), "N02_ST_KST": (3, 6, 2, 1), "N04_ST_KLINGER": (3, 6, 2, 1)}
FRIEND_IDX = {"S2_ST_ROC": (2, 3, 5), "N04_ST_KLINGER": (2, 3, 2, 1)}   # S2 8/3/ROC 37; N04 8/3/Klinger default


def combo_index(strat: str, idx) -> int:
    return int(np.ravel_multi_index(tuple(idx), SHAPE[strat]))


def combo_tuple(strat: str, c: int) -> tuple:
    return tuple(int(x) for x in np.unravel_index(int(c), SHAPE[strat]))


def combo_values(strat: str, c: int) -> dict:
    t = combo_tuple(strat, c)
    return {n: vals[i] for (n, vals), i in zip(DIMS[strat], t)}


def combo_label(strat: str, c: int) -> str:
    v = combo_values(strat, c)
    if strat == "S2_ST_ROC":
        return f"ST {v['st_atr_len']}/{v['st_mult']:g} ROC {v['roc_len']}"
    if strat == "N02_ST_KST":
        return f"ST {v['st_atr_len']}/{v['st_mult']:g} KSTx{v['kst_scale']:g} sig {v['kst_signal_len']}"
    return f"ST {v['st_atr_len']}/{v['st_mult']:g} KVOx{v['kvo_scale']:g} sig {v['kvo_signal_len']}"


def overrides(strat: str, c: int) -> dict:
    """param_defs override dict of combo c."""
    t = combo_tuple(strat, c)
    ov = {"st_atr_len": ST_ATR[t[0]], "st_mult": ST_MULT[t[1]]}
    if strat == "S2_ST_ROC":
        ov["roc_len"] = ROC_LEN[t[2]]
    elif strat == "N02_ST_KST":
        ov["kst_roc_lens"] = list(KST_ROCS[t[2]])
        ov["kst_signal_len"] = KST_SIG[t[3]]
    else:
        ov["kvo_lens"] = list(KVO_LENS[t[2]])
        ov["kvo_signal_len"] = KVO_SIG[t[3]]
    return ov


def neighbours(strat: str, c: int, include_self: bool = True) -> np.ndarray:
    """Combos within +-1 step in every dimension (Moore neighbourhood, clipped at the grid edge); the combo itself
    counted once (PREREG 'Selection')."""
    t = np.array(combo_tuple(strat, c))
    shp = SHAPE[strat]
    offs = np.array(np.meshgrid(*[[-1, 0, 1]] * len(shp), indexing="ij")).reshape(len(shp), -1).T
    pts = t[None, :] + offs
    ok = np.all((pts >= 0) & (pts < np.array(shp)[None, :]), axis=1)
    pts = pts[ok]
    out = np.ravel_multi_index(tuple(pts.T), shp)
    if not include_self:
        out = out[out != c]
    return np.unique(out)


def neighbour_matrix(strat: str):
    """Sparse (rows = combo, cols = neighbourhood incl. self) as a dense 0/1 float32 matrix (<= 735 x 735)."""
    n = NCOMBO[strat]
    M = np.zeros((n, n), np.float32)
    for c in range(n):
        M[c, neighbours(strat, c)] = 1.0
    return M


# ------------------------------------------------------------------ hashes
def sha256_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def check_prereg() -> dict:
    want = open(PREREG_SHA).read().split()[0]
    got = sha256_file(PREREG)
    if want != got:
        raise SystemExit(f"PREREG.md changed: {got} != {want}")
    add = sha256_file(ADDENDUM)
    if add != ADDENDUM_SHA256:
        raise SystemExit(f"PREREG_ADDENDUM_1.md changed: {add}")
    return {"prereg_sha256": got, "addendum_sha256": add}


_MODS: dict = {}


def load_param_def(name: str):
    """Locked param_defs/<name>.py, checked against DEFS_BC.sha256 (whose own hash is pinned)."""
    if name in _MODS:
        return _MODS[name]
    if sha256_file(DEFS_MANIFEST) != DEFS_MANIFEST_PIN:
        raise SystemExit("DEFS_BC.sha256 does not match its pinned hash")
    exp = None
    for line in open(DEFS_MANIFEST):
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == f"param_defs/{name}.py":
            exp = parts[0].lower()
    path = os.path.join(PARAM_DIR, f"{name}.py")
    data = open(path, "rb").read()
    if hashlib.sha256(data).hexdigest() != exp:
        raise SystemExit(f"param_defs/{name}.py hash mismatch")
    spec = importlib.util.spec_from_file_location(f"_stc_pd_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    exec(compile(data, path, "exec"), mod.__dict__)
    _MODS[name] = mod
    return mod


# ------------------------------------------------------------------ memoised locked indicators
_MEMO: dict = {}
_TOKEN = [None]
_ORIG = {"st": fg_fast.supertrend, "kst": fg.kst, "kvo": fg.klinger_oscillator}


def _st_memo(df, atr_length=10, multiplier=3.0):
    if _TOKEN[0] is None:
        return _ORIG["st"](df, atr_length, multiplier)
    key = ("st", _TOKEN[0], len(df), int(atr_length), float(multiplier))
    if key not in _MEMO:
        _MEMO[key] = _ORIG["st"](df, atr_length, multiplier)
    return tuple(s.copy() for s in _MEMO[key])


def _kst_memo(close, roc_lengths=(10, 15, 20, 30), sma_lengths=(10, 10, 10, 15), signal_length=9):
    if _TOKEN[0] is None:
        return _ORIG["kst"](close, roc_lengths, sma_lengths, signal_length)
    key = ("kst", _TOKEN[0], len(close), tuple(int(x) for x in roc_lengths), tuple(int(x) for x in sma_lengths),
           int(signal_length))
    if key not in _MEMO:
        _MEMO[key] = _ORIG["kst"](close, roc_lengths, sma_lengths, signal_length)
    return tuple(s.copy() for s in _MEMO[key])


def _kvo_memo(df, fast_length=34, slow_length=55, signal_length=13):
    if _TOKEN[0] is None:
        return _ORIG["kvo"](df, fast_length, slow_length, signal_length)
    key = ("kvo", _TOKEN[0], len(df), int(fast_length), int(slow_length), int(signal_length))
    if key not in _MEMO:
        _MEMO[key] = _ORIG["kvo"](df, fast_length, slow_length, signal_length)
    return tuple(s.copy() for s in _MEMO[key])


def memo_on(token) -> None:
    """Memoise supertrend / kst / klinger for one series (token); the locked signals() code is unchanged and calls
    the same functions, it only does not recompute an identical call. memo_off() restores the originals."""
    _MEMO.clear()
    _TOKEN[0] = token
    fg_fast.supertrend = _st_memo
    fg.kst = _kst_memo
    fg.klinger_oscillator = _kvo_memo


def memo_off() -> None:
    _MEMO.clear()
    _TOKEN[0] = None
    fg_fast.supertrend = _ORIG["st"]
    fg.kst = _ORIG["kst"]
    fg.klinger_oscillator = _ORIG["kvo"]


def st_direction(atr_len: int, mult: float):
    """The memoised supertrend direction of the current series (after signals were computed)."""
    for k, v in _MEMO.items():
        if k[0] == "st" and k[3] == int(atr_len) and k[4] == float(mult):
            return v[1].to_numpy(float)
    return None


def combo_signal(strat: str, c: int, df: pd.DataFrame, tf: str) -> np.ndarray:
    """int8 side array (+1 / -1 / 0) of combo c from the locked param_defs code."""
    mod = load_param_def(strat)
    lg, sh = mod.signals(df, tf, **overrides(strat, c))
    lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
    return np.where(lg, 1, np.where(sh, -1, 0)).astype(np.int8)


# ------------------------------------------------------------------ bars
def bars_path(coin: str, tf: str) -> str:
    return os.path.join(BARS_DIR, f"{coin}_{tf}.npz")


def load_bars(coin: str, tf: str) -> dict:
    z = np.load(bars_path(coin, tf))
    return {k: z[k] for k in z.files}


def frame(b: dict, tf: str, lo: int = 0, hi: int | None = None) -> pd.DataFrame:
    hi = len(b["ts"]) if hi is None else hi
    df = pd.DataFrame({"ts": pd.to_datetime(b["ts"][lo:hi], utc=True), "open": b["o"][lo:hi], "high": b["h"][lo:hi],
                       "low": b["l"][lo:hi], "close": b["c"][lo:hi], "volume": b["v"][lo:hi]})
    df.attrs["tf"] = tf
    return df


def ts_ns(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value)


def week_of(ts) -> np.ndarray:
    return ((np.asarray(ts, np.int64) - WEEK0) // NS_WEEK).astype(np.int32)


# ------------------------------------------------------------------ sizing (copy of precompute.sizer, k as argument)
def sizer(coin: str, k_stop: float = K_STOP):
    cache = {}

    def f(side, atr_frac):
        key = (side, float(f"{atr_frac:.4g}"))
        if key not in cache:
            raw = 100.0
            a = key[1] * raw
            fill = raw * (1 + side * S.slippage_frac)
            d = size_position(S, EQUITY_SIZER, side, fill, raw - side * k_stop * a, "normal", BR[coin], atr=a,
                              min_notional=5.0)
            cache[key] = (d.leverage, side * (fill - d.liq_price) / fill) if d.ok else (0, np.nan)
        return cache[key]
    return f


def lev_liq(coin: str, side: np.ndarray, atr_frac: np.ndarray, k_stop: float = K_STOP):
    sz = sizer(coin, k_stop)
    ll = np.array([sz(int(s_), float(x)) for s_, x in zip(side, atr_frac)], float).reshape(-1, 2)
    lev = ll[:, 0]
    feas = lev > 0
    return np.where(feas, lev, 20.0), np.where(feas, ll[:, 1], 10.0), feas


# ------------------------------------------------------------------ house exit scan (precompute.scan generalised)
def scan(b, e, side, lev, liq_frac, risk_dist, H, f_bar, fill=None, raw=None, ladder=True, fill_bar=False,
         entry_fee=None, liq_touch=False):
    """House exit on 15m bars b for entries in 15m bar e. Same arithmetic as precompute.scan when fill/raw are None,
    ladder=True, fill_bar=False, entry_fee=None (then raw = open[e], fill = raw*(1+side*slip), stop0 = raw -
    side*risk_dist, entry fee = taker).
    fill_bar=True (MAKER): the entry is a limit fill inside bar e at price `raw` (= fill): that bar's favourable
    excursion is not credited to the ladder and its open is not used for a gap exit (conservative).
    ladder=False: stop-only (STFLIP); the scan then reports the first stop touch.
    liq_touch=True (accounts, forced leverage): a bar trading through the liquidation price before (or, when the
    liquidation price is nearer than the stop, in the same bar as) the stop liquidates the position (ROE -1)."""
    rt, fee, slip = S.round_trip_cost, S.taker_fee, S.slippage_frac
    n = len(b["o"])
    m = len(e)
    off = np.arange(H)
    J = e[:, None] + off[None, :]
    valid = J < n
    Jc = np.minimum(J, n - 1)
    o, h, lo, c = b["o"][Jc], b["h"][Jc], b["l"][Jc], b["c"][Jc]
    if raw is None:
        raw = b["o"][e]
    if fill is None:
        fill = raw * (1 + side * slip)
    efee = fee if entry_fee is None else entry_fee
    stop0 = raw - side * risk_dist
    liq = fill * (1 - side * liq_frac)
    s = side[:, None]
    fund = f_bar * (off[None, :] + 1)
    if ladder:
        fav = np.where(s == 1, h, -lo)
        if fill_bar:
            fav = fav.copy()
            fav[:, 0] = side * fill
        best_px = s * np.maximum.accumulate(np.concatenate([(side * fill)[:, None], fav], axis=1), axis=1)[:, 1:]
        roe_best = lev[:, None] * (s * (best_px / fill[:, None] - 1) - rt - fund)
        first = LAD.first_lock + LAD.trigger_gap
        nstep = np.floor((roe_best - first) / LAD.step + 1e-9)
        lock_roe = np.where(roe_best >= first - 1e-12, LAD.first_lock + LAD.step * nstep, np.nan)
        lock_px = fill[:, None] * (1 + s * (lock_roe / lev[:, None] + rt + fund))
        lp = np.where(np.isnan(lock_px), -np.inf, s * lock_px)
        lock_cum = np.maximum.accumulate(np.concatenate([np.full((m, 1), -np.inf), lp], axis=1), axis=1)[:, :-1]
        stop_eff = np.maximum((side * stop0)[:, None], lock_cum)
    else:
        stop_eff = np.broadcast_to((side * stop0)[:, None], (m, H))
    adverse = np.where(s == 1, lo, -h)
    hit = (adverse <= stop_eff) & valid
    if liq_touch:
        hit_l = (adverse <= (side * liq)[:, None]) & valid
        # liquidation first: touched in an earlier bar, or in the same bar while nearer than the stop
        first_l = np.where(hit_l.any(1), hit_l.argmax(1), H)
        hit = hit | hit_l
    done = hit.any(axis=1)
    q = np.where(done, hit.argmax(axis=1), np.minimum(H, np.maximum(valid.sum(axis=1), 1)) - 1)
    r = np.arange(m)
    st = side * stop_eff[r, q]
    oq = o[r, q]
    gap = (side * oq) <= (side * st)
    if fill_bar:
        gap = gap & (q > 0)
    liq_gap = done & gap & ((side * oq) <= (side * liq))
    if liq_touch:
        liq_gap = liq_gap | (done & (first_l == q) & ((side * liq) >= (side * st) - 1e-12))
    exit_raw = np.where(done, np.where(gap, oq, st), c[r, q])
    exit_px = np.where(liq_gap, liq, exit_raw * (1 - side * slip))
    held = q + 1
    roe = lev * (side * (exit_px / fill - 1) - efee - fee * exit_px / fill - f_bar * held)
    roe = np.where(liq_gap, -1.0, np.maximum(roe, -1.0))
    is_lock = done & ~liq_gap & (side * st > side * stop0 + 1e-12)
    reason = np.where(~done, 3, np.where(liq_gap, 2, np.where(is_lock, 1, 0)))
    risk = np.abs(fill - stop0)
    R = roe * fill / (lev * risk)
    gross = side * (exit_raw - raw) / risk
    return dict(done=done, x=e + q, R=R, gross=gross, roe=roe, reason=reason, fill=fill, risk=risk)


def run_scan(b, e, side, lev, liq_frac, risk_dist, f_bar=F_BAR15, passes=(96, 768, 6144, 49152), **kw):
    """precompute.job's multi-pass driver: short horizon first, the unfinished ones again with a longer one.
    kw arrays (fill, raw) are per row and are subset with the rows."""
    m = len(e)
    res = {k: np.full(m, np.nan) for k in ("x", "R", "gross", "roe", "reason", "fill", "risk")}
    res["done"] = np.zeros(m, bool)
    todo = np.arange(m)
    nb = len(b["o"])
    arr_kw = {k: v for k, v in kw.items() if isinstance(v, np.ndarray)}
    oth_kw = {k: v for k, v in kw.items() if not isinstance(v, np.ndarray)}
    for H in passes:
        if not len(todo):
            break
        nxt = []
        step = max(16, 400_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            r = scan(b, e[sel], side[sel], lev[sel], liq_frac[sel], risk_dist[sel], H, f_bar,
                     **{k: v[sel] for k, v in arr_kw.items()}, **oth_kw)
            keep = r["done"] | (H == passes[-1]) | (e[sel] + H >= nb)
            for k in res:
                res[k][sel[keep]] = r[k][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    res["x"] = res["x"].astype(np.int64)
    return res


# ------------------------------------------------------------------ TPSL scan (fixed TP / stop, no ladder)
TPSL_TP = (1.0, 1.5, 2.0, 3.0)
TPSL_K = (1.5, 2.0, 3.0)
TPSL_CFG = tuple((tp, k) for k in TPSL_K for tp in TPSL_TP)    # 12 settings, index = ki*4 + ti


def tpsl_first_hits(b, e, side, raw, dist, tps, H):
    """First 15m offset (from e) where the stop (raw - side*dist) is touched and where each TP level
    (raw + side*tp*dist) is touched; H if neither within H bars. Also whether the stop bar opened beyond the stop."""
    n = len(b["o"])
    J = e[:, None] + np.arange(H)[None, :]
    valid = J < n
    Jc = np.minimum(J, n - 1)
    s = side[:, None]
    adverse = np.where(s == 1, b["l"][Jc], -b["h"][Jc])
    fav = np.where(s == 1, b["h"][Jc], -b["l"][Jc])
    stp = (side * (raw - side * dist))[:, None]
    hit_s = (adverse <= stp) & valid
    qs = np.where(hit_s.any(1), hit_s.argmax(1), H)
    qt = []
    for tp in tps:
        tpp = (side * (raw + side * tp * dist))[:, None]
        hit_t = (fav >= tpp) & valid
        qt.append(np.where(hit_t.any(1), hit_t.argmax(1), H))
    nvalid = valid.sum(1)
    return qs, np.array(qt), nvalid


def tpsl_outcomes(b, e, side, atr, lev, liq_frac, f_bar=F_BAR15, passes=(96, 768, 6144, 49152)):
    """Per row and per TPSL setting (12): net R, gross R (NaN when the trade does not close before the data end).
    TP fills at its price (no favourable-gap credit); a bar touching both = stop; a stop bar opening beyond the
    stop fills at the open; exit costs taker + slippage like every house exit; liquidation only through a gap
    beyond it (as scan). R in units of that setting's own stop distance (k x ATR)."""
    m = len(e)
    nb = len(b["o"])
    raw = b["o"][e]
    fill = raw * (1 + side * SLIP)
    BIG = 10**12
    R = np.full((len(TPSL_CFG), m), np.nan, np.float32)
    G = np.full((len(TPSL_CFG), m), np.nan, np.float32)
    for ki, k in enumerate(TPSL_K):
        dist = k * atr
        qs = np.full(m, BIG, np.int64)
        qt = np.full((len(TPSL_TP), m), BIG, np.int64)
        todo = np.arange(m)
        for H in passes:
            if not len(todo):
                break
            nxt = []
            step = max(16, 300_000 // H)
            for c0 in range(0, len(todo), step):
                sel = todo[c0:c0 + step]
                a_s, a_t, _nv = tpsl_first_hits(b, e[sel], side[sel], raw[sel], dist[sel], TPSL_TP, H)
                resolved = (a_s < H) | np.all(a_t < H, axis=0) | (H == passes[-1]) | (e[sel] + H >= nb)
                qs[sel] = np.where(a_s < H, a_s, BIG)
                qt[:, sel] = np.where(a_t < H, a_t, BIG)
                nxt.append(sel[~resolved])
            todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
        stop_px = raw - side * dist
        risk = np.abs(fill - stop_px)
        liq = fill * (1 - side * liq_frac)
        for ti, tp in enumerate(TPSL_TP):
            j = ki * len(TPSL_TP) + ti
            is_tp = qt[ti] < qs
            stop_hit = ~is_tp & (qs < BIG)
            done = is_tp | stop_hit
            q = np.where(is_tp, qt[ti], np.where(stop_hit, qs, 0))
            x = np.minimum(e + q, nb - 1)
            oq = b["o"][x]
            gap = stop_hit & ((side * oq) <= (side * stop_px))
            tp_px = raw + side * tp * dist
            exit_raw = np.where(is_tp, tp_px, np.where(gap, oq, stop_px))
            liq_gap = gap & ((side * oq) <= (side * liq))
            exit_px = np.where(liq_gap, liq, exit_raw * (1 - side * SLIP))
            held = q + 1
            roe = lev * (side * (exit_px / fill - 1) - TAKER * (1 + exit_px / fill) - f_bar * held)
            roe = np.where(liq_gap, -1.0, np.maximum(roe, -1.0))
            R[j] = np.where(done, roe * fill / (lev * risk), np.nan)
            G[j] = np.where(done, side * (exit_raw - raw) / risk, np.nan)
    return R, G


# ------------------------------------------------------------------ statistics helpers
def boot_ci(week_n: np.ndarray, week_s: np.ndarray, B: int = 2000, seed: int = 0):
    """Week-block bootstrap 95% interval of the pooled mean (sum s / sum n): the W weeks with >= 1 trade are
    resampled W times with replacement."""
    ok = week_n > 0
    n, s = week_n[ok].astype(float), week_s[ok].astype(float)
    W = len(n)
    if W < 2:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    out = np.empty(B)
    for c0 in range(0, B, 250):
        k = min(250, B - c0)
        idx = rng.integers(0, W, size=(k, W))
        out[c0:c0 + k] = s[idx].sum(1) / n[idx].sum(1)
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def max_dd(r: np.ndarray) -> float:
    """Largest peak-to-trough fall of the cumulative sum (R units), in the given order."""
    if len(r) == 0:
        return 0.0
    cs = np.concatenate([[0.0], np.cumsum(r)])
    return float(np.max(np.maximum.accumulate(cs) - cs))


# ------------------------------------------------------------------ signal list storage (delta-encoded)
def encode_codes(codes: np.ndarray, offs: np.ndarray):
    """Concatenated per-combo sorted codes -> (deltas uint16/uint32 with 0 at each segment start, firsts int64)."""
    c = codes.astype(np.int64)
    d = np.zeros(len(c), np.int64)
    if len(c):
        d[1:] = np.diff(c)
    st = offs[:-1]
    nonempty = offs[1:] > st
    firsts = np.zeros(len(st), np.int64)
    firsts[nonempty] = c[st[nonempty]]
    d[st[nonempty]] = 0
    dt = np.uint16 if (len(d) == 0 or d.max() < 65536) else np.uint32
    return d.astype(dt), firsts


def decode_codes(deltas: np.ndarray, firsts: np.ndarray, offs: np.ndarray) -> np.ndarray:
    cs = np.cumsum(deltas.astype(np.int64))
    seg_len = np.diff(offs)
    st = offs[:-1]
    base = np.zeros(len(st), np.int64)
    ne = seg_len > 0
    base[ne] = firsts[ne] - cs[st[ne]]
    return cs + np.repeat(base, seg_len)


def load_signals(path: str, strat: str):
    """(codes int64, offs) of one strategy from a stage-2 signal file."""
    z = np.load(path)
    offs = z[strat + "__offs"]
    return decode_codes(z[strat + "__d"], z[strat + "__f"], offs), offs


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def save_npz(path: str, **arrs) -> None:
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **arrs)
    os.replace(tmp, path)


def save_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    os.replace(tmp, path)
