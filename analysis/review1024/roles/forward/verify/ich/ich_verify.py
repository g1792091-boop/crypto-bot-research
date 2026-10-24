"""Adversarial check (look-ahead / time alignment / data errors) of the claim that the a2 family top-5 picks
(timing|1h and reversal|1h with the 4h N07_ICHI_CMO state, plus other|4h@1d c_T5_ST10_3, breakout|4h@1d Jlive,
range|4h@1d l_OBV_S) made +3.39 % per signal on H2 (574 signals).

Independent of the study's state / outcome arrays:
  B  the 4h N07_ICHI_CMO state rebuilt from the raw 1m grid with my own numpy code (tenkan 9, kijun 26, span B 52,
     spans displaced 26 bars back = the cloud visible at the bar, CMO14), read on the last 4h bar whose close <= t;
     compared with the stored c4h_N07_ICHI_CMO, and with the in-progress bar (a leak) and one-bar-older bars (lag)
  C  the a2 outcome re-walked minute by minute in plain python from the raw 1m bars (entry = open of minute e, stop
     2 x my own Wilder ATR14 of the signal bar, ladder +12 % -> +10 % then every 5 %, 30x, cost 0.124 %, stop checked
     before the lock moves inside a minute) for every pooled H2 row and its coin-flip twin
  E  1m bars of the grid vs the rule bot's own live_bars (Binance USDT-M via its feed) over H2

    python3 ich_verify.py <live_bars.csv>      (run from this folder without -I)
"""
import json
import os
import sys

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa: F401,F403

OUTD = os.path.dirname(os.path.abspath(__file__))
LIVE = sys.argv[1] if len(sys.argv) > 1 else None
CELLS = [("other", "4h", "1d", "c_T5_ST10_3"), ("breakout", "4h", "1d", "Jlive"), ("range", "4h", "1d", "l_OBV_S"),
         ("timing", "1h", "4h", "c_N07_ICHI_CMO"), ("reversal", "1h", "4h", "c_N07_ICHI_CMO")]
REP = {}


def h2_ok(D, v="a2", opp=False):
    s = "_opp" if opp else ""
    r = roe(D, v, opp)
    return (D.t.to_numpy() >= SPLIT) & (D[f"{v}{s}_why"].to_numpy() != 3) & np.isfinite(r) & \
        (D[f"{v}{s}_k"].to_numpy() >= 0), r


# ---------------------------------------------------------------- A  reproduce the pooled H2 read
S = load("sig")
S = S[S.role != "trend"].reset_index(drop=True)
rows = []
parts = []
for role, tf, htf, src in CELLS:
    D = S[(S.role == role) & (S.tf == tf)].copy()
    st = state(D, src, htf)
    w = (st.astype(int) * D.side.to_numpy(int)) == 1
    ok, r = h2_ok(D)
    m = w & ok
    rows.append({"cell": f"{role}|{tf}@{htf}:{src}", "n2": int(m.sum()), "m2": float(r[m].mean())})
    P = D[m].copy()
    P["cell"] = f"{role}|{tf}@{htf}:{src}"
    P["roe_a2"] = r[m]
    parts.append(P)
P = pd.concat(parts, ignore_index=True)
REP["A_cells"] = rows
REP["A_pooled"] = {"n": len(P), "mean": float(P.roe_a2.mean()), "per_day": len(P) / DAYS["H2"]}
U = P.drop_duplicates(["coin", "tf", "e", "side"])
REP["A_merged"] = {"n": len(U), "mean": float(U.roe_a2.mean()), "per_day": len(U) / DAYS["H2"],
                   "nS": int((U.side < 0).sum()), "mean_S": float(U.roe_a2[U.side < 0].mean()),
                   "nL": int((U.side > 0).sum()), "mean_L": float(U.roe_a2[U.side > 0].mean())}
n07 = P[P.cell.str.contains("N07")]
REP["A_n07_only"] = {"n": len(n07), "mean": float(n07.roe_a2.mean()),
                     "other3_n": int(len(P) - len(n07)), "other3_mean": float(P[~P.cell.str.contains("N07")].roe_a2.mean())}
log("A", REP["A_pooled"], REP["A_merged"])


# ---------------------------------------------------------------- B  independent 4h N07 state
def bars_from_grid(g, k):
    n = g["n"] // k * k
    o = g["o"][:n:k]
    c = g["c"][k - 1:n:k]
    h = g["h"][:n].reshape(-1, k).max(1)
    lo = g["l"][:n].reshape(-1, k).min(1)
    v = g["v"][:n].reshape(-1, k).sum(1)
    return o, h, lo, c, v                           # bar b covers minutes [b*k, (b+1)*k) from T0


def roll_max(x, n):
    return pd.Series(x).rolling(n, min_periods=n).max().to_numpy()


def roll_min(x, n):
    return pd.Series(x).rolling(n, min_periods=n).min().to_numpy()


