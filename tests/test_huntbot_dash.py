"""huntbot/dash.py and its page: nothing without a session, a wrong password refused, a cross-site login refused, the
snapshots served read-only (DeepSeek money never in them), a missing file shown as 준비 중; the page never parses HTML
and every screen renders real snapshot files without a script error (node + a tiny DOM stand-in, when node exists)."""

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

from fastapi.testclient import TestClient  # noqa: E402

from huntbot import dash as D  # noqa: E402

STATIC = os.path.join(ROOT, "huntbot", "static")
FORM = {"content-type": "application/x-www-form-urlencoded", "origin": "http://hunt.test"}


def _client(snap, open_=False):
    return TestClient(D.create_app(str(snap), D.hash_password("pw-123"), b"x" * 32, open_=open_),
                      base_url="http://hunt.test")


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory):
    """Real snapshot files from a short runner pass on synthetic bars (F1 systems + one DeepSeek cell, one lineup)."""
    from huntbot import bench as B
    from huntbot import config as CFG
    from huntbot import systems as S
    from research.hunt import hunt as H
    d = tmp_path_factory.mktemp("hb")
    syms = ["BTCUSDT", "AAAUSDT"]
    warm, at = CFG.day_ms("2026-08-25"), CFG.FORWARD_START_MS + 2 * CFG.DAY + 7 * 3_600_000
    arr = B.synth_arrays(syms, warm, at + CFG.DAY, seed=2)
    st = B.make_store(str(d / "store.db"), syms, arr, warm, at)
    systems, aliases = S.system_list()
    ds = next(s for s in systems if s["kind"] == "ds" and s["tf"] == "1h")
    sel = [s for s in systems if s["family"] == "F1" and s["tf"] in ("15m", "1h")] + \
        [s for s in systems if S.cell_id(s) == S.cell_id(ds)]
    (d / "lineup.json").write_text(json.dumps({"accounts": [
        {"system": "F1:E1:15m:NONE", "label": "정식", "variant": "r0.5", "pick_no": 1},
        {"system": ds["id"], "label": "참고", "variant": "r0.5", "pick_no": 2}]}))
    orig = H.entry_events

    def ev(spec, sym, ser, btc):                       # DeepSeek cells: a causal stand-in (no full-grid run here)
        if spec["kind"] != "ds":
            return orig(spec, sym, ser, btc)
        import numpy as np
        c, o = ser.bars.c, ser.bars.o
        f = (np.abs(np.sin(ser.bars.open_ms / 7.1e5)) * 1e4) % 1.0
        return (f < 0.08) & (c > o), (f > 0.92) & (c < o)
    H.entry_events = ev
    try:
        r = B.make_test_runner(str(d), st, syms, warm, B.FakeClock(at + 60_000), systems=sel,
                               lineup_path=str(d / "lineup.json"))
        info = r.cycle(at)
    finally:
        H.entry_events = orig
    assert not info["errors"], info["errors"]
    return d / "snap", ds["id"]


def test_login_and_read_only_views(tmp_path, snapshot):
    snap, ds_id = snapshot
    c = _client(snap)
    assert c.get("/api/status").status_code == 401
    assert c.get("/", follow_redirects=False).status_code == 303
    assert c.get("/static/js/app.js").status_code == 404
    assert c.get("/static/hb.css").status_code == 200                       # the login page's own files are public
    r = c.post("/login", content="password=nope", follow_redirects=False,
               headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.headers["location"] == "/login?bad=1"
    r = c.post("/login", content="password=pw-123", follow_redirects=False,
               headers={**FORM, "origin": "http://evil.test"})
    assert r.status_code == 403
    r = c.post("/login", content="password=pw-123", follow_redirects=False, headers=FORM)
    assert r.status_code == 303 and D.COOKIE in r.cookies
    for k in ("status", "lineup", "systems", "positions", "trades"):
        doc = c.get(f"/api/{k}").json()
        assert not doc.get("missing"), k
    assert "recent" in c.get("/api/trades").json()
    sysrow = c.get(f"/api/system/{ds_id}").json()
    assert sysrow["row"]["ds"] is True and "equity_now" not in sysrow["row"] and sysrow["hourly"] is None
    assert all("pnl" not in t for t in sysrow["trades"])
    core = c.get("/api/system/F1:E1:15m:NONE").json()
    assert core["trades"] and len(core["hourly"]["eq"]) > 24
    assert c.get("/api/system/NOPE:X:1h:G1").status_code == 404
    assert c.post("/api/status").status_code in (404, 405)                    # nothing writes
    h = c.get("/").headers
    assert "frame-ancestors 'none'" in h["content-security-policy"] and h["x-frame-options"] == "DENY"
    empty = _client(tmp_path)
    empty.post("/login", content="password=pw-123", headers=FORM)
    assert empty.get("/api/lineup").json() == {"missing": True, "status": "준비 중"}


def test_open_mode_only_on_tailscale_or_loopback():
    assert D.open_ok("100.101.2.3") and D.open_ok("127.0.0.1")
    assert not D.open_ok("0.0.0.0") and not D.open_ok("45.76.1.2") and not D.open_ok("")
    assert D.host_ok("100.101.2.3:8092", {"100.101.2.3"}) and not D.host_ok("evil.test", {"100.101.2.3"})


def test_session_token():
    t = D.make_token(b"k" * 32, now=1000)
    assert D.token_ok(b"k" * 32, t, now=2000) and not D.token_ok(b"z" * 32, t, now=2000)
    assert not D.token_ok(b"k" * 32, t, now=1000 + D.SESSION_S + 1)


def test_page_never_parses_html():
    for dp, _dn, fns in os.walk(os.path.join(STATIC, "js")):
        for f in fns:
            src = open(os.path.join(dp, f), encoding="utf-8").read()
            for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function",
                        "eval(", "setAttribute(\"style\"", "binance.com"):
                assert bad not in src, (f, bad)
    index = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    for ref in re.findall(r'(?:href|src)="/static/([^"]+)"', index):
        assert ref in D.STATIC_FILES, ref
    assert "style=" not in index and "<script>" not in index


