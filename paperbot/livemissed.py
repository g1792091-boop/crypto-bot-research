"""못 탄 신호 성적 (D1, owners 10/19 "못 탄 신호들은 어땠나"): what the signals the paper bot could NOT take would have done.

The combined paper bot (paperbot/combo.py, account COMBO@mix, the one both live executors follow) holds ONE position at a
time: a signal that comes while a position is open, or that loses to another signal of the same minute, is recorded by its
engine as an outcome SKIPPED and never traded. That rule stays as it is (the owners' fixed rule): this module only looks.

    missed_pass(src, conn, now_ms)           one pass, from the 1-minute watcher (paperbot/livecheck.py run_watch)
    python -m paperbot.livemissed show       the owners' summary and the newest rows, in Korean
    python -m paperbot.livemissed run        one pass now (the watcher does it every minute)

Which signals: the account's outcomes SKIPPED in the last 7 KST days for the one-position rule only (engine.py
``_handle_entries`` / combo.py ``ComboEngine.step``, their exact reasons):
    "in position"                       a position was open (detail: held_symbol, held_strategy)  -> why "이미 BTC 롱 보유 중"
    "lower score than entered signal"   another signal of the same minute went in (rank)          -> why "같은 분에 ETH 숏이 먼저 들어감"
    "early exit this minute"            the position was closed by an opposite signal that minute and the bot never
                                        switches (early_exit; off in the live config)              -> why "그 분에 빠른 청산 (갈아타지 않음)"
Research filters, switched-off buckets, the weekend and macro pauses are FILTERED in signal_log and late signals REJECTED:
never here.

Each is simulated by paperbot/livesim.py on the paper bot's own engine (a fresh ComboEngine of the config the paper bot runs,
its ``combo_run`` record, with its taker fee) from its entry minute on the rule bot's 1m bars, with the Signal rebuilt from
the outcome exactly as the engine received it (meta: member, rstop, rswing, ref_price, atr …) and the paper account's wallet
at that moment (the wallet after its last closed trade before it; the open trade's own entry fee and funding are not taken
out: the size moves a hair, the ROE does not). Funding is not included (no database keeps the rates: livesim
FUNDING_NOTE_KO). The leverage brackets are the repository's saved Binance table unless the config names a file.

Stored in livecheck.db (the watcher's own file), table ``missed``, one row per signal (key = member|coin|signal bar close):
state ``open`` (re-simulated every pass from its entry: cheap), ``closed`` (never simulated again), ``no_data`` (no 1m bar
at its entry minute: nothing made up), ``refused`` (the engine would not have entered it either: the stop does not fit, the
size), ``error`` (the reason; tried again after RETRY_MS); with the trade the paper bot was in at that moment (its id and
result: "그때 탄 거래: BTC 롱 +12%"), kept fresh while that trade is open. ``missed_meta`` holds the last pass.
Bounded: at most MAX_SIMS simulations and BUDGET_S seconds a pass (the rest wait for the next pass; said on stderr).
A pass never raises: an error is stored with its reason (a row) or in ``missed_meta`` (the pass).
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from typing import Callable, Optional

MIN = 60_000
H1 = 3_600_000
DAY = 86_400_000
KST_MS = 9 * H1
ACCOUNT = "COMBO@mix"
DEFAULT_DB = "/var/lib/paperbot/livecheck.db"
PAPER_DB = "/var/lib/paperbot/combo/live-ac.db"
RULE_DB = "/var/lib/paperbot/paper3.db"
COMBO_CONFIG = "/etc/paperbot/combo.json"
REASONS = {"in position": "held", "lower score than entered signal": "lost", "early exit this minute": "early"}
WINDOW_DAYS = 7                     # the KST days a pass looks back for skipped signals
MAX_SIMS = 30                       # simulations per pass
BUDGET_S = 10.0                     # seconds of simulation per pass
RETRY_MS = 10 * MIN                 # error / no_data rows are tried again after this
OPEN_DAYS = 14                      # a virtual trade is followed this long from its entry (livesim.MAX_MINUTES)
KEEP_DAYS = 90                      # rows older than this are deleted
SMALL = 20                          # fewer closed trades than this: 표본 적음
KO_SIDE = {1: "롱", -1: "숏"}
KO_TF = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
KO_EXIT = {"SL": "손절", "LOCK": "계단 익절", "LIQ": "강제청산", "HALT": "멈춤 청산", "MANUAL": "수동 청산", "REV": "빠른 청산",
           "TP": "익절", "END": "끝"}
KO_STATE = {"open": "진행 중", "closed": "끝남", "no_data": "1분봉 없음", "refused": "진입 안 됨", "error": "못 읽음"}
KO_WHY = {"held": "포지션 있음 (한 번에 하나)", "lost": "같은 분 다른 신호에 밀림", "early": "빠른 청산 분 (갈아타지 않음)"}
NOTE_KO = ("가상 결과예요: 페이퍼 봇과 같은 엔진·같은 1분봉으로 계산했지만 실제 체결이 아니에요. 1포지션 규칙은 그대로이고, 이건 "
           "바꾸자는 뜻이 아니라 보기만 하는 거예요. 거래가 적을 때는 대부분 운이에요.")
SCHEMA = """
CREATE TABLE IF NOT EXISTS missed (
    key TEXT PRIMARY KEY,
    t INTEGER NOT NULL,
    step_ts INTEGER NOT NULL,
    member TEXT,
    strategy TEXT,
    tf TEXT,
    symbol TEXT NOT NULL,
    side INTEGER NOT NULL,
    why_kind TEXT NOT NULL,
    why TEXT NOT NULL,
    state TEXT NOT NULL,
    entry_ts INTEGER,
    entry_price REAL,
    stop REAL,
    leverage INTEGER,
    margin REAL,
    exit_ts INTEGER,
    exit_price REAL,
    reason TEXT,
    roe_net REAL,
    pnl REAL,
    best_roe REAL,
    last_ts INTEGER,
    wallet REAL,
    taken_id INTEGER,
    taken_state TEXT,
    taken_roe REAL,
    taken_pnl REAL,
    taken TEXT,
    error TEXT,
    sims INTEGER NOT NULL DEFAULT 0,
    first_ts INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL,
    signal TEXT NOT NULL,
    detail TEXT,
    data TEXT,
    path TEXT
);
CREATE INDEX IF NOT EXISTS missed_t ON missed (t);
CREATE TABLE IF NOT EXISTS missed_meta (
    k TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    data TEXT NOT NULL
);
"""
COLS = ("key", "t", "step_ts", "member", "strategy", "tf", "symbol", "side", "why_kind", "why", "state", "entry_ts", "entry_price",
        "stop", "leverage", "margin", "exit_ts", "exit_price", "reason", "roe_net", "pnl", "best_roe", "last_ts", "wallet",
        "taken_id", "taken_state", "taken_roe", "taken_pnl", "taken", "error", "sims", "first_ts", "updated_ts", "signal",
        "detail", "data", "path")
READ_COLS = tuple(c for c in COLS if c not in ("signal", "detail", "path"))     # what the screen and ``show`` read
LIGHT_COLS = ("key", "t", "step_ts", "state", "updated_ts", "taken_state", "taken_roe", "why_kind")


class MissedError(RuntimeError):
    """A reason a signal could not be simulated (Korean, stored with the row)."""


# ====================================================================== small helpers
def coin(symbol) -> str:
    return str(symbol or "").replace("USDT", "")


def kst(ms: int, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(int(ms) / 1000 + 9 * 3600))


def window_start(now_ms: int, days: int = WINDOW_DAYS) -> int:
    """00:00 KST of the day ``days - 1`` KST days before today (today and the six days before it)."""
    kd = (int(now_ms) + KST_MS) // DAY
    return (kd - (days - 1)) * DAY - KST_MS


def _f(x) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _j(raw) -> dict:
    try:
        d = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _pct(x: Optional[float], d: int = 1) -> str:
    if x is None:
        return "-"
    s = f"{abs(x) * 100:.{d}f}%"
    return ("+" if x > 0 and float(s[:-1]) else "−" if x < 0 and float(s[:-1]) else "") + s


def _dur(ms: Optional[int]) -> str:
    if ms is None:
        return "-"
    m = max(0, int(ms) // MIN)
    if m < 60:
        return f"{m}분"
    if m < 1440:
        return f"{m // 60}시간 {m % 60}분" if m % 60 else f"{m // 60}시간"
    return f"{m // 1440}일 {(m % 1440) // 60}시간"


# ====================================================================== the paper bot's records (read-only)
def read_paper(pc, since: int, trades_since: Optional[int] = None) -> dict:
    """One snapshot of the paper bot's database: the account's SKIPPED outcomes since ``since`` (one-position reasons only),
    its closed trades (``trades_since``: those that closed from then on and the last one before, for the wallet; None:
    all), its open position and last marks, its ``combo_run`` record."""
    q = ("SELECT id, symbol, entry_time, exit_time, exit_reason, pnl, roe, equity_after, data FROM trades WHERE account_id = ? ")
    pc.execute("BEGIN")
    try:
        outs = pc.execute("SELECT id, step_ts, reason, symbol, data FROM outcomes WHERE account_id = ? AND status = 'SKIPPED' "
                          "AND step_ts >= ? ORDER BY step_ts, id", (ACCOUNT, int(since))).fetchall()
        if trades_since is None:
            trows = pc.execute(q + "ORDER BY exit_time, id", (ACCOUNT,)).fetchall()
        else:
            trows = pc.execute(q + "AND exit_time < ? ORDER BY exit_time DESC, id DESC LIMIT 1", (ACCOUNT, int(trades_since))).fetchall()
            trows += pc.execute(q + "AND exit_time >= ? ORDER BY exit_time, id", (ACCOUNT, int(trades_since))).fetchall()
        st = pc.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        run = pc.execute("SELECT data FROM state WHERE k = 'combo_run'").fetchone()
    finally:
        pc.execute("ROLLBACK")
    cands = []
    for oid, step, reason, sym, data in outs:
        kind = REASONS.get(reason)
        if kind is None:
            continue
        d = _j(data)
        sig = d.get("signal") if isinstance(d.get("signal"), dict) else None
        if not sig or sig.get("ts") is None:
            cands.append({"key": f"outcome:{oid}", "bad": True, "step_ts": int(step), "symbol": sym, "kind": kind, "reason": reason,
                          "t": int(step), "member": None, "strategy": None, "tf": None, "side": 0, "signal": {}, "detail": {}})
            continue
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        t = int(sig["ts"]) + 1
        member = meta.get("member") or sig.get("strategy_id")
        cands.append({"key": f"{member}|{sym}|{t}", "bad": False, "step_ts": int(step), "symbol": sym, "kind": kind, "reason": reason,
                      "t": t, "member": member, "strategy": sig.get("strategy_id"), "tf": sig.get("timeframe"),
                      "side": int(sig.get("side") or 0), "signal": sig, "detail": d.get("detail") if isinstance(d.get("detail"), dict) else {}})
    trades = []
    for tid, sym, et, xt, why, pnl, roe, eq, data in trows:
        d = _j(data)
        trades.append({"id": int(tid), "symbol": sym, "entry_time": int(et), "exit_time": int(xt), "reason": why, "pnl": _f(pnl),
                       "roe": _f(roe), "equity_after": _f(eq), "side": int(d.get("side") or 0), "strategy": d.get("strategy_id"),
                       "tf": d.get("timeframe")})
    eng = ((_j(st[0]).get("engines") or {}).get(ACCOUNT) or {}) if st else {}
    pos = eng.get("position") if isinstance(eng.get("position"), dict) else None
    marks = eng.get("last_mark") if isinstance(eng.get("last_mark"), dict) else {}
    run_d = _j(run[0]) if run else {}
    return {"cands": cands, "trades": trades, "pos": pos, "marks": marks, "run": run_d}


def config_of(paper: dict, config_file: str) -> tuple:
    """(config, taker fee, where from): the paper bot's own ``combo_run`` record, else the config file."""
    run = paper.get("run") or {}
    if isinstance(run.get("config"), dict):
        return run["config"], _f(run.get("taker_fee")), "기록"
    try:
        with open(config_file, encoding="utf-8") as fh:
            raw = json.load(fh)
        return (raw if isinstance(raw, dict) else None), None, config_file
    except (OSError, ValueError):
        return None, None, ""


