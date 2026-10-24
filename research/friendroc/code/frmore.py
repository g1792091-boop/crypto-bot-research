"""PREREG6.md: three return ideas against the chosen structure B (15m friend signal + F4 + V, stop net ROE -75 %, ladder 20 / 10,
30x, one position, the entry blocks, TetherMax payback 90 % per trade): finer ladder steps (C1-a 15 / 5, C1-b 20 / 5, C1-c 30 / 5),
a funding-rate crowding filter (C2), and merging the 15m signals with the same rules on 30m (C3-a) and also 4h (C3-b).

    python3 -I frrun.py build     (once)
    python3 -I frmore.py          -> research/friendroc/results9.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take, rnd
from frloss import PER, LEV
from frfamily import signals, outcomes, filt
from frpay import mask, REFUND
from frp30 import weekdays
import hashlib

RF = REFUND["p90"]
MARGINS = (0.10, 0.20, 0.40)
FUND_WINDOW = 9 * 60                                       # minutes: the last funding must be this recent


def read(t, k, r):
    """Per period: trades, win rate, net ROE per trade with the payback, account multiples at the margins."""
    out = {}
    for pn, (a, z) in PER.items():
        idx = take(t, k, (t >= a) & (t < z))
        roe = LEV * r[idx] + RF
        d = {"n": int(len(idx)), "per_weekday": rnd(len(idx) / weekdays(a, z), 2), "win": rnd((roe > 0).mean(), 4),
             "avg_win_pct": rnd(roe[roe > 0].mean() * 100, 1), "avg_loss_pct": rnd(roe[roe <= 0].mean() * 100, 1),
             "roe_pct": rnd(roe.mean() * 100, 3)}
        for m in MARGINS:
            x = np.maximum(m * roe, -1.0)
            eq = np.cumprod(1 + x)
            d[f"m{int(m * 100)}"] = {"mult": rnd(eq[-1], 4), "maxdd": rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3)}
        out[pn] = d
    return out


def funding_side(R):
    """The last funding rate before the entry minute (within FUND_WINDOW), turned to the trade's side (> 0: that side pays)."""
    out = np.full(len(R), np.nan)
    for ci in range(6):
        g = grid(COINS[ci])
        nz = np.flatnonzero(g["fund"] != 0)
        m = (R.coin == ci).to_numpy()
        e = R.e.to_numpy(np.int64)[m]
        j = np.searchsorted(nz, e, side="left") - 1
        ok = (j >= 0) & (e - nz[np.maximum(j, 0)] <= FUND_WINDOW)
        v = np.where(ok, g["fund"][nz[np.maximum(j, 0)]], np.nan)
        out[m] = v * R.side.to_numpy()[m]
    return out


def merged(parts):
    """One queue of several timeframes' kept rows: (t, k, r) sorted by entry time, then the part's order, then coin."""
    t = np.concatenate([p[0].t.to_numpy(np.int64)[p[2]] for p in parts])
    k = np.concatenate([p[1]["k"][p[2]] for p in parts])
    r = np.concatenate([p[1]["r"][p[2]] for p in parts])
    pr = np.concatenate([np.full(int(p[2].sum()), i) for i, p in enumerate(parts)])
    co = np.concatenate([p[0].coin.to_numpy()[p[2]] for p in parts])
    o = np.lexsort((co, pr, t))
    return t[o], k[o], r[o]


def main():
    want = open(os.path.join(RES_DIR, "PREREG6.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG6.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG6.md changed after it was frozen"
    S = {}
    for tf in ("15m", "30m", "4h"):
        R = signals(tf)
        S[tf] = R[R.block == ""].reset_index(drop=True)
    R15 = S["15m"]
    t15 = R15.t.to_numpy(np.int64)
    m15 = mask(R15, "F4+V")
    OB = outcomes(R15, -0.75, 0.20, 0.10)["own"]
    res = {"prereg6_sha256": sha}
    runs = {"B": (t15[m15], OB["k"][m15], OB["r"][m15])}
    for nm, fl in (("C1-a 15/5", 0.15), ("C1-b 20/5", 0.20), ("C1-c 30/5", 0.30)):
        O = outcomes(R15, -0.75, fl, 0.05)["own"]
        runs[nm] = (t15[m15], O["k"][m15], O["r"][m15])
    fs = funding_side(R15)
    sel = (t15 >= PER["select"][0]) & (t15 < PER["select"][1])
    q80 = float(np.nanquantile(fs[sel], 0.8))
    with np.errstate(invalid="ignore"):
        keep = m15 & ~(fs > q80)
    runs["C2 funding"] = (t15[keep], OB["k"][keep], OB["r"][keep])
    res["funding_q80"] = q80
    res["funding_blocked_share"] = {pn: rnd(1 - keep[m15 & (t15 >= a) & (t15 < z)].mean(), 3) for pn, (a, z) in PER.items()}
    R30 = S["30m"]
    O30 = outcomes(R30, -0.75, 0.20, 0.10)["own"]
    p15, p30 = (R15, OB, m15), (R30, O30, mask(R30, "F4+V"))
    runs["C3-a 15m+30m"] = merged([p15, p30])
    R4 = S["4h"]
    O4 = outcomes(R4, -0.50, 0.10, 0.05)["own"]
    runs["C3-b 15m+30m+4h"] = merged([p15, p30, (R4, O4, filt(R4, "F4"))])
    out = {nm: read(*v) for nm, v in runs.items()}
    b = out["B"]
    for nm, d in out.items():
        d["better_than_B"] = bool(nm != "B" and all(d[p]["roe_pct"] > b[p]["roe_pct"] and d[p]["m10"]["mult"] > b[p]["m10"]["mult"]
                                                    for p in ("select", "confirm")))
        print(f"{nm:18s}", " | ".join(f"{p[:4]} n{d[p]['n']} {d[p]['per_weekday']}/d w{d[p]['win']} aw{d[p]['avg_win_pct']} al{d[p]['avg_loss_pct']} "
                                       f"roe{d[p]['roe_pct']} x10 {d[p]['m10']['mult']} x40 {d[p]['m40']['mult']}" for p in PER),
              "| better" if d["better_than_B"] else "", flush=True)
    better = [nm for nm, d in out.items() if d["better_than_B"]]
    res["pick"] = max(better, key=lambda nm: out[nm]["select"]["m10"]["mult"]) if better else "B"
    res["runs"] = out
    print("funding q80", q80, res["funding_blocked_share"], "pick", res["pick"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results9.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
