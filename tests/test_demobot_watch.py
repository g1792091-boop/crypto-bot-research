"""Demo lab outside watch (demobot/watch.py, CONTRACT.md 8.8) with fake times, a fake systemctl and a fake Telegram.

Rules: dead (no tick for 45 min, or demobot-live inactive/failed), rank (no ranking for 3 h, or the last run failed),
backup (no good backup for 36 h, only once one was expected). At most one warning per what every 3 hours, one clear
when it recovers, a failed send tried again at the next check. systemctl missing = unknown, never a problem.
snap/watch.json per the contract; exit 1 only when the state cannot be written; never raises; no token in a log."""
import json
import subprocess

import pytest

from demobot import notify as N
from demobot import watch as W

T0 = 1_791_590_400_000          # 2026-10-10 00:00 UTC = 09:00 KST
MIN = 60_000
H = 3_600_000
TOKEN = "9" * 10 + ":" + "TESTONLY" * 5
MONO = 1_000_000.0              # seconds since boot "now"


class SC:
    """A fake systemctl: ``live`` (is-active answer or None), the rank unit's ActiveState/Result, the watch timer's
    start (minutes ago, or None). ``None`` everywhere = no systemd."""

    def __init__(self, live="active", rank_state="inactive", rank_result="success", watch_min=24 * 60):
        self.live, self.rank_state, self.rank_result, self.watch_min = live, rank_state, rank_result, watch_min
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        if args[0] == "is-active":
            return self.live
        if args[0] == "show" and args[1] == W.RANK_UNIT:
            if self.rank_state is None:
                return None
            return f"ActiveState={self.rank_state}\nResult={self.rank_result}"
        if args[0] == "show" and args[1] == W.WATCH_TIMER:
            if self.watch_min is None:
                return None
            return f"ActiveEnterTimestampMonotonic={int((MONO - self.watch_min * 60) * 1e6)}"
        return None


NO_SYSTEMD = dict(live=None, rank_state=None, watch_min=None)


class TG:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, token, chat, text):
        if self.fail:
            raise N.TelegramError(f"HTTP 502: Bad Gateway at https://api.telegram.org/bot{token}/sendMessage",
                                  transient=True)
        self.sent.append(text)


class World:
    def __init__(self, tmp_path):
        self.snap = tmp_path / "snap"
        self.snap.mkdir()
        self.state = tmp_path / "lib" / "watch_state.json"
        self.logs = []

    def old_state(self, days=30):
        """A watch that has been running for a while (its first check long ago)."""
        self.state.parent.mkdir(exist_ok=True)
        self.state.write_text(json.dumps({"first_check_ms": T0 - days * 24 * H}), encoding="utf-8")

    def write(self, name, obj):
        (self.snap / name).write_text(json.dumps(obj), encoding="utf-8")

    def files(self, now=T0, tick_min=5, live_start_h=100, rank_min=30, backup_h=10, backup_err=None):
        self.write("status.json", {"last_tick_ms": now - tick_min * MIN if tick_min is not None else None,
                                   "live_start_ms": now - live_start_h * H if live_start_h is not None else None})
        if rank_min is not None:
            self.write("rank_meta.json", {"generated_ms": now - rank_min * MIN})
        if backup_h is not None or backup_err:
            self.write("backup.json", {"last_ok_ms": now - backup_h * H if backup_h is not None else None,
                                       "last_try_ms": now - H, "bytes": 1234, "tables": {"views": 3},
                                       "encrypted": False, "error_ko": backup_err})

    def run(self, now=T0, sc=None, tg=None, token=TOKEN, chat="-100777"):
        self.tg = tg if tg is not None else TG()
        rc = W.run(str(self.snap), str(self.state), token, chat, now_ms=now, sc=sc or SC(), send=self.tg,
                   mono=lambda: MONO, log=self.logs.append)
        return rc

    def watch_json(self):
        return json.loads((self.snap / "watch.json").read_text(encoding="utf-8"))

    def items(self):
        return {i["what"]: i for i in self.watch_json()["items"]}


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_all_fine_sends_nothing_and_writes_watch_json(world):
    world.files()
    assert world.run() == 0 and world.tg.sent == []
    w = world.watch_json()
    assert w["checked_ms"] == T0 and w["ok"] is True and [i["what"] for i in w["items"]] == ["dead", "rank", "backup"]
    assert all(set(i) == {"what", "ok", "detail_ko"} for i in w["items"])
    it = world.items()
    assert it["dead"]["detail_ko"] == "마지막 계산 10/10 08:55 (5분 전)"
    assert it["rank"]["detail_ko"] == "마지막 순위표 10/10 08:30 (30분 전)"
    assert it["backup"]["detail_ko"] == "마지막 백업 10/09 23:00 (10시간 전)"
    st = json.loads(world.state.read_text(encoding="utf-8"))
    assert st["checked_ms"] == T0 and st["first_check_ms"] == T0


