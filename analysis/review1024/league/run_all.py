"""One command for the whole league review: analysis -> engine check -> five-year check -> report.

    cd analysis/review1024/league
    python3 run_all.py --zip LEAGUE_EXPORT.zip --work NEW_EMPTY_DIR [--rulebot-zip PAPERBOT_EXPORT.zip] [--prev-zip OLDER_LEAGUE_EXPORT.zip]
                       [--fg1m FIVE_YEAR_1M_DIR] [--market-cache DIR] [--skip-fivey]

- The zips are untrusted data: unpacked only into NEW_EMPTY_DIR (lg_lib.safe_extract checks every name), nothing from them runs,
  the sqlite files are opened read-only. Run this from this folder WITHOUT python -I (pandas needs the site packages here).
- --fg1m: research/fullgrid/data.py's DATA/1m folder (SYMBOL.npz, 2020-01 .. 2026-09). Without it the engine check and the
  five-year check are skipped and the report says so.
- Outputs: REPORT_KO.md, APPENDIX_ACCOUNTS_KO.md, daily_pnl.csv, trades_norm.csv (this folder) and out/ (numbers).
  DeepSeek five-year money stays in NEW_EMPTY_DIR/fivey/fivey_private.json (outside the repository, owners' rule D11).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(args: list) -> None:
    print("$", " ".join(args), flush=True)
    subprocess.run([sys.executable] + args, cwd=HERE, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--rulebot-zip")
    ap.add_argument("--prev-zip")
    ap.add_argument("--fg1m")
    ap.add_argument("--market-cache")
    ap.add_argument("--skip-fivey", action="store_true")
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    if os.path.exists(work) and os.listdir(work):
        raise SystemExit(f"--work 는 새 빈 폴더여야 합니다: {work}")
    os.makedirs(work, exist_ok=True)
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    cmd = ["analyze.py", "--zip", os.path.abspath(a.zip), "--work", work, "--out", out, "--exports", HERE,
           "--market-cache", os.path.abspath(a.market_cache) if a.market_cache else os.path.join(work, "market")]
    if a.rulebot_zip:
        cmd += ["--rulebot-zip", os.path.abspath(a.rulebot_zip)]
    if a.prev_zip:
        cmd += ["--prev-zip", os.path.abspath(a.prev_zip)]
    run(cmd)
    for f in ("fivey.json", "engine_check.json"):                 # never keep a stale five-year result next to new numbers
        p = os.path.join(out, f)
        if os.path.exists(p):
            os.remove(p)
    if a.fg1m and not a.skip_fivey:
        res = json.load(open(os.path.join(out, "results.json"), encoding="utf-8"))
        good = list(res.get("good", []))
        accts = list(good)
        for g in good:
            pick = g.rsplit("-", 1)[0]
            for sfx in ("ld", "ldc"):
                if f"{pick}-{sfx}" not in accts:
                    accts.append(f"{pick}-{sfx}")
        lg = os.path.join(work, "league")
        if accts:
            extra = []
            if good:
                pick = good[0].rsplit("-", 1)[0]
                extra = [f"{pick}-{s}" for s in ("fq", "fqc", "e") if f"{pick}-{s}" not in accts]
            run(["engine_check.py", "--data", os.path.abspath(a.fg1m),
                 "--market-cache", os.path.abspath(a.market_cache) if a.market_cache else os.path.join(work, "market"),
                 "--league-db", os.path.join(lg, "db", "league_exits.db"), "--cands", os.path.join(lg, "etc", "candidates.json"),
                 "--rules", os.path.join(lg, "etc", "rules.json"), "--accounts", ",".join(accts + extra),
                 "--work", os.path.join(work, "echeck"), "--out", os.path.join(out, "engine_check.json")])
            run(["fivey.py", "--results", os.path.join(out, "results.json"), "--cands", os.path.join(lg, "etc", "candidates.json"),
                 "--rules", os.path.join(lg, "etc", "rules.json"), "--data", os.path.abspath(a.fg1m), "--work", os.path.join(work, "fivey"),
                 "--accounts", ",".join(accts), "--out", os.path.join(out, "fivey.json")])
    run(["report.py", "--out", out, "--dest", HERE])
    return 0


if __name__ == "__main__":
    sys.exit(main())
