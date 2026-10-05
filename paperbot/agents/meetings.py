"""Code-only packets of the meetings added on 2026-10-04 (owners' choice). Read-only on paper3.db, flow.db and
liq.db; agents3.db is only read here. Code computes every number; the staff read the packet and interpret it.

- ``cost_packet``     Monday, 운영·검증팀 (cost_review): per strategy and timeframe over the last 7 days, the P&L before
                      costs, fees, funding and the engine's fixed slippage, costs against the move, the accounts that
                      were up before costs and down after them, the recorded order-book slippage (fill_costs), the
                      signal-to-fill delay and ``real_slippage`` (paperbot/slipcost.week_packet with ``daily_ro``: the
                      nightly check's estimated real stop slippage and the cost at 2x/5x/10x the size; bounded).
- ``combo_packet``    Tuesday, 리스크팀 (combo_review): the strategies' daily P&L correlations (top pairs, clusters),
                      the hours many strategies lost together, and consensus entries (several strategies, same coin,
                      same side within ``window_ms``) against single ones, with the coin flips for scale. The rooms
                      add ``synergy`` (agents/synergy.py: equal-weight combinations against shuffled-day and coin-flip
                      searches; it reuses ``corr_clusters``).
- ``coin_packet``     Wednesday, 손익 복기팀 (coin_review): per strategy x coin and strategy x regime at entry (the
                      trade's chart context, cards.REGIME_KO): trades, win rate, mean ROE, P&L; cells under ``min_n``
                      trades are marked small; best and worst coin per strategy. The rooms add ``entry_moment``
                      (agents/entrymoment.py: outcomes by the moment of entry and the signals not taken).
- ``learning_packet`` Saturday, 총괄 (learning_review): the week's graded predictions by role, the ones still waiting,
                      the week's 5-year and lab tests with their gate results, repeated hypotheses and tests, what the
                      entry study already concluded, and the daily debate's record.
- ``event_packet``    the day after a US release (event_review, 시장분석팀): our accounts' trades in the event's window
                      (2h before .. 6h after) against the same hours of up to 5 earlier weekdays without a release,
                      the coin flips', BTC/ETH moves (public klines) and liquidations (liq.db).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from typing import Any, Optional

from ..config import V3_TRADE_TFS
from . import committee as CM

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
KST_MS = 9 * HOUR_MS
TFS = V3_TRADE_TFS                   # the run's timeframes (5m removed 2026-10-04, docs/paper-v3-rules-change-1.md)


def _f(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if v == v else default


def _r(x: Optional[float], n: int = 2) -> Optional[float]:
    return None if x is None else round(float(x), n)


def _kst_label(ms: int, fmt: str = "%m/%d %H시") -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp((ms + KST_MS) / 1000, dt.timezone.utc).strftime(fmt)


def _closed(paper_ro: sqlite3.Connection, since_ms: int, until_ms: int, kinds=("strategy",)) -> list[tuple]:
    from .digest import _closed as closed
    return closed(paper_ro, since_ms, until_ms, kinds=kinds)


def _names() -> dict:
    from .roster3 import STRATEGY_KO
    return dict(STRATEGY_KO)


# ---------------------------------------------------------------- Monday: costs and fills
def _slip_frac() -> float:
    from ..config import v3_settings
    return float(v3_settings().slippage_frac)


def _cost_cell(ts: list[dict], slip: float) -> dict:
    n = len(ts)
    if not n:
        return {"trades": 0}
    pnl = sum(_f(t.get("pnl")) for t in ts)
    fees = sum(_f(t.get("fees")) for t in ts)
    fund = sum(_f(t.get("funding")) for t in ts)
    # the engine fills every order at its reference price plus a fixed slippage (Settings.slippage_frac): its cost is
    # inside the fill prices, estimated here on the entry and exit notionals
    sl = sum(slip * _f(t.get("qty")) * (_f(t.get("entry_price")) + _f(t.get("exit_price"))) for t in ts)
    gross = pnl + fees + fund + sl
    costs = fees + fund + sl
    return {"trades": n, "gross_before_costs": round(gross, 2), "fees": round(fees, 2), "funding": round(fund, 2),
            "slippage_est": round(sl, 2), "costs": round(costs, 2), "pnl": round(pnl, 2),
            "cost_per_trade": round(costs / n, 3), "gross_per_trade": round(gross / n, 3),
            "cost_vs_gross": round(costs / abs(gross), 3) if gross else None,
            "win_rate": round(sum(1 for t in ts if _f(t.get("pnl")) > 0) / n, 3)}


def cost_packet(paper_ro: Optional[sqlite3.Connection], now_ms: int, days: int = 7, top: int = 12,
                daily_ro: Optional[sqlite3.Connection] = None) -> dict:
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    since = now_ms - days * DAY_MS
    slip = _slip_frac()
    try:
        rows = _closed(paper_ro, since, now_ms)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    names = _names()
    by_acct: dict = {}
    by_s: dict = {}
    by_tf: dict = {}
    for aid, _k, s, tf, d in rows:
        by_acct.setdefault((s, tf), []).append(d)
        by_s.setdefault(s, []).append(d)
        by_tf.setdefault(tf, []).append(d)
    accts = {k: _cost_cell(v, slip) for k, v in by_acct.items()}
    flipped = sorted(([s, tf, c] for (s, tf), c in accts.items() if c["gross_before_costs"] > 0 and c["pnl"] < 0),
                     key=lambda x: x[2]["pnl"])
    tf_rows = {}
    for tf in sorted(by_tf, key=lambda t: TFS.index(t) if t in TFS else 9):
        c = _cost_cell(by_tf[tf], slip)
        c["accounts"] = sum(1 for (s, t) in accts if t == tf)
        c["up_before_costs"] = sum(1 for (s, t), v in accts.items() if t == tf and v["gross_before_costs"] > 0)
        c["up_after_costs"] = sum(1 for (s, t), v in accts.items() if t == tf and v["pnl"] > 0)
        c["flipped_by_costs"] = sum(1 for s, t, _c in flipped if t == tf)
        tf_rows[tf] = c
    strat = []
    for s, ts in by_s.items():
        c = _cost_cell(ts, slip)
        c.update(strategy=s, name_ko=names.get(s, s),
                 flipped_timeframes=[tf for s2, tf, _c in flipped if s2 == s])
        strat.append(c)
    strat.sort(key=lambda c: -(c["costs"] or 0))
    worst = sorted(((s, tf, c) for (s, tf), c in accts.items() if c["trades"] >= 10 and c["cost_vs_gross"] is not None),
                   key=lambda x: -x[2]["cost_vs_gross"])[:top]
    out = {"window": {"from": since, "to": now_ms, "days": days}, "trades": len(rows),
           "total": _cost_cell([d for *_x, d in rows], slip), "by_timeframe": tf_rows, "by_strategy": strat,
           "flipped_by_costs": {"accounts": len(flipped),
                                "list": [{"account": f"{s}@{tf}", "name_ko": names.get(s, s), **{k: c[k] for k in (
                                    "trades", "gross_before_costs", "costs", "pnl")}} for s, tf, c in flipped[:30]]},
           "highest_cost_share": [{"account": f"{s}@{tf}", "name_ko": names.get(s, s), **c} for s, tf, c in worst],
           "assumed_slippage": slip}
    out["book_slippage"] = _book_slippage(paper_ro, since, now_ms, slip)
    out["signal_delay"] = _signal_delay(paper_ro, since, now_ms)
    out["real_slippage"] = _slip_week(daily_ro, paper_ro, since, now_ms)
    out["how_to_read"] = ("gross_before_costs = 손익 + 수수료 + 펀딩 + 슬리피지 추정(엔진은 모든 주문을 기준가에 고정 슬리피지 "
                          f"{slip * 100:.2f}%를 붙여 체결, slippage_est = 그 비율 × 진입·청산 금액). costs = 수수료 + 펀딩 + 슬리피지 "
                          "추정, cost_vs_gross = costs ÷ |비용 전 손익|(1 넘으면 비용이 가격 움직임보다 큼). flipped_by_costs = 비용 "
                          "전에는 플러스였는데 비용 뒤 마이너스인 계좌. book_slippage = 같은 크기 시장가 주문을 실제 호가창에 넣었다면의 "
                          "기록(fill_costs, 체결은 바꾸지 않음). 단위 $, 비율 0.01 = 1%")
    out["note"] = "코드 계산(끝난 거래, 지난 7일). 거래 30건 미만 칸은 운일 수 있음. 직원은 체결 방식·규칙을 바꿀 수 없음"
    return out


SLIP_ROWS = 12          # size-cost rows (coin x timeframe) in the cost packet, the most orders first


def _slip_week(daily_ro: Optional[sqlite3.Connection], paper_ro: Optional[sqlite3.Connection], since: int,
               until: int, max_rows: int = SLIP_ROWS) -> dict:
    """paperbot/slipcost.week_packet (read-only, descriptive): the nightly check's estimated real STOP_MARKET
    slippage of the week's SL / LOCK / LIQ exits (daily3.db stop_slips) and the cost at 2x / 5x / 10x the paper size
    (fill_costs), bounded to ``max_rows`` coin x timeframe rows."""
    from ..slipcost import week_packet
    try:
        pk = week_packet(daily_ro, paper_ro, since, until)
    except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        return {"error": f"실제 슬리피지 추정을 읽지 못함: {type(exc).__name__}"}
    sc = pk.get("size_costs") or {}
    rows = sc.get("rows")
    if isinstance(rows, list) and len(rows) > max_rows:
        keep = sorted(rows, key=lambda r: -int(r.get("orders") or 0))[:max_rows]
        sc["rows"] = keep
        sc["rows_left_out"] = len(rows) - len(keep)
    return pk


def _book_slippage(paper_ro: sqlite3.Connection, since: int, until: int, assumed: float) -> dict:
    """The recorded order-book slippage of the strategy accounts' paper orders by timeframe (paperbot/fillcost.py)."""
    try:
        rows = paper_ro.execute("SELECT a.timeframe, f.event, f.slip_best FROM fill_costs f JOIN accounts a ON "
                                "a.account_id = f.account_id WHERE a.kind = 'strategy' AND f.status = 'ok' AND "
                                "f.slip_best IS NOT NULL AND f.ts >= ? AND f.ts < ?", (since, until)).fetchall()
    except sqlite3.Error:
        return {"note": "기록 없음(fill_costs 표가 없거나 읽지 못함)"}
    by: dict = {}
    for tf, _ev, sb in rows:
        by.setdefault(tf, []).append(float(sb))
    out = {}
    for tf in sorted(by, key=lambda t: TFS.index(t) if t in TFS else 9):
        xs = sorted(by[tf])
        out[tf] = {"orders": len(xs), "median": round(xs[len(xs) // 2], 6), "p90": round(xs[min(len(xs) - 1,
                                                                                                int(0.9 * len(xs)))], 6),
                   "over_assumed": sum(1 for x in xs if x > assumed)}
    return {"by_timeframe": out, "assumed": assumed} if out else {"note": "이 기간의 호가창 기록 없음"}


