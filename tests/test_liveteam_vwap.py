"""실거래 분석 팀 on the 'VWAP 개선판' (paperbot/liveteam.py; owners 10-25 "vwap 개선판봇 … 연구분석이나 손실 분석 … 전부 다
만들어줘", docs/vwap-bot-ko.md 9), on the world made by the real bot code (tests/vwap_site_world.py: the trend bot's paper,
the VWAP bot's own database by ComboRunner, WOO X Pro switched to it by its own start record, 바이비트 on the trend bot):

- its sources are the live site's VWAP screens (dash/more/livevwap.py) and its followers' segments; the one-paper world
  has none and every packet stays as it was;
- its packet: its rules from its running config and its follower's executor rules, the owners' decisions, its record since
  its own start (paper, coin-flip twin, the follower's trades on it, apart), 운이냐 고장이냐 against its 5 years (which
  lost per trade; the 17 days labelled), the costs (DeepCoin's taker as passed on, the research's, what the fills paid),
  the gates' what-ifs (가상), the coins now; no number of the trend bot or of 바이비트;
- when: a losing pair of an executor while it followed the VWAP bot is the VWAP bot's loss meeting and never the main
  bot's; the paper's 50th trade and the follower's 50th live trade are checkpoints, once each; the weekly report carries
  its part;
- the meeting itself: the VWAP members' instructions, the conclusion named "VWAP 개선판 · <executor>", the weekly report's
  VWAP part told apart (message, member lines, ideas), the 분석팀 tab's words;
- every instruction keeps the team off the controls and says the 5 years lost per trade.
The AI is FakeRunner (paperbot/agents/runner.py)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paperbot import liveteam as T  # noqa: E402
from paperbot import vwapband as VB  # noqa: E402
from paperbot.agents import runner as R  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from tests import vwap_site_world as V  # noqa: E402

NOW, K, MIN, H, DAY = V.NOW, V.K, V.MIN, V.H, V.DAY
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    folder = tmp_path_factory.mktemp("teamvwap")
    w = V.build(str(folder / "w"))
    mp = pytest.MonkeyPatch()
    for k, v in V.env_of(w).items():
        mp.setenv(k, v)
    mp.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    mp.setenv(T.DB_ENV, str(folder / "team" / "liveteam.db"))
    mp.delenv(T.BUDGET_ENV, raising=False)
    L._cache.clear()
    src = T.sources(NOW, w["p"])
    yield w, src, folder
    mp.undo()
    L._cache.clear()


class Note:
    def __init__(self):
        self.sent = []

    def send(self, level, text):
        self.sent.append((level, text))


class Rec(R.FakeRunner):
    """FakeRunner that keeps the instructions each member was given."""

    def call(self, model, system_prompt, instruction, packet):
        self.calls_text = getattr(self, "calls_text", []) + [(packet.get("role"), system_prompt, instruction)]
        return super().call(model, system_prompt, instruction, packet)


LEAD = {"headline": "VWAP 개선판 2연패, 5년 기준으로는 정상 범위", "verdict": "주의", "summary": ["하나", "둘"], "good": [], "worries": ["손절 두 번"],
        "watch_next": ["다음 10번"], "ideas": [{"idea": "변동성 위치 0.6 미만만", "why": "숫자", "test": "2020-24로 고르고 2025-26 확인"}]}


def _lose(key, pid, entry, exit_):
    return {"key": key, "entry_time": entry, "exit_time": exit_, "pnl": -2.0, "symbol": "DOGEUSDT", "side": -1, "roe": -0.45,
            "paper": {"id": pid, "roe": -0.43}, "strategy_id": "F6_VWAP_FAIL", "timeframe": "30m", "reason_ko": "손절"}


def _vwap_pair(src, w):
    """``src`` where WOO X Pro's last two closed trades, both entered after its switch to the VWAP bot, lost."""
    vt = w["vt"]
    rows = [_lose("a", vt["E5"]["id"], V.SWITCH + 9 * H, NOW - 5 * H), _lose("b", vt["E7"]["id"], V.SWITCH + 22 * H, NOW - 2 * H)]
    return {**src, "trades": {**src["trades"], "accts": {**src["trades"]["accts"], "mexc": {"rows": rows}, "bybit": {"rows": []}}}}


