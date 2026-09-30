"""Entry study part A: support / resistance (PREREG_ENTRY.md sections 1 and 2; fixed, hash in
PREREG_ENTRY.sha256).

    python3 research/entry_study/analysis_sr.py run [procs]      # stage 1 + stage 2
    python3 research/entry_study/analysis_sr.py stage1 [procs]   # per timeframe x coin tables
    python3 research/entry_study/analysis_sr.py stage2           # tests and outputs from stage 1

Overrides for robustness re-runs (defaults = the pre-registered run; each flag also reads an env var):
    --sig12 DIR     ($SR_SIG12)    periods 1 / 2 signal cache (default <scratch>/paper_rules/signals)
    --volume12 SRC  ($SR_VOLUME12) periods 1 / 2 volume: 'sweep_csv' (default: joined by ts from the sweep
                                   CSV) or 'npz' (the cache's own 'v' key, e.g. the Binance futures cache)
    --out DIR       ($SR_OUT)      output directory (default research/entry_study/out)
    --cache DIR     ($SR_CACHE)    stage-1 cache (default <scratch>/entry_study/cache)
    e.g. the Binance re-run: run 3 --sig12 <scratch>/binance/signals --volume12 npz
         --out research/entry_study/out_binance --cache <scratch>/entry_study/cache_binance
A run with any override is a robustness re-run, not the pre-registered result: run_meta.json and
sr_candidates.json then carry a 'robustness_rerun' block naming the overrides. Period 3 is never overridden.

Stage 1, one job per timeframe x coin (Pool):
  * two bar series: periods 1 and 2 = the paper_rules signal cache (locked code, sweep bars) with
    volume joined by ts from the sweep CSV; period 3 = the pre2021 cache (final_signals.py). Each
    signal's outcome and features are computed on the series its signal came from.
  * signal bars of the 36 account strategies per period: the signal bar's open time in the period,
    i >= warm-up (L.warmup_bars), and a next bar to enter on. DOGE = sigservice.doge_join(DOGE_L,
    DOGE_S): long on the long rule, SHORT on the short rule. The first run of this study used the old
    join DOGE_L - DOGE_S, which turned every DOGE short signal into a long (found by this study's
    verifier; fixed in the live bot and all caches on 2026-09-30, then this analysis was re-run).
    The first run's outputs are kept in out/before_doge_fix/.
  * random-entry null per period: min(20,000, eligible bars) bars drawn uniformly without
    replacement from the same eligible bars, side +1 / -1 with probability 1/2 each
    (np.random.default_rng([RANDOM_SEED, tf minutes, coin index, period]); choice, then side).
  * every distinct (bar, side) pair gets one outcome and one feature row:
      outcome   research/strategy_profiles/profiles._scan (paper v3: next-bar open + slippage,
                2 ATR stop, size_position leverage from profiles._sizer with atr / next open,
                stepped lock, fees, funding) in growing look-ahead passes 64 / 512 / 4096 as in
                profiles._job, plus one more pass of 32,768 bars so that long trades still resolve.
                A trade enters the tests only if it was sized (leverage > 0) and closed before the
                data ends ('open' trades are counted and left out).
      features  sr.features_for with the traded leverage (the PREREG's "L = the actual sizing
                result"), levels from sr.levels_for on the same series.
  * per unit (strategy / random / all strategies pooled) and period: counts, week sums for the
    P1 / P2 groups (additive over coins) and descriptive sums; the per-pair table is cached.
Stage 2 (pooled over coins):
  * cell = strategy x timeframe, tested only if it has >= 300 period-1 signals (signal bars,
    pooled over coins). P1 = mean ROE(level_before_lock = 0) - mean ROE(= 1); P2 = mean
    ROE(support_before_stop = 1) - mean ROE(= 0); hypothesis > 0 for both.
  * one-sided p: week-block bootstrap, blocks = Monday-00:00-UTC weeks of the signal bar, 2,000
    resamples of the weeks with replacement (same draws for P1 and P2 of one unit and period),
    p = (1 + #{resampled difference <= 0 or undefined}) / (2,000 + 1). 'insufficient' when either
    group has < 30 trades in that period.
  * BH at FDR 10% over all tested cells x {P1, P2} in period 1 (an 'insufficient' test enters the
    family with p = 1). Period 2: same sign as period 1 and one-sided p < 0.05. Period 3: same sign
    when both groups have >= 30 trades, else 'no data'. Candidate = passes all three.
  * the random null is tested the same way per timeframe (pooled coins) and reported beside.
Outputs in research/entry_study/out/: sr_cells.csv, sr_trials.csv, sr_random.csv,
sr_descriptive.json, sr_candidates.json, run_meta.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import warnings
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
os.environ.setdefault("SWEEP_DATA", f"{SCR}/sweepdata")
for _p in (HERE, os.path.join(ROOT, "research", "strategy_profiles"), os.path.join(ROOT, "research", "paper_rules"),
           ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
warnings.filterwarnings("ignore")

import sr  # noqa: E402
import profiles as PR  # noqa: E402
import rules_bt as RB  # noqa: E402
from paperbot import sweepsig  # noqa: E402

# ------------------------------------------------------------------ fixed by the PREREG / task
DEFAULT_SIG12 = f"{SCR}/paper_rules/signals"
DEFAULT_CACHE = f"{SCR}/entry_study/cache"
DEFAULT_OUT = os.path.join(HERE, "out")
VOLUME_SOURCES = ("sweep_csv", "npz")
# robustness re-runs only (module docstring); unset = the pre-registered run
SIG12 = os.path.abspath(os.environ.get("SR_SIG12") or DEFAULT_SIG12)
VOLUME12 = os.environ.get("SR_VOLUME12") or "sweep_csv"
SIG3 = f"{SCR}/entry_study/signals_pre2021"
SWEEP = os.environ["SWEEP_DATA"]
CACHE = os.path.abspath(os.environ.get("SR_CACHE") or DEFAULT_CACHE)
OUT = os.path.abspath(os.environ.get("SR_OUT") or DEFAULT_OUT)
PREREG = os.path.join(HERE, "PREREG_ENTRY.md")
PREREG_SHA = os.path.join(HERE, "PREREG_ENTRY.sha256")
TFS = ("5m", "15m", "30m", "1h", "4h")
COINS = RB.COINS
PERIODS = {1: ("2021-08-01", "2024-07-01"), 2: ("2024-07-01", "2026-09-30"), 3: ("2020-01-01", "2021-08-01")}
SOURCES = (("p12", (1, 2)), ("p3", (3,)))
RANDOM_N = 20_000
RANDOM_SEED = 20260930
BOOT_SEED = 20260930
BOOT_B = 2000
MIN_SIGNALS = 300
MIN_GROUP = 30
FDR_Q = 0.10
CONFIRM_ALPHA = 0.05
PASSES = (64, 512, 4096, 32768)
ROOM_EDGES = (0.5, 1.0, 2.0, 4.0)
ROOM_LABELS = ("[0,0.5)", "[0.5,1)", "[1,2)", "[2,4)", "[4,10]")
FIRST_LOCK = RB.LADDER.first_lock + RB.LADDER.trigger_gap          # 0.12: first lock arms here
RANDOM_UNIT, ALL_UNIT = "_RANDOM", "_ALL_STRATEGIES"
TESTS = ("P1", "P2")
TEST_FEATURE = {"P1": "level_before_lock", "P2": "support_before_stop"}
FEAT_KEEP = ("room", "floor", "room_type", "floor_type", "room_kind", "floor_kind", "level_before_lock",
             "support_before_stop", "breakout", "lock_dist_atr")
DESC_VARS = ("room_bucket", "breakout", "room_type", "floor_type", "room_kind", "floor_kind",
             "level_before_lock", "support_before_stop")
FEAT_CHUNK = 200_000
AMBIGUITIES = (
    "Leverage L in level_before_lock = the traded leverage (profiles._sizer on atr / next-bar open, PREREG 'L = actual "
    "sizing result'); the first-lock price uses the signal-bar close as the fill (sr.py), no slippage, no funding.",
    "Minimum sample '300 signals' = period-1 signal bars pooled over coins, counted before sizing (unsized signals "
    "count); a tested cell with < 30 trades in a group of a period is 'insufficient' for that period.",
    "An 'insufficient' period-1 test enters the BH family with p = 1, so m = 2 x tested cells.",
    "Bootstrap blocks = Monday-00:00-UTC weeks of the signal bar; the W weeks with >= 1 trade of that unit and period "
    "(pooled coins) are resampled W times with replacement; a resample leaving a group empty counts as <= 0; the same "
    "draws serve P1 and P2; p = (1 + k) / (2000 + 1).",
    "Only sized (size_position ok) and closed trades have a ROE: unsized signals and trades still open when the data "
    "ends are counted and left out. A fourth look-ahead pass of 32,768 bars was added to profiles' 64/512/4096 "
    "(no trade needed it).",
    "Random null: bars drawn without replacement from the same eligible bars as signals (period, after warm-up, a next "
    "bar exists); bars whose entry cannot be sized give no trade, so random trades < 20,000 on 1h / 4h.",
    "'Same sign' in periods 2 / 3 = the observed difference has the period-1 sign; period 3 uses the sign only.",
    "'Random shows the same effect' (market-wide label) = the random null of that timeframe (pooled coins) has the "
    "same-sign period-1 difference with one-sided p < 0.05 (unadjusted); the PREREG does not define it further.",
    "Levels of periods 1 / 2 look back into the cached bars before 2021-08-01; the cache's DOGE bars before 2021-07 are "
    "known to be corrupted (final_signals.py) and can enter long look-backs (e.g. L6 of 4h = 300 daily bars) early in "
    "period 1. Not altered.",
    "The PREREG's trial ledger is out/trials.csv; part A writes out/sr_trials.csv (one row per primary test).",
    "Descriptive 'pooled over strategies' counts a bar and side once per strategy that signalled it; "
    "'first lock reached' = best net ROE (as in _scan, after costs and funding) >= 12% before the exit.",
    "DOGE join corrected: the first run used DOGE = DOGE_L - DOGE_S, but DOGE_S is already -1 in compute_signals "
    "(sweep_lib.doge_short returns (zeros, short)), so every DOGE short-rule signal entered LONG. This was a bug (the "
    "account is the friend's long/short DOGE bot), also present in the live paperbot/sigservice.py and the backtest "
    "caches. Fixed everywhere with sigservice.doge_join (sum, not difference) and the caches' s__DOGE rebuilt (same "
    "signal bars, sides corrected); this analysis was then re-run unchanged. First-run outputs: out/before_doge_fix/. "
    "The fix is a data correction found by the study's verifier, not a choice made from results; it changes only the "
    "8 DOGE trials directly and the BH ranks of the family indirectly.",
)
# per-strategy remarks written into the 'note' column of sr_cells.csv / sr_trials.csv and into run_meta.json
STRATEGY_NOTES = {
    "DOGE": "DOGE = doge_join(DOGE_L, DOGE_S): long and short (the first run traded the short rule as long; "
            "see AMBIGUITIES and out/before_doge_fix/).",
}


def _lib():
    return sweepsig.lib()


def strategy_names(L) -> list[str]:
    return RB.strategy_names(L)


# ------------------------------------------------------------------ series and periods
def overrides() -> dict:
    """The non-default data / output settings of this process ({} = the pre-registered run)."""
    if VOLUME12 not in VOLUME_SOURCES:
        raise ValueError(f"SR_VOLUME12 / --volume12 must be one of {VOLUME_SOURCES}, not {VOLUME12!r}")
    cur = dict(sig12=SIG12, volume12=VOLUME12, out=OUT, cache=CACHE)
    dft = dict(sig12=os.path.abspath(DEFAULT_SIG12), volume12="sweep_csv", out=os.path.abspath(DEFAULT_OUT),
               cache=os.path.abspath(DEFAULT_CACHE))
    return {k: v for k, v in cur.items() if v != dft[k]}


def load_series(tf: str, coin: str, src: str):
    """(df for sr: ts ns, open, high, low, close, volume, atr; bars dict for _scan; signals dict)."""
    if src == "p12" and VOLUME12 == "sweep_csv":
        df, z = sr.chart_from_cache(tf, coin, SIG12, SWEEP)
        vol_missing = int(df.attrs["volume_missing"])
    else:                            # period 3, or periods 1 / 2 with the cache's own volume ('v')
        z = dict(np.load(os.path.join(SIG12 if src == "p12" else SIG3, f"sig_{tf}_{coin}.npz")))
        df = pd.DataFrame({"ts": z["ts"], "open": z["o"], "high": z["h"], "low": z["l"], "close": z["c"],
                           "volume": z["v"], "atr": z["atr"]})
        vol_missing = int((~np.isfinite(z["v"])).sum())
    b = {k: np.asarray(z[k]) for k in ("ts", "o", "h", "l", "c", "atr")}
    sigs = {k[3:]: np.asarray(z[k]) for k in z if k.startswith("s__")}
    return df, b, sigs, vol_missing


def period_bounds(ts: np.ndarray, period: int, warm: int) -> tuple[int, int]:
    """Signal bars [lo, hi) of a period: open time in [start, end), i >= warm-up, i + 1 < n."""
    start, end = (pd.Timestamp(x).value for x in PERIODS[period])
    lo = max(int(np.searchsorted(ts, start, side="left")), int(warm))
    hi = min(int(np.searchsorted(ts, end, side="left")), len(ts) - 1)
    return lo, max(lo, hi)


def random_bars(lo: int, hi: int, tf_min: int, coin_i: int, period: int, n: int = RANDOM_N,
                seed: int = RANDOM_SEED) -> tuple[np.ndarray, np.ndarray]:
    """min(n, hi - lo) bars uniform without replacement from [lo, hi), sides +1/-1 at 1/2 each."""
    rng = np.random.default_rng([seed, int(tf_min), int(coin_i), int(period)])
    k = min(n, hi - lo)
    idx = lo + np.sort(rng.choice(hi - lo, size=k, replace=False)) if k > 0 else np.zeros(0, np.int64)
    side = np.where(rng.random(k) < 0.5, 1, -1).astype(np.int8)
    return idx.astype(np.int64), side


# ------------------------------------------------------------------ outcome (profiles machinery)
def outcomes(b: dict, idx: np.ndarray, side: np.ndarray, tf: str, sizer, passes=PASSES) -> dict:
    """Paper v3 outcome per (signal bar, side) with profiles._sizer / profiles._scan, in growing
    look-ahead passes (profiles._job: 64 / 512 / 4096, chunk max(32, 256000 // H)); one more pass
    of 32,768 bars resolves the few still open. Trades still open when the data ends keep done=False."""
    L = _lib()
    n = len(b["ts"])
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    m = len(idx)
    idx = np.asarray(idx, np.int64)
    side = np.asarray(side, np.int64)
    a = b["atr"][idx]
    raw = b["o"][np.minimum(idx + 1, n - 1)]
    ok = np.isfinite(a) & (a > 0) & np.isfinite(raw) & (raw > 0) & (idx + 1 < n)
    lev = np.zeros(m)
    liq = np.full(m, np.nan)
    if ok.any():
        ll = np.array([sizer(int(s), float(x)) for s, x in zip(side[ok], a[ok] / raw[ok])], float).reshape(-1, 2)
        lev[ok], liq[ok] = ll[:, 0], ll[:, 1]
    sized = ok & (lev > 0)
    res = {k: np.full(m, np.nan) for k in ("held", "roe", "reason", "mfe")}
    done = np.zeros(m, bool)
    todo = np.flatnonzero(sized)
    for H in passes:
        if not len(todo):
            break
        last = H == passes[-1]
        nxt = []
        step = max(32, 256_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            r = PR._scan(b, idx[sel], side[sel], lev[sel], liq[sel], H, n, f_bar)
            keep = r["done"] | last | (idx[sel] + H >= n - 1)
            for k in res:
                res[k][sel[keep]] = r[k][keep]
            done[sel[keep]] = r["done"][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, np.int64)
    return dict(ok=ok, lev=lev, sized=sized, done=done, **res)


# ------------------------------------------------------------------ features (sr.py)
def feature_table(df: pd.DataFrame, tf: str, idx: np.ndarray, side: np.ndarray, lev: np.ndarray) -> dict:
    htf = sr.htf_bars(df, tf)
    lv = sr.levels_for(df, tf, htf, at=np.unique(idx))
    m = len(idx)
    out = {}
    for c0 in range(0, m, FEAT_CHUNK):
        sl = slice(c0, min(m, c0 + FEAT_CHUNK))
        f = sr.features_for(df, tf, htf, idx[sl], side[sl], lev[sl], levels=lv)
        for k in FEAT_KEEP:
            if k not in out:
                out[k] = np.empty(m, f[k].dtype)
            out[k][sl] = f[k]
    if m == 0:
        out = {k: np.zeros(0) for k in FEAT_KEEP}
    return out


def room_bucket(room: np.ndarray) -> np.ndarray:
    """0..4 for [0,0.5), [0.5,1), [1,2), [2,4), [4,10]; -1 where room is NaN."""
    bkt = np.digitize(room, ROOM_EDGES, right=False)
    return np.where(np.isfinite(room), bkt, -1)


# ------------------------------------------------------------------ aggregation helpers
def _week_sums(week, roe, g):
    """Per week: n0, s0, n1, s1 of roe split by g (0 / 1; other values ignored)."""
    uw, inv = np.unique(week, return_inverse=True)
    W = len(uw)
    out = {}
    for lab, sel in (("0", g == 0), ("1", g == 1)):
        out["n" + lab] = np.bincount(inv, weights=sel.astype(float), minlength=W)
        out["s" + lab] = np.bincount(inv, weights=np.where(sel, roe, 0.0), minlength=W)
    return uw, out


def unit_aggregates(rows: np.ndarray, T: dict, unit: str, period: int, tf: str, coin: str):
    """Counts, week sums and descriptive sums for one unit (a set of pair rows, repeats allowed)."""
    val = T["valid"][rows]
    v = rows[val]
    roe = T["roe"][v]
    cnt = dict(tf=tf, coin=coin, unit=unit, period=period, n_signals=int(len(rows)),
               n_atr_ok=int(T["ok"][rows].sum()), n_sized=int(T["sized"][rows].sum()),
               n_open=int((T["sized"][rows] & ~T["done"][rows]).sum()), n_trades=int(len(v)),
               n_long=int((T["side"][v] > 0).sum()), sum_roe=float(roe.sum()), sum_roe2=float((roe ** 2).sum()),
               n_win=int((roe > 0).sum()), n_lbl1=int((T["level_before_lock"][v] == 1).sum()),
               n_sbs1=int((T["support_before_stop"][v] == 1).sum()), n_breakout1=int((T["breakout"][v] == 1).sum()),
               sum_room=float(np.nansum(T["room"][v])), sum_floor=float(np.nansum(T["floor"][v])),
               n_lock_reached=int(T["lock_reached"][v].sum()), n_lock_exit=int((T["reason"][v] == 1).sum()),
               n_liq=int((T["reason"][v] == 2).sum()))
    wk_rows = []
    if len(v):
        week = T["week"][v]
        parts = {}
        for test in TESTS:
            g = T[TEST_FEATURE[test]][v]
            uw, s = _week_sums(week, roe, np.where(np.isfinite(g), g, -1))
            for k, arr in s.items():
                parts[f"{test}_{k}"] = arr
        wk = pd.DataFrame({"tf": tf, "coin": coin, "unit": unit, "period": period, "week": uw, **parts})
        wk_rows.append(wk)
    desc = []
    if unit in (RANDOM_UNIT, ALL_UNIT) and len(v):
        lr = T["lock_reached"][v].astype(float)
        le = (T["reason"][v] == 1).astype(float)
        for var in DESC_VARS:
            x = T[var][v]
            x = np.where(np.isfinite(x), x, -1).astype(np.int64)
            ux, inv = np.unique(x, return_inverse=True)
            desc.append(pd.DataFrame({"tf": tf, "coin": coin, "unit": unit, "period": period, "var": var, "value": ux,
                                      "n": np.bincount(inv, minlength=len(ux)),
                                      "sum_roe": np.bincount(inv, weights=roe, minlength=len(ux)),
                                      "sum_roe2": np.bincount(inv, weights=roe ** 2, minlength=len(ux)),
                                      "n_win": np.bincount(inv, weights=(roe > 0).astype(float), minlength=len(ux)),
                                      "n_lock_reached": np.bincount(inv, weights=lr, minlength=len(ux)),
                                      "n_lock_exit": np.bincount(inv, weights=le, minlength=len(ux))}))
    return cnt, wk_rows, desc


# ------------------------------------------------------------------ stage 1 job
def _job(args):
    tf, coin = args
    t0 = time.time()
    L = _lib()
    sizer = PR._sizer()
    names = strategy_names(L)
    ci = COINS.index(coin)
    tf_min = int(L.tf_minutes(tf))
    warm = int(L.warmup_bars(tf))
    counts, weeks, descs, info = [], [], [], {"tf": tf, "coin": coin, "series": {}}
    for src, periods in SOURCES:
        ts0 = time.time()
        df, b, sigs, vol_missing = load_series(tf, coin, src)
        n = len(b["ts"])
        missing = [nm for nm in names if nm not in sigs]
        if missing:
            raise KeyError(f"{tf} {coin} {src}: strategies missing from the cache: {missing}")
        units, bounds = {}, {}
        for p in periods:
            lo, hi = period_bounds(b["ts"], p, warm)
            bounds[p] = (lo, hi)
            for nm in names:
                sg = sigs[nm]
                idx = np.flatnonzero(sg[lo:hi]).astype(np.int64) + lo
                units[(nm, p)] = (idx, sg[idx].astype(np.int8))
            units[(RANDOM_UNIT, p)] = random_bars(lo, hi, tf_min, ci, p)
        keys = np.unique(np.concatenate([u[0] * 2 + (u[1] > 0) for u in units.values()] + [np.zeros(0, np.int64)]))
        pidx = (keys // 2).astype(np.int64)
        pside = np.where(keys % 2 == 1, 1, -1).astype(np.int8)
        t1 = time.time()
        oc = outcomes(b, pidx, pside, tf, sizer)
        t2 = time.time()
        ft = feature_table(df, tf, pidx, pside, np.where(oc["sized"], oc["lev"], np.nan))
        t3 = time.time()
        T = dict(idx=pidx, side=pside, ts=b["ts"][pidx], week=sr.period_key(b["ts"][pidx], "week"), **oc, **ft)
        T["valid"] = oc["sized"] & oc["done"] & np.isfinite(oc["roe"])
        T["lock_reached"] = oc["mfe"] >= FIRST_LOCK - 1e-12
        T["room_bucket"] = room_bucket(ft["room"])
        store = {k: np.asarray(v) for k, v in T.items()}
        for p in periods:
            all_rows = []
            for nm in names + [RANDOM_UNIT]:
                idx, side = units[(nm, p)]
                rows = np.searchsorted(keys, idx * 2 + (side > 0)).astype(np.int64)
                store[f"u__{nm}__p{p}"] = rows.astype(np.int32)
                c, w, d = unit_aggregates(rows, T, nm, p, tf, coin)
                c.update(src=src, eligible_bars=bounds[p][1] - bounds[p][0])
                counts.append(c); weeks += w; descs += d
                if nm != RANDOM_UNIT:
                    all_rows.append(rows)
            rows = np.concatenate(all_rows) if all_rows else np.zeros(0, np.int64)
            c, w, d = unit_aggregates(rows, T, ALL_UNIT, p, tf, coin)
            c.update(src=src, eligible_bars=bounds[p][1] - bounds[p][0])
            counts.append(c); weeks += w; descs += d
        os.makedirs(CACHE, exist_ok=True)
        np.savez(os.path.join(CACHE, f"sr_{tf}_{coin}_{src}.npz"), **store)
        info["series"][src] = dict(
            bars=n, first=str(pd.Timestamp(b["ts"][0])), last=str(pd.Timestamp(b["ts"][-1])), warmup_bars=warm,
            volume_missing=vol_missing,
            bounds={str(p): dict(lo=lo, hi=hi, first_signal_bar=str(pd.Timestamp(b["ts"][lo])) if hi > lo else None,
                                 last_signal_bar=str(pd.Timestamp(b["ts"][hi - 1])) if hi > lo else None,
                                 eligible_bars=hi - lo) for p, (lo, hi) in bounds.items()},
            pairs=int(len(keys)), pairs_atr_ok=int(oc["ok"].sum()), pairs_sized=int(oc["sized"].sum()),
            pairs_open_at_end=int((oc["sized"] & ~oc["done"]).sum()),
            pairs_resolved_after_4096=int((oc["done"] & (oc["held"] > 4096)).sum()),
            seconds=dict(load_and_units=round(t1 - ts0, 1), outcomes=round(t2 - t1, 1), features=round(t3 - t2, 1),
                         aggregate=round(time.time() - t3, 1)))
        del df, b, sigs, T, store, oc, ft
    info["seconds"] = round(time.time() - t0, 1)
    return (tf, coin, pd.DataFrame(counts), pd.concat(weeks, ignore_index=True) if weeks else pd.DataFrame(),
            pd.concat(descs, ignore_index=True) if descs else pd.DataFrame(), info)


def stage1(procs: int = 4) -> dict:
    _lib()  # hash check before any work
    os.makedirs(CACHE, exist_ok=True)
    jobs = [(tf, c) for tf in TFS for c in COINS]   # 5m first: longest jobs start first
    t0 = time.time()
    counts, weeks, descs, infos = [], [], [], []
    with Pool(procs, maxtasksperchild=1) as pool:
        for tf, coin, c, w, d, info in pool.imap_unordered(_job, jobs):
            counts.append(c); weeks.append(w); descs.append(d); infos.append(info)
            s = info["series"]
            print(f"[{time.time() - t0:6.0f}s] {tf:>3} {coin}: pairs {s['p12']['pairs']}+{s['p3']['pairs']} "
                  f"({info['seconds']}s: p12 {s['p12']['seconds']}, p3 {s['p3']['seconds']})", flush=True)
    counts = pd.concat(counts, ignore_index=True)
    weeks = pd.concat(weeks, ignore_index=True)
    descs = pd.concat(descs, ignore_index=True)
    infos.sort(key=lambda r: (TFS.index(r["tf"]), COINS.index(r["coin"])))
    counts.to_pickle(os.path.join(CACHE, "stage1_counts.pkl"))
    weeks.to_pickle(os.path.join(CACHE, "stage1_weeks.pkl"))
    descs.to_pickle(os.path.join(CACHE, "stage1_desc.pkl"))
    with open(os.path.join(CACHE, "stage1_info.json"), "w") as fh:
        json.dump(_clean(dict(wall_s=round(time.time() - t0, 1), jobs=infos)), fh, indent=1)
    print(f"stage 1 done in {time.time() - t0:.0f}s", flush=True)
    return dict(wall_s=round(time.time() - t0, 1))


# ------------------------------------------------------------------ statistics
def _diff(test: str, m0: float, m1: float) -> float:
    """P1 = mean(g0) - mean(g1) ('no level before the lock' better); P2 = mean(g1) - mean(g0)."""
    return m0 - m1 if test == "P1" else m1 - m0


def boot_counts(W: int, B: int, seed) -> np.ndarray:
    """(B, W) how often each week is drawn when W weeks are resampled with replacement."""
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, W, size=(B, W))
    return np.bincount((draws + W * np.arange(B)[:, None]).ravel(), minlength=B * W).reshape(B, W).astype(float)


def week_block_test(test: str, n0, s0, n1, s1, C: np.ndarray | None, min_group: int = MIN_GROUP) -> dict:
    """Observed difference and one-sided bootstrap p (hypothesis: difference > 0).
    n0, s0, n1, s1: per-week trade counts and ROE sums of group 0 and group 1; C: (B, W) week draws."""
    n0, s0, n1, s1 = (np.asarray(x, float) for x in (n0, s0, n1, s1))
    N0, N1 = float(n0.sum()), float(n1.sum())
    out = dict(n0=int(N0), n1=int(N1), weeks=int(len(n0)), mean0=np.nan, mean1=np.nan, diff=np.nan, p=np.nan,
               status="insufficient", undefined_resamples=0)
    if N0 > 0:
        out["mean0"] = float(s0.sum() / N0)
    if N1 > 0:
        out["mean1"] = float(s1.sum() / N1)
    if N0 > 0 and N1 > 0:
        out["diff"] = _diff(test, out["mean0"], out["mean1"])
    if N0 < min_group or N1 < min_group or C is None:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        bm0 = (C @ s0) / (C @ n0)
        bm1 = (C @ s1) / (C @ n1)
    bd = _diff(test, bm0, bm1)
    undefined = ~np.isfinite(bd)
    k = int(((bd <= 0) | undefined).sum())
    out.update(p=(1 + k) / (len(bd) + 1), status="ok", undefined_resamples=int(undefined.sum()))
    return out


def bh(p: np.ndarray, q: float = FDR_Q) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Benjamini-Hochberg: (reject, rank 1..m, adjusted p)."""
    p = np.asarray(p, float)
    m = len(p)
    if m == 0:
        return np.zeros(0, bool), np.zeros(0, int), np.zeros(0)
    order = np.argsort(p, kind="mergesort")
    ranked = p[order]
    rank = np.empty(m, int)
    rank[order] = np.arange(1, m + 1)
    below = ranked <= q * np.arange(1, m + 1) / m
    kmax = int(np.flatnonzero(below).max()) + 1 if below.any() else 0
    reject = rank <= kmax
    adj_sorted = np.minimum.accumulate((ranked * m / np.arange(1, m + 1))[::-1])[::-1]
    adj = np.empty(m)
    adj[order] = np.minimum(adj_sorted, 1.0)
    return reject, rank, adj


def unit_tests(wk: pd.DataFrame, unit_code: int, tf: str, period: int) -> dict:
    """P1 and P2 for one unit / timeframe / period from its week sums pooled over coins."""
    g = wk.groupby("week", sort=True)[[f"{t}_{k}" for t in TESTS for k in ("n0", "s0", "n1", "s1")]].sum()
    W = len(g)
    C = boot_counts(W, BOOT_B, [BOOT_SEED, unit_code, TFS.index(tf), period]) if W else None
    return {t: week_block_test(t, g[f"{t}_n0"], g[f"{t}_s0"], g[f"{t}_n1"], g[f"{t}_s1"], C) for t in TESTS}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "HEAD"], text=True).strip()
    except Exception as e:  # pragma: no cover
        return f"unknown ({e})"


