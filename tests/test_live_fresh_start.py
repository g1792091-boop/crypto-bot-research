"""실거래 site on the night of the switch (owners 10/21: "대시보드 화면 안부족하게 만들어준 거 맞지? 뭔가 허전해 보여서"): the
추세판단 봇 has just started on the database the bot before it (규칙봇 15) still has its position in, nothing of its own is
closed yet, both executors restarted and skipped that position as late.

On the trend bot's own world (tests/test_trendbot.py: TrendRunner and its fake judge) with the start moved after an entry
(``since``: the bot's first start on this database) and two executor databases made by paperbot/executor.py's own store:
- 관제 (dash/more/livetrend.py): the open position is the bot before it's (``inherited``, 전환 전 포지션) with each
  executor's part in it from its own records (late = skipped, none = no record); today's funnel, the members' signals today
  and the last 24 h of signals start at the bot's start; once that position is closed it is listed apart (``prev``) and
  its supervisor exit is flagged, never counted as the bot's trade; the next entry pause by the config's own rules
  (Nasdaq open 22:00~23:00 KST, the weekend); the 7/1~10/20 replay's expectation, said to have run with the 시간 정리 exit;
- 일정 · 한눈에 (livebots.calendar, whynow): the pause around each Nasdaq open is a pause window like the weekend and a
  release (it was missing: the next pause read as the weekend two days away);
- 진입 가능성 (순위 · 한눈에): no 5-year frequency table for the new rules, the directions the trend takes now and the
  replay (가상) instead of a bare 수집 전; 거래: the trades entered before the start tagged 전환 전;
- the views in node (the tiny DOM): the hero and the position say 전환 전, the executors' rows say why they are flat, the
  empty boxes say what the bot looks at next, what to expect (가상) and the judgment changes of the last 24 h; the
  calendar draws the Nasdaq windows."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from calendar import timegm

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as LW  # noqa: E402
import test_livetrend as TL  # noqa: E402
import test_trendbot as T  # noqa: E402
from paperbot import combo as C  # noqa: E402
from paperbot import events as EV  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livetrend as LT  # noqa: E402
from paperbot.executor import ExecStore  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
CAL_JS = os.path.join(SCREENS, "livebots-cal.js")
MIN, HOUR, DAY, KST = 60_000, 3_600_000, 86_400_000, 9 * 3_600_000
BAD = re.compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")


def kst(y, mo, d, hh=0, mi=0):
    return timegm((y, mo, d, hh, mi, 0)) * 1000 - KST


def _cfg_json(w) -> dict:
    return json.loads(json.dumps(C.dataclasses.asdict(w.cfg), default=str))


def _switch(tmp_path, monkeypatch):
    """The bot before it entered a BTC long at B + 2 min; the trend bot started at SINCE = B + 10 min (its trend_since) with
    the 1h judgment against the long; bybit skipped the long as late at its restart, WOO X Pro has no record of it."""
    w = T.World(tmp_path)
    w.store.put_state("combo_run", T.T0, {"config": _cfg_json(w)})
    B, p = T._enter_long(w)
    since = B + 10 * MIN
    w.judge.j[("BTCUSDT", "1h")] = T.J(dir=-1, votes={"V39": -1, "S6": -1, "OBV": -1, "N12": 1})
    T._to(w, B + 3 * MIN, since + 2 * MIN)
    # the switch: everything before is the bot before it. Set after the last minute stepped: the trend bot closes such a
    # position at its next minute (SWITCH, owners 10/21 night), so this is the page at the switch's first minute
    w.run.since = since
    w.run._snap = None
    w.run._snapshot(since + 2 * MIN)                         # the trend state with the new start (the page reads it)
    w.run._save_state(since + 2 * MIN)
    w.store.commit()
    key = f"{L.ACCOUNT}|BTCUSDT|{p.entry_time}"
    paths = {"paper": w.cfg.db}
    for name, exch in (("bybit", "bybit"), ("mexc", "wooxpro")):
        db = str(tmp_path / f"exec-{name}.db")
        st = ExecStore(db, lock=False)
        st.put_state("meta", T.T0, {"mode": "mainnet", "account": L.ACCOUNT, "exchange": exch, "live_since": T.T0 - DAY})
        st.event(since + 5 * MIN, "INFO", "start", "시작", {"paper_db": w.cfg.db})
        if name == "bybit":
            st.event(since + 5 * MIN, "WARN", "late", "paper 진입이 780초 전이라 따라 하지 않습니다", {"key": key})
        st.put_state("bot", since + 6 * MIN, {"trade": None, "done": [key], "mode": "mainnet", "account": L.ACCOUNT,
                                              "risk": {"halted": False, "last_equity": 90.0}})
        st.close()
        paths[f"{name}_db"] = db
        paths[f"{name}_config"] = LW.config(str(tmp_path / f"{name}.json"), db, w.cfg.db, exch, 0.85, str(tmp_path / "STOP"))
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", w.cfg.paper_db)
    L._cache.clear()
    return w, B, p, since, paths


# ================================================================ 관제: the answer
def test_the_position_from_before_the_switch_and_the_executors_part_in_it(tmp_path, monkeypatch):
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    now = since + 2 * MIN
    d = json_finite(LT.build(paths, now))
    pos = d["position"]
    assert pos["symbol"] == "BTCUSDT" and pos["entry_time"] == B + 2 * MIN < since == d["since"]
    assert pos["inherited"] is True and pos["inherited_ko"] == LT.INHERITED_KO and "규칙봇 15" in LT.INHERITED_KO
    assert pos["judge_against"] is True                      # the 1h is against it: closed only on the next 1h close
    bybit, woo = pos["follow"]
    assert (bybit["id"], bybit["name_ko"], bybit["state"], bybit["kind"]) == ("bybit", "바이비트", "skip", "late")
    assert bybit["ko"] == L.WHY_KO["late"] and bybit["text"].startswith("paper 진입이 780초 전")
    assert (woo["name_ko"], woo["state"], woo["ko"]) == ("WOO X Pro", "none", "따라간 기록 없음")
    # everything of the bot counts from its start: the signal and the entry before it are the bot before it's
    f = d["funnel"]
    assert (f["from"], f["cut"], f["signals"], f["entered"], f["blocked"]) == (since, True, 0, 0, [])
    assert {m["label"]: m["today"] for m in d["members"]}["N08_ICHI_WR@30m"] == 0
    assert d["signals"]["rows"] == [] and d["signals"]["from"] == since and d["signals"]["cut"] is True
    assert d["record"]["n"] == 0 and d["trades"] == [] and d["prev"] == {"bot_ko": "규칙봇 15", "closed": []}
    # without the executors' paths (another caller): no part, never a guess
    assert LT.build({"paper": w.cfg.db}, now)["position"]["follow"] is None


def test_once_closed_it_is_listed_apart_and_never_the_bots_trade(tmp_path, monkeypatch):
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    H = T.T0 + HOUR
    T._to(w, since + 2 * MIN, H + 2 * MIN)                   # its first minute closes the position from before (SWITCH)
    w.store.commit()
    d = json_finite(LT.build(paths, H + 3 * MIN))
    assert d["position"] is None
    (x,) = d["prev"]["closed"]
    assert (x["symbol"], x["reason"], x["entry_time"]) == ("BTCUSDT", "SWITCH", B + 2 * MIN) and x["entry_time"] < since
    assert x["exit_time"] == since + 2 * MIN
    assert d["sup"] == []                                    # not a supervisor exit of this bot
    assert d["record"]["n"] == 0 and d["trades"] == []       # the bot's record starts empty


def test_the_next_entry_pause_by_the_configs_own_rules():
    cfg = {"no_weekend": True, "macro_blackout_min": None, "us_open_pause_min": 30, "us_open_pre_min": 30}
    wed = kst(2026, 10, 21, 20, 50)                          # Wednesday 20:50 KST (US summer time)
    x = LT.next_pause(cfg, wed)
    assert x == {"why": "usopen", "ko": "나스닥 개장 앞 30분·뒤 30분", "from": kst(2026, 10, 21, 22), "until": kst(2026, 10, 21, 23)}
    # inside it: the next one is the next weekday's
    assert LT.next_pause(cfg, kst(2026, 10, 21, 22, 30))["from"] == kst(2026, 10, 22, 22)
    # Friday after the Nasdaq open: the weekend, Saturday 00:00 to Monday 00:00 KST
    y = LT.next_pause(cfg, kst(2026, 10, 23, 23, 30))
    assert (y["why"], y["from"], y["until"]) == ("weekend", kst(2026, 10, 24), kst(2026, 10, 26))
    assert y["ko"] == "주말(한국 시간 토·일)"
    assert LT.next_pause({}, wed) is None                    # no rule, no pause


def test_the_replays_expectation():
    from paperbot.dash.more import livereplayref as X
    x = LT.expect_of({"trend": {"time_bars": None}})          # the owners' 10/21 night config: no 시간 정리
    d = X.load_ref()["d"]
    assert x["state"] == "ok" and x["per_weekday"] == d["entries"]["weekdays"]["mean"] and x["weekdays"] == 80
    assert x["zero_days"] == d["entries"]["hist_weekdays"]["0"] == 27 and abs(x["zero_share"] - 27 / 80) < 1e-9
    assert 0 < x["wait_q1_ms"] <= x["wait_median_ms"] <= x["wait_q3_ms"]
    assert x["time_exits"] == d["trades"]["by_reason"]["TIME"]["n"] and x["note_ko"].startswith(X.TIME_GONE_KO.format(n=x["time_exits"]))
    assert LT.expect_of({"trend": {"time_bars": 4}})["note_ko"] == X.TIME_KEPT_KO


# ================================================================ 일정 · 한눈에: the Nasdaq open is a pause window
@pytest.fixture
def cal(tmp_path, monkeypatch):
    p = LW.build_world(str(tmp_path / "w"))
    s = Store3(p["paper"])
    s.put_state("combo_run", LW.T0, {"config": {**LW.CONFIG, "us_open_pause_min": 30, "us_open_pre_min": 30}})
    s.commit()
    s.close()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setattr(EV, "all_events", lambda: [])
    monkeypatch.setattr(EV, "problems", lambda: [])
    return p


def test_the_calendar_has_the_nasdaq_open(cal):
    d = json_finite(L.calendar(cal, kst(2026, 10, 21, 20, 50)))
    assert d["rules"]["us_open_pause_min"] == 30 and d["rules"]["us_open_pre_min"] == 30
    us = [s for s in d["spans"] if s["why"] == "usopen"]
    assert [(s["from"], s["to"]) for s in us[:3]] == [(kst(2026, 10, 21, 22), kst(2026, 10, 21, 23)),
                                                      (kst(2026, 10, 22, 22), kst(2026, 10, 22, 23)),
                                                      (kst(2026, 10, 23, 22), kst(2026, 10, 23, 23))]
    assert us[0]["ko"] == "나스닥 개장 앞 30분·뒤 30분" and all(not L.kst_weekend(s["from"]) for s in us)
    n = d["now"]
    assert n["paused"] is False and n["usopen"] is None and n["next"]["why"] == "usopen" and n["next"]["from"] == kst(2026, 10, 21, 22)
    d2 = json_finite(L.calendar(cal, kst(2026, 10, 21, 22, 10)))
    n2 = d2["now"]
    assert n2["paused"] is True and n2["usopen"]["to"] == kst(2026, 10, 21, 23) and n2["pause_until"] == kst(2026, 10, 21, 23)
    assert n2["pause_ko"] == "나스닥 개장 앞 30분·뒤 30분이라 진입 쉬는 중" and n2["next"]["from"] == kst(2026, 10, 22, 22)
    # 한눈에's checklist (/now) has the line too
    w = json_finite(L.whynow(cal, kst(2026, 10, 21, 22, 10)))
    item = next(i for i in w["items"] if i["id"] == "usopen")
    assert item["ok"] is False and item["ko"] == "나스닥 개장 앞 30분·뒤 30분이라 진입 쉼" and w["next_pause"]["from"] == kst(2026, 10, 22, 22)


def test_a_config_without_it_keeps_the_answer_as_before(tmp_path, monkeypatch):
    p = LW.build_world(str(tmp_path / "w"))
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setattr(EV, "all_events", lambda: [])
    d = L.calendar(p, kst(2026, 10, 21, 20, 50))
    assert d["rules"] == {"macro_blackout_min": 30, "no_weekend": True} and d["now"]["usopen"] is None
    assert all(s["why"] != "usopen" for s in d["spans"])


# ================================================================ the views in node
JOURNAL = {"state": "ok", "judge": {"state": "ok", "pending": False}, "events": [
    {"kind": "trend", "t": T.T0 + 20 * MIN, "text": "ETH 1시간 판단이 보류에서 상승으로 바뀌었어요", "detail": "상승 3·하락 1·중립 0 · ADX 24 오름",
     "tone": "up"},
    {"kind": "signal", "t": T.T0 + 25 * MIN, "text": "신호 하나", "tone": ""}]}

VIEW = TL.VIEW.replace("const ctx = {api: () => Promise.resolve(d),",
                       "const ctx = {api: (path) => Promise.resolve(String(path).startsWith(X.JOURNAL_API) ? jr : d),")


def _view(d):
    return TL._node(f"const jr = {json.dumps(JOURNAL)};\n" + VIEW, d)


def test_the_view_of_the_switch_night(tmp_path, monkeypatch):
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    d = json.loads(json.dumps(json_finite(LT.build(paths, since + 2 * MIN))))
    d["next"]["pause"] = {"why": "usopen", "ko": "나스닥 개장 앞 30분·뒤 30분", "from": since + 3 * HOUR, "until": since + 4 * HOUR}
    out = _view(d)
    t = out["text"]
    assert not BAD.search(t), BAD.search(t)
    for words in (
            # the hero and the position: the bot before it's, closed by this one, never its trade
            "전환 전 포지션 정리 중 · BTC 롱", "전환 전 포지션 (예전 규칙봇 15가 연 것, 새 봇이 이어서 정리)",
            "예전 규칙봇 15가", "다음 1분 안에 \"전환 전 포지션 정리\"로 닫아요 (첫 잠금 전이라서)",
            "닫힐 때까지 새 봇은 새로 들어가지 않아요 (한 번에 하나)", "새 봇 성적에 세지 않아요",
            # its 1h judgment was against it from the entry: closed only if the next close is against it too
            "진입 때부터 반대 · 10:00에 끝나는 1시간봉도 반대면 감독 청산",
            # the executors: why they are flat (from their own records)
            "이 포지션 안 따라감 · 페이퍼 진입을 늦게 봐서 건너뛰었어요", "paper 진입이 780초 전이라 따라 하지 않습니다",
            "실거래 두 계좌는 이 포지션을 들고 있지 않아요",
            # nothing waits: what comes next
            "지금 기다리는 신호 없음", "다음 신호 볼 때", "30분봉 10:00 · 1시간봉 10:00", "지금 받는 방향",
            "안 해요 · 전환 전 포지션이 열려 있어요", "다음 쉬는 시간", "나스닥 개장 앞 30분·뒤 30분",
            # nothing closed yet: the replay (가상) and what it ran with
            "아직 거래 없음", "재현(가상)은 평일 하루 약 1.1번", "가상 · 재현", "7/1~10/20 실제 1분봉으로 이 규칙을 다시 돌려 보면",
            "평일 하루 약 1.1번 진입 · 진입 없는 평일도 27일 / 80일 (34%)", "아무 평일 시각에서 다음 진입까지 가운데값 약",
            "시간 정리", "재현 비교 →",
            # today from the bot's start; the judgment changes of the last 24 h
            "새 봇 시작 09:40부터 세요", "새 봇이 켜진 뒤 아직 신호가 없어요", "최근 24시간 바뀐 판단",
            "ETH 1시간 판단이 보류에서 상승으로 바뀌었어요", "상승 3·하락 1·중립 0 · ADX 24 오름", "일지에서 더 보기"):
        assert words in t, words
    assert "신호 하나" not in t                                # only the journal's judgment rows
    assert out["ms"] == [15000, 1000]                          # the journal rides on the 15 s refresh, no timer of its own


def test_the_pure_helpers():
    out = TL._node("""const H = 3600000, M = 60000;
    console.log(JSON.stringify({
      wait: [X.waitKo(40 * M), X.waitKo(17.1 * H), X.waitKo(59 * H), X.waitKo(100 * H), X.waitKo(null)],
      closes: [X.nextCloses(Date.UTC(2026, 9, 21, 11, 50, 5)), X.nextCloses(Date.UTC(2026, 9, 21, 11, 20, 5))],
      idle: [X.idleKo({halted: true}, null, null), X.idleKo({}, null, null), X.idleKo({stale: true}, null, null),
             X.idleKo({}, {}, {state: "skip", ko: "늦게 봐서 건너뛰었어요"}), X.idleKo({}, {}, {state: "none"}),
             X.idleKo({}, {}, {state: "other", ko: "자기 포지션(ETH 롱)을 들고 있어요"}), X.idleKo({}, {}, null)],
      against: [X.againstKo({htf: "1h", entry_time: 2 * H}, {bar_close: 2 * H}), X.againstKo({htf: "4h", entry_time: 2 * H}, {bar_close: 3 * H})],
      exp: [X.expectLines({state: "ok", per_weekday: 1.113, zero_days: 27, weekdays: 80, zero_share: 0.3375, wait_median_ms: 17.1 * H,
             wait_q1_ms: 6 * H, wait_q3_ms: 58.6 * H}), X.expectLines({state: "missing"}), X.expectLines(null)],
      taking: X.takingNow({coins: {BTCUSDT: {"1h": {dir: 1, strong: true}, "4h": {dir: 0}}, ETHUSDT: {"4h": {dir: -1, strong: true}}}})}));""",
                   {"now_ms": T.T0})
    assert out["wait"] == ["40분", "약 17시간", "약 59시간", "약 4일", "—"]
    assert out["closes"] == [{"m30": 1792584000000, "h1": 1792584000000, "h4": 1792584000000},   # 11:50:05 UTC: all at 12:00
                             {"m30": 1792582200000, "h1": 1792584000000, "h4": 1792584000000}]   # 11:20:05: 11:30 and 12:00
    assert out["idle"] == ["포지션 없음 · 멈춤 (사람이 풀기 전엔 새 진입 안 함)", "포지션 없음 · 따라가는 중 · 다음 페이퍼 진입을 기다려요",
                           "포지션 없음 · 따라가는 중 · 다음 페이퍼 진입을 기다려요 (기록 오래됨)", "이 포지션 안 따라감 · 늦게 봐서 건너뛰었어요",
                           "이 포지션을 따라간 기록 없음", "자기 포지션(ETH 롱)을 들고 있어요", "포지션 없음 (안 따라갔거나 이미 닫음)"]
    assert out["against"][0].startswith("진입 때부터 반대 · ") and out["against"][0].endswith("에 끝나는 1시간봉도 반대면 감독 청산")
    assert out["against"][1] == "반대로 바뀜 · 감독 청산"
    assert out["exp"][0] == ["평일 하루 약 1.1번 진입 · 진입 없는 평일도 27일 / 80일 (34%)",
                             "아무 평일 시각에서 다음 진입까지 가운데값 약 17시간 (4번 중 1번은 약 6시간 안, 4번 중 1번은 약 59시간 넘게)"]
    assert out["exp"][1] == [] and out["exp"][2] == []
    assert out["taking"] == ["BTC 30분 롱만", "ETH 1시간 숏만"]


def test_the_calendar_view_draws_the_nasdaq_windows(cal):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    d = json_finite(L.calendar(cal, kst(2026, 10, 21, 20, 50)))
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\nconst C = await import('file://{CAL_JS}');\nconst d = {json.dumps(d)};\n"
              """const ctx = {alive: () => true, every() {}, track() {}, timeout() {}, listen() {}, on() {}, href: () => "#",
      api: async (path) => { if (path !== C.API) { const e = new Error("x"); e.status = 503; throw e; } return d; }};
    const v = C.calView(ctx);
    await new Promise((r) => setTimeout(r, 30));
    const w = D.walk(v.el);
    console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes.join(" "),
      week: C.weekSummary(d.spans, d.now_ms, 7)}));""")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    t, cls = out["text"], out["classes"]
    assert "다음 쉬는 시간" in t and "나스닥 개장 앞 30분·뒤 30분" in t
    assert "나스닥 개장 앞 30분·뒤 30분 진입 안 함 · 평일 22:00~23:00 (한국 시간, 미국 서머타임 따라 움직임)" in t
    assert cls.count("lbc-blk usopen") == 5 and "lbc-week four" in cls and "5번 · 5시간" in t
    assert out["week"]["usN"] == 5 and out["week"]["usMs"] == 5 * HOUR


# ================================================================ the other tabs on the switch night
def _more(w, tmp_path):
    return {**L.paths_more(), "rule_db": w.cfg.paper_db, "combo_config": str(tmp_path / "none.json"),
            "check_db": str(tmp_path / "none-check.db"), "improve_db": str(tmp_path / "none-imp.db"), "shadow_dir": str(tmp_path / "none")}


def test_the_other_tabs_tell_the_bot_before_it_apart(tmp_path, monkeypatch):
    from paperbot.dash.more import livejournal as LJ
    from paperbot.dash.more import livepos as LP
    from paperbot.dash.more import livetrendchart as LTC
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    for k, (var, _d) in L.ENV.items():
        if k in paths:
            monkeypatch.setenv(var, paths[k])
    monkeypatch.setenv("PAPERBOT_LIVE_PAPER2_DB", str(tmp_path / "none-p2.db"))
    more = _more(w, tmp_path)
    for k, (var, _d) in L.ENV_MORE.items():
        monkeypatch.setenv(var, more[k])
    now = since + 2 * MIN
    entry = B + 2 * MIN
    # 추세 차트: the start on the heat; the entry and its signal before it are the bot before it's
    no_bars = LTC.Bars(fetch=lambda s, tf, n: [], now_ms=lambda: now)
    c = json_finite(LTC.build(paths, "BTCUSDT", now, b=no_bars))
    assert c["since"] == since
    (m,) = [x for x in c["marks"]["entries"] if x["t"] == entry]
    assert m["open"] is True and m["before"] is True and c["chart"]["position"]["before"] is True
    (s,) = c["chart"]["signals"]
    assert s["t"] == B and s["before"] is True and (s["kind"], s["kind_ko"]) == ("prev", "전환 전 · 예전 봇 신호")
    # 일지: the open position tagged, not counted as the new bot's entry
    j = json_finite(LJ.build(paths, 24, now, more, b=no_bars))
    (e,) = [x for x in j["events"] if x["kind"] == "trade" and not x.get("twin")]
    assert e["prev"] is True and "새 봇이 이어서 정리해요" in e["detail"]
    assert (j["counts"]["entered"], j["counts"]["prev_entered"]) == (0, 1)
    assert any(n.startswith(LJ.PREV_KO) for n in j["notes"])
    # 신호: counted from the start, the older rows flagged
    sg = L.read_signals(w.cfg.db, L.ACCOUNT, now)
    assert sg["bot_since"] == since and sg["stages"]["today"]["signals"] == 0 and sg["stages"]["week"]["entered"] == 0
    assert sg["rows"] and [r["prev"] for r in sg["rows"]] == [True] * len(sg["rows"])
    # 포지션: the role (never the old A/B group), 전환 전, why each executor is flat
    pos = json_finite(LP.build(paths, more, now))
    card = next(x for x in pos["cards"] if x["id"] == "paper")["position"]
    assert pos["rules"]["trend"] is True and card["setting"]["role"] == "눌림"
    assert card["inherited"] is True and card["inherited_ko"] == LT.INHERITED_KO
    by = {x["id"]: x for x in card["execs"]}
    assert by["bybit"]["why_ko"] == L.WHY_KO["late"] and by["bybit"]["why_text"].startswith("paper 진입이 780초 전")
    assert by["mexc"]["state"] == "none" and by["mexc"]["why_ko"] is None


def test_health_names_the_second_slot_by_its_exchange(tmp_path, monkeypatch):
    from paperbot.dash.more import liveinsight as LI
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    d = json.dumps(json_finite(LI.health({**paths, "paper2": str(tmp_path / "none-p2.db")}, since + 2 * MIN, _more(w, tmp_path))),
                   ensure_ascii=False)
    assert "WOO X Pro 실행기" in d and "MEXC 실행기" not in d and "바이비트 실행기" in d


def test_review_says_the_time_exit_was_taken_out(tmp_path, monkeypatch):
    from paperbot.dash.more import livereview as LR
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    cfg = _cfg_json(w)
    cfg["trend"] = {**(cfg.get("trend") or {}), "time_bars": None}          # the owners' 10/21 night rule
    w.store.put_state("combo_run", T.T0, {"config": cfg})
    w.store.commit()
    d = json_finite(LR.build(paths, since + 2 * MIN, _more(w, tmp_path), budget_s=0.5))
    t = next(x for x in d["whatif"]["items"] if x["id"] == "time")
    assert t["off"] is True and t["rule_ko"] == LR.TIME_OFF_RULE_KO and t["verdict"] == {"kind": "off", "ko": LR.TIME_OFF_KO}
    j = next(x for x in d["whatif"]["items"] if x["id"] == "judge")
    assert "off" not in j


def test_the_replay_words_on_the_first_day():
    from paperbot.dash.more import livereplayref as X
    assert [X.weekdays_ko(x) for x in (1 / 48, 0.25, 1.0, 2.46)] == ["평일 30분", "평일 6시간", "평일 1.0일", "평일 2.5일"]
    band = {"lo": 0, "hi": 1, "where": "inside"}
    ko = X.entries_ko({"weekdays": 1 / 48, "entries": 0}, band)
    assert ko.startswith("새 규칙 시작 뒤 평일 30분 동안 0번 들어갔어요 · 재현이라면 보통 0~1번 · 그 안이에요") and "0.0일" not in ko
    assert X.entries_ko({"weekdays": 2.0, "entries": 3}, band).startswith("평일 2.0일 동안 3번")


def test_the_pages_words_in_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    kit = os.path.join(SCREENS, "livebots-kit.js")
    expect = os.path.join(SCREENS, "livebots-expect.js")
    review = os.path.join(SCREENS, "livebots-review.js")
    script = (f"const K = await import('file://{kit}');\nconst E = await import('file://{expect}');\n"
              f"const R = await import('file://{review}');\n"
              "console.log(JSON.stringify({note: K.paperSinceNote({trend_bot: {name: '추세판단 봇', since: Date.UTC(2026, 9, 21, 11, 20)}, checkpoint: {n: 0}}),"
              " none: K.paperSinceNote({trend_bot: null}), wd: [E.weekdaysKo(1 / 48), E.weekdaysKo(0.5), E.weekdaysKo(3.04), E.weekdaysKo(null)],"
              " off: R.verdictChip('off')}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["note"] == ["추세판단 봇 10/21 20:20 시작 · 위 잔고와 닫힌 거래는 계좌 전체 (그 전 예전 봇 거래 포함) · 새 봇 닫힌 거래 0번"]
    assert out["none"] is None and out["wd"] == ["평일 30분", "평일 12시간", "평일 3.0일", "평일 —"]
    assert out["off"] == {"ko": "뺀 규칙", "cls": "thin"}


# ================================================================ 진입 가능성 · 거래 on the switch night
def test_taking_now_is_the_maps_long_only_and_short_only():
    st = {"coins": {"ETHUSDT": {"1h": {"dir": 1, "strong": False}, "4h": {"dir": -1, "strong": True, "tired": True}},
                    "BTCUSDT": {"1h": {"dir": 0}, "4h": {"dir": 1, "strong": True}}, "SOLUSDT": {"1h": {"error": "x"}, "4h": "?"}}}
    assert LT.taking_now(st) == [{"symbol": "BTCUSDT", "htf": "4h", "entry": "1h", "side": 1}]     # coins in the site's order
    assert LT.taking_now({}) == [] and LT.taking_now(None) == []


def test_likely_says_what_the_trend_takes_now_instead_of_a_bare_table(tmp_path, monkeypatch):
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    monkeypatch.setattr(L, "LIKELY_FILE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none.json"))
    now = since + 2 * MIN
    # 한눈에 (/now): the trend bot has no 5-year frequencies for its new rules, never a bare 수집 전
    lk = json_finite(L.whynow(paths, now))["likely"]
    assert (lk["state"], lk["reason_ko"], lk["table_ko"]) == ("trend", L.LIKELY_TREND_KO, L.LIKELY_MISSING_KO)
    assert lk["taking"][0] == {"symbol": "BTCUSDT", "htf": "1h", "entry": "30m", "side": -1}       # the 1h judgment against the long
    assert lk["expect"]["state"] == "ok" and lk["expect"]["per_weekday"] > 0
    # 순위 › 진입 가능성: the same, what stops an entry now and the bot
    d = json_finite(L.likely(paths, now))
    assert d["state"] == "trend" and d["rows"] == [] and d["taking"] == lk["taking"] and d["trend_bot"]["since"] == since
    assert d["blocked_ko"] and "포지션" in d["blocked_ko"]
    # another bot keeps the answer as before (수집 전 + why)
    monkeypatch.setattr(L, "trend_bot", lambda path: None)
    assert json_finite(L.likely(paths, now))["state"] == "missing"
    # the view: the directions, the replay (가상), no frequency windows, no "풀리면 이 순서예요"
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    js = os.path.join(SCREENS, "livebots-likely.js")
    hq = os.path.join(SCREENS, "livebots-hq.js")
    script = (f"const D = await import('{dom}');\nconst X = await import('file://{js}');\nconst Q = await import('file://{hq}');\n"
              f"const d = {json.dumps(d)};\nconst lk = {json.dumps(lk)};\n"
              """const ctx = {api: () => Promise.resolve(d), every() {}, watch() {}, alive: () => true, href: () => "#", track() {}};
    const card = D.walk(Q.likelyCard({likely: lk}, "#/livebots/rank")).text.replace(/\\s+/g, " ");
    const v = X.likelyView(ctx);
    await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
    const w = D.walk(v.el);
    const hiddenSeg = (function f(n) { for (const c of (n && n.childNodes) || []) {
      if (c.attributes && c.attributes["aria-label"] === "몇 시간 안에") return !!c.hidden; const x = f(c); if (x !== null) return x; } return null; })(v.el);
    console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), seg: hiddenSeg, card, head: Q.LIKELY_HEAD,
      take: X.takingKo([{symbol: "SOLUSDT", entry: "30m", side: 1}, {symbol: "ETHUSDT", entry: "1h", side: -1}])}));""")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    t = out["text"]
    assert not BAD.search(t), BAD.search(t)
    for words in (L.LIKELY_TREND_KO, "지금 추세가 받는 방향", "BTC 30분 진입 숏만", "가상 · 재현", "평일 하루 약 1.1번 진입",
                  "지금은 진입 안 해요: "):
        assert words in t, words
    assert "풀리면 이 순서예요" not in t and out["seg"] is True and out["take"] == ["SOL 30분 진입 롱만", "ETH 1시간 진입 숏만"]
    # 한눈에's card: the same in short, said to be 가상, the replay's 시간 정리 said; never the 5-year table's words
    c = out["card"]
    assert not BAD.search(c), BAD.search(c)
    for words in ("지금 추세가 받는 방향", "BTC 30분 진입 숏만", "평일 하루 약 1.1번 진입", "가상(재현) 숫자", "시간 정리",
                  "이길 확률이 아니라 진입이 얼마나 자주인지예요", "자세히: 순위 탭"):
        assert words in c, words
    assert "신호가 나오는 빈도" not in c and out["head"]["trend"] == ["진입 가능성", "지금 추세가 받는 방향 · 재현(가상)"]


def test_trades_entered_before_the_start_are_tagged(tmp_path, monkeypatch):
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    H = T.T0 + HOUR                                          # closed by the trend bot's supervisor at the first 1h close
    T._to(w, since + 2 * MIN, H + 2 * MIN)
    w.store.commit()
    L._cache.clear()
    d = json_finite(L.trade_rows(paths, H + 3 * MIN, _more(w, tmp_path)))
    assert d["trend_bot"]["since"] == since
    (r,) = d["accts"]["paper"]["rows"]
    assert r["entry_time"] < since
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    js = os.path.join(SCREENS, "livebots-trades.js")
    script = (f"const D = await import('{dom}');\nconst X = await import('file://{js}');\nconst d = {json.dumps(d)};\n"
              """const ctx = {params: {query: {acct: "paper"}}, every() {}, watch() {}, alive: () => true, href: () => "#", track() {},
      api: (path) => (path === "/api/v4/livebots/trades" ? Promise.resolve(d) : Promise.reject(Object.assign(new Error("x"), {status: 503})))};
    const v = X.tradesView(ctx);
    await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
    const w = D.walk(v.el);
    const n = JSON.parse(JSON.stringify(d)); n.trend_bot = null;
    const v2 = X.tradesView({...ctx, api: (path) => (path === "/api/v4/livebots/trades" ? Promise.resolve(n) : ctx.api(path))});
    await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
    console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), other: D.walk(v2.el).text.replace(/\\s+/g, " ")}));""")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "전환 전" in out["text"] and "전환 전 포지션 정리" in out["text"]
    # another bot: no tag (only the exit reason's own words "전환 전 포지션 정리")
    assert out["other"].count("전환 전") == out["other"].count("전환 전 포지션 정리")


# ================================================================ the leftovers of the switch night (한눈에 · 성적 · 지도 · 위험 · 설정 · 다시보기)
def _js(tmp_path, body: str, now: int, **data) -> dict:
    """``body`` in node with the tiny DOM, the clock at ``now`` (the world's), the screens as HQ · P · MP · RV · MO · RP · K
    and each answer as D_<name>; ``shown(node)`` is the text a reader sees (hidden parts left out)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    loads = []
    for k, v in data.items():
        f = tmp_path / f"js-{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    mods = "".join(f"const {n} = await import('file://{SCREENS}/livebots-{f}.js');\n" for n, f in (
        ("HQ", "hq"), ("P", "perf"), ("MP", "map"), ("RV", "risk"), ("MO", "more"), ("RP", "replay"), ("K", "kit")))
    dom = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"Date.now = () => {int(now)};\nconst D = await import('file://{dom}'); const fs = await import('node:fs');\n" + mods
              + "\n".join(loads) + "\n"
              "globalThis.location = {hash: ''};\n"
              "const tick = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 2)); };\n"
              "const shown = (n) => { const out = []; const go = (x) => { if (x == null) return; if (x instanceof Text) { out.push(x.t); return; }"
              " if (x.hidden === true) return; x.childNodes.forEach(go); }; go(n); return out.join(' ').replace(/\\s+/g, ' '); };\n"
              "const mkCtx = (answers) => ({params: {query: {}, arg: ''}, alive: () => true, track() {}, listen() {}, on() {}, watch() {},"
              " timeout() {}, href: (n, a) => '#/' + n + (a ? '/' + a : ''), every(ms, fn, o) { if (o && o.now === false) return; fn(); },"
              " api: async (path) => { const k = Object.keys(answers).find((p) => String(path).startsWith(p));"
              " if (k === undefined) throw Object.assign(new Error('x'), {status: 503}); return JSON.parse(JSON.stringify(answers[k])); }});\n"
              + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _rows_of(db: str) -> list:
    return L.read_paper(db, [L.ACCOUNT], 0)["accounts"][L.ACCOUNT]["trades"]


