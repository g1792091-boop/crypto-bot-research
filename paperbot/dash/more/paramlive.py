"""커스텀값 실시간 비교 (owners' "2번", 2026-10-10): what the nightly custom-value shadow (paperbot/paramshadow.py) wrote
about the 36 strategies' numbers since the v4 run started. Read-only over that job's own output files; nothing is
recomputed here, no database is opened by this module (the run's start, to hide another run's summary after a reset,
comes through the dashboard's own paper3.db reader) and paramshadow itself is not imported (numpy / pandas / the engine
stay out of the dashboard process).

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

Plain words for the owners (2026-10-10, second round), computed here from the job's own numbers so they are tested in
Python and both screens say the same:
- ``summary_ko`` / ``summary_rule`` on every cell (full and compact): the one-line reading of a strategy x timeframe,
  the first rule that matches (``cell_summary``): too few default trades (thin) > a ★ (star) > no variant changed a
  signal (same) > more than half of the changed variants made more, none beyond the luck line (more) > the rest (less).
- ``candidates`` on the overview: up to CANDIDATES variants closest to the luck line (luck.ratio, the job's own z over
  its Bonferroni z), only those the job could test (not small) and above the default per trade (ratio > 0); ``cells_ready``
  / ``cells_total``: cells whose recomputed default has the job's min_trades (the star floor).

Two-number variants (the job's version 2): a variant row is ``combo`` "single" (one number, x0.5 .. x1.5; param / mult /
value / default as before) or "pair" (two numbers, each x0.75 or x1.25; param / mult / value / default null), and
``parts`` lists its one or two changes {param, mult, value, default}. Here every part gets its ``param_ko``; a row of a
version-1 file (no parts) gets the one part its own fields describe, so both file shapes read the same. ``change_ko``
("슈퍼트렌드 배수 6→4.5 + ROC 길이 9→11") names a row's change in summary_ko and on the candidates; the compact cell's
``best`` carries its parts too.
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
OLD_RUN_KO = "새 실행이 시작되어, 다음 10:00 계산부터 새 기록으로 보입니다 (지난 결과는 이전 실행 것)"
ORIGINAL_KINDS = ("strategy", "random", "ds200", "reel")     # paperbot/accounts.py ORIGINAL_KINDS (not imported here)
RUN_TTL_S = 60
BAD_KO = "계산 결과 파일을 읽지 못했습니다 (다음 계산 때 다시 씁니다)"
UNKNOWN_KO = "그런 매매법이 없습니다"
LABEL_KO = "그림자 계좌 · 참고용 (판정 아님)"
ABOUT_KO = ("커스텀값 그림자 = 기존 36개 매매법의 숫자를 하나만(×0.5 · ×0.75 · ×1.25 · ×1.5) 또는 두 개를 함께(각각 ×0.75 · "
            "×1.25) 바꿔 v4 시작부터 다시 계산하는 그림자 계좌입니다. 실제 계좌 · 주문 · 30일 판정과는 상관없습니다.")
SETTING_KEYS = ("version", "initial_equity", "taker_fee", "slippage", "leverage_rule", "stop_atr")
MIN_TRADES = 20                               # paperbot/paramshadow.py MIN_TRADES (not imported); the file's min_trades wins
CANDIDATES = 8                                # 지켜볼 후보 rows on 분석 › 커스텀값 비교
CANDIDATE_KEYS = ("strategy", "name_ko", "tf", "combo", "parts", "change_ko", "param", "param_ko", "default", "value", "mult",
                  "trades", "diff_pnl", "ratio", "star")
PART_KEYS = ("param", "mult", "value", "default")

_CACHE: dict = {}
_LOCK = threading.Lock()
_BAD = object()                               # a file that exists but cannot be read as a JSON object


_RUN: dict = {}


def run_start(data) -> Optional[int]:
    """MIN(created_ts) of the run's original accounts, through the dashboard's own paper3.db reader (``data.conn()``,
    dash.app.Data; read-only like every dashboard query), re-read at most every RUN_TTL_S; None when it cannot be read
    (then the summary is shown as it is)."""
    conn = getattr(data, "conn", None)
    if conn is None:
        return None
    import time
    now = time.monotonic()
    hit = _RUN.get(id(data))
    if hit and now - hit[0] < RUN_TTL_S:
        return hit[1]
    val = None
    try:
        with conn() as c:
            r = c.execute(f"SELECT MIN(created_ts) FROM accounts WHERE kind IN "
                          f"({', '.join('?' * len(ORIGINAL_KINDS))})", ORIGINAL_KINDS).fetchone()
            val = int(r[0]) if r and r[0] is not None else None
    except Exception:  # noqa: BLE001  (a missing or busy database: show the summary as it is)
        val = None
    _RUN[id(data)] = (now, val)
    return val


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


# ------------------------------------------------------------------ plain words (the owners' one line per cell)
def _grouped(x: float, dec: int) -> str:
    """fmt.num of the page: "1,234.5", the true minus sign, no sign for a value that shows as zero."""
    s = f"{abs(x):,.{dec}f}"
    return ("−" if x < 0 and s.strip("0.,") else "") + s


def value_ko(v) -> str:
    """A parameter value as the page's valueKo writes it: 10 → "10", 6.0 → "6", 0.75 → "0.75", [5, 8] → "5·8"."""
    if isinstance(v, (list, tuple)):
        return "·".join(value_ko(x) for x in v)
    if _num(v) is None or not math.isfinite(v):
        return "—" if v is None else str(v)
    d = 0
    while d < 4 and abs(v * 10 ** d - round(v * 10 ** d)) > 1e-9:
        d += 1
    return _grouped(v, d)


