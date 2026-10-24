"""A DESCRIPTIVE baseline of the 5-year table (no selection, nothing tuned): per strategy x timeframe, over the whole
5-year period (2020-03-01 .. 2026-10-23 UTC, bar number >= 300), every signal taken on its own (no one-position rule):

  n, per_day (6 coins), long_share,
  w35_roe / w35_opp_roe  mean net ROE at 35x, net -50 % stop + ladder, for the signal's side and for the opposite side
                         (the coin-flip twin on the same entries), open trades at the end dropped,
  agree_raw              share of signals on the side of the trend bot's 3-of-4 vote (raw, no hold) of the last closed
                         higher bar (15m / 30m -> 1h, 1h -> 4h, 4h -> 1d), among signals where the vote has a side --
                         the same quantity as the role map's htf_agree (roles_measured.csv, 2021-01 .. ), as a cross-check
  roe_with / roe_against / roe_nodir   mean w35 ROE when the held judgment (tj_dir) is with / against / neither

It is a sanity reference for the studies, NOT a ranking to pick from: anything picked from it must be confirmed on
another period (rolesdata.PERIODS) against the coin-flip twin and corrected for the number of things tried.

    python3 baseline.py   ->  baseline_5y.csv next to this file"""
from common import *
import rolesdata as RD


def main():
    N = RD.names()
    rows = []
    for tf in TFS:
        for ci, coin in enumerate(COINS):
            S = RD.signals(tfs=[tf], period="five", coins=[coin])
            if not len(S):
                continue
            S = RD.add_outcomes(S, ["w35"])
            S = RD.add_judge(S, check=False)
            S = S[S.w35_why != 3]
            g = S.groupby("name")
            side = S.side.to_numpy()
            raw, d = S.tj_raw3.to_numpy(), S.tj_dir.to_numpy()
            S = S.assign(w_raw=(raw == side), a_raw=(raw == -side), w_dir=(d == side), a_dir=(d == -side),
                         n_dir=(d == 0) | np.isnan(d), longs=side > 0)
            for name, q in S.groupby("name"):
                rows.append({"name": name, "tf": tf, "coin": coin, "n": len(q), "long": int(q.longs.sum()),
                             "sum_roe": q.w35_roe.sum(), "sum_opp": q.w35_opp_roe.sum(),
                             "w_raw": int(q.w_raw.sum()), "a_raw": int(q.a_raw.sum()),
                             "n_with": int(q.w_dir.sum()), "s_with": q.w35_roe[q.w_dir].sum(),
                             "n_against": int(q.a_dir.sum()), "s_against": q.w35_roe[q.a_dir].sum(),
                             "n_nodir": int(q.n_dir.sum()), "s_nodir": q.w35_roe[q.n_dir].sum()})
            log(tf, coin, len(S))
            drop(coin)
    R = pd.DataFrame(rows)
    days = (FIVE[1] - FIVE[0]) / DAY
    out = []
    for (name, tf), g in R.groupby(["name", "tf"]):
        n = g.n.sum()
        s = lambda c: g[c].sum()
        out.append({"name": name, "tf": tf, "set": N.set[N.name == name].iloc[0], "role": N.role[N.name == name].iloc[0],
                    "n": int(n), "per_day": round(n / days, 3), "long_share": round(s("long") / n, 3),
                    "w35_roe": round(s("sum_roe") / n, 4), "w35_opp_roe": round(s("sum_opp") / n, 4),
                    "agree_raw": round(s("w_raw") / max(s("w_raw") + s("a_raw"), 1), 3),
                    "n_with": int(s("n_with")), "roe_with": round(s("s_with") / max(s("n_with"), 1), 4),
                    "n_against": int(s("n_against")), "roe_against": round(s("s_against") / max(s("n_against"), 1), 4),
                    "n_nodir": int(s("n_nodir")), "roe_nodir": round(s("s_nodir") / max(s("n_nodir"), 1), 4)})
    B = pd.DataFrame(out).sort_values(["role", "name", "tf"])
    M = pd.read_csv(os.path.join(MAP, "roles_measured.csv"))[["name", "tf", "htf_agree"]]
    B = B.merge(M, on=["name", "tf"], how="left").rename(columns={"htf_agree": "rolemap_htf_agree"})
    B.to_csv(os.path.join(HERE, "baseline_5y.csv"), index=False)
    ok = B.rolemap_htf_agree.notna()
    diff = (B.agree_raw - B.rolemap_htf_agree).abs()[ok]
    log("baseline", len(B), "rows; agree vs role map: median |diff|", round(float(diff.median()), 4), "max",
        round(float(diff.max()), 4), "rows > 0.05:", int((diff > 0.05).sum()))
    print(B[ok & ((B.agree_raw - B.rolemap_htf_agree).abs() > 0.05)][["name", "tf", "n", "agree_raw", "rolemap_htf_agree"]]
          .to_string())


if __name__ == "__main__":
    main()
