"""거래 다시보기 (실거래 › 다시보기, ``#/livebots/replay?id=<paper trade id>``; owners 10/19 "D2"): one closed trade of the
live setup replayed on the 1-minute bars it was stepped on. Read-only.

    GET /api/v4/livebots/replay              the paper account's closed trades, newest first (``offset``, ``limit`` at most
                                             500), each with what each executor did with it and its own result (5 s cache)
    GET /api/v4/livebots/replay/{trade_id}   one trade: the bars from 30 minutes before the entry to 30 minutes after the
                                             exit, the stop path and the ladder locks rebuilt minute by minute, the exit,
                                             each executor's paired trade (a finished answer is cached 10 minutes)

Where from (all read-only, the 실거래 tab's own paths):
- the trades: ``COMBO@mix`` in the paper bot's live-ac.db (``PAPERBOT_LIVE_PAPER_DB``; models.TradeRecord in trades.data);
  its ENTERED outcome of the entry minute (did the fill use the reference price), its run's ``combo_run`` (taker fee,
  the ladder of the config it runs);
- the executors' paired trades: dash/more/livebots.py ``sources`` and ``match`` (same coin and side, the paper entry
  within 5 minutes, closest pairs first), so this tab pairs exactly as every other 실거래 tab; a paper trade an executor
  did not follow carries the executor's own reason (``why_missed``);
- the bars: the rule bot's paper3.db ``live_bars`` (``PAPERBOT_LIVE_RULE_DB``, /var/lib/paperbot/paper3.db; never
  pruned), the very 1-minute bars the combined bot steps on (paperbot/combo.py ``read_paper``).

The stop path is rebuilt with the engine's own pure functions (paperbot/ladder.py ``net_roe``, ``roe_price``, ``tighten``;
the combined bot's ladder paperbot/ladder2.py ``ComboLadder.lock_for``, either form) in the order of paperbot/engine.py
``PaperEngine.step`` / ``_handle_exit`` / ``_raise_lock``, one minute at a time (``rebuild``):
  0. ``REV`` (빠른 청산, ComboEngine.step): at the open of the recorded minute, before anything else, at the open with
     slippage;
  1. funding at the open of the minute (the funding fraction of the ladder moves; see below);
  2. the best price so far takes the bar's high (long) / low (short), the entry bar included;
  3. not on the entry bar: the mark open beyond the liquidation price = LIQ at the open; the open beyond the stop = the
     stop filled at the open (slippage against);
  4. the bar's low (long) / high (short) reaching the stop = filled at the stop (slippage against) at the bar's close
     time; else the mark beyond the liquidation price = LIQ; a fill that would lose more than the margin = LIQ;
  5. else the lock: best net ROE -> ``lock_for`` -> a higher lock moves the stop to ``roe_price`` (``tighten``), from the
     next minute; skipped on an entry bar filled at the reference price (the ENTERED signal carried ``ref_price``).
The costs are the trade's own: round trip = 2 x (taker fee + slippage) (config.Settings.round_trip_cost) with the taker
fee the record's fees imply (entry and exit at the taker rate; the run's ``combo_run.taker_fee`` when within 1 % of it,
else rounded to 8 decimals), else the run's; the ladder is the run's config. Funding is not recorded per payment: the trade's total funding over its entry notional is paid at the first
8-hour funding time (UTC 00 / 08 / 16) the position held over (split evenly over several; with none, from the minute
after the entry), and the answer says so whenever the trade paid any.

추세판단 봇 (owners 10-21, livebots.trend_bot): both answers carry ``trend_bot`` and each trade ``prev`` (entered before
its start: the bot before it's, 전환 전); its close of such a position at its first minute (SWITCH, 전환 전 포지션 정리) and
its supervisor's closes (JUDGE, TIME) are not rebuilt, like a kill's: their minute is the record's, the locks up to it are
checked.

Honesty: the record is what the page shows as the result (entry, exit, net ROE, money); the rebuilt path is drawn on it.
When the rebuilt exit or last lock differs from the record (reason, time, price beyond float noise, lock, stop) the answer
carries ``check.state = "differs"`` with both values, never hidden. A trade whose bars are not there is not rebuilt
(``unchecked`` with the reason). Bars: none in the window = ``bars.state`` "none" (1분봉 없음), the rule bot's file not
there = "missing" (수집 전), unreadable = "error" (못 읽음 + why); never an invented candle (a 5-minute bar is made only
of the minutes that exist). A trade held longer than 12 hours is shown on 5-minute bars, longer than 5 days on 1-hour
bars (the lock path is still rebuilt on the 1-minute bars); the answer says so.

Times are UTC ms, ratios are ratios (0.1 = 10 %), money is the paper's USDT (the executors': their exchange's USDT).
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from . import livebots as L

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
PAD_MS = 30 * MIN                       # bars shown before the entry and after the exit
FUND_MS = 8 * HOUR                      # Binance USD-M funding times: UTC 00 / 08 / 16
# (longest hold shown on it, display timeframe, its length): 1m up to 12 hours, then 5m up to 5 days, then 1h
TIERS = ((12 * HOUR, "1m", MIN), (5 * DAY, "5m", 5 * MIN), (None, "1h", HOUR))
TF_KO = {"1m": "1분봉", "5m": "5분봉", "1h": "1시간봉"}
LIST_MAX = 500
LIST_DEFAULT = 200
PRICE_TOL = 1e-9                        # relative: a price this close is the same number (float noise, never rounding)
ROE_TOL = 1e-9
DONE_TTL_S = 600.0                      # a finished answer (all bars in, every executor settled)
LIVE_TTL_S = 5.0
CACHE_MAX = 64
ACCOUNT = L.ACCOUNT
EXT_REASONS = ("MANUAL", "HALT", "END")  # closes from outside the bars (a kill, a halt): their minute is the record's
# the 추세판단 봇's close of the position the bot before it left (owners 10-21 night: at its first minute) is not one the
# bars decide either: its minute is the record's, the locks up to it are still checked
SWITCH_REASONS = ("SWITCH",)
# nor are its supervisor's closes (JUDGE: the higher bar's judgment turned; TIME: no first lock within its bars): the
# rebuild knows the stop and the ladder only
SUP_REASONS = ("JUDGE", "TIME")
OUTSIDE_KO = "봇 밖의 이유(수동·멈춤)로 닫혀 청산 자체는 다시 계산하지 않았어요. 그때까지의 잠금만 맞춰 봤어요"
SWITCH_KO = "새 봇(추세판단 봇)이 켜지며 예전 봇의 포지션을 닫은 거래(전환 전 포지션 정리)라 청산 자체는 다시 계산하지 않았어요. 그때까지의 잠금만 맞춰 봤어요"
SUP_KO = "감독 청산(추세 판단·시간 정리)은 1분봉이 아니라 추세판단 봇의 감독이 정해서 청산 자체는 다시 계산하지 않았어요. 그때까지의 잠금만 맞춰 봤어요"
# the same TIME code in a bot with a hold limit and no supervisor (owners 10-23: the 'VWAP 개선판', combo max_hold_bars):
# the time decided it, not the bars
HOLD_KO = ("보유 한도({n}봉)에 닿아 시장가로 정리한 거래예요. 1분봉이 아니라 시간이 정한 청산이라 청산 자체는 다시 계산하지 않았어요. "
           "그때까지의 잠금만 맞춰 봤어요")


def sup_ko(reason: Optional[str], cfg: Optional[dict] = None) -> str:
    """Why a TIME / JUDGE close is not rebuilt, by the bot: the trend bot's supervisor (SUP_KO) or a hold limit (HOLD_KO)."""
    if reason == "TIME" and L.hold_bot(cfg):
        return HOLD_KO.format(n=(cfg or {}).get("max_hold_bars"))
    return SUP_KO
