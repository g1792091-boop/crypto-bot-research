"""Hunt round 2 results page in plain Korean (PREREG_HUNT_R2.md sections 5, 6, 7, 8, 9, 10): research/hunt_r2/out/
RESULTS_R2_KO.md, written from the public files only (picks.json, pretest_reads.json, test.json, reads_*.json), so a
DeepSeek row never shows a money figure (D11: numbers, ranks, counts and labels only).

It can be written at any stage (after select, after the pretest reads, after the test, after the reads); each section
says what is not there yet. Two labels that need round 1's output ("기준 기본값 = 1차 시스템 <id>" with its round-1
status, and the optional Stage 0 equal / not equal check of 4.1) are added only when round 2's test.json is in the pin
(5, 4.1); they read round 1's public select / picks / test files by their fixed paths and print labels only.
"""

from __future__ import annotations

import json
import math
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt_r2 import pin_r2 as PN  # noqa: E402

OUT_REL = "research/hunt_r2/out"
REPORT = "RESULTS_R2_KO.md"
R1_SELECT = "research/hunt/out/wide/select.json"
R1_PICKS = "research/hunt/out/wide/picks.json"
R1_TEST = "research/hunt/out/wide/test.json"
FAM_KO = {"F1": "새 3개", "F2": "규칙봇", "F3": "딥시크", "F5": "유명"}
GATE_KO = {"G1": "추세장만", "NONE": "문지기 없음"}
HURDLE_KO = {"taken": "통과", "failed (a′)": "탈락: 시각 밀기(a′)", "failed (b′)": "탈락: 동전(b′)",
             "failed both": "탈락: 둘 다", "not taken (below a failed rank)": "앞 순위 탈락으로 멈춤"}
SECRET = "비공개(딥시크)"
LINEUP_KO = {"정식": "정식", "참고": "참고", "excluded": "제외"}
LABEL_KO = {"edge of the coarse lattice": "눈금 끝(½배·2배)",
            "every coarse neighbour positive: yes": "옆 숫자 모두 플러스: 예",
            "every coarse neighbour positive: no": "옆 숫자 모두 플러스: 아니오",
            "same numbers as an F4 watch pick": "F4 관찰 후보와 같은 숫자",
            "same event list as another coarse point": "다른 점과 신호가 같음"}
BOARD_LABEL = "고르는 기간 성적, 골라서 부풀려진 값, 시험 아님"


def _load(path: str):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def mult(x, digits: int = 3) -> str:
    """A mean monthly ln M as a monthly multiple."""
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "-"
    return f"×{math.exp(x):.{digits}f}"


def m_(x, digits: int = 2) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "-"
    return f"×{x:.{digits}f}"


def pct(x, digits: int = 0) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "-"
    return f"{100 * x:.{digits}f}%"


def pv(x) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "-"
    return f"{x:.2g}" if x < 0.01 else f"{x:.3f}"


def num(v) -> str:
    if isinstance(v, (list, tuple)):
        return "(" + ",".join(num(x) for x in v) + ")"
    if isinstance(v, float) and v == int(v) and abs(v) < 1e6:
        return f"{v:g}"
    return f"{v:g}" if isinstance(v, float) else str(v)


def change(default: dict, peak) -> str:
    """'숫자 기본 → 찾은' for every number (unchanged numbers as one value)."""
    if not isinstance(peak, dict):
        return ", ".join(f"{k} {num(v)}" for k, v in default.items()) + " → 꼭대기 없음"
    parts = []
    for k, v in default.items():
        w = peak.get(k, v)
        parts.append(f"{k} {num(v)}" if json.dumps(v) == json.dumps(w) else f"**{k} {num(v)}→{num(w)}**")
    return ", ".join(parts)


def _is_ds(row: dict) -> bool:
    return row.get("family") == "F3" or row.get("kind") == "ds"


