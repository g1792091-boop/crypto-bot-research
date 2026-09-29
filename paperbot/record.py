"""Record-only signal mode (handover v2, case B).

    python -m paperbot.record daily   --market market.db --ledger paper.db [--since 2023-10-01]
        sync market data, then compute and record signals (for the timer)
    python -m paperbot.record sync    --market market.db [--since 2023-10-01]
        fetch closed 5m bars, 5m mark bars and funding for the recorded coins
        (the first sync backfills from --since; default three years back)
    python -m paperbot.record compute --market market.db [--ledger paper.db]
        compute the record-only cells and append new signals
    python -m paperbot.record status  --market market.db
        coverage, last runs, mismatches

Coins: the six traded ones plus XRPUSDT, which is recorded only (never
traded). Public market data needs no API key. The locked signal code is
hash-checked before every compute.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .archive import RECORD_SYMBOLS, MarketArchive, sync
from .recorder import Recorder, last_runs


def _since_ms(text: Optional[str]) -> int:
    if text:
        d = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        d = today - timedelta(days=3 * 365)
    return int(d.timestamp() * 1000)


def _notifier():
    from .live import _notifier as live_notifier
    return live_notifier()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("daily", "sync", "compute", "status"):
        p = sub.add_parser(name)
        p.add_argument("--market", default="market.db")
        p.add_argument("--symbols", default=",".join(RECORD_SYMBOLS))
        if name in ("daily", "sync"):
            p.add_argument("--since", help="first-sync start date (UTC), default 3 years back")
            p.add_argument("--pace", type=float, default=0.15, help="seconds between requests")
        if name in ("daily", "compute"):
            p.add_argument("--ledger", help="paper.db with order-book snapshots (optional)")
    args = ap.parse_args(argv)
    symbols = [s for s in args.symbols.split(",") if s]
    archive = MarketArchive(args.market)
    try:
        if args.cmd == "status":
            out = {"coverage_last_24h": {}, "runs": last_runs(archive.conn, 5)}
            now = int(time.time() * 1000)
            for s in symbols:
                out["coverage_last_24h"][s] = archive.coverage(s, now - 86_400_000, now)
            out["mismatches_total"] = archive.conn.execute(
                "SELECT COUNT(*) FROM sweep_mismatch").fetchone()[0]
            out["signals_total"] = archive.conn.execute(
                "SELECT COUNT(*) FROM sweep_signals").fetchone()[0]
            print(json.dumps(out, indent=2, default=str))
            return 0
        notifier = _notifier()
        if args.cmd in ("daily", "sync"):
            from .live import _rest
            summary = sync(archive, _rest(), symbols, _since_ms(args.since), pace=args.pace)
            archive.log_system("sync", summary)
            print(json.dumps(summary, indent=2))
        if args.cmd in ("daily", "compute"):
            rep = Recorder(archive, ledger_path=args.ledger, notifier=notifier).run(symbols)
            print(json.dumps({k: v for k, v in rep.items() if k != "warmup"}, indent=2))
            return 0 if rep["status"] == "ok" and not rep["mismatches"] else 1
        return 0
    finally:
        archive.close()


if __name__ == "__main__":
    sys.exit(main())
