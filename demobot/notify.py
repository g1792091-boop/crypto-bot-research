"""Telegram of the demo lab bot ("데모 랩"): the wording (``render``), the outbox (``Outbox``) and the sender.

CONTRACT.md section 5. The engine queues events (``Outbox.queue``), this module words them in Korean at once and
stores the text in the table ``outbox`` of demo.db; ``Outbox.flush`` sends the oldest unsent rows to the demo lab's
own Telegram group (a NEW bot and a NEW group, never the rule bot's). Delivery never stops the engine: ``flush``
never raises on a network or Telegram error, it keeps the error text (token removed) on the row and tries again
later; a row Telegram refused 5 times, or one that could not go out for 24 hours, is given up.

Wording (the rule bot's Telegram redesign of 2026-10-04 is the reference): plain text (no parse_mode), the first
line says what happened and may start with one emoji, then short lines; times are KST '%m/%d %H:%M'; coins without
the quote ('BTC', not 'BTCUSD'); no emoji inside the lines. Every message is silent (disable_notification), as the
owners chose for the rule bot ("전부 다 무음으로", 2026-10-05). Telegram allows 4096 characters: a long list is cut
and ends with '외 N건은 대시보드에서'.

The token is read from the environment only (DEMOBOT_TG_TOKEN, DEMOBOT_TG_CHAT; /etc/demobot/demobot.env) and is
never logged, printed or stored: every error text goes through ``redact``.

    python -m demobot.notify test      # sends '🧪 데모 랩 테스트 메시지' to DEMOBOT_TG_CHAT
    python -m demobot.notify chatid    # lists the groups the bot has seen (to find DEMOBOT_TG_CHAT)

Both read the two keys from the environment, else from /etc/demobot/demobot.env (``--env-file``), so the owners
never paste the token anywhere but the server's editor.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from . import grid as G

API = "https://api.telegram.org"
ENV_FILE = "/etc/demobot/demobot.env"
LIMIT = 4000                 # Telegram's limit is 4096 (UTF-16 units; an emoji counts 2): a margin
LINE_MAX = 600               # one list line at most (a runaway setting text cannot eat the message)
MAX_TRIES = 5                # Telegram refused a row this many times: given up (error kept)
MIN_GAP_S = 1.0              # at most one message a second
PER_MINUTE = 18              # Telegram allows about 20 a minute in one group
TIMEOUT_S = 10.0
BACKOFF_S = 30.0             # after a failure the outbox waits 30 s, 60 s, 120 s ... (at most BACKOFF_MAX_S)
BACKOFF_MAX_S = 900.0
STALE_MS = 24 * 3600_000     # an unsent row older than this is given up (no flood of old ticks after an outage)
WARN_EVERY_MS = 3600_000     # warn: at most one per 'what' per hour
KEEP_MS = 30 * 86400_000     # sent (and given-up) rows are deleted after 30 days
PRUNE_EVERY_MS = 3600_000
MORE = "외 {n}건은 대시보드에서"
TEST_TEXT = "🧪 데모 랩 테스트 메시지"

TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
WINDOW_KO = {"live": "실시간", "26w": "26주", "4w": "4주"}
REASON_KO = {"stop": "손절", "lock": "잠금 익절", "liq": "강제청산", "tp": "익절", "time": "시간 청산",
             "open": "보유 중"}
KIND_KO = {"fixed": "고정", "adaptive": "자동", "friend": "친구 규칙", "flip": "동전 던지기"}
WARN_KO = {"data": "시세 자료 빠짐", "stalled": "멈춤 (새 봉 처리 안 됨)", "error": "오류",
           "disk": "디스크 공간 부족"}


# ---------------------------------------------------------------- number and name helpers
def _num(x) -> Optional[float]:
    """A finite float, or None (None, NaN, text, bool)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def kst(ms, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(int(ms) / 1000 + 9 * 3600))


def px(x) -> str:
    """A price with the decimals its size needs: 62,345.1 · 2,345.67 · 2.5123 · 0.21345."""
    v = _num(x)
    if v is None:
        return "-"
    a = abs(v)
    d = 5 if a < 1 else 4 if a < 10 else 2 if a < 1000 else 1
    return f"{v:,.{d}f}"


