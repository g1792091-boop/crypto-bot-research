"""터미널 정리 (term-declutter, owners 10/06 ~14:00, from their 1920x1080 screenshot): the four agreed fixes.

1. the chart's right-edge names are collision-free (core/edgelabels.js, node): lines at almost the same price share one
   name ("손절 ×2"), at most 6 names (the nearest to the price first), the others on hover / tap of their line and in a
   "+N" chip, names closer than one label height nudged apart inside the pane; the lines stay 1 px;
2. the repeated small print is said once: one footer line for the terminal (ui.assumeLine), an ⓘ (ui.infoTip) in each
   panel head with that panel's exact note, a tiny "시장" chip on the market panels; the positions and account screens
   print their shared caption once;
3. 이 코인 포지션 shows the full Korean strategy name (two lines when needed, the timeframe chip kept), 청산가 moved into
   the row's tooltip;
4. a calm default chart ("기본"): the light, the equilibrium line, the nearest OB and FVG above and below the price, our
   position lines (with their stops); every other 프리미엄 지표 part and 지지·저항 opt-in, remembered per device; the
   terminal's chart header keeps all seven timeframe buttons (one '보기 ▾' menu, the head wraps instead of cutting).
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
    """JS without // and /* */ comments (strings kept)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|[^:\"'`])//.*$", r"\1", ln) for ln in src.splitlines())