def test_dead_warns_once_per_3_hours_then_clears_once(world):
    world.files(tick_min=50)
    assert world.run() == 0
    assert len(world.tg.sent) == 1
    msg = world.tg.sent[0]
    assert msg == ("⚠ 데모 랩 경고 · 엔진이 멈춤 (15분 계산이 안 돎)\n\n마지막 계산 10/10 08:10 (50분 전)\n"
                   "45분 넘게 새 계산이 없음\n기록: journalctl -u demobot-live -n 40 --no-pager\n"
                   "규칙봇과는 별개 · 주문 없음\n10/10 09:00")                  # the rule bot's short lines
    assert world.items()["dead"]["detail_ko"] == ("마지막 계산 10/10 08:10 (50분 전) · 45분 넘게 새 계산이 없음 · "
                                                  "기록: journalctl -u demobot-live -n 40 --no-pager")  # watch.json: one line
    assert world.watch_json()["ok"] is False and world.items()["dead"]["ok"] is False
    for k in range(1, 18):                                                  # every 10 minutes for 2 h 50 min
        world.files(now=T0 + k * 10 * MIN, tick_min=50 + k * 10)
        assert world.run(now=T0 + k * 10 * MIN) == 0 and world.tg.sent == [], k
    world.files(now=T0 + 3 * H, tick_min=230)
    world.run(now=T0 + 3 * H)
    assert len(world.tg.sent) == 1 and "3시간 50분 전" in world.tg.sent[0]   # again after 3 hours
    world.files(now=T0 + 3 * H + 10 * MIN, tick_min=2)
    world.run(now=T0 + 3 * H + 10 * MIN)
    assert world.tg.sent == ["✅ 데모 랩 회복 · 엔진이 다시 돎\n\n마지막 계산 10/10 12:08 (2분 전)\n10/10 12:10"]
    world.files(now=T0 + 3 * H + 20 * MIN, tick_min=2)
    world.run(now=T0 + 3 * H + 20 * MIN)
    assert world.tg.sent == []                                               # the clear only once
    world.files(now=T0 + 4 * H, tick_min=60)                                # broken again within 3 h of the last
    world.run(now=T0 + 4 * H)
    assert world.tg.sent == []
    world.files(now=T0 + 6 * H, tick_min=180)
    world.run(now=T0 + 6 * H)
    assert len(world.tg.sent) == 1


@pytest.mark.parametrize("state", ["inactive", "failed"])
def test_dead_when_the_engine_service_is_off_even_with_a_fresh_tick(world, state):
    world.files(tick_min=1)
    world.run(sc=SC(live=state))
    assert len(world.tg.sent) == 1 and f"엔진 서비스(demobot-live)가 꺼져 있음 ({state})" in world.tg.sent[0]
    assert "on.sh" in world.tg.sent[0]


@pytest.mark.parametrize("state", ["active", "activating", "deactivating", "reloading"])
def test_a_restarting_engine_is_not_dead_by_itself(world, state):
    world.files(tick_min=10)
    world.run(sc=SC(live=state))
    assert world.tg.sent == [] and world.items()["dead"]["ok"]


def test_a_crash_loop_is_still_dead_after_45_minutes(world):
    world.files(tick_min=46)
    world.run(sc=SC(live="activating"))
    assert len(world.tg.sent) == 1 and "45분 넘게" in world.tg.sent[0]


