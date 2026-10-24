"""Verifier (costs / executability / overlap lens) of the claim: 'the 7 extra checks make the bot's direction
significantly worse than a coin flip (B0 own -4.39 vs opposite -2.26, p 0.003, q13 0.039; B2 q 0.046; B3 gap -0.48) and
보류 entries are 38-39 % of the bot's trades'.
Part A (from the saved trades files): reproduce, two-sided p, BH13 on two-sided p, per period, week/month blocks,
  gap difference B2-B3 / B0-B3, hold share.
Part B (re-run): B0 / B2 / B3 under gross (cost 0), cost2, exec9 (cost + 9 bp), late1 (entry 1 min later), and B0/B2
  without the forced exits (the coin twin then has only stop + ladder), the paired direction gap and its p.
Run from the livebot folder's verify dir parent: python3 verify/vcx_dir.py [A] [B]"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LBD = os.path.dirname(HERE)
sys.path.insert(0, LBD)
import numpy as np            # noqa: E402
import pandas as pd           # noqa: E402

DAY = 86_400_000
V13 = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "W0", "W3"]


def bh(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    adj = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    q = np.empty(m)
    q[o] = np.minimum(adj, 1)
    return q


def block_boot(t, x, block_days=1, n=5000, seed=1):
    blk = (np.asarray(t, np.int64) // (DAY * block_days))
    ub, inv = np.unique(blk, return_inverse=True)
    s = np.bincount(inv, weights=x)
    c = np.bincount(inv)
    rng = np.random.default_rng(seed)
    pk = rng.integers(0, len(ub), (n, len(ub)))
    return s[pk].sum(1) / np.maximum(c[pk].sum(1), 1)


def ptwo(bs, x0=0.0):
    lo = (bs <= x0).mean()
    hi = (bs >= x0).mean()
    return min(1.0, 2 * min(lo, hi)), lo, hi


def load(v):
    return pd.read_csv(os.path.join(LBD, "trades", f"trades_{v}.csv.gz"))


def partA():
    import lb_core as L
    a, b = L.P_CON[0], L.P_LATE[1]
    rows = []
    for v in V13:
        T = load(v)
        Tp = T[(T.t >= a) & (T.t < b)]
        d = (Tp.tb_roe - Tp.tb_opp_roe).to_numpy()
        rec = dict(variant=v, n=len(Tp), own=Tp.tb_roe.mean(), opp=Tp.tb_opp_roe.mean(), gap=d.mean())
        for bd in (1, 7, 30):
            bs = block_boot(Tp.t.to_numpy(), d, bd, seed=1)
            p2, lo, hi = ptwo(bs)
            rec[f"p_opp_better_{bd}d"] = (bs <= 0).mean()
            rec[f"p2_{bd}d"] = p2
        rows.append(rec)
    R = pd.DataFrame(rows)
    for bd in (1, 7, 30):
        R[f"q13_1s_{bd}d"] = bh(R[f"p_opp_better_{bd}d"])
        R[f"q13_2s_{bd}d"] = bh(R[f"p2_{bd}d"])
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print("== A1: confirm+late paired direction gap, block bootstrap (1/7/30 days), BH over 13")
    print(R.round(4).to_string())
    R.to_csv(os.path.join(HERE, "vcx_dirA1.csv"), index=False, float_format="%.5g")

    print("\n== A2: per period (B0, B1, B2, B3), paired gap, day-block p(opp better), two-sided")
    out = []
    for v in ("B0", "B1", "B2", "B3"):
        T = load(v)
        for pn, (x, y) in list(L.PERIODS4.items()) + [("all_2020_2026_10_05", (L.P_SEL[0], L.P_LATE[1]))]:
            Tp = T[(T.t >= x) & (T.t < y)]
            if len(Tp) < 5:
                continue
            d = (Tp.tb_roe - Tp.tb_opp_roe).to_numpy()
            bs = block_boot(Tp.t.to_numpy(), d, 1)
            p2, lo, hi = ptwo(bs)
            out.append(dict(variant=v, period=pn, n=len(Tp), own=Tp.tb_roe.mean(), opp=Tp.tb_opp_roe.mean(),
                            gap=d.mean(), p_opp_better=lo, p2=p2, hold_share=(Tp.j_dir == 0).mean(),
                            short_share=(Tp.side < 0).mean()))
    P = pd.DataFrame(out)
    print(P.round(4).to_string())
    P.to_csv(os.path.join(HERE, "vcx_dirA2.csv"), index=False, float_format="%.5g")

    print("\n== A3: is the gap of B0 / B2 really different from B3's? joint day bootstrap, confirm+late")
    ud_all = None
    G = {}
    for v in ("B0", "B2", "B3"):
        T = load(v)
        Tp = T[(T.t >= a) & (T.t < b)]
        G[v] = (Tp.t.to_numpy() // DAY, (Tp.tb_roe - Tp.tb_opp_roe).to_numpy())
    ud = np.unique(np.concatenate([G[v][0] for v in G]))
    rng = np.random.default_rng(7)
    pk = rng.integers(0, len(ud), (5000, len(ud)))
    M = {}
    for v, (dd, x) in G.items():
        i = np.searchsorted(ud, dd)
        s, c = np.bincount(i, x, len(ud)), np.bincount(i, minlength=len(ud))
        M[v] = s[pk].sum(1) / np.maximum(c[pk].sum(1), 1)
    for v in ("B0", "B2"):
        dd = M[v] - M["B3"]
        print(f"gap {v} - gap B3 = {G[v][1].mean() - G['B3'][1].mean():+.4f}; p(gap_{v} >= gap_B3) = {(dd >= 0).mean():.4f};"
              f" 95% {np.quantile(dd, .025):+.4f} .. {np.quantile(dd, .975):+.4f}")

    print("\n== A4: 보류 share of B0 one-position trades per period")
    T = load("B0")
    for pn, (x, y) in L.PERIODS4.items():
        Tp = T[(T.t >= x) & (T.t < y)]
        h = Tp.j_dir == 0
        print(pn, len(Tp), f"hold share {h.mean():.3f}", f"hold roe {Tp.tb_roe[h].mean():+.4f} opp {Tp.tb_opp_roe[h].mean():+.4f}",
              f"| trend roe {Tp.tb_roe[~h].mean():+.4f} opp {Tp.tb_opp_roe[~h].mean():+.4f}")
    Tp = T[(T.t >= a) & (T.t < b)]
    h = (Tp.j_dir == 0).to_numpy()
    for lab, m in (("hold", h), ("with-trend", ~h)):
        d = (Tp.tb_roe - Tp.tb_opp_roe).to_numpy()[m]
        bs = block_boot(Tp.t.to_numpy()[m], d, 1)
        print(f"confirm+late B0 {lab}: n {m.sum()} own {Tp.tb_roe.to_numpy()[m].mean():+.4f} opp {Tp.tb_opp_roe.to_numpy()[m].mean():+.4f}"
              f" gap {d.mean():+.4f} p(opp better) {(bs <= 0).mean():.4f}")


def partB(variants=("B0", "B2", "B3")):
    import lb_core as L
    base_cost = L.COST
    orig = L.run_walk
    a, b = L.P_CON[0], L.P_LATE[1]

    def shifted(shift):
        def rw(D, force_col="force", opp=False, ladder=L.LADDER2, payback=False):
            if shift == 0:
                return orig(D, force_col, opp, ladder, payback)
            D2 = D.copy()
            D2["e"] = D2.e.to_numpy(np.int64) + shift
            r, k, w = orig(D2, force_col, opp, ladder, payback)
            return r, np.where(k >= 0, k + shift, k), w
        return rw

    scen = {"base": (base_cost, 0, True), "gross0": (0.0, 0, True), "cost2": (2 * base_cost, 0, True),
            "cost3": (3 * base_cost, 0, True), "exec9": (base_cost + 0.0009, 0, True), "late1": (base_cost, 1, True),
            "late1c2": (2 * base_cost, 1, True), "noforce": (base_cost, 0, False), "noforce_c2": (2 * base_cost, 0, False)}
    want = sys.argv[3:] if len(sys.argv) > 3 else list(scen)
    rows = []
    for sn in want:
        cost, shift, forced = scen[sn]
        L.COST = cost
        L.run_walk = shifted(shift)
        saved = {k: dict(v) for k, v in L.VARIANTS_DEF.items()}
        for v in variants:
            if not forced:
                L.VARIANTS_DEF[v]["exits"] = False
            t0 = time.time()
            S = L.candidates(v)
            S = S[(S.tb_why != 3) & (S.tb_opp_why != 3)].reset_index(drop=True)
            T = L.taken(S)
            Tp = T[(T.t >= a) & (T.t < b)]
            d = (Tp.tb_roe - Tp.tb_opp_roe).to_numpy()
            rec = dict(scen=sn, cost_rt=cost, shift=shift, forced=forced, variant=v, n=len(Tp), own=Tp.tb_roe.mean(),
                       opp=Tp.tb_opp_roe.mean(), gap=d.mean(), hold_share=(Tp.j_dir == 0).mean())
            for bd in (1, 7):
                bs = block_boot(Tp.t.to_numpy(), d, bd)
                p2, lo, hi = ptwo(bs)
                rec[f"p_opp_better_{bd}d"] = lo
                rec[f"p2_{bd}d"] = p2
            # select period gap too
            Ts = T[(T.t >= L.P_SEL[0]) & (T.t < L.P_SEL[1])]
            rec["sel_n"], rec["sel_gap"] = len(Ts), (Ts.tb_roe - Ts.tb_opp_roe).mean()
            Tf = T[(T.t >= L.P_FWD[0]) & (T.t < L.P_FWD[1])]
            rec["fwd_n"], rec["fwd_gap"] = len(Tf), (Tf.tb_roe - Tf.tb_opp_roe).mean()
            rows.append(rec)
            print(sn, v, len(Tp), f"own {rec['own']:+.4f} opp {rec['opp']:+.4f} gap {rec['gap']:+.4f} "
                  f"p1d {rec['p_opp_better_1d']:.4f} p2_1d {rec['p2_1d']:.4f} p2_7d {rec['p2_7d']:.4f} "
                  f"sel_gap {rec['sel_gap']:+.4f} fwd_gap {rec['fwd_gap']:+.4f} ({rec['fwd_n']})", round(time.time() - t0, 1), "s",
                  flush=True)
        L.VARIANTS_DEF.clear()
        L.VARIANTS_DEF.update(saved)
        L.COST = base_cost
        L.run_walk = orig
        pd.DataFrame(rows).to_csv(os.path.join(HERE, "vcx_dirB.csv"), index=False, float_format="%.5g")


if __name__ == "__main__":
    parts = sys.argv[1:2] or ["A"]
    if parts[0] == "A":
        partA()
    elif parts[0] == "B":
        vs = tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else ("B0", "B2", "B3")
        partB(vs)
