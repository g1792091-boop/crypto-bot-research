"""The market team's daily bull vs bear debate (owners' choice 2026-10-04, from the friend's GH Coin idea; our own
code). Code only: nothing here places an order or changes an account, and no trade ever follows from a call.

Once a KST day (trigger 'bull_bear', team:market) one coin of the bot's six is debated: the bull (낙관론자) argues for
a rise over the next 24 hours, the bear (비관론자) for a fall, the risk officer weighs both, and the lead (chair) gives a
call in a fixed form, ``{"direction": "상승" | "하락" | "중립", "confidence": 1 | 2 | 3}``. Code records it here with the
reference price (the last closed 5-minute bar of Binance's public klines when the meeting started, no key) and
grades it 24 hours later on the same public data:

- 상승 is right when the coin rose by at least ``THRESHOLD`` (0.5%), 하락 when it fell by at least that much, 중립 when it
  moved less than that either way;
- a call code cannot read (no ``call``, another word, a confidence outside 1-3) is stored as ``unreadable`` and never
  graded; a call without a reference price as ``no_price``; one whose end price cannot be read within
  ``EXPIRE_MS`` after its due time as ``expired``.

``track_record`` sums the graded calls against a coin flip (50%, with the one-sided binomial p) and against "always
상승" on the same days; the debate's packet shows it to the staff, and the Saturday learning meeting, the Sunday
weekly report and the staff board read it too.

The table lives in agents3.db (``committee_calls``, CREATE TABLE IF NOT EXISTS: an existing agents3.db keeps working;
no trial kind and no CHECK constraint of rooms_db changes). Its only writer is the agents tick.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from typing import Any, Callable, Optional

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
KST_MS = 9 * HOUR_MS
FIVE_MIN = 300_000
HORIZON_MS = DAY_MS            # a call is about the next 24 hours
THRESHOLD = 0.005              # a move smaller than 0.5% either way is 'neutral'
EXPIRE_MS = 3 * DAY_MS         # no end price this long after the due time: expired, not graded
DIRECTIONS = {"상승": 1, "하락": -1, "중립": 0}
FAPI = "https://fapi.binance.com"

SCHEMA = """
CREATE TABLE IF NOT EXISTS committee_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    day TEXT NOT NULL,
    round_id INTEGER,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    direction TEXT,
    confidence INTEGER,
    ref_ts INTEGER,
    ref_price REAL,
    due_ts INTEGER,
    end_price REAL,
    move REAL,
    correct INTEGER,
    graded_ts INTEGER,
    data TEXT,
    UNIQUE (day, symbol)
);
CREATE INDEX IF NOT EXISTS committee_calls_status ON committee_calls (status, due_ts);
"""
STATUS_KO = {"open": "채점 대기", "graded": "채점됨", "unreadable": "판정을 읽을 수 없음(채점 안 함)",
             "no_price": "기준 가격 없음(채점 안 함)", "expired": "24시간 뒤 가격을 못 읽음(채점 안 함)"}


def ensure(conn: sqlite3.Connection) -> None:
    """Create the table on agents3.db when it is missing (the tick's connection, the only writer)."""
    conn.executescript(SCHEMA)
    conn.commit()


# ---------------------------------------------------------------- public prices (no key)
def http_get(url: str, timeout: float = 6.0) -> Any:
    """GET a JSON document (Binance public market data; no key, nothing signed)."""
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:      # noqa: S310 (fixed https host)
        return json.loads(r.read())


Getter = Callable[[str], Any]


def klines(get: Optional[Getter], symbol: str, interval: str, start_ms: Optional[int] = None,
           end_ms: Optional[int] = None, limit: int = 500) -> list[list]:
    """Closed klines [open_time, open, high, low, close, ..., close_time] of Binance USD-M futures; [] when the
    data cannot be read (no getter, network error, odd answer)."""
    if get is None:
        return []
    q = f"{FAPI}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={int(limit)}"
    if start_ms is not None:
        q += f"&startTime={int(start_ms)}"
    if end_ms is not None:
        q += f"&endTime={int(end_ms)}"
    try:
        rows = get(q)
        out = [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0), int(r[6])]
               for r in rows if isinstance(r, (list, tuple)) and len(r) >= 7]
    except Exception:  # noqa: BLE001  (no price is a known state, never a crash)
        return []
    # only closed bars: with ``end_ms`` the caller asks for bars opened by then (closed by the time it means), else
    # the forming bar is left out
    if end_ms is None:
        now = int(time.time() * 1000)
        out = [r for r in out if r[6] < now]
    return out