def _old_losses(db: str) -> None:
    """Two losses of the bot before it, closed before the trend bot's start (a streak of 2 on the whole account)."""
    d = {"side": 1, "entry_price": 100.0, "exit_price": 99.0, "qty": 10.0, "margin": 300.0, "fees": 0.5, "strategy_id": "F3_BOS",
         "timeframe": "30m", "stop_initial": 99.0, "stop_price": 99.0}
    s = Store3(db)
    for k, (pnl, eq) in enumerate(((-20.0, 980.0), (-10.0, 970.0))):
        s.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (L.ACCOUNT, "SOLUSDT", T.T0 - (4 - k) * HOUR, T.T0 - (3 - k) * HOUR, "SL", 30, pnl, -0.5, eq, json.dumps(d)))
    s.commit()
    s.close()


def test_hq_counts_the_new_bots_entries_and_names_it(tmp_path, monkeypatch):
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none.json"))
    now = since + 2 * MIN
    d = json_finite(L.build(paths, now))
    assert d["trend_bot"]["since"] == since
    # the summary's fills still carry the bot before it's entry (요약 lists it); the dial leaves it out
    assert [f["t"] for f in d["fills"] if f["kind"] == "entry" and f["acct"] == "paper"] == [B + 2 * MIN]
    assert next(a for a in d["accts"] if a["id"] == "paper")["sub_ko"] == "추세판단 봇"
    a = {"d": d, "now": L.whynow(paths, now), "cal": L.calendar(paths, now), "rank": L.rank(paths, now)}
    out = _js(tmp_path, """const d0 = HQ.kstDayStart(Date.now()), since = D_a.d.trend_bot.since;
    const mine = HQ.dayDots(D_a.d.fills, d0, since), all = HQ.dayDots(D_a.d.fills, d0);
    const c = mkCtx({"/api/v4/livebots/now": D_a.now, "/api/v4/livebots/calendar": D_a.cal, "/api/v4/livebots/rank": D_a.rank});
    const v = HQ.hqView(c, {get: () => null, state: () => "loading", at: () => 0, retry: () => {}});
    const before = shown(v.el);
    await tick(); v.set(D_a.d, "ok"); await tick();
    console.log(JSON.stringify({d0, mine: mine.length, all: all.length,
      words: [HQ.dayEntriesKo(mine, d0, since, []), HQ.dayEntriesKo(all, d0, null, all.map((x) => K.acctKo(x.acct))),
              HQ.dayEntriesKo([], d0, d0 - 3600000, []), HQ.dayEntriesKo(all, d0, d0 + 3600000, ["바이비트", "바이비트"])],
      side: [HQ.sideBotKo(undefined), HQ.sideBotKo(null), HQ.sideBotKo(D_a.d.trend_bot)], bot: [K.paperBotKo(null), K.paperBotKo({name: "추세판단 봇"})],
      before, text: shown(v.el)}));""", now, a=a)
    assert out["d0"] == kst(2026, 10, 5) and (out["mine"], out["all"]) == (0, 1)
    assert out["words"] == ["새 봇 시작 09:40 뒤 아직 없음", "1번 (페이퍼(연습))", "아직 없음", "새 봇 시작 01:00 뒤 1번 (바이비트)"]
    assert out["side"] == ["COMBO@MIX · 보기만 · 주문 없음", "A+C 합본 · COMBO@MIX · 보기만 · 주문 없음", "추세판단 봇 · COMBO@MIX · 보기만 · 주문 없음"]
    assert out["bot"] == ["A+C 합본", "추세판단 봇"]
    assert "A+C" not in out["before"]                        # before the first summary: no bot's name, never the old one
    t = out["text"]
    assert not BAD.search(t), BAD.search(t)
    for words in ("오늘 24시간", "오늘 진입 새 봇 시작 09:40 뒤 아직 없음", "추세판단 봇 · COMBO@MIX · 보기만 · 주문 없음",
                  "페이퍼(연습) 추세판단 봇 COMBO@mix · 게이지의 순ROE"):
        assert words in t, words
    assert "A+C" not in t


