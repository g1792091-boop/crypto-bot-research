"""Dashboard reliability (review 10/06, branch fix-reliability):

- the page's code under /static/v-<content hash>/ (dash/assets.py): a year in the browser for the current version,
  revalidated for an older one, content ETags on unversioned files, pages and the API never stored; the version follows
  the files (an edit, update-dash's copy, a rollback), never git; '/' lists the boot modules as modulepreloads;
- /api/time carries the same version (the '새 버전' chip, core/version.js);
- /api/summary today.by_group carries each best / worst account's trade count and names, and the day's account count,
  from every trade of the day (홈 no longer downloads the newest 2,000 trades every minute);
- the live stream's events carry the connection's cursor (a short reconnect asks for exactly what it missed);
- in node: request time limits, the stream watchdog / hidden-tab pause / resume address, the '대시보드 연결 다시 잡는
  중' line that never blames the bot with an old heartbeat, the radar's slowing retries, the reload rule, the three
  load states, home's best / worst from the summary;
- source rules: no absolute /static/v4/ address in the page's files, error boxes that heal (no swallowed store
  refresh), no endless animation in the files this branch owns.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash import assets as AS  # noqa: E402
from paperbot.dash.app import create_app, hash_password, stream_event  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dash import SECRET, _store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "paperbot", "dash", "static")
V4 = os.path.join(STATIC, "v4")
PW = "reliability pw 1234"


def _client(db):
    c = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    return c


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "p.db")
    _store(db).close()
    return _client(db)


# ====================================================================== static files: versioned, cached, correct
def test_root_serves_versioned_addresses_a_version_meta_and_boot_preloads(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    html = r.text
    ver = re.search(r'<meta name="pb-ver" content="([0-9a-f]{10})">', html).group(1)
    assert '"/static/v4/' not in html                                       # every own address is versioned
    assert f'<script type="module" src="/static/v-{ver}/v4/core/main.js"></script>' in html
    pre = re.findall(r'<link rel="modulepreload" href="([^"]+)">', html)
    assert f"/static/v-{ver}/v4/core/api.js" in pre and f"/static/v-{ver}/v4/core/router.js" in pre
    assert not any("/screens/" in p for p in pre)                         # boot only: a screen loads on use
    for ref in re.findall(r'(?:href|src)="(/static/[^"]+)"', html):
        assert client.get(ref).status_code == 200, ref
    assert client.get("/v4").text == html
    assert client.get("/api/time").json()["ver"] == ver


def test_cache_headers_current_version_a_year_older_revalidated_pages_and_api_never(client):
    ver = client.get("/api/time").json()["ver"]
    cur = client.get(f"/static/v-{ver}/v4/core/api.js")
    assert cur.status_code == 200 and cur.headers["cache-control"] == AS.IMMUTABLE
    assert "javascript" in cur.headers["content-type"]
    old = client.get("/static/v-0123456789/v4/core/api.js")               # an open tab from before an update
    assert old.status_code == 200 and old.headers["cache-control"] == "no-cache" and old.content == cur.content
    lib = client.get(f"/static/v-{ver}/vendor/lightweight-charts.standalone.production.js")
    assert lib.status_code == 200 and lib.headers["cache-control"] == AS.IMMUTABLE
    plain = client.get("/static/v4/core/api.js")
    assert plain.headers["cache-control"] == "no-cache" and plain.headers["etag"]
    again = client.get("/static/v4/core/api.js", headers={"if-none-match": plain.headers["etag"]})
    assert again.status_code == 304
    assert client.get("/static/v4/index.html").headers["cache-control"] == "no-store"
    assert client.get("/api/board").headers["cache-control"] == "no-store"
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"           # the old /v3 page: revalidated
    # only the page's own folders under a version, never a way out of them
    for bad in (f"/static/v-{ver}/../app.py", f"/static/v-{ver}/v4/../../app.py", f"/static/v-{ver}/index.html",
                f"/static/v-{ver}/login.js", "/static/v-XYZ/v4/core/api.js"):
        assert client.get(bad).status_code == 404, bad

    # below the HTTP client (which tidies '..' away): the mount itself, handed a path that tries to leave the folder
    import asyncio

    from starlette.exceptions import HTTPException
    files = AS.asset_files(STATIC, AS.Assets(STATIC))
    scope = {"type": "http", "method": "GET", "headers": []}
    for raw in (f"v-{ver}/v4/../../app.py", f"v-{ver}/vendor/../../../README.md", f"v-{ver}/v4/../../../../etc/passwd"):
        with pytest.raises(HTTPException) as ex:
            asyncio.run(files.get_response(raw, scope))
        assert ex.value.status_code == 404, raw


def test_without_a_session_versioned_files_go_to_the_login_like_every_other(tmp_path):
    db = str(tmp_path / "p.db")
    _store(db).close()
    anon = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    r = anon.get("/static/v-0123456789/v4/core/main.js", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"].startswith("/login")


def _tree(tmp_path):
    root = tmp_path / "static"
    (root / "v4" / "core").mkdir(parents=True)
    (root / "vendor").mkdir()
    (root / "v4" / "index.html").write_text('<html><head><link rel="stylesheet" href="/static/v4/a.css">\n</head>'
                                            '<body><script type="module" src="/static/v4/core/main.js"></script></body></html>')
    (root / "v4" / "a.css").write_text("a{}")
    (root / "v4" / "core" / "main.js").write_text('import {x} from "./x.js";\nimport "./side.js";\n'
                                                  '// a comment: import {no} from "./no.js"\nexport {y} from "./y.js";\n'
                                                  'const lazy = () => import("../screens/s.js");\n')
    (root / "v4" / "core" / "x.js").write_text('import {\n  y,\n} from "./y.js";\nexport const x = 1;\n')
    (root / "v4" / "core" / "y.js").write_text("export const y = 2;\n")
    (root / "v4" / "core" / "side.js").write_text("window.s = 1;\n")
    (root / "vendor" / "lib.js").write_text("lib\n")
    return root


def test_the_version_follows_the_files_edit_copy_and_rollback(tmp_path):
    root = _tree(tmp_path)
    a = AS.Assets(str(root), check_s=0)
    v1 = a.ver()
    assert re.fullmatch(r"[0-9a-f]{10}", v1) and a.ver() == v1
    e1 = a.etag("v4/core/x.js")
    # an edit under a running server: a new version and a new ETag
    (root / "v4" / "core" / "x.js").write_text('import {y} from "./y.js";\nexport const x = 3;\n')
    v2 = a.ver()
    assert v2 != v1 and a.etag("v4/core/x.js") != e1
    # update-dash.sh copies with cp -a (mtimes kept): same bytes, same version; --rollback: the old bytes, the old version
    shutil.copytree(root, tmp_path / "copy", copy_function=shutil.copy2)
    assert AS.Assets(str(tmp_path / "copy"), check_s=0).ver() == v2
    (root / "v4" / "core" / "x.js").write_text('import {\n  y,\n} from "./y.js";\nexport const x = 1;\n')
    assert a.ver() == v1 and a.etag("v4/core/x.js") == e1
    # the chart library is part of the page too
    (root / "vendor" / "lib.js").write_text("lib2\n")
    assert a.ver() not in (v1, v2)


def test_index_html_and_boot_modules(tmp_path):
    root = _tree(tmp_path)
    a = AS.Assets(str(root), check_s=0)
    assert a.boot_modules() == ["v4/core/main.js", "v4/core/x.js", "v4/core/side.js", "v4/core/y.js"]
    html = a.index_html()
    v = a.ver()
    assert f'<meta name="pb-ver" content="{v}">' in html
    assert f'href="/static/v-{v}/v4/a.css"' in html and f'src="/static/v-{v}/v4/core/main.js"' in html
    assert html.count('rel="modulepreload"') == 4 and "no.js" not in html and "screens/s.js" not in html
    assert AS.split_versioned(f"/static/v-{v}/v4/core/x.js") == (v, "v4/core/x.js")
    assert AS.split_versioned(f"/static/v-{v}/other/x.js") is None and AS.split_versioned("/static/v4/core/x.js") is None


# ====================================================================== /api/summary: today's best / worst for 홈
def test_summary_today_best_and_worst_carry_counts_and_names_from_every_trade_of_the_day(tmp_path):
    db = str(tmp_path / "p.db")
    st = Store3(db)
    now = int(time.time() * 1000)
    t0 = now - 3 * 86_400_000
    for aid, kind in (("S1@15m", "strategy"), ("S2@1h", "strategy"), ("S3@30m", "strategy"), ("F1_X@15m", "ds200")):
        strat, tf = aid.split("@")
        st.add_account(aid, strat, tf, kind, t0, "paper-v4", None, {})
    kst = 9 * 3_600_000
    since = (now + kst) // 86_400_000 * 86_400_000 - kst
    rows = []
    # 2,400 small S1 trades today (more than the old 2,000-row download held), one big S2 win, one S3 loss, a DeepSeek
    # win and yesterday's trade (left out)
    for i in range(2400):
        rows.append(("S1@15m", since + 1000 + i, 1.0))
    rows += [("S2@1h", since + 5000, 500.0), ("S3@30m", since + 6000, -80.0), ("F1_X@15m", since + 7000, 9999.0),
             ("S3@30m", since - 60_000, 7777.0)]
    for aid, ts, pnl in rows:
        st.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                        "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (aid, "BTCUSDT", ts - 1000, ts, "SL", 30, pnl, 0.0, 5000.0, "{}"))
    st.commit()
    st.conn.close()
    c = _client(db)
    core = c.get("/api/summary").json()["today"]["by_group"]["core"]
    assert core["accounts"] == 3 and core["trades"] == 2402
    assert [x["account_id"] for x in core["best"]] == ["S1@15m", "S2@1h"]
    s1 = next(x for x in core["best"] if x["account_id"] == "S1@15m")
    assert s1["pnl"] == 2400.0 and s1["n"] == 2400 and s1["strategy"] == "S1" and s1["timeframe"] == "15m"
    assert s1["kind"] == "strategy"
    assert core["worst"] == [{"account_id": "S3@30m", "pnl": -80.0, "strategy": "S3", "timeframe": "30m", "kind": "strategy",
                              "n": 1}]
    # DeepSeek money stays in its own group (D10/D11): never in the core rows
    assert all(x["account_id"] != "F1_X@15m" for x in core["best"] + core["worst"])


def test_the_stream_event_carries_the_connection_cursor(tmp_path):
    db = str(tmp_path / "p.db")
    _store(db).close()
    from paperbot.dash.app import Data, Rooms
    data, rooms = Data(db, None), Rooms(None, None)
    cur = {"trade_id": 0, "alert_row": 0, "room_msg": 0, "last_board": None}
    ev = json.loads(stream_event(data, rooms, cur)[len("data: "):])
    assert ev["cursor"] == [cur["trade_id"], cur["alert_row"]]           # moved on past this event's trades / alerts
    again = json.loads(stream_event(data, rooms, cur)[len("data: "):])
    assert again["cursor"] == ev["cursor"] and again["trades"] == []


# ====================================================================== the page's logic in node
def _node(body: str, setup: str = "") -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core, scr = "file://" + os.path.join(V4, "core"), "file://" + os.path.join(V4, "screens")
    script = setup + body.replace("@C/", core + "/").replace("@S/", scr + "/")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_requests_have_time_limits_and_say_why_they_failed():
    out = _node("""
