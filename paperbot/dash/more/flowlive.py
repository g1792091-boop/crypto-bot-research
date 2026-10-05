"""시장 파생 지표판 + 시장 강제청산 보드 (거래 › 시장, 차트): read-only views over the recorders' own files.

    GET /api/v4/flowlive
        Per traded coin, from flow.db (paperbot/flow.py, written hourly by paperbot-flow.timer; 5-minute rows):
        open interest in USDT at the newest row with its 1 h / 24 h change, the global long/short account ratio and
        the top traders' position ratio now vs 24 h earlier, the taker buy/sell ratio of the newest hour (sum of buy
        volume / sum of sell volume), the premium index's newest close and its 24 h mean, and a 24 h hourly series of
        open interest and the global long/short ratio for sparklines. Plain-word hints (``hints``) follow fixed,
        published thresholds (``HINT_RULES``); they describe the crowd, they forecast nothing.
        No file -> {"ready": false}: the screen says 수집 전 (never zero).
    GET /api/v4/flowlive/liq
        Per traded coin, from liq.db (paperbot/liqstream.py, the public forced-order stream): long / short liquidated
        USDT and counts over the last 1 h and 24 h, the biggest single one of the 24 h, and the latest 5 across the
        traded coins. A SELL forced order closes a long, a BUY closes a short (same rule as /api/liq). The stream sends
        at most one order per coin per second, so bursts are undercounted (``note_ko``). No file -> ready false; no row
        for 2 hours -> stale true (the recorder may have stopped: 0 is not known).

Both files sit next to paper3.db (as dash/analysis.py and agents/rooms.py find them). Connections are opened
read-only (``file:...?mode=ro``) per request and closed; answers are cached (flow 60 s, liq 20 s). No Binance call.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Optional

HOUR = 3_600_000
DAY = 24 * HOUR
FLOW_TTL_S = 60.0
LIQ_TTL_S = 20.0
LIQ_STALE_MS = 2 * HOUR
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
# the plain-word hints: (key, Korean words, rule in words). Thresholds are fixed and shown on the screen.
HINT_RULES = {
    "long_crowd": ("롱 쏠림", "전체 계좌 롱/숏 비율 1.5 이상 (계좌의 60% 이상이 롱)"),
    "short_crowd": ("숏 쏠림", "전체 계좌 롱/숏 비율 0.67 이하 (계좌의 60% 이상이 숏)"),
    "oi_jump": ("미결제 급증", "미결제약정 1시간 +3% 이상 또는 24시간 +10% 이상"),
    "oi_drop": ("미결제 급감", "미결제약정 1시간 −3% 이하 또는 24시간 −10% 이하"),
    "taker_buy": ("시장가 매수 우세", "최근 1시간 테이커 매수/매도 1.2 이상"),
    "taker_sell": ("시장가 매도 우세", "최근 1시간 테이커 매수/매도 0.83 이하"),
}


def _ro(path: Optional[str]) -> Optional[sqlite3.Connection]:
    if not path or not os.path.exists(path):
        return None
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        c.execute("PRAGMA query_only = 1")
        return c
    except sqlite3.Error:
        return None


def _chg(now: Optional[float], then: Optional[float]) -> Optional[float]:
    return round(now / then - 1, 5) if now is not None and then else None


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def hints(row: dict) -> list:
    """The plain-word hints of one coin's row (keys of HINT_RULES), in a fixed order."""
    out = []
    ls = row.get("ls_global")
    if ls is not None:
        if ls >= 1.5:
            out.append("long_crowd")
        elif ls <= 0.67:
            out.append("short_crowd")
    a, b = row.get("oi_chg_1h"), row.get("oi_chg_24h")
    if (a is not None and a >= 0.03) or (b is not None and b >= 0.10):
        out.append("oi_jump")
    elif (a is not None and a <= -0.03) or (b is not None and b <= -0.10):
        out.append("oi_drop")
    t = row.get("taker_1h")
    if t is not None:
        if t >= 1.2:
            out.append("taker_buy")
        elif t <= 0.83:
            out.append("taker_sell")
    return out