def test_perf_and_map_say_once_that_the_new_bot_has_no_trade_yet(tmp_path, monkeypatch):
    from paperbot.dash.more import liveinsight as LI
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none.json"))
    more = _more(w, tmp_path)
    now = since + 2 * MIN
    pf, mp = json_finite(L.perf(paths, now, more)), json_finite(L.map_view(paths, now))
    for d in (pf, mp):
        e = d["empty"]
        assert e["ko"] == L.TREND_EMPTY_KO == "새 봇 거래 아직 없음 · 첫 거래가 닫히면 채워져요" and e["since"] == since
        assert e["expect"]["state"] == "ok" and e["expect"]["per_weekday"] > 0                  # the replay's (가상)
    # the switch closed the position from before: still none of its own (that close is the bot before it's)
    H = T.T0 + HOUR
    T._to(w, since + 2 * MIN, H + 2 * MIN)
    w.store.commit()
    L._cache.clear()
    assert L.perf(paths, H + 3 * MIN, more)["empty"]["ko"] == L.TREND_EMPTY_KO and L.map_view(paths, H + 3 * MIN)["empty"]
    # from its first closed trade on, or for another bot: none (the pages as before)
    tb = L.trend_bot(w.cfg.db)
    assert L.trend_empty(tb, 1) is None and L.trend_empty(None, 0) is None and L.trend_empty(tb, 0)["since"] == since
    groups = LI.groups(paths, now, more)
    out = _js(tmp_path, """const pv = P.perfView(mkCtx({"/api/v4/livebots/perf": D_pf, "/api/v4/livebots/groups": D_gr}));
    const mv = MP.mapView(mkCtx({"/api/v4/livebots/map": D_mp}));
    await tick();
    console.log(JSON.stringify({pf: shown(pv.el), mp: shown(mv.el), card: shown(P.freshCard(D_pf.empty, "#/livebots/expect"))}));""",
              now, pf=pf, mp=mp, gr=groups)
    for k in ("pf", "mp"):
        t = out[k]
        assert not BAD.search(t), (k, BAD.search(t))
        for words in (L.TREND_EMPTY_KO, "가상 · 재현", "7/1~10/20 실제 1분봉으로 이 규칙을 다시 돌려 보면", "평일 하루 약 1.1번 진입",
                      "아무 평일 시각에서 다음 진입까지 가운데값", "재현 비교 →"):
            assert words in t, (k, words)
        assert t.count(L.TREND_EMPTY_KO) == 1, k
    pft, mpt = out["pf"], out["mp"]
    # 성적: the zero tables go (승률 흐름 · 그룹별 성적 · 나눠 보기 · 동전 쌍둥이 · the account switch); the 2-week review stays
    for gone in ("승률 흐름", "그룹별 성적", "나눠 보기", "동전 쌍둥이 (참고)", "0번 · 승률", "계좌 고르기", "기준 없음"):
        assert gone not in pft, gone
    assert "2주 검토까지" in pft and "추세판단 봇 시작 10/05 09:40부터" in pft
    # 지도: no wins chart, no splits of "거래 없음", no reading guide; the footer names the bot
    for gone in ("진입 때 추세 판단", "거래 없음", "숫자 읽는 법", "거래가 쌓이면", "0승"):
        assert gone not in mpt, gone
    assert "추세판단 봇 시작 10/05 09:40부터" in mpt and "페이퍼(연습) 추세판단 봇의 닫힌 거래" in mpt and "A+C" not in mpt
    assert out["card"].startswith("새 봇 성적 10/05 09:40 시작부터 · 닫힌 거래 기준 " + L.TREND_EMPTY_KO)


