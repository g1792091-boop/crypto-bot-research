"""The agents' side of the paper-v4 gap pass (P11 items of the gap list): DeepSeek and reel cards and earlier tests in
the specialist packet (G3, G6), live risk on the account's own kind and timeframes (G3), loss cards for DeepSeek, the
reel and the five roles (G4), one exit line per group and no ladder words for the reel (G5), the five roles limited to
note / flag_owners / nothing and the lab refusing names outside the 36 without a trial (G7), the Obsidian export's v4
shape (G9), one verdict-method text (G18) and the v4 documents (G19), the digest's coin-flip baseline without the 5m
flips (G21), no no_snapshot incident on day 0 (G25), market moves and incidents per group (G26) and the frozen
DeepSeek timeout text (G27)."""

import json
import re
import sqlite3

import pytest

from paperbot.agents import actions as A
from paperbot.agents import digest as DG
from paperbot.agents import ds_prior
from paperbot.agents import facts as F
from paperbot.agents import labtests as LT
from paperbot.agents import leveval as LV
from paperbot.agents import packets3 as P3
from paperbot.agents import rooms as RM
from paperbot.agents import roster3
from paperbot.agents import survival as SV
from paperbot.agents import triggers as T
from paperbot.config import DS200_IDS, REEL_NAME
from paperbot.groups import role_members
from test_agents_v4 import LEAD, V4World
from test_rooms import DAY, HOUR, MIN, QUIET, QueueRunner, team_answer

OLD_METHOD = re.compile(r"동전 봇 2,000개|FDR 10%")


# ------------------------------------------------------------------ G18 / G19: one method text, the v4 documents
def test_method_ko_is_one_text_built_from_the_checkpoint():
    from paperbot import checkpoint as CP
    m = F.facts()["method_ko"]
    assert m == F.method_ko() and not OLD_METHOD.search(m)
    if callable(getattr(CP, "method_ko", None)):
        assert isinstance(m, str) and m
    else:                                        # built from the checkpoint's own numbers, so it follows them
        assert f"{CP.N_BOTS:,}" in m and "docs/paper-v4-verdict.md" in m
        for a in CP.FAMILY_ALPHA.values():
            assert f"{a * 100:g}%" in m


def test_no_old_method_text_in_prompts_duties_or_packet_notes():
    from paperbot.agents.rooms import system_prompt
    texts = [P3.PASS_CHECK_NOTE, json.dumps(roster3.ROOM_DUTY, ensure_ascii=False),
             json.dumps([r[5] for r in roster3.ALL_ROLES], ensure_ascii=False),
             system_prompt("team_lead", "team", "checkpoint"), system_prompt("learning", "team", "learning_review"),
             P3.checkpoint_section({"ready": True, "rows": []})["note"]]
    for t in texts:
        assert not OLD_METHOD.search(t), t[:200]
    assert F.facts()["method_ko"] in system_prompt("team_lead", "team", "checkpoint")


def test_meta_and_leveval_cite_the_v4_documents(tmp_path):
    w = V4World(tmp_path)
    meta = P3.build(w.paths["paper"], None, QUIET)["meta"]
    assert meta["rules"] == "docs/paper-v4-rules.md" and meta["verdict"] == "docs/paper-v4-verdict.md"
    assert meta["levrule"] == "docs/levrule-eval-v4.md" and "paper-v3" not in meta["rules_change"]
    assert meta["method_ko"] == F.facts()["method_ko"]
    assert "docs/levrule-eval-v4.md" in LV.LABEL and LV.RULES_DOC == "docs/paper-v4-rules.md"
    assert LV.DOC == "docs/levrule-eval.md"          # the pre-registered method itself is unchanged


