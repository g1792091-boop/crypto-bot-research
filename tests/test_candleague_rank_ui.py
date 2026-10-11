"""candleague 순위표 (js/screens/rank*.js, static/scr/rank.css): the rule bot's v4 board for the 후보 리그.

The screen is mounted for real under node with a small DOM (text nodes only, like the browser's) on a synthetic
league snapshot, and the tests read what reached the page:
  * the four 묶음 cards, the tiles, 상위·하위 by 잔고 수익률 (D-3), the 동전 ▲▼ marks on 한 번 평균 (참고), 표본 적음,
    the 2순위 mark, the small balance lines, the "아직 거래 없는 계좌" line;
  * the open-position pill's live ROE after a price tick, and no ROE while the engine replays from 10/01 or its record
    is over 15 minutes old (with the banner);
  * the ▲▼ rank arrows against the viewer's last visit (localStorage);
  * D11: with the snapshot's DeepSeek money switch off, no DeepSeek money anywhere (rows, cards, pills, sparks, table,
    봉별 요약, CSV), even when the snapshot (wrongly) still carries the numbers; counts and labels stay.
Plus the static rules: text only (no HTML parsing), colours only from the tokens, font sizes only var(--t-*)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
STATIC = os.path.join(ROOT, "candleague", "static")
RANK_JS = ["rank.js", "rank-cards.js", "rank-rows.js", "rank-table.js"]
DAY = 86_400_000

# ---------------------------------------------------------------- a small DOM for node (text nodes only)
SHIM = r"""
class Node {
  constructor() { this.childNodes = []; this.parentNode = null; }
  get firstChild() { return this.childNodes[0] || null; }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  appendChild(n) {
    if (n.nodeType === 11) { for (const c of [...n.childNodes]) this.appendChild(c); return n; }
    if (n.parentNode) n.parentNode._rm(n);
    n.parentNode = this; this.childNodes.push(n); return n;
  }
  _rm(n) { const i = this.childNodes.indexOf(n); if (i >= 0) this.childNodes.splice(i, 1); n.parentNode = null; }
  append(...ns) { for (const n of ns) this.appendChild(n !== null && typeof n === "object" ? n : new Text(String(n))); }
  prepend(...ns) { const keep = this.childNodes.splice(0); for (const k of keep) k.parentNode = null; this.append(...ns, ...keep); }
  replaceChildren(...ns) { for (const c of this.childNodes) c.parentNode = null; this.childNodes = []; this.append(...ns); }
  remove() { if (this.parentNode) this.parentNode._rm(this); }
  contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === globalThis.document; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(); if (v !== "" && v != null) this.appendChild(new Text(String(v))); }
  addEventListener() {} removeEventListener() {}
}
class Text extends Node {
  constructor(t) { super(); this.nodeType = 3; this.data = t; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
}
const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
class Element extends Node {
  constructor(tag) {
    super(); this.nodeType = 1; this.tagName = tag.toUpperCase(); this.localName = tag.toLowerCase();
    this.attrs = new Map(); this.dataset = {}; this.listeners = {};
    this.style = {setProperty(k, v) { this[k] = v; }};
    const me = this;
    const set = () => new Set((me.attrs.get("class") || "").split(/\s+/).filter(Boolean));
    const put = (s) => me.attrs.set("class", [...s].join(" "));
    this.classList = {
      add: (...c) => { const s = set(); c.forEach((x) => s.add(x)); put(s); },
      remove: (...c) => { const s = set(); c.forEach((x) => s.delete(x)); put(s); },
      toggle: (c, on) => { const s = set(); const v = on === undefined ? !s.has(c) : !!on; if (v) s.add(c); else s.delete(c); put(s); return v; },
      contains: (c) => set().has(c),
    };
  }
  get className() { return this.attrs.get("class") || ""; }
  set className(v) { this.attrs.set("class", String(v)); }
  get hidden() { return this.attrs.has("hidden"); }
  set hidden(v) { if (v) this.attrs.set("hidden", ""); else this.attrs.delete("hidden"); }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  hasAttribute(k) { return this.attrs.has(k); }
  removeAttribute(k) { this.attrs.delete(k); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  removeEventListener(t, f) { this.listeners[t] = (this.listeners[t] || []).filter((x) => x !== f); }
  fire(t, ev = {}) { for (const f of this.listeners[t] || []) f({target: this, key: "", preventDefault() {}, stopPropagation() {}, ...ev}); }
  focus() {} animate() { return {cancel() {}}; }
  get offsetWidth() { return 0; }
  attr(name) {
    if (name === "class") return this.className;
    if (name.startsWith("data-")) { const k = camel(name.slice(5)); return this.dataset[k] != null ? String(this.dataset[k]) : this.getAttribute(name); }
    return this.getAttribute(name);
  }
  one(c) {
    const m = /^([a-zA-Z0-9]*)((?:\.[\w-]+|\[[^\]]+\])*)$/.exec(c);
    if (!m) throw new Error("selector " + c);
    if (m[1] && m[1].toLowerCase() !== this.localName) return false;
    for (const p of m[2].match(/\.[\w-]+|\[[^\]]+\]/g) || []) {
      if (p[0] === ".") { if (!this.classList.contains(p.slice(1))) return false; continue; }
      const a = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(p);
      const v = this.attr(a[1]);
      if (v == null || (a[2] !== undefined && v !== a[2])) return false;
    }
    return true;
  }
  matches(sel) {
    return sel.split(",").some((alt) => {
      const parts = alt.trim().split(/\s+/);
      if (!this.one(parts[parts.length - 1])) return false;
      let n = this.parentNode, i = parts.length - 2;
      while (i >= 0 && n && n.nodeType === 1) { if (n.one(parts[i])) i--; n = n.parentNode; }
      return i < 0;
    });
  }
  closest(sel) { let n = this; while (n && n.nodeType === 1) { if (n.matches(sel)) return n; n = n.parentNode; } return null; }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => { for (const c of n.childNodes) if (c.nodeType === 1) { if (c.matches(sel)) out.push(c); walk(c); } };
    walk(this); return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
class Frag extends Node { constructor() { super(); this.nodeType = 11; } }

export function install(cfg) {
  const doc = new Node();
  doc.nodeType = 9;
  doc.createElement = (t) => new Element(t);
  doc.createElementNS = (_ns, t) => new Element(t);
  doc.createTextNode = (t) => new Text(String(t));
  doc.createDocumentFragment = () => new Frag();
  doc.visibilityState = "visible"; doc.hidden = false;
  const html = new Element("html");
  html.dataset.motion = "less";                       // every one-shot animation is skipped (v4kit reduced())
  doc.appendChild(html);
  doc.documentElement = html;
  doc.head = new Element("head"); doc.body = new Element("body");
  html.append(doc.head, doc.body);
  globalThis.Node = Node;
  globalThis.document = doc;
  const store = new Map(Object.entries(cfg.local || {}));
  globalThis.localStorage = {getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k)};
  globalThis.requestAnimationFrame = () => 0;
  globalThis.cancelAnimationFrame = () => {};
  globalThis.getComputedStyle = () => ({getPropertyValue: () => "", backgroundColor: "", flexWrap: "wrap"});
  globalThis.location = {hash: "#/rank", href: "/"};
  globalThis.history = {replaceState() {}};
  globalThis.fetch = async (path) => {
    const key = String(path).split("?")[0];
    if (!(key in cfg.routes)) return {ok: false, status: 404, json: async () => ({})};
    return {ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(cfg.routes[key]))};
  };
  return store;
}
export const txt = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : null);
"""

RUNNER = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const store = install(cfg);
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
const live = await import(`file://${S}/js/live.js`);
const R = await import(`file://${S}/js/screens/rank.js`);
const T = await import(`file://${S}/js/screens/rank-table.js`);
const C = await import(`file://${S}/js/screens/rank-cards.js`);
const W = await import(`file://${S}/js/screens/rank-rows.js`);
const doc = cfg.routes["/api/league"];
LK.setLeague(doc);
const el = document.createElement("div");
el.dataset.screen = "rank";
document.body.appendChild(el);
const lives = [], out = {query: null};
const ctx = {params: {name: "rank", arg: null, query: cfg.query || {}}, alive: () => true, signal: null,
  api: async (p) => (await globalThis.fetch(p)).json(), meta: () => LK.getMeta(),
  onLeague: (fn) => fn(doc), onLive: (fn) => { lives.push(fn); return () => {}; }, onPositions: () => () => {},
  every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery: (q) => { out.query = q; },
  href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
const tick = () => new Promise((r) => setTimeout(r, 15));
await R.mount(el, ctx);
await tick();
if (cfg.live) { await live.liveRefresh(); for (const f of lives) f(live.liveDoc()); }
function collect() {
  const rows = el.querySelectorAll(".rk-row").map((r) => ({id: r.dataset.id, top: !!r.closest(".rk-tb"), rk: txt(r.querySelector(".rk")),
    ret: txt(r.querySelector(".ret")), meta: txt(r.querySelector(".meta")), name: txt(r.querySelector(".lname")),
    spark: !!r.querySelector(".rk-spark"), pill: r.querySelector(".kp-pill") ? txt(r.querySelector(".kp-pill")) : null,
    label: r.getAttribute("aria-label"), href: r.getAttribute("href")}));
  return {rows, cards: el.querySelectorAll(".rk-gcard").map(txt), pressed: el.querySelectorAll(".rk-gcard").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.dataset.group),
    tiles: txt(el.querySelector(".rk-stats")), banner: txt(el.querySelector(".rk-banner")), live: txt(el.querySelector(".rk-live")),
    note: txt(el.querySelector(".rk-monote")), foot: txt(el.querySelector(".rk-tbfoot")), count: txt(el.querySelector(".rk-count")),
    table: el.querySelectorAll(".rk-table tbody tr").map(txt), tf: txt(el.querySelector(".rk-tf")), page: txt(el)};
}
const res = {first: collect(), steps: {}};
for (const step of cfg.steps || []) {
  const b = el.querySelector(step.click);
  if (!b) throw new Error("no " + step.click);
  b.fire("click");
  await tick();
  res.steps[step.name] = collect();
}
const d = doc, ix = LK.index(d);
const all = C.ranking(d, d.accounts);
res.csv = T.csvRows(d, ix, all.shown.concat(all.waiting, all.hid), all.rank);
res.csvHead = T.CSV_HEAD;
res.query = out.query;
res.memo = store.get("cl-rank-memo") ? JSON.parse(store.get("cl-rank-memo")) : null;
res.groupFromQuery = [{g: "ds"}, {g: "cmp", sub: "base"}, {g: "nope"}, {role: "flip"}, {role: "quarter"}, {role: "cand", kind: "ds"}, {}].map((q) => R.groupFromQuery(q));
const order = W.sortRows(d.accounts.filter((a) => C.inGroup(a, "all")), "ret", d, all.rank).map((a) => a.id);
res.sorted = order;
console.log(JSON.stringify(res));
"""


