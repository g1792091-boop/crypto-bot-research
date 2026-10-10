"""커스텀값 실시간 비교 (owners' "2번", 2026-10-10): what the nightly custom-value shadow (paperbot/paramshadow.py) wrote
about the 36 strategies' numbers since the v4 run started. Read-only over that job's own output files; nothing is
recomputed here, no database is opened and paramshadow itself is not imported (numpy / pandas / the engine stay out of
the dashboard process).

    GET /api/v4/paramlive               the whole grid: status, the one Korean line, totals, the texts, and one COMPACT
                                        cell per strategy x timeframe (no variant rows)            (분석 › 커스텀값 비교)
    GET /api/v4/paramlive/<strategy>    that strategy's four cells in full: every one-number variant with its parameter's
                                        Korean name                                (매매법 상세 › 커스텀값 실시간 비교)

Files (``PAPERBOT_PARAMSHADOW_DIR`` or /var/lib/paperbot/paramshadow, paramshadow.DEFAULT_OUT):

    last.json   the summary (status ok | filling | no_run); parsed once per file mtime + size, non-finite numbers made
                null (a JSON answer must never fail to encode)
    error.json  the last failed night ({generated_ms, error, line_ko}; the next good night removes it). When it is newer
                than last.json the answer carries ``error_ko`` (its line_ko) and ``error_at`` next to the last good data.

A missing summary is ``{"available": false, "none_ko": "아직 첫 계산 전입니다 ..."}``, an unreadable one says so, a
no_run summary gives its own line; never a 500. An unknown strategy is a 404 only when a summary with cells exists.
HONESTY: a shadow and a reference, never a verdict: the texts (texts_ko) and the one line (line_ko) come from
paramshadow's own TEXTS_KO / summary_line through the file, so the page says what the job says; a ★ is the job's own
luck-corrected mark, never one computed here.
"""
from __future__ import annotations

import json
import math
import os
import threading
from typing import Callable, Optional

from fastapi import HTTPException

DIR = "/var/lib/paperbot/paramshadow"        # paperbot/paramshadow.py DEFAULT_OUT (deploy/paperbot-paramshadow.service)
SUMMARY = "last.json"
ERROR = "error.json"
TFS = ("15m", "30m", "1h", "4h")

NONE_KO = "아직 첫 계산 전입니다 (매일 10:00 KST에 계산)"
BAD_KO = "계산 결과 파일을 읽지 못했습니다 (다음 계산 때 다시 씁니다)"
UNKNOWN_KO = "그런 매매법이 없습니다"
LABEL_KO = "그림자 계좌 · 참고용 (판정 아님)"
ABOUT_KO = ("커스텀값 그림자 = 기존 36개 매매법의 숫자 하나만 바꿔(×0.5 · ×0.75 · ×1.25 · ×1.5) v4 시작부터 다시 계산하는 "
            "그림자 계좌입니다. 실제 계좌 · 주문 · 30일 판정과는 상관없습니다.")
SETTING_KEYS = ("version", "initial_equity", "taker_fee", "slippage", "leverage_rule", "stop_atr")

_CACHE: dict = {}
_LOCK = threading.Lock()
_BAD = object()                               # a file that exists but cannot be read as a JSON object


def out_dir() -> str:
    return os.environ.get("PAPERBOT_PARAMSHADOW_DIR") or DIR