# ------------------------------------------------------------------ G5: exits per group
def test_one_exit_line_per_group_and_no_ladder_for_the_reel():
    ex = F.facts()["exits_ko"]
    assert list(ex) == ["core", "ds200", "reel", "flip", "extra"]
    assert "계단" in ex["core"] and "계단" in ex["ds200"]
    assert "계단식 이익 잠금" not in ex["reel"] and "96봉" in ex["reel"] and "윗선" in ex["reel"]
    five, house = ex["flip"].split(" / ")
    assert "5분" in five and "계단식 이익 잠금" not in five and "계단" in house
    common = RM._read_prompt("rooms_common.md")
    assert "{{" not in common and all(line in common for line in ex.values())
    assert "익절은 계단식 잠금(+12%" not in common
    duty = roster3.room_duty("spec_reel_5m")
    assert F.REEL_EXIT_KO in duty and "96봉" in duty
    assert "릴스" in roster3.room_duty("exit_timing") and "릴스" in roster3.room_duty("whatif")


# ------------------------------------------------------------------ G3 / G6: cards and earlier tests
def test_specialist_packet_falls_back_to_the_v4_card_and_ds_prior():
    for s in ("F9_FVG", REEL_NAME):
        got = P3.specialist_packet({"pass_check": {}, "by_strategy": {}}, s)
        assert got["profile"] and got["profile"]["strategy"] == s
        assert got["research"]["strategy"] == s and got["research"]["candidates"] == 0
        assert "note" in got["research"] and got["research"]["conclusion_ko"]
    assert P3.specialist_packet({"pass_check": {}, "by_strategy": {}}, "V39_ALL")["profile"]["strategy"] == "V39_ALL"
    assert P3.research_prior("NOPE") is None and P3.research_counts()["total"] == 2960


def test_ds_prior_file_is_the_research_outputs():
    doc = json.load(open(ds_prior.PATH, encoding="utf-8"))
    assert doc == ds_prior.build()                    # rebuild with python -m paperbot.agents.ds_prior
    assert set(doc["strategies"]) == set(DS200_IDS) | {REEL_NAME}
    assert doc["totals"]["ds200"]["configs"] == 342 and doc["totals"]["ds200"]["candidates"] == 0
    assert doc["totals"]["reel"]["configs"] == 40 and doc["totals"]["reel"]["h1_pass"] is False
    assert sum(v["configs"] for k, v in doc["strategies"].items() if k != REEL_NAME) == 342
    assert doc["strategies"][REEL_NAME]["h1"]["pass"] is False


# ------------------------------------------------------------------ G3: live risk on the account's own kind
def test_dash_strategy_reads_a_deepseek_or_reel_account(tmp_path):
    w = V4World(tmp_path)
    for k in range(3):
        w.trade("F9_FVG@1h", -10.0 * (k + 1), QUIET - (k + 1) * HOUR)
        w.trade(f"{REEL_NAME}@5m", 5.0, QUIET - (k + 1) * HOUR)
    for k, v in enumerate((1000.0, 900.0, 950.0)):
        w.store.equity("F9_FVG@1h", QUIET - (3 - k) * HOUR, v, 0.0)
        w.store.equity(f"{REEL_NAME}@5m", QUIET - (3 - k) * HOUR, v, 0.0)
    w.store.commit()
    assert SV.own_kinds_tfs("F9_FVG")[0] == ("ds200",) and SV.own_kinds_tfs(REEL_NAME) == (("reel",), ("5m",))
    p = w.paper()
    try:
        ds = SV.dash_strategy(p, "F9_FVG", QUIET)
        reel = SV.dash_strategy(p, REEL_NAME, QUIET)
        brief = SV.strategy_brief(p, "F9_FVG", QUIET)
    finally:
        p.close()
    assert ds["max_dd_pct"] is not None and ds["max_dd_pct"] > 0
    assert reel["max_dd_pct"] is not None
    assert brief["by_tf"] and set(brief["by_tf"]) == {"1h"}


# ------------------------------------------------------------------ G4: loss cards
def test_loss_scope_of_the_36_deepseek_reel_and_the_roles():
    s, kinds, members, _ko = RM.loss_scope("N17_KC_RSI")
    assert (s, kinds, members) == ("N17_KC_RSI", ("strategy",), None)
    s, kinds, members, ko = RM.loss_scope("F9_FVG")
    assert s == "F9_FVG" and "ds200" in kinds and members is None and ko["F9_FVG"].startswith("딥시크")
    for key in ("ds_structure", "team:ds_structure", "spec_ds_structure"):
        s, kinds, members, _ko = RM.loss_scope(key)
        assert s is None and members == set(role_members("ds_structure")) and "F9_FVG" in members
    assert RM.loss_scope("team:reel_5m")[2] == {REEL_NAME}