def test_just_turned_on_waits_for_the_first_tick(world):
    world.files(tick_min=2 * 24 * 60)                                       # off for two days, on.sh 10 min ago
    world.run(sc=SC(watch_min=10))
    assert world.tg.sent == [] and world.items()["dead"]["ok"]
    assert "마지막 계산 10/08 09:00 (2일 전)" in world.items()["dead"]["detail_ko"]
    world.files(now=T0 + 40 * MIN, tick_min=2 * 24 * 60 + 40)
    world.run(now=T0 + 40 * MIN, sc=SC(watch_min=50))                      # 50 min after on.sh, still no tick
    assert len(world.tg.sent) == 1 and "엔진이 멈춤" in world.tg.sent[0]


def test_no_systemd_is_unknown_not_a_problem(world):
    world.files()
    assert world.run(sc=SC(**NO_SYSTEMD)) == 0 and world.tg.sent == []
    assert world.watch_json()["ok"] is True
    world.files(tick_min=60)                                                # the tick rule still works without it
    world.run(sc=SC(**NO_SYSTEMD))
    assert len(world.tg.sent) == 1 and "엔진이 멈춤" in world.tg.sent[0]


def test_missing_status_file(world):
    assert world.run(sc=SC(**NO_SYSTEMD)) == 0 and world.tg.sent == []
    it = world.items()
    assert it["dead"]["ok"] and "확인 못 함" in it["dead"]["detail_ko"]
    assert it["rank"]["ok"] and it["backup"]["ok"]
    world.run(sc=SC(watch_min=60))                                          # the watch ran an hour, never a tick
    assert len(world.tg.sent) == 1 and "아직 계산 기록 없음" in world.tg.sent[0]


def test_rank_rules(world):
    world.files(rank_min=3 * 60 + 5)
    world.run()
    assert len(world.tg.sent) == 1 and world.tg.sent[0].startswith("⚠ 데모 랩 경고 · 순위표가 안 만들어짐")
    assert "3시간 넘게" in world.tg.sent[0]
    world.files(rank_min=20)
    world.run(now=T0 + 10 * MIN, sc=SC(rank_state="failed", rank_result="exit-code"))
    assert world.tg.sent == []                                              # same what within 3 h: quiet
    assert "실패함 (exit-code)" in world.items()["rank"]["detail_ko"]
    world.run(now=T0 + 20 * MIN)
    assert world.tg.sent == ["✅ 데모 랩 회복 · 순위표가 다시 만들어짐\n\n마지막 순위표 10/10 08:40 (40분 전)\n10/10 09:20"]


def test_rank_failed_run_and_missing_ranking(world, tmp_path):
    world.files(rank_min=10)
    world.run(sc=SC(rank_state="inactive", rank_result="oom-kill"))
    assert len(world.tg.sent) == 1 and "oom-kill" in world.tg.sent[0] and "journalctl -u demobot-rank" in world.tg.sent[0]
    (tmp_path / "b").mkdir()
    other = World(tmp_path / "b")
    other.files(rank_min=None, live_start_h=2)                              # no ranking yet, live for 2 h: fine
    other.run(sc=SC(watch_min=None))
    assert other.tg.sent == [] and other.items()["rank"]["detail_ko"] == "아직 순위표 없음"
    other.files(rank_min=None, live_start_h=4)
    other.run(sc=SC(watch_min=None))
    assert len(other.tg.sent) == 1 and "아직 순위표 없음" in other.tg.sent[0]


def test_rank_unknown_without_any_time(world):
    world.files(rank_min=None, live_start_h=None)
    world.run(sc=SC(watch_min=None))
    assert world.tg.sent == [] and "확인 못 함" in world.items()["rank"]["detail_ko"]


