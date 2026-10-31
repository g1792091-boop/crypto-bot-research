"""The 실거래 site after the 레인지 봇's move (owners 10-31 night, docs/range-bot-ko.md 0장): the first WOO X Pro account (the
executor slot "mexc", whose executor followed the old 레인지 봇 paper bot) traded by the 레인지 봇 itself, a third mix bot
(paperbot/mixchop.py: 15m bars, the trend bar's 종합, rule "h0x" 히스토그램 0선 돌파), as the 바이비트 봇 took the Bybit slot
on 10-29 (tests/test_dash_mixbybit_site.py).

- livebots: once the 레인지 봇's server config is there (PAPERBOT_MIXRANGE_CONFIG, /etc/paperbot/mixrange.json) the "mexc"
  slot leaves every answer (installed, the summary's execs and accounts, costs, trades) and ``replaced`` names the bot; the
  old range paper (range.db) is no longer one of the page's paper bots (range_moved), its own screen says it is the past
  record; both slots taken: no executor at all, nothing breaks; before the file, every answer as it was;
- livemix: /mixrange and /mixrangeperf (profile "range"), the bot's words from its config (name, 15분), its 15-minute
  staleness, the trend bar's and rule h0x's values on its signal rows;
- livepos: the 레인지 봇's card (its name, its app, its bar); livegoalres: goalres?bot=range is the mix bot's part (no 전후,
  no 하한) with its own links; liveftrend: the boards of the three mix bots with the trend bar's rows and the histogram,
  the old range paper's 1-hour and ROC reads gone after the move;
- the pages (node): the trend bar's and h0x's words (livebots-mix.js trendKo / valsKo, livebots-ftrend.js), the 레인지 봇
  tab (rangeBotView: the old screen before the move, the mix screens after), 한눈에's 레인지 봇 card and no executor card
  once every slot is taken, the friend bot's name 친구 15분 봇."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from paperbot import mixchop as M
from paperbot.dash.app import json_finite
from paperbot.dash.more import livebots as L
from paperbot.dash.more import liveftrend as FTR
from paperbot.dash.more import livemix as X
from tests import livebots_world as LW
from tests.test_mixbybit_checks import DAY0, H, MIN, _write

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
NOW = DAY0 + 23 * H + 40 * MIN
BAD = __import__("re").compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")
# a coin's trend bar on a 15m close (paperbot/friendtrend.py part 9 as mixchop writes it): 종합 하락
BAR = {"score": 0, "six": -1, "line": -1, "ema": -1, "st": 1, "four": -1}


def _cfg_range():
    return M.load_config(os.path.join(ROOT, "deploy", "mixrange.live.json"))


def _write_range(folder, live_rows, paper_rows, live_state=None, paper_state=None):
    """The 레인지 봇's two deploy configs with this world's files (its coins, leverage and rule as the repo has them)."""
    os.makedirs(folder, exist_ok=True)
    j = lambda n: os.path.join(folder, n)      # noqa: E731
    for mode, src in (("live", "mixrange.live.json"), ("paper", "mixrange.paper.json")):
        d = json.load(open(os.path.join(ROOT, "deploy", src), encoding="utf-8"))
        d.update(state=j(f"{mode}-state.json"), log=j(f"{mode}-log.jsonl"), own_stop_file=j(f"{mode}.STOP"), kill_file=j("STOP"))
        json.dump(d, open(j(f"{mode}.json"), "w", encoding="utf-8"))
    for mode, rows, st in (("live", live_rows, live_state), ("paper", paper_rows, paper_state)):
        with open(j(f"{mode}-log.jsonl"), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        json.dump(st or {"position": None, "start_equity": 100.0, "last_close_ms": NOW - 10 * MIN, "saved_ms": NOW - 9 * MIN,
                         "mode": "mainnet" if mode == "live" else "paper"}, open(j(f"{mode}-state.json"), "w", encoding="utf-8"))
    return {"PAPERBOT_MIXRANGE_CONFIG": j("live.json"), "PAPERBOT_MIXRANGE_PAPER_CONFIG": j("paper.json")}


def _ev(sym, ce, x0, side=0, why="", trend=-1, **kv):
    """A rule h0x signal of the trend bar (mixchop.evaluate_friend's fields in trend "bar" mode: no votes, no chop zone;
    owners 10-31, last: the 15m signal with the trend read on the 30m bar, ``trend_tf``)."""
    return {"symbol": sym, "close_ms": ce, "side": side, "why": why, "rule": "h0x", "close": 84.59, "trend": trend,
            "trend_mode": "bar", "tf": "15분", "trend_tf": "30분", "bar": dict(BAR), "bar_n": [1, 4, 1], "bar_score": -1, "ema_rsi": 23.61,
            "stop_pct": 1.03, "liq_ok": True, "x0": x0, "h6": -4.08, "stop_dist": 0.87, **kv}


def _trade(sym, side, t_in, t_out, entry, dist, eq0, eq1, qty=1.0, lev=40):
    ev = _ev(sym, t_in - 5_000, side, side, trend=side, close=entry, stop_dist=dist)
    sig = {"ts": t_in - 4_000, "kind": "signal", **ev}
    en = {"ts": t_in, "kind": "entry", "symbol": sym, "side": side, "qty": qty, "entry": entry, "stop_dist": dist,
          "stop": entry - side * dist, "best": entry, "step": 0, "opened_ms": t_in, "signal_close_ms": t_in - 5_000,
          "signal_close": entry, "last_bar_ms": t_in - 5_000, "stop_id": "s1", "equity_before": eq0, "leverage": lev,
          "roe_act": 100.0, "why": ev}
    ex = {"ts": t_out, "kind": "exit", "symbol": sym, "side": side, "why": "stop", "price": None, "pnl": eq1 - eq0,
          "equity": eq1, "step": 0, "entry": entry, "stop": entry - side * dist, "opened_ms": t_in}
    return [sig, en, ex]


START = {"ts": DAY0 - H, "kind": "start", "equity": 100.0, "start_equity": 100.0, "setup": [[True, "포지션 모드: 단방향"]], "position": None}


def _range_files(folder, **kv):
    live = [START] + _trade("SOLUSDT", -1, DAY0 + 2 * H, DAY0 + 3 * H, 150.0, 2.4, 100.0, 96.5, qty=10.66)
    live.append({"ts": NOW - 20 * MIN + 4_000, "kind": "signal", **_ev("ETHUSDT", NOW - 20 * MIN, -1, 0,
                                                                       "추세 바 종합 횡보(진입 금지) (상승 2 · 하락 2 · 횡보 2)", trend=0)})
    paper = [START] + _trade("SOLUSDT", -1, DAY0 + 2 * H, DAY0 + 3 * H, 150.0, 2.4, 100.0, 97.0, qty=10.66)
    return _write_range(folder, live, paper, **kv)


@pytest.fixture
def site(tmp_path):
    p0 = LW.build_world(str(tmp_path / "w"))
    env = LW.env_of(p0)
    env["PAPERBOT_MIXRANGE_CONFIG"] = str(tmp_path / "mixrange.json")
    env["PAPERBOT_MIXBYBIT_CONFIG"] = str(tmp_path / "mixbybit.json")
    return {"env": env, "cfg": tmp_path / "mixrange.json", "bybit": tmp_path / "mixbybit.json", "tmp": tmp_path}


# ---------------------------------------------------------------- the WOO X Pro slot
def test_the_woo_x_pro_slot_leaves_once_the_range_bot_is_there(site):
    p = L.paths(site["env"])
    assert [x[0] for x in L.installed(p)] == ["bybit", "mexc"] and L.replaced(p) == [] and not L.range_moved(p)
    d = L.build(p, LW.NOW)
    assert [x["id"] for x in d["execs"]] == ["bybit", "mexc"] and d["replaced"] == [] and "mixrange_config" not in d["paths"]
    site["cfg"].write_text(json.dumps({"exchange": "wooxpro"}), encoding="utf-8")
    p = L.paths(site["env"])
    assert [x[0] for x in L.installed(p)] == ["bybit"] and L.replaced(p) == ["mexc"] and L.range_moved(p)
    d = L.build(p, LW.NOW)
    assert [x["id"] for x in d["execs"]] == ["bybit"] and "mexc" not in [a["id"] for a in d["accts"]]
    assert d["replaced"] == [{"id": "mexc", "bot": "range", "name_ko": "레인지 봇", "account_ko": "WOO X Pro", "unit": "paperbot-mixrange",
                              "api": "/api/v4/livebots/mixrange", "tab": "rangebot"}]
    assert d["paths"]["mixrange_config"] == str(site["cfg"])
    assert "mexc" not in L.costs(p, LW.NOW) and "mexc" not in (L.trade_rows(p, LW.NOW).get("accts") or {})
    # the same table as the live checks'
    from paperbot import livecheck as LC
    assert L.ENV_MIX["mixrange_config"][1] == LC.REPLACED_BY["mexc"][0] and L.REPLACED["mexc"]["unit"] == LC.REPLACED_BY["mexc"][1]
    assert L.REPLACED["mexc"]["name_ko"] == LC.REPLACED_BY["mexc"][2]
    # both slots taken (the 바이비트 봇 too): no executor at all, every answer still made
    site["bybit"].write_text("{}", encoding="utf-8")
    p = L.paths(site["env"])
    assert L.installed(p) == () and L.replaced(p) == ["bybit", "mexc"]
    d = json_finite(L.build(p, LW.NOW))
    assert d["execs"] == [] and [r["id"] for r in d["replaced"]] == ["bybit", "mexc"]
    assert [a["id"] for a in d["accts"] if a.get("kind") == "live"] == []
    assert L.costs(p, LW.NOW) is not None and L.trade_rows(p, LW.NOW) is not None
    from paperbot.dash.more import livepos as LP
    ids = [c["id"] for c in LP.build(p, L.paths_more({}), LW.NOW)["cards"]]
    assert "mexc" not in ids and "bybit" not in ids


def test_the_old_range_paper_leaves_the_page(tmp_path, monkeypatch):
    """The old 레인지 봇 paper bot (range.db, tests/range_world.py: WOO X Pro followed it): before the move a page account with
    its follower; after it no page account (no executor follows it), its own screen still answers, said to be the past record."""
    from paperbot.dash.more import livegoalres as GR
    from paperbot.dash.more import liverange as RG
    from tests import range_world as RW
    folder = str(tmp_path / "rw")
    p = RW.build(folder)
    more = RW.more(folder)
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    L._cache.clear()
    p = {**p, "mixrange_config": str(tmp_path / "mixrange.json"), "mixbybit_config": str(tmp_path / "none.json")}
    _c, _f, paper, execs = L.sources(p, RW.NOW)
    bots = L.paper_bots(p, paper, execs)
    assert "range" in [b["id"] for b in bots] and next(b for b in bots if b["id"] == "range")["follower_ids"] == ["mexc"]
    r0 = RG.build(p, more, RW.NOW)
    assert r0["moved"] is None and r0["bot"]["followers"]
    g0 = GR.build("range", p, RW.NOW, more)
    assert [x["href"] for x in g0["links"]][0] == "#/trades"                     # the old range paper's part, as before
    (tmp_path / "mixrange.json").write_text("{}", encoding="utf-8")
    L._cache.clear()
    _c, _f, paper, execs = L.sources(p, RW.NOW)
    bots = L.paper_bots(p, paper, execs)
    assert "range" not in [b["id"] for b in bots] and "mexc" not in [x["id"] for x in execs]
    d = L.build(p, RW.NOW)
    assert "range" not in [a["id"] for a in d["accts"]] and "range" not in [b["id"] for b in d["papers"] or []]
    r1 = RG.build(p, more, RW.NOW)
    assert r1["bot"] is None and r1["status"]["state"] not in ("off", "missing")             # its record still read
    assert r1["moved"]["tab"] == "rangebot" and "스스로 거래" in r1["moved"]["ko"] and "지난 기록" in r1["moved"]["ko"]
    monkeypatch.setattr(X, "paths", lambda env=None, bot=None, _p=X.paths: _p({"PAPERBOT_MIXRANGE_CONFIG": str(tmp_path / "no-live.json"),
                                                                               "PAPERBOT_MIXRANGE_PAPER_CONFIG": str(tmp_path / "no-paper.json"),
                                                                               "PAPERBOT_MIXRANGE_STATE": str(tmp_path / "no-s.json"),
                                                                               "PAPERBOT_MIXRANGE_LOG": str(tmp_path / "no-l.jsonl"),
                                                                               "PAPERBOT_MIXRANGE_PAPER_STATE": str(tmp_path / "no-ps.json"),
                                                                               "PAPERBOT_MIXRANGE_PAPER_LOG": str(tmp_path / "no-pl.jsonl")}, bot=bot))
    g1 = GR.build("range", p, RW.NOW, more)
    assert g1["state"] == "off" and "레인지 봇(실거래)" in g1["ko"]                  # the mix bot's part (not yet started)
    assert [x["href"] for x in g1["links"]] == ["#/rangebot", "#/ftrend"]


# ---------------------------------------------------------------- the 레인지 봇's own answers (livemix profile "range")
def test_the_range_bots_answers(tmp_path):
    mp = X.paths(_range_files(str(tmp_path / "r")), bot="range")
    c = X.control(mp, NOW)
    cfg = _cfg_range()
    assert (c["bot"], c["name_ko"], c["tf_ko"], c["trend_tf_ko"], c["rules"], c["rules_ko"], c["trend_mode"]) == \
        ("range", "레인지 봇", cfg.tf_ko, cfg.trend_tf_ko, ["h0x"], ["히스토그램 0선 돌파"], "bar")
    assert (cfg.tf_ko, cfg.trend_tf_ko) == ("15분", "30분")                 # owners 10-31, last: 15m signals, the 30m trend
    assert (c["account_ko"], c["exchange_ko"], c["stale_ms"]) == ("WOO X Pro", "WOO X Pro", 20 * MIN)
    live = c["bots"][0]
    assert (live["unit"], live["status"]["state"], live["status"]["tf_ko"], live["status"]["trend_tf_ko"], live["status"]["stale_ms"]) == \
        ("paperbot-mixrange", "running", "15분", "30분", 20 * MIN)
    assert live["equity"]["floor_frac"] == 0 or not live["equity"].get("floor_frac")      # no floor line
    assert [x["coin"] for x in live["coins"]] == [x.symbol.replace("USDT", "") for x in _cfg_range().coins]
    rows = live["feed"]["rows"]
    eth = next(r for r in rows if r["cat"] == "signal" and r["coin"] == "ETH")
    assert (eth["rule"], eth["rule_ko"], eth["colour_ko"], eth["want"], eth["stage"]) == ("h0x", "히스토그램 0선 돌파", "히스토그램 0선 아래로 돌파", -1, "refused")
    v = eth["vals"]
    assert (v["trend_mode"], v["bar"], v["bar_n"], v["bar_score"], v["x0"], v["h6"], v["tf"], v["trend_tf"]) == \
        ("bar", BAR, [1, 4, 1], -1, -1, -4.08, "15분", "30분")
    assert "votes" not in v and "chop_zone" not in v
    sol = next(r for r in rows if r["cat"] == "signal" and r["coin"] == "SOL")
    assert sol["stage"] == "entered" and sol["colour_ko"] == "히스토그램 0선 아래로 돌파"
    # a 15-minute bot reads 멈춤 after 20 minutes (the 30-minute ones after 35)
    late = X.control(mp, NOW + 12 * MIN)["bots"][0]["status"]
    assert late["state"] == "stopped" and late["ko"] == "20분 넘게 새 기록이 없어요 (봇은 15분봉이 끝날 때마다 기록해요)"
    pf = X.perf(mp, NOW)
    assert pf["name_ko"] == "레인지 봇" and pf["backtest"] is None and pf["bots"][0]["record"]["n"] == 1
    assert pf["bots"][0]["rules"]["coins"] and pf["bots"][0]["rules"]["equity_floor_frac"] == 0
    # the three bots' answers: their configs' names and bars (owners 10-31, last: all on 15m signals with the 30m trend)
    for bot, src in (("mix", "mixchop.live.json"), ("bybit", "mixbybit.live.json"), ("range", "mixrange.live.json")):
        rc = M.load_config(os.path.join(ROOT, "deploy", src))
        w = X.live_words(X.paths({}, bot=bot), X.PROFILES[bot])
        assert (w["name_ko"], w["tf_ko"], w["trend_tf_ko"]) == (rc.name, rc.tf_ko, rc.trend_tf_ko), bot


def test_the_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from paperbot.livedash import app as LA
    for k, v in _range_files(str(tmp_path / "r")).items():
        monkeypatch.setenv(k, v)
    app = LA.create_app(None, b"s" * 32, candles=lambda *a, **k: [], ticker=lambda: {}, market=lambda: {}, frames=lambda *a: None,
                        liq_db=str(tmp_path / "no-liq.db"), inbox_db=str(tmp_path / "no-inbox.db"))
    assert {"/api/v4/livebots/mixrange", "/api/v4/livebots/mixrangeperf"} <= set(app.state.more["livemix"]["routes"])
    c = TestClient(app)
    r = c.get("/api/v4/livebots/mixrange")
    assert r.status_code == 200 and r.json()["bot"] == "range" and r.json()["bots"][0]["unit"] == "paperbot-mixrange"
    r = c.get("/api/v4/livebots/mixrangeperf")
    assert r.status_code == 200 and r.json()["name_ko"] == "레인지 봇" and r.json()["backtest"] is None


def test_the_positions_tab_has_the_range_bots_card(site, tmp_path):
    from paperbot.dash.more import livepos as LP
    site["cfg"].write_text("{}", encoding="utf-8")
    pos = {"symbol": "SOLUSDT", "side": -1, "qty": 2.0, "entry": 150.0, "stop_dist": 2.4, "stop": 152.4, "best": 149.0, "step": 0,
           "opened_ms": NOW - H, "signal_close_ms": NOW - H - 5_000, "signal_close": 150.0, "last_bar_ms": NOW - MIN, "stop_id": "s1",
           "equity_before": 100.0, "leverage": 40, "roe_act": 100.0}
    env_r = _range_files(str(tmp_path / "r"), live_state={"position": pos, "start_equity": 100.0, "last_close_ms": NOW - 10 * MIN,
                                                          "saved_ms": NOW - MIN, "mode": "mainnet"})
    p = L.paths(site["env"])
    d = LP.build(p, {**L.paths_more({}), "mixrange_paths": X.paths(env_r, bot="range")}, NOW)
    c = next(c for c in d["cards"] if c["id"] == "mixrange")
    assert (c["state"], c["self"], c["name_ko"], c["short_ko"], c["app_ko"], c["tag"], c["tf_ko"]) == \
        ("ok", True, "WOO X Pro · 레인지 봇", "레인지 봇", "WOO X Pro", "mexc", "15분")
    q = c["position"]
    assert (q["symbol"], q["side"], q["leverage"], q["entry"], q["timeframe"]) == ("SOLUSDT", -1, 40, 150.0, "15m")
    assert q["round_trip"] == pytest.approx(2 * _cfg_range().taker_fee)
    assert q["rule_ko"] == "레인지 봇 · 15분봉 신호 · 스스로 매매 (페이퍼를 따라가지 않음)" and "레인지 봇은" in q["fast"]["ko"]
    assert q["ladder"][0]["at"] == pytest.approx(0.10) and q["ladder"][0]["lock"] == pytest.approx(0.08)
    assert "WOO X Pro 앱" in q["liq_ko"]
    ids = [c["id"] for c in d["cards"]]
    assert "mexc" not in ids and ids.index("mixrange") > ids.index("bybit")
    # before the move: no 레인지 봇 card, the executor's as before
    site["cfg"].unlink()
    d = LP.build(L.paths(site["env"]), {**L.paths_more({}), "mixrange_paths": X.paths(env_r, bot="range")}, NOW)
    ids = [c["id"] for c in d["cards"]]
    assert "mixrange" not in ids and "mexc" in ids


def test_the_goal_part_of_the_range_bot(site, tmp_path, monkeypatch):
    from paperbot.dash.more import livegoalres as GR
    env_r = _range_files(str(tmp_path / "r"))
    monkeypatch.setattr(X, "paths", lambda env=None, bot=None, _p=X.paths: _p(env_r, bot=bot))
    site["cfg"].write_text("{}", encoding="utf-8")
    d = GR.build("range", L.paths(site["env"]), NOW)
    assert d["bot"] == "range" and d["name_ko"] == "레인지 봇" and d["state"] == "ok"
    assert [a["name_ko"] for a in d["accounts"]] == ["WOO X Pro (실거래)", "모의"]
    ids = [i["id"] for i in d["items"]]
    assert "before_after" not in ids and "floor" not in ids and "steps" in ids and "twin" in ids
    assert [x["href"] for x in d["links"]] == ["#/rangebot", "#/ftrend"]
    # the friend bot's part: its config's name
    assert GR.build("mix", L.paths(site["env"]), NOW)["name_ko"] == X.live_name(X.paths(bot="mix"), X.MIX)


# ---------------------------------------------------------------- the board of the three bots
def _row(e):
    r = M.board_row([e], e["close_ms"])
    if e.get("trend_tf"):
        r.setdefault("trend_tf", e["trend_tf"])        # (the board's trend bar, owners 10-31, last)
    return r


def _board_state(evs):
    return {"position": None, "start_equity": 100.0, "last_close_ms": NOW - 10 * MIN, "saved_ms": NOW - 9 * MIN, "mode": "mainnet",
            "board": {e["symbol"]: _row(e) for e in evs}}


def test_the_board_shows_the_three_bots(site, tmp_path):
    ce = NOW - 10 * MIN
    # the 바이비트 봇 (its test world's 30m bars, tests/test_mixbybit_checks.py: rule obvac on the trend bar, no tf key, no histogram)
    obvac = {k: v for k, v in _ev("SOLUSDT", ce, 0, 0, "OBV 연한색→진한색 없음", trend=1).items() if k not in ("x0", "h6", "tf", "trend_tf")}
    obvac.update(rule="obvac", turn=0, obv_cs=1, obv_dark=False, ac=0.42, ac_col=1)
    mp = X.paths(_write(str(tmp_path / "b"), [], [], live_state=_board_state([obvac]), rules=("obvac",)), bot="bybit")
    nofriend = {k: str(tmp_path / f"nf-{k}") for k in ("PAPERBOT_MIX_CONFIG", "PAPERBOT_MIX_PAPER_CONFIG", "PAPERBOT_MIX_STATE",
                                                       "PAPERBOT_MIX_LOG", "PAPERBOT_MIX_PAPER_STATE", "PAPERBOT_MIX_PAPER_LOG")}
    mpr = X.paths(_write_range(str(tmp_path / "r"), [], [], live_state=_board_state([_ev("SOLUSDT", ce, -1, -1, trend=-1),
                                                                                         _ev("ETHUSDT", ce, 0, 0, "히스토그램 0선 돌파 없음", trend=0)])),
                  bot="range")
    p = L.paths(site["env"])
    d = FTR.build(p, NOW, mp, X.paths(nofriend, bot="mix"), mpr)
    assert (d["m30"]["state"], d["m30"]["name_ko"], d["m30"]["tf_ko"]) == ("ok", "바이비트 봇", "30분")
    assert (d["r15"]["state"], d["r15"]["name_ko"], d["r15"]["tf_ko"], d["r15"]["trend_tf_ko"], d["r15"]["stale"]) == \
        ("ok", "레인지 봇", "15분", "30분", False)
    assert d["f30"]["state"] == "off" and "15분봉이 한 번 끝나면" in d["f30"]["ko"] and d["f30"]["trend_tf_ko"] == "30분"   # off, its own bars
    assert d["moved"] is False and d["h1"] is not None                                     # before the move: the old reads stay
    rows = {r["symbol"]: r for r in d["coins"]}
    b = rows["SOLUSDT"]["m30"]
    assert (b["trend"], b["trend_ko"], b["bar"]["colour_ko"], b["votes"]) == (1, "상승", "초록", [])
    assert [(x["ko"], x["side_ko"]) for x in b["bar"]["rows"]] == [("3개 점수", "횡보 (-1)"), ("6종 평균", "하락"), ("하늘·보라 선", "보라"),
                                                                    ("EMA RSI", "빨강"), ("슈퍼트렌드", "상승"), ("4종 평균", "하락")]
    assert b["bar"]["n"] == [1, 4, 1] and b["bar"]["words"].startswith("종합 상승 (상승 1 · 하락 4 · 횡보 1: 3개 점수 -1")
    assert (b["ac"], b["rules"]["obvac"]["ko"]) == (0.42, "OBV 진한색 + AC")
    r = rows["SOLUSDT"]["rg"]
    assert rows["SOLUSDT"]["inrg"] and (r["trend"], r["bar"]["ko"], r["bar"]["colour_ko"], r["tf"], r["trend_tf"]) == (-1, "하락", "빨강", "15분", "30분")
    assert r["h0x"] == {"x0": -1, "h6": -4.08, "ko": "0선 아래로 돌파"} and r["rules"]["h0x"] == {"side": -1, "why": "", "ko": "히스토그램 0선 돌파"}
    e = rows["ETHUSDT"]["rg"]
    assert (e["bar"]["ko"], e["bar"]["colour_ko"], e["bar"]["no_entry"], e["h0x"]["ko"]) == ("횡보", "노랑", True, "0선 돌파 없음")
    assert any(x.startswith("추세 바 종합(10-31 밤부터 세 봇 모두") for x in d["rules_ko"])
    assert any(x.startswith("히스토그램 0선 돌파(친구 15분 봇 · 레인지 봇") for x in d["rules_ko"])
    # after the move: the old range paper's 1-hour and ROC reads leave the board
    site["cfg"].write_text("{}", encoding="utf-8")
    d = FTR.build(L.paths(site["env"]), NOW, mp, X.paths(nofriend, bot="mix"), mpr)
    assert d["moved"] is True and d["h1"] is None and d["roc"] is None and all(c["roc"] is None for c in d["coins"])
    # an old board says so after its own bar + 5 minutes (15분: 20 minutes)
    assert FTR.build(L.paths(site["env"]), NOW + 12 * MIN, mp, X.paths(nofriend, bot="mix"), mpr)["r15"]["stale"] is True


# ---------------------------------------------------------------- the pages (node)
def _node(tmp_path, body: str, **data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              "globalThis.document.documentElement.dataset.site = 'live';\n"
              f"Date.now = () => {NOW};\n" + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_words(tmp_path):
    out = _node(tmp_path, f"""
    const R = await import('file://{V4}/core/routes.js');
    const MX = await import('file://{SCREENS}/livebots-mix.js');
    const F = await import('file://{SCREENS}/livebots-ftrend.js');
    const LB = await import('file://{SCREENS}/livebots.js');
    const LR = await import('file://{SCREENS}/livebots-range.js');
    const HQ = await import('file://{SCREENS}/livebots-hq.js');
    const K = await import('file://{SCREENS}/livebots-kit.js');
    const PB = await import('file://{V4}/core/pb.js');
    const both = {{replaced: [{{id: 'bybit', name_ko: '바이비트 봇', account_ko: '바이비트'}}, {{id: 'mexc', name_ko: '레인지 봇', account_ko: 'WOO X Pro'}}],
      execs: [], accts: []}};
    K.setExecs(both.execs);
    const real = texts(PB.h('div', null, K.realLine(both))), ids = [K.execIds(both), K.execsNow()];
    K.setExecs(undefined);
    const ids0 = K.execsNow();
    const bar = {{trend: -1, trend_mode: 'bar', bar: {json.dumps(BAR)}, bar_n: [1, 4, 1], bar_score: -1, x0: -1, h6: -4.08, close: 84.59,
      stop_pct: 1.03}};
    const moved = {{replaced: [{{id: 'mexc', bot: 'range', tab: 'rangebot', name_ko: '레인지 봇', account_ko: 'WOO X Pro'}}], execs: [], accts: []}};
    const before = {{replaced: [], execs: [{{id: 'mexc', bot: 'range'}}], accts: []}};
    const bt = LB.BOT_TAB.rangebot;
    console.log(JSON.stringify({{
      trend: [MX.trendKo(bar), MX.trendKo({{...bar, trend: 0, bar_n: [2, 2, 2], bar_score: 0}}), MX.trendKo({{...bar, trend: 1, bar_score: 3}}),
        MX.trendKo({{...bar, tf: '15분', trend_tf: '30분'}}), MX.trendKo({{...bar, tf: '15분'}})],
      waitOf: [MX.waitOf(MX.BYBIT_UI, {{status: {{tf_ko: '30분', trend_tf_ko: '30분'}}}}), MX.waitOf(MX.RANGE_UI, null), MX.waitOf(MX.MIX_UI, {{status: {{tf_ko: '15분', trend_tf_ko: '30분'}}}})],
      plan: [MX.BYBIT_UI.plan, MX.BYBIT_UI.planOf('30분'), MX.MIX_UI.planOf || null],
      labels: [F.whoLabel({{name: '바이비트 봇', tf: '15분', ttf: '30분'}}, null), F.whoLabel({{name: '친구 30분 봇', tf: '30분', ttf: null}}, null),
        F.whoLabel({{name: '레인지 봇', tf: '15분', ttf: '30분'}}, {{tf: '15분', trend_tf: '15분'}}), F.barsKo({{tf: '15분', ttf: '30분'}})],
      vals: MX.valsKo({{...bar, rule: 'h0x'}}), h0x: [MX.h0xVal({{x0: 1, h6: 0.5}}), MX.h0xVal({{x0: 0, h6: -0.2}}), MX.h0xVal({{close: 1}})],
      rule: MX.RULE_KO.h0x, ui: [MX.RANGE_UI.api, MX.RANGE_UI.perf, MX.RANGE_UI.account, MX.RANGE_UI.tf, MX.MIX_UI.tf, MX.BYBIT_UI.tf],
      waits: [MX.MIX_UI.wait, MX.RANGE_UI.wait, MX.BYBIT_UI.wait],
      tf: [MX.tfOf({{status: {{tf_ko: '15분'}}}}), MX.tfOf(null), MX.tfOf({{tf_ko: '15분'}})],
      cells: [F.trendCell({{state: 'ok', trend: -1, trend_ko: '하락', bar: {{ko: '하락', colour_ko: '빨강', n: [1, 4, 1]}}}}),
        F.trendCell({{state: 'ok', trend: 0, trend_ko: '횡보', bar: {{ko: '횡보', colour_ko: '노랑', n: [2, 2, 2]}}}})],
      h0xKo: F.h0xKo({{x0: -1, h6: -4.08, ko: '0선 아래로 돌파'}}),
      who: [F.srcWho({{name_ko: '친구 15분 봇', tf_ko: '15분', trend_tf_ko: '30분'}}, 'x', 'y'), F.srcWho(null, '친구 30분 봇', '30분')],
      tab: LB.TABS.find((t) => t.id === 'rangebot').label, mixLabel: LB.TABS.find((t) => t.id === 'mixbot').label,
      heads: [bt.head(moved), bt.head(before)], only: [bt.only(moved), bt.only(before)], none: [bt.none(moved), bt.none(before)],
      movedFn: [LR.rangeMoved(moved), LR.rangeMoved(before), LR.rangeMoved(null)], parts: LR.RANGE_PARTS.map((x) => x.label),
      mixes: HQ.MIX_BOTS.map((m) => [m.slot, m.bot, m.api, m.replaces, m.tab]), name: [HQ.mixName({{bot: 'x', d: {{name_ko: '친구 15분 봇'}}}}), HQ.mixName({{bot: '레인지 봇', d: null}})],
      gate: HQ.mixGate({{status: {{state: 'running', tf_ko: '15분'}}, halts: {{items: []}}, blocks: {{state: 'ok', now: {{blocked: false}}}}, position: null}}),
      real, ids, ids0,
      off: [HQ.mainOff({{execs: [], replaced: [{{id: 'mexc'}}]}}), HQ.mainOff({{execs: []}}), HQ.mainOff({{execs: [{{id: 'bybit', bot: 'paper'}}], replaced: [{{id: 'mexc'}}]}})],
      led: HQ.mixLed({{status: {{state: 'stopped', stale_ms: 1200000}}}}, false, {{unit: 'paperbot-mixrange'}}).why,
      screens: ['rangebot', 'mixbot'].map((k) => [R.SCREENS[k].ko, R.SCREENS[k].title])}}));""")
    t = out["trend"]
    assert t[0] == ("추세 바 종합 하락 빨강 (상승 1 · 하락 4 · 횡보 1: 3개 점수 −1 · 6종 평균 하락 · 하늘·보라 선 보라 · EMA RSI 빨강 · "
                    "슈퍼트렌드 상승 · 4종 평균 하락)")
    assert t[1].startswith("추세 바 종합 횡보 노랑(진입 금지) (상승 2 · 하락 2 · 횡보 2: 3개 점수 0 ·") and t[2].startswith("추세 바 종합 상승 초록 (") and "3개 점수 +3" in t[2]
    # owners 10-31, last: the trend's own bar (trend_tf), else the row's bar
    assert t[3].startswith("추세 바 30분 종합 하락 빨강 (상승 1") and t[4].startswith("추세 바 15분 종합 하락 빨강 (")
    wo = out["waitOf"]
    assert wo[0].startswith("30분봉이 끝날 때 추세 바 종합(") and "AC 막대가 그 쪽" in wo[0]          # (a bot whose trend is its own bar)
    assert wo[1] == out["waits"][1] and wo[2] == out["waits"][0]
    assert out["plan"] == ["손절 = 진입 때 15분봉 ATR × 3 · 증거금 = 잔고의 40%", "손절 = 진입 때 30분봉 ATR × 3 · 증거금 = 잔고의 40%", None]
    assert out["labels"] == ["15분 신호 · 추세 30분 (바이비트 봇)", "30분 (친구 30분 봇)", "15분 (레인지 봇)", "15분 신호 · 추세 30분"]
    assert out["vals"].startswith("추세 바 종합 하락 빨강") and "히스토그램 0선 아래로 돌파 −4.08" in out["vals"] and "찹존" not in out["vals"]
    assert out["h0x"] == ["히스토그램 0선 위로 돌파 0.50", "히스토그램 0선 돌파 없음 −0.20", None] and out["rule"] == "히스토그램 0선 돌파"
    assert out["ui"] == ["/api/v4/livebots/mixrange", "/api/v4/livebots/mixrangeperf", "WOO X Pro", "15분", "15분", "15분"]
    w_mix, w_range, w_bybit = out["waits"]
    assert w_mix.startswith("15분봉이 끝날 때 30분봉의 추세 바 종합") and "히스토그램이 0선을 그 쪽으로 돌파" in w_mix and w_range == w_mix
    assert w_bybit.startswith("15분봉이 끝날 때 30분봉의 추세 바 종합") and "AC 막대가 그 쪽(롱: 플러스 양봉, 숏: 마이너스 음봉)" in w_bybit
    assert "노랑 = 진입 금지" in w_mix and "찹존" not in w_mix + w_bybit
    assert out["tf"] == ["15분", "30분", "15분"]
    assert out["cells"] == [{"text": "종합 하락 빨강", "tone": "down", "sub": "상승 1 · 하락 4 · 횡보 1"},
                            {"text": "종합 횡보 노랑", "tone": "flat", "sub": "상승 2 · 하락 2 · 횡보 2 · 진입 금지"}]
    assert out["h0xKo"] == "히스토그램 0선 아래로 돌파 (−4.08)"
    assert out["who"] == [{"name": "친구 15분 봇", "tf": "15분", "ttf": "30분"}, {"name": "친구 30분 봇", "tf": "30분", "ttf": None}]
    assert out["tab"] == "레인지 봇" and out["mixLabel"] == "친구 15분 봇"
    h = out["heads"]
    assert h[0] == "레인지 봇 · WOO X Pro 계정 실거래와 모의 쌍둥이 (15분봉 진입 · 추세 바 30분 종합 + 히스토그램 0선 돌파) · 다른 봇은 이 화면에 없어요"
    assert h[1].startswith("레인지 봇 페이퍼(연습)와 그 봇을 따라가는") and out["only"] == [[], ["mexc"]]
    assert out["none"] == ["레인지 봇은 WOO X Pro 계정에서 스스로 거래해요 · 잔고는 아래 실거래 칸", "레인지 봇을 따라가는 실행기가 아직 없어요 (페이퍼만)"]
    assert out["movedFn"] == [True, False, False] and out["parts"] == ["관제", "성적 · 모의 비교", "지난 페이퍼 기록"]
    assert out["mixes"][-1] == ["mexc", "레인지 봇", "/api/v4/livebots/mixrange", "mexc", "rangebot"]
    assert out["mixes"][0][1] == "친구 15분 봇" and out["name"] == ["친구 15분 봇", "레인지 봇"]
    assert out["off"] == [True, False, False]
    # no executor at all (both slots taken): the strip names the accounts and their bots, the lists are empty; an answer
    # without ``execs``: the two of before
    assert "진짜 돈 · 바이비트 · 바이비트 봇 · WOO X Pro · 레인지 봇 (스스로 매매 · 잔고는 각 봇 화면)" in out["real"]
    assert out["ids"] == [[], []] and out["ids0"] == ["bybit", "mexc"]
    assert out["gate"] == "가능 · 15분봉 신호를 기다려요" and out["led"].startswith("20분 넘게 새 기록이 없어요")
    assert out["screens"][0][0] == "레인지 봇" and "히스토그램 0선 돌파" in out["screens"][0][1]
    assert out["screens"][1] == ["친구 15분 봇", "친구 15분 봇 (15분봉 · 추세 바 30분 + 히스토그램 0선 돌파 · WOO X Pro 2 실거래와 모의)"]


TAB_JS = """
for (const [k, f] of Object.entries({after: (p, i, x) => p.childNodes.splice(i + 1, 0, x), before: (p, i, x) => p.childNodes.splice(i, 0, x),
  replaceWith: (p, i, x) => p.childNodes.splice(i, 1, x)})) if (!Node.prototype[k]) Node.prototype[k] = function (x) {
  const p = this.parentNode; if (!p) return; f(p, p.childNodes.indexOf(this), x); x.parentNode = p; };