def test_a_group_room_gets_its_members_loss_cards_and_research(tmp_path):
    w = V4World(tmp_path)
    w.ds_losses("F3_BOS@15m", 6)
    w.ds_losses("F16_FIB382@15m", 2)                  # another room's: never in this packet
    runner = QueueRunner({"spec_ds_structure": [team_answer("r")], "team_lead": [LEAD]})
    out = w.tick(runner, QUIET)
    assert [(r["room_id"], r["trigger"]) for r in out["rounds"]] == [("team:ds_structure", "group_loss")]
    pk = runner.calls[0]["packet"]
    accts = {c["account"] for c in pk["losses"]["recent"]}
    assert accts == {"F3_BOS@15m"} and pk["losses"]["n_recent"] == 6
    assert pk["group_accounts"]["research_prior"]["F3_BOS"]["candidates"] == 0
    assert "note" in runner.calls[0]["system"] and "flag_owners" in runner.calls[0]["system"]


# ------------------------------------------------------------------ G7: the five roles' actions and the lab
def test_group_rooms_allow_only_note_flag_and_nothing():
    assert roster3.GROUP_ACTIONS == A.GROUP_ACTIONS == ("note", "flag_owners", "no_action")
    given = {"room": {"room_id": "team:ds_trend", "kind": "team"}}
    for asked in ({"action": "hypothesis", "text": "x", "how_to_confirm": "y"},
                  {"action": "request_test", "test": {"template": "stop_atr", "timeframe": "1h", "k": 2.5}},
                  {"action": "propose_copy", "trial_id": 1}):
        got = RM._proposal({"proposal": asked}, "proposal", given)
        assert got["action"] == "no_action" and got.get("invalid")
    assert RM._proposal({"proposal": {"action": "note", "text": "a"}}, "proposal", given)["action"] == "note"
    other = {"room": {"room_id": "strat:N17_KC_RSI", "kind": "strategy", "strategy": "N17_KC_RSI"}}
    assert RM._proposal({"proposal": {"action": "hypothesis", "text": "x", "how_to_confirm": "y"}}, "proposal",
                        other)["action"] == "hypothesis"
    for role in ("spec_ds_structure", "spec_reel_5m"):
        assert "note(메모)·flag_owners" in roster3.room_duty(role)


def test_a_test_outside_the_36_is_refused_without_a_trial(tmp_path):
    from paperbot.agents import rooms_db as R
    conn = R.open_agents(str(tmp_path / "agents3.db"))
    for s in ("F9_FVG", REEL_NAME, None):
        env = A.ActionEnv(conn=conn, room_id="team:ds_structure", strategy=s, round_id=None, meeting="group_loss",
                          now_ms=QUIET)
        res = A.request_test(env, {"action": "request_test",
                                   "test": {"template": "stop_atr", "timeframe": "1h", "k": 2.5}})
        assert res["ok"] is False and res.get("refused")
    assert conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0] == 0
    for s in ("F9_FVG", REEL_NAME, "RANDOM_1"):
        with pytest.raises(LT.SpecError):
            LT.normalize_spec({"template": "stop_atr", "strategy": s, "timeframe": "1h", "k": 2.5})


# ------------------------------------------------------------------ G21: the digest's coin-flip baseline
def test_week_report_baseline_leaves_the_5m_flips_out(tmp_path):
    w = V4World(tmp_path)
    sunday = QUIET + 4 * DAY
    w.trade("N17_KC_RSI@15m", 10.0, sunday - DAY)
    w.trade("RANDOM_1@5m", 500.0, sunday - DAY)          # a 5m flip: the reel's comparison, never the 36's
    p = w.paper()
    try:
        rep = DG.week_report(p, w.agents, sunday)
    finally:
        p.close()
    assert rep["coin_flips"]["mean_pnl"] in (None, 0.0)


