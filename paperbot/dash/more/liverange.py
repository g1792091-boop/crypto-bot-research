"""실거래 › 봇별 › 레인지 봇 (#/rangebot; owners 10-26: "레인지봇을 추세 봇 woo x pro 거래소로 … 원래 있던 추세봇 woo x pro 는
없애고", docs/range-bot-ko.md): the 레인지 봇 paper bot (account COMBO@mix in range.db, and its coin-flip twin COMBOFLIP@mix)
and only the executors that follow it (now WOO X Pro), on one screen and nothing of the other bots. Read-only, one answer:

    GET /api/v4/livebots/range   status (꺼짐 until its database is there, with the guide's steps to start it; 켜짐 / 멈춤 /
                                 기록 멈춤 / 못 읽음 / 첫 기록 전 after), the plan in words from its config's own numbers (its
                                 start record ``combo_run``; before it, the server's config file, else the repo's template
                                 deploy/combo.range.json, said so), the wallet against its start, today's trades, the open
                                 position with its stop and take-profit prices (and each follower's), the pullback wait and
                                 every coin's 1h supertrend (state ``range``, rangebot.py's snapshot, and ``combo``'s
                                 ``range_wait``), the recent closed paper trades with each follower's part side by side, the
                                 paper entries against each follower (followed, or the executor's own reason), the real side
                                 against the coin-flip twin, the balance lines, the signals of the last 24 hours by what became
                                 of them, the warnings (5 s cache, as every 실거래 tab)

Which database is the 레인지 봇 (the site and this screen must agree): livebots.paper_bots' "range" (a paper database an
executor follows, or PAPERBOT_LIVE_RANGE_DB once it is there, whose start record's config has a ``range`` section; never the
file name alone). Its file opened ``mode=ro`` + ``query_only`` (livebots.open_ro), one snapshot; the executors through
livebots.sources. Honest states as every live page (CONTRACT §1.6): ``missing`` (수집 전) / ``error`` (못 읽음 + why),
never a zero for an unread value; the paper money is never shown as real money.

The numbers: ratios (0.12 = 12 %), net ROE at the trade's leverage, win = P&L > 0, times UTC ms.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Optional

from ... import livepapers as LP
from . import livebots as L

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir))
ACCOUNT, FLIP = L.ACCOUNT, L.FLIP_ACCOUNT
NAME_KO = L.RANGE_NAME_KO
UNIT = "paperbot-combo-range"
GUIDE = "docs/range-bot-ko.md"
GUIDE_STEP_KO = "docs/range-bot-ko.md 3장 'B. 레인지 페이퍼 봇 켜기'"
REPO_CONFIG = os.path.join(REPO, "deploy", "combo.range.json")
OFF_KO = "아직 꺼져 있어요"
FIRST_KO = "레인지 봇이 아직 첫 기록 전이에요 (켜고 1~2분 뒤 생겨요)"
NOT_RANGE_KO = "이 기록 파일의 봇은 레인지 봇이 아니에요 (시작 기록의 설정에 range가 없어요)"
# the guide's start steps (docs/range-bot-ko.md 3장 B), shown while the bot is off
START_STEPS = (
    "sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.range.json /etc/paperbot/combo-range.json",
    "cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo-range.json",
    "sudo systemctl enable --now paperbot-combo-range",
    "sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/range.db",
)
MIN, HOUR, DAY = 60_000, L.HOUR, L.DAY
HB_STALE_MS = L.PAPER_STALE_MS          # the bot saves every stepped minute
SIG_SPAN_MS = 24 * HOUR                 # 최근 신호
SIG_KEEP = 120
TRADES_KEEP = 30                        # recent closed paper trades listed (newest first)
FOLLOW_KEEP = 40
WARN_KEEP = 20
SIDE_KO = {1: "롱", -1: "숏"}
ST_KO = {1: "상승", -1: "하락", 0: "없음"}
FOLLOW_KO = {"followed": "따라 들어감", "open": "같이 들고 있음", "missed": "안 들어감", "before": "옮기기 전", "other": "다른 봇을 따라감",
             "waiting": "실거래 쪽 기록을 기다리는 중"}
WAIT_MS = 2 * L.MATCH_MS                # a paper entry this fresh may not have its live row yet


def coin_ko(symbol: Any) -> str:
    return str(symbol or "").replace("USDT", "")


def _kst(ms: Optional[int]) -> str:
    if ms is None:
        return "?"
    t = time.gmtime((int(ms) + L.KST_MS) / 1000)
    return f"{t.tm_mon}/{t.tm_mday} {t.tm_hour:02d}:{t.tm_min:02d}"


def read_json(path: str) -> dict:
    """A config file as JSON: {"state": "ok", "raw": {...}} / missing / error (never a guess)."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return L._missing(path, "설정 파일이 아직 없어요")
    except ValueError as exc:
        return {**L._err(path, exc), "reason_ko": "설정 파일이 JSON 모양이 아니에요"}
    except OSError as exc:
        return L._err(path, exc)
    if not isinstance(raw, dict):
        return {"state": "error", "path": path, "reason": "not an object", "reason_ko": "설정 파일의 모양이 달라요"}
    return {"state": "ok", "path": path, "raw": raw}