# ---------------------------------------------------------------- the sources
def test_the_vwap_bot_is_read_apart_with_its_follower(world):
    w, src, _f = world
    vs = src["vwap"]
    assert vs["state"] == "ok" and vs["bot_id"] == "paper2" and vs["path"] == w["p"]["paper2"]
    (f,) = vs["followers"]                                  # 바이비트 never followed it
    assert (f["id"], f["name_ko"], f["now"], f["since_ms"]) == ("mexc", "WOO X Pro", True, V.SWITCH)
    assert f["costs"]["n"] == 3 and f["costs"]["measured_n"] == 3 and 0 < f["costs"]["fee_rate_side"] < 0.001
    assert {vs[k]["state"] for k in ("control", "perf", "blocked")} == {"ok"}
    assert T.vwap_apart(src) is vs and T.vwap_apart({**src, "vwap": {**vs, "bot_id": "paper"}}) is None
    assert T.on_vwap(vs, "mexc", V.SWITCH + MIN) and not T.on_vwap(vs, "mexc", V.SWITCH - MIN) and not T.on_vwap(vs, "bybit", NOW)


def test_the_one_paper_world_has_no_vwap_part(tmp_path, monkeypatch):
    import livebots_world as W
    d = str(tmp_path / "w")
    p = W.build_world(d)
    for k, v in {**W.env_of(p), **W.env_more_of(W.live_checks(p, d, rich=True))}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    L._cache.clear()
    src = T.sources(W.NOW, p)
    assert src["vwap"] == {"state": "off"} and T.vwap_apart(src) is None
    pk = T.packet_for(src, "weekly", {"window": [W.NOW - 7 * DAY, W.NOW]})
    assert "vwap_bot" not in pk and pk == T.facts(src, "weekly", window=(W.NOW - 7 * DAY, W.NOW))
    for role in T.ROLES:
        assert T.prompt_for(role, pk) == T.system_prompt(role)
    assert T.due_loss_vwap(src) is None and T.due_checkpoint_vwap(src) is None and T.due_checkpoint_vwap_live(src) is None


