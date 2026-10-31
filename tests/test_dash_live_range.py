"""Three paper bots on the 실거래 site (owners 10-26, docs/range-bot-ko.md: WOO X Pro moved from the 추세판단 봇 to the new
레인지 봇, 딥코인 still follows the 'VWAP 개선판'; tests/range_world.py).

The bug: the page held two paper bots at most ("paper" and the first other database an executor follows as "paper2"), so
with WOO X Pro on range.db the 레인지 봇 took the second place, the VWAP 개선판 screen found no VWAP bot and said 꺼짐, and
딥코인's paper was "other". Now each bot is told by its own config (VWAP: its gates; 레인지 봇: the ``range`` section of its
start record's config, never the file name), the 레인지 봇 is "range", and every screen names each executor's bot."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3

import pytest

from paperbot.dash.app import json_finite
from paperbot.dash.more import liveinsight as I
from paperbot.dash.more import livebots as L
from paperbot.dash.more import livejournal as J
from paperbot.dash.more import livemissed as M
from paperbot.dash.more import livepos as P
from paperbot.dash.more import livetape as TP
from paperbot.dash.more import livetrend as LT
from paperbot.dash.more import livevwap as VW
from paperbot.dash.more import livewhy as Y


@pytest.fixture(autouse=True, scope="module")
def _deepcoin_kept_for_these_tests():
    """Owners 10-31: 딥코인 is retired from the site (livebots.RETIRED_SLOTS); these worlds keep it as the VWAP 개선판's
    follower to check three paper bots side by side (tests/test_retired_slots.py: the site without it)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(L, "RETIRED_SLOTS", ())
        yield
from tests import range_world as RW
from tests import trend_vwap_world as TW

NOW, MIN, H, DAY = RW.NOW, RW.MIN, RW.H, RW.DAY


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("range") / "w")
    return RW.build(d), RW.more(d)


@pytest.fixture
def rw(world, monkeypatch):
    p, more = world
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    L._cache.clear()
    yield p, more
    L._cache.clear()


def _by(xs, key="id"):
    return {x[key]: x for x in xs}


# ---------------------------------------------------------------- the bug: three paper bots, each by its own config
def test_three_paper_bots_each_by_its_own_config(rw):
    p, more = rw
    d = L.build(p, NOW)
    assert [(b["id"], b["short_ko"], os.path.basename(b["path"])) for b in d["papers"]] == [
        ("paper", "추세판단 봇", "live-ac.db"), ("paper2", "VWAP 개선판", "vwap.db"), ("range", "레인지 봇", "range.db")]
    assert [b["label_ko"] for b in d["papers"]] == ["추세판단 봇 (바이비트가 따라감)", "VWAP 개선판 (딥코인이 따라감)",
                                                     "레인지 봇 (WOO X Pro가 따라감)"]
    x = _by(d["execs"])
    assert {k: (v["bot"], v["follows_ko"]) for k, v in x.items()} == {
        "bybit": ("paper", "추세판단 봇"), "mexc": ("range", "레인지 봇"), "deepcoin": ("paper2", "VWAP 개선판")}
    assert x["mexc"]["switched_ms"] == RW.RSWITCH and x["deepcoin"]["switched_ms"] == TW.LIVE_SINCE
    a = _by(d["accts"])
    assert [i for i in a if a[i]["kind"] == "paper"] == ["paper", "paper2", "range"]
    assert a["range"]["bot_ko"] == "레인지 봇" and a["range"]["followers"] == ["WOO X Pro"] and a["range"]["state"] == "ok"
    assert (a["mexc"]["follows_ko"], a["deepcoin"]["follows_ko"]) == ("레인지 봇", "VWAP 개선판")
    # the VWAP 개선판 screen finds its bot again (it said 꺼짐), with 딥코인 following it
    loc = VW.locate(p, NOW, more)
    assert loc["state"] == "ok" and os.path.basename(loc["bot"]["path"]) == "vwap.db" and loc["bot"]["id"] == "paper2"
    v = VW.control(p, NOW, more)
    assert v["state"] == "ok" and [f["id"] for f in v["followers"]] == ["deepcoin"]


def test_the_range_bot_is_never_told_by_its_file_name(rw, tmp_path):
    """A database at range.db whose start record has no ``range`` section is not the 레인지 봇; a 레인지 봇 under another
    file name is."""
    p, more = rw
    fake = tmp_path / "range.db"
    shutil.copy(p["paper2"], fake)                         # the VWAP bot's records under the 레인지 봇's file name
    q = {**p, "range": str(fake), "mexc_db": str(tmp_path / "no-mexc.db"), "mexc_config": str(tmp_path / "no-mexc.json")}
    _c, _f, paper, execs = L.sources(q, NOW)
    assert [(b["id"], os.path.basename(b["path"])) for b in L.paper_bots(q, paper, execs)] == [("paper", "live-ac.db"), ("paper2", "vwap.db")]
    other = tmp_path / "x-bot.db"
    shutil.copy(p["range"], other)                         # the 레인지 봇's records under another name, WOO X Pro on it
    RW.mexc_db(str(tmp_path / "m.db"), str(other), p["paper"])
    q = {**p, "range": str(tmp_path / "none.db"), "mexc_db": str(tmp_path / "m.db")}
    _c, _f, paper, execs = L.sources(q, NOW)
    assert [(b["id"], os.path.basename(b["path"])) for b in L.paper_bots(q, paper, execs)] == [
        ("paper", "live-ac.db"), ("paper2", "vwap.db"), ("range", "x-bot.db")]


def test_one_and_two_paper_worlds_are_as_before(tmp_path, monkeypatch):
    """No 레인지 봇 anywhere: the ids and the answers as they were (the two-bot world of 10-23 and the one-bot world)."""
    from tests import livebots_world as W
    p1 = W.build_world(str(tmp_path / "one"))
    _c, _f, paper, execs = L.sources(p1, W.NOW)
    assert [b["id"] for b in L.paper_bots(p1, paper, execs)] == ["paper"]
    p2 = TW.build(str(tmp_path / "two"))
    _c, _f, paper, execs = L.sources(p2, TW.NOW)
    assert [(b["id"], b["short_ko"]) for b in L.paper_bots(p2, paper, execs)] == [("paper", "추세판단 봇"), ("paper2", "VWAP 개선판")]
    # a server whose range.db is not there yet: the default path changes nothing
    assert L.paths({})["range"] == "/var/lib/paperbot/combo/range.db" and "range" not in L.shown_paths({**p2, "range": str(tmp_path / "no.db")})


