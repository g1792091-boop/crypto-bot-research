"""실거래 › 한눈에 (#/livebots/hq, 관제 until 10/21, screens/livebots-hq.js + livebots-hq.css): the control room of the two real-money executors.

- the geometry and the rules are pure functions, run here in node on the hand-made live world (tests/livebots_world.py):
  the light ring (20 squares, the threshold), the gauge (stop → entry → next lock steps, the needle on the step scale), the
  first lock and 손익비, the day's dial (pause arcs, today's entries), the tiles (this week's signals → brightness), the ring
  of strategies (arcs by settings, the torus points, the projection, the fit), DAY n, the × badge, the milestones
  (celebrated once, never for the past), the result card's trade, the 실시간 feed, the ticker (only numbers the server sent)
- the whole view renders in node (the tiny DOM) on the real answers: no null / undefined / NaN, 못 읽음 / 수집 전 for what
  cannot be read, never a zero for what is unknown
- static: tokens only in the css (no colour literal, every font size a --t-* token), the three endpoints it polls, no HTML
  parsing, no order button, the css reached through livebots.css
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("fastapi")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-hq.js")
CSS = os.path.join(SCREENS, "livebots-hq.css")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
NOW, T0, H, MIN, DAY = W.NOW, W.T0, W.H, W.MIN, W.DAY


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    L._cache.clear()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent")
    yield
    L._cache.clear()


@pytest.fixture
def world(tmp_path):
    return W.build_world(str(tmp_path / "w"))


def answers(p, now=NOW):
    return {"d": L.build(p, now), "now": L.whynow(p, now), "cal": L.calendar(p, now), "rank": L.rank(p, now)}


def _node(body: str, data: dict):
    """Runs `body` with M = livebots-hq.js (the tiny DOM loaded first) and A = the answers; prints the last JSON line."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    script = (f"await import('file://{DOM}');\n"
              f"const M = await import('file://{JS}');\n"
              f"const A = JSON.parse({json.dumps(json.dumps(data))});\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- geometry
def test_circle_arcs_clock_and_countdown():
    out = _node("""console.log(JSON.stringify({
      top: M.polar(100, 100, 50, 0), right: M.polar(100, 100, 50, 90), bottom: M.polar(100, 100, 50, 180),
      a1: M.arcPath(100, 100, 50, 0, 90), a2: M.arcPath(100, 100, 50, 0, 270), full: M.arcPath(100, 100, 50, 0, 400), back: M.arcPath(100, 100, 50, 30, 10),
      c: [M.clockOf(0), M.clockOf(59.9), M.clockOf(3725), M.clockOf(2 * 86400 + 61), M.clockOf(-5), M.clockOf(null), M.clockOf(NaN)],
    }));""", {})
    assert [round(v, 6) for v in out["top"]] == [100, 50] and [round(v, 6) for v in out["right"]] == [150, 100]
    assert [round(v, 6) for v in out["bottom"]] == [100, 150]
    assert out["a1"] == "M100.00 50.00A50 50 0 0 1 150.00 100.00"
    assert " 0 1 1 " in out["a2"] and " 0 1 1 " in out["full"] and out["full"].startswith("M100.00 50.00")    # a full turn is drawn, not nothing
    assert out["back"].endswith("75.00 56.70") or " 0 0 1 " in out["back"]                                      # never a negative arc
    assert out["c"] == ["00:00:00", "00:00:59", "01:02:05", "2일 00:01:01", "00:00:00", "—", "—"]


def test_the_light_ring_is_the_executors_own_squares_and_threshold(world):
    d = L.build(world, NOW)
    out = _node("""const by = (id) => A.d.execs.find((x) => x.id === id);
      const m = M.ringModel(by("bybit").light), x = M.ringModel(by("mexc").light);
      console.log(JSON.stringify({n: m.n, segs: m.segs.map((s) => s.v), a0: m.segs[0].a0, a1: m.segs[0].a1, last: m.segs[19].a1, wins: m.wins, have: m.have,
        need: m.need, needA: m.needA, winA: m.winA, mneed: x.need, off: M.ringModel({state: "off", n: 0}), none: M.ringModel(null)}));""", {"d": d})
    assert out["n"] == 20 and out["segs"][:14] == [None] * 14 and out["segs"][14:] == [True, True, False, True, True, True]
    assert out["a0"] == pytest.approx(1.6) and out["a1"] == pytest.approx(16.4) and out["last"] == pytest.approx(358.4)
    assert out["wins"] == 5 and out["have"] == 6
    assert out["need"] == 17 and out["needA"] == pytest.approx(306) and out["winA"] == pytest.approx(90)    # 85 % of 20
    assert out["mneed"] == 18                                                                                # MEXC: 90 % of 20
    assert out["off"]["n"] == 0 and out["off"]["segs"] == [] and out["none"]["n"] == 0


