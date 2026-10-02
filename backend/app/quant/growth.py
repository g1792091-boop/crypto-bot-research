"""목표 수익 현실 점검 — '한 달에 10만 원 → 1억' 같은 목표를 실제 성적으로 계산한다.

하는 일 (코드 계산 · AI 가 숫자를 지어내지 않는다)
1. 목표 수학: 하루 몇 % 복리가 필요한지, 두 배를 몇 번 연속 해야 하는지
2. 실제 거래 성적(데모 봇 · AI 시그널 채점 · 없으면 '좋은 전략' 가정)을 무작위로 다시 뽑아
   베팅 크기(레버리지 배수)마다 몬테카를로 → 목표 도달 확률 · 파산(원금 90% 손실) 확률 · 중앙값
3. 켈리 기준: 장기 성장이 가장 빠른 베팅 크기와, 그 크기(절반 켈리)로 목표까지 걸리는 기간

열린 소스 참고(코드 복사 없이 개념만 재구현): freqtrade·jesse 의 거래 몬테카를로, 켈리/성장 최적 베팅(Thorp).
"""
from __future__ import annotations

import math
import random

SCALES = [0.25, 0.5, 1, 2, 3, 5, 8, 12, 20, 30]     # 지금 베팅 크기의 몇 배로 거느냐
RUIN = 0.10                                         # 원금의 10% 아래로 떨어지면 '파산'
TAIL = {"every": 150, "mult": 4.0}                   # 급변·갭: 150번에 한 번은 손절가를 뚫고 최악 손실의 4배를 잃는다고 본다
MAX_LIVE_LEV = 20
ASSUMED = {"label": "가정: 승률 45% · 이길 때 +1.6R · 질 때 -1R · 1R=자본 1% · 하루 3번 (꽤 좋은 전략 수준)",
           "win": 0.45, "win_r": 1.6, "loss_r": 1.0, "risk": 0.01, "per_day": 3.0}


def target_math(start: float, target: float, days: int) -> dict:
    mult = target / start
    daily = mult ** (1 / days) - 1
    return {"start": start, "target": target, "days": days, "multiple": round(mult, 2), "doublings": round(math.log2(mult), 2),
            "daily_pct": round(daily * 100, 2), "weekly_pct": round(((1 + daily) ** 7 - 1) * 100, 1),
            "text": (f"{start:,.0f} → {target:,.0f} 은 {mult:,.0f}배 = 두 배를 {math.log2(mult):.1f}번 연속. "
                     f"{days}일 안에 하려면 매일 +{daily * 100:.1f}% 복리(주 +{((1 + daily) ** 7 - 1) * 100:.0f}%)를 하루도 빠짐없이 내야 합니다.")}


def _assumed_returns() -> list[float]:
    a = ASSUMED
    return [a["win_r"] * a["risk"]] * 45 + [-a["loss_r"] * a["risk"]] * 55


def _to_returns(trades: list[dict]) -> list[float]:
    """거래 손익을 '그때 자본 대비 수익률'로 (봇마다 따로 복리 순서대로)."""
    out = []
    for t in trades:
        eq = t.get("equity_before") or 0
        if eq > 0:
            out.append(t["pnl"] / eq)
    return out


