"""Note builders of the Obsidian vault exporter, part 1: framework, strategies, staff, experiment, home.
Part 2 (meetings, lessons and hypotheses, research, rules, nightly checks) is paperbot/obsidian_notes_b.py.

Honesty rules baked in: every table says whether it is code-computed or AI-written, every count shows its sample size,
small samples are flagged under the repo's SMALL_N rule, and nothing here calls a result a conclusion before the
day-30 checkpoint.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from .agents.roster3 import ALL_ROLES, GROUP_SPECIALISTS, MEETINGS, ROLES, STRATEGY_KO, TEAMS
from .agents.facts import facts as _facts
from .config import V4_ACCOUNTS, V4_GROUP_ACCOUNTS, V4_GROUP_JUDGED
from .obsidian_sources import TFS, Data, read_text, recorded_hash, sha256_file, split_account, split_sections
from .obsidian_util import (DAY_MS, KST, MOCHA, normalize_md, badge, bar, callout, fnum, frontmatter, iso_week, kst_day, kst_dt,
                            kst_min, kst_stamp, link, mean, mermaid, num, pct, quote, safe_name, sanitize, small_flag,
                            table, usd, redact)

GENERATED_BY = "paperbot.obsidian_export"
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
# the day-30 verdict and the exits in words, from the agents' one source (agents/facts.py, built from the checkpoint and
# config; G18, G5): never a typed bot count, one FDR for the whole run or the ladder for the reel
METHOD_KO = _facts()["method_ko"]
EXITS_KO = _facts()["exits_ko"]
INITIAL = 5000.0
OBSERVE_DAYS = 21
PERIOD_DAYS = 30
FALLBACK_START = "2026-10-05 10:46"     # KST: the restart of the frozen 30-day run (used only when paper3.db has no run)

STAMP_RE = re.compile(r'^<div class="pb-stamp">.*</div>$', re.M)

FOLDERS = {
    "home": "00 홈", "exp": "01 실험", "strat": "02 매매법", "staff": "03 직원", "meet": "04 회의",
    "learn": "05 교훈·가설", "research": "06 연구", "daily": "07 매일 점검", "rules": "08 규칙·문서",
    "mine": "99 내 메모",
}

TRIGGER_KO = {"incident": "사고 점검", "owner": "두 분 글", "loss_cluster": "손실 묶음 복기", "bust": "파산 복기",
              "checkpoint": "30일 단위 점검", "morning": "아침 회의", "evening": "저녁 점검", "weekly": "주간 검토",
              "research": "새 매매법 연구", "market_move": "시세 급변 회의", "ranking": "순위 검토",
              "tf_split": "봉 비교 회의", "cost_review": "비용·체결 회의", "combo_review": "조합·동시 손실 회의",
              "coin_review": "코인·장세 회의", "learning_review": "학습 정리 회의", "rr_review": "손익비·청산 회의",
              "risk_review": "낙폭·파산 위험 회의", "event_review": "경제지표 복기 회의", "bull_bear": "낙관·비관 토론",
              "run_restart": "실험 재시작",
              # paper v4: the five DeepSeek / reel specialist rooms' meetings (agents/triggers.GROUP_TRIGGERS)
              "group_loss": "딥시크·릴스 손실 묶음 복기", "group_bust": "딥시크·릴스 파산 복기",
              "group_weekly": "딥시크·릴스 주간 검토"}
GROUPS = (("market", "시장·일정 회의", ("morning", "evening", "ranking", "bull_bear", "market_move", "event_review",
                                       "checkpoint")),
          ("loss", "손실·긴급 회의", ("loss_cluster", "bust", "incident", "owner", "group_loss", "group_bust",
                                       "group_weekly")),
          ("weekly", "주간·분석 회의", ("weekly", "tf_split", "cost_review", "combo_review", "coin_review",
                                       "learning_review", "rr_review", "risk_review", "research", "run_restart")))
WEEKLY_TRIGGERS = GROUPS[2][2]


def trigger_ko(t: str) -> str:
    return TRIGGER_KO.get(t, t)


def group_of(trigger: str) -> str:
    for key, _, ts in GROUPS:
        if trigger in ts:
            return key
    return "weekly"


def strat_name(sid: str) -> str:
    return f"{sid} {STRATEGY_KO.get(sid, sid)}"


def strat_link(sid: str, alias: Optional[str] = None) -> str:
    return link(strat_name(sid), alias if alias is not None else STRATEGY_KO.get(sid, sid))


ROLE_BY_ID = {r[0]: r for r in ROLES}
# paper v4: the five DeepSeek / reel specialists (spec_ds_structure ...) and their rooms (team:ds_structure ...)
GROUP_ROLE_BY_ID = {r[0]: r for r in GROUP_SPECIALISTS}
GROUP_ROOM_TITLES = {f"team:{r[0][len('spec_'):]}": f"{r[1]} 방" for r in GROUP_SPECIALISTS}
GROUP_ROLE_OF_ROOM = {f"team:{r[0][len('spec_'):]}": r[0] for r in GROUP_SPECIALISTS}
ROLE_NAME = {r[0]: r[1] for r in ALL_ROLES}
TEAM_NAME = dict(TEAMS)


def team_note(tid: str) -> str:
    n = TEAM_NAME.get(tid, tid)
    return n.split(" ", 1)[1] if " " in n else n


def role_note(rid: str) -> str:
    return safe_name(ROLE_NAME.get(rid, rid))


def role_link(rid: str) -> str:
    if rid in ROLE_BY_ID or rid in GROUP_ROLE_BY_ID:
        return link(role_note(rid), ROLE_NAME[rid])
    if rid.startswith("spec_") and rid[5:] in STRATEGY_KO:
        return strat_link(rid[5:], ROLE_NAME.get(rid))
    return ROLE_NAME.get(rid, rid)


def group_role_lines(rid: str) -> list:
    """A DeepSeek / reel specialist's note: the definitions it covers, by family (paper v4); [] for other roles."""
    if rid not in GROUP_ROLE_BY_ID:
        return []
    from .groups import DS_FAMILY_KO, REEL_KO, role_members
    from .config import DS200_FAMILY, REEL_NAME
    by: dict = {}
    for s in role_members(rid[len("spec_"):]):
        by.setdefault(DS200_FAMILY.get(s), []).append(s)
    rows = [[link(ds_family_note(f), f"{f} {DS_FAMILY_KO[f]}"), ", ".join(ss)] for f, ss in by.items() if f]
    if REEL_NAME in by.get(None, []):
        rows.append([link(REEL_NOTE, REEL_KO), REEL_NAME])
    return ["## 맡은 계좌\n" + table(["계열", "정의"], rows),
            f"회의 방: **{GROUP_ROOM_TITLES.get('team:' + rid[len('spec_'):], '')}** · 할 수 있는 일: 메모·두 분께 알림·없음 "
            "(복제 계좌·5년 시험 없음, 결론은 팀장 요약). 딥시크·릴스 계좌는 60일 전 복제 없음\n"]


def ds_family_note(fam: str) -> str:
    from .groups import DS_FAMILY_KO
    return safe_name(f"딥시크 {fam} {DS_FAMILY_KO.get(fam, fam)}")


REEL_NOTE = "릴스 5분 단타"


def room_name_ko(room_id: str) -> str:
    """Plain Korean name of a room (no link)."""
    if room_id.startswith("strat:"):
        return STRATEGY_KO.get(room_id[6:], room_id)
    if room_id == "team:lab":
        return "새 매매법 연구실"
    if room_id in GROUP_ROOM_TITLES:
        return GROUP_ROOM_TITLES[room_id]
    t = room_id.split(":", 1)[-1]
    return team_note(t) if t in TEAM_NAME else room_id


def day_name(day: str) -> str:
    return f"회의 {day}"


def check_name(day: str) -> str:
    return f"점검 {day}"


def week_name(week: str) -> str:
    return f"주간 회의 {week}"


WEEKDAY_KO = "월화수목금토일"


def day_ko(day: str) -> str:
    import datetime as dt
    d = dt.date.fromisoformat(day)
    return f"{day} ({WEEKDAY_KO[d.weekday()]})"