# ---------------------------------------------------------------- a synthetic league snapshot
def _acct(pid, role, kind, name, tf, trades, wins, mean, wallet, dd, open_=None, rank=1, bust=False):
    aid = {"cand": pid, "quarter": pid + "-q", "exitonly": pid + "-x", "flip": pid + "-flip",
           "base": f"base-{kind}-{name}-{tf}"}[role]
    return {"id": aid, "role": role, "kind": kind, "name": name, "tf": tf, "exit": "tp3R|2", "exit_ko": "고정 익절 3R · 손절 2 ATR",
            "combo": {}, "of": None if role in ("cand", "base") else pid, "size": 0.25 if role == "quarter" else 1.0,
            "source": {"rank": rank}, "trades": trades, "wins": wins, "mean_ret": mean, "wallet": wallet, "max_dd": dd,
            "bust": bust, "open": open_}


def _pos(sym, side, entry, lev, now):
    return {"symbol": sym, "side": side, "entry": entry, "stop": entry * (1 - 0.01 * side), "tp": entry * (1 + 0.03 * side),
            "since": now - 3_600_000, "lev": lev}


def _league(now, ds_money=True, leak=False, catching=False, old=False):
    """Three core picks (one still waiting), two DeepSeek picks (one with 31 trades and judge labels). ds_money False:
    the DeepSeek money is nulled as the engine writes it, unless leak=True (it then stays: the screen must still hide it)."""
    P = lambda *a, **k: _pos(*a, now=now, **k)  # noqa: E731
    A = []
    A += [_acct("core-DOGE-15m-1", "cand", "core", "DOGE", "15m", 12, 7, 0.02, 6200.0, 0.10, P("BTCUSDT", 1, 100000.0, 30)),
          _acct("core-DOGE-15m-1", "quarter", "core", "DOGE", "15m", 12, 7, 0.005, 5300.0, 0.03),
          _acct("core-DOGE-15m-1", "exitonly", "core", "DOGE", "15m", 10, 4, -0.01, 4600.0, 0.20),
          _acct("core-DOGE-15m-1", "flip", "core", "DOGE", "15m", 12, 5, -0.02, 4100.0, 0.25, P("BTCUSDT", -1, 100000.0, 30)),
          _acct("core-DOGE-15m-1", "base", "core", "DOGE", "15m", 30, 15, 0.001, 5050.0, 0.12)]
    A += [_acct("core-N03_ADX_GC-1h-2", "cand", "core", "N03_ADX_GC", "1h", 3, 0, -0.05, 4300.0, 0.15, rank=2),
          _acct("core-N03_ADX_GC-1h-2", "quarter", "core", "N03_ADX_GC", "1h", 3, 0, -0.012, 4820.0, 0.04, rank=2),
          _acct("core-N03_ADX_GC-1h-2", "exitonly", "core", "N03_ADX_GC", "1h", 2, 1, 0.01, 5100.0, 0.05, rank=2),
          _acct("core-N03_ADX_GC-1h-2", "flip", "core", "N03_ADX_GC", "1h", 3, 2, 0.03, 5450.0, 0.06, rank=2),
          _acct("core-N03_ADX_GC-1h-2", "base", "core", "N03_ADX_GC", "1h", 5, 2, -0.002, 4990.0, 0.07, rank=2)]
    for role in ("cand", "quarter", "exitonly", "flip", "base"):
        A.append(_acct("core-OBV-4h-1", role, "core", "OBV", "4h", 0, 0, None, 5000.0, 0.0))
    ds = [_acct("ds-F10_OTE-1h-1", "cand", "ds", "F10_OTE", "1h", 31, 16, 0.0555, 7777.77, 0.4321, P("ETHUSDT", -1, 2500.0, 20)),
          _acct("ds-F10_OTE-1h-1", "quarter", "ds", "F10_OTE", "1h", 31, 16, 0.0144, 6666.66, 0.1234),
          _acct("ds-F10_OTE-1h-1", "exitonly", "ds", "F10_OTE", "1h", 20, 9, 0.0233, 6123.45, 0.2345),
          _acct("ds-F10_OTE-1h-1", "flip", "ds", "F10_OTE", "1h", 31, 12, 0.0101, 5432.1, 0.3456, P("ETHUSDT", 1, 2500.0, 20)),
          _acct("ds-F10_OTE-1h-1", "base", "ds", "F10_OTE", "1h", 40, 22, 0.0607, 8888.88, 0.0987)]
    ds += [_acct("ds-F5_BOX-4h-1", role, "ds", "F5_BOX", "4h", 2, 1, 0.01, 5200.0, 0.02) for role in ("cand", "quarter", "exitonly", "flip", "base")]
    if not ds_money and not leak:
        for a in ds:
            a.update(mean_ret=None, wallet=None, max_dd=None)
            if a["open"]:
                a["open"] = {k: a["open"][k] for k in ("symbol", "side", "since")}
    A += ds
    done = now - (3 * DAY if catching else 120_000)
    gen = now - (20 * 60_000 if old else 60_000)
    return {"generated_ms": gen, "done_ms": done, "lag_s": 120, "start_ms": now - 10 * DAY,
            "started_ms": now - 10 * 60_000 if catching else now - 5 * DAY, "accounts": A, "ds_money": ds_money,
            "judge": {"core-DOGE-15m-1": {"verdict": "early", "trades": 12}, "core-N03_ADX_GC-1h-2": {"verdict": "early", "trades": 3},
                      "core-OBV-4h-1": {"verdict": "early", "trades": 0}, "ds-F5_BOX-4h-1": {"verdict": "early", "trades": 2},
                      "ds-F10_OTE-1h-1": {"verdict": "not_yet", "trades": 31, "positive": True, "beats_base": False, "beats_flip": True}},
            "watch": {"checkpoints": [{"id": "C1", "ko": "1차 점검", "ms": now + 31 * DAY}, {"id": "C2", "ko": "2차 점검", "ms": now + 61 * DAY},
                                      {"id": "C3", "ko": "3차 점검", "ms": now + 92 * DAY}],
                      "pools": {"core": {"c2": {"beats_flip": True, "beats_base": False}}, "ds": {"c2": {"beats_flip": True, "beats_base": False}}}}}


