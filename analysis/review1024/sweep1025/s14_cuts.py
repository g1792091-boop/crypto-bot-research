"""New method 3 (10/25 night): cut the recommended bot's losing buckets with the bot's own off dimensions (config only:
paperbot/rmember.py entry_dims): coin, side, coin x side, 4h block of the KST day, weekday, weekend, BTC 4h trend,
coin 4h trend, 24h momentum, volatility third, funding sign, trend strength (reg5), open-interest 24h change.

Rules fixed before reading 2026 (first run: absolute thresholds cut every bucket, the bot's own mean being below 0
in 2020-25; so relative to the bot's mean in that half). A bucket of a dim is cut when, in BOTH 2020-03..2022-12 and
2023..2025, it has at least NMIN member trades and a mean wallet result below the half's mean - D:
  R1 whole bot, D 1 %      R2 whole bot, D 0.5 %      R3 per member, D 1 %
  R4 one dim only, keep: the buckets at least 0.5 % above the half's mean in both halves (the dim whose kept trades
     have the best 2020-25 mean, at least 30 % of the trades kept)
Then the members' trades without the cut buckets go through the same one-position merge, and are read on 2026 Jan-Sep
(never used to pick), the forward 19 days and 30 days from every start day, alone and with the signal light 20/0.9
(the executor's sizing, s13). Coin flip: the same pipeline on seeded random directions (21, 22, 23). Funding is in the
data through 2026-09 and open interest through 2026-09-28 (none for alts before 2021-12, bucket 3 = unknown, never
cut); in the forward days both are unknown and nothing is cut by them."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
from common import grid, COINS, T0                                # noqa: E402
from paperbot.rmember import ema_sign, regimes as _regs           # noqa: E402
import time as _time
_T00 = _time.time()


def log(*a):
    print(f"[{_time.time() - _T00:7.0f}s]", *a, flush=True)


def _l13(w, n, q):
    """s13_size.light"""
    live = np.ones(len(w), bool)
    if n:
        for i in range(n, len(w)):
            live[i] = (w[i - n:i] > 0).sum() >= q * n - 1e-9
    return live


def _r13(t, w, lv, a, b, mode, floor=0.7, goal=5.0):
    """s13_size.run: one window [a, b) with the executor's sizing (paper qty x a scale fixed at a)."""
    i = np.searchsorted(t, a); P = E = 1.0
    while i < len(t) and t[i] < b:
        if lv[i]:
            r = 1.0 if mode == "ideal" else min(P / E, 1.0 if mode == "cap1" else 2.0)
            E *= 1 + r * w[i]
            if E >= goal:
                return 1, E
            if E <= floor:
                return -1, E
        P *= 1 + w[i]; i += 1
    return 0, E
DAY = 86_400_000; H1 = 3_600_000; H4 = 4 * H1; KST = 9 * H1
NMIN = 40
HALF = ms("2023-01-01"); END_SEL = ms("2026-01-01")
ORDERFLOW = "/home/user/crypto-bot-research/data/orderflow"


def last(close_t, t):
    return np.searchsorted(close_t, t, side="right") - 1


# ---------------------------------------------------------------- per-coin features at any time
FEAT = {}
b4btc = bars("BTCUSDT", "4h")
BT4 = b4btc.ts.to_numpy(np.int64) + H4
BS50C = ema_sign(b4btc.close.to_numpy(), cold=50)
_, REG5 = _regs(b4btc.high.to_numpy(), b4btc.low.to_numpy(), b4btc.close.to_numpy())
for ci, cn in enumerate(COINS):
    b4 = bars(cn, "4h"); b1 = bars(cn, "1h")
    c1 = b1.close.to_numpy(); h1 = b1.high.to_numpy(); l1 = b1.low.to_numpy()
    pc = np.r_[np.nan, c1[:-1]]
    tr = np.maximum(h1 - l1, np.maximum(np.abs(h1 - pc), np.abs(l1 - pc)))
    atrp = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy() / c1
    rank = pd.Series(atrp).rolling(500, min_periods=200).rank(pct=True).to_numpy()
    g = grid(cn); f = np.nan_to_num(g["fund"]); fi = np.flatnonzero(f != 0)
    sym = cn.replace("USDT", "").lower()
    mt = pd.read_csv(f"{ORDERFLOW}/{sym}_metrics_5m.csv.gz", usecols=["create_time", "sum_open_interest"])
    FEAT[ci] = {"t4": b4.ts.to_numpy(np.int64) + H4, "s50": ema_sign(b4.close.to_numpy()),
                "t1": b1.ts.to_numpy(np.int64) + H1, "c1": c1, "rank": rank,
                "ft": T0 + fi.astype(np.int64) * 60000, "fr": f[fi],
                "fund_end": T0 + (fi[-1] + 1) * 60000 + 8 * H1,
                "mt": pd.to_datetime(mt.create_time).astype("int64").to_numpy() // 1_000_000,
                "oi": mt.sum_open_interest.to_numpy(float)}
    log(cn, "features")