const A = await import('@C/api.js');
const res = {};
globalThis.fetch = (path, init) => new Promise((ok, bad) => { init.signal.addEventListener('abort', () => { const e = new Error('aborted'); e.name = 'AbortError'; bad(e); }); });
try { await A.api('/api/ticker', {timeout: 60}); } catch (e) { res.timeout = [e.constructor.name, e.kind, e.status, e.detail]; }
const ac = new AbortController();
const p = A.api('/api/board', {signal: ac.signal}); ac.abort();
try { await p; } catch (e) { res.abort = e.name; }
globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
try { await A.api('/api/board'); } catch (e) { res.network = [e.kind, e.status]; }
globalThis.fetch = async () => ({status: 500, ok: false, json: async () => ({detail: '서버 오류'})});
try { await A.api('/api/board'); } catch (e) { res.http = [e.kind, e.status, e.detail]; }
globalThis.fetch = (path, init) => new Promise((ok, bad) => { init.signal.addEventListener('abort', () => { const e = new Error('x'); e.name = 'AbortError'; bad(e); }); });
try { await A.post('/api/rooms/x/say', {text: 'a'}, {timeout: 50}); } catch (e) { res.post = [e.kind, e.detail]; }
res.limits = [A.timeoutFor('/api/ticker'), A.timeoutFor('/api/board'), A.timeoutFor('/api/analysis/risk'), A.timeoutFor('/api/v4/radar?tf=1h')];
console.log(JSON.stringify(res));
""")
    assert out["timeout"] == ["ApiError", "timeout", 0, "응답이 없습니다 (0초)"]
    assert out["abort"] == "AbortError"                              # a left screen stays silent
    assert out["network"] == ["network", 0] and out["http"] == ["http", 500, "서버 오류"]
    assert out["post"][0] == "timeout" and "저장됐을 수 있으니" in out["post"][1]
    assert out["limits"] == [15000, 15000, 30000, 30000]


_STREAM_SETUP = """
globalThis.document = {visibilityState: 'visible', addEventListener() {}, removeEventListener() {}};
globalThis.window = {addEventListener() {}};
const made = [];
globalThis.EventSource = class { constructor(u) { this.url = u; this.readyState = 0; this.closed = false; made.push(this); } close() { this.closed = true; this.readyState = 2; } };
"""


def test_the_stream_watchdog_reconnects_a_silent_connection_pauses_a_hidden_tab_and_resumes():
    out = _node("""
