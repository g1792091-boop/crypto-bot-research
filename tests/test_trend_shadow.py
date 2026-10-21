"""추세판단 봇's shadow paper bots (owners 10/21: rule variants side by side, at no money cost, so the 11/04 review decides
with numbers; docs/trend-bot-ko.md "그림자 비교 봇").

- the three configs: deploy/combo.trend.json with exactly ONE change each (trend-time: trend.time_bars 4, trend-now:
  trend.pullback_wait false, trend-vote4: trend.vote_min 4) plus their own name, database and "telegram": false; they pass
  check-config ("준비됨") and the unit's start guard (db = shadow-<id>.db, telegram false);
- trend-now (TrendRules.pullback_wait false): a signal that passed the checks enters at its own minute like the combined
  bot's (the coin-flip twin its own side, the score ranks one minute's signals), its SUBMITTED row keeps the judgment; a
  signal against the trend is still filtered and still closes the open position; the live config (no pullback_wait) waits
  exactly as before, word for word;
- the 그림자 tab (livebots.shadows ``trend``, dash/more/liveshadow.py): each shadow next to the live paper from its own
  start, by trade and net ROE (never dollars), its one difference checked from its own start record, 표본 적음 under 20,
  아직 안 켬 with the command that starts it (never a zero); the old bots' shadows only over the old bot's days;
- the view in node draws those answers."""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as LW  # noqa: E402
import test_trendbot as T  # noqa: E402
from paperbot import combo as C  # noqa: E402
from paperbot import trendjudge as TJ  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import liveshadow as LS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy"
LIVE = DEPLOY / "combo.trend.json"
UNIT = DEPLOY / "paperbot-combo-shadow@.service"
SCREENS = REPO / "paperbot" / "dash" / "static" / "v4" / "screens"
DOM = REPO / "tests" / "anasyn_dom.mjs"
MIN, HOUR, DAY = T.MIN, T.HOUR, 86_400_000
# tag -> (name, the one trend key, its value)
SHADOWS = {"trend-time": ("그림자 시간 정리 있음", "time_bars", 4),
           "trend-now": ("그림자 되돌림 없이 바로 진입", "pullback_wait", False),
           "trend-vote4": ("그림자 판단 4개 모두 같은 쪽", "vote_min", 4)}
OWN = ("db", "name", "telegram")
BAD = re.compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")


def _load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _path(tag: str) -> Path:
    return DEPLOY / f"combo.shadow-{tag}.json"


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


# ====================================================================== the configs
@pytest.mark.parametrize("tag", sorted(SHADOWS))
def test_each_trend_shadow_is_the_live_trend_bot_with_one_change(tag):
    live, sh = _load(LIVE), _load(_path(tag))
    name, key, value = SHADOWS[tag]
    assert {k: v for k, v in sh.items() if k not in OWN + ("trend",)} == {k: v for k, v in live.items() if k not in OWN + ("trend",)}
    assert [k for k in sh if k != "trend"] == [k for k in live if k != "trend"]           # the same keys, the same order
    changed = {k for k in set(sh["trend"]) | set(live["trend"]) if sh["trend"].get(k, "∅") != live["trend"].get(k, "∅")}
    assert changed == {key} and sh["trend"][key] == value
    assert sh["db"] == f"/var/lib/paperbot/combo/shadow-{tag}.db" and sh["telegram"] is False and sh["name"] == name
    assert live["db"] == "/var/lib/paperbot/combo/live-ac.db" and live["telegram"] is True        # the live bot untouched
    # the rules the bot reads: the live bot's with that one field
    want = dataclasses.replace(TJ.TrendRules.from_dict(live["trend"]), **{key: value})
    assert TJ.TrendRules.from_dict(sh["trend"]) == want
    # no other config in the repository writes its database, and no executor follows it
    dbs = {_load(p)["db"] for p in DEPLOY.glob("combo.*.json") if p != _path(tag)
           and not p.name.endswith((".expected.json", ".likely.json"))}
    assert sh["db"] not in dbs
    named = set()
    for p in list((REPO / "docs").glob("*.md")) + list(DEPLOY.glob("*.json")) + list(DEPLOY.glob("*.example")):
        named |= set(re.findall(r'"paper_db"\s*:\s*"([^"]+)"', p.read_text(encoding="utf-8", errors="replace")))
    assert sh["db"] not in named


