"""Verifier (lens: look-ahead / time alignment / data errors) -- step 2: every taken CONFIRM trade of B_sel_with20 (and
its coin-flip twin) re-checked from the RAW Binance 1m rows (fg1m/1m/<coin>.npz, own timestamps, looked up by time):

  * signal bar: the raw minutes with open in [t - tf, t) -- all strictly before the entry minute t; their close (the
    minute t - 1) must equal the study's bar close (bars() on the research grid)
  * entry: the raw minute that opens at t (= first minute after the signal bar) exists; its open = the grid's o[e]
  * higher bar: the study's htf index (rolesdata.htf_index) is a bar with open + htf <= t, and the next bar closes > t
  * the source state on that bar has the trade's side (with-condition)
  * the w35 exit walked here from the rule text (35x, net ROE -50 % stop, ladder +12 -> +10 then +5 steps, lock armed
    from the next minute, stop checked before the minute's new high, fill at the level or at the open when gapped
    through, cost 0.124 % round trip, funding of the minutes held) on raw minutes only from t on; must equal w35_r / k
  * one position: every taken trade enters after the previous one's exit minute
    python3 tz_b_hand.py <workdir> <fg1m dir>"""
import os
import sys
DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, DATA)
import rolesdata as RD          # noqa: E402
from common import *            # noqa: E402,F401

WD, FG = sys.argv[1], sys.argv[2]
LV, STOP = 35.0, -0.50


def lock_for(best):
    if best < 0.12 - 1e-12:
        return None
    return 0.10 + 0.05 * np.floor((best - 0.12) / 0.05 + 1e-9)


