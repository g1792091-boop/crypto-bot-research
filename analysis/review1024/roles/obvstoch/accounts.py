"""Step 3: one-position accounts (one position at a time over all 6 coins, the bots' rule), per-trade results after costs,
trades per day, max drawdown and the goal path (30 days, x6) for the friend's literal cells and the most hopeful cells
of this study (none confirmed; each row says why it is listed). Shared math: rolesdata.one_position / account /
goal_bootstrap (day-block bootstrap, 30 days). Writes accounts.csv, goal.csv.

    python3 accounts.py
"""
import oscore as O
from oscore import *

LIST = [  # (cell, side: +1 with the signal / -1 reverse, why listed)
    ("OBV30@1h>SRSI_KD@30m|w35", 1, "L1 friend literal (30m entry, 1h OBV trend)"),
    ("OBV30@4h>SRSI_KD@1h|w35", 1, "L2 friend literal (1h entry, 4h OBV trend)"),
    ("OBV30@4h>SRSI_X@1h|a2", 1, "friend family, best of the 160 in the last 19 days"),
    ("OBVSL10@4h>CCI@1h|a2", 1, "best of all 1,080 cells in the last 19 days (n>=30)"),
    ("OBV20@4h>RSI@1h|a2", 1, "S1/S2 top pick in 2021-23 (not confirmed)"),
    ("ICHI@4h>MFI@30m|a2", -1, "reverse track with payback: only pick positive on CONF (not confirmed)"),
]
GRIDS = {}


def gridk(coin):
    if coin not in GRIDS:
        GRIDS[coin] = RD._grid(coin)
    return GRIDS[coin]


def frame(D, cell, sgn, per, payback):
    """Rows of a cell with k (minutes to exit) for the one-position rule; columns in rolesdata's naming, variant 'X'."""
    tf, htf, T, Ot, X = O.parse(cell)
    a, b = O.P[per]
    lev = O.LEVX[X]
    add = PAYBACK if payback else 0.0
    out = []
    for ci, coin in enumerate(COINS):
        Z = D[coin]
        pre = f"{tf}_"
        e = Z[pre + "e"]
        t = T0 + e * MIN
        sig = Z[pre + "sig_" + Ot]
        st = Z[f"{pre}st_{htf}_{T}"]
        m = (t >= a) & (t < b) & (sig != 0) & (st == sig)
        side = (sig[m] * sgn).astype(np.int8)
        em = e[m]
        G = gridk(coin)
        cols = {}
        for lab_s, s_ in (("", 1), ("_opp", -1)):
            sd = side * s_
            r = np.where(sd > 0, Z[f"{pre}{X}_L_r"][m], Z[f"{pre}{X}_S_r"][m]).astype(float)
            w = np.where(sd > 0, Z[f"{pre}{X}_L_w"][m], Z[f"{pre}{X}_S_w"][m])
            if X == "w35s30":
                k = np.where(sd > 0, Z[f"{pre}{X}_L_k"][m], Z[f"{pre}{X}_S_k"][m])
            elif X == "a2":
                tfm = TF_MIN[tf]
                j = em // tfm - 1
                k = np.where(sd > 0, G[f"a2_{tf}_L_k"][j], G[f"a2_{tf}_S_k"][j])
            else:
                j = em // 15 - 1
                k = np.where(sd > 0, G[f"{X}_L_k"][j], G[f"{X}_S_k"][j])
            cols[f"X{lab_s}_r"] = r + add
            cols[f"X{lab_s}_roe"] = lev * (r + add)
            cols[f"X{lab_s}_k"] = k.astype(np.int64)
            cols[f"X{lab_s}_why"] = w
        df = pd.DataFrame({"t": t[m], "e": em, "coin": np.int8(ci), "tf": tf, "side": side, "blk": Z[pre + "blk"][m], **cols})
        out.append(df)
    S = pd.concat(out, ignore_index=True)
    S = S[np.isfinite(S.X_roe) & np.isfinite(S.X_opp_roe) & (S.X_why != 3) & (S.X_opp_why != 3)]
    return S.sort_values(["t", "coin"]).reset_index(drop=True)


