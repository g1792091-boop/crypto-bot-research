"""실거래 › 믹스 봇 (dash/more/livemix.py; screens/livebots-mix.js), owners 10-25 night: the '믹스 30분 봇' on the second
WOO X Pro account (real money) and its paper twin (docs/mixchop-ko.md), on a world made by the bot's own code
(tests/mix_site_world.py: mixchop.Bot over the deploy configs, the live one on the fake WOO X Pro account of
tests/test_mixchop.py, the paper one with the service's paper_equity save):

- which files (the environment, else the config's own state / log paths; the repo's deploy config when the server's is
  missing or unreadable, said so); 꺼짐 before either bot ran (and how to start it), 멈춤 after 35 minutes without a
  record (the systemd unit to look at), 못 읽음 for an unreadable state file (its position unknown, never "none");
- 관제: the equity now (live: the last one the bot logged; paper: paper_equity), the start equity and the 70 % floor, the
  stop files and the floor now, the last halt the log shows, the entry block now and the next window (mixchop.entry_block
  on the world's calendar: weekend, the Nasdaq open on both sides of the summer-time change, a release next to the open
  merged into one window), the open position with the next ladder step (mixchop.ladder_stop), the last 48 hours: each
  colour change with what became of it, the warnings folded with their count;
- 성적: the trades (exit rows joined to their entries; P&L the equity change, paper with both fees; an unread P&L stays
  모름), the record and the coins, the design's 5-year backtest labelled as such, the rules (a coin its last start turned
  off said so);
- the log's tail (cut, half-written last line, bad lines, parsed once per change); the routes on the live app (read-only);
  the menu, the tabs and the views in node; the house rules of the css."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paperbot import events as EV  # noqa: E402
from paperbot import mixchop as M  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livemix as X  # noqa: E402
from tests import mix_site_world as W  # noqa: E402
from tests import test_dash_livebots_fees as FW  # noqa: E402

NOW, K, MIN, H, DAY = W.NOW, W.K, W.MIN, W.H, W.DAY
ROOT = FW.ROOT
SCREENS = FW.SCREENS
DOM = FW.DOM
BAD = FW.BAD


@pytest.fixture(scope="module")
def w(tmp_path_factory):
    return W.build(str(tmp_path_factory.mktemp("mix") / "w"))


@pytest.fixture(autouse=True)
def _fresh(w, monkeypatch):
    """Every answer on the world's own calendar; no cache across tests."""
    monkeypatch.setattr(EV, "PATH", w["calendar"])
    EV.reset()
    L._cache.clear()
    X._tails.clear()
    yield
    EV.reset()
    L._cache.clear()
    X._tails.clear()


def _p(w_or_folder) -> dict:
    folder = w_or_folder["folder"] if isinstance(w_or_folder, dict) else str(w_or_folder)
    return X.paths(W.env_of(folder))


def _bots(d: dict) -> dict:
    return {b["id"]: b for b in d["bots"]}


def _copy(w, tmp_path, name: str) -> str:
    """The world's files in a folder of their own (a test that changes them)."""
    dst = str(tmp_path / name)
    shutil.copytree(w["folder"], dst)
    for tag in ("live", "paper"):                                    # the configs name the world's folder: point them here
        path = os.path.join(dst, f"{tag}.json")
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        for k in ("state", "log", "kill_file", "own_stop_file"):
            raw[k] = raw[k].replace(w["folder"], dst)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh)
    return dst


# ================================================================ which files, and in what state
def test_off_before_either_bot_ran(tmp_path):
    p = _p(tmp_path)
    c, f = X.control(p, NOW), X.perf(p, NOW)
    for d in (c, f):
        for bid, b in _bots(d).items():
            assert b["status"]["state"] == "off" and b["status"]["ko"] == X.OFF_KO[bid]
            assert "equity" not in b and "position" not in b and "record" not in b and "trades" not in b    # nothing made up
            assert b["start_ko"].endswith(f"sudo systemctl start {b['unit']}") and "docs/mixchop-ko.md 5장" in b["start_ko"]
            assert b["files"]["config"]["source"] == "repo" and "서버 설정 파일이 아직 없어요" in b["files"]["config"]["reason_ko"]
    assert [b["unit"] for b in c["bots"]] == ["paperbot-mixchop", "paperbot-mixchop-paper"] and _bots(c)["live"]["real"] is True
    assert _bots(f)["live"]["rules"]["source"] == "repo" and _bots(f)["live"]["rules"]["mode"] == "mainnet"     # the deploy file
    assert X.paths({})["live"]["config"] == "/etc/paperbot/mixchop.json" and X.paths({})["paper"]["config"] == "/etc/paperbot/mixchop-paper.json"


def test_running_stopped_and_where_the_files_are(w, tmp_path):
    c = _bots(X.control(_p(w), NOW))
    for bid in ("live", "paper"):
        s = c[bid]["status"]
        assert s["state"] == "running" and s["saved_ms"] == K(27, 12, 0, 5) and s["age_ms"] == NOW - K(27, 12, 0, 5)
        assert s["last_close_ms"] == K(27, 12) and s["seen_from"] == "saved_ms"
    assert c["live"]["status"]["started_ms"] == K(26, 12) and c["live"]["status"]["mode"] == "mainnet"
    # 35 minutes without a record: 멈춤, with the unit to look at
    late = _bots(X.control(_p(w), K(27, 12, 0, 5) + 35 * MIN + 1))
    assert late["live"]["status"]["state"] == "stopped" and late["live"]["status"]["ko"] == X.STOPPED_KO
    assert late["paper"]["status"]["unit"] == "paperbot-mixchop-paper"
    # the state and log paths follow the server config when their variables are not set
    env = {"PAPERBOT_MIX_CONFIG": os.path.join(w["folder"], "live.json")}
    b = _bots(X.control(X.paths(env), NOW))["live"]
    assert b["status"]["state"] == "running" and b["files"]["state"]["path"] == os.path.join(w["folder"], "live-state.json")
    assert b["position"]["symbol"] == "BCHUSDT"
    # the repo's config names the guide's paths
    nobody = X.paths({"PAPERBOT_MIX_CONFIG": str(tmp_path / "none.json")})
    assert X.files_of("live", nobody["live"], X.read_config(nobody["live"]["config"], nobody["live"]["repo_config"])) == X.DEFAULT_FILES["live"]


def test_an_unreadable_state_file_says_so(w, tmp_path):
    d = _copy(w, tmp_path, "bad")
    with open(os.path.join(d, "live-state.json"), "w", encoding="utf-8") as fh:
        fh.write('{"position": {"symbol": "BCH')                     # never a half file from the bot, but said if it is
    os.remove(os.path.join(d, "paper-state.json"))
    c = _bots(X.control(_p(d), NOW))
    lv = c["live"]
    assert lv["status"]["state"] == "error" and lv["status"]["reason_ko"] == "상태 파일 내용이 JSON이 아니에요"
    assert lv["position"]["state"] == "error" and "몰라요" in lv["position"]["ko"]                 # unknown, never "no position"
    assert lv["equity"]["now"]["value"] == pytest.approx(49.95) and lv["feed"]["n"] > 0             # the log still read
    pp = c["paper"]
    # no state file: the log's last row tells (the paper's last one is its 10/26 exit: 멈춤), the position unknown
    assert pp["status"]["state"] == "stopped" and pp["status"]["seen_from"] == "log" and pp["status"]["seen_ms"] == K(26, 11, 30, 5)
    assert pp["position"]["state"] == "missing" and pp["position"]["ko"] == "상태 파일이 없어 포지션을 몰라요"
    assert pp["equity"]["now"]["from"] == "exit"                                                    # no paper_equity: the log's


