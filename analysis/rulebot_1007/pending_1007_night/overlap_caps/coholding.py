"""Trader-level overlap from the UNCAPPED joint run (23 traders, CARD scope, setup B) + simultaneous 'wants'.

    python3 -I -B coholding.py <sig23.npz> <out_dir> [scope]

  entry_coheld[A,B] = share of A's entries made while B holds (or enters at the same 15m bar) the same coin and side
                      = the share of A's entries a 1-per-cluster-per-coin-side cap would block if A and B shared a
                      cluster and B were always first. Chance: B's position intervals shifted by +-7 days.
  time_coheld[A,B]  = share of A's position time (15m bars) during which B holds the same coin-side.
  trader daily R corr = Pearson correlation of the traders' daily net R (by exit day), and of gross R.
  wants: per 15m bar and coin-side, how many traders have a scope signal (raw, busy or not) and how many FREE
         traders pick that coin-side as first choice in the uncapped run.
"""
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', os.path.dirname(os.path.abspath(__file__))]
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import common5 as C  # noqa: E402
import capsim as S  # noqa: E402

SHIFT = 672


def main(path, out, scope_name="CARD"):
    os.makedirs(out, exist_ok=True)
    scope = C.CARD if scope_name == "CARD" else C.U
    tr = C.ALL
    t, ts15 = S.prep(path, tr, scope)
    tk, bl, it = S.run(t, ts15, len(tr))
    nb = len(ts15)
    r = tk[:, 0]
    TID = t.tid.to_numpy()[r]; E = t.e.to_numpy()[r]; X = t.x.to_numpy()[r]
    CS = t.coin.to_numpy()[r].astype(np.int64) * 2 + (t.side.to_numpy()[r] > 0)
    R = t.R.to_numpy()[r]; G = t.g.to_numpy()[r]
    nt = len(tr)
    # occupancy bitmaps per trader: held coin-side code per 15m bar (-1 flat)
    occ = np.full((nt, nb + 2 * SHIFT + 2), -1, np.int8)
    for k in range(nt):
        m = TID == k
        for e, x, cs in zip(E[m], X[m], CS[m]):
            occ[k, SHIFT + e:SHIFT + x + 1] = cs
    ent = np.zeros((nt, nt)); ent_ch = np.zeros((nt, nt)); tim = np.zeros((nt, nt))
    for a in range(nt):
        ma = TID == a
        ea, ca = E[ma] + SHIFT, CS[ma]
        held_a = occ[a] >= 0
        for b in range(nt):
            if a == b:
                continue
            ent[a, b] = np.mean(occ[b, ea] == ca)
            ent_ch[a, b] = 0.5 * (np.mean(occ[b, ea - SHIFT] == ca) + np.mean(occ[b, ea + SHIFT] == ca))
            tim[a, b] = np.mean(occ[b][held_a] == occ[a][held_a])
    pd.DataFrame(ent, index=tr, columns=tr).to_csv(os.path.join(out, f"entry_coheld_{scope_name}.csv"), float_format="%.4f")
    pd.DataFrame(ent_ch, index=tr, columns=tr).to_csv(os.path.join(out, f"entry_coheld_chance_{scope_name}.csv"), float_format="%.4f")
    pd.DataFrame(tim, index=tr, columns=tr).to_csv(os.path.join(out, f"time_coheld_{scope_name}.csv"), float_format="%.4f")
    # trader daily R
    T0 = S.T0
    ND = int((pd.Timestamp("2026-09-30").value - T0) // S.DAYNS)
    xd = np.clip(((ts15[X] - T0) // S.DAYNS).astype(int), 0, ND - 1)
    dR = {s: np.bincount(xd[TID == k], weights=R[TID == k], minlength=ND) for k, s in enumerate(tr)}
    dG = {s: np.bincount(xd[TID == k], weights=G[TID == k], minlength=ND) for k, s in enumerate(tr)}
    pd.DataFrame(dR).corr().to_csv(os.path.join(out, f"trader_daily_R_corr_{scope_name}.csv"), float_format="%.3f")
    pd.DataFrame(dG).corr().to_csv(os.path.join(out, f"trader_daily_gross_corr_{scope_name}.csv"), float_format="%.3f")
    # wants
    tt = t
    key = tt.e.to_numpy().astype(np.int64) * 12 + tt.coin.to_numpy().astype(np.int64) * 2 + (tt.side.to_numpy() > 0)
    u = pd.DataFrame({"key": key, "tid": tt.tid.to_numpy()}).drop_duplicates()
    raw = u.groupby("key").tid.nunique()
    # 1h window version
    key1h = (tt.e.to_numpy().astype(np.int64) // 4) * 12 + tt.coin.to_numpy().astype(np.int64) * 2 + (tt.side.to_numpy() > 0)
    raw1h = pd.DataFrame({"key": key1h, "tid": tt.tid.to_numpy()}).drop_duplicates().groupby("key").tid.nunique()
    # free first-choice wants in the uncapped run (= the taken rows, since uncapped)
    fk = E.astype(np.int64) * 12 + CS
    free = pd.Series(fk).value_counts()
    fk1h = (E.astype(np.int64) // 4) * 12 + CS
    free1h = pd.Series(fk1h).value_counts()
    years = ND / 365.25
    w = {}
    for lab, ser in (("raw_signal_same15m", raw), ("raw_signal_same1h", raw1h), ("free_entry_same15m", free),
                     ("free_entry_same1h", free1h)):
        w[lab] = {f">={k}": dict(events=int((ser >= k).sum()), per_year=round(float((ser >= k).sum()) / years, 1))
                  for k in (2, 3, 4, 5, 6, 8)}
        w[lab]["max"] = int(ser.max())
    # concurrent holdings per coin-side in the uncapped run
    ex = S.exposure(t, tk, nb)
    live = slice(int(np.searchsorted(ts15, T0)), nb)
    csmax = ex["csmax"][live]
    hold = {f">={k}": round(float((csmax >= k).mean()), 4) for k in (2, 3, 4, 5, 6, 8)}
    # episodes of >=5 on one coin-side: count starts
    b5 = (csmax >= 5).astype(np.int8)
    hold["episodes_>=5"] = int(((np.diff(np.r_[0, b5])) == 1).sum())
    hold["episodes_>=5_per_year"] = round(hold["episodes_>=5"] / years, 1)
    hold["max"] = int(csmax.max())
    L, Sh = ex["long"][live], ex["short"][live]
    expo = dict(long_max=int(L.max()), short_max=int(Sh.max()),
                long_p99=float(np.quantile(L, .99)), short_p99=float(np.quantile(Sh, .99)),
                long_p50=float(np.median(L)), short_p50=float(np.median(Sh)),
                share_ge8_same_dir=round(float(((L >= 8) | (Sh >= 8)).mean()), 4),
                share_ge10_same_dir=round(float(((L >= 10) | (Sh >= 10)).mean()), 4))
    json.dump(dict(wants=w, coin_side_holding_share=hold, same_dir_exposure=expo, years=years, n_traders=nt,
                   scope=scope_name), open(os.path.join(out, f"wants_{scope_name}.json"), "w"), indent=1)
    print(json.dumps(dict(wants=w, hold=hold, expo=expo), indent=0)[:3000])


import json  # noqa: E402

if __name__ == "__main__":
    main(*sys.argv[1:4])
