"""TradingView(Pine Script `ta.*`)와 동일한 공식의 보조지표 구현.

TradingView 위젯은 지표 값을 외부로 내보내지 않기 때문에, 백테스트·페이퍼 트레이딩에서는
같은 공식으로 직접 계산한다. 워밍업 구간은 None.

- ta.ema / ta.rma: 첫 값은 SMA로 시드 (Pine 공식 구현과 동일)
- ta.rsi / ta.atr: RMA(Wilder) 스무딩
- ta.stdev (BB): 모집단 표준편차
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

Series = list  # list[float | None]


def _src(c: list[dict], source: str) -> Series:
    if source == "hl2":
        return [(b["high"] + b["low"]) / 2 for b in c]
    if source == "hlc3":
        return [(b["high"] + b["low"] + b["close"]) / 3 for b in c]
    if source == "ohlc4":
        return [(b["open"] + b["high"] + b["low"] + b["close"]) / 4 for b in c]
    return [b[source] for b in c]


def sma(x: Series, n: int) -> Series:
    out: Series = [None] * len(x)
    s, cnt = 0.0, 0
    window: list[float] = []
    for i, v in enumerate(x):
        if v is None:
            window.clear(); s = 0.0; cnt = 0
            continue
        window.append(v); s += v; cnt += 1
        if cnt > n:
            s -= window.pop(0); cnt -= 1
        if cnt == n:
            out[i] = s / n
    return out


def _smoothed(x: Series, n: int, alpha: float) -> Series:
    out: Series = [None] * len(x)
    prev = None
    seed: list[float] = []
    for i, v in enumerate(x):
        if v is None:
            continue
        if prev is None:
            seed.append(v)
            if len(seed) == n:
                prev = sum(seed) / n
                out[i] = prev
            continue
        prev = alpha * v + (1 - alpha) * prev
        out[i] = prev
    return out


def ema(x: Series, n: int) -> Series:
    return _smoothed(x, n, 2 / (n + 1))


def rma(x: Series, n: int) -> Series:
    return _smoothed(x, n, 1 / n)


def stdev(x: Series, n: int) -> Series:
    m = sma(x, n)
    out: Series = [None] * len(x)
    for i in range(len(x)):
        if m[i] is None:
            continue
        w = x[i - n + 1: i + 1]
        out[i] = math.sqrt(sum((v - m[i]) ** 2 for v in w) / n)
    return out


def rsi(x: Series, n: int = 14) -> Series:
    up: Series = [None] + [max(x[i] - x[i - 1], 0.0) for i in range(1, len(x))]
    dn: Series = [None] + [max(x[i - 1] - x[i], 0.0) for i in range(1, len(x))]
    au, ad = rma(up, n), rma(dn, n)
    out: Series = [None] * len(x)
    for i in range(len(x)):
        if au[i] is None or ad[i] is None:
            continue
        out[i] = 100.0 if ad[i] == 0 else (0.0 if au[i] == 0 else 100 - 100 / (1 + au[i] / ad[i]))
    return out


def true_range(c: list[dict]) -> Series:
    out: Series = []
    for i, b in enumerate(c):
        if i == 0:
            out.append(b["high"] - b["low"])
        else:
            pc = c[i - 1]["close"]
            out.append(max(b["high"] - b["low"], abs(b["high"] - pc), abs(b["low"] - pc)))
    return out


def atr(c: list[dict], n: int = 14) -> Series:
    return rma(true_range(c), n)


def macd(x: Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, Series]:
    f, s = ema(x, fast), ema(x, slow)
    line: Series = [a - b if a is not None and b is not None else None for a, b in zip(f, s)]
    sig = ema(line, signal)
    hist: Series = [a - b if a is not None and b is not None else None for a, b in zip(line, sig)]
    return {"line": line, "signal": sig, "hist": hist}


def bbands(x: Series, n: int = 20, mult: float = 2.0) -> dict[str, Series]:
    m, sd = sma(x, n), stdev(x, n)
    up = [a + mult * b if a is not None else None for a, b in zip(m, sd)]
    lo = [a - mult * b if a is not None else None for a, b in zip(m, sd)]
    width = [(u - l) / a * 100 if a else None for u, l, a in zip(up, lo, m)]
    return {"upper": up, "middle": m, "lower": lo, "width": width}


def highest(x: Series, n: int) -> Series:
    return [max(x[i - n + 1: i + 1]) if i >= n - 1 else None for i in range(len(x))]


def lowest(x: Series, n: int) -> Series:
    return [min(x[i - n + 1: i + 1]) if i >= n - 1 else None for i in range(len(x))]


def stoch(c: list[dict], n: int = 14, k_smooth: int = 3, d_smooth: int = 3) -> dict[str, Series]:
    hi, lo = highest([b["high"] for b in c], n), lowest([b["low"] for b in c], n)
    raw: Series = []
    for i, b in enumerate(c):
        if hi[i] is None:
            raw.append(None)
        else:
            rng = hi[i] - lo[i]
            raw.append(100 * (b["close"] - lo[i]) / rng if rng else 50.0)
    k = sma(raw, k_smooth)
    return {"k": k, "d": sma(k, d_smooth)}


def supertrend(c: list[dict], n: int = 10, mult: float = 3.0) -> dict[str, Series]:
    """ta.supertrend: direction -1 = 상승추세(라인이 가격 아래), +1 = 하락추세 (Pine 규약)."""
    a = atr(c, n)
    line: Series = [None] * len(c)
    direction: Series = [None] * len(c)
    prev_up = prev_dn = prev_st = None
    for i, b in enumerate(c):
        if a[i] is None:
            continue
        hl2 = (b["high"] + b["low"]) / 2
        up, dn = hl2 - mult * a[i], hl2 + mult * a[i]
        pc = c[i - 1]["close"]
        if prev_up is not None and pc >= prev_up:
            up = max(up, prev_up)
        if prev_dn is not None and pc <= prev_dn:
            dn = min(dn, prev_dn)
        if prev_st is None:
            d = 1
        elif prev_st == prev_dn:
            d = -1 if b["close"] > dn else 1
        else:
            d = 1 if b["close"] < up else -1
        st = up if d == -1 else dn
        line[i], direction[i] = st, d
        prev_up, prev_dn, prev_st = up, dn, st
    # 조건식에서 쓰기 쉽게 trend: +1 상승 / -1 하락 도 제공
    trend = [(-d if d is not None else None) for d in direction]
    return {"line": line, "direction": direction, "trend": trend}


def adx(c: list[dict], n: int = 14) -> dict[str, Series]:
    plus_dm: Series = [None]
    minus_dm: Series = [None]
    for i in range(1, len(c)):
        up = c[i]["high"] - c[i - 1]["high"]
        dn = c[i - 1]["low"] - c[i]["low"]
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
    tr = rma(true_range(c)[1:], n)
    tr = [None] + tr
    p, m = rma(plus_dm, n), rma(minus_dm, n)
    pdi = [100 * a / t if a is not None and t else None for a, t in zip(p, tr)]
    mdi = [100 * a / t if a is not None and t else None for a, t in zip(m, tr)]
    dx = [100 * abs(a - b) / (a + b) if a is not None and b is not None and (a + b) else
          (0.0 if a is not None and b is not None else None) for a, b in zip(pdi, mdi)]
    return {"adx": rma(dx, n), "plus_di": pdi, "minus_di": mdi}


def cci(c: list[dict], n: int = 20) -> Series:
    tp = _src(c, "hlc3")
    m = sma(tp, n)
    out: Series = [None] * len(c)
    for i in range(len(c)):
        if m[i] is None:
            continue
        dev = sum(abs(v - m[i]) for v in tp[i - n + 1: i + 1]) / n
        out[i] = (tp[i] - m[i]) / (0.015 * dev) if dev else 0.0
    return out


def vwap(c: list[dict]) -> Series:
    """UTC 일봉 기준으로 리셋되는 세션 VWAP."""
    out: Series = []
    day, pv, vol = None, 0.0, 0.0
    for b in c:
        d = datetime.fromtimestamp(b["time"], tz=timezone.utc).date()
        if d != day:
            day, pv, vol = d, 0.0, 0.0
        tp = (b["high"] + b["low"] + b["close"]) / 3
        pv += tp * b["volume"]; vol += b["volume"]
        out.append(pv / vol if vol else tp)
    return out


def obv(c: list[dict]) -> Series:
    out, acc = [], 0.0
    for i, b in enumerate(c):
        if i:
            if b["close"] > c[i - 1]["close"]:
                acc += b["volume"]
            elif b["close"] < c[i - 1]["close"]:
                acc -= b["volume"]
        out.append(acc)
    return out


# ---------------------------------------------------------------------------
# 추가 지표 (차트 보조지표를 자동 매매법 탐색에 쓰기 위해)
# ---------------------------------------------------------------------------
def wma(x: Series, n: int) -> Series:
    d = n * (n + 1) / 2
    out: Series = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1: i + 1]
        if any(v is None for v in w):
            continue
        out[i] = sum(v * (k + 1) for k, v in enumerate(w)) / d
    return out


def hma(x: Series, n: int) -> Series:
    h, s = max(1, round(n / 2)), max(1, round(n ** 0.5))
    a, b = wma(x, h), wma(x, n)
    return wma([2 * p - q if p is not None and q is not None else None for p, q in zip(a, b)], s)


def vwma(c: list[dict], x: Series, n: int) -> Series:
    pv = sma([v * b["volume"] if v is not None else None for v, b in zip(x, c)], n)
    vv = sma([b["volume"] for b in c], n)
    return [p / q if p is not None and q else None for p, q in zip(pv, vv)]


def mfi(c: list[dict], n: int = 14) -> Series:
    tp = _src(c, "hlc3")
    out: Series = [None] * len(c)
    for i in range(n, len(c)):
        pos = sum(tp[j] * c[j]["volume"] for j in range(i - n + 1, i + 1) if tp[j] > tp[j - 1])
        neg = sum(tp[j] * c[j]["volume"] for j in range(i - n + 1, i + 1) if tp[j] < tp[j - 1])
        out[i] = 100.0 if neg == 0 else 100 - 100 / (1 + pos / neg)
    return out


def willr(c: list[dict], n: int = 14) -> Series:
    hi, lo = highest([b["high"] for b in c], n), lowest([b["low"] for b in c], n)
    return [(-100 * (h - b["close"]) / (h - l) if h != l else -50.0) if h is not None else None for h, l, b in zip(hi, lo, c)]


def roc(x: Series, n: int = 9) -> Series:
    return [(x[i] / x[i - n] - 1) * 100 if i >= n and x[i] is not None and x[i - n] else None for i in range(len(x))]


def psar(c: list[dict], start: float = 0.02, inc: float = 0.02, mx: float = 0.2) -> dict[str, Series]:
    out: Series = [None] * len(c)
    trend: Series = [None] * len(c)
    if len(c) < 3:
        return {"value": out, "trend": trend}
    up = c[1]["close"] >= c[0]["close"]
    af, ep, sar = start, (c[1]["high"] if up else c[1]["low"]), (c[0]["low"] if up else c[0]["high"])
    for i in range(2, len(c)):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, c[i - 1]["low"], c[i - 2]["low"])
            if c[i]["low"] < sar:
                up, sar, ep, af = False, ep, c[i]["low"], start
            elif c[i]["high"] > ep:
                ep, af = c[i]["high"], min(af + inc, mx)
        else:
            sar = max(sar, c[i - 1]["high"], c[i - 2]["high"])
            if c[i]["high"] > sar:
                up, sar, ep, af = True, ep, c[i]["high"], start
            elif c[i]["low"] < ep:
                ep, af = c[i]["low"], min(af + inc, mx)
        out[i], trend[i] = sar, (1 if up else -1)
    return {"value": out, "trend": trend}


def donchian(c: list[dict], n: int = 20) -> dict[str, Series]:
    hi, lo = highest([b["high"] for b in c], n), lowest([b["low"] for b in c], n)
    return {"upper": hi, "lower": lo, "middle": [(a + b) / 2 if a is not None else None for a, b in zip(hi, lo)]}


def keltner(c: list[dict], n: int = 20, mult: float = 2.0) -> dict[str, Series]:
    m, a = ema(_src(c, "close"), n), atr(c, n)
    return {"upper": [p + mult * q if p is not None and q is not None else None for p, q in zip(m, a)], "middle": m,
            "lower": [p - mult * q if p is not None and q is not None else None for p, q in zip(m, a)]}


def stochrsi(x: Series, n: int = 14, k_smooth: int = 3, d_smooth: int = 3) -> dict[str, Series]:
    r = rsi(x, n)
    raw: Series = [None] * len(x)
    for i in range(len(x)):
        w = r[max(0, i - n + 1): i + 1]
        if i < n - 1 or any(v is None for v in w):
            continue
        h, lo_ = max(w), min(w)
        raw[i] = 100 * (r[i] - lo_) / (h - lo_) if h != lo_ else 50.0
    k = sma(raw, k_smooth)
    return {"k": k, "d": sma(k, d_smooth)}


def ichimoku(c: list[dict], conv: int = 9, base: int = 26, span: int = 52) -> dict[str, Series]:
    def mid(n):
        h, l = highest([b["high"] for b in c], n), lowest([b["low"] for b in c], n)
        return [(a + b) / 2 if a is not None else None for a, b in zip(h, l)]
    t, k, sb = mid(conv), mid(base), mid(span)
    sa = [(a + b) / 2 if a is not None and b is not None else None for a, b in zip(t, k)]
    sh = lambda x: [None] * (base - 1) + x[:len(x) - base + 1]   # 구름은 base-1 봉 앞으로 (지금 봉 위치의 구름)
    return {"tenkan": t, "kijun": k, "span_a": sh(sa), "span_b": sh(sb)}


def cmf(c: list[dict], n: int = 20) -> Series:
    mfv = [((b["close"] - b["low"]) - (b["high"] - b["close"])) / (b["high"] - b["low"]) * b["volume"] if b["high"] != b["low"] else 0.0 for b in c]
    a, v = sma(mfv, n), sma([b["volume"] for b in c], n)
    return [p / q if p is not None and q else None for p, q in zip(a, v)]


def aroon(c: list[dict], n: int = 25) -> dict[str, Series]:
    up: Series = [None] * len(c)
    dn: Series = [None] * len(c)
    for i in range(n, len(c)):
        w = c[i - n: i + 1]
        hi = max(range(len(w)), key=lambda k: (w[k]["high"], k))
        lo = min(range(len(w)), key=lambda k: (w[k]["low"], -k))
        up[i], dn[i] = 100 * hi / n, 100 * lo / n
    return {"up": up, "down": dn}


def atr_stop(c: list[dict], n: int = 14, mult: float = 3.0) -> dict[str, Series]:
    """ATR 추적 손절선 (UT Bot 계열). trend: +1 롱 구간 / -1 숏 구간."""
    a = atr(c, n)
    line: Series = [None] * len(c)
    trend: Series = [None] * len(c)
    prev, d = None, 1
    for i, b in enumerate(c):
        if a[i] is None:
            continue
        lo_, hi_ = b["close"] - mult * a[i], b["close"] + mult * a[i]
        if prev is None:
            prev = lo_
        elif d == 1:
            if b["close"] < prev:
                d, prev = -1, hi_
            else:
                prev = max(prev, lo_)
        elif b["close"] > prev:
            d, prev = 1, lo_
        else:
            prev = min(prev, hi_)
        line[i], trend[i] = prev, d
    return {"line": line, "trend": trend}


# ---------------------------------------------------------------------------
# 전략 DSL에서 쓰는 지표 레지스트리
# type -> (계산 함수, 출력 이름들, 기본 파라미터, 설명)
# 출력이 여러 개면 조건식에서 "<id>.<출력>" 으로 참조 (예: "macd.hist", "bb.upper")
# ---------------------------------------------------------------------------

def _p(params: dict, key: str, default):
    v = params.get(key)
    return default if v is None else v


REGISTRY: dict[str, dict] = {
    "sma": {"outputs": ["value"], "defaults": {"length": 20, "source": "close"},
            "desc": "단순이동평균", "tv": "MASimple@tv-basicstudies"},
    "ema": {"outputs": ["value"], "defaults": {"length": 20, "source": "close"},
            "desc": "지수이동평균", "tv": "MAExp@tv-basicstudies"},
    "rsi": {"outputs": ["value"], "defaults": {"length": 14, "source": "close"},
            "desc": "RSI", "tv": "RSI@tv-basicstudies"},
    "macd": {"outputs": ["line", "signal", "hist"], "defaults": {"fast": 12, "slow": 26, "signal": 9, "source": "close"},
             "desc": "MACD", "tv": "MACD@tv-basicstudies"},
    "bb": {"outputs": ["upper", "middle", "lower", "width"], "defaults": {"length": 20, "mult": 2.0, "source": "close"},
           "desc": "볼린저밴드", "tv": "BB@tv-basicstudies"},
    "atr": {"outputs": ["value"], "defaults": {"length": 14}, "desc": "ATR", "tv": "ATR@tv-basicstudies"},
    "stoch": {"outputs": ["k", "d"], "defaults": {"length": 14, "k_smooth": 3, "d_smooth": 3},
              "desc": "스토캐스틱", "tv": "Stochastic@tv-basicstudies"},
    "supertrend": {"outputs": ["line", "trend"], "defaults": {"length": 10, "mult": 3.0},
                   "desc": "슈퍼트렌드 (trend: +1 상승, -1 하락)", "tv": None},
    "adx": {"outputs": ["adx", "plus_di", "minus_di"], "defaults": {"length": 14},
            "desc": "ADX/DMI", "tv": "DM@tv-basicstudies"},
    "cci": {"outputs": ["value"], "defaults": {"length": 20}, "desc": "CCI", "tv": "CCI@tv-basicstudies"},
    "vwap": {"outputs": ["value"], "defaults": {}, "desc": "세션 VWAP (UTC 리셋)", "tv": "VWAP@tv-basicstudies"},
    "obv": {"outputs": ["value"], "defaults": {}, "desc": "OBV", "tv": "OBV@tv-basicstudies"},
    "highest": {"outputs": ["value"], "defaults": {"length": 20, "source": "high"},
                "desc": "N봉 최고값 (돈치안 상단)", "tv": None},
    "lowest": {"outputs": ["value"], "defaults": {"length": 20, "source": "low"},
               "desc": "N봉 최저값 (돈치안 하단)", "tv": None},
    "volume_sma": {"outputs": ["value"], "defaults": {"length": 20}, "desc": "거래량 이동평균", "tv": None},
    "wma": {"outputs": ["value"], "defaults": {"length": 20, "source": "close"}, "desc": "가중이동평균", "tv": None},
    "hma": {"outputs": ["value"], "defaults": {"length": 55, "source": "close"}, "desc": "헐 이동평균", "tv": None},
    "vwma": {"outputs": ["value"], "defaults": {"length": 20, "source": "close"}, "desc": "거래량 가중 이동평균", "tv": None},
    "mfi": {"outputs": ["value"], "defaults": {"length": 14}, "desc": "MFI (자금 흐름)", "tv": None},
    "willr": {"outputs": ["value"], "defaults": {"length": 14}, "desc": "윌리엄스 %R (-100~0)", "tv": None},
    "roc": {"outputs": ["value"], "defaults": {"length": 9, "source": "close"}, "desc": "ROC 변화율 %", "tv": None},
    "psar": {"outputs": ["value", "trend"], "defaults": {}, "desc": "파라볼릭 SAR (trend: +1 상승, -1 하락)", "tv": None},
    "donchian": {"outputs": ["upper", "middle", "lower"], "defaults": {"length": 20}, "desc": "돈치안 채널", "tv": None},
    "keltner": {"outputs": ["upper", "middle", "lower"], "defaults": {"length": 20, "mult": 2.0}, "desc": "켈트너 채널", "tv": None},
    "stochrsi": {"outputs": ["k", "d"], "defaults": {"length": 14, "k_smooth": 3, "d_smooth": 3, "source": "close"}, "desc": "스토캐스틱 RSI", "tv": None},
    "ichimoku": {"outputs": ["tenkan", "kijun", "span_a", "span_b"], "defaults": {"fast": 9, "slow": 26, "length": 52},
                 "desc": "일목균형표 (span_a/b = 지금 봉 위치의 구름)", "tv": None},
    "cmf": {"outputs": ["value"], "defaults": {"length": 20}, "desc": "차이킨 자금 흐름", "tv": None},
    "aroon": {"outputs": ["up", "down"], "defaults": {"length": 25}, "desc": "아룬 (0~100)", "tv": None},
    "atr_stop": {"outputs": ["line", "trend"], "defaults": {"length": 14, "mult": 3.0}, "desc": "ATR 추적 손절선 (UT Bot 계열, trend ±1)", "tv": None},
}


def compute(c: list[dict], type_: str, params: dict | None = None) -> dict[str, Series]:
    """지표 계산. 항상 {출력이름: 시리즈} 형태로 반환."""
    if type_ not in REGISTRY:
        raise ValueError(f"지원하지 않는 지표: {type_}")
    p = {**REGISTRY[type_]["defaults"], **{k: v for k, v in (params or {}).items() if v is not None}}
    src = _src(c, p.get("source", "close")) if "source" in p else None
    n = int(_p(p, "length", 14))
    if type_ == "sma":
        return {"value": sma(src, n)}
    if type_ == "ema":
        return {"value": ema(src, n)}
    if type_ == "rsi":
        return {"value": rsi(src, n)}
    if type_ == "macd":
        return macd(src, int(p["fast"]), int(p["slow"]), int(p["signal"]))
    if type_ == "bb":
        return bbands(src, n, float(p["mult"]))
    if type_ == "atr":
        return {"value": atr(c, n)}
    if type_ == "stoch":
        return stoch(c, n, int(p["k_smooth"]), int(p["d_smooth"]))
    if type_ == "supertrend":
        st = supertrend(c, n, float(p["mult"]))
        return {"line": st["line"], "trend": st["trend"]}
    if type_ == "adx":
        return adx(c, n)
    if type_ == "cci":
        return {"value": cci(c, n)}
    if type_ == "vwap":
        return {"value": vwap(c)}
    if type_ == "obv":
        return {"value": obv(c)}
    if type_ == "highest":
        return {"value": highest(src, n)}
    if type_ == "lowest":
        return {"value": lowest(src, n)}
    if type_ == "volume_sma":
        return {"value": sma([b["volume"] for b in c], n)}
    if type_ == "wma":
        return {"value": wma(src, n)}
    if type_ == "hma":
        return {"value": hma(src, n)}
    if type_ == "vwma":
        return {"value": vwma(c, src, n)}
    if type_ == "mfi":
        return {"value": mfi(c, n)}
    if type_ == "willr":
        return {"value": willr(c, n)}
    if type_ == "roc":
        return {"value": roc(src, n)}
    if type_ == "psar":
        return psar(c)
    if type_ == "donchian":
        return donchian(c, n)
    if type_ == "keltner":
        return keltner(c, n, float(p["mult"]))
    if type_ == "stochrsi":
        return stochrsi(src, n, int(p["k_smooth"]), int(p["d_smooth"]))
    if type_ == "ichimoku":
        return ichimoku(c, int(p["fast"]), int(p["slow"]), n)
    if type_ == "cmf":
        return {"value": cmf(c, n)}
    if type_ == "aroon":
        return aroon(c, n)
    if type_ == "atr_stop":
        return atr_stop(c, n, float(p["mult"]))
    raise AssertionError(type_)