# ================================================================ 관제
def test_equity_floor_and_what_stops_entries(w, tmp_path):
    c = _bots(X.control(_p(w), NOW))
    e = c["live"]["equity"]
    # the live equity is the newest one the bot logged: BCH's entry (49.95, after the transfer seen at the restart)
    assert e["now"] == {"value": 49.95, "ms": K(27, 9, 0, 5), "from": "entry", "from_ko": "진입 때 읽은 잔고"}
    assert (e["start"], e["floor_frac"], e["floor"], e["below"]) == (50.0, 0.7, 35.0, False) and e["room"] == pytest.approx(14.95)
    assert e["real"] is True and e["change"] == pytest.approx(49.95 / 50 - 1)
    pe = c["paper"]["equity"]
    assert pe["now"]["from"] == "state" and pe["now"]["value"] == pytest.approx(w["paper"]["broker"].equity()) and pe["real"] is False
    h = c["live"]["halts"]
    assert h["items"] == [] and h["halted"] is False
    assert h["last"]["why"].startswith("정지 파일(") and h["last"]["ms"] == K(26, 10, 30, 5) and h["last"]["entry_after"] is True
    # the stop files now (the bot's halts(): the shared kill file, its own), and the floor
    d = _copy(w, tmp_path, "halt")
    open(os.path.join(d, "STOP"), "w").close()
    open(os.path.join(d, "live.STOP"), "w").close()
    st = json.load(open(os.path.join(d, "live-state.json"), encoding="utf-8"))
    st["start_equity"] = 80.0                                                       # 49.95 < 70 % of 80
    json.dump(st, open(os.path.join(d, "live-state.json"), "w", encoding="utf-8"))
    hh = _bots(X.control(_p(d), NOW))["live"]["halts"]
    assert [x["kind"] for x in hh["items"]] == ["kill", "own", "floor"] and hh["halted"] is True and all(x["sure"] for x in hh["items"])
    assert "다른 실행기들은 이 파일에 전부 청산해요" in hh["items"][0]["ko"] and hh["items"][1]["path"] == os.path.join(d, "live.STOP")
    assert hh["items"][2]["ko"] == "잔고가 시작 잔고의 70% 아래 (새 진입 멈춤)"
    assert _bots(X.control(_p(d), NOW))["paper"]["halts"]["items"][0]["kind"] == "kill"           # the shared file stops both


def test_entry_blocks_now_and_the_next_window(w):
    cfg = M.load_config(os.path.join(w["folder"], "live.json"))
    b = X.blocks_view(cfg, NOW)
    assert b["state"] == "ok" and [r["on"] for r in b["rules"]] == [True, True, True]
    assert b["now"] == {"blocked": False, "why": None, "kind": None, "until": None, "ko": "지금 진입 가능 (진입 금지 시간 아님)"}
    # Tuesday: the Nasdaq open on summer time (09:30 New York = 22:30 KST): 22:00 ~ 23:00 KST
    assert (b["next"]["kind"], b["next"]["from"], b["next"]["until"]) == ("usopen", K(27, 22), K(27, 23)) and b["next"]["ko"] == "나스닥 개장 앞뒤"
    assert M.entry_block(cfg, K(27, 22) + X.JUDGE_LAG_MS) and not M.entry_block(cfg, K(27, 21, 59) + X.JUDGE_LAG_MS)
    inside = X.blocks_view(cfg, K(27, 22, 15))
    assert inside["now"]["blocked"] is True and inside["now"]["kind"] == "usopen" and inside["now"]["until"] == K(27, 23)
    assert inside["next"]["from"] == K(28, 22)                                      # the next evening (FOMC 03:00 KST is later)
    # Thursday: PCE 21:30 KST (±30 minutes) runs into the Nasdaq window: one block 21:00 ~ 23:00
    thu = X.blocks_view(cfg, K(29, 12))["next"]
    assert (thu["kind"], thu["from"], thu["until"]) == ("macro", K(29, 21), K(29, 23)) and thu["why"].startswith("경제 발표 앞뒤 30분 진입 안 함: PCE")
    # Saturday: the weekend until Monday 00:00 KST; then Monday's open on winter time (New York left summer time 11-01)
    sat = X.blocks_view(cfg, K(31, 12))
    assert sat["now"]["kind"] == "weekend" and sat["now"]["until"] == K(33)
    assert (sat["next"]["from"], sat["next"]["until"]) == (K(33, 23), K(34))
    cfg.no_weekend, cfg.us_open_pre_min, cfg.us_open_pause_min, cfg.macro_blackout_min = False, 0, 0, 0
    off = X.blocks_view(cfg, K(31, 12))
    assert off["any"] is False and off["now"]["blocked"] is False and "규칙이 꺼져 있어요" in off["now"]["ko"] and off["next"] is None
    assert X.blocks_view(None, NOW)["state"] == "error"


def test_the_open_position_and_its_next_ladder_step(w):
    c = _bots(X.control(_p(w), NOW))
    p = c["live"]["position"]
    raw = M.read_state(os.path.join(w["folder"], "live-state.json"))["position"]
    assert (p["symbol"], p["coin"], p["side"], p["leverage"], p["step"]) == ("BCHUSDT", "BCH", 1, 40, 1) and p["locked"] is True
    assert p["entry"] == raw["entry"] == 100.0 and p["qty"] == raw["qty"] == 0.12
    assert p["notional"] == pytest.approx(12.0) and p["margin"] == pytest.approx(0.3)
    # the stop at ROE +10 % (the first lock), the best price 103.8 (ROE +152 %), the stop-out's money at the stop
    assert p["stop"] == raw["stop"] == pytest.approx(100.25) and p["stop_roe"] == pytest.approx(0.10) and p["stop_pnl"] == pytest.approx(0.03)
    assert p["best"] == 103.8 and p["best_roe"] == pytest.approx(1.52) and p["held_ms"] == NOW - K(27, 9, 0, 5)
    assert p["first_act_price"] == pytest.approx(103.75) and p["first_lock_price"] == pytest.approx(100.25)
    assert p["roe_act"] == pytest.approx(1.5) and p["lock_roe"] == pytest.approx(0.1)          # fractions, like every ROE here
    # the next step: ROE 150 + 140 = 290 % (107.25) moves the stop to ROE +150 % (103.75), as mixchop.ladder_stop does
    nx = p["next"]
    assert (nx["step"], nx["reached"]) == (2, False) and nx["trigger"] == pytest.approx(107.25) and nx["trigger_roe"] == pytest.approx(2.9)
    assert nx["stop_to"] == pytest.approx(103.75) and nx["stop_to_roe"] == pytest.approx(1.5)
    assert M.ladder_stop(1, 100.0, 107.26, 100.25, 150.0, 40) == (pytest.approx(103.75), 2)
    assert M.ladder_stop(1, 100.0, 107.2, 100.25, 150.0, 40) == (100.25, -1)
    assert p["stop_id"] and p["stop_id_missing"] is False and c["paper"]["position"] is None
    # a short before its first lock (XRP: ladder from ROE 200 %): the trigger below the entry; already reached: said so
    short = {**raw, "symbol": "XRPUSDT", "side": -1, "entry": 2.0, "stop": 2.02, "best": 1.899, "step": 0, "roe_act": 200.0, "stop_id": None}
    q = X.position_view("live", {"position": short}, NOW)
    assert q["next"]["trigger"] == pytest.approx(1.9) and q["next"]["stop_to"] == pytest.approx(1.995) and q["next"]["reached"] is True
    assert q["stop_roe"] == pytest.approx(-0.4) and q["stop_pnl"] == pytest.approx(-0.0024) and q["stop_id_missing"] is True
    assert X.position_view("live", {"position": {"symbol": "X"}}, NOW)["state"] == "error"          # a position it cannot read


