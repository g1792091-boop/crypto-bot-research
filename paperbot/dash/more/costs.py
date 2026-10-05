"""비용 점검 (매매법 › 분석 › 비용, ranked #8): where the money leaks. Read-only.

    GET /api/v4/costs

1. Fees and funding per group, from the closed trades (paper3.db ``trades``: pnl is after costs, data.fees and
   data.funding are what the engine charged, so "before costs" = pnl + fees + funding; engine.py _finish).
   - per trade, as a share of the trade's margin (the ROE units every group shares): before costs, fees, funding,
     after costs (means). Every group gets this line, the coin flips always next to the strategies.
   - money sums (USDT) for core / reel / extra only. DeepSeek and the coin flips are counted, never summed in money
     (owners' D10 / D11, CONTRACT rule 3).
   - by timeframe for the 36 and their same-bar coin flips (15m-4h), the reel against its three 5m flips.
2. Real quotes (추정, records only, the paper fills never change):
   - stop slippage of SL / LOCK / LIQ exits estimated nightly from Binance's public trades (daily3.db ``stop_slips``,
     paperbot/daily3.py + slipcost.py): adverse basis points vs the stop price, against what paper assumed;
   - order-book cost at the paper size (paper3.db ``fill_costs`` ``slip_best``, the runner's book reads), entry / exit.
   Both are compared with the paper assumption (config ``slippage_frac``, 0.02 % = 2 bp).

Cost: the trade sums are incremental (each request reads only the trades after the last id it saw; a smaller max id =
a new database, read again from the start); slippage rows are one indexed range read each. Cached 5 minutes.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import statistics
import threading
import time
from typing import Optional

TTL_S = 300.0
MAIN_GROUPS = ("core", "reel", "extra")             # money per group (D10 / D11)
ORDER = ("core", "flip_same", "ds200", "reel", "flip5", "extra")
CORE_TFS = ("15m", "30m", "1h", "4h")
_F = 9                                              # n, pnl, fees, funding, roe, fee_roe, fund_roe, liq, wins


def _r(x: Optional[float], nd: int = 6) -> Optional[float]:
    return None if x is None else round(float(x), nd)


def _q(xs: list, q: float) -> Optional[float]:
    """The q-quantile (nearest rank) of xs; None when empty."""
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]


class Sums:
    """Per-account running sums of the closed trades, read incrementally by trade id."""

    def __init__(self):
        self.last_id = 0
        self.acc: dict = {}
        self.lock = threading.Lock()

    def update(self, c: sqlite3.Connection) -> None:
        with self.lock:
            top = c.execute("SELECT COALESCE(MAX(id), 0) FROM trades").fetchone()[0]
            if top < self.last_id:                  # a new database (reset): read again from the start
                self.last_id, self.acc = 0, {}
            if top == self.last_id:
                return
            for (aid, n, pnl, fees, fund, roe, froe, uroe, liq, wins) in c.execute(
                    "SELECT account_id, COUNT(*), SUM(pnl), "
                    "SUM(COALESCE(json_extract(data, '$.fees'), 0)), SUM(COALESCE(json_extract(data, '$.funding'), 0)), "
                    "SUM(roe), "
                    "SUM(CASE WHEN json_extract(data, '$.margin') > 0 THEN COALESCE(json_extract(data, '$.fees'), 0) "
                    "    / json_extract(data, '$.margin') ELSE 0 END), "
                    "SUM(CASE WHEN json_extract(data, '$.margin') > 0 THEN COALESCE(json_extract(data, '$.funding'), 0) "
                    "    / json_extract(data, '$.margin') ELSE 0 END), "
                    "SUM(exit_reason = 'LIQ'), SUM(pnl > 0) "
                    "FROM trades WHERE id > ? AND id <= ? GROUP BY account_id", (self.last_id, top)):
                a = self.acc.setdefault(aid, [0.0] * _F)
                for i, v in enumerate((n, pnl, fees, fund, roe, froe, uroe, liq, wins)):
                    a[i] += float(v or 0)
            self.last_id = top


def _group_key(a: dict) -> Optional[str]:
    g = a.get("group")
    if g == "flip":
        return "flip5" if a.get("timeframe") == "5m" else "flip_same"
    return g if g in ORDER else None


def _cell(rows: list, money: bool) -> dict:
    """Summed sums of some accounts -> one line (per trade always; money only when ``money``)."""
    s = [0.0] * _F
    for r in rows:
        for i in range(_F):
            s[i] += r[i]
    n = int(s[0])
    out = {"accounts": len(rows), "trades": n, "liq": int(s[7]), "wins": int(s[8])}
    if n:
        fee, fund, net = s[5] / n, s[6] / n, s[4] / n
        out["per_trade"] = {"before": _r(net + fee + fund), "fees": _r(fee), "funding": _r(fund), "after": _r(net)}
    else:
        out["per_trade"] = None
    if money:
        out["money"] = {"before": _r(s[1] + s[2] + s[3], 2), "fees": _r(s[2], 2), "funding": _r(s[3], 2),
                        "after": _r(s[1], 2)}
    return out


def groups_view(accts: list, sums: dict) -> dict:
    """{groups: {key: line}, by_tf: {core: {tf: line}, flip_same: {tf: line}}}."""
    zero = [0.0] * _F
    by: dict = {}
    for a in accts:
        k = _group_key(a)
        if k:
            by.setdefault(k, []).append((a, sums.get(a["account_id"], zero)))
    groups = {k: _cell([s for _a, s in by[k]], k in MAIN_GROUPS) for k in ORDER if k in by}
    by_tf: dict = {}
    for k in ("core", "flip_same", "ds200"):
        for tf in CORE_TFS:
            xs = [s for a, s in by.get(k, []) if a.get("timeframe") == tf]
            if xs:
                by_tf.setdefault(k, {})[tf] = _cell(xs, k in MAIN_GROUPS)
    return {"groups": groups, "by_tf": by_tf}


def stop_view(d: Optional[sqlite3.Connection], start: int, paper_bps: float, main_ids: set) -> dict:
    """Stop slippage of the run's SL / LOCK / LIQ exits from daily3.db stop_slips (추정)."""
    if d is None:
        return {"ready": False, "note": "밤 점검 기록(daily3.db)이 아직 없습니다"}
    try:
        rows = d.execute("SELECT account_id, exit_reason, status, paper_bps, real_bps, diff_usd FROM stop_slips "
                         "WHERE exit_time >= ?", (start,)).fetchall()
    except sqlite3.Error:
        return {"ready": False, "note": "손절 미끄러짐 기록이 아직 없습니다 (밤 점검이 처음 돈 뒤 생김)"}
    ok = [r for r in rows if r[2] == "ok" and r[4] is not None]
    out = {"ready": True, "exits": len(rows), "estimated": len(ok), "paper_assume_bps": paper_bps}
    if not ok:
        out["note"] = "추정할 수 있는 손절 청산이 아직 없습니다"
        return out
    real = [float(r[4]) for r in ok]
    paper = [float(r[3]) for r in ok if r[3] is not None]
    out.update({
        "real_median_bps": _r(statistics.median(real), 2), "real_p90_bps": _r(_q(real, 0.9), 2),
        "paper_median_bps": _r(statistics.median(paper), 2) if paper else None,
        "worse_than_paper": sum(1 for r in ok if r[3] is not None and float(r[4]) > float(r[3]) + 1e-9),
        # money only for core / reel / extra accounts (D10 / D11): what real stops would have cost beyond paper
        "extra_cost_main_usd": _r(sum(float(r[5] or 0) for r in ok if r[0] in main_ids), 2),
        "by_reason": {},
    })
    for reason in ("SL", "LOCK", "LIQ"):
        xs = [float(r[4]) for r in ok if r[1] == reason]
        if xs:
            out["by_reason"][reason] = {"n": len(xs), "real_median_bps": _r(statistics.median(xs), 2)}
    return out