def test_the_gauge_runs_from_the_stop_past_the_entry_to_the_next_locks(world):
    d = L.build(world, NOW)
    out = _node("""const pa = A.d.accts.find((a) => a.id === "paper"), by = A.d.accts.find((a) => a.id === "bybit");
      const g = M.gaugeModel(pa.position, {kind: "paper", mark: 62510, ladder: A.d.paper.ladder});
      const g0 = M.gaugeModel(pa.position, {kind: "paper", mark: null, ladder: A.d.paper.ladder});
      const unl = M.gaugeModel({...pa.position, stop: 61000, locked: false, lock_roe: null, next_lock: {lock: 0.1, at: 0.11, price: null}}, {kind: "paper", mark: 61500, ladder: A.d.paper.ladder});
      const lv = M.gaugeModel(by.position, {kind: "live", mark: 62510, ladder: A.d.paper.ladder});
      const xs = [-0.6, -0.04, 0.11, 0.14];
      console.log(JSON.stringify({g: {...g, at: undefined}, g0roe: g0.roe, last: pa.position.last_mark_roe_net, unl: {...unl, at: undefined}, lv: {...lv, at: undefined},
        sa: [M.stepAngle(-0.6, xs), M.stepAngle(-0.04, xs), M.stepAngle(0.14, xs), M.stepAngle(0.035, xs), M.stepAngle(-5, xs), M.stepAngle(5, xs), M.stepAngle(null, xs), M.stepAngle(0.2, [0.1])],
        none: [M.gaugeModel(null), M.gaugeModel({entry: 0})]}));""", {"d": d})
    g = out["g"]
    assert [a["k"] for a in g["anchors"]] == ["entry", "stop", "next", "next2"]           # locked: the stop is above the entry
    by = {a["k"]: a for a in g["anchors"]}
    assert by["stop"]["locked"] is True and by["stop"]["price"] == 62200
    assert by["next"]["v"] == pytest.approx(0.14) and by["next"]["lock"] == pytest.approx(0.13) and by["next2"]["v"] == pytest.approx(0.17)
    assert [a["angle"] for a in g["anchors"]] == pytest.approx([-68, -68 + 136 / 3, 68 - 136 / 3, 68])
    assert [z["tone"] for z in g["zones"]] == ["out", "safe", "run", "lock", "out"]
    p = next(a for a in d["accts"] if a["id"] == "paper")["position"]
    assert g["roe"] == pytest.approx(40 * ((62510 / 62000 - 1) - p["round_trip"] - p["funding_frac"]))
    assert out["g0roe"] == pytest.approx(out["last"])                                    # no live mark: the paper's own last minute
    assert -68 <= g["needle"] <= 88
    u = out["unl"]
    assert [a["k"] for a in u["anchors"]] == ["stop", "entry", "next", "next2"] and [z["tone"] for z in u["zones"]] == ["out", "loss", "run", "lock", "out"]
    assert u["roe"] < 0 and u["anchors"][2]["v"] == pytest.approx(0.11)
    lv = out["lv"]
    assert lv["kind"] == "live" and lv["roe"] == pytest.approx(0.025 * 500 / (62010 * 0.025 / 40))
    assert next(a for a in lv["anchors"] if a["k"] == "entry")["v"] == 0
    assert out["sa"][:3] == pytest.approx([-68, -68 + 136 / 3, 68]) and out["sa"][3] == pytest.approx(-68 + 136 / 3 + 136 / 3 * 0.5)
    assert out["sa"][4] == -88 and out["sa"][5] == 88 and out["sa"][6] is None and out["sa"][7] == 20
    assert out["none"] == [None, None]


def test_first_lock_and_its_reward_against_the_first_stop(world):
    d = L.build(world, NOW)
    out = _node("""const pa = A.d.accts.find((a) => a.id === "paper");
      console.log(JSON.stringify({f: M.firstLock(pa.position, A.d.paper.ladder), no: [M.firstLock(null, A.d.paper.ladder), M.firstLock(pa.position, null)]}));""", {"d": d})
    f = out["f"]
    p = next(a for a in d["accts"] if a["id"] == "paper")["position"]
    assert f["lock"] == pytest.approx(0.10) and f["at"] == pytest.approx(0.11)
    risk = 40 * ((61000 / 62000 - 1) - p["round_trip"] - p["funding_frac"])                # the first stop (stop_initial), net
    assert f["risk"] == pytest.approx(risk) and f["rr"] == pytest.approx(0.10 / -risk)
    assert f["atPrice"] == pytest.approx(62000 * (1 + 0.11 / 40 + p["round_trip"] + p["funding_frac"]))
    assert out["no"] == [None, None]


def test_the_days_dial_pause_arcs_and_entries():
    d0 = T0 - 9 * H                                                         # 10/19 00:00 KST
    spans = [{"from": d0 + 20 * H, "to": d0 + 21 * H, "why": "macro", "ko": "CPI 앞뒤 30분"},
             {"from": d0 + 5 * DAY, "to": d0 + 7 * DAY, "why": "weekend", "ko": "주말"},
             {"from": d0 - DAY, "to": d0 + 6 * H, "why": "weekend", "ko": "주말"}]
    items = [{"pause_from": d0 + 2 * H, "pause_to": d0 + 3 * H, "kind_ko": "PCE", "kind": "PCE"},
             {"pause_from": d0 + 20 * H, "pause_to": d0 + 21 * H, "kind_ko": "CPI", "kind": "CPI"}]
    fills = [{"kind": "entry", "t": d0 + 6 * H, "acct": "bybit", "symbol": "BTCUSDT", "side": 1}, {"kind": "exit", "t": d0 + 7 * H, "acct": "bybit"},
             {"kind": "entry", "t": d0 - H, "acct": "paper"}, {"kind": "entry", "t": d0 + 18 * H, "acct": "paper", "symbol": "ETHUSDT", "side": -1, "open": True}]
    out = _node(f"""console.log(JSON.stringify({{d0: M.kstDayStart({d0} + 13 * {H}), same: M.kstDayStart({d0}), a: M.dayAngle({d0} + 6 * {H}, {d0}),
      arcs: M.dayArcs({json.dumps(spans)}, {json.dumps(items)}, {d0}), dots: M.dayDots({json.dumps(fills)}, {d0}), none: M.dayArcs(null, null, {d0})}}));""", {})
    assert out["d0"] == d0 and out["same"] == d0 and out["a"] == 90
    arcs = out["arcs"]
    assert [(a["why"], round(a["a0"], 3), round(a["a1"], 3)) for a in arcs] == [("weekend", 0, 90), ("macro", 30, 45), ("macro", 300, 315)]
    assert out["dots"] == [{"acct": "bybit", "sym": "BTCUSDT", "side": 1, "t": d0 + 6 * H, "a": 90, "open": False},
                           {"acct": "paper", "sym": "ETHUSDT", "side": -1, "t": d0 + 18 * H, "a": 270, "open": True}]
    assert out["none"] == []


