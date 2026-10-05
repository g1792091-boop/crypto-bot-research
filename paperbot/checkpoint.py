"""30-day checkpoint verdicts of the paper run (v3: docs/paper-v3-rules.md section 4, confirmed addendum
docs/paper-v3-rules-addendum.md Q1-Q3, the addendum's '확정 내용' table wins; paper v4 since the 2026-10 restart:
docs/paper-v4-verdict.md, which records this file's sha256 and wins where it differs from the v3 text below).

Paper v4 (owners' decisions D5, D6, D7 of 2026-10-05; section "Paper v4" at the end of this docstring has the details)
    Four groups of original accounts: core (the 36, kind "strategy"), ds200 (44 DeepSeek-200 definitions), reel
    (REEL_H1@5m) and the coin flips. Judged: core and ds200 on 15m / 30m / 1h, the reel on 5m; 4h and the coin flips
    are observation only. Three FDR families with their own Benjamini-Hochberg (alpha-split, sum 0.10): core + copies
    of core parents + new-strategy accounts at 0.07, ds200 (+ its copies) at 0.025, reel at 0.005. 10,000 coin-flip
    bots per judged account (the weekly rehearsal 2,000). The bots copy the account's own long share, its coin set
    and its ET-session bar mask; the reel's bots trade with the reel's own exits.

    python -m paperbot.checkpoint run  --db paper3.db --out checkpoint.db [--cache DIR] [--date YYYY-MM-DD]
        [--brackets FILE | --allow-example-brackets] [--bots N]
    python -m paperbot.checkpoint show --out checkpoint.db [--date YYYY-MM-DD]

When
    Checkpoints are 00:00 UTC (09:00 KST) on day 30, 60, 90, ... after the run start (the UTC
    date of the first account's creation in paper3.db). The job runs hourly and does nothing until
    a checkpoint is due and the live runner has saved its ``day:<date>`` state for it (no Binance call
    before that). An error while a due checkpoint has no verdict sends one WARN per date and error type
    and fails the run (the timer retries); a verdict Telegram did not take is sent again on the next run.
    A rehearsal on the real data that never touches checkpoint.db: ``paperbot.checkpoint_preview``.

Q2 snapshot
    At the checkpoint the runner itself keeps the state of every account before the 00:00 step
    (``day:<date>``, paperbot/accounts.py). This job copies it, with the closed trades and the
    signal counts it needs, into one canonical JSON document, hashes it (sha256) and stores it in
    an append-only table of ``--out``. The verdict reads only that snapshot (hash checked).
    Evaluated equity = wallet + unrealised P&L at the mark price - estimated exit cost (taker fee
    + slippage on the current notional). A trade belongs to the period it was entered in: a
    position open at the checkpoint counts as a trade of the period that ends there, valued then.

Q3 schedule
    Each account (strategy x timeframe, and improved copies) gets its 1st verdict at the first
    checkpoint where it has >= 30 trades; 4h accounts and the live coin-flip accounts are
    observation only ('관찰용'). The judged timeframes are 15m, 30m and 1h (5m was removed at the restart
    of 2026-10-04, docs/paper-v3-rules-change-1.md), so the originals' Q1 family has at most 36 x 3 = 108
    accounts (``Q1_MAIN_FAMILY``). 1st pass = trades >= 30 and equity > starting equity and not bust
    and the Q1 luck test passed. A 1st pass is checked again on the next 30 days only (2nd check):
    >= 30 trades entered in them, positive P&L in them (scaled to the $5,000 start) and Q1 again on
    that window. A copy account's windows start at its own creation; it is judged at the run's
    checkpoints (so it shares their FDR family) once 30 days old.

Extra accounts (paperbot/extras.py: copies and new-strategy accounts)
    Each extra is judged from its own start (``created_ts``) and runs in its OWN Q1 group (its own
    seed, its own rule: a copy's first lock and stop distance), so the original accounts' groups, seeds,
    bots and p-values are exactly what they would be without extras. FDR: family A = the originals plus
    the copies (the addendum: "모든 계좌(개선 복사 계좌 포함)"); the originals' rows also keep ``q_orig``
    (their own BH); family B = the new-strategy accounts (their own BH). An extra's signals count from its
    start: a copy's are its parent's signals while it was active (minus the ones its skip tag drops), a
    new-strategy account's its own rows, with the bars missed in restarts left out of its rate. An
    extra's verdict rows carry ``created_ts``: an id re-used after a paper3 restore starts over. Code
    changes of the extras and an extra's own events (suspended, held, code accepted) are warnings that
    name only the affected extras.

Q1 luck test
    Per judged account, coin-flip bots (v3: 2,000; paper v4: ``N_BOTS``) run over the same window with the same
    rules and the same starting equity; each coin and bar of the account's timeframe fires with probability = the
    account's own signal rate in that window (signals / (6 coins x bars)), side 50/50 (as
    research/paper_rules/rules_bt.py ``random_signals``). p = (bots >= account + 1) / (bots + 1).
    Benjamini-Hochberg over every account tested at that checkpoint (v3: one family at 0.10; paper v4: per family,
    ``FAMILY_ALPHA``, ``method_ko`` says it in Korean).

    The bots run on the real 1m bars of the window (last and mark price, real funding times and
    rates) from Binance's public REST API, cached per coin and UTC day under ``--cache``, through a
    vectorised copy of the paper engine (``simulate_bots``): signal at the timeframe close, entry
    at the next minute's open plus slippage, stop 2 x ATR14 of the signal bar, the owners' sizing
    tiers with the exchange brackets (the restarted run's quality_v1 rule, config.V3_LEVERAGE_RULE: each
    bot signal is 'best' - 50x / 50%, 40x / 40%, then 30x / 30%, 20x / 20% - with probability p_best, else
    'normal' - 30x / 30%, 20x / 20%. p_best is the compared account's OWN cell share
    (paperbot/p_best_cells.json: the 5-year share of 'best' signals of that strategy x timeframe; 0 for a cell
    without quality edges, whose signals are always 'normal'); a copy uses its parent's cell, a new-strategy
    account 0. The live coin-flip accounts keep the pooled config.V3_P_BEST),
    coin priority, one position, stepped profit lock on 1m LAST
    high/low (applied from the next bar), liquidation on the mark price, bust below $10. A test
    checks it trade for trade against ``PaperEngine``. All bots of one timeframe and window run in
    one pass (each with its own account's rate), so no sharing of bots between accounts is needed.

The job never writes paper3.db (opened ``mode=ro``); everything goes to ``--out``.
Other code (agents, dashboard) reads results with ``latest_verdict``, ``account_status`` and
``statuses``.

Paper v4 (owners' decisions of 2026-10-05; docs/paper-v4-verdict.md records this file's sha256)
    Groups and families. Every account row of the snapshot (version 3) and of the verdict carries its family
    (``account_family``): "core" = kind strategy, copies of a core parent and new-strategy accounts; "ds200" = the
    DeepSeek-200 accounts and copies of them; "reel" = REEL_H1@5m (and copies of it); "flip" = the coin flips (never
    judged). Judged timeframes (D6, ``JUDGED_BY_FAMILY``): core and ds200 15m / 30m / 1h, reel 5m; 4h is observation
    only for every group.
    FDR (D5 (b), ``FAMILY_ALPHA``): Benjamini-Hochberg inside each family at its own alpha, core 0.07, ds200 0.025,
    reel 0.005; the run's FDR stays <= 0.10 because the families' FDRs add up. A family with no judged account tests
    nothing. ``q_orig`` = the BH of the family's original accounts alone, shown when extras share the family.
    Bots (``N_BOTS`` 10,000; the weekly rehearsal ``REHEARSAL_BOTS`` 2,000). One pass per (family, timeframe, window);
    the core passes keep the v3 seed, the others add ``FAMILY_SALT``, so the 36's p-values do not depend on whether the
    other groups exist. What the bots copy from their account (D7): the signal rate in the window, now per coin it can
    trade and per bar it can fire on; the long share of its signals in the window (``signals_long`` / ``signals``; a
    v2 snapshot without side counts keeps 50/50); its coin set (``COIN_EXCLUDE``: F14_SMT never trades BTC); its
    ET-session bar mask (``SESSION_RULES``, US Eastern wall clock of the bar's open with the US DST rule, for the five
    F15 session definitions); p_best: a core cell's own share (the cell must exist, ``MissingCell``), 0 for DeepSeek,
    the reel and new-strategy accounts. The reel's bots trade with the reel's own exits (``simulate_reel_bots``: the
    stop = the lowest low of the last 12 closed 5m bars minus 0.05 x ATR14, the first target the signal bar's upper
    band, then each closed 5m bar's band, the skip rules, the 96-bar time exit, no ladder; tested trade for trade
    against paperbot/reel_engine.py ``ReelEngine``).
    Holds and warnings. An account with trades but no recorded signal in its window is held (its rate would be 0
    and every bot would end flat: M9); fewer signals than trades is a warning. An account created before the
    checkpoint but missing from the runner's ``day:<date>`` state is held and listed (snapshot ``coverage``: expected
    vs found per group; M10). A restart whose recorded changes touch trading code warns with the groups it restarts
    (runinfo.groups_hit: the shared trading code every group, the DeepSeek or reel code that group only) and puts the
    note on those groups' rows only (D8, M12).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .config import (DS200_IDS, REEL_NAME, REEL_TF, V3_JUDGED_TFS, V3_OBSERVE_TFS, V3_P_BEST, V3_Q1_MAIN_FAMILY,
                     V3_STOP_ATR, V3_SYMBOLS, V4_GROUPS, Settings, v3_settings)
from .levrule import GROUP_SALT, edges as _quality_edges
from .margin import Brackets
from .notify import INFO, WARN, day_ko

MIN = 60_000
DAY_MS = 86_400_000
PERIOD_DAYS = 30
MIN_TRADES = 30
N_BOTS = 10_000                # paper v4 (owners' D5): the ds200 family needs >= 132 / 0.025 = 5,280 (v3: 2,000)
REHEARSAL_BOTS = 2_000         # the weekly rehearsal (checkpoint_preview): a pipeline check, not a verdict
ALPHA = 0.10                   # the whole run's FDR: the sum of the families' alphas
# Paper v4 FDR families (owners' D5 (b), alpha-split): each family has its own Benjamini-Hochberg at its alpha. The
# overall FDR stays <= sum = 0.10 (FDR_total <= sum of the families' FDRs). Copies join their parent's family,
# new-strategy accounts the core family.
FAMILY_ALPHA = {"core": 0.07, "ds200": 0.025, "reel": 0.005}
FAMILIES = tuple(FAMILY_ALPHA)
FAMILY_KO = {"core": "매매법", "ds200": "딥시크", "reel": "5분 단타"}
# Judged timeframes per family (config.V4_GROUPS, owners' D6): core and ds200 15m / 30m / 1h, the reel 5m.
JUDGED_BY_FAMILY = {g: tuple(V4_GROUPS[g]["judged"]) for g in FAMILIES}
OBSERVE_TFS = V3_OBSERVE_TFS                   # 4h: observation only (Q3), every group
JUDGED_TFS = V3_JUDGED_TFS                     # the core group's 15m / 30m / 1h
Q1_MAIN_FAMILY = V3_Q1_MAIN_FAMILY             # 36 x 3 = 108 core accounts can enter the core family
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
# Seed salt of each family's bot passes (the core passes keep the v3 seed, so the 36's bots are exactly what they
# would be without the other groups).
FAMILY_SALT = {"core": None, "ds200": 0xD5200, "reel": 0x5EE15}
# The coins an account can trade (owners' D7): F14_SMT compares a coin with BTC and never trades BTC itself.
COIN_EXCLUDE = {"F14_SMT": ("BTCUSDT",)}
# The ET-session definitions (DeepSeek F15, research/deepseek200/lib_c.py session_signals; 15m / 30m / 1h only): the
# signal bars on which they can fire at all, by the US Eastern wall-clock minute of the bar's OPEN (US DST rule):
# ("window", from, to) = from <= minute < to; ("judge", t_ref) = the one judging bar of the ET day: the first bar at
# or after the bar holding t_ref whose close is at or after t_ref + 60 minutes.
SESSION_RULES = {"F15_ASIA_BRK": ("window", 0, 480), "F15_ASIA_SWEEP": ("window", 0, 480),
                 "F15_LON_BRK": ("window", 300, 720), "F15_OPEN0930": ("judge", 570), "F15_OPEN0000": ("judge", 0)}
ATR_PREFIX_BARS = 300          # TF bars before the window for ATR14 (Wilder; (13/14)^300 ~ 2e-10)
NO_VERDICT_DAYS = 180          # addendum Q3: still < 30 trades at day 180 -> '판정 불가'
SNAPSHOT_VERSION = 3          # 2: extras carry rule / events / skipped bars; 3 (v4): every account also carries
#                               "group", "signals_long" and "signals_coin", the snapshot "coverage" (v2 fields unchanged)
ORIG = "orig"
EXTRA_KINDS = ("copy", "newlab")
EXTRAS_ONLY_KO = "추가 계좌만 해당"

HOLD, PASS1, FAIL, PASS2, OBSERVE = "보류", "1차 합격", "불합격", "2차 통과", "관찰용"
STATUSES = (HOLD, PASS1, FAIL, PASS2, OBSERVE)
# signal_log statuses that are a strategy signal on a trade coin (RECORD = 1d / XRP only)
SIGNAL_STATUSES = ("SUBMITTED", "LATE", "NO_PRICE", "NO_ATR")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    date TEXT PRIMARY KEY, cp_ts INTEGER NOT NULL, created_ts INTEGER NOT NULL,
    sha256 TEXT NOT NULL, data TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS snapshots_frozen_u BEFORE UPDATE ON snapshots
BEGIN SELECT RAISE(ABORT, 'checkpoint snapshots are frozen'); END;
CREATE TRIGGER IF NOT EXISTS snapshots_frozen_d BEFORE DELETE ON snapshots
BEGIN SELECT RAISE(ABORT, 'checkpoint snapshots are frozen'); END;
CREATE TABLE IF NOT EXISTS verdicts (
    date TEXT PRIMARY KEY, ts INTEGER NOT NULL, snapshot_sha256 TEXT NOT NULL, data TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS verdicts_frozen_u BEFORE UPDATE ON verdicts
BEGIN SELECT RAISE(ABORT, 'checkpoint verdicts are final'); END;
CREATE TRIGGER IF NOT EXISTS verdicts_frozen_d BEFORE DELETE ON verdicts
BEGIN SELECT RAISE(ABORT, 'checkpoint verdicts are final'); END;
CREATE TABLE IF NOT EXISTS verdict_accounts (
    date TEXT NOT NULL, account_id TEXT NOT NULL, status TEXT NOT NULL, stage TEXT,
    p REAL, q REAL, data TEXT NOT NULL, PRIMARY KEY (date, account_id));
CREATE TABLE IF NOT EXISTS job_log (ts INTEGER NOT NULL, date TEXT, text TEXT NOT NULL);
"""


