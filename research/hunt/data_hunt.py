"""Hunt data kit: Binance USD-M public archives -> the npz files research/hunt reads (and the 1m fidelity set).

This is the repository copy of the coins30 builder that made the data the hunt studies were pinned on (the scratch
``c30.py download`` plus ``c30_fill.py``): the same listing source (the S3 listing of data.binance.vision), the same
``.CHECKSUM`` (sha256) check of every zip, the same conversion (pandas read, microsecond times to ms, duplicate open
times keep the last, mark price left-joined on the kline open time, int64 / float32 arrays) and the same second pass
that fills whole days missing from the monthly archives from the daily archives (only absent bars are inserted and only
NaN mark values filled; monthly values are never overwritten). Public price data only: no key of any kind.

    python -m research.hunt.data_hunt download --kind 5m --out DIR [--workers 8]
    python -m research.hunt.data_hunt download --kind fidelity --out DIR --symbols A,B [--from 2024-01 --to 2026-09]
    python -m research.hunt.data_hunt verify --data DIR --ref research/hunt/data_ref_5m.json [--report FILE]
    python -m research.hunt.data_hunt refman --data DIR --out research/hunt/data_ref_5m.json
    python -m research.hunt.data_hunt prove --symbol BTCUSDT --month 2024-01 --ref-data DIR --work DIR
    python -m research.hunt.data_hunt symbols [--universe-md FILE]
    python -m research.hunt.data_hunt coins --tests T1.json [T2.json ...]

Symbols: ``--symbols A,B`` or, without it, ``research/hunt/universe30.json`` when it exists, else the table of the
``--universe-md`` file (coins30 UNIVERSE.md). Range: kind 5m 2020-01..2026-09 (as coins30), kind fidelity
2024-01..2026-09 (the test period); ``--from`` / ``--to`` change it.

Files written (both kinds; ``<sub>`` = ``5m`` or ``1m``):

* ``<out>/<sub>/<SYM>.npz``: ``ts`` int64 open time (ms, UTC); ``o h l c`` float32 last-price OHLC; ``v`` float32 base
  volume; ``qv`` float32 quote volume; ``mo mh ml mc`` float32 mark-price OHLC (NaN where the bar has no mark bar).
  Rows are raw exchange bars: nothing forward-filled or synthesized, zero-volume bars kept.
* ``<out>/funding/<SYM>.npz``: ``ts`` int64 calc_time (ms, UTC); ``rate`` float64 last_funding_rate.
* ``<out>/manifest.json``: per coin the coverage fields of coins30 (the hunt reads ``last_nonzero_volume_bar``,
  ``last_bar`` and ``missing_months_funding`` from it), the sha256 of every source zip, of each converted file and of
  its array content (``arrays_sha256``: keys, dtypes, shapes and bytes; independent of the zip container).
* ``<out>/state.json`` (resume), ``<out>/params.json``, ``<out>/download.log``, ``<out>/COMPLETE`` when every coin
  is done. Zips are deleted once a coin is converted. A rerun skips finished coins and downloaded zips.

npz files are written with a fixed zip timestamp, so the same arrays give the same file bytes on one machine. The
coins30 files were written by ``np.savez_compressed`` (timestamped), so the comparison with them is on array content:
``verify`` compares a new manifest with the pinned reference (``refman`` makes it from an existing data folder).
No price outcome of any kind is computed here.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
UNIVERSE30 = os.path.join(ROOT, "research", "hunt", "universe30.json")

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/"
DAY = 86_400_000
HOUR = 3_600_000
KINDS = {"5m": {"interval": "5m", "step": 300_000, "sub": "5m", "range": ("2020-01", "2026-09")},
         "fidelity": {"interval": "1m", "step": 60_000, "sub": "1m", "range": ("2024-01", "2026-09")}}
RETRY_SLEEP = 3.0                 # seconds between checksum retries (tests set 0)
MIN_FREE = 1 * 1024 ** 3          # stop when the output disk has less than this free
# Fields of a coin that must equal the pinned reference (the hunt reads the last three of the first line).
VERIFY_FIELDS = ("first_bar", "last_bar", "last_nonzero_volume_bar", "missing_months_funding",
                 "rows", "missing_months_klines", "missing_months_mark", "funding_rows", "bars_without_mark",
                 "zero_volume_bars", "first_month", "last_month")


class DataError(RuntimeError):
    pass


# ------------------------------------------------------------------ sources
class HttpSource:
    """data.binance.vision: S3 listing for the months, plain GET for the files (as c30.py)."""

    def __init__(self, cafile: str | None = None, tries: int = 6):
        cafile = cafile or os.environ.get("HUNT_CA_BUNDLE") or None
        self.ctx = ssl.create_default_context(cafile=cafile)
        self.tries = tries

    def _get(self, url: str):
        last = None
        for i in range(self.tries):
            try:
                with urllib.request.urlopen(url, context=self.ctx, timeout=120) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                last = e
            except Exception as e:  # network hiccup
                last = e
            time.sleep(min(30, 2 * (i + 1)))
        raise RuntimeError(f"GET failed {url}: {last}")

    def list(self, prefix: str) -> tuple:
        """(common_prefixes, keys) directly under ``prefix``, following pagination."""
        prefixes, keys, marker = [], [], ""
        ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
        while True:
            q = {"prefix": prefix, "delimiter": "/"}
            if marker:
                q["marker"] = marker
            body = self._get(S3 + "?" + urllib.parse.urlencode(q))
            if body is None:
                raise RuntimeError(f"listing failed for {prefix}")
            root = ET.fromstring(body)
            for cp in root.findall(ns + "CommonPrefixes"):
                prefixes.append(cp.find(ns + "Prefix").text)
            for c in root.findall(ns + "Contents"):
                keys.append(c.find(ns + "Key").text)
            if root.find(ns + "IsTruncated").text != "true":
                break
            nm = root.find(ns + "NextMarker")
            marker = nm.text if nm is not None else (keys[-1] if keys else prefixes[-1])
        return prefixes, keys

    def fetch(self, key: str):
        return self._get(DL + key)


class DirSource:
    """A local folder with the same key layout as data.binance.vision (tests, rehearsal, an offline mirror)."""

    def __init__(self, root: str):
        self.root = root

    def list(self, prefix: str) -> tuple:
        d = os.path.join(self.root, prefix)
        if not os.path.isdir(d):
            return [], []
        prefixes, keys = [], []
        for name in sorted(os.listdir(d)):
            if os.path.isdir(os.path.join(d, name)):
                prefixes.append(prefix + name + "/")
            else:
                keys.append(prefix + name)
        return prefixes, keys

    def fetch(self, key: str):
        p = os.path.join(self.root, key)
        if not os.path.isfile(p):
            return None
        with open(p, "rb") as fh:
            return fh.read()


# ------------------------------------------------------------------ small helpers (as c30.py)
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def months_from_keys(keys, sym, stem) -> dict:
    """stem e.g. '5m' or 'fundingRate'. Returns {month: has_checksum}."""
    pat = re.compile(re.escape(f"{sym}-{stem}-") + r"(\d{4}-\d{2})\.zip$")
    zips, cks = set(), set()
    for k in keys:
        base = k.rsplit("/", 1)[-1]
        m = pat.match(base)
        if m:
            zips.add(m.group(1))
        elif base.endswith(".zip.CHECKSUM"):
            m2 = pat.match(base[: -len(".CHECKSUM")])
            if m2:
                cks.add(m2.group(1))
    return {m: (m in cks) for m in sorted(zips)}


def month_range(a: str, b: str) -> list:
    y, m = map(int, a.split("-"))
    y2, m2 = map(int, b.split("-"))
    out = []
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def month_ms(m: str) -> int:
    return int(pd.Timestamp(m + "-01", tz="UTC").value // 1_000_000)


def next_month(m: str) -> str:
    y, mm = map(int, m.split("-"))
    return f"{y + (mm == 12):04d}-{(mm % 12) + 1:02d}"


def ym(t: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t / 1000))


def dstr(d: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(d * DAY / 1000))


def to_ms(ts):
    ts = ts.astype(np.int64)
    us = ts > 10 ** 14            # microsecond timestamps -> ms
    ts[us] //= 1000
    return ts


def read_kline_zip(path: str, usecols):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        frames = []
        for n in names:
            raw = z.read(n)
            if not raw.strip():
                continue
            first = raw[:64].lstrip()
            skip = 0 if first[:1].isdigit() else 1
            df = pd.read_csv(io.BytesIO(raw), header=None, skiprows=skip, usecols=usecols)
            frames.append(df)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def save_npz(path: str, arrays: dict) -> None:
    """np.savez_compressed with a fixed member timestamp (same arrays -> same bytes); read with np.load."""
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for k, v in arrays.items():
            zi = zipfile.ZipInfo(k + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            with zf.open(zi, "w", force_zip64=True) as fh:
                np.lib.format.write_array(fh, np.asanyarray(v), allow_pickle=False)
    os.replace(tmp, path)


def arrays_sha256(path: str) -> str:
    """sha256 of an npz's content: for each key in sorted order its name, dtype, shape and raw bytes."""
    h = hashlib.sha256()
    with np.load(path, allow_pickle=False) as z:
        for k in sorted(z.files):
            a = np.ascontiguousarray(z[k])
            h.update(f"{k}|{a.dtype.str}|{a.shape}\n".encode())
            h.update(a.tobytes())
    return h.hexdigest()


