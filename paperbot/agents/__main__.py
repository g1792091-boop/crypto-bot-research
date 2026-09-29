"""Agent team pipelines.

    python -m paperbot.agents evening --ledger paper.db [--dry-run]
        [--print-packet] [--no-send] [--claude-bin claude] [--out report.json]

--dry-run uses canned answers (no Claude calls) to check the plumbing.
Scheduling: see deploy/ (systemd timer at 22:00 Asia/Seoul).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

from ..live import _notifier
from ..notify import ConsoleNotifier
from .budget import DEFAULT_MAX_CALLS, DEFAULT_MAX_TOKENS, BudgetedRunner
from .packets import evening_packet
from .pipeline import ReportStore, run_evening
from .runner import ClaudeCodeRunner, FakeRunner, billing_warnings


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("evening")
    ev.add_argument("--ledger", required=True, help="paper.db (written by the live runner)")
    ev.add_argument("--market", help="market.db of the signal recorder "
                                     "(default: market.db next to the ledger)")
    ev.add_argument("--agents-db", help="where agent answers and usage are stored "
                                        "(default: agents.db next to the ledger)")
    ev.add_argument("--dry-run", action="store_true")
    ev.add_argument("--print-packet", action="store_true")
    ev.add_argument("--no-send", action="store_true", help="print the report instead of Telegram")
    ev.add_argument("--claude-bin", default="claude")
    ev.add_argument("--timeout", type=float, default=900.0)
    ev.add_argument("--min-n", type=int, default=30)
    ev.add_argument("--out")
    ev.add_argument("--skip-no-trade-days", action="store_true",
                    help="save usage: no agent calls on a day with no closed trades "
                         "(by default the agents run and explain why there were none)")
    ev.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                    help="daily cap on Claude calls (Korea-time day, all runs)")
    ev.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                    help="daily cap on tokens (Korea-time day, all runs)")
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(args.ledger))
    market = args.market or os.path.join(here, "market.db")
    agents_db = args.agents_db or os.path.join(here, "agents.db")
    now = int(time.time() * 1000)
    packet = evening_packet(args.ledger, now, min_n=args.min_n, market=market)
    if args.print_packet:
        print(json.dumps(packet, ensure_ascii=False, indent=2, default=str))
        return 0
    warn = billing_warnings()
    if warn and not args.dry_run:
        print(f"note: {', '.join(warn)} set in this environment; it is NOT passed to "
              f"Claude Code (subscription login only).", file=sys.stderr)
    inner = FakeRunner() if args.dry_run else ClaudeCodeRunner(args.claude_bin, args.timeout)
    # Dry runs are not counted against the daily cap.
    # Each database has one writer: agent answers and usage go to agents.db.
    runner = inner if args.dry_run else BudgetedRunner(inner, agents_db, args.max_calls,
                                                        args.max_tokens)
    notifier = ConsoleNotifier() if (args.no_send or args.dry_run) else _notifier()
    store = ReportStore(agents_db)
    try:
        report = run_evening(packet, runner, store, notifier, now,
                             skip_if_no_trades=args.skip_no_trade_days)
    finally:
        store.close()
        if isinstance(runner, BudgetedRunner):
            runner.close()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
