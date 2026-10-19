"""실거래 (#/livebots; /api/v4/livebots*, dash/more/livebots.py; screens/livebots*.js). Read-only views of the two live order
executors (바이비트, MEXC) and the paper account both follow (COMBO@mix in live-ac.db). tests/livebots_world.py builds every
database with the bots' own schema code (paperbot.store3.Store3, paperbot.executor.ExecStore), never a copy of it.

- the terminal's answer (요약): the three accounts (balance, the change since the first balance record without deposits,
  halt, the open position with the paper's next ladder step and its price, today, hourly P&L, the month calendar), the
  fills (entries and exits, a live close that followed the paper takes the paper's reason, a fired stop above the entry is
  a lock), the lights (the executor's own rule), the 40-trade checkpoint, the risk limits a config really has
- honest states: no file / no table = missing (수집 전), an unreadable file or config = error with its reason (never 0)
- read-only: the files are only read (bytes unchanged), the key file next to the configs is never opened
- the page: the calc functions and the cards in node (the tiny DOM), the wiring (route, menu, 찾기, inventory, env example),
  the terminal's optional hooks (the rule bot's terminal passes none)
"""
import builtins
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot.dash import more as MORE  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from test_dash import SECRET, _store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
PW = "correct horse battery"
NOW = W.NOW
H, MIN = W.H, W.MIN


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _fresh_cache():
    L._cache.clear()
    yield
    L._cache.clear()


@pytest.fixture
def world(tmp_path):
    return W.build_world(str(tmp_path / "w"))


def acct(d, i):
    return next(a for a in d["accts"] if a["id"] == i)


def ex(d, i):
    return next(x for x in d["execs"] if x["id"] == i)


# ---------------------------------------------------------------- the terminal's answer on the standard world
def test_the_three_accounts(world):
    d = L.build(world, NOW)
    p, b, m = acct(d, "paper"), acct(d, "bybit"), acct(d, "mexc")
    assert [a["id"] for a in d["accts"]] == ["paper", "bybit", "mexc"] and all(a["state"] == "ok" for a in d["accts"])
    # paper: wallet 1,000 + 20 + 15 - 60 + 10 + 12 + 8 = 1,005; its open BTC long, locked at +10 %
    assert p["kind"] == "paper" and p["balance"] == 1005.0 and p["initial"] == 1000.0 and p["halted"] is False
    assert p["stats"]["trades"] == 6 and p["stats"]["wins"] == 5 and abs(p["stats"]["pnl"] - 5.0) < 1e-9
    pos = p["position"]
    assert pos["symbol"] == "BTCUSDT" and pos["side"] == 1 and pos["leverage"] == 40 and pos["entry"] == 62000.0
    assert pos["stop"] == 62200.0 and pos["stop_initial"] == 61000.0 and pos["locked"] is True and pos["liq"] == 60600.0
    # the next ladder step: lock 10 % -> 13 % armed at net ROE 14 %; price = entry x (1 + side x (roe / lev + round trip + funding frac))
    rt, ff = pos["round_trip"], 0.5 / (0.25 * 62000.0)
    assert abs(pos["funding_frac"] - ff) < 1e-12 and abs(pos["next_lock"]["lock"] - 0.13) < 1e-12 and abs(pos["next_lock"]["at"] - 0.14) < 1e-12
    assert abs(pos["next_lock"]["price"] - 62000.0 * (1 + (0.14 / 40 + rt + ff))) < 1e-6
    assert pos["member"] == "S2_ST_ROC@1h#1~abc123" and pos["member_order"] == 1 and pos["key"] == f"COMBO@mix|BTCUSDT|{W.T0 + 9 * H}"
    # bybit: balance = the executor's last equity; the change is counted from its first balance record (100.0)
    assert b["kind"] == "live" and b["balance"] == 101.5 and b["initial"] == 100.0 and b["initial_ts"] == W.T0 + 2 * H
    assert b["halted"] is False and b["consecutive_losses"] == 1 and b["max_consecutive_losses"] == 3
    lp = b["position"]
    assert lp["entry"] == 62010.0 and lp["stop"] == 62210.0 and lp["locked"] is True and lp["liq"] is None
    assert abs(lp["margin"] - 62010.0 * 0.025 / 40) < 1e-9
    assert lp["next_lock"]["from"] == "paper" and lp["next_lock"]["price"] == pos["next_lock"]["price"]       # it follows that paper position
    # mexc: halted after three losses, flat, one balance sample
    assert m["halted"] is True and m["halt_reason"] == "연속 손실 3번" and m["halted_ts"] == W.T0 + 8 * H and m["position"] is None
    assert m["balance"] == 102.8 and m["initial"] == 102.8 and m["stats"]["trades"] == 3


