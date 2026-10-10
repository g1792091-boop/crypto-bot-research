"""Korean report of strat_report.json: every strategy, every timeframe, nothing left out. DeepSeek money figures are
hidden (D11: trade counts, win rates and plus / minus labels only) unless FULLGRID_DS_MONEY=1.

    python research/fullgrid/diag/strat_md.py strat_report.json STRATEGIES_KO.md
"""

import json
import os
import re
import sys

DS_MONEY = os.environ.get("FULLGRID_DS_MONEY") == "1"
TFS = ("15m", "30m", "1h", "4h")
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
STATE_COLS = (("장세", "추세장", "추세장"), ("장세", "횡보장", "횡보장"), ("장세", "급변장", "급변장"),
              ("장세", "보통", "보통장"), ("큰 흐름", "위", "상승장"), ("큰 흐름", "아래", "하락장"),
              ("변동성", "작음", "조용한 장"), ("변동성", "보통", "보통 변동"), ("변동성", "큼", "출렁이는 장"))
MIN_N = 20
DS_KO = {
    "F1_RSI_DIV": "RSI 다이버전스", "F1_PVT_DIV": "PVT 다이버전스", "F1_MOM_DIV": "모멘텀 다이버전스",
    "F2_DEMARK": "디마크 피벗", "F3_BOS": "구조 돌파(BOS)", "F3_BOS_ZONE": "BOS 구간 되돌림",
    "F3_HHHL": "고점·저점 높아짐", "F4_PULL": "EMA 정렬 눌림", "F4_PULL_RSI": "EMA 눌림·RSI",
    "F4_FAN": "EMA 피보나치 리본", "F5_BOX": "박스권", "F5_BOX_RSI": "박스권·RSI", "F5_BOX_HTF": "박스권(상위 봉)",
    "F6_VWAP_CROSS": "VWAP 교차", "F6_VWAP_FAIL": "VWAP 복귀 실패", "F7_RF_TRIPLE": "레인지 필터 3중 일치",
    "F7_RF_ONLY": "레인지 필터 방향 전환", "F8_VWICK": "버진 윅", "F9_FVG": "FVG 되돌림", "F9_IFVG": "반전 FVG",
    "F9_OB": "오더 블록", "F9_BREAKER": "브레이커 블록", "F10_M2022": "ICT 2022 모델",
    "F10_OTE": "ICT OTE(62~79% 되돌림)", "F11_TSOUP": "터틀 수프", "F11_RAID": "유동성 레이드",
    "F11_PO3": "파워 오브 3", "F12_MSS": "구조 전환(MSS)", "F12_MSS_DISP": "구조 전환·변위",
    "F13_FVG_PD": "FVG·프리미엄/디스카운트", "F13_RAID_PD": "레이드·프리미엄/디스카운트", "F14_SMT": "SMT 다이버전스",
    "F15_ASIA_BRK": "아시아 레인지 돌파", "F15_ASIA_SWEEP": "아시아 레인지 스윕", "F15_LON_BRK": "런던 레인지 돌파",
    "F15_OPEN0930": "뉴욕 09:30 시가 편향", "F15_OPEN0000": "자정 시가 편향", "F15_ORB": "시가 범위 돌파",
    "F16_FIB382": "피보나치 38.2% 되돌림", "F16_FIB500": "피보나치 50% 되돌림", "F16_FIB618": "피보나치 61.8% 되돌림",
    "F16_FIB764": "피보나치 76.4% 되돌림", "F17_Z": "Z점수 평균회귀", "F17_Z_HL": "Z점수·반감기",
}


def core_names() -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "..", "strategy_profiles", "out_binance", "PROFILES.md")
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"^## (.+) \(([A-Z0-9_]+)\)$", line.strip())
            if m:
                out[m.group(2)] = m.group(1)
    return out


def exit_ko(name: str) -> str:
    tp, stop = name.split("|")
    style = {"ladder": "계단 잠금", "ladder5": "계단 잠금 5%", "ladder20": "계단 잠금 20%",
             "ladder_tp2R": "계단 잠금 + 2R", "swing3": "스윙 익절(3봉)", "swing10": "스윙 익절(10봉)"}.get(tp)
    if style is None:
        style = f"익절 수익 {tp[3:]}%" if tp.startswith("roe") else f"익절 {tp[2:]}"
    return f"손절 {stop} ATR · {style}"


def combo_ko(combo: str) -> str:
    d = json.loads(combo)
    return ", ".join(f"{k} {round(v, 3) if isinstance(v, float) else v}" for k, v in d.items())


