"""Cost / executability verifier of the claim 'the friend-rule rebuild (B4/B5/B6/B9) loses ~1 ROE point less per trade
than B0 out of sample (2024-01 .. 2026-10-05)'.

Scenarios (all 13 variants re-run through lb_core.candidates + one position, nothing else changed):
  base      COST as in the study (0.124 % round trip) -> must reproduce tests_all13.csv
  cost2     doubled costs (0.248 % round trip)
  exec9     base + 9 bp extra on the entry (the live executors' measured 7.7-8.9 bp worse entry), round trip 0.214 %
  late1     base costs, entry one minute later (the executors' ~75 s lag): entry at the open of minute e+1
  late1c2   late1 + doubled costs
Per scenario: per-trade mean ROE confirm+late, paired opposite side, vs B0 (joint day bootstrap, BH over 13), and the
account view (mean daily log growth at 40 % margin, all calendar days, with/without payback; vs B0 joint bootstrap).
Run from this folder's parent (no -I; pandas): python3 verify/v_cost.py [scenario ...]
Writes verify/v_cost_<scenario>.csv"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import numpy as np            # noqa: E402
import pandas as pd           # noqa: E402

import lb_core as L           # noqa: E402

DAY = 86_400_000
V13 = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "W0", "W3"]
BASE_COST = L.COST
ORIG_WALK = L.run_walk
A, B = L.P_CON[0], L.P_LATE[1]


def bh(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    adj = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    q = np.empty(m)
    q[o] = np.minimum(adj, 1)
    return q


def make_walk(shift):
    def rw(D, force_col="force", opp=False, ladder=L.LADDER2, payback=False):
        if shift == 0:
            return ORIG_WALK(D, force_col, opp, ladder, payback)
        D2 = D.copy()
        D2["e"] = D2.e.to_numpy(np.int64) + shift
        r, k, w = ORIG_WALK(D2, force_col, opp, ladder, payback)
        k = np.where(k >= 0, k + shift, k)       # k counted from the signal minute, so one_position stays consistent
        return r, k, w
    return rw


SCEN = {"base": (BASE_COST, 0), "cost2": (2 * BASE_COST, 0), "exec9": (BASE_COST + 0.0009, 0),
        "late1": (BASE_COST, 1), "late1c2": (2 * BASE_COST, 1)}


def daily_log(T, col="tb_roe", pb=False):
    roe = np.maximum(T[col].to_numpy(float), -1.0)
    if pb:
        roe = roe + L.lev_of(T.coin.to_numpy()) * L.PAYBACK
    lg = np.log(np.maximum(1 + L.MARGIN * roe, 1e-9))
    d0 = A // DAY
    nd = int((B - A) // DAY) + 1
    di = (T.t.to_numpy(np.int64) // DAY - d0).astype(int)
    return np.bincount(di, lg, nd), np.bincount(di, minlength=nd)


def run(scen):
    cost, shift = SCEN[scen]
    L.COST = cost
    L.run_walk = make_walk(shift)
    keep = {}
    for v in V13:
        t0 = time.time()
        S = L.candidates(v, period=(L.ms("2020-03-01"), L.FWD[1]))
        S = S[(S.tb_why != 3) & (S.tb_opp_why != 3)].reset_index(drop=True)
        T = L.taken(S)
        keep[v] = T[(T.t >= A) & (T.t < B)].reset_index(drop=True)
        print(scen, v, len(keep[v]), round(time.time() - t0, 1), "s", flush=True)
    L.COST = BASE_COST
    L.run_walk = ORIG_WALK
    rng = np.random.default_rng(3)
    nd = int((B - A) // DAY) + 1
    pk = rng.integers(0, nd, (5000, nd))
    B0 = keep["B0"]
    s0, c0 = daily_log(B0)[1], None
    rows = []
    for v in V13:
        T = keep[v]
        dV = (T.t.to_numpy(np.int64) // DAY - A // DAY).astype(int)
        d0 = (B0.t.to_numpy(np.int64) // DAY - A // DAY).astype(int)
        sV, cV = np.bincount(dV, T.tb_roe.to_numpy(), nd), np.bincount(dV, minlength=nd)
        s0_, c0_ = np.bincount(d0, B0.tb_roe.to_numpy(), nd), np.bincount(d0, minlength=nd)
        diff = sV[pk].sum(1) / np.maximum(cV[pk].sum(1), 1) - s0_[pk].sum(1) / np.maximum(c0_[pk].sum(1), 1)
        lgV, _ = daily_log(T)
        lg0, _ = daily_log(B0)
        lgVp, _ = daily_log(T, pb=True)
        lg0p, _ = daily_log(B0, pb=True)
        dacc = lgV[pk].mean(1) - lg0[pk].mean(1)
        daccp = lgVp[pk].mean(1) - lg0p[pk].mean(1)
        pb = (T.tb_roe + L.lev_of(T.coin.to_numpy()) * L.PAYBACK).mean()
        rows.append(dict(scen=scen, cost_rt=cost, entry_shift_min=shift, variant=v, n=len(T),
                         per_day=len(T) / ((B - A) / DAY), roe=T.tb_roe.mean(), roe_pb=pb, opp=T.tb_opp_roe.mean(),
                         win=(T.tb_roe > 0).mean(), vs_b0=T.tb_roe.mean() - B0.tb_roe.mean(),
                         vs_b0_p=np.nan if v == "B0" else (diff <= 0).mean(),
                         daylog=lgV.mean(), daylog_pb=lgVp.mean(),
                         acc_vs_b0=lgV.mean() - lg0.mean(), acc_vs_b0_p=np.nan if v == "B0" else (dacc <= 0).mean(),
                         acc_vs_b0_pb=lgVp.mean() - lg0p.mean(),
                         acc_vs_b0_pb_p=np.nan if v == "B0" else (daccp <= 0).mean()))
    R = pd.DataFrame(rows)
    m = R.variant != "B0"
    for c in ("vs_b0_p", "acc_vs_b0_p", "acc_vs_b0_pb_p"):
        q = np.full(len(R), np.nan)
        q[m.to_numpy()] = bh(R.loc[m, c].to_numpy())
        R[c.replace("_p", "_q13") if c.endswith("_p") else c + "_q"] = q
    R.to_csv(os.path.join(HERE, f"v_cost_{scen}.csv"), index=False, float_format="%.5g")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(R[["scen", "variant", "n", "per_day", "roe", "roe_pb", "opp", "vs_b0", "vs_b0_p", "vs_b0_q13",
                 "daylog", "daylog_pb", "acc_vs_b0", "acc_vs_b0_p", "acc_vs_b0_pb", "acc_vs_b0_pb_p"]].to_string())


if __name__ == "__main__":
    for s in (sys.argv[1:] or list(SCEN)):
        run(s)