def usd(x) -> str:
    """Signed dollars and cents: '+$12.30', '-$5.10' (never '$-5.10')."""
    v = _num(x)
    if v is None:
        return "-"
    return f"{'-' if v < 0 else '+'}${abs(v):,.2f}"


def pct(x) -> str:
    """A percent value (4.2 means 4.2 %): '+4.2%'."""
    v = _num(x)
    return "-" if v is None else f"{v:+.1f}%"


def rr(x) -> str:
    v = _num(x)
    return "-" if v is None else f"{v:+.2f}R"


def rate(x) -> str:
    """A win rate given as a share (0.41) or as a percent (41.0): '41%'."""
    v = _num(x)
    if v is None:
        return "-"
    return f"{v * 100 if abs(v) <= 1 else v:.0f}%"


def count(x) -> str:
    v = _num(x)
    return "-" if v is None else f"{int(round(v)):,}"


def coin(c) -> str:
    """'BTCUSD' -> 'BTC' (grid.coin_ko); 'BTCUSDT' -> 'BTC'; 'ALL' -> '전체 코인'."""
    s = str(c or "").strip()
    if s.upper() == "ALL":
        return "전체 코인"
    if s.endswith("USDT"):
        return s[:-4]
    if s.endswith("USD") and len(s) > 3:
        return G.coin_ko(s)
    return s or "?"


def side_ko(s) -> str:
    v = _num(s)
    return "롱" if v is not None and v > 0 else "숏" if v is not None and v < 0 else "?"


def tf_ko(tf) -> str:
    return TF_KO.get(str(tf), str(tf or ""))


def strat_short(s) -> str:
    return G.SHORT.get(str(s), str(s or ""))


def exit_label(e) -> str:
    """'house' / 'tp1.5R_sl2atr' / an exit index -> the Korean label (grid.exit_ko); anything else as given."""
    try:
        if isinstance(e, str) and e in G.EXITS:
            return G.exit_ko(e)
        if isinstance(e, int) and not isinstance(e, bool) and 0 <= e < G.NEXIT:
            return G.exit_ko(e)
    except Exception:  # noqa: BLE001  (labels are cosmetic)
        pass
    return str(e or "")


def _lev_sorted(d) -> list:
    """{'20': x, '30': y} -> [(20, x), (30, y)] by leverage."""
    out = []
    for k, v in (d or {}).items():
        try:
            out.append((int(k), v))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def _clip(s: str, n: int = LINE_MAX) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _fit(head: list, sections: list, tail: list) -> str:
    """head lines, then each (title, item lines) section after a blank line, then tail lines. Longer than ``LIMIT``:
    every section first gets an equal share of the room (what one leaves over goes to the others, in order), the rest
    of its items are left out and '외 N건은 대시보드에서' says how many."""
    sections = [(t, [_clip(x) for x in items]) for t, items in sections if items]
    full = list(head)
    for title, items in sections:
        full += ["", title] + items
    full += tail
    text = "\n".join(full)
    if len(text) <= LIMIT or not sections:
        return text[:LIMIT]
    total = sum(len(items) for _, items in sections)
    room = LIMIT - len("\n".join(head)) - len("\n".join(tail)) - len(MORE) - 24
    take, used = [0] * len(sections), [0] * len(sections)

    def grow(i: int, budget: int) -> None:
        title, items = sections[i]
        while take[i] < len(items):
            add = len(items[take[i]]) + 1 + (len(title) + 2 if take[i] == 0 else 0)
            if used[i] + add > budget:
                return
            used[i] += add
            take[i] += 1

    share = room // len(sections)
    for i in range(len(sections)):
        grow(i, share)
    for i in range(len(sections)):
        grow(i, used[i] + room - sum(used))
    lines = list(head)
    for (title, items), k in zip(sections, take):
        if k:
            lines += ["", title] + items[:k]
    lines += ["", MORE.format(n=total - sum(take))] + list(tail)
    return "\n".join(lines)[:LIMIT]


