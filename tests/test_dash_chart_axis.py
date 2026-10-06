"""The chart's Korea-time axis survives a screen's own timeScale options (the terminal's 15분 chart showed
"4일 4일 4일 5일 ..." with no times: {timeScale: {rightOffset: 26}} replaced the whole block, dropping timeVisible
and the KST tick formatter; owners' screenshot 10/06 13:23)."""
import json
import os
import shutil
import subprocess

import pytest

LWC = os.path.join(os.path.dirname(__file__), "..", "paperbot", "dash", "static", "v4", "core", "lwc.js")


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_merge_keeps_the_time_axis_and_adds_the_screen_options():
    js = (f"import {{mergeOptions, kstTick}} from {json.dumps('file://' + os.path.abspath(LWC))};"
          "const base = {timeScale: {timeVisible: true, secondsVisible: false, tickMarkFormatter: kstTick, borderColor: 'x'},"
          " grid: {vertLines: {color: 'a'}}, width: 10};"
          "const m = mergeOptions(base, {timeScale: {rightOffset: 26}, grid: {horzLines: {color: 'b'}}, height: 5});"
          "console.log(JSON.stringify({tv: m.timeScale.timeVisible, ro: m.timeScale.rightOffset,"
          " fmt: m.timeScale.tickMarkFormatter === kstTick, grid: Object.keys(m.grid).sort(), w: m.width, h: m.height,"
          " base: base.timeScale.rightOffset === undefined, tick: kstTick(Date.UTC(2026, 9, 6, 3, 0) / 1000, 3)}));")
    out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    assert r["tv"] is True and r["ro"] == 26 and r["fmt"] is True       # the axis keeps its times, plus the offset
    assert r["grid"] == ["horzLines", "vertLines"] and r["w"] == 10 and r["h"] == 5
    assert r["base"] is True                                               # the shared defaults are not changed
    assert r["tick"] == "12:00"                                            # 03:00 UTC = 12:00 Korea time


def test_make_chart_uses_the_merge():
    src = open(LWC, encoding="utf-8").read()
    assert "mergeOptions(chartOptions(el), extra)" in src and "{...chartOptions(el), ...extra}" not in src
