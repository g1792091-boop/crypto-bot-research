"""Telegram entry / exit alerts for the paper accounts, bundled (docs/server-setup-v4.md "텔레그램 거래 알림").

    python -m paperbot.tradealerts run    --db /var/lib/paperbot/paper3.db --state /var/lib/paperbot/tradealerts.json
    python -m paperbot.tradealerts sample --db paper3.db      (prints what the next message would say, sends nothing)
    python -m paperbot.tradealerts run --dry-run --db paper3.db [--hours 24] [--show 10] [--mode core|all]
        (staging: replays the last hours of the database into the messages Telegram would have got, prints them and
         the count per hour and per group; sends nothing, writes nothing)

Read-only on paper3.db (live3 stays its only writer): entries are positions that appear in the runner's account
snapshot (state 'accounts', saved every minute), exits are new rows of the trades table. Every ``every`` seconds
the new ones go out as ONE silent message (INFO chat, disable_notification), so hundreds of trades a day never
ring the phone; forced liquidations still come loud from the runner itself. Nothing here can change an account.
Every trade message is a PAPER one and its first line says so: '📈 모의 진입 · …', '✅ 모의 이익 …', '❌ 모의 손실 …',
'📊 모의 거래 알림 …', '📊 모의 거래 수 …'.

Paper v4 groups (owners' D10; paperbot/groups.py): one line or block per trade for the 36 (kind strategy), the 5m
reel (kind reel) and the extras (copy, newlab); the DeepSeek accounts (ds200) and the coin flips (random) are only
counted: their entries and exits ride along as one count line in the next message, or, when no message goes for an
hour, as one silent count message (no P&L: DeepSeek P&L is shown only in its own dashboard group, D11). The reel and
the 5m coin flips exit by the reel's own rules (paperbot/reel_engine.py), so their entry block shows the stop, the
band target (the previous 5m bar's upper Bollinger band, moved every 5m) and the time exit instead of the ladder.

Settings (live.env, all optional):
    TRADE_ALERTS        core (default; 'strategy' is the same): the 36, the reel and the extras, DeepSeek and the
                        coin flips counted | all (+ DeepSeek and the coin flips one by one) | off
    TRADE_ALERTS_EVERY  seconds between messages (default 60, at least 30; with 'all' 300 is advised)
    TRADE_ALERTS_MIN_USD  exits with |P&L| below this are counted, not listed (default 0)

The first pass only remembers what is already open and closed (no message for the past). The cursor (last trade
id, open positions, the pending counts) is kept in ``--state`` so a restart neither repeats nor loses alerts.

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
import math
import os
import signal
import sqlite3
import sys
import time
import urllib.parse
from typing import Optional

from .accounts import GROUP_OF_KIND
from .groups import COUNT_ONLY_GROUPS, GROUP_KO, GROUPS, TRADE_ALERT_GROUPS, label_ko
from .notify import INFO, WARN, ConsoleNotifier, Notifier

TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
REASON_KO = {"SL": "손절", "LOCK": "익절 잠금", "LIQ": "강제청산", "TP": "익절", "HALT": "정지", "MANUAL": "수동",
             "END": "종료", "BUST": "파산", "TIME": "시간 청산"}
# the reel's own exits (paperbot/reel_engine.py): the target is the upper band, the time exit 96 x 5m = 8 hours
REEL_REASON_KO = {"TP": "익절(볼린저 윗선)", "TIME": "시간 청산(8시간)"}
BLOCKS = 3          # up to this many entries (exits) in a message: one block each; more: grouped lines
MAX_LINES = 12      # grouped lines per section, then '외 n건'
COUNT_EVERY_S = 3600  # counted-only trades (DeepSeek, coin flips) with no message to ride along: one message an hour
PAPER = "모의"       # the first line of every paper trade message says so (owners 2026-10-05)

MODES = {"core": TRADE_ALERT_GROUPS, "all": tuple(g for g in GROUPS if g in TRADE_ALERT_GROUPS + COUNT_ONLY_GROUPS),
         "off": ()}
MODE_ALIASES = {"strategy": "core"}          # the v3 name of the default


def mode_of(raw: Optional[str]) -> str:
    """TRADE_ALERTS as given -> 'core' | 'all' | 'off' ('strategy' and anything unknown -> 'core')."""
    m = (raw or "core").strip().lower()
    m = MODE_ALIASES.get(m, m)
    return m if m in MODES else "core"


def _kinds_of(groups) -> tuple:
    return tuple(k for g in groups for k, gg in GROUP_OF_KIND.items() if gg == g)


def kinds_for(mode: str) -> tuple:
    """The account kinds announced one by one: core (default) = the 36, the reel and the extras; all = + DeepSeek and
    the coin flips. 'off' gives the default's kinds (main sends nothing then)."""
    m = mode_of(mode)
    return _kinds_of(MODES["core" if m == "off" else m])