SHIM = r"""
const fixtures = JSON.parse(process.env.FIX);
const errors = [];
class Node_ { constructor() { this.childNodes = []; this.parentNode = null; }
  appendChild(c) { if (c.isFrag) { for (const k of c.childNodes) this.appendChild(k); c.childNodes = []; return c; }
    c.parentNode = this; this.childNodes.push(c); return c; }
  replaceChildren(...cs) { this.childNodes = []; for (const c of cs) this.appendChild(c); }
  remove() {} get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.childNodes = [new Text_(String(v))]; } }
class Text_ extends Node_ { constructor(t) { super(); this.t = t; } get textContent() { return this.t; } }
class El extends Node_ { constructor(tag) { super(); this.tag = tag; this.attrs = {}; this.dataset = {}; this.className = "";
    this.style = {setProperty() {}}; this.listeners = {}; }
  setAttribute(k, v) { this.attrs[k] = String(v); } removeAttribute(k) { delete this.attrs[k]; }
  getAttribute(k) { return this.attrs[k]; } addEventListener(k, f) { this.listeners[k] = f; }
  querySelectorAll(sel) { const out = []; const walk = (n) => { for (const c of n.childNodes) { if (c.tag === sel) out.push(c); if (c.childNodes) walk(c); } }; walk(this); return out; } }
const byId = {}; for (const id of ["menu", "screen", "hdot", "clock"]) byId[id] = new El("div");
globalThis.Node = Node_;
globalThis.document = { createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t),
  createTextNode: (t) => new Text_(t), createDocumentFragment: () => { const f = new El("#frag"); f.isFrag = true; return f; },
  getElementById: (id) => byId[id], hidden: false };
const wl = {};
globalThis.window = { addEventListener: (k, f) => { wl[k] = f; } };
globalThis.location = { hash: "", href: "/" };
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
globalThis.setInterval = () => 0;
globalThis.fetch = async (path) => { const key = path.replace(/^\/api\//, "").split("/")[0];
  let body = fixtures[key]; if (key === "system") body = fixtures.system;
  return { status: 200, ok: true, json: async () => JSON.parse(JSON.stringify(body)) }; };
const origErr = console.error; console.error = (...a) => { errors.push(a.join(" ")); };
process.on("unhandledRejection", (e) => { errors.push(String(e && e.stack || e)); });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  await import(process.env.APP);
  const out = {};
  for (const route of ["lineup", "all", "positions", "fills", "status", "sys/" + encodeURIComponent(fixtures.system.row.id)]) {
    location.hash = "#/" + route; wl.hashchange(); await sleep(50);
    const txt = byId.screen.textContent;
    out[route] = txt.length;
    if (/불러오지 못했습니다/.test(txt)) errors.push(route + ": " + txt.slice(0, 300));
  }
  process.stdout.write(JSON.stringify({out, errors, menu: byId.menu.textContent, clock: byId.clock.textContent}));
})();
"""


def test_every_screen_renders_the_snapshots_without_error(tmp_path, snapshot):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    snap, ds_id = snapshot
    fx = {k: json.load(open(os.path.join(snap, f"{k}.json"))) for k in ("status", "lineup", "systems", "positions")}
    fx["trades"] = json.load(open(os.path.join(snap, "trades.json")))
    rows = fx["systems"]["rows"]
    row = next(r for r in rows if r.get("closed") and not r["ds"])
    sf = json.load(open(os.path.join(snap, "sys", row["file"])))
    fx["system"] = {"row": row, "trades": sf["trades"], "hourly": sf.get("hourly")}
    shim = tmp_path / "shim.mjs"
    shim.write_text(SHIM)
    env = dict(os.environ, FIX=json.dumps(fx), APP="file://" + os.path.join(STATIC, "js", "app.js"))
    r = subprocess.run([node, str(shim)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    res = json.loads(r.stdout)
    assert not res["errors"], res["errors"]
    assert all(n > 50 for n in res["out"].values()), res["out"]
    assert "라인업" in res["menu"] and "KST" in res["clock"]
    lu = fx["lineup"]["accounts"]
    assert {a["label"] for a in lu} == {"정식", "참고"} and any(a["ds"] for a in lu)


def test_modules_parse():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    for f in ("app.js", "dom.js", "fmt.js"):
        with open(os.path.join(STATIC, "js", f)) as fh:
            r = subprocess.run([node, "--input-type=module", "--check"], stdin=fh, capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr[:400])