def _signal_delay(paper_ro: sqlite3.Connection, since: int, until: int) -> dict:
    try:
        rows = paper_ro.execute("SELECT timeframe, COUNT(*), AVG(delay_ms), MAX(delay_ms) FROM signal_log WHERE "
                                "bar_close >= ? AND bar_close < ? AND strategy NOT GLOB 'NL[0-9]*' AND delay_ms IS NOT "
                                "NULL GROUP BY timeframe", (since, until)).fetchall()
    except sqlite3.Error:
        return {}
    return {tf: {"signals": int(n), "avg_delay_s": _r(_f(a) / 1000, 1), "max_delay_s": _r(_f(m) / 1000, 1)}
            for tf, n, a, m in sorted(rows, key=lambda r: TFS.index(r[0]) if r[0] in TFS else 9)}


# ---------------------------------------------------------------- Tuesday: combinations and losses together
def _pearson(a: list[float], b: list[float]) -> Optional[float]:
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def _kst_day(ms: int) -> str:
    return _kst_label(ms, "%Y-%m-%d")


def corr_clusters(units: list, pairs: list, cluster_r: float = 0.7) -> list[list]:
    """Groups of ``units`` joined by a correlation of at least ``cluster_r`` (union-find over ``pairs``:
    (r, a, b)), biggest first; single units are left out. Shared with agents/synergy.py."""
    parent = {s: s for s in units}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r, a, b in pairs:
        if r >= cluster_r and a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: dict = {}
    for s in units:
        groups.setdefault(find(s), []).append(s)
    return sorted((g for g in groups.values() if len(g) > 1), key=lambda g: -len(g))


