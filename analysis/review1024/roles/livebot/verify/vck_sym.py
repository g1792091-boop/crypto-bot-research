"""Verifier: is 'opposite side better than the bot's side' (B0/B2) robust to (a) the coin-flip twin's exit rule (the
twin is forced out when the judge turns TOWARD it, the bot's rule; here also: the twin with its OWN symmetric forced
exits, and both sides with no forced exit), (b) the period (select / confirm / late separately), (c) the one-position
path (signal level, every passing signal alone), (d) the attribution to the checks (gap(B2) - gap(B3), joint days)?
Run (no -I): python3 vck_sym.py"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import lb_core as L
from lb_core import *  # noqa

def boot(day, x, n=5000, seed=1):
    ud, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=x); c = np.bincount(inv)
    pk = np.random.default_rng(seed).integers(0, len(ud), (n, len(ud)))
    return s[pk].sum(1) / np.maximum(c[pk].sum(1), 1)

def extra_walks(S):
    S = S.copy()
    lev = lev_of(S.coin.to_numpy())
    # twin with its own exits: judge against the TWIN's side, the member's next signal on the bot's side
    F = S.copy(); F["side"] = (-F.side).astype(np.int8)
    jm = L.judge_exit_minute(F, L.HTF_OF, "vote3"); rm = L.rev_exit_minute(F)
    F["force_sym"] = np.where(jm < 0, rm, np.where(rm < 0, jm, np.minimum(jm, rm)))
    r, k, w = L.run_walk(F, "force_sym")
    S["opp_sym_roe"], S["opp_sym_why"] = lev * r, w
    # no forced exits, both sides
    S["noforce"] = -1
    r, k, w = L.run_walk(S, "noforce"); S["own_nf_roe"], S["own_nf_why"] = lev * r, w
    r, k, w = L.run_walk(S, "noforce", opp=True); S["opp_nf_roe"], S["opp_nf_why"] = lev * r, w
    return S

out = {}
for v in ("B0", "B2", "B3"):
    S = L.candidates(v)
    S = S[(S.tb_why != 3) & (S.tb_opp_why != 3)].reset_index(drop=True)
    S = extra_walks(S)
    S = S[(S.opp_sym_why != 3) & (S.own_nf_why != 3) & (S.opp_nf_why != 3)].reset_index(drop=True)
    T = L.taken(S)
    out[v] = (S, T)
    print(f"\n=== {v}: signals {len(S)}  taken {len(T)}")
    for lab, X in (("one-position (taken)", T), ("signal level (all passing)", S)):
        for pn, per in (("select", ["select"]), ("confirm", ["confirm"]), ("late", ["late"]), ("conf+late", ["confirm", "late"]), ("fwd", ["fwd"])):
            P = X[X.period.isin(per)]
            if not len(P):
                continue
            day = P.t.to_numpy() // DAY
            res = []
            for col in ("tb_opp_roe", "opp_sym_roe"):
                d = (P.tb_roe - P[col]).to_numpy()
                bs = boot(day, d)
                res.append(f"{col.replace('_roe',''):>9s} {100*P[col].mean():+.2f} gap {100*d.mean():+.2f} p(opp>=own) {(bs >= 0).mean():.3f}")
            d = (P.own_nf_roe - P.opp_nf_roe).to_numpy(); bs = boot(day, d)
            res.append(f"noforce own {100*P.own_nf_roe.mean():+.2f} opp {100*P.opp_nf_roe.mean():+.2f} gap {100*d.mean():+.2f} p {(bs >= 0).mean():.3f}")
            print(f" {lab:27s} {pn:9s} n {len(P):5d} own {100*P.tb_roe.mean():+.2f} | " + " | ".join(res))
# (d) attribution: gap(B2) - gap(B3) with joint day resampling (one-position trades and signal level)
for lab, idx in (("taken", 1), ("signals", 0)):
    for pn, per in (("select", ["select"]), ("confirm", ["confirm"]), ("late", ["late"]), ("conf+late", ["confirm", "late"])):
        X2 = out["B2"][idx]; X3 = out["B3"][idx]
        X2 = X2[X2.period.isin(per)]; X3 = X3[X3.period.isin(per)]
        d2, d3 = X2.t.to_numpy() // DAY, X3.t.to_numpy() // DAY
        ud = np.union1d(d2, d3); i2, i3 = np.searchsorted(ud, d2), np.searchsorted(ud, d3)
        g2 = (X2.tb_roe - X2.tb_opp_roe).to_numpy(); g3 = (X3.tb_roe - X3.tb_opp_roe).to_numpy()
        s2, c2 = np.bincount(i2, g2, len(ud)), np.bincount(i2, minlength=len(ud))
        s3, c3 = np.bincount(i3, g3, len(ud)), np.bincount(i3, minlength=len(ud))
        pk = np.random.default_rng(3).integers(0, len(ud), (5000, len(ud)))
        diff = s2[pk].sum(1) / np.maximum(c2[pk].sum(1), 1) - s3[pk].sum(1) / np.maximum(c3[pk].sum(1), 1)
        print(f"gap(B2)-gap(B3) {lab:8s} {pn:9s} {100*(g2.mean()-g3.mean()):+.2f}pt  p(B2 gap >= B3 gap) {(diff >= 0).mean():.3f}")