# ---------------------------------------------------------------- the packet
def test_the_vwap_packet(world):
    from paperbot.dash.more import livevwap as VW
    w, src, _f = world
    pk = T.packet_for(src, "loss", {"bot": "vwap", "executor": "mexc", "executor_ko": "WOO X Pro"})
    assert pk["meeting"] == "VWAP 개선판 · WOO X Pro 손실 회의" and T.packet_vwap(pk) and not T.packet_trend(pk)
    bot = pk["bot"]
    assert (bot["kind"], bot["name"], bot["label"], bot["since_kst"]) == ("vwap", "VWAP 개선판", "VWAP 개선판 · WOO X Pro", T.kst_text(V.VS))
    assert bot["apart"] == T.VWAP_APART_KO and bot["break_even_5y"] == VB.load()["breakeven_win"]
    assert bot["followers"] == [{"name": "WOO X Pro", "following_now": True, "since_kst": T.kst_text(V.SWITCH)}]
    # its rules from its running config (the 관제 answer's own words), then its follower's executor rules
    rules = pk["fixed_rules"]
    own = VW.control(w["p"], NOW, dict(w["more"]))["rules"]["lines"]
    assert rules[:len(own)] == own
    for r in ("손절 2 ATR · 계단 익절 순ROE 12%에서 10% 잠금, 이후 5%씩", "BTC 30배 · 나머지 30배 · 증거금 잔고의 40%",
              "4시간 추세 판단이 반대면 진입 안 함(4개 중 3개 반대; 보류는 진입)",
              "변동성(ATR14%)이 지난 30일의 80% 위치보다 크면 진입 안 함(상위 20% 금지)",
              "보유 한도 96봉(30분 48시간 · 1시간 96시간), 넘으면 시장가 청산", "거래소에 거는 손절",
              "신호등: WOO X Pro는 페이퍼 최근 20번 중 75% 이상 이겼을 때만 새 진입을 따라감"):
        assert r in rules, r
    assert not any("바이비트" in r for r in rules) and pk["owners_decisions"] == list(T.VWAP_DECISIONS)
    # its record since its own start: the paper (its own trades), the twin, the follower's trades on it
    vts = [t for t in V.paper_trades(w["p"]["paper2"]) if t["entry_time"] >= V.VS]
    rec = pk["record"]
    assert (rec["paper"]["n"], rec["paper"]["wins"]) == (len(vts), sum(1 for t in vts if t["pnl"] > 0)) == (7, 5)
    assert rec["flip"]["n"] == 3 and rec["skill"].startswith("실력 vs 운")
    (lv,) = rec["live"]
    assert (lv["name"], lv["n"], lv["goal"], lv["record"]["wins"]) == ("WOO X Pro", 3, 50, 2)
    assert [c["what"] for c in lv["checks"]][:2] == ["실거래 50번", "승률 80% 이상 (키우기)"] and lv["vs_paper"]["pairs"] == 3
    # 운이냐 고장이냐: the paper and the follower apart, the yardstick in words
    bd = pk["band"]
    assert bd["paper"]["n"] == 7 and bd["paper"]["verdict"] in VB.VERDICTS and "5년 승률(72.0%)" in bd["paper"]["win"]["words"]
    assert [x["name"] for x in bd["live"]] == ["WOO X Pro"] and bd["live"][0]["n"] == 3
    y = bd["yardstick"]
    assert y["five_years"]["trades"] == 5805 and "거래당 손해" in y["honest"] and "고를 때 본 가장 좋은 기간" in y["pick17"]
    # the costs: the research's round trip at the bot's 30x; the follower's exchange; what its fills paid
    c = pk["costs"]
    assert c["leverage"] == 30 and c["research"]["round_trip"] == pytest.approx(0.0014) and c["research"]["roe_at_leverage"] == pytest.approx(0.042)
    (cx,) = c["execs"]
    assert (cx["name"], cx["exchange"], cx["code_assumes_taker"]) == ("WOO X Pro", "WOO X Pro", 0.00042)
    assert cx["live_measured"]["n"] == 3 and "taker_told" not in cx                     # DeepCoin's rate only for DeepCoin
    # the gates' what-ifs: 가상
    blk = pk["blocked"]
    assert blk["label"].startswith("가상") and blk["total"]["all"] == 5
    assert {x["why"] for x in blk["virtual"]} >= {"4시간 추세 반대", "변동성 높음"} and "가상" in blk["virtual"][0]["read"]
    assert blk["gates_virtual"]["n"] == 3
    # now: the position with the gates it passed, every coin's sides
    now = pk["now"]
    assert now["position"]["coin"] == "BTC" and now["position"]["hold_left"] == "보유 한도까지 95시간"
    assert now["coins"]["BTC"]["sides"]["VWAP 복귀 실패 30분"] == "롱 가능 · 숏 막힘(4시간 상승 4표)"
    assert "매매법" in pk["splits"] and pk["checkpoint_rule"] == T.VWAP_CHECK_RULE
    # the trades closed in the window (the last 3 days): its own, with the follower's part
    assert pk["trades"] and all(t["strategy"] in ("VWAP 복귀 실패 30분", "CMO·샌드위치 캔들 1시간") for t in pk["trades"])
    doge = next(t for t in pk["trades"] if t["coin"] == "DOGE")
    assert doge["live"]["mexc"]["followed"] is True and doge["gates_at_entry"].startswith("4시간 하락")
    # nothing of the trend bot or of 바이비트 (the owners' decisions name them only to say they stay as they are)
    text = json.dumps({k: v for k, v in pk.items() if k != "owners_decisions"}, ensure_ascii=False)
    for other in ("바이비트", "bybit", "추세판단 봇 숫자", "fit_win", "honest_win", "A+C", "88% 이상"):
        assert other not in text, other
    for secret in ("TELEGRAM", "API_KEY", "SECRET", "executor.env", "OAUTH"):
        assert secret not in text, secret
    assert len(json.dumps(pk, ensure_ascii=False, default=str)) < 60_000


