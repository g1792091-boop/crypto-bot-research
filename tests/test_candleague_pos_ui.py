"""후보 리그 포지션 screen (candleague/static/js/screens/positions*.js, fills.js, static/scr/positions.css), in the rule
bot's v4 look: the cards, the 위험 사다리, the 손절·잠금 주문 and 체결 기록 tabs.

The screen itself runs here under node on a tiny DOM stand-in (no browser): the summary sums what the live mark says, a
hidden DeepSeek position (D11) is counted only and never shows a number even when a field slipped through, the engine's
catch-up and an old record hide the live P&L and say why, a new mark repaints the cards (live refresh), the empty and
not-yet-written answers say so. Static checks: text only through dom.js (no HTML strings), the stylesheet uses tokens and
var(--t-*) sizes only and its own ps- prefix under .ps-scr, the screen modules are served behind the login."""

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
OWN_JS = ("positions.js", "positions-card.js", "positions-risk.js", "positions-orders.js", "fills.js")
CSS = os.path.join(STATIC, "scr", "positions.css")

# A minimal DOM for node: elements, text, fragments, classes, attributes, events and a class-selector query; enough for
# dom.js h()/s()/put() and the screen. Every string the screen adds arrives as a T (text) node, so textContent below is
# exactly what a viewer reads.
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
  addEventListener(t, f) { (this.ev[t] ||= []).push(f); }
  removeEventListener() {}
  fire(t) { for (const f of this.ev[t] || []) f({target: this, key: "Enter", preventDefault() {}, stopPropagation() {}}); }
  click() { this.fire("click"); }
  focus() {} scrollIntoView() {}
  get offsetWidth() { return 0; }
  matches(sel) {
    const m = /^([a-z]*)((?:\.[\w-]+)*)$/i.exec(sel.trim());
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
  addEventListener() {}};
globalThis.window = {addEventListener() {}};
globalThis.location = {hash: "", search: ""};
globalThis.getComputedStyle = () => ({getPropertyValue: () => "", backgroundColor: "", flexWrap: "wrap"});
globalThis.WIDE = false;
globalThis.matchMedia = (q) => ({matches: /reduced-motion/.test(q) ? true : /min-width: 1280/.test(q) ? globalThis.WIDE : false,
  addEventListener() {}, removeEventListener() {}});
globalThis.requestAnimationFrame = (f) => setTimeout(() => f(Date.now()), 0);
globalThis.cancelAnimationFrame = () => {};
const store = {};
globalThis.localStorage = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; }};
// the server: /api/live, /api/positions, /api/klines, /api/fills, /api/meta answered from globalThis.API
globalThis.API = {};
globalThis.fetch = async (path) => {
  const key = Object.keys(globalThis.API).find((k) => String(path).startsWith(k));
  const body = key ? (typeof globalThis.API[key] === "function" ? globalThis.API[key](path) : globalThis.API[key]) : null;
  return {ok: !!key, status: key ? 200 : 404, json: async () => body};
};
globalThis.tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
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
const C = await import("{url('screens/positions-card.js')}");
const R = await import("{url('screens/positions-risk.js')}");
const O = await import("{url('screens/positions-orders.js')}");
const P = await import("{url('screens/positions.js')}");
const FL = await import("{url('screens/fills.js')}");
let out = {{}};
{body}
console.log(JSON.stringify(out));
process.exit(0);
"""
    f = tmp_path / "pos_ui_test.mjs"
    f.write_text(code)
    r = subprocess.run([_node(), str(f)], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


# ------------------------------------------------------------------------------------------------ the shared fixture
# now = 2026-10-11 12:00 KST. BTC long 30x (qty 0.1 @ 100,000, margin 333.33), ETH short 1/4 40x, one hidden DeepSeek
# position whose money fields "slipped through" (the client must still show none of them), one DeepSeek position the
# server legitimately nulled.
FIXTURE = r"""
const NOW = Date.now();
const pos = (o) => ({pick: null, of: null, role: "cand", kind: "core", name: "DOGE", tf: "1h", exit: "tp3R|4", exit_ko: "고정 익절 3R · 손절 4 ATR",
  size: 1, trades: 12, wins: 7, bust: false, hidden: false, stop_is_lock: false, tp: null, tp_pnl: null, why: null, ...o});
