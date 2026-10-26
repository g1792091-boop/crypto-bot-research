#!/usr/bin/env python3
"""추세판단 봇: every arm of PREREG.md through trend_sim.py (the copied 7/1-10/20 replay), in both entry modes, then the
same metrics as the other bots on the months the replay covers (KST 2026-07, 08, 09 = inside the check period; 2026-10
(1-20) = recent). There is no choose period, so there is no verdict (PREREG.md section 3).

    python3 -I trend.py ROOT OUT_DIR [--skip-runs]
ROOT: the replay's scratch folder (research/trendbot/recent/download.sh + parse.py -> ROOT/cache). At most two replays
run at once. Writes OUT_DIR/trend.json and OUT_DIR/trend_trades_<mode>_<arm>.csv.gz."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otcommon as CM  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(CM.REPO, "research", "trendbot", "fiveyear", "code", "combo.trend.1021.json")   # = b270569's
SIGNALS = os.path.join(CM.REPO, "research", "trendbot", "recent", "signals.csv.gz")
WIN = (CM.kst_ms("2026-07-01 00:00"), CM.kst_ms("2026-10-21 00:00"))
MODES = {"now": ["--entry", "now"], "pullback": []}
MONTHS = {"check_part (2026-07..09)": ["2026-07", "2026-08", "2026-09"], "recent (2026-10, 1-20)": ["2026-10"]}


def runs(root: str) -> None:
    jobs = [(m, a) for m in MODES for a in CM.ARMS]
    procs = []
    for mode, arm in jobs:
        while len([p for p in procs if p.poll() is None]) >= 2:
            time.sleep(2)
        log = open(os.path.join(root, f"opentime_{mode}_{arm}.log"), "w")
        cmd = [sys.executable, "-I", os.path.join(HERE, "trend_sim.py"), root, f"{mode}_{arm}", "--config", CONFIG,
               "--signals", SIGNALS, "--arm", arm] + MODES[mode]
        procs.append(subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT))
    for p in procs:
        if p.wait() != 0:
            raise SystemExit(f"a replay failed: {p.args}")


def trades(root: str, mode: str, arm: str) -> pd.DataFrame:
    T = pd.read_csv(os.path.join(root, "out", "recent", f"{mode}_{arm}_trades.csv"))
    T = T[(T.entry_time >= WIN[0]) & (T.entry_time < WIN[1])].reset_index(drop=True)
    locked = T["lock"].notna()
    return pd.DataFrame({"t": T.entry_time.astype(np.int64), "symbol": T.symbol, "member": T.label, "side": T.side,
                         "reason": T.reason, "roe": T.roe, "ret": 0.4 * T.roe, "exit_ts": T.exit_time,
                         "touched": T.touched.astype(bool), "locked": locked,
                         "kind": np.where(locked, "LOCKED", np.where(T.reason == "SL", "SL", "OTHER")),
                         "open_at_M": T.first_m >= 0, "roe_at_M": T.roe_at_M, "R_at_M": T.R_at_M,
                         "hours_at_M": T.hours_at_M, "mfe_share_at_M": T.mfe_share_at_M,
                         "open_4h": T.open_4h.astype(bool), "open_8h": T.open_8h.astype(bool),
                         "open_12h": T.open_12h.astype(bool), "sl_in_window": T.sl_in_window.astype(bool),
                         "held_in_window": T.held_in_window, "held_bars": T.held_bars})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--skip-runs", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    if not a.skip_runs:
        runs(a.root)
    out = {"bot": "추세판단 봇 -> Bybit (7/1-10/20 replay, 10/21 members, exits as live)", "modes": {}}
    for mode in MODES:
        res = {}
        for arm in CM.ARMS:
            T = trades(a.root, mode, arm)
            T.to_csv(os.path.join(a.out, f"trend_trades_{mode}_{arm}.csv.gz"), index=False)
            res[arm] = {k: CM.month_metrics(T, v) for k, v in MONTHS.items()}
            if arm == "A0":
                A0 = T
            print(mode, arm, {k: (d["trades"], round(d["median_month"], 4), round(d["log_growth"], 3))
                              for k, d in res[arm].items()}, flush=True)
        whole = {arm: CM.month_metrics(trades(a.root, mode, arm), MONTHS["check_part (2026-07..09)"] + ["2026-10"])
                 for arm in CM.ARMS}
        out["modes"][mode] = {"arms": res, "window_all": whole,
                              "diagnostics_A0": {"window": CM.by_period_diag(A0)["all"]},
                              "sideways_A0": {"window": CM.sideways(A0)}}
    out["verdict"] = "none: no choose period (PREREG.md section 3)"
    json.dump(CM.jsonable(out), open(os.path.join(a.out, "trend.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
