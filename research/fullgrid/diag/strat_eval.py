"""Korean evaluation of every strategy (after the results, reference only): why the custom values were picked, how
each strategy did from every angle the run's data allows, and a grade by fixed rules written at the top of the report.

    python research/fullgrid/diag/strat_eval.py ANA_DIR RESULTS_BRANCH_DIR OUT.md

ANA_DIR holds strat_report.json, strat_deep.json, landscape.json, regime_explore.json, gross_all.json (scratch
outputs of the diag scripts). DeepSeek money figures are hidden (D11): plus / minus and grown / shrunk / bust only.
"""

import csv
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import strat_md as SM  # noqa: E402

TFS = ("15m", "30m", "1h", "4h")
TFK = SM.TF_KO
MONTHS = {"select": 36, "test": 33, "extra": 12}
NEAR = ("check_test_trades", "check_test_positive", "check_test_beats_default", "check_extra_trades",
        "check_extra_positive")
PNAME = {"select": "2021~23", "test": "2024~26", "extra": "2020"}
DIM_KO = {"장세": "장세", "큰 흐름": "큰 흐름", "변동성": "변동성"}
STATE_KO = {("장세", "추세장"): "추세장", ("장세", "횡보장"): "횡보장", ("장세", "급변장"): "급변장",
            ("장세", "보통"): "보통장", ("큰 흐름", "위"): "상승장(일봉 EMA200 위)", ("큰 흐름", "아래"): "하락장(아래)",
            ("변동성", "작음"): "조용한 장", ("변동성", "보통"): "보통 변동", ("변동성", "큼"): "출렁이는 장"}


def load(path):
    return json.load(open(path)) if os.path.exists(path) else None


def profiles() -> dict:
    path = os.path.join(HERE, "..", "..", "strategy_profiles", "out_binance", "PROFILES.md")
    out, cur = {}, None
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^## (.+) \(([A-Z0-9_]+)\)$", line.strip())
        if m:
            cur = m.group(2)
        elif cur and line.startswith("- 성격:"):
            out[cur] = line[len("- 성격:"):].strip().replace("**", "")
    return out


class H:
    """Formatting that hides DeepSeek money (D11)."""

    def __init__(self, hide: bool):
        self.hide = hide

    def m(self, v, nd=2) -> str:
        if v is None:
            return "—"
        if self.hide:
            return "플러스" if v > 0 else "마이너스"
        return f"{v * 100:+.{nd}f}%"

    def acct(self, a) -> str:
        if not a:
            return "거래 없음"
        if a.get("bust"):
            return "파산"
        if self.hide:
            return "늘어남" if a["final_x"] > 1 else "줄어듦"
        return f"${5000 * a['final_x']:,.0f}"

    def acct_dd(self, a) -> str:
        s = self.acct(a)
        if not a or self.hide or a.get("bust"):
            return s
        return f"{s} (낙폭 {a['max_dd'] * 100:.0f}%)"


def per_month(n, period) -> str:
    return f"{n / MONTHS[period]:.1f}" if n else "0"


def risk_text(a, h: H) -> str:
    if not a:
        return "—"
    parts = [f"연속 손실 최장 {a.get('losing_run', 0)}번"]
    wm = a.get("worst_month")
    if wm and not h.hide:
        parts.append(f"최악의 달 {wm['month']} {wm['change'] * 100:+.0f}%")
    uw = a.get("under_water")
    if uw:
        parts.append(f"손실 회복 {uw['days']:.0f}일" + (" (끝까지 회복 못 함)" if uw.get("open") else ""))
    if a.get("liquidations"):
        parts.append(f"강제청산 {a['liquidations']}번")
    return ", ".join(parts)


def grade(fam: dict, watch: set, name: str) -> tuple:
    if name in watch:
        return "★★★", "관찰 후보"
    if fam["nm"] > 0:
        return "★★", "약한 단서"
    if fam["picks"] > 0:
        return "★", "근거 없음"
    return "✕", "고를 값도 없음"


def family(rows: list) -> dict:
    ok = [r for r in rows if r["check_test_trades"] == "True"]
    nm = [r for r in rows if all(r[c] == "True" for c in NEAR)]
    ps = [float(r["test_p"]) for r in ok if r["test_p"]]
    return {"picks": len(rows), "ok": len(ok), "nm": len(nm), "nm_tfs": sorted({r["tf"] for r in nm}, key=TFS.index),
            "tp": sum(r["check_test_positive"] == "True" for r in ok),
            "ep": sum(r["check_extra_positive"] == "True" for r in ok), "minp": min(ps) if ps else None}