# ---------------------------------------------------------------- every existing screen names each executor's bot
def test_every_screen_names_each_executors_bot(rw):
    p, more = rw
    cards = _by(P.build(p, more, NOW)["cards"])
    assert [c for c in cards] == ["paper", "paper2", "range", "bybit", "mexc", "deepcoin", "flip"]
    assert {k: cards[k].get("follows_ko") for k in ("bybit", "mexc", "deepcoin")} == {"bybit": "추세판단 봇", "mexc": "레인지 봇", "deepcoin": "VWAP 개선판"}
    rc = cards["range"]["position"]
    assert rc["next"]["fixed"] is True and rc["next"]["at"] == 0.1 and rc["next"]["price"] == pytest.approx(RW.tp_price(1, 100.0, 30))
    assert {c["id"]: c["state"] for c in rc["execs"]} == {"bybit": "other", "mexc": "following", "deepcoin": "other"}
    assert rc["why"]["bot"] == "range"
    tr = L.trade_rows(p, NOW, more)["accts"]
    rows = {r["symbol"]: r for r in tr["range"]["rows"]}
    assert rows["BCHUSDT"]["reason_ko"] == "익절" and rows["BCHUSDT"]["live"]["mexc"]["state"] == "matched"
    assert rows["LTCUSDT"]["live"]["mexc"]["why_kind"] == "liq_skip"
    assert rows["BTCUSDT"]["live"]["mexc"]["why_ko"] == "이때 WOO X Pro는 추세판단 봇을 따라갔어요"      # R1: before its move
    assert rows["BCHUSDT"]["live"]["deepcoin"]["why_ko"] == "이때 딥코인은 VWAP 개선판을 따라갔어요"
    assert {r["paper"]["paper_id"] for r in tr["mexc"]["rows"]} == {"paper", "range"}
    assert all(r["why"]["bot"] == r["paper"]["paper_id"] for r in tr["mexc"]["rows"])
    pf = L.perf(p, NOW, more)["accts"]
    assert pf["mexc"]["era"] == {"other_ko": "레인지 봇", "now_other": True, "since": RW.RSWITCH, "other_n": 4}
    assert pf["range"]["short_ko"] == "레인지 봇" and pf["range"]["stats"]["trades"] == 6
    sg = L.signals(p, NOW, "range")
    assert sg["bot"] == "range" and sg["bot_ko"] == "레인지 봇" and [b["id"] for b in sg["bots"]] == ["paper", "paper2", "range"]
    cats = {c["cat"]: c["n"] for c in sg["counts"]["week"]}
    assert (cats["range_st"], cats["range_one"], cats["range_liq"], cats["nopull"]) == (1, 1, 1, 1)
    m = M.build(p, more, NOW, bot="range")
    assert m["kind"] == "plain" and m["bot_ko"] == "레인지 봇" and m["filter_note_ko"] == M.RANGE_FILTER_KO
    assert _by(m["groups"])["exec"]["n"] == 1 and M.build(p, more, NOW, bot="paper2")["filter_note_ko"] == M.PLAIN_FILTER_KO
    c = L.costs(p, NOW)
    assert any(x["kind"] == "liq_skip" for x in c["accts"]["mexc"]["missed"])
    assert _by(c["fees"]["execs"])["mexc"]["since_ko"] == "레인지 봇 따라간 때부터"
    h = [(i["id"], i["ko"]) for i in I.health(p, NOW, more)["items"] if i["id"].startswith(("paper", "range"))]
    assert h[-2:] == [("range_hb", "레인지 봇 심장 박동"), ("range_step", "레인지 봇 마지막 1분")] and ("paper2_hb", "VWAP 개선판 봇 심장 박동") in h
    wn = {i["id"]: i for i in L.whynow(p, NOW)["items"]}
    assert wn["range"]["ko"] == "레인지 봇이 돌고 있음" and wn["range"]["who"] == "mexc" and wn["paper2"]["who"] == "deepcoin"
    ev = J.build(p, 72, NOW, more)["events"]
    assert any(e["text"] == "WOO X Pro · LTC 숏 레인지 봇 진입을 안 따라갔어요" for e in ev)
    assert next(e for e in ev if e["id"] == f"x:mexc:start:{RW.RSWITCH}")["detail"].startswith("따라가는 페이퍼: 레인지 봇 (")
    tape = TP.build_list(p, NOW, bot="range")
    assert tape["bot"] == "range" and len(tape["rows"]) == 6
    cells = {c["id"]: c for c in tape["rows"][0]["execs"]}
    assert cells["mexc"]["state"] == "matched" and cells["deepcoin"]["why_ko"] == "이때 딥코인은 VWAP 개선판을 따라갔어요"
    assert cells["bybit"]["why_ko"] == "이때 바이비트는 추세판단 봇을 따라갔어요"
    st = L.settings(p, NOW)
    b = _by(st["bots"])["range"]
    assert b["short_ko"] == "레인지 봇" and b["followers"] == ["WOO X Pro"] and b["rules"]["take_profit_roe"] == 0.1
    from paperbot.rangebot import RangeRules
    assert [x["ko"] for x in b["rules"]["range_rules"]] == RangeRules.from_dict(RW.run_config("x", "y")["range"]).describe()
    assert {x["id"]: x.get("follows_ko") for x in st["execs"]} == {"bybit": "추세판단 봇", "mexc": "레인지 봇", "deepcoin": "VWAP 개선판"}
    g = I.goal(p, NOW, more)
    assert [s["id"] for s in g["h2h"]["sides"]] == ["paper", "paper2"] and _by(g["accts"])["mexc"]["era"]["bot_ko"] == "레인지 봇"
    assert set(L.map_view(p, NOW)["band"]["accounts"]) == {"paper", "paper2", "range", "bybit", "mexc", "deepcoin"}
    fo = _by(LT.build(p, NOW)["position"]["follow"])
    assert fo["deepcoin"]["state"] == "other_bot" and fo["deepcoin"]["bot_ko"] == "VWAP 개선판"


