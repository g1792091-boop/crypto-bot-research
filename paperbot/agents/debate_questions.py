"""The 24-hour debate room's question bank (owner item B, the idea factory): code picks ONE concrete question per
round from the bot's own data. Read-only, no AI, no writes anywhere.

Every question is about the 36 locked strategies, so every round has a 5-year handle: ready-made test specs that pass
the lab's own checks (``handles``: labtests what-ifs on one of the 36, newlab filter twins of a tag, newlab entries not
tested yet). The model still chooses; the handles only show what the grammar can express. 5m is never offered (v4 has
no 5m strategy account).

Kinds (``KINDS``; owners 10/06: the bank covers ALL 36 strategies, not only the biggest losses):
  big_losses     the KST day's 5 largest losing trades of the 36 (fewer than 3 today: the last 24 h) as cards, and the
                 day's tag shares over winners and losers, so 반대 can show a filter also deletes winners
  loss_traits    ALL of today's losing trades of the 36 (not only the 5 biggest): which traits known at entry (entry
                 tags, side, coin, timeframe, session, trend state, leverage) sit on losers more often than on winners
  worst_vs_flip  the strategy x timeframe account (30+ trades) furthest below its timeframe's coin-flip wallets
  best_luck      the account furthest ABOVE its coin flips: skill or luck? (its own t-test, and the same p times the
                 number of accounts compared: the best of many looks good by luck alone)
  tf_split       the strategy whose timeframes differ most (one makes money, another loses; 20+ trades each)
  loss_tag       the skip tag with the largest (loss share - win share) over the last 7 days (30+ tagged trades) and the
                 3 strategies where the gap is largest
  session_cell   the UTC session (newlab's windows) x timeframe where most of the 36 lose (12+ strategies with 5+
                 trades)
  coin_cell      the same for a coin x timeframe
  regime_cell    the same for the trend state at entry (상승 추세 / 하락 추세 / 박스권 / 횡보, the signal's chart context)
                 x timeframe
  pairs          two strategies whose losing trades come together (same coin, entries in the same hour), last 7 days
  volume_profile the 매물대 (volume profile): an account that keeps losing with a 매물대 level right ahead of its entry
                 (the recorded entry marks of each trade: level kinds 51 / 52 / 53 = 매물 최다 가격 / 매물대 위 끝 /
                 매물대 아래 끝, distance in ATR; read from the stored marks, the frozen sr module is never run here)
  ds_counts      a DeepSeek family whose win rate is lowest against the same timeframes' coin flips: counts and ratios
                 only (dsmoney.DS_MONEY_STRICT: no money numbers)
  near_miss      lab tests that failed only one or two of the six checks (with the rule that a one-element change of a
                 failed test is refused as a near-duplicate, so the idea must differ)
  coverage       the weekly rotation: the strategy debated least recently (every one of the 36 at least once a week)
  event          a NEW bust or critical alert of one of the 36 (debate_packet.unusual) jumps the queue
  retro          nothing fresh, or the forced round: where the last ideas failed (read-back), and the next one

``pick`` chooses: an event first; then a coverage question that is overdue (``COVER_URGENT_MS`` since that strategy was
last debated); then kinds in rotation (never the same kind twice in a row), the strongest evidence within a kind; each
key at most ``MAX_ASKS_A_DAY`` rounds a KST day (``asked``, kept by the caller in debate_state as 'asked:<key>'); a
worst_vs_flip / best_luck account is fresh again after 3 days or 50 more trades; retro only when nothing else is fresh
(or forced). Nothing fresh: None, which the debate records as a free 'no_question' skip. ``deep_pick`` chooses the
daily deep debate's question: the most important one by ``DEEP_ORDER``.

Coverage: the caller keeps {strategy: last ts debated} (``covered_update``: a question focused on one or two
strategies, ``FOCUS_KINDS``, counts for them); ``q_coverage`` asks about the one debated least recently.

The near-miss question was left out of the plan's first draft because a one-element change of a near-pass scores 7+ in
rooms._similar and is refused as a near-duplicate of a failed test. The owners asked for it (10/06): its evidence says
so, so the idea it leads to must move the weak check with a different entry family or a 36-what-if.
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
KINDS = ("big_losses", "loss_traits", "worst_vs_flip", "best_luck", "tf_split", "loss_tag", "session_cell", "coin_cell",
         "regime_cell", "pairs", "volume_profile", "ds_counts", "near_miss", "coverage", "event", "retro")
KIND_KO = {"big_losses": "오늘 큰 손실", "loss_traits": "오늘 손실 전체의 공통점", "worst_vs_flip": "동전보다 못한 계좌",
           "best_luck": "가장 좋은 계좌: 실력인가 운인가", "tf_split": "봉에 따라 갈리는 매매법",
           "loss_tag": "손실에 많은 태그", "session_cell": "잃는 시간대", "coin_cell": "잃는 코인",
           "regime_cell": "잃는 장세", "pairs": "함께 지는 매매법 둘", "volume_profile": "매물대 앞 진입",
           "ds_counts": "딥시크 정의(개수로만)", "near_miss": "아깝게 떨어진 연구실 시험",
           "coverage": "이번 주 차례(36개 돌아가며)", "event": "파산·긴급", "retro": "지난 아이디어 돌아보기"}
# the daily deep debate's question: the most important kind with a candidate first
DEEP_ORDER = ("event", "big_losses", "loss_traits", "worst_vs_flip", "volume_profile", "pairs", "loss_tag", "tf_split",
              "regime_cell", "session_cell", "coin_cell", "best_luck", "near_miss", "ds_counts", "coverage", "retro")
# kinds about one or two named strategies: asking one counts as that strategy's turn in the weekly coverage
FOCUS_KINDS = ("worst_vs_flip", "best_luck", "tf_split", "event", "coverage", "volume_profile", "pairs")
REFRESH_KINDS = ("worst_vs_flip", "best_luck")    # fresh again after REFRESH_MS or REFRESH_TRADES more trades
EVIDENCE_TOKENS = 900              # one question's section (evidence + handles), estimate_tokens
MAX_ASKS_A_DAY = 3                 # rounds one key may take in a KST day
REFRESH_MS = 3 * DAY_MS            # worst_vs_flip: fresh again after this ...
REFRESH_TRADES = 50                # ... or this many more trades of that account
MIN_TRADES_ACCOUNT = 30
MIN_TAGGED = 30
MIN_CELL_STRATEGIES, MIN_CELL_TRADES = 12, 5
MAX_LAB_HANDLES = 8
COVER_URGENT_MS = 5 * DAY_MS       # a strategy not debated for this long jumps the rotation (all 36 within a week)
MIN_TRAIT_LOSSES = 8               # loss_traits: losing trades needed (fewer today: the last 24 h)
MIN_TF_TRADES = 20                 # tf_split: trades each of the two timeframes needs
MIN_PAIR = 5                       # pairs: losing trades together needed
MIN_VP_LOSSES = 4                  # volume_profile: losses with a 매물대 right ahead needed
VP_KINDS = {51: "매물 최다 가격", 52: "매물대 위 끝", 53: "매물대 아래 끝"}   # entry_marks.KIND_KO (sr.py level kinds)
VP_NEAR_ATR = 1.0                  # 'right ahead': the nearest level in the trade's direction within this many ATR
MIN_DS_TRADES = 30
REGIME_KO = {"trend_up": "상승 추세", "trend_down": "하락 추세", "box": "박스권", "chop": "방향 없는 횡보"}
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
    urgent: bool = False            # coverage: overdue (the strategy was not debated for COVER_URGENT_MS)

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


def _week(paper: sqlite3.Connection, now_ms: int) -> list[dict]:
    """The 36's closed trades of the last 7 days as cards (the cell, pair and 매물대 kinds share them)."""
    return _strategy_cards(paper, now_ms - 7 * DAY_MS, now_ms + 1, limit=4000)


