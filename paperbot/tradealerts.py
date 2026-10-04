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

Price alerts (owners' choice 2026-10-03): the owners set them in the dashboard (inbox.db tables ``price_alerts`` /
``price_alert_changes``, written only by the dashboard, read here read-only). Every 10 seconds, while an alert is
armed, the last prices of Binance USD-M (public, one request for all coins, weight 2) are checked; an alert whose
price is reached goes out as a Telegram message WITH sound (WARN) and is then off until the owners re-arm it. The
times they fired, a heartbeat and the last prices are kept in ``price_alerts.json`` next to ``--state`` (the
dashboard shows them). TRADE_ALERTS=off stops the trade messages only, not the price alerts.
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

from .notify import INFO, WARN, ConsoleNotifier, Notifier

TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
REASON_KO = {"SL": "손절", "LOCK": "익절 잠금", "LIQ": "강제청산", "TP": "익절", "HALT": "정지", "MANUAL": "수동",
             "END": "종료", "BUST": "파산"}
BLOCKS = 3          # up to this many entries (exits) in a message: one block each; more: grouped lines
MAX_LINES = 12      # grouped lines per section, then '외 n건'


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
    """'일목·RSI 15분', '복제 슈퍼트렌드·ROC 1시간', '새 매매법 NL2 15분', '동전 봇 3 15분' (notify.who's wording;
    ``names``: STRATEGY_KO)."""
    strat, _, tf = account_id.partition("@")
    tf = tf.split("~", 1)[0]
    tf_ko = TF_KO.get(tf, tf)
    if kind == "random":
        return f"동전 봇 {strat.rsplit('_', 1)[-1]} {tf_ko}"
    if kind == "newlab":
        return f"새 매매법 {strat} {tf_ko}"
    base = names.get(strat, strat)
    return f"복제 {base} {tf_ko}" if kind == "copy" else f"{base} {tf_ko}"


def px(x: float) -> str:
    d = 5 if x < 1 else 4 if x < 10 else 2 if x < 1000 else 1
    return f"{x:,.{d}f}"


