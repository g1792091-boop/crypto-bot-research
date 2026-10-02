"""Telegram entry / exit alerts for the paper accounts, bundled (docs/server-setup-v3.md "텔레그램 거래 알림").

    python -m paperbot.tradealerts run    --db /var/lib/paperbot/paper3.db --state /var/lib/paperbot/tradealerts.json
    python -m paperbot.tradealerts sample --db paper3.db      (prints what the next message would say, sends nothing)

Read-only on paper3.db (live3 stays its only writer): entries are positions that appear in the runner's account
snapshot (state 'accounts', saved every minute), exits are new rows of the trades table. Every ``every`` seconds
the new ones go out as ONE silent message (INFO chat, disable_notification), so hundreds of trades a day never
ring the phone; forced liquidations still come loud from the runner itself. Nothing here can change an account.

Settings (live.env, all optional):
    TRADE_ALERTS        strategy (default: strategy, copy and new-lab accounts) | all (+ coin flips) | off
    TRADE_ALERTS_EVERY  seconds between messages (default 60, at least 30)
    TRADE_ALERTS_MIN_USD  exits with |P&L| below this are counted, not listed (default 0)

The first pass only remembers what is already open and closed (no message for the past). The cursor (last trade
id, open positions) is kept in ``--state`` so a restart neither repeats nor loses alerts.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
import urllib.parse
from typing import Optional

from .notify import INFO, ConsoleNotifier, Notifier

TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
REASON_KO = {"SL": "손절", "LOCK": "익절 잠금", "LIQ": "강제청산", "TP": "익절", "HALT": "정지", "MANUAL": "수동",
             "END": "종료", "BUST": "파산"}
MAX_LINES = 20


def _ro(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _names() -> dict:
    try:
        from .agents.roster3 import STRATEGY_KO
        return dict(STRATEGY_KO)
    except Exception:  # noqa: BLE001  (names are cosmetic)
        return {}


def label(account_id: str, kind: str, names: dict) -> str:
    strat, _, tf = account_id.partition("@")
    tf_ko = TF_KO.get(tf, tf)
    if kind == "random":
        return f"동전 봇 {strat.rsplit('_', 1)[-1]} · {tf_ko}"
    base = names.get(strat, strat)
    if kind == "copy":
        base = f"복제 {base}"
    elif kind == "newlab":
        base = f"새 매매법 {base}"
    return f"{base} · {tf_ko}"


def px(x: float) -> str:
    d = 5 if x < 1 else 4 if x < 10 else 2 if x < 1000 else 1
    return f"{x:,.{d}f}"


def usd(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"


def read(db: str, kinds: tuple, since_id: int) -> tuple[dict, list[dict], int]:
    """(open positions {account_id: position}, new exits after ``since_id`` of the chosen kinds, the highest trade
    id read, filtered rows included)."""
    with _ro(db) as c:
        accts = {r["account_id"]: r["kind"] for r in c.execute("SELECT account_id, kind FROM accounts")}
        r = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        eng = (json.loads(r["data"]) or {}).get("engines", {}) if r else {}
        exits = [dict(x) for x in c.execute(
            "SELECT id, account_id, symbol, exit_time, exit_reason, leverage, pnl, roe, data FROM trades "
            "WHERE id > ? ORDER BY id", (since_id,))]
    top = max([since_id] + [x["id"] for x in exits])      # past every row read, kept or filtered out
    pos = {}
    for aid, e in eng.items():
        p = (e or {}).get("position")
        if p and accts.get(aid) in kinds:
            pos[aid] = {"symbol": p["symbol"], "side": p["side"], "entry": p["entry_price"],
                        "entry_time": p["entry_time"], "leverage": p["leverage"], "margin": p["margin"],
                        "stop": p["stop_price"], "kind": accts.get(aid)}
    out = []
    for x in exits:
        if accts.get(x["account_id"]) not in kinds:
            continue
        try:
            d = json.loads(x.pop("data") or "{}")
        except ValueError:
            d = {}
        out.append({**x, "kind": accts.get(x["account_id"]), "side": d.get("side"), "lock_roe": d.get("lock_roe")})
    return pos, out, int(top)


def message(entries: list[tuple[str, dict]], exits: list[dict], open_n: int, now_ms: int, names: dict,
            min_usd: float = 0.0) -> Optional[str]:
    if not entries and not exits:
        return None
    kst = time.strftime("%H:%M", time.gmtime(now_ms / 1000 + 9 * 3600))
    lines = [f"거래 알림 {kst} · 진입 {len(entries)} · 청산 {len(exits)}"]
    if entries:
        lines.append("")
        lines.append("[진입]")
        for aid, p in sorted(entries, key=lambda e: -e[1]["margin"])[:MAX_LINES]:
            lines.append(f"{'롱' if p['side'] > 0 else '숏'} {p['symbol'].replace('USDT', '')} {p['leverage']}배 @ {px(p['entry'])}"
                         f" · {label(aid, p['kind'], names)} · 증거금 ${p['margin']:,.0f} · 손절 {px(p['stop'])}")
        if len(entries) > MAX_LINES:
            lines.append(f"외 {len(entries) - MAX_LINES}건 (대시보드 포지션 탭)")
    if exits:
        lines.append("")
        lines.append("[청산]")
        shown = [x for x in exits if abs(x["pnl"]) >= min_usd]
        for x in sorted(shown, key=lambda x: -abs(x["pnl"]))[:MAX_LINES]:
            why = REASON_KO.get(x["exit_reason"], x["exit_reason"])
            if x["exit_reason"] == "LOCK" and x.get("lock_roe"):
                why += f" +{round(x['lock_roe'] * 100)}%"
            side = "" if x.get("side") is None else ("롱 " if x["side"] > 0 else "숏 ")
            lines.append(f"{usd(x['pnl'])} ({x['roe'] * 100:+.1f}%) {why} · {side}{x['symbol'].replace('USDT', '')}"
                         f" {x['leverage']}배 · {label(x['account_id'], x['kind'], names)}")
        hidden = len(exits) - min(len(shown), MAX_LINES)
        if hidden > 0:
            lines.append(f"외 {hidden}건 (대시보드 '오늘 체결')")
        tot = sum(x["pnl"] for x in exits)
        win = sum(x["pnl"] > 0 for x in exits)
        lines.append(f"청산 합계 {usd(tot)} · 이긴 거래 {win}/{len(exits)}")
    lines.append(f"지금 열린 포지션 {open_n}개")
    return "\n".join(lines)


def load_state(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            s = json.load(fh)
        return s if isinstance(s, dict) and "last_id" in s else None
    except (OSError, ValueError):
        return None


def save_state(path: str, s: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(s, fh)
    os.replace(tmp, path)


def _key(p: dict) -> str:
    return f"{p['symbol']}:{p['entry_time']}:{p['side']}"


def pass_once(db: str, state: Optional[dict], kinds: tuple, notifier: Notifier, now_ms: int, names: dict,
              min_usd: float = 0.0) -> tuple[dict, Optional[str]]:
    """One pass: (new state, the text sent or None). A failed send keeps the cursor, so the same trades go next time."""
    pos, exits, top = read(db, kinds, state["last_id"] if state else 0)
    keys = {aid: _key(p) for aid, p in pos.items()}
    if state is None:                                    # first run: remember, say nothing about the past
        return {"last_id": top, "open": keys}, None
    entries = [(aid, p) for aid, p in pos.items() if state["open"].get(aid) != keys[aid]]
    text = message(entries, exits, len(pos), now_ms, names, min_usd)
    if text is not None and notifier.send(INFO, text) is False:
        return state, None
    return {"last_id": top, "open": keys}, text


def kinds_for(mode: str) -> tuple:
    return ("strategy", "copy", "newlab", "random") if mode == "all" else ("strategy", "copy", "newlab")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.tradealerts")
    ap.add_argument("cmd", choices=("run", "sample"))
    ap.add_argument("--db", required=True)
    ap.add_argument("--state", default=None)
    a = ap.parse_args(argv)
    mode = (os.environ.get("TRADE_ALERTS") or "strategy").strip().lower()
    every = max(30, int(os.environ.get("TRADE_ALERTS_EVERY") or 60))
    min_usd = float(os.environ.get("TRADE_ALERTS_MIN_USD") or 0)
    names = _names()
    if a.cmd == "sample":
        pos, exits, _ = read(a.db, kinds_for(mode), 0)
        print(message(list(pos.items())[:5], exits[-5:], len(pos), int(time.time() * 1000), names, min_usd)
              or "(no positions or trades)")
        return 0
    if mode == "off":
        print("TRADE_ALERTS=off: no trade alerts", file=sys.stderr)
        while True:                       # stay up (Restart=always would loop); nothing to do
            time.sleep(3600)
    if not a.state:
        ap.error("run needs --state")
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_CRITICAL"):
        from .notify import TelegramNotifier
        notifier: Notifier = TelegramNotifier()
    else:
        print("no Telegram settings: printing instead", file=sys.stderr)
        notifier = ConsoleNotifier()
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    state = load_state(a.state)
    while not stop["now"]:
        try:
            state, _ = pass_once(a.db, state, kinds_for(mode), notifier, int(time.time() * 1000), names, min_usd)
            save_state(a.state, state)
        except (sqlite3.Error, OSError, ValueError, KeyError) as exc:
            print(f"trade alerts pass failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        # 20 s after a minute boundary: the runner has saved that minute's snapshot by then
        now = time.time()
        nxt = (now // every + 1) * every + 20
        while not stop["now"] and time.time() < nxt:
            time.sleep(min(1.0, nxt - time.time()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