def verdict_default(rep: dict, h: H) -> str:
    accs = [rep[t]["default"]["account"].get("test") for t in TFS if rep.get(t)]
    accs = [a for a in accs if a]
    if not accs:
        return "지금 숫자로는 신호가 거의 나오지 않았습니다."
    bust = sum(a["bust"] for a in accs)
    up = sum((a["final_x"] > 1) and not a["bust"] for a in accs)
    return (f"지금 숫자(규칙봇)로는 시험 기간 계좌 {len(accs)}개 중 파산 {bust}개, 줄어듦 {len(accs) - bust - up}개, "
            f"늘어남 {up}개였습니다.")


def side_line(sd: dict, h: H) -> str:
    out = []
    for pn in ("test", "extra"):
        s = sd.get(pn) if sd else None
        if not s or not s.get("n"):
            continue
        if h.hide:
            better = "고른 방향이 나음" if s["chosen"] > s["opposite"] else "반대 방향이 나음"
            out.append(f"{PNAME[pn]} {better}")
        else:
            out.append(f"{PNAME[pn]} 고른 방향 {s['chosen'] * 100:+.2f}% / 반대 {s['opposite'] * 100:+.2f}%")
    return " · ".join(out) if out else "—"


def table_specs(name, rep, deep, gross, h: H, key: str) -> list:
    head = ("| 봉 | 한 달 신호 (24~26) | 승률 24~26 | 손익비 24~26 | 거래당 21~23 | 거래당 24~26 | 거래당 2020 | "
            + ("수수료 0이면 24~26 | " if key == "default" else "")
            + "계좌 24~26 | 계좌 1/4 크기 24~26 | 계좌 21~23 | 계좌 2020 |")
    sep = "|---" * (head.count("|") - 1) + "|"
    rows = [head, sep]
    for tf in TFS:
        r, d = rep.get(tf), deep.get(tf)
        sp = r.get(key) if r else None
        if not sp:
            rows.append(f"| {TFK[tf]} | {'고를 값 없음' if key == 'pick' else '계산 없음'} |" + " |" * (head.count("|") - 3))
            continue
        p = sp["periods"]
        dp = d.get(key) if d else None
        acc = (dp or {}).get("accounts") or {}
        cells = [TFK[tf], per_month(p["test"].get("n", 0), "test"),
                 f"{p['test']['win'] * 100:.0f}%" if p["test"].get("n") else "—",
                 SM.Fmt(h.hide).payoff(p["test"]), h.m(p["select"].get("mean")), h.m(p["test"].get("mean")),
                 h.m(p["extra"].get("mean"))]
        if key == "default":
            g = gross.get((tf,)) if gross else None
            cells.append(h.m(g["test"][1] / g["test"][0]) if g and g["test"][0] else "—")
        q = (acc.get("test") or {}).get("quarter")
        cells += [h.acct_dd(sp["account"].get("test")), h.acct_dd(q) if q else "—",
                  h.acct(sp["account"].get("select")), h.acct(sp["account"].get("extra"))]
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def years_table(rep, deep, h: H) -> list:
    yrs = [str(y) for y in range(2020, 2027)]
    rows = ["| 봉 · 값 | " + " | ".join(yrs) + " |", "|---" * 8 + "|"]
    for tf in TFS:
        d = deep.get(tf)
        for key, lab in (("default", "지금 숫자"), ("pick", "커스텀값")):
            sp = d.get(key) if d else None
            if not sp:
                continue
            cells = []
            for y in yrs:
                v = sp["years"][y]
                cells.append("—" if v["n"] < 10 else f"{h.m(v['mean'], 1)} ({v['n']})")
            rows.append(f"| {TFK[tf]} {lab} | " + " | ".join(cells) + " |")
    return rows


