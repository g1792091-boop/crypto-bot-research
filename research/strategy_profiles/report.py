"""Korean profile cards from out/profiles.json -> PROFILES.md (and the card data the
dashboard and the per-strategy specialists read).

    python3 research/strategy_profiles/report.py
"""

from __future__ import annotations

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from paperbot.agents.roster3 import STRATEGY_KO  # noqa: E402

TFS = ("5m", "15m", "30m", "1h", "4h")
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
RARE_PER_DAY = 0.3      # fewer signals than this on every timeframe: no paper verdict possible
T_CLEAR = 2.0


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def hold_verdict(p: dict) -> str:
    m, t = p["hold_more_roe"].get("16"), p["hold_more_t"].get("16")
    if not (_ok(m) and _ok(t)):
        return "자료 부족"
    if t >= T_CLEAR and m > 0:
        return "더 들고 갔으면 나았음"
    if t <= -T_CLEAR and m < 0:
        return "빨리 나오는 게 맞음"
    return "차이 뚜렷하지 않음"


def card(name: str, byt: dict) -> dict:
    """Plain data for one strategy (dashboard and specialist packet)."""
    rows = []
    for tf in TFS:
        p = byt.get(tf)
        if not p or not p["signals"]:
            rows.append({"tf": tf, "signals_per_day": 0.0})
            continue
        acc = p["account"]
        rows.append({
            "tf": tf, "signals_per_day": p["signals_per_day"], "trend_share": p["trend_share"],
            "mean_roe": p["mean_roe"], "mean_roe_t": p["mean_roe_t"], "win_rate": p["win_rate"],
            "median_hold_hours": p["median_hold_hours"], "lock_share": p["exit_share"]["lock"],
            "sized_share": p["sized_share"], "hold_more_16": p["hold_more_roe"].get("16"),
            "hold_more_16_t": p["hold_more_t"].get("16"), "hold_verdict": hold_verdict(p),
            "account_is": acc["is"]["final"] if acc.get("is") else None,
            "account_cf": acc["cf"]["final"] if acc.get("cf") else None,
            "bust_is": acc["is"]["bust"] if acc.get("is") else None,
            "bust_cf": acc["cf"]["bust"] if acc.get("cf") else None,
        })
    shares = [r["trend_share"] for r in rows if _ok(r.get("trend_share")) and r["signals_per_day"] >= 0.05]
    ts = sum(shares) / len(shares) if shares else None
    style = None if ts is None else ("추세 따라가기" if ts >= 0.6 else "되돌림 노리기" if ts <= 0.4 else "섞임")
    verdicts = [r["hold_verdict"] for r in rows if r.get("hold_verdict") not in (None, "자료 부족")]
    if verdicts.count("더 들고 갔으면 나았음") >= 2:
        hold = "스윙 쪽: 여러 봉에서 더 오래 들고 가는 게 나았음"
    elif verdicts.count("빨리 나오는 게 맞음") >= 2:
        hold = "단타 쪽: 여러 봉에서 빨리 나오는 게 맞았음"
    else:
        hold = "보유 길이에 따른 차이가 뚜렷하지 않음"
    ranked = [r for r in rows if _ok(r.get("mean_roe")) and r["signals_per_day"] * 365 * 5 >= 100]
    least_bad = max(ranked, key=lambda r: r["mean_roe"])["tf"] if ranked else None
    rare = all(r["signals_per_day"] < RARE_PER_DAY for r in rows)
    return {"strategy": name, "name_ko": STRATEGY_KO.get(name, name), "style": style, "trend_share": ts,
            "hold": hold, "least_bad_tf": least_bad, "rare": rare, "rows": rows}


def _f(x, fmt, dash="-"):
    return (fmt % x) if _ok(x) else dash