def n07_state(h, lo, c):
    ten = (roll_max(h, 9) + roll_min(lo, 9)) / 2
    kij = (roll_max(h, 26) + roll_min(lo, 26)) / 2
    sa_raw = (ten + kij) / 2
    sb_raw = (roll_max(h, 52) + roll_min(lo, 52)) / 2
    sa = np.r_[np.full(26, np.nan), sa_raw[:-26]]
    sb = np.r_[np.full(26, np.nan), sb_raw[:-26]]
    d = np.r_[np.nan, np.diff(c)]
    up = pd.Series(np.where(d > 0, d, 0.0)).rolling(14, min_periods=14).sum().to_numpy()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).rolling(14, min_periods=14).sum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        cmo = 100 * (up - dn) / np.where(up + dn == 0, np.nan, up + dn)
        L = (ten > kij) & (sa > sb) & (cmo > 0)
        Sh = (ten < kij) & (sa < sb) & (cmo < 0)
    return np.where(L, 1, np.where(Sh, -1, 0)).astype(np.int8)


def wilder_atr(h, lo, c, n=14):
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.c_[h - lo, np.abs(h - pc), np.abs(lo - pc)], axis=1)
    tr[np.isnan(h)] = np.nan
    out = np.full(len(tr), np.nan)
    a = np.nan
    cnt = 0
    for i, x in enumerate(tr):
        if np.isnan(x):
            continue
        a = x if np.isnan(a) else a + (x - a) / n
        cnt += 1
        if cnt >= n:
            out[i] = a
    return out


def walk_a2(o, h, l, c, e, s, atr_abs, lev=30.0, cost=COST, fl=0.10, step=0.05, gap=0.02, nmax=None):
    """Plain-python re-walk (funding 0, as the grid in October): returns (r, k, why)."""
    p0 = o[e]
    atrd = 2.0 * atr_abs / p0
    best = -1e9
    lk = None
    k = 0
    n = nmax if nmax is not None else len(c)
    while True:
        i = e + k
        if i >= n:
            i = n - 1
            return s * (c[i] / p0 - 1) - cost, i - e, 3
        level = max(-1.0 / lev + cost, -atrd)
        if lk is not None:
            level = max(level, lk / lev + cost)
        if s > 0:
            up, dn = h[i] / p0 - 1, l[i] / p0 - 1
        else:
            up, dn = 1 - l[i] / p0, 1 - h[i] / p0
        op = s * (o[i] / p0 - 1)
        if dn <= level:
            fill = level if level < op else op
            r = max(fill - cost, -1.0 / lev)
            return r, k, (1 if lk is not None else 0)
        ru = lev * (up - cost)
        if ru > best:
            best = ru
            ft = fl + gap
            if best >= ft - 1e-12:
                lk = fl + step * np.floor((best - ft) / step + 1e-9)
        k += 1


# all forward signals of the two N07 cells' roles on 1h (H1 + H2), to check the state on every row
Q = S[(S.tf == "1h") & S.role.isin(["timing", "reversal"])].copy()
Q["mine_closed"] = 0
Q["mine_inprog"] = 0
Q["mine_lag1"] = 0
Q["mine_strict"] = 0
chk = []
liveB = None
if LIVE:
    liveB = pd.read_csv(LIVE, usecols=["ts", "symbol", "open", "high", "low", "close"])