# ---------------------------------------------------------------- the messages (CONTRACT.md section 5)
def _start(p: dict, now_ms: Optional[int]) -> list:
    n = count(p.get("accounts") or 48)
    if str(p.get("phase")) == "warm":
        L = ["▶️ 데모 랩 시작 · 준비 중", "지난 26주 시세를 채우는 중 (10~15분)", f"계좌 {n}개 · 모의 거래만 · 주문 없음"]
    else:
        L = [f"▶️ 데모 랩 시작 · 계좌 {n}개"]
        ls = _num(p.get("live_start_ms"))
        if ls:
            again = now_ms is not None and now_ms - ls > 30 * 60_000
            L.append(f"{'이어서 돌림 · ' if again else ''}실시간 시작 {kst(ls)}")
        L.append("모의 거래만 · 주문 없음 · 결과는 대시보드에서")
    return L


def _trade_line(t: dict, closed: bool) -> str:
    name = str(t.get("name") or t.get("account") or "?")
    what = f"{coin(t.get('coin'))} {side_ko(t.get('side'))}"
    setting = str(t.get("setting_ko") or "").strip()
    ex = str(t.get("exit_ko") or "").strip()
    rule = " / ".join(x for x in (setting, ex) if x)
    if not closed:
        return f"- {name}: {what} {px(t.get('entry'))}" + (f" · {rule}" if rule else "")
    reason = t.get("reason")
    why = REASON_KO.get(str(reason), str(reason or "청산"))
    r = _num(t.get("R"))
    parts = [f"- {name}: {what} {px(t.get('entry'))} → {px(t.get('exit'))} {why}" + (f" {rr(r)}" if r is not None else "")]
    lev = [f"{L}배 {usd(v)}" for L, v in _lev_sorted(t.get("pnl_by_L")) if _num(v) is not None]
    if lev:
        parts.append(" · ".join(lev))
    if rule:
        parts.append(rule)
    return " · ".join(parts)


def _tick(p: dict) -> str:
    opens = [t for t in (p.get("opens") or []) if isinstance(t, dict)]
    closes = [t for t in (p.get("closes") or []) if isinstance(t, dict)]
    if not opens and not closes:
        return ""
    what = " · ".join(x for x in (f"진입 {len(opens)}" if opens else "", f"청산 {len(closes)}" if closes else "") if x)
    head = [f"🧪 데모 랩 모의 거래 · {what}"]
    bar = _num(p.get("bar_ms"))
    if bar:
        head.append(f"{kst(bar)} 봉")
    return _fit(head, [(f"진입 {len(opens)}", [_trade_line(t, False) for t in opens]),
                       (f"청산 {len(closes)}", [_trade_line(t, True) for t in closes])], [])


def _switch(p: dict, now_ms: Optional[int]) -> str:
    name = str(p.get("name") or p.get("account") or "?")
    items = []
    for it in p.get("items") or []:
        if not isinstance(it, dict):
            continue
        where = coin(it.get("coin") or "ALL")
        L = _num(it.get("L"))
        if L:
            where += f" {int(L)}배"
        line = f"- {where}: {it.get('from_ko') or '-'} → {it.get('to_ko') or '-'}"
        if it.get("why_ko"):
            line += f" · {it['why_ko']}"
        items.append(line)
    tail = [kst(now_ms)] if now_ms else []
    return _fit([f"🔁 설정 바꿈 · {name}"], [(f"바뀐 곳 {len(items)}", items)], tail)