def test_a_range_entry_shows_its_own_checks(rw):
    p, more = rw
    r4 = next(r for r in RW.RANGE if r[0] == "R4")
    d = Y.build(p, more, "range", r4[1], r4[3], None, NOW)
    assert d["state"] == "ok" and d["range"] is True and d["bot_ko"] == "레인지 봇" and d["signal"]["strategy_ko"] == "레인지 필터 3중 일치"
    ck = _by(d["checks"])
    assert ck["st"]["ok"] is True and ck["st"]["ko"] == "추세 확인: 코인 1시간 슈퍼트렌드 상승 · BTC 1시간 슈퍼트렌드 상승 → 롱 통과"
    assert ck["liq"]["ok"] is True and "(30배)" in ck["liq"]["ko"]
    assert ck["pull"]["ok"] is True and "0.2 ATR 아래 100에 50분 만에 닿음" in ck["pull"]["ko"]
    assert ck["tp"]["ko"] == "익절은 순ROE +10% 고정 · 손절은 순ROE −50% (계단 없음)" and ck["one"]["ok"] is True
    assert d["five_year"]["reason_ko"] == Y.REF_RANGE_KO.format(name="레인지 봇")
    assert "A그룹" not in json.dumps(d, ensure_ascii=False) and (d["setting"] is None or d["setting"]["group"] is None)


def test_the_friends_trend_check_of_an_entry():
    """Owners 10-29: with ``friend_tf`` the entry's check reads the friend's trend and its votes the bot kept."""
    cfg = {"range": {"friend_tf": "1h", "coin_st": False, "btc_st": False}, "stop": {"mode": "roe", "roe": 0.5}}
    t0 = RW.KST0 + 3 * H
    info = {**RW.info_of("ETHUSDT", 1, t0, t0 + 15 * MIN), "friend": {"trend": 1, "line": 1, "ema": 1, "chop": 1, "st": 0}}
    info.pop("coin_st")
    info.pop("btc_st")
    ck = _by(Y.range_checks(cfg, t0 + 15 * MIN, 1, "ETHUSDT", 30, info, 0.0014))
    assert ck["friend"]["ok"] is True and "st" not in ck
    assert ck["friend"]["ko"] == ("추세 확인: 친구 추세지표 1시간 상승 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 상승 · 슈퍼트렌드 횡보)"
                                  " → 롱 통과")
    ck = _by(Y.range_checks(cfg, t0 + 15 * MIN, 1, "ETHUSDT", 30, {**info, "friend": None}, 0.0014))
    assert ck["friend"]["ok"] is None and ck["friend"]["ko"].endswith("기록 없음")
    # the plan's words on the site: the bot's own describe()
    from paperbot.rangebot import RangeRules
    rules = RangeRules.from_dict({"friend_tf": "1h", "coin_st": False, "btc_st": False})
    words = [x["ko"] for x in L.range_words({"range": {"friend_tf": "1h", "coin_st": False, "btc_st": False},
                                             "members": [{"pick": "ds-F7_RF_TRIPLE-1h-1"}]})]
    assert words == rules.describe() and words[0].startswith("추세 확인: 친구 추세지표 1시간봉")
    # the filtered signals' reasons have their own groups
    assert L.why_cat("FILTERED", "추세 확인: 친구 추세지표 1시간 진입 금지 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 횡보 · "
                                 "슈퍼트렌드 횡보)")[0] == "range_friend"
    assert L.why_cat("FILTERED", "추세 확인: ETH 1시간 슈퍼트렌드 하락(신호 롱와 반대)")[0] == "range_st"
    assert L.why_cat("FILTERED", "친구 추세지표를 못 읽어 진입 안 함: BTC 5분봉 10개뿐") == ("range_unread", "친구 추세지표 못 읽음")


def test_only_the_range_bot_without_a_vwap_bot(tmp_path, monkeypatch):
    """딥코인 not installed and no vwap.db: the 레인지 봇 is the page's second paper bot under its own id."""
    p = RW.build(str(tmp_path / "w"), deepcoin=False)
    p["paper2"] = str(tmp_path / "w" / "no-vwap.db")
    os.remove(os.path.join(str(tmp_path / "w"), "vwap.db"))
    more = RW.more(str(tmp_path / "w"))
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    d = L.build(p, NOW)
    assert [b["id"] for b in d["papers"]] == ["paper", "range"] and _by(d["execs"])["mexc"]["bot"] == "range"
    c = L.compare_papers(L.paper_bots(p, *L.sources(p, NOW)[2:]))
    assert c["twin"] is False and [r["id"] for r in c["rows"]] == ["paper", "range"]
    h2h = I.goal(p, NOW, more)["h2h"]
    assert h2h["live_since_ms"] == RW.RSWITCH and [s["id"] for s in h2h["sides"]] == ["paper", "range"]
    assert VW.locate(p, NOW, more)["state"] == "off"


