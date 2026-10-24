"""Summaries of vcx_rows.csv.gz (lens: costs, executability, overlap) for OBV30@4h>SRSI_X@1h|a2.
 1. reproduce per-signal n / mean ROE per period (x1) and the payback number
 2. per-signal mean under cost x2, x1.5, x0, Bybit taker, funding stress, entry delay 1/2/5 min, liquidation realism
 3. one-position account (study rule: ties by coin order) at 40 % margin, payback on/off, all variants; random tie order
    (1,000 shuffles) and the KST-weekend / US-open blocks of the live combo bots; the live loss cap (max_loss_frac)
 4. day-block bootstrap goal path (rolesdata.goal_bootstrap, same seed) at 58 % / 40 % margin, x1 and x2 costs
Writes vsum.json here.

    python3 vsum.py
"""
import os
import sys
import json

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD                      # noqa: E402
from common import *                        # noqa: E402,F401,F403

HERE = os.path.dirname(os.path.abspath(__file__))
LEV = 30.0
PER = {"SEL": (ms("2021-01-01"), ms("2024-01-01")), "CONF": (ms("2024-01-01"), GRID_END),
       "FWD": (ms("2026-10-05 15:00"), ms("2026-10-24 15:00")), "FIVE": (ms("2020-03-01"), GRID_END)}
VARS = ("x1", "x2", "x1_5", "x0", "bybit", "fneg1", "fneg3", "fpos1", "d1", "d2", "d5", "liq5", "liq10")

R = pd.read_csv(os.path.join(HERE, "vcx_rows.csv.gz"))
blk = np.load(os.path.join(OUT, "grid", "blk15.npy"))
j15 = R.e.to_numpy(np.int64) // 15 - 1
R["blk"] = np.where((j15 >= 0) & (j15 < len(blk)), blk[np.clip(j15, 0, len(blk) - 1)], -1)
sd = R.side.to_numpy()


def side_cols(v, opp=False):
    s = -sd if opp else sd
    r = np.where(s > 0, R[f"{v}_L_r"], R[f"{v}_S_r"])
    k = np.where(s > 0, R[f"{v}_L_k"], R[f"{v}_S_k"])
    w = np.where(s > 0, R[f"{v}_L_w"], R[f"{v}_S_w"])
    return r, k, w


base_r, base_k, base_w = side_cols("x1")
opp_r, opp_k, opp_w = side_cols("x1", True)
KEEP = np.isfinite(base_r) & np.isfinite(opp_r) & (base_w != 3) & (opp_w != 3)   # the study's drop_open rule


def pmask(per):
    a, b = PER[per]
    t = R.t.to_numpy()
    return (t >= a) & (t < b)


out = {"repro": {}, "per_signal": {}, "accounts": {}, "ties": {}, "goal": {}, "exec": {}}
for per in PER:
    m = pmask(per) & KEEP
    out["repro"][per] = {"n": int(m.sum()), "mean_roe": float(LEV * base_r[m].mean()),
                         "mean_roe_payback": float(LEV * (base_r[m] + PAYBACK).mean()),
                         "coinflip_mean_roe": float(LEV * opp_r[m].mean()), "long_share": float((sd[m] > 0).mean()),
                         "dropped_open": int((pmask(per) & ~KEEP & np.isfinite(base_r)).sum())}
    d = {}
    for v in VARS:
        r, k, w = side_cols(v)
        mm = m & np.isfinite(r) & (w != 3)
        d[v] = {"n": int(mm.sum()), "mean_roe": float(LEV * r[mm].mean()),
                "mean_roe_payback": float(LEV * (r[mm] + PAYBACK).mean())}
        if v.startswith("liq"):
            d[v]["liquidated"] = int((mm & (w == 9)).sum())
    d["atrd_gt_2.83pct"] = int((m & (R.atrd > 1 / 30 - 0.005)).sum())
    d["atrd_gt_2.33pct"] = int((m & (R.atrd > 1 / 30 - 0.01)).sum())
    d["atrd_median"] = float(np.median(R.atrd[m]))
    d["hold_min_median"] = float(np.median(base_k[m]))
    d["hold_min_mean"] = float(np.mean(base_k[m]))
    d["exit_lock_share"] = float((base_w[m] == 1).mean())
    d["blk0_n"] = int((m & (R.blk == 0)).sum())
    d["blk0_mean_roe"] = float(LEV * base_r[m & (R.blk == 0)].mean())
    out["per_signal"][per] = d


def frame(per, v="x1", payback=False, keep_blk0=False):
    m = pmask(per) & KEEP
    r, k, w = side_cols(v)
    ro, ko, wo = side_cols(v, True)
    m = m & np.isfinite(r) & (w != 3) & np.isfinite(ro) & (wo != 3)
    if keep_blk0:
        m = m & (R.blk.to_numpy() == 0)
    add = PAYBACK if payback else 0.0
    S = pd.DataFrame({"t": R.t[m].to_numpy(), "e": R.e[m].to_numpy(), "coin": R.coin[m].to_numpy(), "tf": "1h",
                      "side": sd[m], "X_r": r[m] + add, "X_roe": LEV * (r[m] + add), "X_k": k[m].astype(np.int64),
                      "X_why": w[m], "X_opp_roe": LEV * (ro[m] + add), "X_opp_k": ko[m].astype(np.int64),
                      "X_opp_why": wo[m], "atrd": R.atrd[m].to_numpy()})
    return S.sort_values(["t", "coin"]).reset_index(drop=True)


