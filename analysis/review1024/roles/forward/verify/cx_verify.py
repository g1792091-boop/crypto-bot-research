"""Adversarial check (lens: costs, executability, overlap) of the claim 'trend-aligned entries lose much less than
counter-trend entries on the forward data'. Read-only over the study's cached tables. Run without -I:
    python3 cx_verify.py
Writes cx_verify.json in this folder (small)."""
import sys, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *          # noqa
from fw_prespec_bots import auto_state

out = {}
S = load("sig")
S = S[S.role != "trend"].reset_index(drop=True)
side = S.side.to_numpy()
al = auto_state(S, "Jdir") * side
r = roe(S, "w35")
t = S.t.to_numpy()
fin = np.isfinite(r)


def grp(m):
    x = r[m & fin]
    return {"n": int((m).sum()), "n_fin": int(len(x)), "mean": float(np.mean(x)) if len(x) else None,
            "win": float(np.mean(x > 0)) if len(x) else None}


# A. reproduce
A = {}
for per, (a, b) in PERIOD.items():
    mp = (t >= a) & (t < b)
    for cl, c in (("with", 1), ("against", -1), ("neutral", 0)):
        A[f"{per}_{cl}"] = grp(mp & (al == c))
        for sd, s in (("L", 1), ("S", -1)):
            A[f"{per}_{cl}_{sd}"] = grp(mp & (al == c) & (side == s))
for tf in ("15m", "30m", "1h", "4h"):
    for cl, c in (("with", 1), ("against", -1)):
        A[f"map_{tf}_{cl}"] = grp((S.tf.to_numpy() == tf) & (al == c))
out["A_reproduce"] = A

# B. overlap: unique (coin, entry minute, side) within each class -- w35 depends only on these
B = {}
key = S.coin.to_numpy().astype(np.int64) * 10**9 * 4 + S.e.to_numpy(np.int64) * 4 + (side + 1)
for per, (a, b) in PERIOD.items():
    mp = (t >= a) & (t < b) & fin
    for cl, c in (("with", 1), ("against", -1), ("neutral", 0)):
        m = mp & (al == c)
        k, idx = np.unique(key[m], return_index=True)
        x = r[m][idx]
        B[f"{per}_{cl}"] = {"n_signals": int(m.sum()), "n_unique_entries": int(len(k)),
                            "dup_factor": float(m.sum() / max(len(k), 1)), "mean_unique": float(np.mean(x)),
                            "win_unique": float(np.mean(x > 0))}
    # entries that are BOTH with (in one tf mapping) and against (another) at the same coin/minute/side
# unique (coin, e) 'moments': how many distinct entry minutes per day in each class
for cl, c in (("with", 1), ("against", -1)):
    m = fin & (al == c)
    ce = np.unique(S.coin.to_numpy()[m].astype(np.int64) * 10**9 + S.e.to_numpy(np.int64)[m])
    B[f"distinct_coin_minutes_{cl}"] = int(len(ce))
out["B_overlap"] = B

# C. the live entry blocks (KST weekend, US macro +-30 min, NYSE open +-30 min): the live bots do not enter there
C = {}
blk = S.blk.to_numpy()
for per, (a, b) in PERIOD.items():
    mp = (t >= a) & (t < b)
    for cl, c in (("with", 1), ("against", -1), ("neutral", 0)):
        C[f"{per}_{cl}_blk0"] = grp(mp & (al == c) & (blk == 0))
C["share_blocked"] = float(np.mean(blk != 0))
C["blk_counts"] = {int(k): int(v) for k, v in zip(*np.unique(blk, return_counts=True))}
out["C_blocks"] = C

# D. naive cost stress (shift of r by extra round-trip cost; walk NOT re-run -- see cx_cost2.py for the re-walk)
D = {}
for mult in (1.5, 2.0, 3.0):
    extra = (mult - 1) * COST * 35
    for cl, c in (("with", 1), ("against", -1)):
        x = r[fin & (al == c)]
        D[f"x{mult}_{cl}"] = float(np.mean(np.maximum(x - extra, -1)))
out["D_cost_shift_naive"] = D

# E. one position at a time (all coins) with RANDOM priority among signals at the same entry minute
#    and one position PER COIN (6 slots); w35; whole period, H1, H2
import rolesdata as RD


def onepos(X, per_coin=False, seed=0):
    rng = np.random.default_rng(seed)
    X = X.copy()
    X["prio"] = rng.random(len(X))
    if not per_coin:
        T = X[RD.one_position(X, "w35", priority="prio")]
    else:
        T = pd.concat([X[X.coin == c].reset_index(drop=True).pipe(
            lambda Y: Y[RD.one_position(Y, "w35", priority="prio")]) for c in range(6)])
    return T


E = {}
ND = 200
for per in ("all", "H1", "H2"):
    a, b = PERIOD[per]
    for cl, c in (("with", 1), ("against", -1), ("all", None)):
        m = (t >= a) & (t < b) & (S.w35_why.to_numpy() != 3)
        if c is not None:
            m &= al == c
        X = S[m].reset_index(drop=True)
        for pc in (False, True):
            means, ns, opp = [], [], []
            for sd in range(ND if not pc else 50):
                T = onepos(X, pc, sd)
                x = np.maximum(T.w35_roe.to_numpy(float), -1)
                means.append(x.mean()); ns.append(len(x))
                opp.append(np.maximum(T.w35_opp_roe.to_numpy(float), -1).mean())
            E[f"{per}_{cl}_{'percoin' if pc else 'one'}"] = {
                "n_med": float(np.median(ns)), "mean_med": float(np.median(means)),
                "mean_p05": float(np.percentile(means, 5)), "mean_p95": float(np.percentile(means, 95)),
                "coinflip_med": float(np.median(opp))}
out["E_onepos_random_priority"] = E

json.dump(out, open("cx_verify.json", "w"), indent=1)
print(json.dumps(out, indent=1))
