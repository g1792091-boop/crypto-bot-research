"""리스크 도구 — 상관관계·베타·VaR, 포트폴리오 위험, 몬테카를로, 파라미터 민감도(스윕)."""
from __future__ import annotations

import copy
import math
import random
from concurrent.futures import ThreadPoolExecutor

from ..data.synthetic import INTERVAL_SECONDS
from . import universe


def _q(xs: list[float], p: float) -> float:
    s = sorted(xs)
    k = (len(s) - 1) * p
    f = math.floor(k)
    return s[f] + (s[min(f + 1, len(s) - 1)] - s[f]) * (k - f)


def _rets(x: list[float | None]) -> list[float | None]:
    return [None] + [None if x[i] is None or x[i - 1] is None or not x[i - 1] else x[i] / x[i - 1] - 1 for i in range(1, len(x))]


def _pair(a: list[float | None], b: list[float | None]) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for p, q in zip(a, b):
        if p is not None and q is not None:
            xs.append(p)
            ys.append(q)
    return xs, ys


def _corr(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 10:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if not va or not vb:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def matrix(symbols: list[str], interval: str = "1d", bars: int = 120) -> dict:
    """수익률 상관 행렬 + 코인별 연 변동성·BTC 베타·VaR/CVaR(95%, 한 봉)·최대낙폭."""
    times, closes, src = universe.load(symbols, interval, bars)
    syms = [s for s in dict.fromkeys(symbols) if s in closes]
    R = {s: _rets(closes[s]) for s in closes}
    per_year = 365 * 86400 / INTERVAL_SECONDS.get(interval, 86400)
    corr = [[None if i != j else 1.0 for j in range(len(syms))] for i in range(len(syms))]
    for i, a in enumerate(syms):
        for j in range(i + 1, len(syms)):
            v = _corr(*_pair(R[a], R[syms[j]]))
            corr[i][j] = corr[j][i] = None if v is None else round(v, 3)
    stats = []
    btc = R["BTCUSDT"]
    for s in syms:
        r = [x for x in R[s] if x is not None]
        if len(r) < 10:
            continue
        mu = sum(r) / len(r)
        sd = math.sqrt(sum((x - mu) ** 2 for x in r) / len(r))
        xs, ys = _pair(R[s], btc)
        vb = sum((y - sum(ys) / len(ys)) ** 2 for y in ys) if ys else 0
        beta = (sum((x - sum(xs) / len(xs)) * (y - sum(ys) / len(ys)) for x, y in zip(xs, ys)) / vb) if vb else None
        var = -_q(r, 0.05)
        tail = [x for x in r if x <= -var]
        px = [v for v in closes[s] if v is not None]
        peak, mdd = px[0], 0.0
        for v in px:
            peak = max(peak, v)
            mdd = max(mdd, 1 - v / peak)
        stats.append({"symbol": s, "vol_ann_pct": round(sd * math.sqrt(per_year) * 100, 1),
                      "beta_btc": None if beta is None else round(beta, 2),
                      "var95_pct": round(var * 100, 2), "cvar95_pct": round(-sum(tail) / len(tail) * 100, 2) if tail else None,
                      "ret_pct": round((px[-1] / px[0] - 1) * 100, 2), "max_dd_pct": round(mdd * 100, 1),
                      "sharpe": round(mu / sd * math.sqrt(per_year), 2) if sd else None})
    avg = [abs(corr[i][j]) for i in range(len(syms)) for j in range(len(syms)) if i < j and corr[i][j] is not None]
    return {"interval": interval, "bars": len(times), "data_source": src, "symbols": syms, "corr": corr, "stats": stats,
            "avg_abs_corr": round(sum(avg) / len(avg), 3) if avg else None,
            "note": "상관이 0.8 이상인 코인끼리는 사실상 같은 포지션입니다 — 여러 개를 같은 방향으로 들면 위험이 겹칩니다."}


def portfolio(positions: list[dict], interval: str = "1d", bars: int = 250, shock_pct: float = -10.0) -> dict:
    """positions: [{symbol, side: long/short, notional}] → 과거 수익률로 본 한 봉 손익 분포(역사적 시뮬레이션)."""
    if not positions:
        return {"positions": 0}
    syms = list(dict.fromkeys(p["symbol"] for p in positions))
    times, closes, src = universe.load(syms, interval, bars)
    R = {s: _rets(closes[s]) for s in closes}
    pnl = []
    for t in range(1, len(times)):
        v, ok = 0.0, True
        for p in positions:
            r = R.get(p["symbol"], [None] * len(times))[t]
            if r is None:
                ok = False
                break
            v += (1 if p["side"] == "long" else -1) * p["notional"] * r
        if ok:
            pnl.append(v)
    if len(pnl) < 20:
        raise ValueError("과거 데이터가 부족해 포트폴리오 위험을 계산할 수 없습니다")
    var95, var99 = -_q(pnl, .05), -_q(pnl, .01)
    tail = [x for x in pnl if x <= -var95]
    # 베타 스트레스: BTC 가 shock_pct 움직일 때
    btc = R["BTCUSDT"]
    stress = 0.0
    for p in positions:
        xs, ys = _pair(R[p["symbol"]], btc)
        my = sum(ys) / len(ys)
        vb = sum((y - my) ** 2 for y in ys)
        beta = sum((x - sum(xs) / len(xs)) * (y - my) for x, y in zip(xs, ys)) / vb if vb else 1.0
        stress += (1 if p["side"] == "long" else -1) * p["notional"] * beta * shock_pct / 100
    gross = sum(abs(p["notional"]) for p in positions)
    net = sum((1 if p["side"] == "long" else -1) * p["notional"] for p in positions)
    return {"interval": interval, "data_source": src, "positions": len(positions), "gross": round(gross, 2), "net": round(net, 2),
            "var95": round(var95, 2), "var99": round(var99, 2), "cvar95": round(-sum(tail) / len(tail), 2) if tail else None,
            "worst": round(min(pnl), 2), "best": round(max(pnl), 2), "samples": len(pnl),
            "stress_shock_pct": shock_pct, "stress_pnl": round(stress, 2)}


def montecarlo(pnls: list[float], initial_equity: float = 10_000, sims: int = 2000, seed: int | None = 7) -> dict:
    """백테스트 거래 손익 순서를 무작위로 섞고 복원추출해 '운이 달랐다면' 나올 수 있는 결과 분포."""
    if len(pnls) < 5:
        raise ValueError("거래가 5건 이상 있어야 몬테카를로를 돌릴 수 있습니다")
    eq, rets = initial_equity, []
    for p in pnls:                     # 거래마다 '그때 자본 대비' 수익률로 바꿔 복리로 다시 쌓는다
        rets.append(p / eq if eq > 0 else 0)
        eq += p
    rng = random.Random(seed)
    finals, dds = [], []
    n = len(rets)
    for _ in range(sims):
        e, peak, mdd = 1.0, 1.0, 0.0
        for _k in range(n):
            e *= 1 + rets[rng.randrange(n)]
            if e <= 0:
                e, mdd = 0.0, 1.0
                break
            peak = max(peak, e)
            mdd = max(mdd, 1 - e / peak)
        finals.append((e - 1) * 100)
        dds.append(mdd * 100)
    pct = lambda xs: {k: round(_q(xs, v), 2) for k, v in (("p5", .05), ("p25", .25), ("p50", .5), ("p75", .75), ("p95", .95))}  # noqa: E731
    hist_lo, hist_hi = _q(finals, .01), _q(finals, .99)
    bins = 24
    w = (hist_hi - hist_lo) / bins or 1
    hist = [0] * bins
    for f in finals:
        hist[min(bins - 1, max(0, int((f - hist_lo) / w)))] += 1
    return {"sims": sims, "trades": n, "return_pct": pct(finals), "max_dd_pct": pct(dds),
            "prob_loss_pct": round(100 * sum(1 for f in finals if f < 0) / sims, 1),
            "prob_dd30_pct": round(100 * sum(1 for d in dds if d >= 30) / sims, 1),
            "prob_dd50_pct": round(100 * sum(1 for d in dds if d >= 50) / sims, 1),
            "histogram": {"from": round(hist_lo, 2), "step": round(w, 3), "counts": hist}}


# ---------------------------------------------------------------- 파라미터 스윕
def params_of(spec: dict) -> list[dict]:
    out = []
    for i, it in enumerate(spec.get("indicators", [])):
        for k, v in it.items():
            if k not in ("id", "type", "source") and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append({"path": f"indicators.{i}.{k}", "label": f"{it['id']} {k}", "value": v})
    for k in ("stop_loss_pct", "take_profit_pct", "leverage", "trailing_stop_pct", "atr_stop_mult", "atr_tp_mult"):
        v = spec.get("risk", {}).get(k)
        if isinstance(v, (int, float)):
            out.append({"path": f"risk.{k}", "label": {"stop_loss_pct": "손절 %", "take_profit_pct": "익절 %", "leverage": "레버리지",
                        "trailing_stop_pct": "추적 손절 %", "atr_stop_mult": "ATR 손절 배수", "atr_tp_mult": "ATR 익절 배수"}[k], "value": v})
    return out


def _set(d: dict, path: str, v):
    cur = d
    parts = path.split(".")
    for p in parts[:-1]:
        cur = cur[int(p)] if p.isdigit() else cur[p]
    last = parts[-1]
    old = cur.get(last)
    cur[last] = int(round(v)) if isinstance(old, int) and not isinstance(old, bool) and float(v).is_integer() else v


def sweep(spec: dict, p1: str, v1: list[float], p2: str | None, v2: list[float] | None, bars: int = 1500) -> dict:
    from .. import backtest
    from ..data import market
    from ..improve import TRAIN_SHARE, _evaluate
    from ..strategy import StrategySpec, validate
    v2 = v2 if p2 else [None]
    if len(v1) * len(v2) > 81:
        raise ValueError("조합이 너무 많습니다 (최대 81개)")
    base = StrategySpec(**spec)
    candles, src = market.candles(base.symbol, base.interval, bars)
    deriv = market.derivatives(base.symbol, base.interval, 500) if backtest.needs_derivatives(base) else None
    split = candles[int(len(candles) * TRAIN_SHARE)]["time"]

    def one(pair):
        a, b = pair
        d = copy.deepcopy(spec)
        try:
            _set(d, p1, a)
            if p2:
                _set(d, p2, b)
            s = StrategySpec(**d)
            if validate(s):
                return {"a": a, "b": b, "error": "; ".join(validate(s))}
            ev = _evaluate(s, candles, deriv, split)
            return {"a": a, "b": b, "train": ev["train"], "test": ev["test"],
                    "return_pct": ev["all"]["total_return_pct"], "max_dd_pct": ev["all"]["max_drawdown_pct"]}
        except Exception as e:
            return {"a": a, "b": b, "error": str(e)[:120]}
    with ThreadPoolExecutor(max_workers=4) as ex:
        cells = list(ex.map(one, [(a, b) for a in v1 for b in v2]))
    ok = [c for c in cells if "error" not in c]
    good_test = [c for c in ok if c["test"]["net_pnl"] > 0]
    return {"p1": p1, "p2": p2, "v1": v1, "v2": v2 if p2 else [], "cells": cells, "data_source": src,
            "robust_share_pct": round(100 * len(good_test) / len(ok)) if ok else None,
            "note": ("주변 값에서도 검증 구간 손익이 고르게 좋으면 튼튼한 전략, 한 칸만 튀면 과최적화일 가능성이 큽니다.")}
