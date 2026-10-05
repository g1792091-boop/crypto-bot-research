"""What was already tested for the paper-v4 strategies outside the 36 (G6): the 44 DeepSeek-200 definitions and the
reel. ``paperbot/agents/ds_prior.json`` is built from the committed research outputs ONLY (never recomputed):

    research/deepseek200/out/results.csv      one row per (timeframe, definition, exit): 342 configurations
    research/deepseek200/out/near_miss.csv    the configurations the gauntlet kept longest
    research/deepseek200/out/per_family.csv   the gauntlet counts per family
    research/deepseek200/out/summary.json     the run's totals (candidates) and the code / prereg sha256
    research/reel5m/out/results.csv           the reel grid: 40 configurations (H1 = 5m BB_SMA200_CLOSE_LONG SWING_BAND)
    research/reel5m/out/near_miss.csv         (empty when nothing got near)
    research/reel5m/out/summary.json, h1.json the pre-registered H1 test and its result

``packets3.research_prior`` falls back to this file for a name that the entry study (research_prior.json, the 36) does
not have, so a DeepSeek or reel room's packet says what the five years already said. It is NOT in
``packets3.research_counts`` (the 36 rooms' count of earlier tests stays the entry study's 2,960).

Rebuild after a research output changes: ``python -m paperbot.agents.ds_prior`` (tests check the file equals a fresh
build). Descriptive only: the DeepSeek run found no candidate among 342 configurations, and the reel's H1 failed.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DS_OUT = os.path.join(ROOT, "research", "deepseek200", "out")
REEL_OUT = os.path.join(ROOT, "research", "reel5m", "out")
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ds_prior.json")
PERIODS = ("is", "cf", "pre")
PERIODS_KO = {"is": "1기 2021-08..2024-06 (고르기)", "cf": "2기 2024-07..2026-09 (확인)", "pre": "3기 2020-01..2021-07 (최종)"}
DS_EXITS_KO = {"X5_TRAIL2": "2 ATR 손절 + 2 ATR 추적 손절, 최대 48봉", "X2_SL15_TP3": "1.5 ATR 손절 · 3 ATR 익절, 최대 48봉"}
DS_EXIT_NOTE_KO = ("연구는 ATR 청산 두 가지(X5_TRAIL2, X2_SL15_TP3)로 쟀음. 라이브 딥시크 계좌는 하우스 청산(2 ATR 손절 + 계단식 "
                   "이익 잠금)이라 같은 신호라도 숫자가 다름")
REEL_EXIT_NOTE_KO = "연구와 라이브 계좌가 같은 릴스 자체 청산(손절 = 이탈 뒤 최저가 − 0.05 ATR, 익절 = 직전 봉 윗선, 96봉)"
NOTE = ("already tested, pre-registered, same 5-year data: descriptive, not a rule; testing the same thing again is "
        "not new evidence")


def _read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    return d if isinstance(d, dict) else {}


def _f(x, k: int = 4) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, k) if v == v else None


def _i(x) -> Optional[int]:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _b(x) -> bool:
    return str(x).strip().lower() in ("1", "true", "yes")


def _row(r: dict) -> dict:
    """One configuration in a few numbers: trades and mean net per trade (price %, no leverage) per period, the
    pooled p of periods 1+2, and whether all three periods were positive."""
    out = {"tf": r.get("tf"), "exit": r.get("exit")}
    for k in PERIODS:
        out[f"{k}_n"] = _i(r.get(f"{k}_n"))
        out[f"{k}_mean_pct"] = _f(r.get(f"{k}_mean_pct"))
    out["p12"] = _f(r.get("p12"))
    out["all3_positive"] = all((out[f"{k}_mean_pct"] or 0) > 0 for k in PERIODS)
    return out


def _ds(ds_dir: str) -> tuple[dict, dict]:
    from ..config import DS200_DEFS, DS200_FAMILY
    from ..groups import DS_FAMILY_KO
    rows = _read(os.path.join(ds_dir, "results.csv"))
    near = {(r.get("tf"), r.get("entry"), r.get("exit")) for r in _read(os.path.join(ds_dir, "near_miss.csv"))}
    fam = {r["family"]: r for r in _read(os.path.join(ds_dir, "per_family.csv")) if r.get("family")}
    summ = _json(os.path.join(ds_dir, "summary.json"))
    cand = _i(summ.get("candidate"))
    out = {}
    for d, f, tfs in DS200_DEFS:
        mine = [r for r in rows if r.get("entry") == d]
        if not mine:
            continue
        tests = [_row(r) for r in mine]
        fr = fam.get(f) or {}
        out[d] = {"strategy": d, "group": "ds200", "family": f, "family_ko": DS_FAMILY_KO.get(f),
                  "live_timeframes": list(tfs), "configs": len(tests),
                  # the run found no candidate at all (summary.json): then none of this definition's either
                  "candidates": 0 if cand == 0 else None,
                  "all3_positive": sum(t["all3_positive"] for t in tests),
                  "near_miss": [t for t, r in zip(tests, mine) if (r.get("tf"), r.get("entry"), r.get("exit")) in near],
                  "family_gauntlet": {k: _i(fr.get(k)) for k in ("configs", "stage1", "stage2", "stage3", "candidate",
                                                                    "all3_positive")} if fr else None,
                  "tests": tests, "exits_ko": DS_EXITS_KO, "exit_note_ko": DS_EXIT_NOTE_KO}
        assert DS200_FAMILY.get(d) == f
    totals = {"configs": len(rows), "candidates": cand, "stage1": _i(summ.get("stage1")),
              "stage2": _i(summ.get("stage2")), "stage3": _i(summ.get("stage3")),
              "all3_positive": _i(summ.get("all_three_periods_positive")),
              "code_sha256": (summ.get("code_sha256") or {}).get("lib_c.py"),
              "prereg_sha256": summ.get("prereg_sha256")}
    return out, totals


def _reel(reel_dir: str) -> tuple[dict, dict]:
    from ..config import REEL_NAME, REEL_TF
    rows = _read(os.path.join(reel_dir, "results.csv"))
    near = _read(os.path.join(reel_dir, "near_miss.csv"))
    summ = _json(os.path.join(reel_dir, "summary.json"))
    h1 = _json(os.path.join(reel_dir, "h1.json"))
    if not rows and not h1:
        return {}, {}
    tests = [{**_row(r), "entry": r.get("entry"), "h1": _b(r.get("is_h1"))} for r in rows]
    cand = _i(summ.get("candidate"))
    entry = {"strategy": REEL_NAME, "group": "reel", "live_timeframes": [REEL_TF], "configs": len(tests),
             "candidates": cand,
             "h1": {"config": h1.get("config"), "rule": h1.get("rule"), "pass": h1.get("pass"),
                    "p12": _f(h1.get("p12")), "n12": _i(h1.get("n12")), "mean12_pct": _f(h1.get("mean12_pct")),
                    "pre_mean_pct": _f(h1.get("pre_mean_pct"))} if h1 else None,
             "all3_positive": sum(t["all3_positive"] for t in tests),
             "near_miss": [{"tf": r.get("tf"), "entry": r.get("entry"), "exit": r.get("exit")} for r in near],
             "tests": tests, "exit_note_ko": REEL_EXIT_NOTE_KO}
    totals = {"configs": len(rows), "candidates": cand, "h1_pass": summ.get("h1_pass", h1.get("pass")),
              "code_sha256": (summ.get("code_sha256") or {}).get("lib_reel5m.py"),
              "prereg_sha256": summ.get("prereg_sha256")}
    return {REEL_NAME: entry}, totals


def build(ds_dir: str = DS_OUT, reel_dir: str = REEL_OUT) -> dict:
    """The whole document (deterministic: the same research files give the same JSON)."""
    ds, ds_tot = _ds(ds_dir)
    reel, reel_tot = _reel(reel_dir)
    n_ds, n_reel = ds_tot.get("configs") or 0, reel_tot.get("configs") or 0
    concl = (f"딥시크 200 정의 44개는 5년 같은 자료로 {n_ds}개 설정(정의 × 봉 × 연구 청산 2종)을 이미 사전 등록 시험했고 후보 "
             f"{ds_tot.get('candidates')}개였다(세 기간 모두 플러스 {ds_tot.get('all3_positive')}개는 우연 수준). 릴스 5분 단타는 "
             f"사전 등록한 H1이 {'통과' if reel_tot.get('h1_pass') else '불통과'}였고 격자 {n_reel}개 설정 중 후보 "
             f"{reel_tot.get('candidates')}개였다. 그래서 이 숫자들은 설명 자료이고, 같은 것을 다시 시험해도 새 정보가 아니다. "
             "라이브 계좌가 이 숫자보다 좋아도 30일 판정은 체크포인트가 한다")
    return {"source": ("research/deepseek200/out (results, near_miss, per_family, summary); "
                       "research/reel5m/out (results, near_miss, summary, h1)"),
            "periods_ko": PERIODS_KO, "units_ko": "mean_pct = 거래당 순손익(진입가 대비 가격 %, 레버리지 없음, 연구 비용 뺀 뒤)",
            "totals": {"ds200": ds_tot, "reel": reel_tot}, "conclusion_ko": concl,
            "strategies": {**ds, **reel}}


_DOC: Optional[dict] = None


def doc(path: str = PATH) -> Optional[dict]:
    """The committed file (cached); None when it is missing."""
    global _DOC
    if path != PATH:
        return _json(path) or None
    if _DOC is None and os.path.exists(path):
        _DOC = _json(path)
    return _DOC


def prior(strategy: str, path: str = PATH) -> Optional[dict]:
    """One v4 strategy's entry (a DeepSeek id or the reel) with the conclusion; None for any other name."""
    d = doc(path)
    if not d or strategy not in (d.get("strategies") or {}):
        return None
    return {**d["strategies"][strategy], "conclusion_ko": d.get("conclusion_ko"), "periods_ko": d.get("periods_ko"),
            "units_ko": d.get("units_ko"), "note": NOTE}


def write(path: str = PATH) -> dict:
    d = build()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    return d


if __name__ == "__main__":
    d = write(sys.argv[1] if len(sys.argv) > 1 else PATH)
    print(f"{len(d['strategies'])} strategies, ds200 configs {d['totals']['ds200'].get('configs')}, "
          f"reel configs {d['totals']['reel'].get('configs')}")