# ---------------------------------------------------------------- the 레인지 봇 screen's answer
def test_the_range_answer_running(rw):
    from paperbot.dash.more import liverange as R
    p, more = rw
    d = R.build(p, more, NOW)
    s = d["status"]
    assert (s["state"], s["ko"]) == ("running", "켜져 있어요") and s["since_ms"] == RW.RANGE_SINCE and s["unit"] == "paperbot-combo-range"
    pl = d["plan"]
    assert pl["source"] == "db" and pl["tp"] == 0.1 and pl["stop"] == 0.5 and pl["margin"] == 0.4
    words = {x["key"]: x["ko"] for x in pl["lines"]}
    assert words["signal"].startswith("레인지 필터 3중 일치 (F7_RF_TRIPLE 1시간) · 커스텀값 rf_mult=9.0, rf_period=80")
    assert words["trend"] == "코인·BTC 1시간 슈퍼트렌드(10, 3)가 신호와 같은 방향일 때만"
    assert words["pull"].startswith("신호 1시간봉 종가에서 0.2 × ATR(14, 1시간) 되돌림을 최대 60분 기다려요")
    assert words["tp"] == "순ROE +10% 고정 (계단 없음) · 가격으로 40배 0.39%, 30배 0.47%"
    assert words["stop"] == "순ROE −50% · 가격으로 40배 1.11%, 30배 1.53%"
    assert words["size"].startswith("증거금 = 그때 잔고의 40%") and words["leverage"] == "BTC 40배 · 나머지 30배"
    assert "강제청산 여유" == next(x["k"] for x in pl["lines"] if x["key"] == "liq") and "0.5%" in words["liq"]
    assert words["pause"] == "한국 시간 토·일 · 나스닥 개장 앞 30분·뒤 30분 · 경제 발표 앞뒤 30분 (신호 때와 진입 때 둘 다 봄)"
    w = d["wallet"]
    assert w["state"] == "ok" and w["initial"] == 1000.0 and w["record"]["trades"] == 6 and w["record"]["wins"] == 4
    assert w["change"] == pytest.approx(w["wallet"] - 1000.0)
    assert d["today"]["trades"] == 3                                                # R4, R5, R6 closed today (KST)
    pos = d["position"]
    assert (pos["coin"], pos["side"], pos["leverage"]) == ("ETH", 1, 30)
    assert pos["tp"] == pytest.approx(RW.tp_price(1, 100.0, 30)) and pos["stop"] == pytest.approx(RW.sl_price(1, 100.0, 30))
    assert pos["roe"] == pytest.approx(30 * (0.002 - RW.RT)) and pos["range"]["level"] == pytest.approx(100.0)
    assert d["wait"] is None
    st = _by(d["supertrend"]["coins"], "coin")
    assert st["LTC"]["side"] is None and "3600개 필요" in st["LTC"]["error_ko"] and st["ETH"]["ko"] == "상승"
    f = _by(d["followers"])["mexc"]
    assert f["since_ms"] == RW.RSWITCH and f["record"]["trades"] == 4 and f["n_other"] == 3 and f["run"] == "running"
    assert f["position"]["coin"] == "ETH" and f["position"]["tp_roe"] == 0.1 and f["position"]["stop_roe"] == 0.5
    assert f["start_balance"] == 98.0 and f["balance"] == 91.8 and f["change"] == pytest.approx(-6.2)
    tr = d["trades"]
    assert [t["coin"] for t in tr] == ["BCH", "LTC", "DOGE", "SOL", "ETH", "BTC"]
    assert [c["state"] for t in tr for c in t["live"]] == ["followed", "missed", "followed", "followed", "followed", "before"]
    assert tr[0]["live"][0]["exit_ko"] == "익절" and tr[3]["live"][0]["exit_ko"] == "손절"
    fl = d["follow"][0]
    assert fl["counts"] == {"open": 1, "followed": 4, "missed": 1} and fl["why"][0]["kind"] == "liq_skip"
    assert fl["rows"][0]["open"] is True and fl["rows"][0]["state"] == "open"
    fp = d["flip"]
    assert [r["n"] for r in fp["rows"]] == [6, 6] and fp["gap"] == pytest.approx(4 / 6 - 2 / 6) and fp["few"] is True
    assert "아직 우연이 커요" in fp["lead_ko"]
    cats = {c["cat"]: c["n"] for c in d["signals"]["counts"]}
    assert cats["entered"] >= 4 and cats["range_liq"] == 1
    text = json.dumps(json_finite(d), ensure_ascii=False)
    assert "VWAP" not in text and "추세판단 봇" not in text.replace("이때 WOO X Pro는 추세판단 봇을 따라갔어요", "")
    assert "바이비트" not in text and "딥코인" not in text                       # only this bot's executors


def test_the_plan_follows_the_config_numbers(tmp_path, monkeypatch):
    """The plan is read from the config, never typed in: other numbers, other words."""
    from paperbot.dash.more import liverange as R
    path = str(tmp_path / "range.db")
    RW.range_db(path, over={"take_profit_roe": 0.12, "margin": 0.3, "leverage": {"BTCUSDT": 50, "default": 20},
                            "range": {**RW.TW.deploy("combo.range.json")["range"], "pullback_atr": 0.3, "wait_min": 45, "st_period": 12,
                                      "coin_st": True}})
    p = {**L.paths({}), "range": path, "paper": str(tmp_path / "none.db")}
    for k in ("bybit_db", "mexc_db", "bybit_config", "mexc_config"):
        p[k] = str(tmp_path / f"no-{k}")
    d = R.build(p, {**L.paths_more({}), "range_config": str(tmp_path / "no.json")}, NOW)
    words = {x["key"]: x["ko"] for x in d["plan"]["lines"]}
    assert words["tp"].startswith("순ROE +12% 고정") and "50배" in words["tp"] and "20배" in words["tp"]
    assert words["size"].startswith("증거금 = 그때 잔고의 30%") and words["leverage"] == "BTC 50배 · 나머지 20배"
    assert "0.3 × ATR" in words["pull"] and "최대 45분" in words["pull"] and "(12, 3)" in words["trend"]
    assert words["trend"].startswith("친구 추세지표 1시간봉") and "코인 1시간 슈퍼트렌드(12, 3)" in words["trend"]
    assert d["status"]["state"] == "running" and d["followers"] == []


def test_the_range_answer_off_missing_stopped_and_unreadable(tmp_path):
    from paperbot.dash.more import liverange as R
    base = {**L.paths({}), "paper": str(tmp_path / "none.db"), "range": str(tmp_path / "range.db")}
    for k in ("bybit_db", "mexc_db", "bybit_config", "mexc_config"):
        base[k] = str(tmp_path / f"no-{k}")
    more = {**L.paths_more({}), "range_config": str(tmp_path / "no.json")}
    d = R.build(base, more, NOW)
    s = d["status"]
    assert (s["state"], s["ko"]) == ("off", "아직 꺼져 있어요") and s["why_ko"] == "서버에 레인지 봇 기록 파일이 아직 없어요"
    assert s["guide"] == "docs/range-bot-ko.md" and os.path.exists(os.path.join(RW.TW.ROOT, s["guide"]))
    assert "sudo systemctl enable --now paperbot-combo-range" in s["steps"]
    assert d["plan"]["source"] == "repo" and "저장소의 설정 원본" in d["plan"]["reason_ko"] and d["plan"]["tp"] is None
    # owners 10-30: the repository's config has the ladder (net ROE 10 % -> lock 8 %, then 5 %); 10-31: 추세 3개 일치 only
    pl = {x["key"]: x["ko"] for x in d["plan"]["lines"]}
    assert pl["tp"].startswith("계단 익절 순ROE 10%에서 8% 잠금, 그 뒤 5%씩 (고정 익절 없음)")
    assert pl["stop"].startswith("추세 3개 일치는 15분 ATR(14) × 3") and pl["ema3"].startswith("EMA RSI · 하늘·보라 선 · 슈퍼트렌드")
    assert pl["signal"].startswith("추세 3개 일치 (EMA RSI") and "pull" not in pl and "roc" not in pl
    assert d["wallet"] is None and d["position"] is None and d["trades"] == [] and d["flip"] is None
    # a config on the server: the plan from it, said so
    (tmp_path / "cfg.json").write_text(json.dumps(RW.TW.deploy("combo.range.json")), encoding="utf-8")
    d = R.build(base, {**more, "range_config": str(tmp_path / "cfg.json")}, NOW)
    assert d["plan"]["source"] == "server" and d["status"]["state"] == "off"
    # a database without its first start record: 첫 기록 전 (수집 전), nothing made up
    from paperbot.store3 import Store3
    Store3(str(tmp_path / "range.db")).close()
    d = R.build(base, more, NOW)
    assert d["status"]["state"] == "missing" and d["status"]["why_ko"] == R.FIRST_KO and d["wallet"] is None
    # the bot's records but its heartbeat 10 minutes old: 기록 멈춤
    os.remove(str(tmp_path / "range.db"))
    RW.range_db(str(tmp_path / "range.db"))
    d = R.build(base, more, NOW + 10 * MIN)
    assert d["status"]["state"] == "stopped" and "systemctl status paperbot-combo-range" in d["status"]["why_ko"]
    assert d["wallet"]["state"] == "ok"                                              # its numbers stay readable
    # garbage: 못 읽음 with why
    (tmp_path / "bad.db").write_bytes(b"not a database" * 200)
    d = R.build({**base, "range": str(tmp_path / "bad.db")}, more, NOW)
    assert d["status"]["state"] == "error" and d["status"]["reason_ko"] and d["trades"] == []
    # a database whose bot is not the 레인지 봇 (no range in its config): said so, never taken for it
    TW.vwap_db(str(tmp_path / "vw.db"), 0, NOW)
    d = R.build({**base, "range": str(tmp_path / "vw.db")}, more, NOW)
    assert d["status"]["state"] == "other" and d["status"]["why_ko"] == R.NOT_RANGE_KO


