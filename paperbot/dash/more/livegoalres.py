"""실거래 › 봇별 화면의 '목표 연구' (owners 10-26: "필요한 연구 부분들 각 봇마다 내 목표 수익률을 위해 필요한 분석부분들이나 연구
부분들 다 대시보드 화면에 추가해줘"): for each live bot, what its own record says about the owners' goal (한 달 ×6, +500 %:
liveinsight.MONTHLY_TARGET) and the open research questions that decide whether it can get there, measured on its own
records as they come in. Read-only, like every 실거래 tab: nothing here changes a bot, a rule or an order (that is the
owners' decision), and nothing here is a forecast.

    GET /api/v4/livebots/goalres?bot=trend|range|vwap|mix|v39   (5 s cache, as every 실거래 tab)

Bots (each answer shows one bot and the executors that follow it, nothing of the others):
    trend   추세판단 봇: the main paper bot (PAPERBOT_LIVE_PAPER_DB, account COMBO@mix) from its own start
            (livebots.trend_bot), and the executors that follow its database (바이비트, WOO X Pro)
    range   레인지 봇 (owners 10-26, docs/range-bot-ko.md): the paper bot "range" of paper_bots (its config's ``range``
            section), and its followers (WOO X Pro)
    vwap    VWAP 개선판: the paper bot whose config has an entry gate (livevwap.is_vwap; paper_bots), and its followers
            (딥코인)
    mix     믹스 30분 봇 (WOO X Pro 2): the live bot and its paper twin (livemix: their logs), the owners' new settings of
            10-26 (margin_frac 40 %, net ladder) told apart by each entry's own margin share
    bybit   바이비트 봇 (owners 10-29, docs/mixbybit-ko.md): the same parts as the mix bot from its own logs (livemix
            PROFILES "bybit"), but no 전후 (margin 40 % from its first trade) and no 하한 (it has no balance floor)
    v39     V3.9 투비트: the rule bot's paper account V39_ALL@1h (paper3.db) and the Toobit executor (while it is not
            installed, the paper account alone, said so)

The answer:
    goal       the goal in words (×6 in 30 days)
    accounts   per account (the paper bot, each follower): its record (trades, wins, Wilson 90 % range of the win
               rate), the average win and loss as a share of the wallet (pnl / the wallet before the trade: whatever the
               sizing was), the mean log growth a trade, entries a day, and from those (가상 계산, never a forecast):
               the 30-day multiple at this pace, the win rate ×6 needs at its own average win / loss and entries a day,
               the average win ×6 needs at its own win rate, the entries a day ×6 needs at its own growth a trade; this
               month against the ×6 path (from the month's start, or the account's start when later); one verdict line
    items      the research questions of this bot, each {id, title_ko, q_ko (the question), state, lead_ko (what the
               record says now, in one line), tone, kpis [{label_ko, value, fmt}], table {cols, rows} (optional),
               need_ko (when it can be read), use_ko (what decision it feeds), how_ko (how it is measured), link}
    links      the bot's other screens that go deeper (hashes of the live site)

Items by bot (every follower's items only while it follows this bot: livepapers segments):
    every bot with followers   실거래가 덜 버는 이유 (gap: the same trades paper vs live, the fill gaps of
                               livebots.fill_gaps, the paper trades not followed and why: livebots.why_missed) and, for a
                               follower with a signal light, 신호등 검증 (the light replayed over the paper's own trades:
                               the record of the trades it would let through vs the ones it would hold back)
    trend, vwap, v39           진 거래는 한때 얼마나 갔나 (each closed paper trade's best net ROE while it was open:
                               the engine's own best price, else the rule bot's 1-minute bars, livepos.excursion; for
                               V3.9 at the owners' Toobit plan: BTC 40x, others 30x, Toobit costs, against the 20 → 17
                               ladder's buckets)
    trend                      어느 역할·진입봉이 버나 (the trend bot's roles and entry bars)
    vwap                       어느 매매법이 버나 (per strategy) and 막은 신호는 어땠나 (livevwap.blocked: the gates'
                               virtual results)
    mix                        새 설정 전후, 계단 몇 칸까지 갔나, 잔고 하한까지 손절 몇 번, 실거래 vs 모의
    v39                        장세 (V3.9에 맞는 장인가: the last 10 closed paper trades, the weeks, BTC's 24-hour move at
                               each entry from the rule bot's 1-minute bars) and the 30-day study's numbers (research,
                               labelled as such)
    range                      진짜 vs 동전 (the paper account against its coin-flip twin), 장세 (10월 같은 장인가: the same
                               cuts as V3.9's, against the research's October and 2025-01 ~ 2026-09 numbers, labelled as
                               research), 손절 해부 (each stop-out: did the price reach the take-profit level within 24 hours
                               after it (the stop was close) or keep going (the direction was wrong), from the rule bot's
                               1-minute bars) and the research's numbers (analysis/f7tp10_1026/FINAL_KO.md)

Honest states as every live page (CONTRACT §1.6): a source not there = ``missing`` (수집 전), unreadable = ``error``
(못 읽음 + why), never a zero; a small sample says so (``few``). Ratios are ratios (0.1 = 10 %), times UTC ms.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from typing import Any, Callable, Optional

from ... import livepapers as LP
from . import livebots as L

DAY, HOUR, MIN = L.DAY, L.HOUR, 60_000
BOTS = ("trend", "range", "vwap", "mix", "v39", "bybit")
NAME_KO = {"trend": "추세판단 봇", "range": "레인지 봇", "vwap": "VWAP 개선판", "mix": "믹스 30분 봇", "v39": "V3.9 투비트",
           "bybit": "바이비트 봇"}
MONTH_D = 30                            # the goal's month (×6 in 30 days)
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
MIN_DAYS = 1.0                          # entries a day only from one whole day of record
FEW = 20                                # a record under this many closed trades: 표본 적음
READ_N = 10                             # under this many closed trades no verdict at all
ROLL_N = 10                             # V3.9 장세: the last 10 closed paper trades
BTC_MOVE = 0.02                         # V3.9 장세: BTC's 24-hour move beyond ±2 % = up / down, else sideways
TOOBIT_RT = 0.0016                      # docs/toobit-ko.md: Toobit round trip (taker 0.06 % x 2 + slippage), net ROE basis
LINKS = {
    "trend": [("#/goal", "목표"), ("#/review", "2주 검토"), ("#/expect", "재현 비교"), ("#/cost", "비용"), ("#/missed", "못 탄 신호"),
              ("#/map", "지도")],
    "vwap": [("#/vwperf", "VWAP 성적"), ("#/vwblock", "막은 신호")],
    "mix": [("#/mixperf", "믹스 성적")],
    "bybit": [("#/bybitperf", "바이비트 성적"), ("#/ftrend", "친구 추세판")],
    "v39": [],
    "range": [("#/trades", "거래"), ("#/signals", "신호"), ("#/missed", "못 탄 신호"), ("#/cost", "비용")],
}
GOAL_KO = "두 분 목표: 한 달(30일) ×6 (+500%)"
NOTE_KO = ("계산일 뿐 예측이 아니에요: 지금까지의 기록(승률 · 평균 이익 · 평균 손실 · 하루 진입 수)이 그대로 간다고 칠 때의 숫자예요. "
           "거래가 적으면 숫자가 크게 흔들려요")
# the 30-day study of the owners' Toobit plan (analysis/v39_1h/REPORT_KO.md 14장, owners1025h.py): research numbers, never live
V39_STUDY = {
    "src": "analysis/v39_1h/REPORT_KO.md 15장 (owners1027.py, 계단 12→10 줄)",
    "rows": [{"span_ko": "페이퍼 앞 10일 (09-26 ~ 10-06)", "trades": 13, "wins": 6, "stops": 7, "start": 50.0, "end": 14.1},
             {"span_ko": "페이퍼 20일 (10-06 ~ 10-26)", "trades": 26, "wins": 26, "stops": 0, "start": 50.0, "end": 177.9},
             {"span_ko": "30일 한 계좌", "trades": 39, "wins": 32, "stops": 7, "start": 50.0, "end": 48.9}],
    "ko": ("지금 계획(계단 12→10, 10/27부터)으로 다시 돌린 숫자예요. 예전 계단 20→17은 $11.0 · $268 · $57.6이었어요. "
           "결과를 가른 것은 계단보다 V3.9에 맞는 장(20일)이었는지 아닌 장(앞 10일)이었는지였어요"),
}


# the 레인지 봇's research (analysis/f7tp10_1026/FINAL_KO.md 8 · 9장, docs/range-bot-ko.md 0장): research numbers, never live
RANGE_STUDY = {
    "src": "analysis/f7tp10_1026/FINAL_KO.md 8 · 9장",
    "rows": [{"span_ko": "10월 1 ~ 25일", "kind_ko": "10월 같은 장", "trades": 41, "wins": 40, "losses": 1, "win_rate": 40 / 41, "mult": 5.53},
             {"span_ko": "규칙봇 기간 10/06 ~ 10/25", "kind_ko": "10월 같은 장", "trades": 38, "wins": 38, "losses": 0, "win_rate": 1.0, "mult": 6.24},
             {"span_ko": "2025-01 ~ 2026-09 (21달, 달마다 새 지갑)", "kind_ko": "평소 · 약한 장", "trades": None, "wins": None, "losses": None,
              "win_rate": 0.77, "mult": 0.66, "note_ko": "플러스 달 4 / 21 · 가운데 달 약 ×0.66"}],
    "breakeven": 0.82, "usual": 0.77, "october": 40 / 41, "plus_months": 4, "months": 21, "median_month": 0.66,
    "ko": "10월처럼 추세가 강한 장에서는 40승 1패 ×5.53이었고, 2025-01 ~ 2026-09에는 승률 77%로 본전(약 82%)보다 낮아 21달 중 4달만 "
          "플러스였어요 (가운데 달 ×0.66) · 연구 숫자예요, 실거래 아님",
}
STOP_AFTER_MS = 24 * 3_600_000          # 손절 해부: the 24 hours after a stop-out


# ---------------------------------------------------------------- small helpers
def _f(x: Any) -> Optional[float]:
    return L._f(x)


def _i(x: Any) -> Optional[int]:
    return L._i(x)


def _mean(xs) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _pct(x: Optional[float], d: int = 1, sign: bool = True) -> str:
    if x is None:
        return "?"
    v = 100.0 * x
    return f"{v:+.{d}f}%" if sign else f"{v:.{d}f}%"


def _kst(ms: Optional[int]) -> str:
    if ms is None:
        return "?"
    t = time.gmtime((int(ms) + L.KST_MS) / 1000)
    return f"{t.tm_mon}/{t.tm_mday} {t.tm_hour:02d}:{t.tm_min:02d}"


def _src(x: dict) -> dict:
    """A source's honest state (missing / error) for an answer part."""
    return {k: x.get(k) for k in ("state", "reason_ko", "reason", "path") if x.get(k) is not None}


def _wilson(wins: int, n: int, z: float = 1.645) -> Optional[list]:
    if not n:
        return None
    ph = wins / n
    den = 1 + z * z / n
    mid = (ph + z * z / (2 * n)) / den
    half = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return [max(0.0, mid - half), min(1.0, mid + half)]


def item(iid: str, title: str, q: str, **kw) -> dict:
    """One research question: {id, title_ko, q_ko, state ("ok" default), ...}."""
    return {"id": iid, "title_ko": title, "q_ko": q, "state": kw.pop("state", "ok"), **kw}


def kpi(label: str, value: Any, fmt: str = "pct", tone: Optional[str] = None, sub: Optional[str] = None) -> dict:
    out = {"label_ko": label, "value": value, "fmt": fmt}
    if tone:
        out["tone"] = tone
    if sub:
        out["sub_ko"] = sub
    return out


