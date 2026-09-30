"""기관(자산운용사)식 포트폴리오 도구.

- 최적 배분: 동일 비중 · 변동성 역가중 · 리스크 패리티(위험 기여 균등) · 최소 분산 · 최대 샤프.
  앞 70% 기간으로 비중을 정하고 뒤 30% 기간(안 본 데이터)에 그대로 적용해 성과를 따로 보여준다.
  공분산은 대각 행렬 쪽으로 30% 수축, 기대수익은 절반으로 줄여 추정 오차에 덜 휘둘리게 한다.
- 스트레스 테스트: 실제 위기 구간(코로나·중국 규제·루나·FTX·엔캐리)의 코인별 실제 등락을 지금 포지션에 적용.
  그때 상장 전인 코인은 BTC 베타 × BTC 등락으로 추정한다. 가상 충격(BTC −20% 등)도 함께.
- 팩터·유동성: BTC 베타 · 모멘텀 · 변동성 · 코인 그룹별 순노출, 24시간 거래대금 대비 비중, 청산에 걸리는 날 수,
  지금 호가로 한 번에 정리할 때의 슬리피지.
- 성과 분석(티어시트): 샤프 · 소르티노 · 칼마 · 최대 낙폭과 기간 · 승률 · 손익비 · 기대값, 월별 수익률,
  코인 · 방향 · 진입 시간대 · 요일별 손익 분해.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from .. import orderflow
from ..data import market
from ..data.synthetic import INTERVAL_SECONDS
from . import universe

KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------- 공통 수학
def _mean(x):
    return sum(x) / len(x) if x else 0.0


def _cov(R: list[list[float]]) -> list[list[float]]:
    n, T = len(R), len(R[0])
    m = [_mean(r) for r in R]
    return [[sum((R[i][t] - m[i]) * (R[j][t] - m[j]) for t in range(T)) / max(1, T - 1) for j in range(n)] for i in range(n)]


def _mv(A, w):
    return [sum(a * b for a, b in zip(row, w)) for row in A]


def _proj(v: list[float], cap: float) -> list[float]:
    """{w ≥ 0, w ≤ cap, Σw = 1} 로 투영 (τ 이분 탐색)."""
    lo, hi = min(v) - 1, max(v)
    for _ in range(80):
        tau = (lo + hi) / 2
        s = sum(min(cap, max(0.0, x - tau)) for x in v)
        if s > 1:
            lo = tau
        else:
            hi = tau
    w = [min(cap, max(0.0, x - hi)) for x in v]
    t = sum(w) or 1
    return [x / t for x in w]


def _series_stats(rets: list[float], per_year: float) -> dict:
    if not rets:
        return {}
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    mu, sd = _mean(rets), math.sqrt(sum((r - _mean(rets)) ** 2 for r in rets) / len(rets))
    return {"return_pct": round((eq - 1) * 100, 2), "ann_return_pct": round(((eq ** (per_year / len(rets))) - 1) * 100, 2) if eq > 0 else -100.0,
            "ann_vol_pct": round(sd * math.sqrt(per_year) * 100, 2), "sharpe": round(mu / sd * math.sqrt(per_year), 2) if sd else None,
            "max_dd_pct": round(mdd * 100, 2)}


# ---------------------------------------------------------------- 최적 배분
METHODS = {"equal": "동일 비중", "inv_vol": "변동성 역가중", "risk_parity": "리스크 패리티", "min_var": "최소 분산", "max_sharpe": "최대 샤프"}


def optimize(symbols: list[str], interval: str = "1d", bars: int = 365, max_weight: float = 0.4) -> dict:
    times, closes, src = universe.load(symbols, interval, bars)
    syms = [s for s in dict.fromkeys(symbols) if s in closes]
    rets = {s: [(closes[s][t] / closes[s][t - 1] - 1) if closes[s][t] and closes[s][t - 1] else None for t in range(1, len(times))] for s in syms}
    syms = [s for s in syms if sum(r is None for r in rets[s]) <= len(times) * 0.1]   # 기간 대부분 데이터가 있는 코인만
    if len(syms) < 2:
        raise ValueError("배분하려면 기간 전체 데이터가 있는 코인이 2개 이상 필요합니다")
    R = [[r or 0.0 for r in rets[s]] for s in syms]
    T = len(R[0])
    split = int(T * 0.7)
    tr, te = [r[:split] for r in R], [r[split:] for r in R]
    per_year = 365 * 86400 / INTERVAL_SECONDS.get(interval, 86400)
    n = len(syms)
    S = _cov(tr)
    S = [[S[i][j] * (0.7 if i != j else 1.0) for j in range(n)] for i in range(n)]      # 대각 쪽으로 수축
    mu = [_mean(r) * 0.5 for r in tr]                                                   # 기대수익 절반으로 (추정 오차)
    vol = [math.sqrt(S[i][i]) or 1e-9 for i in range(n)]
    cap = max(max_weight, 1 / n)

    def pvar(w):
        return sum(a * b for a, b in zip(w, _mv(S, w)))

    W: dict[str, list[float]] = {"equal": [1 / n] * n}
    iv = [1 / v for v in vol]
    W["inv_vol"] = _proj([x / sum(iv) for x in iv], cap)
    w = W["inv_vol"][:]
    for _ in range(300):                                    # 위험 기여 균등화
        Sw = _mv(S, w)
        rc = [w[i] * Sw[i] for i in range(n)]
        tgt = sum(rc) / n
        w = _proj([w[i] * math.sqrt(tgt / rc[i]) if rc[i] > 0 else w[i] for i in range(n)], cap)
    W["risk_parity"] = w
    w = [1 / n] * n
    lr = 0.5 / (max(S[i][i] for i in range(n)) or 1)
    for _ in range(800):
        g = _mv(S, w)
        w = _proj([w[i] - lr * 2 * g[i] for i in range(n)], cap)
    W["min_var"] = w
    w = W["inv_vol"][:]
    for _ in range(800):                                    # 샤프 = w·μ / √(wᵀΣw) 경사 상승
        Sw = _mv(S, w)
        v = math.sqrt(max(pvar(w), 1e-18))
        m = sum(a * b for a, b in zip(w, mu))
        g = [(mu[i] * v - m * Sw[i] / v) / (v * v) for i in range(n)]
        w = _proj([w[i] + 0.002 * g[i] / (max(abs(x) for x in g) or 1) for i in range(n)], cap)
    W["max_sharpe"] = w

    def perf(w, rs):
        port = [sum(w[i] * rs[i][t] for i in range(n)) for t in range(len(rs[0]))]
        return _series_stats(port, per_year)

    out = []
    for k, w in W.items():
        Sw = _mv(S, w)
        tot = pvar(w) or 1
        out.append({"method": k, "name": METHODS[k], "weights": {s: round(w[i], 4) for i, s in enumerate(syms)},
                    "risk_contrib": {s: round(w[i] * Sw[i] / tot, 4) for i, s in enumerate(syms)},
                    "train": perf(w, tr), "test": perf(w, te)})
    rng = random.Random(1)
    cloud = []
    for _ in range(1200):                                   # 무작위 포트폴리오 (효율적 투자선 배경)
        g = [rng.gammavariate(0.6, 1) for _ in range(n)]
        w = [x / sum(g) for x in g]
        cloud.append({"vol": round(math.sqrt(pvar(w) * per_year) * 100, 2), "ret": round(sum(a * b for a, b in zip(w, [_mean(r) for r in tr])) * per_year * 100, 2)})
    for o in out:
        w = [o["weights"][s] for s in syms]
        o["point"] = {"vol": round(math.sqrt(pvar(w) * per_year) * 100, 2), "ret": round(sum(a * b for a, b in zip(w, [_mean(r) for r in tr])) * per_year * 100, 2)}
    return {"interval": interval, "data_source": src, "symbols": syms, "train_bars": split, "test_bars": T - split,
            "train_from": times[1], "test_from": times[1 + split], "results": out, "cloud": cloud, "max_weight": cap,
            "note": "학습(앞 70%)에서 좋았던 배분이 검증(뒤 30%)에서도 좋은지 보세요. 최대 샤프는 과거 수익률에 민감해 검증에서 자주 무너집니다 — 리스크 패리티·최소 분산이 더 안정적인 경우가 많습니다."}


# ---------------------------------------------------------------- 스트레스 테스트
SCENARIOS = [
    ("covid", "2020.03 코로나 폭락", "2020-03-11", "2020-03-13"),
    ("china", "2021.05 중국 채굴 금지 급락", "2021-05-18", "2021-05-19"),
    ("luna", "2022.05 테라·루나 붕괴", "2022-05-06", "2022-05-12"),
    ("ftx", "2022.11 FTX 파산", "2022-11-06", "2022-11-09"),
    ("yen", "2024.08 엔 캐리 청산", "2024-08-02", "2024-08-05"),
]
HYPOTHETICAL = [
    ("btc20", "가상: BTC −20% (코인별 베타 반영)"),
    ("alt", "가상: BTC −10%, 알트 −30%"),
    ("corr1", "가상: 상관 1 — 전부 −15%"),
    ("squeeze", "가상: 숏 스퀴즈 — BTC +15%, 알트 +25%"),
]


def _ts(d: str) -> int:
    return int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp())


def _betas(symbols: list[str]) -> dict[str, float]:
    times, closes, _ = universe.load(symbols, "1d", 180)
    b = [(closes["BTCUSDT"][t] / closes["BTCUSDT"][t - 1] - 1) for t in range(1, len(times))]
    out = {}
    for s in symbols:
        x = closes.get(s)
        if not x:
            out[s] = 1.2
            continue
        pairs = [((x[t] / x[t - 1] - 1), b[t - 1]) for t in range(1, len(times)) if x[t] and x[t - 1]]
        if len(pairs) < 30:
            out[s] = 1.2
            continue
        mx, mb = _mean([p[0] for p in pairs]), _mean([p[1] for p in pairs])
        vb = sum((p[1] - mb) ** 2 for p in pairs)
        out[s] = sum((p[0] - mx) * (p[1] - mb) for p in pairs) / vb if vb else 1.0
    return out


def _window(symbol: str, start: str, end: str) -> tuple[float, float] | None:
    s, e = _ts(start), _ts(end)
    c, _ = market.candles_range(symbol, "1d", s - 86400, e)
    if len(c) < 2 or c[0]["time"] > s - 86400 + 3600:
        return None
    base = c[0]["close"]
    return c[-1]["close"] / base - 1, min(b["low"] for b in c[1:]) / base - 1


def stress(positions: list[dict]) -> dict:
    """positions: [{symbol, side, notional, leverage?}]"""
    if not positions:
        raise ValueError("포지션이 없습니다. 모의 주문을 넣거나 '최적 배분' 결과로 테스트하세요.")
    syms = list(dict.fromkeys(p["symbol"] for p in positions))
    beta = _betas(syms)
    gross = sum(abs(p["notional"]) for p in positions)
    rows = []
    for key, name, a, b in SCENARIOS:
        btc = _window("BTCUSDT", a, b)
        detail, pnl, worst, liq = [], 0.0, 0.0, []
        for p in positions:
            w = _window(p["symbol"], a, b)
            est = w is None
            if est:
                w = (beta[p["symbol"]] * btc[0], beta[p["symbol"]] * btc[1]) if btc else (0.0, 0.0)
            sg = 1 if p["side"] == "long" else -1
            pnl += sg * p["notional"] * w[0]
            adverse = w[1] if sg == 1 else -w[0] if w[0] > 0 else 0   # 롱은 구간 최저, 숏은 상승폭
            worst += sg * p["notional"] * (w[1] if sg == 1 else w[0])
            lev = p.get("leverage") or 1
            if adverse <= -(1 / lev - 0.005):
                liq.append(p["symbol"])
            detail.append({"symbol": p["symbol"], "ret_pct": round(w[0] * 100, 2), "low_pct": round(w[1] * 100, 2), "estimated": est})
        rows.append({"key": key, "name": name, "period": f"{a} ~ {b}", "pnl": round(pnl, 2), "pnl_pct_gross": round(pnl / gross * 100, 2) if gross else 0,
                     "worst_intraperiod": round(worst, 2), "btc_ret_pct": None if not btc else round(btc[0] * 100, 2),
                     "liquidation": liq, "detail": detail})
    for key, name in HYPOTHETICAL:
        pnl, detail = 0.0, []
        for p in positions:
            alt = p["symbol"] != "BTCUSDT"
            r = {"btc20": -0.20 * (beta[p["symbol"]] if alt else 1), "alt": -0.30 if alt else -0.10, "corr1": -0.15,
                 "squeeze": 0.25 if alt else 0.15}[key]
            pnl += (1 if p["side"] == "long" else -1) * p["notional"] * r
            detail.append({"symbol": p["symbol"], "ret_pct": round(r * 100, 2), "estimated": True})
        rows.append({"key": key, "name": name, "period": "가상 충격", "pnl": round(pnl, 2), "pnl_pct_gross": round(pnl / gross * 100, 2) if gross else 0,
                     "btc_ret_pct": None, "liquidation": [], "detail": detail})
    return {"positions": positions, "gross": round(gross, 2), "scenarios": rows, "betas": {k: round(v, 2) for k, v in beta.items()},
            "note": "위기 구간은 실제 일봉 종가 기준. 그때 상장 전이던 코인은 '추정'(최근 180일 BTC 베타 × BTC 등락)입니다."}


# ---------------------------------------------------------------- 팩터 · 유동성
def exposures(positions: list[dict]) -> dict:
    if not positions:
        raise ValueError("포지션이 없습니다.")
    syms = list(dict.fromkeys(p["symbol"] for p in positions))
    uni = list(dict.fromkeys(universe.DEFAULT_UNIVERSE + syms))
    times, closes, src = universe.load(uni, "1d", 120)
    n = len(times)

    def stat(s):
        x = closes.get(s)
        if not x or x[-1] is None or x[max(0, n - 31)] is None:
            return None
        r = [x[t] / x[t - 1] - 1 for t in range(n - 30, n) if x[t] and x[t - 1]]
        return {"mom": x[-1] / x[n - 31] - 1, "vol": math.sqrt(sum(v * v for v in r) / len(r)) * math.sqrt(365) if r else 0}
    st = {s: stat(s) for s in uni}
    ok = [v for v in st.values() if v]
    mm, sm = _mean([v["mom"] for v in ok]), math.sqrt(_mean([(v["mom"] - _mean([q["mom"] for q in ok])) ** 2 for v in ok])) or 1
    mv, sv = _mean([v["vol"] for v in ok]), math.sqrt(_mean([(v["vol"] - _mean([q["vol"] for q in ok])) ** 2 for v in ok])) or 1
    beta = _betas(syms)
    tick = {t["symbol"]: t for t in market.tickers(syms)[0]}
    rows, gross = [], sum(abs(p["notional"]) for p in positions)
    agg = {"beta_dollars": 0.0, "mom": 0.0, "vol": 0.0, "net": 0.0}
    tiers: dict[str, float] = {}
    for p in positions:
        s, sg, nt = p["symbol"], 1 if p["side"] == "long" else -1, p["notional"]
        z = st.get(s) or {"mom": mm, "vol": mv}
        adv = tick.get(s, {}).get("quote_volume") or 0
        try:
            book, _ = orderflow._raw_book(s)
            mid = (book["bids"][0][0] + book["asks"][0][0]) / 2
            sl = orderflow.slippage(book, mid, (nt,))[0]["sell" if sg == 1 else "buy"]
        except Exception:
            sl = None
        rows.append({"symbol": s, "side": p["side"], "notional": round(nt, 2), "who": p.get("who"), "beta": round(beta[s], 2),
                     "mom_z": round((z["mom"] - mm) / sm, 2), "vol_z": round((z["vol"] - mv) / sv, 2), "vol_ann_pct": round(z["vol"] * 100, 1),
                     "tier": universe.TIER_NAME[universe.tier(s)], "adv_usd": round(adv), "pct_adv": round(nt / adv * 100, 4) if adv else None,
                     "days_to_exit_10pct": round(nt / (adv * 0.1), 3) if adv else None,
                     "exit_slip_pct": None if not sl else round(sl["slip_pct"], 4)})
        agg["beta_dollars"] += sg * nt * beta[s]
        agg["mom"] += sg * nt * (z["mom"] - mm) / sm
        agg["vol"] += sg * nt * (z["vol"] - mv) / sv
        agg["net"] += sg * nt
        t = universe.TIER_NAME[universe.tier(s)]
        tiers[t] = tiers.get(t, 0) + sg * nt
    return {"data_source": src, "rows": rows, "gross": round(gross, 2), "net": round(agg["net"], 2),
            "beta_dollars": round(agg["beta_dollars"], 2), "mom_tilt": round(agg["mom"] / gross, 2) if gross else 0,
            "vol_tilt": round(agg["vol"] / gross, 2) if gross else 0, "tiers": {k: round(v, 2) for k, v in tiers.items()},
            "note": "BTC 베타 달러 = BTC 가 1% 움직일 때 포트폴리오가 움직이는 금액 × 100. 모멘텀·변동성 기울기는 +면 최근 강한(변동성 큰) 코인 쪽으로 쏠림."}


# ---------------------------------------------------------------- 성과 분석
def tearsheet(trades: list[dict], initial: float = 10_000, equity_curve: list[dict] | None = None) -> dict:
    trades = sorted([t for t in trades if t.get("exit_time")], key=lambda t: t["exit_time"])
    if not trades:
        raise ValueError("끝난 거래가 없습니다.")
    if equity_curve and len(equity_curve) > 2:
        pts = [(p["time"], p["value"]) for p in equity_curve]
    else:
        eq, pts = initial, [(trades[0]["entry_time"], initial)]
        for t in trades:
            eq += t["pnl"]
            pts.append((t["exit_time"], eq))
    # 하루 단위 자본 (UTC)
    daily: dict[int, float] = {}
    for t, v in pts:
        daily[t // 86400] = v
    days = sorted(daily)
    vals, last = [], None
    for d in range(days[0], days[-1] + 1):
        last = daily.get(d, last)
        vals.append(last)
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1]]
    mu = _mean(rets)
    sd = math.sqrt(_mean([(r - mu) ** 2 for r in rets])) if rets else 0
    dd_ = math.sqrt(_mean([min(0, r) ** 2 for r in rets])) if rets else 0
    peak, mdd, dd_len, cur_len, under = vals[0], 0.0, 0, 0, []
    for d, v in zip(range(days[0], days[-1] + 1), vals):
        peak = max(peak, v)
        dd = 1 - v / peak if peak else 0
        mdd = max(mdd, dd)
        cur_len = cur_len + 1 if dd > 0 else 0
        dd_len = max(dd_len, cur_len)
        under.append({"time": d * 86400, "value": round(-dd * 100, 3)})
    years = max(1 / 365, (len(vals) - 1) / 365)
    total = pts[-1][1] / pts[0][1] - 1 if pts[0][1] else 0          # 하루 안에 끝난 거래도 반영되게 거래 단위로
    pk = pts[0][1]
    for _, v in pts:
        pk = max(pk, v)
        mdd = max(mdd, 1 - v / pk if pk else 0)
    cagr = ((1 + total) ** (1 / years) - 1 if total > -1 else -1) if len(vals) >= 30 else None   # 30일 미만은 연율화하면 왜곡
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    streak = best = worst_s = 0
    for t in trades:
        streak = (streak + 1 if streak >= 0 else 1) if t["pnl"] > 0 else (streak - 1 if streak <= 0 else -1)
        best, worst_s = max(best, streak), min(worst_s, streak)
    # 월별
    monthly: dict[str, dict[int, float]] = {}
    by_month: dict[tuple, list[float]] = {}
    for d, v in zip(range(days[0], days[-1] + 1), vals):
        dt = datetime.fromtimestamp(d * 86400, timezone.utc)
        by_month.setdefault((dt.year, dt.month), []).append(v)
    prev = vals[0]
    for (y, m), vs in sorted(by_month.items()):
        monthly.setdefault(str(y), {})[m] = round((vs[-1] / prev - 1) * 100, 2) if prev else 0
        prev = vs[-1]

    def group(key):
        g: dict = {}
        for t in trades:
            k = key(t)
            x = g.setdefault(k, {"key": k, "pnl": 0.0, "trades": 0, "wins": 0})
            x["pnl"] += t["pnl"]
            x["trades"] += 1
            x["wins"] += t["pnl"] > 0
        return [{**x, "pnl": round(x["pnl"], 2), "win_rate": round(x["wins"] / x["trades"] * 100, 1)} for x in g.values()]
    hold = [(t["exit_time"] - t["entry_time"]) / 3600 for t in trades]
    gw, gl = sum(wins), -sum(losses)
    wd = "월화수목금토일"
    return {
        "stats": {"trades": len(trades), "total_return_pct": round(total * 100, 2), "cagr_pct": None if cagr is None else round(cagr * 100, 2),
                  "ann_vol_pct": round(sd * math.sqrt(365) * 100, 2), "sharpe": round(mu / sd * math.sqrt(365), 2) if sd else None,
                  "sortino": round(mu / dd_ * math.sqrt(365), 2) if dd_ else None,
                  "calmar": round(cagr / mdd, 2) if mdd and cagr is not None else None, "max_dd_pct": round(mdd * 100, 2), "max_dd_days": dd_len,
                  "win_rate_pct": round(len(wins) / len(trades) * 100, 1), "avg_win": round(_mean(wins), 2), "avg_loss": round(_mean(losses), 2),
                  "payoff": round(_mean(wins) / -_mean(losses), 2) if losses and _mean(losses) else None,
                  "expectancy": round(_mean([t["pnl"] for t in trades]), 2), "profit_factor": round(gw / gl, 2) if gl else None,
                  "avg_hold_h": round(_mean(hold), 1), "best_trade": round(max(t["pnl"] for t in trades), 2),
                  "worst_trade": round(min(t["pnl"] for t in trades), 2), "win_streak": best, "loss_streak": -worst_s,
                  "days": len(vals)},
        "monthly": monthly, "underwater": under,
        "by_symbol": sorted(group(lambda t: t.get("symbol") or "-"), key=lambda x: x["pnl"]),
        "by_side": group(lambda t: "롱" if t["side"] == "long" else "숏"),
        "by_hour": sorted(group(lambda t: datetime.fromtimestamp(t["entry_time"], KST).hour), key=lambda x: x["key"]),
        "by_weekday": sorted(group(lambda t: datetime.fromtimestamp(t["entry_time"], KST).weekday()), key=lambda x: x["key"]),
        "weekday_names": list(wd),
    }
