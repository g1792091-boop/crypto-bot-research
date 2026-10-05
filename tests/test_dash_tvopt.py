"""v4 차트: the opt-in 거래소 차트 tab (owners 10/06 00:25; TradingView back in the page, without its script).

- the frame is TradingView's own page in a cross-origin <iframe>: sandbox "allow-scripts allow-same-origin allow-popups"
  and referrerpolicy "no-referrer", both on the element before it is attached; Binance perpetual, our interval,
  dark, Korea time, Korean, drawing tools on;
- the iframe exists only while the 거래소 차트 tab is open (none after mount, one on open, a fresh one on a coin /
  interval change, none after leaving the tab or the screen); 우리 차트 stays the default and the choice is not
  remembered;
- no outside <script> anywhere in v4 (markup or a script element made in code), and the iframe lives only in
  screens/chart-tv.js;
- the new-tab links (트레이딩뷰에서 열기, Coinglass) are still there; colours are tokens; INVENTORY has the section.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
CAPTION = "트레이딩뷰 화면 (바깥 사이트) · 우리 봇의 진입·손절선은 '우리 차트' 탭에"


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _files(exts=(".js", ".css", ".html")):
    for d, _, fs in os.walk(V4):
        for f in fs:
            if f.endswith(exts):
                yield os.path.join(d, f)


def _code(src):
    """The source without // and /* */ comments (no '//' inside these files' strings except URLs after ':')."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", src)


# A small DOM for node: enough for core/dom.js h() and chart-tv.js (attributes kept in the order they were set).
_FAKE_DOM = r"""
class N {
  constructor() { this.parentNode = null; this.childNodes = []; }
  appendChild(c) { if (c.parentNode) c.parentNode._drop(c); c.parentNode = this; this.childNodes.push(c); return c; }
  _drop(c) { this.childNodes = this.childNodes.filter((x) => x !== c); c.parentNode = null; }
  remove() { if (this.parentNode) this.parentNode._drop(this); }
  replaceChildren(...k) { for (const c of [...this.childNodes]) this._drop(c); for (const c of k) this.appendChild(typeof c === "string" ? new T(c) : c); }
}
class T extends N { constructor(t) { super(); this.nodeType = 3; this.data = String(t); } get textContent() { return this.data; } }
class E extends N {
  constructor(tag) { super(); this.nodeType = 1; this.tagName = tag.toUpperCase(); this.attrs = []; this.style = {setProperty() {}};
    this.dataset = {}; this.className = ""; this.listeners = {}; }
  setAttribute(k, v) { const a = this.attrs.find((x) => x[0] === k); if (a) a[1] = String(v); else this.attrs.push([k, String(v)]); }
  getAttribute(k) { const a = this.attrs.find((x) => x[0] === k); return a ? a[1] : null; }
  hasAttribute(k) { return this.getAttribute(k) !== null; }
  removeAttribute(k) { this.attrs = this.attrs.filter((x) => x[0] !== k); }
  get hidden() { return this.hasAttribute("hidden"); }
  set hidden(v) { if (v) this.setAttribute("hidden", ""); else this.removeAttribute("hidden"); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(new T(v)); }
}
const all = (el, tag) => el.nodeType !== 1 ? [] : [...(el.tagName === tag ? [el] : []), ...el.childNodes.flatMap((c) => all(c, tag))];
"""


