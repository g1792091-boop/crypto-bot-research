"""The five-year leverage and stop-width comparison for the staff (research/levstop, pre-registered in
research/levstop/PREREG_LEVSTOP.md): reads the committed result ``research/levstop/out/levstop.json`` and gives the
Friday 낙폭·파산 위험 회의 (risk_review) a compact ``levstop_5y`` (under 4 KB). Read-only; the numbers are code's
(per-signal outcomes of the 5-year cards' machinery, a week-block bootstrap vs zero, one account per period for the
busts), descriptive, not a verdict, and they change nothing in the 30-day run.
"""

from __future__ import annotations

import json
import os
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEVSTOP_JSON = os.path.join(ROOT, "research", "levstop", "out", "levstop.json")
MAX_BYTES = 4000
COLUMNS = ["sig_pos_bh(보정 뒤 유의하게 플러스 칸)", "sig_neg_bh(유의하게 마이너스 칸)", "cells_mean_positive(평균 플러스 칸)",
           "cells", "pooled_mean_eq(모든 거래의 거래당 자금 대비 평균)", "busts(파산 계좌)", "accounts",
           "rules_ok_share(지금 크기 조건이면 들어갈 수 있던 비율, 고정 배수만)"]
NOTE = ("5년(2021-08~2026-09) 코드 계산, 설명용·판정 아님. 칸 = 매매법 × 시간봉(180). 고정 배수는 모든 신호가 그 배수로 "
        "들어감(15% 상한·청산가 여유 없이, 청산은 적용). 평균은 신호마다 따로(5년 카드와 같음), 유의성은 주 단위 블록 "
        "부트스트랩으로 0과 비교, 180칸 BH 10% 보정. 파산은 기간마다 $5,000 계좌(한 번에 한 포지션, $10 아래). "
        "30일 규칙은 바뀌지 않음: 바꾸려면 실험실 관문·두 분 결정·규칙 버전")

_CACHE: dict = {}


def load(path: str = LEVSTOP_JSON) -> Optional[dict]:
    """The result JSON (cached by path and modification time); None when missing or not version 1."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _CACHE.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    doc = doc if isinstance(doc, dict) and doc.get("version") == 1 else None
    _CACHE[path] = (mtime, doc)
    return doc


def _size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def brief(path: str = LEVSTOP_JSON, max_bytes: int = MAX_BYTES) -> dict:
    """Compact for the packet: per arm ("<leverage>|<stop ATR>", ``tiers`` = the current 50 -> 20x fallback) one
    short row (``COLUMNS``), the code-written lines, and the current rules' row by timeframe. Trimmed (lines, then the
    timeframes) to stay under ``max_bytes`` UTF-8 bytes."""
    doc = load(path)
    if doc is None:
        return {"error": "5년 레버리지·손절 비교 결과 파일 없음 (research/levstop/out/levstop.json)"}
    s = doc.get("summary") or {}
    arms = {}
    for arm, a in (s.get("by_arm") or {}).items():
        pm = a.get("pooled_mean_eq")
        arms[arm] = [a.get("sig_pos_bh"), a.get("sig_neg_bh"), a.get("cells_mean_positive"), a.get("cells"),
                     None if pm is None else round(pm, 5), a.get("busts"), a.get("accounts")]
        if a.get("pooled_rules_ok_share") is not None:
            arms[arm].append(round(a["pooled_rules_ok_share"], 3))
    cur = doc.get("current_arm") or "tiers|2.0"
    tf = {k: [v.get("sig_pos_bh"), v.get("sig_neg_bh"), None if v.get("pooled_mean_eq") is None
              else round(v["pooled_mean_eq"], 5), v.get("busts")]
          for k, v in ((s.get("by_arm_tf") or {}).get(cur) or {}).items()}
    out = {"lines_ko": list(s.get("lines_ko") or []), "current_arm": cur, "columns": COLUMNS, "arms": arms,
           "current_by_tf": tf, "current_by_tf_columns": ["sig_pos_bh", "sig_neg_bh", "pooled_mean_eq", "busts"],
           "grid": doc.get("grid"), "generated": doc.get("generated"),
           "source": "research/levstop (PREREG_LEVSTOP.md, out/levstop.json)", "note": NOTE}
    while _size(out) > max_bytes and len(out["lines_ko"]) > 1:
        out["lines_ko"].pop()
    if _size(out) > max_bytes:
        out.pop("current_by_tf", None)
        out.pop("current_by_tf_columns", None)
    if _size(out) > max_bytes:
        out["columns"] = [c.split("(")[0] for c in COLUMNS]
    return out
