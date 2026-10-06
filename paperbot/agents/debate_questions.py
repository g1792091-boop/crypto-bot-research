"""The 24-hour debate room's question bank (owner item B, the idea factory): code picks ONE concrete question per
round from the bot's own data. Read-only, no AI, no writes anywhere.

Every question is about the 36 locked strategies, so every round has a 5-year handle: ready-made test specs that pass
the lab's own checks (``handles``: labtests what-ifs on one of the 36, newlab filter twins of a tag, newlab entries not
tested yet). The model still chooses; the handles only show what the grammar can express. 5m is never offered (v4 has
no 5m strategy account).

Kinds (``KINDS``):
  big_losses     the KST day's 5 largest losing trades of the 36 (fewer than 3 today: the last 24 h) as cards, and the
                 day's tag shares over winners and losers, so 반대 can show a filter also deletes winners
  worst_vs_flip  the strategy x timeframe account (30+ trades) furthest below its timeframe's coin-flip wallets
  loss_tag       the skip tag with the largest (loss share - win share) over the last 7 days (30+ tagged trades) and the
                 3 strategies where the gap is largest
  session_cell   the UTC session (newlab's windows) x timeframe where most of the 36 lose (12+ strategies with 5+
                 trades)
  event          a NEW bust or critical alert of one of the 36 (debate_packet.unusual) jumps the queue
  retro          nothing fresh, or the forced round: where the last ideas failed (read-back), and the next one

``pick`` chooses: an event first; then kinds in rotation (never the same kind twice in a row), the strongest evidence
within a kind; each key at most ``MAX_ASKS_A_DAY`` rounds a KST day (``asked``, kept by the caller in debate_state as
'asked:<key>'); a worst_vs_flip account is fresh again after 3 days or 50 more trades; retro only when nothing else is
fresh (or forced). Nothing fresh: None, which the debate records as a free 'no_question' skip.

The near-miss question of the plan's first draft is left out on purpose: changing one element of a near-pass scores 7+
in rooms._similar, so it would always be blocked as a near-duplicate of a failed test.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from . import debate_packet as P

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
KST_MS = 9 * HOUR_MS
KINDS = ("big_losses", "worst_vs_flip", "loss_tag", "session_cell", "event", "retro")
KIND_KO = {"big_losses": "오늘 큰 손실", "worst_vs_flip": "동전보다 못한 계좌", "loss_tag": "손실에 많은 태그",
           "session_cell": "잃는 시간대", "event": "파산·긴급", "retro": "지난 아이디어 돌아보기"}
EVIDENCE_TOKENS = 900              # one question's section (evidence + handles), estimate_tokens
MAX_ASKS_A_DAY = 3                 # rounds one key may take in a KST day
REFRESH_MS = 3 * DAY_MS            # worst_vs_flip: fresh again after this ...
REFRESH_TRADES = 50                # ... or this many more trades of that account
MIN_TRADES_ACCOUNT = 30
MIN_TAGGED = 30
MIN_CELL_STRATEGIES, MIN_CELL_TRADES = 12, 5
MAX_LAB_HANDLES = 8
TFS = ("15m", "30m", "1h", "4h")   # config.V3_TRADE_TFS (no 5m: v4 has no 5m strategy account)
# labtests.SKIP_TAGS and TEMPLATES (frozen; read from labtests when it imports, these only when it cannot)
SKIP_TAGS_FALLBACK = ("추세 반대 진입", "상위 봉 추세 반대", "횡보장 진입", "추세 약함 (ADX 20 미만)", "DI 방향 반대",
                      "많이 오른/내린 뒤 추격", "최근 범위 끝에서 진입")
STOP_KS, FIRST_LOCKS = (1.5, 2.5, 3.0), (0.15, 0.20, 0.30)
# a skip tag's newlab filter twin (the nearest filter in the new-strategy grammar)
TAG_TWINS = {
    "추세 반대 진입": ({"kind": "trend_ema", "length": 200}, {"kind": "trend_ema", "length": 50}),
    "상위 봉 추세 반대": ({"kind": "htf_trend", "length": 20}, {"kind": "htf_trend", "length": 50}),
    "횡보장 진입": ({"kind": "adx", "mode": "above", "level": 20}, {"kind": "adx", "mode": "above", "level": 25}),
    "추세 약함 (ADX 20 미만)": ({"kind": "adx", "mode": "above", "level": 20}, {"kind": "adx", "mode": "above", "level": 25}),
}
SESSIONS_UTC = {"asia": (0, 8), "europe": (8, 16), "us": (16, 24)}           # newlab_signals.SESSIONS
SESSION_KO = {"asia": "아시아 시간(UTC 0~8시)", "europe": "유럽 시간(UTC 8~16시)", "us": "미국 시간(UTC 16~24시)"}
TAGS_NOTE_KO = ("loss_share = 진 거래 중 그 태그가 붙은 비율, win_share = 이긴 거래 중 비율. 둘 다 높으면 그 조건을 "
                "건너뛸 때 이긴 거래도 지워짐")


@dataclass
class Question:
    kind: str
    key: str
    question_ko: str
    claim_ko: str
    evidence: dict
    handles: dict = field(default_factory=dict)
    n_evidence: int = 0

    def section(self) -> dict:
        """What the packet carries for this question (the topic section's place)."""
        return {"kind": self.kind, "kind_ko": KIND_KO.get(self.kind, self.kind), "question_ko": self.question_ko,
                "claim_ko": self.claim_ko, "evidence": self.evidence, "handles": self.handles,
                "n_evidence": self.n_evidence}

    def tokens(self) -> int:
        return P.estimate_tokens(P.compact_json(self.section()))


# ---------------------------------------------------------------- small helpers
def _skip_tags() -> tuple:
    try:
        from . import labtests as LT
        return tuple(LT.SKIP_TAGS)
    except Exception:  # noqa: BLE001  (the lab module is optional on this side)
        return SKIP_TAGS_FALLBACK


def kst_day(ms: int) -> str:
    return P.kst_day(ms)


def kst_day_start(ms: int) -> int:
    d = dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, tz=dt.timezone.utc)
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000) - KST_MS