def book_view(c: sqlite3.Connection, start: int, paper_bps: float) -> dict:
    """Order-book cost at the paper size from paper3.db fill_costs (status ok), entry and exit (추정)."""
    try:
        rows = c.execute("SELECT event, slip_best FROM fill_costs WHERE ts >= ? AND status = 'ok' "
                         "AND slip_best IS NOT NULL", (start,)).fetchall()
    except sqlite3.Error:
        return {"ready": False, "note": "호가창 기록(fill_costs)이 없습니다"}
    out = {"ready": True, "reads": len(rows), "paper_assume_bps": paper_bps, "by_event": {}}
    for ev in sorted({r[0] for r in rows}):
        xs = [float(r[1]) * 1e4 for r in rows if r[0] == ev]
        out["by_event"][ev] = {"n": len(xs), "median_bps": _r(statistics.median(xs), 2), "p90_bps": _r(_q(xs, 0.9), 2),
                               "over_paper": sum(1 for x in xs if x > paper_bps + 1e-9)}
    if not rows:
        out["note"] = "호가창 기록이 아직 없습니다"
    return out


def costs(c: sqlite3.Connection, d: Optional[sqlite3.Connection], sums: Sums, now: int) -> dict:
    from ...config import v3_settings
    from .story import accounts, run_start
    sums.update(c)
    accts = accounts(c)
    start = run_start(c) or 0
    fee = None
    try:                                             # the run's own taker fee (dash.app Data._round_trip does the same)
        r = c.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
        fee = json.loads(r[0]).get("taker_fee") if r else None
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        fee = None
    st = v3_settings(**({"taker_fee": float(fee)} if isinstance(fee, (int, float)) and fee > 0 else {}))
    paper_bps = round(st.slippage_frac * 1e4, 4)
    view = groups_view(accts, sums.acc)
    main_ids = {a["account_id"] for a in accts if a.get("group") in MAIN_GROUPS}
    return {
        "ready": True, "now": now, "start": start,
        "fees": {"taker": st.taker_fee, "maker": st.maker_fee, "slippage": st.slippage_frac},
        **view,
        "stops": stop_view(d, start, paper_bps, main_ids),
        "book": book_view(c, start, paper_bps),
        "note": ("수수료·펀딩은 모의 계산(바이낸스 요율), 미끄러짐은 기록으로 낸 추정입니다. 모의 체결은 바뀌지 않습니다. "
                 "딥시크·동전 봇은 돈 합계 없이 거래당 비율만 셉니다."),
    }


# ---------------------------------------------------------------- the route
def register(app, ctx) -> dict:
    data = ctx.data
    daily_db = getattr(ctx, "daily_db", None)
    cache: dict = {}
    lock = threading.Lock()
    sums = Sums()

    @app.get("/api/v4/costs")
    def get_costs():
        """Fees and funding per group (coin flips beside), real stop / book slippage vs paper (추정); cached 5 min."""
        from fastapi import HTTPException

        from ..analysis import ro_connect
        from ..app import json_finite
        hit = cache.get("v")
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:
            hit = cache.get("v")
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
            d = ro_connect(daily_db)
            try:
                with contextlib.closing(data.conn()) as c:
                    v = json_finite(costs(c, d, sums, int(time.time() * 1000)))
            except sqlite3.Error as exc:
                raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}") from None
            finally:
                if d is not None:
                    d.close()
            cache["v"] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/costs"], "cache": cache, "sums": sums}
