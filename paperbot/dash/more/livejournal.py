"""실거래 › 기록 › 일지 (#/journal; owners 10/21: they check the site now and then, often on a phone, and want to know
"what happened while I was away"): one chronological feed of everything the 추세판단 봇 (paperbot/trendbot.py) and the
two real-money executors that follow its paper account did. Read-only, like every 실거래 tab: nothing here changes a bot,
a rule or an order. Nothing is worked out again here either: every row is a record the bots wrote, in the words the other
tabs already use, or a judgment change taken from the 추세 차트 tab's own recomputation.

    GET /api/v4/livebots/journal?hours=24|72|168   (5 s cache per span; the page asks every 60 s, every 15 s while the
                                                   judgments are still being fetched)
        events   newest first (at most MAX_EVENTS), each {id, t, kind, sub, tone, symbol, side, text (one sentence),
                 detail, link {tab, q}} and the fields of its kind:
                 trend    a coin's 1h (30m entries read it), 4h (1h entries) or daily (4h entries, owners 10-22) judgment
                          changed: 상승 / 하락 / 보류 with the votes and ADX (dash/more/livetrendchart.py ``history`` over the same bars and the same cache as
                          the 추세 차트 tab: at most FETCH_PER_BUILD fetches an answer); the last JUDGE_H hours only
                 signal   an entry member's signal and what became of it: 막힘 (주말 · 추격 · 발표 · 나스닥), 추세 판단에 걸림,
                          점검 탈락 + the bot's why, 점검 통과 → 진입 (바로 진입: the owners' config since 10-22), and with
                          a config that waits 되돌림 기다리는 중 (level, deadline), 되돌림 옴 → 진입, 되돌림 안 옴,
                          한 포지션이라 못 탐 (signal_log + the account's outcomes; livebots.why_cat / why_words, the wait
                          words of livecheck's ⏳ message); only the trend bot's own signals (from its first start)
                 trade    the paper account COMBO@mix: 진입 (member, coin, side, price, leverage; a pullback entry and an
                          entry on a 보류 judgment, 10-22 보류 허용, say so),
                          청산 (the reason in the Telegram words: livecheck.KO_EXIT, net ROE, P&L), 감독 청산 (TIME /
                          JUDGE with the bot's why); the coin-flip twin COMBOFLIP@mix's trades too, flagged ``twin`` (the
                          page shows them behind a switch). The paper engine keeps no record of when each lock step moved
                          (only the last lock, on the trade): an exit says how far its lock got. A trade entered before
                          the trend bot's start is the bot before it's (``prev``, 전환 전): tagged, and counted apart
                 exec     each executor (its own database, livebots.sources): entries and exits with the gap to the paper's
                          price (in the trade's favour positive, livebots.pairs_of for the partner), its lock steps (its
                          own 'stop' / 'own_lock' records), the paper entries it did not follow and why (livebots.WHY,
                          the strongest per entry as livebots.why_missed), its halts and its newest WARN / CRITICAL
                          records (livebots.read_exec keeps EVENTS_KEEP of them)
                 safety   starts (the paper bot: ``runs`` rows when there are any, else its last start record; the trend
                          bot's first start; each executor), an executor stopped by SIGTERM, the morning checks and the
                          watcher's alarms (livecheck.db: livebots.read_checks), the paper bot's warnings (``alerts``)
        counts   the span in one line: signals, passed the checks (waited for a pullback, or went in at once), waited
                 (``waits``), pullback touched, paper entries, paper exits and their net P&L, judgment changes (None for
                 what was not read: never a zero)
        judge    {state, covers_h, from, read, of, pending, note_ko, errors}: how much of the judgments could be read
        sources  the paper database, each executor and the live checks: state and reason
        capped   when more than MAX_EVENTS rows: the signals and judgment changes are cut oldest first (the trades,
                 executor and safety rows are always all there), with how many and from when

States (CONTRACT 1.6): the paper database missing / unreadable = ``state`` missing / error (the executors' rows still
show); the running paper bot is not the trend bot (``combo_run`` without ``trend``) = off: no signals and no judgments,
the trades and the executors' rows still show; the trend bot before its first judgment = missing with the reason (its
signals still show). A count of a source that was not read is None. Times are UTC ms (the page shows Korea time), ratios
are ratios (0.012 = 1.2 %), money is the paper's USDT or the executor's exchange USDT (``real``).
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Optional

from ... import livecheck as LC
from . import livebots as L
from . import livetrend as LT
from . import livetrendchart as LTC

ACCOUNT, FLIP = L.ACCOUNT, L.FLIP_ACCOUNT
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
HOURS = (24, 72, 168)                 # the page's spans: 24시간 · 3일 · 7일
JUDGE_H = LTC.HEAT_H                  # judgment changes: the 추세 차트 heatmap's 72 hours (a change links there and is in it)
MAX_EVENTS = 400                      # rows sent at most (the signals and judgment changes are cut first)
LOW = ("signal", "trend")             # the kinds cut first when there are more rows than MAX_EVENTS
SIG_SCAN = 4000                       # signal_log rows read at most (newest first; a week of the trend bot is ~450)
TRADES_SCAN = 600                     # paper trades read at most (both accounts)
ALERTS_SCAN = 500                     # the paper bot's newest alerts looked at
ALERTS_KEEP = 60                      # ... and kept (newest)
EXEC_SCAN = 300                       # an executor's lock-step / SIGTERM records read at most
TF_MS = LT.TF_MS
COINS = L.COINS
KINDS = (("trend", "추세"), ("signal", "신호"), ("trade", "거래"), ("exec", "실행기"), ("safety", "안전"))
ORDER = {"safety": 0, "exec": 1, "trade": 2, "signal": 3, "trend": 4}      # the same minute: the order rows are read
DIR_KO = {1: "상승", -1: "하락", 0: "보류"}
FROM_KO = {1: "상승에서", -1: "하락에서", 0: "보류에서"}
TO_KO = {1: "상승으로", -1: "하락으로", 0: "보류로"}
SIDE_KO = {1: "롱", -1: "숏"}
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
# what stopped a signal before its checks (livebots.why_cat ids): the pauses and the chase block, in the owners' words
BLOCK_KO = {"weekend": "주말이라 막힘", "macro": "경제 발표 앞뒤라 막힘", "usopen": "나스닥 개장 뒤라 막힘",
            "usopen_pre": "나스닥 개장 앞뒤라 막힘",
            "chase": "추격 막기에 걸림", "chase_unread": "추격 판단을 못 해 막힘"}
SUP = ("JUDGE", "TIME")
OFF_KO = "지금 돌고 있는 페이퍼 봇은 추세판단 봇이 아니에요 (설정에 추세 판단이 없음) · 거래와 실행기 기록만 보여요"
JUDGE_NOTE_KO = f"판단 기록은 최근 {JUDGE_H}시간만"
SINCE_KO = "추세판단 봇이 켜지기 전 신호는 빼요"
PREV_KO = f"추세판단 봇이 켜지기 전 예전 {LT.PREV_BOT_KO}의 거래"


# ================================================================ small helpers
def _f(x) -> Optional[float]:
    return L._f(x)


def _i(x) -> Optional[int]:
    return L._i(x)


def coin(sym) -> str:
    return str(sym or "").replace("USDT", "")


def price_ko(x) -> str:
    """A price as the bot writes it in its messages (livecheck's ``:,.6g``): 62,010 / 2,496.25 / 0.18542."""
    v = _f(x)
    return "—" if v is None else f"{v:,.6g}"


def pct_ko(x, dec: int = 1, sign: bool = True) -> str:
    v = _f(x)
    if v is None:
        return "—"
    s = f"{abs(v) * 100:.{dec}f}%"
    return (("+" if v > 0 else "−" if v < 0 else "") if sign else "") + s


def money_ko(x) -> str:
    v = _f(x)
    return "—" if v is None else f"{'+' if v > 0 else '−' if v < 0 else ''}${abs(v):,.2f}"


def kst(ms) -> str:
    """HH:MM in Korea time (livecheck.kst: the ⏳ message's clock)."""
    return LC.kst(int(ms))


def kst_dt(ms) -> str:
    """'10/19 17:30' in Korea time (livecheck.kst_dt)."""
    return LC.kst_dt(int(ms))


def _ev(id_: str, t, kind: str, sub: str, text: str, detail: Optional[str] = None, **kw) -> dict:
    return {"id": id_, "t": int(t), "kind": kind, "sub": sub, "text": text, "detail": detail or None, "tone": kw.pop("tone", ""),
            "symbol": kw.pop("symbol", None), "side": kw.pop("side", None), "link": kw.pop("link", None), **kw}


def _link(tab: str, **q) -> dict:
    return {"tab": tab, "q": {k: v for k, v in q.items() if v is not None} or None}


def _judge_text(tr: dict) -> Optional[str]:
    j = tr.get("judge") if isinstance(tr, dict) else None
    if isinstance(j, dict):
        return j.get("text")
    return j if isinstance(j, str) else None


# ================================================================ judgment changes (the 추세 차트 tab's recomputation)
def changes_of(sym: str, tf: str, cells: list, t_from: int, adx_min: float = 20.0) -> list:
    """The cells (livetrendchart.cells_of: the one in force at ``t_from`` first) where the judgment's direction changed
    (상승 / 하락 / 보류), against the last readable cell before it; a 못 읽음 cell is skipped, never a change. ``adx_min``:
    the rules' strength line (the words of 힘 약함)."""
    out, prev = [], None
    for c in cells:
        if c.get("kind") == "na":
            continue
        d = int(c["dir"])
        if prev is not None and d != prev and int(c["t"]) >= int(t_from):
            weak, tired = c["kind"].endswith(" weak"), c["kind"].endswith(" tired")
            adx, adx_prev = _f(c.get("adx")), _f(c.get("adx_prev"))
            parts = [f"상승 {c['up']}·하락 {c['dn']}·중립 {4 - c['up'] - c['dn']}"]
            if adx is not None:
                parts.append(f"ADX {adx:.0f}" + ("" if adx_prev is None else " 오름" if adx > adx_prev else " 내림"))
            if d == 0 and int(c.get("raw") or 0):
                parts.append(f"{DIR_KO[int(c['raw'])]} 유지 확인 중")
            if tired:
                parts.append("끝물이라 진입은 안 받아요")
            elif weak:
                parts.append(f"힘 약함(ADX {adx_min:g} 미만)이라 진입은 안 받아요")
            parts.append(f"{TF_KO[LTC.ENTRY_OF[tf]]} 진입이 이 판단을 봐요")
            out.append(_ev(f"j:{sym}:{tf}:{c['t']}", c["t"], "trend", "change",
                           f"{coin(sym)} {TF_KO[tf]} 판단이 {FROM_KO[prev]} {TO_KO[d]} 바뀌었어요", " · ".join(parts),
                           symbol=sym, tone={1: "up", -1: "down"}.get(d, "hold"), link=_link("tchart", sym=sym),
                           tf=tf, frm=prev, to=d, raw=int(c.get("raw") or 0), up=c["up"], dn=c["dn"], adx=adx,
                           weak=weak, tired=tired))
        prev = d
    return out


def judgments(st: dict, cfg: dict, now: int, t_from: int, b=None) -> tuple:
    """(events, info): every coin's 1h, 4h and 1d judgment changes from ``t_from`` on, recomputed by the 추세 차트 tab's
    ``history`` over its own bars and cache (livetrendchart.bars(): closed bars through the trend bot's Klines, at most
    FETCH_PER_BUILD fetches an answer, none until a new bar closes)."""
    rules, _src = LTC.rules_of(st, cfg)
    b = b or LTC.bars()
    budget = [LTC.FETCH_PER_BUILD]
    events, errors = [], []
    read = pending = 0
    stale = False
    with b.lock:
        for sym in COINS:
            for tf in LTC.TFS:
                df, info = b.frame(sym, tf, now, budget)
                if df is None:
                    if info["state"] == "pending":
                        pending += 1
                    else:
                        errors.append({"symbol": sym, "tf": tf, "reason_ko": info.get("reason_ko")})
                    continue
                read += 1
                stale = stale or bool(info.get("stale"))
                events += changes_of(sym, tf, LTC.cells_of(b.history(sym, tf, df, rules), t_from, tf), t_from, rules.adx_min)
    of = len(COINS) * len(LTC.TFS)
    state = "ok" if read == of else "pending" if pending and not errors else "error" if not read else "partial"
    return events, {"state": state, "read": read, "of": of, "pending": pending > 0, "errors": errors, "stale": stale}


# ================================================================ signals (signal_log + the account's outcomes)
def _pull_entry(bc: int, tf: str, status: str, why: str) -> bool:
    """The entry row of a pullback (trendbot._pullbacks: SUBMITTED "되돌림 확인" at the minute after the touch, inside the
    entry bar, never on a bar close; restated FILTERED when a pause began meanwhile): counted with its signal."""
    ms = TF_MS.get(tf)
    return (status == "SUBMITTED" and why == "되돌림 확인") or (ms is not None and int(bc) % ms != 0)


def _skip_ko(reason: str) -> str:
    """The engine's reason a signal was not entered, in the ⏳ message's words (livecheck.WAIT_SKIP_KO)."""
    r = str(reason or "")
    return next((ko for head, ko in LC.WAIT_SKIP_KO if r.startswith(head)), r[:60] or "이유 기록 없음")


def _outcome_line(o: Optional[tuple], pulled: bool) -> tuple:
    """(sub, words, tone) of an entry signal's outcome (status, reason, step) for the account."""
    head = "되돌림 옴 → " if pulled else ""
    if o is None:
        return "wait", (head + "진입 확인 중") if pulled else "처리 전 (결과 기록 전)", "accent"
    status, reason, step = o
    if status == "ENTERED":
        return "entered", f"{head}{kst(step)} 진입", "good"
    if str(reason or "") == "in position":
        return "one", ("되돌림은 왔지만 " if pulled else "") + "한 포지션이라 못 탐", "warn"
    return "skip", ("되돌림은 왔지만 " if pulled else "") + f"진입 안 함: {_skip_ko(reason)}", "warn"


def signal_events(rows: list, outs: dict, now: int) -> tuple:
    """(events, counts) of the signal_log rows (newest first: id, bar_close, timeframe, member, symbol, side, status,
    data) with the account's outcomes ``outs`` {(signal ts + 1, timeframe, member, symbol): (status, reason, step)}:
    one row per signal at its bar close with what became of it."""
    pulls: dict = {}
    for _id, bc, tf, member, sym, _side, status, data in rows:
        if _pull_entry(bc, tf, status, L._j(data).get("why")):
            pulls.setdefault((member, sym, tf), []).append((int(bc), status, L._j(data).get("why")))
    events = []
    n = passed = waited = touched = waiting = 0
    for rid, bc, tf, member, sym, side, status, data in rows:
        d = L._j(data)
        why = str(d.get("why") or "")
        if _pull_entry(bc, tf, status, why):
            continue
        n += 1
        bc, side = int(bc), int(side or 0)
        tr = d.get("trend") if isinstance(d.get("trend"), dict) else {}
        level = _f(tr.get("level"))
        ms = TF_MS.get(tf, HOUR)
        extra = {"tf": tf, "member": member, "strategy": d.get("strategy") or str(member).split("@")[0], "status": status,
                 "price": _f(d.get("ref_price")), "level": level, "judge": _judge_text(tr)}
        detail = L.why_words(why) if why else None
        if status == "FILTERED":
            cat, ko = L.why_cat(status, why)
            extra["cat"] = cat
            if cat in BLOCK_KO:
                # the pause from 30 minutes before the open too (owners 10-21 night): its own words
                sub, words, tone = "blocked", BLOCK_KO["usopen_pre" if cat == "usopen" and "개장 앞" in why else cat], "thin"
            elif cat == "trend":
                sub, words, tone = "judge", "추세 판단에 걸림", "thin"
            elif cat == "spot":
                sub, words, tone = "check", "점검 탈락", "thin"
            elif cat == "nopull":
                passed += 1
                waited += 1
                sub, words, tone = "nopull", "되돌림 안 옴 · 진입 없음", "thin"
            else:
                sub, words, tone = "other", f"진입 안 함: {ko}", "thin"
        elif status == "WAITING":
            passed += 1
            waited += 1
            pull = why.startswith(LC.PULLBACK_HEAD)          # (a break wait is the bots' before the trend bot's)
            until = bc + ms - (MIN if pull else 0)
            extra["until"] = until
            if until > now:
                waiting += 1
                sub, words, tone = "wait", "점검 통과 · 되돌림 기다리는 중" if pull else "돌파 기다리는 중", "accent"
                if pull:
                    lv = f"{price_ko(level)}까지 {'내려오면' if side > 0 else '올라오면'} 진입" if level is not None else "되돌림 가격 못 읽음"
                    detail = f"{lv} · {kst(until)}까지 안 오면 진입 없음"
            else:
                sub, words, tone = "wait", f"{'되돌림' if pull else '돌파'} 기다림 · 결과 기록 전", "thin"
        elif status == "BROKE":
            passed += 1
            waited += 1
            touched += 1
            mine = sorted(x for x in pulls.get((member, sym, tf), []) if bc < x[0] < bc + ms)
            if mine and mine[0][1] == "FILTERED":
                cat, ko = L.why_cat("FILTERED", mine[0][2])
                sub, words, tone = "skip", f"되돌림은 왔지만 진입 안 함: {BLOCK_KO.get(cat, ko)}", "warn"
            else:
                o = outs.get((mine[0][0], tf, member, sym)) if mine else None
                sub, words, tone = _outcome_line(o, True)
                if mine:
                    extra["entry_t"] = mine[0][0]
        elif status == "SUBMITTED":
            sub, words, tone = _outcome_line(outs.get((bc, tf, member, sym)), False)
            if why.startswith(LT.PASSED_NOW):                # 바로 진입 (owners 10-22): passed, entered at its own minute
                passed += 1
                extra["held"] = LT.held_of(tr)
                words = "점검 통과" + (" (보류 진입)" if extra["held"] else "") + (" → " + words if sub != "wait" else " · 바로 진입 중")
        else:
            sub, words, tone = "other", str(status), "thin"
        events.append(_ev(f"s:{rid}", bc, "signal", sub, f"{coin(sym)} {SIDE_KO.get(side, '')} 신호 · {words}", detail,
                          symbol=sym, side=side, tone=tone, link=_link("signals"), **extra))
    return events, {"signals": n, "passed": passed, "waits": waited, "touched": touched, "waiting": waiting}


# ================================================================ the paper account's trades
def trade_events(trades: list, positions: dict, entered: dict, t0: int, since: Optional[int] = None) -> tuple:
    """(events, counts) of the paper trades (TradeRecord fields + ``_id``, ``_acct``) and the open positions
    {account: Position dict} from ``t0`` on: entries, exits, supervisor exits; ``entered`` {(symbol, entry ms): the
    ENTERED outcome's signal meta} says whether an entry came after a pullback. The twin's rows carry ``twin`` and are
    left out of the counts. A trade or position entered before ``since`` (the trend bot's start) is the bot before it's:
    ``prev`` on its rows, counted apart (``prev_entered``, ``prev_closed``)."""
    events = []
    n_in = n_out = p_in = p_out = 0
    pnl = 0.0
    is_prev = lambda et: bool(since) and et is not None and int(et) < int(since)  # noqa: E731
    for t in trades:
        acct, tid = t["_acct"], t["_id"]
        twin = acct == FLIP
        sym, side = t.get("symbol"), int(t.get("side") or 0)
        who = "동전 쌍둥이 " if twin else ""
        base = {"symbol": sym, "side": side, "acct": "flip" if twin else "paper", "twin": twin, "trade_id": tid,
                "tf": t.get("timeframe"), "strategy": t.get("strategy_id"), "leverage": _i(t.get("leverage"))}
        link = None if twin else _link("replay", id=tid)
        et, xt = _i(t.get("entry_time")), _i(t.get("exit_time"))
        prev = is_prev(et)
        base["prev"] = prev
        if et is not None and et >= t0:
            if prev:
                p_in += 0 if twin else 1
            else:
                n_in += 0 if twin else 1
            meta = {} if twin else entered.get((sym, et)) or {}
            events.append(_ev(f"t:{acct}:{tid}:e", et, "trade", "entry",
                              f"{who}{coin(sym)} {SIDE_KO.get(side, '')} 진입 · {t.get('leverage')}배 @ {price_ko(t.get('entry_price'))}",
                              _entry_detail(meta, (t.get("context") or {}).get("trend") if isinstance(t.get("context"), dict) else None, twin),
                              tone="accent", link=link, price=_f(t.get("entry_price")), **base))
        if xt is None or xt < t0:
            continue
        reason = t.get("exit_reason")
        ctx = t.get("context") if isinstance(t.get("context"), dict) else {}
        sup = reason in SUP
        if not twin and prev:
            p_out += 1
        elif not twin:
            n_out += 1
            pnl += _f(t.get("pnl")) or 0.0
        words = LC.KO_EXIT.get(reason, L.EXIT_KO.get(reason, str(reason)))
        parts = [f"진입 {price_ko(t.get('entry_price'))} → 청산 {price_ko(t.get('exit_price'))}"]
        if ctx.get("exit_why"):
            parts.insert(0, str(ctx["exit_why"]))
        lock = _f(t.get("lock_roe"))
        if lock is not None:
            parts.append(f"잠금 {pct_ko(lock, 0)}까지 감")
        events.append(_ev(f"t:{acct}:{tid}:x", xt, "trade", "sup" if sup else "exit",
                          f"{who}{coin(sym)} {SIDE_KO.get(side, '')} {words} · 순ROE {pct_ko(t.get('roe'))} · {money_ko(t.get('pnl'))}",
                          " · ".join(parts), tone="up" if (_f(t.get("pnl")) or 0) > 0 else "down" if (_f(t.get("pnl")) or 0) < 0 else "",
                          link=link, reason=reason, roe=_f(t.get("roe")), pnl=_f(t.get("pnl")), price=_f(t.get("exit_price")),
                          hold_ms=(xt - et) if et is not None else None, **base))
    for acct, p in positions.items():
        if not isinstance(p, dict):
            continue
        et = _i(p.get("entry_time"))
        if et is None or et < t0:
            continue
        twin = acct == FLIP
        prev = is_prev(et)
        if prev:
            p_in += 0 if twin else 1
        else:
            n_in += 0 if twin else 1
        sig = p.get("signal") if isinstance(p.get("signal"), dict) else {}
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        sym, side = p.get("symbol"), int(p.get("side") or 0)
        lock = _f(p.get("lock_roe"))
        detail = _entry_detail(meta, meta.get("trend") if isinstance(meta.get("trend"), dict) else None, twin)
        detail = " · ".join(x for x in (detail, "지금 열려 있어요" + (f" · 잠금 {pct_ko(lock, 0)}" if lock is not None else ""),
                                        "새 봇이 이어서 정리해요" if prev else None) if x)
        events.append(_ev(f"t:{acct}:open:{et}", et, "trade", "entry",
                          f"{'동전 쌍둥이 ' if twin else ''}{coin(sym)} {SIDE_KO.get(side, '')} 진입 · {p.get('leverage')}배 @ {price_ko(p.get('entry_price'))}",
                          detail, symbol=sym, side=side, tone="accent", link=None if twin else _link("pos"),
                          acct="flip" if twin else "paper", twin=twin, open=True, prev=prev, tf=sig.get("timeframe"),
                          strategy=sig.get("strategy_id"), leverage=_i(p.get("leverage")), price=_f(p.get("entry_price"))))
    return events, {"entered": n_in, "closed": n_out, "pnl": pnl, "prev_entered": p_in, "prev_closed": p_out}


def _entry_detail(meta: dict, trend: Optional[dict], twin: bool) -> Optional[str]:
    """How an entry came about: a pullback (its level), on a 보류 judgment (10-22 보류 허용), the judgment it entered on;
    the twin's: what it is (its side is a coin's, so neither the pullback nor the judgment is its own)."""
    if twin:
        return "비교용 · 같은 때 같은 코인, 방향만 동전"
    parts = []
    if meta.get("pulled"):
        lv = _f(meta.get("pull_level"))
        parts.append("되돌림 진입" + (f" ({price_ko(lv)} 닿음)" if lv is not None else ""))
    tr_meta = meta.get("trend") if isinstance(meta.get("trend"), dict) else {}
    if LT.held_of(tr_meta if "held" in tr_meta else trend or tr_meta):
        parts.append(LT.HELD_KO)
    j = _judge_text(trend or {}) or _judge_text(tr_meta)
    if j:
        parts.append(j)
    return " · ".join(parts) or None


# ================================================================ the paper database (one snapshot)
def read_paper(path: str, t0: int, now: int) -> dict:
    """The paper database in one snapshot: the bot (its start record, the trend state), the trades and open positions
    of both accounts in the span, the trend bot's signals and the account's outcomes, the warnings, the starts."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return {"state": "missing", "reason_ko": L.MISSING_KO, "path": path}
    except (OSError, sqlite3.Error) as exc:
        return {**L._err(path, exc), "state": "error"}
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "state" not in tables:
            return {"state": "missing", "reason_ko": L.NO_TABLE_KO, "path": path}
        run_ts, run = LT._state(conn, "combo_run")
        cfg = (run or {}).get("config") if isinstance(run, dict) else None
        cfg = cfg if isinstance(cfg, dict) else {}
        trend_on = cfg.get("trend") is not None
        st_ts, st = LT._state(conn, "trend")
        _ts, combo = LT._state(conn, "combo")
        _ts, acc = LT._state(conn, "accounts")
        since = (_i((combo or {}).get("trend_since")) or _i((st or {}).get("since")) or run_ts) if trend_on else None
        trades = []
        if "trades" in tables:
            for tid, acct, data in conn.execute(
                    "SELECT id, account_id, data FROM trades WHERE account_id IN (?, ?) AND exit_time >= ? "
                    "ORDER BY exit_time DESC, id DESC LIMIT ?", (ACCOUNT, FLIP, int(t0), TRADES_SCAN)):
                t = L._j(data)
                if t:
                    trades.append({**t, "_id": int(tid), "_acct": acct})
        engines = ((acc or {}).get("engines") or {}) if isinstance(acc, dict) else {}
        positions = {a: (engines.get(a) or {}).get("position") for a in (ACCOUNT, FLIP) if isinstance(engines.get(a), dict)}
        sig_from = max(int(t0), int(since or 0))
        rows, outs, entered = None, {}, {}
        if trend_on and "signal_log" in tables:
            rows = conn.execute("SELECT id, bar_close, timeframe, strategy, symbol, side, status, data FROM signal_log "
                                "WHERE bar_close >= ? ORDER BY bar_close DESC, id DESC LIMIT ?", (sig_from, SIG_SCAN)).fetchall()
        if "outcomes" in tables:
            for step, status, reason, sym, data in conn.execute(
                    "SELECT step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? AND step_ts >= ? ORDER BY id",
                    (ACCOUNT, int(t0) - HOUR)):
                d = L._j(data)
                sig = d.get("signal") if isinstance(d.get("signal"), dict) else {}
                meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
                ts = _i(sig.get("ts"))
                if ts is not None:
                    outs[(ts + 1, sig.get("timeframe"), meta.get("member") or sig.get("strategy_id"), sym)] = (status, reason, _i(step))
                if status == "ENTERED":
                    entered[(sym, _i(step))] = meta
        alerts = []
        if "alerts" in tables:
            alerts = [(int(ts), lv, txt) for ts, lv, txt in conn.execute(
                "SELECT ts, level, text FROM alerts ORDER BY rowid DESC LIMIT ?", (ALERTS_SCAN,))
                if ts is not None and int(ts) >= int(t0) and lv in ("WARN", "CRITICAL")]
        runs = []
        if "runs" in tables:
            runs = [(int(ts), L._j(d)) for ts, d in conn.execute(
                "SELECT started_ts, data FROM runs WHERE started_ts >= ? ORDER BY id DESC LIMIT 20", (int(t0),))]
    except sqlite3.Error as exc:
        return {**L._err(path, exc), "state": "error"}
    finally:
        conn.close()
    return {"state": "ok", "path": path, "cfg": cfg, "name": cfg.get("name"), "trend_on": trend_on, "trend": st,
            "trend_ts": st_ts, "since": since, "run_ts": run_ts, "trades": trades, "positions": positions, "rows": rows,
            "sig_from": sig_from, "sig_capped": rows is not None and len(rows) >= SIG_SCAN, "outs": outs, "entered": entered,
            "alerts": alerts[:ALERTS_KEEP], "runs": runs}


def safety_events(pr: dict, t0: int) -> list:
    """The paper bot's starts and warnings."""
    out = []
    if pr.get("state") != "ok":
        return out
    name = pr.get("name") or "페이퍼 봇"
    seen = []
    for ts, d in pr.get("runs") or []:
        seen.append(ts)
        ver = d.get("commit") if isinstance(d, dict) else None
        out.append(_ev(f"run:{ts}", ts, "safety", "start", f"페이퍼 봇이 켜졌어요 ({name})",
                       f"코드 {str(ver)[:8]}" if ver else None, tone="accent", link=_link("health")))
    rt = pr.get("run_ts")
    if rt is not None and rt >= t0 and not any(abs(rt - s) < 2 * MIN for s in seen):
        out.append(_ev(f"run:{rt}", rt, "safety", "start", f"페이퍼 봇이 켜졌어요 ({name})", "마지막으로 켜진 때 (그 전 시작은 기록에 없어요)",
                       tone="accent", link=_link("health")))
    since = pr.get("since")
    if pr.get("trend_on") and since is not None and since >= t0:
        out.append(_ev(f"since:{since}", since, "safety", "trend_start", "추세판단 봇이 처음 켜졌어요 · 규칙 고정 2주 시작",
                       f"{kst_dt(since + LT.FREEZE_DAYS * DAY)}(한국 시간)에 2주가 끝나요 · 그때 검토", tone="accent", link=_link("review")))
    for i, (ts, lv, txt) in enumerate(pr.get("alerts") or []):
        out.append(_ev(f"al:{ts}:{i}", ts, "safety", "alert", f"페이퍼 봇 {'긴급' if lv == 'CRITICAL' else '경고'}", txt,
                       tone="bad" if lv == "CRITICAL" else "warn", link=_link("health"), level=lv))
    return out


# ================================================================ the executors (their own databases, livebots.sources)
def exec_steps(path: str, t0: int) -> tuple:
    """(rows, problem) of an executor's lock-step and SIGTERM records in the span (INFO: not in livebots.read_exec's
    WARN / CRITICAL list): [(id, ts, kind, text)] newest first."""
    try:
        conn = L.open_ro(path)
    except (OSError, sqlite3.Error) as exc:
        return [], L.reason_ko(exc, path)
    try:
        rows = conn.execute("SELECT id, ts, kind, text FROM events WHERE kind IN ('stop', 'own_lock', 'sigterm') AND ts >= ? "
                            "ORDER BY id DESC LIMIT ?", (int(t0), EXEC_SCAN)).fetchall()
        return [(int(i), int(ts), k, txt) for i, ts, k, txt in rows], None
    except sqlite3.Error as exc:
        return [], L.reason_ko(exc, path)
    finally:
        conn.close()


def _gap_words(gap: Optional[float], lev, what: str, none_ko: str = "짝 거래 없음") -> str:
    """The fill against the paper's price, in the trade's favour positive: '페이퍼 진입가보다 0.016% 불리, 순ROE −0.6%p'."""
    if gap is None:
        return f"페이퍼 {what}가와 견줄 수 없어요 ({none_ko})"
    if abs(gap) < 5e-6:
        return f"페이퍼 {what}가와 같아요"
    roe = f", 순ROE {pct_ko(gap * float(lev), 1)}p" if _f(lev) else ""
    return f"페이퍼 {what}가보다 {pct_ko(abs(gap), 3, False)} {'유리' if gap > 0 else '불리'}{roe}"


def exec_events(execs: list, paper_by: dict, t0: int) -> tuple:
    """(events, sources) of the executors (livebots.sources' entries): fills with the gap to the paper's price, lock steps,
    skipped follows, halts and warnings, starts. ``paper_by`` {(symbol, entry ms): side} of the paper's entries (the
    side of a skipped follow)."""
    events, srcs = [], []
    for x in execs:
        ex, name, r = x["id"], x["name_ko"], x["record"]
        if r.get("state") != "ok":
            srcs.append({"id": ex, "name_ko": name, "state": r.get("state"), "reason_ko": r.get("reason_ko"), "reason": r.get("reason")})
            continue
        real = r.get("mode") == "mainnet"
        srcs.append({"id": ex, "name_ko": name, "state": "ok", "real": real, "mode": r.get("mode")})
        pairs = L.pairs_of(x)
        tag = {"acct": ex, "ex_ko": name, "real": real}
        for t in r.get("trades") or []:
            sym, side, lev = t.get("symbol"), int(t.get("side") or 0), t.get("leverage")
            pt = pairs.get(str(t.get("key")))
            et, xt = _i(t.get("entry_ts")), _i(t.get("exit_ts"))
            if et is not None and et >= t0:
                pe = t.get("paper_entry") or (pt or {}).get("entry_price")
                gap = side * (pe - t["entry_price"]) / pe if pe and t.get("entry_price") else None
                events.append(_ev(f"x:{ex}:{t['key']}:e", et, "exec", "fill_in",
                                  f"{name} {coin(sym)} {SIDE_KO.get(side, '')} 진입 체결 @ {price_ko(t.get('entry_price'))}",
                                  _gap_words(gap, lev, "진입"), symbol=sym, side=side, tone="accent",
                                  link=_link("trades", acct=ex), gap=gap, leverage=_i(lev), **tag))
            if xt is not None and xt >= t0:
                reason = t.get("exit_reason")
                if reason == "PAPER" and pt:
                    reason = pt.get("exit_reason") or reason
                # the exit against the paper's, when it followed the paper's close (within MATCH_MS of it): an own
                # exchange stop or lock later or earlier is no fill gap (livebots.fill_gaps' own_exit)
                gap, none_ko = None, "짝 거래 없음"
                if pt:
                    if not t.get("exit_ref") or not pt.get("exit_price"):
                        none_ko = "청산 기준가 기록 없음"
                    elif pt.get("exit_time") is None or abs(int(pt["exit_time"]) - xt) > L.MATCH_MS:
                        none_ko = "페이퍼와 다른 때 닫음"
                    else:
                        gap = side * (t["exit_ref"] - pt["exit_price"]) / pt["exit_price"]
                pnl = _f(t.get("pnl"))
                words = L.EXIT_KO.get(reason, str(reason or "청산"))
                detail = [_gap_words(gap, lev, "청산", none_ko)]
                if t.get("est"):
                    detail.append("손익은 지갑 변화로 어림 (체결 기록 전)")
                events.append(_ev(f"x:{ex}:{t['key']}:x", xt, "exec", "fill_out",
                                  f"{name} {coin(sym)} {SIDE_KO.get(side, '')} 청산 · {words} · {money_ko(pnl)}",
                                  " · ".join(detail), symbol=sym, side=side,
                                  tone="up" if (pnl or 0) > 0 else "down" if (pnl or 0) < 0 else "",
                                  link=_link("trades", acct=ex), gap=gap, pnl=pnl, reason=reason, est=bool(t.get("est")), **tag))
        q = r.get("position")
        if q and q.get("entry_time") is not None and int(q["entry_time"]) >= t0:
            sym, side = q.get("symbol"), int(q.get("side") or 0)
            pe = q.get("paper_entry")
            gap = side * (pe - q["entry"]) / pe if pe and q.get("entry") else None
            events.append(_ev(f"x:{ex}:{q.get('key')}:e", q["entry_time"], "exec", "fill_in",
                              f"{name} {coin(sym)} {SIDE_KO.get(side, '')} 진입 체결 @ {price_ko(q.get('entry'))}",
                              _gap_words(gap, q.get("leverage"), "진입") + " · 지금 열려 있어요", symbol=sym, side=side,
                              tone="accent", link=_link("pos"), gap=gap, leverage=_i(q.get("leverage")), open=True, **tag))
        # the paper entries it did not follow: the strongest recorded reason per entry (livebots.why_missed's order)
        for key, kinds in (r.get("why") or {}).items():
            got = next(((k, kinds[k]) for k, _ko in L.WHY if k in kinds), None)
            pk = L.parse_key(key)
            if got is None or pk is None or (got[1].get("ts") or 0) < t0:
                continue
            kind, rec = got
            side = paper_by.get((pk[1], pk[2]))
            events.append(_ev(f"x:{ex}:skip:{key}", rec["ts"], "exec", "skip",
                              f"{name} · {coin(pk[1])}{' ' + SIDE_KO[side] if side in SIDE_KO else ''} 페이퍼 진입을 안 따라갔어요",
                              f"{L.WHY_KO[kind]} · {rec.get('text') or ''}".rstrip(" ·"), symbol=pk[1], side=side, tone="warn",
                              link=_link("cost"), why=kind, **tag))
        for e in r.get("events") or []:
            ts = e.get("ts")
            if ts is None or ts < t0 or e.get("kind") in L.WHY_KO or e.get("kind") in ("entry", "exit"):
                continue
            k = e["kind"]
            crit = e.get("level") == "CRITICAL"
            if k == "halt":
                text = f"{name} 멈춤 · 사람이 풀 때까지 새 진입 없음"
            elif k == "halted":
                text = f"{name} 멈춘 채로 켜졌어요"
            elif k == "halt_cleared":
                text = f"{name} 멈춤이 풀렸어요"
            else:
                text = f"{name} {e.get('level_ko') or ''} · {e.get('kind_ko') or k}"
            events.append(_ev(f"x:{ex}:ev:{e['id']}", ts, "exec", k if k in ("halt", "halted", "halt_cleared") else "warn",
                              text, e.get("text"), tone="bad" if crit or k == "halt" else "good" if k == "halt_cleared" else "warn",
                              link=_link("safety"), level=e.get("level"), ev_kind=k, **tag))
        steps, problem = exec_steps(r["path"], t0)
        if problem:
            srcs[-1]["steps_ko"] = f"잠금 단계 기록을 못 읽었어요 ({problem})"
        for i, ts, k, txt in steps:
            if k == "sigterm":
                events.append(_ev(f"x:{ex}:ev:{i}", ts, "safety", "stop", f"{name} 실행기가 꺼졌어요 (끄라는 신호)", txt,
                                  tone="warn", link=_link("safety"), **tag))
                continue
            if k == "stop" and "거래소 기준 잠금" in str(txt):
                continue                      # an own-ladder step: the own_lock record of the same step says more
            sym = next((s for s in COINS if str(txt).startswith(s)), None)
            events.append(_ev(f"x:{ex}:ev:{i}", ts, "exec", "lock", f"{name} {coin(sym) + ' ' if sym else ''}손절 옮김 (잠금 단계)",
                              txt, symbol=sym, tone="good", link=_link("trades", acct=ex), **tag))
        for ts, pdb in r.get("starts") or []:
            if ts is not None and ts >= t0:
                events.append(_ev(f"x:{ex}:start:{ts}", ts, "safety", "start", f"{name} 실행기가 켜졌어요",
                                  f"따라가는 페이퍼 DB {pdb}" if pdb else None, tone="accent", link=_link("safety"), **tag))
    return events, srcs


def check_events(checks: dict, t0: int) -> list:
    """The morning checks and the watcher's alarms of the span (livebots.read_checks' items)."""
    out = []
    m = checks.get("morning") or {}
    for it in (m.get("items") or []) if m.get("state") == "ok" else []:
        ts = it.get("ts")
        if it.get("state") != "ok" or ts is None or ts < t0:
            continue
        loud = it.get("loud_n") or 0
        tail = " · ".join(str(it.get("head") or "").split(" · ")[1:]) or "이상 없음"
        out.append(_ev(f"am:{it['day']}", ts, "safety", "morning",
                       f"아침 점검 · {'확인할 것 ' + str(loud) + '개' if loud or it.get('level') == 'CRITICAL' else tail}",
                       " · ".join(it.get("reasons") or []) or None, tone="bad" if loud else "good" if tail == "이상 없음" else "warn",
                       link=_link("safety"), level=it.get("level")))
    w = checks.get("watch") or {}
    for f in (w.get("items") or []) if w.get("state") == "ok" else []:
        ts = f.get("ts")
        if ts is None or ts < t0:
            continue
        state = {"active": "아직 켜져 있음", "cleared": f"{kst_dt(f['cleared_ts'])}에 풀림" if f.get("cleared_ts") else "풀림",
                 "once": "한 번만 알림", "unsent": "보내지 못함"}.get(f.get("state"), "")
        out.append(_ev(f"wa:{f.get('key')}:{ts}", ts, "safety", "alarm", f"감시 알람 · {f.get('kind_ko') or f.get('kind')}",
                       " · ".join(x for x in (f.get("title"), state) if x) or None,
                       tone="bad" if f.get("level") == "CRITICAL" else "warn", link=_link("safety"), level=f.get("level"),
                       state=f.get("state"), cleared_ts=f.get("cleared_ts")))
    return out


# ================================================================ the answer
def _order(e: dict) -> tuple:
    return -e["t"], ORDER.get(e["kind"], 9), e["id"]


def cap(events: list, n: int) -> tuple:
    """(kept, newest first; capped or None): over ``n`` rows the signals and judgment changes (LOW) are cut first,
    oldest first; the other rows only when they alone are more than ``n`` (oldest first too). ``capped``: how many there
    were, kept and cut, the oldest signal / judgment row kept (``low_from``, None when none is left) and the oldest
    other row kept once some of them were cut (``hi_from``)."""
    events = sorted(events, key=_order)
    if len(events) <= n:
        return events, None
    hi_all = [e for e in events if e["kind"] not in LOW]
    hi = hi_all[:n]
    low = [e for e in events if e["kind"] in LOW][:n - len(hi)]
    kept = sorted(hi + low, key=_order)
    return kept, {"total": len(events), "kept": len(kept), "cut": len(events) - len(kept), "kinds": list(LOW),
                  "low_from": low[-1]["t"] if low else None, "hi_from": hi[-1]["t"] if len(hi_all) > n else None}


def build(p: dict, hours: int = 24, now_ms: Optional[int] = None, more: Optional[dict] = None, b=None) -> dict:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    hours = int(hours) if int(hours) in HOURS else HOURS[0]
    t0 = now - hours * HOUR
    more = more or L.paths_more()
    pr = read_paper(p["paper"], t0, now)
    events, notes = [], []
    counts = {k: None for k in ("signals", "passed", "waits", "touched", "waiting", "entered", "closed", "pnl", "changes")}
    judge = {"state": "off", "covers_h": JUDGE_H, "from": None, "read": 0, "of": len(COINS) * len(LTC.TFS), "pending": False,
             "note_ko": None, "errors": []}
    state, reason_ko = pr["state"], pr.get("reason_ko")
    if pr["state"] == "ok":
        tev, tc = trade_events(pr["trades"], pr["positions"], pr["entered"], t0, pr["since"])
        events += tev
        counts.update(tc)
        if tc["prev_entered"] or tc["prev_closed"]:
            notes.append(f"{PREV_KO}: 진입 {tc['prev_entered']}번 · 청산 {tc['prev_closed']}번은 '전환 전'으로 따로 표시해요 "
                         "(위 진입·청산 숫자에 안 셈)")
        events += safety_events(pr, t0)
        if not pr["trend_on"]:
            state, reason_ko = "off", OFF_KO
            judge["reason_ko"] = "추세판단 봇이 아니라 판단 기록이 없어요"
        else:
            if pr["rows"] is not None:
                sev, sc = signal_events(pr["rows"], pr["outs"], now)
                events += sev
                counts.update(sc)
                if pr["sig_capped"]:
                    notes.append(f"신호가 많아 최근 {SIG_SCAN}개만 읽었어요")
            if pr["since"] and pr["since"] > t0:
                notes.append(f"{SINCE_KO} (추세판단 봇 시작 {kst_dt(pr['since'])})")
            if pr["trend"] is None:
                state, reason_ko = "missing", "추세판단 봇이 아직 첫 판단을 기록하지 않았어요 (켠 뒤 1~2분)"
                judge.update(state="missing", reason_ko=reason_ko)
            else:
                t_from = max(t0, now - JUDGE_H * HOUR)
                jev, info = judgments(pr["trend"], pr["cfg"], now, t_from, b)
                events += jev
                judge.update(info, **{"from": t_from, "note_ko": JUDGE_NOTE_KO if hours > JUDGE_H else None})
                if info["read"]:
                    counts["changes"] = len(jev)
    paper_by: dict = {}
    for t in pr.get("trades") or []:
        if t.get("_acct") == ACCOUNT and _i(t.get("entry_time")) is not None:
            paper_by[(t.get("symbol"), int(t["entry_time"]))] = int(t.get("side") or 0)
    pos = (pr.get("positions") or {}).get(ACCOUNT)
    if isinstance(pos, dict) and _i(pos.get("entry_time")) is not None:
        paper_by[(pos.get("symbol"), int(pos["entry_time"]))] = int(pos.get("side") or 0)
    _configs, _follows, _paper, execs = L.sources(p, now)
    xev, xsrc = exec_events(execs, paper_by, t0)
    events += xev
    checks = L.read_checks(more["check_db"], now)
    events += check_events(checks, t0)
    kept, capped = cap(events, MAX_EVENTS)
    present = sorted({e["symbol"] for e in kept if e.get("symbol") in COINS}, key=COINS.index)
    return {"state": state, "reason_ko": reason_ko, "reason": pr.get("reason"), "now_ms": now, "hours": hours, "t0": t0,
            "hours_all": list(HOURS), "name": pr.get("name"), "since": pr.get("since"), "events": kept, "capped": capped,
            "counts": counts, "judge": judge, "notes": notes, "coins": present, "kinds": [{"id": k, "ko": ko} for k, ko in KINDS],
            # the running config waits for a pullback (trend.pullback_wait; the owners' since 10-22 enters at once)
            "pullback_wait": L.trend_waits(pr.get("cfg")) if pr.get("trend_on") else None,
            "sources": {"paper": {k: pr.get(k) for k in ("state", "reason_ko", "reason", "path")}, "execs": xsrc,
                        "checks": {k: checks.get(k) for k in ("state", "reason_ko", "reason", "path")}}}


def register(app, ctx) -> dict:
    from fastapi import HTTPException

    from ..app import json_finite

    @app.get("/api/v4/livebots/journal")
    def get_livebots_journal(hours: int = 24):
        """실거래 › 일지: everything the trend bot and the executors did in the last 24 h / 3 days / 7 days, newest first
        (5 s cache per span)."""
        if hours not in HOURS:
            raise HTTPException(400, "hours: 24, 72 or 168")
        p, more = L.paths(), L.paths_more()
        return L._cached(f"journal:{hours}:" + json.dumps([p, more], sort_keys=True),
                         lambda: json_finite(build(p, hours, more=more)))

    return {"routes": ["/api/v4/livebots/journal"]}