def _daily(p: dict) -> str:
    day = str(p.get("day") or "")
    m = re.fullmatch(r"\d{4}-(\d{2})-(\d{2})", day)
    head = [f"📋 데모 랩 하루 요약 · {m[1]}/{m[2]}" if m else "📋 데모 랩 하루 요약"]
    sub = []
    ld = _num(p.get("live_days"))
    if ld is not None:
        sub.append(f"실시간 {ld:.1f}일째")
    if _num(p.get("trades_24h")) is not None:
        sub.append(f"지난 24시간 거래 {count(p.get('trades_24h'))}건")
    if sub:
        head.append(" · ".join(sub))

    def acct(a) -> str:
        L = _num(a.get("L"))
        money = f" ({usd(a['pnl'])})" if _num(a.get("pnl")) is not None else ""
        return f"- {a.get('name') or a.get('id') or '?'}{f' {int(L)}배' if L else ''} {pct(a.get('pnl_pct'))}{money}"

    best = [acct(a) for a in (p.get("best") or [])[:3] if isinstance(a, dict)]
    worst = [acct(a) for a in (p.get("worst") or [])[:3] if isinstance(a, dict)]
    kinds = []
    for k in p.get("by_kind") or []:
        if not isinstance(k, dict):
            continue
        name = k.get("kind_ko") or KIND_KO.get(str(k.get("kind")), str(k.get("kind") or "?"))
        vals = " · ".join(f"{L}배 {pct(v)}" for L, v in _lev_sorted(k.get("mean_pnl_pct")))
        kinds.append(f"- {name} {vals}".rstrip())
    leaders = []
    for x in (p.get("leaders") or [])[:8]:
        if not isinstance(x, dict):
            continue
        where = f"{strat_short(x.get('strategy'))} {tf_ko(x.get('tf'))}".strip()
        win = WINDOW_KO.get(str(x.get("window")), str(x.get("window") or ""))
        rule = " · ".join(s for s in (str(x.get("label") or ""), exit_label(x.get("exit"))) if s)
        luck = "운보다 나음" if x.get("beats_luck") else "운과 구별 안 됨"
        leaders.append(f"- {where}{f' ({win})' if win else ''}: {rule} · {rr(x.get('mean_R'))} · "
                       f"승률 {rate(x.get('win_rate'))} · {count(x.get('n'))}건 · 운 기준 {rr(x.get('luck95'))} → {luck}")
    passed = int(_num(p.get("passed")) or 0)
    tail = ["", f"우리 기준 통과 {passed}개" + (" (실제 돈은 두 분이 정합니다)" if passed else ""),
            "통과 전에는 실제 돈 금지"]
    return _fit(head, [("수익 위", best), ("수익 아래", worst), ("종류별 평균 수익", kinds),
                       ("순위표 1등 vs 운 (운 기준: 무작위 1등의 95% 선)", leaders)], tail)


def _warn(p: dict, now_ms: Optional[int]) -> list:
    what = str(p.get("what") or "")
    L = [f"⚠ 데모 랩 경고 · {WARN_KO.get(what, what or '알림')}"]
    if p.get("detail_ko"):
        L.append(_clip(str(p["detail_ko"]), 1500))
    L.append("규칙봇과는 별개 · 주문 없음")
    if now_ms:
        L.append(kst(now_ms))
    return L


def _pass(p: dict, now_ms: Optional[int]) -> str:
    name = str(p.get("name") or p.get("account") or "?")
    L = _num(p.get("L"))
    head = [f"🏁 우리 기준 통과 · {name}{f' {int(L)}배' if L else ''}"]
    checks = []
    for c in p.get("checks") or []:
        if not isinstance(c, dict):
            continue
        ok = c.get("ok")
        mark = "" if ok is None else " (충족)" if ok else " (미달)"
        val = f": {c['value_ko']}" if c.get("value_ko") not in (None, "") else ""
        checks.append(f"- {c.get('name_ko') or '?'}{val}{mark}")
    tail = ["", "데모 계좌의 모의 거래 결과입니다", "실제 돈을 쓸지는 두 분이 정합니다 (봇은 주문하지 않음)"]
    if now_ms:
        tail.append(kst(now_ms))
    return _fit(head, [("기준", checks)], tail)


def render(kind: str, payload: dict, now_ms: Optional[int] = None) -> str:
    """The Korean Telegram text of one event (CONTRACT.md section 5). ``now_ms`` (optional) adds the KST time to the
    kinds that carry no time of their own. Pure (no I/O, no clock); never raises; '' for a tick with no trade."""
    p = payload if isinstance(payload, dict) else {}
    try:
        if kind == "start":
            text = "\n".join(_start(p, now_ms) + ([kst(now_ms)] if now_ms else []))
        elif kind == "tick":
            text = _tick(p)
        elif kind == "switch":
            text = _switch(p, now_ms)
        elif kind == "daily":
            text = _daily(p)
        elif kind == "warn":
            text = "\n".join(_warn(p, now_ms))
        elif kind == "pass":
            text = _pass(p, now_ms)
        else:
            body = p.get("detail_ko") or p.get("text") or ""
            text = f"🧪 데모 랩 알림 · {kind}" + (f"\n{body}" if body else "")
    except Exception as exc:  # noqa: BLE001  (a wording slip must never stop the engine)
        text = f"🧪 데모 랩 알림 · {kind}\n(문장을 만들지 못함: {type(exc).__name__})"
    return text[:LIMIT]