def wallet_at(trades: list, step_ts: int, initial: float, inclusive: bool = False) -> float:
    """The account's wallet after its last trade closed before the minute ``step_ts`` (``inclusive``: at that minute too,
    an early exit closes before the entries), else the initial equity."""
    w = None
    for t in trades:
        if t["exit_time"] < step_ts or (inclusive and t["exit_time"] <= step_ts):
            if t["equity_after"] is not None:
                w = t["equity_after"]
    return float(w if w is not None else initial)


def _pos_taken(pos: dict, marks: dict, rt: float) -> dict:
    sig = pos.get("signal") if isinstance(pos.get("signal"), dict) else {}
    sym, side = pos.get("symbol"), int(pos.get("side") or 0)
    entry, lev = _f(pos.get("entry_price")), _f(pos.get("leverage"))
    qty, fund = _f(pos.get("qty")) or 0.0, _f(pos.get("funding_paid")) or 0.0
    mark = _f(marks.get(sym))
    ff = fund / (qty * entry) if qty and entry else 0.0
    roe = lev * (side * (mark / entry - 1.0) - rt - ff) if (mark and entry and lev) else None
    return {"id": None, "symbol": sym, "side": side, "strategy": sig.get("strategy_id"), "tf": sig.get("timeframe"),
            "state": "open", "roe": roe, "pnl": None, "reason": None, "entry_time": int(pos.get("entry_time") or 0), "exit_time": None}