def combo_packet(paper_ro: Optional[sqlite3.Connection], now_ms: int, days: int = 7, corr_days: int = 28,
                 window_ms: int = 30 * 60_000, min_losers: int = 8, cluster_r: float = 0.7) -> dict:
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    from .triggers import run_start
    start = run_start(paper_ro) or (now_ms - corr_days * DAY_MS)
    c0 = max(start, now_ms - corr_days * DAY_MS)
    since = now_ms - days * DAY_MS
    try:
        rows = _closed(paper_ro, c0, now_ms)
        flips = _closed(paper_ro, since, now_ms, kinds=("random",))
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    names = _names()
    # daily P&L of each strategy (its four accounts, KST days with at least one closed trade anywhere)
    day_list = sorted({_kst_day(int(_f(d.get("exit_time")))) for *_x, d in rows})
    daily: dict = {}
    for _a, _k, s, _tf, d in rows:
        k = _kst_day(int(_f(d.get("exit_time"))))
        daily.setdefault(s, {}).setdefault(k, 0.0)
        daily[s][k] += _f(d.get("pnl"))
    strats = sorted(daily)
    vec = {s: [daily[s].get(k, 0.0) for k in day_list] for s in strats}
    pairs = []
    for i, a in enumerate(strats):
        for b in strats[i + 1:]:
            r = _pearson(vec[a], vec[b])
            if r is not None:
                pairs.append((r, a, b))
    pairs.sort(key=lambda x: -x[0])
    clusters = [[names.get(s, s) for s in g] for g in corr_clusters(strats, pairs, cluster_r)]
    pr = lambda r, a, b: {"a": names.get(a, a), "b": names.get(b, b), "r": round(r, 3)}  # noqa: E731
    corr = {"days": len(day_list), "strategies": len(strats),
            "mean_r": round(sum(p[0] for p in pairs) / len(pairs), 3) if pairs else None,
            "top_pairs": [pr(*p) for p in pairs[:10]], "most_opposite": [pr(*p) for p in pairs[-5:][::-1]] if pairs else [],
            "clusters": clusters[:8], "cluster_rule": f"하루 손익 상관 {cluster_r} 이상으로 이어진 매매법 묶음"}
    if len(day_list) < 10:
        corr["small"] = True
    # the last ``days``: hours in which many strategies lost together
    week = [x for x in rows if _f(x[4].get("exit_time")) >= since]
    hours: dict = {}
    for _a, _k, s, _tf, d in week:
        h = int(_f(d.get("exit_time"))) // HOUR_MS
        hs = hours.setdefault(h, {})
        e = hs.setdefault(s, {"pnl": 0.0, "coins": {}})
        e["pnl"] += _f(d.get("pnl"))
        coin = str(d.get("symbol", "?")).replace("USDT", "")
        e["coins"][coin] = e["coins"].get(coin, 0) + 1
    events = []
    for h, per in hours.items():
        losers = {s: e for s, e in per.items() if e["pnl"] < 0}
        if len(losers) >= min_losers:
            coins: dict = {}
            for e in losers.values():
                for c, n in e["coins"].items():
                    coins[c] = coins.get(c, 0) + n
            events.append({"hour_kst": _kst_label(h * HOUR_MS), "losing_strategies": len(losers),
                           "strategies_trading": len(per), "loss": round(sum(e["pnl"] for e in losers.values()), 2),
                           "coins": dict(sorted(coins.items(), key=lambda kv: -kv[1])[:4])})
    events.sort(key=lambda e: (-e["losing_strategies"], e["loss"]))
    by_day: dict = {}
    for _a, _k, s, _tf, d in week:
        k = _kst_day(int(_f(d.get("exit_time"))))
        by_day.setdefault(k, {}).setdefault(s, 0.0)
        by_day[k][s] += _f(d.get("pnl"))
    days_view = {k: {"losing_strategies": sum(1 for v in per.values() if v < 0), "strategies": len(per),
                     "pnl": round(sum(per.values()), 2)} for k, per in sorted(by_day.items())}
    out = {"window": {"from": since, "to": now_ms, "days": days, "corr_from": c0}, "correlation": corr,
           "losses_together": {"hours": events[:10], "hours_found": len(events), "rule": f"한 시간에 {min_losers}개 이상의 "
                               "매매법이 그 시간에 끝난 거래 합계로 손실", "days": days_view},
           "consensus": _consensus(week, window_ms), "coin_flips": _flip_cell(flips)}
    out["note"] = ("코드 계산. 상관은 하루 손익(매매법의 4개 봉 계좌 합) 기준이라 날이 적으면(small) 우연이 큼. 합의 신호 = 같은 코인·같은 "
                   f"방향으로 {window_ms // 60_000}분 안에 진입한 다른 매매법 수(자기 포함). 동전 봇은 무작위 진입이라 비교 기준")
    return out


