"""펀딩비 차익(캐리) 점검 — 현물 롱 + 선물 숏(가격 방향 중립)으로 펀딩비만 받는 전략이 얼마나 되나.

열린 소스 참고(코드 복사 없이 개념만 재구현): hummingbot 의 perpetual funding-rate arbitrage, passivbot·freqtrade 커뮤니티의 basis 전략.
- 최근 펀딩 기록(8시간마다)의 평균 · 양수 비율 · 연 환산(APR)
- 진입·청산 수수료(현물 + 선물 왕복)를 빼고, 본전까지 며칠 걸리는지
- 펀딩이 음수로 바뀌면 오히려 내야 하므로 '양수였던 비율'로 안정성을 본다. 분석 전용 — 주문하지 않는다.
"""
from __future__ import annotations

FEES_PCT = 0.2          # 현물 왕복 0.1% + 선물 왕복 0.1% (대략)
PER_DAY = 3             # 바이낸스 USDT-M 은 보통 8시간마다


def one(symbol: str, periods: int = 90) -> dict:
    from ..data import market
    d = market.derivatives(symbol, "1h", periods)
    rows = [x["value"] for x in (d.get("funding") or []) if x.get("value") is not None][-periods:]
    if len(rows) < 10:
        return {"symbol": symbol, "error": "펀딩 기록 없음"}
    avg = sum(rows) / len(rows)                                   # % / 8시간
    pos = sum(1 for v in rows if v > 0) / len(rows) * 100
    recent = sum(rows[-9:]) / len(rows[-9:])
    apr = avg * PER_DAY * 365
    daily = avg * PER_DAY
    breakeven = FEES_PCT / daily if daily > 0 else None
    side = "현물 롱 + 선물 숏 (펀딩 받음)" if avg > 0 else "현물 매도 + 선물 롱 (현물을 빌려야 함 · 보통 불가)"
    score = apr * (pos / 100 if avg > 0 else (100 - pos) / 100)
    cross = _cross(symbol, d.get("source"), rows[-1])
    return {**cross, "symbol": symbol, "source": d.get("source"), "periods": len(rows), "avg_pct": round(avg, 5), "recent_pct": round(recent, 5),
            "apr_pct": round(apr, 2), "positive_pct": round(pos, 1), "breakeven_days": round(breakeven, 1) if breakeven else None,
            "net_30d_pct": round(daily * 30 - FEES_PCT, 3), "side": side, "score": round(score, 2)}


def _cross(symbol: str, source: str | None, last: float) -> dict:
    """거래소 간 펀딩 차이 (hummingbot v2_funding_rate_arb 개념) — 한쪽 롱·다른 쪽 숏이면 차이만큼 받는다. 실제 시세에서만."""
    from .. import config
    if config.DATA_SOURCE == "synthetic":
        return {}
    try:
        from ..data import altex, binance
        bn = binance.funding_history(symbol, 3)[-1]["value"] if source != "binance" else last
        bb = altex.bybit_funding(symbol, 3)[-1]["value"] if source != "bybit" else last
    except Exception:  # noqa: BLE001
        return {}
    spread = bn - bb
    return {"binance_pct": round(bn, 5), "bybit_pct": round(bb, 5), "spread_pct": round(spread, 5),
            "spread_apr_pct": round(abs(spread) * PER_DAY * 365, 2),
            "spread_side": ("바이낸스 숏 + 바이빗 롱" if spread > 0 else "바이빗 숏 + 바이낸스 롱") if abs(spread) > 0.0001 else "차이 거의 없음"}


def scan(symbols: list[str], periods: int = 90) -> list[dict]:
    out = []
    for s in symbols:
        try:
            out.append(one(s, periods))
        except Exception as e:  # noqa: BLE001
            out.append({"symbol": s, "error": str(e)[:80]})
    out.sort(key=lambda r: -(r.get("score") or -1e9))
    return out


def text(rows: list[dict]) -> str:
    ok = [r for r in rows if "error" not in r]
    if not ok:
        return "[펀딩 차익 점검] 펀딩 기록을 받지 못했습니다"
    lines = [f"[펀딩 차익 점검] 현물·선물 반대로 잡아 가격 방향은 지우고 펀딩비만 받는 경우 (수수료 왕복 {FEES_PCT}% 차감 · 분석 전용)"]
    for r in ok[:8]:
        lines.append(f"- {r['symbol']}: 연 {r['apr_pct']:+.1f}% · 최근 {r['recent_pct']:+.4f}%/8h · 양수 {r['positive_pct']}% · 30일 순 {r['net_30d_pct']:+.2f}% · "
                     f"본전 {r['breakeven_days'] or '-'}일 · {r['side']}"
                     + (f" · 거래소 차이 연 {r['spread_apr_pct']}% ({r['spread_side']})" if r.get("spread_apr_pct") is not None else ""))
    lines.append("주의: 펀딩은 수시로 바뀌고, 거래소 위험·청산(선물 쪽 급등) 위험이 있습니다. 큰 수익이 아니라 '안정적인 작은 수익' 전략입니다.")
    return "\n".join(lines)
