"""The 24-hour debate room: a separate, paid-API service (NOT the agent rooms; docs/debate-room.md).

    python -m paperbot.agents.debate run                 # the loop (systemd: deploy/paperbot-debate.service)
    python -m paperbot.agents.debate once [--dry-run]    # one round now; --dry-run: packet + token and cost estimate,
                                                         # no API call, no key needed (run this before paying)
    python -m paperbot.agents.debate status [--json]     # what the service did, spend against the cap, hit rates

What it is: every DEBATE_EVERY_MIN minutes (default 20) ONE call to the Anthropic Messages API (standard library only,
``urllib``) returns a short Korean debate (3-5 turns by rotating roles) plus a note, 0-2 gradable hypotheses and 0-2
ideas for the new-strategy lab. The input is a compact packet code builds from the bot's databases, READ-ONLY
(debate_packet.py). What it is not: it never places an order, never edits a rule, an account or code, and writes
nothing to any bot database; its only writable file is its own debate.db (this process is its only writer; the
dashboard reads it read-only). It runs on the owners' own paid API key, which only this service's env file
(/etc/paperbot/debate.env, readable by user paperbot-debate only) holds. The agent rooms run on the Claude Max
subscription and never see that key (runner.ENV_ALLOW has no ANTHROPIC_API_KEY; a test keeps it so).

Money: cost comes from the API's own usage fields (prices below, overridable by env), counted per call in debate_state
by KST day and month. A warning at 80% of DEBATE_MONTHLY_USD_CAP, no more calls from 95% (resumes next month, or after
the cap is raised and the service restarted), and a round is never started when its worst case would pass the cap. An
hourly guard stops a runaway loop. A round whose picture did not change (fewer than DEBATE_MIN_NEW_TRADES new closed
trades, no new alert, no new nightly report) is skipped and recorded as 'skipped', costing nothing.

Failures never crash-loop: an auth / credit / rate / server / network error is recorded in debate_rounds, the service
backs off exponentially (1 min up to 30 min, a 429's retry-after respected), sends ONE Korean Telegram warning per cause
per hour and ONE note when it recovers. The key is read only from the environment, is never logged or stored, and is
redacted from every error text. SIGTERM finishes the call in progress, commits and exits.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import debate_grade as G
from . import debate_packet as P

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
KST_MS = 9 * HOUR_MS
PROMPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts3", "debate_room.md")
DEFAULT_DIR = "/var/lib/paperbot/debate"
ROLES = ("낙관론자", "비관론자", "회의론자", "리스크 책임자", "퀀트")
STANCE = {"낙관론자": "낙관", "비관론자": "비관", "회의론자": "검증", "리스크 책임자": "리스크", "퀀트": "퀀트"}
NOTE_SPEAKER, NOTE_STANCE = "정리", "정리"
MAX_TURN_CHARS, MAX_NOTE_CHARS, MAX_IDEA_CHARS = 700, 500, 300
KEEP_MESSAGES_DAYS, KEEP_ROUNDS_DAYS, KEEP_HYP_DAYS, KEEP_IDEA_DAYS = 60, 120, 120, 180
WARN_EVERY_MS = HOUR_MS                    # one Telegram warning per cause per hour
BACKOFF_FIRST_S, BACKOFF_MAX_S = 60, 30 * 60
HEARTBEAT_STALE_S = 300                    # the loop beats every <= 30 s (a round takes < 3 min): older = the service is off
SLICE_S = 5.0                              # the loop's sleep slice (stop flag, heartbeat)
GRADE_EVERY_MS = 10 * 60_000
FORCE_AFTER_MS = 6 * HOUR_MS               # never skip for longer than this: one round runs anyway

# USD per million tokens. Built-in guesses by model family; the owners' env (DEBATE_PRICE_IN / DEBATE_PRICE_OUT)
# wins. They must be re-checked in the Anthropic console: a wrong constant only mis-states the cost counter,
# the real bill is the console's, and the owners' hard limit there is the real stop.
PRICES = {"haiku": (1.0, 5.0), "sonnet": (2.0, 10.0), "opus": (4.0, 20.0)}
UNKNOWN_PRICE = (5.0, 25.0)                # an unknown model: counted high on purpose
CACHE_READ_MULT, CACHE_WRITE_5M_MULT, CACHE_WRITE_1H_MULT = 0.1, 1.25, 2.0
CACHE_MIN_TOKENS = {"haiku": 4096}         # shorter prefixes are silently not cached (others: check the docs)


# ---------------------------------------------------------------- redaction, time, flags
KEY_PATTERNS = (re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"), re.compile(r"x-api-key\W{0,4}[A-Za-z0-9_\-]{12,}", re.I))


def redact(text: Any, key: str = "") -> str:
    """``text`` with the API key (and anything shaped like one) replaced by ***. Applied to every error text."""
    s = str(text)
    if key and len(key) >= 6:
        s = s.replace(key, "***")
    for pat in KEY_PATTERNS:
        s = pat.sub("***", s)
    return s


def kst_day(ms: int) -> str:
    return G.kst_day(ms)


def kst_month(ms: int) -> str:
    return G.kst_day(ms)[:7]


def _now_ms() -> int:
    return int(time.time() * 1000)


class StopFlag:
    """A stop request set from a signal handler. No lock is taken in the handler (``threading.Event.set`` takes one and
    a SIGTERM landing while the main thread waits on it could deadlock; paperbot/live3.py's StopFlag, same reason)."""

    def __init__(self) -> None:
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float, slice_s: float = 0.25) -> bool:
        end = time.monotonic() + max(0.0, float(timeout))
        while not self._set:
            left = end - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(slice_s, left))
        return self._set


def stop_on_sigterm() -> tuple[StopFlag, Callable[[], None]]:
    stop = StopFlag()
    try:
        prev_t = signal.signal(signal.SIGTERM, lambda *_: stop.set())
        prev_i = signal.signal(signal.SIGINT, lambda *_: stop.set())
    except ValueError:                         # not the main thread (tests)
        return stop, lambda: None

    def restore() -> None:
        signal.signal(signal.SIGTERM, prev_t)
        signal.signal(signal.SIGINT, prev_i)
    return stop, restore


# ---------------------------------------------------------------- configuration (environment only)
@dataclass
class Config:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    every_min: int = 20
    monthly_cap: float = 40.0
    hourly_cap: float = 0.0            # 0 = cap / 24
    daily_cap: float = 0.0             # 0 = off
    turns: int = 4
    max_tokens: int = 900
    price_in: float = 0.0              # 0 = by model family
    price_out: float = 0.0
    min_new_trades: int = 10
    est_out_tokens: int = 800
    thinking: str = ""                 # "" = not sent; e.g. between_tools for Sonnet 5.5 (see docs)
    effort: str = ""                   # "" = not sent; low | medium | high
    timeout_s: float = 45.0
    retries: int = 2                   # inside one round (429 / 5xx / network); then the service backs off
    paper_db: str = "/var/lib/paperbot/paper3.db"
    daily_db: str = "/var/lib/paperbot/daily3.db"
    agents_db: str = "/var/lib/paperbot/agents3.db"
    checkpoint_db: str = "/var/lib/paperbot/checkpoint.db"
    debate_dir: str = DEFAULT_DIR

    @property
    def debate_db(self) -> str:
        return os.path.join(self.debate_dir, "debate.db")

    def prices(self) -> tuple[float, float]:
        fam = next((k for k in PRICES if k in self.model.lower()), None)
        base = PRICES.get(fam, UNKNOWN_PRICE)
        return (self.price_in or base[0], self.price_out or base[1])

    def hourly(self) -> float:
        return self.hourly_cap or self.monthly_cap / 24.0

    def cache_ttl(self) -> Optional[str]:
        """The cache lifetime worth paying for at this interval: 5 minutes only for rounds under 4 minutes apart, one
        hour (writes cost 2x, reads 0.1x) up to 50 minutes apart, none beyond (the cache would expire unread)."""
        if self.every_min <= 4:
            return "5m"
        return "1h" if self.every_min <= 50 else None


