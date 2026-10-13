"""candleague 여러 차트 screen (js/screens/charts.js + js/live-kit.js, css scr/charts.css) and its menu / 찾기 entries.

Mounted for real under node on the DOM stand-in of test_candleague_rank_ui with a fake chart library (price lines are
recorded), hand-made /api/klines, /api/live and /api/positions answers (positions shaped like candleague.dash.positions_doc):
mounts (2x2), 2x2 -> 3x3 -> 2x2, a cell's coin / timeframe change (remembered), empty positions, a coin with 30 open positions
drawn as at most 12 lines with '+18개 더', one account picked, klines unavailable (a calm note), no undefined / NaN anywhere,
cleanGrid on garbage; plus the static rules (tokens only) and the menu / 찾기 entries."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_rank_ui as RANK  # noqa: E402  (its DOM stand-in)

STATIC = os.path.join(ROOT, "candleague", "static")
BAD = ("NaN", "undefined", "null", "Infinity")
NOW = 1_791_000_000_000

RUNNER = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const store = install(cfg);
const S = cfg.static;
globalThis.window = globalThis;
const fakes = [];
globalThis.LightweightCharts = {createChart(box) {
  const f = {box, dead: false, lines: []};
  const series = () => ({applyOptions() {}, setData() {}, update() {}, priceScale: () => ({applyOptions() {}}),
    createPriceLine(o) { f.lines.push(o); return o; }, removePriceLine(o) { f.lines = f.lines.filter((x) => x !== o); }});
  f.api = {addCandlestickSeries: series, addHistogramSeries: series, priceScale: () => ({applyOptions() {}}),
    timeScale: () => ({getVisibleLogicalRange: () => null, setVisibleLogicalRange() {}}), resize() {}, remove() { f.dead = true; }};
  fakes.push(f);
  return f.api;
}};
const C = await import(`file://${S}/js/screens/charts.js`);
const el = document.createElement("div");
el.dataset.screen = "charts";
document.body.appendChild(el);
const ctx = {params: {name: "charts", arg: null, query: {}}, alive: () => true, signal: null,
  api: async (p) => { const r = await globalThis.fetch(p); if (!r.ok) throw Object.assign(new Error("http"), {status: r.status}); return r.json(); },
  every: () => {}, css: async () => null, setTitle() {}, href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
const tick = () => new Promise((r) => setTimeout(r, 15));
const cleanup = await C.mount(el, ctx);
await tick();
function snap() {
  const cells = el.querySelectorAll("section.cg-cell").map((c) => {
    const sels = c.querySelectorAll("select");
    const f = fakes.find((x) => !x.dead && c.contains(x.box));
    const more = c.querySelector(".cg-more");
    return {coin: sels[0].value, tf: sels[1].value, pos: sels[2].value, posOpts: sels[2].querySelectorAll("option").map(txt), posDisabled: sels[2].hasAttribute("disabled") || sels[2].disabled === true,
      groups: sels[2].querySelectorAll("optgroup").map((g) => g.getAttribute("label")),
      more: more && !more.hidden ? txt(more) : null, note: c.querySelector(".cg-note").hidden ? null : txt(c.querySelector(".cg-note")),
      msg: c.querySelector(".cg-msg").hidden ? null : txt(c.querySelector(".cg-msg")), chart: !!f, lines: f ? f.lines.length : 0,
      titles: f ? f.lines.map((l) => l.title) : [], tag: txt(c.querySelector(".cg-tag")), px: txt(c.querySelector(".cg-px")), chg: txt(c.querySelector(".cg-chg"))};
  });
  return {cells, layout: el.querySelector(".cg-grid").dataset.layout, status: txt(el.querySelector(".k4-live")), page: txt(el),
    saved: (() => { try { return JSON.parse(store.get("cl-charts-grid")); } catch (e) { return null; } })()};
}
const res = {first: snap(), steps: []};
const cell = (i) => el.querySelectorAll("section.cg-cell")[i];
for (const st of cfg.ops || []) {
  if (st.op === "click") el.querySelector(st.sel).fire("click");
  else if (st.op === "sel") { const s = cell(st.cell).querySelectorAll("select")[st.which]; s.value = st.value; s.fire("change"); }
  await tick(); await tick();
  res.steps.push(snap());
}
res.clean = (cfg.garbage || []).map((g) => C.cleanGrid(g));
res.layouts = C.LAYOUTS; res.max = C.MAX_DRAWN;
cleanup();
res.afterCleanup = el.querySelectorAll("section.cg-cell").length;
console.log(JSON.stringify(res));
"""