const LB = await import('file://SCREENS/livebots.js');
const PB = await import('file://V4/core/pb.js');
const run = async (sum, part) => {
  const asked = [];
  if (part) PB.local.set('lrb-part', part);
  const ctx = {params: {arg: 'rangebot', query: {}}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, timeout() {},
    href: (n) => '#/' + n, setTitle() {}, go() {}, every() {},
    api: async (path) => { asked.push(path); const a = {'/api/v4/livebots': sum, '/api/v4/livebots/mixrange': D_c, '/api/v4/livebots/mixrangeperf': D_p,
      '/api/v4/livebots/range': D_r}[path.split('?')[0]];
      if (a === undefined) throw Object.assign(new Error('x'), {status: 503}); return JSON.parse(JSON.stringify(a)); }};
  const el = new Node('div'); await LB.mount(el, ctx); await tick(); await tick(); await tick();
  return {text: texts(el), asked};
};
const before = await run(D_s0), after = await run(D_s1), old = await run(D_s1, 'old'), perf = await run(D_s1, 'perf');
console.log(JSON.stringify({before, after, old, perf}));
"""


def test_the_range_tab(site, tmp_path, monkeypatch):
    """The 레인지 봇 tab (screens/livebots-range.js rangeBotView): before the move the old screen as it was (/range); after it
    the mix bot's 관제 (/mixrange) with the 성적 · 모의 비교 and the old screen as 지난 페이퍼 기록 one switch away."""
    from paperbot.dash.more import liverange as RG
    mp = X.paths(_range_files(str(tmp_path / "r")), bot="range")
    s0 = json_finite(L.build(L.paths(site["env"]), LW.NOW))
    site["cfg"].write_text("{}", encoding="utf-8")
    s1 = json_finite(L.build(L.paths(site["env"]), LW.NOW))
    rg = json_finite(RG.build(L.paths(site["env"]), L.paths_more({}), LW.NOW))
    out = _node(tmp_path, TAB_JS.replace("SCREENS", SCREENS).replace("V4", V4), s0=s0, s1=s1, c=X.control(mp, NOW), p=X.perf(mp, NOW), r=rg)
    b, a, o, pf = out["before"], out["after"], out["old"], out["perf"]
    assert "/api/v4/livebots/range" in b["asked"] and "/api/v4/livebots/mixrange" not in b["asked"]
    assert "레인지 봇 페이퍼(연습)와" in b["text"]
    assert "/api/v4/livebots/mixrange" in a["asked"] and "/api/v4/livebots/range" not in a["asked"]
    assert "/api/v4/livebots/goalres?bot=range" in a["asked"]
    for w in ("레인지 봇 · WOO X Pro 계정 실거래와 모의 쌍둥이 (15분봉 진입 · 추세 바 30분 종합 + 히스토그램 0선 돌파)", "레인지 봇은 WOO X Pro 계정에서 스스로 거래해요",
              "관제", "성적 · 모의 비교", "지난 페이퍼 기록", "실거래 · WOO X Pro", "진짜 돈 · WOO X Pro 계정", "바닥선 없음",
              "히스토그램 0선 아래로 돌파", "추세 바 30분 종합 횡보 노랑(진입 금지)", "봇은 15분봉이 끝날 때마다 기록해요",
              "15분봉이 끝날 때 30분봉의 추세 바 종합"):
        assert w in a["text"], w
    assert not BAD.search(a["text"]), BAD.search(a["text"])
    assert "/api/v4/livebots/range" in o["asked"] and "지난 기록" in o["text"] and "스스로 거래해요" in o["text"]
    assert "/api/v4/livebots/mixrangeperf" in pf["asked"] and "실거래 vs 모의" in pf["text"] and "5년 재생이 없어" in pf["text"]
    assert "손절 = 진입 때 15분봉 ATR × 3" in pf["text"]