def count_kinds_for(mode: str) -> tuple:
    """The account kinds only counted (owners' D10): DeepSeek and the coin flips unless the mode announces them."""
    shown = set(kinds_for(mode))
    return tuple(k for k in _kinds_of(COUNT_ONLY_GROUPS) if k not in shown)


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
    """'일목·RSI 15분', '복제 슈퍼트렌드·ROC 1시간', '새 매매법 NL2 15분', '동전 봇 3 15분' / '동전 봇 1 5분',
    '딥시크 F9_FVG (FVG·오더 블록) 15분', '릴스 5분 단타 (볼린저 20·2 + 200선)' (notify.who's wording; ``names``:
    STRATEGY_KO; the DeepSeek and reel names come from paperbot/groups.py)."""
    strat, _, tf = account_id.partition("@")
    tf = tf.split("~", 1)[0]
    tf_ko = TF_KO.get(tf, tf)
    if kind == "random":
        return f"동전 봇 {strat.rsplit('_', 1)[-1]} {tf_ko}"
    if kind == "newlab":
        return f"새 매매법 {strat} {tf_ko}"
    base = names.get(strat)
    if base is None:
        try:
            base = label_ko(strat)
        except Exception:  # noqa: BLE001  (names are cosmetic)
            base = None
    base = base or strat
    if kind == "copy":
        return f"복제 {base} {tf_ko}"
    return base if kind == "reel" and tf_ko in base else f"{base} {tf_ko}"


def px(x: float) -> str:
    d = 5 if x < 1 else 4 if x < 10 else 2 if x < 1000 else 1
    return f"{x:,.{d}f}"


