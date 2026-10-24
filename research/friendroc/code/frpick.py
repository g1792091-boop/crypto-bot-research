"""After PREREG / PREREG2 / PREREG3 / PREREG4 (no new pre-registration: a side-by-side read for the owners' choice of 10/24,
"월요일부터 친구 매매법으로 실거래, 그나마 목표에 가까운 조합"). Every candidate here was already computed in those studies;
choosing among them after seeing their numbers is a choice, not a test. 30x, cost 0.124 % round trip, one position, the entry
blocks; margin 40 % and 20 %.

    python3 -I frrun.py build     (once)
    python3 -I frpick.py          -> research/friendroc/results5.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import ROWS, take, rnd
from frloss import coin_features, PER, LEV
from frfamily import signals, outcomes, filt
from frp30 import weekdays

QS = np.round(np.arange(0.1, 0.91, 0.1), 1)
MARGINS = (0.40, 0.20)


def read(R, O, use):
    t = R.t.to_numpy(np.int64)
    out = {}
    for pn, (a, z) in list(PER.items()):
        idx = take(t, O["k"], use & (t >= a) & (t < z))
        roe = LEV * O["r"][idx]
        win = roe > 0
        n = len(idx)
        months = (z - a) / DAY / 30.44
        streak = run = 0
        for w in win:
            run = 0 if w else run + 1
            streak = max(streak, run)
        d = {"n": n, "per_weekday": rnd(n / weekdays(a, z), 2), "per_month": rnd(n / months, 1), "win": rnd(win.mean(), 4),
             "avg_win_pct": rnd(roe[win].mean() * 100, 1), "avg_loss_pct": rnd(roe[~win].mean() * 100, 1),
             "roe_pct": rnd(roe.mean() * 100, 2), "gross_roe_pct": rnd((roe.mean() + LEV * COSTS["c042"]) * 100, 2),
             "longest_losing_run": int(streak), "hold_min_median": int(np.median(O["k"][idx] + 1))}
        for m in MARGINS:
            x = np.maximum(m * roe, -1.0)
            eq = np.cumprod(1 + x)
            d[f"m{int(m * 100)}"] = {"mult": rnd(eq[-1], 3), "maxdd": rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3),
                                     "month_avg_pct": rnd(m * roe.mean() * 100 * n / months, 1)}
        out[pn] = d
    # months from 1 (KST month of the entry), 2020-03 .. 2026-09 and 2025-01 .. 2026-09
    idx = take(t, O["k"], use & (t >= ms("2020-03-01")))
    mon = np.asarray(pd.to_datetime(t[idx] + KST, unit="ms").strftime("%Y-%m"))
    roe = LEV * O["r"][idx]
    for m in MARGINS:
        x = np.maximum(m * roe, -1.0)
        mult = {q: float(np.prod(1 + x[mon == q])) for q in pd.period_range("2020-03", "2026-10", freq="M").strftime("%Y-%m")}
        for nm, lo in (("months_all", "2020-03"), ("months_2025", "2025-01")):
            v = np.array([val for q, val in mult.items() if lo <= q <= "2026-09"])
            out[f"{nm}_m{int(m * 100)}"] = {"n": int(len(v)), "median": rnd(np.median(v), 3), "up": rnd((v > 1).mean(), 3),
                                            "x2": int((v >= 2).sum()), "x4": int((v >= 4).sum()), "half_or_less": int((v <= 0.5).sum()),
                                            "worst": rnd(v.min(), 3)}
    return out


def main():
    A = pd.read_pickle(ROWS)
    A = A[A.P & (A.block == "")].reset_index(drop=True)
    F = pd.concat([coin_features(COINS[ci], A[A.coin == ci]) for ci in range(6)]).loc[A.index]
    R15 = signals("15m")
    R15 = R15[R15.block == ""].reset_index(drop=True)
    assert (R15.t.to_numpy() == A.t.to_numpy()).all() and (R15.side.to_numpy() == A.side.to_numpy()).all()
    t = A.t.to_numpy(np.int64)
    sel = (t >= PER["select"][0]) & (t < PER["select"][1])
    # PREREG3's pair pick, its cuts recomputed as frdeep.py does (10 % .. 90 % positions of the 2020-03 .. 2024-12 candidates)
    c52 = np.nanquantile(F.d_e52_atr.to_numpy(float)[sel], QS)[1]          # 20 %
    cvr = np.nanquantile(R15.vr.to_numpy(float)[sel], QS)[3]               # 40 %
    print("cuts", c52, cvr, flush=True)
    base = {"r": A.L30_c042_own_r.to_numpy(), "k": A.L30_c042_own_k.to_numpy(), "why": A.L30_c042_own_why.to_numpy()}
    with np.errstate(invalid="ignore"):
        quiet = ~(R15.vr.to_numpy() > cvr)
        far52 = ~(F.d_e52_atr.to_numpy() < c52)
    R4 = signals("4h")
    R4 = R4[R4.block == ""].reset_index(drop=True)
    cands = {
        "P 친구 그대로(15분)": (A, base, np.ones(len(A), bool)),
        "15분 + 4시간 ADX 20 미만 금지": (A, base, filt(R15, "F4")),
        "15분 + 조용한 봉만": (A, base, quiet),
        "15분 + 조용한 봉 + EMA52에서 떨어짐": (A, base, quiet & far52),
        "4시간봉 + ADX 필터 · 손절 -50% · 계단 10/5": (R4, outcomes(R4, -0.50, 0.10, 0.05)["own"], filt(R4, "F4")),
        "4시간봉 + ADX 필터 · 손절 -75% · 계단 10/5": (R4, outcomes(R4, -0.75, 0.10, 0.05)["own"], filt(R4, "F4")),
        "4시간봉 + ADX 필터 · 손절 -90% · 계단 10/5": (R4, outcomes(R4, -0.90, 0.10, 0.05)["own"], filt(R4, "F4")),
        "4시간봉 + ADX 필터 · 손절 -90% · 계단 30/10": (R4, outcomes(R4, -0.90, 0.30, 0.10)["own"], filt(R4, "F4")),
    }
    res = {"cuts": {"d_e52_atr_min": rnd(c52, 4), "vol_ratio_max": rnd(cvr, 4)}, "candidates": {}}
    for nm, (R, O, use) in cands.items():
        x = read(R, O, use)
        res["candidates"][nm] = x
        s, c, o, l = x["select"], x["confirm"], x["oct2026"], x["last19"]
        print(f"{nm:34s} sel {s['n']} w{s['win']} {s['roe_pct']} | conf {c['n']} w{c['win']} {c['roe_pct']} aw{c['avg_win_pct']} al{c['avg_loss_pct']} "
              f"{c['per_weekday']}/d mo40 {c['m40']['month_avg_pct']} | oct {o['n']} w{o['win']} x{o['m40']['mult']} dd{o['m40']['maxdd']} | 19d x{l['m40']['mult']}", flush=True)
        print("     months all", x["months_all_m40"], "| 2025", x["months_2025_m40"], "| 2025 m20", x["months_2025_m20"], "| streak", c["longest_losing_run"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results5.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