def _trade_taken(t: dict) -> dict:
    return {"id": t["id"], "symbol": t["symbol"], "side": t["side"], "strategy": t["strategy"], "tf": t["tf"], "state": "closed",
            "roe": t["roe"], "pnl": t["pnl"], "reason": t["reason"], "entry_time": t["entry_time"], "exit_time": t["exit_time"]}


def taken_of(kind: str, step_ts: int, detail: dict, trades: list, pos: Optional[dict], marks: dict, rt: float) -> Optional[dict]:
    """The paper trade that had the place at that moment: the open one ("held": entered before the minute, closed at or
    after it, on the held coin), the one entered in that same minute ("lost"), or the one the early exit closed then
    ("early"). Closed trades from the trades table; one still open from the engine's state (its net ROE at the last mark,
    the ladder's formula)."""
    step_ts = int(step_ts)
    if kind == "held":
        sym = (detail or {}).get("held_symbol")
        xs = [t for t in trades if t["entry_time"] < step_ts <= t["exit_time"] and (not sym or t["symbol"] == sym)]
        if xs:
            return _trade_taken(max(xs, key=lambda t: (t["entry_time"], t["id"])))
        if pos and int(pos.get("entry_time") or 0) < step_ts and (not sym or pos.get("symbol") == sym):
            return _pos_taken(pos, marks, rt)
        return None
    if kind == "lost":
        xs = [t for t in trades if t["entry_time"] == step_ts]
        if xs:
            return _trade_taken(xs[0])
        if pos and int(pos.get("entry_time") or 0) == step_ts:
            return _pos_taken(pos, marks, rt)
        return None
    xs = [t for t in trades if t["exit_time"] == step_ts and t["reason"] == "REV"]
    return _trade_taken(xs[-1]) if xs else None