def landscape_lines(name, kind, land, h: H) -> list:
    out = []
    for tf in TFS:
        L = land.get(f"{kind}|{name}|{tf}")
        if not L:
            continue
        g = L["grid"]
        if g.get("hidden"):
            out.append(f"- {TFK[tf]}: 커스텀값 {g['combos']:,}개 (딥시크는 결과 파일에 돈 숫자가 없어 지형 분석 불가, D11)")
            continue
        if not g.get("eligible"):
            out.append(f"- {TFK[tf]}: 커스텀값 {g['combos']:,}개 중 두 기간 거래 수 기준을 넘은 값 없음")
            continue
        rho = g.get("rho_select_test")
        rho_t = "—" if rho is None else f"{rho:+.2f}"
        dpos = ""
        if g.get("default_pct_select") is not None:
            dpos = (f", 지금 숫자는 고르는 기간 상위 {100 - g['default_pct_select'] * 100:.0f}% · "
                    f"시험 기간 상위 {100 - g['default_pct_test'] * 100:.0f}%")
        out.append(f"- {TFK[tf]}: 커스텀값 {g['combos']:,}개 중 기준 통과 {g['eligible']:,}개. 두 기간 다 플러스 "
                   f"{g['pos_both'] * 100:.1f}% (고르는 기간만 {g['pos_select'] * 100:.0f}%, 시험 기간만 "
                   f"{g['pos_test'] * 100:.0f}%). 순위 이어짐 {rho_t}. 고르는 기간 상위 5%의 시험 기간 중앙값 "
                   f"{h.m(g['top5_test_median'])} (전체 {h.m(g['test_median'])}){dpos}.")
        good = []
        for p in g.get("params", []):
            if not p["values"]:
                continue
            bs = max(p["values"], key=lambda v: v["select"])
            bt = max(p["values"], key=lambda v: v["test"])
            agree = p.get("agree")
            ag = "—" if agree is None else f"{agree:+.2f}"
            good.append(f"{p['param']}: 고르는 기간 {fmt_val(bs['value'])} / 시험 기간 {fmt_val(bt['value'])} "
                        f"(지금 {fmt_val(p['default'])}, 일치도 {ag})")
        if good:
            out.append("  - 숫자별로 가장 좋았던 값: " + "; ".join(good))
    return out


def fmt_val(v) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, list):
        return "(" + ", ".join(fmt_val(x) for x in v) + ")"
    return str(v)


def exits_lines(name, kind, land, h: H) -> list:
    out = []
    for tf in TFS:
        L = land.get(f"{kind}|{name}|{tf}")
        if not L:
            continue
        e = L["exits"]
        if e.get("hidden"):
            out.append(f"- {TFK[tf]}: (딥시크, 돈 숫자 없음)")
            continue
        if not e.get("top_select"):
            out.append(f"- {TFK[tf]}: 거래 수 기준을 넘은 청산 방식이 3개 미만")
            continue
        tops = "; ".join(f"{SM.exit_ko(t['exit'])} → 시험 {h.m(t['test'])}" for t in e["top_select"])
        live = (f", 지금 청산은 고르는 기간 {e['live_rank_select']}위 · 시험 기간 {e['live_rank_test']}위"
                if e.get("live_rank_select") else "")
        rho = e.get("rho_select_test")
        out.append(f"- {TFK[tf]}: 고르는 기간 1~3등 = {tops}. 시험 기간 1등 = {SM.exit_ko(e['best_test']['exit'])} "
                   f"({h.m(e['best_test']['test'])}). 시험 기간 플러스인 청산 {e['pos_test']}/{e['eligible']}개"
                   f"{live}. 순위 이어짐 {'—' if rho is None else f'{rho:+.2f}'}.")
    return out


def state_summary(rep, key, h: H) -> list:
    out = []
    for tf in TFS:
        sp = rep.get(tf, {}).get(key) if rep.get(tf) else None
        if not sp:
            continue
        cells = []
        for d, sts in sp["states"].items():
            for s, v in sts.items():
                if v.get("n", 0) >= SM.MIN_N:
                    cells.append((v["mean"], STATE_KO.get((d, s), s)))
        coins = [(v["mean"], c[:-4]) for c, v in sp["coins"].items() if v.get("n", 0) >= SM.MIN_N]
        if not cells:
            continue
        best, worst = max(cells), min(cells)
        pos = sum(m > 0 for m, _ in cells)
        txt = (f"- {TFK[tf]}: 장세 9칸 중 플러스 {pos}칸. 가장 좋은 곳 {best[1]} ({h.m(best[0], 1)}), "
               f"가장 나쁜 곳 {worst[1]} ({h.m(worst[0], 1)})")
        if coins:
            bc, wc = max(coins), min(coins)
            txt += f". 코인: 가장 좋음 {bc[1]} ({h.m(bc[0], 1)}), 가장 나쁨 {wc[1]} ({h.m(wc[0], 1)})"
        sides = sp["sides"]
        if sides["long"].get("n", 0) >= SM.MIN_N and sides["short"].get("n", 0) >= SM.MIN_N:
            txt += f". 롱 {h.m(sides['long']['mean'], 1)}, 숏 {h.m(sides['short']['mean'], 1)}"
        out.append(txt + ".")
    return out