# ------------------------------------------------------------------ round-1 labels (after round 2's test.json hash)
def round1_labels(root: str, picks_pub: dict, private_dir: str | None = None) -> dict | None:
    """5: 'anchor default = round-1 system <id>' with its round-1 status; 4.1's optional Stage 0 check (equal / not
    equal per row). Only when round 2's test.json is in the pin; labels only."""
    if not PN.is_pinned(PN.TEST, root):
        return None
    sel = _load(os.path.join(root, R1_SELECT)) or {}
    pk1 = _load(os.path.join(root, R1_PICKS)) or {}
    t1 = _load(os.path.join(root, R1_TEST)) or {}
    rows1 = {r.get("id"): r for r in sel.get("rows") or []}
    picks1 = {p.get("id") for p in pk1.get("picks") or []}
    tested1 = {p.get("id") for p in t1.get("picks") or []}
    passing1 = set((t1.get("verdict") or {}).get("passing") or [])
    out = {"anchor_default": {}, "stage0": None}
    for r in picks_pub.get("names") or []:
        rid = f"{r['family']}:{r['name']}:{r['anchor']['tf']}:{r['anchor']['gate']}"
        if not sel:
            st = "1차 고르기 파일 없음"
        elif rid in passing1:
            st = "1차 정식 통과"
        elif rid in tested1:
            st = "1차 시험함, 통과 못 함"
        elif rid in picks1:
            st = "1차 픽, 시험 안 함(묶음 규칙)"
        elif rid in rows1:
            st = "1차 후보(조건 충족), 픽 아님" if rows1[rid].get("eligible") else "1차 후보, 조건 미충족"
        else:
            st = "1차 파일에 없음"
        out["anchor_default"][r["name"]] = {"round1_id": rid, "status": st}
    tag = ((picks_pub.get("pin") or {}).get("pin_sha256") or "")[:16]
    real = os.path.join(private_dir, "parts", f"select_{tag}", "real") if private_dir and tag else None
    if sel and real and os.path.isdir(real):
        eq, neq, missing = 0, [], 0
        for r in picks_pub.get("names") or []:
            p = os.path.join(real, f"{r['name']}.pkl")
            if not os.path.exists(p):
                missing += 1
                continue
            with open(p, "rb") as fh:
                u = pickle.load(fh)
            for row in u["stage0"]:
                rid = f"{r['family']}:{r['name']}:{row['tf']}:{row['gate']}"
                r1 = rows1.get(rid)
                if r1 is None:
                    neq.append(rid)
                    continue
                same = (int(r1.get("n_positions", -1)) == int(row["n"]) and bool(r1.get("bust")) == bool(row["bust"]))
                if "score" in r1:
                    same = same and abs(float(r1["score"]) - float(row["S"])) <= 1e-12
                if same:
                    eq += 1
                else:
                    neq.append(rid)
        out["stage0"] = {"equal": eq, "not_equal": neq, "names_without_parts": missing,
                         "note": "DeepSeek rows compared on positions and bust only (their score is private)"}
    return out


# ------------------------------------------------------------------ sections
def sec_status(pk, pre, test, reads) -> list:
    done = [("고르기 (picks.json)", pk is not None), ("시험 전 읽기 (pretest_reads.json)", pre is not None),
            ("시험 (test.json)", test is not None), ("참고 분석 (reads_*.json)", bool(reads))]
    return ["## 0. 어디까지 끝났나", "", " · ".join(f"{n}: {'끝' if ok else '아직'}" for n, ok in done), ""]