META = {"strategies": {"DOGE": {"ko": "도지 봇"}, "N03_ADX_GC": {"ko": "ADX·골든크로스"}, "OBV": {"ko": "OBV 추세형"},
                       "F10_OTE": {"ko": "ICT OTE"}, "F5_BOX": {"ko": "박스권 양 끝 반전"}},
        "picks": {"core-DOGE-15m-1": {"style": "trend"}}}
LEAKS = ("7,777.77", "6,666.66", "6,123.45", "5,432.10", "8,888.88", "+55.6%", "+33.3%", "+22.5%", "+8.6%", "+77.8%", "+4.0%",
         "43.2%", "12.3%", "23.5%", "34.6%", "+5.55%", "+1.44%", "+2.33%", "+6.07%", "+40.0%", "−40.0%", "20배")


def _routes(league, now, sparks_ds=True):
    sparks = {a["id"]: [5000.0, (5000.0 + a["wallet"]) / 2, a["wallet"]] if a["wallet"] is not None and (a["trades"] or 0) else None
              for a in league["accounts"]}
    if not sparks_ds:
        sparks = {k: (None if k.startswith("ds-") or "-ds-" in k else v) for k, v in sparks.items()}
    live = {"generated_ms": now - 2000, "server_ms": now, "source": "binance",
            "coins": [{"coin": "BTCUSD", "price": 101000.0, "mark": 101000.0, "ok": True},
                      {"coin": "ETHUSD", "price": 2450.0, "mark": 2450.0, "ok": True}]}
    return {"/api/league": league, "/api/meta": META, "/api/sparks": {"generated_ms": league["generated_ms"], "sparks": sparks},
            "/api/live": live}


