"""A synthetic shadow-league database for the dashboard tests (tests/test_dash_league.py) and the offline screenshots.

The tables are the bot side's final shape (schema version 2), reproduced VERBATIM from the DDL the agents' migrations leave
in a database (the dashboard branch does not carry the agents code, so this file is the only place the shape lives here):
the statements below are what ``SELECT sql FROM sqlite_master`` printed from a freshly migrated file. ``ddl(version)`` gives the
older shape (version 1: no clones, no account_daily, no acct_* columns on trades) for the 'older file' tests.

The standard world is small and hand-computable (see ``STANDARD``): six trades of one member (``zoneflip``), 50 clones for
each, day-end account rows, 24 series, 14 signals. Times are UTC milliseconds.
"""
from __future__ import annotations

import calendar
import json
import sqlite3
from typing import Optional

DAY = 86_400_000
H = 3_600_000
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
COINS = ("BTC", "ETH", "SOL", "DOGE", "LTC", "BCH")
TFS = ("15m", "30m", "1h", "4h")


def utc_ms(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> int:
    return calendar.timegm((y, m, d, hh, mm, 0)) * 1000


START = utc_ms(2026, 10, 7)                    # the member's start date (09:00 KST)
NOW = START + 5 * DAY + 3 * H                  # 'now' of the standard world

# ---------------------------------------------------------------------------------------------------------------
# The final DDL, verbatim (one statement per entry; the order is the dump's).
STATEMENTS = {
    "account_daily": """CREATE TABLE account_daily (
    member_id  TEXT NOT NULL,
    scope      TEXT NOT NULL,
    day_ms     INTEGER NOT NULL,
    equity     REAL NOT NULL,
    ret_pct    REAL NOT NULL,
    taken      INTEGER NOT NULL,
    liquidated INTEGER NOT NULL,
    asof_ms    INTEGER NOT NULL,
    PRIMARY KEY (member_id, scope, day_ms)
) WITHOUT ROWID;""",
    "bars": """CREATE TABLE bars (
    coin   TEXT NOT NULL,
    tf     TEXT NOT NULL,
    t_ms   INTEGER NOT NULL,
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL NOT NULL,
    atr    REAL,
    PRIMARY KEY (coin, tf, t_ms)
) WITHOUT ROWID;""",
    "clones": """CREATE TABLE clones (
    clone_id    TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL,
    trade_id    TEXT NOT NULL,
    k           INTEGER NOT NULL,
    coin        TEXT NOT NULL,
    tf          TEXT NOT NULL,
    side        INTEGER NOT NULL,
    sl_dist     REAL NOT NULL,
    tp_dist     REAL NOT NULL,
    offset_bars INTEGER NOT NULL,
    target_ms   INTEGER NOT NULL,
    status      TEXT NOT NULL,
    entry_ms    INTEGER,
    entry_px    REAL,
    exit_ms     INTEGER,
    exit_px     REAL,
    reason      TEXT,
    hold        INTEGER,
    gross_raw   REAL,
    gross       REAL,
    fee         REAL,
    funding     REAL,
    net         REAL,
    mae         REAL,
    created_ms  INTEGER NOT NULL,
    resolved_ms INTEGER
);""",
    "feeds": """CREATE TABLE feeds (
    coin          TEXT NOT NULL,
    tf            TEXT NOT NULL,
    first_bar_ms  INTEGER,
    last_bar_ms   INTEGER,
    n_ingested    INTEGER NOT NULL DEFAULT 0,
    holes         INTEGER NOT NULL DEFAULT 0,
    state         TEXT NOT NULL DEFAULT 'new',
    error         TEXT,
    error_since_ms INTEGER,
    error_count   INTEGER NOT NULL DEFAULT 0,
    last_fetch_ms INTEGER,
    last_ok_ms    INTEGER,
    next_try_ms   INTEGER,
    PRIMARY KEY (coin, tf)
);""",
    "league_meta": """CREATE TABLE league_meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);""",
    "members": """CREATE TABLE members (
    member_id    TEXT PRIMARY KEY,
    name_ko      TEXT NOT NULL,
    detector     TEXT NOT NULL,
    spec_json    TEXT NOT NULL,
    spec_sha256  TEXT NOT NULL,
    start_ms     INTEGER NOT NULL,
    created_ms   INTEGER NOT NULL,
    activated_ms INTEGER,
    last_tick_ms INTEGER,
    halted       TEXT
);""",
    "series_state": """CREATE TABLE series_state (
    member_id   TEXT NOT NULL,
    coin        TEXT NOT NULL,
    tf          TEXT NOT NULL,
    status      TEXT NOT NULL,
    last_bar_ms INTEGER,
    warm_have   INTEGER NOT NULL DEFAULT 0,
    warm_need   INTEGER NOT NULL DEFAULT 0,
    note        TEXT,
    updated_ms  INTEGER NOT NULL,
    PRIMARY KEY (member_id, coin, tf)
);""",
    "signals": """CREATE TABLE signals (
    signal_id   TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL,
    coin        TEXT NOT NULL,
    tf          TEXT NOT NULL,
    side        INTEGER NOT NULL,
    bar_ms      INTEGER NOT NULL,
    break_ms    INTEGER,
    plan_entry  REAL,
    stop        REAL,
    target      REAL,
    rr          REAL,
    touches     INTEGER,
    atr         REAL,
    zone_lo     REAL,
    zone_hi     REAL,
    tz_lo       REAL,
    tz_hi       REAL,
    status      TEXT NOT NULL,
    recorded_ms INTEGER NOT NULL
);""",
    "trades": """CREATE TABLE trades (
    trade_id    TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL,
    coin        TEXT NOT NULL,
    tf          TEXT NOT NULL,
    side        INTEGER NOT NULL,
    signal_ms   INTEGER NOT NULL,
    entry_ms    INTEGER NOT NULL,
    entry_px    REAL NOT NULL,
    stop_px     REAL NOT NULL,
    target_px   REAL NOT NULL,
    sl_dist     REAL NOT NULL,
    tp_dist     REAL NOT NULL,
    status      TEXT NOT NULL,
    exit_ms     INTEGER,
    exit_px     REAL,
    reason      TEXT,
    hold        INTEGER,
    gross_raw   REAL,
    gross       REAL,
    fee         REAL,
    funding     REAL,
    net         REAL,
    mae         REAL,
    mfe         REAL,
    recorded_ms INTEGER NOT NULL,
    closed_ms   INTEGER
, acct_taken INTEGER, acct_ret REAL, acct_equity REAL, acct_liq INTEGER);""",
    "clones_open": "CREATE INDEX clones_open ON clones (member_id, status, coin, tf);",
    "clones_trade": "CREATE INDEX clones_trade ON clones (trade_id, k);",
    "signals_member": "CREATE INDEX signals_member ON signals (member_id, bar_ms);",
    "trades_member": "CREATE INDEX trades_member ON trades (member_id, status, entry_ms);",
}
V1_NAMES = ("bars", "feeds", "league_meta", "members", "series_state", "signals", "trades", "signals_member", "trades_member")
V1_TRADES_TAIL = "\n, acct_taken INTEGER, acct_ret REAL, acct_equity REAL, acct_liq INTEGER);"


def ddl(version: int = 2) -> str:
    """The shape of a schema version (2 = final; 1 = before the clones, the day-end account rows and the account columns)."""
    if version >= 2:
        return "\n\n".join(STATEMENTS.values())
    parts = []
    for name in V1_NAMES:
        sql = STATEMENTS[name]
        parts.append(sql.replace(V1_TRADES_TAIL, "\n);") if name == "trades" else sql)
    return "\n\n".join(parts)


def spec_json(**over) -> str:
    """The member's stored definition (the bot's Member.spec())."""
    spec = {"member_id": "zoneflip", "detector": "zoneflip", "detector_params": {"lookback": 200, "bins": 50, "top": 0.2},
            "trade": {"max_hold": 48, "fee_side": 0.0005, "slip_side": 0.0001, "funding_8h": 0.0001, "one_per_series": True},
            "tfs": list(TFS), "coins": list(COINS), "start_ms": START,
            "account": {"start_equity": 5000.0, "margin_frac": 0.2, "leverage": 20, "liq_adverse": 0.045},
            "clones_k": 50, "clone_days": 5, "study": "zoneflip"}
    spec.update(over)
    return json.dumps(spec, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------------------------------------------
# The standard world: six trades, hand-computable numbers (tests/test_dash_league.py has the arithmetic).
#   exit order of the four with every clone decided: T1 (D0+6h), T2 (D0+9h), T3 (D1+8h), T4 (D2+9h)
#   member net % : +1.0, -0.5, +0.2, -0.8             -> cumulative 1.0, 0.5, 0.7, -0.1
#   clone world k of trade i: C[i] + 0.0001 * k       (k = 0..49)  -> cumulative of world k after n trades: sum(C[:n]) + n * 0.0001 * k
#   T5 is open (DOGE 4h); T6 (LTC 15m) is closed but ten of its fifty clones are still pending
def standard(start: int = START) -> dict:
    """The standard world's facts for a start date."""
    return {
        "trades": [   # id, coin, tf, side, entry, exit, net, gross_raw, reason, hold, mae
            ("T1", "BTC", "15m", 1, start + 3 * H + 900_000, start + 6 * H, 0.0100, 0.0114, "TP", 11, -0.0020),
            ("T2", "ETH", "15m", -1, start + 7 * H + 900_000, start + 9 * H, -0.0050, -0.0036, "SL", 8, -0.0060),
            ("T3", "BTC", "1h", 1, start + DAY + 2 * H, start + DAY + 8 * H, 0.0020, 0.0034, "TIME", 6, -0.0030),
            ("T4", "SOL", "30m", -1, start + 2 * DAY + 5 * H, start + 2 * DAY + 9 * H, -0.0080, -0.0066, "SL", 8, -0.0090),
            ("T5", "DOGE", "4h", 1, start + 4 * DAY + 4 * H, None, None, None, None, None, None),
            ("T6", "LTC", "15m", 1, start + 3 * DAY, start + 3 * DAY + 2 * H, 0.0040, 0.0054, "TP", 8, -0.0010),
        ],
        "clone_base": {"T1": -0.0020, "T2": -0.0010, "T3": -0.0030, "T4": 0.0000},      # C[i]
        "clone_step": 0.0001,
        "member_net_pct": [1.0, -0.5, 0.2, -0.8],
        # the owners'-style account over all four timeframes, day-end equity of days 0..4: each trade moves it by 4 x net (20 % margin x 20x):
        #   T1 +1.0 % -> x1.04, T2 -0.5 % -> x0.98 (day 0: 5,096), T3 +0.2 % -> x1.008 (day 1), T4 -0.8 % -> x0.968 (day 2), T6 +0.4 % -> x1.016 (day 3),
        #   T5 is open and blocks the account (day 4 = day 3)
        "account_all": [5000.0 * 1.04 * 0.98, 5000.0 * 1.04 * 0.98 * 1.008, 5000.0 * 1.04 * 0.98 * 1.008 * 0.968,
                        5000.0 * 1.04 * 0.98 * 1.008 * 0.968 * 1.016, 5000.0 * 1.04 * 0.98 * 1.008 * 0.968 * 1.016],
        "account_all_taken": [2, 3, 4, 5, 5],
        "account_15m": [4000.0],                                                           # one liquidation (the margin, 20 %): 5,000 -> 4,000
    }


STANDARD = standard(START)


def _dt(conn: sqlite3.Connection, now: int, member_id: str, ticked: bool, halted: Optional[str], last_tick: Optional[int],
        spec: str, start: int, activated: Optional[int]) -> None:
    conn.execute("INSERT INTO members (member_id, name_ko, detector, spec_json, spec_sha256, start_ms, created_ms, activated_ms, "
                 "last_tick_ms, halted) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (member_id, "매물대 지지→저항 전환 (릴스 parkdando_)", "zoneflip", spec, "0" * 64, start, start - DAY,
                  activated if ticked else None, (last_tick if last_tick is not None else now - 10 * 60_000) if ticked else None, halted))


def add_series(conn: sqlite3.Connection, member_id: str, now: int, mode: str = "standard") -> None:
    """24 series: 'standard' = most recording, LTC 4h warming (150 of 300), BCH 15m in error; 'waiting' = all waiting."""
    for coin in COINS:
        for tf in TFS:
            status, last, have, need, note = "recording", (now // TF_MS[tf]) * TF_MS[tf] - TF_MS[tf], 300, 300, None
            if mode == "waiting":
                status, last, have, need, note = "waiting", None, 0, 0, "시작일 전"
            elif (coin, tf) == ("LTC", "4h"):
                status, have, need, note = "warming", 150, 300, "워밍업 중 (150봉 더 필요)"
            elif (coin, tf) == ("BCH", "15m"):
                status, note = "error", "시세를 받지 못함 (2봉 늦음)"
            conn.execute("INSERT INTO series_state (member_id, coin, tf, status, last_bar_ms, warm_have, warm_need, note, updated_ms) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", (member_id, coin, tf, status, last, have, need, note, now - 600_000))


def add_trades(conn: sqlite3.Connection, member_id: str, now: int, start: int = START, schema: int = 2) -> None:
    for tid, coin, tf, side, entry, exit_, net, gross, reason, hold, mae in standard(start)["trades"]:
        closed = exit_ is not None
        px = {"BTC": 62000.0, "ETH": 2400.0, "SOL": 140.0, "DOGE": 0.11, "LTC": 70.0}.get(coin, 100.0)
        stop = px * (1 - 0.006 * side)
        target = px * (1 + 0.02 * side)
        acct = {"T1": (1, 0.04, 5200.0, 0), "T2": (1, -0.02, 5096.0, 0), "T3": (1, 0.008, 5136.768, 0), "T4": (1, -0.032, 4972.3722, 0),
                "T5": (1, None, None, None), "T6": (1, 0.016, 5051.9302, 0)}.get(tid)
        row = (f"{member_id}|{tid}", member_id, coin, tf, side, entry - TF_MS[tf], entry, px, stop, target, 0.006, 0.02,
               "closed" if closed else "open", exit_, px * (1 + (net or 0) * side) if closed else None, reason, hold, gross,
               None if gross is None else gross - 0.0003, 0.0010, 0.0001, net, mae, 0.01 if closed else None,
               (exit_ or entry) + TF_MS[tf] + 120_000, (exit_ + TF_MS[tf] + 120_000) if closed else None)
        cols = ("trade_id, member_id, coin, tf, side, signal_ms, entry_ms, entry_px, stop_px, target_px, sl_dist, tp_dist, status, "
                "exit_ms, exit_px, reason, hold, gross_raw, gross, fee, funding, net, mae, mfe, recorded_ms, closed_ms")
        if schema >= 2:                                   # the account columns exist from schema version 2
            cols += ", acct_taken, acct_ret, acct_equity, acct_liq"
            row += tuple(acct if acct else (None, None, None, None))
        conn.execute(f"INSERT INTO trades ({cols}) VALUES ({','.join('?' * len(row))})", row)


def add_clones(conn: sqlite3.Connection, member_id: str, now: int, k_count: int = 50, start: int = START) -> None:
    std = standard(start)
    base, step = std["clone_base"], std["clone_step"]
    for tid, coin, tf, side, entry, exit_, net, *_ in std["trades"]:
        trade_id = f"{member_id}|{tid}"
        for k in range(k_count):
            decided = tid in base or (tid == "T6" and k >= 10)          # T5 open: all pending; T6: the first ten pending
            cnet = (base[tid] + step * k) if tid in base else (0.001 * (k % 7 - 3) if decided else None)
            conn.execute(
                "INSERT INTO clones (clone_id, member_id, trade_id, k, coin, tf, side, sl_dist, tp_dist, offset_bars, target_ms, status, entry_ms, "
                "entry_px, exit_ms, exit_px, reason, hold, gross_raw, gross, fee, funding, net, mae, created_ms, resolved_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{trade_id}#{k:02d}", member_id, trade_id, k, coin, tf, side, 0.006, 0.02, k - 25, entry + (k - 25) * TF_MS[tf],
                 "closed" if decided else "pending", entry + (k - 25) * TF_MS[tf] if decided else None, 100.0 if decided else None,
                 entry + (k - 20) * TF_MS[tf] if decided else None, 100.1 if decided else None, "SL" if decided else None, 5 if decided else None,
                 cnet, cnet, 0.0003, 0.0001, cnet, -0.002 if decided else None, entry, now - 3600_000 if decided else None))


def add_account(conn: sqlite3.Connection, member_id: str, now: int, start: int = START) -> None:
    std = standard(start)
    eq = std["account_all"]
    rets = [(e / 5000.0 - 1) * 100 for e in eq]
    taken = std["account_all_taken"]
    for i, e in enumerate(eq):
        day = start + i * DAY
        conn.execute("INSERT INTO account_daily (member_id, scope, day_ms, equity, ret_pct, taken, liquidated, asof_ms) VALUES (?,?,?,?,?,?,?,?)",
                     (member_id, "all", day, e, rets[i], taken[i], 0, min(day + DAY, now)))
    for i, e in enumerate(std["account_15m"]):
        day = start + i * DAY
        conn.execute("INSERT INTO account_daily (member_id, scope, day_ms, equity, ret_pct, taken, liquidated, asof_ms) VALUES (?,?,?,?,?,?,?,?)",
                     (member_id, "15m", day, e, (e / 5000.0 - 1) * 100, 1, 1, min(day + DAY, now)))


def add_signals(conn: sqlite3.Connection, member_id: str, now: int, start: int = START) -> None:
    """14 signals; the first is 'late' (its bar is earlier than the member's activation)."""
    rows = [("BTC", "15m", 1, start + H, "taken"), ("BTC", "15m", 1, start + 3 * H, "taken"), ("ETH", "15m", -1, start + 7 * H, "taken"),
            ("BTC", "1h", 1, start + DAY + H, "taken"), ("SOL", "30m", -1, start + 2 * DAY + 4 * H, "taken"), ("LTC", "15m", 1, start + 3 * DAY - 900_000, "taken"),
            ("DOGE", "4h", 1, start + 4 * DAY, "taken"), ("ETH", "15m", 1, start + 8 * H, "busy"), ("BTC", "30m", -1, start + 10 * H, "skip_rr"),
            ("SOL", "1h", 1, start + DAY + 5 * H, "skip_no_target"), ("DOGE", "15m", -1, start + DAY + 7 * H, "skip_stop_far"),
            ("ETH", "30m", 1, start + 2 * DAY, "skip_entry"), ("BTC", "15m", -1, start + 3 * DAY + 5 * H, "not_chosen"),
            ("SOL", "15m", 1, now - 1_800_000, "pending_entry")]
    for i, (coin, tf, side, bar, status) in enumerate(rows):
        px = {"BTC": 62000.0, "ETH": 2400.0, "SOL": 140.0, "DOGE": 0.11, "LTC": 70.0}[coin]
        conn.execute(
            "INSERT INTO signals (signal_id, member_id, coin, tf, side, bar_ms, break_ms, plan_entry, stop, target, rr, touches, atr, zone_lo, zone_hi, "
            "tz_lo, tz_hi, status, recorded_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"{member_id}|{coin}|{tf}|{bar}|{side}|{i}", member_id, coin, tf, side, bar, bar - 5 * TF_MS[tf], px, px * (1 - 0.006 * side),
             None if status == "skip_no_target" else px * (1 + 0.02 * side), None if status == "skip_no_target" else 3.2, 3, px * 0.004,
             px * 0.99, px * 1.0, px * 0.9, px * 0.92, status, bar + 2 * H))


