"""The locked signal code of the three Supertrend strategies, loaded only after hash checks, and the signals of every
grid setting on one bar series.

* ``research/entry_study/param_defs/<STRAT>.py`` is checked against ``research/entry_study/DEFS_BC.sha256``, whose own
  hash is pinned below (as research/st_custom/common.load_param_def does).
* the indicator modules come from ``paperbot.sweepsig.lib()`` (third_party/sweep, hash-checked there).
* Supertrend / KST / Klinger are memoised per series while the grid runs (the study's memo: the locked signals() code is
  unchanged, it only does not recompute an identical call). ``selfcheck`` compares memoised and plain results.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from paperbot import sweepsig  # noqa: E402

from . import grid as G  # noqa: E402

sweepsig.lib()
import fg_fast  # noqa: E402
import fg_indicators as fg  # noqa: E402
import pine_indicators as pi  # noqa: E402,F401

PARAM_DIR = os.path.join(ROOT, "research", "entry_study", "param_defs")
DEFS_MANIFEST = os.path.join(ROOT, "research", "entry_study", "DEFS_BC.sha256")
DEFS_MANIFEST_PIN = "185dbcf858e93f694d0775e12925c1904373d0db002a4df7bf3cfcefa3d56044"


class LockedCodeChanged(RuntimeError):
    pass


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


_MODS: dict = {}


def param_def(name: str):
    """The locked param_defs/<name>.py module (hash-checked)."""
    if name in _MODS:
        return _MODS[name]
    if _sha(DEFS_MANIFEST) != DEFS_MANIFEST_PIN:
        raise LockedCodeChanged("DEFS_BC.sha256 does not match its pinned hash")
    want = None
    with open(DEFS_MANIFEST) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == f"param_defs/{name}.py":
                want = parts[0].lower()
    path = os.path.join(PARAM_DIR, f"{name}.py")
    with open(path, "rb") as fh:
        data = fh.read()
    if want is None or hashlib.sha256(data).hexdigest() != want:
        raise LockedCodeChanged(f"param_defs/{name}.py hash mismatch")
    spec = importlib.util.spec_from_file_location(f"_demobot_pd_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    exec(compile(data, path, "exec"), mod.__dict__)
    _MODS[name] = mod
    return mod


def verify() -> dict:
    """Hash checks of everything the signals depend on (raises LockedCodeChanged)."""
    out = {"sweep": sweepsig.verify()["prereg_sha256_file"]}
    for s in G.STRATS:
        param_def(s)
        out[s] = "ok"
    return out


# ------------------------------------------------------------------ memo
_MEMO: dict = {}
_TOKEN = [None]
_ORIG = {"st": fg_fast.supertrend, "kst": fg.kst, "kvo": fg.klinger_oscillator}


def _st_memo(df, atr_length=10, multiplier=3.0):
    if _TOKEN[0] is None:
        return _ORIG["st"](df, atr_length, multiplier)
    key = ("st", _TOKEN[0], len(df), int(atr_length), float(multiplier))
    if key not in _MEMO:
        _MEMO[key] = _ORIG["st"](df, atr_length, multiplier)
    return tuple(s.copy() for s in _MEMO[key])


def _kst_memo(close, roc_lengths=(10, 15, 20, 30), sma_lengths=(10, 10, 10, 15), signal_length=9):
    if _TOKEN[0] is None:
        return _ORIG["kst"](close, roc_lengths, sma_lengths, signal_length)
    key = ("kst", _TOKEN[0], len(close), tuple(int(x) for x in roc_lengths), tuple(int(x) for x in sma_lengths),
           int(signal_length))
    if key not in _MEMO:
        _MEMO[key] = _ORIG["kst"](close, roc_lengths, sma_lengths, signal_length)
    return tuple(s.copy() for s in _MEMO[key])


def _kvo_memo(df, fast_length=34, slow_length=55, signal_length=13):
    if _TOKEN[0] is None:
        return _ORIG["kvo"](df, fast_length, slow_length, signal_length)
    key = ("kvo", _TOKEN[0], len(df), int(fast_length), int(slow_length), int(signal_length))
    if key not in _MEMO:
        _MEMO[key] = _ORIG["kvo"](df, fast_length, slow_length, signal_length)
    return tuple(s.copy() for s in _MEMO[key])


_SEQ = [0]


def _memo_on() -> None:
    _MEMO.clear()
    _SEQ[0] += 1
    _TOKEN[0] = _SEQ[0]
    fg_fast.supertrend = _st_memo
    fg.kst = _kst_memo
    fg.klinger_oscillator = _kvo_memo


def _memo_off() -> None:
    _MEMO.clear()
    _TOKEN[0] = None
    fg_fast.supertrend = _ORIG["st"]
    fg.kst = _ORIG["kst"]
    fg.klinger_oscillator = _ORIG["kvo"]


def frame(ts_ms: np.ndarray, o, h, lo, c, v, tf: str) -> pd.DataFrame:
    df = pd.DataFrame({"ts": pd.to_datetime(np.asarray(ts_ms, np.int64), unit="ms", utc=True),
                       "open": np.asarray(o, float), "high": np.asarray(h, float), "low": np.asarray(lo, float),
                       "close": np.asarray(c, float), "volume": np.asarray(v, float)})
    df.attrs["tf"] = tf
    return df


def combo_side(strat: str, c: int, df: pd.DataFrame, tf: str) -> np.ndarray:
    """int8 side array (+1 / -1 / 0) of one setting."""
    lg, sh = param_def(strat).signals(df, tf, **G.overrides(strat, c))
    lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
    return np.where(lg, 1, np.where(sh, -1, 0)).astype(np.int8)


def grid_sides(strat: str, df: pd.DataFrame, tf: str, last_only: bool = False, combos=None) -> np.ndarray:
    """Signals of every setting of ``strat`` on ``df``: int8 (ncombo, len(df)), or (ncombo,) for the last bar."""
    combos = range(G.NCOMBO[strat]) if combos is None else combos
    rows = []
    _memo_on()
    try:
        for c in combos:
            s = combo_side(strat, c, df, tf)
            rows.append(s[-1] if last_only else s)
    finally:
        _memo_off()
    return np.array(rows, np.int8)


def atr14(df: pd.DataFrame) -> np.ndarray:
    """ATR14 of the series (the study's stop distance source, fg.atr)."""
    return fg.atr(df, 14).to_numpy(float)


def selfcheck(df: pd.DataFrame, tf: str, strat: str, combos=(0, 1)) -> bool:
    """Memoised grid result == plain locked call for a few settings."""
    combos = list(combos) + [G.default_combo(strat)]
    memo = grid_sides(strat, df, tf, combos=combos)
    for i, c in enumerate(combos):
        if not np.array_equal(memo[i], combo_side(strat, c, df, tf)):
            return False
    return True
