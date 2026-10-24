"""Stage 3 of the five-year role study: the cell search, picked on SELECT (2021-01 .. 2023-12) only, read ONCE on
CONFIRM (2024-01 .. 2026-09), then on LATE (2026-01 .. 10-22) and the 19 forward days.

Rules fixed before the CONFIRM columns were opened (they are in the same table, so the code never reads them while
picking):
  family     every cell (pair, source, entry strategy, condition with / against / neutral) with >= 60 SELECT trades
             in >= 12 different SELECT months,
             all roles (trend-role entries kept as a control), plus every entry strategy x timeframe unfiltered
  test       one-sided month-clustered t of the mean net ROE per trade (w35) > 0 on SELECT, BH at q = 0.10 over the
             whole family
  shortlist  (exploratory, labelled so) the best cell by SELECT t per (strategy, timeframe, condition), top 20 per
             condition with SELECT mean > 0 -> 60 cells; read once on CONFIRM, BH over the 60 on CONFIRM
  selection  premium: CONFIRM mean of the shortlist vs CONFIRM mean of the whole family of the same condition
Outputs: selection_family.csv (counts), shortlist.csv (60 rows with every read), persist.csv."""
import sys
from fy_analyze import *

TOPK = 20
MIN_MONTHS = 12      # at least 12 SELECT months with trades (drops warm-up-only cells: a latch is 0 only before its
                     # first signal, so 'neutral' latch cells are early-2021 warm-up rows)


