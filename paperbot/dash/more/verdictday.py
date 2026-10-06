"""판정 날 시계와 판정 기계 (review 10/06: fix 1 "판정 날 아침 09:00부터 결과 대신 '2번째 판정 · 30일 남음'", change 13
"'D-29'와 'D+0 / 30'이 나란히", additions 2 "판정 결과가 나온 뒤" and 13 "'판정 기계 준비됐나' 카드와 30일 길의 이정표").
Read-only: checkpoint.db (the checkpoint job's, through its own tables), paper3.db (the runner's ``day:<date>`` state),
rehearsal/*.json (paperbot/checkpoint_preview.py), systemd (more/jobs.py) and agents3.db (the lead's checkpoint meeting).

The verdict-day clock (``clock``)
    A checkpoint is 00:00 UTC (09:00 KST) of day 30, 60, ... (paperbot.checkpoint.checkpoint_ts), but its verdict is
    computed by the hourly job (deploy/paperbot-checkpoint.timer, :35 UTC) and takes a while (10,000 coin-flip bots per
    judged account). The countdown therefore points at the first checkpoint whose verdict is NOT stored in checkpoint.db
    yet: until the job has written it, a checkpoint that has passed stays the one shown, ``due`` (never "2번째 판정 ·
    30일 남음" on the morning of the first verdict). ``state`` says where that checkpoint is:

        before         not reached yet (the countdown)
        waiting_job    reached; the job has not left a line for it yet (its first run is HH:35 UTC; ``late`` after
                       ``LATE_MS``: neither the 09:35 run nor its retry left anything)
        waiting_state  the job ran but the runner had not saved its ``day:<date>`` state (job_log "판정 대기")
        computing      the job froze the snapshot (checkpoint.db snapshots) and is comparing with the coin flips
        failed         the job logged an error for that date (job_log "판정 오류"; it retries every hour at :35)
        unknown        checkpoint.db could not be read: never shown as "no verdict"
        ended          past day 180 (checkpoint.NO_VERDICT_DAYS): no more verdicts

    ``last`` is the newest checkpoint whose verdict is stored. The same clock feeds /api/summary (next_checkpoint,
    verdict_clock, restart), the 자는 동안 sheet (more/since.py), the story (more/story.py), the race (more/flow.py) and
    졸업 길 (more/gradpath.py), so every place shows the same day.

    One sentence everywhere (``line_ko``): "30일 중 N일 지남 · 판정까지 M일 (11/04 09:00)" with N = D+n (whole days since
    00:00 UTC of the start day, the top chip's number) and M = the checkpoint's day - N, so N + M is always the period.

    GET /api/v4/verdictday         the clock, the 판정 기계 card (rehearsals ran / failed, the verdict job's timer, the
                                   projected runtime), the road's milestones, the lead's checkpoint meeting (cached 30 s)
    GET /api/v4/verdictday/after   after a verdict: the real-trading checklist of each account that passed (agents/
                                   readiness.evaluate; DeepSeek never per account), background + cached

Rehearsal result numbers (counts by status, warnings) are never passed on: only whether it ran.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import glob
import json
import os
import sqlite3
import subprocess
import threading
import time
import urllib.parse
from typing import Callable, Optional

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
MIN_MS = 60_000
KST_MS = 9 * HOUR_MS
JOB_MINUTE = 35                     # deploy/paperbot-checkpoint.timer: hourly at :35 UTC (09:35 KST on the day)
LATE_MS = 100 * MIN_MS              # due this long with no line from the job: its 09:35 run and the 10:35 retry left nothing
LEDGER_TIMEOUT_S = 2.0
TTL_S = 30.0
JOBS_TTL_S = 60.0
AFTER_TTL_S = 300
REHEARSALS = 6                      # rehearsal summaries looked at (the job keeps 4)
REHEARSAL_UTC = (2, 3, 30)          # deploy/paperbot-rehearsal.timer: Wednesdays 03:30 UTC (12:30 KST)
CHECK_IDS = ("trades200", "regimes2", "neighbour_tf", "cost_ratio", "testnet")
CHECK_KO = {"trades200": "거래 200건", "regimes2": "국면 2개에서 플러스", "neighbour_tf": "옆 봉도 같은 방향",
            "cost_ratio": "실제 비용 ≤ 가정의 1.5배", "testnet": "테스트넷 연습"}
STATE_KO = {"waiting_job": "09:35에 계산 시작", "waiting_state": "봇의 09:00 상태 저장을 기다리는 중",
            "computing": "동전 봇 비교 계산 중", "failed": "계산 중 오류 · 매시 35분에 다시 시도",
            "unknown": "판정 기록을 읽지 못함"}


# ---------------------------------------------------------------- checkpoint.db, read-only
_LEDGERS: dict = {}
_LEDGER_LOCK = threading.Lock()


def _sig(path: str) -> tuple:
    out = []
    for p in (path, path + "-wal"):
        try:
            s = os.stat(p)
            out.append((s.st_mtime_ns, s.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def _log_kind(text: str) -> str:
    if text == "sent":
        return "sent"
    head = text.split("\n", 1)[0]
    if "판정 오류" in head:
        return "error"
    if "판정 대기" in head:
        return "wait"
    return "other"


def _read_ledger(path: str) -> dict:
    out: dict = {"db": "ok", "error": None, "verdicts": {}, "snapshots": {}, "log": {}}
    try:
        c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro", uri=True,
                            timeout=LEDGER_TIMEOUT_S)
    except sqlite3.Error as exc:
        return {**out, "db": "error", "error": type(exc).__name__}
    try:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "verdicts" in names:
            out["verdicts"] = {str(d): int(ts) for d, ts in c.execute("SELECT date, ts FROM verdicts")}
        if "snapshots" in names:
            out["snapshots"] = {str(d): int(ts) for d, ts in c.execute("SELECT date, created_ts FROM snapshots")}
        if "job_log" in names:
            for ts, d, text in c.execute("SELECT ts, date, text FROM job_log ORDER BY rowid DESC LIMIT 200"):
                text = str(text or "")
                row = {"ts": int(ts), "kind": _log_kind(text)}
                if row["kind"] == "error":
                    row["error_kind"] = next((ln[3:].strip()[:60] for ln in text.split("\n") if ln.startswith("오류:")), "")
                out["log"].setdefault(str(d), []).append(row)
    except sqlite3.Error as exc:
        return {**out, "db": "error", "error": type(exc).__name__}
    finally:
        c.close()
    return out


def read_ledger(path: Optional[str]) -> dict:
    """What checkpoint.db says about each checkpoint date: {"db": "ok" | "missing" | "error" | "unknown", "verdicts":
    {date: stored ms}, "snapshots": {date: frozen ms}, "log": {date: [{"ts", "kind": sent | error | wait | other}]}}.
    Cached on the file's (and its WAL's) modification time and size, so a page asking every minute costs a stat."""
    if not path:
        return {"db": "unknown", "error": None, "verdicts": {}, "snapshots": {}, "log": {}}
    if not os.path.exists(path):
        return {"db": "missing", "error": None, "verdicts": {}, "snapshots": {}, "log": {}}
    sig = _sig(path)
    with _LEDGER_LOCK:
        hit = _LEDGERS.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    led = _read_ledger(path)
    if led["db"] == "ok":
        with _LEDGER_LOCK:
            if len(_LEDGERS) > 16:
                _LEDGERS.clear()
            _LEDGERS[path] = (sig, led)
    return led


def day_state_reader(paper_db: Optional[str]) -> Callable[[str], Optional[int]]:
    """date -> when the runner saved its ``day:<date>`` state in paper3.db (the snapshot the verdict reads), or None."""
    def read(date: str) -> Optional[int]:
        if not paper_db or not os.path.exists(paper_db):
            return None
        try:
            c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(paper_db))}?mode=ro", uri=True, timeout=2)
        except sqlite3.Error:
            return None
        try:
            r = c.execute("SELECT ts FROM state WHERE k = ?", ("day:" + date,)).fetchone()
            return int(r[0]) if r and r[0] is not None else None
        except sqlite3.Error:
            return None
        finally:
            c.close()
    return read


# ---------------------------------------------------------------- the clock
def _mmdd(ms: int) -> str:
    return time.strftime("%m/%d", time.gmtime((int(ms) + KST_MS) / 1000))


def _hm(ms: int) -> str:
    return time.strftime("%H:%M", time.gmtime((int(ms) + KST_MS) / 1000))


def day_n(start: int, now: int) -> int:
    """D+n: whole days since 00:00 UTC of the start day (the checkpoint clock; the top chip's number)."""
    return max(0, (int(now) - (int(start) - int(start) % DAY_MS)) // DAY_MS)


def clock(start: Optional[int], now: int, ledger: Optional[dict] = None,
          day_state: Optional[Callable[[str], Optional[int]]] = None) -> dict:
    """The checkpoint the countdown points at, and where it is (see the module docstring). ``ledger``: read_ledger();
    None = not known (a due checkpoint then reads 'unknown', never 'no verdict' and never the next one)."""
    from ...checkpoint import NO_VERDICT_DAYS, PERIOD_DAYS, checkpoint_ts, day_str
    if start is None:
        return {"ready": False}
    led = ledger if ledger is not None else {"db": "unknown", "verdicts": {}, "snapshots": {}, "log": {}}
    verdicts = led.get("verdicts") or {}
    n = day_n(start, now)
    k, last = 1, None
    while True:
        cp = checkpoint_ts(int(start), k)
        date = day_str(cp)
        if k * PERIOD_DAYS > NO_VERDICT_DAYS or cp > now or date not in verdicts:
            break
        last = {"k": k, "day": k * PERIOD_DAYS, "date": date, "ts": cp, "stored_ts": int(verdicts[date])}
        k += 1
    out: dict = {"ready": True, "now": int(now), "start": int(start), "n": n, "k": k, "day": k * PERIOD_DAYS,
                 "of": k * PERIOD_DAYS, "ts": cp, "date": date, "mmdd": _mmdd(cp), "due": False, "state": "before",
                 "late": False, "db": led.get("db"), "last": last, "job_ts": cp + JOB_MINUTE * MIN_MS}
    if k * PERIOD_DAYS > NO_VERDICT_DAYS:
        out.update(state="ended", ts=None, date=None, mmdd=None, job_ts=None, left=None)
    elif cp > now:
        out["left"] = k * PERIOD_DAYS - n
    else:
        out["due"] = True
        out["left"] = 0
        logs = (led.get("log") or {}).get(date) or []
        err = next((x for x in logs if x.get("kind") == "error"), None)
        wait = next((x for x in logs if x.get("kind") == "wait"), None)
        snap = (led.get("snapshots") or {}).get(date)
        saved = day_state(date) if day_state else None
        out.update(saved_ts=saved, snapshot_ts=snap, error_ts=err["ts"] if err else None,
                   error_kind=(err or {}).get("error_kind") or None, wait_ts=wait["ts"] if wait else None)
        if led.get("db") in ("error", "unknown"):
            out["state"] = "unknown"
        elif err:
            out["state"] = "failed"
        elif snap:
            out["state"] = "computing"
        elif wait:
            out["state"] = "waiting_state"
        else:
            out["state"] = "waiting_job"
            out["late"] = now - cp > LATE_MS
        nxt = now - now % HOUR_MS + JOB_MINUTE * MIN_MS
        out["next_try_ts"] = nxt if nxt > now else nxt + HOUR_MS
    out.update(texts(out))
    return out


def texts(c: dict) -> dict:
    """line_ko (the one sentence of every screen) = passed_ko + " · " + rest_ko, state_ko and the top chip's two parts
    (chip_ko), from a clock."""
    if not c.get("ready"):
        return {"line_ko": "봇이 아직 첫 계좌를 만들지 않았습니다", "passed_ko": "봇 시작 전", "rest_ko": "", "state_ko": "",
                "chip_ko": {"main": "봇 시작 전", "opt": ""}}
    n, k, of = c["n"], c["k"], c["of"]
    kth = "" if k == 1 else f"{k}번째 "
    if c["state"] == "ended":
        passed, rest, sko, chip = f"{n}일 지남", "판정 끝 (180일)", "판정 끝", {"main": f"{n}일 지남", "opt": " · 판정 끝"}
    elif not c["due"]:
        passed, sko = f"{of}일 중 {n}일 지남", ""
        if c["ts"] - c["now"] <= DAY_MS:          # the last day: '오늘 09:00' / '내일 09:00', never '1일' for a minute
            word = "오늘" if (c["now"] + KST_MS) // DAY_MS == (c["ts"] + KST_MS) // DAY_MS else "내일"
            rest = f"{kth}판정 {word} 09:00 ({c['mmdd']})"
        else:
            rest = f"{kth}판정까지 {c['left']}일 ({c['mmdd']} 09:00)"
        chip = {"main": f"{n}/{of}일", "opt": f" · {kth}판정 {c['mmdd']}"}
    else:
        st = c["state"]
        sko = STATE_KO.get(st, "")
        if st == "waiting_job" and c.get("late"):
            sko = "판정 작업이 아직 돌지 않았습니다"
        elif st == "waiting_job" and c["now"] >= (c.get("job_ts") or 0):
            sko = "곧 계산 시작 (매시 35분)"
        passed, rest = f"{c['day']}일 판정 날", sko
        chip = {"main": "판정 날", "opt": " · 결과 계산 중" if st in ("waiting_job", "waiting_state", "computing")
                and not c.get("late") else " · 확인 필요"}
    return {"line_ko": f"{passed} · {rest}", "passed_ko": passed, "rest_ko": rest, "state_ko": sko, "chip_ko": chip}


# ---------------------------------------------------------------- the road's milestones
def _dst_end(year: int) -> int:
    """US daylight saving time ends: the first Sunday of November, 06:00 UTC (checkpoint.et_offset_minutes)."""
    from ...checkpoint import _nth_sunday
    return _nth_sunday(year, 11, 1) * DAY_MS + 6 * HOUR_MS


def milestones(c: dict, rehearsals: Optional[list] = None) -> list:
    """The 30-day road's extra marks of the season the clock is in: [{ts, kind, ko}] with kind rehearsal (Wednesdays
    12:30 KST, skipped on a checkpoint day; a past one says whether it ran), dst (US daylight saving time ends), verdict
    (09:00 snapshot · 09:35 job · the lead's meeting after the result), next (the next checkpoint: 2nd checks)."""
    if not c.get("ready") or c.get("state") == "ended" or not c.get("ts"):
        return []
    from ...checkpoint import PERIOD_DAYS, REHEARSAL_BOTS, checkpoint_ts, day_str
    k, cp = c["k"], c["ts"]
    # this season and the one before (the road still shows the last season on its own verdict day)
    lo = checkpoint_ts(c["start"], k - 2) if k > 2 else c["start"] - c["start"] % DAY_MS
    out = []
    ran = {}
    cp_days = {day_str(checkpoint_ts(c["start"], j)) for j in range(max(1, k - 1), k + 1)}
    for r in rehearsals or []:
        if r.get("ts"):
            ran[day_str(r["ts"])] = r
    wd, hh, mm = REHEARSAL_UTC
    t = lo - lo % DAY_MS + hh * HOUR_MS + mm * MIN_MS
    while t <= cp + DAY_MS:
        if dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).weekday() == wd and t >= lo:
            d = day_str(t)
            r = ran.get(d)
            if d in cp_days:
                ko = "판정 연습 없음 (판정 날이라 건너뜀)"
            elif r and r.get("status") == "ok":
                ko = "판정 연습 12:30 · 정상 끝남"
            elif r and r.get("status") == "failed":
                ko = "판정 연습 12:30 · 실패"
            elif t > c["now"]:
                ko = f"판정 연습 12:30 (동전 봇 {REHEARSAL_BOTS:,}개, 진짜 판정 아님)"
            else:
                ko = "판정 연습 12:30 · 기록 없음"
            out.append({"ts": t, "kind": "rehearsal", "ko": ko, "state": (r or {}).get("status"), "skip": d in cp_days})
        t += DAY_MS
    for y in {dt.datetime.fromtimestamp(lo / 1000, dt.timezone.utc).year,
              dt.datetime.fromtimestamp(cp / 1000, dt.timezone.utc).year}:
        e = _dst_end(y)
        if lo <= e <= cp:
            out.append({"ts": e, "kind": "dst", "ko": "미국 서머타임 끝 · 미국 시각 기준 세션 매매법 5개의 신호가 한국 시각으로 "
                                                    "1시간 늦게 남 (고장 아님)"})
    last = c.get("last")
    if last and last.get("k") == k - 1:
        out.append({"ts": last["ts"], "kind": "verdict", "done": True,
                    "ko": f"{last['day']}일 판정 · 결과 저장 {_hm(last['stored_ts'])} · 총괄 판정 회의는 결과가 나온 뒤"})
    out.append({"ts": cp, "kind": "verdict", "ko": f"{k * PERIOD_DAYS}일 판정 · 09:00 모든 계좌 상태 저장 · 09:35 동전 봇 비교 "
                                                 f"계산 시작 · 총괄 판정 회의 (결과가 나온 뒤)"})
    nxt = checkpoint_ts(c["start"], k + 1)
    out.append({"ts": nxt, "kind": "next", "ko": f"다음 판정 {_mmdd(nxt)} 09:00 · 1차 합격 계좌의 2차 확인 · 보류 계좌 다시"})
    return sorted(out, key=lambda x: x["ts"])


# ---------------------------------------------------------------- the verdict machine (rehearsals, the job's timer)
def _utc_ms(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(dt.datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    except ValueError:
        return None


def rehearsals(folder: Optional[str]) -> dict:
    """The weekly rehearsal's own summaries (checkpoint_preview: rehearsal-<time>.json, latest.json): for each, only
    whether it ran (ok / failed / skipped), when, and how long; never its counts. {"state": "ok" | "missing" | "error"}."""
    if not folder or not os.path.isdir(folder):
        return {"state": "missing", "runs": []}
    runs = []
    try:
        files = sorted(glob.glob(os.path.join(folder, "rehearsal-*.json")))[-REHEARSALS:]
    except OSError:
        return {"state": "error", "runs": []}
    for p in files:
        try:
            with open(p, encoding="utf-8") as fh:
                s = json.load(fh)
        except (OSError, ValueError):
            runs.append({"status": "unreadable", "ts": None})
            continue
        if not isinstance(s, dict):
            continue
        st = s.get("status") if s.get("status") in ("ok", "failed", "skipped") else "unknown"
        err = str(s.get("error") or "")
        runs.append({"status": st, "ts": _utc_ms(s.get("started_utc")), "end_ts": _utc_ms(s.get("finished_utc")),
                     "runtime_s": s.get("runtime_s") if isinstance(s.get("runtime_s"), (int, float)) else None,
                     "projected_real_s": s.get("projected_runtime_s_real")
                     if isinstance(s.get("projected_runtime_s_real"), (int, float)) else None,
                     "error_kind": err.split(":", 1)[0][:60] if st == "failed" and err else None})
    runs.sort(key=lambda r: r.get("ts") or 0)
    return {"state": "ok", "runs": runs}


_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


def timers(runner=None) -> dict:
    """paperbot-checkpoint and paperbot-rehearsal from systemd (more/jobs.py; its own 60 s cache here)."""
    from . import jobs as J
    hit = _JOBS.get("v")
    if hit and time.time() - hit[0] < JOBS_TTL_S:
        return hit[1]
    with _JOBS_LOCK:
        hit = _JOBS.get("v")
        if hit and time.time() - hit[0] < JOBS_TTL_S:
            return hit[1]
        v = J.jobs(runner or subprocess.run, units=("paperbot-checkpoint", "paperbot-rehearsal"))
        _JOBS["v"] = (time.time(), v)
    return v


def machine(rh: dict, jb: dict, c: dict) -> dict:
    """'판정 기계 준비됐나': the last rehearsal (ran / failed / skipped, when, minutes), the verdict job's timer and the
    rehearsal timer (on / off / missing, last run and result), the real verdict's projected runtime (rehearsal x 5)."""
    runs = [r for r in rh.get("runs") or [] if r.get("status") in ("ok", "failed", "skipped")]
    last = runs[-1] if runs else None
    last_run = next((r for r in reversed(runs) if r.get("status") in ("ok", "failed")), None)
    proj = next((r.get("projected_real_s") for r in reversed(runs) if r.get("projected_real_s")), None)
    from ...checkpoint import N_BOTS, REHEARSAL_BOTS
    js = (jb or {}).get("jobs") or {}
    out = {"n_bots": N_BOTS, "rehearsal_bots": REHEARSAL_BOTS,
           "rehearsal": {"state": rh.get("state"), "last": last, "last_run": last_run,
                         "ok": sum(1 for r in runs if r["status"] == "ok"),
                         "failed": sum(1 for r in runs if r["status"] == "failed"), "n": len(runs)},
           "systemd": bool((jb or {}).get("available")), "systemd_reason": (jb or {}).get("reason"),
           "job": js.get("paperbot-checkpoint"), "rehearsal_timer": js.get("paperbot-rehearsal"),
           "projected_s": proj}
    job = out["job"] or {}
    if out["systemd"] and job.get("state") != "on":
        level = "bad"
    elif last_run and last_run["status"] == "failed":
        level = "warn"                          # the rehearsal's own file says so, systemd or not
    elif not out["systemd"]:
        level = "unknown"
    elif job.get("ok") is False and not (c.get("due") and job.get("running")):
        level = "warn"
    else:
        level = "ok" if last_run and last_run["status"] == "ok" else "warn"
    out["level"] = level
    return out


# ---------------------------------------------------------------- after the verdict
def lead_meeting(agents: Optional[sqlite3.Connection], since: Optional[int]) -> Optional[dict]:
    """The lead's checkpoint meeting (team:lead, trigger 'checkpoint', agents/triggers: it waits for the stored verdict)
    started at or after ``since``: status, times, the lead's first summary line. None when there is none yet."""
    if agents is None or since is None:
        return None
    try:
        r = agents.execute("SELECT round_id, room_id, started_ts, ended_ts, status, decision FROM rounds WHERE "
                           "trigger = 'checkpoint' AND started_ts >= ? ORDER BY started_ts DESC, round_id DESC LIMIT 1",
                           (int(since),)).fetchone()
        if r is None:
            return None
        from .brief import _summaries
        from .story import _loads, _strip
        lines, dis = (_summaries(agents, [tuple(r) + (None,)]).get(r[0]) or ([], ""))
        d = _loads(r[5]) or {}
        d = d if isinstance(d, dict) else {}
    except sqlite3.Error:
        return {"error": "agents3.db를 읽지 못함"}
    return {"round_id": int(r[0]), "room_id": r[1], "started_ts": r[2], "ended_ts": r[3], "status": r[4],
            "line": (lines[0] if lines else "") or _strip(d.get("summary_ko")) or "", "lead_n": len(lines),
            "dis": dis or ""}


def checklist(paper_db: str, checkpoint_db: Optional[str], now: int) -> dict:
    """The real-trading conditions (agents/readiness.evaluate, the same as 분석 › 실전 준비도) of every account the
    newest verdict passed (1차 합격 / 2차 통과): 충족 / 아직 / 모름 per condition. DeepSeek accounts are never listed one by
    one (owners' D10 / D11): their count only."""
    from ...agents import readiness as RD
    from ...checkpoint import PASS1, PASS2, dashboard_view
    view = dashboard_view(checkpoint_db) if checkpoint_db and os.path.exists(checkpoint_db) else {"ready": False}
    if not view.get("ready"):
        return {"ready": False}
    rows = [r for r in view.get("rows") or [] if r.get("status") in (PASS1, PASS2)]
    ds = [r for r in rows if r.get("group") == "ds200" or r.get("family") == "ds200"]
    mine = [r for r in rows if r not in ds]
    out = {"ready": True, "date": view.get("date"), "ds_passed": len(ds), "accounts": [], "order": list(CHECK_IDS),
           "labels": dict(CHECK_KO)}
    if not mine:
        return out
    try:
        c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(paper_db))}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        return {**out, "error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    try:
        full = RD.evaluate(c, now, view, kinds=("strategy", "reel"))
    finally:
        c.close()
    if full.get("error"):
        return {**out, "error": full["error"]}
    by = {r["account"]: r for r in full.get("accounts") or []}
    for r in mine:
        e = by.get(r["account_id"])
        conds = {}
        for cid in CHECK_IDS:
            x = ((e or {}).get("conditions") or {}).get(cid) or {}
            s = x.get("status")
            conds[cid] = {"v": "met" if s == RD.OK else "not_yet" if s == RD.NO else "unknown",
                          "why": str(x.get("why") or "")[:120]}
        out["accounts"].append({"account_id": r["account_id"], "status": r["status"], "trades": r.get("trades"),
                                "in_readiness": e is not None, "conditions": conds})
    return out


# ---------------------------------------------------------------- the routes
def register(app, ctx) -> dict:
    from ..analysis import Heavy
    cache: dict = {}
    lock = threading.Lock()
    heavy = Heavy()
    rdir = os.path.join(os.path.dirname(os.path.abspath(ctx.db)), "rehearsal")

    def view(now: int) -> dict:
        data = ctx.data
        try:
            with contextlib.closing(data.conn()) as c:
                from .story import run_start
                start = run_start(c)
        except sqlite3.Error as exc:
            return {"ready": False, "error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
        led = read_ledger(ctx.checkpoint_db)
        c = clock(start, now, led, day_state_reader(ctx.db))
        rh = rehearsals(rdir)
        try:
            jb = timers(getattr(ctx, "jobs_runner", None))
        except Exception as exc:  # noqa: BLE001  (systemd never takes the card down)
            jb = {"available": False, "reason": type(exc).__name__, "jobs": {}}
        meeting = None
        if c.get("last"):
            with ctx.rooms.ro(ctx.rooms.agents_db) as a:
                meeting = lead_meeting(a, c["last"]["ts"])
        return {"ready": bool(c.get("ready")), "now": now, "clock": c, "machine": machine(rh, jb, c),
                "milestones": milestones(c, rh.get("runs")), "meeting": meeting,
                "ledger": {"db": led.get("db"), "error": led.get("error")}}

    @app.get("/api/v4/verdictday")
    def get_verdictday():
        """The verdict-day clock, the 판정 기계 card, the road's milestones and the lead's meeting (cached 30 s)."""
        from ..app import json_finite
        now = int(time.time() * 1000)
        key = now // 30_000
        hit = cache.get("v")
        if hit and hit[0] == key:
            return hit[1]
        with lock:
            hit = cache.get("v")
            if hit and hit[0] == key:
                return hit[1]
            v = json_finite(view(now))
            cache["v"] = (key, v)
        return v

    @app.get("/api/v4/verdictday/after")
    def get_after():
        """After a verdict: the real-trading checklist of the accounts that passed (background, cached 5 minutes)."""
        led = read_ledger(ctx.checkpoint_db)
        last = max(led.get("verdicts") or {"": 0})
        return heavy.get(f"after:{last}", AFTER_TTL_S, lambda: checklist(ctx.db, ctx.checkpoint_db, int(time.time() * 1000)),
                         wait_s=3.0)

    return {"routes": ["/api/v4/verdictday", "/api/v4/verdictday/after"], "cache": cache}
