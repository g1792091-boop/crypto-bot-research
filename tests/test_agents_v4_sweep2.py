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