def test_backup_rules(world):
    world.old_state()
    world.files(backup_h=None, live_start_h=10)                             # running 10 h: no backup expected yet
    world.run()
    assert world.tg.sent == [] and world.items()["backup"]["detail_ko"] == "아직 첫 백업 전 (매일 04:40)"
    world.files(backup_h=None, live_start_h=40)                             # running 40 h, never a backup
    world.run(now=T0)
    assert len(world.tg.sent) == 1 and world.tg.sent[0].startswith("⚠ 데모 랩 경고 · 밤 백업이 안 됨")
    assert "아직 성공한 백업 없음" in world.tg.sent[0]
    world.files(now=T0 + 3 * H, backup_h=37, backup_err="텔레그램이 백업 파일을 받지 않았습니다 (HTTP 400: chat not found)")
    world.run(now=T0 + 3 * H)
    msg = world.tg.sent[0]
    assert "마지막 백업 10/08 23:00 (37시간 전)" in msg and "마지막 오류: 텔레그램이 백업 파일을" in msg
    assert "journalctl -u demobot-backup" in msg
    world.files(now=T0 + 4 * H, backup_h=0)
    world.run(now=T0 + 4 * H)
    assert world.tg.sent[0].startswith("✅ 데모 랩 회복 · 밤 백업이 다시 됨")


def test_backup_not_expected_right_after_the_update_that_installed_it(world):
    world.files(backup_h=None, live_start_h=24 * 20)                        # round 2 ran 20 days; no backup.json yet
    world.run()                                                             # the first check ever (empty state)
    assert world.tg.sent == [] and world.items()["backup"]["ok"]
    world.files(now=T0 + 30 * H, backup_h=None, live_start_h=24 * 20 + 30)
    world.run(now=T0 + 30 * H)
    assert world.tg.sent == []
    world.files(now=T0 + 37 * H, backup_h=None, live_start_h=24 * 20 + 37)
    world.run(now=T0 + 37 * H)
    assert len(world.tg.sent) == 1 and "밤 백업이 안 됨" in world.tg.sent[0]


def test_backup_check_waits_an_hour_after_the_watch_started_and_skips_without_times(world):
    world.old_state()
    world.files(backup_h=50)
    world.run(sc=SC(watch_min=20))                                          # on.sh 20 min ago: catch-up pending
    assert world.tg.sent == [] and "1시간 뒤부터" in world.items()["backup"]["detail_ko"]
    world.run(sc=SC(watch_min=70))
    assert len(world.tg.sent) == 1
    other_snap = world.snap
    (other_snap / "backup.json").unlink()
    world.write("status.json", {"last_tick_ms": T0 - MIN})                  # no live start, no backup: skipped
    world.run(now=T0 + 4 * H, sc=SC())
    assert "확인 못 함" in world.items()["backup"]["detail_ko"]


def test_a_failed_send_is_tried_again_at_the_next_check_and_logs_no_token(world):
    world.files(tick_min=60)
    world.run(tg=TG(fail=True))
    st = json.loads(world.state.read_text(encoding="utf-8"))["items"]["dead"]
    assert st["bad"] is True and not st.get("warned") and st.get("last_warn_ms") is None
    logs = "\n".join(world.logs)
    assert "not sent" in logs and TOKEN not in logs and TOKEN.split(":")[1] not in logs and "<token>" in logs
    world.files(now=T0 + 10 * MIN, tick_min=70)
    world.run(now=T0 + 10 * MIN)
    assert len(world.tg.sent) == 1 and st["since_ms"] == T0
    # a clear that fails is tried again too
    world.files(now=T0 + 20 * MIN, tick_min=1)
    world.run(now=T0 + 20 * MIN, tg=TG(fail=True))
    world.run(now=T0 + 30 * MIN)
    assert world.tg.sent and world.tg.sent[0].startswith("✅ 데모 랩 회복 · 엔진이 다시 돎")


class TG2:
    """A fake Telegram where some chats fail."""

    def __init__(self, failing=()):
        self.sent, self.failing = [], set(failing)

    def __call__(self, token, chat, text):
        if chat in self.failing:
            raise N.TelegramError("HTTP 403: Forbidden: bot was blocked by the user")
        self.sent.append((chat, text.split("\n")[0]))


