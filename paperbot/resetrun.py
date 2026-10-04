"""The agents' side of the one-time clean restart (deploy/paperbot-reset.sh, owners' decision 2026-10-04).

    python -m paperbot.resetrun plan  --lib /var/lib/paperbot                       (read-only: what would change)
    python -m paperbot.resetrun apply --lib /var/lib/paperbot --archive <run dir>   (backup, then reset)
    python -m paperbot.resetrun start --paper-db /var/lib/paperbot/paper3.db --wait 180   (the new start)

The reset script MOVES the run's own files to /var/lib/paperbot/archive/run-<UTC>/ and keeps everything else. The
agents' memory (agents3.db) and the owners' inbox (inbox.db) are KEPT in place: only the few cursors in agents3.db
that point into the old run's paper3.db are reset here, while every writer is stopped (the agents tick, the monthly
lab re-check and the dashboard are their only writers). ``apply`` first copies both databases into the archive
folder (SQLite backup API), then changes agents3.db in ONE transaction; running it again changes nothing more.

Every persistent state on the server, and what the restart does with it:

    /var/lib/paperbot/...      written by                    bound to the old run?                  restart
    paper3.db (+wal/shm)       live3                         yes: accounts, trades, ids, run start  ARCHIVED
    daily3.db                  daily3 (nightly check)        yes: reports of paper3 days            ARCHIVED
    checkpoint.db              checkpoint                    yes: snapshots / verdicts of the run   ARCHIVED
    checkpoint_bars/           checkpoint (bar cache)        cache for the run's verdicts           ARCHIVED
    rehearsal/ (+bars/)        rehearsal (weekly preview)    yes: previews of the old run           ARCHIVED (new empty dir)
    tradealerts.json           tgtrades                      yes: last paper3 trade id, open pos.   ARCHIVED
    evening-latest.json        evening (v2, paper.db)        v2 output, regenerated                 ARCHIVED
    agents3.db                 agents tick, labmonthly       memory; a few cursors (below)          KEPT, cursors reset
    agents3.db.lock            agents tick (lock file)       no                                     kept
    inbox.db                   dashboard                     no: owners' posts, approvals, alerts   KEPT (backup only)
    price_alerts.json          tgtrades (price alerts)       no: fired / heartbeat of inbox alerts  kept
    liq.db, flow.db, market.db liq / flow / record           no: market recorders                   kept
    paper.db                   v2 live / record              v2 run (not paper v3)                  kept
    ghcoin/                    ghcoin recorder               no: GH Coin calls                      kept
    lab/ (+recent/)            labdata, labmonthly           no: 5-year caches, monthly re-check    kept
    failalert/                 paperbot-failed@              no: one-a-day stamps                   kept
    exec/                      order executor                no (its own records)                   kept
    .claude*, .local, ...      agent CLI login               no                                     kept
    /var/backups/paperbot      backup (14 days), offsite     copies                                 kept
    /etc/paperbot/*.env        owners                        no                                     kept
    /etc/paperbot/extras.json  owners                        acks / accept_code name old values     kept (``plan`` warns)
    /etc/paperbot/executor.json owners                       the paper account it follows           kept (``plan`` warns)

agents3.db, table by table:

    trials, trial_results      the hypothesis / lab ledger: the gate's test count never restarts   kept
    notes, messages, rooms     the rooms' memory and talk (append-only)                            kept (+ one note
                                                                                                    and one line per room)
    rounds, agent_calls        meeting history, AI budget per KST day                              kept
    committee_calls            the daily bull/bear calls, graded on public prices                  kept
    proposals                  awaiting_owner / approved rows belong to the old run (the runner    open ones closed
                               refuses them for good: stale_run, observation period)               ('rejected')
    cursors                    see CURSOR_RULES                                                    run-bound reset

inbox.db (owner_messages, approvals, price_alerts, price_alert_changes): nothing in it points into paper3.db; kept.

Cursors (agents3.db ``cursors``) that point into paper3.db (trade ids, alert rowids, account ids, the run's day
count) are reset exactly as triggers.reconcile_paper_cursors would for a new run, so the first tick of the new run
reads every new trade / alert / bust: ``loss:*``, ``weekly:*``, ``incident:alert_rowid``, ``checkpoint:day`` -> 0;
``bust:*`` deleted; ``paper:fingerprint`` (what the cursors stood on), ``extras:orphans`` (old-run account badge),
``proposals:gate_now`` (open proposals' gate) deleted - the tick writes them again. All other cursors are times, KST
days or inbox ids (owner:*, inbox:*, telegram:*, analysis:*, move:*, tf_split:*, event_review:last,
incident:report_day, flag_*, newlab_*, policy:*, usage_scale, tick:last, ...) and stay.

The restart is recorded in the cursor ``run:restarted`` ({ts, day_kst, archive, old_run_start, history}) and told
to the staff once per room (a note and a system line: "실험을 <day>에 처음부터 다시 시작함 (5분봉 제외, 1분봉 5초 뒤
읽기)"), so they never read the old run's numbers as the new run's.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import urllib.parse
from typing import Any, Optional

from . import checkpoint as CP
from .config import V3_ACCOUNTS, V3_TRADE_TFS
from .agents import extra_accounts as XA
from .agents import rooms_db as R
from .agents import triggers as TR
from .sessions import KST

MARKER = "run:restarted"
CLOSED_BY = "code:run_restart"
GATE_NOW = "proposals:gate_now"            # rooms.GATE_NOW (rooms.py is not imported here; a test checks the name)
# cursor rules: (prefix or exact key, action); "0" = set to 0, None = delete
CURSOR_RULES: tuple = (
    ("loss:", "0"), ("weekly:", "0"),                     # paper3 trade ids (triggers.TRADE_CURSOR_PREFIXES)
    (TR.ALERT_CURSOR, "0"),                               # paper3 alert rowid
    ("checkpoint:day", "0"),                              # day 30 / 60 / ... of the old run
    ("bust:", None),                                      # old-run accounts that went bust
    (TR.PAPER_FP, None),                                  # what the cursors stood on in the old paper3.db
    (XA.ORPHANS, None),                                   # old-run extra accounts for the dashboard badge
    (GATE_NOW, None),                                     # open proposals' gate (rewritten by the next tick)
)
PREFIX_RULES = tuple(r for r in CURSOR_RULES if r[0].endswith(":"))
EXACT_RULES = dict(r for r in CURSOR_RULES if not r[0].endswith(":"))
OPEN_STATUSES = R.ACTIVE_PROPOSAL_STATUSES                # awaiting_owner, approved
BACKUP_NAMES = {"agents3.db": "agents3-before-reset.db", "inbox.db": "inbox-before-reset.db"}
WHAT_CHANGED_KO = "5분봉 제외, 1분봉 5초 뒤 읽기"


def kst_day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=KST).strftime("%Y-%m-%d")


def kst_text(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=KST).strftime("%Y-%m-%d %H:%M")


def restart_text(day: str) -> str:
    return f"실험을 {day}에 처음부터 다시 시작함 ({WHAT_CHANGED_KO})"


def _ro(path: str) -> Optional[sqlite3.Connection]:
    if not os.path.exists(path):
        return None
    return sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro", uri=True, timeout=5)


def _tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# ---------------------------------------------------------------- what changes
def cursor_plan(conn: sqlite3.Connection) -> dict:
    """{key: (old value, new value or None = delete)} for the run-bound cursors whose value would change."""
    if "cursors" not in _tables(conn):
        return {}
    out = {}
    for k, v in conn.execute("SELECT k, v FROM cursors ORDER BY k"):
        if k in EXACT_RULES:
            new = EXACT_RULES[k]
        else:
            rule = next((r for r in PREFIX_RULES if k.startswith(r[0])), None)
            if rule is None:
                continue
            new = rule[1]
        if new != v:
            out[k] = (v, new)
    return out


def open_proposals(conn: sqlite3.Connection) -> list[dict]:
    if "proposals" not in _tables(conn):
        return []
    q = ",".join("?" * len(OPEN_STATUSES))
    rows = conn.execute(f"SELECT id, ts, room_id, strategy, status, change FROM proposals WHERE status IN ({q}) "
                        "ORDER BY id", OPEN_STATUSES).fetchall()
    out = []
    for pid, ts, room, strat, status, change in rows:
        try:
            ch = json.loads(change) if change else {}
        except ValueError:
            ch = {}
        acc = ch.get("account") if isinstance(ch, dict) and isinstance(ch.get("account"), dict) else {}
        out.append({"id": int(pid), "ts": int(ts), "room_id": room, "strategy": strat, "status": status,
                    "kind": ch.get("kind") if isinstance(ch, dict) else None, "timeframe": acc.get("timeframe")})
    return out


def memory_counts(agents: Optional[sqlite3.Connection], inbox: Optional[sqlite3.Connection]) -> dict:
    """Row counts of what is kept (memory), for the summary before and after."""
    out: dict = {}
    for conn, tables in ((agents, ("trials", "trial_results", "notes", "messages", "rounds", "proposals",
                                   "committee_calls", "agent_calls")),
                         (inbox, ("owner_messages", "approvals", "price_alerts", "price_alert_changes"))):
        if conn is None:
            continue
        have = _tables(conn)
        for t in tables:
            if t in have:
                out[t] = int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    if inbox is not None:
        out["price_alerts_live"] = len(R.price_alerts(inbox))
    if agents is not None and "trials" in _tables(agents):
        out["newlab_tests"] = int(agents.execute("SELECT COUNT(*) FROM trials WHERE kind = 'newlab'").fetchone()[0])
    return out


def get_marker(conn: sqlite3.Connection) -> Optional[dict]:
    if "cursors" not in _tables(conn):
        return None
    r = conn.execute("SELECT v FROM cursors WHERE k = ?", (MARKER,)).fetchone()
    if r is None:
        return None
    try:
        v = json.loads(r[0])
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def paper_facts(path: str) -> dict:
    """The run in a paper3.db (read-only): start, original accounts, those on 5m. {} when missing/unreadable."""
    try:
        conn = _ro(path)
    except sqlite3.Error:
        return {}
    if conn is None:
        return {}
    try:
        q = ",".join("?" * len(V3_TRADE_TFS))
        r = conn.execute(f"SELECT MIN(created_ts), COUNT(*), SUM(timeframe NOT IN ({q})) "
                         "FROM accounts WHERE kind IN ('strategy', 'random')", V3_TRADE_TFS).fetchone()
        return {"start": None if r[0] is None else int(r[0]), "originals": int(r[1] or 0), "off_tf": int(r[2] or 0)}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def config_warnings(extras_json: str, executor_json: str) -> list[str]:
    """Owner settings that name values of the old run (never changed here)."""
    out = []
    try:
        with open(extras_json, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        cfg = {}
    except (OSError, ValueError) as exc:
        out.append(f"{extras_json}을 읽지 못함({type(exc).__name__}): 직접 확인")
        cfg = {}
    if isinstance(cfg, dict):
        for k in ("agents_ack", "inbox_ack"):
            if cfg.get(k):
                out.append(f"{extras_json}의 {k}가 이전 실행 값입니다. 새 실행에는 필요 없으니 null로 두면 됩니다")
        if cfg.get("accept_code"):
            out.append(f"{extras_json}의 accept_code는 이전 실행의 계좌 번호입니다. 새 실행에서 같은 번호가 다른 계좌에 "
                       "붙을 수 있으니 {}로 비우세요")
        if cfg.get("observe_until"):
            out.append(f"{extras_json}의 observe_until={cfg['observe_until']}: 관찰 기간은 새 시작+21일과 이 날짜 중 "
                       "늦은 쪽입니다(그대로 둬도 됨)")
        if cfg.get("pause_activation"):
            out.append(f"{extras_json}의 pause_activation=true: 새 계좌 시작이 멈춰 있습니다")
    try:
        with open(executor_json, encoding="utf-8") as fh:
            acct = (json.load(fh) or {}).get("account")
    except (OSError, ValueError, AttributeError):
        acct = None
    if isinstance(acct, str) and acct.rsplit("@", 1)[-1] not in V3_TRADE_TFS:
        out.append(f"{executor_json}의 account={acct}: 새 실행에는 없는 봉입니다(주문 실행기는 켜기 전에 바꾸세요)")
    return out


# ---------------------------------------------------------------- backup
def backup_db(src: str, dst: str) -> str:
    """Copy ``src`` to ``dst`` with the SQLite backup API (a consistent copy, rollback-journal mode, integrity
    checked). 'missing' when there is no src; 'kept' when dst exists already (the first, pre-reset copy wins)."""
    if not os.path.exists(src):
        return "missing"
    if os.path.exists(dst):
        return "kept"
    part = dst + ".part"
    if os.path.exists(part):
        os.remove(part)
    s = sqlite3.connect(src, timeout=10)
    try:
        d = sqlite3.connect(part)
        try:
            s.backup(d)
            d.execute("PRAGMA journal_mode=DELETE")
            ok = d.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise RuntimeError(f"backup of {src} failed its integrity check: {ok}")
            d.commit()
        finally:
            d.close()
    finally:
        s.close()
    os.replace(part, dst)
    return "copied"


# ---------------------------------------------------------------- apply
def apply(agents_path: str, inbox_path: str, archive: str, now_ms: Optional[int] = None,
          old_paper: Optional[str] = None) -> dict:
    """Back up agents3.db and inbox.db into ``archive``, then reset the run-bound state of agents3.db in one
    transaction (cursors, open proposals, the marker, the notes). Idempotent for the same archive."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not os.path.isdir(archive):
        raise FileNotFoundError(f"archive folder {archive} does not exist")
    out: dict = {"backups": {}, "cursors": {}, "closed": [], "rooms_told": 0, "already": False}
    for name, path in (("agents3.db", agents_path), ("inbox.db", inbox_path)):
        out["backups"][name] = backup_db(path, os.path.join(archive, BACKUP_NAMES[name]))
    if not os.path.exists(agents_path):
        out["note"] = "agents3.db가 없음(초기화할 것 없음)"
        return out
    conn = R.open_agents(agents_path)            # the tick's own opener: real schema, WAL, refuses a stale -wal
    try:
        conn.execute("PRAGMA busy_timeout = 3000")
        conn.execute("BEGIN IMMEDIATE")          # fails ('database is locked') if anything else is writing
        day = kst_day(now)
        old = get_marker(conn) or {}
        already = old.get("archive") == archive
        out["already"] = already
        # 1. cursors
        plan = cursor_plan(conn)
        for k, (_, new) in plan.items():
            if new is None:
                conn.execute("DELETE FROM cursors WHERE k = ?", (k,))
            else:
                conn.execute("INSERT INTO cursors (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                             (k, new))
        out["cursors"] = plan
        # 2. open proposals of the old run
        for p in open_proposals(conn):
            R.set_proposal_status(conn, p["id"], "rejected", CLOSED_BY, ts=now, commit=False)
            tf = f" ({p['timeframe']})" if p.get("timeframe") else ""
            R.post(conn, p["room_id"], None, "run_restart", "code", None, "system",
                   f"제안 #{p['id']}{tf}을 닫았습니다: run restarted {day} — {restart_text(day)}. 이전 실행의 계좌와 "
                   "기간을 기준으로 한 제안이라 새 실행에서는 시작하지 않습니다. 시험 기록은 장부에 그대로 있습니다.",
                   {"action": "run_restart_close", "proposal_id": p["id"], "was": p["status"], "day": day},
                   ts=now, commit=False)
            out["closed"].append(p)
        # 3. tell every room once (a note: the packets show the newest notes; a line: the room's history)
        if not already:
            facts = paper_facts(old_paper) if old_paper else {}
            text = (f"{restart_text(day)}. 이 날 전의 회의·메모에 나온 거래·손익·계좌 숫자는 이전 실행(보관됨) 것이고, "
                    f"새 실행은 $5,000 계좌 {V3_ACCOUNTS}개({'·'.join(V3_TRADE_TFS)})로 다시 셈. 시험 장부와 시험 수, 메모, "
                    "채점 기록은 그대로 이어짐.")
            for room, strat in conn.execute("SELECT room_id, strategy FROM rooms ORDER BY room_id").fetchall():
                conn.execute("INSERT INTO notes (ts, room_id, strategy, text, round_id) VALUES (?,?,?,?,NULL)",
                             (now, room, strat, text))
                R.post(conn, room, None, "run_restart", "code", None, "system", text,
                       {"action": "run_restart", "day": day}, ts=now, commit=False)
                out["rooms_told"] += 1
            hist = list(old.get("history") or []) + ([{k: old[k] for k in ("ts", "day_kst", "archive") if k in old}]
                                                     if old else [])
            marker = {"ts": now, "day_kst": day, "archive": archive, "text_ko": restart_text(day),
                      "old_run_start": facts.get("start"), "old_originals": facts.get("originals"),
                      "old_5m_accounts": facts.get("off_tf"), "history": hist}
            conn.execute("INSERT INTO cursors (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                         (MARKER, json.dumps(marker, ensure_ascii=False, sort_keys=True)))
        conn.commit()
        out["marker"] = get_marker(conn)
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return out


# ---------------------------------------------------------------- the new start
def start_info(paper_db: str, wait_s: float = 0.0, poll_s: float = 5.0) -> Optional[dict]:
    """The new run's start (checkpoint.run_facts: MIN(accounts.created_ts)) and its first 30-day checkpoint
    (checkpoint.checkpoint_ts), waiting up to ``wait_s`` for the bot to create its accounts. None if not yet."""
    end = time.time() + wait_s
    while True:
        try:
            conn = CP.ro_connect(paper_db)
            try:
                facts = CP.run_facts(conn)
                n = conn.execute("SELECT timeframe, COUNT(*) FROM accounts WHERE kind IN ('strategy', 'random') "
                                 "GROUP BY timeframe").fetchall()
            finally:
                conn.close()
        except (FileNotFoundError, sqlite3.Error):
            facts, n = {"start_ts": None}, []
        start = facts.get("start_ts")
        if start is not None and n:                       # the original accounts exist (not only a runs row)
            cp = CP.checkpoint_ts(start, 1)
            return {"start": start, "start_kst": kst_text(start), "checkpoint": cp,
                    "checkpoint_kst": kst_text(cp), "checkpoint_day": CP.day_str(cp),
                    "observe_end_kst": kst_text(start + 21 * CP.DAY_MS),
                    "accounts": sum(c for _, c in n), "timeframes": sorted(tf for tf, _ in n)}
        if time.time() >= end:
            return None
        time.sleep(poll_s)


# ---------------------------------------------------------------- CLI
def _drop_to(user: str) -> None:
    """Running as root: become ``user`` (files created later, e.g. -wal/-shm, then belong to the service user)."""
    if not user or os.geteuid() != 0:
        return
    import pwd
    pw = pwd.getpwnam(user)
    os.initgroups(user, pw.pw_gid)
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)


def _lib_ok(path: str, write: bool) -> bool:
    """The folder exists and this user may use it (else a database in it would look 'missing')."""
    mode = os.R_OK | os.X_OK | (os.W_OK if write else 0)
    if os.path.isdir(path) and os.access(path, mode):
        return True
    print(f"!! {path}: 폴더가 없거나 이 사용자(uid {os.geteuid()})가 {'쓸' if write else '읽을'} 수 없음")
    return False


def _print_plan(lib: str, warnings: list) -> int:
    agents_p, inbox_p = os.path.join(lib, "agents3.db"), os.path.join(lib, "inbox.db")
    agents, inbox = R.open_ro(agents_p), R.open_ro(inbox_p)
    bad = [p for p, c in ((agents_p, agents), (inbox_p, inbox)) if c is None and os.path.exists(p)]
    if bad:
        for c in (agents, inbox):
            if c is not None:
                c.close()
        print(f"!! 데이터베이스로 읽을 수 없음: {', '.join(bad)} — 고치기 전에는 재시작하지 않습니다(개발자에게 알리세요)")
        return 1
    try:
        counts = memory_counts(agents, inbox)
        plan = cursor_plan(agents) if agents is not None else {}
        props = open_proposals(agents) if agents is not None else []
        marker = get_marker(agents) if agents is not None else None
    finally:
        for c in (agents, inbox):
            if c is not None:
                c.close()
    facts = paper_facts(os.path.join(lib, "paper3.db"))
    print("[에이전트 기억: 그대로 둠]")
    print(f"  agents3.db {'있음' if agents is not None else '없음'}, inbox.db {'있음' if inbox is not None else '없음'}")
    if counts:
        print("  " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    print("[이전 실행에 묶인 커서: 초기화]")
    if not plan:
        print("  없음")
    for k, (old, new) in plan.items():
        print(f"  {k}: {str(old)[:60]} -> {'(지움)' if new is None else new}")
    print(f"[열린 제안: 닫음('rejected', {CLOSED_BY})] " + (", ".join(
        f"#{p['id']} {p['status']} {p.get('kind') or ''} {p.get('timeframe') or ''}".strip() for p in props) or "없음"))
    if agents is not None:
        print(f"[방마다 메모 1개와 알림 1줄] {restart_text(kst_day(int(time.time() * 1000)))} ...")
    if marker:
        print(f"[이미 기록된 재시작] {marker.get('day_kst')} {marker.get('archive')}")
    if facts:
        print(f"[지금 paper3.db] 시작 {kst_text(facts['start']) if facts.get('start') else '-'} KST, 원래 계좌 "
              f"{facts.get('originals')}개(그중 5분봉 등 규칙 밖 {facts.get('off_tf')}개)")
    for w in warnings:
        print(f"[설정 확인] {w}")
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.resetrun", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply", "start"):
        s = sub.add_parser(name)
        s.add_argument("--user", default="", help="as root: run as this user (the services' user, paperbot)")
        if name in ("plan", "apply"):
            s.add_argument("--lib", default="/var/lib/paperbot")
        if name == "plan":
            s.add_argument("--etc", default="/etc/paperbot")
        if name == "apply":
            s.add_argument("--archive", required=True)
        if name == "start":
            s.add_argument("--paper-db", default="/var/lib/paperbot/paper3.db")
            s.add_argument("--wait", type=float, default=0.0)
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        # /etc/paperbot is read before dropping to the service user (root:paperbot 750)
        warn_cfg = config_warnings(os.path.join(a.etc, "extras.json"), os.path.join(a.etc, "executor.json"))
        _drop_to(a.user)
        if not _lib_ok(a.lib, write=False):
            return 1
        return _print_plan(a.lib, warn_cfg)
    _drop_to(a.user)
    if a.cmd == "apply":
        if not (_lib_ok(a.lib, write=True) and _lib_ok(a.archive, write=True)):
            return 1
        res = apply(os.path.join(a.lib, "agents3.db"), os.path.join(a.lib, "inbox.db"), a.archive,
                    old_paper=os.path.join(a.archive, "paper3.db"))
        for name, st in res["backups"].items():
            print(f"  {name} 백업: {st} -> {os.path.join(a.archive, BACKUP_NAMES[name])}")
        if res.get("note"):
            print(f"  {res['note']}")
        print(f"  초기화한 커서 {len(res['cursors'])}개" + (": " + ", ".join(sorted(res["cursors"]))[:400]
                                                       if res["cursors"] else ""))
        print(f"  닫은 제안 {len(res['closed'])}개" + (": " + ", ".join(f"#{p['id']}" for p in res["closed"])
                                                   if res["closed"] else ""))
        print(f"  방 {res['rooms_told']}곳에 재시작 메모" + (" (이미 기록돼 있어 다시 쓰지 않음)" if res["already"] else ""))
        return 0
    info = start_info(a.paper_db, a.wait)
    if info is None:
        print(f"봇이 아직 새 계좌를 만들지 않았습니다({a.paper_db})")
        return 3
    print(f"새 실행 시작 {info['start_kst']} KST, 원래 계좌 {info['accounts']}개 ({'/'.join(info['timeframes'])})")
    print(f"첫 30일 판정 {info['checkpoint_kst']} KST (UTC {info['checkpoint_day']} 00:00, checkpoint.checkpoint_ts), "
          f"관찰 기간 끝(최소 21일) {info['observe_end_kst']} KST")
    return 0


if __name__ == "__main__":
    sys.exit(main())
