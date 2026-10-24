"""실거래 › 포지션 (the 실거래 site's #/pos, screens/livebots-pos.js; owners 10/19 "포지션 진입하고 최대 %까지 갔는지 최대
-%까지 갔는지도 … 진입가 익절가 손절가도 보였으면") and the 최대 +% / 최대 −% of the 거래 tab. Read-only.

    GET /api/v4/livebots/positions              the open position of each of the four accounts (페이퍼 COMBO@mix, 바이비트,
                                                MEXC, 동전 쌍둥이 COMBOFLIP@mix) as one card's numbers, or none (5 s cache)
    GET /api/v4/livebots/positions/excursions   최대 +% (MFE) and 최대 −% (MAE) of the closed trades the 거래 tab lists, keyed
                                                by that tab's own row keys ("paper:<id>", the executors' trade keys; 5 s cache,
                                                a finished trade's numbers kept)

A card (``card``): the strategy (its setting in the config the bot runs, ``group`` A or B: B = a "no_chase" member), coin,
side, leverage, margin, entry time, 진입가; 손절가 = the stop before the first lock (the recorded first stop, and the config's
own net-ROE stop price beside it: ``stop: {"mode": "roe", "roe": 0.5, "net": true}`` = -50 % after fees and slippage of both
sides), the lock price after it; 익절가 = the next ladder step: the price where the best net ROE arms the next lock and the
lock it sets (paperbot/ladder2.py ``ComboLadder.next_after``, either form), and the whole ladder as steps with prices; the
secured profit (the lock as net ROE and money); 최대 +% / 최대 −% since the entry; the liquidation price (the paper's; an
executor does not record one); the fast-stop state (``early_exit`` / ``early_exit_until_lock``); the entry gap between the
paper and each executor.

Prices of the ladder are the engine's own (paperbot/ladder.py ``roe_price``): entry x (1 + side x (roe / leverage + round
trip + funding / notional)), the round trip of the paper's run (``combo_run.taker_fee``, config.v3_settings). An executor
follows the paper position it copies (dash/more/livebots.py ``acct_exec``): its stop moves when the paper's lock moves,
to the paper's stop scaled by its own fill (paperbot/executor.py ``_stop_level`` "ratio"), so its 익절가 is the paper's
trigger price and its lock prices are the paper's x (executor entry / paper entry); without such a paper position the
steps are drawn on its own entry and say so. An executor that runs the ladder on its own position (``"ladder_from":
"own"``, owners 10-20 "거래소 기준으로 익절해야지": its trade's ``own`` record) shows ITS lock, ITS next step and ITS ladder from
its own fill and its exchange's costs ("거래소 기준", ``ladder_from`` "exchange", own_exec_card), whether the paper holds that
position or already closed it.

최대 +% / 최대 −% (net ROE, the ladder's definition): the paper's from the engine's own record (``mfe_price`` /
``mae_price`` of the position or the trade: the best / worst 1m bar high or low since the fill); an executor's (and a
paper record without them) from the rule bot's 1m bars (``PAPERBOT_LIVE_RULE_DB`` live_bars, Binance futures) from the
entry minute on, with the executor's own fill price and the paper's costs ("바이낸스 1분봉 기준": the entry minute's bar
may hold prices from before the fill; the exchange's own prices differ a little). Honest states: the rule bot's file not
there = ``missing`` (수집 전), unreadable = ``error`` (못 읽음 + why), no bar in the window = ``none`` (1분봉 없음); never a
made-up zero. Every database is opened read-only (livebots.open_ro: mode=ro, query_only).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Optional

from . import livebots as L
from .livetrend import INHERITED_KO

MIN = 60_000
LADDER_AHEAD = 5                        # steps shown after the next one (the whole ladder never ends: every 5 % again)
LADDER_MAX = 14
FINAL_MAX = 5000                        # finished trades' excursions kept (a closed trade's bars never change)
BARS_KO = "바이낸스 1분봉 기준 (규칙봇 1분봉 · 진입한 1분부터: 그 1분 안의 진입 전 가격이 섞일 수 있어요)"
ENGINE_KO = "엔진 기록 (페이퍼 엔진이 1분봉 고가·저가로 따라간 값: 잠금 계산과 같은 숫자)"
EXEC_LIQ_KO = "실행기 기록에 청산가가 없어요 (거래소 앱에서 확인)"
FLIP_KO = "동전 쌍둥이 (참고): 같은 순간 같은 신호에 방향만 무작위로 들어가는 비교용 페이퍼"
EXEC_COST_KO = "순ROE는 페이퍼 비용(수수료·슬리피지 왕복) 가정, 펀딩 뺌"
EX_KO = {"bybit": "바이비트", "mexc": "MEXC", "binance": "바이낸스", "wooxpro": "WOO X Pro", "deepcoin": "딥코인",
         "flipster": "플립스터"}                         # Flipster: the third slot's exchange of 10-23, still one the executor runs
OWN_KO = "거래소 기준"
OWN_LADDER_KO = "거래소 기준 (owners 10/20): 이 실행기의 체결가 · 이 거래소의 1분봉 고가·저가 · 이 거래소 수수료로 잠가요 (페이퍼 잠금은 안 따라요)"
# the third executor (딥코인) has a card only once it is installed (livebots.installed: sources() reads it then)
CARDS = (("paper", L.ACCOUNT), ("paper2", L.ACCOUNT), ("bybit", None), ("mexc", None), ("deepcoin", None), ("flip", L.FLIP_ACCOUNT))

_lock = threading.Lock()
_final: "OrderedDict[str, dict]" = OrderedDict()


# ---------------------------------------------------------------- the engine's formulas (paperbot/ladder.py)
def net_roe(side: int, entry: Optional[float], price: Optional[float], lev: Optional[float], rt: float, ff: float = 0.0) -> Optional[float]:
    if not entry or not price or not lev or not side:
        return None
    from ...ladder import net_roe as engine_net_roe
    return engine_net_roe(int(side), float(entry), float(price), float(lev), float(rt or 0.0), float(ff or 0.0))


def roe_price(side: int, entry: Optional[float], lev: Optional[float], roe: Optional[float], rt: float, ff: float = 0.0) -> Optional[float]:
    if not entry or not lev or not side or roe is None:
        return None
    from ...ladder import roe_price as engine_roe_price
    return engine_roe_price(int(side), float(entry), float(lev), float(roe), float(rt or 0.0), float(ff or 0.0))


def ladder_of(cfg: dict):
    """paperbot/ladder2.py ComboLadder of the config's ``ladder`` (either form), None without one."""
    from ...ladder2 import ComboLadder
    return ComboLadder.of(cfg.get("ladder") if isinstance(cfg.get("ladder"), dict) else None)