def regime_lines(name, regx) -> list:
    out = []
    for tf in TFS:
        for tag, lab in (("default|ladder", "지금 숫자"), ("pick|1", "커스텀값 1등")):
            r = regx.get((tag, name, tf))
            if not r:
                continue
            bits = []
            for d, v in r["dims"].items():
                home = v["home"]
                if not home:
                    continue
                per = v["per"]
                rest = [s for s in per["test"] if s not in home]
                ni = sum(per["test"][s][0] for s in home)
                no = sum(per["test"][s][0] for s in rest)
                if ni < 20 or no < 20:
                    continue
                mi = sum(per["test"][s][1] for s in home) / ni
                mo = sum(per["test"][s][1] for s in rest) / no
                hk = "·".join(STATE_KO.get((d, s), s) for s in home)
                bits.append(f"{d} 강점 {hk} → 시험 기간 {'유지' if mi > mo else '사라짐'} ({mi * 100:+.1f}% vs 나머지 "
                            f"{mo * 100:+.1f}%)")
            if bits:
                out.append(f"- {TFK[tf]} {lab}: " + "; ".join(bits))
    return out


def selection_lines(name, kind, cells, cands, h: H) -> list:
    out = []
    for tf in TFS:
        c = cells.get((kind, name, tf))
        if not c:
            continue
        rows = [r for r in cands if r["kind"] == kind and r["name"] == name and r["tf"] == tf]
        allc = int(c["combos"]) * 84
        head = (f"- {TFK[tf]}: 커스텀값 {int(c['combos']):,}개 × 청산 84가지 = {allc:,}개 중 고르는 기간 거래 150건 이상 "
                f"{int(c['with_min_trades']):,}개, 그중 언덕 점수 플러스 {int(c['plateau_positive']):,}개 → 고른 값 {len(rows)}개")
        out.append(head)
        for r in sorted(rows, key=lambda r: int(r["rank"])):
            marks = " · ".join(f"{lab} {'O' if r[k] == 'True' else 'X'}" for lab, k in (
                ("시험 플러스", "check_test_positive"), ("지금보다 나음", "check_test_beats_default"),
                ("우연 보정", "check_test_fdr"), ("2020 플러스", "check_extra_positive")))
            p = f", p {float(r['test_p']):.3f}" if r["test_p"] else ""
            nums = ""
            if not h.hide and r["select_mean"]:
                nums = (f" (고르는 기간 {float(r['select_mean']) * 100:+.2f}%, 시험 {float(r['test_mean']) * 100:+.2f}%, "
                        f"2020 {float(r['extra_mean']) * 100:+.2f}%)" if r["extra_mean"] and r["test_mean"] else "")
            out.append(f"  - {r['rank']}등: {SM.combo_ko(r['combo'])} / {SM.exit_ko(r['exit'])}{nums} — {marks}{p}")
    return out


def summary_bullets(name, kind, fam, rep, deep, land, h: H) -> list:
    out = [f"- 고른 커스텀값 {fam['picks']}개 중 우연 보정만 빼고 다 통과 {fam['nm']}개"
           + (f" ({', '.join(TFK[t] for t in fam['nm_tfs'])})" if fam["nm_tfs"] else "")
           + (f", 가장 좋은 시험 p {fam['minp']:.3f}" if fam["minp"] is not None else "") + "."]
    out.append("- " + verdict_default(rep, h))
    sk = []
    for tf in TFS:
        d = deep.get(tf)
        if d and d.get("pick"):
            s = d["pick"]["sides"]
            t, x = s.get("test") or {}, s.get("extra") or {}
            if t.get("n") and x.get("n"):
                sk.append((tf, t["chosen"] > t["opposite"], x["chosen"] > x["opposite"]))
    if sk:
        both = [TFK[tf] for tf, a, b in sk if a and b]
        out.append(f"- 커스텀값 1등이 같은 자리 반대 방향보다 시험 기간·2020년 모두 나았던 봉: "
                   f"{', '.join(both) if both else '없음'} ({len(sk)}개 봉 중).")
    rhos = [land.get(f"{kind}|{name}|{tf}", {}).get("grid", {}).get("rho_select_test") for tf in TFS]
    rhos = [r for r in rhos if r is not None]
    if rhos and not h.hide:
        out.append(f"- 커스텀값 순위가 다음 기간에도 이어진 정도(봉별 상관): {', '.join(f'{r:+.2f}' for r in rhos)} "
                   f"(0에 가까우면 고르는 기간 1등이 다음 기간에도 좋을 근거가 약함).")
    qs = []
    for tf in TFS:
        d = deep.get(tf)
        if d and d.get("pick") and (d["pick"]["accounts"].get("test") or {}).get("quarter"):
            full = rep[tf]["pick"]["account"].get("test")
            q = d["pick"]["accounts"]["test"]["quarter"]
            if full:
                qs.append(f"{TFK[tf]} {h.acct(full)} → 1/4 크기 {h.acct(q)}")
    if qs:
        out.append("- 커스텀값 1등 계좌(2024~26), 지금 크기 → 1/4 크기: " + "; ".join(qs) + ".")
    return out