const P1 = pos({id: "core-DOGE-1h-1", coin: "BTCUSD", symbol: "BTCUSDT", side: 1, since: NOW - 3 * 3600e3, lev: 30, entry: 100000, stop: 98000,
  tp: 106000, qty: 0.1, notional: 10000, margin: 333.33, margin_pct: 0.1993, liq: 96900, liq_dist_entry: 0.031, wallet: 5100, equity_at_entry: 5102,
  stop_pnl: -200, stop_roe: -0.6, tp_pnl: 600,
  why: {group_ko: null, head_ko: "x", lev_ko: "보통 자리 첫 배수 30배 그대로", sub_ko: "후보: 커스텀값 · 규칙봇과 같은 배수 규칙", rule_ko: "규칙: ..."}});
const P2 = pos({id: "core-OBV_S-1h-3-q", role: "quarter", size: 0.25, name: "OBV_S", coin: "ETHUSD", symbol: "ETHUSDT", side: -1, since: NOW - 3600e3, lev: 40,
  entry: 2500, stop: 2450, stop_is_lock: true, qty: 1, notional: 2500, margin: 62.5, margin_pct: 0.0126, liq: 2560, liq_dist_entry: 0.024,
  stop_pnl: 50, stop_roe: 0.8, exit: "ladder|2", exit_ko: "계단 잠금 10%부터 · 손절 2 ATR"});
const LEAK = pos({id: "ds-F5_BOX-15m-1", kind: "ds", name: "F5_BOX", tf: "15m", coin: "BTCUSD", symbol: "BTCUSDT", side: -1, since: NOW - 7200e3, hidden: true,
  lev: 50, entry: 123456.7, stop: 124999.9, qty: 7.777, margin: 4321.09, liq: 125432.1, stop_pnl: -987.65, wallet: 6543.21,
  why: {group_ko: "좋은 자리", lev_ko: "좋은 자리 첫 배수 50배 그대로", sub_ko: "", rule_ko: ""}});
const HID = pos({id: "base-ds-F1_PVT_DIV-1h", role: "base", kind: "ds", name: "F1_PVT_DIV", coin: "SOLUSD", symbol: "SOLUSDT", side: 1, since: NOW - 600e3,
  hidden: true, lev: null, entry: null, stop: null, qty: null, margin: null, liq: null});
const doc = (o = {}) => ({ds_money: false, exact: false, brackets: "exchange.json", generated_ms: NOW - 60e3, done_ms: NOW - 120e3,
  start_ms: NOW - 10 * 86400e3, started_ms: NOW - 2 * 86400e3, server_ms: NOW, snap_age_s: 60, lag_s: 120, catching_up: false, old: false,
  positions: [P1, P2, LEAK, HID], counts: {open: 4, long: 2, short: 2, hidden: 2, by_coin: {}, by_role: {}, by_kind: {}}, ...o});
const live = (btc, eth) => ({generated_ms: Date.now(), server_ms: Date.now(), source: "binance", stale: false,
  coins: [{coin: "BTCUSD", price: btc, mark: btc, ok: true}, {coin: "ETHUSD", price: eth, mark: eth, ok: true}, {coin: "SOLUSD", price: 150, mark: 150, ok: true}]});
const bars = (path) => { const t = [], c = []; for (let i = 0; i < 288; i++) { t.push(Math.floor((NOW - (288 - i) * 300e3) / 300e3) * 300e3); c.push(100000 + i); } return {bars: {t, o: c, h: c, l: c, c}}; };
const fills = {fills: [
  {symbol: "BTCUSDT", side: 1, entry_time: NOW - 9e6, entry_price: 99000, exit_time: NOW - 6e6, exit_price: 99500, exit_reason: "TP", leverage: 30, pnl: 150.5, roe: 0.45, account: "core-DOGE-1h-1"},
  {symbol: "SOLUSDT", side: -1, entry_time: NOW - 9e6, entry_price: null, exit_time: NOW - 5e6, exit_price: null, exit_reason: "SL", leverage: 30, pnl: null, roe: null, win: false, account: "ds-F5_BOX-15m-1"},
  {symbol: "ETHUSDT", side: -1, entry_time: NOW - 8e6, entry_price: 2600, exit_time: NOW - 4e6, exit_price: 2650, exit_reason: "LIQ", leverage: 40, pnl: -62.5, roe: -1, account: "core-OBV_S-1h-3-q"}]};
