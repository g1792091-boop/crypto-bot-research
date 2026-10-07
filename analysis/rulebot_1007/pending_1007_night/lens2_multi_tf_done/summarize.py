"""Summaries of sim.py results.

    python3 -I -B summarize.py <core_sig_dir> <res_dir> <out_dir>

Writes per_strategy.csv, pooled.csv, paired.csv, blocking_long.csv, blocked_matrix.csv.
"""
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', '/home/user/crypto-bot-research']
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

TF_MIN = np.array([15, 30, 60, 240])
SPLIT = pd.Timestamp("2024-07-01").value
START, END = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
RISK = 0.02
BUDGET_DAY = 500.0 / 30 / 30.4   # owners' ~$500/month for ~30 traders -> $ per trader per day
NB = 2000
DS_MAIN = None


def family(name):
    if name.startswith("C:"):
        return "core"
    return name[2:].split("_")[0]


def maxdd(R):
    if not len(R):
        return np.nan, np.nan
    c = np.concatenate([[0.0], np.cumsum(R)])
    dd_r = float(np.max(np.maximum.accumulate(c) - c))
    eq = np.concatenate([[1.0], np.cumprod(np.maximum(1 + RISK * R, 1e-9))])
    dd_p = float(np.max(1 - eq / np.maximum.accumulate(eq)))
    return dd_r, dd_p


