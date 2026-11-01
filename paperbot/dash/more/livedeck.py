"""실거래 › 관제실 (#/deck; owners 2026-11-01: "이런 화면느낌으로 메인화면으로 똑같이 만들어 줄수 있어?" with three
pictures of trading-terminal dashboards): the site's main screen, one answer for every panel. Read-only, from the three
mix bots' own files (paperbot/mixchop.py through dash/more/livemix.py: the 바이비트 봇, the 친구 15분 봇, the 레인지 봇)
and Binance's closed bars. HONESTY: every number is a bot's record or a price; a panel without data says so; nothing is
made up to fill the look (the pictures' decorative panels are drawn from these values only).

    GET /api/v4/livebots/deck

    {now_ms,
     bots:  [{id, name_ko, account_ko, exchange_ko, tf_ko, trend_tf_ko, rules_ko, unit, status {state, ko},
              equity {value, start, ms}, today {n, wins, losses, pnl}, record {n, wins, losses, win_rate, pnl},
              position (livemix.position_view: coin, side, entry, stop, step, next ladder …) | null,
              paper {status, equity, record}, curve [[ms, equity], …] (live: the equity after each exit, from the start),
              pcurve (the paper twin's), rules_since_ms (the first row of the trend bar on 30m bars: the 10-31 night
              rules), parity {n, same, share} (live entries with a paper entry on the same coin and side within 5 min),
              last_close_ms}],
     coins: [{symbol, coin, state, last, chg24 (vs 96 15m bars ago), spark [closes of the last 96 15m bars],
              bars [[t, o, h, l, c], … the last 120 15m bars], hist [the 'ALL + OBV6 MACD' histogram per 15m bar],
              cross [the bar's 0 cross: 1 / -1 / 0], trend30 [the trend bar's 종합 per 30m bar: [t, 1 / -1 / 0], …],
              rows30 {score, six, line, ema, st, four} (the last closed 30m bar's six rows)}],
     grid:  [{symbol, coin, bots: {bot id: {trend, x0, h6, turn, ac, ac_col, side, why, close_ms}}}] (each bot's own
              board row at its last close),
     tape:  [{ts, bot, bot_ko, kind, kind_ko, symbol, coin, side, text, pnl}] (the three live logs' newest rows),
     flow:  [[slot_ms, crosses, entries], …] (the last 48 h by 15m slot: the histogram's 0 crosses the three bots logged,
              their entries),
     totals {equity, start, pnl, today_pnl, open, n, wins, win_rate}}

Each bot also carries ``last_entry`` (its newest entry row: coin, side, price, stop, leverage and the signal it entered on,
for the 진입 카드), its ``ladder`` and ``stop_atr`` (the config's) and the liquidation room the bots use (M.MMR_PCT).

The coins' series come from ``candles`` (dash/app.py fetch_candles on the server: 15m and 30m klines, cached there) and
paperbot/friendtrend.py part 9 (the bots' own formulas), cached COIN_TTL_S; a coin Binance did not answer says so.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Optional

import numpy as np

from ... import friendtrend as FT
from ... import mixchop as M
from . import livebots as L
from . import livemix as MX

ROUTE = "/api/v4/livebots/deck"
BOT_ORDER = ("bybit", "mix", "range")          # the three mix bots (livemix.PROFILES), the screen's order
COINS = ("SOLUSDT", "ETHUSDT", "XRPUSDT", "BCHUSDT", "ZECUSDT", "DOGEUSDT")   # the owners' six (10-31 night)
MIN = 60_000
MIN15, MIN30 = M.MIN15, M.MIN30
DAY = 86_400_000
CHART_N = 120                                   # 15m bars on the chart (30 hours)
SPARK_N = 96                                    # 15m closes on a coin's line (24 hours)
TREND_N = 60                                    # 30m bars of the trend bar's strip (30 hours)
HIST_BARS = 1000                                # bars read for the indicators (they settle long before)
COIN_TTL_S = 60.0
TAPE_N = 40
FLOW_H = 48
PARITY_MS = 5 * MIN
TAPE_KINDS = {"signal": "신호", "entry": "진입", "adopted": "진입 확인", "exit": "청산", "skip": "건너뜀", "ladder": "계단",
              "start": "시작", "entry_failed": "진입 실패", "stop_failed": "손절 실패"}

_coin_lock = threading.Lock()
_coin_cache: dict = {}


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _i(x: Any) -> Optional[int]:
    v = _f(x)
    return int(v) if v is not None else None


# ---------------------------------------------------------------- the coins (Binance bars, the bots' formulas)
def _frame(rows: list) -> tuple:
    """dash/app.py candle rows (``time`` in seconds) -> (open ms, open, high, low, close, volume) arrays, closed bars only
    are the caller's business (the last row is the bar still open: dropped there)."""
    t = np.array([int(r["time"]) * 1000 for r in rows], dtype=np.int64)
    cols = [np.array([float(r[k]) for r in rows]) for k in ("open", "high", "low", "close")]
    v = np.array([float(r.get("volume") or 0.0) for r in rows])
    return (t, *cols, v)


