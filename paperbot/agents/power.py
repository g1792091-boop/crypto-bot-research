"""The checkpoint's statistical power for the staff (owners approved 2026-10-04; paper v4 2026-10-05): reads the
committed result of research/power/power.py (``research/power/out/power.json``, version 2: if an account had a true
edge of +X net ROE per trade, how likely would it pass the day-30 / 60 / 90 checkpoint under the run's verdict rule).
Paper v4 (owners' D5 (b)): the 36 are judged in the core family (108 accounts, FDR 7%) with 10,000 coin-flip bots;
the 5m reel alone (FDR 0.5%) with its own exits. The JSON also holds the rejected one-family scheme (241 accounts at
10%) for comparison. Read-only; the numbers are code's (a Monte Carlo with stated assumptions), not a verdict. Shown in
the 30-day checkpoint meeting and the Saturday learning meeting.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from ..config import V3_Q1_MAIN_FAMILY

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POWER_JSON = os.path.join(ROOT, "research", "power", "out", "power.json")
FAMILY = V3_Q1_MAIN_FAMILY          # 108: the core family (36 strategies x 15m / 30m / 1h; 4h observation only)
SCHEME = "split"                    # the owners' choice D5 (b): research/power/power.py SCHEMES
NO_5M_KO = ("5분봉: 매매법 36개는 2026-10-04부터 5분봉 없음 (5년 자료 거래당 −2.3%, 36칸 중 34칸 유의한 손실). "
            f"v4의 판정 5분 계좌는 5분 단타(릴스) 1개뿐: 자기 청산 규칙, 혼자 FDR 0.5%. 매매법 판정 묶음은 {FAMILY}개, FDR 7%")


def load(path: str = POWER_JSON) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("version") == 2 else None


def deepseek_line_ko() -> str:
    """A7: the DeepSeek family has no power table (power.json has the core schemes and the reel only); one fixed line
    with its numbers (the checkpoint's FDR and the judged count), so '0 passes' there is not over-read."""
    try:
        from ..checkpoint import FAMILY_ALPHA, N_BOTS
        from ..config import V4_GROUP_JUDGED
        a, n = float(FAMILY_ALPHA["ds200"]), int(V4_GROUP_JUDGED["ds200"])
        p_min = 1 / (N_BOTS + 1)
        return (f"딥시크: 판정 {n}개 · FDR {a * 100:g}% · 한 계좌 통과에 p ≤ {a / n:.1e} (가장 작은 p {p_min:.1e}) · "
                "검정력 표 없음: 딥시크 '합격 0개'는 엣지가 없다는 증거가 아님")
    except (ImportError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return "딥시크: 검정력 표 없음"


def brief(path: str = POWER_JSON, family: int = FAMILY, scheme: str = SCHEME) -> dict:
    """Compact: the code-written lines ('진짜 엣지가 거래당 +X%라면 30일에 합격할 확률 Y%'), and per timeframe and
    edge [edge, P(1st pass at day 30), P(1st pass by day 60), P(2nd pass by day 60)] under the run's scheme, with the
    trades a month and the coin flips' mean net ROE per trade. A result without the scheme's rows is an error (never
    a table of None)."""
    doc = load(path)
    if doc is None:
        return {"error": "검정력 결과 파일 없음 (research/power/out/power.json)"}
    key = f"scheme_{scheme}"
    table, info = {}, {}
    for tf, v in (doc.get("results") or {}).items():
        p = v.get("pool") or {}
        info[tf] = {"trades_per_30d": p.get("trades_per_30d"), "coin_flip_mean_roe": p.get("coin_flip_mean_roe")}
        if v.get("observation_only"):
            info[tf]["observation_only"] = True
        if p.get("too_few"):
            info[tf]["too_few"] = True
        if v.get("exits") == "reel":
            info[tf]["reel"] = True
        rows = []
        for r in v.get("rows") or []:
            if key not in r:
                return {"error": f"검정력 결과에 '{scheme}' 방식 행이 없음 ({tf}): research/power/power.py run 다시 실행"}
            f = r[key]
            rows.append([r.get("edge_roe"), f.get("p_pass1_d30"), f.get("p_pass1_by_d60"), f.get("p_pass2_by_d60")])
        if rows:
            table[tf] = rows
    sc = (doc.get("schemes") or {}).get(scheme) or {}
    return {"lines_ko": doc.get("summary_ko") or [], "family": family, "scheme": scheme,
            "alpha": sc.get("alpha"), "n_bots": sc.get("n_bots"), "table": table, "timeframes": info,
            "no_5m": NO_5M_KO, "deepseek": deepseek_line_ko(),
            "columns": ["edge_roe(거래당 순 ROE에 더한 엣지, 0.01 = +1%)", "30일 1차 합격 확률", "60일까지 1차 합격 확률",
                        "60일까지 2차 통과 확률"],
            "generated": doc.get("generated"), "source": "research/power/power.py (out/power.json)",
            "note": ("코드 계산(몬테카를로, 가정 포함: 거래는 서로 독립, 엣지는 모든 거래에 같음, 다른 계좌는 엣지 없음, 동전 봇 거래 "
                     "모양은 2020-21 자료). 판정 규칙(동전 봇 10,000개, 매매법 묶음 FDR 7%·딥시크 2.5%·5분 단타 0.5%)이 "
                     "얼마나 엄격한지 보여 줄 뿐 판정이 아님. '합격 0개'가 '엣지 없음'의 증거가 되려면 이 확률이 높아야 함")}
