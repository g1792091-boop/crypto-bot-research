"""Loads the study's own code (lib_zoneflip.py, the exact file that produced the 5-year result) for the parity tests.

The reference copy lives in tests/data/zoneflip_original/ (the same bytes as docs/zoneflip-reel/lib_zoneflip.py.txt on
the owners' branch); its sha256 is checked before anything runs. The original imports the study's helpers from the
repository's research/reel5m (frozen): they are loaded from THIS checkout, not from a hard-coded path.
Nothing here is imported by the bot."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGINAL = os.path.join(ROOT, "tests", "data", "zoneflip_original", "lib_zoneflip.py.txt")
ORIGINAL_SHA256 = "b4a5f6d00ff1d9cb71cf8cd209eb39731603daaaa50827dcc5fdd95a424677f3"
PREREG_SHA256 = "202d638e4a3d72aacc1d8ac601f9372f0ed4fdb5a923c5e8ecabadafaa642c8a"
REEL_LIB = os.path.join(ROOT, "research", "reel5m", "lib_reel5m.py")

_CACHE: dict = {}


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_original():
    """The original module (cached). Raises AssertionError when the reference copy is not the committed file."""
    if "mod" in _CACHE:
        return _CACHE["mod"]
    assert sha256_of(ORIGINAL) == ORIGINAL_SHA256, "tests/data/zoneflip_original is not the study's lib_zoneflip.py"
    if "lib_reel5m" not in sys.modules:
        spec = importlib.util.spec_from_file_location("lib_reel5m", REEL_LIB)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["lib_reel5m"] = mod
        spec.loader.exec_module(mod)
    loader = importlib.machinery.SourceFileLoader("zoneflip_original", ORIGINAL)
    spec = importlib.util.spec_from_loader("zoneflip_original", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["zoneflip_original"] = mod
    loader.exec_module(mod)
    _CACHE["mod"] = mod
    return mod


def available() -> bool:
    """True when the original and the study's environment (locked engine, library) can be loaded here."""
    try:
        load_original().env()
        return True
    except Exception:  # noqa: BLE001  (a test then skips: the parity cannot be shown on this machine)
        return False