def test_tiles_are_this_weeks_signals_and_the_position_glows(world):
    a = answers(world)
    out = _node("""console.log(JSON.stringify({t: M.tilesOf(A.rank), unk: M.tilesOf({...A.rank, signals: {state: "error"}}),
      lv: [M.tileLevel(0, 10), M.tileLevel(1, 10), M.tileLevel(3, 10), M.tileLevel(10, 10), M.tileLevel(5, 0), M.tileLevel(null, 10)], none: M.tilesOf(null)}));""", a)
    t = {x["code"]: x for x in out["t"]}
    assert set(t) == {"S2_ST_ROC", "N03_ADX_GC"}                                     # the config's strategies only, in its order
    assert t["S2_ST_ROC"]["hold"] is True and t["N03_ADX_GC"]["hold"] is False       # the open BTC position is S2_ST_ROC's
    assert t["N03_ADX_GC"]["n"] == 9 and t["N03_ADX_GC"]["lvl"] == 4 and t["S2_ST_ROC"]["n"] == 5 and t["S2_ST_ROC"]["lvl"] == 3
    assert t["S2_ST_ROC"]["settings"] == 2 and t["N03_ADX_GC"]["settings"] == 1
    assert all(x["n"] is None and x["lvl"] is None for x in out["unk"])               # unreadable signals: unknown, never 0
    assert out["lv"] == [0, 1, 2, 4, 1, None] and out["none"] == []


def test_the_ring_of_strategies_math():
    out = _node("""const r1 = M.prng(7), r2 = M.prng(7), seq = [r1(), r1(), r1()], seq2 = [r2(), r2(), r2()];
      const arcs = M.arcsOf([{code: "A", settings: 3}, {code: "B", settings: 1}, {code: "C", settings: 0}], 2);
      const one = M.arcsOf([{code: "X", settings: 9}]);
      const pts = M.torusPoints(arcs, 500);
      const cnt = [0, 0, 0]; for (const p of pts) cnt[p.g]++;
      const rad = pts.map((p) => Math.hypot(Math.hypot(p.x, p.z) - 1, p.y));
      const box = M.ringBox(), fit = M.fitRing(400, 250), fitN = M.fitRing(10, 10);
      const near = M.project(0, 0, -1, 0), far = M.project(0, 0, 1, 0), side = M.project(1, 0, 0, Math.PI / 2), flat = M.project(1, 0.5, 0, 0, 0);
      console.log(JSON.stringify({seq, seq2, arcs, one, n: pts.length, cnt, rmax: Math.max(...rad), rmin: Math.min(...rad), box, fit, fitN, near, far, side, flat,
        p0: M.torusXYZ(0, 0), p90: M.torusXYZ(90, Math.PI / 2), bz: [M.bezier([0, 0], [5, 10], [10, 0], 0), M.bezier([0, 0], [5, 10], [10, 0], 0.5), M.bezier([0, 0], [5, 10], [10, 0], 1)],
        glow: [M.glowOf(null), M.glowOf(0), M.glowOf(4), M.glowOf(9)], again: M.torusPoints(arcs, 500).slice(0, 3), first: pts.slice(0, 3)}));""", {})
    assert out["seq"] == out["seq2"] and all(0 <= v < 1 for v in out["seq"])
    arcs = out["arcs"]
    assert [a["code"] for a in arcs] == ["A", "B", "C"]
    lens = [a["a1"] - a["a0"] for a in arcs]
    assert sum(lens) == pytest.approx(360 - 6) and lens[0] == pytest.approx(3 * lens[1]) and lens[1] == pytest.approx(lens[2])   # no settings = one
    assert arcs[0]["a0"] == pytest.approx(1) and arcs[1]["a0"] - arcs[0]["a1"] == pytest.approx(2)
    assert out["one"] == [{"code": "X", "a0": 0, "a1": 360}]                          # one strategy: a closed ring, no gap
    assert abs(out["n"] - 500) <= 3 and out["cnt"][0] > out["cnt"][1] and out["cnt"][2] >= 4
    assert out["rmax"] == pytest.approx(W_TUBE, abs=1e-9) and out["rmin"] == pytest.approx(W_TUBE, abs=1e-9)   # every point on the tube
    assert out["again"] == out["first"]                                                # seeded: the same ring every time
    b = out["box"]
    assert b["x1"] == pytest.approx(-b["x0"]) and b["y1"] < -b["y0"]                    # the near side looks bigger (perspective)
    f = out["fit"]
    assert (b["x1"] - b["x0"]) * f["sc"] <= 400 * 0.66 + 1e-6 and (b["y1"] - b["y0"]) * f["sc"] <= 250 * 0.86 + 1e-6
    assert f["cx"] == pytest.approx(200) and f["cy"] - b["y1"] * f["sc"] == pytest.approx(250 - (f["cy"] - b["y0"] * f["sc"]))   # centred
    assert out["fitN"]["sc"] >= 1
    assert out["near"][3] > 1 > out["far"][3] and out["far"][1] > 0 > out["near"][1]   # the far side higher on the screen, smaller
    assert out["side"][0] == pytest.approx(0, abs=1e-9) and out["side"][2] > 0           # a quarter turn takes x to the back
    assert out["flat"][:2] == pytest.approx([1, 0.5]) and out["flat"][3] == 1
    assert out["p0"] == pytest.approx([1 + W_TUBE, 0, 0]) and out["p90"] == pytest.approx([0, W_TUBE, 1], abs=1e-9)
    assert out["bz"] == [[0, 0], [5, 5], [10, 0]]
    assert out["glow"] == [0.6, 0.55, 1, 1]