def walk(ts, o, h, l, f, t, s, p0):
    p = int(np.searchsorted(ts, t))
    best, lock, Fp = -1e9, None, 0.0
    gaps = 0
    q = p
    while q < len(ts):
        k = int((ts[q] - t) // MIN)
        if q > p and ts[q] - ts[q - 1] != MIN:
            gaps += 1
        F = Fp + s * f[q]
        level = STOP / LV + COST + Fp
        if lock is not None:
            level = max(level, lock / LV + COST + Fp)
        op = s * (o[q] / p0 - 1)
        fav = (h[q] / p0 - 1) if s > 0 else (1 - l[q] / p0)
        adv = (l[q] / p0 - 1) if s > 0 else (1 - h[q] / p0)
        if adv <= level:
            return max(min(level, op) - COST - F, -1 / LV), k, gaps
        hi = LV * (fav - COST - F)
        if hi > best:
            best = hi
            lock = lock_for(best)
        Fp = F
        q += 1
    return np.nan, -1, gaps


T = pd.read_pickle(os.path.join(WD, "B_taken_CONF.pkl")).sort_values("e").reset_index(drop=True)
# one position check
ex = T.e.to_numpy() + T.w35_k.to_numpy()
print("one-position overlaps:", int((T.e.to_numpy()[1:] <= ex[:-1]).sum()), "of", len(T) - 1)
# higher-bar alignment and state
idx = RD.htf_index(T, "1h")  # placeholder, replaced per htf below
rows = []
for htf in sorted(T.htf.unique()) if "htf" in T else []:
    pass
T["cellhtf"] = T.cell.str.split("|").str[1].str.split("@").str[1]
T["src"] = T.cell.str.split("|").str[1].str.split("@").str[0]
al_ok = np.zeros(len(T), bool)
st_ok = np.zeros(len(T), bool)
for h_ in T.cellhtf.unique():
    m = (T.cellhtf == h_).to_numpy()
    sub = T[m]
    ii = RD.htf_index(sub, h_)
    for ci, coin in enumerate(COINS):
        mc = sub.coin.to_numpy() == ci
        if not mc.any():
            continue
        Z = RD._states(coin, h_)
        cl = Z["ts"] + TF_MIN[h_] * MIN
        j = ii[mc]
        tt = sub.t.to_numpy(np.int64)[mc]
        ok = (cl[j] <= tt) & ((j + 1 >= len(cl)) | (cl[np.minimum(j + 1, len(cl) - 1)] > tt))
        src = sub.src.to_numpy()[mc]
        v4 = sum(Z[f"j_{k}"].astype(int) for k in ("V39", "S6", "OBV", "N12"))
        v4 = np.where(np.abs(v4) == 4, np.sign(v4), 0)
        sv = np.array([v4[jj] if s_ == "j:V4OF4" else Z[f"{s_.split(':')[0]}_{s_.split(':')[1]}"][jj]
                       for s_, jj in zip(src, j)])
        pos = np.flatnonzero(m)[mc]
        al_ok[pos] = ok
        st_ok[pos] = sv == sub.side.to_numpy()[mc]
print("htf bar closed at or before t and next one after t:", int(al_ok.sum()), "/", len(T))
print("stored state == trade side (with):", int(st_ok.sum()), "/", len(T))

out = []
for ci, coin in enumerate(COINS):
    sub = T[T.coin == ci]
    if not len(sub):
        continue
    z = np.load(os.path.join(FG, "1m", f"{coin}.npz"))
    ts, o, h, l, c, f = (z[k] for k in ("ts", "o", "h", "l", "c", "fund"))
    G = grid(coin)
    for _, r in sub.iterrows():
        t = int(r.t)
        tfm = TF_MIN[r.tf]
        a, b = np.searchsorted(ts, [t - tfm * MIN, t])
        nmin = b - a
        bar_close_raw = c[b - 1] if nmin > 0 and ts[b - 1] == t - MIN else np.nan
        e = int(r.e)
        bar_close_grid = G["c"][e - 1]
        p = int(np.searchsorted(ts, t))
        has_entry = p < len(ts) and ts[p] == t
        p0 = o[p] if has_entry else np.nan
        rec = {"coin": coin, "t": t, "tf": r.tf, "name": r["name"], "cell": r.cell, "side": int(r.side),
               "bar_minutes": nmin, "last_bar_minute_before_t": bool(nmin > 0 and ts[b - 1] < t),
               "bar_close_eq": bool(np.isclose(bar_close_raw, bar_close_grid, rtol=0, atol=1e-9)),
               "entry_exists": has_entry, "entry_open_eq": bool(has_entry and np.isclose(p0, G["o"][e], rtol=0, atol=1e-9)),
               "r_grid": float(r.w35_r), "k_grid": int(r.w35_k), "r_opp_grid": float(r.w35_opp_r),
               "k_opp_grid": int(r.w35_opp_k)}
        if has_entry:
            rr, kk, gg = walk(ts, o, h, l, f, t, int(r.side), p0)
            ro, ko, go = walk(ts, o, h, l, f, t, -int(r.side), p0)
            rec.update(r_hand=rr, k_hand=kk, gaps=gg, r_opp_hand=ro, k_opp_hand=ko, gaps_opp=go)
        out.append(rec)
D = pd.DataFrame(out)
D["r_eq"] = np.isclose(D.r_hand, D.r_grid, atol=2e-6)
D["k_eq"] = D.k_hand == D.k_grid
D["ro_eq"] = np.isclose(D.r_opp_hand, D.r_opp_grid, atol=2e-6)
D["ko_eq"] = D.k_opp_hand == D.k_opp_grid
D.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tz_b_hand.csv"), index=False)
print(D[["last_bar_minute_before_t", "bar_close_eq", "entry_exists", "entry_open_eq", "r_eq", "k_eq", "ro_eq",
         "ko_eq"]].mean().round(5).to_string())
print("bar minutes == tf:", float((D.bar_minutes == D.tf.map(TF_MIN)).mean()))
bad = D[~(D.r_eq & D.k_eq)]
print("mismatches", len(bad))
print(bad[["coin", "t", "tf", "name", "side", "r_grid", "r_hand", "k_grid", "k_hand", "gaps"]].head(20).to_string())
print("mean ROE grid", 35 * D.r_grid.mean(), "hand", 35 * D.r_hand.mean(), "opp grid", 35 * D.r_opp_grid.mean(),
      "opp hand", 35 * D.r_opp_hand.mean())
print("mean ROE hand + payback", 35 * (D.r_hand + PAYBACK).mean(), "win", (D.r_hand > 0).mean(), "n", len(D))