# ====================================================================== small helpers
def ro_connect(path: str) -> sqlite3.Connection:
    """Read-only connection (the live runner is paper3.db's only writer)."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    uri = f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30)


def day_str(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def day_ms(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def floor_day(ms: int) -> int:
    return ms - ms % DAY_MS


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def checkpoint_ts(run_start: int, k: int) -> int:
    """00:00 UTC of day 30k after the run start."""
    return floor_day(run_start) + k * PERIOD_DAYS * DAY_MS


def due_checkpoints(run_start: int, now_ms: int) -> list[tuple[int, int]]:
    """[(k, cp_ts)] of checkpoints at or before now, up to day NO_VERDICT_DAYS (rules: after day 180 the run is
    observation only, no new verdicts)."""
    out, k = [], 1
    while k * PERIOD_DAYS <= NO_VERDICT_DAYS and checkpoint_ts(run_start, k) <= now_ms:
        out.append((k, checkpoint_ts(run_start, k)))
        k += 1
    return out


def open_value(side: int, qty: float, entry: float, margin: float, mark: float, s: Settings) -> float:
    """What closing an open position at ``mark`` adds to the wallet: gross P&L minus the
    estimated exit cost (taker fee and slippage on the notional). Beyond the isolated margin the
    position would be liquidated (the engine's ``_close`` rule): the margin is lost."""
    gross = side * qty * (mark - entry)
    if gross < -margin:
        return -margin
    return gross - qty * mark * (s.taker_fee + s.slippage_frac)


# ====================================================================== Q2 snapshot
def run_facts(conn: sqlite3.Connection) -> dict:
    """Run start (first account creation), starting equity and fee from the run state."""
    st = conn.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
    run = json.loads(st[0]) if st else {}
    from .accounts import ORIGINAL_KINDS
    r = conn.execute(f"SELECT MIN(created_ts) FROM accounts WHERE kind IN ({','.join('?' * len(ORIGINAL_KINDS))})",
                     ORIGINAL_KINDS).fetchone()
    start = r[0] if r and r[0] is not None else None
    if start is None:
        r = conn.execute("SELECT MIN(started_ts) FROM runs").fetchone()
        start = r[0] if r else None
    return {"start_ts": None if start is None else int(start),
            "initial_equity": float(run.get("initial_equity", 5000.0)),
            "taker_fee": run.get("taker_fee"), "settings_version": run.get("settings")}


def _trading_changes(conn: sqlite3.Connection, upto: int) -> list[dict]:
    """Starts of the runner whose recorded changes touch fills, exits or sizing (Q5). Paper v4 (D8): also the group
    keys (runinfo.GROUP_WATCHED: the DeepSeek and the reel code); each entry names the groups whose window it restarts
    (``groups``: runinfo.groups_hit; a shared trading key hits every group)."""
    from . import runinfo as RI
    trading = {k for k, _, t in RI.WATCHED if t}
    group_keys = {k for k, _, t in getattr(RI, "GROUP_WATCHED", ()) if t}
    out = []
    for ts, data in conn.execute("SELECT started_ts, data FROM runs WHERE started_ts < ? ORDER BY id", (upto,)):
        ch = [c for c in json.loads(data).get("changes", []) if c in trading or c in group_keys]
        if ch:
            out.append({"ts": int(ts), "changes": ch, "groups": list(_groups_hit(ch))})
    return out


def _groups_hit(keys) -> tuple:
    """runinfo.groups_hit, or every group when that module does not have it."""
    try:
        from .runinfo import groups_hit
    except ImportError:
        return ("core", "ds200", "reel", "flip", "extra")
    return tuple(groups_hit(keys))


def _extras_state(conn: sqlite3.Connection) -> dict:
    try:
        r = conn.execute("SELECT data FROM state WHERE k = 'extras'").fetchone()
    except sqlite3.Error:
        return {}
    try:
        return json.loads(r[0]) if r else {}
    except ValueError:
        return {}


def _extra_code_changes(conn: sqlite3.Connection, upto: int) -> list[dict]:
    """Starts of the runner whose recorded changes touch the extras' trading code (runinfo.EXTRA_WATCHED) or the
    signal input code they share with the originals (runinfo.SHARED_WATCHED; for the originals that is open question
    Q-11, the rule keeper's decision, so it is noted on the extras' rows only)."""
    from .runinfo import EXTRA_WATCHED, SHARED_WATCHED
    keys = {k for k, _, t in EXTRA_WATCHED + SHARED_WATCHED if t}
    out = []
    for ts, data in conn.execute("SELECT started_ts, data FROM runs WHERE started_ts < ? ORDER BY id", (upto,)):
        ch = [c for c in json.loads(data).get("changes", []) if c in keys]
        if ch:
            out.append({"ts": int(ts), "changes": ch})
    return out


def _extra_signals(conn: sqlite3.Connection, kind: str, strat: str, tf: str, parent: Optional[str], created: int,
                   cp_ts: int, rule: dict, timeline: list, symbols, longs: Optional[dict] = None,
                   coins: Optional[dict] = None) -> dict:
    """{day: n} of an extra's signals from its start: a copy's parent rows while it was active (minus the ones
    its skip tag drops), a new-strategy account's own rows. ``longs`` / ``coins`` (dicts, filled when given): the
    same rows' {day: long signals} and {day: {symbol: n}} (snapshot v3)."""
    from .daily3 import extra_status
    from .extras import skip_hit
    src_strat, src_tf = (parent.split("@", 1) if kind == "copy" and parent and "@" in parent else (strat, tf))
    q = ("SELECT bar_close, side, data, symbol FROM signal_log WHERE strategy = ? AND timeframe = ? AND bar_close >= ? "
         f"AND bar_close < ? AND status IN ({','.join('?' * len(SIGNAL_STATUSES))}) "
         f"AND symbol IN ({','.join('?' * len(symbols))})")
    out: dict = {}
    x = {"timeline": timeline}
    tag = rule.get("skip_tag")
    for bc, side, data, sym in conn.execute(q, (src_strat, src_tf, created, cp_ts, *SIGNAL_STATUSES, *symbols)):
        if kind == "copy":
            if bc <= created or extra_status(x, int(bc) - MIN) != "active":
                continue
            if tag:
                try:
                    ctx = (json.loads(data or "{}") or {}).get("ctx") or {}
                except (ValueError, AttributeError):
                    ctx = {}
                if skip_hit(tag, int(side), ctx):
                    continue
        d = day_str(int(bc) // DAY_MS * DAY_MS)
        out[d] = out.get(d, 0) + 1
        if longs is not None and int(side) > 0:
            longs[d] = longs.get(d, 0) + 1
        if coins is not None:
            coins.setdefault(d, {})
            coins[d][sym] = coins[d].get(sym, 0) + 1
    return out


def freeze_snapshot(conn: sqlite3.Connection, cp_ts: int, symbols=V3_SYMBOLS,
                    settings: Optional[Settings] = None) -> Optional[dict]:
    """The Q2 snapshot of every account at ``cp_ts`` (00:00 UTC), from the runner's own
    ``day:<date>`` state. None when the runner has not saved that state (yet)."""
    date = day_str(cp_ts)
    row = conn.execute("SELECT ts, data FROM state WHERE k = ?", ("day:" + date,)).fetchone()
    if row is None:
        return None
    facts = run_facts(conn)
    s = settings or v3_settings(**({"taker_fee": facts["taker_fee"]} if facts["taker_fee"] else {}))
    state = json.loads(row[1])
    engines = state.get("engines", {})
    trades: dict[str, list] = {}
    for aid, et, xt, pnl in conn.execute("SELECT account_id, entry_time, exit_time, pnl FROM trades "
                                         "WHERE exit_time < ? ORDER BY id", (cp_ts,)):
        trades.setdefault(aid, []).append([int(et), int(xt), round(float(pnl), 8)])
    sig: dict[tuple, dict] = {}
    sig_long: dict[tuple, dict] = {}
    sig_coin: dict[tuple, dict] = {}
    q = ("SELECT strategy, timeframe, bar_close / 86400000 AS d, symbol, side > 0, COUNT(*) FROM signal_log "
         f"WHERE bar_close < ? AND status IN ({','.join('?' * len(SIGNAL_STATUSES))}) "
         f"AND symbol IN ({','.join('?' * len(symbols))}) GROUP BY strategy, timeframe, d, symbol, side > 0")
    for strat, tf, d, sym, is_long, n in conn.execute(q, (cp_ts, *SIGNAL_STATUSES, *symbols)):
        day = day_str(int(d) * DAY_MS)
        key = (strat, tf)
        sig.setdefault(key, {})[day] = sig.get(key, {}).get(day, 0) + int(n)
        if is_long:
            sig_long.setdefault(key, {})[day] = sig_long.get(key, {}).get(day, 0) + int(n)
        cd = sig_coin.setdefault(key, {}).setdefault(day, {})
        cd[sym] = cd.get(sym, 0) + int(n)
    accounts = {}
    xstate = None
    rows_all = conn.execute("SELECT account_id, strategy, timeframe, kind, created_ts, parent, data FROM accounts "
                            "ORDER BY rowid").fetchall()
    kinds = {r[0]: r[3] for r in rows_all}
    expected: dict[str, int] = {}
    found: dict[str, int] = {}
    missing: list[dict] = []
    for aid, strat, tf, kind, created, parent, adata in rows_all:
        if created >= cp_ts:
            continue
        grp = account_family(kind, strat, parent, kinds)
        expected[grp] = expected.get(grp, 0) + 1
        e = engines.get(aid)
        if e is None:
            # M10: an account the runner did not save at the checkpoint is not dropped silently: it is listed, held
            # (no verdict) and warned about, naming its group
            missing.append({"account_id": aid, "strategy": strat, "timeframe": tf, "kind": kind,
                            "created_ts": int(created), "parent": parent, "group": grp})
            continue
        found[grp] = found.get(grp, 0) + 1
        pos = e.get("position")
        mark = None
        cpos = None
        equity = float(e["wallet"])
        if pos is not None:
            mark = float(e.get("last_mark", {}).get(pos["symbol"], pos["entry_price"]))
            cpos = {k: pos[k] for k in ("symbol", "side", "qty", "entry_price", "entry_time", "leverage",
                                        "margin", "entry_fee", "funding_paid")}
            equity += open_value(int(pos["side"]), float(pos["qty"]), float(pos["entry_price"]),
                                 float(pos["margin"]), mark, s)
        accounts[aid] = {
            "strategy": strat, "timeframe": tf, "kind": kind, "created_ts": int(created), "parent": parent,
            "wallet": round(float(e["wallet"]), 8), "bust": bool(e.get("bust")), "halted": bool(e.get("halted")),
            "position": cpos, "mark": mark, "equity": round(equity, 8),
            "trades": trades.get(aid, []), "signals": sig.get((strat, tf), {}),
            "group": grp, "signals_long": sig_long.get((strat, tf), {}), "signals_coin": sig_coin.get((strat, tf), {}),
        }
        if kind in EXTRA_KINDS:
            from .daily3 import EXTRA_STATUS
            from .extras import parse_rule, rule_fields
            if xstate is None:
                xstate = _extras_state(conn)
            try:
                d = json.loads(adata or "{}")
            except ValueError:
                d = {}
            f = rule_fields(parse_rule(d.get("rule")) if kind == "copy" else None)
            rule = {"stop_atr": f["stop_atr"], "first_lock": f["first_lock"] if f["first_lock"] is not None
                    else s.ladder_first_lock, "skip_tag": f["skip_tag"]}
            evs = [ev for ev in (xstate.get("events") or []) if ev.get("account_id") == aid
                   and int(ev.get("ts") or 0) < cp_ts]
            tl = sorted([(int(created), "active")] + [(int(ev.get("effective", ev.get("ts", 0)) or 0),
                                                       EXTRA_STATUS[ev["event"]])
                                                      for ev in evs if ev.get("event") in EXTRA_STATUS
                                                      and ev.get("event") != "created"], key=lambda t: t[0])
            a = accounts[aid]
            a["rule"] = rule
            a["events"] = [{k: ev.get(k) for k in ("ts", "event", "code", "detail", "effective") if k in ev}
                           for ev in evs]
            xl: dict = {}
            xc: dict = {}
            a["signals"] = _extra_signals(conn, kind, strat, tf, parent, int(created), cp_ts, rule,
                                          [list(t) for t in tl], symbols, longs=xl, coins=xc)
            a["signals_long"], a["signals_coin"] = xl, xc
            if kind == "newlab":
                runs = (xstate.get("health") or {}).get("skipped_runs") or []
                a["skipped_runs"] = [[int(r0), int(r1)] for r0, r1 in runs if int(r1) >= int(created)
                                     and int(r0) < cp_ts]
    return {
        "version": SNAPSHOT_VERSION, "date": date, "cp_ts": cp_ts,
        "source": {"state_key": "day:" + date, "state_ts": int(row[0]), "state_sha256": sha256_text(row[1])},
        "run": {"start_ts": facts["start_ts"], "initial_equity": facts["initial_equity"],
                "taker_fee": s.taker_fee, "slippage": s.slippage_frac, "settings_version": facts["settings_version"],
                "trading_changes": _trading_changes(conn, cp_ts),
                "extra_code_changes": _extra_code_changes(conn, cp_ts)},
        "symbols": list(symbols), "accounts": accounts,
        "coverage": {"expected": expected, "found": found, "missing": missing},
    }


def open_out(path: str) -> sqlite3.Connection:
    out = sqlite3.connect(path, timeout=30)
    out.execute("PRAGMA journal_mode=WAL")
    out.executescript(SCHEMA)
    out.commit()
    return out


def store_snapshot(out: sqlite3.Connection, snap: dict, now_ms: int) -> str:
    """Insert once (the table refuses updates and deletes). Returns the sha256."""
    text = canonical(snap)
    h = sha256_text(text)
    have = out.execute("SELECT sha256 FROM snapshots WHERE date = ?", (snap["date"],)).fetchone()
    if have is not None:
        return have[0]
    out.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)", (snap["date"], snap["cp_ts"], now_ms, h, text))
    out.commit()
    return h


class SnapshotTampered(RuntimeError):
    pass


def load_snapshot(out: sqlite3.Connection, date: str) -> Optional[tuple[dict, str]]:
    r = out.execute("SELECT sha256, data FROM snapshots WHERE date = ?", (date,)).fetchone()
    if r is None:
        return None
    if sha256_text(r[1]) != r[0]:
        raise SnapshotTampered(f"snapshot {date}: stored hash {r[0][:12]} does not match its data")
    return json.loads(r[1]), r[0]


# ====================================================================== period statistics
def period_stats(acct: dict, lo: int, hi: int, s: Settings, initial: float) -> dict:
    """Trades entered in [lo, hi) (closed before ``hi`` or still open at the snapshot ``hi``),
    their P&L (open one at the snapshot value), and the account's signal count in the window."""
    closed = [t for t in acct["trades"] if lo <= t[0] < hi and t[1] < hi]
    pnl = sum(t[2] for t in closed)
    n = len(closed)
    pos = acct.get("position")
    if pos is not None and lo <= pos["entry_time"] < hi:
        n += 1
        pnl += (open_value(pos["side"], pos["qty"], pos["entry_price"], pos["margin"], acct["mark"], s)
                - pos["entry_fee"] - pos["funding_paid"])
    lo_d, hi_d = day_str(lo), day_str(hi - 1)
    sigs = sum(v for d, v in acct["signals"].items() if lo_d <= d <= hi_d)
    out = {"trades": n, "pnl": pnl, "signals": sigs}
    if "signals_long" in acct:                  # snapshot v3: the long share of the window's signals (D7)
        out["signals_long"] = sum(v for d, v in acct["signals_long"].items() if lo_d <= d <= hi_d)
    if "skipped_runs" in acct:
        out["skipped_bars"] = skipped_bars(acct["skipped_runs"], acct["timeframe"], lo, hi, acct["created_ts"])
    return out


def skipped_bars(runs, tf: str, lo: int, hi: int, created: int) -> int:
    """Bars of ``tf`` closing in [lo, hi) after ``created`` whose boundary the runner did not compute for the
    new-strategy accounts (catch-up after a restart; extras state health.skipped_runs [[from, to], ...])."""
    if tf not in TF_MS:
        return 0
    span, n = TF_MS[tf], 0
    for a, b in runs or []:
        a, b = max(int(a), lo, int(created) + 1), min(int(b), hi - 1)
        if b < a:
            continue
        first = -(-a // span) * span
        if first <= b:
            n += (b - first) // span + 1
    return n


def signal_rate(signals: int, tf: str, lo: int, hi: int, coins: int = 6, skipped: int = 0,
                session: Optional[str] = None) -> float:
    """Signals per coin and bar of the window: ``signals`` / (``coins`` x bars closing in [lo, hi), minus the
    ``skipped`` ones). ``session``: an ET-session definition (SESSION_RULES): only the bars it can fire on count."""
    span = TF_MS[tf]
    first = -(-lo // span) * span
    bars = max(0, (hi - 1 - first) // span + 1) if hi > first else 0
    if session is not None and bars:
        bars = int(np.count_nonzero(session_mask(session, tf, first + np.arange(bars, dtype=np.int64) * span)))
    return signals / max(coins * max(bars - int(skipped), 0), 1)


# ====================================================================== v4 groups, coin sets and session masks
def account_family(kind: Optional[str], strategy: Optional[str], parent: Optional[str] = None,
                   kinds: Optional[dict] = None) -> str:
    """The verdict family of an account (D5): "core" (kind strategy, a copy of a core parent, a new-strategy
    account), "ds200", "reel", or "flip" (the coin flips, never judged). A copy joins its parent's family (the parent's
    kind from ``kinds`` {account_id: kind}, else its strategy name)."""
    if kind == "random":
        return "flip"
    if kind == "copy":
        pk = (kinds or {}).get(parent) if parent else None
        if pk is None and isinstance(parent, str) and "@" in parent:
            pname = parent.split("@", 1)[0]
            pk = "ds200" if pname in DS200_IDS else "reel" if pname == REEL_NAME else "strategy"
        if pk is None:
            pk = "ds200" if strategy in DS200_IDS else "reel" if strategy == REEL_NAME else "strategy"
        return account_family(pk, strategy)
    if kind == "ds200":
        return "ds200"
    if kind == "reel":
        return "reel"
    return "core"                  # "strategy", "newlab" (and an unknown kind: never a group of its own)


def _nth_sunday(year: int, month: int, nth: int) -> int:
    d = dt.date(year, month, 1)
    first = d + dt.timedelta(days=(6 - d.weekday()) % 7)
    return (first - dt.date(1970, 1, 1)).days + 7 * (nth - 1)


def et_offset_minutes(ms: int) -> int:
    """UTC offset of US Eastern time at ``ms`` in minutes (-240 EDT / -300 EST): DST from the second Sunday of March
    07:00 UTC to the first Sunday of November 06:00 UTC (US rule since 2007, as lib_c.et_offset_minutes)."""
    y = dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).year
    a = _nth_sunday(y, 3, 2) * DAY_MS + 7 * 3_600_000
    b = _nth_sunday(y, 11, 1) * DAY_MS + 6 * 3_600_000
    return -240 if a <= int(ms) < b else -300


def et_minute(ms: int) -> int:
    """Minute of the day on the US Eastern wall clock at ``ms`` (UTC epoch milliseconds)."""
    wall = int(ms) + et_offset_minutes(ms) * MIN
    return int(wall % DAY_MS // MIN)


def session_mask(name: Optional[str], tf: str, closes) -> np.ndarray:
    """For bars of ``tf`` closing at ``closes`` (ms): can the ET-session definition ``name`` fire on that bar
    (SESSION_RULES, by the ET minute of the bar's open)? All True for a name without a session rule."""
    closes = np.asarray(closes, np.int64).reshape(-1)
    rule = SESSION_RULES.get(name) if name else None
    if rule is None:
        return np.ones(len(closes), bool)
    span = TF_MS[tf]
    tfm = span // MIN
    mins = np.array([et_minute(int(t) - span) for t in closes], np.int64)
    if rule[0] == "window":
        return (mins >= rule[1]) & (mins < rule[2])
    tref = int(rule[1])
    r0 = tref // tfm * tfm
    s0 = max(r0, -(-(tref + 60 - tfm) // tfm) * tfm)
    return mins == s0


def session_of(strategy: Optional[str], kind: Optional[str]) -> Optional[str]:
    """The session rule an account's bots follow: a DeepSeek ET-session definition (or a copy of one), else None."""
    return strategy if strategy in SESSION_RULES and kind in ("ds200", "copy") else None


def coins_of(strategy: Optional[str], kind: Optional[str], symbols=V3_SYMBOLS) -> tuple:
    """The coins an account can trade (D7): every trade coin, F14_SMT (and a copy of it) without BTC."""
    out = tuple(symbols)
    if kind in ("ds200", "copy") and strategy in COIN_EXCLUDE:
        out = tuple(x for x in out if x not in COIN_EXCLUDE[strategy])
    return out


# ====================================================================== Q1 statistics
def luck_p(value: float, bots: np.ndarray) -> float:
    """p = (bots at or above the account + 1) / (bots + 1)."""
    bots = np.asarray(bots, float)
    return float((np.count_nonzero(bots >= value - 1e-9) + 1) / (len(bots) + 1))


def bh(pvals, alpha: float = ALPHA) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg: (q-values, rejected at FDR ``alpha``). q_i = min_{j>=i} p_(j) m / j."""
    p = np.asarray(pvals, float)
    m = len(p)
    if m == 0:
        return np.zeros(0), np.zeros(0, bool)
    order = np.argsort(p, kind="mergesort")
    ranked = p[order] * m / np.arange(1, m + 1)
    qs = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.minimum(qs, 1.0)
    # the step-up rule itself: reject the k smallest, k = max{i: p_(i) <= i alpha / m}
    ok = np.nonzero(p[order] <= np.arange(1, m + 1) * alpha / m)[0]
    rej = np.zeros(m, bool)
    if len(ok):
        rej[order[: ok[-1] + 1]] = True
    return q, rej


# ====================================================================== 1m bars
@dataclass
class Minutes:
    """Aligned 1m bars of the trade coins: ``ts`` (T,) open times, every minute; prices (T, C)
    with NaN where a coin has no bar; ``fr`` (T, C) funding rate settled at that minute or NaN."""
    ts: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741
    c: np.ndarray
    mo: np.ndarray
    mh: np.ndarray
    ml: np.ndarray
    mc: np.ndarray
    fr: np.ndarray
    symbols: tuple

    def window(self, lo: int, hi: int) -> "Minutes":
        a, b = np.searchsorted(self.ts, lo), np.searchsorted(self.ts, hi)
        return Minutes(self.ts[a:b], *(getattr(self, k)[a:b] for k in
                                      ("o", "h", "l", "c", "mo", "mh", "ml", "mc", "fr")), self.symbols)


def empty_minutes(lo: int, hi: int, symbols) -> Minutes:
    ts = np.arange(lo, hi, MIN, dtype=np.int64)
    nan = lambda: np.full((len(ts), len(symbols)), np.nan)  # noqa: E731
    return Minutes(ts, *(nan() for _ in range(9)), tuple(symbols))


class BinanceMinutes:
    """1m last and mark price klines and funding from Binance's public REST API (no key), cached
    per coin and UTC day as .npz under ``cache_dir`` (only complete past days are cached).

    Paced for a server whose live bot polls the same IP: ``pause`` (1 s) after each weight-10 kline call keeps this
    at <= 600 weight a minute (the IP limit is 2,400), and funding is fetched once per coin for every uncached day
    of the range (``_funding``), not once per coin and day (/fapi/v1/fundingRate has its own 500 calls / 5 min per
    IP, which the live feed's polls already use most of). The cached values are the same either way."""

    def __init__(self, rest, cache_dir: Optional[str], symbols=V3_SYMBOLS, pause: float = 1.0,
                 now_ms: Optional[Callable[[], int]] = None):
        self.rest, self.cache, self.symbols, self.pause = rest, cache_dir, tuple(symbols), pause
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.fetched_days = 0
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def _path(self, sym: str, d0: int) -> Optional[str]:
        return os.path.join(self.cache, f"{sym}_{day_str(d0)}.npz") if self.cache else None

    def _funding(self, sym: str, lo: int, hi: int) -> list:
        """Every funding row of ``sym`` with lo <= fundingTime < hi, in pages of 1000 (one page is ~333 days of
        8-hourly funding)."""
        out, t = [], int(lo)
        while t < hi:
            raw = self.rest.funding_rates(sym, start_time=t, limit=1000)
            time.sleep(self.pause)
            rows = [r for r in raw if t <= int(r["fundingTime"]) < hi]
            out += rows
            if len(raw) < 1000 or not rows:
                break
            t = int(rows[-1]["fundingTime"]) + 1
        return out

    def _day(self, sym: str, d0: int, funding: Optional[list] = None) -> dict:
        path = self._path(sym, d0)
        if path and os.path.exists(path):
            z = np.load(path)
            return {k: z[k] for k in z.files}
        d1 = d0 + DAY_MS
        rows = [r for r in self.rest.klines(sym, "1m", start_time=d0, limit=1500) if int(r[0]) < d1]
        time.sleep(self.pause)
        marks = {int(r[0]): r for r in self.rest.mark_klines(sym, "1m", start_time=d0, limit=1500)
                 if int(r[0]) < d1}
        time.sleep(self.pause)
        if funding is None:
            funding = self._funding(sym, d0, d1)
        fund = [r for r in funding if d0 <= int(r["fundingTime"]) < d1]
        t = np.array([int(r[0]) for r in rows], np.int64)
        last = np.array([[float(r[k]) for k in (1, 2, 3, 4)] for r in rows], float).reshape(-1, 4)
        mk = np.array([[float(marks[int(r[0])][k]) if int(r[0]) in marks else np.nan for k in (1, 2, 3, 4)]
                       for r in rows], float).reshape(-1, 4)
        out = {"t": t, "last": last, "mark": mk,
               "fts": np.array([int(r["fundingTime"]) for r in fund], np.int64),
               "frate": np.array([float(r["fundingRate"]) for r in fund], float)}
        self.fetched_days += 1
        if path and d1 <= self.now_ms() - 5 * MIN:
            tmp = path + ".part.npz"
            np.savez_compressed(tmp, **out)
            os.replace(tmp, path)
        return out

    def load(self, lo: int, hi: int) -> Minutes:
        m = empty_minutes(lo, hi, self.symbols)
        end = floor_day(hi - 1) + DAY_MS
        for k, sym in enumerate(self.symbols):
            d = floor_day(lo)
            funding = None
            while d < hi:
                path = self._path(sym, d)
                if funding is None and not (path and os.path.exists(path)):
                    funding = self._funding(sym, d, end)       # one call per coin for every day still to fetch
                got = self._day(sym, d, funding)
                t = got["t"]
                keep = (t >= lo) & (t < hi)
                idx = (t[keep] - lo) // MIN
                for j, name in enumerate(("o", "h", "l", "c")):
                    getattr(m, name)[idx, k] = got["last"][keep, j]
                    getattr(m, "m" + name)[idx, k] = got["mark"][keep, j]
                ft = got["fts"]
                fk = (ft >= lo) & (ft < hi)
                m.fr[(ft[fk] - ft[fk] % MIN - lo) // MIN, k] = got["frate"][fk]
                d += DAY_MS
        return m


def tf_atr(m: Minutes, tf: str) -> tuple[np.ndarray, np.ndarray]:
    """ATR14 (Wilder, as the locked code's fg_indicators.atr) of every TF bar built from the 1m
    bars. Returns (close_times (B,), atr (B, C)): the ATR of the bar that closes at close_times."""
    import pandas as pd
    span = TF_MS[tf]
    per = span // MIN
    a0 = int(np.searchsorted(m.ts, -(-int(m.ts[0]) // span) * span))
    n = (len(m.ts) - a0) // per
    if n <= 0:
        return np.zeros(0, np.int64), np.zeros((0, len(m.symbols)))
    sl = slice(a0, a0 + n * per)
    shape = (n, per, len(m.symbols))
    with np.errstate(all="ignore"), _quiet():
        hi = np.nanmax(m.h[sl].reshape(shape), axis=1)
        lo = np.nanmin(m.l[sl].reshape(shape), axis=1)
        cc = m.c[sl].reshape(shape)
    # close = last present 1m close of the bin
    present = ~np.isnan(cc)
    last_idx = per - 1 - np.argmax(present[:, ::-1, :], axis=1)
    close = np.take_along_axis(cc, last_idx[:, None, :], axis=1)[:, 0, :]
    close[~present.any(axis=1)] = np.nan
    ends = m.ts[a0] + (np.arange(n, dtype=np.int64) + 1) * span
    out = np.full((n, len(m.symbols)), np.nan)
    for k in range(len(m.symbols)):
        ok = ~np.isnan(close[:, k])          # resample drops empty bins
        df = pd.DataFrame({"high": hi[ok, k], "low": lo[ok, k], "close": close[ok, k]})
        prev = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
                       axis=1).max(axis=1)
        out[ok, k] = tr.ewm(alpha=1.0 / 14, adjust=False, min_periods=14).mean().to_numpy()
    return ends, out


class _quiet:
    def __enter__(self):
        import warnings
        self._w = warnings.catch_warnings()
        self._w.__enter__()
        warnings.simplefilter("ignore")

    def __exit__(self, *a):
        self._w.__exit__(*a)


# ====================================================================== the bots (vectorised engine)
@dataclass
class _BracketArrays:
    caps: np.ndarray
    maxlev: np.ndarray
    mmr: np.ndarray
    cum: np.ndarray

    @classmethod
    def of(cls, b: Brackets) -> "_BracketArrays":
        return cls(np.array([t.notional_cap for t in b.tiers], float), np.array([t.max_leverage for t in b.tiers]),
                   np.array([t.mmr for t in b.tiers], float), np.array([t.cum for t in b.tiers], float))


def size_vec(s: Settings, eq, side, fill, stop, atr, br: _BracketArrays, qty_step: float = 0.0,
             min_notional: float = 0.0, best=None) -> dict:
    """``sizing.size_position`` for many candidates of one coin at once (first passing candidate wins). The
    candidates are ``s.tier_chain("best")`` (tier walk: 'best', then lower), or with the "quality_v1" leverage
    rule the chain of each candidate's group: ``best`` (bool array, None = all True) marks the 'best' group, the
    others request 'normal'. Returns arrays ok, lev, qty, margin, liq, mmr, cum."""
    eq, side, fill, stop, atr = (np.asarray(x, float) for x in (eq, side, fill, stop, atr))
    n = len(eq)
    res = {k: np.zeros(n) for k in ("lev", "qty", "margin", "liq", "mmr", "cum")}
    todo0 = (eq > 0) & ((fill - stop) * side > 0)
    buffer = np.maximum(s.liq_buffer_min_frac * fill, s.liq_buffer_atr_mult * atr)
    dist = np.abs(fill - stop)
    exit_px = stop * (1 - side * s.slippage_frac)
    b = np.ones(n, bool) if best is None else np.asarray(best, bool)
    plans = [("best", b)] if s.leverage_rule == "tier_walk" else [("best", b), ("normal", ~b)]
    for group, rows in plans:
        _walk(s, s.tier_chain(group), todo0 & rows, eq, side, fill, stop, buffer, dist, exit_px, br, qty_step,
              min_notional, res)
    res["ok"] = res["lev"] > 0
    return res


def _walk(s: Settings, chain, todo, eq, side, fill, stop, buffer, dist, exit_px, br: _BracketArrays,
          qty_step: float, min_notional: float, res: dict) -> None:
    """size_vec's candidate loop over one chain for the rows ``todo`` (writes the winners into ``res``)."""
    n = len(eq)
    todo = todo.copy()
    for tier, lev in chain:
        margin = eq * tier.margin_frac
        raw = margin * lev / fill
        qty = np.floor(raw / qty_step + 1e-9) * qty_step if qty_step > 0 else raw
        notional = qty * fill
        c = (qty > 0) & (notional >= min_notional)
        margin = notional / lev
        bi = np.minimum(np.searchsorted(br.caps, notional, side="left"), len(br.caps) - 1)
        c &= lev <= br.maxlev[bi]
        mmr, cum = br.mmr[bi], br.cum[bi]
        with np.errstate(all="ignore"):
            liq = np.maximum((margin + cum - side * qty * fill) / (qty * mmr - side * qty), 0.0)
        c &= (stop - liq) * side >= buffer
        loss = (qty * dist + qty * np.abs(stop - exit_px) + notional * s.taker_fee + qty * exit_px * s.taker_fee)
        c &= loss <= s.max_loss_frac * eq
        good = todo & c
        for k, v in (("lev", np.full(n, float(lev))), ("qty", qty), ("margin", margin), ("liq", liq),
                     ("mmr", mmr), ("cum", cum)):
            res[k][good] = v[good]
        todo &= ~good


def has_quality_edges(strategy: str, tf: str) -> bool:
    """True when the strategy x timeframe has entry-quality edges (levrule): only then can a signal be 'best'."""
    try:
        return bool(_quality_edges().get(f"{strategy}|{tf}"))
    except (OSError, ValueError):
        return False


P_BEST_CELLS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "p_best_cells.json")
_P_BEST_CELLS: Optional[dict] = None


def p_best_cells() -> dict:
    """{"<strategy>|<tf>": {"signals", "best", "p_best"}} (paperbot/p_best_cells.json, loaded once)."""
    global _P_BEST_CELLS
    if _P_BEST_CELLS is None:
        with open(P_BEST_CELLS_PATH) as fh:
            _P_BEST_CELLS = json.load(fh)["cells"]
    return _P_BEST_CELLS


class MissingCell(LookupError):
    """A core account whose strategy x timeframe is not in p_best_cells.json (a renamed or misspelled cell): its bots'
    'best' share is unknown, so the verdict stops instead of comparing it with all-'normal' bots (paper v4, M3)."""


def cell_p_best(strategy: str, tf: str, strict: bool = False) -> float:
    """The Q1 bots' 'best' share for an account of ``strategy`` x ``tf``: that cell's own 5-year share of 'best'
    signals (0 for a cell without quality edges; a cell not in the file: 0, or ``MissingCell`` when ``strict``)."""
    cells = p_best_cells()
    key = f"{strategy}|{tf}"
    if strict and key not in cells:
        raise MissingCell(f"paperbot/p_best_cells.json has no cell {key} (a core account must have one)")
    c = cells.get(key)
    return float(c["p_best"]) if c else 0.0


def account_p_best(a: dict, kinds: Optional[dict] = None) -> float:
    """p_best of the bots compared with account ``a`` (snapshot row): a core strategy account its own cell (which must
    exist, ``MissingCell``), a copy of a core account its parent's cell (the copy trades its parent's signals and
    strength), a new-strategy account 0 (no edges), the DeepSeek and reel accounts and their copies 0 by rule (always
    'normal', owners' D7), the coin flips 0 (never judged)."""
    kind = a.get("kind")
    if kind == "newlab":
        return 0.0
    fam = a.get("group") or account_family(kind, a.get("strategy"), a.get("parent"), kinds)
    if fam != "core":
        return 0.0
    strat, tf = a.get("strategy"), a.get("timeframe")
    parent = a.get("parent")
    if kind == "copy" and isinstance(parent, str) and "@" in parent:
        strat, tf = parent.split("@", 1)
    return cell_p_best(strat, tf, strict=kind in ("strategy", "copy"))


def random_draws(rng: np.random.Generator, long_share=None):
    """Coin-flip signals as in rules_bt.random_signals: each coin and bar fires with the bot's
    rate, side long with probability ``long_share`` (None: 50/50, the v3 rule; paper v4 (D7): the compared account's
    own long share, one float or one per bot). The random stream is the same for every share."""
    p = 0.5 if long_share is None else np.asarray(long_share, float)

    def draw(ts: int, idx: np.ndarray, rates: np.ndarray, n_coins: int):
        fire = rng.random((len(idx), n_coins)) < rates[idx, None]
        side = np.where(rng.random((len(idx), n_coins)) < (p[idx, None] if np.ndim(p) else p), 1, -1)
        return fire, side
    return draw


def group_draws(rng: np.random.Generator, p_best):
    """The quality_v1 leverage group of each coin-flip signal: 'best' with probability ``p_best`` (one draw per bot,
    coin and signal bar, from its own stream so the fire / side draws are unchanged). ``p_best``: one share for
    every bot, or one per bot (array indexed like ``rates``)."""
    p = np.asarray(p_best, float)

    def draw(ts: int, idx: np.ndarray, n_coins: int) -> np.ndarray:
        return rng.random((len(idx), n_coins)) < (p[idx, None] if p.ndim else p)
    return draw


def simulate_bots(m: Minutes, tf: str, lo: int, hi: int, rates: np.ndarray, s: Settings,
                  brackets: dict, specs: Optional[dict] = None, seed=0, draw=None,
                  initial: Optional[float] = None, stop_atr: float = V3_STOP_ATR,
                  atr: Optional[tuple] = None, p_best=None, group_draw=None, long_share=None,
                  coin_mask=None, bar_mask=None, exits: str = "house") -> dict:
    """Coin-flip accounts on real 1m bars, the paper engine's rules (see the module docstring).

    ``m`` must start early enough for ATR14 of the first signal bar (``ATR_PREFIX_BARS``); the
    bots trade minutes in [lo, hi) and signals of bars closing at boundaries in [lo, hi). Each bot
    i fires with ``rates[i]``. With the "quality_v1" leverage rule each signal is 'best' with probability
    ``p_best`` (one float, or one per bot; default config.V3_P_BEST[tf]) and sizes with that group's chain
    (``group_draw(ts, idx, n_coins)`` -> bool array replaces the draw in tests). Returns final evaluated equity per
    bot (``equity``), wallet, bust flags and entered-trade counts.

    Paper v4 (D7): ``long_share`` (float or one per bot) is the bots' long probability (None = 50/50);
    ``coin_mask`` (bool, (C,) or (N, C)) the coins a bot may trade; ``bar_mask(ts, idx)`` -> bool per bot in ``idx``
    whether it may fire on the bar closing at ``ts`` (ET-session definitions). The masks act after the draws, so the
    random stream does not depend on them. ``exits="reel"``: the reel's own exits (``simulate_reel_bots``)."""
    if exits == "reel":
        return simulate_reel_bots(m, tf, lo, hi, rates, s, brackets, specs, seed=seed, draw=draw, initial=initial,
                                  atr=atr, p_best=p_best, group_draw=group_draw, coin_mask=coin_mask,
                                  bar_mask=bar_mask)
    if exits != "house":
        raise ValueError(f"unknown exits {exits!r}")
    specs = specs or {}
    syms = m.symbols
    C = len(syms)
    N = len(rates)
    rates = np.asarray(rates, float)
    init = s.initial_equity if initial is None else initial
    span = TF_MS[tf]
    ends, atr_tab = atr if atr is not None else tf_atr(m, tf)
    atr_at = {int(t): atr_tab[i] for i, t in enumerate(ends)}
    draw = draw or random_draws(np.random.default_rng(seed), long_share)
    quality = s.leverage_rule == "quality_v1"
    if quality and group_draw is None:
        gseed = (list(seed) if isinstance(seed, (list, tuple)) else [int(seed)]) + [GROUP_SALT]
        group_draw = group_draws(np.random.default_rng(gseed), V3_P_BEST.get(tf, 0.0) if p_best is None else p_best)
    cmask = None if coin_mask is None else np.asarray(coin_mask, bool)
    br = [_BracketArrays.of(brackets[x]) for x in syms]
    steps = [(specs.get(x, {}).get("qty_step", 0.0), specs.get(x, {}).get("min_notional", 0.0)) for x in syms]
    w = m.window(lo, hi)
    taker, slip, rt = s.taker_fee, s.slippage_frac, s.round_trip_cost
    lad = s.ladder
    first_trig = lad.first_lock + lad.trigger_gap

    wallet = np.full(N, float(init))
    bust = np.zeros(N, bool)
    inpos = np.zeros(N, bool)
    coin = np.zeros(N, np.int64)
    side = np.zeros(N)
    qty = np.zeros(N)
    entry = np.zeros(N)
    stop = np.zeros(N)
    lock = np.full(N, -np.inf)
    liq = np.zeros(N)
    margin = np.zeros(N)
    mmr = np.zeros(N)
    cum = np.zeros(N)
    efee = np.zeros(N)
    fpaid = np.zeros(N)
    mfe = np.zeros(N)
    lev = np.zeros(N)
    ntr = np.zeros(N, np.int64)
    last_mark = np.full(C, np.nan)
    allidx = np.arange(N)
    T = len(w.ts)
    bidx = np.nonzero(w.ts % span == 0)[0]      # minutes where signals arrive

    def close(j, px, liquidate):
        """Close positions j at prices px (liquidate: lose the isolated margin)."""
        gross = side[j] * qty[j] * (px - entry[j])
        liqd = liquidate | (gross < -margin[j])
        wallet[j] = np.where(liqd, wallet[j] - margin[j], wallet[j] + gross - qty[j] * px * taker)
        inpos[j] = False
        bust[j] |= wallet[j] < s.bust_below

    t = -1
    while True:
        t += 1
        if t >= T:
            break
        if not inpos.any():
            # nobody holds a position: nothing happens until the next signal minute
            nb = bidx[np.searchsorted(bidx, t):]
            if not len(nb) or bust.all():
                break
            t = int(nb[0])
        ts = int(w.ts[t])
        o, h, l, c = w.o[t], w.h[t], w.l[t], w.c[t]
        mo, mh, ml, mc = w.mo[t], w.mh[t], w.ml[t], w.mc[t]
        mo = np.where(np.isnan(mo), o, mo)
        mh = np.where(np.isnan(mh), h, mh)
        ml = np.where(np.isnan(ml), l, ml)
        mc = np.where(np.isnan(mc), c, mc)
        # ---- funding at its real minute, on the mark open, first (engine.step): paid by the positions held at the
        #      funding instant (this minute's open), before this minute's entries (they fill after it) and exits
        fr = w.fr[t]
        if not np.all(np.isnan(fr)):
            j = allidx[inpos]
            if len(j):
                k = coin[j]
                rate = fr[k]
                ok = ~np.isnan(rate) & ~np.isnan(o[k])
                j, k, rate = j[ok], k[ok], rate[ok]
                if len(j):
                    pay = side[j] * qty[j] * mo[k] * rate
                    wallet[j] -= pay
                    margin[j] -= pay
                    fpaid[j] += pay
                    sj = side[j]
                    with np.errstate(all="ignore"):
                        liq[j] = np.maximum((margin[j] + cum[j] - sj * qty[j] * entry[j])
                                            / (qty[j] * mmr[j] - sj * qty[j]), 0.0)
        entered = None
        # ---- entries: signals of the TF bar that closed at this minute's open
        if ts % span == 0:
            free = allidx[~inpos & ~bust]
            a = atr_at.get(ts)
            if len(free) and a is not None:
                fire, sd = draw(ts, free, rates, C)
                bestm = group_draw(ts, free, C) if quality else None
                if cmask is not None:
                    fire = fire & (cmask[free] if cmask.ndim == 2 else cmask[None, :])
                if bar_mask is not None:
                    fire = fire & np.asarray(bar_mask(ts, free), bool).reshape(-1, 1)
                got = np.zeros(len(free), bool)
                for k in range(C):            # coin priority; sizing failure -> next coin
                    if np.isnan(o[k]) or not (np.isfinite(a[k]) and a[k] > 0):
                        continue
                    cand = np.nonzero(fire[:, k] & ~got)[0]
                    if not len(cand):
                        continue
                    j = free[cand]
                    sdk = sd[cand, k].astype(float)
                    raw = o[k]
                    fill = raw * (1 + sdk * slip)
                    st = raw - sdk * stop_atr * a[k]
                    r = size_vec(s, wallet[j], sdk, fill, st, np.full(len(j), a[k]), br[k], *steps[k],
                                 best=None if bestm is None else bestm[cand, k])
                    okc = r["ok"]
                    j = j[okc]
                    got[cand[okc]] = True
                    q_ = r["qty"][okc]
                    inpos[j] = True
                    coin[j] = k
                    side[j] = sdk[okc]
                    qty[j] = q_
                    entry[j] = fill[okc]
                    stop[j] = st[okc]
                    lock[j] = -np.inf
                    liq[j] = r["liq"][okc]
                    margin[j] = r["margin"][okc]
                    mmr[j] = r["mmr"][okc]
                    cum[j] = r["cum"][okc]
                    fee = q_ * fill[okc] * taker
                    wallet[j] -= fee
                    efee[j] = fee
                    fpaid[j] = 0.0
                    mfe[j] = fill[okc]
                    lev[j] = r["lev"][okc]
                    ntr[j] += 1
                entered = free[got]
        # ---- exits
        j = allidx[inpos]
        if len(j):
            k = coin[j]
            ok = ~np.isnan(o[k])
            j, k = j[ok], k[ok]
        if len(j):
            sd = side[j]
            bo, bh_, bl = o[k], h[k], l[k]
            mfe[j] = np.where(sd > 0, np.maximum(mfe[j], bh_), np.minimum(mfe[j], bl))
            eb = np.zeros(len(j), bool)
            if entered is not None and len(entered):
                eb = np.isin(j, entered)
            done = np.zeros(len(j), bool)
            # gaps at the open (not on the entry bar): liquidation on mark, then the stop on last
            g_liq = ~eb & ((mo[k] - liq[j]) * sd <= 0)
            if g_liq.any():
                close(j[g_liq], liq[j[g_liq]], True)
                done |= g_liq
            g_st = ~eb & ~done & ((bo - stop[j]) * sd <= 0)
            if g_st.any():
                jj = j[g_st]
                close(jj, bo[g_st] * (1 - sd[g_st] * slip), False)
                done |= g_st
            hit = ~done & np.where(sd > 0, bl <= stop[j], bh_ >= stop[j])
            if hit.any():
                jj = j[hit]
                close(jj, stop[jj] * (1 - side[jj] * slip), False)
                done |= hit
            hl = ~done & np.where(sd > 0, ml[k] <= liq[j], mh[k] >= liq[j])
            if hl.any():
                close(j[hl], liq[j[hl]], True)
                done |= hl
            # profit lock from the best price so far, effective from the next bar
            up = ~done & ~eb
            if up.any():
                jj = j[up]
                sj = side[jj]
                fund = fpaid[jj] / (qty[jj] * entry[jj])
                best = lev[jj] * (sj * (mfe[jj] / entry[jj] - 1.0) - rt - fund)
                armed = best >= first_trig - 1e-12
                nstep = np.floor((best - first_trig) / lad.step + 1e-9)
                lk = np.where(armed, lad.first_lock + lad.step * nstep, -np.inf)
                raise_ = armed & (lk > lock[jj] + 1e-12)
                if raise_.any():
                    jr = jj[raise_]
                    sr = side[jr]
                    px = entry[jr] * (1.0 + sr * (lk[raise_] / lev[jr] + rt + fund[raise_]))
                    stop[jr] = np.where(sr > 0, np.maximum(stop[jr], px), np.minimum(stop[jr], px))
                    lock[jr] = lk[raise_]
        if inpos.any():
            present = ~np.isnan(c)
            last_mark[present] = mc[present]

    # mark price of the last minute of the window (what the checkpoint snapshot holds)
    for k in range(C):
        mk_k = np.where(np.isnan(w.mc[:, k]), w.c[:, k], w.mc[:, k])
        ok_k = np.nonzero(~np.isnan(mk_k))[0]
        if len(ok_k):
            last_mark[k] = mk_k[ok_k[-1]]
    eq = wallet.copy()
    j = allidx[inpos]
    if len(j):
        mk = last_mark[coin[j]]
        gross = side[j] * qty[j] * (mk - entry[j])
        eq[j] += np.where(gross < -margin[j], -margin[j], gross - qty[j] * mk * (taker + slip))
    return {"equity": eq, "wallet": wallet, "bust": bust, "trades": ntr, "open": inpos}


# ====================================================================== the reel's bots (paper v4, owners' D2 (ii), D4, D7)
REEL_STOP_LOOKBACK = 12        # the bots' swing low: the lowest low of the last 12 closed 5m bars (signal bar included)


@dataclass
class FiveMin:
    """5m bars built from the 1m bars (as ``tf_atr``: a 5m bar with no 1m bar is left out), per coin: ``ends`` (B,)
    close times; ``atr`` (B, C) ATR14 (Wilder) of the bar closing there (NaN for an empty bar); ``stop_low`` (B, C)
    the lowest low of the last REEL_STOP_LOOKBACK present bars up to it; ``upper`` (B, C) the upper Bollinger band
    (20, 2, population std; reel_engine.upper_band, the engine's own formula) of the last 20 present closes; and
    ``tgt`` (T, C) for every minute of ``m``: the upper band of the last present 5m bar that closed at or before
    that minute's 5m bucket (the reel's resting target during that minute); ``close`` (B, C) the bar's close (the last
    present 1m close, NaN for an empty bar)."""
    ends: np.ndarray
    atr: np.ndarray
    stop_low: np.ndarray
    upper: np.ndarray
    tgt: np.ndarray
    close: np.ndarray


def five_min_table(m: Minutes, atr: Optional[tuple] = None) -> FiveMin:
    from .reel_engine import BB_LEN, upper_band
    span = TF_MS[REEL_TF]
    per = span // MIN
    ends, atr_tab = atr if atr is not None else tf_atr(m, REEL_TF)
    C = len(m.symbols)
    B = len(ends)
    stop_low = np.full((B, C), np.nan)
    upper = np.full((B, C), np.nan)
    tgt = np.full((len(m.ts), C), np.nan)
    if B == 0:
        return FiveMin(ends, atr_tab, stop_low, upper, tgt, np.full((0, C), np.nan))
    a0 = int(np.searchsorted(m.ts, int(ends[0]) - span))
    sl = slice(a0, a0 + B * per)
    shape = (B, per, C)
    with np.errstate(all="ignore"), _quiet():
        lo5 = np.nanmin(m.l[sl].reshape(shape), axis=1)
        cc = m.c[sl].reshape(shape)
    present = ~np.isnan(cc)
    last_idx = per - 1 - np.argmax(present[:, ::-1, :], axis=1)
    close = np.take_along_axis(cc, last_idx[:, None, :], axis=1)[:, 0, :]
    has = present.any(axis=1)
    bucket = m.ts - m.ts % span
    for k in range(C):
        ok = np.nonzero(has[:, k])[0]
        if not len(ok):
            continue
        lows, closes = lo5[ok, k], close[ok, k]
        for i in range(len(ok)):
            j0 = max(0, i - REEL_STOP_LOOKBACK + 1)
            stop_low[ok[i], k] = float(np.min(lows[j0:i + 1])) if i >= REEL_STOP_LOOKBACK - 1 else np.nan
            if i >= BB_LEN - 1:
                upper[ok[i], k] = upper_band(closes[i - BB_LEN + 1:i + 1])
        # the target of a minute: the band of the last present 5m bar with close time <= the minute's bucket
        pe = ends[ok]
        pos = np.searchsorted(pe, bucket, side="right") - 1
        good = pos >= 0
        tgt[good, k] = upper[ok[pos[good]], k]
    close = np.where(has, close, np.nan)
    return FiveMin(ends, atr_tab, stop_low, upper, tgt, close)


def simulate_reel_bots(m: Minutes, tf: str, lo: int, hi: int, rates: np.ndarray, s: Settings, brackets: dict,
                       specs: Optional[dict] = None, seed=0, draw=None, initial: Optional[float] = None,
                       atr: Optional[tuple] = None, p_best=None, group_draw=None, coin_mask=None,
                       bar_mask=None, five: Optional[FiveMin] = None) -> dict:
    """Coin-flip accounts on real 1m bars with the reel's own exits (paperbot/reel_engine.py ``ReelEngine``, as the
    REEL_H1@5m account and the three 5m coin flips trade; owners' D2 (ii), D4, D7): long only; each coin and 5m bar
    fires with the bot's rate; the stop is the lowest low of the last 12 closed 5m bars (signal bar included) minus
    0.05 x ATR14 (5m); the first target is the signal bar's upper band, then at every 5m close the band of that bar;
    skipped (next coin) when the stop is at or above the fill or the fill at or above the first target; the stop
    first, a target hit only when the high trades through it (filled at the target, maker fee; a bar that opens
    through it at its open); the time exit at the close of the 96th 5m bar at risk (market); no ladder; 'normal'
    leverage (p_best 0, config.V3_P_BEST["5m"]); liquidation on mark, funding, bust as ``simulate_bots``. A test
    checks it trade for trade against ``ReelEngine``."""
    from .reel_engine import FIVE_MS, MAX_HOLD_5M, STOP_BUF_ATR
    if tf != REEL_TF:
        raise ValueError(f"the reel's exits trade {REEL_TF} only, not {tf}")
    specs = specs or {}
    syms = m.symbols
    C = len(syms)
    N = len(rates)
    rates = np.asarray(rates, float)
    init = s.initial_equity if initial is None else initial
    span = TF_MS[tf]
    five = five if five is not None else five_min_table(m, atr)
    row_of = {int(t): i for i, t in enumerate(five.ends)}
    draw = draw or random_draws(np.random.default_rng(seed), 1.0)
    quality = s.leverage_rule == "quality_v1"
    if quality and group_draw is None:
        gseed = (list(seed) if isinstance(seed, (list, tuple)) else [int(seed)]) + [GROUP_SALT]
        group_draw = group_draws(np.random.default_rng(gseed), V3_P_BEST.get(tf, 0.0) if p_best is None else p_best)
    cmask = None if coin_mask is None else np.asarray(coin_mask, bool)
    br = [_BracketArrays.of(brackets[x]) for x in syms]
    steps = [(specs.get(x, {}).get("qty_step", 0.0), specs.get(x, {}).get("min_notional", 0.0)) for x in syms]
    a0 = int(np.searchsorted(m.ts, lo))
    w = m.window(lo, hi)
    tgt_w = five.tgt[a0:a0 + len(w.ts)]
    taker, maker, slip = s.taker_fee, s.maker_fee, s.slippage_frac

    wallet = np.full(N, float(init))
    bust = np.zeros(N, bool)
    inpos = np.zeros(N, bool)
    coin = np.zeros(N, np.int64)
    qty = np.zeros(N)
    entry = np.zeros(N)
    stop = np.zeros(N)
    liq = np.zeros(N)
    margin = np.zeros(N)
    mmr = np.zeros(N)
    cum = np.zeros(N)
    tend = np.zeros(N, np.int64)
    ntr = np.zeros(N, np.int64)
    last_mark = np.full(C, np.nan)
    allidx = np.arange(N)
    T = len(w.ts)
    bidx = np.nonzero(w.ts % span == 0)[0]

    def close(j, px, liquidate, fee_rate):
        """Close positions j (long) at prices px (liquidate: lose the isolated margin; a loss beyond the margin is a
        liquidation, as the engine's ``_close``)."""
        gross = qty[j] * (px - entry[j])
        liqd = liquidate | (gross < -margin[j])
        wallet[j] = np.where(liqd, wallet[j] - margin[j], wallet[j] + gross - qty[j] * px * fee_rate)
        inpos[j] = False
        bust[j] |= wallet[j] < s.bust_below

    t = -1
    while True:
        t += 1
        if t >= T:
            break
        if not inpos.any():
            nb = bidx[np.searchsorted(bidx, t):]
            if not len(nb) or bust.all():
                break
            t = int(nb[0])
        ts = int(w.ts[t])
        o, h, l, c = w.o[t], w.h[t], w.l[t], w.c[t]
        mo, ml, mc = w.mo[t], w.ml[t], w.mc[t]                 # long only: the mark high is never needed
        mo = np.where(np.isnan(mo), o, mo)
        ml = np.where(np.isnan(ml), l, ml)
        mc = np.where(np.isnan(mc), c, mc)
        tg = tgt_w[t]
        # ---- funding first (engine.step), as simulate_bots
        fr = w.fr[t]
        if not np.all(np.isnan(fr)):
            j = allidx[inpos]
            if len(j):
                k = coin[j]
                rate = fr[k]
                ok = ~np.isnan(rate) & ~np.isnan(o[k])
                j, k, rate = j[ok], k[ok], rate[ok]
                if len(j):
                    pay = qty[j] * mo[k] * rate
                    wallet[j] -= pay
                    margin[j] -= pay
                    with np.errstate(all="ignore"):
                        liq[j] = np.maximum((margin[j] + cum[j] - qty[j] * entry[j]) / (qty[j] * mmr[j] - qty[j]), 0.0)
        entered = None
        # ---- entries: signals of the 5m bar that closed at this minute's open
        if ts % span == 0:
            free = allidx[~inpos & ~bust]
            r = row_of.get(ts)
            if len(free) and r is not None:
                a = five.atr[r]
                fire, _sd = draw(ts, free, rates, C)
                bestm = group_draw(ts, free, C) if quality else None
                if cmask is not None:
                    fire = fire & (cmask[free] if cmask.ndim == 2 else cmask[None, :])
                if bar_mask is not None:
                    fire = fire & np.asarray(bar_mask(ts, free), bool).reshape(-1, 1)
                got = np.zeros(len(free), bool)
                for k in range(C):            # coin priority; a skip or a sizing failure -> next coin
                    if np.isnan(o[k]) or not (np.isfinite(a[k]) and a[k] > 0):
                        continue
                    st_k = five.stop_low[r, k] - STOP_BUF_ATR * a[k]
                    tg0 = five.upper[r, k]
                    fill_k = o[k] * (1 + slip)
                    if not (np.isfinite(st_k) and np.isfinite(tg0)) or st_k >= fill_k or fill_k >= tg0:
                        continue              # the reel's skip rules (no position, the next coin is tried)
                    cand = np.nonzero(fire[:, k] & ~got)[0]
                    if not len(cand):
                        continue
                    j = free[cand]
                    n_ = len(j)
                    rz = size_vec(s, wallet[j], np.ones(n_), np.full(n_, fill_k), np.full(n_, st_k),
                                  np.full(n_, a[k]), br[k], *steps[k], best=None if bestm is None else bestm[cand, k])
                    okc = rz["ok"]
                    j = j[okc]
                    got[cand[okc]] = True
                    q_ = rz["qty"][okc]
                    inpos[j] = True
                    coin[j] = k
                    qty[j] = q_
                    entry[j] = fill_k
                    stop[j] = st_k
                    liq[j] = rz["liq"][okc]
                    margin[j] = rz["margin"][okc]
                    mmr[j] = rz["mmr"][okc]
                    cum[j] = rz["cum"][okc]
                    wallet[j] -= q_ * fill_k * taker
                    tend[j] = ts - ts % FIVE_MS + MAX_HOLD_5M * FIVE_MS
                    ntr[j] += 1
                entered = free[got]
        # ---- exits (ReelEngine._handle_exit)
        j = allidx[inpos]
        if len(j):
            k = coin[j]
            ok = ~np.isnan(o[k])
            j, k = j[ok], k[ok]
        if len(j):
            # the time exit fell in a gap of 1m bars: market at this open
            late = ts >= tend[j]
            if late.any():
                close(j[late], o[k[late]] * (1 - slip), False, taker)
                j, k = j[~late], k[~late]
        if len(j):
            eb = np.zeros(len(j), bool)
            if entered is not None and len(entered):
                eb = np.isin(j, entered)
            tj = tg[k]
            done = np.zeros(len(j), bool)
            g_liq = ~eb & (mo[k] <= liq[j])
            if g_liq.any():
                close(j[g_liq], liq[j[g_liq]], True, 0.0)
                done |= g_liq
            g_st = ~eb & ~done & (o[k] <= stop[j])
            if g_st.any():
                close(j[g_st], o[k[g_st]] * (1 - slip), False, taker)
                done |= g_st
            g_tp = ~eb & ~done & (o[k] > tj)
            if g_tp.any():
                close(j[g_tp], o[k[g_tp]], False, maker)
                done |= g_tp
            hit = ~done & (l[k] <= stop[j])
            if hit.any():
                close(j[hit], stop[j[hit]] * (1 - slip), False, taker)
                done |= hit
            hl = ~done & (ml[k] <= liq[j])
            if hl.any():
                close(j[hl], liq[j[hl]], True, 0.0)
                done |= hl
            htp = ~done & (h[k] > tj)
            if htp.any():
                close(j[htp], tj[htp], False, maker)
                done |= htp
            # the time exit at the close of the 96th 5m bar at risk
            te = ~done & (ts + MIN >= tend[j])
            if te.any():
                close(j[te], c[k[te]] * (1 - slip), False, taker)
        if inpos.any():
            present = ~np.isnan(c)
            last_mark[present] = mc[present]

    for k in range(C):
        mk_k = np.where(np.isnan(w.mc[:, k]), w.c[:, k], w.mc[:, k])
        ok_k = np.nonzero(~np.isnan(mk_k))[0]
        if len(ok_k):
            last_mark[k] = mk_k[ok_k[-1]]
    eq = wallet.copy()
    j = allidx[inpos]
    if len(j):
        mk = last_mark[coin[j]]
        gross = qty[j] * (mk - entry[j])
        eq[j] += np.where(gross < -margin[j], -margin[j], gross - qty[j] * mk * (taker + slip))
    return {"equity": eq, "wallet": wallet, "bust": bust, "trades": ntr, "open": inpos}


# ====================================================================== the verdict
@dataclass
class Task:
    aid: str
    stage: str          # "1차" or "2차"
    tf: str
    lo: int
    hi: int
    value: float        # account statistic compared with the bots' final equity
    rate: float
    cls: str = ORIG     # "orig" (the originals share one group per window) or the extra's own id
    stop_atr: float = V3_STOP_ATR
    first_lock: Optional[float] = None
    p_best: Optional[float] = None   # quality_v1 bots' 'best' share (plan: account_p_best); None = V3_P_BEST[tf]
    group: str = "core"              # paper v4: the FDR family (account_family); the originals' passes are per family
    long_share: Optional[float] = None   # the bots' long probability (the account's own share, D7); None = 50/50
    coins: Optional[tuple] = None    # the coins the bots may trade (coins_of); None = every trade coin
    session: Optional[str] = None    # an ET-session definition's bar mask (SESSION_RULES); None = every bar
    exits: str = "house"             # "house" (simulate_bots) or "reel" (simulate_reel_bots)


def _prior(out: sqlite3.Connection, date: str) -> dict:
    """Latest decided state per account before ``date`` (from earlier verdicts). A hold after a 1st pass (the
    account missing from the next snapshot, M10, or held in its 2nd window, M9) keeps that 1st pass with its
    window, so the next checkpoint gives the account its 2nd check, not a fresh 1st verdict."""
    st = {}
    for d, aid, status, stage, data in out.execute(
            "SELECT date, account_id, status, stage, data FROM verdict_accounts WHERE date < ? ORDER BY date",
            (date,)):
        if status == HOLD and (st.get(aid) or {}).get("status") == PASS1:
            continue
        st[aid] = {"date": d, "status": status, "stage": stage, **json.loads(data)}
    return st


def q5_restart(a: dict, cp: int) -> Optional[int]:
    """When an extra account's 30-day window starts over: its last ``code_accepted`` event before ``cp`` (the
    owners accepted changed signal code for that account, a Q5 event for it only; docs/extra-accounts.md 4).
    None when there is none."""
    out = None
    for ev in a.get("events") or []:
        if ev.get("event") == "code_accepted":
            t = int(ev.get("effective") or ev.get("ts") or 0)
            if t < cp and (out is None or t > out):
                out = t
    return out


def _bots_of(a: dict, fam: str, st: dict) -> dict:
    """The Task fields that make the account's bots fair (owners' D7): its long share in the window (None when the
    snapshot has no side counts: 50/50 as v3), its coin set, its ET-session bar mask, the reel's exits."""
    strat = a.get("strategy")
    parent = a.get("parent")
    if a.get("kind") == "copy" and isinstance(parent, str) and "@" in parent:
        strat = parent.split("@", 1)[0]
    kind = a.get("kind")
    src_kind = "ds200" if kind == "copy" and fam == "ds200" else kind
    longs = st.get("signals_long")
    share = None
    if fam == "reel":
        share = 1.0
    elif longs is not None and st["signals"] > 0:
        share = float(longs) / float(st["signals"])
    return {"long_share": share, "coins": coins_of(strat, src_kind), "session": session_of(strat, src_kind),
            "exits": "reel" if fam == "reel" else "house"}


def _rate_problem(st: dict) -> Optional[str]:
    """M9: an account with trades but no recorded signal in its window cannot get a fair coin-flip rate (rate 0: every
    bot ends flat, so any gain would 'beat' them)."""
    if st["trades"] >= 1 and st["signals"] == 0:
        return f"신호 기록 0건인데 거래 {st['trades']}건: 우연 기준을 계산할 수 없음 (신호 기록 확인 필요)"
    return None


def plan(snap: dict, prior: dict, prev_snaps: dict, s: Settings) -> tuple[dict, list[Task]]:
    """Per-account decisions that need no bots, and the Q1 tasks for the rest. An extra account's window
    starts at its creation, or later at its last accepted code change (``q5_restart``). Paper v4: every row carries
    its FDR family (``group``); judged timeframes per family (JUDGED_BY_FAMILY); an account with trades but no
    recorded signal is held (M9); an account the runner did not save at the checkpoint is held (M10)."""
    cp = snap["cp_ts"]
    init = snap["run"]["initial_equity"]
    rows, tasks = {}, []
    kinds = {aid: a.get("kind") for aid, a in snap["accounts"].items()}
    for aid, a in snap["accounts"].items():
        tf = a["timeframe"]
        extra = a["kind"] in EXTRA_KINDS
        fam = a.get("group") or account_family(a["kind"], a.get("strategy"), a.get("parent"), kinds)
        lo = a["created_ts"]
        restart = q5_restart(a, cp) if extra else None
        if restart is not None and restart > lo:
            lo = restart
        st1 = period_stats(a, lo, cp, s, init)
        base = {"strategy": a["strategy"], "timeframe": tf, "kind": a["kind"], "equity": a["equity"],
                "bust": a["bust"], "trades_total": st1["trades"], "group": fam}
        pr = prior.get(aid)
        if extra:
            base["created_ts"] = a["created_ts"]
            if pr is not None and pr.get("created_ts") != a["created_ts"]:
                pr = None                     # an id re-used after a paper3 restore starts over
            if lo != a["created_ts"]:
                base["window_from"] = lo      # Q5: the window starts over at the accepted code change
                if pr is not None and lo >= day_ms(pr["date"]):
                    pr = None                 # judged on the code before the owners accepted the new one
            rl = a.get("rule") or {}
            tkw = {"cls": aid, "stop_atr": float(rl.get("stop_atr") or V3_STOP_ATR),
                   "first_lock": rl.get("first_lock")}
        else:
            tkw = {}
        if a["kind"] == "random" or fam not in FAMILIES:
            rows[aid] = {**base, "status": OBSERVE, "stage": None, "reason": "동전 봇 기준 계좌 (판정 안 함, 눈으로 보는 기준)"}
            continue
        judged = JUDGED_BY_FAMILY[fam]
        if tf not in judged:
            why = ("4시간봉은 처음부터 관찰용 (Q3)" if tf in OBSERVE_TFS else
                   f"{TF_KO.get(tf, tf)}봉은 {FAMILY_KO[fam]} 묶음의 판정 봉이 아님 "
                   f"(판정: {', '.join(TF_KO.get(x, x) for x in judged)})")
            rows[aid] = {**base, "status": OBSERVE, "stage": None, "reason": why}
            continue
        # the bots' 'best' share: the account's own cell (a copy its parent's; a new-strategy, DeepSeek or reel
        # account 0); a core cell missing from p_best_cells.json stops the verdict (MissingCell)
        tkw["p_best"] = account_p_best(a, kinds)
        tkw["group"] = fam
        if pr and pr["status"] in (FAIL, PASS2):
            rows[aid] = {**base, "status": pr["status"], "stage": pr.get("stage"),
                         "reason": f"{pr.get('decided', pr['date'])} 판정 유지: {pr.get('reason', '')}",
                         "decided": pr.get("decided", pr["date"]), "p": pr.get("p"), "q": pr.get("q")}
            continue
        if pr and pr["status"] == PASS1:
            plo = pr["window"][1]
            prev = prev_snaps.get(day_str(plo))
            eq0 = prev["accounts"][aid]["equity"] if prev and aid in prev["accounts"] else None
            st2 = period_stats(a, plo, cp, s, init)
            scaled = st2["pnl"] * init / eq0 if eq0 and eq0 > 0 else st2["pnl"]
            bk = _bots_of(a, fam, st2)
            r = {**base, "stage": "2차", "window": [plo, cp], "trades": st2["trades"], "pnl": st2["pnl"],
                 "pnl_scaled": scaled, "start_equity": eq0, "signals": st2["signals"],
                 "rate": signal_rate(st2["signals"], tf, plo, cp, coins=len(bk["coins"]),
                                     skipped=st2.get("skipped_bars", 0), session=bk["session"])}
            if st2.get("skipped_bars"):
                r["skipped_bars"] = st2["skipped_bars"]
            _bots_row(r, bk)
            bad = _rate_problem(st2)
            if bad:
                rows[aid] = {**r, "status": HOLD, "reason": "2차: " + bad, "notes": [f"{aid}: {bad}"]}
                continue
            if st2["signals"] < st2["trades"]:
                r.setdefault("notes", []).append(f"{aid}: 신호 {st2['signals']}건 < 거래 {st2['trades']}건 (신호 기록 확인 필요)")
            rows[aid] = r
            tasks.append(Task(aid, "2차", tf, plo, cp, init + scaled, r["rate"], **tkw, **bk))
            continue
        # not yet judged
        # Q5 restart of an extra: judge only the window on the accepted code (equity as if it began there)
        restarted = lo != a["created_ts"]
        pnl1 = st1["pnl"] if restarted else a["equity"] - init
        r = {**base, "stage": None, "window": [lo, cp], "trades": st1["trades"], "signals": st1["signals"],
             "pnl": pnl1}
        if restarted:
            r.update(equity=init + pnl1, equity_total=a["equity"])
        old_enough = cp >= floor_day(lo) + PERIOD_DAYS * DAY_MS
        if not old_enough or st1["trades"] < MIN_TRADES:
            why = ("30일 미만 (복사 계좌는 자기 시작부터 셈)" if lo == a["created_ts"] else
                   "30일 미만 (바뀐 신호 코드를 받아들인 날부터 다시 셈, Q5)") if not old_enough \
                else f"거래 {st1['trades']}건 < {MIN_TRADES}건"
            if old_enough and cp - floor_day(lo) >= NO_VERDICT_DAYS * DAY_MS:
                why += f" · {NO_VERDICT_DAYS}일까지 {MIN_TRADES}건 미달: 판정 불가"
            rows[aid] = {**r, "status": HOLD, "reason": why}
            continue
        bk = _bots_of(a, fam, st1)
        bad = _rate_problem(st1)
        if bad:
            rows[aid] = {**r, "status": HOLD, "reason": bad, "notes": [f"{aid}: {bad}"]}
            continue
        r.update(stage="1차", rate=signal_rate(st1["signals"], tf, lo, cp, coins=len(bk["coins"]),
                                               skipped=st1.get("skipped_bars", 0), session=bk["session"]))
        if st1.get("skipped_bars"):
            r["skipped_bars"] = st1["skipped_bars"]
        _bots_row(r, bk)
        if st1["signals"] < st1["trades"]:
            r.setdefault("notes", []).append(f"{aid}: 신호 {st1['signals']}건 < 거래 {st1['trades']}건 (신호 기록 확인 필요)")
        rows[aid] = r
        tasks.append(Task(aid, "1차", tf, lo, cp, init + pnl1 if restarted else a["equity"], r["rate"], **tkw, **bk))
    for x in (snap.get("coverage") or {}).get("missing") or []:
        aid = x["account_id"]
        why = "체크포인트 상태 저장에 이 계좌가 없음 (러너 확인 필요): 이번 판정 없음"
        row = {"strategy": x.get("strategy"), "timeframe": x.get("timeframe"), "kind": x.get("kind"),
               "group": x.get("group"), "equity": None, "bust": None, "trades_total": None, "status": HOLD,
               "stage": None, "reason": why, "missing": True, "notes": [f"{aid}: {why}"]}
        pr = prior.get(aid)
        if pr and pr["status"] in (FAIL, PASS2) and pr.get("created_ts") == (x.get("created_ts") if
                                                                            x.get("kind") in EXTRA_KINDS else None):
            # a final verdict stays final even when the account is missing this time
            row.update(status=pr["status"], stage=pr.get("stage"), decided=pr.get("decided", pr["date"]),
                       p=pr.get("p"), q=pr.get("q"),
                       reason=f"{pr.get('decided', pr['date'])} 판정 유지: {pr.get('reason', '')} ({why})")
        rows[aid] = row
    return rows, tasks


def _bots_row(r: dict, bk: dict) -> None:
    """What the account's bots copy, on its verdict row (D7)."""
    r["bots_rule"] = {"long_share": None if bk["long_share"] is None else round(bk["long_share"], 6),
                      "coins": len(bk["coins"]), "session": bk["session"], "exits": bk["exits"]}


def run_tasks(tasks: list[Task], minutes_for: Callable[[int, int], Minutes], s: Settings, brackets: dict,
              specs: dict, n_bots: int, seed_base: int, initial: float, log=None) -> tuple[dict, list[dict]]:
    """Q1 for every task: all tasks with the same timeframe and window share one vectorised pass
    (each account gets its own ``n_bots`` bots at its own rate). Returns ({aid: p}, groups).

    Paper v4: the originals run one pass per (family, timeframe, window); the core family keeps the v3 seed (so the
    36's bots do not depend on the other groups), the others add their FAMILY_SALT. Each pass gives every account's
    bots its long share, coin set and session mask (D7); the reel's pass trades with the reel's exits."""
    from dataclasses import replace as _replace
    groups: dict[tuple, list[Task]] = {}
    for t in tasks:                                  # the originals: one group per (family, tf, window)
        if t.cls == ORIG:
            groups.setdefault((t.tf, t.lo, t.hi, t.group), []).append(t)
    fam_rank = {g: i for i, g in enumerate(FAMILIES)}
    order = sorted(groups.items(), key=lambda kv: (fam_rank.get(kv[0][3], 9), kv[0][1], TF_MS[kv[0][0]]))
    extra = sorted(((t.tf, t.lo, t.hi, t.group, t.cls), [t]) for t in tasks if t.cls != ORIG)
    order += sorted(extra, key=lambda kv: (kv[0][1], TF_MS[kv[0][0]], kv[0][4]))   # each extra alone, after
    pvals, info = {}, []
    for key, ts in order:
        tf, lo, hi, fam = key[:4]
        t0 = time.time()
        pre = ATR_PREFIX_BARS * TF_MS[tf]
        start = lo - lo % TF_MS[tf] - pre
        m = minutes_for(start, hi)
        rates = np.repeat([t.rate for t in ts], n_bots)
        seed = [seed_base, TF_MS[tf] // MIN, lo // MIN % 2**31]
        if FAMILY_SALT.get(fam) is not None:
            seed = seed + [FAMILY_SALT[fam]]
        gs, stop_atr = s, V3_STOP_ATR
        if len(key) == 5:                            # an extra: its own seed and its own rule
            x = ts[0]
            seed = seed + [int(hashlib.sha256(x.aid.encode()).hexdigest()[:8], 16)]
            if x.first_lock is not None and float(x.first_lock) != s.ladder_first_lock:
                gs = _replace(s, ladder_first_lock=float(x.first_lock))
            stop_atr = float(x.stop_atr)
        shares = [V3_P_BEST.get(tf, 0.0) if t.p_best is None else float(t.p_best) for t in ts]
        p_best = shares[0] if len(set(shares)) == 1 else np.repeat(shares, n_bots)   # one per account's bots
        kw = _pass_rules(ts, n_bots, tf, getattr(m, "symbols", V3_SYMBOLS))
        res = simulate_bots(m, tf, lo, hi, rates, gs, brackets, specs, seed=seed, initial=initial, stop_atr=stop_atr,
                            p_best=p_best, **kw)
        for i, t in enumerate(ts):
            bots = res["equity"][i * n_bots:(i + 1) * n_bots]
            pvals[t.aid] = {"p": luck_p(t.value, bots), "bots_median": float(np.median(bots)),
                            "bots_p90": float(np.quantile(bots, 0.9)),
                            "bots_bust": float(np.mean(res["bust"][i * n_bots:(i + 1) * n_bots])),
                            "bots_trades": float(np.mean(res["trades"][i * n_bots:(i + 1) * n_bots]))}
        sec = time.time() - t0
        row = {"timeframe": tf, "window": [lo, hi], "accounts": len(ts), "bots": len(rates),
               "seed": seed, "seconds": round(sec, 1)}
        if gs.leverage_rule == "quality_v1":
            row["p_best"] = shares[0] if len(set(shares)) == 1 else {t.aid: p for t, p in zip(ts, shares)}
        if fam != "core" or kw:
            row.update(group=fam, exits=kw.get("exits", "house"))
        if len(key) == 5:
            row.update(account_id=ts[0].aid, stop_atr=stop_atr, first_lock=gs.ladder_first_lock)
        info.append(row)
        if log:
            log(f"Q1 {tf} {day_str(lo)}~{day_str(hi)}: {len(ts)} accounts x {n_bots} bots, {sec:.0f}s")
    return pvals, info


def _pass_rules(ts: list[Task], n_bots: int, tf: str, symbols) -> dict:
    """simulate_bots keywords of one pass from its tasks (D7): per-bot long shares, coin masks and session masks
    (each left out when no task of the pass needs it, so a v3-shaped pass is exactly the v3 call), the exits."""
    kw: dict = {}
    if any(t.long_share is not None for t in ts):
        kw["long_share"] = np.repeat([0.5 if t.long_share is None else float(t.long_share) for t in ts], n_bots)
    if any(t.coins is not None and set(t.coins) != set(symbols) for t in ts):
        rows = [[(t.coins is None) or (x in t.coins) for x in symbols] for t in ts]
        kw["coin_mask"] = np.repeat(np.array(rows, bool), n_bots, axis=0)
    sess = sorted({t.session for t in ts if t.session})
    if sess:
        sid = np.repeat([sess.index(t.session) if t.session else -1 for t in ts], n_bots)
        span = TF_MS[tf]

        def bar_mask(ts_: int, idx: np.ndarray) -> np.ndarray:
            ok = np.array([bool(session_mask(x, tf, [ts_])[0]) for x in sess] + [True])
            return ok[sid[idx]]
        bar_mask.span = span      # noqa: for tests
        kw["bar_mask"] = bar_mask
    ex = {t.exits for t in ts}
    if len(ex) != 1:
        raise ValueError(f"one pass cannot mix exits {sorted(ex)}")
    if ex != {"house"}:
        kw["exits"] = ex.pop()
    return kw


def _pct(a: float) -> str:
    return f"{a * 100:g}%"


def _tfs_ko(tfs) -> str:
    return "·".join(TF_KO.get(t, t) for t in tfs)


def method_ko(group: Optional[str] = None, n_bots: int = N_BOTS) -> str:
    """How the verdict judges, in one short Korean line built from the code (``N_BOTS``, ``FAMILY_ALPHA``, the judged
    timeframes per family; never typed in), for the owners' texts (agents' facts, the dashboard, Obsidian; gap G18).
    ``group``: None for the whole run; a family ("core", "ds200", "reel") or a display group ("extra" reads as the
    core family it joins, "flip" says it is never judged)."""
    if group == "flip":
        return f"동전 봇은 비교 기준 (판정 안 함) · 판정 계좌마다 같은 봉 동전 봇 {n_bots:,}개와 비교"
    fam = "core" if group in ("extra", "copy", "newlab", "strategy") else group
    if fam in FAMILY_ALPHA:
        note = " (복사·새 매매법 계좌 포함)" if group == "extra" or fam == "core" else ""
        return (f"같은 봉 동전 봇 {n_bots:,}개와 비교 · {FAMILY_KO[fam]} 묶음{note} 운 기준 FDR "
                f"{_pct(FAMILY_ALPHA[fam])} · 판정 봉 {_tfs_ko(JUDGED_BY_FAMILY[fam])}"
                + (f" · {_tfs_ko(OBSERVE_TFS)}봉은 관찰용" if fam != "reel" else ""))
    fams = " · ".join(f"{FAMILY_KO[g]} {_pct(a)}({_tfs_ko(JUDGED_BY_FAMILY[g])})" for g, a in FAMILY_ALPHA.items())
    return (f"같은 봉 동전 봇 {n_bots:,}개와 비교 · 운 기준 FDR 묶음별 {fams} · 합계 {_pct(sum(FAMILY_ALPHA.values()))}"
            f" · {_tfs_ko(OBSERVE_TFS)}봉은 관찰용")


def family_table(alphas: Optional[dict] = None, n_bots: int = N_BOTS, families: Optional[list] = None) -> list[dict]:
    """The FDR families as rows for the dashboard (G20): family, Korean name, alpha, judged timeframes, method_ko, and
    from a verdict's ``families`` its "tested" / "luck_passed" / "lucky_expected" / "lucky_if_uncorrected" (the
    family's expected lucky passes, verdict doc 6). ``alphas``: a verdict's ``family_alpha`` (default FAMILY_ALPHA)."""
    al = dict(FAMILY_ALPHA if alphas is None else alphas)
    done = {f.get("group"): f for f in families or [] if isinstance(f, dict)}
    return [{"family": g, "name": FAMILY_KO.get(g, g), "alpha": al.get(g),
             "judged_tfs": list(JUDGED_BY_FAMILY.get(g, ())), "method_ko": method_ko(g, n_bots),
             **{k: done[g][k] for k in ("tested", "luck_passed", "lucky_expected", "lucky_if_uncorrected")
                if k in done.get(g, {})}}
            for g in list(FAMILIES) + [g for g in al if g not in FAMILIES]]


def family_alphas(alpha: float = ALPHA) -> dict:
    """The families' alphas (D5): FAMILY_ALPHA, scaled when the total ``alpha`` differs from ALPHA."""
    if alpha == ALPHA:
        return dict(FAMILY_ALPHA)
    return {g: alpha * a / ALPHA for g, a in FAMILY_ALPHA.items()}


def decide(snap: dict, rows: dict, tasks: list[Task], pvals: dict, alpha: float = ALPHA) -> dict:
    """Benjamini-Hochberg per FDR family at its alpha (paper v4, owners' D5 (b): core + copies of core parents +
    new-strategy accounts 0.07, ds200 0.025, reel 0.005; the overall FDR <= 0.10), then the 1st / 2nd check rules."""
    init = snap["run"]["initial_equity"]
    kind = {aid: a.get("kind") for aid, a in snap["accounts"].items()}
    tested_all = [t for t in tasks if t.aid in pvals]
    alphas = family_alphas(alpha)
    bad = sorted({t.group for t in tested_all if t.group not in alphas})
    if bad:
        raise ValueError(f"tasks of unknown FDR families {bad}")
    fams, done = [], []
    for g in FAMILIES:
        tg = [t for t in tested_all if t.group == g]
        q, rej = bh([pvals[t.aid]["p"] for t in tg], alphas[g])
        origs = [t for t in tg if kind.get(t.aid) not in EXTRA_KINDS]
        if len(origs) != len(tg):               # extras in the family: the originals' own BH, for transparency
            qo, _ro = bh([pvals[t.aid]["p"] for t in origs], alphas[g])   # (without extras q_orig == q)
            for t, qi in zip(origs, qo):
                rows[t.aid]["q_orig"] = float(qi)
        n_rej = int(rej.sum()) if len(tg) else 0
        fams.append({"group": g, "name": FAMILY_KO[g], "alpha": alphas[g], "tested": len(tg), "luck_passed": n_rej,
                     "lucky_expected": round(alphas[g] * n_rej, 3),
                     "lucky_if_uncorrected": round(alphas[g] * len(tg), 3)})
        done += [(t, qi, ri, alphas[g]) for t, qi, ri in zip(tg, q, rej)]
    for t, qi, ri, ag in done:
        r = rows[t.aid]
        r.update(pvals[t.aid])
        r.update(q=float(qi), luck_pass=bool(ri), alpha=ag)
        if t.stage == "1차":
            fails = []
            if r["equity"] <= init:
                fails.append(f"평가금 ${r['equity']:,.0f} ≤ 시작 ${init:,.0f}")
            if r["bust"]:
                fails.append("파산")
            if not ri:
                fails.append(f"우연 기준 미통과 (p {r['p']:.4f}, 보정 q {qi:.3f})")
            r["status"] = PASS1 if not fails else FAIL
            r["reason"] = ("거래 %d건, 평가금 $%s, p %.4f, q %.3f" % (r["trades"], f"{r['equity']:,.0f}", r["p"], qi)
                           if not fails else "1차: " + ", ".join(fails))
        else:
            fails = []
            if r["trades"] < MIN_TRADES:
                fails.append(f"2차 기간 거래 {r['trades']}건 < {MIN_TRADES}건")
            if r["pnl"] <= 0:
                fails.append(f"2차 기간 손익 ${r['pnl']:,.0f}")
            if not ri:
                fails.append(f"우연 기준 미통과 (p {r['p']:.4f}, 보정 q {qi:.3f})")
            r["status"] = PASS2 if not fails else FAIL
            r["reason"] = ("2차 통과: 실거래 검토 대상 (거래 %d건, 손익 $%s, q %.3f)" % (r["trades"], f"{r['pnl']:,.0f}", qi)
                           if not fails else "2차: " + ", ".join(fails))
        r["decided"] = snap["date"]
    for aid, r in rows.items():
        if r.get("stage") and "status" not in r:      # a task without a p (should not happen)
            r.update(status=HOLD, reason="우연 기준 계산 없음")
    counts = {k: sum(1 for r in rows.values() if r["status"] == k) for k in STATUSES}
    out = {"tested": sum(f["tested"] for f in fams), "luck_passed": sum(f["luck_passed"] for f in fams),
           "lucky_expected": round(sum(f["alpha"] * f["luck_passed"] for f in fams), 3),
           "lucky_if_uncorrected": round(sum(f["alpha"] * f["tested"] for f in fams), 3),
           "counts": counts, "families": fams}
    return out


def verdict_text(v: dict) -> str:
    """The Telegram / log summary in Korean (owners' layout 2026-10-04; the snapshot hash is on the dashboard)."""
    c = v["counts"]
    L = [f"🏁 {v['day']}일 판정 · {day_ko(v['date'])}", "",
         f"1차 합격 {c[PASS1]} · 2차 통과 {c[PASS2]}",
         f"불합격 {c[FAIL]} · 보류 {c[HOLD]} · 관찰용 {c[OBSERVE]}"]
    new = [(aid, r) for aid, r in v["accounts"].items() if r.get("decided") == v["date"]]
    ko = _names_ko(v["accounts"])
    twice = Counter(ko.values())          # the code only where two accounts would read the same (copies)
    for st in (PASS2, PASS1):
        names = [f"- {ko[aid]} ({aid + ', ' if twice[ko[aid]] > 1 else ''}q {r['q']:.3f})"
                 for aid, r in new if r["status"] == st]
        if names:
            L += ["", f"{st}"] + names[:12] + ([f"외 {len(names) - 12}개"] if len(names) > 12 else [])
    L += ["", f"운 기준: 동전 봇 {v['n_bots']:,}개, FDR "
          + (f"묶음별 · 합계 {v['alpha'] * 100:g}%" if v.get("families") else f"{int(v['alpha'] * 100)}%"),
          f"검정 {v['tested']}개 중 통과 {v['luck_passed']}개",
          f"운으로 기대되는 합격 ≤ {v['lucky_expected']:.1f}개",
          f"(보정 없었다면 {v['lucky_if_uncorrected']:.1f}개)"]
    if v.get("families"):                     # paper v4: one line per FDR family (alpha-split, D5)
        L += ["묶음별 (FDR 나눔)"] + [f"- {f.get('name', f['group'])}: 검정 {f['tested']}개 중 통과 {f['luck_passed']}개 "
                                    f"(FDR {f['alpha'] * 100:g}%) · 운으로 기대 ≤ "
                                    f"{f.get('lucky_expected', f['alpha'] * f['luck_passed']):.2f}개"
                                    for f in v["families"]]
    if v.get("warnings"):
        L += ["", "⚠ 주의"] + [_warning_ko(w) for w in v["warnings"]]
    L += ["", "자세히: 대시보드 순위표 '체크포인트 판정'"]
    return "\n".join(L)


def _warning_ko(w: str) -> str:
    """'2026-10-12 재시작 때 체결·청산·사이즈 관련 변경(trading_code). Q5: …' -> two short lines."""
    m = re.match(r"(\d{4}-\d{2}-\d{2}) 재시작 때 체결·청산·사이즈 관련 변경\((.*?)\)\. Q5", w)
    if m:
        g = re.search(r"해당 묶음: ([^;)]*)", m[2])
        who = f" ({g[1]})" if g else ""
        return f"- {day_ko(m[1])} 재시작 때 체결·청산·사이즈 코드 변경{who}:\n  30일을 다시 셀지 규칙 관리자 확인 필요"
    return f"- {w}"


def _names_ko(accounts: dict) -> dict:
    """{account_id: name} for the Telegram text, as the other Telegram messages write it: the Korean strategy
    name (agents/roster3.STRATEGY_KO) and timeframe, '복제' / '새 매매법' before an extra. Display only."""
    try:
        from .agents.roster3 import STRATEGY_KO
    except Exception:  # noqa: BLE001  (names are cosmetic)
        STRATEGY_KO = {}
    try:
        from .groups import label_ko
    except Exception:  # noqa: BLE001  (names are cosmetic)
        def label_ko(strategy, timeframe=None):
            return None
    pre = {"copy": "복제 ", "newlab": "새 매매법 "}

    def name(r):
        return STRATEGY_KO.get(r["strategy"]) or label_ko(r["strategy"]) or r["strategy"]
    return {aid: f"{pre.get(r.get('kind'), '')}{name(r)} "
                 f"{TF_KO.get(r['timeframe'], r['timeframe'])}" for aid, r in accounts.items()}


def judge(out: sqlite3.Connection, date: str, minutes_for, s: Settings, brackets: dict, specs: dict,
          n_bots: int = N_BOTS, alpha: float = ALPHA, log=None, now_ms: Optional[int] = None) -> dict:
    """The verdict for the snapshot of ``date`` (already stored). Stored once; returns it."""
    have = out.execute("SELECT data FROM verdicts WHERE date = ?", (date,)).fetchone()
    if have is not None:
        return json.loads(have[0])
    t0 = time.time()
    snap, sha = load_snapshot(out, date)
    init = snap["run"]["initial_equity"]
    s = _settings_of(snap, s)
    prior = _prior(out, date)
    prev_snaps = {}
    for aid, pr in prior.items():
        if pr["status"] == PASS1:
            d = day_str(pr["window"][1])
            if d not in prev_snaps:
                got = load_snapshot(out, d)
                prev_snaps[d] = got[0] if got else None
    rows, tasks = plan(snap, prior, prev_snaps, s)
    seed_base = int(snap["cp_ts"] // DAY_MS)
    pvals, groups = run_tasks(tasks, minutes_for, s, brackets, specs, n_bots, seed_base, init, log)
    summary = decide(snap, rows, tasks, pvals, alpha)
    start = snap["run"]["start_ts"]
    warnings = []
    for ch in snap["run"].get("trading_changes", []):
        if start is not None and ch["ts"] > start:
            hit = ch.get("groups")
            names = "·".join(GROUP_NAME_KO.get(g, g) for g in hit) if hit else "전체"
            text = (f"{day_str(ch['ts'])} 재시작 때 체결·청산·사이즈 관련 변경({', '.join(ch['changes'])}; 해당 묶음: {names}). "
                    "Q5: 영향받는 계좌의 기간을 그날부터 다시 세야 하는지 규칙 관리자 확인 필요")
            warnings.append(text)
            if hit is not None:               # v4 (D8, M12): the note goes on the hit groups' rows only
                for aid, r in rows.items():
                    if r.get("group") in hit:
                        r.setdefault("notes", []).append(text)
    warnings += extra_warnings(snap, rows)
    warnings += group_warnings(snap, rows)
    v = {"date": date, "cp_ts": snap["cp_ts"], "day": int((snap["cp_ts"] - floor_day(start)) // DAY_MS) if start else None,
         "snapshot_sha256": sha, "alpha": alpha, "family_alpha": family_alphas(alpha), "n_bots": n_bots,
         "initial_equity": init, "groups": groups, "warnings": warnings, "accounts": rows, **summary,
         "coverage": _coverage_of(snap), "runtime_s": round(time.time() - t0, 1)}
    v["text"] = verdict_text(v)
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    with out:
        out.execute("INSERT INTO verdicts VALUES (?,?,?,?)", (date, now, sha, canonical(v)))
        out.executemany("INSERT OR REPLACE INTO verdict_accounts VALUES (?,?,?,?,?,?,?)",
                        [(date, aid, r["status"], r.get("stage"), r.get("p"), r.get("q"), canonical(r))
                         for aid, r in rows.items()])
    return v


GROUP_NAME_KO = {**FAMILY_KO, "flip": "동전", "extra": "추가 계좌"}


def _coverage_of(snap: dict) -> dict:
    """Expected vs found accounts per group (snapshot v3 ``coverage``; a v2 snapshot: the found ones only)."""
    cov = snap.get("coverage")
    if cov:
        return {"expected": dict(cov.get("expected") or {}), "found": dict(cov.get("found") or {}),
                "missing": [x["account_id"] for x in cov.get("missing") or []]}
    found: dict = {}
    for a in snap["accounts"].values():
        g = a.get("group") or account_family(a.get("kind"), a.get("strategy"), a.get("parent"))
        found[g] = found.get(g, 0) + 1
    return {"expected": None, "found": found, "missing": []}


def group_warnings(snap: dict, rows: dict) -> list[str]:
    """Paper v4 warnings that name the affected group only (M9, M10): accounts missing from the runner's state,
    accounts held for a zero signal count, accounts with fewer signals than trades."""
    out = []
    by: dict[str, list] = {}
    for x in (snap.get("coverage") or {}).get("missing") or []:
        by.setdefault(x.get("group") or "?", []).append(x["account_id"])
    for g, ids in sorted(by.items()):
        out.append(f"상태 저장에 없는 계좌 {len(ids)}개 ({GROUP_NAME_KO.get(g, g)}만 해당: {', '.join(sorted(ids)[:8])}"
                   f"{' 외' if len(ids) > 8 else ''}): 이번 판정에서 보류")
    zero: dict[str, list] = {}
    short: dict[str, list] = {}
    for aid, r in rows.items():
        if r.get("missing"):
            continue
        for n in r.get("notes") or []:
            if "신호 기록 0건" in n:
                zero.setdefault(r.get("group") or "?", []).append(aid)
            elif "신호 " in n and "< 거래" in n:
                short.setdefault(r.get("group") or "?", []).append(aid)
    for g, ids in sorted(zero.items()):
        out.append(f"신호 기록 0건인데 거래가 있는 계좌 {len(ids)}개 ({GROUP_NAME_KO.get(g, g)}만 해당: "
                   f"{', '.join(sorted(ids)[:8])}{' 외' if len(ids) > 8 else ''}): 보류, 신호 기록 확인 필요")
    for g, ids in sorted(short.items()):
        out.append(f"신호가 거래보다 적은 계좌 {len(ids)}개 ({GROUP_NAME_KO.get(g, g)}만 해당: "
                   f"{', '.join(sorted(ids)[:8])}{' 외' if len(ids) > 8 else ''}): 신호 기록 확인 필요")
    return out


def extra_warnings(snap: dict, rows: dict) -> list[str]:
    """Warnings that name only the affected extra accounts ("추가 계좌만 해당"); also kept on the extra's row
    (``notes``). Never on an original's row."""
    out = []
    accts = snap["accounts"]
    extras = {aid: a for aid, a in accts.items() if a.get("kind") in EXTRA_KINDS}
    if not extras:
        return out
    from .runinfo import SHARED_WATCHED
    shared = {k for k, _, _ in SHARED_WATCHED}
    for ch in snap["run"].get("extra_code_changes", []):
        hit = sorted(aid for aid, a in extras.items() if a["created_ts"] < ch["ts"])
        if hit:
            what = (f"추가 계좌 코드 변경 ({EXTRAS_ONLY_KO}: {', '.join(hit)})"
                    if not shared & set(ch.get("changes") or []) else
                    f"신호 입력 코드(recorder·context) 변경 (원래 계좌도 쓰는 코드, 원래 계좌는 recorder.py가 거래 코드로 따로 잡힘, Q-11; "
                    f"추가 계좌: {', '.join(hit)})")
            text = (f"{day_str(ch['ts'])} 재시작 때 {what}. "
                    "Q5: 그 계좌들의 기간을 그날부터 다시 세야 하는지 규칙 관리자 확인 필요")
            out.append(text)
            for aid in hit:
                rows.get(aid, {}).setdefault("notes", []).append(text)
    names = {"suspended": "멈춤", "held": "정지(동결)", "code_accepted": "바뀐 신호 코드 수락", "resumed": "재개"}
    for aid, a in extras.items():
        for ev in a.get("events") or []:
            if ev.get("event") in ("suspended", "held", "code_accepted"):
                text = (f"{aid}: {day_str(int(ev['ts']))} {names[ev['event']]} ({ev.get('code') or ''}) — "
                        f"{EXTRAS_ONLY_KO}" + (", Q5 사건: 이 계좌의 30일 기간을 다시 셈" if ev["event"] == "code_accepted"
                                                 else ""))
                out.append(text)
                rows.get(aid, {}).setdefault("notes", []).append(text)
        r = rows.get(aid) or {}
        if r.get("skipped_bars"):
            note = f"{aid}: 재시작으로 계산하지 못한 봉 {r['skipped_bars']}개는 신호 비율에서 빠짐"
            r.setdefault("notes", []).append(note)
            out.append(note)
    return out


def _settings_of(snap: dict, s: Settings) -> Settings:
    from dataclasses import replace
    return replace(s, taker_fee=snap["run"]["taker_fee"], slippage_frac=snap["run"]["slippage"],
                   initial_equity=snap["run"]["initial_equity"])


# ====================================================================== the job
def run_due(paper_db: str, out_path: str, minutes_for, s: Settings, brackets: dict, specs: dict,
            notifier=None, now_ms: Optional[int] = None, only: Optional[str] = None,
            n_bots: int = N_BOTS, log=print) -> list[dict]:
    """Freeze and judge every due checkpoint that has no verdict yet. paper3.db is read only."""
    conn = ro_connect(paper_db)
    out = open_out(out_path)
    done = []
    try:
        facts = run_facts(conn)
        if facts["start_ts"] is None:
            log("no run in this database yet")
            return done
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        for k, cp in due_checkpoints(facts["start_ts"], now):
            date = day_str(cp)
            if only and date != only:
                continue
            if out.execute("SELECT 1 FROM verdicts WHERE date = ?", (date,)).fetchone():
                continue
            if load_snapshot(out, date) is None:
                snap = freeze_snapshot(conn, cp, settings=s)
                if snap is None:
                    msg = (f"{k * PERIOD_DAYS}일 판정 대기 · {day_ko(date)}\n\n그날 09:00(한국) 상태 저장이 아직 없음\n"
                           "봇이 그 시각을 처리하면 다음 실행에서 판정")
                    _log_once(out, date, msg, notifier, now)
                    log(msg)
                    break
                sha = store_snapshot(out, snap, now)
                log(f"snapshot {date} frozen: {len(snap['accounts'])} accounts, sha256 {sha}")
            v = judge(out, date, minutes_for, s, brackets, specs, n_bots=n_bots, log=log, now_ms=now)
            log(v["text"])
            done.append(v)
        send_verdicts(out, notifier, now)
    finally:
        conn.close()
        out.close()
    return done


def due_unjudged(paper_db: str, out_path: str, now: int, only: Optional[str] = None) -> list[tuple[int, str]]:
    """[(day, date)] of the due checkpoints that have no verdict yet. No REST call: most hourly runs stop here."""
    conn = ro_connect(paper_db)
    try:
        start = run_facts(conn)["start_ts"]
    finally:
        conn.close()
    if start is None:
        return []
    out = open_out(out_path)
    todo = []
    try:
        for k, cp in due_checkpoints(start, now):
            date = day_str(cp)
            judged = out.execute("SELECT 1 FROM verdicts WHERE date = ?", (date,)).fetchone()
            if (not only or date == only) and not judged:
                todo.append((k * PERIOD_DAYS, date))
    finally:
        out.close()
    return todo


def send_verdicts(out, notifier, now) -> None:
    """Send every verdict that Telegram has not taken yet (silent INFO, as documented) and mark it ``sent`` in
    job_log. A send that returns False (not delivered) is tried again on the next hourly run; a notifier that
    cannot tell (None) counts as delivered."""
    if notifier is None:
        return
    for date, data in out.execute("SELECT date, data FROM verdicts v WHERE NOT EXISTS (SELECT 1 FROM job_log j "
                                  "WHERE j.date = v.date AND j.text = 'sent') ORDER BY date").fetchall():
        if notifier.send(INFO, json.loads(data)["text"]) is not False:
            out.execute("INSERT INTO job_log VALUES (?,?,?)", (now, date, "sent"))
            out.commit()


def _log_once(out, date, msg, notifier, now) -> None:
    if out.execute("SELECT 1 FROM job_log WHERE date = ? AND text = ?", (date, msg)).fetchone():
        return
    out.execute("INSERT INTO job_log VALUES (?,?,?)", (now, date, msg))
    out.commit()
    if notifier is not None:
        notifier.send(WARN, msg)


# ====================================================================== read API (agents, dashboard)
def _ro_out(path: str) -> Optional[sqlite3.Connection]:
    if not path or not os.path.exists(path):
        return None
    try:
        return ro_connect(path)
    except sqlite3.Error:
        return None


def latest_verdict(path: str) -> Optional[dict]:
    """The newest checkpoint verdict (dict, see ``judge``), or None. Read-only."""
    c = _ro_out(path)
    if c is None:
        return None
    try:
        r = c.execute("SELECT data FROM verdicts ORDER BY date DESC LIMIT 1").fetchone()
        return None if r is None else json.loads(r[0])
    except sqlite3.OperationalError:
        return None
    finally:
        c.close()


def verdict(path: str, date: str) -> Optional[dict]:
    c = _ro_out(path)
    if c is None:
        return None
    try:
        r = c.execute("SELECT data FROM verdicts WHERE date = ?", (date,)).fetchone()
        return None if r is None else json.loads(r[0])
    except sqlite3.OperationalError:
        return None
    finally:
        c.close()


def statuses(path: str) -> dict[str, str]:
    """{account_id: status} from the newest verdict ('보류', '1차 합격', '불합격', '2차 통과', '관찰용')."""
    v = latest_verdict(path)
    return {} if v is None else {aid: r["status"] for aid, r in v["accounts"].items()}


def account_status(path: str, account_id: str) -> Optional[dict]:
    """One account's row in the newest verdict (status, stage, trades, p, q, reason ...)."""
    v = latest_verdict(path)
    if v is None or account_id not in v["accounts"]:
        return None
    return {"date": v["date"], "account_id": account_id, **v["accounts"][account_id]}


def dashboard_view(path: str) -> dict:
    """Compact JSON for the dashboard section (newest verdict, sorted rows)."""
    v = latest_verdict(path)
    if v is None:
        return {"ready": False}
    order = {PASS2: 0, PASS1: 1, FAIL: 2, HOLD: 3, OBSERVE: 4}
    from .accounts import GROUP_OF_KIND
    al = v.get("family_alpha") or family_alphas(v.get("alpha", ALPHA))
    rows = []
    for aid, r in v["accounts"].items():
        # "family": the verdict family (a copy its parent's, a new-strategy account core, the coin flips "flip");
        # "group": the display group (accounts.GROUP_OF_KIND: copies and new-lab accounts are "extra"); "alpha_family":
        # the family's FDR alpha (None for a family that is never judged); "alpha" the one its q was judged at
        fam = r.get("group") or account_family(r.get("kind"), r.get("strategy"))
        rows.append({"account_id": aid, "status": r["status"], "stage": r.get("stage"), "timeframe": r["timeframe"],
                     "trades": r.get("trades", r.get("trades_total")), "equity": r.get("equity"),
                     "pnl": r.get("pnl"), "p": r.get("p"), "q": r.get("q"), "reason": r.get("reason", ""),
                     "group": GROUP_OF_KIND.get(r.get("kind"), fam), "family": fam, "alpha_family": al.get(fam),
                     "alpha": r.get("alpha")})
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["q"] if r["q"] is not None else 2, r["account_id"]))
    table = family_table(al, v.get("n_bots", N_BOTS), v.get("families"))
    return {"ready": True, "date": v["date"], "day": v.get("day"), "counts": v["counts"], "tested": v["tested"],
            "luck_passed": v["luck_passed"], "lucky_expected": v["lucky_expected"],
            "lucky_if_uncorrected": v["lucky_if_uncorrected"], "alpha": v["alpha"], "n_bots": v["n_bots"],
            "snapshot_sha256": v["snapshot_sha256"], "warnings": v.get("warnings", []), "rows": rows,
            "families": v.get("families", []), "coverage": v.get("coverage"),
            "family_alpha": dict(al), "family_table": table, "method_ko": method_ko(None, v.get("n_bots", N_BOTS))}


# ====================================================================== CLI
def _show(out_path: str, date: Optional[str]) -> int:
    v = verdict(out_path, date) if date else latest_verdict(out_path)
    if v is None:
        print("판정 없음")
        return 1
    print(v["text"])
    for aid, r in sorted(v["accounts"].items(), key=lambda kv: (STATUSES.index(kv[1]["status"]), kv[0])):
        p = "" if r.get("p") is None else f" p {r['p']:.4f} q {r['q']:.3f}"
        print(f"  {r['status']:6s} {aid:28s}{p}  {r.get('reason', '')}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "show"])
    ap.add_argument("--db", default="paper3.db")
    ap.add_argument("--out", default="checkpoint.db")
    ap.add_argument("--cache", default=None, help="1m bar cache directory (default: <out dir>/checkpoint_bars)")
    ap.add_argument("--date", help="only this checkpoint (YYYY-MM-DD)")
    ap.add_argument("--bots", type=int, default=N_BOTS)
    ap.add_argument("--brackets")
    ap.add_argument("--allow-example-brackets", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "show":
        return _show(args.out, args.date)
    if not os.path.exists(args.db):
        # right after a reset (deploy/paperbot-reset.sh) a catching-up timer run can come before the bot has created
        # paper3.db: nothing to judge yet, so no failure (and no "작업 실패" Telegram)
        print(f"INFO: {args.db} does not exist yet (new run not started): nothing to judge, skipped")
        return 0
    from .live import _notifier, _rest, load_brackets
    now = int(time.time() * 1000)
    todo = due_unjudged(args.db, args.out, now, args.date)
    notifier = None if args.no_notify else _notifier()
    if not todo:                          # nothing to judge: no Binance call, only a verdict not delivered yet
        out = open_out(args.out)
        try:
            send_verdicts(out, notifier, now)
        finally:
            out.close()
        return 0
    try:
        rest = _rest()
        conn = ro_connect(args.db)
        fee = run_facts(conn)["taker_fee"]
        conn.close()
        s = v3_settings(**({"taker_fee": fee} if fee else {}))
        brackets, _ = load_brackets(rest, list(V3_SYMBOLS), args.brackets, args.allow_example_brackets)
        specs = rest.exchange_info(list(V3_SYMBOLS))
        cache = args.cache or os.path.join(os.path.dirname(os.path.abspath(args.out)), "checkpoint_bars")
        src = BinanceMinutes(rest, cache)
        run_due(args.db, args.out, src.load, s, brackets, specs, notifier, only=args.date, n_bots=args.bots)
    except (Exception, SystemExit) as exc:
        # a due checkpoint still without a verdict: one loud warning per date and error type (the timer retries);
        # a verdict already stored (an earlier date judged before the error) still goes out on every run
        out = open_out(args.out)
        try:
            send_verdicts(out, notifier, now)
            left = [(day, d) for day, d in todo
                    if out.execute("SELECT 1 FROM verdicts WHERE date = ?", (d,)).fetchone() is None]
            if left:
                day, d = left[0]
                _log_once(out, d, f"{day}일 판정 오류 · {day_ko(d)}\n\n오류: {type(exc).__name__}\n매시 35분에 다시 시도\n"
                                  "계속되면: journalctl -u paperbot-checkpoint -n 50",
                          notifier, now)
        finally:
            out.close()
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
