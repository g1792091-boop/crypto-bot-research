"""Data and hand checks for OBV30@4h > SRSI_X@1h | a2 in the last 19 days, against the rule bot's OWN 1m bars
(export current/live_bars.csv, extracted as data only; path passed as argument).

 1. grid vs live_bars minute by minute (open/high/low/close/volume) for every coin on the overlap before GRID_END
    (after GRID_END the grid IS live_bars, so that part is not an independent check).
 2. Every forward row of vrebuild.py (rows_ok.csv.gz): the 1h signal bar and the 4h trend bar rebuilt from live_bars where
    live_bars cover them; the 4h bar's close <= the signal time, the entry price = live_bars open of the entry minute.
 3. A scalar (third) walk of each forward trade on live_bars only (entry, stop, ladder, exit), compared with the row.
Writes vdata.json and handcheck_fwd.csv.

    python3 vdata.py <live_bars.csv>
"""
import os
import sys
import json

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import grid, drop, ms, T0, MIN, COINS, COST, GRID_END, KST  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEV = 30.0
FL, STEP, GAP = 0.10, 0.05, 0.02


def lock_for(best):
    ft = FL + GAP
    if not best >= ft - 1e-12:
        return None
    return FL + STEP * np.floor((best - ft) / STEP + 1e-9)


def scalar_walk(lb, e_ms, s, atr_abs, fund0=True):
    """Minute-by-minute walk on live_bars rows (dict ts -> (o,h,l,c)), funding 0 (October)."""
    o0 = lb[e_ms][0]
    stop_px_dist = 2.0 * atr_abs / o0
    best = -1e9
    lk = None
    t = e_ms
    while t in lb:
        o, h, l, c = lb[t]
        level = max(-1.0 / LEV + COST, -stop_px_dist)
        locked = lk is not None
        if locked:
            level = max(level, lk / LEV + COST)
        up = (h / o0 - 1) if s > 0 else (1 - l / o0)
        dn = (l / o0 - 1) if s > 0 else (1 - h / o0)
        op = s * (o / o0 - 1)
        if dn <= level:
            fill = min(level, op)
            r = max(fill - COST, -1.0 / LEV)
            return {"entry_px": o0, "exit_ms": t, "exit_px": o0 * (1 + s * fill), "r": r, "why": 1 if locked else 0,
                    "best_roe": best, "lock": lk}
        rup = LEV * (up - COST)
        if rup > best:
            best = rup
            lk = lock_for(best)
        t += MIN
    return {"entry_px": o0, "exit_ms": None, "r": np.nan, "why": 3, "best_roe": best, "lock": lk}


