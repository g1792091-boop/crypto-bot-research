"""The one call the agents tick makes (paperbot/agents/rooms.py), behind a switch that is OFF by default.

    AGENTS_SHADOW_LEAGUE=1   (/etc/paperbot/agents.env; RoomsPolicy.shadow_league)

Off: rooms.py does not even import this package, so no file is created and no query is made. On: one League tick per
agents pass (every 15 minutes), with a wall-time cap (``WALL_S``, hard 20 seconds) after which the rest of the work is
simply done by the next pass: the state lives in the database, never in memory.

The tick reads only public Binance klines through the getter the agents tick already has (no key, no order, no
exchange account) and writes only shadow_league.db next to the agents database. It never touches paper3.db, the
accounts, the rules or the code.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, Optional

from . import ENV_SWITCH
from .league import HARD_S, MEMBERS, WORK_S, League
from .store import Store, default_path

WALL_S = HARD_S            # never longer than this per pass


def enabled(policy: Any) -> bool:
    return bool(getattr(policy, "shadow_league", False))


def run(agents_db: str, now_ms: int, get: Optional[Callable[[str], Any]], members: Optional[tuple] = None,
        path: Optional[str] = None, clock: Callable[[], float] = time.monotonic) -> dict:
    """One league tick. Never raises (a problem is returned and printed; the agents pass goes on)."""
    out: dict = {"enabled": True}
    store = None
    try:
        store = Store(path or default_path(agents_db))
        out.update(League(store, MEMBERS if members is None else members, get, clock).tick(now_ms, work_s=WORK_S, hard_s=WALL_S))
    except Exception as exc:  # noqa: BLE001  (the shadow league never stops the agents' meetings)
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        print(f"warning: shadow league ({ENV_SWITCH}) failed: {out['error']}", file=sys.stderr)
    finally:
        if store is not None:
            store.close()
    return out