def main(pbmode=False):
    """pbmode: the same procedure with the TetherMax payback added to every trade (t and 'mean > 0' on mean + 2.65 ROE
    points); outputs get the suffix _pb."""
    D = pd.read_pickle(os.path.join(SHM, "cells.pkl"))
    tp = "pb" if pbmode else ""
    PB = 35.0 * PAYBACK if pbmode else 0.0
    sfx = "_pb" if pbmode else ""
    rows = []
    for cn in ("W", "A", "N"):
        q = D[(D[f"SEL_n{cn}"] >= SEL_MIN) & (D[f"SEL_M{cn}"] >= MIN_MONTHS)]
        if cn == "N":                # a latch is 0 only before its first signal (warm-up), never a 'neutral' market
            q = q[q.kind != "l"]
        rows.append(pd.DataFrame({"cond": cn, "idx": q.index, "t": q[f"SEL_t{cn}{tp}"].to_numpy(),
                                  "M": q[f"SEL_M{cn}"].to_numpy(), "m": q[f"SEL_m{cn}"].to_numpy() + PB}))
    # unfiltered entries: one row per (sid, entry tf), the 1d-mapping row (largest warm-up = most conservative)
    U = D[(D.htf == "1d")].drop_duplicates(["sid", "etf"])
    U = U[(U.SEL_nALL >= SEL_MIN) & (U.SEL_MALL >= MIN_MONTHS)]
    rows.append(pd.DataFrame({"cond": "ALL", "idx": U.index, "t": U[f"SEL_tALL{tp}"].to_numpy(), "M": U.SEL_MALL.to_numpy(),
                              "m": U.SEL_mALL.to_numpy() + PB}))
    F = pd.concat(rows, ignore_index=True)
    F["p"] = pval(F.t.to_numpy(), F.M.to_numpy())
    F["bh"] = bh(F.p.to_numpy())
    fam = F.groupby("cond").agg(cells=("t", "size"), sel_mean_pos=("m", lambda x: int((x > 0).sum())),
                                t_gt2=("t", lambda x: int((x > 2).sum())), t_gt3=("t", lambda x: int((x > 3).sum())),
                                bh_pass=("bh", "sum")).reset_index()
    fam.loc[len(fam)] = ["total", len(F), int((F.m > 0).sum()), int((F.t > 2).sum()), int((F.t > 3).sum()),
                         int(F.bh.sum())]
    fam.to_csv(os.path.join(HERE, f"selection_family{sfx}.csv"), index=False)
    log("family", len(F), "BH pass on SELECT:", int(F.bh.sum()))
    print(fam.to_string())

    # shortlist: best cell per (strategy, tf, cond) by SELECT t, top TOPK per condition with SELECT mean > 0
    F = F.join(D[["name", "etf", "htf", "kind", "source", "role"]], on="idx")
    sl = []
    for cn in ("W", "A", "N"):
        z = F[(F.cond == cn) & (F.m > 0)].sort_values("t", ascending=False).drop_duplicates(["name", "etf"])
        sl.append(z.head(TOPK))
    SL = pd.concat(sl, ignore_index=True)
    out = []
    for _, r in SL.iterrows():
        c = D.loc[r.idx]
        cn = r.cond
        o = {"cond": cn, "name": c["name"], "role": c.role, "etf": c.etf, "htf": c.htf, "source": f"{c.kind}:{c.source}"}
        for per in ("SEL", "CONF", "LATE", "FWD"):
            o[f"{per}_n"] = c[f"{per}_n{cn}"]
            o[f"{per}_m"] = c[f"{per}_m{cn}"]
            o[f"{per}_mo"] = c[f"{per}_m{cn}o"] if cn in ("W", "A") else np.nan
            o[f"{per}_mALL"] = c[f"{per}_mALL"]
        for per in ("SEL", "CONF"):
            o[f"{per}_t"] = c[f"{per}_t{cn}{tp}"]
            o[f"{per}_M"] = c[f"{per}_M{cn}"]
        if cn == "W":
            for per in ("SEL", "CONF", "FWD"):
                o[f"{per}_ls"] = c[f"{per}_lsW"]
                for v in ("w30", "s20", "a2"):
                    o[f"{per}_{v}"] = c[f"{per}_{v}W"]
        o["payback_in_t"] = pbmode
        out.append(o)
    S = pd.DataFrame(out)
    for per in ("SEL", "CONF", "LATE", "FWD"):
        S[f"{per}_m_pb"] = S[f"{per}_m"] + 35.0 * PAYBACK
    S["CONF_p"] = pval(S.CONF_t.to_numpy(), S.CONF_M.to_numpy())
    S["CONF_bh"] = bh(S.CONF_p.to_numpy())
    S.to_csv(os.path.join(HERE, f"shortlist{sfx}.csv"), index=False, float_format="%.5g")
    # selection premium: shortlist CONF mean vs the family CONF mean of the same condition (trade-weighted)
    prem = []
    for cn in ("W", "A", "N"):
        z = F[F.cond == cn]
        cz = D.loc[z.idx]
        fam_conf = np.nansum(cz[f"CONF_m{cn}"] * cz[f"CONF_n{cn}"]) / np.nansum(cz[f"CONF_n{cn}"])
        s = S[S.cond == cn]
        prem.append({"cond": cn, "shortlist_cells": len(s), "shortlist_conf_pos": int((s.CONF_m + PB > 0).sum()),
                     "shortlist_conf_mean_cellavg": s.CONF_m.mean(), "shortlist_sel_mean_cellavg": s.SEL_m.mean(),
                     "family_conf_mean": fam_conf, "conf_bh_pass": int(s.CONF_bh.sum()),
                     "shortlist_fwd_mean_cellavg": s.FWD_m.mean()})
    P = pd.DataFrame(prem)
    P.to_csv(os.path.join(HERE, f"selection_premium{sfx}.csv"), index=False, float_format="%.5g")
    print(P.to_string())
    print(S[["cond", "name", "etf", "htf", "source", "SEL_n", "SEL_m", "SEL_t", "CONF_n", "CONF_m", "CONF_t", "CONF_mo",
             "FWD_n", "FWD_m"]].round(4).to_string())


if __name__ == "__main__":
    main(pbmode=len(sys.argv) > 1 and sys.argv[1] == "pb")