W_TUBE = 0.34


# ---------------------------------------------------------------- the rules
def test_led_day_and_the_multiplier(world):
    d = L.build(world, NOW)
    out = _node(f"""const by = (id) => A.d.accts.find((a) => a.id === id);
      console.log(JSON.stringify({{
        led: [M.ledOf(by("bybit")), M.ledOf(by("mexc")), M.ledOf({{state: "missing", reason_ko: "없어요"}}), M.ledOf({{state: "error"}}), M.ledOf({{state: "ok", stale: true}}), M.ledOf(null)].map((x) => x.id),
        day: [M.dayN(by("bybit").since_ms, {NOW}), M.dayN(by("bybit").since_ms, {NOW} + 4 * {H}), M.dayN(by("bybit").since_ms, {NOW} + 5 * {H} + 1000), M.dayN(null, {NOW}), M.dayN({NOW} + {DAY}, {NOW})],
        mult: [M.multOf(by("bybit")), M.multOf(by("mexc")), M.multOf({{state: "ok", balance: 50, initial: 100}}), M.multOf({{state: "ok", balance: 50, initial: null}}), M.multOf({{state: "error"}})],
      }}));""", {"d": d})
    assert out["led"] == ["run", "halt", "none", "bad", "stale", "wait"]
    assert out["day"] == [1, 1, 2, None, None]                                  # DAY 2 from 10/20 00:00 KST (NOW is 19:00 KST)
    b = next(a for a in d["accts"] if a["id"] == "bybit")
    assert out["mult"][0] == pytest.approx(b["balance"] / b["initial"]) and out["mult"][1] == pytest.approx(1.0)
    assert out["mult"][2] == 0.5 and out["mult"][3] is None and out["mult"][4] is None   # below 1 is shown, unknown is not 1


def test_idle_words_and_the_pause(world):
    a = answers(world)
    out = _node("""const d = A.d, c = A.cal;
      const paused = {now: {paused: true, pause_ko: "주말이라 진입 쉬는 중", pause_until: 123}};
      const halted = {...d, execs: d.execs.map((x) => ({...x, record: {...x.record, state: "ok", halted: true}}))};
      console.log(JSON.stringify({ok: M.idleWords(d, c), paused: M.idleWords(d, paused), stale: M.idleWords({...d, paper: {...d.paper, stale: true}}, c),
        missing: M.idleWords({...d, paper: {state: "missing", reason_ko: "아직 파일이 없어요"}}, c), err: M.idleWords({...d, paper: {state: "error"}}, c),
        halted: M.idleWords(halted, c), none: M.idleWords(null, null),
        pz: [M.pauseOf(null, paused), M.pauseOf({items: [{id: "weekend", ok: false, ko: "주말이라 진입 쉼", detail: {until: 9}}], pause_until: 8}, null), M.pauseOf(A.now, c)]}));""", a)
    assert out["ok"]["head"] == "대기 중 · 신호를 기다리는 중" and out["ok"]["on"] is True
    assert out["paused"]["head"] == "쉬는 중 · 주말이라 진입 쉬는 중" and out["paused"]["until"] == 123 and out["paused"]["on"] is True
    assert out["stale"]["on"] is False and out["stale"]["head"] == "페이퍼 봇 기록 멈춤"            # the ring turns only while it runs
    assert out["missing"]["head"] == "페이퍼 봇 기록 수집 전" and out["missing"]["sub"] == "아직 파일이 없어요" and out["err"]["head"] == "페이퍼 봇 기록을 못 읽음"
    assert out["halted"]["head"] == "대기 중 · 실행기 둘 다 멈춤" and out["none"]["head"] == "불러오는 중"
    assert out["pz"] == [{"ko": "주말이라 진입 쉬는 중", "until": 123}, {"ko": "주말이라 진입 쉼", "until": 8}, None]


def test_milestones_are_real_and_celebrated_once_never_for_the_past(world):
    d = L.build(world, NOW)
    out = _node(f"""const by = (id) => A.d.accts.find((a) => a.id === id);
      const x2 = {{state: "ok", balance: 200, initial: 100, stats: {{wins: 0}}}};
      console.log(JSON.stringify({{
        reached: [M.milestonesOf(by("bybit")), M.milestonesOf(x2), M.milestonesOf({{state: "ok", balance: 150, initial: 100, stats: {{wins: 2}}}}), M.milestonesOf({{state: "error"}})],
        first: M.freshMilestones(null, ["win1", "x1.5"], [], null, {NOW}),
        firstRecentWin: M.freshMilestones(null, ["win1"], [], {NOW} - 60000, {NOW}),
        firstOldWin: M.freshMilestones(null, ["win1"], [], {NOW} - 3600000, {NOW}),
        crossed: M.freshMilestones(["win1"], ["win1", "x1.5"], [], null, {NOW}),
        seen: M.freshMilestones(["win1"], ["win1", "x1.5"], ["x1.5"], null, {NOW}),
      }}));""", {"d": d})
    assert out["reached"] == [["win1"], ["x1.5", "x2"], ["win1", "x1.5"], []]
    assert out["first"] == [] and out["firstOldWin"] == []                      # the first look is the past
    assert out["firstRecentWin"] == ["win1"]                                     # a first win a minute ago: still 'now'
    assert out["crossed"] == ["x1.5"] and out["seen"] == []                      # this browser already celebrated it