def _stamp(path: str) -> Optional[tuple]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _clean(x):
    """The same JSON with NaN / inf as null (FastAPI's encoder refuses them: a 500 otherwise)."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def _cached(path: str, build: Callable):
    """(stamp, value): build(doc) once per file mtime + size; value None = no file, _BAD = unreadable."""
    stamp = _stamp(path)
    if stamp is None:
        return None, None
    with _LOCK:
        hit = _CACHE.get(path)
        if hit and hit[0] == stamp:
            return hit
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict):
            raise ValueError("not an object")
        val = build(_clean(doc))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        val = _BAD
    with _LOCK:
        _CACHE[path] = (stamp, val)
    return stamp, val


# ------------------------------------------------------------------ names
def _param_ko() -> dict:
    try:
        from .params import PARAM_KO
    except Exception:  # noqa: BLE001  (a name table only)
        return {}
    return PARAM_KO


def _strategy_ko() -> dict:
    try:
        from ...agents.roster3 import STRATEGY_KO
    except Exception:  # noqa: BLE001  (a name table only)
        return {}
    return STRATEGY_KO


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


# ------------------------------------------------------------------ the summary, prepared once per file
def _prepare(doc: dict) -> dict:
    pko, sko = _param_ko(), _strategy_ko()
    cells = [c for c in (doc.get("cells") or []) if isinstance(c, dict) and c.get("strategy") and c.get("tf")]
    compact, by = [], {}
    for c in cells:
        name = str(c["strategy"])
        base, real, par = c.get("base") or {}, c.get("real") or {}, c.get("parity") or {}
        params = [{**p, "param_ko": pko.get(p.get("name"))} for p in (c.get("params") or []) if isinstance(p, dict)]
        variants = [{**v, "param_ko": pko.get(v.get("param"))} for v in (c.get("variants") or []) if isinstance(v, dict)]
        best = c.get("best") if isinstance(c.get("best"), dict) else None
        if best is not None:
            row = next((v for v in variants if v.get("key") == best.get("key")), None)
            best = {**best, **({"param": row.get("param"), "param_ko": row.get("param_ko"), "mult": row.get("mult"),
                                "value": row.get("value")} if row else {})}
        compact.append({
            "strategy": name, "tf": c["tf"], "name_ko": sko.get(name),
            "base": {k: base.get(k) for k in ("trades", "pnl", "win_rate")},
            "real": {k: real.get(k) for k in ("trades", "pnl")},
            "parity": {"share": par.get("share")},
            "k": c.get("k"), "better": c.get("better"), "stars": c.get("stars"), "best": best})
        by.setdefault(name, []).append({**c, "params": params, "variants": variants, "best": best})
    order = {t: i for i, t in enumerate(TFS)}
    for rows in by.values():
        rows.sort(key=lambda x: order.get(x["tf"], 9))
    status = doc.get("status")
    head = {
        "status": status, "line_ko": doc.get("line_ko"), "generated_ms": _num(doc.get("generated_ms")),
        "run_start_ms": _num(doc.get("run_start_ms")), "through_day": doc.get("through_day"),
        "days": doc.get("days"), "days_remaining": doc.get("days_remaining"),
        "texts_ko": doc.get("texts_ko") if isinstance(doc.get("texts_ko"), dict) else {},
        "settings": {k: (doc.get("settings") or {}).get(k) for k in SETTING_KEYS},
        "multipliers": doc.get("multipliers"), "min_trades": doc.get("min_trades"), "alpha": doc.get("alpha"),
        "tfs": doc.get("tfs") or list(TFS),
    }
    return {"head": head, "has": bool(cells) and status != "no_run", "compact": compact, "by": by,
            "overview": doc.get("overview") if isinstance(doc.get("overview"), dict) else {},
            "notes": [str(n) for n in (doc.get("notes") or [])][-20:], "names": sko}


def _summary(folder: str):
    return _cached(os.path.join(folder, SUMMARY), _prepare)


def _error(folder: str, summary_stamp, summary_ms) -> dict:
    """{error_ko, error_at} when error.json exists and is newer than the summary, else {}."""
    path = os.path.join(folder, ERROR)
    stamp, e = _cached(path, lambda d: d)
    if stamp is None:
        return {}
    if e is _BAD:
        e = {}
    at = _num(e.get("generated_ms")) or stamp[0] // 1_000_000
    if summary_stamp is not None:
        newer = at > summary_ms if summary_ms else stamp[0] > summary_stamp[0]
        if not newer:
            return {}
    line = e.get("line_ko") or ("커스텀값 그림자: 이번 밤 계산 못 함" + (f" ({str(e.get('error'))[:120]})" if e.get("error") else ""))
    return {"error_ko": str(line), "error_at": at}


def _base(folder: Optional[str]):
    """(prepared | None, answer head): the parts both routes share, including the not-available states."""
    folder = folder or out_dir()
    stamp, p = _summary(folder)
    ok = p is not None and p is not _BAD
    err = _error(folder, stamp if ok else None, p["head"]["generated_ms"] if ok else None)
    out = {"label_ko": LABEL_KO, "about_ko": ABOUT_KO}
    if not ok:
        return None, {**out, "available": False, "status": None, "none_ko": BAD_KO if p is _BAD else NONE_KO, **err}
    if not p["has"]:
        return None, {**out, **p["head"], "available": False,
                      "none_ko": p["head"]["line_ko"] or NONE_KO, **err}
    return p, {**out, **p["head"], "available": True, **err}


# ------------------------------------------------------------------ the answers
def overview(folder: Optional[str] = None) -> dict:
    p, out = _base(folder)
    if p is None:
        return out
    return {**out, "overview": p["overview"], "notes": p["notes"], "cells": p["compact"]}


def strategy_view(strategy: str, folder: Optional[str] = None) -> Optional[dict]:
    """One strategy's four cells in full; None (the route's 404) for a name not among the cells of a real summary."""
    p, out = _base(folder)
    if p is None:
        return {**out, "strategy": strategy}
    cells = p["by"].get(strategy)
    if cells is None:
        return None
    return {**out, "strategy": strategy, "name_ko": p["names"].get(strategy), "cells": cells}


def register(app, ctx) -> dict:
    @app.get("/api/v4/paramlive")
    def get_paramlive():
        """커스텀값 그림자: the 36 x 4 grid (compact cells), status and texts (read-only files, mtime cache)."""
        return overview()

    @app.get("/api/v4/paramlive/{strategy}")
    def get_paramlive_strategy(strategy: str):
        """커스텀값 그림자: one strategy's four timeframes with every one-number variant (read-only files)."""
        out = strategy_view(strategy)
        if out is None:
            raise HTTPException(404, UNKNOWN_KO)
        return out

    return {"routes": ["/api/v4/paramlive", "/api/v4/paramlive/{strategy}"], "overview": overview,
            "strategy": strategy_view}