const ctxOf = (q = {}) => ({params: {name: "positions", arg: null, query: q}, alive: () => true, signal: {},
  api: async (p) => (await fetch(p)).json(), meta: async () => ({}), onLeague() {}, onLive: (fn) => L.onLive(fn), onPositions: (fn) => K.onPositions(fn),
  every() {}, setTitle() {}, setQuery() {}, css: async () => {}, wide() {},
  href: (n, a, q2) => `#/${n}${a ? "/" + encodeURIComponent(a) : ""}${q2 ? "?" + new URLSearchParams(q2) : ""}`});
const mountOn = async (d, lv, q) => {
  API["/api/positions"] = d; API["/api/live"] = lv; API["/api/klines"] = bars; API["/api/fills"] = fills; API["/api/meta"] = {};
  const el = document.createElement("div");
  document.body.append(el);
  await P.mount(el, ctxOf(q));
  await tick(60); await L.liveRefresh(); await tick(60);
  return el;
};
const text = (el, sel) => el.querySelectorAll(sel).map((x) => x.textContent);
"""


def test_live_numbers_sums_and_refresh(tmp_path):
    """BTC long +100.00 at mark 101,000 (0.1 x 1,000), ETH short −50.00 at 2,550; the summary of 묶음 '전체' adds the two
    shown ones only (+50.00 over 395.83 margin) and counts the two DeepSeek ones apart; a new mark repaints the card."""
    o = _run(tmp_path, FIXTURE + r"""
localStorage.setItem("cl-ps-grp", JSON.stringify("all"));
const el = await mountOn(doc(), live(101000, 2550));
const card = el.querySelectorAll("article.ps-card").find((c) => c.textContent.includes("BTCUSDT · 격리 30배"));
out.btcLed = card.querySelector("b.led-num").textContent;
out.btcRoi = card.querySelector("b.led-sm").textContent;
out.sum = el.querySelector("section.ps-sum").textContent;
out.tab = el.querySelector("div.ps-tabs").textContent;
out.coins = el.querySelector("div.ps-coins").textContent;
out.ladder = text(el, "a.ps-risk-row");
out.why = card.querySelector("div.ps-why").textContent;
out.stop = card.textContent.includes("손절에 닿으면 −200.00 USDT (ROI −60.0%)");
out.spark = !card.querySelector("div.ps-spark").hidden;
out.order = el.querySelectorAll("article.ps-card").map((c) => c.getAttribute("aria-label"));
API["/api/live"] = live(102000, 2550);                       // a new mark: +200.00
await L.liveRefresh(); await tick(60);
out.btcLed2 = card.querySelector("b.led-num").textContent;
out.sum2 = el.querySelector("section.ps-sum").textContent;
""")
    assert o["btcLed"] == "+100.00" and o["btcRoi"] == "+30.00%"
    assert "+50.00" in o["sum"] and "묶인 증거금 대비 +12.63%" in o["sum"]          # 50 / (333.33 + 62.5)
    assert "롱 · 숏2 · 2" in o["sum"] and "열린 4개 · 전체" in o["sum"]
    assert "수익 중 1 · 손실 중 1" in o["sum"] and "묶인 증거금 395.83 USDT" in o["sum"]
    assert "딥시크 2개 (개수만, 합계에서 뺌)" in o["sum"]
    assert o["tab"].startswith("포지션 4") and "BTC1↑ 1↓" in o["coins"]
    assert len(o["ladder"]) == 2                                   # the hidden ones are not in the ladder
    assert "증거금 20%" in o["why"] and "진입 때 청산까지 3.1%" in o["why"] and "보통 또는 좋은 자리 · 30배" in o["why"]
    assert o["stop"] and o["spark"]
    assert all("개수만" in x for x in o["order"][-2:])              # count-only cards last, whatever the sort
    assert o["btcLed2"] == "+200.00" and "+150.00" in o["sum2"]     # live refresh


def test_hidden_deepseek_never_shows_money(tmp_path):
    """D11: a hidden position shows side, coin, time, name and rule only, even when money fields slipped through; the
    딥시크 묶음 sums nothing; 손절·잠금 주문 and the 체결 기록 rows leave hidden ones out of every number."""
    o = _run(tmp_path, FIXTURE + r"""
