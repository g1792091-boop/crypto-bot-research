"""The what-if lists of the V3.9 1h study, shared by window.py (27 paper trades, 1m bars) and fiveyear.py (5 years,
5m bars). Ladder names follow the owners' words: "12/10" = at +12% net ROE the stop locks +10%, then 5% steps."""
from __future__ import annotations

from sim import Variant as V

BASE = V("now", "지금 (12/10, 5%씩, 손절 2ATR)")

TP = [
    BASE,
    V("L15/12", "15/12", first_lock=0.12, gap=0.03),
    V("L20/15", "20/15", first_lock=0.15, gap=0.05),
    V("L25/20", "25/20", first_lock=0.20, gap=0.05),
    V("L30/25", "30/25", first_lock=0.25, gap=0.05),
    V("L40/30", "40/30", first_lock=0.30, gap=0.10),
    V("L20/10", "20/10 (잠금 간격 10%)", first_lock=0.10, gap=0.10),
    V("L30/20", "30/20 (잠금 간격 10%)", first_lock=0.20, gap=0.10),
    V("L12/10s2.5", "12/10, 2.5%씩", step=0.025),
    V("L12/10s10", "12/10, 10%씩", step=0.10),
    V("L20/15s10", "20/15, 10%씩", first_lock=0.15, gap=0.05, step=0.10),
    V("trail0.5", "ATR 0.5배 따라가기 (+12%부터, 계단 없음)", ladder=False, trail_k=0.5),
    V("trail1", "ATR 1배 따라가기 (+12%부터, 계단 없음)", ladder=False, trail_k=1.0),
    V("trail1.5", "ATR 1.5배 따라가기 (+12%부터, 계단 없음)", ladder=False, trail_k=1.5),
    V("trail2", "ATR 2배 따라가기 (+12%부터, 계단 없음)", ladder=False, trail_k=2.0),
    V("trail3", "ATR 3배 따라가기 (+12%부터, 계단 없음)", ladder=False, trail_k=3.0),
    V("L+trail1", "12/10 계단 + ATR 1배 따라가기", trail_k=1.0),
    V("roe10", "고정 익절 +10%", ladder=False, tp="ROE", tp_val=0.10),
    V("roe15", "고정 익절 +15%", ladder=False, tp="ROE", tp_val=0.15),
    V("roe20", "고정 익절 +20%", ladder=False, tp="ROE", tp_val=0.20),
    V("roe30", "고정 익절 +30%", ladder=False, tp="ROE", tp_val=0.30),
    V("roe50", "고정 익절 +50%", ladder=False, tp="ROE", tp_val=0.50),
    V("roe100", "고정 익절 +100%", ladder=False, tp="ROE", tp_val=1.00),
    V("tp1R", "고정 익절 1R (손절 거리의 1배)", ladder=False, tp="R", tp_val=1.0),
    V("tp1.5R", "고정 익절 1.5R", ladder=False, tp="R", tp_val=1.5),
    V("tp2R", "고정 익절 2R", ladder=False, tp="R", tp_val=2.0),
    V("tp3R", "고정 익절 3R", ladder=False, tp="R", tp_val=3.0),
    V("L+tp2R", "12/10 계단 + 2R 익절", tp="R", tp_val=2.0),
]

STOPS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
# stop width with the paper trade's own leverage and margin share ("change only the stop")
SL_SAME = [V(f"stop{k:g}_same", f"손절 {k:g} ATR (레버리지 그대로)", stop_atr=k, same_lev=True) for k in STOPS]
# stop width with the rule bot's sizing (a wider stop may lower the leverage or refuse the entry)
SL_RULE = [V(f"stop{k:g}", f"손절 {k:g} ATR (규칙봇 크기 규칙)", stop_atr=k) for k in STOPS]