def test_the_pullback_wait(tmp_path, monkeypatch):
    from paperbot.dash.more import liverange as R
    p = RW.build(str(tmp_path / "w"), wait=True)
    more = RW.more(str(tmp_path / "w"))
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    d = R.build(p, more, NOW)
    w = d["wait"]
    assert d["position"] is None and (w["coin"], w["side"]) == ("SOL", 1) and w["level"] == pytest.approx(150.0 - 0.2 * 2.0)
    assert w["until"] == NOW - NOW % H + 60 * MIN and w["left_ms"] == w["until"] - NOW and w["hit"] is None
    assert d["supertrend"]["busy_ko"] == "한 신호씩: SOL 롱 되돌림 기다리는 중"
    assert any(r["cat"] == "pullback_wait" for r in d["signals"]["rows"])


# ---------------------------------------------------------------- 목표 연구 for the 레인지 봇
def test_goal_research_for_the_range_bot(rw):
    from paperbot.dash.more import livegoalres as G
    p, more = rw
    d = G.build("range", p, NOW, more)
    assert d["state"] == "ok" and d["name_ko"] == "레인지 봇" and [a["id"] for a in d["accounts"]] == ["paper", "mexc"]
    it = _by(d["items"])
    assert set(it) == {"gap_mexc", "flip", "regime", "stops", "study"}
    assert it["flip"]["lead_ko"].startswith("진짜 4승 2패 · 동전 2승 4패 → 승률 33%p 높아요")
    assert it["regime"]["tone"] == "thin" and "본전 승률 약" in it["regime"]["lead_ko"]
    kp = {k["label_ko"]: k["value"] for k in it["regime"]["kpis"]}
    assert kp["연구 10월 승률"] == pytest.approx(40 / 41) and kp["연구 평소 승률"] == 0.77
    s = it["stops"]
    assert s["lead_ko"] == "손절 2번 중 1번은 24시간 안에 익절 자리까지 갔어요 (손절이 가까웠음) · 1번은 그대로 갔어요 (방향이 틀림)"
    rows = {r["coin"]: r for r in s["table"]["rows"]}
    assert rows["LTC"]["kind"] == "close" and rows["LTC"]["after_ko"] == "180분 뒤 익절 자리 닿음"
    assert rows["SOL"]["kind"] == "wrong" and rows["SOL"]["tp_px"] == pytest.approx(RW.tp_price(1, 100.0, 30))
    st = it["study"]
    assert "40승 1패 ×5.53" in st["lead_ko"] and "본전(약 82%)" in st["lead_ko"] and "×0.66" in st["lead_ko"] and "실거래 아님" in st["lead_ko"]
    assert "4 / 21" in json.dumps(st, ensure_ascii=False) and st["how_ko"].startswith("analysis/f7tp10_1026/FINAL_KO.md")
    assert os.path.exists(os.path.join(RW.TW.ROOT, "analysis", "f7tp10_1026", "FINAL_KO.md"))
    # the other bots' answers keep their own followers only
    assert [a["id"] for a in G.build("vwap", p, NOW, more)["accounts"]] == ["paper", "deepcoin"]
    assert [a["id"] for a in G.build("trend", p, NOW, more)["accounts"]] == ["paper", "bybit"]


def test_goal_research_says_stops_unknown_without_bars_and_off_without_the_bot(rw, tmp_path):
    from paperbot.dash.more import livegoalres as G
    p, more = rw
    d = G.build("range", p, NOW, {**more, "rule_db": str(tmp_path / "none.db")})
    s = _by(d["items"])["stops"]
    assert s["state"] == "ok" and s["sub_state"]["state"] == "missing" and all(r["kind"] == "none" for r in s["table"]["rows"])
    from tests import livebots_world as W
    one = W.build_world(str(tmp_path / "one"))
    off = G.build("range", one, W.NOW, more)
    assert off["state"] == "off" and "docs/range-bot-ko.md" in off["ko"] and "accounts" not in off


