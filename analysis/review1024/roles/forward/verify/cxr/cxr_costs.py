"""Verifier (lens: costs, executability, overlap) of the forward study's a2 family TOP5 claim
("1h reversal + timing entries @4h c_N07_ICHI_CMO, a2 exits, only search result that passed the permutation").

Read-only over the cached tables of ../../fw_build.py. Re-walks the a2 exit (frloss.walk2, the same kernel the grid used)
on every H2 row of the 5 picked cells under
  base      cost 0.124 % round trip, funding 0 (must equal the stored outcome: sanity check)
  cost2     cost 0.248 % round trip (doubled), funding 0
  fund      cost 0.124 %, real October funding recovered from the rule bot's paper trades (Binance funding, charged by
            the paper engine on its open positions: trades.csv 'funding' / (qty x entry price), median per symbol and
            funding time, trades that hold over exactly one 00/08/16 UTC settlement)
  cost2fund both
and reads: pooled per signal, unique entries, per day, one-position bot (all six coins), one position per coin, the
named 1h subset alone, payback, coin-flip twin.

    python3 cxr_costs.py <rule bot trades.csv>     (run from this folder without -I)"""
import os
import sys
import json

FW = "/home/user/crypto-bot-research/analysis/review1024/roles/forward"
sys.path.insert(0, FW)
from fw_lib import *  # noqa: F401,F403,E402
from frloss import walk2  # noqa: E402

HERE_V = os.path.dirname(os.path.abspath(__file__))
H8 = 8 * HOUR


def funding_rates(path):
    T = pd.read_csv(path, usecols=["symbol", "side", "entry_time", "exit_time", "entry_price", "qty", "funding"])
    T = T[T.exit_time.notna() & T.symbol.isin(COINS)].copy()
    a = T.entry_time.to_numpy(np.int64) // H8 + 1          # first settlement strictly after the entry minute start
    b = T.exit_time.to_numpy(np.int64) // H8
    T["nf"], T["fidx"] = b - a + 1, a
    one = T[T.nf == 1].copy()
    one["rate"] = one.funding / (one.qty * one.entry_price * np.sign(one.side))
    R = one.groupby(["symbol", "fidx"]).rate.agg(["median", "count", "std"]).reset_index()
    return R, len(one), int((one.funding != 0).sum())


def rewalk(X, cost, R=None):
    """a2 net price return per row of X (cols coin, e, tf, side) via walk2 at 30x, ATR stop 2 x ATR14 of the signal bar."""
    out = np.full(len(X), np.nan)
    kk = np.full(len(X), -1, np.int64)
    ww = np.full(len(X), -1, np.int8)
    for ci, coin in enumerate(COINS):
        mc = X.coin.to_numpy() == ci
        if not mc.any():
            continue
        g = grid(coin)
        z = np.load(os.path.join(OUT, "grid", f"{coin}.npz"))
        fund = g["fund"].copy()
        if R is not None:
            r_ = R[R.symbol == coin]
            idx = (r_.fidx.to_numpy(np.int64) * H8 - T0) // MIN
            ok = (idx >= 0) & (idx < len(fund))
            fund[idx[ok]] = r_["median"].to_numpy()[ok]
        cumf = np.cumsum(fund)
        for tf in TFS:
            m = mc & (X.tf.to_numpy() == tf)
            if not m.any():
                continue
            e = X.e.to_numpy(np.int64)[m]
            j = e // TF_MIN[tf] - 1
            atr = z[f"atr14_{tf}"][j]
            atrd = np.ascontiguousarray(2.0 * atr / g["o"][e])
            for sd in (1, -1):
                q = X.side.to_numpy()[m] == sd
                if not q.any():
                    continue
                a = walk2(g["o"], g["h"], g["l"], g["c"], cumf, np.ascontiguousarray(e[q]), sd, 30.0, cost, FL, STEP,
                          GAP, np.ascontiguousarray(atrd[q]), -1.0, g["n"])
                pos = np.flatnonzero(m)[q]
                out[pos], kk[pos], ww[pos] = a[0], a[1], a[2]
    return out, kk, ww


def one_pos(Y, kcol, prio="prio", per_coin=False):
    Y = Y.sort_values(["e", prio, "coin"]).reset_index(drop=True)
    took = np.zeros(len(Y), bool)
    free = {}
    for i, (c, e, k) in enumerate(zip(Y.coin.to_numpy(), Y.e.to_numpy(np.int64), Y[kcol].to_numpy(np.int64))):
        key = c if per_coin else 0
        if e > free.get(key, -1):
            took[i] = True
            free[key] = e + k
    return Y[took]