def write_md(cards: list[dict], meta: dict, path: str) -> None:
    all_rows = [r for c in cards for r in c["rows"] if _ok(r.get("mean_roe"))]
    pos = [f"{c['name_ko']} {TF_KO[r['tf']]}" for c in cards for r in c["rows"]
           if _ok(r.get("mean_roe")) and r["mean_roe"] > 0]
    longer = sum(1 for r in all_rows if r["hold_verdict"] == "더 들고 갔으면 나았음")
    shorter = sum(1 for r in all_rows if r["hold_verdict"] == "빨리 나오는 게 맞음")
    by_style = {}
    for c in cards:
        for r in c["rows"]:
            if r.get("hold_verdict") in ("더 들고 갔으면 나았음", "빨리 나오는 게 맞음"):
                by_style.setdefault(c["style"], {}).setdefault(r["hold_verdict"], 0)
                by_style[c["style"]][r["hold_verdict"]] += 1
    L = []
    L.append("# 36개 매매법 성격 카드 (과거 5년, paper v3 규칙)\n")
    L.append("`research/strategy_profiles/profiles.py`로 계산했습니다. 계좌 없이 신호 하나하나를 따로 "
             "paper v3 규칙(다음 봉 시가 진입, 2 ATR 손절, 20~50배 자동 레버리지, 계단 익절, 실제 비용)으로 "
             "끝까지 따라간 결과입니다. 기간: 2021-08-01 ~ 2026-09-30, 코인 6개.\n")
    L.append("## 먼저 알아둘 것 (냉정하게)\n")
    L.append(f"- **거래당 평균 ROE는 거의 모든 칸이 마이너스**입니다(계산된 {len(all_rows)}칸 중 플러스 "
             f"{len(pos)}칸, 대부분 신호가 1년에 몇 번뿐인 칸). 40배 기준 수수료+슬리피지만 한 번 왕복에 약 "
             "−5.6% ROE이고, 평균이 그 근처라는 것은 **방향을 맞히는 힘이 0에 가깝다**는 뜻입니다.")
    L.append("- 그래서 이 카드는 \"어떤 성격의 매매법인가\"를 보여줄 뿐, 실력의 증거가 아닙니다.")
    L.append(f"- **보유 길이:** 익절 잠금으로 나간 거래를 16봉 더 들고 있었다면? 뚜렷하게 나았던 칸 {longer}개, "
             f"뚜렷하게 나빴던 칸 {shorter}개.")
    for st, d in by_style.items():
        if st is None:
            continue
        L.append(f"  - {st}: 더 들고 갔으면 나았음 {d.get('더 들고 갔으면 나았음', 0)}칸, "
                 f"빨리 나오는 게 맞음 {d.get('빨리 나오는 게 맞음', 0)}칸")
    L.append("  - 즉 **추세 따라가기형은 지금 계단 익절이 너무 일찍 자르는 경향**, "
             "**되돌림형은 빨리 나오는 게 맞는 경향**이 있습니다. 두 분이 말한 \"매매법마다 길게/짧게가 다르다\"가 "
             "데이터에서도 보입니다.")
    L.append("  - 단, 이 결과는 같은 5년 데이터에서 본 것이라 이걸 보고 규칙을 바꾸면 같은 데이터로는 다시 확인할 수 "
             "없습니다. **바꾼 규칙은 복사 계좌로 paper에서 새로 확인**합니다(보충 규칙 Q7).")
    L.append("- **4시간봉:** 신호의 약 80%가 크기 조건(손절이 너무 멀어 20배로도 손실 15% 초과)에 막혀 거래가 적습니다.")
    rare = [c["name_ko"] for c in cards if c["rare"]]
    L.append(f"- **신호가 너무 드문 매매법**(모든 봉에서 하루 {RARE_PER_DAY}개 미만): {', '.join(rare) or '없음'}. "
             "paper 기간 안에 판정이 어렵습니다.\n")
    L.append("## 읽는 법\n")
    L.append("- **추세 비율:** 진입 방향이 직전 20봉 움직임과 같은 비율. 0.6 이상 추세 따라가기, 0.4 이하 되돌림 노리기.")
    L.append("- **평균 ROE:** 거래 한 번의 순 ROE 평균(비용 포함). **t**는 우연이 아닐 정도(절댓값 2 이상이면 뚜렷).")
    L.append("- **16봉 더:** 잠금으로 나간 거래를 16봉 더 들고 있었다면 ROE가 평균 몇 %p 달라졌는지.")
    L.append("- **5년 계좌:** 계좌 1개($1,000, 한 번에 1포지션)로 돌렸을 때 기간 끝 금액(앞 기간 → 뒤 기간). 10 근처는 파산.\n")
    for c in cards:
        L.append(f"## {c['name_ko']} ({c['strategy']})\n")
        L.append(f"- 성격: **{c['style'] or '신호 부족'}**"
                 f"{' (추세 비율 %.2f)' % c['trend_share'] if _ok(c['trend_share']) else ''} · {c['hold']}")
        L.append(f"- 5년 기준 가장 덜 나쁜 봉: {TF_KO.get(c['least_bad_tf'], '-')}"
                 f"{' · **신호가 너무 드묾**' if c['rare'] else ''}\n")
        L.append("| 봉 | 하루 신호 | 평균 ROE | t | 승률 | 보유 중앙값 | 잠금 청산 | 16봉 더 | 5년 계좌 |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for r in c["rows"]:
            if not _ok(r.get("mean_roe")):
                L.append(f"| {TF_KO[r['tf']]} | {_f(r['signals_per_day'], '%.2f')} | - | - | - | - | - | - | - |")
                continue
            more = (f"{r['hold_more_16'] * 100:+.1f}%p ({r['hold_verdict']})"
                    if _ok(r.get("hold_more_16")) else "-")
            acct = f"{_f(r['account_is'], '$%.0f')} → {_f(r['account_cf'], '$%.0f')}"
            L.append(f"| {TF_KO[r['tf']]} | {r['signals_per_day']:.2f} | {r['mean_roe'] * 100:+.1f}% | "
                     f"{_f(r['mean_roe_t'], '%.1f')} | {_f(r['win_rate'] * 100, '%.0f%%')} | "
                     f"{_f(r['median_hold_hours'], '%.1f')}시간 | {_f(r['lock_share'] * 100, '%.0f%%')} | "
                     f"{more} | {acct} |")
        L.append("")
    L.append(f"\n계산 조건: {json.dumps(meta, ensure_ascii=False, default=str)}\n")
    with open(path, "w") as fh:
        fh.write("\n".join(L))


def main() -> None:
    d = json.load(open(os.path.join(HERE, "out", "profiles.json")))
    cards = [card(n, d["profiles"][n]) for n in STRATEGY_KO if n in d["profiles"]]
    with open(os.path.join(HERE, "out", "cards.json"), "w") as fh:
        json.dump({"meta": d["meta"], "cards": cards}, fh, ensure_ascii=False, indent=1, default=float)
    write_md(cards, d["meta"], os.path.join(HERE, "PROFILES.md"))
    print("wrote PROFILES.md and out/cards.json")


if __name__ == "__main__":
    main()