def test_risk_counts_the_new_bots_trades_and_leaves_the_executors_whole(tmp_path, monkeypatch):
    from paperbot.dash.more import liveinsight as LI
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none.json"))
    _old_losses(w.cfg.db)
    more = _more(w, tmp_path)
    now = since + 2 * MIN
    assert LI.loss_streak(_rows_of(w.cfg.db)) == 2                      # the whole account: the bot before it's two losses
    d = json_finite(LI.risk(paths, now, more))
    by = {a["id"]: a for a in d["accts"]}
    pa = by["paper"]
    assert (pa["streak"], pa["n"], pa["from_ms"], pa["from_ko"]) == (0, 0, since, LI.RISK_FROM_KO) and LI.RISK_FROM_KO == "새 봇 시작 뒤"
    # its position from before is still open: the new bot has not traded, nothing is down from its own peak
    assert pa["peak"] == pa["balance"] and pa["drawdown"] == 0
    for x in ("bybit", "mexc"):                                           # the executors' are their real accounts' (as before)
        assert "from_ko" not in by[x] and "n" not in by[x]
    # the switch's close (the bot before it's) is not the new bot's either: its peak starts at the balance it left
    H = T.T0 + HOUR
    T._to(w, since + 2 * MIN, H + 2 * MIN)
    w.store.commit()
    L._cache.clear()
    sw = next(t for t in _rows_of(w.cfg.db) if t["exit_reason"] == "SWITCH")
    d2 = json_finite(LI.risk(paths, H + 3 * MIN, more))
    pa2 = next(a for a in d2["accts"] if a["id"] == "paper")
    assert (pa2["streak"], pa2["n"]) == (0, 0) and pa2["peak"] == sw["equity_after"] == pa2["balance"] and pa2["drawdown"] == 0
    out = _js(tmp_path, """const v = RV.riskView(mkCtx({"/api/v4/livebots/risk": D_r}));
    await tick();
    console.log(JSON.stringify({text: shown(v.el), w: [RV.fromWords(D_r.accts.find((a) => a.id === "paper")), RV.fromWords({}), RV.fromWords(null)]}));""",
              now, r=d)
    t = out["text"]
    assert not BAD.search(t), BAD.search(t)
    assert "연속 손실 0번 (새 봇 시작 뒤)" in t and "(새 봇 시작 뒤 최고" in t and t.count("(새 봇 시작 뒤)") == 1
    assert out["w"] == ["연속 손실과 최고점은 새 봇 시작(10/05 09:40) 뒤 거래만 세요 · 새 봇 닫힌 거래 0번 · 잔고는 계좌 전체예요", None, None]