def _bars(n=40, base=100.0):
    t0 = NOW - n * 900_000
    return {"t": [t0 + i * 900_000 for i in range(n)], "o": [base + i for i in range(n)], "h": [base + i + 2 for i in range(n)],
            "l": [base + i - 2 for i in range(n)], "c": [base + i + 1 for i in range(n)], "v": [10.0 + i for i in range(n)]}


def _pos(i, coin="BTCUSD", side=1, hidden=False):
    p = {"id": f"core-{coin[:-3]}-15m-{i}-fq", "name": "빠른 손절", "role": "main", "kind": "ruled", "coin": coin, "symbol": coin + "T", "side": side,
         "since": NOW - i * 60_000, "hidden": hidden, "lev": 30, "entry": 100.0 + i, "stop": 95.0 + i, "tp": 120.0 + i, "stop_is_lock": False}
    if hidden:
        p.update(lev=None, entry=None, stop=None, tp=None)
    return p


LIVE = {"generated_ms": NOW - 2000, "server_ms": NOW, "source": "binance",
        "coins": [{"coin": c, "price": 100.0 + k, "mark": 100.0 + k, "change_pct": 1.25 - k, "ok": True} for k, c in
                  enumerate(["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"])]}


def _routes(positions, klines=None):
    return {"/api/klines": klines if klines is not None else {"coin": "BTCUSD", "tf": "15m", "bars": _bars()},
            "/api/live": LIVE, "/api/positions": positions}


def _run(tmp_path, routes, ops=(), local=None, garbage=()):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": STATIC, "routes": routes, "ops": list(ops), "local": local or {}, "garbage": list(garbage)}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def _no_junk(text: str) -> None:
    for bad in BAD:
        assert bad not in text, bad


def _doc(rows):
    return {"positions": rows, "counts": {"open": len(rows)}, "generated_ms": NOW}


def test_mounts_2x2_with_the_default_cells_and_prices(tmp_path):
    rows = [_pos(i) for i in range(3)] + [_pos(1, "ETHUSD", -1)]
    r = _run(tmp_path, _routes(_doc(rows)))
    f = r["first"]
    assert f["layout"] == "2x2" and len(f["cells"]) == 4
    assert [c["coin"] for c in f["cells"]] == ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD"] and {c["tf"] for c in f["cells"]} == {"15m"}
    assert all(c["chart"] and c["msg"] is None for c in f["cells"])
    assert f["cells"][0]["px"] == "100.00" and f["cells"][0]["chg"] == "+1.25%" and "BTC · 15분" in f["cells"][0]["tag"]
    assert f["status"] == "시세 6초마다"
    assert f["cells"][0]["posOpts"][0] == "포지션 선 끔 · 3개 열림" and f["cells"][1]["posOpts"][0] == "포지션 선 끔 · 1개 열림"
    assert all(c["lines"] == 0 for c in f["cells"])                                   # nothing laid over until a cell picks a position
    assert "주문" in f["page"] and "실시간 체결" in f["page"]
    _no_junk(f["page"])


def test_layout_switch_2x2_3x3_and_back(tmp_path):
    ops = [{"op": "click", "sel": '.seg button[data-id="3x3"]'}, {"op": "click", "sel": '.seg button[data-id="2x2"]'}]
    r = _run(tmp_path, _routes(_doc([_pos(0)])), ops)
    a, b = r["steps"]
    assert a["layout"] == "3x3" and len(a["cells"]) == 9 and all(c["chart"] for c in a["cells"])
    assert [c["coin"] for c in a["cells"]][4:] == ["LTCUSD", "BCHUSD", "BTCUSD", "ETHUSD", "SOLUSD"] and a["cells"][6]["tf"] == "1h"
    assert a["saved"]["layout"] == "3x3"
    assert b["layout"] == "2x2" and len(b["cells"]) == 4
    assert r["layouts"] == {"2x2": 4, "3x3": 9}
    _no_junk(a["page"] + b["page"])