def main(path):
    LB = pd.read_csv(path, usecols=["ts", "symbol", "open", "high", "low", "close", "volume"])
    out = {"data": {}}
    lbd = {}
    for coin in COINS:
        g = grid(coin)
        x = LB[LB.symbol == coin].sort_values("ts").drop_duplicates("ts")
        lbd[coin] = x
        y = x[x.ts < GRID_END]
        i = ((y.ts.to_numpy() - T0) // MIN).astype(np.int64)
        rec = {"minutes": int(len(y)), "first": str(pd.Timestamp(int(y.ts.iloc[0]), unit="ms")),
               "gaps_in_live_bars": int((np.diff(x.ts.to_numpy()) != MIN).sum())}
        for col, k in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v")):
            a, b = y[col].to_numpy(float), g[k][i]
            rel = np.abs(a - b) / np.maximum(np.abs(b), 1e-12)
            rec[f"{col}_max_rel_diff"] = float(rel.max())
            rec[f"{col}_n_diff_gt_1e-6"] = int((rel > 1e-6).sum())
        # the ext part (>= GRID_END) of the grid must equal live_bars too
        z = x[x.ts >= GRID_END]
        iz = ((z.ts.to_numpy() - T0) // MIN).astype(np.int64)
        iz_ok = iz < g["n"]
        rec["ext_minutes_in_grid"] = int(iz_ok.sum())
        rec["ext_close_equal"] = bool(np.allclose(z.close.to_numpy()[iz_ok], g["c"][iz[iz_ok]], rtol=0, atol=0))
        out["data"][coin] = rec
        drop(coin)
    R = pd.read_csv(os.path.join(HERE, "rows_ok.csv.gz"))
    a, b = ms("2026-10-05 15:00"), ms("2026-10-24 15:00")
    F = R[(R.t >= a) & (R.t < b)].copy().sort_values("t")
    hc = []
    for _, row in F.iterrows():
        x = lbd[row.coin]
        lb = {int(t): (o, h, l, c) for t, o, h, l, c in zip(x.ts, x.open, x.high, x.low, x.close)}
        rec = {"coin": row.coin, "signal_close_kst": str(pd.Timestamp(int(row.t) + KST, unit="ms")),
               "side": int(row.side), "k_prev": round(row.k_prev, 2), "k": round(row.k, 2),
               "trend_4h_bar_kst": f"{pd.Timestamp(int(row.j4_open) + KST, unit='ms')} .. {pd.Timestamp(int(row.j4_close) + KST, unit='ms')}",
               "trend_bar_closed_before_signal": bool(row.j4_close <= row.t),
               "trend_bar_is_last_closed": bool(row.t - row.j4_close < 240 * MIN),
               "row_entry_px": row.p0, "row_roe": row.roe, "row_why": int(row.why), "row_k_min": int(row.kk)}
        # 1h signal bar from live_bars (if covered)
        hb = x[(x.ts >= row.t - 60 * MIN) & (x.ts < row.t)]
        rec["lb_1h_minutes"] = len(hb)
        if len(hb) == 60:
            rec["lb_1h_close"] = float(hb.close.iloc[-1])
        h4 = x[(x.ts >= row.j4_open) & (x.ts < row.j4_close)]
        rec["lb_4h_minutes"] = len(h4)
        rec["lb_4h_last_minute_close_ms_le_signal"] = bool(len(h4) == 0 or int(h4.ts.max()) + MIN <= row.t)
        if int(row.t) in lb:
            w = scalar_walk(lb, int(row.t), int(row.side), row.atr)
            rec.update({"lb_entry_px": w["entry_px"], "lb_roe": LEV * w["r"], "lb_why": w["why"],
                        "lb_exit_kst": str(pd.Timestamp(int(w["exit_ms"]) + KST, unit="ms")) if w["exit_ms"] else "",
                        "lb_exit_px": w.get("exit_px", np.nan), "lb_k_min": (int((w["exit_ms"] - row.t) // MIN) if w["exit_ms"] else -1),
                        "lb_best_roe": w["best_roe"]})
        hc.append(rec)
    H = pd.DataFrame(hc)
    H.to_csv(os.path.join(HERE, "handcheck_fwd.csv"), index=False)
    m = H.lb_roe.notna() & (H.row_why != 3)
    out["fwd_rows"] = int(len(H))
    out["fwd_rows_walked_on_live_bars"] = int(m.sum())
    out["fwd_trend_bar_closed_all"] = bool(H.trend_bar_closed_before_signal.all())
    out["fwd_trend_bar_last_closed_all"] = bool(H.trend_bar_is_last_closed.all())
    out["fwd_lb_4h_last_minute_le_signal_all"] = bool(H.lb_4h_last_minute_close_ms_le_signal.all())
    out["fwd_entry_px_equal"] = int((np.abs(H.row_entry_px[m] - H.lb_entry_px[m]) / H.row_entry_px[m] < 1e-9).sum())
    out["fwd_roe_max_abs_diff"] = float(np.abs(H.row_roe[m] - H.lb_roe[m]).max())
    out["fwd_why_equal"] = int((H.row_why[m] == H.lb_why[m]).sum())
    out["fwd_k_equal"] = int((H.row_k_min[m] == H.lb_k_min[m]).sum())
    out["fwd_mean_roe_rows"] = float(H.row_roe[H.row_why != 3].mean())
    out["fwd_mean_roe_live_bars_walk"] = float(H.lb_roe[m].mean())
    json.dump(out, open(os.path.join(HERE, "vdata.json"), "w"), indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