def test_the_result_card_takes_the_last_live_trade_else_the_papers(world):
    d = L.build(world, NOW)
    out = _node("""const paperOnly = A.d.fills.filter((f) => f.acct === "paper");
      console.log(JSON.stringify({live: M.lastClosed(A.d.fills), paper: M.lastClosed(paperOnly), none: M.lastClosed([]), entries: M.lastClosed(A.d.fills.filter((f) => f.kind === "entry"))}));""", {"d": d})
    lv = out["live"]
    exits = sorted((f for f in d["fills"] if f["kind"] == "exit" and f["acct"] != "paper"), key=lambda f: -f["t"])
    assert lv["paper"] is False and lv["exit"]["key"] == exits[0]["key"]
    assert lv["entry"]["key"] == exits[0]["key"].replace(":x:", ":e:") and lv["entry"]["t"] < lv["exit"]["t"]
    assert out["paper"]["paper"] is True and out["paper"]["exit"]["acct"] == "paper"
    assert out["none"] is None and out["entries"] is None


def test_feed_ticker_and_why_words_are_real_records_only(world):
    a = answers(world)
    out = _node("""const rows = M.feedRows(A.d, A.now, 8), all = M.feedRows(A.d, A.now, 999);
      const tk = M.tickerItems(A.d, A.now, A.cal), tk0 = M.tickerItems(null, null, null);
      const broken = {...A.d, accts: A.d.accts.map((x) => (x.id === "mexc" ? {id: "mexc", state: "error", reason_ko: "권한"} : x))};
      const why = A.now.items.map((it) => [it.id, M.whyDetail(it)]);
      console.log(JSON.stringify({rows, n: all.length, tk, tk0, tkb: M.tickerItems(broken, A.now, A.cal), why}));""", a)
    rows = out["rows"]
    assert len(rows) == 8 and [r["t"] for r in rows] == sorted((r["t"] for r in rows), reverse=True)
    assert out["n"] == len(a["d"]["fills"]) + len(a["d"]["events"]) + (1 if a["now"]["last_signal"] else 0)
    assert {r["kind"] for r in rows} <= {"entry", "lock", "stop", "exit", "warn", "crit", "sig"}
    tk = {x["k"]: x["text"] for x in out["tk"]}
    b = next(x for x in a["d"]["accts"] if x["id"] == "bybit")
    assert tk["bybit"].startswith("바이비트 $101.50 ×1.02") and tk["mexc"].endswith("· 멈춤") and tk["sum"] == "실거래 합계 $204.30"
    assert tk["cp"] == "40번 판단까지 34번 (페이퍼 6/40)" and tk["light:bybit"] == "신호등 바이비트 근거 쌓는 중 6/20"
    assert b["balance"] == 101.5
    assert out["tk0"] == []
    tkb = {x["k"]: x["text"] for x in out["tkb"]}
    assert tkb["mexc"] == "WOO X Pro 못 읽음" and "sum" not in tkb                     # never a total over an unreadable wallet
    for x in out["tk"] + out["tkb"]:
        assert not re.search(r"\b(null|undefined|NaN)\b", x["text"]), x
    why = {}
    for k, v in out["why"]:
        if v and k not in why:
            why[k] = v                                                           # the first of each (바이비트 before MEXC)
    assert why["position"]["text"].startswith("BTC 롱 · ") and "순ROE" in why["position"]["text"]
    assert why["light"]["text"] == "페이퍼 거래 6/20번 쌓임 · 기준 85%"


# ---------------------------------------------------------------- the view in node
VIEW = """const D = await import('file://%s');
const ctx = {params: {query: {}}, alive: () => true, api: async (p) => { await null; if (A.fail && A.fail.includes(p)) throw Object.assign(new Error("x"), {status: 0, kind: "network"});
  return p.endsWith("/now") ? A.now : p.endsWith("/calendar") ? A.cal : A.rank; },
  every(ms, fn, o) { if (!o || o.now !== false) fn(); }, track() {}, listen() {}, watch() {}, on() {}, timeout() {}, href: (n, a) => '#/' + n + '/' + a};
const hub = {get: () => null, state: () => "loading", at: () => 0, retry: () => {}};
const v = M.hqView(ctx, hub);
const first = D.walk(v.el).text;
await new Promise((r) => setTimeout(r, 30));
v.set(A.d, "ok");
await new Promise((r) => setTimeout(r, 30));
const ok = D.walk(v.el);
v.set(null, "failed");
const after = D.walk(v.el).text;
console.log(JSON.stringify({first, text: ok.text.replace(/\\s+/g, " "), classes: ok.classes, after: after.replace(/\\s+/g, " ")}));""" % DOM


def test_the_view_renders_the_live_world_honestly(world):
    a = answers(world)
    out = _node(VIEW, a)
    t = out["text"]
    assert not re.search(r"\b(null|undefined|NaN)\b", t)
    for word in ("실거래 한눈에", "진짜 돈", "바이비트", "MEXC", "101.50", "102.80", "×1.02", "신호등 · 근거 쌓는 중 6/20", "멈춤", "기준 85%", "기준 90%",
                 "왜 지금 진입 안 하나", "이미 포지션이 있어 새 진입 안 함", "진입 카드", "결과 카드", "실시간", "40번 판단까지", "남은 34번",
                 "88% 이상이면 금액 늘리기 검토", "82~88%면 그대로 지켜보기", "82% 미만이면 멈추고 다시 생각", "매매법 2개 · 이번 주 신호",
                 "따라감 · COMBO@mix", "손익비", "첫 잠금 기준", "거래소 손절", "실거래 합계 $204.30"):
        assert word in t, word
    assert "주문" not in t.replace("주문 버튼 없음", "").replace("주문 없음", "")             # view only: no order button anywhere
    assert "lbh-tile" in " ".join(out["classes"]) and "hold" in " ".join(c for c in out["classes"] if "lbh-tile" in c)
    assert "101.50" in out["after"]                                                          # a failed refresh keeps the last answer


