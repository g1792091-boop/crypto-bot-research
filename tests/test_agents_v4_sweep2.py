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
    # the note keeps the words, not the amount (the next meeting's packet reads the room notes back)
    assert len(notes) == 1 and "알림 대신 메모" in notes[0]["text"] and "구조 방 (금액 생략) 손실" in notes[0]["text"]
    assert not DM.has_money(notes[0]["text"])
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


# ------------------------------------------------------------------ 11: DeepSeek money strict (D11)
def _money_keys(obj, path=""):
    """Every money number (dsmoney.is_money_key: MONEY_KEYS, any pnl / wallet / equity / usdt key) at any depth."""
    from paperbot.agents import dsmoney as DM
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if DM.is_money_key(k) and not isinstance(v, (dict, list)):
                out.append(f"{path}.{k}")
            out += _money_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _money_keys(v, f"{path}.{i}")
    return out


def test_the_debate_packet_carries_no_deepseek_money(tmp_path):
    from paperbot.agents import debate_packet as P
    from test_debate import NOW, make_world
    w = make_world(tmp_path, NOW, days=3, per_day=60, v4=True)
    keys = [k for k, _ko in P.TOPICS]
    gc = P.build(w["paper"], w["daily"], None, None, NOW, round_no=keys.index("groups"))["packet"]["groups_compare"]
    # the DeepSeek cells (the coin flips next to them are not DeepSeek: as before)
    assert _money_keys({"all": gc["ds200"]["all"],
                        "tf": {tf: c["group"] for tf, c in gc["ds200"]["by_timeframe"].items()}}) == []
    assert "net_pnl" in gc["core"]["all"] and "median_wallet" in gc["reel"]["all"]      # the other groups as before
    cells = [c["group"] for c in gc["ds200"]["by_timeframe"].values()]
    assert cells and all(c["vs_coin_flip"] in ("above", "below", "equal", None) for c in cells)
    assert set(cells[0]) <= {"accounts", "trades", "trades_per_account", "win_rate", "busts", "small_sample",
                             "vs_coin_flip"}
    assert any("돈 숫자를 말하지 않음" in n for n in gc["notes"])
    df = P.build(w["paper"], w["daily"], None, None, NOW, round_no=keys.index("ds_families"))["packet"]["ds_families"]
    assert _money_keys({k: v for k, v in df.items() if k != "coin_flip_by_timeframe"}) == []
    assert df["ds200_all"]["accounts"] == 171 and "win_rate" in df["ds200_all"]
    assert "딥시크는 돈 숫자를 말하지 않음 (개수·비율만)" in open(
        "paperbot/agents/prompts3/debate_room.md", encoding="utf-8").read()


# ------------------------------------------------------------------ 8: the debate is told the run's rules
def test_the_debate_prompt_has_the_v4_facts_and_the_packet_the_verdict_date(tmp_path):
    from paperbot.agents import debate as D
    from paperbot.agents import debate_packet as P
    from paperbot.agents import facts as F
    from test_debate import NOW, make_world
    s = D.system_text()
    assert "## 이번 실행의 규칙" in s and F.run_facts_block() in s and F.exits_block() in s
    assert "50%×50배" in s and "30%×30배 → 20%×20배" in s and "증거금 = 레버리지 %" in s
    assert "342개 설정 중 통과 0개" in s and "자기 청산이라 정상" in s and F.method_text() in s
    assert s == D.system_text() and P.estimate_tokens(s) < 4500         # the same bytes every round (cached)
    w = make_world(tmp_path, NOW, days=3, per_day=20, v4=True)
    cp = P.build(w["paper"], w["daily"], None, None, NOW)["packet"]["meta"]["checkpoint"]
    assert cp["verdict_exists"] is False and cp["next"].endswith("09:00 KST")     # no checkpoint.db yet


# ------------------------------------------------------------------ 13: the group experts' note
def test_a_group_experts_note_is_kept_and_read_back_next_meeting(tmp_path):
    w = V4World(tmp_path)
    w.ds_losses("F3_BOS@15m", 6)
    note = "F3_BOS 15분봉 손실 6건이 모두 추세 반대 진입: 다음 묶음에서 같은 태그 비율을 봄"
    runner = QueueRunner({"spec_ds_structure": [{**team_answer("s"), "note": note}], "team_lead": [LEAD]})
    w.tick(runner, QUIET)
    sysp = runner.calls[0]["system"]
    assert '"note": "다음 회의에 남길 방 메모' in sysp
    assert "다음 회의에 남길 방 메모" not in RM.system_prompt("pnl_reviewer", "team")   # the 36's team rooms: unchanged
    notes = R.room_notes(w.agents, "team:ds_structure", 5)
    assert [n["text"] for n in notes] == [note]
    assert "방 메모 1건" in _last_decision(w)["summary_ko"]
    assert any(m["kind"] == "action" and "메모" in m["text"] for m in w.messages("team:ds_structure"))
    # the next meeting of the room reads it back (packet ``notes``)
    w.ds_losses("F9_FVG@1h", 6, t=QUIET + 26 * HOUR)
    r2 = QueueRunner({"spec_ds_structure": [team_answer("s")], "team_lead": [LEAD]})
    w.tick(r2, QUIET + 26 * HOUR)
    assert [n["text"] for n in r2.calls[0]["packet"]["notes"]] == [note]
    # a DeepSeek room's note keeps its words, not a money amount (D11)
    w.ds_losses("F3_BOS@15m", 6, t=QUIET + 52 * HOUR)
    r3 = QueueRunner({"spec_ds_structure": [{**team_answer("s"), "note": "F3_BOS 손실 합 -135 USDT"}],
                      "team_lead": [LEAD]})
    w.tick(r3, QUIET + 52 * HOUR)
    assert R.room_notes(w.agents, "team:ds_structure", 1)[0]["text"] == "F3_BOS 손실 합 (금액 생략)"
    # a note in a 36 team room's answer is dropped (only the group rooms have the note action there)
    assert "note" not in RM.check_team({**team_answer("x"), "note": "n"}, {"room": {"room_id": "team:risk"}})[0]


