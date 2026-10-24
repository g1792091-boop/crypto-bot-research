"""Cost / executability / overlap verifier, step 2 (reads /dev/shm/claude_vc/<tf>.pkl from vc_build.py).

For 15m and 30m entry-role signals, filter = all four 1h judges agree with the signal side (V4OF4), stack = also the 4h
held judge (DIR) on the signal side. Per cost / delay variant and period:
  pooled   every signal on its own (the study's way; heavy overlap: many strategies fire on the same coin/minute/side)
  unique   each (coin, entry minute, side) once
  bot1     ONE position at a time over all six coins (the live bots' rule), ties broken at random (5 seeds, mean)
Writes vc_results.csv and vc_years.csv.        python3 vc_analyze.py"""
import os
import sys

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import numpy as np
import pandas as pd
import numba
from common import ms, DAY, PAYBACK            # noqa: E402

IND = "/dev/shm/claude_vc"
HERE = os.path.dirname(os.path.abspath(__file__))
PER = {"SEL": (ms("2021-01-01"), ms("2024-01-01")), "CONF": (ms("2024-01-01"), ms("2026-10-01")),
       "Y21": (ms("2021-01-01"), ms("2022-01-01")), "Y22": (ms("2022-01-01"), ms("2023-01-01")),
       "Y23": (ms("2023-01-01"), ms("2024-01-01")), "Y24": (ms("2024-01-01"), ms("2025-01-01")),
       "Y25": (ms("2025-01-01"), ms("2026-01-01")), "Y26a": (ms("2026-01-01"), ms("2026-10-01")),
       "FWD": (ms("2026-10-05 15:00"), ms("2026-10-24 15:00"))}
VARS = {"base": 0, "woo": 0, "x2": 0, "d1": 1, "d2": 2}
SEEDS = [1, 2, 3, 4, 5]


@numba.njit
def one_pos(e, k, order):
    took = np.zeros(len(e), np.bool_)
    busy = -1
    for q in order:
        if k[q] < 0:
            continue
        if e[q] > busy:
            took[q] = True
            busy = e[q] + k[q]
    return took


def bot(P, v, dl, seed):
    e = P.e.to_numpy(np.int64) + dl
    k = P[f"{v}_k"].to_numpy(np.int64)
    rng = np.random.default_rng(seed)
    pr = rng.permutation(len(P))
    order = np.lexsort((pr, e)).astype(np.int64)
    took = one_pos(e, k, order)
    return took


def month_t(t, roe_a, t_b, roe_b):
    """t of the month-level difference of mean ROE (bot a - bot b) over months where both traded."""
    ma = pd.Series(roe_a).groupby(pd.to_datetime(t, unit="ms").to_period("M")).mean()
    mb = pd.Series(roe_b).groupby(pd.to_datetime(t_b, unit="ms").to_period("M")).mean()
    d = (ma - mb).dropna()
    if len(d) < 3:
        return np.nan, len(d)
    return float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), len(d)


def main():
    rows, yrows = [], []
    for tf in ("15m", "30m"):
        S = pd.read_pickle(os.path.join(IND, f"{tf}.pkl"))
        sd = S.side.to_numpy()
        S["f1"] = S.v4_1h.to_numpy() == sd
        S["f2"] = S.f1.to_numpy() & (S.dir_4h.to_numpy() == sd)
        for per, (lo, hi) in PER.items():
            P = S[(S.t >= lo) & (S.t < hi)]
            days = (hi - lo) / DAY
            for v, dl in VARS.items():
                ok = (P[f"{v}_why"] != 3) & (P[f"{v}_opp_why"] != 3) & (P[f"{v}_k"] >= 0)
                Q = P[ok]
                roe = Q[f"{v}_roe"]
                base = roe.mean()
                rec = {"tf": tf, "per": per, "var": v, "n_all": len(Q), "pool_all": base}
                for f in ("f1", "f2"):
                    m = Q[f].to_numpy()
                    rec[f"n_{f}"] = int(m.sum())
                    rec[f"pool_{f}"] = roe[m].mean()
                    rec[f"pool_{f}_opp"] = Q[f"{v}_opp_roe"][m].mean()
                    rec[f"pool_eff_{f}"] = rec[f"pool_{f}"] - base
                # unique (coin, entry minute, side)
                U = Q.drop_duplicates(["coin", "e", "side"])
                ub = U[f"{v}_roe"].mean()
                rec["n_uni_all"], rec["uni_all"] = len(U), ub
                for f in ("f1", "f2"):
                    m = U[f].to_numpy()
                    rec[f"n_uni_{f}"] = int(m.sum())
                    rec[f"uni_{f}"] = U[f"{v}_roe"][m].mean()
                    rec[f"uni_eff_{f}"] = rec[f"uni_{f}"] - ub
                # one position at a time (six coins), random tie order, mean over seeds
                if per in ("SEL", "CONF", "FWD") or v == "base":
                    acc = {}
                    for nm, pool in (("all", Q), ("f1", Q[Q.f1]), ("f2", Q[Q.f2])):
                        means, ns, wins, tl = [], [], [], None
                        for sd_ in SEEDS:
                            took = bot(pool, v, dl, sd_)
                            T = pool[took]
                            means.append(T[f"{v}_roe"].mean())
                            ns.append(len(T))
                            if sd_ == SEEDS[0]:
                                tl = T
                        acc[nm] = (np.mean(means), np.mean(ns), tl, np.min(means), np.max(means))
                        rec[f"bot_{nm}"] = np.mean(means)
                        rec[f"bot_{nm}_min"] = np.min(means)
                        rec[f"bot_{nm}_max"] = np.max(means)
                        rec[f"bot_{nm}_perday"] = np.mean(ns) / days
                    for f in ("f1", "f2"):
                        rec[f"bot_eff_{f}"] = acc[f][0] - acc["all"][0]
                        Ta, Tb = acc[f][2], acc["all"][2]
                        rec[f"bot_t_{f}"], rec["bot_months"] = month_t(Ta.t.to_numpy(), Ta[f"{v}_roe"].to_numpy(),
                                                                      Tb.t.to_numpy(), Tb[f"{v}_roe"].to_numpy())
                    rec["bot_f1_pb"] = rec["bot_f1"] + 35 * PAYBACK
                    rec["bot_f2_pb"] = rec["bot_f2"] + 35 * PAYBACK
                rows.append(rec)
                print(tf, per, v, {k: (round(100 * x, 2) if isinstance(x, float) else x) for k, x in rec.items()
                                   if k.startswith(("pool_eff", "uni_eff", "bot_eff", "bot_f", "bot_all", "pool_f",
                                                    "pool_all", "bot_t"))
                                   and not k.endswith(("_min", "_max", "_perday", "_opp"))}, flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(HERE, "vc_results.csv"), index=False, float_format="%.6g")


if __name__ == "__main__":
    main()