def _num(env: dict, name: str, default, lo: float, hi: float, kind=float):
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = kind(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r}: 숫자가 아닙니다") from None
    if not lo <= v <= hi:
        raise ValueError(f"{name}={raw}: {lo:g}~{hi:g} 사이여야 합니다")
    return v


def config_from_env(environ: Optional[dict] = None) -> Config:
    """Settings from the environment (the unit's EnvironmentFile). A bad value raises ValueError (the service then
    exits with status 2 and is not restarted); the key is only read here and never echoed."""
    env = os.environ if environ is None else environ
    c = Config(api_key=str(env.get("ANTHROPIC_API_KEY") or "").strip())
    c.model = str(env.get("DEBATE_MODEL") or "").strip() or DEFAULT_MODEL
    c.every_min = _num(env, "DEBATE_EVERY_MIN", c.every_min, 1, 1440, int)
    c.monthly_cap = _num(env, "DEBATE_MONTHLY_USD_CAP", c.monthly_cap, 0.5, 100000)
    c.hourly_cap = _num(env, "DEBATE_HOURLY_USD_CAP", 0.0, 0.0, 10000)
    c.daily_cap = _num(env, "DEBATE_DAILY_USD_CAP", 0.0, 0.0, 10000)
    c.turns = _num(env, "DEBATE_TURNS", c.turns, 3, 5, int)
    c.max_tokens = _num(env, "DEBATE_MAX_TOKENS", c.max_tokens, 300, 2000, int)
    c.price_in = _num(env, "DEBATE_PRICE_IN", 0.0, 0.0, 1000)
    c.price_out = _num(env, "DEBATE_PRICE_OUT", 0.0, 0.0, 1000)
    c.min_new_trades = _num(env, "DEBATE_MIN_NEW_TRADES", c.min_new_trades, 0, 100000, int)
    c.est_out_tokens = _num(env, "DEBATE_EST_OUT_TOKENS", c.est_out_tokens, 100, 4000, int)
    c.thinking = str(env.get("DEBATE_THINKING") or "").strip()
    c.effort = str(env.get("DEBATE_EFFORT") or "").strip()
    if c.thinking not in ("", "disabled", "adaptive", "between_tools"):
        raise ValueError(f"DEBATE_THINKING={c.thinking!r}: 비우거나 disabled / adaptive / between_tools")
    if c.effort not in ("", "low", "medium", "high"):
        raise ValueError(f"DEBATE_EFFORT={c.effort!r}: 비우거나 low / medium / high")
    for attr, name in (("paper_db", "DEBATE_PAPER_DB"), ("daily_db", "DEBATE_DAILY_DB"),
                       ("agents_db", "DEBATE_AGENTS_DB"), ("checkpoint_db", "DEBATE_CHECKPOINT_DB"),
                       ("debate_dir", "DEBATE_DIR")):
        v = str(env.get(name) or "").strip()
        if v:
            setattr(c, attr, v)
    return c


# ---------------------------------------------------------------- the database (this service is its only writer)
SCHEMA = """
CREATE TABLE IF NOT EXISTS debate_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    round_id INTEGER,
    speaker TEXT NOT NULL,
    stance TEXT,
    topic TEXT,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS debate_messages_round ON debate_messages (round_id);
CREATE TABLE IF NOT EXISTS debate_rounds (
    round_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    topic TEXT,
    in_tokens INTEGER NOT NULL DEFAULT 0,
    out_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read INTEGER NOT NULL DEFAULT 0,
    cache_write INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT,
    model TEXT,
    turns INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS debate_rounds_ts ON debate_rounds (ts);
CREATE TABLE IF NOT EXISTS debate_hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER,
    ts INTEGER NOT NULL,
    speaker TEXT,
    kind TEXT,
    params_json TEXT,
    horizon TEXT,
    status TEXT NOT NULL,
    outcome TEXT,
    graded_ts INTEGER
);
CREATE INDEX IF NOT EXISTS debate_hypotheses_status ON debate_hypotheses (status, id);
CREATE TABLE IF NOT EXISTS debate_ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER,
    ts INTEGER NOT NULL,
    text TEXT NOT NULL,
    tag TEXT,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS debate_state (k TEXT PRIMARY KEY, v TEXT);
"""


class DB:
    """debate.db. Rollback-journal mode (not WAL) on purpose: the dashboard, another user, reads it read-only and a WAL
    file would need a writable -shm for it."""

    def __init__(self, path: str):
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, timeout=10)
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    def get(self, k: str, default: Any = None) -> Any:
        r = self.conn.execute("SELECT v FROM debate_state WHERE k = ?", (k,)).fetchone()
        if r is None:
            return default
        try:
            return json.loads(r[0])
        except (TypeError, ValueError):
            return default

    def put(self, k: str, v: Any, commit: bool = True) -> None:
        self.conn.execute("INSERT INTO debate_state (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                          (k, json.dumps(v, ensure_ascii=False)))
        if commit:
            self.conn.commit()

    def delete(self, k: str) -> None:
        self.conn.execute("DELETE FROM debate_state WHERE k = ?", (k,))
        self.conn.commit()

    # -- spend counters (USD, KST day and month)
    def spent(self, now_ms: int) -> dict:
        return {"day": float(self.get(f"spend:day:{kst_day(now_ms)}", 0.0)),
                "month": float(self.get(f"spend:month:{kst_month(now_ms)}", 0.0))}

    def add_spend(self, now_ms: int, usd: float) -> None:
        for k in (f"spend:day:{kst_day(now_ms)}", f"spend:month:{kst_month(now_ms)}"):
            self.put(k, round(float(self.get(k, 0.0)) + float(usd), 6), commit=False)
        self.conn.commit()

    def hour_spend(self, now_ms: int) -> float:
        r = self.conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM debate_rounds WHERE ts > ?",
                              (now_ms - HOUR_MS,)).fetchone()
        return float(r[0] or 0.0)

    def prune(self, now_ms: int) -> None:
        c = self.conn
        c.execute("DELETE FROM debate_messages WHERE ts < ?", (now_ms - KEEP_MESSAGES_DAYS * DAY_MS,))
        c.execute("DELETE FROM debate_rounds WHERE ts < ?", (now_ms - KEEP_ROUNDS_DAYS * DAY_MS,))
        c.execute("DELETE FROM debate_hypotheses WHERE ts < ? AND status != 'open'", (now_ms - KEEP_HYP_DAYS * DAY_MS,))
        c.execute("DELETE FROM debate_ideas WHERE ts < ?", (now_ms - KEEP_IDEA_DAYS * DAY_MS,))
        old = kst_month(now_ms - 400 * DAY_MS)
        c.execute("DELETE FROM debate_state WHERE (k LIKE 'spend:month:%' AND substr(k, 13) < ?) "
                  "OR (k LIKE 'spend:day:%' AND substr(k, 11) < ?)", (old, kst_day(now_ms - 400 * DAY_MS)))
        c.commit()


