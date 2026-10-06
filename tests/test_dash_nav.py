"""Dashboard v4, fewer clicks (owners 10/06: "들어가는 클릭버튼이 너무 많아서 들어가서 보는게 귀찮다"):
the PC left rail of every screen, the side panel for accounts / strategies / trades, 찾기 ('/'), the number keys 1-9
and the phone's sideways swipe. Static checks on the v4 files, plus the pure search in node."""
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


# ---------------------------------------------------------------- the rail (PC, >= 1200 px)
def test_index_has_the_rail_the_crumb_and_the_find_button():
    html = _read("index.html")
    assert '<nav class="rail" id="rail" aria-label="모든 화면"></nav>' in html
    assert 'id="crumb"' in html and 'id="findbtn"' in html and "단축키 /" in html
    assert '<link rel="stylesheet" href="/static/v4/core/nav.css">' in html
    # the old group bar, the sub tabs and the phone bar stay (below 1200 px they are the menu)
    for x in ('id="groups"', 'id="subtabs"', 'id="botbar"'):
        assert x in html


def test_rail_lists_every_screen_with_an_icon_label_and_the_current_one_lit():
    rail = _read("core/rail.js")
    assert "export function renderRail(cur, badges, onRedraw)" in rail
    assert "GROUPS.map(" in rail and "visibleScreens(g)" in rail             # every group, every menu screen
    assert '"aria-current": n === cur ? "page" : null' in rail               # the current one
    assert '"aria-label": `${m.ko}' in rail and 'role: "tooltip"' in rail and "aria-describedby" in rail
    assert "onfocus:" in rail and "onmouseenter:" in rail                    # the label on hover and keyboard focus
    assert 'class: "rail-sep"' in rail                                      # thin lines between the groups
    assert "badges[n]" in rail and '"ndot"' in rail                         # the news dots stay
    assert "textCycle(onRedraw)" in rail and "skinCycle(onRedraw)" in rail and 'href: "/v3"' in rail
    shell = _read("core/shell.js")
    assert "renderRail(p.name, badges, () => remount())" in shell
    # every visible screen has its own pixel icon
    routes = _read("core/routes.js")
    sicon = routes[routes.index("const SICON = {"):routes.index("export const screenIcon")]
    for g in re.findall(r'screens: \[([^\]]+)\]', routes):
        for n in re.findall(r'"(\w+)"', g):
            assert re.search(rf"\n  {n}: ", sicon), n


def test_rail_css_shows_at_1200_and_hides_the_sub_tabs_there():
    css = _nocomment(_read("core/nav.css"))
    block = css[css.index("@media (min-width: 1200px)"):]
    block = block[:block.index("\n}\n") + 3]
    assert "--sub-h: 0px" in block and "padding-left: var(--rail-w)" in block
    assert ".subtabs { display: none; }" in block and ".groups { display: none !important; }" in block
    assert ".rail { position: fixed;" in block
    assert re.search(r"^\.rail \{ display: none; \}", css, re.M)            # phones and narrow windows: no rail
    assert '.rail-a[aria-current="page"] { color: var(--accent);' in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\brgba?\(\s*\d", css)   # tokens only


def test_landing_stays_terminal_on_a_pc_and_home_on_a_phone():
    routes = _read("core/routes.js")
    assert "export const LANDING_MIN_PX = 1200;" in routes
    assert 'return wide ? "terminal" : DEFAULT;' in routes and 'export const DEFAULT = "home";' in routes


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
    assert 'if (!fromPanel && curName() === name) return null;' in d                         # the account page's own links
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
    for rel in ("core/rail.js", "core/drawer.js", "core/find.js", "core/navkeys.js", "core/search.js", "screens/account-peek.js"):
        src = _read(rel)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "localStorage"):
            assert bad not in src, (rel, bad)
    css = _nocomment(_read("core/nav.css"))
    for m in re.finditer(r"font(?:-size)?\s*:\s*([^;}]+)", css):
        v = m.group(1)
        assert "var(--t-" in v or v.strip() in ("inherit",), v
