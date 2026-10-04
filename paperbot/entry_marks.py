"""Entry marks: support / resistance and entry-strength numbers for each live signal.

Descriptions only. The pre-registered entry study (research/entry_study: PREREG_ENTRY.md,
RESULTS_ENTRY_A.md, RESULTS_ENTRY_BC.md) measured exactly these numbers on five years of
signals and found no effect on the trade outcome. They are recorded with every signal so the
owners and the specialists can read them next to the chart; nothing trades on them.

- ``sr``        research/entry_study/sr.py (PREREG section 2), loaded by path and run unchanged:
                levels_for on the signal bar only (``at``), features_for for the signal side.
                room / floor = distance to the nearest price level ahead / behind in ATR14
                (capped at 10); level_before_lock = that level ahead is closer than the first
                lock price (+12% net ROE at sr.leverage_at_close, fill = signal close);
                support_before_stop = the level behind is closer than the 2 ATR stop;
                breakout = the signal bar's close passed a level in the trade direction.
- ``strength``  research/entry_study/strength_defs/<NAME>.py (PREREG section 3, B): the
                strategy's own 1-3 FEATURES, value of the side it trades on the signal bar.
                Each file is checked against DEFS_BC.sha256 before it is loaded.

Both use closed bars only: the chart frame ends at the signal bar. The levels need more history
than the 4h signal window holds (swing points of the last 300 daily bars), so the service sends
older 5m bars for them (``marks_window_5m``); the signal frame itself is never changed.
Any failure is caught and recorded as {"error": ...}; it never touches signal handling.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import os
import sys
import time
import warnings
from typing import Optional

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDY = os.path.join(ROOT, "research", "entry_study")
SR_PY = os.path.join(STUDY, "sr.py")
STRENGTH_DIR = os.path.join(STUDY, "strength_defs")
DEFS_SHA = os.path.join(STUDY, "DEFS_BC.sha256")

# KIND codes of sr.py in plain Korean (the dashboard and the loss cards show these)
KIND_KO = {11: "스윙 고점", 12: "스윙 저점", 21: "전날 고가", 22: "전날 저가", 31: "지난주 고가", 32: "지난주 저가",
           40: "라운드 넘버", 51: "매물 최다 가격", 52: "매물대 위 끝", 53: "매물대 아래 끝",
           61: "상위 봉 스윙 고점", 62: "상위 봉 스윙 저점"}
FLAGS = ("level_before_lock", "support_before_stop", "breakout")
# FEATURES units written in English, in Korean for the dashboard (the Korean ones are kept as they are)
UNIT_KO = {"ATR14": "ATR", "bars": "봉", "bars (0-1)": "봉(0~1)", "bars (0-2)": "봉(0~2)", "degrees": "도",
           "ADX points": "ADX 포인트", "DI points": "DI 포인트", "RSI points": "RSI 포인트", "MFI points": "MFI 포인트",
           "CMO points": "CMO 포인트", "STC points": "STC 포인트", "StochRSI K points": "K 포인트", "VI units": "VI",
           "% (ROC 9)": "%", "% of slow EMA": "% (느린 EMA 대비)", "ATR14 per 3 bars": "3봉당 ATR",
           "x 9-bar mean volume": "9봉 평균 거래량 배수", "bandwidth / 20th-pct threshold": "수축 기준 대비 배수",
           "Klinger / (100 x SMA55 volume)": "거래량 대비"}

_SR = None
_STRENGTH: dict = {}


@contextlib.contextmanager
def _contained():
    """Run research code without leaving its process-wide changes behind: sys.path inserts,
    warnings.filterwarnings("ignore") of rules_bt, and sr._lib's SWEEP_DATA default."""
    path = list(sys.path)
    sweep = os.environ.get("SWEEP_DATA")
    try:
        with warnings.catch_warnings():
            yield
    finally:
        sys.path[:] = path
        if sweep is None:
            os.environ.pop("SWEEP_DATA", None)
        else:
            os.environ["SWEEP_DATA"] = sweep


def _load(name: str, path: str, data: Optional[bytes] = None):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            with _contained():
                if data is None:
                    spec.loader.exec_module(mod)
                else:
                    exec(compile(data, path, "exec"), mod.__dict__)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return mod


def sr_module():
    """research/entry_study/sr.py under a private module name (loaded once per process)."""
    global _SR
    if _SR is None:
        _SR = _load("_paperbot_entry_sr", SR_PY)
    return _SR


