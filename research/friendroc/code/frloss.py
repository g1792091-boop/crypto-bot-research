"""The owners' question of 10/24 on the friend's 15m strategy (research/friendroc/PREREG2.md): the 14 October losses of P one
by one against the 50 wins and against the five-year losers / winners, the stop grid of PREREG2 (net ROE -20 .. -75 %, 1 / 1.5 /
2 / 3 x ATR14 of the 15m signal bar, capped at net ROE -50 % or uncapped up to the -100 % liquidation; the ladder unchanged)
and the nine fix candidates F1 .. F9 (stop -50 %, ladder unchanged), on October, the last 19 days, 2020-03 .. 2024-12 and
2025-01 .. 2026-09 (cost 0.124 % round trip, 30x, one position, the entry blocks, margin 40 %).

    python3 -I frrun.py build     (once: OUT/rows.pkl in the session scratchpad)
    python3 -I frloss.py          -> research/friendroc/results2.json

Entry-time values (known at the signal bar's close): ADX14 of the 15m bars (vwcommon.atr_adx) and of the last closed 1h / 4h
bars (the trend bot's judge files, as research/vwap30/code/vwfix4.py), the 4h vote (judge 4h_raw3 x side, as
paperbot/entrygates.py vote_gate), the 15m ATR14 % against its last 30 days (entrygates vol_gate: q 0.8 incl. the bar; and its
percentile), the 30m ATR % percentile, the 24 h / 7-day range position and the chase flag (research/vwap30/code/vwbuild.py
features = combo.chase_check), the distance from EMA21 / EMA52 in 15m ATR, RSI26 and ROC9 turned to the trade's side, which
higher bar confirmed. After the entry (not known at entry): BTC's move with the side to the exit minute, the best net ROE before
the exit, minutes to the exit, the best move from the entry price in the 24 h after the exit (reached the +12 % trigger = the
price went the original way)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import ROWS, PERS, MARGIN, take, rnd
from numpy.lib.stride_tricks import sliding_window_view
import hashlib

LEV, COST = 30.0, COSTS["c042"]
FL, STEP, GAP = 0.10, 0.05, 0.02                         # the ladder of P (EXITS["L30"])
PER = {"oct2026": PERS["oct2026"], "last19": PERS["last19"], "select": PERS["select"], "confirm": PERS["confirm"]}
ROE_STOPS = (-0.20, -0.30, -0.40, -0.50, -0.60, -0.75)
ATR_KS = (1.0, 1.5, 2.0, 3.0)
TRIG = (FL + GAP)                                        # the first lock's trigger: net ROE +12 %
W15, W30 = 30 * 96, 30 * 48                              # 30 days of 15m / 30m bars
SHUFFLES, SEED = 2000, 20261024


# ====================================================================== the walk with a per-trade stop
@numba.njit
def walk2(o, h, l, c, cumf, es, s, lev, cost, first_lock, step, gap, atrd, roe_stop, n):
    """frcore.walk without the time cap, the stop level = the nearer of (side x price change) -atrd[q] (gross, inf = none)
    and net ROE roe_stop (funding in it, as frcore.walk; -1.0 = the liquidation of an uncapped ATR stop)."""
    m = len(es)
    ret = np.zeros(m)
    kk = np.zeros(m, np.int64)
    why = np.zeros(m, np.int8)
    mae = np.zeros(m)
    mfe = np.zeros(m)
    for q in range(m):
        e = es[q]
        p0 = o[e]
        f0 = cumf[e - 1]
        best = -1e9
        lk = np.nan
        worst = 1e9
        k = 0
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
            level = roe_stop / lev + cost + Fp
            if -atrd[q] > level:
                level = -atrd[q]
            locked = not np.isnan(lk)
            if locked:
                lv = lk / lev + cost + Fp
                if lv > level:
                    level = lv
            if s > 0:
                up = h[i] / p0 - 1.0
                dn = l[i] / p0 - 1.0
            else:
                up = 1.0 - l[i] / p0
                dn = 1.0 - h[i] / p0
            op = s * (o[i] / p0 - 1.0)
            F = s * (cumf[i] - f0)
            if dn <= level:
                fill = level if level < op else op
                ret[q] = fill - cost - F
                kk[q] = k
                why[q] = 1 if locked else 0
                break
            r_dn = lev * (dn - cost - Fp)
            if r_dn < worst:
                worst = r_dn
            r_up = lev * (up - cost - F)
            if r_up > best:
                best = r_up
                lk = lock_for(best, first_lock, step, gap)
            k += 1
        if ret[q] < -1.0 / lev:
            ret[q] = -1.0 / lev
        r_ex = lev * ret[q]
        mae[q] = r_ex if r_ex < worst else worst
        mfe[q] = best
    return ret, kk, why, mae, mfe


def stop_settings():
    out = [(f"ROE {int(round(x * 100))}%", "roe", x, None) for x in ROE_STOPS]
    out += [(f"{k:g} ATR (−50% 상한)", "atr_cap", -0.5, k) for k in ATR_KS]
    out += [(f"{k:g} ATR (상한 없음)", "atr_free", -1.0, k) for k in ATR_KS]
    return out


# ====================================================================== entry-time values
def window_pct(x, idx, w):
    """Share of the last w values up to and including x[idx] that are <= x[idx] (nan when fewer than w // 2 known)."""
    out = np.full(len(idx), np.nan)
    xx = np.r_[np.full(w - 1, np.nan), x]
    V = sliding_window_view(xx, w)
    for a in range(0, len(idx), 2000):
        b = min(len(idx), a + 2000)
        M = V[idx[a:b]]
        cur = x[idx[a:b]][:, None]
        known = np.isfinite(M).sum(1)
        with np.errstate(invalid="ignore"):
            le = (M <= cur).sum(1)
        out[a:b] = np.where((known >= w // 2) & np.isfinite(cur[:, 0]), le / np.maximum(known, 1), np.nan)
    return out


def coin_features(coin, R):
    """Entry-time values for the coin's signal rows R (frrun rows)."""
    g = grid(coin)
    df = bars(coin, "15m")
    ts = df.ts.to_numpy(np.int64)
    i = np.searchsorted(ts, R.bar_open.to_numpy(np.int64))
    assert (ts[i] == R.bar_open.to_numpy(np.int64)).all()
    atr, adx = atr_adx(df)
    c = df.close.to_numpy(float)
    atrp = atr / c
    q80 = pd.Series(atrp).rolling(W15, min_periods=W15 // 2).quantile(0.8).to_numpy()
    t = R.t.to_numpy(np.int64)
    s = R.side.to_numpy()
    F = pd.DataFrame(index=R.index)
    F["atr15"] = atr[i]
    F["atrf"] = atr[i] / R.entry_px.to_numpy()
    F["adx15"] = adx[i]
    F["atrp15"] = atrp[i]
    F["atrp15_q80"] = q80[i]
    F["atrp15_pct"] = window_pct(atrp, i, W15)
    d30 = bars(coin, "30m")
    a30, _ = atr_adx(d30)
    p30 = a30 / d30.close.to_numpy(float)
    j30 = np.searchsorted(d30.ts.to_numpy(np.int64) + 30 * MIN, t, side="right") - 1
    F["atrp30_pct"] = window_pct(p30, np.maximum(j30, 0), W30)
    Z = np.load(os.path.join(NL.JUDGE, f"{coin}.npz"))
    for tf, k in (("1h", 60), ("4h", 240)):
        tc = Z[f"{tf}_tclose"]
        jx = np.searchsorted(tc, t, side="right") - 1
        ok = (jx >= 0) & (t - tc[np.maximum(jx, 0)] < 2 * k * MIN)
        F[f"adx{tf}"] = np.where(ok, Z[f"{tf}_adx"].astype(float)[np.maximum(jx, 0)], np.nan)
        F[f"vote{tf}"] = np.where(ok, Z[f"{tf}_raw3"].astype(float)[np.maximum(jx, 0)] * s, np.nan)
    # the 24 h / 7-day range position of the entry price (vwbuild.features, combo.chase_check)
    nh = g["n"] // 60
    with np.errstate(all="ignore"), warnings_off():
        hh = np.nanmax(g["h"][:nh * 60].reshape(nh, 60), axis=1)
        ll = np.nanmin(g["l"][:nh * 60].reshape(nh, 60), axis=1)
    r24h = pd.Series(hh).rolling(24, min_periods=20).max().shift(1).to_numpy()
    r24l = pd.Series(ll).rolling(24, min_periods=20).min().shift(1).to_numpy()
    r7h = pd.Series(hh).rolling(168, min_periods=150).max().shift(1).to_numpy()
    r7l = pd.Series(ll).rolling(168, min_periods=150).min().shift(1).to_numpy()
    kh = (t - T0) // HOUR
    ep = R.entry_px.to_numpy()
    with np.errstate(all="ignore"):
        p24 = (ep - r24l[kh]) / (r24h[kh] - r24l[kh])
        p7 = (ep - r7l[kh]) / (r7h[kh] - r7l[kh])
    F["p24"], F["p7"] = p24, p7
    F["p24_side"] = np.where(s > 0, p24, 1 - p24)            # 1 = the chase end (a long at the top, a short at the bottom)
    F["p7_side"] = np.where(s > 0, p7, 1 - p7)
    F["stop50_atr"] = (0.5 / LEV - COST) / F["atrf"].to_numpy()   # the -50 % stop's price distance in 15m ATR
    F["lock10_atr"] = (FL / LEV + COST) / F["atrf"].to_numpy()    # the +10 % first lock's price distance in 15m ATR
    F["chase"] = np.where(s > 0, (p24 >= 0.9) | (p7 >= 0.8), (p24 <= 0.1) | (p7 <= 0.2))
    cl = R.close.to_numpy()
    F["d_e21_atr"] = (cl - R.e21.to_numpy()) * s / atr[i]
    F["d_e52_atr"] = (cl - R.e52.to_numpy()) * s / atr[i]
    F["rsi_side"] = 50 + s * (R.rsi.to_numpy() - 50)
    F["roc_side"] = s * R.roc.to_numpy()
    F["roc_jump"] = s * (R.roc.to_numpy() - R.rocp.to_numpy())
    h1 = s * R["1h_roc"].to_numpy() > 0
    h4 = s * R["4h_roc"].to_numpy() > 0
    F["conf_both"] = h1 & h4
    F["conf"] = np.where(h1 & h4, "both", np.where(h1, "1h", "4h"))
    return F


class warnings_off:
    def __enter__(self):
        import warnings
        self._w = warnings.catch_warnings()
        self._w.__enter__()
        warnings.simplefilter("ignore")

    def __exit__(self, *a):
        self._w.__exit__(*a)


def path_values(A, idx, k, r):
    """After-entry values of the taken rows idx (exit offsets k, net returns r): BTC's move with the side to the exit minute,
    the best move from the entry price before the exit, and in the 24 h after the exit."""
    bt = grid("BTCUSDT")
    out = {q: np.full(len(idx), np.nan) for q in ("btc_with", "mfe_px", "after_best_px")}
    out["after_trig"] = np.zeros(len(idx), bool)
    out["after_first"] = np.zeros(len(idx), np.int8)   # 1: back to +12 % first, -1: as far again against first, 0: neither
    for coin_i in np.unique(A.coin.to_numpy()[idx]):
        g = grid(COINS[coin_i])
        sel = np.flatnonzero(A.coin.to_numpy()[idx] == coin_i)
        for q in sel:
            row = idx[q]
            e, s, kq = int(A.e.iat[row]), int(A.side.iat[row]), int(k[q])
            p0 = g["o"][e]
            x = min(e + kq, g["n"] - 1)
            out["btc_with"][q] = s * (bt["c"][x] / bt["o"][e] - 1)
            if kq > 0:
                seg = slice(e, e + kq)
                out["mfe_px"][q] = ((g["h"][seg] / p0 - 1) if s > 0 else (1 - g["l"][seg] / p0)).max()
            aft = slice(e + kq + 1, min(g["n"], e + kq + 1 + 24 * 60))
            if aft.start < aft.stop:
                fav = (g["h"][aft] / p0 - 1) if s > 0 else (1 - g["l"][aft] / p0)
                adv = (g["l"][aft] / p0 - 1) if s > 0 else (1 - g["h"][aft] / p0)
                out["after_best_px"][q] = fav.max()
                up = TRIG / LEV + COST                     # back to the +12 % trigger (from the entry price)
                out["after_trig"][q] = fav.max() >= up
                fill = r[q] + COST                         # the exit, as a move from the entry (funding aside)
                dn = fill - (up - fill)                    # as far again past the exit, the other way
                iu = np.flatnonzero(fav >= up)
                idn = np.flatnonzero(adv <= dn)
                fu = iu[0] if len(iu) else 10**9
                fd = idn[0] if len(idn) else 10**9
                out["after_first"][q] = 1 if fu < fd else (-1 if fd < fu else 0)
    return out


# ====================================================================== accounts
def acct(t, k, r, why, use, a, z, keep=False):
    m = use & (t >= a) & (t < z)
    idx = take(t, k, m)
    roe = LEV * r[idx]
    n = len(idx)
    months = (z - a) / DAY / 30.44
    out = {"n": n, "per_month": rnd(n / months, 1)}
    if keep:
        out["_idx"] = idx
    if not n:
        return out
    win = roe > 0
    w, lo = roe[win], roe[~win]
    x = np.maximum(MARGIN * roe, -1.0)
    eq = np.cumprod(1 + x)
    aw = float(w.mean()) if len(w) else np.nan
    al = float(lo.mean()) if len(lo) else np.nan
    wy = why[idx]
    out.update({"wins": int(win.sum()), "losses": int((~win).sum()), "win": rnd(win.mean()),
                "avg_win_pct": rnd(aw * 100, 2), "avg_loss_pct": rnd(al * 100, 2),
                "breakeven_win": rnd(-al / (aw - al)) if len(w) and len(lo) else None,
                "roe_pct": rnd(roe.mean() * 100, 3), "gross_roe_pct": rnd((roe.mean() + LEV * COST) * 100, 3),
                "month_sum_pct": rnd(roe.mean() * 100 * n / months, 1),
                "mult40": rnd(eq[-1], 3), "maxdd40": rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3),
                "stop_share": rnd((wy == 0).mean()), "liquidated": int((r[idx] <= -1.0 / LEV + 1e-12).sum())})
    return out


def table(t, k, r, why, use):
    return {pn: acct(t, k, r, why, use, a, z) for pn, (a, z) in PER.items()}


def line(name, row):
    def f(p):
        v = row[p]
        return (f"{p[:4]} n{v['n']} {v.get('wins')}W{v.get('losses')}L w{v.get('win')} roe{v.get('roe_pct')} "
                f"aw{v.get('avg_win_pct')}/al{v.get('avg_loss_pct')} be{v.get('breakeven_win')} stop{v.get('stop_share')} x{v.get('mult40')}")
    return f"{name:22s} | " + " | ".join(f(p) for p in PER)


# ====================================================================== main
def main():
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG2.md"), "rb").read()).hexdigest()
    assert sha == open(os.path.join(RES_DIR, "PREREG2.md.sha256")).read().split()[0], "PREREG2.md changed after it was frozen"
    A = pd.read_pickle(ROWS)
    A = A[A.P & (A.block == "")].reset_index(drop=True)            # P's candidates after the entry blocks, in entry order
    t = A.t.to_numpy(np.int64)
    s = A.side.to_numpy()
    base = {q: A[f"L30_c042_own_{q}"].to_numpy() for q in ("r", "k", "why", "mae", "mfe")}
    every = np.ones(len(A), bool)
    # entry-time values
    F = pd.concat([coin_features(COINS[ci], A[A.coin == ci]) for ci in range(6)]).loc[A.index]
    A = pd.concat([A, F], axis=1)
    print("features", len(A), flush=True)

    # ---- P as in results.json (check), and its trades with every value
    res = {"prereg2_sha256": sha, "data_end_utc": str(pd.Timestamp(DATA_END, unit="ms")),
           "periods_utc": {k: [str(pd.Timestamp(a, unit="ms")), str(pd.Timestamp(z, unit="ms"))] for k, (a, z) in PER.items()}}
    P0 = table(t, base["k"], base["r"], base["why"], every)
    old = json.load(open(os.path.join(RES_DIR, "results.json")))["variants"]["P"]["c042"]
    for pn in PER:
        assert P0[pn]["n"] == old[pn]["n"] and P0[pn]["wins"] == old[pn]["wins"], (pn, P0[pn], old[pn]["n"])
    res["P"] = P0
    print(line("P", P0), flush=True)

    feats = ["adx15", "adx1h", "adx4h", "p24_side", "p7_side", "stop50_atr", "lock10_atr", "d_e21_atr", "d_e52_atr", "rsi_side", "roc_side", "roc_jump",
             "atrp15_pct", "atrp30_pct", "btc_with_pct", "mfe_roe_pct", "mfe_px_pct", "minutes"]
    flags = {"chase": lambda D: D.chase.astype(bool), "conf_both": lambda D: D.conf_both.astype(bool),
             "vote4h_against": lambda D: D.vote4h < 0, "vote4h_with": lambda D: D.vote4h > 0,
             "vol_top20": lambda D: D.atrp15 > D.atrp15_q80, "adx15_below20": lambda D: D.adx15 < 20,
             "adx4h_below20": lambda D: D.adx4h < 20}

    def trades_frame(pn):
        a, z = PER[pn]
        idx = take(t, base["k"], (t >= a) & (t < z))
        D = A.iloc[idx].copy()
        D["roe"] = LEV * base["r"][idx]
        D["why"] = base["why"][idx]
        D["minutes"] = base["k"][idx] + 1
        D["mfe_roe_pct"] = base["mfe"][idx] * 100
        D["mae_roe_pct"] = base["mae"][idx] * 100
        pv = path_values(A, idx, base["k"][idx], base["r"][idx])
        D["btc_with_pct"] = pv["btc_with"] * 100
        D["mfe_px_pct"] = pv["mfe_px"] * 100
        D["after_best_px_pct"] = pv["after_best_px"] * 100
        D["after_trig"] = pv["after_trig"]
        D["after_first"] = pv["after_first"]
        D["_idx"] = idx
        return D

    def medians(D):
        L, Wn = D[D.roe <= 0], D[D.roe > 0]
        m = {c: [rnd(L[c].median(), 3), rnd(Wn[c].median(), 3)] for c in feats}
        m.update({c: [rnd(f(L).mean(), 3), rnd(f(Wn).mean(), 3)] for c, f in flags.items()})
        return m

    T = {pn: trades_frame(pn) for pn in ("oct2026", "select", "confirm")}
    D = T["oct2026"]
    # the October losses one by one
    evs = [(e.ts_ms, e.kind) for e in EV.all_events()]
    rows = []
    for _, r in D[D.roe <= 0].iterrows():
        near = min(evs, key=lambda ev: abs(ev[0] - int(r.t))) if evs else None
        rows.append({
            "entry_kst": str(pd.Timestamp(int(r.t) + KST, unit="ms"))[:16], "coin": COINS[int(r.coin)][:-4],
            "side": "롱" if r.side > 0 else "숏", "net_roe_pct": rnd(r.roe * 100, 1), "account_pct": rnd(MARGIN * r.roe * 100, 1),
            "exit": REASONS[int(r.why)], "minutes": int(r.minutes),
            "adx15": rnd(r.adx15, 1), "adx1h": rnd(r.adx1h, 1), "adx4h": rnd(r.adx4h, 1),
            "p24": rnd(r.p24, 2), "p7": rnd(r.p7, 2), "chase": bool(r.chase),
            "d_e21_atr": rnd(r.d_e21_atr, 2), "d_e52_atr": rnd(r.d_e52_atr, 2), "rsi26": rnd(r.rsi, 1),
            "roc9": rnd(r.roc, 3), "roc9_prev": rnd(r.rocp, 3), "conf": r.conf,
            "roc9_1h": rnd(r["1h_roc"], 3), "roc9_4h": rnd(r["4h_roc"], 3),
            "vote4h": None if np.isnan(r.vote4h) else int(r.vote4h), "vote1h": None if np.isnan(r.vote1h) else int(r.vote1h),
            "atrp15_pct": rnd(r.atrp15_pct, 2), "atrp30_pct": rnd(r.atrp30_pct, 2), "vol_top20": bool(r.atrp15 > r.atrp15_q80),
            "atr15_px_pct": rnd(r.atrf * 100, 3), "stop50_atr": rnd(r.stop50_atr, 1),
            "after_entry_unknowable": {"btc_with_pct": rnd(r.btc_with_pct, 2), "mfe_roe_pct": rnd(r.mfe_roe_pct, 1),
                                       "mfe_px_pct": rnd(r.mfe_px_pct, 3), "after24h_best_px_pct": rnd(r.after_best_px_pct, 2),
                                       "after24h_reached_trigger": bool(r.after_trig),
                                       "after24h_first": {1: "back +12% first", -1: "further against first", 0: "neither"}[int(r.after_first)]},
            "nearest_macro": None if near is None else {"kind": near[1], "hours": rnd((int(r.t) - near[0]) / HOUR, 1)}})
    res["oct_losses"] = rows
    # medians: October losers / winners (and a label shuffle: how often a random split of the 64 shows as big a gap),
    # five-year losers / winners
    rng = np.random.default_rng(SEED)
    lab = (D.roe <= 0).to_numpy()
    perm = {}
    for c in list(feats) + list(flags):
        v = (flags[c](D).astype(float).to_numpy() if c in flags else D[c].to_numpy(float))
        stat = (lambda x, y: np.nanmean(x) - np.nanmean(y)) if c in flags else (lambda x, y: np.nanmedian(x) - np.nanmedian(y))
        obs = stat(v[lab], v[~lab])
        sh = np.empty(SHUFFLES)
        for d in range(SHUFFLES):
            p = rng.permutation(lab)
            sh[d] = stat(v[p], v[~p])
        perm[c] = rnd((np.abs(sh) >= abs(obs) - 1e-12).mean(), 3)
    res["compare"] = {"columns": "[losers, winners] medians (shares for flags)",
                      "oct2026": medians(D), "oct2026_shuffle_p": perm,
                      "select": medians(T["select"]), "confirm": medians(T["confirm"])}
    # how deep winners went first, how far losers went the right way first
    dd = {}
    for pn, Dq in T.items():
        Wn, L = Dq[Dq.roe > 0], Dq[Dq.roe <= 0]
        dd[pn] = {"winners_below": {f"{x}": rnd((Wn.mae_roe_pct < x).mean(), 3) for x in (-10, -20, -30, -40)},
                  "losers_reached": {f"+{x}": rnd((L.mfe_roe_pct >= x).mean(), 3) for x in (5, 10)},
                  "losers_stop": rnd((L.why == 0).mean(), 3)}
        S = Dq[Dq.why == 0]                                # the stops: what the price did in the 24 h after
        dd[pn]["stops_after24h"] = {"n": int(len(S)), "back_to_trigger": rnd(S.after_trig.mean(), 3),
                                    "back_first": rnd((S.after_first == 1).mean(), 3),
                                    "further_against_first": rnd((S.after_first == -1).mean(), 3),
                                    "neither": rnd((S.after_first == 0).mean(), 3)}
    res["depth"] = dd

    # ---- the stop grid (ladder unchanged)
    stops, same = {}, {}
    for name, kind, rs, kat in stop_settings():
        r = np.zeros(len(A)); k = np.zeros(len(A), np.int64); w = np.zeros(len(A), np.int8)
        for ci in range(6):
            g = grid(COINS[ci])
            cumf = np.cumsum(g["fund"])
            o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
            for side in (1, -1):
                m = ((A.coin == ci) & (A.side == side)).to_numpy()
                es = A.e.to_numpy(np.int64)[m]
                atrd = (np.full(m.sum(), np.inf) if kat is None else kat * A.atrf.to_numpy()[m])
                a_ = walk2(o, h, l, c, cumf, es, side, LEV, COST, FL, STEP, GAP, np.ascontiguousarray(atrd), rs, g["n"])
                r[m], k[m], w[m] = a_[0], a_[1], a_[2]
        if name == "ROE -50%":
            assert np.array_equal(k, base["k"]) and np.allclose(r, base["r"], atol=1e-15), "walk2 differs from frcore.walk"
        stops[name] = table(t, k, r, w, every)
        # the same entries as P (its October and five-year trades) under this stop
        sm = {}
        for pn in ("oct2026", "select", "confirm"):
            idx = T[pn]["_idx"].to_numpy()
            r0, r1 = LEV * base["r"][idx], LEV * r[idx]
            sm[pn] = {"wins_to_losses": int(((r0 > 0) & (r1 <= 0)).sum()), "losses_to_wins": int(((r0 <= 0) & (r1 > 0)).sum()),
                      "roe_pct": rnd(r1.mean() * 100, 3), "loss_avg_pct": rnd(r1[r0 <= 0].mean() * 100, 2)}
        same[name] = sm
        print(line(name, stops[name]), "| same entries", json.dumps(sm), flush=True)
    res["stops"] = stops
    res["stops_same_entries"] = same

    # ---- the fixes (stop -50 %, ladder unchanged), one at a time
    v4, vol = A.vote4h.to_numpy(), A.atrp15.to_numpy() > A.atrp15_q80.to_numpy()
    fx = {"F1 4시간 추세 반대 금지": ~(v4 < 0), "F2 변동성 상위 20% 금지": ~vol,
          "F3 15분 ADX 20 미만 금지": ~(A.adx15.to_numpy() < 20), "F4 4시간 ADX 20 미만 금지": ~(A.adx4h.to_numpy() < 20),
          "F5 추격 금지": ~A.chase.to_numpy(bool), "F6 1시간·4시간 둘 다": A.conf_both.to_numpy(bool),
          "F7 EMA21에서 1ATR 넘으면 금지": ~(A.d_e21_atr.to_numpy() > 1), "F8 EMA21에서 2ATR 넘으면 금지": ~(A.d_e21_atr.to_numpy() > 2),
          "F9 F1 + F2": ~(v4 < 0) & ~vol}
    fixes, swap = {}, {}
    p_oct = set(T["oct2026"]["_idx"].tolist())
    for name, m in fx.items():
        row = table(t, base["k"], base["r"], base["why"], m)
        a, z = PER["oct2026"]
        idx = take(t, base["k"], m & (t >= a) & (t < z))
        roe = LEV * base["r"]
        kept = set(idx.tolist())
        gone = sorted(p_oct - kept)
        new = sorted(kept - p_oct)
        swap[name] = {"P_losses_removed": int(sum(roe[i] <= 0 for i in gone)), "P_wins_removed": int(sum(roe[i] > 0 for i in gone)),
                      "new_trades": len(new), "new_wins": int(sum(roe[i] > 0 for i in new)), "new_losses": int(sum(roe[i] <= 0 for i in new)),
                      "candidates_removed_share_5y": rnd(1 - m[(t >= PER["select"][0]) & (t < PER["confirm"][1])].mean(), 3)}
        row["better_both_halves"] = bool(row["select"]["roe_pct"] > P0["select"]["roe_pct"] and row["confirm"]["roe_pct"] > P0["confirm"]["roe_pct"])
        row["positive_both_halves"] = bool(row["select"]["roe_pct"] > 0 and row["confirm"]["roe_pct"] > 0)
        fixes[name] = row
        print(line(name, row), "|", row["better_both_halves"], json.dumps(swap[name], ensure_ascii=False), flush=True)
    for name, row in stops.items():
        row["better_both_halves"] = bool(row["select"]["roe_pct"] > P0["select"]["roe_pct"] and row["confirm"]["roe_pct"] > P0["confirm"]["roe_pct"])
        row["positive_both_halves"] = bool(row["select"]["roe_pct"] > 0 and row["confirm"]["roe_pct"] > 0)
    res["fixes"] = fixes
    res["fixes_oct_swap"] = swap
    path = os.path.join(RES_DIR, "results2.json")
    if os.path.isfile(path):                                       # keep the P30 part (frp30.py, PREREG2_AMEND1)
        prev_ = json.load(open(path))
        if "P30" in prev_:
            res["P30"] = prev_["P30"]
    json.dump(res, open(path, "w"), ensure_ascii=False, indent=1, default=float)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 60)
    print(pd.DataFrame([{k: v for k, v in x.items() if not isinstance(v, dict)} | x["after_entry_unknowable"] for x in rows]).to_string())
    print(json.dumps(res["compare"], ensure_ascii=False))
    print(json.dumps(res["depth"], ensure_ascii=False))


if __name__ == "__main__":
    main()