def _node(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    scr = "file://" + os.path.join(V4, "screens")
    script = (f"const E = await import('{core}/edgelabels.js'); const S = await import('{core}/smc.js');\n"
              f"const L = await import('{scr}/chart-lines.js');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- 1. the right-edge names (node)
LINES = """
const it = (id, price, y, text, tone = "down", n) => ({id, price, y, text, tone, n});
// the owners' screenshot, BTC around 85,600: stops, OB / FVG zones, resistance / support, all near the price
const items = [
  it("s1", 86460, 120, "손절"), it("s2", 86462, 120.2, "손절"),                // two stops at almost one price
  it("ob1", 86280, 138, "OB−", "ob"), it("f1", 86160, 150, "FVG", "fvg"), it("f2", 86050, 161, "FVG", "fvg"),
  it("r1", 85980, 168, "저항"), it("p1", 85860, 180, "지지", "up"), it("s3", 85700, 196, "손절"),
  it("ob2", 85600, 206, "OB−", "ob"), it("s4", 85150, 251, "손절"), it("far", 87900, 10, "저항"), it("far2", 84100, 330, "지지", "up")];
"""


def test_names_merge_near_equal_lines_and_keep_the_nearest_six():
    out = _node(LINES + """
      const lay = E.edgeLayout(items, {price: 85588, max: 6, H: 17, lo: 2, hi: 340});
      const merged = E.mergeNames(items).map((g) => ({t: g.text, ids: g.ids}));
      const n2 = E.groupText([it("a", 1, 1, "손절", "down", 2), it("b", 1, 1, "손절"), it("c", 1, 1, "지지", "up")]);
      const chain = E.mergeNames([0, 3, 6, 9, 12].map((y, i) => it("c" + i, 100 - i, y, "손절")), {near: 0, nearPx: 4});
      console.log(JSON.stringify({shown: lay.shown.map((g) => ({t: g.text, y: g.y, ly: g.ly, price: g.price, ids: g.ids})),
        hidden: lay.hidden.map((g) => g.ids.join("+")), merged, n2, chain: chain.map((g) => g.text)}));""")
    # two stops at almost one price: one name for both
    assert {"t": "손절 ×2", "ids": ["s1", "s2"]} in out["merged"] and len(out["merged"]) == 11
    shown = out["shown"]
    assert len(shown) == 6                                                 # at most six names
    # the nearest to the price win the places (12, 112, 272, 392, 438, 462 away); the rest wait for a hover / tap
    assert sorted(i for g in shown for i in g["ids"]) == sorted(["ob2", "s3", "p1", "r1", "s4", "f2"])
    assert sorted(out["hidden"]) == sorted(["s1+s2", "ob1", "f1", "far", "far2"])
    assert out["n2"] == "손절 ×3 · 지지"                                  # a line that already stands for two stops
    # a long run of close lines does not chain into one huge name (measured from the group's first line)
    assert out["chain"] == ["손절 ×2", "손절 ×2", "손절"]


def test_names_never_overlap_and_stay_inside_the_pane():
    out = _node(LINES + """
      const H = 17, lay = E.edgeLayout(items, {price: 85588, max: 6, H, lo: 2, hi: 340});
      const tight = E.dodge([5, 6, 7, 8, 9, 10], 17, 0, 60);                       // more names than the pane holds
      const edge = E.dodge([1, 2, 338, 339], 17, 2, 340);
      console.log(JSON.stringify({ly: lay.shown.map((g) => g.ly), y: lay.shown.map((g) => g.y), tight, edge}));""")
    ly = out["ly"]
    assert ly == sorted(ly)                                               # the order of the lines is kept
    assert all(b - a >= 17 - 1e-6 for a, b in zip(ly, ly[1:]))            # never closer than one label height
    assert all(2 + 17 / 2 - 1e-6 <= v <= 340 - 17 / 2 + 1e-6 for v in ly)  # inside the pane
    assert all(abs(a - b) < 40 for a, b in zip(ly, out["y"]))             # each next to its own line
    t = out["tight"]
    assert t == sorted(t) and all(b - a >= 10 - 1e-6 for a, b in zip(t, t[1:])) and t[0] >= 0 and t[-1] <= 60
    e = out["edge"]
    assert e[0] >= 2 + 17 / 2 - 1e-6 and e[-1] <= 340 - 17 / 2 + 1e-6 and all(b - a >= 17 - 1e-6 for a, b in zip(e, e[1:]))


def test_merged_stops_carry_their_count_and_lines_stay_one_px():
    out = _node("""
      const pos = (side, entry, stop) => ({symbol: "BTCUSDT", side, qty: 1, entry, leverage: 30, margin: entry / 30, stop, lock_roe: null});
      const a = (id, p) => ({account_id: id, kind: "strategy", timeframe: "15m", strategy: "S" + id, position: p});
      const out = L.posLines([a("A@15m", pos(-1, 100, 102)), a("B@15m", pos(-1, 100.5, 102.02)), a("C@15m", pos(1, 99, 97))], 100.2, {stops: 6});
      console.log(JSON.stringify(out.filter((x) => x.group === "risk").map((x) => [x.label, x.count, x.price])));""")
    assert sorted(out) == sorted([["손절", 2, 102], ["손절", 1, 97]])
    fx = _code(_read("core", "chartfx.js"))
    assert "n: L.spec.count || 1" in fx                                   # the name reads "손절 ×2"
    assert "c.lineWidth = lw;" in fx and "Math.max(1, Math.round(vr))" in fx     # lines unchanged: 1 px


def test_the_deck_places_every_right_edge_name_in_one_column():
    fx, draw = _code(_read("core", "chartfx.js")), _code(_read("core", "smcdraw.js"))
    # smcdraw no longer writes names at the right edge (zones or our lines): the deck does, through edgelabels.js
    assert 'align: "right"' not in draw and "o.extra" not in draw
    assert 'import {edgeLayout} from "./edgelabels.js";' in fx and "export const NAMES_MAX = 6;" in fx
    assert "edgeLayout(items, {price: last ? last.close : null, max: fitN, H: H + 1, lo, hi: top})" in fx
    assert "const fitN = Math.max(0, Math.min(NAMES_MAX, Math.floor((top - lo) / (H + 1))));" in fx   # never squeezed
    assert "let lo = 2, hi = pane.h - 2;" in fx and "let lay = run(hi);" in fx
    assert "layoutNames();" in fx[fx.index("function place()"):fx.index("function layoutPills()")]
    # the hidden ones: on hover / tap of the line (and the equilibrium / liquidity lines), and a "+N" chip with a list
    assert "chart.subscribeCrosshairMove((p) => showHover(" in fx and "chart.subscribeClick((p) => showHover(" in fx
    assert "const t = `이름 +${n}`;" in fx and '"aria-label": "가려진 선 이름"' in fx
    assert 'text: "중간선 (Equilibrium)"' in fx
    css = _read("core", "chartfx.css")
    assert re.search(r"\.cfx-name \{[^}]*right: 4px;[^}]*font: 600 var\(--t-2xs\)/1\.25", css, re.S)
    assert ".cfx-lead[data-dir=\"up\"]" in css and ".cfx-lead[data-dir=\"down\"]" in css



def test_names_keep_clear_of_the_left_pills_and_name_only_drawn_zones():
    """Review (10/06): in a narrow pane (the left menu with bigger type) a right-edge name sat on a left pill; a zone
    scrolled out to the right of the pane still had a name."""
    fx = _code(_read("core", "chartfx.js"))
    lay = fx[fx.index("function layoutNames()"):fx.index("function paintNamesMore()")]
    assert "it.L._top = Math.round(Math.min(top, pane.h - PILL_H));" in fx              # layoutPills keeps each pill's top
    assert "pb.push({t: L._top, b: L._top + PILL_H, r: 6 + L.pill.offsetWidth})" in lay
    assert "left = pane.w - 4 - nameW(g.text)" in lay and "lay.hidden.push(g)" in lay     # it goes to "+N" and the hover tag
    assert lay.index("lay.hidden.push(g)") < lay.index("shownNames = lay.shown; hiddenNames = lay.hidden;")
    items = fx[fx.index("function nameItems()"):fx.index("function layoutNames()")]
    assert "if (x == null || x > pane.w) continue;" in items
    # the indicator key wraps before it runs under the "+N" chip
    assert 'over.classList.toggle("nmore", !!n);' in fx
    assert ".cfx-over.nmore .cfx-smckey { max-width: calc(100% - 44px - 7.5em); }" in _read("core", "chartfx.css")
    # the OHLC legend (top left): when it runs into the names' column, the names start under it (it kept "−0.16%" hidden)
    assert "lo = Math.max(lo, lg.offsetTop + lg.offsetHeight - pane.y + 2);" in lay and "max: fitN, H: H + 1, lo, hi:" in lay
    # our ▲ / ▼ markers and the "+N" chip hold the right corners: the names keep clear of them
    assert "if (edgeTop.childElementCount) lo = Math.max(lo, 4 + edgeTop.offsetHeight + 2);" in lay
    assert "if (edgeBot.childElementCount) hi = Math.min(hi, pane.h - 4 - Math.max(rowH, edgeBotRow.offsetHeight) - 2);" in lay
    assert "if (lay.shown.some((g) => g.ly + H / 2 > hi2)) lay = run(hi2);" in lay
    assert "sym: () => st.sym, legend});" in _read("screens", "terminal-chart.js")
    assert "sym: () => st.sym, legend});" in _read("screens", "chart.js")


def test_bottom_table_head_wraps_instead_of_cutting_its_totals():
    """Review (10/06): below 1600 px at 크게 / 아주 크게 the table head ran 100-280 px past its panel ("미실" cut, and the
    page scrolled sideways with the left menu); it wraps now, and the ⓘ follows the tabs whose note it carries."""
    css = _read("screens", "terminal.css")
    assert ".term-table .term-ph { flex-wrap: wrap; gap: 4px 10px; min-height: 36px; }" in css
    assert ".term-table .term-ph h2, .term-table .term-ph .term-phs:empty { display: none; }" in css
    assert "tabs.after(el.tip);" in _read("screens", "terminal-table.js")
    # slimmer timeframe buttons below 1600 px keep the chart head on one line at 1440 / 아주 크게
    block = css[css.index("@media (max-width: 1599px) {\n  .term-fx .cfx-light"):]
    block = block[:block.index("\n}\n")]
    assert ".term-chart .term-tfs button { padding-inline: 6px; }" in block


def test_header_menus_stay_inside_the_window():
    """Review (10/06): '보기 ▾' (two columns, opening to the right of its button) ran up to 200 px past the right edge at
    1200 / 아주 크게 and with the left menu at 1280 / 1200: the page scrolled sideways and half the menu was cut."""
    fx = _code(_read("core", "chartfx.js"))
    fit = fx[fx.index("function fit(box)"):fx.index("function dropdown(")]
    assert "if (r.right > vw - 8) dx = vw - 8 - r.right;" in fit and "if (r.left + dx < 8) dx = 8 - r.left;" in fit
    drop = fx[fx.index("function dropdown("):fx.index("const smcItems")]
    assert "paintMenu(); paintLight(); fit(box);" in drop


# ---------------------------------------------------------------- 4. the calm default
def test_nearest_zones_pick_one_above_and_one_below():
    out = _node("""
      const Z = (i, bot, top) => ({i, bot, top, dir: 1});
      const zs = [Z(1, 110, 112), Z(2, 104, 105), Z(3, 120, 121), Z(4, 90, 92), Z(5, 95, 97), Z(6, 99, 100.6)];
      const [up, dn] = S.nearestZones(zs, 100.5);          // 99-100.6 holds the price, its middle is below it
      const [u2, d2] = S.nearestZones([Z(1, 101, 102)], 100);
      console.log(JSON.stringify({up: up && up.i, dn: dn && dn.i, u2: u2 && u2.i, d2, none: S.nearestZones([], 1), nan: S.nearestZones(zs, NaN)}));""")
    assert out["up"] == 2 and out["dn"] == 6
    assert out["u2"] == 1 and out["d2"] is None and out["none"] == [None, None] and out["nan"] == [None, None]


def test_smc_keeps_every_live_zone_for_the_nearest_pick():
    smc = _read("core", "smc.js")
    assert "obsAll: last(obs, ZONES_KEPT), fvgsAll: last(fv, ZONES_KEPT)," in smc
    assert "obsAll: [], fvgsAll: []" in smc                               # fewer than 30 bars: empty like the rest


def test_calm_default_parts_and_opt_in_menus_remembered_per_device():
    fx = _code(_read("core", "chartfx.js"))
    parts = re.findall(r'\{id: "(\w+)", ko: "[^"]+"(?:, sub: "[^"]+")?, def: (true|false)\}', fx)
    assert dict(parts) == {"eq": "true", "near": "true", "zones": "false", "liq": "false", "struct": "false", "ote": "false",
                           "trend": "false", "legs": "false", "words": "false"}
    # what each part draws (smcView): BSL / SSL, BoS / CHoCH, OTE, trendlines, leg %, the words only when chosen
    view = fx[fx.index("function smcView()"):fx.index("const smcP = smcPrimitive(")]
    for k, field in (("liq", "liq"), ("struct", "structure"), ("trend", "trend"), ("legs", "legs")):
        assert f'{field}: P.has("{k}") ? r.{field} : []' in view, k
    assert 'eq: P.has("eq"), ote: P.has("ote"), words: P.has("words") && !st.ai' in view
    assert 'if (P.has("near")) { for (const z of nearestZones(r.obsAll, px)) add(z, "ob"); for (const z of nearestZones(r.fvgsAll, px)) add(z, "fvg"); }' in view
    assert "const smcP = smcPrimitive({chart, series, get: smcView, col: () => st.col});" in fx
    # per device (dom.js local, try/catch inside), versioned: a device saved before the calm default starts from it once
    assert "const save = () => local.set(key, {v: DECK_V, off: [...st.off], hide: [...st.hide].slice(-60), smc: [...st.parts]});" in fx
    assert "const fresh = saved.v !== DECK_V;" in fx and "localStorage" not in fx
    # clear on / off items, 기본으로, 모두 끄기; the AI light's words follow the part
    assert 'role: "menuitemcheckbox", "aria-checked": String(part(x.id)), onclick: () => setPart(x.id, !part(x.id))' in fx
    assert '"기본으로"' in fx and '"모두 끄기"' in fx and "function setDefault()" in fx
    assert 'under.dataset.words = part("words") ? "1" : "";' in fx
    # the terminal: 지지·저항 opt-in too; the light, the flash and the parts in one '보기 ▾' menu
    tc = _code(_read("screens", "terminal-chart.js"))
    assert 'defaults: {sr: false},' in tc and "put(fxSlot, deck.lightChip, deck.viewBtn, deck.menuBtn);" in tc
    assert 'LEVEL_TFS.includes(st.tf) && deck.shown("sr")' in tc            # the key line names only what is drawn
    assert '"보기 ▾"' in fx and "viewBtn," in fx


def test_terminal_chart_header_wraps_instead_of_cutting_a_timeframe_button():
    css = _read("screens", "terminal.css")
    assert ".term-chart .term-ph { flex-wrap: wrap; row-gap: 4px; }" in css
    assert ".term-chart .term-ph .term-tfs, .term-chart .term-ph .term-more { flex: none; }" in css
    assert re.search(r"@media \(max-width: 1599px\) \{\s*\.term-fx \.cfx-light \{ padding: 0 8px; \}\s*\.term-fx \.cfx-light > span \{ display: none; \}", css)
    fxcss = _read("core", "chartfx.css")
    assert ".cfx-vmenu { left: 0; right: auto;" in fxcss                  # opens to the right of its button
    assert ".cfx-smcmenu, .cfx-vmenu { position: fixed; left: 16px; right: 16px; width: auto;" in fxcss   # a phone: a sheet


# ---------------------------------------------------------------- 2. the small print, said once
TERM = ["terminal.js", "terminal-kit.js", "terminal-top.js", "terminal-feed.js", "terminal-live.js", "terminal-side.js",
        "terminal-table.js", "terminal-chart.js"]


def test_terminal_says_the_captions_once():
    for f in TERM:
        assert "ui.assume(" not in _code(_read("screens", f)), f        # no caption under every panel
    js = _read("screens", "terminal.js")
    assert 'const foot = ui.assumeLine(["closed", "open"], `\'시장\' 표시 = 바이낸스 ${MARKET_LABEL} · 딥시크·동전 봇은 건수만`);' in js
    assert "h(\"div\", {class: \"term-grid\"}, left, mid, right), foot);" in js
    ui_src = _read("core", "ui.js")
    allk = re.search(r'export const ASSUME_ALL_KO = "([^"]+)";', ui_src).group(1)
    for w in ("모의", "실제 시세", "수수료·펀딩·슬리피지 포함", "마크 가격 기준 미실현(나갈 때 수수료 전)", "주문 버튼 없음"):
        assert w in allk, w
    # every panel keeps its exact note in an ⓘ; the market panels a tiny "시장" chip
    kit = _read("screens", "terminal-kit.js")
    assert 'const tip = o.info ? ui.infoTip(o.info, `${title} 설명`) : null;' in kit and "export const marketChip" in kit
    side, feed, live, table = (_read("screens", f) for f in ("terminal-side.js", "terminal-feed.js", "terminal-live.js", "terminal-table.js"))
    assert side.count("info: `") == 2 and "중간 기록일 뿐 판정이 아닙니다" in side
    assert feed.count("info: `") == 2 and "marketChip(" in feed and "info: BIG_LABEL" in live and "marketChip(BIG_LABEL)" in live
    assert "info: TAB_NOTE.pos" in table and "el.tip.set(TAB_NOTE[t.tab] || TAB_NOTE.pos);" in table
    assert "(실제 주문 아님)" in table                                    # the stops tab still says it in sight
    assert "marketChip(" in _read("screens", "terminal-top.js") and "marketChip(" in js     # movers, 호가
    # nothing typed twice: the phrases come from core/ui.js
    for f in TERM:
        assert "수수료·펀딩·슬리피지 포함" not in _read("screens", f), f


def test_info_tip_is_a_button_with_a_tooltip_and_a_tap_bubble():
    ui_src = _code(_read("core", "ui.js"))
    tip = ui_src[ui_src.index("export function infoTip("):]
    assert 'h("button", {type: "button", class: "itip", "aria-expanded": "false"}, "ⓘ")' in tip
    assert "b.title = t;" in tip and 'b.setAttribute("aria-label", `${label}: ${t}`);' in tip
    assert 'h("div", {class: "itip-pop", role: "tooltip"}, b.title)' in tip
    assert 'if (e.key === "Escape") tipClose();' in ui_src
    css = _read("components.css")
    assert "@media (pointer: coarse) { .itip { width: 32px; height: 32px; } }" in css      # a phone's touch target


def test_positions_and_account_print_the_shared_caption_once():
    pos = _read("screens", "positions.js")
    assert 'ui.stat(["미실현 손익 합계 (USDT) ", ui.infoTip(ui.ASSUME_OPEN_KO, "미실현 손익")], sumNum, sumSub)' in pos
    assert "caption: false, countOnly: co(x)," in pos                     # a phone's cards: the list's caption once
    assert pos.count("ui.assume(") == 3                                   # one per tab (positions / orders / trades)
    assert 'ui.screenHead("포지션", "모의 계좌의 열린 포지션")' in pos
    acc = _read("screens", "account.js")
    assert "ui.assume(" not in acc and acc.count('ui.assumeLine(["closed", "open"])') == 1
    # the two big money numbers keep an ⓘ with their own caption (review: "each money card keeps an ⓘ")
    assert 'noName: true, caption: "tip"});' in acc
    assert '"잔고 (USDT) ", ui.infoTip(ui.ASSUME_KO, "잔고")' in acc
    kit = _read("screens", "positions-kit.js")
    assert 'o.caption === "tip" ? [" ", ui.infoTip(ui.ASSUME_OPEN_KO, "미실현 손익")] : null' in kit
    assert 'o.caption === false || o.caption === "tip" || co ? null : ui.assume("open"),' in kit
    for note in ("점선은 시작 잔고", "손익은 거래마다 나갈 때 수수료·펀딩 뒤", "수익률 = 지금 잔고 ÷ 시작 잔고"):
        assert f'ui.note("{note}")' in acc, note


# ---------------------------------------------------------------- 3. 이 코인 포지션: the full name
def test_coin_positions_show_the_full_name_and_move_the_liquidation_price_to_the_tooltip():
    side = _read("screens", "terminal-side.js")
    cp = side[side.index("export function coinPositions("):side.index("// ---------------------------------------------------------------- 수익")]
    assert "청산가 ${fmt.price(x.p.liq)}`" in cp                           # in the row's tooltip
    assert 'h("span", null, "청산가")' not in cp and "term-lq" not in cp
    assert 'h("span", {class: "term-fn term-cfn"}' in cp and "ui.acctLabel(x.a)" in cp        # the timeframe chip + name
    css = _read("screens", "terminal.css")
    assert ".term-cr { display: grid; grid-template-columns: calc(30px * var(--ts)) minmax(0, 1fr) calc(36px * var(--ts)) calc(60px * var(--ts));" in css
    assert re.search(r"\.term-cr \.term-cfn \.an-n \{[^}]*-webkit-line-clamp: 2;[^}]*white-space: normal;", css)
    assert ".term-cr .term-cfn .an-tf { flex: none; }" in css