def test_the_last_48_hours(w):
    f = _bots(X.control(_p(w), NOW))["live"]["feed"]
    rows = f["rows"]
    assert f["from"] == NOW - 48 * H and all(r["t"] >= NOW - 48 * H for r in rows) and [r["t"] for r in rows] == sorted((r["t"] for r in rows), reverse=True)
    assert f["counts"] == {"signal": 11, "entered": 3, "skipped": 6, "refused": 2, "waiting": 0, "warn": 4, "exit": 2, "ladder": 2}
    sig = {(r["symbol"], r["t"]): r for r in rows if r["cat"] == "signal"}
    sol = sig[("SOLUSDT", K(26, 9, 0, 5))]
    assert sol["stage"] == "entered" and sol["outcome"]["entry"] == 100.0 and sol["outcome"]["stop"] == 99.0 and sol["colour_ko"] == "하늘색으로 바뀜"
    assert sol["vals"]["avg_rsi_30m"] == 60.0 and sol["vals"]["stop_pct"] == 1.0
    assert sig[("XRPUSDT", K(26, 9, 0, 5))]["outcome"]["group"] == "same_bar" and sig[("XRPUSDT", K(26, 9, 0, 5))]["outcome"]["why"] == "같은 봉에 SOL 먼저"
    assert sig[("BCHUSDT", K(26, 9, 30, 5))]["outcome"]["group_ko"] == "보유 중"
    halt = sig[("DOGEUSDT", K(26, 10, 30, 5))]["outcome"]
    assert halt["group"] == "halt" and halt["tone"] == "bad" and halt["why"].startswith("정지 파일(")
    nasdaq = sig[("SOLUSDT", K(26, 22, 0, 5))]["outcome"]
    assert nasdaq["group"] == "block" and nasdaq["why"] == "나스닥 개장 앞 30분·뒤 30분 진입 안 함 (뉴욕 09:30 개장)"
    assert sig[("ETHUSDT", K(25, 14, 0, 5))]["outcome"]["why"] == "주말(한국 시간 토·일) 진입 안 함"
    refused = sig[("DOGEUSDT", K(27, 9, 30, 5))]
    assert refused["stage"] == "refused" and refused["why"] == "30분 평균 RSI 조건 안 맞음" and refused["want"] == -1
    assert ("SOLUSDT", K(24, 10, 30, 5)) not in sig                                                # older than 48 h
    assert not any(r["cat"] in ("skip", "entry") for r in rows)                                     # every one folded into its signal
    # the warnings: three read failures in one row, the stop placed again
    warn = [r for r in rows if r["cat"] == "warn"]
    assert [(r["kind"], r["n"]) for r in warn] == [("stop_replaced", 1), ("read_failed", 3)]
    assert warn[1]["first_ms"] == K(27, 10) and warn[1]["t"] == K(27, 10, 0, 2) and warn[1]["error"] == "timeout" and warn[0]["where"] == "점검 중"
    ex = [r for r in rows if r["cat"] == "exit"]
    assert [(r["symbol"], r["why_ko"]) for r in ex] == [("XRPUSDT", "손절"), ("SOLUSDT", "계단 익절")] and ex[0]["price"] is None
    assert ex[0]["pnl"] == pytest.approx(-0.13) and ex[1]["pnl"] == pytest.approx(0.02) and ex[0]["tone"] == "bad"
    start = next(r for r in rows if r["cat"] == "start")
    assert start["t"] == K(26, 12) and start["setup_bad"] == ["ZECUSDT: 레버리지를 못 맞춤 (leverage 20 not allowed)"]
    assert _bots(X.control(_p(w), NOW))["live"]["setup_bad"] == start["setup_bad"]
    assert next(c for c in _bots(X.control(_p(w), NOW))["live"]["coins"] if c["symbol"] == "ZECUSDT")["enabled"] is False
    pf = _bots(X.control(_p(w), NOW))["paper"]["feed"]
    assert pf["counts"]["entered"] == 2 and pf["counts"]["warn"] == 0 and pf["bad"] == 0


def test_a_warning_never_overflows_the_feed(tmp_path):
    rows = [{"ts": NOW - i * 15_000, "kind": "poll_failed", "error": "HTTP 502"} for i in range(500)]
    rows += [{"ts": NOW - 10 * MIN, "kind": "stop_failed", "symbol": "SOLUSDT", "error": "refused", "where": "entry"}]
    f = X.feed_view(sorted(rows, key=lambda r: r["ts"]), NOW)
    assert len(f["rows"]) == 2 and f["rows"][0]["n"] == 500 and f["bad"] == 1 and f["counts"]["warn"] == 501
    assert f["rows"][1]["tone"] == "bad" and f["rows"][1]["ko"] == "손절 주문을 걸지 못했어요"


# ================================================================ 성적
def _expect(log: str) -> list:
    """The trades the page must show, from the bot's own rows (independent of the module): exit joined to entry."""
    rows = W.rows(log)
    ent = {(r["symbol"], r["opened_ms"]): r for r in rows if r["kind"] == "entry"}
    out = []
    for r in rows:
        if r["kind"] == "exit":
            e = ent[(r["symbol"], r["opened_ms"])]
            out.append({"symbol": r["symbol"], "pnl": r["equity"] - e["equity_before"], "row_pnl": r["pnl"], "step": r["step"], "why": r["why"],
                        "exit_ms": r["ts"], "opened_ms": r["opened_ms"], "qty": e["qty"]})
    return out[::-1]


def test_the_trades_and_the_record(w):
    d = _bots(X.perf(_p(w), NOW))
    for bid in ("live", "paper"):
        b, e = d[bid], _expect(os.path.join(w["folder"], f"{bid}-log.jsonl"))
        assert [(t["symbol"], t["why"], t["step"], t["exit_ms"], t["opened_ms"]) for t in b["trades"]] == \
            [(x["symbol"], x["why"], x["step"], x["exit_ms"], x["opened_ms"]) for x in e]
        for t, x in zip(b["trades"], e):
            assert t["pnl"] == pytest.approx(x["pnl"]) and t["pnl_src"] == "equity" and t["qty"] == pytest.approx(x["qty"])
        r = b["record"]
        assert (r["n"], r["wins"], r["losses"], r["unknown"], r["ladder_n"]) == (2, 1, 1, 0, 1) and r["win_rate"] == 0.5 and r["small"] is True
        assert r["pnl"] == pytest.approx(sum(x["pnl"] for x in e)) and r["worst"] == pytest.approx(min(x["pnl"] for x in e))
        assert r["avg_win"] == pytest.approx(max(x["pnl"] for x in e)) and r["avg_loss"] == pytest.approx(min(x["pnl"] for x in e))
        coins = {c["symbol"]: c for c in b["coins"]}
        assert list(coins) == [c.symbol for c in M.load_config(os.path.join(w["folder"], f"{bid}.json")).coins]
        assert (coins["SOLUSDT"]["n"], coins["SOLUSDT"]["wins"], coins["XRPUSDT"]["losses"], coins["ETHUSDT"]["n"]) == (1, 1, 1, 0)
        assert coins["ETHUSDT"]["pnl"] is None and coins["SOLUSDT"]["small"] is True                 # no trade: no zero
    lv, pp = d["live"]["trades"], d["paper"]["trades"]
    # live: no exit price in the bot's record (WOO X Pro's fill is not read back); ROE = P&L over the margin
    assert lv[0]["exit"] is None and lv[0]["why_ko"] == "손절" and lv[0]["roe"] == pytest.approx(-0.13 / (6.25 * 2.0 / 40))
    assert lv[1]["why_ko"] == "계단 익절" and lv[1]["signal"]["avg_rsi_1h"] == 55.0 and lv[0]["hold_ms"] == K(26, 11, 20) - K(26, 11, 0, 5)
    assert lv[0]["r"] == pytest.approx(-0.13 / (50.02 * 0.0025))
    # paper: the exit price, and the P&L with both fees (the exit row's own pnl leaves the entry fee out)
    sol = pp[1]
    assert sol["exit"] == 100.25 and sol["roe"] == pytest.approx(0.10)
    row = next(x for x in _expect(os.path.join(w["folder"], "paper-log.jsonl")) if x["symbol"] == "SOLUSDT")
    assert sol["pnl"] == pytest.approx(row["row_pnl"] - 0.125 * 100 * 0.00042) and sol["pnl"] < row["row_pnl"]


