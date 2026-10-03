"""Alert delivery. The engine never depends on delivery succeeding."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Optional, Protocol

INFO = "INFO"
WARN = "WARN"
CRITICAL = "CRITICAL"
# what a Telegram message starts with, by level (the owners may route every level to one chat)
PREFIX = {CRITICAL: "🚨 ", WARN: "⚠ ", INFO: ""}
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}


def _kst(ms: str) -> str:
    return time.strftime("%m/%d %H:%M", time.gmtime(int(ms) / 1000 + 9 * 3600))


def _coins(text: str) -> str:
    """"['BTCUSDT', 'ETHUSDT']" -> "BTC, ETH"."""
    return ", ".join(re.findall(r"(\w+?)USDT", text)) or text


def _who(book: str) -> str:
    """'S2_ST_ROC@15m' as the other Telegram messages name it (agents/roster3 STRATEGY_KO · timeframe)."""
    strat, _, tf = book.partition("@")
    if tf not in TF_KO:
        return book
    if strat.startswith("RANDOM_"):
        return f"동전 봇 {strat[7:]} · {TF_KO[tf]}"
    try:
        from .agents.roster3 import STRATEGY_KO
    except Exception:  # noqa: BLE001  (names are cosmetic)
        STRATEGY_KO = {}
    return f"{STRATEGY_KO.get(strat, strat)} · {TF_KO[tf]}"


# The English lines of the engine, the feed and the runner (trading files, kept as they are) that reach Telegram,
# in Korean, as the dashboard's alert list shows them (app.js alertKo). Applied per line of a Telegram message only
# (a digest's lines too): the stored alerts and the Digest's own text stay as they are. Anything else is unchanged.
KO_LINES = (
    (r"\[([^\]]+)\] LIQUIDATED (\w+?)(?:USDT)? (\d+)x lost margin ([\d.]+)",
     lambda m: f"{_who(m[1])} 강제청산: {m[2]} {m[3]}배, 증거금 ${m[4]} 손실"),
    (r"\[([^\]]+)\] BUST: bust: equity (-?[\d.]+) below ([\d.]+)",
     lambda m: f"{_who(m[1])} 파산: 잔고 ${m[2]} (${m[3]} 미만), 계좌 정지"),
    (r"\[([^\]]+)\] drawdown ([\d.]+)% \(level (\d+)%\), equity ([\d.]+)",
     lambda m: f"{_who(m[1])} 낙폭 {m[2]}% ({m[3]}% 경고선), 잔고 ${m[4]}"),
    (r"signal workers did not answer within (\d+)s; signals skipped at (\d+) for (.+)",
     lambda m: f"신호 계산이 {m[1]}초 안에 끝나지 않아 {_kst(m[2])}(한국) 봉 신호를 건너뜀: "
               + ", ".join(TF_KO.get(t, t) for t in m[3].split(", ")) + ". 계산 프로세스를 새로 띄우고 봇은 계속 돕니다"),
    (r"data gap at (\d+): no bar for (.+)",
     lambda m: f"1분봉 빠짐 {_kst(m[1])}(한국): {_coins(m[2])}. 그 코인은 그 1분을 건너뜀"),
    (r"(\w+?)USDT: exchange returned no bars for (\d+) min from (\d+)",
     lambda m: f"{m[1]}: 바이낸스가 {_kst(m[3])}(한국)부터 {m[2]}분 동안 1분봉을 주지 않음"),
    (r"no new closed bars for (\d+)s", lambda m: f"새 1분봉이 {m[1]}초째 들어오지 않음"),
    (r"Binance blocked this server: (.*)", lambda m: f"바이낸스가 이 서버의 접속을 막았습니다: {m[1]}"),
    (r"local clock off by (-?\d+) ms from Binance; using server time",
     lambda m: f"서버 시계가 바이낸스와 {m[1]}ms 어긋남: 바이낸스 시각을 씁니다"),
    # the last line of a digest (Digest here, extras.py): the screen that lists the rest
    (r"외 (\d+)건 \(대시보드 알림 목록\)$", lambda m: f"외 {m[1]}건 (대시보드 '서버 상태 → 경고')"),
)


def ko(text: str) -> str:
    """The Korean text of a known English alert line (KO_LINES); any other text unchanged. Never raises."""
    try:
        for pat, fmt in KO_LINES:
            m = re.match(pat, text, re.S)
            if m:
                return fmt(m)
    except Exception:  # noqa: BLE001  (a wording helper must never stop an alert)
        pass
    return text


class Notifier(Protocol):
    # False: delivery failed (a notifier that cannot tell returns None)
    def send(self, level: str, text: str) -> Optional[bool]: ...


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

    def send(self, level: str, text: str) -> bool:
        """True when Telegram accepted the message; False when delivery failed (never raises)."""
        data = urllib.parse.urlencode({
            "chat_id": self.chats.get(level, self.chats[CRITICAL]),
            "text": PREFIX.get(level, f"[{level}] ") + "\n".join(ko(line) for line in text.split("\n")),
            "disable_notification": json.dumps(level == INFO),
        }).encode()
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            urllib.request.urlopen(url, data=data, timeout=self.timeout).read()
        except Exception as exc:  # delivery failure must not stop trading logic
            print(f"telegram send failed: {type(exc).__name__}", file=sys.stderr)
            return False
        return True


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