localStorage.setItem("cl-ps-grp", JSON.stringify("ds"));
LKm.setLeague({ds_money: false, accounts: [{id: "core-DOGE-1h-1", role: "cand", kind: "core", name: "DOGE", tf: "1h"},
  {id: "core-OBV_S-1h-3-q", role: "quarter", kind: "core", name: "OBV_S", tf: "1h", of: "core-OBV_S-1h-3"},
  {id: "ds-F5_BOX-15m-1", role: "cand", kind: "ds", name: "F5_BOX", tf: "15m"}]});
const el = await mountOn(doc(), live(101000, 2550));
out.cards = el.querySelectorAll("article.ps-card").map((c) => ({hid: c.classList.contains("ps-hidden"), t: c.textContent}));
out.sum = el.querySelector("section.ps-sum").textContent;
out.ladder = el.querySelector("section.ps-risk").textContent;
const tabs = el.querySelector("div.ps-tabs").querySelectorAll("button");
tabs[1].click(); await tick(30);
out.orders = el.querySelectorAll("div.ps-orow").length;
tabs[2].click(); await tick(80);
const per = el.querySelectorAll("div.ps-filters")[0].querySelectorAll("button").find((b) => b.textContent === "최근 300건");
per.click(); await tick(20);
out.trows = el.querySelectorAll("div.ps-trow").map((r) => ({hid: r.classList.contains("ps-hid"), t: r.textContent}));
out.tsum = el.querySelector("p.ps-sumline").textContent;
const row = O.fillRow(fills.fills[1], {id: "ds-F5_BOX-15m-1", kind: "ds", role: "cand", name: "F5_BOX", tf: "15m"});
out.row = row.textContent;
out.sumsHidden = (({coins, ...x}) => x)(K.sums([LEAK, HID], () => 101000));
""")
    secrets = ("123,456", "123456", "124,999", "7.777", "4,321", "4321", "125,432", "987.65", "6,543", "50배", "좋은 자리")
    assert len(o["cards"]) == 2 and all(c["hid"] for c in o["cards"])
    for c in o["cards"]:
        assert "개수만" in c["t"] and "배수 숨김" in c["t"]
        for s in secrets:
            assert s not in c["t"], (s, c["t"])
        assert "USDT ·" not in c["t"].replace("BTCUSDT ·", "").replace("SOLUSDT ·", "")
    assert "딥시크 금액 숨김" in o["sum"] and "딥시크 2개" in o["sum"] and "+" not in o["sum"].split("롱 · 숏")[0]
    assert "사다리에 없습니다" in o["ladder"] and o["orders"] == 0
    assert len(o["trows"]) == 1 and o["trows"][0]["hid"]                 # the 딥시크 묶음 follows the screen's 묶음
    t0 = o["trows"][0]["t"]
    assert "개수만" in t0 and "30배" not in t0 and "ROE" not in t0 and "USDT" not in t0
    assert o["tsum"].startswith("0건 · 합계 0.00 USDT") and "딥시크 1건 (개수만, 합계에서 뺌)" in o["tsum"]
    assert "개수만" in o["row"] and not re.search(r"\d+\.\d+|USDT|%", o["row"].replace("15분", ""))
    t = o["sumsHidden"]
    assert t["n"] == 2 and t["hidden"] == 2 and t["pnl"] == 0 and t["margin"] == 0 and t["priced"] == 0


def test_catchup_old_empty_and_missing(tmp_path):
    """While the engine replays from 10/01 (or its record is over 15 minutes old) no live P&L or distance is shown and the
    screen says why; the ladder falls back to the entry-time distances. No position at all, or no record yet: said so."""
    o = _run(tmp_path, FIXTURE + r"""
localStorage.setItem("cl-ps-grp", JSON.stringify("all"));
let el = await mountOn(doc({catching_up: true}), live(101000, 2550));
const card = el.querySelectorAll("article.ps-card").find((c) => c.textContent.includes("BTCUSDT · 격리 30배"));
out.catch = {led: card.querySelector("b.led-num").textContent, note: card.querySelector("small.ps-lednote").textContent,
  banner: el.querySelector("div.ps-banner").textContent, sum: el.querySelector("section.ps-sum").textContent,
  ladder: el.querySelector("section.ps-risk").textContent, mark: card.querySelector("dl.kv").textContent};
el.remove();
API["/api/positions"] = doc({old: true});
await K.kickPositions(); await tick(60);
el = await mountOn(doc({old: true}), live(101000, 2550));
out.old = {banner: el.querySelector("div.ps-banner").textContent,
  note: el.querySelectorAll("small.ps-lednote").map((x) => x.textContent).filter(Boolean)[0]};