def money_ko(x) -> str:
    """Paper money in a sentence: "+$1,234.56" / "−$51.15" / "$0.00"."""
    x = _num(x)
    if x is None or not math.isfinite(x):
        return "—"
    s = f"{abs(x):,.2f}"
    zero = not s.strip("0.,")
    return ("" if zero else "+" if x > 0 else "−") + "$" + s


def variant_row(v: dict, pko: dict) -> dict:
    """A variant row with ``combo`` and ``parts`` (each with its Korean name) whatever the file's version: a version-1
    row (no parts) is the one change its own param / mult / value / default describe."""
    parts = v.get("parts")
    if not isinstance(parts, list) or not parts:
        parts = [{k: v.get(k) for k in PART_KEYS}] if v.get("param") else []
    parts = [{**pt, "param_ko": pko.get(pt.get("param"))} for pt in parts if isinstance(pt, dict)]
    combo = v.get("combo") if v.get("combo") in ("single", "pair") else "pair" if len(parts) > 1 else "single"
    return {**v, "param_ko": pko.get(v.get("param")), "combo": combo, "parts": parts}


def change_ko(row: dict) -> str:
    """What a variant changes, in words: "슈퍼트렌드 배수 6→3", a pair "슈퍼트렌드 배수 6→4.5 + ROC 길이 9→11"."""
    parts = row.get("parts") or ([row] if row.get("param") else [])          # a version-1 row is its own one change
    words = [f"{pt.get('param_ko') or pt.get('param')} {value_ko(pt.get('default'))}→{value_ko(pt.get('value'))}"
             for pt in parts if isinstance(pt, dict) and pt.get("param")]
    return " + ".join(words) or str(row.get("key") or "숫자")


def cell_summary(c: dict, variants: list, min_trades: int = MIN_TRADES) -> tuple[str, str]:
    """(rule, the owners' one line) for one strategy x timeframe; the first rule that matches:
    thin (the recomputed default has fewer than min_trades trades) > star > same (k == 0) > more (better * 2 > k) > less.
    A reference, never a verdict: a ★ is "지켜볼 후보", and changing a number is the owners' call after the 30-day verdict."""
    base = c.get("base") or {}
    n = int(_num(base.get("trades")) or 0)
    if n < min_trades:
        lead = "아직 거래가 없어" if n == 0 else f"아직 거래 {n:,}건뿐이라"
        return "thin", f"{lead} 판단하기 이릅니다 (거래 {min_trades:,}건부터 판단)"
    starred = [v for v in variants if v.get("star")]
    if starred or (_num(c.get("stars")) or 0) > 0:
        tail = "운으로 설명하기 어려운 차이 → 지켜볼 후보 (바꿀지는 30일 판정 뒤 두 분이)"
        if not starred:
            return "star", f"★ 변형 {int(c.get('stars')):,}개: {tail}"
        v = max(starred, key=lambda x: _num(x.get("diff_pnl")) or 0)
        return "star", f"★ {change_ko(v)}: 기본값보다 {money_ko(v.get('diff_pnl'))}, {tail}"
    k, better = int(_num(c.get("k")) or 0), int(_num(c.get("better")) or 0)
    if k == 0:
        return "same", "숫자를 바꿔도 신호가 달라지지 않았습니다"
    if better * 2 > k:
        return "more", f"숫자를 바꾼 {k:,}개 중 {better:,}개가 더 벌었지만 운 기준선을 넘은 것은 없음 → 아직 바꿀 근거 없음"
    return "less", f"숫자를 바꾼 {k:,}개 대부분이 기본값보다 못하거나 비슷함 → 기본값 유지가 무난"


def candidate_rows(strategy: str, name_ko: Optional[str], tf: str, variants: list) -> list[dict]:
    """The variants of one cell that may enter 지켜볼 후보: the job could test them (luck not small, a ratio) and they
    beat the default per trade (ratio > 0); a variant whose signals equal the default's never does."""
    out = []
    for v in variants:
        lk = v.get("luck")
        if v.get("same_as_base") or not isinstance(lk, dict) or lk.get("small"):
            continue
        r = _num(lk.get("ratio"))
        if r is None or not r > 0:
            continue
        out.append({"strategy": strategy, "name_ko": name_ko, "tf": tf, "combo": v.get("combo"),
                    "parts": v.get("parts") or [], "change_ko": change_ko(v), "param": v.get("param"),
                    "param_ko": v.get("param_ko"), "default": v.get("default"), "value": v.get("value"),
                    "mult": v.get("mult"), "trades": v.get("trades"), "diff_pnl": v.get("diff_pnl"), "ratio": r,
                    "star": bool(v.get("star"))})
    return out


