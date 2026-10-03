"""Trendline entry study (PREREG_TRENDLINE.md; fixed, hash in PREREG_TRENDLINE.sha256).

    python3 research/entry_study/analysis_trendline.py run [procs]      # stage 1 + stage 2
    python3 research/entry_study/analysis_trendline.py stage1 [procs]   # per timeframe x coin tables
    python3 research/entry_study/analysis_trendline.py stage2           # tests and outputs from stage 1
    python3 research/entry_study/analysis_trendline.py checks [binance_out]   # section 6 / 7 checks of the candidates

The run stops at once when PREREG_TRENDLINE.md does not match PREREG_TRENDLINE.sha256.

Overrides for robustness re-runs (defaults = the pre-registered run; each flag also reads an env var):
    --sig12 DIR   ($TL_SIG12)  periods 1 / 2 signal cache (default <scratch>/paper_rules/signals)
    --out DIR     ($TL_OUT)    output directory (default research/entry_study/out)
    --cache DIR   ($TL_CACHE)  stage-1 cache (default <scratch>/entry_study/cache_trendline)
    --sig3 DIR    ($TL_SIG3)   period 3 cache (tests only; the pre-registered run never overrides it)
    --tfs LIST    ($TL_TFS)    comma-separated timeframes (tests only)
    e.g. the Binance re-run of section 6 (1): run 3 --sig12 <scratch>/binance/signals
         --out research/entry_study/out_binance --cache <scratch>/entry_study/cache_trendline_binance
A run with any override is a robustness re-run, not the pre-registered result: trendline_run_meta.json and
trendline_candidates.json then carry a 'robustness_rerun' block naming the overrides.

What it does (section numbers = PREREG_TRENDLINE.md):
  Stage 1, one job per timeframe x coin:
    * periods 1 / 2 = the paper_rules signal cache (locked code); period 3 = the pre2021 cache
      (final_signals.py). Signal bars of the 36 account strategies per period exactly as part A
      (analysis_sr.period_bounds: open time in the period, after warm-up, a next bar exists; DOGE is
      already doge_join(DOGE_L, DOGE_S) in both caches).
    * random entries: part A's draw (analysis_sr.random_bars, same seed 20260930): the same bars and
      sides, so the same outcomes; only the trendline features are new.
    * outcome per distinct (bar, side): analysis_sr.outcomes (paper v3 net ROE, the same code as A).
      Unsized signals and trades still open when the data ends are counted and left out.
    * features: trendline.lines_for on the whole series (causal per bar) + trendline.features_for.
    * per unit (strategy / random / all strategies pooled) and period: counts, week sums of the four
      primary tests (T1..T4) and descriptive sums; the per-pair table is cached for the checks.
  Stage 2 (pooled over coins):
    * cell = strategy x timeframe, tested if it has >= 300 period-1 signal bars (pooled coins, before
      sizing). The random entries of each timeframe (pooled coins) are tested the same way and are part
      of the family: 4 x tested cells + 4 x 5 timeframes tests (planned 600).
    * T1 tl_break_now, T3 tl_support, T4 tl_aligned: diff = mean ROE(=1) - mean ROE(=0);
      T2 tl_against: diff = mean ROE(=0) - mean ROE(=1). Hypothesis diff > 0 (one-sided).
    * week-block bootstrap (Monday-00:00-UTC weeks of the signal bar, the W weeks with trades resampled W
      times): 10,000 resamples in period 1, 2,000 in periods 2 / 3, seed
      np.random.default_rng([20261003, unit code, tf index, period]); unit code = account-list index
      0..35, random 1000, all strategies 1001; the four tests of one unit and period share the draws.
      p = (1 + #{resampled diff <= 0 or undefined}) / (B + 1). 'insufficient' if a group has < 30 trades.
    * period 1: BH at FDR 10% over the whole family ('insufficient' enters with p = 1), diff > 0;
      period 2: both groups >= 30, same sign, one-sided p < 0.05; period 3: both groups >= 30 and same
      sign, else 'no data' (not a pass). Candidate = all three.
    * 'market-wide' label on a strategy-cell candidate: the random entries of the same timeframe have the
      same-sign period-1 difference with unadjusted one-sided p < 0.05 (as in part A).
  Checks (section 6 proposal conditions and section 7 candidate-only tables), for candidates only:
    Binance re-run (needs the re-run's trendline_trials.csv), leverage tiers, effect size, trades left,
    coin majority, loss note; sensitivity table (one definition change at a time, never adopted),
    long / short, per coin, period 1 without DOGE's 2021-08 signals.
Outputs in <out>/: trendline_cells.csv, trendline_trials.csv (trial ledger, one row per test),
trendline_random.csv, trendline_descriptive.json, trendline_candidates.json, trendline_run_meta.json,
trendline_checks.json and trendline_trials_checks.csv (checks stage; the checks are listed apart from the family).
"""

from __future__ import annotations