def growth(roe, f):
    return float(np.mean(np.log(np.maximum(1.0 + f * np.maximum(roe, -1.0), 1e-12))))


if __name__ == "__main__":
    D = O.load_all()
    acc, goal = [], []
    for cell, sgn, why in LIST:
        for per in ("CONF", "FWD", "FIVE"):
            a, b = O.P[per]
            b_eff = min(b, ext_end())
            days = (b_eff - a) / DAY
            for pb in (False, True):
                S = frame(D, cell, sgn, per, pb)
                for blk0 in (False, True):
                    A = S[S.blk == 0] if blk0 else S
                    took = RD.one_position(A, "X")
                    Tk = A[took]
                    for side_col in ("", "_opp"):
                        for mg in (0.1, 0.2, 0.4):
                            r = RD.account(Tk, "X", margin=mg, side_col=side_col, start=a, end=b_eff)
                            r.update(cell=cell, reverse=sgn < 0, why=why, period=per, payback=pb, blk0=blk0,
                                     side=("signal" if side_col == "" else "coin_flip_twin"), margin=mg,
                                     signals=len(A), per_trade_all_signals=float(A[f"X{side_col}_roe"].mean()) if len(A) else np.nan,
                                     long_share=float((Tk.side > 0).mean()) if len(Tk) else np.nan)
                            r["per_day"] = len(Tk) / days
                            acc.append(r)
                    if blk0 or per == "FIVE":
                        continue
                    roe = np.maximum(Tk.X_roe.to_numpy(float), -1.0)
                    n30 = len(Tk) / days * 30
                    fs = np.linspace(0.01, 1.0, 100)
                    g = np.array([growth(roe, f) for f in fs]) if len(roe) else np.zeros(len(fs))
                    fbest = float(fs[np.argmax(g)])
                    med30 = float(np.exp(n30 * g.max())) if len(roe) else 1.0
                    need = np.flatnonzero(n30 * g >= np.log(6.0))
                    f_need = float(fs[need[0]]) if len(need) else np.nan
                    rec = {"cell": cell, "reverse": sgn < 0, "why": why, "period": per, "payback": pb, "trades": len(Tk),
                           "per_day": len(Tk) / days, "mean_roe_taken": float(roe.mean()) if len(roe) else np.nan,
                           "trades_per_30d": n30, "best_margin_by_growth": fbest,
                           "median_30d_x_at_best_margin": med30, "margin_needed_for_x6_median": f_need,
                           "lev_x_margin_needed": f_need * O.LEVX[O.parse(cell)[4]] if np.isfinite(f_need) else np.nan}
                    for mg in (0.1, 0.4, fbest):
                        gb = RD.goal_bootstrap(Tk, "X", margin=mg, days=(a, b_eff), n_boot=4000)
                        tag = "best" if mg == fbest else f"{int(mg * 100)}"
                        rec.update({f"p_x6_m{tag}": gb["p_target"], f"p_lose50_m{tag}": gb["p_lose50_first"],
                                    f"p_lose90_m{tag}": gb["p_lose90_first"], f"median_x_m{tag}": gb["median_final_x"]})
                    goal.append(rec)
            log(cell, per, "done")
    A = pd.DataFrame(acc)
    A.to_csv("accounts.csv", index=False, float_format="%.6g")
    G = pd.DataFrame(goal)
    G.to_csv("goal.csv", index=False, float_format="%.6g")
    pd.set_option("display.width", 260)
    v = A[(A.margin == 0.4) & (~A.blk0)]
    print(v.pivot_table(index=["cell", "reverse", "payback"], columns=["period", "side"],
                        values=["n", "mean_roe", "final_x", "max_dd"]).round(3).to_string())
    print(G[["cell", "period", "payback", "trades", "per_day", "mean_roe_taken", "best_margin_by_growth",
             "median_30d_x_at_best_margin", "margin_needed_for_x6_median", "p_x6_m40", "p_lose50_m40", "p_lose90_m40",
             "p_x6_mbest"]].round(4).to_string())
