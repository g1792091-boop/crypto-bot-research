"""보호 장치 — 연속 손절·급한 낙폭 뒤에는 새 진입을 잠시 쉰다 (청산은 언제나 허용).

열린 소스 참고(코드 복사 없이 개념만 재구현): freqtrade 의 Protections
(StoplossGuard · MaxDrawdown · CooldownPeriod · LowProfitPairs).
실거래 동기화(live.sync)가 새 포지션을 열기 전에 그 매매법의 데모 거래 기록으로 확인한다.
"""
from __future__ import annotations

import time

RULES = {
    "stoploss_guard": {"window_h": 24, "losses": 3, "pause_h": 6},       # 24시간 안에 손실 3번 → 6시간 쉼
    "max_drawdown": {"window_h": 48, "dd_pct": 15.0, "pause_h": 12},     # 48시간 동안 낙폭 15% → 12시간 쉼
    "cooldown": {"after_loss_min": 30},                                   # 손실 청산 뒤 30분은 새 진입 안 함
    "low_profit": {"trades": 10, "pf": 0.8, "pause_h": 24},               # 최근 10번 손익비 0.8 미만 → 24시간 쉼
}


def check(trades: list, initial_equity: float = 10_000.0, now: float | None = None) -> dict:
    """trades: pnl · exit_time(초) 를 가진 거래들(시간순). → {blocked, reason, until}"""
    now = now or time.time()
    if not trades:
        return {"blocked": False, "reason": None, "until": None}
    g = RULES["stoploss_guard"]
    recent_losses = [t for t in trades if t.exit_time >= now - g["window_h"] * 3600 and t.pnl < 0]
    if len(recent_losses) >= g["losses"]:
        until = recent_losses[-1].exit_time + g["pause_h"] * 3600
        if until > now:
            return {"blocked": True, "reason": f"{g['window_h']}시간 안 손실 {len(recent_losses)}번 → {g['pause_h']}시간 쉼 (연속 손절 보호)", "until": until}
    m = RULES["max_drawdown"]
    eq, curve = initial_equity, []
    for t in trades:
        eq += t.pnl
        curve.append((t.exit_time, eq))
    win = [(ts, v) for ts, v in curve if ts >= now - m["window_h"] * 3600]
    if win:
        start_eq = next((v for ts, v in reversed(curve) if ts < now - m["window_h"] * 3600), initial_equity)
        peak, dd = start_eq, 0.0
        for _, v in win:
            peak = max(peak, v)
            dd = max(dd, (peak - v) / peak * 100 if peak > 0 else 0)
        if dd >= m["dd_pct"]:
            until = win[-1][0] + m["pause_h"] * 3600
            if until > now:
                return {"blocked": True, "reason": f"{m['window_h']}시간 낙폭 {dd:.1f}% → {m['pause_h']}시간 쉼 (낙폭 보호)", "until": until}
    c = RULES["cooldown"]
    last = trades[-1]
    if last.pnl < 0 and now - last.exit_time < c["after_loss_min"] * 60:
        return {"blocked": True, "reason": f"방금 손실 청산 → {c['after_loss_min']}분 쉼", "until": last.exit_time + c["after_loss_min"] * 60}
    lp = RULES["low_profit"]
    tail = trades[-lp["trades"]:]
    if len(tail) >= lp["trades"]:
        gw = sum(t.pnl for t in tail if t.pnl > 0)
        gl = -sum(t.pnl for t in tail if t.pnl < 0)
        pf = gw / gl if gl > 0 else 99
        until = tail[-1].exit_time + lp["pause_h"] * 3600
        if pf < lp["pf"] and until > now:
            return {"blocked": True, "reason": f"최근 {lp['trades']}번 손익비 {pf:.2f} → {lp['pause_h']}시간 쉼 (성적 부진 보호)", "until": until}
    return {"blocked": False, "reason": None, "until": None}
