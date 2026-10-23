"""참고 read: the trades of 'VWAP 개선판' (PREREG_FWD1.md candidate A) over the rule bot's run (2026-10-05 19:30 UTC .. the
data end), the 6 stops one by one against the wins, with the same entry-time and path values as vwloss10.py.

    python3 -I vwloss6.py   -> research/vwap30/loss6.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwfix2 import *
from vwloss10 import path, trade_k
from vwacct import _take


def main():
    lib = sweepsig.lib()
    parts = []
    for coin in COINS:
        R = rows_tf(coin, "30m", lib)
        R = R[(R.t >= START) & (R.t < DATA_END - MIN)].reset_index(drop=True)
        O = outcomes_tf(coin, R, 30)
        R["r"], R["x"] = O["base"]
        F = features(coin, "30m", bars(coin, "30m"), signals(coin, "30m"), grid(coin))
        F = F.set_index("bar_close")
        for c in ("day_pos", "p24", "p7", "chase", "wick_frac", "j1h_raw3", "relvol"):
            R[c] = F.loc[R.t.to_numpy(), c].to_numpy()
        parts.append(R)
    R = pd.concat(parts, ignore_index=True)
    t, coin = R.t.to_numpy(), R.coin.to_numpy()
    kst = pd.to_datetime(t + KST, unit="ms")
    wd = np.asarray(kst.dayofweek < 5)
    usop = np.array([bool(us_open_pause(int(x), 30, 30)) for x in t])
    macro = np.array([bool(EV.near(int(x), 30 * MIN, 30 * MIN)) for x in t])
    cand = wd & ~usop & ~macro & ~(R.j4h.to_numpy() < 0) & ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy())
    lev = np.minimum(LEVP, 0.5 / (2.0 * R.atrf.to_numpy() + COST_RT))
    o = np.lexsort((coin, t))
    ext = t[o] + (R.x.to_numpy()[o] + 1) * MIN
    idx = o[_take(t[o], ext, cand[o])]
    rows = []
    for q in idx:
        r = R.iloc[q]
        cn = COINS[int(r.coin)]
        e = int(r.e)
        s = int(r.side)
        k_exit = int(r.x)
        roe = float(r.r * lev[q])
        row = {"entry_kst": str(pd.Timestamp(int(r.t) + KST, unit="ms"))[:16], "coin": cn[:-4], "side": "롱" if s > 0 else "숏",
               "minutes": k_exit + 1, "lev": round(float(lev[q]), 1), "roe_pct": round(roe * 100, 1),
               "balance_pct": round(0.3 * roe * 100, 1), "win": bool(r.r > 0),
               "day_pos": round(float(r.day_pos), 2), "p24": round(float(r.p24), 2), "p7": round(float(r.p7), 2),
               "chase": bool(r.chase), "close_vwap_atr": round(float(r.cva), 2), "wick_frac": round(float(r.wick_frac), 2),
               "adx": round(float(r.adx), 1), "j1h": None if np.isnan(r.j1h_raw3) else float(r.j1h_raw3),
               "j4h": None if np.isnan(r.j4h) else float(r.j4h), "btc4": None if np.isnan(r.btc4) else float(r.btc4),
               "atr_pct": round(float(r.atrf * 100), 3), **path(cn, e, s, k_exit, float(r.atrf))}
        for kst_ in (1.5, 3.0):
            kk, ret = trade_k(cn, e, s, float(r.atrf), kst_)
            row[f"roe_stop{kst_:g}atr"] = round(ret * lev[q] * 100, 1)
        rows.append(row)
    D = pd.DataFrame(rows)
    L, W = D[~D.win], D[D.win]
    comp = {c: {"losses_median": round(float(L[c].median()), 3), "wins_median": round(float(W[c].median()), 3)}
            for c in ("day_pos", "p24", "p7", "close_vwap_atr", "wick_frac", "adx", "atr_pct", "mfe_pct", "btc_move_pct_with_side")}
    for c in ("chase", "after24h_reached_lock_trigger"):
        comp[c] = {"losses_share": round(float(L[c].mean()), 3), "wins_share": round(float(W[c].mean()), 3)}
    for c in ("j1h", "btc4"):
        comp[c + "_against_share"] = {"losses": round(float((L[c] < 0).mean()), 3), "wins": round(float((W[c] < 0).mean()), 3)}
    out = {"trades": len(D), "wins": int(D.win.sum()), "losses": int((~D.win).sum()), "loss_rows": L.to_dict("records"),
           "compare": comp, "all": D.to_dict("records")}
    json.dump(out, open(os.path.join(RES_DIR, "loss6.json"), "w"), ensure_ascii=False, indent=1, default=float)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(L[["entry_kst", "coin", "side", "minutes", "lev", "roe_pct", "balance_pct", "day_pos", "p24", "p7", "chase",
             "close_vwap_atr", "wick_frac", "adx", "j1h", "j4h", "btc4"]].to_string())
    print(L[["entry_kst", "atr_pct", "mfe_pct", "mfe_min", "btc_move_pct_with_side", "after24h_best_pct",
             "after24h_reached_lock_trigger", "roe_stop1.5atr", "roe_stop3atr"]].to_string())
    print(json.dumps(comp, ensure_ascii=False))


if __name__ == "__main__":
    main()