@pytest.mark.parametrize("tag", sorted(SHADOWS))
def test_each_trend_shadow_passes_check_config(tag, capsys):
    cfg = C.ComboConfig.from_file(str(_path(tag)))
    assert cfg.problems() == [] and cfg.trend is not None and cfg.telegram is False
    assert C.make_cls(cfg).func.__name__ == "TrendEngine"
    assert C.main(["check-config", "--config", str(_path(tag))]) == 0
    out = capsys.readouterr().out
    assert out.rstrip().splitlines()[-1] == "준비됨" and "[문제]" not in out
    words = {"trend-time": "진입 봉 4개 안에 첫 잠금 못 가면 청산", "trend-now": "되돌림을 기다리지 않고 검사를 통과한 신호에 바로 진입",
             "trend-vote4": "중 4개 모두 같은 쪽"}[tag]
    assert words in out


def _guard() -> list:
    lines = [ln.strip() for ln in UNIT.read_text(encoding="utf-8").splitlines() if ln.strip().startswith("ExecStartPre=")]
    argv = shlex.split(lines[0].split("=", 1)[1])
    assert argv[0] == "/opt/paperbot/venv/bin/python" and argv[1] == "-c"
    assert argv[3:] == ["/opt/crypto-bot-research/deploy/combo.shadow-%i.json", "%i"]
    return [sys.executable] + argv[1:3]