# ---------------------------------------------------------------- the 레인지 봇's database (one snapshot)
def _trade(r: tuple) -> dict:
    """A closed paper trade (livebots._paper_trade) with the range facts of its entry (its context ``range``)."""
    t = L._paper_trade(r)
    d = L._j(r[9])
    ctx = d.get("context") if isinstance(d.get("context"), dict) else {}
    t["range"] = ctx.get("range") if isinstance(ctx.get("range"), dict) else None
    t["tp_price"] = L._f(d.get("tp_price"))
    return t


def snapshot(path: str, now: int) -> dict:
    """range.db in one read: its states (accounts, combo_run, heartbeat, combo, range), its accounts' first records, the
    closed trades of both accounts (with their range facts), the signal rows of the last 24 hours with the outcomes, and the
    bot's own WARN / CRITICAL alerts."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path, L.MISSING_KO)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if not {"state", "trades"} <= tables:
            return L._missing(path, L.NO_TABLE_KO)
        st = {k: (L._i(ts), L._j(d)) for k, ts, d in conn.execute(
            "SELECT k, ts, data FROM state WHERE k IN ('accounts', 'combo_run', 'heartbeat', 'combo', 'range')")}
        created = {a: L._i(t) for a, t in conn.execute("SELECT account_id, created_ts FROM accounts")} if "accounts" in tables else {}
        trades = {a: [_trade(r) for r in conn.execute(
            "SELECT id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data FROM trades "
            "WHERE account_id = ? ORDER BY exit_time, id", (a,))] for a in (ACCOUNT, FLIP)}
        sigs, outs, alerts = [], [], []
        since = now - SIG_SPAN_MS
        if "signal_log" in tables:
            sigs = conn.execute("SELECT id, bar_close, timeframe, strategy, symbol, side, status, data FROM signal_log WHERE bar_close >= ? "
                                "ORDER BY bar_close DESC, id DESC LIMIT ?", (since, SIG_KEEP)).fetchall()
        if "outcomes" in tables:
            outs = conn.execute("SELECT step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? AND step_ts >= ? "
                                "ORDER BY id", (ACCOUNT, since)).fetchall()
        if "alerts" in tables:
            alerts = conn.execute("SELECT ts, level, text FROM alerts WHERE level IN ('WARN', 'CRITICAL') ORDER BY ts DESC LIMIT ?",
                                  (WARN_KEEP,)).fetchall()
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    run_ts, run = st.get("combo_run") or (None, {})
    acc_ts, acc = st.get("accounts") or (None, {})
    return {"state": "ok", "path": path, "as_of_ms": acc_ts, "engines": acc.get("engines") if isinstance(acc.get("engines"), dict) else {},
            "run_ts": run_ts, "cfg": run.get("config") if isinstance(run.get("config"), dict) else None,
            "describe": [x for x in run.get("members") or [] if isinstance(x, str)], "taker_fee": L._f(run.get("taker_fee")),
            "heartbeat": st.get("heartbeat") or (None, {}), "combo": (st.get("combo") or (None, {}))[1],
            "range": st.get("range") or (None, None), "created": created, "trades": trades, "signals": sigs, "outcomes": outs,
            "alerts": [{"ts": L._i(t), "level": lvl, "level_ko": L.LEVEL_KO.get(lvl, lvl), "text": txt} for t, lvl, txt in alerts]}


# ---------------------------------------------------------------- the plan in words (the config's own numbers)
def _pct(x: float, d: int = 0) -> str:
    v = round(x * 100, max(d, 2))
    return f"{v:g}%"


def member_line(cfg: dict, describe: list) -> str:
    """The entry strategy: the bot's own start record's words ("F7_RF_TRIPLE 1시간 - 커스텀값 rf_mult=9.0, rf_period=80"),
    else the config's pick with where the numbers are."""
    from ... import combo as C                         # the owners' names of the strategies (combo.member_ko)
    out = []
    for line in describe or []:
        t = str(line).split(". ", 1)[-1].split(" [", 1)[0]
        name, _sep, rest = t.partition(" - ")
        strat = name.split(" ")[0]
        out.append(f"{C.member_ko(strat)} ({name}) · {rest}".rstrip(" ·"))
    if out:
        return " / ".join(out)
    picks = [str(m.get("pick") or m.get("strategy")) for m in (cfg.get("members") or []) if isinstance(m, dict)]
    return (" / ".join(picks) or "매매법 설정 없음") + " (커스텀값 숫자는 봇이 켜질 때 시작 기록에 남아요)"


