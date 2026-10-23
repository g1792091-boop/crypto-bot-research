"""참고 read: 'VWAP 개선판' + CMO·샌드위치 1시간 (A's gates on both, the owners' 10/23 pick) at the owners' size (margin 40 %,
30x, size cut so a stop loses at most ROE -50 %), A's exits, one position: every calendar month (KST) from 2020-03 to the
data end, each month started fresh. How often a month reached x2 .. x10, how often it lost, the worst months.

    python3 -I vwmonth.py   -> research/vwap30/month.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwadd as AD
from vwadd import *
from vwacct import _take
from multiprocessing import Pool

AD.PHOTO = [("S3_CMO_SANDWICH", "1h", "CMO·샌드위치 캔들 1시간")]
MARGIN = 0.4


def main():
    lib = sweepsig.lib()
    parts = []
    for coin in COINS:
        R = rows_tf(coin, "30m", lib)
        R["r"], R["x"] = outcomes_tf(coin, R, 30)["base"]
        parts.append(R)
    A = pd.concat(parts, ignore_index=True)
    A = A[time_ok(A.t.to_numpy()) & gates(A)].assign(prio=0, member="VWAP")
    with Pool(2) as pool:
        sig = dict(pool.map(AD.sig_job, COINS))
    rs = []
    for coin in COINS:
        R = rows_of(coin, "1h", sig[coin][("S3_CMO_SANDWICH", "1h")])
        R["r"], R["x"] = outcomes_k(coin, R, 60)
        rs.append(R)
    X = pd.concat(rs, ignore_index=True)
    X = X[time_ok(X.t.to_numpy()) & gates(X)].assign(prio=1, member="CMO")
    P = pd.concat([A, X], ignore_index=True)
    P = P[P.t >= SEL[0]]
    P["lev"] = np.minimum(LEVP, 0.5 / (2.0 * P.atrf.to_numpy() + COST_RT))
    t, coin, prio = P.t.to_numpy(), P.coin.to_numpy(), P.prio.to_numpy()
    o = np.lexsort((coin, prio, t))
    ext = t[o] + (P.x.to_numpy()[o] + 1) * MIN
    idx = o[_take(t[o], ext, np.ones(len(o), bool))]
    T = P.iloc[idx].copy()
    T["g"] = MARGIN * T.lev * T.r
    T["month"] = pd.to_datetime(T.t + KST, unit="ms").dt.strftime("%Y-%m")
    rows = []
    for m, G in T.groupby("month"):
        eq = np.cumprod(1 + np.maximum(G.g.to_numpy(), -1))
        dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min())
        rows.append({"month": m, "n": int(len(G)), "wins": int((G.r > 0).sum()), "mult": round(float(eq[-1]), 4),
                     "maxdd": round(dd, 4)})
    M = pd.DataFrame(rows)
    full = M[M.month < "2026-10"]                          # whole months only (October 2026 is the rule bot's run)
    mult = full["mult"].to_numpy()
    out = {"margin": MARGIN, "months": int(len(full)), "data_end": DATA_END,
           "share": {k: round(float(f(mult).mean()), 4) for k, f in (
               ("x10 이상", lambda m: m >= 10), ("x5 이상", lambda m: m >= 5), ("x3 이상", lambda m: m >= 3),
               ("x2 이상", lambda m: m >= 2), ("플러스", lambda m: m > 1), ("마이너스", lambda m: m <= 1),
               ("반 넘게 잃음", lambda m: m < 0.5), ("90% 넘게 잃음", lambda m: m < 0.1))},
           "count": {k: int(f(mult).sum()) for k, f in (
               ("x10 이상", lambda m: m >= 10), ("x5 이상", lambda m: m >= 5), ("x3 이상", lambda m: m >= 3),
               ("x2 이상", lambda m: m >= 2), ("플러스", lambda m: m > 1), ("마이너스", lambda m: m <= 1),
               ("반 넘게 잃음", lambda m: m < 0.5), ("90% 넘게 잃음", lambda m: m < 0.1))},
           "median_mult": round(float(np.median(mult)), 4),
           "best": full.sort_values("mult", ascending=False).head(8).to_dict("records"),
           "worst": full.sort_values("mult").head(8).to_dict("records"),
           "october_2026_so_far": M[M.month == "2026-10"].to_dict("records"),
           "all": M.to_dict("records")}
    print(json.dumps({k: v for k, v in out.items() if k != "all"}, ensure_ascii=False, default=float), flush=True)
    json.dump(out, open(os.path.join(RES_DIR, "month.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