# ---------------------------------------------------------------- the API call (standard library only)
class ApiError(Exception):
    """A failed call. ``kind``: auth (401/403) | credit (balance too low) | rate (429) | server (5xx) | network |
    bad_request (any other 4xx) | output (a 200 whose answer could not be used). The text never holds the key."""

    def __init__(self, kind: str, message: str, status: int = 0, retry_after: float = 0.0, usage: Optional[dict] = None):
        super().__init__(message)
        self.kind, self.status, self.retry_after, self.usage = kind, status, retry_after, usage


Transport = Callable[[str, dict, bytes, float], tuple]     # (url, headers, body, timeout) -> (status, headers, body)


def urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple:
    """POST with urllib. An HTTP error answer is returned (status, headers, body); a network failure raises OSError."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (fixed https host)
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read()
    except urllib.error.URLError as e:
        raise OSError(str(getattr(e, "reason", "network error"))) from None


def classify(status: int, body: bytes, headers: dict, key: str) -> ApiError:
    """The ApiError for a non-200 answer."""
    msg, etype = "", ""
    try:
        err = (json.loads(body) or {}).get("error") or {}
        msg, etype = str(err.get("message") or ""), str(err.get("type") or "")
    except (TypeError, ValueError, AttributeError):
        pass
    low = (msg + " " + etype).lower()
    ra = 0.0
    try:
        ra = float(headers.get("retry-after") or 0)
    except (TypeError, ValueError):
        ra = 0.0
    text = redact(f"HTTP {status} {etype}: {msg}"[:240], key)
    if status in (401, 403):
        return ApiError("auth", text, status)
    if status == 402 or "credit balance" in low or "credit_balance" in low:
        return ApiError("credit", text, status)
    if status == 429:
        return ApiError("rate", text, status, retry_after=ra)
    if status >= 500 or etype == "overloaded_error":
        return ApiError("server", text, status, retry_after=ra)
    return ApiError("bad_request", text, status)


def request_body(cfg: Config, system_text: str, user_text: str) -> dict:
    sys_block: dict = {"type": "text", "text": system_text}
    ttl = cfg.cache_ttl()
    if ttl:
        sys_block["cache_control"] = {"type": "ephemeral", **({"ttl": "1h"} if ttl == "1h" else {})}
    body: dict = {"model": cfg.model, "max_tokens": cfg.max_tokens, "system": [sys_block],
                  "messages": [{"role": "user", "content": user_text}]}
    if cfg.thinking:
        body["thinking"] = {"type": cfg.thinking}
    if cfg.effort:
        body["output_config"] = {"effort": cfg.effort}
    return body


def call_api(cfg: Config, system_text: str, user_text: str, transport: Transport = urllib_transport,
             sleep: Callable[[float], Any] = time.sleep, stop: Optional[StopFlag] = None) -> dict:
    """One Messages API request with a few bounded retries (429 / 5xx / network: waits 2 s, 6 s, honouring a
    retry-after up to 60 s). Returns {"text", "usage", "stop_reason", "request_id"}; raises ApiError."""
    body = json.dumps(request_body(cfg, system_text, user_text), ensure_ascii=False).encode()
    headers = {"x-api-key": cfg.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
    last: Optional[ApiError] = None
    for attempt in range(cfg.retries + 1):
        if attempt:
            wait = min(60.0, max(last.retry_after if last else 0.0, (2.0, 6.0, 15.0)[min(attempt - 1, 2)]))
            left = wait
            while left > 0 and not (stop is not None and stop.is_set()):
                sleep(min(1.0, left))                      # in short slices: a stop request is seen within a second
                left -= 1.0
            if stop is not None and stop.is_set():
                raise last or ApiError("network", "중단 요청")
        try:
            status, hdrs, raw = transport(API_URL, headers, body, cfg.timeout_s)
        except (OSError, TimeoutError) as exc:
            last = ApiError("network", redact(f"{type(exc).__name__}: {exc}"[:200], cfg.api_key))
            continue
        if status != 200:
            last = classify(status, raw, hdrs, cfg.api_key)
            if last.kind in ("rate", "server"):
                continue
            raise last
        try:
            data = json.loads(raw)
        except ValueError:
            raise ApiError("server", "200인데 답이 JSON이 아님", 200) from None
        text = "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict) and b.get("type") == "text")
        return {"text": text, "usage": data.get("usage") or {}, "stop_reason": data.get("stop_reason"),
                "request_id": hdrs.get("request-id")}
    assert last is not None
    raise last


def cost_of(usage: dict, cfg: Config) -> float:
    """USD from the API's usage fields: input, output, cache reads (0.1x) and cache writes (1.25x for 5 minutes, 2x
    for one hour: the split is read from ``usage.cache_creation`` when present)."""
    pin, pout = cfg.prices()
    g = lambda k: int(usage.get(k) or 0)          # noqa: E731
    cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else None
    if cc:
        w5, w1 = int(cc.get("ephemeral_5m_input_tokens") or 0), int(cc.get("ephemeral_1h_input_tokens") or 0)
    else:
        w = g("cache_creation_input_tokens")
        w5, w1 = (0, w) if cfg.cache_ttl() == "1h" else (w, 0)
    usd = (g("input_tokens") * pin + g("output_tokens") * pout + g("cache_read_input_tokens") * pin * CACHE_READ_MULT
           + w5 * pin * CACHE_WRITE_5M_MULT + w1 * pin * CACHE_WRITE_1H_MULT) / 1e6
    return round(usd, 6)


# ---------------------------------------------------------------- prompts and the answer
def system_text() -> str:
    """The stable prefix: rules, roles, output format and the hypothesis menu (the same bytes every round)."""
    with open(PROMPT, encoding="utf-8") as fh:
        return fh.read().rstrip() + "\n\n## 가설 메뉴\n" + G.MENU_KO + "\n"


def roles_for(round_no: int, n: int) -> list[str]:
    """The speaking order of this round: the roles rotate, starting one place further each round."""
    return [ROLES[(round_no + i) % len(ROLES)] for i in range(n)]


def user_text(packet: dict, topic_ko: str, why: str, round_no: int, order: list[str]) -> str:
    return (f"회차 {round_no}번. 주제: {topic_ko} ({why})\n발언 순서(이 순서 그대로, {len(order)}명): {', '.join(order)}\n"
            f"아래는 이번 회차 자료(JSON)입니다.\n{P.compact_json(packet)}")


TURN_RE = re.compile(r'\{\s*"speaker"\s*:\s*"([^"\\]*)"\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}')


def _salvage_turns(s: str) -> list:
    """The complete {"speaker", "text"} objects of an answer that was cut off (max_tokens): what was paid for is kept."""
    out = []
    for sp, tx in TURN_RE.findall(s):
        try:
            out.append({"speaker": sp, "text": json.loads('"' + tx + '"')})
        except ValueError:
            continue
    return out


def parse_answer(text: str, order: list[str]) -> dict:
    """The model's JSON answer, checked: {"turns": [{"speaker", "text"}], "note", "hypotheses": [...], "ideas": [...],
    "truncated": bool}. A cut-off answer keeps its complete turns (no note, hypotheses or ideas). Raises
    ApiError('output') when nothing usable is left."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    obj: Any = None
    try:
        obj = json.loads(s)
    except ValueError:
        i, j = s.find("{"), s.rfind("}")
        try:
            obj = json.loads(s[i:j + 1]) if 0 <= i < j else None
        except ValueError:
            obj = None
    truncated = False
    if not isinstance(obj, dict) or not isinstance(obj.get("turns"), list):
        got = _salvage_turns(s)
        if not got:
            raise ApiError("output", "답이 약속한 JSON 모양이 아님(잘렸거나 설명이 섞임)")
        obj, truncated = {"turns": got}, True
    turns = []
    for t in obj["turns"][:5]:
        if not isinstance(t, dict) or not isinstance(t.get("text"), str) or not t["text"].strip():
            continue
        sp = t.get("speaker") if t.get("speaker") in ROLES else (order[len(turns)] if len(turns) < len(order) else None)
        if sp is None:
            continue
        turns.append({"speaker": sp, "text": " ".join(t["text"].split())[:MAX_TURN_CHARS]})
    if len(turns) < 2:
        raise ApiError("output", "토론 발언이 2개 미만")
    note = " ".join(str(obj.get("note") or "").split())[:MAX_NOTE_CHARS]
    ideas = []
    for it in (obj.get("ideas") if isinstance(obj.get("ideas"), list) else [])[:2]:
        if isinstance(it, dict) and isinstance(it.get("text"), str) and it["text"].strip():
            ideas.append({"text": " ".join(it["text"].split())[:MAX_IDEA_CHARS],
                          "tag": " ".join(str(it.get("tag") or "").split())[:40]})
    hyps = obj.get("hypotheses") if isinstance(obj.get("hypotheses"), list) else []
    return {"turns": turns, "note": note, "ideas": ideas, "hypotheses": hyps, "truncated": truncated}