# ---------------------------------------------------------------- the sender
_TOKEN_RE = re.compile(r"\d{5,}(?::|%3A)[A-Za-z0-9_-]{20,}", re.IGNORECASE)


def redact(text, token: Optional[str] = None) -> str:
    """``text`` without the bot token (its exact value, URL-quoted, and anything shaped like a bot token)."""
    s = str(text)
    t = (token or "").strip()
    if len(t) >= 8:
        s = s.replace(t, "<token>").replace(urllib.parse.quote(t, safe=""), "<token>")
    return _TOKEN_RE.sub("<token>", s)


class TelegramError(Exception):
    """A failed Bot API call; the message never holds the token. ``transient``: a network error, Telegram busy
    (5xx) or the rate limit (429; ``retry_after`` seconds): the row is tried again without counting a try."""

    def __init__(self, msg: str, transient: bool = False, retry_after: Optional[float] = None):
        super().__init__(msg)
        self.transient = transient
        self.retry_after = retry_after


def _http_detail(exc: urllib.error.HTTPError) -> tuple:
    try:
        body = json.loads(exc.read() or b"{}")
        desc = str(body.get("description") or exc.reason)
        ra = (body.get("parameters") or {}).get("retry_after")
        return desc, (float(ra) if ra is not None else None)
    except Exception:  # noqa: BLE001
        return str(getattr(exc, "reason", "") or ""), None


def api(token: str, method: str, params: Optional[dict] = None, timeout: float = TIMEOUT_S):
    """One Bot API call (POST, urllib); its ``result``. Raises ``TelegramError`` (token removed) on any failure."""
    url = f"{API}/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
            body = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        desc, ra = _http_detail(exc)
        raise TelegramError(redact(f"HTTP {exc.code}: {desc}", token)[:300],
                            transient=exc.code == 429 or exc.code >= 500, retry_after=ra) from None
    except Exception as exc:  # noqa: BLE001  (URLError, timeout, reset, bad JSON: the network)
        reason = getattr(exc, "reason", None) or exc
        raise TelegramError(redact(f"{type(exc).__name__}: {reason}", token)[:300], transient=True) from None
    if not isinstance(body, dict) or not body.get("ok"):
        desc = body.get("description") if isinstance(body, dict) else body
        raise TelegramError(redact(f"Telegram: {desc}", token)[:300])
    return body.get("result")


def send_message(token: str, chat: str, text: str, timeout: float = TIMEOUT_S):
    """sendMessage: plain text, silent, no link preview."""
    return api(token, "sendMessage", {"chat_id": chat, "text": text, "disable_web_page_preview": "true",
                                      "disable_notification": "true"}, timeout)


# ---------------------------------------------------------------- the outbox
OUTBOX_SCHEMA = ("CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, ts_ms INTEGER, kind TEXT, payload TEXT, "
                 "text TEXT, sent_ms INTEGER, tries INTEGER DEFAULT 0, error TEXT)")
OUTBOX_INDEX = "CREATE INDEX IF NOT EXISTS outbox_unsent ON outbox(id) WHERE sent_ms IS NULL"