def test_today_hours_and_the_month_calendar(world):
    d = L.build(world, NOW)
    p, b = acct(d, "paper"), acct(d, "bybit")
    assert p["today"]["trades"] == 6 and p["today"]["wins"] == 5 and p["today"]["losses"] == 1
    assert p["today"]["from_ms"] == W.T0 - 9 * H                                # 00:00 KST of 10/19
    # bybit's trade one day before the paper database (10/18 KST) is not today's
    assert b["today"]["trades"] == 4 and abs(b["today"]["pnl"] - (1.4 - 6.3 + 0.7 - 2.0)) < 1e-9
    # an hour holds the trades that closed in (start, end]: the paper's t1 closed at T0 + 1h40 -> the hour ending T0 + 2h
    assert p["hours"][0] == [W.T0 + 2 * H, 20.0, 1, 1, 0] and len(p["hours"]) == 6
    assert sum(h_[1] for h_ in b["hours"]) == pytest.approx(3.0 + 1.4 - 6.3 + 0.7 - 2.0)
    cal = b["calendar"]["days"]
    assert len(cal) == 31 and cal[0]["d"] == "2026-10-01" and cal[0]["dow"] == 3          # 10/01/2026 is a Thursday (0 = Monday)
    by = {c["d"]: c for c in cal}
    assert by["2026-10-19"]["state"] == "today" and by["2026-10-20"]["state"] == "future"
    assert by["2026-10-18"]["state"] == "done" and by["2026-10-18"]["g"]["bybit"] == {"pnl": 3.0, "trades": 1, "wins": 1}
    assert by["2026-10-17"]["state"] == "empty" and "g" not in by["2026-10-17"]          # before any record: no record, never a zero
    assert "g" not in by["2026-10-01"]


def test_fills_name_entries_and_exits_with_their_real_reasons(world):
    d = L.build(world, NOW)
    f = d["fills"]
    assert [x["t"] for x in f] == sorted((x["t"] for x in f), reverse=True)            # newest first
    first = f[:2]
    assert {x["acct"] for x in first} == {"bybit", "paper"} and all(x["kind"] == "entry" and x.get("open") for x in first)
    by = {x["key"]: x for x in f}
    px = by[f"paper:x:{6}"]
    assert px["reason"] == "LOCK" and px["reason_ko"] == "잠금 익절" and px["pnl"] == 8.0
    # the executors closed because the paper closed: the matched paper trade's reason (LOCK / SL) is the live one's
    bx = [x for x in f if x["acct"] == "bybit" and x["kind"] == "exit"]
    assert sorted((x["symbol"], x["reason"]) for x in bx) == [("BCHUSDT", "LOCK"), ("BTCUSDT", "PAPER"), ("ETHUSDT", "LOCK"), ("ETHUSDT", "PAPER"),
                                                              ("SOLUSDT", "SL")]        # the day-before ETH trade has no paper partner here
    btc = next(x for x in bx if x["symbol"] == "BTCUSDT")
    assert btc["reason_ko"] == "페이퍼 따라 청산" and btc["est"] is True                    # no paper trade, wallet estimate
    assert len(f) <= L.FILLS_KEEP