def _num(x):
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def _clean(o):
    """JSON-safe copy: numpy scalars to Python, NaN / inf to None, tuples to lists, keys to str."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return [_clean(v) for v in o.tolist()]
    return _num(o)


# ------------------------------------------------------------------ stage 2
def stage2(stage1_meta: dict | None = None) -> dict:
    t0 = time.time()
    L = _lib()
    names = strategy_names(L)
    counts = pd.read_pickle(os.path.join(CACHE, "stage1_counts.pkl"))
    weeks = pd.read_pickle(os.path.join(CACHE, "stage1_weeks.pkl"))
    descs = pd.read_pickle(os.path.join(CACHE, "stage1_desc.pkl"))
    with open(os.path.join(CACHE, "stage1_info.json")) as fh:
        s1info = json.load(fh)
    unit_code = {nm: i for i, nm in enumerate(names)}
    unit_code[RANDOM_UNIT], unit_code[ALL_UNIT] = 1000, 1001

    # pooled-over-coins tests for every unit x tf x period
    wk_groups = {k: g for k, g in weeks.groupby(["unit", "tf", "period"], sort=False)}
    tests = {}
    for unit in names + [RANDOM_UNIT, ALL_UNIT]:
        for tf in TFS:
            for p in PERIODS:
                g = wk_groups.get((unit, tf, p))
                if g is None or g.empty:
                    tests[(unit, tf, p)] = {t: week_block_test(t, [], [], [], [], None) for t in TESTS}
                else:
                    tests[(unit, tf, p)] = unit_tests(g, unit_code[unit], tf, p)
    t_tests = time.time()

    cnt = counts.groupby(["unit", "tf", "period"]).sum(numeric_only=True)

    def cstat(unit, tf, p, key):
        try:
            return cnt.loc[(unit, tf, p), key]
        except KeyError:
            return 0

    # ---------------- cells
    rows = []
    for nm in names:
        for tf in TFS:
            r = dict(strategy=nm, tf=tf)
            for p in PERIODS:
                ns, nt = int(cstat(nm, tf, p, "n_signals")), int(cstat(nm, tf, p, "n_trades"))
                r[f"n_signals_p{p}"] = ns
                r[f"n_sized_p{p}"] = int(cstat(nm, tf, p, "n_sized"))
                r[f"n_trades_p{p}"] = nt
                r[f"n_open_excluded_p{p}"] = int(cstat(nm, tf, p, "n_open"))
                r[f"n_unsized_p{p}"] = ns - int(cstat(nm, tf, p, "n_sized"))
                r[f"mean_roe_p{p}"] = cstat(nm, tf, p, "sum_roe") / nt if nt else np.nan
                for k, lab in (("n_lbl1", "share_level_before_lock"), ("n_sbs1", "share_support_before_stop"),
                               ("n_breakout1", "share_breakout"), ("n_lock_reached", "share_lock_reached"),
                               ("n_long", "share_long")):
                    r[f"{lab}_p{p}"] = cstat(nm, tf, p, k) / nt if nt else np.nan
                r[f"mean_room_p{p}"] = cstat(nm, tf, p, "sum_room") / nt if nt else np.nan
                r[f"mean_floor_p{p}"] = cstat(nm, tf, p, "sum_floor") / nt if nt else np.nan
            r["tested"] = r["n_signals_p1"] >= MIN_SIGNALS
            r["not_tested_reason"] = "" if r["tested"] else f"period-1 signals {r['n_signals_p1']} < {MIN_SIGNALS}"
            for t in TESTS:
                for p in PERIODS:
                    x = tests[(nm, tf, p)][t]
                    for k in ("n0", "n1", "mean0", "mean1", "diff", "p", "status", "weeks", "undefined_resamples"):
                        r[f"{t}_{k}_p{p}"] = x[k]
                    y = tests[(RANDOM_UNIT, tf, p)][t]
                    r[f"random_{t}_diff_p{p}"] = y["diff"]
                    r[f"random_{t}_p_p{p}"] = y["p"]
            rows.append(r)
    cells = pd.DataFrame(rows)

    # ---------------- BH over all tested cells x {P1, P2}, period 1
    trial_rows = []
    for _, r in cells[cells["tested"]].iterrows():
        for t in TESTS:
            trial_rows.append(dict(trial_id=f"A-{r['strategy']}-{r['tf']}-{t}", part="A", strategy=r["strategy"],
                                   tf=r["tf"], test=t, feature=TEST_FEATURE[t],
                                   hypothesis=("mean ROE(level_before_lock=0) - mean ROE(=1) > 0" if t == "P1"
                                               else "mean ROE(support_before_stop=1) - mean ROE(=0) > 0")))
    trials = pd.DataFrame(trial_rows)
    if len(trials):
        for p in PERIODS:
            for k in ("n0", "n1", "mean0", "mean1", "diff", "p", "status", "weeks", "undefined_resamples"):
                trials[f"{k}_p{p}"] = [tests[(s, tf, p)][t][k] for s, tf, t in
                                       zip(trials["strategy"], trials["tf"], trials["test"])]
        p_bh = np.where(trials["status_p1"] == "ok", trials["p_p1"], 1.0)
        trials["p_for_bh"] = p_bh
        rej, rank, adj = bh(p_bh, FDR_Q)
        trials["bh_rank"] = rank
        trials["bh_threshold"] = FDR_Q * rank / len(trials)
        trials["bh_qvalue"] = adj
        trials["pass_p1_bh"] = rej & (trials["diff_p1"] > 0)
        sgn1 = np.sign(trials["diff_p1"])
        trials["pass_p2"] = trials["pass_p1_bh"] & (trials["status_p2"] == "ok") & (np.sign(trials["diff_p2"]) == sgn1) \
            & (trials["p_p2"] < CONFIRM_ALPHA)
        p3_ok = (trials["n0_p3"] >= MIN_GROUP) & (trials["n1_p3"] >= MIN_GROUP)
        trials["verdict_p3"] = np.where(~p3_ok, "no data", np.where(np.sign(trials["diff_p3"]) == sgn1, "same sign",
                                                                     "opposite sign"))
        trials["pass_p3"] = trials["pass_p2"] & (trials["verdict_p3"] == "same sign")
        trials["candidate"] = trials["pass_p3"]
        # random null beside: same test on random entries of that timeframe (pooled coins)
        for p in PERIODS:
            trials[f"random_diff_p{p}"] = [tests[(RANDOM_UNIT, tf, p)][t]["diff"] for tf, t in
                                           zip(trials["tf"], trials["test"])]
            trials[f"random_p_p{p}"] = [tests[(RANDOM_UNIT, tf, p)][t]["p"] for tf, t in
                                        zip(trials["tf"], trials["test"])]
        trials["random_same_effect_p1"] = (np.sign(trials["random_diff_p1"]) == sgn1) & (trials["random_p_p1"] < 0.05)
        trials["label"] = np.where(trials["candidate"] & trials["random_same_effect_p1"],
                                   "candidate, but the random null shows the same effect: market-wide, not the strategy",
                                   np.where(trials["candidate"], "candidate", ""))
        m = trials.set_index(["strategy", "tf", "test"])
        for t in TESTS:
            for col in ("p_for_bh", "bh_rank", "bh_qvalue", "pass_p1_bh", "pass_p2", "verdict_p3", "pass_p3", "candidate",
                        "random_same_effect_p1"):
                cells[f"{t}_{col}"] = [m.loc[(s, tf, t), col] if (s, tf, t) in m.index else None
                                       for s, tf in zip(cells["strategy"], cells["tf"])]
    t_cells = time.time()

    # ---------------- random null table
    rrows = []
    for tf in TFS:
        for p in PERIODS:
            sub = counts[(counts["unit"] == RANDOM_UNIT) & (counts["tf"] == tf) & (counts["period"] == p)]
            for scope, s in [("pooled", sub)] + [(c, sub[sub["coin"] == c]) for c in COINS]:
                nt = int(s["n_trades"].sum())
                r = dict(tf=tf, period=p, scope=scope, eligible_bars=int(s["eligible_bars"].sum()),
                         n_sampled=int(s["n_signals"].sum()), n_atr_ok=int(s["n_atr_ok"].sum()),
                         n_sized=int(s["n_sized"].sum()), n_trades=nt, n_open_excluded=int(s["n_open"].sum()),
                         mean_roe=s["sum_roe"].sum() / nt if nt else np.nan,
                         share_long=s["n_long"].sum() / nt if nt else np.nan,
                         share_level_before_lock=s["n_lbl1"].sum() / nt if nt else np.nan,
                         share_support_before_stop=s["n_sbs1"].sum() / nt if nt else np.nan,
                         share_breakout=s["n_breakout1"].sum() / nt if nt else np.nan,
                         share_lock_reached=s["n_lock_reached"].sum() / nt if nt else np.nan)
                if scope == "pooled":
                    x = tests[(RANDOM_UNIT, tf, p)]
                else:                              # per coin: descriptive only, no p
                    g = weeks[(weeks["unit"] == RANDOM_UNIT) & (weeks["tf"] == tf) & (weeks["period"] == p)
                              & (weeks["coin"] == scope)]
                    x = {t: dict(week_block_test(t, g[f"{t}_n0"], g[f"{t}_s0"], g[f"{t}_n1"], g[f"{t}_s1"], None),
                                 status="descriptive") for t in TESTS}
                for t in TESTS:
                    for k in ("n0", "n1", "mean0", "mean1", "diff", "p", "status"):
                        r[f"{t}_{k}"] = x[t][k]
                rrows.append(r)
    rnd = pd.DataFrame(rrows)

    # ---------------- descriptive
    desc = {}
    dsum = descs.groupby(["unit", "tf", "period", "var", "value"])[
        ["n", "sum_roe", "sum_roe2", "n_win", "n_lock_reached", "n_lock_exit"]].sum()
    names_for = {"room_bucket": dict(enumerate(ROOM_LABELS)), "room_type": {0: "none", **sr.FAMILY_NAME},
                 "floor_type": {0: "none", **sr.FAMILY_NAME}, "room_kind": {0: "none", **sr.KIND},
                 "floor_kind": {0: "none", **sr.KIND}}
    for tf in TFS:
        desc[tf] = {}
        for p in PERIODS:
            dd = {}
            for unit, lab in ((ALL_UNIT, "strategies_pooled"), (RANDOM_UNIT, "random_null")):
                block = {}
                for var in DESC_VARS:
                    try:
                        s = dsum.loc[(unit, tf, p, var)]
                    except KeyError:
                        block[var] = []
                        continue
                    tab = []
                    tot = float(s["n"].sum())
                    for val, x in s.iterrows():
                        nx = float(x["n"])
                        mean = x["sum_roe"] / nx if nx else np.nan
                        sd = np.sqrt(max(x["sum_roe2"] / nx - mean ** 2, 0.0)) if nx else np.nan
                        tab.append(dict(value=int(val), label=names_for.get(var, {}).get(int(val), str(int(val))),
                                        n=int(nx), share=nx / tot if tot else None, mean_roe=_num(mean),
                                        sd_roe=_num(sd), se_roe=_num(sd / np.sqrt(nx)) if nx > 1 else None,
                                        win_rate=_num(x["n_win"] / nx) if nx else None,
                                        lock_reached_share=_num(x["n_lock_reached"] / nx) if nx else None,
                                        lock_exit_share=_num(x["n_lock_exit"] / nx) if nx else None))
                    block[var] = tab
                x = tests[(unit, tf, p)]
                block["P1_pooled"] = {k: _num(v) for k, v in x["P1"].items()}
                block["P2_pooled"] = {k: _num(v) for k, v in x["P2"].items()}
                nt = int(cstat(unit, tf, p, "n_trades"))
                block["n_trades"] = nt
                block["mean_roe"] = _num(cstat(unit, tf, p, "sum_roe") / nt) if nt else None
                dd[lab] = block
            desc[tf][str(p)] = dd
    desc_doc = dict(note="Descriptive only (PREREG section 2): not used for any decision. 'strategies_pooled' counts a "
                         "trade once per strategy that signalled it. room buckets in ATR; *_type 1..6 = L1..L6 "
                         "(swing, prior day, prior week, round, volume profile, HTF swing); P1/P2_pooled = the primary "
                         "statistics on all strategies' trades of the timeframe pooled (week-block bootstrap, one-sided).",
                    first_lock_roe=FIRST_LOCK, room_buckets=ROOM_LABELS, by_tf_period=desc)

    # ---------------- candidates
    cand = trials[trials["candidate"]] if len(trials) else trials
    cand_doc = dict(
        definition="period-1 BH (FDR 10%, all tested cells x {P1,P2}) -> period-2 same sign and one-sided p < 0.05 "
                   "-> period-3 same sign (>= 30 trades in both groups, else 'no data'). A candidate is not a rule "
                   "change; it can only go to a Q7 copy-account proposal.",
        cells_tested=int(cells["tested"].sum()), cells_total=int(len(cells)), trials=int(len(trials)),
        insufficient_in_period1=int((trials["status_p1"] != "ok").sum()) if len(trials) else 0,
        bh_survivors_period1=int(trials["pass_p1_bh"].sum()) if len(trials) else 0,
        passing_period2=int(trials["pass_p2"].sum()) if len(trials) else 0,
        passing_period3=int(trials["pass_p3"].sum()) if len(trials) else 0,
        period3_no_data_among_period2_passers=int(((trials["pass_p2"]) & (trials["verdict_p3"] == "no data")).sum())
        if len(trials) else 0,
        candidates=[{k: _num(v) for k, v in r.items()} for r in cand.to_dict("records")],
        bh_survivors=[{k: _num(v) for k, v in r.items()} for r in
                      (trials[trials["pass_p1_bh"]].to_dict("records") if len(trials) else [])],
        random_null=[{k: _num(v) for k, v in r.items()} for r in rnd[rnd["scope"] == "pooled"][
            ["tf", "period", "n_trades", "P1_diff", "P1_p", "P1_status", "P2_diff", "P2_p", "P2_status"]].to_dict("records")])

    ov = overrides()
    rr = dict(note="Robustness re-run with non-default data / outputs: NOT the pre-registered result "
                   "(PREREG_ENTRY.md fixes the default data). Same code, seeds, tests and thresholds.",
              overrides=ov) if ov else None
    if rr:
        cand_doc["robustness_rerun"] = rr

    # ---------------- write
    cells["note"] = cells["strategy"].map(STRATEGY_NOTES).fillna("")
    if len(trials):
        trials["note"] = trials["strategy"].map(STRATEGY_NOTES).fillna("")
    os.makedirs(OUT, exist_ok=True)
    cells.to_csv(os.path.join(OUT, "sr_cells.csv"), index=False)
    trials.to_csv(os.path.join(OUT, "sr_trials.csv"), index=False)
    rnd.to_csv(os.path.join(OUT, "sr_random.csv"), index=False)
    with open(os.path.join(OUT, "sr_descriptive.json"), "w") as fh:
        json.dump(_clean(desc_doc), fh, indent=1)
    with open(os.path.join(OUT, "sr_candidates.json"), "w") as fh:
        json.dump(_clean(cand_doc), fh, indent=1)

    sha_file = open(PREREG_SHA).read().split()[0]
    sha_now = _sha256(PREREG)
    tot = counts.groupby(["unit", "period"]).sum(numeric_only=True)
    strat = counts[~counts["unit"].isin([RANDOM_UNIT, ALL_UNIT])]
    skipped = dict(
        cells_not_tested=cells.loc[~cells["tested"], ["strategy", "tf", "n_signals_p1"]].to_dict("records"),
        tests_insufficient=[dict(trial_id=r["trial_id"], period=p, n0=r[f"n0_p{p}"], n1=r[f"n1_p{p}"])
                            for r in trials.to_dict("records") for p in PERIODS if r[f"status_p{p}"] != "ok"]
        if len(trials) else [],
        signals_without_trade={str(p): dict(
            signals=int(strat.loc[strat["period"] == p, "n_signals"].sum()),
            atr_or_next_open_invalid=int((strat.loc[strat["period"] == p, "n_signals"]
                                          - strat.loc[strat["period"] == p, "n_atr_ok"]).sum()),
            not_sized=int((strat.loc[strat["period"] == p, "n_atr_ok"] - strat.loc[strat["period"] == p, "n_sized"]).sum()),
            open_at_data_end_excluded=int(strat.loc[strat["period"] == p, "n_open"].sum()),
            trades=int(strat.loc[strat["period"] == p, "n_trades"].sum())) for p in PERIODS},
        random_without_trade={str(p): dict(
            sampled=int(tot.loc[(RANDOM_UNIT, p), "n_signals"]),
            not_sized_or_invalid=int(tot.loc[(RANDOM_UNIT, p), "n_signals"] - tot.loc[(RANDOM_UNIT, p), "n_sized"]),
            open_at_data_end_excluded=int(tot.loc[(RANDOM_UNIT, p), "n_open"]),
            trades=int(tot.loc[(RANDOM_UNIT, p), "n_trades"])) for p in PERIODS})
    meta = dict(
        script="research/entry_study/analysis_sr.py", git_head=_git_head(),
        prereg_sha256_file=sha_file, prereg_sha256_now=sha_now, prereg_hash_ok=sha_file == sha_now,
        signal_lock=sweepsig.verify()["prereg_sha256_file"],
        seeds=dict(random_null=f"np.random.default_rng([{RANDOM_SEED}, tf_minutes, coin_index(BTC,ETH,SOL,DOGE,LTC,BCH "
                                f"= 0..5), period]); rng.choice(eligible, min(20000, eligible), replace=False) "
                                f"then rng.random(k) < 0.5 -> long",
                   bootstrap=f"np.random.default_rng([{BOOT_SEED}, unit_code (strategy index in the account list 0..35, "
                             f"random 1000, all-strategies 1001), tf_index (5m..4h = 0..4), period]); "
                             f"rng.integers(0, W, (2000, W)); same draws for P1 and P2"),
        constants=dict(periods=PERIODS, random_n=RANDOM_N, bootstrap_resamples=BOOT_B, min_signals=MIN_SIGNALS,
                       min_group=MIN_GROUP, fdr_q=FDR_Q, confirm_alpha=CONFIRM_ALPHA, lookahead_passes=PASSES,
                       first_lock_roe=FIRST_LOCK, room_buckets=ROOM_LABELS),
        data=dict(periods_1_2=SIG12, period_3=SIG3,
                  volume_periods_1_2=(os.path.join(SWEEP, "full") if VOLUME12 == "sweep_csv"
                                      else "the periods 1 / 2 cache's own 'v' key"), cache=CACHE),
        timings=dict(stage1=(stage1_meta or {}).get("wall_s", s1info.get("wall_s")),
                     stage2_tests_s=round(t_tests - t0, 1), stage2_total_s=round(time.time() - t0, 1)),
        row_counts=dict(sr_cells=len(cells), sr_trials=len(trials), sr_random=len(rnd),
                        stage1_counts=len(counts), stage1_week_rows=len(weeks), stage1_desc_rows=len(descs)),
        headline=dict(cells_tested=cand_doc["cells_tested"], trials=cand_doc["trials"],
                      insufficient_in_period1=cand_doc["insufficient_in_period1"],
                      bh_survivors_period1=cand_doc["bh_survivors_period1"], passing_period2=cand_doc["passing_period2"],
                      passing_period3=cand_doc["passing_period3"], candidates=len(cand_doc["candidates"])),
        ambiguities=list(AMBIGUITIES), strategy_notes=dict(STRATEGY_NOTES), skipped=skipped, jobs=s1info["jobs"])
    if rr:
        meta["robustness_rerun"] = rr
    with open(os.path.join(OUT, "run_meta.json"), "w") as fh:
        json.dump(_clean(meta), fh, indent=1)
    print(f"stage 2 done in {time.time() - t0:.0f}s (tests {t_tests - t0:.0f}s, cells {t_cells - t_tests:.0f}s)",
          flush=True)
    print(json.dumps(meta["headline"], indent=1), flush=True)
    return meta


def _apply_overrides(argv: list[str]) -> list[str]:
    """Strip --sig12 / --volume12 / --out / --cache from argv, set the module settings and the env vars (so
    Pool workers see them under any start method). Returns the remaining argv."""
    global SIG12, VOLUME12, OUT, CACHE
    flags = {"--sig12": ("SR_SIG12", True), "--volume12": ("SR_VOLUME12", False), "--out": ("SR_OUT", True),
             "--cache": ("SR_CACHE", True)}
    rest, i = [], 0
    while i < len(argv):
        a = argv[i]
        key, val = (a.split("=", 1) + [None])[:2] if a.startswith("--") else (a, None)
        if key in flags:
            if val is None:
                if i + 1 >= len(argv):
                    raise SystemExit(f"{key} needs a value")
                val, i = argv[i + 1], i + 1
            env, is_path = flags[key]
            os.environ[env] = os.path.abspath(val) if is_path else val
        else:
            rest.append(a)
        i += 1
    SIG12 = os.path.abspath(os.environ.get("SR_SIG12") or DEFAULT_SIG12)
    VOLUME12 = os.environ.get("SR_VOLUME12") or "sweep_csv"
    OUT = os.path.abspath(os.environ.get("SR_OUT") or DEFAULT_OUT)
    CACHE = os.path.abspath(os.environ.get("SR_CACHE") or DEFAULT_CACHE)
    ov = overrides()
    if ov:
        if ({"sig12", "volume12"} & set(ov)) and not {"out", "cache"} <= set(ov):
            raise SystemExit("a re-run on other data must name its own --out and --cache (the defaults hold the "
                             "pre-registered run)")
        print(f"robustness re-run, not the pre-registered result: {json.dumps(ov)}", flush=True)
    return rest


def main(argv: list[str]) -> None:
    argv = _apply_overrides(list(argv))
    cmd = argv[1] if len(argv) > 1 else ""
    procs = int(argv[2]) if len(argv) > 2 else 4
    sha_file = open(PREREG_SHA).read().split()[0]
    if sha_file != _sha256(PREREG):
        raise SystemExit("PREREG_ENTRY.md does not match PREREG_ENTRY.sha256")
    if cmd == "run":
        m = stage1(procs)
        stage2(m)
    elif cmd == "stage1":
        stage1(procs)
    elif cmd == "stage2":
        stage2()
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv)
