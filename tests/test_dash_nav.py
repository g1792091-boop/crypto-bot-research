"""Dashboard v4, fewer clicks (owners 10/06: "들어가는 클릭버튼이 너무 많아서 들어가서 보는게 귀찮다"), with the menu
where the owners want it (10/06 13:27: "클릭하는 버튼들이 다 왼쪽으로 바꼈네??", "들어가면 요약화면이 아니라 차트화면부터"):
the top bar by default with a dropdown of every screen per group, the left rail as a stored choice (메뉴 위치), the
terminal as the start screen, the side panel for accounts / strategies / trades, 찾기 ('/'), the number keys 1-9 and the
phone's sideways swipe. Static checks on the v4 files, plus the pure parts in node (search, routes, the stored choice)."""
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


# ---------------------------------------------------------------- the menu: top bar by default, the left rail by choice
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


def test_index_has_the_top_menu_the_rail_the_crumb_and_the_find_button():
    html = _read("index.html")
    # the group bar + sub tabs are the menu (the default); the rail is there for the 왼쪽 choice; the phone bar stays
    for x in ('<nav class="groups" id="groups" aria-label="메뉴"></nav>', 'id="subtabs"', 'id="botbar"',
              '<nav class="rail" id="rail" aria-label="모든 화면"></nav>'):
        assert x in html, x
    assert 'id="crumb"' in html and 'id="findbtn"' in html and "단축키 /" in html
    assert '<link rel="stylesheet" href="/static/v4/core/nav.css">' in html


def test_top_menu_is_the_default_and_the_rail_only_a_choice():
    """Owners 10/06 13:27: "클릭하는 버튼들이 다 왼쪽으로 바꼈네??" - the top bar is back on a PC by default."""
    css = _nocomment(_read("core/nav.css"))
    assert re.search(r"^\.rail \{ display: none; \}", css, re.M)                        # no rail unless chosen
    block = css[css.index("@media (min-width: 1200px)"):]
    block = block[:block.index("\n}\n") + 3]
    # every rule that hides the top menu or shows the rail is under [data-nav="left"]
    for rule in ('--sub-h: 0px', "padding-left: var(--rail-w)", ".groups { display: none !important; }", ".subtabs { display: none; }",
                 ".crumb { display: flex; }", ".rail { position: fixed;"):
        line = next(x for x in block.splitlines() if rule in x)
        assert ':root[data-nav="left"]' in line, line
    assert ".subtabs .navsw { display: inline-flex; }" in block                         # the switch from 1200 px
    assert re.search(r"^\.navsw \{ display: none; \}", css, re.M)                       # and only there
    # nothing outside [data-nav="left"] hides the group bar or the sub tabs any more
    assert css.count(".groups { display: none !important; }") == 1 and css.count(".subtabs { display: none; }") == 1
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
    assert out["def"] == "top" and out["applied"] == "top"                      # nothing stored: the top bar
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


def test_menu_position_switch_is_where_the_owners_look_and_redraws():
    shell = _read("core/shell.js")
    subtabs = shell[shell.index('put($("#subtabs")'):shell.index("/** 찾기 at the start")]
    assert "navPosSwitch());" in subtabs                                                # the end of the sub tabs row
    assert subtabs.index("textSwitch(") < subtabs.index("navPosSwitch()")
    rail = _read("core/rail.js")
    assert 'h("div", {class: "rail-foot"}, navPosSwitch(),' in rail                     # and the rail's foot
    navpos = shell[shell.index('bus.on("navpos", (id) => {'):]
    assert navpos.index("renderNav(); remount();") < navpos.index("});")                 # any caller: menu + screen redrawn
    assert '.navsw button[data-nav="${id}"]' in navpos                                   # the keyboard focus follows the switch
    inv = _read("INVENTORY.md")
    assert "setNavPos(" in inv and "currentNavPos()" in inv and "메뉴 위치" in inv            # the settings panel's hook