def _flip_cell(rows: list[tuple]) -> dict:
    n = len(rows)
    if not n:
        return {"trades": 0}
    pnl = [_f(d.get("pnl")) for *_x, d in rows]
    return {"trades": n, "win_rate": round(sum(1 for p in pnl if p > 0) / n, 3),
            "mean_roe": round(sum(_f(d.get("roe")) for *_x, d in rows) / n, 4), "pnl": round(sum(pnl), 2)}


def _consensus(rows: list[tuple], window_ms: int) -> dict:
    """Each closed trade by how many strategies (itself included) entered the same coin on the same side within
    ``window_ms`` of its entry; outcomes by group size."""
    by_key: dict = {}
    for _a, _k, s, _tf, d in rows:
        by_key.setdefault((d.get("symbol"), 1 if _f(d.get("side")) > 0 else -1), []).append((int(_f(d.get("entry_time"))), s, d))
    buckets: dict = {"1": [], "2": [], "3-4": [], "5+": []}
    for lst in by_key.values():
        lst.sort(key=lambda x: x[0])
        times = [x[0] for x in lst]
        import bisect
        for t, s, d in lst:
            lo, hi = bisect.bisect_left(times, t - window_ms), bisect.bisect_right(times, t + window_ms)
            k = len({x[1] for x in lst[lo:hi]})
            b = "1" if k <= 1 else "2" if k == 2 else "3-4" if k <= 4 else "5+"
            buckets[b].append(d)

    def cell(ds: list[dict]) -> dict:
        n = len(ds)
        if not n:
            return {"trades": 0}
        pnl = [_f(d.get("pnl")) for d in ds]
        c = {"trades": n, "win_rate": round(sum(1 for p in pnl if p > 0) / n, 3),
             "mean_roe": round(sum(_f(d.get("roe")) for d in ds) / n, 4), "pnl": round(sum(pnl), 2)}
        if n < 30:
            c["small"] = True
        return c
    return {"by_strategies_agreeing": {k: cell(v) for k, v in buckets.items()},
            "rule": f"같은 코인·같은 방향, 진입 시각 ±{window_ms // 60_000}분 안의 다른 매매법 수(자기 포함)"}