def _cells(cs: list[dict], key_fn) -> dict:
    """{(axis value, timeframe): {strategy: [roe, ...]}} of the cards; ``key_fn`` returns None to leave a card out."""
    cells: dict = {}
    for c in cs:
        k = key_fn(c)
        if k is None:
            continue
        cells.setdefault((k, c["timeframe"]), {}).setdefault(c["strategy"], []).append(c.get("roe") or 0.0)
    return cells


def _worst_cell(cells: dict) -> Optional[tuple]:
    """The cell where the largest share of the 36 lose (MIN_CELL_STRATEGIES+ strategies with MIN_CELL_TRADES+ trades,
    more than half of them losing on average): ((share, strategies), axis value, tf, {strategy: roes}, [losing]) or
    None."""
    best = None
    for (ax, tf), per in cells.items():
        enough = {s: xs for s, xs in per.items() if len(xs) >= MIN_CELL_TRADES}
        if len(enough) < MIN_CELL_STRATEGIES or tf not in TFS:
            continue
        losing = [s for s, xs in enough.items() if sum(xs) / len(xs) < 0]
        score = (len(losing) / len(enough), len(enough))
        if best is None or score > best[0]:
            best = (score, ax, tf, enough, losing)
    if best is None or best[0][0] <= 0.5:
        return None
    return best


def _worst_first(losing: list, enough: dict) -> list:
    return sorted(losing, key=lambda s: (sum(enough[s]) / len(enough[s]), s))


def q_session_cell(paper: sqlite3.Connection, now_ms: int, cs: Optional[list] = None) -> Optional[Question]:
    cs = _week(paper, now_ms) if cs is None else cs
    best = _worst_cell(_cells(cs, lambda c: _session_utc(c["entry_time"])))
    if best is None:
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


def _cell_tags(cell_cards: list[dict], preferred: tuple = ()) -> list[str]:
    """Skip tags found more on the cell's losing trades than on its winners (the most first); ``preferred`` when none."""
    bad = [r["tag"] for r in _tag_rows(cell_cards) if (r["loss_share"] or 0) > (r["win_share"] or 0)]
    return (bad or [t for t in preferred if t in _skip_tags()])[:2]


def _coin(c: dict) -> Optional[str]:
    return str(c.get("symbol") or "").replace("USDT", "") or None


def q_coin_cell(paper: sqlite3.Connection, now_ms: int, cs: Optional[list] = None) -> Optional[Question]:
    """The coin x timeframe where most of the 36 lose (last 7 days). The tests always run on all six coins, so the
    handles are the skip tags most common on that cell's losing trades."""
    cs = _week(paper, now_ms) if cs is None else cs
    best = _worst_cell(_cells(cs, _coin))
    if best is None:
        return None
    (share, m), coin, tf, enough, losing = best
    cell = [c for c in cs if c["timeframe"] == tf and _coin(c) == coin]
    bad = _cell_tags(cell)
    worst = _worst_first(losing, enough)[:3]
    trades = sum(len(xs) for xs in enough.values())
    q = Question("coin_cell", f"coin_cell:{coin}:{tf}:{kst_day(now_ms)}",
                 f"{tf} {coin}: 매매법 {len(losing)}/{m}개가 잃는 자리, 피하는 조건은?",
                 f"{tf} {coin} 거래의 손실에 많이 붙은 진입 상황을 건너뛰면 덜 잃는다",
                 {"window": "최근 7일, 36개 매매법", "cell": {"coin": coin, "timeframe": tf, "strategies": m,
                  "losing": len(losing), "trades": trades}, "losing_strategies_worst_first": worst + sorted(
                      set(losing) - set(worst))[:5], "tags_in_cell": _tag_rows(cell)[:5], "tags_note": TAGS_NOTE_KO,
                  "note": "시험은 언제나 6개 코인이 함께라서 '이 코인만 빼기'는 5년 시험 문법에 없음: 그 코인 손실에 많은 "
                          "진입 상황 태그로 가림"},
                 {"labtest": [skip_handle(s, tf, t) for s in worst for t in bad], "newlab_filters": _twins(bad),
                  "timeframe": tf, "strategies": worst},
                 n_evidence=trades)
    return _trim(q)


def q_regime_cell(paper: sqlite3.Connection, now_ms: int, cs: Optional[list] = None) -> Optional[Question]:
    """The trend state at entry (the signal's recorded chart context) x timeframe where most of the 36 lose."""
    cs = _week(paper, now_ms) if cs is None else cs

    def regime(c):
        r = (c.get("ctx") or {}).get("regime")
        return r if r in REGIME_KO else None
    best = _worst_cell(_cells(cs, regime))
    if best is None:
        return None
    (share, m), reg, tf, enough, losing = best
    cell = [c for c in cs if c["timeframe"] == tf and regime(c) == reg]
    prefer = ("횡보장 진입", "추세 약함 (ADX 20 미만)") if reg in ("box", "chop") else ("추세 반대 진입", "상위 봉 추세 반대")
    bad = _cell_tags(cell, prefer)
    worst = _worst_first(losing, enough)[:3]
    trades = sum(len(xs) for xs in enough.values())
    q = Question("regime_cell", f"regime_cell:{reg}:{tf}:{kst_day(now_ms)}",
                 f"{tf} {REGIME_KO[reg]} 장세에서 매매법 {len(losing)}/{m}개가 잃는다: 피하는 조건은?",
                 f"{tf}에서 {REGIME_KO[reg]} 장세의 진입 상황 하나를 건너뛰면 덜 잃는다",
                 {"window": "최근 7일, 36개 매매법(장세 = 신호 봉의 차트 상황)", "cell": {"regime": REGIME_KO[reg],
                  "timeframe": tf, "strategies": m, "losing": len(losing), "trades": trades},
                  "losing_strategies_worst_first": worst + sorted(set(losing) - set(worst))[:5],
                  "tags_in_cell": _tag_rows(cell)[:5], "tags_note": TAGS_NOTE_KO},
                 {"labtest": [skip_handle(s, tf, t) for s in worst for t in bad], "newlab_filters": _twins(bad),
                  "timeframe": tf, "strategies": worst},
                 n_evidence=trades)
    return _trim(q)


