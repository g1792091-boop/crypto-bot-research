"""fill-people: 순위표 · 계좌 · 회의실 · 판정 · 에이전트 방 · 토론방 filled with real records.

- dash/more/people.py on a small synthetic paper3.db: today's closes per group since 00:00 KST (DeepSeek and the coin
  flips COUNTED ONLY: no P&L key), today's loss cards (losing closes of the 36 and the 5-minute strategy), each of the
  36's newest trade / signal, one strategy's record; read-only, behind the login, registered in MODULES;
- the pure JS helpers in node: the live ROE chip only for money groups, the dense table hides money for DeepSeek / coin
  rows in a mixed list, the coin chart's zoom window and crowded labels, the countdown, the checkpoint pace, the
  strategy room's latest-event line;
- wiring greps: the 카드 / 표 toggle is remembered, the analysis link row, the 상황판 next to the 대표실, the 토론방 tab is
  soft (greyed '꺼짐' pill), new CSS uses tokens only (font sizes only var(--t-*)).
"""
import calendar as _cal
import json
import os
import re
import shutil
import sqlite3
import subprocess

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import people as P  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

H = 3_600_000
MIN = 60_000
PW = "correct horse battery"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
START = _cal.timegm((2026, 10, 5, 18, 35, 0)) * 1000        # 03:35 KST 10/06
NOW = START + 10 * H                                           # 13:35 KST 10/06
MIDNIGHT = _cal.timegm((2026, 10, 5, 15, 0, 0)) * 1000        # 00:00 KST 10/06
ACCTS = {"S1@15m": ("S1", "strategy"), "S1@1h": ("S1", "strategy"), "S2@15m": ("S2", "strategy"),
         "D1@15m": ("D1", "ds200"), "RANDOM_1@15m": ("RANDOM_1", "random"), "REEL@5m": ("REEL", "reel"),
         "S1@15m~c1": ("S1", "copy")}


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _trade(c, aid, t, pnl, reason="SL", side=1):
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data)"
              " VALUES (?,?,?,?,?,?,?,?,?,?)", (aid, "LTCUSDT", t - H, t, reason, 30, pnl, pnl / 1000, 5000 + pnl,
                                                json.dumps({"side": side})))


def make_db(path):
    st = Store3(path)
    for aid, (s, kind) in ACCTS.items():
        tf = aid.split("@")[1].split("~")[0]
        st.add_account(aid, s, tf, kind, START, "paper-v4", None, {})
    c = st.conn
    _trade(c, "S1@15m", MIDNIGHT - 10 * MIN, 50.0)                  # yesterday (KST): not today
    _trade(c, "S1@15m", START + 1 * H, 200.0, "LOCK", -1)
    _trade(c, "S1@1h", START + 2 * H, -100.0)
    _trade(c, "S2@15m", START + 3 * H, -40.0)
    _trade(c, "D1@15m", START + 1 * H, 300.0)
    _trade(c, "D1@15m", START + 2 * H, -10.0)
    _trade(c, "RANDOM_1@15m", START + 2 * H, -5.0)
    _trade(c, "REEL@5m", START + 4 * H, -7.0)
    _trade(c, "S1@15m~c1", START + 4 * H, 11.0)
    c.execute("INSERT INTO signal_log (bar_close, timeframe, strategy, symbol, side, status, data) VALUES (?,?,?,?,?,?,?)",
              (START + 5 * H, "30m", "S1", "BTCUSDT", 1, "SUBMITTED", "{}"))
    c.execute("INSERT INTO signal_log (bar_close, timeframe, strategy, symbol, side, status, data) VALUES (?,?,?,?,?,?,?)",
              (START + 30 * MIN, "15m", "S2", "ETHUSDT", -1, "FILTERED", "{}"))
    st.commit()
    st.conn.close()
    return path


@pytest.fixture
def db(tmp_path):
    return make_db(str(tmp_path / "paper3.db"))


def test_kst_midnight():
    assert P.kst_midnight(NOW) == MIDNIGHT
    assert P.kst_midnight(MIDNIGHT) == MIDNIGHT
    assert P.kst_midnight(MIDNIGHT - 1) == MIDNIGHT - 24 * H


def test_today_counts_groups_and_never_money_for_deepseek_or_flips(db):
    d = P.today_view(db, NOW)
    g = d["groups"]
    assert g["core"] == {"n": 3, "wins": 1, "losses": 2, "pnl": 60.0}          # yesterday's close left out
    assert g["ds"] == {"n": 2, "wins": 1, "losses": 1} and "pnl" not in g["ds"]
    assert g["coin"] == {"n": 1, "wins": 0, "losses": 1} and "pnl" not in g["coin"]
    assert g["m5"]["pnl"] == -7.0 and g["extra"]["n"] == 1
    assert d["loss_cards"] == 3                                                # 2 losing closes of the 36 + 1 reel
    assert d["since"] == MIDNIGHT


