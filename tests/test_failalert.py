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
    assert [(lv, t.split(":")[0]) for lv, t in note.messages] == [
        (WARN, "[작업 실패] 체크포인트 판정"), (WARN, "[작업 실패] 에이전트 회의"), (WARN, "[작업 실패] 체크포인트 판정")]
    text = note.messages[0][1]
    assert "오류로 끝남, 종료 코드 1 (paperbot-checkpoint.service)" in text
    assert "sudo journalctl -u paperbot-checkpoint.service -n 50 --no-pager" in text
    assert "sudo systemctl reset-failed paperbot-checkpoint.service" in text and "매시 35분" in text
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
    assert "매달 재검사: 시간 제한을 넘김 (paperbot-labmonthly.service)" in note.messages[1][1]


def test_only_a_unit_name_is_accepted(tmp_path):
    note = ListNotifier()
    for bad in ("../x", "a b", ".hidden"):
        assert FA.main([bad], env={}, notifier=note, now_ms=T, state_dir=str(tmp_path)) == 2
    assert note.messages == [] and not os.listdir(tmp_path)
