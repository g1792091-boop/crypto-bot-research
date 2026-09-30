"""전략 백테스트."""
from __future__ import annotations

from dataclasses import asdict

from .data import market
from .data.synthetic import INTERVAL_SECONDS
from .engine import Simulator, metrics
from .strategy import DERIV_FIELDS, StrategySpec, build_series, referenced_names, signals, validate


def needs_derivatives(spec: StrategySpec) -> bool:
    return bool(referenced_names(spec) & DERIV_FIELDS)


def run(spec: StrategySpec, candles: list[dict], deriv: dict | None = None,
        initial_equity: float = 10_000.0) -> dict:
    problems = validate(spec)
    if problems:
        raise ValueError("; ".join(problems))
    bar_seconds = INTERVAL_SECONDS.get(spec.interval, 3600)
    sig = signals(spec, candles, deriv)
    sim = Simulator(risk=spec.risk, initial_equity=initial_equity, bar_seconds=bar_seconds)
    for i, bar in enumerate(candles):
        sim.step(bar, sig, i)
        if sim.blown:
            break
    if sim.position:  # 마지막 봉 종가로 정리
        sim.close_position(candles[-1]["close"], candles[-1]["time"], "end_of_test")
        sim.equity_curve[-1]["value"] = round(sim.cash, 4)

    first, last = candles[0]["close"], candles[-1]["close"]
    m = metrics(sim, bar_seconds)
    m["buy_and_hold_pct"] = round((last / first - 1) * 100, 2)
    markers = []
    for t in sim.trades:
        long_ = t.side == "long"
        markers.append({"time": t.entry_time, "position": "belowBar" if long_ else "aboveBar",
                        "color": "#22c55e" if long_ else "#ef4444",
                        "shape": "arrowUp" if long_ else "arrowDown",
                        "text": f"{'L' if long_ else 'S'} {t.entry_price:.2f}"})
        markers.append({"time": t.exit_time, "position": "aboveBar" if long_ else "belowBar",
                        "color": "#a3a3a3", "shape": "circle",
                        "text": f"{t.exit_reason} {t.pnl:+.1f}"})
    markers.sort(key=lambda m_: m_["time"])
    return {
        "spec": spec.model_dump(),
        "metrics": m,
        "equity_curve": sim.equity_curve,
        "trades": [asdict(t) for t in sim.trades],
        "markers": markers,
    }


def coverage_warnings(spec: StrategySpec, candles: list[dict], deriv: dict | None) -> list[str]:
    used = referenced_names(spec) & DERIV_FIELDS
    if not used:
        return []
    series = build_series(spec, candles, deriv)
    out = []
    for name in sorted(used):
        have = sum(v is not None for v in series[name])
        pct = have / len(candles) * 100
        if pct < 99:
            out.append(f"{name}: 테스트 구간의 {pct:.0f}%만 데이터가 있습니다. 데이터가 없는 봉에서는 이 조건이 거짓으로 처리됩니다.")
    return out


def run_live_data(spec: StrategySpec, bars: int = 1500, initial_equity: float = 10_000.0) -> dict:
    candles, source = market.candles(spec.symbol, spec.interval, bars)
    deriv = market.derivatives(spec.symbol, spec.interval, 500) if needs_derivatives(spec) else None
    res = run(spec, candles, deriv, initial_equity)
    res["data_source"] = source
    res["warnings"] = coverage_warnings(spec, candles, deriv)
    res["candles"] = candles
    if deriv:
        res["derivatives_source"] = deriv.get("source")
    return res