def sources() -> dict:
    """쓸 수 있는 실제 성적 — 데모 봇 거래(수수료·펀딩 포함) → AI 시그널 채점 → 가정."""
    rets, days, label = [], 0.0, ""
    try:
        from ..office import engine as E
        from ..office import teamjobs
        if E._paper:
            ids = {p.get("bot_id") for p in teamjobs.pipeline() if p["stage"] in ("demo", "candidate", "live")}
            for bid in ids:
                b = E._paper.bots.get(bid)
                if not b or not b.sim.trades:
                    continue
                eq = b.initial_equity
                for t in b.sim.trades:
                    rets.append(t.pnl / eq if eq > 0 else 0)
                    eq += t.pnl
                first = min(t.entry_time for t in b.sim.trades)
                days = max(days, (b.sim.trades[-1].exit_time - first) / 86400)
            if len(rets) >= 20:
                label = f"데모 봇 실제 거래 {len(rets)}건 (실제 시세 · 수수료·펀딩 포함)"
    except Exception:  # noqa: BLE001
        rets = []
    if len(rets) < 20:
        try:
            from . import copilot
            sig = [s for s in copilot.signals_for(limit=400).get("items", []) if s["outcome"].get("status") in ("take", "stop")]
            if len(sig) >= 20:
                rets = [0.01 * float(s["outcome"]["r"]) for s in sig]   # 1R = 자본 1% 로 걸었다고 보고
                ts = [s["outcome"].get("closed_at") or 0 for s in sig]
                days = max(1.0, (max(ts) - min(ts)) / 86400)
                label = f"AI 시그널 채점 {len(sig)}건 (1R = 자본 1% 로 환산)"
        except Exception:  # noqa: BLE001
            pass
    if len(rets) < 20:
        return {"label": ASSUMED["label"], "returns": _assumed_returns(), "per_day": ASSUMED["per_day"], "assumed": True}
    per_day = len(rets) / days if days >= 1 else 3.0
    return {"label": label, "returns": rets, "per_day": round(min(max(per_day, 0.2), 30), 2), "assumed": False}


def _stats(rets: list[float]) -> dict:
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r <= 0]
    gl = sum(losses)
    return {"n": len(rets), "win_pct": round(len(wins) / len(rets) * 100, 1), "mean_pct": round(sum(rets) / len(rets) * 100, 3),
            "pf": round(sum(wins) / gl, 2) if gl > 0 else None, "worst_pct": round(min(rets) * 100, 2), "best_pct": round(max(rets) * 100, 2)}


def kelly(rets: list[float]) -> dict:
    """장기 성장(로그 자산)이 가장 빠른 베팅 배수 k — 한 번이라도 1 + k·r ≤ 0 이면 그 배수는 파산."""
    worst = min(rets)
    k_max = (-0.999 / worst) if worst < 0 else 100.0
    best_k, best_g = 0.0, 0.0
    k = 0.05
    while k <= min(k_max, 100):
        g = sum(math.log(1 + k * r) for r in rets) / len(rets)
        if g > best_g:
            best_k, best_g = k, g
        k = round(k * 1.08 + 0.01, 4)
    return {"k": round(best_k, 2), "growth_per_trade_pct": round(best_g * 100, 4), "k_ruin": round(k_max, 2)}


