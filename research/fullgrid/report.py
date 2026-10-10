"""Korean report of the full-grid study (research/fullgrid/run.py ``report`` and ``pack``): OUT/RESULTS_KO.md,
OUT/candidates.csv, OUT/cells.csv; ``pack`` copies them with select.json, confirm.json and every cell's pooled
statistics (grid_stats.npz) into OUT/results for the trip home.

DeepSeek money numbers: the owners' decision D11 hides DeepSeek's money figures (counts only) until they decide
otherwise for this report (DESIGN_KO.md section 10); ``DS_MONEY`` switches it.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DS_MONEY = False
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
DS_PARAM_KO = {
    "swing_k": "스윙 확인 봉 수", "zone_life": "구간 유지 봉 수", "fvg_min_atr": "FVG 최소 크기(ATR)",
    "disp_atr": "장대봉 기준(ATR)", "leg_atr": "파동 최소 크기(ATR)", "leg_max_bars": "파동 최대 길이",
    "div_max_bars": "다이버전스 최대 간격", "rsi_len": "RSI 길이", "mom_len": "모멘텀 길이", "ema_len": "EMA 길이",
    "ema_fast": "빠른 EMA", "ema_mid": "중간 EMA", "ema_slow": "느린 EMA", "rsi_level": "RSI 기준선",
    "fan_lens": "EMA 부채 길이들", "box_len": "박스 길이", "adx_max": "ADX 상한", "edge": "박스 끝 비율",
    "width_atr": "박스 최소 폭(ATR)", "fail_bars": "실패 확인 봉 수", "rf_period": "레인지 필터 기간",
    "rf_mult": "레인지 필터 배수", "body_frac": "몸통 비율", "body_atr": "몸통 크기(ATR)", "sweep_bars": "사냥 확인 봉 수",
    "tsoup_len": "터틀 수프 길이", "min_age": "최소 경과 봉 수", "po3_range_h": "축적 구간(시간)",
    "po3_rev_bars": "되돌림 봉 수", "smt_len": "SMT 비교 길이", "asia_win_h": "아시아 돌파 창(시간)",
    "lon_win_h": "런던 돌파 창(시간)", "judge_min": "판단까지 분", "orb_bars": "시초 구간 봉 수", "z_len": "Z 길이",
    "z_level": "Z 기준", "hl_len": "평균회귀 측정 길이", "half_life": "반감기 상한",
}


def _names():
    try:
        from paperbot.agents.roster3 import STRATEGY_KO
        from paperbot.dash.more.params import PARAM_KO
        return dict(STRATEGY_KO), dict(PARAM_KO)
    except Exception:  # noqa: BLE001  a bare server without the dashboard deps still writes the report
        return {}, {}


def strat_ko(kind: str, name: str, S: dict) -> str:
    return f"{S.get(name, name)} (`{name}`)" if kind == "core" else f"딥시크 `{name}`"


def param_ko(kind: str, p: str, P: dict) -> str:
    return (P.get(p) if kind == "core" else DS_PARAM_KO.get(p)) or p


def pct(x, d=3) -> str:
    return "-" if x is None else f"{x * 100:+.{d}f}%"


def money_ok(kind: str) -> bool:
    return kind == "core" or DS_MONEY


def _defaults(kind: str, name: str) -> dict:
    run = sys.modules.get("fullgrid_run")
    return run.default_combo(kind, name) if run else {}


def exit_ko(name: str) -> str:
    """'roe20|1.5' -> '손절 1.5 ATR · 고정 익절 수익 20%'."""
    rule, k = name.split("|")
    stop = f"손절 {float(k):g} ATR"
    tp = {"ladder": "계단 잠금 10%부터(지금)", "ladder5": "계단 잠금 5%부터", "ladder20": "계단 잠금 20%부터",
          "ladder_tp2R": "계단 잠금 + 익절 2R", "swing3": "구조 익절(가까운 스윙 고·저점, 3봉) + 계단 잠금",
          "swing10": "구조 익절(큰 스윙 고·저점, 10봉) + 계단 잠금"}.get(rule)
    if tp is None and rule.startswith("roe"):
        tp = f"고정 익절 수익 {rule[3:]}%"
    if tp is None and rule.startswith("tp"):
        tp = f"고정 익절 {rule[2:]}(손절 거리의 {rule[2:-1]}배)"
    return f"{stop} · {tp or rule}"


LIVE_EXIT = "ladder|2"


def changes(r: dict, P: dict) -> str:
    d = _defaults(r["kind"], r["name"])
    out = []
    for k, v in r["combo"].items():
        dv = d.get(k)
        if dv is not None and (list(dv) if isinstance(dv, tuple) else dv) != v:
            out.append(f"{param_ko(r['kind'], k, P)} {_fmt(dv)}→{_fmt(v)}")
    return ", ".join(out) or "숫자는 지금과 같음"


def _fmt(v) -> str:
    if isinstance(v, (list, tuple)):
        return "(" + ",".join(_fmt(x) for x in v) + ")"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def write(out: str) -> str:
    S, P = _names()
    sel = json.load(open(os.path.join(out, "select.json")))
    con = json.load(open(os.path.join(out, "confirm.json")))
    rows = con["rows"]
    L = []
    core = [r for r in rows if r["kind"] == "core"]
    ds = [r for r in rows if r["kind"] == "ds"]
    pc = [r for r in core if r["pass"]]
    pd_ = [r for r in ds if r["pass"]]
    cells = sel["cells"]
    L.append("# 5년 전체 조합 커스텀값 연구 결과")
    L.append("")
    L.append("기준은 `research/fullgrid/PREREG.md`(계산 전에 고정). 거래 하나 = 신호 하나, $5,000 계좌, 지금 v4 규칙봇과 같은 진입·손절·"
             "계단 잠금·레버리지 규칙·수수료·펀딩·강제청산(1분봉). '거래당'은 거래 하나의 순손익을 계좌 $5,000에 대한 %로 적은 것입니다.")
    L.append("")
    L.append("## 결론")
    L.append("")
    L.append(f"- **규칙봇 36개**: 고른 조합 {len(core)}개 중 **{len(pc)}개 통과**")
    L.append(f"- **딥시크 44개**: 고른 조합 {len(ds)}개 중 **{len(pd_)}개 통과**")
    if sel.get("missing"):
        L.append(f"- ⚠️ **계산이 빠진 칸 {len(sel['missing'])}개** (이 칸들은 고르기·우연 보정에서 빠졌습니다): "
                 + ", ".join(sel["missing"][:12]) + (" …" if len(sel["missing"]) > 12 else ""))
    nf = sum(c.get("failed_combos", 0) for c in cells)
    if nf:
        L.append(f"- 참고: 신호 계산이 실패한 숫자 조합 {nf:,}개(거래 없음으로 셈, `cells.csv`의 failed_combos).")
    if not pc and not pd_:
        L.append("- 세 기간을 모두 통과한 숫자 조합이 **없습니다.** 숫자를 바꿔서 운을 넘어 좋아진다는 근거가 이번에도 나오지 않았습니다. "
                 "기준을 낮춰 다시 찾지 않습니다(PREREG 6.5).")
    else:
        L.append("- 통과한 후보는 **바로 실거래에 쓰지 않습니다.** 실시간 그림자·데모봇에서 고른 뒤의 성적(28일 이상, 거래 20건 이상)으로 "
                 "다시 확인합니다(PREREG 7).")
    L.append("")
    if pc or pd_:
        L.append("## 후보")
        L.append("")
        L.append("| 매매법 | 봉 | 바꾼 숫자 | 청산(손절·익절) | 고르는 기간(2021-23) 거래당 | 시험 기간(2024-26) 거래당 · 기본값 | "
                 "2020 거래당 | 시험 거래 수 | 실제 계좌식 2021-26 ($5,000 → 후보 / 기본값, 최대 낙폭) |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for r in pc + pd_:
            m = money_ok(r["kind"])
            acc = r.get("account") or {}
            a, b = acc.get("pick") or {}, acc.get("default") or {}
            at, bt = acc.get("pick_test") or {}, acc.get("default_test") or {}
            acc_s = (f"${a.get('final', 0):,.0f} / ${b.get('final', 0):,.0f}, {a.get('max_dd_at_closes', 0):.0%}"
                     + (" 파산" if a.get("bust") else "")
                     + f"; 시험 기간만 ${at.get('final', 0):,.0f} / ${bt.get('final', 0):,.0f}") if (m and a) else "(가림)"
            ex_s = exit_ko(r["exit"]) + ("" if r["exit"] != LIVE_EXIT else " (지금과 같음)")
            L.append(f"| {strat_ko(r['kind'], r['name'], S)} | {TF_KO[r['tf']]} | {changes(r, P)} | {ex_s} | "
                     f"{pct(r['select_mean']) if m else '+'} | "
                     f"{(pct(r['test']['mean']) + ' · ' + pct(r['default_test']['mean'])) if m else '기본값보다 높음'} | "
                     f"{pct(r['extra']['mean']) if m else '+'} | {r['test']['n']:,} | {acc_s} |")
        L.append("")
    L.append("## 단계별 통과 수")
    L.append("")
    L.append("| 단계 | 규칙봇 36개 | 딥시크 44개 |")
    L.append("|---|---|---|")

    def cnt(kind, f):
        return sum(1 for c in cells if c["kind"] == kind and f(c))
    L.append(f"| 칸(매매법 × 봉) | {cnt('core', lambda c: True)} | {cnt('ds', lambda c: True)} |")
    L.append(f"| 숫자 조합 | {sum(c['combos'] for c in cells if c['kind'] == 'core'):,} | "
             f"{sum(c['combos'] for c in cells if c['kind'] == 'ds'):,} |")
    L.append(f"| 숫자 조합 × 청산 방식 {len(sel.get('exits', [1]))}가지 | "
             f"{sum(c['combos'] * c.get('exits', 1) for c in cells if c['kind'] == 'core'):,} | "
             f"{sum(c['combos'] * c.get('exits', 1) for c in cells if c['kind'] == 'ds'):,} |")
    L.append(f"| 고르는 기간 거래 150건 이상인 조합이 있는 칸 | {cnt('core', lambda c: c['with_min_trades'] > 0)} | "
             f"{cnt('ds', lambda c: c['with_min_trades'] > 0)} |")
    L.append(f"| 언덕 점수가 플러스인 조합이 있는 칸 | {cnt('core', lambda c: c['plateau_positive'] > 0)} | "
             f"{cnt('ds', lambda c: c['plateau_positive'] > 0)} |")
    L.append(f"| 고른 조합 (칸마다 최대 3개, 지금 숫자·지금 청산보다 높은 언덕) | {len(core)} | {len(ds)} |")
    for key, label in (("test_trades", "시험 기간 거래 100건 이상"), ("test_positive", "시험 기간 플러스"),
                       ("test_beats_default", "시험 기간 기본값보다 높음"), ("test_fdr", "우연 보정(FDR 10%) 통과"),
                       ("extra_positive", "2020년 플러스")):
        L.append(f"| {label} | {sum(1 for r in core if r['checks'][key])} | {sum(1 for r in ds if r['checks'][key])} |")
    L.append(f"| **모두 통과** | **{len(pc)}** | **{len(pd_)}** |")
    L.append("")
    L.append("## 기본값은 어땠나 (고르는 기간, 칸마다)")
    L.append("")
    for kind, label in (("core", "규칙봇"), ("ds", "딥시크")):
        cs = [c for c in cells if c["kind"] == kind]
        dm = [c["default"]["mean"] for c in cs if c["default"]["mean"] is not None and c["default"]["n"] >= 150]
        if dm and money_ok(kind):
            L.append(f"- {label}: 기본값 거래당 중앙값 {pct(float(np.median(dm)))}, 플러스인 칸 "
                     f"{sum(1 for x in dm if x > 0)}/{len(dm)}")
        elif dm:
            L.append(f"- {label}: 기본값이 플러스인 칸 {sum(1 for x in dm if x > 0)}/{len(dm)} (돈 숫자 가림, D11)")
    L.append("")
    L.append("## 지금 숫자 그대로 청산만 바꾸면 (고르는 기간, 참고)")
    L.append("")
    from collections import Counter
    for kind, label in (("core", "규칙봇"), ("ds", "딥시크")):
        cs = [c for c in cells if c["kind"] == kind and c.get("default_numbers_best_exit")]
        better = [c for c in cs if (c["default_numbers_best_exit"]["plateau"] or 0) > c["default"]["plateau"]]
        top = Counter(c["default_numbers_best_exit"]["exit"] for c in better).most_common(3)
        L.append(f"- {label}: 청산만 바꿔서 언덕 점수가 지금보다 높아지는 칸 {len(better)}/{len(cs)}"
                 + (" (많이 나온 방식: " + ", ".join(f"{exit_ko(e)} {n}칸" for e, n in top) + ")" if top else "")
                 + ". 통과 기준이 아니라 참고입니다.")
    L.append("")
    L.append("## 읽는 법")
    L.append("")
    L.append("- **언덕 점수**: 그 조합과 바로 옆 조합(숫자 하나를 한 칸 움직인 것, 손절 폭을 한 칸 움직인 것)들의 거래당 순손익 "
             "중앙값. 혼자만 튀는 숫자는 뽑히지 않습니다.")
    L.append("- **청산 방식 84가지**: 손절 1·1.5·2(지금)·2.5·3·4 ATR × 익절 14가지(계단 잠금 5%·10%(지금)·20%부터, 고정 익절 "
             "수익 10%·20%·30%·50%, 고정 익절 1R·1.5R·2R·3R, 계단 잠금+익절 2R, 구조 익절 3봉·10봉 스윙 + 계단 잠금). R = 손절 거리. "
             "수익 %는 증거금 대비 비용 뺀 수익(ROE).")
    L.append("- **우연 보정(FDR)**: 고른 조합을 모두 한 묶음으로 보고, 많이 시험해서 우연히 좋아 보이는 것을 걸러 냅니다(주 단위 다시 뽑기 2,000번).")
    L.append("- **실제 계좌식**: 후보만 따로, 실제 계좌처럼 한 번에 한 포지션·복리·파산 포함으로 다시 계산한 값입니다. 최대 낙폭은 거래가 끝날 때 잔고 기준입니다.")
    L.append("- 걸러내기 단계는 신호 하나를 거래 하나로 셉니다(포지션이 있어도 셈). 그래서 거래 수는 실제 계좌보다 많습니다.")
    if not DS_MONEY:
        L.append("- 딥시크는 두 분 결정 D11에 따라 돈 숫자를 가리고 통과 여부와 개수만 적었습니다.")
    L.append("")
    L.append("파일: `candidates.csv`(고른 조합 전부와 단계별 결과), `cells.csv`(칸마다 요약), `grid_stats.npz`(모든 숫자 조합, 지금 "
             "청산), `default_by_exit.npz`(지금 숫자, 청산 84가지).")
    text = "\n".join(L) + "\n"
    with open(os.path.join(out, "RESULTS_KO.md"), "w") as fh:
        fh.write(text)
    _csvs(out, rows, cells)
    print(text[:3000])
    return text


def _csvs(out: str, rows: list, cells: list) -> None:
    with open(os.path.join(out, "candidates.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["kind", "name", "tf", "rank", "combo", "exit", "select_n", "select_mean", "plateau", "default_plateau",
                    "test_n", "test_mean", "test_p", "default_test_mean", "extra_n", "extra_mean", "pass"]
                   + ["check_" + k for k in (rows[0]["checks"] if rows else [])])
        for r in rows:
            hide = not money_ok(r["kind"])
            w.writerow([r["kind"], r["name"], r["tf"], r["rank"], json.dumps(r["combo"]), r["exit"], r["select_n"],
                        "" if hide else r["select_mean"], "" if hide else r["plateau"], "" if hide else r["default_plateau"],
                        r["test"]["n"], "" if hide else r["test"]["mean"], r["test"]["p"],
                        "" if hide else r["default_test"]["mean"], r["extra"]["n"], "" if hide else r["extra"]["mean"],
                        r["pass"]] + [r["checks"][k] for k in r["checks"]])
    with open(os.path.join(out, "cells.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["kind", "name", "tf", "combos", "with_min_trades", "plateau_positive", "default_n", "default_mean",
                    "default_plateau", "best_plateau", "picks", "failed_combos"])
        for c in cells:
            hide = not money_ok(c["kind"])
            w.writerow([c["kind"], c["name"], c["tf"], c["combos"], c["with_min_trades"], c["plateau_positive"],
                        c["default"]["n"], "" if hide else c["default"]["mean"], "" if hide else c["default"]["plateau"],
                        "" if hide else c["best_plateau"], len(c["picks"]), c.get("failed_combos", 0)])


def pack(out: str, run) -> str:
    """OUT/results: the report files plus every cell's pooled statistics (float32) and its grid."""
    dest = os.path.join(out, "results")
    os.makedirs(dest, exist_ok=True)
    for f in ("RESULTS_KO.md", "candidates.csv", "cells.csv", "code_stamp.json"):
        if os.path.exists(os.path.join(out, f)):
            shutil.copy(os.path.join(out, f), dest)
    for f in ("select.json", "confirm.json"):                   # DeepSeek money figures stay on the server (D11)
        if os.path.exists(os.path.join(out, f)):
            doc = _strip_ds(json.load(open(os.path.join(out, f))))
            with open(os.path.join(dest, f), "w") as fh:
                json.dump(doc, fh, indent=1, ensure_ascii=False)
    live, by_exit, grids = {}, {}, {}
    for kind, name, tf in run.cells():
        st = run.cell_stats(out, kind, name, tf)
        if st is None:
            continue
        key = f"{kind}|{name}|{tf}"
        if kind == "ds" and not DS_MONEY:
            st = st.copy()
            st[..., 1:] = np.nan                                           # counts only (D11)
        live[key] = st[:, 0].astype(np.float32)                         # every combination, the live exit
        by_exit[key] = st[run.default_row(kind, name)].astype(np.float32)  # the live numbers, every exit
        ps, vals, _combos = run.cell_grid(kind, name)
        grids[f"{kind}|{name}"] = {"params": [p["name"] for p in ps], "values": [list(map(_plain, v)) for v in vals]}
    np.savez_compressed(os.path.join(dest, "grid_stats.npz"), **live)
    np.savez_compressed(os.path.join(dest, "default_by_exit.npz"), **by_exit)
    with open(os.path.join(dest, "grids.json"), "w") as fh:
        json.dump({"grids": grids, "exits": [e[0] for e in run.K.EXITS],
                   "stats": "[combination or exit, period select/test/extra, n/sum/sumsq/wins]"}, fh)
    return dest


MONEY_KEYS = ("select_mean", "plateau", "default_select_mean", "default_plateau", "mean", "sum", "best_plateau",
              "account", "default_numbers_best_exit")


def _strip_ds(doc):
    """DeepSeek rows and cells without money figures (D11), unless DS_MONEY."""
    if DS_MONEY:
        return doc

    def clean(x):
        if isinstance(x, dict):
            return {k: (None if k in MONEY_KEYS else clean(v)) for k, v in x.items()}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x
    for key in ("picks", "rows", "cells"):
        if key in doc:
            doc[key] = [clean(r) if r.get("kind") == "ds" else r for r in doc[key]]
    return doc


def _plain(v):
    return list(v) if isinstance(v, tuple) else v
