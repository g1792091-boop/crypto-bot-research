"""How often a random ~6-day window of the backtest (default numbers, live exit) looks like the live interim.
Per core timeframe: all 36 strategies' per-signal outcomes pooled; rolling windows of W days, step 1 day."""
import json
import os
import sys

FG = "/home/user/crypto-bot-research/research/fullgrid"
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)
import run as R  # noqa: E402

SP = sys.argv[1]  # WORKROOT: fg1m/, fgwork/, fgresults/ of the full grid
WORK, DATA = os.path.join(SP, "fgwork"), os.path.join(SP, "fg1m")
R.FRAME_DIR[0] = os.path.join(WORK, "frames")
cells = [c for c in __import__("csv").DictReader(open(os.path.join(SP, "fgresults/fullgrid-results-20261010-1602/cells.csv")))
         if c["kind"] == "core"]


def job(c):
    T = R.cell_trades(DATA, WORK, "core", c["name"], c["tf"], [(R.default_combo("core", c["name"]), 0)])[0]
    return c["name"], c["tf"], T["close"].tolist(), T["x"].tolist(), T["pid"].tolist(), T["coin"].tolist(), T["side"].tolist()


out = []
for k, r in enumerate(R.run_pool(job, cells, int(sys.argv[2]) if len(sys.argv) > 2 else 4, "win")):
    out.append(r)
    print(k, r[0], r[1], len(r[3]), flush=True)
json.dump(out, open(os.path.join(SP, "interim", "core_default_trades.json"), "w"))
print("done")