def test_the_rules_say_deepcoins_size_from_its_balance():
    """The DeepCoin executor's own config (deploy/executor.live-deepcoin.json: size_from "equity", margin_frac 0.4, the light
    20 / 75 %) under the bot's own rules; a config that cannot be read: said, never a guess."""
    from paperbot import livecheck as LC
    path = os.path.join(ROOT, "deploy", "executor.live-deepcoin.json")
    (ex,) = LC.load_executors((("deepcoin", path, "paperbot-executor-deepcoin", "/nonexistent/dc.db", 0, 0.85),))
    assert ex.margin_frac == 0.4 and ex.label == "딥코인"
    rules = T._vw_rules({"state": "ok", "rules": {"lines": ["손절 2 ATR · 계단 익절 순ROE 12%에서 10% 잠금, 이후 5%씩"]}}, [ex])
    assert rules[0] == "손절 2 ATR · 계단 익절 순ROE 12%에서 10% 잠금, 이후 5%씩"
    assert "크기: 딥코인은 진입할 때마다 자기 잔고의 40%를 증거금으로 (손절이 멀어도 줄이지 않음)" in rules
    assert "신호등: 딥코인은 페이퍼 최근 20번 중 75% 이상 이겼을 때만 새 진입을 따라감" in rules and "실거래 금액 딥코인 $100" in rules
    assert T._vw_rules({"state": "error"}, [])[0].startswith("규칙을 읽지 못했어요(자료 없음)") and T._vw_rules({"state": "error"}, [])[-1] == \
        "따라가는 실행기 없음(페이퍼만)"


def test_deepcoins_costs_say_the_rate_as_passed_on():
    vs = {"followers": [{"name_ko": "딥코인", "exchange": "deepcoin", "costs": {"n": 0}}]}
    (x,) = T._vw_costs(vs, {"leverage": {"default": 30}})["execs"]
    assert x["exchange"] == "딥코인" and x["code_assumes_taker"] == 0.0005
    t = x["taker_told"]
    assert t["taker_side"] == 0.0004 and t["round_trip"] == 0.0008 and t["roe_at_leverage"] == pytest.approx(0.024)
    assert "0.04%" in t["words"]


# ---------------------------------------------------------------- when
def test_a_losing_pair_on_the_vwap_bot_is_its_own_meeting(world):
    w, src, _f = world
    s = _vwap_pair(src, w)
    assert T.due_loss(s) is None                                   # never the main bot's
    key, f = T.due_loss_vwap(s)
    ids = sorted([str(w["vt"]["E5"]["id"]), str(w["vt"]["E7"]["id"])])
    assert key == "loss:vwap:" + "+".join(ids) and (f["bot"], f["executor"], f["executor_ko"]) == ("vwap", "mexc", "WOO X Pro")
    assert [x["coin"] for x in f["losses"]] == ["DOGE", "DOGE"] and f["losses"][1]["strategy"] == "VWAP 복귀 실패 30분"
    assert f["losses"][1]["gates_at_entry"].startswith("4시간 하락") and f["losses"][1]["worst_roe"] < -0.4
    band = T._vwap_band_of(s["vwap"], "mexc")
    assert f["how_rare"] == VB.streak_ko(band) and f["band_verdict"] == band["verdict_ko"]
    assert T.due_loss_vwap({**s, "now": NOW + 4 * DAY}) is None   # an old pair when the team is turned on
    # the same executor's trend-era pair (entered before its switch): the main bot's, never the VWAP bot's
    old = [_lose("c", 901, V.SWITCH - 9 * H, V.SWITCH - 8 * H), _lose("d", 902, V.SWITCH - 3 * H, V.SWITCH - 2 * H)]
    s2 = {**src, "now": V.SWITCH + H, "trades": {"accts": {"mexc": {"rows": old}}}}
    assert T.due_loss(s2)[0] == "loss:901+902" and T.due_loss_vwap(s2) is None