def _series(c, table: str, col: str, sym: str, hi: int) -> list:
    """[ts, value] of the 24 h up to hi, one point per hour (the last 5-minute row of each hour) plus hi itself."""
    rows = c.execute(f"SELECT ts, {col} FROM {table} WHERE symbol = ? AND ts > ? AND ts <= ? ORDER BY ts",
                     (sym, hi - DAY, hi)).fetchall()
    out, last_h = [], None
    for ts, v in rows:
        if v is None:
            continue
        hr = int(ts) // HOUR
        if out and hr == last_h:
            out[-1] = [int(ts), float(v)]
        else:
            out.append([int(ts), float(v)])
        last_h = hr
    return [[t, _r(v, 6)] for t, v in out]


def _at(c, table: str, col: str, sym: str, ts: int):
    r = c.execute(f"SELECT {col} FROM {table} WHERE symbol = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                  (sym, ts)).fetchone()
    return None if not r or r[0] is None else float(r[0])


def _last(c, table: str, sym: str) -> Optional[int]:
    r = c.execute(f"SELECT MAX(ts) FROM {table} WHERE symbol = ?", (sym,)).fetchone()
    return int(r[0]) if r and r[0] is not None else None


def flow_live(flow_path: Optional[str], now_ms: int, symbols=SYMBOLS) -> dict:
    c = _ro(flow_path)
    rules = {k: {"ko": v[0], "rule": v[1]} for k, v in HINT_RULES.items()}
    if c is None:
        return {"ready": False, "why": "flow.db 없음 (시장 지표 기록기가 아직 돌지 않음)", "hint_rules": rules}
    coins = []
    try:
        for sym in symbols:
            row: dict = {"symbol": sym}
            try:
                t = _last(c, "oi5m", sym)
                if t is not None:
                    now_v = _at(c, "oi5m", "sum_oi_value", sym, t)
                    row.update(ts=t, oi_usd=_r(now_v, 0), oi_chg_1h=_chg(now_v, _at(c, "oi5m", "sum_oi_value", sym, t - HOUR)),
                               oi_chg_24h=_chg(now_v, _at(c, "oi5m", "sum_oi_value", sym, t - DAY)),
                               oi_series=[[a, _r(b, 0)] for a, b in _series(c, "oi5m", "sum_oi_value", sym, t)])
                t2 = _last(c, "ls_global5m", sym)
                if t2 is not None:
                    row.update(ls_global=_r(_at(c, "ls_global5m", "ratio", sym, t2), 3),
                               ls_global_24h=_r(_at(c, "ls_global5m", "ratio", sym, t2 - DAY), 3),
                               long_share=_r(_at(c, "ls_global5m", "long_share", sym, t2), 4),
                               ls_series=[[a, _r(b, 3)] for a, b in _series(c, "ls_global5m", "ratio", sym, t2)])
                    row["ts"] = max(row.get("ts") or 0, t2)
                t3 = _last(c, "ls_top_position5m", sym)
                if t3 is not None:
                    row.update(ls_top=_r(_at(c, "ls_top_position5m", "ratio", sym, t3), 3),
                               ls_top_24h=_r(_at(c, "ls_top_position5m", "ratio", sym, t3 - DAY), 3))
                t4 = _last(c, "taker5m", sym)
                if t4 is not None:
                    r = c.execute("SELECT SUM(buy_vol), SUM(sell_vol) FROM taker5m WHERE symbol = ? AND ts > ? AND ts <= ?",
                                  (sym, t4 - HOUR, t4)).fetchone()
                    row["taker_1h"] = _r(r[0] / r[1], 3) if r and r[0] and r[1] else None
                t5 = _last(c, "premium5m", sym)
                if t5 is not None:
                    row["premium"] = _r(_at(c, "premium5m", "close", sym, t5), 6)
                    r = c.execute("SELECT AVG(close) FROM premium5m WHERE symbol = ? AND ts > ? AND ts <= ?",
                                  (sym, t5 - DAY, t5)).fetchone()
                    row["premium_24h_avg"] = _r(r[0], 6) if r and r[0] is not None else None
            except sqlite3.Error:
                pass
            if row.get("ts"):
                row["age_min"] = max(0, int((now_ms - row["ts"]) // 60_000))
                row["hints"] = hints(row)
            coins.append(row)
    finally:
        c.close()
    stamps = [x["ts"] for x in coins if x.get("ts")]
    return {"ready": bool(stamps), "why": None if stamps else "flow.db에 아직 기록 없음", "as_of": max(stamps) if stamps else None,
            "coins": coins, "hint_rules": rules, "every_ko": "기록기가 1시간마다 받아 옴 (5분 단위 기록)"}


def liq_board(liq_path: Optional[str], now_ms: int, symbols=SYMBOLS, latest_n: int = 5) -> dict:
    c = _ro(liq_path)
    note = "바이낸스는 코인마다 1초에 한 건만 알려 줘서, 몰릴 때는 실제보다 적게 잡힘"
    if c is None:
        return {"ready": False, "why": "liq.db 없음 (강제청산 기록기가 아직 돌지 않음)", "note_ko": note}
    usd = "COALESCE(NULLIF(avg_price, 0), price) * COALESCE(NULLIF(filled_qty, 0), qty)"
    coins, latest = [], []
    try:
        newest = c.execute("SELECT trade_ts FROM liq ORDER BY rowid DESC LIMIT 1").fetchone()
        newest = int(newest[0]) if newest and newest[0] is not None else None
        first = c.execute("SELECT trade_ts FROM liq ORDER BY rowid LIMIT 1").fetchone()
        first = int(first[0]) if first and first[0] is not None else None
        for sym in symbols:
            row = {"symbol": sym}
            for key, span in (("h1", HOUR), ("h24", DAY)):
                d = {"long_usd": 0.0, "short_usd": 0.0, "long_n": 0, "short_n": 0}
                for side, n, s in c.execute(f"SELECT side, COUNT(*), SUM({usd}) FROM liq WHERE symbol = ? AND trade_ts >= ? "
                                            "AND trade_ts <= ? GROUP BY side", (sym, now_ms - span, now_ms)):
                    k = "long" if side == "SELL" else "short"
                    d[f"{k}_usd"] = round(float(s or 0), 2)
                    d[f"{k}_n"] = int(n)
                row[key] = d
            b = c.execute(f"SELECT trade_ts, side, COALESCE(NULLIF(avg_price, 0), price), {usd} FROM liq WHERE symbol = ? "
                          f"AND trade_ts >= ? AND trade_ts <= ? ORDER BY {usd} DESC LIMIT 1",
                          (sym, now_ms - DAY, now_ms)).fetchone()
            row["biggest"] = ({"ts": int(b[0]), "liquidated": "long" if b[1] == "SELL" else "short", "price": b[2],
                               "usd": round(float(b[3] or 0), 2)} if b else None)
            coins.append(row)
            for ts, side, px, u in c.execute(f"SELECT trade_ts, side, COALESCE(NULLIF(avg_price, 0), price), {usd} FROM liq "
                                             "WHERE symbol = ? AND trade_ts <= ? ORDER BY trade_ts DESC LIMIT ?",
                                             (sym, now_ms, latest_n)):
                latest.append({"symbol": sym, "ts": int(ts), "liquidated": "long" if side == "SELL" else "short",
                               "price": px, "usd": round(float(u or 0), 2)})
    except sqlite3.Error as exc:
        return {"ready": False, "why": f"liq.db를 읽지 못함 ({type(exc).__name__})", "note_ko": note}
    finally:
        c.close()
    latest.sort(key=lambda x: -x["ts"])
    stale = newest is None or now_ms - newest > LIQ_STALE_MS
    return {"ready": newest is not None, "stale": stale, "last_record_ts": newest, "since_ts": first,
            "partial_24h": bool(first is not None and first > now_ms - DAY), "coins": coins,
            "latest": latest[:latest_n], "note_ko": note,
            "why": None if newest is not None else "liq.db에 아직 기록 없음"}


def register(app, ctx) -> dict:
    here = os.path.dirname(os.path.abspath(ctx.db))
    cache: dict = {}
    lock = threading.Lock()

    def cached(key: str, ttl: float, fn):
        hit = cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        with lock:
            hit = cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            v = fn()
            cache[key] = (time.time(), v)
            return v

    @app.get("/api/v4/flowlive")
    def get_flowlive():
        """Open interest, long/short ratios, taker flow and premium per traded coin (flow.db, read-only, 60 s)."""
        return cached("flow", FLOW_TTL_S, lambda: flow_live(os.path.join(here, "flow.db"), int(time.time() * 1000)))

    @app.get("/api/v4/flowlive/liq")
    def get_flowlive_liq():
        """Market-wide forced liquidations per traded coin, 1 h and 24 h (liq.db, read-only, 20 s)."""
        return cached("liq", LIQ_TTL_S, lambda: liq_board(os.path.join(here, "liq.db"), int(time.time() * 1000)))

    return {"routes": ["/api/v4/flowlive", "/api/v4/flowlive/liq"]}