def why_of(kind: str, taken: Optional[dict], detail: dict) -> str:
    """Why the signal was not taken, in the owners' words."""
    if kind == "held":
        if taken:
            return f"이미 {coin(taken['symbol'])} {KO_SIDE.get(taken['side'], '')} 보유 중".replace("  ", " ")
        sym = (detail or {}).get("held_symbol")
        return f"이미 {coin(sym)} 포지션 보유 중" if sym else "이미 포지션 보유 중"
    if kind == "lost":
        if taken:
            return f"같은 분에 {coin(taken['symbol'])} {KO_SIDE.get(taken['side'], '')} 신호가 먼저 들어감"
        return "같은 분에 다른 신호가 먼저 들어감"
    return "그 분에 반대 신호로 빠른 청산 (갈아타지 않음)"


# ====================================================================== the pass
def _meta_put(conn, now_ms: int, data: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO missed_meta VALUES (?,?,?)", ("pass", int(now_ms), json.dumps(data, ensure_ascii=False)))


def _first_put(conn, now_ms: int, since: int) -> None:
    """The start of what the table covers (the first pass's window), kept once."""
    conn.execute("INSERT OR IGNORE INTO missed_meta VALUES (?,?,?)", ("first", int(now_ms), json.dumps({"since": int(since)})))


def _existing(conn, since: int) -> dict:
    """{key: the few columns that decide the work} of the rows from ``since`` on (no JSON read)."""
    cur = conn.execute(f"SELECT {', '.join(LIGHT_COLS)} FROM missed WHERE t >= ?", (int(since),))
    return {r[0]: dict(zip(LIGHT_COLS, r)) for r in cur.fetchall()}


def _full(conn, key: str) -> Optional[dict]:
    cur = conn.execute("SELECT * FROM missed WHERE key = ?", (key,))
    r = cur.fetchone()
    return None if r is None else dict(zip([c[0] for c in cur.description], r))


def _upsert(conn, row: dict) -> None:
    conn.execute(f"INSERT OR REPLACE INTO missed ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                 tuple(row.get(c) for c in COLS))


def _base(c: dict, old: Optional[dict], now_ms: int) -> dict:
    """A row's identity, kept from its first sight."""
    row = dict(old) if old else {}
    row.update(key=c["key"], t=c["t"], step_ts=c["step_ts"], member=c["member"], strategy=c["strategy"], tf=c["tf"],
               symbol=c["symbol"], side=c["side"], why_kind=c["kind"],
               signal=json.dumps(c["signal"], default=str, ensure_ascii=False),
               detail=json.dumps(c["detail"], default=str, ensure_ascii=False))
    row.setdefault("first_ts", int(now_ms))
    row.setdefault("sims", 0)
    return row


def _with_taken(row: dict, taken: Optional[dict]) -> dict:
    row.update(taken_id=taken.get("id") if taken else None, taken_state=taken.get("state") if taken else None,
               taken_roe=taken.get("roe") if taken else None, taken_pnl=taken.get("pnl") if taken else None,
               taken=json.dumps(taken, ensure_ascii=False) if taken else None)
    return row


def _apply(row: dict, r: dict, rig_notes: list) -> dict:
    """The simulation's answer into the row (livesim.simulate's shape)."""
    from .livesim import thin_path
    ent, ex = r.get("entry") or {}, r.get("exit") or {}
    roe = ex.get("roe") if r["state"] == "closed" else (r.get("latest") or {}).get("roe")
    row.update(state=r["state"], entry_ts=ent.get("ts"), entry_price=ent.get("price"), stop=ent.get("stop"),
               leverage=ent.get("leverage"), margin=ent.get("margin"), exit_ts=ex.get("ts"), exit_price=ex.get("price"),
               reason=ex.get("reason"), roe_net=roe, pnl=ex.get("pnl"), best_roe=r.get("best_roe"), last_ts=r.get("last_ts"),
               error=None,
               data=json.dumps({"stop_now": r.get("stop"), "lock": r.get("lock"), "why": r.get("why") or "", "reject": r.get("reject"),
                                "stop_rule": ent.get("stop_rule"), "funding": r.get("funding"), "minutes": r.get("minutes"),
                                "notes": rig_notes}, default=str, ensure_ascii=False),
               path=json.dumps(thin_path(r.get("path") or []), default=str))
    return row


def missed_pass(src, conn, now_ms: int, cap: int = MAX_SIMS, budget_s: float = BUDGET_S,
                log: Optional[Callable[[str], None]] = None) -> dict:
    """One pass of 못 탄 신호 성적 for the 1-minute watcher (module docstring). ``src``: livecheck.Sources (its paper_db,
    rule_db, combo_config); ``conn``: livecheck.db open for writing (the watcher's own connection; committed here).
    Returns {new, resim, closed, errors, left, capped, taken, rows, elapsed_s} (``error`` when the pass itself failed).
    Never raises."""
    say = log or _stderr
    res = {"new": 0, "resim": 0, "closed": 0, "errors": 0, "left": 0, "capped": False, "taken": 0, "rows": 0}
    t0 = time.monotonic()
    try:
        _schema(conn)
        # a savepoint: a failure here undoes this pass only, never the watcher's other passes on the same connection
        conn.execute("SAVEPOINT missed_pass")
        try:
            _pass(src, conn, int(now_ms), int(cap), float(budget_s), res, t0)
        except BaseException:
            conn.execute("ROLLBACK TO missed_pass")
            conn.execute("RELEASE missed_pass")
            raise
        conn.execute("RELEASE missed_pass")
        conn.commit()
    except Exception as exc:  # noqa: BLE001  the watcher's other passes go on
        res["error"] = f"{type(exc).__name__}: {exc}"[:300]
        try:
            _schema(conn)
            _meta_put(conn, now_ms, {"state": "error", "error": res["error"], "now": int(now_ms)})
            conn.commit()
        except Exception:  # noqa: BLE001
            pass
        say(f"[못 탄 신호] 이번 계산 실패: {res['error']}")
    res["elapsed_s"] = round(time.monotonic() - t0, 3)
    if res.get("capped"):
        say(f"[못 탄 신호] 이번에 {res['new'] + res['resim']}개만 계산했어요(한 번에 {cap}개·{budget_s:g}초까지), "
            f"남은 {res['left']}개는 다음 감시 때")
    return res


def _schema(conn) -> None:
    """The tables, one statement at a time (``executescript`` would commit whatever the watcher has pending)."""
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            conn.execute(stmt)


def _pass(src, conn, now_ms: int, cap: int, budget_s: float, res: dict, t0: float) -> None:
    from . import livecheck as LC
    from . import livesim as LS
    since = window_start(now_ms)
    pc = LC.open_ro(getattr(src, "paper_db", ""))
    if pc is None:
        _meta_put(conn, now_ms, {"state": "no_paper", "now": now_ms, "paper_db": getattr(src, "paper_db", "")})
        return
    look = since - OPEN_DAYS * DAY                 # the rows still worked on: open ones are followed OPEN_DAYS
    try:
        paper = read_paper(pc, since, trades_since=look)
    finally:
        pc.close()
    _first_put(conn, now_ms, since)
    cfg_raw, fee, cfg_src = config_of(paper, getattr(src, "combo_config", COMBO_CONFIG))
    rig, rig_err = None, None
    if cfg_raw is None:
        rig_err = "페이퍼 봇 설정을 못 읽음 (기록에도 설정 파일에도 없음)"
    else:
        try:
            rig = LS.rig_of(cfg_raw, taker_fee=fee)
        except Exception as exc:  # noqa: BLE001  every row says so
            rig_err = f"페이퍼 봇 설정으로 엔진을 못 만듦: {type(exc).__name__}: {exc}"[:300]
    initial = rig.initial if rig is not None else (_f((cfg_raw or {}).get("initial_equity")) or 1000.0)
    rt = rig.settings.round_trip_cost if rig is not None else 0.0014
    trades, pos, marks = paper["trades"], paper["pos"], paper["marks"]
    have = _existing(conn, look)
    cands = {c["key"]: c for c in paper["cands"]}

    def cand_of(row: dict) -> dict:
        return {"key": row["key"], "bad": not _j(row["signal"]), "step_ts": int(row["step_ts"]), "symbol": row["symbol"], "kind": row["why_kind"],
                "t": int(row["t"]), "member": row["member"], "strategy": row["strategy"], "tf": row["tf"], "side": int(row["side"]),
                "signal": _j(row["signal"]), "detail": _j(row["detail"])}

    jobs = []                                       # (kind, key): open rows first, then new signals, then retries
    by_age = sorted(have.items(), key=lambda kv: kv[1]["updated_ts"])
    for key, row in by_age:
        if row["state"] == "open" and int(row["step_ts"]) >= now_ms - OPEN_DAYS * DAY:
            jobs.append(("resim", key))
    for c in paper["cands"]:
        if c["key"] not in have:
            jobs.append(("new", c["key"]))
    for key, row in by_age:
        if row["state"] in ("error", "no_data") and int(row["t"]) >= since and int(row["updated_ts"]) <= now_ms - RETRY_MS:
            jobs.append(("resim", key))
    rc = LC.open_ro(getattr(src, "rule_db", ""))
    try:
        for i, (kind, key) in enumerate(jobs):
            if i >= cap or time.monotonic() - t0 > budget_s:
                res["capped"], res["left"] = True, len(jobs) - i
                break
            old = _full(conn, key) if key in have else None
            c = cands.get(key) or cand_of(old)
            row = _base(c, old, now_ms)
            taken = taken_of(c["kind"], c["step_ts"], c["detail"], trades, pos, marks, rt)
            _with_taken(row, taken)
            row["why"] = why_of(c["kind"], taken, c["detail"])
            if row.get("wallet") is None:
                row["wallet"] = wallet_at(trades, c["step_ts"], initial, inclusive=c["kind"] == "early")
            row["sims"] = int(row.get("sims") or 0) + 1
            row["updated_ts"] = now_ms
            try:
                if c.get("bad"):
                    raise MissedError("페이퍼 봇 기록(outcomes)의 신호를 못 읽음")
                if rig is None:
                    raise MissedError(rig_err)
                if rc is None:
                    raise MissedError(f"규칙봇 1분봉 파일을 못 읽음 ({getattr(src, 'rule_db', '')})")
                sig = LS.signal_of(c["signal"])
                r = LS.simulate_db(rig, sig, rc, c["step_ts"], wallet=row["wallet"])
                _apply(row, r, rig.notes)
            except Exception as exc:  # noqa: BLE001  stored with the row, tried again later
                row["state"] = "error"
                row["error"] = str(exc)[:300] if isinstance(exc, MissedError) else f"{type(exc).__name__}: {exc}"[:300]
                res["errors"] += 1
            _upsert(conn, row)
            res["new" if kind == "new" else "resim"] += 1
            res["closed"] += int(row["state"] == "closed")
    finally:
        if rc is not None:
            rc.close()
    # the trade that had the place, while it is still open (no simulation: a lookup)
    for key, light in _existing(conn, look).items():
        if light["taken_state"] == "closed" or (light["taken_state"] is None and int(light["t"]) < since):
            continue
        row = _full(conn, key)
        taken = taken_of(row["why_kind"], int(row["step_ts"]), _j(row["detail"]), trades, pos, marks, rt)
        if (taken or {}).get("state") != row["taken_state"] or (taken and taken.get("roe") != row["taken_roe"]):
            row = _with_taken(row, taken)
            row["why"] = why_of(row["why_kind"], taken, _j(row["detail"]))
            _upsert(conn, row)
            res["taken"] += 1
    conn.execute("DELETE FROM missed WHERE t < ?", (now_ms - KEEP_DAYS * DAY,))
    res["rows"] = int(conn.execute("SELECT COUNT(*) FROM missed").fetchone()[0])
    _meta_put(conn, now_ms, {"state": "ok", "now": now_ms, "since": since, "config": cfg_src, "rig_error": rig_err,
                             "funding": "excluded", "notes": rig.notes if rig is not None else [],
                             **{k: res[k] for k in ("new", "resim", "closed", "errors", "left", "capped", "taken", "rows")},
                             "elapsed_s": round(time.monotonic() - t0, 3)})


# ====================================================================== reading it back (the CLI and the dashboard)
def row_out(d: dict) -> dict:
    """A stored row as the screen and the CLI use it: numbers, the trade that had the place, hold time, win."""
    data = _j(d.get("data"))
    taken = _j(d.get("taken")) or None
    st = d.get("state")
    entry, exit_ts, last = d.get("entry_ts"), d.get("exit_ts"), d.get("last_ts")
    hold = (int(exit_ts) - int(entry)) if (st == "closed" and entry is not None and exit_ts is not None) else \
        (int(last) + MIN - int(entry)) if (st == "open" and entry is not None and last is not None) else None
    if taken is not None:
        taken["reason_ko"] = KO_EXIT.get(taken.get("reason"), taken.get("reason"))
    return {"key": d.get("key"), "t": d.get("t"), "step_ts": d.get("step_ts"), "member": d.get("member"), "strategy": d.get("strategy"),
            "tf": d.get("tf"), "symbol": d.get("symbol"), "side": d.get("side"), "why_kind": d.get("why_kind"),
            "why_kind_ko": KO_WHY.get(d.get("why_kind"), d.get("why_kind")), "why": d.get("why"), "state": st,
            "state_ko": KO_STATE.get(st, st), "entry_ts": entry, "entry_price": _f(d.get("entry_price")), "stop": _f(d.get("stop")),
            "leverage": d.get("leverage"), "margin": _f(d.get("margin")), "exit_ts": exit_ts, "exit_price": _f(d.get("exit_price")),
            "reason": d.get("reason"), "reason_ko": KO_EXIT.get(d.get("reason"), d.get("reason")), "roe": _f(d.get("roe_net")),
            "pnl": _f(d.get("pnl")), "best_roe": _f(d.get("best_roe")), "last_ts": last, "hold_ms": hold,
            "win": (st == "closed" and (_f(d.get("pnl")) or 0) > 0), "lock": _f(data.get("lock")), "stop_now": _f(data.get("stop_now")),
            "stop_rule": data.get("stop_rule") or "", "note": data.get("why") or "", "error": d.get("error") or "",
            "taken": taken, "updated_ts": d.get("updated_ts"), "sims": d.get("sims")}


def summary_of(rows: list, trades: list, pos_entry: Optional[int], since: int) -> dict:
    """The two blocks of the screen: the paper trades actually taken (entered since ``since``: the closed ones, and the open
    position) and the missed signals (rows of the same span, ``row_out`` shape): counts, wins (pnl > 0, the executor's
    rule) and losses, win rate, the sum and mean of net ROE over the closed ones, small sample under SMALL closed."""
    def block(closed: list, n: int, open_n: int) -> dict:
        roes = [x for x in (_f(r.get("roe")) for r in closed) if x is not None]
        w = sum(1 for r in closed if (_f(r.get("pnl")) or 0) > 0)
        return {"n": n, "closed": len(closed), "wins": w, "losses": len(closed) - w, "open": open_n,
                "win_rate": w / len(closed) if closed else None, "roe_sum": sum(roes) if roes else 0.0,
                "roe_mean": sum(roes) / len(roes) if roes else None, "small": len(closed) < SMALL}
    rs = [r for r in rows if (r.get("t") or 0) >= since]
    m = block([r for r in rs if r["state"] == "closed"], len(rs), sum(1 for r in rs if r["state"] == "open"))
    m.update({k: sum(1 for r in rs if r["state"] == k) for k in ("no_data", "refused", "error")})
    m["moments"] = len({(r["symbol"], r["side"], r["step_ts"]) for r in rs})
    tk = [t for t in trades if (t.get("entry_time") or 0) >= since]
    open_n = 1 if pos_entry is not None and pos_entry >= since else 0
    return {"missed": m, "taken": block(tk, len(tk) + open_n, open_n), "small_n": SMALL}


def result_ko(r: dict) -> str:
    st = r["state"]
    if st == "closed":
        return f"{'✅' if r['win'] else '❌'} {_pct(r['roe'])} {r['reason_ko'] or ''}".strip()
    if st == "open":
        return f"진행 중 {_pct(r['roe'])}"
    if st == "no_data":
        return "1분봉 없음"
    if st == "refused":
        return f"진입 안 됨 ({r['note'] or '엔진이 거절'})"
    return f"못 읽음 ({r['error'] or '이유 없음'})"


def taken_ko(t: Optional[dict]) -> str:
    if not t:
        return "그때 탄 거래: 기록 못 찾음"
    head = f"그때 탄 거래: {coin(t.get('symbol'))} {KO_SIDE.get(t.get('side'), '')}"
    if t.get("state") == "open":
        return f"{head} 진행 중 {_pct(t.get('roe'))}" if t.get("roe") is not None else f"{head} 진행 중"
    return f"{head} {_pct(t.get('roe'))}"


def read_rows(conn, since: int, limit: Optional[int] = None) -> list:
    """The rows of signals from ``since`` on, newest first (``row_out``; the stored signal and path are not read)."""
    q = f"SELECT {', '.join(READ_COLS)} FROM missed WHERE t >= ? ORDER BY t DESC, key" + (" LIMIT ?" if limit else "")
    cur = conn.execute(q, (int(since),) + ((int(limit),) if limit else ()))
    return [row_out(dict(zip(READ_COLS, r))) for r in cur.fetchall()]


def read_path(conn, key: str) -> list:
    """One row's thinned per-minute path ({t, c, roe, stop, lock}, the exit last)."""
    r = conn.execute("SELECT path FROM missed WHERE key = ?", (key,)).fetchone()
    try:
        return json.loads(r[0]) if r and r[0] else []
    except ValueError:
        return []


def show_text(db: str, paper_db: str, now_ms: int, days: Optional[int] = WINDOW_DAYS, limit: int = 30) -> tuple:
    """(exit code, text) of ``show``."""
    from . import livecheck as LC
    conn = LC.open_ro(db)
    if conn is None:
        return 1, f"{db}가 없어요 (1분 감시가 아직 기록 전)"
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "missed" not in tables:
            return 1, "1분 감시가 아직 못 탄 신호를 계산하기 전이에요 (missed 표가 없음)"
        meta = {k: (ts, _j(d)) for k, ts, d in conn.execute("SELECT k, ts, data FROM missed_meta")} if "missed_meta" in tables else {}
        since = window_start(now_ms, days) if days else int((meta.get("first") or (0, {}))[1].get("since") or 0)
        rows = read_rows(conn, since)
    finally:
        conn.close()
    trades, pos_entry, paper_ok = [], None, False
    pc = LC.open_ro(paper_db)
    if pc is not None:
        try:
            p = read_paper(pc, now_ms, trades_since=since)
            trades, pos_entry, paper_ok = p["trades"], (int(p["pos"]["entry_time"]) if p["pos"] else None), True
        except sqlite3.Error:
            paper_ok = False
        finally:
            pc.close()
    s = summary_of(rows, trades, pos_entry, since)
    last = meta.get("pass")
    span = f"최근 {days}일" if days else "기록 전체"
    lines = [f"못 탄 신호 성적 ({span}, 한국 시간 {kst(since)}부터)"
             + (f" · 마지막 계산 {kst(last[0])}" if last else "")]
    tk, ms = s["taken"], s["missed"]

    def block(name: str, b: dict, extra: str = "", unit: str = "개") -> str:
        if not b["n"]:
            return f"{name}: 없음"
        wr = f"{b['win_rate']:.0%}" if b["win_rate"] is not None else "-"
        mean = f" (평균 {_pct(b['roe_mean'])})" if b["roe_mean"] is not None else ""
        return (f"{name}: {b['n']}{unit} · 끝남 {b['closed']} ({b['wins']}승 {b['losses']}패, 승률 {wr}) · 순ROE 합 "
                f"{_pct(b['roe_sum'])}{mean}" + (f" · 진행 중 {b['open']}" if b["open"] else "") + extra
                + (" · 표본 적음(20번 미만)" if b["small"] else ""))
    lines.append(block("실제로 탄 거래", tk, unit="번") if paper_ok else "실제로 탄 거래: 페이퍼 봇 DB를 못 읽음")
    extra = "".join(f" · {KO_STATE[k]} {ms[k]}" for k in ("no_data", "refused", "error") if ms[k])
    lines.append(block("못 탄 신호(가상)", ms, extra) + (f" · 서로 다른 순간 {ms['moments']}번" if ms["n"] else ""))
    if rows:
        lines.append("")
    for r in rows[:limit]:
        lines.append(f"{kst(r['t'])} {coin(r['symbol'])} {KO_SIDE.get(r['side'], '')} {r['strategy']} {KO_TF.get(r['tf'], r['tf'])}"
                     f" · {r['why']} → {result_ko(r)}" + (f" ({_dur(r['hold_ms'])})" if r["hold_ms"] is not None else "")
                     + f" · {taken_ko(r['taken'])}")
    if len(rows) > limit:
        lines.append(f"… 나머지 {len(rows) - limit}개 (--limit)")
    lines += ["", NOTE_KO, _funding_note()]
    return 0, "\n".join(lines)


def _funding_note() -> str:
    from .livesim import FUNDING_NOTE_KO
    return FUNDING_NOTE_KO


def _sources(a):
    from . import livecheck as LC
    try:
        with open(a.combo_config, encoding="utf-8") as fh:
            cc = json.load(fh)
    except (OSError, ValueError):
        cc = {}
    return LC.Sources(db=a.db, paper_db=a.paper_db or cc.get("db") or PAPER_DB, rule_db=a.rule_db or cc.get("paper_db") or RULE_DB,
                      combo_config=a.combo_config)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.livemissed", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--db", default=DEFAULT_DB, help="livecheck.db (the watcher's file: table missed)")
        p.add_argument("--paper-db", default=None, help="the paper bot's database (default: combo.json's db)")
        p.add_argument("--rule-db", default=None, help="paper3.db, the rule bot's 1m bars (default: combo.json's paper_db)")
        p.add_argument("--combo-config", default=COMBO_CONFIG)
    s = sub.add_parser("show", help="the summary (실제로 탄 거래 vs 못 탄 신호) and the newest rows")
    common(s)
    s.add_argument("--days", type=int, default=WINDOW_DAYS, help="KST days (0: everything recorded)")
    s.add_argument("--limit", type=int, default=30)
    r = sub.add_parser("run", help="one pass now (the 1-minute watcher does it every minute)")
    common(r)
    a = ap.parse_args(argv)
    now = int(time.time() * 1000)
    src = _sources(a)
    if a.cmd == "show":
        code, text = show_text(a.db, src.paper_db, now, a.days or None, a.limit)
        print(text)
        return code
    from . import livecheck as LC
    conn = LC.open_out(a.db)
    try:
        out = missed_pass(src, conn, now)
    finally:
        conn.close()
    print(json.dumps(out, ensure_ascii=False))
    return 1 if out.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
