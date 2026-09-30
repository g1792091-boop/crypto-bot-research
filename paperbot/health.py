"""Liveness for the live runner: two separate signals.

* systemd watchdog (``WATCHDOG=1`` every loop): proves the process is not hung.
  If the loop stops, systemd kills and restarts it (``WatchdogSec=`` in the unit).
* External dead-man ping (``DEADMAN_URL``, e.g. a healthchecks.io check URL):
  sent only while the bot is actually processing fresh 1m bars. If Binance data
  stops, the server dies or the process hangs, the pings stop and the external
  service alerts both owners' phones. A restart cannot fix a data outage, so
  this one never restarts anything; it only makes sure someone is told.

Both are no-ops when their environment variable is not set.
"""

from __future__ import annotations

import os
import socket
import sys
import urllib.request
from typing import Callable, Optional

MIN = 60_000


def sd_notify(msg: str, env: Optional[dict] = None) -> bool:
    """Send a message to systemd (READY=1, WATCHDOG=1, STATUS=...).
    Returns False when not running under systemd with a notify socket."""
    addr = (env if env is not None else os.environ).get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(msg.encode())
        return True
    except OSError:
        return False


def _get(url: str, timeout: float) -> None:
    urllib.request.urlopen(url, timeout=timeout).read()


class DeadMan:
    """Pings ``url`` at most once per ``every_ms`` while the newest processed 1m bar
    closed less than ``max_lag_ms`` ago. Configure the external check with a period
    of ``every_ms`` and a grace of about 5 minutes."""

    def __init__(self, url: Optional[str], max_lag_ms: int = 3 * MIN, every_ms: int = MIN,
                 get: Callable[[str, float], None] = _get, timeout: float = 5.0):
        self.url = url or None
        self.max_lag_ms = max_lag_ms
        self.every_ms = every_ms
        self.get = get
        self.timeout = timeout
        self.last_ping: Optional[int] = None
        self.last_try: Optional[int] = None
        self.failures = 0

    def beat(self, now_ms: int, last_bar_open_ms: Optional[int]) -> Optional[bool]:
        """Returns True when a ping was sent, False when it was due but withheld or
        failed, None when nothing was due."""
        if self.url is None:
            return None
        if self.last_try is not None and now_ms - self.last_try < self.every_ms:
            return None
        self.last_try = now_ms
        if last_bar_open_ms is None or now_ms - (last_bar_open_ms + MIN) > self.max_lag_ms:
            return False  # stale data: stay silent so the external check fires
        try:
            self.get(self.url, self.timeout)
        except Exception as exc:  # the ping must never stop the bot
            self.failures += 1
            print(f"dead-man ping failed: {type(exc).__name__}", file=sys.stderr)
            return False
        self.last_ping = now_ms
        return True
