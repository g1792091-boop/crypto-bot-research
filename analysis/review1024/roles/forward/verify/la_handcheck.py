"""Look-ahead verifier, step 2: hand-recheck a random sample of forward entry signals from the raw 1m bars.
For each sampled signal (non-trend entry strategy, auto mapping):
  A. rebuild the higher bars from the raw 1m arrays myself, emulate the live bot's Klines.frame at t + 10 s (the bar
     closing at the boundary <= t, the last 300 closed bars only, nothing after), run paperbot.trendjudge.judge_frame,
     compare the 4 votes / raw3 / dir with the stored J<htf>_* columns; check judged bar close <= t < next close.
  B. walk the owners' exit (35x, net ROE -50 % stop, +12 -> +10 then every 5 %) myself from the entry minute (the minute
     opening at the signal bar close) on the raw 1m bars, and compare r / k / why with the stored w35 columns (both sides).
Run from this folder without -I:  python3 la_handcheck.py [n_per_tf]"""
import sys
import math
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
from paperbot import trendjudge as TJ

NPT = int(sys.argv[1]) if len(sys.argv) > 1 else 25
COST_ = 2 * (0.00042 + 0.0002)


def my_bars(g, tf_min, open_ts_list):
    """Aggregate 1m arrays into bars whose open times are open_ts_list (ms)."""
    rows = []
    for ts in open_ts_list:
        i0 = (ts - T0) // MIN
        i1 = i0 + tf_min
        o = g["o"][i0]; c = g["c"][i1 - 1]
        h = np.max(g["h"][i0:i1]); l_ = np.min(g["l"][i0:i1]); v = np.sum(g["v"][i0:i1])
        rows.append((ts, o, h, l_, c, v))
    a = np.array(rows, float)
    return pd.DataFrame({"ts": pd.to_datetime(a[:, 0].astype(np.int64), unit="ms"), "open": a[:, 1], "high": a[:, 2],
                         "low": a[:, 3], "close": a[:, 4], "volume": a[:, 5]})


def my_walk(g, e_idx, side, lev=35.0, stop=-0.5, n_end=None):
    o, h, l_, c = g["o"], g["h"], g["l"], g["c"]
    n_end = len(c) if n_end is None else n_end
    p0 = o[e_idx]
    best, lock = -1e9, None
    i = e_idx
    while i < n_end:
        lv_roe = stop if lock is None else max(stop, lock)
        why = 0 if lock is None or lock <= stop else 1
        if side > 0:
            worst, bp, op = l_[i] / p0 - 1, h[i] / p0 - 1, o[i] / p0 - 1
        else:
            worst, bp, op = 1 - h[i] / p0, 1 - l_[i] / p0, 1 - o[i] / p0
        lvl = lv_roe / lev + COST_
        if worst <= lvl:
            r = min(lvl, op) - COST_
            return max(r, -1 / lev), i - e_idx, why
        rb = lev * (bp - COST_)
        if rb > best:
            best = rb
            if best >= 0.12 - 1e-12:
                lock = 0.10 + 0.05 * math.floor((best - 0.12) / 0.05 + 1e-9)
        i += 1
    return max(side * (c[n_end - 1] / p0 - 1) - COST_, -1 / lev), n_end - 1 - e_idx, 3


def main():
    S = load("sig")
    S = S[S.role != "trend"].reset_index(drop=True)
    rng = np.random.default_rng(20261024)
    pick = []
    for tf in TFS:
        idx = np.flatnonzero((S.tf.to_numpy() == tf) & (S.w35_why.to_numpy() != 3))
        pick += list(rng.choice(idx, NPT, replace=False))
    P = S.loc[sorted(pick)].copy()
    rules = TJ.TrendRules()
    res = []
    for ci, coin in enumerate(COINS):
        Q = P[P.coin == ci]
        if not len(Q):
            continue
        g = grid(coin)
        for _, r in Q.iterrows():
            tf, t, side, e = r.tf, int(r.t), int(r.side), int(r.e)
            htf = AUTO[tf]
            hm = TF_MIN[htf] * MIN
            tdec = t + 10_000
            need = tdec - tdec % hm - hm
            opens = [need - k * hm for k in range(299, -1, -1)]
            df = my_bars(g, TF_MIN[htf], opens)
            j = TJ.judge_frame(df, coin, htf, rules)
            nxt_close = need + 2 * hm
            out = {"coin": coin, "tf": tf, "name": r["name"], "t_kst": str(kst([t])[0]), "side": side, "htf": htf,
                   "bar_close_le_t": j.bar_close <= t, "next_close_gt_t": nxt_close > t,
                   "bar_close_kst": str(kst([j.bar_close])[0]),
                   "dir_mine": j.dir, "dir_stored": int(np.nan_to_num(r[f"J{htf}_dir"])),
                   "raw_mine": j.raw, "raw_stored": int(np.nan_to_num(r[f"J{htf}_raw3"])),
                   "votes_ok": all(j.votes[k] == int(np.nan_to_num(r[f"J{htf}_{k}"])) for k in ("V39", "S6", "OBV", "N12")),
                   "adx_diff": abs(j.adx - float(r[f"J{htf}_adx"]))}
            # entry minute and outcome
            e_idx = (t - T0) // MIN
            out["e_is_t"] = (e_idx == e)
            for sfx, sd in (("", side), ("_opp", -side)):
                rr, kk, ww = my_walk(g, e_idx, sd)
                out[f"r{sfx}_mine"], out[f"k{sfx}_mine"], out[f"why{sfx}_mine"] = rr, kk, ww
                out[f"r{sfx}_st"], out[f"k{sfx}_st"], out[f"why{sfx}_st"] = float(r[f"w35{sfx}_r"]), int(r[f"w35{sfx}_k"]), int(r[f"w35{sfx}_why"])
            # previous-minute leakage check: the signal bar's last 1m close is the bar close; entry price is the next open
            out["p0"] = g["o"][e_idx]
            out["sig_bar_close"] = g["c"][e_idx - 1]
            res.append(out)
        drop(coin)
    R = pd.DataFrame(res)
    R["dir_ok"] = R.dir_mine == R.dir_stored
    R["raw_ok"] = R.raw_mine == R.raw_stored
    R["r_ok"] = (R.r_mine - R.r_st).abs() < 1e-6
    R["k_ok"] = R.k_mine == R.k_st
    R["why_ok"] = R.why_mine == R.why_st
    R["ropp_ok"] = (R.r_opp_mine - R.r_opp_st).abs() < 1e-6
    R["kopp_ok"] = R.k_opp_mine == R.k_opp_st
    R.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "la_handcheck.csv"), index=False)
    cols = ["bar_close_le_t", "next_close_gt_t", "dir_ok", "raw_ok", "votes_ok", "e_is_t", "r_ok", "k_ok", "why_ok", "ropp_ok", "kopp_ok"]
    print("n", len(R))
    print(R[cols].mean().round(4).to_string())
    print("adx max diff", R.adx_diff.max())
    bad = R[~R[cols].all(axis=1)]
    print(bad.to_string() if len(bad) else "no mismatches")
    print(R[["coin", "tf", "name", "t_kst", "side", "htf", "bar_close_kst", "dir_mine", "r_mine", "k_mine", "why_mine"]].head(12).to_string())


if __name__ == "__main__":
    main()