# ---------------------------------------------------------------- the service
CAUSE_KO = {
    "auth": "API 키가 거부됐습니다(401/403) — 키를 확인해 debate.env에 다시 넣고 서비스를 다시 시작하세요",
    "credit": "API 잔액 부족 — 콘솔에서 충전하면 저절로 이어집니다",
    "rate": "요청이 너무 잦다는 답(429)을 받았습니다 — 잠시 쉬었다가 이어집니다",
    "server": "Anthropic 서버 오류 — 잠시 쉬었다가 이어집니다",
    "network": "인터넷 연결 오류 — 연결되면 저절로 이어집니다",
    "bad_request": "요청이 거절됐습니다(모델 이름 등 설정 확인) — journalctl -u paperbot-debate 를 보세요",
    "output": "AI 답을 읽을 수 없는 일이 계속됩니다 — 잠시 쉬었다가 이어집니다",
    "packet": "봇 데이터를 읽지 못했습니다(paper3.db 등) — 잠시 쉬었다가 이어집니다",
    "no_key": "API 키가 없습니다 — /etc/paperbot/debate.env 에 ANTHROPIC_API_KEY 를 넣고 서비스를 다시 시작하세요",
    "cap": "이번 달 사용 한도에 거의 닿아 멈췄습니다 — 다음 달에 저절로 이어지거나, 한도를 올리고 다시 시작하세요",
}


