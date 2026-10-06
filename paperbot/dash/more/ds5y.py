"""딥시크 5년 결과 (ana7b, 순위표 › 딥시크 only: DeepSeek numbers are shown on the DeepSeek group screen, owners' D10 /
D11). Read-only: the 5-year test's own output files, never recomputed here and never written.

    GET /api/v4/ds5y

Source: what ``research/deepseek200/lib_c.py run`` writes (PREREG_DEEPSEEK200.md sections 7, 9, 10) into its out
directory (default research/deepseek200/out; ``PAPERBOT_DS5Y_OUT`` names another one, e.g. a server run's):

- ``results.csv``  one row per configuration = timeframe x definition x exit (X5_TRAIL2, X2_SL15_TP3): 342 rows when
  complete (``config_list``: 39 definitions x 15m-4h + the five session definitions x 15m-1h = 171, x 2 exits). Per
  period (``is`` 1기 2021-08..2024-06 고르기, ``cf`` 2기 2024-07..2026-09 확인, ``pre`` 3기 2020-01..2021-07 최종):
  n, win_pct, mean_pct (net per trade, price %, no leverage, after costs), sum_pct, gross_mean_pct (before fee and
  funding; lib_c's fills already pay the slippage), cost_mean_pct, coin_mdd_pct (median over coins of the drawdown of
  the compounded per-trade results, no leverage), own_final_x (the owners' 20x / 20% one-position account's final
  multiple); and the gauntlet flags (stage1, stage1_top, stage2, stage3, bh12, candidate, all3_positive).
- ``summary.json`` the gauntlet counts; ``run.log`` / ``progress.log`` (optional): the job's printed lines
  "<tf>: <n> trades, <k> configs so far, <s>s" while ``results.csv`` is not there yet.

``state``: "done" (all 342 rows), "partial" (a results.csv with fewer rows: N/342), "running" (no results.csv, a log
says k/342), "absent" (nothing yet: the page says what will appear). Research exits are NOT the live ones (the live
DeepSeek accounts trade the house exits: 2 ATR stop + the profit-lock ladder at the 'normal' leverage); the page
says so. A coin flip with the same exits loses about the costs per trade (its result before costs is about zero), so
``gross`` is the comparison with coin flips; the live coin-flip accounts sit next to it on the page (from the board).
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(ROOT, "research", "deepseek200", "out")
LOGS = ("run.log", "progress.log")
TOTAL = 342
PERIODS = (("is", "1기", "고르기", "2021-08-01", "2024-06-30"),
           ("cf", "2기", "확인", "2024-07-01", "2026-09-29"),
           ("pre", "3기", "최종", "2020-01-01", "2021-07-31"))
COLS = ("n", "win_pct", "mean_pct", "sum_pct", "gross_mean_pct", "cost_mean_pct", "coin_mdd_pct", "own_final_x")
DEC = (0, 2, 4, 2, 4, 4, 2, 4)            # decimals per column (a busted account's tiny own_final_x is kept, 3 digits)
EXITS = (("X5_TRAIL2", "추적 손절", "2 ATR 손절 + 고점에서 2 ATR 되돌리면 청산, 최대 48봉 (라이브 청산에 가장 가까운 연구 청산)"),
         ("X2_SL15_TP3", "1.5 / 3 ATR", "1.5 ATR 손절 · 3 ATR 익절, 최대 48봉"))
STAGES = ("stage1", "stage1_top", "stage2", "stage3", "bh12", "candidate", "weak_candidate", "all3_positive")
PROGRESS_RE = re.compile(r"(\d+)\s+configs so far")
LABEL = "설명용, 판정 아님"
NOTE_KO = ("5년 시험(사전 등록 PREREG_DEEPSEEK200.md)의 결과 파일을 그대로 읽습니다. 연구 청산은 ATR 두 가지(추적 손절, "
           "1.5/3 ATR)이고, 지금 딥시크 모의 계좌는 하우스 청산(2 ATR 손절 + 계단 잠금, 늘 '보통' 레버리지)이라 같은 신호라도 "
           "숫자가 다릅니다. 거래당 손익은 레버리지 없이 진입가 대비 %, 수수료·슬리피지·펀딩을 뺀 뒤입니다")
COIN_KO = ("동전 던지기와 견주기: 같은 청산으로 아무 때나 들어가면(동전) 비용 전 손익은 평균 0 근처, 정확히는 체결 미끄러짐만큼 "
           "아래(거래당 약 −0.04%)이고 나머지 비용만큼 더 잃습니다. 그래서 '비용 전' 칸이 0 위면 동전보다 나은 진입, −0.04% "
           "근처면 동전과 비슷한 진입입니다. 이 칸은 수수료·펀딩을 빼기 전이고, 미끄러짐(양쪽 0.02%)은 체결가에 이미 들어 있습니다. "
           "계산으로 정한 기준이지 동전 봇을 5년 돌린 숫자는 아닙니다")
ABSENT_KO = "서버가 5년 결과를 아직 쓰지 않았습니다 (계산 중이거나 아직 시작 안 함). 다 되면 여기에 나오는 것:"
RUNNING_KO = ("서버가 5년 결과를 계산하는 중입니다 (15분·30분·1시간·4시간 중 한 봉 종류가 끝날 때마다 숫자가 오르고, 결과 파일은 342개가 다 끝난 뒤 한 번에 "
              "씁니다). 다 되면 여기에 나오는 것:")
PARTIAL_KO = "계산이 아직 끝나지 않았습니다. 아래 목록은 끝난 설정만 셉니다 (342개가 다 차면 관문 결과도 나옵니다)"


def out_dir() -> str:
    return os.environ.get("PAPERBOT_DS5Y_OUT") or OUT_DIR


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x: Optional[float], n: int = 4):
    if x is None:
        return None
    if n and 0 < abs(x) < 10 ** -n:
        return float(f"{x:.3g}")             # own_final_x of a busted account: 6e-18, kept as a tiny number
    v = round(x, n)
    return int(v) if n == 0 else v


def _bool(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "1.0")


def expected() -> list:
    """The 342 configurations (lib_c.config_list, from the live table config.DS200_DEFS): (tf, definition, exit)."""
    from ...config import DS200_DEFS
    return [(tf, d, x) for d, _f, tfs in DS200_DEFS for tf in tfs for x, _k, _n in EXITS]


def _progress(folder: str) -> Optional[int]:
    best = None
    for name in LOGS:
        try:
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as fh:
                text = fh.read()[-20000:]
        except OSError:
            continue
        for m in PROGRESS_RE.finditer(text):
            best = max(best or 0, int(m.group(1)))
    return best


_CACHE: dict = {}


def view(folder: Optional[str] = None) -> dict:
    folder = folder or out_dir()
    path = os.path.join(folder, "results.csv")
    base = {"label": LABEL, "total": TOTAL, "note": NOTE_KO, "coin_ko": COIN_KO,
            "source": os.path.relpath(path, ROOT) if path.startswith(ROOT) else path,
            "periods": [{"key": k, "ko": ko, "role": role, "start": a, "end": b} for k, ko, role, a, b in PERIODS],
            "exits": [{"id": x, "ko": ko, "d": d} for x, ko, d in EXITS], "cols": list(COLS)}
    try:
        st = os.stat(path)
    except OSError:
        k = _progress(folder)
        return {**base, "state": "running" if k is not None else "absent", "done": min(k or 0, TOTAL),
                "absent_ko": RUNNING_KO if k is not None else ABSENT_KO}
    stamp = (path, st.st_mtime_ns, st.st_size)
    hit = _CACHE.get("v")
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, ValueError, csv.Error) as exc:
        return {**base, "state": "absent", "done": 0, "absent_ko": ABSENT_KO,
                "error": f"결과 파일을 읽지 못함: {type(exc).__name__}"}
    want = expected()
    wantset = set(want)
    order = {d: i for i, (_t, d, _x) in enumerate(want)}
    from ...config import DS200_FAMILY
    from ...groups import DS_FAMILY_KO
    defs: dict = {}
    seen = set()
    for r in rows:
        key = (r.get("tf"), r.get("entry"), r.get("exit"))
        if key not in wantset or key in seen:
            continue
        seen.add(key)
        tf, d, x = key
        cfg = {"p": {k: [_r(_num(r.get(f"{k}_{c}")), dec) for c, dec in zip(COLS, DEC)] for k, *_rest in PERIODS},
               "flags": [s for s in STAGES if _bool(r.get(s))], "max_lev": _num(r.get("max_lev"))}
        fam = DS200_FAMILY.get(d) or r.get("family")
        e = defs.setdefault(d, {"id": d, "family": fam, "family_ko": DS_FAMILY_KO.get(fam, fam), "cfg": {}})
        e["cfg"][f"{tf}|{x}"] = cfg
    for d in defs.values():
        d["tfs"] = sorted({k.split("|")[0] for k in d["cfg"]}, key=("15m", "30m", "1h", "4h").index)
    done = len(seen)
    summary = {}
    try:
        with open(os.path.join(folder, "summary.json"), encoding="utf-8") as fh:
            sj = json.load(fh)
        summary = {k: sj.get(k) for k in ("configs", "stage1", "stage1_top", "stage2", "stage3", "bh12_all",
                                         "candidate", "weak_candidate", "candidate_20x", "all_three_periods_positive")
                   if k in sj}
    except (OSError, ValueError, AttributeError):
        summary = {}
    out = {**base, "state": "done" if done >= TOTAL else "partial", "done": done, "file_ts": int(st.st_mtime * 1000),
           "summary": summary, "defs": sorted(defs.values(), key=lambda e: order.get(e["id"], 999))}
    if done < TOTAL:
        out["absent_ko"] = PARTIAL_KO
    _CACHE["v"] = (stamp, out)
    return out


def register(app, ctx) -> dict:
    @app.get("/api/v4/ds5y")
    def get_ds5y():
        """딥시크 5년 결과 (the 5-year test's own files; cached by the file's time and size)."""
        return view()

    return {"routes": ["/api/v4/ds5y"]}