def plan_of(cfg: dict, describe: list, rt: float) -> dict:
    """The plan of a 레인지 봇 config in the owners' words (docs/range-bot-ko.md 1장), each line from the config's own
    numbers: [{"key", "k", "ko"}]; a number the config lacks says so (never the guide's number in its place)."""
    lines = []

    def add(key: str, k: str, ko: str) -> None:
        lines.append({"key": key, "k": k, "ko": ko})
    rw = {x["id"]: x["ko"] for x in L.range_words(cfg)}
    r = {**L.RANGE_DEFAULTS, **(cfg.get("range") if isinstance(cfg.get("range"), dict) else {})}
    add("signal", "신호", f"{member_line(cfg, describe)} · 1시간봉이 마감될 때마다")
    if rw.get("range_st"):
        add("trend", "추세 확인", rw["range_st"].split(": ", 1)[-1])
    add("pull", "되돌림 진입", f"신호 1시간봉 종가에서 {float(r['pullback_atr']):g} × ATR(14, 1시간) 되돌림을 최대 {int(r['wait_min'])}분 기다려요 → "
                             "닿은 5분봉이 끝나면 다음 5분봉 시가에 시장가 · 안 오면 그 신호는 버려요")
    if rw.get("range_one"):
        add("one", "한 신호씩", rw["range_one"].split(": ", 1)[-1])
    if r.get("liq_check"):
        add("liq", "강제청산 여유", f"손절 거리 + 1시간 ATR이 (1/배수 − {float(r['liq_mmr']):.1%}) 안쪽일 때만 · 아주 거친 장이면 건너뜀")
    else:
        add("liq", "강제청산 여유", "확인 안 함 (설정에서 꺼짐)")
    lev = cfg.get("leverage") if isinstance(cfg.get("leverage"), dict) else {}
    syms = [s for s in cfg.get("symbols") or [] if isinstance(s, str)]
    levs = sorted({L._i(lev.get(s)) or L._i(lev.get("default")) for s in syms} - {None}, reverse=True) or \
        sorted({L._i(v) for v in lev.values()} - {None}, reverse=True)
    tp = L._f(cfg.get("take_profit_roe"))
    if tp is not None:
        add("tp", "익절", f"순ROE +{_pct(tp)} 고정 (계단 없음) · 가격으로 " + ", ".join(f"{v}배 {tp / v + rt:.2%}" for v in levs))
    else:
        add("tp", "익절", "고정 익절이 설정에 없어요")
    stop = cfg.get("stop") if isinstance(cfg.get("stop"), dict) else {}
    sr = L._f(stop.get("roe"))
    if stop.get("mode") == "roe" and sr is not None:
        net = stop.get("net") is True
        add("stop", "손절", f"{'순ROE' if net else 'ROE'} −{_pct(sr)} · 가격으로 "
            + ", ".join(f"{v}배 {sr / v - (rt if net else 0.0):.2%}" for v in levs))
    else:
        add("stop", "손절", L.stop_ko(None, stop or None).get("ko") or "손절 설정을 읽지 못했어요")
    named = [f"{coin_ko(k)} {L._i(v)}배" for k, v in lev.items() if k != "default" and L._i(v)]
    rest = L._i(lev.get("default"))
    add("leverage", "배수", " · ".join(named + ([f"{'나머지' if named else '모든 코인'} {rest}배"] if rest else [])) or "배수 설정 없음")
    m = L._f(cfg.get("margin"))
    add("size", "크기", (f"증거금 = 그때 잔고의 {_pct(m)} (이기면 다음 거래가 커지는 복리)" if m is not None else "증거금 설정을 읽지 못했어요")
        + " · 포지션은 언제나 하나")
    pauses = []
    if cfg.get("no_weekend"):
        pauses.append("한국 시간 토·일")
    pre, post = L._i(cfg.get("us_open_pre_min")), L._i(cfg.get("us_open_pause_min"))
    if pre or post:
        pauses.append(f"나스닥 개장 {'앞 ' + str(pre) + '분' if pre else ''}{'·' if pre and post else ''}{'뒤 ' + str(post) + '분' if post else ''}")
    mb = L._i(cfg.get("macro_blackout_min"))
    if mb:
        pauses.append(f"경제 발표 앞뒤 {mb}분")
    add("pause", "진입 금지", (" · ".join(pauses) + " (신호 때와 진입 때 둘 다 봄)") if pauses else "없음")
    if rw.get("range_none"):
        add("none", "없는 것", rw["range_none"])
    add("coins", "코인", " · ".join(coin_ko(s) for s in syms) or "코인 설정 없음")
    add("flip", "동전 쌍둥이", "있음 (COMBOFLIP@mix: 같은 때 들어가고 방향만 동전으로)" if cfg.get("flip_twin", True) else "없음")
    return {"lines": lines, "tp": tp, "stop": sr, "margin": m, "leverage": lev, "initial_equity": L._f(cfg.get("initial_equity")),
            "range": r}