def one_liner(gr: str, fam: dict, rep: dict, h: H) -> str:
    if gr == "★★★":
        return ("여러 봉에서 고른 커스텀값의 절반 이상이 시험 기간과 2020년 모두 플러스였습니다. 운 검사는 통과하지 못했으니 "
                "paper 관찰로 앞으로를 확인할 1순위입니다.")
    if gr == "★★":
        return ("일부 커스텀값이 시험 기간과 2020년 모두 플러스였지만 한두 봉에 그쳐, 운으로 나온 것과 구별하기 어렵습니다.")
    if gr == "★":
        return "고른 커스텀값 중 시험 기간과 2020년을 함께 넘은 것이 없습니다. 숫자를 바꿔도 근거가 보이지 않습니다."
    return "고르는 기간에 기준을 넘는 커스텀값조차 없었습니다."


def main(ana: str, res_dir: str, dst: str) -> None:
    rep_l = load(os.path.join(ana, "strat_report.json")) or []
    deep_l = load(os.path.join(ana, "strat_deep.json")) or load(os.path.join(ana, "strat_deep.part.json")) or []
    land = load(os.path.join(ana, "landscape.json")) or {}
    regx_l = load(os.path.join(ana, "regime_explore.json")) or []
    gross_l = load(os.path.join(ana, "gross_all.json")) or load(os.path.join(ana, "gross_all.part.json")) or []
    cands = list(csv.DictReader(open(os.path.join(res_dir, "candidates.csv"))))
    cells = {(c["kind"], c["name"], c["tf"]): c for c in csv.DictReader(open(os.path.join(res_dir, "cells.csv")))}
    watch = {r["name"] for r in json.load(open(os.path.join(HERE, "watch_sel.json")))}
    prof = profiles()
    cn = SM.core_names()
    rep, deep, gross = {}, {}, {}
    for r in rep_l:
        rep.setdefault((r["kind"], r["name"]), {})[r["tf"]] = r
    for r in deep_l:
        deep.setdefault((r["kind"], r["name"]), {})[r["tf"]] = r
    for r in gross_l:
        gross.setdefault((r["kind"], r["name"]), {})[(r["tf"],)] = r["x0"]
    regx = {}
    for r in regx_l:
        regx[(r["tag"], r["name"], r["tf"])] = r
    fams = {}
    for kind in ("core", "ds"):
        for n in sorted({c[1] for c in cells if c[0] == kind}):
            fams[(kind, n)] = family([r for r in cands if r["kind"] == kind and r["name"] == n])

    notes = load(os.path.join(HERE, "eval_notes_ko.json")) or {}
    out = intro(fams, watch, cn, rep, land, deep, gross_l, rep_l)
    out += priority(fams, watch, cn, rep, deep, land)
    for kind, title in (("core", "규칙봇 36개"), ("ds", "딥시크 44개")):
        h = H(kind == "ds" and not SM.DS_MONEY)
        labels = cn if kind == "core" else SM.DS_KO
        names = sorted([n for k, n in fams if k == kind],
                       key=lambda n: ("★★★ ★★ ★ ✕".split().index(grade(fams[(kind, n)], watch, n)[0]),
                                      labels.get(n, n)))
        out += [f"## {title}: 매매법별 평가", ""]
        for n in names:
            fam = fams[(kind, n)]
            gr, glab = grade(fam, watch, n)
            R_, D_ = rep.get((kind, n), {}), deep.get((kind, n), {})
            G_ = gross.get((kind, n), {})
            out += [f"### {gr} {labels.get(n, n)} ({n}) — {glab}", ""]
            if kind == "core" and n in prof:
                out += [f"성격: {prof[n]}", ""]
            out += [f"**한 줄 평가**: {one_liner(gr, fam, R_, h)}", ""]
            if notes.get(n):
                out += [f"**해석**: {notes[n]}", ""]
            out += ["**평가 이유**", ""]
            out += summary_bullets(n, kind, fam, R_, D_, land, h) + [""]
            out += ["**커스텀값을 어떻게 골랐나 (고르는 기간만 보고, 칸마다 최대 3개)**", ""]
            out += selection_lines(n, kind, cells, cands, h) + [""]
            out += ["**지금 숫자 (규칙봇 기본값, 손절 2 ATR · 계단 잠금)**", ""]
            out += table_specs(n, R_, D_, G_, h, "default") + [""]
            out += ["**커스텀값 1등**", ""] + table_specs(n, R_, D_, G_, h, "pick") + [""]
            risks = []
            for tf in TFS:
                for key, lab in (("default", "지금 숫자"), ("pick", "커스텀값")):
                    d = D_.get(tf, {}).get(key) if D_.get(tf) else None
                    if d and d["accounts"].get("test"):
                        risks.append(f"- {TFK[tf]} {lab}: {risk_text(d['accounts']['test'], h)}")
            if risks:
                out += ["**계좌 위험 (2024~26, 지금 크기)**", ""] + risks + [""]
            out += ["**연도별 거래당 (거래 수)**", ""] + years_table(R_, D_, h) + [""]
            sides = []
            for tf in TFS:
                for key, lab in (("default", "지금 숫자"), ("pick", "커스텀값")):
                    d = D_.get(tf, {}).get(key) if D_.get(tf) else None
                    if d:
                        sides.append(f"- {TFK[tf]} {lab}: {side_line(d['sides'], h)}")
            if sides:
                out += ["**방향 실력 (같은 진입 자리에서 고른 방향 vs 반대 방향)**", ""] + sides + [""]
            ll = landscape_lines(n, kind, land, h)
            if ll:
                out += ["**커스텀값 지형 (지금 청산으로 모든 커스텀값을 계산)**", ""] + ll + [""]
            el = exits_lines(n, kind, land, h)
            if el:
                out += ["**청산 방식 84가지 (지금 숫자)**", ""] + el + [""]
            for key, lab in (("default", "지금 숫자"), ("pick", "커스텀값 1등")):
                sl = state_summary(R_, key, h)
                if sl:
                    out += [f"**장세·코인·방향 ({lab}, 2021~26)**", ""] + sl + [""]
            if kind == "core":
                rl = regime_lines(n, regx)
                if rl:
                    out += ["**장세 강점이 다음 기간에도 유지됐나**", ""] + rl + [""]
            out += [f"전체 표: `STRATEGIES_KO.md`의 {labels.get(n, n)} 항목.", ""]
    open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")