# ------------------------------------------------------------------ the summary, prepared once per file
def _prepare(doc: dict) -> dict:
    pko, sko = _param_ko(), _strategy_ko()
    min_trades = int(_num(doc.get("min_trades")) or MIN_TRADES)
    cells = [c for c in (doc.get("cells") or []) if isinstance(c, dict) and c.get("strategy") and c.get("tf")]
    compact, by, cands = [], {}, []
    ready = 0
    for c in cells:
        name = str(c["strategy"])
        base, real, par = c.get("base") or {}, c.get("real") or {}, c.get("parity") or {}
        params = [{**p, "param_ko": pko.get(p.get("name"))} for p in (c.get("params") or []) if isinstance(p, dict)]
        variants = [variant_row(v, pko) for v in (c.get("variants") or []) if isinstance(v, dict)]
        best = c.get("best") if isinstance(c.get("best"), dict) else None
        if best is not None:
            row = next((v for v in variants if v.get("key") == best.get("key")), None) or variant_row(best, pko)
            best = {**best, **{k: row.get(k) for k in ("param", "param_ko", "mult", "value", "combo", "parts")}}
        rule, line = cell_summary(c, variants, min_trades)
        ready += (_num(base.get("trades")) or 0) >= min_trades
        cands += candidate_rows(name, sko.get(name), str(c["tf"]), variants)
        compact.append({
            "strategy": name, "tf": c["tf"], "name_ko": sko.get(name),
            "base": {k: base.get(k) for k in ("trades", "pnl", "win_rate")},
            "real": {k: real.get(k) for k in ("trades", "pnl")},
            "parity": {"share": par.get("share")},
            "k": c.get("k"), "better": c.get("better"), "stars": c.get("stars"), "best": best,
            "summary_ko": line, "summary_rule": rule})
        by.setdefault(name, []).append({**c, "params": params, "variants": variants, "best": best,
                                        "summary_ko": line, "summary_rule": rule})
    # closest to the luck line first; the same ratio: more money over the default first
    cands.sort(key=lambda x: (-x["ratio"], -(_num(x["diff_pnl"]) or 0)))
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
        "multipliers": doc.get("multipliers"), "pair_multipliers": doc.get("pair_multipliers"),
        "min_trades": doc.get("min_trades"), "alpha": doc.get("alpha"),
        "tfs": doc.get("tfs") or list(TFS),
    }
    return {"head": head, "has": bool(cells) and status != "no_run", "compact": compact, "by": by,
            "overview": doc.get("overview") if isinstance(doc.get("overview"), dict) else {},
            "notes": [str(n) for n in (doc.get("notes") or [])][-20:], "names": sko,
            "candidates": [{k: x[k] for k in CANDIDATE_KEYS} for x in cands[:CANDIDATES]], "cells_ready": ready}


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


def _base(folder: Optional[str], run: Optional[int] = None):
    """(prepared | None, answer head): the parts both routes share, including the not-available states. ``run``: the
    current run's start; a summary of another run (a reset happened since) is not shown."""
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
    rs = p["head"].get("run_start_ms")
    if run is not None and rs is not None and int(rs) != int(run):
        return None, {**out, "available": False, "status": "old_run", "none_ko": OLD_RUN_KO}
    return p, {**out, **p["head"], "available": True, **err}


# ------------------------------------------------------------------ the answers
def overview(folder: Optional[str] = None, run: Optional[int] = None) -> dict:
    p, out = _base(folder, run)
    if p is None:
        return out
    return {**out, "overview": p["overview"], "notes": p["notes"], "cells": p["compact"],
            "candidates": p["candidates"], "cells_ready": p["cells_ready"], "cells_total": len(p["compact"])}


def strategy_view(strategy: str, folder: Optional[str] = None, run: Optional[int] = None) -> Optional[dict]:
    """One strategy's four cells in full; None (the route's 404) for a name not among the cells of a real summary."""
    p, out = _base(folder, run)
    if p is None:
        return {**out, "strategy": strategy}
    cells = p["by"].get(strategy)
    if cells is None:
        return None
    return {**out, "strategy": strategy, "name_ko": p["names"].get(strategy), "cells": cells}


def register(app, ctx) -> dict:
    data = getattr(ctx, "data", None)

    @app.get("/api/v4/paramlive")
    def get_paramlive():
        """커스텀값 그림자: the 36 x 4 grid (compact cells), status and texts (read-only files, mtime cache)."""
        return overview(run=run_start(data))

    @app.get("/api/v4/paramlive/{strategy}")
    def get_paramlive_strategy(strategy: str):
        """커스텀값 그림자: one strategy's four timeframes with every one-number variant (read-only files)."""
        out = strategy_view(strategy, run=run_start(data))
        if out is None:
            raise HTTPException(404, UNKNOWN_KO)
        return out

    return {"routes": ["/api/v4/paramlive", "/api/v4/paramlive/{strategy}"], "overview": overview,
            "strategy": strategy_view}