def build(path: str, *, now: int = NOW, schema: int = 2, ticked: bool = True, halted: Optional[str] = None, last_tick_ms: Optional[int] = None,
          start: int = START, activated: Optional[int] = None, series_mode: str = "standard", with_data: bool = True, spec: Optional[str] = None,
          member_id: str = "zoneflip", wal: bool = True, version_row: Optional[str] = "default") -> dict:
    """Create the database file at ``path`` (a fresh file) and fill it. Returns the facts the tests compare against.
    schema 1 = the older shape (no clones, no day-end rows, no account columns). with_data False = the member and its 24 series only."""
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(ddl(schema))
        conn.execute("BEGIN")
        act = (start + 2 * H) if activated is None else activated
        _dt(conn, now, member_id, ticked, halted, last_tick_ms, spec or spec_json(start_ms=start, member_id=member_id), start, act)
        sv = str(schema) if version_row == "default" else version_row
        if sv is not None:
            conn.execute("INSERT INTO league_meta (k, v) VALUES ('schema_version', ?)", (sv,))
        if ticked:
            tick = {"ms": (last_tick_ms if last_tick_ms is not None else now - 10 * 60_000), "wall_s": 4.2, "bars_added": 8, "signals": 1,
                    "opened": 0, "closed": 1, "errors": [f"{member_id}/LTC/4h: 12 clones wait for an entry bar that is no longer stored"],
                    "timed_out": False, "behind": 0}
            conn.execute("INSERT INTO league_meta (k, v) VALUES ('last_tick', ?)", (json.dumps(tick),))
        if ticked or with_data:
            add_series(conn, member_id, now, series_mode)
        if with_data:
            add_trades(conn, member_id, now, start, schema)
            add_signals(conn, member_id, now, start)
            if schema >= 2:
                add_clones(conn, member_id, now, 50, start)
                add_account(conn, member_id, now, start)
        conn.execute("COMMIT")
    finally:
        conn.close()
    return {"path": path, "now": now, "start": start, "activated": (start + 2 * H) if activated is None else activated,
            "member_id": member_id}


