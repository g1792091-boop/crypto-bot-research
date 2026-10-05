"""Note builders of the Obsidian vault exporter, part 2: meetings, lessons and hypotheses, research, rules documents,
nightly checks. See paperbot/obsidian_notes.py for the framework and the honesty rules."""

from __future__ import annotations

import glob
import json
import math
import os
import re
from collections import Counter, defaultdict
from typing import Optional

from .agents.roster3 import STRATEGY_KO
from .obsidian_notes import (FOLDERS, LEGEND, WEEKLY_TRIGGERS, GROUPS, Ctx, Vault, check_name, day_ko, day_name, group_of,
                             hero, hyp_name, role_link, stat_row, status_ko, strat_link, strat_name, team_note, trigger_ko,
                             week_name, TEAM_NAME)
from .obsidian_sources import read_text, recorded_hash, sha256_file, split_account, split_sections
from .obsidian_util import (DAY_MS, badge, callout, fnum, iso_week, kst_day, kst_hm, kst_min, link, mean, mermaid, num,
                            pct, quote, safe_name, sanitize, small_flag, table, usd)

AI_KINDS = ("analysis", "challenge", "expert", "revision", "summary", "verdict")
CODE_SHOW = ("action", "code_result")
DAY_AI_BUDGET = 36_000          # characters of AI text per day note
MSG_CHARS = 700
ROUND_MSGS = 6
CONCL_CHARS = 520
MAX_HYP_NOTES = 200
DOC_BODY_CAP = 24_000
ID_RE = re.compile(r"\b((?:[SN]\d{1,2}|V\d{2})_[A-Z0-9_]+|OBV_[SB]|DOGE)\b")


def ids_in(text: str) -> set:
    return {m for m in ID_RE.findall(text or "") if m in STRATEGY_KO}


# ================================================================== prepare (mentions, research docs)
RESEARCH_MAP = [
    # (note name, repo path, kind)  kind: full = summary + folded full text; outline = summary + headings only
    ("5년 매매법 성격 카드", "research/strategy_profiles/PROFILES.md", "full"),
    ("레버리지·손절 5년 연구", "research/levstop/PREREG_LEVSTOP.md", "levstop"),
    ("익절 방식 5년 비교", "research/exitstyle/out/SUMMARY_KO.md", "full"),
    ("익절 방식 사전 등록", "research/exitstyle/PREREG_EXITSTYLE.md", "outline"),
    ("유명 매매법 결과", "research/famous/RESULTS_FAMOUS.md", "full"),
    ("라이브러리 지표 결과 1", "research/library/RESULTS_LIBRARY.md", "full"),
    ("라이브러리 지표 결과 2", "research/library/RESULTS_LIBRARY_B.md", "full"),
    ("오더플로 결과", "research/orderflow/RESULTS_ORDERFLOW.md", "full"),
    ("3라운드 연구 결과", "research/round3/RESULTS_ROUND3.md", "full"),
    ("진단 결과", "research/diagnosis/RESULTS_DIAG.md", "full"),
    ("규칙 시뮬레이션 결과", "research/paper_rules/RESULTS_RULES.md", "full"),
    ("탐색 결과", "research/search/RESULTS_SEARCH.md", "full"),
    ("검증 결과", "research/verify/RESULTS_VERIFY.md", "full"),
    ("차트 리뷰 결과", "research/chart_review/RESULTS_CHART.md", "full"),
    ("메이커 주문 연구 결과", "research/maker/RESULTS_ROUND2.md", "full"),
    ("진입 연구 결과", "research/entry_study/RESULTS_ENTRY.md", "full"),
    ("진입 연구 결과 A", "research/entry_study/RESULTS_ENTRY_A.md", "outline"),
    ("진입 연구 결과 BC", "research/entry_study/RESULTS_ENTRY_BC.md", "outline"),
    ("추세선 연구 결과", "research/entry_study/RESULTS_TRENDLINE.md", "outline"),
    ("바이낸스 자료 비교 결과", "research/binance_data/RESULTS_BINANCE.md", "outline"),
    ("DeepSeek 200개 분류", "research/deepseek200/CLASSIFICATION.md", "full"),
    ("DeepSeek 200개 사전 등록", "research/deepseek200/PREREG_DEEPSEEK200.md", "outline"),
]
RULES_DOCS = [
    ("규칙 본문 v4", "docs/paper-v4-rules.md"), ("판정 방법 v4", "docs/paper-v4-verdict.md"),
    ("레버리지 규칙 B 평가 v4", "docs/levrule-eval-v4.md"),
    ("규칙 본문 v3", "docs/paper-v3-rules.md"), ("규칙 보충안", "docs/paper-v3-rules-addendum.md"),
    ("규칙 변경 1 (2026-10-04)", "docs/paper-v3-rules-change-1.md"), ("레버리지 규칙 B 평가 방법", "docs/levrule-eval.md"),
    ("관찰 그림자 1", "docs/observation-shadows.md"), ("관찰 그림자 2", "docs/observation-shadows-2.md"),
    ("관찰 그림자 3", "docs/observation-shadows-3.md"), ("관찰 그림자 4", "docs/observation-shadows-4.md"),
    ("새 매매법 연구실 사전 등록", "docs/newlab-prereg.md"),
]
REQUIRED_RESEARCH = ("5년 매매법 성격 카드",)
RESEARCH_AREA = {"strategy_profiles": "매매법 성격", "levstop": "레버리지·손절", "exitstyle": "익절 방식", "famous": "유명 매매법",
                 "library": "지표 라이브러리", "orderflow": "오더플로", "round3": "3라운드", "diagnosis": "진단",
                 "paper_rules": "규칙 시뮬레이션", "search": "탐색", "verify": "검증", "chart_review": "차트 리뷰",
                 "maker": "지정가(메이커)", "entry_study": "진입 연구", "binance_data": "자료 비교", "deepseek200": "DeepSeek 200개"}


def _research_files(repo: str) -> list:
    """RESEARCH_MAP entries whose file exists, plus any other RESULTS*.md / CLASSIFICATION.md under research/ and
    deepseek200 result files that appear later (no note is made for a file that is not there)."""
    out = []
    seen = set()
    for name, rel, kind in RESEARCH_MAP:
        if os.path.isfile(os.path.join(repo, rel)):
            out.append((name, rel, kind))
            seen.add(rel)
    extra = sorted(glob.glob(os.path.join(repo, "research", "*", "RESULTS*.md")) +
                   glob.glob(os.path.join(repo, "research", "deepseek200", "*.md")))
    used = {n for n, _, _ in out}
    for p in extra:
        rel = os.path.relpath(p, repo).replace(os.sep, "/")
        if rel in seen or "PREREG" in rel:
            continue
        area = rel.split("/")[1]
        name = safe_name(f"연구 {RESEARCH_AREA.get(area, area)} {os.path.splitext(os.path.basename(p))[0]}")
        if name in used:
            continue
        used.add(name)
        out.append((name, rel, "full"))
    return out