def _run(tmp_path, routes, steps=(), local=None, query=None, live=True):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": STATIC, "routes": routes, "steps": list(steps), "local": local or {}, "query": query or {}, "live": live}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120,
                       cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def _row(view, aid):
    hits = [r for r in view["rows"] if r["id"] == aid]
    assert hits, (aid, [r["id"] for r in view["rows"]])
    return hits[0]


# ---------------------------------------------------------------- tests
def test_rank_files_are_text_only_and_use_the_tokens():
    """No HTML parsing in the screen's modules; its stylesheet is served, loaded by the screen, scoped, and uses only
    the tokens' colours and the type scale."""
    from candleague import dash as D
    for f in RANK_JS:
        src = open(os.path.join(STATIC, "js", "screens", f)).read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval("):
            assert bad not in src, (f, bad)
    assert 'export const css = "scr/rank.css"' in open(os.path.join(STATIC, "js", "screens", "rank.js")).read()
    assert "scr/rank.css" in D.STATIC_FILES
    css = open(os.path.join(STATIC, "scr", "rank.css")).read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)
    for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", css):
        assert "var(--t-" in m.group(1), m.group(0)
    for rule in re.findall(r"(?m)^([^@/\s}][^{]*)\{", css):
        for sel in rule.split(","):
            assert sel.strip().startswith('.scr[data-screen="rank"]'), sel
    node = shutil.which("node")
    if node:
        for f in RANK_JS:
            with open(os.path.join(STATIC, "js", "screens", f)) as fh:
                r = subprocess.run([node, "--input-type=module", "--check"], stdin=fh, capture_output=True, text=True)
            assert r.returncode == 0, (f, r.stderr[:400])


