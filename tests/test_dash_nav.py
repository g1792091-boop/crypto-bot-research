"""Dashboard v4, fewer clicks (owners 10/06: "들어가는 클릭버튼이 너무 많아서 들어가서 보는게 귀찮다"), with the menu
where the owners want it (10/06 ~14:00, with a photo of the old v3 tab bar: "클릭해서 바로 들어갈수있는 버튼들을 많이
만들어줬으면", "왼쪽에 그림으로 되어있는데 너무 헷갈려"; 13:27: "들어가면 요약화면이 아니라 차트화면부터"): every screen its
own text button in one strip under the top bar (no icons, no group to open first), the left rail as a stored choice
(메뉴 위치), the terminal as the start screen, the side panel for accounts / strategies / trades, 찾기 ('/'), the number
keys 1-9 and the phone's sideways swipe. Static checks on the v4 files, plus the pure parts in node (search, routes, the
stored choice)."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def _read(rel: str) -> str:
    with open(os.path.join(V4, rel), encoding="utf-8") as fh:
        return fh.read()


def _nocomment(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    script = (f"const search = await import('{core}/search.js'); const routes = await import('{core}/routes.js');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- the menu: the strip on top by default, the left rail by choice
def _node_dom(body: str) -> dict:
    """node with a fake <html> (dataset) and a fake localStorage, for core/navpos.js."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    script = ("globalThis.document = {documentElement: {dataset: {}}};\n"
              "const mem = new Map();\n"
              "globalThis.localStorage = {getItem: (k) => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => mem.set(k, String(v)),"
              " removeItem: (k) => mem.delete(k)};\n"
              f"const nav = await import('{core}/navpos.js'); const api = await import('{core}/api.js');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _media(css: str, head: str) -> str:
    """The body of the first `@media ... {` block whose head starts with `head` (to its closing line)."""
    block = css[css.index(head):]
    return block[:block.index("\n}\n") + 3]


def test_index_has_the_strip_the_rail_the_crumb_and_the_find_button():
    html = _read("index.html")
    # the strip under the top bar is the menu (the default); the rail is there for the 왼쪽 choice; the phone bar stays
    for x in ('<nav class="subtabs strip" id="subtabs" aria-label="화면 메뉴"></nav>', 'id="botbar"',
              '<nav class="rail" id="rail" aria-label="모든 화면"></nav>', '<span class="toptools" id="toptools"></span>'):
        assert x in html, x
    assert 'id="groups"' not in html and "gbtn" not in html                              # the group bar + dropdowns are gone
    assert not os.path.exists(os.path.join(V4, "core", "topnav.js"))
    assert 'id="crumb"' in html and 'id="findbtn"' in html and "단축키 /" in html
    assert '<link rel="stylesheet" href="/static/v4/core/nav.css">' in html
    # the top bar keeps the brand mark, 찾기, the D+n chip and the health dot (the bell and the speaker join at boot)
    top = html[html.index('<header class="top">'):html.index("</header>")]
    for x in ('class="brand"', 'id="findbtn"', 'id="dchip"', 'id="hdot"', 'class="mocktag"'):
        assert x in top, x
    shell = _read("core/shell.js")
    assert "bellButton()" in shell and "soundButton()" in shell


def test_strip_is_the_default_and_the_rail_only_a_choice():
    """Owners 10/06 13:27: "클릭하는 버튼들이 다 왼쪽으로 바꼈네??" - the menu is on top by default; 10/06 ~14:00: as v3's
    tab bar, every screen a direct text button."""
    css = _nocomment(_read("core/nav.css"))
    assert re.search(r"^\.rail \{ display: none; \}", css, re.M)                        # no rail unless chosen
    left = _media(css, "@media (min-width: 1200px) {\n  :root[data-nav=\"left\"]")
    # every rule that hides the strip or shows the rail is under [data-nav="left"]
    for rule in ('--sub-h: 0px', "padding-left: var(--rail-w)", ".subtabs { display: none; }", ".crumb { display: flex; }", ".rail { position: fixed;"):
        line = next(x for x in left.splitlines() if rule in x)
        assert ':root[data-nav="left"]' in line, line
    assert css.count(".subtabs { display: none; }") == 1                                # nothing else hides the strip
    assert ".groups" not in css and ".gmenu" not in css and ".gw" not in css             # the old group bar is gone
    assert ".groups" not in _nocomment(_read("base.css"))
    # a PC window with the strip: the header spans the window and the buttons wrap (never a sideways scroll there)
    pc = _media(css, "@media (min-width: 1200px) {\n  :root:not([data-nav=\"left\"])")
    assert ':root:not([data-nav="left"]) .top, :root:not([data-nav="left"]) .subtabs { max-width: none;' in pc
    assert ':root:not([data-nav="left"]) .subtabs { flex-wrap: wrap; overflow: visible;' in pc
    # the settings move to the top bar there; below 1200 px they stay at the strip's end
    assert ':root:not([data-nav="left"]) .strip-tools { display: none; }' in pc and ':root:not([data-nav="left"]) .toptools { display: inline-flex; }' in pc
    assert re.search(r"^\.toptools \{ display: none;", css, re.M) and re.search(r"^\.navsw \{ display: none; \}", css, re.M)
    out = _node_dom("console.log(JSON.stringify({def: nav.DEFAULT_NAV, ids: nav.NAV_POS.map((x) => x.id), ko: nav.NAV_POS.map((x) => x.ko)}));")
    assert out == {"def": "top", "ids": ["top", "left"], "ko": ["위", "왼쪽"]}
    main = _read("core/main.js")
    assert 'import {applyNavPos} from "./navpos.js";' in main and main.index("applyNavPos();") < main.index("startShell();")


