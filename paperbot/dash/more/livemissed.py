"""실거래 › 못 탄 신호 (#/livebots/missed; owners 10/19 "못 탄 신호들은 어땠나", "진입을 안 했는데 좋은 놓친 신호 분석 같은 거"): what
every signal the paper bot did not take would have done, by why it was not taken (한 번에 하나 · 연구 조건 밖 · 돌파 없음 · 쉬는
시간 · 늦음·재시작), and the paper trades the executors did not follow (their paper result), next to the trades it did take.
Read-only and view only: no rule of the bots changes here.

    GET /api/v4/livebots/missed?span=7d|all&group=all|one|research|nobreak|pause|late|exec&result=all|win|loss
        the cards (실제로 탄 거래, then each group: n, closed, 이김 / 짐, win rate, net ROE sum and mean, the other states, the
        one-line read), the rows of the chosen group and result, newest first (at most ROWS_KEEP), with the totals of that
        group for both sides whatever the result filter (``list``); 5 s cache

Where it reads (the 실거래 tabs' own paths, dash/more/livebots.py ``paths`` / ``paths_more``):
    PAPERBOT_LIVE_CHECK_DB   /var/lib/paperbot/livecheck.db   table ``missed`` and ``missed_meta``, written by the 1-minute
                             watcher's pass (paperbot/livemissed.py ``missed_pass``: each not-entered signal simulated on the
                             paper bot's own engine with the rule bot's 1m bars, paperbot/livesim.py; the executors' misses
                             with the paper trade's own result)
    PAPERBOT_LIVE_PAPER_DB   /var/lib/paperbot/combo/live-ac.db  the paper account's closed trades and open position (the
                             trades it really took over the same span; the result of the trade that had the place, fresh)
Both ``mode=ro`` + ``query_only``, one snapshot each.

States (CONTRACT §1.6): the watcher's file or its table not there yet -> ``missing`` (수집 전: "1분 감시가 아직 기록 전"),
unreadable -> ``error`` (못 읽음 + why), never an empty list that reads as "nothing missed". The paper database unreadable
only blanks the 실제로 탄 거래 card (its own state). A pass that stopped: ``pass.stale``.
Numbers: ratios (0.112 = +11.2 % net ROE), times UTC ms. Funding is not in the virtual results (livesim FUNDING_NOTE_KO).
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Optional

from . import livebots as L

ROWS_KEEP = 300                          # rows sent (the page shows 10 a page)
PASS_STALE_MS = 10 * 60_000              # the watcher runs every minute
SPANS = (("7d", "최근 7일"), ("all", "기록 전체"))
RESULTS = (("all", "전체"), ("win", "이겼을 신호"), ("loss", "졌을 신호"))
MISSING_KO = "1분 감시가 아직 기록 전이에요 (못 탄 신호는 1분 감시가 매번 계산해요)"
NO_TABLE_KO = "점검 파일은 있지만 못 탄 신호 표가 아직 없어요 (1분 감시가 아직 기록 전)"
SMALL_KO = "20번 미만은 대부분 운이에요"
# the trend bot (owners 10-21): its blocks (the trend judge, the entry checks, the pullback while its config waits) were
# never measured on the 5-year data, so the old line "필터는 5년 시험에서 …" is not its; said instead (trend_filter_note)
TREND_FILTER_TAIL_KO = ("은 새 규칙이라 아직 숫자로 확인하지 않았어요. 이긴 것만 보면 아쉬움만 커져요: 진 것과 같이 봐야 해요. 규칙은 "
                        "시작부터 2주 동안 바꾸지 않고, 그 뒤 두 분이 검토해요.")
TREND_FILTER_NOTE_KO = "추세판단 봇이 막는 규칙(추세 판단 · 진입 전 검사 · 되돌림)" + TREND_FILTER_TAIL_KO


def trend_filter_note(tb: Optional[dict]) -> str:
    """TREND_FILTER_NOTE_KO for a config that waits for its pullback; without it (바로 진입, owners 10-22) no 되돌림."""
    if L.trend_waits((tb or {}).get("config")):
        return TREND_FILTER_NOTE_KO
    return "추세판단 봇이 막는 규칙(추세 판단 · 진입 전 검사)" + TREND_FILTER_TAIL_KO


def _LM():
    from ... import livemissed as LM
    return LM


def read_missed(path: str, now: int, span: str) -> dict:
    """livecheck.db ``missed`` (rows of the span, ``livemissed.row_out`` shape, newest first) and the last pass."""
    LM = _LM()
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path, MISSING_KO)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "missed" not in tables:
            return L._missing(path, NO_TABLE_KO)
        meta = {k: (ts, L._j(d)) for k, ts, d in conn.execute("SELECT k, ts, data FROM missed_meta")} \
            if "missed_meta" in tables else {}
        first = (meta.get("first") or (None, {}))[1].get("since")
        since = LM.window_start(now) if span == "7d" else (L._i(first) if first is not None else 0)
        rows = LM.read_rows(conn, since)
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    last_ts, last = meta.get("pass") or (None, {})
    return {"state": "ok", "path": path, "since_ms": since, "rows": rows,
            "pass": {"last_ms": last_ts, "stale": last_ts is None or now - last_ts > PASS_STALE_MS, "state": last.get("state"),
                     "left": L._i(last.get("left")) or 0, "capped": bool(last.get("capped")), "error": last.get("error"),
                     "rig_error": last.get("rig_error"), "config": last.get("config"), "funding": last.get("funding") or "excluded",
                     "first_ms": L._i(first), "executors": last.get("executors") or {}}}


def _fresh_taken(t: Optional[dict], by_id: dict, pos: Optional[dict]) -> Optional[dict]:
    """The trade that had the place, its result from the paper database now (closed since the watcher stored it, or its
    open position's net ROE at the last mark)."""
    if not t:
        return t
    out = dict(t)
    tr = by_id.get(L._i(t.get("id"))) if t.get("id") is not None else None
    if tr is None and t.get("state") == "open":
        tr = next((x for x in by_id.values() if x.get("entry_time") == L._i(t.get("entry_time")) and x.get("symbol") == t.get("symbol")), None)
    if tr is not None:
        out.update(id=tr["id"], state="closed", roe=tr["roe"], pnl=tr["pnl"], reason=tr["exit_reason"],
                   reason_ko=_LM().KO_EXIT.get(tr["exit_reason"], tr["exit_reason"]), exit_time=tr["exit_time"])
    elif t.get("state") == "open" and pos and pos.get("entry_time") == L._i(t.get("entry_time")) and pos.get("symbol") == t.get("symbol"):
        out["roe"] = pos.get("last_mark_roe_net")
    return out


def result_of(r: dict) -> str:
    """"win" / "loss" for a closed row, else its state (the result filter keeps closed rows only)."""
    if r.get("state") != "closed":
        return str(r.get("state"))
    return "win" if r.get("win") else "loss"


PLAIN_KO = ("이 봇의 못 탄 신호는 1분 감시가 아직 가상으로 따라가 보지 않아요 (가상 결과는 추세판단 봇 신호만 계산해요) · 그래서 왜 못 "
            "탔는지와 그때 조건이 읽은 숫자만 보여요 · 실행기가 안 따라간 거래는 페이퍼 거래의 실제 결과예요")
# its gates are the owners' 10/23 rules (docs/vwap-bot-ko.md 2장), not the 5-year filters of FILTER_NOTE_KO: said as such
PLAIN_FILTER_KO = ("조건(4시간 추세 반대 · 변동성 높음 · 쉬는 시간 · 한 번에 하나)은 설정 그대로예요 (docs/vwap-bot-ko.md 2장). 여기는 "
                   "보기만 해요: 규칙을 바꿀지는 두 분이 정하고, 바꾸려면 13장 순서(백테스트 → 그림자 → 채택)를 따라요.")
PLAIN_ONE = {"in position": ("one", "한 번에 하나 (포지션 있음)"), "lower score than entered signal": ("one", "같은 때 다른 신호에 밀림"),
             "late": ("late", "늦음")}


def plain_rows(path: str, since: int) -> tuple:
    """(rows, state) of a paper bot's not-taken signals from ``since`` (its own signal_log and outcomes): each filtered
    signal with its why (livebots.why_cat / why_words) and what its gates read (``gates_ko``), each submitted one the
    engine did not enter (한 번에 하나 · 밀림 · 늦음). Newest first. No virtual result (PLAIN_KO)."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return [], L._missing(path)
    except (OSError, sqlite3.Error) as exc:
        return [], L._err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "signal_log" not in tables:
            return [], L._missing(path, L.NO_TABLE_KO)
        sigs = conn.execute("SELECT bar_close, timeframe, strategy, symbol, side, status, data FROM signal_log WHERE bar_close >= ? "
                            "AND status IN ('FILTERED', 'SUBMITTED') ORDER BY bar_close, id", (int(since),)).fetchall()
        outs = conn.execute("SELECT step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? AND step_ts >= ? "
                            "AND status IN ('SKIPPED', 'REJECTED')", (L.ACCOUNT, int(since))).fetchall() if "outcomes" in tables else []
    except sqlite3.Error as exc:
        return [], L._err(path, exc)
    finally:
        conn.close()
    oc = {}
    for step, st, reason, sym, data in outs:
        sig = L._j(data).get("signal") or {}
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        if L._i(sig.get("ts")) is not None:
            oc[(L._i(sig["ts"]) + 1, sig.get("timeframe"), meta.get("member") or sig.get("strategy_id"), sym)] = (st, reason, meta.get("gates"))
    rows = []
    for bc, tf, member, sym, side, status, data in sigs:
        d = L._j(data)
        gates = d.get("gates") if isinstance(d.get("gates"), dict) else None
        if status == "FILTERED":
            cat, ko = L.why_cat(status, d.get("why"))
            why = d.get("why")
        else:
            o = oc.get((L._i(bc), tf, member, sym))
            if o is None:
                continue                                    # entered, or its result not written yet
            cat, ko = PLAIN_ONE.get(o[1], ("other", L.outcome_cat(o[0], o[1])[1]))
            why, gates = ko, gates or (o[2] if isinstance(o[2], dict) else None)
        rows.append({"t": L._i(bc), "tf": tf, "member": member, "strategy": d.get("strategy") or str(member).split("@")[0], "symbol": sym,
                     "side": L._i(side), "grp": cat, "grp_ko": ko, "why": why, "why_ko": L.why_words(why) if why else None,
                     "gates_ko": L.gates_text(gates), "state": "none"})
    rows.reverse()
    return rows, None


def plain(p: dict, now: int, span: str, group: str, bots: list, b: dict, execs: list) -> dict:
    """GET /api/v4/livebots/missed?bot=paper2 (owners 10-23: the 'VWAP 개선판'): its not-taken signals by why (its gates'
    reasons in their own categories) with what its gates read, and the paper trades of it that an executor following it
    did not follow (why, from the executor's own records; their paper result, not a virtual one). ``kind`` "plain"."""
    LM = _LM()
    since = LM.window_start(now) if span == "7d" else 0
    rows, st = plain_rows(b["path"], since)
    base = {"now_ms": now, "span": span, "spans": [{"id": k, "ko": ko} for k, ko in SPANS], "kind": "plain", "bot": b["id"],
            "bot_ko": b["short_ko"], "bots": L.bots_out(bots), "note_ko": PLAIN_KO, "filter_note_ko": PLAIN_FILTER_KO,
            "small_ko": SMALL_KO, "since_ms": since}
    if st is not None:
        return {**base, **{k: st.get(k) for k in ("state", "reason_ko", "reason", "path")}, "rows": [], "n_rows": 0, "groups": [],
                "group": "all"}
    pr = b["read"]
    a = (pr.get("accounts") or {}).get(L.ACCOUNT) if pr.get("state") == "ok" else None
    cfg = L.cfg_of(pr)
    for x in execs:                                     # its trades an executor following it then did not follow
        if x["record"].get("state") != "ok":
            continue
        took = {pt["id"] for pt in L.pairs_of(x).values() if L.LP.same(pt["paper_path"], b["path"])}
        for t in (a or {}).get("trades") or []:
            if (t.get("entry_time") or 0) < since or t["id"] in took or not L.followed_at(x, b["path"], t.get("entry_time")):
                continue
            w = L.why_missed(x["record"], t, L.ACCOUNT)
            if w.get("state") != "missed":
                continue
            rows.append({"t": t.get("entry_time"), "tf": t.get("timeframe"), "member": None, "strategy": t.get("strategy_id"),
                         "symbol": t.get("symbol"), "side": t.get("side"), "grp": "exec", "grp_ko": f"{x['name_ko']}가 안 따라감",
                         "why": w.get("why_ko"), "why_ko": w.get("why_ko"), "gates_ko": None, "state": "closed", "roe": t.get("roe"),
                         "pnl": t.get("pnl"), "win": (t.get("pnl") or 0) > 0, "reason_ko": L.exit_words(t.get("exit_reason"), cfg, t.get("exit_why")),
                         "ex": x["id"]})
    rows.sort(key=lambda r: -(r["t"] or 0))
    groups: dict = {}
    for r in rows:
        g = groups.setdefault(r["grp"], {"id": r["grp"], "ko": r["grp_ko"] if r["grp"] != "exec" else "실행기가 안 따라감", "n": 0})
        g["n"] += 1
    gs = sorted(groups.values(), key=lambda g: -g["n"])
    group = group if group in groups else "all"
    shown = [r for r in rows if group == "all" or r["grp"] == group]
    return {**base, "state": "ok", "path": b["path"], "groups": gs, "group": group, "counts": {"all": len(rows), **{g["id"]: g["n"] for g in gs}},
            "rows": shown[:ROWS_KEEP], "n_rows": len(shown)}


def build(p: dict, more: dict, now: int, span: str = "7d", group: str = "all", result: str = "all", bot: str = "paper") -> dict:
    """GET /api/v4/livebots/missed (module docstring). ``bot`` "paper2": the second paper bot's (``plain``); with two
    paper bots the main answer carries the switch (``bots``)."""
    LM = _LM()
    from ...livesim import FUNDING_NOTE_KO
    span = span if span in dict(SPANS) else "7d"
    bots, execs = [], []
    if all(p.get(k) for k in ("bybit_db", "mexc_db", "bybit_config", "mexc_config")):     # (a caller may name only the paper)
        _c, _f, paper0, execs = L.sources(p, now)
        bots = L.paper_bots(p, paper0, execs)
    if len(bots) > 1 and bot != "paper":
        b = next((x for x in bots if x["id"] == bot), None)
        if b is not None:
            return plain(p, now, span, group, bots, b, execs)
    out = _main(p, more, now, span, group, result, LM, FUNDING_NOTE_KO)
    if len(bots) > 1:
        out.update(bot="paper", bot_ko=bots[0]["short_ko"], bots=L.bots_out(bots))
    return out


def _main(p: dict, more: dict, now: int, span: str, group: str, result: str, LM, FUNDING_NOTE_KO: str) -> dict:
    """The main paper bot's answer (the watcher's virtual results), as it always was."""
    group = group if group in LM.GROUPS else "all"
    result = result if result in dict(RESULTS) else "all"
    tb = L.trend_bot(p["paper"])                         # the trend bot: its blocks were never measured on 5 years (said)
    base = {"now_ms": now, "span": span, "group": group, "result": result, "spans": [{"id": k, "ko": ko} for k, ko in SPANS],
            "groups_ko": [{"id": g, "ko": LM.GROUP_KO[g]} for g in LM.GROUPS], "results": [{"id": k, "ko": ko} for k, ko in RESULTS],
            "note_ko": LM.NOTE_KO, "filter_note_ko": trend_filter_note(tb) if tb else LM.FILTER_NOTE_KO, "funding_ko": FUNDING_NOTE_KO,
            "small_ko": SMALL_KO, "small_n": LM.SMALL, "trend_bot": L.trend_out(tb)}
    m = read_missed(more["check_db"], now, span)
    if m.get("state") != "ok":
        return {**base, **{k: m.get(k) for k in ("state", "reason_ko", "reason", "path")}, "rows": [], "n_rows": 0, "summary": None,
                "list": None, "paper": None, "pass": None}
    paper = L.read_paper(p["paper"], [L.ACCOUNT], now)
    a = (paper.get("accounts") or {}).get(L.ACCOUNT) if paper.get("state") == "ok" else None
    trades = (a or {}).get("trades") or []
    pos = (a or {}).get("position")
    by_id = {t["id"]: t for t in trades}
    rows = m["rows"]
    for r in rows:
        if r.get("taken"):
            r["taken"] = _fresh_taken(r["taken"], by_id, pos)
        r["result"] = result_of(r)
    s = LM.summary_of(rows, trades, (pos or {}).get("entry_time"), m["since_ms"])
    if a is None:
        s["taken"] = None
    in_group = [r for r in rows if group == "all" or r["grp"] == group]
    lst = LM.block_of(in_group)                       # the chosen group's totals, both sides, whatever the result filter
    shown = [r for r in in_group if result == "all" or r["result"] == result]
    paper_state = {k: paper.get(k) for k in ("state", "reason_ko", "reason", "path")} if paper.get("state") != "ok" else \
        ({"state": "ok"} if a is not None else {"state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요"})
    return {**base, "state": "ok", "path": m["path"], "since_ms": m["since_ms"], "pass": m["pass"], "summary": s, "paper": paper_state,
            "list": {**lst, "group": group, "group_ko": "전체" if group == "all" else LM.GROUP_KO[group],
                     "read_ko": None if group == "all" else LM.read_ko(group, lst), "shown": len(shown)},
            "counts": {"all": len(rows), **{g: sum(1 for r in rows if r["grp"] == g) for g in LM.GROUPS}},
            "rows": shown[:ROWS_KEEP], "n_rows": len(shown), "funding_included": m["pass"].get("funding") == "included"}


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/missed")
    def get_livebots_missed(span: str = "7d", group: str = "all", result: str = "all", bot: str = "paper"):
        """실거래 › 못 탄 신호: every not-entered signal's virtual result by group, next to the trades really taken; ``bot``
        paper2: the second paper bot's not-taken signals and why (read-only, 5 s cache)."""
        p, more = L.paths(), L.paths_more()
        LM = _LM()
        bt = bot if bot in ("paper", "paper2") else "paper"
        sp = span if span in dict(SPANS) else "7d"
        gr = (group if group in LM.GROUPS else "all") if bt == "paper" else (group if isinstance(group, str) and len(group) <= 40 else "all")
        rs = result if result in dict(RESULTS) else "all"
        key = "missed:" + json.dumps([p, more, sp, gr, rs, bt], sort_keys=True)
        return L._cached(key, lambda: json_finite(build(p, more, int(time.time() * 1000), sp, gr, rs, bt)))

    return {"routes": ["/api/v4/livebots/missed"], "paths": L.paths}
