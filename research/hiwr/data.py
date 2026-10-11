"""Track 2 1m data (PREREG_HIWR.md section 3): the Binance USD-M public archive (data.binance.vision) for the hunt's 30
coins, with month bounds. Public price data only, no key of any kind.

    python -m research.hiwr.data download --dir KIT --first 2020-01 --last 2023-12 [--procs 8]   # the practice kit
    python -m research.hiwr.data build    --dir KIT --first 2020-01 --last 2023-12
    python -m research.hiwr.data all      --dir KIT --first 2020-01 --last 2023-12

A copy of research/fullgrid/data.py (not imported: 17.1 imports only run/grid/memo/kernel) with these changes:
- symbols from research/hunt/universe30.json; month bounds are arguments, so a kit downloads only the months it needs
  (practice kit 2020-01 .. 2023-12; the confirm stage fetches 2024-01 .. 2026-09 into its own kit);
- the kline columns kept are open time, OHLC, base volume ``v`` (as the full grid; the chart frames and every signal
  use it, exactly as the full grid's signals did) and quote volume ``qv`` (as the hunt);
- the daily files fill only minutes absent from the monthly file (monthly values are never overwritten, as the hunt's
  builder; section 3 "absent minutes only"). A day is read from the daily archive when its monthly file holds fewer
  than 1,440 minutes;
- a coin may end inside the kit (TOMO 2023-11-14 in the practice kit): its span ends at its last bar with volume,
  which the build reports (``ended``) instead of refusing;
- the identity of the data: per coin and per array the hunt's content sha256 (``content_sha``), recomputed by every
  stage on load (``load_kit``);
- chart frames are built from the period-cut arrays by research/fullgrid/run.build_frame (imported read-only) and kept
  in hiwr's own frame folder (``make_frames``), never in the full grid's ``fgwork/frames``.
Kept from the full grid: every zip is checked against its ``.CHECKSUM``; a 404 is recorded and not asked again;
zero-volume minutes are dropped; a missing mark minute takes the last-price bar; funding goes to its calc minute
(floored; the next minute when that one is missing). Output ``KIT/1m/<SYMBOL>.npz``: ts int64 (ms, minute open),
o h l c v qv, mo mh ml mc, fund (rate on its minute, 0 elsewhere), all float64; ``KIT/build.json``.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
UNIVERSE30 = os.path.join(ROOT, "research", "hunt", "universe30.json")
FULLGRID = os.path.join(ROOT, "research", "fullgrid")


def _universe() -> dict:
    with open(UNIVERSE30) as fh:
        return json.load(fh)


SYMBOLS = tuple(_universe()["symbols"])          # coin priority order (section 4)
OLD_SIX = tuple(_universe()["old_six"])
BASE_URL = "https://data.binance.vision/data/"
MIN = 60_000
DAY = 86_400_000
MIN_FREE = 1024 ** 3                             # stop downloading below 1 GB free (as the hunt's builder)
KIT_SEL = ("2020-01", "2023-12")                 # the practice kit: the only months select may download
KIT_TEST = ("2024-01", "2026-09")                # the confirm stage's kit (after the picks' hash, 10.6)
ARRAYS = ("ts", "o", "h", "l", "c", "v", "qv", "mo", "mh", "ml", "mc", "fund")
END_GAP = 3 * DAY                                # last bar with volume this far before the kit end: the coin ended


def ms(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").value // 1_000_000)


# Periods by signal-bar close (section 9): [start, end) in ms UTC.
PERIODS = {"SEL": (ms("2021-01-01"), ms("2024-01-01")), "TEST": (ms("2024-01-01"), ms("2026-10-01")),
           "EXTRA": (ms("2020-01-01"), ms("2021-01-01"))}


def months(a: str, b: str) -> list[str]:
    y, m = map(int, a.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_end_ms(month: str) -> int:
    """First ms after ``month`` (the start of the next month)."""
    y, m = map(int, month.split("-"))
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return ms(f"{y:04d}-{m:02d}-01")


def rel_monthly(kind: str, sym: str, month: str) -> str:
    if kind == "fundingRate":
        return f"futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{month}.zip"
    return f"futures/um/monthly/{kind}/{sym}/1m/{sym}-1m-{month}.zip"


def rel_daily(kind: str, sym: str, day: str) -> str:
    return f"futures/um/daily/{kind}/{sym}/1m/{sym}-1m-{day}.zip"


# ------------------------------------------------------------------ download (as the full grid)
def _get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "crypto-bot-research/hiwr"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch(raw: str, rel: str, tries: int = 5, get=_get) -> str:
    """'ok' (file present and checksum-verified), 'missing' (404) or raises after ``tries`` attempts."""
    path = os.path.join(raw, rel)
    if os.path.exists(path):
        return "ok"
    last = None
    for k in range(tries):
        try:
            data = get(BASE_URL + rel)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return "missing"
            last = exc
            time.sleep(min(30, 2 ** k))
            continue
        except Exception as exc:  # noqa: BLE001  network: retry with backoff
            last = exc
            time.sleep(min(30, 2 ** k))
            continue
        try:
            want = get(BASE_URL + rel + ".CHECKSUM").decode().split()[0].strip().lower()
            got = hashlib.sha256(data).hexdigest()
            if got != want:
                raise IOError(f"checksum mismatch {rel}: {got} != {want}")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
            return "ok"
        except Exception as exc:  # noqa: BLE001  network or checksum: retry with backoff
            last = exc
        time.sleep(min(30, 2 ** k))
    raise RuntimeError(f"download failed {rel}: {last}")


def _manifest(d: str) -> dict:
    p = os.path.join(d, "manifest.json")
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return {"missing": []}


def _save_json(path: str, doc) -> None:
    with open(path + ".tmp", "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)


def _free_ok(d: str) -> None:
    free = shutil.disk_usage(d).free
    if free < MIN_FREE:
        raise SystemExit(f"disk: {free / 1024 ** 3:.2f} GB free under {d}, below {MIN_FREE / 1024 ** 3:.0f} GB; stopping")


def _fetch_all(d: str, rels: list[str], procs: int, man: dict, label: str, get=_get) -> None:
    raw = os.path.join(d, "raw")
    miss = set(man["missing"])
    todo = [r for r in rels if r not in miss and not os.path.exists(os.path.join(raw, r))]
    t0, done = time.time(), 0
    with cf.ThreadPoolExecutor(procs) as ex:
        futs = {ex.submit(fetch, raw, r, 5, get): r for r in todo}
        for f in cf.as_completed(futs):
            if f.result() == "missing":
                miss.add(futs[f])
            done += 1
            if done % 50 == 0 or done == len(todo):
                _free_ok(d)
                print(f"[{label}] {done}/{len(todo)} files, {time.time() - t0:.0f}s", flush=True)
    man["missing"] = sorted(miss)
    _save_json(os.path.join(d, "manifest.json"), man)


def download(d: str, first: str, last: str, symbols=SYMBOLS, procs: int = 8, get=_get) -> None:
    """Monthly klines, mark klines and funding of the months [first, last] only; then the daily files of the days a
    monthly kline file lacks minutes of."""
    os.makedirs(os.path.join(d, "raw"), exist_ok=True)
    _free_ok(d)
    man = _manifest(d)
    man["months"] = [first, last]
    rels = [rel_monthly(k, s, m) for s in symbols for m in months(first, last)
            for k in ("klines", "markPriceKlines", "fundingRate")]
    _fetch_all(d, rels, procs, man, "monthly", get)
    keys = sorted({f"{s}|{day}" for s in symbols for day in gap_days(d, s, man, first, last)}
                  | set(man.get("gap_days", [])))
    man["gap_days"] = keys
    rels = [rel_daily(k, *key.split("|")) for key in keys for k in ("klines", "markPriceKlines")]
    _fetch_all(d, rels, procs, man, "gap-fill days", get)


# ------------------------------------------------------------------ read
KLINE_COLS = ["t", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]


def read_kline_zip(path: str) -> pd.DataFrame:
    """Binance kline CSV in a zip (header line or not; open time in ms or us) -> t (ms), OHLC, base and quote volume."""
    with zipfile.ZipFile(path) as z:
        frames = []
        for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
            data = z.read(n)
            if not data.strip():
                continue
            header = 0 if data[:1].isalpha() else None
            x = pd.read_csv(io.BytesIO(data), header=header, usecols=range(8), float_precision="round_trip")
            x.columns = KLINE_COLS
            t = x["t"].to_numpy(np.int64)
            x["t"] = np.where(t >= 10 ** 14, t // 1000, t)
            frames.append(x.drop(columns=["close_time"]))
    if not frames:
        return pd.DataFrame(columns=[c for c in KLINE_COLS if c != "close_time"])
    return pd.concat(frames, ignore_index=True)


def read_funding_zip(path: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        frames = []
        for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
            data = z.read(n)
            x = pd.read_csv(io.BytesIO(data), header=0 if data[:1].isalpha() else None, float_precision="round_trip")
            x = x.iloc[:, [0, x.shape[1] - 1]]
            x.columns = ["calc_time", "rate"]
            frames.append(x)
    if not frames:
        return pd.DataFrame(columns=["calc_time", "rate"])
    return pd.concat(frames, ignore_index=True)


def _series(d: str, kind: str, sym: str, man: dict, first: str, last: str, daily: bool = True) -> pd.DataFrame:
    """Monthly rows of [first, last]; with ``daily``, the gap days' daily rows for minutes the monthly files lack."""
    raw, miss = os.path.join(d, "raw"), set(man["missing"])
    parts = []
    for m in months(first, last):
        r = rel_monthly(kind, sym, m)
        if r not in miss and os.path.exists(os.path.join(raw, r)):
            parts.append(read_kline_zip(os.path.join(raw, r)))
    n_monthly = len(parts)
    if daily:
        lo, hi = ms(first + "-01"), month_end_ms(last)
        for key in man.get("gap_days", []):
            s, day = key.split("|")
            r = rel_daily(kind, sym, day)
            if s == sym and lo <= ms(day) < hi and r not in miss and os.path.exists(os.path.join(raw, r)):
                parts.append(read_kline_zip(os.path.join(raw, r)))
    if not parts:
        return pd.DataFrame(columns=[c for c in KLINE_COLS if c != "close_time"])
    x = pd.concat(parts, ignore_index=True)
    x["src"] = np.repeat(np.arange(len(parts)) >= n_monthly, [len(p) for p in parts])
    # monthly rows first and kept on a repeated open time: a daily row only adds a minute the month lacks
    x = x.sort_values(["t", "src"], kind="mergesort").drop_duplicates("t", keep="first")
    return x.drop(columns=["src"]).reset_index(drop=True)