def sec_verdict(pk, test) -> list:
    out = ["## 1. 판정", ""]
    if test is None:
        if pk is not None and not pk.get("picks"):
            out += ["**고르기에서 끝났습니다.** 운 거르기(가짜 탐색 400번)를 넘은 매매법이 없거나 확인 상자에서 모두 "
                    "빠졌습니다. 2024~2026 시험 기간은 한 번도 쓰지 않았고 장부에 더한 가설도 없습니다.", ""]
        else:
            out += ["시험 판정은 아직 없습니다.", ""]
        return out
    v = test["verdict"]
    if not test.get("picks"):
        out += ["**고르기에서 끝났습니다.** 시험 기간은 쓰지 않았습니다(장부 가설 없음).", ""]
        return out
    out += [f"* **① 2차 통과 (R2 PASS): {'예' if v['r2_pass'] else '아니오'}**"
            + (f" — 통과 {len(v['passing'])}개: " + ", ".join(v["passing"]) if v["passing"] else ""),
            f"* **② 커스텀이 기본값을 이김 (TUNED BETTER): {'예' if v['tuning_beat_textbook'] else '아니오'}**"
            + (f" — {len(v['tuned_better'])}개: " + ", ".join(v["tuned_better"]) if v["tuned_better"] else ""),
            "* 시험한 묶음: " + ", ".join("{} ({}개 통과 / {}개)".format(b["label"], b["passes"], b["K"])
                                        for b in v["batches"])
            + f"; 시험 안 한 픽 {len(v['untested'])}개(앞 묶음 통과 5개 미만이면 다음 묶음은 시험하지 않음)",
            "* ①만 통과하고 ②를 못 넘으면 \"매매법은 괜찮지만 숫자를 바꾼 덕은 아님\"입니다.",
            "* 1차(v1, 와이드), 2번 트랙, 2차, 풀그리드 네 연구가 같은 33개월(2024-01~2026-09)을 봅니다. 판정은 나란히 "
            "보여 드리고 합치지 않습니다.", ""]
    gate = (test.get("ledger") or {}).get("round2_live_gate") or {}
    if gate:
        out += ["* 실제 돈 조건(장부 (L) 통과): " + ", ".join(f"{k}: {g['label']}" for k, g in gate.items()), ""]
    return out


