"""참고 read for the owners' question of 10/23: the 55 trades of VWAP fail 30m under the paper rules with the live bot's
entry blocks (paper19.json), the 10 stops one by one against the 45 wins: where the entry sat (day / 24h / 7-day range,
distance from VWAP), the trend judges and BTC at entry, how far it went the right way before the stop, whether a closed
30m bar reclaimed VWAP before the stop, what the price did after the stop, and the same trade with a 1 / 1.5 / 3 ATR stop.

    python3 -I vwloss10.py   -> research/vwap30/loss10.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwpaper19 as P
from vwpaper19 import *
from vwbuild import features, lock_house

ACC = "페이퍼 규칙 + 실거래봇 진입 금지(주말·발표·개장) | VWAP 복귀 실패 30분"


def trade_k(coin, e, s, atrf, k_stop):
    """paper_trade with a k ATR stop (same ladder, 96-bar cap): (minutes to exit, net price return)."""
    g = grid(coin)
    end = min(g["n"], e + CAP)
    o, h, l, c = (g[x][e:end] for x in ("o", "h", "l", "c"))
    p0 = o[0]
    UP = (h / p0 - 1) if s > 0 else (1 - l / p0)
    DN = (l / p0 - 1) if s > 0 else (1 - h / p0)
    OP = s * (o / p0 - 1)
    RMUp = np.r_[0.0, np.maximum.accumulate(UP)[:-1]]
    lk = lock_house(LEV_P * (RMUp - COST_RT))
    level = np.maximum(np.where(np.isnan(lk), -np.inf, lk / LEV_P + COST_RT), -k_stop * atrf)
    hit = np.flatnonzero(DN <= level)
    if len(hit):
        k = int(hit[0])
        return k, float(min(level[k], OP[k]) - COST_RT)
    return len(o) - 1, float(s * (c[-1] / p0 - 1) - COST_RT)


def path(coin, e, s, k_exit, atrf):
    g = grid(coin)
    p0 = g["o"][e]
    seg = slice(e, e + k_exit + 1)
    fav = (g["h"][seg] / p0 - 1) if s > 0 else (1 - g["l"][seg] / p0)
    adv = (g["l"][seg] / p0 - 1) if s > 0 else (1 - g["h"][seg] / p0)
    after = slice(e + k_exit + 1, min(g["n"], e + k_exit + 1 + 24 * 60))
    fav_after = ((g["h"][after] / p0 - 1) if s > 0 else (1 - g["l"][after] / p0)) if after.start < after.stop else np.array([np.nan])
    trig = (0.12 / LEV_P + COST_RT)                        # price move that reaches +12 % net ROE (the first lock)
    bt = grid("BTCUSDT")
    btc = s * (bt["c"][e + k_exit] / bt["o"][e] - 1)
    return {"mfe_pct": round(float(fav.max() * 100), 3), "mfe_min": int(fav.argmax()), "mae_pct": round(float(adv.min() * 100), 3),
            "stop_dist_pct": round(float(2 * atrf * 100), 3),
            "after24h_best_pct": round(float(np.nanmax(fav_after) * 100), 3),
            "after24h_reached_lock_trigger": bool(np.nanmax(fav_after) >= trig),
            "btc_move_pct_with_side": round(float(btc * 100), 3)}


def vwap_reclaim(df, vw, i_entry, bar_exit_close, s):
    """Did a 30m bar after the entry close on the wrong side of the day's VWAP before the exit?"""
    ts = df.ts.to_numpy(np.int64) + 30 * MIN
    c = df.close.to_numpy(float)
    j = np.flatnonzero((ts > ts[i_entry]) & (ts <= bar_exit_close))
    bad = (c[j] > vw[j]) if s < 0 else (c[j] < vw[j])
    return bool(bad.any()), (int(np.argmax(bad)) + 1 if bad.any() else None)


