"""예약 작업 (서버 › 서버·비용 › 예약 작업, v4_missing A9): whether each paperbot timer is switched on, when it last
fired, when it fires next and how its last run ended, straight from systemd. Read-only.

    GET /api/v4/jobs

One ``systemctl show`` call for the timers and one for their services (a fixed list of unit names below: nothing from
the request reaches the command line), each with a 2 s timeout, the whole answer cached 60 s. The command runs with
TZ=UTC and LC_ALL=C, so the timestamps it prints ("Mon 2026-10-05 23:40:01 UTC") are read the same on any server.

Answer::

    {"ready": true, "available": true, "ts": <ms>, "jobs": {"paperbot-backup": {
        "state": "on" | "off" | "missing",       # timer enabled and waiting / switched off / not installed
        "file_state": "enabled", "active": "active",
        "last_ms": <ms> | null,                  # the timer's last trigger (LastTriggerUSec)
        "next_ms": <ms> | null,                  # its next elapse (NextElapseUSecRealtime), null while off
        "result": "success" | "exit-code" | ... | null,   # the service's last result
        "ok": true | false | null,               # result == success (null: never ran)
        "running": bool}}}

When systemctl is missing, times out or answers with an error (a container, a test machine, an older server) the
answer is ``{"ready": true, "available": false, "reason": "...", "jobs": {}}`` and the page keeps its 수집 전 marks.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

TTL_S = 60.0
TIMEOUT_S = 2.0
# the timers the 예약 작업 card lists (screens/server-kit.js JOBS; deploy/paperbot-*.timer)
UNITS = ("paperbot-daily3", "paperbot-backup", "paperbot-offsite", "paperbot-obsidian", "paperbot-shadow200",
         "paperbot-agents", "paperbot-checkpoint", "paperbot-dscheck", "paperbot-evening", "paperbot-rehearsal",
         "paperbot-labmonthly")
TIMER_PROPS = "Id,LoadState,UnitFileState,ActiveState,LastTriggerUSec,NextElapseUSecRealtime"
SERVICE_PROPS = "Id,LoadState,ActiveState,SubState,Result,ExecMainExitTimestamp"
ON_FILE_STATES = ("enabled", "enabled-runtime", "linked", "linked-runtime", "static", "alias", "indirect", "generated",
                  "transient")
_UNIT = re.compile(r"^paperbot-[a-z0-9]+$")
_TS = re.compile(r"^(?:[A-Za-z]{3} )?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.\d+)?(?: ([A-Za-z]+|[+-]\d{2}:?\d{2}))?$")
_ZONES = {"UTC": 0, "GMT": 0, "Z": 0, "KST": 9 * 3600}


class Unavailable(Exception):
    """systemctl cannot answer here (missing, timed out, refused): the reason is shown as is."""


def parse_ts(v: Optional[str]) -> Optional[int]:
    """systemd's timestamp text -> ms (None for "n/a", "0", empty or a zone this file does not know)."""
    v = (v or "").strip()
    if not v or v in ("n/a", "0"):
        return None
    if v.startswith("@"):
        try:
            return int(float(v[1:]) * 1000)
        except ValueError:
            return None
    m = _TS.match(v)
    if not m:
        return None
    zone = m.group(2) or "UTC"
    if zone in _ZONES:
        off = _ZONES[zone]
    elif zone[0] in "+-":
        z = zone.replace(":", "")
        off = (1 if z[0] == "+" else -1) * (int(z[1:3]) * 3600 + int(z[3:5]) * 60)
    else:
        return None
    t = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    return int(t.timestamp() * 1000) - off * 1000


def parse_show(text: str) -> dict:
    """`systemctl show -p ... a b` output (blank-line separated blocks of Key=Value) -> {Id: {Key: Value}}."""
    out: dict = {}
    for block in re.split(r"\n\s*\n", text or ""):
        props: dict = {}
        for line in block.splitlines():
            k, sep, v = line.partition("=")
            if sep:
                props[k.strip()] = v.strip()
        if props.get("Id"):
            out[props["Id"]] = props
    return out