def test_group_dropdowns_list_every_screen_with_icon_name_and_key():
    t = _read("core/topnav.js")
    assert "export function renderGroups(cur, badges)" in t
    assert 'h("button", {type: "button", class: "gbtn"' in t
    assert '"aria-expanded": "false", "aria-controls": `gm-${g.id}`' in t                # a disclosure: button + its list
    assert "menuScreens(g, features)" in t                                              # every screen of the group
    assert "screenIcon(n)" in t and 'h("span", {class: "gm-t"}, m.ko)' in t and 'h("kbd"' in t and "keyOf(n)" in t
    assert '"aria-current": n === cur ? "page" : null' in t and '"aria-current": g.id === gid ? "true" : null' in t
    assert "badges[n]" in t and '"꺼짐"' in t
    # mouse hover (mouse only), click / tap toggles, keyboard, Esc, outside press, a chosen screen closes it
    assert 'e.pointerType !== "mouse"' in t and '"pointerenter"' in t and '"pointerleave"' in t
    assert "if (st.open === g.id && st.pinned) closeGroupMenu();" in t and "else openGroupMenu(g.id, true);" in t
    for k in ('"ArrowDown"', '"ArrowUp"', '"Home"', '"End"', '"ArrowRight"', '"ArrowLeft"', '"Escape"'):
        assert k in t, k
    assert 'document.addEventListener("pointerdown"' in t and "w.contains(e.target)" in t
    assert '"focusout"' in t and 'e.target.closest(".gm-a")' in t
    assert "st.cur === cur && (st.pinned || st.hover === st.open) ? st.open : null" in t    # a new screen closes it
    shell = _read("core/shell.js")
    assert "renderGroups(p.name, badges);" in shell and 'put($("#groups")' not in shell
    css = _nocomment(_read("core/nav.css"))
    assert ".gmenu { position: absolute;" in css and '.gm-a[aria-current="page"]' in css
    assert "@media (prefers-reduced-motion: reduce) { .gw[data-open] .gmenu { animation: none; }" in css
    base = _nocomment(_read("base.css"))
    assert '.groups .gbtn[aria-current="true"] { color: var(--accent-ink); background: var(--accent); }' in base
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\brgba?\(\s*\d", css)   # tokens only


def test_menu_screens_and_keys_in_node():
    out = _node("""
    const g = (id) => routes.GROUPS.find((x) => x.id === id);
    console.log(JSON.stringify({
      tradePc: routes.menuScreens(g("trade"), {wide: true}), tradePhone: routes.menuScreens(g("trade"), {wide: false}),
      home: routes.menuScreens(g("home"), {}), agents: routes.menuScreens(g("agents"), {debate: false}),
      keys: ["terminal", "home", "server", "flow", "debate"].map(routes.keyOf)}));""")
    assert out["tradePc"] == ["terminal", "positions", "chart", "market"]
    assert out["tradePhone"] == ["positions", "chart", "market"]                         # the PC 터미널 is off a phone's menu
    assert out["home"] == ["home", "board", "flow", "checkpoint"]                        # hidden screens (계좌, 하이라이트) out
    assert out["agents"] == ["office", "rooms", "digest", "debate"]                      # 토론방 stays (greyed 꺼짐)
    assert out["keys"] == ["1", "2", "9", None, None]


def test_left_rail_reads_by_itself():
    rail = _read("core/rail.js")
    assert "export function renderRail(cur, badges, onRedraw)" in rail
    assert "GROUPS.map(" in rail and "visibleScreens(g)" in rail                         # every group, every menu screen
    assert '"aria-current": n === cur ? "page" : null' in rail                           # the current one lit
    assert 'h("span", {class: "rail-t", "aria-hidden": "true"}, m.ko)' in rail            # the Korean name beside the icon
    assert 'h("p", {class: "rail-h", id: `rh-${g.id}`}, g.ko)' in rail and '"aria-labelledby": `rh-${g.id}`' in rail   # headings
    assert "badges[n]" in rail and '"ndot"' in rail and "keyOf(n)" in rail
    assert "textCycle(onRedraw)" in rail and "skinCycle(onRedraw)" in rail and 'href: "/v3"' in rail
    assert 'role: "tooltip"' not in rail                                                 # no hover-only labels any more
    shell = _read("core/shell.js")
    assert "renderRail(p.name, badges, () => remount())" in shell
    css = _nocomment(_read("core/nav.css"))
    assert ":root[data-nav=\"left\"] { --rail-w: calc(184px * var(--ts)); --sub-h: 0px; }" in css   # grows with 글자 크기
    assert '.rail-a[aria-current="page"] { color: var(--ink); background: var(--accent-soft);' in css
    assert ".rail-t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }" in css
    # every visible screen has its own pixel icon
    routes = _read("core/routes.js")
    sicon = routes[routes.index("const SICON = {"):routes.index("export const screenIcon")]
    for g in re.findall(r'screens: \[([^\]]+)\]', routes):
        for n in re.findall(r'"(\w+)"', g):
            assert re.search(rf"\n  {n}: ", sicon), n


def test_start_screen_is_the_terminal_and_home_stays_reachable():
    """Owners 10/06 13:27: "대시보드 들어가면 요약화면이 나오는게 아니라 사진속 차트화면부터"."""
    routes = _read("core/routes.js")
    assert "export const LANDING_MIN_PX = 760;" in routes and 'return wide ? "terminal" : "chart";' in routes
    assert 'export const DEFAULT = "home";' in routes                                     # unknown names: 홈, never a loop
    assert 'matchMedia("(min-width: 760px)")' in _read("core/features.js")               # the terminal's own width
    # a PC screen opened on a phone goes to the start screen there (the 차트), named in the toast
    router = _read("core/router.js")
    assert 'const to = meta.feature === "wide" ? landing() : DEFAULT;' in router and "location.replace(href(to));" in router
    # the brand mark opens the start screen and says so; 홈 stays in its group, the number key 2, #/home
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
    for (const w of [390, 759, 760, 1100, 1920]) { at(w); o[w] = [routes.parseHash("").name, routes.parseHash("#/").name, routes.landing()]; }
    at(1920); o.home = routes.parseHash("#/home").name; o.keys = routes.KEYS.indexOf("home") + 1;
    console.log(JSON.stringify(o));""")
    for w, want in (("390", "chart"), ("759", "chart"), ("760", "terminal"), ("1100", "terminal"), ("1920", "terminal")):
        assert out[w] == [want, want, want], (w, out[w])
    assert out["home"] == "home" and out["keys"] == 2


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
    out = _node("console.log(JSON.stringify(routes.KEYS));")
    assert out == ["terminal", "home", "positions", "strategies", "board", "office", "chart", "market", "server"]
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
    # the phone's 찾기 sits in the sub-tab row (2 taps to any account)
    shell = _read("core/shell.js")
    assert "textCycle(() => remount()), findTab()," in shell
    css = _nocomment(_read("core/nav.css"))
    assert "@media (max-width: 459px) { .findbtn { display: none; } .findsub { display: inline-flex; } }" in css


def test_new_nav_files_follow_the_text_rules():
    for rel in ("core/rail.js", "core/topnav.js", "core/navpos.js", "core/drawer.js", "core/find.js", "core/navkeys.js", "core/search.js",
                "screens/account-peek.js"):
        src = _read(rel)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "localStorage"):
            assert bad not in src, (rel, bad)
    css = _nocomment(_read("core/nav.css"))
    for m in re.finditer(r"font(?:-size)?\s*:\s*([^;}]+)", css):
        v = m.group(1)
        assert "var(--t-" in v or v.strip() in ("inherit",), v
