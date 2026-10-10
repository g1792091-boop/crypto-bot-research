"""후보 리그 watch: one check, run every 10 minutes by candleague-watch.timer, apart from the engine (so a stopped engine
is still reported).

    python -m candleague.watch

Rules:
* stall: the league's processed time (snap/league.json ``done_ms``) has not moved for STALL_MS (60 minutes; the engine
  moves it every 5 minutes, and the catch-up from 10-01 after every day it replays). Counted from the later of when it
  last moved and the watch's own first check, so a fresh install is not reported before the engine had time.
* stopped: ``systemctl is-active candleague-live.service`` says inactive or failed (unprivileged; no systemctl means
  "unknown", never a problem).
A warning goes to every chat of CANDLEAGUE_TG_CHAT at once (the Bot API directly, not through the engine), then at most
every REPEAT_MS (3 hours) while it lasts; one "다시 정상" once it is fine again. Without a token or chat it only prints.
State: /var/lib/candleague/watch_state.json (or CANDLEAGUE_WATCH_STATE). It never raises; exit 1 only when it could not
write its state (the unit then fails visibly instead of repeating a warning every 10 minutes).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Callable, Optional

from .notify import KST, TAG, send_telegram

STALL_MS = 60 * 60_000
REPEAT_MS = 3 * 3_600_000
UNIT = "candleague-live.service"


def service_state(run: Callable = subprocess.run) -> str:
    try:
        r = run(["systemctl", "is-active", UNIT], capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def read_json(path: str) -> Optional[dict]:
    try:
        with open(path) as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def _kst(ms) -> str:
    return "-" if not ms else time.strftime("%m-%d %H:%M", time.gmtime((ms + KST) / 1000))


def check(state: dict, league: Optional[dict], svc: str, now_ms: int) -> tuple[dict, list[str]]:
    """(new state, messages to send) for one check."""
    st = dict(state or {})
    st.setdefault("first_ms", now_ms)
    done = league.get("done_ms") if league else None
    if done is not None and done != st.get("done_ms"):
        st["done_ms"], st["moved_ms"] = done, now_ms
    since = max(st.get("moved_ms") or 0, st["first_ms"])
    problems = []
    if svc in ("inactive", "failed"):
        problems.append(f"엔진이 꺼져 있습니다 ({UNIT}: {svc})")
    if now_ms - since >= STALL_MS:
        if done is None:
            problems.append(f"첫 처리 기록(league.json)이 {(now_ms - since) // 60_000}분째 없습니다")
        else:
            problems.append(f"처리 시각이 {(now_ms - since) // 60_000}분째 그대로입니다 (마지막 {_kst(done)} KST까지)")
    msgs = []
    if problems:
        if not st.get("warned_ms") or now_ms - st["warned_ms"] >= REPEAT_MS:
            msgs.append(f"{TAG} ⚠️ 멈춤 확인 필요 (종이 매매, 실제 돈 아님)\n" + "\n".join(f"- {p}" for p in problems)
                        + "\n서버에서 확인: sudo journalctl -u candleague-live -n 40 --no-pager")
            st["warned_ms"] = now_ms
    elif st.get("warned_ms"):
        msgs.append(f"{TAG} ✅ 다시 정상으로 돕니다 ({_kst(done)} KST까지 처리)")
        st["warned_ms"] = None
    return st, msgs


def send(msgs: list[str], token: Optional[str], chats: list[str], sender: Callable = send_telegram) -> None:
    for text in msgs:
        print(text, flush=True)
        for chat in chats if token else []:
            try:
                sender(token, chat, text)
            except Exception as exc:  # noqa: BLE001  one chat failing never stops the others
                print(f"{TAG} telegram failed: {type(exc).__name__}", flush=True)


def main(argv: Optional[list] = None) -> int:
    snap = os.environ.get("CANDLEAGUE_SNAP", "/var/lib/candleague/snap")
    path = os.environ.get("CANDLEAGUE_WATCH_STATE", "/var/lib/candleague/watch_state.json")
    now = int(time.time() * 1000)
    st, msgs = check(read_json(path) or {}, read_json(os.path.join(snap, "league.json")), service_state(), now)
    chats = [c.strip() for c in os.environ.get("CANDLEAGUE_TG_CHAT", "").split(",") if c.strip()][:4]
    send(msgs, os.environ.get("CANDLEAGUE_TG_TOKEN"), chats)
    try:
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as fh:
            json.dump(st, fh)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"{TAG} watch state not written: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
