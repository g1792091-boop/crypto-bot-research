#!/usr/bin/env python3
"""Collect the four bots' outputs (v39.py, rangebot.py, trend.py, vwap.py) into research/opentime/results.json and print
the Markdown tables REPORT_KO.md uses (stdout; the report's prose is written by hand around them).

    python3 -I report.py OUT_DIR > tables.md"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import otcommon as CM  # noqa: E402

ARM_SHORT = {"A0": "A0 지금", "A1": "A1 개장 전 정리", "A2": "A2 개장 전 본전", "A3": "A3 4시간 정리", "A4": "A4 8시간 정리",
             "A5": "A5 12시간 정리", "A6": "A6 본전+정리", "A7": "A7 깊은 손실 정리"}


def load(out: str, name: str):
    p = os.path.join(out, name)
    return json.load(open(p)) if os.path.exists(p) else None


def x(v, nd=2):
    return f"×{v:.{nd}f}" if v is not None else "-"


def arms_table(arms: dict, verdicts: dict | None, periods=("choose", "check"), recent="recent") -> str:
    head = ("| 안 | 가운데 달 배수 (고르는 / 확인) | 로그 성장 (고르는 / 확인) | 거래 | 승률 % | 거래당 지갑 % | 플러스 달 | "
            "가장 나쁜 달 | 건드린 포지션 | 10월 | 도움? |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
    rows = []
    for arm, r in arms.items():
        a, b = r[periods[0]], r[periods[1]]
        if arm == "A0":
            v = "기준"
        elif verdicts is None:
            v = "판정 없음"
        else:
            vv = verdicts[arm]
            v = ("**예**" if vv["helps"] else "아니오") + f" ({'이김' if vv['beats_A0_choose'] else '짐'} / " \
                f"{'이김' if vv['beats_A0_check'] else '짐'})"
        rec = r.get(recent)
        rows.append(f"| {ARM_SHORT[arm]} | {x(a['median_month'], 3)} / {x(b['median_month'], 3)} | "
                    f"{a['log_growth']:.1f} / {b['log_growth']:.1f} | {a['trades']} / {b['trades']} | "
                    f"{a['win_pct']:.0f} / {b['win_pct']:.0f} | {a['mean_ret_pct']:+.2f} / {b['mean_ret_pct']:+.2f} | "
                    f"{a['months_up']}/{a['months']} · {b['months_up']}/{b['months']} | "
                    f"{x(a['worst_month'], 3)} / {x(b['worst_month'], 3)} | {a['touched']} / {b['touched']} | "
                    f"{x(rec['median_month'], 2) if rec else '-'} | {v} |")
    return head + "\n".join(rows) + "\n"


def reach_table(diag: dict, periods=("choose", "check")) -> str:
    def f(d):
        if not d or d.get("n", 0) == 0:
            return "0"
        return f"{d['n']} · {d['later_locked_pct']:.0f}% · {d['stopped_pct']:.0f}% · {d['mean_ret_pct']:+.1f}%"
    head = "| 무리 | " + " | ".join({"choose": "고르는 기간", "check": "확인 기간", "all": "창 전체"}.get(p, p) for p in periods) + \
        " |\n|---|" + "---|" * len(periods) + "\n"
    lines = [("모든 포지션", lambda d: d["open_at_M"]["all"]),
             ("개장 5분 전에 아직 열림·잠금 전", lambda d: d["open_at_M"]["flagged"]),
             ("　그중 그때 순ROE > 0", lambda d: d["open_at_M"].get("flagged_in_profit")),
             ("　그중 그때 순ROE ≤ 0", lambda d: d["open_at_M"].get("flagged_in_loss")),
             ("진입 4시간 뒤 아직 열림·잠금 전", lambda d: d["open_4h"]["flagged"]),
             ("진입 8시간 뒤 아직 열림·잠금 전", lambda d: d["open_8h"]["flagged"]),
             ("진입 12시간 뒤 아직 열림·잠금 전", lambda d: d["open_12h"]["flagged"])]
    return head + "\n".join(f"| {nm} | " + " | ".join(f(g(diag[p])) for p in periods) + " |" for nm, g in lines) + "\n"


def loss_table(diag: dict, periods=("choose", "check")) -> str:
    head = "| | " + " | ".join({"choose": "고르는 기간", "check": "확인 기간", "all": "창 전체"}.get(p, p) for p in periods) + \
        " |\n|---|" + "---|" * len(periods) + "\n"
    L = {p: diag[p]["losses"] for p in periods}
    rows = [("손실 거래", lambda d: f"{d['losses']}"),
            ("그중 개장 뒤 90분(09:30~11:00 뉴욕) 안 손절", lambda d: f"{d['stop_in_window']} ({d['stop_in_window_pct']:.1f}%)"),
            ("그 손절들의 손실 몫", lambda d: f"{d['loss_share_in_window_pct']:.1f}%" if d['losses'] else "-"),
            ("포지션을 들고 있던 시간 중 그 90분의 몫", lambda d: f"{d['held_time_in_window_pct']:.1f}%" if d['held_time_in_window_pct'] is not None else "-")]
    return head + "\n".join(f"| {nm} | " + " | ".join(g(L[p]) for p in periods) + " |" for nm, g in rows) + "\n"


SIDE_ROWS = [("R", "R <= -0.5", "진행 R ≤ −0.5"), ("R", "-0.5 < R <= 0", "진행 −0.5 < R ≤ 0"),
             ("R", "0 < R <= 0.25", "진행 0 < R ≤ 0.25"), ("R", "0.25 < R <= 0.5", "진행 0.25 < R ≤ 0.5"),
             ("R", "R > 0.5", "진행 R > 0.5"), ("net_sign", "net ROE > 0", "비용 뺀 순ROE > 0"),
             ("net_sign", "net ROE <= 0", "비용 뺀 순ROE ≤ 0"), ("hours", "< 2h", "보유 2시간 미만"),
             ("hours", "2-6h", "보유 2~6시간"), ("hours", "6-12h", "보유 6~12시간"), ("hours", ">= 12h", "보유 12시간 이상"),
             ("best_share", "< 25%", "최고점이 잠금까지의 25% 미만"), ("best_share", "25-50%", "최고점 25~50%"),
             ("best_share", "50-75%", "최고점 50~75%"), ("best_share", ">= 75%", "최고점 75% 이상")]


def side_table(side: dict, periods=("choose", "check")) -> str:
    def f(d):
        if not d or d.get("n", 0) == 0:
            return "0"
        s = f"{d['n']} · 손절 {d['stopped_pct']:.0f}% · 잠금 {d['later_locked_pct']:.0f}% · {d['mean_ret_pct']:+.1f}%"
        return s + (" (표본 적음)" if d["n"] < CM.SMALL else "")
    head = "| 그때 상태 | " + " | ".join({"choose": "고르는 기간", "check": "확인 기간", "all": "창 전체"}.get(p, p)
                                         for p in periods) + " |\n|---|" + "---|" * len(periods) + "\n"
    rows = ["| 전체 (개장 5분 전 열림·잠금 전) | " + " | ".join(f(side[p]["all_unresolved_at_M"]) for p in periods) + " |"]
    for grp, key, nm in SIDE_ROWS:
        rows.append(f"| {nm} | " + " | ".join(f(side[p][grp].get(key)) for p in periods) + " |")
    return head + "\n".join(rows) + "\n"


def main(argv=None) -> int:
    out = (argv or sys.argv[1:])[0]
    prereg = os.path.join(HERE, "PREREG.md")
    sha = hashlib.sha256(open(prereg, "rb").read()).hexdigest()
    V, R, T, W = (load(out, f) for f in ("v39.json", "range.json", "trend.json", "vwap.json"))
    par = {"v39": load(out, "v39_parity.json"), "range": load(out, "range_parity.json"), "vwap": load(out, "vwap_parity.json")}
    pb = T["modes"]["pullback"]["window_all"]["A0"]
    par["trend"] = {"pullback_A0_window_trades": pb["trades"], "win_pct": pb["win_pct"],
                    "mean_net_roe_pct": pb["mean_ret_pct"] / 0.4, "wallet_1000_to": 1000 * math.exp(pb["log_growth"]),
                    "published_A1": {"trades": 78, "win_pct": 70.5, "mean_net_roe_pct": -3.13, "wallet_1000_to": 234}}
    res = {"prereg_sha256_final": sha, "prereg_sha256_first": "af9a55696965e990f0f327e9d6227d9680cd084615dff04bf3f6133002c8cb61",
           "arms": {k: CM.ARM_KO[k] for k in CM.ARMS}, "periods": CM.PERIODS, "parity": par,
           "v39_toobit": V, "range_woox": R, "trend_bybit": T, "vwap_deepcoin": W}
    json.dump(CM.jsonable(res), open(os.path.join(HERE, "results.json"), "w"), indent=1, ensure_ascii=False)
    print("## V3.9\n")
    print(arms_table(V["arms"], V["verdicts"]))
    print(reach_table(V["diagnostics_A0"]))
    print(loss_table(V["diagnostics_A0"]))
    print(side_table(V["sideways_A0"]))
    print("## RANGE\n")
    print(arms_table(R["arms"], R["verdicts"]))
    print(reach_table(R["diagnostics_A0"]))
    print(loss_table(R["diagnostics_A0"]))
    print(side_table(R["sideways_A0"]))
    for m in ("now", "pullback"):
        print(f"## TREND {m}\n")
        print(arms_table(T["modes"][m]["arms"], None, periods=("check_part (2026-07..09)", "check_part (2026-07..09)"),
                         recent="recent (2026-10, 1-20)"))
        print(reach_table(T["modes"][m]["diagnostics_A0"], periods=("window",)))
        print(loss_table(T["modes"][m]["diagnostics_A0"], periods=("window",)))
        print(side_table(T["modes"][m]["sideways_A0"], periods=("window",)))
    print("## VWAP live\n")
    print(arms_table({k: {p: v[p] for p in CM.PERIODS} for k, v in W["live"].items()}, W["verdicts"]))
    print("copied share %:", {k: round(v["copied_share_pct"], 1) for k, v in W["live"].items()})
    print("## VWAP paper\n")
    print(arms_table(W["paper"], W["verdicts_paper"]))
    print(reach_table(W["diagnostics_A0"]["live"]))
    print(reach_table(W["diagnostics_A0"]["paper"]))
    print(loss_table(W["diagnostics_A0"]["live"]))
    print(loss_table(W["diagnostics_A0"]["paper"]))
    print(side_table(W["sideways_A0"]["live"]))
    print(side_table(W["sideways_A0"]["paper"]))
    print("parity", json.dumps(CM.jsonable(par), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