def simulate(rets: list[float], per_day: float, start: float, target: float, days: int, scale: float,
             sims: int = 3000, seed: int = 7) -> dict:
    rng = random.Random(seed)
    n_trades = max(1, int(round(per_day * days)))
    goal, floor = target / start, RUIN
    reached, ruined, finals, hit_days = 0, 0, [], []
    for _ in range(sims):
        e = 1.0
        for i in range(n_trades):
            e *= 1 + scale * rets[rng.randrange(len(rets))]
            if e <= floor:
                ruined += 1
                e = max(e, 0.0)
                break
            if e >= goal:
                reached += 1
                hit_days.append((i + 1) / per_day)
                break
        finals.append(e)
    finals.sort()
    q = lambda p: finals[min(len(finals) - 1, int(p * len(finals)))] * start  # noqa: E731
    return {"scale": scale, "p_target": round(reached / sims * 100, 2), "p_ruin": round(ruined / sims * 100, 1),
            "median": round(q(.5)), "p10": round(q(.1)), "p90": round(q(.9)),
            "median_days_to_target": round(sorted(hit_days)[len(hit_days) // 2], 1) if hit_days else None}


def analyze(start: float = 100_000, target: float = 100_000_000, days: int = 30, base_leverage: float = 3.0,
            sims: int = 3000, src: dict | None = None) -> dict:
    if start <= 0 or target <= start or not (1 <= days <= 3650):
        raise ValueError("시작 금액 > 0, 목표 > 시작, 기간 1~3650일")
    src = src or sources()
    raw, per_day = src["returns"], src["per_day"]
    st = _stats(raw)
    # 급변 갭(손절이 밀리는 경우)을 섞어 넣는다 — 레버리지가 클수록 이 한 번이 계좌를 끝낸다
    worst = min(min(raw), -0.005)
    rets = raw + [worst * TAIL["mult"]] * max(1, len(raw) // TAIL["every"])
    kl = kelly(rets)
    rows = [{**simulate(rets, per_day, start, target, days, k, sims), "leverage": round(base_leverage * k, 1),
             "over_limit": base_leverage * k > MAX_LIVE_LEV} for k in SCALES]
    best = max(rows, key=lambda r: (r["p_target"], -r["p_ruin"]))
    half = min(kl["k"] / 2, MAX_LIVE_LEV / base_leverage)          # 절반 켈리 · 실거래 레버리지 한도 안
    g_day = sum(math.log(1 + half * r) for r in rets) / len(rets) * per_day if half > 0 else 0
    need = math.log(target / start)
    realistic_days = need / g_day if g_day > 0 else None
    tm = target_math(start, target, days)
    if st["mean_pct"] <= 0 or kl["k"] <= 0:
        verdict = "이 성적은 기대값이 0 이하라 어떤 레버리지로도 장기적으로 돈이 줄어듭니다. 레버리지를 올리면 더 빨리 잃을 뿐입니다."
    elif best["p_target"] < 1:
        verdict = (f"{days}일 안 목표 달성 확률은 어떤 베팅 크기에서도 1% 미만입니다 (가장 높은 경우 {best['p_target']}%, 그때 파산 확률 {best['p_ruin']}%). "
                   "레버리지를 올릴수록 파산 확률이 먼저 올라갑니다.")
    else:
        verdict = (f"가장 높은 달성 확률은 {best['p_target']}% (지금의 {best['scale']}배 베팅 · 레버리지 약 {best['leverage']}배)지만 그때 파산 확률이 {best['p_ruin']}%입니다. "
                   "과거 성적이 미래에 그대로 나온다는 가정이라 실제로는 더 낮습니다.")
    path = (f"절반 켈리(지금의 {half:.2f}배 베팅)로 꾸준히 하면 목표까지 중앙값 약 {realistic_days:,.0f}일(약 {realistic_days / 30:.0f}개월)"
            if realistic_days else "이 성적으로는 목표에 닿는 현실적인 경로가 없습니다")
    if src["assumed"]:
        verdict += (" ※ 근거 성적은 '꽤 좋은 전략'을 가정한 숫자입니다. 연구 결과 약 3,500개 셋업 중 검증 구간을 통과한 것은 0개였으니, "
                    "데모에서 실제로 이 정도 성적이 확인되기 전에는 이 경로도 장담할 수 없습니다.")
    return {"math": tm, "tail": f"급변 갭 가정: {TAIL['every']}번에 한 번 최악 손실의 {TAIL['mult']:.0f}배", "source": {"label": src["label"], "assumed": src["assumed"], "per_day": per_day, **st}, "kelly": {**kl, "half": round(half, 2)},
            "rows": rows, "best": best, "verdict": verdict, "realistic_days": round(realistic_days) if realistic_days else None, "path": path,
            "base_leverage": base_leverage, "sims": sims,
            "notes": ["실거래 안전장치(레버리지 최대 20배 · 하루 손실 한도 · 사람 승인)는 이 계산과 상관없이 그대로입니다.",
                      "몬테카를로는 과거 거래를 무작위로 다시 뽑은 것이라 미래 수익을 보장하지 않습니다. 슬리피지·급변 갭은 더 나쁩니다."]}


def text(a: dict) -> str:
    m, s, k = a["math"], a["source"], a["kelly"]
    lines = [f"[목표 현실 점검] {m['text']}", f"- 근거 성적: {s['label']} · 거래당 평균 {s['mean_pct']:+.3f}% · 승률 {s['win_pct']}% · 손익비 {s['pf']} · 하루 {s['per_day']}번",
             f"- {a['tail']}",
             f"- 켈리 최적 베팅: 지금의 {k['k']}배 (이 배수의 {k['k_ruin']}배를 넘으면 한 번의 최악 거래로 파산)"]
    for r in a["rows"]:
        lines.append(f"  · 베팅 {r['scale']}배(레버리지≈{r['leverage']}배{' · 실거래 한도 초과' if r['over_limit'] else ''}): "
                     f"목표 도달 {r['p_target']}% · 파산 {r['p_ruin']}% · 중앙값 {r['median']:,}원")
    lines += [f"- 판정: {a['verdict']}", f"- 현실 경로: {a['path']}"]
    return "\n".join(lines)