def locked_defs() -> dict:
    """{"strength_defs/<NAME>.py": sha256} from DEFS_BC.sha256."""
    out = {}
    with open(DEFS_SHA) as fh:
        for line in fh:
            if line.strip():
                h, rel = line.split(None, 1)
                out[rel.strip()] = h
    return out


def strength_module(name: str):
    """strength_defs/<name>.py, loaded only when its bytes match DEFS_BC.sha256 (the exact
    definition the study ran). None when the strategy has no definition."""
    if name in _STRENGTH:
        return _STRENGTH[name]
    rel = f"strength_defs/{name}.py"
    path = os.path.join(STUDY, rel)
    if not os.path.exists(path):
        _STRENGTH[name] = None
        return None
    data = open(path, "rb").read()
    want = locked_defs().get(rel)
    got = hashlib.sha256(data).hexdigest()
    if want != got:
        raise RuntimeError(f"{rel}: sha256 {got[:12]} != locked {str(want)[:12]}")
    _STRENGTH[name] = _load(f"_paperbot_strength_{name}_{got[:8]}", path, data)
    return _STRENGTH[name]


# ------------------------------------------------------------------ history the levels need
def marks_window_5m(lib, tf: str) -> int:
    """5m bars that make the levels of the last bar equal to the full-history ones: swing points
    of the last 300 (+5) chart and higher-timeframe bars, the 200-bar volume profile and the
    prior UTC week (two calendar weeks), plus one partial higher-timeframe bar at each end."""
    SR = sr_module()
    htf = SR.HTF.get(tf)
    if htf is None:
        return 0
    per = lib.tf_minutes(tf) // 5
    chart = max(SR.PIVOT_LOOKBACK + SR.PIVOT_K, SR.VP_BARS) + 1
    week = 14 * 24 * 12
    hbars = (SR.PIVOT_LOOKBACK + 2 * SR.PIVOT_K + 2) * (lib.tf_minutes(htf) // 5)
    return int(max(chart * per, week, hbars))


# ------------------------------------------------------------------ values
def _num(v, nd: Optional[int] = None):
    """JSON-safe float: None for NaN / inf; ``nd`` decimals when given (prices keep full precision)."""
    v = float(v)
    if not np.isfinite(v):
        return None
    return v if nd is None else round(v, nd)


def _flag(v):
    v = float(v)
    return int(v) if np.isfinite(v) else None


def sr_marks(df: pd.DataFrame, tf: str, sides=(1, -1)) -> dict:
    """{"1": {...}, "-1": {...}}: sr.features_for of the LAST bar of ``df`` for each side.
    ``df``: closed chart bars ending at the signal bar (ts, open, high, low, close, volume)."""
    SR = sr_module()
    with _contained():
        i = len(df) - 1
        lv = SR.levels_for(df, tf, None, at=np.array([i]))
        sides = [int(s) for s in sides]
        f = SR.features_for(df, tf, None, np.full(len(sides), i), np.array(sides), levels=lv)
    out = {}
    for k, s in enumerate(sides):
        d = {"lev": _num(f["lev"][k]), "atr": _num(f["atr"][k]), "close": _num(f["close"][k])}
        for name, tag in (("room", "ahead"), ("floor", "behind")):
            kind = int(f[name + "_kind"][k])
            d[name] = _num(f[name][k], 4)
            d[name + "_type"] = int(f[name + "_type"][k])
            d[name + "_kind"] = kind
            d[name + "_ko"] = KIND_KO.get(kind)
            d[name + "_px"] = _num(f[tag + "_px"][k])
        for name in FLAGS:
            d[name] = _flag(f[name][k])
        d["lock_px"] = _num(f["lock_px"][k])
        d["stop_px"] = _num(f["stop_px"][k])
        out[str(s)] = d
    return out


def strength_marks(name: str, df: pd.DataFrame, tf: str, side: int) -> Optional[dict]:
    """The strategy's strength FEATURES on the last bar of ``df`` for ``side`` (research
    side_values: the long array for a long, the short array for a short). None when the
    strategy has no definition (coin-flip accounts). Values are kept at full float64 precision
    (JSON round-trips them exactly): levrule.quality_score scores them against quality_edges.json,
    whose edges were cut on the exact research values, and a rounded value sitting on an edge (for
    example 20 +- 1e-9 against an edge of 19.9999999970898) would land in the wrong quintile."""
    S = strength_module(name)
    if S is None:
        return None
    with _contained():
        st = S.strength(df, tf)
    i = len(df) - 1
    feats = []
    for f in S.FEATURES:
        long_v, short_v = st[f["name"]]
        v = (long_v if side > 0 else short_v)[i]
        feats.append({"name": f["name"], "label_ko": f["label_ko"], "unit": f["unit"],
                      "unit_ko": UNIT_KO.get(f["unit"], f["unit"]),
                      "higher_is_stronger": bool(f["higher_is_stronger"]), "value": _num(v)})
    return {"side": int(side), "features": feats}


def _err(exc: BaseException) -> dict:
    return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def marks(df: pd.DataFrame, tf: str, sides: dict, sr_df: Optional[pd.DataFrame] = None) -> dict:
    """Marks of one (coin, timeframe) bar. ``sides``: {strategy: side} of the strategies that
    signalled (0 = none). ``df`` is the signal frame (strength), ``sr_df`` the same bars with the
    longer history of marks_window_5m (default df). S/R is computed once for both sides, so the
    coin-flip accounts of that bar get it too. Never raises."""
    t0 = time.perf_counter()
    out: dict = {}
    try:
        if tf not in sr_module().HTF:
            out["sr"] = {"error": f"no higher timeframe for {tf}"}
        else:
            out["sr"] = sr_marks(df if sr_df is None else sr_df, tf)
    except Exception as exc:  # the marks must never block a signal
        out["sr"] = _err(exc)
    t1 = time.perf_counter()
    st = {}
    for name, side in sides.items():
        if not side:
            continue
        try:
            m = strength_marks(name, df, tf, int(side))
        except Exception as exc:
            m = _err(exc)
        if m is not None:
            st[name] = m
    out["strength"] = st
    out["ms"] = {"sr": round((t1 - t0) * 1000, 1), "strength": round((time.perf_counter() - t1) * 1000, 1)}
    return out


def attach(ctx: Optional[dict], m: Optional[dict], name: str, side: int) -> Optional[dict]:
    """The signal's own ctx: the bar's chart context plus ``sr`` of its side and ``strength``
    of its strategy. Unchanged when the bar has no marks."""
    if not m:
        return ctx
    out = dict(ctx or {})
    if "error" in m:
        out["marks_error"] = m["error"]
        return out
    sr = m.get("sr") or {}
    out["sr"] = sr if "error" in sr else sr.get(str(int(side)))
    s = (m.get("strength") or {}).get(name)
    if s is not None:
        out["strength"] = s
    return out


# ------------------------------------------------------------------ chart lines (dashboard)
def chart_bars(tf: str) -> int:
    """Chart-timeframe bars that give the last bar the same levels as full history (marks_window_5m), at most
    6,000 (four Binance requests). 0 when the timeframe has no levels (1d)."""
    from . import sweepsig
    lib = sweepsig.lib()
    n5 = marks_window_5m(lib, tf)
    if not n5:
        return 0
    per = lib.tf_minutes(tf) // 5
    return int(min(6000, -(-n5 // per) + 2))


def chart_levels(df: pd.DataFrame, tf: str, merge_atr: float = 0.1) -> dict:
    """The lines the dashboard draws on the trade chart: sr.levels_for (unchanged) on the LAST closed bar of
    ``df``, the nearest level of each family above the close (resistance) and below it (support), with its
    distance in ATR14. Levels closer than ``merge_atr`` ATR on the same side are shown as one line with both
    names. Descriptive only (the entry study found no effect on outcomes)."""
    SR = sr_module()
    with _contained():
        i = len(df) - 1
        lv = SR.levels_for(df, tf, None, at=np.array([i]))
        atr = float(SR._atr(df)[i])
    close = float(lv["close"][0])
    lines = []
    for col, side in (("up_gt", "resistance"), ("dn_lt", "support")):
        got = []
        for f in range(lv[col].shape[1]):
            p, k = _num(lv[col][0, f]), int(lv[col + "_kind"][0, f])
            if p is None or not k:
                continue
            got.append((p, k))
        got.sort(key=lambda x: abs(x[0] - close))
        for p, k in got:
            near = next((x for x in lines if x["side"] == side and atr > 0 and abs(x["price"] - p) < merge_atr * atr), None)
            if near is not None:
                near["kinds"].append(k)
                near["ko"] = " · ".join(KIND_KO.get(x, str(x)) for x in near["kinds"])
                continue
            lines.append({"price": p, "side": side, "kinds": [k], "ko": KIND_KO.get(k, str(k)),
                          "atr": _num((p - close) / atr, 2) if atr > 0 else None})
    return {"close": close, "atr": _num(atr), "levels": lines}