# ---------------------------------------------------------------- owners 10/06: every strategy, more kinds
# tags that describe how the trade ended, not the entry: never a 'trait' to avoid (losers carry them by definition)
OUTCOME_TAGS = ("강제청산", "수익 났다가 손절", "진입 직후 바로 손절")


def _trait_values(c: dict) -> list[tuple]:
    """(kind, value) traits of one card known AT ENTRY: its entry tags, side, coin, timeframe, UTC session, trend state
    and leverage (never the exit or an outcome tag: losers carry those by definition)."""
    out = [("태그", t) for t in c.get("tags") or [] if t not in OUTCOME_TAGS]
    out += [("방향", c.get("side_ko")), ("코인", _coin(c)), ("봉", c.get("timeframe")),
            ("시간대", SESSION_KO[_session_utc(c["entry_time"])]), ("레버리지", f"{c.get('leverage')}배")]
    reg = (c.get("ctx") or {}).get("regime")
    if reg in REGIME_KO:
        out.append(("장세", REGIME_KO[reg]))
    return [(k, v) for k, v in out if v]


def q_loss_traits(paper: sqlite3.Connection, now_ms: int) -> Optional[Question]:
    """ALL of today's losing trades of the 36 (not only the biggest five): the traits that sit on losers much more
    often than on winners (loss share - win share)."""
    start = kst_day_start(now_ms)
    cs, window = _strategy_cards(paper, start, now_ms + 1, limit=4000), "오늘(한국 시간)"
    if sum(1 for c in cs if c["pnl"] < 0) < MIN_TRAIT_LOSSES:
        cs, window = _strategy_cards(paper, now_ms - DAY_MS, now_ms + 1, limit=4000), "최근 24시간"
    losses = [c for c in cs if c["pnl"] < 0]
    wins = [c for c in cs if c["pnl"] > 0]
    if len(losses) < MIN_TRAIT_LOSSES:
        return None
    cnt: dict = {}
    for side, xs in (("l", losses), ("w", wins)):
        for c in xs:
            for kv in set(_trait_values(c)):
                cnt.setdefault(kv, {"l": 0, "w": 0})[side] += 1
    rows = []
    for (k, v), n in cnt.items():
        if n["l"] < 3:
            continue
        ls, ws = n["l"] / len(losses), (n["w"] / len(wins) if wins else None)
        rows.append({"kind": k, "trait": v, "losses": n["l"], "wins": n["w"], "loss_share": _r(ls, 3),
                     "win_share": _r(ws, 3), "gap": _r(ls - (ws or 0.0), 3)})
    rows.sort(key=lambda r: (-r["gap"], -r["losses"], r["kind"], r["trait"]))
    rows = rows[:8]
    if not rows:
        return None
    top = rows[0]
    tags = [r["trait"] for r in rows if r["kind"] == "태그" and r["trait"] in _skip_tags()][:2]
    labs = []
    for t in tags:                       # the accounts with the most losing trades carrying the tag
        per: dict = {}
        for c in losses:
            if t in (c.get("tags") or []):
                per[(c["strategy"], c["timeframe"])] = per.get((c["strategy"], c["timeframe"]), 0) + 1
        labs += [skip_handle(s, tf, t) for (s, tf), _n in sorted(per.items(), key=lambda x: (-x[1], x[0]))[:3]]
    filt = _twins(tags)
    sess = next((r["trait"] for r in rows if r["kind"] == "시간대"), None)
    if sess is not None:
        filt += [{"kind": "session", "window": w} for w, ko in SESSION_KO.items() if ko != sess]
    ws = "" if top["win_share"] is None else f", 이긴 거래의 {top['win_share'] * 100:.0f}%"
    q = Question("loss_traits", f"loss_traits:{kst_day(now_ms)}:{len(losses) // 10}",
                 f"오늘 진 거래 {len(losses)}건 전부의 공통점은? 이긴 거래에는 덜 붙는 조건은?",
                 f"진 거래의 {top['loss_share'] * 100:.0f}%{ws}에 붙은 '{top['kind']}: {top['trait']}'를 피하면 "
                 "지운 손실이 지운 이익보다 크다",
                 {"window": window, "losses": len(losses), "wins": len(wins), "traits": rows,
                  "note": "traits = 진입 때 알 수 있는 특징(진입 상황 태그, 방향, 코인, 봉, 시간대 UTC, 장세, 레버리지) 중 "
                          "진 거래에 더 자주 붙은 것. gap = 손실 비율 - 이익 비율"},
                 {"labtest": _dedupe(labs), "newlab_filters": _dedupe(filt),
                  "strategies": list(dict.fromkeys(h["strategy"] for h in labs))},
                 n_evidence=len(cs))
    return _trim(q)


def _roe_test(roes: list) -> dict:
    """mean ROE, t and the one-sided p (normal approximation) of 'mean > 0' over one account's trades."""
    import math
    import statistics
    n = len(roes)
    if n < 2:
        return {"trades": n, "mean_roe": _r(roes[0] if roes else None), "t": None, "p_one_sided": None}
    m, sd = statistics.fmean(roes), statistics.stdev(roes)
    t = m / (sd / math.sqrt(n)) if sd > 0 else None
    p = None if t is None else 0.5 * math.erfc(t / math.sqrt(2))
    return {"trades": n, "mean_roe": _r(m), "t": _r(t, 2), "p_one_sided": _r(p, 4)}