def test_the_view_without_the_88_rule_and_with_strategies_on_two_bars(world):
    """The 추세판단 봇 (owners 10/22): no 88 / 82 % rule (checkpoint rule_ko), so the bar under the frame never shows it;
    18 entries on 15 strategies: the tiles' heading says both counts (one tile per strategy)."""
    a = answers(world)
    a["d"]["checkpoint"]["rule_ko"] = "새 규칙이라 88%·82% 같은 판단 기준이 없어요 · 2주 뒤 검토에서 두 분이 정해요"
    rows = [r for r in a["rank"]["rows"] if r.get("in_config") is not False]
    rows[0]["n_settings"] = 2                                       # one strategy on two entry bars
    a["rank"]["trend_bot"] = {"trend": True}                        # (another bot keeps "매매법 N개": its settings are variants)
    n = sum(int(r.get("n_settings") or 0) for r in rows)
    out = _node(VIEW, a)
    t = out["text"]
    assert "88% 이상 금액 늘리기 검토" not in t and "88% 이상이면 금액 늘리기 검토" not in t
    assert "새 규칙이라 88%·82% 같은 판단 기준이 없어요 · 2주 뒤 검토에서 두 분이 정해요 · 40번 전에는 판단 안 함" in t
    assert f"매매법 {len(rows)}종 · 진입 {n}개 · 이번 주 신호" in t


def test_the_view_says_what_it_cannot_read(tmp_path):
    p = W.build_world(str(tmp_path / "w"))
    with open(p["mexc_db"], "wb") as fh:
        fh.write(b"not a database at all" * 50)
    os.remove(p["bybit_db"])
    a = answers(p)
    a["fail"] = ["/api/v4/livebots/rank"]
    out = _node(VIEW, a)
    t = out["text"]
    assert not re.search(r"\b(null|undefined|NaN)\b", t)
    assert "수집 전" in t and "못 읽음" in t
    assert "$0.00" not in t and "×" not in t                                                 # no balance, no × for an unread wallet
    assert "실거래 합계" not in t
    assert "불러오지 못했" in t                                                             # /rank failed before any answer: says so


def test_the_view_on_day_one_no_trade_no_position(tmp_path):
    folder = str(tmp_path / "d1")
    p = W.build_world(folder)
    W.paper_db(os.path.join(folder, "p2.db"), with_position=False)
    import sqlite3
    for db in (p["bybit_db"],):
        c = sqlite3.connect(db)
        ts, data = c.execute("SELECT ts, data FROM state WHERE k = 'bot'").fetchone()
        dd = json.loads(data)
        dd["trade"] = None
        c.execute("UPDATE state SET data = ? WHERE k = 'bot'", (json.dumps(dd),))
        c.commit()
        c.close()
    p["paper"] = os.path.join(folder, "p2.db")
    a = answers(p)
    out = _node(VIEW, a)
    t = out["text"]
    assert "지금 열린 포지션이 없어요" in t and "대기 중" in t and "마지막 신호" in t
    assert not re.search(r"\b(null|undefined|NaN)\b", t)


