"""The agent staff at the paper v4 restart (owners 2026-10-05): the run's facts from one source (M5), the groups kept
apart in every owner-facing count (M4), the levrule population (M6), the 36's rooms untouched by DeepSeek and the
reel (M7), old-run debate claims voided (M11), and the five new specialist rooms (roster, rooms, the accounts each
covers, loss-meeting routing per group, the budget unchanged)."""

import json
import re

import pytest

from paperbot.agents import facts as F
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents import roster3
from paperbot.agents import triggers as TR
from paperbot.config import (DS200_FAMILY, DS200_IDS, REEL_NAME, V4_ACCOUNTS, V4_GROUP_ACCOUNTS, V4_JUDGED_ACCOUNTS,
                             V4_TF_ACCOUNTS)
from paperbot.groups import role_of
from test_rooms import DAY, HOUR, MIN, QUIET, START, QueueRunner, World, rec, team_answer

LEAD = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
# literal shapes of the v3 run that must never reach a prompt or a packet again
STALE = re.compile(r"(?<![0-9,.$])(156|144|195)(?![0-9])|뺐음|(?<![0-9,.$])180개|규칙 v4가 필요|paper v3 규칙|paper v3로")


class V4World(World):
    """test_rooms.World plus DeepSeek, reel and 5m coin-flip accounts (kinds ds200 / reel / random@5m)."""

    DS = (("F3_BOS", "15m"), ("F9_FVG", "1h"), ("F11_PO3", "30m"), ("F16_FIB382", "15m"), ("F7_RF_ONLY", "4h"))

    def __init__(self, tmp_path, start=START):
        super().__init__(tmp_path, start)
        for s, tf in self.DS:
            self.store.add_account(f"{s}@{tf}", s, tf, "ds200", start, "paper-v4",
                                   data={"group": "ds200", "family": DS200_FAMILY[s], "exits": "house"})
        self.store.add_account(f"{REEL_NAME}@5m", REEL_NAME, "5m", "reel", start, "paper-v4",
                               data={"group": "reel", "family": None, "exits": "reel"})
        for k in (1, 2, 3):
            self.store.add_account(f"RANDOM_{k}@5m", f"RANDOM_{k}", "5m", "random", start, "paper-v4",
                                   data={"group": "flip", "family": None, "exits": "reel"})
        self.store.commit()

    def ds_losses(self, aid="F3_BOS@15m", n=6, t=QUIET):
        for k in range(n):
            self.trade(aid, -20.0 - k, t - (n + 1 - k) * 10 * MIN)


# ------------------------------------------------------------------ the five specialist roles
def test_five_new_specialists_cover_every_deepseek_definition_and_the_reel_once():
    assert len(roster3.ROLES) == 36 and len(roster3.SPECIALISTS) == 36 and len(roster3.TEAMS) == 12
    keys = [r[0] for r in roster3.GROUP_SPECIALISTS]
    assert keys == ["spec_ds_structure", "spec_ds_trend", "spec_ds_session", "spec_ds_reversal", "spec_reel_5m"]
    assert [r[1] for r in roster3.GROUP_SPECIALISTS] == ["구조·유동성 담당", "추세·눌림 담당", "세션·시가 담당",
                                                         "반전·되돌림 담당", "5분봉 단타 담당"]
    assert all(r[2] == "specialist" for r in roster3.GROUP_SPECIALISTS)       # the specialist team, no 13th team
    covered = {s: TR.group_room_of(s) for s in (*DS200_IDS, REEL_NAME)}
    assert None not in covered.values() and set(covered.values()) == set(R.GROUP_ROOMS)
    assert covered["F11_PO3"] == "team:ds_session" and covered["F11_RAID"] == "team:ds_structure"
    assert covered[REEL_NAME] == "team:reel_5m" and covered["F15_ORB"] == "team:ds_session"
    fam_room = {}
    for s, room in covered.items():
        if s != REEL_NAME and s != "F11_PO3":
            assert fam_room.setdefault(DS200_FAMILY[s], room) == room                # a family sits in one room
    assert {f for f, r in fam_room.items() if r == "team:ds_trend"} == {"F4", "F6", "F7"}
    assert {f for f, r in fam_room.items() if r == "team:ds_reversal"} == {"F1", "F2", "F5", "F8", "F16", "F17"}
    for s in roster3.STRATEGY_KO:                  # the 36 keep their own rooms
        assert TR.group_room_of(s) is None and role_of(s) is None
    assert TR.group_room_of("RANDOM_1") is None and TR.group_room_of(None) is None
    # every new specialist has a room duty, a roster row on the dashboard and a name in the rooms
    ro = roster3.roster()
    assert {r["id"] for r in ro["roles"]} >= set(keys) and len(ro["roles"]) == 77
    for role in keys:
        assert roster3.room_duty(role) and R.role_name(role) != role and role in RM.ROLE_INFO