def test_the_vwap_checkpoints(world, tmp_path):
    w, src, _f = world
    assert T.due_checkpoint_vwap(src) is None and T.due_checkpoint_vwap_live(src) is None      # 7 paper trades, 3 live
    vs = src["vwap"]
    prf = vs["perf"]
    trades = [{"id": i, "win": i % 4 != 0} for i in range(53)]
    fake = {**prf, "paper": {**prf["paper"], "n": 53}, "trades": trades, "checklist": [{**prf["checklist"][0], "n": 51}]}
    s = {**src, "vwap": {**vs, "perf": fake}}
    key, f = T.due_checkpoint_vwap(s)
    assert key == f"checkpoint:vwap-{T.kst_date(V.VS)}:50" and (f["bot"], f["what"], f["milestone"], f["paper_closed"]) == ("vwap", "paper", 50, 53)
    assert f["last_k_wins"] == sum(1 for t in trades[:50] if t["win"]) and f["live"] == [{"name": "WOO X Pro", "n": 51, "goal": 50}]
    key2, f2 = T.due_checkpoint_vwap_live(s)
    assert key2 == f"checkpoint:vwap-live-mexc-{T.kst_date(V.SWITCH)}:50"
    assert (f2["what"], f2["executor_ko"], f2["milestone"], f2["live_closed"]) == ("live", "WOO X Pro", 50, 51)
    vsx = s["vwap"]
    assert T.vwap_meeting_label("checkpoint", f, vsx) == "VWAP 개선판 · WOO X Pro 50번째 거래 점검(페이퍼)"
    assert T.vwap_meeting_label("checkpoint", f2, vsx) == "VWAP 개선판 · WOO X Pro 실거래 50번 점검"
    assert T.vwap_meeting_label("weekly", None, {"followers": []}) == "VWAP 개선판 (페이퍼만) 주간 보고"
    assert T.kind_ko("checkpoint", key) == "VWAP 거래 점검" and T.kind_ko("checkpoint", key2) == "VWAP 실거래 점검"
    assert T.kind_ko("weekly", "weekly:2026-10-26:vwap") == "VWAP 주간 보고" and T.kind_ko("checkpoint", "checkpoint:40") == "판단 회의"
    # the order: the follower's 50th live trade, then the paper's, then the weekly report; each once
    conn = T.connect(str(tmp_path / "t.db"))
    try:
        keys = [k for _kind, k, _f in T.due(conn, s)]
        assert keys.index(key2) < keys.index(key) < len(keys) - 1 and keys[-1].startswith("weekly:")
        conn.execute("INSERT INTO meetings (kind, key, title, started_ts, state) VALUES ('checkpoint', ?, 'x', 0, 'done')", (key2,))
        assert key2 not in [k for _kind, k, _f in T.due(conn, s)]
    finally:
        conn.close()


# ---------------------------------------------------------------- the meetings
def test_a_vwap_loss_meeting_is_named_and_told_apart(world):
    w, src, folder = world
    s = _vwap_pair(src, w)
    conn = T.connect(os.environ[T.DB_ENV])
    try:
        run, note = Rec(answers={"lead": LEAD}), Note()
        out = T.tick(conn, s, run, T.BUDGET_DEFAULT, notifier=note)
        assert out["state"] == "done" and out["key"].startswith("loss:vwap:") and [c["role"] for c in run.calls] == ["risk", "stats", "lead"]
        for role, sp, ins in run.calls_text:
            assert sp == T.vwap_prompt(role) and ins.startswith("VWAP 개선판 · WOO X Pro 손실 회의 회의입니다")
        facts = run.calls[0]["packet"]["facts"]
        assert facts["bot"]["kind"] == "vwap" and facts["focus"]["executor_ko"] == "WOO X Pro"
        title, = conn.execute("SELECT title FROM meetings WHERE key = ?", (out["key"],)).fetchone()
        assert title.startswith("VWAP 개선판 · WOO X Pro 손실 회의 · ") and T.kind_ko("loss", out["key"]) == "VWAP 손실 회의"
        (_lv, msg), = note.sent
        assert msg.startswith("🧭 [실거래 분석팀] VWAP 개선판 · WOO X Pro 손실 회의 🟠 주의\n" + LEAD["headline"])
        assert "시험해 볼 아이디어 1개 (결정은 두 분)" in msg and "—" not in msg
        assert out["key"] not in [k for _kind, k, _f in T.due(conn, s)]         # once per pair
        # the 분석팀 tab: the meeting under the VWAP bot's name, its idea with the VWAP bot's way to test it
        t = L.team(w["p"], NOW, units=lambda u: ("inactive", "disabled"))
        m = next(x for x in t["meetings"] if x["key"] == out["key"])
        assert m["kind_ko"] == "VWAP 손실 회의" and m["ideas"][0]["how_ko"] == T.VWAP_IDEA_HOW_KO
    finally:
        conn.close()