def evidence(kind, n, fam, rep, deep, land) -> dict:
    side_both = q_up = q_n = 0
    for tf in TFS:
        d = deep.get((kind, n), {}).get(tf)
        if d and d.get("pick"):
            s = d["pick"]["sides"]
            t, x = s.get("test") or {}, s.get("extra") or {}
            if t.get("n") and x.get("n") and t["chosen"] > t["opposite"] and x["chosen"] > x["opposite"]:
                side_both += 1
            q = (d["pick"]["accounts"].get("test") or {}).get("quarter")
            if q:
                q_n += 1
                q_up += q["final_x"] > 1 and not q["bust"]
    rhos = [land.get(f"{kind}|{n}|{tf}", {}).get("grid", {}).get("rho_select_test") for tf in TFS]
    rhos = [r for r in rhos if r is not None]
    return {"ratio": fam["nm"] / max(fam["ok"], 1), "tfs": len(fam["nm_tfs"]), "side_both": side_both,
            "q": f"{q_up}/{q_n}", "q_up": q_up, "rho": st.median(rhos) if rhos else None}


def priority(fams, watch, cn, rep, deep, land) -> list:
    rows = []
    for (kind, n), f in fams.items():
        if n not in watch:
            continue
        e = evidence(kind, n, f, rep, deep, land)
        rows.append((e["ratio"] + 0.1 * e["tfs"] + 0.1 * e["side_both"] + 0.05 * e["q_up"], kind, n, f, e))
    rows.sort(reverse=True)
    out = ["## 4. 관찰 후보 16개 우선순위", "",
           "점수 = 다 통과 비율 + 0.1 × 다 통과가 나온 봉 수 + 0.1 × 반대 방향보다 두 기간 다 나았던 봉 수 + 0.05 × 1/4 크기로 "
           "시험 기간 계좌가 늘어난 봉 수. 순서를 정하기 위한 것이지 실력의 증거가 아닙니다.", "",
           "| 순위 | 매매법 | 다 통과 (고른 값) | 다 통과 봉 | 가장 좋은 p | 반대 방향보다 두 기간 다 나은 봉 | 1/4 크기 계좌 늘어남 | "
           "커스텀값 순위 이어짐 |", "|---|---|---|---|---|---|---|---|"]
    for i, (_sc, kind, n, f, e) in enumerate(rows, 1):
        lab = cn.get(n, n) if kind == "core" else SM.DS_KO.get(n, n) + " (딥시크)"
        rho = "—" if e["rho"] is None or kind == "ds" else f"{e['rho']:+.2f}"
        out.append(f"| {i} | {lab} | {f['nm']}/{f['ok']} | {', '.join(TFK[t] for t in f['nm_tfs'])} | "
                   f"{f['minp']:.3f} | {e['side_both']} | {e['q']} | {rho} |")
    out.append("")
    return out