def coin_view(symbol: str, candles: Callable, now: int) -> dict:
    """One coin's panels: its 15m bars (the last one still open is left out), the histogram and its 0 crosses on them,
    and the trend bar's 종합 on the closed 30m bars."""
    out: dict = {"symbol": symbol, "coin": MX.coin_ko(symbol), "state": "ok"}
    try:
        r15 = candles(symbol, "15m", HIST_BARS)
        r30 = candles(symbol, "30m", HIST_BARS)
    except Exception as exc:  # noqa: BLE001  Binance unreachable: said, never guessed
        return {**out, "state": "error", "ko": "바이낸스 봉을 못 읽었어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    t15, o15, h15, l15, c15, v15 = _frame([r for r in r15 if int(r["time"]) * 1000 + MIN15 <= now])
    t30, _o30, h30, l30, c30, v30 = _frame([r for r in r30 if int(r["time"]) * 1000 + MIN30 <= now])
    if len(c15) < 300 or len(c30) < 300:
        return {**out, "state": "short", "ko": "지난 봉이 모자라요"}
    H = FT.h6_pane(h15, l15, c15, v15)
    B = FT.bar_pane(h30, l30, c30, v30)
    k = slice(len(c15) - CHART_N, len(c15))
    last = float(c15[-1])
    base = float(c15[-SPARK_N - 1]) if len(c15) > SPARK_N else None
    hist = [None if not np.isfinite(x) else round(float(x), 3) for x in H["hist"][k]]
    out.update({"last": last, "last_ms": int(t15[-1]) + MIN15, "chg24": (last / base - 1) if base else None,
                "spark": [round(float(x), 8) for x in c15[-SPARK_N:]],
                "bars": [[int(t15[i]), float(o15[i]), float(h15[i]), float(l15[i]), float(c15[i])] for i in range(k.start, k.stop)],
                "hist": hist, "cross": [int(x) for x in H["cross"][k]],
                "trend30": [[int(t30[i]), int(B["trend"][i])] for i in range(len(t30) - TREND_N, len(t30))],
                "rows30": {kk: int(r[-1]) for kk, r in B["rows"].items()}, "n30": [int(B["up"][-1]), int(B["down"][-1]), int(B["side"][-1])]})
    return out


def coins_view(candles: Optional[Callable], now: int) -> list:
    """The six coins, cached COIN_TTL_S (one Binance read a minute for every viewer)."""
    if candles is None:
        return [{"symbol": s, "coin": MX.coin_ko(s), "state": "error", "ko": "가격 읽기가 없는 서버예요"} for s in COINS]
    key = (id(candles), now // int(COIN_TTL_S * 1000))
    with _coin_lock:
        hit = _coin_cache.get("coins")
        if hit is not None and hit[0] == key:
            return hit[1]
    out = [coin_view(s, candles, now) for s in COINS]
    with _coin_lock:
        _coin_cache["coins"] = (key, out)
    return out


# ---------------------------------------------------------------- the bots (their own files)
def _curve(rows: list, start: Optional[float]) -> list:
    """[[ms, equity], …]: the start, then the equity each exit row read (the bot's own numbers, oldest first)."""
    out = []
    st = next((r for r in rows if r.get("kind") == "start"), None)
    if st is not None and _f(st.get("equity")) is not None:
        out.append([_i(st.get("ts")), _f(st.get("equity"))])
    elif start is not None and rows:
        out.append([_i(rows[0].get("ts")), start])
    for r in rows:
        if r.get("kind") == "exit" and _f(r.get("equity")) is not None and _i(r.get("ts")) is not None:
            out.append([_i(r["ts"]), _f(r["equity"])])
    return [p for p in out if p[0] is not None]


def _rules_since(rows: list) -> Optional[int]:
    """The first row the bot wrote on the 10-31 night rules (a signal or a board row read on the 30m trend bar)."""
    for r in rows:
        if r.get("trend_tf") or (isinstance(r.get("why"), dict) and r["why"].get("trend_tf")):
            return _i(r.get("ts"))
    return None


def _parity(live_rows: list, paper_rows: list) -> dict:
    """Live entries the paper twin also made (the same coin and side within PARITY_MS): the two running the same rules."""
    le = [(r.get("symbol"), _i(r.get("side")), _i(r.get("ts"))) for r in live_rows if r.get("kind") in ("entry", "adopted")]
    pe = [(r.get("symbol"), _i(r.get("side")), _i(r.get("ts"))) for r in paper_rows if r.get("kind") == "entry"]
    same = sum(1 for s, sd, t in le if t is not None and any(ps == s and psd == sd and pt is not None and abs(pt - t) <= PARITY_MS
                                                             for ps, psd, pt in pe))
    return {"n": len(le), "same": same, "share": (same / len(le)) if le else None}


def _px(x: Any) -> str:
    v = _f(x)
    return f"{v:.6g}" if v is not None else "?"


def _tape_text(r: dict) -> str:
    k = r.get("kind")
    if k == "signal":
        if r.get("side"):
            return f"{'롱' if r['side'] > 0 else '숏'} 신호 · {r.get('why') or ''}".rstrip(" ·")
        x0 = _i(r.get("x0"))
        if x0:
            return f"히스토그램 0선 {'위로' if x0 > 0 else '아래로'} 돌파 · {r.get('why') or '진입 안 함'}"
        t = _i(r.get("turn"))
        if t:
            return f"OBV {'연한→진한 초록' if t > 0 else '연한→진한 빨강'} · {r.get('why') or '진입 안 함'}"
        return str(r.get("why") or "신호")
    if k in ("entry", "adopted"):
        return f"{'롱' if _i(r.get('side')) == 1 else '숏'} 진입 {_px(r.get('entry'))} · 손절 {_px(r.get('stop'))}"
    if k == "exit":
        return f"{M.EXIT_KO.get(r.get('why'), str(r.get('why') or '청산'))} {_px(r.get('price'))}"
    if k == "ladder":
        return f"계단 {_i(r.get('step')) or ''}단계 · 손절 {_px(r.get('old'))} → {_px(r.get('new'))}"
    if k == "skip":
        return f"건너뜀 · {r.get('why') or ''}".rstrip(" ·")
    return str(r.get("why") or r.get("ko") or TAPE_KINDS.get(k, k or ""))


ENTRY_WHY = ("rule", "trend", "trend_mode", "tf", "trend_tf", "bar", "bar_n", "bar_score", "x0", "h6", "turn", "ac", "ac_col", "stop_pct",
             "ema_rsi", "close", "close_ms")


def last_entry(rows: list) -> Optional[dict]:
    """The bot's newest entry (진입 카드): its coin, side, price, stop, leverage and the signal it entered on (the entry
    row's ``why``: the rule, the trend bar it read, the histogram's cross or the OBV turn and AC bar)."""
    r = next((x for x in reversed(rows) if x.get("kind") in ("entry", "adopted")), None)
    if r is None:
        return None
    why = r.get("why") if isinstance(r.get("why"), dict) else {}
    return {"ts": _i(r.get("ts")), "symbol": r.get("symbol"), "coin": MX.coin_ko(r["symbol"]) if r.get("symbol") else None,
            "side": _i(r.get("side")), "entry": _f(r.get("entry")), "stop": _f(r.get("stop")), "leverage": _i(r.get("leverage")),
            "qty": _f(r.get("qty")), "opened_ms": _i(r.get("opened_ms")), "why": {k: why.get(k) for k in ENTRY_WHY if why.get(k) is not None}}


def bot_view(prof: Any, now: int) -> dict:
    p = MX.paths(bot=prof.id)
    words = MX.live_words(p, prof)
    live = MX.load_bot("live", p["live"], now)
    paper = MX.load_bot("paper", p["paper"], now)
    cfg = live["conf"].get("cfg")
    out = {"id": prof.id, "name_ko": words["name_ko"], "account_ko": prof.account_ko, "exchange_ko": prof.exchange_ko,
           "tf_ko": words["tf_ko"], "trend_tf_ko": words["trend_tf_ko"], "rules_ko": words["rules_ko"],
           "unit": next(u for b, _k, u, _m, _g in prof.bots if b == "live"), "status": live["status"]}
    rows = live["lg"].get("rows") or [] if live["lg"].get("state") == "ok" else []
    prow = paper["lg"].get("rows") or [] if paper["lg"].get("state") == "ok" else []
    if live["status"]["state"] != "off":
        eq = MX.equity_view("live", live)
        d = (live["st"].get("d") or {}) if live["st"].get("state") == "ok" else {}
        ts = MX.trades_of(rows, cfg) if rows else []
        d0 = L.kst_day_start(L.kst_day(now))
        out.update({"equity": {"value": (eq.get("now") or {}).get("value") if isinstance(eq.get("now"), dict) else None,
                               "start": eq.get("start"), "ms": (eq.get("now") or {}).get("ms") if isinstance(eq.get("now"), dict) else None},
                    "today": {k: v for k, v in MX.record([t for t in ts if (t.get("exit_ms") or 0) >= d0]).items()
                              if k in ("n", "wins", "losses", "pnl")},
                    "record": {k: v for k, v in MX.record(ts).items() if k in ("n", "wins", "losses", "win_rate", "pnl", "worst", "best")},
                    "position": MX.position_view("live", d, now, cfg) if live["st"].get("state") == "ok" else None,
                    "curve": _curve(rows, eq.get("start")), "rules_since_ms": _rules_since(rows),
                    "last_close_ms": _i(d.get("last_close_ms")), "last_entry": last_entry(rows),
                    "ladder": dict(cfg.ladder) if cfg is not None and getattr(cfg, "ladder", None) else None,
                    "stop_atr": float(cfg.stop_atr) if cfg is not None and getattr(cfg, "stop_atr", None) else None,
                    "trades": [{k: t.get(k) for k in ("symbol", "coin", "side", "exit_ms", "pnl", "roe", "win", "why_ko")} for t in ts[:12]]})
    if paper["status"]["state"] != "off":
        peq = MX.equity_view("paper", paper)
        pts = MX.trades_of(prow, paper["conf"].get("cfg")) if prow else []
        out["paper"] = {"status": paper["status"],
                        "equity": (peq.get("now") or {}).get("value") if isinstance(peq.get("now"), dict) else None,
                        "start": peq.get("start"), "record": {k: v for k, v in MX.record(pts).items() if k in ("n", "wins", "win_rate", "pnl")}}
        out["pcurve"] = _curve(prow, peq.get("start"))
    if rows and prow:
        out["parity"] = _parity(rows, prow)
    out["_rows"] = rows                                   # (for the tape and the flow; dropped before the answer)
    out["_board"] = ((live["st"].get("d") or {}).get("board") or {}) if live["st"].get("state") == "ok" else {}
    return out


def grid_view(bots: list) -> list:
    """Each coin, each bot's own board row at its last close (the trend it read, the signal it saw)."""
    out = []
    for s in COINS:
        cell = {}
        for b in bots:
            r = (b.get("_board") or {}).get(s)
            if not isinstance(r, dict):
                continue
            rule = next(iter((r.get("rules") or {}).items()), (None, {}))
            cell[b["id"]] = {"trend": _i(r.get("trend")), "x0": _i(r.get("x0")), "h6": _f(r.get("h6")), "turn": _i(r.get("turn")),
                             "ac": _f(r.get("ac")), "ac_col": _i(r.get("ac_col")), "close_ms": _i(r.get("close_ms")),
                             "bar_n": r.get("bar_n"), "side": _i((rule[1] or {}).get("side")) or 0, "why": (rule[1] or {}).get("why") or "",
                             "rule": rule[0]}
        out.append({"symbol": s, "coin": MX.coin_ko(s), "bots": cell})
    return out


def tape_view(bots: list) -> list:
    rows = []
    for b in bots:
        for r in b.get("_rows") or []:
            k = r.get("kind")
            if k not in TAPE_KINDS or (k == "signal" and not (r.get("side") or r.get("x0") or r.get("turn"))):
                continue
            rows.append({"ts": _i(r.get("ts")), "bot": b["id"], "bot_ko": b["name_ko"], "kind": k, "kind_ko": TAPE_KINDS[k],
                         "symbol": r.get("symbol"), "coin": MX.coin_ko(r["symbol"]) if r.get("symbol") else None,
                         "side": _i(r.get("side")), "text": _tape_text(r), "pnl": _f(r.get("pnl")) if k == "exit" else None})
    rows = [r for r in rows if r["ts"] is not None]
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows[:TAPE_N]


def flow_view(bots: list, now: int) -> list:
    """The last FLOW_H hours by 15m slot: the 0 crosses / OBV turns the three bots logged, and their entries."""
    n = FLOW_H * 4
    end = now // MIN15 * MIN15
    slots = {end - (n - 1 - i) * MIN15: [0, 0] for i in range(n)}
    for b in bots:
        for r in b.get("_rows") or []:
            k, t = r.get("kind"), _i(r.get("ts"))
            if t is None:
                continue
            s = (_i(r.get("close_ms")) or t) // MIN15 * MIN15 if k == "signal" else t // MIN15 * MIN15
            if s not in slots:
                continue
            if k == "signal" and (r.get("x0") or r.get("turn")):
                slots[s][0] += 1
            elif k in ("entry", "adopted"):
                slots[s][1] += 1
    return [[s, a, e] for s, (a, e) in sorted(slots.items())]


def totals_view(bots: list) -> dict:
    eqs = [b["equity"]["value"] for b in bots if isinstance(b.get("equity"), dict) and b["equity"].get("value") is not None]
    sts = [b["equity"]["start"] for b in bots if isinstance(b.get("equity"), dict) and b["equity"].get("start") is not None]
    recs = [b.get("record") or {} for b in bots]
    n = sum(int(r.get("n") or 0) for r in recs)
    wins = sum(int(r.get("wins") or 0) for r in recs)
    known = sum(int(r.get("wins") or 0) + int(r.get("losses") or 0) for r in recs)
    tp = [((b.get("today") or {}).get("pnl")) for b in bots if (b.get("today") or {}).get("pnl") is not None]
    return {"equity": sum(eqs) if eqs else None, "start": sum(sts) if sts and len(sts) == len(eqs) else None,
            "pnl": (sum(eqs) - sum(sts)) if eqs and sts and len(sts) == len(eqs) else None, "today_pnl": sum(tp) if tp else None,
            "open": sum(1 for b in bots if isinstance(b.get("position"), dict) and b["position"].get("state") == "ok"),
            "n": n, "wins": wins, "win_rate": wins / known if known else None, "bots": len(eqs)}


def build(candles: Optional[Callable], now_ms: Optional[int] = None) -> dict:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    bots = []
    for bid in BOT_ORDER:
        prof = MX.PROFILES[bid]
        try:
            bots.append(bot_view(prof, now))
        except Exception as exc:  # noqa: BLE001  one bot's broken file never hides the others
            bots.append({"id": bid, "name_ko": prof.name, "account_ko": prof.account_ko, "exchange_ko": prof.exchange_ko,
                         "status": {"state": "error", "ko": "기록을 읽지 못했어요"}, "reason": f"{type(exc).__name__}: {exc}"[:200]})
    out = {"now_ms": now, "mmr": M.MMR_PCT / 100.0, "grid": grid_view(bots), "tape": tape_view(bots), "flow": flow_view(bots, now), "totals": totals_view(bots)}
    out["bots"] = [{k: v for k, v in b.items() if not k.startswith("_")} for b in bots]
    try:
        out["coins"] = coins_view(candles, now)
    except Exception as exc:  # noqa: BLE001
        out["coins"] = [{"symbol": s, "coin": MX.coin_ko(s), "state": "error", "ko": "코인 값을 만들지 못했어요",
                         "reason": f"{type(exc).__name__}: {exc}"[:200]} for s in COINS]
    return out


def register(app, ctx) -> dict:
    from ..app import json_finite
    candles = getattr(ctx, "candles", None)

    @app.get("/api/v4/livebots/deck")                   # (= ROUTE: written out for tests/test_dash_v4.py's route list)
    def get_livebots_deck():
        """실거래 › 관제실: the three mix bots and the six coins in one answer (read-only, 5 s cache; the coins' bars 60 s)."""
        key = "deck:" + json.dumps([MX.paths(bot=b) for b in BOT_ORDER], sort_keys=True)
        return L._cached(key, lambda: json_finite(build(candles)))

    return {"routes": [ROUTE]}