el.remove();
API["/api/positions"] = doc({positions: [], counts: {open: 0, long: 0, short: 0, hidden: 0, by_coin: {}}});
await K.kickPositions(); await tick(60);
el = await mountOn(doc({positions: [], counts: {open: 0, long: 0, short: 0, hidden: 0, by_coin: {}}}), live(101000, 2550));
out.empty = el.querySelector("div.ps-empty").textContent;
el.remove();
API["/api/positions"] = {status: "준비 중", positions: [], counts: null};
await K.kickPositions(); await tick(60);
el = await mountOn({status: "준비 중", positions: [], counts: null}, live(101000, 2550));
out.missing = el.textContent.includes("준비 중") && !el.querySelector("article.ps-card");
""")
    c = o["catch"]
    assert c["led"] == "—" and c["note"] == "엔진이 따라잡는 중"
    assert "10/01부터 다시 계산 중" in c["banner"] and "엔진이 따라잡는 중: 실시간 손익 감춤" in c["sum"]
    assert "진입 때 거리" in c["ladder"] and "청산 3.10%" in c["ladder"]          # liq 96,900 from the entry 100,000
    assert "따라잡은 뒤" in c["mark"] and "101,000" not in c["mark"]
    assert "엔진 기록이" in o["old"]["banner"] and o["old"]["note"] == "엔진 기록이 멈춤"
    assert "지금 열린 포지션이 없습니다" in o["empty"]
    assert o["missing"]


def test_pieces_rules_and_order(tmp_path):
    """The exit rule words per rule code, the 왜 N배 margin share, the risk order (closest to liquidation first, hidden
    left out), the order list, the sort that keeps count-only rows last."""
    o = _run(tmp_path, FIXTURE + r"""
out.tp = C.exitPlain(P1).textContent;
out.ladder = C.exitPlain(P2).textContent;
out.roe = C.exitPlain(pos({exit: "roe50|4", exit_ko: "고정 익절 수익 50% · 손절 4 ATR", tp: 101.5, entry: 100, lev: 30, side: 1})).textContent;
out.whyQ = C.whyBox(P2).textContent;
const marks = {BTCUSD: 97500, ETHUSD: 2400}, marks2 = {BTCUSD: 99000, ETHUSD: 2400};
out.risk = R.rankRisk([P2, LEAK, P1, HID], (c) => marks[c] ?? null).map((x) => [x.p.id, Math.round(x.dLiq * 1e4)]);
out.orders = O.orderList([P2, P1, LEAK, HID], (c) => marks2[c] ?? null).map((x) => x.p.id);
out.ordersEntry = O.orderList([P2, P1], null, false).map((x) => [x.p.id, Math.round(x.d * 1e4)]);
const pnl = {"core-DOGE-1h-1": 5, "core-OBV_S-1h-3-q": 9};
out.sort = P.sortPositions([LEAK, P1, HID, P2], "pnl", (p) => pnl[p.id] ?? null, () => null).map((p) => p.id);
out.sortLoss = P.sortPositions([LEAK, P1, HID, P2], "loss", (p) => pnl[p.id] ?? null, () => null).map((p) => p.id);
out.line = C.priceLine([1, 2, 3], {base: 2, refs: [{v: 100, cls: "stopl"}], clip: true}).dropped.length;
out.kst = O.kstMidnight(Date.UTC(2026, 9, 10, 16, 30)) === Date.UTC(2026, 9, 10, 15, 0);
""")
    assert "손절 거리(R)의 3배" in o["tp"] and "(106,000.0)" in o["tp"]
    assert "잠금 중" in o["ladder"] and "+12%" in o["ladder"] and "+10% 자리" in o["ladder"] and "5%씩" in o["ladder"]
    assert "순 ROE +50%에 닿으면 익절" in o["roe"] and "(가격 101.50)" in o["roe"]
    assert "증거금 1.3%" in o["whyQ"] and "40배" in o["whyQ"]
    assert o["risk"] == [["core-DOGE-1h-1", 62], ["core-OBV_S-1h-3-q", 667]]       # 0.62 % from liq vs 6.67 %
    assert o["orders"] == ["core-DOGE-1h-1", "core-OBV_S-1h-3-q"]                  # 1.01 % vs 2.08 % from the stop
    assert o["ordersEntry"] == [["core-OBV_S-1h-3-q", -200], ["core-DOGE-1h-1", 200]]   # not live: from the entry
    assert o["sort"][:2] == ["core-OBV_S-1h-3-q", "core-DOGE-1h-1"] and set(o["sort"][2:]) == {LEAK_ID, HID_ID}
    assert o["sortLoss"][:2] == ["core-DOGE-1h-1", "core-OBV_S-1h-3-q"] and set(o["sortLoss"][2:]) == {LEAK_ID, HID_ID}
    assert o["line"] == 1 and o["kst"]


LEAK_ID, HID_ID = "ds-F5_BOX-15m-1", "base-ds-F1_PVT_DIV-1h"


def test_fills_screen_rows_and_table(tmp_path):
    """#/fills: the rule-bot rows by default (with the sum line that leaves hidden trades out), the dense table on 표."""
    o = _run(tmp_path, FIXTURE + r"""
API["/api/fills"] = fills; API["/api/live"] = live(101000, 2550);
const el = document.createElement("div"); document.body.append(el);
await FL.mount(el, {...ctxOf(), params: {name: "fills", arg: null, query: {}}});
await tick(80);
out.rows = el.querySelectorAll("div.ps-trow").length;
out.sum = el.querySelector("p.ps-sumline").textContent;
const seg = el.querySelector("div.scr-head").querySelectorAll("button");
seg.find((b) => b.textContent === "표").click(); await tick(80);
out.table = el.querySelectorAll("table.tbl").length + el.querySelectorAll("table").length;
out.hiddenCell = el.textContent.includes("숨김");
""")
    assert o["rows"] == 3 and "2건 · 합계 +88.00 USDT" in o["sum"] and "딥시크 1건" in o["sum"]
    assert o["table"] >= 1 and o["hiddenCell"]