def test_board_cards_tiles_rows_and_live_pill(tmp_path):
    """Money shown: the 묶음 cards, the tiles and 상위·하위 by 잔고 수익률 with the rule bot's row (avatar, 15분 chip,
    name, small line, %, 거래 · 승패 · 잔고 · 낙폭, live pill, 표본 적음, 동전 ▲▼), the waiting account unranked."""
    now = int(time.time() * 1000)
    lg = _league(now)
    o = _run(tmp_path, _routes(lg, now), steps=[{"name": "ds", "click": '.rk-gcard[data-group="ds"]'},
                                                {"name": "all", "click": ".k4-allbtn"},
                                                {"name": "table", "click": '.rk-view button[data-id="table"]'}])
    f = o["first"]
    assert f["pressed"] == ["core"]
    core, dsc, cmp_, flip = f["cards"]
    assert "후보 · 기존 36" in core and "3계좌" in core and "0.0%" in core            # median of +24.0 %, −14.0 %, 0.0 %
    assert "동전보다 위 1/2" in core and "기본값보다 위 1/2" in core and "파산 0 · 포지션 1" in core
    assert "묶음 한 번 평균" in core and "동전 ▲" in core and "기본값 ▼" in core
    assert "후보 · 딥시크" in dsc and "숨김" not in dsc and "동전보다 위 1/2" in dsc
    assert "비교 계좌" in cmp_ and "15계좌" in cmp_ and "후보보다 나음" in cmp_ and "1/4가 후보보다 덜 흔들림" in cmp_
    assert "동전 던지기" in flip and "비교 기준 (판정 안 함)" in flip
    tiles = f["tiles"].replace(" ", "")
    assert "계좌3" in tiles and "포지션중1" in tiles and "시작보다많은계좌1" in tiles and "파산0" in tiles
    top = [r for r in f["rows"] if r["top"]]
    assert [r["id"] for r in top] == ["core-DOGE-15m-1", "core-N03_ADX_GC-1h-2"]
    doge = top[0]
    assert doge["rk"] == "1" and doge["ret"] == "+24.0%" and doge["spark"] and doge["href"] == "#/account/core-DOGE-15m-1"
    assert "15분" in doge["name"] and "도지 봇" in doge["name"]
    assert "거래 12 · 7승 5패 · 잔고 6,200.00 · 낙폭 10.0%" in doge["meta"] and "표본 적음" in doge["meta"] and "동전 ▲" in doge["meta"]
    assert doge["pill"] == "BTC 롱 30배+30.0%"                                  # side × lev × (mark / entry − 1), live
    n03 = top[1]
    assert n03["ret"] == "−14.0%" and "2순위" in n03["name"] and "동전 ▼" in n03["meta"] and n03["pill"] is None
    assert "아직 거래 없는 계좌 1개" in f["foot"]
    assert "실시간 시세" in f["live"] and not f["banner"]
    lst = [r for r in f["rows"] if not r["top"]]
    assert [r["id"] for r in lst] == ["core-DOGE-15m-1", "core-N03_ADX_GC-1h-2", "core-OBV-4h-1"] and lst[2]["rk"] == "—"
    assert "기존 36 후보 · 3계좌" in f["count"]
    # 딥시크 (money shown, the owners' current setting): ranked like the others
    d = o["steps"]["ds"]
    assert d["pressed"] == ["ds"] and o["query"] is not None
    f10 = _row(d, "ds-F10_OTE-1h-1")
    assert f10["rk"] == "1" and f10["ret"] == "+55.6%" and f10["pill"] == "ETH 숏 20배+40.0%" and "동전 ▲" in f10["meta"]
    # 전체: every role, the role chip on non-후보 rows, 봉별 요약 per 묶음
    a = o["steps"]["all"]
    assert a["pressed"] == [] and "전체 · 25계좌" in a["count"]
    assert "1/4" in _row(a, "core-DOGE-15m-1-q")["name"] and "기존 36" in _row(a, "core-DOGE-15m-1-q")["meta"]
    assert "비교 기준" in _row(a, "core-DOGE-15m-1-flip")["meta"]
    assert "기존 36 후보" in a["tf"] and "동전" in a["tf"]
    t = o["steps"]["table"]
    assert len(t["table"]) == 25 and any("+55.6%" in r for r in t["table"])
    # the CSV: one row per account, ranks first, the open position named
    head = o["csvHead"]
    rows = {r[head.index("account")]: r for r in o["csv"]}
    assert rows["core-DOGE-15m-1"][head.index("open")] == "BTC 롱 30배" and rows["core-DOGE-15m-1"][head.index("vs_flip")] == "위"
    assert rows["ds-F10_OTE-1h-1"][head.index("wallet")] == 7777.77 and rows["ds-F10_OTE-1h-1"][head.index("money_hidden")] == ""
    # the order of a mixed list: ranked first, then waiting, then nothing hidden here
    assert o["sorted"][0] == "base-ds-F10_OTE-1h" and o["sorted"][-1].startswith("core-OBV-4h-1")


