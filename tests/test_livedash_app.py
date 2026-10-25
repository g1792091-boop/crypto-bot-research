"""실거래 대시보드 (paperbot/livedash; owners 10/19 "따로 실거래용 봇 대시보드 사이트를"): the live bots' own site.

- login required everywhere but the login page; the same password as the rule bot's dashboard, its OWN cookie (another
  name, another signing key: a rule-bot session is no live session and back)
- the page: static/live/index.html (<html data-site="live">), versioned files under /static/v-<ver>/{live,v4}/, the
  live boot module and the core it loads; the rule bot's page keeps its own index, assets and menu
- every /api path the live page's JS can call (a static scan of static/live/main.js and every module it reaches, the
  실거래 screens included) is served by the live app, or is listed below with the reason the live site never calls it
- the 포지션 tab's answer (dash/more/livepos.py) on the hand-made live world (tests/livebots_world.py) with the 규칙봇 15
  config: 진입가 · 손절가 (the −50 % net stop) · 익절가 (the two-part ladder's next step) · 최대 +% / 최대 −% (the paper
  engine's record, the executor's from the rule bot's 1m bars) · the A / B group · the fast-stop state · the entry gap;
  the 거래 tab's excursions by row key; honest states without the bars (수집 전), read-only
- the rule bot's dashboard: no 실거래 in its menu, #/livebots says where it moved
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot.dash import app as D  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livepos as P  # noqa: E402
from paperbot.livedash import app as LA  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from test_dash import SECRET  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "paperbot", "dash", "static")
V4 = os.path.join(STATIC, "v4")
PW = "correct horse battery"
NOW, T0, H, MIN = W.NOW, W.T0, W.H, W.MIN
ENTRY = T0 + 9 * H                     # the open BTC long of the world (paper 62,000; bybit 62,010 at +15 s)


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


# ================================================================ the world: the 규칙봇 15 config, the BTC bars
def live15_config() -> dict:
    """deploy/combo.live15.json with the world's first setting (S2_ST_ROC 1h, the open position's member_order 1) as a B
    (no_chase) member."""
    cfg = json.loads(_read(ROOT, "deploy", "combo.live15.json"))
    cfg["members"][0] = {"strategy": "S2_ST_ROC", "tf": "1h", "no_chase": True}
    return cfg


def btc_bars(path: str) -> None:
    """The rule bot's 1m BTC bars from the open position's entry minute to now: highs up to 62,900, lows down to 61,600."""
    s = Store3(path)
    rows = []
    for i, ts in enumerate(range(ENTRY, NOW, MIN)):
        hi = 62900.0 if i == 20 else 62300.0
        lo = 61600.0 if i == 7 else 61950.0
        rows.append({"ts": ts, "symbol": "BTCUSDT", "open": 62100.0, "high": hi, "low": lo, "close": 62100.0, "volume": 1.0,
                     "close_time": ts + MIN - 1, "processed_at": ts + MIN})
    # bybit's t2 (ETH short, entry 100 at T0 + 2h + 20 s, exit T0 + 2h + 41 min): a high of 101, a low of 98.5
    t2 = T0 + 2 * H
    for ts in range(t2, t2 + 42 * MIN, MIN):
        rows.append({"ts": ts, "symbol": "ETHUSDT", "open": 100.0, "high": 101.0 if ts == t2 + 5 * MIN else 100.2,
                     "low": 98.5 if ts == t2 + 30 * MIN else 99.8, "close": 100.0, "volume": 1.0, "close_time": ts + MIN - 1,
                     "processed_at": ts + MIN})
    s.live_bars(rows)
    s.close()


def engine_extremes(paper_db: str, mfe: float, mae: float) -> None:
    """The paper engine's own record of the open position's best / worst price (what Position.mfe_price / mae_price hold)."""
    c = sqlite3.connect(paper_db)
    data = json.loads(c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()[0])
    pos = data["engines"][W.ACCOUNT]["position"]
    pos["mfe_price"], pos["mae_price"] = mfe, mae
    c.execute("UPDATE state SET data = ? WHERE k = 'accounts'", (json.dumps(data),))
    c.commit()
    c.close()


def set_config(paper_db: str, cfg: dict) -> None:
    s = Store3(paper_db)
    s.put_state("combo_run", T0, {"version": "combo-v2", "brackets": "example", "taker_fee": 0.0005, "members": [], "config": cfg})
    s.close()


@pytest.fixture(autouse=True)
def _fresh_cache():
    L._cache.clear()
    P._final.clear()
    yield
    L._cache.clear()
    P._final.clear()


@pytest.fixture
def world(tmp_path, monkeypatch):
    folder = str(tmp_path / "w")
    p = W.build_world(folder)
    set_config(p["paper"], live15_config())
    engine_extremes(p["paper"], 62800.0, 61700.0)
    rule = os.path.join(folder, "rule-paper3.db")
    btc_bars(rule)
    more = {"rule_db": rule, "combo_config": os.path.join(folder, "no-combo.json"), "check_db": os.path.join(folder, "no-check.db"),
            "improve_db": os.path.join(folder, "no-improve.db"), "shadow_dir": folder}
    for k, v in W.env_of(p).items():
        monkeypatch.setenv(k, v)
    for k, v in W.env_more_of(more).items():
        monkeypatch.setenv(k, v)
    return {**p, **more, "folder": folder}


def _fake_candles(symbol, interval, limit=300):
    return [{"time": 1_700_000_000 + 60 * i, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0} for i in range(min(limit, 3))]


def _app(tmp_path, **kw):
    return LA.create_app(D.hash_password(PW), SECRET, candles=_fake_candles, ticker=lambda: {"BTCUSDT": {"c": 62500.0, "mark": 62500.0}},
                         market=lambda: {"fng": None}, frames=lambda *a: None, liq_db=str(tmp_path / "no-liq.db"),
                         inbox_db=str(tmp_path / "no-inbox.db"), **kw)


@pytest.fixture
def client(tmp_path):
    c = TestClient(_app(tmp_path))
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    return c


# ================================================================ login, cookie, headers
def test_login_is_required_and_the_session_cookie_is_the_sites_own(tmp_path):
    c = TestClient(_app(tmp_path))
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"].startswith("/login")
    assert c.get("/api/v4/livebots").status_code == 401 and c.get("/api/v4/livebots/positions").status_code == 401
    assert c.get("/api/time").status_code == 401 and c.get("/static/live/main.js", follow_redirects=False).status_code in (302, 307)
    page = c.get("/login")
    assert page.status_code == 200 and "실거래" in page.text and "Paper v4" not in page.text and "/static/login.js" in page.text
    assert c.post("/api/login", json={"password": "wrong password!"}).status_code == 401
    r = c.post("/api/login", json={"password": PW})
    assert r.status_code == 200
    set_cookie = r.headers["set-cookie"]
    assert set_cookie.startswith(f"{LA.COOKIE}=") and "pb_session=" not in set_cookie and "HttpOnly" in set_cookie and "SameSite=strict" in set_cookie
    assert LA.COOKIE != D.COOKIE
    assert c.get("/").status_code == 200 and c.get("/api/time").status_code == 200
    # the headers of the rule bot's dashboard: the strict CSP, never in a frame, pages and API answers never stored
    r = c.get("/api/time")
    assert r.headers["content-security-policy"] == D.CSP and r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
    # logging out here never touches the rule bot's cookie
    out = c.post("/api/logout")
    assert out.status_code == 200 and LA.COOKIE in out.headers["set-cookie"] and "pb_session" not in out.headers["set-cookie"]


def test_a_rule_bot_session_is_no_live_session_and_back(tmp_path):
    live = TestClient(_app(tmp_path))
    rule_token = D.make_token(SECRET)                              # what the rule bot's dashboard hands out
    live.cookies.set(D.COOKIE, rule_token)
    assert live.get("/api/time").status_code == 401                # its cookie name is not read here
    live.cookies.clear()
    live.cookies.set(LA.COOKIE, rule_token)                        # even under this site's name: another signing key
    assert live.get("/api/time").status_code == 401
    live.cookies.clear()
    live.cookies.set(LA.COOKIE, D.make_token(LA.live_secret(SECRET)))
    assert live.get("/api/time").status_code == 200
    assert not D.token_ok(SECRET, D.make_token(LA.live_secret(SECRET)))   # a live token on the rule bot's dashboard: refused


# ================================================================ the page
def test_the_page_is_the_live_index_with_versioned_files(client):
    html = client.get("/").text
    ver = client.get("/api/time").json()["ver"]
    assert re.fullmatch(r"[0-9a-f]{10}", ver) and f'<meta name="pb-ver" content="{ver}">' in html
    assert '<html lang="ko" data-site="live" data-nav="top">' in html and "<title>실거래</title>" in html
    assert f'src="/static/v-{ver}/live/main.js"' in html and f'href="/static/v-{ver}/v4/tokens.css"' in html
    assert f'href="/static/v-{ver}/live/live.css"' in html and "PAPER" not in html and "Paper v4" not in html
    assert '<span class="mocktag real"' in html and ">실거래</span>" in html and "모의" not in html
    pre = re.findall(r'<link rel="modulepreload" href="([^"]+)">', html)
    assert f"/static/v-{ver}/live/main.js" in pre and f"/static/v-{ver}/live/shell.js" in pre and f"/static/v-{ver}/v4/core/routes.js" in pre
    for path in (f"/static/v-{ver}/live/main.js", f"/static/v-{ver}/v4/core/site.js", f"/static/v-{ver}/v4/screens/livebots.js",
                 f"/static/v-{ver}/v4/screens/livebots-pos.js", f"/static/v-{ver}/vendor/lightweight-charts.standalone.production.js"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "private, max-age=31536000, immutable", path
    # the boot starts none of the rule bot's machinery
    boot = _read(STATIC, "live", "main.js")
    for gone in ("startStream", "startShell", "maybeStartTour", "startSince", "startVerdictBand", "startDrawer", "startTvMode", "startBell"):
        assert gone not in re.sub(r"//[^\n]*", "", boot), gone
    shell = _read(STATIC, "live", "shell.js")
    assert "renderStrip(" in shell and "soundButton()" in shell and "dchip" not in re.sub(r"//[^\n]*", "", shell)
    # the rule bot's page keeps its own index, menu and version (static/live is not one of its folders)
    from paperbot.dash.assets import Assets
    paper = Assets(STATIC)
    assert paper.dirs == ("v4", "vendor") and "data-site" not in paper.index_html() and "/live/" not in paper.index_html()


def test_the_rule_bots_menu_no_longer_lists_실거래_and_its_old_link_says_where_it_moved():
    routes = _read(V4, "core", "routes.js")
    paper_groups = routes[routes.index("export const GROUPS = ["):routes.index("export const SCREENS")]
    assert "livebots" not in paper_groups
    assert 'livebots: {ko: "실거래", group: "home", title: "실거래", hidden: true},' in routes
    assert "livebots:" not in _read(V4, "core", "search.js").split("export const LIVE_ALIAS")[0]
    lb = _read(V4, "screens", "livebots.js")
    assert "if (!LIVE) {" in lb and "실거래 화면은 따로 옮겼어요" in lb and "siteUrl(LIVE_PORT" in lb
    assert "export const LIVE_PORT = 8093;" in _read(V4, "core", "site.js")


def _node(body: str, live: bool) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pre = "globalThis.document = {documentElement: {dataset: {site: 'live'}}};\n" if live else ""
    script = pre + f"const R = await import('file://{V4}/core/routes.js');\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_menus_of_both_sites_in_node():
    body = ("console.log(JSON.stringify({items: R.navGroups(true).flatMap((g) => g.items.map((it) => it.id)), groups: R.navGroups(true).map((g) => g.ko),"
            " keys: R.KEYS, land: R.landing(), tag: R.modeTag(R.landing()), parse: R.parseHash('#/livebots/trades?acct=mexc'),"
            " href: R.href('livebots', 'replay', {id: 7}), mod: (R.SCREENS.pos || {}).mod || null}));")
    paper, live = _node(body, False), _node(body, True)
    assert "livebots" not in paper["items"] and paper["groups"] == ["거래", "성적", "매매법", "AI 직원", "서버"]
    assert paper["tag"]["text"] == "모의" and paper["href"] == "#/livebots/replay?id=7" and paper["mod"] is None
    # 지금 · 기록 · 성적 · 운영, then VWAP 봇 (owners 10/23: the 'VWAP 개선판' paper bot's tabs, tests/test_dash_livevwap.py) and
    # 믹스 봇 (owners 10/25 night: the '믹스 30분 봇' and its paper twin, tests/test_dash_livemix.py)
    assert live["groups"] == ["지금", "기록", "성적", "운영", "VWAP 봇", "믹스 봇"] and live["land"] == "trend" and live["tag"]["text"] == "실거래"
    assert live["items"][-5:] == ["vwap", "vwperf", "vwblock", "mix", "mixperf"]
    assert live["items"][:4] == ["trend", "tchart", "hq", "pos"] and {"trades", "replay", "signals", "missed", "perf", "rank", "map", "cost", "cal", "safety",
                                                     "settings", "team", "shadows", "summary", "chart"} <= set(live["items"])
    assert live["keys"] == live["items"][:9] and live["mod"] == "livebots"
    assert live["parse"] == {"name": "trades", "arg": None, "query": {"acct": "mexc"}} and live["href"] == "#/replay?id=7"
    # 성적 starts with 검토 (the 추세판단 봇's 2-week review), then 재현 비교 (its 7/1~10/20 replay against the live record)
    assert live["items"].index("review") + 1 == live["items"].index("expect") == live["items"].index("perf") - 1
    # 기록 starts with 일지 (what the trend bot and the executors did, one feed)
    assert live["items"].index("journal") + 1 == live["items"].index("trades")
    # every menu item of the live site is a tab of screens/livebots.js (part B's tabs once their files are there)
    tabs = re.findall(r'\{id: "(\w+)", label: "([^"]+)"', _read(V4, "screens", "livebots.js"))
    have = {t for t, _ in tabs}
    pending = {"risk", "health", "goal", "judge"} - have                    # part B's four, until they land
    assert set(live["items"]) - pending == have


# ================================================================ every /api path the live JS can call is served
_IMP = re.compile(r'(?:^|[\n;])\s*(import|export)\s*(\{[^}]*\}|\*\s*as\s+\w+|\*|\w+(?:\s*,\s*\{[^}]*\})?)\s*from\s*"([^"]+)"', re.S)
_DYN = re.compile(r'\bimport\(\s*"([^"]+)"\s*\)')
_PARAM = re.compile(r"\$\{[^}]*\}")
# Paths in modules the live page loads that the live site never calls, and why (each one is a code path it does not run)
NOT_ON_LIVE = {
    "/api/stream": "core/api.js startStream: the rule bot's stream; static/live/main.js never starts it",
    "/api/trades": "core/shell.js (not booted here); terminal-chart.js / terminal-feed.js read it only without a `src` (the "
                   "실거래 터미널 and 차트 pass one; fillsFeed is the rule bot's)",
    "/api/summary": "core/store.js key polled only while watched: by the rule bot's shell, sound (the live site's watches the "
                    "ticker only) and verdict band",
    "/api/analysis/health": "core/store.js key of the rule bot's shell", "/api/status": "core/store.js key of the rule bot's shell",
    "/api/office": "core/store.js key; terminal-top.js asks it only with meetings on (livebots-term.js passes meetings: false)",
    "/api/rooms": "core/store.js key of the rule bot's shell and sound", "/api/agents/usage": "core/store.js key (서버 screen)",
    "/api/checkpoint": "core/store.js key (verdict band)", "/api/debate": "core/store.js key and the rule bot's feature probe",
    "/api/levwhy": "core/store.js key (포지션 / 계좌 screens of the rule bot)",
    "/api/analysis/questions": "core/features.js: probed on the rule bot's page only (core/site.js LIVE)",
    "/api/ghcoin/board": "core/features.js probes it on the rule bot's page only; terminal-feed.js reads it only while "
                         "features.ghcoin (never set here)",
    "/api/account/{}": "screens/account-peek.js: the side panel (core/drawer.js), never opened here (PEEKABLE is empty)",
    "/api/strategies": "screens/account-peek.js (the side panel)", "/api/v4/replay/{}": "screens/account-peek.js (the side panel)",
    "/api/depth": "screens/positions-book.js bookPanel: terminal-top.js imports only countdown / fundPct",
    "/api/signals": "screens/strategies-panels.js signalFeed (reached through the side panel's imports, never called)",
    "/api/v4/bell": "core/bell.js: the rule bot's shell only",
    "/api/v4/chartplus/liq": "screens/chart-plus.js: terminal-chart.js mounts it only without a `src`",
    "/api/v4/chartplus/series": "screens/chart-plus.js (as above)",
    "/api/v4/flow/calendar": "terminal-pnl.js loadCal only without a `src` (the 실거래 수익 차트 takes the summary's calendar)",
    "/api/v4/flow/race": "screens/flow-kit.js (imported for names through flow-cal.js, never called here)",
    "/api/v4/flowlive": "screens/market-live.js boards: terminal-top.js / terminal-stats.js import only usdKo / rangePos",
    "/api/v4/flowlive/liq": "screens/market-live.js (as above)",
    "/api/v4/grid/profile/{}": "screens/grid-kit.js profileCard (the side panel's imports)",
    "/api/v4/jobs": "core/since.js: not started here (the live 설정 has no '자는 동안 요약')",
    "/api/v4/since": "core/since.js (as above)",
    "/api/v4/termpnl": "terminal-pnl.js loadCurve only without a `src` (the 실거래 수익 차트 takes the summary's hours)",
}


def _api_paths(text: str) -> set:
    out = set()
    lits = re.findall(r"`(/api/(?:[^`$]|\$\{[^}]*\})*)`", text) + re.findall(r'"(/api/[^"]*)"', text) + re.findall(r"'(/api/[^']*)'", text)
    for lit in lits:
        path = _PARAM.sub("{}", lit).split("?")[0].split("#")[0]
        path = re.sub(r"(\{\})+$", lambda x: "{}" if x.start() and path[x.start() - 1] == "/" else "", path)
        if path.endswith("/") and path.count("/") > 2:
            path += "{}"
        out.add(path)
    return out


def _closure() -> set:
    """static/live/main.js and every module it reaches, statically or by a literal dynamic import; the router's screen
    module (screens/livebots.js: every live menu item's `mod`) and core/drawer.js's side-panel modules included."""
    roots = [os.path.join(STATIC, "live", "main.js"), os.path.join(V4, "screens", "livebots.js")]
    seen, todo = set(), [os.path.normpath(p) for p in roots]
    while todo:
        p = todo.pop()
        if p in seen or not os.path.exists(p):
            continue
        seen.add(p)
        src = _read(p)
        refs = [r for _, _, r in _IMP.findall(src)] + _DYN.findall(src)
        todo += [os.path.normpath(os.path.join(os.path.dirname(p), r)) for r in refs]
    return seen


def _served(app) -> set:
    return {re.sub(r"\{[^}]+\}", "{}", r.path) for r in app.routes if hasattr(r, "path")}


def _matches(path: str, routes: set) -> bool:
    probe = path.replace("{}", "x")
    return any(re.match("^" + re.escape(r).replace(r"\{\}", "[^/]+") + "$", probe) for r in routes)


def test_every_api_path_the_live_page_can_call_is_served(tmp_path):
    served = _served(_app(tmp_path))
    files = _closure()
    assert os.path.join(V4, "screens", "livebots-pos.js") in files and os.path.join(V4, "core", "site.js") in files
    called: dict = {}
    for f in files:
        for p in _api_paths(_read(f)):
            called.setdefault(p, set()).add(os.path.relpath(f, STATIC))
    missing = {p: sorted(fs) for p, fs in called.items() if not _matches(p, served) and p not in NOT_ON_LIVE}
    assert not missing, f"the live page can call routes the live app does not serve: {missing}"
    # the 실거래 screens' own calls are all served: no exception may cover them
    own = {p for p, fs in called.items() if any(os.path.basename(f).startswith("livebots") for f in fs)}
    assert own and all(_matches(p, served) for p in own), sorted(p for p in own if not _matches(p, served))
    # the list stays honest: each entry is really called somewhere the live page loads and really not served here
    stale = [p for p in NOT_ON_LIVE if p not in called or _matches(p, served)]
    assert not stale, f"take these off NOT_ON_LIVE: {stale}"
    # what the 실거래 tabs need is there: the live answers, the market pieces of 요약 / 차트, the clock and the names
    for p in ("/api/v4/livebots", "/api/v4/livebots/positions", "/api/v4/livebots/positions/excursions", "/api/v4/livebots/replay/{}",
              "/api/v4/livebots/missed", "/api/v4/ticks", "/api/v4/movers", "/api/v4/topstats", "/api/v4/vplevels", "/api/candles",
              "/api/ticker", "/api/levels", "/api/events", "/api/liq", "/api/market", "/api/time", "/api/board", "/api/price-alerts",
              "/api/v4/livebots/trendreview", "/api/v4/livebots/journal"):
        assert _matches(p, served), p
    # and none of the rule bot's machinery
    for p in ("/api/stream", "/api/rooms", "/api/office", "/api/summary", "/api/v4/bell", "/api/lab/intake", "/api/proposals"):
        assert not _matches(p, served), p


def test_part_bs_module_is_optional_and_registered_when_there(tmp_path):
    app = fastapi.FastAPI()
    assert LA.register_modules(app, None, names=(), optional=("no_such_live_module_xyz",)) == {}
    assert "liveinsight" in LA.OPTIONAL_MODULES
    have = os.path.exists(os.path.join(ROOT, "paperbot", "dash", "more", "liveinsight.py"))
    assert ("liveinsight" in _app(tmp_path).state.more) == have


# ================================================================ the small routes of the live app
def test_names_clock_market_and_price_alerts_read_only(client, tmp_path):
    b = client.get("/api/board").json()
    assert b["names_only"] is True and b["accounts"] == [] and b["strategy_ko"]["N08_ICHI_WR"] and "names_ko" in b
    t = client.get("/api/time").json()
    assert abs(t["now"] - __import__("time").time() * 1000) < 60_000
    assert client.get("/api/candles?symbol=BTCUSDT&interval=1m&limit=2").json()[0]["close"] == 1.0
    assert client.get("/api/candles?symbol=NOPEUSDT&interval=1m").status_code == 400
    assert client.get("/api/ticker").json()["BTCUSDT"]["mark"] == 62500.0
    assert client.get("/api/liq?symbol=ALL&minutes=60").json()["recorder"] is False      # no liq.db: no recorder, never a zero list as data
    pa = client.get("/api/price-alerts").json()
    assert pa["alerts"] == [] and pa["read_only"] is True and pa["sender_alive"] is False
    r = client.post("/api/price-alerts", json={"symbol": "BTCUSDT", "price": 1})
    assert r.status_code == 403 and "규칙봇 대시보드" in r.json()["detail"]
    assert not os.path.exists(tmp_path / "no-inbox.db")                                   # never created here
    assert "events" in client.get("/api/events?days_back=1&days_ahead=1").json()


# ================================================================ 포지션 (dash/more/livepos.py) on the world
def _card(d, cid):
    return next(c for c in d["cards"] if c["id"] == cid)


def test_positions_paper_card_entry_stop_takeprofit_ladder_group_fast_and_extremes(world):
    d = P.build(L.paths(), L.paths_more(), NOW)
    assert [c["id"] for c in d["cards"]] == ["paper", "bybit", "mexc", "flip"]
    r = d["rules"]
    assert r["name"] == "규칙봇 15" and r["stop"] == {"roe": 0.5, "net": True} and r["two_part"] is True and r["early_exit"] == "own"
    assert r["early_exit_until_lock"] is True and r["margin"] == 0.4 and (r["leverage_btc"], r["leverage_alt"]) == (40, 30)
    assert r["n_members"] == 14 and r["n_no_chase"] == 4                    # live15's three B members + the world's first
    p = _card(d, "paper")["position"]
    rt, ff = p["round_trip"], 0.5 / (0.25 * 62000.0)
    assert p["entry"] == 62000.0 and p["side"] == 1 and p["leverage"] == 40 and p["entry_time"] == ENTRY
    assert p["setting"]["group"] == "B" and p["setting"]["no_chase"] is True and p["strategy_id"] == "S2_ST_ROC" and p["timeframe"] == "1h"
    # 손절가: the recorded first stop, and the config's −50 % net stop at this entry beside it
    assert p["stop_initial"] == 61000.0 and p["stop50"] == pytest.approx(62000.0 * (1 + (-0.5 / 40 + rt)))
    # locked at +10 %: the lock line, the money it secures; 익절가 = the two-part ladder's next step (15 % -> 12 %)
    assert p["locked"] is True and p["lock_price"] == 62200.0 and p["secured"]["usd"] == pytest.approx(0.1 * 387.5)
    nx = p["next"]
    assert nx["lock"] == pytest.approx(0.12) and nx["at"] == pytest.approx(0.15)
    assert nx["price"] == pytest.approx(62000.0 * (1 + (0.15 / 40 + rt + ff)))
    lad = p["ladder"]
    assert [(round(s["at"], 4), round(s["lock"], 4)) for s in lad[:4]] == [(0.11, 0.1), (0.15, 0.12), (0.2, 0.17), (0.25, 0.22)]
    assert [s["state"] for s in lad[:3]] == ["done", "next", "later"] and lad[1]["price"] == pytest.approx(nx["price"])
    # 최대 +% / 최대 −%: the paper engine's own record (mfe 62,800 / mae 61,700)
    ex = p["excursion"]
    assert ex["src"] == "engine" and ex["mfe"] == pytest.approx(40 * ((62800 / 62000 - 1) - rt - ff))
    assert ex["mae"] == pytest.approx(40 * ((61700 / 62000 - 1) - rt - ff)) and ex["mfe_move"] == pytest.approx(800 / 62000)
    # locked: the fast stop is off (the ladder alone decides); the liquidation price is the paper's
    assert p["fast"]["state"] == "off" and "계단 익절만" in p["fast"]["ko"] and p["liq"] == 60600.0
    # bybit follows this very position: its entry gap (10 USDT worse, 15 s later); MEXC has none
    gaps = {x["id"]: x for x in p["execs"]}
    assert gaps["bybit"]["state"] == "following" and gaps["bybit"]["slip"] == pytest.approx(-10 / 62000) and gaps["bybit"]["delay_ms"] == 15_000
    assert gaps["mexc"]["state"] == "none"


def test_positions_executor_card_follows_the_papers_ladder_and_its_extremes_come_from_the_bars(world):
    d = P.build(L.paths(), L.paths_more(), NOW)
    b = _card(d, "bybit")["position"]
    p = _card(d, "paper")["position"]
    rt = b["round_trip"]
    assert b["paired"] is True and b["entry"] == 62010.0 and b["stop"] == 62210.0 and b["locked"] is True and b["liq"] is None
    assert "청산가가 없어요" in b["liq_ko"] and b["setting"]["group"] == "B" and b["strategy_id"] == "S2_ST_ROC"
    # 익절가 = the paper's trigger price (its lock moves there); the lock price scaled to this executor's fill
    assert b["next"]["price"] == pytest.approx(p["next"]["price"]) and b["next"]["from"] == "paper"
    assert b["next"]["lock_price"] == pytest.approx(p["next"]["lock_price"] * 62010.0 / 62000.0) and b["ladder_from"] == "paper"
    assert [s["state"] for s in b["ladder"][:2]] == ["done", "next"]
    # its secured profit: the net ROE at its exchange stop (the paper's costs), its own margin
    sroe = 40 * ((62210 / 62010 - 1) - rt)
    assert b["secured"]["roe"] == pytest.approx(sroe) and b["secured"]["usd"] == pytest.approx(sroe * 62010.0 * 0.025 / 40)
    # 최대 +% / 최대 −% from the rule bot's 1m bars since the entry minute (high 62,900, low 61,600)
    ex = b["excursion"]
    assert ex["src"] == "bars" and "바이낸스 1분봉" in ex["src_ko"] and ex["bars"] == (NOW - ENTRY) // MIN
    assert ex["mfe"] == pytest.approx(40 * ((62900 / 62010 - 1) - rt)) and ex["mae"] == pytest.approx(40 * ((61600 / 62010 - 1) - rt))
    assert b["gap"]["slip"] == pytest.approx(-10 / 62000) and b["fast"]["state"] == "off"
    # MEXC: no position (halted); the coin-flip twin: none either, said so
    m, f = _card(d, "mexc"), _card(d, "flip")
    assert m["state"] == "ok" and m["position"] is None and m["halted"] is True
    assert f["state"] == "ok" and f["position"] is None and "동전 쌍둥이" in f["note_ko"]


def test_positions_before_the_first_lock_arm_the_fast_stop_and_show_the_first_step(world):
    c = sqlite3.connect(world["paper"])
    data = json.loads(c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()[0])
    pos = data["engines"][W.ACCOUNT]["position"]
    pos["lock_roe"], pos["stop_price"] = None, 61000.0
    c.execute("UPDATE state SET data = ? WHERE k = 'accounts'", (json.dumps(data),))
    c.commit()
    c.close()
    p = _card(P.build(L.paths(), L.paths_more(), NOW), "paper")["position"]
    assert p["locked"] is False and p["secured"] is None and p["lock_price"] is None
    assert p["fast"]["state"] == "armed" and p["fast"]["ko"].startswith("빠른 손절 대기: 같은 매매법 반대 신호가 나오면 바로 청산")
    assert p["next"]["lock"] == pytest.approx(0.1) and p["next"]["at"] == pytest.approx(0.11) and p["ladder"][0]["state"] == "next"


def test_positions_without_the_bars_or_the_files_say_so(world, monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", os.path.join(world["folder"], "nope.db"))
    engine_extremes(world["paper"], 0.0, 0.0)                       # a position saved without the engine's extremes
    d = P.build(L.paths(), L.paths_more(), NOW)
    assert d["bars"]["state"] == "missing" and "1분봉" in d["bars"]["reason_ko"]
    for cid in ("paper", "bybit"):
        ex = _card(d, cid)["position"]["excursion"]
        assert ex["state"] == "missing" and "mfe" not in ex                     # 수집 전, never a zero
    gone = P.build({k: "/nonexistent/" + k for k in L.ENV}, L.paths_more(), NOW)
    assert all(c["state"] == "missing" and c.get("position") is None for c in gone["cards"])
    with open(world["bybit_db"], "wb") as fh:
        fh.write(b"garbage" * 300)
    L._cache.clear()
    bad = _card(P.build(L.paths(), L.paths_more(), NOW), "bybit")
    assert bad["state"] == "error" and bad["reason_ko"] and "position" not in bad


def test_excursions_by_the_trade_tabs_own_keys(world):
    x = P.excursions(L.paths(), L.paths_more(), NOW)
    rows = L.trade_rows(L.paths(), NOW)
    paper_keys = {r["key"] for r in rows["accts"]["paper"]["rows"]}
    assert set(x["accts"]["paper"]["rows"]) == paper_keys and all(v["src"] == "engine" for v in x["accts"]["paper"]["rows"].values())
    bybit = x["accts"]["bybit"]["rows"]
    assert set(bybit) == {str(r["key"]) for r in rows["accts"]["bybit"]["rows"]}
    t2 = bybit[f"{W.ACCOUNT}|ETHUSDT|{T0 + 2 * H}"]
    rt = L.round_trip(0.0005)
    # a short from 100: the best price is the low (98.5), the worst the high (101); 30x
    assert t2["state"] == "ok" and t2["src"] == "bars" and t2["mfe"] == pytest.approx(30 * (0.015 - rt)) and t2["mae"] == pytest.approx(30 * (-0.01 - rt))
    sol = bybit[f"{W.ACCOUNT}|SOLUSDT|{T0 + 3 * H}"]
    assert sol["state"] == "none" and "1분봉" in sol["reason_ko"]                # no SOL bars: said, never a zero
    assert x["accts"]["mexc"]["state"] == "ok"


def test_the_live_app_serves_the_positions_and_reads_only(world, client):
    before = {k: open(world[k], "rb").read() for k in ("paper", "bybit_db", "mexc_db", "rule_db")}
    d = client.get("/api/v4/livebots/positions").json()
    assert _card(d, "paper")["position"]["setting"]["group"] == "B"
    x = client.get("/api/v4/livebots/positions/excursions").json()
    assert x["accts"]["paper"]["state"] == "ok"
    for path in ("/api/v4/livebots", "/api/v4/livebots/trades", "/api/v4/livebots/signals", "/api/v4/livebots/perf", "/api/v4/livebots/safety",
                 "/api/v4/livebots/settings", "/api/v4/livebots/rank", "/api/v4/livebots/calendar", "/api/v4/livebots/now",
                 "/api/v4/livebots/replay", "/api/v4/livebots/missed"):
        assert client.get(path).status_code == 200, path
    after = {k: open(world[k], "rb").read() for k in before}
    assert after == before


# ================================================================ the 포지션 card and the 거래 tab's cell in node
def _render(call: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\n"
              "if (!Node.prototype.after) Node.prototype.after = function () {};\n"
              f"const X = await import('file://{V4}/screens/livebots-pos.js'); const T = await import('file://{V4}/screens/livebots-trades.js');\n"
              f"const d = {json.dumps(data)};\nconst out = ({call});\n"
              "console.log(JSON.stringify(out && out.childNodes ? D.walk(out) : {json: out}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    if "text" in out:
        out["text"] = re.sub(r"\s+", " ", out["text"])
    return out


def test_the_position_cards_in_node(world):
    d = json.loads(json.dumps(D.json_finite(P.build(L.paths(), L.paths_more(), NOW))))
    t = _render("X.posCard(d.cards[0])", d)["text"]
    for word in ("BTCUSDT", "격리 40배", "B그룹 · 추격 막기", "진입가", "62,000", "손절", "62,200", "익절가 (다음 잠금 자리)", "15%에 닿으면 12% 잠금",
                 "청산가", "60,600", "최대 +%", "최대 −%", "페이퍼 엔진 기록", "계단 익절", "확보한 수익", "빠른 손절", "꺼짐 · 계단 익절만", "바이비트 62,010"):
        assert word in t, word
    assert "null" not in t and "undefined" not in t and "NaN" not in t
    b = _render("X.posCard(d.cards[1])", d)["text"]
    for word in ("바이비트", "진짜 돈", "62,010", "잠금선", "페이퍼 기준", "바이낸스 1분봉 기준", "실행기 기록에 청산가가 없어요", "페이퍼 진입", "페이퍼보다 불리"):
        assert word in b, word
    m = _render("X.posCard(d.cards[2])", d)["text"]
    assert "포지션 없음" in m and "멈춤" in m
    gone = _render("X.posCard({id: 'bybit', kind: 'live', state: 'missing', reason_ko: '아직 파일이 없어요'})", None)["text"]
    assert "수집 전" in gone and "$" not in gone and "0.00" not in gone
    # the mark rolls the numbers: unrealized, net ROE, the meter between the stop and the next step
    m2 = _render("X.atMark(d.cards[0].position, 62300)", d)["json"]
    p = d["cards"][0]["position"]
    assert m2["u"] == pytest.approx(0.25 * 300) and m2["roe"] == pytest.approx(40 * (300 / 62000 - p["round_trip"] - p["funding_frac"]))
    assert 0 < m2["meter"]["mark"] < 1 and m2["meter"]["out"] is None
    assert _render("X.meterOf(-1, 105, 100, 90, 80)", None)["json"] == {"entry": 0.3333333333333333, "mark": 1, "out": "tp"}
    assert _render("X.atMark(d.cards[0].position, null)", d)["json"]["u"] is None


def test_the_trade_tabs_extremes_cell_in_node(world):
    x = json.loads(json.dumps(D.json_finite(P.excursions(L.paths(), L.paths_more(), NOW))))
    key = f"{W.ACCOUNT}|ETHUSDT|{T0 + 2 * H}"
    ok = _render(f"T.excOf(d, 'bybit', {json.dumps(key)}, false)", x)["json"]
    assert ok["state"] == "ok" and ok["src"] == "bars" and ok["mfe"] > 0 > ok["mae"]
    none = _render(f"T.excOf(d, 'bybit', {json.dumps(f'{W.ACCOUNT}|SOLUSDT|{T0 + 3 * H}')}, false)", x)["json"]
    assert none["state"] == "none" and "1분봉" in none["why"]
    assert _render("T.excOf(null, 'paper', 'paper:1', false)", None)["json"]["state"] == "wait"
    assert _render("T.excOf(null, 'paper', 'paper:1', true)", None)["json"]["state"] == "failed"
    js = _read(V4, "screens", "livebots-trades.js")
    assert 'export const EXC_API = "/api/v4/livebots/positions/excursions";' in js and "excCell(r)," in js and "...excRows(r)," in js


# ================================================================ deploy
def test_the_service_unit_and_the_install_wiring():
    unit = _read(ROOT, "deploy", "paperbot-livedash.service")
    assert "User=paperbot" in unit and "EnvironmentFile=/etc/paperbot/dash.env" in unit and "--port 8093" in unit
    assert "-m paperbot.livedash --host ${DASH_HOST}" in unit and 'until ip -4 -o addr show | grep -qF " inet $$DASH_HOST/"' in unit
    assert "ProtectSystem=strict" in unit and "NoNewPrivileges=yes" in unit
    assert "-/var/lib/paperbot/exec" in unit.split("ReadOnlyPaths=")[1].splitlines()[0]
    hidden = unit.split("InaccessiblePaths=")[1].splitlines()[0]
    assert "/etc/paperbot/executor.env" in hidden and "/etc/paperbot/agents.env" in hidden and "/etc/paperbot/debate.env" in hidden
    inst = _read(ROOT, "deploy", "install.sh")
    assert "paperbot-livedash.service" in inst and "paperbot-dash paperbot-livedash" in inst
    assert "systemctl enable paperbot-livedash" in inst and "systemctl restart paperbot-livedash" in inst
    assert "ufw allow in on tailscale0 to any port \"$LIVEDASH_PORT\" proto tcp" in inst and "LIVEDASH_PORT=8093" in inst
    up = _read(ROOT, "deploy", "update-dash.sh")
    assert '"paperbot/livedash/"' in up and '"$SYSTEMCTL" restart paperbot-livedash' in up
    doc = _read(ROOT, "docs", "livedash-ko.md")
    assert ":8093" in doc and "sudo bash deploy/install.sh" in doc and "systemctl status paperbot-livedash" in doc and "## B 화면" in doc