def ladder_steps(spec, lock: Optional[float], best: Optional[float], price_of, lock_price_of) -> list:
    """The ladder from its first step: [{n, at (best net ROE that arms it), lock (the net ROE it locks), price, lock_price,
    state: "done" (locked) | "next" | "later"}]; every step already locked, the next one and LADDER_AHEAD more."""
    if spec is None:
        return []
    out, cur = [], None
    for i in range(1, LADDER_MAX + 1):
        lk, at = spec.next_after(cur)
        done = lock is not None and lk <= lock + 1e-9
        out.append({"n": i, "at": at, "lock": lk, "price": price_of(at), "lock_price": lock_price_of(lk),
                    "state": "done" if done else "later", "reached": best is not None and best >= at - 1e-12})
        cur = lk
        if not done and sum(1 for s in out if s["state"] != "done") > LADDER_AHEAD:
            break
    nxt = next((s for s in out if s["state"] != "done"), None)
    if nxt:
        nxt["state"] = "next"
    return out


def fast_state(cfg: dict, lock: Optional[float], follows: bool = False) -> dict:
    """빠른 손절 (``early_exit``): "armed" (a reverse signal closes it now), "off" (after the first lock: the ladder alone),
    "none" (the config has none); an executor closes when the paper it follows does (``follows``)."""
    ee = cfg.get("early_exit")
    until = cfg.get("early_exit_until_lock") is True
    tail = " (실행기는 페이퍼가 닫을 때 따라 닫아요)" if follows else ""
    if not ee:
        return {"state": "none", "ko": "빠른 손절 없음 (설정에 없어요) · 손절선과 계단 익절만" + tail}
    who = "같은 매매법" if ee == "own" else "아무 매매법"
    if until and lock is not None:
        return {"state": "off", "ko": "꺼짐 · 계단 익절만 (첫 잠금 뒤에는 반대 신호로 닫지 않아요)" + tail}
    return {"state": "armed", "ko": f"빠른 손절 대기: {who} 반대 신호가 나오면 바로 청산" + ("" if until else " (잠금 뒤에도)") + tail,
            "until_lock": until}


def stop_rule(cfg: dict) -> Optional[dict]:
    """The config's stop as numbers: {"roe": 0.5, "net": True} for ``stop: {"mode": "roe", ...}``, None for another rule."""
    st = cfg.get("stop") if isinstance(cfg.get("stop"), dict) else {}
    if st.get("mode") != "roe" or L._f(st.get("roe")) is None:
        return None
    return {"roe": L._f(st.get("roe")), "net": st.get("net") is True}


# ---------------------------------------------------------------- bars (the rule bot's live_bars, read-only)
def open_bars(path: str) -> tuple:
    """(connection or None, state dict): the rule bot's database with its live_bars table, read-only."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return None, L._missing(path, "규칙봇 1분봉 파일이 아직 없어요 (PAPERBOT_LIVE_RULE_DB 경로를 확인해 주세요)")
    except (OSError, sqlite3.Error) as exc:
        return None, L._err(path, exc)
    try:
        if "live_bars" not in L._tables(conn):
            conn.close()
            return None, L._missing(path, "규칙봇 파일은 있지만 1분봉 표(live_bars)가 아직 없어요")
    except sqlite3.Error as exc:
        conn.close()
        return None, L._err(path, exc)
    return conn, {"state": "ok", "path": path}


def bar_range(conn, symbol: str, lo: int, hi: int) -> dict:
    """The highest high and lowest low of ``symbol``'s 1m bars opened in [lo, hi] (minute starts), with their count."""
    r = conn.execute("SELECT MAX(high), MIN(low), COUNT(*), MIN(ts), MAX(ts) FROM live_bars WHERE symbol = ? AND ts >= ? AND ts <= ?",
                     (symbol, int(lo), int(hi))).fetchone()
    n = int(r[2] or 0)
    if not n or L._f(r[0]) is None or L._f(r[1]) is None:
        return {"state": "none", "reason_ko": "이 시간의 1분봉이 규칙봇 기록에 없어요"}
    return {"state": "ok", "high": float(r[0]), "low": float(r[1]), "n": n, "first": L._i(r[3]), "last": L._i(r[4])}