def _node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    tv = "file://" + os.path.join(SCREENS, "chart-tv.js")
    # chart-tv.js (and pb.js behind it) is imported before the fake document exists: nothing in it may touch the DOM
    # at import time; h() reads document / Node only when called.
    script = (f"const tv = await import('{tv}');\n" + _FAKE_DOM +
              "globalThis.Node = N;\n"
              "globalThis.document = {createElement: (t) => new E(t), createElementNS: (ns, t) => new E(t), createTextNode: (t) => new T(t)};\n"
              + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- the frame, wired in node
def test_iframe_only_while_the_tab_is_open_and_sandboxed():
    out = _node("""
    const page = new E("div");
    const f = tv.tvFrame();
    page.appendChild(f.el);
    const snap = () => all(page, "IFRAME").map((x) => ({attrs: x.attrs, parent: !!x.parentNode}));
    const o = {};
    o.mounted = {n: all(page, "IFRAME").length, hidden: f.el.hidden, open: f.isOpen(), cap: f.el.textContent};
    f.show("BTC", "15m");
    const first = all(page, "IFRAME")[0];
    o.opened = {frames: snap(), hidden: f.el.hidden, open: f.isOpen()};
    f.show("BTC", "15m");
    o.same = all(page, "IFRAME").length === 1 && all(page, "IFRAME")[0] === first;
    f.show("ETH", "4h");
    const second = all(page, "IFRAME")[0];
    o.changed = {frames: snap(), fresh: second !== first, oldGone: first.parentNode === null};
    f.hide();
    o.closed = {n: all(page, "IFRAME").length, hidden: f.el.hidden, open: f.isOpen(), secondGone: second.parentNode === null};
    f.show("SOL", "5m");
    o.reopened = all(page, "IFRAME").length;
    f.hide(); f.hide();
    o.twice = all(page, "IFRAME").length;
    console.log(JSON.stringify(o));""")
    assert out["mounted"]["n"] == 0 and out["mounted"]["hidden"] is True and out["mounted"]["open"] is False
    assert out["mounted"]["cap"] == CAPTION
    fr = out["opened"]["frames"]
    assert len(fr) == 1 and fr[0]["parent"] and out["opened"]["hidden"] is False and out["opened"]["open"] is True
    attrs = dict(fr[0]["attrs"])
    names = [k for k, _ in fr[0]["attrs"]]
    assert attrs["sandbox"] == "allow-scripts allow-same-origin allow-popups"
    assert attrs["referrerpolicy"] == "no-referrer"
    assert names.index("sandbox") < names.index("src") and names.index("referrerpolicy") < names.index("src")
    assert "allow-top-navigation" not in attrs["sandbox"] and "allow-forms" not in attrs["sandbox"]
    assert not {"srcdoc", "allow", "allowfullscreen"} & set(names)
    assert attrs["src"].startswith("https://s.tradingview.com/widgetembed/?")
    assert out["same"] is True                                       # the same coin and interval: no reload
    ch = out["changed"]["frames"]
    assert len(ch) == 1 and out["changed"]["fresh"] is True and out["changed"]["oldGone"] is True
    assert "symbol=BINANCE%3AETHUSDT.P" in dict(ch[0]["attrs"])["src"] and "interval=240" in dict(ch[0]["attrs"])["src"]
    assert out["closed"] == {"n": 0, "hidden": True, "open": False, "secondGone": True}
    assert out["reopened"] == 1 and out["twice"] == 0


def test_embed_url_binance_perpetual_our_interval_korea_time_dark_drawing_tools():
    out = _node("""
    const q = (coin, tf) => Object.fromEntries(new URL(tv.tvEmbedUrl(coin, tf)).searchParams);
    const u = new URL(tv.tvEmbedUrl("BTC", "15m"));
    console.log(JSON.stringify({host: u.host, path: u.pathname, proto: u.protocol, btc: q("BTC", "15m"),
      iv: Object.fromEntries(["5m", "15m", "30m", "1h", "4h", "1d", "1w", "nope"].map((tf) => [tf, q("ETH", tf).interval]))}));""")
    assert out["proto"] == "https:" and out["host"] == "s.tradingview.com" and out["path"] == "/widgetembed/"
    p = out["btc"]
    assert p["symbol"] == "BINANCE:BTCUSDT.P" and p["interval"] == "15"
    assert p["theme"] == "dark" and p["timezone"] == "Asia/Seoul" and p["locale"] == "kr"
    assert p["hidesidetoolbar"] == "0"                               # the drawing tools are there
    assert out["iv"] == {"5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D", "1w": "W", "nope": "15"}


# ---------------------------------------------------------------- the 차트 screen: default tab, lazy, cleanup
def test_chart_screen_keeps_our_chart_the_default_and_opens_the_frame_only_on_the_tab():
    js = _read("screens", "chart.js")
    code = _code(js)
    assert 'import {TV_IV, tvFrame} from "./chart-tv.js";' in js
    assert 'view: "bot"' in code and 'dataset: {view: "bot"}' in code
    assert re.search(r'ui\.seg\(\[\{id: "bot", label: "우리 차트"\}, \{id: "tv", label: "거래소 차트"[^\]]*\], "bot",', code)
    # tv.show only on the 거래소 차트 tab: in setView behind its tv test, or in paintLinks behind st.view === "tv"
    shows = [ln for ln in code.splitlines() if "tv.show(" in ln]
    assert len(shows) == 2 and all('st.view === "tv"' in ln for ln in shows), shows
    assert "ctx.track(() => tv.hide());" in code                     # removed on unmount
    assert "else tv.hide();" in code                                 # removed when 우리 차트 is chosen again
    assert 'if (st.view === "tv") setView("bot");' in code           # picking an account goes back to our lines
    # opt-in every visit: the tab is not remembered nor read from the URL
    assert not re.search(r"local\.(get|set)\([\"']chart-view", code) and "query.view" not in code
    # the bot-only parts hide on that tab; the interval strip stays (it drives the frame)
    css = _read("screens", "chart.css")
    assert '.chart-card[data-view="tv"] > :is(.chart-wrap, .chart-ctrl, .chart-toggles, .pos-note, .assume) { display: none; }' in css


def test_chart_screen_module_still_loads_in_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    url = "file://" + os.path.join(SCREENS, "chart.js")
    r = subprocess.run([node, "--input-type=module", "-e",
                        f"const m = await import('{url}'); console.log(JSON.stringify([typeof m.mount, typeof m.update, typeof m.unmount]));"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == ["function", "function", "function"]


def test_link_out_is_still_there():
    js = _read("screens", "chart.js")
    assert 'h("a", {class: "btn-line", target: "_blank", rel: "noopener noreferrer"}, "트레이딩뷰에서 열기 ↗")' in js
    assert "tvA.href = `https://www.tradingview.com/chart/?symbol=BINANCE:${c}USDT.P&interval=${TV_IV[st.tf] || \"15\"}`;" in js
    for label in ("코인글래스 차트", "청산 지도", "청산 히트맵", "파생 정보"):
        assert label in js, label
    assert 'target: "_blank", rel: "noopener noreferrer"}, t, " ↗")' in js
    assert "tvA, cgLinks" in js                                      # the link row is still on the page


# ---------------------------------------------------------------- no outside script, one frame, in one file
def test_no_outside_script_anywhere_in_v4_and_the_iframe_only_in_chart_tv():
    for p in _files():
        src = _read(p)
        rel = os.path.relpath(p, V4)
        assert not re.search(r"<script[^>]+src=[\"']?(https?:)?//", src, re.I), rel
        assert not re.search(r"tradingview\.com/tv\.js|[\"'/]tv\.js[\"']", src), rel          # the v3 loader script
        assert "s3.tradingview.com" not in src and "TradingView.widget" not in src, rel
        assert "embed-widget" not in src, rel                        # TradingView's script-tag widgets
        if p.endswith(".js"):
            code = _code(src)
            assert not re.search(r"""h\(\s*["'`]script""", code), rel
            if re.search(r"""createElement\(\s*["'`]script""", code):
                # the only script element made in code is the vendored chart library, same origin
                assert rel == os.path.join("core", "lwc.js"), rel
                assert 'const SRC = "/static/vendor/lightweight-charts.standalone.production.js";' in src
            if rel != os.path.join("screens", "chart-tv.js"):
                assert not re.search(r"""(h|createElement)\(\s*["'`]iframe""", code), rel
                assert "s.tradingview.com" not in src, rel
        else:
            assert "<iframe" not in src.lower(), rel
    tvjs = _read("screens", "chart-tv.js")
    assert len(re.findall(r'h\("iframe"', tvjs)) == 1
    assert 'const SANDBOX = "allow-scripts allow-same-origin allow-popups";' in tvjs
    assert 'sandbox: SANDBOX, referrerpolicy: "no-referrer"' in tvjs
    assert f'export const TV_CAPTION = "{CAPTION}";' in tvjs
    assert set(re.findall(r"https?://([a-z0-9.-]+)", tvjs)) == {"s.tradingview.com"}


def test_tokens_only_and_a_sensible_frame_height_on_phone_and_pc():
    css = re.sub(r"/\*.*?\*/", "", _read("screens", "chart.css"), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\b(rgba?|hsla?)\(\s*\d", css)
    tvjs = _code(_read("screens", "chart-tv.js"))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", tvjs) and not re.search(r"\b(rgba?|hsla?)\(\s*\d", tvjs)
    slot = re.search(r"\.chart-tv-slot \{([^}]*)\}", css).group(1)
    assert "height: 60vh" in slot and "min-height: 360px" in slot and "max-height: 600px" in slot
    assert "var(--line)" in slot and "var(--surface-2)" in slot
    assert "@media (min-width: 1000px) { .chart-tv-slot { height: 560px; max-height: none; } }" in css
    assert ".chart-tv-frame { display: block; width: 100%; height: 100%; border: 0; }" in css
    assert re.search(r"\.chart-views button \{ height: (3[2-9]|4\d)px;", css)          # touch target


def test_inventory_and_contract_name_it():
    inv = _read("INVENTORY.md")
    sec = inv[inv.index("## 17. 거래소 차트 (TradingView opt-in)"):]
    for want in ("screens/chart-tv.js", 'sandbox="allow-scripts allow-same-origin allow-popups"', 'referrerpolicy="no-referrer"',
                 "frame-src https://s.tradingview.com https://www.tradingview-widget.com", CAPTION, "test_dash_tvopt.py"):
        assert want in sec, want
    assert "(§17)" in inv[:inv.index("## 3. ")]                     # the old 거래소 차트 row points at the new section
    assert "screens/chart-tv.js" in _read("CONTRACT.md")
