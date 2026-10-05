"""Instagram reel "5분봉 단타, 선 두 개로 끝내는 법" (research/reel5m/PREREG_REEL5M.md): H1 + 40-config grid.

    python3 research/reel5m/lib_reel5m.py selftest
    python3 research/reel5m/lib_reel5m.py count
    python3 research/reel5m/lib_reel5m.py run --bars <BINANCE_DIR>/bars [--pre data/pre2021] [--out research/reel5m/out]
                                              [--procs 4] [--tfs 5m,15m,30m,1h,4h] [--n-boot 2000]
    python3 research/reel5m/lib_reel5m.py synth-bars <dir>      # SYNTHETIC bar files, only to time the pipeline

Rules (PREREG section 5): Bollinger(20, 2, population std) and a 200 MA on close. Filter on = middle band > MA
(long). A bar closing below the lower band (or, in the WICK variant, with its low below it) arms a setup; the first
later green bar that closes inside the band is the signal, while the filter stays on, at most 12 bars after the last
breach bar. Entry next bar open; stop = lowest low from the first breach bar through the signal bar minus 0.05 ATR14;
target = resting limit at the previous closed bar's upper band; max hold 96 bars. Short = mirror image.
H1-only sensitivities (reported, never judged): entry at the signal close, the live-band target, a 0.3 ATR stop
buffer, and three cost stresses (PREREG section 9).

The exit is not expressible in the locked engine (its stop/target are ATR multiples of the entry), so
``exit_trade`` re-implements the engine's ``_simulate_one`` FIXED branch with a per-bar target and a given stop,
using the engine's own CostCfg (fee, slippage, funding, max hold) from ``sweep_lib._cost``. The tests prove it equals
the engine exactly for a fixed ATR stop/target. Gauntlet: research/library/lib.py ``config_rows`` / ``select``,
imported, not copied. Nothing here reads real data unless ``run`` is called, and ``run`` refuses to start when
PREREG_REEL5M.md does not match PREREG_REEL5M.sha256.
"""

from __future__ import annotations

import bisect
import dataclasses
import hashlib
import importlib.util
import json
import os
import sys
import time
import warnings
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")

# ------------------------------------------------------------------ fixed parameters (PREREG sections 5 and 7)
TFS = ("5m", "15m", "30m", "1h", "4h")
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
BB_LEN, BB_K = 20, 2.0            # Bollinger(20, 2), population std (ddof=0) as TradingView ta.bb
MA_LEN = 200
MA_TYPES = ("SMA200", "EMA200")
BREACHES = ("CLOSE", "WICK")      # CLOSE: close outside the band; WICK: low below lower (short: high above upper)
SIDES = ("LONG", "BOTH")          # BOTH = long + mirrored short
WAIT = 12                         # signal within 12 bars after the (last) breach bar
STOP_BUF_ATR = 0.05               # stop = swing extreme -/+ 0.05 x ATR14 of the signal bar
ATR_LEN = 14
MAX_HOLD = 96                     # bars, entry bar included (engine convention)
EXIT_NAME = "SWING_BAND"
LEVS = (20, 30, 40, 50)           # owners' live leverage range
MMR = 0.005                       # liquidation distance = 1/L - 0.5% (engine leverage_layer, library OWN_LIQ)
# live-band touch: during bar j the upper band moves with the price; the price p at which p == its own live upper band
# is mu19 + LIVE_K * sd19 of the 19 closes before j (population sd), known at the bar's open
LIVE_K = BB_K * float(np.sqrt(BB_LEN / (BB_LEN - 1 - BB_K ** 2)))     # 2 * sqrt(20/15) = 2.3094
STOP_BUF_SENS = 0.3               # sensitivity only: the gap drawn under the swing low in frames 10 and 12
SLIP_SENS = 0.0005                # sensitivity only: 0.05% per market fill (entry, stop, time exit)
TP_THROUGH_SENS = 0.0002          # sensitivity only: the target fills only when price trades 0.02% through it
SEED = 20261005
BH_Q = 0.10
H1_ALPHA = 0.05
PERIODS = {  # split label -> (start, end) UTC, signal bar times; 'pre' lives in the data/pre2021 series
    "is": ("2021-08-01", "2024-07-01"),
    "oos": ("2024-07-01", "2026-09-30"),
    "pre": ("2020-01-01", "2021-08-01"),
}
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
PREREG = os.path.join(HERE, "PREREG_REEL5M.md")
PREREG_SHA = os.path.join(HERE, "PREREG_REEL5M.sha256")


def entry_name(ma: str, breach: str, side: str) -> str:
    return f"BB_{ma}_{breach}_{side}"


def parse_entry(name: str) -> tuple[str, str, str]:
    _bb, ma, breach, side = name.split("_")
    return ma, breach, side


H1 = ("5m", entry_name("SMA200", "CLOSE", "LONG"), EXIT_NAME)
ENTRY_NAMES = [entry_name(m, b, s) for m in MA_TYPES for b in BREACHES for s in SIDES]


def config_list() -> list[tuple[str, str, str]]:
    """Every (timeframe, entry, exit): the N = 40 configurations of the PREREG (H1 is one of them)."""
    return [(tf, e, EXIT_NAME) for tf in TFS for e in ENTRY_NAMES]


# Sensitivities (PREREG section 9): reported next to the test, never used for any verdict. "close" runs for every
# configuration; the others run for H1 only.
SENS = {
    "close": dict(entry_mode="close"),                    # the reel's "그 종가에 매수"
    "live_target": dict(target="live"),                   # target = the live band touch level (LIVE_K)
    "buf03": dict(stop_buf=STOP_BUF_SENS),                # stop 0.3 ATR under the swing low, as drawn
    "cost_a": dict(slip=SLIP_SENS),                       # slippage 0.05% per market fill
    "cost_b": dict(tp_through=TP_THROUGH_SENS),           # target must trade 0.02% through
    "cost_c": dict(slip=SLIP_SENS, tp_through=TP_THROUGH_SENS),
}


# ------------------------------------------------------------------ environment (library lib, locked engine)
_ENV: dict = {}


def env() -> dict:
    if not _ENV:
        sys.path.insert(0, os.path.join(ROOT, "research", "search"))
        name = "research_library_lib"
        if name in sys.modules:
            lib = sys.modules[name]
        else:
            spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "research", "library", "lib.py"))
            lib = importlib.util.module_from_spec(spec)
            sys.modules[name] = lib
            spec.loader.exec_module(lib)
        L = lib.SR.lib()                   # verifies the locked code hashes, puts the vendor dir on sys.path
        import engine as ENG               # the locked engine module (third_party/sweep/harness/vendor/engine.py)
        import fg_indicators as fg
        import pine_indicators as pi
        _ENV.update(lib=lib, SR=lib.SR, L=L, ENG=ENG, fg=fg, pi=pi)
    return _ENV


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_prereg(md: str | None = None, sha_file: str | None = None) -> str:
    """Refuse (SystemExit) unless the PREREG matches its recorded sha256. Returns the hash."""
    md, sha_file = md or PREREG, sha_file or PREREG_SHA
    if not os.path.exists(sha_file) or not os.path.exists(md):
        raise SystemExit(f"refusing to run: {os.path.basename(md)} or {os.path.basename(sha_file)} is missing")
    with open(sha_file) as fh:
        parts = fh.read().split()
    if len(parts) != 2 or parts[1] != os.path.basename(md):
        raise SystemExit(f"refusing to run: {sha_file} is not '<sha256>  {os.path.basename(md)}'")
    got = _sha256(md)
    if got != parts[0]:
        raise SystemExit(f"refusing to run: {os.path.basename(md)} sha256 {got} != recorded {parts[0]}. "
                         "A changed PREREG is a new pre-registration.")
    return got