def test_the_weekly_report_carries_the_vwap_bots_part(world, tmp_path):
    w, src, _f = world
    key, focus = T.due_weekly(src)
    pk = T.packet_for(src, "weekly", focus)
    sec = pk["vwap_bot"]
    a, b = focus["window"]
    main = T.facts(src, "weekly", window=(a, b))
    assert {k: v for k, v in pk.items() if k != "vwap_bot"} == main                     # the main bot's packet as it was
    assert sec["bot"]["kind"] == "vwap" and sec["meeting"] == "VWAP 개선판 · WOO X Pro 주간 보고(같은 회의의 다른 봇 칸)"
    assert sec["trades"] and "research" not in sec and "next_releases" not in sec
    assert {t["coin"] for t in sec["trades"]} == {"BTC", "ETH", "LTC"}                    # E1 E2 E3 closed in that week
    for role in T.ROLES:
        assert T.prompt_for(role, pk) == T.system_prompt(role, T.packet_trend(pk)) + T.vwap_section_prompt(role)
    assert T.week_has_trades({"trades": [], "vwap_bot": {"trades": [1]}}) and not T.week_has_trades({"trades": [], "vwap_bot": {"trades": []}})
    conn = T.connect(str(tmp_path / "w.db"))
    try:
        lead = {**LEAD, "verdict": "지켜보기", "headline": "추세판단 봇 한 줄",
                "vwap": {"headline": "VWAP 한 줄", "verdict": "정상 범위", "summary": ["v1", "v2"], "worries": ["v걱정"], "watch_next": [],
                         "ideas": [{"idea": "VWAP 아이디어", "why": "w", "test": "t"}]}}
        member = {"headline": "한 줄", "points": ["p"], "vwap_points": ["VWAP 7번 중 5번"], "worry": None, "luck": "작음"}
        run, note = Rec(answers={"risk": member, "stats": member, "market": member, "lead": lead}), Note()
        out = T.tick(conn, src, run, T.BUDGET_DEFAULT, notifier=note, only="weekly")
        assert out["state"] == "done" and out["key"] == key
        for role, sp, _ins in run.calls_text:
            assert sp.endswith(T.vwap_section_prompt(role)) and "다른 봇: VWAP 개선판" in sp
        (_lv, msg), = note.sent
        lines = msg.split("\n")
        assert lines[1] == "추세판단 봇 한 줄" and "— VWAP 개선판 · WOO X Pro 🟢 정상 범위" in lines
        i = lines.index("— VWAP 개선판 · WOO X Pro 🟢 정상 범위")
        assert lines[i + 1:i + 4] == ["VWAP 한 줄", "· v1", "· v2"] and "시험해 볼 아이디어 2개 (결정은 두 분)" in msg
        ideas = [r[0] for r in conn.execute("SELECT idea FROM ideas ORDER BY id")]
        assert ideas == [LEAD["ideas"][0]["idea"], "[VWAP 개선판] VWAP 아이디어"]
        risk, = conn.execute("SELECT text FROM messages WHERE role = 'risk'").fetchone()
        assert "· [VWAP 개선판] VWAP 7번 중 5번" in risk
        res = json.loads(conn.execute("SELECT result FROM meetings").fetchone()[0])
        assert res["vwap"]["label"] == "VWAP 개선판 · WOO X Pro" and res["vwap"]["verdict"] == "정상 범위"
        lead_text, = conn.execute("SELECT text FROM messages WHERE role = 'lead'").fetchone()
        assert "· [VWAP 개선판] VWAP 한 줄" in lead_text
    finally:
        conn.close()
    # a meeting without the VWAP part keeps nothing of a stray answer about it
    r = T.lead_result({**LEAD, "vwap": {"headline": "x", "verdict": "매수"}})
    assert r["vwap"]["verdict"] == "지켜보기" and T.lead_result(LEAD).get("vwap") is None