HQ_JS = """
for (const [k, f] of Object.entries({after: (p, i, x) => p.childNodes.splice(i + 1, 0, x), before: (p, i, x) => p.childNodes.splice(i, 0, x),
  replaceWith: (p, i, x) => p.childNodes.splice(i, 1, x)})) if (!Node.prototype[k]) Node.prototype[k] = function (x) {
  const p = this.parentNode; if (!p) return; f(p, p.childNodes.indexOf(this), x); x.parentNode = p; };
const K = await import('file://SCREENS/livebots-kit.js');
const HQ = await import('file://SCREENS/livebots-hq.js');
const asked = [];
const ctxOf = () => ({params: {query: {}, arg: ''}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, timeout() {},
  href: (n) => '#/' + n, every(ms, fn, o) { if (o && o.now === false) return; fn(); },
  api: async (path) => { asked.push(path); const a = {'/api/v4/livebots/mixrange': D_r, '/api/v4/livebots/mixbybit': D_b}[path];
    if (a === undefined) throw Object.assign(new Error('x'), {status: 503}); return JSON.parse(JSON.stringify(a)); }});
const view = async (S) => {
  K.setPapers(S.papers); K.setExecs(S.execs);
  const v = HQ.hqView(ctxOf(), {get: () => S, state: () => 'ok', at: () => S.now_ms, retry: () => {}});
  await tick(); v.set(S, 'ok'); await tick(); await tick(); await tick();
  const w = D.walk(v.el);
  const shown = (n, acc = []) => { if (!n || n.hidden) return acc; if (n.className) acc.push(String(n.className)); for (const k of n.childNodes || []) shown(k, acc); return acc; };
  const cls = shown(v.el);
  return {text: w.text.replace(/\\s+/g, ' '), mixr: cls.filter((x) => x.split(' ').includes('lbh-mixr')).length,
    execCards: cls.filter((x) => x.split(' ').includes('lbh-reactor') && !x.split(' ').includes('lbh-mix')).length, ids: K.execsNow()};
};
const one = await view(D_s1);
const none = await view(D_s2);
console.log(JSON.stringify({one, none, asked: asked.filter((x) => x.endsWith('mixrange')).length}));
"""


