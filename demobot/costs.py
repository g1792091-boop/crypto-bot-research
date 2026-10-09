"""Real costs from the Binance order book (CONTRACT 8.3): what a market order of each size would have paid when the
demo lab entered, against the engine's assumed 2 bps of slippage; and, for the limit entries of the private
plug-ins, whether the fill bar traded through the limit or only touched it.

The book is read once per tick (after the new bars, ~25-40 s after the 15m open, when a real bot would send its
order). Only cost curves are kept (bps per order size), not the levels. Records only: nothing here changes a trade.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from . import accounts as A
from . import exits as X
from . import grid as G

SIZES = [500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000]
DEPTH_LIMIT = 500
ASSUMED_BPS = X.SLIP * 1e4          # the engine's slippage per side (2 bps)
TOUCH_BPS = 1.0                     # a limit fill whose bar went less than this beyond the limit: "touch only"
SERIES_MAX = 800
M15 = 15 * 60 * 1000
NOTES_KO = [
    "호가는 15분봉이 열리고 약 25~40초 뒤에 읽습니다 (실제 봇이 주문을 낼 때쯤). 봉 시작 가격에서 그사이 움직인 것은 빼고, "
    "호가 두께 때문에 드는 비용만 셉니다.",
    "엔진은 진입·청산마다 0.02%(2bp)의 미끄러짐을 가정합니다. '추가 비용'은 실제 호가로 잰 비용에서 이 2bp를 뺀 것입니다.",
    "청산할 때의 호가는 따로 재지 않고 진입과 같다고 보고 왕복으로 계산합니다.",
    "지정가 진입(비공개 매매법)은 호가 대신 그 봉이 지정가를 얼마나 넘어갔는지 봅니다. 1bp도 못 넘고 '닿기만' 한 경우는 "
    "실제로는 체결이 안 됐을 수 있습니다.",
]


def book_cost_bps(levels, notional: float, mid: float) -> Optional[float]:
    """Walk ``levels`` ([price, qty] best first) for ``notional`` USD; (VWAP - mid) / mid in bps, adverse direction
    positive. None when the levels do not cover the size."""
    left, qty, cost = float(notional), 0.0, 0.0
    for p, q in levels:
        p, q = float(p), float(q)
        if left <= 1e-9:
            break
        take = min(q, left / p)
        qty += take
        cost += take * p
        left -= take * p
    if left > 1e-6 * max(1.0, notional) or qty <= 0:
        return None
    vwap = cost / qty
    return abs(vwap - mid) / mid * 1e4


def curve_from_depth(d: dict) -> Optional[tuple]:
    """(bid, ask, buy_bps per size, sell_bps per size) from a /fapi/v1/depth answer."""
    bids, asks = d.get("bids") or [], d.get("asks") or []
    if not bids or not asks:
        return None
    bid, ask = float(bids[0][0]), float(asks[0][0])
    if not (bid > 0 and ask > 0 and ask >= bid):
        return None
    mid = (bid + ask) / 2
    buy = [book_cost_bps(asks, s, mid) for s in SIZES]
    sell = [book_cost_bps(bids, s, mid) for s in SIZES]
    return bid, ask, buy, sell


def fetch_rows(market, bar_open_ms: int, log=print) -> list:
    """One depth row per coin for the bar that just opened (put_depth rows). Errors skip that coin."""
    rows = []
    for coin in G.COINS:
        try:
            d = market.depth(coin, DEPTH_LIMIT)
            c = curve_from_depth(d or {})
        except Exception as exc:          # never stops a tick
            log("depth failed:", coin, type(exc).__name__)
            continue
        if c is not None:
            rows.append((coin, int(bar_open_ms)) + c)
    return rows


def interp_bps(curve: list, notional: float) -> Optional[float]:
    """Cost at ``notional`` by linear interpolation between SIZES (below the first size: the first size's cost)."""
    if notional is None or not np.isfinite(notional) or notional <= 0:
        return None
    if notional <= SIZES[0]:
        return curve[0]
    for i in range(1, len(SIZES)):
        if notional <= SIZES[i]:
            a, b = curve[i - 1], curve[i]
            if a is None or b is None:
                return None
            f = (notional - SIZES[i - 1]) / (SIZES[i] - SIZES[i - 1])
            return a + f * (b - a)
    return None


def depth_index(rows: list) -> dict:
    return {(r["coin"], int(r["ts"])): r for r in rows}


def through_bps(eng, coin: str, entry_ms: int, side: int, limit_px: float) -> Optional[float]:
    """How far the fill bar of a limit entry traded beyond the limit (bps)."""
    b = eng.b15.get(coin)
    if b is None or not len(b["ts"]) or not limit_px:
        return None
    i = int(np.searchsorted(b["ts"], entry_ms, side="right")) - 1
    if i < 0 or i >= len(b["ts"]) or entry_ms - int(b["ts"][i]) >= M15:
        return None
    if side > 0:
        return (limit_px - float(b["l"][i])) / limit_px * 1e4
    return (float(b["h"][i]) - limit_px) / limit_px * 1e4


def annotate(eng, res: dict, didx: dict) -> None:
    """Adds cost_bps / through_bps to every trade of every plain line (in place)."""
    for aid, r in res.items():
        for L, sim in r["lines"].items():
            for t in sim["trades"]:
                t["cost_bps"] = None
                t["through_bps"] = None
                if t.get("maker"):
                    t["through_bps"] = through_bps(eng, t["coin"], t["entry_ms"], t["side"], t["entry"])
                    continue
                d = didx.get((t["coin"], int(t["entry_ms"])))
                if d is not None:
                    t["cost_bps"] = interp_bps(d["buy"] if t["side"] > 0 else d["sell"], t.get("notional"))


def _q(vals: list, q: float) -> Optional[float]:
    v = [x for x in vals if x is not None and np.isfinite(x)]
    return float(np.percentile(v, q)) if v else None


def _down(points: list, limit: int = SERIES_MAX) -> list:
    if len(points) <= limit:
        return points
    step = len(points) / (limit - 1)
    idx = sorted({int(i * step) for i in range(limit - 1)} | {len(points) - 1})
    return [points[i] for i in idx]


def snapshot(eng, res: dict, rows: list, now_ms: int) -> dict:
    """costs.json (CONTRACT 8.3). ``rows``: depth rows (store.load_depth) of the live period; trades annotated."""
    coins, series = [], []
    i10k = SIZES.index(10000)
    for coin in G.COINS:
        cr = [r for r in rows if r["coin"] == coin]
        spreads = [(r["ask"] - r["bid"]) / ((r["ask"] + r["bid"]) / 2) * 1e4 for r in cr]
        item = dict(coin=coin, n=len(cr), last_ms=(cr[-1]["ts"] if cr else None),
                    spread_bps=dict(last=(spreads[-1] if spreads else None), median=_q(spreads, 50)))
        for side in ("buy", "sell"):
            cols = list(zip(*[r[side] for r in cr])) if cr else [[] for _ in SIZES]
            item[f"{side}_bps"] = dict(median=[_q(list(c), 50) for c in cols], p90=[_q(list(c), 90) for c in cols],
                                       last=(list(cr[-1][side]) if cr else [None] * len(SIZES)))
        coins.append(item)
        series.append(dict(coin=coin, points=_down([[int(r["ts"]), s, r["buy"][i10k]] for r, s in zip(cr, spreads)])))
    lines, maker = [], []
    for a in A.current_accounts():
        r = res.get(a.id)
        if r is None:
            continue
        for L, sim in r["lines"].items():
            ts = sim["trades"]
            meas = [t for t in ts if t.get("cost_bps") is not None]
            pnl = sim["line"]["pnl"]
            if meas:
                extra = [(t["cost_bps"] - ASSUMED_BPS) for t in meas]
                extra_R = [(t["cost_bps"] - ASSUMED_BPS) / 1e4 * t["entry"] / t["risk"]
                           for t in meas if t.get("risk")]
                adj = sum(2 * (t["cost_bps"] - ASSUMED_BPS) / 1e4 * t["notional"] for t in meas)
                lines.append(dict(id=a.id, name=a.name, L=int(L), n=len(meas), mean_extra_bps=float(np.mean(extra)),
                                  mean_extra_R=(float(np.mean(extra_R)) if extra_R else None),
                                  mean_cost_bps=float(np.mean([t["cost_bps"] for t in meas])),
                                  pnl=pnl, pnl_adj=pnl - adj, pnl_adj_pct=(pnl - adj) / A.SEED * 100,
                                  extra_cost=adj))
            mk = [t for t in ts if t.get("maker")]
            if mk:
                touch = [t for t in mk if t.get("through_bps") is not None and t["through_bps"] < TOUCH_BPS]
                strict = pnl - sum(t["pnl"] for t in touch)
                maker.append(dict(id=a.id, name=a.name, L=int(L), n=len(mk), touch_only=len(touch),
                                  touch_share=len(touch) / len(mk), pnl=pnl, pnl_strict=strict))
    return dict(generated_ms=now_ms, since_ms=(rows[0]["ts"] if rows else None), assumed_bps=ASSUMED_BPS,
                sizes=list(SIZES), coins=coins, series=series, lines=lines, maker=maker, notes_ko=list(NOTES_KO))


def line_costs(costs: dict, aid: str, L: int) -> dict:
    """{"entry_bps", "roundtrip_pct_of_pnl"} of one line (for the candidate cards)."""
    for r in costs.get("lines", []):
        if r["id"] == aid and r["L"] == L:
            pnl = r["pnl"]
            return dict(entry_bps=r["mean_cost_bps"],
                        roundtrip_pct_of_pnl=(r["extra_cost"] / pnl * 100 if pnl and pnl > 0 else None))
    return dict(entry_bps=None, roundtrip_pct_of_pnl=None)


def median_entry_bps(costs: dict) -> Optional[float]:
    v = [c["buy_bps"]["median"][SIZES.index(5000)] for c in costs.get("coins", [])
         if c["buy_bps"]["median"] and c["buy_bps"]["median"][SIZES.index(5000)] is not None]
    return float(np.median(v)) if v else None