def gap_days(d: str, sym: str, man: dict, first: str, last: str) -> list[str]:
    """UTC days after the coin's first listed day (through its last day in the kit) whose monthly klines hold fewer
    than 1,440 minutes."""
    x = _series(d, "klines", sym, man, first, last, daily=False)
    if not len(x):
        return []
    day = x["t"].to_numpy(np.int64) // DAY
    cnt = pd.Series(1, index=day).groupby(level=0).sum()
    f, la = int(day[0]), int(day[-1])
    out = []
    for k in range(f + 1, la + 1):               # the listing day itself starts mid-day
        if int(cnt.get(k, 0)) < 1440:
            out.append(str(dt.date(1970, 1, 1) + dt.timedelta(days=k)))
    return out


# ------------------------------------------------------------------ identity (the hunt's content sha, H 2)
def array_sha(name: str, a: np.ndarray) -> str:
    """sha256 of 'name|dtype|shape' (shape comma-joined) newline, then the raw C-order bytes (research/hunt/hunt.py
    content_sha, one array)."""
    a = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(f"{name}|{a.dtype.str}|{','.join(str(x) for x in a.shape)}\n".encode())
    h.update(a.tobytes())
    return h.hexdigest()


def content_sha(arrays: dict, keys=ARRAYS) -> dict:
    """Per array its content sha256, plus 'all': the hunt's combined hash over ``keys`` in that order."""
    out = {k: array_sha(k, arrays[k]) for k in keys if k in arrays}
    h = hashlib.sha256()
    for k in keys:
        if k in arrays:
            a = np.ascontiguousarray(arrays[k])
            h.update(f"{k}|{a.dtype.str}|{','.join(str(x) for x in a.shape)}\n".encode())
            h.update(a.tobytes())
    out["all"] = h.hexdigest()
    return out