const A = await import('@C/api.js');
const states = [];
A.bus.on('stream:state', (s) => states.push(s));
A.startStream();
const es1 = made[0];
es1.onopen();
es1.onmessage({data: JSON.stringify({ts: 1, changed: {}, trades: [{id: 41}], alerts: [], heartbeat: [Date.now(), {}], room_msg: 9, rooms: {}, cursor: [41, 7]})});
const fresh1 = A.stream.fresh();
// 13 s without a byte while the browser still calls it open: dropped and made again, the cursors kept (short gap)
A.stream.lastEventAt = Date.now() - 13000; A.stream.openAt = Date.now() - 20000;
A.checkStream();
const es2 = made[1];
// hidden for 2 minutes: the stream is let go (no error, no banner)
document.visibilityState = 'hidden';
A.checkStream(Date.now());
A.checkStream(Date.now() + A.HIDDEN_CLOSE_MS + 1000);
const paused = [A.stream.state, A.stream.es === null, es2.closed];
// shown again after a long gap: a new connection at once, from now (only the room cursor)
document.visibilityState = 'visible';
A.stream.lastEventAt = Date.now() - 300000;
A.checkStream();
const es3 = made[2];
console.log(JSON.stringify({fresh1, closed1: es1.closed, url2: es2.url, url3: es3.url, paused, states,
  url: [A.streamUrl([5, 6], 2, 1000), A.streamUrl([5, 6], 2, 200000), A.streamUrl(null, 0, null)]}));
