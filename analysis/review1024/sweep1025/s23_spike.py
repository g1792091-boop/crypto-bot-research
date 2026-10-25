"""New method 8 (10/25 night): trade the minute after a spike. A spike = the coin's 5-minute move (close of the last
closed minute vs 5 minutes before) beyond a threshold (BTC 1 / 1.5 / 2 %, alts 1.5 / 2.5 / 3.5 %); after one spike the
coin is skipped 30 minutes. Enter at the next minute's open, FADE (against the move: liquidation overshoot) or FOLLOW
(with it), fixed rules (BTC 40x / alts 30x, margin 40 %), exits: stop ROE -50 % / take profit ROE +50 %, stop -75 % /
take profit +100 %, stop -35 % / small ladder 6->4, stop -50 % / ladder 12->10. Costs: DeepCoin round trip 0.14 % and
0.08 % (after the owners' payback). Pick on 2020-03 .. 2023-12, read 2024-01 .. 2026-10 (never used to pick); one
position across the coins; coin-flip sides on the same entries."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/hunt1025")
sys.path.insert(0, "/home/user/crypto-bot-research")
import hb_build as HB                                    # noqa: E402
from common import COINS, MIN, ms, grid, bars, T0 as GT0  # noqa: E402
from paperbot.rmember import regimes                     # noqa: E402

T00 = time.time()
A = ms("2020-03-01"); Z = ms("2026-10-24 14:12"); SPLIT = ms("2024-01-01"); KST = 9 * 3600 * 1000; DAY = 86_400_000


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


b4 = bars("BTCUSDT", "4h")
REG, _ = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
B4C = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000

O, H, L, C, OFF = [], [], [], [], [0]
EV = []                                                   # (coin, minute index of entry, move sign, threshold level)
TH = {"BTCUSDT": (0.01, 0.015, 0.02)}
for ci, cn in enumerate(COINS):
    g = grid(cn)
    O.append(g["o"]); H.append(g["h"]); L.append(g["l"]); C.append(g["c"]); OFF.append(OFF[-1] + g["n"])
    lc = np.log(np.where(g["c"] > 0, g["c"], np.nan))
    r5 = lc - np.r_[np.full(5, np.nan), lc[:-5]]
    ths = TH.get(cn, (0.015, 0.025, 0.035))
    for lev_i, th in enumerate(ths):
        idx = np.flatnonzero(np.abs(np.nan_to_num(r5)) >= th)
        keep = []; last = -10 ** 9
        for i in idx:
            if i - last >= 30:
                keep.append(i); last = i
        keep = np.array(keep, np.int64)
        e = keep + 1                                      # entry at the next minute's open
        t = GT0 + e * MIN
        ok = (t >= A) & (t < Z) & (e < g["n"] - 1)
        EV.append(np.c_[np.full(ok.sum(), ci), e[ok], np.sign(r5[keep[ok]]).astype(int), np.full(ok.sum(), lev_i)])
    log(cn, "spikes", [int((np.abs(np.nan_to_num(r5)) >= th).sum()) for th in ths])
EV = np.concatenate(EV).astype(np.int64)
o = np.concatenate(O); h = np.concatenate(H); l = np.concatenate(L); cl = np.concatenate(C); off = np.array(OFF)
del O, H, L, C
ci_ = EV[:, 0]; e = EV[:, 1]; mv = EV[:, 2]; lvl = EV[:, 3]
t = GT0 + e * MIN
start = off[ci_] + e; send = off[ci_ + 1]
good = np.isfinite(o[start])
lev = HB.LEVC[ci_]
j = np.searchsorted(B4C, t, side="right") - 1; reg = np.where(j >= 0, REG[np.clip(j, 0, None)], 2)
log("events", len(EV), "by level", [int((lvl == k).sum()) for k in range(3)])

EXN = ["손절-50%·익절+50%", "손절-75%·익절+100%", "손절-35%·작은계단6→4", "손절-50%·계단12→10"]
sk = np.array([1, 1, 1, 1], np.int8); sv = np.array([0.5, 0.75, 0.35, 0.5])
tk = np.array([1, 1, 0, 0], np.int8); tv = np.array([0.5, 1.0, 0.0, 0.0])
LAD = ["none", "none", "tight", "house"]
lg = np.array([HB.LADS[x][0] for x in LAD]); ll = np.array([HB.LADS[x][1] for x in LAD])
ls = np.array([max(HB.LADS[x][2], 1e-9) for x in LAD])
atrf = np.full(len(EV), 0.01)
st2 = np.where(good, start, 0)
RES = {}
for cost in (0.0014, 0.0008):
    for mode, sd in (("FADE", -mv), ("FOLLOW", mv)):
        W, K, _ = HB.walk_all(o, h, l, cl, st2, send, sd.astype(np.int8), lev, atrf, sk, sv, tk, tv, lg, ll, ls, cost,
                              HB.MARGIN, HB.MAXK)
        W[~good] = np.nan
        RES[(cost, mode)] = (W, K)
    rng = np.random.default_rng(5); fs = np.where(rng.random(len(EV)) < 0.5, mv, -mv)
    W, K, _ = HB.walk_all(o, h, l, cl, st2, send, fs.astype(np.int8), lev, atrf, sk, sv, tk, tv, lg, ll, ls, cost,
                          HB.MARGIN, HB.MAXK)
    W[~good] = np.nan
    RES[(cost, "COIN")] = (W, K)
log("walks done")


def one_pos(m, W, K):
    ii = np.flatnonzero(m & np.isfinite(W)); ii = ii[np.argsort(t[ii], kind="stable")]
    keep = []; free = -1
    for i in ii:
        if t[i] >= free:
            keep.append(i); free = t[i] + int(K[i]) * MIN
    return np.array(keep, np.int64)


def read(idx, w):
    tt = t[idx]; d = pd.to_datetime(tt + KST, unit="ms"); ym = (d.year * 100 + d.month).to_numpy(); yr = d.year.to_numpy()
    hit = bust = mon = 0
    for k in np.unique(ym):
        if k >= 202610:
            continue
        mon += 1; eq = 1.0
        for v in w[ym == k]:
            eq *= 1 + v
            if eq >= 5:
                hit += 1; break
            if eq <= 0.5:
                bust += 1; break
    return {"거래": len(idx), "거래당": round(float(w.mean()), 4) if len(w) else None,
            "해별": {str(y): round(float(w[yr == y].mean()), 4) for y in range(2020, 2027) if (yr == y).any()},
            "장세별(상승/하락/횡보)": [round(float(w[reg[idx] == g].mean()), 4) if (reg[idx] == g).any() else None for g in (0, 1, 2)],
            "x5달": hit, "-50%달": bust, "달": mon}


out = {}
for cost in (0.0014, 0.0008):
    for mode in ("FADE", "FOLLOW", "COIN"):
        W, K = RES[(cost, mode)]
        for x in range(len(EXN)):
            for lv in range(3):
                m = lvl >= lv
                sel_a = m & (t < SPLIT); sel_b = m & (t >= SPLIT)
                ia = one_pos(sel_a, W[:, x], K[:, x]); ib = one_pos(sel_b, W[:, x], K[:, x])
                ra = read(ia, W[ia, x].astype(float)); rb = read(ib, W[ib, x].astype(float))
                key = f"왕복 {cost*100:.2f}% / {mode} / {EXN[x]} / 급등락 {lv + 1}단계 이상"
                out[key] = {"2020~23 (고르는 기간)": ra, "2024~26 (확인)": rb}
                if mode != "COIN":
                    log(key, "| pick", ra["거래당"], ra["거래"], "| check", rb["거래당"], rb["거래"], "x5", rb["x5달"], "-50", rb["-50%달"],
                        "yrs", rb["해별"], "reg", rb["장세별(상승/하락/횡보)"])
json.dump(out, open(os.path.join(OUTD, "spike23.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