class Log:
    def __init__(self, path: str | None):
        self.path = path

    def __call__(self, msg: str) -> None:
        line = time.strftime("%Y-%m-%d %H:%M:%S ", time.gmtime()) + msg
        print(line, flush=True)
        if self.path:
            with open(self.path, "a") as f:
                f.write(line + "\n")


def fetch_verified(src, key: str, dest: str, has_ck: bool, log=print) -> tuple:
    """Download key to dest and check it against its .CHECKSUM when the listing has one.
    Returns (status, sha256 of the zip): status ok / nock (no checksum file) / 404 / mismatch.
    Resume: a dest with its '.ok' file is not fetched again."""
    ok = dest + ".ok"
    if os.path.exists(dest) and os.path.exists(ok):
        with open(ok) as fh:
            parts = fh.read().split()
        st = parts[0] if parts else "ok"
        return st, (parts[1] if len(parts) > 1 else sha256_file(dest))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(4):
        data = src.fetch(key)
        if data is None:
            return "404", None
        status = "nock"
        got = sha256_bytes(data)
        if has_ck:
            ck = src.fetch(key + ".CHECKSUM")
            if ck is not None:
                want = ck.decode().split()[0].strip().lower()
                if want != got:
                    log(f"CHECKSUM MISMATCH {key} attempt {attempt}")
                    time.sleep(RETRY_SLEEP)
                    continue
                status = "ok"
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        with open(ok, "w") as f:
            f.write(f"{status} {got}")
        return status, got
    return "mismatch", None


