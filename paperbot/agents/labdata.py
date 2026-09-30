"""Build the lab's five-year signal caches on the server, the same way the research built them.

    python -m paperbot.agents.labdata build --out DIR [--procs 2] [--only main|pre2021]
    python -m paperbot.agents.labdata check --out DIR

``build`` runs the research builders themselves, so the server cache is the research cache:
  * periods 1-2 (2021-08 .. 2026-09): ``research/binance_data/build.py`` download -> assemble -> signals.
    Binance USDT-M futures klines from the public archive (data.binance.vision, each zip checked against its
    .CHECKSUM), days the monthly 5m files lack repaired from the daily files, bars without trades dropped,
    30m resampled from 5m, edges trimmed, signals from the locked code (hash-checked) with
    DOGE = sigservice.doge_join(DOGE_L, DOGE_S). Written to ``DIR/sig_<tf>_<COIN>.npz``; downloads and
    bars under ``DIR/_binance`` (kept, so a rebuild does not download again), reports under ``DIR/_reports``.
  * period 3 (2020-01 .. 2021-07): ``research/entry_study/final_signals.py build`` from the Binance futures
    bars in the repository (data/pre2021), no download. Written to ``DIR/pre2021``.
``check`` (also run at the end of ``build``) compares every file's content digest with
``labdata_reference.json``: the digests of the caches the research results were computed on. The result
goes to ``DIR/labdata_manifest.json``; the exit code is 1 when a file is missing or differs.

Public market data only: no API key, no account, no orders. Nothing is written into the repository.
Only run by hand on the server; the tests never touch the network.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from .. import sweepsig

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD_PY = os.path.join(ROOT, "research", "binance_data", "build.py")
ENTRY_STUDY = os.path.join(ROOT, "research", "entry_study")
PRE2021_BARS = os.path.join(ROOT, "data", "pre2021")
REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labdata_reference.json")
TFS = ("5m", "15m", "30m", "1h", "4h")
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
MANIFEST = "labdata_manifest.json"
SOURCES = ("main", "pre2021")


def paths(out: str) -> dict:
    out = os.path.abspath(out)
    return {"main": out, "pre2021": os.path.join(out, "pre2021"), "work": os.path.join(out, "_binance"),
            "reports": os.path.join(out, "_reports")}


def load_builder(out: str, procs: Optional[int] = None):
    """research/binance_data/build.py as a module, pointed at ``out`` (its paths are read at import)."""
    p = paths(out)
    os.environ["BINANCE_DIR"] = p["work"]
    os.environ["BINANCE_SIGNALS"] = p["main"]
    os.environ["BINANCE_REPORTS"] = p["reports"]
    name = "paperbot_lab_binance_build"
    spec = importlib.util.spec_from_file_location(name, BUILD_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod            # Pool workers (fork) find the module by this name
    spec.loader.exec_module(mod)
    if procs:
        mod.PROCS = procs
    return mod


def load_final_signals(out: str):
    if ENTRY_STUDY not in sys.path:
        sys.path.insert(0, ENTRY_STUDY)
    import final_signals as FS
    FS.OUT = paths(out)["reports"]     # its manifest copy goes to the reports folder, not the repository
    return FS


def reference(path: str = REFERENCE) -> dict:
    with open(path) as fh:
        return json.load(fh)


def content_digest(arrays: dict) -> str:
    """Same as research/entry_study/final_signals.content_digest (kept here so ``check`` needs no research import)."""
    import hashlib
    h = hashlib.sha256()
    for k in sorted(arrays):
        a = np.ascontiguousarray(arrays[k])
        h.update(k.encode()); h.update(str(a.dtype).encode()); h.update(a.tobytes())
    return h.hexdigest()


def check(out: str, ref: Optional[dict] = None, sources=SOURCES) -> dict:
    """Every lab file against the research digests; writes DIR/labdata_manifest.json."""
    ref = ref or reference()
    p = paths(out)
    res = {"checked_utc": datetime.now(timezone.utc).isoformat(), "reference": os.path.relpath(REFERENCE, ROOT),
           "files": {}, "missing": [], "differ": []}
    for src in sources:
        for tf in TFS:
            for coin in COINS:
                key = f"{tf}_{coin}"
                want = ref[src][key]
                f = os.path.join(p[src], f"sig_{key}.npz")
                row = {"source": src, "tf": tf, "coin": coin, "reference": want["digest"], "reference_bars": want["bars"]}
                if not os.path.exists(f):
                    row["status"] = "missing"
                    res["missing"].append(f"{src} {key}")
                else:
                    with np.load(f) as z:
                        arrs = {k: z[k] for k in z.files}
                    row.update(digest=content_digest(arrs), bars=int(len(arrs["ts"])))
                    row["status"] = "identical" if row["digest"] == want["digest"] else "differs"
                    if row["status"] == "differs":
                        res["differ"].append(f"{src} {key}")
                res["files"][f"{src}/{key}"] = row
    res["all_identical"] = not res["missing"] and not res["differ"]
    os.makedirs(p["main"], exist_ok=True)
    with open(os.path.join(p["main"], MANIFEST), "w") as fh:
        json.dump(res, fh, indent=1)
    return res


def build(out: str, procs: int = 2, only: Optional[str] = None, refresh_404: bool = False, force: bool = False) -> dict:
    sweepsig.verify()                  # locked signal code, hash check before any work
    p = paths(out)
    for d in (p["main"], p["reports"]):
        os.makedirs(d, exist_ok=True)
    steps = {}
    t0 = time.time()
    if only in (None, "main"):
        B = load_builder(out, procs)
        dl = B.download(refresh_404=refresh_404)
        if dl.get("failed"):
            raise SystemExit(f"download failed for {len(dl['failed'])} files (network?); run the same command again")
        steps["download_s"] = round(time.time() - t0, 1)
        B.assemble(force=force)
        steps["assemble_s"] = round(time.time() - t0, 1)
        B.signals(force=force)
        steps["signals_s"] = round(time.time() - t0, 1)
    if only in (None, "pre2021"):
        FS = load_final_signals(out)
        FS.build(p["pre2021"], procs, PRE2021_BARS)
        steps["pre2021_s"] = round(time.time() - t0, 1)
    res = check(out, sources=(only,) if only else SOURCES)
    res["steps"] = steps
    with open(os.path.join(p["main"], MANIFEST), "w") as fh:
        json.dump(res, fh, indent=1)
    return res


def _report(res: dict) -> int:
    n = len(res["files"])
    same = sum(1 for r in res["files"].values() if r["status"] == "identical")
    print(f"{same}/{n} files identical to the research caches")
    for k in res["missing"]:
        print(f"  missing: {k}")
    for k in res["differ"]:
        print(f"  differs: {k}")
    if not res["all_identical"]:
        print("The lab can still run, but its numbers will not match the research exactly. "
              "Send labdata_manifest.json and _reports/ to the developer.")
    return 0 if res["all_identical"] else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.agents.labdata",
                                 description="Build/check the lab signal caches (same build as the research).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", required=True, help="cache directory (the lab's LAB_DATA_DIR)")
    b.add_argument("--procs", type=int, default=2)
    b.add_argument("--only", choices=SOURCES, default=None)
    b.add_argument("--refresh-404", action="store_true", help="ask the archive again for files it did not have")
    b.add_argument("--force", action="store_true", help="rebuild bars and signals that already exist")
    c = sub.add_parser("check")
    c.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return _report(check(a.out))
    return _report(build(a.out, a.procs, a.only, a.refresh_404, a.force))


if __name__ == "__main__":
    sys.exit(main())