def test_deepseek_money_never_shown_when_the_switch_hides_it(tmp_path):
    """D11 with ds_money false, even when the snapshot still (wrongly) carries the DeepSeek numbers: count-only rows
    (no rank, %, balance, drawdown, line, leverage or ROE), the card says 숨김 with the judge's labels, the table, 봉별
    요약 and CSV keep the money cells empty; counts, wins, sides and labels stay."""
    now = int(time.time() * 1000)
    for leak in (True, False):
        lg = _league(now, ds_money=False, leak=leak)
        o = _run(tmp_path, _routes(lg, now), steps=[{"name": "ds", "click": '.rk-gcard[data-group="ds"]'},
                                                    {"name": "all", "click": ".k4-allbtn"},
                                                    {"name": "table", "click": '.rk-view button[data-id="table"]'},
                                                    {"name": "cmp", "click": '.rk-gcard[data-group="cmp"]'}])
        views = [o["first"], *o["steps"].values()]
        for v in views:
            for bad in LEAKS:
                assert bad not in v["page"], (leak, bad)
            for r in v["rows"]:
                if r["id"].startswith("ds-") or r["id"].startswith("base-ds-"):
                    assert r["ret"] == "개수만" and r["rk"] == "—" and not r["spark"], r
                    assert "잔고" not in r["meta"] and "낙폭" not in r["meta"] and "%" not in r["meta"].replace("표본", ""), r
                    assert r["pill"] in (None, "ETH 숏", "ETH 롱"), r
        dsc = o["first"]["cards"][1]
        assert "숨김" in dsc and "동전보다 위 1/1 (라벨)" in dsc and "기본값보다 위 0/1 (라벨)" in dsc and "%" not in dsc
        d = o["steps"]["ds"]
        f10 = _row(d, "ds-F10_OTE-1h-1")
        assert f10["top"] and "거래 31 · 16승 15패" in f10["meta"] and "동전 ▲" in f10["meta"] and "금액 숨김" in f10["meta"]
        assert "딥시크 금액 숨김 설정" in d["foot"] and "숨김" in d["tf"]
        a = o["steps"]["all"]
        ids = [r["id"] for r in a["rows"] if not r["top"]]
        assert ids and not any(i.startswith("ds-") or i.startswith("base-ds-") for i in ids)   # page 1 of 10: the ranked core rows
        assert "딥시크 10개는 금액 숨김 설정이라 순위 없이 개수만" in a["foot"]
        assert o["sorted"][-10:] and all(i.startswith("ds-") or i.startswith("base-ds-") for i in o["sorted"][-10:])
        t = o["steps"]["table"]
        ds_rows = [r for r in t["table"] if "ICT OTE" in r or "박스권" in r]
        assert len(ds_rows) == 10 and all("개수만" in r and "숨김" in r for r in ds_rows)      # 승률 (a win share) may stay
        assert "%" not in o["steps"]["cmp"]["cards"][1]
        head = o["csvHead"]
        for r in o["csv"]:
            if r[head.index("kind")] == "ds":
                assert r[head.index("money_hidden")] == "yes"
                for k in ("wallet_return", "mean_per_trade", "wallet", "max_dd"):
                    assert r[head.index(k)] == "", (r, k)
                assert "배" not in r[head.index("open")]


