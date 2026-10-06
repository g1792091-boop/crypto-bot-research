"""Dashboard v4, conv-b (owners 10/06): ★ 즐겨찾기, 차트 그리기 + 이 가격에 알림, 매매법 비교 (#/compare) and TV 자동 넘김.

Server: /api/v4/compare on a hand-built paper3.db (every number computed by hand below), DeepSeek counts only (no money
key anywhere in its item), coin flips never a pick, the 400s, the background answer shape. Pages: the pure helpers in
node (favourites, compare picks, the TV schedule, the drawing geometry and storage, the compare chart data, the 홈
strip numbers), and the wiring that must stay (the existing price-alert route, per-device storage only, the rail /
side panel / 찾기 / key t hooks, the route, the honesty words)."""
import json
import math
import os
import re
import shutil
import subprocess
import sys

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

START = 1_791_200_000_000          # a fixed run start (ms)
H = 3_600_000
INIT = 5000.0


def _read(rel: str) -> str:
    with open(os.path.join(V4, rel), encoding="utf-8") as fh:
        return fh.read()


def _trade(st: Store3, aid: str, t: int, pnl: float, eq: float, sym: str = "BTCUSDT") -> None:
    st.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", (aid, sym, t - H, t, "SL" if pnl < 0 else "LOCK", 30, pnl, pnl / 1500, eq, "{}"))


def _world(path: str) -> str:
    """S1 (15m + 1h), its two coin-flip seeds on the same timeframes, one DeepSeek definition, one extra copy.
    S1@15m: +200 (5200) at +1 h, -100 (5100) at +3 h; S1@1h: -50 (4950) at +2 h."""
    st = Store3(path)
    accts = [("S1@15m", "S1", "15m", "strategy"), ("S1@1h", "S1", "1h", "strategy"),
             ("RANDOM_1@15m", "RANDOM_1", "15m", "random"), ("RANDOM_1@1h", "RANDOM_1", "1h", "random"),
             ("RANDOM_2@15m", "RANDOM_2", "15m", "random"), ("RANDOM_2@1h", "RANDOM_2", "1h", "random"),
             ("F1_RSI_DIV@15m", "F1_RSI_DIV", "15m", "ds200"), ("S1@15m~c1", "S1", "15m", "copy")]
    for aid, s, tf, kind in accts:
        st.add_account(aid, s, tf, kind, START, "paper-v4", "S1@15m" if kind == "copy" else None, {})
    _trade(st, "S1@15m", START + 1 * H, 200.0, 5200.0)
    _trade(st, "S1@1h", START + 2 * H, -50.0, 4950.0)
    _trade(st, "S1@15m", START + 3 * H, -100.0, 5100.0)
    _trade(st, "F1_RSI_DIV@15m", START + 2 * H, 333.0, 5333.0)
    _trade(st, "S1@15m~c1", START + 2 * H, -10.0, 4990.0)
    wallets = {"S1@15m": 5100.0, "S1@1h": 4950.0, "RANDOM_1@15m": 5000.0, "RANDOM_1@1h": 4900.0, "RANDOM_2@15m": 5300.0,
               "RANDOM_2@1h": 5000.0, "F1_RSI_DIV@15m": 5333.0, "S1@15m~c1": 4990.0}
    dd = {"S1@15m": 0.0192, "S1@1h": 0.01}
    eng = {aid: {"wallet": w, "max_drawdown": dd.get(aid, 0.0), "bust": False, "position": None} for aid, w in wallets.items()}
    st.put_state("accounts", START + 4 * H, {"last_ts": START + 4 * H, "engines": eng})
    st.put_state("run", START, {"initial_equity": INIT})
    st.commit()
    st.close()
    return path


@pytest.fixture()
def client(tmp_path):
    from paperbot.dash.app import create_app
    db = _world(str(tmp_path / "paper3.db"))
    return TestClient(create_app(db, None, b"s" * 32))


