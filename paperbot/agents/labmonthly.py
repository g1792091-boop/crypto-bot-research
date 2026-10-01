"""Monthly re-check on new data ("period 4"): run on the server early each month.

    python -m paperbot.agents.labmonthly run --lab DIR [--agents-db agents3.db] [--through YYYY-MM] [--procs 2]

The five-year lab data ends at 2026-09-29. Each month this job
  1. builds the bars and signals from RECENT_START to the end of the last complete month with the
     research builder itself (research/binance_data/build.py: same archive, checks and gap repair),
     into DIR/recent (downloads shared with the lab build under DIR/_binance/raw; the months before
     P4_START are only warm-up for the indicators);
  2. writes DIR/recent/recheck.json:
     - per strategy and timeframe: the paper v3 outcome of every signal in period 4 (P4_START to the
       end of that month; same calculation as the lab, research/strategy_profiles/profiles.py), next
       to the five-year mean of the strategy profile card;
     - every lab test that passed the gate (read from agents3.db, read-only): the same comparison of
       the tested rule against the current one on period 4 only.
It is descriptive: nothing is decided by it, the gate's verdicts stay as they were, and the agent
tick (the only writer of agents3.db) posts a summary to the rooms when a new month appears.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

RECENT_START = "2025-10-01"   # one year of warm-up before period 4 (the 1d signals need 200 bars)
P4_START = "2026-09-30"       # the five-year data ends at 2026-09-29 (ts < 2026-09-30)
TFS = ("5m", "15m", "30m", "1h", "4h")
REPORT = "recheck.json"


def last_complete_month(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    first = pd.Timestamp(year=now.year, month=now.month, day=1)
    return (first - pd.Timedelta(days=1)).strftime("%Y-%m")


def month_end(month: str) -> str:
    """'2026-10' -> '2026-11-01' (exclusive end)."""
    return (pd.Timestamp(month + "-01") + pd.offsets.MonthBegin(1)).strftime("%Y-%m-%d")


def build_recent(lab: str, through: str, procs: int = 2) -> dict:
    from . import labdata as LD
    end = month_end(through)
    if end <= P4_START:
        raise SystemExit(f"--through {through}: period 4 starts {P4_START}")
    p = LD.paths(lab)
    recent, work = os.path.join(p["main"], "recent"), os.path.join(p["main"], "_recent")
    os.makedirs(recent, exist_ok=True)
    B = LD.load_builder(lab, procs, env={"BINANCE_DIR": work, "BINANCE_SIGNALS": recent,
                                         "BINANCE_REPORTS": os.path.join(work, "reports"),
                                         "BINANCE_RAW": os.path.join(p["work"], "raw"),
                                         "BINANCE_START": RECENT_START, "BINANCE_END": end})
    dl = B.download()
    if dl.get("failed"):
        raise SystemExit(f"download failed for {len(dl['failed'])} files (network?); run the same command again")
    B.assemble(force=True)
    B.signals(force=True)
    return {"through": through, "end": end, "dir": recent, "missing_404": dl.get("missing_404", [])}


def _f(x, nd=6):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def _five_year(cards_path: str) -> dict:
    try:
        with open(cards_path) as fh:
            cards = json.load(fh)["cards"]
    except (OSError, ValueError, KeyError):
        return {}
    return {(c["strategy"], r["tf"]): r for c in cards for r in c.get("rows", [])}


def _passed_tests(agents_db: Optional[str]) -> list[dict]:
    if not agents_db or not os.path.exists(agents_db):
        return []
    from . import rooms_db as R
    conn = R.open_ro(agents_db)
    if conn is None:
        return []
    try:
        out = []
        for t in R.trial_history(conn, kinds=("test",), limit=2000):
            res = (t.get("result") or {})
            body = res.get("result") if isinstance(res.get("result"), dict) else {}
            gate = body.get("gate") if isinstance(body.get("gate"), dict) else {}
            if res.get("status") == "passed" or gate.get("pass") is True:
                out.append({"trial_id": t["id"], "strategy": t["strategy"], "room_id": t["room_id"], "spec": t["spec"]})
        return out
    finally:
        conn.close()


def recheck(lab: str, through: str, agents_db: Optional[str] = None, cards_path: Optional[str] = None,
            names: Optional[list] = None) -> dict:
    from . import labtests as LT
    from . import packets3
    from ..strategy_view_defs import NAMES
    end = month_end(through)
    p4 = (("4", P4_START, end, "recent"),)
    data = LT.LabData(lab, extra={"recent": os.path.join(lab, "recent")})
    five = _five_year(cards_path or packets3.CARDS)
    t0 = time.time()
    strategies = {}
    for s in names or NAMES:
        rows = []
        for tf in TFS:
            spec = {"template": "by_tf", "strategy": s}
            row = LT._period_table(spec, LT._collect(spec, data, tf, None, p4), False, p4)["4"]
            b = row.get("baseline") or {}
            ref = five.get((s, tf)) or {}
            rows.append({"tf": tf, "available": row.get("available"), "trades": b.get("trades"),
                         "mean_roe": _f(b.get("mean_roe")), "win_rate": _f(b.get("win_rate")),
                         "mean_pnl_equity": _f(b.get("mean_pnl_equity")),
                         "five_year_mean_roe": _f(ref.get("mean_roe")), "five_year_win_rate": _f(ref.get("win_rate"))})
        strategies[s] = rows
    trials = []
    for t in _passed_tests(agents_db):
        try:
            sp = LT.normalize_spec(t["spec"], t["strategy"])
            per = LT._period_table(sp, LT._collect(sp, data, sp["timeframe"], sp, p4), True, p4)["4"]
            trials.append({**t, "spec": sp, "description_ko": LT.describe_ko(sp), "available": per.get("available"),
                           "baseline": per.get("baseline"), "variant": per.get("variant"),
                           "diff": _f(per.get("diff")), "p": _f(per.get("p")),
                           "still_better": None if per.get("diff") is None else bool(per["diff"] > 0)})
        except Exception as exc:  # noqa: BLE001  (one test that cannot be re-run never stops the report)
            trials.append({**t, "error": f"{type(exc).__name__}: {exc}"[:200]})
    return {"through": through, "period": [P4_START, end], "built_utc": datetime.now(timezone.utc).isoformat(),
            "runtime_s": round(time.time() - t0, 1), "strategies": strategies, "trials": trials,
            "note": "period 4 = new data after the five-year lab data; descriptive, the gate's verdicts do not change"}


def _json_default(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return _f(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    return str(x)


def write(lab: str, rep: dict) -> str:
    path = os.path.join(lab, "recent", REPORT)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, default=_json_default)
    os.replace(tmp, path)
    return path


def read(lab: Optional[str]) -> Optional[dict]:
    if not lab:
        return None
    try:
        with open(os.path.join(lab, "recent", REPORT), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.agents.labmonthly")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--lab", required=True)
    r.add_argument("--agents-db", default=None)
    r.add_argument("--through", default=None, help="last month to include (default: the last complete month)")
    r.add_argument("--procs", type=int, default=2)
    r.add_argument("--no-build", action="store_true", help="re-check on the data already built")
    a = ap.parse_args(argv)
    through = a.through or last_complete_month()
    if not a.no_build:
        print(json.dumps(build_recent(a.lab, through, a.procs)))
    path = write(a.lab, recheck(a.lab, through, a.agents_db))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
