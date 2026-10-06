"""wave-b merge (term-plus + chart-plus + vp-chart on the owners' branch): the joins the three branches share.

- ONE liquidation colour rule and money format: core/liqkit.js (liqTone / liqKo / usdShort) is the only place that says
  롱 청산 = the up colour, 숏 청산 = the down colour; the chart's bubbles, price bars and note dots (chart-plus), the terminal's
  feed, the flashes, the 시장 board and the chart screen's list all read it (no second copy anywhere in v4);
- the chart deck's onToggle subscribers get (group) or (null, how) and every one of them handles both;
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
    # the subscribers: a group or null (redraw on any null), chart-plus turns its add-ons off on default / none only
    tc, ch = _code(_read("screens", "terminal-chart.js")), _code(_read("screens", "chart.js"))
    assert 'deck.onToggle((g) => { if (g === "ev" || g === "sr" || g == null) drawMarks(); });' in tc
    assert 'deck.onToggle((g) => { if (g === "ev" || g == null) drawMarkers(); if (g === "sr" || g == null) loadLevels(); });' in ch
    plus = _code(_read("screens", "chart-plus.js"))
    assert 'deck.onToggle(safe((g, how) => {' in plus and 'if (g == null && (how === "default" || how === "none")) {' in plus