# ---------------------------------------------------------------- status, wallet, position, wait
def status_of(snap: dict, now: int) -> dict:
    """off (no database: 아직 꺼져 있어요, the guide's steps) / error / missing (첫 기록 전) / stopped (기록 멈춤) / halted /
    running; ``seen_ms`` the bot's last heartbeat."""
    base = {"unit": UNIT, "guide": GUIDE, "guide_ko": GUIDE_STEP_KO}
    if snap.get("state") == "missing" and snap.get("reason_ko") == L.MISSING_KO:
        return {**base, "state": "off", "ko": OFF_KO, "why_ko": "서버에 레인지 봇 기록 파일이 아직 없어요", "path": snap.get("path"),
                "steps": list(START_STEPS)}
    if snap.get("state") == "error":
        return {**base, "state": "error", "ko": "레인지 봇 기록을 못 읽었어요", "reason_ko": snap.get("reason_ko"), "reason": snap.get("reason"),
                "path": snap.get("path")}
    if snap.get("state") != "ok" or snap.get("cfg") is None:
        return {**base, "state": "missing", "ko": "수집 전", "why_ko": FIRST_KO, "path": snap.get("path")}
    if not L.range_bot(snap["cfg"]):
        return {**base, "state": "other", "ko": "레인지 봇 아님", "why_ko": NOT_RANGE_KO, "path": snap.get("path")}
    hb_ts, hb = snap["heartbeat"]
    out = {**base, "seen_ms": hb_ts, "since_ms": snap["created"].get(ACCOUNT) or snap.get("run_ts"), "started_ms": snap.get("run_ts"),
           "last_step_ms": L._i((hb or {}).get("last_step")) if isinstance(hb, dict) else None}
    e = (snap.get("engines") or {}).get(ACCOUNT) or {}
    if hb_ts is None or now - hb_ts > HB_STALE_MS:
        return {**out, "state": "stopped", "ko": "기록 멈춤",
                "why_ko": f"{HB_STALE_MS // MIN}분 넘게 새 기록이 없어요 (봇은 1분마다 기록해요) · 서버에서 systemctl status {UNIT}"}
    if e.get("halted"):
        return {**out, "state": "halted", "ko": "멈춤", "why_ko": f"페이퍼 계좌 멈춤: {e.get('halt_reason') or '이유 기록 없음'}"}
    return {**out, "state": "running", "ko": "켜져 있어요", "why_ko": "1시간봉 마감마다 신호를 보고, 되돌림이 오면 들어가요"}


def wallet_of(snap: dict, acct: str, plan: Optional[dict]) -> dict:
    """A paper account's wallet against its start (모의 돈), its record and today's closed trades."""
    e = (snap.get("engines") or {}).get(acct)
    trades = (snap.get("trades") or {}).get(acct) or []
    if e is None and not trades:
        return {"state": "missing", "reason_ko": f"기록에 {acct} 계좌가 아직 없어요", "account": acct}
    first = trades[0] if trades else None
    init = (plan or {}).get("initial_equity")
    if init is None and first and first.get("equity_after") is not None and first.get("pnl") is not None:
        init = first["equity_after"] - first["pnl"]
    wallet = L._f((e or {}).get("wallet"))
    return {"state": "ok", "account": acct, "wallet": wallet, "initial": init,
            "change": wallet - init if wallet is not None and init else None,
            "change_pct": wallet / init - 1 if wallet is not None and init else None,
            "record": L.stats(t["pnl"] for t in trades), "roe_sum": sum(t.get("roe") or 0.0 for t in trades),
            "curve": L.thin([[first["entry_time"], init]] + [[t["exit_time"], t["equity_after"]] for t in trades if t.get("equity_after") is not None])
            if first and init is not None else [], "max_drawdown": L._f((e or {}).get("max_drawdown")),
            "halted": bool((e or {}).get("halted")), "since_ms": snap["created"].get(acct)}


def position_of(snap: dict, rt: float) -> Optional[dict]:
    """The paper's open position: entry, its stop and take-profit prices (the engine's own), net ROE at the last mark, the
    liquidation price, the range facts it entered on."""
    e = (snap.get("engines") or {}).get(ACCOUNT) or {}
    p = e.get("position") if isinstance(e.get("position"), dict) else None
    if not p:
        return None
    sig = p.get("signal") if isinstance(p.get("signal"), dict) else {}
    meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
    sym, side = p.get("symbol"), L._i(p.get("side")) or 0
    entry, lev = L._f(p.get("entry_price")), L._i(p.get("leverage"))
    mark = L._f((e.get("last_mark") or {}).get(sym)) if isinstance(e.get("last_mark"), dict) else None
    qty = L._f(p.get("qty"))
    ff = (L._f(p.get("funding_paid")) or 0.0) / (qty * entry) if qty and entry else 0.0
    roe = lev * (side * (mark / entry - 1.0) - rt - ff) if mark and entry and lev else None
    stop, tp = L._f(p.get("stop_price")), L._f(p.get("tp_price"))
    move = lambda px: side * (px / entry - 1.0) if px and entry and side else None     # noqa: E731
    return {"key": f"{ACCOUNT}|{sym}|{L._i(p.get('entry_time'))}", "symbol": sym, "coin": coin_ko(sym), "side": side, "leverage": lev,
            "qty": qty, "entry": entry, "entry_time": L._i(p.get("entry_time")), "stop": stop, "stop_move": move(stop),
            "tp": tp, "tp_move": move(tp), "liq": L._f(p.get("liq_price")), "margin": L._f(p.get("margin_initial")) or L._f(p.get("margin")),
            "mark": mark, "roe": roe, "range": meta.get("range") if isinstance(meta.get("range"), dict) else None,
            "strategy_id": sig.get("strategy_id"), "timeframe": sig.get("timeframe")}