def q_best_luck(paper: sqlite3.Connection, agents: Optional[sqlite3.Connection], board: dict,
                now_ms: int) -> Optional[Question]:
    """The account furthest ABOVE its timeframe's coin flips (30+ trades): skill or luck? Its own t-test next to the
    same p times the number of accounts compared (the best of many looks good by luck alone)."""
    league = board.get("league") or {}
    pc = board.get("pass_check") or {}
    n_acc = sum(1 for a in pc if a.partition("@")[2] in TFS)
    rows = []
    for aid, v in pc.items():
        strat, _, tf = aid.partition("@")
        flips = list(((league.get(tf) or {}).get("coin_flip_wallets") or {}).values())
        if tf not in TFS or not flips or (v.get("trades") or 0) < MIN_TRADES_ACCOUNT or v.get("wallet") is None:
            continue
        gap = float(v["wallet"]) - sum(flips) / len(flips)
        if gap > 0:
            rows.append((gap, aid, strat, tf, v, flips))
    if not rows:
        return None
    gap, aid, strat, tf, v, flips = max(rows, key=lambda r: (r[0], r[1]))
    cs = _strategy_cards(paper, 0, now_ms + 1, limit=300, account=aid)
    test = _roe_test([float(c["roe"]) for c in cs if c.get("roe") is not None])
    p = test["p_one_sided"]
    from .compare import win_loss_compare
    wl = win_loss_compare(cs)
    tags = _tag_rows(cs)
    bad = [r["tag"] for r in tags if (r["loss_share"] or 0) > (r["win_share"] or 0)][:2]
    ev = {"account": aid, "wallet": v.get("wallet"), "coin_flip_mean_wallet": _r(sum(flips) / len(flips), 2),
          "gap_to_coin_flips": _r(gap, 2), "coin_flips_at_or_above": sum(1 for w in flips if w >= float(v["wallet"])),
          "luck_test": {**test, "accounts_compared": n_acc,
                        "p_times_accounts": None if p is None else _r(min(1.0, p * n_acc), 4)},
          "luck_note": f"계좌 {n_acc}개 중 가장 좋은 하나는 운만으로도 좋아 보임: p x 계좌 수가 0.05보다 크면 운으로 "
                       "설명됨(30일 판정 전에는 결론 아님)",
          "win_loss": {k: wl.get(k) for k in ("all", "by_side", "by_coin") if k in wl}, "tags": tags[:4],
          "tested_here": _tested_tests(agents, strat), "prior_5y": _prior(strat)}
    q = Question("best_luck", f"best_luck:{aid}",
                 f"{strat} {tf} 계좌가 같은 봉 동전 봇보다 잔고가 높다: 실력인가 운인가? 5년 자료로 가릴 시험 하나는?",
                 f"{strat} {tf}의 앞섬은 운이 아니라 규칙의 힘이다: 5년 자료(prior_5y)와 같은 방향이고, 손실 쪽 조건 하나를 "
                 "고치면 5년 자료에서도 더 나아진다",
                 ev, {"labtest": _what_ifs(strat, tf, bad), "newlab_filters": _twins(bad), "strategies": [strat]},
                 n_evidence=int(v.get("trades") or 0))
    return _trim(q)


def q_tf_split(paper: sqlite3.Connection, agents: Optional[sqlite3.Connection], board: dict,
               now_ms: int) -> Optional[Question]:
    """The strategy whose timeframes differ most: one timeframe makes money, another loses (MIN_TF_TRADES+ each)."""
    pc = board.get("pass_check") or {}
    names = {a.partition("@")[0] for a in pc}
    league = board.get("league") or {}
    best = None
    for strat, tfs in (board.get("by_strategy") or {}).items():
        if strat not in names:
            continue
        cells = {tf: c for tf, c in (tfs or {}).items() if tf in TFS and (c.get("trades") or 0) >= MIN_TF_TRADES
                 and c.get("mean_roe") is not None}
        if len(cells) < 2:
            continue
        hi = max(cells, key=lambda t: (cells[t]["mean_roe"], t))
        lo = min(cells, key=lambda t: (cells[t]["mean_roe"], t))
        if cells[hi]["mean_roe"] <= 0 or cells[lo]["mean_roe"] >= 0:
            continue
        spread = cells[hi]["mean_roe"] - cells[lo]["mean_roe"]
        if best is None or (spread, strat) > (best[0], best[1]):
            best = (spread, strat, hi, lo, tfs)
    if best is None:
        return None
    spread, strat, hi, lo, tfs = best
    cs = _strategy_cards(paper, 0, now_ms + 1, limit=300, account=f"{strat}@{lo}")
    tags = _tag_rows(cs)
    bad = [r["tag"] for r in tags if (r["loss_share"] or 0) > (r["win_share"] or 0)][:2]
    flips = {tf: _r(sum(w) / len(w), 2) for tf in TFS
             if (w := list(((league.get(tf) or {}).get("coin_flip_wallets") or {}).values()))}
    by_tf = {tf: {k: c.get(k) for k in ("trades", "mean_roe", "win_rate", "wallet")} for tf, c in sorted(tfs.items())
             if tf in TFS}
    q = Question("tf_split", f"tf_split:{strat}:{kst_day(now_ms)}",
                 f"{strat}: {hi}에선 거래당 ROE {tfs[hi]['mean_roe'] * 100:+.1f}%, {lo}에선 {tfs[lo]['mean_roe'] * 100:+.1f}%"
                 " — 봉에 따른 차이는 진짜인가, 우연인가?",
                 f"{strat}는 {lo}에서 지는 이유가 따로 있다: 그 봉의 규칙 하나를 바꾸면 5년 자료에서도 덜 잃는다",
                 {"strategy": strat, "by_timeframe": by_tf, "good_tf": hi, "bad_tf": lo,
                  "coin_flip_mean_wallet_by_tf": flips, "tags_bad_tf": tags[:4], "tags_note": TAGS_NOTE_KO,
                  "note": "봉 4개를 견주면 하나쯤은 우연히 달라 보임(여러 번 비교). mean_roe는 비율(0.01 = +1%)",
                  "tested_here": _tested_tests(agents, strat, 4), "prior_5y": _prior(strat)},
                 {"labtest": _what_ifs(strat, lo, bad), "newlab_filters": _twins(bad), "timeframe": lo,
                  "strategies": [strat]},
                 n_evidence=sum(int((tfs.get(t) or {}).get("trades") or 0) for t in (hi, lo)))
    return _trim(q)


