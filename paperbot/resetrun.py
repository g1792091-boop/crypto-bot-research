"""The agents' side of a clean restart (deploy/paperbot-reset.sh; v3 2026-10-04, paper v4 2026-10, owners' decisions).

    python -m paperbot.resetrun plan  --lib /var/lib/paperbot                       (read-only: what would change)
    python -m paperbot.resetrun apply --lib /var/lib/paperbot --archive <run dir>   (backup, then reset)
    python -m paperbot.resetrun start --paper-db /var/lib/paperbot/paper3.db --wait 180   (the new start)
    python -m paperbot.resetrun guard --lib /var/lib/paperbot     (exit 4: the reset already happened, refuse --yes)

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
    dscheck/ (last.*, days/)   dscheck (DeepSeek nightly)    yes: the run's recompute summaries     ARCHIVED (new empty dir)
    dscheck/bars5m.db          dscheck (kline cache)         no: final public 5m klines             kept (moved back)
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
to the staff once per room (a note and a system line: "실험을 <day>에 처음부터 다시 시작함 (paper v4: ...)", the run
shape written from config.V4_GROUPS, never typed in), so they never read the old run's numbers as the new run's.

Paper v4 (docs/paper-v4-rules.md): the run has four groups of original accounts (accounts.ORIGINAL_KINDS: core
"strategy", DeepSeek "ds200", the 5m reel "reel", coin flips "random"); ``paper_facts`` reads a paper3.db per group and
says whether it is the v4 shape (``shape``), and an account on a timeframe its group does not trade is "off_tf"
(a v4 database has none; a 5m strategy account of the run before 2026-10-04 is one). The order executor may only
follow a core account (one of the 36 on 15m / 30m / 1h / 4h): ``executor_problem``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from typing import Any, Optional

from . import checkpoint as CP
from .accounts import GROUP_OF_KIND, ORIGINAL_KINDS
from .config import (DS200_DEFS, DS200_IDS, DS200_TFS, REEL_NAME, REEL_TF, V3_RANDOM_SEEDS, V3_STRATEGIES,
                     V3_TRADE_TFS, V4_ACCOUNTS, V4_FLIP_TFS, V4_GROUP_ACCOUNTS, V4_GROUP_TF_COUNTS, V4_VERSION)
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
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
GROUPS = ("core", "ds200", "reel", "flip")                  # the original groups (accounts.GROUP_OF_KIND values)
GROUP_KO = {"core": "매매법", "ds200": "딥시크", "reel": "릴스 5분 단타", "flip": "동전"}
DS_TFS_OF = {d[0]: d[2] for d in DS200_DEFS}
FLIP_NAMES = tuple(f"RANDOM_{k}" for k in V3_RANDOM_SEEDS)


def _tfs_ko(tfs) -> str:
    return "·".join(TF_KO.get(tf, tf) for tf in tfs)


def what_changed_ko() -> str:
    """The v4 run in one Korean line, every number from config (the run shape), none typed in."""
    full = sum(1 for d in DS200_DEFS if tuple(d[2]) == tuple(DS200_TFS))
    part = [d for d in DS200_DEFS if tuple(d[2]) != tuple(DS200_TFS)]
    ds = f"딥시크 정의 {len(DS200_DEFS)}개({full}개 {_tfs_ko(DS200_TFS)}"
    if part:
        ds += f", {len(part)}개 {_tfs_ko(part[0][2])}"
    flip5 = V4_GROUP_TF_COUNTS["flip"].get(REEL_TF, 0)
    return (f"paper v4: $5,000 계좌 {V4_ACCOUNTS}개 = 매매법 {V3_STRATEGIES}개 × {_tfs_ko(V3_TRADE_TFS)} + "
            f"{ds}, {V4_GROUP_ACCOUNTS['ds200']}계좌) + 릴스 5분 단타 {V4_GROUP_ACCOUNTS['reel']}개({TF_KO[REEL_TF]}봉, "
            f"자기 청산 규칙) + 동전 {V4_GROUP_ACCOUNTS['flip']}개({TF_KO[REEL_TF]}봉 {flip5}개 포함). 매매법 "
            f"{V3_STRATEGIES}개는 {TF_KO[REEL_TF]}봉 없음, {TF_KO[REEL_TF]}봉은 릴스와 그 비교용 동전만. 좋은 자리 50·40배·보통 "
            "30·20배(비중=배수%), 딥시크·릴스는 늘 보통. 1분봉 8초 뒤 읽기")


WHAT_CHANGED_KO = what_changed_ko()


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


def allowed_tf(kind: str, strategy: str, timeframe: str) -> bool:
    """Does the v4 run trade this original account's timeframe (config.V4_GROUPS)? The 36 on 15m / 30m / 1h / 4h,
    each DeepSeek definition on its own timeframes, the reel on 5m only, the coin flips on 5m .. 4h."""
    if kind == "strategy":
        return timeframe in V3_TRADE_TFS
    if kind == "ds200":
        return timeframe in DS_TFS_OF.get(strategy, ())
    if kind == "reel":
        return strategy == REEL_NAME and timeframe == REEL_TF
    if kind == "random":
        return strategy in FLIP_NAMES and timeframe in V4_FLIP_TFS
    return False


def facts_of_rows(rows) -> dict:
    """``paper_facts`` of (strategy, timeframe, kind, created_ts, settings_version) rows of original accounts."""
    groups = {g: 0 for g in GROUPS}
    by = {g: {} for g in GROUPS}
    by_tf: dict = {}
    off = 0
    versions, days, start = set(), set(), None
    for strategy, tf, kind, created, ver in rows:
        g = GROUP_OF_KIND.get(kind)
        if g in groups:
            groups[g] += 1
            by[g][tf] = by[g].get(tf, 0) + 1
        by_tf[tf] = by_tf.get(tf, 0) + 1
        off += not allowed_tf(kind, strategy, tf)
        versions.add(str(ver))
        if created is not None:
            start = int(created) if start is None else min(start, int(created))
            days.add(int(created) // 86_400_000)
    n = sum(groups.values())
    kinds = {g for g, k in groups.items() if k}
    if n and by == {g: dict(V4_GROUP_TF_COUNTS[g]) for g in GROUPS} and versions == {V4_VERSION} and not off:
        shape = "v4"
    elif n and kinds <= {"core", "flip"} and V4_VERSION not in versions:
        shape = "v3"                                     # only the 36 and the coin flips, made by a v3 runner
    else:
        shape = "other" if n else None
    return {"start": start, "originals": n, "off_tf": off, "groups": groups, "by_tf": by_tf, "by_group_tf": by,
            "versions": sorted(versions), "utc_days": len(days), "shape": shape}


def original_rows(conn: sqlite3.Connection) -> list:
    """(strategy, timeframe, kind, created_ts, settings_version) of the original accounts (a column a database lacks
    reads as NULL: the repeat guard must still see the run's start in a hand-made or older accounts table)."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(accounts)")}
    cols = ", ".join(c if c in have else "NULL" for c in ("strategy", "timeframe", "kind", "created_ts",
                                                           "settings_version"))
    q = ",".join("?" * len(ORIGINAL_KINDS))
    return conn.execute(f"SELECT {cols} FROM accounts WHERE kind IN ({q})", ORIGINAL_KINDS).fetchall()


def paper_facts(path: str) -> dict:
    """The run in a paper3.db (read-only): start, original accounts per group and per timeframe, those on a timeframe
    their group does not trade in v4 ("off_tf"), the settings versions, how many UTC days the accounts were made on
    and the run's shape ("v4", "v3" or "other"). {} when missing/unreadable."""
    try:
        conn = _ro(path)
    except sqlite3.Error:
        return {}
    if conn is None:
        return {}
    try:
        return facts_of_rows(original_rows(conn))
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def groups_text(groups: dict) -> str:
    """'매매법 n · 딥시크 n · 릴스 5분 단타 n · 동전 n' (groups with accounts only)."""
    return " · ".join(f"{GROUP_KO[g]} {groups[g]}" for g in GROUPS if groups.get(g))


def executor_problem(acct: str) -> str:
    """'' when the order executor may follow ``acct`` (a core account: one of the 36 on a core timeframe), else why
    not in Korean. Names only (no database): the executor's paper account must never be a DeepSeek, reel, coin-flip
    or extra account (they never went through the live-safety review)."""
    name, _, tf = acct.rpartition("@")
    if "~c" in tf or "~c" in name or re.match(r"^NL[0-9]+$", name or ""):
        return "추가 계좌(복제·새 매매법)"
    if name in DS200_IDS:
        return "딥시크 계좌"
    if name == REEL_NAME:
        return "릴스 5분 단타 계좌"
    if name.startswith("RANDOM_"):
        return "동전 계좌"
    if not name or tf not in V3_TRADE_TFS:
        return f"새 실행의 매매법 계좌에 없는 봉({tf or '?'})"
    return ""


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
    why = executor_problem(acct) if isinstance(acct, str) else ""
    if why:
        out.append(f"{executor_json}의 account={acct}: {why}입니다. 주문 실행기는 매매법 {V3_STRATEGIES}개의 "
                   f"{'·'.join(V3_TRADE_TFS)} 계좌만 따라 합니다(켜기 전에 바꾸세요)")
    return out


# ---------------------------------------------------------------- already reset?
REPEAT_MS = 24 * 3_600_000      # a run younger than this, made right after a restart marker, is the reset's new run


def repeat_reason(paper_path: str, agents_path: str, now_ms: Optional[int] = None) -> Optional[str]:
    """Korean text when the reset has already been done: the current paper3.db's run started less than 24 h ago and
    agents3.db holds a ``run:restarted`` marker written at most 24 h before that start (or after it), so that run is
    the reset's NEW run and another --yes would archive it. None otherwise (the old run, no marker, no paper3.db)."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    start = paper_facts(paper_path).get("start")
    if start is None or now - start >= REPEAT_MS:
        return None
    conn = R.open_ro(agents_path)
    if conn is None:
        return None
    try:
        marker = get_marker(conn) or {}
    finally:
        conn.close()
    ts = marker.get("ts")
    if not isinstance(ts, (int, float)) or ts < start - REPEAT_MS:
        return None
    return (f"!! 재시작은 이미 끝났습니다. 지금 paper3.db의 실행은 {kst_text(start)} KST에 시작했고(24시간 안), 바로 전 "
            f"{kst_text(int(ts))} KST에 재시작 기록(run:restarted, 보관 폴더 {marker.get('archive') or '?'})이 있습니다. "
            "여기서 --yes를 또 하면 방금 시작한 새 실행을 보관 폴더로 옮기고 처음부터 다시 시작하므로 거절합니다. "
            "봇이 잘 도는지는 launchcheck --stage after로 봅니다. 정말 한 번 더 처음부터 시작해야 할 때만(개발자와 상의한 뒤): "
            "sudo bash deploy/paperbot-reset.sh --yes --force-again")


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
            text = (f"{restart_text(day)}. 이 날 전의 회의·메모에 나온 거래·손익·계좌 숫자는 이전 실행(30일 판정 없이 "
                    "보관됨) 것이고, 새 실행은 처음부터 다시 셈. 그룹(매매법·딥시크·릴스 5분 단타·동전)은 따로 세고, 매매법 "
                    f"{V3_STRATEGIES}개의 순위·판정에 다른 그룹을 섞지 않음. 시험 장부와 시험 수, 메모, 채점 기록은 그대로 이어짐.")
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
                      "old_5m_accounts": (facts.get("by_tf") or {}).get("5m", 0) if facts else None,
                      "old_groups": facts.get("groups"), "old_shape": facts.get("shape"),
                      "new_run": V4_VERSION, "new_accounts": V4_ACCOUNTS, "history": hist}
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
                rows = original_rows(conn)
            finally:
                conn.close()
        except (FileNotFoundError, sqlite3.Error):
            facts, rows = {"start_ts": None}, []
        mine = facts_of_rows(rows)
        # the start: checkpoint.run_facts (the verdict's own rule), else the earliest original account
        start = facts.get("start_ts") if facts.get("start_ts") is not None else mine["start"]
        if start is not None and rows:                    # the original accounts exist (not only a runs row)
            cp = CP.checkpoint_ts(start, 1)
            return {"start": start, "start_kst": kst_text(start), "checkpoint": cp,
                    "checkpoint_kst": kst_text(cp), "checkpoint_day": CP.day_str(cp),
                    "observe_end_kst": kst_text(start + 21 * CP.DAY_MS),
                    "accounts": mine["originals"], "timeframes": sorted(mine["by_tf"]),
                    "groups": mine["groups"], "shape": mine["shape"], "utc_days": mine["utc_days"]}
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
        shape = {"v4": "v4 실행", "v3": "v3 실행(이번에 보관할 것)"}.get(facts.get("shape"), "모양이 규칙과 다름")
        print(f"[지금 paper3.db] 시작 {kst_text(facts['start']) if facts.get('start') else '-'} KST, 원래 계좌 "
              f"{facts.get('originals')}개({groups_text(facts.get('groups') or {}) or '-'}; v4 규칙 밖 봉 "
              f"{facts.get('off_tf')}개), {shape}")
    print(f"[새 실행] {WHAT_CHANGED_KO}")
    for w in warnings:
        print(f"[설정 확인] {w}")
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.resetrun", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply", "start", "guard"):
        s = sub.add_parser(name)
        s.add_argument("--user", default="", help="as root: run as this user (the services' user, paperbot)")
        if name in ("plan", "apply", "guard"):
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
    if a.cmd == "guard":
        if not _lib_ok(a.lib, write=False):
            return 1
        why = repeat_reason(os.path.join(a.lib, "paper3.db"), os.path.join(a.lib, "agents3.db"))
        if why:
            print(why)
            return 4
        return 0
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
    print(f"새 실행 시작 {info['start_kst']} KST, 원래 계좌 {info['accounts']}개 ({'/'.join(info['timeframes'])}; "
          f"{groups_text(info.get('groups') or {})})")
    if info.get("accounts") != V4_ACCOUNTS or info.get("shape") != "v4":
        print(f"!! 계좌가 아직 규칙의 {V4_ACCOUNTS}개({groups_text(V4_GROUP_ACCOUNTS)})와 다릅니다: 1~2분 뒤 다시 보고, 그래도 "
              "같으면 launchcheck --stage after를 돌려 개발자에게 보내세요")
    if (info.get("utc_days") or 0) > 1:
        print("!! 계좌를 만든 UTC 날짜가 둘 이상입니다(일부 계좌의 30일 판정이 밀림): 개발자에게 알리세요")
    print(f"첫 30일 판정 {info['checkpoint_kst']} KST (UTC {info['checkpoint_day']} 00:00, checkpoint.checkpoint_ts), "
          f"관찰 기간 끝(최소 21일) {info['observe_end_kst']} KST")
    return 0


if __name__ == "__main__":
    sys.exit(main())