# ---------------------------------------------------------------- Wednesday: coins and regimes
def _cell(ts: list[dict], min_n: int) -> dict:
    n = len(ts)
    pnl = [_f(t.get("pnl")) for t in ts]
    c = {"n": n, "win_rate": round(sum(1 for p in pnl if p > 0) / n, 3) if n else None,
         "mean_roe": round(sum(_f(t.get("roe")) for t in ts) / n, 4) if n else None, "pnl": round(sum(pnl), 2)}
    if n < min_n:
        c["small"] = True
    return c


def _regime(d: dict) -> str:
    from ..cards import REGIME_KO
    ctx = d.get("context") if isinstance(d.get("context"), dict) else {}
    return REGIME_KO.get(ctx.get("regime"), "모름")


def coin_packet(paper_ro: Optional[sqlite3.Connection], now_ms: int, min_n: int = 10) -> dict:
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    try:
        rows = _closed(paper_ro, 0, now_ms)
        flips = _closed(paper_ro, 0, now_ms, kinds=("random",))
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    names = _names()
    per: dict = {}
    for _a, _k, s, _tf, d in rows:
        e = per.setdefault(s, {"coins": {}, "regimes": {}})
        e["coins"].setdefault(str(d.get("symbol", "?")).replace("USDT", ""), []).append(d)
        e["regimes"].setdefault(_regime(d), []).append(d)
    strategies = []
    for s, e in per.items():
        coins = {c: _cell(v, min_n) for c, v in sorted(e["coins"].items())}
        regs = {r: _cell(v, min_n) for r, v in sorted(e["regimes"].items(), key=lambda kv: -len(kv[1]))}
        big = {c: v for c, v in coins.items() if not v.get("small")}
        pool = big or coins
        best = max(pool, key=lambda c: pool[c]["pnl"]) if pool else None
        worst = min(pool, key=lambda c: pool[c]["pnl"]) if pool else None
        strategies.append({"strategy": s, "name_ko": names.get(s, s), "trades": sum(v["n"] for v in coins.values()),
                           "coins": coins, "regimes": regs, "best_coin": best, "worst_coin": worst,
                           "best_worst_small": not big})
    strategies.sort(key=lambda r: -r["trades"])
    tot_c: dict = {}
    tot_r: dict = {}
    for *_x, d in rows:
        tot_c.setdefault(str(d.get("symbol", "?")).replace("USDT", ""), []).append(d)
        tot_r.setdefault(_regime(d), []).append(d)
    fl_c: dict = {}
    fl_r: dict = {}
    for *_x, d in flips:
        fl_c.setdefault(str(d.get("symbol", "?")).replace("USDT", ""), []).append(d)
        fl_r.setdefault(_regime(d), []).append(d)
    return {"window": {"from": "실험 시작", "to": now_ms}, "trades": len(rows), "min_n": min_n,
            "all_strategies": {"by_coin": {c: _cell(v, min_n) for c, v in sorted(tot_c.items())},
                               "by_regime": {r: _cell(v, min_n) for r, v in sorted(tot_r.items())}},
            "coin_flips": {"by_coin": {c: _cell(v, min_n) for c, v in sorted(fl_c.items())},
                           "by_regime": {r: _cell(v, min_n) for r, v in sorted(fl_r.items())}},
            "strategies": strategies,
            "how_to_read": ("strategies.<i>.coins.<코인>/regimes.<장세>: n(끝난 거래), win_rate, mean_roe(0.01 = 1%), pnl($). "
                            f"small = {min_n}건 미만이라 우연일 수 있음. 장세는 진입 순간 코드가 판정한 차트 상황(상승 추세, 하락 "
                            "추세, 박스권, 방향 없는 횡보, 뚜렷하지 않음). best_coin/worst_coin은 small이 아닌 칸에서 고름"
                            "(모두 small이면 best_worst_small = true)"),
            "note": "코드 계산(실험 시작부터 끝난 거래, 수수료·펀딩 포함). 동전 봇(무작위 진입)의 같은 칸이 비교 기준"}


