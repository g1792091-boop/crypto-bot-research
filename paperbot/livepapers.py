"""Which paper bot each live executor follows, and since when (owners 10-19, docs/live15-mexc-ko.md: "두 봇을 다른 느낌으로
돌리면 한 개만 성공해도 좋잖아"). Pure helpers for the live checks (paperbot/livecheck.py, livemissed.py, liveimprove.py,
liveteam.py) and the 실거래 site (paperbot/dash/more/live*.py); nothing here opens a bot's database for writing.

Bybit follows 규칙봇 15 (-50 % net stop, /var/lib/paperbot/combo/live-ac.db); MEXC follows its twin with the -35 % stop
(/var/lib/paperbot/combo/live15-mexc.db). Both paper databases hold the same account name (COMBO@mix) and the same
entries most of the time, so a live trade must be compared with the paper bot it really followed, not with whichever
database has a trade of that coin at that minute.

The executor records the ``paper_db`` of its config in every ``start`` event (paperbot/executor.py, since 10-19; a
start before that says nothing). An executor's paper source over time (``segments``):

- before its first start that names a paper database (and at every start that names none, and with no start record
  at all): the main paper bot (the one both executors followed from the live start on 10-20);
- from each start that names one: that database.

A config edited but not restarted yet does not count: the running executor still follows what its last start said
(``config_differs`` says so; the next start records the new one). When both executors follow the main paper bot (the
10-20 state) every segment is that one and every comparison is what it was before.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Iterable, Optional


def norm(path: Optional[str]) -> Optional[str]:
    """The same file whatever way its path is written (None stays None)."""
    return os.path.abspath(path) if path else path


def same(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a) and bool(b) and norm(a) == norm(b)


def starts_of(conn) -> list:
    """[(ts, paper_db or None)] of an executor database's ``start`` events, oldest first (read-only; [] when the events
    table cannot be read)."""
    try:
        rows = conn.execute("SELECT ts, data FROM events WHERE kind = 'start' ORDER BY id").fetchall()
    except sqlite3.Error:
        return []
    out = []
    for ts, data in rows:
        try:
            d = json.loads(data) if isinstance(data, (str, bytes)) and data else {}
        except (TypeError, ValueError):
            d = {}
        p = d.get("paper_db") if isinstance(d, dict) else None
        try:
            out.append((int(ts), p if isinstance(p, str) and p else None))
        except (TypeError, ValueError):
            continue
    return out


def segments(starts: Iterable, main: str, config_paper: Optional[str] = None) -> list:
    """[[from ms or None, paper db]]: which paper database the executor followed from when (module docstring). The
    first segment starts at None (always); a new one only where the database changes. ``config_paper`` is not used
    for the past (only what a start recorded counts); it is the caller's to compare (config_differs)."""
    segs: list = [[None, main]]
    for ts, pdb in list(starts or []):
        path = pdb or main
        if not same(path, segs[-1][1]):
            segs.append([int(ts), path])
    return segs


def paper_at(segs: list, t: Optional[int]) -> str:
    """The paper database the executor followed at ``t`` (ms; None: the first one)."""
    cur = segs[0][1]
    for frm, path in segs[1:]:
        if t is not None and int(t) >= int(frm):
            cur = path
    return cur


def current(segs: list) -> str:
    return segs[-1][1]


def paths_of(segs: list) -> list:
    """The paper databases of the segments, each once, in order."""
    out: list = []
    for _f, p in segs:
        if not any(same(p, q) for q in out):
            out.append(p)
    return out


def config_differs(segs: list, config_paper: Optional[str]) -> bool:
    """The config names another paper database than the one the executor followed at its last start (edited and not
    restarted yet, or never started with this code)."""
    return bool(config_paper and not same(config_paper, current(segs)))


def followed_at(segs: list, path: str, t: Optional[int]) -> bool:
    """Did the executor follow ``path`` at ``t``?"""
    return same(paper_at(segs, t), path)


def stop_short(stop: Any) -> Optional[str]:
    """A paper bot's stop in two or three characters for a label: "−50%" (net-ROE stop), "3 ATR"; None when unknown."""
    if not isinstance(stop, dict):
        return None
    if stop.get("mode") == "roe":
        try:
            return f"−{float(stop.get('roe')) * 100:g}%"
        except (TypeError, ValueError):
            return None
    try:
        return f"{float(stop.get('atr')):g} ATR"
    except (TypeError, ValueError):
        return None


def stop_words(stop: Any) -> Optional[str]:
    """The stop in the owners' words: "순ROE −35% (수수료·슬리피지 포함)" / "ROE −50%" / "3 ATR"."""
    if not isinstance(stop, dict):
        return None
    if stop.get("mode") == "roe":
        try:
            pct = f"−{float(stop.get('roe')) * 100:g}%"
        except (TypeError, ValueError):
            return None
        return f"순ROE {pct} (수수료·슬리피지 포함)" if stop.get("net") is True else f"ROE {pct}"
    return stop_short(stop)


def bot_short(name: Any, stop: Any) -> str:
    """A paper bot's short name on the site and in the messages: its config's ``name`` ("추세판단 봇", "VWAP 개선판",
    owners 10-23: two different bots, each executor following one), else the stop ("페이퍼 −35%"; the 10-19 twins had
    the same rules and only the stop told them apart), else "페이퍼"."""
    if isinstance(name, str) and name.strip():
        return name.strip()
    s = stop_short(stop)
    return f"페이퍼 {s}" if s else "페이퍼"


def label(stop: Any, followers: list, name: Any = None) -> str:
    """"VWAP 개선판 (바이비트가 따라감)" / "페이퍼 −50% (바이비트·MEXC가 따라감)" / "페이퍼 −35% (따라가는 실행기 없음)"."""
    head = bot_short(name, stop)
    if not followers:
        return f"{head} (따라가는 실행기 없음)"
    return f"{head} ({'·'.join(followers)}가 따라감)"            # 바이비트가, MEXC가


# a paper bot's TIME exit (combo exit reason "TIME"): the trend bot's supervisor closing a position that went nowhere
# (paperbot/trendbot.py), or a bot's hold limit (combo ``max_hold_bars``: 'VWAP 개선판' 96 bars of the trade's own bar)
TIME_TREND_KO = "감독 청산(시간 정리)"
TIME_HOLD_KO = "보유 한도 청산"


def time_exit_ko(cfg: Any) -> str:
    """The words for a paper bot's TIME exit from its config (combo_run config dict): the hold limit's for a bot with
    ``max_hold_bars`` and no trend supervisor, the trend bot's otherwise (and when the config is unknown)."""
    if isinstance(cfg, dict) and cfg.get("trend") is None and cfg.get("max_hold_bars"):
        return TIME_HOLD_KO
    return TIME_TREND_KO


def exit_ko(reason: Any, cfg: Any, table: dict) -> str:
    """A paper exit reason in words: ``table`` (the caller's own KO_EXIT) with TIME by the bot (time_exit_ko)."""
    if reason == "TIME":
        return time_exit_ko(cfg)
    return table.get(reason, reason) if isinstance(reason, str) else str(reason)