def test_week_report_groups_block_reel_against_its_5m_flips_and_counts_only_for_deepseek(tmp_path):
    """A1 (plan T10/C6): the Sunday report's own block for the reel (vs the median of its three 5m flips, its bust
    kept), DeepSeek and the 5m flips as counts (no money in Telegram, D10/D11); the 36's numbers stay the 36's."""
    w = V4World(tmp_path)
    sunday = QUIET + 4 * DAY
    w.trade("N17_KC_RSI@15m", 10.0, sunday - DAY)
    for k in range(3):
        w.trade(f"{REEL_NAME}@5m", 20.0, sunday - (k + 1) * HOUR)
    w.trade("RANDOM_1@5m", -30.0, sunday - DAY)
    w.trade("RANDOM_2@5m", 5.0, sunday - DAY)
    w.trade("RANDOM_3@5m", 40.0, sunday - DAY)
    w.trade("F3_BOS@15m", 777.0, sunday - DAY)
    w.trade("F9_FVG@1h", -333.0, sunday - DAY)
    w.trade("F9_FVG@1h", 1.0, sunday - 9 * DAY)                    # the week before: not this week
    w.store.alert(sunday - DAY, "WARN", f"[{REEL_NAME}@5m] BUST: equity 0.00")
    w.store.alert(sunday - DAY, "WARN", "[F9_FVG@1h] BUST: equity 0.00")
    w.store.commit()
    p = w.paper()
    try:
        rep = DG.week_report(p, w.agents, sunday)
    finally:
        p.close()
    g = rep["groups"]
    assert (g["reel"]["pnl"], g["reel"]["trades"], g["reel"]["busts"]) == (60.0, 3, 1)
    assert g["reel"]["bust_accounts"][0]["account"] == f"{REEL_NAME}@5m"
    assert (g["reel"]["flips_5m"], g["reel"]["flip_median_pnl"], g["reel"]["above_flip_median"]) == (3, 5.0, True)
    assert g["ds200"] == {"accounts": len(V4World.DS), "accounts_traded": 2, "trades": 2, "busts": 1}
    assert g["flip_5m"] == {"accounts": 3, "accounts_traded": 3, "trades": 3, "busts": 0}
    assert "pnl" not in g["ds200"] and "pnl" not in g["flip_5m"]
    assert rep["busts"] == [] and rep["strategies_total"]["trades"] == 1           # the 36's own numbers
    text = DG.compose_week(rep)
    lines = text.split("\n")
    reel = [x for x in lines if x.startswith("릴스 5분 단타")]
    assert reel and "+$60" in reel[0] and "중간값 +$5보다 위" in reel[0] and "파산 1개" in reel[0]
    ds = [x for x in lines if x.startswith("딥시크")]
    assert ds and "$" not in ds[0] and "거래 2건" in ds[0] and "파산 1개" in ds[0]
    f5 = [x for x in lines if x.startswith("5분 동전")]
    assert f5 and "$" not in f5[0] and "RANDOM" not in text and "777" not in text and "333" not in text
    assert "다른 묶음 (참고)" in text and len(text) <= 4000


def test_week_report_without_v4_groups_has_no_group_lines(tmp_path):
    from test_rooms import World
    w = World(tmp_path)
    p = w.paper()
    try:
        rep = DG.week_report(p, w.agents, QUIET + 4 * DAY)
    finally:
        p.close()
    assert rep["groups"] == {} and "다른 묶음" not in DG.compose_week(rep)


def test_dashboard_week_screen_shows_the_group_block_without_deepseek_money():
    import pathlib
    js = (pathlib.Path(__file__).resolve().parents[1] / "paperbot/dash/static/v4/screens/digest-week.js").read_text()
    assert "d.groups" in js and "groupsCard" in js and "flip_median_pnl" in js and "refNote" in js
    body = js[js.index("function groupsCard"):js.index("function render(d)")]
    assert "ds.pnl" not in body and "f5.pnl" not in body


# ------------------------------------------------------------------ G25 / G26 / G27: incidents
def _due_incident(w, now):
    p = w.paper()
    daily = sqlite3.connect(w.paths["daily"])
    try:
        return [d for d in T.find_due(p, daily, w.agents, None, now, T.TriggerPolicy(max_rounds_per_tick=50))
                if d.trigger == "incident"]
    finally:
        p.close()
        daily.close()