def _get(client, ids):
    r = client.get("/api/v4/compare", params={"ids": ids})
    assert r.status_code == 200, r.text
    d = r.json()
    for _ in range(20):                       # background + cached: a first slow answer is {pending: true}
        if not d.get("pending"):
            break
        d = client.get("/api/v4/compare", params={"ids": ids}).json()
    return d


# ---------------------------------------------------------------- /api/v4/compare by hand
def test_compare_strategy_numbers_by_hand(client):
    d = _get(client, "S1")
    assert d["label"] == "설명용, 판정 아님" and d["small_n"] == 30 and d["max"] == 4
    (x,) = d["items"]
    assert x["kind"] == "strategy" and x["tfs"] == ["15m", "1h"] and x["accounts"] == 2 and not x["counts_only"]
    assert x["trades"] == 3 and x["wins"] == 1 and x["losses"] == 2 and x["small"] is True
    assert x["w0"] == 10000.0 and x["wallet"] == 10050.0 and math.isclose(x["ret"], 0.005, abs_tol=1e-6)
    # the summed realized curve: 10000 -> 10200 -> 10150 -> 10050 (-> now, the wallets)
    assert x["curve"][:4] == [0.0, 0.02, 0.015, 0.005] and x["curve"][-1] == 0.005
    assert x["t"][:4] == [START, START + H, START + 2 * H, START + 3 * H]
    assert math.isclose(x["mdd"], 1 - 10050 / 10200, abs_tol=1e-6)               # peak 10200, trough 10050
    assert x["mdd_worst"] == 0.0192
    assert math.isclose(x["win_rate"], 1 / 3, abs_tol=1e-6)
    assert math.isclose(x["payoff"], 200 / (150 / 2), abs_tol=1e-6)               # average win / |average loss|
    assert math.isclose(x["pf"], 200 / 150, abs_tol=1e-6)                         # gross win / |gross loss|
    # 동전 봇 순위: RANDOM_1 (5000 + 4900) = -1 %, RANDOM_2 (5300 + 5000) = +3 %: S1's +0.5 % is above one of two
    assert x["flip"] == {"n": 2, "above": 1, "tfs": ["15m", "1h"]}
    t15 = next(r for r in x["by_tf"] if r["tf"] == "15m")
    assert math.isclose(t15["ret"], 0.02, abs_tol=1e-6) and math.isclose(t15["flip_med"], 0.03, abs_tol=1e-6)
    assert math.isclose(t15["vs"], -0.01, abs_tol=1e-6) and t15["trades"] == 2 and math.isclose(t15["win_rate"], 0.5, abs_tol=1e-6)


def test_compare_account_extra_flips_and_unknown(client):
    d = _get(client, "S1@1h,S1@15m~c1,RANDOM_1@1h,NOPE_9@1h")
    assert d["dropped"] == ["RANDOM_1@1h"] and d["unknown"] == ["NOPE_9@1h"]
    a, x = d["items"]
    assert a["id"] == "S1@1h" and a["kind"] == "account" and a["tfs"] == ["1h"]
    assert math.isclose(a["ret"], -0.01, abs_tol=1e-6) and a["mdd"] == 0.01 and a["no_loss"] is False and a["pf"] == 0.0
    assert a["flip"] == {"n": 2, "above": 1, "tfs": ["1h"]}               # -1 %: above RANDOM_1 (-2 %), below RANDOM_2 (0 %)
    # a late-started extra is never compared and has no 5-year side (another rule)
    assert x["extra"] is True and x["flip"] is None and x["y5"] is None and all(r["vs"] is None for r in x["by_tf"])


def test_compare_deepseek_is_counts_only(client):
    from paperbot.dash.analysis import MONEY_KEYS
    d = _get(client, "F1_RSI_DIV,S1")
    ds = d["items"][0]
    assert ds["counts_only"] is True and ds["trades"] == 1 and ds["open"] == 0 and ds["tfs"] == ["15m"]
    banned = set(MONEY_KEYS) | {"ret", "curve", "t", "mdd", "mdd_worst", "win_rate", "wins", "losses", "payoff", "pf", "flip", "y5", "w0", "pnl"}

    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    assert not banned & set(keys(ds)), banned & set(keys(ds))
    assert set(ds["by_tf"][0]) == {"tf", "account_id", "trades", "open"}


