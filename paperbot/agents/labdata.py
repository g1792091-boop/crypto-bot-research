"""Build the lab's five-year signal caches on the server from Binance's public kline archive.

    python -m paperbot.agents.labdata build --out DIR            # periods 1-2 (2021-05 .. 2026-09)
    python -m paperbot.agents.labdata build --out DIR --pre2021  # period 3 into DIR/pre2021

Writes ``DIR/sig_<tf>_<COIN>.npz`` in the format of research/paper_rules/rules_bt.py ``signals``
(mirrors ``rules_bt._signals_job``): ts (int64 ns, bar open, UTC), o, h, l, c, atr (ATR14 of the
bar), s__<STRATEGY> (int8 +1/-1/0 on the signal bar; entry is the next bar's open). Signals come
from the locked backtest code (``paperbot.sweepsig.lib().compute_signals``, hash-checked), run on
the whole series (the code is causal); DOGE = DOGE_L - DOGE_S as in rules_bt.

Bars: USD-M futures klines of the timeframe itself from
https://data.binance.vision/data/futures/um/monthly/klines/<SYMBOL>/<tf>/<SYMBOL>-<tf>-<YYYY-MM>.zip
(each zip checked against its published .CHECKSUM). A month not published yet (the current one)
is filled from the daily files. Downloads are kept in ``--cache`` (default DIR/_klines) so a
rebuild does not download again. A manifest (labdata_manifest.json) lists the months used.

This is public market data only: no API key, no account, no orders. The research caches came
from the backtest's own data files, so a server-built cache can differ slightly (data source and
series start); the lab's numbers are then close to, not identical with, profiles.json.
Only run by hand on the server; the tests never touch the network.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from multiprocessing import Pool
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .. import sweepsig

BASE_URL = "https://data.binance.vision/data/futures/um"
TFS = ("5m", "15m", "30m", "1h", "4h")
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
MAIN = ("2021-05-01", "2026-09-30")      # warm-up before period 1 (2021-08-01); rules_bt keeps ts < 2026-09-30
PRE2021 = ("2019-09-01", "2021-09-01")   # period 3 = 2020-01-01 .. 2021-08-01; bars kept to 2021-08-31
MANIFEST = "labdata_manifest.json"
USER_AGENT = "paperbot-labdata/1 (public market data)"

Getter = Callable[[str], Optional[bytes]]


def symbol_of(coin: str) -> str:
    """Cache coin name -> Binance USD-M symbol (BTCUSD -> BTCUSDT)."""
    return coin if coin.endswith("USDT") else coin + "T"


def monthly_url(symbol: str, tf: str, month: str) -> str:
    return f"{BASE_URL}/monthly/klines/{symbol}/{tf}/{symbol}-{tf}-{month}.zip"


def daily_url(symbol: str, tf: str, day: str) -> str:
    return f"{BASE_URL}/daily/klines/{symbol}/{tf}/{symbol}-{tf}-{day}.zip"


def months_between(start: str, end: str) -> list[str]:
    """'YYYY-MM' of every month that has a day in [start, end)."""
    s, e = pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=1)
    out, y, m = [], s.year, s.month
    while (y, m) <= (e.year, e.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ---------------------------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------------------------
def parse_kline_csv(text: str) -> pd.DataFrame:
    """Binance kline CSV (with or without the header line) -> ts (UTC), open, high, low, close,
    volume. Open times in microseconds (newer archive files) are converted to milliseconds."""
    raw = pd.read_csv(io.StringIO(text), header=None, usecols=range(6), dtype=str)
    t = pd.to_numeric(raw[0], errors="coerce")
    raw, t = raw[t.notna()], t[t.notna()].astype("int64").to_numpy()
    t = np.where(t >= 10 ** 14, t // 1000, t)
    out = pd.DataFrame({"ts": pd.to_datetime(t, unit="ms", utc=True)})
    for k, col in zip(("open", "high", "low", "close", "volume"), range(1, 6)):
        out[k] = pd.to_numeric(raw[col]).to_numpy(float)
    return out.reset_index(drop=True)


def parse_kline_zip(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("kline zip without a CSV file")
        return pd.concat([parse_kline_csv(z.read(n).decode("utf-8")) for n in names], ignore_index=True)


def checksum_ok(blob: bytes, checksum_text: Optional[str]) -> bool:
    """``<sha256>  <file name>`` as published next to every archive zip."""
    if not checksum_text:
        return True
    want = checksum_text.strip().split()[0].lower()
    return hashlib.sha256(blob).hexdigest() == want


# ---------------------------------------------------------------------------------------------
# download (public archive, cached)
# ---------------------------------------------------------------------------------------------
def http_get(url: str, timeout: float = 60.0, retries: int = 3) -> Optional[bytes]:
    """GET a public archive file; None when it does not exist (404)."""
    last: Optional[Exception] = None
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        time.sleep(2.0 * (k + 1))
    raise RuntimeError(f"download failed: {url}: {last}")


def fetch(url: str, cache_dir: Optional[str], getter: Getter = http_get, verify: bool = True) -> Optional[bytes]:
    """The zip at ``url`` from the cache or the archive (checked against its .CHECKSUM)."""
    path = None
    if cache_dir:
        path = os.path.join(cache_dir, url.split("/klines/", 1)[-1])
        if os.path.exists(path):
            with open(path, "rb") as fh:
                return fh.read()
    blob = getter(url)
    if blob is None:
        return None
    if verify:
        cs = getter(url + ".CHECKSUM")
        if not checksum_ok(blob, cs.decode("utf-8", "replace") if cs else None):
            raise RuntimeError(f"checksum mismatch: {url}")
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, path)
    return blob


def load_klines(symbol: str, tf: str, start: str, end: str, cache_dir: Optional[str] = None,
                getter: Getter = http_get, today: Optional[date] = None, verify: bool = True) -> tuple[pd.DataFrame, dict]:
    """Bars with start <= ts < end, oldest first, one row per open time. Returns (bars, notes)."""
    today = today or datetime.now(timezone.utc).date()
    frames, notes = [], {"months": [], "months_missing": [], "days": [], "days_missing": []}
    for month in months_between(start, end):
        blob = fetch(monthly_url(symbol, tf, month), cache_dir, getter, verify)
        if blob is not None:
            frames.append(parse_kline_zip(blob))
            notes["months"].append(month)
            continue
        m0 = pd.Timestamp(month + "-01")
        if (m0 + pd.offsets.MonthEnd(0)).date() < today - timedelta(days=45):
            notes["months_missing"].append(month)          # before listing, or not archived
            continue
        # the newest month is not published monthly yet: use the daily files
        day = m0
        stop = min(m0 + pd.offsets.MonthBegin(1), pd.Timestamp(end), pd.Timestamp(today))
        while day < stop:
            d = day.strftime("%Y-%m-%d")
            b = fetch(daily_url(symbol, tf, d), cache_dir, getter, verify)
            if b is None:
                notes["days_missing"].append(d)
            else:
                frames.append(parse_kline_zip(b))
                notes["days"].append(d)
            day += pd.Timedelta(days=1)
    if not frames:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"]), notes
    df = pd.concat(frames, ignore_index=True).sort_values("ts", kind="stable")
    df = df.drop_duplicates("ts", keep="last")
    df = df[(df["ts"] >= pd.Timestamp(start, tz="UTC")) & (df["ts"] < pd.Timestamp(end, tz="UTC"))]
    df = df.reset_index(drop=True)
    df.attrs["tf"] = tf
    return df, notes


# ---------------------------------------------------------------------------------------------
# signals (mirrors research/paper_rules/rules_bt._signals_job)
# ---------------------------------------------------------------------------------------------
def signal_arrays(df: pd.DataFrame, tf: str, coin: str) -> dict:
    from .labtests import profiles_module
    RB = profiles_module().RB
    L = sweepsig.lib()
    df.attrs["tf"] = tf
    raw = L.compute_signals({coin: df}, tf, list(L.NAMES), strict=True)
    sig = {n: raw[n][coin] for n in L.NAMES if n not in ("DOGE_L", "DOGE_S")}
    sig["DOGE"] = (raw["DOGE_L"][coin].astype(np.int8) - raw["DOGE_S"][coin].astype(np.int8)).astype(np.int8)
    atr = L.fg.atr(df, 14).to_numpy(float)
    return dict(ts=RB._ns(df["ts"]), o=df["open"].to_numpy(float), h=df["high"].to_numpy(float),
                l=df["low"].to_numpy(float), c=df["close"].to_numpy(float), atr=atr,
                **{f"s__{k}": v for k, v in sig.items()})


def content_digest(arrays: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(arrays):
        a = np.ascontiguousarray(arrays[k])
        h.update(k.encode()); h.update(str(a.dtype).encode()); h.update(a.tobytes())
    return h.hexdigest()


def write_npz(path: str, arrays: dict) -> None:
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        np.savez_compressed(fh, **arrays)
    os.replace(tmp, path)


def build_one(tf: str, coin: str, out_dir: str, start: str, end: str, cache_dir: Optional[str],
              getter: Getter = http_get, verify: bool = True) -> dict:
    t0 = time.time()
    sym = symbol_of(coin)
    df, notes = load_klines(sym, tf, start, end, cache_dir, getter, verify=verify)
    row = dict(tf=tf, coin=coin, symbol=sym, bars=len(df), **notes)
    if len(df) == 0:
        row["error"] = "no bars"
        return row
    arrs = signal_arrays(df, tf, coin)
    write_npz(os.path.join(out_dir, f"sig_{tf}_{coin}.npz"), arrs)
    row.update(first=str(df["ts"].iloc[0]), last=str(df["ts"].iloc[-1]), digest=content_digest(arrs),
               seconds=round(time.time() - t0, 1))
    return row


def _job(args):
    return build_one(*args)


def build(out_dir: str, tfs=TFS, coins=COINS, start: str = MAIN[0], end: str = MAIN[1],
          cache_dir: Optional[str] = None, procs: int = 4, force: bool = False) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    lock = sweepsig.verify()["prereg_sha256_file"]         # hash check before any work
    cache_dir = cache_dir or os.path.join(out_dir, "_klines")
    jobs = [(tf, c, out_dir, start, end, cache_dir) for tf in tfs for c in coins
            if force or not os.path.exists(os.path.join(out_dir, f"sig_{tf}_{c}.npz"))]
    t0 = time.time()
    rows = []
    with Pool(max(1, procs)) as p:
        for r in p.imap_unordered(_job, jobs):
            rows.append(r)
            print(f"[{time.time() - t0:6.0f}s] {r['tf']:>3} {r['coin']}: {r['bars']} bars "
                  f"{r.get('first', '')} .. {r.get('last', '')} {r.get('error', '')}", flush=True)
    man_path = os.path.join(out_dir, MANIFEST)
    old = {}
    if os.path.exists(man_path):
        with open(man_path) as fh:
            old = {(f["tf"], f["coin"]): f for f in json.load(fh).get("files", [])}
    for r in rows:
        old[(r["tf"], r["coin"])] = r
    man = dict(built_utc=datetime.now(timezone.utc).isoformat(), source=BASE_URL + "/monthly/klines/",
               start=start, end=end, locked_code=lock, wall_s=round(time.time() - t0, 1),
               files=sorted(old.values(), key=lambda f: (f["tf"], f["coin"])))
    with open(man_path, "w") as fh:
        json.dump(man, fh, indent=1)
    return man


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.agents.labdata",
                                 description="Build the lab signal caches from Binance public klines.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", required=True, help="cache directory (the lab's LAB_DATA_DIR)")
    b.add_argument("--pre2021", action="store_true", help="build the period-3 cache into OUT/pre2021")
    b.add_argument("--start", default=None)
    b.add_argument("--end", default=None)
    b.add_argument("--tfs", default=",".join(TFS))
    b.add_argument("--coins", default=",".join(COINS))
    b.add_argument("--cache", default=None, help="download cache (default OUT/_klines)")
    b.add_argument("--procs", type=int, default=4)
    b.add_argument("--force", action="store_true", help="rebuild files that already exist")
    a = ap.parse_args(argv)
    start, end = PRE2021 if a.pre2021 else MAIN
    out = os.path.join(a.out, "pre2021") if a.pre2021 else a.out
    cache = a.cache or os.path.join(a.out, "_klines")
    tfs = [t for t in a.tfs.split(",") if t]
    bad = [t for t in tfs if t not in TFS]
    if bad:
        ap.error(f"unknown timeframe(s): {bad}")
    man = build(out, tfs, [c for c in a.coins.split(",") if c], a.start or start, a.end or end, cache,
                a.procs, a.force)
    errors = [f for f in man["files"] if f.get("error")]
    print(f"wrote {len(man['files'])} files into {out} ({len(errors)} with errors)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
