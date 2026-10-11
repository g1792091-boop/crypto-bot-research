"""Inputs of the new-information batch (research/newinfo/PREREG_NEWINFO.md 2.2-2.3): 5-minute metrics and funding
settlements. Public Binance archive only (data.binance.vision), no key, nothing private.

    python3 research/newinfo/data.py download --dir NI_DATA                  # the 12 daily metrics files below
    python3 research/newinfo/data.py manifest --dir NI_DATA --archive FG1M   # sha256 of every input file
    python3 research/newinfo/data.py status   --dir NI_DATA

What and why
- Metrics (PREREG 2.3): ``data/orderflow/<coin>_metrics_5m.csv.gz`` (in the repo; its sha256 must equal
  data/orderflow/MANIFEST.json) plus the archive's daily metrics files of 2026-09-29 and 2026-09-30, which that folder
  lacks (not yet published when it was made). Those are downloaded to NI_DATA/raw/futures/um/daily/metrics/..., checked
  against the archive's .CHECKSUM (research/fullgrid/data.py ``fetch``) and their sha256 kept in NI_DATA/manifest.json.
  Columns used: ``count_long_short_ratio`` ("ls", all accounts) and ``sum_open_interest`` ("oi", in coins).
  A repeated stamp keeps the last row (the repo file first, then the daily files by day); a non-positive or
  non-numeric value is missing (NaN). Nothing is filled. Parsed into NI_DATA/metrics/<SYMBOL>.npz (t ms, ls, oi) the
  first time the study needs it; the cache records the sha256 of the files it was made from and is rebuilt when they
  differ.
- Funding (PREREG 2.2): the 1m archive's monthly fundingRate zips (FG1M/raw/..., downloaded and checksum-verified by
  research/fullgrid/data.py): calc time, rate, interval. A file without ``funding_interval_hours`` (or a row without a
  positive interval) stops the study. Settlement time = calc time floored to the minute (the minute the 1m archive
  pays it on); f8 = rate x 8 / interval hours.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import sys
import zipfile

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MIN = 60_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
COIN = {"BTCUSDT": "btc", "ETHUSDT": "eth", "SOLUSDT": "sol", "DOGEUSDT": "doge", "LTCUSDT": "ltc", "BCHUSDT": "bch"}
EXTRA_DAYS = ("2026-09-29", "2026-09-30")          # PREREG 2.3: published after data/orderflow was made
ORDERFLOW = os.path.join(ROOT, "data", "orderflow")
METRIC_COLS = ("count_long_short_ratio", "sum_open_interest")
FUNDING_COLS = ("calc_time", "funding_interval_hours", "last_funding_rate")
CACHE_VERSION = 1


def _load(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def fg_data():
    """research/fullgrid/data.py (download with checksum, month list), read-only."""
    return _load("fullgrid_data", os.path.join(ROOT, "research", "fullgrid", "data.py"))


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ files
def rel_daily_metrics(sym: str, day: str) -> str:
    return f"futures/um/daily/metrics/{sym}/{sym}-metrics-{day}.zip"


def orderflow_file(sym: str) -> str:
    return os.path.join(ORDERFLOW, f"{COIN[sym]}_metrics_5m.csv.gz")


def daily_file(d: str, sym: str, day: str) -> str:
    return os.path.join(d, "raw", rel_daily_metrics(sym, day))


def funding_files(archive: str, sym: str, months=None) -> list[str]:
    """The 1m archive's monthly fundingRate zips of ``sym`` that exist (months before listing are 404 there)."""
    F = fg_data()
    out = []
    for m in months or F.months():
        p = os.path.join(archive, "raw", F.rel_monthly("fundingRate", sym, m))
        if os.path.exists(p):
            out.append(p)
    return out


def orderflow_manifest() -> dict:
    """{file name: sha256} of data/orderflow/MANIFEST.json's metrics files."""
    with open(os.path.join(ORDERFLOW, "MANIFEST.json")) as fh:
        doc = json.load(fh)
    out = {}
    for s in SYMBOLS:
        for name, f in doc["symbols"][s]["metrics_5m"]["files"].items():
            out[name] = f["sha256"]
    return out


