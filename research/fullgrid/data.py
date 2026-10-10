"""Five-year data for the full-grid study (research/fullgrid, DESIGN_KO.md section 3): Binance USD-M public archive
(data.binance.vision), no API key, nothing private.

    python3 research/fullgrid/data.py download --dir DATA [--procs 8]   # zips -> DATA/raw (cached, checksummed)
    python3 research/fullgrid/data.py build --dir DATA                  # zips -> DATA/1m/<SYMBOL>.npz
    python3 research/fullgrid/data.py all --dir DATA

What and why
- 1m klines (last price), 1m mark-price klines and funding rates, monthly files 2020-01 .. 2026-09, for the six coins the
  rule bot trades (config.V3_SYMBOLS). The paper engine steps on 1m bars of last and mark price and pays funding at the
  funding minute's mark open, so the trade simulator (kernel.py) needs exactly these.
- Every zip is checked against its published .CHECKSUM. A 404 (a month before the coin was listed) is recorded in
  DATA/manifest.json and not asked again.
- Gap fill (as research/binance_data/build.py): a UTC day whose monthly kline zip holds fewer than 1,440 minutes, or a
  zero-volume minute, is read again from the archive's daily zip of that day; the daily file wins on a repeated open
  time. The same days are refilled for mark price.
- Minutes without trades (volume 0) are dropped: the archive writes an interval without trades (an exchange halt) as a
  flat bar at the last price, which is not market data (research/binance_data/build.py ``drop_no_trade``).
- Mark price: a minute missing from the mark file takes the last-price bar (counted in the build report).
- Funding: each settlement goes to the minute of its calc time (floored to the minute; the next minute when that one
  is missing): the engine pays funding at that minute's open (engine.step).
Output DATA/1m/<SYMBOL>.npz: ts (int64 ms, minute open), o h l c v (last price), mo mh ml mc (mark), fund (rate per
minute, 0 where none), and DATA/build.json (counts, gaps, sha256 of every file).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
FIRST_MONTH, LAST_MONTH = "2020-01", "2026-09"
BASE_URL = "https://data.binance.vision/data/"
MIN = 60_000
DAY = 86_400_000


def months(a: str = FIRST_MONTH, b: str = LAST_MONTH) -> list[str]:
    y, m = map(int, a.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def rel_monthly(kind: str, sym: str, month: str) -> str:
    if kind == "fundingRate":
        return f"futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{month}.zip"
    return f"futures/um/monthly/{kind}/{sym}/1m/{sym}-1m-{month}.zip"


def rel_daily(kind: str, sym: str, day: str) -> str:
    return f"futures/um/daily/{kind}/{sym}/1m/{sym}-1m-{day}.zip"


# ------------------------------------------------------------------ download
def _get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "crypto-bot-research/fullgrid"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch(raw: str, rel: str, tries: int = 5) -> str:
    """'ok' (file present and checksum-verified), 'missing' (404) or raises after ``tries`` attempts."""
    path = os.path.join(raw, rel)
    if os.path.exists(path):
        return "ok"
    last = None
    for k in range(tries):
        try:
            data = _get(BASE_URL + rel)
            want = _get(BASE_URL + rel + ".CHECKSUM").decode().split()[0].strip().lower()
            got = hashlib.sha256(data).hexdigest()
            if got != want:
                raise IOError(f"checksum mismatch {rel}: {got} != {want}")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".part"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
            return "ok"
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return "missing"
            last = exc
        except Exception as exc:  # noqa: BLE001  network: retry with backoff
            last = exc
        time.sleep(min(30, 2 ** k))
    raise RuntimeError(f"download failed {rel}: {last}")


def _manifest(d: str) -> dict:
    p = os.path.join(d, "manifest.json")
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return {"missing": []}


def _save_manifest(d: str, man: dict) -> None:
    p = os.path.join(d, "manifest.json")
    with open(p + ".tmp", "w") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
    os.replace(p + ".tmp", p)


def _fetch_all(d: str, rels: list[str], procs: int, man: dict, label: str) -> None:
    raw = os.path.join(d, "raw")
    miss = set(man["missing"])
    todo = [r for r in rels if r not in miss and not os.path.exists(os.path.join(raw, r))]
    t0, done = time.time(), 0
    with cf.ThreadPoolExecutor(procs) as ex:
        futs = {ex.submit(fetch, raw, r): r for r in todo}
        for f in cf.as_completed(futs):
            if f.result() == "missing":
                miss.add(futs[f])
            done += 1
            if done % 50 == 0 or done == len(todo):
                print(f"[{label}] {done}/{len(todo)} files, {time.time() - t0:.0f}s", flush=True)
    man["missing"] = sorted(miss)
    _save_manifest(d, man)


def download(d: str, procs: int = 8, symbols=SYMBOLS) -> None:
    os.makedirs(os.path.join(d, "raw"), exist_ok=True)
    man = _manifest(d)
    rels = [rel_monthly(k, s, m) for s in symbols for m in months() for k in ("klines", "markPriceKlines", "fundingRate")]
    _fetch_all(d, rels, procs, man, "monthly")
    keys = sorted({f"{s}|{day}" for s in symbols for day in gap_days(d, s, man)} | set(man.get("gap_days", [])))
    man["gap_days"] = keys
    rels = [rel_daily(k, *key.split("|")) for key in keys for k in ("klines", "markPriceKlines")]
    _fetch_all(d, rels, procs, man, "gap-fill days")


# ------------------------------------------------------------------ read
def read_kline_zip(path: str) -> pd.DataFrame:
    """Binance kline CSV in a zip (header line or not; open time in ms or us) -> t (ms) + OHLCV."""
    with zipfile.ZipFile(path) as z:
        frames = []
        for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
            data = z.read(n)
            header = 0 if data[:1].isalpha() else None
            x = pd.read_csv(io.BytesIO(data), header=header, usecols=range(6), float_precision="round_trip")
            x.columns = ["t", "open", "high", "low", "close", "volume"]
            t = x["t"].to_numpy(np.int64)
            x["t"] = np.where(t >= 10 ** 14, t // 1000, t)
            frames.append(x)
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
    return pd.concat(frames, ignore_index=True)


def _series(d: str, kind: str, sym: str, man: dict, daily: bool = True) -> pd.DataFrame:
    raw, miss = os.path.join(d, "raw"), set(man["missing"])
    parts = []
    for m in months():
        r = rel_monthly(kind, sym, m)
        if r not in miss and os.path.exists(os.path.join(raw, r)):
            parts.append(read_kline_zip(os.path.join(raw, r)))
    if daily:
        for key in man.get("gap_days", []):
            s, day = key.split("|")
            r = rel_daily(kind, sym, day)
            if s == sym and r not in miss and os.path.exists(os.path.join(raw, r)):
                parts.append(read_kline_zip(os.path.join(raw, r)))      # later = wins on a repeated open time
    if not parts:
        return pd.DataFrame(columns=["t", "open", "high", "low", "close", "volume"])
    x = pd.concat(parts, ignore_index=True)
    return x.drop_duplicates("t", keep="last").sort_values("t", kind="mergesort").reset_index(drop=True)


def gap_days(d: str, sym: str, man: dict) -> list[str]:
    """UTC days (after the first listed minute) whose monthly klines lack minutes or hold a zero-volume minute."""
    x = _series(d, "klines", sym, man, daily=False)
    if not len(x):
        return []
    day = x["t"].to_numpy(np.int64) // DAY
    cnt = pd.Series(1, index=day).groupby(level=0).sum()
    zero = pd.Series(x["volume"].to_numpy(float) == 0, index=day).groupby(level=0).sum()
    first, last = int(day[0]), int(day[-1])
    out = []
    for k in range(first + 1, last + 1):          # the listing day itself starts mid-day
        if int(cnt.get(k, 0)) < 1440 or int(zero.get(k, 0)) > 0:
            out.append(dt.date(1970, 1, 1) + dt.timedelta(days=k))
    return [str(v) for v in out]


# ------------------------------------------------------------------ build
def build_symbol(d: str, sym: str, man: dict) -> dict:
    k = _series(d, "klines", sym, man)
    n_read = len(k)
    k = k[k["volume"] > 0].reset_index(drop=True)
    m = _series(d, "markPriceKlines", sym, man).set_index("t")
    ts = k["t"].to_numpy(np.int64)
    mk = m.reindex(ts)
    no_mark = mk["open"].isna().to_numpy()
    cols = {}
    for a, b in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
        cols[a] = k[b].to_numpy(float)
    for a, b, fall in (("mo", "open", "o"), ("mh", "high", "h"), ("ml", "low", "l"), ("mc", "close", "c")):
        cols[a] = np.where(no_mark, cols[fall], mk[b].to_numpy(float))
    raw, miss = os.path.join(d, "raw"), set(man["missing"])
    fr = [read_funding_zip(os.path.join(raw, r)) for r in (rel_monthly("fundingRate", sym, mo) for mo in months())
          if r not in miss and os.path.exists(os.path.join(raw, r))]
    f = pd.concat(fr, ignore_index=True).drop_duplicates("calc_time", keep="last").sort_values("calc_time")
    ft = f["calc_time"].to_numpy(np.int64) // MIN * MIN  # calc times carry a few ms past the settlement minute
    fund = np.zeros(len(ts))
    j = np.searchsorted(ts, ft, side="left")              # that minute, or the first one after it when missing
    ok = j < len(ts)
    lost = int((~ok).sum())
    np.add.at(fund, j[ok], f["rate"].to_numpy(float)[ok])
    out = os.path.join(d, "1m", f"{sym}.npz")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    np.savez(out, ts=ts, fund=fund, **cols)
    gaps = np.diff(ts) // MIN - 1
    return {"symbol": sym, "minutes": int(len(ts)), "read": int(n_read), "zero_volume_dropped": int(n_read - len(ts)),
            "first": _iso(ts[0]), "last": _iso(ts[-1]), "mark_filled_from_last": int(no_mark.sum()),
            "missing_minutes": int(gaps[gaps > 0].sum()), "gaps_over_1h": int((gaps >= 60).sum()),
            "funding_events": int(ok.sum()), "funding_after_data_end": lost, "sha256": _sha(out)}


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build(d: str, symbols=SYMBOLS) -> dict:
    man = _manifest(d)
    rep = {"symbols": [build_symbol(d, s, man) for s in symbols], "months": [FIRST_MONTH, LAST_MONTH],
           "gap_days": len(man.get("gap_days", [])), "missing_files": len(man["missing"])}
    with open(os.path.join(d, "build.json"), "w") as fh:
        json.dump(rep, fh, indent=1)
    for r in rep["symbols"]:
        print(f"{r['symbol']}: {r['minutes']:,} minutes {r['first']} .. {r['last']}, mark filled {r['mark_filled_from_last']}, "
              f"missing minutes {r['missing_minutes']:,}, funding {r['funding_events']}")
    return rep


def load(d: str, sym: str) -> dict:
    with np.load(os.path.join(d, "1m", f"{sym}.npz")) as z:
        return {k: z[k] for k in z.files}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("download", "build", "all"))
    ap.add_argument("--dir", required=True)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    a = ap.parse_args(argv)
    syms = tuple(a.symbols.split(","))
    if a.step in ("download", "all"):
        download(a.dir, a.procs, syms)
    if a.step in ("build", "all"):
        build(a.dir, syms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