# the full-grid study's exit set (research/fullgrid/kernel.py TP_RULES x STOPS, the swing take-profits left out:
# they need structure levels): name "<rule>|<k>" as in its default_by_exit.npz
FG_RULES = {
    "ladder": dict(),
    "ladder5": dict(first_lock=0.05),
    "ladder20": dict(first_lock=0.20),
    "roe10": dict(ladder=False, tp="ROE", tp_val=0.10),
    "roe20": dict(ladder=False, tp="ROE", tp_val=0.20),
    "roe30": dict(ladder=False, tp="ROE", tp_val=0.30),
    "roe50": dict(ladder=False, tp="ROE", tp_val=0.50),
    "tp1R": dict(ladder=False, tp="R", tp_val=1.0),
    "tp1.5R": dict(ladder=False, tp="R", tp_val=1.5),
    "tp2R": dict(ladder=False, tp="R", tp_val=2.0),
    "tp3R": dict(ladder=False, tp="R", tp_val=3.0),
    "ladder_tp2R": dict(tp="R", tp_val=2.0),
}
FG = [V(f"{r}|{k:g}", f"{r} · 손절 {k:g}ATR", stop_atr=k, **kw) for k in STOPS for r, kw in FG_RULES.items()]

LEV = [
    V("lev_rule", "지금 규칙 (품질·안전 검사로 20/30배, 증거금 = 배수 %)"),
    V("lev40_30", "BTC 40배·나머지 30배, 증거금 = 배수 % (40%/30%)", lev_btc=40, lev_alt=30),
    V("lev40_30_m40", "BTC 40배·나머지 30배, 증거금 40% 고정", lev_btc=40, lev_alt=30, frac=0.40),
    V("lev_paper_m40", "실제 배수 그대로, 증거금 40% 고정", same_lev=True, frac=0.40),
    V("lev30_m40", "모두 30배, 증거금 40% 고정", lev_btc=30, lev_alt=30, frac=0.40),
    V("lev20_m40", "모두 20배, 증거금 40% 고정", lev_btc=20, lev_alt=20, frac=0.40),
    V("lev50_40_m40", "BTC 50배·나머지 40배, 증거금 40% 고정", lev_btc=50, lev_alt=40, frac=0.40),
]


# Entry timing (market orders only, the owners' rule): (name, label, kind, params)
ENTRY = [
    ("now", "지금 (봉 마감 후 약 30초, 시장가)", "now", {}),
    ("wait5", "5분 기다렸다 시장가", "wait", {"min": 5}),
    ("wait15", "15분 기다렸다 시장가", "wait", {"min": 15}),
    ("wait30", "30분 기다렸다 시장가", "wait", {"min": 30}),
    ("wait60", "1시간 기다렸다 시장가", "wait", {"min": 60}),
    ("wait120", "2시간 기다렸다 시장가", "wait", {"min": 120}),
    ("wait240", "4시간 기다렸다 시장가", "wait", {"min": 240}),
    ("pb0.25_1h", "0.25 ATR 되돌림 닿으면 시장가 (1시간 안)", "pullback", {"x": 0.25, "win": 60}),
    ("pb0.5_1h", "0.5 ATR 되돌림 닿으면 시장가 (1시간 안)", "pullback", {"x": 0.5, "win": 60}),
    ("pb0.5_4h", "0.5 ATR 되돌림 닿으면 시장가 (4시간 안)", "pullback", {"x": 0.5, "win": 240}),
    ("pb1_4h", "1 ATR 되돌림 닿으면 시장가 (4시간 안)", "pullback", {"x": 1.0, "win": 240}),
    ("pb1_12h", "1 ATR 되돌림 닿으면 시장가 (12시간 안)", "pullback", {"x": 1.0, "win": 720}),
    ("conf5m", "5분봉 하나가 신호 방향으로 마감하면 시장가 (1시간 안)", "confirm", {"bar": 5, "win": 60}),
    ("conf15m", "15분봉 하나가 신호 방향으로 마감하면 시장가 (2시간 안)", "confirm", {"bar": 15, "win": 120}),
    ("conf1h", "다음 1시간봉이 신호 방향으로 마감하면 시장가", "confirm", {"bar": 60, "win": 60}),
]
