"""The backtest session's locked signal code, loaded only after a hash check.

The handover (v2, section 8) requires the bot to import this code rather
than rewrite it. ``lib()`` verifies every file listed in
``third_party/sweep/PREREG.sha256`` and refuses to load if one differs.
"""

from __future__ import annotations

import csv
import hashlib
import os
import sys
from typing import Optional

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "third_party", "sweep")
HARNESS = os.path.join(ROOT, "harness")
CLASSIFICATION = os.path.join(ROOT, "classify", "classification.csv")
CLASSIFICATION_SHA256 = "1c3f2cdc0851cfc4181d887325883a8d23757b49f5ce4b01db0fe0666a8a6ce8"
SOURCE_COMMIT = "a20ebe5"  # branch claude/handover-doc-analysis-l7q9u7
TF_ORDER = ("5m", "15m", "30m", "1h", "4h", "1d")

_lib = None


class LockedCodeChanged(RuntimeError):
    pass


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def verify() -> dict:
    """Check every hash in PREREG.sha256 and the classification file.
    Returns {"files": {path: sha}, "prereg_sha256_file": sha of PREREG.sha256}."""
    listing = os.path.join(ROOT, "PREREG.sha256")
    files = {}
    bad = []
    with open(listing) as fh:
        for line in fh:
            if not line.strip():
                continue
            want, rel = line.split(None, 1)
            rel = rel.strip()
            got = _sha256(os.path.join(ROOT, rel))
            files[rel] = got
            if got != want:
                bad.append(rel)
    if _sha256(CLASSIFICATION) != CLASSIFICATION_SHA256:
        bad.append("classify/classification.csv")
    if bad:
        raise LockedCodeChanged(f"locked signal code changed: {bad}. Restore it from the "
                                f"backtest branch (commit {SOURCE_COMMIT}); do not edit it.")
    return {"files": files, "prereg_sha256_file": _sha256(listing), "source_commit": SOURCE_COMMIT}


def lib():
    """The verified ``sweep_lib`` module."""
    global _lib
    if _lib is None:
        verify()
        if HARNESS not in sys.path:
            sys.path.insert(0, HARNESS)
        import sweep_lib  # noqa: E402  (locked code, loaded after the hash check)
        _lib = sweep_lib
    return _lib


def cells(cls: str = "2", path: Optional[str] = None) -> list[tuple[str, str]]:
    """(strategy, timeframe) cells of one class from the backtest classification:
    "1" trade, "2" record only, "3" excluded. Sorted by timeframe, then name."""
    with open(path or CLASSIFICATION, newline="") as fh:
        rows = [(r["strategy"], r["tf"]) for r in csv.DictReader(fh) if r["cls"] == cls]
    return sorted(rows, key=lambda x: (TF_ORDER.index(x[1]), x[0]))


def class_counts(path: Optional[str] = None) -> dict:
    with open(path or CLASSIFICATION, newline="") as fh:
        out: dict = {}
        for r in csv.DictReader(fh):
            out[r["cls"]] = out.get(r["cls"], 0) + 1
    return {c: out.get(c, 0) for c in ("1", "2", "3")}
