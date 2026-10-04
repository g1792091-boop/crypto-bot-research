"""One Telegram warning when a scheduled job fails (deploy/paperbot-failed@.service).

The checkpoint, nightly-check, monthly re-check, agent and weekly rehearsal units name the handler in OnFailure=, and systemd
starts it with the failed unit's name: ``python -m paperbot.failalert paperbot-checkpoint.service``. It sends
one Korean WARN: which job, how it ended (systemd's $MONITOR_SERVICE_RESULT / $MONITOR_EXIT_STATUS), and the
commands to see why and to clear the entry. At most one per unit per KST day: the hourly checkpoint retries
and the 15-minute agent passes would otherwise repeat it. The day of the last delivered warning is kept in
<state dir>/<unit>; a warning Telegram did not take is tried again at the next failure. Opens no database.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from typing import Mapping, Optional

from .notify import WARN, Notifier

STATE_DIR = "/var/lib/paperbot/failalert"
# unit -> (what the owners call the job, when it runs again by itself)
JOBS_KO = {
    "paperbot-checkpoint.service": ("체크포인트 판정", "매시 35분에 다시 돕니다."),
    "paperbot-daily3.service": ("매일 점검(09:20)", "내일 09:20에 다시 돕니다."),
    "paperbot-labmonthly.service": ("매달 재검사", "다음 달 6일에 다시 돕니다. 지금 다시: sudo systemctl start paperbot-labmonthly"),
    "paperbot-agents.service": ("에이전트 회의", "15분마다 다시 시도합니다."),
    "paperbot-rehearsal.service": ("판정 미리 연습(매주 수요일)",
                                   "다음 주 수요일 12:30에 다시 돕니다. 진짜 판정에는 영향 없음. "
                                   "지금 다시: sudo systemctl start paperbot-rehearsal"),
}
RESULT_KO = {"exit-code": "오류로 끝남", "timeout": "시간 제한을 넘김", "signal": "강제로 멈춰짐",
             "core-dump": "강제로 멈춰짐", "oom-kill": "메모리 한도를 넘김", "watchdog": "응답 없음"}


def kst_day(now_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now_ms / 1000 + 9 * 3600))


def alert_text(unit: str, env: Mapping[str, str]) -> str:
    name, again = JOBS_KO.get(unit, (unit, ""))
    result, status = env.get("MONITOR_SERVICE_RESULT") or "", env.get("MONITOR_EXIT_STATUS") or ""
    how = RESULT_KO.get(result, "실패")
    if result == "exit-code" and status:
        how += f", 종료 코드 {status}"
    if unit == "paperbot-agents.service" and result == "exit-code" and status == "2":
        how += ": Claude 로그인 확인 거부이거나 설정 값 오류 (안내서 8-2·8-4)"
    return (f"[작업 실패] {name}: {how} ({unit}).\n"
            f"봇(195개 계좌)은 그대로 돕니다. {again}\n"
            f"이유 보기: sudo journalctl -u {unit} -n 50 --no-pager\n"
            f"확인한 뒤: sudo systemctl reset-failed {unit}\n"
            "같은 작업은 오늘(한국 날짜) 다시 알리지 않습니다 (안내서 13-7).")


def main(argv: Optional[list[str]] = None, *, env: Optional[Mapping[str, str]] = None,
         notifier: Optional[Notifier] = None, now_ms: Optional[int] = None, state_dir: str = STATE_DIR) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.failalert", description=__doc__)
    ap.add_argument("unit", help="the failed unit (systemd's %%i of paperbot-failed@.service)")
    unit = ap.parse_args(argv).unit
    if not re.fullmatch(r"[A-Za-z0-9@._:-]+", unit) or unit.startswith("."):
        print(f"not a unit name: {unit!r}", file=sys.stderr)
        return 2
    env = os.environ if env is None else env
    day = kst_day(int(time.time() * 1000) if now_ms is None else now_ms)
    stamp = os.path.join(state_dir, unit)
    try:
        with open(stamp) as fh:
            if fh.read().strip() == day:
                return 0                          # told today already
    except OSError:
        pass
    if notifier is None:
        from .live import _notifier
        notifier = _notifier()
    if notifier.send(WARN, alert_text(unit, env)) is False:
        return 1                                  # not delivered: the next failure tries again
    os.makedirs(state_dir, exist_ok=True)
    with open(stamp + ".tmp", "w") as fh:
        fh.write(day + "\n")
    os.replace(stamp + ".tmp", stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