def price_at(get: Optional[Getter], symbol: str, ts_ms: int) -> Optional[tuple[int, float]]:
    """(close time + 1 ms, close) of the last 5-minute bar that closed at or before ``ts_ms``; None if unknown."""
    rows = klines(get, symbol, "5m", end_ms=int(ts_ms) - FIVE_MIN, limit=1)
    if not rows:
        return None
    r = rows[-1]
    if r[6] + 1 > int(ts_ms) or int(ts_ms) - (r[6] + 1) > 30 * 60_000:
        return None                               # not that bar (the exchange answered for another time)
    return r[6] + 1, r[4]


def funding(get: Optional[Getter], symbol: str) -> Optional[dict]:
    """The last funding rate and the mark price (public premiumIndex)."""
    if get is None:
        return None
    try:
        d = get(f"{FAPI}/fapi/v1/premiumIndex?symbol={symbol}")
        return {"last_funding_rate": float(d["lastFundingRate"]), "mark_price": float(d["markPrice"]),
                "next_funding_ms": int(d.get("nextFundingTime") or 0)}
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- calls
def parse_call(raw: Any) -> tuple[Optional[dict], str]:
    """The chair's call, strictly: {"direction": "상승" | "하락" | "중립", "confidence": 1 | 2 | 3}. (call, '') or
    (None, why it cannot be read)."""
    if not isinstance(raw, dict):
        return None, "call이 없거나 객체가 아님"
    d = raw.get("direction")
    d = d.strip() if isinstance(d, str) else d
    if d not in DIRECTIONS:
        return None, f"direction은 상승·하락·중립 중 하나 (받은 값: {str(d)[:20]!r})"
    c = raw.get("confidence")
    if isinstance(c, str) and c.strip().isdigit():
        c = int(c.strip())
    if isinstance(c, bool) or not isinstance(c, int) or not 1 <= c <= 3:
        return None, f"confidence는 1·2·3 중 하나 (받은 값: {str(raw.get('confidence'))[:20]!r})"
    return {"direction": d, "confidence": c}, ""


def judge(direction: str, move: float, threshold: float = THRESHOLD) -> bool:
    if direction == "상승":
        return move >= threshold
    if direction == "하락":
        return move <= -threshold
    return abs(move) < threshold


def record(conn: sqlite3.Connection, *, day: str, symbol: str, round_id: Optional[int], call: Optional[dict],
           why: str, ref: Optional[tuple], now_ms: int, data: Optional[dict] = None) -> Optional[int]:
    """Store the day's call (once per day and coin: a retried meeting never stores a second one). Returns the row
    id, or None when the day's call was already stored."""
    ensure(conn)
    if call is None:
        status = "unreadable"
    elif not ref:
        status = "no_price"
    else:
        status = "open"
    ref_ts, ref_px = (int(ref[0]), float(ref[1])) if ref else (None, None)
    cur = conn.execute(
        "INSERT OR IGNORE INTO committee_calls (ts, day, round_id, symbol, status, direction, confidence, ref_ts, "
        "ref_price, due_ts, data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (int(now_ms), day, round_id, symbol, status, (call or {}).get("direction"), (call or {}).get("confidence"),
         ref_ts, ref_px, None if ref_ts is None else ref_ts + HORIZON_MS,
         json.dumps({**(data or {}), **({"why": why} if why else {})}, ensure_ascii=False)))
    conn.commit()
    return int(cur.lastrowid) if cur.rowcount else None


def _rows(conn: Optional[sqlite3.Connection], sql: str, args: tuple = ()) -> list[dict]:
    if conn is None:
        return []
    try:
        cur = conn.execute(sql, args)
    except sqlite3.Error:                 # no table yet (an agents3.db from before 2026-10-04), unreadable file
        return []
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def grade_due(conn: sqlite3.Connection, now_ms: int, get: Optional[Getter]) -> list[dict]:
    """Grade every open call whose 24 hours are over: the move from the reference price to the close of the last
    5-minute bar at the due time. A price that cannot be read now is tried again on the next tick; after
    ``EXPIRE_MS`` the call is closed as expired (never graded). Returns the rows changed."""
    done = []
    for r in _rows(conn, "SELECT * FROM committee_calls WHERE status = 'open' AND due_ts <= ? ORDER BY id",
                   (int(now_ms),)):
        got = price_at(get, r["symbol"], int(r["due_ts"]))
        if got is None:
            if now_ms - int(r["due_ts"]) > EXPIRE_MS:
                conn.execute("UPDATE committee_calls SET status = 'expired', graded_ts = ? WHERE id = ? "
                             "AND status = 'open'", (int(now_ms), r["id"]))
                conn.commit()
                done.append({**r, "status": "expired"})
            continue
        end = got[1]
        move = end / float(r["ref_price"]) - 1 if r["ref_price"] else 0.0
        ok = judge(r["direction"], move)
        conn.execute("UPDATE committee_calls SET status = 'graded', end_price = ?, move = ?, correct = ?, graded_ts = ? "
                     "WHERE id = ? AND status = 'open'", (end, move, int(ok), int(now_ms), r["id"]))
        conn.commit()
        done.append({**r, "status": "graded", "end_price": end, "move": move, "correct": int(ok)})
    return done