# ---------------------------------------------------------------- Saturday: what we learned
def _loads(s: Any) -> Any:
    try:
        return json.loads(s) if s else None
    except (TypeError, ValueError):
        return None


def _norm(text: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "")).lower()


def _spec_ko(spec: dict) -> str:
    if not isinstance(spec, dict):
        return ""
    keys = ("template", "timeframe", "k", "lock", "tag")
    return " ".join(f"{k}={spec[k]}" for k in keys if spec.get(k) is not None)


def learning_packet(agents_conn: Optional[sqlite3.Connection], now_ms: int, days: int = 7) -> dict:
    from . import rooms_db as R
    from .scorecard import describe_ko, hypotheses, scorecard
    if agents_conn is None:
        return {"error": "agents3.db 없음"}
    since = now_ms - days * DAY_MS

    def q(sql: str, args: tuple = ()) -> list[tuple]:
        try:
            return [tuple(r) for r in agents_conn.execute(sql, args).fetchall()]
        except sqlite3.Error:
            return []
    graded = []
    by_role: dict = {}
    for tid, strat, spec, status, res in q(
            "SELECT t.id, t.strategy, t.spec, r.status, r.result FROM trial_results r JOIN trials t ON t.id = r.trial_id "
            "WHERE t.kind = 'hypothesis' AND r.status IN ('graded', 'expired') AND r.ts >= ? AND r.ts < ? ORDER BY r.id",
            (since, now_ms)):
        sp, body = _loads(spec) or {}, _loads(res) or {}
        p = sp.get("prediction") if isinstance(sp.get("prediction"), dict) else body.get("prediction")
        role = sp.get("by") or body.get("by") or ""
        k = by_role.setdefault(role, {"name": R.role_name(role) if role else "", "graded": 0, "correct": 0, "expired": 0})
        if status == "expired":
            k["expired"] += 1
        else:
            k["graded"] += 1
            k["correct"] += bool(body.get("correct"))
        graded.append({"trial_id": tid, "strategy": strat, "by": role, "text": str(sp.get("text") or "")[:200],
                       "prediction_ko": describe_ko(p) if isinstance(p, dict) else "", "status": status,
                       "correct": body.get("correct"), "value": _r(body.get("value"), 4), "n": body.get("n")})
    waiting = [h for h in hypotheses(agents_conn, waiting_only=True)
               if isinstance((h.get("spec") or {}).get("prediction"), dict)]
    wait_rows = [{"trial_id": h["id"], "strategy": h["strategy"], "by": (h["spec"] or {}).get("by") or "",
                  "prediction_ko": describe_ko(h["spec"]["prediction"]),
                  "days_waiting": round((now_ms - int(h["ts"])) / DAY_MS, 1)} for h in waiting[-15:][::-1]]
    tests = []
    for tid, kind, strat, spec, shash, status, res in q(
            "SELECT t.id, t.kind, t.strategy, t.spec, t.spec_hash, r.status, r.result FROM trials t JOIN trial_results r ON r.id = "
            "(SELECT MIN(x.id) FROM trial_results x WHERE x.trial_id = t.id AND x.status NOT IN ('proposed', 'lapsed')) "
            "WHERE t.kind IN ('test', 'newlab') AND r.ts >= ? AND r.ts < ? ORDER BY t.id", (since, now_ms)):
        body = _loads(res) or {}
        inner = body.get("result") if isinstance(body.get("result"), dict) else body
        gate = inner.get("gate") if isinstance(inner.get("gate"), dict) else (body.get("gate") if isinstance(
            body.get("gate"), dict) else {})
        sp = _loads(spec) or {}
        tests.append({"trial_id": tid, "kind": kind, "strategy": strat,
                      "spec": _spec_ko(sp) if kind == "test" else f"{sp.get('timeframe', '')} #{str(shash)[:8]}",
                      "status": status, "gate_pass": None if not gate else gate.get("pass") is True,
                      "gate_reasons": [str(x)[:120] for x in (gate.get("reasons") or [])][:3]})
    # repeats over the whole ledger: the same hypothesis text or prediction for one strategy, the same test spec
    hyp_text: dict = {}
    hyp_pred: dict = {}
    for tid, strat, spec in q("SELECT id, strategy, spec FROM trials WHERE kind = 'hypothesis' ORDER BY id"):
        sp = _loads(spec) or {}
        hyp_text.setdefault((strat, _norm(sp.get("text"))), []).append(tid)
        if isinstance(sp.get("prediction"), dict):
            hyp_pred.setdefault((strat, json.dumps(sp["prediction"], sort_keys=True)), []).append(tid)
    test_rep = q("SELECT strategy, spec, COUNT(*), GROUP_CONCAT(id) FROM trials WHERE kind = 'test' GROUP BY spec_hash "
                 "HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC LIMIT 15")
    repeats = {"same_text": [{"strategy": s, "trial_ids": ids} for (s, _t), ids in hyp_text.items() if len(ids) > 1][:15],
               "same_prediction": [{"strategy": s, "trial_ids": ids} for (s, _p), ids in hyp_pred.items() if len(ids) > 1][:15],
               "same_test": [{"strategy": s, "spec": _spec_ko(_loads(sp) or {}), "times": int(n),
                              "trial_ids": [int(x) for x in str(ids).split(",")]} for s, sp, n, ids in test_rep]}
    from . import packets3
    doc = packets3.research_doc() or {}
    try:
        from .rooms import LIBRARY_PRIOR_KO
    except ImportError:  # pragma: no cover
        LIBRARY_PRIOR_KO = ""
    card = scorecard(agents_conn)
    return {"window": {"from": since, "to": now_ms, "days": days},
            "graded_this_week": {"by_role": by_role, "list": graded[-30:]},
            "waiting_predictions": {"count": len(waiting), "latest": wait_rows},
            "tests_this_week": {"five_year": [t for t in tests if t["kind"] == "test"],
                                "lab": {"count": sum(t["kind"] == "newlab" for t in tests),
                                        "passed": sum(t["kind"] == "newlab" and t["gate_pass"] is True for t in tests),
                                        "list": [t for t in tests if t["kind"] == "newlab"][:10]}},
            "repeats": repeats,
            "already_known": {"entry_study": {"totals": doc.get("totals"), "conclusion_ko": doc.get("conclusion_ko")},
                              "library": LIBRARY_PRIOR_KO},
            "scorecard": {"total": card.get("total"), "roles": card.get("roles")},
            "debate_record": CM.track_record(agents_conn, recent=7),
            "note": ("코드 집계(agents3.db의 가설 장부·시험 결과). 채점은 가설을 쓴 뒤 들어간 거래로 코드가 한 번 판정한 것. "
                     "already_known은 같은 5년 자료로 이미 한 연구의 결론: 같은 것을 다시 시험해도 새 증거가 아님")}