def test_compare_rejects_bad_lists(client):
    assert client.get("/api/v4/compare", params={"ids": ""}).status_code == 400
    assert client.get("/api/v4/compare", params={"ids": "a,b,c,d,e"}).status_code == 400
    r = client.get("/api/v4/compare", params={"ids": "S1,<script>"})
    assert r.status_code == 400 and "올바르지" in r.json()["detail"]
    d = _get(client, "S1,S1")                          # duplicates collapse
    assert [x["id"] for x in d["items"]] == ["S1"]


def test_compare_pure_pieces():
    from paperbot.dash.more import compare as C
    ts, vs, mdd = C.realized_curve([(10, "a", 110.0), (20, "b", 90.0), (30, "a", 100.0), (40, "x", 1.0)], {"a": 100.0, "b": 100.0}, 0)
    assert ts == [0, 10, 20, 30] and vs == [200.0, 210.0, 200.0, 190.0] and math.isclose(mdd, 1 - 190 / 210)
    t2, v2 = C.thin(list(range(1000)), list(range(1000)), 10)
    assert len(t2) == 10 and t2[0] == 0 and t2[-1] == 999
    assert C.flip_rank(0.0, ["15m"], [], 5000) is None
    assert C.parse_ids(" a , b ,a") == ["a", "b"]
    assert "compare" in __import__("paperbot.dash.more", fromlist=["MODULES"]).MODULES


def test_compare_route_uses_its_own_background_worker():
    src = open(os.path.join(ROOT, "paperbot", "dash", "more", "compare.py"), encoding="utf-8").read()
    assert "Heavy(wait_s=WAIT_S)" in src and 'heavy.get("compare:"' in src and "TTL_S = 60" in src
    assert "INSERT" not in src and "UPDATE " not in src and "DELETE" not in src            # read-only


