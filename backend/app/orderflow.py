"""호가창 · 호가 벽 · 고래 체결 (고래맵).

- 호가창: 바이낸스 선물 depth(1000)를 가격 단위로 묶어서 보여준다.
- 호가 벽: 현재가 ±5% 안에서 주변보다 물량이 크게 쌓인 가격대.
- 고래 체결: 최근 체결(aggTrades)에서 기준 금액 이상인 것만 모은다. 바이낸스는 과거 체결을 한 번에
  많이 주지 않으므로, 서버가 켜져 있는 동안 보고 있는 심볼의 체결을 계속 모아 쌓는다.
"""
from __future__ import annotations

import asyncio
import bisect
import math
import threading
import time
from collections import deque

from . import config
from .data import binance, market, synthetic

WHALE_DEFAULT = {"BTC": 500_000, "ETH": 250_000, "SOL": 150_000}
STORE_FLOOR = 0.4        # 기본 기준의 40% 이상은 저장 (사용자가 기준을 낮춰도 보이도록)
_lock = threading.Lock()


def default_min_usd(symbol: str) -> float:
    for k, v in WHALE_DEFAULT.items():
        if symbol.startswith(k):
            return v
    return 100_000


def nice_step(x: float) -> float:
    """x 이상인 1·2·5 × 10^k 단위."""
    if x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * e >= x:
            return m * e
    return 10 * e


def _last_price(symbol: str) -> float:
    c, _ = market.candles(symbol, "1m", 2)
    return c[-1]["close"]


def _raw_book(symbol: str) -> tuple[dict, str]:
    if config.DATA_SOURCE != "synthetic":
        try:
            return binance.depth(symbol, 1000), "binance"
        except Exception:
            if config.DATA_SOURCE == "binance":
                raise
    return synthetic.depth(symbol, _last_price(symbol)), "synthetic"


def _group(levels: list[list[float]], step: float, side: str) -> list[dict]:
    agg: dict[float, float] = {}
    for p, q in levels:
        k = (math.floor(p / step) if side == "bid" else math.ceil(p / step)) * step
        agg[k] = agg.get(k, 0.0) + q
    keys = sorted(agg, reverse=(side == "bid"))
    out, cum = [], 0.0
    for k in keys:
        cum += agg[k]
        out.append({"price": round(k, 10), "qty": agg[k], "usd": agg[k] * k, "cum": cum})
    return out