class Outbox:
    """The queue of Telegram messages in demo.db (table ``outbox``).

    ``queue(kind, payload)`` words the event now (``render``) and stores it; ``flush(token, chat)`` sends the oldest
    unsent rows; ``state()`` is the status.json "telegram" block. A write made while the caller's own transaction
    is open joins that transaction (the caller commits it); otherwise it is committed at once.
    ``clock`` (seconds), ``sleep`` and ``monotonic`` are injectable for tests."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic):
        self.conn = conn
        self._clock, self._sleep, self._mono = clock, sleep, monotonic
        self._write(OUTBOX_SCHEMA)
        self._write(OUTBOX_INDEX)
        self._configured: Optional[bool] = None
        self._hold_until_ms = 0
        self._fails = 0
        self._sent_at: list = []          # monotonic times of the sends in the last minute
        self._last_prune_ms = 0

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _write(self, sql: str, args=()) -> None:
        was = self.conn.in_transaction
        self.conn.execute(sql, args)
        if not was and self.conn.in_transaction:
            self.conn.commit()

    # -------------------------------------------------- queue
    def queue(self, kind: str, payload: dict) -> None:
        """Word ``payload`` now and store it unsent. warn: at most one per ``what`` per hour (the later ones are
        dropped); a tick without trades is not stored."""
        payload = payload if isinstance(payload, dict) else {}
        now = self._now_ms()
        if kind == "warn":
            what = str(payload.get("what") or "")
            for (raw,) in self.conn.execute("SELECT payload FROM outbox WHERE kind = 'warn' AND ts_ms > ?",
                                            (now - WARN_EVERY_MS,)):
                try:
                    if str((json.loads(raw) or {}).get("what") or "") == what:
                        return
                except (TypeError, ValueError, AttributeError):
                    continue
        text = render(kind, payload, now_ms=now)
        if not text.strip():
            return
        self._write("INSERT INTO outbox(ts_ms, kind, payload, text, tries) VALUES(?, ?, ?, ?, 0)",
                    (now, str(kind), json.dumps(payload, ensure_ascii=False, default=str), text))

    # -------------------------------------------------- flush
    def _pace(self) -> bool:
        """Wait for the 1-a-second gap; False when the minute's budget (``PER_MINUTE``) is used up."""
        now = self._mono()
        self._sent_at = [t for t in self._sent_at if now - t < 60.0]
        if len(self._sent_at) >= PER_MINUTE:
            return False
        if self._sent_at:
            gap = MIN_GAP_S - (now - self._sent_at[-1])
            if gap > 0:
                self._sleep(gap)
        return True

    def _prune(self, now: int) -> None:
        if now - self._last_prune_ms < PRUNE_EVERY_MS:
            return
        self._last_prune_ms = now
        self._write("DELETE FROM outbox WHERE (sent_ms IS NOT NULL AND sent_ms < ?) "
                    "OR (sent_ms IS NULL AND tries >= ? AND ts_ms < ?)", (now - KEEP_MS, MAX_TRIES, now - KEEP_MS))

    def flush(self, token: str, chat: str, limit: int = 20, send: Optional[Callable] = None) -> int:
        """Send the oldest unsent rows (at most ``limit``, one a second, ``PER_MINUTE`` a minute); the number sent.
        ``send(token, chat, text)`` raises (or returns False) on failure; default: ``send_message``. A failure keeps
        its error on the row (token removed), counts a try unless it was transient (network, 5xx, 429) and pauses
        the outbox (30 s, doubling, at most 15 min). Never raises on network, Telegram or database errors."""
        token, chat = (token or "").strip(), str(chat or "").strip()
        self._configured = bool(token and chat)
        sent = 0
        try:
            now = self._now_ms()
            self._prune(now)
            if not self._configured or now < self._hold_until_ms:
                return 0
            self._write("UPDATE outbox SET tries = ?, error = ? WHERE sent_ms IS NULL AND tries < ? AND ts_ms < ?",
                        (MAX_TRIES, "24시간 안에 못 보내 건너뜀", MAX_TRIES, now - STALE_MS))
            rows = self.conn.execute("SELECT id, text FROM outbox WHERE sent_ms IS NULL AND tries < ? "
                                     "ORDER BY id LIMIT ?", (MAX_TRIES, max(0, int(limit)))).fetchall()
            send = send or send_message
            for rid, text in rows:
                if not self._pace():
                    break
                try:
                    self._sent_at.append(self._mono())
                    if send(token, chat, text) is False:
                        raise TelegramError("send returned False")
                except Exception as exc:  # noqa: BLE001  (delivery never stops the engine)
                    err = redact(str(exc) if isinstance(exc, TelegramError) else f"{type(exc).__name__}: {exc}",
                                 token)[:300]
                    transient = bool(getattr(exc, "transient", False))
                    self._write("UPDATE outbox SET tries = tries + ?, error = ? WHERE id = ?",
                                (0 if transient else 1, err, rid))
                    self._fails += 1
                    wait = min(BACKOFF_MAX_S, BACKOFF_S * 2 ** min(self._fails - 1, 10))
                    ra = _num(getattr(exc, "retry_after", None))
                    self._hold_until_ms = self._now_ms() + int(max(wait, ra or 0.0) * 1000)
                    break
                self._write("UPDATE outbox SET sent_ms = ? WHERE id = ?", (self._now_ms(), rid))
                sent += 1
                self._fails = 0
                self._hold_until_ms = 0
        except sqlite3.Error as exc:
            print(f"demobot outbox: {type(exc).__name__}: {exc}"[:300], file=sys.stderr)
        return sent

    # -------------------------------------------------- state
    def state(self) -> dict:
        """{"configured", "queued", "last_ok_ms", "last_error"} for status.json. ``configured``: the last flush had a
        token and a chat (before any flush: the environment has both). Never raises."""
        configured = self._configured
        if configured is None:
            configured = bool(os.environ.get("DEMOBOT_TG_TOKEN", "").strip()
                              and os.environ.get("DEMOBOT_TG_CHAT", "").strip())
        out = {"configured": bool(configured), "queued": 0, "last_ok_ms": None, "last_error": None}
        try:
            c = self.conn
            out["queued"] = int(c.execute("SELECT COUNT(*) FROM outbox WHERE sent_ms IS NULL AND tries < ?",
                                          (MAX_TRIES,)).fetchone()[0])
            ok = c.execute("SELECT MAX(sent_ms), MAX(CASE WHEN sent_ms IS NOT NULL THEN id END) FROM outbox").fetchone()
            out["last_ok_ms"] = int(ok[0]) if ok[0] is not None else None
            err = c.execute("SELECT error FROM outbox WHERE sent_ms IS NULL AND error IS NOT NULL AND id > ? "
                            "ORDER BY id DESC LIMIT 1", (ok[1] or 0,)).fetchone()
            out["last_error"] = err[0] if err else None
        except sqlite3.Error as exc:
            out["last_error"] = f"db: {type(exc).__name__}"
        return out