def add_member(path: str, member_id: str, name: str, now: int = NOW, study: str = "") -> None:
    """A second, empty member (to show the list of members): ticked, 24 waiting series, no trades."""
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        conn.execute("BEGIN")
        conn.execute("INSERT INTO members (member_id, name_ko, detector, spec_json, spec_sha256, start_ms, created_ms, activated_ms, last_tick_ms, halted) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (member_id, name, member_id, spec_json(member_id=member_id, study=study, start_ms=now + DAY),
                                                       "1" * 64, now + DAY, now - DAY, now - H, now - 600_000, None))
        add_series(conn, member_id, now, "waiting")
        conn.execute("COMMIT")
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------------------------
# A bigger, random (seeded) world for the screenshots and the speed test: many trades, 50 clones each, a real account run.
OWN_EXPO, OWN_MARGIN, OWN_LIQ = 4.0, 0.20, 1 / 20 - 0.005          # the owners' account (the bot's account.py)
SL_DIST = {"15m": 0.0065, "30m": 0.0085, "1h": 0.0125, "4h": 0.026}
COST = {"15m": 0.0014, "30m": 0.0014, "1h": 0.0014, "4h": 0.0021}
PX = {"BTC": 62000.0, "ETH": 2400.0, "SOL": 140.0, "DOGE": 0.11, "LTC": 70.0, "BCH": 380.0}


