"""Binance USDT-M futures bars and locked-signal cache for 2021-01 .. 2026-09 (the venue the paper bot trades).

    python3 research/binance_data/build.py download   # public archive zips -> <BASE>/raw (cached, 404s in manifest)
    python3 research/binance_data/build.py assemble   # zips -> <BASE>/bars/<coin>usd-<tf>.csv.gz (+ native-vs-5m checks)
    python3 research/binance_data/build.py signals    # bars -> <BASE>/signals/sig_<tf>_<COIN>.npz (locked code, Pool(3))
    python3 research/binance_data/build.py funding    # fundingRate zips -> <BASE>/funding/<SYMBOL>.csv
    python3 research/binance_data/build.py compare    # vs the sweep (Astral/Polygon spot) cache -> out/compare_*
    python3 research/binance_data/build.py all        # the five steps in order
Options: --force (redo signals / bars that exist), --refresh-404 (ask the archive again for known 404s).
<BASE> = $BINANCE_DIR or <scratchpad>/binance; the sweep data is $SWEEP_DATA or <scratchpad>/sweepdata.

Why: the research caches for 2021-08 .. 2026-09 (research/paper_rules/rules_bt.py ``signals``) come from
aggregated USD spot data, not from the Binance USDT-M futures the paper bot trades; on the 2021 overlap
(research/entry_study/out/final_signals_check.json) closes differ ~5 bp, volume 9-22x, and same-bar
signal agreement is 54-76%. This builds the same cache from Binance futures klines.

Source: https://data.binance.vision/data/futures/um/{monthly,daily}/klines/<SYMBOL>/<tf>/... for
5m 15m 1h 4h 1d, monthly 2021-01 .. 2026-08 plus daily 2026-09-01 .. 2026-09-29, and
monthly fundingRate 2021-01 .. 2026-08. Every zip is checked against its published .CHECKSUM and kept
under <BASE>/raw (same path as below /data/ in the URL), so a rerun never downloads again; a 404 is
recorded in <BASE>/manifest_download.json and not asked again. <= 4 downloads at a time, retries with
exponential backoff.

Bars (mirrors research/entry_study/final_signals.py ``load_bars``, which built the period-3 Binance cache):
  * ts = kline open time (UTC); columns ts, open, high, low, close, volume; sorted, one row per ts
    (duplicate open times are counted, conflicting ones reported, the last one kept as read_ohlcv does);
    2021-01-01 <= ts < 2026-09-30 (the existing cache ends at ts < 2026-09-30).
  * 5m, 15m, 1h, 4h, 1d from the native klines; 30m = ``resample_ohlcv(5m, "30m")``. Every timeframe
    goes through ``final_signals.trim_partial_edges`` (first/last bin dropped when the 5m series starts
    after its open / ends before its close; bins partial from data gaps kept).
  * each native 15m/1h/4h/1d file is compared with ``resample_ohlcv(5m)``: same bar times and OHLC
    (rtol 1e-12, as final_signals asserts). Differences are REPORTED (assemble_report.json, "ok": false)
    and the native bars are kept as they are, not replaced. Native volume is kept; bins where it
    differs from the 5m sum are counted.
Signals (mirrors rules_bt._signals_job / final_signals.signal_arrays, imported from there):
``L.compute_signals(strict=True)`` on the whole series from 2021-01 (the locked code is causal, and the
period-1 warm-up before 2021-08-01 is covered for every timeframe, 1d = 200 bars included), DOGE =
paperbot.sigservice.doge_join(DOGE_L, DOGE_S) (sum). Keys: exactly those of the sweep cache (ts int64
ns, o, h, l, c, atr, s__<36 account strategies>) plus v (volume).
Compare (2021-08-01 <= ts < 2026-09-30, bars both caches hold): open/high/low/close |A/B-1| in bp
(median, p99, max) and the signed mean, ATR, volume ratio Binance/sweep; per strategy the same-bar
agreement on the bars where either side signals (both caches past their warm-up, as rules_bt's windows
start). A control against the period-3 Binance cache (data/pre2021, same source) checks that the bars
are identical on 2021-01 .. 2021-08 and that the signals differ only by the series start.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import sys
import threading
import time
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRATCH = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
os.environ.setdefault("SWEEP_DATA", os.path.join(SCRATCH, "sweepdata"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "paper_rules"))
sys.path.insert(0, os.path.join(ROOT, "research", "entry_study"))
warnings.filterwarnings("ignore")

from paperbot import sweepsig  # noqa: E402

BASE = os.environ.get("BINANCE_DIR", os.path.join(SCRATCH, "binance"))
RAW = os.path.join(BASE, "raw")
BARS = os.path.join(BASE, "bars")
SIGNALS = os.path.join(BASE, "signals")
FUNDING = os.path.join(BASE, "funding")
MANIFEST = os.path.join(BASE, "manifest_download.json")
OUT = os.path.join(HERE, "out")
SWEEP_CACHE = os.path.join(SCRATCH, "paper_rules", "signals")          # periods 1-2, sweep (spot) bars
PRE2021_CACHE = os.path.join(SCRATCH, "entry_study", "signals_pre2021")  # period 3, Binance futures

URL = "https://data.binance.vision/data"
USER_AGENT = "crypto-bot-research/binance_data (public market data)"
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")   # rules_bt.COINS order
SYMBOLS = {c: c + "T" for c in COINS}                                   # BTCUSD -> BTCUSDT
KLINE_TFS = ("5m", "15m", "1h", "4h", "1d")                             # downloaded
NATIVE_HTF = ("15m", "1h", "4h", "1d")                                  # checked against resampled 5m
TFS = ("5m", "15m", "30m", "1h", "4h", "1d")                            # cache timeframes
START, END = "2021-01-01", "2026-09-30"                                  # bars: START <= ts < END
MONTHS = [p.strftime("%Y-%m") for p in pd.period_range("2021-01", "2026-08", freq="M")]
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-09-01", "2026-09-29", freq="D")]
CMP = ("2021-08-01", "2026-09-30")                                       # compare window (periods 1+2)
MAX_PAR = 4
PROCS = 3


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _dump(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=_jsonable)
    os.replace(tmp, path)


def _jsonable(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp,)):
        return x.isoformat()
    return str(x)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# =============================================================================================
# download
# =============================================================================================
def targets() -> list[dict]:
    out = []
    for coin in COINS:
        s = SYMBOLS[coin]
        for tf in KLINE_TFS:
            out += [dict(kind="klines", symbol=s, tf=tf, period=m,
                         rel=f"futures/um/monthly/klines/{s}/{tf}/{s}-{tf}-{m}.zip") for m in MONTHS]
            out += [dict(kind="klines_daily", symbol=s, tf=tf, period=d,
                         rel=f"futures/um/daily/klines/{s}/{tf}/{s}-{tf}-{d}.zip") for d in DAYS]
        out += [dict(kind="fundingRate", symbol=s, tf=None, period=m,
                     rel=f"futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip") for m in MONTHS]
    return out


_tls = threading.local()


def _session():
    import requests
    if getattr(_tls, "s", None) is None:
        _tls.s = requests.Session()
        _tls.s.headers["User-Agent"] = USER_AGENT
    return _tls.s


def _get(url: str, tries: int = 6) -> tuple[int, bytes | None, int]:
    """(status, body, attempts). 404 is final; other errors retried with exponential backoff."""
    last = None
    for k in range(tries):
        try:
            r = _session().get(url, timeout=(20, 120))
            if r.status_code == 200:
                return 200, r.content, k + 1
            if r.status_code == 404:
                return 404, None, k + 1
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001  (network errors: retry)
            last = f"{type(exc).__name__}: {exc}"[:200]
        time.sleep(min(60.0, 2.0 * 2 ** k) * (0.75 + 0.5 * random.random()))
    raise RuntimeError(f"{url}: {last}")


def _checksum_of(text: str) -> str:
    return text.strip().split()[0].lower()


def fetch_one(t: dict, known404: set, refresh_404: bool) -> dict:
    rel = t["rel"]
    path = os.path.join(RAW, rel)
    cs_path = path + ".CHECKSUM"
    rec = dict(t, status=None, bytes=None, sha256=None, checksum=None, attempts=0, error=None)
    if os.path.exists(path):
        sha = _sha256(path)
        if os.path.exists(cs_path):
            with open(cs_path) as fh:
                ok = _checksum_of(fh.read()) == sha
            if ok:
                return dict(rec, status="cached", bytes=os.path.getsize(path), sha256=sha, checksum="ok")
            os.remove(path)   # corrupt cache entry: download again
        else:
            return dict(rec, status="cached", bytes=os.path.getsize(path), sha256=sha, checksum="none_published")
    if rel in known404 and not refresh_404:
        return dict(rec, status="404", checksum=None, error="404 (recorded earlier; not asked again)")
    try:
        for attempt in range(3):
            st, blob, n = _get(f"{URL}/{rel}")
            rec["attempts"] += n
            if st == 404:
                return dict(rec, status="404")
            cst, cs, n2 = _get(f"{URL}/{rel}.CHECKSUM")
            rec["attempts"] += n2
            sha = hashlib.sha256(blob).hexdigest()
            if cst == 200 and _checksum_of(cs.decode("utf-8", "replace")) != sha:
                rec["error"] = f"checksum mismatch (attempt {attempt + 1})"
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".part", "wb") as fh:
                fh.write(blob)
            os.replace(path + ".part", path)
            if cst == 200:
                with open(cs_path, "wb") as fh:
                    fh.write(cs)
            return dict(rec, status="downloaded", bytes=len(blob), sha256=sha,
                        checksum="ok" if cst == 200 else "none_published", error=None)
        return dict(rec, status="failed")
    except Exception as exc:  # noqa: BLE001
        return dict(rec, status="failed", error=str(exc)[:300])


def download(refresh_404: bool = False) -> dict:
    t0 = time.time()
    os.makedirs(RAW, exist_ok=True)
    known404 = set()
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as fh:
            known404 = {r["rel"] for r in json.load(fh)["files"] if r["status"] == "404"}
    tl = targets()
    recs = []
    with ThreadPoolExecutor(MAX_PAR) as ex:
        futs = [ex.submit(fetch_one, t, known404, refresh_404) for t in tl]
        for k, f in enumerate(as_completed(futs), 1):
            recs.append(f.result())
            if k % 250 == 0 or k == len(futs):
                st = pd.Series([r["status"] for r in recs]).value_counts().to_dict()
                _log(f"download {k}/{len(futs)} {st} {time.time() - t0:.0f}s")
    recs.sort(key=lambda r: r["rel"])
    df = pd.DataFrame(recs)
    miss = df[df["status"] == "404"]
    fail = df[df["status"] == "failed"]
    summary = dict(
        built_utc=pd.Timestamp.now(tz="UTC").isoformat(), source=URL, raw_dir=RAW,
        months=[MONTHS[0], MONTHS[-1]], days=[DAYS[0], DAYS[-1]], symbols=list(SYMBOLS.values()),
        kline_tfs=list(KLINE_TFS), files=len(df), status_counts=df["status"].value_counts().to_dict(),
        checksum_counts=df["checksum"].fillna("n/a").value_counts().to_dict(),
        bytes_total=int(df["bytes"].fillna(0).sum()),
        missing_404=[f"{r.kind} {r.symbol} {r.tf or ''} {r.period}".replace("  ", " ") for r in miss.itertuples()],
        failed=[dict(rel=r.rel, error=r.error) for r in fail.itertuples()],
        wall_s=round(time.time() - t0, 1))
    _dump(MANIFEST, dict(summary, files=recs))
    _dump(os.path.join(OUT, "download_manifest.json"), summary)
    _log(f"download done: {summary['status_counts']}, 404 {len(miss)}, failed {len(fail)}, "
         f"{summary['bytes_total'] / 1e6:.0f} MB, {summary['wall_s']}s")
    return summary


def _manifest_ok() -> dict:
    """rel -> record of the files that exist locally."""
    with open(MANIFEST) as fh:
        man = json.load(fh)
    return {r["rel"]: r for r in man["files"] if r["status"] in ("cached", "downloaded")}


# =============================================================================================
# assemble
# =============================================================================================
KCOLS = ["ts", "open", "high", "low", "close", "volume"]


def read_kline_zip(path: str) -> pd.DataFrame:
    """Binance kline CSV in a zip (header line or not; open time in ms or us) -> ts (UTC) + OHLCV."""
    with zipfile.ZipFile(path) as z:
        frames = []
        for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
            data = z.read(n)
            header = 0 if data[:1].isalpha() else None
            d = pd.read_csv(io.BytesIO(data), header=header, usecols=range(6), float_precision="round_trip")
            d.columns = ["t", "open", "high", "low", "close", "volume"]
            t = d["t"].to_numpy(np.int64)
            t = np.where(t >= 10 ** 14, t // 1000, t)
            out = pd.DataFrame({"ts": pd.to_datetime(t, unit="ms", utc=True)})
            for k in KCOLS[1:]:
                out[k] = d[k].to_numpy(float)
            frames.append(out)
    return pd.concat(frames, ignore_index=True)


def raw_series(sym: str, tf: str, ok: dict) -> tuple[pd.DataFrame, dict]:
    frames, used_m, used_d = [], [], []
    for m in MONTHS:
        rel = f"futures/um/monthly/klines/{sym}/{tf}/{sym}-{tf}-{m}.zip"
        if rel in ok:
            frames.append(read_kline_zip(os.path.join(RAW, rel))); used_m.append(m)
    for d in DAYS:
        rel = f"futures/um/daily/klines/{sym}/{tf}/{sym}-{tf}-{d}.zip"
        if rel in ok:
            frames.append(read_kline_zip(os.path.join(RAW, rel))); used_d.append(d)
    df = pd.concat(frames, ignore_index=True)
    n_read = len(df)
    df = df.sort_values("ts", kind="stable")
    dup = df.duplicated("ts", keep=False)
    n_dup = int(df.duplicated("ts").sum())
    n_conflict = int((df[dup].groupby("ts")[KCOLS[1:]].nunique() > 1).any(axis=1).sum()) if n_dup else 0
    df = df.drop_duplicates("ts", keep="last")
    inside = (df["ts"] >= pd.Timestamp(START, tz="UTC")) & (df["ts"] < pd.Timestamp(END, tz="UTC"))
    n_out = int((~inside).sum())
    df = df[inside].reset_index(drop=True)
    step = pd.Timedelta(minutes=sweepsig.lib().tf_minutes(tf))
    mis = int(((df["ts"] - pd.Timestamp("1970-01-01", tz="UTC")) % step != pd.Timedelta(0)).sum())
    return df, dict(months_used=len(used_m), days_used=len(used_d),
                    months_missing=[m for m in MONTHS if m not in used_m],
                    days_missing=[d for d in DAYS if d not in used_d], rows_read=n_read,
                    duplicate_ts=n_dup, duplicate_ts_conflicting=n_conflict, rows_outside_range=n_out,
                    misaligned_ts=mis)


def gap_stats(ts: pd.Series, tf: str) -> dict:
    step = pd.Timedelta(minutes=sweepsig.lib().tf_minutes(tf))
    d = ts.diff().iloc[1:]
    g = d[d != step]
    miss = (g / step - 1).round().astype(int)
    top = sorted(zip(miss.tolist(), ts.shift(1).loc[g.index].tolist()), reverse=True)[:5]
    return dict(gaps=int(len(g)), missing_bars=int(miss.sum()), nonpositive_steps=int((d <= pd.Timedelta(0)).sum()),
                largest=[dict(after=str(t0), missing_bars=int(n)) for n, t0 in top])


def compare_native(nat: pd.DataFrame, ref: pd.DataFrame) -> dict:
    """Native higher-TF klines vs resample_ohlcv(5m) (both edge-trimmed)."""
    tn, tr = nat["ts"].to_numpy(), ref["ts"].to_numpy()
    only_n = np.setdiff1d(tn, tr)
    only_r = np.setdiff1d(tr, tn)
    common, i_n, i_r = np.intersect1d(tn, tr, return_indices=True)
    res = dict(bars_native=len(nat), bars_resampled=len(ref), bars_common=len(common),
               only_native=len(only_n), only_resampled=len(only_r),
               only_native_first=[str(pd.Timestamp(x)) for x in only_n[:5]],
               only_resampled_first=[str(pd.Timestamp(x)) for x in only_r[:5]], ohlc={})
    ok = len(only_n) == 0 and len(only_r) == 0
    for k in ("open", "high", "low", "close"):
        a, b = nat[k].to_numpy(float)[i_n], ref[k].to_numpy(float)[i_r]
        bad = ~np.isclose(a, b, rtol=1e-12, atol=0)
        rel = np.abs(a - b) / np.abs(b).clip(1e-300)
        res["ohlc"][k] = dict(mismatches=int(bad.sum()), max_rel=float(rel.max()) if len(rel) else 0.0,
                              first=[dict(ts=str(pd.Timestamp(common[j])), native=float(a[j]), resampled=float(b[j]))
                                     for j in np.flatnonzero(bad)[:5]])
        ok &= not bad.any()
    vn, vr = nat["volume"].to_numpy(float)[i_n], ref["volume"].to_numpy(float)[i_r]
    vrel = np.abs(vn - vr) / np.abs(vr).clip(1e-12)
    vbad = (np.abs(vn - vr) > 1e-9) & (vrel > 1e-9)
    res["volume_vs_5m_sum"] = dict(bins=int(vbad.sum()), max_rel=float(vrel.max()) if len(vrel) else 0.0)
    res["ok"] = bool(ok)
    return res


def _bars_path(coin: str, tf: str) -> str:
    return os.path.join(BARS, f"{coin.lower()}-{tf}.csv.gz")


def _write_bars(df: pd.DataFrame, path: str) -> None:
    out = df[KCOLS].copy()
    out["ts"] = out["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = path + ".tmp.gz"
    out.to_csv(tmp, index=False, compression="gzip")
    os.replace(tmp, path)


def _assemble_job(args) -> list[dict]:
    coin, ok = args
    import final_signals as FS
    L = sweepsig.lib()
    sym = SYMBOLS[coin]
    t0 = time.time()
    df5, n5 = raw_series(sym, "5m", ok)
    rows = []

    def _row(tf, df, notes, source, dropped, native_check=None):
        full = L.tf_minutes(tf) // 5
        per_bin = None
        if tf != "5m":
            cnt = df5.set_index("ts")["close"].resample(L.RESAMPLE_RULE[tf], label="left", closed="left").count()
            cnt = cnt.reindex(df["ts"]).fillna(0).astype(int)
            per_bin = dict(bins_with_fewer_5m=int((cnt < full).sum()), bins_without_5m=int((cnt == 0).sum()))
        _write_bars(df, _bars_path(coin, tf))
        return dict(coin=coin, symbol=sym, tf=tf, source=source, rows=len(df), first=str(df["ts"].iloc[0]),
                    last=str(df["ts"].iloc[-1]), **gap_stats(df["ts"], tf), zero_volume_bars=int((df["volume"] <= 0).sum()),
                    hl_bad=int(((df["high"] < df[["open", "close"]].max(axis=1)) |
                                (df["low"] > df[["open", "close"]].min(axis=1))).sum()),
                    nonpos_prices=int((df[["open", "high", "low", "close"]] <= 0).to_numpy().sum()),
                    dropped_edges=dropped, partial_bins=per_bin, raw=notes, native_vs_5m=native_check)

    rows.append(_row("5m", df5, n5, "native 5m klines", []))
    for tf in NATIVE_HTF:
        nat_raw, notes = raw_series(sym, tf, ok)
        nat, dropped = FS.trim_partial_edges(nat_raw, df5, tf)
        ref, _ = FS.trim_partial_edges(L.resample_ohlcv(df5, tf), df5, tf)
        chk = compare_native(nat, ref)
        rows.append(_row(tf, nat.reset_index(drop=True), notes,
                         f"native {tf} klines (OHLC vs resample_ohlcv(5m): {'equal' if chk['ok'] else 'DIFFER'})",
                         dropped, chk))
    r30, dropped = FS.trim_partial_edges(L.resample_ohlcv(df5, "30m"), df5, "30m")
    rows.append(_row("30m", r30.reset_index(drop=True), None, "resample_ohlcv(5m, 30m)", dropped))
    for r in rows:
        r["coin_wall_s"] = round(time.time() - t0, 1)
    return rows


def assemble(force: bool = False) -> dict:
    t0 = time.time()
    os.makedirs(BARS, exist_ok=True)
    ok = _manifest_ok()
    with Pool(PROCS) as p:
        rows = [r for rs in p.imap_unordered(_assemble_job, [(c, ok) for c in COINS]) for r in rs]
    rows.sort(key=lambda r: (COINS.index(r["coin"]), TFS.index(r["tf"])))
    failed = [f"{r['coin']} {r['tf']}" for r in rows if r["native_vs_5m"] is not None and not r["native_vs_5m"]["ok"]]
    rep = dict(built_utc=pd.Timestamp.now(tz="UTC").isoformat(), bars_dir=BARS, range=[START, END],
               native_equals_resampled_5m_all=not failed, native_differs=failed,
               wall_s=round(time.time() - t0, 1), files=rows)
    _dump(os.path.join(OUT, "assemble_report.json"), rep)
    for r in rows:
        nv = r["native_vs_5m"]
        if nv is None:
            chk = ""
        elif nv["ok"]:
            chk = "native==5m"
        else:
            mm = {k: v["mismatches"] for k, v in nv["ohlc"].items()}
            chk = f"NATIVE != 5m {mm} only_native {nv['only_native']} only_resampled {nv['only_resampled']}"
        dup = r["raw"]["duplicate_ts"] if r["raw"] else "-"
        _log(f"{r['coin']} {r['tf']:>3}: {r['rows']} bars {r['first']} .. {r['last']} gaps {r['gaps']} "
             f"(missing {r['missing_bars']}) dup {dup} {chk}")
    _log(f"assemble done in {rep['wall_s']}s; native==resampled 5m for all: {rep['native_equals_resampled_5m_all']}")
    return rep


# =============================================================================================
# signals
# =============================================================================================
def _sig_path(d: str, tf: str, coin: str) -> str:
    return os.path.join(d, f"sig_{tf}_{coin}.npz")


def _signals_job(args) -> dict:
    tf, coin = args
    import final_signals as FS
    import rules_bt as RB
    L = sweepsig.lib()
    t0 = time.time()
    df = L.read_ohlcv(_bars_path(coin, tf))
    df = df[df["ts"] < pd.Timestamp(RB.WINDOWS["cf"][1], tz="UTC")].reset_index(drop=True)
    df.attrs["tf"] = tf
    t1 = time.time()
    arrs = FS.signal_arrays(L, df, tf, coin)
    t2 = time.time()
    ref_keys = set(np.load(_sig_path(SWEEP_CACHE, tf, coin)).files)
    if set(arrs) != ref_keys | {"v"}:
        raise RuntimeError(f"{tf} {coin}: keys {sorted(set(arrs) ^ (ref_keys | {'v'}))} differ from the sweep cache")
    tmp = _sig_path(SIGNALS, tf, coin) + ".tmp.npz"
    np.savez_compressed(tmp, **arrs)
    os.replace(tmp, _sig_path(SIGNALS, tf, coin))
    warm = L.warmup_bars(tf)
    return dict(tf=tf, coin=coin, bars=len(df), first=str(df["ts"].iloc[0]), last=str(df["ts"].iloc[-1]),
                warmup_bars=warm, first_after_warmup=str(df["ts"].iloc[warm]) if len(df) > warm else None,
                n_signals=int(sum(np.count_nonzero(v) for k, v in arrs.items() if k.startswith("s__"))),
                doge_long=int((arrs["s__DOGE"] > 0).sum()), doge_short=int((arrs["s__DOGE"] < 0).sum()),
                load_s=round(t1 - t0, 1), signals_s=round(t2 - t1, 1), total_s=round(time.time() - t0, 1),
                digest=FS.content_digest(arrs))


def signals(force: bool = False) -> dict:
    t0 = time.time()
    os.makedirs(SIGNALS, exist_ok=True)
    ver = sweepsig.verify()  # hash check before any work
    jobs = [(tf, c) for tf in TFS for c in COINS if force or not os.path.exists(_sig_path(SIGNALS, tf, c))]
    rows = []
    prev = os.path.join(OUT, "signals_manifest.json")
    if os.path.exists(prev):
        with open(prev) as fh:
            rows = [r for r in json.load(fh)["files"] if (r["tf"], r["coin"]) not in set(jobs)]
    _log(f"signals: {len(jobs)} jobs on {PROCS} processes")
    with Pool(PROCS) as p:
        for r in p.imap_unordered(_signals_job, jobs):
            rows.append(r)
            _log(f"signals {r['tf']:>3} {r['coin']}: {r['bars']} bars {r['first']} .. {r['last']} "
                 f"load {r['load_s']}s signals {r['signals_s']}s  DOGE +{r['doge_long']}/-{r['doge_short']}")
    rows.sort(key=lambda r: (TFS.index(r["tf"]), COINS.index(r["coin"])))
    man = dict(built_utc=pd.Timestamp.now(tz="UTC").isoformat(), signals_dir=SIGNALS, bars_dir=BARS,
               locked_code=ver["prereg_sha256_file"], doge="paperbot.sigservice.doge_join (sum)",
               procs=PROCS, wall_s=round(time.time() - t0, 1), jobs_run=len(jobs), files=rows)
    _dump(prev, man)
    _log(f"signals done: {len(jobs)} files in {man['wall_s']}s")
    return man


# =============================================================================================
# funding
# =============================================================================================
def read_funding_zip(path: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        frames = []
        for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
            data = z.read(n)
            d = pd.read_csv(io.BytesIO(data), header=0 if data[:1].isalpha() else None,
                            float_precision="round_trip")
            if d.shape[1] == 3:
                d.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"]
            else:   # older layout without the interval column
                d = d.iloc[:, :2]
                d.columns = ["calc_time", "last_funding_rate"]
                d["funding_interval_hours"] = np.nan
            frames.append(d)
    return pd.concat(frames, ignore_index=True)


def funding() -> dict:
    t0 = time.time()
    os.makedirs(FUNDING, exist_ok=True)
    ok = _manifest_ok()
    rows = []
    for coin in COINS:
        s = SYMBOLS[coin]
        fr, used = [], []
        for m in MONTHS:
            rel = f"futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip"
            if rel in ok:
                fr.append(read_funding_zip(os.path.join(RAW, rel))); used.append(m)
        d = pd.concat(fr, ignore_index=True).sort_values("calc_time", kind="stable")
        n_dup = int(d.duplicated("calc_time").sum())
        d = d.drop_duplicates("calc_time", keep="last").reset_index(drop=True)
        out = pd.DataFrame({"fundingTime": d["calc_time"].astype(np.int64), "rate": d["last_funding_rate"].astype(float),
                            "interval_h": d["funding_interval_hours"]})
        out.to_csv(os.path.join(FUNDING, f"{s}.csv"), index=False)
        dt_h = np.diff(out["fundingTime"].to_numpy()) / 3.6e6
        iv = out["interval_h"].to_numpy(float)[1:]
        late = np.isfinite(iv) & (dt_h > iv + 0.5)
        rows.append(dict(symbol=s, rows=len(out), months_used=len(used), months_missing=[m for m in MONTHS if m not in used],
                         first=str(pd.Timestamp(out["fundingTime"].iloc[0], unit="ms")),
                         last=str(pd.Timestamp(out["fundingTime"].iloc[-1], unit="ms")), duplicates=n_dup,
                         interval_h_counts={str(k): int(v) for k, v in out["interval_h"].value_counts(dropna=False).items()},
                         gaps_longer_than_interval=int(late.sum()),
                         rate_mean=float(out["rate"].mean()), rate_median=float(out["rate"].median()),
                         rate_share_positive=float((out["rate"] > 0).mean()),
                         rate_abs_max=float(out["rate"].abs().max())))
        _log(f"funding {s}: {len(out)} rows {rows[-1]['first']} .. {rows[-1]['last']} mean {rows[-1]['rate_mean']:.6f} "
             f"intervals {rows[-1]['interval_h_counts']} gaps {rows[-1]['gaps_longer_than_interval']}")
    rep = dict(built_utc=pd.Timestamp.now(tz="UTC").isoformat(), funding_dir=FUNDING,
               columns="fundingTime (ms, Binance calc_time as published), rate, interval_h",
               wall_s=round(time.time() - t0, 1), symbols=rows)
    _dump(os.path.join(OUT, "funding_report.json"), rep)
    return rep


# =============================================================================================
# compare
# =============================================================================================
def _load(d: str, tf: str, coin: str) -> dict:
    z = np.load(_sig_path(d, tf, coin))
    return {k: z[k] for k in z.files}


def _names(b: dict) -> list[str]:
    return [k[3:] for k in b if k.startswith("s__")]


def _bp(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a / b - 1.0) * 1e4


def _signal_rows(A, B, ia, ib, names, pm1, **key) -> list[dict]:
    rows = []
    for n in names:
        sa, sb = A[f"s__{n}"][ia], B[f"s__{n}"][ib]
        u = (sa != 0) | (sb != 0)
        rows.append(dict(key, strategy=n, n_bars=len(ia), n_sig_binance=int(np.count_nonzero(sa)),
                         n_sig_other=int(np.count_nonzero(sb)), n_union=int(u.sum()),
                         n_both_same=int(((sa == sb) & u).sum()),
                         n_opposite=int(((sa * sb) < 0).sum()),
                         n_binance_matched_pm1=pm1(sa, sb), n_other_matched_pm1=pm1(sb, sa)))
    return rows


def _compare_job(args) -> tuple[dict, list[dict], dict | None, list[dict]]:
    tf, coin = args
    import final_signals as FS
    L = sweepsig.lib()
    warm = L.warmup_bars(tf)
    A, B = _load(SIGNALS, tf, coin), _load(SWEEP_CACHE, tf, coin)
    names = _names(B)
    assert _names(A) == names, (tf, coin, "strategy keys differ")
    lo, hi = pd.Timestamp(CMP[0]).value, pd.Timestamp(CMP[1]).value
    _, ia, ib = np.intersect1d(A["ts"], B["ts"], assume_unique=True, return_indices=True)
    m = (A["ts"][ia] >= lo) & (A["ts"][ia] < hi)
    ia, ib = ia[m], ib[m]
    inA = int(((A["ts"] >= lo) & (A["ts"] < hi)).sum())
    inB = int(((B["ts"] >= lo) & (B["ts"] < hi)).sum())
    vol_b = FS._sweep_volume(tf, coin, B["ts"])
    row = dict(tf=tf, coin=coin, bars_binance=inA, bars_sweep=inB, bars_common=len(ia),
               only_binance=inA - len(ia), only_sweep=inB - len(ia),
               first=str(pd.Timestamp(A["ts"][ia[0]])), last=str(pd.Timestamp(A["ts"][ia[-1]])))
    for k, lab in (("c", "close"), ("h", "high"), ("l", "low"), ("o", "open")):
        d = _bp(A[k][ia], B[k][ib])
        ad = np.abs(d)
        row.update({f"{lab}_absdiff_bp_median": float(np.median(ad)), f"{lab}_absdiff_bp_p99": float(np.quantile(ad, 0.99)),
                    f"{lab}_absdiff_bp_max": float(ad.max()), f"{lab}_diff_bp_mean": float(d.mean()),
                    f"{lab}_equal_share": float(np.mean(A[k][ia] == B[k][ib]))})
    arel = np.abs(A["atr"][ia] / B["atr"][ib] - 1.0) * 100
    row["atr_absdiff_pct_median"] = float(np.nanmedian(arel))
    if vol_b is not None:
        va, vb = A["v"][ia], vol_b[ib]
        ok = np.isfinite(vb) & (vb > 0) & (va > 0)
        r = va[ok] / vb[ok]
        row.update(volume_ratio_median=float(np.median(r)), volume_ratio_p10=float(np.quantile(r, 0.1)),
                   volume_ratio_p90=float(np.quantile(r, 0.9)),
                   logvolume_corr=float(np.corrcoef(np.log(va[ok]), np.log(vb[ok]))[0, 1]),
                   volume_bars_compared=int(ok.sum()), sweep_zero_volume_bars=int((vb[np.isfinite(vb)] <= 0).sum()))
    # signals: bars past both warm-ups (rules_bt.window_bounds starts at max(window start, warm-up))
    ms = (ia >= warm) & (ib >= warm)
    ja, jb = ia[ms], ib[ms]
    row.update(signal_bars=len(ja), signal_first=str(pd.Timestamp(A["ts"][ja[0]])) if len(ja) else None)
    srows = _signal_rows(A, B, ja, jb, names, FS._pm1_match, tf=tf, coin=coin)
    # control: the period-3 Binance cache (data/pre2021; same source) on 2021-01 .. 2021-08
    ctrl, crows = None, []
    if os.path.exists(_sig_path(PRE2021_CACHE, tf, coin)):
        P = _load(PRE2021_CACHE, tf, coin)
        _, ka, kp = np.intersect1d(A["ts"], P["ts"], assume_unique=True, return_indices=True)
        ctrl = dict(tf=tf, coin=coin, bars_common=len(ka), first=str(pd.Timestamp(A["ts"][ka[0]])),
                    last=str(pd.Timestamp(A["ts"][ka[-1]])),
                    **{f"{k}_equal_share": float(np.mean(A[k][ka] == P[k][kp])) for k in ("o", "h", "l", "c", "v")},
                    close_absdiff_bp_max=float(np.max(np.abs(_bp(A["c"][ka], P["c"][kp])))),
                    volume_absdiff_rel_max=float(np.max(np.abs(A["v"][ka] / P["v"][kp] - 1))),
                    bars_only_pre2021_in_2021=int(((P["ts"] >= pd.Timestamp(START).value) &
                                                  ~np.isin(P["ts"], A["ts"])).sum()))
        mc = (ka >= warm) & (kp >= warm)
        crows = _signal_rows(A, P, ka[mc], kp[mc], names, FS._pm1_match, tf=tf, coin=coin)
        ctrl["signal_bars"] = int(mc.sum())
    return row, srows, ctrl, crows


def _agg(g: pd.DataFrame) -> dict:
    nsa = max(1, int(g["n_sig_binance"].sum()))
    return dict(union_agree=float(g["n_both_same"].sum() / max(1, g["n_union"].sum())),
                binance_signals_same_bar=float(g["n_both_same"].sum() / nsa),
                binance_signals_within_1bar=float(g["n_binance_matched_pm1"].sum() / nsa),
                opposite_share_of_union=float(g["n_opposite"].sum() / max(1, g["n_union"].sum())),
                n_sig_binance=int(g["n_sig_binance"].sum()), n_sig_other=int(g["n_sig_other"].sum()),
                n_union=int(g["n_union"].sum()), n_both_same=int(g["n_both_same"].sum()))


def compare() -> dict:
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    jobs = [(tf, c) for tf in TFS for c in COINS]
    with Pool(PROCS) as p:
        res = p.map(_compare_job, jobs)
    bars = pd.DataFrame([r[0] for r in res])
    sig = pd.DataFrame([x for r in res for x in r[1]])
    ctrl = pd.DataFrame([r[2] for r in res if r[2] is not None])
    csig = pd.DataFrame([x for r in res for x in r[3]])
    sig["union_agree"] = sig["n_both_same"] / sig["n_union"].replace(0, np.nan)
    bars.to_csv(os.path.join(OUT, "compare_bars.csv"), index=False)
    sig.to_csv(os.path.join(OUT, "compare_signals.csv"), index=False)
    by_ts = sig.groupby(["tf", "strategy"], sort=False)[["n_union", "n_both_same", "n_sig_binance", "n_sig_other"]].sum()
    by_ts["union_agree"] = by_ts["n_both_same"] / by_ts["n_union"].replace(0, np.nan)
    by_ts["signal_count_ratio_binance_over_sweep"] = by_ts["n_sig_binance"] / by_ts["n_sig_other"].replace(0, np.nan)
    by_ts.reset_index().to_csv(os.path.join(OUT, "compare_signals_by_strategy.csv"), index=False)
    summary = dict(built_utc=pd.Timestamp.now(tz="UTC").isoformat(), window=list(CMP),
                   binance_cache=SIGNALS, sweep_cache=SWEEP_CACHE,
                   notes=["price/volume stats over all bars both caches hold in the window; signal agreement over "
                          "those bars past both caches' warm-up (sweep 1d: 200 bars from 2021-05-31 -> 2021-12)",
                          "union_agree = same side on the same bar / bars where either side signals",
                          "binance_signals_within_1bar: Binance signals with a same-side sweep signal on the bar or one either side",
                          "volume ratio = Binance futures volume / sweep (spot aggregate) volume"],
                   per_tf={}, all_tfs=_agg(sig))
    for tf in TFS:
        b, g = bars[bars["tf"] == tf], sig[sig["tf"] == tf]
        s = by_ts.loc[tf]
        s = s[s["n_union"] > 0]
        summary["per_tf"][tf] = dict(
            bars_common=int(b["bars_common"].sum()),
            close_absdiff_bp_median_by_coin=dict(zip(b["coin"], b["close_absdiff_bp_median"].round(3))),
            close_absdiff_bp_p99_by_coin=dict(zip(b["coin"], b["close_absdiff_bp_p99"].round(2))),
            high_absdiff_bp_median_by_coin=dict(zip(b["coin"], b["high_absdiff_bp_median"].round(3))),
            low_absdiff_bp_median_by_coin=dict(zip(b["coin"], b["low_absdiff_bp_median"].round(3))),
            close_diff_bp_mean_by_coin=dict(zip(b["coin"], b["close_diff_bp_mean"].round(3))),
            atr_absdiff_pct_median_by_coin=dict(zip(b["coin"], b["atr_absdiff_pct_median"].round(3))),
            volume_ratio_median_by_coin=dict(zip(b["coin"], b.get("volume_ratio_median", pd.Series(dtype=float)).round(3))),
            signals=_agg(g),
            signals_by_coin={c: round(_agg(gc)["union_agree"], 4) for c, gc in g.groupby("coin", sort=False)},
            strategy_union_agree_median=float(s["union_agree"].median()),
            worst5_strategies=s["union_agree"].sort_values().head(5).round(3).to_dict(),
            best5_strategies=s["union_agree"].sort_values().tail(5).round(3).to_dict())
    if len(ctrl):
        ctrl.to_csv(os.path.join(OUT, "compare_control_pre2021.csv"), index=False)
        csig.to_csv(os.path.join(OUT, "compare_control_pre2021_signals.csv"), index=False)
        summary["control_pre2021"] = dict(
            what="new Binance cache vs the period-3 Binance cache (data/pre2021, same source) on the bars both hold "
                 "(2021-01 .. 2021-08); signal differences there come only from the series start (2021-01 vs 2020)",
            bars_identical_share_min={k: float(ctrl[f"{k}_equal_share"].min()) for k in ("o", "h", "l", "c", "v")},
            close_absdiff_bp_max=float(ctrl["close_absdiff_bp_max"].max()),
            per_tf={tf: _agg(g) for tf, g in csig.groupby("tf", sort=False)})
    summary["wall_s"] = round(time.time() - t0, 1)
    _dump(os.path.join(OUT, "compare_summary.json"), summary)
    for tf, v in summary["per_tf"].items():
        _log(f"compare {tf:>3}: close |d| median bp {v['close_absdiff_bp_median_by_coin']} "
             f"vol ratio {v['volume_ratio_median_by_coin']} union_agree {v['signals']['union_agree']:.3f} "
             f"same_bar {v['signals']['binance_signals_same_bar']:.3f} within1 {v['signals']['binance_signals_within_1bar']:.3f}")
    return summary


# =============================================================================================
def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else ""
    force, r404 = "--force" in argv, "--refresh-404" in argv
    steps = {"download": lambda: download(r404), "assemble": lambda: assemble(force),
             "signals": lambda: signals(force), "funding": funding, "compare": compare}
    todo = list(steps) if cmd == "all" else [cmd] if cmd in steps else None
    if not todo:
        print(__doc__)
        sys.exit(2)
    timing_path = os.path.join(OUT, "timing.json")
    timing = {}
    if os.path.exists(timing_path):
        with open(timing_path) as fh:
            timing = json.load(fh)
    for s in todo:
        t0 = time.time()
        _log(f"=== {s}")
        steps[s]()
        timing[s] = dict(wall_s=round(time.time() - t0, 1), finished_utc=pd.Timestamp.now(tz="UTC").isoformat())
        _dump(timing_path, timing)


if __name__ == "__main__":
    main(sys.argv)
