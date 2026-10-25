"""New method 6b (10/25 night): the learned entry, round 2 (s17 found a direction edge in every regime, coin flip 0).
Bigger models (600 trees, 63 leaves, every 2nd sample), three ladder exits, fixed thresholds and an adaptive one
(the q-quantile of the predictions of the 30 days before), with and without the executor signal light 20/0.9.

Round 1 description:

Every 15m close on the 6 coins (2020-03 .. 2026-10-24) is a sample. Label: the wallet result of a long and of a short
entered at that close (open of the next minute) with the fixed rules (BTC 40x / alts 30x, margin 40 %, cost 0.12 %
round trip), for two exits: E1 stop ROE -75 % / take profit ROE +100 % (the widest bracket, best for x5 months), E2 stop
ROE -75 % / ladder 12->10/5. Features at the close (closed bars only): returns 15m..7d, volatility, ATR %, RSI, EMA
distances, 1d / 7d range position, volume ratio, funding (last, 3-day mean), open interest change 1h / 24h, taker and
long/short ratios, BTC returns / regime / ADX, KST hour and weekday, coin, the 121 coded strategies' long / short signal
counts on the coin over 1h and 4h, and every trend source's state and latch on the last closed 1h and 4h bar (V3.9, OBV,
CMO, Supertrend, ... = the trend judges).

Walk-forward: half-year test blocks 2022-01 .. 2026-10-24; each block's models are trained only on samples ending 3 days
before the block (expanding window, every 3rd sample), one regressor per side x exit. Trading: at each 15m close the
highest predicted result over coins and sides, if above a threshold, one position at a time. Read per threshold: KST
months x5 (before -50 %), x5 months in a row, -50 % months, mean per trade by BTC regime (up / down / range), 2026
30-day starts. Luck: the same entries with a coin-flip side. argv 1 "shuffle": the labels shuffled by month (no signal)."""
import os, sys, time, json
import numpy as np, pandas as pd
import lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/hunt1025")
sys.path.insert(0, "/home/user/crypto-bot-research")
import hb_build as HB                                    # noqa: E402
from hb_common import RD                                 # noqa: E402
from common import COINS, TFS, TF_MIN, MIN, ms, grid, bars, T0 as GT0   # noqa: E402
from paperbot.rmember import regimes, adx14              # noqa: E402

T00 = time.time()
MODE = sys.argv[1] if len(sys.argv) > 1 else "real"
A = ms("2020-03-01"); Z = ms("2026-10-24 14:12"); FWD_A = ms("2026-10-05 15:00")
KST = 9 * 3600 * 1000; DAY = 86_400_000; M15 = 15 * MIN
ORDERFLOW = "/home/user/crypto-bot-research/data/orderflow"
assert RD.T0 == GT0


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


def ema(x, span):
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    a = pd.Series(up).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    b = pd.Series(dn).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    return 100 - 100 / (1 + a / np.maximum(b, 1e-12))