# ---------------------------------------------------------------- the pure page helpers in node
def _node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core, scr = "file://" + os.path.join(V4, "core"), "file://" + os.path.join(V4, "screens")
    script = (f"const favs = await import('{core}/favs.js'); const cmp = await import('{core}/cmp.js');"
              f"const tv = await import('{core}/tvmode.js'); const dk = await import('{scr}/draw-kit.js');"
              f"const cp = await import('{scr}/compare.js'); const hf = await import('{scr}/home-favs.js');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_favourites_storage_shape_in_node():
    out = _node("""
    const a = favs.readFavs({strategy: ["S1", "S1", "bad id!", 3, "S2"], account: "x", coin: ["BTCUSDT"]});
    let f = favs.withFav(a, "account", "S1@1h", true);
    f = favs.withFav(f, "strategy", "S3", true);
    f = favs.withFav(f, "strategy", "S1", false);
    let many = {strategy: []};
    for (let i = 0; i < 50; i++) many = favs.withFav(many, "strategy", "S" + i, true);
    console.log(JSON.stringify({a, f, n: many.strategy.length, first: many.strategy[0], junk: favs.readFavs(null), bad: favs.withFav(a, "nope", "x", true)}));
    """)
    assert out["a"] == {"strategy": ["S1", "S2"], "account": [], "coin": ["BTCUSDT"]}
    assert out["f"] == {"strategy": ["S3", "S2"], "account": ["S1@1h"], "coin": ["BTCUSDT"]}      # newest first
    assert out["n"] == 40 and out["first"] == "S49"
    assert out["junk"] == {"strategy": [], "account": [], "coin": []} and out["bad"] == out["a"]


def test_compare_picks_never_take_a_coin_flip_and_stop_at_four():
    out = _node("""
    console.log(JSON.stringify({a: cmp.readPicks("S1, RANDOM_1@1h,S2,S1,S3,S4,S5"), b: cmp.readPicks(["x y", "S1@1h"]), c: cmp.readPicks(null),
      f: cmp.isFlipId("RANDOM_3@5m"), max: cmp.CMP_MAX}));
    """)
    assert out == {"a": ["S1", "S2", "S3", "S4"], "b": ["S1@1h"], "c": [], "f": True, "max": 4}


def test_tv_schedule_in_node():
    out = _node("""
    const d = tv.readTv(null), bad = tv.readTv({on: "yes", secs: 999, screens: ["nope", "home", "home", "board"]});
    console.log(JSON.stringify({d, bad, lo: tv.clampSecs(3), hi: tv.clampSecs(500), nan: tv.clampSecs("x"),
      phone: tv.playable(tv.TV_DEFAULT, false), pc: tv.playable(tv.TV_DEFAULT, true),
      syn: tv.stopOf({name: "analysis", arg: "synergy"}), other: tv.stopOf({name: "analysis", arg: "risk"}), home: tv.stopOf({name: "home", arg: null}),
      n1: tv.nextStop(["terminal", "home", "board"], "board"), n2: tv.nextStop(["terminal", "home"], "rooms"), n3: tv.nextStop([], "home"),
      idle: tv.TV_IDLE_MS, ko: tv.TV_DEFAULT.map(tv.stopKo)}));
    """)
    assert out["d"] == {"on": False, "secs": 30, "screens": ["terminal", "home", "board", "office", "analysis/synergy"]}
    assert out["bad"] == {"on": False, "secs": 120, "screens": ["home", "board"]}
    assert (out["lo"], out["hi"], out["nan"]) == (15, 120, 30)
    assert out["phone"] == ["home", "board", "office", "analysis/synergy"] and out["pc"][0] == "terminal"
    assert out["syn"] == "analysis/synergy" and out["other"] is None and out["home"] == "home"
    assert out["n1"] == "terminal" and out["n2"] == "terminal" and out["n3"] is None
    assert out["idle"] == 60000 and out["ko"] == ["터미널", "홈", "계좌 순위", "회의실", "조합 시너지"]


def test_drawing_geometry_and_storage_in_node():
    out = _node("""
    const bars = [{time: 0}, {time: 900}, {time: 1800}, {time: 3600}];          // a gap between the last two bars
    const L = [0, 450, 1800, 2700, 3600, 4500, -900].map((t) => dk.logicalOf(bars, t, 900));
    const T = L.map((l) => dk.timeOf(bars, l, 900));
    const shapes = dk.readShapes([{id: "a1", t: "h", p: 100}, {id: "b2", t: "line", a: {x: 1.4, p: 1}, b: {x: 9, p: 2}}, {id: "c3", t: "rect", a: {x: 1, p: 1}},
      {id: "d4", t: "text", a: {x: 1, p: 1}, s: "  " + "가".repeat(80)}, {id: "e5", t: "text", a: {x: 1, p: 1}, s: "   "}, {id: "BAD", t: "h", p: 1},
      {id: "f6", t: "circle", p: 1}, {id: "g7", t: "h", p: Infinity}]);
    const many = dk.readShapes(Array.from({length: 60}, (_, i) => ({id: "s" + i, t: "h", p: i})));
    const g = {a: {x: 0, y: 0}, b: {x: 100, y: 100}};
    console.log(JSON.stringify({L, T, shapes, n: many.length, first: many[0].id, key: dk.shapeKey("BTCUSDT", "15m"),
      seg: [dk.segDist(50, 0, 0, 0, 100, 0), dk.segDist(150, 0, 0, 0, 100, 0), dk.segDist(5, 5, 0, 0, 0, 0)],
      hit: [dk.hitTest({t: "h"}, {y: 50}, 10, 55), dk.hitTest({t: "h"}, {y: 50}, 10, 70), dk.hitTest({t: "line"}, g, 50, 52),
        dk.hitTest({t: "line"}, g, 2, 1), dk.hitTest({t: "line"}, g, 98, 99), dk.hitTest({t: "line"}, g, 80, 10), dk.hitTest({t: "rect"}, g, 50, 30),
        dk.hitTest({t: "rect"}, g, 150, 30), dk.hitTest({t: "text"}, {x: 10, y: 50, w: 60, h: 20}, 30, 40), dk.hitTest({t: "line"}, null, 1, 1)],
      round: [dk.roundPrice(65432.123), dk.roundPrice(0.118234567), dk.roundPrice(145.6789)]}));
    """)
    assert out["L"] == [0, 0.5, 2, 2.5, 3, 4, -1]                  # inside the gap: half way between the two bars
    assert out["T"] == [0, 450, 1800, 2700, 3600, 4500, -900]      # timeOf is the inverse
    assert [s["id"] for s in out["shapes"]] == ["a1", "b2", "d4"] and out["shapes"][1]["a"] == {"x": 1, "p": 1}
    assert len(out["shapes"][2]["s"]) == 60
    assert out["n"] == 40 and out["first"] == "s20" and out["key"] == "draw-BTCUSDT-15m"
    assert out["seg"][0] == 0 and out["seg"][1] == 50 and math.isclose(out["seg"][2], math.hypot(5, 5))
    assert out["hit"] == ["body", None, "body", "a", "b", None, "body", None, "body", None]
    assert out["round"] == [65432.1, 0.11823, 145.68]


def test_compare_chart_data_and_picker_in_node():
    out = _node("""
    const data = cp.lineData([1000, 1500, 2000, 2000, 1999, null, 5000], [0, 0.1, 0.2, 0.3, 0.4, 0.5, null]);
    const board = {initial: 5000, accounts: [{account_id: "S1@15m", strategy: "S1", kind: "strategy", timeframe: "15m"},
      {account_id: "S1@1h", strategy: "S1", kind: "strategy", timeframe: "1h"}, {account_id: "RANDOM_1@1h", strategy: "RANDOM_1", kind: "random", timeframe: "1h"},
      {account_id: "F1_X@15m", strategy: "F1_X", kind: "ds200", timeframe: "15m"}]};
    const items = cp.pickables(board);
    console.log(JSON.stringify({data, ids: items.map((x) => x.id), find: cp.findPicks(items, "s1", ["S1@1h"]).map((x) => x.id), none: cp.findPicks(items, " ", [])}));
    """)
    assert out["data"] == [{"time": 1, "value": 0.1}, {"time": 2, "value": 0.4}]
    assert out["ids"] == ["S1", "F1_X", "S1@15m", "S1@1h", "F1_X@15m"]          # strategies first; no coin flip
    assert out["find"] == ["S1", "S1@15m"] and out["none"] == []


def test_home_strip_counts_deepseek_and_flips_only_in_node():
    out = _node("""
    const board = {initial: 5000, accounts: [
      {account_id: "S1@15m", strategy: "S1", kind: "strategy", timeframe: "15m", group: "core", wallet: 5100, trades: 3},
      {account_id: "S1@1h", strategy: "S1", kind: "strategy", timeframe: "1h", group: "core", wallet: 4950, trades: 1},
      {account_id: "F1_X@15m", strategy: "F1_X", kind: "ds200", timeframe: "15m", group: "ds200", wallet: 9000, trades: 7},
      {account_id: "RANDOM_1@1h", strategy: "RANDOM_1", kind: "random", timeframe: "1h", group: "flip", wallet: 6000, trades: 2}]};
    const r = (k, id) => hf.favNumbers(k, id, board);
    console.log(JSON.stringify({s: r("strategy", "S1"), ds: r("strategy", "F1_X"), flip: r("account", "RANDOM_1@1h"), dsa: r("account", "F1_X@15m"),
      gone: r("account", "S9@1h")}));
    """)
    assert math.isclose(out["s"]["ret"], 0.005) and out["s"]["trades"] == 4 and out["s"]["countOnly"] is False
    for k in ("ds", "flip", "dsa"):
        assert out[k]["countOnly"] is True and out[k]["ret"] is None, k
    assert out["ds"]["trades"] == 7 and out["gone"]["missing"] is True


# ---------------------------------------------------------------- the wiring that must stay
def test_alerts_go_through_the_existing_route_only():
    dk = _read("screens/draw-kit.js")
    assert 'ctx.post("/api/price-alerts", {symbol: sym, price})' in dk
    code = re.sub(r"(?m)^\s*//.*$", "", dk)
    assert set(re.findall(r"/api/[a-z0-9/_-]*", code)) == {"/api/price-alerts"}            # no other route
    assert len(re.findall(r"ctx\.post\(", code)) == 1                                       # one write: the alert
    assert '"contextmenu"' in dk and "LONG_MS = 550" in dk and 'e.pointerType === "touch"' in dk
    assert "(e && e.detail) ||" in dk                                                      # the server's own Korean words
    term, chart = _read("screens/terminal-chart.js"), _read("screens/chart.js")
    assert "drawTools({ctx, chart: C.chart" in term and "drawTools({ctx, chart: C.chart" in chart
    assert 'ctx.api("/api/price-alerts")' in term and 'deck.setLines("al"' in term
    assert "onAlertAdded: () => panels.alerts().load()" in chart
    for css in ("screens/terminal.css", "screens/chart.css"):
        assert '@import url("draw-kit.css");' in _read(css)


def test_per_device_storage_and_text_rules():
    files = ["core/favs.js", "core/favpop.js", "core/cmp.js", "core/tvmode.js", "screens/draw-kit.js", "screens/compare.js", "screens/home-favs.js"]
    for rel in files:
        src = _read(rel)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "localStorage"):
            assert bad not in src, (rel, bad)
    assert 'local.get(FAV_KEY' in _read("core/favs.js") and 'local.get(CMP_KEY' in _read("core/cmp.js")
    assert 'local.get(TV_KEY' in _read("core/tvmode.js") and "local.set(st.key" in _read("screens/draw-kit.js")
    for rel in ("core/favs.css", "core/tvmode.css", "screens/draw-kit.css", "screens/compare.css", "screens/home-favs.css"):
        css = re.sub(r"/\*.*?\*/", "", _read(rel), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*\d", css), rel
        for m in re.finditer(r"font(?:-size)?\s*:\s*([^;}]+)", css):
            assert "var(--t-" in m.group(1) or m.group(1).strip() == "inherit", (rel, m.group(1))


def test_tv_mode_wiring():
    tv, nav, main = _read("core/tvmode.js"), _read("core/navkeys.js"), _read("core/main.js")
    assert 'e.code === "KeyT"' in nav and "toggleTv()" in nav and "startTvMode();" in main
    assert 'navigator.wakeLock.request("screen")' in tv and "catch (e) { st.lock = \"none\"; }" in tv
    for ev in ("pointerdown", "keydown", "wheel", "touchstart"):
        assert f'"{ev}"' in tv
    assert "TV_IDLE_MS = 60000" in tv and "TV_MIN = 15, TV_MAX = 120" in tv
    assert 'html[data-tv="on"] .rail { display: none !important; }' in _read("core/tvmode.css")
    # the left rail has the TV button; the menu strip (which replaced the group bar's sub tabs) has none: below 1200 px and
    # with the menu on top TV mode starts from the 설정 panel's section (tvSection) or the key t
    assert "tvRailBtn()" in _read("core/rail.js") and "tvTab" not in _read("core/shell.js")
    assert "export function tvSection(" in tv                                          # the 설정 panel's section
    st = _read("core/settings.js")
    assert 'import {tvSection} from "./tvmode.js";' in st and "tvSection(() => closeSettings())" in st and "tvPanelSection()," in st
    # a PC window hides the menu strip too while it runs (the strip is the menu there, like the rail)
    assert 'html[data-tv="on"] .subtabs { display: none; }' in _read("core/tvmode.css")


def test_favourites_wiring():
    # ONE ★ per layout: the rail's foot (menu on the left), the top bar's #toptools (a PC with the menu on top), the end of
    # the menu strip (below 1200 px); the popup drops down from the last two
    assert "favRailBtn()" in _read("core/rail.js")
    sh = _read("core/shell.js")
    assert "favTopBtn(), gearButton());" in sh and "oldLink(), favTab(), settingsTab()]," in sh
    pop = _read("core/favpop.js")
    assert 'export const favTopBtn = () => favButton("favrail favtop");' in pop and 'export const favTab = () => favButton("favsub", "즐겨찾기");' in pop
    assert 'title: "즐겨찾기"' in pop and "anchor.closest(\".rail\")" in pop
    dr = _read("core/drawer.js")
    assert "starBtn(favKind, spec.id, {text: true}), cmpBtn(spec.id)" in dr
    assert "...favItems()" in _read("core/find.js")
    assert "favStrip(ctx)" in _read("screens/home.js")
    assert 'memo: "strat-favonly"' in _read("screens/strategies-list.js") and 'memo: "acp-favonly"' in _read("screens/account-pick.js")
    assert "favs: true" in _read("screens/board.js") and "if (only) rows = rows.filter(only);" in _read("screens/board-table.js")
    assert 'fav.starBtn("coin", st.sym' in _read("screens/terminal-top.js") and 'fav.starBtn("coin", st.sym' in _read("screens/chart.js")


def test_compare_route_and_honesty_words():
    routes = _read("core/routes.js")
    assert '"strategies", "grid", "analysis", "compare", "path", "combo", "combo5y", "whatif"' in routes and 'compare: {ko: "비교", group: "strat", title: "매매법 비교"}' in routes
    page = _read("screens/compare.js")
    assert "/api/v4/compare?ids=" in page and "progressBar(" in page and '"채워지는 중"' in page and "ui.refNote(" in page and "ui.assume(" in page
    assert "if (!items.length) {" in page and "kids.push(emptyCard());" in page         # all unknown / flips: no empty tables
    assert "거래 수만" in page and "설명용, 판정 아님" in page and 'ctx.href("analysis", "synergy")' in page
    assert "--pick-1" in _read("tokens.css") and "--draw:" in _read("tokens.css")
    inv = _read("INVENTORY.md")
    assert "## conv-b:" in inv and "#/compare" in inv and "TV 자동 넘김" in inv


# ---------------------------------------------------------------- review fixes (conv-b review)
def _mini_trades(rows):
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, exit_time INTEGER, equity_after REAL)")
    c.executemany("INSERT INTO trades (account_id, exit_time, equity_after) VALUES (?,?,?)", rows)
    return c


