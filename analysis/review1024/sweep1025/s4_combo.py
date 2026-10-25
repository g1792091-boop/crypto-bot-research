"""Sweep 4: the October 5-member bot (A, ladder exits) and the regime bot picked on 2020-25 (B, fixed take-profits,
each member only in its BTC 4h regime), alone and merged in one position, with A gated to regimes. Read: forward 19 days,
x5 / x10 / x15 within 30 days from every start day (2026 Jan-Sep, 2020-25), 2026 months, and coin-flip directions."""
import os, sys, json
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import s2_members as SM                                  # noqa: E402
from common import ms, bars                              # noqa: E402
sys.path.insert(0, "/home/user/crypto-bot-research")
from paperbot.rmember import regimes                     # noqa: E402

b4 = bars("BTCUSDT", "4h")
REG, _ = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
CLOSE = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000


def reg_at(t):
    j = np.searchsorted(CLOSE, t, side="right") - 1
    return np.where(j >= 0, REG[np.clip(j, 0, None)], 2)


X = {n: i for i, n in enumerate(SM.XN)}
L75, L50, L1A = X["손절 ROE -75% · 익절 없음 · 계단 12→10 / 5"], X["손절 ROE -50% · 익절 없음 · 계단 12→10 / 5"], X["손절 1ATR · 익절 없음 · 계단 12→10 / 5"]
T3A, A2T3, T100 = X["손절 ROE -75% · 익절 3ATR · 계단 없음"], X["손절 2ATR · 익절 3ATR · 계단 없음"], X["손절 ROE -75% · 익절 ROE +100% · 계단 없음"]
# (cell, judge, mode, exit, regimes allowed: None = all; 0 up, 1 down, 2 range)
A = [("V39_ALL@15m", "none", "숏만", L75, None), ("S6_EMA_DMI_ADX@15m", "none", "숏만", L50, None),
     ("F12_MSS@1h", "none", "숏만", L75, None), ("N12_ICHI_AO@30m", "none", "양방향", L75, None),
     ("F16_FIB382@4h", "none", "양방향", L1A, None)]
B = [("F9_OB@4h", "none", "롱만", T3A, (0,)), ("F16_FIB618@4h", "none", "롱만", T3A, (0,)),
     ("N05_PSAR_POC@1h", "none", "숏만", A2T3, (1,)), ("F5_BOX_HTF@15m", "none", "숏만", T100, (1,)),
     ("F1_RSI_DIV@4h", "none", "양방향", T3A, (2,)), ("F11_TSOUP@4h", "none", "숏만", T3A, (2,))]


def gate(mems, regs):
    return [(c, f, m, x, regs) for c, f, m, x, _ in mems]


BOTS = {
    "A 10월 5개 (계단)": A,
    "A, 하락장에서만": gate(A, (1,)),
    "A, 상승장 빼고": gate(A, (1, 2)),
    "B 장세별 6개 (고정 익절)": B,
    "A + B": A + B,
    "B 상승·횡보 + A 하락장": [m for m in B if m[4] != (1,)] + gate(A, (1,)),
    "B 전체 + A 하락장": B + gate(A, (1,)),
}


def trades(mems, seed):
    T = []
    for c, f, m, x, regs in mems:
        tr = SM.trades(c, f, m, x, flip_seed=seed)
        if regs is not None:
            tr = tr[np.isin(reg_at(tr.t.to_numpy()), regs)]
        T.append(tr)
    return SM.H.merge(T)


def read(T):
    out = {"19일": {k: round(v, 3) for k, v in SM.forward(T).items()}}
    for g in (5.0, 10.0, 15.0):
        out[f"2026 시작 30일 x{g:g}/-50%"] = [round(v, 3) for v in SM.roll(T, ms("2026-01-01"), ms("2026-09-25"), goal=g)]
    out["2026 시작 30일 x5/-30%"] = [round(v, 3) for v in SM.roll(T, ms("2026-01-01"), ms("2026-09-25"), floor=0.7)]
    out["2020~25 시작 30일 x5/-50%"] = [round(v, 3) for v in SM.roll(T, ms("2020-03-01"), ms("2025-12-02"))]
    d = pd.to_datetime(T.t + 9 * 3600 * 1000, unit="ms"); k = (d.dt.year * 100 + d.dt.month).to_numpy()
    m26 = (k >= 202601) & (k <= 202610)
    out["2026 월별"] = {int(q): round(float(np.prod(1 + T.w.to_numpy()[k == q])), 2) for q in np.unique(k[m26])}
    w26 = T.w.to_numpy()[(T.t.to_numpy() >= ms("2026-01-01")) & (T.t.to_numpy() < SM.FWD_A)]
    out["2026 1~9월 거래당"] = round(float(w26.mean()), 4) if len(w26) else None
    out["2026 1~9월 거래/달"] = round(len(w26) / 9, 1)
    return out


res = {}
for lab, mems in BOTS.items():
    r = read(trades(mems, None))
    r["동전"] = [read(trades(mems, s)) for s in (21, 22, 23)]
    res[lab] = r
    print("==", lab, json.dumps({k: v for k, v in r.items() if k != "동전"}, ensure_ascii=False, default=float), flush=True)
    print("   동전 2026 x5/-50%:", [d["2026 시작 30일 x5/-50%"] for d in r["동전"]], " 19일:", [d["19일"]["x"] for d in r["동전"]],
          " 2026 거래당:", [d["2026 1~9월 거래당"] for d in r["동전"]], flush=True)
json.dump(res, open(os.path.join(OUTD, "combo4.json"), "w"), ensure_ascii=False, indent=1, default=float)
