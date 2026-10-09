"""Outside watch of the demo lab (CONTRACT.md 8.8): one check, run every 10 minutes by demobot-watch.timer.

    python -m demobot.watch

Reads ``snap/status.json`` (``last_tick_ms``, ``live_start_ms``), ``snap/rank_meta.json`` (``generated_ms``) and
``snap/backup.json``, and asks systemd (unprivileged, best effort: ``systemctl is-active demobot-live.service``, the
last result of ``demobot-rank.service``; no systemctl or no systemd means "unknown", never a problem). Rules:

* ``dead``: no engine tick for 45 minutes, or demobot-live is not running (inactive / failed). The 45 minutes count
  from the later of the last tick and the time the watch timer itself was (re)started (on.sh, a reboot, update.sh),
  so turning the bot back on after a pause is not reported before its first tick could have happened. A crash loop
  restarts only the engine, not the watch, so it is still reported.
* ``rank``: no new ranking for 3 hours (same start rule; before the first ranking: since the live start), or the
  last ranking run failed.
* ``backup``: no good backup for 36 hours, counted from the latest of the last good backup, the live start and the
  watch's own first check (a first backup is not expected before the bot has run 36 hours, nor in the first 36 hours
  after an update installed the backup and the watch; without the live start and a good backup the rule is skipped).
  Deferred for the first hour after the watch timer started (the backup timer catches up a missed night then).

Each problem is sent at once to every chat of ``DEMOBOT_TG_CHAT`` (``notify.parse_chats``: the owners' private chats
and/or a group), directly with the Bot API (``notify.render`` 'warn'), not through the outbox: when the engine is dead
nobody flushes the outbox. At most one warning per what every 3 hours; once it is fine again, one ``warn_clear``.
A message that reached some chats but not others is sent again at the next checks to the missing ones only (while
it still applies), so nobody gets it twice. The watch keeps its own state (``/var/lib/demobot/watch_state.json``, or
``DEMOBOT_WATCH_STATE``) and writes ``snap/watch.json``. It never raises; exit 1 only when it could not write its
state (then the unit fails visibly instead of repeating a warning every 10 minutes).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Callable, Optional

from . import notify as N

DEAD_MS = 45 * 60_000
RANK_MS = 3 * 3600_000
BACKUP_MS = 36 * 3600_000
BACKUP_SETTLE_MS = 3600_000
REPEAT_MS = 3 * 3600_000
WHATS = ("dead", "rank", "backup")
STATE_FILE = "/var/lib/demobot/watch_state.json"
DEFAULT_SNAP = "/var/lib/demobot/snap"
LIVE_UNIT, RANK_UNIT, WATCH_TIMER = "demobot-live.service", "demobot-rank.service", "demobot-watch.timer"
RUNNING = ("active", "reloading", "activating", "deactivating", "refreshing")
STOPPED = ("inactive", "failed", "maintenance")
KIT = "/root/demobot-src/deploy/demobot"

Systemctl = Callable[[list], Optional[str]]


def _stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- reading
def systemctl(args: list, run=subprocess.run) -> Optional[str]:
    """stdout of ``systemctl --no-pager ARGS``; None when systemctl is missing, hangs or says nothing (no systemd)."""
    try:
        r = run(["systemctl", "--no-pager", *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    out = (r.stdout or "").strip()
    return out or None


def unit_state(sc: Systemctl, unit: str) -> Optional[str]:
    out = sc(["is-active", unit])
    s = out.splitlines()[0].strip() if out else ""
    return s if s in RUNNING + STOPPED else None


def unit_props(sc: Systemctl, unit: str, props: tuple) -> dict:
    out = sc(["show", unit, "--property=" + ",".join(props)])
    d = {}
    for ln in (out or "").splitlines():
        k, sep, v = ln.partition("=")
        if sep:
            d[k.strip()] = v.strip()
    return d


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _ms(x) -> Optional[int]:
    v = N._num(x)
    return int(v) if v is not None and v > 0 else None


def _since_ms(props: dict, key: str, now_ms: int, mono_now: float) -> Optional[int]:
    """A systemd monotonic timestamp (microseconds since boot) as epoch ms; None when unknown or never."""
    try:
        us = int(props.get(key) or 0)
    except ValueError:
        return None
    if us <= 0 or us / 1e6 > mono_now + 5:
        return None
    return int(now_ms - (mono_now - us / 1e6) * 1000)


def gather(snap: str, now_ms: int, sc: Optional[Systemctl] = None, mono: Callable[[], float] = time.monotonic) -> dict:
    """The facts the rules need (missing ones are None)."""
    sc = sc or systemctl
    status = _read_json(os.path.join(snap, "status.json")) or {}
    rank = _read_json(os.path.join(snap, "rank_meta.json")) or {}
    backup = _read_json(os.path.join(snap, "backup.json"))
    rp = unit_props(sc, RANK_UNIT, ("ActiveState", "Result"))
    wp = unit_props(sc, WATCH_TIMER, ("ActiveEnterTimestampMonotonic",))
    return {"now_ms": int(now_ms),
            "last_tick_ms": _ms(status.get("last_tick_ms")),
            "live_start_ms": _ms(status.get("live_start_ms")),
            "live_state": unit_state(sc, LIVE_UNIT),
            "rank_ms": _ms(rank.get("generated_ms")),
            "rank_state": rp.get("ActiveState") or None,
            "rank_result": rp.get("Result") or None,
            "backup": backup,
            "watch_since_ms": _since_ms(wp, "ActiveEnterTimestampMonotonic", now_ms, mono())}


# ---------------------------------------------------------------- the rules (pure)
def ago(ms: int) -> str:
    m = max(0, int(ms // 60_000))
    if m < 60:
        return f"{m}분"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h}시간" + (f" {m}분" if m else "")
    d, h = divmod(h, 24)
    return f"{d}일" + (f" {h}시간" if h else "")


def _when(t: int, now: int) -> str:
    return f"{N.kst(t)} ({ago(now - t)} 전)"


def _item(what: str, ok: bool, detail, known: bool = True) -> dict:
    """``detail``: one text or a list of short parts. watch.json gets them on one line (' · '); Telegram gets one part
    per line (the rule bot's short lines)."""
    parts = [str(x) for x in (detail if isinstance(detail, (list, tuple)) else [detail]) if str(x or "").strip()]
    return {"what": what, "ok": bool(ok), "detail_ko": " · ".join(parts), "known": bool(known), "lines": parts}


def check_dead(f: dict) -> dict:
    now, tick, state = f["now_ms"], f.get("last_tick_ms"), f.get("live_state")
    last = f"마지막 계산 {_when(tick, now)}" if tick else "아직 계산 기록 없음"
    if state in STOPPED:
        return _item("dead", False, [f"엔진 서비스(demobot-live)가 꺼져 있음 ({state})", last,
                                     f"다시 켜기: sudo bash {KIT}/on.sh"])
    ref = max(x for x in (tick, f.get("watch_since_ms"), 0) if x is not None)
    if not ref:
        return _item("dead", True, "확인 못 함: 엔진 상태 파일(status.json)이 아직 없음", known=False)
    if now - ref > DEAD_MS:
        return _item("dead", False, [last, "45분 넘게 새 계산이 없음", "기록: journalctl -u demobot-live -n 40 --no-pager"])
    if not tick:
        return _item("dead", True, "켜진 지 얼마 안 됨: 첫 계산을 기다리는 중")
    return _item("dead", True, last)


def check_rank(f: dict) -> dict:
    now, gen = f["now_ms"], f.get("rank_ms")
    last = f"마지막 순위표 {_when(gen, now)}" if gen else "아직 순위표 없음"
    result, state = f.get("rank_result"), f.get("rank_state")
    if state == "failed" or (result and result != "success"):
        return _item("rank", False, [f"마지막 순위표 계산이 실패함 ({result or state})", last,
                                     "기록: journalctl -u demobot-rank -n 40 --no-pager"])
    ref = max(x for x in (gen, f.get("live_start_ms") if not gen else None, f.get("watch_since_ms"), 0)
              if x is not None)
    if not ref:
        return _item("rank", True, "확인 못 함: 순위표도 실시간 시작 시각도 아직 없음", known=False)
    if now - ref > RANK_MS:
        return _item("rank", False, [last, "3시간 넘게 새 순위표가 없음",
                                     "시간표: systemctl list-timers demobot-rank.timer"])
    return _item("rank", True, last)


def check_backup(f: dict) -> dict:
    now = f["now_ms"]
    b = f.get("backup") if isinstance(f.get("backup"), dict) else {}
    ok_ms, live0 = _ms(b.get("last_ok_ms")), f.get("live_start_ms")
    last = f"마지막 백업 {_when(ok_ms, now)}" if ok_ms else "아직 성공한 백업 없음"
    err = str(b.get("error_ko") or "").strip()
    ws = f.get("watch_since_ms")
    if ws and now - ws < BACKUP_SETTLE_MS:
        return _item("backup", True, ["감시를 막 켬: 1시간 뒤부터 확인", last], known=False)
    if not ok_ms and not live0:
        return _item("backup", True, "확인 못 함: 실시간 시작 시각이 아직 없음", known=False)
    ref = max(x for x in (ok_ms, live0, f.get("watch_first_ms"), 0) if x is not None)
    if now - ref > BACKUP_MS:
        parts = [last, "36시간 넘게 백업이 안 됨"] + ([f"마지막 오류: {N._clip(err, 300)}"] if err else [])
        return _item("backup", False, parts + ["기록: journalctl -u demobot-backup -n 30 --no-pager"])
    if not ok_ms:
        return _item("backup", True, "아직 첫 백업 전 (매일 04:40)")
    return _item("backup", True, last)


def evaluate(f: dict) -> list:
    """The three items (what, ok, detail_ko, known). Never raises: a slip makes that item 'unknown'."""
    out = []
    for what, fn in (("dead", check_dead), ("rank", check_rank), ("backup", check_backup)):
        try:
            out.append(fn(f))
        except Exception as exc:  # noqa: BLE001
            out.append(_item(what, True, f"확인 못 함 ({type(exc).__name__})", known=False))
    return out


# ---------------------------------------------------------------- state and sending
def load_state(path: str) -> dict:
    """{"items": {what: {"bad", "warned", "last_warn_ms", "since_ms"}}, "first_check_ms"}; empty when missing or bad."""
    d = _read_json(path) or {}
    items = d.get("items") if isinstance(d.get("items"), dict) else {}
    return {"items": {w: (items.get(w) if isinstance(items.get(w), dict) else {}) for w in WHATS},
            "first_check_ms": _ms(d.get("first_check_ms"))}


def _atomic_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


Deliver = Callable[[str, dict, Optional[list]], tuple]


def decide(items: list, state: dict, now_ms: int, deliver: Deliver) -> dict:
    """Send what is due and return the new state. ``deliver(kind, payload, chats)`` sends to ``chats`` (None: every
    chat) and returns (chats that got it, chats that did not). A warning goes when a what is bad and none went for it
    in the last 3 hours; a clear when it is fine again after a warning. A message no chat got is tried again in full
    at the next check (the state only moves when at least one chat got it); one that some chats missed is kept as
    ``retry`` and sent to those only, while it still applies (a warning while still bad, a clear while fine)."""
    st = {"items": {w: dict(v) for w, v in state.get("items", {}).items()},
          "first_check_ms": state.get("first_check_ms") or now_ms}
    for it in items:
        what = it["what"]
        s = st["items"].setdefault(what, {})
        if not it.get("known", True):
            continue
        payload = {"what": what, "detail_ko": "\n".join(it.get("lines") or [it["detail_ko"]])}
        kind = None
        if not it["ok"]:
            if not s.get("bad"):
                s["since_ms"] = now_ms
            s["bad"] = True
            last = s.get("last_warn_ms")
            if not isinstance(last, (int, float)) or now_ms - last >= REPEAT_MS:
                kind = "warn"
        else:
            if s.get("warned"):
                kind = "warn_clear"
            s["bad"] = False
            s["since_ms"] = None
        if kind:
            got, missed = deliver(kind, payload, None)
            if got:
                s["warned"] = kind == "warn"
                if kind == "warn":
                    s["last_warn_ms"] = now_ms
                s["retry"] = {"kind": kind, "payload": payload, "chats": list(missed)} if missed else None
            continue
        r = s.get("retry")
        if isinstance(r, dict) and r.get("chats") and isinstance(r.get("payload"), dict):
            if (r.get("kind") == "warn") == (not it["ok"]):
                _got, missed = deliver(str(r["kind"]), r["payload"], [str(c) for c in r["chats"]])
                r["chats"] = list(missed)
                if not missed:
                    s["retry"] = None
            else:
                s["retry"] = None              # no longer applies (the problem came or went meanwhile)
        elif r is not None:
            s["retry"] = None
    st["checked_ms"] = now_ms
    return st


def make_deliver(token: str, chat: str, now_ms: int, send=None, log=_stderr) -> Deliver:
    send = send or N.send_message
    chats = N.parse_chats(chat)

    def deliver(kind: str, payload: dict, only: Optional[list] = None) -> tuple:
        targets = [c for c in (only if only is not None else chats)]
        if not token or not targets:
            log(f"demobot watch: {kind} {payload.get('what')} not sent: DEMOBOT_TG_TOKEN / DEMOBOT_TG_CHAT empty")
            return [], []
        text = N.render(kind, payload, now_ms=now_ms)
        got, missed = [], []
        for c in targets:
            try:
                if send(token, c, text) is False:
                    raise N.TelegramError("send returned False")
                got.append(c)
            except Exception as exc:  # noqa: BLE001  (tried again at the next check)
                missed.append(c)
                log(N.redact(f"demobot watch: {kind} {payload.get('what')} not sent to {c}: "
                             f"{exc if isinstance(exc, N.TelegramError) else f'{type(exc).__name__}: {exc}'}",
                             token)[:300])
        if got:
            log(f"demobot watch: sent {kind} {payload.get('what')} to {', '.join(got)}")
        return got, missed
    return deliver


def run(snap: str, state_path: str, token: str, chat: str, now_ms: Optional[int] = None,
        sc: Optional[Systemctl] = None, send=None, mono: Callable[[], float] = time.monotonic, log=_stderr) -> int:
    """One check. 0, or 1 when the state could not be written. Never raises."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    try:
        facts = gather(snap, now_ms, sc, mono)
    except Exception as exc:  # noqa: BLE001
        log(f"demobot watch: cannot read the facts: {type(exc).__name__}: {exc}"[:300])
        facts = {"now_ms": now_ms}
    state = load_state(state_path)
    facts["watch_first_ms"] = state.get("first_check_ms") or now_ms
    items = evaluate(facts)
    try:
        new = decide(items, state, now_ms, make_deliver(token, chat, now_ms, send, log))
    except Exception as exc:  # noqa: BLE001
        log(f"demobot watch: {type(exc).__name__}: {exc}"[:300])
        new = dict(state, checked_ms=now_ms, first_check_ms=state.get("first_check_ms") or now_ms)
    try:
        _atomic_json(os.path.join(snap, "watch.json"),
                     {"checked_ms": now_ms, "ok": all(i["ok"] for i in items),
                      "items": [{"what": i["what"], "ok": i["ok"], "detail_ko": i["detail_ko"]} for i in items]})
    except Exception as exc:  # noqa: BLE001
        log(f"demobot watch: cannot write {snap}/watch.json: {type(exc).__name__}: {exc}"[:300])
    log("demobot watch: " + " · ".join(f"{i['what']} {'ok' if i['ok'] else 'PROBLEM'}"
                                       f"{'' if i['known'] else ' (unknown)'}" for i in items))
    try:
        _atomic_json(state_path, new)
    except Exception as exc:  # noqa: BLE001
        log(f"demobot watch: cannot write its state {state_path}: {type(exc).__name__}: {exc}"[:300])
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demobot.watch", description="demo lab outside watch: one check")
    ap.add_argument("--snap", default=None, help="snapshot folder (default $DEMOBOT_SNAP or /var/lib/demobot/snap)")
    ap.add_argument("--state", default=None,
                    help="state file (default $DEMOBOT_WATCH_STATE or /var/lib/demobot/watch_state.json)")
    ap.add_argument("--env-file", default=N.ENV_FILE)
    try:
        a = ap.parse_args(argv)
        snap = a.snap or os.environ.get("DEMOBOT_SNAP") or DEFAULT_SNAP
        state = a.state or os.environ.get("DEMOBOT_WATCH_STATE") or STATE_FILE
        token, chat = N.credentials(a.env_file)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _stderr(f"demobot watch: {type(exc).__name__}: {exc}"[:300])
        return 0
    return run(snap, state, token, chat)


if __name__ == "__main__":
    sys.exit(main())
