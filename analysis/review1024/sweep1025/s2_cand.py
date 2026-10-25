"""Sweep 2 candidates: the configs with the most x5 months over 2020-03 .. 2026-09 (distinct cells), the October 5-member
bot with bold exits, and merged bots. Each read: x5 within 30 days from every start day (2020-25, 2026 Jan-Sep), the
forward 19 days, and the same config with coin-flip directions (3 seeds). Writes out/cand.json."""
import os, sys, json
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import s2_members as SM                                  # noqa: E402
from common import ms                                    # noqa: E402

M = np.load(os.path.join(OUTD, "meta.npz")); FN, XN, CELLS, SETS = M["FN"], M["XN"], M["cells"], M["sets"]
MODES = np.array(["양방향", "숏만", "롱만"])
R = np.load(os.path.join(OUTD, "R_real.npy")).astype(np.float32)
act, hit, act6, hit6, fx, fn = R[..., 1], R[..., 2], R[..., 4], R[..., 5], np.exp(R[..., 8]), R[..., 11]
tot = np.where(act + act6 >= 40, (hit + hit6) / np.maximum(act + act6, 1), -1)
o = np.argsort(-tot.ravel())
picks, seen = [], set()
for j in o:
    c, f, m, x = np.unravel_index(j, tot.shape)
    if CELLS[c] in seen:
        continue
    seen.add(CELLS[c]); picks.append((CELLS[c], FN[f], MODES[m], int(x), float(tot[c, f, m, x]), float(fx[c, f, m, x]), int(fn[c, f, m, x])))
    if len(picks) >= 12:
        break
BOLD = XN.tolist().index("손절 ROE -75% · 익절 ROE +100% · 계단 없음")
LADDER = {"ROE -75": XN.tolist().index("손절 ROE -75% · 익절 없음 · 계단 12→10 / 5"),
          "ROE -50": XN.tolist().index("손절 ROE -50% · 익절 없음 · 계단 12→10 / 5"),
          "1ATR": XN.tolist().index("손절 1ATR · 익절 없음 · 계단 12→10 / 5")}
OCT5 = [("V39_ALL@15m", "none", "숏만", LADDER["ROE -75"]), ("S6_EMA_DMI_ADX@15m", "none", "숏만", LADDER["ROE -50"]),
        ("F12_MSS@1h", "none", "숏만", LADDER["ROE -75"]), ("N12_ICHI_AO@30m", "none", "양방향", LADDER["ROE -75"]),
        ("F16_FIB382@4h", "none", "양방향", LADDER["1ATR"])]
BOTS = {f"1위 하나: {p[0]} · {p[1]} · {p[2]} · {XN[p[3]]}": [p[:4]] for p in picks[:5]}
BOTS["상위 3개 합침"] = [p[:4] for p in picks[:3]]
BOTS["상위 5개 합침"] = [p[:4] for p in picks[:5]]
BOTS["10월 5개 봇 (계단)"] = OCT5
BOTS["10월 5개 봇, 청산만 크게 (ROE -75% / +100%)"] = [(c, f, m, BOLD) for c, f, m, _ in OCT5]


def read(mems, seed=None):
    T = SM.H.merge([SM.trades(*mm, flip_seed=seed) for mm in mems])
    g25 = SM.roll(T, ms("2020-03-01"), ms("2025-12-02")); g26 = SM.roll(T, ms("2026-01-01"), ms("2026-09-25"))
    g26b = SM.roll(T, ms("2026-01-01"), ms("2026-09-25"), floor=0.7)
    g10 = SM.roll(T, ms("2020-03-01"), ms("2026-09-25"), goal=10.0); g15 = SM.roll(T, ms("2020-03-01"), ms("2026-09-25"), goal=15.0)
    return {"2020~25 30일 x5/-50%": [round(v, 3) for v in g25], "2026 30일 x5/-50%": [round(v, 3) for v in g26],
            "2026 30일 x5/-30%": [round(v, 3) for v in g26b], "2020~26 30일 x10/-50%": [round(v, 3) for v in g10],
            "2020~26 30일 x15/-50%": [round(v, 3) for v in g15], "19일": {k: round(v, 3) for k, v in SM.forward(T).items()},
            "달": SM.months(T), "거래": len(T), "승률": round(float((T.w > 0).mean()), 3)}


out = {"picks": [dict(cell=p[0], filt=p[1], mode=p[2], exit=XN[p[3]], goal_month_rate=round(p[4], 3), fwd=round(p[5], 2),
                      fwd_n=p[6]) for p in picks]}
for lab, mems in BOTS.items():
    r = read(mems)
    r["동전"] = [read(mems, s) for s in (11, 12, 13)]
    out[lab] = r
    print(lab, {k: v for k, v in r.items() if k != "동전"}, flush=True)
    print("   동전:", [(d["2026 30일 x5/-50%"], d["2020~25 30일 x5/-50%"], d["19일"]["x"]) for d in r["동전"]], flush=True)
json.dump(out, open(os.path.join(OUTD, "cand.json"), "w"), ensure_ascii=False, indent=1, default=float)
