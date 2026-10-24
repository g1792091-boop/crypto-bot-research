#!/usr/bin/env python3
"""Regenerate everything in analysis/review1024/other/ from the uploaded zips.

    python3 run_all.py --demo <demo_export_..._1.zip> <demo_export_..._2.zip> \
        --old-demo <10/17 demo _1.zip> <10/17 demo _2.zip> --extra <extra_export_....zip> \
        --work <NEW empty scratch folder> [--out <this folder>/csv]

The zips are untrusted: each is unpacked (data files only) into its own new folder under --work, nothing from them is
executed, and the databases are opened read-only. Writes the CSVs into --out and daily_pnl.csv next to this script;
the console output holds the numbers REPORT_KO.md quotes (save it with `| tee`).
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(*args):
    print("\n$", " ".join(os.path.basename(a) if a.endswith(".py") else a for a in args), flush=True)
    subprocess.run([sys.executable, *args], check=True, cwd=HERE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", nargs=2, required=True)
    ap.add_argument("--old-demo", nargs=2)
    ap.add_argument("--extra", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "csv"))
    a = ap.parse_args(argv)
    if os.path.exists(a.work) and os.listdir(a.work):
        sys.exit(f"--work {a.work} must be a new empty folder")
    ex = os.path.join(HERE, "extract_zip.py")
    d_new, d_old, d_ex = (os.path.join(a.work, x) for x in ("demo_new", "demo_old", "extra"))
    run(ex, a.demo[0], d_new)
    run(ex, "--allow-nonempty", a.demo[1], d_new)
    if a.old_demo:
        run(ex, a.old_demo[0], d_old)
        run(ex, "--allow-nonempty", a.old_demo[1], d_old)
    run(ex, a.extra, d_ex)
    full_db = os.path.join(d_ex, "db", "demobot", "demo.db")
    small_db = os.path.join(d_new, "db", "demo_small.db")
    demo_args = ["demo_review.py", "--snap", os.path.join(d_new, "snap"), "--db", full_db if os.path.exists(full_db) else small_db,
                 "--small-db", small_db, "--out", a.out]
    if a.old_demo:
        demo_args += ["--old-snap", os.path.join(d_old, "snap"), "--old-db", os.path.join(d_old, "db", "demo_small.db")]
    run(*demo_args)
    root = os.path.join(d_ex, "db", "paperbot")
    run("live_review.py", "--db-root", root, "--out", a.out)
    run("shadows_review.py", "--db-root", root, "--out", a.out,
        "--paramshadow-last", os.path.join(d_new, "paramshadow", "last.json"))
    run("agents_review.py", "--db-root", root, "--out", a.out)
    rows = []
    for part in ("daily_pnl_demo.csv", "daily_pnl_live.csv"):
        p = os.path.join(a.out, part)
        if os.path.exists(p):
            rows += list(csv.DictReader(open(p, encoding="utf-8")))
    with open(os.path.join(HERE, "daily_pnl.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bot", "account_id", "day_kst", "pnl", "trades"])
        w.writeheader()
        w.writerows(rows)
    print(f"\ndaily_pnl.csv: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
