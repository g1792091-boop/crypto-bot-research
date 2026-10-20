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
              "if (!Node.prototype.after) Node.prototype.after = function (...xs) { const p = this.parentNode; if (!p) return;"
              " const i = p.childNodes.indexOf(this); for (const [j, x] of xs.entries()) { p.childNodes.splice(i + 1 + j, 0, x); x.parentNode = p; } };\n"
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
    assert "바이비트 $101.50" in band and "WOO X Pro $102.80" in band and "오늘 실거래" in band and "7번 5승 2패" in band
    assert "근거 쌓는 중 6/20" in band and "멈춤 MEXC" in band and "40번 판단까지 34번 남음" in band and "페이퍼(연습) 6/40" in band
    fills = _render("(() => { const f = P.fillsPanel(ctx); f.set(d, 'ok'); return f.el; })()", d)["text"]
    assert "실거래 체결" in fills and "진입" in fills and "잠금" in fills and "손절" in fills and "+0.70" in fills
    wait = _render("(() => { const b = P.bandLine(ctx); b.set(null, 'failed'); return b.el; })()", d)["text"]
    assert "$" not in wait and "0.00" not in wait and "—" in wait          # nothing read: dashes, never a zero
    gone = L.build({k: "/nonexistent/" + k for k in L.ENV}, NOW)
    for call in ("P.tablePanel(ctx, {sym: 'BTCUSDT'}, () => {})", "P.minePanel(ctx, {sym: 'BTCUSDT'})"):
        t = _render(f"(() => {{ const x = {call}; x.set(d, 'ok'); return x.el; }})()", gone)["text"]
        assert "수집 전" in t and "없어요" not in t and "0.00" not in t, (call, t)               # nothing read is not 'none'
    t = _render("(() => { const x = P.tablePanel(ctx, {sym: 'BTCUSDT'}, () => {}); x.set(d, 'ok'); return x.el; })()", d)["text"]
    assert "페이퍼" in t and "바이비트" in t and "62,010.0" in t and "잠금 62,210.0" in t


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


# ---------------------------------------------------------------- 신호 and 성적
def test_signals_funnel_counts_every_row_by_its_real_reason(world):
    sg = L.read_signals(world["paper"], L.ACCOUNT, NOW)
    assert sg["state"] == "ok" and sg["today_ms"] == W.T0 - 9 * H and sg["since_ms"] == W.T0 - 9 * H - 6 * W.DAY
    assert sg["stages"]["today"] == {"signals": 13, "filtered": 4, "entered": 6, "skipped": 1, "rejected": 1, "waiting": 1}
    assert sg["stages"]["week"]["signals"] == 14 and sg["stages"]["week"]["filtered"] == 5          # + the Saturday one
    week = {c["cat"]: c["n"] for c in sg["counts"]["week"]}
    assert week == {"entered": 6, "off": 2, "research": 1, "weekend": 1, "macro": 1, "lost": 1, "late": 1, "waiting": 1}
    ko = {c["cat"]: c["ko"] for c in sg["counts"]["week"]}
    assert ko["lost"] == "같은 때 다른 신호에 밀림" and ko["off"] == "끈 구간" and ko["weekend"] == "주말 진입 안 함"
    rows = sg["rows"]
    assert rows[0]["status"] == "WAITING" and rows[0]["stage"] == "waiting" and [r["t"] for r in rows] == sorted((r["t"] for r in rows), reverse=True)
    eth = next(r for r in rows if r["symbol"] == "ETHUSDT" and r["status"] == "FILTERED")
    assert eth["why"] == "끈 구간: hr=5" and eth["why_ko"] == "끈 구간: 시각 05시"
    btc = next(r for r in rows if r["cat"] == "research")
    assert btc["why_ko"] == "연구 조건 밖 (필요: 평일만)"
    late = next(r for r in rows if r["cat"] == "late")
    assert late["stage"] == "rejected" and late["member"] == "S2_ST_ROC@30m#3~abc123" and late["strategy"] == "S2_ST_ROC"


def test_signals_without_records_are_missing(tmp_path):
    p = str(tmp_path / "empty.db")
    sqlite3.connect(p).close()
    assert L.read_signals(p, L.ACCOUNT, NOW)["state"] == "missing"
    assert L.read_signals(str(tmp_path / "none.db"), L.ACCOUNT, NOW)["reason_ko"] == L.MISSING_KO


def test_why_and_outcome_words():
    assert L.why_cat("FILTERED", "경제 발표 앞뒤 30분: 소비자물가(CPI) 2026-10-19 12:30") == ("macro", "경제 발표 앞뒤")
    assert L.why_cat("FILTERED", "돌파 없음(신호봉 시간 안에)") == ("nobreak", "돌파 없음")
    assert L.why_cat("FILTERED", "조건 밖(BTC 4시간 추세를 못 읽음)")[0] == "unread"
    assert L.why_cat("FILTERED", "조건 밖") == ("when", "조건 밖") and L.why_cat("BROKE", "")[0] == "broke"
    assert L.outcome_cat("SKIPPED", "in position")[1] == "포지션 있음 (한 번에 하나)"
    assert L.outcome_cat("REJECTED", "stop rule")[0] == "stoprule" and L.outcome_cat("REJECTED", "halted: x")[0] == "halted"
    assert L.why_words("끈 구간: oi24=읽기 실패, dow=6") == "끈 구간: 미결제약정 읽기 실패 · 요일 일요일"


def test_perf_rolling_breakdowns_and_the_live_side(tmp_path):
    p = W.build_world(str(tmp_path / "w"))
    os.remove(p["paper"])
    W.paper_db(p["paper"], extra_wins=[True] * 12 + [False] * 2 + [True] * 20)       # 40 paper trades
    pf = L.perf(p, NOW)
    a = pf["accts"]["paper"]
    assert a["stats"]["trades"] == 40 and a["stats"]["wins"] == 37
    assert len(a["roll20"]) == 21 and len(a["roll40"]) == 1 and a["roll40"][0][1] == pytest.approx(37 / 40)
    assert a["roll20"][-1][1] == pytest.approx(1.0) and a["roll20"][0][1] == pytest.approx(17 / 20)
    coins = {r["key"]: r for r in a["by_coin"]}
    assert coins["ETHUSDT"]["trades"] == 35 and coins["ETHUSDT"]["small"] is True and coins["ETHUSDT"]["small_floor"] == 40
    sides = {r["key"]: r["trades"] for r in a["by_side"]}
    assert sides == {1: 38, -1: 2}                                              # t2 and t5 were the shorts
    hours = {r["key"]: r["trades"] for r in a["by_hour"]}
    assert hours[10] == 1 and sum(hours.values()) == 40                         # t1 entered at 10:00 KST
    assert pf["checkpoint"]["ready"] is True and pf["checkpoint"]["zone"] == "up"
    m = pf["accts"]["mexc"]
    assert {r["key"]: r["trades"] for r in m["by_strategy"]} == {"N03_ADX_GC": 3}  # the live trades take their paper partner's strategy
    assert pf["flip"]["stats"]["trades"] == 4 and pf["refs"]["breakeven"] == 0.78


def test_rolling_chart_in_node(tmp_path):
    p = W.build_world(str(tmp_path / "w"))
    os.remove(p["paper"])
    W.paper_db(p["paper"], extra_wins=[True] * 12 + [False] * 2 + [True] * 20)
    pf = L.perf(p, NOW)
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}'); const P = await import('file://{SCREENS}/livebots-perf.js'); const d = {json.dumps(pf)};\n"
              "const svg = P.rollChart(d.accts.paper, d.refs, 600); const none = P.rollChart({roll20: [], roll40: []}, d.refs, 600);\n"
              "const cls = []; const go = (n) => { if (!n || !n.childNodes) return; const c = n.getAttribute && n.getAttribute('class'); if (c) cls.push(c); n.childNodes.forEach(go); }; go(svg);\n"
              "console.log(JSON.stringify({w: D.walk(svg), none, cls}));")
    out = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    o = json.loads(out.stdout.strip().splitlines()[-1])
    assert o["none"] is None and "100%" in o["w"]["text"] and "50%" in o["w"]["text"]
    assert {"r20", "r40", "band"} <= set(" ".join(o["cls"]).split())