def main(core_dir, res_dir, out_dir):
    ts15 = np.load(os.path.join(core_dir, "sig_15m_BTCUSD.npz"))["ts"]
    week = ((ts15 - START) // (7 * 86400 * 10**9)).astype(int)
    nweek = int(week.max()) + 1
    days = {"all": (END - START) / 86400e9, "IS": (SPLIT - START) / 86400e9, "CF": (END - SPLIT) / 86400e9}
    rows, wk = [], {}
    blk_rows, mat_rows = [], []
    for fn in sorted(os.listdir(res_dir)):
        name = fn[:-4].replace("__", ":", 1)
        z = np.load(os.path.join(res_dir, fn))
        combos = sorted({"|".join(k.split("|")[:2]) for k in z.files})
        for cb in combos:
            g = lambda k: z[f"{cb}|{k}"]  # noqa: E731
            e, xe, R, gross, tf = g("tr|e"), g("tr|xe"), g("tr|R").astype(float), g("tr|gross").astype(float), g("tr|tf")
            sw_out, alone, nlow, nall, hold = g("tr|switched_out"), g("tr|alone_R").astype(float), g("tr|nblk_low"), g("tr|nblk_all"), g("tr|hold_min")
            be, btf, bR, bheld, btie = g("bl|e"), g("bl|tf"), g("bl|R").astype(float), g("bl|held_tf"), g("bl|tie")
            cnt = g("cnt")
            n_sig, n_inf, n_sw, n_conf = (int(v) for v in cnt[:4])
            ets = ts15[e]
            order = np.argsort(xe, kind="stable")
            for per in ("all", "IS", "CF"):
                m = np.ones(len(e), bool) if per == "all" else (ets < SPLIT if per == "IS" else ets >= SPLIT)
                bm = np.ones(len(be), bool) if per == "all" else (ts15[be] < SPLIT if per == "IS" else ts15[be] >= SPLIT) if len(be) else np.zeros(0, bool)
                d = days[per]
                Rm = R[m]
                n = int(m.sum())
                dd_r, dd_p = maxdd(R[order][m[order]])
                busy = bm & ~btie.astype(bool) if len(be) else bm
                tie = bm & btie.astype(bool) if len(be) else bm
                nsig_p = n + int(bm.sum()) + int((sw_out & m).sum()) * 0
                hold_bars = hold[m] / TF_MIN[tf[m]]
                rows.append(dict(
                    strategy=name, family=family(name), combo=cb, scope=cb.split("|")[0], rule=cb.split("|")[1], period=per,
                    signals=nsig_p, signals_per_day=nsig_p / d, infeasible_in_scope=n_inf if per == "all" else np.nan,
                    trades=n, trades_per_day=n / d, sumR=float(Rm.sum()), meanR=float(Rm.mean()) if n else np.nan,
                    win=float((Rm > 0).mean()) if n else np.nan, mean_gross=float(gross[m].mean()) if n else np.nan,
                    mean_cost=float((gross[m] - Rm).mean()) if n else np.nan,
                    taken_alone_meanR=float(alone[m].mean()) if n else np.nan,
                    blocked_busy=int(busy.sum()), blocked_tie=int(tie.sum()),
                    blocked_share=float(busy.sum() / max(nsig_p, 1)), tie_share=float(tie.sum() / max(nsig_p, 1)),
                    blocked_meanR=float(bR[bm].mean()) if bm.any() else np.nan,
                    blocked_sumR=float(bR[bm].sum()),
                    switches=int((sw_out & m).sum()), switch_cost_R=float((R[m & sw_out] - alone[m & sw_out]).mean()) if (m & sw_out).any() else np.nan,
                    maxdd_R=dd_r, maxdd_pct_2pct=dd_p,
                    hold_h_mean=float(hold[m].mean() / 60) if n else np.nan, hold_h_median=float(np.median(hold[m]) / 60) if n else np.nan,
                    tf_mix=" ".join(f"{t}:{int((tf[m] == i).sum())}" for i, t in enumerate(("15m", "30m", "1h", "4h"))),
                    calls_entry_free_per_day=n / d,
                    calls_entry_all_per_day=nsig_p / d,
                    calls_hold_tfbar_per_day=float(hold_bars.sum()) / d,
                    calls_hold_30m_per_day=float((hold[m] / 30).sum()) / d,
                ))
            # weekly sums for cluster bootstrap
            w = week[e]
            sR = np.bincount(w, weights=R, minlength=nweek)
            sn = np.bincount(w, minlength=nweek).astype(float)
            wk[(name, cb)] = (sR, sn)
            # long-hold blocking (multi-tf scopes)
            if cb.split("|")[0] in ("ALL", "ALLINF"):
                hi = tf >= 2
                blk_rows.append(dict(strategy=name, family=family(name), combo=cb, hi_trades=int(hi.sum()),
                                     hi_trades_blk_ge5=int((nlow[hi] >= 5).sum()), hi_trades_blk_ge10=int((nlow[hi] >= 10).sum()),
                                     hi_trades_blk_ge20=int((nlow[hi] >= 20).sum()),
                                     hi_trades_mean_blk_low=float(nlow[hi].mean()) if hi.any() else np.nan,
                                     lo_trades=int((~hi).sum()),
                                     low_blocked_total=int(((btf <= 1) & ~btie.astype(bool)).sum()) if len(be) else 0,
                                     low_blocked_by_hi=int(((btf <= 1) & (bheld >= 2) & ~btie.astype(bool)).sum()) if len(be) else 0,
                                     low_blocked_by_hi_meanR=float(bR[(btf <= 1) & (bheld >= 2)].mean()) if len(be) and ((btf <= 1) & (bheld >= 2)).any() else np.nan,
                                     hi_held_hours=float(hold[hi].sum() / 60), all_held_hours=float(hold.sum() / 60)))
            if len(be):
                for ht in range(4):
                    for bt in range(4):
                        mm = (bheld == ht) & (btf == bt)
                        if mm.any():
                            mat_rows.append(dict(strategy=name, family=family(name), combo=cb, held_tf=ht, blocked_tf=bt,
                                                 n=int(mm.sum()), sumR=float(bR[mm].sum())))
    per = pd.DataFrame(rows)
    os.makedirs(out_dir, exist_ok=True)
    per.to_csv(os.path.join(out_dir, "per_strategy.csv"), index=False)
    pd.DataFrame(blk_rows).to_csv(os.path.join(out_dir, "blocking_long.csv"), index=False)
    pd.DataFrame(mat_rows).to_csv(os.path.join(out_dir, "blocked_matrix.csv"), index=False)

    # pooled per group with week-cluster bootstrap
    rng = np.random.default_rng(7)
    groups = {"core36": lambda f: f == "core", "ds44": lambda f: f != "core"}
    for fam in sorted({family(n) for n, _ in wk if family(n) != "core"}):
        groups["ds_" + fam] = (lambda ff: (lambda f: f == ff))(fam)
    combos = sorted({cb for _, cb in wk})
    BW = rng.integers(0, nweek, size=(NB, nweek))
    agg = {}
    for gname, sel in groups.items():
        for cb in combos:
            keys = [(n, c) for (n, c) in wk if c == cb and sel(family(n))]
            if not keys:
                continue
            sR = sum(wk[k][0] for k in keys)
            sn = sum(wk[k][1] for k in keys)
            agg[(gname, cb)] = (sR, sn, len(keys))
    prow = []
    for (gname, cb), (sR, sn, k) in agg.items():
        bs = sR[BW].sum(1) / np.maximum(sn[BW].sum(1), 1)
        sub = per[(per["combo"] == cb) & (per["family"].map(groups[gname]))]
        a = sub[sub["period"] == "all"]
        row = dict(group=gname, combo=cb, strategies=k, trades=int(sn.sum()), meanR=float(sR.sum() / sn.sum()),
                   ci_lo=float(np.percentile(bs, 2.5)), ci_hi=float(np.percentile(bs, 97.5)))
        for p in ("IS", "CF"):
            s2 = sub[sub["period"] == p]
            row[f"meanR_{p}"] = float(s2["sumR"].sum() / max(s2["trades"].sum(), 1))
        tot_sig = a["signals"].sum()
        row.update(
            trades_per_day_per_trader=float(a["trades_per_day"].mean()),
            signals_per_day_per_trader=float(a["signals_per_day"].mean()),
            win=float((a["win"] * a["trades"]).sum() / a["trades"].sum()),
            mean_gross=float((a["mean_gross"] * a["trades"]).sum() / a["trades"].sum()),
            mean_cost=float((a["mean_cost"] * a["trades"]).sum() / a["trades"].sum()),
            taken_alone_meanR=float((a["taken_alone_meanR"] * a["trades"]).sum() / a["trades"].sum()),
            blocked_share=float(a["blocked_busy"].sum() / tot_sig), tie_share=float(a["blocked_tie"].sum() / tot_sig),
            blocked_meanR=float(a["blocked_sumR"].sum() / max((a["blocked_busy"] + a["blocked_tie"]).sum(), 1)),
            switches_per_day=float(a["switches"].sum() / len(a) / days["all"]),
            switch_cost_R=float(np.nansum(a["switch_cost_R"] * a["switches"]) / max(a["switches"].sum(), 1)) if a["switches"].sum() else np.nan,
            median_maxdd_R=float(a["maxdd_R"].median()), median_maxdd_pct_2pct=float(a["maxdd_pct_2pct"].median()),
            hold_h_mean=float((a["hold_h_mean"] * a["trades"]).sum() / a["trades"].sum()),
            median_hold_h_median=float(a["hold_h_median"].median()),
            calls_entry_free_per_day=float(a["calls_entry_free_per_day"].mean()),
            calls_entry_all_per_day=float(a["calls_entry_all_per_day"].mean()),
            calls_hold_tfbar_per_day=float(a["calls_hold_tfbar_per_day"].mean()),
            calls_hold_30m_per_day=float(a["calls_hold_30m_per_day"].mean()),
            strategies_meanR_pos=int((a["meanR"] > 0).sum()),
            strategies_pos_IS_and_CF=int(sum(1 for s in a["strategy"]
                                             if (sub[(sub.strategy == s) & (sub.period == "IS")]["meanR"].iloc[0] > 0)
                                             and (sub[(sub.strategy == s) & (sub.period == "CF")]["meanR"].iloc[0] > 0))),
        )
        prow.append(row)
    pooled = pd.DataFrame(prow).sort_values(["group", "combo"])
    pooled.to_csv(os.path.join(out_dir, "pooled.csv"), index=False)

    # paired differences (same weeks resampled)
    pairs = [("ALL|FC", "A|FC"), ("ALL|LTF", "A|FC"), ("ALL|SWH", "A|FC"), ("ALL|SW", "A|FC"), ("A|SW", "A|FC"),
             ("A|SWH", "A|FC"), ("ALL|SWH", "ALL|FC"), ("ALL|SW", "ALL|FC"), ("HI|FC", "A|FC"), ("ALLINF|FC", "ALL|FC"),
             ("T30|FC", "T15|FC"), ("T1h|FC", "T15|FC"), ("T4h|FC", "T15|FC"), ("A|FC", "T15|FC"), ("ALL|LTF", "ALL|FC")]
    drow = []
    for gname in ("core36", "ds44"):
        for a_, b_ in pairs:
            if (gname, a_) not in agg or (gname, b_) not in agg:
                continue
            sa, na, _ = agg[(gname, a_)]
            sb, nb, _ = agg[(gname, b_)]
            ba = sa[BW].sum(1) / np.maximum(na[BW].sum(1), 1)
            bb = sb[BW].sum(1) / np.maximum(nb[BW].sum(1), 1)
            dif = ba - bb
            sub_a = per[(per.combo == a_) & (per.period == "all") & per.family.map(groups[gname])].set_index("strategy")["meanR"]
            sub_b = per[(per.combo == b_) & (per.period == "all") & per.family.map(groups[gname])].set_index("strategy")["meanR"]
            j = sub_a.index.intersection(sub_b.index)
            dd = (sub_a[j] - sub_b[j])
            drow.append(dict(group=gname, a=a_, b=b_, diff=float(sa.sum() / na.sum() - sb.sum() / nb.sum()),
                             ci_lo=float(np.percentile(dif, 2.5)), ci_hi=float(np.percentile(dif, 97.5)),
                             p_a_le_b=float((dif <= 0).mean()), strategies=len(j), strategies_a_better=int((dd > 0).sum())))
    pd.DataFrame(drow).to_csv(os.path.join(out_dir, "paired.csv"), index=False)
    print(pooled[pooled.group.isin(["core36", "ds44"])].to_string())
    print(pd.DataFrame(drow).to_string())


if __name__ == "__main__":
    main(*sys.argv[1:4])