def test_text_only_tokens_and_prefix():
    """No HTML from strings in the screen's modules; the stylesheet: colours from the tokens, sizes var(--t-*), every
    rule under .ps-scr and every own class ps-."""
    for f in OWN_JS:
        src = open(os.path.join(JS, "screens", f)).read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval("):
            assert bad not in src, (f, bad)
        for imp in re.findall(r'^import .* from "([^"]+)";', src, re.M):         # copied from the rule bot, never imported
            assert re.fullmatch(r"\.\.?/[\w./-]+\.js", imp) and "/v4/" not in imp and "paperbot" not in imp, (f, imp)
    css = open(CSS).read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", css)
    for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", css):
        assert "var(--t-" in m.group(1) or m.group(1).strip() == "inherit", m.group(0)
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for sel_block in re.findall(r"([^{}]+)\{[^{}]*\}", body):
        sel = sel_block.strip()
        if not sel or sel.startswith("@") or re.match(r"^(\d+%|from|to)(\s*,\s*(\d+%|from|to))*$", sel):
            continue
        for part in sel.split(","):
            part = part.strip()
            if part.startswith("@media") or not part:
                continue
            assert part.startswith(".ps-scr"), part
    own = set(re.findall(r"\.(ps-[\w-]+)", css))
    assert {"ps-card", "ps-row", "ps-risk-row", "ps-why", "ps-spark", "ps-meter", "ps-skew", "ps-trow"} <= own
    pos = open(os.path.join(JS, "screens", "positions.js")).read()
    assert 'export const css = "scr/positions.css"' in pos
    assert 'export const css = "scr/positions.css"' in open(os.path.join(JS, "screens", "fills.js")).read()


def test_served_behind_login(tmp_path):
    """The new modules and the stylesheet are static files of the dashboard, served only after the login."""
    from fastapi.testclient import TestClient

    from candleague import dash as D
    from candleague.live import Live
    for f in ("scr/positions.css", "js/screens/positions-card.js", "js/screens/positions-risk.js", "js/screens/positions-orders.js"):
        assert f in D.STATIC_FILES, f
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(D.create_app(str(snap), D.hash_password("pw-123"), b"x" * 32, live=Live(mode="fake")), base_url="http://league.test")
    assert c.get("/static/scr/positions.css").status_code == 404
    form = {"content-type": "application/x-www-form-urlencoded", "origin": "http://league.test"}
    assert c.post("/login", content="password=pw-123", follow_redirects=False, headers=form).status_code == 303
    r = c.get("/static/scr/positions.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert c.get("/static/js/screens/positions-card.js").status_code == 200
