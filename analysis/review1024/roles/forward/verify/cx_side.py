"""Side composition vs judge effect: within-side gaps (WITH - AGAINST) per signal (w35, a2), with the live entry blocks,
by mapping, and on the rule bot's real executed house-exit trades. Read-only. Run without -I: python3 cx_side.py
Writes cx_side.json."""
import sys, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *          # noqa
from fw_prespec_bots import auto_state
import rolesdata as RD

S = load("sig")
S = S[S.role != "trend"].reset_index(drop=True)
side = S.side.to_numpy(); al = auto_state(S, "Jdir") * side
t = S.t.to_numpy(); blk = S.blk.to_numpy(); tf = S.tf.to_numpy()
out = {}


def split(r, base):
    o = {}
    for sd, s in (("L", 1), ("S", -1)):
        w = base & (side == s) & (al == 1) & np.isfinite(r)
        g = base & (side == s) & (al == -1) & np.isfinite(r)
        o[sd] = {"n_with": int(w.sum()), "with": float(r[w].mean()), "n_against": int(g.sum()),
                 "against": float(r[g].mean()), "gap": float(r[w].mean() - r[g].mean())}
    # side-standardised gap: within-side gaps weighted by the side mix of with+against together
    m = base & np.isfinite(r) & (al != 0)
    pL = float(np.mean(side[m] > 0))
    o["std_gap"] = pL * o["L"]["gap"] + (1 - pL) * o["S"]["gap"]
    w = base & (al == 1) & np.isfinite(r); g = base & (al == -1) & np.isfinite(r)
    o["raw_gap"] = float(r[w].mean() - r[g].mean())
    o["share_long_with"] = float(np.mean(side[w] > 0)); o["share_long_against"] = float(np.mean(side[g] > 0))
    return o


for v in ("w35", "a2"):
    r = roe(S, v)
    for per, (a, b) in PERIOD.items():
        for bl in (False, True):
            base = (t >= a) & (t < b) & ((blk == 0) if bl else True)
            out[f"{v}_{per}_{'blk0' if bl else 'all'}"] = split(r, base)
        for tf_ in ("15m", "30m", "1h", "4h"):
            for bl in (False, True):
                base = (t >= a) & (t < b) & (tf == tf_) & ((blk == 0) if bl else True)
                out[f"{v}_{per}_{tf_}_{'blk0' if bl else 'all'}"] = split(r, base)

# rule bot real trades (house exits), as in fw_principle part D
F = RD.forward("rule")
F = F[(F.taken == 1) & F.tr_roe.notna() & F.tf.isin(TFS) & (F.coin >= 0) & ~F.group.isin(["flip"])].copy()
alF = np.sign(np.nan_to_num(F.tj_dir.to_numpy())) * F.side.to_numpy()
rb = {}
for rk in ("all", "nontrend"):
    mr = np.ones(len(F), bool) if rk == "all" else (F.role.to_numpy() != "trend")
    for col in ("tr_roe", "w35"):
        x = F.tr_roe.to_numpy(float) if col == "tr_roe" else np.where(F.w35_why.to_numpy() == 3, np.nan,
                                                                      np.maximum(35 * F.w35_r.to_numpy(float), -1))
        o = {}
        for sd, s in (("L", 1), ("S", -1)):
            w = mr & (F.side.to_numpy() == s) & (alF == 1) & np.isfinite(x)
            g = mr & (F.side.to_numpy() == s) & (alF == -1) & np.isfinite(x)
            o[sd] = {"n_with": int(w.sum()), "with": float(x[w].mean()), "n_against": int(g.sum()),
                     "against": float(x[g].mean()), "gap": float(x[w].mean() - x[g].mean()),
                     "pnl_with": float(F.tr_pnl.to_numpy()[w].sum()), "pnl_against": float(F.tr_pnl.to_numpy()[g].sum())}
        m = mr & (alF != 0) & np.isfinite(x)
        pL = float(np.mean(F.side.to_numpy()[m] > 0))
        o["std_gap"] = pL * o["L"]["gap"] + (1 - pL) * o["S"]["gap"]
        w = mr & (alF == 1) & np.isfinite(x); g = mr & (alF == -1) & np.isfinite(x)
        o["raw_gap"] = float(x[w].mean() - x[g].mean())
        rb[f"{rk}_{col}"] = o
    # counterfactual: against trades priced at the same-side WITH average (house exits, per-trade pnl / margin)
    roeF = F.tr_roe.to_numpy(float); mg = F.tr_margin.to_numpy(float); pnl = F.tr_pnl.to_numpy(float)
    cf = 0.0; act = 0.0
    for s in (1, -1):
        w = mr & (F.side.to_numpy() == s) & (alF == 1)
        g = mr & (F.side.to_numpy() == s) & (alF == -1)
        cf += float(np.sum(mg[g]) * roeF[w].mean()); act += float(pnl[g].sum())
    rb[f"{rk}_against_pnl_actual"] = act
    rb[f"{rk}_against_pnl_if_sameside_with_avg"] = cf
    rb[f"{rk}_total_pnl"] = float(pnl[mr].sum())
out["rulebot"] = rb
json.dump(out, open("cx_side.json", "w"), indent=1)


def f(o):
    return (f"L {100*o['L']['with']:+.2f}/{100*o['L']['against']:+.2f} gap {100*o['L']['gap']:+.2f} | "
            f"S {100*o['S']['with']:+.2f}/{100*o['S']['against']:+.2f} gap {100*o['S']['gap']:+.2f} | "
            f"raw {100*o['raw_gap']:+.2f} std {100*o['std_gap']:+.2f}")


for k, o in out.items():
    if k == "rulebot":
        continue
    if any(x in k for x in ("15m", "30m", "1h", "4h")) and "w35" not in k:
        continue
    print(k, f(o))
for k, o in rb.items():
    print("RB", k, f(o) if isinstance(o, dict) else round(o))