# ------------------------------------------------------------------ download
def download(d: str, procs: int = 2, symbols=SYMBOLS) -> dict:
    """The daily metrics files of EXTRA_DAYS (checksum-verified by fullgrid data.fetch). At most 2 at a time."""
    import concurrent.futures as cf
    F = fg_data()
    raw = os.path.join(d, "raw")
    rels = [rel_daily_metrics(s, day) for s in symbols for day in EXTRA_DAYS]
    status = {}
    with cf.ThreadPoolExecutor(max(1, min(2, procs))) as ex:
        futs = {ex.submit(F.fetch, raw, r): r for r in rels}
        for f in cf.as_completed(futs):
            try:
                status[futs[f]] = f.result()
            except Exception as exc:  # noqa: BLE001  reported, the study stops on a missing file later
                status[futs[f]] = f"error: {exc}"[:300]
    bad = {r: s for r, s in status.items() if s != "ok"}
    print(f"[download] {len(rels) - len(bad)} of {len(rels)} files ok" + (f"; problems: {bad}" if bad else ""),
          flush=True)
    return status


def manifest(d: str, archive: str | None) -> dict:
    """NI_DATA/manifest.json: sha256 of every input file and whether it matches its reference."""
    want = orderflow_manifest()
    doc = {"orderflow": {}, "daily": {}, "funding": {}, "problems": []}
    for s in SYMBOLS:
        p = orderflow_file(s)
        name = os.path.basename(p)
        got = sha256(p) if os.path.exists(p) else None
        doc["orderflow"][name] = {"sha256": got, "manifest": want.get(name), "ok": got is not None and got == want.get(name)}
        if not doc["orderflow"][name]["ok"]:
            doc["problems"].append(f"{name}: sha256 differs from data/orderflow/MANIFEST.json or file missing")
        for day in EXTRA_DAYS:
            q = daily_file(d, s, day)
            rel = rel_daily_metrics(s, day)
            doc["daily"][rel] = {"sha256": sha256(q) if os.path.exists(q) else None}
            if not os.path.exists(q):
                doc["problems"].append(f"{rel}: not downloaded")
        if archive:
            files = funding_files(archive, s)
            doc["funding"][s] = {os.path.basename(f): sha256(f) for f in files}
            for f in files:
                cols = funding_header(f)
                if "funding_interval_hours" not in cols:
                    doc["problems"].append(f"{os.path.basename(f)}: no funding_interval_hours column")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json.tmp"), "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    os.replace(os.path.join(d, "manifest.json.tmp"), os.path.join(d, "manifest.json"))
    return doc


def problems(d: str, archive: str | None) -> list[str]:
    """Input files that do not match their reference (an empty list: all fine)."""
    return manifest(d, archive)["problems"]