def show(units: list, props: str, runner: Optional[Callable] = None) -> dict:
    """One `systemctl show` for ``units`` (fixed names only); Unavailable when it cannot answer."""
    units = [u for u in units if re.match(r"^paperbot-[a-z0-9]+\.(timer|service)$", u)]
    exe = shutil.which("systemctl")
    if not exe:
        raise Unavailable("systemctl 없음")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TZ": "UTC", "LC_ALL": "C", "SYSTEMD_PAGER": "",
           "SYSTEMD_COLORS": "0"}
    runner = runner or subprocess.run
    try:
        # one --property= per name (older systemd versions do not split a comma list)
        r = runner([exe, "show", "--no-pager", *[f"--property={p}" for p in props.split(",")], *units], capture_output=True, text=True,
                   timeout=TIMEOUT_S, env=env, check=False)
    except subprocess.TimeoutExpired:
        raise Unavailable("systemctl 응답 없음 (2초)") from None
    except OSError as exc:
        raise Unavailable(f"systemctl 실행 실패: {type(exc).__name__}") from None
    if r.returncode != 0:
        msg = (r.stderr or "").strip().splitlines()
        raise Unavailable(("systemctl 오류: " + msg[0][:120]) if msg else f"systemctl 오류 (코드 {r.returncode})")
    return parse_show(r.stdout)


def job_state(timer: Optional[dict], service: Optional[dict]) -> dict:
    """One unit's row for the page from its timer's and service's properties."""
    timer, service = timer or {}, service or {}
    if not timer or timer.get("LoadState") in ("not-found", "masked", "error", "bad-setting"):
        state = "missing" if timer.get("LoadState") != "masked" else "off"
    else:
        on = timer.get("UnitFileState", "") in ON_FILE_STATES and timer.get("ActiveState") == "active"
        state = "on" if on else "off"
    result = service.get("Result") or None
    last = parse_ts(timer.get("LastTriggerUSec"))
    ran = last is not None or parse_ts(service.get("ExecMainExitTimestamp")) is not None
    return {
        "state": state,
        "file_state": timer.get("UnitFileState") or None,
        "active": timer.get("ActiveState") or None,
        "last_ms": last,
        "next_ms": parse_ts(timer.get("NextElapseUSecRealtime")) if state == "on" else None,
        "result": result if ran else None,
        "ok": (result == "success") if (ran and result) else None,
        "running": service.get("ActiveState") in ("activating", "active") and service.get("SubState") in ("start", "running"),
    }


def jobs(runner: Optional[Callable] = None, units: tuple = UNITS) -> dict:
    """The whole answer (never raises for a systemctl problem)."""
    now = int(time.time() * 1000)
    names = [u for u in units if _UNIT.match(u)]
    try:
        timers = show([u + ".timer" for u in names], TIMER_PROPS, runner)
        services = show([u + ".service" for u in names], SERVICE_PROPS, runner)
    except Unavailable as exc:
        return {"ready": True, "available": False, "reason": str(exc), "ts": now, "jobs": {}}
    return {"ready": True, "available": True, "ts": now,
            "jobs": {u: job_state(timers.get(u + ".timer"), services.get(u + ".service")) for u in names}}


# ---------------------------------------------------------------- the route
def register(app, ctx) -> dict:
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/jobs")
    def get_jobs():
        """The paperbot timers from systemd (on / off, last / next run, last result); cached 60 s, 2 s timeout."""
        hit = cache.get("v")
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:                                   # one systemctl at a time (two phones opening together)
            hit = cache.get("v")
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
            v = jobs(getattr(ctx, "jobs_runner", None) or subprocess.run)
            cache["v"] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/jobs"], "cache": cache}
