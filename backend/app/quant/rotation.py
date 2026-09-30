"""순환매 분석.

코인 시장의 자금은 대체로 비트코인 → 이더리움 → 대형 알트 → 중소형 알트 → 밈코인 순으로 돈다.
- 상대강도 회전 그래프(RRG): 기준(BTC 또는 시장 평균) 대비 상대강도의 '수준(RS-Ratio)'과 '변화(RS-Momentum)'로
  코인을 주도(Leading) · 약화(Weakening) · 소외(Lagging) · 개선(Improving) 네 구역에 놓는다.
  보통 개선 → 주도 → 약화 → 소외 방향(시계 방향)으로 돈다.
- 순환 단계: 최근 N봉 동안 어느 그룹(티어)이 가장 강했는지로 지금이 몇 단계인지 판단한다.
- 순환매 전략 백테스트: 정해진 주기마다 모멘텀 상위 K개 코인을 같은 비중으로 들고(원하면 하위 K개는 숏),
  모멘텀이 음수면 현금으로 빠진다(절대 모멘텀 필터). 비트코인 보유·동일 비중 보유와 비교한다.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

from .. import indicators as ind
from ..data import market
from ..data.synthetic import INTERVAL_SECONDS

TIER_NAME = {"btc": "비트코인", "eth": "이더리움", "large": "대형 알트", "mid": "중소형 알트", "meme": "밈코인"}
TIER_ORDER = ["btc", "eth", "large", "mid", "meme"]
LARGE = {"SOL", "BNB", "XRP", "ADA", "DOGE", "TRX", "AVAX", "LINK", "TON", "DOT", "LTC", "BCH", "SUI", "XLM", "HBAR"}
MEME = {"1000PEPE", "1000SHIB", "1000BONK", "1000FLOKI", "WIF", "PEPE", "SHIB", "BONK", "FLOKI", "1000SATS", "MEME", "BOME", "POPCAT"}
PHASE_TEXT = {
    "btc": "1단계 · 비트코인 주도 — 자금이 비트코인으로 먼저 들어오는 구간. 알트는 아직 소외돼 있습니다.",
    "eth": "2단계 · 이더리움으로 순환 — 비트코인 다음으로 이더리움이 강해지는 구간입니다.",
    "large": "3단계 · 대형 알트 순환 — 솔라나·리플 같은 대형 알트로 자금이 퍼지는 구간입니다.",
    "mid": "4단계 · 중소형 알트 확산 — 중소형 알트까지 오르는 구간. 추세 후반일 수 있습니다.",
    "meme": "5단계 · 밈코인 과열 — 알트 시즌 막바지에 자주 나오는 모습. 급락·되돌림 위험이 큽니다.",
    "off": "위험 회피 — 모든 그룹이 약합니다. 현금(스테이블) 비중을 늘리거나 숏이 유리한 구간입니다.",
}
QUAD = {"leading": "주도", "weakening": "약화", "lagging": "소외", "improving": "개선"}
DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
                    "SUIUSDT", "TRXUSDT", "DOTUSDT", "LTCUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
                    "1000PEPEUSDT", "WIFUSDT", "1000BONKUSDT"]


def tier(symbol: str) -> str:
    b = symbol.upper().removesuffix("USDT")
    if b == "BTC":
        return "btc"
    if b == "ETH":
        return "eth"
    if b in MEME:
        return "meme"
    return "large" if b in LARGE else "mid"


def load(symbols: list[str], interval: str, bars: int) -> tuple[list[int], dict[str, list[float | None]], str]:
    """BTC 시간축에 맞춘 종가표. 상장 전·빈 구간은 None (중간 빈칸은 직전 값으로 채움)."""
    syms = list(dict.fromkeys(["BTCUSDT", *symbols]))

    def get(s):
        try:
            return s, market.candles(s, interval, bars)
        except Exception:
            return s, None
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = dict(ex.map(get, syms))
    if not got.get("BTCUSDT"):
        raise ValueError("기준(BTC) 데이터를 불러오지 못했습니다")
    btc, src = got["BTCUSDT"]
    times = [b["time"] for b in btc]
    closes: dict[str, list[float | None]] = {}
    for s in syms:
        if not got.get(s):
            continue
        m = {b["time"]: b["close"] for b in got[s][0]}
        row, last, started = [], None, False
        for t in times:
            v = m.get(t)
            if v is not None:
                started, last = True, v
            row.append(v if v is not None else (last if started else None))
        closes[s] = row
    return times, closes, src


def _ret(x: list[float | None], i: int, n: int) -> float | None:
    if i - n < 0 or x[i] is None or x[i - n] is None or not x[i - n]:
        return None
    return x[i] / x[i - n] - 1


def _bench(times, closes, kind: str) -> list[float]:
    if kind == "btc":
        return closes["BTCUSDT"]
    idx, out = 1.0, []
    for i in range(len(times)):
        rs = [r for s in closes if (r := _ret(closes[s], i, 1)) is not None]
        idx *= 1 + (sum(rs) / len(rs) if rs else 0)
        out.append(idx)
    return out


def rrg(symbols: list[str] | None = None, interval: str = "1d", bench: str = "btc", fast: int = 10, slow: int = 40,
        mom: int = 5, tail: int = 8, bars: int = 400, lookback: int = 14) -> dict:
    symbols = symbols or DEFAULT_UNIVERSE
    times, closes, src = load(symbols, interval, bars)
    b = _bench(times, closes, bench)
    n = len(times)
    rows = []
    for s, x in closes.items():
        if bench == "btc" and s == "BTCUSDT":
            continue
        rs = [None if v is None or not b[i] else v / b[i] for i, v in enumerate(x)]
        ef, es = ind.ema(rs, fast), ind.ema(rs, slow)
        ratio = [None if f is None or e is None or not e else 100 * f / e for f, e in zip(ef, es)]
        momv = [None if i < mom or ratio[i] is None or ratio[i - mom] is None else 100 + (ratio[i] / ratio[i - mom] - 1) * 400
                for i in range(n)]
        pts = [{"time": times[i], "ratio": round(ratio[i], 3), "mom": round(momv[i], 3)}
               for i in range(max(0, n - tail), n) if ratio[i] is not None and momv[i] is not None]
        if not pts:
            continue
        r, m = pts[-1]["ratio"], pts[-1]["mom"]
        q = "leading" if r >= 100 and m >= 100 else "weakening" if r >= 100 else "lagging" if m < 100 else "improving"
        ret = _ret(x, n - 1, lookback)
        bret = _ret(b, n - 1, lookback)
        rows.append({"symbol": s, "tier": tier(s), "tier_name": TIER_NAME[tier(s)], "quadrant": q, "quadrant_name": QUAD[q],
                     "ratio": r, "mom": m, "tail": pts,
                     "ret_pct": None if ret is None else round(ret * 100, 2),
                     "rel_pct": None if ret is None or bret is None else round((ret - bret) * 100, 2)})
    rows.sort(key=lambda r: (-(r["rel_pct"] if r["rel_pct"] is not None else -1e9)))
    return {"interval": interval, "bench": bench, "lookback": lookback, "data_source": src, "rows": rows,
            "phase": phase(times, closes, lookback)}


def phase(times, closes, lookback: int = 14) -> dict:
    n = len(times)
    groups: dict[str, list[float]] = {t: [] for t in TIER_ORDER}
    for s, x in closes.items():
        r = _ret(x, n - 1, lookback)
        if r is not None:
            groups[tier(s)].append(r)
    avg = {t: sum(v) / len(v) * 100 for t, v in groups.items() if v}
    btc = avg.get("btc", 0.0)
    others = [s for s in closes if s != "BTCUSDT" and _ret(closes[s], n - 1, lookback) is not None]
    beat = sum(1 for s in others if _ret(closes[s], n - 1, lookback) > (_ret(closes["BTCUSDT"], n - 1, lookback) or 0))
    above = 0
    for s in closes:
        e = ind.ema([v if v is not None else float("nan") for v in closes[s]], 20)
        if closes[s][-1] is not None and e[-1] is not None and not math.isnan(e[-1]) and closes[s][-1] > e[-1]:
            above += 1
    eth = closes.get("ETHUSDT")
    ethbtc = None
    if eth and eth[-1] and eth[n - 1 - lookback] and closes["BTCUSDT"][n - 1 - lookback]:
        ethbtc = (eth[-1] / closes["BTCUSDT"][-1]) / (eth[n - 1 - lookback] / closes["BTCUSDT"][n - 1 - lookback]) - 1
    if avg and max(avg.values()) < 0:
        key = "off"
    else:
        key = max(avg, key=avg.get) if avg else "btc"
    return {"key": key, "text": PHASE_TEXT[key], "tier_ret_pct": {TIER_NAME[t]: round(v, 2) for t, v in avg.items()},
            "breadth_beat_btc_pct": round(100 * beat / len(others)) if others else None,
            "breadth_above_ema20_pct": round(100 * above / len(closes)) if closes else None,
            "ethbtc_change_pct": None if ethbtc is None else round(ethbtc * 100, 2), "btc_ret_pct": round(btc, 2)}


def backtest(symbols: list[str] | None = None, interval: str = "1d", lookback: int = 20, top: int = 3,
             rebalance: int = 7, mode: str = "long", abs_filter: bool = True, score: str = "momentum",
             fee_pct: float = 0.04, bars: int = 1000) -> dict:
    """모멘텀 순환매. mode: long(상위 K개 매수) / long_short(상위 K개 매수 + 하위 K개 숏, 시장 중립)."""
    symbols = symbols or DEFAULT_UNIVERSE
    times, closes, src = load(symbols, interval, bars)
    n = len(times)
    syms = list(closes)
    start = max(lookback, 20) + 1
    if n - start < rebalance * 3:
        raise ValueError("기간이 너무 짧습니다. 봉 개수를 늘리거나 조회 기간을 줄이세요.")
    fee = fee_pct / 100
    w: dict[str, float] = {}
    eq, curve, btc_curve, ew_curve, picks_log = 1.0, [], [], [], []
    btc0 = closes["BTCUSDT"][start - 1]
    ew = 1.0
    rets_hist = []

    def scores(i):
        out = {}
        for s in syms:
            r = _ret(closes[s], i, lookback)
            if r is None:
                continue
            if score == "risk_adj":
                rs = [q for k in range(i - lookback + 1, i + 1) if (q := _ret(closes[s], k, 1)) is not None]
                sd = math.sqrt(sum(v * v for v in rs) / len(rs)) if rs else 0
                out[s] = r / sd if sd else 0
            else:
                out[s] = r
        return out

    for i in range(start, n):
        # 봉 수익 반영 (i-1 → i)
        pr = sum(wt * (_ret(closes[s], i, 1) or 0) for s, wt in w.items())
        eq *= 1 + pr
        rets_hist.append(pr)
        rs = [r for s in syms if (r := _ret(closes[s], i, 1)) is not None]
        ew *= 1 + (sum(rs) / len(rs) if rs else 0)
        if (i - start) % rebalance == 0:
            sc = scores(i)
            ranked = sorted(sc, key=sc.get, reverse=True)
            longs = [s for s in ranked[:top] if not abs_filter or sc[s] > 0]
            shorts = [s for s in ranked[::-1][:top] if s not in longs and (not abs_filter or sc[s] < 0)] if mode == "long_short" else []
            nw: dict[str, float] = {}
            gross = len(longs) + len(shorts)
            for s in longs:
                nw[s] = 1 / gross if mode == "long_short" else 1 / len(longs)
            for s in shorts:
                nw[s] = -1 / gross
            turnover = sum(abs(nw.get(s, 0) - w.get(s, 0)) for s in set(nw) | set(w))
            eq *= 1 - turnover * fee
            w = nw
            picks_log.append({"time": times[i], "long": longs, "short": shorts,
                              "scores": {s: round(sc[s] * (100 if score == "momentum" else 1), 2) for s in longs + shorts}})
        curve.append({"time": times[i], "value": round(eq * 100, 4)})
        b = closes["BTCUSDT"][i]
        btc_curve.append({"time": times[i], "value": round(b / btc0 * 100, 4)})
        ew_curve.append({"time": times[i], "value": round(ew * 100, 4)})

    def stats(cv):
        vals = [p["value"] for p in cv]
        peak, mdd = vals[0], 0.0
        for v in vals:
            peak = max(peak, v)
            mdd = max(mdd, 1 - v / peak)
        rets = [vals[k] / vals[k - 1] - 1 for k in range(1, len(vals))]
        mu = sum(rets) / len(rets) if rets else 0
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) if rets else 0
        per_year = 365 * 86400 / INTERVAL_SECONDS.get(interval, 86400)
        return {"return_pct": round(vals[-1] - 100, 2), "max_drawdown_pct": round(mdd * 100, 2),
                "sharpe": round(mu / sd * math.sqrt(per_year), 2) if sd else None}
    sc_now = scores(n - 1)
    ranked = sorted(sc_now, key=sc_now.get, reverse=True)
    return {"interval": interval, "data_source": src, "params": {"lookback": lookback, "top": top, "rebalance": rebalance,
            "mode": mode, "abs_filter": abs_filter, "score": score, "fee_pct": fee_pct},
            "strategy": stats(curve), "btc": stats(btc_curve), "equal_weight": stats(ew_curve),
            "curve": curve, "btc_curve": btc_curve, "ew_curve": ew_curve,
            "rebalances": len(picks_log), "history": picks_log[-30:],
            "now": {"long": [s for s in ranked[:top] if not abs_filter or sc_now[s] > 0],
                    "short": [s for s in ranked[::-1][:top] if mode == "long_short" and (not abs_filter or sc_now[s] < 0)],
                    "ranking": [{"symbol": s, "score": round(sc_now[s] * (100 if score == "momentum" else 1), 2)} for s in ranked]}}
