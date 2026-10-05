"""Sweep-2 fixes for the v4 specialist rooms, the debate and the staff prompts (the 'tonight' list, 2026-10-06): the
group rooms' meeting card and lead view (6), their owners' alert (7), DeepSeek money kept out of the agents' outputs
(11, D11), the debate's run facts (8) and agenda (9), stale v3 wording (10), the group experts' notes (13)."""

import json

from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.config import REEL_NAME
from test_agents_v4 import LEAD, V4World
from test_rooms import HOUR, QUIET, QueueRunner, team_answer


def _last_decision(w):
    return w.rounds()[-1]["decision"]


# ------------------------------------------------------------------ 6: the group rooms' card and lead view
def test_reel_room_card_says_its_own_accounts_and_its_lead_reads_the_groups(tmp_path):
    w = V4World(tmp_path)
    w.trade("N17_KC_RSI@15m", 500.0, QUIET - HOUR)          # the 36's money must not appear on the reel's card
    w.ds_losses(f"{REEL_NAME}@5m", 3)
    runner = QueueRunner({"spec_reel_5m": [team_answer("r")], "team_lead": [LEAD]})
    w.tick(runner, QUIET)
    s = _last_decision(w)["summary_ko"]
    assert "최근 24시간" not in s and "+500" not in s
    assert "이 방 계좌(코드 집계, 시작부터): 1개, 끝난 거래 3건, 파산 0개, 손익 -63.00 USDT" in s
    lead = [c for c in runner.calls if c["role"] == "team_lead"][0]["packet"]
    assert set(lead["board"]) <= {"meta", "groups", "error"} and "groups" in lead["board"]


def test_deepseek_room_card_has_counts_and_no_money(tmp_path):
    w = V4World(tmp_path)
    w.ds_losses("F3_BOS@15m", 6)
    runner = QueueRunner({"spec_ds_structure": [team_answer("s")], "team_lead": [LEAD]})
    w.tick(runner, QUIET)
    s = _last_decision(w)["summary_ko"]
    assert "이 방 계좌(코드 집계, 시작부터): 2개, 끝난 거래 6건, 파산 0개" in s
    assert "USDT" not in s and "손익" not in s and "최근 24시간" not in s


# ------------------------------------------------------------------ 7: the group rooms' owners' alert
def _flag_lead(text):
    return {**LEAD, "flag_owners": {"level": "WARN", "text": text}}


def test_group_rooms_share_one_alert_a_day_and_leave_the_36s_count_alone(tmp_path):
    from paperbot.notify import ListNotifier
    w = V4World(tmp_path)
    w.ds_losses("F3_BOS@15m", 6)
    w.ds_losses("F16_FIB382@15m", 6)
    runner = QueueRunner({"spec_ds_structure": [team_answer("s")], "spec_ds_reversal": [team_answer("r")],
                          "team_lead": [_flag_lead("구조 방 손실이 6건 이어짐"), _flag_lead("반전 방 손실이 6건 이어짐")]})
    n = ListNotifier()
    out = w.tick(runner, QUIET, notifier=n)
    assert sorted(r["room_id"] for r in out["rounds"]) == ["team:ds_reversal", "team:ds_structure"]
    assert len(n.messages) == 1
    day = R.kst_day(QUIET)
    cur = w.cursors()
    assert cur[f"flag_owners:group:{day}"] == "1" and f"flag_owners:{day}" not in cur
    assert any("다섯 방 합쳐 하루 1번" in m["text"] for room in ("team:ds_structure", "team:ds_reversal")
               for m in w.messages(room))


def test_a_deepseek_alert_with_money_is_kept_as_a_room_note(tmp_path):
    from paperbot.agents import dsmoney as DM
    from paperbot.notify import ListNotifier
    assert DM.DS_MONEY_STRICT is True
    for t in ("손실 -120 USDT", "$35 잃음", "35달러", "USDT 12", "１２０ ＵＳＤＴ"):
        assert DM.has_money(t), t
    for t in ("손실 6건 연속", "승률 0.3", "파산 2개", "ROE -12%"):
        assert not DM.has_money(t), t
    w = V4World(tmp_path)
    w.ds_losses("F3_BOS@15m", 6)
    runner = QueueRunner({"spec_ds_structure": [team_answer("s")], "team_lead": [_flag_lead("구조 방 -120 USDT 손실")]})
    n = ListNotifier()
    w.tick(runner, QUIET, notifier=n)
    assert n.messages == []
    notes = R.room_notes(w.agents, "team:ds_structure", 5)
    assert len(notes) == 1 and "알림 대신 메모" in notes[0]["text"] and "-120 USDT" in notes[0]["text"]
    assert f"flag_owners:group:{R.kst_day(QUIET)}" not in w.cursors()


def test_the_reel_room_alert_may_name_its_money(tmp_path):
    from paperbot.notify import ListNotifier
    w = V4World(tmp_path)
    w.ds_losses(f"{REEL_NAME}@5m", 3)
    runner = QueueRunner({"spec_reel_5m": [team_answer("r")], "team_lead": [_flag_lead("릴스 -63 USDT")]})
    n = ListNotifier()
    w.tick(runner, QUIET, notifier=n)
    assert len(n.messages) == 1 and "-63 USDT" in n.messages[0][1]
    assert "딥시크 방 알림에는 금액을 쓰지 않음(개수만)" in RM.system_prompt("team_lead", "lead")
