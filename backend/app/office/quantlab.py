"""퀀트 연구소 검증 도구 — 지표 29종 스냅샷, 전체 과거 캔들, 70/30 관문, 시나리오 재시험.

- 관문(코드 판정, AI 가 뒤집지 못함): 한 번 백테스트 → 진입 시각으로 앞 70%/뒤 30% 를 나눠
  검증 구간 거래 20건 이상 · 손익비 1.2 이상 · 검증 구간 순손익 > 0 · 학습 구간 순손익 > 0.
- 시나리오: 레버리지 1~200배 · 장세(상승/하락/횡보/폭락/고변동) · 연도별 · 비용 2·3배 · 1봉 지연 · 손절 0.5·1.5배.
  판정 견고/보통/취약 — 이 앱에서는 '취약'이면 시그널 추적에 올리지 않는다(원본은 참고만 했다).
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from .. import indicators as ind
from ..data import market
from ..data.synthetic import INTERVAL_SECONDS
from ..engine import Simulator, metrics
from ..strategy import StrategySpec, signals, validate

GATE = {"train_share": 0.7, "min_test_trades": 20, "min_test_pf": 1.2}
LEVERAGES = [1, 2, 3, 5, 10, 20, 50, 100, 125, 200]
COSTS = {"fee_pct": 0.04, "slippage_pct": 0.01, "funding_rate_8h_pct": 0.01}
_hist: dict = {}


# ------------------------------------------------------------------ 전체 과거
def history(symbol: str, interval: str, max_bars: int | None = None) -> tuple[list[dict], str]:
    """가능한 한 오래된 과거부터 (바이낸스 선물 상장 이후, 1h 이하 20,000봉 · 그 이상 30,000봉까지). 1시간 캐시."""
    mb = max_bars or (30000 if interval in ("1d", "3d", "1w", "1M") else 20000)
    key = (symbol, interval, mb)
    hit = _hist.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1], hit[2]
    try:
        c, src = market.candles(symbol, interval, mb)
    except Exception:  # noqa: BLE001
        c, src = market.candles(symbol, interval, 1500)
    if len(c) < 300:
        c, src = market.candles(symbol, interval, 1500)
    d = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    yrs = (c[-1]["time"] - c[0]["time"]) / 31_557_600 if c else 0
    note = f"{src} {symbol} {interval} · {d(c[0]['time'])} ~ {d(c[-1]['time'])} · {len(c):,}봉 ({yrs:.1f}년)" if c else "데이터 없음"
    _hist[key] = (time.time(), c, note)
    return c, note


# ------------------------------------------------------------------ 지표 29종 스냅샷
def _last(x):
    for v in reversed(x):
        if v is not None:
            return v
    return None


def snapshot(c: list[dict]) -> dict:
    """모든 내장 지표의 마지막 값 + 추세·모멘텀·변동성·거래량 4줄 해설."""
    vals: dict = {}
    for name in ind.REGISTRY:
        if name in ("ml", "custom"):
            continue
        try:
            res = ind.compute(c, name, {})
            vals[name] = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in ((k, _last(s)) for k, s in res.items())}
        except Exception:  # noqa: BLE001
            continue
    px = c[-1]["close"]
    g = lambda n, k="value": (vals.get(n) or {}).get(k)
    mas = [g(n) for n in ("sma", "ema", "wma", "vwma", "hma")]
    above = sum(1 for m in mas if m and px > m)
    e20 = g("ema")
    adx = g("adx", "adx")
    trend = [f"가격이 이평 {len([m for m in mas if m])}개 중 {above}개 위" + (f" (EMA20 대비 {(px / e20 - 1) * 100:+.2f}%)" if e20 else ""),
             f"슈퍼트렌드 {'상승' if g('supertrend', 'trend') == 1 else '하락'}", f"PSAR {'상승' if g('psar', 'trend') == 1 else '하락'}",
             f"ATR추적 {'상승' if g('atr_stop', 'trend') == 1 else '하락'}"]
    if adx is not None:
        trend.append(f"ADX {adx:.0f}{' 추세 뚜렷' if adx >= 25 else ' 방향성 약함' if adx < 18 else ' 보통'} (+DI {'>' if (g('adx', 'plus_di') or 0) > (g('adx', 'minus_di') or 0) else '<'} -DI)")
    sa, sb = g("ichimoku", "span_a"), g("ichimoku", "span_b")
    if sa and sb:
        trend.append("일목 구름 " + ("위" if px > max(sa, sb) else "아래" if px < min(sa, sb) else "안"))
    rsi, k = g("rsi"), g("stoch", "k")
    mom = []
    if rsi is not None:
        mom.append(f"RSI {rsi:.1f}{' 과매수' if rsi >= 70 else ' 과매도' if rsi <= 30 else ''}")
    if k is not None:
        mom.append(f"스토캐스틱 K {k:.0f}{' 과열' if k >= 80 else ' 침체' if k <= 20 else ''}")
    if g("cci") is not None:
        mom.append(f"CCI {g('cci'):.0f}")
    if g("roc") is not None:
        mom.append(f"ROC9 {g('roc'):+.2f}%")
    mh = ind.compute(c, "macd", {})["hist"]
    h1, h0 = _last(mh), _last(mh[:-1])
    if h1 is not None and h0 is not None:
        mom.append(f"MACD 히스토 {'양(+)' if h1 > 0 else '음(-)'} {'확대' if abs(h1) > abs(h0) else '축소'}")
    vol = []
    atr = g("atr")
    if atr:
        vol.append(f"ATR14 {atr / px * 100:.2f}%")
    widths = [w for w in ind.compute(c, "bb", {})["width"] if w is not None]
    if widths:
        rank = sum(1 for w in widths if w <= widths[-1]) / len(widths) * 100
        vol.append(f"볼린저 폭 {widths[-1]:.2f}% (과거 대비 하위 {rank:.0f}%{', 수축 — 큰 움직임 대기' if rank <= 15 else ', 과열' if rank >= 85 else ''})")
    dh, dl = g("donchian", "upper"), g("donchian", "lower")
    if dh and dl:
        vol.append("돈치안20 " + ("신고가" if px >= dh else "신저가" if px <= dl else "범위 안"))
    vs = g("volume_sma")
    volume = []
    if vs:
        volume.append(f"평균의 {c[-1]['volume'] / vs:.2f}배")
    cmf = g("cmf")
    if cmf is not None:
        volume.append(f"CMF {cmf:+.2f}{' 매수 우위' if cmf > .05 else ' 매도 우위' if cmf < -.05 else ' 중립'}")
    if g("mfi") is not None:
        volume.append(f"MFI {g('mfi'):.0f}")
    vw = g("vwap")
    if vw:
        volume.append(f"VWAP {'위' if px > vw else '아래'} ({(px / vw - 1) * 100:+.2f}%)")
    text = f"추세: {' · '.join(trend)}\n모멘텀: {' · '.join(mom)}\n변동성: {' · '.join(vol)}\n거래량: {' · '.join(volume)}"
    return {"price": px, "ind": vals, "text": text}


# ------------------------------------------------------------------ 시뮬레이션
def _sim(spec: StrategySpec, c: list[dict], sig: dict, risk=None, leverage=None) -> tuple[Simulator, dict]:
    bar = INTERVAL_SECONDS.get(spec.interval, 3600)
    r = (risk or spec.risk).model_copy(update={"leverage": leverage} if leverage else {})
    sim = Simulator(risk=r, initial_equity=10_000.0, bar_seconds=bar)
    for i, b in enumerate(c):
        sim.step(b, sig, i)
        if sim.blown:
            break
    if sim.position:
        sim.close_position(c[-1]["close"], c[-1]["time"], "end_of_test")
        sim.equity_curve[-1]["value"] = round(sim.cash, 4)
    m = metrics(sim, bar)
    m["buy_and_hold_pct"] = round((c[-1]["close"] / c[0]["close"] - 1) * 100, 2)
    return sim, m


def _stats(trades, eq_from, eq_to) -> dict:
    n = len(trades)
    wins = [t for t in trades if t.pnl > 0]
    gw, gl = sum(t.pnl for t in wins), -sum(t.pnl for t in trades if t.pnl <= 0)
    return {"n": n, "net": round(sum(t.pnl for t in trades), 2), "win": round(len(wins) / n * 100, 1) if n else None,
            "pf": round(gw / gl, 2) if gl > 0 else (None if not n else 99.0), "ret": round((eq_to / eq_from - 1) * 100, 2) if eq_from else None}


def _dd(eq: list[float]) -> float:
    peak, mdd = -math.inf, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100)
    return round(mdd, 2)


def gate(spec: StrategySpec, c: list[dict], deriv: dict | None = None, extra: dict | None = None) -> dict:
    """앞 70% 학습 / 뒤 30% 검증 관문 (코드 판정)."""
    probs = validate(spec)
    if probs:
        raise ValueError("; ".join(probs))
    sig = signals(spec, c, deriv, extra)
    sim, m = _sim(spec, c, sig)
    cut_t = c[int(len(c) * GATE["train_share"])]["time"]
    eq = sim.equity_curve
    k = next((i for i, p in enumerate(eq) if p["time"] >= cut_t), len(eq) - 1)
    eqv = [p["value"] for p in eq]
    ist = [t for t in sim.trades if t.entry_time < cut_t]
    oot = [t for t in sim.trades if t.entry_time >= cut_t]
    IS = {**_stats(ist, eqv[0], eqv[k]), "dd": _dd(eqv[:k + 1])}
    OOS = {**_stats(oot, eqv[k], eqv[-1]), "dd": _dd(eqv[k:])}
    ALL = {"n": m.get("trades", 0), "ret": m.get("total_return_pct"), "dd": m.get("max_drawdown_pct"), "win": m.get("win_rate_pct"),
           "pf": m.get("profit_factor")}
    checks = [(OOS["n"] >= GATE["min_test_trades"], f"검증 구간(뒤 30%) 거래 {OOS['n']}건 (기준 {GATE['min_test_trades']}건 이상)"),
              (OOS["pf"] is not None and OOS["pf"] >= GATE["min_test_pf"], f"검증 구간 손익비 {OOS['pf']} (기준 {GATE['min_test_pf']} 이상)"),
              (OOS["net"] > 0, f"검증 구간 순손익 {OOS['net']:+.0f} (기준 0 초과)"),
              (IS["net"] > 0, f"학습 구간 순손익 {IS['net']:+.0f} (기준 0 초과)")]
    reasons = [("통과: " if ok else "미달: ") + s for ok, s in checks]
    passed = all(ok for ok, _ in checks)
    if not passed and IS["net"] > 0 and OOS["net"] <= 0:
        reasons.append("학습 구간에서만 이익 → 과최적화 가능성이 큽니다")
    return {"pass": passed, "reasons": reasons, "all": ALL, "is": IS, "oos": OOS, "metrics": m, "sig": sig, "sim": sim}


# ------------------------------------------------------------------ 장세 분류
def regimes(c: list[dict], interval: str) -> list[str]:
    n = len(c)
    per_day = max(1, round(86400 / INTERVAL_SECONDS.get(interval, 3600)))
    L, S, C = 200 * per_day, 50 * per_day, 20 * per_day
    if n < 2.5 * L:
        L = max(20, n // 5)
        S, C = max(5, L // 4), max(5, L // 10)
    cl = [b["close"] for b in c]
    hi = [b["high"] for b in c]
    sma = ind.sma(cl, L)
    hiL, hiC = ind.highest(hi, L), ind.highest(hi, C)
    atrp = [a / x if a else None for a, x in zip(ind.atr(c, 14), cl)]
    vals = sorted(v for v in atrp if v)
    p80 = vals[int(len(vals) * .8)] if len(vals) > 50 else None
    rets = [0.0] + [cl[i] / cl[i - 1] - 1 for i in range(1, n)]
    out = []
    for i in range(n):
        if hiC[i] and cl[i] <= hiC[i] * 0.8:
            out.append("crash")
            continue
        if sma[i] and hiL[i] and cl[i] < sma[i] and cl[i] <= hiL[i] * 0.8:
            out.append("bear")
            continue
        if p80 and atrp[i] and atrp[i] >= p80:
            out.append("highvol")
            continue
        if sma[i] is None or i < S or sma[i - S] is None:
            out.append("unknown")
            continue
        w = rets[i - S + 1:i + 1]
        m = sum(w) / S
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / S) or 1e-12
        z = (sma[i] / sma[i - S] - 1) / (sd * math.sqrt(S))
        out.append("bull" if cl[i] > sma[i] and z >= .25 else "bear" if cl[i] < sma[i] and z <= -.25 else "sideways")
    return out


REG_KO = {"bull": "상승장", "bear": "하락장", "sideways": "횡보", "crash": "폭락", "highvol": "고변동", "unknown": "판단불가(초기)"}


def scenarios(spec: StrategySpec, c: list[dict], deriv: dict | None = None, extra: dict | None = None, sig: dict | None = None) -> dict:
    sig = sig or signals(spec, c, deriv, extra)
    base_sim, base = _sim(spec, c, sig)
    lev0 = spec.risk.leverage
    d = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")

    def summary(sim, m):
        eq = [p["value"] for p in sim.equity_curve] or [10000]
        liq = sum(1 for t in sim.trades if t.exit_reason == "liquidation")
        bust = sim.blown or min(eq) <= 100
        ruin = next((p["time"] for p in sim.equity_curve if p["value"] <= 100), None)
        return {"ret": m.get("total_return_pct"), "dd": m.get("max_drawdown_pct"), "n": m.get("trades", 0), "liq": liq,
                "bust": bust, "ruin": d(ruin) if ruin else None}
    lev = []
    for L in LEVERAGES:
        sim, m = _sim(spec, c, sig, leverage=L)
        lev.append({"lev": L, **summary(sim, m)})
    safe = [x["lev"] for x in lev if not x["liq"] and not x["bust"]]
    max_safe = max(safe) if safe else 0
    first_liq = next((x for x in lev if x["liq"]), None)
    first_bust = next((x for x in lev if x["bust"]), None)
    # 장세
    reg = regimes(c, spec.interval)
    t_idx = {b["time"]: i for i, b in enumerate(c)}
    per = {}
    for r in set(reg):
        per[r] = {"bars": reg.count(r), "trades": 0, "wins": 0, "pnl": 0.0}
    for t in base_sim.trades:
        i = t_idx.get(t.entry_time, 1)
        r = reg[max(0, i - 1)]
        per[r]["trades"] += 1
        per[r]["wins"] += t.pnl > 0
        per[r]["pnl"] += t.pnl
    # 연도
    years: dict = {}
    for t in base_sim.trades:
        y = datetime.fromtimestamp(t.exit_time, timezone.utc).year
        a = years.setdefault(y, {"n": 0, "pnl": 0.0})
        a["n"] += 1
        a["pnl"] += t.pnl
    # 스트레스
    r = spec.risk

    def stressed(**upd):
        return _sim(spec, c, sig, risk=r.model_copy(update=upd))[1].get("total_return_pct")
    stress = {"cost_x2": stressed(fee_pct=r.fee_pct * 2, slippage_pct=r.slippage_pct * 2),
              "cost_x3": stressed(fee_pct=r.fee_pct * 3, slippage_pct=r.slippage_pct * 3)}
    shifted = {k: ([False] + v[:-1] if isinstance(v, list) and k in ("long_entry", "short_entry", "long_exit", "short_exit") else v) for k, v in sig.items()}
    stress["delay_1"] = _sim(spec, c, shifted)[1].get("total_return_pct")
    has_stop = any(getattr(r, k) for k in ("stop_loss_pct", "atr_stop_mult", "trailing_stop_pct"))
    if has_stop:
        for f in (0.5, 1.5):
            stress[f"stop_x{f}"] = stressed(**{k: getattr(r, k) * f for k in ("stop_loss_pct", "atr_stop_mult", "trailing_stop_pct") if getattr(r, k)})
    # 판정
    checks, points = [], []
    b = base.get("total_return_pct") or 0
    if not base.get("trades"):
        return {"grade": "판정 보류", "text": f"[시나리오 분석] {spec.name} · 거래가 없어 판정 보류", "leverage": lev, "base": base}
    checks.append(b > 0)
    checks.append(max_safe >= lev0)
    points.append(f"레버리지 {max_safe}배까지는 강제청산 없음" + (f", {first_liq['lev']}배부터 강제청산 {first_liq['liq']}회" if first_liq else "")
                  + (f" · {first_bust['lev']}배는 파산 ({first_bust['ruin'] or '-'})" if first_bust else ""))
    checks.append((stress["cost_x2"] or 0) > 0)
    if (stress["cost_x2"] or 0) <= 0:
        points.append(f"수수료·슬리피지 2배면 손익분기 아래 ({stress['cost_x2']:+.1f}%) — 비용에 민감")
    checks.append((stress["delay_1"] or 0) > 0)
    if (stress["delay_1"] or 0) <= 0:
        points.append(f"신호 1봉 지연 시 손실 전환 ({stress['delay_1']:+.1f}%) — 체결 타이밍에 민감")
    if len(years) >= 2:
        pos = sum(1 for v in years.values() if v["pnl"] > 0)
        checks.append(pos / len(years) >= .6)
        worst = min(years.items(), key=lambda kv: kv[1]["pnl"])
        points.append(f"{len(years)}년 중 {pos}년 이익 · 최악 {worst[0]}년 {worst[1]['pnl']:+.0f}")
    active = {k: v for k, v in per.items() if k != "unknown" and v["trades"] >= 3}
    if active:
        prof = [k for k, v in active.items() if v["pnl"] > 0]
        checks.append(len(prof) >= 2 or len(prof) == len(active))
        losing = [REG_KO[k] for k, v in active.items() if v["pnl"] <= 0]
        if losing and prof:
            points.append(f"{', '.join(losing)}에서 손실")
    if has_stop:
        checks.append((stress.get("stop_x0.5") or 0) > 0 and (stress.get("stop_x1.5") or 0) > 0)
    points.append(f"같은 기간 보유만 했을 때 {base.get('buy_and_hold_pct'):+.1f}% (전략 {b:+.1f}%)")
    score = sum(checks) / len(checks)
    grade = "취약" if b <= 0 else "견고" if score >= .8 else "보통" if score >= .5 else "취약"
    lines = [f"[시나리오 분석] {spec.name} · {spec.symbol} {spec.interval} · {d(c[0]['time'])}~{d(c[-1]['time'])} ({len(c):,}봉, {(c[-1]['time'] - c[0]['time']) / 31_557_600:.1f}년)",
             f"기본(레버리지 {lev0:g}배): 수익 {b:+.1f}% · 최대낙폭 {base.get('max_drawdown_pct')}% · 거래 {base.get('trades')} · 승률 {base.get('win_rate_pct')}%",
             "레버리지: " + " | ".join(f"{x['lev']}x {x['ret']:+.0f}%/DD {x['dd']:.0f}%/청산 {x['liq']}" for x in lev),
             "국면(진입 기준): " + " · ".join(f"{REG_KO[k]} {v['trades']}건 {v['pnl']:+.0f}" for k, v in per.items() if v["trades"]),
             "연도: " + " · ".join(f"{y} {v['pnl']:+.0f}({v['n']})" for y, v in sorted(years.items())),
             "스트레스: " + " · ".join(f"{k} {v:+.1f}%" for k, v in stress.items() if v is not None),
             f"판정: {grade} ({sum(checks)}/{len(checks)} 통과) — " + " / ".join(points)]
    return {"grade": grade, "score": score, "leverage": lev, "max_safe_lev": max_safe, "regimes": per, "years": years, "stress": stress,
            "points": points, "base": base, "text": "\n".join(lines)[:2500]}