def acct(Tk, margin, col="X_roe", cap=None):
    roe = np.maximum(Tk[col].to_numpy(float), -1.0)
    if cap is not None:   # live loss cap: size cut so a stop-out costs at most cap of equity (stop = 2 ATR + costs)
        stop_loss_frac = margin * LEV * (Tk.atrd.to_numpy() + COST)
        stop_loss_frac = np.minimum(stop_loss_frac, margin * 1.0)
        scale = np.minimum(1.0, cap / stop_loss_frac)
    else:
        scale = 1.0
    eq = np.cumprod(1.0 + margin * scale * roe)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return {"n": len(roe), "mean_roe": float(roe.mean()) if len(roe) else np.nan,
            "final_x": float(eq[-1]) if len(eq) else 1.0, "max_dd": float((1 - eq / peak).max()) if len(eq) else 0.0}


for per in ("FWD", "CONF"):
    a, b = PER[per]
    days = (min(b, ext_end()) - a) / DAY
    for v in VARS:
        for pb in (False, True):
            for b0 in (False, True):
                S = frame(per, v, pb, b0)
                took = RD.one_position(S, "X")
                Tk = S[took]
                rec = {"signals": len(S), "per_day": len(Tk) / days}
                for mg in (0.4, 0.58):
                    rec[f"m{int(round(mg * 100))}"] = acct(Tk, mg)
                    rec[f"m{int(round(mg * 100))}_twin"] = acct(Tk, mg, "X_opp_roe")
                    for cap in (0.15, 0.20):
                        rec[f"m{int(round(mg * 100))}_cap{int(round(cap * 100))}"] = acct(Tk, mg, cap=cap)
                out["accounts"][f"{per}|{v}|pb{int(pb)}|blk0{int(b0)}"] = rec

# tie order: who gets the slot when several coins signal on the same 1h close (study: BTC first)
rng = np.random.default_rng(7)
for per in ("FWD",):
    for v in ("x1", "x2"):
        for pb in (False, True):
            S = frame(per, v, pb)
            same = S.groupby("e").size()
            res = []
            for it in range(1000):
                pr = rng.permutation(len(S))
                S2 = S.assign(pr=pr)
                took = RD.one_position(S2, "X", priority="pr")
                res.append(acct(S2[took], 0.4)["final_x"])
            res = np.array(res)
            out["ties"][f"{per}|{v}|pb{int(pb)}"] = {
                "signals_sharing_a_close": int((S.e.map(same) > 1).sum()), "closes_with_2plus": int((same > 1).sum()),
                "study_order_x": acct(S[RD.one_position(S, "X")], 0.4)["final_x"],
                "random_ties_median_x": float(np.median(res)), "random_ties_p10": float(np.percentile(res, 10)),
                "random_ties_p90": float(np.percentile(res, 90)), "share_below_1": float((res < 1).mean()),
                "min": float(res.min()), "max": float(res.max())}
    # one position per coin (6 slots, margin split 40 %/6 each) instead of one over all coins
    S = frame(per, "x1", False)
    took = np.zeros(len(S), bool)
    for ci in range(6):
        ix = np.flatnonzero(S.coin.to_numpy() == ci)
        sub = S.iloc[ix]
        took[ix] = RD.one_position(sub, "X")
    out["ties"]["FWD|x1|per_coin_slots_taken"] = int(took.sum())
    out["ties"]["FWD|x1|per_coin_slots_mean_roe"] = float(S.X_roe[took].mean())

# goal path (day-block bootstrap, same function and seed as the study)
for per in ("FWD", "CONF"):
    a, b = PER[per]
    for v in ("x1", "x2"):
        for pb in (False, True):
            S = frame(per, v, pb)
            Tk = S[RD.one_position(S, "X")]
            for mg in (0.4, 0.58):
                gb = RD.goal_bootstrap(Tk, "X", margin=mg, days=(a, min(b, ext_end())), n_boot=4000)
                out["goal"][f"{per}|{v}|pb{int(pb)}|m{int(round(mg * 100))}"] = gb

json.dump(out, open(os.path.join(HERE, "vsum.json"), "w"), indent=1, default=float)
print(json.dumps(out["repro"], indent=1))
for per in ("FWD", "CONF", "FIVE"):
    print(per, {v: round(out["per_signal"][per][v]["mean_roe"], 4) for v in VARS})
    print(per, {k: out["per_signal"][per][k] for k in out["per_signal"][per] if not isinstance(out["per_signal"][per][k], dict)})
for k, rec in out["accounts"].items():
    if "|pb" in k and k.split("|")[1] in ("x1", "x2", "x1_5", "bybit", "liq5", "d1", "d2", "fneg3"):
        print(k, rec["signals"], round(rec["per_day"], 2), {q: (round(rec[q]["final_x"], 3), rec[q]["n"])
              for q in ("m40", "m40_twin", "m40_cap20", "m40_cap15", "m58")})
print(json.dumps(out["ties"], indent=1))
for k, g in out["goal"].items():
    print(k, {q: round(g[q], 4) for q in ("p_target", "p_lose50_first", "p_lose90_first", "median_final_x")})