def test_menu_position_is_stored_per_device_and_survives_blocked_storage():
    out = _node_dom("""
    const seen = []; api.bus.on("navpos", (id) => seen.push(id));
    const o = {def: nav.currentNavPos(), applied: nav.applyNavPos()};
    o.set = nav.setNavPos("left"); o.stored = mem.get("pb4-nav"); o.html = document.documentElement.dataset.nav;
    o.again = nav.setNavPos("left"); o.bad = nav.setNavPos("middle"); o.seen1 = [...seen];
    mem.set("pb4-nav", JSON.stringify("sideways")); o.weird = nav.currentNavPos();
    mem.set("pb4-nav", JSON.stringify("left")); o.back = nav.currentNavPos();
    globalThis.localStorage = {getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }};
    o.blocked = nav.currentNavPos(); o.bset = nav.setNavPos("top"); o.bhtml = document.documentElement.dataset.nav; o.bnow = nav.navPosNow();
    o.seen2 = seen;
    console.log(JSON.stringify(o));""")
    assert out["def"] == "top" and out["applied"] == "top"                      # nothing stored: the strip on top
    assert out["set"] == "left" and out["stored"] == '"left"' and out["html"] == "left"
    assert out["again"] == "left" and out["bad"] == "left" and out["seen1"] == ["left"]   # same / unknown: no event
    assert out["weird"] == "top" and out["back"] == "left"
    # blocked storage (a private window): the default, and a switch still applies for this page
    assert out["blocked"] == "top" and out["bset"] == "top" and out["bhtml"] == "top" and out["bnow"] == "top"
    assert out["seen2"] == ["left", "top"]
    js = _read("core/navpos.js")
    assert 'import {h, local} from "./dom.js"' in js and "localStorage" not in js        # through the try/catch helper
    assert 'const KEY = "nav";' in js and "local.get(KEY" in js and "local.set(KEY" in js
    assert "export function setNavPos(id)" in js and 'bus.emit("navpos", id)' in js
    assert '"aria-pressed"' in js and 'h("span", {class: "k"}, "메뉴 위치")' in js and '"aria-label": "메뉴 위치"' in js


def test_settings_sit_in_the_top_bar_on_a_pc_and_at_the_strips_end_below():
    shell = _read("core/shell.js")
    strip = shell[shell.index("renderStrip(p.name, badges, {"):shell.index('const tt = $("#toptools");')]
    # below 1200 px: 글자 크기, 화면 색, 예전 화면 at the strip's end; 찾기 + the one-button 글자 크기 at its start
    assert "lead: [findTab(), textCycle(() => remount())]," in strip
    # (and the gear that opens 설정, core/settings.js: ONE per layout, here for the strip below 1200 px)
    assert "tools: [textSwitch(() => remount()), skinSwitch(() => remount()), oldLink(), favTab(), settingsTab()]," in strip
    # a PC: the full switches from 1680 px, one small button each below, 예전 화면 and 메뉴 위치 (the settings panel's hook)
    top = shell[shell.index('const tt = $("#toptools");'):]
    top = top[:top.index("\n}\n")]
    assert 'h("span", {class: "tt-full"}, textSwitch(() => remount()), skinSwitch(() => remount()))' in top
    assert 'h("span", {class: "tt-mini"}, textCycle(() => remount()), skinCycle(() => remount()))' in top
    assert "oldLink(), navPosSwitch(), favTopBtn(), gearButton());" in top               # ★ and the gear close the top bar tools
    assert 'const oldLink = () => h("a", {class: "oldui", href: "/v3"' in shell
    css = _nocomment(_read("core/nav.css"))
    assert "@media (min-width: 1680px) { .toptools .tt-full { display: inline-flex; } .toptools .tt-mini { display: none; } }" in css
    rail = _read("core/rail.js")
    assert 'h("div", {class: "rail-foot"}, navPosSwitch(),' in rail                     # and the rail's foot
    assert 'h("div", {class: "rail-tools"}, favRailBtn(), tvRailBtn(), settingsRail(), skinCycle(onRedraw),' in rail  # the tools: ★ TV gear ◐ v3
    navpos = shell[shell.index('bus.on("navpos", (id) => {'):]
    assert navpos.index("renderNav(); remount();") < navpos.index("});")                 # any caller: menu + screen redrawn
    assert '.navsw button[data-nav="${id}"]' in navpos                                   # the keyboard focus follows the switch
    inv = _read("INVENTORY.md")
    assert "setNavPos(" in inv and "currentNavPos()" in inv and "메뉴 위치" in inv            # the settings panel's hook


