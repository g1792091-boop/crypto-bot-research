"""잘하는 선물 트레이더들이 지금 무슨 포지션을 몇 배 레버리지로 들고 있는지.

- Hyperliquid 는 온체인 거래소라 모든 계정의 포지션이 공개된다. 리더보드에서 기간 수익 상위 계정을 골라
  계정마다 보유 포지션(방향 · 규모 · 진입가 · 레버리지 · 청산가)을 읽고, 코인별로 묶어 롱·숏 인원과 금액,
  평균 레버리지·평균 진입가를 낸다.
- 바이낸스는 개인 포지션을 공개하지 않는다. 대신 '상위 20% 트레이더 롱/숏 비율'(포지션 기준 · 계정 기준)을 공식 제공한다.
"""
from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor

from .. import config
from ..data import binance, hyperliquid, market, synthetic

_lb: tuple[float, list] | None = None
_acc: dict[str, tuple[float, dict]] = {}
WINDOWS = {"day": "24시간", "week": "7일", "month": "30일", "allTime": "전체 기간"}


def _f(x, d=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _perf(row: dict) -> dict:
    wp = row.get("windowPerformances") or []
    items = wp.items() if isinstance(wp, dict) else ((w[0], w[1]) for w in wp if len(w) == 2)
    return {k: {"pnl": _f(v.get("pnl")), "roi": _f(v.get("roi")), "vlm": _f(v.get("vlm"))} for k, v in items}


def _positions(state: dict) -> list[dict]:
    out = []
    for ap in state.get("assetPositions", []):
        p = ap.get("position", ap)
        szi = _f(p.get("szi"))
        if not szi:
            continue
        lev = p.get("leverage") or {}
        out.append({"coin": p.get("coin"), "symbol": hyperliquid.to_symbol(p.get("coin", "")), "side": "long" if szi > 0 else "short",
                    "size": abs(szi), "notional": abs(_f(p.get("positionValue"))), "entry": _f(p.get("entryPx")),
                    "leverage": _f(lev.get("value"), None) if isinstance(lev, dict) else _f(lev, None),
                    "margin_type": lev.get("type") if isinstance(lev, dict) else None,
                    "liq": _f(p.get("liquidationPx"), None) if p.get("liquidationPx") not in (None, "") else None,
                    "upnl": _f(p.get("unrealizedPnl")), "roe_pct": _f(p.get("returnOnEquity")) * 100})
    return out


def _synthetic_traders(n: int) -> list[dict]:
    """오프라인 데모용 가상 트레이더 (가격은 가상 시세 기준)."""
    rng = random.Random(int(time.time()) // 3600)
    coins = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "SUI", "kPEPE"]
    out = []
    for k in range(n):
        acct = rng.uniform(2e5, 2e7)
        pos = []
        for coin in rng.sample(coins, rng.randint(1, 3)):
            px = synthetic.candles(hyperliquid.to_symbol(coin), "1h", 2)[-1]["close"]
            side = rng.choice(["long", "long", "short"])
            lev = rng.choice([2, 3, 5, 5, 10, 10, 20, 25, 40])
            notional = acct * rng.uniform(0.2, 1.5)
            entry = px * (1 + rng.uniform(-0.04, 0.04))
            liq = entry * (1 - (1 / lev) * 0.9) if side == "long" else entry * (1 + (1 / lev) * 0.9)
            upnl = notional * ((px / entry - 1) if side == "long" else (1 - px / entry))
            pos.append({"coin": coin, "symbol": hyperliquid.to_symbol(coin), "side": side, "size": notional / px, "notional": notional,
                        "entry": entry, "leverage": lev, "margin_type": rng.choice(["cross", "isolated"]), "liq": liq,
                        "upnl": upnl, "roe_pct": upnl / (notional / lev) * 100})
        pnl = acct * rng.uniform(0.05, 1.2)
        out.append({"address": f"0x{rng.getrandbits(160):040x}", "name": None, "account_value": acct,
                    "perf": {w: {"pnl": pnl * f, "roi": pnl * f / acct, "vlm": pnl * 30} for w, f in (("day", .03), ("week", .2), ("month", 1), ("allTime", 3))},
                    "positions": pos})
    return out


def top_traders(window: str = "month", n: int = 30, sort: str = "pnl", min_account: float = 100_000) -> dict:
    global _lb
    window = window if window in WINDOWS else "month"
    src, err = "hyperliquid", None
    traders: list[dict] = []
    if config.DATA_SOURCE == "synthetic":
        src, traders = "synthetic", _synthetic_traders(n)
    else:
        try:
            if _lb is None or time.time() - _lb[0] > 1800:
                _lb = (time.time(), hyperliquid.leaderboard())
            rows = []
            for r in _lb[1]:
                pf = _perf(r)
                if window not in pf or _f(r.get("accountValue")) < min_account:
                    continue
                rows.append({"address": r.get("ethAddress"), "name": r.get("displayName"), "account_value": _f(r.get("accountValue")), "perf": pf})
            rows = [r for r in rows if r["perf"][window]["pnl"] > 0]
            rows.sort(key=lambda r: -r["perf"][window]["roi" if sort == "roi" else "pnl"])
            rows = rows[:n]

            def fill(r):
                hit = _acc.get(r["address"])
                if not hit or time.time() - hit[0] > 60:
                    hit = (time.time(), hyperliquid.account(r["address"]))
                    _acc[r["address"]] = hit
                r["positions"] = _positions(hit[1])
                return r
            with ThreadPoolExecutor(max_workers=8) as ex:
                traders = list(ex.map(fill, rows))
        except Exception as e:
            if config.DATA_SOURCE == "binance":
                raise
            err = f"Hyperliquid 에 연결하지 못했습니다: {str(e)[:120]}"
    for t in traders:
        tot = sum(p["notional"] for p in t["positions"])
        t["gross_leverage"] = round(tot / t["account_value"], 2) if t["account_value"] else None
        t["pnl"], t["roi_pct"] = t["perf"][window]["pnl"], t["perf"][window]["roi"] * 100
    # 코인별 집계
    coins: dict[str, dict] = {}
    for t in traders:
        for p in t["positions"]:
            c = coins.setdefault(p["symbol"], {"symbol": p["symbol"], "coin": p["coin"], "long": _side(), "short": _side()})
            s = c[p["side"]]
            s["traders"] += 1
            s["notional"] += p["notional"]
            s["_lev"] += (p["leverage"] or 0) * p["notional"]
            s["_entry"] += p["entry"] * p["notional"]
            s["upnl"] += p["upnl"]
    for c in coins.values():
        for k in ("long", "short"):
            s = c[k]
            s["avg_leverage"] = round(s.pop("_lev") / s["notional"], 1) if s["notional"] else None
            s["avg_entry"] = s.pop("_entry") / s["notional"] if s["notional"] else None
        tot = c["long"]["notional"] + c["short"]["notional"]
        c["total"] = tot
        c["long_share"] = round(c["long"]["notional"] / tot * 100, 1) if tot else None
        c["bias"] = "long" if (c["long_share"] or 50) >= 60 else "short" if (c["long_share"] or 50) <= 40 else "mixed"
    prices = {}
    try:
        prices = {t["symbol"]: t["price"] for t in market.tickers(list(coins))[0]}
    except Exception:
        pass
    for c in coins.values():
        c["price"] = prices.get(c["symbol"])
    return {"source": src, "window": window, "window_name": WINDOWS[window], "sort": sort, "error": err,
            "traders": sorted(traders, key=lambda t: -t["pnl"]) if sort == "pnl" else sorted(traders, key=lambda t: -t["roi_pct"]),
            "by_coin": sorted(coins.values(), key=lambda c: -c["total"]), "time": int(time.time()),
            "note": "Hyperliquid(온체인 선물 거래소)의 기간 수익 상위 계정이 지금 실제로 들고 있는 포지션입니다. "
                    "바이낸스는 개인 포지션을 공개하지 않아 '상위 트레이더 롱/숏 비율'만 볼 수 있습니다."}


def _side() -> dict:
    return {"traders": 0, "notional": 0.0, "_lev": 0.0, "_entry": 0.0, "upnl": 0.0}


def binance_ratios(symbol: str, interval: str = "1h") -> dict:
    """바이낸스 상위 트레이더 롱/숏 비율 (포지션 · 계정)."""
    if config.DATA_SOURCE != "synthetic":
        try:
            d = binance.top_trader_ratios(symbol, interval, 100)
            return {"symbol": symbol, "source": "binance", **d}
        except Exception:
            if config.DATA_SOURCE == "binance":
                raise
    c = synthetic.candles(symbol, interval, 100)
    out = {"symbol": symbol, "source": "synthetic"}
    for key, amp in (("position", 0.35), ("account", 0.25)):
        rows = []
        for i, b in enumerate(c):
            lr = 0.5 + amp * ((b["close"] / c[max(0, i - 12)]["close"]) - 1) * 10
            lr = min(0.8, max(0.2, lr))
            rows.append({"time": b["time"], "ratio": round(lr / (1 - lr), 3), "long": round(lr, 4), "short": round(1 - lr, 4)})
        out[key] = rows
    return out