def dims(T):
    """Every dim of the bot at each trade's signal/entry time t (one entry minute = signal close, entry 'now')."""
    t = T.t.to_numpy(np.int64); side = T.side.to_numpy(int); coin = T.coin.to_numpy(int)
    hr = ((t + KST) // H1) % 24; dow = (((t + KST) // DAY) + 3) % 7
    out = {"sym": coin, "side": side, "symside": coin * 2 + (side > 0), "hb": hr // 4, "dow": dow,
           "wk": (dow >= 5).astype(int)}
    j = last(BT4, t)
    out["btc"] = ((j >= 0) & (BS50C[np.clip(j, 0, None)] == side)).astype(int)
    out["reg5"] = np.where(j >= 0, REG5[np.clip(j, 0, None)], 4)
    ctr4 = np.zeros(len(t), int); mom = np.zeros(len(t), int); vol = np.ones(len(t), int)
    fund = np.full(len(t), -1); oi = np.full(len(t), 3)
    for ci in range(6):
        m = np.flatnonzero(coin == ci)
        if not len(m):
            continue
        F = FEAT[ci]; tt = t[m]; sd = side[m]
        j4 = last(F["t4"], tt); ctr4[m] = (j4 >= 0) & (F["s50"][np.clip(j4, 0, None)] == sd)
        j1 = last(F["t1"], tt); j0 = last(F["t1"], tt - 24 * H1)
        r = F["c1"][np.clip(j1, 0, None)] / F["c1"][np.clip(j0, 0, None)] - 1
        mom[m] = (j0 >= 0) & (np.sign(r) == sd)
        rk = F["rank"][np.clip(j1, 0, None)]
        vol[m] = np.where(np.isnan(rk), 1, np.where(rk < 1 / 3, 0, np.where(rk < 2 / 3, 1, 2)))
        jf = last(F["ft"], tt); fr = F["fr"][np.clip(jf, 0, None)]
        fund[m] = np.where((jf >= 0) & (tt < F["fund_end"]), (sd * fr > 0).astype(int), -1)
        k1 = last(F["mt"], tt); k0 = last(F["mt"], tt - DAY)
        ok = (k1 >= 0) & (k0 >= 0) & (tt - F["mt"][np.clip(k1, 0, None)] < H1)
        a = F["oi"][np.clip(k1, 0, None)]; b = F["oi"][np.clip(k0, 0, None)]
        with np.errstate(invalid="ignore", divide="ignore"):
            ch = a / b - 1
        ok &= (b > 0) & np.isfinite(ch)
        oi[m] = np.where(ok, np.where(ch < -0.05, 0, np.where(ch > 0.05, 2, 1)), 3)
    out["ctr4"] = ctr4; out["mom24"] = mom; out["vol3"] = vol; out["fund"] = fund; out["oi24"] = oi
    return pd.DataFrame(out)


DIMS = ["sym", "side", "symside", "hb", "dow", "wk", "btc", "ctr4", "mom24", "vol3", "fund", "reg5", "oi24"]
UNKNOWN = {"fund": -1, "oi24": 3}


def pick_cuts(T, D, dd):
    w = T.w.to_numpy(); t = T.t.to_numpy()
    a = (t < HALF); b = (t >= HALF) & (t < END_SEL)
    ba, bb = w[a].mean(), w[b].mean()
    cuts = []
    for d in DIMS:
        v = D[d].to_numpy()
        for x in np.unique(v):
            if UNKNOWN.get(d) == x:
                continue
            ma, mb = a & (v == x), b & (v == x)
            if ma.sum() >= NMIN and mb.sum() >= NMIN and w[ma].mean() < ba - dd and w[mb].mean() < bb - dd:
                cuts.append((d, int(x)))
    return cuts


def pick_keep(T, D, up=0.005, share=0.3):
    """One dim: the buckets clearly above the bot's mean in both halves; cut every other known bucket of it."""
    w = T.w.to_numpy(); t = T.t.to_numpy()
    a = (t < HALF); b = (t >= HALF) & (t < END_SEL); sel = a | b
    ba, bb = w[a].mean(), w[b].mean()
    best = (None, -9.0, [])
    for d in DIMS:
        v = D[d].to_numpy(); good = []
        for x in np.unique(v):
            if UNKNOWN.get(d) == x:
                continue
            ma, mb = a & (v == x), b & (v == x)
            if ma.sum() >= NMIN and mb.sum() >= NMIN and w[ma].mean() > ba + up and w[mb].mean() > bb + up:
                good.append(int(x))
        if not good:
            continue
        k = sel & np.isin(v, good)
        if k.sum() >= share * sel.sum() and w[k].mean() > best[1]:
            best = (d, float(w[k].mean()), [(d, int(x)) for x in np.unique(v) if int(x) not in good
                                              and UNKNOWN.get(d) != x])
    return best[2]


def apply(T, D, cuts):
    keep = np.ones(len(T), bool)
    for d, x in cuts:
        keep &= D[d].to_numpy() != x
    return T[keep]


def member_trades(seed):
    out = []
    for c, f, m, x, regs in gate(A, (1,)):
        tr = SM.trades(c, f, m, x, flip_seed=seed)
        tr = tr[np.isin(reg_at(tr.t.to_numpy()), regs)].reset_index(drop=True)
        out.append((tr, dims(tr)))
    return out


def readout(M):
    t = M.t.to_numpy(); w = M.w.to_numpy()
    y = pd.to_datetime(t + KST, unit="ms").year.to_numpy()
    out = {str(yy): round(float(w[(y == yy) & (t < SM.FWD_A)].mean()), 4) for yy in range(2020, 2027)
           if ((y == yy) & (t < SM.FWD_A)).any()}
    out["거래 2026 1~9월"] = int(((t >= ms("2026-01-01")) & (t < SM.FWD_A)).sum())
    for lab, (n, q) in (("신호등 없음", (0, 0)), ("신호등 20 0.9", (20, 0.9))):
        lv = _l13(w, n, q)
        R = np.array([_r13(t, w, lv, s, s + 30 * DAY, "cap1")[0] for s in range(ms("2026-01-01"), ms("2026-09-25"), DAY)])
        R0 = np.array([_r13(t, w, lv, s, s + 30 * DAY, "cap1")[0] for s in range(ms("2020-03-01"), ms("2025-12-02"), DAY)])
        out[lab] = {"2026 30일 x5/-30%": [round(float((R == 1).mean()), 3), round(float((R == -1).mean()), 3)],
                    "2020~25 30일 x5/-30%": [round(float((R0 == 1).mean()), 3), round(float((R0 == -1).mean()), 3)],
                    "10월19일": round(_r13(t, w, lv, SM.FWD_A, SM.Z, "cap1", floor=0.0, goal=1e9)[1], 2)}
    return out


res = {}
for seed in (None, 21, 22, 23):
    lab = "실제" if seed is None else f"동전{seed}"
    MT = member_trades(seed)
    allT = pd.concat([tr for tr, _ in MT], ignore_index=True); allD = pd.concat([d for _, d in MT], ignore_index=True)
    base = SM.H.merge([tr for tr, _ in MT])
    r = {"기본": readout(base)}
    for rule, (scope, thr) in {"R1 전체 평균-1%": ("all", 0.01), "R2 전체 평균-0.5%": ("all", 0.005),
                               "R3 매매법별 평균-1%": ("mem", 0.01), "R4 한 가지만 남기기": ("keep", 0.005)}.items():
        if scope in ("all", "keep"):
            cuts = pick_cuts(allT, allD, thr) if scope == "all" else pick_keep(allT, allD, thr)
            kept = [apply(tr, d, cuts) for tr, d in MT]
            cut_txt = [f"{d}={x}" for d, x in cuts]
        else:
            kept, cut_txt = [], []
            for (tr, d), mem in zip(MT, gate(A, (1,))):
                cs = pick_cuts(tr, d, thr); kept.append(apply(tr, d, cs))
                cut_txt.append(f"{mem[0]}: " + ",".join(f"{a}={b}" for a, b in cs))
        M = SM.H.merge(kept)
        r[rule] = {"자름": cut_txt, **readout(M)}
    res[lab] = r
    print("==", lab, json.dumps(r, ensure_ascii=False, default=float), flush=True)
json.dump(res, open(os.path.join(OUTD, "cuts14.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
