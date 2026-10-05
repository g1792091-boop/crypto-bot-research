"""Dashboard v4 UI (paperbot/dash/static/v4): served behind the same login by the existing /static mount, the screen
contract (every routed screen has screens/<name>.js exporting mount/unmount and a .css), every referenced file and
every imported name exists and every file is reachable (no dead copies), no outside hosts except Google Fonts, no HTML
parsing of server or model text, one number format, every /api route the old UI used is still used (or listed as not
needed with the reason), every /api path the new UI calls exists on the server (or is a listed NEEDS SERVER probe),
the tour and the '예전 화면' link are wired, and the pure core modules (fmt, derive, alerts, routes) run in node: group
medians and counts, the critical-banner rules, the Korean alert lines."""

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import create_app, hash_password  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dash import SECRET, _store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
OLD = os.path.join(ROOT, "paperbot", "dash", "static")
PW = "correct horse battery"


def _files(exts=(".js", ".css", ".html")):
    for d, _, fs in os.walk(V4):
        for f in fs:
            if f.endswith(exts):
                yield os.path.join(d, f)


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _routes() -> dict:
    """SCREENS of core/routes.js: {name: {group, hidden, feature}} (parsed, not executed)."""
    src = _read(os.path.join(V4, "core", "routes.js"))
    block = re.search(r"export const SCREENS = \{(.*?)\n\};", src, re.S).group(1)
    out = {}
    for m in re.finditer(r"^\s*(\w+): \{(.*?)\},?$", block, re.M):
        body = m.group(2)
        out[m.group(1)] = {"group": re.search(r'group: "(\w+)"', body).group(1), "hidden": "hidden: true" in body,
                           "feature": (re.search(r'feature: "(\w+)"', body) or [None, None])[1]}
    return out