# ---------------------------------------------------------------- the route on the live app
def test_the_route_on_the_live_app(world, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from paperbot.livedash import app as LA
    p, more = world
    env = {L.ENV[k][0]: v for k, v in p.items() if k in L.ENV}
    env[L.ENV_RANGE["range"][0]] = p["range"]
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for k in ("rule_db", "check_db", "improve_db", "combo_config", "combo2_config", "range_config"):
        monkeypatch.setenv(L.ENV_MORE[k][0], more[k])
    folder = os.path.dirname(p["paper"])
    snap = lambda: {n: os.stat(os.path.join(folder, n)).st_mtime_ns for n in sorted(os.listdir(folder))}   # noqa: E731
    before = snap()
    L._cache.clear()
    app = LA.create_app(None, b"s" * 32, candles=lambda *a, **k: [], ticker=lambda: {}, market=lambda: {}, frames=lambda *a: None,
                        liq_db=str(tmp_path / "no-liq.db"), inbox_db=str(tmp_path / "no-inbox.db"))
    assert "liverange" in LA.MODULES and app.state.more["liverange"]["routes"] == ["/api/v4/livebots/range"]
    c = TestClient(app)
    r = c.get("/api/v4/livebots/range")
    assert r.status_code == 200 and r.json()["bot"]["id"] == "range" and r.json()["status"]["state"] in ("running", "stopped")
    assert c.get("/api/v4/livebots/goalres?bot=range").json()["bot"] == "range"
    for path in ("/api/v4/livebots/signals?bot=range", "/api/v4/livebots/missed?bot=range", "/api/v4/livebots/replay?bot=range"):
        assert c.get(path).status_code == 200, path
    assert c.get("/api/v4/livebots/signals?bot=range").json()["bot"] == "range"
    assert snap() == before                                                          # read-only: nothing written


# ---------------------------------------------------------------- the screens in node
ROOT = RW.TW.ROOT
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
BAD = __import__("re").compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")


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
    r = __import__("subprocess").run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_range_view_in_node(rw, tmp_path):
    from paperbot.dash.more import liverange as R
    from paperbot.dash.more import livegoalres as G
    p, more = rw
    on = R.build(p, more, NOW)
    base = {**L.paths({}), "paper": str(tmp_path / "none.db"), "range": str(tmp_path / "range.db")}
    for k in ("bybit_db", "mexc_db", "bybit_config", "mexc_config"):
        base[k] = str(tmp_path / f"no-{k}")
    off = R.build(base, {**L.paths_more({}), "range_config": str(tmp_path / "no.json")}, NOW)
    wp = RW.build(str(tmp_path / "wait"), wait=True)
    L._cache.clear()
    wait = R.build(wp, RW.more(str(tmp_path / "wait")), NOW)
    gr = G.build("range", p, NOW, more)
    out = _node(tmp_path, f"""
    const X = await import('file://{SCREENS}/livebots-range.js');
    const GR = await import('file://{SCREENS}/livebots-goalres.js');
    const mkCtx = (a) => ({{params: {{query: {{}}}}, alive: () => true, track() {{}}, listen() {{}}, on() {{}}, watch() {{}}, href: (n) => '#/' + n,
      every() {{}}, api: async (u) => {{ globalThis.ASKED = u; return JSON.parse(JSON.stringify(a)); }}}});
    const run = async (a) => {{ const v = X.rangeView(mkCtx(a)); await tick(); await tick(); return texts(v.el); }};
    const g = GR.goalResSection(mkCtx(D_g), 'range'); await tick(); await tick(); const askedG = globalThis.ASKED;
    console.log(JSON.stringify({{on: await run(D_on), off: await run(D_off), wait: await run(D_w), goal: texts(g), asked: askedG,
      st: [X.statusOf(D_on.status, D_on.now_ms), X.statusOf(D_off.status, D_on.now_ms), X.statusOf({{...D_on.status, state: 'stopped'}}, D_on.now_ms)],
      cells: D_on.trades.map((t) => X.cellKo(t.live[0]).pill), wk: X.waitKo(D_w.wait, D_w.now_ms),
      stk: D_on.supertrend.coins.map((c) => X.stKo(c).text), pnl: [X.pnlKo(3.4), X.pnlKo(-16.4), X.pnlKo(null)]}}));""",
                on=on, off=off, w=wait, g=gr)
    a = out["on"]
    for word in ("레인지 봇", "켜짐", "따라가는 실행기: WOO X Pro (진짜 돈)", "페이퍼 지갑 (모의)", "진짜 돈 아님", "페이퍼 성적", "4승 2패",
                 "오늘 페이퍼 (한국 시간)", "WOO X Pro 잔고 (실거래)", "$91.80", "오늘 WOO X Pro (실거래)", "2승 0패 · +$6.70", "계획", "신호", "레인지 필터 3중 일치 (F7_RF_TRIPLE 1시간)",
                 "추세 확인", "코인·BTC 1시간 슈퍼트렌드(10, 3)", "되돌림 진입", "0.2 × ATR(14, 1시간)", "최대 60분", "강제청산 여유",
                 "순ROE +10% 고정 (계단 없음)", "순ROE −50%", "증거금 = 그때 잔고의 40%", "BTC 40배 · 나머지 30배", "지금 포지션", "ETH",
                 "익절", "손절", "강제청산", "WOO X Pro:", "익절 순ROE +10% (자기 체결가 기준)", "되돌림 기다림 · 1시간 슈퍼트렌드",
                 "포지션을 들고 있어 새 신호를 받지 않아요 (한 신호씩)", "1시간 슈퍼트렌드", "LTC 못 읽음", "최근 거래 · 페이퍼 vs 실거래",
                 "WOO X Pro 따라 들어감", "WOO X Pro 안 들어감", "WOO X Pro 옮기기 전", "이때 WOO X Pro는 추세판단 봇을 따라갔어요",
                 L.WHY_KO["liq_skip"], "페이퍼 진입 vs 실거래", "따라 들어감 4", "같이 들고 있음 1", "안 들어감 1", "진짜 방향 vs 동전 쌍둥이",
                 "진짜 방향 (레인지 봇)", "동전 방향 (쌍둥이)", "아직 우연이 커요", "잔고", "최근 24시간 신호", "강제청산 여유 부족",
                 "추세 확인 (슈퍼트렌드 반대)", "되돌림 안 옴", "한 신호씩 (기다림·포지션 중)", "주의 · 긴급 기록"):
        assert word in a, (word, a)
    assert not BAD.search(a), BAD.search(a)
    for bad in ("바이비트", "딥코인", "VWAP"):
        assert bad not in a, bad
    b = out["off"]
    for word in ("꺼짐", "아직 꺼져 있어요", "서버에 레인지 봇 기록 파일이 아직 없어요", "docs/range-bot-ko.md 3장 'B. 레인지 페이퍼 봇 켜기'",
                 "sudo systemctl enable --now paperbot-combo-range", "그 전에는 숫자를 만들지 않아요", "저장소의 설정 원본", "계단 익절 순ROE 10%에서 8% 잠금"):
        assert word in b, word
    assert "페이퍼 지갑 (모의)" not in b and "$" not in b.split("계획")[0] and not BAD.search(b)
    c = out["wait"]
    assert "되돌림 기다림" in c and "SOL 롱" in c and "페이퍼 포지션 없음" in c and not BAD.search(c)
    assert out["wk"] == "SOL 롱 · 149.60에 닿으면 다음 5분봉 시가에 진입 · 10/27 21:00까지 (1시간 남음)"
    st = out["st"]
    assert (st[0]["cls"], st[0]["pill"], st[0]["hint"]) == ("run", "켜짐", "")
    assert st[1]["cls"] == "off" and st[1]["line"].startswith("아직 꺼져 있어요") and "레인지 페이퍼 봇 켜기" in st[1]["hint"]
    assert st[2]["hint"] == "서버에서 systemctl status paperbot-combo-range"
    assert out["cells"] == ["따라 들어감", "안 들어감", "따라 들어감", "따라 들어감", "따라 들어감", "옮기기 전"]
    assert "LTC 못 읽음" in out["stk"] and out["pnl"] == ["+$3.40", "−$16.40", "모름"]
    g = out["goal"]
    for word in ("목표 연구", "레인지 봇 페이퍼(연습)", "WOO X Pro", "WOO X Pro: 실거래가 덜 버는 이유", "진짜 vs 동전: 신호의 방향이 동전보다 나은가",
                 "장세: 지금 10월 같은 장인가", "연구 10월 승률", "손절 해부: 손절이 가까웠나, 방향이 틀렸나", "손절이 가까웠음", "방향이 틀림",
                 "180분 뒤 익절 자리 닿음", "연구 기록: 이 구조를 지난 기간에 돌려 본 것", "×5.53", "×0.66"):
        assert word in g, word
    assert not BAD.search(g) and out["asked"] == "/api/v4/livebots/goalres?bot=range"


def test_the_menu_button_strip_and_names(rw, tmp_path):
    """봇별 › 레인지 봇 right after 추세판단 봇; its strip and head name WOO X Pro only; three paper bots' names everywhere
    (kit setPapers / acctKo / followLine / followersOf)."""
    p, more = rw
    summary = L.build(p, NOW)
    out = _node(tmp_path, f"""
    for (const [k, f] of Object.entries({{after: (p, i, x) => p.childNodes.splice(i + 1, 0, x), before: (p, i, x) => p.childNodes.splice(i, 0, x),
      replaceWith: (p, i, x) => p.childNodes.splice(i, 1, x)}})) if (!Node.prototype[k]) Node.prototype[k] = function (x) {{
      const p = this.parentNode; if (!p) return; f(p, p.childNodes.indexOf(this), x); x.parentNode = p; }};
    const R = await import('file://{V4}/core/routes.js');
    const K = await import('file://{SCREENS}/livebots-kit.js');
    const LB = await import('file://{SCREENS}/livebots.js');
    const asked = [];
    const mk = (tab) => ({{params: {{arg: tab, query: {{}}}}, alive: () => true, track() {{}}, listen() {{}}, on() {{}}, watch() {{}}, timeout() {{}},
      href: (n) => '#/' + n, setTitle() {{}}, go() {{}}, every() {{}},
      api: async (path) => {{ asked.push(path); if (path === '/api/v4/livebots') return JSON.parse(JSON.stringify(D_s));
        throw Object.assign(new Error('x'), {{status: 503}}); }}}});
    const strip = async (tab) => {{ const el = new Node('div'); await LB.mount(el, mk(tab)); await tick(); await tick();
      return D.walk(el).text.replace(/\\s+/g, ' '); }};
    const r = {{range: await strip('rangebot'), trend: await strip('trendbot'), vwap: await strip('vwapbot')}};
    K.setPapers(D_s.papers);
    console.log(JSON.stringify({{r, asked, group: R.GROUPS[0].screens, nav: R.navGroups(true)[0].items.map((x) => x.ko),
      screen: [R.SCREENS.rangebot.ko, R.SCREENS.rangebot.group, R.SCREENS.rangebot.mod], icon: R.screenIcon('rangebot').childNodes.length,
      fol: [K.followersOf(D_s, 'paper'), K.followersOf(D_s, 'range'), K.followersOf(D_s, 'paper2')],
      names: ['paper', 'paper2', 'range'].map((id) => K.acctKo(id)), line: K.followLine(D_s.papers), isp: ['range', 'mexc'].map(K.isPaperId),
      tab: LB.BOT_TAB.rangebot.bot}}));""", s=summary)
    assert out["group"] == ["bybitbot", "rangebot", "vwapbot", "mixbot", "trendbot"]          # (owners 10-29: 바이비트 봇 first, 추세판단 봇 last)
    assert out["nav"] == ["바이비트 봇", "레인지 봇", "VWAP 개선판", "친구 30분 봇", "추세판단 봇"]
    assert out["screen"] == ["레인지 봇", "bots", "livebots"] and out["icon"] > 5 and out["tab"] == "range"
    assert out["fol"] == [["bybit"], ["mexc"], ["deepcoin"]]
    assert out["names"] == ["추세판단 봇", "VWAP 개선판", "레인지 봇"] and out["isp"] == [True, False]
    assert out["line"] == "바이비트 → 추세판단 봇 · 딥코인 → VWAP 개선판 · WOO X Pro → 레인지 봇"
    head = lambda t: t.split("보기만 하는 화면(주문 버튼 없음)")[0]                   # noqa: E731  the strip, before its last words
    assert "WOO X Pro $91.80" in head(out["r"]["range"]) and "바이비트" not in head(out["r"]["range"]) and "딥코인" not in head(out["r"]["range"])
    assert "레인지 봇 페이퍼(연습)와 그 봇을 따라가는 WOO X Pro 실행기(진짜 돈) · 다른 봇은 이 화면에 없어요" in out["r"]["range"]
    assert "WOO X Pro" not in head(out["r"]["trend"]) and "바이비트" in head(out["r"]["trend"])
    assert "딥코인" in head(out["r"]["vwap"])
    assert "/api/v4/livebots/range" in out["asked"] and "/api/v4/livebots/goalres?bot=range" in out["asked"]


def test_the_files_keep_the_house_rules():
    import re
    from tests.test_dash_livebots_fees import house_rules, _read
    house_rules("livebots-range", "lrb")
    assert '"/api/v4/livebots/range"' in _read(SCREENS, "livebots-range.js")
    assert '@import url("livebots-range.css");' in _read(SCREENS, "livebots.css")
    assert re.search(r'^MODULES = MODULES \+ \("liverange",\)$', _read(ROOT, "paperbot", "livedash", "app.py"), re.M)
    assert "--series-rg:" in _read(V4, "tokens.css") and ".lb-a-range .lb-sw" in _read(SCREENS, "livebots.css")
    inv = _read(V4, "INVENTORY.md")
    assert "/api/v4/livebots/range" in inv and "livebots-range.js" in inv
    src = _read(ROOT, "paperbot", "dash", "more", "liverange.py")
    assert not re.search(r"open\([^)]*['\"][wa]b?['\"]", src) and "subprocess" not in src and ".unlink(" not in src
    assert ".env" not in src.replace("os.environ", "")
    doc = _read(ROOT, "docs", "livedash-ko.md")
    assert "레인지 봇" in doc and "/api/v4/livebots/range" in doc and "bot=trend|range|vwap|mix|v39" in doc
    example = _read(ROOT, "deploy", "dash.env.example")
    assert "#PAPERBOT_LIVE_RANGE_DB=" in example and "#PAPERBOT_LIVE_RANGE_CONFIG=" in example


def test_the_existing_views_draw_three_bots(rw, tmp_path):
    """요약 띠 · 한눈에 · 거래 · 성적 · 지도 · 포지션 in node with the three paper bots: each by its name, the 레인지 봇's own
    swatch and its fixed take-profit, nothing unread."""
    from tests.test_wooxpro2_slot import _node as w2_node
    p, more = rw
    sum_ = L.build(p, NOW)
    tr, pf, mp = L.trade_rows(p, NOW, more), L.perf(p, NOW, more), L.map_view(p, NOW)
    pos, gr = P.build(p, more, NOW), I.groups(p, NOW, more)
    out = w2_node(tmp_path, f"""
    const PO = await import('file://{SCREENS}/livebots-pos.js');
    K.setPapers(D_s.papers); K.setExecs(D_s.execs);
    const band = P.bandLine(mkCtx(null)); band.set(D_s, "ok");
    const hub = {{get: () => D_s, state: () => "ok", at: () => D_s.now_ms, retry: () => {{}}}};
    const t = await run(TR.tradesView, (u) => (u.startsWith('/api/v4/livebots/trades') ? D_t : {{accts: {{}}}}));
    const pe = await run(PE.perfView, (u) => (u.startsWith('/api/v4/livebots/perf') ? D_p : D_g));
    const m = await run(MA.mapView, D_m);
    const po = await run(PO.posView, D_o, hub);
    if (po.set) po.set(D_s, "ok");
    await tick();
    console.log(JSON.stringify({{band: texts(band.el), trades: texts(t.el), perf: texts(pe.el), map: texts(m.el), pos: texts(po.el),
      ids: [PE.idsOf(D_p), MA.idsOf(D_m.band)], sw: D.walk(m.el).classes.filter((c) => c.split(' ').includes('lbm-a-range')).length}}));""",
                 s=sum_, t=tr, p=pf, m=mp, o=pos, g=gr)
    for k in ("band", "trades", "perf", "map", "pos"):
        assert not BAD.search(out[k]), (k, BAD.search(out[k]))
    assert out["ids"][0][:3] == ["paper", "paper2", "range"] and out["ids"][1][:3] == ["paper", "paper2", "range"] and out["sw"] >= 1
    assert "레인지 봇" in out["trades"] and "VWAP 개선판" in out["trades"] and "추세판단 봇" in out["trades"]
    assert "레인지 봇" in out["perf"] and "레인지 봇 · 이 봇 시작부터 (아래 나눠 보기는 추세판단 봇만)" in out["map"]
    (rnx,) = [c["position"]["next"] for c in pos["cards"] if c["id"] == "range"]
    assert "익절가 (고정 익절)" in out["pos"] and f"순ROE +10% 고정 익절 · 거래소 화면 ROE 약 +{rnx['screen_at'] * 100:.1f}%" in out["pos"]
    assert "(닿으면 시장가로 전부 닫음 · 계단 없음)" in out["pos"]
    assert "따라감 · 레인지 봇" in out["pos"] and "따라감 · VWAP 개선판" in out["pos"]


# ---------------------------------------------------------------- the executor's own fixed take-profit (owners 10-27)
def test_the_executor_card_shows_its_fixed_take_profit_and_the_screen_roe(tmp_path, monkeypatch):
    """Owners 10-27 ("사진에서 익절가가 안나와서 그런데 익절가가 얼마야", "거래소에서 실시간 포지션 봤을때 기준으로 몇%"): the
    WOO X Pro executor follows the 레인지 봇 with its own +10 % net take-profit and no ladder (its trade's ``own`` record:
    ``tp`` 0.1, ``ladder`` {}). Its card's 익절가 is the last price where it closes it all (its own fill, leverage and round
    trip, as executor._own_tp), with the exchange screen's ROE there (leverage x the move, before fees)."""
    d = str(tmp_path / "w")
    p, more = RW.build(d), RW.more(d)
    from paperbot.executor import ExecStore
    st = ExecStore(p["mexc_db"], lock=False)
    bot = st.get_state("bot")
    rt = 2 * (0.00042 + 0.0002)
    bot["trade"]["own"] = {"fill_ms": bot["trade"]["entry_ts"], "best": bot["trade"]["entry_price"], "best_roe": None, "lock": None,
                           "rt": rt, "cost": {"taker_fee": 0.00042, "slippage": 0.0002}, "cost_rt": rt, "basis": "net",
                           "exchange": "wooxpro", "ladder": {}, "tp": 0.1}
    st.put_state("bot", NOW - 4_000, bot)
    st.commit()
    st.close()
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    L._cache.clear()
    try:
        pos = _by(P.build(p, more, NOW)["cards"])["mexc"]["position"]
    finally:
        L._cache.clear()
    t = bot["trade"]
    side, entry, lev = t["side"], t["entry_price"], t["leverage"]
    nx = pos["next"]
    assert nx["fixed"] is True and nx["at"] == 0.1 and nx["lock"] is None and nx["from"] == "exchange"
    assert nx["price"] == pytest.approx(entry * (1 + side * (0.1 / lev + rt)))
    assert nx["screen_at"] == pytest.approx(0.1 + lev * rt)                  # 30x: +13.72 % on the screen
    assert pos["ladder_from"] == "exchange" and pos["ladder"] == []
    # the paper card's fixed take-profit carries the screen ROE too
    rc = _by(P.build(p, more, NOW)["cards"])["range"]["position"]["next"]
    assert rc["fixed"] is True and rc["screen_at"] == pytest.approx(30 * (rc["price"] / 100.0 - 1.0))