def excursion(side: int, entry: Optional[float], lev: Optional[float], rt: float, ff: float, best_px: Optional[float],
              worst_px: Optional[float], src: str) -> dict:
    """최대 +% / 최대 −% at the best and the worst price since the entry, as net ROE and as the price move."""
    if not (entry and lev and side and best_px and worst_px):
        return {"state": "none", "reason_ko": "진입가나 배수가 기록에 없어요"}
    return {"state": "ok", "src": src, "src_ko": ENGINE_KO if src == "engine" else BARS_KO,
            "mfe": net_roe(side, entry, best_px, lev, rt, ff), "mae": net_roe(side, entry, worst_px, lev, rt, ff),
            "mfe_px": best_px, "mae_px": worst_px, "mfe_move": side * (best_px / entry - 1.0), "mae_move": side * (worst_px / entry - 1.0)}


def from_bars(conn, bars_state: dict, symbol: str, side: int, entry: Optional[float], lev: Optional[float], rt: float, ff: float,
              t0: Optional[int], t1: int) -> dict:
    """최대 +% / 최대 −% from the 1m bars of the entry minute through ``t1`` (both minute starts included)."""
    if conn is None:
        return {k: bars_state.get(k) for k in ("state", "reason_ko", "reason", "path")}
    if t0 is None:
        return {"state": "none", "reason_ko": "진입 시각이 기록에 없어요"}
    try:
        r = bar_range(conn, symbol, int(t0) - int(t0) % MIN, int(t1) - int(t1) % MIN)
    except sqlite3.Error as exc:
        return L._err(bars_state.get("path") or "", exc)
    if r["state"] != "ok":
        return r
    best, worst = (r["high"], r["low"]) if side > 0 else (r["low"], r["high"])
    out = excursion(side, entry, lev, rt, ff, best, worst, "bars")
    if out["state"] == "ok":
        out.update(bars=r["n"], from_ms=r["first"], to_ms=r["last"])
    return out


# ---------------------------------------------------------------- the paper's own records (state + trades, read-only)
def raw_positions(path: str, accounts: tuple) -> dict:
    """{account: the engine's saved position (paperbot.engine engine_state, asdict(Position))} of live-ac.db, for the fields
    livebots does not pass on (mfe_price, mae_price, margin_initial, entry_fee)."""
    try:
        conn = L.open_ro(path)
    except (OSError, sqlite3.Error):
        return {}
    try:
        if "state" not in L._tables(conn):
            return {}
        r = conn.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    engines = L._j(r[0]).get("engines") if r else None
    engines = engines if isinstance(engines, dict) else {}
    out = {}
    for a in accounts:
        e = engines.get(a)
        if isinstance(e, dict) and isinstance(e.get("position"), dict):
            out[a] = e["position"]
    return out


def paper_trade_extremes(path: str, account: str, keep: int) -> dict:
    """{trade id: {symbol, side, entry_time, exit_time, entry_price, leverage, mfe_price, mae_price, funding, qty}} of the
    account's newest ``keep`` closed trades (the 거래 tab's rows), read-only."""
    try:
        conn = L.open_ro(path)
    except (OSError, sqlite3.Error):
        return {}
    try:
        if "trades" not in L._tables(conn):
            return {}
        rows = conn.execute("SELECT id, symbol, entry_time, exit_time, leverage, data FROM trades WHERE account_id = ? "
                            "ORDER BY exit_time DESC, id DESC LIMIT ?", (account, int(keep))).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    out = {}
    for tid, sym, et, xt, lev, data in rows:
        d = L._j(data)
        out[L._i(tid)] = {"symbol": sym, "side": L._i(d.get("side")), "entry_time": L._i(et), "exit_time": L._i(xt), "leverage": L._i(lev),
                          "entry_price": L._f(d.get("entry_price")), "mfe_price": L._f(d.get("mfe_price")), "mae_price": L._f(d.get("mae_price")),
                          "funding": L._f(d.get("funding")), "qty": L._f(d.get("qty"))}
    return out


# ---------------------------------------------------------------- the config the bot runs
def combo_facts(p: dict, more: dict, path: Optional[str] = None) -> dict:
    """The run's config (live-ac.db combo_run, else PAPERBOT_LIVE_COMBO_CONFIG) as the cards need it; ``path``: another
    paper bot's database (its combo_run, else PAPERBOT_LIVE_COMBO2_CONFIG; owners 10-19, the -35 % bot)."""
    combo = L.read_combo(path, more.get("combo2_config") or "-") if path else L.read_combo(p["paper"], more["combo_config"])
    if combo.get("state") != "ok":
        return {"state": combo.get("state"), "reason_ko": combo.get("reason_ko"), "reason": combo.get("reason"), "path": combo.get("path"),
                "cfg": {}, "members": []}
    cfg = combo.get("config") or {}
    return {"state": "ok", "source": combo.get("source"), "path": combo.get("path"), "cfg": cfg, "members": L.members_of(combo)}


def rules_out(facts: dict, rt: Optional[float]) -> dict:
    """The fixed rules for the page's head line (words come from the config's own numbers)."""
    cfg = facts.get("cfg") or {}
    spec = ladder_of(cfg)
    lev = cfg.get("leverage") if isinstance(cfg.get("leverage"), dict) else {}
    return {"state": facts.get("state"), "name": cfg.get("name") if isinstance(cfg.get("name"), str) else None,
            "stop": stop_rule(cfg), "ladder_ko": spec.describe() if spec else None, "two_part": bool(spec and spec.two_part),
            "early_exit": cfg.get("early_exit"), "early_exit_until_lock": cfg.get("early_exit_until_lock") is True,
            "margin": L._f(cfg.get("margin")) if not isinstance(cfg.get("margin"), str) else cfg.get("margin"),
            "leverage_btc": L._i(lev.get("BTCUSDT")), "leverage_alt": L._i(lev.get("default")), "round_trip": rt,
            "n_members": len(facts.get("members") or []), "n_no_chase": sum(1 for m in facts.get("members") or [] if m.get("no_chase")),
            # the 추세판단 봇 (docs/trend-bot-ko.md): its members by role (눌림 · 자리 · 돌파 · 횡보), never the old bot's A/B groups
            "trend": cfg.get("trend") is not None}