def wait_of(snap: dict, now: int) -> Optional[dict]:
    """The pullback the bot waits for now (state ``combo``'s ``range_wait``, else the ``range`` snapshot's ``wait``): the
    coin, side, the level, the signal's close and ATR, until when (and the minutes left), whether it was touched."""
    combo = snap.get("combo") or {}
    w = combo.get("range_wait")
    if "range_wait" in combo and not isinstance(w, dict):
        return None                                      # the bot's own minute state says it waits for nothing
    if not isinstance(w, dict):
        _ts, rs = snap.get("range") or (None, None)
        w = (rs or {}).get("wait") if isinstance(rs, dict) else None
        if not isinstance(w, dict):
            return None
        sym, side = w.get("symbol"), L._i(w.get("side"))
    else:
        s = w.get("signal") if isinstance(w.get("signal"), dict) else {}
        sym, side = s.get("symbol"), L._i(s.get("side"))
    info = w.get("info") if isinstance(w.get("info"), dict) else {}
    until = L._i(w.get("until"))
    return {"symbol": sym, "coin": coin_ko(sym), "side": side, "t0": L._i(w.get("t0")), "until": until,
            "left_ms": max(0, until - now) if until is not None else None, "level": L._f(w.get("level")), "hit": L._i(w.get("hit")),
            "close": L._f(info.get("close")), "atr": L._f(info.get("atr")), "k": L._f(info.get("k")),
            "coin_st": L._i(info.get("coin_st")), "btc_st": L._i(info.get("btc_st"))}


def supertrend_of(snap: dict, now: int) -> Optional[dict]:
    """Each coin's 1h supertrend side on the last closed hour (the ``range`` snapshot; an unreadable one with its why), the
    bot's own 'busy' words and its rules (its own words), and how old the snapshot is."""
    ts, rs = snap.get("range") or (None, None)
    if not isinstance(rs, dict):
        return None
    coins = []
    for sym, v in (rs.get("supertrend") or {}).items():
        if isinstance(v, dict):
            coins.append({"symbol": sym, "coin": coin_ko(sym), "side": None, "error_ko": str(v.get("error") or "못 읽음")})
        else:
            sd = L._i(v)
            coins.append({"symbol": sym, "coin": coin_ko(sym), "side": sd, "ko": ST_KO.get(sd, "모름")})
    return {"at": ts, "st_at": L._i(rs.get("st_at")), "age_ms": now - ts if ts is not None else None, "coins": coins,
            "busy_ko": rs.get("busy") or None, "rules": [str(x) for x in rs.get("rules") or [] if isinstance(x, str)]}


# ---------------------------------------------------------------- the followers
def _live_cell(x: dict, rev: dict, live_by: dict, pt: dict, path: str, bots: list) -> dict:
    """One follower's part of a paper trade: matched (its own result), missed (its own reason), before its move, or the
    bot it followed then."""
    r = x["record"]
    base = {"id": x["id"], "name_ko": x["name_ko"]}
    if r.get("state") != "ok":
        return {**base, "state": "unknown", "reason_ko": r.get("reason_ko")}
    lk = rev.get((LP.norm(path), pt["id"]))
    if lk is not None:
        lt = live_by.get(lk) or {}
        return {**base, "state": "followed", "pnl": lt.get("pnl"), "roe": lt.get("roe"), "exit_reason": lt.get("exit_reason"),
                "exit_ko": L.EXIT_KO.get(lt.get("exit_reason") or "", "청산"), "est": lt.get("est"), "exit_ms": lt.get("exit_ts")}
    if not L.followed_at(x, path, pt.get("entry_time")):
        then = LP.paper_at(x["segs"], pt.get("entry_time"))
        b = next((b for b in bots if LP.same(b["path"], then)), None)
        name = (b or {}).get("short_ko") or L._bot_ko({**x, "paper_path": then})
        if (x.get("switched_ms") or 0) and (pt.get("entry_time") or 0) < (x.get("switched_ms") or 0):
            return {**base, "state": "before", "why_ko": f"이때 {L.josa(x['name_ko'], '은', '는')} {L.josa(name, '을', '를')} 따라갔어요"}
        return {**base, "state": "other", "why_ko": f"이때 {L.josa(x['name_ko'], '은', '는')} {L.josa(name, '을', '를')} 따라갔어요"}
    w = L.why_missed(r, pt, x["follows"])
    return {**base, "state": w["state"], "why_kind": w.get("why_kind"), "why_ko": w.get("why_ko"), "why_text": w.get("why_text")}