def test_strip_is_one_text_button_per_screen_like_v3():
    t = _read("core/strip.js")
    assert "export function renderStrip(cur, badges, {lead = [], tools = []} = {})" in t
    assert "navGroups(features)" in t                                                   # every menu screen, from routes.js
    assert "screenIcon" not in t and "icon(" not in t and "<svg" not in t                 # text only, no pictures
    # one link per button: the current one lit, the dot of news, 꺼짐, the number key in the tooltip
    assert 'h("a", {class: ["sb", off ? "off" : ""], href: href(it.to), "aria-current": on ? "page" : null, title: tip,' in t
    assert '"aria-keyshortcuts": k' in t and "숫자 키 ${k}" in t
    assert 'news ? h("i", {class: "ndot", "aria-label": "새 소식"}) : null' in t and '"꺼짐"' in t
    assert "it.screens.includes(cur)" in t and "it.screens.some((n) => badges[n])" in t
    assert 'h("div", {class: "sg", role: "group", "aria-label": g.ko' in t                # the groups, named for screen readers
    # the focus and the sideways scroll survive a redraw; the current button is brought into view (that row only)
    assert "nav.replaceChildren(...lead, ...groups, h(\"span\", {class: \"strip-tools\"}, tools));" in t
    assert 'b.focus({preventScroll: true})' in t and "nav.scrollTo({left:" in t and "scrollIntoView" not in t
    # the wheel scrolls the sideways row (a mouse below 1200 px), never the page there
    assert 'nav.addEventListener("wheel"' in t and "{passive: false}" in t and "if (nav.scrollLeft !== before) e.preventDefault();" in t
    assert "nav.scrollLeft = keepX;" in t                                                # a redraw keeps the row where it was
    css = _nocomment(_read("core/nav.css"))
    # v3: plain text, the current one bold with an accent underline; a lit button is as wide as an unlit one
    assert '.sb[aria-current="page"] { color: var(--ink); font-weight: 700; }' in css
    assert '.sb[aria-current="page"]::after { content: ""; position: absolute;' in css and "background: var(--accent);" in css
    assert '.sb-t::after { content: attr(data-t) / ""; height: 0; overflow: hidden; visibility: hidden; font-weight: 700; }' in css
    assert ".strip .sg + .sg::before {" in css and ".strip .sg[data-rowstart]::before { display: none; }" in css
    assert ".strip { column-gap: 15px; }" in css                                         # a wrapped row starts flush
    # the phone's 찾기 stays at the row's left edge
    assert ".strip .findsub { position: sticky; left: 0;" in css
    shell = _read("core/shell.js")
    assert "renderStrip(p.name, badges, {" in shell and "renderGroups" not in shell and 'put($("#subtabs")' not in shell
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\brgba?\(\s*\d", css)   # tokens only


def test_strip_height_is_measured_into_sub_h():
    """The screens' sticky parts sit under the strip however many rows it has (1 on a 1920 window, 2 when it wraps)."""
    t = _read("core/strip.js")
    assert 'root.style.setProperty("--sub-h", `${px}px`)' in t and "nav.offsetHeight" in t
    assert "new ResizeObserver(() => measure())" in t and "document.fonts.ready.then(measure" in t
    assert 'g.toggleAttribute("data-rowstart", top != null && t > top + 4);' in t
    base = _nocomment(_read("base.css"))
    sub = next(x for x in base.splitlines() if x.startswith(".subtabs {"))
    assert "min-height: 44px;" in sub and "var(--sub-h)" not in sub                      # it never reads what it writes
    # the screens keep reading --sub-h for their sticky tops and heights
    assert "var(--sub-h)" in _read("screens/terminal.css") and "var(--sub-h)" in _read("screens/chart.css")
    # the red critical banner sits in the same sticky header: its height counts while it shows (review: the analysis
    # tabs slid under it and the 터미널 ran past the window's bottom by its height), and a change of it re-measures
    assert 'const px = nav.offsetHeight + (crit ? crit.offsetHeight : 0);' in t
    assert "if (crit) st.ro.observe(crit);" in t
    html = _read("index.html")
    shell_top = html[html.index('<div class="shell-top">'):html.index('<nav class="rail"')]
    assert 'id="crit"' in shell_top and 'id="subtabs"' in shell_top


def test_strip_keeps_still_and_the_top_bar_fits():
    """Review fixes: the buttons do not shift when the 터미널 is opened or left; the top bar's small 글자 크기 button
    reads centred; the D+n chip keeps its 관찰 date at 1200-1439 px with 아주 크게."""
    css = _nocomment(_read("core/nav.css"))
    pc = _media(css, "@media (min-width: 1200px) {\n  :root:not([data-nav=\"left\"])")
    assert ':root:not([data-nav="left"]) .top, :root:not([data-nav="left"]) .subtabs { max-width: none; padding-inline: 12px; }' in pc
    term = _read("screens/terminal.css")
    assert 'body:has(.scr[data-screen="terminal"]) .subtabs { max-width: none; padding-inline: 12px; }' in term   # the same edge
    base = _nocomment(_read("base.css"))
    cyc = next(x for x in base.splitlines() if x.startswith(".textcyc {"))
    assert "align-items: center;" in cyc and "baseline" not in cyc
    assert ('@media (min-width: 1200px) and (max-width: 1439px) { :root[data-text="xl"]:not([data-nav="left"]) .brand-t { display: none; } }'
            in base)
    assert 'class="bic"' in _read("index.html")                                          # the brand's mark itself always stays


def test_menu_order_captions_keys_and_new_screens_in_node():
    out = _node("""
    const pc = routes.navGroups({wide: true}), phone = routes.navGroups({wide: false, debate: false}), all = routes.navGroups(true);
    const flat = (gs) => gs.flatMap((g) => g.items.map((it) => it.id));
    const o = {groups: pc.map((g) => [g.group, g.ko]), pc: flat(pc), phone: flat(phone), help: pc[4].items.find((it) => it.id === "help"),
      keys: routes.KEYS, keyOf: ["terminal", "home", "strategies", "server", "flow", "debate"].map(routes.keyOf),
      label: ["home", "agents", "trade"].map(routes.navLabel)};
    // a screen added to a group in routes.js shows in the menu by itself (조합 성과 / 졸업 길 are coming)
    routes.SCREENS.fresh = {ko: "새 화면", group: "strat", title: "새 화면"};
    routes.GROUPS.find((g) => g.id === "strat").screens.push("fresh");
    o.added = routes.navGroups({wide: true})[2].items.map((it) => it.ko);
    // a group added to GROUPS but not to NAV comes last under its own name
    routes.SCREENS.lab = {ko: "실험실", group: "lab", title: "실험실"};
    routes.GROUPS.push({id: "lab", ko: "실험실", screens: ["lab"]});
    o.extra = routes.navGroups({wide: true}).map((g) => g.ko);
    console.log(JSON.stringify(o));""")
    assert out["groups"] == [["trade", "거래"], ["home", "성적"], ["strat", "매매법"], ["agents", "AI 직원"], ["server", "서버"]]
    assert out["pc"] == ["terminal", "positions", "chart", "charts", "market", "home", "board", "flow", "checkpoint", "strategies", "grid", "analysis",
                         "compare", "path", "combo", "combo5y", "whatif", "office", "rooms", "digest", "debate", "server", "alerts", "signals", "help"]
    assert out["phone"] == [x for x in out["pc"] if x != "terminal"]                     # the PC 터미널 is off a phone's menu; 토론방 stays
    assert out["help"] == {"id": "help", "ko": "도움말", "to": "howto", "screens": ["howto", "faq"]}
    # 여러 차트 (conv-a) sits next to 차트: it takes key 4, so 요약 is key 6 now and 매매법 has no number key
    assert out["keys"] == ["terminal", "positions", "chart", "charts", "market", "home", "board", "flow", "checkpoint"]
    assert out["keyOf"] == ["1", "6", None, None, "8", None]
    assert out["label"] == ["성적", "AI 직원", "거래"]
    assert out["added"] == ["매매법", "한눈 지도", "분석", "비교", "졸업 길", "조합 성과", "5년 조합", "만약 실험실", "새 화면"]   # a new screen gets its button by itself
    assert out["extra"] == ["거래", "성적", "매매법", "AI 직원", "서버", "실험실"]
    out = _node("""
    const g = (id) => routes.GROUPS.find((x) => x.id === id);
    console.log(JSON.stringify({tradePc: routes.menuScreens(g("trade"), {wide: true}), tradePhone: routes.menuScreens(g("trade"), {wide: false}),
      tradeAll: routes.menuScreens(g("trade"), true), home: routes.menuScreens(g("home"), {}), agents: routes.menuScreens(g("agents"), {debate: false})}));""")
    assert out["tradePc"] == out["tradeAll"] == ["terminal", "positions", "chart", "charts", "market"]
    assert out["tradePhone"] == ["positions", "chart", "charts", "market"]
    assert out["home"] == ["home", "board", "flow", "checkpoint"]                        # hidden screens (계좌, 하이라이트) out
    assert out["agents"] == ["office", "rooms", "digest", "debate"]                      # 토론방 stays (greyed 꺼짐)


def test_help_button_keeps_both_screens_one_click_away():
    routes = _read("core/routes.js")
    assert 'export const JOINED = [{id: "help", ko: "도움말", screens: ["howto", "faq"]}];' in routes
    t = _read("core/strip.js")
    assert "export function joinedTabs(name)" in t and '"aria-current": n === name ? "page" : null' in t
    assert 'export {joinedTabs} from "./strip.js";' in _read("core/pb.js")
    # each of the two screens shows the switch right under its title
    assert 'ui.screenHead("어떻게 돌아가나", "한 거래가 신호에서 판정까지 지나가는 여섯 단계"), joinedTabs("howto"),' in _read("screens/howto.js")
    assert 'el.append(ui.screenHead("자주 묻는 질문", "짧게 묻고 짧게 답합니다"), joinedTabs("faq"));' in _read("screens/faq.js")
    css = _nocomment(_read("core/nav.css"))
    assert '.jt-a[aria-current="page"] {' in css
    # 찾기 still finds each by its own name, and by 도움말
    f = _read("core/find.js")
    assert 'const j = JOINED.find((x) => x.screens.includes(n));' in f and "sub: navLabel(g.id)" in f


def test_left_rail_reads_by_itself():
    rail = _read("core/rail.js")
    assert "export function renderRail(cur, badges, onRedraw)" in rail
    assert "navGroups(features).map(" in rail                                            # the very buttons of the strip
    assert '"aria-current": it.screens.includes(cur) ? "page" : null' in rail             # the current one lit
    assert 'h("span", {class: "rail-t", "aria-hidden": "true"}, it.ko)' in rail           # the Korean name beside the icon
    assert 'h("p", {class: "rail-h", id: `rh-${g.group}`}, g.ko)' in rail and '"aria-labelledby": `rh-${g.group}`' in rail   # headings
    assert "it.screens.some((n) => badges[n])" in rail and '"ndot"' in rail and "keyOf(it.to)" in rail
    assert "textCycle(onRedraw)" in rail and "skinCycle(onRedraw)" in rail and 'href: "/v3"' in rail
    assert 'role: "tooltip"' not in rail                                                 # no hover-only labels any more
    shell = _read("core/shell.js")
    assert "renderRail(p.name, badges, () => remount())" in shell
    assert 'h("span", {class: "crumb-g"}, navLabel(gid))' in shell                       # "성적 › 요약"
    css = _nocomment(_read("core/nav.css"))
    assert ":root[data-nav=\"left\"] { --rail-w: calc(184px * var(--ts)); --sub-h: 0px; }" in css   # grows with 글자 크기
    assert '.rail-a[aria-current="page"] { color: var(--ink); background: var(--accent-soft);' in css
    assert ".rail-t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }" in css
    # the rows carry data-screen: screens/terminal.css' bare [data-screen="terminal"] { gap: 0 } must not reach them
    assert '[data-screen="terminal"] { gap: 0; }' in _read("screens/terminal.css")
    assert ".rail .rail-a { gap: 10px; }" in css
    # every visible screen has its own pixel icon
    routes = _read("core/routes.js")
    sicon = routes[routes.index("const SICON = {"):routes.index("export const screenIcon")]
    for g in re.findall(r'screens: \[([^\]]+)\]', routes):
        for n in re.findall(r'"(\w+)"', g):
            assert re.search(rf"\n  {n}: ", sicon), n


def test_phone_keeps_its_bottom_bar_and_gets_the_same_buttons_in_one_sideways_row():
    shell = _read("core/shell.js")
    assert 'put($("#botbar"), GROUPS.map((g) => link(g)));' in shell                      # the 5 groups as before
    base = _nocomment(_read("base.css"))
    assert "@media (min-width: 900px) { .botbar { display: none; } body { padding-bottom: 0; } }" in base
    sub = next(x for x in base.splitlines() if x.startswith(".subtabs {"))
    assert "overflow-x: auto;" in sub and "flex-wrap" not in sub                         # one row that scrolls sideways
    t = _read("core/strip.js")
    assert 'const scrolls = (nav) => getComputedStyle(nav).flexWrap === "nowrap";' in t
    assert "if (moved) center(nav, !first);" in t                                        # a new screen: its button in view
    # the swipe on the screen leaves the strip alone (it scrolls sideways itself)
    k = _read("core/navkeys.js")
    assert "e.scrollWidth > e.clientWidth + 2" in k


def test_start_screen_is_the_terminal_and_home_stays_reachable():
    """Owners 10/06 13:27: "대시보드 들어가면 요약화면이 나오는게 아니라 사진속 차트화면부터"."""
    routes = _read("core/routes.js")
    # a PC window (900 px, where the phone's bottom bar goes and the terminal fits without sideways scrolling); the
    # terminal itself exists from 760 px, so the start screen is never a switched-off one
    assert "export const LANDING_MIN_PX = 900;" in routes and 'return wide ? "terminal" : "chart";' in routes
    assert 'export const DEFAULT = "home";' in routes                                     # unknown names: 홈, never a loop
    assert 'matchMedia("(min-width: 760px)")' in _read("core/features.js")               # the terminal's own width
    assert "@media (min-width: 900px) { .botbar { display: none; }" in _read("base.css")  # the phone bar's width
    # a PC screen opened on a phone goes to the start screen there (the 차트), named in the toast
    router = _read("core/router.js")
    assert 'const to = meta.feature === "wide" ? landing() : DEFAULT;' in router and "location.replace(href(to));" in router
    # an address without a screen name follows the window across the start width (menu and screen never disagree)
    assert "cur.name !== landing()" in router and "matchMedia(`(min-width: ${LANDING_MIN_PX}px)`)" in router
    assert "|| startMoved()) go();" in router and 'mq.addEventListener("change", () => { if (startMoved()) go(); });' in router
    # a 하이라이트 opened from the '지난번 본 뒤로' sheet (or a link) closes to the start screen, not to 홈
    story = _read("screens/story.js")
    assert "else ctx.go(landing());" in story and 'ctx.go("home")' not in story
    assert 'export {href, SCREENS, GROUPS, landing} from "./routes.js";' in _read("core/pb.js")
    # the brand mark opens the start screen and says so; 홈 (요약) stays a button, a number key (6 since 여러 차트), #/home
    html = _read("index.html")
    assert '<a class="brand" href="#/" aria-label="Paper v4 첫 화면">' in html and 'href="#/home"' not in html
    shell = _read("core/shell.js")
    assert 'brand.setAttribute("href", href(to));' in shell and "Paper v4 첫 화면 (${SCREENS[to].ko})" in shell
    # the first-visit tour comes back to the start screen, never to 홈 by default
    tour = _read("core/tour.js")
    assert ': href(landing());' in tour and 'location.hash || href("home")' not in tour
    out = _node("""
    const at = (w) => { globalThis.matchMedia = (q) => ({matches: Number((q.match(/min-width: (\\d+)px/) || [0, 0])[1]) <= w}); };
    const o = {};
    for (const w of [390, 759, 760, 899, 900, 1100, 1920]) { at(w); o[w] = [routes.parseHash("").name, routes.parseHash("#/").name, routes.landing()]; }
    at(1920); o.home = routes.parseHash("#/home").name; o.keys = routes.KEYS.indexOf("home") + 1;
    console.log(JSON.stringify(o));""")
    for w, want in (("390", "chart"), ("759", "chart"), ("760", "chart"), ("899", "chart"), ("900", "terminal"), ("1100", "terminal"),
                    ("1920", "terminal")):
        assert out[w] == [want, want, want], (w, out[w])
    assert out["home"] == "home" and out["keys"] == 6


def test_tour_starts_with_the_strip():
    tour = _read("core/tour.js")
    steps = re.findall(r'\{go: "(\w+)", sel: \[(.*?)\], t: "([^"]+)"', tour)
    assert steps[0] == ("home", '"#subtabs, #rail"', "화면 버튼")                        # the strip, or the rail when chosen
    assert "글자 버튼" in tour and "숫자 1-9는 앞의 아홉 버튼" in tour and "옆으로 밀어서" in tour
    assert '"#toptools .oldui, .subtabs .oldui, .rail-old"' in tour                     # 예전 화면 wherever it sits
    assert "#groups" not in tour and ".gbtn" not in tour
    # one entry may list several selectors (the first shown wins): the tour reads them with querySelectorAll
    assert "for (const el of document.querySelectorAll(sel)) if (visible(el)) return el;" in tour



# ---------------------------------------------------------------- the side panel
def test_links_and_ctx_go_open_the_side_panel():
    routes = _read("core/routes.js")
    assert 'export const PEEKABLE = {account: "account", strategies: "strategy", replay: "trade"};' in routes
    router = _read("core/router.js")
    assert 'import {peekGo} from "./drawer.js";' in router
    assert "go: (n, a, q) => { if (!peekGo(n, a, q)) location.hash = href(n, a, q); }," in router
    assert "export function makeCtx(" in router and "export function loadCss(" in router
    d = _read("core/drawer.js")
    assert 'document.addEventListener("click", (e) => {' in d and "}, true);" in d          # capture: before the row's own onclick
    assert "e.metaKey || e.ctrlKey || e.shiftKey || e.altKey" in d                          # a new tab stays a new tab
    assert 'if (!fromPanel && curName() === name && !(name === "strategies" && !parseHash(location.hash).arg)) return null;' in d
    main = _read("core/main.js")
    assert main.index("startDrawer();") < main.index("startRouter();")


def test_side_panel_closes_with_esc_outside_click_and_back_and_is_a_dialog():
    d = _read("core/drawer.js")
    assert 'role: "dialog", "aria-modal": "true", "aria-labelledby": "peek-t"' in d
    assert 'e.key === "Escape" && st.open' in d
    assert 'class: "peek-scrim"' in d and "onclick: () => closePeek()" in d
    assert "history.pushState({...(history.state || {}), peek: spec}" in d                # one entry: back closes it
    assert 'window.addEventListener("popstate"' in d and "history.back();" in d
    assert 'e.key !== "Tab"' in d                                                          # focus stays in the panel
    assert "back.focus(" in d                                                              # and returns to the link
    assert '"전체 화면으로"' in d and 'dataset: {full: "1"}' in d
    css = _nocomment(_read("core/nav.css"))
    assert "width: min(540px, 100vw)" in css and "@media (max-width: 599px)" in css and ".peek { width: 100vw;" in css
    assert "html.peek-open { overflow: hidden; }" in css
    assert "@media (prefers-reduced-motion: reduce) { .peek, .peek-scrim { transition: none; } }" in css


def test_side_panel_reuses_the_pages_pieces():
    p = _read("screens/account-peek.js")
    assert 'import {h, ui, fmt, derive, store, makeChart, candleOptions, tok, priceDec} from "../core/pb.js";' in p
    for piece in ('from "./positions-kit.js"', 'from "./account-pick.js"', 'from "./grid-kit.js"', 'from "./strategies-calc.js"'):
        assert piece in p
    assert "posCard(a, pos," in p and "tradeRow(t, a," in p and "chartWindow(" in p and "markLabels(" in p and "profileCard(ctx" in p
    assert "/api/account/${" in p and "/api/v4/replay/${" in p and "/api/candles?symbol=" in p
    assert "export async function renderPeek(spec, ctx, panel)" in p
    d = _read("core/drawer.js")
    assert 'import("../screens/account-peek.js")' in d and 'loadCss("account")' in d


def test_side_panel_counts_deepseek_and_coin_flips_only_outside_their_group():
    """CONTRACT §1: no DeepSeek / coin-flip money in a mixed view; the view is the screen's ?g= filter."""
    p = _read("screens/account-peek.js")
    assert p.count("derive.countOnlyIn(a, spec.view)") >= 2
    assert "const isCo = (a) => derive.countOnlyIn(a, spec.view);" in p
    assert "countOnly: o.co" in p and "countOnly: o.co || (o.isCo && o.isCo(a))" in p
    # count-only: neutral exit dots, no ROE on them, no profile card (it would show the return)
    assert 'color: co ? tok("--muted")' in p
    acc = p[p.index("async function accountPeek"):p.index("async function strategyPeek")]
    assert acc.index("if (co) {") < acc.index("profileCard(ctx")
    trade = p[p.index("async function tradePeek"):]
    assert "const hero = co" in trade and 'co ? null : ["증거금"' in trade
    d = _read("core/drawer.js")
    assert 'const viewNow = () => { const g = parseHash(location.hash).query.g; return g || "all"; };' in d
    f = _read("core/find.js")
    assert 'view: "all"' in f                                                               # 찾기 is a mixed list
    assert "ui.assume(" in p                                                                # money carries the caption


# ---------------------------------------------------------------- 찾기, number keys, swipe
def test_number_keys_and_slash():
    """1-9 = the strip's first nine buttons (owners 10/06 ~14:00), shown in each button's tooltip."""
    out = _node("console.log(JSON.stringify(routes.KEYS));")
    assert out == ["terminal", "positions", "chart", "charts", "market", "home", "board", "flow", "checkpoint"]
    assert "export const KEYS = navGroups(true).flatMap((g) => g.items.map((it) => it.to)).slice(0, 9);" in _read("core/routes.js")
    k = _read("core/navkeys.js")
    assert "e.ctrlKey || e.metaKey || e.altKey || e.isComposing || typing(e.target) || findOpen()" in k
    assert 'if (e.key === "/") { e.preventDefault(); openFind(); return; }' in k
    assert "KEYS[Number(k) - 1]" in k
    assert "closePeek(() =>" in k                                                           # an open panel goes first


def test_find_matches_korean_codes_and_first_consonants():
    out = _node("""
    const items = [{label: "순위표", code: "board", words: "랭킹 ranking"}, {label: "포지션", code: "positions", words: ""},
      {label: "돈치안·MFI · 1시간", code: "S5_DONCHIAN_MFI@1h", words: "기존 36"}, {label: "V1.2_TREND · 15분", code: "V1.2_TREND@15m", words: ""}];
    const names = (q, n = 5) => search.rank(search.norm(q), items, n).map((x) => x.code);
    console.log(JSON.stringify({cho: search.chosung("순위표"), a: names("ㅅㅇㅍ"), b: names("랭킹"), c: names("donchian"), d: names("v1.2"),
      e: names("돈치"), f: names("없는것"), g: names("ㅍㅈ")}));
    """)
    assert out["cho"] == "ㅅㅇㅍ"
    assert out["a"] == ["board"] and out["b"] == ["board"] and out["c"] == ["S5_DONCHIAN_MFI@1h"]
    assert out["d"] == ["V1.2_TREND@15m"] and out["e"] == ["S5_DONCHIAN_MFI@1h"] and out["f"] == [] and out["g"] == ["positions"]
    f = _read("core/find.js")
    assert 'role: "combobox"' in f and 'role: "listbox"' in f and "aria-activedescendant" in f
    assert "openPeek({kind: x.kind" in f                                                    # accounts / strategies: the panel
    assert "rank(q, scr, 5), ...rank(q, strats, 6), ...rank(q, accts, 8)" in f              # a short list, never 335 rows


def test_phone_swipe_moves_inside_the_group_and_leaves_charts_and_tables_alone():
    k = _read("core/navkeys.js")
    assert '"touchstart"' in k and '"touchend"' in k and "{passive: true}" in k
    assert "Math.abs(dx) < 70 || Math.abs(dx) < 2 * Math.abs(dy)" in k
    assert 'e.tagName === "CANVAS"' in k and "e.scrollWidth > e.clientWidth + 2" in k and "[data-noswipe]" in k
    assert "export function neighbour(cur, dir)" in k and "list[i + dir] || null" in k
    # the phone's 찾기 sits first in the menu strip (2 taps to any account)
    shell = _read("core/shell.js")
    assert "lead: [findTab(), textCycle(() => remount())]," in shell
    css = _nocomment(_read("core/nav.css"))
    assert "@media (max-width: 459px) { .findbtn { display: none; } .findsub { display: inline-flex; } }" in css


def test_new_nav_files_follow_the_text_rules():
    for rel in ("core/rail.js", "core/strip.js", "core/navpos.js", "core/drawer.js", "core/find.js", "core/navkeys.js", "core/search.js",
                "screens/account-peek.js"):
        src = _read(rel)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "localStorage"):
            assert bad not in src, (rel, bad)
    css = _nocomment(_read("core/nav.css"))
    for m in re.finditer(r"font(?:-size)?\s*:\s*([^;}]+)", css):
        v = m.group(1)
        assert "var(--t-" in v or v.strip() in ("inherit",), v
