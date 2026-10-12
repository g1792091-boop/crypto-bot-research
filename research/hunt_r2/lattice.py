"""Hunt round 2 (research/hunt_r2/PREREG_HUNT_R2.md, sections 3.1-3.6): the 85 names, their numbers, the order
rules, the coarse lattice (1/2x, 1x, 2x) and the fine box (a check, never a source of a tested number), the one-step
positions, system identity and the code-only counts (``counts.json``).

    python -m research.hunt_r2.lattice counts [--out research/hunt_r2/counts.json]

Nothing here reads a price. Values come from ``research/fullgrid/grid.values``' own rules (half-up rounding, at least
2, clipping of declared length bounds and of neutral thresholds, dropping of multipliers and absolute thresholds
outside their bounds); a value of the coarse lattice is therefore always a value of ``grid.values`` for that number
(tests/test_hunt_r2_core.py).

Kinds (3.1, 3.2): F1 = E1-E3 (new declarations, the defaults are PREREG_HUNT 5's constants), F2 = the full grid's 36
core names (``run.params_of("core", name)``), F3 = 42 of the 44 DeepSeek definitions (``ds_defs.DEFS``; F2_DEMARK and
F6_VWAP_CROSS have no numbers and are out), F5 = TURTLE20, TURTLE55, TSMOM7, TSMOM28 (lengths in days).
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import sys
from dataclasses import dataclass, field

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TFS = ("15m", "30m", "1h", "4h")
GATES = ("G1", "NONE")
FAMILY_ORDER = ("F1", "F2", "F3", "F5")          # W 5's family order (F4 is out of round 2, 3.1)
KIND_OF = {"F1": "hunt", "F2": "core", "F3": "ds", "F5": "famous"}
COARSE_IDX = (1, 4, 7)                           # grid.MULTS / grid.NEUTRAL_F indices of 1/2x, 1x, 2x (3.4)
BLOCK_OF = {1: (0, 1, 2), 4: (3, 4, 5), 7: (6, 7, 8)}   # the 9-step block around each coarse factor (3.5)
OUT_F3 = ("F2_DEMARK", "F6_VWAP_CROSS")          # no numbers (3.1)
COUNTS_REL = "research/hunt_r2/counts.json"
INF = math.inf


def _p(name, default, kind, neutral=None, bounds=None) -> dict:
    d = {"name": name, "default": default, "kind": kind, "neutral": neutral}
    if bounds is not None:
        d["bounds"] = bounds
    return d


# 3.2: F1 declarations (defaults = PREREG_HUNT 5 / entries_wide constants)
F1_DECL = {
    "E1": [_p("channel", 55, "length"), _p("vol_len", 20, "length"),
           _p("vol_mult", 2.0, "threshold_neutral", neutral=1.0, bounds=(1.0, INF))],
    "E2": [_p("window", 120, "length"), _p("pct", 20.0, "threshold_abs", bounds=(0.0, 100.0)),
           _p("bb_len", 20, "length"), _p("bb_k", 2.0, "mult")],
    "E3": [_p("threshold", 1.5, "threshold_neutral", neutral=1.0, bounds=(1.0, INF)), _p("fast", 14, "length"),
           _p("slow", 100, "length"), _p("side_len", 20, "length")],
}
# 3.1: F5 (W 3.3, entries_wide.FAMOUS_COMBO), lengths in days
F5_DECL = {
    "TURTLE20": [_p("entry_days", 20, "length"), _p("exit_days", 10, "length")],
    "TURTLE55": [_p("entry_days", 55, "length"), _p("exit_days", 20, "length")],
    "TSMOM7": [_p("lookback_days", 7, "length")],
    "TSMOM28": [_p("lookback_days", 28, "length")],
}
F1_NAMES = ("E1", "E2", "E3")
F5_NAMES = ("TURTLE20", "TURTLE55", "TSMOM7", "TSMOM28")

# 3.3: strict order rules (closed at the design hash). Each chain a < b (< c).
ORDER_RULES = {
    "N01_ST_EMA": [("ema_fast", "ema_slow")],
    "N03_ADX_GC": [("ema_fast", "ema_slow")],
    "N06_MACD_ORB": [("macd_fast", "macd_slow")],
    "N18_VWMA_MACD": [("macd_fast", "macd_slow")],
    "N07_ICHI_CMO": [("tenkan_len", "kijun_len", "senkou_b_len")],
    "N08_ICHI_WR": [("tenkan_len", "kijun_len")],
    "N12_ICHI_AO": [("tenkan_len", "kijun_len"), ("ao_fast_len", "ao_slow_len")],
    "N14_ICHI_RSI": [("tenkan_len", "kijun_len")],
    "N15_KC_AO": [("ao_fast", "ao_slow")],
    "OBV_B": [("ao_fast", "ao_slow")],
    "N09_ALLIG_AROON": [("lips_len", "teeth_len", "jaw_len")],
    "F4_PULL": [("ema_fast", "ema_mid", "ema_slow")],
    "F4_PULL_RSI": [("ema_fast", "ema_slow")],
    "E3": [("fast", "slow")],
    "TURTLE20": [("exit_days", "entry_days")],
    "TURTLE55": [("exit_days", "entry_days")],
}

# 3.6 "one system, two names": names that share one family code (same numbers in bars = the same system). Every
# other name is its own code. The shared numbers are compared in days (x bars per day of the same timeframe).
CODE_OF = {"TSMOM7": "tsmom", "TSMOM28": "tsmom", "TURTLE20": "donchian", "TURTLE55": "donchian"}


def _grid():
    from research.hunt import entries_wide as EW
    return EW.fullgrid_run().G


def _run():
    from research.hunt import entries_wide as EW
    return EW.fullgrid_run()


# ------------------------------------------------------------------ names
def names() -> list:
    """The 85 names as (family, name) in W 5 order: F1 E1-E3; F2 run.core_names() (sorted); F3 ds_defs.DEFS order
    without the two number-less definitions; F5 TURTLE20, TURTLE55, TSMOM7, TSMOM28."""
    R = _run()
    out = [("F1", n) for n in F1_NAMES]
    out += [("F2", n) for n in R.core_names()]
    out += [("F3", n) for n in R.ds_module().DEFS if n not in OUT_F3]
    out += [("F5", n) for n in F5_NAMES]
    return out


def family_of(name: str) -> str:
    if name in F1_DECL:
        return "F1"
    if name in F5_DECL:
        return "F5"
    R = _run()
    if name in R.core_names():
        return "F2"
    if name in R.ds_module().DEFS and name not in OUT_F3:
        return "F3"
    raise KeyError(f"{name} is not a round-2 name")


def params_of(name: str) -> list:
    fam = family_of(name)
    if fam == "F1":
        return F1_DECL[name]
    if fam == "F5":
        return F5_DECL[name]
    return list(_run().params_of(KIND_OF[fam], name))


def tfs_of(name: str) -> tuple:
    """Timeframes of the name (F3: ds_defs.TFS_OF, the five ET-session names without 4h; W 4)."""
    if family_of(name) == "F3":
        allowed = _run().ds_module().TFS_OF[name]
        return tuple(tf for tf in TFS if tf in allowed)
    return TFS


# ------------------------------------------------------------------ values (3.4, 3.5)
def _rhu(x: float) -> int:
    return int(math.floor(x + 0.5))


def value_at(strategy: str, spec: dict, idx: int):
    """The value of ``spec`` at grid.MULTS / grid.NEUTRAL_F index ``idx`` under grid.values' own rules, or None when
    grid.values drops it (a multiplier / absolute threshold outside its bounds, a neutral threshold on its neutral
    point). Index 4 (1x) is the default itself in grid.values' representation."""
    G = _grid()
    d, kind = spec["default"], spec["kind"]
    lo, hi = spec.get("bounds") or G.BOUNDS.get((strategy, spec["name"]), (0.0, INF))
    if kind == "length" and isinstance(d, (list, tuple)):
        m = G.MULTS[idx]
        return [max(2, _rhu(x * m)) for x in d] if idx != 4 else list(d)
    if kind == "length":
        if idx == 4:
            return d
        m = G.MULTS[idx]
        return min(max(2, _rhu(d * m)), hi) if hi < INF else max(2, _rhu(d * m))
    if idx == 4:
        return float(d)
    if kind in ("mult", "threshold_abs"):
        v = round(float(d) * G.MULTS[idx], 12)
        return v if (lo < v <= hi or (v == hi and hi < INF)) else None
    if kind == "threshold_neutral":
        n = float(spec["neutral"])
        v = round(n + G.NEUTRAL_F[idx] * (float(d) - n), 12)
        v = min(max(v, lo), hi)
        return v if v != n else None
    raise ValueError(f"{strategy}.{spec['name']}: unknown kind {kind}")


