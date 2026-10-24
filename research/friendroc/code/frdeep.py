"""The owners' question of 10/24 on the friend's 15m strategy (research/friendroc/PREREG3.md): can good fixes turn October's
14 losses into 4? Five parts, all on P's candidates after the entry blocks (30x, net ROE -50 % stop, the ladder, cost 0.124 %
round trip, one position over the six coins, margin 40 %):

  0  the target in numbers: the fewest losses in any run of 64 consecutive five-year trades of P
  A  can a loser be told apart at entry: a logistic regression and a small tree model fit on 2020-03 .. 2024-12, AUC on
     2025-01 .. 2026-09 and October, and the two models as entry filters
  B  rules fit to October (the overfitting demo): single and paired "skip if value > / < cut" rules, the best one with at
     most 4 October losses, and what every such rule did over five years
  C  the same rules picked on 2020-03 .. 2024-12 only, read once on 2025-01 .. 2026-09 and October
  D  thirteen exit fixes (time stop, break-even, signal cancel, EMA21 / EMA trend exit, a lower first lock, BTC against)
  E  the picked entry rule / F4 with the picked exit fix; coin-flip twins of the picks

plus the 14 October losses one by one (types and the new entry-time values N1 .. N13).

    python3 -I frrun.py build     (once: OUT/rows.pkl in the session scratchpad)
    python3 -I frdeep.py          -> research/friendroc/results3.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frcore import _ind
from frrun import ROWS, PERS, MARGIN, take, rnd, coin_flip
from frloss import coin_features, path_values, acct, table, PER, LEV, COST, FL, STEP, GAP, warnings_off
import hashlib
from types import SimpleNamespace

SEED = 20261024
QS = np.round(np.arange(0.1, 0.91, 0.1), 1)               # the cuts: 10 % .. 90 % positions of the select candidates
MIN_OCT_N, MAX_OCT_LOSSES = 30, 4
FIVE = (PERS["select"][0], PERS["confirm"][1])             # 2020-03 .. 2026-09

NUM = {                                                    # entry-time values used by the rules and the models
    "adx15": "15분 ADX", "adx1h": "1시간 ADX", "adx4h": "4시간 ADX", "p24_side": "24시간 위치", "p7_side": "7일 위치",
    "d_e21_atr": "EMA21 거리(ATR)", "d_e52_atr": "EMA52 거리(ATR)", "rsi_side": "15분 RSI26", "roc_side": "15분 ROC9",
    "roc_jump": "ROC9 돌파 폭", "atrp15_pct": "15분 변동성 위치", "atrp30_pct": "30분 변동성 위치", "stop50_atr": "손절 ATR 배수",
    "vote1h": "1시간 판단", "vote4h": "4시간 판단", "roc1h_side": "1시간 ROC9", "roc4h_side": "4시간 ROC9",
    "btc_roc15_side": "BTC 15분 ROC9", "btc_gap_side": "BTC EMA 간격", "btc_roc1h_side": "BTC 1시간 ROC9",
    "cross24": "출렁임(24봉 0선 넘나듦)", "trend_age": "추세 나이(봉)", "ema_gap_atr": "EMA 간격(ATR)", "vol_ratio": "거래량 배수",
    "body_atr": "신호봉 몸통(ATR)", "close_loc": "신호봉 종가 위치", "rsi1h_side": "1시간 RSI26", "rsi4h_side": "4시간 RSI26",
}
CAT = {"hour4": ("한국 시간대", ("09~15시", "15~21시", "21~03시", "03~09시")), "side_c": ("방향", ("롱", "숏")),
       "coin": ("코인", tuple(c[:-4] for c in COINS))}


# ====================================================================== new entry-time values (PREREG3 N1 .. N13)
def coin_new(coin, R, btc):
    """N1 .. N13 for the coin's rows R (frrun rows); btc: BTC's 15m / 1h arrays."""
    df = bars(coin, "15m")
    ts = df.ts.to_numpy(np.int64)
    i = np.searchsorted(ts, R.bar_open.to_numpy(np.int64))
    assert (ts[i] == R.bar_open.to_numpy(np.int64)).all()
    c, o, h, l, v = (df[k].to_numpy(float) for k in ("close", "open", "high", "low", "volume"))
    I = _ind(c)
    atr, _ = atr_adx(df)
    s = R.side.to_numpy()
    roc, e21, e52 = I["roc"], I["e21"], I["e52"]
    rp = prev(roc)
    with np.errstate(invalid="ignore"):
        x = (((rp <= 0) & (roc > 0)) | ((rp >= 0) & (roc < 0))).astype(float)
    cx = np.r_[0.0, np.cumsum(x)]
    F = pd.DataFrame(index=R.index)
    F["cross24"] = cx[i] - cx[np.maximum(i - 24, 0)]           # bars i-24 .. i-1 (the signal bar left out)
    sg = np.sign(e21 - e52)
    flip = np.r_[True, sg[1:] != sg[:-1]]
    last = np.maximum.accumulate(np.where(flip, np.arange(len(sg)), 0))
    F["trend_age"] = i - last[i]
    F["ema_gap_atr"] = (e21[i] - e52[i]) * s / atr[i]
    vm = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    with np.errstate(all="ignore"):
        F["vol_ratio"] = v[i] / vm[i]
        F["body_atr"] = (c[i] - o[i]) * s / atr[i]
        rng_ = h[i] - l[i]
        cl = np.where(rng_ > 0, (c[i] - l[i]) / np.where(rng_ > 0, rng_, 1), 0.5)
    F["close_loc"] = np.where(s > 0, cl, 1 - cl)
    F["rsi1h_side"] = 50 + s * (R["1h_rsi"].to_numpy() - 50)
    F["rsi4h_side"] = 50 + s * (R["4h_rsi"].to_numpy() - 50)
    F["roc1h_side"] = s * R["1h_roc"].to_numpy()
    F["roc4h_side"] = s * R["4h_roc"].to_numpy()
    j = np.searchsorted(btc["ts15"], R.bar_open.to_numpy(np.int64))
    ok = (j < len(btc["ts15"])) & (btc["ts15"][np.minimum(j, len(btc["ts15"]) - 1)] == R.bar_open.to_numpy(np.int64))
    j = np.minimum(j, len(btc["ts15"]) - 1)
    F["btc_roc15_side"] = np.where(ok, s * btc["roc15"][j], np.nan)
    F["btc_gap_side"] = np.where(ok, s * btc["gap15"][j], np.nan)
    jh = np.searchsorted(btc["tc1h"], R.t.to_numpy(np.int64), side="right") - 1
    F["btc_roc1h_side"] = np.where(jh >= 0, s * btc["roc1h"][np.maximum(jh, 0)], np.nan)
    hk = ((R.t.to_numpy(np.int64) + KST) // HOUR) % 24
    F["hour4"] = np.select([(hk >= 9) & (hk < 15), (hk >= 15) & (hk < 21), (hk >= 21) | (hk < 3)], [0, 1, 2], 3)
    F["side_c"] = np.where(s > 0, 0, 1)
    return F


def btc_arrays():
    df = bars("BTCUSDT", "15m")
    I = _ind(df.close.to_numpy(float))
    atr, _ = atr_adx(df)
    dh = bars("BTCUSDT", "1h")
    return {"ts15": df.ts.to_numpy(np.int64), "roc15": I["roc"], "gap15": (I["e21"] - I["e52"]) / atr,
            "tc1h": dh.ts.to_numpy(np.int64) + 60 * MIN, "roc1h": _ind(dh.close.to_numpy(float))["roc"]}


# ====================================================================== the walk with the exit fixes (PREREG3 part D)
@numba.njit
def walk3(o, h, l, c, cumf, es, s, lev, cost, first_lock, step, gap, roe_stop, be_trig, be_lock, tstop, flag, use_flag,
          bc, bo, btc_x, n):
    """frloss.walk2 (no ATR stop) with the exit fixes, each only before the ladder's first lock: a time stop at the open of
    entry + tstop minutes (0 = none); flag[i] (a 15m close shows the cancel condition; i = the minute after that bar) exits at
    the open of minute i; BTC's 1m close against the side by btc_x from BTC's entry-minute open exits at the next open
    (0 = none); and a break-even floor at net ROE be_lock once the best net ROE reached be_trig (armed from the next minute,
    as the ladder; be_trig > 1 = none). Reasons: 0 stop, 1 lock, 2 time, 3 open, 4 break-even, 5 cancel, 6 BTC."""
    m = len(es)
    ret = np.zeros(m)
    kk = np.zeros(m, np.int64)
    why = np.zeros(m, np.int8)
    for q in range(m):
        e = es[q]
        p0 = o[e]
        b0 = bo[e]
        f0 = cumf[e - 1]
        best = -1e9
        lk = np.nan
        k = 0
        pend = False
        while True:
            i = e + k
            if i >= n:
                i = n - 1
                F = s * (cumf[i] - f0)
                ret[q] = s * (c[i] / p0 - 1.0) - cost - F
                kk[q] = i - e
                why[q] = 3
                break
            Fp = s * (cumf[i - 1] - f0)
            F = s * (cumf[i] - f0)
            locked = not np.isnan(lk)
            op = s * (o[i] / p0 - 1.0)
            if k > 0 and not locked:
                ex = -1
                if tstop > 0 and k == tstop:
                    ex = 2
                elif use_flag and flag[i]:
                    ex = 5
                elif pend:
                    ex = 6
                if ex >= 0:
                    ret[q] = op - cost - F
                    kk[q] = k
                    why[q] = ex
                    break
            level = roe_stop / lev + cost + Fp
            rs = 0
            if best >= be_trig - 1e-12:
                lb = be_lock / lev + cost + Fp
                if lb > level:
                    level = lb
                    rs = 4
            if locked:
                lv = lk / lev + cost + Fp
                if lv > level:
                    level = lv
                    rs = 1
            if s > 0:
                up = h[i] / p0 - 1.0
                dn = l[i] / p0 - 1.0
            else:
                up = 1.0 - l[i] / p0
                dn = 1.0 - h[i] / p0
            if dn <= level:
                fill = level if level < op else op
                ret[q] = fill - cost - F
                kk[q] = k
                why[q] = rs
                break
            r_up = lev * (up - cost - F)
            if r_up > best:
                best = r_up
                lk = lock_for(best, first_lock, step, gap)
            if btc_x > 0 and np.isnan(lk) and s * (bc[i] / b0 - 1.0) <= -btc_x:
                pend = True
            k += 1
        if ret[q] < -1.0 / lev:
            ret[q] = -1.0 / lev
    return ret, kk, why


EXIT_REASONS = ("stop", "lock", "time", "open", "breakeven", "cancel", "btc")
XFIX = {                                                   # PREREG3 part D: name -> settings (one change each)
    "X1-30 시간 손절 30분": {"tstop": 30}, "X1-60 시간 손절 60분": {"tstop": 60},
    "X1-120 시간 손절 2시간": {"tstop": 120}, "X1-240 시간 손절 4시간": {"tstop": 240},
    "X2-5 본전 이동 +5%": {"be_trig": 0.05}, "X2-8 본전 이동 +8%": {"be_trig": 0.08},
    "X3 신호 취소(ROC9 반대)": {"flag": "roc"}, "X4 EMA21 이탈": {"flag": "e21"}, "X5 EMA 뒤집힘": {"flag": "e52"},
    "X6 첫 잠금 +5%": {"fl": 0.05}, "X7-0.5 BTC 반대 0.5%": {"btc_x": 0.005}, "X7-1.0 BTC 반대 1.0%": {"btc_x": 0.01},
}


def coin_flags(coin, n):
    """The cancel conditions per minute (the minute after a 15m close) and side: {kind: {+1: bool[n], -1: bool[n]}}."""
    df = bars(coin, "15m")
    c = df.close.to_numpy(float)
    I = _ind(c)
    m = (df.ts.to_numpy(np.int64) + 15 * MIN - T0) // MIN
    ok = m < n
    out = {}
    with np.errstate(invalid="ignore"):
        cond = {"roc": (I["roc"] < 0, I["roc"] > 0), "e21": (c < I["e21"], c > I["e21"]), "e52": (I["e21"] < I["e52"], I["e21"] > I["e52"])}
    for kind, (lo, sh) in cond.items():
        fl, fs = np.zeros(n, bool), np.zeros(n, bool)
        fl[m[ok]], fs[m[ok]] = lo[ok], sh[ok]
        out[kind] = {1: fl, -1: fs}
    return out


def exits(A, cfg, sides=("own", "opp")):
    """walk3 outcomes of every row of A under one exit setting: {own|opp: {r, k, why}}."""
    bt = grid("BTCUSDT")
    bc_, bo_ = (np.ascontiguousarray(bt[x], dtype=np.float64) for x in ("c", "o"))
    out = {}
    for sn in sides:
        r = np.zeros(len(A)); k = np.zeros(len(A), np.int64); w = np.zeros(len(A), np.int8)
        for ci in range(6):
            g = grid(COINS[ci])
            cumf = np.cumsum(g["fund"])
            o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
            fk = cfg.get("flag")
            flags = coin_flags(COINS[ci], g["n"]) if fk else None
            for side in (1, -1):
                msk = ((A.coin == ci) & (A.side * (1 if sn == "own" else -1) == side)).to_numpy()
                if not msk.any():
                    continue
                fl_ = flags[fk][side] if fk else np.zeros(1, bool)
                a = walk3(o, h, l, c, cumf, A.e.to_numpy(np.int64)[msk], side, LEV, COST, cfg.get("fl", FL), STEP, GAP, -0.5,
                          cfg.get("be_trig", 9.0), 0.01, cfg.get("tstop", 0), fl_, bool(fk), bc_, bo_, cfg.get("btc_x", 0.0), g["n"])
                r[msk], k[msk], w[msk] = a
        out[sn] = {"r": r, "k": k, "why": w}
    return out


# ====================================================================== fast account numbers for the rule search
@numba.njit
def per_stats(t, ext, roe, use, bnd):
    """For each period [a, z): the one-position pass over the rows in entry order (vwacct._take) -> n, wins, sum of net
    ROE, log growth at margin 40 %."""
    out = np.zeros((bnd.shape[0], 4))
    for p in range(bnd.shape[0]):
        a, z = bnd[p, 0], bnd[p, 1]
        free = -1
        n = 0
        w = 0
        sm = 0.0
        gr = 0.0
        for i in range(len(t)):
            if t[i] < a or t[i] >= z or not use[i] or t[i] < free:
                continue
            n += 1
            r = roe[i]
            if r > 0:
                w += 1
            sm += r
            x = 0.4 * r
            if x < -1 + 1e-12:
                x = -1 + 1e-12
            gr += np.log1p(x)
            free = ext[i]
        out[p, 0] = n
        out[p, 1] = w
        out[p, 2] = sm
        out[p, 3] = gr
    return out


def stats_row(S):
    """per_stats rows -> {period: {n, wins, losses, roe_pct, mult40}} in PER order."""
    out = {}
    for j, pn in enumerate(PER):
        n, w, sm, gr = S[j]
        out[pn] = {"n": int(n), "wins": int(w), "losses": int(n - w), "roe_pct": rnd(sm / n * 100, 3) if n else None,
                   "mult40": rnd(np.exp(gr), 3)}
    return out


# ====================================================================== main
def main():
    for f in ("PREREG3.md",):
        want = open(os.path.join(RES_DIR, f + ".sha256")).read().split()[0]
        sha = hashlib.sha256(open(os.path.join(RES_DIR, f), "rb").read()).hexdigest()
        assert sha == want, f"{f} changed after it was frozen"
    A = pd.read_pickle(ROWS)
    A = A[A.P & (A.block == "")].reset_index(drop=True)            # P's candidates after the entry blocks, in entry order
    t = A.t.to_numpy(np.int64)
    base = {q: A[f"L30_c042_own_{q}"].to_numpy() for q in ("r", "k", "why", "mfe")}
    opp = {q: A[f"L30_c042_opp_{q}"].to_numpy() for q in ("r", "k", "why")}
    every = np.ones(len(A), bool)
    btc = btc_arrays()
    F = pd.concat([pd.concat([coin_features(COINS[ci], A[A.coin == ci]), coin_new(COINS[ci], A[A.coin == ci], btc)], axis=1)
                   for ci in range(6)]).loc[A.index]
    A = pd.concat([A, F], axis=1)
    A["coin_c"] = A.coin
    res = {"prereg3_sha256": sha, "data_end_utc": str(pd.Timestamp(DATA_END, unit="ms")),
           "periods_utc": {k: [str(pd.Timestamp(a, unit="ms")), str(pd.Timestamp(z, unit="ms"))] for k, (a, z) in PER.items()}}
    P0 = table(t, base["k"], base["r"], base["why"], every)
    old = json.load(open(os.path.join(RES_DIR, "results.json")))["variants"]["P"]["c042"]
    for pn in PER:
        assert P0[pn]["n"] == old[pn]["n"] and P0[pn]["wins"] == old[pn]["wins"], (pn, P0[pn], old[pn]["n"])
    res["P"] = P0
    print("P", {pn: (v["n"], v["wins"], v["roe_pct"], v["mult40"]) for pn, v in P0.items()}, flush=True)
    sel = (t >= PER["select"][0]) & (t < PER["select"][1])
    roe_b = LEV * base["r"]
    ext_b = t + (base["k"].astype(np.int64) + 1) * MIN
    bnd = np.array([PER[pn] for pn in PER], np.int64)

    # ---- 0: the target in numbers
    idx5 = take(t, base["k"], (t >= FIVE[0]) & (t < FIVE[1]))
    lose5 = (roe_b[idx5] <= 0).astype(int)
    roll = np.convolve(lose5, np.ones(64, int), "valid")
    res["target"] = {"five_year_trades": int(len(idx5)), "runs_of_64": int(len(roll)), "fewest_losses_in_64": int(roll.min()),
                     "most_losses_in_64": int(roll.max()), "median_losses_in_64": float(np.median(roll)),
                     "share_runs_le4": rnd((roll <= 4).mean(), 5), "share_runs_le8": rnd((roll <= 8).mean(), 5),
                     "share_runs_le10": rnd((roll <= 10).mean(), 5), "share_runs_ge14": rnd((roll >= 14).mean(), 4),
                     "oct_win_needed_for_4_of_64": rnd(60 / 64, 4)}
    print("target", res["target"], flush=True)

    # ---- A: can a loser be told apart at entry
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    cols = list(NUM)
    X = A[cols].to_numpy(float)
    oh = [((A.hour4 == v).to_numpy(float)) for v in range(4)] + [(A.side > 0).to_numpy(float)] + [((A.coin == c).to_numpy(float)) for c in range(6)]
    X = np.c_[X, np.array(oh).T]
    y = (roe_b <= 0).astype(int)
    conf = (t >= PER["confirm"][0]) & (t < PER["confirm"][1])
    octm = (t >= PER["oct2026"][0]) & (t < PER["oct2026"][1])
    oct_taken = take(t, base["k"], octm)
    med = np.nanmedian(X[sel], axis=0)
    Xi = np.where(np.isnan(X), med, X)
    sc = StandardScaler().fit(Xi[sel])
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(sc.transform(Xi[sel]), y[sel])
    hgb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=200,
                                         l2_regularization=1.0, random_state=SEED).fit(X[sel], y[sel])
    preds = {"logistic": lr.predict_proba(sc.transform(Xi))[:, 1], "tree": hgb.predict_proba(X)[:, 1]}
    ml = {"loss_share": {"select": rnd(y[sel].mean()), "confirm": rnd(y[conf].mean()), "oct_candidates": rnd(y[octm].mean())},
          "n": {"select": int(sel.sum()), "confirm": int(conf.sum()), "oct_candidates": int(octm.sum()), "oct_taken": int(len(oct_taken))}}
    for nm, p in preds.items():
        d = {"auc_select_in_sample": rnd(roc_auc_score(y[sel], p[sel])), "auc_confirm": rnd(roc_auc_score(y[conf], p[conf])),
             "auc_oct_candidates": rnd(roc_auc_score(y[octm], p[octm])), "auc_oct_taken": rnd(roc_auc_score(y[oct_taken], p[oct_taken]))}
        for top in (0.2, 0.4):
            cut = np.quantile(p[sel], 1 - top)
            use = p < cut
            row = table(t, base["k"], base["r"], base["why"], use)
            row["candidates_removed_share"] = {pn: rnd(1 - use[(t >= a) & (t < z)].mean(), 3) for pn, (a, z) in PER.items()}
            d[f"filter_top{int(top * 100)}"] = row
        ml[nm] = d
        print("ML", nm, {k: v for k, v in d.items() if k.startswith("auc")}, flush=True)
        for top in (20, 40):
            r_ = d[f"filter_top{top}"]
            print("   filter", top, {pn: (v["n"], v.get("wins"), v.get("losses"), v.get("roe_pct"), v.get("mult40")) for pn, v in r_.items() if pn in PER}, flush=True)
    res["predict"] = ml

    # ---- the rules (B and C)
    singles = []                                            # (feature, kind, cut, label, keep mask)
    seen = set()
    for f in NUM:
        x = A[f].to_numpy(float)
        cuts = np.nanquantile(x[sel], QS)
        for q, ct in zip(QS, cuts):
            for kind in (">", "<"):
                with np.errstate(invalid="ignore"):
                    keep = ~(x > ct) if kind == ">" else ~(x < ct)
                key = keep.tobytes()
                if key in seen or keep.all() or not keep.any():
                    continue
                seen.add(key)
                singles.append((f, kind, float(ct), f"{NUM[f]} {kind} {ct:.3g}이면 안 들어감 (고르기 {int(q * 100)}% 위치)", keep))
    for f, (lab, names) in CAT.items():
        col = "coin_c" if f == "coin" else f
        for v, vn in enumerate(names):
            keep = A[col].to_numpy() != v
            if keep.tobytes() in seen:
                continue
            seen.add(keep.tobytes())
            singles.append((f, "=", float(v), f"{lab} {vn}이면 안 들어감", keep))
    print("single rules", len(singles), flush=True)
    S1 = np.array([per_stats(t, ext_b, roe_b, r[4], bnd) for r in singles])        # (rules, periods, 4)
    keys = list(PER)
    io, i19, isel, icf = keys.index("oct2026"), keys.index("last19"), keys.index("select"), keys.index("confirm")
    nsel_min = 0.5 * P0["select"]["n"]
    # pairs: two rules on different values
    pair_ix, pair_S = [], []
    feat = [r[0] for r in singles]
    M = np.array([r[4] for r in singles])
    for a_ in range(len(singles)):
        for b_ in range(a_ + 1, len(singles)):
            if feat[a_] == feat[b_]:
                continue
            pair_ix.append((a_, b_))
            pair_S.append(per_stats(t, ext_b, roe_b, M[a_] & M[b_], bnd))
    S2 = np.array(pair_S)
    print("pair rules", len(pair_ix), flush=True)

    def label(j, pair):
        return (singles[pair_ix[j][0]][3] + " + " + singles[pair_ix[j][1]][3]) if pair else singles[j][3]

    def mask_of(j, pair):
        return (M[pair_ix[j][0]] & M[pair_ix[j][1]]) if pair else M[j]

    def roe_of(S, p):
        return np.where(S[:, p, 0] > 0, S[:, p, 2] / np.maximum(S[:, p, 0], 1), np.nan)

    def full(j, pair):
        m = mask_of(j, pair)
        row = table(t, base["k"], base["r"], base["why"], m)
        row["rule"] = label(j, pair)
        row["candidates_removed_share_5y"] = rnd(1 - m[(t >= FIVE[0]) & (t < FIVE[1])].mean(), 3)
        row["better_both_halves"] = bool(row["select"]["roe_pct"] > P0["select"]["roe_pct"] and row["confirm"]["roe_pct"] > P0["confirm"]["roe_pct"])
        row["positive_both_halves"] = bool(row["select"]["roe_pct"] > 0 and row["confirm"]["roe_pct"] > 0)
        return row

    # B: fit to October
    allS = np.concatenate([S1, S2])
    npair = len(S1)
    on, ol = allS[:, io, 0], allS[:, io, 0] - allS[:, io, 1]
    ok4 = (on >= MIN_OCT_N) & (ol <= MAX_OCT_LOSSES)
    rs_sel, rs_cf = roe_of(allS, isel), roe_of(allS, icf)
    if ok4.any():
        cand = np.flatnonzero(ok4)
        j = cand[np.lexsort((-on[cand], -allS[cand, io, 3]))[0]]
    else:
        cand = np.flatnonzero(on >= MIN_OCT_N)
        j = cand[np.lexsort((-allS[cand, io, 3], ol[cand]))[0]]
    pickB = full(j - npair if j >= npair else j, j >= npair)
    p_sel, p_cf = P0["select"]["roe_pct"] / 100, P0["confirm"]["roe_pct"] / 100
    res["oct_fit"] = {
        "rules_searched": {"single": int(len(S1)), "pair": int(len(S2))},
        "oct_le4_rules": {"single": int(ok4[:npair].sum()), "pair": int(ok4[npair:].sum())},
        "oct_fewest_losses_any_rule_n30": int(ol[on >= MIN_OCT_N].min()),
        "le4_rules_five_year": None if not ok4.any() else {
            "better_both_halves_share": rnd(((rs_sel[ok4] > p_sel) & (rs_cf[ok4] > p_cf)).mean(), 4),
            "positive_both_halves_share": rnd(((rs_sel[ok4] > 0) & (rs_cf[ok4] > 0)).mean(), 4),
            "select_roe_pct_median": rnd(np.nanmedian(rs_sel[ok4]) * 100, 3), "confirm_roe_pct_median": rnd(np.nanmedian(rs_cf[ok4]) * 100, 3),
            "confirm_roe_pct_best": rnd(np.nanmax(rs_cf[ok4]) * 100, 3),
            "oct_mult40_median": rnd(np.median(np.exp(allS[ok4, io, 3])), 3)},
        "pick": pickB}
    print("B", json.dumps({k: v for k, v in res["oct_fit"].items() if k != "pick"}, ensure_ascii=False), flush=True)
    print("B pick", pickB["rule"], {pn: (v["n"], v.get("wins"), v.get("losses"), v.get("roe_pct"), v.get("mult40")) for pn, v in pickB.items() if pn in PER}, flush=True)

    # C: picked on 2020-03 .. 2024-12 only
    picks = {}
    for nm, S, pair in (("single", S1, False), ("pair", S2, True)):
        rs = roe_of(S, isel)
        okn = S[:, isel, 0] >= nsel_min
        order = np.flatnonzero(okn)[np.argsort(-rs[okn])]
        top = []
        for j in order[:10]:
            top.append({"rule": label(j, pair), **{pn: v for pn, v in stats_row(S[j]).items()}})
        picks[nm] = {"pick": full(order[0], pair), "top10": top, "_j": int(order[0])}
        pk = picks[nm]["pick"]
        print("C", nm, pk["rule"], {pn: (v["n"], v.get("wins"), v.get("losses"), v.get("roe_pct"), v.get("mult40")) for pn, v in pk.items() if pn in PER}, flush=True)
    res["select_fit"] = {k: {kk: vv for kk, vv in v.items() if kk != "_j"} for k, v in picks.items()}
    res["select_fit"]["min_select_trades"] = int(np.ceil(nsel_min))

    # ---- D: the exit fixes
    chk = exits(A, {}, sides=("own",))
    assert np.array_equal(chk["own"]["k"], base["k"]) and np.allclose(chk["own"]["r"], base["r"], atol=1e-15), "walk3 differs from frcore.walk"
    XO, xres = {}, {}
    for nm, cfg in XFIX.items():
        O = exits(A, cfg)
        XO[nm] = O
        row = table(t, O["own"]["k"], O["own"]["r"], O["own"]["why"], every)
        for pn, (a, z) in PER.items():
            idx = take(t, O["own"]["k"], (t >= a) & (t < z))
            row[pn]["exits"] = {EXIT_REASONS[q]: int((O["own"]["why"][idx] == q).sum()) for q in range(7) if (O["own"]["why"][idx] == q).any()}
        row["better_both_halves"] = bool(row["select"]["roe_pct"] > P0["select"]["roe_pct"] and row["confirm"]["roe_pct"] > P0["confirm"]["roe_pct"])
        row["positive_both_halves"] = bool(row["select"]["roe_pct"] > 0 and row["confirm"]["roe_pct"] > 0)
        xres[nm] = row
        print("D", nm, {pn: (v["n"], v.get("wins"), v.get("losses"), v.get("roe_pct"), v.get("avg_win_pct"), v.get("avg_loss_pct"), v.get("mult40")) for pn, v in row.items() if pn in PER}, row["better_both_halves"], flush=True)
    xpick = max(xres, key=lambda nm: xres[nm]["select"]["roe_pct"])
    res["exit_fixes"] = xres
    res["exit_pick"] = xpick
    # after the fact (not in PREREG3, an explanation only): the same entries as P with each exit fix
    same = {}
    for nm, O in XO.items():
        sm = {}
        for pn in ("oct2026", "select", "confirm"):
            a, z = PER[pn]
            idx = take(t, base["k"], (t >= a) & (t < z))
            r0, r1 = roe_b[idx], LEV * O["own"]["r"][idx]
            sm[pn] = {"losses_to_wins": int(((r0 <= 0) & (r1 > 0)).sum()), "wins_to_losses": int(((r0 > 0) & (r1 <= 0)).sum()),
                      "wins_smaller": int(((r0 > 0) & (r1 > 0) & (r1 < r0 - 1e-9)).sum()), "losses": int((r1 <= 0).sum()),
                      "roe_pct": rnd(r1.mean() * 100, 3), "roe_pct_P": rnd(r0.mean() * 100, 3)}
        same[nm] = sm
    res["posthoc_exit_same_entries"] = same
    print("D pick", xpick, flush=True)

    # ---- E: together, and the coin-flip twins of the picks
    f4 = ~(A.adx4h.to_numpy() < 20)
    XP = XO[xpick]
    runs = {"C 규칙 하나 1등": (mask_of(picks["single"]["_j"], False), {"own": base, "opp": opp}),
            "C 규칙 둘 1등": (mask_of(picks["pair"]["_j"], True), {"own": base, "opp": opp}),
            "D 청산 1등": (every, XP),
            "E1 규칙 하나 1등 + 청산 1등": (mask_of(picks["single"]["_j"], False), XP),
            "E2 F4 + 청산 1등": (f4, XP)}
    honest = {}
    for nm, (use, O) in runs.items():
        row = table(t, O["own"]["k"], O["own"]["r"], O["own"]["why"], use)
        for pn in ("confirm", "oct2026"):
            a, z = PER[pn]
            m = use & (t >= a) & (t < z)
            idx = take(t, O["own"]["k"], m)
            roe = LEV * O["own"]["r"][idx]
            growth = np.log1p(np.maximum(MARGIN * roe, -1 + 1e-12)).sum()
            row[pn]["twin"] = coin_flip(SimpleNamespace(t=t), m, O["own"], O["opp"], LEV, roe.mean(), growth)
        o_ = row["oct2026"]
        row["pass_14_to_4"] = {"oct_le4_n30": bool(o_["n"] >= MIN_OCT_N and o_["losses"] <= MAX_OCT_LOSSES),
                               "confirm_positive": bool(row["confirm"]["roe_pct"] > 0),
                               "confirm_twin_975": bool(row["confirm"]["twin"]["pct_below"] >= 0.975)}
        row["better_both_halves"] = bool(row["select"]["roe_pct"] > P0["select"]["roe_pct"] and row["confirm"]["roe_pct"] > P0["confirm"]["roe_pct"])
        row["positive_both_halves"] = bool(row["select"]["roe_pct"] > 0 and row["confirm"]["roe_pct"] > 0)
        honest[nm] = row
        print("E", nm, {pn: (v["n"], v.get("wins"), v.get("losses"), v.get("roe_pct"), v.get("mult40"), (v.get("twin") or {}).get("pct_below")) for pn, v in row.items() if pn in PER}, row["pass_14_to_4"], flush=True)
    res["honest_picks"] = honest
    res["verdict_14_to_4"] = any(all(v["pass_14_to_4"].values()) for v in honest.values())
    print("verdict 14->4", res["verdict_14_to_4"], flush=True)

    # ---- the 14 October losses one by one
    D = A.iloc[oct_taken].copy()
    D["roe"] = roe_b[oct_taken]
    D["minutes"] = base["k"][oct_taken] + 1
    D["mfe_roe"] = base["mfe"][oct_taken] * 100
    pv = path_values(A, oct_taken, base["k"][oct_taken], base["r"][oct_taken])
    D["btc_with_pct"] = pv["btc_with"] * 100
    D["mfe_px_pct"] = pv["mfe_px"] * 100
    rows = []
    for _, r in D[D.roe <= 0].iterrows():
        rows.append({"entry_kst": str(pd.Timestamp(int(r.t) + KST, unit="ms"))[:16], "coin": COINS[int(r.coin)][:-4],
                     "side": "롱" if r.side > 0 else "숏", "net_roe_pct": rnd(r.roe * 100, 1), "minutes": int(r.minutes),
                     "type_move": "처음부터 반대" if r.mfe_roe < 3 else "조금 가다 밀림",
                     "type_btc": "BTC와 같이 밀림" if r.btc_with_pct < -0.3 else "코인만 밀림",
                     "type_time": "1시간 안" if r.minutes <= 60 else ("1~4시간" if r.minutes <= 240 else "4시간 넘음"),
                     "mfe_roe_pct": rnd(r.mfe_roe, 1), "btc_with_pct": rnd(r.btc_with_pct, 2),
                     **{f: rnd(r[f], 3) for f in NUM}, "hour4": CAT["hour4"][1][int(r.hour4)]})
    res["oct_losses"] = rows
    W = D[D.roe > 0]
    res["oct_wins_types"] = {"mfe_lt3": int((W.mfe_roe < 3).sum()), "btc_against_03": int((W.btc_with_pct < -0.3).sum()), "n": int(len(W))}
    res["oct_medians_new"] = {f: [rnd(D[D.roe <= 0][f].median(), 3), rnd(W[f].median(), 3)] for f in NUM}
    # after the fact (not in PREREG3): the same medians over P's five-year trades, losers / winners per half
    ph = {}
    for pn in ("select", "confirm"):
        a, z = PER[pn]
        idx = take(t, base["k"], (t >= a) & (t < z))
        Dq = A.iloc[idx]
        lq = roe_b[idx] <= 0
        ph[pn] = {f: [rnd(Dq[f][lq].median(), 3), rnd(Dq[f][~lq].median(), 3)] for f in NUM}
    res["posthoc_medians_5y"] = ph
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows)[["entry_kst", "coin", "side", "net_roe_pct", "minutes", "type_move", "type_btc", "type_time", "mfe_roe_pct", "btc_with_pct"]].to_string(), flush=True)
    path = os.path.join(RES_DIR, "results3.json")
    json.dump(res, open(path, "w"), ensure_ascii=False, indent=1, default=float)
    D[["t", "coin", "side", "e", "roe", "minutes", "mfe_roe", "btc_with_pct"]].to_pickle(os.path.join(OUT, "oct_taken.pkl"))


if __name__ == "__main__":
    main()
