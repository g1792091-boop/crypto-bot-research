"""후보 리그 터미널 (candleague/static/js/screens/terminal*.js, static/scr/terminal.css), in the rule bot's v4 terminal look.

The screen runs here under node on a tiny DOM stand-in and a stand-in chart library (no browser): it opens on an open 후보
position (B5) and shows its live P&L at the mark in the left panel, the table and the band; a new mark repaints them (live
refresh); the chart gets that position's entry / stop / take-profit / liquidation lines and a chip per position of the
coin; a hidden DeepSeek position (D11) is counted only and never shows a price, a leverage or money — not in the text,
not in a tooltip, not as a chart line — even when such a field slipped through; while the engine replays from 10/01 the
live numbers are hidden and the screen says why. The realized-P&L math and the default choice are checked as plain
functions. Static checks: text only through dom.js (no HTML strings), relative imports only (copied from the rule bot,
never imported), the stylesheet uses tokens and var(--t-*) sizes only and its own tm- prefix, the files are served
behind the login."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STATIC = os.path.join(ROOT, "candleague", "static")
JS = os.path.join(STATIC, "js")
OWN_JS = ("terminal.js", "terminal-kit.js", "terminal-top.js", "terminal-chart.js", "terminal-table.js", "terminal-side.js",
          "terminal-feed.js")
CSS = os.path.join(STATIC, "scr", "terminal.css")

# A minimal DOM for node (elements, text, fragments, classes, attributes, events, a tag.class selector query) and a
# stand-in for the vendored lightweight-charts that records the price lines and marks the screen asks for.
DOM_SHIM = r"""
class N {
  constructor() { this.childNodes = []; this.parentNode = null; }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  appendChild(c) {
    if (c.nodeType === 11) { for (const k of [...c.childNodes]) this.appendChild(k); return c; }
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.childNodes.push(c); return c;
  }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  append(...k) { for (const x of k) this.appendChild(x instanceof N ? x : new T(String(x))); }
  replaceChildren(...k) { for (const c of this.childNodes) c.parentNode = null; this.childNodes = []; this.append(...k); }
  after(x) { const p = this.parentNode; if (!p) return; const i = p.childNodes.indexOf(this); if (x.parentNode) x.parentNode.removeChild(x); x.parentNode = p; p.childNodes.splice(i + 1, 0, x); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(); if (v != null && v !== "") this.appendChild(new T(String(v))); }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === globalThis.document.documentElement; }
}
class T extends N { constructor(t) { super(); this.nodeType = 3; this.data = t; } get textContent() { return this.data; } set textContent(v) { this.data = String(v); } }
class F extends N { constructor() { super(); this.nodeType = 11; } }
class E extends N {
  constructor(tag) {
    super(); this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {}; this.dataset = {}; this.ev = {};
    const self = this;
    this.style = {setProperty(k, v) { this[k] = v; }, removeProperty(k) { delete this[k]; }};
    this.classList = {
      add: (...c) => { const s = self._cls(); c.forEach((x) => s.add(x)); self._set(s); },
      remove: (...c) => { const s = self._cls(); c.forEach((x) => s.delete(x)); self._set(s); },
      toggle: (c, on) => { const s = self._cls(); const v = on === undefined ? !s.has(c) : !!on; if (v) s.add(c); else s.delete(c); self._set(s); return v; },
      contains: (c) => self._cls().has(c),
    };
  }
  _cls() { return new Set(String(this.attrs.class || "").split(/\s+/).filter(Boolean)); }
  _set(s) { this.attrs.class = [...s].join(" "); }
  get className() { return this.attrs.class || ""; }
  set className(v) { this.attrs.class = String(v); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  get hidden() { return "hidden" in this.attrs; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get title() { return this.attrs.title || ""; }
  set title(v) { this.attrs.title = String(v); }
  get tabIndex() { return Number(this.attrs.tabindex || 0); }
  set tabIndex(v) { this.attrs.tabindex = String(v); }
  addEventListener(t, f) { (this.ev[t] ||= []).push(f); }
  removeEventListener() {}
  fire(t) { for (const f of this.ev[t] || []) f({target: this, key: "Enter", preventDefault() {}, stopPropagation() {}}); }
  click() { this.fire("click"); }
  focus() {} scrollIntoView() {}
  get offsetWidth() { return 0; }
  matches(sel) {
    const m = /^([a-z0-9]*)((?:\.[\w-]+)*)$/i.exec(sel.trim());
    if (!m) throw new Error("selector " + sel);
    if (m[1] && m[1].toUpperCase() !== this.tagName) return false;
    const c = this._cls();
    return m[2].split(".").filter(Boolean).every((x) => c.has(x));
  }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => { for (const c of n.childNodes) { if (c.nodeType === 1) { if (c.matches(sel)) out.push(c); walk(c); } } };
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const html = new E("html"), body = new E("body"), head = new E("head");
html.append(head, body);
html.dataset.motion = "less";                       // 숫자 움직임 줄이기: numbers paint at once
globalThis.Node = N;
globalThis.document = {createElement: (t) => new E(t), createElementNS: (ns, t) => new E(t), createTextNode: (t) => new T(t),
  createDocumentFragment: () => new F(), documentElement: html, body, head, visibilityState: "visible", hidden: false,
  addEventListener() {}, removeEventListener() {}};
globalThis.window = {addEventListener() {}, removeEventListener() {}, scrollY: 0};
globalThis.location = {hash: "", search: ""};
globalThis.getComputedStyle = () => ({getPropertyValue: () => "", backgroundColor: "", flexWrap: "wrap"});
globalThis.NARROW = false;
globalThis.matchMedia = (q) => ({matches: /reduced-motion/.test(q) ? true : /max-width: 899/.test(q) ? globalThis.NARROW : false,
  addEventListener() {}, removeEventListener() {}});
globalThis.requestAnimationFrame = (f) => setTimeout(() => f(Date.now()), 0);
globalThis.cancelAnimationFrame = () => {};
const store = {};
globalThis.localStorage = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; }};
// the chart library stand-in: records what the screen draws
globalThis.CH = null;
const mkSeries = () => ({data: [], lines: [], marks: [], opts: {},
  setData(d) { this.data = d.slice(); }, update(b) { const l = this.data[this.data.length - 1]; if (l && l.time === b.time) this.data[this.data.length - 1] = b; else this.data.push(b); },
  setMarkers(m) { this.marks = m.slice(); }, createPriceLine(o) { const x = {...o}; this.lines.push(x); return x; },
  removePriceLine(x) { this.lines = this.lines.filter((y) => y !== x); }, applyOptions(o) { Object.assign(this.opts, o); },
  priceToCoordinate(p) { return 120; }});
globalThis.window.LightweightCharts = {createChart: () => {
  const cs = mkSeries(), vs = mkSeries();
  globalThis.CH = {cs, vs};
  return {addCandlestickSeries: () => cs, addHistogramSeries: () => vs, priceScale: () => ({applyOptions() {}, width: () => 60}),
    timeScale: () => ({setVisibleLogicalRange() {}, setVisibleRange() {}, subscribeVisibleLogicalRangeChange() {}, height: () => 24, fitContent() {}}),
    subscribeCrosshairMove() {}, resize() {}, remove() {}};
}};
// the server: every /api/... answered from globalThis.API
globalThis.API = {};
globalThis.fetch = async (path) => {
  const key = Object.keys(globalThis.API).filter((k) => String(path).startsWith(k)).sort((a, b) => b.length - a.length)[0];
  const body = key ? (typeof globalThis.API[key] === "function" ? globalThis.API[key](path) : globalThis.API[key]) : null;
  return {ok: !!key, status: key ? 200 : 404, json: async () => body};
};
globalThis.tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
/** every text and every tooltip / label under a node (what a viewer can read or hover) */
globalThis.allText = (n) => {
  let out = n.textContent;
  const walk = (x) => { for (const c of x.childNodes || []) { if (c.nodeType === 1) { for (const k of ["title", "aria-label"]) if (c.attrs[k]) out += " " + c.attrs[k]; walk(c); } } };
  walk(n);
  return out;
};
"""


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    return node


def _run(tmp_path, body: str) -> dict:
    """Run ``body`` (an async JS block that sets ``out``) after the DOM stand-in; returns ``out`` as JSON."""
    url = lambda f: "file://" + os.path.join(JS, f)  # noqa: E731
    code = DOM_SHIM + f"""
const K = await import("{url('poskit.js')}");
const LKm = await import("{url('lk.js')}");
const L = await import("{url('live.js')}");
const TK = await import("{url('screens/terminal-kit.js')}");
const TM = await import("{url('screens/terminal.js')}");
let out = {{}};
{body}
console.log(JSON.stringify(out));
process.exit(0);
"""
    f = tmp_path / "term_ui_test.mjs"
    f.write_text(code)
    r = subprocess.run([_node(), str(f)], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


# ------------------------------------------------------------------------------------------------ the shared fixture
# BTC long 30x 후보 (qty 0.1 @ 100,000, margin 333.33), ETH short 1/4 40x (a lock), one hidden DeepSeek position whose money
# fields "slipped through" (the client must still show none of them), one DeepSeek position the server legitimately nulled.
FIXTURE = r"""
const NOW = Date.now();
const pos = (o) => ({pick: null, of: null, role: "cand", kind: "core", name: "DOGE", tf: "1h", exit: "tp3R|4", exit_ko: "고정 익절 3R · 손절 4 ATR",
  size: 1, trades: 12, wins: 7, bust: false, hidden: false, stop_is_lock: false, tp: null, tp_pnl: null, why: null, ...o});
const P1 = pos({id: "core-DOGE-1h-1", coin: "BTCUSD", symbol: "BTCUSDT", side: 1, since: NOW - 3 * 3600e3, lev: 30, entry: 100000, stop: 98000,
  tp: 106000, qty: 0.1, notional: 10000, margin: 333.33, margin_pct: 0.1993, liq: 96900, liq_dist_entry: 0.031, wallet: 5100, equity_at_entry: 5102,
  stop_pnl: -200, stop_roe: -0.6, tp_pnl: 600,
  why: {group_ko: null, head_ko: "보통 또는 좋은 자리 · 30배 · 증거금 20%", lev_ko: "보통 자리 첫 배수 30배 그대로", sub_ko: "후보: 커스텀값", rule_ko: "규칙: ..."}});
const P2 = pos({id: "core-OBV_S-1h-3-q", role: "quarter", size: 0.25, name: "OBV_S", coin: "ETHUSD", symbol: "ETHUSDT", side: -1, since: NOW - 3600e3, lev: 40,
  entry: 2500, stop: 2450, stop_is_lock: true, qty: 1, notional: 2500, margin: 62.5, margin_pct: 0.0126, liq: 2560, liq_dist_entry: 0.024,
  stop_pnl: 50, stop_roe: 0.8, exit: "ladder|2", exit_ko: "계단 잠금 10%부터 · 손절 2 ATR"});
const LEAK = pos({id: "ds-F5_BOX-15m-1", kind: "ds", name: "F5_BOX", tf: "15m", coin: "BTCUSD", symbol: "BTCUSDT", side: -1, since: NOW - 7200e3, hidden: true,
  lev: 50, entry: 123456.7, stop: 124999.9, qty: 7.777, margin: 4321.09, liq: 125432.1, stop_pnl: -987.65, wallet: 6543.21, liq_dist_entry: 0.001,
  why: {group_ko: "좋은 자리", head_ko: "좋은 자리 · 50배", lev_ko: "좋은 자리 첫 배수 50배 그대로", sub_ko: "", rule_ko: ""}});
const HID = pos({id: "base-ds-F1_PVT_DIV-1h", role: "base", kind: "ds", name: "F1_PVT_DIV", coin: "SOLUSD", symbol: "SOLUSDT", side: 1, since: NOW - 600e3,
  hidden: true, lev: null, entry: null, stop: null, qty: null, margin: null, liq: null});
const doc = (o = {}) => ({ds_money: false, exact: false, brackets: "exchange.json", generated_ms: NOW - 60e3, done_ms: NOW - 120e3,
  start_ms: NOW - 10 * 86400e3, started_ms: NOW - 2 * 86400e3, server_ms: NOW, snap_age_s: 60, lag_s: 120, catching_up: false, old: false,
  positions: [P1, P2, LEAK, HID], counts: {open: 4, long: 2, short: 2, hidden: 2,
    by_coin: {BTCUSD: {long: 1, short: 1}, ETHUSD: {long: 0, short: 1}, SOLUSD: {long: 1, short: 0}}, by_role: {}, by_kind: {}}, ...o});
const live = (btc, eth) => ({generated_ms: Date.now(), server_ms: Date.now(), source: "binance", stale: false,
  coins: [{coin: "BTCUSD", price: btc, mark: btc, change_pct: 1.2, quote_volume: 1.2e9, high: btc + 500, low: btc - 900, funding_rate: 0.0001,
    next_funding_ms: NOW + 3600e3, open_interest: 9000, ok: true},
    {coin: "ETHUSD", price: eth, mark: eth, ok: true}, {coin: "SOLUSD", price: 150, mark: 150, ok: true}]});
const TFMS = {"1m": 60e3, "5m": 300e3, "15m": 900e3, "30m": 1800e3, "1h": 3600e3, "4h": 14400e3};
const bars = (path) => {          // the bars of the asked timeframe, the last one the bar forming now
  const step = TFMS[new URLSearchParams(String(path).split("?")[1]).get("tf")] || 900e3, t = [], c = [], v = [];
  for (let i = 0; i < 288; i++) { t.push(Math.floor(NOW / step) * step - (287 - i) * step); c.push(100000 + i); v.push(5); }
  return {bars: {t, o: c, h: c, l: c, c, v}};
};
const fills = {fills: [
  {symbol: "BTCUSDT", side: 1, entry_time: NOW - 9e6, entry_price: 99000, exit_time: NOW - 6e6, exit_price: 99500, exit_reason: "TP", leverage: 30, pnl: 150.5, roe: 0.45, account: "core-DOGE-1h-1"},
  {symbol: "SOLUSDT", side: -1, entry_time: NOW - 9e6, entry_price: null, exit_time: NOW - 5e6, exit_price: null, exit_reason: "SL", leverage: 50, pnl: null, roe: null, win: false, account: "ds-F5_BOX-15m-1"},
  {symbol: "ETHUSDT", side: -1, entry_time: NOW - 8e6, entry_price: 2600, exit_time: NOW - 4e6, exit_price: 2650, exit_reason: "LIQ", leverage: 40, pnl: -62.5, roe: -1, account: "core-OBV_S-1h-3-q"}]};
const book = {equity: null, trades: [fills.fills[0]]};
const pnlDoc = {role: "cand", kind: "all", accounts: 2, hidden: 1, total: 90.5, trades: 3, wins: 1, losses: 2, max_dd: 30,
  hours: [[Math.floor((NOW - 5 * 3600e3) / 3600e3) * 3600e3, 120.5, 2, 1], [Math.floor((NOW - 2 * 3600e3) / 3600e3) * 3600e3, -30, 1, 0]],
  days: [[TK.kstMidnight(NOW), 90.5, 3, 1]], generated_ms: NOW - 60e3, server_ms: NOW};
LKm.setLeague({ds_money: false, start_ms: NOW - 10 * 86400e3, done_ms: NOW - 120e3, generated_ms: NOW - 60e3, started_ms: NOW - 2 * 86400e3,
  watch: {checkpoints: [{id: "C1", ko: "1차 점검", ms: NOW + 31 * 86400e3}]},
  accounts: [{id: "core-DOGE-1h-1", role: "cand", kind: "core", name: "DOGE", tf: "1h", trades: 12, wins: 7, wallet: 5100, mean_ret: 0.01, max_dd: 0.05},
    {id: "core-OBV_S-1h-3", role: "cand", kind: "core", name: "OBV_S", tf: "1h", trades: 5, wins: 2, wallet: 4900, mean_ret: -0.01},
    {id: "core-OBV_S-1h-3-q", role: "quarter", kind: "core", name: "OBV_S", tf: "1h", of: "core-OBV_S-1h-3", trades: 5, wins: 2, wallet: 4980},
    {id: "ds-F5_BOX-15m-1", role: "cand", kind: "ds", name: "F5_BOX", tf: "15m", trades: 9, wins: 4},
    {id: "base-ds-F1_PVT_DIV-1h", role: "base", kind: "ds", name: "F1_PVT_DIV", tf: "1h", trades: 3, wins: 1}]});
const every = [];
const queries = [];
const ctxOf = (q = {}) => ({params: {name: "terminal", arg: null, query: q}, alive: () => true, signal: {addEventListener() {}},
  api: async (p) => { const r = await fetch(p); if (!r.ok) throw Object.assign(new Error("HTTP"), {status: r.status}); return r.json(); },
  meta: async () => ({}), onLeague(fn) { if (LKm.league()) fn(LKm.league()); }, onLive: (fn) => L.onLive(fn), onPositions: (fn) => K.onPositions(fn),
  every(ms, fn) { every.push({ms, fn}); }, setTitle() {}, setQuery(x) { queries.push(x); }, css: async () => {}, wide() {},
  href: (n, a, q2) => `#/${n}${a ? "/" + encodeURIComponent(a) : ""}${q2 ? "?" + new URLSearchParams(q2) : ""}`});
const mountOn = async (d, lv, q) => {
  API["/api/positions"] = d; API["/api/live"] = lv; API["/api/klines"] = bars; API["/api/fills"] = fills; API["/api/meta"] = {};
  API["/api/trades/"] = book; API["/api/pnl"] = pnlDoc;
  const el = document.createElement("div");
  document.body.append(el);
  const done = TM.mount(el, ctxOf(q));
  await tick(80); await L.liveRefresh(); await tick(80); await done; await tick(40);
  return el;
};
const q1 = (el, sel) => { const x = el.querySelector(sel); return x ? x.textContent : null; };
"""


def test_opens_on_a_live_position_and_refreshes(tmp_path):
    """B5: with no account asked for, the terminal opens on the open 후보 position (BTC long +100.00 at mark 101,000:
    0.1 x 1,000, ROE 30 %) — the left panel, the table's total and the band agree; the chart has its lines and its chip;
    a new mark (102,000) repaints them all (live refresh); the address keeps the choice."""
    o = _run(tmp_path, FIXTURE + r"""
const el = await mountOn(doc(), live(101000, 2550), {});
out.led = q1(el, "b.tm-led"); out.roe = q1(el, "b.tm-ledsm");
out.sel = q1(el, "div.tm-selb");
out.total = q1(el, "b.tm-utot");
out.band = q1(el, "div.tm-band");
out.rows = el.querySelectorAll("tr.click").length;
out.tableTab = q1(el, "div.tm-seg");
out.lines = CH.cs.lines.map((x) => [x.price, x.title]);
out.marks = CH.cs.marks.map((x) => x.text);
out.chips = el.querySelectorAll("button.tm-chip").map((x) => x.textContent);
out.strip = el.querySelectorAll("button.tm-wr").map((x) => x.textContent);
out.mine = el.querySelectorAll("button.tm-cr").map((x) => x.textContent);
out.top = q1(el, "div.tm-row");
out.query = queries[queries.length - 1];
API["/api/live"] = live(102000, 2550);
await L.liveRefresh(); await tick(60);
out.led2 = q1(el, "b.tm-led"); out.total2 = q1(el, "b.tm-utot"); out.band2 = q1(el, "div.tm-band");
out.chips2 = el.querySelectorAll("button.tm-chip").map((x) => x.textContent);
out.last = CH.cs.data[CH.cs.data.length - 1].close;
out.feed = el.querySelectorAll("button.tm-fr").map((x) => x.textContent);
out.fold = el.querySelectorAll("div.tm-fr").map((x) => x.textContent);
// a new engine snapshot with a new 후보 position: the table, the band and the feed take it (no reload)
const P4 = {...P1, id: "core-OBV_S-1h-3", name: "OBV_S", coin: "ETHUSD", symbol: "ETHUSDT", side: -1, since: NOW - 60e3, entry: 2600, qty: 1, margin: 86.67, liq: 2680};
API["/api/positions"] = doc({positions: [P1, P2, LEAK, HID, P4], generated_ms: NOW - 30e3});
await K.kickPositions(); await tick(80);
out.rows3 = el.querySelectorAll("tr.click").length;
out.total3 = q1(el, "b.tm-utot");
out.feed3 = el.querySelectorAll("button.tm-fr").map((x) => x.textContent);
""")
    assert o["led"] == "+100.00" and o["roe"] == "+30.00%"
    assert "BTCUSDT" in o["sel"] and "격리 30배" in o["sel"] and "손절에 닿으면−200.00 USDT" in o["sel"] and "왜 30배" in o["sel"]
    assert o["total"] == "+100.00" and "후보 미실현 +100.00 USDT" in o["band"] and "열린 4 · 롱 2 · 숏 2" in o["band"]
    assert "D+10" in o["band"] and "11/" in o["band"]     # days gone since 10/01 (the rule bot's D+n: 10/01 = D+0), next checkpoint
    assert o["rows"] == 1 and o["tableTab"].startswith("포지션 2")             # 묶음 후보: P1 shown, the hidden one counted
    prices = {p: t for p, t in o["lines"]}
    assert prices[100000].startswith("진입 롱 30배") and prices[98000] == "손절" and prices[106000] == "익절" and prices[96900] == "청산 추정"
    assert "롱 열림" in o["marks"] and any(m.startswith("익절") for m in o["marks"])
    assert o["chips"] == ["롱 30배 +30.0% 후보"]
    assert o["strip"][0].startswith("BTC") and "1↑ 1↓" in o["strip"][0]      # counts include the hidden one
    assert len(o["mine"]) == 1 and "+30.0%" in o["mine"][0]
    assert "101,000" in o["top"] and "롱이 냄" in o["top"]
    assert o["query"] == {"acct": "core-DOGE-1h-1", "coin": "BTCUSD", "tf": "15m"}
    assert o["led2"] == "+200.00" and o["total2"] == "+200.00" and "후보 미실현 +200.00 USDT" in o["band2"]
    assert o["chips2"] == ["롱 30배 +60.0% 후보"] and o["last"] == 102000      # the forming bar follows the live price
    assert any("익절" in r and "+150.50" in r and "BTC" in r for r in o["feed"])      # a closed 후보 trade
    assert any("진입" in r and "100,000.0" in r for r in o["feed"])                   # the open position's entry
    assert o["fold"] and all("딥시크" in r and "개수만" in r for r in o["fold"])         # the hidden 후보 one, counted
    assert o["rows3"] == 2 and o["total3"] == "+250.00"                                # +200 BTC, +50 ETH (2,600 -> 2,550)
    assert "진입" in o["feed3"][0] and "ETH" in o["feed3"][0] and "2,600.0" in o["feed3"][0]


def test_hidden_deepseek_never_shows_money(tmp_path):
    """D11: a hidden DeepSeek position chosen through the address shows its side, coin and time only — no price, size,
    leverage or money in any text or tooltip, no chart line, no chip, no marks — even with money fields that slipped
    through; the table, the coin list, the feed and the sums count it only."""
    o = _run(tmp_path, FIXTURE + r"""
localStorage.setItem("cl-tm-grp", JSON.stringify("all"));
const el = await mountOn(doc(), live(101000, 2550), {acct: "ds-F5_BOX-15m-1"});
out.sel = q1(el, "div.tm-selb");
out.all = allText(el);
out.linePrices = CH.cs.lines.map((x) => x.price);
out.marks = CH.cs.marks.length;
out.chips = el.querySelectorAll("button.tm-chip").map((x) => x.textContent);
out.rows = el.querySelectorAll("tr.click").map((x) => x.textContent);
out.foot = el.querySelectorAll("div.tm-pf").map((x) => x.textContent).join(" | ");
out.feed = el.querySelectorAll("div.tm-fr").map((x) => x.textContent);
out.mine = q1(el, "p.tm-cpo");
out.band = q1(el, "div.tm-band");
const tabs = el.querySelector("div.tm-seg").querySelectorAll("button");
tabs[1].click(); await tick(20);
out.fillRows = el.querySelectorAll("tr.click").map((x) => x.textContent);
out.fillFoot = el.querySelectorAll("div.tm-pf").map((x) => x.textContent).join(" | ");
out.all2 = allText(el);
tabs[2].click(); await tick(20);
out.stops = el.querySelectorAll("tr.click").map((x) => x.textContent);
out.all3 = allText(el);
out.hidFill = TK.hiddenFill(fills.fills[1], {kind: "ds"}, true);
out.shownFill = TK.hiddenFill(fills.fills[0], {kind: "core"}, false);
""")
    for key in ("all", "all2", "all3"):
        for s in SECRETS_PY:
            assert s not in o[key], (key, s)
    assert "딥시크 금액 숨김" in o["sel"] and "SOLUSDT" not in o["sel"] and "BTCUSDT" in o["sel"]
    assert 123456.7 not in o["linePrices"] and 124999.9 not in o["linePrices"] and 125432.1 not in o["linePrices"]
    assert o["marks"] == 0                                                   # the hidden account's trades: no marks
    assert o["chips"] == ["롱 30배 +30.0% 후보"]                              # P1 only (BTC); the hidden one is not a chip
    assert len(o["rows"]) == 2 and all("F5_BOX" not in r for r in o["rows"])
    assert "딥시크 2개 열림 (금액 숨김: 개수만, 합계에서 뺌)" in o["foot"]
    folded = [r for r in o["feed"] if "딥시크" in r]
    assert folded and all("개수만" in r and "배" not in r for r in folded)
    assert o["mine"] == "딥시크 1개도 열림 (금액 숨김: 개수만)"
    assert len(o["fillRows"]) == 2 and "딥시크 1건 (금액 숨김: 건수만)" in o["fillFoot"]
    assert len(o["stops"]) == 3                                              # P1 stop + take-profit, P2 lock
    assert o["hidFill"] is True and o["shownFill"] is False


SECRETS_PY = ["123,456", "123456.7", "124,999", "124999", "7.777", "4,321", "4321.09", "125,432", "125432", "987.65", "6,543", "6543.21", "50배", "좋은 자리"]


def test_catchup_hides_live_numbers_and_says_why(tmp_path):
    """B2: while the engine replays from 10/01 the positions are "그때 기준": no live P&L, ROE or % anywhere (left panel,
    table, band, chips, this coin's list), a banner says why; the entry, stop and liquidation stay."""
    o = _run(tmp_path, FIXTURE + r"""
const el = await mountOn(doc({catching_up: true}), live(101000, 2550), {});
out.led = q1(el, "b.tm-led"); out.note = q1(el, "small.tm-lednote");
out.total = q1(el, "b.tm-utot");
out.band = q1(el, "div.tm-band");
out.banner = q1(el, "div.tm-banner");
out.chips = el.querySelectorAll("button.tm-chip").map((x) => x.textContent);
out.mine = el.querySelectorAll("button.tm-cr").map((x) => x.textContent);
out.row = el.querySelectorAll("tr.click").map((x) => x.textContent);
out.foot = q1(el, "div.tm-pf");
out.lines = CH.cs.lines.map((x) => x.price);
""")
    assert o["led"] == "—" and "따라잡는 중" in o["note"] and o["total"] == "—"
    assert "후보 미실현 따라잡는 중" in o["band"] and "엔진이 따라잡는 중" in o["banner"]
    assert o["chips"] == ["롱 30배 후보"] and all("%" not in x for x in o["mine"])
    assert "+100.00" not in o["row"][0] and "96,900.0" in o["row"][0]
    assert 100000 in o["lines"] and 98000 in o["lines"] and 96900 in o["lines"]


def test_default_choice_links_and_phone_cards(tmp_path):
    """The default position (후보 first; nearest liquidation at the mark, else at entry; hidden never); ?acct=&coin=&tf=
    links keep their coin and timeframe; a phone gets card rows instead of the wide table."""
    o = _run(tmp_path, FIXTURE + r"""
API["/api/live"] = live(101000, 2550); await L.liveRefresh(); await tick(20);
const P3 = {...P1, id: "core-X-1h-1", coin: "ETHUSD", symbol: "ETHUSDT", side: -1, entry: 2500, qty: 1, margin: 80, liq: 2560, liq_dist_entry: 0.024};
out.d1 = TM.defaultPosition(doc()).id;
out.d2 = TM.defaultPosition(doc({positions: [P1, P3, LEAK]})).id;          // ETH short 2,560 is 0.4 % from the mark 2,550
out.d3 = TM.defaultPosition(doc({positions: [P1, P3], catching_up: true})).id;   // not live: the entry distance (2.4 % < 3.1 %)
out.d4 = TM.defaultPosition(doc({positions: [P2, LEAK]})).id;              // no 후보 open: any shown one
out.d5 = TM.defaultPosition(doc({positions: [LEAK, HID]}));
out.d6 = TM.defaultPosition({status: "준비 중"});
out.d7 = TM.defaultPosition(doc(), "ETHUSD").id;
NARROW = true;
const el = await mountOn(doc(), live(101000, 2550), {acct: "core-OBV_S-1h-3-q", coin: "ETHUSD", tf: "1h"});
out.query = queries[queries.length - 1];
out.cards = el.querySelectorAll("button.tm-pcard").map((x) => x.textContent);
out.table = el.querySelectorAll("table.tm-t").length;
out.sel = q1(el, "div.tm-selb");
out.tf = el.querySelector("div.tm-tfs").querySelectorAll("button").filter((b) => b.getAttribute("aria-selected") === "true").map((b) => b.textContent);
""")
    assert o["d1"] == "core-DOGE-1h-1" and o["d2"] == "core-X-1h-1" and o["d3"] == "core-X-1h-1"
    assert o["d4"] == "core-OBV_S-1h-3-q" and o["d5"] is None and o["d6"] is None and o["d7"] == "core-OBV_S-1h-3-q"
    assert o["query"] == {"acct": "core-OBV_S-1h-3-q", "coin": "ETHUSD", "tf": "1h"} and o["tf"] == ["1시간"]
    assert o["table"] == 0 and len(o["cards"]) == 1 and "미실현" in o["cards"][0]   # 묶음 후보: the BTC one
    assert "ETHUSDT" in o["sel"] and "격리 40배" in o["sel"] and "잠금선" in o["sel"] and "+50.00" in o["sel"]


def test_realized_pnl_math(tmp_path):
    """The 수익 차트 math (copied from the rule bot's terminal-pnl-calc.js): /api/pnl rows to hour ends, the cumulative
    line from 0, wins / losses, the deepest fall, today's numbers from the same rows, the calendar weeks (Monday first, a
    day without a record is not a zero), the windows worth offering, the hidden-position rule."""
    o = _run(tmp_path, r"""
const H = 3600e3, D = 24 * H, KST = 9 * H;
const start = Date.UTC(2026, 9, 1, 0, 0), now = Date.UTC(2026, 9, 3, 6, 30);      // 10/01 09:00 KST, 10/03 15:30 KST
const api = {hours: [[start + 2 * H, 100, 2, 2], [start + 5 * H, -250, 3, 0], [start + 52 * H, 80, 1, 1]], days: [[TK.kstMidnight(start), -150, 5, 2]]};
const cur = TK.fromApi(api, start, now);
out.hours = cur.hours;
const sr = TK.series(cur, null);
out.sr = {total: sr.total, trades: sr.trades, wins: sr.wins, losses: sr.losses, mdd: sr.mdd, step: sr.step / H, last: sr.pts[sr.pts.length - 1], first: sr.pts[0], empty: sr.empty};
out.win24 = TK.series(cur, D).total;
out.today = TK.todayOf(cur, now);
out.windows = TK.windowsFor(now - start).map((w) => w.id);
const cal = TK.calDays(api.days, start, now);
out.cal = {label: cal.label, n: cal.cells.length, pads: cal.cells.filter((c) => c.pad).length, first: cal.cells.find((c) => !c.pad),
  today: cal.cells.find((c) => c.state === "today").d, future: cal.cells.filter((c) => c.state === "future").length,
  noRecord: cal.cells.filter((c) => c.state === "done" && c.v === null).length};
out.empty = TK.series(TK.fromApi({hours: []}, start, now), null).empty;
out.hp = [TK.hiddenPos({hidden: true}), TK.hiddenPos({kind: "ds", qty: null, entry: 1}), TK.hiddenPos({kind: "core", qty: 1, entry: 1})];
out.mmss = TK.mmss(3725e3);
out.usdKo = [TK.usdKo(1.234e9), TK.usdKo(34000), TK.usdKo(950)];
""")
    assert o["hours"][0] == [1790812800000 + 3 * 3600e3, 100, 2, 2, 0] and o["hours"][1][4] == 3
    s = o["sr"]
    assert s["total"] == -70 and s["trades"] == 6 and s["wins"] == 3 and s["losses"] == 3 and s["mdd"] == 250
    assert s["step"] == 1 and s["first"] == [1790812800000, 0] and s["last"][1] == -70 and not s["empty"]
    assert o["win24"] == 80
    assert o["today"] == {"n": 1, "w": 1, "l": 0, "pnl": 80}               # 10/03 KST: the 15:00 hour
    assert o["windows"] == ["24h", "all"]
    c = o["cal"]
    assert c["label"] == "2026.10" and c["n"] == 7 and c["pads"] == 3                 # Monday 9/28 .. Sunday 10/4
    assert c["first"]["d"] == 1 and c["first"]["state"] == "done" and c["first"]["v"] == -150
    assert c["today"] == 3 and c["future"] == 1 and c["noRecord"] == 1     # 10/02 closed nothing: no zero drawn
    assert o["empty"] is True and o["hp"] == [True, True, False]
    assert o["mmss"] == "1:02:05" and o["usdKo"] == ["12.3억", "3만", "950"]


def test_text_only_tokens_and_prefix():
    """No HTML from strings in the terminal's modules, relative imports only (the rule bot's code is copied, never
    imported); the stylesheet: colours from the tokens, sizes var(--t-*) (or calc(px * var(--ts))), every rule scoped to the
    terminal (.tm…, or the screen's own main) and every own class tm-; the module brings its css and asks for the width."""
    for f in OWN_JS:
        src = open(os.path.join(JS, "screens", f)).read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
            assert bad not in src, (f, bad)
        for imp in re.findall(r'^import .* from "([^"]+)";', src, re.M):
            assert re.fullmatch(r"\.\.?/[\w./-]+\.js", imp) and "/v4/" not in imp and "paperbot" not in imp, (f, imp)
    css = open(CSS).read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", css)
    for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", css):
        assert "var(--t-" in m.group(1) or re.search(r"calc\(\d+px \* var\(--ts\)\)", m.group(1)) or m.group(1).strip() == "inherit", m.group(0)
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for sel_block in re.findall(r"([^{}]+)\{[^{}]*\}", body):
        sel = sel_block.strip()
        if not sel or sel.startswith("@") or re.match(r"^(\d+%|from|to)(\s*,\s*(\d+%|from|to))*$", sel):
            continue
        for part in sel.split(","):
            part = part.strip()
            if not part or part.startswith("@media"):
                continue
            part = re.sub(r'^(:root:not\(\[data-skin="classic"\]\)|html\[data-text="\w+"\])\s+', "", part)
            assert re.match(r"^([a-z]+)?\.tm", part) or part.startswith('.screen[data-screen="terminal"]'), part
    own = set(re.findall(r"\.(tm-[\w-]+)", css))
    assert {"tm-p", "tm-top", "tm-band", "tm-coins", "tm-chart", "tm-chip", "tm-t", "tm-pcard", "tm-fr", "tm-cr", "tm-psvg", "tm-cal"} <= own
    for cls in re.findall(r'class: (?:\[)?"(tm-[\w-]+)', "".join(open(os.path.join(JS, "screens", f)).read() for f in OWN_JS)):
        assert cls in own, cls
    term = open(os.path.join(JS, "screens", "terminal.js")).read()
    assert 'export const css = "scr/terminal.css"' in term and "export const wide = true" in term
    # the shell's own terminal routes stay as they were (the menu's first button, the links into it)
    app = open(os.path.join(JS, "app.js")).read()
    assert 'terminal: "terminal"' in app


def test_served_behind_login(tmp_path):
    """The new modules and the stylesheet are static files of the dashboard, served only after the login."""
    from fastapi.testclient import TestClient

    from candleague import dash as D
    from candleague.live import Live
    files = ["scr/terminal.css"] + [f"js/screens/{f}" for f in OWN_JS]
    for f in files:
        assert f in D.STATIC_FILES, f
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(D.create_app(str(snap), D.hash_password("pw-123"), b"x" * 32, live=Live(mode="fake")), base_url="http://league.test")
    assert c.get("/static/scr/terminal.css").status_code == 404
    form = {"content-type": "application/x-www-form-urlencoded", "origin": "http://league.test"}
    assert c.post("/login", content="password=pw-123", follow_redirects=False, headers=form).status_code == 303
    r = c.get("/static/scr/terminal.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    for f in files[1:]:
        assert c.get(f"/static/{f}").status_code == 200, f
