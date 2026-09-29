"""Agent team pipelines.

    python -m paperbot.agents evening --ledger paper.db [--dry-run]
        [--print-packet] [--no-send] [--claude-bin claude] [--out report.json]

--dry-run uses canned answers (no Claude calls) to check the plumbing.
Scheduling: see deploy/ (systemd timer at 22:00 Asia/Seoul).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional

from ..live import _notifier
from ..notify import ConsoleNotifier
from .packets import evening_packet
from .pipeline import ReportStore, run_evening
from .runner import ClaudeCodeRunner, FakeRunner, billing_warnings


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("evening")
    ev.add_argument("--ledger", required=True)
    ev.add_argument("--dry-run", action="store_true")
    ev.add_argument("--print-packet", action="store_true")
    ev.add_argument("--no-send", action="store_true", help="print the report instead of Telegram")
    ev.add_argument("--claude-bin", default="claude")
    ev.add_argument("--timeout", type=float, default=900.0)
    ev.add_argument("--min-n", type=int, default=30)
    ev.add_argument("--out")
    args = ap.parse_args(argv)

    now = int(time.time() * 1000)
    packet = evening_packet(args.ledger, now, min_n=args.min_n)
    if args.print_packet:
        print(json.dumps(packet, ensure_ascii=False, indent=2, default=str))
        return 0
    warn = billing_warnings()
    if warn and not args.dry_run:
        print(f"note: {', '.join(warn)} set in this environment; it is NOT passed to "
              f"Claude Code (subscription login only).", file=sys.stderr)
    runner = FakeRunner() if args.dry_run else ClaudeCodeRunner(args.claude_bin, args.timeout)
    notifier = ConsoleNotifier() if (args.no_send or args.dry_run) else _notifier()
    store = ReportStore(args.ledger)
    try:
        report = run_evening(packet, runner, store, notifier, now)
    finally:
        store.close()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