def test_settings_and_the_labels_use_the_trend_bots_name(tmp_path, monkeypatch):
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none.json"))
    now = since + 2 * MIN
    st = json_finite(L.settings(paths, now))
    assert st["trend"]["name"] == "추세판단 봇" and st["rules"]["name"] == "추세판단 봇"
    # a trend config without a name: still the trend bot's name (livebots TREND_NAME_KO), never the old A+C label
    cfg = _cfg_json(w)
    cfg["name"] = None
    w.store.put_state("combo_run", T.T0, {"config": cfg})
    w.store.commit()
    L._cache.clear()
    assert L.read_paper(w.cfg.db, [L.ACCOUNT], now)["name_ko"] == L.TREND_NAME_KO == L.trend_bot(w.cfg.db)["name"]
    assert next(a for a in L.build(paths, now)["accts"] if a["id"] == "paper")["sub_ko"] == L.TREND_NAME_KO
    out = _js(tmp_path, """const v = MO.settingsView(mkCtx({"/api/v4/livebots/settings": D_st}));
    await tick();
    console.log(JSON.stringify({text: shown(v.el), sub: [MO.rulesSub(D_st.trend), MO.rulesSub(null)]}));""", now, st=st)
    t = out["text"]
    assert not BAD.search(t), BAD.search(t)
    assert "추세판단 봇의 모든 설정이 같이 쓰는 규칙" in t and "합친 봇의" not in t and "A+C" not in t
    assert out["sub"] == ["추세판단 봇의 모든 설정이 같이 쓰는 규칙", "합친 봇의 모든 설정이 같이 쓰는 규칙"]