def pct(x, nd=2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def money(x) -> str:
    return "—" if x is None else f"${5000 * x:,.0f}"


class Fmt:
    def __init__(self, hide: bool):
        self.hide = hide

    def mean(self, s: dict) -> str:
        if not s or s.get("n", 0) == 0:
            return "거래 없음"
        if self.hide:
            return "플러스" if s["mean"] > 0 else "마이너스"
        return pct(s["mean"])

    def payoff(self, s: dict) -> str:
        if self.hide or not s or s.get("n", 0) == 0 or s.get("payoff") is None:
            return "—"
        return f"{s['payoff']:.2f}"

    def account(self, a) -> str:
        if not a:
            return "거래 없음"
        if a["bust"]:
            return "파산" if self.hide else f"파산 ({money(a['final_x'])})"
        if self.hide:
            return "늘어남" if a["final_x"] > 1 else "줄어듦"
        return money(a["final_x"])

    def dd(self, a) -> str:
        if not a or self.hide:
            return "—"
        return f"{a['max_dd'] * 100:.0f}%"

    def cell(self, s: dict) -> str:
        if not s or s.get("n", 0) < MIN_N:
            return "—"
        m = ("+" if s["mean"] > 0 else "−") if self.hide else pct(s["mean"], 1)
        return f"{m} ({s['win'] * 100:.0f}%)"


def all_n(spec: dict) -> int:
    return sum(spec["periods"][p].get("n", 0) for p in ("select", "test"))


def all_win(spec: dict) -> str:
    n = w = 0
    for p in ("select", "test"):
        s = spec["periods"][p]
        if s.get("n"):
            n += s["n"]
            w += s["win"] * s["n"]
    return f"{w / n * 100:.0f}%" if n else "—"


def checks_ko(c: dict) -> str:
    marks = [("시험 기간 거래 100건↑", "check_test_trades"), ("시험 플러스", "check_test_positive"),
             ("지금 숫자보다 나음", "check_test_beats_default"), ("우연 보정", "check_test_fdr"),
             ("2020 플러스", "check_extra_positive")]
    return " · ".join(f"{lab} {'O' if c.get(k) else 'X'}" for lab, k in marks)


def spec_rows(recs: dict, key: str, F: Fmt) -> list:
    rows = []
    for tf in TFS:
        r = recs.get(tf)
        sp = r.get(key) if r else None
        if not sp:
            rows.append(f"| {TF_KO[tf]} | 고를 값 없음 | | | | | | | |" if key == "pick" else
                        f"| {TF_KO[tf]} | 계산 없음 | | | | | | | |")
            continue
        p, a = sp["periods"], sp["account"]
        rows.append(f"| {TF_KO[tf]} | {all_n(sp):,} | {all_win(sp)} | {F.payoff(p['test'])} | "
                    f"{F.mean(p['select'])} | {F.mean(p['test'])} | {F.mean(p['extra'])} | "
                    f"{F.account(a.get('test'))} ({F.dd(a.get('test'))}) | {F.account(a.get('select'))} |")
    return rows


def state_rows(recs: dict, key: str, F: Fmt) -> list:
    rows = []
    for tf in TFS:
        r = recs.get(tf)
        sp = r.get(key) if r else None
        if not sp:
            continue
        cells = [F.cell(sp["states"][d][s]) for d, s, _lab in STATE_COLS]
        rows.append(f"| {TF_KO[tf]} | " + " | ".join(cells) + " |")
    return rows


def coin_rows(recs: dict, key: str, F: Fmt) -> list:
    rows = []
    for tf in TFS:
        r = recs.get(tf)
        sp = r.get(key) if r else None
        if not sp:
            continue
        cells = [F.cell(sp["coins"][c]) for c in COINS] + [F.cell(sp["sides"][s]) for s in ("long", "short")]
        rows.append(f"| {TF_KO[tf]} | " + " | ".join(cells) + " |")
    return rows


def section(name: str, label: str, recs: dict, F: Fmt) -> list:
    out = [f"### {label} ({name})", ""]
    out += ["**지금 숫자 (규칙봇이 돌리는 값, 손절 2 ATR · 계단 잠금)**", "",
            "| 봉 | 거래 수 21~26 | 승률 21~26 | 손익비 24~26 | 거래당 21~23 | 거래당 24~26 | 거래당 2020 | "
            "계좌 24~26 (최대 낙폭) | 계좌 21~23 |",
            "|---|---|---|---|---|---|---|---|---|"] + spec_rows(recs, "default", F) + [""]
    out += ["**가장 좋았던 커스텀값 (고르는 기간 1등)**", "",
            "| 봉 | 거래 수 21~26 | 승률 21~26 | 손익비 24~26 | 거래당 21~23 | 거래당 24~26 | 거래당 2020 | "
            "계좌 24~26 (최대 낙폭) | 계좌 21~23 |",
            "|---|---|---|---|---|---|---|---|---|"] + spec_rows(recs, "pick", F) + [""]
    picks = [(tf, recs[tf]["pick"]) for tf in TFS if recs.get(tf) and recs[tf].get("pick")]
    if picks:
        out += ["커스텀값과 관문 결과:", ""]
        for tf, pk in picks:
            out.append(f"- {TF_KO[tf]}: {combo_ko(pk['combo'])} / {exit_ko(pk['exit'])} — {checks_ko(pk['checks'])}")
        out.append("")
    head = "| 봉 | " + " | ".join(lab for _d, _s, lab in STATE_COLS) + " |"
    sep = "|---|" + "---|" * len(STATE_COLS)
    for key, title in (("default", "지금 숫자"), ("pick", "커스텀값 1등")):
        rows = state_rows(recs, key, F)
        if rows:
            out += [f"**장세별 거래당 (승률), {title}, 2021~2026**", "", head, sep] + rows + [""]
    rows = coin_rows(recs, "default", F)
    if rows:
        out += ["**코인별·방향별 거래당 (승률), 지금 숫자, 2021~2026**", "",
                "| 봉 | BTC | ETH | SOL | DOGE | LTC | BCH | 롱 | 숏 |", "|---|---|---|---|---|---|---|---|---|"]
        out += rows + [""]
    return out


def overview(by: dict, names: list, labels: dict, F: Fmt) -> list:
    out = ["| 매매법 | " + " | ".join(f"지금 숫자 {TF_KO[t]}" for t in TFS) + " | "
           + " | ".join(f"커스텀값 {TF_KO[t]}" for t in TFS) + " |", "|---|" + "---|" * 8]
    for n in names:
        recs = by[n]
        d = [F.account(recs[t]["default"]["account"].get("test")) if recs.get(t) else "—" for t in TFS]
        p = [F.account(recs[t]["pick"]["account"].get("test")) if recs.get(t) and recs[t].get("pick") else "—"
             for t in TFS]
        out.append(f"| {labels.get(n, n)} | " + " | ".join(d + p) + " |")
    return out


def tally(res: list, kind: str, key: str, per: str) -> dict:
    acc = [r[key]["account"].get(per) for r in res if r["kind"] == kind and r.get(key)]
    acc = [a for a in acc if a]
    up = sum(a["final_x"] > 1 and not a["bust"] for a in acc)
    bust = sum(a["bust"] for a in acc)
    return {"n": len(acc), "up": up, "bust": bust, "down": len(acc) - up - bust,
            "x2": sum(a["final_x"] >= 2 for a in acc)}


def summary(res: list) -> list:
    cells = state_cells(res)
    out = ["## 먼저 요약", "", "시험 기간(2024~2026) 계좌를 $5,000으로 돌렸을 때입니다(거래가 있는 칸만).", "",
           "| 묶음 | 칸 | 늘어남 | 줄어듦 | 파산 | 2배 이상 |", "|---|---|---|---|---|---|"]
    for kind, kl in (("core", "규칙봇"), ("ds", "딥시크")):
        for key, vl in (("default", "지금 숫자"), ("pick", "커스텀값 1등")):
            t = tally(res, kind, key, "test")
            out.append(f"| {kl} {vl} | {t['n']} | {t['up']} | {t['down']} | {t['bust']} | {t['x2']} |")
    wins = {}
    for key in ("default", "pick"):
        w = [r[key]["periods"]["test"]["win"] for r in res
             if r["kind"] == "core" and r.get(key) and r[key]["periods"]["test"].get("n", 0) >= 30]
        wins[key] = sorted(w)[len(w) // 2] if w else None
    out += ["",
            f"- 지금 숫자(계단 잠금)는 승률이 높습니다(규칙봇 시험 기간 중앙값 {wins['default'] * 100:.0f}%). 그런데도 계좌는 대부분 "
            "줄거나 파산했습니다. 작게 여러 번 이기고 크게 집니다.",
            f"- 커스텀값 1등은 대부분 3R 고정 익절이라 승률이 낮습니다(중앙값 {wins['pick'] * 100:.0f}%). 고르는 기간에는 계좌가 "
            "많이 늘었지만, 시험 기간에는 대부분 줄었습니다.",
            "- **계좌 결과는 운에 크게 흔들립니다.** 규칙봇 레버리지에서는 거래 순서와 큰 이익 몇 번이 결과를 정합니다. 예를 들어 "
            "돈치안·MFI 1시간 커스텀값은 시험 기간 거래당 평균이 마이너스(−0.67%)인데도 계좌는 $75,644가 됐습니다. 그 사이 최대 "
            "낙폭은 94%였고, 이 값을 고른 기간(2021~2023)에는 계좌가 제자리($4,950, 낙폭 84%)였습니다. 그래서 통과 기준은 계좌 "
            "금액이 아니라 거래당 평균과 우연 보정으로 정했습니다.",
            f"- 장세·코인·방향별로 나눠 봐도 지금 숫자가 플러스인 곳은 거의 없습니다. 규칙봇 쪽 거래 20건 이상인 {cells[0]:,}칸 중 "
            f"{cells[1]}칸({cells[1] / max(cells[0], 1) * 100:.0f}%)만 플러스였습니다.", ""]
    return out


def state_cells(res: list) -> tuple:
    tot = pos = 0
    for r in res:
        if r["kind"] != "core":
            continue
        d = r["default"]
        for grp in list(d["states"].values()) + [d["coins"], d["sides"]]:
            for v in grp.values():
                if v.get("n", 0) >= MIN_N:
                    tot += 1
                    pos += v["mean"] > 0
    return tot, pos


def main(src: str, dst: str) -> None:
    res = json.load(open(src))
    cn = core_names()
    by = {"core": {}, "ds": {}}
    for r in res:
        by[r["kind"]].setdefault(r["name"], {})[r["tf"]] = r
    out = ["# 매매법 80개 성적표 (5년, 하나도 빠짐없이)", "",
           "`ANALYSIS_KO.md`의 부록입니다. 결과를 본 뒤 만든 참고용이라 통과·탈락을 바꾸지 않습니다. 숫자는",
           "`diag/strat_report.py`(계산)와 `diag/strat_md.py`(이 문서)가 만들었습니다.", "",
           "## 읽는 법", "",
           "- **지금 숫자**: 규칙봇이 지금 돌리는 기본값과 지금 청산(손절 2 ATR, 계단 잠금)입니다.",
           "- **커스텀값 1등**: 그 칸에서 고르는 기간(2021~2023)만 보고 1등으로 고른 값과 청산입니다.",
           "- **거래 수·승률·거래당**: 신호 하나를 거래 하나로 셉니다(포지션이 있어도 셈). 거래당은 거래 하나의 순손익을 계좌 대비 %로 "
           "적은 것입니다(수수료·슬리피지·펀딩 포함). 손익비는 평균 이익 ÷ 평균 손실입니다.",
           "- **계좌**: 실제 계좌처럼 계산했습니다. $5,000에서 시작해 한 번에 한 포지션, 복리, 규칙봇과 같은 레버리지·강제청산·파산"
           "(잔고 $10 아래)을 적용했습니다. 괄호 안은 그 기간 최대 낙폭입니다.",
           "- **기간**: 21~23 = 고르는 기간, 24~26 = 시험 기간(2026-09까지), 2020 = 추가 기간.",
           "- **장세별·코인별**: 2021~2026 전체에서 그 장세·코인의 거래당과 (승률)입니다. 거래 20건 미만은 —.",
           "  - 장세: 추세장·횡보장·급변장·보통장",
           "  - 큰 흐름: 일봉 EMA200 위 = 상승장, 아래 = 하락장",
           "  - 변동성: 조용한 장·보통 변동·출렁이는 장",
           "- **딥시크**는 두 분 결정 D11에 따라 돈 숫자를 가립니다. 거래 수·승률과 플러스/마이너스, 계좌는 늘어남/줄어듦/파산만 "
           "적습니다. 두 분이 정하시면 `FULLGRID_DS_MONEY=1`로 숫자를 열 수 있습니다.", ""]
    out += summary(res)
    for kind, title in (("core", "규칙봇 36개"), ("ds", "딥시크 44개")):
        F = Fmt(kind == "ds" and not DS_MONEY)
        labels = cn if kind == "core" else DS_KO
        names = sorted(by[kind], key=lambda n: (labels.get(n, n)))
        out += [f"## {title}: 한눈에 보기 (시험 기간 2024~2026 계좌, $5,000 시작)", ""]
        out += overview(by[kind], names, labels, F) + [""]
    for kind, title in (("core", "규칙봇 36개"), ("ds", "딥시크 44개")):
        F = Fmt(kind == "ds" and not DS_MONEY)
        labels = cn if kind == "core" else DS_KO
        out += [f"## {title}: 매매법별 자세히", ""]
        for n in sorted(by[kind], key=lambda n: (labels.get(n, n))):
            out += section(n, labels.get(n, n), by[kind][n], F)
    open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