# ------------------------------------------------------------------ indicators
def indicators(df: pd.DataFrame) -> dict:
    """Arrays for one bar series: o h l c, Bollinger(20, 2, ddof=0) upper/mid/lower, SMA200, EMA200, ATR14, and the
    live-band touch levels up_live/dn_live. Every value at bar t uses bars <= t only; up_live[t]/dn_live[t] use the
    closes of bars t-19..t-1 only (the level is known when bar t opens)."""
    E = env()
    fg, pi = E["fg"], E["pi"]
    c = df["close"].astype(float)
    up, mid, dn, _bw = fg.bollinger_bands(c, BB_LEN, BB_K)
    ca = c.to_numpy()
    r19 = pd.Series(ca).rolling(BB_LEN - 1)
    mu19, sd19 = r19.mean().to_numpy(), r19.std(ddof=0).to_numpy()
    return {"o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float), "l": df["low"].to_numpy(float), "c": ca,
            "upper": up.to_numpy(float), "mid": mid.to_numpy(float), "lower": dn.to_numpy(float),
            "SMA200": pi.pine_sma(ca, MA_LEN), "EMA200": pi.pine_ema(ca, MA_LEN),
            "atr": fg.atr(df, ATR_LEN).to_numpy(float),
            "up_live": np.r_[np.nan, (mu19 + LIVE_K * sd19)[:-1]], "dn_live": np.r_[np.nan, (mu19 - LIVE_K * sd19)[:-1]]}


# ------------------------------------------------------------------ setup state machine + exit simulator
class Prep:
    """Per (series, MA type, breach, sides) flag arrays, as numpy (for slicing) and lists (for the scan loop)."""

    def __init__(self, ind: dict, ma: str, breach: str, sides: str):
        assert ma in MA_TYPES and breach in BREACHES and sides in SIDES, (ma, breach, sides)
        o, h, l, c = ind["o"], ind["h"], ind["l"], ind["c"]
        up, mid, dn, mav = ind["upper"], ind["mid"], ind["lower"], ind[ma]
        with np.errstate(invalid="ignore"):
            filt_l = mid > mav
            filt_s = (mid < mav) if sides == "BOTH" else np.zeros(len(c), bool)
            br_l = (c < dn) if breach == "CLOSE" else (l < dn)
            br_s = (c > up) if breach == "CLOSE" else (h > up)
            inside = (c > dn) & (c < up)
            sig_l = (c > o) & inside & filt_l          # green candle closing inside the band, filter on
            sig_s = (c < o) & inside & filt_s          # red candle closing inside the band (short filter on)
        self.ma, self.breach, self.sides = ma, breach, sides
        self.o, self.h, self.l, self.c, self.atr = o, h, l, c, ind["atr"]
        self.up, self.dn = up, dn
        self.up_prev = np.r_[np.nan, up[:-1]]           # long target active during bar j = upper band of bar j-1
        self.dn_prev = np.r_[np.nan, dn[:-1]]
        self.up_live = ind.get("up_live")               # sensitivity: live-band touch level during bar j
        self.dn_live = ind.get("dn_live")
        self.arm_l, self.arm_s = br_l & filt_l, br_s & filt_s
        self.L = {k: v.tolist() for k, v in (("filt_l", filt_l), ("filt_s", filt_s), ("br_l", br_l), ("br_s", br_s),
                                               ("sig_l", sig_l), ("sig_s", sig_s), ("h", h), ("l", l))}


def exit_trade(side: int, e: int, entry: float, stop: float, tgt, o, h, l, c, cost, tp_through: float = 0.0) -> dict:
    """One trade entered at ``entry`` with bar ``e`` as the first bar at risk. ``stop``: fixed stop-market level.
    ``tgt``: scalar target or an array giving the resting limit level active during each bar (NaN = none).
    Same conventions and arithmetic as the locked engine's ``_simulate_one`` (FIXED): stop first when both are
    touched in one bar, stop fills at min(open, stop) less slippage, target at max(open, target) without slippage,
    time exit at the close of bar e+max_hold-1 less slippage, fee 2 x taker, funding pro rata.
    ``tp_through`` (sensitivity only, 0 = engine): the target counts as hit only when price trades that fraction
    through it; the fill is still max(open, target).
    Extra outputs (not in the engine): ``mae_held`` = adverse excursion while the position was actually open (on a
    stop exit the exit bar counts only down to the stop fill), used for the liquidation count; ``gross_raw`` = the
    price move before fee, slippage and funding (``gross`` keeps the engine meaning: after slippage)."""
    n = len(o)
    last = min(n - 1, e + cost.max_hold - 1)
    oo, hh, ll, cc = o[e:last + 1], h[e:last + 1], l[e:last + 1], c[e:last + 1]
    m = len(oo)
    adverse = ll if side > 0 else hh
    favour = hh if side > 0 else ll
    hit_sl = (adverse <= stop) if side > 0 else (adverse >= stop)
    tg = np.full(m, float(tgt)) if np.ndim(tgt) == 0 else np.asarray(tgt, float)[e:last + 1]
    thr = tg if tp_through == 0.0 else tg * (1.0 + side * tp_through)
    with np.errstate(invalid="ignore"):
        hit_tp = (favour >= thr) if side > 0 else (favour <= thr)
    any_hit = hit_sl | hit_tp
    if any_hit.any():
        j = int(np.argmax(any_hit))
        if hit_sl[j]:
            reason = "SL"
            fill = min(oo[j], stop) if side > 0 else max(oo[j], stop)
            exit_px = fill * (1.0 - side * cost.slip_side)
            raw_exit = fill
        else:
            reason = "TP"
            exit_px = max(oo[j], tg[j]) if side > 0 else min(oo[j], tg[j])
            raw_exit = exit_px
    else:
        j = m - 1
        reason = "TIME" if last < n - 1 else "EOD"
        exit_px = cc[j] * (1.0 - side * cost.slip_side)
        raw_exit = cc[j]
    hold = j + 1
    seg_adv, seg_fav = adverse[: j + 1], favour[: j + 1]
    mae = side * (seg_adv.min() / entry - 1.0) if side > 0 else side * (seg_adv.max() / entry - 1.0)
    mfe = side * (seg_fav.max() / entry - 1.0) if side > 0 else side * (seg_fav.min() / entry - 1.0)
    # held: on a stop exit the position is closed at the stop fill, the rest of that bar's wick is not carried
    held = np.r_[adverse[:j], raw_exit] if reason == "SL" else seg_adv
    mae_held = side * (held.min() / entry - 1.0) if side > 0 else side * (held.max() / entry - 1.0)
    gross = side * (exit_px / entry - 1.0)
    gross_raw = side * (raw_exit / (entry / (1.0 + side * cost.slip_side)) - 1.0)
    fee = 2.0 * cost.fee_side
    funding = cost.funding_8h * (hold * cost.bar_minutes / 480.0)
    net = gross - fee - funding
    return dict(side=side, entry_idx=e, exit_idx=e + j, entry_px=entry, exit_px=exit_px, gross=gross, fee=fee,
                funding=funding, net=net, mae=mae, mfe=mfe, reason=reason, hold=hold,
                sl_dist=side * (entry - stop) / entry, stop_px=stop, mae_held=mae_held, gross_raw=gross_raw)


