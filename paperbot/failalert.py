"""One Telegram warning when a scheduled job fails (deploy/paperbot-failed@.service).

The checkpoint, nightly-check, monthly re-check, agent, weekly rehearsal, DeepSeek check, shadow200 and
backup units name the handler in OnFailure=, and systemd
starts it with the failed unit's name: ``python -m paperbot.failalert paperbot-checkpoint.service``. It sends
one Korean WARN: which job, how it ended (systemd's $MONITOR_SERVICE_RESULT / $MONITOR_EXIT_STATUS), and the
commands to see why and to clear the entry. At most one per unit per KST day: the hourly checkpoint retries
and the 15-minute agent passes would otherwise repeat it. The day of the last delivered warning is kept in
<state dir>/<unit>; a warning Telegram did not take is tried again at the next failure. The one database it reads
is paper3.db, read-only, for the number of accounts the bot runs (the runner's state 'run', else the accounts
table; no number when it cannot be read): the warning says the bot keeps running them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from typing import Mapping, Optional

from .notify import WARN, Notifier

STATE_DIR = "/var/lib/paperbot/failalert"
PAPER_DB = "/var/lib/paperbot/paper3.db"
# unit -> (what the owners call the job, when it runs again by itself)
JOBS_KO = {
    "paperbot-checkpoint.service": ("체크포인트 판정", "매시 35분에 다시 돎"),
    "paperbot-daily3.service": ("매일 점검(09:20)", "내일 09:20에 다시 돎"),
    "paperbot-labmonthly.service": ("매달 재검사", "다음 달 6일에 다시 돎\n지금 다시: sudo systemctl start paperbot-labmonthly"),
    "paperbot-agents.service": ("에이전트 회의", "15분마다 다시 시도"),
    "paperbot-obsidian.service": ("옵시디언 볼트 갱신(09:50)",
                                  "내일 09:50에 다시 돎\n지금 다시: sudo systemctl start paperbot-obsidian"),
    "paperbot-rehearsal.service": ("판정 미리 연습(매주 수요일)",
                                   "다음 주 수요일 12:30에 다시 돎 (진짜 판정에는 영향 없음)\n"
                                   "지금 다시: sudo systemctl start paperbot-rehearsal"),
    "paperbot-dscheck.service": ("딥시크 신호 밤 재계산 점검(09:30)",
                                 "내일 09:30에 다시 돎 (계좌·주문과 무관)\n"
                                 "결과 한 줄: cat /var/lib/paperbot/dscheck/last.txt\n"
                                 "지금 다시: sudo systemctl start paperbot-dscheck"),
    "paperbot-backup.service": ("데이터베이스 백업(08:40)",
                                "내일 08:40에 다시 돎 (봇·계좌와 무관, 그 전 사본 14일치는 그대로)\n"
                                "사본 확인: ls -lt /var/backups/paperbot | head -3\n"
                                "지금 다시: sudo systemctl start paperbot-backup"),
    "paperbot-paramshadow.service": ("커스텀값 그림자 밤 계산(10:00)",
                                     "내일 10:00에 다시 돎 (빠진 날은 다음 실행이 이어서 계산, 계좌·주문과 무관)\n"
                                     "결과 한 줄: cat /var/lib/paperbot/paramshadow/last.txt\n"
                                     "지금 다시: sudo systemctl start paperbot-paramshadow"),
    "paperbot-shadow200.service": ("딥시크 200 그림자 시험(기록만)",
                                   "15분마다 다시 돎 (빠진 부분은 다음 실행이 스스로 메움, 계좌·주문과 무관)\n"
                                   "지금 상태: cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.shadow200 status"),
}
RESULT_KO = {"exit-code": "오류로 끝남", "timeout": "시간 제한을 넘김", "signal": "강제로 멈춰짐",
             "core-dump": "강제로 멈춰짐", "oom-kill": "메모리 한도를 넘김", "watchdog": "응답 없음"}


def kst_day(now_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now_ms / 1000 + 9 * 3600))


def accounts_n(db: Optional[str] = PAPER_DB) -> Optional[int]:
    """How many accounts the bot runs, from paper3.db read-only: the runner's own count at its last start (state
    'run' "accounts"), else the rows of the accounts table; None when the database cannot be read. Never raises."""
    if not db or not os.path.exists(db):
        return None
    try:
        c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(db))}?mode=ro", uri=True, timeout=5)
        try:
            try:
                r = c.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
                n = (json.loads(r[0]) or {}).get("accounts") if r else None
            except (sqlite3.Error, ValueError, TypeError, AttributeError):
                n = None
            if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
                n = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            return int(n) if n else None
        finally:
            c.close()
    except Exception:  # noqa: BLE001  (a number in a warning never stops the warning)
        return None


def alert_text(unit: str, env: Mapping[str, str], accounts: Optional[int] = None) -> str:
    name, again = JOBS_KO.get(unit, (unit, ""))
    result, status = env.get("MONITOR_SERVICE_RESULT") or "", env.get("MONITOR_EXIT_STATUS") or ""
    how = RESULT_KO.get(result, "실패")
    if result == "exit-code" and status:
        how += f" (종료 코드 {status})"
    if unit == "paperbot-agents.service" and result == "exit-code" and status == "2":
        how += ": Claude 로그인 확인 거부이거나 설정 값 오류 (안내서 8-2·8-4)"
    if unit == "paperbot-dscheck.service" and result == "exit-code" and status in ("1", "2"):
        how += (": 다시 계산한 딥시크 신호가 기록과 다름" if status == "1"
                else ": 코드 고정값(핀) 확인이나 봉 받기가 안 돼 점검을 못 함")
    if unit == "paperbot-backup.service" and result == "exit-code" and status == "1":
        how += ": 데이터베이스 사본 하나 이상을 만들지 못함 (어느 것인지는 아래 이유에)"
    short = unit.removesuffix(".service")
    bot = f"봇(계좌 {accounts}개)" if accounts else "봇"
    return (f"작업 실패 · {name}\n\n{how}\n{bot}은 그대로 돎\n" + (f"{again}\n" if again else "")
            + f"\n이유: sudo journalctl -u {short} -n 50\n"
            f"확인 후: sudo systemctl reset-failed {short}\n"
            "(오늘은 다시 알리지 않음)")


def main(argv: Optional[list[str]] = None, *, env: Optional[Mapping[str, str]] = None,
         notifier: Optional[Notifier] = None, now_ms: Optional[int] = None, state_dir: str = STATE_DIR,
         db: Optional[str] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.failalert", description=__doc__)
    ap.add_argument("unit", help="the failed unit (systemd's %%i of paperbot-failed@.service)")
    ap.add_argument("--db", default=None, help=f"paper3.db, read-only, for the account count (default {PAPER_DB})")
    args = ap.parse_args(argv)
    unit = args.unit
    db = db or args.db or PAPER_DB
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
    if notifier.send(WARN, alert_text(unit, env, accounts_n(db))) is False:
        return 1                                  # not delivered: the next failure tries again
    os.makedirs(state_dir, exist_ok=True)
    with open(stamp + ".tmp", "w") as fh:
        fh.write(day + "\n")
    os.replace(stamp + ".tmp", stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