def prepare(ctx: Ctx) -> None:
    """Pass over meetings and research documents that the other builders link from (mentions of strategies)."""
    d = ctx.data
    for r in d.rounds:
        day = r["kst_day"]
        if r["room_id"].startswith("strat:"):
            ctx.mentions[day].add(r["room_id"][6:])
        ctx.mentions[day] |= ids_in(r["decision_summary"] + " " + r["summary_ko"])
        for m in d.messages.get(r["round_id"], []):
            if m["kind"] == "summary":
                ctx.mentions[day] |= ids_in(m["text"])
    found = _research_files(ctx.repo_dir)
    for name, rel, kind in RESEARCH_MAP:                   # notes other notes link to exist even when the file is missing
        if name in REQUIRED_RESEARCH and not any(n == name for n, _, _ in found):
            found.insert(0, (name, rel, "missing"))
    for name, rel, kind in found:
        txt = read_text(os.path.join(ctx.repo_dir, rel)) or ""
        ids = ids_in(txt)
        ctx.research.append({"name": name, "rel": rel, "kind": kind, "text": txt, "ids": ids})
        for sid in ids:
            ctx.research_by_sid[sid].append(name)


# ================================================================== 04 meetings
def build_meetings(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    by_day = defaultdict(list)
    for r in d.rounds:
        by_day[r["kst_day"]].append(r)
    owner_by_day = defaultdict(list)
    for m in d.owner_messages:
        owner_by_day[kst_day(m["ts"])].append(m)
    comm_by_day = defaultdict(list)
    for c in d.committee:
        comm_by_day[c["day"]].append(c)
    days = ctx.days
    idx = {x: i for i, x in enumerate(days)}
    week_days = defaultdict(list)
    for x in days:
        week_days[iso_week(x)].append(x)
    for day in days:
        rounds = sorted(by_day.get(day, []), key=lambda r: (r["started_ts"], r["round_id"]))
        tr = d.day_trades.get(day) or {"n": 0, "pnl": 0.0, "wins": 0}
        calls = d.calls_by_day.get(day, [0, 0])
        i = idx[day]
        nav = []
        if i > 0:
            nav.append("← " + link(day_name(days[i - 1]), days[i - 1]))
        if any(c["day"] == day for c in d.daily):
            nav.append(link(check_name(day), "그날 밤 점검"))
        nav.append(link(week_name(iso_week(day)), "이번 주"))
        nav.append(link("회의 목록"))
        if i + 1 < len(days):
            nav.append(link(day_name(days[i + 1]), days[i + 1]) + " →")
        body = [hero(day_ko(day), f"회의 {len(rounds)}번 · AI 호출 {calls[0]}회"), LEGEND + "\n", " · ".join(nav) + "\n"]
        body.append(callout("pb-stat", "그날의 숫자 " + badge("code"),
                            stat_row([("끝난 거래", f"{tr['n']}건"), ("손익 합계", usd(tr["pnl"], 0)),
                                      ("이긴 거래", pct(tr["wins"] / tr["n"], 0, False) if tr["n"] else "-"),
                                      ("AI 호출", f"{calls[0]}회"), ("토큰", f"{calls[1]:,}")]).rstrip()
                            + (f"\n\n{badge('small')} {small_flag(tr['n'])}" if small_flag(tr["n"]) else "")))
        if rounds:
            body.append("## 회의 한눈에 " + badge("code"))
            body.append(table(["시각", "회의", "방", "결과", "AI 호출"],
                              [[kst_hm(r["started_ts"]), trigger_ko(r["trigger"]), room_label(r["room_id"]),
                                r["status"] + (f" · {r['action']}" if r.get("action") else ""), r["calls"]]
                               for r in rounds], ["l", "l", "l", "l", "r"]))
        budget = [DAY_AI_BUDGET]
        mentioned = set(ctx.mentions.get(day, set()))
        for key, label, trigs in GROUPS:
            rs = [r for r in rounds if group_of(r["trigger"]) == key]
            if not rs:
                continue
            body.append(f"## {label} ({len(rs)}번)")
            for r in rs:
                body.append(round_block(ctx, r, budget))
        if comm_by_day.get(day):
            body.append("## 낙관·비관 토론 판정 " + badge("code"))
            body.append(table(["코인", "판정", "확신", "상태", "24시간 뒤 움직임", "맞음"],
                              [[c["symbol"], c["direction"] or "-", c["confidence"] or "-", c["status"],
                                pct(c["move"], 2), {1: "맞음", 0: "틀림"}.get(c["correct"], "-")]
                               for c in comm_by_day[day]]))
        if owner_by_day.get(day):
            body.append("## 두 분이 남긴 글")
            for m in owner_by_day[day][-8:]:
                body.append(callout("quote", f"{kst_hm(m['ts'])} · {sanitize(m['room_id'])}", sanitize(m["text"], 300)))
        notes_today = [n for n in d.notes if kst_day(n["ts"]) == day]
        if notes_today:
            body.append(f"## 그날 남긴 메모\n{len(notes_today)}개 — " + link(f"교훈 {day}") + "\n")
        if mentioned:
            body.append("## 관련 매매법\n" + " · ".join(strat_link(s) for s in sorted(mentioned)[:40])
                        + (f" 외 {len(mentioned) - 40}개" if len(mentioned) > 40 else ""))
        if not rounds and not tr["n"]:
            body.append("이 날은 회의와 거래 기록이 없습니다.")
        v.add(FOLDERS["meet"], day_name(day), "\n".join(body), type="회의", tags=["회의"], css=("pb-meeting",), sub="일일",
              source="mixed", props={"date": day, "week": iso_week(day), "n_rounds": len(rounds), "n_trades": tr["n"],
                                     "small_sample": tr["n"] < 10, "strategy": sorted(mentioned)[:40]},
              legend="코드 계산 + AI 작성(표시됨)")
    # weeks
    for wk, ds in sorted(week_days.items()):
        rows = []
        for x in ds:
            tr = d.day_trades.get(x) or {"n": 0, "pnl": 0.0, "wins": 0}
            rows.append([link(day_name(x), x), len(by_day.get(x, [])), tr["n"], usd(tr["pnl"], 0),
                         d.calls_by_day.get(x, [0, 0])[0]])
        body = [hero(f"{wk} 주간 회의", f"{ds[0]} ~ {ds[-1]}"), LEGEND + "\n",
                table(["날", "회의", "끝난 거래", "손익 합계", "AI 호출"], rows, ["l", "r", "r", "r", "r"])]
        wr = [r for x in ds for r in by_day.get(x, []) if r["trigger"] in WEEKLY_TRIGGERS]
        if wr:
            body.append("## 주간·분석 회의 결론")
            for r in sorted(wr, key=lambda r: r["started_ts"]):
                lead = next((m for m in d.messages.get(r["round_id"], []) if m["kind"] == "summary"), None)
                parts = [f"{link(day_name(r['kst_day']), r['kst_day'])} {kst_hm(r['started_ts'])} · {trigger_ko(r['trigger'])}"
                         f" · {room_label(r['room_id'])}", "",
                         f"{badge('code')} " + sanitize(r["decision_summary"] or r["summary_ko"], 360).replace("\n", " / ")]
                if lead:
                    parts += ["", callout("quote", "AI 작성 · " + (lead["name"] or lead["role"]), sanitize(lead["text"], 420), "-")]
                body.append("\n".join(parts) + "\n")
        else:
            body.append("이 주에는 주간·분석 회의 기록이 없습니다.")
        body.append("\n" + link("회의 목록") + " · " + link("홈"))
        v.add(FOLDERS["meet"], week_name(wk), "\n".join(body), type="회의", tags=["회의", "주간"], css=("pb-meeting",),
              sub="주간", source="mixed", props={"date": ds[0], "week": wk, "n_rounds": sum(len(by_day.get(x, [])) for x in ds)})
    build_meeting_categories(v, by_day)
    # hub
    rows = []
    for x in reversed(days):
        tr = d.day_trades.get(x) or {"n": 0, "pnl": 0.0}
        rows.append([link(day_name(x), x), link(week_name(iso_week(x)), iso_week(x)), len(by_day.get(x, [])), tr["n"],
                     usd(tr["pnl"], 0), d.calls_by_day.get(x, [0, 0])[0]])
    cnt = Counter(r["trigger"] for r in d.rounds)
    body = [hero("회의 기록", f"하루 한 장. 지금까지 회의 {len(d.rounds)}번, 기록된 날 {len(days)}일"), LEGEND + "\n",
            callout("warning", "AI가 쓴 글입니다", "회의 본문은 AI 직원이 쓴 것이라 틀릴 수 있습니다. 숫자는 코드가 계산한 표만 믿으세요. "
                    "'결론'은 30일 체크포인트에서 코드가 판정하기 전까지 모두 가설입니다."),
            "## 모음\n- " + link("손실 복기 회의 모음") + "\n- " + link("시세 급변 회의 모음") + "\n- " + link("체크포인트 회의 모음")
            + "\n- " + link("사고·파산 회의 모음"),
            "## 회의 종류별 횟수 " + badge("code"),
            table(["회의", "횟수"], [[trigger_ko(t), c] for t, c in sorted(cnt.items(), key=lambda x: -x[1])]) or "아직 회의가 없습니다.\n",
            "## 날짜별\n" + (table(["날", "주", "회의", "끝난 거래", "손익 합계", "AI 호출"], rows[:200],
                                 ["l", "l", "r", "r", "r", "r"]) or "아직 기록이 없습니다.\n"),
            "\n" + link("홈") + " · " + link("직원 목록")]
    v.add(FOLDERS["meet"], "회의 목록", "\n".join(body), type="허브", tags=["허브", "회의"], css=("pb-hub",), source="mixed")


def room_label(room_id: str) -> str:
    if room_id.startswith("strat:"):
        sid = room_id[6:]
        return strat_link(sid) if sid in STRATEGY_KO else sanitize(room_id)
    if room_id == "team:lab":
        return "새 매매법 연구실"
    t = room_id.split(":", 1)[-1]
    return link(team_note(t)) if t in TEAM_NAME else sanitize(room_id)


def round_block(ctx: Ctx, r: dict, budget: list) -> str:
    d = ctx.data
    msgs = d.messages.get(r["round_id"], [])
    head = f"#### {kst_hm(r['started_ts'])} · {trigger_ko(r['trigger'])} · {room_label(r['room_id'])}"
    concl = r["decision_summary"] or next((m["text"] for m in msgs if m["kind"] == "decision"), "") or r["summary_ko"]
    out = [head, "", callout("pb-code", "결론 · 코드 집계 " + badge("code").replace("\n", ""), sanitize(concl, CONCL_CHARS))]
    ai = [m for m in msgs if m["kind"] in AI_KINDS]
    code = [m for m in msgs if m["kind"] in CODE_SHOW]
    for m in code[:3]:
        out.append(callout("pb-code", {"action": "코드가 한 일", "code_result": "코드 시험 결과"}[m["kind"]],
                           sanitize(m["text"], 360), "-"))
    if ai and budget[0] > 0:
        lead = next((m for m in reversed(ai) if m["kind"] == "summary"), None)
        shown = ([lead] if lead else []) + [m for m in ai if m is not lead][: ROUND_MSGS - (1 if lead else 0)]
        inner = []
        for m in shown:
            if budget[0] <= 0:
                break
            t = sanitize(m["text"], MSG_CHARS)
            budget[0] -= len(t)
            inner.append(f"**{sanitize(m['name'] or m['role'])}** ({m['kind']}): {t}")
        if inner:
            more = len(ai) - len(shown)
            out.append(callout("pb-ai", f"AI 작성 · 발언 {len(ai)}개 중 {len(inner)}개", "\n\n".join(inner)
                               + (f"\n\n…나머지 {more}개 생략" if more > 0 else ""), "-"))
    elif ai:
        out.append(f"*AI 발언 {len(ai)}개는 이 날 분량 한도로 생략했습니다.*")
    return "\n".join(out) + "\n"


def build_meeting_categories(v: Vault, by_day: dict) -> None:
    d = v.ctx.data
    cats = [("손실 복기 회의 모음", ("loss_cluster",), "손실이 이어질 때 매매법 방에서 연 복기 회의"),
            ("시세 급변 회의 모음", ("market_move",), "시세가 크게 움직였을 때 연 회의"),
            ("체크포인트 회의 모음", ("checkpoint",), "30일 단위 점검 때 연 회의 (공식 판정은 코드)"),
            ("사고·파산 회의 모음", ("incident", "bust"), "데이터·운영 사고나 계좌 파산 때 연 회의")]
    for name, trigs, what in cats:
        rs = [r for r in d.rounds if r["trigger"] in trigs]
        rows = []
        for r in reversed(rs[-300:]):
            rows.append([link(day_name(r["kst_day"]), r["kst_day"]), kst_hm(r["started_ts"]), trigger_ko(r["trigger"]),
                         room_label(r["room_id"]), r["status"], r.get("action") or "-"])
        cnt = Counter(r["room_id"] for r in rs)
        top = ", ".join(f"{room_label(k)} {c}" for k, c in cnt.most_common(6))
        body = [hero(name, what), LEGEND + "\n",
                stat_row([("전체", f"{len(rs)}번"), ("표시", f"{min(len(rs), 300)}번")]),
                (f"가장 많은 방: {top}\n" if top else ""),
                table(["날", "시각", "회의", "방", "상태", "결과"], rows) or "아직 이런 회의가 없습니다.\n",
                "\n" + link("회의 목록") + " · " + link("홈")]
        v.add(FOLDERS["meet"], name, "\n".join(body), type="회의", tags=["회의", "모음"], css=("pb-meeting",), source="code",
              props={"n_rounds": len(rs), "small_sample": len(rs) < 10})


# ================================================================== 05 lessons, hypotheses, trials
def binom_p(k: int, n: int) -> Optional[float]:
    if n <= 0:
        return None
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def pred_ko(p: dict) -> str:
    try:
        from .agents.scorecard import describe_ko
        return describe_ko(p)
    except Exception:
        return json.dumps(p, ensure_ascii=False)[:160]


def build_lessons(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    # notes grouped by day, identical texts merged
    by_day = defaultdict(lambda: defaultdict(list))
    for n in d.notes:
        by_day[kst_day(n["ts"])][n["text"].strip()].append(n.get("strategy") or "")
    for day, texts in sorted(by_day.items()):
        body = [hero(f"교훈 {day}", f"{day_ko(day)}에 에이전트가 남긴 메모 {sum(len(x) for x in texts.values())}개"),
                badge("ai") + " 에이전트가 쓴 메모입니다. 사실로 확인된 것이 아니라 가설일 수 있습니다.\n"]
        for text, sids in texts.items():
            sids_u = sorted({s for s in sids if s in STRATEGY_KO})
            who = (" · ".join(strat_link(s) for s in sids_u[:6]) + (f" 외 {len(sids_u) - 6}개" if len(sids_u) > 6 else "")
                   if sids_u else "팀 방")
            body.append(callout("pb-ai", f"{who}" + (f" (같은 메모 {len(sids)}개)" if len(sids) > 1 else ""), sanitize(text, 700)))
        body.append("\n" + link(day_name(day), "그날 회의") + " · " + link("교훈 모음") + " · " + link("교훈과 가설"))
        v.add(FOLDERS["learn"], f"교훈 {day}", "\n".join(body), type="교훈", tags=["교훈"], css=("pb-lesson",), sub="교훈",
              source="ai", props={"date": day, "n_notes": sum(len(x) for x in texts.values()),
                                  "strategy": sorted({s for ss in texts.values() for s in ss if s in STRATEGY_KO})[:40]},
              legend="AI 작성")
    rows = [[link(f"교훈 {day}", day), sum(len(x) for x in texts.values()), len(texts)] for day, texts in sorted(by_day.items(), reverse=True)]
    body = [hero("교훈 모음", "에이전트가 방에 남긴 메모를 날짜별로 모았습니다 (AI 작성)"),
            callout("warning", "교훈은 아직 가설입니다", "30건 미만의 거래에서 나온 메모는 우연일 수 있습니다. 가설로 적힌 것은 "
                    + link("가설 장부") + "에서 코드가 채점합니다."),
            table(["날", "메모", "서로 다른 글"], rows[:120], ["l", "r", "r"]) or "아직 메모가 없습니다.\n",
            "\n" + link("교훈과 가설") + " · " + link("홈")]
    v.add(FOLDERS["learn"], "교훈 모음", "\n".join(body), type="허브", tags=["허브", "교훈"], css=("pb-hub",), source="ai")
    build_hypotheses(v)
    build_trials(v)
    build_debate(v)
    sc = d.scorecard.get("total") or {}
    tc = d.trial_counts or {}
    gr = sc.get("graded", 0)
    body = [hero("교훈과 가설", "직원들이 배운 것, 세운 가설, 시험한 것. 가설은 코드가 나중에 채점합니다"), LEGEND + "\n",
            callout("pb-stat", "숫자 " + badge("code"),
                    stat_row([("가설", str(tc.get("hypothesis", 0))), ("채점됨", str(gr)),
                              ("맞음", str(sc.get("correct", 0))),
                              ("5년 시험", str(tc.get("test", 0))), ("새 매매법 시험", str(tc.get("newlab", 0)))]).rstrip()
                    + (f"\n\n{badge('small')} 채점된 가설이 {gr}개라 적중률은 의미를 두기 이릅니다." if gr < 10 else "")),
            "- " + link("가설 장부") + " — 모든 가설과 채점 결과\n- " + link("시험 장부") + " — 여러 번 시험했을 때의 우연 보정 횟수\n- "
            + link("교훈 모음") + " — 날짜별 메모\n- " + link("낙관·비관 토론 채점") + " — 하루 한 코인 토론의 24시간 뒤 채점\n- "
            + link("직원 성적표"),
            callout("info", "왜 시험 횟수를 세나요", "같은 자료로 여러 번 시험하면 우연히 좋아 보이는 것이 나옵니다. 그래서 시험 횟수를 장부에 "
                    "빠짐없이 적고, 횟수가 늘수록 통과 기준(p)을 엄격하게 합니다 (본페로니: 기준 ÷ 시험 횟수)."),
            "\n" + link("홈")]
    v.add(FOLDERS["learn"], "교훈과 가설", "\n".join(body), type="허브", tags=["허브", "교훈", "가설"], css=("pb-hub",),
          source="mixed", props={"n_hypotheses": tc.get("hypothesis", 0), "n_graded": gr, "small_sample": gr < 10})


def hyp_result_line(h: dict) -> str:
    res = h.get("result") or {}
    spec = h.get("spec") if isinstance(h.get("spec"), dict) else {}
    if not isinstance(spec.get("prediction"), dict) or h.get("result") is None or res.get("status") != "graded":
        return ""
    val = res.get("value")
    return f"측정 {fnum(val, 3)} (거래 {res.get('n', '-')}건)" if val is not None else (res.get("why") or "")


def build_hypotheses(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    hs = list(d.hypotheses)
    with_note = {h["id"] for h in hs[-MAX_HYP_NOTES:]}
    for h in hs[-MAX_HYP_NOTES:]:
        spec = h.get("spec") if isinstance(h.get("spec"), dict) else {}
        sid = h.get("strategy") or ""
        by = spec.get("by") or ""
        day = kst_day(h["ts"])
        pred = spec.get("prediction") if isinstance(spec.get("prediction"), dict) else None
        res = h.get("result") or {}
        n_tr = res.get("n") if isinstance(res.get("n"), int) else None
        st = status_ko(h)
        body = [hero(f"가설 {h['id']}", f"{STRATEGY_KO.get(sid, '팀')} · {day} · {st}"),
                callout("pb-ai", "가설 내용 " + badge("ai").replace("\n", ""), sanitize(spec.get("text") or str(spec), 700)),
                ("**확인 방법(AI 작성)**: " + sanitize(spec.get("how_to_confirm"), 300) + "\n") if spec.get("how_to_confirm") else "",
                "## 코드가 채점하는 방법 " + badge("code")]
        if pred:
            body.append(pred_ko(pred) + "\n")
            line = hyp_result_line(h)
            body.append(f"**결과: {st}** " + (f"— {line}" if line else "") + "\n")
            if n_tr is not None and n_tr < 10:
                body.append(badge("small") + f" 거래 {n_tr}건\n")
        else:
            body.append("예측이 붙지 않은 가설이라 채점하지 않습니다.\n")
        links = []
        if sid in STRATEGY_KO:
            links.append("매매법: " + strat_link(sid))
        if by:
            links.append("쓴 사람: " + role_link(by))
        links.append("회의: " + link(day_name(day), day) if day in ctx.days else "")
        body.append("## 연결\n" + " · ".join(x for x in links if x) + "\n\n" + link("가설 장부") + " · " + link("교훈과 가설"))
        v.add(FOLDERS["learn"], hyp_name(h), "\n".join(body), type="가설", tags=["가설"], css=("pb-hypo",), sub="가설",
              source="mixed", props={"strategy": sid or None, "status": st, "date": day, "by": by or None,
                                     "n_trades": n_tr, "small_sample": (n_tr is not None and n_tr < 10)},
              legend="가설은 AI 작성, 채점은 코드")
    rows = []
    for h in reversed(hs[:500]) if len(hs) <= 500 else reversed(hs[-500:]):
        spec = h.get("spec") if isinstance(h.get("spec"), dict) else {}
        nm = link(hyp_name(h), f"#{h['id']}") if h["id"] in with_note else f"#{h['id']}"
        rows.append([nm, kst_day(h["ts"]), strat_link(h["strategy"]) if h.get("strategy") in STRATEGY_KO else "-",
                     sanitize(spec.get("text") or "", 110).replace("\n", " "), role_link(spec["by"]) if spec.get("by") else "-",
                     status_ko(h)])
    cnt = Counter(status_ko(h) for h in hs)
    sc = d.scorecard.get("roles") or []
    srows = [[role_link(r["role"]) if r["role"] else "(표시 없음)", r["graded"], r["correct"],
              pct(r["hit_rate"], 0, False) if r["hit_rate"] is not None else "-", r["waiting"], r["expired"], r["not_gradable"],
              small_flag(r["graded"]) if r["graded"] < 10 else "-"] for r in sc]
    tot = d.scorecard.get("total") or {}
    p = binom_p(int(tot.get("correct", 0)), int(tot.get("graded", 0)))
    body = [hero("가설 장부", f"가설 {len(hs)}개. 예측이 붙은 가설은 코드가 거래 30~300건 뒤 한 번 채점합니다"), LEGEND + "\n",
            stat_row([(k, str(c)) for k, c in sorted(cnt.items())] or [("가설", "0")]),
            "## 직원별 적중률 " + badge("code"),
            table(["직원", "채점", "맞음", "적중률", "대기", "만료", "예측 없음", "표본"], srows,
                  ["l", "r", "r", "r", "r", "r", "r", "l"]) or "아직 채점된 가설이 없습니다.\n",
            (f"전체: 채점 {tot.get('graded', 0)}개 중 {tot.get('correct', 0)}개 맞음. 동전 던지기(50%)였다면 이만큼 맞을 확률 p = "
             f"{fnum(p, 3)} (한쪽).\n" if p is not None else ""),
            callout("warning", "읽는 법", "채점이 10개 미만이면 '표본 적음'입니다. 맞았다고 해서 규칙을 바꾸지 않습니다: 같은 자료로 "
                    "규칙을 고르면 안 되고, 바꾸려면 새 계좌로 따로 확인합니다."),
            "## 전체 목록 " + badge("ai") + (f" (최근 500개, 노트가 있는 것은 최근 {MAX_HYP_NOTES}개)" if len(hs) > 200 else ""),
            table(["번호", "날", "매매법", "가설 (앞부분)", "쓴 사람", "상태"], rows) or "아직 가설이 없습니다.\n",
            "\n" + link("교훈과 가설") + " · " + link("시험 장부") + " · " + link("홈")]
    v.add(FOLDERS["learn"], "가설 장부", "\n".join(body), type="가설", tags=["가설", "장부"], css=("pb-hypo",), source="mixed",
          props={"n_hypotheses": len(hs), "n_graded": tot.get("graded", 0), "small_sample": tot.get("graded", 0) < 10})


def trial_row(t: dict) -> list:
    res = t.get("result") or {}
    body = res.get("result") if isinstance(res.get("result"), dict) else {}
    gate = body.get("gate") if isinstance(body.get("gate"), dict) else {}
    ledger = body.get("ledger") if isinstance(body.get("ledger"), dict) else {}
    g = gate.get("pass", (ledger.get("gate") or {}).get("pass") if isinstance(ledger.get("gate"), dict) else None)
    spec = t.get("spec") if isinstance(t.get("spec"), dict) else {}
    brief = spec.get("template") or (spec.get("entry") or {}).get("family") or spec.get("kind") or ""
    tf = spec.get("timeframe") or ""
    num_ = ledger.get("test_number") or gate.get("test_number") or "-"
    return [f"#{t['id']}", kst_day(t["ts"]), t["kind"], strat_link(t["strategy"]) if t.get("strategy") in STRATEGY_KO else
            (sanitize(t.get("room_id") or "-")), sanitize(f"{brief} {tf}".strip(), 60), res.get("status") or "-",
            {True: "통과", False: "불통과", None: "-"}.get(g if g in (True, False) else None, "-"), num_]


def build_trials(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    tc = d.trial_counts or {}
    n_new, n_test = tc.get("newlab", 0), tc.get("test", 0)
    rows = [trial_row(t) for t in reversed(d.trials[-400:])]
    alpha = 0.05
    body = [hero("시험 장부", "5년 시험과 새 매매법 시험을 한 번도 빠짐없이 적는 장부. 횟수가 늘수록 통과 기준이 엄격해집니다"),
            LEGEND + "\n",
            callout("pb-stat", "여러 번 시험한 횟수 " + badge("code"),
                    stat_row([("가설", str(tc.get("hypothesis", 0))), ("5년 시험(test)", str(n_test)),
                              ("새 매매법 시험(newlab)", str(n_new)), ("복제 제안", str(tc.get("copy_proposal", 0))),
                              ("새 매매법 통과", str(tc.get("newlab_passed", 0)))]).rstrip()),
            callout("info", "우연 보정 (본페로니)",
                    f"새 매매법 시험은 모든 방을 합쳐 지금까지 **{n_new}번**입니다. 다음 시험의 1기간 기준은 p < 0.05 ÷ ({n_new} + 1) = "
                    f"**{alpha / (n_new + 1):.4f}** 입니다. 5년 시험(복사 계좌 제안용)은 {n_test}번입니다. 횟수는 줄어들지 않고, "
                    "같은 시험을 다시 해도 새 횟수로 셉니다."),
            "## 시험 목록 " + badge("code") + f" (최근 {min(len(d.trials), 400)}개 / 전체 {len(d.trials)}개)",
            table(["번호", "날", "종류", "매매법/방", "내용(요약)", "결과 상태", "관문", "시험 번호"], rows) or "아직 시험이 없습니다.\n"]
    props = d.proposals
    if props:
        body.append("## 제안 " + badge("code"))
        body.append(table(["번호", "날", "매매법", "종류", "상태", "결정"],
                          [[p["id"], kst_day(p["ts"]), strat_link(p["strategy"]) if p.get("strategy") in STRATEGY_KO else "-",
                            (p.get("change") or {}).get("kind", "copy"), p["status"], p.get("decided_by") or "-"]
                           for p in reversed(props[-60:])]))
    if d.approvals:
        body.append("## 두 분의 승인·거부 " + badge("code"))
        body.append(table(["시각", "제안", "결정"], [[kst_min(a["ts"]), f"#{a['proposal_id']}", a["decision"]] for a in d.approvals[-30:]]))
    body.append("\n" + link("교훈과 가설") + " · " + link("추가 계좌") + " · " + link("홈"))
    v.add(FOLDERS["learn"], "시험 장부", "\n".join(body), type="시험", tags=["시험", "장부"], css=("pb-hypo",), source="code",
          props={"n_tests": n_test + n_new, "small_sample": (n_test + n_new) < 10})


def build_debate(v: Vault) -> None:
    d = v.ctx.data
    graded = [c for c in d.committee if c["status"] == "graded"]
    k = sum(1 for c in graded if c["correct"] == 1)
    p = binom_p(k, len(graded))
    rows = [[c["day"], c["symbol"], c["direction"] or "-", c["confidence"] or "-", c["status"], pct(c["move"], 2),
             {1: "맞음", 0: "틀림"}.get(c["correct"], "-")] for c in d.committee[-60:]][::-1]
    body = [hero("낙관·비관 토론 채점", "하루 한 코인: 낙관론자와 비관론자가 토론하고 팀장이 24시간 뒤 방향을 판정. 거래로 이어지지 않습니다"),
            LEGEND + "\n",
            stat_row([("전체 판정", str(len(d.committee))), ("채점됨", str(len(graded))), ("맞음", str(k))]),
            (f"채점 {len(graded)}개 중 {k}개 맞음 (50% 동전 던지기 기준 p = {fnum(p, 3)}, 한쪽). "
             + (badge("small") + " 표본이 적어 우연일 수 있습니다." if len(graded) < 10 else "") + "\n" if graded else
             "아직 채점된 판정이 없습니다.\n"),
            table(["날", "코인", "판정", "확신", "상태", "24시간 움직임", "맞음"], rows) or "",
            "\n" + link("교훈과 가설") + " · " + link("홈")]
    v.add(FOLDERS["learn"], "낙관·비관 토론 채점", "\n".join(body), type="가설", tags=["가설", "토론"], css=("pb-hypo",), source="code",
          props={"n_graded": len(graded), "small_sample": len(graded) < 10})


# ================================================================== 06 research, 08 rules
def outline(md: str, limit: int = 40) -> list[str]:
    out = []
    for h, lv, _ in split_sections(md):
        if h and lv in (1, 2, 3):
            out.append(f"{'  ' * (lv - 1)}- {sanitize(h, 110)}")
    return out[:limit]


SUMMARY_HEAD = re.compile(r"결론|요약|한 줄|핵심|먼저 알아|Conclusion|Summary|판정", re.I)


def summary_of(md: str, max_lines: int = 36) -> str:
    secs = split_sections(md)
    picked = []
    for h, lv, body in secs:
        if h and SUMMARY_HEAD.search(h):
            picked.append((h, body))
    out = []
    if picked:
        for h, body in picked[:3]:
            txt = [ln for ln in body if ln.strip()][:max_lines]
            out.append(f"**{sanitize(h, 100)}**\n\n" + sanitize("\n".join(txt)))
    else:
        first = secs[0][2] + (secs[1][2] if len(secs) > 1 else [])
        txt = [ln for ln in first if ln.strip()][:max_lines]
        out.append(sanitize("\n".join(txt)))
    return "\n\n".join(out)


def first_title(md: str, default: str) -> str:
    for h, lv, _ in split_sections(md):
        if lv == 1 and h:
            return sanitize(h, 120)
    return default


def folded_body(md: str, title: str, cap: int = DOC_BODY_CAP) -> str:
    return callout("note", title, sanitize(md, cap, "\n\n…(원문이 길어 여기서 줄였습니다. 전체는 저장소의 같은 이름 파일)"), "-")


def levstop_table(repo: str) -> str:
    txt = read_text(os.path.join(repo, "research", "levstop", "out", "levstop.json"), 5_000_000)
    try:
        j = json.loads(txt) if txt else None
    except ValueError:
        return ""
    by = ((j or {}).get("summary") or {}).get("by_arm") if isinstance(j, dict) else None
    if not isinstance(by, dict):
        return ""
    rows = []
    for arm, s in by.items():
        if not isinstance(s, dict):
            continue
        rows.append([f"`{arm}`", s.get("cells"), f"{s.get('trades', 0):,}" if isinstance(s.get("trades"), int) else "-",
                     s.get("cells_mean_positive"), s.get("sig_pos_bh"), s.get("sig_neg_bh"), pct(s.get("pooled_mean_eq"), 2),
                     pct(s.get("median_cell_mean_eq"), 2)])
    return table(["방식(레버리지|손절 ATR)", "칸", "거래", "평균 플러스 칸", "유의 플러스(BH)", "유의 마이너스(BH)",
                  "전체 평균(자금 대비)", "칸 중앙값"], rows, ["l", "r", "r", "r", "r", "r", "r", "r"])


def build_research(v: Vault) -> None:
    ctx = v.ctx
    repo = ctx.repo_dir
    rows = []
    for item in ctx.research:
        name, rel, kind, txt = item["name"], item["rel"], item["kind"], item["text"]
        area = rel.split("/")[1] if rel.startswith("research/") else ""
        title = first_title(txt, name)
        h = sha256_file(os.path.join(repo, rel)) or ""
        body = [hero(name, f"{RESEARCH_AREA.get(area, area)} · 원문 {rel}"), f"{badge('doc')} 저장소의 문서를 읽어 옮긴 요약입니다(서버 경로·비밀값은 지움). "
                "과거 5년 자료에서의 결과이고 **이번 실험의 결론이 아닙니다**.\n",
                callout("info", "원문", f"`{rel}` · 해시 `{h[:16]}…` · 제목: {title}")]
        if not txt.strip():
            body.append(callout("warning", "원문을 읽지 못했습니다", f"`{rel}` 파일이 이 서버의 저장소에 없거나 비어 있습니다."))
        else:
            body.append("## 요약\n" + summary_of(txt) + "\n")
        if kind == "levstop":
            tbl = levstop_table(repo)
            if tbl:
                body.append("## 결과 표 (연구 결과 파일, 코드 계산)\n" + tbl)
        ol = outline(txt)
        if ol:
            body.append(callout("abstract", "목차", "\n".join(ol), "-"))
        if kind in ("full", "levstop"):
            body.append(folded_body(txt, "원문 전체 (펼치기)"))
        ids = sorted(item["ids"])
        if ids:
            body.append("## 이 문서에 나온 매매법\n" + " · ".join(strat_link(s) for s in ids[:36]))
        body.append("\n" + link("연구 지도") + " · " + link("매매법 목록") + " · " + link("홈"))
        v.add(FOLDERS["research"], name, "\n".join(body), type="연구", tags=["연구"], css=("pb-research",), source="doc",
              props={"area": RESEARCH_AREA.get(area, area), "source_file": rel, "strategy": ids[:36]}, legend="원문 문서 요약")
        rows.append([link(name), RESEARCH_AREA.get(area, area), f"`{rel}`"])
    body = [hero("연구 지도", "과거 5년 자료로 한 연구들의 요약. 이번 실험이 아니라 '시작 전에 알던 것'입니다"), LEGEND + "\n",
            callout("warning", "5년 연구는 결론이 아닙니다", "대부분의 연구는 '지금 규칙이 무엇을 놓치는지'를 찾는 탐색입니다. 같은 자료로 규칙을 "
                    "고르면 안 되므로, 좋아 보이는 것도 새 계좌로 따로 확인합니다."),
            table(["연구", "분야", "원문"], rows) or "연구 문서를 찾지 못했습니다(저장소 research/ 폴더).\n",
            "\n" + link("교훈과 가설") + " · " + link("매매법 목록") + " · " + link("홈")]
    v.add(FOLDERS["research"], "연구 지도", "\n".join(body), type="허브", tags=["허브", "연구"], css=("pb-hub",), source="doc",
          props={"n_documents": len(ctx.research)})


def build_rules(v: Vault) -> None:
    ctx = v.ctx
    repo = ctx.repo_dir
    rows = []
    for name, rel in RULES_DOCS:
        path = os.path.join(repo, rel)
        txt = read_text(path)
        if txt is None:
            body = [hero(name, f"원문 {rel}"), callout("warning", "원문을 읽지 못했습니다", f"`{rel}` 파일이 이 서버의 저장소에 없습니다."),
                    "\n" + link("규칙 문서 목록") + " · " + link("홈")]
            v.add(FOLDERS["rules"], name, "\n".join(body), type="규칙", tags=["규칙", "문서"], css=("pb-rules",), source="doc",
                  props={"source_file": rel, "hash_state": "문서 없음"})
            rows.append([link(name), f"`{rel}`", "-", "-", "문서 없음"])
            continue
        h = sha256_file(path) or ""
        rec = recorded_hash(os.path.splitext(path)[0] + ".sha256")
        state = "일치" if rec and rec == h else ("해시 파일 없음" if not rec else "불일치")
        body = [hero(name, f"고정 문서의 읽기 전용 사본 · 원문 {rel}"),
                callout("danger" if state == "불일치" else "success", f"해시 확인: {state} " + badge("code").replace("\n", ""),
                        f"문서 해시(SHA-256) `{h}`\n기록된 해시 `{rec or '-'}`"),
                callout("warning", "읽기 전용 사본", "이 문서는 해시로 고정돼 있어 고치지 않습니다. 여기 사본을 고쳐도 원본은 바뀌지 않으며, "
                        "다음 갱신 때 이 파일은 다시 만들어집니다. 서버 경로·비밀값은 지웠습니다."),
                "## 요약\n" + summary_of(txt, 24) + "\n",
                folded_body(txt, "원문 전체 (펼치기)", 40_000),
                "\n" + link("규칙 문서 목록") + " · " + link("실험 규칙 한눈에") + " · " + link("홈")]
        v.add(FOLDERS["rules"], name, "\n".join(body), type="규칙", tags=["규칙", "문서"], css=("pb-rules",), source="doc",
              props={"source_file": rel, "sha256": h, "hash_state": state}, legend="고정 문서 사본")
        rows.append([link(name), f"`{rel}`", f"`{h[:12]}…`", f"`{(rec or '-')[:12]}…`" if rec else "-", state])
    body = [hero("규칙 문서", "실험 규칙을 적은 고정 문서들. 해시로 잠겨 있어 바뀌면 바로 드러납니다"), LEGEND + "\n",
            callout("info", "해시란", "문서 내용을 지문(SHA-256)으로 만든 값입니다. 문서가 한 글자라도 바뀌면 지문이 달라져 '불일치'로 나옵니다."),
            table(["문서", "원문 위치", "지금 해시", "기록된 해시", "확인"], rows),
            "\n" + link("실험 규칙 한눈에") + " · " + link("실험 개요") + " · " + link("홈")]
    v.add(FOLDERS["rules"], "규칙 문서 목록", "\n".join(body), type="허브", tags=["허브", "규칙"], css=("pb-hub",), source="doc")


# ================================================================== 07 nightly checks
def build_daily(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    days = [r["day"] for r in d.daily]
    for i, r in enumerate(d.daily):
        day = r["day"]
        bad_par = (r.get("parity_mismatched") or 0) > 0 or (r.get("bars_mismatched") or 0) > 0
        nav = []
        if i > 0:
            nav.append("← " + link(check_name(days[i - 1]), days[i - 1]))
        if day in ctx.days:
            nav.append(link(day_name(day), "그날 회의"))
        nav.append(link("매일 점검 목록"))
        if i + 1 < len(days):
            nav.append(link(check_name(days[i + 1]), days[i + 1]) + " →")
        body = [hero(f"{day_ko(day)} 밤 점검", "09:20 KST에 코드가 어제를 다시 계산해 paper 기록과 맞춰 본 결과"), LEGEND + "\n",
                " · ".join(nav) + "\n",
                callout("danger" if bad_par else "success",
                        "paper와 재계산이 다릅니다" if bad_par else "paper와 재계산이 일치합니다",
                        f"계좌 {r.get('parity_accounts', '-')}개 중 다른 계좌 {r.get('parity_mismatched', '-')}개 · "
                        f"1분봉 {r.get('bars', '-')}개 중 다른 봉 {r.get('bars_mismatched', '-')}개")]
        body.append("## 한눈에 " + badge("code"))
        body.append(table(["항목", "값"], [
            ["점검한 날", r.get("data_day") or day], ["처리한 분(step)", r.get("steps")],
            ["진입 세기 점검", f"{r.get('strength_checked', '-')}개 중 실패 {r.get('strength_failed', '-')}개"],
            ["데이터: 빠진 분 / 거래량 0 / 튀는 범위", f"{r.get('missing_minutes')} / {r.get('zero_volume')} / {r.get('extreme_ranges')}"],
            ["최대 펀딩비(절댓값)", fnum(r.get("max_abs_funding_pct"), 3) + "%" if r.get("max_abs_funding_pct") is not None else "-"],
            ["체결 비용 기록", f"{r.get('fills_recorded', '-')}건, 진입 슬리피지 중앙값 {fnum(num(r.get('entry_slip_median')) * 1e4 if num(r.get('entry_slip_median')) is not None else None, 2)} bp"],
            ["손절 슬리피지(공개 체결로 추정)", f"끝난 거래 {r.get('stop_exits', '-')}건 중 측정 {r.get('stop_measured', '-')}건"
             + (f", 실제 중앙값 {fnum(r['stop_real_bps_median'], 1)} bp" if r.get("stop_real_bps_median") is not None else "")],
            ["파산한 그림자 계좌", len(r.get("busts") or [])],
        ]))
        vs = r.get("variants") or {}
        if vs:
            base = (vs.get("base") or {}).get("mean_eq")
            rows = []
            for k, x in vs.items():
                rows.append([f"`{k}`", x.get("trades"), x.get("resolved"), pct(x.get("mean_eq"), 2), pct(x.get("mean_roe"), 2),
                             pct((x.get("mean_eq") - base), 2) if (x.get("mean_eq") is not None and base is not None) else "-"])
            body.append("## 그림자 (그날 끝난 거래 기준) " + badge("code"))
            body.append(table(["그림자", "거래", "끝난 수", "평균 자금 대비 손익", "평균 ROE", "base와 차이(자금 대비)"], rows,
                              ["l", "r", "r", "r", "r", "r"]))
            body.append(callout("pb-soft", "읽는 법", "그림자는 규칙을 바꾸지 않고 '만약'을 기록한 것입니다. 레버리지가 다르면 ROE는 크기가 달라 "
                                "비교가 안 되므로 '자금 대비 손익'으로 비교합니다. 하루치는 거래가 적어 우연이 크니 "
                                "누적은 각 매매법 카드의 '그림자 비교'를 보세요."))
        sv = r.get("stop_variants") or {}
        if sv:
            body.append("## 진 거래에 손절을 넓혔다면 " + badge("code"))
            body.append(table(["손절", "진 거래", "평균 ROE", "플러스로 바뀜", "실제보다 나음"],
                              [[f"{k} ATR", x.get("losing_trades"), pct(x.get("mean_roe"), 1), x.get("turned_positive"),
                                x.get("better_than_actual")] for k, x in sv.items()]))
        if r.get("limit_signals") is not None:
            body.append(f"**지정가 그림자**: 신호 {r['limit_signals']}개 중 체결 {r.get('limit_filled')}개, 평균 ROE "
                        f"{pct(r.get('limit_mean_roe'), 2)} · 순서 때문에 놓친 신호 {r.get('skipped')}개\n")
        body.append("\n" + link("매매법 목록") + " · " + link("홈"))
        v.add(FOLDERS["daily"], check_name(day), "\n".join(body), type="점검", tags=["점검"], css=("pb-daily",), sub="일일",
              source="code", props={"date": day, "parity_mismatched": r.get("parity_mismatched"),
                                    "bars_mismatched": r.get("bars_mismatched"), "n_trades": r.get("closed"),
                                    "small_sample": (r.get("closed") or 0) < 10, "status": "불일치" if bad_par else "일치"})
    rows = []
    for r in reversed(d.daily):
        bad = (r.get("parity_mismatched") or 0) > 0 or (r.get("bars_mismatched") or 0) > 0
        rows.append([link(check_name(r["day"]), r["day"]), "불일치" if bad else "일치", r.get("parity_mismatched"),
                     r.get("strength_failed"), r.get("missing_minutes"), r.get("closed"),
                     pct(((r.get("variants") or {}).get("base") or {}).get("mean_eq"), 2)])
    n_bad = sum(1 for r in d.daily if (r.get("parity_mismatched") or 0) > 0 or (r.get("bars_mismatched") or 0) > 0)
    body = [hero("매일 점검", "매일 09:20(KST) 코드가 어제를 다시 계산해 paper와 맞춰 보고, 데이터·비용·그림자를 기록합니다"), LEGEND + "\n",
            stat_row([("점검한 날", str(len(d.daily))), ("불일치 있던 날", str(n_bad))]),
            table(["날", "paper 일치", "다른 계좌", "세기 실패", "빠진 분", "끝난 거래", "base 평균(자금 대비)"], rows[:200],
                  ["l", "l", "r", "r", "r", "r", "r"]) or "아직 밤 점검 기록이 없습니다(첫 점검은 시작 다음 날 09:20).\n",
            "\n" + link("홈") + " · " + link("회의 목록")]
    v.add(FOLDERS["daily"], "매일 점검 목록", "\n".join(body), type="허브", tags=["허브", "점검"], css=("pb-hub",), source="code",
          props={"n_days": len(d.daily)})