def _outcome(rng, tf: str, win_p: float) -> tuple:
    """(net, reason, hold bars, mae) of one trade at 1x after costs: about a quarter reach the 3 x stop target, most hit the stop."""
    sl, cost = SL_DIST[tf], COST[tf]
    u = rng.random()
    if u < win_p:
        return 3 * sl - cost, "TP", rng.randint(4, 40), -rng.uniform(0.0, 0.8) * sl
    if u < win_p + 0.05:
        return rng.uniform(-0.8, 1.4) * sl - cost, "TIME", 48, -rng.uniform(0.2, 1.0) * sl
    return -sl - cost, "SL", rng.randint(2, 30), -sl


def run_account(trades: list) -> list:
    """The owners' account over trades [(trade_id, entry_ms, exit_ms|None, net|None, mae|None, tf)] in entry order: one result per
    trade {taken, liquidated, multiple} (multiple None while open): the same rules as the bot's account.py."""
    mult, last_exit, blocked, out = 1.0, None, False, []
    for tid, entry, exit_, net, mae, tf in sorted(trades, key=lambda t: (t[1], t[0])):
        if blocked or (last_exit is not None and entry < last_exit):
            out.append((tid, False, False, None, None))
            continue
        if exit_ is None:
            blocked = True
            out.append((tid, True, False, None, None))
            continue
        liq = -mae >= OWN_LIQ
        mult *= (1 - OWN_MARGIN) if liq else (1 + max(OWN_EXPO * net, -OWN_MARGIN))
        last_exit = exit_
        out.append((tid, True, liq, mult, exit_ + TF_MS[tf]))
    return out