def stats(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return {"n": int(len(x)), "mean": float(np.mean(x)) if len(x) else None,
            "win": float(np.mean(x > 0)) if len(x) else None}


def main():
    R, n_one, n_nz = funding_rates(sys.argv[1])
    S = load("sig")
    S = S[S.role != "trend"].reset_index(drop=True)
    P = pd.read_csv(os.path.join(FW, "search_picks.csv"))
    P = P[(P.exit == "a2") & (P.level == "F")].sort_values("rank")
    side = S.side.to_numpy()
    rows = []
    for _, c in P.iterrows():
        role, tf = c.key.split("|")
        m = (S.role.to_numpy() == role) & (S.tf.to_numpy() == tf) & ((state(S, c.src, c.htf) * side) == 1)
        X = S[m].copy()
        X["prio"] = int(c["rank"])
        X["cell"] = f"{c.key}@{c.htf}:{c.src}"
        rows.append(X)
    A = pd.concat(rows, ignore_index=True)
    A["roe0"] = roe(A, "a2")
    A["roe0_opp"] = roe(A, "a2", True)
    h2 = (A.t.to_numpy() >= SPLIT) & (A.a2_why.to_numpy() != 3) & np.isfinite(A.roe0.to_numpy())
    A = A[h2].reset_index(drop=True)
    res = {"funding_recovery": {"trades_one_settlement": n_one, "nonzero": n_nz, "settlements": int(len(R)),
                                "h2_mean_rate_by_symbol": R[R.fidx * H8 >= SPLIT].groupby("symbol")["median"].mean()
                                .to_dict(),
                                "h2_settlements_by_symbol": R[R.fidx * H8 >= SPLIT].groupby("symbol").size().to_dict()}}
    variants = {"base": (COST, None), "cost2": (2 * COST, None), "fund": (COST, R), "cost2fund": (2 * COST, R)}
    for vn, (cost, rr) in variants.items():
        for sd_lab, flip in (("", 1), ("_opp", -1)):
            Xs = A[["coin", "e", "tf"]].copy()
            Xs["side"] = A.side.to_numpy() * flip
            r, k, w = rewalk(Xs, cost, rr)
            A[f"{vn}{sd_lab}_roe"] = np.maximum(30.0 * r, -1.0)
            A[f"{vn}{sd_lab}_k"] = k
            A[f"{vn}{sd_lab}_why"] = w
    res["sanity_base_vs_stored_maxabs"] = float(np.nanmax(np.abs(A.base_roe - A.roe0)))
    res["sanity_base_opp_vs_stored_maxabs"] = float(np.nanmax(np.abs(A.base_opp_roe - A.roe0_opp)))
    days = DAYS["H2"]
    U = A.sort_values("prio").drop_duplicates(["coin", "e", "side"])           # one position per coin+minute+side
    Ut = A.sort_values("prio").drop_duplicates(["coin", "e", "side", "tf"])     # same, but 1h and 4h kept apart
    named = A[A.prio.isin([4, 5])]
    res["counts"] = {"pooled": len(A), "per_day_pooled": len(A) / days, "unique_coin_e_side": len(U),
                     "unique_coin_e_side_tf": len(Ut), "per_day_unique": len(U) / days,
                     "per_day_unique_tf": len(Ut) / days, "h2_days": days,
                     "shorts_pooled": int((A.side < 0).sum()), "shorts_unique": int((U.side < 0).sum())}
    out = {}
    for vn in variants:
        col = f"{vn}_roe"
        d = {"pooled": stats(A[col]), "pooled_twin": stats(A[f"{vn}_opp_roe"]),
             "unique": stats(U[col]), "unique_tf": stats(Ut[col]),
             "named_1h_pooled": stats(named[col]),
             "named_1h_unique": stats(named.drop_duplicates(["coin", "e", "side"])[col]),
             "other3_pooled": stats(A[~A.prio.isin([4, 5])][col]),
             "pooled_short": stats(A[A.side < 0][col]), "pooled_long": stats(A[A.side > 0][col]),
             "pooled_ci_day": day_boot_ci(A[col].to_numpy(float), A.day.to_numpy(), 5000, 3)}
        B1 = one_pos(A, f"{vn}_k")
        Bc = one_pos(A, f"{vn}_k", per_coin=True)
        Bn = one_pos(named, f"{vn}_k")
        Bnc = one_pos(named, f"{vn}_k", per_coin=True)
        d["bot_one_position"] = stats(B1[col])
        d["bot_one_per_coin"] = stats(Bc[col])
        d["bot_named_1h_one_position"] = stats(Bn[col])
        d["bot_named_1h_one_per_coin"] = stats(Bnc[col])
        d["pooled_plus_payback"] = float(A[col].mean() + 30 * PAYBACK)
        d["bot_one_position_plus_payback"] = float(B1[col].mean() + 30 * PAYBACK)
        out[vn] = d
    res["reads"] = out
    # max concurrent open positions if every unique entry were taken (minute sweep)
    ev = []
    for e, k in zip(U.e.to_numpy(np.int64), U.base_k.to_numpy(np.int64)):
        ev.append((e, 1))
        ev.append((e + k + 1, -1))
    ev.sort()
    cur = mx = 0
    for _, dlt in ev:
        cur += dlt
        mx = max(mx, cur)
    res["max_concurrent_if_all_unique_taken"] = mx
    res["hold_minutes_median_unique"] = float(np.median(U.base_k))
    json.dump(res, open(os.path.join(HERE_V, "cxr_costs.json"), "w"), indent=1, default=float)
    print(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
