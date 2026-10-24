"""The 11 pre-registered variants (PLAN.md) over select / confirm / late / fwd: one-position accounts (own side and the
coin-flip twin = the opposite side on the same entries, its own path), per-trade results, the paired direction test and
the comparison with B0 (day-block bootstrap, BH over the 11). Writes variants_summary.csv, variants_tests.csv and the
taken trades of every variant (trades_<v>.csv.gz, small). Run: python3 lb_variants.py [B0 B1 ...]"""
import sys
import time

import lb_core as L
from lb_core import *  # noqa: F401,F403

OUTD = L.LB


def stats(T, side_col, a, b):
    if not len(T):
        return {"n": 0}
    acc = RD.account(T, "tb", margin=L.MARGIN, side_col=side_col, start=a, end=b)
    roe = T[f"tb{side_col}_roe"].to_numpy(float)
    r = T[f"tb{side_col}_r"].to_numpy(float)
    days = (b - a) / DAY
    wk = days * 5 / 7
    return {"n": len(T), "per_day": len(T) / days, "per_weekday": len(T) / wk, "roe": roe.mean(), "r_pct": 100 * r.mean(),
            "roe_pb": (roe + lev_of(T.coin.to_numpy()) * PAYBACK).mean(), "win": (roe > 0).mean(),
            "short": (T.side.to_numpy() * (-1 if side_col else 1) < 0).mean(), "final_x": acc["final_x"],
            "max_dd": acc["max_dd"], "stop_share": (T[f"tb{side_col}_why"] == 0).mean(),
            "forced_share": (T[f"tb{side_col}_why"] == 2).mean()}


def day_boot(day, x, n_boot=5000, seed=1):
    """Mean of x per trade, resampling whole UTC days (days with trades)."""
    ud, inv = np.unique(day, return_inverse=True)
    sums = np.bincount(inv, weights=x)
    cnt = np.bincount(inv)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(ud), (n_boot, len(ud)))
    return sums[pick].sum(1) / np.maximum(cnt[pick].sum(1), 1)


def main(names, tag=""):
    rows, keep = [], {}
    for v in names:
        t0 = time.time()
        S = L.candidates(v)
        S = S[(S.tb_why != 3) & (S.tb_opp_why != 3)].reset_index(drop=True)
        T = L.taken(S)
        To = L.taken(S, "_opp")
        T.drop(columns=[c for c in T.columns if c.startswith("f_")]).to_csv(
            os.path.join(OUTD, "trades", f"trades_{v}.csv.gz"), index=False, float_format="%.6g")
        keep[v] = T
        for pn, (a, b) in list(L.PERIODS4.items()) + [("oos1022", L.P_OOS)]:
            Tp = T[(T.t >= a) & (T.t < b)]
            Top = To[(To.t >= a) & (To.t < b)]
            own, opp = stats(Tp, "", a, b), stats(Top, "_opp", a, b)
            pair = Tp.tb_opp_roe.mean() if len(Tp) else np.nan
            rows.append({"variant": v, "ko": L.KO_VAR[v], "period": pn, "signals": int(((S.t >= a) & (S.t < b)).sum()),
                         **{f"own_{k}": x for k, x in own.items()}, **{f"opp_{k}": x for k, x in opp.items() if k != "n"},
                         "opp_n": opp.get("n", 0), "paired_opp_roe": pair})
        print(v, L.KO_VAR[v], "signals", len(S), "taken", len(T), round(time.time() - t0, 1), "s", flush=True)
        pd.DataFrame(rows).to_csv(os.path.join(OUTD, f"variants_summary{tag}.csv"), index=False, float_format="%.5g")
    # ---- tests on the pooled confirm + late (never used to pick)
    a, b = L.P_CON[0], L.P_LATE[1]
    tests = []
    if "B0" not in keep and os.path.exists(os.path.join(OUTD, "trades", "trades_B0.csv.gz")):
        keep_b0 = pd.read_csv(os.path.join(OUTD, "trades", "trades_B0.csv.gz"))
    else:
        keep_b0 = keep.get("B0")
    if keep_b0 is not None:
        B0 = keep_b0
        B0 = B0[(B0.t >= a) & (B0.t < b)]
    for v, T in keep.items():
        Tp = T[(T.t >= a) & (T.t < b)]
        if len(Tp) < 10:
            continue
        d = (Tp.tb_roe - Tp.tb_opp_roe).to_numpy()
        bs = day_boot(Tp.t.to_numpy() // DAY, d)
        bm = day_boot(Tp.t.to_numpy() // DAY, Tp.tb_roe.to_numpy(), seed=2)
        rec = {"variant": v, "n": len(Tp), "mean_roe": Tp.tb_roe.mean(), "mean_opp_paired": Tp.tb_opp_roe.mean(),
               "dir_diff": d.mean(), "dir_p": (bs <= 0).mean(), "mean_ci_lo": np.quantile(bm, 0.025),
               "mean_ci_hi": np.quantile(bm, 0.975), "p_mean_le0": (bm <= 0).mean()}
        if keep_b0 is not None and v != "B0":
            # joint day resampling: the same days for both
            dV = Tp.t.to_numpy() // DAY
            d0 = B0.t.to_numpy() // DAY
            ud = np.union1d(dV, d0)
            iV, i0 = np.searchsorted(ud, dV), np.searchsorted(ud, d0)
            sV, cV = np.bincount(iV, Tp.tb_roe.to_numpy(), len(ud)), np.bincount(iV, minlength=len(ud))
            s0, c0 = np.bincount(i0, B0.tb_roe.to_numpy(), len(ud)), np.bincount(i0, minlength=len(ud))
            rng = np.random.default_rng(3)
            pk = rng.integers(0, len(ud), (5000, len(ud)))
            diff = sV[pk].sum(1) / np.maximum(cV[pk].sum(1), 1) - s0[pk].sum(1) / np.maximum(c0[pk].sum(1), 1)
            rec.update(vs_b0=Tp.tb_roe.mean() - B0.tb_roe.mean(), vs_b0_p=(diff <= 0).mean())
        tests.append(rec)
    Te = pd.DataFrame(tests)
    for col in ("dir_p", "vs_b0_p", "p_mean_le0"):
        if col in Te:
            p = Te[col].to_numpy(float)
            ok = np.isfinite(p)
            q = np.full(len(p), np.nan)
            if ok.sum():
                o = np.argsort(p[ok])
                m = ok.sum()
                adj = np.minimum.accumulate((p[ok][o] * m / np.arange(1, m + 1))[::-1])[::-1]
                qq = np.empty(m)
                qq[o] = np.minimum(adj, 1)
                q[ok] = qq
            Te[col.replace("_p", "_q") if col != "p_mean_le0" else "q_mean_le0"] = q
    Te.to_csv(os.path.join(OUTD, f"variants_tests{tag}.csv"), index=False, float_format="%.5g")
    print(Te.to_string())


if __name__ == "__main__":
    os.makedirs(os.path.join(OUTD, "trades"), exist_ok=True)
    a = sys.argv[1:]
    tag = ""
    if a and a[0].startswith("--tag="):
        tag, a = a[0][6:], a[1:]
    main(a or [v for v in L.VARIANTS_DEF if v.startswith("B")], tag)