def _h(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def _r(x: Any, n: int = 4) -> Any:
    try:
        return None if x is None else round(float(x), n)
    except (TypeError, ValueError):
        return None


def skip_handle(strategy: str, tf: str, tag: str) -> dict:
    return {"template": "skip_tag", "strategy": strategy, "timeframe": tf, "tag": tag}


def _what_ifs(strategy: str, tf: str, tags: Iterable[str]) -> list[dict]:
    """stop_atr / lock_start on S@tf and skip_tag for ``tags`` (the 36's fixed what-if templates)."""
    out = [skip_handle(strategy, tf, t) for t in tags]
    out += [{"template": "stop_atr", "strategy": strategy, "timeframe": tf, "k": k} for k in STOP_KS]
    out += [{"template": "lock_start", "strategy": strategy, "timeframe": tf, "first_lock": f} for f in FIRST_LOCKS]
    return out


def _dedupe(xs: list) -> list:
    seen, out = set(), []
    for x in xs:
        k = json.dumps(x, sort_keys=True, ensure_ascii=False)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _twins(tags: Iterable[str]) -> list[dict]:
    return _dedupe([f for t in tags for f in TAG_TWINS.get(t, ())])


def _round_trip(paper: sqlite3.Connection) -> float:
    from .riskreward import round_trip_of
    return round_trip_of(paper)


def _strategy_cards(paper: sqlite3.Connection, since_ms: int, until_ms: int, *, losses_only: bool = False,
                    order: str = "t.id DESC", limit: int = 2000, account: Optional[str] = None) -> list[dict]:
    """Cards (paperbot.cards.card) of the 36's closed trades (accounts.kind 'strategy', 15m-4h) in [since, until)."""
    from .. import cards as C
    rt = _round_trip(paper)
    q = ("SELECT t.account_id, t.data, a.kind FROM trades t JOIN accounts a ON a.account_id = t.account_id "
         f"WHERE a.kind = 'strategy' AND a.timeframe IN ({','.join('?' * len(TFS))}) AND t.exit_time >= ? "
         "AND t.exit_time < ?")
    args: list = [*TFS, int(since_ms), int(until_ms)]
    if losses_only:
        q += " AND t.pnl < 0"
    if account:
        q += " AND t.account_id = ?"
        args.append(account)
    q += f" ORDER BY {order} LIMIT ?"
    args.append(int(limit))
    out = []
    for aid, data, kind in paper.execute(q, args).fetchall():
        try:
            out.append(C.card(aid, json.loads(data), rt, kind=kind))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _brief(c: dict) -> dict:
    tags = [t for t in c.get("tags") or [] if t in _skip_tags()]
    return {"strategy": c.get("strategy"), "tf": c.get("timeframe"), "coin": str(c.get("symbol") or "").replace("USDT", ""),
            "side": c.get("side_ko"), "exit": c.get("reason_ko"), "lev": c.get("leverage"), "roe": _r(c.get("roe"), 3),
            "tags": tags}


def _tag_rows(cards: list[dict]) -> list[dict]:
    from .. import cards as C
    skip = set(_skip_tags())
    out = []
    for r in C.tag_stats(cards):
        if r["tag"] in skip and (r["losses"] or r["wins"]):
            out.append({"tag": r["tag"], "losses": r["losses"], "wins": r["wins"],
                        "loss_share": _r(r["loss_share"], 3), "win_share": _r(r["win_share"], 3)})
    return out


def _trim(q: Question, budget: int = EVIDENCE_TOKENS) -> Question:
    """Cut the evidence (lists, then strings) until the section fits the budget; handles are kept (capped)."""
    q.handles = {k: (v[:MAX_LAB_HANDLES] if isinstance(v, list) else v) for k, v in q.handles.items()}
    for ml, ms in ((8, 160), (6, 120), (4, 100), (3, 80), (2, 60)):
        if q.tokens() <= budget:
            return q
        q.evidence = P.shrink(q.evidence, ml, ms)
    while q.tokens() > budget and q.evidence:
        q.evidence.pop(next(reversed(q.evidence)))           # the least needed piece is the last one
    return q


def _tested_tests(agents: Optional[sqlite3.Connection], strategy: str, k: int = 6) -> list[dict]:
    """The strategy room's stored what-if tests (agents3 read-only): spec and latest status."""
    if agents is None:
        return []
    try:
        rows = agents.execute(
            "SELECT t.id, t.spec, (SELECT status FROM trial_results WHERE id = (SELECT MAX(id) FROM trial_results "
            "WHERE trial_id = t.id)) FROM trials t WHERE t.kind = 'test' AND t.strategy = ? ORDER BY t.id DESC LIMIT ?",
            (strategy, k)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for tid, spec, st in rows:
        try:
            sp = json.loads(spec)
        except (TypeError, ValueError):
            sp = {}
        out.append({"trial": tid, "test": {k2: v for k2, v in (sp or {}).items() if k2 != "strategy"}, "status": st})
    return out


def _prior(strategy: str) -> Optional[dict]:
    from . import packets3
    p = packets3.research_prior(strategy) or {}
    if not p:
        return None
    out = {}
    for k in ("support_resistance", "entry_strength", "parameters", "trendline"):
        v = p.get(k)
        if isinstance(v, dict):
            passed = v.get("passed_all3")
            out[k] = {"tests": v.get("tests"), "passed_all3": len(passed) if isinstance(passed, list) else passed}
    out["conclusion_ko"] = str(p.get("conclusion_ko") or "")[:160]
    return out


# ---------------------------------------------------------------- the kinds
def q_big_losses(paper: sqlite3.Connection, now_ms: int) -> Optional[Question]:
    start = kst_day_start(now_ms)
    worst = _strategy_cards(paper, start, now_ms + 1, losses_only=True, order="t.pnl ASC, t.id ASC", limit=5)
    window, since = "오늘(한국 시간)", start
    if len(worst) < 3:
        since = now_ms - DAY_MS
        worst = _strategy_cards(paper, since, now_ms + 1, losses_only=True, order="t.pnl ASC, t.id ASC", limit=5)
        window = "최근 24시간"
    if len(worst) < 3:
        return None
    day = _strategy_cards(paper, since, now_ms + 1, limit=2000)
    tags = _tag_rows(day)
    counts: dict = {}
    for c in worst:
        for t in set(c.get("tags") or []):
            counts[t] = counts.get(t, 0) + 1
    common = [t for t in _skip_tags() if counts.get(t, 0) >= 2]
    labs = []
    for t in sorted(common, key=lambda t: -counts[t]):
        for c in worst:
            if t in (c.get("tags") or []) and c.get("timeframe") in TFS:
                labs.append(skip_handle(c["strategy"], c["timeframe"], t))
    ids = sorted(int(c.get("exit_time") or 0) for c in worst)
    strategies = list(dict.fromkeys(c["strategy"] for c in worst))
    top = max(common, key=lambda t: counts[t]) if common else None
    claim = (f"오늘 큰 손실 5건 중 {counts[top]}건에 붙은 '{top}' 신호를 건너뛰었다면 손실을 줄이고, 이긴 거래는 그보다 덜 지운다"
             if top else "오늘 큰 손실 5건에는 공통 조건이 있고, 그 조건의 신호를 건너뛰면 덜 잃는다")
    q = Question("big_losses", f"big_losses:{kst_day(now_ms)}:{_h(*[c['account_id'] for c in worst], *ids)}",
                 "오늘 가장 크게 잃은 거래 5개를 막을 수 있었던 조건은? 그 조건은 이긴 거래도 지우는가?", claim,
                 {"window": window, "losses": [_brief(c) for c in worst], "trades_in_window": len(day),
                  "tags_in_window": tags, "tags_note": TAGS_NOTE_KO},
                 {"labtest": _dedupe(labs), "newlab_filters": _twins(common), "strategies": strategies},
                 n_evidence=len(day))
    return _trim(q)


def q_worst_vs_flip(paper: sqlite3.Connection, agents: Optional[sqlite3.Connection], board: dict,
                    now_ms: int) -> list[Question]:
    rows = []
    league = board.get("league") or {}
    for aid, v in (board.get("pass_check") or {}).items():
        strat, _, tf = aid.partition("@")
        flips = list(((league.get(tf) or {}).get("coin_flip_wallets") or {}).values())
        if tf not in TFS or not flips or (v.get("trades") or 0) < MIN_TRADES_ACCOUNT or v.get("wallet") is None:
            continue
        gap = float(v["wallet"]) - sum(flips) / len(flips)
        if gap < 0:
            rows.append((gap, aid, strat, tf, v, sum(flips) / len(flips)))
    rows.sort()
    out = []
    for gap, aid, strat, tf, v, flip in rows[:3]:
        cs = _strategy_cards(paper, 0, now_ms + 1, limit=300, account=aid)
        from .compare import win_loss_compare
        wl = win_loss_compare(cs)
        tags = _tag_rows(cs)
        bad = [r["tag"] for r in tags if (r["loss_share"] or 0) > (r["win_share"] or 0)][:3]
        ev = {"account": aid, "trades": v.get("trades"), "wallet": v.get("wallet"), "coin_flip_mean_wallet": _r(flip, 2),
              "gap_to_coin_flips": _r(gap, 2),
              "win_loss": {k: wl.get(k) for k in ("all", "by_side", "by_session", "by_coin") if k in wl},
              "tags": tags[:5], "tags_note": TAGS_NOTE_KO, "tested_here": _tested_tests(agents, strat),
              "prior_5y": _prior(strat)}
        q = Question("worst_vs_flip", f"worst_vs_flip:{aid}",
                     f"{strat} {tf} 계좌가 같은 봉 동전 봇들보다 잔고가 낮다: 5년 자료로 시험할 고칠 점 하나는?",
                     f"{strat} {tf}는 규칙 하나(손절폭, 첫 익절 잠금, 진입 태그 건너뛰기)를 바꾸면 동전과의 차이를 줄인다",
                     ev, {"labtest": _what_ifs(strat, tf, bad), "newlab_filters": _twins(bad), "strategies": [strat]},
                     n_evidence=int(v.get("trades") or 0))
        out.append(_trim(q))
    return out


def q_loss_tag(paper: sqlite3.Connection, now_ms: int) -> Optional[Question]:
    cs = _strategy_cards(paper, now_ms - 7 * DAY_MS, now_ms + 1, limit=2000)
    rows = [r for r in _tag_rows(cs) if r["losses"] + r["wins"] >= MIN_TAGGED
            and r["loss_share"] is not None and r["win_share"] is not None and r["loss_share"] > r["win_share"]]
    if not rows:
        return None
    best = max(rows, key=lambda r: (r["loss_share"] - r["win_share"], r["losses"]))
    tag = best["tag"]
    per: dict = {}
    for c in cs:
        per.setdefault(c["strategy"], []).append(c)
    gaps = []
    for s, xs in per.items():
        r = next((x for x in _tag_rows(xs) if x["tag"] == tag), None)
        if r is None or r["loss_share"] is None or r["win_share"] is None or r["losses"] < 2:
            continue
        tfs: dict = {}
        for c in xs:
            if tag in (c.get("tags") or []) and c["pnl"] < 0:
                tfs[c["timeframe"]] = tfs.get(c["timeframe"], 0) + 1
        tf = max(tfs, key=lambda k: tfs[k]) if tfs else None
        if tf in TFS:
            gaps.append((r["loss_share"] - r["win_share"], s, tf, r))
    gaps.sort(key=lambda g: (-g[0], g[1]))
    top3 = gaps[:3]
    ls, ws = best["loss_share"] * 100, best["win_share"] * 100
    q = Question("loss_tag", f"loss_tag:{tag}:{kst_day(now_ms)}",
                 f"'{tag}' 태그가 진 거래의 {ls:.0f}%, 이긴 거래의 {ws:.0f}%에 붙었다: 건너뛰면 덜 잃나?",
                 f"'{tag}' 신호를 건너뛰면 지운 손실이 지운 이익보다 커서 덜 잃는다",
                 {"window": "최근 7일, 36개 매매법", "trades": len(cs), "tag": best, "all_tags": _tag_rows(cs)[:7],
                  "strategies_with_largest_gap": [{"strategy": s, "tf": tf, **{k: r[k] for k in ("losses", "wins",
                                                   "loss_share", "win_share")}} for _g, s, tf, r in top3],
                  "tags_note": TAGS_NOTE_KO},
                 {"labtest": [skip_handle(s, tf, tag) for _g, s, tf, _r2 in top3], "newlab_filters": _twins([tag]),
                  "strategies": [s for _g, s, _tf, _r2 in top3]},
                 n_evidence=best["losses"] + best["wins"])
    return _trim(q)


def _session_utc(ms: int) -> str:
    h = dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc).hour
    return next(k for k, (a, b) in SESSIONS_UTC.items() if a <= h < b)


def q_session_cell(paper: sqlite3.Connection, now_ms: int) -> Optional[Question]:
    cs = _strategy_cards(paper, now_ms - 7 * DAY_MS, now_ms + 1, limit=4000)
    cells: dict = {}
    for c in cs:
        key = (_session_utc(c["entry_time"]), c["timeframe"])
        cells.setdefault(key, {}).setdefault(c["strategy"], []).append(c.get("roe") or 0.0)
    best = None
    for (sess, tf), per in cells.items():
        enough = {s: xs for s, xs in per.items() if len(xs) >= MIN_CELL_TRADES}
        if len(enough) < MIN_CELL_STRATEGIES or tf not in TFS:
            continue
        losing = [s for s, xs in enough.items() if sum(xs) / len(xs) < 0]
        score = (len(losing) / len(enough), len(enough))
        if best is None or score > best[0]:
            best = (score, sess, tf, enough, losing)
    if best is None or best[0][0] <= 0.5:
        return None
    (share, m), sess, tf, enough, losing = best
    trades = sum(len(xs) for xs in enough.values())
    others = [w for w in SESSIONS_UTC if w != sess]
    q = Question("session_cell", f"session_cell:{sess}:{tf}:{kst_day(now_ms)}",
                 f"{tf} {SESSION_KO[sess]}: 매매법 {len(losing)}/{m}개가 잃는 자리, 피하는 조건은?",
                 f"{tf}에서 {SESSION_KO[sess]} 진입을 피하고 다른 시간대만 거래하면 덜 잃는다",
                 {"window": "최근 7일, 36개 매매법(진입 시각 UTC)", "cell": {"session": sess, "timeframe": tf,
                  "strategies": m, "losing": len(losing), "trades": trades},
                  "losing_strategies": sorted(losing)[:8],
                  "note": "새 매매법 문법의 시간대 필터는 '그 시간대에만 거래'라서, 피하려면 다른 시간대 필터를 고름"},
                 {"labtest": [], "newlab_filters": [{"kind": "session", "window": w} for w in others],
                  "timeframe": tf, "strategies": sorted(losing)[:8]},
                 n_evidence=trades)
    return _trim(q)


def q_event(paper: sqlite3.Connection, board: dict, now_ms: int, seen: Optional[dict] = None,
            start: Optional[int] = None) -> Optional[Question]:
    """A NEW bust or critical alert of one of the 36 (debate_packet.unusual with the last ok round's marks)."""
    flags = [k for k, _w in P.unusual(board, None, seen, start) if k == "risk"]
    if not flags:
        return None
    pc = board.get("pass_check") or {}                      # the 36's accounts (a coin flip's alert is not a question)
    crit = []
    for a in ((board.get("today") or {}).get("alerts") or []):
        text = str(a.get("text") or "")
        if a.get("level") == "CRITICAL" and text.startswith("[") and "]" in text and text[1:text.find("]")] in pc:
            crit.append(text[1:text.find("]")])
    busts = sorted(a for a, v in pc.items() if v.get("bust"))
    aid = next((a for a in crit + busts if a.partition("@")[2] in TFS), None)
    if aid is None:
        return None
    strat, _, tf = aid.partition("@")
    cs = _strategy_cards(paper, 0, now_ms + 1, losses_only=True, limit=5, account=aid)
    tags = [t for t in _skip_tags() if sum(t in (c.get("tags") or []) for c in cs) >= 2]
    marks = P.agenda_marks(board, start)
    q = Question("event", f"event:{aid}:{marks.get('busts')}:{marks.get('crit_ts')}",
                 f"{strat} {tf}의 파산·긴급 청산을 막을 수 있었던 조건은?",
                 f"{strat} {tf}의 마지막 손실들에는 규칙 하나로 막을 수 있었던 공통점이 있다",
                 {"account": aid, "pass_check": (board.get("pass_check") or {}).get(aid),
                  "last_losses": [_brief(c) for c in cs]},
                 {"labtest": _what_ifs(strat, tf, tags), "newlab_filters": _twins(tags), "strategies": [strat]},
                 n_evidence=len(cs))
    return _trim(q)


def q_retro(agents: Optional[sqlite3.Connection], now_ms: int, readback: Optional[dict] = None) -> Question:
    """Nothing fresh (or the forced round): where the last ideas failed, and which entries were never tested."""
    from . import labintake as LI
    wf = LI.why_fail(agents)
    recent = [{"desc": c["description_ko"][:100], "result": c["result_ko"][:140]}
              for c in LI.view(agents, "debate", 12) if c["status"] in ("tested", "reused", "duplicate")][:5]
    tested_fams: set = set()
    if agents is not None:
        try:
            for (sp,) in agents.execute("SELECT spec FROM trials WHERE kind = 'newlab'"):
                fam = ((json.loads(sp) or {}).get("entry") or {}).get("family")
                if fam:
                    tested_fams.add(fam)
        except (sqlite3.Error, TypeError, ValueError):
            pass
    fams = []
    try:
        from .newlab_signals import FAMILIES
        fams = [f for f in FAMILIES if f not in tested_fams][:6]
    except Exception:  # noqa: BLE001  (the grammar tables are optional on this side)
        fams = []
    ev = {"why_fail": {"tests": wf["tests"], "failed": wf["failed"], "text_ko": wf["text_ko"]}, "recent_results": recent,
          **({"read_back": readback} if readback else {})}
    q = Question("retro", f"retro:{kst_day(now_ms)}:{wf['tests']}:{len(recent)}",
                 "지난 아이디어들은 관문 ①~⑥ 중 어느 칸에서 떨어졌나? 다음에 시험할 하나는?",
                 "지난 실패에서 배운 조건 하나를 더하면, 아직 안 해 본 진입으로 그 칸을 넘을 수 있다", ev,
                 {"labtest": [], "newlab_filters": [], "newlab_entries": fams, "strategies": []},
                 n_evidence=int(wf["tests"]))
    return _trim(q)


# ---------------------------------------------------------------- the bank
def candidates(paper_path: Optional[str], daily_path: Optional[str], agents_path: Optional[str], now_ms: int,
               board: Optional[dict] = None, seen: Optional[dict] = None, start: Optional[int] = None,
               readback: Optional[dict] = None) -> list[Question]:
    """Every question the data supports now (read-only). ``board``: packets3.build's board when the caller already
    has it; ``seen`` / ``start``: the last ok round's agenda marks and the run's start (only a NEW event counts)."""
    from . import packets3
    if board is None:
        board = packets3.build(paper_path, daily_path, now_ms)
    paper, agents = P.open_ro(paper_path), P.open_ro(agents_path)
    out: list[Question] = []
    try:
        if paper is not None:
            for fn in (lambda: q_event(paper, board, now_ms, seen, start), lambda: q_big_losses(paper, now_ms),
                       lambda: q_loss_tag(paper, now_ms), lambda: q_session_cell(paper, now_ms)):
                try:
                    q = fn()
                except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:  # one kind never stops the others
                    q = None
                    _note(f"question kind failed: {type(exc).__name__}: {exc}")
                if q is not None:
                    out.append(q)
            try:
                out += q_worst_vs_flip(paper, agents, board, now_ms)
            except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
                _note(f"worst_vs_flip failed: {type(exc).__name__}: {exc}")
        out.append(q_retro(agents, now_ms, readback))
    finally:
        for c in (paper, agents):
            if c is not None:
                c.close()
    return out


def _note(msg: str) -> None:
    import sys
    print(f"note: {msg}", file=sys.stderr)


def eligible(q: Question, asked: Optional[dict], now_ms: int) -> bool:
    """Fresh enough to ask: never asked; asked today fewer than MAX_ASKS_A_DAY rounds; a worst_vs_flip account asked on
    an earlier day is fresh again after REFRESH_MS or REFRESH_TRADES more trades (other kinds carry their day or
    their evidence in the key, so a new day or new evidence is a new key)."""
    rec = (asked or {}).get(q.key)
    if not isinstance(rec, dict):
        return True
    if rec.get("day") == kst_day(now_ms):
        return int(rec.get("n") or 0) < MAX_ASKS_A_DAY
    if q.kind == "worst_vs_flip":
        return (now_ms - int(rec.get("ts") or 0) >= REFRESH_MS
                or q.n_evidence - int(rec.get("n_evidence") or 0) >= REFRESH_TRADES)
    return True


def pick(cands: list[Question], asked: Optional[dict], last_kind: Optional[str], now_ms: int,
         force: bool = False) -> Optional[Question]:
    """One question: an event first; then the next kind in rotation after ``last_kind`` that has a fresh candidate
    (never the same kind twice in a row), the strongest evidence within it; retro only when nothing else is fresh or
    ``force`` (the 6-hour forced round). None: nothing fresh (a free 'no_question' skip)."""
    fresh = [q for q in cands if eligible(q, asked, now_ms) and q.kind != last_kind]
    ev = [q for q in fresh if q.kind == "event"]
    if ev:
        return max(ev, key=lambda q: (q.n_evidence, q.key))
    retro = [q for q in fresh if q.kind == "retro"]
    if force and retro:
        return retro[0]
    order = [k for k in KINDS if k not in ("event", "retro")]
    if last_kind in order:
        i = order.index(last_kind)
        order = order[i + 1:] + order[:i + 1]
    for k in order:
        xs = [q for q in fresh if q.kind == k]
        if xs:
            return max(xs, key=lambda q: (q.n_evidence, q.key))
    return retro[0] if retro else None


def asked_record(prev: Optional[dict], q: Question, now_ms: int) -> dict:
    """The value the caller stores under 'asked:<key>' after asking ``q``."""
    day = kst_day(now_ms)
    n = int((prev or {}).get("n") or 0) + 1 if (prev or {}).get("day") == day else 1
    return {"day": day, "n": n, "ts": int(now_ms), "n_evidence": int(q.n_evidence), "kind": q.kind}