# ------------------------------------------------------------------ 9: the agenda jumps only on a new event
def _bust(paper, aid):
    import sqlite3
    con = sqlite3.connect(paper)
    eng = json.loads(con.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()[0])
    eng["engines"].setdefault(aid, {})["bust"] = True
    con.execute("UPDATE state SET data = ? WHERE k = 'accounts'", (json.dumps(eng),))
    con.commit()
    con.close()


def test_one_bust_jumps_the_agenda_once_then_it_rotates(tmp_path):
    from paperbot.agents import debate_packet as P
    from debate_world import make_world
    from test_debate import NOW
    w = make_world(tmp_path, NOW, days=3, per_day=20)
    _bust(w["paper"], "N01_ST_EMA@1h")
    first = P.build(w["paper"], w["daily"], None, None, NOW, round_no=0)          # no marks yet: it jumps
    assert first["topic"] == "risk" and "파산한 계좌(매매법·동전) 1개" in first["why"]
    seen = first["marks"]
    assert seen["busts"] == 1 and seen["start"] is not None
    topics = [P.build(w["paper"], w["daily"], None, None, NOW, round_no=i, seen=seen)["topic"] for i in range(1, 6)]
    assert topics == [k for k, _ko in P.TOPICS[1:6]]                                # plain rotation after the jump
    later = P.build(w["paper"], w["daily"], None, None, NOW, round_no=1, seen=seen)
    assert later["topic"] == P.TOPICS[1][0] and later["packet"]["unusual"] == []
    _bust(w["paper"], "V45_AMB@15m")                                                # a NEW bust: one more jump
    again = P.build(w["paper"], w["daily"], None, None, NOW, round_no=1, seen=seen)
    assert again["topic"] == "risk" and "2개" in again["why"] and again["marks"]["busts"] == 2
    assert P.build(w["paper"], w["daily"], None, None, NOW, round_no=1, seen=again["marks"])["topic"] == P.TOPICS[1][0]
    other_run = {**again["marks"], "start": 1}                                      # marks of another run: ignored
    assert P.build(w["paper"], w["daily"], None, None, NOW, round_no=1, seen=other_run)["topic"] == "risk"


def test_the_debate_service_jumps_once_for_a_bust_then_rotates(tmp_path):
    from paperbot.agents import debate as D
    from debate_world import make_world
    from test_debate import NOW, answer, make, ok_body, rows
    w = make_world(tmp_path, NOW, days=3, per_day=20)
    _bust(w["paper"], "N01_ST_EMA@1h")
    svc = make(tmp_path, w, *[ok_body(answer())] * 6)
    for _ in range(6):
        svc.clk.t += 21 * 60_000
        assert svc.tick(force=True) == "round"
    topics = [r[0] for r in rows(svc, "SELECT topic FROM debate_rounds WHERE status = 'ok' ORDER BY round_id")]
    from paperbot.agents import debate_packet as P
    assert topics[0] == P.TOPIC_KO["risk"] and topics.count(P.TOPIC_KO["risk"]) == 1, topics
    assert svc.db.get(D.AGENDA_MARKS)["busts"] == 1


def test_a_deepseek_room_packet_has_roe_and_counts_but_no_money(tmp_path):
    w = V4World(tmp_path)
    w.ds_losses("F3_BOS@15m", 6)
    runner = QueueRunner({"spec_ds_structure": [team_answer("s")], "team_lead": [LEAD]})
    w.tick(runner, QUIET)
    for c in runner.calls:                              # the specialist and the lead
        pk = c["packet"]
        assert _money_keys(pk["group_accounts"]) == [], c["role"]
        assert pk["losses"].get("recent") and _money_keys(pk["losses"]) == [], c["role"]     # win_loss had P&L
        assert _money_keys(pk["board"]["groups"]["ds200"]) == [], c["role"]
        assert "net_pnl" in pk["board"]["groups"]["core"] or "core" not in pk["board"]["groups"]
    ga = runner.calls[0]["packet"]["group_accounts"]
    f3 = [d for d in ga["definitions"] if d["strategy"] == "F3_BOS"][0]
    from paperbot.config import V3_INITIAL
    want = round(100 * sum(-20.0 - k for k in range(6)) / V3_INITIAL, 2)
    assert f3["timeframes"]["15m"]["roe_pct"] == want and f3["trades"] == 6 and f3["win_rate"] == 0.0
    assert "돈 숫자" in ga["money_note"] and ga["costs"]["F3_BOS"]["15m"]["trades"] == 6
    # the reel room keeps its money (D10)
    (tmp_path / "reel").mkdir()
    w2 = V4World(tmp_path / "reel")
    w2.ds_losses(f"{REEL_NAME}@5m", 3)
    r2 = QueueRunner({"spec_reel_5m": [team_answer("r")], "team_lead": [LEAD]})
    w2.tick(r2, QUIET)
    assert r2.calls[0]["packet"]["group_accounts"]["definitions"][0]["pnl"] == -63.0