def find_walls(book: dict, mid: float, span: float = 0.05, n: int = 8) -> list[dict]:
    step = nice_step(mid * 0.001)
    lo, hi = mid * (1 - span), mid * (1 + span)
    buckets = []
    for side, levels in (("bid", book["bids"]), ("ask", book["asks"])):
        for g in _group([lv for lv in levels if lo <= lv[0] <= hi], step, side):
            buckets.append({**g, "side": side})
    if not buckets:
        return []
    usd = sorted(b["usd"] for b in buckets)
    median = usd[len(usd) // 2]
    walls = [b for b in buckets if b["usd"] >= median * 3]
    walls.sort(key=lambda b: -b["usd"])
    return [{"price": w["price"], "usd": w["usd"], "side": w["side"]} for w in walls[:n]]


# ---------------------------------------------------------------- 진입 도구: 깊이 불균형 · 슬리피지 · 벽 추적 · 진입 계획
DEPTHS = (0.25, 0.5, 1.0, 2.0)
SIZES = (10_000, 100_000, 1_000_000, 5_000_000)


def depth_stats(book: dict, mid: float) -> list[dict]:
    out = []
    for pct in DEPTHS:
        lo, hi = mid * (1 - pct / 100), mid * (1 + pct / 100)
        b = sum(p * q for p, q in book["bids"] if p >= lo)
        a = sum(p * q for p, q in book["asks"] if p <= hi)
        out.append({"pct": pct, "bid_usd": b, "ask_usd": a, "imbalance": (b - a) / (b + a) if b + a else 0.0})
    return out


def slippage(book: dict, mid: float, sizes=SIZES) -> list[dict]:
    """시장가로 usd 만큼 사면(팔면) 호가를 먹어 들어가며 평균 체결가가 얼마나 밀리는지."""
    out = []
    for usd in sizes:
        row = {"usd": usd}
        for side, levels in (("buy", book["asks"]), ("sell", book["bids"])):
            left, cost, qty, last = usd, 0.0, 0.0, None
            for p, q in levels:
                take = min(left, p * q)
                cost += take
                qty += take / p
                left -= take
                last = p
                if left <= 1e-9:
                    break
            if left > 1e-9 or not qty:
                row[side] = None                        # 받아온 호가(±수 %) 안에 물량이 모자람
            else:
                avg = cost / qty
                row[side] = {"avg": avg, "slip_pct": abs(avg / mid - 1) * 100, "worst": last}
        out.append(row)
    return out


class WallTracker:
    """보고 있는 동안 호가 벽이 얼마나 오래 있었는지, 가격이 닿기 전에 사라진 벽(허수 의심)은 무엇인지 기록."""

    def __init__(self):
        self.seen: dict[str, dict[tuple, dict]] = {}
        self.pulled: dict[str, deque] = {}
        self.history: dict[str, deque] = {}

    def update(self, symbol: str, walls: list[dict], mid: float, imbalance: float) -> list[dict]:
        now = time.time()
        with _lock:
            prev = self.seen.get(symbol, {})
            cur: dict[tuple, dict] = {}
            for w in walls:
                key = (w["side"], w["price"])
                first = prev.get(key, {}).get("first", now)
                cur[key] = {**w, "first": first, "last": now, "peak": max(w["usd"], prev.get(key, {}).get("peak", 0))}
            pulled = self.pulled.setdefault(symbol, deque(maxlen=30))
            for key, w in prev.items():
                if key in cur or now - w["last"] > 60:
                    continue
                reached = mid <= w["price"] * 1.0005 if w["side"] == "bid" else mid >= w["price"] * 0.9995
                if not reached and w["last"] - w["first"] >= 5:    # 가격이 닿지 않았는데 사라짐
                    pulled.append({"side": w["side"], "price": w["price"], "usd": w["peak"], "lived_sec": round(w["last"] - w["first"]),
                                   "time": int(now)})
            self.seen[symbol] = cur
            h = self.history.setdefault(symbol, deque(maxlen=240))
            h.append({"time": int(now), "imbalance": round(imbalance, 4), "mid": mid})
            return [{**w, "age_sec": round(now - w["first"])} for w in cur.values()]


walls_tracker = WallTracker()


def entry_plan(mid: float, walls: list[dict], depth: list[dict], tick: float) -> dict:
    """벽을 근거로 한 롱·숏 진입 계획. 벽 바로 앞에 지정가, 벽 너머에 손절, 반대편 벽 앞에서 익절."""
    bids = sorted([w for w in walls if w["side"] == "bid" and w["price"] < mid and mid / w["price"] - 1 <= 0.02], key=lambda w: -w["usd"])
    asks = sorted([w for w in walls if w["side"] == "ask" and w["price"] > mid and w["price"] / mid - 1 <= 0.02], key=lambda w: -w["usd"])
    plans = {}
    if bids:
        b = bids[0]
        entry = b["price"] + tick
        stop = b["price"] * 0.997
        tp = (asks[0]["price"] - tick) if asks else entry + 2 * (entry - stop)
        plans["long"] = {"entry": entry, "stop": stop, "take": tp, "rr": round((tp - entry) / (entry - stop), 2) if entry > stop else None,
                         "why": f"매수 벽 {b['price']:.6g} (${b['usd'] / 1e6:.2f}M) 바로 위에 지정가 — 벽이 받쳐 주는 동안만 유효, 벽이 사라지면 취소"}
    if asks:
        a = asks[0]
        entry = a["price"] - tick
        stop = a["price"] * 1.003
        tp = (bids[0]["price"] + tick) if bids else entry - 2 * (stop - entry)
        plans["short"] = {"entry": entry, "stop": stop, "take": tp, "rr": round((entry - tp) / (stop - entry), 2) if stop > entry else None,
                          "why": f"매도 벽 {a['price']:.6g} (${a['usd'] / 1e6:.2f}M) 바로 아래 지정가 — 벽이 누르는 동안만 유효"}
    near = depth[1]["imbalance"] if len(depth) > 1 else 0
    bias = "long" if near >= 0.2 else "short" if near <= -0.2 else "neutral"
    return {"bias": bias, "plans": plans,
            "note": {"long": "현재가 ±0.5% 안 매수 호가가 두껍습니다 (아래가 단단함)",
                     "short": "현재가 ±0.5% 안 매도 호가가 두껍습니다 (위가 무거움)",
                     "neutral": "가까운 호가는 균형 — 호가만으로는 방향 우위 없음"}[bias]}


def orderbook(symbol: str, step: float | None = None, rows: int = 20) -> dict:
    book, src = _raw_book(symbol)
    best_bid, best_ask = book["bids"][0][0], book["asks"][0][0]
    mid = (best_bid + best_ask) / 2
    step = step or nice_step(mid * 0.00005)
    near = lambda lv: abs(lv[0] - mid) / mid <= 0.01
    bid_usd = sum(p * q for p, q in book["bids"] if near((p, q)))
    ask_usd = sum(p * q for p, q in book["asks"] if near((p, q)))
    imb = (bid_usd - ask_usd) / (bid_usd + ask_usd) if bid_usd + ask_usd else 0.0
    walls = find_walls(book, mid)
    tracked = walls_tracker.update(symbol, walls, mid, imb)
    depth = depth_stats(book, mid)
    return {
        "symbol": symbol, "source": src, "time": book["time"], "step": step,
        "steps": [nice_step(mid * f) for f in (0.00001, 0.00005, 0.0001, 0.0005, 0.001)],
        "mid": mid, "spread": best_ask - best_bid, "spread_bps": (best_ask - best_bid) / mid * 1e4,
        "bids": _group(book["bids"], step, "bid")[:rows],
        "asks": _group(book["asks"], step, "ask")[:rows],
        "imbalance": imb, "bid_usd_1pct": bid_usd, "ask_usd_1pct": ask_usd,
        "walls": tracked, "depth": depth, "slippage": slippage(book, mid),
        "pulled": list(walls_tracker.pulled.get(symbol, []))[-8:],
        "imbalance_history": list(walls_tracker.history.get(symbol, []))[-120:],
        "plan": entry_plan(mid, find_walls(book, mid, span=0.02, n=10), depth, nice_step(mid * 0.0001)),
    }


class WhaleTracker:
    """보고 있는 심볼의 큰 체결을 계속 모은다 (심볼당 최근 5000건)."""

    def __init__(self):
        self.trades: dict[str, deque] = {}
        self.last_id: dict[str, int] = {}
        self.touched: dict[str, float] = {}
        self.started: dict[str, int] = {}
        self._task: asyncio.Task | None = None

    def poll(self, symbol: str) -> None:
        rows = binance.agg_trades(symbol, 1000)
        floor = default_min_usd(symbol) * STORE_FLOOR
        with _lock:
            dq = self.trades.setdefault(symbol, deque(maxlen=5000))
            last = self.last_id.get(symbol, -1)
            for t in rows:
                if t["id"] > last and t["usd"] >= floor:
                    dq.append(t)
            if rows:
                self.last_id[symbol] = max(last, rows[-1]["id"])
                self.started.setdefault(symbol, rows[0]["time"])

    def get(self, symbol: str, min_usd: float, since: int) -> list[dict]:
        with _lock:
            return [t for t in self.trades.get(symbol, ()) if t["usd"] >= min_usd and t["time"] >= since]

    def touch(self, symbol: str) -> None:
        self.touched[symbol] = time.time()

    def tick(self) -> None:
        now = time.time()
        for sym, t in list(self.touched.items()):
            if now - t < 900:   # 15분 안에 본 심볼만 계속 수집
                try:
                    self.poll(sym)
                except Exception:
                    pass

    async def run_forever(self):
        while True:
            if config.DATA_SOURCE != "synthetic":
                await asyncio.to_thread(self.tick)
            await asyncio.sleep(4)

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self.run_forever())


tracker = WhaleTracker()


def whales(symbol: str, interval: str, limit: int = 500, min_usd: float | None = None) -> dict:
    min_usd = min_usd or default_min_usd(symbol)
    candles, src = market.candles(symbol, interval, limit)
    since = candles[0]["time"]
    trades, collecting_since = [], None
    if src == "binance":
        tracker.touch(symbol)
        try:
            tracker.poll(symbol)
        except Exception:
            pass
        trades = tracker.get(symbol, min_usd, since)
        collecting_since = tracker.started.get(symbol)
    else:
        trades = [t for t in synthetic.trades(symbol, candles, min_usd) if t["usd"] >= min_usd]
    times = [b["time"] for b in candles]
    for t in trades:
        t["bar"] = times[max(0, bisect.bisect_right(times, t["time"]) - 1)]   # 체결이 속한 봉의 시작 시각
    try:
        walls = orderbook(symbol)["walls"]
    except Exception:
        walls = []
    return {"symbol": symbol, "interval": interval, "min_usd": min_usd, "source": src,
            "collecting_since": collecting_since, "trades": trades[-3000:], "walls": walls}