def test_group_rooms_and_their_plans():
    specs = {s["room_id"]: s for s in R.room_specs()}
    assert len(specs) == 47 and set(R.GROUP_ROOMS) <= set(specs) and set(R.GROUP_ROOMS) <= set(TR.all_rooms())
    for room, role in roster3.GROUP_ROLE_OF_ROOM.items():
        assert specs[room]["members"] == [role, "team_lead"] and specs[room]["kind"] == "team"
        for trig in TR.GROUP_TRIGGERS:
            d = TR.Due(room, trig, 5, {"class": "research"}, trig)
            assert RM.team_plan(d) == [(role, "team"), ("team_lead", "lead")]
            assert RM.round_min_calls(d, RM.RoomsPolicy()) == 2
        assert [r for r, _t in RM.team_plan(TR.Due(room, "owner", 1, {}, "owner"))] == [role, "team_lead"]
        assert RM.TEAM_VIEW[role] == ("meta", "groups")
    for trig in TR.GROUP_TRIGGERS:
        assert TR.TRIGGER_CLASS[trig] == "research" and TR.PRIORITY[trig] == 5     # spare calls, after the 36's
        assert trig in RM.RoomsPolicy().paced_triggers and trig in RM.TRIGGER_KO
    assert RM.DEFAULT_BUDGETS == {"incident": (15, 400_000), "owner": (20, 500_000), "loss": (48, 1_400_000),
                                  "scheduled": (20, 600_000), "weekly": (20, 550_000), "research": (24, 700_000)}
    assert RM.policy_from_env({"AGENTS_GROUP_MEETINGS_PER_DAY": "2"}).triggers.group_meetings_per_day == 2


# ------------------------------------------------------------------ routing (M7, M3)
def _dues(w, now=QUIET, policy=None):
    paper = w.paper()
    try:
        return TR.find_due(paper, None, w.agents, None, now, policy or TR.TriggerPolicy())
    finally:
        paper.close()