def hkey(v):
    """Hashable form of a value (list lengths as tuples)."""
    return tuple(v) if isinstance(v, list) else v


def coarse_values(strategy: str, spec: dict) -> list:
    """[(value, factor index)] ascending by value (lists: as sorted tuples, grid.values' order), deduplicated; a value
    reached from several coarse factors keeps the factor nearest 1x in log distance (3.5)."""
    best: dict = {}
    for idx in COARSE_IDX:
        v = value_at(strategy, spec, idx)
        if v is None:
            continue
        k = hkey(v)
        dist = abs(idx - 4)
        if k not in best or dist < best[k][1]:
            best[k] = (v, dist, idx)
    return [(best[k][0], best[k][2]) for k in sorted(best)]


def block_values(strategy: str, spec: dict, factor_idx: int) -> list:
    """The deduplicated, ascending values of the 9-step block around a coarse factor (3.5)."""
    vals = {}
    for idx in BLOCK_OF[factor_idx]:
        v = value_at(strategy, spec, idx)
        if v is not None:
            vals[hkey(v)] = v
    return [vals[k] for k in sorted(vals)]


# ------------------------------------------------------------------ validity (3.3)
def valid_r2(name: str, combo: dict) -> bool:
    """grid.valid (SAR caps, two bodies) and the strict order rules of 3.3."""
    if not _grid().valid(name, combo):
        return False
    for chain in ORDER_RULES.get(name, ()):
        for a, b in zip(chain[:-1], chain[1:]):
            if not hkey(combo[a]) < hkey(combo[b]):
                return False
    return True


