"""Wave 2 터미널 (#/terminal, owners 10/05: the old v3 트레이드 tab's density in the "AI" look, PC only).

- the route exists as the 거래 group's first sub tab, is a PC screen (`feature: "wide"`, off the phone menu) and is
  the start screen on a PC window (owners 10/06 13:27: "요약화면이 아니라 차트화면부터"; a window at least 900 px wide,
  where the top menu shows and the terminal fits; a phone or a tablet held upright starts on the 차트 screen; unknown
  screens never fall back to the terminal, so a narrow window cannot loop);
- the terminal's css and js carry no colour literals (tokens only), and its motion stops under reduced motion and on a
  hidden page;
- the honesty captions are there: the shared money captions under fills / open P&L / closed trades, 참고 on the group
  return, DeepSeek and coin flips only as counts in the fills feed, no pass / fail words;
- it reuses the existing helpers and routes (chart engine, positions kit, book, flow race / calendar) and adds no
  polling faster than those screens already do.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
FILES = ["terminal.js", "terminal-kit.js", "terminal-top.js", "terminal-feed.js", "terminal-chart.js", "terminal-side.js",
         "terminal-table.js", "terminal.css"]


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _src(name):
    return _read("screens", name)


def _code(src):
    """The source without // and /* */ comments (good enough for these files: no '//' inside their strings)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", src)


def test_route_is_the_first_trade_tab_and_a_pc_screen():
    routes = _read("core", "routes.js")
    trade = re.search(r'\{id: "trade", ko: "거래", screens: \[([^\]]*)\]', routes).group(1)
    assert [x.strip().strip('"') for x in trade.split(",")][0] == "terminal"
    meta = re.search(r"^\s*terminal: \{(.*?)\},?$", routes, re.M).group(1)
    assert 'group: "trade"' in meta and 'feature: "wide"' in meta and "hidden" not in meta
    for f in FILES:
        assert os.path.exists(os.path.join(V4, "screens", f)), f
    js = _src("terminal.js")
    assert re.search(r"^export (async )?function mount\(el, ctx\)", js, re.M) and re.search(r"^export function unmount\(", js, re.M)
    # the wide flag is measured in the page, never asked from the server, and the router knows it without a probe
    feats = _read("core", "features.js")
    assert 'matchMedia("(min-width: 760px)")' in feats and "wide:" in feats
    assert 'meta.feature === "wide"' in _read("core", "router.js")


def _landing(width):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    script = (f"globalThis.matchMedia = (q) => ({{matches: Number((q.match(/min-width: (\\d+)px/) || [0, 0])[1]) <= {width}}});\n"
              f"const routes = await import('{core}/routes.js');\n"
              "console.log(JSON.stringify({empty: routes.parseHash('').name, bare: routes.parseHash('#/').name,"
              " home: routes.parseHash('#/home').name, def: routes.DEFAULT, land: routes.landing()}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("width,want", [(390, "chart"), (759, "chart"), (760, "chart"), (899, "chart"), (900, "terminal"),
                                        (1024, "terminal"), (1199, "terminal"), (1200, "terminal"), (1920, "terminal")])
def test_landing_rule(width, want):
    out = _landing(width)
    assert out["empty"] == want and out["bare"] == want and out["land"] == want
    assert out["home"] == "home"                 # an explicit #/home always opens 홈
    assert out["def"] == "home"                  # the fallback of unknown / switched-off screens is never the terminal


def test_no_colour_literals_and_motion_respects_reduced_motion_and_hidden_pages():
    for f in FILES:
        src = _code(_src(f))
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), (f, "colour literal")
        assert not re.search(r"\b(rgba?|hsla?)\(\s*\d", src), (f, "colour literal")
    css = _src("terminal.css")
    rm = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    for cls in (".term-marq-in.run", ".term-dot.on"):
        assert cls in rm, cls                                       # the two loops stop under reduced motion
        assert f'.term[data-still="1"] {cls.split(".run")[0].split(".on")[0]}' in css or "data-still" in css
    assert "visibilitychange" in _src("terminal.js") and "dataset.still" in _src("terminal.js")
    # one-shots go through the shared helpers (they skip reduced motion and hidden pages), only for real changes
    feed = _src("terminal-feed.js")
    assert "motion.fillIn(" in feed and "motion.tickPrice(" in feed
    assert "motion.tickPrice(" in _src("terminal-top.js") and "motion.flashPrice(" in _src("terminal-chart.js")
    assert "if (m.live && live())" in feed                          # rows drawn on mount never slide in
    # the breathing dot shows live state only while the stream is really live
    assert 'dot.classList.toggle("on", stream.live())' in _src("terminal-chart.js")


def test_honesty_captions_are_present():
    feed, side, table, top = _src("terminal-feed.js"), _src("terminal-side.js"), _src("terminal-table.js"), _src("terminal-top.js")
    assert "ui.assume()" in feed                                    # money in the fills feed
    assert 'ui.assume("open")' in side and 'ui.assume("open")' in table and 'ui.assume("closed")' in table
    assert 'ui.pill("", "ref")' in side                              # the group return is 참고 (the pill prints the word)
    assert "판정이 아닙니다" in side
    assert 'FOLD = new Set(["ds", "coin"])' in feed                 # DeepSeek / coin flips: counts only, no money per account
    fold = feed[feed.index("const what = "):feed.index("function render()")]
    assert "pnl" not in fold.replace("m.one", "")
    assert "수집 전" in side and "기록 없음" in side                  # nothing drawn before real points, no zero for a missing day
    assert "running" in top and "회의 중" in top                      # 회의 중 only from office.running
    for f in FILES:
        src = _src(f)
        assert "innerHTML" not in src and "toLocaleString" not in src, f
        for word in ("합격", "불합격", "통과"):
            assert word not in src, (f, word)


def test_reuses_existing_helpers_and_polls_no_faster_than_the_screens_it_borrows_from():
    chart, side, js = _src("terminal-chart.js"), _src("terminal-side.js"), _src("terminal.js")
    assert "makeChart" in chart and "candleOptions" in chart and 'from "./chart-lines.js"' in chart
    assert 'from "./positions-kit.js"' in _src("chart-lines.js")              # the position lines: one helper for 차트 and 터미널
    assert 'import {bookPanel} from "./positions-book.js"' in js
    assert 'from "./flow-cal.js"' in side and "CAL_API" in side        # term v2: the 수익 card reads the calendar answer
    # clock, forming bar, liq, office, movers (term v2: the server caches 60 s), levels, GH / calendar
    known = {1000, 5000, 10000, 30000, 60000, 120000, 300000}
    for f in FILES:
        for ms in re.findall(r"ctx\.every\((\d+)", _src(f)):
            assert int(ms) in known, (f, ms)
    # the clock tick only repaints (no request inside the 1 s tick)
    tick = js[js.index("ctx.every(1000"):].split("\n")[0]
    assert "api" not in tick


def test_inventory_lists_the_terminal():
    inv = _read("INVENTORY.md")
    assert "터미널" in inv and "`#/terminal`" in inv