def follower_view(x: dict, path: str, snap: dict, plan: Optional[dict], now: int) -> dict:
    """A follower (an executor whose paper database is this bot's now): its state, since when it follows the bot, its
    balance and the change since then, its trades on this bot only (era_trades), today's, its open position (stop from its
    exchange record; the take-profit is its own config's net ROE), its config's plan in a few words, notes and warnings."""
    r, cfg = x["record"], x.get("config") or {}
    since = next((frm for frm, sp in reversed(x.get("segs") or []) if LP.same(sp, path)), None)
    base = {"id": x["id"], "name_ko": x["name_ko"], "since_ms": since, "notes": x.get("notes") or [],
            "config": {k: cfg.get(k) for k in ("state", "path", "reason_ko")}}
    if r.get("state") != "ok":
        return {**base, **{k: r.get(k) for k in ("state", "reason_ko", "reason", "path")}}
    mine = L.era_trades(x, path)
    curve = r.get("curve") or []
    before = [v for t, v in curve if since is not None and (t or 0) <= since]
    eq = ([[since, before[-1]]] if before else []) + [pt for pt in curve if since is None or (pt[0] or 0) > since]
    eq0 = eq[0][1] if eq else None                       # its balance when it moved to this bot (the last one before)
    now_eq = r.get("last_equity")
    pos = r.get("position")
    raw = (read_json(cfg["path"]).get("raw") or {}) if cfg.get("state") == "ok" and cfg.get("path") else {}
    tp = L._f(raw.get("take_profit_roe"))               # its own fixed take-profit and stop (deploy/range_switch.py writes them)
    sr = L._f(raw.get("stop_roe")) if raw.get("stop_from") == "roe" else None
    state = "stopped" if r.get("stale") else "halted" if r.get("halted") else "running"
    return {**base, "state": "ok", "run": state, "run_ko": {"running": "켜짐", "stopped": "기록 멈춤", "halted": "멈춤"}[state],
            "halt_reason": r.get("halt_reason") or "", "seen_ms": r.get("as_of_ms"), "mode": r.get("mode"),
            "balance": now_eq, "start_balance": eq0, "change": now_eq - eq0 if now_eq is not None and eq0 else None,
            "change_pct": now_eq / eq0 - 1 if now_eq is not None and eq0 else None, "curve": eq,
            "record": L.stats(t["pnl"] for t in mine), "today": L.today_of(mine, now, "exit_ts"), "n_other": len(r.get("trades") or []) - len(mine),
            "position": ({**pos, "coin": coin_ko(pos.get("symbol")), "tp_roe": tp, "stop_roe": sr} if pos else None),
            "plan_ko": [w for w in (f"익절 순ROE +{_pct(tp)} (자기 체결가 기준 · 시장가로 닫음)" if tp else None,
                                    f"손절 순ROE −{_pct(sr)} (자기 체결가 기준 · 거래소에 걸어 둠)" if sr else None,
                                    f"크기 = 진입 때 잔고의 {_pct(L._f(cfg.get('margin_frac')))}" if cfg.get("size_from") == "equity" and L._f(cfg.get("margin_frac")) else None)
                        if w],
            "events": (r.get("events") or [])[:WARN_KEEP]}


def trades_view(snap: dict, path: str, fol: list, bots: list, cfg: dict) -> list:
    """The recent closed paper trades (newest first) with each follower's part side by side."""
    revs = {x["id"]: L.rev_pairs(x) for x in fol}
    lives = {x["id"]: {str(t["key"]): t for t in (x["record"].get("trades") or [])} for x in fol if x["record"].get("state") == "ok"}
    out = []
    for t in sorted(snap["trades"].get(ACCOUNT) or [], key=lambda t: (t.get("exit_time") or 0, t.get("id") or 0), reverse=True)[:TRADES_KEEP]:
        out.append({**{k: t.get(k) for k in ("id", "symbol", "side", "entry_time", "exit_time", "exit_reason", "leverage", "pnl", "roe",
                                              "entry_price", "exit_price")},
                    "coin": coin_ko(t.get("symbol")), "reason_ko": L.exit_words(t.get("exit_reason"), cfg, t.get("exit_why")),
                    "win": (t.get("pnl") or 0) > 0, "range": t.get("range"),
                    "live": [_live_cell(x, revs[x["id"]], lives.get(x["id"], {}), t, path, bots) for x in fol]})
    return out


