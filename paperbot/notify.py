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
            WARN: os.environ.get("TELEGRAM_CHAT_WARN", critical),
            INFO: os.environ.get("TELEGRAM_CHAT_INFO", critical),
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