def test_an_unread_pnl_stays_unknown():
    rows = [{"ts": 1, "kind": "entry", "symbol": "SOLUSDT", "side": 1, "qty": 0.1, "entry": 100.0, "opened_ms": 1, "equity_before": 50.0, "leverage": 40},
            {"ts": 9, "kind": "exit", "symbol": "SOLUSDT", "side": 1, "why": "stop", "price": None, "pnl": None, "equity": None, "step": 0,
             "entry": 100.0, "stop": 99.0, "opened_ms": 1},
            {"ts": 20, "kind": "exit", "symbol": "ETHUSDT", "side": -1, "why": "manual", "price": None, "pnl": 0.5, "equity": None, "step": 0,
             "entry": 2000.0, "stop": 2010.0, "opened_ms": 12}]
    ts = X.trades_of(rows, None)
    assert ts[1]["pnl"] is None and ts[1]["win"] is None and ts[1]["roe"] is None and ts[1]["pnl_src"] is None
    assert ts[0]["no_entry_row"] is True and ts[0]["pnl"] == 0.5 and ts[0]["pnl_src"] == "row" and ts[0]["why_ko"] == "직접 청산"
    r = X.record(ts)
    assert (r["n"], r["known"], r["unknown"], r["wins"], r["losses"]) == (2, 1, 1, 1, 0) and r["pnl"] == 0.5 and r["win_rate"] == 1.0
    assert X.record([])["pnl"] is None and X.record([])["win_rate"] is None


def test_the_backtest_and_the_rules(w, tmp_path):
    d = X.perf(_p(w), NOW)
    bt = d["backtest"]
    assert [(r["symbol"], r["month"], r["win"]) for r in bt["rows"]] == [
        ("SOLUSDT", 0.0117, 0.32), ("ETHUSDT", 0.0094, 0.19), ("XRPUSDT", 0.0089, 0.20), ("BCHUSDT", 0.0070, 0.31),
        ("ZECUSDT", 0.0047, 0.37), ("DOGEUSDT", 0.0037, 0.40)]
    assert "실거래 아님" in bt["ko"] and bt["risk_pct"] == 0.25 and "60개월 중 20~30개월은 마이너스였어요" in bt["notes_ko"]
    r = _bots(d)["live"]["rules"]
    assert (r["source"], r["mode"], r["risk_pct"], r["equity_floor_frac"], r["max_notional_usd"], r["one_position"]) == ("server", "mainnet", 0.25, 0.7, 500.0, True)
    coins = {c["coin"]: c for c in r["coins"]}
    assert list(coins) == ["SOL", "ETH", "XRP", "BCH", "ZEC", "DOGE"] and coins["ZEC"]["leverage"] == 20 and coins["ZEC"]["roe_act"] == 1.0
    assert coins["ZEC"]["off_at_start"] is True and coins["SOL"]["off_at_start"] is False and coins["ETH"]["h1_buf"] == 8.5
    assert [b["on"] for b in r["blocks"]] == [True, True, True] and _bots(d)["paper"]["rules"]["start_equity"] == 50.0
    # a server config the bot itself would refuse: the repo's, said so
    dd = _copy(w, tmp_path, "cfg")
    with open(os.path.join(dd, "live.json"), "w", encoding="utf-8") as fh:
        json.dump({"mode": "live", "coins": {}}, fh)
    rr = _bots(X.perf(_p(dd), NOW))["live"]
    assert rr["rules"]["source"] == "repo" and rr["files"]["config"]["server_state"] == "error"
    assert rr["rules"]["reason_ko"].startswith("서버 설정 파일을 읽지 못했어요: \"mode\"는") and rr["rules"]["reason_ko"].endswith("저장소 기본 설정으로 보여 줘요")


# ================================================================ the log's tail
def test_the_log_tail_is_read_once_per_change(tmp_path):
    log = tmp_path / "log.jsonl"
    lines = [json.dumps({"ts": i, "kind": "signal", "symbol": "SOLUSDT", "side": 0, "why": "x" * 50}) for i in range(400)]
    log.write_text("\n".join(lines) + "\nnot json\n" + '{"ts": 999, "kind": "sig', encoding="utf-8")
    a = X.read_log(str(log))
    assert a["state"] == "ok" and a["cut"] is False and len(a["rows"]) == 400 and a["bad"] == 1 and a["half"] is True
    assert X.read_log(str(log)) is a                                                # the same file: not parsed again
    small = X.read_log(str(log), tail=10_000)
    assert small["cut"] is True and small["rows"][-1]["ts"] == 399 and small["from_ms"] == small["rows"][0]["ts"] > 0
    assert len(small["rows"]) < 400 and all(isinstance(r["ts"], int) for r in small["rows"])        # the cut line left out
    with open(log, "a", encoding="utf-8") as fh:
        fh.write('nal"}\n')
    b = X.read_log(str(log))
    assert b is not a and b["bad"] == 1 and b["half"] is False and b["rows"][-1] == {"ts": 999, "kind": "signal"}     # finished now
    assert X.read_log(str(tmp_path / "none.jsonl"))["state"] == "missing"
    (tmp_path / "dir.jsonl").mkdir()
    assert X.read_log(str(tmp_path / "dir.jsonl"))["state"] == "error"


