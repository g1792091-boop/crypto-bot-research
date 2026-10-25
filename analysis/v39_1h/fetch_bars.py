#!/usr/bin/env python3
"""Public Binance USD-M klines for the V3.9 1h study (data.binance.vision, no key, nothing private).

    python3 -I fetch_bars.py five   --cache DIR [--first 2020-11 --last-day 2026-10-24] [--procs 8]
    python3 -I fetch_bars.py minute --cache DIR --from 2026-10-01 --to 2026-10-24 [--procs 8]

five:   5-minute klines of the six coins from the first month to the last day (monthly zips, then daily zips of the last
        month), plus the monthly funding-rate files -> DIR/5m/<SYMBOL>.npz (ts, o, h, l, c, fund). Used for the 5-year
        check (the owners' rule: 1-minute bars only for the 20-day window; coarser bars for 5 years).
minute: 1-minute klines (last price) and mark-price klines of the six coins for whole UTC days -> DIR/1m/<SYMBOL>.npz
        (ts, o, h, l, c, mo, mh, ml, mc). Used around the 20-day window: hours after the export ends (how far price went
        after an exit) and before it starts.

Every zip is checked against its published .CHECKSUM, converted, and deleted (disk is tight); a 404 (a day not yet
published, a month before listing) is skipped and reported. Minutes / 5-minute bars without trades (volume 0) are
dropped, as the full-grid study does (research/fullgrid/data.py). Re-running reuses the npz files already built
(delete them to refresh).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import io
import os
import sys
sys.dont_write_bytecode = True  # never write .pyc files into the repository
import time
import urllib.error
import urllib.request
import zipfile

import site
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
BASE = "https://data.binance.vision/data/futures/um/"


def _get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "crypto-bot-research/v39_1h"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch(rel: str, tries: int = 5):
    """The verified zip bytes of ``rel``, or None on 404."""
    last = None
    for k in range(tries):
        try:
            data = _get(BASE + rel)
            want = _get(BASE + rel + ".CHECKSUM").decode().split()[0].strip().lower()
            if hashlib.sha256(data).hexdigest() != want:
                raise IOError(f"checksum mismatch {rel}")
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
        except Exception as exc:  # noqa: BLE001  network: retry with backoff
            last = exc
        time.sleep(min(20, 2 ** k))
    raise RuntimeError(f"download failed {rel}: {last}")


def read_klines(data: bytes) -> pd.DataFrame:
    """Kline CSV inside a zip (header or not; open time in ms or us) -> t (ms), open, high, low, close, volume."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        frames = []
        for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
            raw = z.read(n)
            x = pd.read_csv(io.BytesIO(raw), header=0 if raw[:1].isalpha() else None, usecols=range(6),
                            float_precision="round_trip")
            x.columns = ["t", "open", "high", "low", "close", "volume"]
            t = x["t"].to_numpy(np.int64)
            x["t"] = np.where(t >= 10 ** 14, t // 1000, t)
            frames.append(x)
    return pd.concat(frames, ignore_index=True)


def read_funding(data: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        frames = []
        for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
            raw = z.read(n)
            x = pd.read_csv(io.BytesIO(raw), header=0 if raw[:1].isalpha() else None, float_precision="round_trip")
            x = x.iloc[:, [0, x.shape[1] - 1]]
            x.columns = ["calc_time", "rate"]
            frames.append(x)
    return pd.concat(frames, ignore_index=True)


def months(a: str, b: str) -> list[str]:
    y, m = map(int, a.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def days(a: str, b: str) -> list[str]:
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [str(d0 + dt.timedelta(days=k)) for k in range((d1 - d0).days + 1)]


def _many(rels: list[str], procs: int, parse) -> tuple[list, list[str]]:
    out, missing = [], []
    with cf.ThreadPoolExecutor(procs) as ex:
        futs = {ex.submit(fetch, r): r for r in rels}
        for f in cf.as_completed(futs):
            data = f.result()
            if data is None:
                missing.append(futs[f])
            else:
                out.append(parse(data))
    return out, sorted(missing)


def five(cache: str, first: str, last_day: str, procs: int) -> None:
    os.makedirs(os.path.join(cache, "5m"), exist_ok=True)
    last_month = last_day[:7]
    full = [m for m in months(first, last_month) if m < last_month]
    for sym in SYMBOLS:
        path = os.path.join(cache, "5m", f"{sym}.npz")
        if os.path.exists(path):
            print(f"{sym}: kept {path}")
            continue
        t0 = time.time()
        rels = [f"monthly/klines/{sym}/5m/{sym}-5m-{m}.zip" for m in full]
        rels += [f"daily/klines/{sym}/5m/{sym}-5m-{d}.zip" for d in days(last_month + "-01", last_day)]
        parts, miss = _many(rels, procs, read_klines)
        k = pd.concat(parts, ignore_index=True).drop_duplicates("t", keep="last").sort_values("t")
        k = k[k["volume"] > 0]
        fr, fmiss = _many([f"monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip" for m in full], procs, read_funding)
        f = pd.concat(fr, ignore_index=True).drop_duplicates("calc_time").sort_values("calc_time")
        ts = k["t"].to_numpy(np.int64)
        fund = np.zeros(len(ts))
        ft = f["calc_time"].to_numpy(np.int64) // 60_000 * 60_000
        # a settlement at minute m is paid at the open of the 5-minute bar holding m (the bar opening at m: 00/08/16 UTC)
        j = np.searchsorted(ts, ft, side="left")
        ok = j < len(ts)
        np.add.at(fund, j[ok], f["rate"].to_numpy(float)[ok])
        np.savez(path, ts=ts, o=k["open"].to_numpy(float), h=k["high"].to_numpy(float), l=k["low"].to_numpy(float),
                 c=k["close"].to_numpy(float), fund=fund)
        print(f"{sym}: {len(ts):,} 5m bars {pd.Timestamp(ts[0], unit='ms')} .. {pd.Timestamp(ts[-1], unit='ms')}, "
              f"funding {int(ok.sum())}, missing files {len(miss) + len(fmiss)} {(miss + fmiss)[:3]} "
              f"({time.time() - t0:.0f}s)", flush=True)


def minute(cache: str, a: str, b: str, procs: int) -> None:
    os.makedirs(os.path.join(cache, "1m"), exist_ok=True)
    for sym in SYMBOLS:
        path = os.path.join(cache, "1m", f"{sym}.npz")
        if os.path.exists(path):
            print(f"{sym}: kept {path}")
            continue
        dd = days(a, b)
        parts, miss = _many([f"daily/klines/{sym}/1m/{sym}-1m-{d}.zip" for d in dd], procs, read_klines)
        k = pd.concat(parts, ignore_index=True).drop_duplicates("t", keep="last").sort_values("t")
        k = k[k["volume"] > 0].set_index("t")
        mp, mmiss = _many([f"daily/markPriceKlines/{sym}/1m/{sym}-1m-{d}.zip" for d in dd], procs, read_klines)
        m = pd.concat(mp, ignore_index=True).drop_duplicates("t", keep="last").set_index("t").reindex(k.index)
        cols = {c: k[n].to_numpy(float) for c, n in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))}
        for c, n, fb in (("mo", "open", "o"), ("mh", "high", "h"), ("ml", "low", "l"), ("mc", "close", "c")):
            v = m[n].to_numpy(float)
            cols[c] = np.where(np.isfinite(v), v, cols[fb])
        np.savez(path, ts=k.index.to_numpy(np.int64), **cols)
        print(f"{sym}: {len(k):,} 1m bars, missing days {miss[:3]} mark missing {mmiss[:3]}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=("five", "minute"))
    ap.add_argument("--cache", required=True)
    ap.add_argument("--first", default="2020-11")
    ap.add_argument("--last-day", default=None, help="last UTC day of the 5m data (default: yesterday)")
    ap.add_argument("--from", dest="a")
    ap.add_argument("--to", dest="b")
    ap.add_argument("--procs", type=int, default=8)
    a = ap.parse_args(argv)
    if a.what == "five":
        last = a.last_day or str(dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1))
        five(a.cache, a.first, last, a.procs)
    else:
        minute(a.cache, a.a, a.b, a.procs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