process.exit(0);
""", _STREAM_SETUP)
    assert out["fresh1"] is True and out["closed1"] is True
    assert out["url2"] == "/api/stream?trade_id=41&alert_row=7&room_msg=9"
    assert out["paused"] == ["paused", True, True]
    assert out["url3"] == "/api/stream?room_msg=9"
    assert out["states"][:3] == ["connecting", "open", "reconnecting"] and "paused" in out["states"]
    assert out["url"] == ["/api/stream?trade_id=5&alert_row=6&room_msg=2", "/api/stream?room_msg=2", "/api/stream"]


def test_a_dead_page_connection_gets_its_own_line_and_never_blames_the_bot():
    out = _node("""
const {criticalLines, LINK_KO} = await import('@C/alerts.js');
const now = 1_000_000_000;
const hbOld = [now - 600000, {last_step: now - 600000}];
const healthOk = {bot: {ready: true, alive: true, data_fresh: true}};
const blip = criticalLines({health: healthOk, hb: hbOld, streamOk: false, link: {state: 'reconnecting', since: now - 2000}, now});
const long = criticalLines({health: healthOk, hb: hbOld, streamOk: false, link: {state: 'reconnecting', since: now - 9000}, now});
const freshOld = criticalLines({health: healthOk, hb: hbOld, streamOk: true, link: {state: 'open', since: now - 9000}, now});
const paused = criticalLines({health: healthOk, hb: hbOld, streamOk: false, link: {state: 'paused', since: now - 900000}, now});
console.log(JSON.stringify({blip: blip.map((l) => l.kind), long: long.map((l) => [l.kind, l.text]), freshOld: freshOld.map((l) => l.kind),
  paused: paused.map((l) => l.kind), LINK_KO}));
