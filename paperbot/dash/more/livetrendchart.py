"""실거래 › 추세 차트 (#/tchart; owners 10/21 "대시보드 화면들 더 멋있게 모든 필요한 화면 부분들 다 추가로 만들어줘"): the
추세판단 봇's (paperbot/trendbot.py) judgments over time and its signals on the price chart, read-only.

    GET /api/v4/livebots/trendchart?symbol=BTCUSDT   (5 s cache per coin; the page asks every 30 s)
        heat     every coin's judgment of every closed 1h bar (the one 30m entries read) and 4h bar (1h entries) of the last
                 72 hours, recomputed bar by bar with the bot's own functions and numbers (``history``: trendjudge
                 vote_arrays + raw_votes over the frame, the hold ``TrendRules.hold``, ADX ``adx_min``, 끝물 ``adx_tired``
                 and falling; tests/test_livetrendchart.py checks it equals ``judge_frame`` of the frame up to each bar).
                 A cell is the time its judgment was in force, from its bar's close to the next close, so an entry minute
                 sits in the cell the bot read. The newest cell is checked against the bot's own record (state ``trend``):
                 ``check`` same / differs
        marks    the paper bot's entries (every coin, 72 h) and the supervisor's exits (감독 청산: JUDGE, TIME); ``before``:
                 opened before the trend bot's start (``since``: the bot before it on this database, 전환 전)
        chart    the chosen coin: its 1h and 4h judgments over 7 days (the band under the candles), its signals of the last
                 3 days by what became of them (signal_log, the bot's own reason), the paper trades (entry, exit, the exit
                 reason in words), the open paper position, the waits now (the pullback level)
The candles themselves come from the site's /api/candles (the page asks for them).

Rules: the running config's numbers (state ``trend`` → ``numbers``, as the bot wrote them), else the config's ``trend``
section (state ``combo_run``), else TrendRules' defaults (said so: ``rules.from``).

Bars for the judgments: Binance USDT-M klines through the trend bot's own ``Klines`` (closed bars only, settled 3 s, its
back-off after a failed fetch, the picture's ``bg`` path), fetched with the bot's own client settings (make_judge: 5 s
timeout, one retry). A coin and timeframe is fetched only once a newer bar has closed, at most once a minute, and at most
FETCH_PER_BUILD fetches per answer (the rest on the next answer: ``pending``, the page asks again in a few seconds);
``FETCH`` is the one function that reaches Binance (a test or a screenshot run puts its own there).

The frame: up to FRAME_BARS (499, one request) closed bars, every judgment read from the same pass. The bot reads the last
300 (trendjudge.KEEP); the indicators settle long before that (EMA, Wilder's averages, the supertrend's bands), so the
longer frame gives the same judgments (the newest one is checked against the bot's record on every answer).

HONESTY: missing / off / error as livetrend.build (CONTRACT §1.6: never a zero for an unread value); a coin whose bars
cannot be read says 못 읽음 with the reason; a bar the bot could not have judged (fewer than trendjudge.MIN_BARS bars, an
empty indicator) is 못 읽음 too; bars not fetched yet are 불러오는 중, never a guess.
"""
from __future__ import annotations

import dataclasses
import json
import math
import sqlite3
import threading
import time
from typing import Callable, Optional

import numpy as np

from ... import trendjudge as TJ
from . import livebots as L
from . import livetrend as LT

