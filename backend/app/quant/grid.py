"""그리드 매매 백테스트 — 박스권에서 '싸게 사서 한 칸 위에 판다'를 반복한다.

열린 소스 참고(코드 복사 없이 개념만 재구현): OctoBot·hummingbot·passivbot 의 그리드 전략.
- 가격 구간 [lower, upper] 를 levels 칸으로 나누고, 칸마다 같은 금액을 건다.
- 가격이 칸 아래로 내려오면 그 칸에서 롱 1개, 한 칸 위로 올라오면 그 롱을 익절 (수수료 포함).
- 박스를 아래로 이탈(lower × (1 − stop))하면 모두 손절하고 멈춘다. 레버리지 · 청산(증거금 소진)도 계산.
"""
from __future__ import annotations

import math


def backtest(candles: list[dict], lower: float, upper: float, levels: int = 10, leverage: float = 2.0,
             capital: float = 10_000.0, fee_pct: float = 0.05, stop_pct: float = 3.0) -> dict:
    if not (0 < lower < upper) or not (2 <= levels <= 200) or not (1 <= leverage <= 20):
        raise ValueError("lower < upper · 칸 2~200 · 레버리지 1~20")
    if len(candles) < 20:
        raise ValueError("캔들이 20개 이상 필요합니다")
    step = (upper - lower) / levels
    grid = [lower + i * step for i in range(levels + 1)]
    per = capital * leverage / levels                      # 칸마다 거는 명목 금액
    fee = fee_pct / 100
    held: dict[int, float] = {}                            # 칸 번호 → 수량
    cash, realized, fees, trips = capital, 0.0, 0.0, 0
    peak, mdd, liquidated, stopped = capital, 0.0, False, None
    curve = []
    first = candles[0]["close"]
    prev = candles[0]["open"]
    for k, b in enumerate(candles):
        lo, hi, close = b["low"], b["high"], b["close"]
        # 지난 종가보다 아래 칸에 걸어 둔 매수 주문이 이번 봉 저가에 닿으면 체결
        bought = set()
        for i in range(levels):
            px = grid[i]
            if i not in held and px < prev and lo <= px:
                held[i] = per / px
                f = per * fee
                cash -= f
                fees += f
                bought.add(i)
        # 산 롱은 한 칸 위 가격에 익절 주문 (같은 봉 안의 순서는 알 수 없으니 산 봉에서는 팔지 않는다)
        for i in list(held):
            tp = grid[i + 1]
            if i not in bought and hi >= tp:
                qty = held.pop(i)
                gain = qty * (tp - grid[i])
                f = qty * tp * fee
                cash += gain - f
                realized += gain
                fees += f
                trips += 1
        prev = close
        unreal = sum(q * (close - grid[i]) for i, q in held.items())
        eq = cash + unreal
        margin_used = sum(q * grid[i] for i, q in held.items()) / leverage
        if eq <= margin_used * 0.5 and held:               # 유지 증거금 50% 아래 → 청산
            liquidated = True
            cash = max(0.0, eq)
            held.clear()
            curve.append(round(cash, 2))
            break
        if close < lower * (1 - stop_pct / 100) and held:   # 박스 아래 이탈 → 모두 손절
            loss = sum(q * (close - grid[i]) for i, q in held.items())
            f = sum(q * close for q in held.values()) * fee
            cash += loss - f
            fees += f
            held.clear()
            stopped = b["time"]
            curve.append(round(cash, 2))
            break
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100 if peak > 0 else 0)
        curve.append(round(eq, 2))
    end_px = candles[-1]["close"]
    final = cash + sum(q * (end_px - grid[i]) for i, q in held.items())
    days = (candles[-1]["time"] - candles[0]["time"]) / 86400 or 1
    return {"lower": round(lower, 6), "upper": round(upper, 6), "levels": levels, "leverage": leverage, "spacing_pct": round(step / lower * 100, 3),
            "round_trips": trips, "fees": round(fees, 2), "return_pct": round((final / capital - 1) * 100, 2), "max_dd_pct": round(mdd, 2),
            "liquidated": liquidated, "stopped_at": stopped, "open_levels": len(held), "days": round(days, 1),
            "trips_per_day": round(trips / days, 2), "buy_hold_pct": round((end_px / first - 1) * 100, 2), "curve": curve[-300:]}


def auto_range(candles: list[dict], lookback: int = 168) -> tuple[float, float]:
    """최근 lookback 봉의 고가·저가에서 위아래 5% 를 잘라낸 박스."""
    xs = candles[-lookback:]
    highs = sorted(b["high"] for b in xs)
    lows = sorted(b["low"] for b in xs)
    k = max(0, int(len(xs) * 0.05))
    return lows[k], highs[-1 - k]


def ranging(candles: list[dict], lookback: int = 168) -> dict:
    """박스권인가: 기간 수익률이 작고, 고저 폭 대비 순이동이 작을수록 박스권 (효율비 · Kaufman ER)."""
    xs = candles[-lookback:]
    move = abs(xs[-1]["close"] - xs[0]["close"])
    path = sum(abs(xs[i]["close"] - xs[i - 1]["close"]) for i in range(1, len(xs))) or 1
    er = move / path
    width = (max(b["high"] for b in xs) / min(b["low"] for b in xs) - 1) * 100
    return {"efficiency": round(er, 3), "width_pct": round(width, 2), "ranging": er < 0.25 and width < 25}


def scan(symbols: list[str], interval: str = "1h", bars: int = 720, levels: int = 12, leverage: float = 2.0) -> list[dict]:
    """코인마다: 앞부분으로 박스를 잡고(학습), 뒷부분으로 그리드를 돌린다(검증) — 같은 구간으로 맞추지 않는다."""
    from ..data import market
    out = []
    for s in symbols:
        try:
            c, _ = market.candles(s, interval, bars)
        except Exception as e:  # noqa: BLE001
            out.append({"symbol": s, "error": str(e)[:80]})
            continue
        if len(c) < 200:
            continue
        cut = int(len(c) * 0.5)
        lo, hi = auto_range(c[:cut], lookback=min(168, cut))
        reg = ranging(c[:cut], lookback=min(168, cut))
        try:
            r = backtest(c[cut:], lo, hi, levels, leverage)
        except ValueError as e:
            out.append({"symbol": s, "error": str(e)})
            continue
        out.append({"symbol": s, **reg, **{k: v for k, v in r.items() if k != "curve"}})
    out.sort(key=lambda x: -(x.get("return_pct") or -math.inf))
    return out


def text(rows: list[dict]) -> str:
    ok = [r for r in rows if "error" not in r]
    if not ok:
        return "[그리드 점검] 데이터 없음"
    lines = ["[그리드 점검] 앞 절반으로 박스를 잡고 뒤 절반으로 검증 (12칸 · 레버리지 2배 · 수수료 포함)"]
    for r in ok[:8]:
        flag = "청산" if r["liquidated"] else "박스 이탈 손절" if r["stopped_at"] else "진행"
        lines.append(f"- {r['symbol']}: {r['return_pct']:+.2f}% (보유만 {r['buy_hold_pct']:+.2f}%) · 왕복 {r['round_trips']}번 · 낙폭 {r['max_dd_pct']}% · "
                     f"박스권 {'예' if r['ranging'] else '아니오'}(효율비 {r['efficiency']}) · {flag}")
    return "\n".join(lines)