def simulate(P: Prep, cost, lo: int, hi: int, entry_mode: str = "open", trade: bool = True,
             stop_buf: float = STOP_BUF_ATR, target: str = "prev", tp_through: float = 0.0):
    """Walk one series from bar ``lo`` (flat, nothing armed). Signal bars must lie in [lo, hi).

    trade=True : one position at a time; bars up to and including a position's exit bar neither arm nor signal.
    trade=False: no positions; every signal is recorded and the machine is free again from the bar after it
                 (used for the look-ahead test of the signal logic alone).
    stop_buf / target / tp_through: the test uses the defaults (0.05 ATR, previous closed bar's band, touch fills);
    other values are the PREREG section 9 sensitivities. target="live": the live-band touch level (up_live/dn_live).
    Returns (trades, signals, skips)."""
    assert entry_mode in ("open", "close") and target in ("prev", "live")
    if target == "prev":
        tgt_l, tgt_s = P.up_prev, P.dn_prev
    else:
        tgt_l, tgt_s = P.up_live, P.dn_live
        assert tgt_l is not None and tgt_s is not None, "indicators without up_live/dn_live"
    o, c, atr = P.o, P.c, P.atr
    n = len(c)
    hi = min(hi, n - 1)                                  # the entry bar s+1 must exist
    if hi <= lo:
        return [], [], {"stop": 0, "target": 0, "atr": 0}
    arm = P.arm_l | P.arm_s
    cand = (np.flatnonzero(arm[lo:hi]) + lo).tolist()
    arm_l = P.arm_l
    Lx = P.L
    slip = cost.slip_side
    trades, sigs = [], []
    skips = {"stop": 0, "target": 0, "atr": 0}
    free, k = lo, 0
    while True:
        k = bisect.bisect_left(cand, free, k)
        if k >= len(cand):
            break
        b = cand[k]
        side = 1 if arm_l[b] else -1
        if side > 0:
            fl, sg, br, xs = Lx["filt_l"], Lx["sig_l"], Lx["br_l"], Lx["l"]
        else:
            fl, sg, br, xs = Lx["filt_s"], Lx["sig_s"], Lx["br_s"], Lx["h"]
        ext = xs[b]
        b_last, s, nxt, t = b, -1, -1, b + 1
        while t < hi:
            if not fl[t]:                                # filter off: setup cancelled; bar t may arm the other side
                nxt = t
                break
            x = xs[t]
            if (x < ext) if side > 0 else (x > ext):
                ext = x
            if sg[t]:
                s = t
                break
            if br[t]:                                    # new breach: stays armed, clock restarts, extreme kept
                b_last = t
            elif t - b_last >= WAIT:                     # 12 bars after the last breach without a signal
                nxt = t + 1
                break
            t += 1
        if s < 0:
            if nxt < 0:
                break                                    # reached the end of the window while armed
            free = nxt
            continue
        a = atr[s]
        stop = ext - side * stop_buf * a
        tgt = tgt_l if side > 0 else tgt_s
        tgt0 = tgt[s + 1]                                # target resting during the entry bar (prev: band of bar s)
        sigs.append(dict(signal_idx=s, side=side, arm_idx=b, last_breach_idx=b_last, extreme=ext, stop_px=stop,
                         target0=tgt0))
        if not trade:
            free = s + 1
            continue
        if not np.isfinite(a) or a <= 0:
            skips["atr"] += 1
            free = s + 1
            continue
        e = s + 1
        entry = (o[e] if entry_mode == "open" else c[s]) * (1.0 + side * slip)
        if side * (entry - stop) <= 0:                   # stop at or beyond the entry: skip, flat again
            skips["stop"] += 1
            free = s + 1
            continue
        if not side * (tgt0 - entry) > 0:                # entry already at/through the first target: skip
            skips["target"] += 1
            free = s + 1
            continue
        tr = exit_trade(side, e, entry, stop, tgt, P.o, P.h, P.l, P.c, cost, tp_through)
        tr.update(signal_idx=s, arm_idx=b, last_breach_idx=b_last)
        trades.append(tr)
        free = tr["exit_idx"] + 1
    return trades, sigs, skips


def run_fixed(o, h, l, c, atr, long_sig, short_sig, sl_atr: float, tp_atr: float, cost, start_idx: int = 0,
              end_idx: int | None = None) -> pd.DataFrame:
    """Engine-parity bridge (tests only): the locked ``run_backtest`` loop with FIXED ATR stop/target, but every
    trade simulated by ``exit_trade``. Must equal ``run_backtest`` exactly."""
    n = len(o)
    end_idx = n if end_idx is None else end_idx
    start_idx = max(start_idx, cost.warmup)
    sig_idx = np.where((long_sig | short_sig)[start_idx:end_idx])[0] + start_idx
    out, next_free = [], -1
    for i in sig_idx:
        if i <= next_free:
            continue
        if i + 1 >= n:
            break
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        side = 1 if long_sig[i] else -1
        e = int(i) + 1
        entry = o[e] * (1.0 + side * cost.slip_side)
        sl_dist = sl_atr * float(atr[i]) / entry
        stop = entry * (1.0 - side * sl_dist)
        tp = entry * (1.0 + side * tp_atr * float(atr[i]) / entry)
        t = exit_trade(side, e, entry, stop, tp, o, h, l, c, cost)
        t["sl_dist"] = sl_dist
        t["signal_idx"] = int(i)
        out.append(t)
        next_free = t["exit_idx"]
    return pd.DataFrame(out)


def liq_stats(mae_held: np.ndarray, sl_dist: np.ndarray, prefix: str = "", mae_full: np.ndarray | None = None) -> dict:
    """Per leverage L: liquidation distance 1/L - 0.5% (last price, first order of margin.py's formula).
    liq{L}_n: trades whose adverse excursion while the position was open (``mae_held``: a stop exit counts only down
    to the stop fill) reached it, i.e. liquidated before the stop / target / time exit. slbeyond{L}_pct: stop at or
    beyond the liquidation distance. maereach{L}_n (when ``mae_full`` is given): the engine leverage_layer convention,
    the whole exit bar included (overstates liquidations on stop exits; reported for comparison only)."""
    mae, sl = np.asarray(mae_held, float), np.asarray(sl_dist, float)
    n = len(mae)
    d = {f"{prefix}sl_med_pct": 100 * float(np.median(sl)) if n else np.nan,
         f"{prefix}sl_p90_pct": 100 * float(np.quantile(sl, 0.9)) if n else np.nan}
    for lev in LEVS:
        liq = 1.0 / lev - MMR
        nl = int((mae <= -liq).sum())
        d[f"{prefix}liq{lev}_n"] = nl
        d[f"{prefix}liq{lev}_pct"] = 100 * nl / n if n else np.nan
        d[f"{prefix}slbeyond{lev}_pct"] = 100 * float((sl >= liq).mean()) if n else np.nan
        if mae_full is not None:
            d[f"{prefix}maereach{lev}_n"] = int((np.asarray(mae_full, float) <= -liq).sum())
    return d


