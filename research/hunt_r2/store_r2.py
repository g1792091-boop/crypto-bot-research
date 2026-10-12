"""Hunt round 2 event store (PREREG_HUNT_R2.md 11, 3.7): per (name, timeframe, coin) work unit, the select-period
events of every lattice combo, before the gate, as int32 bar index (into the coin's signal bars of that timeframe,
``hunt.series(sym, tf).bars``), int8 side (+1 / -1) and an int8 G1 flag (the bar's 장세 label is 추세장). A bar with a
long and a short event is no event (W 3.2; counted per combo as ``n_both``). Every null replicate reads this store;
signals are never recomputed per replicate.

Layout: ``<root>/<part>/<name>/<tf>/<sym>/`` with ``j.npy``, ``side.npy``, ``g1.npy``, ``off.npy`` (combo i's events
are rows off[i]:off[i+1]), ``n_both.npy`` and ``meta.json`` (combo shas, the combos whose signal code raised with the
exception text (3.7), the series fingerprint, the period). A unit directory is written under a temporary name and
renamed, so a unit is either complete or absent (resume skips complete units whose fingerprint matches).

``part`` = "coarse" (every coarse combo on every timeframe of the name) or "box" (box cells of taken names, 11).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt_r2 import entries_r2 as E  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402

STORE_VERSION = 1
ARRAYS = ("j", "side", "g1", "off", "n_both")


def unit_dir(root: str, part: str, name: str, tf: str, sym: str) -> str:
    return os.path.join(root, part, name, tf, sym)


def series_fingerprint(ser) -> dict:
    cm = ser.bars.close_ms
    h = hashlib.sha256(np.ascontiguousarray(cm).tobytes())
    h.update(np.ascontiguousarray(ser.bars.c).tobytes())
    return {"sym": ser.sym, "tf": ser.tf, "n_bars": int(len(cm)), "sha": h.hexdigest()[:16]}


def compute_unit(name: str, tf: str, sym: str, combos: list, start_ms: int, end_ms: int) -> dict:
    """The unit's arrays for ``combos`` on the installed coins (``hunt.install`` / ``load_study_data``)."""
    ser = H.series(sym, tf)
    fam = L.family_of(name)
    btc = None
    if L.KIND_OF[fam] == "ds" and sym != "BTCUSDT":
        btc = H.series("BTCUSDT", tf).bars
    se = E.SeriesEvents(name, ser.bars, sym, btc)
    cm = ser.bars.close_ms
    inper = (cm >= start_ms) & (cm < end_ms)
    trend = np.asarray(ser.code == H.TREND, bool)
    J, S, G, off, nboth, raised = [], [], [], [0], [], {}
    for i, combo in enumerate(combos):
        try:
            el, es = se.events(combo)
        except Exception as exc:  # noqa: BLE001  3.7: removed from this (name, timeframe), listed with its text
            raised[str(i)] = f"{type(exc).__name__}: {exc}"[:300]
            off.append(off[-1])
            nboth.append(0)
            continue
        both = el & es & inper
        jl = np.flatnonzero(el & inper & ~both)
        js = np.flatnonzero(es & inper & ~both)
        j = np.concatenate([jl, js]).astype(np.int32)
        J.append(j)
        S.append(np.concatenate([np.ones(len(jl), np.int8), -np.ones(len(js), np.int8)]))
        G.append(trend[j].astype(np.int8))
        off.append(off[-1] + len(j))
        nboth.append(int(both.sum()))
    cat = lambda xs, dt_: np.concatenate(xs).astype(dt_) if xs else np.zeros(0, dt_)  # noqa: E731
    meta = {"version": STORE_VERSION, "name": name, "tf": tf, "sym": sym, "period": [int(start_ms), int(end_ms)],
            "combo_sha": [L.combo_sha(c) for c in combos], "raised": raised, "series": series_fingerprint(ser)}
    return {"j": cat(J, np.int32), "side": cat(S, np.int8), "g1": cat(G, np.int8), "off": np.asarray(off, np.int64),
            "n_both": np.asarray(nboth, np.int32), "meta": meta}


def write_unit(path: str, doc: dict) -> str:
    tmp = f"{path}.tmp{os.getpid()}"
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    for k in ARRAYS:
        np.save(os.path.join(tmp, f"{k}.npy"), doc[k])
    with open(os.path.join(tmp, "meta.json"), "w") as fh:
        json.dump(doc["meta"], fh)
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.replace(tmp, path)
    return path


def unit_complete(path: str, combos: list, start_ms: int, end_ms: int, ser=None) -> bool:
    mp = os.path.join(path, "meta.json")
    if not os.path.exists(mp):
        return False
    try:
        with open(mp) as fh:
            m = json.load(fh)
    except (OSError, ValueError):
        return False
    ok = (m.get("version") == STORE_VERSION and m.get("period") == [int(start_ms), int(end_ms)]
          and m.get("combo_sha") == [L.combo_sha(c) for c in combos])
    if ok and ser is not None:
        ok = m.get("series") == series_fingerprint(ser)
    return bool(ok)


class StoreUnit:
    """One unit read back (arrays memory-mapped)."""

    def __init__(self, path: str, mmap: bool = True):
        self.path = path
        with open(os.path.join(path, "meta.json")) as fh:
            self.meta = json.load(fh)
        mode = "r" if mmap else None
        for k in ARRAYS:
            setattr(self, k, np.load(os.path.join(path, f"{k}.npy"), mmap_mode=mode))
        self.index = {s: i for i, s in enumerate(self.meta["combo_sha"])}
        self.raised = {int(k): v for k, v in self.meta["raised"].items()}

    def events(self, ci: int) -> tuple:
        a, b = int(self.off[ci]), int(self.off[ci + 1])
        return np.asarray(self.j[a:b]), np.asarray(self.side[a:b]), np.asarray(self.g1[a:b])

    @classmethod
    def from_doc(cls, doc: dict):
        u = cls.__new__(cls)
        u.path = None
        u.meta = doc["meta"]
        for k in ARRAYS:
            setattr(u, k, doc[k])
        u.index = {s: i for i, s in enumerate(u.meta["combo_sha"])}
        u.raised = {int(k): v for k, v in u.meta["raised"].items()}
        return u


def build(root: str, part: str, name: str, tf: str, sym: str, combos: list, start_ms: int, end_ms: int) -> str:
    """Compute and write one unit unless a complete one with the same combos, period and series is there."""
    path = unit_dir(root, part, name, tf, sym)
    if unit_complete(path, combos, start_ms, end_ms, H.series(sym, tf)):
        return path
    H.disk_check(root)
    return write_unit(path, compute_unit(name, tf, sym, combos, start_ms, end_ms))


def removed_of(units: list) -> dict:
    """3.7 over the coins of one (name, timeframe): {combo index: 'SYM: exception'} when any coin raised."""
    out = {}
    for u in units:
        for i, txt in u.raised.items():
            out.setdefault(i, f"{u.meta['sym']}: {txt}")
    return out