# ------------------------------------------------------------------ metrics
def _times_ms(x: pd.Series) -> np.ndarray:
    """Archive stamps: text in UTC (the metrics files) or epoch ms / us."""
    if pd.api.types.is_numeric_dtype(x):
        v = x.to_numpy(np.int64)
        return np.where(v >= 10 ** 14, v // 1000, v)
    return (pd.to_datetime(x, utc=True).astype("int64") // 1_000_000).to_numpy(np.int64)


def _read_metrics_csv(raw: bytes, gz: bool) -> pd.DataFrame:
    x = pd.read_csv(io.BytesIO(raw), compression="gzip" if gz else None, dtype=str)
    missing = [c for c in ("create_time",) + METRIC_COLS if c not in x.columns]
    if missing:
        raise ValueError(f"metrics file without columns {missing}")
    return x[["create_time", *METRIC_COLS]]


def read_metrics_sources(paths: list[str]) -> pd.DataFrame:
    """Rows of the given metrics files in order (csv.gz or the archive's daily zip)."""
    parts = []
    for p in paths:
        if p.endswith(".zip"):
            with zipfile.ZipFile(p) as z:
                for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
                    parts.append(_read_metrics_csv(z.read(n), False))
        else:
            with open(p, "rb") as fh:
                parts.append(_read_metrics_csv(fh.read(), p.endswith(".gz")))
    return pd.concat(parts, ignore_index=True)


def parse_metrics(x: pd.DataFrame) -> dict:
    """(t ms, ls, oi) sorted by stamp; a repeated stamp keeps the last row; a non-positive or non-numeric value is
    NaN. Also counts for the report (rows, repeated stamps, stamps off the 5-minute marks)."""
    t = _times_ms(x["create_time"])
    vals = {}
    for c, k in zip(METRIC_COLS, ("ls", "oi")):
        v = pd.to_numeric(x[c], errors="coerce").to_numpy(float)
        vals[k] = np.where(np.isfinite(v) & (v > 0), v, np.nan)
    order = np.argsort(t, kind="stable")
    t = t[order]
    vals = {k: v[order] for k, v in vals.items()}
    last = np.r_[t[1:] != t[:-1], True] if len(t) else np.zeros(0, bool)     # the last row of each stamp
    info = {"rows": int(len(t)), "repeated": int((~last).sum()), "off_mark": int((t[last] % (5 * MIN) != 0).sum())}
    return {"t": t[last], **{k: v[last] for k, v in vals.items()}, "info": info}


def metric_sources(d: str, sym: str) -> list[str]:
    return [orderflow_file(sym)] + [daily_file(d, sym, day) for day in EXTRA_DAYS]


def metrics(d: str, sym: str) -> dict:
    """The coin's metrics (t, ls, oi), from NI_DATA/metrics/<SYMBOL>.npz when it was made from the same files."""
    src = metric_sources(d, sym)
    for p in src:
        if not os.path.exists(p):
            raise SystemExit(f"metrics file missing: {p} (python3 research/newinfo/data.py download --dir {d})")
    hashes = [sha256(p) for p in src]
    path = os.path.join(d, "metrics", f"{sym}.npz")
    if os.path.exists(path):
        with np.load(path) as z:
            if str(z["sources"]) == json.dumps(hashes) and int(z["version"]) == CACHE_VERSION:
                return {"t": z["t"], "ls": z["ls"], "oi": z["oi"], "info": json.loads(str(z["info"]))}
    m = parse_metrics(read_metrics_sources(src))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez(path + ".tmp.npz", t=m["t"], ls=m["ls"], oi=m["oi"], sources=json.dumps(hashes),
             info=json.dumps(m["info"]), version=CACHE_VERSION)
    os.replace(path + ".tmp.npz", path)
    return m


# ------------------------------------------------------------------ funding
def funding_header(path: str) -> list[str]:
    with zipfile.ZipFile(path) as z:
        n = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        first = z.read(n).split(b"\n", 1)[0].decode().strip()
    return [c.strip() for c in first.split(",")]


def read_funding_zip(path: str) -> pd.DataFrame:
    """calc_time (ms), funding_interval_hours, last_funding_rate; a file without the interval column stops."""
    with zipfile.ZipFile(path) as z:
        frames = []
        for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
            x = pd.read_csv(io.BytesIO(z.read(n)), float_precision="round_trip")
            missing = [c for c in FUNDING_COLS if c not in x.columns]
            if missing:
                raise SystemExit(f"{os.path.basename(path)}: no column {missing} (PREREG_NEWINFO 2.2: the study stops)")
            frames.append(x[list(FUNDING_COLS)])
    return pd.concat(frames, ignore_index=True)


def parse_funding(x: pd.DataFrame) -> dict:
    """Settlements in time order: calc (ms), t (calc floored to the minute), rate, hours, f8 = rate x 8 / hours.
    A repeated calc time keeps the last row (as research/fullgrid/data.py)."""
    x = x.drop_duplicates("calc_time", keep="last").sort_values("calc_time", kind="mergesort")
    calc = _times_ms(x["calc_time"])
    rate = pd.to_numeric(x["last_funding_rate"], errors="coerce").to_numpy(float)
    hours = pd.to_numeric(x["funding_interval_hours"], errors="coerce").to_numpy(float)
    if len(hours) and not (np.isfinite(hours) & (hours > 0)).all():
        raise SystemExit("funding row without a positive funding_interval_hours (PREREG_NEWINFO 2.2: the study stops)")
    return {"calc": calc, "t": calc // MIN * MIN, "rate": rate, "hours": hours, "f8": rate * 8.0 / hours}


def funding(archive: str, sym: str, months=None) -> dict:
    files = funding_files(archive, sym, months)
    if not files:
        raise SystemExit(f"{sym}: no funding files under {archive}/raw")
    return parse_funding(pd.concat([read_funding_zip(f) for f in files], ignore_index=True))


# ------------------------------------------------------------------ cli
def status(d: str) -> None:
    for s in SYMBOLS:
        for day in EXTRA_DAYS:
            p = daily_file(d, s, day)
            print(f"{rel_daily_metrics(s, day)}: {'ok ' + sha256(p)[:12] if os.path.exists(p) else 'missing'}")
    print(f"manifest.json: {'yes' if os.path.exists(os.path.join(d, 'manifest.json')) else 'not yet'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("download", "manifest", "status"))
    ap.add_argument("--dir", required=True)
    ap.add_argument("--archive", help="the full grid's 1m archive (FG1M: raw/ with the fundingRate zips)")
    ap.add_argument("--procs", type=int, default=2)
    a = ap.parse_args(argv)
    if a.step == "download":
        st = download(a.dir, a.procs)
        manifest(a.dir, a.archive)
        return 0 if all(v == "ok" for v in st.values()) else 1
    if a.step == "manifest":
        doc = manifest(a.dir, a.archive)
        print("problems: " + ("; ".join(doc["problems"]) if doc["problems"] else "none"))
        return 1 if doc["problems"] else 0
    status(a.dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