import hashlib
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
SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
os.environ.setdefault("SWEEP_DATA", f"{SCR}/sweepdata")
for _p in (HERE, os.path.join(ROOT, "research", "strategy_profiles"), os.path.join(ROOT, "research", "paper_rules"),
           ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
warnings.filterwarnings("ignore")

import analysis_sr as A  # noqa: E402  (part A: outcomes, random draw, bootstrap, BH, helpers)
import sr  # noqa: E402
import trendline as TL  # noqa: E402
import profiles as PR  # noqa: E402
from paperbot import sweepsig  # noqa: E402

# ------------------------------------------------------------------ fixed by the PREREG
DEFAULT_SIG12 = A.DEFAULT_SIG12
DEFAULT_SIG3 = A.SIG3
DEFAULT_CACHE = f"{SCR}/entry_study/cache_trendline"
DEFAULT_OUT = os.path.join(HERE, "out")
ALL_TFS = A.TFS
SIG12 = os.path.abspath(os.environ.get("TL_SIG12") or DEFAULT_SIG12)
SIG3 = os.path.abspath(os.environ.get("TL_SIG3") or DEFAULT_SIG3)
CACHE = os.path.abspath(os.environ.get("TL_CACHE") or DEFAULT_CACHE)
OUT = os.path.abspath(os.environ.get("TL_OUT") or DEFAULT_OUT)
TFS = tuple(os.environ.get("TL_TFS").split(",")) if os.environ.get("TL_TFS") else ALL_TFS
PREREG = os.path.join(HERE, "PREREG_TRENDLINE.md")
PREREG_SHA = os.path.join(HERE, "PREREG_TRENDLINE.sha256")
CODE_LOCK = os.path.join(HERE, "CODE_TRENDLINE.sha256")
CODE_FILES = ("research/entry_study/trendline.py", "research/entry_study/analysis_trendline.py",
              "tests/test_entry_trendline.py")
COINS = A.COINS
PERIODS = A.PERIODS
SOURCES = A.SOURCES
RANDOM_UNIT, ALL_UNIT = A.RANDOM_UNIT, A.ALL_UNIT
BOOT_SEED = 20261003
BOOT_B = {1: 10_000, 2: 2_000, 3: 2_000}
MIN_SIGNALS = 300
MIN_GROUP = 30
FDR_Q = 0.10
CONFIRM_ALPHA = 0.05
FIRST_LOCK = A.FIRST_LOCK
TESTS = ("T1", "T2", "T3", "T4")
TEST_FEATURE = {"T1": "tl_break_now", "T2": "tl_against", "T3": "tl_support", "T4": "tl_aligned"}
GOOD = {"T1": 1, "T2": 0, "T3": 1, "T4": 1}          # the group the hypothesis says is better
TEST_NAME = {"T1": "break", "T2": "against", "T3": "support", "T4": "aligned"}
HYPOTHESIS = {"T1": "mean ROE(tl_break_now=1) - mean ROE(=0) > 0",
              "T2": "mean ROE(tl_against=0) - mean ROE(=1) > 0",
              "T3": "mean ROE(tl_support=1) - mean ROE(=0) > 0",
              "T4": "mean ROE(tl_aligned=1) - mean ROE(=0) > 0"}
# section 6 proposal conditions
MIN_EFFECT = 0.005
MIN_GOOD = {1: 300, 2: 100}
LEV_MIN_GROUP = 10
COIN_MIN_GROUP = 30
# section 7 descriptive buckets
DIST_EDGES = (0.5, 1.0, 2.0, 4.0, 10.0)
DIST_LABELS = ("[0,0.5)", "[0.5,1)", "[1,2)", "[2,4)", "[4,10)", "10 (none or >= 10)")
TOUCH_LABELS = {-1: "no live line", 0: "<= 2", 1: "3", 2: ">= 4"}
SLOPE_EDGES = (0.05, 0.15)
SLOPE_LABELS = {-1: "no live line", 0: "<= 0.05", 1: "(0.05, 0.15]", 2: "(0.15, 0.5]"}
AGE_EDGES = (50, 150)
AGE_LABELS = {-1: "no live line", 0: "< 50", 1: "[50, 150)", 2: "[150, 300)"}
TREND_SIDE_LABELS = {2 * t + lg: f"{TL.TREND_NAME[t]} / {'long' if lg else 'short'}" for t in range(4) for lg in (0, 1)}
DESC_VARS = ("tl_break_now", "tl_against", "tl_support", "tl_aligned", "ahead_bucket", "behind_bucket",
             "touch_ahead_bucket", "touch_behind_bucket", "slope_ahead_bucket", "slope_behind_bucket",
             "age_ahead_bucket", "age_behind_bucket", "tl_break_3", "tl_break_10", "trend_side")
FEAT_STORE = {"tl_ahead": np.float32, "tl_behind": np.float32, "tl_break_now": np.int8, "tl_against": np.int8,
              "tl_support": np.int8, "tl_aligned": np.int8, "tl_touch_ahead": np.float32,
              "tl_touch_behind": np.float32, "tl_slope_ahead": np.float32, "tl_slope_behind": np.float32,
              "tl_age_ahead": np.float32, "tl_age_behind": np.float32, "tl_break_3": np.int8, "tl_break_10": np.int8,
              "tl_trend": np.int8}
# section 7 sensitivity variants (candidates only; never adopted)
VARIANTS = (("k", 3), ("k", 8), ("delta", 0.1), ("delta", 0.5), ("slope_max", 0.25), ("slope_max", 1.0),
            ("window", 150), ("window", 500), ("near", 1.0), ("near", 3.0))
AMBIGUITIES = (
    "File names: the PREREG names the analysis script analysis_tl.py and the outputs tl_*.csv / tl_*.json; the "
    "task that implemented it asked for analysis_trendline.py and trendline_*.csv / *.json. Same content.",
    "A missing ATR makes a candidate A fail (comparisons with NaN are false), so a line needing it is 'none' "
    "(PREREG 2-2 item 4); a signal bar with a missing or non-positive ATR has no features and no trade.",
    "A*(B) is searched once per swing low B among A >= B - 294 (an older A can never be inside the 300-bar window of "
    "a bar that can use B since i >= B + 5); the line of bar i is (A*(B), B) when A*(B) >= i - 299. This equals the "
    "PREREG's scan from the most recent A back, because the conditions on A do not depend on i.",
    "The break tolerance delta (0.25 ATR) is used in all three 'close beyond the line' rules: between A and B, the "
    "break after B, and the close part of a touch; eps (0.25 ATR) is only the touch distance of the low / high. The "
    "sensitivity variants 'break margin 0.1 / 0.5' change delta in all three places.",
    "tl_break_now / tl_break_3 / tl_break_10 use the line in use at bar i (the PREREG's 'line of that bar'): a break "
    "of an older line that was replaced by a newer swing is not counted. tl_break_now does not require the line to "
    "be live at i - 1 beyond 'first break bar = i' (the first break bar is by definition the first).",
    "Clipping: a live ahead / behind line can be up to 0.25 ATR on the wrong side of the close (not yet broken); "
    "tl_ahead / tl_behind are then clipped to 0 (PREREG: clipped to 0..10).",
    "Trade counts use the traded outcome of analysis_sr.outcomes (paper v3, profiles._scan, sizing with atr / "
    "next-bar open); 'sized and closed before the data ends' trades only, as in part A.",
    "Bootstrap: the W weeks with >= 1 trade of the unit and period (pooled coins) are resampled W times; a resample "
    "leaving a group empty counts as <= 0; the four tests of one unit and period share the draws; period 1 uses "
    "10,000 resamples, periods 2 / 3 use 2,000.",
    "The family (BH, period 1) holds every tested cell's four tests plus the random entries' four tests of each "
    "timeframe; 'insufficient' tests enter with p = 1. Period 2 / 3 rules are the same for cells and random tests.",
    "'Market-wide' label (strategy-cell candidates) = random entries of the same timeframe with the same-sign "
    "period-1 difference and unadjusted one-sided p < 0.05 (10,000 resamples), as part A.",
    "Leverage tiers (section 6 (2)): tiers = the distinct traded leverages (20 / 30 / 40 / 50x); a tier enters when "
    "both groups have >= 10 trades; the weighted average uses the tier's trade count (both groups).",
    "Coin majority (section 6 (5)): among the coins with >= 30 trades in both groups in period 1, the number of "
    "coins whose difference has the candidate's sign must be more than half of them.",
    "Descriptive 'strategies pooled' counts a bar and side once per strategy that signalled it (as part A); "
    "'first lock reached' = best net ROE (as in _scan, after costs and funding) >= 12% before the exit.",
    "Periods 1 / 2 look back into the cached bars before 2021-08-01 (300-bar window = 50 days on 4h); the cache's "
    "DOGE bars before 2021-07 are known to be corrupted (part A, section 1). Not altered; the candidate checks "
    "report period 1 without DOGE's 2021-08 signals.",
)


def _lib():
    return sweepsig.lib()


# ------------------------------------------------------------------ settings, hashes
def overrides() -> dict:
    cur = dict(sig12=SIG12, sig3=SIG3, out=OUT, cache=CACHE, tfs=",".join(TFS))
    dft = dict(sig12=os.path.abspath(DEFAULT_SIG12), sig3=os.path.abspath(DEFAULT_SIG3),
               out=os.path.abspath(DEFAULT_OUT), cache=os.path.abspath(DEFAULT_CACHE), tfs=",".join(ALL_TFS))
    return {k: v for k, v in cur.items() if v != dft[k]}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def check_prereg(path: str | None = None, sha_path: str | None = None) -> dict:
    """Hash of the pre-registration now vs the registered hash file (first token)."""
    path, sha_path = path or PREREG, sha_path or PREREG_SHA
    want = open(sha_path).read().split()[0]
    now = sha256(path)
    return dict(prereg_sha256_file=want, prereg_sha256_now=now, prereg_hash_ok=want == now)


def prereg_commit() -> str:
    """The commit that added the pre-registration (git log of PREREG_TRENDLINE.md)."""
    import subprocess
    try:
        return subprocess.check_output(["git", "-C", ROOT, "log", "--format=%H %cI %s", "--",
                                        os.path.relpath(PREREG, ROOT)], text=True).strip().splitlines()[-1]
    except Exception as e:  # pragma: no cover
        return f"unknown ({e})"


def code_hashes() -> dict:
    """SHA-256 of the locked code files now, and whether they match CODE_TRENDLINE.sha256 (if it exists)."""
    now = {f: sha256(os.path.join(ROOT, f)) for f in CODE_FILES if os.path.exists(os.path.join(ROOT, f))}
    lock = {}
    if os.path.exists(CODE_LOCK):
        for line in open(CODE_LOCK):
            parts = line.split()
            if len(parts) == 2:
                lock[parts[1]] = parts[0]
    return dict(code_sha256=now, code_lock_file=os.path.relpath(CODE_LOCK, ROOT) if lock else None,
                code_lock=lock or None, code_lock_ok=(all(now.get(f) == h for f, h in lock.items()) if lock else None))


# ------------------------------------------------------------------ series and units
def load_bars(tf: str, coin: str, src: str):
    """(bars dict ts, o, h, l, c, atr; signals dict strategy -> +1 / 0 / -1) of one cache file."""
    z = np.load(os.path.join(SIG12 if src == "p12" else SIG3, f"sig_{tf}_{coin}.npz"))
    b = {k: np.asarray(z[k]) for k in ("ts", "o", "h", "l", "c", "atr")}
    sigs = {k[3:]: np.asarray(z[k]) for k in z.files if k.startswith("s__")}
    return b, sigs


def buckets(ft: dict) -> dict:
    """Descriptive buckets (section 7) from a feature dict; -1 = no live line / undefined."""
    def dist(x):
        return np.where(np.isfinite(x), np.digitize(x, DIST_EDGES, right=False), -1)

    def touch(x):
        return np.where(np.isfinite(x), np.where(x <= 2, 0, np.where(x == 3, 1, 2)), -1)

    def slope(x):
        return np.where(np.isfinite(x), np.digitize(np.abs(x), SLOPE_EDGES, right=True), -1)

    def age(x):
        return np.where(np.isfinite(x), np.digitize(x, AGE_EDGES, right=False), -1)

    out = {"ahead_bucket": dist(ft["tl_ahead"]), "behind_bucket": dist(ft["tl_behind"]),
           "touch_ahead_bucket": touch(ft["tl_touch_ahead"]), "touch_behind_bucket": touch(ft["tl_touch_behind"]),
           "slope_ahead_bucket": slope(ft["tl_slope_ahead"]), "slope_behind_bucket": slope(ft["tl_slope_behind"]),
           "age_ahead_bucket": age(ft["tl_age_ahead"]), "age_behind_bucket": age(ft["tl_age_behind"])}
    tr = ft["tl_trend"]
    out["trend_side"] = np.where(np.isfinite(tr), 2 * np.nan_to_num(tr, nan=0).astype(int) + (ft["side"] > 0), -1)
    return {k: v.astype(np.int16) for k, v in out.items()}


def unit_aggregates(rows: np.ndarray, T: dict, unit: str, period: int, tf: str, coin: str):
    """Counts, week sums (T1..T4 groups) and descriptive sums of one unit (pair rows, repeats allowed)."""
    val = T["valid"][rows]
    v = rows[val]
    roe = T["roe"][v]
    cnt = dict(tf=tf, coin=coin, unit=unit, period=period, n_signals=int(len(rows)),
               n_atr_ok=int(T["ok"][rows].sum()), n_sized=int(T["sized"][rows].sum()),
               n_open=int((T["sized"][rows] & ~T["done"][rows]).sum()), n_trades=int(len(v)),
               n_long=int((T["side"][v] > 0).sum()), sum_roe=float(roe.sum()), sum_roe2=float((roe ** 2).sum()),
               n_win=int((roe > 0).sum()), n_lock_reached=int(T["lock_reached"][v].sum()),
               n_live_ahead=int(np.isfinite(T["tl_touch_ahead"][v]).sum()),
               n_live_behind=int(np.isfinite(T["tl_touch_behind"][v]).sum()),
               sum_ahead=float(T["tl_ahead"][v].sum()), sum_behind=float(T["tl_behind"][v].sum()))
    for t in TESTS:
        cnt[f"n_{t}_1"] = int((T[TEST_FEATURE[t]][v] == 1).sum())
    wk = []
    if len(v):
        parts = {}
        for t in TESTS:
            uw, s = A._week_sums(T["week"][v], roe, T[TEST_FEATURE[t]][v].astype(int))
            for k, arr in s.items():
                parts[f"{t}_{k}"] = arr
        wk.append(pd.DataFrame({"tf": tf, "coin": coin, "unit": unit, "period": period, "week": uw, **parts}))
    desc = []
    if unit in (RANDOM_UNIT, ALL_UNIT) and len(v):
        lr = T["lock_reached"][v].astype(float)
        win = (roe > 0).astype(float)
        for var in DESC_VARS:
            x = T[var][v].astype(np.int64)
            ux, inv = np.unique(x, return_inverse=True)
            desc.append(pd.DataFrame({"tf": tf, "coin": coin, "unit": unit, "period": period, "var": var, "value": ux,
                                      "n": np.bincount(inv, minlength=len(ux)),
                                      "sum_roe": np.bincount(inv, weights=roe, minlength=len(ux)),
                                      "sum_roe2": np.bincount(inv, weights=roe ** 2, minlength=len(ux)),
                                      "n_win": np.bincount(inv, weights=win, minlength=len(ux)),
                                      "n_lock_reached": np.bincount(inv, weights=lr, minlength=len(ux))}))
    return cnt, wk, desc


def pair_table(b: dict, units: dict, tf: str, sizer, P: TL.Params = TL.DEFAULT):
    """Distinct (bar, side) pairs of all units with outcome and features. Returns (keys, T, timings)."""
    keys = np.unique(np.concatenate([u[0].astype(np.int64) * 2 + (u[1] > 0) for u in units.values()]
                                    + [np.zeros(0, np.int64)]))
    pidx = (keys // 2).astype(np.int64)
    pside = np.where(keys % 2 == 1, 1, -1).astype(np.int8)
    t0 = time.time()
    oc = A.outcomes(b, pidx, pside, tf, sizer)
    t1 = time.time()
    lines = TL.lines_for(b["h"], b["l"], b["c"], b["atr"], P)
    ft = TL.features_for(b, pidx, pside, lines=lines)
    t2 = time.time()
    T = dict(idx=pidx, side=pside, ts=b["ts"][pidx], week=sr.period_key(b["ts"][pidx], "week"), **oc)
    for k in TL.FEATURES:
        T[k] = ft[k]
    feat_ok = np.isfinite(ft["tl_break_now"])
    T["feat_ok"] = feat_ok
    T["valid"] = oc["sized"] & oc["done"] & np.isfinite(oc["roe"]) & feat_ok
    T["lock_reached"] = oc["mfe"] >= FIRST_LOCK - 1e-12
    T.update(buckets({**ft, "side": pside}))
    return keys, T, dict(outcomes=round(t1 - t0, 1), features=round(t2 - t1, 1))


# ------------------------------------------------------------------ stage 1 job
def _job(args):
    tf, coin = args
    t0 = time.time()
    L = _lib()
    sizer = PR._sizer()
    names = A.strategy_names(L)
    ci = COINS.index(coin)
    tf_min = int(L.tf_minutes(tf))
    warm = int(L.warmup_bars(tf))
    counts, weeks, descs, info = [], [], [], {"tf": tf, "coin": coin, "series": {}}
    for src, periods in SOURCES:
        ts0 = time.time()
        b, sigs = load_bars(tf, coin, src)
        n = len(b["ts"])
        missing = [nm for nm in names if nm not in sigs]
        if missing:
            raise KeyError(f"{tf} {coin} {src}: strategies missing from the cache: {missing}")
        units, bounds = {}, {}
        for p in periods:
            lo, hi = A.period_bounds(b["ts"], p, warm)
            bounds[p] = (lo, hi)
            for nm in names:
                sg = sigs[nm]
                idx = np.flatnonzero(sg[lo:hi]).astype(np.int64) + lo
                units[(nm, p)] = (idx, sg[idx].astype(np.int8))
            units[(RANDOM_UNIT, p)] = A.random_bars(lo, hi, tf_min, ci, p)
        t1 = time.time()
        keys, T, tim = pair_table(b, units, tf, sizer)
        t2 = time.time()
        store = {k: np.asarray(T[k]) for k in ("idx", "side", "ts", "week", "lev", "sized", "done", "roe", "mfe",
                                                "reason", "valid", "feat_ok")}
        for k, dt in FEAT_STORE.items():
            store[k] = np.nan_to_num(T[k], nan=-1).astype(dt) if dt == np.int8 else T[k].astype(dt)
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
        np.savez(os.path.join(CACHE, f"tl_{tf}_{coin}_{src}.npz"), **store)
        info["series"][src] = dict(
            bars=n, first=str(pd.Timestamp(b["ts"][0])), last=str(pd.Timestamp(b["ts"][-1])), warmup_bars=warm,
            bounds={str(p): dict(lo=lo, hi=hi, eligible_bars=hi - lo,
                                 first_signal_bar=str(pd.Timestamp(b["ts"][lo])) if hi > lo else None,
                                 last_signal_bar=str(pd.Timestamp(b["ts"][hi - 1])) if hi > lo else None)
                    for p, (lo, hi) in bounds.items()},
            pairs=int(len(keys)), pairs_atr_ok=int(T["ok"].sum()), pairs_sized=int(T["sized"].sum()),
            pairs_open_at_end=int((T["sized"] & ~T["done"]).sum()),
            pairs_without_features=int((~T["feat_ok"]).sum()),
            pairs_sized_closed_without_features=int((T["sized"] & T["done"] & ~T["feat_ok"]).sum()),
            seconds=dict(load_and_units=round(t1 - ts0, 1), **tim, aggregate=round(time.time() - t2, 1)))
        del b, sigs, T, store
    info["seconds"] = round(time.time() - t0, 1)
    return (tf, coin, pd.DataFrame(counts), pd.concat(weeks, ignore_index=True) if weeks else pd.DataFrame(),
            pd.concat(descs, ignore_index=True) if descs else pd.DataFrame(), info)


def _map(fn, jobs, procs):
    if procs <= 1:
        for j in jobs:
            yield fn(j)
        return
    with Pool(procs, maxtasksperchild=1) as pool:
        yield from pool.imap_unordered(fn, jobs)


def stage1(procs: int = 4) -> dict:
    _lib()  # signal-code hash check before any work
    os.makedirs(CACHE, exist_ok=True)
    jobs = [(tf, c) for tf in TFS for c in COINS]
    t0 = time.time()
    counts, weeks, descs, infos = [], [], [], []
    for tf, coin, c, w, d, info in _map(_job, jobs, procs):
        counts.append(c); weeks.append(w); descs.append(d); infos.append(info)
        s = info["series"]
        print(f"[{time.time() - t0:6.0f}s] {tf:>3} {coin}: pairs {s['p12']['pairs']}+{s['p3']['pairs']} "
              f"({info['seconds']}s: p12 {s['p12']['seconds']}, p3 {s['p3']['seconds']})", flush=True)
    counts = pd.concat(counts, ignore_index=True)
    weeks = pd.concat(weeks, ignore_index=True)
    descs = pd.concat(descs, ignore_index=True)
    infos.sort(key=lambda r: (ALL_TFS.index(r["tf"]), COINS.index(r["coin"])))
    counts.to_pickle(os.path.join(CACHE, "stage1_counts.pkl"))
    weeks.to_pickle(os.path.join(CACHE, "stage1_weeks.pkl"))
    descs.to_pickle(os.path.join(CACHE, "stage1_desc.pkl"))
    with open(os.path.join(CACHE, "stage1_info.json"), "w") as fh:
        json.dump(A._clean(dict(wall_s=round(time.time() - t0, 1), tfs=TFS, jobs=infos)), fh, indent=1)
    print(f"stage 1 done in {time.time() - t0:.0f}s", flush=True)
    return dict(wall_s=round(time.time() - t0, 1))


# ------------------------------------------------------------------ statistics
def wb_test(test: str, n0, s0, n1, s1, C) -> dict:
    """analysis_sr.week_block_test with the hypothesis direction of ``test`` (A's 'P2' = mean1 - mean0,
    'P1' = mean0 - mean1)."""
    return A.week_block_test("P2" if GOOD[test] == 1 else "P1", n0, s0, n1, s1, C, MIN_GROUP)


def unit_code_map(names: list[str]) -> dict:
    code = {nm: i for i, nm in enumerate(names)}
    code[RANDOM_UNIT], code[ALL_UNIT] = 1000, 1001
    return code


def boot(W: int, unit_code: int, tf: str, period: int):
    return A.boot_counts(W, BOOT_B[period], [BOOT_SEED, int(unit_code), ALL_TFS.index(tf), int(period)]) if W else None


def unit_tests(wk: pd.DataFrame, unit_code: int, tf: str, period: int) -> dict:
    """T1..T4 for one unit / timeframe / period from its week sums pooled over coins."""
    g = wk.groupby("week", sort=True)[[f"{t}_{k}" for t in TESTS for k in ("n0", "s0", "n1", "s1")]].sum()
    C = boot(len(g), unit_code, tf, period)
    return {t: wb_test(t, g[f"{t}_n0"], g[f"{t}_s0"], g[f"{t}_n1"], g[f"{t}_s1"], C) for t in TESTS}


def tests_from_pairs(week, roe, groups: dict, unit_code: int, tf: str, period: int, with_p: bool = True) -> dict:
    """T tests from per-trade arrays (week, roe, {test: 0/1 group}); the bootstrap uses the study's seeds."""
    uw, inv = np.unique(np.asarray(week), return_inverse=True)
    C = boot(len(uw), unit_code, tf, period) if with_p else None
    out = {}
    for t, g in groups.items():
        g = np.asarray(g)
        s = {}
        for lab, sel in (("0", g == 0), ("1", g == 1)):
            s["n" + lab] = np.bincount(inv, weights=sel.astype(float), minlength=len(uw))
            s["s" + lab] = np.bincount(inv, weights=np.where(sel, roe, 0.0), minlength=len(uw))
        r = wb_test(t, s["n0"], s["s0"], s["n1"], s["s1"], C)
        if not with_p:
            r["status"] = "descriptive" if min(r["n0"], r["n1"]) >= MIN_GROUP else "insufficient"
        out[t] = r
    return out


# ------------------------------------------------------------------ stage 2
def stage2(stage1_meta: dict | None = None) -> dict:
    t0 = time.time()
    L = _lib()
    names = A.strategy_names(L)
    counts = pd.read_pickle(os.path.join(CACHE, "stage1_counts.pkl"))
    weeks = pd.read_pickle(os.path.join(CACHE, "stage1_weeks.pkl"))
    descs = pd.read_pickle(os.path.join(CACHE, "stage1_desc.pkl"))
    with open(os.path.join(CACHE, "stage1_info.json")) as fh:
        s1info = json.load(fh)
    code = unit_code_map(names)
    tfs = [tf for tf in ALL_TFS if tf in set(counts["tf"])]

    wk_groups = {k: g for k, g in weeks.groupby(["unit", "tf", "period"], sort=False)}
    tests = {}
    for unit in names + [RANDOM_UNIT, ALL_UNIT]:
        for tf in tfs:
            for p in PERIODS:
                g = wk_groups.get((unit, tf, p))
                if g is None or g.empty:
                    tests[(unit, tf, p)] = {t: wb_test(t, [], [], [], [], None) for t in TESTS}
                else:
                    tests[(unit, tf, p)] = unit_tests(g, code[unit], tf, p)
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
        for tf in tfs:
            r = dict(strategy=nm, tf=tf)
            for p in PERIODS:
                ns, nt = int(cstat(nm, tf, p, "n_signals")), int(cstat(nm, tf, p, "n_trades"))
                r[f"n_signals_p{p}"] = ns
                r[f"n_sized_p{p}"] = int(cstat(nm, tf, p, "n_sized"))
                r[f"n_trades_p{p}"] = nt
                r[f"n_open_excluded_p{p}"] = int(cstat(nm, tf, p, "n_open"))
                r[f"n_unsized_p{p}"] = ns - int(cstat(nm, tf, p, "n_sized"))
                r[f"mean_roe_p{p}"] = cstat(nm, tf, p, "sum_roe") / nt if nt else np.nan
                for t in TESTS:
                    r[f"share_{TEST_FEATURE[t]}_p{p}"] = cstat(nm, tf, p, f"n_{t}_1") / nt if nt else np.nan
                for k, lab in (("n_live_ahead", "share_live_ahead"), ("n_live_behind", "share_live_behind"),
                               ("n_lock_reached", "share_lock_reached"), ("n_long", "share_long")):
                    r[f"{lab}_p{p}"] = cstat(nm, tf, p, k) / nt if nt else np.nan
                r[f"mean_tl_ahead_p{p}"] = cstat(nm, tf, p, "sum_ahead") / nt if nt else np.nan
                r[f"mean_tl_behind_p{p}"] = cstat(nm, tf, p, "sum_behind") / nt if nt else np.nan
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

    # ---------------- the family: tested cells x T1..T4 + random x timeframe x T1..T4
    trial_rows = []
    for _, r in cells[cells["tested"]].iterrows():
        for t in TESTS:
            trial_rows.append(dict(trial_id=f"TL-{r['strategy']}-{r['tf']}-{t}", kind="cell", strategy=r["strategy"],
                                   unit=r["strategy"], tf=r["tf"], test=t, feature=TEST_FEATURE[t],
                                   good_group=GOOD[t], hypothesis=HYPOTHESIS[t]))
    for tf in tfs:
        for t in TESTS:
            trial_rows.append(dict(trial_id=f"TL-RANDOM-{tf}-{t}", kind="random", strategy="", unit=RANDOM_UNIT,
                                   tf=tf, test=t, feature=TEST_FEATURE[t], good_group=GOOD[t], hypothesis=HYPOTHESIS[t]))
    trials = pd.DataFrame(trial_rows)
    for p in PERIODS:
        for k in ("n0", "n1", "mean0", "mean1", "diff", "p", "status", "weeks", "undefined_resamples"):
            trials[f"{k}_p{p}"] = [tests[(u, tf, p)][t][k] for u, tf, t in zip(trials["unit"], trials["tf"], trials["test"])]
        trials[f"n_good_p{p}"] = np.where(trials["good_group"] == 1, trials[f"n1_p{p}"], trials[f"n0_p{p}"])
        trials[f"mean_good_p{p}"] = np.where(trials["good_group"] == 1, trials[f"mean1_p{p}"], trials[f"mean0_p{p}"])
    trials["bootstrap_resamples_p1"] = BOOT_B[1]
    p_bh = np.where(trials["status_p1"] == "ok", trials["p_p1"], 1.0)
    trials["p_for_bh"] = p_bh
    rej, rank, adj = A.bh(p_bh, FDR_Q)
    trials["bh_rank"] = rank
    trials["bh_threshold"] = FDR_Q * rank / len(trials)
    trials["bh_qvalue"] = adj
    trials["pass_p1_bh"] = rej & (trials["diff_p1"] > 0)
    sgn1 = np.sign(trials["diff_p1"])
    trials["pass_p2"] = trials["pass_p1_bh"] & (trials["status_p2"] == "ok") & (np.sign(trials["diff_p2"]) == sgn1) \
        & (trials["p_p2"] < CONFIRM_ALPHA)
    p3_ok = (trials["n0_p3"] >= MIN_GROUP) & (trials["n1_p3"] >= MIN_GROUP)
    trials["verdict_p3"] = np.where(~p3_ok, "no data",
                                    np.where(np.sign(trials["diff_p3"]) == sgn1, "same sign", "opposite sign"))
    trials["pass_p3"] = trials["pass_p2"] & (trials["verdict_p3"] == "same sign")
    trials["candidate"] = trials["pass_p3"]
    for p in PERIODS:
        trials[f"random_diff_p{p}"] = [tests[(RANDOM_UNIT, tf, p)][t]["diff"] for tf, t in zip(trials["tf"], trials["test"])]
        trials[f"random_p_p{p}"] = [tests[(RANDOM_UNIT, tf, p)][t]["p"] for tf, t in zip(trials["tf"], trials["test"])]
    trials["random_same_effect_p1"] = (trials["kind"] == "cell") & (np.sign(trials["random_diff_p1"]) == sgn1) \
        & (trials["random_p_p1"] < 0.05)
    trials["label"] = np.where(
        trials["candidate"] & (trials["kind"] == "random"),
        "random-entry candidate: a property of any entry -> lab filter path (section 6)",
        np.where(trials["candidate"] & trials["random_same_effect_p1"],
                 "candidate, but the random entries show the same effect: market-wide, not the strategy",
                 np.where(trials["candidate"], "candidate (strategy cell) -> Q7 copy-account path only", "")))
    m = trials[trials["kind"] == "cell"].set_index(["strategy", "tf", "test"])
    for t in TESTS:
        for col in ("p_for_bh", "bh_rank", "bh_qvalue", "pass_p1_bh", "pass_p2", "verdict_p3", "pass_p3", "candidate",
                    "random_same_effect_p1"):
            cells[f"{t}_{col}"] = [m.loc[(s, tf, t), col] if (s, tf, t) in m.index else None
                                   for s, tf in zip(cells["strategy"], cells["tf"])]
    t_cells = time.time()

    # ---------------- random entries table
    rrows = []
    for tf in tfs:
        for p in PERIODS:
            sub = counts[(counts["unit"] == RANDOM_UNIT) & (counts["tf"] == tf) & (counts["period"] == p)]
            for scope, s in [("pooled", sub)] + [(c, sub[sub["coin"] == c]) for c in COINS]:
                nt = int(s["n_trades"].sum())
                r = dict(tf=tf, period=p, scope=scope, eligible_bars=int(s["eligible_bars"].sum()),
                         n_sampled=int(s["n_signals"].sum()), n_atr_ok=int(s["n_atr_ok"].sum()),
                         n_sized=int(s["n_sized"].sum()), n_trades=nt, n_open_excluded=int(s["n_open"].sum()),
                         mean_roe=s["sum_roe"].sum() / nt if nt else np.nan,
                         share_long=s["n_long"].sum() / nt if nt else np.nan,
                         share_live_ahead=s["n_live_ahead"].sum() / nt if nt else np.nan,
                         share_live_behind=s["n_live_behind"].sum() / nt if nt else np.nan,
                         share_lock_reached=s["n_lock_reached"].sum() / nt if nt else np.nan)
                for t in TESTS:
                    r[f"share_{TEST_FEATURE[t]}"] = s[f"n_{t}_1"].sum() / nt if nt else np.nan
                if scope == "pooled":
                    x = tests[(RANDOM_UNIT, tf, p)]
                else:                              # per coin: descriptive only, no p
                    g = weeks[(weeks["unit"] == RANDOM_UNIT) & (weeks["tf"] == tf) & (weeks["period"] == p)
                              & (weeks["coin"] == scope)]
                    x = {t: dict(wb_test(t, g[f"{t}_n0"], g[f"{t}_s0"], g[f"{t}_n1"], g[f"{t}_s1"], None),
                                 status="descriptive") for t in TESTS}
                for t in TESTS:
                    for k in ("n0", "n1", "mean0", "mean1", "diff", "p", "status"):
                        r[f"{t}_{k}"] = x[t][k]
                rrows.append(r)
    rnd = pd.DataFrame(rrows)

    # ---------------- descriptive (section 7)
    dsum = descs.groupby(["unit", "tf", "period", "var", "value"])[["n", "sum_roe", "sum_roe2", "n_win",
                                                                   "n_lock_reached"]].sum()
    label_for = {"ahead_bucket": dict(enumerate(DIST_LABELS)), "behind_bucket": dict(enumerate(DIST_LABELS)),
                 "touch_ahead_bucket": TOUCH_LABELS, "touch_behind_bucket": TOUCH_LABELS,
                 "slope_ahead_bucket": SLOPE_LABELS, "slope_behind_bucket": SLOPE_LABELS,
                 "age_ahead_bucket": AGE_LABELS, "age_behind_bucket": AGE_LABELS, "trend_side": TREND_SIDE_LABELS}
    desc = {}
    for tf in tfs:
        desc[tf] = {}
        for p in PERIODS:
            dd = {}
            for unit, lab in ((ALL_UNIT, "strategies_pooled"), (RANDOM_UNIT, "random_entries")):
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
                        tab.append(dict(value=int(val), label=label_for.get(var, {}).get(int(val), str(int(val))),
                                        n=int(nx), share=nx / tot if tot else None, mean_roe=A._num(mean),
                                        sd_roe=A._num(sd), se_roe=A._num(sd / np.sqrt(nx)) if nx > 1 else None,
                                        win_rate=A._num(x["n_win"] / nx) if nx else None,
                                        lock_reached_share=A._num(x["n_lock_reached"] / nx) if nx else None))
                    block[var] = tab
                for t in TESTS:
                    block[f"{t}_pooled"] = {k: A._num(v) for k, v in tests[(unit, tf, p)][t].items()}
                nt = int(cstat(unit, tf, p, "n_trades"))
                block["n_trades"] = nt
                block["mean_roe"] = A._num(cstat(unit, tf, p, "sum_roe") / nt) if nt else None
                dd[lab] = block
            desc[tf][str(p)] = dd
    desc_doc = dict(note="Descriptive only (PREREG section 7): not used for any decision, no correction. "
                         "'strategies_pooled' counts a trade once per strategy that signalled it. Distances in ATR; "
                         "touch / slope / age buckets only for live lines (-1 = no live line); trend_side = trend "
                         "(up / down / none / both) x side. T1..T4_pooled = the primary statistics on all strategies' "
                         "trades of the timeframe pooled, and on the random entries (week-block bootstrap, one-sided).",
                    first_lock_roe=FIRST_LOCK, distance_buckets=DIST_LABELS, by_tf_period=desc)

    # ---------------- candidates and counts by stage
    testable = trials["status_p1"] == "ok"
    p2_tests = int(trials["pass_p1_bh"].sum())
    cand = trials[trials["candidate"]]
    by_test = {}
    for t in TESTS + ("all",):
        sel = trials if t == "all" else trials[trials["test"] == t]
        ok1 = sel["status_p1"] == "ok"
        by_test[t] = dict(
            tests=int(len(sel)), testable_p1=int(ok1.sum()), insufficient_p1=int((~ok1).sum()),
            raw_p_below_005_p1=int((ok1 & (sel["p_p1"] < 0.05) & (sel["diff_p1"] > 0)).sum()),
            hypothesis_direction_p1=f"{int((ok1 & (sel['diff_p1'] > 0)).sum())} / {int(ok1.sum())}",
            hypothesis_direction_p2=f"{int(((sel['status_p2'] == 'ok') & (sel['diff_p2'] > 0)).sum())} / "
                                    f"{int((sel['status_p2'] == 'ok').sum())}",
            hypothesis_direction_p3=f"{int(((sel['status_p3'] == 'ok') & (sel['diff_p3'] > 0)).sum())} / "
                                    f"{int((sel['status_p3'] == 'ok').sum())}",
            pass_p1_bh=int(sel["pass_p1_bh"].sum()), pass_p2=int(sel["pass_p2"].sum()),
            pass_p3=int(sel["pass_p3"].sum()), candidates=int(sel["candidate"].sum()))
    cand_doc = dict(
        definition="period-1 BH (FDR 10%, all tested cells x T1..T4 plus random entries x timeframe x T1..T4) -> "
                   "period-2 same sign and one-sided p < 0.05 -> period-3 same sign (>= 30 trades in both groups, "
                   "else 'no data'). A candidate is not a rule change (PREREG section 6).",
        cells_tested=int(cells["tested"].sum()), cells_total=int(len(cells)),
        cells_tested_by_tf={tf: int(cells[(cells["tf"] == tf) & cells["tested"]].shape[0]) for tf in tfs},
        trials=int(len(trials)), trials_planned=600, random_trials=int((trials["kind"] == "random").sum()),
        insufficient_in_period1=int((~testable).sum()),
        bh_survivors_period1=p2_tests, passing_period2=int(trials["pass_p2"].sum()),
        passing_period3=int(trials["pass_p3"].sum()),
        period3_no_data_among_period2_passers=int((trials["pass_p2"] & (trials["verdict_p3"] == "no data")).sum()),
        chance_expectation=dict(
            raw_p_below_005_p1=round(0.05 * float(testable.sum()), 1),
            bh_note="BH at FDR 10%: if no test has an effect, the chance of one or more survivors is <= 10%",
            period2_if_period1_were_chance=round(0.05 * p2_tests, 2),
            period3_if_period2_were_chance=round(0.5 * 0.05 * p2_tests, 2)),
        min_possible_p_period1=1.0 / (BOOT_B[1] + 1), bh_rank1_threshold=FDR_Q / len(trials) if len(trials) else None,
        by_test=by_test,
        candidates=[{k: A._num(v) for k, v in r.items()} for r in cand.to_dict("records")],
        bh_survivors=[{k: A._num(v) for k, v in r.items()} for r in trials[trials["pass_p1_bh"]].to_dict("records")],
        closest=[{k: A._num(v) for k, v in r.items()} for r in
                 trials[testable & (trials["diff_p1"] > 0)].sort_values("p_p1").head(12).to_dict("records")],
        random_entries=[{k: A._num(v) for k, v in r.items()} for r in rnd[rnd["scope"] == "pooled"][
            ["tf", "period", "n_trades"] + [f"{t}_{k}" for t in TESTS for k in ("diff", "p", "status")]].to_dict("records")])
    ov = overrides()
    rr = dict(note="Robustness re-run with non-default data / outputs: NOT the pre-registered result "
                   "(PREREG_TRENDLINE.md fixes the default data). Same code, seeds, tests and thresholds.",
              overrides=ov) if ov else None
    if rr:
        cand_doc["robustness_rerun"] = rr

    # ---------------- write
    os.makedirs(OUT, exist_ok=True)
    cells.to_csv(os.path.join(OUT, "trendline_cells.csv"), index=False)
    trials.to_csv(os.path.join(OUT, "trendline_trials.csv"), index=False)
    rnd.to_csv(os.path.join(OUT, "trendline_random.csv"), index=False)
    with open(os.path.join(OUT, "trendline_descriptive.json"), "w") as fh:
        json.dump(A._clean(desc_doc), fh, indent=1)
    with open(os.path.join(OUT, "trendline_candidates.json"), "w") as fh:
        json.dump(A._clean(cand_doc), fh, indent=1)

    tot = counts.groupby(["unit", "period"]).sum(numeric_only=True)
    strat = counts[~counts["unit"].isin([RANDOM_UNIT, ALL_UNIT])]
    skipped = dict(
        cells_not_tested=cells.loc[~cells["tested"], ["strategy", "tf", "n_signals_p1"]].to_dict("records"),
        tests_insufficient=[dict(trial_id=r["trial_id"], period=p, n0=r[f"n0_p{p}"], n1=r[f"n1_p{p}"])
                            for r in trials.to_dict("records") for p in PERIODS if r[f"status_p{p}"] != "ok"],
        signals_without_trade={str(p): dict(
            signals=int(strat.loc[strat["period"] == p, "n_signals"].sum()),
            atr_or_next_open_invalid=int((strat.loc[strat["period"] == p, "n_signals"]
                                          - strat.loc[strat["period"] == p, "n_atr_ok"]).sum()),
            not_sized=int((strat.loc[strat["period"] == p, "n_atr_ok"] - strat.loc[strat["period"] == p, "n_sized"]).sum()),
            open_at_data_end_excluded=int(strat.loc[strat["period"] == p, "n_open"].sum()),
            trades=int(strat.loc[strat["period"] == p, "n_trades"].sum())) for p in PERIODS},
        random_without_trade={str(p): dict(
            sampled=int(tot.loc[(RANDOM_UNIT, p), "n_signals"]) if (RANDOM_UNIT, p) in tot.index else 0,
            trades=int(tot.loc[(RANDOM_UNIT, p), "n_trades"]) if (RANDOM_UNIT, p) in tot.index else 0)
            for p in PERIODS})
    meta = dict(
        script="research/entry_study/analysis_trendline.py", git_head=A._git_head(), **check_prereg(),
        prereg_commit=prereg_commit(),
        signal_lock=sweepsig.verify()["prereg_sha256_file"], **code_hashes(),
        params=TL.params_dict(TL.DEFAULT),
        seeds=dict(random_entries=f"part A's draw: np.random.default_rng([{A.RANDOM_SEED}, tf_minutes, coin_index "
                                  f"(BTC,ETH,SOL,DOGE,LTC,BCH = 0..5), period]); choice then side",
                   bootstrap=f"np.random.default_rng([{BOOT_SEED}, unit_code (account-list index 0..35, random 1000, "
                             f"all strategies 1001), tf_index (5m..4h = 0..4), period]); rng.integers(0, W, (B, W)); "
                             f"B = {BOOT_B}; the four tests of one unit and period share the draws"),
        constants=dict(periods=PERIODS, random_n=A.RANDOM_N, bootstrap_resamples=BOOT_B, min_signals=MIN_SIGNALS,
                       min_group=MIN_GROUP, fdr_q=FDR_Q, confirm_alpha=CONFIRM_ALPHA, lookahead_passes=A.PASSES,
                       first_lock_roe=FIRST_LOCK, tests=TEST_FEATURE, good_group=GOOD,
                       proposal=dict(min_effect=MIN_EFFECT, min_good_trades=MIN_GOOD, lev_min_group=LEV_MIN_GROUP,
                                     coin_min_group=COIN_MIN_GROUP)),
        data=dict(periods_1_2=SIG12, period_3=SIG3, cache=CACHE, tfs=tfs),
        timings=dict(stage1=(stage1_meta or {}).get("wall_s", s1info.get("wall_s")),
                     stage2_tests_s=round(t_tests - t0, 1), stage2_cells_s=round(t_cells - t_tests, 1),
                     stage2_total_s=round(time.time() - t0, 1)),
        row_counts=dict(trendline_cells=len(cells), trendline_trials=len(trials), trendline_random=len(rnd),
                        stage1_counts=len(counts), stage1_week_rows=len(weeks), stage1_desc_rows=len(descs)),
        headline=dict(cells_tested=cand_doc["cells_tested"], trials=cand_doc["trials"],
                      insufficient_in_period1=cand_doc["insufficient_in_period1"],
                      bh_survivors_period1=cand_doc["bh_survivors_period1"], passing_period2=cand_doc["passing_period2"],
                      passing_period3=cand_doc["passing_period3"], candidates=len(cand_doc["candidates"])),
        ambiguities=list(AMBIGUITIES), skipped=skipped, jobs=s1info["jobs"])
    if rr:
        meta["robustness_rerun"] = rr
    with open(os.path.join(OUT, "trendline_run_meta.json"), "w") as fh:
        json.dump(A._clean(meta), fh, indent=1)
    print(f"stage 2 done in {time.time() - t0:.0f}s (tests {t_tests - t0:.0f}s, cells {t_cells - t_tests:.0f}s)",
          flush=True)
    print(json.dumps(meta["headline"], indent=1), flush=True)
    return meta


# ------------------------------------------------------------------ checks (sections 6 and 7, candidates only)
def _unit_trades(tf: str, unit: str, period: int, cache: str = None) -> pd.DataFrame:
    """Per-trade rows (valid trades) of one unit / timeframe / period from the stage-1 pair caches."""
    cache = cache or CACHE
    src = "p3" if period == 3 else "p12"
    parts = []
    for coin in COINS:
        z = np.load(os.path.join(cache, f"tl_{tf}_{coin}_{src}.npz"))
        key = f"u__{unit}__p{period}"
        if unit == ALL_UNIT:
            rows = np.concatenate([z[k] for k in z.files if k.startswith("u__") and k.endswith(f"__p{period}")
                                   and not k.startswith(f"u__{RANDOM_UNIT}__")])
        else:
            rows = z[key]
        rows = rows[z["valid"][rows]]
        d = {k: z[k][rows] for k in ("idx", "side", "ts", "week", "lev", "roe") + tuple(TL.FEATURES)}
        d["coin"] = np.full(len(rows), coin)
        parts.append(pd.DataFrame(d))
    return pd.concat(parts, ignore_index=True)


def _diff(test: str, df: pd.DataFrame) -> dict:
    g = df[TEST_FEATURE[test]].to_numpy()
    r0, r1 = df["roe"].to_numpy()[g == 0], df["roe"].to_numpy()[g == 1]
    m0 = float(r0.mean()) if len(r0) else np.nan
    m1 = float(r1.mean()) if len(r1) else np.nan
    return dict(n0=int(len(r0)), n1=int(len(r1)), mean0=m0, mean1=m1,
                diff=(m1 - m0) if GOOD[test] == 1 else (m0 - m1))


def _lev_tiers(test: str, df: pd.DataFrame) -> dict:
    tiers, wsum, wtot = [], 0.0, 0
    for lev, g in df.groupby("lev"):
        d = _diff(test, g)
        use = d["n0"] >= LEV_MIN_GROUP and d["n1"] >= LEV_MIN_GROUP
        tiers.append(dict(lev=float(lev), used=use, **d))
        if use:
            wsum += d["diff"] * (d["n0"] + d["n1"])
            wtot += d["n0"] + d["n1"]
    return dict(tiers=tiers, weighted_diff=wsum / wtot if wtot else np.nan, trades_used=wtot)


def _variant_tests(tf: str, unit: str, test: str, P: TL.Params, code: int) -> dict:
    """One sensitivity variant: features recomputed with P on the cached pairs, the test in periods 1-3
    (p for periods 1 / 2 with the study's bootstrap; period 3 difference only)."""
    acc = {p: ([], [], []) for p in PERIODS}
    for src, periods in SOURCES:
        for coin in COINS:
            b, _ = load_bars(tf, coin, src)
            z = np.load(os.path.join(CACHE, f"tl_{tf}_{coin}_{src}.npz"))
            lines = TL.lines_for(b["h"], b["l"], b["c"], b["atr"], P)
            for p in periods:
                if unit == ALL_UNIT:
                    rows = np.concatenate([z[k] for k in z.files if k.startswith("u__") and k.endswith(f"__p{p}")
                                           and not k.startswith(f"u__{RANDOM_UNIT}__")])
                else:
                    rows = z[f"u__{unit}__p{p}"]
                rows = rows[z["valid"][rows]]
                ft = TL.features_for(b, z["idx"][rows], z["side"][rows], lines=lines, P=P)
                acc[p][0].append(z["week"][rows]); acc[p][1].append(z["roe"][rows]); acc[p][2].append(ft[TEST_FEATURE[test]])
    out = {}
    for p in PERIODS:
        week, roe, g = (np.concatenate(x) for x in acc[p])
        ok = np.isfinite(g)
        r = tests_from_pairs(week[ok], roe[ok], {test: g[ok].astype(int)}, code, tf, p, with_p=(p != 3))[test]
        out[str(p)] = {k: A._num(v) for k, v in r.items()}
    return out


def checks(binance_out: str | None = None) -> dict:
    """Section 6 proposal conditions and the section 7 candidate-only tables, for every candidate."""
    L = _lib()
    names = A.strategy_names(L)
    code = unit_code_map(names)
    trials = pd.read_csv(os.path.join(OUT, "trendline_trials.csv"))
    cand = trials[trials["candidate"].astype(bool)]
    binance_out = binance_out or os.path.join(HERE, "out_binance")
    bpath = os.path.join(binance_out, "trendline_trials.csv")
    btr = pd.read_csv(bpath).set_index("trial_id") if os.path.exists(bpath) else None
    res = []
    for r in cand.to_dict("records"):
        t, tf, unit = r["test"], r["tf"], r["unit"]
        sign = np.sign(r["diff_p1"])
        c = dict(trial_id=r["trial_id"], kind=r["kind"], tf=tf, test=t, unit=unit, label=r["label"])
        per = {p: _unit_trades(tf, unit, p) for p in PERIODS}
        # (1) Binance re-run
        if btr is not None and r["trial_id"] in btr.index:
            x = btr.loc[r["trial_id"]]
            ok = all(np.sign(x[f"diff_p{p}"]) == sign and x[f"status_p{p}"] == "ok" and x[f"p_p{p}"] < 0.05
                     for p in (1, 2))
            c["binance"] = dict(diff_p1=x["diff_p1"], p_p1=x["p_p1"], diff_p2=x["diff_p2"], p_p2=x["p_p2"],
                                n0_p1=x["n0_p1"], n1_p1=x["n1_p1"], n0_p2=x["n0_p2"], n1_p2=x["n1_p2"], passed=bool(ok))
        else:
            c["binance"] = dict(passed=False, note=f"no Binance re-run output at {bpath}")
        # (2) leverage tiers
        lv = {str(p): _lev_tiers(t, per[p]) for p in (1, 2)}
        c["leverage"] = dict(by_period=lv, passed=bool(all(np.sign(lv[str(p)]["weighted_diff"]) == sign
                                                            for p in (1, 2))))
        # (3) effect size, (4) trades left, (6) loss note
        c["effect"] = dict(diff_p1=r["diff_p1"], diff_p2=r["diff_p2"],
                           passed=bool(r["diff_p1"] >= MIN_EFFECT and r["diff_p2"] >= MIN_EFFECT))
        c["good_trades"] = dict(n_good_p1=int(r["n_good_p1"]), n_good_p2=int(r["n_good_p2"]),
                                passed=bool(r["n_good_p1"] >= MIN_GOOD[1] and r["n_good_p2"] >= MIN_GOOD[2]))
        c["good_side_loses"] = bool(r["mean_good_p1"] <= 0 or r["mean_good_p2"] <= 0)
        # (5) coins
        coin_rows = []
        for coin in COINS:
            for p in PERIODS:
                d = _diff(t, per[p][per[p]["coin"] == coin])
                coin_rows.append(dict(coin=coin, period=p, **d))
        eligible = [x for x in coin_rows if x["period"] == 1 and x["n0"] >= COIN_MIN_GROUP and x["n1"] >= COIN_MIN_GROUP]
        same = sum(1 for x in eligible if np.sign(x["diff"]) == sign)
        c["coins"] = dict(rows=coin_rows, eligible_p1=len(eligible), same_sign_p1=same,
                          passed=bool(len(eligible) > 0 and same > len(eligible) / 2))
        c["proposal_conditions_passed"] = bool(c["binance"]["passed"] and c["leverage"]["passed"]
                                               and c["effect"]["passed"] and c["good_trades"]["passed"]
                                               and c["coins"]["passed"])
        # section 7: long / short, DOGE 2021-08, sensitivity
        c["by_side"] = [dict(side=s, period=p, **_diff(t, per[p][per[p]["side"] == s])) for s in (1, -1) for p in PERIODS]
        p1 = per[1]
        ts = pd.to_datetime(p1["ts"])
        drop = (p1["coin"] == "DOGEUSD") & (ts >= "2021-08-01") & (ts < "2021-09-01")
        c["period1_without_doge_2021_08"] = dict(dropped=int(drop.sum()), **_diff(t, p1[~drop]))
        sens = []
        for field, val in VARIANTS:
            P = TL.Params(**{**TL.params_dict(TL.DEFAULT), field: val})
            sens.append(dict(change=f"{field} = {val}", **_variant_tests(tf, unit, t, P, code[unit])))
        c["sensitivity"] = dict(note="One definition change at a time; never adopted (a change needs a v2 "
                                     "pre-registration).", rows=sens)
        res.append(c)
    doc = dict(note="PREREG_TRENDLINE.md sections 6 and 7, candidates only. Not part of the 600-test family; the "
                    "trial ledger lists them separately as checks (trendline_trials_checks.csv).",
               candidates=len(cand), checks=res, binance_trials=bpath if btr is not None else None)
    with open(os.path.join(OUT, "trendline_checks.json"), "w") as fh:
        json.dump(A._clean(doc), fh, indent=1)
    ledger = []
    for c in res:
        for chk in ("binance", "leverage", "effect", "good_trades", "coins"):
            ledger.append(dict(trial_id=f"{c['trial_id']}-check-{chk}", of=c["trial_id"], kind="check", check=chk,
                               passed=c[chk]["passed"]))
        for s in c["sensitivity"]["rows"]:
            ledger.append(dict(trial_id=f"{c['trial_id']}-sens-{s['change'].replace(' ', '')}", of=c["trial_id"],
                               kind="check", check="sensitivity " + s["change"], passed=None))
    pd.DataFrame(ledger, columns=["trial_id", "of", "kind", "check", "passed"]).to_csv(
        os.path.join(OUT, "trendline_trials_checks.csv"), index=False)
    print(f"checks: {len(cand)} candidates, proposal conditions passed by "
          f"{sum(c['proposal_conditions_passed'] for c in res)}", flush=True)
    return doc


# ------------------------------------------------------------------ command line
def _apply_overrides(argv: list[str]) -> list[str]:
    """Strip --sig12 / --sig3 / --out / --cache / --tfs from argv, set the module settings and env vars (so Pool
    workers see them under any start method). Returns the remaining argv."""
    global SIG12, SIG3, OUT, CACHE, TFS
    flags = {"--sig12": ("TL_SIG12", True), "--sig3": ("TL_SIG3", True), "--out": ("TL_OUT", True),
             "--cache": ("TL_CACHE", True), "--tfs": ("TL_TFS", False)}
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
    SIG12 = os.path.abspath(os.environ.get("TL_SIG12") or DEFAULT_SIG12)
    SIG3 = os.path.abspath(os.environ.get("TL_SIG3") or DEFAULT_SIG3)
    OUT = os.path.abspath(os.environ.get("TL_OUT") or DEFAULT_OUT)
    CACHE = os.path.abspath(os.environ.get("TL_CACHE") or DEFAULT_CACHE)
    TFS = tuple(os.environ.get("TL_TFS").split(",")) if os.environ.get("TL_TFS") else ALL_TFS
    bad = [tf for tf in TFS if tf not in ALL_TFS]
    if bad:
        raise SystemExit(f"unknown timeframes {bad}")
    ov = overrides()
    if ov:
        if ({"sig12", "sig3", "tfs"} & set(ov)) and not {"out", "cache"} <= set(ov):
            raise SystemExit("a re-run on other data must name its own --out and --cache (the defaults hold the "
                             "pre-registered run)")
        print(f"robustness re-run, not the pre-registered result: {json.dumps(ov)}", flush=True)
    return rest


def main(argv: list[str]) -> None:
    pr = check_prereg()
    if not pr["prereg_hash_ok"]:
        raise SystemExit(f"PREREG_TRENDLINE.md does not match PREREG_TRENDLINE.sha256 "
                         f"({pr['prereg_sha256_now']} != {pr['prereg_sha256_file']}): stopped")
    argv = _apply_overrides(list(argv))
    cmd = argv[1] if len(argv) > 1 else ""
    procs = int(argv[2]) if len(argv) > 2 and cmd in ("run", "stage1") else 4
    if cmd == "run":
        m = stage1(procs)
        stage2(m)
    elif cmd == "stage1":
        stage1(procs)
    elif cmd == "stage2":
        stage2()
    elif cmd == "checks":
        checks(argv[2] if len(argv) > 2 else None)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv)