def usd(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"


def _kst(now_ms: int, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(now_ms / 1000 + 9 * 3600))


def _settings(c: sqlite3.Connection):
    """The run's settings for the ladder prices: v3 with the run's taker fee (state 'run')."""
    from .config import v3_settings
    fee = None
    try:
        r = c.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
        fee = (json.loads(r["data"]) or {}).get("taker_fee") if r else None
    except (sqlite3.Error, ValueError, TypeError):
        fee = None
    return v3_settings(**({"taker_fee": float(fee)} if fee else {}))


def ladder_prices(p: dict) -> tuple[float, float, float, float]:
    """(trigger ROE, its price, first lock ROE, the stop it moves to) of an open position: the profit lock arms at
    first_lock + trigger_gap net ROE (ladder.LadderSpec) and moves the stop to the first lock's price, both net of
    the run's round trip (funding left out). A copy with its own 'lock_start' rule has its own first lock."""
    from .config import v3_settings
    from .ladder import roe_price
    s = v3_settings()
    first = float(p.get("first_lock") or s.ladder_first_lock)
    gap = float(p.get("trigger_gap") or s.ladder_trigger_gap)
    rt = float(p.get("round_trip") or s.round_trip_cost)
    trig = first + gap
    return (trig, roe_price(p["side"], p["entry"], p["leverage"], trig, rt),
            first, roe_price(p["side"], p["entry"], p["leverage"], first, rt))


def read(db: str, kinds: tuple, since_id: int) -> tuple[dict, list[dict], int]:
    """(open positions {account_id: position}, new exits after ``since_id`` of the chosen kinds, the highest trade
    id read, filtered rows included)."""
    with _ro(db) as c:
        try:
            rows = c.execute("SELECT account_id, kind, data FROM accounts").fetchall()
        except sqlite3.OperationalError:            # an old table without data
            rows = c.execute("SELECT account_id, kind, NULL AS data FROM accounts").fetchall()
        accts, first_lock = {}, {}
        for r in rows:
            accts[r["account_id"]] = r["kind"]
            try:
                d = json.loads(r["data"] or "{}")
            except (ValueError, TypeError):
                d = {}
            if isinstance(d, dict) and d.get("first_lock") is not None:
                first_lock[r["account_id"]] = float(d["first_lock"])     # extras: their own ladder start
        s = _settings(c)
        r = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        eng = (json.loads(r["data"]) or {}).get("engines", {}) if r else {}
        exits = [dict(x) for x in c.execute(
            "SELECT id, account_id, symbol, exit_time, exit_reason, leverage, pnl, roe, equity_after, data FROM trades "
            "WHERE id > ? ORDER BY id", (since_id,))]
        lev_why = _lev_why(c, eng, accts, kinds)
    top = max([since_id] + [x["id"] for x in exits])      # past every row read, kept or filtered out
    pos = {}
    for aid, e in eng.items():
        p = (e or {}).get("position")
        if p and accts.get(aid) in kinds:
            pos[aid] = {"symbol": p["symbol"], "side": p["side"], "entry": p["entry_price"],
                        "entry_time": p["entry_time"], "leverage": p["leverage"], "margin": p["margin"],
                        "stop": p["stop_price"], "kind": accts.get(aid),
                        "first_lock": first_lock.get(aid, s.ladder_first_lock), "trigger_gap": s.ladder_trigger_gap,
                        "round_trip": s.round_trip_cost, "tier": p.get("tier"), "wallet": (e or {}).get("wallet"),
                        "lev_why": lev_why.get(aid)}
    out = []
    for x in exits:
        if accts.get(x["account_id"]) not in kinds:
            continue
        try:
            d = json.loads(x.pop("data") or "{}")
        except ValueError:
            d = {}
        if x.get("equity_after") is None and d.get("equity_after") is not None:
            x["equity_after"] = d["equity_after"]
        out.append({**x, "kind": accts.get(x["account_id"]), "side": d.get("side"), "lock_roe": d.get("lock_roe")})
    return pos, out, int(top)


def _lev_why(c: sqlite3.Connection, eng: dict, accts: dict, kinds: tuple) -> dict:
    """{account_id: "50배 불가: 손절 손실 > 자금 15% → 30배"} of the open 좋은 자리 positions below 50x (levwhy: the
    ENTERED outcome's rejected candidates; one indexed query each). Never raises."""
    out = {}
    try:
        from .levwhy import first_reason_ko, latest_entered
        for aid, e in eng.items():
            p = (e or {}).get("position")
            if not p or accts.get(aid) not in kinds or p.get("tier") != "best" or int(p.get("leverage") or 0) >= 50:
                continue
            dg = latest_entered(c, aid, p.get("symbol"), ((p.get("signal") or {}).get("ts")))
            txt = first_reason_ko(dg, p.get("leverage"))
            if txt:
                out[aid] = txt
    except Exception:  # noqa: BLE001  (a reason is cosmetic: the alert goes out without it)
        return out
    return out


def _side(side) -> str:
    return "" if side is None else ("🟢 롱" if side > 0 else "🔴 숏")


def _why(x: dict) -> str:
    why = REASON_KO.get(x["exit_reason"], x["exit_reason"])
    if x["exit_reason"] == "LOCK" and x.get("lock_roe"):
        why += f"(+{round(x['lock_roe'] * 100)}%)"
    return why


def entry_block(aid: str, p: dict, names: dict) -> list[str]:
    trig, p_trig, first, p_lock = ladder_prices(p)
    dist = (p["stop"] / p["entry"] - 1) * 100
    wallet = p.get("wallet")
    share = f" ({p['margin'] / wallet:.0%})" if isinstance(wallet, (int, float)) and wallet > 0 else ""
    best = " · 좋은 자리" if p.get("tier") == "best" else ""
    why = [p["lev_why"]] if p.get("tier") == "best" and p.get("lev_why") else []
    return [f"📈 진입 · {label(aid, p['kind'], names)}",
            f"{_side(p['side'])} · {coin(p['symbol'])} {p['leverage']}배{best}", *why,
            f"진입가 {px(p['entry'])}",
            f"익절 잠금 시작 {px(p_trig)} (+{trig * 100:.0f}%)",
            f"→ 손절을 {px(p_lock)}로 {'올림' if p['side'] > 0 else '내림'} (+{first * 100:.0f}% 확보)",
            f"손절가 {px(p['stop'])} ({dist:+.2f}%)",
            f"증거금 ${p['margin']:,.0f}{share}"]


def exit_block(x: dict, names: dict) -> list[str]:
    win = x["pnl"] > 0
    side = _side(x.get("side"))
    L = [f"{'✅ 이익' if win else '❌ 손실'} {usd(x['pnl'])} · {label(x['account_id'], x['kind'], names)}",
         f"{side + ' · ' if side else ''}{coin(x['symbol'])} {x['leverage']}배 · {_why(x)}",
         f"ROE {x['roe'] * 100:+.1f}%"]
    if x.get("equity_after") is not None:
        L.append(f"남은 잔고 ${x['equity_after']:,.0f}")
    return L


def coin(symbol: str) -> str:
    return symbol.replace("USDT", "")


def _grouped_entries(entries: list[tuple[str, dict]], names: dict) -> list[str]:
    L = []
    for side in (1, -1):
        es = [(a, p) for a, p in entries if (p["side"] > 0) == (side > 0)]
        if not es:
            continue
        L += ["", f"{_side(side)} {len(es)}건"]
        shown = 0
        for c in dict.fromkeys(coin(p["symbol"]) for _, p in es):
            ce = [(a, p) for a, p in es if coin(p["symbol"]) == c]
            same = len({p["entry"] for _, p in ce}) == 1
            body = []
            for a, p in ce:
                if shown >= MAX_LINES:
                    break
                shown += 1
                body.append(f"- {label(a, p['kind'], names)} · {p['leverage']}배"
                            + ("" if same else f" · 진입 {px(p['entry'])}") + f" · 손절 {px(p['stop'])}")
            if body:
                L += [f"{c} · 진입 {px(ce[0][1]['entry'])}" if same else c] + body
        if len(es) > shown:
            L.append(f"외 {len(es) - shown}건 — 대시보드 포지션 탭")
    return L


def _grouped_exits(exits: list[dict], shown: list[dict], names: dict) -> list[str]:
    L = []
    for win in (True, False):
        xs = [x for x in exits if (x["pnl"] > 0) == win]
        if not xs:
            continue
        L += ["", f"{'✅ 이익' if win else '❌ 손실'} {len(xs)}건 {usd(sum(x['pnl'] for x in xs))}"]
        listed = sorted([x for x in xs if any(x is y for y in shown)], key=lambda x: -abs(x["pnl"]))[:MAX_LINES]
        for x in listed:
            bal = f" · 잔고 ${x['equity_after']:,.0f}" if x.get("equity_after") is not None else ""
            L.append(f"- {label(x['account_id'], x['kind'], names)} · {coin(x['symbol'])}"
                     f" · {x['roe'] * 100:+.1f}% · {usd(x['pnl'])}{bal}")
        if len(xs) > len(listed):
            L.append(f"외 {len(xs) - len(listed)}건 — 대시보드 '오늘 체결'")
    return L


def message(entries: list[tuple[str, dict]], exits: list[dict], open_n: int, now_ms: int, names: dict,
            min_usd: float = 0.0) -> Optional[str]:
    """The Telegram text (owners' layout 2026-10-04): one trade -> its block and the KST time; more -> a header
    '📊 거래 알림 <time> · 진입 n (롱 a·숏 b) · 청산 m · 합계 ±$', then up to ``BLOCKS`` entries (exits) as blocks,
    more as lines grouped by side and coin (entries) or by profit / loss (exits), ``MAX_LINES`` per section,
    and the open positions last. Exits with |P&L| below ``min_usd`` are counted, not listed."""
    if not entries and not exits:
        return None
    entries = sorted(entries, key=lambda e: -e[1]["margin"])
    shown = [x for x in exits if abs(x["pnl"]) >= min_usd]
    if len(entries) + len(exits) == 1 and (entries or shown):
        L = entry_block(*entries[0], names) if entries else exit_block(exits[0], names)
        return "\n".join(L + [_kst(now_ms)])
    nl = sum(p["side"] > 0 for _, p in entries)
    head = [f"📊 거래 알림 {_kst(now_ms)}"]
    if entries:
        head.append(f"진입 {len(entries)}" + (f" (롱 {nl}·숏 {len(entries) - nl})" if 0 < nl < len(entries) else ""))
    if exits:
        head += [f"청산 {len(exits)}", f"합계 {usd(sum(x['pnl'] for x in exits))}"]
    L = [" · ".join(head)]
    if len(entries) <= BLOCKS:
        for a, p in entries:
            L += [""] + entry_block(a, p, names)
    else:
        L += _grouped_entries(entries, names)
    if len(exits) <= BLOCKS:
        for x in sorted(shown, key=lambda x: -abs(x["pnl"])):
            L += [""] + exit_block(x, names)
        if len(exits) > len(shown):
            L += ["", f"외 {len(exits) - len(shown)}건 (작은 손익) — 대시보드 '오늘 체결'"]
    else:
        L += _grouped_exits(exits, shown, names)
    L += ["", f"열린 포지션 {open_n}개"]
    return "\n".join(L)


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


# ---------------------------------------------------------------- price alerts
PRICE_EVERY_S = 10
PRICE_URL = "https://fapi.binance.com/fapi/v1/ticker/price"


def fetch_prices(get=None, timeout: float = 5.0) -> dict:
    """{symbol: last price} of every Binance USD-M contract (one public request)."""
    import urllib.request
    get = get or (lambda url: json.loads(urllib.request.urlopen(url, timeout=timeout).read()))
    return {r["symbol"]: float(r["price"]) for r in get(PRICE_URL) if isinstance(r, dict) and "symbol" in r}


def _level(x: float) -> str:
    """An owner-set price as they typed it: 65000 -> '65,000', 0.1234 -> '0.1234'."""
    return f"{int(x):,}" if float(x) == int(x) else f"{x:,.10g}"


def price_text(a: dict, last: float, now_ms: Optional[int] = None) -> str:
    c = a["symbol"].replace("USDT", "")
    way = "돌파" if a["direction"] == "above" else "이탈"
    L = [f"🔔 가격 알림 · {c} {_level(a['price'])} {way}", "", f"지금 {px(last)}"]
    if a.get("note"):
        L.append(f"메모: {a['note']}")
    L.append(_kst(int(time.time() * 1000) if now_ms is None else now_ms))
    return "\n".join(L)


def check_price_alerts(inbox: Optional[str], pstate: dict, notifier: Notifier, now_ms: int, prices_fn) -> list[str]:
    """Send the armed alerts whose price is reached (WARN: with sound). ``pstate``: {"fired": {id: ts}, "hb",
    "prices"} (changed in place). A failed send is tried again on the next check. Returns the texts sent."""
    from .agents import rooms_db as R
    fired = pstate.setdefault("fired", {})
    pstate["hb"] = now_ms
    conn = R.open_ro(inbox) if inbox else None
    try:
        alerts = R.price_alerts(conn)
    finally:
        if conn is not None:
            conn.close()
    armed = [a for a in alerts if int(fired.get(str(a["id"]), 0)) < a["armed_ts"]]
    pstate["armed"] = len(armed)
    if not armed:
        return []
    prices = prices_fn()
    pstate["prices"] = {a["symbol"]: prices.get(a["symbol"]) for a in armed}
    pstate["prices_ts"] = now_ms
    sent = []
    for a in armed:
        last = prices.get(a["symbol"])
        if last is None:
            continue
        if (a["direction"] == "above" and last >= a["price"]) or (a["direction"] == "below" and last <= a["price"]):
            text = price_text(a, last, now_ms)
            if notifier.send(WARN, text) is False:
                continue
            fired[str(a["id"])] = now_ms
            sent.append(text)
    return sent


def kinds_for(mode: str) -> tuple:
    return ("strategy", "copy", "newlab", "random") if mode == "all" else ("strategy", "copy", "newlab")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.tradealerts")
    ap.add_argument("cmd", choices=("run", "sample"))
    ap.add_argument("--db", required=True)
    ap.add_argument("--state", default=None)
    ap.add_argument("--inbox", default=None, help="inbox.db of the dashboard (price alerts), read-only")
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
        print("TRADE_ALERTS=off: no trade messages (price alerts still on)", file=sys.stderr)
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
    pstate_path = os.path.join(os.path.dirname(os.path.abspath(a.state)), "price_alerts.json")
    try:
        with open(pstate_path, encoding="utf-8") as fh:
            pstate = json.load(fh)
    except (OSError, ValueError):
        pstate = {}
    next_trade = 0.0
    while not stop["now"]:
        if mode != "off" and time.time() >= next_trade:
            try:
                state, _ = pass_once(a.db, state, kinds_for(mode), notifier, int(time.time() * 1000), names, min_usd)
                save_state(a.state, state)
            except (sqlite3.Error, OSError, ValueError, KeyError) as exc:
                print(f"trade alerts pass failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            # 20 s after a minute boundary: the runner has saved that minute's snapshot by then
            now = time.time()
            next_trade = (now // every + 1) * every + 20
        try:
            check_price_alerts(a.inbox, pstate, notifier, int(time.time() * 1000), fetch_prices)
        except Exception as exc:  # noqa: BLE001  (no prices this time: try again in 10 s)
            print(f"price alerts check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            save_state(pstate_path, pstate)
        except OSError as exc:
            print(f"price alerts state not saved: {exc}", file=sys.stderr)
        end = time.time() + PRICE_EVERY_S
        while not stop["now"] and time.time() < end:
            time.sleep(min(1.0, end - time.time()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
