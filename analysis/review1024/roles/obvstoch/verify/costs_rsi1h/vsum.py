"""Summary of vcell.py rows: per variant x period n, mean ROE (no payback / payback), cluster(day) t, coin-flip twin;
same-coin overlap; one-position account (own code) at 40 % margin; doubled-cost and liquidation reads.
    python3 vsum.py"""
import os
import sys
import json

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import *  # noqa

HERE = os.path.dirname(os.path.abspath(__file__))
LEV = 30.0
PB = 2 * 0.9 * 0.00042
P = {"PRE": (ms("2020-03-01"), ms("2021-01-01")), "SEL": (ms("2021-01-01"), ms("2024-01-01")),
     "CONF": (ms("2024-01-01"), GRID_END), "YTD": (ms("2026-01-01"), GRID_END),
     "FWD": (ms("2026-10-05 15:00"), ms("2026-10-24 15:00")), "FIVE": (ms("2020-03-01"), GRID_END)}


def clt(x, day):
    n = len(x)
    if n < 2:
        return np.nan
    m = x.mean()
    u, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=x - m)
    G = len(u)
    se = np.sqrt((s * s).sum() * G / max(G - 1, 1)) / n
    return m / se


def one_pos(df):
    df = df.sort_values(["e", "coin"])
    took = np.zeros(len(df), bool)
    busy = -1
    for i, (e, k) in enumerate(zip(df.e.to_numpy(), df.k.to_numpy())):
        if e > busy:
            took[i] = True
            busy = e + k
    return df[took]


def acct(roe, margin=0.4):
    roe = np.maximum(roe, -1.0)
    eq = np.cumprod(1 + margin * roe)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float(eq[-1]) if len(eq) else 1.0, float((1 - eq / peak).max()) if len(eq) else 0.0


if __name__ == "__main__":
    A = pd.read_csv(os.path.join(HERE, "rows_all.csv.gz"))
    A["roe"] = LEV * A.r
    A["roe_opp"] = LEV * A.r_opp
    A["day"] = A.t // DAY
    out = []
    for vn, V in A.groupby("variant", sort=False):
        for per, (a, b) in P.items():
            X = V[(V.t >= a) & (V.t < b) & (V.why != 3) & (V.why_opp != 3)]
            if not len(X):
                continue
            rec = {"variant": vn, "period": per, "n": len(X), "per_day": len(X) / ((min(b, ext_end()) - a) / DAY),
                   "mean": X.roe.mean(), "mean_pb": X.roe.mean() + LEV * PB, "t": clt(X.roe.to_numpy(), X.day.to_numpy()),
                   "t_pb": clt(X.roe.to_numpy() + LEV * PB, X.day.to_numpy()), "opp": X.roe_opp.mean(),
                   "opp_pb": X.roe_opp.mean() + LEV * PB, "win": (X.roe > 0).mean(), "liq_n": int((X.why == 2).sum()),
                   "floor_n": int((X.roe <= -0.9999).sum())}
            T = one_pos(X)
            for pb in (0, 1):
                fx, dd = acct(T.roe.to_numpy() + pb * LEV * PB)
                rec.update({f"op_n": len(T), f"op_mean{'_pb' if pb else ''}": T.roe.mean() + pb * LEV * PB,
                            f"op_x{'_pb' if pb else ''}": fx, f"op_dd{'_pb' if pb else ''}": dd})
            out.append(rec)
    S = pd.DataFrame(out)
    S.to_csv(os.path.join(HERE, "vsum.csv"), index=False, float_format="%.5g")
    pd.set_option("display.width", 250)
    print(S.round(4).to_string())

    # overlap: same-coin trades that open while an earlier trade of the same coin is still open (base, FIVE)
    B = A[(A.variant == "base") & (A.why != 3)].sort_values(["coin", "e"])
    ov = {}
    for per, (a, b) in P.items():
        X = B[(B.t >= a) & (B.t < b)]
        cnt = 0
        tot = 0
        for coin, C in X.groupby("coin"):
            busy = -1
            for e, k in zip(C.e.to_numpy(), C.k.to_numpy()):
                tot += 1
                if e <= busy:
                    cnt += 1
                busy = max(busy, e + k)
        ov[per] = {"n": tot, "same_coin_overlapping": cnt}
    # stop-distance vs liquidation distance (base rows, CONF)
    X = B[(B.t >= P["CONF"][0]) & (B.t < P["CONF"][1])]
    mmr = X.coin.map({"BTCUSDT": 0.005, "ETHUSDT": 0.005}).fillna(0.01)
    ov["CONF_stop_beyond_liq_real"] = int((X.stopd > 1 / 30 - mmr).sum())
    ov["CONF_stop_beyond_floor_3.21pct"] = int((X.stopd > 1 / 30 - 2 * (0.00042 + 0.0002)).sum())
    ov["CONF_stopd_median_pct"] = float(X.stopd.median() * 100)
    ov["CONF_hold_min_median"] = float(X.k.median())
    ov["CONF_hold_min_mean"] = float(X.k.mean())
    print(json.dumps(ov, indent=1))
    json.dump(ov, open(os.path.join(HERE, "voverlap.json"), "w"), indent=1)