dataE = {}
for ci, coin in enumerate(COINS):
    g = grid(coin)
    o4, h4, l4, c4, v4 = bars_from_grid(g, 240)
    st4 = n07_state(h4, l4, c4)
    m = (Q.coin == ci).to_numpy()
    t = Q.t.to_numpy(np.int64)[m]
    nclosed = (t - T0) // (240 * MIN)            # number of 4h bars whose close <= t (bar b closes at (b+1)*240)
    b = nclosed - 1
    Q.loc[m, "mine_closed"] = st4[b]
    Q.loc[m, "mine_inprog"] = st4[np.minimum(b + 1, len(st4) - 1)]   # the bar still open at t (would be a leak)
    Q.loc[m, "mine_lag1"] = st4[b - 1]
    at_edge = ((t - T0) % (240 * MIN)) == 0
    Q.loc[m, "mine_strict"] = np.where(at_edge, st4[b - 1], st4[b])  # ignore a 4h bar closing at the same minute
    # ---- C: re-walk every pooled H2 row of this coin (and its twin)
    for tf in ("1h", "4h"):
        k = TF_MIN[tf]
        ob, hb, lb, cb, vb = bars_from_grid(g, k)
        atr = wilder_atr(hb, lb, cb)
        mp = (P.coin == ci).to_numpy() & (P.tf == tf).to_numpy()
        for _, r in P[mp].iterrows():
            e = int(r.e)
            jb = e // k - 1                          # the signal bar (closes at minute e)
            assert (jb + 1) * k == e
            for sg, lab in ((int(r.side), ""), (-int(r.side), "_opp")):
                rr, kk, why = walk_a2(g["o"], g["h"], g["l"], g["c"], e, sg, atr[jb])
                chk.append({"coin": coin, "tf": tf, "e": e, "side": sg, "twin": lab == "_opp", "cell": r.cell,
                            "mine_r": rr, "mine_k": kk, "mine_why": why,
                            "grid_r": float(r[f"a2{lab}_r"]), "grid_k": int(r[f"a2{lab}_k"]), "grid_why": int(r[f"a2{lab}_why"]),
                            "atr_mine": atr[jb], "p0": g["o"][e], "c_prev": g["c"][e - 1],
                            "bar_close_px": cb[jb]})
    # ---- E: 1m grid vs live_bars over H2
    if liveB is not None:
        lb_ = liveB[(liveB.symbol == coin) & (liveB.ts >= SPLIT) & (liveB.ts < DATA_END)].drop_duplicates("ts")
        idx = ((lb_.ts.to_numpy(np.int64) - T0) // MIN).astype(np.int64)
        idx_ok = idx < g["n"]
        idx, lb_ = idx[idx_ok], lb_[idx_ok]
        res = {"minutes_live": int(len(lb_)), "minutes_grid_h2": int((DATA_END - SPLIT) // MIN)}
        for col, k_ in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c")):
            a = lb_[col].to_numpy(float)
            b_ = g[k_][idx]
            rel = np.abs(a / b_ - 1)
            res[f"{col}_n_diff"] = int((rel > 1e-9).sum())
            res[f"{col}_max_rel"] = float(np.nanmax(rel))
        hh, ll, oo = g["h"], g["l"], g["o"]
        a0 = (SPLIT - T0) // MIN
        a1 = (DATA_END - T0) // MIN
        rng_ = hh[a0:a1] / ll[a0:a1] - 1
        res["grid_nan_h2"] = int(np.isnan(g["c"][a0:a1]).sum())
        res["max_1m_range_pct"] = float(100 * np.nanmax(rng_))
        res["n_1m_range_gt_3pct"] = int((rng_ > 0.03).sum())
        dataE[coin] = res
    drop(coin)

Q["stored"] = Q["c4h_N07_ICHI_CMO"].astype(int)
REP["B_state_rows"] = int(len(Q))
REP["B_state_equal_closed"] = float((Q.stored == Q.mine_closed).mean())
REP["B_state_equal_inprog"] = float((Q.stored == Q.mine_inprog).mean())
REP["B_state_mismatch_rows"] = Q[Q.stored != Q.mine_closed][["name", "coin", "t", "side", "stored", "mine_closed",
                                                              "mine_inprog"]].head(20).astype(str).to_dict("records")
# H2 read of the two N07 cells under alignment variants (pooled over timing + reversal 1h)
alt = {}
for var in ("stored", "mine_closed", "mine_strict", "mine_lag1", "mine_inprog"):
    w = (Q[var].to_numpy(int) * Q.side.to_numpy(int)) == 1
    ok, r = h2_ok(Q)
    m = w & ok
    o1 = {}
    for role in ("timing", "reversal"):
        mm = m & (Q.role == role).to_numpy()
        o1[role] = {"n": int(mm.sum()), "mean": float(r[mm].mean())}
    o1["pooled"] = {"n": int(m.sum()), "mean": float(r[m].mean())}
    # coin-flip twin of the same with-trend rows
    okt, rt = h2_ok(Q, opp=True)
    o1["twin"] = float(rt[m & okt].mean())
    alt[var] = o1
REP["B_alignment_variants_H2_a2"] = alt

C = pd.DataFrame(chk)
C.to_csv(os.path.join(OUTD, "ich_rewalk.csv"), index=False, float_format="%.8g")
C["dr"] = (C.mine_r - C.grid_r).abs()
REP["C_rewalk"] = {"rows": len(C), "r_equal_1e-6": float((C.dr < 1e-6).mean()), "r_abs_diff_max": float(C.dr.max()),
                   "k_equal": float((C.mine_k == C.grid_k).mean()), "why_equal": float((C.mine_why == C.grid_why).mean()),
                   "entry_gap_vs_prev_close_max_rel": float((C.p0 / C.c_prev - 1).abs().max()),
                   "signal_bar_close_eq_prev_minute_close": float((C.bar_close_px == C.c_prev).mean()),
                   "mine_mean_roe_signal_rows": float(np.maximum(30 * C.mine_r[~C.twin], -1).mean()),
                   "grid_mean_roe_signal_rows": float(np.maximum(30 * C.grid_r[~C.twin], -1).mean()),
                   "mine_mean_roe_twin": float(np.maximum(30 * C.mine_r[C.twin & (C.mine_why != 3)], -1).mean())}
REP["C_worst_diffs"] = C.sort_values("dr", ascending=False).head(8)[["coin", "tf", "e", "side", "twin", "mine_r", "grid_r",
                                                                      "mine_k", "grid_k", "mine_why", "grid_why"]].astype(str).to_dict("records")
REP["E_live_vs_grid_H2"] = dataE
json.dump(REP, open(os.path.join(OUTD, "ich_verify.json"), "w"), indent=1, default=str)
print(json.dumps(REP, indent=1, default=str))
