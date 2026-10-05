"""One Korean WARN when a scheduled job fails (paperbot/failalert.py, deploy/paperbot-failed@.service)."""
import os

from paperbot import failalert as FA
from paperbot.notify import WARN, ListNotifier

T = 1791036000000            # 2026-10-03 14:00 UTC = 23:00 KST
MIN = 60_000
FAILED = {"MONITOR_SERVICE_RESULT": "exit-code", "MONITOR_EXIT_STATUS": "1"}


def test_one_warning_per_unit_per_kst_day(tmp_path):
    note = ListNotifier()

    def run(unit, t, env=FAILED):
        return FA.main([unit], env=env, notifier=note, now_ms=t, state_dir=str(tmp_path))
    assert run("paperbot-checkpoint.service", T) == 0
    assert run("paperbot-checkpoint.service", T + 35 * MIN) == 0        # the hourly retry, 23:35 KST: no second one
    assert run("paperbot-agents.service", T + 15 * MIN) == 0            # another job: its own warning
    assert run("paperbot-agents.service", T + 30 * MIN) == 0            # the next 15-minute pass: silent
    assert run("paperbot-checkpoint.service", T + 95 * MIN) == 0        # 00:35 KST: a new day, told again
    assert [(lv, t.split("\n")[0]) for lv, t in note.messages] == [
        (WARN, "작업 실패 · 체크포인트 판정"), (WARN, "작업 실패 · 에이전트 회의"), (WARN, "작업 실패 · 체크포인트 판정")]
    text = note.messages[0][1]
    assert "\n오류로 끝남 (종료 코드 1)\n" in text
    assert "이유: sudo journalctl -u paperbot-checkpoint -n 50\n" in text and "--no-pager" not in text
    assert "확인 후: sudo systemctl reset-failed paperbot-checkpoint\n" in text and "매시 35분" in text
    assert text.endswith("(오늘은 다시 알리지 않음)")
    assert open(os.path.join(tmp_path, "paperbot-checkpoint.service")).read().strip() == "2026-10-04"


def test_an_undelivered_warning_is_tried_at_the_next_failure(tmp_path):
    class Down:
        def send(self, level, text):
            return False                                   # what TelegramNotifier.send says when it failed
    assert FA.main(["paperbot-daily3.service"], env={}, notifier=Down(), now_ms=T, state_dir=str(tmp_path)) == 1
    assert not os.listdir(tmp_path)
    note = ListNotifier()
    assert FA.main(["paperbot-daily3.service"], env={}, notifier=note, now_ms=T + MIN, state_dir=str(tmp_path)) == 0
    assert len(note.messages) == 1 and "매일 점검(09:20)" in note.messages[0][1]


def test_how_it_ended_in_korean(tmp_path):
    note = ListNotifier()
    FA.main(["paperbot-agents.service"], env={"MONITOR_SERVICE_RESULT": "exit-code", "MONITOR_EXIT_STATUS": "2"},
            notifier=note, now_ms=T, state_dir=str(tmp_path / "a"))
    FA.main(["paperbot-labmonthly.service"], env={"MONITOR_SERVICE_RESULT": "timeout"}, notifier=note, now_ms=T,
            state_dir=str(tmp_path / "b"))
    assert "Claude 로그인 확인 거부이거나 설정 값 오류 (안내서 8-2·8-4)" in note.messages[0][1]
    assert note.messages[1][1].startswith("작업 실패 · 매달 재검사\n\n시간 제한을 넘김\n")


def test_only_a_unit_name_is_accepted(tmp_path):
    note = ListNotifier()
    for bad in ("../x", "a b", ".hidden"):
        assert FA.main([bad], env={}, notifier=note, now_ms=T, state_dir=str(tmp_path)) == 2
    assert note.messages == [] and not os.listdir(tmp_path)


def _paper_db(path, run=None, accounts=0):
    import json
    import sqlite3
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE state (k TEXT PRIMARY KEY, ts INTEGER, data TEXT);"
                    "CREATE TABLE accounts (account_id TEXT PRIMARY KEY, kind TEXT);")
    if run is not None:
        c.execute("INSERT INTO state VALUES ('run', 1, ?)", (json.dumps(run),))
    c.executemany("INSERT INTO accounts VALUES (?, 'strategy')", [(f"A{k}@15m",) for k in range(accounts)])
    c.commit()
    c.close()