def test_live_exit_reasons_come_from_the_executors_own_words():
    assert L.live_exit("거래소 손절(또는 잠금) 발동", {"stop": 101.0}, 1, 100.0) == "LOCK"
    assert L.live_exit("거래소 손절(또는 잠금) 발동", {"stop": 99.0}, 1, 100.0) == "SL"
    assert L.live_exit("거래소 손절(또는 잠금) 발동", {"stop": 99.0}, -1, 100.0) == "LOCK"           # a short's lock is below the entry
    assert L.live_exit("손절/잠금 가격이 이미 지나 시장가로 닫음", {"stop": 98.0}, 1, 100.0) == "SL"
    assert L.live_exit("paper 청산 → 거래소 포지션 닫기", {}, 1, 100.0) == "PAPER"
    assert L.live_exit("거래소에서 포지션이 닫혔습니다(이유 미확인)", {}, 1, 100.0) == "OTHER"
    assert L.live_exit("비상 정지 파일이 있습니다", {}, 1, 100.0) == "HALT"


def test_match_takes_the_closest_pairs_within_five_minutes_once_each():
    paper = [{"id": 1, "symbol": "ETHUSDT", "side": 1, "entry_time": 1000}, {"id": 2, "symbol": "ETHUSDT", "side": 1, "entry_time": 1000 + 3 * MIN},
             {"id": 3, "symbol": "ETHUSDT", "side": -1, "entry_time": 1000}]
    live = [{"key": "a", "symbol": "ETHUSDT", "side": 1, "paper_time": 1000 + 2 * MIN},
            {"key": "b", "symbol": "ETHUSDT", "side": 1, "paper_time": 1000 + 10 * MIN},
            {"key": "c", "symbol": "ETHUSDT", "side": 1, "paper_time": 1000 - 1}]
    assert L.match(paper, live) == {"c": 1, "a": 2}                     # b is 7 minutes off; the short never pairs with a long


def test_lights_follow_the_executors_rule(tmp_path):
    d = L.build(W.build_world(str(tmp_path / "a")), NOW)
    b, m = ex(d, "bybit")["light"], ex(d, "mexc")["light"]
    assert b["state"] == "building" and b["have"] == 6 and b["need_more"] == 14 and b["min_win"] == 0.85 and m["min_win"] == 0.9
    assert b["last_event"] is None
    # 20 closed trades, 17 won: 85 % holds for bybit (17 >= 17), not for MEXC (needs 18 of 20)
    p = W.build_world(str(tmp_path / "b"))
    os.remove(p["paper"])
    W.paper_db(p["paper"], extra_wins=[True] * 12 + [False] * 2)                # 6 (5 won) + 14 (12 won) = 20 trades, 17 won
    d = L.build(p, NOW)
    b, m = ex(d, "bybit")["light"], ex(d, "mexc")["light"]
    assert b["have"] == 20 and b["wins"] == 17 and b["state"] == "green" and b["next_loss_red"] is True    # the oldest (t1) is a win
    assert m["state"] == "red" and m["need_wins"] == 18 and m["next_win_green"] is False
    assert b["recent"][:2] == [False, False] and b["recent"][-1] is True                                      # newest first
    assert L.light(20, 0.85, [1.0] * 17 + [-1.0] * 3)["state"] == "green"
    lt = L.light(20, 0.85, [1.0] * 17 + [-1.0] * 3)
    assert lt["need_wins"] == 17 and lt["spare"] == 0 and lt["next_loss_red"] is False      # the oldest is a loss: a new loss keeps 17
    assert L.light(20, 0.85, [-1.0] * 3 + [1.0] * 17)["next_loss_red"] is True             # the oldest is a win: a new loss leaves 16
    assert L.light(20, 0.9, [1.0] * 17 + [-1.0] * 3)["state"] == "red"
    assert L.light(0, 0.85, [])["state"] == "off"
    assert L.need_wins(20, 0.85) == 17 and L.need_wins(20, 0.9) == 18


def test_the_checkpoint_waits_for_forty_trades():
    cp = L.checkpoint([{"pnl": 1.0}] * 30)
    assert cp["n"] == 30 and cp["left"] == 10 and cp["ready"] is False and cp["zone"] is None
    cp = L.checkpoint([{"pnl": -1.0}] * 5 + [{"pnl": 1.0}] * 36)              # 41 trades; the last 40: 4 losses, 36 wins = 90 %
    assert cp["ready"] and cp["left"] == 0 and cp["zone"] == "up" and cp["last_win_rate"] == pytest.approx(36 / 40)
    assert L.checkpoint([{"pnl": -1.0}] * 6 + [{"pnl": 1.0}] * 34)["zone"] == "mid"       # 85 %
    assert L.checkpoint([{"pnl": -1.0}] * 8 + [{"pnl": 1.0}] * 32)["zone"] == "low"       # 80 %