# ---------------------------------------------------------------- the day after a US release
def _window_cell(rows: list[tuple], lo: int, hi: int) -> dict:
    ent = [d for *_x, d in rows if lo <= _f(d.get("entry_time")) < hi]
    ext = [d for *_x, d in rows if lo <= _f(d.get("exit_time")) < hi]
    n = len(ent)
    by_tf: dict = {}
    for _a, _k, _s, tf, d in rows:
        if lo <= _f(d.get("entry_time")) < hi:
            e = by_tf.setdefault(tf, [0, 0.0])
            e[0] += 1
            e[1] += _f(d.get("pnl"))
    return {"entered": n, "entered_wins": sum(1 for d in ent if _f(d.get("pnl")) > 0),
            "entered_pnl": round(sum(_f(d.get("pnl")) for d in ent), 2),
            "entered_mean_roe": round(sum(_f(d.get("roe")) for d in ent) / n, 4) if n else None,
            "closed": len(ext), "closed_pnl": round(sum(_f(d.get("pnl")) for d in ext), 2),
            "entered_by_timeframe": {tf: {"trades": v[0], "pnl": round(v[1], 2)}
                                     for tf, v in sorted(by_tf.items(), key=lambda kv: TFS.index(kv[0]) if kv[0] in TFS else 9)}}


def _move(bars: list[list], lo: int, hi: int) -> Optional[dict]:
    w = [b for b in bars if lo <= b[0] < hi]
    if not w:
        return None
    o, c = w[0][1], w[-1][4]
    hi_p, lo_p = max(b[2] for b in w), min(b[3] for b in w)
    return {"move": round(c / o - 1, 4), "range": round(hi_p / lo_p - 1, 4), "open": o, "close": c}