def test_compare_drawdown_counts_the_last_point_of_the_line():
    """An open position's entry fee and funding are already out of the wallet: the line's last point (the wallets now)
    falls below the last closed trade, and the 합친 곡선 최대 낙폭 must count that fall (the chart shows it)."""
    from paperbot.dash.more import compare as C
    c = _mini_trades([("A@15m", START + H, 5200.0)])                  # 5000 -> 5200 (the peak)
    board = {"initial": INIT, "accounts": [{"account_id": "A@15m", "strategy": "A", "timeframe": "15m", "kind": "strategy",
                                            "group": "core", "created_ts": START, "wallet": 5148.0, "trades": 1, "wins": 1,
                                            "losses": 0, "gross_win": 200.0, "gross_loss": 0.0, "max_drawdown": 0.02,
                                            "position": {"symbol": "BTCUSDT"}}]}
    x = C.item(c, "A", board, {}, START + 2 * H)
    assert x["curve"] == [0.0, 0.04, 0.0296] and x["open"] == 1
    assert math.isclose(x["mdd"], 1 - 5148 / 5200, abs_tol=1e-6)        # was 0: the last point was left out
    assert C.max_drawdown([100.0, 120.0, 90.0, 130.0, 117.0]) == 0.25 and C.max_drawdown([]) == 0.0