def test_signals_and_perf_routes(client):
    client.post("/api/login", json={"password": PW})
    sg = client.get("/api/v4/livebots/signals").json()
    assert sg["state"] == "ok" and sg["stages"]["today"]["entered"] == 6
    pf = client.get("/api/v4/livebots/perf").json()
    assert set(pf["accts"]) == {"paper", "bybit", "mexc"} and pf["checkpoint"]["left"] == 34


# ---------------------------------------------------------------- 안전 · 그림자 · 설정
def test_safety_lists_halts_limits_the_kill_file_lights_and_the_log(world):
    open(os.path.join(os.path.dirname(world["paper"]), "STOP"), "w").close()
    sf = L.safety(world, NOW)
    b, m = sf["execs"]
    assert b["id"] == "bybit" and b["record"]["halted"] is False and m["record"]["halted"] is True
    assert m["record"]["halt_reason"] == "연속 손실 3번" and m["record"]["halted_ts"] == W.T0 + 8 * H
    assert [x["action"] for x in b["record"]["halts"]] == ["halt", "clear"]
    assert b["config"]["kill_file"]["present"] is True
    assert "daily_max_loss_usd" not in [x["key"] for x in b["config"]["limits"]]
    assert [e["kind"] for e in b["log"]] == ["pnl_check", "halt_cleared", "halt"] and all(e["kind"] != "retry" for e in b["log"])
    assert b["lights"] == [] and b["light"]["state"] == "building"


def test_safety_shows_the_lights_history(tmp_path):
    p = W.build_world(str(tmp_path / "w"))
    from paperbot.executor import ExecStore
    st = ExecStore(p["bybit_db"], lock=False)
    st.event(NOW - H, "WARN", "light_red", "신호등 빨강: paper 최근 20번 중 16번 이김(80%, 기준 85%) → ETHUSDT 진입을 따라 하지 않습니다",
             {"key": "COMBO@mix|ETHUSDT|1", "wins": 16, "n": 20})
    st.close()
    sf = L.safety(p, NOW)
    lt = sf["execs"][0]["lights"]
    assert len(lt) == 1 and lt[0]["kind_ko"] == "신호등 빨강" and lt[0]["data"]["wins"] == 16
    d = L.build(p, NOW)
    assert ex(d, "bybit")["light"]["last_event"]["kind"] == "light_red"


