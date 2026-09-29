"""Daily usage cap for agent calls.

Every Claude call is counted in agents.db (agent_calls table), failed ones
included. Before each call the day's totals (Korea-time day) are checked;
over the cap, the call is not made and the pipeline stops like it does at
the plan's own usage limit. Tokens are known only after a call, so one
call can run past the token cap; the next one is then refused.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from ..ledger import SCHEMA
from ..sessions import KST
from .runner import CallResult, Runner, UsageLimitReached

DEFAULT_MAX_CALLS = 12       # one evening run is 6 calls; room for retries
DEFAULT_MAX_TOKENS = 300_000  # one measured evening run: about 105,000


class BudgetExceeded(UsageLimitReached):
    pass


def kst_day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(KST).strftime("%Y-%m-%d")


def tokens_of(meta: dict) -> int:
    u = (meta or {}).get("usage") or {}
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                             "cache_read_input_tokens", "output_tokens"))


class BudgetedRunner:
    def __init__(self, runner: Runner, db_path: str, max_calls: int = DEFAULT_MAX_CALLS,
                 max_tokens: int = DEFAULT_MAX_TOKENS, pipeline: str = "evening",
                 clock_ms: Optional[Callable[[], int]] = None):
        self.runner = runner
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.pipeline = pipeline
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def used_today(self) -> tuple[int, int]:
        row = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(tokens), 0) FROM agent_calls "
                                "WHERE day = ?", (kst_day(self.clock_ms()),)).fetchone()
        return int(row[0]), int(row[1])

    def _record(self, role: str, model: str, ok: bool, tokens: int) -> None:
        now = self.clock_ms()
        self.conn.execute("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)",
                          (now, kst_day(now), self.pipeline, role, model, int(ok), tokens))
        self.conn.commit()

    def call(self, model: str, system_prompt: str, instruction: str, packet: dict) -> CallResult:
        calls, tokens = self.used_today()
        if calls >= self.max_calls:
            raise BudgetExceeded(f"daily cap: {calls}/{self.max_calls} calls used today")
        if tokens >= self.max_tokens:
            raise BudgetExceeded(f"daily cap: {tokens:,}/{self.max_tokens:,} tokens used today")
        role = str(packet.get("role", ""))
        try:
            res = self.runner.call(model, system_prompt, instruction, packet)
        except Exception:
            self._record(role, model, False, 0)
            raise
        self._record(role, model, True, tokens_of(res.meta))
        return res

    def close(self) -> None:
        self.conn.close()