ACCOUNT = L.ACCOUNT
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
COINS = L.COINS                              # BTC ETH SOL DOGE LTC BCH (the trend bot's six)
TFS = ("1h", "4h")                           # the judged timeframes
ENTRY_OF = {"1h": "30m", "4h": "1h"}         # judged timeframe -> the entries that read it
HTF_OF = TJ.HTF_OF                           # entry timeframe -> judged timeframe
HEAT_H = 72                                  # the heatmap's hours
BAND_H = 168                                 # the chosen coin's band under the candles (150 1h bars fit)
SIG_SPAN_MS = 3 * DAY                        # the chosen coin's signals
TRADE_SPAN_MS = 7 * DAY                      # the chosen coin's trades
FRAME_BARS = TJ.FETCH                        # bars per frame (one request of trendjudge.FETCH rows)
FETCH_PER_BUILD = 6                          # Binance requests per answer at most (cold start: two answers)
REFETCH_MS = 60_000                          # one coin and timeframe: at most one fetch a minute
HIST_KEEP = 48                               # computed histories kept (12 coin-timeframes, a few bars each)
SIG_KEEP = 300
# the paper engine's exit codes in the owners' short words (screens/livebots-trend.js EXIT_SHORT_KO)
EXIT_SHORT_KO = {"LOCK": "계단 익절", "SL": "손절", "REV": "빠른 청산", "JUDGE": "감독(추세)", "TIME": "감독(시간)", "LIQ": "강제청산",
                 "HALT": "멈춤", "MANUAL": "수동", "END": "끝냄"}
SUP_REASONS = ("JUDGE", "TIME")
# signal_log categories (livebots.why_cat ids) -> what the chart draws
KIND_OF = {"pullback_wait": "wait", "waiting": "wait", "pulled": "touched", "broke": "touched", "nopull": "nopull",
           "trend": "blocked", "spot": "blocked"}
KIND_KO = {"entered": "진입", "touched": "되돌림 닿음 · 진입 안 됨", "wait": "되돌림 기다림", "nopull": "되돌림 안 옴",
           "blocked": "검사에 걸림", "other": "다른 이유로 안 함", "pending": "처리 전", "prev": "전환 전 · 예전 봇 신호"}


