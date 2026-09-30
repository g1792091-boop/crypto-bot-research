"""Alert delivery. The engine never depends on delivery succeeding."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Protocol

INFO = "INFO"
WARN = "WARN"
CRITICAL = "CRITICAL"


class Notifier(Protocol):
    def send(self, level: str, text: str) -> None: ...


class NullNotifier:
    def send(self, level: str, text: str) -> None:
        pass


class ListNotifier:
    """Keeps messages in memory; used by tests and replays."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send(self, level: str, text: str) -> None:
        self.messages.append((level, text))


class ConsoleNotifier:
    def send(self, level: str, text: str) -> None:
        print(f"[{level}] {text}", file=sys.stderr)


class TelegramNotifier:
    """Sends to one chat per level. Token and chat ids come from the
    environment so they never land in the repository:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_CRITICAL, TELEGRAM_CHAT_WARN,
    TELEGRAM_CHAT_INFO (WARN and INFO fall back to CRITICAL's chat)."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        critical = os.environ["TELEGRAM_CHAT_CRITICAL"]
        self.chats = {
            CRITICAL: critical,
            # an empty value in the env file means "not set", not "chat id ''"
            WARN: os.environ.get("TELEGRAM_CHAT_WARN") or critical,
            INFO: os.environ.get("TELEGRAM_CHAT_INFO") or critical,
        }
        self.timeout = timeout

    def send(self, level: str, text: str) -> None:
        data = urllib.parse.urlencode({
            "chat_id": self.chats.get(level, self.chats[CRITICAL]),
            "text": f"[{level}] {text}",
            "disable_notification": json.dumps(level == INFO),
        }).encode()
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            urllib.request.urlopen(url, data=data, timeout=self.timeout).read()
        except Exception as exc:  # delivery failure must not stop trading logic
            print(f"telegram send failed: {type(exc).__name__}", file=sys.stderr)


KO_KINDS = (("BUST", "파산"), ("drawdown", "낙폭"), ("ENGINE HALTED", "정지"), ("LIQUIDATED", "강제청산"))


class Digest:
    """Collects per-account WARN messages (bust, drawdown levels) and sends them
    as one silent message per interval, so 195 accounts cannot flood a phone.

    ``add`` never sends; ``flush(now_ms)`` sends when the interval has passed
    (or at once with ``force``) and returns the text it sent, if any."""

    def __init__(self, forward: Notifier, every_ms: int = 3_600_000, max_lines: int = 15):
        self.forward = forward
        self.every_ms = every_ms
        self.max_lines = max_lines
        self.items: list[str] = []
        self.last_ms: int | None = None

    def add(self, text: str) -> None:
        self.items.append(text)

    def flush(self, now_ms: int, force: bool = False):
        if self.last_ms is None:
            self.last_ms = now_ms
        if not self.items or (not force and now_ms - self.last_ms < self.every_ms):
            return None
        counts = {}
        for t in self.items:
            kind = next((ko for key, ko in KO_KINDS if key in t), "기타")
            counts[kind] = counts.get(kind, 0) + 1
        head = "알림 모음: " + " · ".join(f"{k} {n}" for k, n in counts.items())
        lines = self.items[:self.max_lines]
        more = len(self.items) - len(lines)
        text = "\n".join([head] + lines + ([f"외 {more}건 (대시보드 알림 목록)"] if more else []))
        self.forward.send(INFO, text)
        self.items = []
        self.last_ms = now_ms
        return text