def setting_of(facts: dict, order: Optional[int], strategy: Optional[str] = None, tf: Optional[str] = None) -> Optional[dict]:
    """The member (setting) at ``order`` in the config the bot runs, with its group: B = "no_chase" (추격 진입 막기), else A.
    With the position's strategy and timeframe: that setting even when the list was renumbered since (livebots.member_of)."""
    ms = facts.get("members") or []
    m = L.member_of(ms, order, strategy, tf)
    if m is None:
        return None
    trend = (facts.get("cfg") or {}).get("trend") is not None
    cfg = facts.get("cfg") or {}
    # the A / B groups were 규칙봇 15's: none on a bot with entry gates (owners 10-23, the 'VWAP 개선판')
    gate = isinstance(cfg.get("vote_gate"), dict) or isinstance(cfg.get("vol_gate"), dict)
    return {"order": m.get("order") or order, "strategy": m.get("strategy"), "tf": m.get("tf"),
            "group": None if gate else "B" if m.get("no_chase") else "A",
            "no_chase": bool(m.get("no_chase")), "no_chase_ko": m.get("no_chase_ko"), "entry_ko": m.get("entry_ko"),
            "stop_ko": (m.get("stop") or {}).get("ko"), "role": L.TREND_ROLE.get(m.get("strategy")) if trend else None}


# ---------------------------------------------------------------- one card
def why_ref(bot: Optional[str], symbol: Optional[str], entry: Optional[int]) -> Optional[dict]:
    """The 진입 근거 reference of a paper entry (GET /api/v4/livebots/why?bot=&symbol=&entry=): an executor's position and
    trade carry the one of the paper entry they followed."""
    if bot not in ("paper", "paper2") or not symbol or entry is None:
        return None
    return {"bot": bot, "symbol": symbol, "entry": int(entry)}


def _gap(pp: Optional[dict], xp: dict) -> Optional[dict]:
    """The entry gap of an executor's position against the paper's: price (in the trade's favour positive, livebots'
    trade_rows rule) and time."""
    if not pp or not pp.get("entry") or not xp.get("entry"):
        return None
    side = int(xp.get("side") or 0)
    return {"paper_entry": pp["entry"], "live_entry": xp["entry"], "slip": side * (pp["entry"] - xp["entry"]) / pp["entry"],
            "delay_ms": (xp["entry_time"] - pp["entry_time"]) if xp.get("entry_time") is not None and pp.get("entry_time") is not None else None}