def test_live_roe_hidden_while_replaying_or_when_the_record_is_old(tmp_path):
    """B2 / B8: while the engine replays from 10/01, or its record is over 15 minutes old, the pills name the position
    without a live ROE and a banner says why."""
    now = int(time.time() * 1000)
    o = _run(tmp_path, _routes(_league(now, catching=True), now))
    f = o["first"]
    assert _row(f, "core-DOGE-15m-1")["pill"] == "BTC 롱 30배"
    assert "10/01부터 다시 계산 중" in f["banner"] and "ROE 감춤" in f["live"]
    o = _run(tmp_path, _routes(_league(now, old=True), now))
    f = o["first"]
    assert _row(f, "core-DOGE-15m-1")["pill"] == "BTC 롱 30배"
    assert "엔진 기록이" in f["banner"] and "멈춤" in f["banner"]
    o = _run(tmp_path, _routes(_league(now), now), live=False)                 # no price yet: no number, never a guess
    assert _row(o["first"], "core-DOGE-15m-1")["pill"] == "BTC 롱 30배"


def test_rank_arrows_since_the_last_visit_and_old_links(tmp_path):
    """▲▼ = the rank in the 묶음 now against this viewer's last visit (localStorage); the visit is remembered; old
    ?role= / ?kind= links pick the matching 묶음."""
    now = int(time.time() * 1000)
    prev = {"prev": {"ts": now - 3 * 3_600_000, "v": {"core-DOGE-15m-1": -0.5, "core-N03_ADX_GC-1h-2": 0.5}}}
    o = _run(tmp_path, _routes(_league(now), now), local={"cl-rank-memo": json.dumps(prev)})
    f = o["first"]
    top = {r["id"]: r for r in f["rows"] if r["top"]}
    assert top["core-DOGE-15m-1"]["rk"] == "1▲1" and top["core-N03_ADX_GC-1h-2"]["rk"] == "2▼1"
    assert "이 화면을 봤을 때보다" in f["note"]
    assert abs(o["memo"]["cur"]["v"]["core-DOGE-15m-1"] - 0.24) < 1e-9 and "ds-F10_OTE-1h-1" in o["memo"]["cur"]["v"]
    assert o["groupFromQuery"] == [{"g": "ds", "sub": "all"}, {"g": "cmp", "sub": "base"}, None, {"g": "flip", "sub": "all"},
                                   {"g": "cmp", "sub": "quarter"}, {"g": "ds", "sub": "all"}, None]
    o = _run(tmp_path, _routes(_league(now), now), query={"role": "exitonly"})
    assert o["first"]["pressed"] == ["cmp"] and "비교 계좌 · 청산만 · 5계좌" in o["first"]["count"]