def test_deepseek_and_reel_losses_never_open_a_meeting_in_the_36_rooms(tmp_path):
    """M7: with DeepSeek and the reel losing heavily, the 36's meetings are exactly those of the same day without them;
    the DeepSeek losses go to their family's room, every Due names a real room."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    base, v4 = World(tmp_path / "a"), V4World(tmp_path / "b")
    for w in (base, v4):
        w.losses()
    v4.ds_losses("F3_BOS@15m", 6)
    v4.ds_losses("F9_FVG@1h", 2)                     # same room (structure): 8 in all
    v4.ds_losses("F16_FIB382@15m", 3)                # reversal: below the digest's 5
    v4.ds_losses(f"{REEL_NAME}@5m", 3)
    v4.ds_losses("RANDOM_1@5m", 9)                   # coin flips open nothing
    pol = TR.TriggerPolicy(max_rounds_per_tick=50)
    got = _dues(v4, policy=pol)
    want = [(d.room_id, d.trigger) for d in _dues(base, policy=pol)]
    core = [(d.room_id, d.trigger) for d in got if not d.data.get("group")]
    assert core == want and ("strat:N17_KC_RSI", "loss_cluster") in core
    groups = {d.room_id: d for d in got if d.data.get("group")}
    assert set(groups) == {"team:ds_structure", "team:reel_5m"}
    st = groups["team:ds_structure"]
    assert st.trigger == "group_loss" and st.data["losses"] == 8 and st.data["class"] == "research"
    assert st.data["by_definition"] == {"F3_BOS": 6, "F9_FVG": 2} and st.priority == 5
    assert groups["team:reel_5m"].data["losses"] == 3
    assert all(d.room_id in TR.all_rooms() for d in got)
    assert got.index(st) > max(i for i, d in enumerate(got) if not d.data.get("group"))   # after the 36's
    assert "인스타" not in st.data["summary_ko"] and st.data["summary_ko"].startswith("구조·유동성 담당 방: 새 손실 8건")


def test_group_meetings_have_their_own_daily_line_and_gaps(tmp_path):
    w = V4World(tmp_path)
    w.ds_losses("F3_BOS@15m", 6)
    w.ds_losses("F16_FIB382@15m", 6)
    w.ds_losses("F11_PO3@30m", 6)
    pol = TR.TriggerPolicy(group_meetings_per_day=2, max_rounds_per_tick=10)
    assert len([d for d in _dues(w, policy=pol) if d.data.get("group")]) == 2
    assert _dues(w, policy=TR.TriggerPolicy(group_meetings_per_day=0)) == []
    # a room met about its losses today: no second digest within the day even with new losses
    for d in _dues(w, policy=TR.TriggerPolicy(max_rounds_per_tick=10)):
        rid = TR.begin_round(w.agents, d, QUIET)
        TR.finish_round(w.agents, rid, "done", QUIET + MIN, {"action": "team_meeting"}, 2, 100)
        TR.advance_cursors(w.agents, d)
    w.ds_losses("F3_BOS@15m", 6, t=QUIET + 3 * HOUR)
    assert [d for d in _dues(w, now=QUIET + 4 * HOUR) if d.data.get("group")] == []
    assert [d.room_id for d in _dues(w, now=QUIET + 25 * HOUR) if d.data.get("group")] == ["team:ds_structure"]


def test_group_busts_are_batched_once_a_day(tmp_path):
    w = V4World(tmp_path)
    w.store.alert(QUIET - HOUR, "WARN", "[F3_BOS@15m] BUST: wallet 3.20 < 10")
    w.store.alert(QUIET - HOUR + 1, "WARN", "[F9_FVG@1h] BUST: wallet 1.00 < 10")
    w.store.alert(QUIET - HOUR + 2, "WARN", "[N17_KC_RSI@15m] BUST: wallet 1.00 < 10")
    w.store.commit()
    got = _dues(w, policy=TR.TriggerPolicy(max_rounds_per_tick=10))
    gb = [d for d in got if d.trigger == "group_bust"]
    assert [(d.room_id, d.data["accounts"]) for d in gb] == [("team:ds_structure", ["F3_BOS@15m", "F9_FVG@1h"])]
    assert [(d.room_id, d.trigger) for d in got if d.trigger == "bust"] == [("strat:N17_KC_RSI", "bust")]


def test_a_group_meeting_runs_on_spare_calls_with_its_own_packet(tmp_path):
    w = V4World(tmp_path)
    w.ds_losses(f"{REEL_NAME}@5m", 3)
    w.trade("RANDOM_2@5m", 4.0, QUIET - HOUR)
    runner = QueueRunner({"spec_reel_5m": [team_answer("r")], "team_lead": [LEAD]})
    out = w.tick(runner, QUIET)
    assert [(r["room_id"], r["trigger"], r["class"], r["calls"]) for r in out["rounds"]] == [
        ("team:reel_5m", "group_loss", "research", 2)]
    assert runner.roles() == ["spec_reel_5m", "team_lead"]
    pk = runner.calls[0]["packet"]["group_accounts"]
    assert pk["room"] == "team:reel_5m" and pk["accounts"] == 1 and pk["definitions"][0]["strategy"] == REEL_NAME
    assert pk["definitions"][0]["trades"] == 3 and len(pk["recent_losses"]) == 3
    assert [f["account_id"] for f in pk["coin_flips_5m"]] == ["RANDOM_1@5m", "RANDOM_2@5m", "RANDOM_3@5m"]
    assert runner.calls[0]["packet"]["board"].keys() <= {"meta", "groups", "error"}
    assert "5분봉 단타 담당" in runner.calls[0]["system"]
    assert R.usage_today(w.agents, QUIET)["by_class"]["research"]["calls"] == 2
    assert w.cursors()["loss:team:reel_5m"] == str(w.store.conn.execute("SELECT MAX(id) FROM trades").fetchone()[0])


# ------------------------------------------------------------------ the board and owner texts (M4)
def test_board_sections_are_the_core_group_and_groups_are_apart(tmp_path):
    from paperbot.agents import packets3
    w = V4World(tmp_path)
    w.trade("N17_KC_RSI@15m", 5.0, QUIET - HOUR)
    w.trade("RANDOM_1@15m", -1.0, QUIET - HOUR)
    w.ds_losses("F3_BOS@15m", 6)
    w.ds_losses(f"{REEL_NAME}@5m", 2)
    w.trade("RANDOM_3@5m", 7.0, QUIET - HOUR)
    w.store.put_state("accounts", QUIET, {"engines": {"F3_BOS@15m": {"wallet": 2.0, "bust": True},
                                                      "N17_KC_RSI@15m": {"wallet": 5005.0}}})
    w.store.alert(QUIET - HOUR, "WARN", "[F3_BOS@15m] BUST: wallet 2.00 < 10")
    w.store.commit()
    b = packets3.build(w.paths["paper"], None, QUIET)
    assert b["today"]["trades"] == 2 and b["today"]["net_pnl"] == 4.0 and b["today"]["busts_total"] == 0
    assert b["today"]["alerts"] == [] and "5m" not in b["league"] and b["league"]["15m"]["strategy_accounts"] == 2
    assert b["meta"]["accounts"] == 5 and b["meta"]["original_accounts"] == V4_ACCOUNTS
    assert b["meta"]["no_5m"] == F.five_m_ko() and "board_scope" in b["meta"]
    g = b["groups"]
    assert g["core"]["trades"] == 1 and g["ds200"]["trades"] == 6 and g["ds200"]["busts"] == 1
    assert g["ds200"]["by_family"]["F3"]["trades"] == 6 and g["reel"]["trades"] == 2
    assert g["flip"]["by_timeframe"]["5m"]["trades"] == 1 and g["flip"]["by_timeframe"]["15m"]["trades"] == 1
    # the evening Telegram: the core line, then one line per other group; DeepSeek and the 5m flips by counts only
    ctx = RM.RoundContext(agents_conn=w.agents, paper_ro=None, daily_ro=None, inbox_ro=None, runner=None, lab=None,
                          now_ms=QUIET)
    text = RM.compose_evening(ctx, b, LEAD)
    assert "매매법 거래 2건" in text and "매매법 파산 누적 0개" in text
    assert "\n딥시크: 거래 6건 · 파산 누적 1개" in text and "\n5분봉 동전: 거래 1건 · 파산 누적 0개" in text
    assert re.search(r"\n릴스 5분 단타: 거래 2건 · -\$[0-9]+ · 파산 누적 0개", text)
    assert "-$1" not in text.split("딥시크")[1].split("\n")[0]              # no DeepSeek P&L in a Telegram


# ------------------------------------------------------------------ one source of facts (M5)
def test_facts_come_from_config():
    f = F.facts()
    assert f["accounts"] == V4_ACCOUNTS and f["judged_accounts"] == V4_JUDGED_ACCOUNTS
    assert {g: v["accounts"] for g, v in f["groups"].items()} == V4_GROUP_ACCOUNTS
    assert f["five_minute"] == {"timeframe": "5m", "accounts": V4_TF_ACCOUNTS["5m"], "groups": ["reel", "flip"]}
    lines = F.run_facts_ko()
    assert f"계좌 {V4_ACCOUNTS}개" in lines[0] and f"{V4_GROUP_ACCOUNTS['ds200']}개" in lines[2]
    assert F.fill("a {{ORIGINALS}} b {x}") == f"a 원본 {V4_ACCOUNTS}개 계좌 b {{x}}"


def _prompts():
    for role in RM.ROLE_INFO:
        for turn in ("specialist", "revision", "challenge", "expert", "validator", "approver", "team", "lead"):
            if turn == "expert" and role not in RM.EXPERT_FILE:
                continue
            for meeting in ("", *RM.MEETING_FILE):
                yield role, turn, meeting, RM.system_prompt(role, turn, meeting)
    for turn in RM.LAB_TURNS:
        yield "lab", turn, "", RM.system_prompt("researcher", turn)


def test_no_stale_run_numbers_in_any_prompt_or_packet(tmp_path):
    seen = 0
    block = F.run_facts_block()          # the only place the counts appear: built from config (test_facts_...)
    for role, turn, meeting, text in _prompts():
        rest = text.replace(block, "")
        assert not STALE.search(rest), (role, turn, meeting, STALE.search(rest).group(0))
        assert "{{" not in text, (role, turn, meeting)
        seen += 1
    assert seen > 500
    common = RM.system_prompt("team_lead", "team")
    assert f"계좌 {V4_ACCOUNTS}개" in common and "딥시크" in common and "5분봉 계좌는 4개뿐" in common
    from paperbot.agents import debate as D, packets3
    # the debate prompt carries the run's facts too (sweep2 #8): the counts there are config's (block stripped)
    dsys = D.system_text()
    assert block in dsys and F.RULE_B_KO in dsys and F.exits_block() in dsys and F.method_text() in dsys
    assert not STALE.search(dsys.replace(block, "")) and "2026-10-26" not in dsys and "{{" not in dsys
    b = packets3.build(V4World(tmp_path).paths["paper"], None, QUIET)
    meta = {k: v for k, v in b["meta"].items() if k not in ("groups", "original_accounts")}     # config numbers
    assert not STALE.search(json.dumps(meta, ensure_ascii=False))
    assert b["meta"]["groups"] == V4_GROUP_ACCOUNTS and b["meta"]["original_accounts"] == V4_ACCOUNTS
    assert not STALE.search(RM.LIBRARY_PRIOR_KO.replace("195개도", ""))      # 195 there is the research count


# ------------------------------------------------------------------ levrule population (M6)
def _tier_rec(strategy, tf, pnl, t, tier):
    r = rec(strategy, tf, pnl, t)
    return r.__class__(**{**r.__dict__, "tier": tier})


def test_levrule_population_is_the_36_and_the_12_core_coin_flips(tmp_path):
    from paperbot.agents import leveval as LV
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    base, v4 = World(tmp_path / "a"), V4World(tmp_path / "b")
    for w in (base, v4):
        for k in range(12):
            for aid, tier, pnl in (("N17_KC_RSI@15m", "best", 6.0), ("N17_KC_RSI@15m", "normal", -2.0),
                                   ("RANDOM_1@15m", "best", 1.0), ("RANDOM_1@15m", "normal", 1.0)):
                s, tf = aid.split("@")
                w.store.trade(aid, _tier_rec(s, tf, pnl + k * 0.01, START + DAY + k * HOUR, tier))
    for k in range(12):                              # extreme r on the 5m coin flips and DeepSeek: must not count
        for aid, tier, pnl in (("RANDOM_2@5m", "best", -40.0), ("RANDOM_2@5m", "normal", 40.0),
                               ("F3_BOS@15m", "best", -40.0), ("F3_BOS@15m", "normal", 40.0)):
            s, tf = aid.split("@")
            v4.store.trade(aid, _tier_rec(s, tf, pnl, START + DAY + k * HOUR, tier))
    for w in (base, v4):
        w.store.commit()
    a, b = (LV.levrule_eval(w.paper(), now_ms=START + 40 * DAY, n_boot=200, mix=False) for w in (base, v4))
    for k in ("d_s", "d_c", "decision", "p_s"):
        assert a.get(k) == b.get(k), k
    rows = LV.trade_rows(v4.paper(), START, START + 40 * DAY)
    assert {r["account"] for r in rows} == {"N17_KC_RSI@15m", "RANDOM_1@15m"}
    assert b["population_doc"] == "docs/levrule-eval-v4.md"


# ------------------------------------------------------------------ debate room (M11)
def test_old_run_claims_are_void_and_the_observation_end_follows_the_start(tmp_path):
    from paperbot.agents import debate_grade as G
    from paperbot.agents import debate_packet as DP
    w = V4World(tmp_path)
    paper = w.paper()
    assert G.run_start(paper) == START
    before = START - 3 * DAY
    for kind, params in (("strategy_roe_sign", {"account": "N17_KC_RSI@15m", "base_id": 0, "n": 1, "op": "<"}),
                         ("best_vs_normal", {"base_id": 0, "n": 1}),
                         ("busts_by_day", {"day": 1, "max_busts": 5, "start_ts": START - 20 * DAY})):
        res = G.grade(kind, params, before, paper, None, QUIET)
        assert res["status"] == "void" and res["outcome"].startswith("void: 이전 실행"), kind
    res = G.grade("busts_by_day", {"day": 1, "max_busts": 5, "start_ts": START - 20 * DAY}, START + HOUR, paper, None,
                  QUIET)
    assert res["status"] == "void"                                    # a claim about the old run's day count
    assert G.grade("busts_by_day", {"day": 1, "max_busts": 5, "start_ts": START}, START + HOUR, paper, None,
                   QUIET)["status"] == "graded"
    assert DP.observe_until(START) == R.kst_day(START + 21 * DAY) and DP.observe_until(None) is None


@pytest.mark.parametrize("trig", TR.GROUP_TRIGGERS)
def test_probe_covers_the_group_triggers(trig):
    assert RM._PROBE[trig] in R.GROUP_ROOMS