def usd(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"


def _kst(now_ms: int, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(now_ms / 1000 + 9 * 3600))


def _finite(x) -> bool:
    try:
        return x is not None and not isinstance(x, bool) and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


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


def _data(raw) -> dict:
    try:
        d = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def _row_exits(kind: Optional[str], data: dict) -> str:
    """"reel" for the reel and for an account whose row records the reel's exits (the paper v4 5m coin flips:
    data.exits, config.v4_account_defs), else "house" (accounts.exits_of's rule, read from the row)."""
    return "reel" if kind == "reel" or data.get("exits") == "reel" else "house"


def _reel_state(p: dict) -> Optional[dict]:
    """The reel exit state the reel engine keeps in an open position's own signal (reel_engine.STATE_KEY)."""
    st = (((p or {}).get("signal") or {}).get("meta") or {}).get("reel_exit")
    return st if isinstance(st, dict) else None


def read(db: str, kinds: tuple, since_id: int, why_kinds: Optional[tuple] = None) -> tuple[dict, list[dict], int]:
    """(open positions {account_id: position}, new exits after ``since_id`` of the chosen kinds, the highest trade
    id read, filtered rows included). ``why_kinds``: the kinds whose 50x reasons are looked up (default ``kinds``)."""
    with _ro(db) as c:
        try:
            rows = c.execute("SELECT account_id, kind, data FROM accounts").fetchall()
        except sqlite3.OperationalError:            # an old table without data
            rows = c.execute("SELECT account_id, kind, NULL AS data FROM accounts").fetchall()
        accts, first_lock, exits_of = {}, {}, {}
        for r in rows:
            accts[r["account_id"]] = r["kind"]
            d = _data(r["data"])
            if d.get("first_lock") is not None:
                first_lock[r["account_id"]] = float(d["first_lock"])     # extras: their own ladder start
            exits_of[r["account_id"]] = _row_exits(r["kind"], d)
        s = _settings(c)
        r = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        eng = (json.loads(r["data"]) or {}).get("engines", {}) if r else {}
        exits = [dict(x) for x in c.execute(
            "SELECT id, account_id, symbol, exit_time, exit_reason, leverage, pnl, roe, equity_after, data FROM trades "
            "WHERE id > ? ORDER BY id", (since_id,))]
        lev_why = _lev_why(c, eng, accts, kinds if why_kinds is None else why_kinds)
    top = max([since_id] + [x["id"] for x in exits])      # past every row read, kept or filtered out
    pos = {}
    for aid, e in eng.items():
        p = (e or {}).get("position")
        if p and accts.get(aid) in kinds:
            pos[aid] = _position(aid, p, accts.get(aid), exits_of.get(aid, "house"), (e or {}).get("wallet"),
                                 first_lock.get(aid, s.ladder_first_lock), s, lev_why.get(aid))
    out = []
    for x in exits:
        if accts.get(x["account_id"]) not in kinds:
            continue
        d = _data(x.pop("data"))
        if x.get("equity_after") is None and d.get("equity_after") is not None:
            x["equity_after"] = d["equity_after"]
        out.append({**x, "kind": accts.get(x["account_id"]), "side": d.get("side"), "lock_roe": d.get("lock_roe"),
                    "exits": exits_of.get(x["account_id"], "house")})
    return pos, out, int(top)


def _position(aid: str, p: dict, kind: Optional[str], row_exits: str, wallet, first_lock: float, s,
              lev_why: Optional[str]) -> dict:
    """The alert's view of an open position (the runner's saved Position)."""
    st = _reel_state(p)
    return {"symbol": p["symbol"], "side": p["side"], "entry": p["entry_price"], "entry_time": p["entry_time"],
            "leverage": p["leverage"], "margin": p["margin"], "stop": p["stop_price"], "kind": kind,
            "group": GROUP_OF_KIND.get(kind, "other"),
            "exits": "reel" if st is not None or row_exits == "reel" else "house",
            "tp": p.get("tp_price"), "time_exit": (st or {}).get("end"),
            "first_lock": first_lock, "trigger_gap": s.ladder_trigger_gap,
            "round_trip": s.round_trip_cost, "tier": p.get("tier"), "wallet": wallet, "lev_why": lev_why}


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
    if x.get("exits") == "reel" and x["exit_reason"] in REEL_REASON_KO:
        return REEL_REASON_KO[x["exit_reason"]]
    why = REASON_KO.get(x["exit_reason"], x["exit_reason"])
    if x["exit_reason"] == "LOCK" and x.get("lock_roe"):
        why += f"(+{round(x['lock_roe'] * 100)}%)"
    return why


def _share(p: dict) -> str:
    wallet = p.get("wallet")
    return f" ({p['margin'] / wallet:.0%})" if isinstance(wallet, (int, float)) and wallet > 0 else ""


def entry_block(aid: str, p: dict, names: dict) -> list[str]:
    if p.get("exits") == "reel":
        return reel_entry_block(aid, p, names)
    trig, p_trig, first, p_lock = ladder_prices(p)
    dist = (p["stop"] / p["entry"] - 1) * 100
    best = " · 좋은 자리" if p.get("tier") == "best" else ""
    why = [p["lev_why"]] if p.get("tier") == "best" and p.get("lev_why") else []
    return [f"📈 {PAPER} 진입 · {label(aid, p['kind'], names)}",
            f"{_side(p['side'])} · {coin(p['symbol'])} {p['leverage']}배{best}", *why,
            f"진입가 {px(p['entry'])}",
            f"익절 잠금 시작 {px(p_trig)} (+{trig * 100:.0f}%)",
            f"→ 손절을 {px(p_lock)}로 {'올림' if p['side'] > 0 else '내림'} (+{first * 100:.0f}% 확보)",
            f"손절가 {px(p['stop'])} ({dist:+.2f}%)",
            f"증거금 ${p['margin']:,.0f}{_share(p)}"]


def reel_entry_block(aid: str, p: dict, names: dict) -> list[str]:
    """The reel's (and a 5m coin flip's) entry: its own exits (paperbot/reel_engine.py), no ladder: the target is a
    resting limit at the previous 5m bar's upper Bollinger band (moved at every 5m close), the stop is fixed, and
    what is still open after 96 x 5m bars closes at market."""
    dist = (p["stop"] / p["entry"] - 1) * 100
    best = " · 좋은 자리" if p.get("tier") == "best" else ""
    why = [p["lev_why"]] if p.get("tier") == "best" and p.get("lev_why") else []
    L = [f"📈 {PAPER} 진입 · {label(aid, p['kind'], names)}",
         f"{_side(p['side'])} · {coin(p['symbol'])} {p['leverage']}배{best}", *why,
         f"진입가 {px(p['entry'])}"]
    if _finite(p.get("tp")):
        tp = float(p["tp"])
        L += [f"익절 목표 {px(tp)} ({(tp / p['entry'] - 1) * 100:+.2f}%) · 볼린저 윗선",
              "→ 5분마다 새 윗선으로 바뀜 (익절 잠금 없음)"]
    L.append(f"손절가 {px(p['stop'])} ({dist:+.2f}%)")
    if _finite(p.get("time_exit")):
        end = int(p["time_exit"])
        hours = (end - (int(p["entry_time"]) - int(p["entry_time"]) % 300_000)) / 3_600_000
        L.append(f"시간 청산 {_kst(end)}" + (f" ({hours:g}시간)" if 0 < hours <= 24 else ""))
    L.append(f"증거금 ${p['margin']:,.0f}{_share(p)}")
    return L


def exit_block(x: dict, names: dict) -> list[str]:
    win = x["pnl"] > 0
    side = _side(x.get("side"))
    L = [f"{'✅' if win else '❌'} {PAPER} {'이익' if win else '손실'} {usd(x['pnl'])} · "
         f"{label(x['account_id'], x['kind'], names)}",
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
                target = f" · 목표 {px(float(p['tp']))}" if p.get("exits") == "reel" and _finite(p.get("tp")) else ""
                body.append(f"- {label(a, p['kind'], names)} · {p['leverage']}배"
                            + ("" if same else f" · 진입 {px(p['entry'])}") + f" · 손절 {px(p['stop'])}" + target)
            if body:
                L += [f"{c} · 진입 {px(ce[0][1]['entry'])}" if same else c] + body
        if len(es) > shown:
            L.append(f"외 {len(es) - shown}건 — 대시보드 '거래 › 포지션'")
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
            L.append(f"외 {len(xs) - len(listed)}건 — 대시보드 '거래 › 포지션 › 체결 기록'")
    return L


def count_text(counted: Optional[dict]) -> Optional[str]:
    """'딥시크 진입 3 · 청산 2 · 동전 진입 1' of the counted-only groups ({group: {"in": n, "out": m}}); None when
    nothing was counted. Counts only: no P&L (owners' D11)."""
    parts = []
    for g in COUNT_ONLY_GROUPS:
        c = (counted or {}).get(g) or {}
        sub = [f"진입 {c['in']}" if c.get("in") else "", f"청산 {c['out']}" if c.get("out") else ""]
        sub = [x for x in sub if x]
        if sub:
            parts.append(f"{GROUP_KO.get(g, g)} " + " · ".join(sub))
    return " · ".join(parts) or None


def count_message(counted: dict, since_ms: int, now_ms: int) -> Optional[str]:
    """The message of the counted-only trades when no trade message carried them for ``COUNT_EVERY_S``: one line
    per group, counts only (no P&L, owners' D11). None when nothing was counted."""
    lines = []
    for g in COUNT_ONLY_GROUPS:
        one = count_text({g: (counted or {}).get(g) or {}})
        if one:
            lines.append(one)
    if not lines:
        return None
    mins = max(1, round((now_ms - since_ms) / 60_000))
    span = f"지난 {mins // 60}시간" if mins % 60 == 0 else f"지난 {mins}분"
    return "\n".join([f"📊 {PAPER} 거래 수 · {_kst(now_ms)} · {span}", ""] + lines + ["손익은 대시보드 그룹 화면에서"])


def message(entries: list[tuple[str, dict]], exits: list[dict], open_n: int, now_ms: int, names: dict,
            min_usd: float = 0.0, counted: Optional[dict] = None) -> Optional[str]:
    """The Telegram text (owners' layout 2026-10-04; '모의' first, 2026-10-05): one trade -> its block and the KST
    time; more -> a header '📊 모의 거래 알림 <time> · 진입 n (롱 a·숏 b) · 청산 m · 합계 ±$', then up to ``BLOCKS``
    entries (exits) as blocks, more as lines grouped by side and coin (entries) or by profit / loss (exits),
    ``MAX_LINES`` per section, and the open positions last. Exits with |P&L| below ``min_usd`` are counted, not
    listed. ``counted``: the counted-only groups' trades since the last message, one line at the end (never a
    message by themselves here: ``count_message``)."""
    if not entries and not exits:
        return None
    extra = count_text(counted)
    tail = [f"그 밖에 {extra} (개수만)"] if extra else []
    entries = sorted(entries, key=lambda e: -e[1]["margin"])
    shown = [x for x in exits if abs(x["pnl"]) >= min_usd]
    if len(entries) + len(exits) == 1 and (entries or shown):
        L = entry_block(*entries[0], names) if entries else exit_block(exits[0], names)
        return "\n".join(L + tail + [_kst(now_ms)])
    nl = sum(p["side"] > 0 for _, p in entries)
    head = [f"📊 {PAPER} 거래 알림 {_kst(now_ms)}"]
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
            L += ["", f"외 {len(exits) - len(shown)}건 (작은 손익) — 대시보드 '거래 › 포지션 › 체결 기록'"]
    else:
        L += _grouped_exits(exits, shown, names)
    L += ["", f"열린 포지션 {open_n}개"] + tail
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


def _add_counts(counted: dict, kind: Optional[str], what: str) -> None:
    g = GROUP_OF_KIND.get(kind, "other")
    c = counted.setdefault(g, {"in": 0, "out": 0})
    c[what] = int(c.get(what, 0)) + 1


def pass_once(db: str, state: Optional[dict], kinds: tuple, notifier: Notifier, now_ms: int, names: dict,
              min_usd: float = 0.0, count_kinds: tuple = ()) -> tuple[dict, Optional[str]]:
    """One pass: (new state, the text sent or None). A failed send keeps the cursor, so the same trades go next time.
    ``count_kinds``: kinds only counted (owners' D10): their entries and exits ride along in the next message as one
    line, or go as one count message once ``COUNT_EVERY_S`` passed without a message; the pending counts and when
    they started are kept in the state ("counts", "counts_since")."""
    kinds, count_kinds = tuple(kinds), tuple(k for k in count_kinds if k not in kinds)
    pos_all, exits_all, top = read(db, kinds + count_kinds, state["last_id"] if state else 0, why_kinds=kinds)
    keys = {aid: _key(p) for aid, p in pos_all.items()}
    if state is None:                                    # first run: remember, say nothing about the past
        return {"last_id": top, "open": keys}, None
    new = [(aid, p) for aid, p in pos_all.items() if state["open"].get(aid) != keys[aid]]
    entries = [(aid, p) for aid, p in new if p["kind"] in kinds]
    exits = [x for x in exits_all if x["kind"] in kinds]
    counted = {g: dict(c) for g, c in (state.get("counts") or {}).items()}
    for _aid, p in new:
        if p["kind"] in count_kinds:
            _add_counts(counted, p["kind"], "in")
    for x in exits_all:
        if x["kind"] in count_kinds:
            _add_counts(counted, x["kind"], "out")
    since = state.get("counts_since") if state.get("counts") else None
    if counted and since is None:
        since = now_ms
    text = message(entries, exits, sum(p["kind"] in kinds for p in pos_all.values()), now_ms, names, min_usd,
                   counted=counted or None)
    if text is None and counted and now_ms - int(since) >= COUNT_EVERY_S * 1000:
        text = count_message(counted, int(since), now_ms)
    if text is not None:
        if notifier.send(INFO, text) is False:
            return state, None
        return {"last_id": top, "open": keys}, text
    out = {"last_id": top, "open": keys}
    if counted:
        out.update(counts=counted, counts_since=int(since))
    return out, None


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


# ---------------------------------------------------------------- staging: what Telegram would have got
SEEN_ENTRY_MS = 70_000      # an entry (1m bar open) is in the runner's snapshot after that bar closed and settled
SEEN_EXIT_MS = 10_000       # an exit (1m bar close) is in the trades table right after that step
PASS_OFFSET_MS = 20_000     # passes run 20 s after each ``every`` boundary (main)


def _pass_at(t_ms: int, every_ms: int) -> int:
    """The first pass (k x every + 20 s) at or after ``t_ms``."""
    return -(-(int(t_ms) - PASS_OFFSET_MS) // every_ms) * every_ms + PASS_OFFSET_MS


def dry_run(db: str, mode: str = "core", every_s: int = 60, hours: float = 24.0, end_ms: Optional[int] = None,
            names: Optional[dict] = None, min_usd: float = 0.0, show: int = 10, out=print) -> dict:
    """Replay the last ``hours`` of a paper3.db into the trade messages Telegram would have got under ``mode``,
    without sending or writing anything (staging, owners' check before a restart). Entries come from the trades
    table (closed trades) and the runner's snapshot (open positions), exits from the trades table; each is put in
    the pass that would first have seen it (passes every ``every_s`` seconds, 20 s past the boundary) and the
    counted-only groups follow ``pass_once``'s rule (one line in the next message, or a count message after an
    hour). Approximate by design: a position opened and closed before its pass is not an entry (as live), and a
    closed trade's target is its last one. Prints the first ``show`` messages (all with -1) and a table per KST hour
    and per group; returns the numbers."""
    names = _names() if names is None else names
    m = mode_of(mode)
    kinds = () if m == "off" else kinds_for(m)
    ckinds = () if m == "off" else count_kinds_for(m)
    every_ms = max(30, int(every_s)) * 1000
    with _ro(db) as c:
        try:
            rows = c.execute("SELECT account_id, kind, data FROM accounts").fetchall()
        except sqlite3.OperationalError:
            rows = c.execute("SELECT account_id, kind, NULL AS data FROM accounts").fetchall()
        accts = {r["account_id"]: r["kind"] for r in rows}
        exits_of = {r["account_id"]: _row_exits(r["kind"], _data(r["data"])) for r in rows}
        first_lock = {r["account_id"]: float(_data(r["data"])["first_lock"]) for r in rows
                      if _data(r["data"]).get("first_lock") is not None}
        s = _settings(c)
        snap = c.execute("SELECT ts, data FROM state WHERE k = 'accounts'").fetchone()
        eng = (json.loads(snap["data"]) or {}).get("engines", {}) if snap else {}
        last_exit = c.execute("SELECT MAX(exit_time) FROM trades").fetchone()[0]
        end = int(end_ms if end_ms is not None else (snap["ts"] if snap else None) or last_exit
                  or time.time() * 1000)
        start = end - int(hours * 3_600_000)
        trades = [dict(x) for x in c.execute(
            "SELECT id, account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data "
            "FROM trades WHERE exit_time >= ? OR entry_time >= ? ORDER BY id", (start, start))]
    wanted = set(kinds) | set(ckinds)
    # open spans of the announced accounts' positions (for '열린 포지션 n개'): (seen from, seen until)
    spans: list[tuple[int, int]] = []
    ev: dict[int, dict] = {}

    def slot(t):
        return ev.setdefault(_pass_at(t, every_ms), {"entries": [], "exits": [], "counted": []})

    for x in trades:
        kind = accts.get(x["account_id"])
        if kind not in wanted:
            continue
        d = _data(x.pop("data"))
        seen_in, seen_out = int(x["entry_time"]) + SEEN_ENTRY_MS, int(x["exit_time"]) + SEEN_EXIT_MS
        if kind in kinds:
            spans.append((seen_in, seen_out))
        if seen_in >= start and _pass_at(seen_in, every_ms) < seen_out:
            if kind in kinds:
                p = {"symbol": x["symbol"], "side": d.get("side") or 1, "entry": float(d.get("entry_price") or 0.0),
                     "entry_time": x["entry_time"], "leverage": x["leverage"], "margin": float(d.get("margin") or 0.0),
                     "stop": float(d.get("stop_initial") or d.get("stop_price") or 0.0), "kind": kind,
                     "group": GROUP_OF_KIND.get(kind, "other"), "exits": exits_of.get(x["account_id"], "house"),
                     "tp": d.get("tp_price"), "time_exit": None, "first_lock": first_lock.get(x["account_id"]),
                     "trigger_gap": s.ladder_trigger_gap, "round_trip": s.round_trip_cost, "tier": d.get("tier"),
                     "wallet": None, "lev_why": None}
                if p["entry"] > 0 and p["stop"] > 0:
                    slot(seen_in)["entries"].append((x["account_id"], p))
            else:
                slot(seen_in)["counted"].append((kind, "in"))
        if seen_out >= start and int(x["exit_time"]) <= end:
            if kind in kinds:
                slot(seen_out)["exits"].append({**x, "kind": kind, "side": d.get("side"), "lock_roe": d.get("lock_roe"),
                                                "equity_after": x.get("equity_after", d.get("equity_after")),
                                                "exits": exits_of.get(x["account_id"], "house")})
            else:
                slot(seen_out)["counted"].append((kind, "out"))
    for aid, e in eng.items():
        p = (e or {}).get("position")
        kind = accts.get(aid)
        if not p or kind not in wanted:
            continue
        seen_in = int(p["entry_time"]) + SEEN_ENTRY_MS
        if kind in kinds:
            spans.append((seen_in, end + 10 * every_ms))
        if seen_in < start:
            continue
        if kind in kinds:
            slot(seen_in)["entries"].append((aid, _position(aid, p, kind, exits_of.get(aid, "house"),
                                                            (e or {}).get("wallet"),
                                                            first_lock.get(aid, s.ladder_first_lock), s, None)))
        else:
            slot(seen_in)["counted"].append((kind, "in"))

    sent: list[tuple[int, str, str]] = []          # (pass ms, "trade" | "count", text)
    per_group: dict[str, dict] = {}
    counted: dict = {}
    since: Optional[int] = None
    passes = sorted(t for t in ev if t <= end + every_ms)
    i = 0
    while True:
        nxt = passes[i] if i < len(passes) else None
        due = _pass_at(since + COUNT_EVERY_S * 1000, every_ms) if counted else None
        if due is not None and due > end + every_ms:
            due = None
        if nxt is None and due is None:
            break
        if due is not None and (nxt is None or due < nxt):
            text = count_message(counted, since, due)
            if text:
                sent.append((due, "count", text))
            counted, since = {}, None
            continue
        i += 1
        e = ev[nxt]
        for kind, what in e["counted"]:
            _add_counts(counted, kind, what)
            g = per_group.setdefault(GROUP_OF_KIND.get(kind, "other"), {"in": 0, "out": 0, "shown": False})
            g[what] += 1
        if counted and since is None:
            since = nxt
        for a, p in e["entries"]:
            g = per_group.setdefault(p["group"], {"in": 0, "out": 0, "shown": True})
            g["in"] += 1
        for x in e["exits"]:
            g = per_group.setdefault(GROUP_OF_KIND.get(x["kind"], "other"), {"in": 0, "out": 0, "shown": True})
            g["out"] += 1
        open_n = sum(1 for a, b in spans if a <= nxt < b)
        text = message(e["entries"], e["exits"], open_n, nxt, names, min_usd, counted=counted or None)
        if text is None and counted and nxt - since >= COUNT_EVERY_S * 1000:
            text = count_message(counted, since, nxt)
            kind_ = "count"
        else:
            kind_ = "trade"
        if text is not None:
            sent.append((nxt, kind_, text))
            counted, since = {}, None

    per_hour: dict[str, dict] = {}
    for k, (t, kind_, text) in enumerate(sent):
        h = per_hour.setdefault(_kst(t, "%m/%d %H시"), {"messages": 0, "count_messages": 0, "chars": 0})
        h["messages"] += 1
        h["count_messages"] += kind_ == "count"
        h["chars"] = max(h["chars"], len(text))
    for e_t, e in ev.items():
        if e_t > end + every_ms:
            continue
        h = per_hour.setdefault(_kst(e_t, "%m/%d %H시"), {"messages": 0, "count_messages": 0, "chars": 0})
        h["entries"] = h.get("entries", 0) + len(e["entries"])
        h["exits"] = h.get("exits", 0) + len(e["exits"])
        h["counted"] = h.get("counted", 0) + len(e["counted"])
    res = {"mode": m, "start": start, "end": end, "every_s": every_ms // 1000, "messages": len(sent),
           "count_messages": sum(k == "count" for _, k, _ in sent),
           "max_per_hour": max((h["messages"] for h in per_hour.values()), default=0),
           "per_hour": dict(sorted(per_hour.items())), "groups": per_group, "texts": [t for _, _, t in sent]}

    out(f"모의 거래 알림 미리보기 (보내지 않음) · {os.path.basename(db)} · 모드 {m} · {every_ms // 1000}초마다 · "
        f"{_kst(start)} ~ {_kst(end)} (KST)")
    if m == "off":
        out("TRADE_ALERTS=off: 거래 메시지 없음 (가격 알림은 따로)")
    n_show = len(sent) if show < 0 else min(show, len(sent))
    for t, kind_, text in sent[:n_show]:
        out(f"\n----- {_kst(t, '%m/%d %H:%M:%S')} -----")
        out(text)
    if len(sent) > n_show:
        out(f"\n(메시지 {len(sent) - n_show}개 더: --show -1 이면 모두)")
    out("\n시간(KST)      메시지  (개수만)  진입  청산  개수만 거래  가장 긴 글자수")
    for h, v in res["per_hour"].items():
        out(f"{h:<13} {v['messages']:>6}  {v['count_messages']:>7}  {v.get('entries', 0):>4}  {v.get('exits', 0):>4}"
            f"  {v.get('counted', 0):>10}  {v['chars']:>13}")
    out(f"합계: 메시지 {res['messages']}개 (개수만 {res['count_messages']}) · 한 시간 최대 {res['max_per_hour']}개")
    for g in GROUPS:
        if g in per_group:
            v = per_group[g]
            out(f"- {GROUP_KO.get(g, g)}: 진입 {v['in']} · 청산 {v['out']} · "
                + ("건별 알림" if v["shown"] else "개수만"))
    too_long = [len(t) for t in res["texts"] if len(t) > 4096]
    if too_long:
        out(f"주의: 텔레그램 한도(4,096자)를 넘는 메시지 {len(too_long)}개")
    return res


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.tradealerts")
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "sample"))
    ap.add_argument("--db", required=True)
    ap.add_argument("--state", default=None)
    ap.add_argument("--inbox", default=None, help="inbox.db of the dashboard (price alerts), read-only")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the trade messages of the last --hours and the count per hour; send and write nothing")
    ap.add_argument("--hours", type=float, default=24.0, help="--dry-run: how far back (default 24)")
    ap.add_argument("--show", type=int, default=10, help="--dry-run: messages printed in full (default 10, -1 all)")
    ap.add_argument("--mode", default=None, help="core | all | off (default: TRADE_ALERTS, else core)")
    a = ap.parse_args(argv)
    raw = a.mode or os.environ.get("TRADE_ALERTS") or "core"
    mode = mode_of(raw)
    if raw.strip().lower() not in MODES and raw.strip().lower() not in MODE_ALIASES:
        print(f"TRADE_ALERTS={raw!r} is not core | all | off: using core", file=sys.stderr)
    every = max(30, int(os.environ.get("TRADE_ALERTS_EVERY") or 60))
    min_usd = float(os.environ.get("TRADE_ALERTS_MIN_USD") or 0)
    names = _names()
    if a.dry_run:
        dry_run(a.db, mode, every, a.hours, names=names, min_usd=min_usd, show=a.show)
        return 0
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
                state, _ = pass_once(a.db, state, kinds_for(mode), notifier, int(time.time() * 1000), names, min_usd,
                                     count_kinds=count_kinds_for(mode))
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