# ---------------------------------------------------------------- 목표 계산 (one account)
def month_from(now: int) -> tuple:
    """(this KST month's first moment, its length in days)."""
    kd = L.kst_day(now)
    import datetime as _dt
    d = _dt.date(1970, 1, 1) + _dt.timedelta(days=kd)
    first = _dt.date(d.year, d.month, 1)
    nxt = _dt.date(d.year + 1, 1, 1) if d.month == 12 else _dt.date(d.year, d.month + 1, 1)
    return L.kst_day_start((first - _dt.date(1970, 1, 1)).days), (nxt - first).days


def goal_numbers(rows: list, entries: list, since: Optional[int], now: int, target: float, eq_from: Optional[float] = None,
                 eq_now: Optional[float] = None, from_ms: Optional[int] = None, month_days: int = MONTH_D) -> dict:
    """The goal arithmetic of one account. ``rows``: its closed trades [{pnl, roe, eq (the wallet before it), ...}];
    ``entries``: every entry time from ``since`` on (the closed trades' and the open position's). Wallet shares: a win's
    and a loss's pnl / eq; growth a trade: the mean of ln(1 + pnl / eq). Needs (가상): the win rate p with
    p ln(1 + w) + (1 - p) ln(1 - l) = ln(target) / (entries a day x 30), the average win w at the record's p, the entries
    a day at the record's growth."""
    known = [r for r in rows if r.get("pnl") is not None]
    n = len(known)
    wins = sum(1 for r in known if r["pnl"] > 0)
    shares = [r["pnl"] / r["eq"] for r in known if r.get("eq") and r["eq"] > 0]
    w = _mean([x for x in shares if x > 0])
    lo = _mean([-x for x in shares if x <= 0])
    g = _mean([math.log1p(x) for x in shares if x > -1])
    days = (now - since) / DAY if since is not None else None
    n_ent = sum(1 for t in entries if t is not None and since is not None and since <= t <= now)
    per_day = n_ent / days if days and days >= MIN_DAYS else None
    p = wins / n if n else None
    out = {"n": n, "unknown": len(rows) - n, "wins": wins, "losses": n - wins, "win_rate": p, "wilson": _wilson(wins, n),
           "avg_win_roe": _mean([r.get("roe") for r in known if r["pnl"] > 0]),
           "avg_loss_roe": _mean([-(r.get("roe")) for r in known if r["pnl"] <= 0 and r.get("roe") is not None]),
           "avg_win": w, "avg_loss": lo, "growth": g, "shares_n": len(shares), "days": days, "entries": n_ent,
           "per_day": per_day, "few": n < FEW, "target": target, "month_days": month_days}
    need_g = math.log(target) / (per_day * month_days) if per_day else None
    out["need_growth"] = need_g
    out["pace_mult"] = math.exp(g * per_day * month_days) if g is not None and per_day else None
    l_ = lo if lo is not None else 0.0
    if need_g is not None and w and l_ < 1:
        den = math.log1p(w) - math.log1p(-l_)
        out["need_win"] = (need_g - math.log1p(-l_)) / den if den > 0 else None
    else:
        out["need_win"] = None
    if need_g is not None and p and l_ < 1:
        x = (need_g - (1 - p) * math.log1p(-l_)) / p
        out["need_avg_win"] = math.expm1(x) if x < 50 else None
    else:
        out["need_avg_win"] = None
    out["need_per_day"] = math.log(target) / (g * month_days) if g and g > 0 else None
    if eq_from and eq_now is not None and from_ms is not None:
        el = max(0.0, (now - from_ms) / DAY)
        mult = eq_now / eq_from
        path = target ** (el / month_days)
        out["month"] = {"from_ms": from_ms, "start_equity": eq_from, "now_equity": eq_now, "mult": mult, "path_now": path,
                        "vs_path": mult / path - 1, "days": el}
    out["verdict_ko"], out["tone"] = verdict(out)
    return out


def verdict(g: dict) -> tuple:
    """One honest line from the goal arithmetic, and its tone (good / warn / bad / thin)."""
    n = g["n"]
    if n < READ_N:
        return (f"닫힌 거래가 {n}번뿐이라 아직 판단하지 않아요 ({READ_N}번부터 숫자로 보고, {FEW}번이 넘어야 믿을 만해요)", "thin")
    if g.get("per_day") is None:
        return ("하루가 다 지나야 하루 진입 수로 목표를 계산해요", "thin")
    need = g.get("need_win")
    wil = g.get("wilson") or [None, None]
    tail = " · 표본 적음" if g["few"] else ""
    if g.get("avg_win") is None:
        return ("이긴 거래가 없어 평균 이익을 몰라요: 이대로는 목표 계산이 안 돼요" + tail, "bad")
    if need is None:
        return ("평균 손실이 너무 커서 목표 계산이 안 돼요" + tail, "bad")
    if need > 1:
        return (f"지금 평균 이익·손실과 하루 {g['per_day']:.1f}번 진입으로는 승률 100%여도 한 달 ×{g['target']:.0f}이 안 돼요 → "
                "평균 이익을 키우거나(계단·익절) 진입을 늘려야 해요" + tail, "bad")
    if wil[1] is not None and wil[1] < need:
        return (f"목표에 필요한 승률 {_pct(need, 0, False)}가 지금 승률 범위({_pct(wil[0], 0, False)}~{_pct(wil[1], 0, False)}) 위에 "
                "있어요 → 지금 그대로는 목표 속도가 아니에요" + tail, "bad")
    if wil[0] is not None and wil[0] > need:
        return (f"지금 승률 범위({_pct(wil[0], 0, False)}~{_pct(wil[1], 0, False)})가 필요한 승률 {_pct(need, 0, False)}보다 위예요 → "
                "이 속도가 이어지면 목표 근처예요" + tail, "good")
    return (f"필요한 승률 {_pct(need, 0, False)}가 지금 승률 범위({_pct(wil[0], 0, False)}~{_pct(wil[1], 0, False)}) 안이에요 → "
            "더 쌓여야 알 수 있어요" + tail, "warn")


def paper_rows(trades: list) -> list:
    """A paper account's closed trades as goal rows (the wallet before = equity_after - pnl)."""
    out = []
    for t in trades:
        eq = (t["equity_after"] - t["pnl"]) if t.get("equity_after") is not None and t.get("pnl") is not None else None
        out.append({"pnl": t.get("pnl"), "roe": t.get("roe"), "eq": eq, "entry": t.get("entry_time"), "exit": t.get("exit_time")})
    return out


def _eq_at(rows: list, ms: int) -> tuple:
    """(equity at ``ms``: the last sample at or before it, else the first after it; its time)."""
    before = [r for r in rows if r[0] is not None and r[0] <= ms]
    if before:
        return before[-1][1], before[-1][0]
    return (rows[0][1], rows[0][0]) if rows else (None, None)


def paper_goal(aid: str, name_ko: str, acc: dict, since: Optional[int], now: int, target: float) -> dict:
    """The goal card of a paper account (read_paper's account answer), its trades from ``since`` on."""
    if not acc or not acc.get("known"):
        return {"id": aid, "name_ko": name_ko, "kind": "paper", "state": "missing", "reason_ko": "페이퍼 계좌 기록이 아직 없어요"}
    trades = [t for t in acc.get("trades") or [] if since is None or (t.get("entry_time") or 0) >= since]
    rows = paper_rows(trades)
    entries = [t.get("entry_time") for t in trades]
    pos = acc.get("position")
    if pos and pos.get("entry_time") is not None:
        entries.append(pos["entry_time"])
    start = since if since is not None else (acc.get("since_ms") or (trades[0]["entry_time"] if trades else None))
    m0, mdays = month_from(now)
    f_ms = max(m0, start) if start is not None else m0
    curve = [[t.get("exit_time"), t.get("equity_after")] for t in acc.get("trades") or [] if t.get("equity_after") is not None]
    init = acc.get("initial")
    eq_from = next((e for t, e in reversed(curve) if t is not None and t <= f_ms), init)
    eq_now = acc.get("wallet") if acc.get("wallet") is not None else (curve[-1][1] if curve else init)
    return {"id": aid, "name_ko": name_ko, "kind": "paper", "state": "ok", "since_ms": start,
            **goal_numbers(rows, entries, start, now, target, eq_from, eq_now, f_ms)}


def live_goal(x: dict, path: str, since: Optional[int], now: int, target: float) -> dict:
    """The goal card of a follower: its closed trades while it followed ``path`` from ``since`` on (era_trades), the
    wallet before each from its own equity samples (deposits taken out: liveinsight.exec_equity)."""
    from . import liveinsight as I
    r = x["record"]
    base = {"id": x["id"], "name_ko": x["name_ko"], "kind": "live"}
    if r.get("state") != "ok":
        return {**base, **_src(r)}
    seg0 = next((s[0] for s in x.get("segs") or [] if LP.same(s[1], path)), None) if len(x.get("segs") or []) > 1 else None
    start = max(v for v in (since, seg0, r.get("since_ms")) if v is not None) if any(v is not None for v in (since, seg0, r.get("since_ms"))) else None
    ts = L.era_trades(x, path, start)
    eqs = I.exec_equity(r["path"])
    erows = eqs.get("rows") or [] if eqs.get("state") == "ok" else []
    rows = [{"pnl": t.get("pnl"), "roe": t.get("roe"), "eq": _eq_at(erows, t["entry_ts"])[0] if t.get("entry_ts") is not None else None,
             "entry": t.get("entry_ts"), "exit": t.get("exit_ts"), "est": t.get("est")} for t in ts]
    entries = [t.get("entry_ts") for t in ts]
    if r.get("position") and r["position"].get("entry_time") is not None:
        entries.append(r["position"]["entry_time"])
    m0, _md = month_from(now)
    f_ms = max(m0, start) if start is not None else m0
    eq_from, _t = _eq_at(erows, f_ms)
    eq_now = erows[-1][1] if erows else None
    out = {**base, "state": "ok", "since_ms": start, "real": r.get("mode") == "mainnet", "est": sum(1 for t in ts if t.get("est")),
           **goal_numbers(rows, entries, start, now, target, eq_from, eq_now, f_ms)}
    if eqs.get("state") != "ok":
        out["equity_ko"] = "잔고 기록을 읽지 못해 거래마다의 잔고 비율을 몰라요"
    return out