def p_at_least(k: int, n: int, p: float = 0.5) -> Optional[float]:
    """One-sided binomial p: the chance of ``k`` or more right out of ``n`` by coin flips."""
    if n <= 0:
        return None
    return float(sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def _score(rows: list[dict]) -> dict:
    n = len(rows)
    k = sum(1 for r in rows if r.get("correct"))
    up = sum(1 for r in rows if judge("상승", float(r.get("move") or 0.0)))
    return {"graded": n, "correct": k, "hit_rate": round(k / n, 3) if n else None,
            "coin_flip_rate": 0.5, "p_vs_coin_flip": None if not n else round(p_at_least(k, n), 4),
            "always_up_correct": up, "always_up_rate": round(up / n, 3) if n else None}


def track_record(conn: Optional[sqlite3.Connection], symbol: Optional[str] = None, recent: int = 10) -> dict:
    """The graded calls (all, or one coin's) against a coin flip and against "always 상승" on the same days, by
    confidence and by coin, the open and ungraded counts, and the latest calls."""
    where, args = "", ()
    if symbol:
        where, args = " WHERE symbol = ?", (symbol,)
    rows = _rows(conn, f"SELECT * FROM committee_calls{where} ORDER BY id", args)
    graded = [r for r in rows if r["status"] == "graded"]
    out = {"calls": len(rows), **_score(graded),
           "open": sum(r["status"] == "open" for r in rows),
           "ungraded": {s: sum(r["status"] == s for r in rows) for s in ("unreadable", "no_price", "expired")
                        if any(r["status"] == s for r in rows)},
           "by_confidence": {str(c): _score([r for r in graded if r["confidence"] == c]) for c in (1, 2, 3)
                             if any(r["confidence"] == c for r in graded)},
           "recent": [{"day": r["day"], "coin": r["symbol"].replace("USDT", ""), "direction": r["direction"],
                       "confidence": r["confidence"], "status": r["status"],
                       "move": None if r["move"] is None else round(float(r["move"]), 4),
                       "correct": None if r["correct"] is None else bool(r["correct"])} for r in rows[-recent:][::-1]]}
    if not symbol:
        out["by_coin"] = {s.replace("USDT", ""): _score([r for r in graded if r["symbol"] == s])
                          for s in sorted({r["symbol"] for r in graded})}
    out["rule"] = (f"24시간 뒤 종가(바이낸스 공개 5분봉)로 코드가 채점: 상승은 +{THRESHOLD * 100:.1f}% 이상, 하락은 "
                   f"-{THRESHOLD * 100:.1f}% 이하, 중립은 그 사이일 때 맞음. 동전 던지기는 50%, '늘 상승'은 같은 날들에 "
                   "늘 상승이라고 했을 때의 적중률. 판정은 기록·채점만 하고 어떤 거래로도 이어지지 않음")
    return out


def week_summary(conn: Optional[sqlite3.Connection], since_ms: int, until_ms: int) -> Optional[dict]:
    """The calls graded in [since, until) and the whole record (for the weekly report). None before the first
    call."""
    rows = _rows(conn, "SELECT * FROM committee_calls ORDER BY id")
    if not rows:
        return None
    week = [r for r in rows if r["status"] == "graded" and since_ms <= int(r["graded_ts"] or 0) < until_ms]
    return {"week": _score(week), "all": _score([r for r in rows if r["status"] == "graded"]),
            "calls_week": sum(1 for r in rows if since_ms <= int(r["ts"]) < until_ms)}


# ---------------------------------------------------------------- the debate's packet (code numbers only)
def _ro(path: Optional[str]) -> Optional[sqlite3.Connection]:
    if not path or not os.path.exists(path):
        return None
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        c.execute("PRAGMA query_only = 1")
        return c
    except sqlite3.Error:
        return None


def _ret(rows: list[list], hours: int) -> Optional[float]:
    if len(rows) <= hours:
        return None
    a, b = rows[-1 - hours][4], rows[-1][4]
    return round(b / a - 1, 5) if a else None


def flow_view(flow_path: Optional[str], symbol: str, now_ms: int) -> Optional[dict]:
    """Open interest, the global long/short account ratio and taker buy/sell of the last day (flow.db, written
    hourly by paperbot.flow; read-only). None without the file."""
    c = _ro(flow_path)
    if c is None:
        return None
    out: dict = {}
    try:
        def last_and_day_ago(table: str, col: str) -> tuple:
            a = c.execute(f"SELECT ts, {col} FROM {table} WHERE symbol = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                          (symbol, now_ms)).fetchone()
            b = c.execute(f"SELECT {col} FROM {table} WHERE symbol = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                          (symbol, now_ms - DAY_MS)).fetchone()
            return a, b
        a, b = last_and_day_ago("oi5m", "sum_oi_value")
        if a and a[1] is not None:
            out["open_interest_usd"] = round(float(a[1]), 0)
            out["open_interest_change_24h"] = round(float(a[1]) / float(b[0]) - 1, 4) if b and b[0] else None
            out["as_of"] = int(a[0])
        a, b = last_and_day_ago("ls_global5m", "ratio")
        if a and a[1] is not None:
            out["long_short_ratio"] = round(float(a[1]), 3)
            out["long_short_ratio_24h_ago"] = None if not b or b[0] is None else round(float(b[0]), 3)
        r = c.execute("SELECT SUM(buy_vol), SUM(sell_vol) FROM taker5m WHERE symbol = ? AND ts > ? AND ts <= ?",
                      (symbol, now_ms - DAY_MS, now_ms)).fetchone()
        if r and r[0] and r[1]:
            out["taker_buy_sell_24h"] = round(float(r[0]) / float(r[1]), 3)
    except sqlite3.Error:
        pass
    finally:
        c.close()
    return out or None


def liq_view(liq_path: Optional[str], symbol: str, since_ms: int, until_ms: int) -> Optional[dict]:
    """Liquidations Binance published for the coin in [since, until) (liq.db, paperbot.liqstream; read-only): the
    stream sends at most one per symbol per second, so this undercounts bursts. SELL = longs liquidated."""
    c = _ro(liq_path)
    if c is None:
        return None
    try:
        rows = c.execute("SELECT side, COUNT(*), SUM(COALESCE(filled_qty, qty) * COALESCE(avg_price, price)) FROM liq "
                         "WHERE symbol = ? AND trade_ts >= ? AND trade_ts < ? GROUP BY side",
                         (symbol, since_ms, until_ms)).fetchall()
    except sqlite3.Error:
        return None
    finally:
        c.close()
    out = {"longs_liquidated": 0, "longs_usd": 0.0, "shorts_liquidated": 0, "shorts_usd": 0.0}
    for side, n, usd in rows:
        k = "longs" if side == "SELL" else "shorts"
        out[f"{k}_liquidated"] += int(n)
        out[f"{k}_usd"] += round(float(usd or 0.0), 0)
    return out


def our_view(paper_ro: Optional[sqlite3.Connection], symbol: str, now_ms: int, price: Optional[float]) -> dict:
    """Our strategy accounts on the coin: open positions now (long/short, margin, unrealized P&L at ``price``
    before exit fees) and their closed trades of the last 7 days (by side and timeframe)."""
    out: dict = {"open": {"long": 0, "short": 0, "margin": 0.0, "upnl": 0.0}, "last_7d": {}}
    if paper_ro is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        kinds = dict(paper_ro.execute("SELECT account_id, kind FROM accounts").fetchall())
        r = paper_ro.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        eng = (json.loads(r[0]) or {}).get("engines", {}) if r else {}
        for aid, e in eng.items():
            p = (e or {}).get("position")
            if kinds.get(aid) != "strategy" or not p or p.get("symbol") != symbol:
                continue
            side = int(p.get("side") or 0)
            out["open"]["long" if side > 0 else "short"] += 1
            out["open"]["margin"] += float(p.get("margin") or 0)
            if price:
                out["open"]["upnl"] += side * float(p.get("qty") or 0) * (price - float(p.get("entry_price") or price))
        rows = paper_ro.execute("SELECT t.pnl, t.roe, t.data, a.timeframe FROM trades t JOIN accounts a ON "
                                "a.account_id = t.account_id WHERE a.kind = 'strategy' AND t.symbol = ? AND "
                                "t.exit_time >= ?", (symbol, now_ms - 7 * DAY_MS)).fetchall()
    except (sqlite3.Error, ValueError, TypeError) as exc:
        out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
        return out
    out["open"]["margin"] = round(out["open"]["margin"], 2)
    out["open"]["upnl"] = round(out["open"]["upnl"], 2)

    def cell(rs: list) -> dict:
        n = len(rs)
        w = sum(1 for r in rs if r[0] > 0)
        return {"trades": n, "win_rate": round(w / n, 3) if n else None, "pnl": round(sum(r[0] for r in rs), 2),
                "mean_roe": round(sum(r[1] for r in rs) / n, 4) if n else None}
    sides: dict = {}
    tfs: dict = {}
    for r in rows:
        try:
            side = "롱" if int(json.loads(r[2]).get("side") or 0) > 0 else "숏"
        except (TypeError, ValueError):
            side = "?"
        sides.setdefault(side, []).append(r)
        tfs.setdefault(r[3], []).append(r)
    out["last_7d"] = {"all": cell(list(rows)), "by_side": {k: cell(v) for k, v in sides.items()},
                      "by_timeframe": {k: cell(v) for k, v in sorted(tfs.items())}}
    return out


def coin_packet(paper_ro: Optional[sqlite3.Connection], agents_conn: Optional[sqlite3.Connection], symbol: str,
                now_ms: int, get: Optional[Getter], market: Optional[dict] = None, flow_path: Optional[str] = None,
                liq_path: Optional[str] = None) -> dict:
    """Everything the debate may use, computed by code: the reference price, returns over 1h-7d, the 7-day range,
    the signal log's regime per timeframe (``market``: rooms._market of the board), funding, open interest and the
    long/short ratio (flow.db), liquidations (liq.db), our accounts on the coin, and the debate's own track record."""
    ref = price_at(get, symbol, now_ms)
    h1 = klines(get, symbol, "1h", end_ms=now_ms - HOUR_MS, limit=170)
    price = ref[1] if ref else (h1[-1][4] if h1 else None)
    ret = {k: _ret(h1, n) for k, n in (("1h", 1), ("4h", 4), ("24h", 24), ("3d", 72), ("7d", 168))}
    wk = h1[-168:] if h1 else []
    rng = None
    if wk and price:
        hi, lo = max(r[2] for r in wk), min(r[3] for r in wk)
        rng = {"high_7d": hi, "low_7d": lo, "from_high": round(price / hi - 1, 4), "from_low": round(price / lo - 1, 4)}
    day = h1[-24:] if h1 else []
    vol = None
    if len(day) >= 2:
        vol = {"range_24h": round(max(r[2] for r in day) / min(r[3] for r in day) - 1, 4),
               "volume_24h_vs_7d_avg": (round(sum(r[5] for r in day) / (sum(r[5] for r in wk) / max(1, len(wk) / 24)), 3)
                                        if wk and sum(r[5] for r in wk) else None)}
    return {"symbol": symbol, "coin": symbol.replace("USDT", ""),
            "reference": {"ts": ref[0], "price": ref[1]} if ref else None,
            "price": price, "returns": ret, "range_7d": rng, "volatility": vol,
            "regime": (market or {}).get(symbol), "funding": funding(get, symbol),
            "flow": flow_view(flow_path, symbol, now_ms), "liquidations_24h": liq_view(liq_path, symbol,
                                                                                       now_ms - DAY_MS, now_ms),
            "ours": our_view(paper_ro, symbol, now_ms, price),
            "track_record": track_record(agents_conn),
            "track_record_coin": track_record(agents_conn, symbol, recent=5),
            "rules": {"horizon_hours": HORIZON_MS // HOUR_MS, "threshold": THRESHOLD,
                      "call_format": {"direction": "상승 | 하락 | 중립", "confidence": "1 | 2 | 3"}},
            "note": ("코드 계산: 기준 가격은 바이낸스 공개 5분봉 종가, 수익률은 1시간봉 종가 기준(0.01 = 1%), regime은 신호 기록의 "
                     "장세 판정, flow는 미결제약정·롱숏 비율(없으면 null = 모름). 이 토론의 판정은 기록·채점만 하고 어떤 주문·"
                     "계좌 변경으로도 이어지지 않음")}
