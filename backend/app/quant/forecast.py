"""과거에 지금과 비슷했던 차트를 찾아 그 뒤 흐름으로 예상 시나리오를 만들고, 다음 봉을 예측한다.

- 패턴 유사도: 최근 window 봉의 (로그)가격 모양을 z-정규화해 과거 모든 구간과 상관계수로 비교한다.
  변동성이 너무 다른 구간은 점수를 깎고, 서로 겹치는 구간은 하나만 쓴다.
  고른 구간들의 '그 다음 horizon 봉' 수익률을 지금 가격에 (변동성 비율로 보정해) 이어 붙여 분포(10~90%)를 낸다.
- 다음 봉 예측: 최근 수익률·RSI·이평 거리·MACD·거래량·캔들 모양 등 12개 특징이 비슷했던 과거 봉(k-최근접)의
  바로 다음 봉 결과로 상승 확률·예상 범위를 낸다. 최근 150봉에 대해 '그 시점까지의 데이터만으로' 예측해 본
  적중률을 함께 보여줘 예측력이 실제로 있는지(항상 많이 나온 쪽을 찍는 것보다 나은지) 확인할 수 있게 한다.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from .. import indicators as ind
from ..data import market
from ..data.synthetic import INTERVAL_SECONDS

_cache: dict[tuple, tuple[float, dict]] = {}


def _q(xs: list[float], p: float) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    k = (len(s) - 1) * p
    f = math.floor(k)
    return s[f] + (s[min(f + 1, len(s) - 1)] - s[f]) * (k - f)


def _znorm(x: list[float]) -> list[float] | None:
    m = sum(x) / len(x)
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / len(x))
    return None if sd <= 1e-12 else [(v - m) / sd for v in x]


def future_times(last: int, interval: str, n: int) -> list[int]:
    if interval in ("1M", "1y"):
        d = datetime.fromtimestamp(last, timezone.utc)
        out, y, m = [], d.year, d.month
        for _ in range(n):
            if interval == "1M":
                m += 1
                if m > 12:
                    y, m = y + 1, 1
            else:
                y += 1
            out.append(int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp()))
        return out
    step = INTERVAL_SECONDS.get(interval, 3600)
    return [last + step * (h + 1) for h in range(n)]


def _vol(c: list[dict], a: int, b: int) -> float:
    """구간 [a, b] 의 평균 봉 변동폭(고저/종가)."""
    xs = [(c[i]["high"] - c[i]["low"]) / c[i]["close"] for i in range(a, b + 1) if c[i]["close"]]
    return sum(xs) / len(xs) if xs else 0.0


def analogs(c: list[dict], window: int = 48, horizon: int = 24, k: int = 20) -> dict:
    n = len(c)
    if n < window + horizon + 50:
        raise ValueError(f"데이터가 부족합니다 (필요 {window + horizon + 50}봉, 현재 {n}봉)")
    logp = [math.log(b["close"]) for b in c]
    cur = _znorm(logp[n - window:])
    if cur is None:
        raise ValueError("최근 가격 변동이 없어 패턴을 비교할 수 없습니다")
    cur_vol = _vol(c, n - window, n - 1) or 1e-9
    cands = []
    for j in range(window - 1, n - 1 - horizon):           # j = 과거 구간의 마지막 봉. 그 뒤 horizon 봉이 모두 있어야 함
        if j > n - 1 - window:                               # 지금 구간과 겹치면 제외
            break
        z = _znorm(logp[j - window + 1:j + 1])
        if z is None:
            continue
        corr = sum(p * q for p, q in zip(cur, z)) / window
        vr = (_vol(c, j - window + 1, j) or 1e-9) / cur_vol
        score = corr - 0.15 * abs(math.log(vr))
        cands.append((score, corr, j, vr))
    cands.sort(reverse=True)
    picked: list[tuple] = []
    for cand in cands:
        if all(abs(cand[2] - p[2]) >= window // 2 for p in picked):
            picked.append(cand)
            if len(picked) >= k:
                break
    if not picked:
        raise ValueError("비슷한 과거 구간을 찾지 못했습니다")

    last = c[-1]["close"]
    paths, matches = [], []
    for score, corr, j, vr in picked:
        scale = min(2.0, max(0.5, 1 / vr))                    # 과거 구간 변동성 → 지금 변동성으로 보정
        base = c[j]["close"]
        rets = [(c[j + h]["close"] / base - 1) * scale for h in range(1, horizon + 1)]
        paths.append(rets)
        seg = c[j - window + 1:j + horizon + 1]
        matches.append({"start": c[j - window + 1]["time"], "end": c[j]["time"], "corr": round(corr, 3),
                        "ret_pct": round(rets[-1] * 100, 2),
                        "max_up_pct": round(max(rets) * 100, 2), "max_down_pct": round(min(rets) * 100, 2),
                        # 미니 차트용: 구간 끝 = 100 으로 맞춘 종가
                        "shape": [round(b["close"] / base * 100, 3) for b in seg]})
    finals = [p[-1] for p in paths]
    band = {q: [round(last * (1 + _q([p[h] for p in paths], v)), 10) for h in range(horizon)]
            for q, v in (("p10", .1), ("p25", .25), ("p50", .5), ("p75", .75), ("p90", .9))}
    ups = sum(1 for f in finals if f > 0)
    avg_corr = sum(m["corr"] for m in matches) / len(matches)
    prob_up = round(100 * ups / len(finals))
    at = lambda h: round(100 * sum(1 for p in paths if p[h - 1] > 0) / len(paths))   # noqa: E731
    reliability = "높음" if avg_corr >= 0.85 and len(paths) >= 15 else "보통" if avg_corr >= 0.7 else "낮음"
    med = _q(finals, .5) * 100
    return {
        "window": window, "horizon": horizon, "n": len(paths), "candidates": len(cands),
        "avg_corr": round(avg_corr, 3), "reliability": reliability,
        "prob_up": prob_up, "prob_up_by_h": {str(h): at(h) for h in sorted({1, max(1, horizon // 4), max(1, horizon // 2), horizon})},
        "median_ret_pct": round(med, 2), "mean_ret_pct": round(sum(finals) / len(finals) * 100, 2),
        "p10_ret_pct": round(_q(finals, .1) * 100, 2), "p90_ret_pct": round(_q(finals, .9) * 100, 2),
        "times": future_times(c[-1]["time"], "1h", 0),   # 아래 forecast() 에서 채움
        "bands": band, "matches": matches,
        "summary": (f"지금과 비슷했던 과거 {len(paths)}개 구간(평균 유사도 {avg_corr:.2f}) 중 {ups}개({prob_up}%)가 "
                    f"{horizon}봉 뒤 올랐습니다. 중간값 {med:+.2f}%, 범위(10~90%) "
                    f"{_q(finals, .1) * 100:+.2f}% ~ {_q(finals, .9) * 100:+.2f}%."),
    }


# ---------------------------------------------------------------- 다음 봉 (k-최근접)
FEATURES = ["1봉 수익률", "3봉 수익률", "10봉 수익률", "RSI", "EMA20 거리", "MACD 히스토그램", "20봉 범위 위치",
            "거래량 배수", "캔들 몸통", "윗꼬리", "아랫꼬리", "시장가 매수 비율",
            "현재 세션 POC 거리", "직전 세션 POC 거리", "직전 세션 가치영역 위치", "10봉 누적 델타"]


def _session_key(t: int, step: int):
    """봉 간격에 맞는 세션: 1일 미만 → 하루(UTC), 1일~3일 → 주(월요일 시작), 그 이상 → 달."""
    if step < 86400:
        return t // 86400
    if step < 604800:
        return (t // 86400 + 3) // 7
    d = datetime.fromtimestamp(t, timezone.utc)
    return (d.year, d.month)


def _finalize(bins: dict[int, float], tick: float, va: float = 0.7) -> dict | None:
    if not bins:
        return None
    ks = sorted(bins)
    poc = max(ks, key=lambda k: bins[k])
    tot = sum(bins.values())
    lo = hi = ks.index(poc)
    acc = bins[poc]
    while acc < tot * va and (lo > 0 or hi < len(ks) - 1):
        up = bins[ks[hi + 1]] if hi < len(ks) - 1 else -1
        dn = bins[ks[lo - 1]] if lo > 0 else -1
        if up >= dn:
            hi += 1
            acc += bins[ks[hi]]
        else:
            lo -= 1
            acc += bins[ks[lo]]
    return {"poc": (poc + 0.5) * tick, "vah": (ks[hi] + 1) * tick, "val": ks[lo] * tick}


def session_profiles(c: list[dict], atr: list) -> list[tuple[float | None, dict | None]]:
    """봉마다 (현재 세션의 지금까지 POC, 직전 세션 {poc, vah, val})."""
    step = c[1]["time"] - c[0]["time"] if len(c) > 1 else 3600
    a = sorted(x for x in atr if x)
    tick = (a[len(a) // 2] / 3) if a else c[-1]["close"] * 0.001
    out, bins, key, prev = [], {}, None, None
    for b in c:
        k = _session_key(b["time"], step)
        if k != key:
            if bins:
                prev = _finalize(bins, tick)
            bins, key = {}, k
        lo, hi = int(math.floor(b["low"] / tick)), int(math.floor(b["high"] / tick))
        share = b["volume"] / (hi - lo + 1)
        for lv in range(lo, hi + 1):
            bins[lv] = bins.get(lv, 0.0) + share
        poc = max(bins, key=bins.get)
        out.append(((poc + 0.5) * tick, prev))
    return out


def _features(c: list[dict]) -> list[list[float] | None]:
    cl = [b["close"] for b in c]
    atr = ind.atr(c, 14)
    rsi = ind.rsi(cl, 14)
    e20 = ind.ema(cl, 20)
    mh = ind.macd(cl)["hist"]
    vs = ind.sma([b["volume"] for b in c], 20)
    hh = ind.highest([b["high"] for b in c], 20)
    ll = ind.lowest([b["low"] for b in c], 20)
    prof = session_profiles(c, atr)
    dl = [(2 * b["taker_buy"] - b["volume"]) if b.get("taker_buy") is not None else 0.0 for b in c]
    clip = lambda v: max(-5.0, min(5.0, v))   # noqa: E731 — 극단값 하나가 거리 계산을 지배하지 않게
    out: list[list[float] | None] = []
    for i, b in enumerate(c):
        a = atr[i]
        if i < 30 or a is None or not a or rsi[i] is None or e20[i] is None or mh[i] is None or not vs[i] or hh[i] is None:
            out.append(None)
            continue
        ap = a / b["close"]
        rng = b["high"] - b["low"] or 1e-12
        rg = (hh[i] - ll[i]) or 1e-12
        tb = b.get("taker_buy")
        out.append([
            (cl[i] / cl[i - 1] - 1) / ap, (cl[i] / cl[i - 3] - 1) / ap, (cl[i] / cl[i - 10] - 1) / ap,
            (rsi[i] - 50) / 50, (cl[i] - e20[i]) / a, mh[i] / a, (cl[i] - ll[i]) / rg - 0.5,
            math.log(max(b["volume"], 1e-12) / vs[i]), (b["close"] - b["open"]) / rng,
            (b["high"] - max(b["open"], b["close"])) / rng, (min(b["open"], b["close"]) - b["low"]) / rng,
            (tb / b["volume"] - 0.5) if tb is not None and b["volume"] else 0.0,
            clip((cl[i] - prof[i][0]) / a), *_prev_feats(cl[i], prof[i][1], a, clip),
            sum(dl[i - 9:i + 1]) / (sum(x["volume"] for x in c[i - 9:i + 1]) or 1),
        ])
    return out


def _prev_feats(px: float, prev: dict | None, a: float, clip) -> list[float]:
    if not prev:
        return [0.0, 0.0]
    pos = (px - prev["vah"]) / a if px > prev["vah"] else (px - prev["val"]) / a if px < prev["val"] else 0.0
    return [clip((px - prev["poc"]) / a), clip(pos)]


def evidence(c: list[dict], f: list[float]) -> list[str]:
    """지금 봉의 특징을 말로 (예측 근거)."""
    out = []
    if f[3] >= 0.4:
        out.append(f"RSI {50 + f[3] * 50:.0f} 과매수권")
    elif f[3] <= -0.4:
        out.append(f"RSI {50 + f[3] * 50:.0f} 과매도권")
    if abs(f[12]) >= 0.5:
        out.append(f"현재 세션 POC(가장 많이 거래된 가격)보다 {abs(f[12]):.1f} ATR {'위' if f[12] > 0 else '아래'} — "
                   f"{'위쪽 가격이 받아들여지는 중' if f[12] > 0 else '아래쪽 가격이 받아들여지는 중'}")
    else:
        out.append("현재 세션 POC 근처 — 균형 가격대 (방향 결정 전)")
    if f[14] > 0:
        out.append(f"직전 세션 가치영역(VAH) 위 {f[14]:.1f} ATR — 위로 벗어남, 유지되면 추세 지속")
    elif f[14] < 0:
        out.append(f"직전 세션 가치영역(VAL) 아래 {-f[14]:.1f} ATR — 아래로 벗어남, 유지되면 약세 지속")
    else:
        out.append("직전 세션 가치영역 안 — 영역 끝(VAH·VAL)에서 되돌림이 나오기 쉬움")
    if 0 < abs(f[13]) <= 1.5:
        out.append(f"직전 세션 POC 까지 {abs(f[13]):.1f} ATR — 가격이 끌려가는 '자석' 역할을 자주 함")
    if abs(f[15]) >= 0.1:
        out.append(f"최근 10봉 누적 델타 {'매수' if f[15] > 0 else '매도'} 우위 ({f[15] * 100:+.0f}%)")
    if f[7] >= 1.0:
        out.append(f"이번 봉 거래량이 평소의 {math.exp(f[7]):.1f}배")
    return out


def _standardize(fs: list[list[float] | None], upto: int) -> list[list[float] | None]:
    rows = [f for f in fs[:upto] if f]
    d = len(rows[0])
    mu = [sum(r[k] for r in rows) / len(rows) for k in range(d)]
    sd = [math.sqrt(sum((r[k] - mu[k]) ** 2 for r in rows) / len(rows)) or 1.0 for k in range(d)]
    return [None if f is None else [(f[k] - mu[k]) / sd[k] for k in range(d)] for f in fs]


def _knn(fs, c, i: int, lo: int, k: int) -> dict:
    """i 번째 봉 시점에서, j+1 <= i 인 과거 봉들(=결과를 이미 아는 봉)만으로 다음 봉을 예측."""
    x = fs[i]
    ds = []
    for j in range(lo, i):
        f = fs[j]
        if f is None:
            continue
        ds.append((sum((p - q) ** 2 for p, q in zip(x, f)), j))
    ds.sort()
    nb = [j for _, j in ds[:k]]
    rets = [c[j + 1]["close"] / c[j]["close"] - 1 for j in nb]
    his = [c[j + 1]["high"] / c[j]["close"] - 1 for j in nb]
    los = [c[j + 1]["low"] / c[j]["close"] - 1 for j in nb]
    ups = sum(1 for r in rets if r > 0)
    return {"p_up": (ups + 1) / (len(rets) + 2), "mean": sum(rets) / len(rets), "med": _q(rets, .5),
            "hi": _q(his, .5), "lo": _q(los, .5), "hi75": _q(his, .75), "lo25": _q(los, .25), "n": len(rets)}


def next_bar(c: list[dict], k: int = 40, evaluate: int = 150, history: int = 1200) -> dict:
    n = len(c)
    if n < 300:
        raise ValueError("다음 봉 예측에는 최소 300봉이 필요합니다")
    raw = _features(c)
    first_eval = n - 1 - evaluate
    fs = _standardize(raw, first_eval)                     # 평가 구간 이전 데이터로만 정규화
    # 1) 과거 evaluate 봉에 대해 '그때까지의 데이터만으로' 예측해 적중률 측정 (워크포워드)
    hits = conf_hits = conf_n = ups = 0
    tot = 0
    for i in range(first_eval, n - 1):
        if fs[i] is None:
            continue
        p = _knn(fs, c, i, max(0, i - history), k)
        actual = c[i + 1]["close"] - c[i]["close"]
        if actual == 0:
            continue
        tot += 1
        ups += actual > 0
        hit = (p["p_up"] > 0.5) == (actual > 0)
        hits += hit
        if abs(p["p_up"] - 0.5) >= 0.1:
            conf_n += 1
            conf_hits += hit
    base = max(ups, tot - ups) / tot * 100 if tot else 50.0
    acc = hits / tot * 100 if tot else None
    # 2) 지금(마지막 봉 기준) 예측
    i = n - 1
    if fs[i] is None:
        raise ValueError("특징을 계산할 수 없습니다")
    p = _knn(fs, c, i, max(0, i - history), k)
    last = c[-1]["close"]
    edge = (acc or 0) - base
    prof = session_profiles(c[-400:], ind.atr(c[-400:], 14))[-1]
    return {
        "p_up": round(p["p_up"] * 100), "exp_ret_pct": round(p["mean"] * 100, 3), "median_ret_pct": round(p["med"] * 100, 3),
        "neighbors": p["n"],
        "candle": {"open": last, "close": last * (1 + p["med"]), "high": last * (1 + max(p["hi"], p["med"], 0)),
                   "low": last * (1 + min(p["lo"], p["med"], 0))},
        "range": {"high": last * (1 + p["hi75"]), "low": last * (1 + p["lo25"])},
        "backtest": {"evaluated": tot, "accuracy_pct": None if acc is None else round(acc, 1),
                     "baseline_pct": round(base, 1), "confident_n": conf_n,
                     "confident_accuracy_pct": round(conf_hits / conf_n * 100, 1) if conf_n else None},
        "verdict": ("최근 적중률이 '많이 나온 쪽 찍기'보다 확실히 높습니다" if edge >= 5 else
                    "최근 적중률이 찍기보다 조금 높습니다 — 참고만 하세요" if edge >= 1.5 else
                    "최근 적중률이 찍기 수준입니다 — 예측력이 없다고 보는 게 맞습니다"),
        "features": FEATURES, "evidence": evidence(c, raw[i]),
        "session": {"poc": prof[0], **({f"prev_{k}": v for k, v in prof[1].items()} if prof[1] else {})},
    }


def forecast(symbol: str, interval: str, window: int = 48, horizon: int = 24, bars: int = 3000) -> dict:
    key = (symbol, interval, window, horizon)
    c, src = market.candles(symbol, interval, bars)
    hit = _cache.get(key)
    if hit and hit[1].get("bar_time") == c[-1]["time"] and time.time() - hit[0] < 300:
        return hit[1]
    out = {"symbol": symbol, "interval": interval, "data_source": src, "bar_time": c[-1]["time"], "bars": len(c)}
    try:
        a = analogs(c, window, horizon)
        a["times"] = future_times(c[-1]["time"], interval, horizon)
        out["analog"] = a
    except ValueError as e:
        out["analog"] = None
        out["analog_error"] = str(e)
    try:
        nb = next_bar(c)
        nb["time"] = future_times(c[-1]["time"], interval, 1)[0]
        out["next_bar"] = nb
    except ValueError as e:
        out["next_bar"] = None
        out["next_bar_error"] = str(e)
    _cache[key] = (time.time(), out)
    if len(_cache) > 200:
        _cache.pop(next(iter(_cache)))
    return out