def test_replay_tags_the_trade_from_before_and_says_the_switch(tmp_path, monkeypatch):
    from paperbot.dash.more import livetape as R
    w, B, p, since, paths = _switch(tmp_path, monkeypatch)
    more = _more(w, tmp_path)
    H = T.T0 + HOUR
    T._to(w, since + 2 * MIN, H + 2 * MIN)                   # its first minute closes the position from before (SWITCH)
    w.store.commit()
    L._cache.clear()
    now = H + 3 * MIN
    ls = json_finite(R.build_list(paths, now_ms=now))
    (r,) = ls["rows"]
    assert (r["exit_reason"], r["reason_ko"], r["prev"]) == ("SWITCH", "전환 전 포지션 정리", True) and ls["trend_bot"]["since"] == since
    one = json_finite(R.build_one(paths, r["id"], now_ms=now, more=more))
    assert one["trade"]["prev"] is True and one["trend_bot"]["since"] == since and one["exit"]["record"]["reason_ko"] == "전환 전 포지션 정리"
    # the switch closed it, not the bars: its minute is the record's (never 기록과 다름), the locks up to it are checked
    assert one["check"]["state"] == "same" and one["check"]["why_ko"] == R.SWITCH_KO and one["exit"]["stopped"] == "outside"
    assert R._prev({"entry_time": B}, None) is False and R._prev({"entry_time": since}, {"since": since}) is False
    out = _js(tmp_path, f"""const v = RP.replayView(mkCtx({{"/api/v4/livebots/replay/{r['id']}": D_one, "/api/v4/livebots/replay": D_ls}}));
    await tick();
    console.log(JSON.stringify({{text: shown(v.el), ko: [RP.prevKo(D_one.trade), RP.prevKo({{prev: true, exit_reason: "SL"}}), RP.prevKo({{prev: false}}), RP.prevKo(null)]}}));""",
              now, one=one, ls=ls)
    t = out["text"]
    assert not BAD.search(t), BAD.search(t)
    for words in ("전환 전 포지션 정리", "기록과 같음", "새 봇(추세판단 봇)이 켜지며 예전 봇의 포지션을 닫은 거래",
                  "예전 봇이 연 포지션을 새 봇(추세판단 봇)이 켜지며 바로 닫았어요 (전환 전 포지션 정리) · 새 봇 성적에 세지 않아요"):
        assert words in t, words
    assert "기록과 다름" not in t
    assert t.count("전환 전") - t.count("전환 전 포지션 정리") >= 3                 # the tag: the list row, the head, the result
    assert out["ko"][1] == "새 봇(추세판단 봇)이 켜지기 전 예전 봇의 거래예요 · 새 봇 성적에 세지 않아요" and out["ko"][2:] == [None, None]