def _daily(w):
    from paperbot.daily3 import SCHEMA
    c = sqlite3.connect(w.paths["daily"])
    c.executescript(SCHEMA)
    return c


def test_incidents_open_for_core_reel_and_extras_only_and_the_ds_timeout_has_its_own_kind(tmp_path):
    from paperbot.sigservice import DS_TIMEOUT_TEXT
    w = V4World(tmp_path)
    _daily(w).close()
    t = QUIET
    w.store.alert(t - 30 * MIN, "CRITICAL", "[F9_FVG@1h] LIQUIDATED BTCUSDT 30x lost margin 25.00")
    w.store.alert(t - 29 * MIN, "CRITICAL", "[RANDOM_1@5m] LIQUIDATED BTCUSDT 30x lost margin 25.00")
    w.store.commit()
    assert _due_incident(w, t) == []                    # DeepSeek and coin flips: counted, never met about
    w.store.alert(t - 20 * MIN, "WARN", DS_TIMEOUT_TEXT.format(secs=60, boundary=123, tfs="1h, 4h"))
    w.store.alert(t - 19 * MIN, "CRITICAL", f"[{REEL_NAME}@5m] LIQUIDATED BTCUSDT 30x lost margin 25.00")
    w.store.alert(t - 18 * MIN, "CRITICAL", "[F3_BOS@15m] ENGINE HALTED: x. Operator action required.")
    w.store.commit()
    ds = _due_incident(w, t)
    assert len(ds) == 1
    # one DeepSeek timeout in the day: counted in the digest, not part of the meeting (jobs review 8)
    assert ds[0].data["counts"] == {"liquidation": 1, "engine_halted": 1}
    assert T.DS_TIMEOUT_FRAGMENT and DS_TIMEOUT_TEXT.startswith(T.DS_TIMEOUT_FRAGMENT)
    assert "did not answer within" not in T.DS_TIMEOUT_FRAGMENT


def test_deepseek_timeouts_open_an_incident_only_past_the_daily_threshold(tmp_path):
    """Jobs review 8: every DeepSeek map timeout used to open an ops meeting (every 30 min at worst, spending the
    incident class's calls). Now a KST day's timeouts open one only once ``ds_timeout_meeting_min`` (12, the
    Router's one loud WARN a day) have come; the 36's own signal timeout still opens one at once."""
    from paperbot.sigservice import DS_TIMEOUT_TEXT
    w = V4World(tmp_path)
    _daily(w).close()
    t = QUIET
    n = T.TriggerPolicy().ds_timeout_meeting_min
    assert n == 12
    for k in range(n - 1):
        w.store.alert(t - (n - k) * MIN, "WARN", DS_TIMEOUT_TEXT.format(secs=60, boundary=123 + k, tfs="15m"))
    w.store.commit()
    assert _due_incident(w, t) == []
    w.store.alert(t - 30_000, "WARN", DS_TIMEOUT_TEXT.format(secs=60, boundary=999, tfs="15m"))
    w.store.commit()
    ds = _due_incident(w, t)
    assert len(ds) == 1 and ds[0].data["counts"] == {"ds_signal_timeout": n}
    (tmp_path / "core").mkdir()
    w2 = V4World(tmp_path / "core")
    _daily(w2).close()
    w2.store.alert(t - MIN, "WARN", "signal workers did not answer within 120s; signals skipped at 123 for 15m")
    w2.store.commit()
    assert [d.data["counts"] for d in _due_incident(w2, t)] == [{"signal_timeout": 1}]