@pytest.mark.parametrize("tag", sorted(SHADOWS))
def test_each_trend_shadow_passes_the_units_start_guard(tag):
    r = subprocess.run(_guard() + [str(_path(tag)), tag], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    other = next(t for t in SHADOWS if t != tag)                       # never another shadow's database
    assert subprocess.run(_guard() + [str(_path(tag)), other], capture_output=True, text=True).returncode != 0
    # the live config itself is refused as a shadow (its database is the executors' paper_db, Telegram on)
    assert subprocess.run(_guard() + [str(LIVE), tag], capture_output=True, text=True).returncode != 0


def test_the_docs_and_the_morning_check_name_them():
    doc = (REPO / "docs" / "trend-bot-ko.md").read_text(encoding="utf-8")
    sec = doc.split("그림자 비교 봇")[1]
    for tag in SHADOWS:
        assert f"sudo systemctl start paperbot-combo-shadow@{tag}" in sec and f"`{tag}`" in sec, tag
    for w in ("sudo systemctl stop paperbot-combo-shadow@trend-time", "약 2분", "MemoryMax=768M", "표본 적음 · 아직 판단 못 함",
              "trend.time_bars: 4", "trend.pullback_wait: false", "trend.vote_min: 4"):
        assert w in sec, w
    assert "**그림자**" in (REPO / "docs" / "livedash-ko.md").read_text(encoding="utf-8")
    from paperbot import livecheck as LC
    for tag, (name, _k, _v) in SHADOWS.items():
        assert LC.SHADOW_NAMES[f"shadow-{tag}"] == name
    unit = UNIT.read_text(encoding="utf-8")
    assert all(f"@{tag}" in unit for tag in SHADOWS)


# ====================================================================== trend-now
def test_the_live_config_still_waits_for_the_pullback_word_for_word(tmp_path):
    live = _load(LIVE)["trend"]
    r = TJ.TrendRules.from_dict(live)
    assert "pullback_wait" not in live and r.pullback_wait is True and TJ.TrendRules().pullback_wait is True
    assert r.describe()[2] == ("진입 방식: 진입 봉 하나 동안 0.25 ATR 되돌림을 기다림(신호 봉이 2 ATR 넘는 장대봉이면 0.5 ATR), 안 오면 버림 / "
                               "동시 신호는 점수(판단 강도+자리+최근 성적)")
    assert "3개 이상 같은 쪽" in r.describe()[0]
    # the live trend section in the runner: waits (WAITING), touches, enters the minute after (as before)
    w = T.World(tmp_path, trend=live)
    B, p = T._enter_long(w)
    assert [(bc, st) for bc, st, _d in w.rows("N08_ICHI_WR@30m")] == [(B, "BROKE"), (B + 2 * MIN, "SUBMITTED")]
    assert p.signal.meta["pulled"] and w.run.counts["N08_ICHI_WR@30m"] == {"waiting": 1, "submitted": 1}
    # an explicit true is the same rules
    assert TJ.TrendRules.from_dict({**live, "pullback_wait": True}) == r


def test_the_live_rules_read_as_before_the_option(tmp_path):
    """The live config's rules and their words equal those of trendjudge.py before pullback_wait existed (commit b270569)."""
    if not shutil.which("git"):
        pytest.skip("needs git")
    r = subprocess.run(["git", "-C", str(REPO), "show", "b270569:paperbot/trendjudge.py"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("commit b270569 not in this checkout")
    import importlib.util
    f = tmp_path / "trendjudge_before.py"
    f.write_text(r.stdout.replace("from . import sweepsig", "from paperbot import sweepsig"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("trendjudge_before", f)
    old = importlib.util.module_from_spec(spec)
    sys.modules["trendjudge_before"] = old             # (its dataclasses look their module up)
    try:
        spec.loader.exec_module(old)
    finally:
        sys.modules.pop("trendjudge_before", None)
    for trend in (_load(LIVE)["trend"], {}, {"time_bars": 4}, {"vote_min": 4}):
        a, b = TJ.TrendRules.from_dict(trend), old.TrendRules.from_dict(trend)
        want = b.describe()
        if trend.get("vote_min") == 4:                 # the vote4 shadow's words only: "4개 모두" for "4개 이상"
            want = [want[0].replace("중 4개 이상 같은 쪽", "중 4개 모두 같은 쪽")] + want[1:]
        assert a.describe() == want, trend
        assert {k: v for k, v in dataclasses.asdict(a).items() if k != "pullback_wait"} == dataclasses.asdict(b)
        assert a.problems() == b.problems() == []


def test_pullback_wait_must_be_true_or_false():
    assert any("pullback_wait" in x for x in TJ.TrendRules.from_dict({"pullback_wait": 1}).problems())
    assert any("pullback_wait" in x for x in TJ.TrendRules.from_dict({"pullback_wait": "no"}).problems())
    assert TJ.TrendRules.from_dict({"pullback_wait": False}).problems() == []


def test_trend_now_enters_at_the_signals_own_minute(tmp_path):
    w = T.World(tmp_path, trend={**_load(LIVE)["trend"], "pullback_wait": False})
    T._start(w)
    B = T.T0 + 30 * MIN
    w.add_minutes(T.T0, 30)
    w.signal("N08_ICHI_WR", "BTCUSDT", 1, B)
    w.step(B)                                       # due at B: in at B, no wait
    p = w.engine().position
    assert p is not None and p.entry_time == B and p.side == 1 and not w.run.pulls
    assert not p.signal.meta.get("pulled") and p.signal.meta["trend"]["dir"] == 1
    assert p.signal.meta["trend"]["judge"].startswith("1시간 상승") and p.signal.score == pytest.approx(1.0)
    (bc, st, d), = w.rows("N08_ICHI_WR@30m")
    d = json.loads(d)
    assert (bc, st) == (B, "SUBMITTED") and d["why"].startswith("추세 판단 통과: 되돌림 안 기다리고 바로 진입 · 1시간 상승")
    assert d["trend"]["judge"]["dir"] == 1 and d["trend"]["score"] == pytest.approx(1.0)
    assert w.run.counts["N08_ICHI_WR@30m"] == {"submitted": 1}
    # the coin-flip twin: the same moment, the side combo._submit_due draws for it
    tw = w.engine(C.FLIP_ACCOUNT).position
    assert tw is not None and tw.entry_time == B and tw.side == C.flip_side(C.FLIP_ACCOUNT, p.signal)
    # the trade record keeps the judgment it entered on (ctx), as the waiting bot's
    assert p.signal.meta["ctx"]["trend"]["judge"].startswith("1시간 상승")
    ts, state = w.store.get_state(T.TB.STATE_TREND)
    assert state["waits"] == [] and "바로 진입" in state["rules"][2]


def test_trend_now_ranks_one_minutes_signals_by_score(tmp_path):
    w = T.World(tmp_path, trend={"pullback_wait": False})
    T._start(w)
    B = T.T0 + 30 * MIN
    w.add_minutes(T.T0, 30)
    w.judge.j[("ETHUSDT", "1h")] = T.J(close=2500.0, ema20=2498.0, atr=12.5, votes={"V39": 1, "S6": 1, "OBV": 1, "N12": 1})
    w.judge.s[("ETHUSDT", "30m")] = T.S(ema20=2500.0, atr=7.5)
    w.signal("N08_ICHI_WR", "BTCUSDT", 1, B)        # 3 of 4: score 1
    w.signal("F3_BOS", "ETHUSDT", 1, B)             # 4 of 4: score 2 -> this one
    w.judge.j[("BTCUSDT", "1h")] = T.J(adx=24.0, adx_prev=21.0)
    w.judge.j[("ETHUSDT", "1h")] = dataclasses.replace(w.judge.j[("ETHUSDT", "1h")], adx=24.0, adx_prev=21.0)
    w.step(B)
    p = w.engine().position
    assert p is not None and p.symbol == "ETHUSDT" and p.entry_time == B and p.signal.score == pytest.approx(2.0)
    assert {r[1] for r in w.rows("N08_ICHI_WR@30m")} == {"SUBMITTED"}           # submitted too, lost the rank


def test_trend_now_still_filters_against_the_trend_and_keeps_the_fast_exit(tmp_path):
    w = T.World(tmp_path, trend={"pullback_wait": False, "time_bars": None})
    T._start(w)
    B = T.T0 + 30 * MIN
    w.add_minutes(T.T0, 30)
    w.signal("N08_ICHI_WR", "BTCUSDT", 1, B)
    w.step(B)
    assert w.engine().position is not None
    B2 = B + 30 * MIN
    T._to(w, B + MIN, B2)
    w.signal("N08_ICHI_WR", "BTCUSDT", -1, B2)      # against the 1h trend: no short, but the same member turned
    w.step(B2)
    assert w.engine().position is None
    t, = w.trades()
    assert t["exit_reason"] == "REV" and t["exit_time"] == B2
    st, d = w.rows("N08_ICHI_WR@30m")[-1][1:]
    assert st == "FILTERED" and json.loads(d)["why"].startswith("1시간 추세가 상승이라 숏 안 함")


# ====================================================================== the 그림자 tab
def _world(root: Path, name: str, trend: dict, db: str = None):
    (root / name).mkdir()
    w = T.World(root / name, **({"trend": trend, "db": db} if db else {"trend": trend}))
    w.store.put_state("combo_run", T.T0, {"config": json.loads(json.dumps(dataclasses.asdict(w.cfg), default=str))})
    return w


@pytest.fixture
def tsw(tmp_path, monkeypatch):
    """The live trend bot (the live config's trend section): one long after its pullback, closed by the supervisor
    (JUDGE) at T0 + 1 h. The shadow trend-time on its own database: the same long, closed by TIME 4 entry bars later.
    trend-now: a database without a record yet. trend-vote4: no database. Old shadows: B from before the trend bot's
    start (trades before and after it) and 규칙봇 15 turned on after it."""
    live = _load(LIVE)["trend"]
    sd = tmp_path / "sh"
    sd.mkdir()
    m = _world(tmp_path, "main", live)
    B, _p = T._enter_long(m)
    m.judge.j[("BTCUSDT", "1h")] = T.J(dir=-1, votes={"V39": -1, "S6": -1, "OBV": -1, "N12": 1})
    T._to(m, B + 3 * MIN, T.T0 + HOUR + MIN)
    # the live account carries over from the bots before it: created 5 h before the trend bot, one old-bot trade at T0 - 1 h
    m.store.conn.execute("UPDATE accounts SET created_ts = ? WHERE account_id = ?", (T.T0 - 5 * HOUR, C.ACCOUNT))
    m.store.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, "
                         "data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (C.ACCOUNT, "SOLUSDT", T.T0 - HOUR, T.T0 - 30 * MIN, "LOCK",
                                                                        30, 77.0, 0.26, 1077.0, json.dumps({"side": 1})))
    m.store.commit()
    s = _world(tmp_path, "time", {**live, "time_bars": 4}, db=str(sd / "shadow-trend-time.db"))
    B, p = T._enter_long(s)
    T._to(s, B + 3 * MIN, p.entry_time + 2 * HOUR + MIN)
    s.store.commit()
    from paperbot.store3 import Store3
    Store3(str(sd / "shadow-trend-now.db")).close()
    LW.shadow_db(str(sd / "shadow-b.db"), [4.0, 6.0, -30.0, 5.0], since=T.T0 - 2 * HOUR - 30 * MIN)   # entries T0-1h30 .. T0+1h30
    LW.shadow_db(str(sd / "shadow-rule15.db"), [7.0], since=T.T0 + 10 * MIN)
    monkeypatch.setenv("PAPERBOT_LIVE_SHADOW_DIR", str(sd))
    return {"p": {"paper": m.cfg.db}, "main": m, "time": s, "dir": sd, "now": T.T0 + 3 * HOUR}


def _units(states: dict):
    return lambda unit: (states.get(unit, ""), "")


def test_the_trend_shadows_next_to_the_live_paper_each_from_its_own_start(tsw):
    d = L.shadows(tsw["p"], tsw["now"], units=_units({}))
    t = d["trend"]
    assert t["on"] and t["since"] == T.T0 and t["review_ms"] == T.T0 + 14 * DAY and t["small_n"] == 20
    tm, nw, v4 = t["shadows"]
    assert [x["id"] for x in t["shadows"]] == ["trend-time", "trend-now", "trend-vote4"]
    # trend-time: its own record by trade and ROE, the live paper over the same span
    assert tm["state"] == "ok" and tm["since_ms"] == T.T0 and tm["from_ms"] == T.T0 and tm["running"] is None
    sh, mn = tm["shadow"], tm["main"]
    roe_s, roe_m = tsw["time"].trades()[0]["roe"], tsw["main"].trades()[0]["roe"]
    assert (sh["trades"], sh["wins"], sh["roe_sum"], sh["roe_mean"]) == (1, 0, pytest.approx(roe_s), pytest.approx(roe_s))
    assert sh["exits"] == [{"reason": "TIME", "reason_ko": "감독 청산(시간 정리)", "n": 1}]
    assert (mn["trades"], mn["roe_sum"]) == (1, pytest.approx(roe_m))
    assert mn["exits"] == [{"reason": "JUDGE", "reason_ko": "감독 청산(추세 뒤집힘)", "n": 1}]
    assert sh["max_dd_roe"] == pytest.approx(min(0.0, roe_s)) and sh["curve"][0] == [T.T0, 0.0]
    assert sh["entries"] == 1 and sh["weekday_days"] == pytest.approx(3 / 24) and sh["per_weekday"] is None   # 3 h of a Monday
    assert tm["small"] and tm["small_ko"] == "표본 적음 · 아직 판단 못 함"
    # its one difference, checked from its own start record
    assert tm["cfg_ok"] is True and tm["cfg_diff"] == [{"key": "trend.time_bars", "main": None, "shadow": 4}]
    assert "첫 잠금(+10%)을 못 가면 청산(시간 정리)" in tm["diff_ko"] and "시간 정리 없음" in tm["live_ko"]
    # never a zero for what is not there: no numbers at all, the state and the command instead
    assert nw["state"] == "empty" and "첫 기록 전" in nw["state_ko"] and "shadow" not in nw and "main" not in nw
    assert v4["state"] == "off" and v4["state_ko"] == "아직 안 켬" and "shadow" not in v4
    assert v4["start_ko"] == "sudo systemctl start paperbot-combo-shadow@trend-vote4"
    assert t["start_all_ko"] == "sudo systemctl start paperbot-combo-shadow@trend-now paperbot-combo-shadow@trend-vote4"
    # the systemd unit's word: starting (the 2-minute wait) and stopped
    t2 = L.shadows(tsw["p"], tsw["now"], units=_units({"paperbot-combo-shadow@trend-now.service": "activating",
                                                       "paperbot-combo-shadow@trend-time.service": "inactive"}))["trend"]
    tm2, nw2, _v = t2["shadows"]
    assert nw2["state"] == "starting" and "켜는 중" in nw2["state_ko"] and nw2["running"] is True
    assert tm2["state"] == "ok" and tm2["running"] is False and tm2["state_ko"].startswith("꺼져 있음")
    assert "paperbot-combo-shadow@trend-time" in t2["start_all_ko"] and "trend-now" not in t2["start_all_ko"]


def test_a_later_shadow_counts_the_live_paper_from_its_own_start_only(tsw):
    s = tsw["time"]
    s.store.put_state(C.STATE_KEY, T.T0, {**(s.store.get_state(C.STATE_KEY) or (0, {}))[1], "trend_since": T.T0 + 40 * MIN})
    s.store.commit()                                 # as if this shadow was turned on at T0 + 40 min (after the live entry)
    tm = L.shadows(tsw["p"], tsw["now"], units=_units({}))["trend"]["shadows"][0]
    assert tm["from_ms"] == T.T0 + 40 * MIN and tm["main"]["trades"] == 0 and tm["main"]["roe_sum"] is None
    assert tm["main"]["max_dd_roe"] is None and tm["main"]["win_rate"] is None          # nothing closed: no number


def test_a_shadow_left_behind_by_a_changed_live_config_says_so(tsw):
    m = tsw["main"]
    cfg = json.loads(json.dumps(dataclasses.asdict(m.cfg), default=str))
    cfg["trend"] = {**cfg["trend"], "adx_min": 25}
    m.store.put_state("combo_run", T.T0 + HOUR, {"config": cfg})
    m.store.commit()
    tm = L.shadows(tsw["p"], tsw["now"], units=_units({}))["trend"]["shadows"][0]
    assert tm["cfg_ok"] is False and [x["key"] for x in tm["cfg_diff"]] == ["trend.adx_min", "trend.time_bars"]


def test_the_old_shadows_compare_only_over_the_old_bots_days(tsw):
    d = L.shadows(tsw["p"], tsw["now"], units=_units({}))
    assert d["old_until_ms"] == T.T0 and [x["id"] for x in d["shadows"]] == ["b", "nocut", "ac32", "chase", "trend4h", "rule15"]
    b = d["shadows"][0]
    # B's entries: T0-1h30, T0-30m (before the trend bot), T0+30m, T0+1h30 (after it: not compared)
    assert b["state"] == "ok" and b["until_ms"] == T.T0 and b["stats"]["trades"] == 2 and b["stats"]["pnl"] == pytest.approx(10.0)
    assert b["later"] == 2 and b["main"]["stats"]["trades"] == 1 and b["main"]["stats"]["pnl"] == pytest.approx(77.0)   # the old bot's
    r15 = d["shadows"][-1]
    assert r15["no_overlap"] is True and r15["main"] is None and r15["stats"]["trades"] == 1 and r15["until_ms"] is None


def test_another_live_bot_keeps_the_old_comparison(tmp_path, monkeypatch):
    p = LW.build_world(str(tmp_path / "w"))
    monkeypatch.setenv("PAPERBOT_LIVE_SHADOW_DIR", str(tmp_path / "nowhere"))
    d = L.shadows(p, LW.NOW, units=_units({}))
    t = d["trend"]
    assert t["on"] is False and t["main_ko"] == LS.NOT_TREND_KO and d["old_until_ms"] is None
    assert [x["state"] for x in t["shadows"]] == ["off"] * 3


def test_record_by_trade_and_roe_and_the_weekdays():
    fri_noon = LW.T0 + 4 * DAY + 3 * HOUR                     # LW.T0 is Monday 2026-10-19 09:00 KST
    mon_noon = fri_noon + 3 * DAY
    assert LS.weekday_days(fri_noon, mon_noon) == pytest.approx(0.5 + 0.5)           # Friday afternoon + Monday morning
    assert LS.weekday_days(fri_noon + 12 * HOUR, fri_noon + 2 * DAY) == 0.0          # Saturday and Sunday (KST)
    trades = [{"entry_time": LW.T0 + i * HOUR, "exit_time": LW.T0 + i * HOUR + 30 * MIN, "pnl": p, "roe": r, "exit_reason": x}
              for i, (p, r, x) in enumerate([(8, 0.2, "LOCK"), (-20, -0.5, "SL"), (4, 0.1, "LOCK"), (-12, -0.3, "TIME")], 1)]
    r = LS.record(trades, LW.T0, LW.T0 + DAY, {"entry_time": LW.T0 + 6 * HOUR})
    assert (r["trades"], r["wins"], r["win_rate"]) == (4, 2, 0.5)
    assert r["roe_sum"] == pytest.approx(-0.5) and r["roe_mean"] == pytest.approx(-0.125)
    assert r["max_dd_roe"] == pytest.approx(-0.7)                                    # +0.2 down to -0.5
    assert r["entries"] == 5 and r["open"] and r["per_weekday"] == pytest.approx(5.0)
    assert [(e["reason"], e["n"]) for e in r["exits"]] == [("LOCK", 2), ("SL", 1), ("TIME", 1)]
    assert LS.record(trades, LW.T0 + 3 * HOUR, LW.T0 + DAY)["trades"] == 2           # entered from the start on only
    e = LS.record([], LW.T0, LW.T0 + DAY)
    assert e["trades"] == 0 and e["roe_sum"] is None and e["max_dd_roe"] is None and e["curve"] == [] and e["per_weekday"] == 0.0


def test_the_route_answers_with_both_parts(tsw, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from test_dash import SECRET, _store
    monkeypatch.setenv("PAPERBOT_LIVE_PAPER_DB", tsw["main"].cfg.db)
    dbp = str(tmp_path / "paper3-dash.db")
    _store(dbp).close()
    c = TestClient(create_app(dbp, hash_password("pw for the test"), SECRET, candles=lambda s, i, n: []))
    c.post("/api/login", json={"password": "pw for the test"})
    d = c.get("/api/v4/livebots/shadows").json()
    assert [x["id"] for x in d["trend"]["shadows"]] == ["trend-time", "trend-now", "trend-vote4"] and len(d["shadows"]) == 6


# ====================================================================== the view in node
def test_the_view_draws_the_trend_shadows_and_folds_the_old_ones(tsw, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    ans = L.shadows(tsw["p"], tsw["now"], units=_units({"paperbot-combo-shadow@trend-now.service": "activating"}))
    f = tmp_path / "d.json"
    f.write_text(json.dumps(json_finite(ans), allow_nan=False, default=str), encoding="utf-8")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              f"const V = await import('file://{SCREENS}/livebots-more.js');\n"
              f"const SH = await import('file://{SCREENS}/livebots-shadow.js');\n"
              f"const d = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));\n"
              "const st = {every: []}; const ctx = {params: {query: {}}, alive: () => true, every(ms) { st.every.push(ms); },"
              " api: async () => JSON.parse(JSON.stringify(d))};\n"
              "const v = V.shadowsView(ctx); await new Promise((r) => setTimeout(r, 5)); await new Promise((r) => setTimeout(r, 5));\n"
              "const tm = d.trend.shadows[0];\n"
              "console.log(JSON.stringify({t: D.walk(v.el).text.replace(/\\s+/g, ' '), rows: SH.cmpRows(tm.shadow, tm.main),"
              " none: SH.cmpRows(null, null).map((r) => r.sh), cfg: SH.cfgWords(tm).ko, bad: SH.cfgWords({...tm, cfg_ok: false, cfg_diff: []}).ko,"
              " same: V.twoLines === SH.twoLines}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    t = out["t"]
    assert not BAD.search(t), BAD.search(t)
    for w in ("추세판단 봇 그림자 비교", "그림자 · 시간 정리 있음", "다른 점 하나", "실거래 봇은 시간 정리 없음", "같은 기간", "닫힌 거래", "이긴 비율",
              "거래당 평균 순ROE", "순ROE 합", "평일 하루 진입", "누적 순ROE 최대 낙폭", "청산 이유", "감독 청산(시간 정리) 1",
              "감독 청산(추세 뒤집힘) 1", "표본 적음 · 아직 판단 못 함", "실거래 페이퍼도 같은 기간", "설정 확인 ✓",
              "그림자 · 되돌림 없이 바로 진입", "켜는 중", "그림자 · 판단 4개 모두 같은 쪽",
              "아직 안 켬 · 켜는 법: sudo systemctl start paperbot-combo-shadow@trend-vote4",
              "예전 봇 비교용 · 그림자 6개", "지금 추세판단 봇과는 견주지 않아요", "그림자 B 안정형", "견줄 기간 없음", "그 뒤 거래 2번은 지금 봇과 견주지 않아요"):
        assert w in t, w
    assert "USDT" not in t.split("예전 봇 비교용")[0]                                  # the trend shadows: never dollars
    rows = {r["k"]: r for r in out["rows"]}
    assert rows["닫힌 거래"]["sh"] == "1번" and rows["이긴 비율"]["sh"] == "0% (0/1)" and rows["청산 이유"]["mn"] == "감독 청산(추세 뒤집힘) 1"
    assert rows["평일 하루 진입"]["sh"].startswith("평일 0.1일 · 1번")
    assert out["none"] == ["—"] * 7 and out["cfg"].startswith("설정 확인 ✓") and "설정이 같아요" in out["bad"] and out["same"]