def event_packet(paper_ro: Optional[sqlite3.Connection], now_ms: int, event: dict, get: Optional[CM.Getter] = None,
                 liq_path: Optional[str] = None, before_ms: int = 2 * HOUR_MS, after_ms: int = 6 * HOUR_MS,
                 baseline_days: int = 5) -> dict:
    from .. import events as EV
    from .triggers import run_start
    ts = int(event["ts_ms"])
    lo, hi = ts - before_ms, ts + after_ms
    out: dict = {"event": {**event, "kst": _kst_label(ts, "%Y-%m-%d %H:%M"), "window_kst":
                           f"{_kst_label(lo, '%m/%d %H:%M')} ~ {_kst_label(hi, '%m/%d %H:%M')}"}}
    if paper_ro is None:
        out["error"] = "paper3.db 없음"
        return out
    start = run_start(paper_ro) or 0
    base: list[tuple[int, int]] = []
    import datetime as dt
    for k in range(1, 22):
        a, b = lo - k * DAY_MS, hi - k * DAY_MS
        if len(base) >= baseline_days or a < start:
            break
        wd = dt.datetime.fromtimestamp((ts - k * DAY_MS) / 1000, dt.timezone.utc).weekday()
        if wd >= 5 or EV.near(ts - k * DAY_MS, after_ms + DAY_MS // 2, before_ms + DAY_MS // 2):
            continue                       # a weekend, or another release near those hours
        base.append((a, b))
    first = min([lo] + [a for a, _b in base])
    try:
        rows = _closed(paper_ro, first - 2 * DAY_MS, hi + 2 * DAY_MS)
        flips = _closed(paper_ro, first - 2 * DAY_MS, hi + 2 * DAY_MS, kinds=("random",))
    except sqlite3.Error as exc:
        out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
        return out
    ev_cell = _window_cell(rows, lo, hi)
    base_cells = [_window_cell(rows, a, b) for a, b in base]

    def mean(key: str, cells: list[dict]) -> Optional[float]:
        return round(sum(c[key] for c in cells) / len(cells), 2) if cells else None
    out["ours"] = {"event_window": ev_cell, "baseline_days": len(base),
                   "baseline_mean": {k: mean(k, base_cells) for k in ("entered", "entered_pnl", "closed", "closed_pnl")},
                   "baseline": [{"window_kst": f"{_kst_label(a, '%m/%d %H:%M')}~", **{k: c[k] for k in (
                       "entered", "entered_pnl", "closed_pnl")}} for (a, _b), c in zip(base, base_cells)]}
    fl = _window_cell(flips, lo, hi)
    out["coin_flips"] = {"event_window": {k: fl[k] for k in ("entered", "entered_wins", "entered_pnl", "closed_pnl")},
                         "baseline_mean": {k: mean(k, [_window_cell(flips, a, b) for a, b in base])
                                           for k in ("entered", "entered_pnl")}}
    mkt = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        bars = CM.klines(get, sym, "1h", start_ms=first, end_ms=hi - HOUR_MS, limit=1000)
        if not bars:
            mkt[sym.replace("USDT", "")] = None
            continue
        m = _move(bars, lo, hi)
        bm = [x for x in (_move(bars, a, b) for a, b in base) if x]
        mkt[sym.replace("USDT", "")] = {"event_window": m, "baseline_mean_abs_move": round(
            sum(abs(x["move"]) for x in bm) / len(bm), 4) if bm else None, "baseline_mean_range": round(
            sum(x["range"] for x in bm) / len(bm), 4) if bm else None}
    out["market"] = mkt
    liq = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        e = CM.liq_view(liq_path, sym, lo, hi)
        if e is None:
            continue
        if not e.get("collected", True):              # #88: the feed stopped: say 수집 안 됨, never a zero
            liq[sym.replace("USDT", "")] = {"event_window": e, "baseline_mean_usd": None}
            continue
        bl = [x for x in (CM.liq_view(liq_path, sym, a, b) or {} for a, b in base) if x.get("collected", True)]
        liq[sym.replace("USDT", "")] = {"event_window": e, "baseline_mean_usd": round(sum(
            x.get("longs_usd", 0) + x.get("shorts_usd", 0) for x in bl) / len(bl), 0) if bl else None}
    out["liquidations"] = liq or None
    out["how_to_read"] = ("ours.event_window: 발표 2시간 전~6시간 뒤에 진입한(entered) 매매법 계좌 거래 수·이긴 수·손익($)·평균 ROE와 "
                          "그 사이 끝난(closed) 거래 손익. baseline = 앞선 평일(발표 없는 날) 같은 시간대, baseline_mean = 그 평균. "
                          "market = BTC·ETH 1시간봉(바이낸스 공개 자료)으로 본 그 시간대 움직임(0.01 = 1%), null = 못 읽음. "
                          "liquidations = 기록된 강제청산(liq.db, 많을 때 덜 셈)")
    out["note"] = ("코드 계산. 발표 하나는 표본 하나라 결론이 아니라 관찰로만. 직원은 인터넷·뉴스를 볼 수 없어 발표 내용(숫자, 예상 대비)은 "
                   "모름. 원인은 패킷 숫자로만 말함")
    return out