# ====================================================================== the judgments, every bar
def history(df, tf: str, rules: TJ.TrendRules, fg=None, pi=None) -> dict:
    """trendjudge.judge_frame for every bar of ``df`` in one pass: element i is the judgment of ``df`` up to bar i (the
    indicators read only bars before and at i). Arrays: bar_close (ms), votes {judge: +1/-1/0}, up, down, raw, dir,
    adx, adx_prev, close, ema20, atr, tired, strong, ok (False where judge_frame raises: an empty value, or fewer than
    trendjudge.MIN_BARS bars, which the bot's frame refuses)."""
    arr = TJ.vote_arrays(df, fg, pi)
    raw = TJ.raw_votes(arr, rules.vote_min).astype(int)
    n = len(raw)
    idx = np.arange(n)
    hold = rules.hold(tf)
    held = idx >= hold - 1
    for k in range(1, hold):
        prev = np.r_[np.zeros(k, dtype=int), raw[:-k]] if n > k else np.zeros(n, dtype=int)
        held &= prev == raw
    direction = np.where((raw != 0) & held, raw, 0)
    adx = np.asarray(arr["adx"], dtype=float)
    adx_prev = np.r_[np.nan, adx[:-1]] if n else adx
    close, ema20, atr = (np.asarray(arr[k], dtype=float) for k in ("close", "ema20", "atr"))
    with np.errstate(invalid="ignore"):
        ok = (np.isfinite(adx) & np.isfinite(adx_prev) & np.isfinite(close) & np.isfinite(ema20) & np.isfinite(atr)
              & (atr > 0) & (idx >= TJ.MIN_BARS - 1))
        tired = (adx > rules.adx_tired) & (adx < adx_prev)
        strong = adx >= rules.adx_min
    m = np.vstack([arr[k] for k in TJ.JUDGES]).astype(int)
    ts = df["ts"].to_numpy()
    opens = (ts.astype("datetime64[ms]").astype(np.int64) if np.issubdtype(ts.dtype, np.datetime64)
             else np.array([int(x.value // 1_000_000) for x in df["ts"]], dtype=np.int64))
    return {"bar_close": opens + TJ.TF_MS[tf], "votes": {k: np.asarray(arr[k], dtype=int) for k in TJ.JUDGES},
            "up": (m > 0).sum(axis=0), "down": (m < 0).sum(axis=0), "raw": raw, "dir": direction, "adx": adx,
            "adx_prev": adx_prev, "close": close, "ema20": ema20, "atr": atr, "tired": tired, "strong": strong, "ok": ok}


def kind(d: int, raw: int, strong: bool, tired: bool, ok: bool) -> str:
    """The cell's look: up / down (a trend the bot takes), "up weak" / "up tired" (힘 약함 / 끝물: no entry), "hold up"
    (3 of 4 up but not held yet: 유지 확인 중), "hold", "na" (못 읽음)."""
    if not ok:
        return "na"
    side = {1: "up", -1: "down"}
    if d:
        return f"{side[d]} tired" if tired else f"{side[d]} weak" if not strong else side[d]
    return f"hold {side[raw]}" if raw in side else "hold"


def _r(x, n=2):
    x = float(x)
    return round(x, n) if math.isfinite(x) else None


def cells_of(hist: dict, t_from: int, tf: str) -> list:
    """The cells in force at or after ``t_from`` (a cell is in force from its bar's close for one bar)."""
    ms = TJ.TF_MS[tf]
    out = []
    for i in np.nonzero(hist["bar_close"] + ms > int(t_from))[0]:
        i = int(i)
        t = int(hist["bar_close"][i])
        if not hist["ok"][i]:
            out.append({"t": t, "kind": "na", "why": "봉이 모자라거나 지표 값이 비어 있음 (봇도 판단 안 함)"})
            continue
        d, raw = int(hist["dir"][i]), int(hist["raw"][i])
        out.append({"t": t, "dir": d, "raw": raw, "up": int(hist["up"][i]), "dn": int(hist["down"][i]),
                    "votes": [int(hist["votes"][k][i]) for k in TJ.JUDGES], "adx": _r(hist["adx"][i]),
                    "adx_prev": _r(hist["adx_prev"][i]),
                    "kind": kind(d, raw, bool(hist["strong"][i]), bool(hist["tired"][i]), True)})
    return out


# ====================================================================== the bars (the trend bot's own Klines)
_client = None


def binance_klines(symbol: str, interval: str, limit: int) -> list:
    """Binance USDT-M klines with the trend bot's own client settings (trendbot.make_judge: 5 s timeout, one retry)."""
    global _client
    if _client is None:
        from ...binance import FAPI, BinanceREST, urllib_fetch
        _client = BinanceREST(base_url=FAPI, fetch=lambda u, h: urllib_fetch(u, h, timeout=5.0), max_retries=1, backoff=0.5)
    return _client.klines(symbol, interval, limit=limit)


FETCH: Callable[[str, str, int], list] = binance_klines     # the one function that reaches Binance (tests replace it)


class Bars:
    """The judged bars of every coin and timeframe (one trendjudge.Klines, the bot's own class: closed and settled bars,
    its back-off) and the judgments computed from them (once per new bar)."""

    def __init__(self, fetch: Optional[Callable] = None, now_ms: Optional[Callable[[], int]] = None):
        self.k = TJ.Klines(fetch or (lambda s, tf, n: FETCH(s, tf, n)), now_ms or (lambda: int(time.time() * 1000)),
                           keep=FRAME_BARS)
        self.tried: dict = {}
        self.err: dict = {}
        self.hist: dict = {}
        self.lock = threading.Lock()

    def frame(self, sym: str, tf: str, now: int, budget: list):
        """(frame or None, {"state": ok / pending / error, "reason_ko", "stale", "fetched"}) of the newest closed bars."""
        ms, key = TJ.TF_MS[tf], (sym, tf)
        asked = int(now) - TJ.SETTLE_MS                           # a bar counts once settled (as the bot's Klines)
        need = asked - asked % ms - ms                            # the open of the newest bar that should be closed
        have = self.k.rows.get(key, [])
        info = {"state": "ok", "stale": False, "fetched": False}
        if (not have or have[-1][0] < need) and budget[0] > 0 and asked - self.tried.get(key, -REFETCH_MS) >= REFETCH_MS:
            self.tried[key] = asked
            budget[0] -= 1
            info["fetched"] = True
            n0 = len(self.k.errors)
            try:
                self.k.frame(sym, tf, asked, bg=True)
            except TJ.TrendError:
                pass                                              # an older frame below; the reason from errors
            if len(self.k.errors) > n0:
                self.err[key] = self.k.errors[-1]
            elif self.k.rows.get(key):
                self.err.pop(key, None)
            del self.k.errors[:]
            have = self.k.rows.get(key, [])
        if not have:
            if key in self.err:
                return None, {**info, "state": "error", "reason_ko": f"바이낸스 봉을 못 받았어요 · 잠시 뒤 다시 받아요 ({self.err[key]})"}
            return None, {**info, "state": "pending", "reason_ko": "봉을 받는 중이에요 (몇 초 뒤 보여요)"}
        try:
            df = self.k.frame(sym, tf, int(have[-1][0]) + ms, bg=True)   # never a fetch: that bar is here
        except TJ.TrendError as exc:
            return None, {**info, "state": "error", "reason_ko": str(exc)}
        if int(have[-1][0]) < need:
            info["stale"] = True
            info["reason_ko"] = ("최근 봉을 아직 못 받았어요" + (f" ({self.err[key]})" if key in self.err else " (곧 다시 받아요)"))
        return df, info

    def history(self, sym: str, tf: str, df, rules: TJ.TrendRules) -> dict:
        key = (sym, tf, int(df["ts"].iloc[-1].value // 1_000_000), len(df), dataclasses.astuple(rules))
        got = self.hist.get(key)
        if got is None:
            fg, pi = TJ.lib()
            got = history(df, tf, rules, fg, pi)
            self.hist[key] = got
            if len(self.hist) > HIST_KEEP:
                for k in list(self.hist)[:len(self.hist) - HIST_KEEP]:
                    self.hist.pop(k, None)
        return got


_bars: Optional[Bars] = None
_bars_lock = threading.Lock()


def bars() -> Bars:
    global _bars
    with _bars_lock:
        if _bars is None:
            _bars = Bars()
        return _bars


# ====================================================================== the paper bot's records
def rules_of(st: Optional[dict], cfg: Optional[dict]) -> tuple:
    """(TrendRules, "bot" / "config" / "default"): the numbers the bot wrote (state trend), else its config's section."""
    known = {f.name for f in dataclasses.fields(TJ.TrendRules)}
    for src, d in (("bot", (st or {}).get("numbers")), ("config", (cfg or {}).get("trend"))):
        if isinstance(d, dict):
            try:
                return TJ.TrendRules.from_dict({k: v for k, v in d.items() if k in known}), src
            except (TJ.TrendError, TypeError, ValueError):
                continue
    return TJ.TrendRules(), "default"


def _position(conn) -> Optional[dict]:
    _ts, acc = LT._state(conn, "accounts")
    p = (((acc or {}).get("engines") or {}).get(ACCOUNT) or {}).get("position") if isinstance(acc, dict) else None
    if not isinstance(p, dict):
        return None
    sig = p.get("signal") if isinstance(p.get("signal"), dict) else {}
    meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
    tr = meta.get("trend") if isinstance(meta.get("trend"), dict) else {}
    tf = sig.get("timeframe")
    return {"symbol": p.get("symbol"), "side": int(p.get("side") or 0), "strategy": sig.get("strategy_id"), "tf": tf,
            "htf": HTF_OF.get(tf), "entry_time": int(p.get("entry_time") or 0), "entry_price": p.get("entry_price"),
            "stop": p.get("stop_price"), "locked": p.get("lock_roe") is not None, "entry_judge": tr.get("judge")}


def _trades(conn, since: int) -> list:
    rows = conn.execute("SELECT id, data FROM trades WHERE account_id = ? AND exit_time >= ? ORDER BY exit_time, id",
                        (ACCOUNT, int(since))).fetchall()
    out = []
    for tid, data in rows:
        t = LT._json(data)
        if not t:
            continue
        ctx = t.get("context") if isinstance(t.get("context"), dict) else {}
        tr = ctx.get("trend") if isinstance(ctx.get("trend"), dict) else {}
        tf = t.get("timeframe")
        out.append({"id": int(tid), "symbol": t.get("symbol"), "side": int(t.get("side") or 0), "strategy": t.get("strategy_id"),
                    "tf": tf, "htf": HTF_OF.get(tf), "entry_time": t.get("entry_time"), "entry_price": t.get("entry_price"),
                    "exit_time": t.get("exit_time"), "exit_price": t.get("exit_price"), "reason": t.get("exit_reason"),
                    "reason_ko": EXIT_SHORT_KO.get(t.get("exit_reason"), L.EXIT_KO.get(t.get("exit_reason"), t.get("exit_reason"))),
                    "why": ctx.get("exit_why"), "roe": t.get("roe"), "pnl": t.get("pnl"), "entry_judge": tr.get("judge")})
    return out


def signals_of(conn, symbol: str, now: int, entries: set, since: Optional[int] = None) -> list:
    """The coin's signals of the last 3 days, oldest first, each with what became of it: entered (its pullback touched and
    the paper entered at that minute), touched (touched, no entry: one position at a time), wait, nopull, blocked (the
    trend judgment or the entry spot checks), other (a pause, the chase block, unread), pending (not decided yet); prev:
    a row of the bot before it on this database (before the trend bot's start ``since``: none of its words are this one's)."""
    rows = conn.execute("SELECT bar_close, timeframe, strategy, symbol, side, status, data FROM signal_log WHERE symbol = ? "
                        "AND bar_close >= ? ORDER BY bar_close DESC, id DESC LIMIT ?",
                        (symbol, int(now) - SIG_SPAN_MS, SIG_KEEP)).fetchall()
    pulled = {}                                                    # (member, tf) -> entry minutes of 되돌림 확인 rows
    for bc, tf, member, _sym, _side, status, data in rows:
        if status == "SUBMITTED" and LT._json(data).get("why") == "되돌림 확인":
            pulled.setdefault((member, tf), []).append(int(bc))
    out = []
    for bc, tf, member, _sym, side, status, data in rows:
        d = LT._json(data)
        why = d.get("why")
        if status == "SUBMITTED" and why == "되돌림 확인":
            continue                                               # the entry row of a pullback: counted at its signal
        tr = d.get("trend") if isinstance(d.get("trend"), dict) else {}
        judge = tr.get("judge")
        jtext = judge.get("text") if isinstance(judge, dict) else judge if isinstance(judge, str) else None
        before = bool(since) and int(bc) < int(since)
        if status == "SUBMITTED":
            cat, ko, kd = "submitted", "처리 전", "pending"
        else:
            cat, ko = L.why_cat(status, why)
            kd = KIND_OF.get(cat, "other")
        if before:
            kd = "prev"
        entry_t = None
        if kd == "touched":
            ms = TJ.TF_MS.get(tf, HOUR)
            mine = [t for t in pulled.get((member, tf), []) if int(bc) < t <= int(bc) + ms + 2 * MIN]
            entry_t = min(mine) if mine else None
            if entry_t is not None and entry_t in entries:
                kd = "entered"
        level = tr.get("level")
        out.append({"t": int(bc), "tf": tf, "member": member, "strategy": d.get("strategy") or str(member).split("@")[0],
                    "side": int(side), "status": status, "cat": cat, "cat_ko": ko, "kind": kd, "kind_ko": KIND_KO[kd],
                    "why": L.why_words(why) if why else None, "judge": jtext,
                    "level": float(level) if isinstance(level, (int, float)) and math.isfinite(level) else None,
                    "entry_time": entry_t, "before": before})
    out.reverse()
    return out


# ====================================================================== the answer
def _check(cell: Optional[dict], bot: Optional[dict]) -> Optional[str]:
    """The newest recomputed cell vs the bot's own judgment of that bar (state trend): same / differs / None (nothing
    to compare: no record, another bar, unread)."""
    if not cell or cell.get("kind") == "na" or not isinstance(bot, dict) or bot.get("error"):
        return None
    if int(bot.get("bar_close") or 0) != int(cell["t"]):
        return None
    votes = bot.get("votes") if isinstance(bot.get("votes"), dict) else {}
    same = (int(bot.get("dir") or 0) == cell["dir"] and int(bot.get("raw") or 0) == cell["raw"]
            and [int(votes.get(k) or 0) for k in TJ.JUDGES] == cell["votes"])
    return "same" if same else "differs"


def heat_rows(b: Bars, st: dict, rules: TJ.TrendRules, now: int, symbol: str, budget: list) -> tuple:
    """(heat, band of the chosen coin, pending): every coin's 1h and 4h cells over HEAT_H hours (the chosen coin first,
    so its chart is never the one waiting), its band over BAND_H."""
    t1 = int(now) - int(now) % HOUR + HOUR
    t0 = t1 - HEAT_H * HOUR
    bot = st.get("coins") or {}
    heat, band, pending = {}, {}, False
    for sym in [symbol] + [c for c in COINS if c != symbol]:
        row = {}
        for tf in TFS:
            df, info = b.frame(sym, tf, now, budget)
            if df is None:
                row[tf] = {"state": info["state"], "reason_ko": info["reason_ko"], "cells": []}
                pending = pending or info["state"] == "pending"
                continue
            h = b.history(sym, tf, df, rules)
            cells = cells_of(h, t0, tf)
            mine = (bot.get(sym) or {}).get(tf)
            row[tf] = {"state": "ok", "cells": cells, "stale": info["stale"], "reason_ko": info.get("reason_ko"),
                       "last": cells[-1]["t"] if cells else None,
                       "check": _check(next((c for c in reversed(cells) if isinstance(mine, dict)
                                             and c["t"] == mine.get("bar_close")), None), mine),
                       "bot": mine.get("text") if isinstance(mine, dict) else None}
            if sym == symbol:
                band[tf] = cells_of(h, t1 - BAND_H * HOUR, tf)
        heat[sym] = row
    return {"t0": t0, "t1": t1, "hours": HEAT_H, "coins": {c: heat[c] for c in COINS}}, band, pending


def build(p: dict, symbol: str = "BTCUSDT", now_ms: Optional[int] = None, b: Optional[Bars] = None) -> dict:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    path = p["paper"]
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return {"state": "missing", "reason_ko": L.MISSING_KO, "now_ms": now, "symbol": symbol}
    except (OSError, sqlite3.Error) as exc:
        return {"state": "error", "reason_ko": "페이퍼 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200],
                "now_ms": now, "symbol": symbol}
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "state" not in tables:
            return {"state": "missing", "reason_ko": L.NO_TABLE_KO, "now_ms": now, "symbol": symbol}
        _rt, run = LT._state(conn, "combo_run")
        cfg = (run or {}).get("config") if isinstance(run, dict) else None
        base = {"now_ms": now, "symbol": symbol, "name": cfg.get("name") if isinstance(cfg, dict) else None}
        if not (isinstance(cfg, dict) and cfg.get("trend") is not None):
            return {**base, "state": "off", "reason_ko": "지금 돌고 있는 페이퍼 봇은 추세판단 봇이 아니에요 (설정에 추세 판단이 없음)"}
        ts, st = LT._state(conn, "trend")
        if st is None:
            return {**base, "state": "missing", "reason_ko": "추세판단 봇이 아직 첫 판단을 기록하지 않았어요 (켠 뒤 1~2분)"}
        rules, rsrc = rules_of(st, cfg)
        since = L._i(st.get("since"))                     # the trend bot's first start: what came before is the bot before it
        trades = _trades(conn, now - max(TRADE_SPAN_MS, (HEAT_H + 4) * HOUR)) if "trades" in tables else []
        pos = _position(conn)
        for t in trades + ([pos] if pos else []):
            t["before"] = bool(since) and t.get("entry_time") is not None and int(t["entry_time"]) < since
        entries = {int(t["entry_time"]) for t in trades if t.get("entry_time") is not None}
        if pos:
            entries.add(pos["entry_time"])
        sigs = signals_of(conn, symbol, now, entries, since) if "signal_log" in tables else []
    except sqlite3.Error as exc:
        return {"state": "error", "reason_ko": "페이퍼 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200],
                "now_ms": now, "symbol": symbol}
    finally:
        conn.close()
    b = b or bars()
    budget = [FETCH_PER_BUILD]
    with b.lock:
        heat, band, pending = heat_rows(b, st, rules, now, symbol, budget)
    t0 = heat["t0"]
    marks = {"entries": [{"symbol": t["symbol"], "t": int(t["entry_time"]), "side": t["side"], "tf": t["tf"], "htf": t["htf"],
                          "strategy": t["strategy"], "open": False, "before": t["before"]} for t in trades
                         if t.get("entry_time") is not None and int(t["entry_time"]) >= t0],
             "sup": [{"symbol": t["symbol"], "t": int(t["exit_time"]), "side": t["side"], "tf": t["tf"], "htf": t["htf"],
                      "reason": t["reason"], "reason_ko": t["reason_ko"], "why": t["why"], "strategy": t["strategy"], "roe": t["roe"],
                      "before": t["before"]}
                     for t in trades if t["reason"] in SUP_REASONS and t.get("exit_time") is not None and int(t["exit_time"]) >= t0]}
    if pos and pos["entry_time"] >= t0:
        marks["entries"].append({"symbol": pos["symbol"], "t": pos["entry_time"], "side": pos["side"], "tf": pos["tf"],
                                 "htf": pos["htf"], "strategy": pos["strategy"], "open": True, "before": pos["before"]})
    waits = [{"member": w.get("member"), "side": w.get("side"), "tf": w.get("tf"), "level": w.get("level"),
              "until": w.get("until"), "t0": w.get("t0"), "judge": w.get("judge")}
             for w in (st.get("waits") or []) if isinstance(w, dict) and w.get("symbol") == symbol
             and int(w.get("until") or 0) > now]
    nums = dataclasses.asdict(rules)
    return {**base, "state": "ok", "ts": ts, "age_ms": now - int(ts), "pending": pending, "since": since,
            "rules": {"from": rsrc, **{k: nums[k] for k in ("vote_min", "adx_min", "adx_tired", "hold_1h", "hold_4h", "time_bars")}},
            "heat": heat, "marks": marks,
            "chart": {"symbol": symbol, "band": band, "signals": sigs,
                      "trades": [t for t in trades if t["symbol"] == symbol],
                      "position": pos if pos and pos["symbol"] == symbol else None, "waits": waits}}


def register(app, ctx) -> dict:
    from fastapi import HTTPException

    from ..app import json_finite

    @app.get("/api/v4/livebots/trendchart")
    def get_livebots_trendchart(symbol: str = "BTCUSDT"):
        """실거래 › 추세 차트: every coin's 1h / 4h judgment of the last 72 h recomputed bar by bar with the bot's own rules,
        the chosen coin's band, signals, trades and waits (5 s cache per coin)."""
        if symbol not in COINS:
            raise HTTPException(400, "unknown symbol")
        p = L.paths()
        return L._cached(f"tchart:{symbol}:" + json.dumps(p, sort_keys=True), lambda: json_finite(build(p, symbol)))

    return {"routes": ["/api/v4/livebots/trendchart"]}
