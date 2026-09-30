"""Period-3 locked-signal cache (PREREG_ENTRY.md section 1: period 3 = 2020-01-01 .. 2021-07-31).

    python3 research/entry_study/final_signals.py build <out_dir> [procs]
    SWEEP_DATA=<sweep data> python3 research/entry_study/final_signals.py check <out_dir> <ref_signals_dir>

``build`` writes ``<out_dir>/sig_<tf>_<COIN>.npz`` in the format of the period-1/2 cache
(``research/paper_rules/rules_bt.py signals``): ts (int64 ns UTC bar open), o, h, l, c, atr (ATR14
of the bar), s__<NAME> (int8 +1/-1/0 on the signal bar; entry is the next bar's open), plus v
(volume). Bars come from ``data/pre2021`` (Binance USDT-M monthly klines, 2020-01 .. 2021-08).

How the bars are built, mirroring the sweep data (checked in ``check``):
  * sweepdata 15m/30m/1h/4h == ``resample_ohlcv(5m)`` exactly, partial bins from data gaps kept,
    and the first / last bin dropped when the 5m series starts after its open / ends before its
    close. The same edge rule is applied here to every timeframe (``trim_partial_edges``).
  * 5m, 15m, 1h, 4h are read from the native files; each native higher-TF file is asserted to have
    the same bar times and OHLC as the resampled 5m file (native volume kept; the few bins where it
    differs from the 5m sum are recorded). 30m has no native file and is ``resample_ohlcv(5m, "30m")``.
``check`` writes out/final_signals_{check.json,overlap.csv,counts.csv}: (a) bars and warm-up per
file, (b) agreement with the period-1/2 cache on the bars both hold (2021-05/06 .. 2021-08-31) plus
a code-path control (this module fed the sweep bars reproduces that cache), (c) period-3 signal
rates vs a same-length slice of period 1.

Signals: ``L.compute_signals(strict=True)`` on the whole series (the locked code is causal), DOGE =
DOGE_L - DOGE_S as in ``rules_bt._signals_job``. The file keeps every bar through 2021-08-31, so a
period-3 trade can be followed past 2021-08-01. Signals on bars from 2021-08-01 on are NOT period 3
(they belong to period 1, whose signals come from the period-1/2 cache).
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
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "paper_rules"))
warnings.filterwarnings("ignore")

from paperbot import sweepsig  # noqa: E402
from paperbot.sigservice import doge_join  # noqa: E402
import rules_bt as RB  # noqa: E402

PRE2021 = os.path.join(ROOT, "data", "pre2021")
OUT = os.path.join(HERE, "out")
TFS = ("5m", "15m", "30m", "1h", "4h")
COINS = RB.COINS
NATIVE = ("5m", "15m", "1h", "4h")
PERIODS = {1: ("2021-08-01", "2024-07-01"), 2: ("2024-07-01", "2026-09-30"), 3: ("2020-01-01", "2021-08-01")}
CLEAN_FROM = "2021-07-01"   # overlap check: the period-1/2 DOGE bars before this are corrupted


# ---------------------------------------------------------------------------------------------
# bars
# ---------------------------------------------------------------------------------------------
def _path(data_dir: str, tf: str, coin: str) -> str:
    return os.path.join(data_dir, f"{coin.lower()}-{tf}.csv.gz")


def trim_partial_edges(df: pd.DataFrame, df5: pd.DataFrame, tf: str) -> tuple[pd.DataFrame, list[str]]:
    """Drop the first bin when the 5m series starts after its open, and the last bin when the 5m
    series ends before its close (the series starts / ends inside the bin). Bins that are partial
    only because of missing 5m bars (data gaps, also at the edges) are kept, as in the sweep data
    (sweep DOGE 30m keeps 2021-01-01 00:00 with 5 of 6 5m bars: 00:20 missing, series starts 00:00)."""
    if tf == "5m" or df.empty:
        return df, []
    width = pd.Timedelta(minutes=sweepsig.lib().tf_minutes(tf))
    full = int(width / pd.Timedelta(minutes=5))
    t5 = df5["ts"]
    first5, end5 = t5.iloc[0], t5.iloc[-1] + pd.Timedelta(minutes=5)
    dropped, keep = [], np.ones(len(df), bool)
    for pos in sorted({0, len(df) - 1}):
        t0 = df["ts"].iloc[pos]
        if t0 < first5 or t0 + width > end5:
            n5 = int(((t5 >= t0) & (t5 < t0 + width)).sum())
            keep[pos] = False
            dropped.append(f"{t0.isoformat()} ({n5}/{full} 5m bars)")
    out = df.loc[keep].reset_index(drop=True)
    out.attrs.update(df.attrs)
    return out, dropped


def load_bars(L, tf: str, coin: str, data_dir: str = PRE2021) -> pd.DataFrame:
    """Bars of one coin/timeframe from data/pre2021, built like the sweep data (module docstring)."""
    df5 = L.read_ohlcv(_path(data_dir, "5m", coin))
    ref, dropped = trim_partial_edges(L.resample_ohlcv(df5, tf), df5, tf) if tf != "5m" else (df5, [])
    if tf in NATIVE and tf != "5m":
        df, dropped = trim_partial_edges(L.read_ohlcv(_path(data_dir, tf, coin)), df5, tf)
        if len(df) != len(ref) or not (df["ts"].to_numpy() == ref["ts"].to_numpy()).all():
            raise ValueError(f"{coin} {tf}: native bars ({len(df)}) and resampled 5m ({len(ref)}) differ in time")
        for k in ("open", "high", "low", "close"):
            if not np.allclose(df[k].to_numpy(float), ref[k].to_numpy(float), rtol=1e-12, atol=0):
                raise ValueError(f"{coin} {tf}: native {k} differs from resampled 5m")
        # Binance's own higher-TF klines differ from the sum of its 5m volumes in a few bins
        # (<= 2 per file, <= 2e-4 relative); the native volume is kept and the difference recorded.
        vn, vr = df["volume"].to_numpy(float), ref["volume"].to_numpy(float)
        vrel = np.abs(vn - vr) / np.abs(vr).clip(1e-12)
        vbad = (np.abs(vn - vr) > 1e-9) & (vrel > 1e-9)
        vol_note = dict(bins=int(vbad.sum()), max_rel=float(vrel.max()) if len(vrel) else 0.0)
        source = f"native {os.path.basename(_path(data_dir, tf, coin))} (OHLC == resampled 5m)"
    elif tf == "5m":
        df, source, vol_note = df5, f"native {os.path.basename(_path(data_dir, tf, coin))}", None
    else:
        df, source, vol_note = ref, f"resample_ohlcv({os.path.basename(_path(data_dir, '5m', coin))}, {tf})", None
    df = df.reset_index(drop=True)
    df.attrs.update(tf=tf, sym=coin, source=source, dropped_edges=dropped, volume_vs_5m=vol_note)
    return df


# ---------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------
def content_digest(arrays: dict) -> str:
    """sha256 over the arrays in key order (the npz zip itself carries write times)."""
    h = hashlib.sha256()
    for k in sorted(arrays):
        a = np.ascontiguousarray(arrays[k])
        h.update(k.encode()); h.update(str(a.dtype).encode()); h.update(a.tobytes())
    return h.hexdigest()


def signal_arrays(L, df: pd.DataFrame, tf: str, coin: str) -> dict:
    import fg_indicators as fg
    raw = L.compute_signals({coin: df}, tf, list(L.NAMES), strict=True)
    sig = {n: raw[n][coin] for n in L.NAMES if n not in ("DOGE_L", "DOGE_S")}
    sig["DOGE"] = doge_join(raw["DOGE_L"][coin], raw["DOGE_S"][coin])  # DOGE_S is already -1 on shorts
    atr = fg.atr(df, 14).to_numpy(float)
    return dict(ts=RB._ns(df["ts"]), o=df["open"].to_numpy(float), h=df["high"].to_numpy(float),
                l=df["low"].to_numpy(float), c=df["close"].to_numpy(float), v=df["volume"].to_numpy(float),
                atr=atr, **{f"s__{k}": v for k, v in sig.items()})


def _job(args):
    tf, coin, out_dir, data_dir = args
    L = sweepsig.lib()
    t0 = time.time()
    df = load_bars(L, tf, coin, data_dir)
    t1 = time.time()
    arrs = signal_arrays(L, df, tf, coin)
    t2 = time.time()
    np.savez_compressed(os.path.join(out_dir, f"sig_{tf}_{coin}.npz"), **arrs)
    return dict(tf=tf, coin=coin, bars=len(df), first=str(df["ts"].iloc[0]), last=str(df["ts"].iloc[-1]),
                source=df.attrs["source"], dropped_edges=df.attrs["dropped_edges"],
                volume_vs_5m=df.attrs["volume_vs_5m"], load_s=round(t1 - t0, 1),
                signals_s=round(t2 - t1, 1), total_s=round(time.time() - t0, 1), digest=content_digest(arrs))


def build(out_dir: str, procs: int = 4, data_dir: str = PRE2021) -> list[dict]:
    os.makedirs(out_dir, exist_ok=True)
    sweepsig.lib()  # hash check before any work
    jobs = [(tf, c, out_dir, data_dir) for tf in TFS for c in COINS]  # 5m first: longest jobs start first
    t0 = time.time()
    rows = []
    with Pool(procs) as p:
        for r in p.imap_unordered(_job, jobs):
            rows.append(r)
            print(f"[{time.time() - t0:6.0f}s] {r['tf']:>3} {r['coin']}: {r['bars']} bars {r['first']} .. "
                  f"{r['last']}  load {r['load_s']}s signals {r['signals_s']}s  dropped {r['dropped_edges']}",
                  flush=True)
    rows.sort(key=lambda r: (TFS.index(r["tf"]), COINS.index(r["coin"])))
    man = dict(built_utc=pd.Timestamp.now(tz="UTC").isoformat(), data_dir=os.path.relpath(data_dir, ROOT),
               locked_code=sweepsig.verify()["prereg_sha256_file"], wall_s=round(time.time() - t0, 1), files=rows)
    for d in (out_dir, OUT):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "final_signals_manifest.json"), "w") as fh:
            json.dump(man, fh, indent=1)
    print(f"done: {len(rows)} files in {time.time() - t0:.0f}s", flush=True)
    return rows


# ---------------------------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------------------------
def _load(d: str, tf: str, coin: str) -> dict:
    z = np.load(os.path.join(d, f"sig_{tf}_{coin}.npz"))
    return {k: z[k] for k in z.files}


def _names(b: dict) -> list[str]:
    return [k[3:] for k in b if k.startswith("s__")]


def _bounds(ts: np.ndarray, period: tuple[str, str], warm: int) -> tuple[int, int]:
    lo = max(int(np.searchsorted(ts, pd.Timestamp(period[0]).value)), warm)
    hi = int(np.searchsorted(ts, pd.Timestamp(period[1]).value))
    return lo, max(lo, hi)


def check_sweep_30m(L, sweep_full: str) -> list[dict]:
    """The rule used for 30m, applied to the sweep data's own 5m, must give the sweep 30m file."""
    out = []
    for c in COINS:
        d5 = L.read_ohlcv(os.path.join(sweep_full, f"{c.lower()}-5m.csv"))
        mine, dropped = trim_partial_edges(L.resample_ohlcv(d5, "30m"), d5, "30m")
        theirs = L.read_ohlcv(os.path.join(sweep_full, f"{c.lower()}-30m.csv"))
        same_ts = len(mine) == len(theirs) and bool((mine["ts"].to_numpy() == theirs["ts"].to_numpy()).all())
        dif = {k: float(np.max(np.abs(mine[k].to_numpy() - theirs[k].to_numpy()) / np.abs(theirs[k].to_numpy()).clip(1e-12)))
               if same_ts else None for k in ("open", "high", "low", "close", "volume")}
        out.append(dict(coin=c, bars=len(theirs), same_ts=same_ts, max_rel_diff=dif, dropped_edges=dropped))
    return out


