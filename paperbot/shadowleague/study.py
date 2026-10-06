"""The 5-year results the shadow members are shown next to (static: typed in from the committed result documents).

Nothing here is computed or changed by the league. Every number is copied from RESULTS_ZONEFLIP.md (docs/zoneflip-reel/
on the owners' branch claude/keen-pasteur-wav02u; sha256 below), the MAIN rule's tables per timeframe and period.
The pre-registration (PREREG_ZONEFLIP.md, sha256 below) fixed the rules before the data was run; the run was on
2026-10-06 and its verdict is FAIL (실패): 0 of 8 cells passed, every timeframe and period lost money after costs and
the rule was no better than random entry times.

tests/test_shadowleague_view.py re-reads these numbers from the committed result text when it is available and checks
that they are the same.
"""

from __future__ import annotations

PERIOD_KO = {"is": "1기 2021-08 ~ 2024-06", "oos": "2기 2024-07 ~ 2026-09", "pre": "3기 2020-01 ~ 2021-07"}


def _row(trades, win, avg_win, avg_loss, pf, net, gross, pos, of, flip, acct):
    return {"trades": trades, "win_pct": win, "avg_win_pct": avg_win, "avg_loss_pct": avg_loss, "pf": pf,
            "net_pct": net, "gross_pct": gross, "coins_positive": pos, "coins_of": of, "flip_net_pct": flip,
            "account_x": acct}


# MAIN rule (zone held at least 3 times), per timeframe and period. net_pct = after costs, per trade, at 1x;
# gross_pct = before fee, slippage and funding; flip_net_pct = the average of 2,000 random-entry bots with the same
# coin, period, side, stop and target distances; account_x = the owners'-style account's final multiple (1 = even).
STUDIES = {
    "zoneflip": {
        "title_ko": "매물대 지지→저항 전환 5년 시험",
        "verdict": "FAIL",
        "verdict_ko": "실패",
        "one_line_ko": "5년 자료에서 8칸 중 통과 0칸. 4개 봉 모두, 세 기간 모두 비용 뒤 거래당 손실이었고 무작위 시점 진입보다 낫지 않았습니다.",
        "honest_ko": ("라이브는 이 5년 결과와 같은 규칙입니다. 그래서 비용을 못 넘고 손실이 나는 것이 예상입니다. "
                      "이 기록은 라이브가 5년 시험과 같은 모양인지 보고, 앞으로 다른 아이디어를 같은 방식으로 지켜볼 길을 "
                      "닦기 위한 참고용입니다(판정 아님)."),
        "run_date": "2026-10-06",
        "prereg_sha256": "202d638e4a3d72aacc1d8ac601f9372f0ed4fdb5a923c5e8ecabadafaa642c8a",
        "results_sha256": "85d137f404a875b604c9173e470ada5da870798d331f4f575ed72dabdc6ebd7c",
        "code_sha256": "b4a5f6d00ff1d9cb71cf8cd209eb39731603daaaa50827dcc5fdd95a424677f3",
        "where": "docs/zoneflip-reel/RESULTS_ZONEFLIP.md (브랜치 claude/keen-pasteur-wav02u)",
        "cells": 8, "cells_passed": 0, "trades_main": 3173, "trades_ctrl": 6755,
        "periods": PERIOD_KO,
        "main": {
            "15m": {"is": _row(796, 26.6, 1.76, -0.78, 0.82, -0.10, 0.04, 0, 6, -0.15, 0.01),
                    "oos": _row(614, 22.0, 1.60, -0.67, 0.67, -0.17, -0.03, 1, 6, -0.14, 0.01),
                    "pre": _row(345, 27.0, 2.75, -1.06, 0.96, -0.03, 0.11, 3, 6, -0.14, 0.07)},
            "30m": {"is": _row(389, 24.9, 2.08, -1.07, 0.65, -0.28, -0.14, 0, 6, -0.15, 0.01),
                    "oos": _row(294, 24.5, 2.29, -0.89, 0.83, -0.11, 0.03, 3, 6, -0.14, 0.12),
                    "pre": _row(201, 24.4, 4.39, -1.46, 0.97, -0.03, 0.11, 3, 6, -0.16, 0.41)},
            "1h": {"is": _row(180, 24.4, 3.64, -1.66, 0.71, -0.36, -0.21, 2, 6, -0.16, 0.01),
                   "oos": _row(128, 22.7, 3.08, -1.34, 0.67, -0.34, -0.18, 1, 6, -0.13, 0.16),
                   "pre": _row(100, 21.0, 4.78, -1.90, 0.67, -0.50, -0.35, 2, 6, -0.16, 0.07)},
            "4h": {"is": _row(52, 23.1, 9.04, -3.73, 0.73, -0.78, -0.57, 2, 2, -0.18, 0.07),
                   "oos": _row(48, 22.9, 7.09, -2.85, 0.74, -0.57, -0.39, 1, 2, -0.12, 0.12),
                   "pre": _row(26, 3.8, 14.10, -4.61, 0.12, -3.89, -3.69, 0, 0, -0.13, 0.05)},
        },
        # typical stop and target distance of the study's trades (range over the three periods, % of the entry price)
        "distance_pct": {"15m": {"stop": [0.5, 0.8], "target": [2.0, 2.5]}, "30m": {"stop": [0.7, 1.0], "target": [2.3, 3.6]},
                         "1h": {"stop": [1.1, 1.4], "target": [3.9, 4.6]}, "4h": {"stop": [2.5, 2.7], "target": [9.0, 13.0]}},
        # periods 1 + 2 together: the one-sided p that the MAIN average is above zero, and against the random entries
        "p12": {"15m": 1.00, "30m": 1.00, "1h": 0.99, "4h": 0.88},
        "vs_flip": {"15m": {"main_pct": -0.13, "flip_pct": -0.14, "p": 0.35}, "30m": {"main_pct": -0.21, "flip_pct": -0.14, "p": 0.86},
                    "1h": {"main_pct": -0.35, "flip_pct": -0.15, "p": 0.93}, "4h": {"main_pct": -0.68, "flip_pct": -0.15, "p": 0.83}},
        "reading_ko": ["승률은 22~27%이고, 손익비 약 3에서 본전에 필요한 승률(약 25% + 비용)을 넘지 못했습니다.",
                       "15분·30분봉은 비용 전에 거의 0이고 비용만큼 손실입니다. 1시간·4시간봉은 비용 전부터 손실입니다.",
                       "'3번 이상 막힌 구간'이라는 조건을 빼도(대조 설정) 12칸 모두 손실이었고 결과가 거의 같았습니다."],
        "cost_note_ko": "비용 = 수수료 왕복 0.10% + 슬리피지 0.02%(시장가 체결마다) + 펀딩 0.01%/8시간. 거래당 약 0.14%(4시간봉 약 0.21%).",
    }
}


def study(key: str) -> dict | None:
    return STUDIES.get(key)
