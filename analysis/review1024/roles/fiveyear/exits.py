"""Exit comparison on the pooled entry-role signals (every signal on its own): no filter vs with the trend (main
judges, friend's mappings), under the four exits of the data layer: w35 (owners' live exits, 35x), w30 (same at 30x),
s20 (35x, -20 % net stop), a2 (2 x ATR14 of the signal bar + ladder, 30x). Mean net ROE per trade and the same in
price terms before costs (ROE / leverage + 0.124 %).      python3 exits.py -> exits_table.csv"""
from fy_analyze import *

LEV = {"w35": 35.0, "w30": 30.0, "s20": 35.0, "a2": 30.0}


def main():
    meta, A, AM, B, B0, BARS = load()
    SRC = [tuple(x) for x in meta["src"]]
    N = RD.names()
    sids = N.sid[N.role.isin(ENTRY_ROLES)].to_numpy()
    rows = []
    for (k, s) in [("j", "DIR"), ("j", "V4OF4")]:
        si = SRC.index((k, s))
        for p, (etf, htf) in enumerate(PAIRS):
            if (etf, htf) not in FRIEND_PAIRS:
                continue
            X = A[p, si][:, sids].sum(1)                      # [3, NB, K]
            for per in ("SEL", "CONF", "LATE", "FWD"):
                W = X[2][PER[per]].sum(0)
                ALL = X[:, PER[per]].sum((0, 1))
                for lab, Y in (("no filter", ALL), (f"with {k}:{s}", W)):
                    o = {"map": f"{etf}->{htf}", "filter": lab, "per": per, "n": Y[SI["n"]]}
                    for v in LEV:
                        m = Y[SI[v]] / Y[SI["n"]]
                        o[f"{v}_roe"] = m
                        o[f"{v}_gross_price_pct"] = (m / LEV[v] + COST) * 100
                    rows.append(o)
    R = pd.DataFrame(rows).drop_duplicates(["map", "filter", "per"])
    R.to_csv(os.path.join(HERE, "exits_table.csv"), index=False, float_format="%.5g")
    print(R.round(4).to_string())


if __name__ == "__main__":
    main()