def _sweep_volume(tf: str, coin: str, ts_b: np.ndarray):
    """Volume of the period-1/2 bars (not in that cache) from the sweep CSV, aligned to ts_b."""
    sw = os.environ.get("SWEEP_DATA")
    p = os.path.join(sw or "", "full", f"{coin.lower()}-{tf}.csv")
    if not sw or not os.path.exists(p):
        return None
    d = pd.read_csv(p, usecols=["ts", "volume"])
    t = pd.to_datetime(d["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)
    v = pd.Series(d["volume"].to_numpy(float), index=t)
    v = v[~v.index.duplicated(keep="last")]
    return v.reindex(ts_b).to_numpy(float)


def _pm1_match(sa: np.ndarray, sb: np.ndarray) -> int:
    """Signals of sa with a same-sign signal of sb on the same bar or one bar either side."""
    n = 0
    for k in np.flatnonzero(sa):
        if (sb[max(0, k - 1):k + 2] == sa[k]).any():
            n += 1
    return n


def _overlap_rows(A, B, ia, ib, vol_b, names, **key) -> list[dict]:
    rel = A["c"][ia] / B["c"][ib] - 1.0
    hrel = A["h"][ia] / B["h"][ib] - 1.0
    lrel = A["l"][ia] / B["l"][ib] - 1.0
    arel = A["atr"][ia] / B["atr"][ib] - 1.0
    base = dict(key, n_bars=len(ia), first=str(pd.Timestamp(A["ts"][ia[0]])), last=str(pd.Timestamp(A["ts"][ia[-1]])),
                close_equal_share=float(np.mean(A["c"][ia] == B["c"][ib])),
                close_absrel_bp_median=float(np.median(np.abs(rel)) * 1e4),
                close_absrel_bp_p99=float(np.quantile(np.abs(rel), 0.99) * 1e4),
                close_absrel_bp_max=float(np.max(np.abs(rel)) * 1e4),
                close_rel_bp_mean=float(np.mean(rel) * 1e4),
                high_absrel_bp_median=float(np.median(np.abs(hrel)) * 1e4),
                low_absrel_bp_median=float(np.median(np.abs(lrel)) * 1e4),
                atr_absrel_pct_median=float(np.nanmedian(np.abs(arel)) * 100))
    if vol_b is not None:
        va, vb = A["v"][ia], vol_b[ib]
        ok = np.isfinite(vb) & (vb > 0) & (va > 0)
        base.update(volume_ratio_median=float(np.median(va[ok] / vb[ok])) if ok.any() else None,
                    logvolume_corr=float(np.corrcoef(np.log(va[ok]), np.log(vb[ok]))[0, 1]) if ok.sum() > 2 else None)
    rows = []
    for n in names:
        sa, sb = A[f"s__{n}"][ia], B[f"s__{n}"][ib]
        u = (sa != 0) | (sb != 0)
        rows.append(dict(base, strategy=n, bar_agree=float(np.mean(sa == sb)),
                         n_sig_pre2021=int(np.count_nonzero(sa)), n_sig_cache=int(np.count_nonzero(sb)),
                         n_union=int(u.sum()), n_both_same=int(((sa == sb) & u).sum()),
                         n_pre2021_matched_pm1=_pm1_match(sa, sb)))
    return rows


def _repro_job(args):
    """Control for the code path: this module's bar building + signal_arrays, fed the sweep bars,
    must reproduce the period-1/2 cache (built by rules_bt._signals_job) bit for bit."""
    tf, coin, ref_dir = args
    L = sweepsig.lib()
    full = os.path.join(os.environ["SWEEP_DATA"], "full")
    d5 = L.read_ohlcv(os.path.join(full, f"{coin.lower()}-5m.csv"))
    if tf == "30m":
        df, _ = trim_partial_edges(L.resample_ohlcv(d5, tf), d5, tf)
    else:
        df = L.read_ohlcv(os.path.join(full, f"{coin.lower()}-{tf}.csv"))
    df = df[df["ts"] < pd.Timestamp(RB.WINDOWS["cf"][1], tz="UTC")].reset_index(drop=True)
    df.attrs["tf"] = tf
    arr = signal_arrays(L, df, tf, coin)
    B = _load(ref_dir, tf, coin)
    same_len = len(arr["ts"]) == len(B["ts"])
    diff = [k for k in B if not (same_len and np.array_equal(arr[k], B[k], equal_nan=k in ("atr", "o", "h", "l", "c")))]
    return dict(tf=tf, coin=coin, bars=len(B["ts"]), identical_keys=len(B) - len(diff), keys=len(B), differing=diff)


def _split_job(args):
    """Split the (b) disagreement: signals on the Binance bars cut to start where the period-1/2
    cache starts (T) vs (i) the full Binance history = start-date effect only, and (ii) the cache =
    data-source effect only. Compared on bars >= CLEAN_FROM, past the warm-up of both series."""
    tf, coin, out_dir, ref_dir = args
    L = sweepsig.lib()
    A, B = _load(out_dir, tf, coin), _load(ref_dir, tf, coin)
    df = load_bars(L, tf, coin)
    df = df[RB._ns(df["ts"]) >= B["ts"][0]].reset_index(drop=True)
    df.attrs["tf"] = tf
    T = signal_arrays(L, df, tf, coin)
    warm = L.warmup_bars(tf)
    rows = []
    for other, lab in ((A, "start_effect"), (B, "data_effect")):
        _, it, io = np.intersect1d(T["ts"], other["ts"], assume_unique=True, return_indices=True)
        m = (it >= warm) & (io >= warm) & (T["ts"][it] >= pd.Timestamp(CLEAN_FROM).value)
        it, io = it[m], io[m]
        for n in _names(B):
            st, so = T[f"s__{n}"][it], other[f"s__{n}"][io]
            u = (st != 0) | (so != 0)
            rows.append(dict(tf=tf, coin=coin, effect=lab, strategy=n, n_bars=len(it), n_union=int(u.sum()),
                             n_both_same=int(((st == so) & u).sum()), n_sig_T=int(np.count_nonzero(st)),
                             n_T_matched_pm1=_pm1_match(st, so)))
    return rows


def check(out_dir: str, ref_dir: str, report_dir: str = OUT, repro_tfs=("30m", "4h"), procs: int = 4) -> dict:
    L = sweepsig.lib()
    os.makedirs(report_dir, exist_ok=True)
    res: dict = {"a_bars": [], "b_overlap_tf": {}, "c_counts_flags": {}}
    ov_rows, cnt_rows = [], []
    p3_days = (pd.Timestamp(PERIODS[3][1]) - pd.Timestamp(PERIODS[3][0])).days
    p1_slice = (PERIODS[1][0], str((pd.Timestamp(PERIODS[1][0]) + pd.Timedelta(days=p3_days)).date()))
    res["c_p1_slice"] = p1_slice
    for tf in TFS:
        warm = L.warmup_bars(tf)
        bar_days = L.tf_minutes(tf) / 1440.0
        cnt = {}
        for coin in COINS:
            A, B = _load(out_dir, tf, coin), _load(ref_dir, tf, coin)
            names = _names(B)
            assert _names(A) == names, (tf, coin, "strategy keys differ from the period-1/2 cache")
            ts = A["ts"]
            lo3, hi3 = _bounds(ts, PERIODS[3], warm)
            # (a)
            res["a_bars"].append(dict(
                tf=tf, coin=coin, bars=len(ts), first=str(pd.Timestamp(ts[0])), last=str(pd.Timestamp(ts[-1])),
                warmup_bars=warm, first_after_warmup=str(pd.Timestamp(ts[warm])) if len(ts) > warm else None,
                p3_first_signal_bar=str(pd.Timestamp(ts[lo3])), p3_signal_bars=hi3 - lo3,
                p3_days=round((hi3 - lo3) * bar_days, 1),
                gaps=int((np.diff(ts) != L.tf_minutes(tf) * 60_000_000_000).sum()),
                atr_nan_after_warmup=int((~np.isfinite(A["atr"][warm:])).sum()),
                nonpos_prices=int((np.c_[A["o"], A["h"], A["l"], A["c"]] <= 0).sum()),
                hl_bad=int(((A["h"] < np.maximum(A["o"], A["c"])) | (A["l"] > np.minimum(A["o"], A["c"]))).sum()),
                zero_volume_bars=int((A["v"] <= 0).sum()),
                p3_signals=int(sum(np.count_nonzero(A[f"s__{n}"][lo3:hi3]) for n in names))))
            # (b) overlap past both warm-ups; "all" and "clean" (from 2021-07-01: the cache's DOGE
            # bars before 2021-07 contain cross-venue corruption, up to +-200% off Binance)
            _, ia0, ib0 = np.intersect1d(ts, B["ts"], assume_unique=True, return_indices=True)
            m0 = (ia0 >= warm) & (ib0 >= warm)
            vol_b = _sweep_volume(tf, coin, B["ts"])
            for win, t_from in (("all", None), ("clean", CLEAN_FROM)):
                m = m0 if t_from is None else m0 & (ts[ia0] >= pd.Timestamp(t_from).value)
                ia, ib = ia0[m], ib0[m]
                if len(ia):
                    ov_rows += _overlap_rows(A, B, ia, ib, vol_b, names, tf=tf, coin=coin, window=win)
            # (c) counts: period 3 (this cache) vs same-length slice of period 1 (period-1/2 cache)
            lo1, hi1 = _bounds(B["ts"], p1_slice, warm)
            for n in names:
                s3, s1 = A[f"s__{n}"][lo3:hi3], B[f"s__{n}"][lo1:hi1]
                c_ = cnt.setdefault(n, dict(n3=0, l3=0, d3=0.0, n1=0, l1=0, d1=0.0))
                c_["n3"] += int(np.count_nonzero(s3)); c_["l3"] += int((s3 > 0).sum()); c_["d3"] += (hi3 - lo3) * bar_days
                c_["n1"] += int(np.count_nonzero(s1)); c_["l1"] += int((s1 > 0).sum()); c_["d1"] += (hi1 - lo1) * bar_days
        for n, c_ in cnt.items():
            r3 = c_["n3"] / c_["d3"] if c_["d3"] else np.nan
            r1 = c_["n1"] / c_["d1"] if c_["d1"] else np.nan
            cnt_rows.append(dict(tf=tf, strategy=n, p3_signals=c_["n3"], p3_coin_days=round(c_["d3"], 1),
                                 p3_per_coin_day=r3, p1slice_signals=c_["n1"], p1slice_coin_days=round(c_["d1"], 1),
                                 p1slice_per_coin_day=r1, ratio=r3 / r1 if r1 else np.nan,
                                 p3_long_share=c_["l3"] / c_["n3"] if c_["n3"] else np.nan,
                                 p1slice_long_share=c_["l1"] / c_["n1"] if c_["n1"] else np.nan))
    ov = pd.DataFrame(ov_rows)
    cn = pd.DataFrame(cnt_rows)
    ov.to_csv(os.path.join(report_dir, "final_signals_overlap.csv"), index=False)
    cn.to_csv(os.path.join(report_dir, "final_signals_counts.csv"), index=False)
    bar_cols = ["coin", "n_bars", "first", "last", "close_equal_share", "close_absrel_bp_median",
                "close_absrel_bp_p99", "close_absrel_bp_max", "close_rel_bp_mean", "high_absrel_bp_median",
                "low_absrel_bp_median", "atr_absrel_pct_median", "volume_ratio_median", "logvolume_corr"]
    for (win, tf), g in ov.groupby(["window", "tf"], sort=False):
        bars = g.drop_duplicates("coin")
        by_s = g.groupby("strategy")[["n_union", "n_both_same"]].sum()
        by_s = (by_s["n_both_same"] / by_s["n_union"].replace(0, np.nan)).sort_values()
        res["b_overlap_tf"].setdefault(win, {})[tf] = dict(
            coins=bars[[c for c in bar_cols if c in bars]].round(4).to_dict("records"),
            bar_agree_all=float((g["bar_agree"] * g["n_bars"]).sum() / g["n_bars"].sum()),
            signal_agree_union=float(g["n_both_same"].sum() / max(1, g["n_union"].sum())),
            pre2021_signals_same_bar=float(g["n_both_same"].sum() / max(1, g["n_sig_pre2021"].sum())),
            pre2021_signals_within_1bar=float(g["n_pre2021_matched_pm1"].sum() / max(1, g["n_sig_pre2021"].sum())),
            n_sig_pre2021=int(g["n_sig_pre2021"].sum()), n_sig_cache=int(g["n_sig_cache"].sum()),
            worst5_strategies_union_agree=by_s.dropna().head(5).round(3).to_dict(),
            best5_strategies_union_agree=by_s.dropna().tail(5).round(3).to_dict())
    for tf, g in cn.groupby("tf", sort=False):
        f = g[(g["p3_signals"] + g["p1slice_signals"] >= 50) & ((g["ratio"] < 0.5) | (g["ratio"] > 2.0))]
        res["c_counts_flags"][tf] = dict(
            p3_total=int(g["p3_signals"].sum()), p1slice_total=int(g["p1slice_signals"].sum()),
            ratio_median=float(g["ratio"].median()),
            ratio_q10_q90=[float(g["ratio"].quantile(0.1)), float(g["ratio"].quantile(0.9))],
            outside_0p5_2x=f[["strategy", "p3_signals", "p1slice_signals", "ratio"]].round(3).to_dict("records"))
    sw = os.environ.get("SWEEP_DATA")
    if sw and os.path.isdir(os.path.join(sw, "full")):
        res["sweep_30m_rule"] = check_sweep_30m(L, os.path.join(sw, "full"))
        if repro_tfs:
            t0 = time.time()
            with Pool(procs) as p:
                rows = list(p.imap_unordered(_repro_job, [(tf, c, ref_dir) for tf in repro_tfs for c in COINS]))
            rows.sort(key=lambda r: (TFS.index(r["tf"]), COINS.index(r["coin"])))
            res["code_path_reproduces_period12_cache"] = dict(wall_s=round(time.time() - t0, 1), files=rows)
    with Pool(procs) as p:
        sp = pd.DataFrame([r for rows in p.imap_unordered(_split_job, [(tf, c, out_dir, ref_dir) for tf in TFS
                                                                         for c in COINS]) for r in rows])
    sp.to_csv(os.path.join(report_dir, "final_signals_overlap_split.csv"), index=False)
    res["b_split"] = {}
    for (tf, eff), g in sp.groupby(["tf", "effect"], sort=False):
        by_s = g.groupby("strategy")[["n_union", "n_both_same"]].sum()
        by_s = (by_s["n_both_same"] / by_s["n_union"].replace(0, np.nan)).dropna().sort_values()
        res["b_split"].setdefault(tf, {})[eff] = dict(
            union_agree=float(g["n_both_same"].sum() / max(1, g["n_union"].sum())),
            same_bar=float(g["n_both_same"].sum() / max(1, g["n_sig_T"].sum())),
            within_1bar=float(g["n_T_matched_pm1"].sum() / max(1, g["n_sig_T"].sum())),
            worst3=by_s.head(3).round(3).to_dict())
    with open(os.path.join(report_dir, "final_signals_check.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        build(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
    elif cmd == "check":
        print(json.dumps(check(sys.argv[2], sys.argv[3]), indent=1, default=float))
    else:
        print(__doc__)
        sys.exit(2)
