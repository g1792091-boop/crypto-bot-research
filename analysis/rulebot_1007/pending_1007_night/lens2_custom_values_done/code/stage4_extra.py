"""Extra descriptives: (1) trades per week of a one-position trader (default values, one position across the six
coins, every-signal stream thinned greedily) per cell; (2) what the naive search picks (composition by dimension).
Output ../out/one_position.csv, ../out/pick_composition.csv."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cvlib as C  # noqa: E402
import stage2 as S2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

METRIC = os.environ.get("CV_METRIC", "R")
WF = os.path.join(C.WORK, "work", "wf" if METRIC == "R" else "wf_" + METRIC)
OUT = os.path.join(C.WORK, "out" if METRIC == "R" else "out_" + METRIC)


def one_position(cell):
    z = np.load(os.path.join(C.WORK, "work", "cells", cell + ".npz"))
    tf = cell.rsplit("_", 1)[1]
    tfns = C.TF_MIN[tf] * 60 * 10**9
    j = 3   # stop 2.0, house
    keep = z["pmask"][:, 0] & z["done"][:, j]
    ts, ec, rn = z["ts"][keep], z["exit_close"][keep, j], z["rnet"][keep, j]
    lo = S2.WEEK0 + S2.T0 * S2.NS_WEEK
    hi = S2.WEEK0 + S2.NWEEK * S2.NS_WEEK
    free = -1
    taken = []
    for i in range(len(ts)):
        if ts[i] < lo or ts[i] >= hi:
            continue
        if ts[i] + tfns >= free:
            taken.append(i)
            free = ec[i]
    weeks = (hi - lo) / S2.NS_WEEK
    tk = np.array(taken, int)
    return dict(cell=cell, one_pos_trades=len(tk), one_pos_trades_per_week=round(len(tk) / weeks, 2),
                one_pos_mean_R=round(float(np.mean(rn[tk])), 4) if len(tk) else None,
                all_signal_trades_per_week=round(int(((ts >= lo) & (ts < hi)).sum()) / weeks, 1))


def composition():
    rows = []
    cells = [f"{s}_{tf}" for s in C.STRATS for tf in C.TFS]
    for c in cells:
        z = np.load(os.path.join(WF, c + ".npz"))
        keys = list(z["sel_keys"])
        for k in keys:
            if not k.endswith("|naive"):
                continue
            sel = z["sel"][keys.index(k)].astype(int)
            x = sel % 3
            s = (sel // 3) % 3
            pf = sel // 9
            p, f = pf // 5, pf % 5
            rows.append(dict(cell=c, scheme=k.split("|")[0], share_default=float(np.mean(sel == S2.DEFAULT)),
                             share_P_changed=float(np.mean(p != 0)), share_filter_on=float(np.mean(f != 0)),
                             share_stop_changed=float(np.mean(s != 1)), share_exit_changed=float(np.mean(x != 0)),
                             share_stop25=float(np.mean(s == 2)), share_stop15=float(np.mean(s == 0)),
                             **{f"share_F_{C.FILTERS[i]}": float(np.mean(f == i)) for i in range(1, 5)},
                             **{f"share_X_{C.EXITS[i]}": float(np.mean(x == i)) for i in range(3)},
                             distinct_combos=int(len(np.unique(sel))),
                             changes=int(np.sum(sel[1:] != sel[:-1]))))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    from multiprocessing import Pool
    os.makedirs(OUT, exist_ok=True)
    cells = [f"{s}_{tf}" for s in C.STRATS for tf in C.TFS]
    with Pool(4) as p:
        op = list(p.imap(one_position, cells))
    pd.DataFrame(op).to_csv(os.path.join(OUT, "one_position.csv"), index=False)
    comp = composition()
    comp.to_csv(os.path.join(OUT, "pick_composition.csv"), index=False)
    print(pd.DataFrame(op).to_string())
    print(comp.groupby("scheme")[[c for c in comp.columns if c.startswith("share") or c in ("distinct_combos", "changes")]].mean().round(3).T.to_string())