# ---------------------------------------------------------------- CLI
def read_env_file(path: str, keys=("DEMOBOT_TG_TOKEN", "DEMOBOT_TG_CHAT")) -> dict:
    """KEY=VALUE lines of the env file (quotes removed), only ``keys``; {} when it cannot be read."""
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, _, v = ln.partition("=")
                k, v = k.strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                if k in keys:
                    out[k] = v
    except OSError:
        return {}
    return out


def credentials(env_file: str = ENV_FILE, env=None) -> tuple:
    """(token, chat): the environment first, else the env file."""
    env = os.environ if env is None else env
    token, chat = (env.get("DEMOBOT_TG_TOKEN") or "").strip(), (env.get("DEMOBOT_TG_CHAT") or "").strip()
    if not token or not chat:
        f = read_env_file(env_file)
        token = token or f.get("DEMOBOT_TG_TOKEN", "").strip()
        chat = chat or f.get("DEMOBOT_TG_CHAT", "").strip()
    return token, chat


EDIT = "SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env"


def _hint(err: str) -> str:
    e = err.lower()
    if "401" in e or "unauthorized" in e:
        return "토큰이 틀렸습니다. BotFather의 토큰을 편집기 안에서 다시 넣으세요: " + EDIT
    if "chat not found" in e or "400" in e:
        return "방 번호가 틀렸거나 봇이 그 방에 없습니다. python -m demobot.notify chatid 로 번호를 다시 찾으세요."
    if "403" in e or "kicked" in e or "not a member" in e:
        return "봇이 그 방에서 빠졌습니다. 봇을 단체방에 다시 넣으세요."
    return "서버의 인터넷 연결을 확인하고 잠시 뒤 다시 실행하세요."