""")
    assert out["blip"] == []                                         # a 2-second blip stays quiet
    assert out["long"] == [["link", out["LINK_KO"]]]                 # the page's own link, not the bot
    assert "봇과는 별개" in out["LINK_KO"]
    assert out["freshOld"] == ["stale"]                              # a live connection bringing an old heartbeat: the bot
    assert out["paused"] == []                                       # a hidden tab's pause is not trouble


def test_radar_pending_retries_slow_down_and_stop_when_stalled():
    out = _node("""
const R = await import('@S/strategies-radar.js');
const close = 9_999_999;
let w = null, t = 0;
const seq = [];
for (const pending of [10, 10, 8, 8, 8, 8, 8, 8, 8]) {
  const p = R.pendingPlan(w, pending, t, close);
  seq.push([p.at === close ? 'close' : p.at - t, p.stalled]);
  w = p.wait; t = p.at === close ? t : p.at;
}
const none = R.pendingPlan(null, 0, 5, close);
console.log(JSON.stringify({seq, none: [none.at, none.stalled, none.wait], steps: R.PENDING_STEPS, stall: R.STALL_MS}));
""")
    assert out["steps"] == [2500, 5000, 10000, 30000] and out["stall"] == 120000
    gaps = [g for g, _ in out["seq"]]
    assert gaps[:5] == [2500, 5000, 10000, 30000, 30000]
    assert ["close", True] in out["seq"]                             # 2 minutes without progress: wait for the bar
    assert out["none"] == [9999999, False, None]


def test_reload_rule_load_states_and_home_best_worst_from_the_summary():
    out = _node("""
