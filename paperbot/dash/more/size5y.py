"""손실 크기 규칙 (size5y, 분석 › 손실 크기 규칙, the 36 only): the same 5-year entries and exits of the 36 under other
position-size rules (지금 v4 / 손절 = 잔고 0.5·1·2% / 배수 절반). Read-only; descriptive, not a verdict (설명용, 판정 아님).
Pre-registered in docs/size5y.md; the live rules do not change before the verdict.

    GET /api/v4/size5y                       the study as committed (paperbot/dash/data/size5y.json, written offline by
                                             paperbot/dash/tools/size5y.py) without the per-cell monthly curves
    GET /api/v4/size5y/cell?s=<name>&tf=<tf> one strategy x timeframe with its monthly curves (the drill-down)

Nothing is computed here: the file is read once and again only when it changes (mtime), so there is no background job.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional

from fastapi import HTTPException

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "size5y.json")
LABEL = "설명용, 판정 아님"

_lock = threading.Lock()
_doc: dict = {"key": None, "doc": None, "view": None}


def load_doc(path: str = DATA) -> dict:
    """The committed JSON (cached until the file changes); ``unavailable`` when it is missing or unreadable."""
    try:
        st = os.stat(path)
    except OSError:
        return {"unavailable": True, "label": LABEL, "note": "5년 계산 결과 파일이 아직 없습니다."}
    key = (path, st.st_mtime_ns, st.st_size)
    with _lock:
        if _doc["key"] == key and _doc["doc"] is not None:
            return _doc["doc"]
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {"unavailable": True, "label": LABEL, "note": "5년 계산 결과 파일을 읽지 못했습니다."}
    if not isinstance(doc, dict) or doc.get("version") != 1:
        return {"unavailable": True, "label": LABEL, "note": "5년 계산 결과 파일의 형식이 다릅니다."}
    with _lock:
        _doc.update(key=key, doc=doc, view=None)
    return doc


def view(doc: dict) -> dict:
    """The page's first answer: everything but the per-cell monthly curves (the pooled curves stay)."""
    if doc.get("unavailable"):
        return doc
    with _lock:
        if _doc["doc"] is doc and _doc["view"] is not None:
            return _doc["view"]
    cells = []
    for c in doc.get("cells") or []:
        r = {k: {kk: vv for kk, vv in (v or {}).items() if kk != "curve"} for k, v in (c.get("r") or {}).items()}
        cells.append({**c, "r": r})
    out = {**doc, "cells": cells}
    with _lock:
        if _doc["doc"] is doc:
            _doc["view"] = out
    return out


def cell(doc: dict, s: str, tf: str) -> Optional[dict]:
    """One strategy x timeframe with its curves, plus the month labels; None when it is not in the file."""
    for c in doc.get("cells") or []:
        if c.get("s") == s and c.get("tf") == tf:
            return {"label": doc.get("label", LABEL), "months": doc.get("months") or [], **c}
    return None


def register(app, ctx) -> dict:
    path = getattr(ctx, "size5y_json", None) or DATA

    @app.get("/api/v4/size5y")
    def get_size5y():
        """The 5-year loss-size rule study as committed (docs/size5y.md), without the per-cell curves."""
        return view(load_doc(path))

    @app.get("/api/v4/size5y/cell")
    def get_size5y_cell(s: str = "", tf: str = ""):
        """One strategy x timeframe of the study with its monthly equity curves under every rule."""
        if len(s) > 80 or len(tf) > 8:
            raise HTTPException(404, "unknown cell")
        doc = load_doc(path)
        if doc.get("unavailable"):
            return doc
        c = cell(doc, s, tf)
        if c is None:
            raise HTTPException(404, "unknown cell")
        return c

    return {"routes": ["/api/v4/size5y", "/api/v4/size5y/cell"]}