def test_only_the_risk_limits_a_config_has_are_listed(world, tmp_path):
    d = L.build(world, NOW)
    keys = [x["key"] for x in ex(d, "bybit")["config"]["limits"]]
    assert keys == ["max_consecutive_losses", "max_drawdown_pct", "max_loss_frac", "max_leverage", "max_notional_usd", "allowed_symbols"]
    ko = " ".join(x["ko"] for x in ex(d, "bybit")["config"]["limits"])
    assert "3연패" in ko and "50%" in ko and "35%" in ko and "40배" in ko and "$40" not in ko and "정한 금액" not in ko
    # a config that still has the daily limit and the money set aside lists them
    cfg = str(tmp_path / "x.json")
    W.config(cfg, world["bybit_db"], world["paper"], "bybit", 0.85, "/nonexistent/STOP", extra={"budget_usd": 100})
    with open(cfg, encoding="utf-8") as fh:
        raw = json.load(fh)
    raw["risk"]["daily_max_loss_usd"] = 40
    with open(cfg, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)
    c = L.read_config(cfg)
    assert [x["key"] for x in c["limits"]][2] == "daily_max_loss_usd" and "하루 $40" in c["limits"][2]["ko"]
    assert c["limits"][-1]["key"] == "budget_usd" and c["kill_file"] == {"path": "/nonexistent/STOP", "present": False}


def test_the_kill_file_is_seen(world):
    open(os.path.join(os.path.dirname(world["paper"]), "STOP"), "w").close()
    d = L.build(world, NOW)
    assert acct(d, "bybit")["kill_file"]["present"] is True


# ---------------------------------------------------------------- honest states
def test_nothing_there_yet_is_missing_never_zero(tmp_path):
    p = {k: str(tmp_path / f"{k}.db") for k in L.ENV}
    d = L.build(p, NOW)
    assert [a["state"] for a in d["accts"]] == ["missing", "missing", "missing"]
    assert all("balance" not in a and "stats" not in a for a in d["accts"])
    assert d["fills"] == [] and d["checkpoint"] is None and all(x["light"]["state"] == "unknown" for x in d["execs"])
    assert d["paper"]["reason_ko"] == L.MISSING_KO


def test_a_file_without_the_tables_is_missing_and_garbage_is_an_error(tmp_path, world):
    sqlite3.connect(world["mexc_db"] + ".empty").close()
    with open(world["paper"], "wb") as fh:
        fh.write(b"garbage" * 200)
    p = dict(world, mexc_db=world["mexc_db"] + ".empty")
    d = L.build(p, NOW)
    pa, m = acct(d, "paper"), acct(d, "mexc")
    assert pa["state"] == "error" and "망가졌" in pa["reason_ko"] and "DatabaseError" in pa["reason"]
    assert m["state"] == "missing" and m["reason_ko"] == L.NO_TABLE_KO
    assert acct(d, "bybit")["state"] == "ok"                              # one source failing never hides the others
    assert ex(d, "bybit")["light"]["state"] == "unknown" and "페이퍼 기록을 읽지 못해" in ex(d, "bybit")["light"]["reason_ko"]


def test_a_broken_config_says_so(world):
    with open(world["mexc_config"], "w", encoding="utf-8") as fh:
        fh.write("{not json")
    d = L.build(world, NOW)
    x = ex(d, "mexc")
    assert x["config"]["state"] == "error" and "JSON" in x["config"]["reason_ko"] and x["light"]["state"] == "unknown"
    assert acct(d, "mexc")["state"] == "ok"                               # its database is still read


def test_files_are_only_read_and_the_key_file_is_never_opened(world, monkeypatch):
    env = os.path.join(os.path.dirname(world["bybit_config"]), "executor.env")
    with open(env, "w", encoding="utf-8") as fh:
        fh.write("BYBIT_LIVE_KEY=secret-key-123\n")
    before = {k: open(v, "rb").read() for k, v in world.items()}
    real = builtins.open

    def guarded(path, *a, **k):
        assert not str(path).endswith(".env"), path
        return real(path, *a, **k)
    monkeypatch.setattr(builtins, "open", guarded)
    out = json.dumps(L.build(world, NOW), ensure_ascii=False)
    monkeypatch.setattr(builtins, "open", real)
    assert "secret-key-123" not in out
    assert {k: open(v, "rb").read() for k, v in world.items()} == before