def test_cell_coin_and_timeframe_change_is_remembered(tmp_path):
    ops = [{"op": "sel", "cell": 1, "which": 0, "value": "LTCUSD"}, {"op": "sel", "cell": 1, "which": 1, "value": "1h"}]
    r = _run(tmp_path, _routes(_doc([_pos(0, "LTCUSD"), _pos(1, "LTCUSD")])), ops)
    a, b = r["steps"]
    assert a["cells"][1]["coin"] == "LTCUSD" and "LTC" in a["cells"][1]["tag"] and a["cells"][1]["posOpts"][0] == "포지션 선 끔 · 2개 열림"
    assert a["cells"][1]["chart"]
    assert b["cells"][1]["tf"] == "1h" and "1시간" in b["cells"][1]["tag"]
    assert b["saved"]["cells"][1]["coin"] == "LTCUSD" and b["saved"]["cells"][1]["tf"] == "1h" and b["saved"]["cells"][0]["coin"] == "BTCUSD"
    _no_junk(b["page"])


def test_empty_positions_hidden_rows_and_missing_doc(tmp_path):
    r = _run(tmp_path, _routes(_doc([])), [{"op": "sel", "cell": 0, "which": 2, "value": "all"}])
    c = r["first"]["cells"][0]
    assert c["posOpts"] == ["열린 모의 포지션 없음"] and c["posDisabled"] and c["more"] is None and c["lines"] == 0
    assert r["steps"][0]["cells"][0]["lines"] == 0
    # a hidden DeepSeek row (no price, D11) and a not-yet-ready snapshot draw nothing and say nothing odd
    r = _run(tmp_path, _routes(_doc([_pos(0, hidden=True)])))
    assert r["first"]["cells"][0]["posOpts"] == ["열린 모의 포지션 없음"]
    r = _run(tmp_path, _routes({"status": "준비 중", "positions": [], "counts": None}))
    assert r["first"]["cells"][0]["posOpts"] == ["열린 모의 포지션 없음"]
    r = _run(tmp_path, _routes(None))                                                    # /api/positions fails
    assert r["first"]["cells"][0]["posOpts"] == ["포지션 불러오는 중"] and r["first"]["cells"][0]["chart"]
    _no_junk(r["first"]["page"])


def test_many_positions_are_capped_at_12_lines_with_a_more_mark(tmp_path):
    rows = [_pos(i) for i in range(30)] + [_pos(i, "ETHUSD") for i in range(5)]
    one = "core-BTC-15m-7-fq|%d|1" % (NOW - 7 * 60_000)
    ops = [{"op": "sel", "cell": 0, "which": 2, "value": "all"}, {"op": "click", "sel": 'button[aria-pressed="false"]'},
           {"op": "sel", "cell": 0, "which": 2, "value": one}, {"op": "sel", "cell": 1, "which": 2, "value": "all"}]
    r = _run(tmp_path, _routes(_doc(rows)), ops)
    f = r["first"]["cells"][0]
    assert f["posOpts"][0] == "포지션 선 끔 · 30개 열림" and f["posOpts"][1].startswith("우리 포지션 전부 (최근 12개 / 30개)")
    assert len(f["posOpts"]) == 2 + 20 and f["groups"] == ["계좌 하나만 (최근 20개)"]          # the newest 20 accounts, not 30
    a, b, c, d = r["steps"]
    assert a["cells"][0]["lines"] == 12 and a["cells"][0]["more"] == "+18개 더"
    assert sum(1 for t in a["cells"][0]["titles"] if t) == 2 and any("롱 30배" in t for t in a["cells"][0]["titles"])
    assert b["cells"][0]["lines"] == 12 * 3 and b["cells"][0]["more"] == "+18개 더"       # 손절·목표 on: stop + take-profit lines, still 12 entries
    assert c["cells"][0]["lines"] == 3 and c["cells"][0]["more"] is None                  # one account: its entry, stop and target
    assert "core-BTC-15m-7-fq" in c["cells"][0]["note"] and "진입" in c["cells"][0]["note"]
    assert d["cells"][1]["lines"] == 5 * 3 and d["cells"][1]["more"] is None              # 5 open on ETH: all drawn, nothing "more"
    _no_junk(d["page"])