def default_combo(name: str) -> dict:
    """The default numbers in the lattice's representation (grid.values: lengths as declared, other kinds float)."""
    out = {}
    for p in params_of(name):
        d = p["default"]
        out[p["name"]] = (list(d) if isinstance(d, (list, tuple)) else d) if p["kind"] == "length" else float(d)
    return out


# ------------------------------------------------------------------ identity (3.6)
def canon(combo: dict) -> str:
    """Canonical JSON: sorted keys, lists kept, floats as repr (json's float form), compact separators."""
    return json.dumps({k: (list(v) if isinstance(v, tuple) else v) for k, v in combo.items()}, sort_keys=True,
                      separators=(",", ":"))


def combo_sha(combo: dict) -> str:
    return hashlib.sha256(canon(combo).encode()).hexdigest()[:12]


def system_id(family: str, name: str, tf: str, gate: str, combo: dict) -> str:
    return f"R2:{family}:{name}:{tf}:{gate}:{combo_sha(combo)}"


def log_distance(name: str, combo: dict) -> float:
    """Sum over numbers of |ln(value / default)| (list lengths: element-wise)."""
    d = default_combo(name)
    s = 0.0
    for k, v in combo.items():
        a, b = (list(v), list(d[k])) if isinstance(v, (list, tuple)) else ([v], [d[k]])
        for x, y in zip(a, b):
            s += abs(math.log(float(x) / float(y))) if x and y and (x > 0) == (y > 0) else INF
    return s


def owner_of_shared(code: str, combo: dict, names_: list) -> str:
    """3.6: the name a shared system belongs to: the one whose default is nearer in log distance; on a tie the
    earlier name (``names_`` in W 5 order)."""
    best = None
    for n in names_:
        if CODE_OF.get(n) != code:
            continue
        ld = log_distance(n, combo)
        if best is None or ld < best[0] - 1e-12:
            best = (ld, n)
    return best[1]


# ------------------------------------------------------------------ lattices
@dataclass
class Lattice:
    """A name's coarse lattice (or a fine box): numbers in declared order, each number's ascending values, the points
    (value-index tuples, product order minus valid_r2 failures) and their combos. ``nb[i]`` = the 2k one-step
    positions of point i (number j down, number j up, ...), as point indices, -1 where the position does not exist."""
    name: str
    family: str
    params: list
    values: list
    keys: list
    combos: list
    nb: np.ndarray
    default: int = -1
    factors: list = field(default_factory=list)      # coarse only: per number, the factor index of each value
    edge: np.ndarray = None                          # coarse only: any number at its first or last value

    @property
    def k(self) -> int:
        return len(self.params)

    def __len__(self) -> int:
        return len(self.combos)

    def index(self, combo: dict) -> int:
        key = tuple(next(i for i, v in enumerate(self.values[j]) if hkey(v) == hkey(combo[p]))
                    for j, p in enumerate(self.params))
        return self._pos[key]

    def __post_init__(self):
        self._pos = {key: i for i, key in enumerate(self.keys)}


def _neighbours(keys: list, n_vals: list) -> np.ndarray:
    pos = {key: i for i, key in enumerate(keys)}
    k = len(n_vals)
    nb = np.full((len(keys), 2 * k), -1, np.int64)
    for i, key in enumerate(keys):
        for j in range(k):
            for d, col in ((-1, 2 * j), (1, 2 * j + 1)):
                kk = key[:j] + (key[j] + d,) + key[j + 1:]
                if 0 <= kk[j] < n_vals[j]:
                    nb[i, col] = pos.get(kk, -1)
    return nb