# ------------------------------------------------------------------ data
def load_series(bars_dir: str, pre_dir: str, tf: str, coin: str, manifest: dict | None = None):
    """(main series 2021-01..2026-09-29, pre series 2020-01..2021-08-10). Binance USDT-M futures bars both.
    Same as research/deepseek200/lib_c.py: pre 5m/15m/1h/4h native, pre 30m = 15m resampled."""
    E = env()
    L, lib = E["L"], E["lib"]
    stem = coin.lower()
    p = os.path.join(bars_dir, f"{stem}-{tf}.csv.gz")
    main = L.read_ohlcv(p)
    main = main[main["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
    main.attrs["tf"] = tf
    if manifest is not None:
        manifest[os.path.basename(p)] = _sha256(p)
    src = "15m" if tf == "30m" else tf
    pp = os.path.join(pre_dir, f"{stem}-{src}.csv.gz")
    pre = pd.read_csv(pp)
    pre["ts"] = pd.to_datetime(pre["ts"], utc=True)
    pre = pre.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    pre = pre[pre["ts"] < lib.PRE[1] + pd.Timedelta(days=10)].reset_index(drop=True)
    if tf == "30m":
        pre = L.resample_ohlcv(pre, "30m")
    pre.attrs["tf"] = tf
    if manifest is not None:
        manifest["pre2021/" + os.path.basename(pp)] = _sha256(pp)
    return main, pre


def window_idx(L, df: pd.DataFrame, tf: str, start: str, end: str) -> tuple[int, int]:
    """Signal-bar positions [lo, hi): bar time >= start, past the warm-up, and the 96-bar hold ends before `end`."""
    ts = L._utc_ns(df["ts"])
    lo = max(int(np.searchsorted(ts, np.datetime64(pd.Timestamp(start).tz_localize(None), "ns"))), L.warmup_bars(tf))
    hi = int(np.searchsorted(ts, np.datetime64(pd.Timestamp(end).tz_localize(None), "ns"))) - (MAX_HOLD + 1)
    return lo, max(lo, hi)


def _frame(trades: list, ts: np.ndarray, coin: str, entry: str, split: str, tf: str, mode: str) -> pd.DataFrame:
    t = pd.DataFrame(trades)
    sl = t["sl_dist"].to_numpy(np.float64)
    return pd.DataFrame({
        "net": t["net"].to_numpy(np.float64), "gross": t["gross"].to_numpy(np.float64),
        "gross_raw": t["gross_raw"].to_numpy(np.float64),
        "mae": t["mae"].to_numpy(np.float64), "mae_held": t["mae_held"].to_numpy(np.float64),
        "mfe": t["mfe"].to_numpy(np.float32), "sl_dist": sl,
        "r": (t["gross_raw"].to_numpy(np.float64) / sl).astype(np.float32),
        "r_net": (t["net"].to_numpy(np.float64) / sl).astype(np.float32),
        "hold": t["hold"].to_numpy(np.int16), "side": t["side"].to_numpy(np.int8), "reason": t["reason"].to_numpy(),
        "entry_px": t["entry_px"].to_numpy(np.float64), "exit_px": t["exit_px"].to_numpy(np.float64),
        "stop_px": t["stop_px"].to_numpy(np.float64),
        "signal_ts": ts[t["signal_idx"].to_numpy(int)], "arm_ts": ts[t["arm_idx"].to_numpy(int)],
        "entry_ts": ts[t["entry_idx"].to_numpy(int)], "exit_ts": ts[t["exit_idx"].to_numpy(int)],
        "symbol": coin, "entry": entry, "exit": EXIT_NAME, "split": split, "tf": tf, "mode": mode})


def simulate_sens(P: Prep, cost, lo: int, hi: int, entry_mode: str = "open", target: str = "prev",
                  stop_buf: float = STOP_BUF_ATR, slip: float | None = None, tp_through: float = 0.0):
    """One SENS variant: simulate() with the variant's entry, target, stop buffer and cost stress."""
    c = cost if slip is None else dataclasses.replace(cost, slip_side=slip)
    return simulate(P, c, lo, hi, entry_mode, True, stop_buf=stop_buf, target=target, tp_through=tp_through)


def run_series(df: pd.DataFrame, tf: str, coin: str, splits: list[str], entries: list[str] | None = None):
    """Every entry config on one series over the listed splits: entry at next open (the test), and the SENS
    variants (sensitivity only: the signal-close entry for every config, the rest for H1 only; the frame's
    ``mode`` column names the variant). Returns (trades_open, trades_sens, skip_rows)."""
    E = env()
    L = E["L"]
    df.attrs["tf"] = tf
    ind = indicators(df)
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy()
    cost = L._cost(tf, MAX_HOLD)
    wins = {s: window_idx(L, df, tf, *PERIODS[s]) for s in splits}
    parts, sens, skips = [], [], []
    for name in (entries or ENTRY_NAMES):
        ma, br, sd = parse_entry(name)
        P = Prep(ind, ma, br, sd)
        variants = SENS if (tf, name) == H1[:2] else {"close": SENS["close"]}
        for s, (lo, hi) in wins.items():
            if hi <= lo:
                continue
            tr, sg, sk = simulate(P, cost, lo, hi, "open")
            skips.append({"tf": tf, "entry": name, "exit": EXIT_NAME, "split": s, "symbol": coin, "signals": len(sg),
                          "skip_stop": sk["stop"], "skip_target": sk["target"], "skip_atr": sk["atr"]})
            if tr:
                parts.append(_frame(tr, ts, coin, name, s, tf, "open"))
            for label, kw in variants.items():
                tr, _sg, _sk = simulate_sens(P, cost, lo, hi, **kw)
                if tr:
                    sens.append(_frame(tr, ts, coin, name, s, tf, label))
    cat = lambda x: pd.concat(x, ignore_index=True) if x else pd.DataFrame()  # noqa: E731
    return cat(parts), cat(sens), skips


def _task(args):
    bars_dir, pre_dir, tf, coin = args
    man: dict = {}
    main, pre = load_series(bars_dir, pre_dir, tf, coin, man)
    a = run_series(main, tf, coin, ["is", "oos"])
    b = run_series(pre, tf, coin, ["pre"])
    return (pd.concat([a[0], b[0]], ignore_index=True), pd.concat([a[1], b[1]], ignore_index=True), a[2] + b[2],
            man, (tf, coin, len(main), len(pre)))


# ------------------------------------------------------------------ statistics and gauntlet
def week_index(entry_ts) -> np.ndarray:
    days = np.asarray(entry_ts, "datetime64[ns]").astype("datetime64[D]").astype(np.int64)
    return (days + 3) // 7                      # Monday-based week number (1970-01-01 was a Thursday)


def _seed(tf: str, e: str, x: str, tag: str) -> int:
    return int(hashlib.sha256(f"{SEED}|{tf}|{e}|{x}|{tag}".encode()).hexdigest()[:8], 16)


def _p12(SR, g: pd.DataFrame) -> float:
    if len(g) < 20:
        return 1.0
    day = pd.to_datetime(g["entry_ts"]).dt.floor("D").to_numpy()
    return SR.mean_test(g["net"].to_numpy(), day)[1]


def extra_rows(tt: pd.DataFrame, sens: pd.DataFrame, skips: list, n_boot: int) -> list[dict]:
    """Per configuration: library gauntlet columns (lib.config_rows) + p12 (1st+2nd period, day-clustered), week-block
    bootstrap p, long/short, gross/cost, R, hold, exit reasons, liquidation counts, skips, close-entry sensitivity."""
    E = env()
    lib, SR = E["lib"], E["SR"]
    from paperbot.agents.newlab import boot_mean_p
    tt = tt.copy()
    tt["symbol"] = tt["symbol"].astype(str)         # unused categories break lib.coin_mdd
    rows = lib.config_rows(tt)
    key = {(r["tf"], r["entry"], r["exit"]): r for r in rows}
    for (tf, e, x), g in tt.groupby(["tf", "entry", "exit"], observed=True):
        r = key[(tf, e, x)]
        g12 = g[g["split"].isin(["is", "oos"])]
        net12 = g12["net"].to_numpy()
        r["p12"] = _p12(SR, g12)
        r["n12"] = len(g12)
        r["mean12_pct"] = 100 * net12.mean() if len(net12) else np.nan
        r["boot_p12"] = boot_mean_p(week_index(g12["entry_ts"].to_numpy()), net12, n_boot, _seed(tf, e, x, "12")) if len(net12) else 1.0
        gp = g[g["split"] == "pre"]
        r["boot_p3"] = boot_mean_p(week_index(gp["entry_ts"].to_numpy()), gp["net"].to_numpy(), n_boot, _seed(tf, e, x, "3")) if len(gp) else 1.0
        for pre, sel in (("is_", g["split"] == "is"), ("cf_", g["split"] == "oos"), ("pre_", g["split"] == "pre")):
            gg = g[sel]
            r[f"{pre}long_n"] = int((gg["side"] > 0).sum())
            r[f"{pre}short_n"] = int((gg["side"] < 0).sum())
            r[f"{pre}long_mean_pct"] = 100 * gg.loc[gg["side"] > 0, "net"].mean()
            r[f"{pre}short_mean_pct"] = 100 * gg.loc[gg["side"] < 0, "net"].mean()
            r[f"{pre}gross_mean_pct"] = 100 * gg["gross_raw"].mean()             # before fee, slippage, funding
            r[f"{pre}cost_mean_pct"] = 100 * (gg["gross_raw"] - gg["net"]).mean()  # fee + slippage + funding
            r[f"{pre}hold_mean"] = gg["hold"].astype(float).mean()
            r[f"{pre}r_mean"] = gg["r"].astype(float).mean()
            r[f"{pre}r_net_mean"] = gg["r_net"].astype(float).mean()
            for why in ("TP", "SL", "TIME"):
                r[f"{pre}{why.lower()}_pct"] = 100 * float((gg["reason"] == why).mean()) if len(gg) else np.nan
            r.update(liq_stats(gg["mae_held"].to_numpy(), gg["sl_dist"].to_numpy(), pre, gg["mae"].to_numpy()))
        r.update(liq_stats(g["mae_held"].to_numpy(), g["sl_dist"].to_numpy(), "all_", g["mae"].to_numpy()))
    sens = sens[sens["mode"] == "close"] if len(sens) else sens
    if len(sens):
        for (tf, e, x), g in sens.groupby(["tf", "entry", "exit"], observed=True):
            if (tf, e, x) not in key:
                continue
            r = key[(tf, e, x)]
            g12 = g[g["split"].isin(["is", "oos"])]
            r["sens_close_n12"] = len(g12)
            r["sens_close_mean12_pct"] = 100 * g12["net"].mean()
            r["sens_close_p12"] = _p12(SR, g12)
            r["sens_close_pre_mean_pct"] = 100 * g.loc[g["split"] == "pre", "net"].mean()
    if skips:
        sk = pd.DataFrame(skips).groupby(["tf", "entry", "exit"])[["signals", "skip_stop", "skip_target", "skip_atr"]].sum()
        for (tf, e, x), s in sk.iterrows():
            if (tf, e, x) in key:
                key[(tf, e, x)].update({k: int(v) for k, v in s.items()})
    return rows


def finish(rows: list[dict]) -> pd.DataFrame:
    """Join to the full configuration list (N = 40 rows), run the library stages, BH over all N, the H1 rule."""
    E = env()
    lib, SR = E["lib"], E["SR"]
    t = pd.DataFrame(rows)
    full = pd.DataFrame(config_list(), columns=["tf", "entry", "exit"])
    parts = full["entry"].map(parse_entry)
    full["ma"], full["breach"], full["sides"] = parts.str[0], parts.str[1], parts.str[2]
    t = full.merge(t, on=["tf", "entry", "exit"], how="left") if len(t) else full
    for col in ("is_n", "cf_n", "pre_n", "n12"):
        t[col] = t[col].fillna(0) if col in t else 0
    for col in ("is_p", "cf_p", "pre_p", "p12", "boot_p12", "boot_p3"):
        t[col] = t[col].fillna(1.0) if col in t else 1.0
    t = lib.select(t)
    t["bh12"] = SR.bh(t["p12"].to_numpy(float), BH_Q)
    t["candidate"] = t["stage3"] & t["bh12"]
    t["weak_candidate"] = t["stage3"] & ~t["bh12"]
    t["candidate_20x"] = t["candidate"] & t["x20_ok"]
    m = max(int(t["stage2"].sum()), 1)
    t["stage3_bonf"] = t["stage3"] & (t["pre_p"] < 0.05 / m)
    t["all3_positive"] = (t["is_mean_pct"] > 0) & (t["cf_mean_pct"] > 0) & (t["pre_mean_pct"] > 0)
    t["is_h1"] = (t["tf"] == H1[0]) & (t["entry"] == H1[1]) & (t["exit"] == H1[2])
    t["h1_pass"] = t["is_h1"] & (t["p12"] < H1_ALPHA) & (t["pre_mean_pct"] > 0)
    return t


def _period_block(g: pd.DataFrame) -> dict:
    y = g["net"].to_numpy()
    w, ls = y[y > 0], y[y <= 0]
    d = {"n": len(g), "win_pct": 100 * float((y > 0).mean()) if len(y) else None,
         "mean_net_pct": 100 * float(y.mean()) if len(y) else None,
         "mean_gross_pct": 100 * float(g["gross_raw"].mean()) if len(y) else None,
         "mean_cost_pct": 100 * float((g["gross_raw"] - g["net"]).mean()) if len(y) else None,
         "avg_win_pct": 100 * float(w.mean()) if len(w) else None, "avg_loss_pct": 100 * float(ls.mean()) if len(ls) else None,
         "pf": float(w.sum() / -ls.sum()) if len(ls) and ls.sum() < 0 else None,
         "r_mean": float(g["r"].astype(float).mean()) if len(y) else None,
         "r_net_mean": float(g["r_net"].astype(float).mean()) if len(y) else None,
         "hold_median": float(g["hold"].median()) if len(y) else None,
         "exit_reason_pct": {k: 100 * float((g["reason"] == k).mean()) for k in ("TP", "SL", "TIME", "EOD")} if len(y) else {}}
    d.update(liq_stats(g["mae_held"].to_numpy(), g["sl_dist"].to_numpy(), "", g["mae"].to_numpy()) if len(y) else {})
    return d


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _failed(c: pd.DataFrame) -> pd.Series:
    return c.apply(lambda r: ",".join(k for k in c.columns if not r[k]), axis=1) if len(c) else pd.Series(dtype=str)


def stage_conditions(t: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The library gauntlet's conditions (lib.select) one by one, to report why each configuration dropped."""
    k2 = max(int(t.attrs.get("top_k", 30)), 1)
    col = lambda name: t[name] if name in t else pd.Series(np.nan, index=t.index)  # noqa: E731
    c1 = pd.DataFrame({"n": col("is_n") >= 100, "mean": col("is_mean_pct") > 0,
                       "coins": (col("is_coins_pos") >= 4) & (col("is_coins_pos") > col("is_coins_n") / 2),
                       "half1": col("is_half1_mean_pct") > 0, "half2": col("is_half2_mean_pct") > 0})
    c2 = pd.DataFrame({"mean": col("cf_mean_pct") > 0, "pf": col("cf_pf") > 1, "coins": col("cf_coins_pos") >= 4,
                       "p": col("cf_p") < 0.05 / k2})
    c3 = pd.DataFrame({"mean": col("pre_mean_pct") > 0, "pf": col("pre_pf") > 1,
                       "coins": (col("pre_coins_pos") >= 3) & (col("pre_coins_pos") > col("pre_coins_n") / 2),
                       "p": col("pre_p") < 0.05})
    return c1, c2, c3


def report(t: pd.DataFrame, h1_tr: pd.DataFrame, h1_sens: pd.DataFrame, out: str) -> dict:
    os.makedirs(out, exist_ok=True)
    SR = env()["SR"]
    attrs = dict(t.attrs)
    t = t.copy()
    t.attrs.update(attrs)
    c1, c2, c3 = stage_conditions(t)
    # why each configuration dropped (empty = passed, or never reached that stage)
    t["stage1_failed"] = _failed(c1)
    t["stage2_failed"] = np.where(t["stage1_top"], _failed(c2), "")
    t["stage3_failed"] = np.where(t["stage2"], _failed(c3), "")
    t.to_csv(os.path.join(out, "results.csv"), index=False)
    # near misses: stage-1 top-k failing exactly one stage-2 condition / stage-2 survivors failing one stage-3 condition
    top = t[t["stage1_top"]].copy()
    top["stage2_fails"] = (~c2[t["stage1_top"]]).sum(axis=1)
    s2 = t[t["stage2"]].copy()
    if len(s2):
        s2["stage3_fails"] = (~c3[t["stage2"]]).sum(axis=1)
    near = pd.concat([top[top["stage2_fails"] == 1].assign(kind="stage2_one_miss"),
                      s2[s2["stage3_fails"] == 1].assign(kind="stage3_one_miss") if len(s2) else None,
                      t[t["all3_positive"]].assign(kind="all_three_periods_positive"),
                      t[(t["p12"] < 0.05) & ~t["bh12"]].assign(kind="p12_below_0.05_not_bh")], ignore_index=True)
    near.to_csv(os.path.join(out, "near_miss.csv"), index=False)
    agg = dict(configs=("entry", "size"), is_n=("is_n", "sum"), cf_n=("cf_n", "sum"), pre_n=("pre_n", "sum"),
               is_mean_pct=("is_mean_pct", "mean"), cf_mean_pct=("cf_mean_pct", "mean"), pre_mean_pct=("pre_mean_pct", "mean"),
               is_gross_pct=("is_gross_mean_pct", "mean"), cf_gross_pct=("cf_gross_mean_pct", "mean"),
               pre_gross_pct=("pre_gross_mean_pct", "mean"), is_cost_pct=("is_cost_mean_pct", "mean"),
               cf_cost_pct=("cf_cost_mean_pct", "mean"), is_hold=("is_hold_mean", "mean"), cf_hold=("cf_hold_mean", "mean"),
               is_win_pct=("is_win_pct", "mean"), is_r=("is_r_mean", "mean"), sl_med_pct=("all_sl_med_pct", "mean"),
               liq20_pct=("all_liq20_pct", "mean"), liq50_pct=("all_liq50_pct", "mean"),
               is_pos=("is_mean_pct", lambda s: int((s > 0).sum())), cf_pos=("cf_mean_pct", lambda s: int((s > 0).sum())),
               pre_pos=("pre_mean_pct", lambda s: int((s > 0).sum())), all3_positive=("all3_positive", "sum"),
               stage1=("stage1", "sum"), stage2=("stage2", "sum"), stage3=("stage3", "sum"), bh12=("bh12", "sum"),
               candidate=("candidate", "sum"))
    agg = {k: v for k, v in agg.items() if v[0] in t}
    t.groupby("tf").agg(**agg).reindex(list(TFS)).to_csv(os.path.join(out, "per_tf.csv"))
    pv = [t.groupby(col).agg(**agg).assign(dimension=col) for col in ("ma", "breach", "sides")]
    pd.concat(pv).to_csv(os.path.join(out, "per_variant.csv"))
    h1 = t[t["is_h1"]].iloc[0]
    h1_info = {"config": list(H1), "rule": f"p12 < {H1_ALPHA} (one-sided, day-clustered, periods 1+2 pooled) and period-3 mean net > 0",
               "pass": bool(h1["h1_pass"]), "p12": h1["p12"], "n12": h1["n12"], "mean12_pct": h1.get("mean12_pct"),
               "boot_p12": h1["boot_p12"], "boot_p3": h1["boot_p3"], "pre_mean_pct": h1.get("pre_mean_pct"),
               "library_gauntlet": {k: bool(h1[k]) for k in ("stage1", "stage1_top", "stage2", "stage3", "x20_ok", "bh12")},
               "skips": {k: h1.get(k) for k in ("signals", "skip_stop", "skip_target", "skip_atr")},
               "periods": {}, "close_entry_sensitivity": {}}
    if len(h1_tr):
        for s in ("is", "oos", "pre"):
            h1_info["periods"][s] = _period_block(h1_tr[h1_tr["split"] == s])
        h1_info["periods"]["p12"] = _period_block(h1_tr[h1_tr["split"].isin(["is", "oos"])])
        h1_tr.to_csv(os.path.join(out, "h1_trades.csv.gz"), index=False)
        bc = h1_tr.groupby(["symbol", "split"]).agg(n=("net", "size"), mean_net_pct=("net", lambda x: 100 * x.mean()),
                                                    win_pct=("net", lambda x: 100 * (x > 0).mean()),
                                                    mean_gross_pct=("gross_raw", lambda x: 100 * x.mean()))
        bc.to_csv(os.path.join(out, "h1_by_coin.csv"))
        yr = h1_tr.assign(year=pd.to_datetime(h1_tr["entry_ts"]).dt.year).groupby("year").agg(
            n=("net", "size"), mean_net_pct=("net", lambda x: 100 * x.mean()), win_pct=("net", lambda x: 100 * (x > 0).mean()))
        yr.to_csv(os.path.join(out, "h1_by_year.csv"))
    h1_info["sensitivity"] = {}
    if len(h1_sens):
        for s in ("is", "oos", "pre"):
            g = h1_sens[(h1_sens["mode"] == "close") & (h1_sens["split"] == s)]
            h1_info["close_entry_sensitivity"][s] = {"n": len(g), "mean_net_pct": 100 * float(g["net"].mean()) if len(g) else None}
        for label in SENS:
            g = h1_sens[h1_sens["mode"] == label]
            g12, gp = g[g["split"].isin(["is", "oos"])], g[g["split"] == "pre"]
            h1_info["sensitivity"][label] = {
                "settings": SENS[label], "n12": len(g12), "mean12_pct": 100 * float(g12["net"].mean()) if len(g12) else None,
                "p12": _p12(SR, g12), "pre_n": len(gp), "pre_mean_pct": 100 * float(gp["net"].mean()) if len(gp) else None,
                "win12_pct": 100 * float((g12["net"] > 0).mean()) if len(g12) else None,
                "tp12_pct": 100 * float((g12["reason"] == "TP").mean()) if len(g12) else None,
                "would_pass": bool(_p12(SR, g12) < H1_ALPHA and len(gp) and gp["net"].mean() > 0)}
    cc = h1_info["sensitivity"].get("cost_c")
    # PREREG section 9: an H1 pass whose p12 is >= 0.05 under cost stress (c) is labelled cost-sensitive
    h1_info["cost_sensitive_pass"] = bool(h1["h1_pass"]) and (cc is None or not cc["p12"] < H1_ALPHA)
    with open(os.path.join(out, "h1.json"), "w") as fh:
        json.dump(_clean(h1_info), fh, indent=1)
    summary = {"configs": len(t), "h1_pass": bool(h1["h1_pass"]), "h1_p12": float(h1["p12"]),
               "h1_pre_mean_pct": _clean(h1.get("pre_mean_pct")), "stage1": int(t["stage1"].sum()),
               "stage1_top": int(t["stage1_top"].sum()), "stage2": int(t["stage2"].sum()), "stage3": int(t["stage3"].sum()),
               "stage3_bonferroni": int(t["stage3_bonf"].sum()), "bh12_all": int(t["bh12"].sum()),
               "candidate": int(t["candidate"].sum()), "weak_candidate": int(t["weak_candidate"].sum()),
               "candidate_20x": int(t["candidate_20x"].sum()), "all_three_periods_positive": int(t["all3_positive"].sum()),
               "h1_cost_sensitive_pass": h1_info["cost_sensitive_pass"],
               "stage1_condition_failed": {k: int((~c1[k]).sum()) for k in c1.columns},
               "stage2_condition_failed_of_top": {k: int((~c2.loc[t["stage1_top"], k]).sum()) for k in c2.columns},
               "stage3_condition_failed_of_stage2": {k: int((~c3.loc[t["stage2"], k]).sum()) for k in c3.columns}}
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    return summary


def run(bars: str, pre: str, out: str, procs: int, tfs: tuple, n_boot: int) -> dict:
    prereg_sha = check_prereg()
    t0 = time.time()
    tasks = [(bars, pre, tf, coin) for tf in tfs for coin in COINS]   # 5m first: the longest tasks start first
    trades, sens, skips, manifest, sizes = [], [], [], {}, []
    with Pool(procs) as pool:
        for tr, se, sk, man, size in pool.imap_unordered(_task, tasks):
            trades.append(tr)
            sens.append(se)
            skips.extend(sk)
            manifest.update(man)
            sizes.append(size)
            print(f"{size[0]} {size[1]}: {len(tr)} trades, {time.time() - t0:.0f}s", flush=True)
    order = ["tf", "entry", "split", "symbol", "entry_ts"]       # tasks finish in any order: fix the row order so
    tt = pd.concat([x for x in trades if len(x)], ignore_index=True)  # every float sum is bit-identical across runs
    tt = tt.sort_values(order, kind="mergesort").reset_index(drop=True)
    ss = pd.concat([x for x in sens if len(x)], ignore_index=True) if any(len(x) for x in sens) else pd.DataFrame()
    if len(ss):
        ss = ss.sort_values(order, kind="mergesort").reset_index(drop=True)
    skips = sorted(skips, key=lambda r: (r["tf"], r["entry"], r["split"], r["symbol"]))
    rows = []
    for tf in tfs:
        g = tt[tt["tf"] == tf]
        if len(g):
            rows.extend(extra_rows(g, ss[ss["tf"] == tf] if len(ss) else ss, [s for s in skips if s["tf"] == tf], n_boot))
        print(f"{tf}: {len(g)} trades, {len(rows)} configs so far, {time.time() - t0:.0f}s", flush=True)
    t = finish(rows)
    h1m = (tt["tf"] == H1[0]) & (tt["entry"] == H1[1])
    h1s = (ss["tf"] == H1[0]) & (ss["entry"] == H1[1]) if len(ss) else None
    summary = report(t, tt[h1m].sort_values(["symbol", "entry_ts"]), ss[h1s] if len(ss) else ss, out)
    summary["seconds"] = round(time.time() - t0)
    summary["bars_dir"], summary["pre_dir"], summary["n_boot"], summary["tfs"] = bars, pre, n_boot, list(tfs)
    summary["code_sha256"] = {os.path.basename(__file__): _sha256(__file__)}
    summary["prereg_sha256"] = prereg_sha
    summary["series_bars"] = {f"{tf}_{coin}": [nm, npre] for tf, coin, nm, npre in sorted(sizes)}
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    with open(os.path.join(out, "data_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in summary.items() if k != "series_bars"}))
    return summary


# ------------------------------------------------------------------ synthetic data (self-test and timing only)
def synth(n: int = 9000, tf: str = "1h", seed: int = 0, start: str = "2021-01-01", vol: float = 0.006,
          mr: float = 0.0) -> pd.DataFrame:
    """Random walk with volatility clusters and up / flat / down regimes of zero mean drift (no edge for any rule).
    ``mr`` > 0 adds a mean-reverting component (a planted edge for this strategy). SYNTHETIC ONLY."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=n, freq=f"{TF_MIN[tf]}min", tz="UTC")
    regime = np.repeat(rng.choice([-1, 0, 0, 1], size=n // 600 + 1), 600)[:n]
    sig = vol * np.exp(np.repeat(rng.normal(0, 0.4, n // 80 + 1), 80)[:n])
    ret = rng.normal(0, 1, n) * sig + regime * 0.06 * sig
    jump = rng.random(n) < 0.01
    ret[jump] *= 4
    x = np.cumsum(ret)
    if mr > 0:                                   # OU deviation around the walk, half-life ~4 bars
        dev = np.zeros(n)
        z = rng.normal(0, 1, n) * vol * mr
        for i in range(1, n):
            dev[i] = 0.84 * dev[i - 1] + z[i]
        x = x + dev
    c = 100 * np.exp(x)
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.0003, n))
    hi = np.maximum(o, c) * (1 + rng.uniform(0, 1, n) * sig * 0.6)
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 1, n) * sig * 0.6)
    return pd.DataFrame({"ts": ts, "open": o, "high": hi, "low": lo, "close": c, "volume": rng.lognormal(0, 1, n) * 100})


def synth_bars(dest: str, seed: int = 0) -> dict:
    """Write SYNTHETIC files laid out like the real ones (<dest>/bars/<coin>-<tf>.csv.gz for 2021-01-01..2026-09-29
    and <dest>/pre2021/<coin>-{5m,15m,1h,4h}.csv.gz for 2020-01..2021-08), 5m random walks resampled with the
    locked resampler. Only for timing the full pipeline; never mistake them for market data."""
    L = env()["L"]
    os.makedirs(os.path.join(dest, "bars"), exist_ok=True)
    os.makedirs(os.path.join(dest, "pre2021"), exist_ok=True)
    with open(os.path.join(dest, "SYNTHETIC_README.txt"), "w") as fh:
        fh.write("SYNTHETIC random-walk bars written by lib_reel5m.synth_bars. Not market data.\n")
    spans = {"bars": ("2021-01-01", "2026-09-30", ("5m", "15m", "30m", "1h", "4h")),
             "pre2021": ("2020-01-01", "2021-09-01", ("5m", "15m", "1h", "4h"))}
    counts = {}
    for i, coin in enumerate(COINS):
        for sub, (a, b, tfs) in spans.items():
            n = int((pd.Timestamp(b) - pd.Timestamp(a)) / pd.Timedelta("5min"))
            d5 = synth(n, "5m", seed + 17 * i + (0 if sub == "bars" else 1000), start=a, vol=0.0012 + 0.0002 * i)
            for tf in tfs:
                d = d5 if tf == "5m" else L.resample_ohlcv(d5, tf)
                d = d.copy()
                d["ts"] = pd.to_datetime(d["ts"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                p = os.path.join(dest, sub, f"{coin.lower()}-{tf}.csv.gz")
                d[["ts", "open", "high", "low", "close", "volume"]].to_csv(p, index=False, float_format="%.6f")
                counts[f"{sub}/{coin.lower()}-{tf}"] = len(d)
    return counts


def lookahead_check(tf: str = "5m", n: int = 4000, cuts=(0.45, 0.7, 0.93), seed: int = 5, lo: int = 260) -> None:
    """Signals and trades up to a cut must be identical when bars after it are removed or replaced by junk.
    Coarse (whole-series) check; decision_lookahead_check below is the per-decision one that catches one-bar leaks."""
    E = env()
    cost = E["L"]._cost(tf, MAX_HOLD)
    df = synth(n, tf, seed)
    rng = np.random.default_rng(1)

    def everything(d: pd.DataFrame) -> dict:
        ind = indicators(d)
        out = {}
        for name in ENTRY_NAMES:
            P = Prep(ind, *parse_entry(name))
            _t, sg, _s = simulate(P, cost, lo, len(d) - 1, trade=False)
            for label, kw in SENS.items():
                tr, _g, _s = simulate_sens(P, cost, lo, len(d) - 1, **kw)
                out[(name, label)] = (tr, sg)
            tr, _g, _s = simulate(P, cost, lo, len(d) - 1, "open")
            out[(name, "open")] = (tr, sg)
        return out

    full = everything(df)
    for cut in [int(n * f) for f in cuts]:
        d2 = df.iloc[:cut].copy()
        d3 = df.copy()
        for k in ("open", "high", "low", "close"):
            d3.loc[d3.index[cut:], k] = d3[k].to_numpy()[cut:] * rng.uniform(0.5, 1.5, n - cut)
        tail = d3.loc[d3.index[cut:], ["open", "high", "low", "close"]]
        d3.loc[d3.index[cut:], "high"] = tail.max(axis=1).to_numpy()
        d3.loc[d3.index[cut:], "low"] = tail.min(axis=1).to_numpy()
        for label, d in (("removed", d2), ("changed", d3)):
            other = everything(d)
            # the truncated run can signal up to cut-2 and ends with an EOD exit at cut-1; the junked run has full length
            lim = cut - 1 if label == "removed" else cut
            for key, (tr, sg) in full.items():
                tr2, sg2 = other[key]
                a = [s for s in sg if s["signal_idx"] < lim]
                b = [s for s in sg2 if s["signal_idx"] < lim]
                assert a == b, f"lookahead ({label}) signals {key} {tf} cut={cut}"
                a = [x for x in tr if x["exit_idx"] < lim]
                b = [x for x in tr2 if x["exit_idx"] < lim]
                assert a == b, f"lookahead ({label}) trades {key} {tf} cut={cut}"


def decision_lookahead_check(tf: str, n: int = 1500, per: int = 3, seed: int = 8, lo: int = 260,
                             variants: tuple = ("open", "close", "live_target")) -> list:
    """Each sampled decision must survive junking everything it may not see (returns the violations, [] = ok):
    a signal at s -> every bar after s; entry / stop / skip of a trade entered on bar e -> every bar from e on except
    o[e] (next-open entry); an exit on bar j -> c[j] (moved inside [l[j], h[j]]) and every bar after j. Catches a
    one-bar leak that lookahead_check cannot see. SYNTHETIC ONLY."""
    cost = env()["L"]._cost(tf, MAX_HOLD)
    df = synth(n, tf, seed, mr=2.0)
    rng = np.random.default_rng(seed)
    kws = {"open": {}, **SENS}

    def junk(k, keep_ohl=False, keep_open=False):
        O, H, L, C = (df[c].to_numpy().copy() for c in ("open", "high", "low", "close"))
        for x in (O, H, L, C):
            x[k + 1:] *= rng.uniform(0.7, 1.3, n - k - 1)
        if keep_ohl:
            C[k] = rng.uniform(L[k], H[k])
        else:
            for x in ((C, H, L) if keep_open else (O, C, H, L)):
                x[k] *= rng.uniform(0.7, 1.3)
        a = k + 1 if keep_ohl else k
        H[a:] = np.maximum.reduce([O, H, L, C])[a:]
        L[a:] = np.minimum.reduce([O, H, L, C])[a:]
        return df.assign(open=O, high=H, low=L, close=C)

    def run(d, name, trade, variant="open"):
        P = Prep(indicators(d), *parse_entry(name))
        if not trade:
            return simulate(P, cost, lo, len(d) - 1, trade=False)[1]
        return simulate_sens(P, cost, lo, len(d) - 1, **kws[variant])[0]

    bad = []
    for name in ENTRY_NAMES:
        sg = run(df, name, False)
        for s in rng.choice(sg, min(per, len(sg)), replace=False):
            if [x for x in run(junk(s["signal_idx"] + 1), name, False) if x["signal_idx"] == s["signal_idx"]] != [s]:
                bad.append(("signal", name, s["signal_idx"]))
        for variant in variants:
            next_open = kws[variant].get("entry_mode", "open") == "open"
            tr = run(df, name, True, variant)
            for i in rng.choice(len(tr), min(per, len(tr)), replace=False):
                t = tr[i]
                key = lambda x: (x["signal_idx"], x["entry_idx"], x["entry_px"], x["stop_px"])  # noqa: E731
                tr2 = run(junk(t["entry_idx"], keep_open=next_open), name, True, variant)
                m = [x for x in tr2 if x["signal_idx"] == t["signal_idx"]]
                if tr2[:i] != tr[:i] or [key(x) for x in m] != [key(t)]:
                    bad.append(("entry", name, variant, t["signal_idx"]))
                for j in sorted({t["entry_idx"], t["exit_idx"], int(rng.integers(t["entry_idx"], t["exit_idx"] + 1))}):
                    m = [x for x in run(junk(j, keep_ohl=True), name, True, variant) if x["signal_idx"] == t["signal_idx"]]
                    same = (m[0]["exit_idx"], m[0]["reason"], m[0]["exit_px"]) == (j, t["reason"], t["exit_px"]) if m else False
                    if not m or m[0]["exit_idx"] < j or (j == t["exit_idx"] and t["reason"] in ("SL", "TP") and not same):
                        bad.append(("exit", name, variant, t["signal_idx"], j))
    return bad


def engine_parity_check(n: int = 3000, seed: int = 9) -> int:
    """exit_trade == engine._simulate_one (FIXED) on random trades, and run_fixed == engine.run_backtest."""
    E = env()
    L, ENG, fg = E["L"], E["ENG"], E["fg"]
    df = synth(n, "15m", seed)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = fg.atr(df, 14).to_numpy(float)
    rng = np.random.default_rng(seed)
    checked = 0
    for mh in (MAX_HOLD, 48, 7):
        cost = dataclasses.replace(L._cost("15m", mh), warmup=40)     # short synthetic series: small warm-up
        for sl, tp in ((1.0, 2.0), (1.5, 3.0), (2.0, 1.0), (0.3, 0.4)):
            cfg = L.ExitCfg(name="x", mode="FIXED", sl_atr=sl, tp_atr=tp)
            for i in rng.integers(30, n - 2, 40):
                side = int(rng.choice([-1, 1]))
                e = int(i) + 1
                want = ENG._simulate_one(side, e, o, h, l, c, float(atr[i]), cfg, cost, n)
                entry = o[e] * (1.0 + side * cost.slip_side)
                sld = sl * float(atr[i]) / entry
                got = exit_trade(side, e, entry, entry * (1.0 - side * sld), entry * (1.0 + side * tp * float(atr[i]) / entry),
                                 o, h, l, c, cost)
                for k in ("side", "entry_idx", "exit_idx", "entry_px", "exit_px", "gross", "fee", "funding", "net", "mae",
                          "mfe", "reason", "hold"):
                    assert got[k] == want[k], (k, got[k], want[k])
                assert abs(got["sl_dist"] - want["sl_dist"]) <= 1e-12 * max(1.0, abs(want["sl_dist"]))
                checked += 1
            lg = rng.random(n) < 0.03
            sh = (rng.random(n) < 0.03) & ~lg
            want = L.run_backtest(df, atr, lg, sh, cfg, cost, 40, n - 5)
            got = run_fixed(o, h, l, c, atr, lg, sh, sl, tp, cost, 40, n - 5)
            assert len(want) == len(got) and len(want) > 10
            for k in ("side", "entry_idx", "exit_idx", "entry_px", "exit_px", "gross", "fee", "funding", "net", "mae", "mfe",
                      "reason", "hold", "sl_dist", "signal_idx"):
                assert (want[k].to_numpy() == got[k].to_numpy()).all(), k
            checked += len(want)
    return checked


def selftest() -> None:
    assert len(config_list()) == 40 and len(set(config_list())) == 40 and H1 in config_list()
    for tf in TFS:
        lookahead_check(tf, n=3000)
        bad = decision_lookahead_check(tf)
        assert bad == [], (tf, bad[:5])
    print("look-ahead ok on", TFS, "(series cuts and per-decision junking)")
    print("engine parity ok on", engine_parity_check(), "trades")
    E = env()
    cost = E["L"]._cost("5m", MAX_HOLD)
    df = synth(30000, "5m", 11, vol=0.0015)
    ind = indicators(df)
    counts = {}
    for name in ENTRY_NAMES:
        P = Prep(ind, *parse_entry(name))
        tr, sg, sk = simulate(P, cost, 300, len(df) - MAX_HOLD - 2)
        tr2, sg2, sk2 = simulate(P, cost, 300, len(df) - MAX_HOLD - 2)
        assert tr == tr2 and sg == sg2 and sk == sk2, f"nondeterministic {name}"
        counts[name] = (len(sg), len(tr), sk["stop"], sk["target"])
        assert len(tr) > 20, (name, len(tr))
        net = np.array([x["net"] for x in tr])
        assert np.isfinite(net).all()
    print("5m synthetic 30000 bars (signals, trades, skip_stop, skip_target):", counts)
    print("selftest ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selftest":
        selftest()
    elif cmd == "count":
        cl = config_list()
        print(f"N = {len(cl)} configurations ({len(TFS)} timeframes x {len(MA_TYPES)} MA x {len(BREACHES)} breach x "
              f"{len(SIDES)} sides); H1 = {H1}")
    elif cmd == "synth-bars":
        print(json.dumps(synth_bars(sys.argv[2]), indent=1))
    elif cmd == "run":
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("cmd")
        ap.add_argument("--bars", required=True)
        ap.add_argument("--pre", default=os.path.join(ROOT, "data", "pre2021"))
        ap.add_argument("--out", default=os.path.join(HERE, "out"))
        ap.add_argument("--procs", type=int, default=4)
        ap.add_argument("--tfs", default=",".join(TFS))
        ap.add_argument("--n-boot", type=int, default=2000)
        a = ap.parse_args()
        run(a.bars, a.pre, a.out, a.procs, tuple(a.tfs.split(",")), a.n_boot)
    else:
        print(__doc__)