class Service:
    def __init__(self, cfg: Config, db: DB, notifier: Any = None, transport: Transport = urllib_transport,
                 clock: Callable[[], int] = _now_ms, stop: Optional[StopFlag] = None,
                 sleep: Callable[[float], Any] = time.sleep, out: Callable[[str], Any] = None):
        self.cfg, self.db, self.notifier = cfg, db, notifier
        self.transport, self.clock = transport, clock
        self.stop = stop or StopFlag()
        self.sleep = sleep
        self.out = out or (lambda s: print(s, flush=True))
        self._system: Optional[str] = None
        self.beat_s = SLICE_S * 6                   # seconds between two passes of the loop (tests make it short)

    # -- small helpers
    def log(self, msg: str) -> None:
        self.out(redact(msg, self.cfg.api_key))

    def notify(self, level: str, text: str) -> None:
        if self.notifier is None:
            return
        try:
            self.notifier.send(level, redact(text, self.cfg.api_key))
        except Exception as exc:  # noqa: BLE001  (a message that cannot be sent never stops the service)
            self.log(f"telegram send failed: {type(exc).__name__}")

    def system(self) -> str:
        if self._system is None:
            self._system = system_text()
        return self._system

    def beat(self, now: Optional[int] = None) -> None:
        self.db.put("heartbeat", self.clock() if now is None else now)

    def set_run_state(self, state: str, reason: str = "", now: Optional[int] = None) -> None:
        now = self.clock() if now is None else now
        self.db.put("run", {"state": state, "reason": reason[:200], "ts": now, "model": self.cfg.model,
                            "every_min": self.cfg.every_min, "cap": self.cfg.monthly_cap}, commit=False)
        self.db.put("heartbeat", now)

    # -- outage bookkeeping: one WARN per cause per hour, one INFO on recovery
    def fail(self, cause: str, detail: str, now: int, retry_after: float = 0.0) -> None:
        level = int(self.db.get("backoff:level", 0))
        wait = min(BACKOFF_MAX_S, BACKOFF_FIRST_S * (2 ** level))
        wait = min(BACKOFF_MAX_S, max(wait, retry_after))
        self.db.put("backoff:level", level + 1, commit=False)
        self.db.put("backoff:until", now + int(wait * 1000), commit=False)
        self.db.put("fail:cause", cause, commit=False)
        last = int(self.db.get(f"warn:{cause}", 0))
        if now - last >= WARN_EVERY_MS:
            self.db.put(f"warn:{cause}", now, commit=False)
            self.db.put("fail:warned", True, commit=False)
            self.notify("WARN", f"⚠ 24시간 토론방 멈춤: {CAUSE_KO.get(cause, cause)}")
        self.set_run_state("paused", CAUSE_KO.get(cause, cause), now)
        self.db.conn.commit()
        self.log(f"debate: {cause}: {detail} (다음 시도 {int(wait)}초 뒤)")

    def recovered(self, now: int) -> None:
        if self.db.get("fail:cause"):
            if self.db.get("fail:warned"):
                self.notify("INFO", "24시간 토론방 다시 시작: 이어서 토론합니다")
            for k in ("fail:cause", "fail:warned", "backoff:until"):
                self.db.delete(k)
            self.db.put("backoff:level", 0)

    # -- guards
    def worst_case_usd(self, in_tokens: int) -> float:
        pin, pout = self.cfg.prices()
        return (in_tokens * pin * CACHE_WRITE_1H_MULT + self.cfg.max_tokens * pout) / 1e6

    def check_cap(self, now: int, in_tokens: int = 0) -> Optional[str]:
        """None when a round may start, else why not ('cap' = month limit, 'hour' / 'day' = rate guards)."""
        sp, cap = self.db.spent(now), self.cfg.monthly_cap
        month = kst_month(now)
        if sp["month"] >= 0.8 * cap and not self.db.get(f"warn80:{month}:{cap:g}"):
            self.db.put(f"warn80:{month}:{cap:g}", now)
            self.notify("WARN", f"⚠ 24시간 토론방: 이번 달 AI 사용액이 한도의 80%입니다 (${sp['month']:.2f} / ${cap:g}). "
                                "95%가 되면 멈춥니다")
        if sp["month"] >= 0.95 * cap or sp["month"] + self.worst_case_usd(in_tokens) > cap:
            if not self.db.get(f"warn95:{month}:{cap:g}"):
                self.db.put(f"warn95:{month}:{cap:g}", now)
                self.notify("WARN", f"⚠ 24시간 토론방 멈춤: 이번 달 한도에 닿았습니다 (${sp['month']:.2f} / ${cap:g}). "
                                    "다음 달에 저절로 이어집니다. 지금 이어가려면 한도를 올리고 서비스를 다시 시작하세요")
            return "cap"
        if self.cfg.daily_cap and sp["day"] >= self.cfg.daily_cap:
            return "day"
        if self.db.hour_spend(now) >= self.cfg.hourly():
            return "hour"
        return None

    # -- one round
    def due_ms(self) -> int:
        last = int(self.db.get("last_attempt", 0))
        nxt = last + self.cfg.every_min * 60_000 if last else 0
        return max(nxt, int(self.db.get("backoff:until", 0)))

    def _paths(self) -> tuple:
        c = self.cfg
        return c.paper_db, c.daily_db, c.agents_db, c.checkpoint_db

    def round_no(self) -> int:
        return int(self.db.get("round_seq", 0))

    def last_texts(self) -> tuple[list, list]:
        notes = [r[0] for r in self.db.conn.execute(
            "SELECT text FROM debate_messages WHERE stance = ? ORDER BY id DESC LIMIT 2", (NOTE_STANCE,))]
        turns = [f"{r[0]}: {r[1][:160]}" for r in self.db.conn.execute(
            "SELECT speaker, text FROM debate_messages WHERE stance != ? ORDER BY id DESC LIMIT 2", (NOTE_STANCE,))]
        return notes, turns[::-1]

    def record_round(self, now: int, status: str, topic: Optional[str] = None, error: Optional[str] = None,
                     usage: Optional[dict] = None, cost: float = 0.0, turns: int = 0) -> int:
        u = usage or {}
        cur = self.db.conn.execute(
            "INSERT INTO debate_rounds (ts, topic, in_tokens, out_tokens, cache_read, cache_write, cost_usd, status, "
            "error, model, turns) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (now, topic, int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0),
             int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0), cost, status,
             redact(error, self.cfg.api_key)[:300] if error else None, self.cfg.model, turns))
        self.db.conn.commit()
        return int(cur.lastrowid)

    def tick(self, force: bool = False, dry_run: bool = False) -> str:
        """One pass of the loop: returns what happened ('idle', 'round', 'skipped', 'paused', 'no_key', 'cap',
        'hour', 'day', 'error'). ``force``: ignore the schedule and the unchanged-picture skip."""
        now = self.clock()
        self.beat(now)
        if now - int(self.db.get("graded_at", 0)) >= GRADE_EVERY_MS:
            self.grade(now)
        if not self.cfg.api_key:
            self.set_run_state("no_key", CAUSE_KO["no_key"], now)
            self.db.conn.commit()
            last = int(self.db.get("warn:no_key", 0))
            if now - last >= WARN_EVERY_MS:
                self.db.put("warn:no_key", now)
                self.notify("WARN", f"⚠ 24시간 토론방 멈춤: {CAUSE_KO['no_key']}")
            return "no_key"
        if not force and now < self.due_ms():
            return "idle"
        # the picture: did anything relevant change since the last debate? (no API call, no packet build)
        fp = P.fingerprint(self.cfg.paper_db, self.cfg.daily_db)
        if not force:
            ch, why = P.changed(self.db.get("fp:last"), fp, self.cfg.min_new_trades)
            idle_ms = now - int(self.db.get("last_round_ok", 0))
            if not ch and idle_ms < FORCE_AFTER_MS:
                self.db.put("last_attempt", now, commit=False)
                self.record_round(now, "skipped", error=f"unchanged: {why}")
                return "skipped"
        why_cap = self.check_cap(now, in_tokens=0)
        if why_cap:
            reason = {"cap": CAUSE_KO["cap"], "hour": "시간당 사용 한도(안전장치)에 닿아 잠시 쉽니다",
                      "day": "하루 사용 한도에 닿아 오늘은 쉽니다"}[why_cap]
            self.set_run_state("paused", reason, now)
            self.db.put("last_attempt", now, commit=False)
            self.db.conn.commit()
            return why_cap
        return self.round(now, fp, dry_run=dry_run)

    def round(self, now: int, fp: dict, dry_run: bool = False) -> str:
        cfg = self.cfg
        n = self.round_no()
        notes, turns_prev = self.last_texts()
        recent = tuple(r[0] for r in self.db.conn.execute(
            "SELECT topic FROM debate_rounds WHERE status = 'ok' ORDER BY round_id DESC LIMIT 2"))
        key_of = {ko: k for k, ko in P.TOPIC_KO.items()}
        recent_keys = tuple(key_of.get(t, "") for t in recent)
        self.db.put("last_attempt", now, commit=False)
        try:
            built = P.build(*self._paths(), now, round_no=n, recent_topics=recent_keys,
                            last_notes=notes, last_turns=turns_prev, scoreboard=G.scoreboard(self.db.conn))
        except Exception as exc:  # noqa: BLE001  (a bot database that cannot be read is a state, not a crash)
            self.record_round(now, "error", error=f"packet: {type(exc).__name__}: {exc}")
            self.fail("packet", f"{type(exc).__name__}: {exc}", now)
            return "error"
        order = roles_for(n, cfg.turns)
        utext = user_text(built["packet"], built["topic_ko"], built["why"], n, order)
        in_est = P.estimate_tokens(self.system()) + P.estimate_tokens(utext)
        stop_cap = self.check_cap(now, in_tokens=in_est)
        if stop_cap:
            self.set_run_state("paused", CAUSE_KO["cap"] if stop_cap == "cap" else "사용 한도 안전장치", now)
            self.db.conn.commit()
            return stop_cap
        rid = self.record_round(now, "running", topic=built["topic_ko"])
        try:
            res = call_api(cfg, self.system(), utext, self.transport, self.sleep, self.stop)
        except ApiError as exc:
            self.finish_round(rid, "error", error=f"{exc.kind}: {exc}")
            self.fail(exc.kind, str(exc), self.clock(), exc.retry_after)
            return "error"
        t = self.clock()
        cost = cost_of(res["usage"], cfg)
        self.db.add_spend(t, cost)                         # the money is counted before the answer is used
        try:
            if res.get("stop_reason") == "refusal":
                raise ApiError("output", "stop_reason=refusal")
            ans = parse_answer(res["text"], order)
        except ApiError as exc:
            self.finish_round(rid, "error", error=f"{exc.kind}: {exc}", usage=res["usage"], cost=cost)
            bad = int(self.db.get("bad_output", 0)) + 1
            self.db.put("bad_output", bad)
            if bad >= 3:
                self.fail("output", str(exc), t)
            else:
                self.set_run_state("running", "", t)
                self.db.conn.commit()
            return "error"
        self.db.put("bad_output", 0, commit=False)
        self.store_answer(rid, t, built["topic_ko"], ans)
        self.finish_round(rid, "ok", usage=res["usage"], cost=cost, turns=len(ans["turns"]),
                          error="답이 잘려 일부만 씀(max_tokens)" if ans["truncated"] else None)
        self.db.put("round_seq", n + 1, commit=False)
        self.db.put("fp:last", fp, commit=False)
        self.db.put("last_round_ok", t, commit=False)
        self.db.put("last_usage", {"in": res["usage"].get("input_tokens"), "out": res["usage"].get("output_tokens"),
                                   "cache_read": res["usage"].get("cache_read_input_tokens"),
                                   "cache_write": res["usage"].get("cache_creation_input_tokens")}, commit=False)
        self.recovered(t)
        self.set_run_state("running", "", t)
        if int(self.db.get("pruned_at", 0)) + 6 * HOUR_MS < t:
            self.db.put("pruned_at", t, commit=False)
            self.db.prune(t)
        self.db.conn.commit()
        self.grade(t)
        self.log(f"debate: 회차 {n} 주제 '{built['topic_ko']}' 발언 {len(ans['turns'])}개, ${cost:.4f}")
        return "round"

    def finish_round(self, rid: int, status: str, error: Optional[str] = None, usage: Optional[dict] = None,
                     cost: float = 0.0, turns: int = 0) -> None:
        u = usage or {}
        self.db.conn.execute(
            "UPDATE debate_rounds SET status = ?, error = ?, in_tokens = ?, out_tokens = ?, cache_read = ?, "
            "cache_write = ?, cost_usd = ?, turns = ? WHERE round_id = ?",
            (status, redact(error, self.cfg.api_key)[:300] if error else None, int(u.get("input_tokens") or 0),
             int(u.get("output_tokens") or 0), int(u.get("cache_read_input_tokens") or 0),
             int(u.get("cache_creation_input_tokens") or 0), cost, turns, rid))
        self.db.conn.commit()

    def store_answer(self, rid: int, ts: int, topic: str, ans: dict) -> None:
        c = self.db.conn
        for t in ans["turns"]:
            c.execute("INSERT INTO debate_messages (ts, round_id, speaker, stance, topic, text) VALUES (?,?,?,?,?,?)",
                      (ts, rid, t["speaker"], STANCE.get(t["speaker"], ""), topic, t["text"]))
        if ans["note"]:
            c.execute("INSERT INTO debate_messages (ts, round_id, speaker, stance, topic, text) VALUES (?,?,?,?,?,?)",
                      (ts, rid, NOTE_SPEAKER, NOTE_STANCE, topic, ans["note"]))
        recent_ideas = {r[0] for r in c.execute("SELECT text FROM debate_ideas ORDER BY id DESC LIMIT 50")}
        for it in ans["ideas"]:
            if it["text"] not in recent_ideas:
                c.execute("INSERT INTO debate_ideas (round_id, ts, text, tag, status) VALUES (?,?,?,?, 'new')",
                          (rid, ts, it["text"], it["tag"]))
        paper, daily = P.open_ro(self.cfg.paper_db), P.open_ro(self.cfg.daily_db)
        try:
            n_open = c.execute("SELECT COUNT(*) FROM debate_hypotheses WHERE status = 'open'").fetchone()[0]
            for i, h in enumerate(ans["hypotheses"]):
                sp = h.get("speaker") if isinstance(h, dict) and h.get("speaker") in ROLES else "퀀트"
                raw = json.dumps(h, ensure_ascii=False)[:300]
                if i >= 2:
                    clean, why, horizon = None, "한 회차에 2개까지", ""
                elif n_open >= G.MAX_OPEN:
                    clean, why, horizon = None, f"열린 가설이 이미 {G.MAX_OPEN}개", ""
                else:
                    clean, why, horizon = G.validate(h, paper, daily, ts)
                if clean is None:
                    c.execute("INSERT INTO debate_hypotheses (round_id, ts, speaker, kind, params_json, horizon, status, "
                              "outcome, graded_ts) VALUES (?,?,?,?,?,?, 'dropped', ?, ?)",
                              (rid, ts, sp, str((h or {}).get("kind") if isinstance(h, dict) else "")[:40], raw, "",
                               why, ts))
                else:
                    n_open += 1
                    c.execute("INSERT INTO debate_hypotheses (round_id, ts, speaker, kind, params_json, horizon, status) "
                              "VALUES (?,?,?,?,?,?, 'open')", (rid, ts, sp, clean["kind"],
                                                               json.dumps(clean, ensure_ascii=False), horizon))
        finally:
            for x in (paper, daily):
                if x is not None:
                    x.close()
        c.commit()

    def grade(self, now: int) -> int:
        """Grade the open hypotheses whose horizon is reached (read-only on the bot databases; no API call)."""
        self.db.put("graded_at", now)
        paper, daily = P.open_ro(self.cfg.paper_db), P.open_ro(self.cfg.daily_db)
        try:
            n = G.grade_open(self.db.conn, paper, daily, now)
        except sqlite3.Error as exc:
            self.log(f"debate: grading skipped: {type(exc).__name__}")
            return 0
        finally:
            for x in (paper, daily):
                if x is not None:
                    x.close()
        self.db.conn.commit()
        return n

    # -- the loop
    def start(self) -> None:
        now = self.clock()
        self.db.conn.execute("UPDATE debate_rounds SET status = 'aborted', error = '서비스가 도중에 멈춤' "
                             "WHERE status = 'running'")
        self.db.conn.commit()
        self.db.prune(now)
        self.db.put("pruned_at", now)
        self.set_run_state("running", "", now)
        self.db.conn.commit()

    def run(self) -> int:
        self.start()
        self.log(f"debate: 시작 (모델 {self.cfg.model}, {self.cfg.every_min}분마다, 월 한도 ${self.cfg.monthly_cap:g})")
        while not self.stop.is_set():
            try:
                self.tick()
            except sqlite3.Error as exc:                  # a database hiccup is retried at the next beat
                self.log(f"debate: database error: {type(exc).__name__}")
            except Exception as exc:  # noqa: BLE001  (never crash-loop: log, wait, go on)
                self.log(f"debate: unexpected {type(exc).__name__}: {exc}")
                self.stop.wait(min(30, self.beat_s * 5))
            self.stop.wait(self.beat_s)
        self.db.close()
        self.log("debate: 멈춤 요청을 받아 정리하고 끝냅니다")
        return 0


