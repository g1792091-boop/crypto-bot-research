"""실거래 › VWAP 봇 (dash/more/livevwap.py; screens/livebots-vwap.js), owners 10-23: the second paper bot 'VWAP 개선판'
(docs/vwap-bot-ko.md) and the executor that follows it, on a world made by the real bot code (tests/vwap_site_world.py: the
ComboRunner with the owners' config and entry gates, the gates' picture by entrygates.picture, WOO X Pro switched to it by
its own start record, livecheck.db ``missed`` rows per the Telegram side's contract):

- which database is the VWAP bot (livebots.paper_bots, then its config: an entry gate or 'VWAP' in its name, never the file
  name alone); nothing VWAP in the one-paper world (꺼짐 with the guide's words) nor with the 10-19 −35 % twin; 수집 전 /
  못 읽음 states;
- 관제: running, its first start, who follows it since when and its own light (20 / 75 %), the rules in words, the position
  with the hold limit left and the gates it passed, every coin's sides now (and a stale / missing / failed picture), the
  pauses, the last 48 h of signals with the reasons and the gates' numbers (late and skipped too);
- 성적: the paper and its coin-flip twin (break-even from their own averages, PF, deepest drop), 실력 vs 운, the follower's
  checklist on its VWAP-era live trades only (the break-even stop line, the owners' 50 / 80 % rule, the two checks of the
  lead's correction), the research's numbers (scale.json read now, else the written values), the splits and the trades
  with the executor's part;
- 막은 신호: the filtered signals by reason (today / 7 days / since the start) and the watcher's virtual results per reason
  (the main paper's rows never; "아직 계산 전" before the ``paper`` column; the contract's read_rows(paper=) used when there);
- the routes on the live app (read-only), the menu, the tabs and the views in node, the house rules of the css."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paperbot import combo as C  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livevwap as VW  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from tests import test_dash_livebots_fees as FW  # noqa: E402
from tests import two_papers_world as TW  # noqa: E402
from tests import vwap_site_world as V  # noqa: E402

NOW, K, MIN, H, DAY = V.NOW, V.K, V.MIN, V.H, V.DAY
ROOT = FW.ROOT
SCREENS = FW.SCREENS
DOM = FW.DOM
BAD = FW.BAD


def _more(w_or_folder) -> dict:
    return dict(w_or_folder["more"])


@pytest.fixture(scope="module")
def w(tmp_path_factory):
    return V.build(str(tmp_path_factory.mktemp("vwap") / "w"))


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


def _fees(tmp_path, name: str) -> dict:
    """The one-paper world (tests/test_dash_livebots_fees.py: the trend bot, both executors following it) in a new folder."""
    folder = tmp_path / name
    folder.mkdir()
    return FW.build_world(folder)


def _answers(w, now=NOW):
    p, more = w["p"], _more(w)
    return VW.control(p, now, more), VW.perf(p, now, more), VW.blocked(p, now, more)


def _rec(trades):
    """The record the page must show, from the engine's own trade rows (independent of the module)."""
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    loss = [t for t in trades if t["pnl"] <= 0]
    aw = sum(t["roe"] for t in wins) / len(wins) if wins else None
    al = sum(t["roe"] for t in loss) / len(loss) if loss else None
    eq, peak, dd = 1000.0, 1000.0, 0.0
    for t in trades:
        eq = t["equity_after"]
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
    return {"n": n, "wins": len(wins), "losses": len(loss), "aw": aw, "al": al,
            "be": abs(al) / (aw + abs(al)) if aw is not None and al is not None else None,
            "pf": sum(t["pnl"] for t in wins) / -sum(t["pnl"] for t in loss) if loss else None, "dd": dd,
            "roe_sum": sum(t["roe"] for t in trades), "pnl": sum(t["pnl"] for t in trades)}


# ================================================================ which bot, and nothing VWAP elsewhere
def test_nothing_vwap_in_the_one_paper_world(tmp_path):
    f = _fees(tmp_path, "fees")
    p, more = f["p"], {**f["more"], "combo2_config": str(tmp_path / "no-combo-vwap.json")}
    for d in (VW.control(p, FW.NOW, more), VW.perf(p, FW.NOW, more), VW.blocked(p, FW.NOW, more)):
        assert d["state"] == "off" and d["reason_ko"] == VW.OFF_KO and "5장 B" in d["reason_ko"] and d["other_ko"] is None
        assert set(d) == {"now_ms", "state", "reason_ko", "reason", "other_ko", "off_ko"}           # nothing else is read or sent
    s = L.build(p, FW.NOW)
    assert s["papers"] is None and "VWAP" not in json.dumps(s, ensure_ascii=False)


def test_the_10_19_twin_is_not_the_vwap_bot(tmp_path):
    p = TW.build(str(tmp_path / "two"))
    more = {**L.paths_more({}), "combo_config": str(tmp_path / "no.json"), "combo2_config": str(tmp_path / "no2.json"),
            "check_db": str(tmp_path / "no-check.db")}
    d = VW.control(p, TW.NOW, more)
    assert d["state"] == "off" and d["other_ko"] == "두 번째 페이퍼 봇(규칙봇 15 −35%)은 VWAP 개선판이 아니에요"


