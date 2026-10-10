"""Reference diagnostic (not pre-registered, after the results): the best core picks of the test period (top 3 per
timeframe by test mean, plus the 3 lowest test p). Per pick and its cell's default numbers (live exit): per-signal
win rate, average win / loss and payoff by period; the test-period account (live sizing, one position at a time,
compounding); and the chosen side vs the opposite side at the same entries.

    python research/fullgrid/diag/top_picks.py WORKROOT [RESULTS_BRANCH_DIR]

Output: WORKROOT/fgwork/ana/top_picks.json. Chosen after seeing the test period, so the figures flatter the picks.
"""

import csv
import json
import os
import sys

FG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)

import numpy as np  # noqa: E402

import kernel as K  # noqa: E402
import run as R  # noqa: E402
import sizing as SZ  # noqa: E402

SP = sys.argv[1]
WORK = os.path.join(SP, "fgwork")
DATA = os.path.join(SP, "fg1m")
RES = os.path.join(SP, "fgresults", sys.argv[2] if len(sys.argv) > 2 else "fullgrid-results-20261010-1602")
R.FRAME_DIR[0] = os.path.join(WORK, "frames")
EXITS = [e[0] for e in R.K.EXITS]
PERIODS = (("select", 0), ("test", 1), ("extra", 2))


def stats(x: np.ndarray) -> dict | None:
    x = x[np.isfinite(x)]
    if not len(x):
        return None
    w, lo = x[x > 0], x[x <= 0]
    return {"n": int(len(x)), "mean": float(x.mean()), "win": float(len(w) / len(x)),
            "avg_win": float(w.mean()) if len(w) else 0.0, "avg_loss": float(lo.mean()) if len(lo) else 0.0,
            "payoff": float(w.mean() / -lo.mean()) if len(w) and len(lo) and lo.mean() < 0 else None}


def chosen_vs_opposite(name: str, tf: str, combo: dict, e: int) -> dict:
    acc = {p: [0, 0.0, 0.0] for _n, p in PERIODS}
    for sym in R.SYMBOLS:
        P = R.trade_table(DATA, WORK, "core", name, sym, tf)[e]
        _d, close = R.frame(DATA, sym, tf)
        pid = R.period_ids(close)
        lo, sh = R.signals(DATA, "core", name, sym, tf, combo)
        for mask, s in ((np.asarray(lo, bool), 0), (np.asarray(sh, bool), 1)):
            idx = np.flatnonzero(mask)
            ch, op = P[idx, s], P[idx, 1 - s]
            ok = np.isfinite(ch) & np.isfinite(op)
            for _n, p in PERIODS:
                m = ok & (pid[idx] == p)
                acc[p][0] += int(m.sum())
                acc[p][1] += float(ch[m].sum())
                acc[p][2] += float(op[m].sum())
    return acc


def main() -> None:
    ex = R.exchange(os.path.join(FG, "exchange.json"), False)
    rows = [r for r in csv.DictReader(open(os.path.join(RES, "candidates.csv")))
            if r["kind"] == "core" and r["test_n"] and int(r["test_n"]) >= 100]
    pick = {}
    for tf in ("15m", "30m", "1h", "4h"):
        for r in sorted([r for r in rows if r["tf"] == tf], key=lambda r: -float(r["test_mean"]))[:3]:
            pick[(r["name"], tf, r["rank"])] = r
    for r in sorted(rows, key=lambda r: float(r["test_p"]))[:3]:
        pick[(r["name"], r["tf"], r["rank"])] = r
    lo, hi = R.PERIOD_MS[R.P_TEST][1], R.PERIOD_MS[R.P_TEST][2]
    S = K.settings_vector()
    out = []
    for (name, tf, rank), r in pick.items():
        combo = {k: (tuple(v) if isinstance(v, list) else v) for k, v in json.loads(r["combo"]).items()}
        e = EXITS.index(r["exit"])
        Ts = R.cell_trades(DATA, WORK, "core", name, tf, [(combo, e), (R.default_combo("core", name), 0)])
        rec = {"name": name, "tf": tf, "rank": rank, "exit": r["exit"], "combo": r["combo"],
               "test_p": float(r["test_p"]), "side": chosen_vs_opposite(name, tf, combo, e)}
        for lab, T, ee in (("pick", Ts[0], e), ("default", Ts[1], 0)):
            rec[lab] = {pn: stats(T["x"][T["pid"] == k]) for pn, k in PERIODS}
            a = SZ.account_trades(DATA, T, ex, lo, hi, ee, S)
            rec[lab]["account_test"] = {k: a[k] for k in ("final_x", "max_dd", "bust", "trades", "liquidations")}
        out.append(rec)
        print(name, tf, rank, r["exit"], rec["pick"]["account_test"], flush=True)
    json.dump(out, open(os.path.join(WORK, "ana", "top_picks.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