def test_the_team_tab_shows_the_weekly_vwap_part():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    js = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens", "livebots-team.js")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    r = {"vwap": {"label": "VWAP 개선판 · 딥코인", "headline": "VWAP 한 줄", "verdict": "주의", "summary": ["v1"], "worries": ["w1"], "watch_next": []}}
    script = (f"const D = await import('{dom}');\nconst R = await import('file://{js}');\n"
              f"const a = R.vwapPart({json.dumps(r)}), b = R.vwapPart({{}}), c = R.vwapPart(null);\n"
              "console.log(JSON.stringify({t: D.walk(a).text.replace(/\\s+/g, ' '), v: a.dataset.v, b, c}));")
    out = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    d = json.loads(out.stdout.strip().splitlines()[-1])
    assert d["b"] is None and d["c"] is None and d["v"] == "warn"
    for words in ("VWAP 개선판 · 딥코인", "주의", "같은 회의 · 다른 봇", "VWAP 한 줄", "v1", "걱정", "w1"):
        assert words in d["t"], words
    assert "다음에 볼 것" not in d["t"]


def test_the_vwap_prompts_keep_the_team_off_the_controls():
    for role in T.ROLES:
        sp = T.vwap_prompt(role)
        assert sp != T.system_prompt(role) and T.ROLES_VWAP[role]["focus"] in sp
        assert "매매 권한이 없습니다" in sp and "고정 규칙" in sp and "패킷(JSON)에 있는 숫자만" in sp and "JSON 하나만" in sp
        assert f"{T.SMALL_N}번보다 적으면" in sp and "두 분의 결정(owners_decisions)" in sp
        assert "추세판단 봇과 다른 봇" in sp and "섞지 않고" in sp and "거래당 손해" in sp and "17일(pick17)" in sp
        assert "'가상'이라고" in sp and "아주 드묾" in sp
        for trend_only in ("2주 검토", "88%", "fit(맞춘 숫자", "trend-wait", "감독"):
            assert trend_only not in sp, trend_only
        add = T.vwap_section_prompt(role)
        assert "다른 봇: VWAP 개선판" in add and "섞지 않습니다" in add and "거래당 손해" in add and "'가상'" in add
    assert "시험해 볼 가설" in T.vwap_prompt("lead") and "채택은 두 분이 정합니다" in T.vwap_prompt("lead")
    assert '"vwap": {' in T.vwap_section_prompt("lead") and '"vwap_points"' in T.vwap_section_prompt("risk")
    assert [(T.ROLES_VWAP[r]["name"], T.ROLES_VWAP[r]["title"]) for r in T.ROLES] == [(T.ROLES[r]["name"], T.ROLES[r]["title"]) for r in T.ROLES]


def test_the_owners_preview_of_the_vwap_packet(world, capsys):
    """python -m paperbot.liveteam preview loss --vwap: the VWAP packet and its members' instructions, no AI call, nothing
    written."""
    _w, _src, folder = world
    db = str(folder / "team" / "preview.db")
    assert T.main(["--db", db, "preview", "loss", "--vwap"]) == 0
    out = capsys.readouterr().out
    pk = json.loads(out[:out.index("\n=====")])
    assert pk["bot"]["kind"] == "vwap" and pk["meeting"] == "VWAP 개선판 · WOO X Pro 손실 회의" and pk["focus"]["bot"] == "vwap"
    assert out.count("===== ") == 3 and T.vwap_prompt("lead") in out and not os.path.exists(db)