# ------------------------------------------------------------------ context + vault
@dataclass
class Ctx:
    data: Data
    now_ms: int
    repo_dir: str
    strategies: tuple = tuple(STRATEGY_KO)
    run_start_ms: int = 0
    run_known: bool = False
    days: list = field(default_factory=list)            # every KST day with something to show, oldest first
    mentions: dict = field(default_factory=lambda: defaultdict(set))   # day -> strategy ids seen in meetings
    research: list = field(default_factory=list)         # research / rules documents read from the repo (part 2)
    research_by_sid: dict = field(default_factory=lambda: defaultdict(list))   # strategy id -> [note names]

    @property
    def gen(self) -> str:
        return kst_stamp(self.now_ms)

    @property
    def snap(self) -> str:
        return kst_stamp(self.data.snapshot_ms) if self.data.snapshot_ms else "자료 없음"

    @property
    def obs_end_ms(self) -> int:
        return self.run_start_ms + OBSERVE_DAYS * DAY_MS

    @property
    def cp1_ms(self) -> int:
        """00:00 UTC of day 30 after the run start (paperbot/checkpoint.py checkpoint_ts)."""
        return (self.run_start_ms // DAY_MS) * DAY_MS + PERIOD_DAYS * DAY_MS

    @property
    def day_no(self) -> int:
        """Whole days since the start (0 on the first day), at the data snapshot (or now)."""
        ref = self.data.snapshot_ms or self.now_ms
        return max(0, int((ref - self.run_start_ms) // DAY_MS))


def make_ctx(data: Data, now_ms: int, repo_dir: str) -> Ctx:
    import datetime as dt
    ctx = Ctx(data=data, now_ms=now_ms, repo_dir=repo_dir)
    if data.run_start_ms:
        ctx.run_start_ms, ctx.run_known = int(data.run_start_ms), True
    else:
        t = dt.datetime.strptime(FALLBACK_START, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        ctx.run_start_ms = int(t.timestamp() * 1000)
    days = set(data.day_trades)
    days |= {r["day"] for r in data.daily}
    days |= {r["kst_day"] for r in data.rounds if r.get("kst_day")}
    days |= {kst_day(n["ts"]) for n in data.notes}
    ctx.days = sorted(d for d in days if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)))
    return ctx


class Vault:
    """Collects generated notes (path -> text) and checks that every note name is unique."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.files: dict[str, str] = {}
        self.names: dict[str, str] = {}          # note name -> path
        self.canvases: dict[str, str] = {}

    def add(self, folder: str, name: str, body: str, *, type: str, tags: list, css: tuple = (), source: str = "code",
            props: Optional[dict] = None, sub: str = "", legend: str = "") -> str:
        name = safe_name(name)
        path = f"{folder}/{sub + '/' if sub else ''}{name}.md"
        if name in self.names:
            raise ValueError(f"duplicate note name {name!r}: {self.names[name]} and {path}")
        if folder == FOLDERS["mine"]:
            raise ValueError("the exporter never writes into 99 내 메모")
        fm = {"type": type, "tags": tags, "cssclasses": list(css), "source": source, **(props or {}),
              "generated_by": GENERATED_BY}
        stamp = (f'<div class="pb-stamp">자동 생성 {self.ctx.gen} · 자료 기준 {self.ctx.snap}'
                 f'{(" · " + legend) if legend else ""}</div>')
        self.files[path] = frontmatter(fm) + "\n" + stamp + "\n\n" + normalize_md(body.strip("\n")) + "\n"
        self.names[name] = path
        return name

    def add_raw(self, path: str, text: str) -> None:
        self.files[path] = text


def hero(title: str, sub: str = "") -> str:
    return callout("pb-hero", title, sub)


def stat_row(items: list[tuple[str, str]]) -> str:
    """A compact stat table: label row over value row."""
    return table([a for a, _ in items], [[b for _, b in items]], ["c"] * len(items))


LEGEND = (f"{badge('code')} = 코드가 계산한 숫자 · {badge('ai')} = AI 직원이 쓴 글(틀릴 수 있음) · "
          f"{badge('doc')} = 고정 문서 원문")


# ------------------------------------------------------------------ account helpers
def acct_status(ctx: Ctx, aid: str) -> str:
    e = ctx.data.engines.get(aid) or {}
    if e.get("bust"):
        return "파산"
    if e.get("halted"):
        return "정지"
    if aid in ctx.data.equity or aid in ctx.data.trade_stats:
        return "운영 중"
    return "대기"


def acct_equity(ctx: Ctx, aid: str) -> Optional[float]:
    eq = ctx.data.equity.get(aid)
    if eq and eq[0] is not None:
        return eq[0]
    e = ctx.data.engines.get(aid) or {}
    return num(e.get("wallet"))


def initial_equity(ctx: Ctx) -> float:
    return num(ctx.data.run_info.get("initial_equity")) or INITIAL


def strat_totals(ctx: Ctx, sid: str) -> dict:
    n = wins = liq = 0
    pnl = 0.0
    eqs, dds, busts = [], [], 0
    for tf in TFS:
        aid = f"{sid}@{tf}"
        st = ctx.data.trade_stats.get(aid)
        if st:
            n += st["n"]
            wins += st["wins"]
            liq += st["liq"]
            pnl += st["sum_pnl"]
        e = acct_equity(ctx, aid)
        if e is not None:
            eqs.append(e)
        eng = ctx.data.engines.get(aid) or {}
        dd = num(eng.get("max_drawdown"))
        if dd is not None:
            dds.append(dd)
        busts += bool(eng.get("bust"))
    ini = initial_equity(ctx)
    return {"n": n, "wins": wins, "liq": liq, "pnl": pnl, "accounts": len(eqs), "busts": busts,
            "equity_mean": mean(eqs), "ret": (mean(eqs) / ini - 1) if eqs else None,
            "dd_max": max(dds) if dds else None}


# ------------------------------------------------------------------ strategy profiles (research/strategy_profiles)
def load_profiles(repo: str) -> dict:
    """{strategy id: {"style", "least_bad", "rows": [[cells]], "headers": [...]}} from PROFILES.md."""
    txt = read_text(os.path.join(repo, "research", "strategy_profiles", "PROFILES.md"))
    out: dict = {}
    if not txt:
        return out
    for head, lv, body in split_sections(txt):
        m = re.search(r"\((\w+)\)\s*$", head)
        if lv != 2 or not m:
            continue
        sid = m.group(1)
        style = least = ""
        rows, headers = [], []
        for ln in body:
            if ln.startswith("- 성격:"):
                style = ln[len("- 성격:"):].strip()
            elif ln.startswith("- 5년 기준"):
                least = ln.split(":", 1)[-1].strip() if ":" in ln else ln
            elif ln.startswith("|"):
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if cells and cells[0] in ("봉",):
                    headers = cells
                elif cells and not set(cells[0]) <= set("-: "):
                    if cells[0] != "5분":                       # 5-minute accounts were removed on 2026-10-04
                        rows.append(cells)
        out[sid] = {"style": style, "least_bad": least, "headers": headers, "rows": rows}
    return out


# ================================================================== 02 strategies
SHADOW_KO = {
    "lock15": ("첫 잠금 15%", "첫 익절 잠금을 10%에서 15%로"), "lock20": ("첫 잠금 20%", "첫 익절 잠금을 20%로"),
    "lock30": ("첫 잠금 30%", "첫 익절 잠금을 30%로"), "timestop": ("시간 청산", "잠금이 안 걸리면 N봉 뒤 청산"),
    "lev10": ("10배 고정", "항상 10배"), "lev20": ("20배 고정", "항상 20배"), "lev30": ("30배 고정", "항상 30배"),
    "lev40": ("40배 고정", "항상 40배"), "lev50": ("50배 고정", "항상 50배"),
    "stopw1.5": ("손절 1.5 ATR", "처음 손절을 1.5 ATR로"), "stopw2.5": ("손절 2.5 ATR", "처음 손절을 2.5 ATR로"),
    "stopw3": ("손절 3 ATR", "처음 손절을 3 ATR로"),
    "tp1R": ("고정 익절 1R", "계단 잠금 없이 1R에서 익절"), "tp1.5R": ("고정 익절 1.5R", "계단 잠금 없이 1.5R에서 익절"),
    "tp2R": ("고정 익절 2R", "계단 잠금 없이 2R에서 익절"), "tp3R": ("고정 익절 3R", "계단 잠금 없이 3R에서 익절"),
    "ladder_cap2R": ("잠금 + 2R 상한", "계단 잠금에 2R 익절 상한 추가"),
    "quality": ("진입 품질 규칙", "진입 품질로 크기를 정했다면"), "limit": ("지정가 진입", "신호가보다 0.25 ATR 유리하게 지정가"),
}
SHADOW_ORDER = ("lock15", "lock20", "lock30", "timestop", "lev10", "lev20", "lev30", "lev40", "lev50", "stopw1.5",
                "stopw2.5", "stopw3", "tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_cap2R", "quality", "limit")


def shadow_table(items: dict) -> str:
    rows = []
    for k in SHADOW_ORDER:
        v = items.get(k)
        if not v:
            continue
        name, what = SHADOW_KO[k]
        unit = "자금 대비" if v["unit"] == "equity" else "ROE"
        rows.append([f"`{k}` {name}", what, v["n"], f"{pct(v['mean'], 2)} ({unit})", f"{pct(v['base'], 2)}",
                     pct(v["diff"], 2), small_flag(v["n"]) or "-"])
    return table(["그림자", "뜻", "같은 거래 수", "그림자 평균", "실제(base) 평균", "차이", "표본"], rows,
                 ["l", "l", "r", "r", "r", "r", "l"])


def build_strategies(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    profiles = load_profiles(ctx.repo_dir)
    notes_by = defaultdict(list)
    for n in d.notes:
        sid = n.get("strategy") or ""
        if sid:
            notes_by[sid].append(n)
    hyp_by = defaultdict(list)
    for h in d.hypotheses:
        if h.get("strategy"):
            hyp_by[h["strategy"]].append(h)
    trials_by = defaultdict(list)
    for t in d.trials:
        if t.get("strategy"):
            trials_by[t["strategy"]].append(t)
    meet_by = defaultdict(lambda: defaultdict(list))        # sid -> trigger -> [days]
    for r in d.rounds:
        if r["room_id"].startswith("strat:"):
            meet_by[r["room_id"][6:]][r["trigger"]].append(r["kst_day"])
    rows_hub = []
    ini = initial_equity(ctx)
    for sid, ko in STRATEGY_KO.items():
        tot = strat_totals(ctx, sid)
        prof = profiles.get(sid) or {}
        body = [hero(f"{ko}", f"{sid} · 매매법 카드 · 이번 실험 기록과 연구 메모"),
                f"{LEGEND}\n"]
        status_kind = "info"
        if tot["busts"]:
            status_kind = "danger"
        small = tot["n"] < 10
        body.append(callout(
            "pb-stat", "한눈에 (현재 숫자, 결론 아님)",
            stat_row([("거래", f"{tot['n']}건"), ("평균 평가금", usd(tot["equity_mean"])),
                      ("시작 대비", pct(tot["ret"], 1) if tot["ret"] is not None else "-"),
                      ("최대 낙폭", pct(tot["dd_max"], 1, False) if tot["dd_max"] is not None else "-"),
                      ("파산 계좌", f"{tot['busts']}/4")]).rstrip()
            + f"\n\n{badge('code')} " + (badge("small") + " " + small_flag(tot["n"]) if small_flag(tot["n"]) else "")))
        body.append("")
        if prof.get("style"):
            body.append(f"**5년 성격**: {sanitize(prof['style'])}\n")
        body.append("## 이번 실험 기록 " + badge("code"))
        rows = []
        for tf in TFS:
            aid = f"{sid}@{tf}"
            st = d.trade_stats.get(aid)
            n = st["n"] if st else 0
            e = acct_equity(ctx, aid)
            eng = d.engines.get(aid) or {}
            rows.append([TF_KO[tf], acct_status(ctx, aid), usd(e), pct(e / ini - 1, 1) if e is not None else "-", n,
                         pct(st["wins"] / n, 0, False) if n else "-", pct(st["sum_roe"] / n, 1) if n else "-",
                         st["liq"] if st else "-", pct(eng.get("max_drawdown"), 1, False) if eng.get("max_drawdown") is not None else "-",
                         small_flag(n) or "-"])
        body.append(table(["봉", "상태", "평가금", "시작 대비", "거래", "승률", "거래당 평균 ROE", "청산(LIQ)", "최대 낙폭",
                           "표본"], rows, ["l", "l", "r", "r", "r", "r", "r", "r", "r", "l"]))
        if not tot["n"]:
            body.append(callout("pb-soft", "아직 끝난 거래가 없습니다", "거래가 쌓이면 이 표가 채워집니다. 이 매매법은 신호가 드물 수 있습니다."))
        # best / normal
        body.append("## 좋은 자리 vs 보통 (진입 품질) " + badge("code"))
        trs = []
        for tier, label in (("best", "좋은 자리 (best)"), ("normal", "보통 (normal)")):
            st = d.tier_stats.get((sid, tier))
            if not st:
                trs.append([label, 0, "-", "-", "-", "-", small_flag(0)])
                continue
            n = st["n"]
            lev = " · ".join(f"{k}배 {c}" for k, c in sorted(st["lev"].items(), reverse=True))
            trs.append([label, n, pct(st["wins"] / n, 0, False), pct(st["sum_roe"] / n, 1),
                        fnum(st["sum_r"] / st["n_r"] * 100, 2) + "%" if st["n_r"] else "-", lev or "-",
                        small_flag(n) or "-"])
        body.append(table(["묶음", "거래", "승률", "거래당 평균 ROE", "노출당 수익 r", "쓴 레버리지(건수)", "표본"], trs,
                          ["l", "r", "r", "r", "r", "l", "l"]))
        body.append(callout("pb-soft", "읽는 법",
                            "r = 손익 ÷ (증거금 × 레버리지): 노출 1단위당 수익입니다. 좋은 자리가 보통보다 나은지는 "
                            "30일 체크포인트에서 미리 정한 방법(" + link("레버리지 규칙 B 평가 방법") + ")으로만 판정합니다. "
                            "지금 숫자는 중간 기록이며 결론이 아닙니다."))
        # shadows
        body.append("## 그림자 비교 (같은 거래끼리) " + badge("code"))
        sh = d.shadow_by_strategy.get(sid) or {}
        if sh:
            body.append(shadow_table(sh))
            body.append(callout("pb-soft", "읽는 법",
                                "그림자는 계좌 없이 기록만 하는 '만약 이렇게 했다면'입니다. 같은 거래에서 그림자와 실제(base)의 평균을 "
                                "비교했습니다. 차이가 +이면 그림자가 나았다는 뜻이지만 거래가 적으면 우연일 수 있습니다. "
                                "규칙은 30일 동안 바뀌지 않습니다. 같은 자료로 규칙을 고르면 안 되므로, 좋아 보이는 그림자는 "
                                "새 계좌로 따로 확인합니다(" + link("교훈과 가설") + ")."))
        else:
            body.append("아직 그림자 비교 자료가 없습니다 (밤 점검이 돌면 채워집니다).\n")
        # profile
        body.append("## 5년 성격 카드 " + badge("doc"))
        if prof.get("rows"):
            body.append(f"성격: {sanitize(prof['style'])}\n\n가장 덜 나쁜 봉: {sanitize(prof['least_bad'])}\n")
            body.append(table(prof["headers"], prof["rows"]))
            body.append(callout("pb-soft", "냉정하게", "과거 5년에서 거의 모든 칸의 거래당 평균이 마이너스였습니다. "
                                "이 카드는 매매법의 성격을 보여줄 뿐 실력의 증거가 아닙니다. 원문: " + link("5년 매매법 성격 카드")))
        else:
            body.append("5년 성격 카드 자료(research/strategy_profiles/PROFILES.md)를 읽지 못했습니다.\n")
        rs_ = ctx.research_by_sid.get(sid, [])
        if rs_:
            body.append("## 관련 연구 " + badge("doc"))
            body.append(" · ".join(link(n) for n in rs_[:12]) + "\n")
        # hypotheses / trials
        body.append("## 가설과 시험")
        hs = hyp_by.get(sid, [])
        if hs:
            body.append(f"가설 {len(hs)}개 {badge('ai')} (최근 8개):\n")
            for h in hs[-8:][::-1]:
                body.append(f"- {link(hyp_name(h))} — {status_ko(h)}")
        else:
            body.append("이 매매법에 적힌 가설은 아직 없습니다.")
        ts = trials_by.get(sid, [])
        if ts:
            body.append(f"\n시험 장부에 {len(ts)}건 — " + link("시험 장부"))
        # meetings
        body.append("\n## 관련 회의")
        mm = meet_by.get(sid)
        if mm:
            alld = sorted({x for v_ in mm.values() for x in v_})
            body.append(f"이 매매법 방에서 열린 회의 {sum(len(x) for x in mm.values())}번 " +
                        " · ".join(f"{trigger_ko(t)} {len(x)}" for t, x in sorted(mm.items())))
            body.append("\n최근 날짜: " + " · ".join(link(day_name(x), x) for x in alld[-6:][::-1]))
        else:
            body.append("아직 이 매매법 방의 회의가 없습니다.")
        mentioned = sorted({x for x, ids in ctx.mentions.items() if sid in ids})
        if mentioned:
            body.append("\n회의 기록에 이름이 나온 날: " + " · ".join(link(day_name(x), x) for x in mentioned[-6:][::-1]))
        # notes
        ns = notes_by.get(sid, [])
        body.append("\n## 에이전트 메모 " + badge("ai"))
        if ns:
            for n in ns[-4:][::-1]:
                body.append(callout("quote", f"{kst_min(n['ts'])} · {ko} 전담", sanitize(n["text"], 500)))
        else:
            body.append("아직 메모가 없습니다.")
        spec = f"spec_{sid}"
        body.append(f"\n## 연결\n담당: {link(team_note('specialist'), ko + ' 전담')} (AI) · {link('매매법 목록')} · {link('직원 목록')} · {link('홈')}")
        v.add(FOLDERS["strat"], strat_name(sid), "\n".join(body), type="전략",
              tags=["전략", "매매법"], css=("pb-strategy",), source="mixed",
              props={"strategy": sid, "name_ko": ko, "timeframe": list(TFS),
                     "status": ("파산 있음" if tot["busts"] else ("관찰 중" if tot["n"] else "거래 없음")),
                     "n_trades": tot["n"], "small_sample": small, "style": prof.get("style", "").split("(")[0].strip("* ") or None,
                     "aliases": [ko, sid]},
              legend="코드 계산 + AI 작성(표시됨)")
        rows_hub.append((sid, ko, tot))
    build_strategy_hub(v, rows_hub, profiles)
    build_coin_flips(v)
    build_extra_accounts(v)


def status_ko(h: dict) -> str:
    res = h.get("result")
    spec = h.get("spec") if isinstance(h.get("spec"), dict) else {}
    if not isinstance(spec.get("prediction"), dict):
        return "채점 안 함(예측 없음)"
    if res is None:
        return "채점 대기"
    if res.get("status") == "expired":
        return "기한 만료"
    return "맞음" if res.get("correct") else "틀림"


def hyp_name(h: dict) -> str:
    return f"가설 {int(h['id']):04d} {h.get('strategy') or '전체'}"


def build_strategy_hub(v: Vault, rows: list, profiles: dict) -> None:
    ctx, d = v.ctx, v.ctx.data
    tbl = []
    for sid, ko, t in rows:
        prof = profiles.get(sid) or {}
        sty = re.sub(r"\*\*|\(.*", "", prof.get("style", "")).strip() or "-"
        tbl.append([strat_link(sid), sid, sty, t["n"], usd(t["equity_mean"]),
                    pct(t["ret"], 1) if t["ret"] is not None else "-", t["busts"], small_flag(t["n"]) or "-"])
    n_all = sum(t["n"] for _, _, t in rows)
    body = [hero("매매법 36개", "한 매매법 = 4개 봉(15분·30분·1시간·4시간) 계좌. 이름을 누르면 카드가 열립니다."),
            LEGEND + "\n",
            callout("warning", "순위가 아닙니다", "표는 매매법 번호순입니다. 어느 매매법이 실력이 있는지는 30일 체크포인트에서 "
                    "코드가 판정합니다(" + METHOD_KO + ", " + link("체크포인트 판정") + "). 지금 숫자는 중간 기록입니다."),
            stat_row([("매매법", "36"), ("계좌", f"{sum(1 for a in d.accounts.values() if a['kind'] == 'strategy') or V4_GROUP_ACCOUNTS['core']}"),
                      ("지금까지 끝난 거래", f"{n_all}건"), ("시작 금액", usd(initial_equity(ctx)))]),
            "## 전체 표 " + badge("code"),
            table(["매매법", "번호", "5년 성격", "거래", "평균 평가금", "시작 대비", "파산 계좌", "표본"], tbl,
                  ["l", "l", "l", "r", "r", "r", "r", "l"]),
            "## 함께 보기\n- " + link("딥시크·릴스") + " (딥시크 44개 정의 · 릴스 5분 단타, 따로 판정)\n- "
            + link("동전 던지기 봇") + " (비교 기준 12개)\n- " + link("추가 계좌") +
            "\n- " + link("5년 매매법 성격 카드") + "\n- " + link("직원 목록") + "\n- " + link("홈")]
    v.add(FOLDERS["strat"], "매매법 목록", "\n".join(body), type="허브", tags=["허브", "전략"], css=("pb-hub",),
          source="code", props={"n_strategies": 36})


def build_coin_flips(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    ini = initial_equity(ctx)
    rows = []
    for aid, a in sorted(d.accounts.items()):
        if a["kind"] != "random":
            continue
        st = d.trade_stats.get(aid)
        n = st["n"] if st else 0
        e = acct_equity(ctx, aid)
        rows.append([aid, TF_KO.get(a["timeframe"], a["timeframe"]), acct_status(ctx, aid), usd(e),
                     pct(e / ini - 1, 1) if e is not None else "-", n, pct(st["wins"] / n, 0, False) if n else "-",
                     small_flag(n) or "-"])
    body = [hero("동전 던지기 봇", "실력이 없는 봇이 우연히 얼마나 버는지 보는 기준선"),
            f"동전 던지기 봇은 봉마다 3개씩 모두 {V4_GROUP_ACCOUNTS['flip']}개입니다(5분봉 3개 포함). 신호도 방향도 우연으로 뽑고, 손절·계단 익절·레버리지 규칙은 "
            "매매법과 같습니다(5분봉 동전 3개는 릴스와 같은 자기 청산으로 릴스의 비교용). 매매법이 이 봇들보다 낫다는 것만으로는 "
            "부족하고, 30일 체크포인트에서 코드가 판정합니다: " + METHOD_KO + " (" + link("체크포인트 판정") + ").\n",
            f"## {sum(1 for a in d.accounts.values() if a['kind'] == 'random') or V4_GROUP_ACCOUNTS['flip']}개 계좌 "
            + badge("code"),
            table(["계좌", "봉", "상태", "평가금", "시작 대비", "거래", "승률", "표본"], rows,
                  ["l", "l", "l", "r", "r", "r", "r", "l"]) or "아직 계좌 자료가 없습니다.\n",
            "\n" + link("매매법 목록") + " · " + link("홈")]
    v.add(FOLDERS["strat"], "동전 던지기 봇", "\n".join(body), type="전략", tags=["전략", "기준선"], css=("pb-strategy",),
          source="code", props={"n_trades": sum(s["n"] for a, s in d.trade_stats.items()
                                                if d.accounts.get(a, {}).get("kind") == "random")})


def build_extra_accounts(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    from .accounts import ORIGINAL_KINDS
    rows = []
    for aid, a in sorted(d.accounts.items()):
        if a["kind"] in ORIGINAL_KINDS:          # the originals of every group (DeepSeek, the reel too) are not extras
            continue
        st = d.trade_stats.get(aid)
        e = acct_equity(ctx, aid)
        rows.append([aid, a["kind"], a.get("parent") or "-", usd(e), st["n"] if st else 0])
    props = d.proposals
    prow = [[p["id"], kst_min(p["ts"]), p.get("strategy") or "-", (p.get("change") or {}).get("kind", "copy"),
             p["status"], p.get("decided_by") or "-"] for p in props[-30:]]
    body = [hero("추가 계좌와 제안", f"에이전트가 제안해 승인된 복사 계좌·새 매매법 계좌(원본 {V4_ACCOUNTS}개와 따로 셈)"),
            "원본 계좌는 에이전트가 바꿀 수 없습니다. 개선안은 코드 관문(5년 시험)을 통과하고 승인된 것만 **새 계좌**로 따로 "
            "돌립니다. 관찰 기간(시작 후 21일) 동안은 복사 제안이 없습니다.\n",
            "## 추가 계좌 " + badge("code"),
            table(["계좌", "종류", "부모", "평가금", "거래"], rows) or "아직 추가 계좌가 없습니다.\n",
            "## 제안 기록 " + badge("code"),
            table(["번호", "시각", "매매법", "종류", "상태", "결정자"], prow) or "아직 제안이 없습니다.\n",
            "\n" + link("시험 장부") + " · " + link("매매법 목록") + " · " + link("홈")]
    v.add(FOLDERS["strat"], "추가 계좌", "\n".join(body), type="전략", tags=["전략", "제안"], css=("pb-strategy",),
          source="code")


# ================================================================== 03 staff
def build_staff(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    score = {r["role"]: r for r in (d.scorecard.get("roles") or [])}
    team_roles = defaultdict(list)
    for r in ROLES:
        team_roles[r[2]].append(r)
    for tid, tname in TEAMS:
        rs = team_roles.get(tid, [])
        rows = []
        if tid == "specialist":
            for sid, ko in STRATEGY_KO.items():
                rows.append([strat_link(sid, f"{ko} 전담"), "sonnet", "손절 즉시(긴급만), 주 1회"])
            for g in GROUP_SPECIALISTS:           # paper v4: DeepSeek families and the reel
                rows.append([link(role_note(g[0]), g[1]), g[3], g[4]])
            rows_t = table(["전담", "모델", "일하는 때"], rows)
        else:
            for r in rs:
                cnt = d.room_messages.get(r[0], [0, 0])
                rows.append([link(role_note(r[0]), r[1]), r[3], r[4], cnt[0], r[6]])
            rows_t = table(["역할", "모델", "일하는 때", "발언 수", "시작"], rows, ["l", "l", "l", "r", "l"])
        n_t = len(rs) if tid != "specialist" else 36 + len(GROUP_SPECIALISTS)
        body = [hero(tname, f"역할 {n_t}명 · 직원 조직도의 한 칸"
                     + (f" (매매법 전담 36명 + 딥시크·릴스 담당 {len(GROUP_SPECIALISTS)}명)" if tid == "specialist" else "")),
                rows_t, "\n" + link("조직도") + " · " + link("직원 목록")]
        v.add(FOLDERS["staff"], team_note(tid), "\n".join(body), type="직원", tags=["직원", "팀"], css=("pb-staff",),
              sub="팀", props={"team": tid, "n_roles": n_t}, source="doc")
    for r in ROLES + GROUP_SPECIALISTS:
        rid, name, tid, model, when, duty, start = r
        cnt = d.room_messages.get(rid, [0, 0])
        calls = d.calls_by_role.get(rid, [0, 0])
        sc = score.get(rid)
        body = [hero(name, f"{TEAM_NAME[tid]} · 모델 {model} · {when}"),
                f"**하는 일**: {duty}\n", f"**시작 조건**: {'실험 시작부터' if start == 'now' else start}\n"] + group_role_lines(rid) + [
                "## 활동 기록 " + badge("code"),
                stat_row([("방에서 발언", f"{cnt[0]}번"), ("마지막 발언", kst_min(cnt[1]) if cnt[1] else "-"),
                          ("AI 호출", f"{calls[0]}회"), ("사용 토큰", f"{calls[1]:,}")])]
        if sc:
            gr = sc["graded"]
            body.append("## 가설 채점 " + badge("code") + f"\n채점된 가설 {gr}개 중 {sc['correct']}개 맞음"
                        + (f" (적중률 {pct(sc['hit_rate'], 0, False)})" if sc["hit_rate"] is not None else "")
                        + f" · 기다리는 중 {sc['waiting']} · 만료 {sc['expired']}"
                        + (f"\n\n{badge('small')} 채점이 {gr}개뿐이라 적중률은 우연일 수 있습니다." if gr < 10 else ""))
        last = [m for ms in d.messages.values() for m in ms if m["role"] == rid
                and m["kind"] in ("analysis", "challenge", "expert", "summary", "revision")]
        if last:
            body.append("## 최근 발언 " + badge("ai"))
            for m in sorted(last, key=lambda m: m["id"])[-3:][::-1]:
                body.append(callout("quote", kst_min(m["ts"]) + " · " + room_name_ko(m["room_id"]), sanitize(m["text"], 400), "-"))
        body.append("\n" + link(team_note(tid)) + " · " + link("조직도") + " · " + link("직원 성적표") + " · " + link("직원 목록"))
        v.add(FOLDERS["staff"], role_note(rid), "\n".join(body), type="직원", tags=["직원", "역할"], css=("pb-staff",),
              sub="역할", source="mixed", props={"role": rid, "team": tid, "model": model,
                                                   "n_statements": cnt[0], "small_sample": cnt[0] < 10},
              legend="코드 계산 + AI 작성(표시됨)")
    # scorecard
    srows = []
    for r in ROLES + GROUP_SPECIALISTS:
        cnt = d.room_messages.get(r[0], [0, 0])
        calls = d.calls_by_role.get(r[0], [0, 0])
        sc = score.get(r[0])
        srows.append([link(role_note(r[0]), r[1]), TEAM_NAME[r[2]], cnt[0], calls[0],
                      f"{calls[1]:,}", (f"{sc['correct']}/{sc['graded']}" if sc else "-"),
                      (pct(sc["hit_rate"], 0, False) if sc and sc["hit_rate"] is not None else "-"),
                      small_flag(sc["graded"]) if sc and sc["graded"] < 10 else "-"])
    tot = d.scorecard.get("total") or {}
    body = [hero("직원 성적표", "발언 수와 가설 적중률 (코드 계산). 적중률은 채점된 예측만 셉니다."), LEGEND + "\n",
            stat_row([("채점된 가설", str(tot.get("graded", 0))), ("맞음", str(tot.get("correct", 0))),
                      ("기다리는 중", str(tot.get("waiting", 0))), ("만료", str(tot.get("expired", 0))),
                      ("예측 없음", str(tot.get("not_gradable", 0)))]),
            table(["역할", "팀", "발언", "AI 호출", "토큰", "맞음/채점", "적중률", "표본"], srows,
                  ["l", "l", "r", "r", "r", "r", "r", "l"]),
            callout("warning", "읽는 법", "적중률은 10개 이상 채점돼야 의미를 두기 시작합니다. 그 전에는 모두 '표본 적음'입니다. "
                    "채점은 가설을 쓴 뒤 들어간 거래 30~300건으로 코드가 한 번만 합니다."),
            "\n" + link("교훈과 가설") + " · " + link("직원 목록")]
    v.add(FOLDERS["staff"], "직원 성적표", "\n".join(body), type="직원", tags=["직원", "성적"], css=("pb-staff",),
          source="code")
    # hub
    trows = []
    for tid, tname in TEAMS:
        n = len(team_roles.get(tid, [])) if tid != "specialist" else 36 + len(GROUP_SPECIALISTS)
        trows.append([link(team_note(tid), tname), n,
                      ", ".join(link(role_note(r[0]), r[1]) for r in team_roles.get(tid, [])[:4]) if tid != "specialist" else
                      "36개 매매법별 전담 + " + ", ".join(link(role_note(g[0]), g[1]) for g in GROUP_SPECIALISTS)])
    mrows = [[name, when] for _, name, when in MEETINGS]
    body = [hero(f"직원 {len(ALL_ROLES)}명", f"역할 36명 + 매매법 전담 36명 + 딥시크·릴스 담당 {len(GROUP_SPECIALISTS)}명, 12개 팀. "
                 "모두 AI이고 주문은 낼 수 없습니다."),
            "에이전트는 **읽고 의견을 낼 뿐** 주문을 내지 않고 원본 계좌와 규칙을 바꾸지 못합니다. 숫자는 코드가 계산하고, "
            "직원은 그 숫자를 읽고 해석합니다.\n",
            "## 팀\n" + table(["팀", "인원", "주요 역할"], trows, ["l", "r", "l"]),
            "## 정기 회의\n" + table(["회의", "때"], mrows),
            "## 바로가기\n- " + link("조직도") + " (그림)\n- " + link("직원 성적표") + "\n- " + link("회의 목록") + "\n- " + link("홈")]
    v.add(FOLDERS["staff"], "직원 목록", "\n".join(body), type="허브", tags=["허브", "직원"], css=("pb-hub",), source="doc")
    # org chart
    lines = ["flowchart TD", '  owners(["두 분 (사장님)"])', '  lead{{"⑥ 총괄 · 팀장"}}', "  owners --> lead"]
    for tid, tname in TEAMS:
        if tid == "lead":
            continue
        lines.append(f'  subgraph g_{tid}["{tname}"]')
        lines.append("    direction TB")
        if tid == "specialist":
            lines.append('    spec_all["매매법 전담 36명<br/>(매매법마다 1명)"]')
            lines.append(f'    spec_v4["딥시크·릴스 담당 {len(GROUP_SPECIALISTS)}명<br/>(계열·릴스마다 1명)"]')
        else:
            for r in team_roles.get(tid, []):
                lines.append(f'    r_{r[0]}["{r[1]}"]')
        lines.append("  end")
        lines.append(f"  lead --> g_{tid}")
    lines.append('  code(["코드 (숫자 계산·주문 없음)"])')
    lines.append("  code -.-> lead")
    body = [hero("조직도", "12개 팀. 화살표는 보고 방향이 아니라 '팀장이 회의 결과를 모아 두 분께 전한다'는 흐름입니다."),
            mermaid("\n".join(lines)),
            "캔버스 버전(클릭하면 팀 노트가 열림): `조직도.canvas`\n\n" + link("직원 목록") + " · " + link("홈")]
    v.add(FOLDERS["staff"], "조직도", "\n".join(body), type="직원", tags=["직원", "그림"], css=("pb-staff",), source="doc")
    v.canvases[f"{FOLDERS['staff']}/조직도.canvas"] = org_canvas(v)


def _canvas_edge(i, a, b, label=None, color=None):
    e = {"id": f"e{i}", "fromNode": a, "fromSide": "bottom", "toNode": b, "toSide": "top"}
    if label:
        e["label"] = label
    if color:
        e["color"] = color
    return e


def org_canvas(v: Vault) -> str:
    import json
    nodes, edges = [], []
    nodes.append({"id": "owners", "type": "text", "text": "**두 분 (사장님)**\n최종 결정은 두 분", "x": -140, "y": -420,
                  "width": 280, "height": 90, "color": "6"})
    lead_note = f"{FOLDERS['staff']}/역할/{role_note('team_lead')}.md"
    nodes.append({"id": "lead", "type": "file", "file": lead_note, "x": -140, "y": -260, "width": 280, "height": 90,
                  "color": "5"})
    edges.append(_canvas_edge(0, "owners", "lead"))
    teams = [t for t in TEAMS if t[0] != "lead"]
    cols = 4
    for i, (tid, tname) in enumerate(teams):
        row, col = divmod(i, cols)
        x = (col - 1.5) * 330
        y = -80 + row * 200
        nid = f"t_{tid}"
        nodes.append({"id": nid, "type": "file", "file": f"{FOLDERS['staff']}/팀/{team_note(tid)}.md", "x": int(x),
                      "y": y, "width": 280, "height": 140, "color": "4" if tid != "specialist" else "3"})
        edges.append(_canvas_edge(i + 1, "lead", nid))
    return json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=1)


# ================================================================== 01 experiment
RULES_ROWS = [
    ("계좌", f"매매법 36개 × 봉 4개 = {V4_GROUP_ACCOUNTS['core']}개 + 딥시크 {V4_GROUP_ACCOUNTS['ds200']}개 + 릴스 5분 단타 "
            f"{V4_GROUP_ACCOUNTS['reel']}개 + 동전 던지기 {V4_GROUP_ACCOUNTS['flip']}개(5분봉 포함), 합계 **{V4_ACCOUNTS}개**. "
            "계좌마다 $5,000, 충전 없음"),
    ("코인", "BTC, ETH, SOL, DOGE, LTC, BCH 6개 (XRP는 신호 기록만, 일봉은 신호만)"),
    ("진입", "확정된 봉에서 신호 계산 → 그 순간 시장가 + 슬리피지 0.02%. 계좌마다 포지션 1개, 코인 순서 BTC → ETH → SOL → DOGE → LTC → BCH"),
    ("손절", "진입가 − 방향 × 2 × ATR14 (신호 봉; 하우스 청산 계좌)"),
    ("익절", "계단 잠금: 순 ROE +12%에서 +10% 잠금, +17%에서 +15%, 이후 5%마다. 잠금은 올라가기만 함. 고정 익절·시간 청산 없음 "
           "(하우스 청산: 매매법 36개·딥시크·15분~4시간 동전·추가 계좌)"),
    ("릴스·5분봉 동전 청산", EXITS_KO["reel"] + " · " + EXITS_KO["flip"].split(" / ")[0]),
    ("레버리지·증거금", "**규칙 B (2026-10-04)**: 진입 품질 'best' 신호는 50배·증거금 50% → 안 되면 40배·40% → 30배·30% → 20배·20%. 나머지 신호는 30배·30% → 20배·20%"),
    ("크기 조건", "거래소 레버리지 구간 허용 + 손절이 청산가보다 max(1 ATR, 0.2%) 안쪽 + 손절 손실(비용 포함) ≤ 자금의 15%. 모두 안 되면 진입하지 않고 이유를 기록"),
    ("파산", "자금 $10 미만이면 그 계좌 정지"),
    ("비용", "수수료 0.05%, 슬리피지 0.02%, 펀딩은 실제 펀딩비와 실제 시각"),
    ("관찰 기간", "시작 후 21일 동안은 복사·새 계좌 제안이 없습니다"),
    ("체크포인트", "시작 후 30, 60, 90 … 180일. 계좌(매매법 × 봉)마다 거래 30건을 넘긴 첫 판정일에 1차 판정. "
                  f"{METHOD_KO}. 1차 판정 대상은 그룹마다 따로(매매법 {V4_GROUP_JUDGED['core']}개 · 딥시크 "
                  f"{V4_GROUP_JUDGED['ds200']}개 · 5분 단타 {V4_GROUP_JUDGED['reel']}개), 4시간은 관찰용"),
    ("30일 고정", "새 시작부터 **30일 동안 규칙과 매매 코드는 그대로**입니다. 바꾸려면 다음 버전(v5)으로 올리고 새 계좌로만 돌립니다"),
]


def build_experiment(v: Vault) -> None:
    ctx, d = v.ctx, v.ctx.data
    start = ctx.run_start_ms
    obs_end, cp1 = ctx.obs_end_ms, ctx.cp1_ms
    ref = d.snapshot_ms or ctx.now_ms
    day_no = ctx.day_no
    day_show = min(day_no + 1, PERIOD_DAYS)
    info = d.run_info
    # rules at a glance
    body = [hero("실험 규칙 한눈에", "paper v4 규칙의 요약 (v3 규칙에서 이어받은 것 포함). 원문은 08 규칙·문서."), LEGEND + "\n",
            table(["항목", "내용"], [[a, b] for a, b in RULES_ROWS]),
            callout("info", "원문", f"{link('규칙 본문 v4')} · {link('판정 방법 v4')} · {link('레버리지 규칙 B 평가 v4')} · "
                    f"{link('규칙 변경 1 (2026-10-04)')} · {link('규칙 본문 v3')} · {link('규칙 보충안')} · "
                    f"{link('레버리지 규칙 B 평가 방법')} · {link('규칙 문서 목록')}"),
            callout("warning", "30일 전에는 결론이 없습니다",
                    "첫 체크포인트(시작 후 30일) 전의 모든 숫자는 중간 기록입니다. 어느 매매법이 좋다·나쁘다는 판정은 "
                    "코드가 체크포인트에서만 합니다."),
            "\n" + link("실험 개요") + " · " + link("타임라인") + " · " + link("레버리지 계단")]
    v.add(FOLDERS["exp"], "실험 규칙 한눈에", "\n".join(body), type="규칙", tags=["규칙", "실험"], css=("pb-rules",), source="doc")
    # leverage ladder
    ladder = """flowchart TD
  S(["신호 발생 (봉 마감)"]) --> Q{"진입 품질 점수 4 이상?<br/>(5년 5분위 평균)"}
  Q -->|"예: 좋은 자리 best"| B50["50배 · 증거금 50%"]
  Q -->|"아니오 또는 점수 없음: 보통 normal"| N30["30배 · 증거금 30%"]
  B50 -->|"크기 조건 안 되면"| B40["40배 · 40%"]
  B40 -->|"안 되면"| B30["30배 · 30%"]
  B30 -->|"안 되면"| B20["20배 · 20%"]
  N30 -->|"안 되면"| N20["20배 · 20%"]
  B20 -->|"안 되면"| X(["진입 안 함<br/>이유를 기록"])
  N20 -->|"안 되면"| X
  B50 -->|"되면"| E(["진입"])
  B40 -->|"되면"| E
  B30 -->|"되면"| E
  B20 -->|"되면"| E
  N30 -->|"되면"| E
  N20 -->|"되면"| E"""
    cmp_tbl = table(["", "이전 규칙(~2026-10-04)", "규칙 B (지금)"],
                    [["모든 신호", "40%×50배 → 40%×40배 → 30%×30배 → 20%×20배", "-"],
                     ["좋은 자리(best)", "-", "50%×50배 → 40%×40배 → 30%×30배 → 20%×20배"],
                     ["나머지", "-", "30%×30배 → 20%×20배"]])
    body = [hero("레버리지 계단", "진입 품질로 좋은 자리에서만 크게 (규칙 B, 두 분 결정 'B로 가자')"),
            mermaid(ladder),
            "**'크기 조건'** = 거래소 레버리지 구간 허용 + 손절이 청산가보다 충분히 안쪽 + 손절 손실 ≤ 자금의 15%.\n",
            cmp_tbl,
            callout("info", "진입 품질이란",
                    "신호 때 기록한 진입 세기를 5년 진입 연구의 5분위 경계에 대어 1~5점을 매기고 평균이 4 이상이면 best입니다. "
                    "점수를 못 내는 신호(세기 기록 없음 등)는 보통으로 갑니다. 동전 던지기 봇은 봉별 확률(약 21%)로 best를 뽑습니다."),
            callout("warning", "30일 판정",
                    "좋은 자리가 보통보다 노출당 수익이 낫고(p ≤ 0.10) 동전 봇보다도 나으면 규칙 B를 다음 30일도 유지하고, "
                    "아니면 다음 창은 모든 신호 20배·증거금 20% 고정입니다. 그 전 숫자는 중간 기록입니다."),
            "\n근거: " + link("규칙 변경 1 (2026-10-04)") + " · " + link("레버리지 규칙 B 평가 방법") + " · " + link("실험 규칙 한눈에")]
    v.add(FOLDERS["exp"], "레버리지 계단", "\n".join(body), type="규칙", tags=["규칙", "실험"], css=("pb-rules",), source="doc")
    # timeline (gantt)
    def g(ms):
        return kst_dt(ms).strftime("%Y-%m-%d %H:%M")
    elapsed_obs = "done" if ref >= obs_end else "active"
    gantt = f"""gantt
  title 30일 고정 실험 (한국 시간)
  dateFormat YYYY-MM-DD HH:mm
  axisFormat %m-%d
  section 실험
  관찰 기간 21일 (복사 제안 없음) :{elapsed_obs}, obs, {g(start)}, {g(obs_end)}
  규칙·코드 고정 30일 :{'done' if ref >= cp1 else 'active'}, frz, {g(start)}, {g(cp1)}
  section 판정
  1차 체크포인트 (30일) :milestone, cp1, {g(cp1)}, 0d
  2차 체크포인트 (60일) :milestone, cp2, {g(cp1 + 30 * DAY_MS)}, 0d"""
    ev_rows = [[g(start), f"실험 시작 ({len(d.accounts) or V4_ACCOUNTS}개 계좌 $5,000)",
                f"코드 버전 {str(info.get('commit') or '-')[:10]}"],
               [g(obs_end), "관찰 기간 끝 (이후 복사 제안 가능)", "시작 + 21일"],
               [g(cp1), "1차 체크포인트 판정", "코드가 스냅샷으로 판정"]]
    if d.restart:
        ev_rows.insert(0, [kst_min(d.restart.get("ts")), "이전 실행 보관 후 처음부터 다시 시작",
                           sanitize(str(d.restart.get("text_ko") or ""), 120)])
    body = [hero("타임라인", f"시작 {kst_stamp(start)} · 지금 {min(day_show, PERIOD_DAYS)}일째 / 30일"
                 + ("" if ctx.run_known else " (계좌 자료가 없어 예정 시각 사용)")),
            f"<progress value=\"{min(day_no, PERIOD_DAYS)}\" max=\"{PERIOD_DAYS}\"></progress> "
            f"`{bar(min(day_no, PERIOD_DAYS) / PERIOD_DAYS)}` {min(day_no, PERIOD_DAYS)}/30일\n",
            mermaid(gantt),
            "## 주요 날짜\n" + table(["한국 시간", "일", "메모"], ev_rows),
            callout("info", "체크포인트 시각", "체크포인트는 시작 뒤 30일째 날의 00:00 UTC(한국 09:00)에 스냅샷을 고정하고 그 스냅샷으로만 판정합니다."),
            "\n" + link("실험 개요") + " · " + link("체크포인트 판정") + " · " + link("홈")]
    v.add(FOLDERS["exp"], "타임라인", "\n".join(body), type="실험", tags=["실험", "규칙"], css=("pb-exp",), source="code",
          props={"date": kst_day(start)})
    # checkpoint
    vv = d.verdict
    rows = []
    cnt = defaultdict(int)
    for r in d.verdict_rows:
        cnt[r["status"]] += 1
        sid, tf = split_account(r["account_id"])
        rows.append([r["account_id"], r["status"], r["stage"] or "-", f"{r['trades'] if r['trades'] is not None else '-'}",
                     usd(r["equity"]), fnum(r["p"], 3), fnum(r["q"], 3)])
    if vv:
        head = [stat_row([(k, str(c)) for k, c in sorted(cnt.items())] or [("판정", "0")]),
                f"판정일 {vv['date']} · 스냅샷 해시 `{str(vv['snapshot_sha256'])[:16]}…` {badge('code')}\n"]
        table_md = table(["계좌", "판정", "단계", "거래", "평가금", "p", "보정 q"], rows[:200], ["l", "l", "l", "r", "r", "r", "r"])
        if len(rows) > 200:
            table_md += f"\n(앞 200개만 표시, 전체 {len(rows)}개)\n"
        if vv["date"] and ctx.run_known and vv["ts"] < ctx.cp1_ms:
            head.append(callout("warning", "공식 30일 판정이 아닙니다", "이 판정일은 첫 체크포인트 이전입니다(연습 또는 미리보기). 실험의 결론으로 읽지 마세요."))
    else:
        head = [callout("note", "아직 판정이 없습니다",
                        f"첫 체크포인트는 {kst_stamp(cp1)}입니다. 그때까지 어느 매매법도 합격·불합격이 아닙니다.")]
        table_md = ""
    body = [hero("체크포인트 판정", "30일마다 코드가 판정: " + METHOD_KO), LEGEND + "\n"] + head + [table_md,
            "## 판정 규칙\n- 거래 30건 미만: 판단 보류\n- 1차: 평가금 > 시작 금액, 동전 봇 비교로 우연 기준 통과(p, 보정 q), 파산 아님\n"
            "- 2차: 1차 통과 계좌만, 그다음 30일의 새 거래로 다시\n- 2차까지 통과해야 '실거래 검토 대상'\n",
            "근거: " + link("규칙 보충안") + " · " + link("타임라인") + " · " + link("홈")]
    v.add(FOLDERS["exp"], "체크포인트 판정", "\n".join(body), type="규칙", tags=["규칙", "실험"], css=("pb-rules",), source="code",
          props={"n_verdicts": len(d.verdict_rows), "date": vv["date"] if vv else None})
    # overview hub
    n_acc = len(d.accounts) or V4_ACCOUNTS
    body = [hero("실험 개요", f"paper v4: 잠긴 36개 매매법·딥시크·릴스 5분 단타를 모의 계좌 {V4_ACCOUNTS}개로 규칙 고정 상태에서 지켜보는 실험"),
            callout("pb-stat", "지금", stat_row([("일차", f"{min(day_show, 30)}/30"), ("계좌", str(n_acc)),
                                               ("관찰 기간 끝", kst_day(obs_end)), ("1차 체크포인트", kst_day(cp1))]).rstrip()),
            "- " + link("실험 규칙 한눈에") + "\n- " + link("타임라인") + "\n- " + link("레버리지 계단") + "\n- " + link("체크포인트 판정") +
            "\n- " + link("규칙 문서 목록") + "\n- " + link("매매법 목록") + "\n- " + link("홈"),
            callout("danger", "실제 돈이 아닙니다", "이 실험은 모의(paper) 계좌입니다. 주문 기능은 없고 거래소 키는 읽기 전용입니다."),
            ]
    v.add(FOLDERS["exp"], "실험 개요", "\n".join(body), type="허브", tags=["허브", "실험"], css=("pb-hub",), source="code")


# ================================================================== 02 매매법: DeepSeek families and the reel (paper v4)
_DEFS_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dash", "static", "v4", "screens",
                        "strategies-defs.js")
_NAMES_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dash", "static", "v4", "core", "names.js")
_JS_STR = re.compile(r'"((?:[^"\\]|\\.)*)"|`((?:[^`\\]|\\.)*)`')


def _js_strings(src: str, p: Optional[str] = None) -> list:
    out = []
    for a, b in _JS_STR.findall(src):
        x = a if a else b
        if p is not None:
            x = x.replace("${p}", p)
        out.append(x.replace('\\"', '"'))
    return out


def plain_rules() -> dict:
    """The owners' plain-Korean rule lines of the 44 DeepSeek definitions and the reel, read from the dashboard's
    own table (dash/static/v4/screens/strategies-defs.js, written from the pre-registrations; the one place they
    live) and its names (core/names.js). {"families": {F1: line}, "defs": {id: [lines]}, "names": {id: name},
    "reel": {"desc": str, "lines": [...]}}; empty parts when the files are missing or changed shape."""
    out: dict = {"families": {}, "defs": {}, "names": {}, "reel": {}}
    src = read_text(_DEFS_JS) or ""
    for fid, desc in re.findall(r'\{id: "(F\d+)", desc: "((?:[^"\\]|\\.)*)"\}', src):
        out["families"][fid] = desc
    fib = re.search(r"const fib = \(p\) => \(\{lines: \[(.*?)\]\}\);", src)
    for line in src.splitlines():
        m = re.match(r'\s*(F\d+_[A-Z0-9_]+): \{fam: "F\d+", lines: \[(.*)\]\},?\s*$', line)
        if m:
            out["defs"][m.group(1)] = _js_strings(m.group(2))
            continue
        m = re.match(r'\s*(F\d+_[A-Z0-9_]+): \{fam: "F\d+", \.\.\.fib\("([^"]+)"\)\},?\s*$', line)
        if m and fib:
            out["defs"][m.group(1)] = _js_strings(fib.group(1), m.group(2))
    rm = re.search(r"export const REEL = \{(.*?)\n\};", src, re.S)
    if rm:
        d = re.search(r'\n\s*desc: "((?:[^"\\]|\\.)*)"', rm.group(1))
        ls = re.search(r"\n\s*lines: \[(.*?)\]", rm.group(1), re.S)
        out["reel"] = {"desc": d.group(1) if d else "", "lines": _js_strings(ls.group(1)) if ls else []}
    names = read_text(_NAMES_JS) or ""
    nm = re.search(r"export const DS_NAME_KO = \{(.*?)\n\};", names, re.S)
    if nm:
        out["names"] = dict(re.findall(r'\n\s*(F\d+_[A-Z0-9_]+): "((?:[^"\\]|\\.)*)"', nm.group(1)))
    return out


def _research_line(sid: str) -> tuple:
    """(rows, conclusion) of a v4 strategy's 5-year card (ds_profiles.card): per timeframe the research exit's
    trades per day and net % per trade in each period; ([], None) without the research files."""
    try:
        from . import ds_profiles as DP
        c = DP.card(sid)
    except Exception:  # noqa: BLE001  (a description only)
        c = None
    if not c:
        return [], None
    rows = [[TF_KO.get(r["tf"], r["tf"]), c.get("exit") or r.get("exit"), fnum(r["trades_per_day"], 1),
             f"{fnum(r['net_pct_is'], 3)}% · {fnum(r['net_pct_cf'], 3)}% · {fnum(r['net_pct_pre'], 3)}%",
             pct(r["win_rate"], 0, False) if r.get("win_rate") is not None else "-"] for r in c["rows"]]
    return rows, (c.get("research") or {}).get("conclusion_ko")


def _group_counts(ctx: Ctx, ids: list) -> tuple:
    """(accounts, trades, busts) of a v4 strategy's accounts (counts only: owners' D10/D11 keep DeepSeek money in
    its own group view on the dashboard)."""
    d = ctx.data
    aids = [a for a, x in d.accounts.items() if x["strategy"] in ids and x["kind"] in ("ds200", "reel")]
    trades = sum((d.trade_stats.get(a) or {}).get("n", 0) for a in aids)
    busts = sum(1 for a in aids if (d.engines.get(a) or {}).get("bust"))
    return aids, trades, busts


def build_v4_groups(v: Vault) -> None:
    """One note per DeepSeek family (its definitions in plain Korean, their 5-year research rows and live counts),
    the reel's note and the hub '딥시크·릴스'. Counts only for the live DeepSeek accounts; nothing here is a verdict."""
    from .config import DS200_DEFS, REEL_NAME
    from .groups import DS_FAMILY_KO, REEL_KO, V4_ROLES, role_of
    ctx = v.ctx
    pr = plain_rules()
    fams: dict = {}
    for did, fam, _tfs in DS200_DEFS:
        fams.setdefault(fam, []).append(did)
    hub_rows = []
    for fam, ids in fams.items():
        roles = []
        for did in ids:
            r = role_of(did)
            if r and f"spec_{r}" not in roles:
                roles.append(f"spec_{r}")
        _a, trades, busts = _group_counts(ctx, ids)
        rows = []
        for did in ids:
            aids, n, b = _group_counts(ctx, [did])
            rule = " · ".join(sanitize(x, 200) for x in pr["defs"].get(did, [])) or "규칙 원문: PREREG_DEEPSEEK200.md 5절"
            rows.append([f"**{did}** {sanitize(pr['names'].get(did, ''), 60)}", rule,
                         ", ".join(TF_KO.get(ctx.data.accounts[a]["timeframe"], ctx.data.accounts[a]["timeframe"])
                                   for a in sorted(aids)) or "-", n, b or "-"])
        res = []
        concl = None
        for did in ids:
            rr, concl = _research_line(did)
            res += [[did] + x for x in rr]
        body = [hero(f"딥시크 {fam} {DS_FAMILY_KO[fam]}", f"딥시크 200 정의 {len(ids)}개 · 담당 "
                     + ", ".join(ROLE_NAME.get(r, r) for r in roles)),
                LEGEND + "\n",
                (sanitize(pr["families"].get(fam, ""), 300) + "\n") if pr["families"].get(fam) else "",
                callout("warning", "판정 전 기록입니다", "딥시크 계좌의 손익은 대시보드 딥시크 묶음에서만 봅니다(두 분 D11). "
                        "여기는 거래 수와 파산 수만 적습니다. 30일 판정 전 숫자는 모두 참고입니다."),
                "## 정의와 규칙 " + badge("doc"),
                table(["정의", "규칙(쉬운 말)", "봉", "거래", "파산"], rows, ["l", "l", "l", "r", "r"]),
                "## 5년 연구 " + badge("code") + "\n거래당 순손익(가격 %, 레버리지 없음, 연구 청산 X5_TRAIL2 = 라이브의 계단 "
                "잠금과 다름) 1기 · 2기 · 3기.\n",
                table(["정의", "봉", "연구 청산", "하루 거래", "순손익 1·2·3기", "승률"], res,
                      ["l", "l", "l", "r", "r", "r"]) if res else "연구 파일이 없습니다.\n",
                (callout("info", "5년 연구 결론", sanitize(concl, 300)) if concl else ""),
                "\n" + " · ".join(link(role_note(r), ROLE_NAME.get(r, r)) for r in roles) + " · " + link("딥시크·릴스")
                + " · " + link("매매법 목록")]
        name = ds_family_note(fam)
        v.add(FOLDERS["strat"], name, "\n".join(x for x in body if x), type="전략", tags=["전략", "딥시크"],
              css=("pb-strategy",), sub="딥시크", source="mixed",
              props={"family": fam, "definitions": len(ids), "trades": trades, "busts": busts})
        hub_rows.append([link(name, f"{fam} {DS_FAMILY_KO[fam]}"), len(ids),
                         ", ".join(link(role_note(r), ROLE_NAME.get(r, r)) for r in roles), trades, busts or "-"])
    # the reel
    aids, n, b = _group_counts(ctx, [REEL_NAME])
    rr, concl = _research_line(REEL_NAME)
    reel = pr.get("reel") or {}
    flips = sorted(a for a, x in ctx.data.accounts.items() if x["kind"] == "random" and x["timeframe"] == "5m")
    fn = sum((ctx.data.trade_stats.get(a) or {}).get("n", 0) for a in flips)
    body = [hero(REEL_KO, f"{REEL_NAME} · 5분봉 계좌 {len(aids) or 1}개 · 담당 {ROLE_NAME.get('spec_reel_5m', '')}"),
            LEGEND + "\n",
            (sanitize(reel.get("desc", ""), 300) + "\n") if reel.get("desc") else "",
            "## 규칙 " + badge("doc") + "\n" + "\n".join(f"- {sanitize(x, 200)}" for x in reel.get("lines", [])),
            "\n## 청산\n" + sanitize(EXITS_KO.get("reel", ""), 400) + "\n",
            "## 비교 기준 " + badge("code") + f"\n같은 5분봉·롱만·같은 청산의 동전 던지기 {len(flips)}개가 기준입니다"
            f"(끝난 거래 {fn}건). 동전 봇 숫자는 개수로만 셉니다.\n",
            "## 지금까지 " + badge("code") + "\n" + stat_row([("끝난 거래", f"{n}건"), ("파산", str(b))]),
            callout("warning", "판정 전 기록입니다", "30일 판정 전 숫자는 모두 참고입니다. 판정은 체크포인트가 동전 봇과 "
                    "비교해 코드로만 합니다(" + METHOD_KO + ")."),
            "## 5년 연구 " + badge("code") + "\n거래당 순손익(가격 %, 레버리지 없음, 연구와 라이브가 같은 청산) 1기 · 2기 · 3기.\n",
            table(["봉", "청산", "하루 거래", "순손익 1·2·3기", "승률"], rr, ["l", "l", "r", "r", "r"]) if rr else
            "연구 파일이 없습니다.\n",
            (callout("info", "5년 연구 결론", sanitize(concl, 300)) if concl else ""),
            "\n" + link(role_note("spec_reel_5m"), ROLE_NAME.get("spec_reel_5m")) + " · " + link("딥시크·릴스") + " · "
            + link("동전 던지기 봇") + " · " + link("매매법 목록")]
    v.add(FOLDERS["strat"], REEL_NOTE, "\n".join(x for x in body if x), type="전략", tags=["전략", "릴스"],
          css=("pb-strategy",), source="mixed", props={"strategy": REEL_NAME, "trades": n, "busts": b})
    # hub
    body = [hero("딥시크·릴스", f"딥시크 200 정의 {len(DS200_DEFS)}개({len(fams)}개 계열)와 릴스 5분 단타. "
                 f"담당 {len(V4_ROLES)}명"),
            LEGEND + "\n",
            callout("warning", "잠긴 36개와 섞지 않습니다", "묶음마다 따로 판정합니다(" + METHOD_KO + "). 딥시크 손익은 대시보드 "
                    "딥시크 묶음에서만 보고 여기는 개수만 적습니다."),
            "## 딥시크 계열\n" + table(["계열", "정의", "담당", "거래", "파산"], hub_rows, ["l", "r", "l", "r", "r"]),
            "## 릴스\n- " + link(REEL_NOTE, REEL_KO),
            "\n" + link("매매법 목록") + " · " + link("직원 목록") + " · " + link("홈")]
    v.add(FOLDERS["strat"], "딥시크·릴스", "\n".join(body), type="허브", tags=["허브", "전략", "딥시크"],
          css=("pb-hub",), source="mixed", props={"families": len(fams), "definitions": len(DS200_DEFS)})
