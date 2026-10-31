"""실거래 › 봇별 (owners 10-26: "대시보드에 추가화면으로 안헷갈리게 추세판단봇 화면 따로, vwap 개선판 봇 화면 따로, 친구 15분 봇
화면 따로, v3.9 화면 따로"): four screens, one bot each, first in the live site's menu (core/routes.js LIVE_GROUPS "bots";
screens/livebots.js BOT_TAB), and the new one, V3.9 투비트 (dash/more/livev39.py, screens/livebots-v39.js):

- the menu: 봇별 first with 추세판단 봇 · VWAP 개선판 · 친구 15분 봇 · V3.9 투비트, every other group and tab as it was;
- the summary names which paper bot each executor follows (``execs[].bot``), and a 봇별 screen's strip and head name that
  bot's executors only (kit followersOf, realLine(d, {only, none}));
- V3.9 투비트 before the executor runs: 아직 꺼져 있어요 and the guide's step, the plan from the repo template (said so), no
  number made up; once it runs (a world made by the executor's own ExecStore and the rule bot's Store3, the account
  V39_ALL@1h as tests/test_toobit_slot.py makes it): the plan from the server's config, the open position with its ladder
  step, the trades with the paper trade each followed, the paper entries followed / missed with the executor's own reason
  (liq_skip, macro_skip) or before its start, the equity; 기록 멈춤, 멈춤 and 못 읽음 when so;
- the route on the live app (read-only: nothing written), the views in node, the house rules of the css."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livev39 as X  # noqa: E402
from paperbot.executor import ExecStore  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from tests import livebots_world as LW  # noqa: E402
from tests import test_dash_livebots_fees as FW  # noqa: E402
from tests import test_toobit_slot as TS  # noqa: E402
from tests import vwap_site_world as V  # noqa: E402

ROOT = FW.ROOT
SCREENS, DOM, BAD = FW.SCREENS, FW.DOM, FW.BAD
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
NOW, MIN, H = TS.NOW, V.MIN, V.H
ACC = TS.TB_ACC
TEMPLATE = os.path.join(ROOT, "deploy", "executor.live-toobit.json")
# (coin, side, entry ms, reason, pnl): LTC before the executor's start, SOL skipped (liq_skip), BCH skipped (macro_skip)
EXTRA = (("LTCUSDT", -1, V.K(3, 9), "SL", -40.0), ("BCHUSDT", -1, V.K(5, 22), "SL", -35.0), ("SOLUSDT", 1, V.K(6, 2), "LOCK", 30.0))
LADDER = {"first_lock": 0.17, "trigger_gap": 0.03, "step": 0.05, "next_trigger": 0.25, "next_gap": 0.03}


def _key(sym: str, t: int) -> str:
    return f"{ACC}|{sym}|{t}"


def world(folder: str) -> dict:
    """paper3.db (V39_ALL@1h: tests/test_toobit_slot.py's two followed trades and the open DOGE, plus EXTRA) and 투비트's
    database and config (the owners' template with the account and the paper file filled in); the open DOGE position at
    its first ladder step (거래소 기준: lock 17 %, next 25 % -> 22 %: the ladder it was opened with, 20 -> 17, kept in the trade;
    the plan reads the template's ladder, 12 -> 10 since 10-27)."""
    os.makedirs(folder, exist_ok=True)
    rp = TS.rule_paper_db(os.path.join(folder, "paper3.db"))
    s = Store3(rp["path"])
    eq = 1000.0
    for sym, side, et, reason, pnl in EXTRA:
        d = {"strategy_id": "V39_ALL", "symbol": sym, "timeframe": "1h", "side": side, "entry_time": et, "entry_price": 100.0,
             "exit_time": et + 2 * H, "exit_price": 100.0 * (1 + side * 0.01), "exit_reason": reason, "qty": 90.0, "leverage": 30,
             "margin": 300.0, "fees": 0.5, "funding": 0.0, "pnl": pnl, "roe": pnl / 300.0, "context": {}}
        eq += pnl
        s.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?)", (ACC, sym, et, et + 2 * H, reason, 30, pnl, pnl / 300.0, eq, json.dumps(d)))
    s.close()
    paths = {"config": os.path.join(folder, "executor-toobit.json"), "db": os.path.join(folder, "executor-toobit-live.db"),
             "paper": os.path.join(folder, "no-paper3.db"), "repo_config": TEMPLATE}
    x = TS.toobit_db(paths["db"], paths["config"], rp)
    st = ExecStore(paths["db"], lock=False)
    st.event(V.K(5, 22) + 3000, "INFO", "macro_skip", "BCHUSDT 미국 경제 발표(CPI 10/26 22:30) 앞뒤 30분이라 이번 진입은 하지 않음",
             {"key": _key("BCHUSDT", V.K(5, 22))})
    st.event(V.K(6, 2) + 5000, "INFO", "liq_skip", "SOLUSDT 손절(2.5 ATR)이 강제청산 가격보다 멀어 이번 진입은 하지 않음",
             {"key": _key("SOLUSDT", V.K(6, 2))})
    st.event(NOW - 30 * MIN, "WARN", "move_failed", "DOGEUSDT 손절 옮기기 실패: timeout", {"key": x["trade"]["key"]})
    trade = dict(x["trade"], stop=0.2113, own={
        "lock": 0.17, "lock_price": 0.2113, "best": 0.2166, "best_roe": 0.21, "rt": 0.0016, "basis": "net", "exchange": "toobit",
        "cost": {"taker_fee": 0.0006, "slippage": 0.0002}, "ladder": LADDER,
        "next": {"lock": 0.22, "at": 0.25, "price": 0.21195, "lock_price": 0.21160}})
    st.put_state("bot", NOW - 5_000, {"trade": trade, "done": [], "loops": 9000, "mode": "mainnet", "account": ACC,
                                      "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 0, "last_equity": x["equity"]}})
    st.close()
    return {"p": paths, "rp": rp, "x": x, "folder": folder}


@pytest.fixture(scope="module")
def w(tmp_path_factory):
    return world(str(tmp_path_factory.mktemp("v39") / "w"))


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    yield
    L._cache.clear()


def _off(tmp_path) -> dict:
    return {"config": str(tmp_path / "none.json"), "db": str(tmp_path / "none.db"), "paper": str(tmp_path / "no-paper3.db"),
            "repo_config": TEMPLATE}


# ================================================================ the answer
def test_off_before_the_executor_runs(tmp_path):
    """No config, no database: 아직 꺼져 있어요 and the guide's step; the plan from the repo template, said so; nothing made up."""
    d = X.build(_off(tmp_path), NOW)
    s = d["status"]
    assert (s["state"], s["ko"]) == ("off", "아직 꺼져 있어요") and s["why_ko"] == "서버에 설정 파일도 기록 파일도 아직 없어요"
    assert s["guide"] == "docs/toobit-ko.md" and "실행기 켜기" in s["guide_ko"] and s["unit"] == "paperbot-executor-toobit"
    assert os.path.exists(os.path.join(ROOT, s["guide"]))
    assert d["position"] is None and d["trades"] == [] and d["today"] is None and d["record"] is None and d["events"] == []
    assert d["equity"] == {"state": "missing"} and d["follow"]["rows"] == []
    assert d["paper"]["state"] == "missing" and d["paper"]["account"] == "V39_ALL@1h"
    pl = d["plan"]
    assert pl["source"] == "repo" and "저장소의 설정 원본" in pl["reason_ko"]
    words = {x["key"]: x["ko"] for x in pl["lines"]}
    # the owners' plan (docs/toobit-ko.md "두 분이 정한 계획"), from the template's own numbers
    assert "투비트 잔고의 40%" in words["size"] and words["leverage"].startswith("BTC 40배 · 나머지 30배")
    assert words["stop"].startswith("2.5 ATR (페이퍼 손절 거리 2 ATR × 1.25)")
    assert "순ROE 12%→10% · 17%→15% · 22%→20% …" in words["ladder"] and "순ROE 12%에서 10% 잠금, 이후 5%씩" in words["ladder"]
    assert words["tp"] == "없음" and "강제청산 가격보다 멀면 그 진입은 안 함" in words["liq"] and "40배 약 2%" in words["liq"]
    assert "30배 약 2.83%" in words["liq"] and words["macro"].startswith("미국 경제 발표(CPI·FOMC·NFP·PCE) 앞뒤 30분은 새 진입 안 함")
    # owners 10-26 "투비트도 나스닥 개장 앞뒤 30분 진입금지" (the template's us_open_pre_min / us_open_pause_min)
    assert words["us_open"] == "나스닥 개장 앞 30분·뒤 30분은 새 진입 안 함 · 열린 포지션은 그대로"
    lim = {x["key"]: x for x in L.fixed_rules(json.load(open(TEMPLATE, encoding="utf-8")))}
    assert lim["us_open"]["value"] == [30, 30] and lim["us_open"]["ko"] == "나스닥 개장 앞 30분·뒤 30분 새 진입 안 함"
    assert L.WHY_KO["us_open_skip"] == "나스닥 개장 앞뒤라 들어가지 않았어요" and L.KIND_KO["us_open_skip"] == "나스닥 개장 앞뒤라 안 들어감"
    assert L.fixed_rules({"us_open_pre_min": 0}) == [] and L.us_open_window({"us_open_pause_min": 15}) == (0, 15)
    assert "BTC · ETH · SOL · DOGE · LTC · BCH" in words["coins"] and "정한 금액 $50" in words["coins"] and "V39_ALL@1h" in words["follow"]
    assert pl["ladder"] == [{"at": 0.12, "lock": 0.1}, {"at": 0.17, "lock": 0.15}, {"at": 0.22, "lock": 0.2}, {"at": 0.27, "lock": 0.25}]
    # a config on the server but no database yet: still off, said why
    with open(TEMPLATE, encoding="utf-8") as fh:
        (tmp_path / "cfg.json").write_text(fh.read(), encoding="utf-8")
    d2 = X.build({**_off(tmp_path), "config": str(tmp_path / "cfg.json")}, NOW)
    assert d2["status"]["state"] == "off" and "설정 파일은 서버에 있어요" in d2["status"]["why_ko"] and d2["plan"]["source"] == "server"


def test_running_plan_position_and_ladder(w):
    d = X.build(w["p"], NOW)
    s = d["status"]
    assert (s["state"], s["ko"]) == ("running", "켜져 있어요") and s["since_ms"] == V.K(4, 9) and s["seen_ms"] == NOW - 5_000
    assert d["plan"]["source"] == "server" and d["plan"]["account"] == ACC and d["notes"] == []
    p = d["position"]
    assert (p["coin"], p["side"], p["leverage"], p["step"], p["lock_roe"], p["locked"]) == ("DOGE", 1, 30, 1, 0.17, True)
    assert p["next"] == {"at": 0.25, "lock": 0.22, "price": 0.21195, "lock_price": 0.2116} and p["best_roe"] == 0.21
    assert p["stop"] == 0.2113 and p["stop_move"] > 0 and p["stop_roe"] == pytest.approx(p["stop_move"] * 30)
    assert p["liq_frac"] == pytest.approx(1 / 30 - 0.005) and p["liq_price"] == pytest.approx(p["entry"] * (1 - (1 / 30 - 0.005)))
    assert p["paper_entry"] == 0.21 and p["stop_order"] is True


def test_trades_follow_and_why(w):
    d = X.build(w["p"], NOW)
    tr = d["trades"]
    assert [t["coin"] for t in tr] == ["ETH", "BTC"] and all(t["paper"] for t in tr)            # newest first, each with its paper trade
    assert tr[0]["paper"]["exit_ko"] == "손절" and tr[1]["paper"]["exit_ko"] == "잠금 익절" and tr[0]["est"] is False
    assert sum(t["pnl"] for t in tr) == pytest.approx(d["record"]["pnl"]) and d["record"]["trades"] == 2
    assert d["today"]["trades"] == 0                                         # nothing closed today (KST) in the world
    f = d["follow"]
    by = {r["coin"]: r for r in f["rows"]}
    assert by["DOGE"]["state"] == "open" and by["DOGE"]["open"] is True
    assert by["BTC"]["state"] == "followed" and by["BTC"]["live"]["exit_ko"] == "페이퍼 따라 청산" and by["ETH"]["state"] == "followed"
    assert (by["SOL"]["state"], by["SOL"]["why_kind"]) == ("missed", "liq_skip") and by["SOL"]["why_ko"] == L.WHY_KO["liq_skip"]
    assert (by["BCH"]["state"], by["BCH"]["why_kind"]) == ("missed", "macro_skip") and "앞뒤 30분" in by["BCH"]["why_text"]
    assert by["LTC"]["state"] == "before"
    assert f["counts"] == {"open": 1, "followed": 2, "missed": 2, "before": 1}
    assert [r["entry_ms"] for r in f["rows"]] == sorted((r["entry_ms"] for r in f["rows"]), reverse=True)
    assert {x["kind"] for x in f["why"]} == {"liq_skip", "macro_skip"}
    e = d["equity"]
    assert e["state"] == "ok" and e["first"] == 50.0 and e["now"] == pytest.approx(w["x"]["equity"]) and e["budget"] == 50.0
    assert e["change"] == pytest.approx(w["x"]["equity"] - 50.0) and len(e["curve"]) == 2
    pa = d["paper"]
    assert pa["state"] == "ok" and pa["position"]["coin"] == "DOGE" and pa["record"]["trades"] == 5 and pa["record_live"]["trades"] == 4
    assert [x["kind"] for x in d["events"]] == ["move_failed"]                # WARN / CRITICAL only
    assert not re.search(r"\bnan\b|undefined", json.dumps(json_finite(d), ensure_ascii=False))


def test_stopped_halted_and_unreadable(w, tmp_path):
    d = X.build(w["p"], NOW + 10 * MIN)                                       # its loop wrote nothing for 10 minutes
    assert d["status"]["state"] == "stopped" and "systemctl status paperbot-executor-toobit" in d["status"]["why_ko"]
    db = tmp_path / "halted.db"
    shutil.copy(w["p"]["db"], db)
    st = ExecStore(str(db), lock=False)
    st.put_state("bot", NOW - 5_000, {"trade": None, "done": [], "mode": "mainnet", "account": ACC,
                                      "risk": {"halted": True, "halt_reason": "비상 정지 파일", "halted_ts": NOW - H, "last_equity": 47.0}})
    st.close()
    d = X.build({**w["p"], "db": str(db)}, NOW)
    assert (d["status"]["state"], d["status"]["ko"]) == ("halted", "멈춤") and "비상 정지 파일" in d["status"]["why_ko"]
    assert d["status"]["halted_ms"] == NOW - H and d["position"] is None
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a database" * 100)
    d = X.build({**w["p"], "db": str(bad)}, NOW)
    assert d["status"]["state"] == "error" and d["status"]["reason_ko"] and d["trades"] == [] and d["position"] is None
    assert d["equity"] == {"state": "error"}
    # an account the executor's record names other than the config's: said so
    cfg = json.loads(open(w["p"]["config"], encoding="utf-8").read())
    (tmp_path / "other.json").write_text(json.dumps({**cfg, "account": "V39_ALL@4h"}), encoding="utf-8")
    d = X.build({**w["p"], "config": str(tmp_path / "other.json")}, NOW)
    assert d["notes"] == ["실행기 기록의 계좌(V39_ALL@1h)와 설정의 계좌(V39_ALL@4h)가 달라요"] and d["paper"]["state"] == "none"


def test_the_summary_says_which_bot_each_executor_follows(w, tmp_path):
    """``execs[].bot``: "paper" for the executors on the main paper bot (추세판단 봇's screen), None for 투비트 (its own
    paper account): the 봇별 screens' filter."""
    lw = LW.build_world(str(tmp_path / "lw"))
    env = {**LW.env_of(lw), "PAPERBOT_LIVE_TOOBIT_DB": w["p"]["db"], "PAPERBOT_LIVE_TOOBIT_CONFIG": w["p"]["config"]}
    for k in ("PAPERBOT_LIVE_PAPER2_DB", "PAPERBOT_LIVE_DEEPCOIN_DB", "PAPERBOT_LIVE_DEEPCOIN_CONFIG", "PAPERBOT_LIVE_WOOXPRO2_DB",
              "PAPERBOT_LIVE_WOOXPRO2_CONFIG", "PAPERBOT_LIVE_PAPER3_DB"):
        env[k] = str(tmp_path / ("none-" + k.lower()))
    d = L.build(L.paths(env), LW.NOW)
    assert {x["id"]: x["bot"] for x in d["execs"]} == {"bybit": "paper", "mexc": "paper", "toobit": None}
    env2 = {k: v for k, v in env.items() if "TOOBIT" not in k}
    env2.update(PAPERBOT_LIVE_TOOBIT_DB=str(tmp_path / "no-tb.db"), PAPERBOT_LIVE_TOOBIT_CONFIG=str(tmp_path / "no-tb.json"))
    L._cache.clear()
    assert [x["id"] for x in L.build(L.paths(env2), LW.NOW)["execs"]] == ["bybit", "mexc"]
    # V3.9's own answer reads the same two files the summary does
    p = X.paths(env)
    assert (p["config"], p["db"]) == (w["p"]["config"], w["p"]["db"]) and p["paper"] == "/var/lib/paperbot/paper3.db"


def test_the_route_on_the_live_app(w, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from paperbot.livedash import app as LA
    monkeypatch.setenv("PAPERBOT_LIVE_TOOBIT_DB", w["p"]["db"])
    monkeypatch.setenv("PAPERBOT_LIVE_TOOBIT_CONFIG", w["p"]["config"])
    monkeypatch.setenv("PAPERBOT_LIVE_V39_PAPER_DB", w["p"]["paper"])
    before = {n: (open(os.path.join(w["folder"], n), "rb").read(), os.stat(os.path.join(w["folder"], n)).st_mtime_ns) for n in sorted(os.listdir(w["folder"]))}
    app = LA.create_app(None, b"s" * 32, candles=lambda *a, **k: [], ticker=lambda: {}, market=lambda: {}, frames=lambda *a: None,
                        liq_db=str(tmp_path / "no-liq.db"), inbox_db=str(tmp_path / "no-inbox.db"))
    assert "livev39" in LA.MODULES and app.state.more["livev39"]["routes"] == ["/api/v4/livebots/v39"]
    r = TestClient(app).get("/api/v4/livebots/v39")
    assert r.status_code == 200 and r.json()["status"]["state"] in ("running", "stopped") and r.json()["account"] == ACC
    after = {n: (open(os.path.join(w["folder"], n), "rb").read(), os.stat(os.path.join(w["folder"], n)).st_mtime_ns) for n in sorted(os.listdir(w["folder"]))}
    assert after == before                                                    # nothing written, nothing new


# ================================================================ the menu and the views in node
def _node(tmp_path, body: str, live: bool = True, **data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              + ("globalThis.document.documentElement.dataset.site = 'live';\n" if live else "")
              + f"Date.now = () => {NOW};\n" + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_menu_puts_the_four_bots_first(tmp_path):
    out = _node(tmp_path, f"""
    const R = await import('file://{V4}/core/routes.js');
    console.log(JSON.stringify({{groups: R.GROUPS.map((g) => [g.id, g.ko, g.screens]), keys: R.KEYS, land: R.landing(),
      nav: R.navGroups(true).map((g) => [g.ko, g.items.map((it) => it.ko)]),
      screens: ['trendbot', 'rangebot', 'vwapbot', 'mixbot', 'v39'].map((k) => [R.SCREENS[k].ko, R.SCREENS[k].group, R.SCREENS[k].mod]),
      parse: R.parseHash('#/v39'), href: R.href('livebots', 'mixbot'), icon: R.icon('bots').childNodes.length}}));""")
    # 레인지 봇 (owners 10/26 evening, tests/test_dash_live_range.py) right after 추세판단 봇
    # (owners 10-29: the 바이비트 봇 first, the 추세판단 봇 switched off last, the 바이비트 봇's group last;
    # tests/test_dash_mixbybit_site.py)
    assert out["groups"][0] == ["bots", "봇별", ["bybitbot", "rangebot", "vwapbot", "mixbot", "v39", "trendbot"]]
    assert [g[0] for g in out["groups"]] == ["bots", "now", "rec", "perf", "ops", "vwap", "mix", "bybit"]      # the rest as it was
    assert out["nav"][0] == ["봇별", ["바이비트 봇", "레인지 봇", "VWAP 개선판", "친구 15분 봇", "V3.9 투비트", "추세판단 봇"]]
    assert out["screens"] == [["추세판단 봇", "bots", "livebots"], ["레인지 봇", "bots", "livebots"], ["VWAP 개선판", "bots", "livebots"], ["친구 15분 봇", "bots", "livebots"],
                              ["V3.9 투비트", "bots", "livebots"]]
    assert out["keys"][:7] == ["bybitbot", "rangebot", "vwapbot", "mixbot", "v39", "trendbot", "trend"] and out["land"] == "hq"
    assert out["parse"]["name"] == "v39" and out["href"] == "#/mixbot" and out["icon"] > 20
    lb = FW._read(SCREENS, "livebots.js")
    for t, label in (("trendbot", "추세판단 봇"), ("vwapbot", "VWAP 개선판"), ("mixbot", "친구 15분 봇"), ("v39", "V3.9 투비트")):
        assert f'{{id: "{t}", label: "{label}"' in lb
    assert 'import {v39View} from "./livebots-v39.js";' in lb
    search = FW._read(V4, "core", "search.js").split("export const LIVE_ALIAS")[1]
    assert all(f"{k}:" in search for k in ("trendbot", "vwapbot", "mixbot", "v39"))
    assert ".botbar { grid-template-columns: repeat(8, minmax(0, 1fr)); }" in FW._read(ROOT, "paperbot", "dash", "static", "live", "live.css")


def test_each_bot_screen_names_its_own_executors_only(w, tmp_path):
    """The strip and the head of a 봇별 screen (screens/livebots.js mount): 추세판단 봇 with 바이비트 · WOO X Pro only, V3.9
    투비트 with 투비트 only (꺼짐 while it is not on the summary), 친구 15분 봇 with none of the executors; the empty 목표 연구
    foot with its bot, and in it the 목표 연구 section (screens/livebots-goalres.js) asking for that bot's own answer."""
    summary = {"execs": [{"id": "bybit", "bot": "paper", "name_ko": "바이비트"}, {"id": "mexc", "bot": "paper", "name_ko": "WOO X Pro"},
                         {"id": "deepcoin", "bot": "paper2", "name_ko": "딥코인"}, {"id": "toobit", "bot": None, "name_ko": "투비트"}],
               "accts": [{"id": "paper", "kind": "paper", "state": "ok", "balance": 1000.0},
                         {"id": "bybit", "kind": "live", "state": "ok", "balance": 101.5, "position": None},
                         {"id": "mexc", "kind": "live", "state": "ok", "balance": 102.8, "position": None},
                         {"id": "deepcoin", "kind": "live", "state": "ok", "balance": 77.7, "position": None},
                         {"id": "toobit", "kind": "live", "state": "ok", "balance": 47.6, "position": None}],
               "papers": None, "now_ms": NOW}
    no_tb = {**summary, "execs": summary["execs"][:3], "accts": summary["accts"][:4]}
    v39 = json_finite(X.build(w["p"], NOW))
    out = _node(tmp_path, f"""
    for (const [k, f] of Object.entries({{after: (p, i, x) => p.childNodes.splice(i + 1, 0, x), before: (p, i, x) => p.childNodes.splice(i, 0, x),
      replaceWith: (p, i, x) => p.childNodes.splice(i, 1, x)}})) if (!Node.prototype[k]) Node.prototype[k] = function (x) {{
      const p = this.parentNode; if (!p) return; f(p, p.childNodes.indexOf(this), x); x.parentNode = p; }};
    const K = await import('file://{SCREENS}/livebots-kit.js');
    const LB = await import('file://{SCREENS}/livebots.js');
    const asked = [];
    const mk = (tab, sum) => ({{params: {{arg: tab, query: {{}}}}, alive: () => true, track() {{}}, listen() {{}}, on() {{}}, watch() {{}}, timeout() {{}},
      href: (n) => '#/' + n, setTitle() {{}}, go() {{}}, every() {{}},
      api: async (path) => {{ asked.push(path); const a = {{'/api/v4/livebots': sum, '/api/v4/livebots/v39': D_v}}[path];
        if (a === undefined) throw Object.assign(new Error('x'), {{status: 503}}); return JSON.parse(JSON.stringify(a)); }}}});
    const strip = async (tab, sum) => {{ const el = new Node('div'); await LB.mount(el, mk(tab, sum)); await tick(); await tick();
      const w = D.walk(el); return {{text: w.text.replace(/\\s+/g, ' '), goal: w.classes.filter((c) => c.split(' ').includes('lb-goalres')).length,
        lgr: w.classes.filter((c) => c.split(' ').includes('lgr')).length}}; }};
    const r = {{trend: await strip('trendbot', D_s), vwap: await strip('vwapbot', D_s), mix: await strip('mixbot', D_s), v39: await strip('v39', D_s),
      v39off: await strip('v39', D_n), old: await strip('hq', D_s)}};
    console.log(JSON.stringify({{r, asked, fol: [K.followersOf(D_s, 'paper'), K.followersOf(D_s, 'paper2'), K.followersOf(null, 'paper')],
      tabs: Object.fromEntries(Object.entries(LB.BOT_TAB).map(([k, v]) => [k, v.bot]))}}));""", s=summary, n=no_tb, v=v39)
    assert out["fol"] == [["bybit", "mexc"], ["deepcoin"], []]
    assert out["tabs"] == {"bybitbot": "bybit", "trendbot": "trend", "rangebot": "range", "vwapbot": "vwap", "mixbot": "mix", "v39": "v39"}
    r = out["r"]
    head = lambda t: t.split("보기만 하는 화면(주문 버튼 없음)")[0]       # the strip, before its last words
    assert "바이비트 $101.50" in head(r["trend"]["text"]) and "WOO X Pro $102.80" in head(r["trend"]["text"])
    assert "딥코인" not in head(r["trend"]["text"]) and "투비트" not in head(r["trend"]["text"])
    assert "추세판단 봇 페이퍼(연습)와 그 봇을 따라가는 바이비트 · WOO X Pro 실행기(진짜 돈) · 다른 봇은 이 화면에 없어요" in r["trend"]["text"]
    assert "딥코인 $77.70" in head(r["vwap"]["text"]) and "바이비트" not in head(r["vwap"]["text"])
    assert "친구 15분 봇은 WOO X Pro 두 번째 계정에서 거래해요" in r["mix"]["text"] and "바이비트" not in head(r["mix"]["text"])
    assert "투비트 $47.60" in head(r["v39"]["text"]) and "바이비트" not in head(r["v39"]["text"])
    assert "투비트 실행기는 아직 꺼져 있어요" in r["v39off"]["text"]
    assert "바이비트 $101.50" in r["old"]["text"] and "딥코인 $77.70" in r["old"]["text"]          # the old screens as they were
    assert [r[k]["goal"] for k in ("trend", "vwap", "mix", "v39", "old")] == [1, 1, 1, 1, 0]
    assert [r[k]["lgr"] for k in ("trend", "vwap", "mix", "v39", "old")] == [1, 1, 1, 1, 0]
    assert all(f"/api/v4/livebots/goalres?bot={b}" in out["asked"] for b in ("trend", "vwap", "mix", "v39"))
    assert "목표 연구" in r["trend"]["text"] and "목표 연구" not in r["old"]["text"]


def test_the_v39_view_in_node(w, tmp_path):
    on = json_finite(X.build(w["p"], NOW))
    off = json_finite(X.build(_off(tmp_path), NOW))
    out = _node(tmp_path, f"""
    const X = await import('file://{SCREENS}/livebots-v39.js');
    const mkCtx = (a) => ({{params: {{query: {{}}}}, alive: () => true, track() {{}}, listen() {{}}, on() {{}}, watch() {{}}, href: (n) => '#/' + n,
      every() {{}}, api: async () => JSON.parse(JSON.stringify(a))}});
    const run = async (a) => {{ const v = X.v39View(mkCtx(a)); await tick(); await tick(); return texts(v.el); }};
    const p = D_on.position;
    console.log(JSON.stringify({{on: await run(D_on), off: await run(D_off),
      st: [X.statusOf(D_on.status, D_on.now_ms), X.statusOf(D_off.status, D_on.now_ms), X.statusOf({{...D_on.status, state: 'stopped'}}, D_on.now_ms)],
      step: [X.stepKo(p), X.stepKo({{step: 0}}), X.nextKo(p), X.nextKo({{next: null}})],
      fol: D_on.follow.rows.map((r) => X.followKo(r)), paper: D_on.follow.rows.map((r) => X.paperKo(r)),
      pnl: [X.pnlKo(0.026), X.pnlKo(-0.13), X.pnlKo(null)]}}));""", on=on, off=off)
    a = out["on"]
    for word in ("진짜 돈 · 투비트 실행기 · 규칙봇 V3.9 1시간 페이퍼(V39_ALL@1h)를 따라가요", "V3.9 투비트", "켜짐", "페이퍼 V39_ALL@1h가 진입하면 따라 들어가요",
                 "처음 켬 10/25 09:00", "투비트 잔고 (실거래)", "처음 잔고 대비", "오늘 (한국 시간)", "오늘 닫힌 거래 없음", "실거래 성적", "1승 1패",
                 "표본 적음", "페이퍼 V39 지갑", "모의 · 진짜 돈 아님",
                 "계획", "1단계", "12% → 10%", "17% → 15%", "22% → 20%", "BTC 40배 · 나머지 30배", "2.5 ATR", "증거금 = 그때 투비트 잔고의 40%",
                 "미국 경제 발표(CPI·FOMC·NFP·PCE) 앞뒤 30분은 새 진입 안 함", "강제청산 가격보다 멀면 그 진입은 안 함",
                 "나스닥 개장 앞 30분·뒤 30분은 새 진입 안 함",
                 "지금 포지션", "DOGE", "30배 격리", "계단 1단계 · 순ROE 17% 잠금", "가장 좋았던 순ROE +21%",
                 "순ROE 25% (0.21195)에 닿으면 손절을 순ROE 22% (0.21160)로", "잠금선", "강제청산 (어림)", "페이퍼 V39:",
                 "페이퍼 V39 진입 vs 실거래", "따라 들어감 2", "같이 들고 있음 1", "안 들어감 2", "실행기 시작 전 1",
                 L.WHY_KO["liq_skip"], L.WHY_KO["macro_skip"], "실거래 페이퍼 따라 청산", "페이퍼 손절", "페이퍼 잠금 익절",
                 "오늘 · 최근 실거래", "ETH 숏 30배", "BTC 롱 30배", "잔고", "처음", "$50.00", "정한 금액",
                 "주의 · 긴급 기록", "손절 옮기기 실패", "DOGEUSDT 손절 옮기기 실패: timeout"):
        assert word in a, (word, a)
    assert not BAD.search(a), BAD.search(a)
    b = out["off"]
    for word in ("꺼짐", "아직 꺼져 있어요", "서버에 설정 파일도 기록 파일도 아직 없어요", "docs/toobit-ko.md의 '실행기 켜기' → '켜는 순서'",
                 "그 전에는 숫자를 만들지 않아요", "저장소의 설정 원본", "12% → 10%", "17% → 15%", "실행기 꺼짐", "실행기가 아직 꺼져 있어요"):
        assert word in b, word
    assert "투비트 잔고 (실거래)" not in b and "실거래 성적" not in b and "처음 잔고 대비" not in b and not BAD.search(b)
    assert not re.search(r"\$\d", b.split("계획")[0].replace("$50", ""))                     # no money before the plan's own $50
    st = out["st"]
    assert (st[0]["cls"], st[0]["pill"], st[0]["hint"]) == ("run", "켜짐", "")
    assert st[1]["cls"] == "off" and st[1]["line"].startswith("아직 꺼져 있어요") and "실행기 켜기" in st[1]["hint"]
    assert st[2]["hint"] == "서버에서 systemctl status paperbot-executor-toobit"
    assert out["step"][:2] == ["계단 1단계 · 순ROE 17% 잠금", "처음 손절 (계단 전)"] and "다음 계단은" in out["step"][3]
    pills = {f["pill"] for f in out["fol"]}
    assert {"따라 들어감", "같이 들고 있음", "안 들어감", "실행기 시작 전"} <= pills
    assert "페이퍼 아직 열림" in out["paper"] and out["pnl"] == ["+$0.026", "−$0.130", "모름"]


def test_the_files_keep_the_house_rules():
    FW.house_rules("livebots-v39", "l39")
    js = FW._read(SCREENS, "livebots-v39.js")
    assert '"/api/v4/livebots/v39"' in js
    assert '@import url("livebots-v39.css");' in FW._read(SCREENS, "livebots.css")
    assert re.search(r'^MODULES = MODULES \+ \("livev39",\)$', FW._read(ROOT, "paperbot", "livedash", "app.py"), re.M)
    inv = FW._read(V4, "INVENTORY.md")
    assert "실거래 › 봇별" in inv and "/api/v4/livebots/v39" in inv and "livebots-v39.js" in inv
    # read-only: the module never opens a file to write, never runs a command, never reads a key file
    src = FW._read(ROOT, "paperbot", "dash", "more", "livev39.py")
    assert not re.search(r"open\([^)]*['\"][wa]b?['\"]", src) and "subprocess" not in src and ".unlink(" not in src
    assert ".env" not in src.replace("os.environ", "")