def test_strats_and_one_strategy_record(db):
    s = P.strats_view(db, NOW)["strats"]
    assert set(s) == {"S1", "S2"}                                              # the 36 only
    assert s["S1"]["trade"]["timeframe"] == "1h" and s["S1"]["signal"]["timeframe"] == "30m"
    assert s["S2"]["signal"]["status_ko"] == "규칙으로 건너뜀"
    r = P.strat_view(db, "S1", NOW)
    assert r["today"]["15m"] == {"n": 1, "wins": 1, "pnl": 200.0} and r["today"]["1h"]["n"] == 1
    assert r["closed"] == 3 and r["trades"][0]["timeframe"] == "1h" and r["trades"][1]["side"] == -1
    assert r["signals"][0]["symbol"] == "BTCUSDT"
    assert P.strat_view(db, "NOPE", NOW)["closed"] == 0


def test_missing_database_answers_honestly(tmp_path):
    assert P.today_view(str(tmp_path / "none.db"), NOW)["error"] == "paper3.db 없음"
    assert P.strats_view(str(tmp_path / "none.db"), NOW)["strats"] == {}


def test_routes_read_only_behind_login_and_registered(db):
    from paperbot.dash.more import MODULES
    assert "people" in MODULES
    before = os.path.getmtime(db)
    c = TestClient(create_app(db, hash_password(PW), b"x" * 32))
    assert c.get("/api/v4/people/today").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    t = c.get("/api/v4/people/today").json()
    assert set(t) >= {"since", "groups", "loss_cards", "computed_at"}
    assert "pnl" not in t["groups"].get("ds", {}) and "pnl" not in t["groups"].get("coin", {})
    assert isinstance(c.get("/api/v4/people/strats").json()["strats"], dict)
    assert c.get("/api/v4/people/strat?name=S1").json()["strategy"] == "S1"
    assert c.get("/api/v4/people/strat").json()["error"]
    assert os.path.getmtime(db) == before
    src = open(os.path.join(ROOT, "paperbot", "dash", "more", "people.py"), encoding="utf-8").read()
    assert "ro_connect" in src and "INSERT" not in src and "UPDATE " not in src and "requests" not in src