def _lattice(name: str, family: str, specs: list, vals: list, factors: list | None = None) -> Lattice:
    pnames = [p["name"] for p in specs]
    keys, combos = [], []
    for key in itertools.product(*[range(len(v)) for v in vals]):
        combo = {p: vals[j][key[j]] for j, p in enumerate(pnames)}
        if valid_r2(name, combo):
            keys.append(tuple(key))
            combos.append(combo)
    nb = _neighbours(keys, [len(v) for v in vals])
    lat = Lattice(name, family, pnames, vals, keys, combos, nb, factors=factors or [])
    return lat


_COARSE: dict = {}


def coarse(name: str) -> Lattice:
    """The name's coarse lattice (3.4)."""
    lat = _COARSE.get(name)
    if lat is not None:
        return lat
    specs = params_of(name)
    cv = [coarse_values(name, p) for p in specs]
    vals = [[v for v, _f in c] for c in cv]
    facs = [[f for _v, f in c] for c in cv]
    lat = _lattice(name, family_of(name), specs, vals, facs)
    d = default_combo(name)
    lat.default = lat.index(d)
    if lat.combos[lat.default] != d and canon(lat.combos[lat.default]) != canon(d):
        raise RuntimeError(f"{name}: the 1x lattice point is not the default")
    nv = [len(v) for v in vals]
    lat.edge = np.asarray([any(nv[j] > 1 and key[j] in (0, nv[j] - 1) for j in range(len(nv))) for key in lat.keys])
    _COARSE[name] = lat
    return lat


def box(name: str, peak: dict) -> Lattice:
    """The fine box around a coarse point (3.5): per number the deduplicated values of the 9-step block holding the
    point's coarse factor; the product minus valid_r2 failures (the 3.7 removals are applied by the caller)."""
    c = coarse(name)
    specs = params_of(name)
    vals = []
    for j, p in enumerate(specs):
        vi = next(i for i, v in enumerate(c.values[j]) if hkey(v) == hkey(peak[p["name"]]))
        vals.append(block_values(name, p, c.factors[j][vi]))
    return _lattice(name, family_of(name), specs, vals)


# ------------------------------------------------------------------ counts (3.4, 3.6, appendix A)
def counts() -> dict:
    """Per name: numbers with their coarse values, coarse points, the points grid.valid alone keeps, the largest box
    over every possible coarse peak; totals. Code only (no data)."""
    G = _grid()
    rows, tot = [], {"coarse": 0, "defaults": 0, "grid_valid_only": 0, "cells": 0, "largest_box": 0, "tries": 0,
                     "selectable": 0, "stage0": 0}
    for fam, name in names():
        lat = coarse(name)
        specs = params_of(name)
        gv = sum(1 for key in itertools.product(*[range(len(v)) for v in lat.values])
                 if G.valid(name, {p: lat.values[j][key[j]] for j, p in enumerate(lat.params)}))
        largest = max(len(box(name, cb)) for cb in lat.combos)
        n_tf = len(tfs_of(name))
        st0 = n_tf * len(GATES)
        row = {"family": fam, "name": name, "timeframes": list(tfs_of(name)),
               "numbers": [{"name": p["name"], "kind": p["kind"], "default": p["default"],
                            "coarse": lat.values[j]} for j, p in enumerate(specs)],
               "coarse_points": len(lat), "grid_valid_only": gv, "largest_box": largest,
               "stage0_systems": st0, "selectable": st0 + len(lat) - 1, "tries": st0 + len(lat) - 1 + largest - 1}
        rows.append(row)
        tot["coarse"] += len(lat)
        tot["defaults"] += 1
        tot["grid_valid_only"] += gv
        tot["cells"] += len(lat) * n_tf
        tot["largest_box"] += largest
        tot["tries"] += row["tries"]
        tot["selectable"] += row["selectable"]
        tot["stage0"] += st0
    tot["new_coarse"] = tot["coarse"] - tot["defaults"]
    tot["order_rule_removed"] = tot["grid_valid_only"] - tot["coarse"]
    return {"what": "PREREG_HUNT_R2 3.4-3.6 and appendix A, from code only (no data read)",
            "names": len(rows), "totals": tot, "rows": rows}


def write_counts(path: str | None = None) -> str:
    path = path or os.path.join(ROOT, COUNTS_REL)
    doc = counts()
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m research.hunt_r2.lattice")
    ap.add_argument("cmd", choices=["counts"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    p = write_counts(a.out)
    with open(p) as fh:
        print(json.dumps(json.load(fh)["totals"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
