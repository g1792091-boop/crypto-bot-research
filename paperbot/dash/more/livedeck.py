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
              bars [[t, o, h, l, c], … the last 120 15m bars], hist [the 3합 histogram per 15m bar (owners 11-02: the
              친구 15분 봇's and the 레인지 봇's entry)], cross [its 0 cross on the bar: 1 / -1 / 0], o4side [the 바이비트 봇's
              entry mark per bar: the OBV4 MACD histogram turning green under 0: 1 / red over 0: -1 / 0], o4 (its last
              value), trend30 [the 추세 MACD histogram's side of 0 per 30m bar: [t, 1 / -1 / 0], …], tm30 {hist, macd,
              yellow} (the last closed 30m bar's)}],
     grid:  [{symbol, coin, bots: {bot id: {trend, x0, h3, o4, o4_turn, o4_col, tmacd, tyellow, side, why, close_ms,
              rule, trend_mode}}}] (each bot's own board row at its last close),
     tape:  [{ts, bot, bot_ko, kind, kind_ko, symbol, coin, side, text, pnl}] (the three live logs' newest rows),
     flow:  [[slot_ms, crosses, entries], …] (the last 48 h by 15m slot: the histogram's 0 crosses the three bots logged,
              their entries),
     totals {equity, start, pnl, today_pnl, open, n, wins, win_rate},
     goal   {goal_ko, target, month_days, from_ms, bots [...], all {...}} (goal_view: the owners' monthly ×6 against each
              bot's record this month, the 목표 연구 arithmetic),
     month  {from_ms, days_n, need, days [...], over, green, red, best, worst, loss_run, max_loss_run, worst_trade, dd}
              (month_view: this month's calendar of the three bots' closed trades and the month's risk numbers)}

    GET /api/v4/livebots/deck/px     (owners 11-01: the price now, every 5 s; px_view)

    {now_ms, state, coins {symbol: {last, mark, funding, next_ms}}, missing [symbols]} (Binance futures: the last trade, the
     mark price the exchanges liquidate on, the funding rate and the next funding time; nothing of the bots')

Each bot also carries ``last_entry`` (its newest entry row: coin, side, price, stop, leverage and the signal it entered on,
for the 진입 카드), its ``ladder`` and ``stop_atr`` (the config's) and the liquidation room the bots use (M.MMR_PCT).

The coins' series come from ``candles`` (dash/app.py fetch_candles on the server: 15m and 30m klines, cached there) and
paperbot/friendtrend.py part 10 (the bots' own formulas since 11-02), cached COIN_TTL_S; a coin Binance did not answer says
so.
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
PX_ROUTE = "/api/v4/livebots/deck/px"
PX_TTL_S = 5.0                                    # the price now: one fetch every 5 s, shared by every viewer
_PX_CACHE: dict = {}
_PX_LOCK = threading.Lock()
BOT_ORDER = ("bybit", "mix", "range")          # the mix bots (livemix.PROFILES), the screen's order


def bot_order() -> tuple:
    """BOT_ORDER without a bot switched off for good (livebots.mix_off; owners 11-03: the 바이비트 봇 off, the two WOO X
    Pro accounts trade): the bots 관제실, 회의실 and the 분석팀 read."""
    return tuple(b for b in BOT_ORDER if not L.mix_off(b))
# the coins the two bots trade together (owners 11-03: WOO X Pro 1 BTC · SOL · ZEC · DOGE, WOO X Pro 2 BTC · XRP · BCH · ZEC · DOGE;
# ETH left both); before: the owners' six of 10-31 night (SOL · ETH · XRP · BCH · ZEC · DOGE)
COINS = ("BTCUSDT", "SOLUSDT", "XRPUSDT", "BCHUSDT", "ZECUSDT", "DOGEUSDT")
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
    """One coin's panels: its 15m bars (the last one still open is left out), the 3합 histogram and its 0 crosses and the
    OBV4 MACD histogram's entry marks on them, and the 추세 MACD histogram's side of 0 on the closed 30m bars (owners
    11-02: the three bots' trend)."""
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
    H = FT.h3_pane(o15, h15, l15, c15, v15)
    O = FT.o4_pane(h15, l15, c15, v15)
    T = FT.tmacd_pane(h30, l30, c30, v30)
    k = slice(len(c15) - CHART_N, len(c15))
    last = float(c15[-1])
    base = float(c15[-SPARK_N - 1]) if len(c15) > SPARK_N else None
    hist = [None if not np.isfinite(x) else round(float(x), 3) for x in H["hist"][k]]
    out.update({"last": last, "last_ms": int(t15[-1]) + MIN15, "chg24": (last / base - 1) if base else None,
                "spark": [round(float(x), 8) for x in c15[-SPARK_N:]],
                "bars": [[int(t15[i]), float(o15[i]), float(h15[i]), float(l15[i]), float(c15[i])] for i in range(k.start, k.stop)],
                "hist": hist, "cross": [int(x) for x in H["cross"][k]], "o4side": [int(x) for x in O["side"][k]],
                "o4": _r(O["ac"][-1], 3),
                "trend30": [[int(t30[i]), int(T["trend"][i])] for i in range(len(t30) - TREND_N, len(t30))],
                "tm30": {"hist": _r(T["hist"][-1], 3), "macd": _r(T["macd"][-1], 3), "yellow": bool(T["yellow"][-1])}})
    return out


def _r(x: Any, n: int) -> Optional[float]:
    x = float(x)
    return round(x, n) if np.isfinite(x) else None


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
            return (f"{'3합 ' if r.get('rule') == 'h3x' else ''}히스토그램 0선 {'위로' if x0 > 0 else '아래로'} 돌파 · "
                    f"{r.get('why') or '진입 안 함'}")
        o4 = _i(r.get("o4_turn"))
        if o4:                                          # owners 11-02: the 바이비트 봇's OBV histogram
            return f"OBV 히스토그램 {FT.o4_words(r.get('o4'), o4)} · {r.get('why') or '진입 안 함'}"
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
             "ema_rsi", "close", "close_ms", "tmacd", "tmacd_line", "tyellow", "h3", "o4", "o4_col", "o4_turn")


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
    out["_trades"] = ts if live["status"]["state"] != "off" and rows else []   # (every closed trade: the month view)
    out["_prows"] = prow                                  # (the paper twin's rows: liveroom.py's seats and feed)
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
                             "rule": rule[0], "trend_mode": r.get("trend_mode"), "tmacd": _f(r.get("tmacd")),
                             "tyellow": bool(r.get("tyellow")), "h3": _f(r.get("h3")), "o4": _f(r.get("o4")),
                             "o4_turn": _i(r.get("o4_turn")), "o4_col": _i(r.get("o4_col"))}
        out.append({"symbol": s, "coin": MX.coin_ko(s), "bots": cell})
    return out


def tape_view(bots: list) -> list:
    rows = []
    for b in bots:
        for r in b.get("_rows") or []:
            k = r.get("kind")
            if k not in TAPE_KINDS or (k == "signal" and not (r.get("side") or r.get("x0") or r.get("turn") or r.get("o4_turn"))):
                continue
            rows.append({"ts": _i(r.get("ts")), "bot": b["id"], "bot_ko": b["name_ko"], "kind": k, "kind_ko": TAPE_KINDS[k],
                         "symbol": r.get("symbol"), "coin": MX.coin_ko(r["symbol"]) if r.get("symbol") else None,
                         "side": _i(r.get("side")), "text": _tape_text(r), "pnl": _f(r.get("pnl")) if k == "exit" else None})
    rows = [r for r in rows if r["ts"] is not None]
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows[:TAPE_N]


def flow_view(bots: list, now: int) -> list:
    """The last FLOW_H hours by 15m slot: the 0 crosses / OBV turns / OBV histogram turns (owners 11-02) the three bots
    logged, and their entries."""
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
            if k == "signal" and (r.get("x0") or r.get("turn") or r.get("o4_turn")):
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


# ---------------------------------------------------------------- 목표 페이스 (owners 11-01: "내 1달 목표 수익률 달성을 위해 필요한
# 대시보드 화면 내용들 있으면 추가해도 돼"): the three live bots against the owners' goal (한 달 ×6), with the 목표 연구 arithmetic
# (dash/more/livegoalres.py goal_numbers: the same numbers as each bot's screen), never a forecast.
def goal_view(now: int, names: Optional[dict] = None) -> dict:
    """{goal_ko, target, month_days, from_ms (this KST month's start), bots: [{id, name_ko, state, reason_ko | month
    {from_ms, start_equity, now_equity, mult, path_now, vs_path, days}, need_daily (the daily growth the rest of the 30
    days would need from here), n, win_rate, per_day, pace_mult, need_win, verdict_ko, tone}], all {start_equity,
    now_equity, mult, path_now, vs_path, need_daily} (the bots with this month's numbers, together)}. ``names``: each bot's
    name as its config says it (bot_view's), else the profile's."""
    from . import livegoalres as G
    target = 1 + G._target()
    m0, _md = G.month_from(now)
    out: dict = {"goal_ko": G.GOAL_KO, "target": target, "month_days": G.MONTH_D, "from_ms": m0, "bots": []}

    def need_daily(mult: float, days: float):
        left = G.MONTH_D - days
        return (target / mult) ** (1 / left) - 1 if mult and mult > 0 and left >= 0.5 else None

    s0 = s1 = 0.0
    el = []
    for bid in bot_order():
        prof = MX.PROFILES[bid]
        row = {"id": bid, "name_ko": (names or {}).get(bid) or prof.name}
        try:
            r = G.mix_bot(None, now, bid)
        except Exception as exc:  # noqa: BLE001  one bot's broken file never hides the others
            out["bots"].append({**row, "state": "error", "reason_ko": "목표 숫자를 만들지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        if r.get("state") != "ok":
            out["bots"].append({**row, "state": r.get("state") or "error", "reason_ko": r.get("ko")})
            continue
        acc = next((a for a in r.get("accounts") or [] if a.get("id") == "live"), None)
        if not acc or acc.get("state") != "ok":
            out["bots"].append({**row, "state": "missing", "reason_ko": (acc or {}).get("reason_ko") or "실거래 기록이 아직 없어요"})
            continue
        mo = acc.get("month")
        x = {**row, "state": "ok", "n": acc.get("n"), "win_rate": acc.get("win_rate"), "per_day": acc.get("per_day"),
             "pace_mult": acc.get("pace_mult"), "need_win": acc.get("need_win"), "verdict_ko": acc.get("verdict_ko"),
             "tone": acc.get("tone"), "month": mo}
        if mo:
            x["need_daily"] = need_daily(mo["mult"], mo["days"])
            s0 += mo["start_equity"]
            s1 += mo["now_equity"]
            el.append(mo["days"])
        out["bots"].append(x)
    if s0 > 0 and el:
        days = max(el)
        mult = s1 / s0
        path = target ** (days / G.MONTH_D)
        out["all"] = {"start_equity": s0, "now_equity": s1, "mult": mult, "path_now": path, "vs_path": mult / path - 1,
                      "days": days, "need_daily": need_daily(mult, days)}
    return out


def _eq_at(curve: list, t: int) -> Optional[float]:
    """A bot's equity at ``t`` from its curve (the start, then after each exit): the last point at or before ``t``; the
    start when the bot began after ``t`` (its money that day); None without a curve."""
    if not curve:
        return None
    last = None
    for ms, eq in curve:
        if ms <= t:
            last = eq
    return last if last is not None else curve[0][1]


def month_view(bots: list, now: int, target: Optional[float] = None) -> dict:
    """이번 달 (owners 11-01 "다 해줘": a month calendar beside the goal, and the month's risk): each KST day of this month
    with the three live bots' closed trades that day, from their own records.

    {from_ms, days_n, need (the daily growth ×target in 30 days needs, compounding: target^(1/30) − 1), days: [{d, ms, state
    past | today | future, n, wins, pnl, base (the bots' equity at the day's start), pct (pnl / base)}], over (days with pct
    at or over need), green / red (days that made / lost money), best / worst {d, pct}, loss_run (losing trades in a row
    up to the newest), max_loss_run (this month), worst_trade {pnl, coin, bot_ko, exit_ms}, dd {bot_ko, pct} (the deepest
    fall from a high of one bot's balance this month)}. A day without trades: n 0, pnl 0, pct 0; a future day: no numbers.
    A trade whose P&L the bot could not read (모름) counts in n, never in pnl."""
    from . import livegoalres as G
    t = float(target) if target else 1 + G._target()
    m0, days_n = G.month_from(now)
    today = L.kst_day(now)
    need = t ** (1 / G.MONTH_D) - 1
    live = [b for b in bots if b.get("curve") or b.get("_trades")]
    days = []
    for i in range(days_n):
        ms = m0 + i * L.DAY
        kd = L.kst_day(ms)
        if kd > today:
            days.append({"d": i + 1, "ms": ms, "state": "future"})
            continue
        n = wins = 0
        pnl = 0.0
        for b in live:
            for tr in b.get("_trades") or []:
                ex = tr.get("exit_ms")
                if ex is not None and ms <= ex < ms + L.DAY:
                    n += 1
                    if tr.get("pnl") is not None:
                        pnl += float(tr["pnl"])
                        wins += 1 if tr["pnl"] > 0 else 0
        base = sum(e for e in (_eq_at(b.get("curve") or [], ms) for b in live if (b.get("curve") or [[now + 1]])[0][0] < ms + L.DAY) if e)
        days.append({"d": i + 1, "ms": ms, "state": "today" if kd == today else "past", "n": n, "wins": wins,
                     "pnl": pnl, "base": base or None, "pct": pnl / base if base else None})
    seen = [x for x in days if x["state"] != "future" and x.get("n")]
    out = {"from_ms": m0, "days_n": days_n, "need": need, "target": t, "days": days,
           "over": sum(1 for x in seen if x["pct"] is not None and x["pct"] >= need),
           "green": sum(1 for x in seen if x["pnl"] > 0), "red": sum(1 for x in seen if x["pnl"] < 0)}
    ranked = [x for x in seen if x["pct"] is not None]
    if ranked:
        b_, w_ = max(ranked, key=lambda x: x["pct"]), min(ranked, key=lambda x: x["pct"])
        out["best"] = {"d": b_["d"], "pct": b_["pct"], "pnl": b_["pnl"]}
        out["worst"] = {"d": w_["d"], "pct": w_["pct"], "pnl": w_["pnl"]}
    # the month's risk: losing trades in a row (all three bots, by exit time), the worst trade, the deepest fall of a balance
    trs = sorted(((tr, b.get("name_ko")) for b in live for tr in b.get("_trades") or []
                  if tr.get("exit_ms") is not None and tr["exit_ms"] >= m0 and tr.get("pnl") is not None), key=lambda x: x[0]["exit_ms"])
    run = best_run = 0
    for tr, _n in trs:
        run = run + 1 if tr["pnl"] < 0 else 0
        best_run = max(best_run, run)
    out["loss_run"], out["max_loss_run"], out["trades_n"] = run, best_run, len(trs)
    if trs:
        w, wn = min(trs, key=lambda x: x[0]["pnl"])
        out["worst_trade"] = {"pnl": w["pnl"], "coin": w.get("coin"), "side": w.get("side"), "bot_ko": wn, "exit_ms": w["exit_ms"]}
    dd = None
    for b in live:
        cv = b.get("curve") or []
        pts = [eq for ms, eq in cv if ms >= m0]
        if not pts:
            continue
        peak = _eq_at(cv, m0) if cv[0][0] < m0 else pts[0]
        low = 0.0
        for eq in pts:
            peak = max(peak, eq)
            low = min(low, eq / peak - 1 if peak else 0.0)
        if dd is None or low < dd["pct"]:
            dd = {"bot_ko": b.get("name_ko"), "pct": low}
    out["dd"] = dd
    return out


def fetch_px(symbols=COINS) -> dict:
    """Binance futures now, per coin: {symbol: {last, mark, funding, next_ms}} (ticker/price and premiumIndex, weight 1
    each, the coins in parallel; a coin that did not answer is left out, never a zero)."""
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    def one(sym):
        row: dict = {}
        try:
            with urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}", timeout=4) as r:
                m = json.loads(r.read())
            row.update(mark=float(m["markPrice"]), funding=float(m["lastFundingRate"]), next_ms=int(m["nextFundingTime"]))
        except Exception:  # noqa: BLE001  (a coin missing is shown as the 15m close)
            pass
        try:
            with urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=4) as r:
                row["last"] = float(json.loads(r.read())["price"])
        except Exception:  # noqa: BLE001
            pass
        return sym, row

    with ThreadPoolExecutor(max_workers=max(1, len(symbols))) as ex:
        return {sym: row for sym, row in ex.map(one, symbols) if row}


def px_view(fetch: Optional[Callable] = None, now_ms: Optional[int] = None) -> dict:
    """The six coins' price now (owners 11-01: the 관제실's prices, the open position's P&L and its risk move with it), one
    fetch every PX_TTL_S shared by every viewer: {now_ms, state ok | error, coins {symbol: {last, mark, funding, next_ms}},
    missing [symbols], ko (when nothing came)}."""
    with _PX_LOCK:
        hit = _PX_CACHE.get("px")
        if hit and time.time() - hit[0] < PX_TTL_S:
            return hit[1]
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        try:
            got = (fetch or fetch_px)(COINS) or {}
            err = None
        except Exception as exc:  # noqa: BLE001
            got, err = {}, f"{type(exc).__name__}: {exc}"[:200]
        coins = {}
        for sym in COINS:
            row = got.get(sym) or {}
            keep = {k: (int(v) if k == "next_ms" else float(v)) for k, v in row.items()
                    if k in ("last", "mark", "funding", "next_ms") and v is not None and np.isfinite(float(v))}
            if keep.get("last") or keep.get("mark"):
                coins[sym] = keep
        out = {"now_ms": now, "state": "ok" if coins else "error", "coins": coins, "missing": [x for x in COINS if x not in coins]}
        if not coins:
            out["ko"] = "바이낸스 지금 가격을 못 받았어요 (끝난 15분봉 값으로 보여요)"
            if err:
                out["reason"] = err
        _PX_CACHE["px"] = (time.time(), out)
        return out


def build(candles: Optional[Callable], now_ms: Optional[int] = None) -> dict:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    bots = []
    for bid in bot_order():
        prof = MX.PROFILES[bid]
        try:
            bots.append(bot_view(prof, now))
        except Exception as exc:  # noqa: BLE001  one bot's broken file never hides the others
            bots.append({"id": bid, "name_ko": prof.name, "account_ko": prof.account_ko, "exchange_ko": prof.exchange_ko,
                         "status": {"state": "error", "ko": "기록을 읽지 못했어요"}, "reason": f"{type(exc).__name__}: {exc}"[:200]})
    out = {"now_ms": now, "mmr": M.MMR_PCT / 100.0, "grid": grid_view(bots), "tape": tape_view(bots), "flow": flow_view(bots, now), "totals": totals_view(bots)}
    out["bots"] = [{k: v for k, v in b.items() if not k.startswith("_")} for b in bots]
    try:
        out["goal"] = goal_view(now, {b["id"]: b.get("name_ko") for b in bots})
    except Exception as exc:  # noqa: BLE001  the goal's arithmetic never hides the rest
        out["goal"] = {"state": "error", "ko": "목표 숫자를 만들지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    try:
        out["month"] = month_view(bots, now, (out.get("goal") or {}).get("target"))
    except Exception as exc:  # noqa: BLE001  the calendar never hides the rest
        out["month"] = {"state": "error", "ko": "이번 달 달력을 만들지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
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
        key = "deck:" + json.dumps([MX.paths(bot=b) for b in bot_order()], sort_keys=True)
        return L._cached(key, lambda: json_finite(build(candles)))

    px = getattr(ctx, "px", None)

    @app.get("/api/v4/livebots/deck/px")                # (= PX_ROUTE)
    def get_livebots_deck_px():
        """실거래 › 관제실: the six coins' price now (Binance futures: last, mark, funding; 5 s, shared; prices only)."""
        return json_finite(px_view(px))

    return {"routes": [ROUTE, PX_ROUTE]}