# ---------------------------------------------------------------- the owners' view (status, dashboard, launchcheck)
STATE_KO = {"running": "돌고 있음", "paused": "멈춤", "no_key": "키 없음", "off": "꺼짐"}


def summary(debate_db: Optional[str], now_ms: Optional[int] = None, rounds: int = 12, hyps: int = 20,
            ideas: int = 15) -> dict:
    """Everything the dashboard, ``status`` and launchcheck show, from debate.db opened READ-ONLY. A missing file or
    table gives ``{"ready": False, "state": "off", ...}``: the service was never started."""
    now = _now_ms() if now_ms is None else now_ms
    out: dict = {"ready": False, "state": "off", "state_ko": STATE_KO["off"], "reason": "서비스가 켜져 있지 않거나 아직 시작한 적이 없습니다",
                 "rounds": [], "hypotheses": [], "ideas": [], "caution": CAUTION_KO}
    c = P.open_ro(debate_db)
    if c is None:
        return out
    try:
        st = {k: _loads(v) for k, v in c.execute("SELECT k, v FROM debate_state")}
        c.execute("SELECT 1 FROM debate_messages LIMIT 1")
        c.execute("SELECT 1 FROM debate_rounds LIMIT 1")
        run = st.get("run") if isinstance(st.get("run"), dict) else {}
        hb = int(st.get("heartbeat") or 0)
        cap = float(run.get("cap") or 0)
        month_key, day_key = kst_month(now), kst_day(now)
        month, day = float(st.get(f"spend:month:{month_key}") or 0), float(st.get(f"spend:day:{day_key}") or 0)
        every = int(run.get("every_min") or 0)
        state, reason = run.get("state") or "off", run.get("reason") or ""
        if not hb or now - hb > HEARTBEAT_STALE_S * 1000:
            state, reason = "off", "서비스가 멈춰 있거나 꺼져 있습니다 (마지막 신호 " + (_ago(now - hb) if hb else "없음") + ")"
        last_ok = c.execute("SELECT ts FROM debate_rounds WHERE status = 'ok' ORDER BY round_id DESC LIMIT 1").fetchone()
        last_any = c.execute("SELECT ts, status, error FROM debate_rounds ORDER BY round_id DESC LIMIT 1").fetchone()
        rows = c.execute("SELECT round_id, ts, topic, in_tokens, out_tokens, cache_read, cache_write, cost_usd, status, "
                         "error, model, turns FROM debate_rounds ORDER BY round_id DESC LIMIT ?", (rounds,)).fetchall()
        shown = []
        for r in rows:
            d = {k: r[k] for k in r.keys()}
            d["cost_usd"] = round(float(d["cost_usd"] or 0), 5)
            d["messages"] = [{"speaker": m["speaker"], "stance": m["stance"], "text": m["text"]} for m in c.execute(
                "SELECT speaker, stance, text FROM debate_messages WHERE round_id = ? ORDER BY id", (r["round_id"],))]
            shown.append(d)
        hy = [{k: r[k] for k in r.keys()} for r in c.execute(
            "SELECT id, round_id, ts, speaker, kind, horizon, status, outcome, graded_ts, params_json FROM "
            "debate_hypotheses ORDER BY id DESC LIMIT ?", (hyps,))]
        for h in hy:
            h["claim"] = G.claim_ko(h["kind"], h["params_json"])
            h["status_ko"] = G.status_ko(h["status"], h["outcome"])
            h["params_json"] = str(h["params_json"] or "")[:300] if h["status"] == "dropped" else ""
        idl = [{k: r[k] for k in r.keys()} for r in c.execute(
            "SELECT id, ts, text, tag, status FROM debate_ideas ORDER BY id DESC LIMIT ?", (ideas,))]
        avg = c.execute("SELECT AVG(in_tokens + cache_read + cache_write), AVG(out_tokens), AVG(cost_usd), COUNT(*) "
                        "FROM debate_rounds WHERE status = 'ok' AND ts > ?", (now - 7 * DAY_MS,)).fetchone()
        sk = c.execute("SELECT COUNT(*) FROM debate_rounds WHERE status = 'skipped' AND ts > ?",
                       (now - DAY_MS,)).fetchone()[0]
        out.update(ready=True, state=state, state_ko=STATE_KO.get(state, state), reason=reason, heartbeat_ts=hb,
                   model=run.get("model"), every_min=every, last_round_ts=last_ok[0] if last_ok else None,
                   last_attempt=None if not last_any else {"ts": last_any[0], "status": last_any[1], "error": last_any[2]},
                   spend={"month_key": month_key, "month": round(month, 4), "day": round(day, 4), "cap": cap,
                          "pct": round(100 * month / cap, 1) if cap else None},
                   avg_round={"in_tokens": round(avg[0] or 0), "out_tokens": round(avg[1] or 0),
                              "cost_usd": round(avg[2] or 0, 5), "rounds_7d": int(avg[3] or 0)},
                   skipped_24h=int(sk), rounds=shown, hypotheses=hy, ideas=idl,
                   scoreboard=G.scoreboard(c))
    except sqlite3.Error:
        return {**out, "ready": False}
    finally:
        c.close()
    return out


