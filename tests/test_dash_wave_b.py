"""wave-b merge (term-plus + chart-plus + vp-chart on the owners' branch): the joins the three branches share.

- ONE liquidation colour rule and money format: core/liqkit.js (liqTone / liqKo / usdShort) is the only place that says
  롱 청산 = the up colour, 숏 청산 = the down colour; the chart's bubbles, price bars and note dots (chart-plus), the terminal's
  feed, the flashes, the 시장 board and the chart screen's list all read it (no second copy anywhere in v4);
- the chart deck's onToggle subscribers get (group) or (null, how) and every one of them handles both;
- both chart screens: one deck whose groups are the union (…, "vol", "vp"), the terminal with everything new off, the 차트
  screen with 매물대 on for a PC window; vpPrepare before the deck, vpAttach right after it, then 그리기 and chart-plus's
  one call; the 설정 panel lists the same groups and first choices; the candle rows carry k[9] as "buy" and "taker_buy";
  every route module of the three branches is registered once.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _code(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|[^:\"'`])//.*$", r"\1", ln) for ln in src.splitlines())


def _js_files():
    for base, _dirs, files in os.walk(V4):
        for f in files:
            if f.endswith(".js"):
                p = os.path.join(base, f)
                yield os.path.relpath(p, V4).replace(os.sep, "/"), p


def _node(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pre = (f"const L = await import('file://{os.path.join(V4, 'core', 'liqkit.js')}');\n"
           f"const C = await import('file://{os.path.join(V4, 'screens', 'chart-plus-calc.js')}');\n")
    r = subprocess.run([node, "--input-type=module", "-e", pre + body], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- one liquidation colour rule, one money format
def test_the_liquidation_colour_rule_has_one_source():
    """The map {long: "up", short: "down"} and the words '롱 청산' / '숏 청산' as a choice live in core/liqkit.js only."""
    copies = []
    for rel, p in _js_files():
        if rel == "core/liqkit.js":
            continue
        with open(p, encoding="utf-8") as f:
            src = _code(f.read())
        if re.search(r'\blong\s*:\s*"up"\s*,\s*short\s*:\s*"down"', src) or "LIQ_TONE" in src:
            copies.append(rel)
        if re.search(r'(liquidated|side)\s*===\s*"long"\s*\?\s*"(up|down)"', src) or re.search(r'\blg\s*\?\s*"(up|down)"', src):
            copies.append(rel)
        if re.search(r'"long"\s*\?\s*"롱 청산"\s*:\s*"숏 청산"', src):
            copies.append(rel)
    assert not copies, copies
    assert 'export const LIQ_TONE = Object.freeze({long: "up", short: "down"});' in _read("core", "liqkit.js")


def test_every_liquidation_surface_reads_core_liqkit():
    # the chart's add-ons (bubbles, price bars, the note's colour dots and the bubble legend's amounts)
    liq = _code(_read("screens", "chart-liqmap.js"))
    assert "liqkit} from \"../core/pb.js\"" in liq and "const {liqTone, liqKo, usdShort} = liqkit;" in liq
    assert "koUsdt" not in liq and "만 USDT" not in liq                    # liquidation money is $ K / M, never 만 / 억 here
    plus = _code(_read("screens", "chart-plus.js"))
    assert "const {liqTone, usdShort} = liqkit;" in plus and "dataset: {tone: liqTone(side)}" in plus
    assert 'usdShort(minLiqUsd("BTCUSDT"))' in plus and 'usdShort(minLiqUsd("ETHUSDT"))' in plus
    # the terminal's feed, the flashes, the 시장 board and the chart screen's list (term-plus)
    for f in ("core/flash.js", "screens/terminal-feed.js", "screens/market-live.js", "screens/chart-panels.js"):
        assert "liqTone" in _code(_read(*f.split("/"))), f
    assert "why: liqKo(r.liquidated)" in _read("core", "flash.js")


def test_the_one_rule_in_node():
    out = _node("""console.log(JSON.stringify({tone: [L.liqTone("long"), L.liqTone("short")], ko: [L.liqKo("long"), L.liqKo("short")],
      calc: C.LIQ_TONE === undefined, legend: [L.usdShort(C.minLiqUsd("BTCUSDT")), L.usdShort(C.minLiqUsd("ETHUSDT"))]}));""")
    assert out["tone"] == ["up", "down"] and out["ko"] == ["롱 청산", "숏 청산"]
    assert out["calc"] is True                                                       # chart-plus-calc.js keeps no copy
    assert out["legend"] == ["$50.0K", "$10.0K"]                                     # the bubbles' smallest amounts, in the one format


# ---------------------------------------------------------------- the chart deck's shared hooks
def test_every_ontoggle_subscriber_takes_the_how_argument():
    fx = _code(_read("core", "chartfx.js"))
    assert 'fn(null, on ? "all" : "none")' in fx and 'fn(null, "default")' in fx and 'fn(null, "pref")' in fx
    assert re.search(r"for \(const fn of subs\) fn\(null\);", fx) is None             # every several-at-once call says how
    assert "onData(fn) { dataSubs.push(fn); }" in fx and "menuEl: menu," in fx
    # with chart-plus's second column the '선' menu is ~520 px wide: on a 1280 px terminal it hung off the window's left edge
    assert "if (on) { paintMenu(); keepInView();" in fx and 'if (r.left < 8) menu.style.right = `${Math.round(r.left - 8)}px`;' in fx
    # the subscribers: a group or null (redraw on any null), chart-plus turns its add-ons off on default / none only
    tc, ch = _code(_read("screens", "terminal-chart.js")), _code(_read("screens", "chart.js"))
    assert 'deck.onToggle((g) => { if (g === "ev" || g === "sr" || g == null) drawMarks(); });' in tc
    assert 'deck.onToggle((g) => { if (g === "ev" || g == null) drawMarkers(); if (g === "sr" || g == null) loadLevels(); });' in ch
    plus = _code(_read("screens", "chart-plus.js"))
    assert 'deck.onToggle(safe((g, how) => {' in plus and 'if (g == null && (how === "default" || how === "none")) {' in plus
    vp = _code(_read("screens", "chart-vp.js"))
    assert 'deck.onToggle((grp) => { if (grp === "vp" || grp == null) sync(); });' in vp      # any several-at-once change: sync


# ---------------------------------------------------------------- the two chart screens: one deck, every add-on hooked once
def test_both_chart_screens_join_the_three_branches_hooks():
    tc, ch = _code(_read("screens", "terminal-chart.js")), _code(_read("screens", "chart.js"))
    groups = 'groups: ["pos", "risk", "sr", "smc", "ev", "vol", "vp"]'            # chart-plus adds no group: its own menu column
    # the terminal: everything new off (지지·저항 off as the declutter left it, 매물대 off, chart-plus's add-ons off on their own)
    assert groups in tc and "defaults: {sr: false, vp: false}," in tc
    # the 차트 screen: 매물대 on for a PC window, off on a phone (the owners asked for it by name)
    assert groups in ch and "defaults: narrow() ? {pos: false, risk: false, sr: false, smc: false, vp: false} : {vp: true}," in ch
    for src, key in ((tc, "term"), (ch, "chart")):
        i_prep, i_deck = src.index(f'vpPrepare("{key}"'), src.index("deck = chartDeck({")
        i_vp, i_tog = src.index(f'vpAttach({{chart: C.chart, series, deck, wrap, box, ctx, key: "{key}"'), src.index("deck.onToggle((g) =>")
        i_draw, i_plus = src.index("draw = drawTools({"), src.index("chartPlus({")
        assert i_prep < i_deck < i_vp < i_tog < i_draw < i_plus, key           # vpPrepare before the deck, vpAttach right after it
        assert src.count("chartPlus({") == 1 and src.count("vpAttach({") == 1 and src.count("drawTools({") == 1, key
    # the 매물대 legend row sits under the chart (chart-plus puts its notes and panes right after the chart box: wrap.after(below))
    assert "}, wrap, vpHost, keyLine);" in tc and "fxBar, wrap, vpHost, tv.el," in ch
    # term-plus's failed-load note and the 차트 크게 보기 marks are kept
    assert 'const wrap = h("div", {class: "term-cwrap"}, box, legend, dot, tag, tip, cfail);' in tc
    assert 'const box = h("div", {class: "chart-box", "data-fc-box": ""});' in ch


def test_the_settings_panel_lists_the_same_groups_and_first_choices():
    """The 설정 panel writes a deck's choices back with its own group list: without "vp" it would switch the 매물대 on."""
    st = _code(_read("core", "settings.js"))
    assert '["term", "터미널 차트", ["pos", "risk", "sr", "smc", "ev", "vol", "vp"], () => ({sr: false, vp: false})],' in st
    assert '["chart", "차트 화면", ["pos", "risk", "sr", "smc", "ev", "vol", "vp"], () => ({vp: !phone()})],' in st
    assert 'const defaults = typeof defs === "function" ? defs() : defs;' in st
    assert 'if (groups.includes("vp") && defaults && defaults.vp === false && !local.get("vp-seen-" + key, false)) now.off.add("vp");' in st
    vp = _read("screens", "chart-vp.js")
    assert 'local.get(PREF + "seen-" + key, false)' in vp and 'const PREF = "vp-";' in vp            # the same "vp-seen-" key
    assert 'vp: "매물대"' in _code(_read("core", "chartfx.js"))