# ---------------------------------------------------------------- static
def test_static_tokens_endpoints_and_safety():
    js, css = _read(JS), _read(CSS)
    for path in ("/api/v4/livebots/now", "/api/v4/livebots/calendar", "/api/v4/livebots/rank"):
        assert f'"{path}"' in js, path
    assert "export function hqView(ctx, hub)" in js
    assert not re.search(r"innerHTML|insertAdjacentHTML|outerHTML|DOMParser|\beval\(|toLocaleString|Intl\.NumberFormat", js)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"//[^\n]*|/\*.*?\*/", "", js, flags=re.S).replace('"#/', ""))   # no colour in js
    assert 'from "../core/pb.js"' in js and not re.search(r'from "\.\./core/(?!pb\.js)', js)
    assert "post(" not in js and "ctx.post" not in js                                      # view only: it never writes
    assert "getComputedStyle(document.documentElement)" in js and "requestAnimationFrame" in js and "cancelAnimationFrame" in js
    assert "Math.min(2, " in js and "document.hidden" in js and "motion.reduced()" in js     # dpr capped, hidden / reduced respected
    bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", bare) and not re.search(r"\brgba?\(\s*\d", bare)
    assert not re.search(r"font-size:\s*\d", bare)
    for m in re.finditer(r"(?<![-\w])font(?:-size)?:\s*([^;}]+)", bare):
        v = m.group(1)
        assert "var(--t-" in v or re.search(r"calc\(\d+px \* var\(--ts\)\)", v) or v.strip() == "inherit", v
    assert all(c.startswith("lbh") for c in re.findall(r"\.(lb[\w-]*)", bare)), "every class is lbh-"
    assert '@import url("livebots-hq.css");' in _read(os.path.join(SCREENS, "livebots.css"))
    assert "[data-still=\"1\"]" in bare and "prefers-reduced-motion" in bare


# ---------------------------------------------------------------- ⏳ 진입 대기 (the /now answer's pending)
T0W = NOW - 10 * MIN                               # the world's WAITING row: BCH long, N03_ADX_GC 15m


def _wait_world(tmp_path, monkeypatch, position=False, rule=True):
    d = tmp_path / "ww"
    d.mkdir()
    p = W.build_world(str(d))
    if not position:
        W.paper_db(p["paper"] + ".2", with_position=False)
        os.replace(p["paper"] + ".2", p["paper"])
    path = str(d / "paper3.db")
    if rule:
        W.rule_bars(path, "BCHUSDT", T0W - 20 * MIN, NOW, high=lambda ts: 101.0 if T0W - 15 * MIN <= ts < T0W else 100.5)
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", path)
    return p, path


CARD = """const D = await import('file://%s');
const out = {};
for (const [k, n] of Object.entries(A)) { const c = M.waitCard(n, Date.now()); const w = D.walk(c.el); out[k] = {text: w.text.replace(/\\s+/g, " "), classes: w.classes, rows: [...c.rows.keys()]}; }
console.log(JSON.stringify(out));""" % DOM


def test_the_wait_card_shows_the_level_the_price_the_distance_and_the_deadline(tmp_path, monkeypatch):
    p, _rule = _wait_world(tmp_path, monkeypatch)
    n = L.whynow(p, NOW)
    w = n["pending"]["waits"][0]
    assert w["level"] == 101.0 and w["touched"] is False and n["pending_blocked_ko"] is None
    touched = json.loads(json.dumps(n))
    touched["pending"]["waits"][0].update(touched=True, to_go=-0.002, last=101.2)
    short = json.loads(json.dumps(n))
    short["pending"]["waits"][0].update(side=-1, level=99.0, to_go=0.0101)
    out = _node(CARD, {"wait": n, "touched": touched, "short": short})
    t = out["wait"]["text"]
    for word in ("BCH", "롱", "N03_ADX_GC · 15분", "101.00 위로 올라가면 진입", "지금 100.00", "1.00% 남음",
                 "진입 대기 = 신호는 나왔고 정한 가격(되돌림 또는 돌파)을 기다리는 중. 진입 확정이 아니에요. 시간 안에 안 닿으면 진입 없음.",
                 "텔레그램에도 ⏳ 진입 대기 알림이 한 번 가요 (끄기: PAPERBOT_LIVE_WAIT_MSGS=0)"):
        assert word in t, word
    assert re.search(r"00:0[45]:\d\d", t)                                         # the deadline: left_ms from the answer's time
    assert out["wait"]["rows"] == [w["key"]] and "lbh-wbar" in out["wait"]["classes"]
    assert "돌파함 · 진입 확인 중" not in t and "지금은 진입으로 이어지지 않아요" not in t
    tt = out["touched"]["text"]
    assert "돌파함 · 진입 확인 중" in tt and "남음 " not in tt.split("진입 대기 =")[0].replace("00:", "")   # no 'n% 남음' once beyond
    assert any("touched" in c for c in out["touched"]["classes"])
    assert "99.00 아래로 내려가면 진입" in out["short"]["text"] and "숏" in out["short"]["text"]
    pure = _node("""const w = A.w; console.log(JSON.stringify({c: [M.closeness(w), M.closeness({...w, touched: true}), M.closeness({...w, to_go: 0.05}), M.closeness({...w, level: null, to_go: null}), M.closeness(null)],
      end: [M.waitEnd(w, 1000), M.waitEnd({...w, left_ms: null}, 1000), M.waitEnd(null, 1000)], words: M.waitWords(w), none: M.waitWords({...w, level: null, last: null, to_go: null})}));""", {"w": w})
    assert pure["c"] == [pytest.approx(0.5), 1, 0, None, None]
    assert pure["end"] == [1000 + 5 * MIN, w["until"], None]
    assert pure["words"] == {"move": "101.00 위로 올라가면 진입", "last": "100.00", "left": "1.00% 남음", "touch": "돌파함 · 진입 확인 중"}
    assert pure["none"] == {"move": None, "last": None, "left": None, "touch": "돌파함 · 진입 확인 중"}


def test_the_wait_card_never_invents_a_level_and_says_when_nothing_waits(tmp_path, monkeypatch):
    p, rule = _wait_world(tmp_path, monkeypatch, rule=False)                     # the rule bot's bars are not there
    n = L.whynow(p, NOW)
    assert n["pending"]["waits"][0]["level"] is None
    empty = json.loads(json.dumps(n))
    empty["pending"]["waits"] = []
    broken = json.loads(json.dumps(n))
    broken["pending"] = {"state": "error", "reason_ko": "파일이 깨졌어요", "waits": [], "closes": []}
    old = json.loads(json.dumps(n))
    del old["pending"]
    out = _node(CARD, {"nolevel": n, "empty": empty, "broken": broken, "old": old})
    t = out["nolevel"]["text"]
    assert f"기준가 못 읽음 (규칙봇 1분봉 파일: {rule}" in t and "위로 올라가면" not in t and "% 남음" not in t
    assert "lbh-wbar" not in out["nolevel"]["classes"]                              # no distance bar without a level
    e = out["empty"]["text"]
    assert "지금 기다리는 진입 없음" in e
    closes = n["pending"]["closes"]
    assert [c["tf"] for c in closes] == ["15m", "30m", "1h"]
    for c in closes:
        hm = L.time.strftime("%H:%M", L.time.gmtime((c["next_ms"] + 9 * H) / 1000))
        assert f"{ {'15m': '15분', '30m': '30분', '1h': '1시간'}[c['tf']]}봉 마감 {hm} KST · 바로 진입 {c['now']}개 · 돌파 대기 {c['break']}개" in e
    assert "못 읽음" in out["broken"]["text"] and "파일이 깨졌어요" in out["broken"]["text"]
    assert "수집 전" in out["old"]["text"]
    for k in out:
        assert not re.search(r"\b(null|undefined|NaN)\b", out[k]["text"]), k


def test_the_wait_card_says_why_a_wait_cannot_become_an_entry_now(tmp_path, monkeypatch):
    p, _rule = _wait_world(tmp_path, monkeypatch, position=True)                 # a position is open: one at a time
    n = L.whynow(p, NOW)
    assert n["pending_blocked_ko"] == "이미 포지션이 있어 새 진입 안 함(한 번에 하나)"
    out = _node(CARD, {"blocked": n})
    assert "지금은 진입으로 이어지지 않아요 · 이미 포지션이 있어 새 진입 안 함(한 번에 하나)" in out["blocked"]["text"]
    tk = _node("""console.log(JSON.stringify(M.tickerItems(A.d, A.now, null).find((x) => x.k === "wait")));""", {"d": L.build(p, NOW), "now": n})
    assert tk["text"] == "⏳ 진입 대기 BCH 롱 · 101.00 위로 올라가면 진입 · 1.00% 남음"


# ---------------------------------------------------------------- 진입 가능성 TOP 5 (the /now answer's likely)
LIKELY = """const D = await import('file://%s');
const out = {};
for (const [k, n] of Object.entries(A)) { const w = D.walk(M.likelyCard(n, "#/livebots/rank")); out[k] = {text: w.text.replace(/\\s+/g, " "), classes: w.classes}; }
out.pct = [M.pctK(38.5), M.pctK(7.4), M.pctK(0), M.pctK(null), M.pctK(100)];
console.log(JSON.stringify(out));""" % DOM


def test_the_likely_card_ranks_by_signal_frequency_waits_first_and_says_what_it_is(tmp_path, monkeypatch):
    p, _rule = _wait_world(tmp_path, monkeypatch, position=True)
    L._likely_ref.clear()
    n = L.whynow(p, NOW)
    lk = n["likely"]
    assert lk["state"] == "ok" and lk["top"][0]["strategy"] == "N03_ADX_GC" and lk["top"][0]["waits"]
    missing = json.loads(json.dumps(n))
    missing["likely"] = {"state": "missing", "reason_ko": "진입 가능성 기준표(deploy/combo.live-ac.likely.json)가 없어요"}
    broken = json.loads(json.dumps(n))
    broken["likely"] = {"state": "error", "reason_ko": "모양이 달라요"}
    old = json.loads(json.dumps(n))
    del old["likely"]
    out = _node(LIKELY, {"ok": n, "missing": missing, "broken": broken, "old": old})
    t = out["ok"]["text"]
    b = lk["bot"]
    w4 = lambda x: f"{x:.1f}%" if x < 10 else f"{int(x + 0.5)}%"                  # noqa: E731  (fmt.pctOf: half up, 1 decimal under 10)
    assert f"4시간 안 진입 신호: 지금 같은 시간엔 {w4(b['w4']['recent'])} (5년 {w4(b['w4']['all'])}) · 보통 {b['next_h_median']['recent']:.1f}시간 뒤" in t
    top = lk["top"][0]
    assert f"1 N03_ADX_GC {top['type']} 15분 ⏳ 진입 대기 {w4(top['p']['w4']['recent'])} 5년 {w4(top['p']['w4']['all'])}" in t
    assert "월~목 19시 기준" in t
    assert "이길 확률이 아니라 신호가 나오는 빈도예요 · 자세히: 순위 탭" in t and "예측이 아니라 과거 빈도" in t
    assert any("lbh-lrow wait" in c for c in out["ok"]["classes"])                 # the waiting one is marked
    unknown = [r for r in lk["top"] if not r["known"]]
    if unknown:
        assert "기준 없음" in t                                                   # a strategy the file does not know: no number
    assert out["pct"] == ["39%", "7.4%", "0.0%", "—", "100%"]
    assert "수집 전" in out["missing"]["text"] and "deploy/combo.live-ac.likely.json" in out["missing"]["text"]
    assert "못 읽음" in out["broken"]["text"] and "모양이 달라요" in out["broken"]["text"] and "수집 전" in out["old"]["text"]
    for k in ("ok", "missing", "broken", "old"):
        assert not re.search(r"\b(null|undefined|NaN)\b", out[k]["text"]), k


# ---------------------------------------------------------------- layout guards (owners 10/19: the light's note was squeezed
# into a one-character column because the TOP 5 rows' grid class had the same name as the note)
def test_one_class_is_always_one_kind_of_element():
    """A class names one thing: never the same lbh- class on two kinds of element (a span and a list row would share a
    grid meant for one of them). SVG ring segments may be a circle (the light off) or a path."""
    js = _read(JS)
    tags = {}
    for tag, cls in re.findall(r'\b[hs]\("(\w+)", \{class: \[?"(lbh-[\w-]+)', js):
        tags.setdefault(cls, set()).add(tag)
    assert len(tags) > 100
    assert {c: t for c, t in tags.items() if len(t) > 1 and c != "lbh-seg"} == {}


def test_the_lights_note_is_a_full_width_line_under_its_label(world):
    css = re.sub(r"/\*.*?\*/", "", _read(CSS), flags=re.S)
    light = re.search(r"\.lbh-light\s*\{([^}]*)\}", css).group(1)
    assert "display: grid" in light and "grid-template-columns: minmax(0, 1fr)" in light       # one column: label, then note
    note = re.findall(r"\.lbh-lnote\s*\{([^}]*)\}", css)
    assert note and "display: block" in note[0] and "width: 100%" in note[0]
    assert not re.search(r"\.lbh-lnote[^{]*\{[^}]*grid-template", css)
    a = answers(world)
    out = _node(VIEW, a)
    assert "lbh-lnote" in out["classes"] and "lbh-lr" not in out["classes"]
    assert "신호등 · 근거 쌓는 중 6/20 기준 85% · 최근 20번 중 17번 이상 이김" in out["text"]
