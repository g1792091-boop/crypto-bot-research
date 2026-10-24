"""Extra reads for the report: (1) the alignment effect per calendar block (stability), pooled over all entry-role
signals, for the main judges on the friend's mappings; (2) the gross edge before costs in price terms; (3) how far each
bot is from the goal: the per-trade ROE shift (in ROE points at 35x) that would make the growth-optimal 30-day median
multiple reach x6 with the bot's CONFIRM trade rate and spread.     python3 extras.py -> effect_by_year.csv, goal_gap.csv"""
import sys
from fy_analyze import *
from goalpath import bot_rows, read, growth_opt
from cellsig import period_rows

def by_year():
    meta, A, AM, B, B0, BARS = load()
    SRC = [tuple(x) for x in meta["src"]]
    N = RD.names()
    sids = N.sid[N.role.isin(ENTRY_ROLES)].to_numpy()
    rows = []
    for (k, s) in [("j", "DIR"), ("j", "V4OF4"), ("j", "DIR_ADX20"), ("c", "OBV_S")]:
        si = SRC.index((k, s))
        for p, (etf, htf) in enumerate(PAIRS):
            if (etf, htf) not in FRIEND_PAIRS:
                continue
            X = A[p, si][:, sids].sum(1)                      # [3, NB, K]
            for b, bn in enumerate(BLOCKS):
                W, ALL = X[2, b], X[:, b].sum(0)
                if W[SI["n"]] <= 0:
                    continue
                rows.append({"source": f"{k}:{s}", "map": f"{etf}->{htf}", "block": bn, "nW": W[SI["n"]],
                             "mW": W[SI["w35"]] / W[SI["n"]], "mALL": ALL[SI["w35"]] / ALL[SI["n"]],
                             "mWo": W[SI["w35o"]] / W[SI["n"]], "lsW": W[SI["nlong"]] / W[SI["n"]]})
    Y = pd.DataFrame(rows)
    Y["eff"] = Y.mW - Y.mALL
    Y.to_csv(os.path.join(HERE, "effect_by_year.csv"), index=False, float_format="%.5g")
    print(Y.pivot_table(index=["source", "map"], columns="block", values="eff").reindex(columns=BLOCKS).mul(100).round(2).to_string())


def gap():
    import json
    G = pd.read_csv(os.path.join(HERE, "goalpath.csv"))
    out = []
    for f in ["goalpath.csv", "goalpath_G.csv", "goalpath_H.csv", "goalpath_X_S4.csv"]:
        pth = os.path.join(HERE, f)
        if os.path.exists(pth):
            out.append(pd.read_csv(pth))
    G = pd.concat(out, ignore_index=True)
    G = G[(G.period == "CONF") & (G.blk0 == False)]                       # noqa: E712
    rows = []
    for _, r in G.iterrows():
        rows.append({"bot": r.bot, "per_day": r.per_day, "mean_roe": r.mean_roe, "mean_roe_pb": r.mean_roe_pb,
                     "gross_price_pct": (r.mean_roe / 35 + COST) * 100,
                     "a2_30x": r.a2_mean, "s20_35x": r.s20_mean, "w30_30x": r.w30_mean})
    Q = pd.DataFrame(rows)
    Q.to_csv(os.path.join(HERE, "goal_gap.csv"), index=False, float_format="%.5g")
    print(Q.round(4).to_string())


if __name__ == "__main__":
    by_year()
    gap()