def paper_card(cid: str, acct: str, paper: dict, raw: dict, facts: dict, conn, bars_state: dict, now: int, execs: list,
               bot: Optional[dict] = None, since: Optional[int] = None) -> dict:
    """The paper account's (or its coin-flip twin's) card. ``bot`` (livebots.paper_bots; two paper bots, owners 10-19):
    its label, and its executors' cells only for the executors that follow it (the others "other"); an executor without
    it says why from its own records (livebots.WHY). ``since``: the 추세판단 봇's start: a position entered before it is the
    bot before it's (``inherited``, 전환 전)."""
    base = {"id": cid, "kind": "flip" if cid == "flip" else "paper", "account": acct,
            "name_ko": "동전 쌍둥이" if cid == "flip" else "페이퍼(연습)", "note_ko": FLIP_KO if cid == "flip" else None}
    if bot:
        base.update(label_ko=bot.get("label_ko"), stop_ko=bot.get("stop_ko"), bot_ko=bot.get("name"))
    if paper.get("state") != "ok":
        return {**base, **{k: paper.get(k) for k in ("state", "reason_ko", "reason", "path")}}
    a = (paper.get("accounts") or {}).get(acct) or {}
    if not a.get("known"):
        return {**base, "state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요", "path": paper.get("path")}
    out = {**base, "state": "ok", "as_of_ms": paper.get("as_of_ms"), "stale": paper.get("stale"), "wallet": a.get("wallet"),
           "halted": bool(a.get("halted")), "position": None}
    pos = a.get("position")
    if not pos:
        return out
    cfg = facts.get("cfg") or {}
    rp = raw.get(acct) or {}
    side, entry, lev = int(pos.get("side") or 0), pos.get("entry"), pos.get("leverage")
    rt, ff = float(pos.get("round_trip") or 0.0), float(pos.get("funding_frac") or 0.0)
    margin = L._f(rp.get("margin_initial")) or pos.get("margin")
    lock = pos.get("lock_roe")
    # 최대 +% / 최대 −%: the engine's own record when it has one (a position saved before the fill has 0.0 there)
    mfe_px, mae_px = L._f(rp.get("mfe_price")), L._f(rp.get("mae_price"))
    if mfe_px and mae_px and mfe_px > 0 and mae_px > 0:
        ex = excursion(side, entry, lev, rt, ff, mfe_px, mae_px, "engine")
    else:
        ex = from_bars(conn, bars_state, pos.get("symbol"), side, entry, lev, rt, ff, pos.get("entry_time"), now)
    spec = ladder_of(cfg)
    best = ex.get("mfe") if ex.get("state") == "ok" else None
    sr = stop_rule(cfg)
    stop50 = roe_price(side, entry, lev, -sr["roe"], rt if sr["net"] else 0.0) if sr else None
    cells = []
    for x in execs:
        xp = (x["record"].get("position") if x["record"].get("state") == "ok" else None) or None
        if cid not in ("paper", "paper2"):
            continue
        if bot and not L.LP.same(x.get("paper_path"), bot["path"]):
            cells.append({"id": x["id"], "name_ko": x["name_ko"], "state": "other",
                          "reason_ko": f"{L.josa(x['name_ko'], '은', '는')} 다른 페이퍼({x.get('follows_ko') or '다른 페이퍼'})를 따라가요"})
        elif xp and xp.get("key") == pos.get("key"):
            cells.append({"id": x["id"], "name_ko": x["name_ko"], "state": "following", **(_gap(pos, xp) or {})})
        else:
            why = ((x["record"].get("why") or {}).get(pos.get("key")) or {}) if x["record"].get("state") == "ok" else {}
            kind = next((k for k, _ko in L.WHY if k in why), None)
            cells.append({"id": x["id"], "name_ko": x["name_ko"], "state": "none" if x["record"].get("state") == "ok" else "unknown",
                          "reason_ko": None if x["record"].get("state") == "ok" else x["record"].get("reason_ko"),
                          "why_ko": L.WHY_KO[kind] if kind else None, "why_text": why[kind].get("text") if kind else None})
    out["position"] = {
        "key": pos.get("key"), "symbol": pos.get("symbol"), "side": side, "leverage": lev, "qty": pos.get("qty"), "margin": margin,
        "entry": entry, "entry_time": pos.get("entry_time"), "strategy_id": pos.get("strategy_id"), "timeframe": pos.get("timeframe"),
        "member": pos.get("member"), "member_order": pos.get("member_order"), "stop_rule": pos.get("stop_rule"),
        "setting": setting_of(facts, pos.get("member_order"), pos.get("strategy_id"), pos.get("timeframe")),
        "stop": pos.get("stop"), "stop_initial": pos.get("stop_initial"), "stop50": stop50, "stop_rule_cfg": sr,
        "locked": lock is not None, "lock_roe": lock, "lock_price": pos.get("stop") if lock is not None else None,
        "secured": {"roe": lock, "usd": lock * margin if margin else None} if lock is not None else None,
        "next": pos.get("next_lock"), "ladder": ladder_steps(spec, lock, best, lambda r: roe_price(side, entry, lev, r, rt, ff),
                                                             lambda r: roe_price(side, entry, lev, r, rt, ff)),
        "liq": pos.get("liq"), "liq_ko": None if pos.get("liq") else "청산가 기록이 없어요",
        "round_trip": rt, "funding_frac": ff, "funding_paid": pos.get("funding_paid"),
        "last_mark": pos.get("last_mark"), "last_mark_roe_net": pos.get("last_mark_roe_net"), "best_roe": best,
        "excursion": ex, "fast": fast_state(cfg, lock), "execs": cells, "status": "open",
        # 진입 근거 (dash/more/livewhy.py): this paper entry's reference (the coin-flip twin's side is a coin flip: none)
        "why": why_ref(cid, pos.get("symbol"), pos.get("entry_time")) if cid in ("paper", "paper2") else None,
    }
    inh = bool(since) and pos.get("entry_time") is not None and int(pos["entry_time"]) < int(since)
    out["position"].update(inherited=inh, inherited_ko=INHERITED_KO if inh else None)
    return out