# ---------------------------------------------------------------- served by the existing app, behind the login
def test_v4_is_served_behind_the_same_login(tmp_path):
    db = str(tmp_path / "p.db")
    _store(db).close()
    c = TestClient(create_app(db, hash_password(PW), SECRET))
    r = c.get("/static/v4/index.html", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"].split("?next=")[0] == "/login"   # back here after login
    assert c.get("/static/v4/core/main.js", follow_redirects=False).status_code in (302, 307)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get("/static/v4/index.html")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert r.headers.get("cache-control") == "no-store"
    js = c.get("/static/v4/core/main.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]   # ES modules need a JS type
    # every local file the page references exists and is served
    html = r.text
    for ref in re.findall(r'(?:href|src)="(/static/[^"]+)"', html):
        assert c.get(ref).status_code == 200, ref


def test_the_old_ui_files_are_not_touched_by_v4():
    """v4 lives only under static/v4; the old index still loads its own scripts (team P10 owns them)."""
    old = _read(os.path.join(OLD, "index.html"))
    assert "/static/v4/" not in old
    assert '<script src="/static/app.js"></script>' in old


# ---------------------------------------------------------------- the screen contract
def test_every_routed_screen_has_its_module_and_css_with_mount_and_unmount():
    routes = _routes()
    assert {"home", "board", "checkpoint", "account", "positions", "chart", "market", "strategies", "analysis", "office",
            "rooms", "digest", "debate", "server", "alerts", "signals", "howto", "faq"} <= set(routes)
    groups = re.findall(r'\{id: "(\w+)", ko: "([^"]+)"', _read(os.path.join(V4, "core", "routes.js")))
    assert [g[1] for g in groups] == ["홈", "거래", "매매법", "에이전트", "서버"]
    for name in routes:
        js = os.path.join(V4, "screens", name + ".js")
        assert os.path.exists(js), name
        assert os.path.exists(os.path.join(V4, "screens", name + ".css")), name
        src = _read(js)
        assert re.search(r"^export (async )?function mount\(el, ctx\)", src, re.M), name
        assert re.search(r"^export function unmount\(", src, re.M), name
    assert routes["debate"]["feature"] == "debate"          # hidden until the debate room has run


def test_inventory_maps_every_old_view_and_every_new_screen():
    inv = _read(os.path.join(V4, "INVENTORY.md"))
    old = _read(os.path.join(OLD, "index.html"))
    labels = re.findall(r'<button data-v="\w+"[^>]*>([^<]+)<', old)
    assert len(labels) == 12
    for lab in labels:
        assert lab.strip() in inv, lab
    for name in _routes():
        if not name.startswith("_"):
            assert name in inv, name
    # every GET route of the old server is listed
    app_src = _server_src()
    for path in re.findall(r'@app\.get\("(/api/[^"{]+)', app_src):
        base = path.rstrip("/")
        assert base in inv or base.rsplit("/", 1)[0] in inv, path


# ---------------------------------------------------------------- the module graph: files, names, no dead copies
_IMP = re.compile(r'(?:^|[\n;])\s*(import|export)\s*(\{[^}]*\}|\*\s*as\s+\w+|\*|\w+(?:\s*,\s*\{[^}]*\})?)\s*from\s*"([^"]+)"', re.S)
_DYN = re.compile(r'\bimport\(\s*"([^"]+)"\s*\)')
_SIDE = re.compile(r'(?:^|\n)\s*import\s+"([^"]+)"')


def _resolve(src_file: str, ref: str) -> str:
    if ref.startswith("/static/"):
        return os.path.normpath(os.path.join(OLD, ref[len("/static/"):]))
    return os.path.normpath(os.path.join(os.path.dirname(src_file), ref))


def _code(src: str) -> str:
    r"""The source without comments: a small scanner that knows strings, template literals and regex literals, so a
    "deploy/*.timer" string or a /https?:\/\// regex is not taken for a comment."""
    out, i, n, last = [], 0, len(src), ""
    while i < n:
        c, d = src[i], src[i + 1] if i + 1 < n else ""
        if c == "/" and d == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and d == "*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "\"'`" or (c == "/" and (not last or last in "(,=:[!&|?{};+-*%<>~^")):
            j, in_class = i + 1, False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if c == "/" and src[j] == "[":
                    in_class = True
                elif c == "/" and src[j] == "]":
                    in_class = False
                elif src[j] == c and not in_class:
                    break
                elif src[j] == "\n" and c != "`":
                    break
                j += 1
            out.append(src[i:j + 1])
            i, last = j + 1, "a"
            continue
        out.append(c)
        if not c.isspace():
            last = c
        i += 1
    return "".join(out)


def _names(spec: str) -> list:
    """'{a, b as c}' -> [(a, c), (b, c)...] as (imported, local)."""
    out = []
    for part in spec.strip().strip("{}").split(","):
        part = part.strip()
        if part:
            bits = re.split(r"\s+as\s+", part)
            out.append((bits[0].strip(), bits[-1].strip()))
    return out


_EXPORTS: dict = {}


def _exports(path: str) -> set:
    """Every name a module exports (functions, consts, lists, `* as x`, and `export *` followed)."""
    if path in _EXPORTS:
        return _EXPORTS[path]
    _EXPORTS[path] = set()
    src = _code(_read(path))
    names = set(re.findall(r"\bexport\s+(?:async\s+)?function\*?\s+([\w$]+)", src))
    names |= set(re.findall(r"\bexport\s+(?:const|let|var|class)\s+([\w$]+)", src))
    for kind, spec, ref in _IMP.findall(src):
        if kind != "export":
            continue
        if spec.startswith("{"):
            names |= {b for _, b in _names(spec)}
        elif spec.replace(" ", "").startswith("*as"):
            names.add(spec.split()[-1])
        elif spec.strip() == "*":
            names |= _exports(_resolve(path, ref))
    for spec in re.findall(r"\bexport\s*(\{[^}]*\})\s*;", src):
        names |= {b for _, b in _names(spec)}
    if re.search(r"\bexport\s+default\b", src):
        names.add("default")
    _EXPORTS[path] = names
    return names


def _deps(path: str) -> list:
    src = _code(_read(path))
    refs = [ref for _, _, ref in _IMP.findall(src)] + _DYN.findall(src) + _SIDE.findall(src)
    return [_resolve(path, r) for r in refs]


def test_every_referenced_file_and_imported_name_exists():
    bad = []
    for p in _files((".js",)):
        src = _code(_read(p))
        for kind, spec, ref in _IMP.findall(src):
            target = _resolve(p, ref)
            if not os.path.exists(target):
                bad.append(f"{p}: {ref} (missing file)")
                continue
            if spec.startswith("{") or "{" in spec:
                have = _exports(target)
                for imported, _ in _names(spec[spec.index("{"):]):
                    if imported not in have:
                        bad.append(f"{os.path.relpath(p, V4)}: {imported} is not exported by {ref}")
        for ref in _DYN.findall(src) + _SIDE.findall(src):
            if not os.path.exists(_resolve(p, ref)):
                bad.append(f"{p}: {ref} (missing file)")
        for ref in re.findall(r'"(/static/[^"$`]+\.(?:js|css|svg|png|json))"', src):   # literal asset paths
            if not os.path.exists(_resolve(p, ref)):
                bad.append(f"{p}: {ref} (missing asset)")
    for p in _files((".css",)):
        for ref in re.findall(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)', _read(p)):
            if not ref.startswith(("data:", "#", "https://")) and not os.path.exists(_resolve(p, ref)):
                bad.append(f"{p}: {ref} (missing css file)")
    html = _read(os.path.join(V4, "index.html"))
    for ref in re.findall(r'(?:href|src)="(/static/[^"]+)"', html):
        if not os.path.exists(_resolve(os.path.join(V4, "index.html"), ref)):
            bad.append(f"index.html: {ref}")
    assert not bad, "\n".join(bad)


def test_every_file_is_reachable_from_the_page_or_a_route():
    """No dead copies: every .js is imported from core/main.js or a routed screen, every .css is linked by
    index.html, is a routed screen's own css, or is @imported by one of those."""
    js_roots = [os.path.join(V4, "core", "main.js")] + [os.path.join(V4, "screens", n + ".js") for n in _routes()]
    seen, todo = set(), [os.path.normpath(p) for p in js_roots]
    while todo:
        p = todo.pop()
        if p in seen or not os.path.exists(p):
            continue
        seen.add(p)
        todo.extend(_deps(p))
    dead = sorted(os.path.relpath(p, V4) for p in _files((".js",)) if os.path.normpath(p) not in seen)
    assert not dead, f"JS files nothing imports: {dead}"
    html = _read(os.path.join(V4, "index.html"))
    css_seen = {os.path.normpath(_resolve(os.path.join(V4, "index.html"), r)) for r in re.findall(r'href="(/static/v4/[^"]+\.css)"', html)}
    css_todo = [os.path.join(V4, "screens", n + ".css") for n in _routes()]
    while css_todo:
        p = os.path.normpath(css_todo.pop())
        if p in css_seen or not os.path.exists(p):
            continue
        css_seen.add(p)
        css_todo.extend(_resolve(p, r) for r in re.findall(r'@import\s+url\(\s*["\']?([^"\')]+)', _read(p)))
    dead = sorted(os.path.relpath(p, V4) for p in _files((".css",)) if os.path.normpath(p) not in css_seen)
    assert not dead, f"CSS files nothing loads: {dead}"


def test_screens_import_shared_code_through_pb_and_style_with_tokens():
    """Screens reach core through core/pb.js (pure data tables like core/names.js excepted); screen css uses the
    tokens (no colour literals), so the one navy look stays one look."""
    allowed_core = {"pb.js", "names.js"}
    for p in _files((".js",)):
        if os.sep + "screens" + os.sep not in p:
            continue
        for _, _, ref in _IMP.findall(_code(_read(p))):
            if "/core/" in ref:
                assert ref.rsplit("/", 1)[1] in allowed_core, (p, ref)
    for p in _files((".css",)):
        if os.sep + "screens" + os.sep not in p:
            continue
        src = re.sub(r"/\*.*?\*/", "", _read(p), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), (p, "colour literal: use a token from tokens.css")
        assert not re.search(r"\brgba?\(\s*\d", src), (p, "colour literal: use a token from tokens.css")


# ---------------------------------------------------------------- every /api route: old UI, new UI, server
_PARAM = re.compile(r"\$\{[^}]*\}")


def _api_paths(text: str) -> set:
    """'/api/...' string literals (quotes or backticks) with ${...} as {} and the query string dropped."""
    out = set()
    lits = re.findall(r"`(/api/(?:[^`$]|\$\{[^}]*\})*)`", text) + re.findall(r'"(/api/[^"]*)"', text) + re.findall(r"'(/api/[^']*)'", text)
    for lit in lits:
        path = _PARAM.sub("{}", lit).split("?")[0].split("#")[0]
        path = re.sub(r"(\{\})+$", lambda x: "{}" if x.start() and path[x.start() - 1] == "/" else "", path)
        if path.endswith("/") and path.count("/") > 2:       # "/api/account/" + id
            path += "{}"
        out.add(path)
    return out


def _server_src() -> str:
    """dash/app.py, dash/analysis.py and the v4 additions in dash/more/*.py (each registers its own routes)."""
    more = os.path.join(ROOT, "paperbot", "dash", "more")
    files = [os.path.join(ROOT, "paperbot", "dash", f) for f in ("app.py", "analysis.py")]
    files += sorted(os.path.join(more, f) for f in os.listdir(more) if f.endswith(".py")) if os.path.isdir(more) else []
    return "".join(_read(f) for f in files)


def _server_routes() -> set:
    src = _server_src()
    return {re.sub(r"\{[^}]+\}", "{}", p) for p in re.findall(r'@app\.(?:get|post)\("(/api/[^"]+)"', src)}


def _matches(path: str, routes: set) -> bool:
    pat = lambda r: re.compile("^" + re.escape(r).replace(r"\{\}", "[^/]+") + "$")  # noqa: E731
    probe = path.replace("{}", "x")
    return any(pat(r).match(probe) for r in routes)


def _v4_paths() -> set:
    return set().union(*(_api_paths(_read(p)) for p in _files((".js",))))


def _old_paths() -> set:
    """Every /api path of the old UI, with the old analysis tab's '/api/analysis/' + ROUTE[t] expanded."""
    out = set()
    for f in os.listdir(OLD):
        if f.endswith((".js", ".html")):
            out |= _api_paths(_read(os.path.join(OLD, f)))
    if "/api/analysis/{}" in out:
        out.discard("/api/analysis/{}")
        route = re.search(r"const ROUTE = \{(.*?)\};", _read(os.path.join(OLD, "analysis.js")), re.S).group(1)
        out |= {"/api/analysis/" + v for v in re.findall(r':\s*"(\w+)"', route)}
    return out


# Old-UI routes the new UI deliberately does not call (none today; a removal needs its reason here).
OLD_NOT_NEEDED = {"/api/login": "the /login page posts it; the dashboard itself sits behind that page"}
# Server routes the new UI does not call, and why.
SERVER_NOT_USED = {
    "/api/agents/feed": "no room_id / round_id / speaker name yet: the console is built from /api/office + room "
                        "messages (CONTRACT.md NEEDS SERVER #3)",
    "/api/login": "the login page (/login) posts it, not the dashboard",
}
# Paths the new UI probes before the server has them (it shows '수집 전' on a 404): CONTRACT.md NEEDS SERVER.
NEEDS_SERVER: dict = {}       # /api/v4/server (#4) and /api/v4/curves (#2) are on the server now


def test_every_old_ui_route_is_still_used_or_listed_as_not_needed():
    v4 = _v4_paths()
    missing = [p for p in sorted(_old_paths()) if p not in OLD_NOT_NEEDED and not _matches(p, v4) and p not in v4]
    assert not missing, f"old /api routes nothing in v4 calls: {missing}"
    assert len(_old_paths()) >= 50                       # the parser still sees the old UI's routes


def test_every_route_the_new_ui_calls_exists_on_the_server():
    server = _server_routes()
    unknown = [p for p in sorted(_v4_paths()) if not _matches(p, server) and p not in NEEDS_SERVER]
    assert not unknown, f"v4 calls routes the server does not have: {unknown}"
    for p in NEEDS_SERVER:                       # a listed probe that the server now has should leave the list
        assert not _matches(p, server), f"{p} exists now: take it off NEEDS_SERVER"
    unused = [r for r in sorted(server) if r not in SERVER_NOT_USED and not any(_matches(p, {r}) for p in _v4_paths())]
    assert not unused, f"server routes v4 neither calls nor lists as not used: {unused}"


def test_unready_probes_degrade_to_not_yet():
    """A NEEDS SERVER probe is wrapped: its 404 becomes '수집 전', never an error box or a made-up number."""
    for path in NEEDS_SERVER:
        users = [p for p in _files((".js",)) if f'"{path}"' in _code(_read(p))]
        assert users, path
        for p in users:
            src = _read(p)
            line = next(x for x in _code(src).splitlines() if f'"{path}"' in x)
            assert "try" in line and "catch" in line, (p, line)              # a 404 is caught where it is called
            near = src + "".join(_read(d) for d in _deps(p) if os.path.exists(d) and os.sep + "screens" + os.sep in d)
            assert "notYet" in near, (p, "shows ui.notYet() until the route exists")


# ---------------------------------------------------------------- shell wiring: tour, old UI link, wording
def test_tour_walks_real_screens_and_points_at_real_elements():
    tour = _read(os.path.join(V4, "core", "tour.js"))
    steps = re.findall(r'\{go: "(\w+)", sel: \[(.*?)\], t:', tour)
    assert 6 <= len(steps) <= 7                                    # owners: 6-7 steps
    routes = _routes()
    assert {g for g, _ in steps} >= {"home", "positions", "office", "server"}
    allsrc = "\n".join(_read(p) for p in _files((".js",)))
    for go, sels in steps:
        assert go in routes and not routes[go]["hidden"] and not routes[go]["feature"], go
        for tag in re.findall(r'data-tour="(\w+)"', sels):
            assert re.search(rf'tour: "{tag}"|dataset\.tour = "{tag}"', allsrc), f"no element has data-tour={tag}"
        assert re.search(r"'\[data-group=\"\w+\"\]'|#\w+", sels), f"step {go} has no shell fallback"
    assert "skipb" in tour and 'local.set("tour-done", 1)' in tour        # skippable and remembered
    assert "startTour" in _read(os.path.join(V4, "screens", "faq.js"))       # FAQ restarts it


def test_the_old_dashboard_is_one_tap_away_in_the_menu():
    shell = _read(os.path.join(V4, "core", "shell.js"))
    assert re.search(r'h\("a", \{class: "oldui", href: "/v3"', shell) and "예전 화면" in shell     # '/' is v4 now
    inv = _read(os.path.join(V4, "INVENTORY.md"))
    assert "예전 화면" in inv


def test_the_reference_note_counts_the_coin_flips_the_verdict_really_uses():
    cp = _read(os.path.join(ROOT, "paperbot", "checkpoint.py"))
    n = int(re.search(r"^N_BOTS = ([\d_]+)", cp, re.M).group(1).replace("_", ""))
    shown = f"{n:,}"
    ui_src = _read(os.path.join(V4, "core", "ui.js"))
    # the count comes from the server (/api/summary restart.n_bots, checkpoint.N_BOTS), never typed in
    assert "같은 봉 동전 봇 ${int(METHOD.n_bots)}개" in ui_src and "METHOD.method_ko" in ui_src
    for p in _files((".js",)):
        for m in re.finditer(r"동전 봇 (\d{1,3}(?:,\d{3})+)개", _read(p)):
            assert m.group(1) == shown, (p, m.group(0))


def test_money_and_comparison_captions_are_the_shared_ones():
    """The caption and the 참고 note are written once (core/ui.js) and screens call them, never retype them."""
    ui_src = _read(os.path.join(V4, "core", "ui.js"))
    assert "모의 · 실제 시세 · 수수료·펀딩·슬리피지 포함" in ui_src
    for p in _files((".js",)):
        if p.endswith(os.path.join("core", "ui.js")):
            continue
        src = _read(p)
        assert "수수료·펀딩·슬리피지 포함" not in src, (p, "use ui.assume()")
        assert "지금 비교는 합격·불합격을 뜻하지 않습니다" not in src, (p, "use ui.refNote()")


# ---------------------------------------------------------------- honesty and safety rules, checked in the source
def test_no_outside_hosts_except_google_fonts_and_new_tab_links():
    allowed_resource = {"fonts.googleapis.com", "fonts.gstatic.com"}
    link_only = {"www.coinglass.com", "www.tradingview.com", "kr.tradingview.com"}     # <a target=_blank> only
    for p in _files():
        src = _read(p)
        assert "wss://" not in src and "new WebSocket(" not in src, p              # prices come through the server
        assert not re.search(r"<script[^>]+src=\"https?:", src), p
        for host in re.findall(r"https?://([a-z0-9.-]+)", src):
            if host == "www.w3.org":                      # the SVG namespace name, never fetched
                continue
            if host in allowed_resource:
                assert p.endswith("index.html"), (p, host)
            else:
                assert host in link_only and p.endswith(os.path.join("screens", "chart.js")), (p, host)


def test_no_html_is_parsed_from_text():
    for p in _files((".js",)):
        src = _read(p)
        for bad in ("insertAdjacentHTML", "outerHTML", "document.write", "DOMParser", "createContextualFragment",
                    "new Function", "eval("):
            assert bad not in src, (p, bad)
        for m in re.finditer(r"\.innerHTML\s*\+?=\s*([^;\n]+)", src):
            assert p.endswith(os.path.join("core", "dom.js")) and m.group(1).strip() == '""', (p, m.group(0))
        assert "javascript:" not in _code(src), p
        assert not re.search(r"setAttribute\(\s*[\"'`]on", src), (p, "inline handler")
        assert not re.search(r"\bon\w+:\s*[\"'`]", _code(src)), (p, "a string handler in h() attributes")
    dom = _read(os.path.join(V4, "core", "dom.js"))
    assert 'typeof v === "function") el.addEventListener' in dom          # h() never sets a string handler
    assert "never \"javascript:\"" in dom and "https?:|\\/(?!\\/)|#" in dom        # h() drops javascript: / data: / //host links


def test_one_number_format():
    """Grouping and decimals for shown numbers come from core/fmt.js only."""
    for p in _files((".js",)):
        if p.endswith(os.path.join("core", "fmt.js")):
            continue
        src = _read(p)
        assert "toLocaleString(" not in src and "Intl.NumberFormat" not in src, p


def test_storage_is_wrapped_and_per_viewer_only():
    for p in _files((".js",)):
        src = _read(p)
        if p.endswith(os.path.join("core", "dom.js")):
            assert src.count("localStorage.") == 3 and src.count("try {") >= 3
            continue
        assert "localStorage." not in src or "try {" in src, p


# ---------------------------------------------------------------- pure core modules in node
def _node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    script = (f"const fmt = await import('{core}/fmt.js'); const derive = await import('{core}/derive.js');\n"
              f"const alerts = await import('{core}/alerts.js'); const routes = await import('{core}/routes.js');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_number_format_in_node():
    out = _node("""console.log(JSON.stringify({
      a: fmt.money(-1234.5), b: fmt.money(1234.5, true), c: fmt.pct(0.0153), d: fmt.pct(-0.2, 2), e: fmt.price(0.11322),
      f: fmt.price(62410.53), g: fmt.usdt(5), h: fmt.money(-0.001), i: fmt.int(331), j: fmt.money(null), k: fmt.kst(1791180000000),
      l: fmt.compact(260661), m: fmt.lev(30), n: fmt.acctName({strategy: "RANDOM_2", timeframe: "5m", kind: "random"}),
      o: fmt.groupOf({kind: "random", timeframe: "5m"}), p: fmt.groupOf({kind: "random", timeframe: "15m"}),
      q: fmt.groupOf({kind: "ds200"}), r: fmt.groupOf({kind: "reel"}), s: fmt.groupOf({kind: "copy"}), t: fmt.dur(3700)}));""")
    assert out == {"a": "−1,234.50", "b": "+1,234.50", "c": "+1.5%", "d": "−20.00%", "e": "0.11322",
                   "f": "62,410.5", "g": "5.00 USDT", "h": "0.00", "i": "331", "j": "—", "k": "10/05 15:00",
                   "l": "261k", "m": "30배", "n": "동전 봇 2 · 5분", "o": "coin", "p": "coin", "q": "ds", "r": "m5",
                   "s": "extra", "t": "1시간 1분"}


def test_group_stats_compare_with_the_same_timeframe_coin_flips_and_leave_extras_out():
    out = _node("""
    const A = (id, kind, tf, wallet, extra = {}) => ({account_id: id, kind, timeframe: tf, wallet, trades: 5, ...extra});
    const board = {initial: 5000, accounts: [
      A("S1@15m", "strategy", "15m", 5200), A("S2@15m", "strategy", "15m", 4800, {bust: false, position: {symbol: "BTCUSDT"}}),
      A("S1@4h", "strategy", "4h", 4000), A("DS01_F3@15m", "ds200", "15m", 5100), A("REEL_H1@5m", "reel", "5m", 4990),
      A("RANDOM_1@15m", "random", "15m", 5000), A("RANDOM_2@15m", "random", "15m", 4900), A("RANDOM_3@15m", "random", "15m", 5050),
      A("RANDOM_1@4h", "random", "4h", 4500), A("RANDOM_1@5m", "random", "5m", 5010),
      A("S1@15m~c1", "copy", "15m", 9000)]};
    const g = derive.groupStats(board);
    const r = derive.ranked(board, "core").map((a) => a.account_id);
    console.log(JSON.stringify({core: g.groups.core, ds: g.groups.ds, m5: g.groups.m5, coin: g.groups.coin, extra: g.groups.extra,
      strat: g.strat, flip: g.flipMedByTf, r, total: g.total,
      liq: derive.liqDistance({entry: 100, liq: 98}), pnl: derive.livePnl({side: -1, qty: 2, entry: 100, margin: 10}, 99)}));""")
    assert out["core"]["n"] == 3 and out["core"]["above"] == 1 and out["core"]["below"] == 2 and out["core"]["open"] == 1
    assert out["flip"] == {"15m": 5000, "4h": 4500, "5m": 5010}
    assert out["ds"]["above"] == 1 and out["m5"]["n"] == 1 and out["m5"]["below"] == 1     # the reel vs the 5m flip
    assert out["coin"]["n"] == 5 and out["coin"]["vsN"] == 0          # all coin flips (5m too) are the yardstick
    assert out["extra"]["n"] == 1 and out["extra"]["vsN"] == 0                               # never compared
    assert out["strat"]["n"] == 5 and out["strat"]["above"] == 2 and out["strat"]["medWallet"] == 4990
    assert out["r"] == ["S1@15m", "S2@15m", "S1@4h"]
    assert out["total"]["n"] == 11 and abs(out["liq"] - 0.02) < 1e-12
    assert out["pnl"]["pnl"] == 2 and out["pnl"]["roe"] == 0.2


def test_the_critical_banner_reads_only_real_records():
    out = _node("""
    const now = 1_800_000_000_000, M = 60_000;
    const L = (o) => alerts.criticalLines({health: null, alerts: [], trades: [], hb: null, streamOk: false, now, ...o});
    const T = (k, reason) => ({exit_reason: reason, exit_time: now - k * M});
    console.log(JSON.stringify({
      none: L({}),
      bust: L({alerts: [{ts: now - 10 * M, level: "CRITICAL", text: "[S5_DONCHIAN_MFI@15m] BUST equity 7.3"}]}),
      oldBust: L({alerts: [{ts: now - 7 * 60 * M, level: "CRITICAL", text: "[S5_DONCHIAN_MFI@15m] BUST equity 7.3"}]}),
      warnOnly: L({alerts: [{ts: now - M, level: "WARN", text: "[S4_BB_BBP@30m] drawdown 31.2% (level 30%), equity 3440.10"}]}),
      liq2: L({trades: [T(1, "LIQ"), T(2, "LIQ"), T(3, "SL")]}),
      liq3: L({trades: [T(1, "LIQ"), T(5, "LIQ"), T(14, "LIQ"), T(30, "LIQ")]}),
      staleStream: L({hb: [now - 10 * M, {last_step: now - 11 * M}], streamOk: true}),
      freshStream: L({hb: [now - 5000, {last_step: now - 40000}], streamOk: true,
        health: {bot: {ready: true, alive: false, heartbeat_age_s: 600, data_fresh: false, data_age_s: 650}}}),
      staleHealth: L({health: {bot: {ready: true, alive: false, heartbeat_age_s: 600, data_fresh: true}}}),
      ko: alerts.alertKo("[S4_BB_BBP@30m] drawdown 31.2% (level 30%), equity 3440.10"),
    }));""")
    assert out["none"] == [] and out["warnOnly"] == [] and out["oldBust"] == [] and out["liq2"] == []
    assert [x["kind"] for x in out["bust"]] == ["bust"] and out["bust"][0]["dismissable"] is True
    assert "파산" in out["bust"][0]["text"]
    assert out["liq3"][0]["kind"] == "liq" and out["liq3"][0]["text"].startswith("강제청산 3건")
    s = out["staleStream"]
    assert len(s) == 1 and s[0]["kind"] == "stale" and not s[0]["dismissable"] and "시세" in s[0]["text"]
    assert out["freshStream"] == []                 # the live stream is newer than the minute-old health card
    assert out["staleHealth"][0]["text"].startswith("봇 생존 신호가 10분 전에")
    assert out["ko"] == "S4_BB_BBP · 30분 낙폭 31.2% (30% 경고선), 잔고 3440.10 USDT"


def test_hash_routes_round_trip():
    out = _node("""
    const a = routes.parseHash(routes.href("rooms", "strat:S5_DONCHIAN_MFI", {from: "office"}));
    const b = routes.parseHash("#/account/N05_PSAR_POC%4015m");
    const c = routes.parseHash("");
    console.log(JSON.stringify({a, b, c}));""")
    assert out["a"] == {"name": "rooms", "arg": "strat:S5_DONCHIAN_MFI", "query": {"from": "office"}}
    assert out["b"]["arg"] == "N05_PSAR_POC@15m" and out["c"]["name"] == "home"

# ---------------------------------------------------------------- review pass: rule numbers, names, banner, fonts
def test_rule_numbers_match_the_checkpoint_and_the_server_run_shape_is_read():
    cp = _read(os.path.join(ROOT, "paperbot", "checkpoint.py"))
    n = int(re.search(r"^MIN_TRADES = (\d+)", cp, re.M).group(1))
    shared = _read(os.path.join(V4, "screens", "home-shared.js"))
    assert re.search(r"export const MIN_TRADES = (\d+);", shared).group(1) == str(n)
    assert "run_shape.judged_by_group" in shared and "judgedTfs(board" in shared
    assert re.search(r"export function smallSample\(n, min = (\d+)\)", _read(os.path.join(V4, "core", "ui.js"))).group(1) == str(n)


def test_fonts_never_block_the_first_paint():
    html = _read(os.path.join(V4, "index.html"))
    assert not re.search(r'<link rel="stylesheet" href="https://fonts', html)      # a hung font host would hold the page
    assert 'rel="preload" as="style" id="gfonts"' in html
    assert "attachFonts()" in _read(os.path.join(V4, "core", "main.js"))


def test_account_names_keep_the_timeframe_and_use_the_short_names():
    out = _node("""
    fmt.setStrategyNames({F15_OPEN0930: "딥시크 F15_OPEN0930 (세션 레인지·시가 편향)", S5_DONCHIAN_MFI: "돈치안·MFI"});
    console.log(JSON.stringify({
      ds: fmt.acctParts({kind: "ds200", strategy: "F15_OPEN0930", timeframe: "15m", name_ko: "딥시크 F15_OPEN0930 (세션 레인지·시가 편향)"}),
      core: fmt.acctName({kind: "strategy", strategy: "S5_DONCHIAN_MFI", timeframe: "1h"}),
      reel: fmt.acctName({kind: "reel", strategy: "REEL_H1", timeframe: "5m", name_ko: "릴스 5분 단타 (볼린저 20·2 + 200선)"}),
      copy: fmt.acctName({kind: "copy", strategy: "S5_DONCHIAN_MFI", timeframe: "1h", name_ko: "돈치안·MFI 복제"}),
      tz: fmt.tone(-0.0003, fmt.pct(-0.0003)), tn: fmt.tone(-0.03, fmt.pct(-0.03)),
      sg: fmt.SERVER_GROUP}));""")
    assert out["ds"] == {"name": "뉴욕 개장 1시간 방향", "tf": "15분"}
    assert out["core"] == "돈치안·MFI · 1시간" and out["reel"] == "릴스 5분 단타 · 5분" and out["copy"] == "돈치안·MFI 복제 · 1시간"
    assert out["tz"] == "" and out["tn"] == "down"                      # "0.0%" is never painted red
    assert out["sg"] == {"core": "core", "ds200": "ds", "reel": "m5", "flip": "coin", "extra": "extra"}


def test_busts_fold_into_one_banner_line_and_bursts_count_announced_groups_only():
    out = _node("""
    const now = 1_800_000_000_000, M = 60_000;
    const L = (o) => alerts.criticalLines({health: null, alerts: [], trades: [], hb: null, streamOk: false, now, ...o});
    const B = (k, id) => ({ts: now - k * M, level: "CRITICAL", text: `[${id}] BUST equity 7.3`});
    const T = (k, kind) => ({exit_reason: "LIQ", exit_time: now - k * M, account_id: "X@15m", kind});
    console.log(JSON.stringify({
      busts: L({alerts: [B(5, "S5_DONCHIAN_MFI@15m"), B(9, "F9_FVG@30m"), B(12, "F9_FVG@30m"), B(30, "RANDOM_1@1h")]}),
      dsBurst: L({trades: [T(1, "ds200"), T(2, "ds200"), T(3, "random"), T(4, "ds200")]}),
      coreBurst: L({trades: [T(1, "strategy"), T(2, "reel"), T(3, "copy")]}),
      lookup: L({trades: [T(1), T(2), T(3)].map((t) => ({...t, kind: undefined})), kindOf: () => "ds200"}),
    }));""")
    b = out["busts"]
    assert len(b) == 1 and b[0]["kind"] == "bust" and b[0]["id"] == f"bust-{1_800_000_000_000 - 5 * 60_000}"
    assert b[0]["text"].startswith("파산 3개 계좌")
    assert out["dsBurst"] == [] and out["lookup"] == []
    assert out["coreBurst"][0]["kind"] == "liq"


def test_the_board_is_patched_from_the_stream_not_refetched_per_event():
    store = _read(os.path.join(V4, "core", "store.js"))
    assert 'bus.on("trades"' not in store                       # a closed trade no longer re-downloads the board
    assert "BOARD_MIN_GAP = 15000" in store and 'document.visibilityState === "hidden"' in store
    pk = _read(os.path.join(V4, "screens", "positions-kit.js"))
    assert "p.tp ?? p.tp_price" in pk and "p.time_exit ?? rx.end" in pk    # app.board_position field names
    assert "loadReel" not in _read(os.path.join(V4, "screens", "positions.js"))
    assert "/api/trades?limit=${" not in _read(os.path.join(V4, "screens", "home-today.js"))


def test_rows_use_the_servers_group_and_exits_and_5m_flips_count_as_coin_flips():
    out = _node("""console.log(JSON.stringify({
      g1: fmt.groupOf({kind: "random", timeframe: "5m", group: "flip"}), g2: fmt.groupOf({kind: "reel", group: "reel"}),
      g3: fmt.groupOf({kind: "newlab", group: "extra"}), g4: fmt.groupOf({kind: "random", timeframe: "5m"}),
      g5: fmt.groupOf({kind: "ds200", group: "nonsense"}),
      e1: fmt.ownExits({kind: "random", timeframe: "5m"}), e2: fmt.ownExits({kind: "random", timeframe: "5m", exits: "house"}),
      e3: fmt.ownExits({kind: "strategy", exits: "reel"}), e4: fmt.ownExits({kind: "reel"}), f5: fmt.isFlip5({kind: "random", timeframe: "5m"})}));""")
    assert out == {"g1": "coin", "g2": "m5", "g3": "extra", "g4": "coin", "g5": "ds",
                   "e1": True, "e2": False, "e3": True, "e4": True, "f5": True}
    home = _read(os.path.join(V4, "screens", "home-shared.js"))
    assert "비교: 5분봉 동전" in home and "(동전 봇에서 셈)" in home         # the 5분봉 card's labelled comparison
    assert "5분 포함" not in _read(os.path.join(V4, "screens", "home-today.js"))


def test_method_and_rules_texts_come_from_the_server():
    """No typed-in verdict method (2,000개 / FDR 10% / 규칙 변경 1) and no fallback to the v3 rules-change document:
    the server's restart.method_ko / n_bots / rules_label / doc, else neutral words."""
    for p in _files((".js",)):
        src = _read(p)
        for bad in ("2,000개", "FDR 10%", "규칙 변경 1", "/api/doc/rules-change-1", "동전 봇 10,000개"):
            assert bad not in src, (p, bad)
    shell = _read(os.path.join(V4, "core", "shell.js"))
    assert "setMethod(s.restart)" in shell and "rs.rules_label" in shell and "methodKo()" in shell


def test_loss_cards_show_own_exits_and_skip_the_house_stop_what_if():
    src = _read(os.path.join(V4, "screens", "strategies-panels.js"))
    body = src[src.index("export function lossCard"):src.index("export function tagRows")]
    assert "c.exits_ko" in body and "c.stop_ko" in body
    assert re.search(r'c\.exits === "reel" \? null : h\("p", \{class: "muted"\}, "손절 거리를 바꿨다면: "', body)
    assert "export function researchBody" in src


def test_v4_strategy_views_and_curves_are_asked_for():
    chart = _read(os.path.join(V4, "screens", "strategies-chart.js"))
    assert 'kind === "ds200" || kind === "reel"' in chart and "lineType: ov.step ? 1 : 0" in chart
    det = _read(os.path.join(V4, "screens", "strategies-detail.js"))
    assert "loadView(ctx, name, v.tf, v.sym, st.list36, kind)" in det and "researchBody(v.profile, v.tf)" in det
    home = _read(os.path.join(V4, "screens", "home.js"))
    assert '"/api/v4/curves?step=3600000"' in home and "curvesOn = false" in home
    assert '"/api/v4/server"' in _read(os.path.join(V4, "screens", "server.js"))