def test_compare_five_year_side_says_when_the_research_exit_differs(monkeypatch):
    from paperbot.dash.more import compare as C
    from paperbot.dash.more import vs5y
    monkeypatch.setattr(vs5y, "five_year", lambda s: ("1x", {"5m": {"per_day": 3.0, "roe": 0.001, "win": 0.5, "hold_h": 0.5, "lock": None}},
                                                       {"source": "binance_futures", "exit": "bb_mid", "same_exits_as_live": False}))
    y = C._y5("REEL_H1", ["5m"])
    assert y["unit"] == "1x" and y["exit"] == "bb_mid" and y["same_exits_as_live"] is False and y["rows"][0]["tf"] == "5m"
    assert C._y5("REEL_H1", ["15m"]) is None                            # no row for the item's timeframes: no side


def test_compare_page_never_says_the_research_used_todays_rules():
    page = _read("screens/compare.js")
    assert "지금과 같은 규칙" not in page                                     # the 36's cards used the v3 leverage rule
    assert "v3 배수" in page and "same_exits_as_live === false" in page and "신호를 모두 따로 잡아서" in page
    assert "x.trades < SMALL ? h(\"small\", {class: \"muted\"}, \" · 표본 적음\")" in page   # a coin-flip rank on a few trades


def test_chart_alert_never_promises_a_ring_while_the_sender_is_off():
    dk = _read("screens/draw-kit.js")
    assert "a.sender_alive" in dk and "features.priceSender" in dk
    assert "켜지면 그때부터 울립니다" in dk and "지금은 보내는 프로그램이 꺼져 있어" in dk