# ------------------------------------------------------------------ build one coin
def _prefixes(sym: str, iv: str) -> dict:
    return {"kl": (f"data/futures/um/monthly/klines/{sym}/{iv}/", iv),
            "mk": (f"data/futures/um/monthly/markPriceKlines/{sym}/{iv}/", iv),
            "fr": (f"data/futures/um/monthly/fundingRate/{sym}/", "fundingRate")}


def _fetch_days(src, sym: str, kind: str, iv: str, days, raw: str, workers: int, log) -> tuple:
    """Daily archive files of ``days`` (kind 'klines' or 'markPriceKlines'). Returns (DataFrame or None,
    {day: status}, {key: sha256})."""
    stat, frames, shas = {}, [], {}

    def one(d):
        ds = dstr(d)
        key = f"data/futures/um/daily/{kind}/{sym}/{iv}/{sym}-{iv}-{ds}.zip"
        dest = os.path.join(raw, "daily_" + kind, f"{sym}-{iv}-{ds}.zip")
        st, h = fetch_verified(src, key, dest, True, log)
        return d, key, dest, st, h

    with ThreadPoolExecutor(workers) as ex:
        for d, key, dest, st, h in ex.map(one, sorted(days)):
            stat[dstr(d)] = st
            if st in ("404", "mismatch"):
                continue
            shas[key] = h
            cols = [0, 1, 2, 3, 4, 5, 7] if kind == "klines" else [0, 1, 2, 3, 4]
            df = read_kline_zip(dest, cols)
            if df is not None:
                frames.append(df)
    if not frames:
        return None, stat, shas
    df = pd.concat(frames, ignore_index=True)
    df = df[pd.to_numeric(df[0], errors="coerce").notna()].copy()
    df[0] = to_ms(df[0].astype(np.int64).values)
    return df.drop_duplicates(0, keep="last"), stat, shas


