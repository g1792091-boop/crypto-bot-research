"""Role-level pooled reads (fewer, broader units than single cells): for every role x mapping pair x trend source x
condition, the trade-weighted mean net ROE of ALL entry strategies of that role together, per exit (w35, w30, w35s20,
a2) and period, with and without the TetherMax payback (90 % of the taker fee back: +0.0756 % price per round trip =
+2.65 ROE points at 35x, +2.27 at 30x), the coin-flip twin and month-clustered t (w35).

Selection rule (SELECT only): a unit is 'picked' when its w35 SELECT mean WITH payback > 0 and SELECT clustered t > 2
(payback adds a constant, so t is computed on the payback-shifted mean). BH over all units at q = 0.10 on SELECT.
Picked units are read once on CONFIRM.     python3 role_pool.py  ->  role_pool.csv, role_pool_picked.csv"""
from fy_analyze import *

LEVS = {"w35": 35.0, "w30": 30.0, "s20": 35.0, "a2": 30.0}


def main():
    meta, A, AM, B, B0, BARS = load()
    SRC = meta["src"]
    N = RD.names()
    roles = ["range", "pullback", "breakout", "reversal", "timing", "other", "trend"]
    rows = []
    for role in roles:
        sids = N.sid[N.role == role].to_numpy()
        X = A[:, :, :, sids].sum(axis=3)                         # [P, NS, 3, NB, K]
        XM = AM[:, :, :, sids].sum(axis=3)                       # [P, NS, 3, NMON, 3]
        for p in range(len(PAIRS)):
            for s in range(len(SRC)):
                for ci, cn in ((2, "W"), (0, "A"), (1, "N")):
                    if cn == "N" and SRC[s][0] == "l":
                        continue
                    o = {"role": role, "etf": PAIRS[p][0], "htf": PAIRS[p][1], "kind": SRC[s][0],
                         "source": SRC[s][1], "cond": cn}
                    for per in ("SEL", "CONF", "LATE", "FWD"):
                        Y = X[p, s, ci][PER[per]].sum(0)
                        n = Y[SI["n"]]
                        o[f"{per}_n"] = n
                        if n <= 0:
                            continue
                        o[f"{per}_ls"] = Y[SI["nlong"]] / n
                        for v, (a, b) in (("w35", ("w35", "w35o")), ("w30", ("w30", "w30o")), ("s20", ("s20", "s20o")),
                                          ("a2", ("a2", "a2o"))):
                            o[f"{per}_{v}"] = Y[SI[a]] / n
                            o[f"{per}_{v}o"] = Y[SI[b]] / n
                        allY = X[p, s][:, PER[per]].sum((0, 1))
                        o[f"{per}_w35all"] = allY[SI["w35"]] / max(allY[SI["n"]], 1)
                    for per in ("SEL", "CONF"):
                        sl = months_of(per)
                        Z = XM[p, s, ci, sl]
                        pb = LEVS["w35"] * PAYBACK
                        mu, t, M = cluster_t(Z[:, 0], Z[:, 1] + pb * Z[:, 0])
                        o[f"{per}_t_pb"], o[f"{per}_M"] = t, M
                        mu, t, M = cluster_t(Z[:, 0], None, d_m=Z[:, 1] - Z[:, 2])
                        o[f"{per}_tflip"] = t
                    rows.append(o)
        log(role)
    R = pd.DataFrame(rows)
    R = R[(R.SEL_n > 0) | (R.CONF_n > 0)]
    for v in LEVS:
        for per in ("SEL", "CONF", "LATE", "FWD"):
            R[f"{per}_{v}_pb"] = R[f"{per}_{v}"] + LEVS[v] * PAYBACK
    fam = R[(R.SEL_n >= 300) & (R.SEL_M >= 24)].copy()
    fam["SEL_p"] = pval(fam.SEL_t_pb.to_numpy(), fam.SEL_M.to_numpy())
    fam["SEL_bh"] = bh(fam.SEL_p.to_numpy())
    fam["picked"] = (fam.SEL_w35_pb > 0) & (fam.SEL_t_pb > 2)
    R = R.merge(fam[["role", "etf", "htf", "kind", "source", "cond", "SEL_p", "SEL_bh", "picked"]],
                on=["role", "etf", "htf", "kind", "source", "cond"], how="left")
    R.to_csv(os.path.join(SCR, "fiveyear_role_pool.csv.gz"), index=False, float_format="%.5g")
    P = R[R.picked == True].copy()                                   # noqa: E712
    P["CONF_p"] = pval(P.CONF_t_pb.to_numpy(), P.CONF_M.to_numpy())
    P["CONF_bh"] = bh(P.CONF_p.to_numpy())
    P.to_csv(os.path.join(HERE, "role_pool_picked.csv"), index=False, float_format="%.5g")
    log("units", len(R), "family", len(fam), "SEL BH pass", int(fam.SEL_bh.sum()), "picked", len(P),
        "CONF w35+payback > 0:", int((P.CONF_w35_pb > 0).sum()), "CONF BH pass", int(P.CONF_bh.sum()))
    print("SELECT units with w35+payback > 0:", int((fam.SEL_w35_pb > 0).sum()), "of", len(fam))
    print("CONF  units with w35+payback > 0 (same family):", int((fam.merge(R, on=['role', 'etf', 'htf', 'kind', 'source',
                                                                                     'cond']).CONF_w35_pb_y > 0).sum()))
    cols = ["role", "etf", "htf", "kind", "source", "cond", "SEL_n", "SEL_w35", "SEL_w35_pb", "SEL_t_pb", "CONF_n",
            "CONF_w35", "CONF_w35_pb", "CONF_t_pb", "CONF_w35o", "LATE_w35_pb", "FWD_n", "FWD_w35_pb"]
    print(P.sort_values("SEL_t_pb", ascending=False)[cols].head(40).round(4).to_string())


if __name__ == "__main__":
    main()