RULE_MISSING_KO = "규칙봇 1분봉 파일이 아직 없어요 (PAPERBOT_LIVE_RULE_DB 경로를 확인해 주세요)"
RULE_NO_TABLE_KO = "규칙봇 파일은 있지만 1분봉 표(live_bars)가 아직 없어요"
NO_BARS_KO = "이 거래 시간의 1분봉이 규칙봇 기록에 없어요"
EXIT_KO = L.EXIT_KO
SHORT = {"bybit": "B", "mexc": "W", "paper": "P"}            # the second slot runs WOO X Pro (owners 10-20)

_lock = threading.Lock()
_one: "OrderedDict[str, tuple]" = OrderedDict()


# ---------------------------------------------------------------- the paper trade
def _trade(r: tuple) -> dict:
    """A trades row as livebots reads it (``_paper_trade``) plus what the replay needs from the record."""
    out = L._paper_trade(r)
    d = L._j(r[9])
    out.update(mfe_price=L._f(d.get("mfe_price")), mae_price=L._f(d.get("mae_price")), signal_ts=L._i(d.get("signal_ts")),
               score=L._f(d.get("score")), tier=d.get("tier"), price_move=L._f(d.get("price_move")))
    return out


def read_trade(path: str, trade_id: int, account: str = ACCOUNT) -> dict:
    """One snapshot of live-ac.db: the trade (None when this account has no such id), its run (``combo_run``) and the
    ENTERED outcome of its entry minute (``ref``: True when the signal carried ``ref_price``, False when it did not, None
    when no outcome was found)."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if not {"state", "trades"} <= tables:
            return L._missing(path, L.NO_TABLE_KO)
        r = conn.execute("SELECT id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data FROM trades "
                         "WHERE id = ? AND account_id = ?", (int(trade_id), account)).fetchone()
        run = conn.execute("SELECT ts, data FROM state WHERE k = 'combo_run'").fetchone()
        t = _trade(r) if r else None
        ref, meta, step = None, {}, None
        if t is not None and "outcomes" in tables:
            o = conn.execute("SELECT data FROM outcomes WHERE account_id = ? AND status = 'ENTERED' AND symbol = ? AND step_ts = ? "
                             "ORDER BY id DESC LIMIT 1", (account, t["symbol"], t["entry_time"])).fetchone()
            if o:
                od = L._j(o[0])
                sig = od.get("signal") if isinstance(od.get("signal"), dict) else {}
                meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
                ref = "ref_price" in meta
                step = L._f((od.get("detail") or {}).get("fill")) if isinstance(od.get("detail"), dict) else None
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    return {"state": "ok", "path": path, "trade": t, "run": L._j(run[1]) if run else {}, "run_ts": L._i(run[0]) if run else None,
            "ref": ref, "meta": {"member": meta.get("member"), "member_order": L._i(meta.get("member_order")),
                                  "stop_rule": meta.get("stop_rule"), "ref_price": L._f(meta.get("ref_price")),
                                  "break_level": L._f(meta.get("break_level")), "fill": step}}


# ---------------------------------------------------------------- the trade's own rules
def rules_of(t: dict, run: dict) -> dict:
    """The round trip, slippage and ladder the engine used for this trade (see the module doc). ``ladder`` None when the
    run's config has none (then nothing can be rebuilt); ``spec`` is paperbot/ladder2.py ``ComboLadder`` (the rule bot's
    form, or the two-part one when the config has next_trigger / next_gap)."""
    from ...config import v3_settings
    from ...ladder2 import ComboLadder
    run_fee = L._f((run or {}).get("taker_fee"))
    fees, qty, e, x = t.get("fees"), t.get("qty"), t.get("entry_price"), t.get("exit_price")
    tk, src = None, None
    if fees is not None and fees > 0 and qty and e:
        base = qty * e + (0.0 if t.get("exit_reason") == "LIQ" else qty * (x or 0.0))
        if base > 0:
            tk, src = round(fees / base, 8), "trade"
    if tk is None and run_fee:
        tk, src = run_fee, "run"
    if tk is not None and run_fee and abs(tk - run_fee) <= 0.01 * run_fee:
        tk = run_fee            # the very number the engine had (another fee level differs by far more than 1 %)
    s = v3_settings(**({"taker_fee": tk} if tk else {}))
    if tk is None:
        tk, src = s.taker_fee, "default"
    cfg = (run or {}).get("config") if isinstance((run or {}).get("config"), dict) else {}
    lad = cfg.get("ladder") if isinstance(cfg.get("ladder"), dict) else {}
    first, step, gap = L._f(lad.get("first_lock")), L._f(lad.get("step")), L._f(lad.get("trigger_gap"))
    spec = ComboLadder.of(lad) if None not in (first, step, gap) else None
    return {"taker_fee": tk, "taker_from": src, "run_taker_fee": run_fee, "slippage": s.slippage_frac, "round_trip": s.round_trip_cost,
            "ladder": L.ladder_numbers(lad) if spec else None, "spec": spec}


def funding_steps(entry_t: int, exit_t: int, funding: Optional[float], notional: Optional[float]) -> tuple:
    """([(minute ms, funding fraction paid by then)], how): "none" (no funding: exact), "boundary" (one funding time held
    over: the whole fraction from that minute), "split" (several: split evenly), "guess" (none held over although the
    trade paid some: from the minute after the entry)."""
    if not funding or not notional:
        return [], "none"
    total = funding / notional
    e0, x0 = entry_t - entry_t % MIN, exit_t - exit_t % MIN
    first = e0 + MIN                                    # the entry minute pays none (engine.step: funding before entries)
    b = -(-first // FUND_MS) * FUND_MS
    bounds = list(range(b, x0 + 1, FUND_MS))
    if not bounds:
        return [(first, total)], "guess"
    k = len(bounds)
    return [(bt, total if i == k - 1 else total * (i + 1) / k) for i, bt in enumerate(bounds)], "boundary" if k == 1 else "split"


# ---------------------------------------------------------------- the rebuild (engine order, one minute at a time)
def rebuild(t: dict, bars: list, rules: dict, ref_fill: bool, fund: list, until: Optional[int] = None) -> dict:
    """The trade replayed on 1-minute ``bars`` (dicts ts, open, high, low, close, m_open, m_high, m_low, close_time; oldest
    first, from the entry minute) with the engine's own functions. ``t``: the record (side, entry_price, entry_time,
    leverage, stop_initial, liq_price, qty, margin, exit_reason, exit_time). ``fund``: ``funding_steps``. ``until``: the
    last minute to step (the shown window's end).

    -> {"minutes": [[t, stop_in, stop_out, best, lock_out, fund, roe_c, roe_h, roe_l, lock_in]], "locks": [...],
        "exit": {...} | None, "stopped": "exit" | "outside" | "end", "missing": minutes without a bar between the entry and
        the end}. stop_in / lock_in: in force during the minute; stop_out / lock_out: after it (from the next minute)."""
    from ...ladder import net_roe, roe_price, tighten
    side, entry, lev = int(t["side"]), float(t["entry_price"]), float(t["leverage"])
    rt, slip, spec = rules["round_trip"], rules["slippage"], rules["spec"]
    qty, margin0 = t.get("qty") or 0.0, t.get("margin") or 0.0
    liq = t.get("liq_price")
    notional = qty * entry
    e0 = int(t["entry_time"]) - int(t["entry_time"]) % MIN
    x_rec = int(t["exit_time"])
    x0 = x_rec - x_rec % MIN
    reason = t.get("exit_reason")
    stop, lock, mfe = float(t["stop_initial"]), None, entry
    minutes, locks, out = [], [], None
    stopped, last, seen = "end", None, 0

    def fund_at(ts):
        f = 0.0
        for ft, frac in fund:
            if ft <= ts:
                f = frac
        return f

    def close(px, ts, why, how, ff):
        gross = side * qty * (px - entry)
        if qty and gross < -(margin0 - ff * notional):          # engine._close: beyond the isolated margin = liquidated
            return {"t": ts, "price": liq, "reason": "LIQ", "how": "margin"}
        return {"t": ts, "price": px, "reason": why, "how": how}

    for b in bars:
        ts = int(b["ts"])
        if ts < e0:
            continue
        if until is not None and ts > until:
            break
        seen += 1
        last = ts
        ff = fund_at(ts)
        o, hi, lo, c = b["open"], b["high"], b["low"], b["close"]
        mo, mh, ml = b["m_open"], b["m_high"], b["m_low"]
        ct = int(b["close_time"])
        if reason == "REV" and ts == x_rec:                     # ComboEngine.step: before funding, entries and exits
            out = close(o * (1 - side * slip), ts, "REV", "rev", fund_at(ts - 1))
            stopped = "exit"
            break
        if reason in EXT_REASONS + SWITCH_REASONS + SUP_REASONS and ts >= x0:
            stopped = "outside"
            break
        entry_bar = ts == e0
        mfe = max(mfe, hi) if side > 0 else min(mfe, lo)
        stop_in, why = stop, ("LOCK" if lock is not None else "SL")
        best = net_roe(side, entry, mfe, lev, rt, ff)
        row = [ts, stop_in, None, best, lock, ff, net_roe(side, entry, c, lev, rt, ff), net_roe(side, entry, hi, lev, rt, ff),
               net_roe(side, entry, lo, lev, rt, ff), lock]
        if not entry_bar:
            if liq is not None and (mo - liq) * side <= 0:
                out = {"t": ts, "price": liq, "reason": "LIQ", "how": "liq_open"}
            elif (o - stop) * side <= 0:
                out = close(o * (1 - side * slip), ts, why, "gap", ff)
        if out is None:
            hit_stop = (lo <= stop) if side > 0 else (hi >= stop)
            hit_liq = liq is not None and ((ml <= liq) if side > 0 else (mh >= liq))
            if hit_stop:
                out = close(stop * (1 - side * slip), ct, why, "touch", ff)
            elif hit_liq:
                out = {"t": ct, "price": liq, "reason": "LIQ", "how": "liq"}
            elif spec is not None and not (entry_bar and ref_fill):
                new = spec.lock_for(best)
                if new is not None and not (lock is not None and new <= lock + 1e-12):
                    price = tighten(side, stop, roe_price(side, entry, lev, new, rt, ff))
                    # how many ladder steps this bar climbed (a fast bar can arm 10 % and 13 % at once: only the higher is set)
                    steps = spec.index(new) - spec.index(lock)
                    locks.append({"t": ts, "at": ts + MIN, "best": best, "lock": new, "trigger": spec.trigger_of(new),
                                  "price": price, "from": stop, "from_lock": lock, "steps": max(1, steps)})
                    stop, lock = price, new
        row[2] = None if out is not None else stop
        row[4] = lock
        minutes.append(row)
        if out is not None:
            stopped = "exit"
            break
    end = out["t"] - out["t"] % MIN if out else (last if last is not None else e0)
    missing = max(0, (end - e0) // MIN + 1 - seen) if seen else None
    return {"minutes": minutes, "locks": locks, "exit": out, "stopped": stopped, "missing": missing, "last_minute": last,
            "stop": stop, "lock": lock, "mfe": mfe if seen else None}


def _same_px(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= PRICE_TOL * max(abs(a), abs(b), 1e-12)


def compare(t: dict, rb: dict, cfg: Optional[dict] = None) -> dict:
    """The rebuilt path against the record: {"state": "same" | "differs" | "unchecked", "items": [{key, ko, record, rebuilt,
    kind}], "why_ko"} (``cfg``: the bot's config, for the words of its TIME close)."""
    items = []
    x = rb.get("exit")
    reason = t.get("exit_reason")

    def add(key, ko, rec, reb, kind):
        items.append({"key": key, "ko": ko, "record": rec, "rebuilt": reb, "kind": kind})

    if rb.get("stopped") == "outside":
        # a kill, a halt or the switch closed it: the minute is the record's; what the bars say is the lock it had by then
        pass
    elif x is None:
        add("exit", "청산", {"t": t.get("exit_time"), "price": t.get("exit_price"), "reason": reason}, None, "exit")
    else:
        if x["reason"] != reason:
            add("reason", "청산 이유", reason, x["reason"], "reason")
        if int(x["t"]) != int(t.get("exit_time") or 0):
            add("exit_time", "청산 시각", t.get("exit_time"), x["t"], "time")
        if not _same_px(x["price"], t.get("exit_price")):
            add("exit_price", "청산 가격", t.get("exit_price"), x["price"], "price")
    rec_lock, reb_lock = t.get("lock_roe"), rb.get("lock")
    if (rec_lock is None) != (reb_lock is None) or (rec_lock is not None and abs(rec_lock - reb_lock) > ROE_TOL):
        add("lock", "마지막 잠금", rec_lock, reb_lock, "roe")
    if t.get("stop_price") is not None and not _same_px(rb.get("stop"), t.get("stop_price")):
        add("stop", "마지막 손절선", t.get("stop_price"), rb.get("stop"), "price")
    if rb.get("stopped") != "outside" and t.get("mfe_price") is not None and rb.get("mfe") is not None \
            and not _same_px(rb["mfe"], t["mfe_price"]):
        add("mfe", "가장 유리했던 가격", t["mfe_price"], rb["mfe"], "price")
    return {"state": "differs" if items else "same", "items": items,
            "why_ko": (SWITCH_KO if reason in SWITCH_REASONS else sup_ko(reason, cfg) if reason in SUP_REASONS else OUTSIDE_KO)
            if rb.get("stopped") == "outside" else None}


# ---------------------------------------------------------------- bars
def read_bars(path: str, symbol: str, lo: int, hi: int) -> dict:
    """The rule bot's 1m bars of ``symbol`` in [lo, hi) (live_bars, one read)."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path, RULE_MISSING_KO)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        if "live_bars" not in L._tables(conn):
            return L._missing(path, RULE_NO_TABLE_KO)
        cur = conn.execute("SELECT ts, open, high, low, close, mark_open, mark_high, mark_low, close_time FROM live_bars "
                           "WHERE symbol = ? AND ts >= ? AND ts < ? ORDER BY ts", (symbol, int(lo), int(hi)))
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    out = []
    for ts, o, h, lo_, c, mo, mh, ml, ct in rows:
        o, h, lo_, c = L._f(o), L._f(h), L._f(lo_), L._f(c)
        if None in (o, h, lo_, c):
            continue
        out.append({"ts": int(ts), "open": o, "high": h, "low": lo_, "close": c,
                    "m_open": o if L._f(mo) is None else float(mo), "m_high": h if L._f(mh) is None else float(mh),
                    "m_low": lo_ if L._f(ml) is None else float(ml),
                    "close_time": int(ct) if ct is not None else int(ts) + MIN - 1})
    return {"state": "ok", "path": path, "rows": out}


def tier_of(hold_ms: int) -> tuple:
    for top, tf, ms in TIERS:
        if top is None or hold_ms <= top:
            return tf, ms
    return TIERS[-1][1], TIERS[-1][2]


def bucket(rows: list, tf_ms: int) -> list:
    """1m bar dicts -> [[open ms, o, h, l, c, minutes]] per ``tf_ms`` bucket, only of the minutes that exist."""
    out: list = []
    for r in rows:
        b = r["ts"] - r["ts"] % tf_ms
        if out and out[-1][0] == b:
            cur = out[-1]
            cur[2] = max(cur[2], r["high"])
            cur[3] = min(cur[3], r["low"])
            cur[4] = r["close"]
            cur[5] += 1
        else:
            out.append([b, r["open"], r["high"], r["low"], r["close"], 1])
    return out


def path_of(minutes: list, tf_ms: int, side: int, entry: float, lev: float, rt: float, shown: list) -> list:
    """The readout per shown bar inside the trade: [[open ms, stop in force, best net ROE so far, net ROE at the close, at
    the high, at the low, the lock in force]]. 1m: the minutes themselves; longer bars: the last minute's stop, best and
    lock, the ROE at the bar's own close / high / low (that minute's funding)."""
    from ...ladder import net_roe
    if tf_ms == MIN:
        return [[m[0], m[1], m[3], m[6], m[7], m[8], m[9]] for m in minutes]
    by = {b[0]: b for b in shown}
    out: list = []
    for m in minutes:
        k = m[0] - m[0] % tf_ms
        b = by.get(k)
        if b is None:
            continue
        row = [k, m[1], m[3], net_roe(side, entry, b[4], lev, rt, m[5]), net_roe(side, entry, b[2], lev, rt, m[5]),
               net_roe(side, entry, b[3], lev, rt, m[5]), m[9]]
        if out and out[-1][0] == k:
            out[-1] = row
        else:
            out.append(row)
    return out


def stops_of(t: dict, rb: dict) -> list:
    """The stop line as change points [[from ms, price, lock]] (1-minute precision): the first stop from the entry, each
    lock from the minute after the bar that armed it."""
    out = [[int(t["entry_time"]), t.get("stop_initial"), None]]
    for k in rb.get("locks") or []:
        out.append([k["at"], k["price"], k["lock"]])
    return out


# ---------------------------------------------------------------- the executors
def _exec_cell(x: dict, pairs: dict, live_by: dict, pt: dict, path: Optional[str] = None, other_ko: Optional[str] = None,
               cfg: Optional[dict] = None) -> dict:
    """What one executor did with the paper trade ``pt``: matched (its own trade: entry, exit reference, the exchange stop
    it recorded, its own result), or why not (livebots ``why_missed``: the executor's own records), or "other": it followed
    the other paper bot then (owners 10-19, ``path``: this trade's paper database). ``cfg``: the paper bot's config (the
    words of its TIME close)."""
    r = x["record"]
    base = {"id": x["id"], "name_ko": x["name_ko"], "s": SHORT.get(x["id"], x["id"][:1].upper())}
    if r.get("state") != "ok":
        return {**base, "state": "unknown", "src_state": r.get("state"), "reason_ko": r.get("reason_ko")}
    lk = pairs.get(pt["id"])
    if lk is None:
        if path and not L.followed_at(x, path, pt.get("entry_time")):
            return {**base, **L.other_cell(x, other_ko)}
        return {**base, **L.why_missed(r, pt, ACCOUNT)}
    lt = live_by[lk]
    reason = lt["exit_reason"]
    if reason == "PAPER":
        reason = pt.get("exit_reason") or reason
    slip = (lt["side"] * (pt["entry_price"] - lt["entry_price"]) / pt["entry_price"]) \
        if pt.get("entry_price") and lt.get("entry_price") else None
    return {**base, "state": "matched", "key": lt["key"], "side": lt["side"], "qty": lt["qty"], "leverage": lt["leverage"],
            "entry_ts": lt["entry_ts"], "entry_price": lt["entry_price"], "exit_ts": lt["exit_ts"], "exit_ref": lt["exit_ref"],
            "stop_initial": lt["stop_initial"], "stop_final": lt["stop_final"], "pnl": lt["pnl"], "roe": lt["roe"], "est": lt["est"],
            "margin": lt["margin"], "commission": lt["commission"], "funding": lt["funding"], "reason": reason,
            "reason_ko": L.exit_words(reason, cfg, pt.get("exit_why")) if reason == pt.get("exit_reason") else EXIT_KO.get(reason, reason),
            "exit_raw": lt["exit_raw"], "slip_vs_paper": slip,
            "locked": bool(lt.get("stop_final") and lt.get("entry_price") and (lt["stop_final"] - lt["entry_price"]) * lt["side"] > 0)}


def exec_pairs(execs: list, ptrades: list, path: Optional[str] = None) -> list:
    """[(executor, {paper id: live key}, {live key: live trade})] (livebots ``pairs_of``, the pairing of every 실거래 tab:
    each live trade with the paper trade of the paper bot it followed; only this paper database's (``path``) here)."""
    out = []
    for x in execs:
        r = x["record"]
        if r.get("state") != "ok":
            out.append((x, {}, {}))
            continue
        m = {pt["id"]: lk for lk, pt in L.pairs_of(x).items() if path is None or L.LP.same(pt["paper_path"], path)}
        out.append((x, m, {str(t["key"]): t for t in r.get("trades") or []}))
    return out


def _sources(p: dict, now: int, bot: str = "paper") -> tuple:
    """(paper read, its account, execs, its path, the other bot's short label): ``bot`` "paper2" is the second paper bot
    (owners 10-19); without one it is the main one."""
    _configs, _follows, paper, execs = L.sources(p, now)
    bots = L.paper_bots(p, paper, execs)
    b = next((x for x in bots if x["id"] == bot), bots[0])
    other = next((x for x in bots if x["id"] != b["id"]), None)
    pr = b["read"]
    a = (pr.get("accounts") or {}).get(ACCOUNT) if pr.get("state") == "ok" else None
    return pr, a, execs, b["path"], (other or {}).get("short_ko") or None, bots


def _prev(t: dict, tb: Optional[dict]) -> bool:
    """Entered before the 추세판단 봇's start (livebots.trend_bot ``since``): the bot before it's trade (전환 전)."""
    since = (tb or {}).get("since")
    return since is not None and t.get("entry_time") is not None and int(t["entry_time"]) < int(since)


# ---------------------------------------------------------------- GET /api/v4/livebots/replay
def build_list(p: Optional[dict] = None, now_ms: Optional[int] = None, offset: int = 0, limit: int = LIST_DEFAULT,
               bot: str = "paper") -> dict:
    """The closed paper trades, newest first (exit time, then id), ``limit`` from ``offset`` (at most 500); ``bot``
    "paper2": the second paper bot's (owners 10-19, two paper bots)."""
    p = p or L.paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    offset, limit = max(0, int(offset or 0)), max(1, min(LIST_MAX, int(limit or LIST_DEFAULT)))
    paper, a, execs, path, other_ko, bots = _sources(p, now, bot)
    tb = L.trend_bot(path)
    head = {"now_ms": now, "account": ACCOUNT, "offset": offset, "limit": limit,
            "execs": [{"id": x["id"], "name_ko": x["name_ko"], "s": SHORT.get(x["id"], x["id"][:1].upper()),
                       "state": x["record"].get("state"), "reason_ko": x["record"].get("reason_ko")} for x in execs],
            "bot": bot if len(bots) > 1 else "paper", "papers": L.papers_out(bots), "trend_bot": L.trend_out(tb)}
    if paper.get("state") != "ok":
        return {**head, **{k: paper.get(k) for k in ("state", "reason_ko", "reason", "path")}, "rows": [], "n": 0}
    if not a or not a.get("known"):
        return {**head, "state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요", "path": paper.get("path"), "rows": [], "n": 0}
    trades = a.get("trades") or []
    newest = sorted(trades, key=lambda t: (t["exit_time"] or 0, t["id"] or 0), reverse=True)
    prs = exec_pairs(execs, trades, path)
    cfg = L.cfg_of(paper)                                # the bot's own words for its TIME close (owners 10-23)
    rows = []
    for t in newest[offset:offset + limit]:
        cells = []
        for x, pairs, live_by in prs:
            c = _exec_cell(x, pairs, live_by, t, path, other_ko, cfg)
            cells.append({k: c.get(k) for k in ("id", "s", "name_ko", "state", "pnl", "roe", "est", "reason_ko", "why_ko")})
        rows.append({**{k: t.get(k) for k in ("id", "symbol", "side", "strategy_id", "timeframe", "entry_time", "exit_time", "exit_reason",
                                               "leverage", "pnl", "roe", "lock_roe", "entry_price", "exit_price")},
                     "reason_ko": L.exit_words(t["exit_reason"], cfg, t.get("exit_why")), "win": (t["pnl"] or 0) > 0,
                     "hold_ms": (t["exit_time"] - t["entry_time"]) if t.get("exit_time") is not None and t.get("entry_time") is not None else None,
                     "prev": _prev(t, tb), "execs": cells})
    return {**head, "state": "ok", "n": len(trades), "rows": rows, "newest_id": newest[0]["id"] if newest else None,
            "name_ko": paper.get("name_ko")}


# ---------------------------------------------------------------- GET /api/v4/livebots/replay/{trade_id}
def build_one(p: Optional[dict], trade_id: int, now_ms: Optional[int] = None, more: Optional[dict] = None,
              bot: str = "paper") -> Optional[dict]:
    """One trade's replay (None when the paper account has no trade with this id); ``bot`` "paper2": the second paper
    bot's trade (its own database, its own run's ladder and costs)."""
    p = p or L.paths()
    more = more or L.paths_more()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    _pr, _a, _x, bot_path, _o, _b = _sources(p, now, bot) if bot != "paper" else (None, None, None, p["paper"], None, None)
    rec = read_trade(bot_path, trade_id)
    if rec.get("state") != "ok":
        return {"now_ms": now, "id": int(trade_id), **{k: rec.get(k) for k in ("state", "reason_ko", "reason", "path")}}
    t = rec["trade"]
    if t is None:
        return None
    notes: list = []
    rules = rules_of(t, rec["run"])
    run_cfg = (rec["run"] or {}).get("config") if isinstance((rec["run"] or {}).get("config"), dict) else {}
    words = lambda r: L.exit_words(r, run_cfg, t.get("exit_why") if r == t["exit_reason"] else None)   # noqa: E731  its own bot's words
    hold = max(0, int(t["exit_time"]) - int(t["entry_time"]))
    tf, tf_ms = tier_of(hold)
    e0 = int(t["entry_time"]) - int(t["entry_time"]) % MIN
    x0 = int(t["exit_time"]) - int(t["exit_time"]) % MIN
    lo, hi = e0 - PAD_MS, x0 + PAD_MS + MIN
    lo, hi = lo - lo % tf_ms, -(-hi // tf_ms) * tf_ms
    src = read_bars(more["rule_db"], t["symbol"], lo, hi)
    notional = (t.get("qty") or 0) * (t.get("entry_price") or 0)
    fund, fund_how = funding_steps(int(t["entry_time"]), int(t["exit_time"]), t.get("funding"), notional)
    ref = rec["ref"]
    ref_from = "outcome"
    rows = src.get("rows") or []
    if ref is None:                                   # no ENTERED outcome: a fill at the bar open (+ slippage) = no reference price
        first = next((r for r in rows if r["ts"] == e0), None)
        if first is not None and t.get("entry_price"):
            open_fill = first["open"] * (1 + int(t["side"]) * rules["slippage"])
            ref, ref_from = not _same_px(open_fill, t["entry_price"]), "bar"
        else:
            ref, ref_from = True, "assumed"
    bars = {"state": src.get("state"), "tf": tf, "tf_ms": tf_ms, "stepped": tf != "1m", "from_ms": lo, "to_ms": hi,
            "rule_path": more["rule_db"], "rows": [], "reason_ko": src.get("reason_ko"), "reason": src.get("reason"), "missing": None}
    if tf != "1m":
        bars["step_ko"] = (f"{'12시간' if tf == '5m' else '5일'}이 넘는 거래라 {TF_KO[tf]}으로 보여요 "
                           f"(손절·잠금은 1분봉으로 다시 계산)")
    rb, check, path, stops = None, None, [], stops_of(t, {"locks": []})
    if src.get("state") == "ok" and not rows:
        bars["state"], bars["reason_ko"] = "none", NO_BARS_KO
    if bars["state"] == "ok":
        shown = bucket(rows, tf_ms)
        bars["rows"] = [b[:5] for b in shown]
        if tf != "1m":
            bars["partial"] = sum(1 for b in shown if b[5] < tf_ms // MIN)
        inside = [r for r in rows if r["ts"] >= e0]
        if rules["spec"] is None:
            check = {"state": "unchecked", "items": [], "why_ko": "봇 설정에 계단 익절 숫자가 없어 다시 계산하지 못했어요"}
        elif not inside or inside[0]["ts"] > x0:
            check = {"state": "unchecked", "items": [], "why_ko": "진입부터 청산까지의 1분봉이 없어 다시 계산하지 못했어요"}
        else:
            rb = rebuild(t, inside, rules, bool(ref), fund, until=hi - MIN)
            check = compare(t, rb, run_cfg)
            path = path_of(rb["minutes"], tf_ms, int(t["side"]), float(t["entry_price"]), float(t["leverage"]), rules["round_trip"], shown)
            stops = stops_of(t, rb)
            bars["missing"] = rb["missing"]
            if rb["missing"]:
                notes.append(f"진입부터 청산까지 1분봉 {rb['missing']}개가 규칙봇 기록에 비어 있어요 (봇도 그 분은 건너뛰어요)")
    else:
        check = {"state": "unchecked", "items": [], "why_ko": "1분봉이 없어 다시 계산하지 못했어요"}
    if fund_how != "none":
        notes.append({"boundary": "펀딩은 한 번 냈어요. 그때(UTC 00·08·16시 중 보유 중이던 시각)부터 잠금 계산에 넣었어요 (봇은 몇 분 늦게 반영할 수 있어요)",
                      "split": "펀딩을 여러 번 냈는데 한 번씩의 크기는 기록에 없어 똑같이 나눠 넣었어요",
                      "guess": "펀딩을 냈지만 보유 중에 펀딩 시각이 없어 진입 다음 분부터 넣었어요"}[fund_how])
    if ref_from != "outcome":
        notes.append("진입 신호 기록이 없어 진입 봉 규칙(참고 가격 체결이면 그 봉엔 잠금 안 함)을 " +
                     ("1분봉 시가로 판단했어요" if ref_from == "bar" else "참고 가격 체결로 놓았어요"))
    if rules["taker_from"] != "trade":
        notes.append("거래 기록으로 수수료율을 알 수 없어 " + ("봇 실행 기록의 수수료율" if rules["taker_from"] == "run" else "기본 수수료율") + "로 계산했어요")
    side = int(t["side"])
    rb_exit = rb.get("exit") if rb else None
    _paper, a, execs, bpath, other_ko, _bots = _sources(p, now, bot)
    ptrades = (a or {}).get("trades") or []
    pt = next((x for x in ptrades if x["id"] == t["id"]), None) or t
    cells = [_exec_cell(x, pairs, live_by, pt, bpath, other_ko, run_cfg) for x, pairs, live_by in exec_pairs(execs, ptrades, bpath)]
    done = now >= hi and all(c["state"] not in ("open", "unknown") for c in cells) and bars["state"] in ("ok", "none")
    lad = rules["ladder"]
    tb = L.trend_bot(bpath)
    trade = {**{k: t.get(k) for k in ("id", "symbol", "side", "strategy_id", "timeframe", "entry_time", "exit_time", "exit_reason",
                                       "leverage", "qty", "margin", "fees", "funding", "pnl", "roe", "equity_after", "lock_roe",
                                       "stop_initial", "liq_price", "entry_price", "exit_price", "mfe_price", "mae_price", "signal_ts",
                                       "price_move")},
             "stop_final": t.get("stop_price"), "notional": notional or None, "hold_ms": hold, "win": (t.get("pnl") or 0) > 0,
             "reason_ko": words(t["exit_reason"]), "prev": _prev(t, tb)}
    return {
        "state": "ok", "now_ms": now, "id": t["id"], "account": ACCOUNT, "trade": trade, "trend_bot": L.trend_out(tb),
        "setting": {k: rec["meta"].get(k) for k in ("member", "member_order", "stop_rule", "ref_price", "break_level")},
        "rules": {k: rules[k] for k in ("taker_fee", "taker_from", "slippage", "round_trip", "ladder")} | {
            "entry_bar": "ref" if ref else "open", "entry_bar_from": ref_from, "funding_frac": (t.get("funding") or 0) / notional if notional else None,
            "funding_how": fund_how, "funding_steps": [[ft, fr] for ft, fr in fund],
            "ladder_ko": ladder_ko(lad)},
        "bars": bars, "path": path, "stops": stops, "locks": (rb or {}).get("locks") or [],
        "exit": {"record": {"t": t["exit_time"], "price": t.get("exit_price"), "reason": t["exit_reason"],
                            "reason_ko": words(t["exit_reason"])},
                 "rebuilt": ({**rb_exit, "reason_ko": L.exit_words(rb_exit["reason"], run_cfg)} if rb_exit else None),
                 "stopped": rb.get("stopped") if rb else None},
        "check": check, "execs": cells, "notes_ko": notes, "final": done,
        "first_stop_roe": _roe_at(side, t, t.get("stop_initial"), rules, 0.0),
    }


def _roe_at(side: int, t: dict, px: Optional[float], rules: dict, ff: float) -> Optional[float]:
    from ...ladder import net_roe
    if px is None or not t.get("entry_price") or not t.get("leverage"):
        return None
    return net_roe(side, float(t["entry_price"]), float(px), float(t["leverage"]), rules["round_trip"], ff)


def ladder_ko(lad: Optional[dict]) -> Optional[str]:
    """The run's ladder in the owners' words: '순ROE 11%에서 10% 잠금, 그 뒤 3%씩' (the rule bot's form), or the two-part
    one '순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%)'. None without a ladder."""
    if not lad:
        return None
    first = f"순ROE {_pk(lad['first_lock'] + lad['trigger_gap'])}에서 {_pk(lad['first_lock'])} 잠금"
    if lad.get("next_trigger") is None or lad.get("next_gap") is None:
        return f"{first}, 그 뒤 {_pk(lad['step'])}씩"
    t2, l2, st = lad["next_trigger"], lad["next_trigger"] - lad["next_gap"], lad["step"]
    return (f"{first}, {_pk(t2)}에서 {_pk(l2)}, {_pk(t2 + st)}에서 {_pk(l2 + st)}, 그 뒤 {_pk(st)}마다 "
            f"(닿은 순ROE - {_pk(lad['next_gap'])})")


def _pk(x: Optional[float]) -> str:
    if x is None:
        return "—"
    v = x * 100
    return f"{v:.0f}%" if abs(v - round(v)) < 1e-6 else f"{v:.1f}%"


def one_cached(p: dict, more: dict, trade_id: int, bot: str = "paper") -> Optional[dict]:
    """``build_one`` cached per trade: a finished answer (``final``) for 10 minutes, any other for 5 seconds."""
    from ..app import json_finite
    key = json.dumps([int(trade_id), p, more] + ([bot] if bot != "paper" else []), sort_keys=True)
    now = time.time()
    with _lock:
        hit = _one.get(key)
        if hit is not None and now < hit[0]:
            _one.move_to_end(key)
            return hit[1]
    v = build_one(p, int(trade_id), more=more, bot=bot)
    if v is None:
        return None
    v = json_finite(v)
    with _lock:
        _one[key] = (now + (DONE_TTL_S if v.get("final") else LIVE_TTL_S), v)
        _one.move_to_end(key)
        while len(_one) > CACHE_MAX:
            _one.popitem(last=False)
    return v


# ---------------------------------------------------------------- routes
def register(app, ctx) -> dict:
    from fastapi import HTTPException

    from ..app import json_finite

    @app.get("/api/v4/livebots/replay")
    def get_livebots_replay(offset: int = 0, limit: int = LIST_DEFAULT, bot: str = "paper"):
        """실거래 › 다시보기: the paper account's closed trades, newest first, with each executor's part (5 s cache);
        ``bot=paper2``: the second paper bot's (owners 10-19)."""
        p = L.paths()
        o, n = max(0, int(offset)), max(1, min(LIST_MAX, int(limit)))
        b = "paper2" if bot == "paper2" else "paper"
        key = "replay:" + json.dumps([p, L.paths_more(), o, n] + ([b] if b != "paper" else []), sort_keys=True)
        return L._cached(key, lambda: json_finite(build_list(p, offset=o, limit=n, bot=b)))

    @app.get("/api/v4/livebots/replay/{trade_id}")
    def get_livebots_replay_one(trade_id: int, bot: str = "paper"):
        """실거래 › 다시보기: one closed trade on its 1-minute bars, the stop path and the locks rebuilt, the executors' part."""
        v = one_cached(L.paths(), L.paths_more(), trade_id, "paper2" if bot == "paper2" else "paper")
        if v is None:
            raise HTTPException(404, "그런 거래가 없어요")
        return v

    return {"routes": ["/api/v4/livebots/replay", "/api/v4/livebots/replay/{trade_id}"]}
