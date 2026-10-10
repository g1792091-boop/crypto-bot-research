"""Reference diagnostic (not pre-registered, after the results): every bar, both sides, no strategy (stored outcome
tables, the run's costs, the normal leverage group). The baseline a signal has to beat.

    python research/fullgrid/diag/uncond.py WORKROOT

Output: WORKROOT/fgwork/ana/uncond.json, per timeframe "exit|period|side": [n, sum of P&L / equity].
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
EXITS = [e[0] for e in R.K.EXITS]
EX = {en: EXITS.index(en) for en in ("ladder|2", "tp3R|4", "tp3R|2", "ladder|4")}
NAMES = ("sel", "test", "2020")


def main() -> None:
    out = {}
    for tf in ("4h", "1h", "30m", "15m"):
        acc = {f"{en}|{p}|{s}": [0, 0.0] for en in EX for p in (0, 1, 2) for s in (0, 1)}
        for sym in R.SYMBOLS:
            tab = R.outcome_table(WORK, sym, tf, False)
            _df, close = R.frame(DATA, sym, tf)
            pid = R.period_ids(close)
            for en, e in EX.items():
                P = tab["pnl_normal"][e]
                for s in (0, 1):
                    for p in (0, 1, 2):
                        m = np.isfinite(P[:, s]) & (pid == p)
                        a = acc[f"{en}|{p}|{s}"]
                        a[0] += int(m.sum())
                        a[1] += float(P[m, s].sum())
        out[tf] = acc
        for en in EX:
            parts = []
            for p in (0, 1, 2):
                lo, sh = acc[f"{en}|{p}|0"], acc[f"{en}|{p}|1"]
                parts.append(f"{NAMES[p]}: long {lo[1] / max(lo[0], 1) * 100:+.3f}% "
                             f"short {sh[1] / max(sh[0], 1) * 100:+.3f}% (n {lo[0]})")
            print(tf, en, " ".join(parts), flush=True)
    json.dump(out, open(os.path.join(WORK, "ana", "uncond.json"), "w"))


if __name__ == "__main__":
    main()