# ---------------------------------------------------------------- the route
@pytest.fixture
def client(tmp_path, world, monkeypatch):
    for k, v in W.env_of(world).items():
        monkeypatch.setenv(k, v)
    base = tmp_path / "data"
    base.mkdir()
    dbp = str(base / "paper3.db")
    _store(dbp).close()
    app = create_app(dbp, hash_password(PW), SECRET, candles=lambda s, i, n: [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}])
    return TestClient(app)


def test_the_route_is_behind_the_login_and_answers(client):
    r = client.get("/api/v4/livebots", follow_redirects=False)
    assert r.status_code in (401, 302, 307)
    assert client.post("/api/login", json={"password": PW}).status_code == 200
    d = client.get("/api/v4/livebots").json()
    assert [a["id"] for a in d["accts"]] == ["paper", "bybit", "mexc"] and d["account"] == "COMBO@mix"
    assert "trades" not in d["paper"]["accounts"]["COMBO@mix"] and all("trades" not in x["record"] for x in d["execs"])
    assert d["refs"]["backtest"] == 0.91 and d["checkpoint"]["trades"] == 40


def test_env_vars_choose_the_files():
    p = L.paths({"PAPERBOT_LIVE_PAPER_DB": "/x/p.db"})
    assert p["paper"] == "/x/p.db" and p["bybit_db"] == "/var/lib/paperbot/exec/executor-bybit-live.db"
    assert p["mexc_config"] == "/etc/paperbot/executor-mexc.json"
    example = _read(ROOT, "deploy", "dash.env.example")
    for var, _default in list(L.ENV.values()) + list(L.ENV_MORE.values()):
        assert f"#{var}=" in example, var


# ---------------------------------------------------------------- the page: pure functions in node
def _node(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    script = f"const C = await import('file://{SCREENS}/livebots-calc.js');\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_calc_in_node(world):
    d = L.build(world, NOW)
    out = _node(f"""const d = {json.dumps(d)};
    const p = d.accts[0].position, b = d.accts[1].position;
    console.log(JSON.stringify({{
      u: C.unrealized(b, 62510), roe: C.roeAt(b, 62510), net: C.netRoe(p, 62500), price: C.roePrice(1, 62000, 40, 0.14, p.round_trip, p.funding_frac),
      none: [C.unrealized(b, null), C.roeAt(null, 1), C.netRoe(p, 0)],
      cnt: C.coinCounts(d.accts, () => 62510), keys: [...C.posKeys(d.accts, "BTCUSDT")], today: C.liveToday(d.accts),
      w: C.lightWords(d.execs[0].light), cells: C.lightCells(d.execs[0].light),
      fresh0: C.freshFills(null, d.fills).fresh.length, fresh1: C.freshFills(new Set(d.fills.slice(1).map((f) => f.key)), d.fills).fresh.map((f) => f.key),
      snd: d.fills.map(C.fillSound),
      al: C.alarms({{execs: [{{id: "mexc", light: {{state: "green"}}, record: {{state: "ok", halted: false}}}}]}}, {{execs: [{{id: "mexc", light: {{state: "red"}}, record: {{state: "ok", halted: true}}}}]}}),
      al0: C.alarms(null, d), al1: C.alarms(d, d),
    }}));""")
    assert out["u"] == pytest.approx(0.025 * 500) and out["roe"] == pytest.approx(0.025 * 500 / (62010 * 0.025 / 40))
    p = acct(d, "paper")["position"]
    assert out["net"] == pytest.approx(40 * ((62500 / 62000 - 1) - p["round_trip"] - p["funding_frac"]))
    assert out["price"] == pytest.approx(p["next_lock"]["price"]) and out["none"] == [None, None, None]
    assert [x["id"] for x in out["cnt"]["BTCUSDT"]] == ["paper", "bybit"] and len(out["keys"]) == 2
    assert out["today"]["trades"] == 7 and out["today"]["pnl"] == pytest.approx(-6.2 + 2.8)
    assert out["w"]["tone"] == "wait" and out["w"]["short"] == "근거 쌓는 중 6/20" and "14번 더" in out["w"]["line"]
    assert len(out["cells"]) == 20 and out["cells"][:14] == [None] * 14 and out["cells"][14:] == [True, True, False, True, True, True]
    assert out["fresh0"] == 0 and out["fresh1"] == [d["fills"][0]["key"]]                 # the first look is the past, never new
    assert set(out["snd"]) <= {"lv_entry", "lv_tp", "lv_sl", None} and out["snd"][0] == "lv_entry"
    assert out["al"] == [{"id": "mexc", "what": "red"}, {"id": "mexc", "what": "halt"}] and out["al0"] == [] and out["al1"] == []


# ---------------------------------------------------------------- the page: cards and lines in node (the tiny DOM)
def _render(call: str, data: dict) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\n"
              f"const K = await import('file://{SCREENS}/livebots-kit.js'); const P = await import('file://{SCREENS}/livebots-parts.js');\n"
              f"const {{ui}} = await import('file://{V4}/core/pb.js');\n"
              f"const d = {json.dumps(data)}; const ctx = {{href: (n, a, q) => '#/' + n + (a ? '/' + a : ''), alive: () => true, track() {{}}, every() {{}}, on() {{}}}};\n"
              f"const out = ({call});\n"
              "console.log(JSON.stringify(Array.isArray(out) && out.length && !(out[0] instanceof Node) ? {json: out} : D.walk(out)));")
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    if "text" in out:
        out["text"] = re.sub(r"\s+", " ", out["text"])
    return out