def test_every_listed_chat_is_warned_and_a_missed_one_gets_it_later_without_doubles(world):
    world.files(tick_min=60)
    world.run(chat="111,222", tg=TG2(failing={"222"}))
    assert world.tg.sent == [("111", "⚠ 데모 랩 경고 · 엔진이 멈춤 (15분 계산이 안 돎)")]
    st = json.loads(world.state.read_text(encoding="utf-8"))["items"]["dead"]
    assert st["warned"] is True and st["last_warn_ms"] == T0 and st["retry"]["chats"] == ["222"]
    assert "not sent to 222" in "\n".join(world.logs) and TOKEN not in "\n".join(world.logs)
    world.files(now=T0 + 10 * MIN, tick_min=70)
    world.run(now=T0 + 10 * MIN, chat="111,222", tg=TG2(failing={"222"}))  # still blocked: 111 not sent again
    assert world.tg.sent == []
    world.files(now=T0 + 20 * MIN, tick_min=80)
    world.run(now=T0 + 20 * MIN, chat="111,222", tg=TG2())
    assert world.tg.sent == [("222", "⚠ 데모 랩 경고 · 엔진이 멈춤 (15분 계산이 안 돎)")]
    assert json.loads(world.state.read_text(encoding="utf-8"))["items"]["dead"]["retry"] is None
    world.files(now=T0 + 30 * MIN, tick_min=1)
    world.run(now=T0 + 30 * MIN, chat="111,222", tg=TG2())
    assert world.tg.sent == [("111", "✅ 데모 랩 회복 · 엔진이 다시 돎"), ("222", "✅ 데모 랩 회복 · 엔진이 다시 돎")]


def test_a_missed_warning_is_dropped_once_the_problem_is_gone(world):
    world.files(tick_min=60)
    world.run(chat="111,222", tg=TG2(failing={"222"}))
    world.files(now=T0 + 10 * MIN, tick_min=1)                               # fixed before 222 could be told
    world.run(now=T0 + 10 * MIN, chat="111,222", tg=TG2())
    assert world.tg.sent == [("111", "✅ 데모 랩 회복 · 엔진이 다시 돎"), ("222", "✅ 데모 랩 회복 · 엔진이 다시 돎")]
    world.files(now=T0 + 20 * MIN, tick_min=1)
    world.run(now=T0 + 20 * MIN, chat="111,222", tg=TG2())
    assert world.tg.sent == []


def test_no_telegram_settings_keeps_trying_quietly(world):
    world.files(tick_min=60)
    assert world.run(token="", chat="") == 0 and world.tg.sent == []
    assert "DEMOBOT_TG_TOKEN / DEMOBOT_TG_CHAT empty" in "\n".join(world.logs)
    assert world.watch_json()["ok"] is False


def test_several_problems_each_get_their_message(world):
    world.old_state()
    world.files(tick_min=60, rank_min=4 * 60, backup_h=40)
    world.run(sc=SC(live="failed"))
    assert [t.split("\n")[0] for t in world.tg.sent] == ["⚠ 데모 랩 경고 · 엔진이 멈춤 (15분 계산이 안 돎)",
                                                          "⚠ 데모 랩 경고 · 순위표가 안 만들어짐",
                                                          "⚠ 데모 랩 경고 · 밤 백업이 안 됨"]


def test_cannot_write_the_state_exits_1_but_still_writes_watch_json(world, tmp_path):
    world.files()
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    rc = W.run(str(world.snap), str(blocker / "state.json"), TOKEN, "-1", now_ms=T0, sc=SC(), send=TG(),
               mono=lambda: MONO, log=world.logs.append)
    assert rc == 1 and world.watch_json()["checked_ms"] == T0
    assert "cannot write its state" in "\n".join(world.logs)


def test_broken_files_never_raise(world):
    (world.snap / "status.json").write_text("{not json")
    (world.snap / "rank_meta.json").write_text("[1, 2]")
    (world.snap / "backup.json").write_text('{"last_ok_ms": "soon", "error_ko": 5}')
    world.state.parent.mkdir()
    world.state.write_text('{"items": {"dead": "x", "rank": [1]}, "first_check_ms": "?"}')
    assert world.run(sc=SC(live="weird output")) == 0
    assert len(world.watch_json()["items"]) == 3


def test_snap_folder_missing_still_saves_the_state(world, tmp_path):
    rc = W.run(str(tmp_path / "nowhere" / "snap"), str(world.state), TOKEN, "-1", now_ms=T0, sc=SC(**NO_SYSTEMD),
               send=TG(), mono=lambda: MONO, log=world.logs.append)
    assert rc == 0 and world.state.exists()