def q_pairs(paper: sqlite3.Connection, now_ms: int, cs: Optional[list] = None) -> Optional[Question]:
    """Two strategies (different names) whose losing trades come together: the same coin, entries in the same UTC hour,
    both lost (last 7 days). The skip tags common to their shared losses are the handles."""
    cs = _week(paper, now_ms) if cs is None else cs
    buckets: dict = {}
    losses: dict = {}
    for c in cs:
        if c["pnl"] >= 0:
            continue
        a = c["account_id"]
        losses[a] = losses.get(a, 0) + 1
        buckets.setdefault((c["symbol"], int(c["entry_time"]) // HOUR_MS), {}).setdefault(a, c)
    pairs: dict = {}
    for accts in buckets.values():
        ids = sorted(accts)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if a.partition("@")[0] != b.partition("@")[0]:
                    pairs.setdefault((a, b), []).append((accts[a], accts[b]))
    good = [(len(v), k) for k, v in pairs.items() if len(v) >= MIN_PAIR]
    if not good:
        return None
    co, (a, b) = max(good, key=lambda x: (x[0], x[0] / min(losses[x[1][0]], losses[x[1][1]]), x[1]))
    shared = pairs[(a, b)]
    tag_n: dict = {}
    for ca, cb in shared:
        for t in set(ca.get("tags") or []) & set(cb.get("tags") or []):
            tag_n[t] = tag_n.get(t, 0) + 1
    common = [t for t in _skip_tags() if tag_n.get(t, 0) * 2 >= co][:2]
    coins: dict = {}
    for ca, _cb in shared:
        coins[_coin(ca)] = coins.get(_coin(ca), 0) + 1
    (sa, _, ta), (sb, _, tb) = a.partition("@"), b.partition("@")
    labs = [skip_handle(sa, ta, t) for t in common] + [skip_handle(sb, tb, t) for t in common]
    q = Question("pairs", f"pairs:{a}|{b}:{kst_day(now_ms)}",
                 f"{a}와 {b}가 같은 코인·같은 시간에 함께 진 거래 {co}건: 같은 신호를 두 번 세는 것인가, 둘 다 피할 조건은?",
                 f"{a}와 {b}가 함께 지는 거래에는 공통 진입 상황이 있어, 그 신호를 건너뛰면 둘 다 덜 잃는다",
                 {"window": "최근 7일, 36개 매매법(같은 코인, 진입이 같은 1시간 안, 둘 다 손실)", "pair": [a, b],
                  "losses_together": co, "losses": {a: losses[a], b: losses[b]},
                  "share_of_smaller": _r(co / min(losses[a], losses[b]), 3), "coins": coins,
                  "common_tags": {t: n for t, n in sorted(tag_n.items(), key=lambda x: -x[1])[:5]},
                  "note": "함께 진 거래가 많으면 두 계좌가 같은 움직임에 함께 걸림(손실이 겹쳐 커짐). 같은 봉 동전 봇끼리도 "
                          "우연히 겹칠 수 있음"},
                 {"labtest": _dedupe(labs), "newlab_filters": _twins(common), "strategies": list(dict.fromkeys([sa, sb]))},
                 n_evidence=co)
    return _trim(q)


def _vp_ahead(c: dict) -> Optional[tuple]:
    """(level kind, distance in ATR) when the nearest price level in the trade's direction (the recorded entry marks'
    ``room``: above a long, below a short) is a 매물대 level within VP_NEAR_ATR; else None. Reads what was stored with the
    signal (cards.card ``sr``); the frozen sr module is never run here."""
    sr = c.get("sr")
    if not isinstance(sr, dict):
        return None
    k, d = sr.get("room_kind"), sr.get("room")
    if k in VP_KINDS and isinstance(d, (int, float)) and not isinstance(d, bool) and 0 <= d <= VP_NEAR_ATR:
        return int(k), float(d)
    return None


def q_volume_profile(paper: sqlite3.Connection, agents: Optional[sqlite3.Connection], now_ms: int,
                     cs: Optional[list] = None) -> Optional[Question]:
    """매물대 (volume profile): the account (last 7 days) with the most losing trades entered with a 매물대 level right
    ahead (within VP_NEAR_ATR ATR in the trade's direction), when such entries lose more often than its others."""
    cs = _week(paper, now_ms) if cs is None else cs
    per: dict = {}
    allv = {"vp": [0, 0], "other": [0, 0]}                      # [trades, losses] over the 36
    for c in cs:
        if not isinstance(c.get("sr"), dict):
            continue
        vp = _vp_ahead(c)
        d = per.setdefault(c["account_id"], {"vp": [], "other": []})
        d["vp" if vp else "other"].append((c, vp))
        b = allv["vp" if vp else "other"]
        b[0] += 1
        b[1] += int(c["pnl"] < 0)
    best = None
    for aid, d in per.items():
        vl = sum(1 for c, _ in d["vp"] if c["pnl"] < 0)
        if vl < MIN_VP_LOSSES or not d["other"]:
            continue
        vr = vl / len(d["vp"])
        orate = sum(1 for c, _ in d["other"] if c["pnl"] < 0) / len(d["other"])
        if vr <= orate:
            continue
        if best is None or (vl, vr - orate, aid) > (best[0], best[1], best[2]):
            best = (vl, vr - orate, aid)
    if best is None:
        return None
    vl, _gap, aid = best
    d = per[aid]
    strat, _, tf = aid.partition("@")
    by_level: dict = {}
    for c, vp in d["vp"]:
        if c["pnl"] < 0:
            by_level[VP_KINDS[vp[0]]] = by_level.get(VP_KINDS[vp[0]], 0) + 1
    dist = sorted(vp[1] for _c, vp in d["vp"])

    def cell(xs):
        n = len(xs)
        lost = sum(1 for c, _ in xs if c["pnl"] < 0)
        return {"trades": n, "losses": lost, "loss_rate": _r(lost / n, 3) if n else None,
                "mean_roe": _r(sum(float(c.get("roe") or 0) for c, _ in xs) / n) if n else None}
    tag = "최근 범위 끝에서 진입"
    q = Question("volume_profile", f"volume_profile:{aid}:{kst_day(now_ms)}",
                 f"{strat} {tf}: 진입 방향 바로 앞(1 ATR 안)에 매물대가 있던 거래 {len(d['vp'])}건 중 {vl}건 손실 — 매물대 "
                 "앞 진입을 피하면 덜 잃나?",
                 f"{strat} {tf}는 진입 방향 1 ATR 안에 매물대가 있으면 더 자주 진다: 그런 신호를 건너뛰면 덜 잃는다",
                 {"window": "최근 7일(신호와 함께 기록된 지지·저항 표시)", "account": aid,
                  "vp_ahead": cell(d["vp"]), "others": cell(d["other"]), "losses_by_level": by_level,
                  "median_distance_atr": _r(dist[len(dist) // 2], 2) if dist else None,
                  "all_36": {"vp_ahead_trades": allv["vp"][0], "vp_ahead_loss_rate": _r(allv["vp"][1] / allv["vp"][0], 3)
                             if allv["vp"][0] else None, "other_trades": allv["other"][0],
                             "other_loss_rate": _r(allv["other"][1] / allv["other"][0], 3) if allv["other"][0] else None},
                  "side_note": "진입 방향 앞 = 롱이면 진입가 바로 위, 숏이면 바로 아래. 매물대 = 최근 200봉 거래량이 몰린 가격대"
                               "(매물 최다 가격·위 끝·아래 끝)",
                  "research_note": "5년 진입 연구(사전 등록)는 지지·저항·매물대까지 거리가 거래 결과와 무관하다고 결론냄 "
                                   "(RESULTS_ENTRY_A)",
                  "grammar_note": "매물대 조건은 5년 시험 문법·36개 고쳐 보기에 없음: 가장 가까운 것은 '최근 범위 끝에서 진입' "
                                  "건너뛰기. 옮길 수 없으면 lab_idea는 engine none과 그 이유"},
                 {"labtest": _what_ifs(strat, tf, [tag] if tag in _skip_tags() else []), "newlab_filters": [],
                  "strategies": [strat]},
                 n_evidence=len(d["vp"]) + len(d["other"]))
    return _trim(q)


# the nearest newlab grammar to each DeepSeek family (an approximation code states as such; [] = nothing close)
DS_TWINS = {
    "F1": (("rsi_reversal", "mfi_reversal"), ()), "F2": (("inside_break",), ()), "F3": (("donchian_break",), ()),
    "F4": (("ema_cross",), ({"kind": "trend_ema", "length": 50},)),
    "F5": (("bb_revert",), ({"kind": "adx", "mode": "below", "level": 20},)), "F6": ((), ()),
    "F7": (("supertrend_flip",), ()), "F8": ((), ()), "F9": ((), ()), "F10": ((), ()), "F11": ((), ()),
    "F12": (("donchian_break",), ()), "F13": (("bb_revert",), ()), "F14": ((), ()),
    "F15": (("inside_break",), ({"kind": "session", "window": "europe"}, {"kind": "session", "window": "us"})),
    "F16": ((), ()), "F17": (("bb_revert", "cci_extreme"), ()),
}


def q_ds_counts(board: dict, now_ms: int) -> Optional[Question]:
    """The DeepSeek family with the lowest win rate (MIN_DS_TRADES+ trades) below the coin flips of the DeepSeek
    timeframes: counts and ratios only (dsmoney: no P&L, wallet or USDT)."""
    from . import dsmoney as DM
    from ..groups import DS_FAMILY_KO
    gs = board.get("groups") or {}
    ds = gs.get("ds200")
    if not isinstance(ds, dict) or not ds.get("by_family"):
        return None
    flips = (gs.get("flip") or {}).get("by_timeframe") or {}
    ft = sum(int((flips.get(tf) or {}).get("trades") or 0) for tf in (ds.get("by_timeframe") or {}) if tf in TFS)
    fw = sum(int((flips.get(tf) or {}).get("wins") or 0) for tf in (ds.get("by_timeframe") or {}) if tf in TFS)
    if not ft:
        return None
    fwr = fw / ft
    rows = []
    for fam, c in (ds.get("by_family") or {}).items():
        n = int((c or {}).get("trades") or 0)
        if n >= MIN_DS_TRADES:
            rows.append((int(c.get("wins") or 0) / n, fam, c))
    rows.sort(key=lambda r: (r[0], r[1]))
    if not rows or rows[0][0] >= fwr:
        return None
    wr, fam, c = rows[0]
    cell = DM.strict_cell({"accounts": c.get("accounts"), "trades": c.get("trades"), "busts": c.get("busts"),
                           "trades_per_account": _r(int(c["trades"]) / int(c["accounts"]), 1) if c.get("accounts") else None,
                           "win_rate": _r(wr, 3), "small_sample": False})
    name = DS_FAMILY_KO.get(fam, fam)
    entries, filters = DS_TWINS.get(fam, ((), ()))
    q = Question("ds_counts", f"ds_counts:{fam}:{kst_day(now_ms)}",
                 f"딥시크 {fam} {name}: 거래 {c['trades']}건 승률 {wr * 100:.0f}%, 같은 봉 동전 승률 {fwr * 100:.0f}% — 정의의 "
                 "어느 부분이 지게 만드나?",
                 f"딥시크 {name}의 진입에 조건 하나를 더하면(가장 가까운 문법으로) 5년 자료에서 동전보다 나아진다",
                 {"family": fam, "name_ko": name, "cell": cell, "coin_flip_win_rate": _r(fwr, 3),
                  "coin_flip_trades": ft,
                  "families_lowest_win_rate": [{"family": f, "name_ko": DS_FAMILY_KO.get(f, f), "trades": x.get("trades"),
                                                "win_rate": _r(w, 3)} for w, f, x in rows[:5]],
                  "notes": [DM.STRICT_NOTE_KO, "딥시크 정의 그대로는 5년 시험 문법에 없음: handles는 코드가 정한 가장 가까운 "
                            "새 매매법 문법(근사)", "가족 17개를 견주면 우연히 나빠 보이는 가족이 나옴(여러 번 비교)"]},
                 {"labtest": [], "newlab_filters": list(filters), "newlab_entries": list(entries), "strategies": []},
                 n_evidence=int(c["trades"]))
    return _trim(q)


def q_near_miss(agents: Optional[sqlite3.Connection], now_ms: int) -> Optional[Question]:
    """Lab tests that failed only one or two of the six checks (their first result's stored checks)."""
    if agents is None:
        return None
    from .labintake import CHECK_MARKS, NEWLAB_CHECK_KO, why_fail
    try:
        rows = agents.execute(
            "SELECT t.id, t.spec, COALESCE(json_extract(r.result, '$.ledger.checks'), json_extract(r.result, "
            "'$.gate.checks')) FROM trials t JOIN trial_results r ON r.id = (SELECT MIN(id) FROM trial_results WHERE "
            "trial_id = t.id) WHERE t.kind = 'newlab' ORDER BY t.id DESC LIMIT 400").fetchall()
    except sqlite3.Error:
        return None
    near = []
    for tid, spec, raw in rows:
        try:
            checks, sp = json.loads(raw or "null"), json.loads(spec or "null")
        except (TypeError, ValueError):
            continue
        if not isinstance(checks, dict) or not isinstance(sp, dict):
            continue
        failed = [m for k, m in CHECK_MARKS.items() if checks.get(k) is False]
        if 1 <= len(failed) <= 2:
            near.append((len(failed), -int(tid), int(tid), sp, failed))
    if not near:
        return None
    near.sort()
    try:
        from . import newlab as NL
        desc = NL.describe_ko
    except Exception:  # noqa: BLE001  (the lab module is optional on this side)
        desc = None
    items, filters = [], []
    for _n, _neg, tid, sp, failed in near[:5]:
        try:
            d = desc(sp) if desc else json.dumps(sp, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            d = json.dumps(sp, ensure_ascii=False)
        items.append({"trial": tid, "desc": str(d)[:140], "failed": failed,
                      "failed_ko": [NEWLAB_CHECK_KO.get(m, m) for m in failed]})
        filters += [f for f in sp.get("filters") or [] if isinstance(f, dict)]
    wf = why_fail(agents)
    top = max(it["trial"] for it in items)
    q = Question("near_miss", f"near_miss:{top}:{kst_day(now_ms)}",
                 "연구실 새 매매법 시험 중 관문 한두 칸만 못 넘은 것들: 그 칸을 넘을 다른 아이디어는?",
                 "아깝게 떨어진 시험의 약한 칸은 다른 진입 가족에 같은 필터를 붙이면 넘을 수 있다",
                 {"near_misses": items, "why_fail": {"tests": wf["tests"], "failed": wf["failed"]},
                  "rule_note": "떨어진 시험에서 한 가지만 바꾼 것은 '비슷한 실패 시험'(닮은 점수 7 이상)으로 시험하지 않음: "
                               "진입 가족을 바꾸거나 36개 고쳐 보기로 그 칸을 노림. 시험이 늘수록 통과 기준이 엄격해짐"},
                 {"labtest": [], "newlab_filters": _dedupe(filters)[:4], "newlab_entries": _untested_families(agents),
                  "strategies": []},
                 n_evidence=len(near))
    return _trim(q)


def _untested_families(agents: Optional[sqlite3.Connection], k: int = 6) -> list[str]:
    tested: set = set()
    if agents is not None:
        try:
            for (sp,) in agents.execute("SELECT spec FROM trials WHERE kind = 'newlab'"):
                fam = ((json.loads(sp) or {}).get("entry") or {}).get("family")
                if fam:
                    tested.add(fam)
        except (sqlite3.Error, TypeError, ValueError, AttributeError):
            pass
    try:
        from .newlab_signals import FAMILIES
    except Exception:  # noqa: BLE001  (the grammar tables are optional on this side)
        return []
    return [f for f in FAMILIES if f not in tested][:k]


def q_coverage(paper: sqlite3.Connection, agents: Optional[sqlite3.Connection], board: dict, now_ms: int,
               covered: Optional[dict] = None, since: Optional[int] = None) -> Optional[Question]:
    """The weekly rotation: the strategy of the 36 debated least recently (``covered`` {strategy: last ts}; one never
    debated counts from ``since``, the rotation's start). ``urgent`` once that is COVER_URGENT_MS ago."""
    pc = board.get("pass_check") or {}
    names = sorted({a.partition("@")[0] for a in pc if a.partition("@")[2] in TFS})
    if not names:
        return None
    cov = covered if isinstance(covered, dict) else {}
    base = int(since if since is not None else now_ms)

    def last(s):
        try:
            return int(cov.get(s) or 0) or base
        except (TypeError, ValueError):
            return base
    strat = min(names, key=lambda s: (last(s), s))
    age = max(0, int(now_ms) - last(strat))
    league = board.get("league") or {}
    tfs = (board.get("by_strategy") or {}).get(strat) or {}
    by_tf = {}
    for tf in TFS:
        v = pc.get(f"{strat}@{tf}") or {}
        flips = list(((league.get(tf) or {}).get("coin_flip_wallets") or {}).values())
        by_tf[tf] = {"trades": v.get("trades"), "wallet": v.get("wallet"), "mean_roe": (tfs.get(tf) or {}).get("mean_roe"),
                     "win_rate": (tfs.get(tf) or {}).get("win_rate"),
                     "coin_flip_mean_wallet": _r(sum(flips) / len(flips), 2) if flips else None}
    weak = min((tf for tf in TFS if by_tf[tf]["wallet"] is not None),
               key=lambda t: (by_tf[t]["wallet"], t), default=TFS[0])
    cs = [c for c in _strategy_cards(paper, now_ms - 7 * DAY_MS, now_ms + 1, limit=600)
          if c.get("strategy") == strat]
    tags = _tag_rows(cs)
    bad = [r["tag"] for r in tags if (r["loss_share"] or 0) > (r["win_share"] or 0)][:2]
    days = None if not cov.get(strat) else _r(age / DAY_MS, 1)
    q = Question("coverage", f"coverage:{strat}:{kst_day(now_ms)}",
                 f"이번 주 {strat} 차례(36개를 한 주에 한 번씩): 4개 봉 성적과 5년 결과로 보면 시험할 고칠 점 하나는?",
                 f"{strat}의 가장 약한 봉({weak})은 규칙 하나를 바꾸면 5년 자료에서도 덜 잃는다",
                 {"strategy": strat, "days_since_debated": days, "by_timeframe": by_tf, "weakest_tf": weak,
                  "week": {"trades": len(cs), "tags": tags[:4]}, "tags_note": TAGS_NOTE_KO,
                  "tested_here": _tested_tests(agents, strat, 4), "prior_5y": _prior(strat)},
                 {"labtest": _what_ifs(strat, weak, bad), "newlab_filters": _twins(bad), "strategies": [strat]},
                 n_evidence=sum(int(v["trades"] or 0) for v in by_tf.values()), urgent=age >= COVER_URGENT_MS)
    return _trim(q)


def covered_update(covered: Optional[dict], q: Question, now_ms: int) -> dict:
    """The coverage record after asking ``q``: a question focused on one or two strategies (FOCUS_KINDS) counts as
    their turn. Returns a new dict."""
    out = dict(covered) if isinstance(covered, dict) else {}
    if q.kind in FOCUS_KINDS:
        for s in (q.handles.get("strategies") or [])[:2]:
            out[s] = int(now_ms)
    return out


def q_event(paper: sqlite3.Connection, board: dict, now_ms: int, seen: Optional[dict] = None,
            start: Optional[int] = None) -> Optional[Question]:
    """A NEW bust or critical alert of one of the 36 (debate_packet.unusual with the last ok round's marks)."""
    flags = [k for k, _w in P.unusual(board, None, seen, start) if k == "risk"]
    if not flags:
        return None
    if not isinstance(seen, dict) or seen.get("start") != start:
        seen = None                                         # as P.unusual: another run's marks count as none
    marks = P.agenda_marks(board, start)
    pc = board.get("pass_check") or {}                      # the 36's accounts (a coin flip's alert is not a question)
    # the NEW thing, never an old one: a CRITICAL alert of the 36 newer than the last ok round's mark (newest first),
    # then (when the bust count grew) the busted account of the 36 with the latest losing trade
    crit = []
    for a in ((board.get("today") or {}).get("alerts") or []):
        text = str(a.get("text") or "")
        if a.get("level") == "CRITICAL" and text.startswith("[") and "]" in text and text[1:text.find("]")] in pc:
            if seen is None or int(a.get("ts") or 0) > int(seen.get("crit_ts") or 0):
                crit.append((int(a.get("ts") or 0), text[1:text.find("]")]))
    crit = [aid for _ts, aid in sorted(crit, key=lambda x: -x[0])]
    busts: list = []
    if seen is None or marks["busts"] > int(seen.get("busts") or 0):
        last = {}
        for a in (a for a, v in pc.items() if v.get("bust")):
            r = paper.execute("SELECT MAX(exit_time) FROM trades WHERE account_id = ? AND pnl < 0", (a,)).fetchone()
            last[a] = int((r[0] if r else 0) or 0)
        busts = sorted(last, key=lambda a: (-last[a], a))
    aid = next((a for a in crit + busts if a.partition("@")[2] in TFS), None)
    if aid is None:
        return None                                         # the new thing was not one of the 36's (a coin flip)
    strat, _, tf = aid.partition("@")
    cs = _strategy_cards(paper, 0, now_ms + 1, losses_only=True, limit=5, account=aid)
    tags = [t for t in _skip_tags() if sum(t in (c.get("tags") or []) for c in cs) >= 2]
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
               readback: Optional[dict] = None, covered: Optional[dict] = None,
               covered_since: Optional[int] = None) -> list[Question]:
    """Every question the data supports now (read-only). ``board``: packets3.build's board when the caller already
    has it; ``seen`` / ``start``: the last ok round's agenda marks and the run's start (only a NEW event counts);
    ``covered`` / ``covered_since``: the weekly coverage record (``covered_update``) and when the rotation began."""
    from . import packets3
    if board is None:
        board = packets3.build(paper_path, daily_path, now_ms)
    paper, agents = P.open_ro(paper_path), P.open_ro(agents_path)
    out: list[Question] = []
    try:
        if paper is not None:
            week: list = []
            try:
                week = _week(paper, now_ms)
            except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
                _note(f"week cards failed: {type(exc).__name__}: {exc}")
            for fn in (lambda: q_event(paper, board, now_ms, seen, start), lambda: q_big_losses(paper, now_ms),
                       lambda: q_loss_traits(paper, now_ms), lambda: q_best_luck(paper, agents, board, now_ms),
                       lambda: q_tf_split(paper, agents, board, now_ms), lambda: q_loss_tag(paper, now_ms),
                       lambda: q_session_cell(paper, now_ms, week), lambda: q_coin_cell(paper, now_ms, week),
                       lambda: q_regime_cell(paper, now_ms, week), lambda: q_pairs(paper, now_ms, week),
                       lambda: q_volume_profile(paper, agents, now_ms, week), lambda: q_ds_counts(board, now_ms),
                       lambda: q_near_miss(agents, now_ms),
                       lambda: q_coverage(paper, agents, board, now_ms, covered, covered_since)):
                try:
                    q = fn()
                except (sqlite3.Error, KeyError, TypeError, ValueError, ZeroDivisionError) as exc:  # one kind never
                    q = None                                                                       # stops the others
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
    """Fresh enough to ask: never asked; asked today fewer than MAX_ASKS_A_DAY rounds; a worst_vs_flip / best_luck
    account asked on an earlier day is fresh again after REFRESH_MS or REFRESH_TRADES more trades (other kinds carry
    their day or their evidence in the key, so a new day or new evidence is a new key)."""
    rec = (asked or {}).get(q.key)
    if not isinstance(rec, dict):
        return True
    if rec.get("day") == kst_day(now_ms):
        return int(rec.get("n") or 0) < MAX_ASKS_A_DAY
    if q.kind in REFRESH_KINDS:
        return (now_ms - int(rec.get("ts") or 0) >= REFRESH_MS
                or q.n_evidence - int(rec.get("n_evidence") or 0) >= REFRESH_TRADES)
    return True


def pick(cands: list[Question], asked: Optional[dict], last_kind: Optional[str], now_ms: int,
         force: bool = False) -> Optional[Question]:
    """One question: an event first; then an overdue coverage question (a strategy not debated for COVER_URGENT_MS;
    not twice in a row); then the next kind in rotation after ``last_kind`` that has a fresh candidate (never the same
    kind twice in a row), the strongest evidence within it; retro only when nothing else is fresh or ``force`` (the
    6-hour forced round). None: nothing fresh (a free 'no_question' skip)."""
    ok = [q for q in cands if eligible(q, asked, now_ms)]
    # an event jumps the queue even right after another event: each is a NEW bust or alert (its key carries the
    # marks, and the next round's marks no longer count it), so a second one would otherwise never be asked
    ev = [q for q in ok if q.kind == "event"]
    if ev:
        return max(ev, key=lambda q: (q.n_evidence, q.key))
    fresh = [q for q in ok if q.kind != last_kind]
    urgent = [q for q in fresh if q.urgent]
    if urgent:
        return urgent[0]
    retro = [q for q in fresh if q.kind == "retro"]
    if force:
        # the forced round (hours without news) asks the retro question, even right after a retro: a forced round
        # is never a skip
        retro = retro or [q for q in ok if q.kind == "retro"]
        if retro:
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


def deep_pick(cands: list[Question]) -> Optional[Question]:
    """The daily deep debate's question: the most important kind with a candidate (``DEEP_ORDER``), the strongest
    evidence within it. The per-key day limit does not apply (it is a separate, once-a-day round)."""
    for k in DEEP_ORDER:
        xs = [q for q in cands if q.kind == k]
        if xs:
            return max(xs, key=lambda q: (q.n_evidence, q.key))
    return None


def asked_record(prev: Optional[dict], q: Question, now_ms: int) -> dict:
    """The value the caller stores under 'asked:<key>' after asking ``q``."""
    day = kst_day(now_ms)
    n = int((prev or {}).get("n") or 0) + 1 if (prev or {}).get("day") == day else 1
    return {"day": day, "n": n, "ts": int(now_ms), "n_evidence": int(q.n_evidence), "kind": q.kind}
