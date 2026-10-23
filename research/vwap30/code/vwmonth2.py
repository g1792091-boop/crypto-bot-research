"""참고 read: the live bot (deploy/combo.vwap.json: 'VWAP 개선판' + CMO sandwich 1h, A's gates, A's exits, one position)
month by month (KST) from 2020-03 to the data end, at margin 10 / 20 / 30 / 40 %, and at 40 % with the executor's
신호등 (signal light, deploy/vwap_switch.py: a new entry is followed only while the paper's last 20 closed trades won
75 % or more; fewer than 20: followed). The paper trades every signal either way; the light only decides which of its
trades the live account copies. Each month on its own (started fresh) and the whole run in one piece.

    python3 -I vwmonth2.py   -> research/vwap30/month2.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwadd as AD
from vwadd import *
from vwacct import _take
from multiprocessing import Pool

AD.PHOTO = [("S3_CMO_SANDWICH", "1h", "CMO·샌드위치 캔들 1시간")]
LIGHT_N, LIGHT_WIN = 20, 0.75


def paper_trades():
    lib = sweepsig.lib()
    parts = []
    for coin in COINS:
        R = rows_tf(coin, "30m", lib)
        R["r"], R["x"] = outcomes_tf(coin, R, 30)["base"]
        parts.append(R)
    A = pd.concat(parts, ignore_index=True)
    A = A[time_ok(A.t.to_numpy()) & gates(A)].assign(prio=0)
    with Pool(2) as pool:
        sig = dict(pool.map(AD.sig_job, COINS))
    rs = []
    for coin in COINS:
        R = rows_of(coin, "1h", sig[coin][("S3_CMO_SANDWICH", "1h")])
        R["r"], R["x"] = outcomes_k(coin, R, 60)
        rs.append(R)
    X = pd.concat(rs, ignore_index=True)
    X = X[time_ok(X.t.to_numpy()) & gates(X)].assign(prio=1)
    P = pd.concat([A, X], ignore_index=True)
    P = P[P.t >= SEL[0]]
    P["lev"] = np.minimum(LEVP, 0.5 / (2.0 * P.atrf.to_numpy() + COST_RT))
    t, coin, prio = P.t.to_numpy(), P.coin.to_numpy(), P.prio.to_numpy()
    o = np.lexsort((coin, prio, t))
    ext = t[o] + (P.x.to_numpy()[o] + 1) * MIN
    T = P.iloc[o[_take(t[o], ext, np.ones(len(o), bool))]].reset_index(drop=True)
    T["month"] = pd.to_datetime(T.t + KST, unit="ms").dt.strftime("%Y-%m")
    return T


def light(win: np.ndarray) -> np.ndarray:
    """True where the live account copies the trade: fewer than N earlier trades, or N earlier won >= the share."""
    out = np.ones(len(win), bool)
    c = np.r_[0, np.cumsum(win.astype(int))]
    for i in range(LIGHT_N, len(win)):
        out[i] = (c[i] - c[i - LIGHT_N]) >= LIGHT_WIN * LIGHT_N
    return out


def months(T, g):
    rows = []
    for m, idx in T.groupby("month").groups.items():
        x = g[np.asarray(idx)]
        eq = np.cumprod(1 + np.maximum(x, -1))
        dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()) if len(eq) else 0.0
        rows.append({"month": m, "mult": round(float(eq[-1]) if len(eq) else 1.0, 4), "maxdd": round(dd, 4),
                     "n": int((x != 0).sum())})
    return rows


def summary(rows):
    full = [r for r in rows if r["month"] < "2026-10"]
    m = np.array([r["mult"] for r in full])
    return {"months": len(full), "x2_or_more": int((m >= 2).sum()), "x5_or_more": int((m >= 5).sum()),
            "plus": int((m > 1).sum()), "lost_half": int((m < 0.5).sum()), "lost_90pct": int((m < 0.1).sum()),
            "median": round(float(np.median(m)), 4), "worst": round(float(m.min()), 4), "best": round(float(m.max()), 4),
            "oct_2026": next((r["mult"] for r in rows if r["month"] == "2026-10"), None)}


def main():
    T = paper_trades()
    win = (T.r.to_numpy() > 0)
    base = T.lev.to_numpy() * T.r.to_numpy()
    on = light(win)
    out = {"data_end": DATA_END, "trades": int(len(T)), "light": {"n": LIGHT_N, "min_win": LIGHT_WIN,
                                                                  "copied_share": round(float(on.mean()), 4)}}
    for name, g in (("증거금 10%", 0.1 * base), ("증거금 20%", 0.2 * base), ("증거금 30%", 0.3 * base),
                    ("증거금 40%", 0.4 * base), ("증거금 40% + 신호등", np.where(on, 0.4 * base, 0.0))):
        rows = months(T, g)
        eq = np.cumprod(1 + np.maximum(g, -1))
        dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min())
        out[name] = {"by_month": summary(rows), "whole_run_mult": float(eq[-1]), "whole_run_maxdd": round(dd, 4),
                     "months": rows}
        print(name, json.dumps(out[name]["by_month"], ensure_ascii=False), "whole", f"{eq[-1]:.3g}", round(dd, 3), flush=True)
    # where the light was red: the paper's own months then
    red = ~on
    out["light"]["red_trades"] = int(red.sum())
    out["light"]["red_trades_paper_win"] = round(float(win[red].mean()), 4) if red.any() else None
    out["light"]["green_trades_paper_win"] = round(float(win[on].mean()), 4)
    print("light", out["light"], flush=True)
    json.dump(out, open(os.path.join(RES_DIR, "month2.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