def test_evaluate_survives_a_slip(monkeypatch):
    monkeypatch.setattr(W, "check_rank", lambda f: 1 / 0)
    items = W.evaluate({"now_ms": T0})
    assert [i["what"] for i in items] == ["dead", "rank", "backup"]
    assert items[1] == {"what": "rank", "ok": True, "detail_ko": "확인 못 함 (ZeroDivisionError)", "known": False,
                        "lines": ["확인 못 함 (ZeroDivisionError)"]}


# ---------------------------------------------------------------- the systemd readers
def test_systemctl_wrapper_treats_missing_or_silent_systemctl_as_unknown():
    def missing(*a, **k):
        raise FileNotFoundError("systemctl")

    def hangs(*a, **k):
        raise subprocess.TimeoutExpired("systemctl", 20)

    def silent(*a, **k):
        return subprocess.CompletedProcess(a[0], 1, stdout="", stderr="Failed to connect to bus: Host is down")

    def ok(argv, **k):
        assert argv[:2] == ["systemctl", "--no-pager"] and k["timeout"] == 20
        return subprocess.CompletedProcess(argv, 3, stdout="inactive\n", stderr="")
    assert W.systemctl(["is-active", "x"], run=missing) is None
    assert W.systemctl(["is-active", "x"], run=hangs) is None
    assert W.systemctl(["is-active", "x"], run=silent) is None
    assert W.systemctl(["is-active", "x"], run=ok) == "inactive"


def test_unit_readers():
    assert W.unit_state(lambda a: "active\n", "u") == "active"
    assert W.unit_state(lambda a: "System has not been booted", "u") is None
    assert W.unit_state(lambda a: None, "u") is None
    assert W.unit_props(lambda a: "Result=exit-code\nActiveState=failed\njunk", "u", ("Result",)) == {
        "Result": "exit-code", "ActiveState": "failed"}
    us = int((MONO - 600) * 1e6)
    assert W._since_ms({"X": str(us)}, "X", T0, MONO) == T0 - 600_000
    assert W._since_ms({"X": "0"}, "X", T0, MONO) is None                  # never entered
    assert W._since_ms({"X": "abc"}, "X", T0, MONO) is None
    assert W._since_ms({}, "X", T0, MONO) is None
    assert W._since_ms({"X": str(int((MONO + 3600) * 1e6))}, "X", T0, MONO) is None   # from another boot


def test_gather_asks_the_right_units(world):
    world.files()
    sc = SC()
    f = W.gather(str(world.snap), T0, sc, mono=lambda: MONO)
    assert ["is-active", "demobot-live.service"] in sc.calls
    assert ["show", "demobot-rank.service", "--property=ActiveState,Result"] in sc.calls
    assert ["show", "demobot-watch.timer", "--property=ActiveEnterTimestampMonotonic"] in sc.calls
    assert f["last_tick_ms"] == T0 - 5 * MIN and f["live_state"] == "active" and f["rank_result"] == "success"
    assert f["watch_since_ms"] == T0 - 24 * H


def test_ago():
    assert W.ago(0) == "0분" and W.ago(59 * MIN) == "59분" and W.ago(60 * MIN) == "1시간"
    assert W.ago(3 * H + 20 * MIN) == "3시간 20분" and W.ago(50 * H) == "2일 2시간" and W.ago(48 * H) == "2일"


def test_main_uses_the_environment(world, monkeypatch):
    world.files()
    monkeypatch.setenv("DEMOBOT_SNAP", str(world.snap))
    monkeypatch.setenv("DEMOBOT_WATCH_STATE", str(world.state))
    monkeypatch.setenv("DEMOBOT_TG_TOKEN", TOKEN)
    monkeypatch.setenv("DEMOBOT_TG_CHAT", "-100777")
    monkeypatch.setattr(W, "systemctl", lambda args, run=None: None)
    sent = []
    monkeypatch.setattr(N, "send_message", lambda t, c, x: sent.append(x))
    run = W.run       # the fixture's files are written at T0: check at T0, not at today's wall clock
    monkeypatch.setattr(W, "run", lambda *a, **k: run(*a, now_ms=T0, mono=lambda: MONO, **k))
    assert W.main(["--env-file", "/nonexistent"]) == 0
    assert world.state.exists() and (world.snap / "watch.json").exists() and sent == []