def cmd_test(token: str, chat: str, send=send_message, out=print) -> int:
    if not token:
        out(f"DEMOBOT_TG_TOKEN이 비어 있습니다. 편집기 안에서 넣으세요: {EDIT}")
        return 2
    if not chat:
        out("DEMOBOT_TG_CHAT이 비어 있습니다. 먼저 방 번호를 찾으세요: python -m demobot.notify chatid")
        return 2
    text = f"{TEST_TEXT}\n이 방으로 데모 랩 알림이 옵니다 (모의 거래만, 주문 없음)\n{kst(int(time.time() * 1000))}"
    try:
        send(token, chat, text)
    except Exception as exc:  # noqa: BLE001
        err = redact(str(exc), token)
        out(f"보내지 못했습니다: {err}")
        out(_hint(err))
        return 1
    out("보냈습니다. 텔레그램 단체방을 확인하세요.")
    return 0


def chats_from_updates(updates) -> dict:
    """{chat id: (title, type, new id or None)} of the chats in getUpdates' result, the latest last."""
    seen: dict = {}
    for u in updates or []:
        if not isinstance(u, dict):
            continue
        for key in ("message", "edited_message", "channel_post", "my_chat_member", "chat_member"):
            m = u.get(key)
            chat = m.get("chat") if isinstance(m, dict) else None
            if not isinstance(chat, dict) or "id" not in chat:
                continue
            title = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
            moved = m.get("migrate_to_chat_id")
            prev = seen.pop(chat["id"], None)
            seen[chat["id"]] = (title or "?", chat.get("type", "?"), moved or (prev[2] if prev else None))
    return seen


def cmd_chatid(token: str, call=api, out=print) -> int:
    out("텔레그램 방 번호 찾기 (토큰은 화면에 내지 않습니다)")
    out("먼저: 새 단체방을 만들고 이 봇을 넣은 뒤, 그 방에 메시지를 하나 보내세요 (/start@봇아이디 가 가장 확실합니다).")
    if not token:
        out(f"DEMOBOT_TG_TOKEN이 비어 있습니다. 편집기 안에서 넣으세요: {EDIT}")
        return 2
    try:
        me = call(token, "getMe", {}) or {}
        if me.get("username"):
            out(f"이 봇의 아이디: @{me['username']}  (방에 보낼 것: /start@{me['username']})")
        updates = call(token, "getUpdates", {"limit": "100", "timeout": "0"}) or []
    except Exception as exc:  # noqa: BLE001
        err = redact(str(exc), token)
        out(f"텔레그램에 묻지 못했습니다: {err}")
        if "409" in err:
            out("이 봇에 webhook이 걸려 있습니다. 새로 만든 봇을 쓰세요 (규칙봇의 봇은 쓰지 않습니다).")
        else:
            out(_hint(err))
        return 1
    seen = chats_from_updates(updates)
    if not seen:
        out("")
        out("최근 메시지가 없습니다. 봇을 단체방에 넣고 그 방에 /start@봇아이디 를 보낸 뒤 다시 실행하세요.")
        out("(텔레그램은 지난 24시간 메시지만 보여 줍니다)")
        return 0
    out("")
    order = sorted(seen.items(), key=lambda kv: kv[1][1] not in ("group", "supergroup"))
    for cid, (title, kind, moved) in order:
        line = f"방 번호 {cid}   이름 {title}   ({kind})"
        if moved:
            line += f"   -> 번호가 {moved} 로 바뀜: 이 새 번호를 쓰세요"
        out(line)
    out("")
    out("데모 랩 단체방의 번호(보통 -100으로 시작)를 DEMOBOT_TG_CHAT= 뒤에 넣습니다:")
    out(f"  {EDIT}")
    out("규칙봇 알림방의 번호와 달라야 합니다. 넣은 뒤: python -m demobot.notify test")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demobot.notify",
                                 description="demo lab Telegram: send a test message, or find the group's chat id")
    ap.add_argument("cmd", choices=["test", "chatid"])
    ap.add_argument("--env-file", default=ENV_FILE,
                    help="read DEMOBOT_TG_TOKEN / DEMOBOT_TG_CHAT from here when they are not in the environment")
    a = ap.parse_args(argv)
    token, chat = credentials(a.env_file)
    if a.cmd == "test":
        return cmd_test(token, chat)
    return cmd_chatid(token)


if __name__ == "__main__":
    sys.exit(main())
