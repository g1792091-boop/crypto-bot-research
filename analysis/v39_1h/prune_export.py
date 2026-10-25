#!/usr/bin/env python3
"""Shrink an extracted rule-bot export to what the V3.9 1h study reads (disk is tight), and print its time span.

    python3 -I prune_export.py <extracted_export>

Keeps current/{trades, signal_log, live_bars, accounts, runs, d3_stop_slips}.csv as they are (all trades are needed:
funding rates and order steps are inferred from them), cuts signal_ctx.jsonl and outcomes.csv to the V3.9 rows, writes
the V39_ALL@1h rows of d3_shadows.csv to current/v39_shadows.csv, and deletes the rest (other runs' folders, the full
shadows, alerts, equity, fill costs, reports). Only ever touches the folder it is given (a copy made by
extract_zip.py). Prints "start_ms end_ms first_day last_day" of the live 1m bars (UTC days).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import shutil
import sys

sys.dont_write_bytecode = True


def main(argv) -> int:
    root = argv[0]
    cur = os.path.join(root, "current")
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isdir(p) and name != "current":
            shutil.rmtree(p)
    ids = set()
    with open(os.path.join(cur, "signal_log.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            if r["strategy"] == "V39_ALL":
                ids.add(int(r["id"]))
    p = os.path.join(cur, "signal_ctx.jsonl")
    if os.path.exists(p):
        with open(p) as fh, open(p + ".tmp", "w") as out:
            for line in fh:
                if int(json.loads(line).get("id", -1)) in ids:
                    out.write(line)
        os.replace(p + ".tmp", p)
    for name, col, keep in (("outcomes.csv", "account_id", lambda v: v.startswith("V39_ALL@")),
                            ("d3_shadows.csv", "account_id", lambda v: v == "V39_ALL@1h")):
        p = os.path.join(cur, name)
        if not os.path.exists(p):
            continue
        dest = p + ".tmp" if name == "outcomes.csv" else os.path.join(cur, "v39_shadows.csv")
        with open(p, newline="") as fh, open(dest, "w", newline="") as out:
            rd, w = csv.reader(fh), csv.writer(out)
            h = next(rd)
            w.writerow(h)
            k = h.index(col)
            for r in rd:
                if keep(r[k]):
                    w.writerow(r)
        if name == "outcomes.csv":
            os.replace(dest, p)
        else:
            os.remove(p)
    for name in ("alerts.csv", "equity_hourly.csv", "fill_costs.csv", "d3_reports.csv"):
        p = os.path.join(cur, name)
        if os.path.exists(p):
            os.remove(p)
    lo = hi = None
    with open(os.path.join(cur, "live_bars.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            t = int(r["ts"])
            lo = t if lo is None or t < lo else lo
            hi = t if hi is None or t > hi else hi
    day = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date()  # noqa: E731
    print(lo, hi + 60_000, day(lo), day(hi))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