def test_hq_shows_the_range_bot_and_no_executor_once_every_slot_is_taken(site, tmp_path):
    site["cfg"].write_text("{}", encoding="utf-8")
    s1 = json_finite(L.build(L.paths(site["env"]), LW.NOW))
    site["bybit"].write_text("{}", encoding="utf-8")
    s2 = json_finite(L.build(L.paths(site["env"]), LW.NOW))
    r = json_finite(X.control(X.paths(_range_files(str(tmp_path / "r")), bot="range"), NOW))
    b = json_finite(X.control(X.paths(_write(str(tmp_path / "b"), [START], [START]), bot="bybit"), NOW))
    out = _node(tmp_path, HQ_JS.replace("SCREENS", SCREENS), s1=s1, s2=s2, r=r, b=b)
    one, none = out["one"], out["none"]
    assert one["mixr"] == 1 and one["ids"] == ["bybit"] and one["execCards"] == 1 and out["asked"] >= 1
    coins = "·".join(x.symbol.replace("USDT", "") for x in _cfg_range().coins)
    for word in ("WOO X Pro 진짜 돈 봇 레인지 봇 스스로 매매 · 페이퍼를 따라가지 않음", "레인지 봇 관제 · 성적 →", f"15분봉 신호 · {coins}",
                 "신호등 없음 · 15분봉 신호마다 바로 들어가요", " · 추세 30분봉"):
        assert word in one["text"], word
    assert "WOO X Pro 진짜 돈 봇 레인지 봇 따라감" not in one["text"]                    # the old executor's card is gone
    assert none["ids"] == [] and none["execCards"] == 0 and none["mixr"] == 1
    assert "바이비트 진짜 돈 봇 바이비트 봇 스스로 매매" in none["text"] and "따라감 · 그 봇의 페이퍼 진입을 실거래로" not in none["text"]
    # no executor follows the 추세판단 봇 (none at all): the centre is the bots trading now (tests/test_rules1030.py)
    assert "실거래 봇 " in none["text"] and "개 돌아가는 중" in none["text"] and "고리 = 지금 실거래 봇" in none["text"]
    assert not BAD.search(none["text"]), BAD.search(none["text"])


def test_the_files():
    for f in ("livebots-mix.js", "livebots-range.js", "livebots-ftrend.js", "livebots-hq.js", "livebots.js", "livebots-kit.js", "livebots-pos.js"):
        r = subprocess.run(["node", "--check", os.path.join(SCREENS, f)], capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    from tests.test_dash_livebots_fees import house_rules
    house_rules("livebots-range", "lrb")
    house_rules("livebots-ftrend", "lft")
    inv = open(os.path.join(V4, "INVENTORY.md"), encoding="utf-8").read()
    assert "/api/v4/livebots/mixrange" in inv and "rangeBotView" in inv and "추세 바" in inv
    src = open(os.path.join(ROOT, "paperbot", "dash", "more", "livemix.py"), encoding="utf-8").read()
    assert '"/api/v4/livebots/mixrange"' in src and '"/api/v4/livebots/mixrangeperf"' in src
