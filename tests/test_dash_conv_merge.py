"""Dashboard v4, the merge of conv-a (설정 창, 자는 동안, 전체 화면, 여러 차트) and conv-b (즐겨찾기, 그리기 + 우클릭 알림,
매매법 비교, TV 순환) into the owners' branch (the menu strip, the terminal declutter, the blinking chart light, 메뉴 위치).

What only the two together can break: one start-screen rule, one gear and one ★ per layout, the 설정 panel's 메뉴 위치 and
차트 조명 rows that follow the top bar / the chart (and the other way round), a stored '선' choice that keeps its version
and its 프리미엄 지표 parts when the panel writes it, every screen of both branches in the menu and found by 찾기, the calm
terminal defaults (nothing new ON), and chart colours lightweight-charts can parse. Static checks plus pure functions in
node (a tiny DOM, tests/anasyn_dom.mjs); the screenshots and the click-through of the merge are in the commit's report."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as fh:
        return fh.read()


def _nocomment(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pre = f"await import('file://{os.path.join(ROOT, 'tests', 'anasyn_dom.mjs')}');\n"
    core = "file://" + os.path.join(V4, "core")
    script = pre + f"const CORE = '{core}';\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- routes, start screen, exports
def test_one_start_screen_rule_for_the_router_and_the_settings_panel():
    out = _node("""
    let w = 1920; globalThis.matchMedia = (q) => ({matches: Number((q.match(/min-width: (\\d+)px/) || [0, 0])[1]) <= w, addEventListener() {}});
    const R = await import(CORE + '/routes.js'), P = await import(CORE + '/prefs.js');
    const o = {};
    for (const x of [390, 759, 899, 900, 1920]) { w = x; o[x] = [R.mainLanding(), R.landing()]; }
    w = 390; P.setPref(P.START_KEY, "charts"); o.picked = R.landing(); o.pickedMain = R.mainLanding();
    P.setPref(P.START_KEY, "terminal"); o.pcOnly = R.landing();             // a PC-only choice on a phone: the main rule
    w = 1920; o.pcOnlyWide = R.landing(); P.setPref(P.START_KEY, ""); o.auto = R.landing();
    o.min = R.LANDING_MIN_PX; o.trade = R.GROUPS.find((g) => g.id === "trade").screens; o.strat = R.GROUPS.find((g) => g.id === "strat").screens;
    console.log(JSON.stringify(o));""")
    for width, want in (("390", "chart"), ("759", "chart"), ("899", "chart"), ("900", "terminal"), ("1920", "terminal")):
        assert out[width] == [want, want], (width, out[width])           # no choice: landing() IS the main rule
    assert out["picked"] == "charts" and out["pickedMain"] == "chart"      # the choice wins; the main rule is untouched
    assert out["pcOnly"] == "chart" and out["pcOnlyWide"] == "terminal" and out["auto"] == "terminal"
    assert out["min"] == 900
    assert out["trade"] == ["terminal", "positions", "chart", "charts", "market"]
    assert out["strat"] == ["strategies", "grid", "analysis", "compare", "path", "combo", "combo5y", "whatif"]
    st = _read("core", "settings.js")
    assert "const autoStart = () => SCREENS[mainLanding()].ko;" in st and "LANDING_MIN_PX" not in st
    rt = _read("core", "routes.js")
    assert "return startScreen() || mainLanding();" in rt


def test_pb_exports_both_sides():
    pb = _read("core", "pb.js")
    for line in ('export {listenTicks, ticksState} from "./ticks.js";', 'export {onPref, setPref, GRID_KEY, GRID_DECK} from "./prefs.js";',
                 'export {fullChart} from "./fullchart.js";', 'export * as fav from "./favs.js";', 'export * as cmp from "./cmp.js";'):
        assert line in pb, line


def test_every_screen_of_both_branches_is_in_the_menu_and_found_by_find():
    out = _node("""
    const R = await import(CORE + '/routes.js'), F = await import(CORE + '/find.js');
    const menu = R.navGroups(true).flatMap((g) => g.items.flatMap((it) => it.screens));
    const miss = [], unlisted = [];
    for (const [n, m] of Object.entries(R.SCREENS)) {
      if (m.hidden) continue;
      if (!menu.includes(n)) unlisted.push(n);
      const byName = F.search(m.ko).filter((x) => x.kind === "screen").map((x) => x.id);
      const byCode = F.search(n).filter((x) => x.kind === "screen").map((x) => x.id);
      if (!byName.includes(n) || !byCode.includes(n)) miss.push(n);
    }
    console.log(JSON.stringify({unlisted, miss, charts: F.search("여러").map((x) => x.id), cmp: F.search("비교").map((x) => x.id)}));""")
    assert out["unlisted"] == [] and out["miss"] == []
    assert "charts" in out["charts"] and "compare" in out["cmp"]


# ---------------------------------------------------------------- the chart light and the panel
def test_chart_follows_the_panel_live_for_light_flash_and_lines():
    fx = _read("core", "chartfx.js")
    # the menu's own choices go through prefs (store, then tell every listener: this deck, the other decks, the panel)
    assert "function setLight(id) { setPref(LIGHT_KEY, lightModeOf(id).id); }" in fx
    assert "function setFlash(id) { setPref(FLASH_KEY, modeOf(id).id); }" in fx
    # the panel's choices reach a deck on screen: 번쩍임 repaints the menu words (flashSel is a span, not a select), 조명 syncs
    # the halves and the relay listener
    flash = fx[fx.index("onPref(FLASH_KEY, (v) => {"):fx.index("onPref(LIGHT_KEY, (v) => {")]
    assert "fmode = modeOf(v).id;" in flash and "paintLight();" in flash and '"value" in flashSel' not in fx
    light = fx[fx.index("onPref(LIGHT_KEY, (v) => {"):]
    light = light[:light.index("}),")]
    assert "lmode = lightModeOf(v).id;" in light and "lightSync();" in light
    assert "export {LIGHT_KEY};" in fx and "export {FLASH_KEY};" in fx
    # the panel writes the deck's own stored shape back: version and 프리미엄 지표 parts stay (else the next load starts over)
    assert 'setPref("cfx-" + key, deckValue(now))' in _read("core", "settings.js")
    out = _node("""
    const C = await import(CORE + '/chartfx.js'), P = await import(CORE + '/prefs.js');
    const groups = ["pos", "risk", "sr", "smc", "ev", "vol"];
    const now = C.deckState("term", groups, {sr: false});
    now.off.add("vol"); now.parts.add("liq"); now.hide.add("L1");
    P.setPref("cfx-term", C.deckValue(now));
    const back = C.deckState("term", groups, {sr: false});
    console.log(JSON.stringify({stored: JSON.parse(localStorage.getItem("pb4-cfx-term")), vol: back.off.has("vol"), liq: back.parts.has("liq"), hide: [...back.hide]}));""")
    assert out["stored"]["v"] == 2 and "liq" in out["stored"]["smc"] and out["stored"]["hide"] == ["L1"]
    assert out["vol"] is True and out["liq"] is True and out["hide"] == ["L1"]


def test_settings_panel_has_menu_position_and_chart_light_in_step_with_the_top_bar():
    st = _read("core", "settings.js")
    assert 'import {NAV_POS, navPosNow, setNavPos} from "./navpos.js";' in st
    assert 'choice("메뉴 위치", NAV_POS, navPosNow(), (id) => setNavPos(id))' in st            # the very control of the top bar, via setNavPos
    assert 'import {LIGHT_MODES, lightModeOf} from "./blink.js";' in st
    assert "choice(\"차트 조명\", LIGHT_MODES.map(" in st and "(id) => setPref(LIGHT_KEY, id)" in st
    # the other way round: while the panel is open it follows the top bar's / the rail's switch and the chart's own light menu
    assert 'st.offs = [bus.on("navpos", () => repaint()), onPref(LIGHT_KEY, () => repaint()), onPref(FLASH_KEY, () => repaint())];' in st
    assert "for (const off of st.offs) off();" in st
    nav = _read("core", "navpos.js")
    assert 'bus.emit("navpos", id)' in nav and 'const KEY = "nav";' in nav
    shell = _read("core", "shell.js")
    assert 'bus.on("navpos", (id) => {' in shell and "renderNav(); remount();" in shell      # the shell redraws the top bar's switch


# ---------------------------------------------------------------- one gear, one star per layout
def test_one_gear_and_one_star_per_layout_with_a_tooltip_and_the_keyboard():
    st = _read("core", "settings.js")
    assert 'title: "설정", "aria-label": "설정"' in st and '"aria-keyshortcuts": ","' in st and 'h("button", {type: "button"' in st
    assert 'export const gearButton = () => gear("setbtn", "설정");' in st and 'export const settingsTab = () => gear("setsub", "설정");' in st
    assert 'export const settingsRail = () => gear("setcyc");' in st
    assert 'id: "setbtn"' not in st and 'id="setbtn"' not in st and "find.after(gearButton())" not in st     # no second gear in the top bar
    shell, rail = _read("core", "shell.js"), _read("core", "rail.js")
    assert "tools: [textSwitch(() => remount()), skinSwitch(() => remount()), oldLink(), favTab(), settingsTab()]," in shell   # < 1200 px
    assert "oldLink(), navPosSwitch(), favTopBtn(), gearButton());" in shell                                                  # PC, menu on top
    assert "favRailBtn(), tvRailBtn(), settingsRail()," in rail                                                               # PC, menu on the left
    # which one shows is the container's: the top bar's tools (PC, menu on top), the strip's tools (the rest), the rail
    nav = _nocomment(_read("core", "nav.css"))
    assert ':root:not([data-nav="left"]) .strip-tools { display: none; }' in nav and ':root:not([data-nav="left"]) .toptools { display: inline-flex; }' in nav
    assert ":root[data-nav=\"left\"] .subtabs { display: none; }" in nav and ".toptools { display: none;" in nav
    set_css = _nocomment(_read("core", "settings.css"))
    assert "@media (max-width: 1199px) { .awaybtn { display: none; } }" in set_css and ".setsub { appearance: none; display: inline-flex;" in set_css
    pop = _read("core", "favpop.js")
    assert 'export const favRailBtn = () => favButton("favrail");' in pop and 'export const favTopBtn = () => favButton("favrail favtop");' in pop
    assert 'export const favTab = () => favButton("favsub", "즐겨찾기");' in pop and 'title: "즐겨찾기"' in pop and "$$(\".favbtn\")" in pop
    # the speaker menu and the key "," stay (a shortcut, not a second button); the awaybtn is not a second gear
    assert 'bus.emit("settings:open", "sound")' in _read("core", "sound.js")
    assert 'const anchor = $("#findbtn");' in _read("core", "since.js")


# ---------------------------------------------------------------- the calm terminal
def test_conv_b_hooks_keep_the_terminal_calm():
    tc = _read("screens", "terminal-chart.js")
    # the decluttered deck call and header stay (calm 지지·저항 default, the 보기 ▾ menu); 그리기 is one more button, off
    assert 'defaults: {sr: false},' in tc and "put(fxSlot, deck.lightChip, deck.viewBtn, deck.menuBtn, draw.toggle);" in tc
    assert 'groups: ["pos", "risk", "sr", "smc", "ev", "vol"]' in tc and '"al"' in tc          # the owner's own alert lines: group "al" is not in the '선' menu, so they show
    dk = _read("screens", "draw-kit.js")
    assert '"aria-pressed": "false"' in dk and 'hidden: true' in dk                            # the tools start closed, the toggle off
    assert "key: \"term\"" in tc
    # the key line stays short (details in tooltips): one more hint, short, with its tooltip
    assert '"우클릭 = 알림"' in tc and "차트에서 오른쪽 클릭: 이 가격에 텔레그램 알림 걸기" in tc
    ch = _read("screens", "chart.js")
    assert "draw.toggle, fs);" in ch and "onPref, fullChart, fav}" in ch


def test_chart_colour_tokens_are_ones_lightweight_charts_can_parse():
    tok = _read("tokens.css")
    for name in ("--pick-3", "--draw"):
        line = next(x for x in tok.splitlines() if x.strip().startswith(name + ":"))
        assert "hsl(" not in _nocomment(line), line          # lightweight-charts throws on hsl(300 45% 58%) (the 3rd pick's line)
        assert "rgb(196, 100, 196)" in line                   # = --series-m5, written as rgb
    cmpjs = _read("screens", "compare.js")
    assert "tok(`--pick-${i + 1}`)" in cmpjs