def build_symbol(src, sym: str, kind: str, out: str, first: str, last: str, workers: int = 8,
                 log=print) -> dict:
    """Download, check and convert one coin (monthly archives, then the daily fill); returns its manifest entry."""
    K = KINDS[kind]
    iv, step, sub = K["interval"], K["step"], K["sub"]
    t0 = time.time()
    raw = os.path.join(out, "raw", sym)
    kinds = _prefixes(sym, iv)
    avail = {}
    for k, (pfx, stem) in kinds.items():
        _, keys = src.list(pfx)
        ms = months_from_keys(keys, sym, stem)
        avail[k] = {m: c for m, c in ms.items() if first <= m <= last}
    if not avail["kl"]:
        raise DataError(f"{sym}: no {iv} kline months in {first}..{last}")
    kl_first, kl_last = min(avail["kl"]), max(avail["kl"])
    span = month_range(kl_first, kl_last)
    jobs = []
    for k, (pfx, stem) in kinds.items():
        for m, has_ck in avail[k].items():
            if m < kl_first:
                continue
            key = f"{pfx}{sym}-{stem}-{m}.zip"
            jobs.append((k, m, key, os.path.join(raw, k, f"{sym}-{stem}-{m}.zip"), has_ck))
    log(f"{sym}: {len(jobs)} files (kl {len(avail['kl'])}, mk {len(avail['mk'])}, fr {len(avail['fr'])}) "
        f"span {kl_first}..{kl_last}")
    status, zsha = {}, {}

    def one(j):
        k, m, key, dest, has_ck = j
        st, h = fetch_verified(src, key, dest, has_ck, log)
        return k, m, key, st, h

    with ThreadPoolExecutor(workers) as ex:
        for i, (k, m, key, st, h) in enumerate(ex.map(one, jobs)):
            status[(k, m)] = st
            if h:
                zsha[key] = h
            if (i + 1) % 60 == 0:
                free = shutil.disk_usage(out).free
                log(f"{sym}: {i + 1}/{len(jobs)} files, free {free / 1e9:.2f} GB")
                if free < MIN_FREE:
                    raise SystemExit(f"ABORT: free disk below {MIN_FREE / 1e9:.1f} GB while downloading {sym}")
    bad = {f"{k}:{m}": st for (k, m), st in status.items() if st in ("404", "mismatch")}
    ck_counts = {}
    for st in status.values():
        ck_counts[st] = ck_counts.get(st, 0) + 1

    def load_kind(k, cols):
        frames = []
        stem = "fundingRate" if k == "fr" else iv
        for m in sorted(avail[k]):
            if m < kl_first or status.get((k, m)) in ("404", "mismatch"):
                continue
            df = read_kline_zip(os.path.join(raw, k, f"{sym}-{stem}-{m}.zip"), cols)
            if df is not None:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else None

    # --- klines + mark (c30.build_symbol)
    kl = load_kind("kl", [0, 1, 2, 3, 4, 5, 7])
    if kl is None:
        raise DataError(f"{sym}: no readable kline file")
    kl.columns = ["ts", "o", "h", "l", "c", "v", "qv"]
    kl = kl[pd.to_numeric(kl["ts"], errors="coerce").notna()].copy()
    kl["ts"] = to_ms(kl["ts"].astype(np.int64).values)
    n_read = len(kl)
    kl = kl.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)
    n_dup = n_read - len(kl)
    mk = load_kind("mk", [0, 1, 2, 3, 4])
    if mk is not None:
        mk.columns = ["ts", "mo", "mh", "ml", "mc"]
        mk = mk[pd.to_numeric(mk["ts"], errors="coerce").notna()].copy()
        mk["ts"] = to_ms(mk["ts"].astype(np.int64).values)
        mk = mk.drop_duplicates("ts", keep="last")
        merged = kl.merge(mk, on="ts", how="left")
    else:
        merged = kl.assign(mo=np.nan, mh=np.nan, ml=np.nan, mc=np.nan)
    ts = merged["ts"].values.astype(np.int64)
    a = {"ts": ts}
    for c in ["o", "h", "l", "c", "v", "qv", "mo", "mh", "ml", "mc"]:
        a[c] = merged[c].values.astype(np.float32)
    last_bar_pre = int(ts[-1])

    # --- funding
    fr = load_kind("fr", None)
    fts = rate = None
    if fr is not None:
        # columns: calc_time, funding_interval_hours, last_funding_rate
        fr = fr[pd.to_numeric(fr[0], errors="coerce").notna()]
        fts = to_ms(fr[0].astype(np.int64).values)
        rate = fr[fr.columns[-1]].astype(np.float64).values
        o = np.argsort(fts, kind="stable")
        fts, rate = fts[o], rate[o]
        keep = np.ones(len(fts), bool)
        keep[1:] = fts[1:] != fts[:-1]
        fts, rate = fts[keep], rate[keep]
        if not len(fts):
            fts = rate = None

    # --- daily fill (c30_fill.py): kline holes > 1h, mark holes >= 1h of a day while the coin traded
    nz = np.flatnonzero(a["v"] > 0)
    d = np.diff(ts)
    kdays = set()
    for i in np.flatnonzero(d > HOUR):
        for dd in range(int((ts[i] + step) // DAY), int((ts[i + 1] - step) // DAY) + 1):
            kdays.add(dd)
    mdays = set(kdays)
    if len(nz):
        nanmask = np.isnan(a["mc"]) & (ts <= int(ts[nz[-1]]))
        ddu, cnt = np.unique(ts[nanmask] // DAY, return_counts=True)
        mdays |= {int(x) for x, c in zip(ddu, cnt) if c >= HOUR // step}
    fill = {"kline_days": [dstr(x) for x in sorted(kdays)], "mark_days": [dstr(x) for x in sorted(mdays)],
            "kline_rows_added": 0, "mark_bars_filled": 0, "daily_status": {}}
    if kdays:
        kdf, st, shas = _fetch_days(src, sym, "klines", iv, kdays, raw, workers, log)
        fill["daily_status"]["klines"] = st
        zsha.update(shas)
        if kdf is not None:
            kdf = kdf[~np.isin(kdf[0].values, ts)]
            kdf = kdf[(kdf[0] >= ts[0]) & (kdf[0] <= ts[-1])]
            if len(kdf):
                n = len(kdf)
                new = {"ts": kdf[0].values.astype(np.int64)}
                for c, j in zip(["o", "h", "l", "c", "v", "qv"], [1, 2, 3, 4, 5, 7]):
                    new[c] = kdf[j].values.astype(np.float32)
                for c in ["mo", "mh", "ml", "mc"]:
                    new[c] = np.full(n, np.nan, np.float32)
                for k in a:
                    a[k] = np.concatenate([a[k], new[k]])
                o = np.argsort(a["ts"], kind="stable")
                a = {k: v[o] for k, v in a.items()}
                ts = a["ts"]
                fill["kline_rows_added"] = int(n)
    if mdays:
        mdf, st, shas = _fetch_days(src, sym, "markPriceKlines", iv, mdays, raw, workers, log)
        fill["daily_status"]["mark"] = st
        zsha.update(shas)
        if mdf is not None:
            mdf = mdf.set_index(0)
            need = np.flatnonzero(np.isnan(a["mc"]))
            hit = np.isin(ts[need], mdf.index.values)
            idx = need[hit]
            if len(idx):
                sub_df = mdf.loc[ts[idx]]
                for c, j in zip(["mo", "mh", "ml", "mc"], [1, 2, 3, 4]):
                    a[c][idx] = sub_df[j].values.astype(np.float32)
                fill["mark_bars_filled"] = int(len(idx))

    # --- write
    for dname in (sub, "funding"):
        os.makedirs(os.path.join(out, dname), exist_ok=True)
    outp = os.path.join(out, sub, f"{sym}.npz")
    save_npz(outp, a)
    outf = os.path.join(out, "funding", f"{sym}.npz")
    if fts is not None:
        save_npz(outf, {"ts": fts, "rate": rate})
    elif os.path.exists(outf):
        os.remove(outf)

    # --- coverage (data quality only; no trading quantity)
    ts = a["ts"]
    d = np.diff(ts)
    nz = np.flatnonzero(a["v"] > 0)
    lt = int(ts[nz[-1]]) if len(nz) else None
    trailing = int(len(ts) - 1 - nz[-1]) if len(nz) else int(len(ts))

    def miss(k):
        return [m for m in span if m not in avail[k] or status.get((k, m)) in ("404", "mismatch")]

    info = {
        "symbol": sym, "kind": kind, "interval": iv,
        "first_month": kl_first, "last_month": kl_last, "ends_before_range_end": kl_last < last,
        "rows": int(len(ts)), "first_bar": ym(int(ts[0])), "last_bar": ym(last_bar_pre),
        "missing_months_klines": miss("kl"), "missing_months_mark": miss("mk"), "missing_months_funding": miss("fr"),
        f"missing_{iv}_bars_inside_span": int(((d // step) - 1)[d > step].sum()),
        "gaps_over_1h": int((d > HOUR).sum()), "largest_gap_hours": round(float(d.max() / HOUR), 2) if len(d) else 0.0,
        "off_grid_ts": int((ts % step != 0).sum()), "duplicate_rows_dropped": int(n_dup),
        "bars_without_mark": int(np.isnan(a["mc"]).sum()),
        "bars_without_mark_while_trading": int((np.isnan(a["mc"]) & (ts <= lt)).sum()) if lt is not None else 0,
        "zero_volume_bars": int((a["v"] == 0).sum()),
        "last_nonzero_volume_bar": ym(lt) if lt is not None else None,
        "trailing_zero_volume_bars": trailing,
        "trailing_zero_volume_days": round(trailing * (step / 60_000) / 1440, 1),
        "traded_to_range_end": bool(lt is not None and lt >= ts[-1] - DAY and kl_last == last),
        "funding_rows": int(len(fts)) if fts is not None else 0,
        "funding_first": ym(int(fts[0])) if fts is not None else None,
        "funding_last": ym(int(fts[-1])) if fts is not None else None,
        "download_problems": bad, "checksum_status_counts": ck_counts,
        f"npz_{iv}": os.path.relpath(outp, out), f"npz_{iv}_bytes": os.path.getsize(outp),
        f"sha256_{iv}": sha256_file(outp), "arrays_sha256": arrays_sha256(outp),
        "npz_funding": os.path.relpath(outf, out) if fts is not None else None,
        "npz_funding_bytes": os.path.getsize(outf) if fts is not None else 0,
        "sha256_funding": sha256_file(outf) if fts is not None else None,
        "arrays_sha256_funding": arrays_sha256(outf) if fts is not None else None,
        "daily_fill": fill,
    }
    if fts is not None and lt is not None:
        info["funding_rows_after_last_traded_bar"] = int((fts > lt).sum())
        fin = fts[fts <= lt]
        fd = np.diff(fin)
        info["funding_gaps_over_8h_while_trading"] = int((fd > 8 * HOUR + 300_000).sum())
        info["funding_largest_gap_hours_while_trading"] = round(float(fd.max() / HOUR), 2) if len(fd) else None
    if lt is not None:
        lm = time.strftime("%Y-%m", time.gmtime(lt / 1000))
        for k in ("funding", "klines", "mark"):
            info[f"missing_months_{k}_while_trading"] = [m for m in info[f"missing_months_{k}"] if m <= lm]
    info["source_zips"] = dict(sorted(zsha.items()))
    info["build_seconds"] = round(time.time() - t0, 1)
    shutil.rmtree(raw, ignore_errors=True)          # delete zips after conversion
    return info


# ------------------------------------------------------------------ the download command
def _load_json(p: str, default=None):
    if not os.path.exists(p):
        return default
    with open(p) as fh:
        return json.load(fh)


def _dump_json(p: str, obj) -> None:
    tmp = p + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, p)


def write_manifest(out: str, state: dict, syms: list, params: dict) -> dict:
    K = KINDS[params["kind"]]
    iv = K["interval"]
    done = [state[s] for s in syms if s in state]
    man = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "source": "https://data.binance.vision (Binance USD-M futures monthly archives, daily archives for whole "
                  "missing days)",
        "builder": {"code": "research/hunt/data_hunt.py", "code_sha256": sha256_file(os.path.abspath(__file__)),
                    "numpy": np.__version__, "pandas": pd.__version__, "python": sys.version.split()[0]},
        "kind": params["kind"], "range": [params["from"], params["to"]], "universe": list(syms),
        "format": {iv: f"np.savez_compressed layout (fixed zip timestamps); keys ts(int64 ms open time UTC),o,h,l,c,"
                       f"v(base vol),qv(quote vol),mo,mh,ml,mc (mark price OHLC, NaN where no mark bar); all float32 "
                       f"except ts; file <{K['sub']}>/<SYM>.npz",
                   "funding": "keys ts(int64 ms calc_time UTC), rate(float64 last_funding_rate); "
                              "file funding/<SYM>.npz",
                   "arrays_sha256": "sha256 over the sorted keys: name|dtype|shape newline, then the raw bytes"},
        "notes": ["rows are raw exchange bars: nothing forward-filled or synthesized, zero-volume bars kept",
                  "ts converted to ms if source used microseconds",
                  "every monthly and daily zip was checked against its .CHECKSUM (sha256) when the listing has one; "
                  "see checksum_status_counts, daily_fill.daily_status and source_zips",
                  "whole days missing from the monthly archives were filled from the daily archives (daily_fill), "
                  "inserting only absent bars / NaN mark values",
                  "after a coin stops trading the archive can keep producing flat zero-volume bars and fixed funding "
                  "rows: use last_nonzero_volume_bar as the end of the tradable period"],
        "n_symbols_done": len(done), "n_symbols_universe": len(syms),
        "total_npz_bytes": sum(r.get(f"npz_{iv}_bytes", 0) + r.get("npz_funding_bytes", 0) for r in done),
        "symbols": done,
    }
    _dump_json(os.path.join(out, "manifest.json"), man)
    return man


def download(src, syms: list, kind: str, out: str, first: str, last: str, workers: int = 8, log=None) -> int:
    """Build every coin of ``syms`` into ``out`` (resumable). Returns 0 when all are done, 1 otherwise."""
    os.makedirs(out, exist_ok=True)
    log = log or Log(os.path.join(out, "download.log"))
    params = {"kind": kind, "from": first, "to": last}
    pp = os.path.join(out, "params.json")
    old = _load_json(pp)
    if old is not None and old != params:
        raise DataError(f"{out} was built with {old}, not {params}: use a new folder")
    _dump_json(pp, params)
    state = _load_json(os.path.join(out, "state.json"), {})
    iv = KINDS[kind]["interval"]
    comp = os.path.join(out, "COMPLETE")
    if os.path.exists(comp):
        os.remove(comp)
    log(f"download {kind}: start, {len(syms)} coins, {first}..{last}, already done "
        f"{sum(1 for s in syms if s in state)}, workers {workers}")
    failed = []
    for n, sym in enumerate(syms, 1):
        info = state.get(sym)
        if info and os.path.exists(os.path.join(out, info[f"npz_{iv}"])) \
                and sha256_file(os.path.join(out, info[f"npz_{iv}"])) == info[f"sha256_{iv}"]:
            log(f"[data {n}/{len(syms)}] {sym}: already done")
            continue
        if shutil.disk_usage(out).free < MIN_FREE:
            log(f"ABORT: free disk below {MIN_FREE / 1e9:.1f} GB before {sym}")
            return 2
        try:
            info = build_symbol(src, sym, kind, out, first, last, workers, log)
        except SystemExit as e:
            log(str(e))
            return 2
        except Exception as e:
            log(f"ERROR {sym}: {e!r} (rerun to resume)")
            failed.append(sym)
            continue
        state[sym] = info
        _dump_json(os.path.join(out, "state.json"), state)
        write_manifest(out, state, syms, params)
        log(f"[data {n}/{len(syms)}] {sym}: rows {info['rows']} {info['first_bar']}..{info['last_bar']}, "
            f"problems {len(info['download_problems'])}, fill +{info['daily_fill']['kline_rows_added']} rows "
            f"/ {info['daily_fill']['mark_bars_filled']} marks, {info['build_seconds']}s")
    man = write_manifest(out, state, syms, params)
    try:
        os.rmdir(os.path.join(out, "raw"))         # only when empty (every coin converted)
    except OSError:
        pass
    done = [s for s in syms if s in state]
    if len(done) == len(syms) and not failed:
        with open(comp, "w") as fh:
            fh.write(json.dumps({"symbols": syms, "kind": kind, "range": [first, last],
                                 "manifest_symbols": man["n_symbols_done"]}) + "\n")
        log(f"download {kind}: finished {len(done)}/{len(syms)}")
        return 0
    log(f"download {kind}: {len(done)}/{len(syms)} done, failed {failed} (rerun to resume)")
    return 1


# ------------------------------------------------------------------ symbols
def symbols_from_md(path: str) -> list:
    """The universe of a coins30 UNIVERSE.md: its 'Universe (copy-paste):' line, else the table after
    '## The 30 coins' (rows '| rank | SYMBOL | ...')."""
    txt = open(path).read()
    for line in txt.splitlines():
        if line.startswith("Universe (copy-paste):"):
            syms = line.split(":", 1)[1].split()
            if syms:
                return syms
    syms, inside = [], False
    for line in txt.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.strip().lower().startswith("## the 30 coins")
            continue
        if inside and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0].isdigit() and re.fullmatch(r"[A-Z0-9]+USDT", cells[1]):
                syms.append(cells[1])
    if not syms:
        raise DataError(f"{path}: no universe table found")
    return syms


def resolve_symbols(symbols: str | None, universe_md: str | None, universe_json: str = UNIVERSE30) -> tuple:
    if symbols:
        return [s.strip() for s in symbols.replace(",", " ").split() if s.strip()], "--symbols"
    if os.path.exists(universe_json):
        with open(universe_json) as fh:
            return list(json.load(fh)["symbols"]), os.path.relpath(universe_json, ROOT)
    if universe_md:
        return symbols_from_md(universe_md), universe_md
    raise DataError("no symbols: give --symbols, create research/hunt/universe30.json or pass --universe-md")


def coins_from_tests(paths: list, universe: list) -> tuple:
    """Coins the picks traded, from test outputs that list them (keys 'coins_traded' / 'traded_coins' lists, or
    'by_coin' / 'positions_by_coin' maps with a count > 0). Without any, the whole universe."""
    found = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("coins_traded", "traded_coins") and isinstance(v, list):
                    found.update(str(s) for s in v)
                elif k in ("by_coin", "positions_by_coin") and isinstance(v, dict):
                    for s, n in v.items():
                        cnt = n.get("n", 0) if isinstance(n, dict) else n
                        if isinstance(cnt, (int, float)) and cnt > 0:
                            found.add(str(s))
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for p in paths:
        if os.path.exists(p):
            walk(_load_json(p))
    if found:
        order = [s for s in universe if s in found] + sorted(found - set(universe))
        return order, "test outputs"
    return list(universe), "all coins (the test outputs list no coins)"


# ------------------------------------------------------------------ reference and verify
def _norm_ref(ref: dict) -> dict:
    syms = ref.get("symbols", {})
    if isinstance(syms, list):
        return {r["symbol"]: r for r in syms}
    return dict(syms)


def make_ref(data: str, sub: str = "5m") -> dict:
    """Reference of an existing data folder: coverage fields from its manifest.json and the array-content sha256 of
    every converted file (files checked against the manifest's file sha256 first)."""
    mp = os.path.join(data, "manifest.json")
    man = _load_json(mp)
    if man is None:
        raise DataError(f"{mp} missing")
    iv = sub
    out = {}
    for r in man["symbols"]:
        s = r["symbol"]
        p5 = os.path.join(data, sub, f"{s}.npz")
        pf = os.path.join(data, "funding", f"{s}.npz")
        want5 = r.get(f"sha256_{iv}")
        if want5 and sha256_file(p5) != want5:
            raise DataError(f"{p5}: file differs from {mp}")
        if r.get("sha256_funding") and sha256_file(pf) != r["sha256_funding"]:
            raise DataError(f"{pf}: file differs from {mp}")
        e = {f: r.get(f) for f in VERIFY_FIELDS if f in r}
        e["arrays_sha256"] = arrays_sha256(p5)
        e["arrays_sha256_funding"] = arrays_sha256(pf) if os.path.exists(pf) else None
        e["file_sha256"] = want5
        e["file_sha256_funding"] = r.get("sha256_funding")
        out[s] = e
    uni = _load_json(os.path.join(data, "universe.json"), {}) or {}
    return {"kind": "hunt-data-ref", "sub": sub,
            "what": "array-content reference of the data the hunt was pinned on (no price outcome)",
            "made_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "source_manifest_sha256": sha256_file(mp), "source_manifest_generated": man.get("generated"),
            "range": man.get("range"), "universe": uni.get("universe") or [r["symbol"] for r in man["symbols"]],
            "verify_fields": list(VERIFY_FIELDS), "symbols": out}


def verify(manifest_path: str, ref_path: str, data: str | None = None, allow_meta_only: bool = False,
           sub: str = "5m") -> dict:
    """Compare a manifest (and, with ``data``, the files on disk) with the pinned reference. Any difference fails."""
    man = _load_json(manifest_path)
    ref_doc = _load_json(ref_path)
    diffs = []
    if man is None:
        raise DataError(f"{manifest_path} missing")
    if ref_doc is None:
        raise DataError(f"{ref_path} missing")
    new, ref = _norm_ref(man), _norm_ref(ref_doc)
    if set(new) != set(ref):
        diffs.append(f"symbols differ: missing {sorted(set(ref) - set(new))}, extra {sorted(set(new) - set(ref))}")
    meta_only = []
    for s in sorted(set(ref) & set(new)):
        r, n = ref[s], new[s]
        for f in VERIFY_FIELDS:
            if f in r and r[f] != n.get(f):
                diffs.append(f"{s}: {f} {n.get(f)!r} != reference {r[f]!r}")
        for f in ("arrays_sha256", "arrays_sha256_funding"):
            if f not in r:
                meta_only.append(f"{s}:{f}")
                continue
            if r.get(f) != n.get(f):
                diffs.append(f"{s}: {f} differs from the reference")
        if data:
            p5 = os.path.join(data, sub, f"{s}.npz")
            pf = os.path.join(data, "funding", f"{s}.npz")
            got5 = arrays_sha256(p5) if os.path.exists(p5) else None
            gotf = arrays_sha256(pf) if os.path.exists(pf) else None
            if got5 != n.get("arrays_sha256"):
                diffs.append(f"{s}: {p5} content differs from its manifest")
            if gotf != n.get("arrays_sha256_funding"):
                diffs.append(f"{s}: {pf} content differs from its manifest")
            if "arrays_sha256" in r and got5 != r["arrays_sha256"]:
                diffs.append(f"{s}: {p5} content differs from the reference")
            if "arrays_sha256_funding" in r and gotf != r["arrays_sha256_funding"]:
                diffs.append(f"{s}: {pf} content differs from the reference")
    if meta_only and not allow_meta_only:
        diffs.append(f"the reference has no array hashes ({len(meta_only)} missing): make it with 'refman'")
    return {"ok": not diffs, "n_symbols": len(ref), "n_checked": len(set(ref) & set(new)),
            "differences": diffs[:200], "n_differences": len(diffs),
            "manifest": manifest_path, "manifest_sha256": sha256_file(manifest_path),
            "reference": ref_path, "reference_sha256": sha256_file(ref_path),
            "files_rechecked": bool(data), "array_hashes_compared": not meta_only,
            "checked_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}


# ------------------------------------------------------------------ one coin-month proof
def prove(src, sym: str, month: str, ref_data: str, work: str, keep: bool = False) -> dict:
    """Build one coin-month (kind 5m) and compare it with the same month of an existing data folder, bit for bit."""
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(work)
    info = build_symbol(src, sym, "5m", work, month, month, workers=2, log=Log(None))
    a0, a1 = month_ms(month), month_ms(next_month(month))
    res = {"symbol": sym, "month": month, "rows_new": info["rows"], "zips": info["source_zips"],
           "checksum_status_counts": info["checksum_status_counts"], "keys": {}}
    pn, pr = os.path.join(work, "5m", f"{sym}.npz"), os.path.join(ref_data, "5m", f"{sym}.npz")
    with np.load(pn) as zn, np.load(pr) as zr:
        cut = (zr["ts"] >= a0) & (zr["ts"] < a1)
        res["rows_ref"] = int(cut.sum())
        res["same_keys"] = sorted(zn.files) == sorted(zr.files)
        for k in sorted(zr.files):
            x, y = zn[k], zr[k][cut]
            res["keys"][k] = {"dtype_new": x.dtype.str, "dtype_ref": y.dtype.str, "equal_bits":
                              bool(x.dtype == y.dtype and x.shape == y.shape and x.tobytes() == y.tobytes())}
    pf = os.path.join(work, "funding", f"{sym}.npz")
    with np.load(pf) as fn, np.load(os.path.join(ref_data, "funding", f"{sym}.npz")) as fr:
        cut = (fr["ts"] >= a0) & (fr["ts"] < a1)
        res["funding"] = {k: bool(fn[k].dtype == fr[k].dtype and fn[k].tobytes() == fr[k][cut].tobytes())
                          for k in ("ts", "rate")}
        res["funding_rows"] = [int(len(fn["ts"])), int(cut.sum())]
    res["reproduced"] = bool(res["same_keys"] and all(v["equal_bits"] for v in res["keys"].values())
                             and all(res["funding"].values()) and res["rows_new"] == res["rows_ref"])
    res["bytes_kept_in_work"] = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(work) for f in fs)
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return res


# ------------------------------------------------------------------ CLI
def _source(args):
    return DirSource(args.source_dir) if getattr(args, "source_dir", None) else HttpSource(args.ca_bundle)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m research.hunt.data_hunt", description=__doc__.split("\n\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("download", help="download + convert (resumable)")
    d.add_argument("--kind", choices=tuple(KINDS), default="5m")
    d.add_argument("--out", required=True)
    d.add_argument("--symbols", default=None, help="A,B,... (default: research/hunt/universe30.json)")
    d.add_argument("--universe-md", default=None)
    d.add_argument("--from", dest="first", default=None)
    d.add_argument("--to", dest="last", default=None)
    d.add_argument("--workers", type=int, default=8)
    d.add_argument("--source-dir", default=None, help="a local mirror with the data.binance.vision layout")
    d.add_argument("--ca-bundle", default=None)
    v = sp.add_parser("verify", help="compare a manifest (and its files) with the pinned reference")
    v.add_argument("--data", required=True)
    v.add_argument("--ref", required=True)
    v.add_argument("--manifest", default=None, help="default <data>/manifest.json")
    v.add_argument("--report", default=None)
    v.add_argument("--allow-meta-only", action="store_true")
    r = sp.add_parser("refman", help="array-content reference of an existing 5m data folder")
    r.add_argument("--data", required=True)
    r.add_argument("--out", required=True)
    p = sp.add_parser("prove", help="one coin-month rebuilt and compared bit for bit with an existing folder")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--month", default="2024-01")
    p.add_argument("--ref-data", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--source-dir", default=None)
    p.add_argument("--ca-bundle", default=None)
    s = sp.add_parser("symbols", help="print the symbol list the download would use")
    s.add_argument("--symbols", default=None)
    s.add_argument("--universe-md", default=None)
    c = sp.add_parser("coins", help="coins the picks traded (from test outputs), else the whole universe")
    c.add_argument("--tests", nargs="*", default=[])
    c.add_argument("--universe-md", default=None)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "download":
            syms, where = resolve_symbols(args.symbols, args.universe_md)
            K = KINDS[args.kind]
            first, last = args.first or K["range"][0], args.last or K["range"][1]
            print(f"symbols ({len(syms)}) from {where}: {' '.join(syms)}", flush=True)
            return download(_source(args), syms, args.kind, args.out, first, last, args.workers)
        if args.cmd == "verify":
            rep = verify(args.manifest or os.path.join(args.data, "manifest.json"), args.ref, args.data,
                         args.allow_meta_only)
            if args.report:
                _dump_json(args.report, rep)
            print(("VERIFY OK" if rep["ok"] else "VERIFY FAIL") + f": {rep['n_checked']}/{rep['n_symbols']} coins, "
                  f"{rep['n_differences']} differences")
            for x in rep["differences"][:20]:
                print("  " + x)
            return 0 if rep["ok"] else 1
        if args.cmd == "refman":
            ref = make_ref(args.data)
            _dump_json(args.out, ref)
            print(f"{args.out}: {len(ref['symbols'])} coins, sha256 {sha256_file(args.out)}")
            return 0
        if args.cmd == "prove":
            res = prove(_source(args), args.symbol, args.month, args.ref_data, args.work, args.keep)
            print(json.dumps({k: v for k, v in res.items() if k != "zips"}, indent=1))
            print("zips:", json.dumps(res["zips"], indent=1))
            return 0 if res["reproduced"] else 1
        if args.cmd == "symbols":
            syms, where = resolve_symbols(args.symbols, args.universe_md)
            print(" ".join(syms))
            print(f"({len(syms)} from {where})", file=sys.stderr)
            return 0
        if args.cmd == "coins":
            uni, _ = resolve_symbols(None, args.universe_md)
            coins, why = coins_from_tests(args.tests, uni)
            print(" ".join(coins))
            print(f"({len(coins)} coins: {why})", file=sys.stderr)
            return 0
    except DataError as e:
        print(f"data_hunt: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
