"""Why the VWAP-fail 30m trades lose (the owners, 10/23: "5년 손실이 왜 반복되는지 찾아야지"). Descriptive, chooses nothing.

1. The rule bot's own form (B1 exits: 2 ATR stop + its ladder at 30x; margin 30 % of the balance at 30x = 9x exposure,
   one position across the six coins) over 2020-03 .. 2026-10-20: every 19-day stretch (the rule bot has run 19 days),
   how often it looked like now and what came after.
2. Every trade of that pass, with what happened after the entry (from the 1m path): how far it went our way first, how
   fast the stop came, whether a 30m bar closed back across VWAP first, BTC's move meanwhile, the day's range, the
   volume of the bar that hit the stop, how many coins stood on the trade's side of VWAP at the entry, earlier losses
   that day. Winners vs losers, select period (2020-03 .. 2024-12) and confirm period (2025-01 .. 2026-09) apart.

    python3 -I vwautopsy.py      -> OUT/autopsy_trades.pkl, research/vwap30/autopsy.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwacct import *

EXPO = 9.0                    # rule bot: margin 30 % of the balance at 30x
WIN_D = 19                    # days the rule bot has run
RES_DIR = os.path.abspath(os.path.join(HERE, ".."))
PERIODS["all"] = (SEL[0], DATA_END)


def vwap_30m(coin):
    df = bars(coin, "30m")
    h, l, c, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    ts = df.ts.to_numpy(np.int64)
    day = ts // DAY
    pv = pd.Series((h + l + c) / 3 * v).groupby(day).cumsum().to_numpy()
    cv = pd.Series(v).groupby(day).cumsum().to_numpy()
    with np.errstate(all="ignore"):
        vw = np.where(cv > 0, pv / cv, np.nan)
    vol20 = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    return {"ts": ts, "day": day, "h": h, "l": l, "c": c, "v": v, "vw": vw, "vol20": vol20}


def rolling(book, idx, net, ext):
    """19-day stretches by entry day (KST), exposure 9x."""
    x = np.maximum(EXPO * net, -1.0)
    kday = (book.entry[idx] + KST) // DAY
    d0, d1 = (SEL[0] + KST) // DAY, (DATA_END + KST) // DAY
    lg = np.log1p(np.maximum(x, -1 + 1e-12))
    per_day = np.zeros(d1 - d0 + 1)
    np.add.at(per_day, kday - d0, lg)
    cs = np.r_[0.0, np.cumsum(per_day)]
    n = len(per_day) - WIN_D + 1
    w = np.expm1(cs[WIN_D:WIN_D + n] - cs[:n])                    # stretch starting each day
    nxt = np.full(n, np.nan)
    nxt[:n - WIN_D] = w[WIN_D:]                                    # the next 19 days
    nxt60 = np.full(n, np.nan)
    m60 = n - WIN_D - 60 + WIN_D
    for k in range(max(0, n - WIN_D)):
        e = k + WIN_D + 60
        if e < len(cs):
            nxt60[k] = np.expm1(cs[e] - cs[k + WIN_D])
    days = pd.to_datetime((np.arange(n) + d0) * DAY, unit="ms")
    return pd.DataFrame({"start": days, "ret19": w, "next19": nxt, "next60": nxt60})


def main():
    b = Book("30m")
    m = np.ones(len(b.entry), bool)
    a, z = PERIODS["all"]
    idx, net, ext, D = trades(b, m & (b.entry >= a) & (b.entry < z), EX_B1)
    F = b.F.iloc[idx].reset_index(drop=True)
    t_exit = b.t[idx, EX_B1]
    out = {}
    # 1. 19-day stretches
    R = rolling(b, idx, net, ext)
    live_now = R[R.start == pd.Timestamp("2026-10-06")]
    good = R[R.ret19 >= 0.5]
    out["stretch19"] = {
        "n": int(len(R)), "share_pos": round(float((R.ret19 > 0).mean()), 4),
        "share_ge50": round(float((R.ret19 >= 0.5).mean()), 4),
        "q": {str(q): round(float(R.ret19.quantile(q)), 4) for q in (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)},
        "sim_from_1006": round(float(live_now.ret19.iloc[0]), 4) if len(live_now) else None,
        "after_ge50_next19_median": round(float(good.next19.median()), 4),
        "after_ge50_next19_pos": round(float((good.next19.dropna() > 0).mean()), 4),
        "after_ge50_next60_median": round(float(good.next60.median()), 4),
        "after_ge50_next60_pos": round(float((good.next60.dropna() > 0).mean()), 4),
        "by_year_pos": {str(y): round(float((g.ret19 > 0).mean()), 3) for y, g in R.groupby(R.start.dt.year)},
        "by_year_ge50": {str(y): int((g.ret19 >= 0.5).sum()) for y, g in R.groupby(R.start.dt.year)},
    }
    # the whole run at 9x, year by year
    x = np.maximum(EXPO * net, -1.0)
    yr = pd.to_datetime(b.entry[idx] + KST, unit="ms").year
    out["year_9x"] = {str(y): {"n": int((yr == y).sum()), "win": round(float((net[yr == y] > 0).mean()), 4),
                               "mult": round(float(np.prod(1 + x[yr == y])), 4)} for y in sorted(set(yr))}
    # 2. after-entry anatomy
    g = {c: grid(c) for c in COINS}
    V = {c: vwap_30m(c) for c in COINS}
    btc = g["BTCUSDT"]
    rows = []
    for q in range(len(idx)):
        c, s, bc = F.coin.iloc[q], int(F.side.iloc[q]), int(F.bar_close.iloc[q])
        e = (bc - T0) // MIN
        te = int(t_exit[q])
        ep = F.entry_px.iloc[q]
        hh, ll = g[c]["h"][e:e + te + 1], g[c]["l"][e:e + te + 1]
        fav = (hh.max() / ep - 1) if s > 0 else (1 - ll.min() / ep)
        adv = (1 - ll.min() / ep) if s > 0 else (hh.max() / ep - 1)
        # minutes until the best price (MFE) was printed
        k_fav = int(np.argmax(hh) if s > 0 else np.argmin(ll))
        vv = V[c]
        bi = int(np.searchsorted(vv["ts"], bc - 30 * MIN))         # the signal bar
        rec = None
        for k in range(1, 40):
            j = bi + k
            if j >= len(vv["ts"]) or vv["day"][j] != vv["day"][bi]:
                break
            if (s < 0 and vv["c"][j] > vv["vw"][j]) or (s > 0 and vv["c"][j] < vv["vw"][j]):
                rec = k
                break
        rec_min = rec * 30 if rec else np.nan                         # minutes from entry to that bar's close
        xb = (bc + (te + 1) * MIN - T0) // MIN
        btc_mv = (btc["c"][min(xb, len(btc["c"]) - 1)] / btc["o"][e] - 1) * s
        di = vv["day"][bi]
        dsel = vv["day"] == di
        drange = (vv["h"][dsel].max() - vv["l"][dsel].min()) / F.atr.iloc[q]
        sb = bi + 1 + (te // 30)                                      # the bar the exit fell in
        sb = min(sb, len(vv["v"]) - 1)
        relv_exit = vv["v"][sb] / vv["vol20"][sb] if vv["vol20"][sb] > 0 else np.nan
        # breadth: coins whose last closed 30m bar is on the trade's side of VWAP
        br = 0
        for c2 in COINS:
            v2 = V[c2]
            j2 = int(np.searchsorted(v2["ts"], bc - 30 * MIN))
            if j2 < len(v2["ts"]) and v2["ts"][j2] == bc - 30 * MIN and np.isfinite(v2["vw"][j2]):
                br += int((v2["c"][j2] - v2["vw"][j2]) * s > 0)
        rows.append({"fav_pct": fav * 100, "adv_pct": adv * 100, "fav_atr": fav / F.atrf.iloc[q],
                     "min_to_best": k_fav, "min_to_exit": te + 1, "reclaim_min": rec_min, "drange_atr": drange,
                     "btc_move_pct": btc_mv * 100, "relvol_exit_bar": relv_exit, "breadth": br})
    A = pd.concat([F[["coin", "side", "bar_close", "kst_hour", "weekend", "atrf", "close_vwap_atr", "wick_frac",
                      "brk_depth_atr", "relvol", "adx", "atrp", "atrp_q20", "atrp_q80", "j4h_raw3", "j1h_raw3", "chase"]],
                   pd.DataFrame(rows)], axis=1)
    A["net_pct"] = net * 100
    A["win"] = net > 0
    A["stop_pct"] = (D - COST_RT) * 100
    A["period"] = np.where(A.bar_close < SEL[1], "select", np.where(A.bar_close < CONF[1], "confirm", "live"))
    # losses earlier the same KST day on the same coin / any coin
    kd = (A.bar_close + KST) // DAY
    A["loss_before_today_coin"] = 0
    A["loss_before_today_any"] = 0
    seen_c, seen_a = {}, {}
    for q in range(len(A)):
        k1, k2 = (kd.iloc[q], A.coin.iloc[q]), kd.iloc[q]
        A.iat[q, A.columns.get_loc("loss_before_today_coin")] = seen_c.get(k1, 0)
        A.iat[q, A.columns.get_loc("loss_before_today_any")] = seen_a.get(k2, 0)
        if not A.win.iloc[q]:
            seen_c[k1] = seen_c.get(k1, 0) + 1
            seen_a[k2] = seen_a.get(k2, 0) + 1
    A.to_pickle(os.path.join(OUT, "autopsy_trades.pkl"))
    R.to_pickle(os.path.join(OUT, "stretch19.pkl"))
    json.dump(out, open(os.path.join(RES_DIR, "autopsy.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=float)[:3000])


if __name__ == "__main__":
    main()
