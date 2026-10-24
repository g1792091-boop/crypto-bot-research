"""Re-walk the owners' exit (w35: 35x, net-ROE -50 % stop, ladder 12->10 then 5 %) at 1x, 1.5x and 2x the round-trip
cost for every forward entry of the non-trend signals (the stop and the lock are NET-ROE levels, so a higher cost moves
them; a plain shift of r is not enough), then re-read the friend's principle per signal, per unique entry, with the
live entry blocks, and as executable one-position bots (random tie priority). Read-only. Run without -I:
    python3 cx_cost2.py
Writes cx_cost2.json (small)."""
import sys, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *          # noqa
from fw_prespec_bots import auto_state
import rolesdata as RD
from frdeep import walk3

S = load("sig")
S = S[S.role != "trend"].reset_index(drop=True)
side = S.side.to_numpy()
al = auto_state(S, "Jdir") * side
MULTS = (1.0, 1.5, 2.0)
R = {m: np.full(len(S), np.nan) for m in MULTS}
K = {m: np.full(len(S), -1, np.int64) for m in MULTS}
W = {m: np.full(len(S), -1, np.int8) for m in MULTS}
dummy = np.zeros(1, bool)
for ci, coin in enumerate(COINS):
    mc = S.coin.to_numpy() == ci
    g = grid(coin)
    o, h, l, c = g["o"], g["h"], g["l"], g["c"]
    cumf = np.cumsum(g["fund"])
    n = g["n"]
    for sd in (1, -1):
        q = mc & (side == sd)
        es_all = S.e.to_numpy(np.int64)[q]
        u, inv = np.unique(es_all, return_inverse=True)
        for m in MULTS:
            a = walk3(o, h, l, c, cumf, u, sd, 35.0, COST * m, FL, STEP, GAP, -0.50, 9.0, 0.01, 0, dummy, False, c, o,
                      0.0, n)
            R[m][q] = a[0][inv]; K[m][q] = a[1][inv]; W[m][q] = a[2][inv]
    drop(coin)
    log(coin, "done")

out = {}
# check: 1x re-walk == the study's grid outcome
fin0 = S.w35_why.to_numpy() != 3
out["check_1x_maxabs_r_diff"] = float(np.nanmax(np.abs(R[1.0][fin0] - S.w35_r.to_numpy()[fin0])))
out["check_1x_why_equal"] = float(np.mean(W[1.0][fin0] == S.w35_why.to_numpy()[fin0]))
t = S.t.to_numpy()
blk = S.blk.to_numpy()
key = S.coin.to_numpy().astype(np.int64) * 4 * 10**9 + S.e.to_numpy(np.int64) * 4 + (side + 1)
for m in MULTS:
    roe_ = np.where(W[m] == 3, np.nan, np.maximum(35 * R[m], -1))
    o = {}
    for per, (a, b) in PERIOD.items():
        mp = (t >= a) & (t < b) & np.isfinite(roe_)
        for cl, cc in (("with", 1), ("against", -1), ("neutral", 0)):
            mm = mp & (al == cc)
            x = roe_[mm]
            k_, idx = np.unique(key[mm], return_index=True)
            xb = roe_[mm & (blk == 0)]
            o[f"{per}_{cl}"] = {"n": int(mm.sum()), "mean": float(x.mean()), "win": float((x > 0).mean()),
                                "stop_share": float((W[m][mm] == 0).mean()),
                                "mean_unique": float(x[idx].mean()), "n_unique": int(len(idx)),
                                "mean_blk0": float(xb.mean()), "n_blk0": int(len(xb))}
        o[f"{per}_gap"] = o[f"{per}_with"]["mean"] - o[f"{per}_against"]["mean"]
        o[f"{per}_gap_blk0"] = o[f"{per}_with"]["mean_blk0"] - o[f"{per}_against"]["mean_blk0"]
    # day-cluster CI of the gap (whole period)
    mp = np.isfinite(roe_)
    wm, gm = mp & (al == 1), mp & (al == -1)
    days = np.unique(S.day.to_numpy()[mp]); ix = {d: i for i, d in enumerate(days)}
    gx = np.array([ix[d] for d in S.day.to_numpy()[wm]]); gy = np.array([ix[d] for d in S.day.to_numpy()[gm]])
    sx, cx = np.bincount(gx, roe_[wm], len(days)), np.bincount(gx, minlength=len(days)).astype(float)
    sy, cy = np.bincount(gy, roe_[gm], len(days)), np.bincount(gy, minlength=len(days)).astype(float)
    rng = np.random.default_rng(3)
    idx = rng.integers(0, len(days), (4000, len(days)))
    d = sx[idx].sum(1) / cx[idx].sum(1) - sy[idx].sum(1) / cy[idx].sum(1)
    o["all_gap_ci"] = [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]
    # executable bots: one position over all coins, live entry blocks applied, random tie priority, 200 draws
    X0 = S.assign(r_m=R[m], k_m=K[m], why_m=W[m], roe_m=roe_)
    bots = {}
    for per in ("all", "H1", "H2"):
        a, b = PERIOD[per]
        for setname, sel in (("with", al == 1), ("against", al == -1), ("no_against", al != -1), ("all", al > -9)):
            for bl in (False, True):
                mm = (t >= a) & (t < b) & (W[m] != 3) & sel
                if bl:
                    mm &= blk == 0
                X = X0[mm].reset_index(drop=True)
                X["w35m_k"] = X.k_m
                means, ns, finals = [], [], []
                for sd_ in range(200):
                    X["prio"] = np.random.default_rng(sd_).random(len(X))
                    T = X[RD.one_position(X, "w35m", priority="prio")]
                    x = T.roe_m.to_numpy(float)
                    means.append(x.mean()); ns.append(len(x)); finals.append(np.prod(1 + 0.4 * x))
                bots[f"{per}_{setname}_{'blk0' if bl else 'noblk'}"] = {
                    "n_med": float(np.median(ns)), "mean_med": float(np.median(means)),
                    "mean_p05": float(np.percentile(means, 5)), "mean_p95": float(np.percentile(means, 95)),
                    "final_x_m40_med": float(np.median(finals))}
    o["onepos"] = bots
    out[f"cost_x{m}"] = o
json.dump(out, open("cx_cost2.json", "w"), indent=1)
for m in MULTS:
    o = out[f"cost_x{m}"]
    print(f"== cost x{m}")
    for per in ("all", "H1", "H2"):
        print(per, {cl: (round(100 * o[f'{per}_{cl}']['mean'], 2), round(100 * o[f'{per}_{cl}']['mean_unique'], 2),
                         round(100 * o[f'{per}_{cl}']['mean_blk0'], 2)) for cl in ("with", "against", "neutral")},
              "gap", round(100 * o[f"{per}_gap"], 2), "gap_blk0", round(100 * o[f"{per}_gap_blk0"], 2))
    print("CI", [round(100 * x, 2) for x in o["all_gap_ci"]])
    for k, v in o["onepos"].items():
        print("  ", k, v["n_med"], round(100 * v["mean_med"], 2), round(100 * v["mean_p05"], 2),
              round(100 * v["mean_p95"], 2), round(v["final_x_m40_med"], 3))
print(out["check_1x_maxabs_r_diff"], out["check_1x_why_equal"])