def atrp(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy() / c


def htf_at(tf, T, arrs):
    """values of higher-timeframe bar arrays at the last bar closed by T."""
    b = bars_cache[tf]
    close = b["ts"] + TF_MIN[tf] * MIN
    j = np.searchsorted(close, T, side="right") - 1
    ok = j >= 0; jj = np.clip(j, 0, None)
    return [np.where(ok, a[jj], np.nan) for a in arrs]


# ---------------------------------------------------------------- the 121 strategies' signals (counts per 15m slot)
NM = RD.names()
SIGC = {}
for ci, coin in enumerate(COINS):
    z = RD._sigfile(coin); es_l, es_s = [], []
    for ti, tf in enumerate(TFS):
        n = int(z[f"{tf}_n"]); e0 = int(z[f"{tf}_e0"]); tfm = TF_MIN[tf]
        for sid in NM.sid.to_numpy():
            for lab, out in (("L", es_l), ("S", es_s)):
                key = f"{tf}_{sid}_{lab}"
                if key in z.files:
                    nb = np.flatnonzero(np.unpackbits(z[key])[:n])
                    out.append(e0 + nb.astype(np.int64) * tfm)
    SIGC[ci] = (np.concatenate(es_l), np.concatenate(es_s))
log("signals loaded")

# ---------------------------------------------------------------- BTC context
gb = grid("BTCUSDT")
b4 = bars("BTCUSDT", "4h")
REG, REG5 = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
BADX = adx14(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
B4CLOSE = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000


def btc_at(T):
    j = np.searchsorted(B4CLOSE, T, side="right") - 1; jj = np.clip(j, 0, None)
    return np.where(j >= 0, REG[jj], 2), np.where(j >= 0, REG5[jj], 4), np.where(j >= 0, BADX[jj], np.nan)


# ---------------------------------------------------------------- features and labels per coin
O, H, L, C, OFF = [], [], [], [], [0]
FEATS, META = [], []
FNAMES = None
btc15 = None
for ci, cn in enumerate(COINS):
    g = grid(cn)
    O.append(g["o"]); H.append(g["h"]); L.append(g["l"]); C.append(g["c"]); OFF.append(OFF[-1] + g["n"])
    b15 = bars(cn, "15m"); bars_cache = {"1h": None, "4h": None}
    for tf in ("1h", "4h"):
        b = bars(cn, tf)
        bars_cache[tf] = {"ts": b.ts.to_numpy(np.int64), "h": b.high.to_numpy(), "l": b.low.to_numpy(),
                          "c": b.close.to_numpy(), "v": b.volume.to_numpy()}
    ts = b15.ts.to_numpy(np.int64); T = ts + M15
    c = b15.close.to_numpy(); h = b15.high.to_numpy(); l = b15.low.to_numpy(); v = b15.volume.to_numpy()
    lc = np.log(c)
    F = {}
    for k in (1, 4, 16, 48, 96, 288, 672):
        F[f"ret{k}"] = lc - np.r_[np.full(k, np.nan), lc[:-k]]
    r1 = np.r_[np.nan, np.diff(lc)]
    F["sd16"] = pd.Series(r1).rolling(16).std().to_numpy(); F["sd96"] = pd.Series(r1).rolling(96).std().to_numpy()
    F["atr15"] = atrp(h, l, c); F["rsi15"] = rsi(c)
    for sp in (20, 50, 200):
        F[f"ema{sp}"] = c / ema(c, sp) - 1
    for nwin, lab in ((96, "1d"), (672, "7d")):
        hi = pd.Series(h).rolling(nwin).max().to_numpy(); lo = pd.Series(l).rolling(nwin).min().to_numpy()
        F[f"pos{lab}"] = (c - lo) / np.maximum(hi - lo, 1e-12)
    F["vratio"] = pd.Series(v).rolling(4).sum().to_numpy() / (pd.Series(v).rolling(672).mean().to_numpy() * 4 + 1e-12)
    for tf in ("1h", "4h"):
        b = bars_cache[tf]
        a_, r_, e50 = atrp(b["h"], b["l"], b["c"]), rsi(b["c"]), b["c"] / ema(b["c"], 50) - 1
        e200 = b["c"] / ema(b["c"], 200) - 1
        x1, x2, x3, x4 = htf_at(tf, T, [a_, r_, e50, e200])
        F[f"atr{tf}"] = x1; F[f"rsi{tf}"] = x2; F[f"ema50_{tf}"] = x3; F[f"ema200_{tf}"] = x4
    # funding (settled rate in force at T), 3-day mean
    fr = np.nan_to_num(g["fund"]); fi = np.flatnonzero(fr != 0); ft = GT0 + fi.astype(np.int64) * MIN
    j = np.searchsorted(ft, T, side="right") - 1; ok = (j >= 0) & (T < ft[-1] + 9 * 3600 * 1000)
    F["fund"] = np.where(ok, fr[fi][np.clip(j, 0, None)], np.nan)
    f3 = pd.Series(fr[fi]).rolling(9, min_periods=1).mean().to_numpy()
    F["fund3d"] = np.where(ok, f3[np.clip(j, 0, None)], np.nan)
    # order flow metrics (5m)
    sym = cn.replace("USDT", "").lower()
    mt = pd.read_csv(f"{ORDERFLOW}/{sym}_metrics_5m.csv.gz")
    mts = pd.to_datetime(mt.create_time).astype("int64").to_numpy() // 1_000_000
    oi = mt.sum_open_interest.to_numpy(float)
    for lab, lag in (("oi1h", 3600_000), ("oi24h", DAY)):
        k1 = np.searchsorted(mts, T, side="right") - 1; k0 = np.searchsorted(mts, T - lag, side="right") - 1
        okk = (k1 >= 0) & (k0 >= 0) & (T - mts[np.clip(k1, 0, None)] < 3600_000)
        F[lab] = np.where(okk, oi[np.clip(k1, 0, None)] / np.maximum(oi[np.clip(k0, 0, None)], 1e-9) - 1, np.nan)
    k1 = np.searchsorted(mts, T, side="right") - 1; okk = (k1 >= 0) & (T - mts[np.clip(k1, 0, None)] < 3600_000)
    for col, lab in (("sum_taker_long_short_vol_ratio", "taker"), ("sum_toptrader_long_short_ratio", "toplsr"),
                     ("count_long_short_ratio", "lsr")):
        x = mt[col].to_numpy(float)
        xm = pd.Series(x).rolling(12, min_periods=1).mean().to_numpy()
        F[lab] = np.where(okk, x[np.clip(k1, 0, None)], np.nan); F[lab + "1h"] = np.where(okk, xm[np.clip(k1, 0, None)], np.nan)
    # BTC
    reg, reg5, badx = btc_at(T)
    F["reg"] = reg.astype(float); F["reg5"] = reg5.astype(float); F["badx"] = badx
    if ci == 0:
        btc15 = {"T": T, "ret4": F["ret4"], "ret16": F["ret16"], "ret96": F["ret96"], "atr15": F["atr15"]}
    jb = np.searchsorted(btc15["T"], T); jb = np.clip(jb, 0, len(btc15["T"]) - 1)
    okb = btc15["T"][jb] == T
    for k in ("ret4", "ret16", "ret96", "atr15"):
        F[f"btc_{k}"] = np.where(okb, btc15[k][jb], np.nan)
    F["hour"] = (((T + KST) // 3600_000) % 24).astype(float); F["dow"] = ((((T + KST) // DAY) + 3) % 7).astype(float)
    F["coin"] = np.full(len(T), float(ci))
    # strategy signal counts: signals whose entry minute is in (T - 60, T] and (T - 240, T]
    eT = (T - GT0) // MIN
    for lab, es in (("sigL", SIGC[ci][0]), ("sigS", SIGC[ci][1])):
        es = np.sort(es)
        for w, wl in ((60, "1h"), (240, "4h")):
            F[f"{lab}{wl}"] = (np.searchsorted(es, eT, side="right") - np.searchsorted(es, eT - w, side="right")).astype(float)
    # trend sources' state and latch on the last closed 1h / 4h bar
    for tf in ("1h", "4h"):
        Zs = RD._states(cn, tf); close = Zs["ts"] + TF_MIN[tf] * MIN
        j = np.searchsorted(close, T, side="right") - 1; ok = j >= 0; jj = np.clip(j, 0, None)
        for k in sorted(Zs.keys()):
            if k in ("ts", "nb"):
                continue
            F[f"{k}@{tf}"] = np.where(ok, Zs[k][jj].astype(float), np.nan)
    RD._GR.pop(cn, None) if hasattr(RD, "_GR") else None
    sel = (T >= A) & (T < Z) & np.isfinite(F["ret672"])
    names = sorted(F)
    if FNAMES is None:
        FNAMES = names
    assert names == FNAMES, (cn, set(names) ^ set(FNAMES))
    X = np.column_stack([F[k][sel].astype(np.float32) for k in FNAMES])
    FEATS.append(X)
    META.append(pd.DataFrame({"T": T[sel], "coin": ci, "e": ((T[sel] - GT0) // MIN).astype(np.int64),
                              "atr15": F["atr15"][sel], "reg": reg[sel]}))
    log(cn, "features", X.shape)
X = np.concatenate(FEATS); del FEATS
MT = pd.concat(META, ignore_index=True); del META
o = np.concatenate(O); h = np.concatenate(H); l = np.concatenate(L); cl = np.concatenate(C); off = np.array(OFF)
del O, H, L, C
log("X", X.shape, "features", len(FNAMES))

# ---------------------------------------------------------------- labels: walk long and short for 3 ladder exits
EXN = ["E2 손절ROE-75%·계단12→10", "E3 손절2ATR·계단12→10", "E4 손절ROE-50%·작은계단6→4"]
sk = np.array([1, 0, 1], np.int8); sv = np.array([0.75, 2.0, 0.50])
tk = np.zeros(3, np.int8); tv = np.zeros(3)
lg = np.array([HB.LADS["house"][0], HB.LADS["house"][0], HB.LADS["tight"][0]])
ll = np.array([HB.LADS["house"][1], HB.LADS["house"][1], HB.LADS["tight"][1]])
ls = np.array([HB.LADS["house"][2], HB.LADS["house"][2], HB.LADS["tight"][2]])
ci_ = MT.coin.to_numpy(); start = off[ci_] + MT.e.to_numpy(); send = off[ci_ + 1]
good = start < send - 1
p0 = o[np.minimum(start, len(o) - 1)]; good &= np.isfinite(p0)
lev = HB.LEVC[ci_]; atrf = np.nan_to_num(MT.atr15.to_numpy(), nan=0.01)
st2 = np.where(good, start, 0)
WL, KL, _ = HB.walk_all(o, h, l, cl, st2, send, np.ones(len(MT), np.int8), lev, atrf, sk, sv, tk, tv, lg, ll, ls,
                        HB.COST, HB.MARGIN, HB.MAXK)
WS, KS, _ = HB.walk_all(o, h, l, cl, st2, send, -np.ones(len(MT), np.int8), lev, atrf, sk, sv, tk, tv, lg, ll, ls,
                        HB.COST, HB.MARGIN, HB.MAXK)
WL[~good] = np.nan; WS[~good] = np.nan
log("labels", np.nanmean(WL, 0), np.nanmean(WS, 0))
del o, h, l, cl
NX = 3

# ---------------------------------------------------------------- walk-forward
Tm = MT["T"].to_numpy()
blocks = []
y0 = 2022
while True:
    for half in (0, 1):
        a = ms(f"{y0}-{1 + 6 * half:02d}-01") - KST
        b = ms(f"{y0 + half}-{(7 if half == 0 else 1):02d}-01") - KST
        if a >= Z:
            break
        blocks.append((a, min(b, Z)))
    y0 += 1
    if ms(f"{y0}-01-01") > Z:
        break
PRED = np.full((len(MT), 2, NX), np.nan, np.float32)
for (a, b) in blocks:
    tr = np.flatnonzero((Tm < a - 3 * DAY))[::2]
    te = np.flatnonzero((Tm >= a) & (Tm < b))
    for si, W in enumerate((WL, WS)):
        for x in range(NX):
            y = W[tr, x]; m = np.isfinite(y); idx = tr[m]
            mdl = lgb.LGBMRegressor(n_estimators=600, learning_rate=0.02, num_leaves=63, min_child_samples=300,
                                    subsample=0.7, subsample_freq=1, colsample_bytree=0.5, reg_lambda=5.0,
                                    n_jobs=4, verbose=-1)
            mdl.fit(X[idx], y[m].astype(np.float64))
            PRED[te, si, x] = mdl.predict(X[te])
    log("block", pd.Timestamp(a, unit="ms").strftime("%Y-%m"), "trained", len(tr), "tested", len(te))
REGS = MT.reg.to_numpy()
np.savez_compressed(os.path.join(OUTD, f"ml18_{MODE}.npz"), PRED=PRED, WL=WL.astype(np.float32), WS=WS.astype(np.float32),
                    KL=KL, KS=KS, T=Tm, REG=REGS, COIN=MT.coin.to_numpy().astype(np.int8))
log("saved")


def light(w, n=20, q=0.9):
    lv = np.ones(len(w), bool)
    for i in range(n, len(w)):
        lv[i] = (w[i - n:i] > 0).sum() >= q * n - 1e-9
    return lv


def trade(x, thr=None, qa=None, flip=None):
    te = np.flatnonzero(np.isfinite(PRED[:, 0, x]))
    pl, ps = PRED[te, 0, x], PRED[te, 1, x]
    side = np.where(pl >= ps, 0, 1); best = np.maximum(pl, ps)
    if qa is not None:                     # adaptive: above the q-quantile of the 30 days before (all coins, best side)
        tt = Tm[te]; o_ = np.argsort(tt, kind="stable"); te, side, best, tt = te[o_], side[o_], best[o_], tt[o_]
        day = (tt + KST) // DAY; ud = np.unique(day); ok = np.zeros(len(te), bool)
        for d in ud:
            past = (day >= d - 30) & (day < d)
            if past.sum() < 1000:
                continue
            q = np.quantile(best[past], qa)
            m = day == d
            ok[m] = best[m] > max(q, 0.0)
    else:
        ok = best > thr
    te, side, best = te[ok], side[ok], best[ok]
    order = np.lexsort((-best, Tm[te])); te, side = te[order], side[order]
    if flip is not None:
        side = np.where(np.random.default_rng(flip).random(len(side)) < 0.5, 1 - side, side)
    W = np.where(side == 0, WL[te, x], WS[te, x]); K = np.where(side == 0, KL[te, x], KS[te, x])
    keep = []; free = -1
    for i in range(len(te)):
        if Tm[te[i]] >= free and np.isfinite(W[i]):
            keep.append(i); free = Tm[te[i]] + int(K[i]) * MIN
    keep = np.array(keep, int)
    return Tm[te[keep]], W[keep].astype(float), REGS[te[keep]], side[keep]


def read(t, w, rg, sd, use_light=False):
    lv = light(w) if use_light else np.ones(len(w), bool)
    d = pd.to_datetime(t + KST, unit="ms"); ym = (d.year * 100 + d.month).to_numpy(); yr = d.year.to_numpy()
    rs, ends = [], []
    for k in sorted(set(ym)):
        if k >= 202610:
            continue
        eq = 1.0; r = "그대로"; mm = ym == k
        for v, on in zip(w[mm], lv[mm]):
            if not on:
                continue
            eq *= 1 + v
            if eq >= 5:
                r = "x5"; break
            if eq <= 0.5:
                r = "-50%"; break
        rs.append((k, r)); ends.append(float(np.prod(1 + w[mm][lv[mm]])))
    hits = [r == "x5" for _, r in rs]
    two = sum(1 for i in range(1, len(hits)) if hits[i] and hits[i - 1])
    res26 = []
    for s0 in range(ms("2026-01-01"), ms("2026-09-25"), DAY):
        i = np.searchsorted(t, s0); eq = 1.0; r = 0
        while i < len(t) and t[i] < s0 + 30 * DAY:
            if lv[i]:
                eq *= 1 + w[i]
            i += 1
            if eq >= 5:
                r = 1; break
            if eq <= 0.7:
                r = -1; break
        res26.append(r)
    res26 = np.array(res26); f = (t >= FWD_A) & lv
    wl = w[lv]
    return {"거래": int(lv.sum()), "달": len(rs), "x5달": int(sum(hits)), "연속 x5": two,
            "-50%달": sum(r == "-50%" for _, r in rs), "달 중간값": round(float(np.median(ends)), 3) if ends else None,
            "거래당": round(float(wl.mean()), 4) if len(wl) else None,
            "해별 거래당": {str(y): round(float(w[lv & (yr == y)].mean()), 4) for y in range(2022, 2027) if (lv & (yr == y)).any()},
            "장세별 거래당(상승/하락/횡보)": [round(float(w[lv & (rg == g)].mean()), 4) if (lv & (rg == g)).any() else None
                                       for g in (0, 1, 2)],
            "2026 30일 x5/-30%": [round(float((res26 == 1).mean()), 3), round(float((res26 == -1).mean()), 3)],
            "10월19일": round(float(np.prod(1 + w[f])), 3), "x5달 목록": [str(k) for (k, r) in rs if r == "x5"]}


res = {}
for x in range(NX):
    rules = [("기준", v) for v in (0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04)] + [("30일 분위", q) for q in (0.99, 0.995, 0.999)]
    for kind, v in rules:
        tr_ = trade(x, thr=v) if kind == "기준" else trade(x, qa=v)
        for ul in (False, True):
            r = read(*tr_, use_light=ul)
            fl = trade(x, thr=v, flip=1) if kind == "기준" else trade(x, qa=v, flip=1)
            r["동전 x5달"] = read(*fl, use_light=ul)["x5달"]
            key = f"{EXN[x]} / {kind} {v} / 신호등 {'켬' if ul else '끔'}"
            res[key] = r
            log(key, json.dumps(r, ensure_ascii=False))
json.dump({"features": FNAMES, "res": res}, open(os.path.join(OUTD, f"ml18_{MODE}.json"), "w"), ensure_ascii=False,
          indent=1, default=float)
log("done")