# ---------------------------------------------------------------- JS logic in node
def _node(body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    base = "file://" + os.path.join(V4, "screens")
    pre = ("globalThis.localStorage = {getItem: () => null, setItem: () => {}, removeItem: () => {}};"
           "globalThis.matchMedia = () => ({matches: false, addEventListener() {}});"
           "globalThis.document = {createElement: () => ({}), visibilityState: 'visible', addEventListener() {}};"
           "globalThis.window = globalThis; globalThis.location = {hash: ''};\n")
    script = pre + body.replace("@S", base)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and ("document" in r.stderr or "is not defined" in r.stderr):
        pytest.skip("module needs a browser: " + r.stderr.strip().splitlines()[-1][:200])
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_chart_window_and_crowded_labels():
    out = _node("""
const A = await import('@S/account-pick.js');
const data = Array.from({length: 400}, (_, i) => ({time: 1000 + i * 900}));
const w1 = A.chartWindow(data, [{entry_time: (1000 + 300 * 900) * 1000 + 5}], 900);
const w2 = A.chartWindow(data, [], 900);
const w3 = A.chartWindow(data.slice(0, 50), [], 900);
const few = A.markLabels(3, w1), many = A.markLabels(14, w1), lots = A.markLabels(60, w1);
const t = {side: 1, leverage: 30, exit_reason: 'LOCK', roe: 0.2};
console.log(JSON.stringify({w1, w2, w3, few: [few.level, few.entry(t)], many: [many.level, many.entry(t), many.exit(t)], lots: [lots.level, lots.entry(t)]}));
""")
    assert out["w1"] == {"from": 260, "to": 402}             # the first trade minus 40 bars through now
    assert out["w2"] == {"from": 240, "to": 402} and out["w3"] is None
    assert out["few"] == ["full", "롱 30배"]
    assert out["many"][0] == "short" and out["many"][1] == "롱30" and "%" in out["many"][2]
    assert out["lots"] == ["bare", ""]


def test_table_money_rule_and_sort():
    out = _node("""
const T = await import('@S/board-table.js');
const rows = [{account_id: 'a', kind: 'strategy', ret: 0.1, _rk: 2, wallet: 5500}, {account_id: 'b', kind: 'ds200', ret: 0.5, _rk: 1, wallet: 7500},
  {account_id: 'c', kind: 'random', ret: -0.2, _rk: 3, wallet: 4000}];
const ok = (g) => rows.map((a) => T.moneyOk(a, g));
console.log(JSON.stringify({all: ok('all'), ds: ok('ds'), coin: ok('coin'), core: ok('core'),
  byRetAll: T.sortRows(rows, 'ret', 1, 'all').map((a) => a.account_id), byRk: T.sortRows(rows, 'rk', 1, 'ds').map((a) => a.account_id), page: T.PAGE}));
""")
    assert out["all"] == [True, False, False]                 # a mixed list: DeepSeek / coin flips counted only
    assert out["ds"] == [True, True, False] and out["coin"] == [True, False, True]
    assert out["byRetAll"][0] == "a"                         # money-less rows never sort by money
    assert out["byRk"] == ["b", "a", "c"] and out["page"] == 50


def test_countdown_pace_and_room_line():
    out = _node("""
const W = await import('@S/office-wall.js');
const C = await import('@S/checkpoint-stage.js');
const R = await import('@S/rooms-record.js');
const now = 1_000_000_000;
console.log(JSON.stringify({
  cd: [W.countdown(now + 9_027_000, now), W.countdown(now + 65_000, now), W.countdown(now - 1, now), W.countdown(null, now)],
  open: W.openByGroup({accounts: [{kind: 'strategy', position: {}}, {kind: 'ds200', position: {}}, {kind: 'ds200'}, {kind: 'random', position: {}}]}),
  reach: [C.reachTs(10, 86400000, now), C.reachTs(30, 86400000, now), C.reachTs(0, 86400000, now)],
  ev: R.latestEventKo({trade: {exit_time: 5, timeframe: '1h', symbol: 'LTCUSDT', side: -1, exit_reason: 'LOCK', roe: 0.2}, signal: {bar_close: 9, timeframe: '30m', symbol: 'BTCUSDT', side: 1, status_ko: '진입 신호'}}),
  none: R.latestEventKo({}), strat: [R.stratOf('strat:V4.3_TREND'), R.stratOf('team:lead')]}));
""")
    assert out["cd"] == ["2:30:27", "01:05", None, None]
    assert out["open"] == {"core": 1, "ds": 1, "coin": 1}
    assert out["reach"][0] == 1_000_000_000 + 2 * 86400000 and out["reach"][1] is None and out["reach"][2] is None
    assert out["ev"]["ts"] == 9 and "BTC" in out["ev"]["text"] and "신호" in out["ev"]["text"]
    assert out["none"] is None and out["strat"] == ["V4.3_TREND", None]


# ---------------------------------------------------------------- wiring and style
def test_wiring():
    hs = _read("screens", "home-shared.js")
    assert 'ROE_GROUPS = new Set(["core", "m5", "extra"])' in hs and "export function paintRoe" in hs
    b = _read("screens", "board.js")
    assert 'local.get("board-view", "card")' in b and 'local.set("board-view", id)' in b
    assert 'href("analysis", "sessions")' in b and 'ctx.watch("ticker"' in b
    a = _read("screens", "account.js")
    assert "accountPicker(" in a and "setVisibleLogicalRange(win)" in a and "profDraws ? null : eqCard" in a
    assert re.search(r"backLink\(\), headSlot, same \? same\.el : null, candleCard", a)
    of = _read("screens", "office-floor.js")
    assert "st.wall.style.order = \"1000\"" in of
    o = _read("screens", "office.js")
    assert "makeWall(ctx)" in o and "countdown(n && n.at_ms)" in o
    assert "leaderBox()" in _read("screens", "checkpoint-stage.js")
    assert "recordBox(ctx" in _read("screens", "rooms-chat.js") and "latestEventKo(" in _read("screens", "rooms.js")
    r = _read("core", "routes.js")
    assert 'debate: {ko: "토론방", group: "agents", title: "24시간 토론방", soft: "debate"}' in r
    assert "SCREENS[n].soft && !features[SCREENS[n].soft]" in _read("core", "shell.js")
    assert "아직 시작 전 · 켜면 하루 종일 토론" in _read("screens", "debate.js")
    inv = _read("INVENTORY.md")
    assert "fill-people" in inv


NEW_JS = ["board-table.js", "account-pick.js", "office-wall.js", "rooms-record.js"]


def test_new_css_and_js_use_tokens_only():
    for name in ["board.css", "account.css", "office.css", "checkpoint.css", "rooms.css"]:
        src = _read("screens", name)
        tail = src.split("fill-people", 1)[1] if "fill-people" in src else ""
        assert tail, name
        for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", tail):
            sizes = re.findall(r"\d+px", m.group(1))
            assert not sizes, (name, m.group(0))
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", tail), name
        assert not re.search(r"rgba?\(", tail), name
    for name in NEW_JS:
        js = _read("screens", name)
        assert "fontSize" not in js and "font-size" not in js, name