def exec_card(x: dict, pp: Optional[dict], paper: dict, facts: dict, conn, bars_state: dict, now: int) -> dict:
    """An executor's card: its own position (its fill, its exchange stop), the paper position it follows for the ladder."""
    base = {"id": x["id"], "kind": "live", "account": x["follows"], "name_ko": x["name_ko"]}
    r = x["record"]
    if r.get("state") != "ok":
        return {**base, **{k: r.get(k) for k in ("state", "reason_ko", "reason", "path")}}
    out = {**base, "state": "ok", "as_of_ms": r.get("as_of_ms"), "stale": r.get("stale"), "wallet": r.get("last_equity"),
           "halted": bool(r.get("halted")), "halt_reason": r.get("halt_reason") or "", "position": None}
    xp = r.get("position")
    if not xp:
        return out
    cfg = facts.get("cfg") or {}
    side, entry, lev = int(xp.get("side") or 0), xp.get("entry"), xp.get("leverage")
    rt = float(paper.get("round_trip") or 0.0) if paper.get("state") == "ok" else 0.0
    paired = bool(pp and xp.get("key") == pp.get("key") and pp.get("entry"))
    ratio = entry / pp["entry"] if paired and entry else None
    stop, locked = xp.get("stop"), bool(xp.get("locked"))
    ex = from_bars(conn, bars_state, xp.get("symbol"), side, entry, lev, rt, 0.0, xp.get("entry_time"), now)
    spec = ladder_of(cfg)
    sr = stop_rule(cfg)
    lock = pp.get("lock_roe") if paired else None
    own = xp.get("own") if isinstance(xp.get("own"), dict) else None
    if own is not None:
        return own_exec_card(out, x, xp, pp, paired, own, cfg, facts, spec, sr, ex, rt)
    if paired:
        pside, pentry, plev = int(pp["side"]), pp["entry"], pp["leverage"]
        prt, pff = float(pp.get("round_trip") or 0.0), float(pp.get("funding_frac") or 0.0)
        price_of = lambda r_: roe_price(pside, pentry, plev, r_, prt, pff)           # noqa: E731  (the paper's trigger: where its lock moves)
        lock_price_of = lambda r_: (lambda v: v * ratio if v and ratio else None)(roe_price(pside, pentry, plev, r_, prt, pff))  # noqa: E731
        best = (pp.get("_best_roe"))
        nx = pp.get("next_lock")
        nxt = {**nx, "lock_price": nx["lock_price"] * ratio if nx.get("lock_price") and ratio else None, "from": "paper"} if nx else None
    else:
        price_of = lambda r_: roe_price(side, entry, lev, r_, rt, 0.0)               # noqa: E731
        lock_price_of = price_of
        best = ex.get("mfe") if ex.get("state") == "ok" else None
        nl = spec.next_after(None) if spec and not locked else None
        nxt = {"lock": nl[0], "at": nl[1], "price": price_of(nl[1]), "lock_price": price_of(nl[0]), "from": "own"} if nl else None
    secured = None
    if locked and stop and entry:
        sroe = net_roe(side, entry, stop, lev, rt)
        secured = {"roe": sroe, "usd": sroe * xp["margin"] if sroe is not None and xp.get("margin") else None, "basis": "stop"}
    out["position"] = {
        "key": xp.get("key"), "symbol": xp.get("symbol"), "side": side, "leverage": lev, "qty": xp.get("qty"), "margin": xp.get("margin"),
        "entry": entry, "entry_time": xp.get("entry_time"), "status": xp.get("status"), "stop_order": xp.get("stop_order"),
        "strategy_id": pp.get("strategy_id") if paired else None, "timeframe": pp.get("timeframe") if paired else None,
        "member": pp.get("member") if paired else None, "member_order": pp.get("member_order") if paired else None,
        "setting": setting_of(facts, pp.get("member_order"), pp.get("strategy_id"), pp.get("timeframe")) if paired else None,
        "paired": paired,
        "stop": stop, "stop_initial": xp.get("stop_initial"), "stop50": roe_price(side, entry, lev, -sr["roe"], rt if sr["net"] else 0.0) if sr else None,
        "stop_rule_cfg": sr, "locked": locked, "lock_roe": lock, "lock_price": stop if locked else None, "secured": secured,
        "next": nxt, "ladder": ladder_steps(spec, lock if paired else None, best, price_of, lock_price_of),
        "ladder_from": "paper" if paired else "own", "liq": None, "liq_ko": EXEC_LIQ_KO,
        "round_trip": rt, "funding_frac": 0.0, "cost_ko": EXEC_COST_KO, "best_roe": best,
        "excursion": ex, "fast": fast_state(cfg, lock if paired else None, follows=True) if paired else
        {"state": "unknown", "ko": "따라가는 페이퍼 포지션을 못 찾았어요: 빠른 손절은 페이퍼가 닫을 때 따라 닫는 것뿐이에요"},
        "gap": _gap(pp, xp) if paired else None,
    }
    return out


def own_exec_card(out: dict, x: dict, xp: dict, pp: Optional[dict], paired: bool, own: dict, cfg: dict, facts: dict, spec, sr,
                  ex: dict, paper_rt: float) -> dict:
    """An executor that runs the ladder on its own position ("own", owners 10-20 "거래소 기준으로 익절해야지"): its own lock,
    next step and ladder from its own fill, its own exchange's prices and costs (the executor's ``own`` record,
    livebots._own_view), never the paper's; its fast stop follows the paper's reverse signal only before its OWN first
    lock. 최대 +% / 최대 −% stay the Binance 1m bars' (the page's one source for them); its own best price beside it.
    The ladder's numbers are on its basis (``ladder_basis``: "net" after its round-trip cost, "gross" the exchange
    screen's ROE before fees); the money it secures and the card's net ROE are always after its round-trip cost."""
    side, entry, lev = int(xp.get("side") or 0), xp.get("entry"), xp.get("leverage")
    rt = own.get("round_trip") if own.get("round_trip") is not None else paper_rt          # the ladder's (0: gross)
    crt = own.get("cost_round_trip") if own.get("cost_round_trip") is not None else rt     # the exchange's
    gross = own.get("basis") == "gross"
    from ...ladder2 import ComboLadder
    ospec = ComboLadder.of(own.get("ladder")) or spec
    lock = own.get("lock")
    stop = xp.get("stop")
    price_of = lambda r_: roe_price(side, entry, lev, r_, rt)                    # noqa: E731
    nx = own.get("next")
    nxt = {**nx, "from": "exchange"} if nx else None
    if nxt is None and ospec is not None:
        nl = ospec.next_after(lock)
        nxt = {"lock": nl[0], "at": nl[1], "price": price_of(nl[1]), "lock_price": price_of(nl[0]), "from": "exchange"}
    secured = None
    if lock is not None and stop and entry:
        sroe = net_roe(side, entry, stop, lev, crt)
        secured = {"roe": sroe, "usd": sroe * xp["margin"] if sroe is not None and xp.get("margin") else None, "basis": "stop"}
    exname = EX_KO.get(own.get("exchange") or x["id"], x.get("name_ko") or x["id"])
    cost_ko = (f"순ROE는 {exname} 비용 기준 (수수료 {own['taker_fee'] * 100:.3f}% + 슬리피지 {own['slippage'] * 100:.2f}%, 양쪽 · 왕복 "
               f"{crt * 100:.2f}%), 펀딩 뺌") if own.get("taker_fee") is not None and own.get("slippage") is not None and crt is not None \
        else "순ROE는 이 거래소 비용 기준, 펀딩 뺌"
    ee = cfg.get("early_exit")
    if not ee:
        fast = {"state": "none", "ko": "빠른 손절 없음 (설정에 없어요) · 손절선과 거래소 기준 계단 익절만"}
    elif lock is not None:
        fast = {"state": "off", "ko": "꺼짐 · 이 실행기는 자기 첫 잠금을 지나 계단 익절만 (페이퍼의 빠른 청산은 안 따라요)"}
    else:
        fast = {"state": "armed", "ko": "빠른 손절 대기: 페이퍼가 반대 신호로 닫으면 따라 닫아요 (이 실행기 자기 첫 잠금 전까지만)"}
    staying = None
    if own.get("staying"):
        why = EXIT_REASON_KO.get(own.get("paper_reason"), own.get("paper_reason") or "")
        staying = {"paper_reason": own.get("paper_reason"), "paper_exit_time": own.get("paper_exit_time"),
                   "ko": f"페이퍼는 이미 닫았어요 ({why}) · 이 포지션은 거래소 기준 손절·계단으로 계속 들고 있어요"}
    out["position"] = {
        "key": xp.get("key"), "symbol": xp.get("symbol"), "side": side, "leverage": lev, "qty": xp.get("qty"), "margin": xp.get("margin"),
        "entry": entry, "entry_time": xp.get("entry_time"), "status": xp.get("status"), "stop_order": xp.get("stop_order"),
        "strategy_id": pp.get("strategy_id") if paired else None, "timeframe": pp.get("timeframe") if paired else None,
        "member": pp.get("member") if paired else None, "member_order": pp.get("member_order") if paired else None,
        "setting": setting_of(facts, pp.get("member_order"), pp.get("strategy_id"), pp.get("timeframe")) if paired else None,
        "paired": paired,
        "stop": stop, "stop_initial": xp.get("stop_initial"),
        "stop50": roe_price(side, entry, lev, -sr["roe"], paper_rt if sr["net"] else 0.0) if sr else None,
        "stop_rule_cfg": sr, "locked": lock is not None, "lock_roe": lock, "lock_price": stop if lock is not None else None,
        "secured": secured, "next": nxt, "ladder": ladder_steps(ospec, lock, own.get("best_roe"), price_of, price_of),
        "ladder_from": "exchange", "basis": "gross" if gross else "net", "basis_ko": OWN_KO + (" · 화면 ROE" if gross else ""),
        "ladder_ko": OWN_LADDER_KO + (" · 계단 숫자는 화면 ROE(수수료 전), 잠금 가격 = 체결가 × (1 ± 잠금 / 배수)" if gross else ""),
        "liq": None, "liq_ko": EXEC_LIQ_KO, "round_trip": crt, "ladder_round_trip": rt, "funding_frac": 0.0, "cost_ko": cost_ko,
        "best_roe": own.get("best_roe"),
        "own_best": {"price": own.get("best"), "roe": own.get("best_roe"), "src": own.get("src")},
        "excursion": ex, "fast": fast, "staying": staying, "gap": _gap(pp, xp) if paired else None,
    }
    return out