def test_a_finger_drawing_or_moving_a_drawing_does_not_scroll_the_page():
    """Phones: with a tool picked the chart takes the finger (touch-action none); moving a picked drawing with no tool
    stops the page scroll in touchmove (checked in a browser: the page scrolled 127 px / 65 px under the finger before)."""
    assert ".drw-drawing, .drw-drawing * { touch-action: none; }" in _read("screens/draw-kit.css")
    dk = _read("screens/draw-kit.js")
    assert 'wrap.addEventListener("touchmove", (e) => { if (st.drag || st.draft) e.preventDefault(); }, {capture: true, passive: false});' in dk


def test_rail_star_count_and_home_strip_size():
    """The rail's ★ count follows a star change before its list was ever opened (the listener is module level), and the
    홈 strip shows at most 20 chips (CONTRACT: about 20 rows at once)."""
    pop = _read("core/favpop.js")
    assert "\nonFavs(() => { paintBtn(); if (st.pop && !st.pop.hidden) paint(); });" in pop
    strip = _read("screens/home-favs.js")
    assert "const CHIPS = 20;" in strip and "kids.slice(0, CHIPS)" in strip


def test_tv_remembered_on_with_nothing_to_show_turns_itself_off():
    """A narrow window that remembered 'on' with 터미널 alone: TV mode is off there (checked in a browser: before, the
    page kept 'on' with no rotation, so t answered 'TV 자동 넘김을 끝냈습니다')."""
    tv = _read("core/tvmode.js")
    assert "if (c.on) { c.on = false; save(); paintChip(); }" in tv