const V = await import('@C/version.js');
const ui = await import('@C/ui.js');
const H = await import('@S/home-live.js');
const r = {
  hidden: V.autoReloadOk({hidden: true, idleMs: 0, typing: false}),
  idle: V.autoReloadOk({hidden: false, idleMs: V.IDLE_RELOAD_MS, typing: false}),
  busy: V.autoReloadOk({hidden: false, idleMs: 60000, typing: false}),
  typing: V.autoReloadOk({hidden: true, idleMs: V.IDLE_RELOAD_MS, typing: true}),
  states: [ui.loadState(undefined, null), ui.loadState(undefined, new Error('x')), ui.loadState({a: 1}, new Error('x')), ui.loadState([], null)],
  ko: [ui.failKo({status: 404}), ui.failKo({kind: 'timeout'}), ui.failKo({kind: 'network'}), ui.failKo(new Error('x'))],
  bw: H.bestWorstOf({trades: 9, accounts: 3, best: [{account_id: 'S1@15m', pnl: 5, n: 2, strategy: 'S1', timeframe: '15m', kind: 'strategy'}], worst: []}),
  none: H.bestWorstOf(undefined),
};
console.log(JSON.stringify(r));
""")
    assert out["hidden"] and out["idle"] and not out["busy"] and not out["typing"]
    assert out["states"] == ["loading", "failed", "stale", "ok"]
    assert out["ko"] == ["이 자료가 서버에 없습니다", "서버가 제때 답하지 않았습니다", "서버에 닿지 못했습니다 (연결 끊김)", "불러오지 못했습니다"]
    assert out["bw"] == {"best": [{"id": "S1@15m", "strategy": "S1", "timeframe": "15m", "kind": "strategy", "pnl": 5, "n": 2}],
                         "worst": [], "accounts": 3, "trades": 9}
    assert out["none"] is None


# ====================================================================== source rules
def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _v4_files(exts=(".js", ".css")):
    for d, _, files in os.walk(V4):
        for f in files:
            if f.endswith(exts):
                yield os.path.join(d, f)


def test_no_absolute_v4_address_in_the_page_files():
    # the page's files load relative to their own module, so they carry the version prefix (dash/assets.py); an absolute
    # /static/v4/ address would load outside it (never kept, and a mix of versions after an update)
    for p in _v4_files():
        src = open(p, encoding="utf-8").read()
        assert "/static/v4/" not in re.sub(r"//[^\n]*|/\*.*?\*/", "", src, flags=re.S), os.path.relpath(p, V4)


def test_error_boxes_heal_and_promise_only_what_they_do():
    ui = _read("core", "ui.js")
    assert "잠시 뒤 다시 시도합니다" not in ui                      # the old promise nothing kept
    assert "export const RETRY_S = [5, 15, 30, 60];" in ui and "저절로 다시 시도" in ui
    assert "/location\\.reload/.test(String(retry))" in ui         # a page reload is never run by itself
    for p in _v4_files((".js",)):
        src = open(p, encoding="utf-8").read()
        rel = os.path.relpath(p, V4)
        # a retry that swallows the store's error would make the box vanish on a failure: the store-bound boxes pass
        # the bare refresh and their key
        assert not re.search(r"errorBox\([^;]*refresh\([^)]*\)\.catch\(\(\) => \{\}\)", src), rel


def test_the_branch_files_run_no_endless_animation_and_use_type_tokens():
    for rel in ("base.css", os.path.join("screens", "positions.css"), os.path.join("screens", "strategies-radar.css")):
        assert not re.search(r"animation:[^;}]*infinite", _read(rel)), rel
    base = _read("base.css")
    assert ".hdot[data-level=\"bad\"] i::after" in base and "animation: dot-ring 1.8s ease-out 3;" in base
    comp = _read("components.css")
    for sel in (".errbox-when", ".failnote", ".verchip"):
        block = comp[comp.index(sel):comp.index("}", comp.index(sel))]
        for m in re.findall(r"font(?:-size)?:[^;]*", block):
            assert "var(--t-" in m, (sel, m)


def test_the_version_chip_is_started_once_and_reads_the_page_meta():
    main = _read("core", "main.js")
    assert 'import {startVersion} from "./version.js";' in main and main.count("startVersion()") == 1
    ver = _read("core", "version.js")
    assert 'meta[name="pb-ver"]' in ver and "새 버전 준비됨" in ver and "눌러서 새로고침" in ver
    assert "innerHTML" not in ver and "location.reload()" in ver