# ---------------------------------------------------------------- 실거래가 덜 버는 이유 (one follower)
def gap_item(x: dict, path: str, since: Optional[int], now: int) -> dict:
    """The same trades paper vs live (pairs_of), where the difference comes from (fill_gaps: entry and exit price gaps and
    the fee in net ROE points at the trade's leverage), and the paper trades it did not follow and why (why_missed)."""
    name = x["name_ko"]
    title, q = f"{name}: 실거래가 덜 버는 이유", f"같은 신호에서 {name}가 페이퍼보다 얼마나, 어디서 덜 버나?"
    r = x["record"]
    if r.get("state") != "ok":
        return item(f"gap_{x['id']}", title, q, **_src(r), lead_ko=r.get("reason_ko") or "실행기 기록을 아직 못 읽어요")
    pairs = L.pairs_of(x)
    lts = L.era_trades(x, path, since)
    matched = [(lt, pairs[str(lt["key"])]) for lt in lts if str(lt["key"]) in pairs]
    diffs = [lt["roe"] - pt["roe"] for lt, pt in matched if lt.get("roe") is not None and pt.get("roe") is not None]
    keys = {str(lt["key"]) for lt in lts}
    try:
        ladder_from = (x.get("config") or {}).get("ladder_from") or "paper"
        fg = L.fill_gaps(r["path"], [g for g in L.gap_rows(x, since) if str(g["key"]) in keys], r.get("exchange") or "binance",
                         ladder_from=ladder_from)
    except Exception as exc:  # noqa: BLE001  (one part never takes the panel down)
        fg = {"state": "error", "reason_ko": "체결 차이를 계산하지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    pa = L._paper_of(x, path)
    acc = (pa.get("accounts") or {}).get(x["follows"]) if pa.get("state") == "ok" else None
    used = {pt["id"] for pt in pairs.values() if LP.same(pt.get("paper_path") or path, path)}
    start = max(v for v in (since, r.get("since_ms")) if v is not None) if (since is not None or r.get("since_ms") is not None) else None
    unf = [pt for pt in (acc or {}).get("trades") or [] if pt.get("entry_time") is not None
           and (start is None or pt["entry_time"] >= start) and L.followed_at(x, path, pt["entry_time"]) and pt["id"] not in used]
    why: dict = {}
    for pt in unf:
        w = L.why_missed(r, pt, x["follows"])
        if w.get("state") in ("before", "open"):
            continue
        b = why.setdefault(w.get("why_ko") or "?", {"why_ko": w.get("why_ko") or "?", "n": 0, "wins": 0, "roe_sum": 0.0})
        b["n"] += 1
        b["wins"] += 1 if (pt.get("pnl") or 0) > 0 else 0
        b["roe_sum"] += pt.get("roe") or 0.0
    miss = sorted(why.values(), key=lambda b: -b["n"])
    gap = _mean(diffs)
    parts = []
    if fg.get("state") == "ok":
        for k, ko in (("entry_roe", "진입 가격"), ("exit_roe", "청산 가격"), ("fee_roe", "수수료")):
            if fg.get(k) is not None:
                parts.append((fg[k], ko))
    worst = min(parts) if parts else None
    if not matched:
        lead = f"{name}가 이 봇을 따라 닫은 거래가 아직 없어요" + (f" · 안 따라간 페이퍼 거래 {sum(b['n'] for b in miss)}번" if miss else "")
        tone = "thin"
    else:
        if gap is None:
            lead = f"같은 거래 {len(matched)}번: 순ROE를 아직 견주지 못했어요"
        elif gap < 0:
            lead = f"같은 거래 {len(diffs)}번: 실거래가 페이퍼보다 거래당 순ROE {_pct(-gap, 1, False)}p 덜 벌어요"
        else:
            lead = f"같은 거래 {len(diffs)}번: 실거래가 페이퍼보다 거래당 순ROE {_pct(gap, 1, False)}p 더 벌었어요"
        if worst is not None and worst[0] < 0:
            lead += f" · 가장 큰 몫: {worst[1]} {_pct(worst[0])}p"
        tone = "bad" if gap is not None and gap < -0.02 else "warn" if gap is not None and gap < 0 else "good"
    kp = [kpi("같은 거래", len(matched), "n"), kpi("거래당 순ROE 차이", gap, "pctp", "bad" if gap is not None and gap < 0 else None)]
    if fg.get("state") == "ok":
        kp += [kpi("진입 가격 차이", fg.get("entry_roe"), "pctp", sub=f"{fg.get('entry_n', 0)}번 잼"),
               kpi("청산 가격 차이", fg.get("exit_roe"), "pctp", sub=f"{fg.get('exit_n', 0)}번 잼"),
               kpi("수수료 차이", fg.get("fee_roe"), "pctp", sub=f"페이퍼 {100 * L.PAPER_TAKER:.3f}% 기준")]
    kp.append(kpi("안 따라간 페이퍼 거래", sum(b["n"] for b in miss), "n",
                  sub=f"그 거래들 페이퍼 순ROE 합 {_pct(sum(b['roe_sum'] for b in miss))}" if miss else None))
    out = item(f"gap_{x['id']}", title, q, lead_ko=lead, tone=tone, kpis=kp, n=len(matched),
               table={"cols": [{"key": "why_ko", "label_ko": "안 따라간 이유", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
                               {"key": "wins", "label_ko": "그중 페이퍼가 이긴 것", "fmt": "n"},
                               {"key": "roe_sum", "label_ko": "페이퍼 순ROE 합", "fmt": "pct"}], "rows": miss} if miss else None,
               need_ko=f"같은 거래 {FEW}번부터 믿을 만해요 (지금 {len(matched)}번)",
               use_ko="차이가 진입·청산 가격에서 크면 주문 방식(지정가 등)이, 수수료에서 크면 거래소·등급이, 안 따라간 거래에서 크면 "
                      "신호등·멈춤 규칙이 다음에 볼 곳이에요",
               how_ko=f"같은 코인 · 같은 방향 · 페이퍼 진입 {L.MATCH_MS // MIN}분 안의 짝 (거래 탭과 같은 짝). 가격 차이는 체결가 기준, 배수를 곱한 순ROE %p",
               link="#/cost")
    if fg.get("state") not in (None, "ok"):
        out["sub_state"] = _src(fg)
    return out


# ---------------------------------------------------------------- 신호등 검증 (one follower with a light)
def light_item(x: dict, trades: list) -> Optional[dict]:
    """The follower's signal light (its own rule, livebots.light) replayed before each of the paper bot's trades: the
    record of the trades a green light lets through, a red one holds back, and the ones before it had its N trades."""
    cfg = x.get("config") or {}
    n, mw = _i(cfg.get("signal_light_n")) or 0, _f(cfg.get("signal_light_min_win"))
    if cfg.get("state") != "ok" or n <= 0:
        return None
    closed = sorted([t for t in trades if t.get("exit_time") is not None and t.get("pnl") is not None],
                    key=lambda t: (t["exit_time"], t.get("id") or 0))
    by = {k: {"state": k, "n": 0, "wins": 0, "roe_sum": 0.0} for k in ("green", "red", "building")}
    for t in sorted(trades, key=lambda t: t.get("entry_time") or 0):
        if t.get("entry_time") is None or t.get("pnl") is None:
            continue
        prior = [c["pnl"] for c in closed if c["exit_time"] < t["entry_time"]][::-1]
        st = L.light(n, mw, prior)["state"]
        if st not in by:
            continue
        b = by[st]
        b["n"] += 1
        b["wins"] += 1 if t["pnl"] > 0 else 0
        b["roe_sum"] += t.get("roe") or 0.0
    ko = {"green": "초록 (따라 들어감)", "red": "빨강 (안 들어감)", "building": "근거 쌓는 중 (모두 따라감)"}
    rows = []
    for k in ("green", "red", "building"):
        b = by[k]
        rows.append({**b, "state_ko": ko[k], "win_rate": b["wins"] / b["n"] if b["n"] else None,
                     "roe_mean": b["roe_sum"] / b["n"] if b["n"] else None, "roe_sum": b["roe_sum"] if b["n"] else None})
    g, rd = by["green"], by["red"]
    title = f"{x['name_ko']}: 신호등 {n}번 · {_pct(mw, 0, False)} 검증"
    q = f"최근 {n}번 중 {_pct(mw, 0, False)} 넘게 이겼을 때만 따라가는 규칙이 실제로 나쁜 거래를 거르나?"
    if not g["n"] and not rd["n"]:
        lead, tone = f"페이퍼 거래가 아직 {n}번이 안 돼 신호등이 근거를 쌓는 중이에요 (그동안은 모두 따라가요)", "thin"
    else:
        gw = g["wins"] / g["n"] if g["n"] else None
        rw = rd["wins"] / rd["n"] if rd["n"] else None
        lead = f"초록일 때 {g['n']}번 승률 {_pct(gw, 0, False)} · 빨강일 때 {rd['n']}번 승률 {_pct(rw, 0, False)}"
        if rd["n"]:
            lead += f" → 빨강에서 쉰 거래의 페이퍼 순ROE 합 {_pct(rd['roe_sum'])} ({'피한 손실' if rd['roe_sum'] < 0 else '놓친 이익'})"
        tone = "good" if rd["n"] and rd["roe_sum"] < 0 else "warn" if rd["n"] else "thin"
    return item(f"light_{x['id']}", title, q, lead_ko=lead, tone=tone, n=g["n"] + rd["n"],
                kpis=[kpi("초록 거래", g["n"], "n"), kpi("빨강 거래", rd["n"], "n"), kpi("빨강에서 쉰 순ROE 합", rd["roe_sum"] if rd["n"] else None)],
                table={"cols": [{"key": "state_ko", "label_ko": "그때 신호등", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
                                {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"}, {"key": "roe_mean", "label_ko": "평균 순ROE", "fmt": "pct"},
                                {"key": "roe_sum", "label_ko": "순ROE 합", "fmt": "pct"}], "rows": rows},
                need_ko=f"빨강 거래가 {FEW}번은 쌓여야 규칙이 돕는지 말할 수 있어요 (지금 {rd['n']}번)",
                use_ko="빨강에서 쉰 거래들이 계속 이기면 신호등이 이익을 막는 것이라 기준을 낮출지, 계속 지면 지금 규칙을 지킬지 정해요",
                how_ko="페이퍼 거래마다 그 진입 전에 닫힌 페이퍼 거래 마지막 N번으로 실행기와 같은 규칙을 다시 계산 (실행기 기록과 별개)")


# ---------------------------------------------------------------- 진 거래는 한때 얼마나 갔나 (a paper account)
def mfe_item(iid: str, title: str, q: str, path: str, account: str, trades: list, rt: float, edges: tuple, edge_ko: tuple,
             rule_db: Optional[str], lev_of: Optional[Callable] = None, use_ko: str = "", how_extra: str = "") -> dict:
    """Each closed paper trade's best net ROE while it was open (the engine's best price, else the rule bot's 1m bars),
    the losers and the winners in buckets (``edges``: net ROE bounds, ``edge_ko`` their words, one more than the edges)."""
    from . import livepos as P
    ex = P.paper_trade_extremes(path, account, 2000)
    conn, bstate = P.open_bars(rule_db) if rule_db else (None, {"state": "missing"})
    rows, unknown = [], 0
    try:
        for t in trades:
            if t.get("exit_time") is None or t.get("pnl") is None:
                continue
            e = ex.get(t.get("id")) or {}
            side = int(e.get("side") or t.get("side") or 0)
            entry = e.get("entry_price") or t.get("entry_price")
            lev = lev_of(t.get("symbol")) if lev_of else (e.get("leverage") or t.get("leverage"))
            if e.get("mfe_price") and e.get("mae_price") and e["mfe_price"] > 0 and e["mae_price"] > 0:
                v = P.excursion(side, entry, lev, rt, 0.0, e["mfe_price"], e["mae_price"], "engine")
            else:
                v = P.from_bars(conn, bstate, t.get("symbol"), side, entry, lev, rt, 0.0, t.get("entry_time"), t["exit_time"])
            if v.get("state") != "ok" or v.get("mfe") is None:
                unknown += 1
                continue
            rows.append((t["pnl"] > 0, v["mfe"]))
    finally:
        if conn is not None:
            conn.close()

    def bucket(m: float) -> int:
        return sum(1 for b in edges if m >= b)
    table = []
    for k, ko in enumerate(edge_ko):
        lose = sum(1 for won, m in rows if not won and bucket(m) == k)
        win = sum(1 for won, m in rows if won and bucket(m) == k)
        table.append({"range_ko": ko, "losers": lose, "winners": win})
    losers = [m for won, m in rows if not won]
    top = edges[-1] if edges else None
    went = sum(1 for m in losers if top is not None and m >= edges[0])
    if not rows:
        lead, tone = "닫힌 페이퍼 거래의 최고 순ROE를 아직 못 쟀어요", "thin"
    else:
        lead = (f"진 거래 {len(losers)}번 중 {went}번은 한때 순ROE {_pct(edges[0], 0)} 넘게 갔다가 돌아왔어요"
                if losers else "진 거래가 아직 없어요")
        tone = "warn" if went else "good" if losers else "thin"
    return item(iid, title, q, lead_ko=lead, tone=tone, n=len(rows),
                kpis=[kpi("잰 거래", len(rows), "n"), kpi("진 거래", len(losers), "n"),
                      kpi(f"그중 한때 {_pct(edges[0], 0)} 넘게 간 것", went, "n"), kpi("못 잰 거래", unknown, "n")],
                table={"cols": [{"key": "range_ko", "label_ko": "열려 있는 동안 최고 순ROE", "fmt": "text"},
                                {"key": "losers", "label_ko": "진 거래", "fmt": "n"}, {"key": "winners", "label_ko": "이긴 거래", "fmt": "n"}],
                       "rows": table},
                need_ko=f"진 거래 {FEW}번부터 계단 높이를 말할 수 있어요 (지금 {len(losers)}번)", use_ko=use_ko,
                how_ko="페이퍼 엔진이 기록한 최고 가격(없으면 규칙봇 1분봉의 최고·최저)으로 수수료를 뺀 순ROE" + how_extra)


# ---------------------------------------------------------------- 나눠 보기 (a paper account)
def split_item(iid: str, title: str, q: str, trades: list, key: Callable, label_ko: str, order: Optional[list] = None,
               use_ko: str = "", min_n: int = 10) -> dict:
    by: dict = {}
    for t in trades:
        if t.get("pnl") is None:
            continue
        k = key(t)
        if k is None:
            continue
        b = by.setdefault(k, {"key": k, "n": 0, "wins": 0, "roe_sum": 0.0, "pnl": 0.0})
        b["n"] += 1
        b["wins"] += 1 if t["pnl"] > 0 else 0
        b["roe_sum"] += t.get("roe") or 0.0
        b["pnl"] += t["pnl"]
    keys = [k for k in (order or []) if k in by] + sorted((k for k in by if k not in (order or [])), key=lambda k: -by[k]["n"])
    rows = [{**by[k], "win_rate": by[k]["wins"] / by[k]["n"], "roe_mean": by[k]["roe_sum"] / by[k]["n"], "few": by[k]["n"] < min_n}
            for k in keys]
    big = [r for r in rows if not r["few"]]
    if not rows:
        lead, tone = ("닫힌 거래가 아직 없어요" if not trades else f"{label_ko}을 아는 닫힌 거래가 아직 없어요"), "thin"
    elif not big:
        lead, tone = f"아직 어느 칸도 {min_n}번이 안 돼요 (표본 적음)", "thin"
    else:
        best = max(big, key=lambda r: r["roe_sum"])
        worst = min(big, key=lambda r: r["roe_sum"])
        lead = f"가장 번 칸: {best['key']} (순ROE 합 {_pct(best['roe_sum'])}, {best['n']}번)"
        if worst is not best:
            lead += f" · 가장 잃은 칸: {worst['key']} ({_pct(worst['roe_sum'])}, {worst['n']}번)"
        tone = "warn" if worst["roe_sum"] < 0 else "good"
    return item(iid, title, q, lead_ko=lead, tone=tone, n=sum(r["n"] for r in rows),
                table={"cols": [{"key": "key", "label_ko": label_ko, "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
                                {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"}, {"key": "roe_mean", "label_ko": "평균 순ROE", "fmt": "pct"},
                                {"key": "roe_sum", "label_ko": "순ROE 합", "fmt": "pct"}], "rows": rows},
                need_ko=f"칸마다 {min_n}번 넘어야 비교해요 (적은 칸은 '표본 적음')", use_ko=use_ko,
                how_ko="닫힌 페이퍼 거래를 칸별로 나눠 센 것 (순ROE: 그 거래 배수의 수수료 뺀 증거금 대비 %)")


# ---------------------------------------------------------------- the paper bots of the main site (trend, vwap)
def _bot_of(bots: list, which: str) -> Optional[dict]:
    from . import livevwap as VW
    for b in bots:
        cfg = (b.get("read") or {}).get("_cfg") if (b.get("read") or {}).get("state") == "ok" else None
        if which == "vwap" and VW.is_vwap(cfg):
            return b
        if which == "trend" and b["id"] == "paper":
            return b
    return None


def _followers(execs: list, path: str) -> list:
    return [x for x in execs if LP.same(x["paper_path"], path)]


def site_bot(which: str, p: dict, now: int, more: dict) -> dict:
    """trend / vwap: the bot's paper account and its followers (livebots.sources), the goal cards and the items."""
    target = 1 + _target()
    _cfgs, _fol, paper, execs = L.sources(p, now)
    bots = L.paper_bots(p, paper, execs)
    b = _bot_of(bots, which)
    if b is None or (which == "vwap" and b["read"].get("state") != "ok"):
        from . import livevwap as VW
        return {"state": "off", "ko": VW.OFF_KO if which == "vwap" else "추세판단 봇 페이퍼 기록이 아직 없어요"}
    pr = b["read"]
    if pr.get("state") != "ok":
        return {"state": pr.get("state"), "ko": pr.get("reason_ko") or "페이퍼 기록을 읽지 못했어요", **_src(pr)}
    acc = (pr.get("accounts") or {}).get(L.ACCOUNT) or {}
    if which == "trend":
        tb = L.trend_bot(b["path"])
        since = tb["since"] if tb else acc.get("since_ms")
    else:
        since = acc.get("since_ms")
    trades = [t for t in acc.get("trades") or [] if since is None or (t.get("entry_time") or 0) >= since]
    fol = _followers(execs, b["path"])
    accounts = [paper_goal("paper", "페이퍼(연습)", acc, since, now, target)] + [live_goal(x, b["path"], since, now, target) for x in fol]
    items = []
    for x in fol:
        items.append(_safe(lambda x=x: gap_item(x, b["path"], since, now), f"gap_{x['id']}", f"{x['name_ko']}: 실거래가 덜 버는 이유"))
        li = _safe(lambda x=x: light_item(x, trades), f"light_{x['id']}", f"{x['name_ko']}: 신호등 검증")
        if li:
            items.append(li)
    rt = float(pr.get("round_trip") or 0.0)
    lad = pr.get("ladder") or {}
    first = _f(lad.get("first_lock")) if isinstance(lad, dict) else None
    edges = (0.05, 0.10, 0.20) if not first or first <= 0.12 else (first / 2, first, 2 * first)
    edge_ko = (f"{_pct(edges[0], 0)} 안", f"{_pct(edges[0], 0)} ~ {_pct(edges[1], 0)}", f"{_pct(edges[1], 0)} ~ {_pct(edges[2], 0)}",
               f"{_pct(edges[2], 0)} 넘게")
    items.append(_safe(lambda: mfe_item("mfe", "진 거래는 한때 얼마나 갔나", "손절로 끝난 거래가 그 전에 얼마나 수익을 냈었나? (계단·익절 자리를 정하는 근거)",
                                        b["path"], L.ACCOUNT, trades, rt, edges, edge_ko, more.get("rule_db"),
                                        use_ko=(f"한때 {_pct(edges[0], 0)} 넘게 갔다 진 거래가 많으면 첫 계단을 그 아래로 내리는 것이, 거의 없으면 "
                                                "계단은 그대로 두고 진입을 보는 것이 다음 연구예요")),
                       "mfe", "진 거래는 한때 얼마나 갔나"))
    if which == "trend":
        items.append(_safe(lambda: split_item("roles", "어느 역할이 버나", "눌림 · 자리 · 돌파 · 횡보 · 추세 중 어느 역할이 목표에 보태나?", trades,
                                              lambda t: L.TREND_ROLE.get(t.get("strategy_id")) if t.get("strategy_id") else None, "역할",
                                              list(L.TREND_ROLES),
                                              use_ko="잃는 역할이 표본이 쌓여도 계속 잃으면 그 역할을 빼거나 진입 조건을 바꾸는 것이 2주 검토의 안건이에요"),
                           "roles", "어느 역할이 버나"))
        items.append(_safe(lambda: split_item("tf", "어느 진입봉이 버나", "30분 · 1시간 · 4시간 진입 중 어디가 버나?", trades,
                                              lambda t: TF_KO.get(t.get("timeframe"), t.get("timeframe")), "진입봉", ["30분", "1시간", "4시간"],
                                              use_ko="한 진입봉이 계속 잃으면 그 봉을 끄는 것이 다음 검토 안건이에요"), "tf", "어느 진입봉이 버나"))
    else:
        items.append(_safe(lambda: split_item("strategies", "어느 매매법이 버나", "VWAP 개선판 안의 매매법 중 어느 것이 목표에 보태나?", trades,
                                              lambda t: t.get("strategy_id"), "매매법",
                                              use_ko="표본이 쌓여도 잃는 매매법은 빼는 것이 다음 검토 안건이에요"), "strategies", "어느 매매법이 버나"))
        items.append(_safe(lambda: vwap_block_item(p, now, more), "blocked", "막은 신호는 어땠나"))
    return {"state": "ok", "since_ms": since, "accounts": accounts, "items": [i for i in items if i]}


def vwap_block_item(p: dict, now: int, more: dict) -> dict:
    """막은 신호 (livevwap.blocked): the gates' virtual results by reason, in its own words."""
    from . import livevwap as VW
    b = VW.blocked(p, now, more)
    v = b.get("virtual") or {}
    title, q = "막은 신호는 어땠나", "4시간 추세 반대 · 변동성 높음 같은 관문이 손실을 막았나, 이익을 막았나?"
    if v.get("state") != "ok":
        return item("blocked", title, q, **_src(v), lead_ko=v.get("reason_ko") or "1분 감시 기록이 아직 없어요", link="#/vwblock")
    kinds = v.get("kinds") or []
    rows = [{"why_ko": k.get("ko"), "n": k.get("n"), "closed": k.get("closed"), "wins": k.get("wins"), "losses": k.get("losses"),
             "roe_sum": k.get("roe_sum"), "read_ko": k.get("read_ko")} for k in kinds]
    g = v.get("gate") or {}
    s = g.get("roe_sum")
    lead = (f"관문이 막은 신호 {g.get('n', 0)}번 (끝난 것 {g.get('closed', 0)}번): 가상 순ROE 합 {_pct(s)} → "
            + ("막아서 손해를 줄였어요" if s is not None and s < 0 else "막아서 이익을 놓쳤어요" if s else "아직 본전")) if g.get("n") else "관문이 막은 신호가 아직 없어요"
    return item("blocked", title, q, lead_ko=lead, tone="good" if s is not None and s < 0 else "warn" if s else "thin", n=g.get("closed") or 0,
                table={"cols": [{"key": "why_ko", "label_ko": "막은 이유", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
                                {"key": "closed", "label_ko": "끝난 것", "fmt": "n"}, {"key": "roe_sum", "label_ko": "가상 순ROE 합", "fmt": "pct"}],
                       "rows": rows},
                need_ko=f"관문마다 끝난 가상 거래가 {FEW}번은 쌓여야 말할 수 있어요", link="#/vwblock",
                use_ko="막은 신호가 계속 이겼다면 그 관문을 풀지, 계속 졌다면 지금 그대로 둘지 정해요",
                how_ko="1분 감시가 '그때 들어갔다면'을 봇의 엔진으로 가상 계산한 것 (계좌가 비어 있었다고 침)")


# ---------------------------------------------------------------- 믹스 30분 봇
def mix_margin_share(t: dict) -> Optional[float]:
    """An entry's margin as a share of the wallet before it: qty x entry / leverage / equity_before."""
    q, e, lev, eq = t.get("qty"), t.get("entry"), t.get("leverage"), t.get("equity_before")
    return q * e / lev / eq if q and e and lev and eq else None


def mix_bot(p: dict, now: int, bot: str = "mix") -> dict:
    """A mix bot's goal part (``bot``: livemix.PROFILES, the 믹스 30분 봇 or the 바이비트 봇)."""
    from . import livemix as MX
    prof = MX.PROFILES[bot]
    target = 1 + _target()
    mp = MX.paths(bot=bot)
    loaded = {bid: MX.load_bot(bid, mp[bid], now) for bid, *_r in prof.bots}
    if all(b["status"]["state"] == "off" for b in loaded.values()):
        return {"state": "off", "ko": MX.OFF_KO["live"] if bot == "mix" else MX.off_ko(prof, "live")}
    accounts, per = [], {}
    for bid, ko in (("live", f"{prof.account_ko} (실거래)"), ("paper", "모의")):
        b = loaded[bid]
        if b["status"]["state"] == "off" or b["lg"].get("state") != "ok":
            accounts.append({"id": bid, "name_ko": ko, "kind": "live" if bid == "live" else "paper",
                             "state": "missing" if b["status"]["state"] == "off" else b["lg"].get("state") or "error",
                             "reason_ko": b["status"].get("ko") or b["lg"].get("reason_ko")})
            continue
        cfg = b["conf"].get("cfg")
        ts = list(reversed(MX.trades_of(b["lg"]["rows"], cfg)))         # oldest first
        new = [t for t in ts if (mix_margin_share(t) or 0) >= 0.3]
        old = [t for t in ts if t not in new]
        since = new[0]["opened_ms"] if new else None
        per[bid] = {"all": ts, "new": new, "old": old, "since": since, "b": b, "cfg": cfg}
        rows = [{"pnl": t.get("pnl"), "roe": t.get("roe"), "eq": t.get("equity_before"), "entry": t.get("opened_ms"), "exit": t.get("exit_ms")}
                for t in new]
        entries = [t.get("opened_ms") for t in new]
        eqv = MX.equity_view(bid, b)
        eq_now = (eqv.get("now") or {}).get("value")
        m0, _md = month_from(now)
        f_ms = max(m0, since) if since is not None else m0
        eq_from = next((t["equity_before"] for t in new if t.get("opened_ms") is not None and t["opened_ms"] >= f_ms and t.get("equity_before")), None)
        if since is None:
            accounts.append({"id": bid, "name_ko": ko, "kind": "live" if bid == "live" else "paper", "state": "missing",
                             "reason_ko": "새 설정(증거금 40%)으로 닫힌 거래가 아직 없어요"})
            continue
        accounts.append({"id": bid, "name_ko": ko, "kind": "live" if bid == "live" else "paper", "state": "ok", "since_ms": since,
                         "real": bid == "live", **goal_numbers(rows, entries, since, now, target, eq_from, eq_now, f_ms)})
    items = []
    if per:
        if bot == "mix":                                # the 바이비트 봇: margin 40 % from its first trade, no floor
            items.append(_safe(lambda: mix_before_after(per), "before_after", "새 설정 전후"))
        items.append(_safe(lambda: mix_steps(per), "steps", "계단 몇 칸까지 갔나"))
        if bot == "mix":
            items.append(_safe(lambda: mix_floor(per), "floor", "잔고 하한까지 손절 몇 번"))
    if "live" in per and "paper" in per:
        items.append(_safe(lambda: mix_twin(per), "twin", "실거래 vs 모의"))
    return {"state": "ok", "accounts": accounts, "items": [i for i in items if i]}


def _rec(ts: list) -> dict:
    known = [t for t in ts if t.get("pnl") is not None]
    wins = sum(1 for t in known if t["pnl"] > 0)
    shares = [t["pnl"] / t["equity_before"] for t in known if t.get("equity_before")]
    return {"n": len(known), "wins": wins, "win_rate": wins / len(known) if known else None, "pnl": sum(t["pnl"] for t in known) if known else None,
            "avg_win": _mean([x for x in shares if x > 0]), "avg_loss": _mean([-x for x in shares if x <= 0]),
            "growth": _mean([math.log1p(x) for x in shares if x > -1])}


def mix_before_after(per: dict) -> dict:
    rows = []
    for bid, ko in (("live", "실거래"), ("paper", "모의")):
        if bid not in per:
            continue
        for k, kko in (("old", "예전 (손절 1번 = 잔고 0.25%)"), ("new", "새 설정 (증거금 40% · 순ROE 계단)")):
            r = _rec(per[bid][k])
            rows.append({"bot_ko": ko, "set_ko": kko, **r})
    nv = next((r for r in rows if r["bot_ko"] == "실거래" and r["set_ko"].startswith("새")), None) or next((r for r in rows if r["set_ko"].startswith("새")), None)
    if not nv or not nv["n"]:
        lead, tone = "새 설정으로 닫힌 거래가 아직 없어요 (10/26부터)", "thin"
    else:
        lead = (f"새 설정 {nv['n']}번: 승률 {_pct(nv['win_rate'], 0, False)} · 이길 때 잔고 {_pct(nv['avg_win'])} · 질 때 {_pct(-(nv['avg_loss'] or 0))}"
                f" · 거래당 잔고 {_pct(math.expm1(nv['growth']) if nv['growth'] is not None else None)}")
        tone = "good" if (nv["growth"] or 0) > 0 else "bad"
    return item("before_after", "새 설정(10/26) 전후", "증거금 40%와 순ROE 계단(12→10 · 17→15 · 22→20 …)으로 바꾼 뒤 거래당 잔고가 얼마나 움직이나?",
                lead_ko=lead, tone=tone, n=nv["n"] if nv else 0,
                table={"cols": [{"key": "bot_ko", "label_ko": "봇", "fmt": "text"}, {"key": "set_ko", "label_ko": "설정", "fmt": "text"},
                                {"key": "n", "label_ko": "번", "fmt": "n"}, {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"},
                                {"key": "avg_win", "label_ko": "이길 때 잔고", "fmt": "pct"}, {"key": "avg_loss", "label_ko": "질 때 잔고", "fmt": "pctneg"},
                                {"key": "pnl", "label_ko": "손익", "fmt": "usd"}], "rows": rows},
                need_ko=f"새 설정 거래 {FEW}번부터 예전과 비교해요", link="#/mixperf",
                use_ko="손절 한 번이 잔고를 크게 깎는 크기라, 승률이 설계(20~40%)대로면 계단에서 얼마나 크게 먹는지가 목표를 정해요",
                how_ko="진입 때 증거금이 잔고의 30% 넘으면 새 설정 거래로 셈 (10/26 바꾼 뒤), 잔고 비율은 진입 전 잔고 대비")


def mix_steps(per: dict) -> dict:
    src = per.get("live") or per.get("paper")
    bid = "live" if "live" in per else "paper"
    ts = src["new"] or src["all"]
    by: dict = {}
    for t in ts:
        s = min(int(t.get("step") or 0), 4)
        b = by.setdefault(s, {"step": s, "n": 0, "wins": 0, "pnl": 0.0, "roe_sum": 0.0})
        b["n"] += 1
        b["wins"] += 1 if (t.get("pnl") or 0) > 0 else 0
        b["pnl"] += t.get("pnl") or 0.0
        b["roe_sum"] += t.get("roe") or 0.0
    lad = getattr(src.get("cfg"), "ladder", None) or {"trigger": 12, "lock": 10, "step": 5}     # its config's net-ROE ladder
    tg, lk, sp = (lad[k] for k in ("trigger", "lock", "step"))
    ko = {0: "계단 전 (손절·수동)", 1: f"1칸 ({tg:g}% 닿고 {lk:g}% 잠금)", 2: f"2칸 ({tg + sp:g}→{lk + sp:g})",
          3: f"3칸 ({tg + 2 * sp:g}→{lk + 2 * sp:g})", 4: "4칸 넘게"}
    rows = [{**by[k], "step_ko": ko[k], "roe_mean": by[k]["roe_sum"] / by[k]["n"]} for k in sorted(by)]
    up = sum(r["n"] for r in rows if r["step"] > 0)
    n = sum(r["n"] for r in rows)
    lead = f"닫힌 {n}번 중 계단에 닿은 것 {up}번 ({_pct(up / n, 0, False)})" if n else "닫힌 거래가 아직 없어요"
    return item("steps", "계단 몇 칸까지 갔나", "이긴 거래가 몇 칸까지 올라갔나? 몇 칸에서 끝나는 게 흔한가?", lead_ko=lead,
                tone="good" if up else "thin", n=n,
                table={"cols": [{"key": "step_ko", "label_ko": "끝난 칸", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
                                {"key": "roe_mean", "label_ko": "평균 순ROE", "fmt": "pct"}, {"key": "pnl", "label_ko": "손익", "fmt": "usd"}],
                       "rows": rows},
                need_ko=f"계단에 닿은 거래 {FEW}번부터 칸 간격을 말할 수 있어요 (지금 {up}번)",
                use_ko=f"1칸에서 끝나는 게 대부분이면 첫 칸({tg:g}→{lk:g})이, 3칸 넘게 가는 게 많으면 칸 간격({sp:g}%)이 다음 연구예요",
                how_ko=f"{'실거래' if bid == 'live' else '모의'} 봇 기록의 청산 때 칸 수 (새 설정 거래, 없으면 모든 거래)")


def mix_floor(per: dict) -> dict:
    from . import livemix as MX
    rows = []
    for bid, ko in (("live", "실거래"), ("paper", "모의")):
        if bid not in per:
            continue
        ev = MX.equity_view(bid, per[bid]["b"])
        r = _rec(per[bid]["new"])
        now_eq = (ev.get("now") or {}).get("value")
        loss = r.get("avg_loss")
        left = None
        if now_eq and ev.get("floor") and loss and loss > 0 and now_eq > ev["floor"]:
            left = math.floor(math.log(ev["floor"] / now_eq) / math.log1p(-loss))
        rows.append({"bot_ko": ko, "now": now_eq, "floor": ev.get("floor"), "floor_frac": ev.get("floor_frac"), "avg_loss": loss, "stops_left": left})
    lv = rows[0] if rows else {}
    if lv.get("stops_left") is not None:
        lead = (f"{lv['bot_ko']} 잔고 ${lv['now']:.2f}, 하한 ${lv['floor']:.2f} (시작의 {_pct(lv['floor_frac'], 0, False)}): 평균 손절(잔고 "
                f"{_pct(-(lv['avg_loss'] or 0))})로 {lv['stops_left']}번 더 지면 새 진입이 멈춰요")
        tone = "bad" if lv["stops_left"] <= 1 else "warn" if lv["stops_left"] <= 3 else "good"
    else:
        lead, tone = "새 설정의 평균 손절을 아직 몰라서 계산하지 못했어요", "thin"
    return item("floor", "잔고 하한까지 손절 몇 번", "증거금 40%에서 손절이 몇 번 이어지면 잔고 하한(시작의 70%)에 닿아 봇이 멈추나?",
                lead_ko=lead, tone=tone, n=len(rows),
                table={"cols": [{"key": "bot_ko", "label_ko": "봇", "fmt": "text"}, {"key": "now", "label_ko": "잔고", "fmt": "usd"},
                                {"key": "floor", "label_ko": "하한", "fmt": "usd"}, {"key": "avg_loss", "label_ko": "평균 손절 (잔고)", "fmt": "pctneg"},
                                {"key": "stops_left", "label_ko": "남은 손절 수", "fmt": "n"}], "rows": rows},
                need_ko="손절이 몇 번 쌓이면 평균 손절이 자리 잡아요",
                use_ko="남은 손절 수가 2~3번이면 하한(0.7)을 낮출지, 증거금 비율을 줄일지 두 분이 정할 때예요 (봇은 스스로 바꾸지 않아요)",
                how_ko="남은 손절 수 = log(하한 ÷ 지금 잔고) ÷ log(1 − 평균 손절 비율), 내림")


def mix_twin(per: dict) -> dict:
    lv, pp = _rec(per["live"]["new"] or per["live"]["all"]), _rec(per["paper"]["new"] or per["paper"]["all"])
    rows = [{"bot_ko": "실거래", **lv}, {"bot_ko": "모의", **pp}]
    if lv["n"] and pp["n"] and lv["growth"] is not None and pp["growth"] is not None:
        d = math.expm1(lv["growth"]) - math.expm1(pp["growth"])
        lead = f"거래당 잔고: 실거래 {_pct(math.expm1(lv['growth']))} · 모의 {_pct(math.expm1(pp['growth']))} (차이 {_pct(d)}p)"
        tone = "bad" if d < -0.01 else "warn" if d < 0 else "good"
    else:
        lead, tone = "둘 다 닫힌 거래가 있어야 비교해요", "thin"
    return item("twin", "실거래 vs 모의", "같은 신호를 받는 실거래와 모의의 차이(체결·수수료·놓친 진입)가 얼마나 되나?", lead_ko=lead, tone=tone,
                n=min(lv["n"], pp["n"]),
                table={"cols": [{"key": "bot_ko", "label_ko": "봇", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
                                {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"}, {"key": "avg_win", "label_ko": "이길 때 잔고", "fmt": "pct"},
                                {"key": "avg_loss", "label_ko": "질 때 잔고", "fmt": "pctneg"}, {"key": "pnl", "label_ko": "손익", "fmt": "usd"}],
                       "rows": rows},
                need_ko=f"둘 다 {FEW}번부터 비교해요", use_ko="차이가 크면 진입 체결(시장가 미끄러짐)과 놓친 진입부터 봐요",
                how_ko="새 설정 거래끼리 (없으면 모든 거래), 모의는 수수료 포함 잔고 변화")


# ---------------------------------------------------------------- V3.9 투비트
def v39_bot(p: dict, now: int, more: dict) -> dict:
    target = 1 + _target()
    try:
        from . import livev39 as V3
        vp = V3.paths()
        raw = V3.read_raw(vp["config"])
        acct = ((raw.get("raw") or {}).get("account") if raw.get("state") == "ok" else None) or V3.ACCOUNT
        ppath = ((raw.get("raw") or {}).get("paper_db") if raw.get("state") == "ok" else None) or vp["paper"]
        plan_raw = raw.get("raw") if raw.get("state") == "ok" else (V3.read_raw(vp["repo_config"]).get("raw") or {})
    except Exception:  # noqa: BLE001  (the screen module of the same day may be missing on an old checkout)
        acct, ppath, plan_raw = "V39_ALL@1h", more.get("rule_db") or "/var/lib/paperbot/paper3.db", {}
    x = None
    if L.installed(p) and any(ex == "toobit" for ex, *_r in L.installed(p)):
        _c, _f2, _paper, execs = L.sources(p, now)
        x = next((e for e in execs if e["id"] == "toobit"), None)
    pr = (L._paper_of(x, ppath) if x else L.read_paper(ppath, [acct], now))
    if pr.get("state") != "ok":
        return {"state": pr.get("state") or "error", "ko": pr.get("reason_ko") or "규칙봇 페이퍼 기록을 읽지 못했어요", **_src(pr)}
    acc = (pr.get("accounts") or {}).get(acct) or {}
    if not acc.get("known"):
        return {"state": "missing", "ko": f"규칙봇 기록에 {acct} 계좌가 아직 없어요"}
    since = acc.get("since_ms")
    trades = list(acc.get("trades") or [])
    accounts = [paper_goal("paper", f"페이퍼 {acct} (규칙봇, 연습)", acc, since, now, target)]
    items = []
    if x is not None:
        accounts.append(live_goal(x, ppath, None, now, target))
        items.append(_safe(lambda: gap_item(x, ppath, None, now), "gap_toobit", "투비트: 실거래가 덜 버는 이유"))
        li = _safe(lambda: light_item(x, trades), "light_toobit", "투비트: 신호등 검증")
        if li:
            items.append(li)
    else:
        accounts.append({"id": "toobit", "name_ko": "투비트", "kind": "live", "state": "off",
                         "reason_ko": "투비트 실행기가 아직 꺼져 있어요 (docs/toobit-ko.md '실행기 켜기')"})
    items.append(_safe(lambda: v39_regime(trades, more.get("rule_db"), now), "regime", "장세: 지금 V3.9에 맞는 장인가"))
    lev = plan_raw.get("leverage_by_symbol") if isinstance(plan_raw.get("leverage_by_symbol"), dict) else {}
    lev_btc, lev_alt = _i(lev.get("BTCUSDT")) or 40, _i(lev.get("*")) or _i(lev.get("default")) or 30

    nc = ((plan_raw.get("net_costs") or {}).get("toobit") or {}) if isinstance(plan_raw.get("net_costs"), dict) else {}
    rt = 2 * ((_f(nc.get("taker_fee")) or 0.0) + (_f(nc.get("slippage")) or 0.0)) if nc else TOOBIT_RT

    def lev_of(sym: Any) -> int:
        return _i(lev.get(sym)) or (lev_btc if sym == "BTCUSDT" else lev_alt)
    # the plan's first rung (form 1: first_lock + trigger_gap; 12 -> 10 since owners 10-27 "투비트봇 12→10 계단으로 바꿔줘")
    lad = plan_raw.get("ladder") if isinstance(plan_raw.get("ladder"), dict) else {}
    lock1 = _f(lad.get("first_lock")) or 0.10
    trig1 = lock1 + (_f(lad.get("trigger_gap")) or 0.0)
    rung = f"{100 * trig1:.0f}→{100 * lock1:.0f}"
    edges = (trig1 / 2, trig1, trig1 + 0.08)
    edge_ko = tuple(f"{100 * e:.0f}%" for e in edges)
    items.append(_safe(lambda: mfe_item(
        "ladder", f"계단 {rung} 확인: 진 거래는 한때 얼마나 갔나",
        "투비트 계획(BTC 40배 · 나머지 30배 · 투비트 비용)으로 보면 손절로 끝난 V3.9 거래가 그 전에 순ROE 몇 %까지 갔나?",
        ppath, acct, trades, rt or TOOBIT_RT, edges,
        (f"{edge_ko[0]} 안", f"{edge_ko[0]} ~ {edge_ko[1]}", f"{edge_ko[1]} ~ {edge_ko[2]}", f"{edge_ko[2]} 넘게"), more.get("rule_db"), lev_of,
        use_ko=(f"첫 계단은 순ROE {edge_ko[1]}에 닿으면 손절을 {100 * lock1:.0f}% 자리로 올려요. {edge_ko[1]} 넘게 갔다 진 페이퍼 거래는 "
                f"실거래 계단이었다면 잠금으로 끝났을 거래예요(배수·체결가가 달라 어림). "
                f"{edge_ko[0]} ~ {edge_ko[1]} 칸에 진 거래가 쌓이면 첫 계단을 더 내릴지 다시 볼 때예요"),
        how_extra=f" · 배수는 투비트 계획(BTC {lev_btc}배 · 나머지 {lev_alt}배), 비용 왕복 {100 * (rt or TOOBIT_RT):.2f}%"), "ladder", f"계단 {rung} 확인"))
    items.append(item("study", "30일 다시 돌려 본 것 (연구 기록)", "투비트 계획을 지난 30일에 그대로 돌리면 어땠나? (실거래 아님)",
                      lead_ko=V39_STUDY["ko"], tone="warn",
                      table={"cols": [{"key": "span_ko", "label_ko": "기간", "fmt": "text"}, {"key": "trades", "label_ko": "번", "fmt": "n"},
                                      {"key": "stops", "label_ko": "손절", "fmt": "n"}, {"key": "start", "label_ko": "시작", "fmt": "usd"},
                                      {"key": "end", "label_ko": "끝", "fmt": "usd"}], "rows": V39_STUDY["rows"]},
                      need_ko="연구 숫자라 바뀌지 않아요 (실거래가 쌓이면 위 '목표 계산'이 이걸 대신해요)",
                      use_ko="맞는 장이 아닐 때 쉬는 규칙이 목표에 가장 큰 차이를 낼 수 있어요: 위 '장세' 칸이 그 근거를 쌓아요",
                      how_ko=V39_STUDY["src"]))
    return {"state": "ok", "since_ms": since, "accounts": accounts, "items": [i for i in items if i]}


# ---------------------------------------------------------------- 레인지 봇 (owners 10-26)
def range_bot(p: dict, now: int, more: dict) -> dict:
    """The 레인지 봇 (livebots.paper_bots "range": its config's ``range`` section) and its followers: the goal cards and the
    items (실거래가 덜 버는 이유 per follower, 진짜 vs 동전, 장세, 손절 해부, the research's numbers)."""
    from . import liverange as RG
    target = 1 + _target()
    _cfgs, _fol, paper, execs = L.sources(p, now)
    bots = L.paper_bots(p, paper, execs)
    b = next((x for x in bots if x["id"] == "range"), None)
    if b is None:
        return {"state": "off", "ko": f"레인지 봇 페이퍼 봇이 아직 꺼져 있어요 ({RG.GUIDE_STEP_KO}로 켜요)"}
    pr = b["read"]
    if pr.get("state") != "ok":
        return {"state": pr.get("state"), "ko": pr.get("reason_ko") or "레인지 봇 기록을 읽지 못했어요", **_src(pr)}
    acc = (pr.get("accounts") or {}).get(L.ACCOUNT) or {}
    since = acc.get("since_ms")
    trades = [t for t in acc.get("trades") or [] if since is None or (t.get("entry_time") or 0) >= since]
    fol = _followers(execs, b["path"])
    accounts = [paper_goal("paper", "레인지 봇 페이퍼(연습)", acc, since, now, target)] + [live_goal(x, b["path"], since, now, target) for x in fol]
    items = []
    for x in fol:
        items.append(_safe(lambda x=x: gap_item(x, b["path"], since, now), f"gap_{x['id']}", f"{x['name_ko']}: 실거래가 덜 버는 이유"))
        li = _safe(lambda x=x: light_item(x, trades), f"light_{x['id']}", f"{x['name_ko']}: 신호등 검증")
        if li:
            items.append(li)
    flip = (pr.get("accounts") or {}).get(L.FLIP_ACCOUNT) or {}
    items.append(_safe(lambda: range_flip(trades, flip, since), "flip", "진짜 vs 동전"))
    items.append(_safe(lambda: range_regime(trades, more.get("rule_db"), accounts[0]), "regime", "장세: 10월 같은 장인가"))
    cfg = L.cfg_of(pr)
    items.append(_safe(lambda: range_stops(trades, cfg, float(pr.get("round_trip") or 0.0), more.get("rule_db"), now), "stops", "손절 해부"))
    items.append(range_study())
    return {"state": "ok", "since_ms": since, "accounts": accounts, "items": [i for i in items if i]}


def range_flip(trades: list, flip: dict, since: Optional[int]) -> dict:
    """진짜 vs 동전: the paper account against its coin-flip twin (the same moments, a random side), from the bot's start."""
    rows = []
    for ko, ts in (("진짜 방향", trades), ("동전 방향 (쌍둥이)",
                                         [t for t in (flip or {}).get("trades") or [] if since is None or (t.get("entry_time") or 0) >= since])):
        known = [t for t in ts if t.get("pnl") is not None]
        w = sum(1 for t in known if t["pnl"] > 0)
        rows.append({"side_ko": ko, "n": len(known), "wins": w, "win_rate": w / len(known) if known else None,
                     "roe_sum": sum(t.get("roe") or 0.0 for t in known), "pnl": sum(t["pnl"] for t in known) if known else None})
    real, coin = rows
    title, q = "진짜 vs 동전: 신호의 방향이 동전보다 나은가", "같은 때 들어가고 방향만 동전으로 정한 쌍둥이보다 레인지 봇의 방향이 더 이기나?"
    if not (flip or {}).get("known"):
        return item("flip", title, q, state="missing", lead_ko="동전 쌍둥이 계좌 기록이 아직 없어요", tone="thin")
    if not real["n"] or not coin["n"]:
        lead, tone = "둘 다 닫힌 거래가 있어야 견줘요", "thin"
    else:
        gap = real["win_rate"] - coin["win_rate"]
        lead = (f"진짜 {real['wins']}승 {real['n'] - real['wins']}패 · 동전 {coin['wins']}승 {coin['n'] - coin['wins']}패 → 승률 "
                f"{_pct(abs(gap), 0, False)}p {'높아요' if gap > 0 else '낮아요' if gap < 0 else '같아요'}" + (" · 아직 우연이 커요" if real["n"] < 40 else ""))
        tone = "good" if gap > 0 and real["n"] >= 40 else "warn" if gap <= 0 else "thin"
    return item("flip", title, q, lead_ko=lead, tone=tone, n=real["n"],
                kpis=[kpi("진짜 승률", real["win_rate"], "pct0"), kpi("동전 승률", coin["win_rate"], "pct0"),
                      kpi("진짜 순ROE 합", real["roe_sum"], "pct", "good" if real["roe_sum"] > 0 else "bad"),
                      kpi("동전 순ROE 합", coin["roe_sum"], "pct")],
                table={"cols": [{"key": "side_ko", "label_ko": "방향", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
                                {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"}, {"key": "roe_sum", "label_ko": "순ROE 합", "fmt": "pct"},
                                {"key": "pnl", "label_ko": "손익 (모의)", "fmt": "usd"}], "rows": rows},
                need_ko="둘 다 40번이 넘어야 우연과 실력을 가를 수 있어요",
                use_ko="진짜 방향이 동전보다 계속 낫지 않으면 신호(레인지 필터 3중 일치)가 아니라 익절·손절 모양이 결과를 만드는 거예요",
                how_ko="같은 페이퍼 기록의 COMBO@mix(진짜)와 COMBOFLIP@mix(동전) 닫힌 거래, 봇 시작부터")


def breakeven_of(avg_win: Optional[float], avg_loss: Optional[float]) -> Optional[float]:
    """The win rate at which the wallet stays where it is (compounding): p ln(1 + w) + (1 - p) ln(1 - l) = 0."""
    if not avg_win or avg_loss is None or not 0 < avg_loss < 1:
        return None
    a, b = math.log1p(avg_win), -math.log1p(-avg_loss)
    return b / (a + b)


def range_regime(trades: list, rule_db: Optional[str], goal: dict) -> dict:
    """장세: 10월 같은 장인가 — the last ROLL_N closed paper trades against the break-even win rate (this record's own wallet
    shares when it has wins and losses, else the research's ~82 %), the KST weeks, BTC's 24-hour move at each entry, next to
    the research's October and 2025-01 ~ 2026-09 numbers (research, never live)."""
    c = regime_cuts(trades, rule_db)
    closed, last, wins, roe = c["closed"], c["last"], c["wins"], c["roe"]
    be = breakeven_of((goal or {}).get("avg_win"), (goal or {}).get("avg_loss"))
    be_src = "이 기록의 이길 때·질 때 잔고로 잰 본전" if be is not None else "연구의 본전 (약 82%)"
    be = be if be is not None else RANGE_STUDY["breakeven"]
    title, q = "장세: 지금 10월 같은 장인가", "레인지 봇이 잘 된 10월 같은 강한 추세 장인가, 2025-01 ~ 2026-09 같은 약한 장인가?"
    if len(last) < ROLL_N:
        lead, tone = f"닫힌 거래가 {len(last)}번뿐이라 최근 {ROLL_N}번 장세 표시는 아직이에요 (본전 승률 약 {_pct(be, 0, False)})", "thin"
    else:
        rate = wins / ROLL_N
        good = rate >= be
        lead = (f"최근 {ROLL_N}번: {wins}승 {ROLL_N - wins}패 · 승률 {_pct(rate, 0, False)} (본전 약 {_pct(be, 0, False)}) → "
                + ("10월 같은 장 쪽이에요 (연구 10월 40승 1패)" if good else "약한 장 쪽이에요 (연구 2025-01 ~ 2026-09 평소 승률 77%)"))
        tone = "good" if good else "bad"
    return item("regime", title, q, lead_ko=lead, tone=tone, n=len(closed),
                kpis=[kpi(f"최근 {ROLL_N}번 승률", wins / ROLL_N if len(last) >= ROLL_N else None, "pct0"),
                      kpi("본전 승률", be, "pct0", sub=be_src),
                      kpi(f"최근 {ROLL_N}번 순ROE 합", roe if len(last) >= ROLL_N else None, "pct", "good" if roe > 0 else "bad"),
                      kpi("연구 10월 승률", RANGE_STUDY["october"], "pct0", sub="40승 1패 ×5.53 · 연구"),
                      kpi("연구 평소 승률", RANGE_STUDY["usual"], "pct0", sub="2025-01 ~ 2026-09 · 연구")],
                table={"cols": REGIME_COLS, "rows": c["rows"]},
                table2={"title_ko": "주마다 (청산 기준, 한국 시간 월요일부터)", "cols": WEEK_COLS, "rows": c["wrows"]},
                need_ko=f"최근 {ROLL_N}번이 쌓여야 장세를 말하고, 약한 장이 한 번은 지나가야 쉬는 규칙을 시험해 볼 수 있어요 (지금 {len(closed)}번)",
                use_ko="약한 장 쪽이 이어지면 쉬는 규칙(연구 19 · 21절: 신호등, 1패 뒤 24시간 쉼)을 다시 볼 때예요 · 바꿀지는 두 분이 정해요",
                how_ko="레인지 봇 페이퍼 닫힌 거래 · 본전 = 이길 때 잔고 w, 질 때 잔고 l에서 p·ln(1+w) + (1−p)·ln(1−l) = 0 · "
                       f"BTC 하루 움직임은 규칙봇 1분봉 · 연구 숫자: {RANGE_STUDY['src']}")


def stop_after(conn, sym: str, side: int, after: int, until: int, tp_px: float) -> Optional[int]:
    """The first 1m bar (its open ms) in [after, until] whose high (a long) / low (a short) reached ``tp_px``; None when none."""
    col, op = ("high", ">=") if side > 0 else ("low", "<=")
    r = conn.execute(f"SELECT MIN(ts) FROM live_bars WHERE symbol = ? AND ts >= ? AND ts <= ? AND {col} {op} ?",
                     (sym, int(after), int(until), float(tp_px))).fetchone()
    return L._i(r[0]) if r and r[0] is not None else None


def range_stops(trades: list, cfg: dict, rt: float, rule_db: Optional[str], now: int) -> dict:
    """손절 해부: each stop-out of the paper account — did the price reach the take-profit level (entry x (1 + side x (tp /
    leverage + round trip))) within 24 hours after the stop (the direction was right, the stop was close: 손절이 가까웠음),
    or not (the price kept going: 방향이 틀림)? The rule bot's 1-minute bars; a stop younger than 24 hours that has not
    reached it yet is 아직 모름, a stop without bars says so (never a guess)."""
    from . import livepos as P
    tp = L._f((cfg or {}).get("take_profit_roe"))
    lad = (cfg or {}).get("ladder") if isinstance((cfg or {}).get("ladder"), dict) else {}
    if tp is None and L._f(lad.get("first_lock")) is not None and L._f(lad.get("trigger_gap")) is not None:
        tp = L._f(lad["first_lock"]) + L._f(lad["trigger_gap"])    # owners 10-30: the ladder's first lock arms there
    stops = [t for t in trades if t.get("exit_reason") == "SL" and t.get("exit_time") is not None]
    title, q = "손절 해부: 손절이 가까웠나, 방향이 틀렸나", "손절로 끝난 거래가 그 뒤 24시간 안에 익절 자리까지 갔나 (손절이 가까웠음), 그대로 갔나 (방향이 틀림)?"
    if tp is None:
        return item("stops", title, q, state="missing", lead_ko="설정에 고정 익절도 계단도 없어 익절 자리를 몰라요", tone="thin")
    conn, bst = P.open_bars(rule_db) if rule_db else (None, {"state": "missing", "reason_ko": "규칙봇 1분봉 파일 경로가 없어요"})
    rows = []
    try:
        for t in sorted(stops, key=lambda t: -(t["exit_time"] or 0)):
            side, entry, lev = int(t.get("side") or 0), t.get("entry_price"), t.get("leverage")
            px = entry * (1 + side * (tp / lev + rt)) if entry and lev and side else None
            row = {"t": t["exit_time"], "when_ko": _kst(t["exit_time"]), "coin": str(t.get("symbol") or "").replace("USDT", ""),
                   "side_ko": "롱" if side > 0 else "숏", "roe": t.get("roe"), "tp_px": px}
            end = int(t["exit_time"]) + STOP_AFTER_MS
            if conn is None or px is None:
                row.update(kind="none", kind_ko="1분봉 없음" if conn is None else "진입가 기록 없음")
            else:
                n = conn.execute("SELECT COUNT(*) FROM live_bars WHERE symbol = ? AND ts >= ? AND ts <= ?",
                                 (t.get("symbol"), int(t["exit_time"]), min(end, now))).fetchone()[0]
                hit = stop_after(conn, t.get("symbol"), side, int(t["exit_time"]), min(end, now), px) if n else None
                if hit is not None:
                    row.update(kind="close", kind_ko="손절이 가까웠음", after_ko=f"{(hit - int(t['exit_time'])) // MIN}분 뒤 익절 자리 닿음")
                elif not n:
                    row.update(kind="none", kind_ko="1분봉 없음")
                elif end > now:
                    row.update(kind="pending", kind_ko="아직 모름 (24시간 안 지남)")
                else:
                    row.update(kind="wrong", kind_ko="방향이 틀림", after_ko="24시간 안에 익절 자리에 안 닿음")
            rows.append(row)
    except sqlite3.Error as exc:
        return item("stops", title, q, state="error", lead_ko="규칙봇 1분봉을 읽지 못했어요", reason=f"{type(exc).__name__}: {exc}"[:200])
    finally:
        if conn is not None:
            conn.close()
    close = sum(1 for r in rows if r["kind"] == "close")
    wrong = sum(1 for r in rows if r["kind"] == "wrong")
    if not stops:
        lead, tone = "손절로 끝난 거래가 아직 없어요", "good" if trades else "thin"
    elif conn is None and bst.get("state") != "ok":
        lead, tone = f"손절 {len(stops)}번 · {bst.get('reason_ko') or '규칙봇 1분봉을 못 읽어요'}", "thin"
    else:
        lead = f"손절 {len(stops)}번 중 {close}번은 24시간 안에 익절 자리까지 갔어요 (손절이 가까웠음) · {wrong}번은 그대로 갔어요 (방향이 틀림)"
        tone = "warn" if close > wrong else "bad" if wrong else "thin"
    out = item("stops", title, q, lead_ko=lead, tone=tone, n=len(stops),
               kpis=[kpi("손절", len(stops), "n"), kpi("손절이 가까웠음", close, "n"), kpi("방향이 틀림", wrong, "n"),
                     kpi("아직 모름 · 1분봉 없음", len(rows) - close - wrong, "n")],
               table={"cols": [{"key": "when_ko", "label_ko": "손절 시각", "fmt": "text"}, {"key": "coin", "label_ko": "코인", "fmt": "text"},
                               {"key": "side_ko", "label_ko": "방향", "fmt": "text"}, {"key": "kind_ko", "label_ko": "그 뒤 24시간", "fmt": "text"},
                               {"key": "after_ko", "label_ko": "언제", "fmt": "text"}], "rows": rows},
               need_ko=f"손절이 {READ_N}번은 쌓여야 어느 쪽이 많은지 말할 수 있어요 (지금 {len(stops)}번)",
               use_ko="손절이 가까웠던 게 많으면 손절 거리(순ROE −50%)가, 방향이 틀린 게 많으면 진입 조건(추세 확인 · 되돌림)이 다음 연구예요",
               how_ko=f"손절 뒤 24시간의 규칙봇 1분봉 고가(롱) · 저가(숏)가 익절 가격(진입가 × (1 ± (익절 순ROE {_pct(tp, 0, False)} ÷ 배수 + 왕복 비용)))에 "
                      "닿았는지")
    if bst.get("state") != "ok":
        out["sub_state"] = _src(bst)
    return out


def range_study() -> dict:
    """연구 기록: the research's numbers of this structure (analysis/f7tp10_1026/FINAL_KO.md), labelled as research."""
    return item("study", "연구 기록: 이 구조를 지난 기간에 돌려 본 것", "레인지 봇 구조를 지난 기간에 그대로 돌리면 어땠나? (실거래 아님)",
                lead_ko=RANGE_STUDY["ko"], tone="warn",
                table={"cols": [{"key": "span_ko", "label_ko": "기간", "fmt": "text"}, {"key": "kind_ko", "label_ko": "장", "fmt": "text"},
                                {"key": "wins", "label_ko": "승", "fmt": "n"}, {"key": "losses", "label_ko": "패", "fmt": "n"},
                                {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"}, {"key": "mult", "label_ko": "지갑", "fmt": "mult"},
                                {"key": "note_ko", "label_ko": "", "fmt": "text"}], "rows": RANGE_STUDY["rows"]},
                need_ko="연구 숫자라 바뀌지 않아요 (실거래가 쌓이면 위 '목표까지'와 '장세'가 이걸 대신해요)",
                use_ko="약한 장에서는 한 달 −30 ~ −60%가 날 수 있어요: 위 '장세' 칸이 지금이 어느 쪽인지의 근거를 쌓아요",
                how_ko=RANGE_STUDY["src"] + " (수수료 · 미끄러짐 포함, 지갑 배수)")


def btc_moves(rule_db: Optional[str], times: list) -> dict:
    """{entry ms: BTC's 24-hour move (close at the entry minute over the close 24 h before)} from the rule bot's 1m bars."""
    from . import livepos as P
    out: dict = {}
    if not rule_db or not times:
        return out
    conn, st = P.open_bars(rule_db)
    if conn is None:
        return out
    try:
        q = "SELECT close FROM live_bars WHERE symbol = 'BTCUSDT' AND ts <= ? AND ts > ? ORDER BY ts DESC LIMIT 1"
        for t in times:
            a = conn.execute(q, (int(t), int(t) - 10 * MIN)).fetchone()
            b = conn.execute(q, (int(t) - DAY, int(t) - DAY - 10 * MIN)).fetchone()
            if a and b and _f(a[0]) and _f(b[0]):
                out[t] = float(a[0]) / float(b[0]) - 1.0
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    return out


def regime_cuts(trades: list, rule_db: Optional[str]) -> dict:
    """장세's cuts of a paper account (V3.9 and the 레인지 봇): its closed trades oldest first, the last ROLL_N (wins, net ROE
    sum), BTC's 24-hour move at each entry (up / down / sideways, with or against the trade's side) and the KST weeks."""
    closed = sorted([t for t in trades if t.get("exit_time") is not None and t.get("pnl") is not None], key=lambda t: t["exit_time"])
    last = closed[-ROLL_N:]
    wins = sum(1 for t in last if t["pnl"] > 0)
    roe = sum(t.get("roe") or 0.0 for t in last)
    moves = btc_moves(rule_db, [t["entry_time"] for t in closed if t.get("entry_time") is not None])
    by: dict = {}
    for t in closed:
        mv = moves.get(t.get("entry_time"))
        if mv is None:
            k = "BTC 움직임 모름"
        else:
            d = 1 if mv > BTC_MOVE else -1 if mv < -BTC_MOVE else 0
            k = ("BTC 옆걸음 (하루 ±2% 안)" if d == 0 else
                 ("BTC와 같은 방향 (하루 2% 넘게 " + ("오를 때 롱)" if d > 0 else "내릴 때 숏)")) if d == (t.get("side") or 0) else
                 ("BTC와 반대 방향 (하루 2% 넘게 " + ("오를 때 숏)" if d > 0 else "내릴 때 롱)")))
        b = by.setdefault(k, {"key": k, "n": 0, "wins": 0, "roe_sum": 0.0})
        b["n"] += 1
        b["wins"] += 1 if t["pnl"] > 0 else 0
        b["roe_sum"] += t.get("roe") or 0.0
    rows = [{**b, "win_rate": b["wins"] / b["n"], "few": b["n"] < 10} for b in sorted(by.values(), key=lambda b: -b["n"])]
    weeks: dict = {}
    for t in closed:
        kd = L.kst_day(t["exit_time"])
        wk = kd - ((kd + 3) % 7)                        # the KST Monday of its exit (1970-01-01 was a Thursday)
        w = weeks.setdefault(wk, {"week_ms": L.kst_day_start(wk), "n": 0, "wins": 0, "roe_sum": 0.0})
        w["n"] += 1
        w["wins"] += 1 if t["pnl"] > 0 else 0
        w["roe_sum"] += t.get("roe") or 0.0
    wrows = [{**w, "week_ko": _kst(w["week_ms"]).split(" ")[0] + " 주", "win_rate": w["wins"] / w["n"]} for _k, w in sorted(weeks.items())][-8:]
    return {"closed": closed, "last": last, "wins": wins, "roe": roe, "moves": moves, "rows": rows, "wrows": wrows}


REGIME_COLS = [{"key": "key", "label_ko": "진입 때 BTC 하루 움직임", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
               {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"}, {"key": "roe_sum", "label_ko": "순ROE 합", "fmt": "pct"}]
WEEK_COLS = [{"key": "week_ko", "label_ko": "주", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
             {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"}, {"key": "roe_sum", "label_ko": "순ROE 합", "fmt": "pct"}]


def v39_regime(trades: list, rule_db: Optional[str], now: int) -> dict:
    """장세: the last ROLL_N closed paper trades (wins, net ROE sum) as the one live sign of a V3.9 market, the KST weeks,
    and BTC's 24-hour move at each entry (up / down / sideways, and with or against the trade's side)."""
    c = regime_cuts(trades, rule_db)
    closed, last, wins, roe, moves, rows, wrows = c["closed"], c["last"], c["wins"], c["roe"], c["moves"], c["rows"], c["wrows"]
    if len(last) < ROLL_N:
        lead, tone = f"닫힌 거래가 {len(last)}번뿐이라 최근 {ROLL_N}번 장세 표시는 아직이에요", "thin"
    else:
        good = roe > 0
        lead = (f"최근 {ROLL_N}번: {wins}승 {ROLL_N - wins}패 · 순ROE 합 {_pct(roe)} → "
                + ("V3.9가 버는 장으로 보여요" if good else "V3.9가 잃는 장으로 보여요 (30일 연구의 앞 10일처럼)"))
        tone = "good" if good else "bad"
    return item("regime", "장세: 지금 V3.9에 맞는 장인가", "V3.9가 버는 장(20일)과 잃는 장(앞 10일)을 미리 알 수 있는 표시가 있나?",
                lead_ko=lead, tone=tone, n=len(closed),
                kpis=[kpi(f"최근 {ROLL_N}번 승", wins if len(last) >= ROLL_N else None, "n"),
                      kpi(f"최근 {ROLL_N}번 순ROE 합", roe if len(last) >= ROLL_N else None, "pct", "good" if roe > 0 else "bad"),
                      kpi("BTC 움직임 잰 거래", len(moves), "n")],
                table={"cols": [{"key": "key", "label_ko": "진입 때 BTC 하루 움직임", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
                                {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"}, {"key": "roe_sum", "label_ko": "순ROE 합", "fmt": "pct"}],
                       "rows": rows},
                table2={"title_ko": "주마다 (청산 기준, 한국 시간 월요일부터)",
                        "cols": [{"key": "week_ko", "label_ko": "주", "fmt": "text"}, {"key": "n", "label_ko": "번", "fmt": "n"},
                                 {"key": "win_rate", "label_ko": "승률", "fmt": "pct0"}, {"key": "roe_sum", "label_ko": "순ROE 합", "fmt": "pct"}],
                        "rows": wrows},
                need_ko=f"칸마다 10번 넘고, 잃는 장이 한 번은 더 지나가야 '쉬는 규칙'을 시험해 볼 수 있어요 (지금 {len(closed)}번)",
                use_ko="한 칸(예: BTC와 반대 방향)이 계속 잃으면 그 장에서 쉬는 규칙을 연구실에서 5년 자료로 먼저 시험해요 (바로 켜지 않아요)",
                how_ko="규칙봇 V3.9 1시간 페이퍼 계좌의 닫힌 거래 · BTC 하루 움직임은 규칙봇 1분봉의 진입 때 종가 ÷ 24시간 전 종가")


# ---------------------------------------------------------------- the answer
def _target() -> float:
    from . import liveinsight as I
    return float(I.MONTHLY_TARGET)


def _safe(make: Callable, iid: str, title: str) -> Optional[dict]:
    """One item; its own failure is said in its place, never the panel's."""
    try:
        return make()
    except Exception as exc:  # noqa: BLE001
        return item(iid, title, "", state="error", lead_ko="이 연구 칸을 만들지 못했어요", reason=f"{type(exc).__name__}: {exc}"[:300])


def build(bot: str, p: Optional[dict] = None, now_ms: Optional[int] = None, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/goalres?bot= (module docstring)."""
    p = p or L.paths()
    more = more or L.paths_more()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    bot = bot if bot in BOTS else "trend"
    head = {"now_ms": now, "bot": bot, "name_ko": NAME_KO[bot], "goal": {"mult": 1 + _target(), "days": MONTH_D, "ko": GOAL_KO},
            "note_ko": NOTE_KO, "few_n": FEW, "read_n": READ_N,
            "links": [{"href": h, "ko": k} for h, k in LINKS[bot]]}
    try:
        body = (site_bot(bot, p, now, more) if bot in ("trend", "vwap") else mix_bot(p, now, bot) if bot in ("mix", "bybit")
                else range_bot(p, now, more) if bot == "range" else v39_bot(p, now, more))
    except Exception as exc:  # noqa: BLE001
        body = {"state": "error", "ko": "목표 연구를 만들지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:300]}
    return {**head, **body}


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/goalres")
    def get_livebots_goalres(bot: str = "trend"):
        """실거래 › 봇별 › 목표 연구: one bot's goal arithmetic and its research questions on its own records (read-only,
        5 s cache)."""
        b = bot if bot in BOTS else "trend"
        p, more = L.paths(), L.paths_more()
        return L._cached("goalres:" + b + ":" + json.dumps([p, more], sort_keys=True), lambda: json_finite(build(b, p, None, more)))

    return {"routes": ["/api/v4/livebots/goalres"]}