def test_compare_deepseek_only_shows_the_count_rows():
    page = _read("screens/compare.js")
    assert 'items.every((x) => x.counts_only) ? rowsIn.filter((r) => r.money === false) : rowsIn' in page
    assert "딥시크 정의의 5년 연구 숫자는 섞인 화면에서 보이지 않습니다" in page
    assert '!x.trades ? h("span", {class: "muted"}, "거래 전 (아직 견줄 것 없음)")' in page        # no rank before a trade
    assert "autoscaleInfoProvider: minSpan" in page


def test_rail_foot_packs_five_to_a_row():
    """★ 즐겨찾기 · TV · 설정 · 화면 색 · 예전 화면 in the rail's foot: one row of five small buttons on a PC (the gear of conv-a
    joined the two of conv-b), 글자 크기 under them, so the screen rows above still fit at 1280 x 800 (checked in a browser:
    stacked one per row they scrolled the rail and hid the 서버 group's last rows)."""
    css = re.sub(r"/\*.*?\*/", "", _read("core/nav.css"), flags=re.S)
    assert ".rail-tools { display: grid; grid-template-columns: repeat(5, 26px);" in css
    assert ".rail-tools .textcyc { grid-column: 1 / -1; }" in css
    assert ".rail .favrail, .rail .tvbtn, .rail .setcyc, .rail .skincyc, .rail .rail-old { width: 26px; height: 26px; padding: 0; }" in css
