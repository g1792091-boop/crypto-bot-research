"""Reference diagnostic (not pre-registered, after the results): at the same signal entries, the chosen side vs the
opposite side (stored outcome tables, the run's costs). Default numbers, core 36 x 4 timeframes, exits ladder|2 and
tp3R|4. Direction skill = (chosen - opposite) / 2.

    python research/fullgrid/diag/side_skill.py WORKROOT

Output: WORKROOT/fgwork/ana/side_skill.json, per cell "exit|period": [n, sum chosen, sum opposite, long n,
trades with chosen > opposite].
"""

import json
import os
import sys

FG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)

import numpy as np  # noqa: E402

import run as R  # noqa: E402

SP = sys.argv[1]
WORK = os.path.join(SP, "fgwork")
DATA = os.path.join(SP, "fg1m")
R.FRAME_DIR[0] = os.path.join(WORK, "frames")
EX = {"ladder|2": 0, "tp3R|4": [e[0] for e in R.K.EXITS].index("tp3R|4")}


def job(it):
    name, tf = it
    combo = R.default_combo("core", name)
    acc = {f"{en}|{p}": [0, 0.0, 0.0, 0, 0] for en in EX for p in (0, 1, 2)}
    for sym in R.SYMBOLS:
        P_all = R.trade_table(DATA, WORK, "core", name, sym, tf)
        _df, close = R.frame(DATA, sym, tf)
        pid = R.period_ids(close)
        lo, sh = R.signals(DATA, "core", name, sym, tf, combo)
        for en, e in EX.items():
            P = P_all[e]
            for mask, s in ((np.asarray(lo, bool), 0), (np.asarray(sh, bool), 1)):
                idx = np.flatnonzero(mask)
                ch, op = P[idx, s], P[idx, 1 - s]
                ok = np.isfinite(ch) & np.isfinite(op)
                for p in (0, 1, 2):
                    m = ok & (pid[idx] == p)
                    a = acc[f"{en}|{p}"]
                    a[0] += int(m.sum())
                    a[1] += float(ch[m].sum())
                    a[2] += float(op[m].sum())
                    a[3] += int(m.sum()) if s == 0 else 0
                    a[4] += int((ch[m] > op[m]).sum())
    return name, tf, acc


if __name__ == "__main__":
    res = []
    items = [(n, tf) for tf in ("4h", "1h", "30m", "15m") for n in R.core_names()]
    for name, tf, acc in R.run_pool(job, items, 1, "side"):
        res.append({"name": name, "tf": tf, "acc": acc})
        print(name, tf, flush=True)
        json.dump(res, open(os.path.join(WORK, "ana", "side_skill.part.json"), "w"))
    json.dump(res, open(os.path.join(WORK, "ana", "side_skill.json"), "w"))
    print("done", flush=True)