def main():
    acc = json.load(open(os.path.join(RES_DIR, "paper19.json")))["accounts"][ACC]
    T = pd.DataFrame(acc["trades"])
    T["t"] = pd.to_datetime(T.entry_utc).astype("int64") // 10**6
    T["t_exit"] = pd.to_datetime(T.exit_utc).astype("int64") // 10**6
    T["coin_full"] = T.coin + "USDT"
    rows = []
    lib = sweepsig.lib()
    for coin in sorted(T.coin_full.unique()):
        g = grid(coin)
        df = bars(coin, "30m")
        sg = signals(coin, "30m", df)
        F = features(coin, "30m", df, sg, g)
        F["i"] = sg.i.to_numpy()
        F["atr14"] = lib.fg.atr(df, 14).to_numpy(float)[sg.i.to_numpy()]
        ts = df.ts.to_numpy(np.int64)
        day = ts // DAY
        tp = (df.high + df.low + df.close).to_numpy(float) / 3
        v = df.volume.to_numpy(float)
        vw = pd.Series(tp * v).groupby(day).cumsum().to_numpy() / pd.Series(v).groupby(day).cumsum().to_numpy()
        for r in T[T.coin_full == coin].itertuples():
            f = F[F.bar_close == r.t]
            assert len(f) == 1, (coin, r.entry_utc)
            f = f.iloc[0]
            s = 1 if r.side == "롱" else -1
            e = (r.t - T0) // MIN
            atrf = float(f.atr14 / g["o"][e])
            k_exit = (r.t_exit - r.t) // MIN - 1
            row = {"coin": r.coin, "side": r.side, "entry_kst": str(pd.Timestamp(r.t + KST, unit="ms"))[:16],
                   "minutes": int(k_exit + 1), "roe_pct": round(r.roe * 100, 1), "win": r.roe > 0, "why": r.why,
                   "kst_hour": int(f.kst_hour), "day_pos": round(float(f.day_pos), 2), "p24": round(float(f.p24), 2),
                   "p7": round(float(f.p7), 2), "chase": bool(f.chase), "close_vwap_atr": round(float(f.close_vwap_atr), 2),
                   "brk_depth_atr": round(float(f.brk_depth_atr), 2) if np.isfinite(f.brk_depth_atr) else None,
                   "wick_frac": round(float(f.wick_frac), 2), "relvol": round(float(f.relvol), 2), "adx": round(float(f.adx), 1),
                   "ema4h50_with": float(f.ema4h50), "ema1d20_with": float(f.ema1d20),
                   "j1h_raw3": None if np.isnan(f.j1h_raw3) else float(f.j1h_raw3),
                   "j4h_raw3": None if np.isnan(f.j4h_raw3) else float(f.j4h_raw3),
                   **path(coin, e, s, k_exit, atrf)}
            rec, bars_to = vwap_reclaim(df, vw, int(f.i), r.t_exit, s)
            row["vwap_reclaim_before_exit"], row["reclaim_bar"] = rec, bars_to
            for kst in (1.0, 1.5, 3.0):
                kk, ret = trade_k(coin, e, s, atrf, kst)
                row[f"roe_stop{kst:g}atr"] = round(ret * LEV_P * 100, 1)
            rows.append(row)
    D = pd.DataFrame(rows).sort_values("entry_kst").reset_index(drop=True)
    L, W = D[~D.win], D[D.win]
    cols = ["day_pos", "p24", "p7", "close_vwap_atr", "brk_depth_atr", "wick_frac", "relvol", "adx", "mfe_pct", "stop_dist_pct",
            "btc_move_pct_with_side"]
    comp = {c: {"losses_median": round(float(L[c].median()), 3), "wins_median": round(float(W[c].median()), 3)} for c in cols}
    for c in ("chase", "vwap_reclaim_before_exit", "after24h_reached_lock_trigger"):
        comp[c] = {"losses_share": round(float(L[c].mean()), 3), "wins_share": round(float(W[c].mean()), 3)}
    for c in ("ema4h50_with", "ema1d20_with", "j1h_raw3", "j4h_raw3"):
        comp[c + "_against_share"] = {"losses": round(float((L[c] < 0).mean()), 3), "wins": round(float((W[c] < 0).mean()), 3)}
    alt = {f"stop{k:g}atr": {"sum_roe_losses": round(float(L[f"roe_stop{k:g}atr"].sum()), 1),
                             "sum_roe_wins": round(float(W[f"roe_stop{k:g}atr"].sum()), 1),
                             "wins_turned_losses": int((W[f"roe_stop{k:g}atr"] <= 0).sum()),
                             "losses_turned_wins": int((L[f"roe_stop{k:g}atr"] > 0).sum())} for k in (1.0, 1.5, 3.0)}
    alt["stop2atr(지금)"] = {"sum_roe_losses": round(float(L.roe_pct.sum()), 1), "sum_roe_wins": round(float(W.roe_pct.sum()), 1)}
    out = {"account": ACC, "losses": L.to_dict("records"), "compare": comp, "alt_stops": alt, "all": D.to_dict("records")}
    json.dump(out, open(os.path.join(RES_DIR, "loss10.json"), "w"), ensure_ascii=False, indent=1, default=float)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(L[["entry_kst", "coin", "side", "minutes", "roe_pct", "day_pos", "p24", "p7", "close_vwap_atr", "mfe_pct", "mfe_min",
             "stop_dist_pct", "vwap_reclaim_before_exit", "after24h_best_pct", "after24h_reached_lock_trigger",
             "btc_move_pct_with_side", "j1h_raw3", "j4h_raw3", "ema4h50_with", "roe_stop1atr", "roe_stop1.5atr", "roe_stop3atr"]]
          .to_string())
    print(json.dumps(comp, ensure_ascii=False, indent=0))
    print(json.dumps(alt, ensure_ascii=False))


if __name__ == "__main__":
    main()