EXIT_REASON_KO = {"SL": "손절", "LOCK": "계단 익절", "TP": "익절", "LIQ": "강제청산", "REV": "빠른 청산", "HALT": "멈춤 청산",
                  "MANUAL": "수동 청산", "JUDGE": "감독 청산(추세 뒤집힘)", "TIME": "감독 청산(시간 정리)",
                  "SWITCH": "전환 전 포지션 정리"}


def build(p: Optional[dict] = None, more: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """GET /api/v4/livebots/positions."""
    p = p or L.paths()
    more = more or L.paths_more()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    _configs, _follows, paper, execs = L.sources(p, now)
    bots = L.paper_bots(p, paper, execs)
    two = len(bots) > 1
    facts = combo_facts(p, more)
    # each paper bot: its read, its config (the -35 % bot's stop for its own cards and its executor's), its raw positions
    per: dict = {}
    for b in bots:
        f = facts if b["id"] == "paper" else combo_facts(p, more, b["path"])
        rw = raw_positions(b["path"], (L.ACCOUNT, L.FLIP_ACCOUNT)) if b["read"].get("state") == "ok" else {}
        per[L.LP.norm(b["path"])] = (b, f, rw)
    raw = per[L.LP.norm(p["paper"])][2]
    tb = L.trend_bot(p["paper"])
    since = tb["since"] if tb else None                    # the 추세판단 봇's start on the main paper database
    conn, bars_state = open_bars(more["rule_db"])
    try:
        cards = {}
        best: dict = {}
        for b, f, rw in per.values():
            cards[b["id"]] = paper_card(b["id"], L.ACCOUNT, b["read"], rw, f, conn, bars_state, now, execs, bot=b if two else None,
                                        since=since if b["id"] == "paper" else None)
            best[L.LP.norm(b["path"])] = (cards[b["id"]].get("position") or {}).get("best_roe")
        for x in execs:
            b, f, _rw = per.get(L.LP.norm(x["paper_path"])) or per[L.LP.norm(p["paper"])]
            own = b["read"]
            follow = (own.get("accounts") or {}).get(x["follows"], {}).get("position") if own.get("state") == "ok" else None
            fp = {**follow, "_best_roe": best.get(L.LP.norm(b["path"])) if x["follows"] == L.ACCOUNT else None} if follow else None
            cards[x["id"]] = exec_card(x, fp, own, f, conn, bars_state, now)
            xpos = cards[x["id"]].get("position")
            if xpos and xpos.get("paired") and follow:
                xpos["why"] = why_ref(b["id"], follow.get("symbol"), follow.get("entry_time"))
            if two:
                cards[x["id"]]["follows_ko"] = b["short_ko"]
        cards["flip"] = paper_card("flip", L.FLIP_ACCOUNT, paper, raw, facts, conn, bars_state, now, [], since=since)
    finally:
        if conn is not None:
            conn.close()
    return {"now_ms": now, "account": L.ACCOUNT, "rules": rules_out(facts, paper.get("round_trip") if paper.get("state") == "ok" else None),
            "combo": {k: facts.get(k) for k in ("state", "reason_ko", "reason", "path", "source")},
            "bars": {k: bars_state.get(k) for k in ("state", "reason_ko", "reason", "path")},
            "cards": [cards[c] for c, _a in CARDS if c in cards], "papers": L.papers_out(bots)}


# ---------------------------------------------------------------- 거래 tab: 최대 +% / 최대 −% of the closed trades
def _final_get(key: str) -> Optional[dict]:
    with _lock:
        v = _final.get(key)
        if v is not None:
            _final.move_to_end(key)
        return v


def _final_put(key: str, v: dict) -> None:
    with _lock:
        _final[key] = v
        _final.move_to_end(key)
        while len(_final) > FINAL_MAX:
            _final.popitem(last=False)


def _closed(conn, bars_state: dict, fkey: str, sym: str, side: int, entry, lev, rt: float, ff: float, t0, t1) -> dict:
    """One closed trade's excursion from the bars, kept once its bars reach its exit minute (they never change after)."""
    hit = _final_get(fkey)
    if hit is not None:
        return hit
    v = from_bars(conn, bars_state, sym, side, entry, lev, rt, ff, t0, t1)
    if v.get("state") == "ok" and t1 is not None and (v.get("to_ms") or 0) >= int(t1) - int(t1) % MIN:
        _final_put(fkey, v)
    return v


def excursions(p: Optional[dict] = None, more: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """GET /api/v4/livebots/positions/excursions: {accts: {paper | bybit | mexc: {state, rows: {row key: excursion}}}}."""
    p = p or L.paths()
    more = more or L.paths_more()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    _configs, _follows, paper, execs = L.sources(p, now)
    rt_paper = float(paper.get("round_trip") or 0.0) if paper.get("state") == "ok" else 0.0
    conn, bars_state = open_bars(more["rule_db"])
    accts: dict = {}
    try:
        for b in L.paper_bots(p, paper, execs):           # the second paper bot's rows as "paper2:<id>" (거래 tab's keys)
            pr, aid = b["read"], b["id"]
            if pr.get("state") != "ok":
                accts[aid] = {k: pr.get(k) for k in ("state", "reason_ko", "reason", "path")}
                continue
            rt = float(pr.get("round_trip") or 0.0)
            rows = {}
            for tid, t in paper_trade_extremes(b["path"], L.ACCOUNT, L.TRADES_KEEP).items():
                side, entry, lev = int(t["side"] or 0), t["entry_price"], t["leverage"]
                notional = (t["qty"] or 0) * (entry or 0)
                ff = (t["funding"] or 0.0) / notional if notional else 0.0
                if t["mfe_price"] and t["mae_price"] and t["mfe_price"] > 0 and t["mae_price"] > 0:
                    rows[f"{aid}:{tid}"] = excursion(side, entry, lev, rt, ff, t["mfe_price"], t["mae_price"], "engine")
                else:
                    fk = ["paper", tid, t["entry_time"], t["exit_time"], rt] if aid == "paper" else [aid, b["path"], tid, t["entry_time"], t["exit_time"], rt]
                    rows[f"{aid}:{tid}"] = _closed(conn, bars_state, json.dumps(fk), t["symbol"], side, entry, lev, rt, ff,
                                                   t["entry_time"], t["exit_time"])
            accts[aid] = {"state": "ok", "rows": rows}
        for x in execs:
            r = x["record"]
            if r.get("state") != "ok":
                accts[x["id"]] = {k: r.get(k) for k in ("state", "reason_ko", "reason", "path")}
                continue
            rows = {}
            for t in (r.get("trades") or [])[-L.TRADES_KEEP:]:
                fkey = json.dumps([x["id"], t["key"], t["entry_ts"], t["exit_ts"], t["entry_price"], rt_paper])
                rows[str(t["key"])] = _closed(conn, bars_state, fkey, t["symbol"], int(t["side"] or 0), t["entry_price"], t["leverage"],
                                              rt_paper, 0.0, t["entry_ts"], t["exit_ts"])
            accts[x["id"]] = {"state": "ok", "rows": rows, "cost_ko": EXEC_COST_KO}
    finally:
        if conn is not None:
            conn.close()
    return {"now_ms": now, "bars": {k: bars_state.get(k) for k in ("state", "reason_ko", "reason", "path")},
            "engine_ko": ENGINE_KO, "bars_ko": BARS_KO, "accts": accts}


# ---------------------------------------------------------------- routes
def register(app, ctx) -> dict:
    from ..app import json_finite

    def key(name: str, p: dict, more: dict) -> str:
        return name + ":" + json.dumps([p, more], sort_keys=True)

    @app.get("/api/v4/livebots/positions")
    def get_livebots_positions():
        """실거래 › 포지션: each account's open position with its 진입가 · 손절가 · 익절가, the ladder, 최대 +% / 최대 −% (5 s cache)."""
        p, more = L.paths(), L.paths_more()
        return L._cached(key("pos", p, more), lambda: json_finite(build(p, more)))

    @app.get("/api/v4/livebots/positions/excursions")
    def get_livebots_excursions():
        """실거래 › 거래: 최대 +% / 최대 −% of each closed trade the tab lists, keyed by its row key (5 s cache)."""
        p, more = L.paths(), L.paths_more()
        return L._cached(key("exc", p, more), lambda: json_finite(excursions(p, more)))

    return {"routes": ["/api/v4/livebots/positions", "/api/v4/livebots/positions/excursions"]}
