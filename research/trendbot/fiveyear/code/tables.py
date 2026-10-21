"""Markdown tables for RESULTS_KO.md from out/results.json (printed; pasted into the report)."""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fycommon import *

R = json.load(open(f"{OUT}/results.json"))
D0 = R["D"]["C0_current"]
KO_EXIT = {"LOCK": "익절", "SL": "손절", "JUDGE": "추세", "REV": "빠른", "TIME": "시간", "LIQ": "강제"}


def usd(g):
    v = 1000 * g
    if v >= 100:
        return f"${v:,.0f}"
    if v >= 1:
        return f"${v:.2f}"
    if v >= 0.01:
        return f"${v:.3f}"
    return f"${v:.1e}"


def p(x, d=1):
    return f"{100 * x:+.{d}f}%"


def exits(b):
    return " · ".join(f"{KO_EXIT.get(k, k)} {v}" for k, v in b["exits"].items())


def band(b):
    g = b["twin_growth_5_50_95"]
    return f"{usd(g[0])} ~ {usd(g[2])} (가운데 {usd(g[1])})"


def year_table(blocks, title):
    print(f"\n| {title} | 진입 | 평일 하루 | 승률 | 평균 순ROE | 비용 전 ROE | 미끄러짐 | 수수료 | 펀딩 | 청산 | $1,000 → | 최악 낙폭 | 동전 쌍둥이 5~95% | 동전보다 나은 비율 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, b in blocks.items():
        if not b.get("entries"):
            continue
        print(f"| {k} | {b['entries']} | {b['per_weekday']:.2f} | {b['win_pct']:.0f}% | {p(b['roe_mean'])} | {p(b['pre_mean'])} | "
              f"{100 * b['slip_mean']:.1f}%p | {100 * b['fee_mean']:.1f}%p | {100 * b['fund_mean']:+.2f}%p | {exits(b)} | "
              f"{usd(b['growth'])} | {100 * b['worst_dd']:.2f}% | {band(b)} | {b['rank_vs_twin_pct']:.0f}% |")


def group_table(blocks, title):
    print(f"\n| {title} | 진입 | 승률 | 평균 순ROE | 비용 전 ROE | 반대쪽 비용 전 | 비용(미끄러짐+수수료) | $1,000 → (5년 복리) | 동전 순ROE 5~95% | 동전보다 나은 비율 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k, b in blocks.items():
        if not b.get("entries"):
            continue
        tm = b["twin_roe_mean_5_50_95"]
        print(f"| {k} | {b['entries']} | {b['win_pct']:.0f}% | {p(b['roe_mean'])} | {p(b['pre_mean'])} | {p(b['pre_mean_other_side'])} | "
              f"{100 * (b['slip_mean'] + b['fee_mean']):.1f}%p | {usd(b['growth'])} | {p(tm[0])} ~ {p(tm[2])} | {b['rank_vs_twin_pct']:.0f}% |")


def matrix(m, n, title):
    ys = [str(y) for y in range(2021, 2027)]
    print(f"\n| {title} | " + " | ".join(ys) + " |")
    print("|---" * (len(ys) + 1) + "|")
    for k in m:
        cells = []
        for y in ys:
            if y in m[k]:
                cells.append(f"{p(m[k][y], 0)} ({n[k][y]})")
            else:
                cells.append("-")
        print(f"| {k} | " + " | ".join(cells) + " |")


print("## D0 연도별")
year_table(D0["years"], "연도")
year_table({"전체 2021-01~2026-09": D0["all"]}, "기간")
print("\n## D0 반기별")
year_table(D0["halves"], "반기")
print("\n## D0 코인별")
group_table(D0["coins"], "코인")
print("\n## D0 매매법별")
group_table(D0["members"], "매매법")
matrix(D0["coin_year_roe_mean"], D0["coin_year_n"], "코인 (평균 순ROE, 진입 수)")
matrix(D0["member_year_roe_mean"], D0["member_year_n"], "매매법 (평균 순ROE, 진입 수)")

print("\n## 지갑 (분기 말, $1,000에서 시작해 계속 복리)")
q = D0["wallet_quarter_end_usd"]
print("| 분기 말 | " + " | ".join(k[:7] for k in q) + " |")
print("|---" * (len(q) + 1) + "|")
print("| 지갑 | " + " | ".join(usd(v / 1000) for v in q.values()) + " |")
print(f"\n$10 아래로 처음: {D0['wallet_below_10usd_first']}, 최저 {usd(D0['wallet_min_usd'] / 1000)}, 끝 {usd(D0['wallet_end_usd'] / 1000)}")
print("보유 시간(분, 가운데):", D0["hold_min_median"], D0["hold_min_by_reason_median"])
print("잠금 도달:", D0["lock_reached"])

print("\n## 그림자 / 메이커 / 수수료 (5년 전체, 연도별 $1,000 →)")
names = {"C0_current": "지금 규칙(D0)", "D1_time4": "D1 시간 정리 4봉", "D2_immediate": "D2 바로 진입(되돌림 없음)",
         "D3_vote4": "D3 판단 4/4", "D4_maker": "D4 메이커 진입", "S_taker0044_bybit": "수수료 0.044%(바이비트)",
         "S_taker0042_woo": "수수료 0.042%(WOO X Pro)"}
ys = [str(y) for y in range(2021, 2027)]
print("\n| 규칙 | 진입 | 평일 하루 | 승률 | 평균 순ROE | 비용 전 ROE | 미끄러짐+수수료 | 청산 | 5년 log 성장 | 동전 5~95% (log) | 동전보다 나은 비율 | " + " | ".join(ys) + " |")
print("|---" * (11 + len(ys)) + "|")
for k, nm in names.items():
    d = R["D"][k]
    b = d["all"]
    tl = b["twin_log_growth_5_50_95"]
    yy = [usd(d["years"][y]["growth"]) + f" ({d['years'][y]['rank_vs_twin_pct']:.0f}%)" if d["years"][y].get("entries") else "-" for y in ys]
    print(f"| {nm} | {b['entries']} | {b['per_weekday']:.2f} | {b['win_pct']:.0f}% | {p(b['roe_mean'])} | {p(b['pre_mean'])} | "
          f"{100 * (b['slip_mean'] + b['fee_mean']):.1f}%p | {exits(b)} | {b['log_growth']:.1f} | {tl[0]:.1f} ~ {tl[2]:.1f} | "
          f"{b['rank_vs_twin_pct']:.0f}% | " + " | ".join(yy) + " |")

print("\n## C (선택 구간 2021-01~2024-12)")
CN = {"C0_current": "C0 지금(40/30배, -50%, 10% 첫 잠금)", "C1_lev20": "C1 20배", "C2_lev10": "C2 10배",
      "C3_lock20": "C3 첫 잠금 +20%", "C4_lock30": "C4 첫 잠금 +30%", "C5_stop35": "C5 손절 -35%",
      "C6_lev20_lock20": "C6 20배 + 첫 잠금 +20%", "C7_lev20_lock20_stop35": "C7 20배 + +20% + -35%"}
print("\n| 변형 | 진입 | 승률 | 평균 순ROE | 비용 전 ROE | 미끄러짐+수수료 | 청산 | log 성장 (선택 기준) | $1,000 → | 동전 5~95% (log) | 동전보다 나은 비율 |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for k, nm in CN.items():
    b = R["C"]["variants"][k]["selection_2021_2024"]
    tl = b["twin_log_growth_5_50_95"]
    sel = " **← 선택**" if k == R["C"]["selected"] else ""
    print(f"| {nm}{sel} | {b['entries']} | {b['win_pct']:.0f}% | {p(b['roe_mean'])} | {p(b['pre_mean'])} | "
          f"{100 * (b['slip_mean'] + b['fee_mean']):.1f}%p | {exits(b)} | {b['log_growth']:.2f} | {usd(b['growth'])} | "
          f"{tl[0]:.1f} ~ {tl[2]:.1f} | {b['rank_vs_twin_pct']:.0f}% |")
print("\n## C 확인 구간 2025-01~2026-09 (선택된 것 + 지금 규칙; 나머지는 참고)")
print("\n| 변형 | 진입 | 승률 | 평균 순ROE | 비용 전 ROE | log 성장 | $1,000 → | 동전 5~95% (log) | 동전보다 나은 비율 |")
print("|---|---|---|---|---|---|---|---|---|")
order = [R["C"]["selected"], "C0_current"] + [k for k in CN if k not in (R["C"]["selected"], "C0_current")]
for k in order:
    b = R["C"]["variants"][k]["confirm_2025_202609"]
    tl = b["twin_log_growth_5_50_95"]
    tag = " (선택)" if k == R["C"]["selected"] else (" (지금)" if k == "C0_current" else " (참고)")
    print(f"| {CN[k]}{tag} | {b['entries']} | {b['win_pct']:.0f}% | {p(b['roe_mean'])} | {p(b['pre_mean'])} | {b['log_growth']:.2f} | "
          f"{usd(b['growth'])} | {tl[0]:.2f} ~ {tl[2]:.2f} | {b['rank_vs_twin_pct']:.0f}% |")
print("\n", json.dumps(R["C"]["confirm"], ensure_ascii=False))
print("\n## C 연도별 $1,000 → (참고)")
print("| 변형 | " + " | ".join(ys) + " |")
print("|---" * (len(ys) + 1) + "|")
for k, nm in CN.items():
    d = R["C"]["variants"][k]["years"]
    print(f"| {nm} | " + " | ".join(usd(d[y]["growth"]) + f" ({p(d[y]['roe_mean'])})" for y in ys) + " |")

print("\n## 거름 단계 (D0, 신호 막대 마감 연도별)")
f = R["funnel_C0"]
cols = ["when", "block", "check", "no_pullback", "block_at_entry", "in_position", "lower_score", "entered"]
print("| 연도 | 신호 | " + " | ".join(cols) + " |")
print("|---" * (len(cols) + 2) + "|")
for y, r in f["by_year"].items():
    print(f"| {y} | {sum(r.values())} | " + " | ".join(str(r.get(c, 0)) for c in cols) + " |")
print("막힘 이유:", f["blocks"])
print("\n애매한 1분봉(손절 먼저):", R["ambiguity_stop_first_C0"], "메이커:", R["ambiguity_stop_first_D4"],
      "메이커 체결 분 손절:", R["maker_stopped_in_fill_minute"])