def test_shadows_from_the_same_start_or_not_there_yet(world, tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_SHADOW_DIR", str(tmp_path / "nowhere"))
    sh = L.shadows(world, NOW)
    assert [x["state"] for x in sh["shadows"]] == ["missing"] * 5
    assert sh["start_ko"].startswith("sudo systemctl start paperbot-combo-shadow@b")
    d = tmp_path / "sh"
    d.mkdir()
    W.shadow_db(str(d / "shadow-b.db"), [4.0, 6.0, -30.0, 5.0])
    with open(d / "shadow-nocut.db", "wb") as fh:
        fh.write(b"garbage" * 100)
    monkeypatch.setenv("PAPERBOT_LIVE_SHADOW_DIR", str(d))
    sh = L.shadows(world, NOW)
    b, nocut, ac32, chase, trend4h = sh["shadows"]
    assert b["state"] == "ok" and b["name_ko"] == "그림자 B 안정형" and b["stats"]["trades"] == 4 and b["stats"]["pnl"] == pytest.approx(-15.0)
    assert b["since_ms"] == W.T0 and b["main"]["stats"]["trades"] == 6                     # the live paper over the same start
    assert nocut["state"] == "error" and ac32["state"] == chase["state"] == trend4h["state"] == "missing"


def test_settings_group_every_setting_by_strategy(world, monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    st = L.settings(world, NOW)
    assert st["combo"]["source"] == "db" and st["n_settings"] == 3 and st["n_strategies"] == 2
    r = st["rules"]
    assert (r["leverage_btc"], r["leverage_alt"], r["margin"], r["max_loss_frac"], r["no_weekend"], r["macro_blackout_min"]) == (40, 30, 0.4, 0.35, True, 30)
    assert r["ladder"] == {"first_lock": 0.1, "step": 0.03, "trigger_gap": 0.01}
    g = {x["strategy"]: x for x in st["groups"]}
    assert g["S2_ST_ROC"]["n"] == 2 and g["S2_ST_ROC"]["tfs"] == ["1h", "30m"] and [m["order"] for m in g["S2_ST_ROC"]["members"]] == [1, 3]
    assert [x["config"]["signal_light_min_win"] for x in st["execs"]] == [0.85, 0.9]


def test_settings_fall_back_to_the_config_file_then_say_missing(tmp_path, monkeypatch):
    p = {k: str(tmp_path / f"{k}.db") for k in L.ENV}
    cfg = tmp_path / "combo.json"
    cfg.write_text(json.dumps(W.CONFIG), encoding="utf-8")
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(cfg))
    st = L.settings(p, NOW)
    assert st["combo"]["source"] == "file" and st["n_settings"] == 3
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none.json"))
    assert L.settings(p, NOW)["combo"]["state"] == "missing"


def test_the_last_three_routes(client):
    client.post("/api/login", json={"password": PW})
    assert len(client.get("/api/v4/livebots/safety").json()["execs"]) == 2
    assert len(client.get("/api/v4/livebots/shadows").json()["shadows"]) == 5
    assert client.get("/api/v4/livebots/settings").json()["n_settings"] == 3


# ---------------------------------------------------------------- 소리 · 빛
def test_live_events_only_what_really_arrived(world):
    d = L.build(world, NOW)
    later = json.loads(json.dumps(d))
    later["fills"] = [{"key": "mexc:x:new", "acct": "mexc", "kind": "exit", "t": NOW + 30_000, "reason": "LOCK", "pnl": 0.5},
                      {"key": "bybit:e:new", "acct": "bybit", "kind": "entry", "t": NOW + 31_000},
                      {"key": "paper:x:old", "acct": "paper", "kind": "exit", "t": NOW - 3 * H, "reason": "SL", "pnl": -5}] + d["fills"]
    m = ex(later, "mexc")
    b = ex(later, "bybit")
    b["light"] = {**b["light"], "state": "red", "last_event": {"kind": "light_red", "ts": NOW + 20_000}}
    b["record"]["halted"] = True
    b["record"]["halted_ts"] = NOW - 2 * H                                   # an old halt: no alarm sound now
    out = _node(f"""const d = {json.dumps(d)}, later = {json.dumps(later)};
    const a = C.liveEvents(null, d, {NOW});
    const b = C.liveEvents(a.state, later, {NOW} + 40000);
    const c = C.liveEvents(b.state, later, {NOW} + 45000);
    const re = C.liveEvents({{...b.state, seen: null}}, later, {NOW} + 50000);
    console.log(JSON.stringify({{a: a.names, b: b.names, fresh: b.fresh.map((f) => f.key), al: b.alarms, c: c.names, re: re.names}}));""")
    assert out["a"] == []                                                    # the first look is the past
    assert out["b"] == ["lv_tp", "lv_entry", "lv_alert"] and out["fresh"] == ["mexc:x:new", "bybit:e:new"]      # the 3-hour-old one is not now
    assert out["al"] == [{"id": "bybit", "what": "red"}]                     # the halt is old: no alarm for it
    assert out["c"] == [] and out["re"] == []                                # heard once; after a hidden page: a new baseline
    assert m["id"] == "mexc"


def _sound(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    pre = ("const mem = {}; globalThis.localStorage = {getItem: (k) => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); }, removeItem: (k) => { delete mem[k]; }};\n"
           "globalThis.window = globalThis; globalThis.AudioContext = class { constructor() { this.state = 'running'; this.currentTime = 0; this.destination = {}; }\n"
           "  createGain() { return {gain: {value: 0, setTargetAtTime() {}}, connect() {}}; } resume() { return Promise.resolve(); } };\n")
    script = pre + f"const S = await import('{core}/sound.js');\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_live_sounds_borrow_the_rule_bots_motifs_with_their_own_switches():
    out = _sound("""
    const played = []; S._test.setSink((k, a) => played.push({name: a.name, fs: a.fs, eng: a.eng}));
    const ids = S.EVENTS.map((e) => e[0]);
    const off = S.playLive(["lv_entry"]);                                   // sound off: nothing
    S.cfg.on = true; S.cfg.night = false; S._test.unlock(true); S.setKind("v6");
    const two = S.playLive(["lv_entry", "lv_tp", "lv_sl"], 1000);           // at most two, the rarest first
    const again = S.playLive(["lv_sl"], 1500);                              // the same motif within 1.2 s: one sound
    S.setEv("lv_alert", false);
    const muted = S.playLive(["lv_alert"], 9000);
    S.cfg.on = false;
    const pv = [S.preview("lv_tp"), S.preview("lv_alert"), S.preview("lv_nope")];
    console.log(JSON.stringify({ids, off, two, again, muted, pv, played, tp: S.MOTIFS.c_tp[0], sl: S.MOTIFS.c_sl[0], liq: S.MOTIFS.c_liq[0], map: S.LIVE_MOTIF}));""")
    assert out["ids"][-1] == "layer" and {"lv_entry", "lv_tp", "lv_sl", "lv_alert"} <= set(out["ids"])
    assert out["map"] == {"lv_entry": "c_entry", "lv_tp": "c_tp", "lv_sl": "c_sl", "lv_alert": "c_liq"}
    assert out["off"] == [] and out["two"] == ["lv_sl", "lv_tp"] and out["again"] == [] and out["muted"] == []
    assert out["played"][0] == {"name": "lv_sl", "fs": out["sl"]}                        # the 손절 motif, note for note (v6)
    assert out["pv"] == [True, True, False] and out["played"][-2]["fs"] == out["tp"] and out["played"][-1]["fs"] == out["liq"]


def test_sound_and_light_are_wired_to_real_records_only():
    js = _read(SCREENS, "livebots.js")
    assert "const ev = liveEvents(heard.state, d, serverNow());" in js and "sound.playLive(ev.names)" in js and "view.alarm(ev.alarms)" in js
    assert 'heard.state = {...heard.state, seen: null}' in js                # a page shown again starts from a new baseline
    term, chart = _read(SCREENS, "livebots-term.js"), _read(SCREENS, "livebots-chart.js")
    for src in (term, chart):
        assert "posKeys: (sym) => posKeys(" in src and "tickStream(ctx)" in src and "chart.onBig(r)" in src
    tc = _read(SCREENS, "terminal-chart.js")
    assert "[...seenPos].some((k) => !keys.has(k)))) deck.flash(ownEvent());" in tc   # a live position that opened or closed: one wash
    assert "sound.EVENTS.map(" in _read(V4, "core", "settings.js")                        # the 설정 panel lists the live switches too


# ---------------------------------------------------------------- wiring
def test_wiring_route_menu_find_inventory_and_module():
    # owners 10/19: the 실거래 screens moved to their own site (paperbot/livedash, tests/test_livedash_app.py): on the rule
    # bot's dashboard the route stays (hidden) and only says where it moved; the 실거래 site's menu lists the tabs
    routes = _read(V4, "core", "routes.js")
    assert 'livebots: {ko: "실거래", group: "home", title: "실거래", hidden: true}' in routes and '"checkpoint"]},' in routes
    assert "livebots:" not in _read(V4, "core", "search.js").split("export const LIVE_ALIAS")[0]
    assert "pos:" in _read(V4, "core", "search.js").split("export const LIVE_ALIAS")[1]
    assert "livebots" in MORE.MODULES and "livemissed" in MORE.MODULES and "livetape" in MORE.MODULES
    js = "".join(_read(SCREENS, f) for f in os.listdir(SCREENS) if f.startswith("livebots") and f.endswith(".js"))
    for path in ("/api/v4/livebots", "/api/v4/livebots/trades", "/api/v4/livebots/signals", "/api/v4/livebots/perf", "/api/v4/livebots/safety",
                 "/api/v4/livebots/shadows", "/api/v4/livebots/settings", "/api/v4/livebots/rank", "/api/v4/livebots/calendar",
                 "/api/v4/livebots/map", "/api/v4/livebots/costs", "/api/v4/livebots/now", "/api/v4/livebots/team",
                 "/api/v4/livebots/likely", "/api/v4/livebots/missed", "/api/v4/livebots/replay"):
        assert f'"{path}"' in js, path
    tabs = re.findall(r'\{id: "(\w+)", label: "([^"]+)"', _read(SCREENS, "livebots.js"))
    # in the 실거래 site's menu order (core/routes.js LIVE_GROUPS: 지금 · 기록 · 성적 · 운영); part B's 위험 · 봇 상태 · 목표 ·
    # 규칙 점검 join once their files are there
    own = [t for t in tabs if t[0] not in ("risk", "health", "goal", "judge")]
    assert own == [("hq", "관제"), ("pos", "포지션"), ("summary", "요약"), ("chart", "차트"), ("trades", "거래"), ("replay", "다시보기"),
                   ("signals", "신호"), ("missed", "못 탄 신호"), ("perf", "성적"), ("rank", "순위"), ("map", "지도"), ("cost", "비용"),
                   ("cal", "일정"), ("safety", "안전"), ("settings", "설정"), ("team", "분석팀"), ("shadows", "그림자")]
    assert 'tabOf = (arg) => (TABS.some((t) => t.id === arg) ? arg : "hq")' in _read(SCREENS, "livebots.js")   # owners 10/19: 관제 first
    inv = _read(V4, "INVENTORY.md")
    for word in ("#/livebots", "/api/v4/livebots", "PAPERBOT_LIVE_PAPER_DB", "PAPERBOT_LIVE_BYBIT_DB", "PAPERBOT_LIVE_MEXC_DB",
                 "PAPERBOT_LIVE_BYBIT_CONFIG", "PAPERBOT_LIVE_MEXC_CONFIG", "실거래 터미널"):
        assert word in inv, word
    css = _read(SCREENS, "livebots.css")
    for part in ("hq", "rank", "map", "cost", "cal", "team", "likely", "missed", "replay"):
        assert f'@import url("livebots-{part}.css");' in css, part
        own = re.sub(r"/\*.*?\*/", "", _read(SCREENS, f"livebots-{part}.css"), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", own) and not re.search(r"font-size:\s*\d", own), part
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
    assert "topBar(ctx, st, {meetings: false})" in live and "bigFeed(ctx)" in live and "liqFeed(ctx, st," in live and "consolePanel(" in live
    # the AI meetings line is the rule bot's (the 실거래 site has no rooms): the live terminal never asks for the office
    top = _read(SCREENS, "terminal-top.js")
    assert "export function topBar(ctx, st, o = {})" in top and "if (o.meetings !== false) {\n    office(25000);" in top


# ================================================================ the live checks: livecheck.db and liveimprove.db (read-only)
# Both files are made by paperbot/livecheck.py and paperbot/liveimprove.py themselves (livebots_world.live_checks): the
# watcher's two passes with their loss cards, the morning checks, the weekly pass, the owners' ledger steps.
from paperbot import livecheck as LC  # noqa: E402
from paperbot import liveimprove as LI  # noqa: E402


def _checked(folder, rich=False):
    p = W.build_world(folder)
    m = W.live_checks(p, folder, rich=rich)
    return p, {**L.paths_more(), **m}


@pytest.fixture
def checked(tmp_path):
    return _checked(str(tmp_path / "c"))


@pytest.fixture(scope="module")
def rich(tmp_path_factory):
    return _checked(str(tmp_path_factory.mktemp("rich")), rich=True)


def test_a_losing_trade_carries_its_loss_card(checked):
    p, more = checked
    t = L.trade_rows(p, NOW, more)
    assert t["cards"]["state"] == "ok" and t["cards"]["n"] == 1
    assert [k["id"] for k in t["cards"]["kinds"]] == ["gap", "bigger", "streak", "weak", "normal"]
    by = {r["symbol"]: r for r in t["accts"]["paper"]["rows"]}
    c = by["SOLUSDT"]["card"]                                         # t3, the standard world's one loss
    assert all(by[s]["card"] is None for s in by if s != "SOLUSDT")   # wins have none
    assert c["key"] == f"COMBO@mix|SOLUSDT|{W.T0 + 3 * H}" and c["label"] == "정상 범위 손실" and c["kind"] == "normal"
    assert c["strategy"] == "S2_ST_ROC" and c["tf"] == "30m" and c["member_order"] == 3 and c["roe"] == pytest.approx(-0.15)
    assert c["fit_win"] is None and c["streak"] == 1 and c["hold_ms"] == 40 * MIN and c["exit_ko"] == "손절"
    # the noise stop, four hours after the exit, from the rule bot's 1m bars: back to +15 % net ROE (30x, 100 -> 100.5)
    assert c["noise"]["state"] == "noise" and c["noise"]["roe"] == pytest.approx(0.15)
    ex = {o["name"]: o for o in c["executors"]}
    assert ex["bybit"]["status"] == "followed" and ex["bybit"]["pnl"] == pytest.approx(-6.3)
    assert ex["mexc"]["status"] == "not_followed" and "오늘 남은 손실 한도" in ex["mexc"]["why"]
    assert c["text"] == LC.card_text(json.loads(sqlite3.connect(more["check_db"]).execute(
        "SELECT data FROM loss_cards").fetchone()[0]))                # the stored card, as the watcher wrote it
    # a live trade shows its paper partner's card
    b = next(r for r in t["accts"]["bybit"]["rows"] if r["symbol"] == "SOLUSDT")
    assert b["card"]["key"] == c["key"] and all(r["card"] is None for r in t["accts"]["bybit"]["rows"] if r["symbol"] != "SOLUSDT")


def test_loss_cards_of_every_label_and_their_counts(rich):
    p, more = rich
    t = L.trade_rows(p, NOW, more)
    rows = t["accts"]["paper"]["rows"]
    cards = [r["card"] for r in rows if r["card"]]
    stored = dict(sqlite3.connect(more["check_db"]).execute("SELECT key, label FROM loss_cards").fetchall())
    assert len(cards) == len(stored) == 17 and all(stored[c["key"]] == c["label"] for c in cards)   # the watcher's labels
    assert all(not r["win"] for r in rows if r["card"])
    kinds = {}
    for c in cards:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    assert kinds == {"gap": 1, "bigger": 1, "streak": 3, "weak": 8, "normal": 4}
    gap = next(c for c in cards if c["kind"] == "gap")
    assert gap["label"] == "실거래-페이퍼 차이" and gap["gap"] is True
    assert {o["name"]: o["status"] for o in gap["executors"]} == {"bybit": "followed", "mexc": "not_followed"}
    assert next(o for o in gap["executors"] if o["name"] == "bybit")["roe"] > 0               # bybit won where the paper lost
    big = next(c for c in cards if c["kind"] == "bigger")
    assert big["strategy"] == "F12_MSS_DISP" and big["roe"] == pytest.approx(-0.75) and big["roe"] < big["loss_worst"]
    weak = next(c for c in cards if c["kind"] == "weak")
    assert weak["strategy"] == "F4_FAN" and weak["sym_cell"] == [26, pytest.approx(0.7692)] and weak["weak"] == ["코인"]
    assert weak["honest"] == [116, pytest.approx(0.6207)] and weak["fit_longest"] == 3 and weak["honest_longest"] == 5
    assert {c["label"] for c in cards if c["kind"] == "streak"} == {"연속 손실 2번째"}
    # noise: the old ones without 1m bars could not be checked; the newest are still being checked; t3 was a noise stop
    states = {c["noise"]["state"] for c in cards}
    assert {"noise", "unknown", "checking"} <= states and "wait" not in states


def test_the_scorecard_is_liveimproves_own(rich):
    """Status words, counts, fit / honest rates and the executors' cost gap are exactly liveimprove's (its `score`)."""
    p, more = rich
    sc = L.perf(p, NOW, more)["scorecard"]
    assert sc["state"] == "ok" and sc["source"] == "live" and sc["n"] == 48
    g = LI.gather(LI.Sources(paper_db=p["paper"], executors=W.exec_infos(p)))
    card = LI.scorecard(g["trades"], g["ref"], g["follow"], cuts=("strategy",))
    mine = {r["key"]: r for r in sc["rows"]}
    theirs = {r["key"]: r for r in card["cuts"]["strategy"]}
    assert set(mine) == set(theirs) and len(mine) == 28                 # the 27 reference strategies + S2_ST_ROC (not in it)
    for k, r in theirs.items():
        m = mine[k]
        assert (m["n"], m["wins"], m["status"], m["fit"], m["honest"], m["honest_src"], m["label"]) == \
            (r["n"], r["wins"], r["status"], r["fit"], r["honest"], r["honest_src"], r["label"]), k
        for ex, e in r["exec"].items():
            assert m["exec"][ex]["n"] == e["n"] and m["exec"][ex]["leak"] == pytest.approx(e["leak"]) if e["leak"] is not None \
                else m["exec"][ex]["leak"] is None
    words = {k: mine[k]["status"] for k in ("N03_ADX_GC", "F4_FAN", "N08_ICHI_WR", "F12_MSS_DISP")}
    assert words == {"N03_ADX_GC": LI.WATCH, "F4_FAN": LI.BAD, "N08_ICHI_WR": LI.OK, "F12_MSS_DISP": LI.SMALL}
    assert sc["words"] == [LI.SMALL, LI.OK, LI.WATCH, LI.BAD] == ["표본 작음", "기대 안", "주의", "확실히 나쁨"]
    assert sc["overall"]["status"] == card["overall"]["status"] and sc["overall"]["n"] == 48 and sc["overall"]["wins"] == 31
    assert sc["luck_ko"] == LI.LUCK_NOTE and "1~2개는 \"주의\"" in sc["luck_ko"] and sc["family"] == 27
    assert sc["problems"] and "세팅 수가 다름" in sc["problems"][0]          # the world's config is not the reference's
    assert mine["N03_ADX_GC"]["exec"]["bybit"]["n"] == 16 and sc["cmd"].endswith("python -m paperbot.liveimprove score")


def test_the_ledger_open_first_with_question_next_step_and_the_exact_command(rich):
    p, more = rich
    lg = L.perf(p, NOW, more)["ledger"]
    assert lg["state"] == "ok" and lg["n"] == 4 and lg["open_n"] == 3
    items = lg["items"]
    assert [x["open"] for x in items] == [True, True, True, False] and [x["id"] for x in items[:3]] == [1, 2, 3]
    one = items[0]
    assert one["status"] == "백테스트 시험" and one["question"].endswith(LI.QUESTION_TAIL)
    assert one["next_ko"] == LI.next_step({"id": 1, "status": "백테스트 시험"}, full=False)
    assert one["cmds"] == ['sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove ledger set 1 --status "그림자 시험" '
                           '--backtest-ok --note "..."',
                           'sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove ledger set 1 --status 기각 --note "..."']
    assert [(x["old"], x["new"]) for x in one["log"]] == [(None, "발견"), ("발견", "백테스트 시험")] and one["log"][1]["who"] == "두 분"
    assert items[1]["status"] == "발견" and items[1]["cmds"][0].endswith('ledger set 2 --status "백테스트 시험" --note "..."')
    for x in items[:3]:                                                # liveimprove's own command, as the start guide runs it
        full = LI.next_step({"id": x["id"], "status": x["status"]}, full=True)
        assert all(c.replace("sudo -u paperbot /opt/paperbot/venv/bin/", "") in full for c in x["cmds"])
    last = items[-1]
    assert last["status"] == "기각" and last["cmds"] == [] and last["next_ko"] == "끝난 항목" and last["note"] == "2025-26에서 나빠짐"
    assert lg["adopt_rule"] == list(LI.ADOPT_RULE) and len(lg["adopt_rule"]) == 5
    assert lg["week"]["week"] == "2026-10-19" and lg["week"]["tested"] > 0 and lg["week"]["flagged"] == 4
    assert lg["list_cmd"].endswith("python -m paperbot.liveimprove ledger list") and lg["cd"] == "cd /opt/crypto-bot-research"


def test_morning_checks_of_14_days_and_the_watchers_alarms(checked):
    p, more = checked
    ch = L.safety(p, NOW, more=more)["checks"]
    assert ch["state"] == "ok"
    m = ch["morning"]
    assert m["state"] == "ok" and m["last_day"] == "2026-10-18" and m["loud_days"] == 1
    assert [(x["day"], x["state"]) for x in m["items"]] == [("2026-10-18", "ok"), ("2026-10-17", "ok"), ("2026-10-16", "none"),
                                                             ("2026-10-15", "ok")]  # from the first record on; 10/16 had no check
    d18 = m["items"][0]
    text = sqlite3.connect(more["check_db"]).execute("SELECT text FROM days WHERE day = '2026-10-18'").fetchone()[0]
    assert d18["level"] == "CRITICAL" and d18["text"] == text and d18["day_ko"] == "10/18(일)" and d18["sent"] is True
    assert d18["loud_n"] == len(d18["reasons"]) == 2 and all(f"\n- {r}\n" in text for r in d18["reasons"])
    assert any("MEXC" in r for r in d18["reasons"])
    sm = d18["summary"]
    assert {x["name"]: (x["n"], x["halted"]) for x in sm["execs"]} == {"bybit": (1, False), "mexc": (0, True)}
    assert sm["paper"] == {"n": 0, "wins": 0, "pnl": 0.0} and sm["parity_error"]
    d17 = m["items"][1]
    assert d17["level"] == "INFO" and d17["loud_n"] == 0 and d17["reasons"] == [] and all(x["missing"] for x in d17["summary"]["execs"])
    assert m["items"][2]["why_ko"].startswith("그날 점검 기록이")
    # before 09:45 KST the day that just ended is 점검 전, not a missing check
    early = L.read_checks(more["check_db"], W.T0 + L.DAY + 10 * MIN)["morning"]
    assert early["items"][0]["day"] == "2026-10-19" and early["items"][0]["state"] == "pending"
    w = ch["watch"]
    assert w["state"] == "ok" and w["last_seen_ms"] == NOW and w["passes"] == 2 and w["stale"] is False
    by = {f["kind"]: f for f in w["items"]}
    assert by["rule_bars"]["state"] == "cleared" and by["rule_bars"]["cleared_ts"] == NOW and by["rule_bars"]["ts"] == NOW - 30 * MIN
    assert by["rule_bars"]["recover"].startswith("✅") and by["rule_bars"]["kind_ko"] == "규칙봇 1분봉 멈춤"
    assert by["stop"]["state"] == "active" and by["stop"]["ex"] == "bybit" and by["stop"]["last_ts"] == NOW
    assert by["halt"]["state"] == "active" and by["halt"]["ex"] == "mexc" and by["halt"]["level"] == "CRITICAL"
    assert w["active_n"] == 2 and all(f["sent"] for f in w["items"]) and by["halt"]["title"].startswith("MEXC 실행기가 멈췄습니다")
    assert L.read_checks(more["check_db"], NOW + 11 * MIN)["watch"]["stale"] is True    # a watcher silent for 10 minutes


def test_live_check_files_not_there_yet_say_so(tmp_path, world):
    """No file: 수집 전 (missing), never an empty list; a file without its tables: missing; garbage: 못 읽음 with the reason."""
    more = {**L.paths_more(), "check_db": str(tmp_path / "none" / "livecheck.db"), "improve_db": str(tmp_path / "none" / "liveimprove.db")}
    t = L.trade_rows(world, NOW, more)
    assert t["cards"]["state"] == "missing" and t["cards"]["reason_ko"] == L.CHECK_MISSING_KO and t["cards"]["n"] == 0
    assert all(r["card"] is None for r in t["accts"]["paper"]["rows"])
    pf = L.perf(world, NOW, more)
    assert pf["ledger"]["state"] == "missing" and pf["ledger"]["reason_ko"] == L.IMPROVE_MISSING_KO and "items" not in pf["ledger"]
    assert pf["scorecard"]["state"] == "ok"                                 # the scorecard reads the paper bot only
    ch = L.safety(world, NOW, more=more)["checks"]
    assert ch["state"] == ch["morning"]["state"] == ch["watch"]["state"] == "missing" and "items" not in ch["morning"]
    # files there but without their tables
    empty = str(tmp_path / "empty.db")
    sqlite3.connect(empty).close()
    more2 = {**more, "check_db": empty, "improve_db": empty}
    assert L.trade_rows(world, NOW, more2)["cards"]["state"] == "missing"
    assert L.perf(world, NOW, more2)["ledger"]["state"] == "missing"
    ch = L.safety(world, NOW, more=more2)["checks"]
    assert ch["morning"]["state"] == "missing" and ch["watch"]["state"] == "missing"
    # garbage: 못 읽음 + why, never 0 or an empty list
    bad = str(tmp_path / "bad.db")
    with open(bad, "wb") as fh:
        fh.write(b"garbage" * 300)
    more3 = {**more, "check_db": bad, "improve_db": bad}
    c = L.trade_rows(world, NOW, more3)["cards"]
    assert c["state"] == "error" and "망가졌" in c["reason_ko"] and "DatabaseError" in c["reason"]
    assert L.perf(world, NOW, more3)["ledger"]["state"] == "error"
    assert L.safety(world, NOW, more=more3)["checks"]["morning"]["state"] == "error"
    # a watcher file before its first pass: the morning check ran, the watcher not yet
    only = str(tmp_path / "only-morning.db")
    LC.open_out(only).close()
    w = L.read_checks(only, NOW)
    assert w["morning"]["state"] == "missing" and "아침 점검이 아직" in w["morning"]["reason_ko"]
    assert w["watch"]["state"] == "missing" and "실시간 감시가 아직" in w["watch"]["reason_ko"]
    # the scorecard without the paper database: 수집 전, without the reference: 못 읽음
    gone = dict(world, paper=str(tmp_path / "nope.db"))
    assert L.perf(gone, NOW, more)["scorecard"]["state"] == "missing"


def test_the_live_check_files_are_only_read(rich, monkeypatch):
    """Byte-identical files, no new file next to them (no -journal / -wal), every connection mode=ro, no key file opened."""
    p, more = rich
    folder = os.path.dirname(p["paper"])
    env = os.path.join(folder, "executor.env")
    with open(env, "w", encoding="utf-8") as fh:
        fh.write("BYBIT_LIVE_KEY=secret-key-456\n")
    files = sorted(os.listdir(folder))
    before = {f: open(os.path.join(folder, f), "rb").read() for f in files if os.path.isfile(os.path.join(folder, f))}
    uris = []
    real_connect, real_open = sqlite3.connect, builtins.open

    def connect(target, *a, **k):
        uris.append(str(target))
        return real_connect(target, *a, **k)

    def guarded(path, *a, **k):
        assert not str(path).endswith(".env"), path
        return real_open(path, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(builtins, "open", guarded)
    out = json.dumps([L.trade_rows(p, NOW, more), L.perf(p, NOW, more), L.safety(p, NOW, more=more)], ensure_ascii=False)
    monkeypatch.setattr(builtins, "open", real_open)
    monkeypatch.setattr(sqlite3, "connect", real_connect)
    assert "secret-key-456" not in out
    assert uris and all("mode=ro" in u for u in uris), [u for u in uris if "mode=ro" not in u]
    assert any("livecheck.db" in u for u in uris) and any("liveimprove.db" in u for u in uris)
    assert sorted(os.listdir(folder)) == files
    assert {f: open(os.path.join(folder, f), "rb").read() for f in before} == before


def test_the_new_parts_come_through_the_routes(tmp_path, monkeypatch):
    p, more = _checked(str(tmp_path / "r"))
    for k, v in {**W.env_of(p), **W.env_more_of({"check_db": more["check_db"], "improve_db": more["improve_db"]})}.items():
        monkeypatch.setenv(k, v)
    base = tmp_path / "data"
    base.mkdir()
    dbp = str(base / "paper3.db")
    _store(dbp).close()
    c = TestClient(create_app(dbp, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    c.post("/api/login", json={"password": PW})
    t = c.get("/api/v4/livebots/trades").json()
    assert t["cards"]["state"] == "ok" and next(r for r in t["accts"]["paper"]["rows"] if r["symbol"] == "SOLUSDT")["card"]["kind"] == "normal"
    pf = c.get("/api/v4/livebots/perf").json()
    assert pf["scorecard"]["state"] == "ok" and pf["ledger"]["state"] == "ok" and pf["ledger"]["open_n"] == 1
    sf = c.get("/api/v4/livebots/safety").json()
    assert sf["checks"]["morning"]["state"] == "ok" and sf["checks"]["watch"]["state"] == "ok"


def test_the_env_vars_and_the_service_let_the_dashboard_read_them():
    assert L.paths_more({})["check_db"] == "/var/lib/paperbot/livecheck.db"
    assert L.paths_more({})["improve_db"] == "/var/lib/paperbot/liveimprove.db"
    assert L.paths_more({"PAPERBOT_LIVE_CHECK_DB": "/x/c.db"})["check_db"] == "/x/c.db"
    example = _read(ROOT, "deploy", "dash.env.example")
    assert "#PAPERBOT_LIVE_CHECK_DB=/var/lib/paperbot/livecheck.db" in example
    assert "#PAPERBOT_LIVE_IMPROVE_DB=/var/lib/paperbot/liveimprove.db" in example
    svc = _read(ROOT, "deploy", "paperbot-dash.service").splitlines()
    val = lambda k: next(ln for ln in svc if ln.startswith(k + "=")).split("=", 1)[1].split()       # noqa: E731
    hidden = val("InaccessiblePaths")
    for f in ("/var/lib/paperbot/livecheck.db", "/var/lib/paperbot/liveimprove.db"):
        assert not any(f.startswith(h.lstrip("-")) or h.lstrip("-").rstrip("/") == "/var/lib/paperbot" for h in hidden), f
        assert any(f.startswith(r.rstrip("/") + "/") for r in val("ReadWritePaths") + val("ReadOnlyPaths")), f
    assert "User=paperbot" in svc                                   # the user the livecheck / livewatch / liveimprove units write as
    for unit in ("paperbot-livecheck.service", "paperbot-livewatch.service", "paperbot-liveimprove.service"):
        assert "User=paperbot" in _read(ROOT, "deploy", unit).splitlines()
    src = _read(ROOT, "paperbot", "dash", "more", "livebots.py")
    new = src[src.index("# ================================================================ the live checks"):src.index("def _cached(")]
    for call in ("sqlite3.connect(", "executor.env", ".open_out(", ".set_status(", ".ledger_add(", ".run_weekly(", ".run_watch(",
                 ".run_check(", ".cards_pass(", ".save_day(", ".save_week("):
        assert call not in new, call                                # only read: never a writer of either module


# ---------------------------------------------------------------- the page: the card, the scorecard, the ledger, the checks in node
def _page(call: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\n"
              + "".join(f"const {n} = await import('file://{SCREENS}/{f}');\n" for n, f in (
                  ("Cd", "livebots-cards.js"), ("Sc", "livebots-score.js"), ("Ch", "livebots-checks.js"), ("Tr", "livebots-trades.js")))
              + f"const d = {json.dumps(data)};\nconst out = ({call});\n"
              "console.log(JSON.stringify(out && out.el ? D.walk(out.el) : out instanceof Node ? D.walk(out) : {json: out}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    if "text" in out:
        out["text"] = re.sub(r"\s+", " ", out["text"])
    return out


def test_the_loss_card_opens_inline_with_label_backtest_noise_and_executors(rich):
    p, more = rich
    t = L.trade_rows(p, NOW, more)
    rows = t["accts"]["paper"]["rows"]
    gap = next(r for r in rows if r["card"] and r["card"]["kind"] == "gap")["card"]
    x = _page("Cd.cardBlock(d.card, {kinds: d.kinds})", {"card": gap, "kinds": t["cards"]["kinds"]})
    txt = x["text"]
    assert "실거래-페이퍼 차이" in txt and "손실 카드 · N03_ADX_GC 15분" in txt and "백테스트 승률 95.2%" in txt   # (names table: browser only) and "처음 보는 2025-26 84% (171번)" in txt
    assert "손실은 보통" in txt and "최악" in txt and "연속 손실 1번째 (백테스트 최장 3번, 처음 보는 기간 5번)" in txt
    assert "노이즈 손절은 확인 못 했어요" in txt and "바이비트" in txt and "따라감" in txt and "MEXC" in txt and "안 따라감" in txt
    assert "카드 글 보기" in txt and "pp lb-cchip bad" in x["classes"]
    for bad in ("null", "undefined", "NaN"):
        assert bad not in txt, bad
    t3 = next(r for r in rows if r["symbol"] == "SOLUSDT")["card"]
    assert "노이즈 손절이었어요: 청산 뒤 4시간 안에 순ROE +15.0%까지 돌아갔어요" in _page("Cd.cardBlock(d)", t3)["text"]
    assert "백테스트 기준표에 이 매매법이 없어요" in _page("Cd.cardBlock(d)", t3)["text"]
    # 손실 카드만 and the count by label over the trades shown
    out = _page("({only: Tr.filterRows(d.rows, {res: 'all', card: true}).length, all: Tr.filterRows(d.rows, {res: 'all'}).length,"
                " counts: Cd.cardCounts(d.rows, d.kinds), f4: Tr.filterRows(d.rows, {strat: 'F4_FAN', res: 'all', card: true}).length})",
                {"rows": rows, "kinds": t["cards"]["kinds"]})["json"]
    assert out["only"] == 17 and out["all"] == 48 and out["f4"] == 9
    assert [(k["id"], k["n"]) for k in out["counts"]] == [("gap", 1), ("bigger", 1), ("streak", 3), ("weak", 8), ("normal", 4)]
    s = _page("Cd.cardSummary(d.rows, d.kinds, {state: 'ok'})", {"rows": rows, "kinds": t["cards"]["kinds"]})["text"]
    assert "손실 카드 17장" in s and "백테스트에서도 약한 자리 8" in s and "연속 손실 3" in s and "10/15~10/19" in s
    # a live account's rows carry the paper partner's card
    live = t["accts"]["bybit"]["rows"]
    assert _page("Tr.filterRows(d, {res: 'all', card: true}).length", live)["json"] == sum(1 for r in live if r["card"])


def test_scorecard_ledger_and_checks_render(rich, checked, tmp_path):
    p, more = rich
    pf = L.perf(p, NOW, more)
    sc = _page("(() => { const v = Sc.scoreView({}); v.set(d); return v; })()", pf["scorecard"])["text"]
    assert "전체 48번 31승" in sc and "주의" in sc and "확실히 나쁨" in sc and "표본 작음" in sc and "기대 안" in sc
    assert "매매법 27개를 한꺼번에 보면 운만으로도 1~2개는 \"주의\"가 나옵니다. 정상입니다." in sc and "N03_ADX_GC 15분·1시간" in sc
    assert "실거래 비용" in sc and "바이비트 16번" in sc and "python -m paperbot.liveimprove score" in sc
    order = _page("Sc.sortRows(d.rows.filter((r) => r.n), 'status', d.words).map((r) => r.key)", pf["scorecard"])["json"]
    assert order[:2] == ["F4_FAN", "N03_ADX_GC"]                         # 확실히 나쁨, then 주의
    assert _page("Sc.sortRows(d.rows.filter((r) => r.n), 'n', d.words).map((r) => r.key)", pf["scorecard"])["json"][0] == "N03_ADX_GC"
    lg = _page("(() => { const v = Sc.ledgerView(); v.set(d); return v; })()", pf["ledger"])["text"]
    assert "열린 것 3개" in lg and "#1" in lg and "백테스트 시험" in lg and "질문" in lg and "다음" in lg
    assert 'ledger set 1 --status "그림자 시험" --backtest-ok --note "..."' in lg and "ledger list" in lg
    for line in LI.ADOPT_RULE:
        assert line in lg, line
    ch = L.safety(checked[0], NOW, more=checked[1])["checks"]
    c = _page("(() => { const v = Ch.checksView(); v.set(d); return v; })()", ch)["text"]
    assert "10/18(일)" in c and "확인할 것 2개" in c and "대조는 못 함" in c and "기록 없음" in c and "점검 글 보기" in c
    assert "지금 켜진 알람 2개" in c and "다시 울릴 준비" in c and "켜져 있음" in c and "규칙봇 1분봉 멈춤" in c
    for bad in ("null", "undefined", "NaN"):
        assert bad not in sc + lg + c, bad
    # nothing there yet: 수집 전 in every part, never a zero or '없어요'
    none = {**L.paths_more(), "check_db": str(tmp_path / "x" / "c.db"), "improve_db": str(tmp_path / "x" / "i.db")}
    gone = {**L.read_checks(none["check_db"], NOW)}
    c = _page("(() => { const v = Ch.checksView(); v.set(d); return v; })()", gone)["text"]
    lg = _page("(() => { const v = Sc.ledgerView(); v.set(d); return v; })()", L.read_ledger(none["improve_db"]))["text"]
    for t_ in (c, lg):
        assert "수집 전" in t_ and "없어요" not in t_ and "0.00" not in t_ and "USDT" not in t_, t_
    assert c.count("수집 전") == 2


# ================================================================ never taken for the rule bot's paper screens (owners 10/19)
def _core(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    script = f"const R = await import('file://{V4}/core/routes.js');\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_mode_chip_says_실거래_on_livebots_and_모의_everywhere_else():
    out = _core("console.log(JSON.stringify({all: Object.fromEntries(Object.keys(R.SCREENS).map((n) => [n, R.modeTag(n)])),"
                " home: R.modeTag(''), items: R.navGroups(true).flatMap((g) => g.items.map((it) => it.id))}));")
    tags = out["all"]
    assert tags["livebots"]["text"] == "실거래" and tags["livebots"]["real"] is True and "진짜 돈" in tags["livebots"]["title"]
    others = {n: t for n, t in tags.items() if n != "livebots"}
    assert len(others) > 20 and all(t == {"text": "모의", "real": False, "title": "모든 계좌는 모의(가상 돈)입니다"} for t in others.values())
    assert out["home"]["text"] == "모의"
    # the shell sets it on every route; the real-money colour is a token (the warn / gold one), never a hex
    shell = _read(V4, "core", "shell.js")
    assert "const m = modeTag(p.name);" in shell and 'tag.classList.toggle("real", m.real)' in shell and 'bus.on("route", renderNav)' in shell
    base = re.sub(r"/\*.*?\*/", "", _read(V4, "base.css"), flags=re.S)
    rule = re.search(r"\.mocktag\.real \{([^}]*)\}", base).group(1)
    assert "var(--warn)" in rule and "var(--warn-soft)" in rule and not re.search(r"#[0-9a-fA-F]{3,8}\b", rule)
    assert '<span class="mocktag" title="모든 계좌는 모의(가상 돈)입니다">모의</span>' in _read(V4, "index.html")   # the default
    # the menu: no 실거래 button on the rule bot's dashboard any more (owners 10/19: its own site, tests/test_livedash_app.py);
    # the dot rule for a 실거래 button stays in core/nav.css, outside any media query
    assert "livebots" not in out["items"]
    nav = re.sub(r"/\*.*?\*/", "", _read(V4, "core", "nav.css"), flags=re.S)
    dot = re.search(r'\.sb\[data-sb="livebots"\]::before \{([^}]*)\}', nav)
    assert dot and "var(--warn)" in dot.group(1) and 'content: ""' in dot.group(1)
    depth = 0
    for ch in nav[:dot.start()]:
        depth += 1 if ch == "{" else -1 if ch == "}" else 0
    assert depth == 0                                                   # top level: on every window, both menu layouts
    assert '.rail-a[data-screen="livebots"] .rail-ic' in nav and 'dataset: {sb: it.id}' in _read(V4, "core", "strip.js")


def test_the_real_money_strip_on_every_livebots_tab(world, tmp_path):
    d = L.build(world, NOW)
    t = _render("ui.note(K.realLine(d))", d)["text"]
    assert t.startswith("진짜 돈 · 바이비트 $101.50 · WOO X Pro $102.80 · 포지션 1/1·0/1 · 보기만 하는 화면(주문 버튼 없음)"), t
    gone = L.build({k: "/nonexistent/" + k for k in L.ENV}, NOW)
    t = _render("ui.note(K.realLine(d))", gone)["text"]
    assert "바이비트 수집 전" in t and "WOO X Pro 수집 전" in t and "$" not in t and "0.00" not in t and "0/1" not in t
    with open(world["mexc_db"], "wb") as fh:
        fh.write(b"garbage" * 200)
    t = _render("ui.note(K.realLine(d))", L.build(world, NOW))["text"]
    assert "바이비트 $101.50" in t and "WOO X Pro 못 읽음" in t and "포지션 1/1·못 읽음" in t
    t = _render("ui.note(K.realLine(null))", None)["text"]                  # before the first answer: dashes only
    assert "바이비트 —" in t and "$" not in t and "0/1" not in t
    # it is the 실거래 screen's own: drawn by livebots.js on every tab (one mount), refreshed with the summary; no other screen
    js = _read(SCREENS, "livebots.js")
    assert "el.append(real, head, staleSlot, body);" in js and "put(real, realLine(d));" in js
    others = [f for f in os.listdir(SCREENS) if f.endswith(".js") and not f.startswith("livebots") and "realLine" in _read(SCREENS, f)]
    assert others == []
    css = re.sub(r"/\*.*?\*/", "", _read(SCREENS, "livebots.css"), flags=re.S)
    assert "var(--warn-line)" in re.search(r"\.lb-real \{([^}]*)\}", css).group(1)


def test_the_paper_account_is_named_페이퍼_연습_next_to_real_money(world):
    d = L.build(world, NOW)
    assert acct(d, "paper")["name_ko"] == "페이퍼(연습)"
    t = _render("d.accts.map((a) => K.acctCard(a, ui.ledBar({label: a.id}), []))", d)["text"]
    assert "페이퍼(연습)" in t and "바이비트" in t
    fills = _render("(() => { const f = P.fillsPanel(ctx); f.set(d, 'ok'); return f.el; })()", d)["text"]
    assert "페이퍼(연습) · 바이비트 · WOO X Pro" in fills
    kit = _read(SCREENS, "livebots-kit.js")
    assert 'paper: {ko: "페이퍼(연습)"' in kit
    assert "페이퍼(연습)" in _read(SCREENS, "livebots-parts.js")
    for f in ("livebots-term.js", "livebots-chart.js"):                  # the chart's line key: 페이퍼(연습, P) · 바이비트(B) · MEXC(M)
        assert "페이퍼(연습, P)" in _read(SCREENS, f), f


# ---------------------------------------------------------------- the 10/20 config: two-part ladder, no_chase, another bot's reference
TWO = {"first_lock": 0.10, "trigger_gap": 0.01, "step": 0.05, "next_trigger": 0.15, "next_gap": 0.03}
LIVE_CFG = os.path.join(ROOT, "deploy", "combo.live-ac.json")


def _set_ladder(world, ladder):
    """The world's paper bot runs ``ladder`` (its own combo_run record, as the bot writes it at its start)."""
    conn = sqlite3.connect(world["paper"])
    d = json.loads(conn.execute("SELECT data FROM state WHERE k = 'combo_run'").fetchone()[0])
    d["config"] = {**d["config"], "ladder": ladder}
    conn.execute("UPDATE state SET data = ? WHERE k = 'combo_run'", (json.dumps(d),))
    conn.commit()
    conn.close()


def _running_config(tmp_path, monkeypatch, same: bool) -> str:
    """PAPERBOT_LIVE_COMBO_CONFIG -> a copy of deploy/combo.live-ac.json (the references' config) or other bytes."""
    with open(LIVE_CFG, "rb") as fh:
        raw = fh.read()
    path = tmp_path / ("same.json" if same else "new.json")
    path.write_bytes(raw if same else raw + b"\n")
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(path))
    return str(path)


def _node_mods(body: str, data, mods: dict):
    """Runs ``body`` in node with the tiny DOM, each of ``mods`` ({name: screens file}) imported and ``d`` = data."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    imports = "".join(f"const {k} = await import('file://{SCREENS}/{f}');\n" for k, f in mods.items())
    script = f"const D = await import('{dom}');\n{imports}const d = {json.dumps(data)};\n{body}"
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_next_lock_follows_the_two_part_ladder_and_keeps_the_old_one():
    want = {None: (0.10, 0.11), 0.10: (0.12, 0.15), 0.12: (0.17, 0.20), 0.17: (0.22, 0.25)}
    for lock, (lk, at) in want.items():
        nx = L.next_lock(lock, TWO)
        assert set(nx) == {"lock", "at"} and nx["lock"] == pytest.approx(lk) and nx["at"] == pytest.approx(at), lock
    old = dict(W.LADDER)                          # 10 % at 11 %, then 3 % steps: the very floats of the old formula
    assert L.next_lock(None, old) == {"lock": 0.1, "at": 0.1 + 0.01}
    assert L.next_lock(0.1, old) == {"lock": 0.1 + 0.03, "at": 0.1 + 0.03 + 0.01}
    assert L.next_lock(0.13, old) == {"lock": 0.13 + 0.03, "at": 0.13 + 0.03 + 0.01}
    assert L.next_lock(None, {"first_lock": 0.1, "step": 0.03}) is None and L.next_lock(0.1, {}) is None
    assert L.ladder_numbers(old) == old and L.ladder_numbers(TWO) == TWO
    assert L.ladder_numbers({**old, "next_trigger": 0.15}) == old              # half a second part: the old form


def test_the_open_position_and_the_settings_show_the_two_part_ladder(world):
    _set_ladder(world, TWO)
    d = L.build(world, NOW)
    p = acct(d, "paper")["position"]
    assert p["lock_roe"] == pytest.approx(0.10)                              # locked 10 %: next 12 % at 15 %, then 17 % at 20 %
    nx = p["next_lock"]
    assert nx["lock"] == pytest.approx(0.12) and nx["at"] == pytest.approx(0.15)
    assert nx["then"] == {"lock": pytest.approx(0.17), "at": pytest.approx(0.20)}
    assert nx["price"] == pytest.approx(L.roe_price(1, 62000.0, 40, 0.15, p["round_trip"], p["funding_frac"]))
    assert acct(d, "bybit")["position"]["next_lock"]["then"]["at"] == pytest.approx(0.20)      # the executor follows the paper's
    assert d["paper"]["ladder"] == TWO and L.settings(world, NOW)["rules"]["ladder"] == TWO
    out = _node_mods("""const pa = d.accts.find((a) => a.id === "paper");
      const g = Q.gaugeModel(pa.position, {kind: "paper", mark: 62510, ladder: d.paper.ladder});
      const un = {lock: 0.1, at: 0.11, then: {lock: 0.12, at: 0.15}};
      console.log(JSON.stringify({next2: g.anchors.find((a) => a.k === "next2"), un: Q.afterNext(un, d.paper.ladder),
        old: Q.afterNext({lock: 0.1, at: 0.11}, {step: 0.03}), none: Q.afterNext(null, d.paper.ladder),
        two: M.ladderKo(d.paper.ladder), one: M.ladderKo({first_lock: 0.1, step: 0.03, trigger_gap: 0.01}), no: M.ladderKo({})}));""",
                     d, {"Q": "livebots-hq.js", "M": "livebots-more.js"})
    assert out["next2"]["v"] == pytest.approx(0.20) and out["next2"]["lock"] == pytest.approx(0.17)
    assert out["un"] == {"at": pytest.approx(0.15), "lock": pytest.approx(0.12)}            # 11 % -> 10 %, then 15 % -> 12 %
    assert out["old"] == {"at": pytest.approx(0.14), "lock": pytest.approx(0.13)} and out["none"] is None
    assert out["two"] == "순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%)"
    assert out["one"] == "순ROE 11%에서 10% 잠금, 그 뒤 3%씩 올림" and out["no"] == "—"
    for f in ("livebots-chart.js", "livebots-term.js"):                       # no fixed ladder numbers in the chart key
        assert "그 뒤 3%마다" not in _read(SCREENS, f), f


def test_new_filter_reasons_have_their_own_categories():
    assert L.why_cat("FILTERED", "추격 진입 막기: 롱인데 24시간 고점 쪽(93% 위치)") == ("chase", "추격 진입 막기")
    assert L.why_cat("FILTERED", "추격 진입 막기: 숏인데 7일 범위 아래 20% 안(12% 위치)") == ("chase", "추격 진입 막기")
    for w in ("추격 판단에 쓸 24시간 1분봉이 모자람(진입 안 함)", "추격 판단에 쓸 1분봉을 못 읽음(진입 안 함): OperationalError",
              "추격 판단에 쓸 가격이 없음(진입 안 함)"):
        assert L.why_cat("FILTERED", w) == ("chase_unread", "추격 판단 못 함"), w          # never '조건을 못 읽음'
    assert L.why_cat("FILTERED", "나스닥 개장 뒤 30분 진입 안 함 (뉴욕 09:30 개장)") == ("usopen", "나스닥 개장 뒤")
    assert L.why_cat("FILTERED", "설정이 바뀌어 기다리던 돌파 신호를 버림") == ("config", "설정이 바뀜")
    assert L.why_cat("FILTERED", "주말 진입 안 함")[0] == "weekend"                   # the old ones as before
    assert L.why_words("추격 진입 막기: 롱인데 24시간 고점 쪽(93% 위치)") == "추격 진입 막기: 롱인데 24시간 고점 쪽(93% 위치)"
    m = L.describe_member({"strategy": "S2_ST_ROC", "tf": "1h", "no_chase": True}, 3)
    assert m["no_chase"] is True and m["no_chase_ko"].startswith("추격 진입 막기 (")
    m = L.describe_member({"strategy": "S2_ST_ROC", "tf": "1h"}, 4)
    assert m["no_chase"] is False and m["no_chase_ko"] is None
    for f in ("livebots-more.js", "livebots-rank.js", "livebots-trades.js"):          # the settings, rank and trade screens say it
        assert "추격 진입 막기" in _read(SCREENS, f), f


def test_another_configs_5_year_reference_is_never_shown(world, tmp_path, monkeypatch):
    from paperbot import livecheck as LC
    _running_config(tmp_path, monkeypatch, same=False)
    why = LC.REF_OTHER_CONFIG_KO
    with pytest.raises(ValueError) as e:                                      # load_likely: the guard's reason
        L.load_likely()
    assert isinstance(e.value, LC.RefConfigMismatch) and str(e.value) == why
    lk = L.likely(world, NOW)
    assert lk["state"] == "missing" and lk["reason_ko"] == why and lk["rows"] == []
    assert L.whynow(world, NOW)["likely"]["state"] == "missing" and L.whynow(world, NOW)["likely"]["reason_ko"] == why
    rk = L.rank(world, NOW)
    assert rk["ref"]["state"] == "missing" and rk["ref"]["reason_ko"] == why
    assert rk["ref"]["break_even"] is None and rk["ref"]["fit_win"] is None and rk["ref"]["honest_win"] is None
    assert all(r["bt"] is None and all(m["bt"] is None for m in r["members"]) for r in rk["rows"])   # no per-member numbers
    assert rk["scorecard"]["state"] == "missing" and rk["scorecard"]["reason_ko"] == why
    d = L.build(world, NOW)
    assert d["refs"] is None and d["refs_ko"] == why
    cp = d["checkpoint"]
    assert cp["rule_ko"] == why and cp["trades"] == 40 and cp["n"] == 6 and cp["zone"] is None
    assert cp["up"] is None and cp["low"] is None and cp["up_ko"] is None and cp["mid_ko"] is None and cp["low_ko"] is None
    pf = L.perf(world, NOW)
    assert pf["refs"] is None and pf["checkpoint"]["rule_ko"] == why and pf["scorecard"]["reason_ko"] == why
    mp = L.map_view(world, NOW)
    assert mp["band"] is None and mp["card"]["state"] == "missing" and mp["card"]["reason_ko"] == why
    assert all(r["bt_win"] is None and r["bt_n"] is None for rows in mp["cuts"].values() for r in rows)
    out = _node_mods("""const svg = P.rollChart({roll20: [[1, 0.9], [2, 0.8]], roll40: []}, d.refs, 600), cls = [];
      const go = (n) => { if (!n || !n.childNodes) return; const c = n.getAttribute && n.getAttribute('class'); if (c) cls.push(c); n.childNodes.forEach(go); };
      go(svg); console.log(JSON.stringify({cls}));""", pf, {"P": "livebots-perf.js"})
    assert "r20" in out["cls"] and not {"ref bt", "ref be", "band"} & set(out["cls"])     # no old reference line drawn
    # the same bytes as the references' config: today's answers
    _running_config(tmp_path, monkeypatch, same=True)
    L._cache.clear()
    assert L.load_likely()["source"]["config"] == "deploy/combo.live-ac.json"
    assert L.likely(world, NOW)["state"] == "ok" and L.rank(world, NOW)["ref"]["state"] == "ok"
    d = L.build(world, NOW)
    assert d["refs"] == L.REFS and d["refs_ko"] is None
    assert "rule_ko" not in d["checkpoint"] and d["checkpoint"]["up_ko"] == L.CHECKPOINT["up_ko"]
    assert L.map_view(world, NOW)["band"] is not None