CAUTION_KO = ("AI가 쓴 토론이라 사실이 아니라 의견입니다. 거래가 적은 계좌 이야기는 표본이 작아 우연일 수 있고, "
              "30일 체크포인트 전에는 결론이 없습니다. 이 방은 주문·규칙·계좌를 바꾸지 않습니다.")


def _loads(v: Any) -> Any:
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return None


def _ago(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s}초 전" if s < 120 else (f"{s // 60}분 전" if s < 7200 else f"{s // 3600}시간 전")


# ---------------------------------------------------------------- cost estimate (dry run)
INTERVALS = (10, 20, 30, 60)
MODELS = (("Haiku 4.5", "haiku"), ("Sonnet 5.5", "sonnet"))


def round_cost(in_tokens: int, out_tokens: int, price: tuple[float, float]) -> float:
    return (in_tokens * price[0] + out_tokens * price[1]) / 1e6


def cost_table(in_tokens: int, out_tokens: int, skip: float = 0.3, days: int = 30) -> list[dict]:
    """USD per round and per 30-day month for each model and interval, with and without the skip rule (no prompt cache
    assumed: the stable prefix is under Haiku's 4,096-token minimum, and rounds are minutes apart)."""
    rows = []
    for name, fam in MODELS:
        per = round_cost(in_tokens, out_tokens, PRICES[fam])
        for iv in INTERVALS:
            n = days * 24 * 60 / iv
            rows.append({"model": name, "every_min": iv, "per_round": round(per, 5), "month_no_skip": round(per * n, 2),
                         "month_skip": round(per * n * (1 - skip), 2), "rounds_month": int(n)})
    return rows


def format_table(rows: list[dict], skip: float = 0.3) -> str:
    lines = [f"{'모델':<11}{'간격':>6}{'회당 $':>10}{'한 달 $ (건너뛰기 없음)':>26}{f'한 달 $ (약 {int(skip * 100)}% 건너뜀)':>26}"]
    for r in rows:
        lines.append(f"{r['model']:<11}{r['every_min']:>4}분{r['per_round']:>10.4f}{r['month_no_skip']:>22.2f}{r['month_skip']:>26.2f}")
    return "\n".join(lines)


SAMPLE_NOTES = ["지금은 표본이 작아 좋은 자리 묶음의 평균이 우연일 수 있고, 30일 체크포인트 전이라 결론은 없다. " * 2,
                "밤 점검 재계산은 일치했고 빠진 1분봉도 없어 데이터 문제로 볼 근거는 아직 없다. " * 2]
SAMPLE_TURNS = ["퀀트: " + "표본이 작은 계좌의 평균은 한두 건에 크게 흔들린다. " * 4, "회의론자: " + "비교 기준이 같은지부터 확인해야 한다. " * 4]


def dry_run(cfg: Config, now_ms: Optional[int] = None, show_packet: bool = False, out: Callable[[str], Any] = print) -> int:
    """Builds the packet of every agenda topic and prints the token estimate and the estimated cost. No API call, no
    key, nothing written. The previous round's notes are filled with a full-size sample (the steady state)."""
    now = _now_ms() if now_ms is None else now_ms
    sys_tok = P.estimate_tokens(system_text())
    order = roles_for(0, cfg.turns)
    sizes, built0 = [], None
    for i, (key, ko) in enumerate(P.TOPICS):
        try:
            built = P.build(cfg.paper_db, cfg.daily_db, cfg.agents_db, cfg.checkpoint_db, now, round_no=i,
                            last_notes=SAMPLE_NOTES, last_turns=SAMPLE_TURNS)
        except Exception as exc:  # noqa: BLE001
            out(f"패킷을 만들지 못했습니다: {type(exc).__name__}: {exc}")
            out(f"(paper3.db 경로: {cfg.paper_db}. 서버에서는 sudo -u paperbot-debate 로 실행하세요)")
            return 1
        utext = user_text(built["packet"], built["topic_ko"], built["why"], i, order)
        sizes.append((ko, P.estimate_tokens(utext)))
        if built0 is None:
            built0 = built
    usr_avg = round(sum(n for _, n in sizes) / len(sizes))
    usr_max = max(n for _, n in sizes)
    in_tok, out_tok = sys_tok + usr_avg, cfg.est_out_tokens
    price = cfg.prices()
    out(f"고정 앞부분(규칙·역할·메뉴, 캐시 대상): 약 {sys_tok:,} 토큰")
    out("회차마다 바뀌는 자료+요청: " + ", ".join(f"{ko} {n:,}" for ko, n in sizes))
    out(f"  → 평균 {usr_avg:,}, 가장 큰 것 {usr_max:,} 토큰 (자료 상한 {P.MAX_PACKET_TOKENS:,})")
    out(f"입력 토큰 추정(평균): {sys_tok:,} + {usr_avg:,} = {in_tok:,}   출력 토큰 추정: {out_tok:,} (상한 {cfg.max_tokens:,}; 발언 {cfg.turns}개 + 정리·가설·아이디어)")
    per = round_cost(in_tok, out_tok, price)
    out(f"설정 모델 {cfg.model}: 단가 입력 ${price[0]:g} / 출력 ${price[1]:g} (100만 토큰당) → 회당 약 ${per:.4f}, "
        f"한 달({cfg.every_min}분 간격, 건너뛰기 없이) 약 ${per * 30 * 24 * 60 / cfg.every_min:.2f} (월 한도 ${cfg.monthly_cap:g})")
    out("")
    out(format_table(cost_table(in_tok, out_tok)))
    out("")
    out("토큰은 코드가 센 추정값(한글은 글자마다 1토큰 안팎으로 넉넉히 셈)이고, 단가는 코드에 넣은 값이라 콘솔에서 다시 확인해야 합니다. "
        "실제 값은 첫 회차 뒤 `status`의 '회당 평균'에 나옵니다. 건너뛰기 30%는 가정일 뿐, 실제 비율은 청산이 얼마나 자주 나느냐에 달렸습니다. "
        "API 호출 없음, 키 필요 없음.")
    if show_packet and built0 is not None:
        out("")
        out(P.compact_json(built0["packet"]))
    return 0


# ---------------------------------------------------------------- command line
def make_notifier(environ: Optional[dict] = None) -> Any:
    """TelegramNotifier from TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_CRITICAL (debate.env); None when they are not set."""
    env = os.environ if environ is None else environ
    if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_CRITICAL"):
        return None
    from ..notify import TelegramNotifier
    return TelegramNotifier()


def print_status(s: dict, out: Callable[[str], Any] = print) -> None:
    if not s.get("ready"):
        out(f"24시간 토론방: {s['state_ko']} — {s['reason']}")
        return
    sp = s["spend"]
    out(f"24시간 토론방: {s['state_ko']}" + (f" — {s['reason']}" if s.get("reason") else ""))
    out(f"모델 {s.get('model')}, {s.get('every_min')}분 간격, 마지막 토론 "
        f"{'없음' if not s.get('last_round_ts') else _ago(_now_ms() - s['last_round_ts'])}")
    out(f"이번 달({sp['month_key']}) ${sp['month']:.2f} / 한도 ${sp['cap']:g}" + (f" ({sp['pct']}%)" if sp["pct"] is not None else "")
        + f", 오늘 ${sp['day']:.2f}, 하루 안에 건너뛴 회차 {s['skipped_24h']}번")
    a = s["avg_round"]
    out(f"최근 7일 회당 평균: 입력 {a['in_tokens']:,} 토큰, 출력 {a['out_tokens']:,} 토큰, ${a['cost_usd']:.4f} ({a['rounds_7d']}회)")
    sb = s["scoreboard"]
    out(f"가설 채점: {sb['graded']}개 중 {sb['hit']}개 맞음" + (" (표본 작음: 결론 아님)" if sb["small"] else "")
        + f", 열린 가설 {sb['by_status'].get('open', 0)}개")
    for who, b in sorted(sb["speakers"].items()):
        out(f"  {who}: {b['hit']}/{b['graded']}" + (" (표본 작음)" if b["small"] else ""))


def main(argv: Optional[list] = None, environ: Optional[dict] = None, transport: Transport = urllib_transport,
         out: Callable[[str], Any] = print) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.agents.debate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("run", "once", "status"))
    ap.add_argument("--dry-run", action="store_true", help="once: build the packet, print tokens and cost; no API call")
    ap.add_argument("--show-packet", action="store_true", help="once --dry-run: also print the packet")
    ap.add_argument("--json", action="store_true", help="status: JSON")
    args = ap.parse_args(argv)
    try:
        cfg = config_from_env(environ)
    except ValueError as exc:
        print(f"debate: 설정 오류: {redact(exc)}", file=sys.stderr)
        return 2
    if args.cmd == "status":
        s = summary(cfg.debate_db)
        out(json.dumps(s, ensure_ascii=False, indent=1) if args.json else "")
        if not args.json:
            print_status(s, out)
        return 0
    if args.cmd == "once" and args.dry_run:
        return dry_run(cfg, show_packet=args.show_packet, out=out)
    if not cfg.api_key and args.cmd == "once":
        print("debate: ANTHROPIC_API_KEY가 없습니다 (/etc/paperbot/debate.env). 키 없이 확인하려면: once --dry-run",
              file=sys.stderr)
        return 2                                   # (`run` without a key idles in state 'no_key': the dashboard says so)
    db = DB(cfg.debate_db)
    stop, restore = stop_on_sigterm()
    svc = Service(cfg, db, make_notifier(environ), transport=transport, stop=stop, out=out)
    try:
        if args.cmd == "once":
            svc.start()
            res = svc.tick(force=True)
            out(f"결과: {res}")
            print_status(summary(cfg.debate_db), out)
            return 0 if res == "round" else 1
        return svc.run()
    finally:
        restore()
        try:
            db.close()
        except sqlite3.Error:
            pass



if __name__ == "__main__":
    sys.exit(main())