def cost_line(gross_l: list, rep_l: list) -> str | None:
    parts = []
    for tf in TFS:
        g = [r for r in gross_l if r["kind"] == "core" and r["tf"] == tf]
        r = [x for x in rep_l if x["kind"] == "core" and x["tf"] == tf]
        n0 = sum(x["x0"]["test"][0] for x in g)
        s0 = sum(x["x0"]["test"][1] for x in g)
        n1 = sum(x["default"]["periods"]["test"].get("n", 0) for x in r)
        s1 = sum(x["default"]["periods"]["test"].get("sum", 0.0) for x in r)
        if n0 and n1:
            parts.append(f"{TFK[tf]} {s0 / n0 * 100:+.2f}% → {s1 / n1 * 100:+.2f}%")
    if not parts:
        return None
    return ("**수수료 전에는 거의 0, 수수료 뒤에는 크게 마이너스입니다.** 규칙봇 36개 지금 숫자를 모두 합친 시험 기간 거래당 "
            "(수수료 0 → 실제 수수료): " + ", ".join(parts) + ". 신호가 버는 몫보다 비용이 10배 넘게 큽니다.")


def intro(fams, watch, cn, rep, land, deep, gross_l=(), rep_l=()) -> list:
    counts = {}
    for (kind, n), f in fams.items():
        counts.setdefault(kind, {}).setdefault(grade(f, watch, n)[0], []).append(n)
    core_rho = [v["grid"]["rho_select_test"] for k, v in land.items()
                if k.startswith("core") and v["grid"].get("rho_select_test") is not None]
    exit_rho = [v["exits"]["rho_select_test"] for k, v in land.items()
                if k.startswith("core") and v["exits"].get("rho_select_test") is not None]
    pos_both = [v["grid"]["pos_both"] for k, v in land.items() if k.startswith("core") and "pos_both" in v["grid"]]
    out = ["# 매매법 80개 하나하나 평가 (5년 백테스트 전체 분석)", "",
           "결과를 본 뒤 만든 참고용 분석입니다. 통과·탈락(711개 중 0개)은 바뀌지 않습니다. 매매법마다 계산할 수 있는 것을 모두 "
           "계산해 같은 순서로 적었습니다. 숫자 표 전체는 `STRATEGIES_KO.md`, 연구 전체 결론은 `ANALYSIS_KO.md`에 있습니다.", "",
           "## 0. 읽는 법", "",
           "- **기간**: 2021~23 = 고르는 기간(커스텀값을 고를 때 본 기간), 2024~26 = 시험 기간(고를 때 안 본 기간, 2026-09까지), "
           "2020 = 추가 기간(역시 안 본 기간).",
           "- **거래당**: 신호 하나를 거래 하나로 셉니다. 거래 하나의 순손익(수수료·슬리피지·펀딩 포함)을 계좌 대비 %로 적었습니다.",
           "- **한 달 신호**: 시험 기간의 한 달 평균 신호 수입니다. 조건이 맞는 동안 봉마다 신호가 나는 매매법은 이 숫자가 매우 큽니다"
           "(한 달 수백~수천). 계좌는 한 번에 한 포지션만 들고 있어서 실제 거래 수는 훨씬 적습니다.",
           "- **계좌**: $5,000으로 시작해 한 번에 한 포지션, 복리, 규칙봇과 같은 레버리지·강제청산·파산을 적용했습니다. "
           "1/4 크기는 증거금 비율만 1/4로 줄인 것입니다(레버리지는 그대로).",
           "- **방향 실력**: 같은 진입 자리에서 반대로 들어갔다면 어땠는지와 비교합니다. 고른 방향이 반대보다 나아야 방향을 "
           "맞히는 힘이 있다고 봅니다.",
           "- **순위 이어짐**: 고르는 기간 성적 순위와 시험 기간 성적 순위가 얼마나 같은지(스피어만 상관, −1 ~ +1)입니다. 0 근처면 "
           "고르는 기간 1등이 다음 기간에도 좋을 근거가 약합니다.",
           "- **딥시크**는 두 분 결정 D11에 따라 돈 숫자를 가렸습니다(플러스/마이너스, 늘어남/줄어듦/파산만). 결과 파일에도 딥시크 "
           "돈 숫자가 없어서 커스텀값 지형과 청산 비교는 딥시크에 대해 할 수 없습니다.", "",
           "## 1. 왜 이 커스텀값과 매매법들을 골랐나", "",
           "**1단계, 계산 전에 고정한 규칙(`PREREG.md`)으로 커스텀값 고르기.** 칸(매매법 × 봉)마다:", "",
           "1. 커스텀값 전부 × 청산 84가지를 2021~2023년 데이터로만 계산합니다.",
           "2. 그 기간 거래가 150건 이상인 것만 남깁니다.",
           "3. **언덕 점수**(그 값과 바로 옆 값들의 거래당 중앙값)로 줄을 세웁니다. 혼자만 튀는 값은 뽑히지 않습니다.",
           "4. 지금 숫자·지금 청산의 언덕 점수보다 높은 것 중 상위 3개를 고릅니다.",
           "5. 고른 711개를 시험 기간과 2020년으로 확인합니다. 시험 거래 100건 이상, 시험 플러스, 지금 숫자보다 나음, 우연 보정"
           "(711개 전체 FDR 10%), 2020년 플러스를 **모두** 넘어야 통과입니다. 결과는 0개였습니다.", "",
           "**2단계, 결과를 본 뒤 관찰 후보 고르기(참고용).** 매매법 단위로 \"고른 커스텀값 6개 이상, 그중 절반 이상이 우연 보정만 "
           "빼고 다 통과\"인 매매법을 관찰 후보로 했습니다. 한 봉의 우연보다 여러 봉에서 꾸준한 쪽을 믿기 위해서입니다.", "",
           "**등급 기준**", "",
           "| 등급 | 뜻 | 기준 | 규칙봇 | 딥시크 |", "|---|---|---|---|---|"]
    rows = (("★★★", "관찰 후보", "위 2단계 기준을 넘음"), ("★★", "약한 단서", "우연 보정만 빼고 다 통과한 커스텀값이 1개 이상"),
            ("★", "근거 없음", "고른 커스텀값은 있으나 다 통과한 것 없음"), ("✕", "고를 값도 없음", "1단계 4번까지 넘은 값 없음"))
    for g, lab, rule in rows:
        out.append(f"| {g} | {lab} | {rule} | {len(counts.get('core', {}).get(g, []))} | "
                   f"{len(counts.get('ds', {}).get(g, []))} |")
    out += ["", "## 2. 전체에서 보이는 것", ""]
    if core_rho:
        out.append(f"1. **커스텀값 순위는 다음 기간으로 거의 이어지지 않습니다.** 규칙봇 칸마다 수천 개 커스텀값의 고르는 기간 "
                   f"순위와 시험 기간 순위의 상관은 중앙값 {st.median(core_rho):+.2f}입니다. 같은 계산을 청산 방식 84가지로 하면 "
                   f"{st.median(exit_rho):+.2f}입니다. 청산 방식의 효과는 기간이 바뀌어도 대체로 유지되지만, 숫자 고르기의 "
                   "효과는 대부분 그 기간의 운이었습니다.")
    if pos_both:
        out.append(f"2. **지금 청산으로는 두 기간 모두 플러스인 커스텀값 자체가 드뭅니다.** 규칙봇 칸의 중앙값이 "
                   f"{st.median(pos_both) * 100:.1f}%입니다.")
    cl = cost_line(list(gross_l), list(rep_l))
    if cl:
        out.append("3. " + cl)
    out += ["4. **방향 실력은 거의 0입니다.** 지금 숫자로는 고른 방향과 반대 방향의 차이가 비용보다 훨씬 작습니다"
            "(`ANALYSIS_KO.md` 5-4).",
            "5. **지금 크기(레버리지)가 계좌를 망가뜨립니다.** 거래당 플러스여도 지금 크기로는 계좌가 줄어든 경우가 많고, 1/4 "
            "크기로 줄이면 같은 거래로 계좌가 지켜진 경우가 많습니다. 아래 매매법마다 두 계좌를 같이 적었습니다.",
            "6. **계좌 금액 1등은 믿을 기준이 아닙니다.** 큰 이익 몇 번의 순서 운이 결과를 바꿉니다. 그래서 등급은 계좌 금액이 아니라 "
            "여러 기간·여러 봉에서의 거래당 일관성으로 매겼습니다.", ""]
    out += ["## 3. 등급표", "", "| 등급 | 규칙봇 | 딥시크 |", "|---|---|---|"]
    for g, _lab, _rule in rows:
        c = ", ".join(cn.get(n, n) for n in sorted(counts.get("core", {}).get(g, [])))
        d = ", ".join(SM.DS_KO.get(n, n) for n in sorted(counts.get("ds", {}).get(g, [])))
        out.append(f"| {g} | {c or '—'} | {d or '—'} |")
    out.append("")
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