def day_rows(results: list, start: int, asof: int) -> list:
    """Day-end rows [(day_ms, equity, ret_pct, taken, liquidated, asof_ms)] from run_account's results (settled at the exit bar's end)."""
    done = sorted((r[4], r[3], r[2]) for r in results if r[1] and r[3] is not None)
    rows, k, eq, taken, liqs, d = [], 0, 5000.0, 0, 0, (start // DAY) * DAY
    while d <= ((asof - 1) // DAY) * DAY:
        edge = min(d + DAY, asof)
        while k < len(done) and done[k][0] <= edge:
            eq, taken, liqs, k = 5000.0 * done[k][1], taken + 1, liqs + int(done[k][2]), k + 1
        rows.append((d, eq, (eq / 5000.0 - 1) * 100, taken, liqs, edge))
        d += DAY
    return rows


def build_rich(path: str, *, now: int, days: int = 24, seed: int = 7, per_day: float = 2.4, member_id: str = "zoneflip",
               win_p: float = 0.24, clone_win_p: float = 0.22) -> dict:
    """A member that started ``days`` days before ``now`` (midnight UTC) with about per_day trades a day over all 24 series, 50 clones
    each (the clones of a trade that closed within 5 days are partly pending), the account rows of every scope, signals and the
    24 series' states. Deterministic for a seed."""
    import random
    rng = random.Random(seed)
    start = ((now - days * DAY) // DAY) * DAY
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    facts = {"trades": 0, "closed": 0}
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(ddl(2))
        conn.execute("BEGIN")
        _dt(conn, now, member_id, True, None, None, spec_json(start_ms=start, member_id=member_id), start, start + 2 * H)
        conn.execute("INSERT INTO league_meta (k, v) VALUES ('schema_version', '2')")
        conn.execute("INSERT INTO league_meta (k, v) VALUES ('last_tick', ?)", (json.dumps(
            {"ms": now - 8 * 60_000, "wall_s": 6.4, "bars_added": 24, "signals": 2, "opened": 1, "closed": 1, "errors": [], "timed_out": False, "behind": 0}),))
        add_series(conn, member_id, now, "standard")
        n = int(days * per_day)
        acct, by_scope = [], {sc: [] for sc in TFS}
        for i in range(n):
            coin, tf = rng.choice(COINS), rng.choice(TFS)
            if (coin, tf) in (("LTC", "4h"), ("BCH", "15m")):
                continue
            side = rng.choice((1, -1))
            entry = start + 3 * H + int(rng.random() * (now - start - 12 * H - 3 * H)) // TF_MS[tf] * TF_MS[tf]
            net, reason, hold, mae = _outcome(rng, tf, win_p)
            exit_ = entry + hold * TF_MS[tf]
            is_open = exit_ + TF_MS[tf] > now - 20 * 60_000
            px, sl = PX[coin], SL_DIST[tf]
            tid = f"{member_id}|{coin}|{tf}|{entry}|{side}|{i}"
            facts["trades"] += 1
            conn.execute(
                "INSERT INTO trades (trade_id, member_id, coin, tf, side, signal_ms, entry_ms, entry_px, stop_px, target_px, sl_dist, tp_dist, status, exit_ms, "
                "exit_px, reason, hold, gross_raw, gross, fee, funding, net, mae, mfe, recorded_ms, closed_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, member_id, coin, tf, side, entry - TF_MS[tf], entry, px, px * (1 - sl * side), px * (1 + 3 * sl * side), sl, 3 * sl,
                 "open" if is_open else "closed", None if is_open else exit_, None if is_open else px * (1 + net * side), None if is_open else reason,
                 None if is_open else hold, None if is_open else net + COST[tf], None if is_open else net + COST[tf] - 0.0002, 0.0010, 0.0001,
                 None if is_open else net, None if is_open else mae, None if is_open else 0.02, entry + 120_000, None if is_open else exit_ + TF_MS[tf] + 120_000))
            facts["closed"] += 0 if is_open else 1
            row = (tid, entry, None if is_open else exit_, None if is_open else net, None if is_open else mae, tf)
            acct.append(row)
            by_scope[tf].append(row)
            fresh = (not is_open) and exit_ > now - 5 * DAY
            for k in range(50):
                pend = is_open or (fresh and k % 5 == 0)
                cn, cr, ch, cm = _outcome(rng, tf, clone_win_p)
                conn.execute(
                    "INSERT INTO clones (clone_id, member_id, trade_id, k, coin, tf, side, sl_dist, tp_dist, offset_bars, target_ms, status, entry_ms, entry_px, "
                    "exit_ms, exit_px, reason, hold, gross_raw, gross, fee, funding, net, mae, created_ms, resolved_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"{tid}#{k:02d}", member_id, tid, k, coin, tf, side, sl, 3 * sl, k - 25, entry, "pending" if pend else "closed",
                     None if pend else entry, None if pend else px, None if pend else entry + ch * TF_MS[tf], None if pend else px, None if pend else cr,
                     None if pend else ch, None if pend else cn + COST[tf], None if pend else cn + COST[tf], 0.0010, 0.0001, None if pend else cn,
                     None if pend else cm, entry, None if pend else now - H))
        # taken / not taken, stored on each trade as the bot's rows have them (the 'all' account)
        for tid, taken, liq, mult, _ in run_account(acct):
            conn.execute("UPDATE trades SET acct_taken = ?, acct_liq = ?, acct_equity = ? WHERE trade_id = ?",
                         (int(taken), None if mult is None else int(liq), None if mult is None else 5000.0 * mult, tid))
        for scope, rows in [("all", acct)] + list(by_scope.items()):
            for d, eq, ret, taken, liqs, edge in day_rows(run_account(rows), start, now):
                conn.execute("INSERT INTO account_daily (member_id, scope, day_ms, equity, ret_pct, taken, liquidated, asof_ms) VALUES (?,?,?,?,?,?,?,?)",
                             (member_id, scope, d, eq, ret, taken, liqs, edge))
        add_signals(conn, member_id, now, start)
        conn.execute("COMMIT")
    finally:
        conn.close()
    return {"path": path, "now": now, "start": start, **facts}