# ------------------------------------------------------------------ build
def build_symbol(d: str, sym: str, man: dict, first: str, last: str) -> dict:
    k = _series(d, "klines", sym, man, first, last)
    n_read = len(k)
    if not n_read:
        return {"symbol": sym, "minutes": 0, "months": [first, last], "ended": True, "problems": [f"{sym}: no klines"]}
    k = k[k["volume"] > 0].reset_index(drop=True)
    m = _series(d, "markPriceKlines", sym, man, first, last).set_index("t")
    ts = k["t"].to_numpy(np.int64)
    mk = m.reindex(ts)
    no_mark = mk["open"].isna().to_numpy()
    cols = {}
    for a, b in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"), ("qv", "quote_volume")):
        cols[a] = k[b].to_numpy(float)
    for a, b, fall in (("mo", "open", "o"), ("mh", "high", "h"), ("ml", "low", "l"), ("mc", "close", "c")):
        cols[a] = np.where(no_mark, cols[fall], mk[b].to_numpy(float))
    raw, miss = os.path.join(d, "raw"), set(man["missing"])
    fr = [read_funding_zip(os.path.join(raw, r)) for r in (rel_monthly("fundingRate", sym, mo)
                                                           for mo in months(first, last))
          if r not in miss and os.path.exists(os.path.join(raw, r))]
    fund = np.zeros(len(ts))
    lost = 0
    ft = np.zeros(0, np.int64)
    if fr:
        f = pd.concat(fr, ignore_index=True).drop_duplicates("calc_time", keep="last").sort_values("calc_time")
        ft = f["calc_time"].to_numpy(np.int64) // MIN * MIN
        j = np.searchsorted(ts, ft, side="left")   # that minute, or the first one after it when missing
        ok = j < len(ts)
        lost = int((~ok).sum())
        np.add.at(fund, j[ok], f["rate"].to_numpy(float)[ok])
    arrays = {"ts": ts, **cols, "fund": fund}
    out = os.path.join(d, "1m", f"{sym}.npz")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    np.savez(out + ".part.npz", **arrays)
    os.replace(out + ".part.npz", out)
    kit_end = month_end_ms(last)
    gaps = np.diff(ts) // MIN - 1
    ended = bool(ts[-1] < kit_end - END_GAP)
    per_month = pd.Series(pd.to_datetime(ft, unit="ms").strftime("%Y-%m")).value_counts() if len(ft) else {}
    inner = [mo for mo in months(first, last) if ts[0] < ms(mo + "-01") and month_end_ms(mo) <= ts[-1] + MIN]
    thin = [mo for mo in inner if int(per_month.get(mo, 0)) < 60]   # 3 a day; the first and last month may be short
    problems = []
    if len(gaps) and (np.diff(ts) > 3 * DAY).any():
        i = int(np.argmax(np.diff(ts)))
        problems.append(f"{sym}: {(ts[i + 1] - ts[i]) / DAY:.1f}-day hole after {_iso(ts[i])}")
    if thin:
        problems.append(f"{sym}: funding missing in {', '.join(thin[:5])}")
    return {"symbol": sym, "months": [first, last], "minutes": int(len(ts)), "read": int(n_read),
            "zero_volume_dropped": int(n_read - len(ts)), "first": _iso(ts[0]), "last": _iso(ts[-1]),
            "last_ms": int(ts[-1]), "ended": ended, "mark_filled_from_last": int(no_mark.sum()),
            "missing_minutes": int(gaps[gaps > 0].sum()), "gaps_over_1h": int((gaps >= 60).sum()),
            "funding_events": int(len(ft) - lost), "funding_after_data_end": lost, "content_sha256": content_sha(arrays),
            "problems": problems}