def test_chart_lines_entry_stop_first_stop_and_next_lock(world):
    d = L.build(world, NOW)
    out = _render("K.liveLines(d.accts, 'BTCUSDT', 62510)", d)["json"]
    ids = [x["id"] for x in out]
    assert ids[0] == "lv:e:bybit,paper"                                   # one entry line for the paper and the executor that followed it
    assert set(ids[1:]) == {"lv:s:bybit", "lv:s:paper", "lv:f:paper", "lv:n:paper"}
    by = {x["id"]: x for x in out}
    nl = acct(d, "paper")["position"]["next_lock"]
    assert by["lv:n:paper"]["price"] == pytest.approx(nl["price"]) and by["lv:n:paper"]["label"] == "다음 잠금 14%"
    assert by["lv:f:paper"]["price"] == 61000.0 and by["lv:s:bybit"]["label"] == "B 잠금" and by["lv:s:bybit"]["tone"] == "up"
    pill = by["lv:e:bybit,paper"]["pill"]
    assert pill["text"].startswith("B·P 롱 40배") and "잠금" in pill["text"] and len(pill["chips"][0]["ids"]) == 4
    assert _render("K.liveLines(d.accts, 'ETHUSDT', 2500)", d)["text"] == ""          # no position on that coin: no line


def test_account_cards_say_halt_and_never_print_null(world):
    d = L.build(world, NOW)
    t = _render("d.accts.map((a) => K.acctCard(a, ui.ledBar({label: a.id}), []))", d)["text"]
    assert "null" not in t and "undefined" not in t
    assert "멈춤: 연속 손실 3번" in t and "사람이 풀 때까지 새 진입 없음" in t and "멈춤 아님" in t and "연속 손실 1번 (한도 3)" in t
    assert "실거래 · 거래소 실제 체결" in t and "모의 · 실제 시세" in t                     # each money keeps its own caption
    gone = L.build({k: "/nonexistent/" + k for k in L.ENV}, NOW)
    t = _render("d.accts.map((a) => K.acctCard(a, ui.ledBar({label: a.id}), []))", gone)["text"]
    assert t.count("수집 전") == 3 and "USDT" not in t and "0.00" not in t