def test_found_by_its_config_not_its_file_name(w, tmp_path):
    other = str(tmp_path / "second-paper.db")                         # the VWAP bot's records under another name
    shutil.copy(w["p"]["paper2"], other)
    p = {**w["p"], "paper2": other}
    with open(p["mexc_config"], encoding="utf-8") as fh:
        keep = fh.read()
    try:
        cfg = json.loads(keep)
        cfg["paper_db"] = w["p"]["paper"]                             # no executor names it: found by PAPERBOT_LIVE_PAPER2_DB
        with open(p["mexc_config"], "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        loc = VW.locate(p, NOW, _more(w))
        # WOO X Pro's start record still names vwap.db: that one is the second paper bot the site shows (paper_bots)
        assert loc["state"] == "ok" and loc["bot"]["path"] == w["p"]["paper2"]
    finally:
        with open(p["mexc_config"], "w", encoding="utf-8") as fh:
            fh.write(keep)
    # a database named vwap.db running another config is not the VWAP bot
    fake = str(tmp_path / "vwap.db")
    s = Store3(fake)
    s.put_state("combo_run", K(2, 9), {"taker_fee": 0.0005, "config": {**FW.CFG, "name": "추세판단 봇 그림자"}})
    s.close()
    f = _fees(tmp_path, "f2")
    d = VW.control({**f["p"], "paper2": fake}, FW.NOW, {**f["more"], "combo2_config": str(tmp_path / "none.json")})
    assert d["state"] == "off" and "VWAP 개선판이 아니에요" in d["other_ko"]


def test_before_its_first_record_and_an_unreadable_file(w, tmp_path):
    f = _fees(tmp_path, "f")
    cfg_file = str(tmp_path / "combo-vwap.json")
    with open(cfg_file, "w", encoding="utf-8") as fh:
        json.dump(V.vwap_config("x", "y"), fh)
    empty = str(tmp_path / "vwap.db")
    sqlite3.connect(empty).close()                                     # the file is there, no table yet
    more = {**f["more"], "combo2_config": cfg_file}
    d = VW.control({**f["p"], "paper2": empty}, FW.NOW, more)
    assert d["state"] == "missing" and d["reason_ko"] == VW.FIRST_KO and d["bot"]["path"] == empty
    with open(empty, "wb") as fh:
        fh.write(b"not a database at all" * 100)
    L._cache.clear()
    d = VW.perf({**f["p"], "paper2": empty}, FW.NOW, more)
    assert d["state"] == "error" and d["reason_ko"] and "paper" not in d


# ================================================================ 관제
def test_the_bot_its_follower_and_its_rules(w):
    d, _p, _b = _answers(w)
    assert d["state"] == "ok" and d["bot"]["name"] == "VWAP 개선판" and d["bot"]["path"] == w["p"]["paper2"]
    b = d["bot"]
    assert b["since_ms"] == V.VS and b["started_ms"] == V.VS and b["running"] is True and b["age_ms"] == 40_000
    assert VW.control(w["p"], NOW + 6 * MIN, _more(w))["bot"]["running"] is False      # the heartbeat 6 minutes old: stopped
    fol = {f["id"]: f for f in d["followers"]}
    assert set(fol) == {"mexc"} and d["following"] == ["mexc"]                       # Bybit follows the trend bot: not listed
    woo = fol["mexc"]
    assert woo["name_ko"] == "WOO X Pro" and woo["state"] == "following" and woo["since_ms"] == V.SWITCH and woo["until_ms"] is None
    # its own light (the executor's rule: 20 trades, 75 %) on the VWAP paper's closed trades, newest first
    pnls = [t["pnl"] for t in reversed(V.paper_trades(w["p"]["paper2"]))]
    assert woo["light"] == {**L.light(20, 0.75, pnls), "last_event": None} and woo["light"]["state"] == "building"
    assert woo["light"]["have"] == 7 and woo["light"]["wins"] == 5
    assert woo["position"]["key"] == d["position"]["key"] and woo["pos_state"] == "same"
    lines = d["rules"]["lines"]
    for want in ("매매법 VWAP 복귀 실패 30분 · CMO·샌드위치 캔들 1시간", "BTC 30배 · 나머지 30배 · 증거금 잔고의 40%", "손절 2 ATR",
                 "순ROE 12%에서 10% 잠금, 이후 5%씩", "손절 한 번에 계좌 최대 −20%", "4시간 추세 판단이 반대면 진입 안 함(4개 중 3개 반대; 보류는 진입)",
                 "변동성(ATR14%)이 지난 30일의 80% 위치보다 크면 진입 안 함(상위 20% 금지)", "보유 한도 96봉(30분 48시간 · 1시간 96시간)",
                 "진입 쉼: 주말(한국 시간 토·일) · 미국 경제 발표 앞뒤 30분 · 나스닥 개장 앞 30분·뒤 30분", "동전 쌍둥이"):
        assert any(want in x for x in lines), want
    assert d["rules"]["error"] is None and [m["hold_ko"] for m in d["rules"]["members"]] == ["48시간", "96시간"]


def test_paper_only_says_no_follower(tmp_path):
    w2 = V.build(str(tmp_path / "po"), switch=False, missed=False)
    d, p, _b = _answers(w2)
    assert d["state"] == "ok" and d["followers"] == [] and d["following"] == [] and d["no_follower_ko"] == "아직 따라가는 실행기 없음 (페이퍼만)"
    assert p["checklist"] == [] and all(t["live"] == {} for t in p["trades"]) and p["research"]["live"] == []


def test_the_position_with_its_hold_limit_and_the_gates_it_passed(w):
    d = VW.control(w["p"], NOW, _more(w))
    p = d["position"]
    raw = V.paper_position(w["p"]["paper2"])
    assert (p["symbol"], p["side"], p["strategy_id"], p["timeframe"]) == ("BTCUSDT", 1, "S3_CMO_SANDWICH", "1h")
    assert p["strategy_ko"] == "CMO·샌드위치 캔들 1시간" and p["entry_time"] == K(6, 11) == raw["entry_time"]
    assert p["entry"] == pytest.approx(raw["entry_price"]) and p["leverage"] == 30 and p["stop"] == pytest.approx(raw["stop_price"])
    assert p["margin"] == pytest.approx(raw["margin_initial"] or raw["margin"])
    # 96 bars of its own 1h bar from the entry: closed at the first minute past it ("TIME")
    assert p["limit_bars"] == 96 and p["limit_ms"] == 96 * H and p["deadline_ms"] == K(6, 11) + 96 * H
    assert p["hold_ms"] == H and p["left_ms"] == 95 * H and p["left_ko"] == "보유 한도까지 95시간"
    assert VW.position_view(VW.snapshot(w["p"]["paper2"], NOW), w["vwap_cfg"], K(6, 11) + 96 * H + MIN)["left_ko"] == "보유 한도 지남 · 다음 1분에 정리"
    # net ROE at the bot's last mark: 30x the move, both sides' costs (livebots._paper_position's own rule)
    with sqlite3.connect(w["p"]["paper2"]) as c:
        mark = json.loads(c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()[0])["engines"][V.ACC]["last_mark"]["BTCUSDT"]
    rt = L.round_trip(0.0005)
    assert p["mark"] == pytest.approx(mark) and p["roe_now"] == pytest.approx(30 * ((mark / raw["entry_price"] - 1) - rt))
    assert p["locked"] is False and p["next_lock"]["lock"] == pytest.approx(0.10) and p["next_lock"]["at"] == pytest.approx(0.12)
    g = p["gates"]
    assert g["vote"]["word"] == "보류" and g["vote"]["with_side"] == 0 and (g["vote"]["up"], g["vote"]["down"], g["vote"]["neutral"]) == (2, 0, 2)
    assert g["vol"]["tf"] == "1h" and g["vol"]["atr_pct"] == 0.33 and g["vol"]["ratio"] == pytest.approx(0.33 / 0.58)
    assert g["text"] == "4시간 보류(상승 2·하락 0·중립 2) · 변동성 1시간 ATR 0.33% (30일 80% 위치 0.58%)"


def test_every_coin_now_and_which_side_a_signal_could_take(w):
    pic = VW.control(w["p"], NOW, _more(w))["picture"]
    assert pic["state"] == "ok" and pic["at"] == V.PIC_AT and pic["age_ms"] == NOW - V.PIC_AT and pic["stale"] is False
    assert pic["tfs"] == ["30m", "1h"] and pic["vote_tf"] == "4h"
    rows = {r["symbol"]: r for r in pic["rows"]}
    assert list(rows) == list(L.COINS)
    side = lambda s, tf: next(x for x in rows[s]["sides"] if x["tf"] == tf)          # noqa: E731
    btc = rows["BTCUSDT"]
    assert btc["vote"]["word"] == "상승" and (btc["vote"]["up"], btc["vote"]["down"], btc["vote"]["neutral"]) == (4, 0, 0)
    assert side("BTCUSDT", "30m")["ko"] == "롱 가능 · 숏 막힘(4시간 상승 4표)" and side("BTCUSDT", "30m")["member_ko"] == "VWAP 복귀 실패 30분"
    assert btc["vol"]["30m"]["high"] is False and btc["vol"]["30m"]["ratio"] == pytest.approx(btc["vol"]["30m"]["atr_pct"] / btc["vol"]["30m"]["q_pct"])
    assert rows["ETHUSDT"]["vol"]["30m"]["high"] is True and rows["ETHUSDT"]["vol"]["1h"]["high"] is False
    assert side("ETHUSDT", "30m")["ko"] == "둘 다 막힘(4시간 하락 4표, 변동성 높음 30분)"
    assert side("ETHUSDT", "1h")["ko"] == "숏 가능 · 롱 막힘(4시간 하락 4표)" and side("ETHUSDT", "1h")["short"]["ok"] is True
    assert side("SOLUSDT", "30m")["ko"] == "롱·숏 둘 다 가능" and rows["SOLUSDT"]["vote"]["word"] == "보류"
    assert rows["DOGEUSDT"]["vote"]["error"].startswith("4시간 추세 판단을 못 읽음(진입 안 함)")
    assert side("DOGEUSDT", "1h")["ko"] == "못 읽음 → 진입 안 함 (4시간 판단 못 읽음)" and side("DOGEUSDT", "1h")["unread"] is True
    assert side("LTCUSDT", "1h")["ko"] == "둘 다 막힘(4시간 하락 4표, 변동성 높음 1시간)" and side("LTCUSDT", "30m")["ko"].startswith("숏 가능")
    assert "error" in rows["BCHUSDT"]["vol"]["30m"] and side("BCHUSDT", "30m")["ko"] == "못 읽음 → 진입 안 함 (30분 변동성 못 읽음)"
    # older than 40 minutes: said so; before the first picture: 아직 그림 없음; a picture the bot could not make: 못 읽음
    assert VW.control(w["p"], V.PIC_AT + 41 * MIN, _more(w))["picture"]["stale"] is True
    snap = VW.snapshot(w["p"]["paper2"], NOW)
    none = VW.picture_view({**snap, "gates_now": (None, None)}, w["vwap_cfg"], NOW)
    assert none["state"] == "none" and none["ko"].startswith("아직 그림 없음")
    bad = VW.picture_view({**snap, "gates_now": (K(6, 11), {"at": K(6, 11, 1), "error": "OSError: down"})}, w["vwap_cfg"], NOW)
    assert bad["state"] == "error" and bad["reason"] == "OSError: down"


def test_the_words_of_the_sides():
    vote_up = {"raw": 1, "up": 3, "down": 0}
    calm, high = {"high": False}, {"high": True}
    assert VW.sides_ko(VW._side_why(vote_up, calm, True, True, "30m", "4h")) == "롱 가능 · 숏 막힘(4시간 상승 3표)"
    assert VW.sides_ko(VW._side_why({"raw": 0, "up": 2, "down": 1}, high, True, True, "30m", "4h")) == "둘 다 막힘(변동성 높음 30분)"
    assert VW.sides_ko(VW._side_why(None, calm, True, True, "1h", "4h")) == "못 읽음 → 진입 안 함 (4시간 판단 못 읽음)"
    assert VW.sides_ko(VW._side_why(vote_up, {"error": "x"}, True, True, "1h", "4h")) == "못 읽음 → 진입 안 함 (1시간 변동성 못 읽음)"
    # the ATR% point not known yet (fewer than half the window): it passes, as the gate does
    assert VW.sides_ko(VW._side_why({"raw": 0, "up": 1, "down": 1}, {"high": False, "q_pct": None}, True, True, "30m", "4h")) == "롱·숏 둘 다 가능"
    assert VW.sides_ko(VW._side_why(vote_up, None, True, False, "30m", "4h")) == "롱 가능 · 숏 막힘(4시간 상승 3표)"   # vol gate off


def test_the_last_48_hours_of_signals(w):
    sg = VW.control(w["p"], NOW, _more(w))["signals"]
    assert sg["from"] == NOW - 48 * H and sg["cut"] is False
    rows = {(r["symbol"], r["t"]): r for r in sg["rows"]}
    assert [r["t"] for r in sg["rows"]] == sorted((r["t"] for r in sg["rows"]), reverse=True)
    assert ("BCHUSDT", K(3, 12)) not in rows and ("SOLUSDT", K(2, 11)) not in rows          # older than 48 h
    f7 = rows[("ETHUSDT", K(6, 11, 30))]
    assert f7["stage"] == "skipped" and f7["why"] == "포지션 있음 (한 번에 하나)" and f7["gates"]["vote"]["with_side"] == 1
    l1 = rows[("SOLUSDT", K(6, 1))]
    assert l1["stage"] == "late" and l1["why"] == "신호를 2분 30초 넘게 늦게 봐서 들어가지 않음 (재시작 뒤 따라잡기 등)"
    e8 = rows[("BTCUSDT", K(6, 11))]
    assert e8["stage"] == "entered" and e8["member_ko"] == "CMO·샌드위치 캔들 1시간" and e8["gates"]["vol"]["atr_pct"] == 0.33
    f6 = rows[("BTCUSDT", K(5, 22, 30))]
    assert f6["stage"] == "filtered" and f6["group"] == "pause" and f6["why"].startswith("나스닥 개장 앞 30분·뒤 30분 진입 안 함") and f6["gates"] is None
    f5 = rows[("BTCUSDT", K(5, 9, 30))]
    assert f5["group"] == "unread" and f5["group_ko"] == "못 읽음" and f5["gates"]["vote"]["word"] == "보류"
    assert sg["counts"] == {"skipped": 1, "entered": 5, "late": 1, "filtered": 2}
    # a bot younger than 48 h: its own signals only, said so
    young = VW.signals_view(VW.snapshot(w["p"]["paper2"], NOW, sig_from=NOW - 48 * H), NOW, K(6, 0))
    assert young["cut"] is True and young["from"] == K(6, 0) and all(r["t"] >= K(6, 0) for r in young["rows"])


def test_the_pauses_by_its_config(w):
    pz = VW.control(w["p"], NOW, _more(w))["pause"]
    assert pz["now"]["paused"] is False
    # Tuesday 12:00 KST: the next pause is the NYSE open of that night (summer time in New York: 22:00 ~ 23:00 KST)
    assert pz["next"]["why"] == "usopen" and pz["next"]["from"] == K(6, 22) and pz["next"]["until"] == K(6, 23)
    sat = VW.control(w["p"], K(3, 12), _more(w))["pause"]["now"]
    assert sat["paused"] is True and sat["why"] == "weekend"


# ================================================================ 성적
def test_the_paper_and_its_coin_flip_twin(w):
    d = VW.perf(w["p"], NOW, _more(w))
    for aid, key in ((V.ACC, "paper"), (V.FLIP, "flip")):
        ts = V.paper_trades(w["p"]["paper2"], aid)
        e, a = _rec(ts), d[key]
        assert (a["n"], a["wins"], a["losses"]) == (e["n"], e["wins"], e["losses"]), key
        assert a["avg_win"] == pytest.approx(e["aw"]) and (a["avg_loss"] == pytest.approx(e["al"]) if e["al"] is not None else a["avg_loss"] is None)
        assert (a["breakeven"] == pytest.approx(e["be"])) if e["be"] is not None else a["breakeven"] is None
        assert (a["pf"] == pytest.approx(e["pf"])) if e["pf"] is not None else a["pf"] is None
        assert a["max_dd"] == pytest.approx(e["dd"]) and a["roe_sum"] == pytest.approx(e["roe_sum"]) and a["pnl"] == pytest.approx(e["pnl"])
        assert a["initial"] == 1000.0 and a["change"] == pytest.approx(a["wallet"] / 1000 - 1) and a["curve"][0] == [ts[0]["entry_time"], 1000.0]
    p, f = d["paper"], d["flip"]
    assert (p["n"], p["wins"], p["losses"]) == (7, 5, 2) and p["breakeven"] == pytest.approx(abs(p["avg_loss"]) / (p["avg_win"] + abs(p["avg_loss"])))
    assert p["open"] is True and p["small"] is True
    k = d["skill"]
    assert k["win_rate_diff"] == pytest.approx(p["win_rate"] - f["win_rate"]) and k["roe_sum_diff"] == pytest.approx(p["roe_sum"] - f["roe_sum"])
    assert k["small"] is True and k["ko"].startswith("실력 vs 운: 진짜 방향이 동전보다 승률 −") and k["ko"].endswith("표본 적음 (30번 미만은 대부분 운)")


def test_the_checklist_counts_the_vwap_era_only(w):
    d = VW.perf(w["p"], NOW, _more(w))
    c = d["checklist"][0]
    assert len(d["checklist"]) == 1 and c["id"] == "mexc" and c["since_ms"] == V.SWITCH and c["goal"] == 50
    # WOO X Pro's live trades: two of the trend bot before the switch (never counted), three VWAP trades after it
    woo = L.read_exec(w["p"]["mexc_db"], NOW)["trades"]
    era = [t for t in woo if t["entry_ts"] >= V.SWITCH]
    assert len(woo) == 5 and len(era) == 3 and c["n"] == 3
    e = _rec([{**t, "equity_after": 100.0} for t in era])
    r = c["record"]
    assert (r["wins"], r["losses"]) == (e["wins"], e["losses"]) == (2, 1) and r["roe_sum"] == pytest.approx(e["roe_sum"])
    assert r["breakeven"] == pytest.approx(e["be"]) and c["breakeven"]["value"] == pytest.approx(e["be"]) and c["breakeven"]["src"] == "live"
    assert c["breakeven"]["paper"] == pytest.approx(d["paper"]["breakeven"]) and c["breakeven"]["ref"] == VW.scale_ref()["breakeven_win"]
    rows = {x["id"]: x for x in c["rows"]}
    assert rows["n"]["state"] == "wait" and rows["n"]["value_ko"] == "3 / 50번" and rows["win80"]["state"] == "wait"
    assert rows["roe"]["state"] == ("ok" if e["roe_sum"] > 0 else "no") == "no"
    assert rows["twin"]["state"] == "no" and "동전" in rows["twin"]["value_ko"]
    assert rows["paper"]["state"] == "info" and rows["paper"]["value_ko"].startswith("결과가 같은 거래 3/3 · 순ROE 차이 평균 ")
    # the stop line is the break-even of its own averages (the lead's correction), not a fixed 71 %
    assert c["stop"]["state"] == "bad" and c["stop"]["value_ko"] == f"승률 66.7% · 본전 승률 {e['be'] * 100:.1f}%" and c["stop"]["small"] is True
    assert "71%" not in json.dumps(c, ensure_ascii=False)
    assert c["scale_ko"].startswith("실거래 50번(약 3주) 동안 승률 80% 이상") and c["honest_ko"].startswith("5년 기록에서 50번 80% 이상 뒤 다음 50번도 평균 손해였어요")
    # 페이퍼와 비슷한가: each era trade against the paper trade it followed (the same coin and side within 5 minutes)
    pv = c["pairs"]
    paper = {(t["symbol"], t["entry_time"]): t for t in V.paper_trades(w["p"]["paper2"])}
    for x in pv["rows"]:
        lt = next(t for t in era if t["key"] == x["key"])
        pt = paper[(lt["symbol"], lt["paper_time"])]
        assert x["diff"] == pytest.approx(lt["roe"] - pt["roe"]) and x["slip"] == pytest.approx(lt["side"] * (pt["entry_price"] - lt["entry_price"]) / pt["entry_price"])
    assert pv["n"] == 3 and pv["same"] == 3 and pv["slip_mean"] == pytest.approx(-0.0003)


def test_the_research_numbers_are_read_now_or_said_written(w, tmp_path, monkeypatch):
    r = VW.perf(w["p"], NOW, _more(w))["research"]
    assert r["pick17"]["n"] == 40 and r["pick17"]["wins"] == 37 and r["pick17"]["win_rate"] == pytest.approx(37 / 40)
    assert "고를 때 본 기간이라 실제보다 좋게" in r["pick17"]["ko"]
    y = r["five_year"]
    assert y["per_trade"]["a"] == -0.00133 and y["months"]["plus"] == 6 and y["breakeven_win"] == pytest.approx(0.7856)
    assert r["paper"]["n"] == 7 and r["live"][0]["id"] == "mexc" and r["live"][0]["n"] == 3
    fake = tmp_path / "scale.json"
    fake.write_text(json.dumps({"trades": 6000, "win_rate": 0.7, "avg_win_roe": 0.1, "avg_loss_roe": -0.4, "breakeven_win": 0.8,
                                "stretches": {"share_80_or_more": 0.2},
                                "thresholds": {"승률 80% 이상": {"next_win": 0.75, "next_roe_per_trade": -0.03, "next_mult_median": 0.4}}}), encoding="utf-8")
    monkeypatch.setattr(VW, "SCALE_FILE", str(fake))
    s = VW.scale_ref()
    assert s["src"] == "research/vwap30/scale.json" and (s["trades"], s["breakeven_win"], s["next_win_80"]) == (6000, 0.8, 0.75)
    monkeypatch.setattr(VW, "SCALE_FILE", str(tmp_path / "gone.json"))
    s = VW.scale_ref()
    assert "적어 둔 값" in s["src"] and s["breakeven_win"] == VW.SCALE_DEFAULT["breakeven_win"]


def test_the_research_notes_dips_and_the_light(w):
    d = VW.perf(w["p"], NOW, _more(w))
    rt = L.round_trip(0.0005)
    worst = {}
    for t in V.paper_trades(w["p"]["paper2"]):
        worst[(t["symbol"], t["entry_time"])] = (t["leverage"] * (t["side"] * (t["mae_price"] / t["entry_price"] - 1) - rt), t["pnl"] > 0,
                                                 t["leverage"] * (t["side"] * (t["mfe_price"] / t["entry_price"] - 1) - rt))
    dp = d["notes"]["dips"]
    wins = [m for m, won, _b in worst.values() if won]
    assert dp["wins"] == len(wins) == 5 and dp["losses"] == 2
    assert [x["n"] for x in dp["dips"]] == [sum(1 for m in wins if m < -0.2), sum(1 for m in wins if m < -0.4)] == [1, 0]
    assert dp["mae_win"] == pytest.approx(sum(wins) / len(wins)) and tuple(dp["ref"]["rows"][0]) == ("17일", 0.31)
    # E4 (BCH, CMO 1h) went about −28 % against before its lock: the trade row says so too
    e4 = next(t for t in d["trades"] if t["symbol"] == "BCHUSDT")
    assert e4["mae"] == pytest.approx(worst[("BCHUSDT", K(5, 10))][0]) and e4["mae"] < -0.2 and e4["mfe"] == pytest.approx(worst[("BCHUSDT", K(5, 10))][2])
    # the exit itself was reached: never a best below the trade's own result, nor a worst above it
    for t in d["trades"]:
        assert t["mfe"] >= t["roe"] - 1e-12 and t["mae"] <= t["roe"] + 1e-12
    x = VW.excursion({"entry_price": 100.0, "leverage": 10, "side": 1, "mae_price": 99.0, "mfe_price": 101.0, "roe": 0.2}, 0.001)
    assert x["mfe"] == pytest.approx(0.2) and x["mae"] == pytest.approx(10 * (-0.01 - 0.001))
    lt = d["notes"]["light"]
    assert lt["rule"] == {"n": 20, "min_win": 0.75} and lt["follow"]["n"] == 7 and lt["hold"]["n"] == 0 and lt["small"] is True
    # the light at every entry from the trades closed before it (the executor's rule: 15 of the last 20)
    ts, eq = [], 1000.0
    for i, won in enumerate([True] * 14 + [False] * 6 + [True, False, True, True, False, True, True, True, True, True]):
        pnl = 10.0 if won else -40.0
        eq += pnl
        ts.append({"id": i, "entry_time": i * 100, "exit_time": i * 100 + 50, "pnl": pnl, "roe": pnl / 400, "equity_after": eq})
    v = VW.light_view(ts, 20, 0.75)
    hold = []
    for i, t in enumerate(ts):
        last = [x["pnl"] > 0 for x in ts[:i]][-20:]
        if len(last) == 20 and sum(last) < 15:
            hold.append(t)
    assert v["hold"]["n"] == len(hold) > 0 and v["follow"]["n"] == len(ts) - len(hold)
    assert v["hold"]["wins"] == sum(1 for t in hold if t["pnl"] > 0)


def test_the_splits(w):
    d = VW.perf(w["p"], NOW, _more(w))
    ts = V.paper_trades(w["p"]["paper2"])
    sp = {x["id"]: {r["ko"]: r for r in x["rows"]} for x in d["splits"]["paper"]}
    assert list(sp) == ["strategy", "coin", "side", "vote", "atr", "session", "exit", "hold"]
    assert sp["strategy"]["VWAP 복귀 실패 30분"]["n"] == 6 and sp["strategy"]["CMO·샌드위치 캔들 1시간"]["n"] == 1
    assert sum(r["n"] for r in sp["coin"].values()) == 7 and sp["coin"]["ETH"]["n"] == 2
    # the 4h vote at the entry with the trade's side (the context's gates): 같은 방향 / 보류
    want = {}
    for t in ts:
        v = t["context"]["gates"]["vote"]
        k = {1: "같은 방향", 0: "보류", -1: "반대 (동전 쌍둥이만)"}[v["raw"] * t["side"]]
        want[k] = want.get(k, 0) + 1
    assert {k: r["n"] for k, r in sp["vote"].items()} == want == {"같은 방향": 5, "보류": 2}
    atr = {}
    for t in ts:
        g = t["context"]["gates"]["vol"]
        x = g["atr_pct"] / g["q_pct"]
        k = "0.6 미만" if x < 0.6 else "0.6~0.8" if x < 0.8 else "0.8~1.0" if x < 1 else "1.0 이상"
        atr[k] = atr.get(k, 0) + 1
    assert {k: r["n"] for k, r in sp["atr"].items()} == atr
    ses = {}
    for t in ts:
        k = C.KO_SESSION[C.kst_session(t["entry_time"])]
        ses[k] = ses.get(k, 0) + 1
    assert {k: r["n"] for k, r in sp["session"].items()} == ses and "새벽(06-09시)" in ses
    assert {k: r["n"] for k, r in sp["exit"].items()} == {"계단 익절": 4, "손절": 2, "보유 한도 청산": 1}
    assert sp["exit"]["보유 한도 청산"]["roe_sum"] == pytest.approx(next(t["roe"] for t in ts if t["exit_reason"] == "TIME"))
    assert sp["hold"]["48시간 넘게"]["n"] == 1 and all(r["small"] for r in sp["coin"].values())
    w8 = sp["strategy"]["VWAP 복귀 실패 30분"]
    assert w8["wins"] == sum(1 for t in ts if t["strategy_id"] == "F6_VWAP_FAIL" and t["pnl"] > 0)
    # the coin-flip twin: the same splits, its side against the vote
    fl = {x["id"]: {r["ko"]: r for r in x["rows"]} for x in d["splits"]["flip"]}
    tw = V.paper_trades(w["p"]["paper2"], V.FLIP)
    assert sum(r["n"] for r in fl["side"].values()) == len(tw) and sum(r["n"] for r in fl["vote"].values()) == len(tw)


def test_the_trades_with_the_executors_part(w):
    d = VW.perf(w["p"], NOW, _more(w))
    rows = {(r["symbol"], r["entry_time"]): r for r in d["trades"]}
    assert len(d["trades"]) == 7 and d["trades"][0]["exit_time"] >= d["trades"][-1]["exit_time"]
    e3 = rows[("LTCUSDT", K(2, 15))]
    assert e3["reason"] == "TIME" and e3["reason_ko"] == "보유 한도 청산" and e3["why"] == "96봉(48시간) 지남" and e3["hold_ms"] == 48 * H
    assert e3["live"]["mexc"] == {"state": "other", "why_ko": "이때 WOO X Pro는 추세판단 봇을 따라갔어요"}
    assert rows[("ETHUSDT", K(5, 23, 30))]["live"]["mexc"]["why_kind"] == "late"
    e4 = rows[("BCHUSDT", K(5, 10))]
    assert e4["live"]["mexc"]["state"] == "matched" and e4["live"]["mexc"]["roe"] > 0 and e4["reason_ko"] == "계단 익절"
    assert e4["gates"]["text"] == "4시간 상승(상승 3·하락 1·중립 0) · 변동성 1시간 ATR 0.55% (30일 80% 위치 0.70%)"
    assert rows[("DOGEUSDT", K(6, 7))]["live"]["mexc"]["roe"] < 0 and rows[("DOGEUSDT", K(6, 7))]["reason_ko"] == "손절"


# ================================================================ 막은 신호
def test_the_blocked_signals_by_reason(w):
    d = VW.blocked(w["p"], NOW, _more(w))
    g = {x["id"]: x for x in d["counts"]["groups"]}
    assert [x["id"] for x in d["counts"]["groups"]] == ["vote", "vol", "pause", "unread", "other"]
    assert (g["vote"]["all"], g["vol"]["all"], g["pause"]["all"], g["unread"]["all"], g["other"]["all"]) == (1, 1, 2, 1, 0)
    assert all(x["today"] == 0 for x in g.values()) and d["counts"]["total"] == {"today": 0, "week": 5, "all": 5}
    assert {k["id"]: k["n"] for k in g["pause"]["kinds"]} == {"weekend": 1, "usopen": 1}
    # the 7 days are today and the six KST days before it
    tomorrow = VW.blocked(w["p"], K(7, 12), _more(w))["counts"]
    assert tomorrow["total"]["week"] == 5 and VW.blocked(w["p"], K(9, 12), _more(w))["counts"]["total"]["week"] == 3   # from 10/24
    rec = d["counts"]["recent"]
    assert [r["t"] for r in rec] == sorted((r["t"] for r in rec), reverse=True) and len(rec) == 5
    f3 = next(r for r in rec if r["symbol"] == "DOGEUSDT")
    assert f3["group"] == "vol" and f3["why"] == "변동성 높음: ATR 0.912% > 지난 30일 80% 위치 0.655%" and f3["gates"]["vol"]["ratio"] == pytest.approx(0.912 / 0.655)
    f2 = next(r for r in rec if r["symbol"] == "SOLUSDT")
    assert f2["group"] == "vote" and f2["gates"]["vote"]["with_side"] == -1 and f2["member_ko"] == "CMO·샌드위치 캔들 1시간"


def test_what_the_gates_cost_or_saved(w):
    v = VW.blocked(w["p"], NOW, _more(w))["virtual"]
    assert v["state"] == "ok" and v["n"] == 7                             # the trend bot's row (paper NULL) is not here
    kinds = {k["id"]: k for k in v["kinds"]}
    assert [k["id"] for k in v["kinds"]] == ["gate_vote", "gate_vol", "gate_unread", "weekend", "usopen", "held", "exec"]
    gv = kinds["gate_vote"]
    assert (gv["n"], gv["closed"], gv["wins"], gv["losses"]) == (1, 1, 1, 0) and gv["roe_sum"] == pytest.approx(0.121)
    assert gv["read_ko"] == "4시간 추세 반대로 막은 신호: 가상 1승 0패 · 순ROE 합 +12.1% → 이번엔 막은 게 이익을 놓쳤어요 · 표본 적음 · 대부분 운"
    assert gv["rows"][0]["gates"]["vote"]["with_side"] == -1 and gv["grp_ko"] == "진입 조건(4시간·변동성)"
    assert kinds["gate_vol"]["read_ko"].endswith("→ 이번엔 막은 게 손해를 줄였어요 · 표본 적음 · 대부분 운")
    assert kinds["gate_unread"]["read_ko"] == "봉을 못 읽어 막은 신호: 끝난 것이 아직 없어요 (진행 중 1)"
    assert kinds["usopen"]["read_ko"] == "나스닥 개장 앞뒤라 쉰 신호: 끝난 것이 아직 없어요 (1분봉 없음 1)"
    ex = kinds["exec"]
    assert ex["paper_result"] is True and ex["read_ko"].startswith("실행기가 안 따라간 페이퍼 거래: 페이퍼 결과 1승 0패")
    assert ex["rows"][0]["executor_ko"] == "WOO X Pro"
    gate = v["gate"]
    assert (gate["n"], gate["closed"], gate["wins"], gate["losses"], gate["open"]) == (3, 2, 1, 1, 1) and gate["roe_sum"] == pytest.approx(0.121 - 0.43)
    assert "표본이 적으면 아무것도 결정하지 않아요" in v["note_ko"]


def test_the_virtual_results_before_the_watchers_new_version(w, tmp_path, monkeypatch):
    old = str(tmp_path / "livecheck.db")
    V.missed_db(old, V.missed_rows(w["plan"], w["vt"]), paper_col=False)
    v = VW.blocked(w["p"], NOW, {**_more(w), "check_db": old})["virtual"]
    assert v == {"state": "pending", "reason_ko": "아직 계산 전 (감시가 새 버전으로 돌아야 생겨요)", "reason": None, "path": old}
    gone = VW.blocked(w["p"], NOW, {**_more(w), "check_db": str(tmp_path / "none.db")})["virtual"]
    assert gone["state"] == "missing" and gone["reason_ko"]
    # the watcher's own livemissed.read_rows(conn, since, limit=None, paper=None) (the contract), asked for 'vwap' rows
    from paperbot import livemissed as LM
    seen = {}
    real = LM.read_rows

    def read_rows(conn, since, limit=None, paper=None):
        seen["paper"] = paper
        return real(conn, since, limit, paper=paper)
    monkeypatch.setattr(LM, "read_rows", read_rows)
    v = VW.blocked(w["p"], NOW, _more(w))["virtual"]
    assert seen["paper"] == "vwap" and v["n"] == 7 and v["kinds"][0]["id"] == "gate_vote"


# ================================================================ the routes, read-only
def test_the_routes_on_the_live_app(w, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from paperbot.livedash import app as LA
    for k, v in V.env_of(w).items():
        monkeypatch.setenv(k, v)
    names = ("paper", "paper2", "bybit_db", "mexc_db")
    before = {k: open(w["p"][k], "rb").read() for k in names}
    check = open(w["more"]["check_db"], "rb").read()
    app = LA.create_app(None, b"s" * 32, candles=lambda *a, **k: [], ticker=lambda: {}, market=lambda: {}, frames=lambda *a: None,
                        liq_db=str(tmp_path / "no-liq.db"), inbox_db=str(tmp_path / "no-inbox.db"))
    assert "livevwap" in app.state.more and app.state.more["livevwap"]["routes"] == ["/api/v4/livebots/vwap", "/api/v4/livebots/vwperf",
                                                                                      "/api/v4/livebots/vwblock"]
    c = TestClient(app)
    for path, key in (("/api/v4/livebots/vwap", "picture"), ("/api/v4/livebots/vwperf", "checklist"), ("/api/v4/livebots/vwblock", "virtual")):
        r = c.get(path)
        assert r.status_code == 200 and r.json()["state"] == "ok" and key in r.json(), path
    assert {k: open(w["p"][k], "rb").read() for k in names} == before and open(w["more"]["check_db"], "rb").read() == check


# ================================================================ the menu, the tabs and the views in node
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
              f"Date.now = () => {NOW};                                   // the world's clock (core/api.js serverNow)\n"
              f"const X = await import('file://{SCREENS}/livebots-vwap.js');\n" + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n"
              "const mkCtx = (a) => ({params: {query: {}}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, href: (n) => '#/' + n,"
              " every() {}, api: async () => JSON.parse(JSON.stringify(a))});\n"
              "const run = async (V, a, hub) => { const v = V(mkCtx(a), hub); await tick(); await tick(); return v; };\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_views_in_node(w, tmp_path):
    ctl, prf, blk = (json_finite(x) for x in _answers(w))
    summ = json_finite(L.build(w["p"], NOW))
    out = _node(tmp_path, """
    const hub = {get: () => D_s};
    const a = texts((await run(X.vwapView, D_c, hub)).el), b = texts((await run(X.vwperfView, D_p)).el), c = texts((await run(X.vwblockView, D_b)).el);
    const find = (n, cls) => (String(n.className || "").split(" ").includes(cls) ? n : n.childNodes.map((k) => find(k, cls)).find(Boolean) || null);
    const shown = (n) => (n.hidden ? "" : n.t != null ? n.t : n.childNodes.map(shown).join(" "));          // the hidden parts left out
    const vo = await run(X.vwapView, D_o, null), po = await run(X.vwperfView, D_o);
    const off = shown(vo.el).replace(/\s+/g, " "), offp = shown(po.el).replace(/\s+/g, " ");
    const offHidden = [find(vo.el, "lvw-cards").hidden, find(vo.el, "lvw-hero").hidden, find(po.el, "lvw-cards").hidden];
    console.log(JSON.stringify({a, b, c, off, offp, offHidden, hero: X.heroOf(D_c, D_c.now_ms), heroStop: X.heroOf({...D_c, bot: {...D_c.bot, running: false}}, D_c.now_ms),
      hold: [X.holdKo(31 * 3600e3 + 20 * 60e3), X.holdKo(45 * 60e3), X.holdKo(null)], left: X.leftKo(D_c.position, D_c.now_ms),
      open: X.openSides(D_c.picture), tones: D_c.picture.rows.map((r) => r.sides.map(X.sideTone)),
      res: [X.resultKo({state: 'closed', win: true, roe: 0.121, reason_ko: '계단 익절'}), X.resultKo({state: 'open', roe: -0.05}), X.resultKo({state: 'no_data', state_ko: '1분봉 없음'})],
      cell: [X.liveCellKo({state: 'matched', roe: 0.1}), X.liveCellKo({state: 'other'}), X.liveCellKo({state: 'missed'}), X.liveCellKo(null)],
      cmp: X.compareRows(D_p.paper, D_p.flip).map((r) => [r[0], r[1], r[2]]), al: X.alignCurves([D_p.paper.curve, D_p.flip.curve]),
      al0: X.alignCurves([[[1, 2]], []]), al1: X.alignCurves([[[1, 10], [3, 12]], [[2, 5]]])}));""",
                c=ctl, p=prf, b=blk, s=summ, o={"now_ms": NOW, "state": "off", "reason_ko": VW.OFF_KO, "other_ko": None})
    a = out["a"]
    for word in ("BTC 롱 보유 중", "CMO·샌드위치 캔들 1시간", "보유 한도까지 95시간", "돌고 있음", "처음 켬 10/23 09:00",
                 "따라감: WOO X Pro (10/26 08:00부터)", "WOO X Pro 실거래 (VWAP)", "페이퍼(연습) 지갑", "진짜 돈 아님", "5승 2패", "표본 적음",
                 "보유 한도 96봉 (1시간봉 · 96시간)", "10/31 11:00에 시장가 정리 (보유 한도 청산)", "진입 때 통과한 조건", "4시간 보류 (상승 2·하락 0·중립 2)",
                 "1시간 ATR 0.33% / 80% 위치 0.58% (0.57배)", "WOO X Pro 같은 포지션", "WOO X Pro 신호등 (VWAP 페이퍼 기준)", "근거 쌓는 중",
                 "지금 코인별", "롱 가능 · 숏 막힘(4시간 상승 4표)", "못 읽음 → 진입 안 함 (4시간 판단 못 읽음)", "높음 → 진입 안 함", "→ 진입 안 함",
                 "진입 쉬는 시간", "나스닥 개장 앞 30분·뒤 30분", "규칙", "보유 한도 96봉(30분 48시간 · 1시간 96시간)", "최근 신호 (48시간)",
                 "진입 5", "막힘 2", "늦음 1", "신호를 2분 30초 넘게 늦게 봐서 들어가지 않음", "막힘 · 주말·발표·나스닥"):
        assert word in a, word
    assert not BAD.search(a), BAD.search(a)
    b = out["b"]
    for word in ("페이퍼 vs 동전 쌍둥이", "본전 승률 (이 평균으로)", "77.7%", "손익비 (PF)", "가장 깊은 낙폭", "실력 vs 운", "키우기 · 멈추기",
                 "3 / 50번", "본전 승률 (멈추기 선)", "실거래 평균 익절·손절로 계산", "5년 기록 78.6% (참고)", "본전 아래", "순ROE 합 플러스",
                 "페이퍼가 동전 쌍둥이보다 나음", "페이퍼와 비슷한가", "결과가 같은 거래 3/3", "5년 기록에서 50번 80% 이상 뒤 다음 50번도 평균 손해였어요",
                 "연구 노트", "물림 (진입 뒤 가장 깊이 밀린 순ROE)", "먼저 −20% 넘게 물린 거래 1번 (20%)", "신호등 시험 (최근 20번 중 75% 이상일 때만 따라감)",
                 "따라갔을 거래 7번", "걸렀을 거래 없음", "물림 −",
                 "연구 숫자와 나란히", "17일 연구 (고른 기간)", "37승 3패 · 92.5%", "5년 페이퍼 (같은 규칙)", "5,805번", "72.0%", "WOO X Pro 실거래 (VWAP 뒤)",
                 "−0.133%", "79개월 중 플러스 6달", "나눠 보기", "VWAP 복귀 실패 30분", "보유 한도 청산", "96봉(48시간) 지남", "WOO X Pro: 다른 페이퍼",
                 "안 따라감", "페이퍼 진입을 늦게 봐서 건너뛰었어요"):
        assert word in b, word
    assert not BAD.search(b), BAD.search(b)
    c = out["c"]
    for word in ("막은 신호 수", "4시간 추세 반대", "변동성 높음", "주말·발표·나스닥", "못 읽음", "기타", "합계", "나스닥 개장 앞뒤 1 · 주말 진입 안 함 1",
                 "막지 않았다면", "진입 조건(4시간·변동성)이 막은 신호:", "4시간 추세 반대로 막은 신호: 가상 1승 0패", "✅ +12.1% 계단 익절", "❌ −43.0% 손절",
                 "진행 중 −5.0%", "1분봉 없음", "페이퍼 결과 (가상 아님)", "WOO X Pro", "표본이 적으면 아무것도 결정하지 않아요", "최근 막은 신호",
                 "변동성 높음: ATR 0.912% > 지난 30일 80% 위치 0.655%", "30분 ATR 0.91% / 80% 위치 0.66% (1.39배)"):
        assert word in c, word
    assert not BAD.search(c), BAD.search(c)
    for t in (out["off"], out["offp"]):                                  # what is shown: the off box, the note (the cards are hidden)
        assert "꺼짐" in t and VW.OFF_KO in t and "5장 B" in t and "보유" not in t and "실력" not in t and not BAD.search(t)
    assert out["offHidden"] == [True, True, True]
    assert out["hero"]["cls"] == "hold" and out["hero"]["head"] == "BTC 롱 보유 중" and out["heroStop"]["cls"] == "stop"
    assert "systemctl status paperbot-combo-vwap" in out["heroStop"]["sub"]
    assert out["hold"] == ["31시간 20분", "45분", "—"] and out["left"] == "보유 한도까지 95시간"
    assert "BTC 30분 롱" in out["open"] and "SOL 30분 롱·숏" in out["open"] and not any(x.startswith("DOGE") for x in out["open"])
    assert out["tones"][0] == ["long", "long"] and out["tones"][3] == ["unread", "unread"] and out["tones"][2] == ["both", "both"]
    assert out["res"] == ["✅ +12.1% 계단 익절", "진행 중 −5.0%", "1분봉 없음"]
    assert [x["ko"] for x in out["cell"]] == ["+10.0%", "다른 페이퍼", "안 따라감", "—"]
    cmp = {r[0]: r[1:] for r in out["cmp"]}
    assert cmp["닫힌 거래"] == ["7번", "3번"] and cmp["본전 승률 (이 평균으로)"][1] == "아직 모름" and cmp["손익비 (PF)"][1] == "손실 없음"
    # the two curves on every close of either account, each holding its last equity (null before its own first point)
    assert out["al0"] is None and out["al1"] == {"t": [1, 2, 3], "series": [[10, 10, 12], [None, 5, 5]]}
    al = out["al"]
    assert al["t"] == sorted({t for t, _e in prf["paper"]["curve"] + prf["flip"]["curve"]})
    assert al["series"][0][-1] == pytest.approx(prf["paper"]["curve"][-1][1]) and al["series"][1][-1] == pytest.approx(prf["flip"]["curve"][-1][1])


def test_the_menu_group_and_the_tabs():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    v4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
    script = ("globalThis.document = {documentElement: {dataset: {site: 'live'}}};\n"
              f"const R = await import('file://{v4}/core/routes.js');\n"
              "console.log(JSON.stringify({groups: R.GROUPS.map((g) => [g.id, g.ko, g.screens]), keys: R.KEYS, nav: R.navGroups(true).map((g) => g.ko),"
              " screens: ['vwap', 'vwperf', 'vwblock'].map((k) => [R.SCREENS[k].ko, R.SCREENS[k].group, R.SCREENS[k].mod]),"
              " parse: R.parseHash('#/livebots/vwperf'), href: R.href('livebots', 'vwblock')}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout.strip().splitlines()[-1])
    assert d["groups"][-1] == ["vwap", "VWAP 봇", ["vwap", "vwperf", "vwblock"]] and d["nav"][-1] == "VWAP 봇" and len(d["groups"]) == 5
    assert d["keys"] == ["trend", "tchart", "hq", "pos", "summary", "chart", "risk", "health", "journal"]       # the four groups' keys stay
    assert d["screens"] == [["VWAP 관제", "vwap", "livebots"], ["VWAP 성적", "vwap", "livebots"], ["VWAP 막은 신호", "vwap", "livebots"]]
    assert d["parse"]["name"] == "vwperf" and d["href"] == "#/vwblock"
    lb = FW._read(SCREENS, "livebots.js")
    for t, label in (("vwap", "VWAP 관제"), ("vwperf", "VWAP 성적"), ("vwblock", "VWAP 막은 신호")):
        assert f'{{id: "{t}", label: "{label}"' in lb
    assert 'import {vwapView, vwperfView, vwblockView} from "./livebots-vwap.js";' in lb


def test_the_files_keep_the_house_rules():
    FW.house_rules("livebots-vwap", "lvw")
    js = FW._read(SCREENS, "livebots-vwap.js")
    for api in ('"/api/v4/livebots/vwap"', '"/api/v4/livebots/vwperf"', '"/api/v4/livebots/vwblock"'):
        assert api in js
    # its css comes with the other tabs' (screens/livebots.css @imports it)
    assert '@import url("livebots-vwap.css");' in FW._read(SCREENS, "livebots.css")
    assert re.search(r"^MODULES = MODULES \+ \(\"livevwap\",\)$", FW._read(ROOT, "paperbot", "livedash", "app.py"), re.M)