def follow_view(snap: dict, path: str, fol: list, bots: list, now: int) -> list:
    """Per follower, the paper entries since its move to this bot (newest first): followed, missed (its own reason), still
    open together, or waiting for its record; counts and the reasons."""
    out = []
    pos = position_of(snap, 0.0)
    for x in fol:
        r = x["record"]
        if r.get("state") != "ok":
            out.append({"id": x["id"], "name_ko": x["name_ko"], **{k: r.get(k) for k in ("state", "reason_ko", "reason", "path")}, "rows": []})
            continue
        since = next((frm for frm, sp in reversed(x.get("segs") or []) if LP.same(sp, path)), None)
        start = max(v for v in (since, r.get("since_ms")) if v is not None) if (since is not None or r.get("since_ms") is not None) else None
        rev = L.rev_pairs(x)
        live_by = {str(t["key"]): t for t in r.get("trades") or []}
        rows = []
        for t in snap["trades"].get(ACCOUNT) or []:
            if start is not None and (t.get("entry_time") or 0) < start:
                continue
            c = _live_cell(x, rev, live_by, t, path, bots)
            rows.append({"symbol": t["symbol"], "coin": coin_ko(t["symbol"]), "side": t.get("side"), "entry_ms": t.get("entry_time"),
                         "paper_roe": t.get("roe"), "paper_ko": L.exit_words(t.get("exit_reason"), None), "open": False, **c})
        if pos and (start is None or (pos["entry_time"] or 0) >= start):
            lp = r.get("position")
            row = {"symbol": pos["symbol"], "coin": pos["coin"], "side": pos["side"], "entry_ms": pos["entry_time"], "paper_roe": None,
                   "paper_ko": None, "open": True, "id": x["id"], "name_ko": x["name_ko"]}
            if lp and lp.get("key") == pos["key"]:
                row.update(state="open", why_ko="실거래도 같은 포지션을 들고 있어요")
            else:
                w = L.why_missed(r, {"symbol": pos["symbol"], "entry_time": pos["entry_time"]}, x["follows"])
                if w.get("why_kind") is None and pos["entry_time"] and now - pos["entry_time"] < WAIT_MS:
                    row.update(state="waiting", why_ko="방금 들어간 페이퍼 포지션이에요 · 실거래 쪽 기록을 기다리는 중")
                else:
                    row.update(state=w["state"], why_kind=w.get("why_kind"), why_ko=w.get("why_ko"), why_text=w.get("why_text"))
            rows.append(row)
        rows.sort(key=lambda r_: -(r_["entry_ms"] or 0))
        counts: dict = {}
        why: dict = {}
        for rr in rows:
            counts[rr["state"]] = counts.get(rr["state"], 0) + 1
            if rr["state"] == "missed":
                k = rr.get("why_kind") or "none"
                why.setdefault(k, {"kind": k, "ko": rr.get("why_ko"), "n": 0})["n"] += 1
        out.append({"id": x["id"], "name_ko": x["name_ko"], "state": "ok", "since_ms": start, "rows": rows[:FOLLOW_KEEP],
                    "more": max(0, len(rows) - FOLLOW_KEEP), "counts": counts, "why": sorted(why.values(), key=lambda w: -w["n"])})
    return out


def flip_view(snap: dict) -> dict:
    """진짜 방향 vs 동전 방향: the paper account and its coin-flip twin (the same moments, a random side) side by side."""
    rows = []
    for acct, ko in ((ACCOUNT, "진짜 방향 (레인지 봇)"), (FLIP, "동전 방향 (쌍둥이)")):
        ts = snap["trades"].get(acct) or []
        e = (snap.get("engines") or {}).get(acct)
        if e is None and not ts:
            rows.append({"account": acct, "ko": ko, "state": "missing", "reason_ko": f"기록에 {acct} 계좌가 아직 없어요"})
            continue
        st = L.stats(t["pnl"] for t in ts)
        rows.append({"account": acct, "ko": ko, "state": "ok", "n": st["trades"], "wins": st["wins"], "losses": st["losses"],
                     "win_rate": st["win_rate"], "roe_sum": sum(t.get("roe") or 0.0 for t in ts), "pnl": st["pnl"],
                     "wallet": L._f((e or {}).get("wallet"))})
    ok = [r for r in rows if r.get("state") == "ok"]
    gap = ok[0]["win_rate"] - ok[1]["win_rate"] if len(ok) == 2 and ok[0]["win_rate"] is not None and ok[1]["win_rate"] is not None else None
    n = min((r["n"] for r in ok), default=0)
    if len(ok) < 2:
        lead = "두 계좌 기록이 다 있어야 견줘요"
    elif not n:
        lead = "닫힌 거래가 아직 없어요"
    else:
        lead = (f"진짜 방향이 동전보다 승률 {abs(gap) * 100:.0f}%p {'높아요' if gap > 0 else '낮아요' if gap < 0 else '같아요'}" if gap is not None
                else "승률을 아직 견주지 못했어요") + (" · 아직 우연이 커요" if n < 40 else "")
    return {"rows": rows, "gap": gap, "n": n, "lead_ko": lead, "few": n < 40}


def signals_view(snap: dict, now: int) -> dict:
    """The signals of the last 24 hours (newest first) by what became of each (livebots.why_cat / outcome_cat: 되돌림 기다림,
    되돌림 확인, 진입, 추세 확인, 되돌림 안 옴, 한 신호씩, 강제청산 여유, 쉬는 시간 …), counted per reason."""
    oc: dict = {}
    for step, st, reason, sym, data in snap.get("outcomes") or []:
        d = L._j(data)
        sig = d.get("signal") if isinstance(d.get("signal"), dict) else {}
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        ts = L._i(sig.get("ts"))
        if ts is not None:
            oc[(ts + 1, meta.get("member") or sig.get("strategy_id"), sym)] = (st, reason)
    rows, counts = [], {}
    for _id, bc, tf, strat, sym, side, status, data in snap.get("signals") or []:
        d = L._j(data)
        if status in ("FILTERED", "WAITING", "BROKE"):
            cat, ko = L.why_cat(status, d.get("why"))
            stage = "filtered" if status == "FILTERED" else status.lower()
        elif status == "SUBMITTED":
            o = oc.get((L._i(bc), strat, sym))
            if o:
                cat, ko = L.outcome_cat(o[0], o[1])
                stage = "entered" if o[0] == "ENTERED" else "skipped"
            else:
                cat, ko, stage = "pending", "제출됨 (결과 기록 전)", "submitted"
        else:
            cat, ko, stage = "other", str(status), "other"
        rows.append({"t": L._i(bc), "tf": tf, "symbol": sym, "coin": coin_ko(sym), "side": L._i(side), "status": status, "stage": stage,
                     "cat": cat, "ko": ko, "why": d.get("why"), "pulled": bool(d.get("pulled"))})
        c = counts.setdefault(cat, {"cat": cat, "ko": ko, "stage": stage, "n": 0})
        c["n"] += 1
    return {"rows": rows, "counts": sorted(counts.values(), key=lambda c: -c["n"]), "since_ms": now - SIG_SPAN_MS}