def test_the_strip_and_the_lists(world):
    d = L.build(world, NOW)
    band = _render("(() => { const b = P.bandLine(ctx); b.set(d, 'ok'); return b.el; })()", d)["text"]
    assert "바이비트 $101.50" in band and "MEXC $102.80" in band and "오늘 실거래" in band and "7번 5승 2패" in band
    assert "근거 쌓는 중 6/20" in band and "멈춤 MEXC" in band and "40번 판단까지 34번 남음" in band and "페이퍼 6/40" in band
    fills = _render("(() => { const f = P.fillsPanel(ctx); f.set(d, 'ok'); return f.el; })()", d)["text"]
    assert "실거래 체결" in fills and "진입" in fills and "잠금" in fills and "손절" in fills and "+0.70" in fills
    wait = _render("(() => { const b = P.bandLine(ctx); b.set(null, 'failed'); return b.el; })()", d)["text"]
    assert "$" not in wait and "0.00" not in wait and "—" in wait          # nothing read: dashes, never a zero


# ---------------------------------------------------------------- 거래: the trade list with settings, reasons and partners
def test_trades_carry_the_setting_the_reason_and_the_partners(world, monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")            # the run's own config (in the database) is used
    t = L.trade_rows(world, NOW)
    assert t["combo_state"] == "ok" and t["members_n"] == 3
    paper = t["accts"]["paper"]
    assert paper["state"] == "ok" and paper["n"] == 6 and [r["symbol"] for r in paper["rows"]][:2] == ["BCHUSDT", "LTCUSDT"]     # newest first
    by = {r["symbol"]: r for r in paper["rows"]}
    sol = by["SOLUSDT"]                                                     # t3: S2_ST_ROC 30m = the config's 3rd setting
    assert sol["order"] == 3 and sol["member"] == "S2_ST_ROC@30m#3~abc123" and sol["exit_reason"] == "SL" and sol["reason_ko"] == "손절"
    assert sol["setting"]["stop"] == {"mode": "pct", "value": 2.0, "ko": "진입가의 2% (강제청산 안쪽으로 당김)"} and sol["setting"]["entry_ko"] == "즉시"
    bch = by["BCHUSDT"]                                                     # t6: N03 15m = the 2nd setting: 돌파 확인, 반대 방향, swing stop
    s2 = bch["setting"]
    assert s2["entry_ko"] == "돌파 확인" and s2["invert"] is True and s2["stop"]["mode"] == "swing" and s2["disp"] == "신호봉 높이 ATR 1.5배 이상"
    assert s2["off"] == [{"dim": "oi24", "dim_ko": "미결제약정", "value": 2, "ko": "미결제약정: 미결제약정 늘어남(+5% 위)"}]
    btc = by["BTCUSDT"]
    assert btc["setting"]["filter"] == [{"tag": "weekend", "value": 0, "ko": "평일만"}, {"tag": "session", "value": 0, "ko": "시간대 아시아(09-17시)"}]
    assert {o["ko"] for o in btc["setting"]["off"]} == {"시각: 05시", "코인x방향: DOGE 롱", "요일: 목요일"}     # symside 7 = DOGE (3) x 2 + long
    # what each executor did with each paper trade, from its own records
    assert bch["live"]["bybit"]["state"] == "matched" and bch["live"]["bybit"]["diff"] == pytest.approx(0.7 - 8.0 * 0.1)
    assert by["DOGEUSDT"]["live"]["bybit"] == {"state": "missed", "why_kind": "halted", "why_ko": "그때 실행기가 멈춰 있었어요"}
    assert by["LTCUSDT"]["live"]["mexc"]["why_kind"] == "late" and by["SOLUSDT"]["live"]["mexc"]["why_kind"] == "entry_check"
    assert "오늘 남은 손실 한도" in by["SOLUSDT"]["live"]["mexc"]["why_text"]
    assert by["LTCUSDT"]["live"]["bybit"]["why_kind"] is None and "이유가 없어요" in by["LTCUSDT"]["live"]["bybit"]["why_ko"]
    assert by["BTCUSDT"]["live"]["bybit"]["state"] == "before"           # the paper's t1 came before the executor started
    # a live trade: its paper partner, the entry slippage against it (in the trade's favour > 0) and the money difference
    m = {r["symbol"]: r for r in t["accts"]["mexc"]["rows"]}
    eth = m["ETHUSDT"]
    assert eth["exit_reason"] == "LOCK" and eth["paper"]["id"] == 2 and eth["slip_vs_paper"] == pytest.approx(0.0)
    assert eth["diff"] == pytest.approx(1.3 - 15.0 * 0.1) and eth["order"] == 2 and eth["setting"]["strategy"] == "N03_ADX_GC"
    assert m["BCHUSDT"]["gap_ms"] == 2 * MIN                               # matched though its key is 2 minutes off
    b = [r for r in t["accts"]["bybit"]["rows"] if r["symbol"] == "BTCUSDT"][0]
    assert b["paper"] is None and b["exit_reason"] == "PAPER" and b["diff"] is None and b["est"] is True


def test_trade_filters_in_node(world):
    rows = L.trade_rows(world, NOW)["accts"]["paper"]["rows"]
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"await import('{dom}'); const T = await import('file://{SCREENS}/livebots-trades.js'); const r = {json.dumps(rows)};\n"
              "console.log(JSON.stringify({w: T.filterRows(r, {res: 'win'}).length, l: T.filterRows(r, {res: 'loss'}).length,"
              " c: T.filterRows(r, {coin: 'BTCUSDT', res: 'all'}).length, s: T.filterRows(r, {strat: 'N03_ADX_GC', res: 'win'}).length}));")
    out = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"w": 5, "l": 1, "c": 1, "s": 3}