def test_no_snapshot_on_the_first_day_opens_no_incident(tmp_path):
    import datetime as dt
    from test_rooms import START
    w = V4World(tmp_path)
    c = _daily(w)
    day0 = dt.datetime.fromtimestamp(START / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    day1 = dt.datetime.fromtimestamp((START + DAY) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    text = "no 00:00 snapshot for this day (runner not running then)"
    c.execute("INSERT INTO reports VALUES (?,?,?)", (day0, START + DAY, json.dumps({"day": day0, "parity": text})))
    c.commit()
    now = START + DAY + HOUR
    assert _due_incident(w, now) == []                  # the run started after that day's 00:00 UTC
    c.execute("INSERT INTO reports VALUES (?,?,?)", (day1, now, json.dumps({"day": day1, "parity": text})))
    c.commit()
    c.close()
    ds = _due_incident(w, now + HOUR)
    assert len(ds) == 1 and ds[0].data["counts"] == {"no_snapshot": 1}


def test_market_move_counts_exposure_per_group_core_first(tmp_path):
    w = V4World(tmp_path)
    pos = lambda side, m: {"symbol": "BTCUSDT", "side": side, "qty": 0.1, "entry_price": 60_000.0,  # noqa: E731
                           "margin": m, "liq_price": 50_000.0, "leverage": 20}
    w.store.put_state("accounts", QUIET - MIN, {"engines": {
        "N17_KC_RSI@15m": {"position": pos(1, 300.0)}, "F9_FVG@1h": {"position": pos(-1, 200.0)},
        "F3_BOS@15m": {"position": pos(1, 100.0)}, "RANDOM_1@5m": {"position": pos(1, 50.0)}}})
    w.store.commit()
    ctx = RM.RoundContext(agents_conn=w.agents, paper_ro=w.paper(), daily_ro=None, inbox_ro=None, runner=None,
                          lab=None, now_ms=QUIET)
    due = T.Due(room_id="team:market", trigger="market_move", priority=3, meeting="",
                data={"moves": [{"symbol": "BTCUSDT", "last": 58_000.0, "ref": 60_000.0, "high": 60_100.0,
                                 "low": 57_900.0, "move": -0.033}]})
    try:
        pk = RM.market_move_packet(ctx, due)
    finally:
        ctx.paper_ro.close()
    e = pk["exposure"]["BTCUSDT"]
    assert (e["long"], e["short"]) == (3, 1)
    assert list(e["by_group"]) == ["core", "ds200", "flip"]
    assert (e["by_group"]["core"]["long"], e["by_group"]["ds200"]["long"], e["by_group"]["ds200"]["short"]) == (1, 1, 1)
    text = RM.compose_market_move(pk, None, QUIET)
    lines = text.split("\n")
    core = next(i for i, x in enumerate(lines) if x.startswith("우리 계좌 · 매매법: 롱 1 · 숏 0"))
    assert lines[core + 2] == "딥시크: 롱 1 · 숏 1" and lines[core + 3] == "동전: 롱 1 · 숏 0"


# ------------------------------------------------------------------ G9: the Obsidian export's v4 shape
def test_obsidian_lists_no_original_as_an_extra_and_shows_the_groups(tmp_path):
    import test_obsidian_export as OX
    w = {"dir": tmp_path, "paper": str(tmp_path / "paper3.db"), "daily": str(tmp_path / "daily3.db"),
         "agents": str(tmp_path / "agents3.db"), "cp": str(tmp_path / "checkpoint.db"),
         "inbox": str(tmp_path / "inbox.db"), "repo": str(OX.make_repo(tmp_path / "repo")), "out": str(tmp_path / "vault")}
    OX.make_paper(w["paper"])
    OX.make_daily(w["daily"])
    OX.make_agents(w["agents"])
    OX.make_checkpoint(w["cp"])
    OX.make_inbox(w["inbox"])
    OS, md_files, run = OX.START, OX.md_files, OX.run
    c = sqlite3.connect(w["paper"])
    for aid, s, tf, kind in (("F9_FVG@1h", "F9_FVG", "1h", "ds200"), (f"{REEL_NAME}@5m", REEL_NAME, "5m", "reel"),
                             ("RANDOM_1@5m", "RANDOM_1", "5m", "random")):
        c.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", (aid, s, tf, kind, OS, "paper-v4", None, "{}"))
    c.commit()
    c.close()
    run(w)
    files = md_files(w["out"])
    extra = next(v for k, v in files.items() if k.endswith("/추가 계좌.md"))
    assert "F9_FVG@1h" not in extra and REEL_NAME not in extra
    home = next(v for k, v in files.items() if k.endswith("/홈.md"))
    assert "## 그룹별 계좌" in home and "| 딥시크 | 1 |" in home and "| 5분 단타 | 1 |" in home
    assert not OLD_METHOD.search(home)
    for k, v in files.items():
        assert "동전 봇 2,000개" not in v, k