def sec_names(pk, r1lab) -> list:
    out = ["## 2. 매매법마다 \"기본값 → 찾은 값\" (85개 모두)", "",
           "굵은 글씨가 바뀐 숫자입니다. 고원 점수는 2021~2023 월평균 배수로 쓴 꼭대기 점수(찾은 값 / 기본값)입니다. "
           "딥시크는 숫자·순위·표시만 공개합니다.", "",
           "| 묶음 | 매매법 | 기준 자리 | 기본값 → 찾은 값 | 후보 | 순위 | 운 거르기 | 확인 상자 | 고원 점수 (찾은/기본) | 표시 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in pk.get("names") or []:
        a = r["anchor"]
        box = r.get("box")
        bx = "-" if not box else ("통과" if box.get("plateau") else "빠짐: 점 사이 튐")
        if _is_ds(r):
            score = SECRET
        else:
            score = f"{mult(r.get('P_c_peak'))} / {mult(r.get('P_c_default'))}"
        lab = [LABEL_KO.get(x, x) for x in r.get("labels") or [] if x != "old six not blind"]
        if "pick_no" in r:
            lab = [f"픽 {r['pick_no']} ({r['batch']}군)"] + lab
        if r1lab and r["name"] in r1lab.get("anchor_default", {}):
            x = r1lab["anchor_default"][r["name"]]
            lab.append(f"기준 기본값 = 1차 시스템 {x['round1_id']} ({x['status']})")
        out.append(f"| {FAM_KO.get(r['family'], r['family'])} | {r['name']} | {a['tf']} {GATE_KO.get(a['gate'], a['gate'])}"
                   f" | {change(r['default'], r['peak'])} | {'예' if r.get('candidate') else '아니오'} | "
                   f"{r.get('rank') or '-'} | {HURDLE_KO.get(r.get('hurdle'), r.get('hurdle') or '-')} | {bx} | {score} | "
                   f"{'; '.join(lab) if lab else '-'} |")
    sc = pk.get("stage_counts") or {}
    out += ["", f"단계별 개수: 매매법 {sc.get('names')}, 기준 자리 시스템 {sc.get('stage0_systems')}, 넓게 본 점 "
                f"{sc.get('stage_a_points')}, 꼭대기 있음 {sc.get('with_peak')}, 후보 {sc.get('candidates')}, 운 거르기 통과 "
                f"{sc.get('taken')}, 확인 상자 {sc.get('boxes_checked')}(빠짐 {sc.get('boxes_failed')}), 픽 {sc.get('picks')}. "
                "모든 줄에 '옛 6코인은 이미 본 자료' 표시가 붙습니다(1차와 같음).", ""]
    return out


def sec_test(test) -> list:
    out = ["## 3. 시험 결과 (2024-01~2026-09, 한 번)", ""]
    if test is None or not test.get("picks"):
        return out + ["시험한 픽이 없습니다.", ""]
    out += ["| 픽 | 매매법 | 자리 | 판정 | 월평균 | 중앙 월 | 최대 낙폭 | 포지션 | 비용 2배 | 가짜와 비교 (a / b / 묶은 동전 / 밀기) | p | "
            "커스텀 vs 기본값 | 줄 세우기 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    lineup = (test.get("lineup") or {}).get("picks", {})
    for p in test["picks"]:
        blk = test["results"][p["id"]]
        c, tu = blk["checks"], blk.get("tune") or {}
        fails = [k for k in ("P0", "P1", "P3", "P4") if not c.get(k)] + \
            [f"순위 {k}" for k in ("a", "b", "bc", "ac") if not c.get(f"rank_ok_{k}")] + \
            ([] if c.get("bh_significant") else ["BH"])
        verdict = "**통과**" if c.get("PASS") else "불통과(" + ", ".join(fails) + ")"
        lab = (tu.get("label") or {}).get("ko", "-")
        ln = LINEUP_KO.get((lineup.get(p["id"]) or {}).get("lineup"), "-")
        if _is_ds(p):
            oks = " / ".join("예" if c.get("rank_ok_" + k) else "아니오" for k in ("a", "b", "bc", "ac"))
            out.append(f"| {p.get('pick_no')} | {p['name']} | {p['tf']} {p['gate']} | {verdict} | {SECRET} | | | "
                       f"{blk['base'].get('n_positions', '-')} | | {oks} | {SECRET} | {lab} | {ln} |")
            continue
        b, c2 = blk["base"], blk["cost2"]
        ranks = " / ".join(pv(c.get(f"rank_p_{k}")) for k in ("a", "b", "bc", "ac"))
        ci = tu.get("ci90_mean_d_tune") or [None, None]
        tune = f"{lab} (월 {mult(tu.get('mean_d_tune'), 4)}, 90% {mult(ci[0], 4)}~{mult(ci[1], 4)})"
        out.append(f"| {p.get('pick_no')} | {p['name']} | {p['tf']} {p['gate']} | {verdict} | {mult(b.get('mean_lnM'))} | "
                   f"{m_(b.get('median_M'), 3)} | {pct(b.get('max_dd'))} | {b.get('n_positions')} | {mult(c2.get('mean_lnM'))} | "
                   f"{ranks} | {pv(c.get('p'))} | {tune} | {ln} |")
    out += ["", "판정 기준: 포지션 월 2개 이상·80% 달에 포지션·파산 없음(P0), 중앙 월 배수 ≥ 1과 월평균 > 1(P1), 비용 2배에서도(P3), "
                "최대 낙폭 50% 미만(P4), 가짜 매매 4가지 각각 상위 5% 안(순위), 10개 묶음 우연 보정 BH q = 0.10. "
                "\"커스텀 vs 기본값\"은 같은 자리 기본 숫자와의 달별 차이입니다.", ""]
    return out


def sec_ledger(test) -> list:
    out = ["## 4. 프로그램 전체 장부", ""]
    lg = (test or {}).get("ledger")
    if not lg:
        return out + ["시험 때 함께 계산합니다(아직 없음).", ""]
    names = {"A": "시험한 것", "A+": "시험한 것 + 풀그리드 711개 + F4 관찰 38개", "L": "실제 돈 문턱(아직 안 돈 시험을 최대 개수로)"}
    for k in ("A", "A+", "L"):
        pr = lg["prints"][k]
        out.append(f"* ({k}) {names[k]}: 가설 {pr['m']}개, BH 통과 {len(pr['bh_rejections'])}개, Holm 통과 "
                   f"{len(pr['holm_rejections'])}개")
    out += [f"* 같은 시험 기간을 본 횟수(looks): {lg.get('looks_count')}", f"* {lg.get('line', '')}", ""]
    return out


def _cell(x: dict | None, ds: bool) -> str:
    if not x:
        return "-"
    if "removed" in x:
        return "신호 코드 오류로 빠짐"
    if ds:
        return f"{x.get('positions', '-')}회"
    return f"{mult(x.get('S'))} / 중앙 {m_(x.get('median_M'), 3)} / {x.get('positions')}회 / 낙폭 {pct(x.get('max_dd'))} / 비용2배 {mult(x.get('S2'))}"


def sec_reference(pre) -> list:
    out = ["## 5. 2021~2023 참고 표 (" + BOARD_LABEL + ")", ""]
    if pre is None:
        return out + ["시험 전 읽기(pretest)가 끝나면 채워집니다.", ""]
    t4 = pre.get("four_timeframes") or {}
    out += ["### 5.1 봉 4가지 × 주말 포함/제외 (모든 매매법, 기준 자리의 문지기)", "",
            "칸: 월평균 배수 / 중앙 월 배수 / 포지션 수 / 최대 낙폭 / 비용 2배 월평균. 딥시크는 포지션 수만.", "",
            "| 매매법 | 봉 | 숫자 | 주말 포함 | 주말 제외 (O1) | 주말 롱만 제외 (O1b) |", "|---|---|---|---|---|---|"]
    for nm, t in (t4.get("rows") or {}).items():
        ds = t.get("family") == "F3"
        for tf, by in (t.get("timeframes") or {}).items():
            for which in ("at_default", "at_peak"):
                x = by.get(which)
                if x is None:
                    continue
                anchor = " (기준)" if tf == t.get("anchor_tf") else ""
                out.append(f"| {nm} | {tf}{anchor} | {'기본값' if which == 'at_default' else '찾은 값'} | "
                           f"{_cell(x.get('base'), ds)} | {_cell(x.get('O1'), ds)} | {_cell(x.get('O1b'), ds)} |")
    agg = t4.get("aggregates_F1_F2_F5") or {}
    if agg:
        out += ["", "### 5.2 묶음별 요약 (새 3개 F1, 규칙봇 F2, 유명 F5; 딥시크 제외)", "",
                "| 묶음 | 봉 | 숫자 | 주말 포함: 매매법 수 / 월평균 중앙값 / 플러스 비율 | 주말 제외 (O1) | 롱만 제외 (O1b) |",
                "|---|---|---|---|---|---|"]
        for fam, by_tf in agg.items():
            for tf, by_w in by_tf.items():
                for which, by_v in by_w.items():
                    cells = []
                    for v in ("base", "O1", "O1b"):
                        a = by_v.get(v)
                        cells.append("-" if not a else f"{a['names']}개 / {mult(a['median_S'])} / {pct(a['share_S_above_0'])}")
                    out.append(f"| {FAM_KO.get(fam, fam)} | {tf} | {'기본값' if which == 'at_default' else '찾은 값'} | "
                               + " | ".join(cells) + " |")
    board = pre.get("owner_board") or {}
    if board:
        out += ["", "### 5.3 상위 10개 후보: 찾은 값 vs 기본값 (배수만)", "",
                "| 순위 | 매매법 | 숫자 | 한 달 x5 닿은 달 비율 (목표판, r 5%) | 가짜 a / b | 고른 크기 | 20배 / 30배 / 40배 x5 닿은 비율 | "
                "주말 포함 / 제외 / 롱만 제외 월평균 | 커스텀 − 기본 (월, 90%) |", "|---|---|---|---|---|---|---|---|---|"]
        for key, e in sorted(board.items(), key=lambda kv: (kv[1].get("rank") or 99, kv[1].get("which") != "peak")):
            if e.get("family") == "F3" or "note" in e:
                out.append(f"| {e.get('rank')} | {e.get('name')} | {'찾은 값' if e.get('which') == 'peak' else '기본값'} | "
                           f"{SECRET} | | | | | |")
                continue
            h = e.get("headline") or {}
            ca, cb = h.get("control_a") or {}, h.get("control_b") or {}
            r24 = e.get("r24") or {}
            lev = " / ".join(pct(((r24.get(f"L|{L_}x") or {}).get("shares") or {}).get("touch_x5")) for L_ in (20, 30, 40))
            wk = e.get("weekend") or {}
            wks = " / ".join(mult((wk.get(v) or {}).get("S")) for v in ("base", "O1", "O1b"))
            cmd = e.get("custom_minus_default")
            cm = "-" if not cmd else f"{mult(cmd['mean_d'], 4)} ({mult(cmd['ci90'][0], 4)}~{mult(cmd['ci90'][1], 4)})"
            fx = (e.get("size_fixed_on_select") or {}).get("cell") or "-"
            out.append(f"| {e.get('rank')} | {e.get('name')} | {'찾은 값' if e.get('which') == 'peak' else '기본값'} | "
                       f"{pct((h.get('shares') or {}).get('touch_x5'))} | {pct(ca.get('control_pooled'))} / "
                       f"{pct(cb.get('control_pooled'))} | {fx} | {lev} | {wks} | {cm} |")
    out.append("")
    return out


def sec_pretest(pre) -> list:
    out = ["## 6. 시험 전 읽기 요약 (2021~2023만, 아무것도 고르지 않음)", ""]
    if pre is None:
        return out + ["아직 없음.", ""]
    cs = (pre.get("cscv") or {}).get("strict") or {}
    if "pbo" in cs:
        out.append(f"* 과적합 확률(CSCV PBO, 기준 자리 고정 안 함): {pct(cs.get('pbo'))}; 기준 자리 고정판: "
                   f"{pct(((pre.get('cscv') or {}).get('fixed') or {}).get('pbo'))}")
    lf = (pre.get("lift_2023") or {}).get("strict") or {}
    if "median_lift" in lf:
        out.append(f"* 2023 이득(2021~22로 고르고 2023에 잼): 중앙값 {mult(lf.get('median_lift'), 4)}, 플러스 비율 "
                   f"{pct(lf.get('share_above_0'))}")
    lo = (pre.get("leave_one_year_out") or {}).get("strict") or {}
    if "share_returning_3_of_3" in lo:
        out.append(f"* 한 해 빼고 고르기: 세 번 모두 같은 꼭대기(또는 옆)로 돌아온 매매법 비율 {pct(lo.get('share_returning_3_of_3'))}")
    ns = (pre.get("null_summary") or {}).get("nulls") or {}
    for k, nm in (("a", "시각 밀기"), ("b", "동전")):
        x = ns.get(k) or {}
        if "N_eff" in x:
            out.append(f"* 가짜 탐색({nm}): 반복당 후보 평균 {x['candidates_per_replicate']['mean']:.1f}개, 실효 시도 수 "
                       f"N_eff {x['N_eff'] if x['N_eff'] is None else round(x['N_eff'])}")
    nmiss = pre.get("near_miss") or []
    if nmiss:
        out.append("* 아깝게 빠진 것: " + "; ".join(f"{r['name']} ({r['failed']})" for r in nmiss[:20]))
    mc = ((pre.get("momentum_c_prime") or {}).get("candidates") or {})
    mo = [nm for nm, e in mc.items() if e.get("label")]
    if mc:
        out.append(f"* 단순 모멘텀(최근 20봉 방향)보다 낫지 않은 후보: {', '.join(mo) if mo else '없음'}")
    wm = (pre.get("weekend_map") or {}).get("candidates") or []
    if wm:
        out.append(f"* 주말 빼고 다시 골랐다면: 후보 {len(wm)}개 (같은 꼭대기 {sum(1 for x in wm if x['same_peak_as_selection'])}개); "
                   "시험하지 않음")
    return out + [""]


def sec_reads(reads: dict, test) -> list:
    out = ["## 7. 참고 분석 (판정 뒤, 통과 기준 아님)", ""]
    if not reads:
        return out + ["아직 없음.", ""]
    rr = ((reads.get("reads_rows.json") or {}).get("out") or {}).get("rows") or {}
    for rid, r in rr.items():
        if "note" in r:
            out.append(f"* {rid}: {SECRET} (표시: {', '.join(r.get('labels') or []) or '-'})")
            continue
        r1 = (r.get("r1_line") or {}).get("checks") or {}
        out.append(f"* {rid}: 새 24코인만 시험 기간 월평균 {mult(((r.get('new24') or {}).get('test') or {}).get('mean_lnM'))}; "
                   f"1% 크기 P0~P4 {'모두 예' if all(r1.get(k) for k in ('P0', 'P1', 'P3', 'P4')) else '아님'}; "
                   f"기본값과 달별 상관(시험) {pv((r.get('corr_with_anchor_default') or {}).get('test'))}; "
                   f"표시: {', '.join(r.get('labels') or []) or '-'}")
    wk = ((reads.get("reads_weekend.json") or {}).get("out") or {}).get("rows") or {}
    for rid, r in wk.items():
        if "note" in r:
            continue
        t = ((r.get("periods") or {}).get("test") or {})
        out.append(f"* {rid} 주말: 시험 기간 주말 포함 {mult((t.get('base') or {}).get('mean_lnM'))}, 주말 제외 "
                   f"{mult((t.get('O1') or {}).get('mean_lnM'))}, 롱만 제외 {mult((t.get('O1b') or {}).get('mean_lnM'))}"
                   + ("; 모멘텀만으로도 비슷함" if r.get("momentum_only") else ""))
    st = (reads.get("reads_status.json") or {}).get("status") or {}
    left = [k for k, v in st.items() if v != "written"]
    if left:
        out.append("* 끝나지 않은 참고 분석: " + ", ".join(f"{k} ({st[k]})" for k in left))
    out += ["", "주말·크기·모멘텀 같은 규칙은 여기서 정하지 않습니다. 정하려면 다음 라운드에서 앞으로의 자료로만 확인합니다.", ""]
    return out


def build(root: str = ROOT, private_dir: str | None = None) -> str:
    out_dir = os.path.join(root, OUT_REL)
    pk = _load(os.path.join(out_dir, "picks.json"))
    pre = _load(os.path.join(out_dir, "pretest_reads.json"))
    test = _load(os.path.join(out_dir, "test.json"))
    reads = {}
    for f in ("reads_rows.json", "reads_weekend.json", "reads_goal.json", "reads_status.json"):
        d = _load(os.path.join(out_dir, f))
        if d is not None:
            reads[f] = d
    lines = ["# 1번 트랙 2차 (커스텀값) 결과", "",
             "자동으로 쓴 결과 페이지입니다. 규칙 원문: `PREREG_HUNT_R2.md`, 쉬운 설명: `README_R2_KO.md`. 딥시크 매매법은 "
             "숫자·순위·표시만 공개하고 돈 숫자는 비공개 파일에 둡니다.", ""]
    lines += sec_status(pk, pre, test, reads)
    lines += sec_verdict(pk, test)
    if pk is not None:
        lines += sec_names(pk, round1_labels(root, pk, private_dir))
    lines += sec_test(test)
    lines += sec_ledger(test)
    lines += sec_reference(pre)
    lines += sec_pretest(pre)
    lines += sec_reads(reads, test)
    r1 = round1_labels(root, pk, private_dir) if pk is not None else None
    if r1 and r1.get("stage0"):
        s0 = r1["stage0"]
        lines += ["## 8. 1차와 같은지 (자동 확인, 2차 test.json 고정 뒤)", "",
                  f"기준 자리 시스템 줄: 같음 {s0['equal']}, 다름 {len(s0['not_equal'])} ({s0['note']})", ""]
    return "\n".join(lines) + "\n"


def write(root: str = ROOT, private_dir: str | None = None) -> str:
    path = os.path.join(root, OUT_REL, REPORT)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    txt = build(root, private_dir)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        fh.write(txt)
    os.replace(tmp, path)
    return path