def test_trades_route(client):
    client.post("/api/login", json={"password": PW})
    d = client.get("/api/v4/livebots/trades").json()
    assert set(d["accts"]) == {"paper", "bybit", "mexc"} and d["accts"]["mexc"]["qty_scale"] == 0.1


# ---------------------------------------------------------------- wiring
def test_wiring_route_menu_find_inventory_and_module():
    routes = _read(V4, "core", "routes.js")
    assert 'livebots: {ko: "실거래", group: "home", title: "실거래"}' in routes and '"checkpoint", "livebots"]' in routes
    assert "livebots:" in _read(V4, "core", "search.js")
    assert "livebots" in MORE.MODULES
    js = "".join(_read(SCREENS, f) for f in os.listdir(SCREENS) if f.startswith("livebots") and f.endswith(".js"))
    assert '"/api/v4/livebots"' in js and '"/api/v4/livebots/trades"' in js
    tabs = re.findall(r'\{id: "(\w+)", label: "([^"]+)"', _read(SCREENS, "livebots.js"))
    assert tabs[:3] == [("summary", "요약"), ("chart", "차트"), ("trades", "거래")]
    inv = _read(V4, "INVENTORY.md")
    for word in ("#/livebots", "/api/v4/livebots", "PAPERBOT_LIVE_PAPER_DB", "PAPERBOT_LIVE_BYBIT_DB", "PAPERBOT_LIVE_MEXC_DB",
                 "PAPERBOT_LIVE_BYBIT_CONFIG", "PAPERBOT_LIVE_MEXC_CONFIG", "실거래 터미널"):
        assert word in inv, word
    css = _read(SCREENS, "livebots.css")
    assert '@import url("terminal.css");' in css and not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    assert not re.search(r"font-size:\s*\d", css)


def test_the_terminal_hooks_are_optional_and_the_rule_bots_terminal_passes_none():
    term = _read(SCREENS, "terminal.js")
    assert "termChart(ctx, st, (tf) => { st.tf = tf; local.set(\"term-tf\", tf); });" in term and "pnlPanel(ctx);" in term
    assert "watchList(ctx, st, pick);" in term
    chart = _read(SCREENS, "terminal-chart.js")
    assert "export function termChart(ctx, st, onTf, src = null)" in chart and "if (!src) {\n        try { chartPlus(" in chart
    assert "export function pnlPanel(ctx, src = null)" in _read(SCREENS, "terminal-pnl.js")
    assert "const marks = o.marks || coinMarks();" in _read(SCREENS, "terminal-feed.js")
    live = _read(SCREENS, "livebots-term.js")
    assert "termChart(ctx, st," in live and "pnlPanel(ctx, {" in live and "watchList(ctx, st, pick, {marks})" in live
    assert "topBar(ctx, st)" in live and "bigFeed(ctx)" in live and "liqFeed(ctx, st," in live and "consolePanel(" in live