def test_the_account_count_comes_from_the_database_not_the_code(tmp_path):
    """Paper v4 (plan T5): '봇(계좌 N개)' is the runner's own count (paper3.db state 'run'), else the accounts table;
    with no readable database the warning names no number (never the old 156)."""
    run_db, rows_db = str(tmp_path / "run.db"), str(tmp_path / "rows.db")
    _paper_db(run_db, run={"accounts": 333, "settings": "paper-v4"}, accounts=5)
    _paper_db(rows_db, accounts=7)
    assert FA.accounts_n(run_db) == 333 and FA.accounts_n(rows_db) == 7
    assert FA.accounts_n(str(tmp_path / "none.db")) is None and FA.accounts_n(None) is None
    (tmp_path / "junk.db").write_bytes(b"not a database")
    assert FA.accounts_n(str(tmp_path / "junk.db")) is None
    note = ListNotifier()
    for k, db in enumerate((run_db, rows_db, str(tmp_path / "none.db"))):
        FA.main(["paperbot-daily3.service"], env=FAILED, notifier=note, now_ms=T, state_dir=str(tmp_path / f"s{k}"),
                db=db)
    texts = [t for _, t in note.messages]
    assert "\n봇(계좌 333개)은 그대로 돎\n" in texts[0] and "\n봇(계좌 7개)은 그대로 돎\n" in texts[1]
    assert "\n봇은 그대로 돎\n" in texts[2] and not any("156" in t for t in texts)
    before = os.path.getmtime(run_db)
    FA.main(["paperbot-agents.service", "--db", run_db], env=FAILED, notifier=note, now_ms=T,
            state_dir=str(tmp_path / "s9"))
    assert "계좌 333개" in note.messages[-1][1] and os.path.getmtime(run_db) == before          # read-only


def test_every_unit_that_names_the_handler_has_a_korean_name():
    """A new unit with OnFailure=paperbot-failed@ must be named in JOBS_KO (plan T11), else the owners get its raw
    unit name."""
    import glob
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    units = [os.path.basename(p) for p in glob.glob(os.path.join(root, "deploy", "*.service"))
             if "OnFailure=paperbot-failed@" in open(p, encoding="utf-8").read()]
    assert units and sorted(u for u in units if u not in FA.JOBS_KO) == []


def test_the_deepseek_check_says_what_its_exit_codes_mean(tmp_path):
    note = ListNotifier()
    for k, status in enumerate(("1", "2")):
        FA.main(["paperbot-dscheck.service"], env={"MONITOR_SERVICE_RESULT": "exit-code", "MONITOR_EXIT_STATUS": status},
                notifier=note, now_ms=T, state_dir=str(tmp_path / str(k)))
    assert note.messages[0][1].startswith("작업 실패 · 딥시크 신호 밤 재계산 점검(09:30)\n\n오류로 끝남 (종료 코드 1): 다시 계산한")
    assert "핀) 확인이나 봉 받기" in note.messages[1][1] and "last.txt" in note.messages[1][1]


def test_the_backup_and_the_deepseek_check_have_korean_names_once(tmp_path):
    """G29 / G31: the DeepSeek check and the database backup are named (each once: a dict key), and the backup says
    what its exit code 1 means (a copy failed; the 14 days of older copies stay)."""
    assert {"paperbot-dscheck.service", "paperbot-backup.service"} <= set(FA.JOBS_KO)
    import inspect
    src = inspect.getsource(FA)
    assert src.count('"paperbot-dscheck.service": (') == 1 and src.count('"paperbot-backup.service": (') == 1
    note = ListNotifier()
    FA.main(["paperbot-backup.service"], env={"MONITOR_SERVICE_RESULT": "exit-code", "MONITOR_EXIT_STATUS": "1"},
            notifier=note, now_ms=T, state_dir=str(tmp_path))
    text = note.messages[0][1]
    assert text.startswith("작업 실패 · 데이터베이스 백업(08:40)\n\n오류로 끝남 (종료 코드 1): 데이터베이스 사본 하나 이상을")
    assert "sudo journalctl -u paperbot-backup -n 50" in text and "sudo systemctl start paperbot-backup" in text
