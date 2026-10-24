"""Six coins' 1-minute prices for the league period, from Binance's public archive (data.binance.vision, no key).

    python3 market.py --from 2026-10-11 --to 2026-10-22 --cache DIR      # downloads (once) and prints daily moves

Each daily zip is checked against its published .CHECKSUM before it is read. Only the CSV inside is parsed (numbers), nothing
runs. Days the archive does not have yet (it lags about a day) are skipped and listed; the league's own last prices fill the
end point in that case (analyze.py).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import os
import sys
import urllib.error
import urllib.request
import zipfile

import numpy as np
import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/daily/klines/{s}/1m/{s}-1m-{d}.zip"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def _get(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def fetch_day(sym: str, day: str, cache: str) -> str | None:
    path = os.path.join(cache, f"{sym}-1m-{day}.zip")
    if os.path.exists(path):
        return path
    url = BASE.format(s=sym, d=day)
    try:
        blob = _get(url)
        chk = _get(url + ".CHECKSUM").decode().split()[0]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if hashlib.sha256(blob).hexdigest() != chk:
        raise SystemExit(f"체크섬이 맞지 않습니다: {url}")
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)
    return path


def read_zip(path: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        raw = z.read(names[0])
    df = pd.read_csv(io.BytesIO(raw), header=None, usecols=[0, 1, 2, 3, 4, 5], dtype=str)
    if not df.iloc[0, 0].isdigit():               # header row in newer files
        df = df.iloc[1:]
    df.columns = ["t", "o", "h", "l", "c", "v"]
    df = df.astype({"t": "int64", "o": float, "h": float, "l": float, "c": float, "v": float})
    return df


def load(start_day: str, end_day: str, cache: str) -> tuple[dict, list]:
    """{symbol: DataFrame(t, o, h, l, c, v)} for the days the archive has, and the list of missing (symbol, day)."""
    os.makedirs(cache, exist_ok=True)
    d0 = dt.date.fromisoformat(start_day)
    d1 = dt.date.fromisoformat(end_day)
    out, missing = {}, []
    for s in SYMBOLS:
        parts = []
        d = d0
        while d <= d1:
            p = fetch_day(s, d.isoformat(), cache)
            if p is None:
                missing.append((s, d.isoformat()))
            else:
                parts.append(read_zip(p))
            d += dt.timedelta(days=1)
        if parts:
            df = pd.concat(parts).drop_duplicates("t").sort_values("t").reset_index(drop=True)
            out[s] = df
    return out, missing


def price_at(df: pd.DataFrame, ms: int, col: str = "o") -> float | None:
    """Price at the minute that starts at or just before ``ms`` (open of that minute by default)."""
    t = df["t"].values
    i = np.searchsorted(t, ms, side="right") - 1
    if i < 0 or i >= len(t):
        return None
    if ms - t[i] > 3 * 60_000:
        return None
    return float(df[col].values[i])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True)
    ap.add_argument("--to", dest="d1", required=True)
    ap.add_argument("--cache", required=True)
    a = ap.parse_args()
    data, missing = load(a.d0, a.d1, a.cache)
    for s, df in data.items():
        print(s, len(df), df.t.min(), df.t.max(), df.c.iloc[0], df.c.iloc[-1])
    if missing:
        print("없는 날:", missing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