def test_style_imports_sit_together_at_the_top():
    for name, need in (("terminal.css", ("positions-kit.css", "flow-kit.css", "draw-kit.css", "terminal-plus.css", "chart-plus.css", "chart-vp.css")),
                       ("chart.css", ("positions-kit.css", "draw-kit.css", "terminal-coinpos.css", "chart-plus.css", "chart-vp.css"))):
        lines = re.sub(r"/\*.*?\*/", "", _read("screens", name), flags=re.S).strip().splitlines()
        assert [re.search(r'"([^"]+)"', ln).group(1) for ln in lines[:len(need)] if ln.startswith("@import")] == list(need), name
        assert "@import" not in "\n".join(lines[len(need):]), name
    # the terminal chart panel's rows: the candles, then chart-plus's notes + panes, the 매물대 legend, the key line (auto rows)
    assert ".term-chart .term-pb { flex: 1 1 auto; display: grid; grid-template-rows: minmax(0, 1fr) auto auto; padding: 0; }" in _read("screens", "terminal.css")


def test_candle_rows_carry_the_taker_buy_volume_under_both_names(monkeypatch):
    import paperbot.dash.app as A

    class _Resp:
        def __init__(self, rows):
            self.rows = rows

        def read(self):
            return json.dumps(self.rows).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    k = [1_700_000_000_000, "100", "102", "99", "101", "20.5", 1_700_000_059_999, "2070", 17, "15.25", "1540", "0"]
    monkeypatch.setattr(A.urllib.request, "urlopen", lambda url, timeout=0: _Resp([k]))
    A._CANDLE_CACHE.clear()
    try:
        row = A.fetch_candles("BTCUSDT", "1m", 1)[0]
        assert row == {"time": 1_700_000_000, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 20.5,
                       "buy": 15.25, "taker_buy": 15.25}                 # vp-chart's "buy" and chart-plus's "taker_buy", every key kept
        monkeypatch.setattr(A.urllib.request, "urlopen", lambda url, timeout=0: _Resp([k[:7]]))
        A._CANDLE_CACHE.clear()
        row = A.fetch_candles("ETHUSDT", "1m", 1)[0]
        assert "buy" not in row and "taker_buy" not in row                 # no field: no key, never a made-up zero
    finally:
        A._CANDLE_CACHE.clear()


def test_the_route_modules_of_all_three_branches_are_registered():
    from paperbot.dash.more import MODULES
    for name in ("topstats", "termpnl", "chartplus", "vplevels", "compare"):
        assert MODULES.count(name) == 1, name