# ================================================================ the routes, read-only
def test_the_routes_on_the_live_app(w, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from paperbot.livedash import app as LA
    for k, v in W.env_of(w["folder"]).items():
        monkeypatch.setenv(k, v)
    before = {n: (open(os.path.join(w["folder"], n), "rb").read(), os.stat(os.path.join(w["folder"], n)).st_mtime_ns) for n in sorted(os.listdir(w["folder"]))}
    app = LA.create_app(None, b"s" * 32, candles=lambda *a, **k: [], ticker=lambda: {}, market=lambda: {}, frames=lambda *a: None,
                        liq_db=str(tmp_path / "no-liq.db"), inbox_db=str(tmp_path / "no-inbox.db"))
    assert app.state.more["livemix"]["routes"] == ["/api/v4/livebots/mix", "/api/v4/livebots/mixperf", "/api/v4/livebots/mixbybit",
                                                   "/api/v4/livebots/mixbybitperf"]
    c = TestClient(app)
    for path, key in (("/api/v4/livebots/mix", "position"), ("/api/v4/livebots/mixperf", "record")):
        r = c.get(path)
        assert r.status_code == 200 and [b["id"] for b in r.json()["bots"]] == ["live", "paper"] and key in r.json()["bots"][0], path
        assert r.json()["bots"][0]["status"]["state"] in ("running", "stopped")
    after = {n: (open(os.path.join(w["folder"], n), "rb").read(), os.stat(os.path.join(w["folder"], n)).st_mtime_ns) for n in sorted(os.listdir(w["folder"]))}
    assert after == before                                                          # nothing written, nothing new


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
              f"const X = await import('file://{SCREENS}/livebots-mix.js');\n" + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n"
              "const mkCtx = (a) => ({params: {query: {}}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, href: (n) => '#/' + n,"
              " every() {}, api: async () => JSON.parse(JSON.stringify(a))});\n"
              "const run = async (V, a) => { const v = V(mkCtx(a)); await tick(); await tick(); return v; };\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_views_in_node(w, tmp_path):
    ctl, prf = json_finite(X.control(_p(w), NOW)), json_finite(X.perf(_p(w), NOW))
    off_p = _p(tmp_path)
    oc, op = json_finite(X.control(off_p, NOW)), json_finite(X.perf(off_p, NOW))
    out = _node(tmp_path, """
    const a = texts((await run(X.mixView, D_c)).el), b = texts((await run(X.mixperfView, D_p)).el);
    const oa = texts((await run(X.mixView, D_oc)).el), ob = texts((await run(X.mixperfView, D_op)).el);
    const L = D_c.bots[0], P = D_c.bots[1];
    console.log(JSON.stringify({a, b, oa, ob,
      st: [X.statusOf(L, D_c.now_ms), X.statusOf({...L, status: {...L.status, state: 'stopped'}}, D_c.now_ms), X.statusOf(D_oc.bots[0], D_c.now_ms)],
      vd: [X.verdictOf(L), X.verdictOf(P), X.verdictOf({...P, halts: {items: [{kind: 'own', ko: '정지 파일', sure: true}]}}),
           X.verdictOf({...P, blocks: {...P.blocks, now: {blocked: true, ko: '주말(한국 시간 토·일) 진입 안 함'}}}), X.verdictOf(D_oc.bots[0])],
      lad: [X.ladderKo(L.position), X.ladderKo({next: {...L.position.next, reached: true}}), X.stopKo(L.position)],
      pnl: [X.pnlKo(0.02), X.pnlKo(-0.13), X.pnlKo(null), X.pnlKo(0)], hold: [X.holdKo(31 * 3600e3 + 20 * 60e3), X.holdKo(45 * 60e3), X.holdKo(50 * 3600e3), X.holdKo(null)],
      feed: L.feed.rows.map((x) => X.feedKo(x)), rec: X.recordRows(D_p.bots[0].record, true).map((r) => [r[0], r[1]]),
      cmp: X.compareCoins(D_p.backtest, D_p.bots)}));""", c=ctl, p=prf, oc=oc, op=op)
    a = out["a"]
    for word in ("실거래 · WOO X Pro 2", "진짜 돈 · WOO X Pro 두 번째 계정", "돌고 있음", "마지막 기록 10/27 12:00 (9분 전)", "마지막으로 본 30분봉 12:00 마감",
                 "마지막 시작 10/26 12:00", "실거래 잔고", "$49.95", "진입 때 읽은 잔고 · 10/27 09:00", "시작 잔고", "$50.00", "바닥선 (시작의 70%)",
                 "$35.00", "남은 여유 $14.95", "BCH 롱 보유 중", "새 신호는 건너뛰어요 (한 번에 1포지션)", "지금 진입 가능 (진입 금지 시간 아님)",
                 "나스닥 개장 앞뒤 · 10/27 22:00 ~ 10/27 23:00 · 9시간 50분 뒤", "마지막 멈춤 기록 10/26 10:30: 정지 파일(", "그 뒤 진입이 있었어요",
                 "진입 금지: 주말 (한국 시간 토·일) 켬", "40배 격리", "3시간 9분 째", "100.00 · 10/27 09:00", "0.1200개 · ≈ $12.00 (증거금 $0.30)",
                 "100.25 · ROE +10% · 계단 1단계", "맞으면 약 +$0.030 (수수료 전)", "103.80 · ROE +152%",
                 "ROE +290% (107.25)에 닿으면 손절을 103.75 (ROE +150%)로", "가장 유리했던 가격이 ROE +150% (103.75)에 닿으면 손절을 ROE +10% (100.25)로", "10/27 09:00 마감 · 종가 100.00",
                 "마지막 시작 때 설정 실패: ZECUSDT: 레버리지를 못 맞춤 (leverage 20 not allowed)", "모의 · 주문 없음", "모의 잔고", "진짜 돈 아님",
                 "모의 잔고 (상태 파일)", "지금 진입 가능", "포지션 없음",
                 "최근 48시간", "색 변화 11", "진입 3", "건너뜀 6", "조건 안 맞음 2", "청산 2", "계단 2", "경고 4", "손절이 없거나 모자라 다시 걸었어요 · BCH",
                 "거래소를 읽지 못했어요 · BCH", "3번 (10/27 10:00부터)", "BCH 계단 1단계", "손절 99.00 → 100.25", "건너뜀 · 보유 중", "진입 안 함",
                 "30분 평균 RSI 조건 안 맞음", "BCH 하늘색으로 바뀜 (롱 쪽)", "체결 100.00 · 0.1200개 · 손절 99.00", "건너뜀 · 진입 금지 시간",
                 "나스닥 개장 앞 30분·뒤 30분 진입 안 함", "봇 시작", "설정 실패 있음", "XRP 숏 청산 · 손절", "−$0.130", "체결가는 기록에 없음",
                 "건너뜀 · 새 진입 멈춤", "건너뜀 · 같은 봉 다른 코인 먼저", "주말(한국 시간 토·일) 진입 안 함", "30분 평균 RSI 60.0 · 1시간 평균 RSI 55.0"):
        assert word in a, word
    assert not BAD.search(a), BAD.search(a)
    b = out["b"]
    for word in ("닫힌 거래", "2번", "1승 1패", "50.0%", "손익 합", "−$0.110", "평균 익절", "+$0.020", "평균 손절", "−$0.130", "가장 큰 손실", "계단까지 간 거래",
                 "표본 적음", "코인별", "1번 · 1승 0패 · 승률 100%", "아직 없음", "손익 합 (모의)", "−$0.115", "설계서 5년 백테스트와 나란히",
                 "백테스트 한 달 평균", "+1.17%", "32%", "+0.94%", "19%", "+0.37%", "40%", "실거래 아님", "60개월 중 20~30개월은 마이너스였어요",
                 "XRP 숏", "10/26 11:00 → 10/26 11:20 (19분)", "2.0000 → 체결가 기록 없음", "ROE −42%", "계단 1단계",
                 "진입 근거: 30분 평균 RSI 40.0 · 1시간 평균 RSI 45.0 · 종가 2.0000 · 손절 폭 1.00%", "실거래 (mainnet)", "손절 1번 = 잔고의 0.25%",
                 "한 번에 1포지션", "잔고가 시작의 70% 아래면 새 진입 멈춤", "한 포지션 최대 $500.00", "ZEC (시작 때 꺼짐)", "150% → 10%", "20배",
                 "모의 (paper)", "시작 금액 $50.00 (모의)", "나스닥 개장 앞 30분·뒤 30분 (뉴욕 09:30, 평일, 미국 휴장일 빼고) 켬"):
        assert word in b, word
    assert not BAD.search(b), BAD.search(b)
    for t in (out["oa"], out["ob"]):                                        # before the bots run: 꺼짐 and how, nothing made up
        assert "꺼짐" in t and X.OFF_KO["live"] in t and "sudo systemctl start paperbot-mixchop" in t and "sudo systemctl start paperbot-mixchop-paper" in t
        assert "포지션 없음" not in t and "실거래 잔고" not in t and "모의 잔고" not in t and "닫힌 거래" not in t and not BAD.search(t)
    assert "$" not in out["oa"]                                             # (성적 still shows the repo config's rules: said so)
    assert "저장소 기본 설정으로 보여 줘요" in out["ob"] and "한 포지션 최대 $10,000.00" in out["ob"]
    assert "실거래 봇이 아직 꺼져 있어요" in out["oa"] and "실거래 봇이 아직 꺼져 있어요" in out["ob"]
    st = out["st"]
    assert (st[0]["cls"], st[0]["pill"], st[0]["hint"]) == ("run", "돌고 있음", "") and st[1]["hint"] == "서버에서 systemctl status paperbot-mixchop"
    assert st[2]["cls"] == "off" and st[2]["line"] == X.OFF_KO["live"]
    vd = out["vd"]
    assert [v["cls"] for v in vd] == ["hold", "go", "halt", "block", "na"] and vd[3]["sub"] == "주말(한국 시간 토·일) 진입 안 함"
    assert out["lad"][1].endswith("이미 닿음: 다음 30분봉 마감 때 옮겨요") and out["lad"][2] == "100.25 · ROE +10% · 계단 1단계"
    assert out["pnl"] == ["+$0.020", "−$0.130", "모름", "$0.000"] and out["hold"] == ["31시간 20분", "45분", "2일 2시간", "—"]
    fd = out["feed"]
    assert fd[1] == {"head": "거래소를 읽지 못했어요 · BCH", "pill": "주의", "tone": "warn", "text": "3번 (10/27 10:00부터) · timeout"}
    assert all(not BAD.search(json.dumps(x, ensure_ascii=False)) for x in fd)
    assert dict((r[0], r[1]) for r in out["rec"])["닫힌 거래"] == "2번"
    cmp = {r["coin"]: r for r in out["cmp"]}
    assert cmp["SOL"]["month"] == "+1.17%" and cmp["SOL"]["live"] == "1번 · 승률 100% · +$0.020" and cmp["ETH"]["paper"] == "아직 없음" and cmp["SOL"]["small"] is True


HQ_JS = """
for (const [k, f] of Object.entries({after: (p, i, x) => p.childNodes.splice(i + 1, 0, x), before: (p, i, x) => p.childNodes.splice(i, 0, x),
  replaceWith: (p, i, x) => p.childNodes.splice(i, 1, x)})) if (!Node.prototype[k]) Node.prototype[k] = function (x) {
  const p = this.parentNode; if (!p) return; f(p, p.childNodes.indexOf(this), x); x.parentNode = p; };
const K = await import('file://SCREENS/livebots-kit.js');
const HQ = await import('file://SCREENS/livebots-hq.js');
const ctxOf = (mix) => ({params: {query: {}, arg: ''}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, timeout() {},
  href: (n) => '#/' + n, every(ms, fn, o) { if (o && o.now === false) return; fn(); },
  api: async (path) => { const a = {'/api/v4/livebots/now': D_n, '/api/v4/livebots/calendar': D_cal, '/api/v4/livebots/rank': D_r,
    '/api/v4/livebots/mix': mix}[path]; if (a === undefined) throw Object.assign(new Error('x'), {status: 503}); return JSON.parse(JSON.stringify(a)); }});
const view = async (mix) => {
  K.setPapers(D_s.papers); K.setExecs(D_s.execs);
  const v = HQ.hqView(ctxOf(mix), {get: () => D_s, state: () => 'ok', at: () => D_s.now_ms, retry: () => {}});
  await tick(); v.set(D_s, 'ok'); await tick(); await tick();
  const w = D.walk(v.el);
  return {text: w.text.replace(/\\s+/g, ' '), reactors: w.classes.filter((x) => x.split(' ').includes('lbh-reactor')).length,
    deck: w.classes.find((x) => x.startsWith('lbh-deck')), mix: w.classes.filter((x) => x.split(' ').includes('lbh-mix'))};
};
const on = await view(D_m), off = await view(D_o), late = await view(D_l), failed = await view(undefined);
const L = D_m.bots[0];
console.log(JSON.stringify({on, off, late, failed,
  led: [HQ.mixLed(L), HQ.mixLed(D_o.bots[0]), HQ.mixLed(D_l.bots[0]), HQ.mixLed(null), HQ.mixLed(null, true),
        HQ.mixLed({...L, halts: {items: [{kind: 'own', ko: '이 봇 전용 정지 파일', sure: true}]}}), HQ.mixLed({...L, status: {...L.status, state: 'error', reason_ko: '권한 없음'}})],
  ring: HQ.tradeRing(L.recent), ring0: HQ.tradeRing(null), ring25: HQ.tradeRing(Array.from({length: 25}, (_, i) => ({win: i % 5 === 0}))),
  gate: [HQ.mixGate(L), HQ.mixGate({...L, position: null}), HQ.mixGate({...L, position: null, blocks: {...L.blocks, now: {blocked: true, kind: 'weekend'}}}),
         HQ.mixGate({...L, halts: {items: [{sure: true}]}}), HQ.mixGate(D_o.bots[0]), HQ.mixGate(D_l.bots[0])],
  who: [HQ.botOfExec(null, D_s.execs[0]), HQ.botOfExec(D_s, D_s.execs[0]), HQ.botOfExec(D_s, {...D_s.execs[0], follows_ko: 'VWAP 개선판'})]}));
"""


def test_the_four_live_accounts_on_hq(w, tmp_path):
    """한눈에 (screens/livebots-hq.js; owners 10-25 night): 바이비트 · WOO X Pro (추세판단 봇) · 딥코인 (설치 전 until its executor
    comes) · WOO X Pro 2 (친구 30분 봇(믹스), its own state and log): every card says its bot; 꺼짐 / 기록 멈춤 / 불러오지 못함,
    never a zero; nothing there says 주문 (view only)."""
    f = tmp_path / "fees"
    f.mkdir()
    world = FW.build_world(f)
    p = world["p"]
    summ = json_finite(L.build(p, FW.NOW))
    extra = {"n": json_finite(L.whynow(p, FW.NOW)), "cal": json_finite(L.calendar(p, FW.NOW)), "r": json_finite(L.rank(p, FW.NOW))}
    mix = json_finite(X.control(_p(w), NOW))
    off = json_finite(X.control(_p(tmp_path / "none"), NOW))
    late = json_finite(X.control(_p(w), K(27, 12, 0, 5) + 36 * MIN))
    out = _node(tmp_path, HQ_JS.replace("SCREENS", SCREENS), s=summ, m=mix, o=off, l=late, **extra)
    on = out["on"]
    t = on["text"]
    assert on["reactors"] == 4 and {"three", "four"} <= set(on["deck"].split()) and "five" not in on["deck"].split() and len(on["mix"]) == 1
    for word in ("바이비트 진짜 돈 봇", "WOO X Pro 진짜 돈 봇", "따라감 · 그 봇의 페이퍼 진입을 실거래로 따라 들어가요",
                 "딥코인 진짜 돈 봇 VWAP 개선판 따라갈 실행기 (paperbot-executor-deepcoin) 설치 전 이 서버에 딥코인 실행기가 아직 없어요",
                 "설치하고 켜면 잔고 · 신호등 · 포지션이 여기 보여요",
                 "WOO X Pro 2 진짜 돈 봇 친구 15분 봇 스스로 매매 · 페이퍼를 따라가지 않음 돌아가는 중", "DAY 04", "49.95", "×1.00",
                 "시작 대비 −$0.05 · 진입 때 읽은 잔고 10/27 09:00", "최근 거래 · 1승 1패", "신호등 없음 · 30분봉 신호마다 바로 들어가요",
                 "오늘 실현 닫힌 거래 없음", "포지션 BCH 롱 40배 · 계단 1단계", "새 진입 보유 중 (한 번에 1개)",
                 "30분봉 신호 · SOL·ETH·XRP·BCH·ZEC(꺼짐)·DOGE · 손절 1번 잔고의 0.25%",
                 "마지막 시작 때 설정 실패: ZECUSDT: 레버리지를 못 맞춤 (leverage 20 not allowed)", "믹스 관제 · 성적 →"):
        assert word in t, word
    bots = re.findall(r"진짜 돈 봇 (.+?) (따라감|따라갈|스스로) ", t)
    assert ("친구 15분 봇", "스스로") in bots and ("VWAP 개선판", "따라갈") in bots and len(bots) == 4      # every card says its bot
    assert "딥코인 $" not in t and not BAD.search(t)
    assert "주문" not in t.replace("주문 버튼 없음", "").replace("주문 없음", "")                    # view only
    o = out["off"]["text"]
    assert "WOO X Pro 2 진짜 돈 봇 친구 15분 봇 스스로 매매 · 페이퍼를 따라가지 않음 꺼짐 아직 켠 적 없어요 (기록 파일 없음) · 켜기: sudo systemctl start paperbot-mixchop" in o
    assert "최근 거래 —" in o and "49.95" not in o and not BAD.search(o)
    assert "기록 멈춤" in out["late"]["text"] and "서버에서 systemctl status paperbot-mixchop" in out["late"]["text"]
    assert "WOO X Pro 2 진짜 돈 봇 친구 15분 봇 스스로 매매 · 페이퍼를 따라가지 않음 불러오지 못함" in out["failed"]["text"]
    led = out["led"]
    assert [x["id"] for x in led] == ["run", "none", "stale", "wait", "bad", "halt", "bad"] and led[0]["why"] is None
    assert led[5]["ko"] == "새 진입 멈춤" and led[6]["why"] == "권한 없음"
    ring = out["ring"]
    assert (ring["n"], ring["have"], ring["wins"], ring["losses"]) == (20, 2, 1, 1) and [x["v"] for x in ring["segs"][:3]] == [True, False, None]
    assert out["ring0"]["have"] == 0 and out["ring25"]["have"] == 20 and out["ring25"]["wins"] == 4
    assert out["gate"] == ["보유 중 (한 번에 1개)", "가능 · 30분봉 신호를 기다려요", "진입 금지 시간 · 주말", "멈춤", "—", "— (기록 멈춤)"]
    assert out["who"][0] == "" and out["who"][1] and out["who"][2] == "VWAP 개선판"
    # the mix answer's card parts: today (KST) and the last 20 results, oldest first
    lv = _bots(X.control(_p(w), NOW))["live"]
    assert lv["today"] == {"n": 0, "known": 0, "unknown": 0, "wins": 0, "losses": 0, "pnl": None, "from_ms": K(27)}
    assert [(x["symbol"], x["win"]) for x in lv["recent"]] == [("SOLUSDT", True), ("XRPUSDT", False)]
    assert lv["status"]["first_start_ms"] == K(24, 10, 0, 10) and lv["risk_pct"] == 0.25
    assert _bots(X.control(_p(w), K(26, 23)))["live"]["today"]["n"] == 2                          # Monday: both trades


def test_the_menu_group_and_the_tabs():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    v4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
    script = (f"await import('file://{DOM}');\nglobalThis.document.documentElement.dataset.site = 'live';\n"   # (icon() draws)
              f"const R = await import('file://{v4}/core/routes.js');\n"
              "console.log(JSON.stringify({groups: R.GROUPS.map((g) => [g.id, g.ko, g.screens]), keys: R.KEYS, nav: R.navGroups(true).map((g) => g.ko),"
              " screens: ['mix', 'mixperf'].map((k) => [R.SCREENS[k].ko, R.SCREENS[k].group, R.SCREENS[k].mod]),"
              " parse: R.parseHash('#/livebots/mixperf'), href: R.href('livebots', 'mix'), icons: [R.icon('mix').childNodes.length]}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout.strip().splitlines()[-1])
    # (the 바이비트 봇's group after it since 10-29, tests/test_dash_mixbybit_site.py)
    assert d["groups"][-2] == ["mix", "믹스 봇", ["mix", "mixperf"]] and d["nav"][-2] == "믹스 봇" and len(d["groups"]) == 8
    assert d["groups"][-3][0] == "vwap" and d["groups"][-1][0] == "bybit"            # VWAP 봇 stays where it was
    # 봇별 first (owners 10/26, tests/test_dash_livev39.py): its five screens take the first number keys (레인지 봇 second)
    assert d["keys"] == ["bybitbot", "rangebot", "vwapbot", "mixbot", "v39", "trendbot", "trend", "tchart", "hq"]
    assert d["screens"] == [["믹스 관제", "mix", "livebots"], ["믹스 성적", "mix", "livebots"]]
    assert d["parse"]["name"] == "mixperf" and d["href"] == "#/mix" and d["icons"][0] > 5
    lb = FW._read(SCREENS, "livebots.js")
    for t, label in (("mix", "믹스 관제"), ("mixperf", "믹스 성적")):
        assert f'{{id: "{t}", label: "{label}"' in lb
    assert 'import {mixView, mixperfView, BYBIT_UI} from "./livebots-mix.js";' in lb       # (the 바이비트 봇's too, 10-29)
    routes = FW._read(ROOT, "paperbot", "dash", "static", "v4", "core", "routes.js")
    assert "mix: ICON.mix," in routes and "mixperf: () => SICON.board()," in routes
    assert "mix:" in FW._read(ROOT, "paperbot", "dash", "static", "v4", "core", "search.js").split("export const LIVE_ALIAS")[1]
    assert ".botbar { grid-template-columns: repeat(8, minmax(0, 1fr)); }" in FW._read(ROOT, "paperbot", "dash", "static", "live", "live.css")


def test_the_files_keep_the_house_rules():
    FW.house_rules("livebots-mix", "lmx")
    js = FW._read(SCREENS, "livebots-mix.js")
    for api in ('"/api/v4/livebots/mix"', '"/api/v4/livebots/mixperf"'):
        assert api in js
    assert '@import url("livebots-mix.css");' in FW._read(SCREENS, "livebots.css")
    assert re.search(r"^MODULES = MODULES \+ \(\"livemix\",\)$", FW._read(ROOT, "paperbot", "livedash", "app.py"), re.M)
    # read-only: the module never opens a file to write, never runs a command
    src = FW._read(ROOT, "paperbot", "dash", "more", "livemix.py")
    assert not re.search(r"open\([^)]*['\"][wa]b?['\"]", src) and "subprocess" not in src and "write_state" not in src and ".unlink(" not in src


def test_the_second_rules_rows_in_words(tmp_path):
    """Owners 10-26: a Stoch RSI cross row says whose it is and its own numbers; the friend's rows read as before."""
    st = {"cat": "signal", "coin": "SOL", "rule": "st", "rule_ko": "슈퍼트렌드·스톡RSI", "colour_ko": "골든크로스", "want": 1,
          "stage": "refused", "why": "30분 RSI26 조건 안 맞음", "vals": {"k": 30.1, "d": 25.2, "rsi26_30m": 48.0, "rsi26_1h": 54.0, "close": 100.0, "stop_pct": 1.5}}
    mix = {"cat": "signal", "coin": "SOL", "rule": "mix", "rule_ko": "친구 매매법", "colour_ko": "하늘색으로 바뀜", "want": 1, "stage": "waiting",
           "vals": {"avg_rsi_30m": 60.0, "avg_rsi_1h": 55.0}}
    out = _node(tmp_path, "console.log(JSON.stringify([X.feedKo(D_s), X.feedKo(D_m)]));", s=st, m=mix)
    assert out[0]["head"] == "SOL 슈퍼트렌드·스톡RSI 골든크로스" and out[0]["pill"] == "진입 안 함"
    assert out[0]["text"] == "30분 RSI26 조건 안 맞음 · 스톡RSI K 30.1 / D 25.2 · 30분 RSI26 48.0 · 1시간 RSI26 54.0 · 종가 100.00 · 손절 폭 1.50%"
    assert out[1]["head"] == "SOL 하늘색으로 바뀜 (롱 쪽)" and out[1]["text"] == "30분 평균 RSI 60.0 · 1시간 평균 RSI 55.0"



MARK_JS = """
const PB = await import('file://SCREENS/../core/pb.js');
globalThis.fetch = async (path) => {                          // the page's ticker: BCH at 101 (nothing else answers)
  if (path !== '/api/ticker') throw new Error('offline');
  return {status: 200, ok: true, json: async () => ({BCHUSDT: {mark: 101}})};
};
await PB.store.need('ticker', 0);
const v = await view(D_m);
console.log(JSON.stringify({text: v.text}));
"""


def test_the_friend_bot_card_and_strip_move_with_the_mark(w, tmp_path, monkeypatch):
    """한눈에, owners 10-27 ("친구봇 돈 움직이는것도 안뜨고 저기 위에 문구도 없어"): with BCH long 0.12 @ 100 open (margin $0.30) and the
    page's mark at 101, the 친구봇 card shows the balance read at the entry + the position's P&L ($49.95 + $0.12) and ROE +40 %;
    with a paper or executor position open (the gauge shows), its strip of real-money positions has a WOO X Pro 2 row too."""
    from tests import livebots_world as LW
    mix = json_finite(X.control(_p(w), NOW))
    js = (HQ_JS.split("const on = await view")[0] + MARK_JS).replace("SCREENS", SCREENS)
    # no paper / executor position: the card moves, the gauge (and its strip) stays hidden
    f = tmp_path / "fees"
    f.mkdir()
    p = FW.build_world(f)["p"]
    t = _node(tmp_path, js, s=json_finite(L.build(p, FW.NOW)), m=mix, n=json_finite(L.whynow(p, FW.NOW)),
              cal=json_finite(L.calendar(p, FW.NOW)), r=json_finite(L.rank(p, FW.NOW)))["text"]
    for word in ("WOO X Pro 2 진짜 돈 봇 친구 15분 봇 스스로 매매", "$ 50.07 ×1.00", "시작 대비 +$0.07 · 진입 때 잔고 $49.95 + 평가 +$0.12",
                 "포지션 BCH 롱 40배 · 계단 1단계 · ROE +40.0%"):
        assert word in t, word
    assert "진입 때 읽은 잔고 10/27 09:00" not in t and not BAD.search(t)
    # the paper and both executors hold BTC (tests/livebots_world.py): the strip lists them, then WOO X Pro 2
    L._cache.clear()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent")
    q = LW.build_world(str(tmp_path / "lw"))
    t = _node(tmp_path, js, s=json_finite(L.build(q, LW.NOW)), m=mix, n=json_finite(L.whynow(q, LW.NOW)),
              cal=json_finite(L.calendar(q, LW.NOW)), r=json_finite(L.rank(q, LW.NOW)))["text"]
    L._cache.clear()
    row = re.search(r"WOO X Pro 2 BCH 롱 · 진입 (\S+) 거래소 손절 (\S+) 계단 1단계 (\S+)", t)
    assert row and row.groups() == ("100.00", "100.25", "+40.0%"), t[t.find("거래소 손절") - 200:]
    assert t.index("바이비트 BTC") < t.index("WOO X Pro 2 BCH") and not BAD.search(t)


def test_the_positions_tab_has_the_friend_bot(w, tmp_path):
    """실거래 › 포지션 (dash/more/livepos.py mix_card; owners 10-27 "친구봇 대시보드 화면에 실시간 포지션도 안뜨고"): the 친구봇
    trades by itself (no executor, no paper), so its card comes from its own state file: BCH long 0.12 @ 100, 40x, margin $0.30,
    its stop, its net-ROE ladder (the live config's 10 -> 8, then every 5 %) at its own fee round trip; no paper gap line."""
    from paperbot.dash.more import livepos as LP
    mp = _p(w)
    with open(mp["live"]["config"], encoding="utf-8") as fh:
        raw = json.load(fh)
    raw.update(ladder={"trigger": 10, "lock": 8, "step": 5}, ladder_every_s=60)
    cfgp = tmp_path / "live-net.json"
    cfgp.write_text(json.dumps(raw), encoding="utf-8")
    mp = {**mp, "live": {**mp["live"], "config": str(cfgp)}}
    f = tmp_path / "fees"
    f.mkdir()
    p = FW.build_world(f)["p"]
    d = json_finite(LP.build(p, {**L.paths_more({}), "mix_paths": mp}, NOW))
    ids = [c["id"] for c in d["cards"]]
    assert "mix" in ids and ids.index("mix") > ids.index("paper")
    c = next(c for c in d["cards"] if c["id"] == "mix")
    assert (c["state"], c["kind"], c["self"], c["name_ko"]) == ("ok", "live", True, "WOO X Pro 2 · 친구봇")
    q = c["position"]
    fee = M.load_config(str(cfgp)).taker_fee
    assert (q["symbol"], q["side"], q["leverage"], q["entry"], q["qty"]) == ("BCHUSDT", 1, 40, 100.0, 0.12)
    assert q["margin"] == pytest.approx(0.3) and q["round_trip"] == pytest.approx(2 * fee) and q["locked"] is True
    assert q["stop"] == pytest.approx(100.25) and q["lock_roe"] == pytest.approx(0.08) and q["ladder_from"] == "bot"
    nx = q["next"]                                       # step 2: net 15 % -> 13 %
    assert (nx["at"], nx["lock"]) == (pytest.approx(0.15), pytest.approx(0.13))
    assert nx["price"] == pytest.approx(100 * (1 + 0.15 / 40 + 2 * fee)) and nx["screen_at"] == pytest.approx(0.15 + 40 * 2 * fee)
    assert [(round(s["at"], 4), round(s["lock"], 4), s["state"]) for s in q["ladder"][:3]] == [(0.1, 0.08, "done"), (0.15, 0.13, "next"), (0.2, 0.18, "later")]
    assert q["secured"]["roe"] == pytest.approx(40 * (0.0025 - 2 * fee)) and q["gap"] is None and q["fast"]["state"] == "none"
    # the card in node: the bot's rule line, no "follow the paper" words, the ladder said as the bot's own
    out = _node(tmp_path, f"""
    const P = await import('file://{SCREENS}/livebots-pos.js');
    const el = P.posCard(D_c, {{}}); el.update(101);
    const flat = P.posCard({{...D_c, position: null}}, {{}});
    console.log(JSON.stringify({{t: texts(el), flat: texts(flat)}}));""", c=c)
    t = out["t"]
    for word in ("WOO X Pro 2 · 친구봇", "진짜 돈", "BCHUSDT", "격리 40배", "믹스 30분 봇 · 30분봉 신호 · 스스로 매매 (페이퍼를 따라가지 않음)",
                 "친구봇 기준: 자기 체결가 · 바이낸스 1분봉 · 친구봇 수수료로 잠가요 (60초마다)", "10%→8%", "15%→13%",
                 "확보한 수익", "빠른 손절 없음 · 친구봇은 손절선과 계단 익절로만 닫아요"):
        assert word in t, word
    assert "페이퍼와 진입 차이" not in t and "매매법 모름" not in t and not BAD.search(t)
    assert "30분봉 신호를 기다려요 · 스스로 매매 (한 번에 포지션 하나)" in out["flat"] and "다음 페이퍼 진입" not in out["flat"]