def _iso(t: int) -> str:
    return dt.datetime.fromtimestamp(int(t) / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def build(d: str, first: str, last: str, symbols=SYMBOLS) -> dict:
    man = _manifest(d)
    rep = {"months": [first, last], "symbols": [build_symbol(d, s, man, first, last) for s in symbols],
           "gap_days": len(man.get("gap_days", [])), "missing_files": len(man["missing"])}
    rep["problems"] = [p for r in rep["symbols"] for p in r["problems"]]
    _save_json(os.path.join(d, "build.json"), rep)
    for r in rep["symbols"]:
        if r["minutes"]:
            print(f"{r['symbol']}: {r['minutes']:,} minutes {r['first']} .. {r['last']}{' (ended)' if r['ended'] else ''}"
                  f", mark filled {r['mark_filled_from_last']}, missing minutes {r['missing_minutes']:,}, "
                  f"funding {r['funding_events']}", flush=True)
    if rep["problems"]:
        raise SystemExit("data incomplete: " + "; ".join(rep["problems"]))
    return rep


def manifest(d: str) -> dict:
    """The kit's identity for research/hiwr/data_manifest_<period>.json: per coin its span and array hashes."""
    with open(os.path.join(d, "build.json")) as fh:
        rep = json.load(fh)
    return {"months": rep["months"], "coins": {r["symbol"]: {k: r[k] for k in ("first", "last", "last_ms", "ended",
                                                                                "minutes", "content_sha256")}
                                                for r in rep["symbols"] if r["minutes"]}}


# ------------------------------------------------------------------ load (every stage)
class DataMismatch(RuntimeError):
    pass


def load(d: str, sym: str) -> dict:
    with np.load(os.path.join(d, "1m", f"{sym}.npz")) as z:
        return {k: z[k] for k in z.files}


def load_kit(d: str, sym: str, end_ms: int | None = None, want: dict | None = None, keys=ARRAYS) -> dict:
    """One kit's arrays of ``sym``. ``want`` (a manifest's ``content_sha256`` of the coin): every array's hash is
    recomputed and compared before anything else (DataMismatch on a difference). ``end_ms``: every array is cut to
    minutes with open < end_ms right after loading, before any other use (section 9)."""
    out = {}
    with np.load(os.path.join(d, "1m", f"{sym}.npz")) as z:
        ts = z["ts"]
        if want is not None and array_sha("ts", ts) != want.get("ts"):
            raise DataMismatch(f"{sym} ts differs from the manifest")
        m = len(ts) if end_ms is None else int(np.searchsorted(ts, end_ms))
        out["ts"] = np.ascontiguousarray(ts[:m])
        del ts
        for k in keys:
            if k == "ts" or k not in z.files:
                continue
            a = z[k]
            if want is not None and array_sha(k, a) != want.get(k):
                raise DataMismatch(f"{sym} {k} differs from the manifest")
            out[k] = np.ascontiguousarray(a[:m])
            del a
    if end_ms is not None and len(out["ts"]):
        assert out["ts"][-1] < end_ms
    return out


def load_cut(dirs, sym: str, end_ms: int, wants=None, keys=ARRAYS) -> dict:
    """Several kits of one coin in time order (the practice kit, then the confirm kit), joined and cut at ``end_ms``.
    A kit whose first minute is not after the previous kit's last minute is refused."""
    dirs = [dirs] if isinstance(dirs, str) else list(dirs)
    parts = []
    for i, d in enumerate(dirs):
        if not os.path.exists(os.path.join(d, "1m", f"{sym}.npz")):
            continue
        p = load_kit(d, sym, end_ms, None if wants is None else wants[i], keys)
        if parts and len(p["ts"]) and len(parts[-1]["ts"]) and p["ts"][0] <= parts[-1]["ts"][-1]:
            raise DataMismatch(f"{sym}: kit {d} overlaps the previous kit")
        if len(p["ts"]):
            parts.append(p)
    if not parts:
        raise DataMismatch(f"{sym}: no data before {_iso(end_ms)}")
    if len(parts) == 1:
        return parts[0]
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def coin_ended(arrays: dict, end_ms: int) -> bool:
    """The coin's tradable span ends inside the period (7.6): its last bar with volume is more than 3 days before the
    period end. A position still open there closes at that bar's close; otherwise it is open at the period end."""
    return bool(len(arrays["ts"]) and arrays["ts"][-1] < end_ms - END_GAP)


# ------------------------------------------------------------------ chart frames (hiwr's own FRAME_DIR)
def fg_run():
    """research/fullgrid/run.py, loaded once read-only under its own name (a test of the full grid may load and patch
    another copy)."""
    name = "hiwr_fullgrid_run"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(FULLGRID, "run.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def build_frame(arrays: dict, tf: str):
    """(chart bars, close ms) of one coin from its (cut) 1m arrays by run.build_frame, unchanged: only its data source
    is pointed at ``arrays`` for the call."""
    R = fg_run()
    old = R.minute_data
    R.minute_data = lambda _d, _s: arrays
    try:
        return R.build_frame("hiwr", "hiwr", tf)
    finally:
        R.minute_data = old


def frame_path(frame_dir: str, sym: str, tf: str) -> str:
    return os.path.join(frame_dir, f"{tf}_{sym}.pkl")      # run.frame's own naming


def make_frames(arrays: dict, sym: str, tfs, frame_dir: str) -> dict:
    """Build (or reuse) the chart frames of ``sym`` in ``frame_dir`` from the cut arrays; {tf: (df, close ms)}."""
    R = fg_run()
    os.makedirs(frame_dir, exist_ok=True)
    out = {}
    for tf in tfs:
        p = frame_path(frame_dir, sym, tf)
        if os.path.exists(p):
            df = pd.read_pickle(p)
            df.attrs["tf"] = tf
            out[tf] = (df, (df["ts"].astype("int64").to_numpy() // 1_000_000) + R.TF_MS[tf])
            continue
        df, close = build_frame(arrays, tf)
        tmp = f"{p}.{os.getpid()}.tmp"
        df.to_pickle(tmp)
        os.replace(tmp, p)
        out[tf] = (df, close)
    return out


def use_frames(frame_dir: str):
    """Point run.frame (and so run.signals) at hiwr's frame folder; a frame missing there raises instead of being
    built from the full grid's own 1m data. Returns a function that undoes it."""
    R = fg_run()
    old_dir, old_md = R.FRAME_DIR[0], R.minute_data

    def refuse(data_dir, sym):
        raise RuntimeError(f"hiwr: frame {sym} not in {frame_dir} (built only from the period-cut arrays)")
    R.FRAME_DIR[0] = frame_dir
    R.minute_data = refuse
    R.frame.cache_clear()

    def undo():
        R.FRAME_DIR[0] = old_dir
        R.minute_data = old_md
        R.frame.cache_clear()
    return undo


# ------------------------------------------------------------------ cross-checks before the pin (section 3)
def check_fg1m(mine: dict, fg: dict, end_ms: int, rel: float = 1e-9, limit: float = 1e-4) -> dict:
    """(i) the old six: hiwr's 1m bars against the full grid's archive on every minute both have before ``end_ms``;
    a minute differs when any of o h l c v mo mh ml mc differs by more than ``rel`` relative."""
    a = mine["ts"] < end_ms
    b = fg["ts"] < end_ms
    common, ia, ib = np.intersect1d(mine["ts"][a], fg["ts"][b], return_indices=True)
    bad = np.zeros(len(common), bool)
    per = {}
    for k in ("o", "h", "l", "c", "v", "mo", "mh", "ml", "mc"):
        x, y = mine[k][a][ia], fg[k][b][ib]
        with np.errstate(invalid="ignore", divide="ignore"):
            d = np.abs(x - y) > rel * np.maximum(np.abs(x), np.abs(y))
        per[k] = int(d.sum())
        bad |= d
    share = float(bad.mean()) if len(common) else 0.0
    return {"common_minutes": int(len(common)), "only_mine": int(a.sum() - len(common)),
            "only_fg": int(b.sum() - len(common)), "differing": int(bad.sum()), "per_array": per, "share": share,
            "pass": bool(len(common) > 0 and share <= limit)}


def resample_5m(arrays: dict) -> dict:
    """UTC 5m bins of 1m bars: first open, max high, min low, last close, summed volumes."""
    ts = arrays["ts"]
    b = ts // 300_000
    cut = np.flatnonzero(np.diff(b)) + 1
    st = np.r_[0, cut]
    en = np.r_[cut, len(ts)]
    out = {"ts": b[st] * 300_000, "o": arrays["o"][st], "h": np.maximum.reduceat(arrays["h"], st),
           "l": np.minimum.reduceat(arrays["l"], st), "c": arrays["c"][en - 1], "v": np.add.reduceat(arrays["v"], st),
           "n": en - st}
    if "qv" in arrays:
        out["qv"] = np.add.reduceat(arrays["qv"], st)
    return out


def check_5m(mine_1m: dict, hunt5: dict, end_ms: int, rel_px: float = 1e-6, rel_v: float = 1e-3,
             need: float = 0.999) -> dict:
    """(ii) all 30 coins: hiwr's 1m bars resampled to 5m against the hunt's 5m bars (with volume) before ``end_ms``,
    on every 5m bar both have: OHLC within ``rel_px``, base volume within ``rel_v`` relative."""
    r = resample_5m({k: v[mine_1m["ts"] < end_ms] for k, v in mine_1m.items() if k in ("ts", "o", "h", "l", "c", "v", "qv")})
    hv = hunt5["v"] > 0
    keep = (hunt5["ts"] < end_ms) & hv
    common, ia, ib = np.intersect1d(r["ts"], hunt5["ts"][keep], return_indices=True)
    ok = np.ones(len(common), bool)
    for k in ("o", "h", "l", "c"):
        x, y = r[k][ia], hunt5[k][keep][ib]
        ok &= np.abs(x - y) <= rel_px * np.maximum(np.abs(x), np.abs(y))
    x, y = r["v"][ia], hunt5["v"][keep][ib]
    ok &= np.abs(x - y) <= rel_v * np.maximum(np.abs(x), np.abs(y))
    share = float(ok.mean()) if len(common) else 0.0
    return {"common_bars": int(len(common)), "matching": int(ok.sum()), "share": share,
            "pass": bool(len(common) > 0 and share >= need)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("download", "build", "all"))
    ap.add_argument("--dir", required=True)
    ap.add_argument("--first", default=KIT_SEL[0])
    ap.add_argument("--last", default=KIT_SEL[1])
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    a = ap.parse_args(argv)
    syms = tuple(a.symbols.split(","))
    if a.step in ("download", "all"):
        download(a.dir, a.first, a.last, syms, a.procs)
    if a.step in ("build", "all"):
        build(a.dir, a.first, a.last, syms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