def test_klines_unavailable_is_a_calm_note(tmp_path):
    kl = {"coin": "BTCUSD", "tf": "15m", "unavailable": True, "stale": True, "bars": {k: [] for k in "tohlcv"}}
    r = _run(tmp_path, _routes(_doc([_pos(0)]), kl))
    for c in r["first"]["cells"]:
        assert not c["chart"] and "차트 자료를 아직 받지 못했습니다" in c["msg"]
    _no_junk(r["first"]["page"])
    r = _run(tmp_path, _routes(_doc([_pos(0)]), {"off": True}))
    assert "꺼져" in r["first"]["cells"][0]["msg"]


def test_clean_grid_on_garbage_and_a_bad_stored_value(tmp_path):
    garbage = [None, 5, "x", [], {}, {"layout": "9x9", "cells": "no", "sw": 3}, {"layout": "3x3", "cells": [None, 1, {"coin": "XRPUSD", "tf": "2m", "pos": 7}, {"coin": "SOLUSD", "tf": "4h", "pos": "all"}],
                                                                         "sw": {"pos": False, "risk": True, "vol": "no"}}]
    r = _run(tmp_path, _routes(_doc([])), local={"cl-charts-grid": "{broken"}, garbage=garbage)
    assert r["first"]["layout"] == "2x2" and len(r["first"]["cells"]) == 4
    for g in r["clean"]:
        assert g["layout"] in ("2x2", "3x3") and len(g["cells"]) == 9
        assert all(c["coin"].endswith("USD") and c["tf"] in ("1m", "5m", "15m", "30m", "1h", "4h", "1d") and isinstance(c["pos"], str) for c in g["cells"])
        assert set(g["sw"]) == {"pos", "risk", "vol"} and all(isinstance(v, bool) for v in g["sw"].values())
    last = r["clean"][-1]
    assert last["layout"] == "3x3" and last["cells"][2]["coin"] == "SOLUSD" and last["cells"][2]["tf"] == "15m" and last["cells"][2]["pos"] == ""
    assert last["cells"][3] == {"coin": "SOLUSD", "tf": "4h", "pos": "all"} and last["sw"] == {"pos": False, "risk": True, "vol": True}
    assert r["clean"][5]["layout"] == "2x2" and r["afterCleanup"] == 0
    # a stored 3x3 grid with a known cell comes back
    st = json.dumps({"layout": "3x3", "cells": [{"coin": "DOGEUSD", "tf": "5m", "pos": ""}], "sw": {"pos": True, "risk": False, "vol": False}})
    r = _run(tmp_path, _routes(_doc([])), local={"cl-charts-grid": st})
    assert r["first"]["layout"] == "3x3" and r["first"]["cells"][0]["coin"] == "DOGEUSD" and r["first"]["cells"][0]["tf"] == "5m"


def test_menu_screens_find_and_static_rules():
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    menu = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", group: "(\w+)"', re.search(r"const MENU = \[(.*?)\];", app, re.S).group(1))
    ids = [m[0] for m in menu]
    i = ids.index("positions")
    assert ids[i + 1] == "charts" and menu[i + 1][1:] == ("여러 차트", "trade")
    assert 'charts: "charts"' in re.search(r"const SCREENS = \{([^}]*)\}", app).group(1)
    assert 'charts: "여러 차트 (코인 · 봉을 칸마다 골라 한 화면에: 캔들 위에 열린 포지션 선)"' in app
    find = open(os.path.join(STATIC, "js", "find.js"), encoding="utf-8").read()
    assert re.search(r"\bcharts: \"여러 차트 ", find)
    from candleague import dash as D
    for rel in ("js/screens/charts.js", "js/live-kit.js", "scr/charts.css"):
        assert rel in D.STATIC_FILES, rel
    src = open(os.path.join(STATIC, "js", "screens", "charts.js"), encoding="utf-8").read()
    assert 'export const css = "scr/charts.css"' in src
    for name in ("js/screens/charts.js", "js/live-kit.js", "scr/charts.css"):
        text = open(os.path.join(STATIC, name), encoding="utf-8").read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
            assert bad not in text, (name, bad)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", text), name                        # colours only from the tokens
    css = open(os.path.join(STATIC, "scr", "charts.css"), encoding="utf-8").read()
    for m in re.finditer(r"font(?:-size)?:[^;}]*", css):
        assert "var(--t-" in m.group(0) or "var(--f-" in m.group(0), m.group(0)                    # font sizes only from the tokens