# ---------------------------------------------------------------- the answer
def locate(p: dict, now: int) -> tuple:
    """(the 레인지 봇 among the site's paper bots or None, its path, the sources, the bots)."""
    configs, _follows, paper, execs = L.sources(p, now)
    bots = L.paper_bots(p, paper, execs)
    b = next((x for x in bots if x["id"] == "range"), None)
    return b, (b["path"] if b else p.get("range")), execs, bots


def build(p: Optional[dict] = None, more: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """GET /api/v4/livebots/range."""
    p = p or L.paths()
    more = more or L.paths_more()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    b, path, execs, bots = locate(p, now)
    snap = snapshot(path, now) if path else L._missing("-", L.MISSING_KO)
    status = status_of(snap, now)
    ok = status["state"] not in ("off", "error", "missing", "other")
    cfg = snap.get("cfg") if snap.get("state") == "ok" else None
    if cfg is not None and L.range_bot(cfg):
        plan_src = {"source": "db", "path": path, "since_ms": snap.get("run_ts")}
    else:
        server = read_json(L.combo_fallback(more, "range"))
        if server.get("state") == "ok" and L.range_bot(server["raw"]):
            cfg, plan_src = server["raw"], {"source": "server", "path": server["path"],
                                            "reason_ko": "봇이 아직 시작 기록을 남기기 전이라 서버의 설정 파일로 보여 줘요"}
        else:
            repo = read_json(REPO_CONFIG)
            cfg = repo.get("raw") if repo.get("state") == "ok" else None
            plan_src = {"source": "repo", "path": REPO_CONFIG,
                        "reason_ko": "서버에 설정 파일이 아직 없어 저장소의 설정 원본(deploy/combo.range.json)으로 보여 줘요"
                        if server.get("state") == "missing" else "서버 설정 파일을 못 읽어 저장소의 설정 원본으로 보여 줘요"}
    rt = L.round_trip(snap.get("taker_fee") if snap.get("state") == "ok" else None)
    plan = {**plan_of(cfg, snap.get("describe") if plan_src["source"] == "db" else [], rt), **plan_src} if cfg else \
        {**plan_src, "lines": [], "state": "none", "reason_ko": "설정 파일도 저장소의 설정 원본도 읽지 못했어요"}
    fol = [x for x in execs if path and LP.same(x["paper_path"], path)]
    head = {"now_ms": now, "name_ko": NAME_KO, "account": ACCOUNT, "flip_account": FLIP, "status": status, "plan": plan,
            "bot": {"id": "range", "path": path, "short_ko": b["short_ko"], "label_ko": b["label_ko"], "followers": b["followers"]} if b else None,
            "files": {"db": {"state": snap.get("state"), "path": path, "reason_ko": snap.get("reason_ko"), "reason": snap.get("reason")},
                      "config": {"path": L.combo_fallback(more, "range")}},
            "round_trip": rt}
    if not ok:
        return {**head, "wallet": None, "flip_wallet": None, "today": None, "position": None, "wait": None, "supertrend": None,
                "followers": [follower_view(x, path, snap, plan, now) for x in fol], "trades": [], "follow": [], "flip": None,
                "signals": {"rows": [], "counts": []}, "alerts": []}
    run_cfg = cfg if plan_src["source"] == "db" else (snap.get("cfg") or {})
    paper_trades = snap["trades"].get(ACCOUNT) or []
    return {**head,
            "wallet": wallet_of(snap, ACCOUNT, plan), "flip_wallet": wallet_of(snap, FLIP, plan),
            "today": L.today_of(paper_trades, now), "position": position_of(snap, rt), "wait": wait_of(snap, now),
            "supertrend": supertrend_of(snap, now),
            "followers": [follower_view(x, path, snap, plan, now) for x in fol],
            "trades": trades_view(snap, path, fol, bots, run_cfg), "follow": follow_view(snap, path, fol, bots, now),
            "flip": flip_view(snap), "signals": signals_view(snap, now), "alerts": snap.get("alerts") or []}


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/range")
    def get_livebots_range():
        """실거래 › 봇별 › 레인지 봇: the 레인지 봇 paper bot and the executors that follow it: status, the plan in words, the
        wallet, today's trades, the open position with its stop and take-profit, the pullback wait, the trades paper vs
        live, the entries followed or missed and why, real vs coin flip, the balance lines (read-only, 5 s cache)."""
        p, more = L.paths(), L.paths_more()
        return L._cached("range:" + json.dumps([p, more], sort_keys=True), lambda: json_finite(build(p, more)))

    return {"routes": ["/api/v4/livebots/range"]}
