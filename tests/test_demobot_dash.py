"""Demo lab dashboard (demobot/dash): login, the read-only snapshot API on a fake snapshot folder, the ranking table's
filters / sorting / paging, strict query validation, and the static page's safety rules."""
import glob
import json
import math
import os
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from demobot import grid
from demobot.dash import fake
from demobot.dash.app import COOKIE, CSP, check_password, create_app, hash_password

PW = "correct horse battery staple"
SECRET = b"s" * 40
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "demobot", "dash", "static")
SNAP_ROUTES = ("status", "home", "accounts", "trades", "judge", "rank_meta")


@pytest.fixture(scope="module")
def folders(tmp_path_factory):
    root = tmp_path_factory.mktemp("demosnap")
    snap, data = str(root / "snap"), str(root / "data")
    facts = fake.build(snap, past5y_dir=data)
    return {"snap": snap, "data": data, "facts": facts}


@pytest.fixture(scope="module")
def pw_hash():
    return hash_password(PW)


@pytest.fixture(scope="module")
def app(folders, pw_hash):
    return create_app(folders["snap"], pw_hash, SECRET, data_dir=folders["data"])


@pytest.fixture()
def anon(app):
    return TestClient(app)


@pytest.fixture(scope="module")
def client(app):
    c = TestClient(app)
    r = c.post("/login", json={"password": PW})
    assert r.status_code == 200 and c.cookies.get(COOKIE)
    return c


def _file(folders, *parts):
    with open(os.path.join(folders["snap"], *parts), encoding="utf-8") as f:
        return json.load(f)


def _npz(folders, strat="S2_ST_ROC", tf="15m"):
    with np.load(os.path.join(folders["snap"], f"rank_{strat}_{tf}.npz")) as z:
        return {k: z[k] for k in z.files}


# ---------------------------------------------------------------- login
def test_pages_and_every_api_route_need_the_login(anon):
    r = anon.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/"
    assert anon.get("/static/js/app.js", follow_redirects=False).status_code == 303
    assert anon.get("/static/index.html", follow_redirects=False).status_code == 303
    for path in [f"/api/{k}" for k in SNAP_ROUTES] + ["/api/account/fx-def-S2-15m", "/api/rank", "/api/rank?strat=N02",
                                                      "/api/grid"]:
        r = anon.get(path)
        assert r.status_code == 401, path
        assert "accounts" not in r.text and "luck" not in r.text
    # the login page and what it needs are public, and carry the same headers
    r = anon.get("/login")
    assert r.status_code == 200 and "<form" in r.text and r.headers["content-security-policy"] == CSP
    assert anon.get("/static/login.js").status_code == 200


def test_wrong_password_is_refused(anon):
    r = anon.post("/login", json={"password": "wrong password here"})
    assert r.status_code == 401 and not anon.cookies.get(COOKIE)
    r = anon.post("/login", data={"password": "nope", "next": "/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?e=1")
    assert "set-cookie" not in r.headers
    assert anon.get("/api/status").status_code == 401
    # a forged or expired cookie is not a session
    anon.cookies.set(COOKIE, "9999999999.deadbeef")
    assert anon.get("/api/status").status_code == 401


def test_login_works_with_a_hash_made_by_the_module(anon, pw_hash):
    assert pw_hash.startswith("pbkdf2$") and check_password(PW, pw_hash) and not check_password("x", pw_hash)
    r = anon.post("/login", data={"password": PW, "next": "/#/rank"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#/rank"
    sc = r.headers["set-cookie"]
    assert sc.startswith(COOKIE + "=") and "HttpOnly" in sc and "samesite=strict" in sc.lower()
    assert anon.get("/api/status").status_code == 200
    assert anon.get("/").status_code == 200
    # a next that leaves the site falls back to the front page
    r = anon.post("/login", data={"password": PW, "next": "//evil.example/x"}, follow_redirects=False)
    assert r.headers["location"] == "/"
    # logout clears the cookie
    r = anon.post("/logout", follow_redirects=False)
    assert r.status_code == 303 and COOKIE in r.headers.get("set-cookie", "")


def test_cross_site_login_is_refused(anon):
    r = anon.post("/login", json={"password": PW}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and not anon.cookies.get(COOKIE)
    r = anon.post("/login", json={"password": PW}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = anon.post("/login", json={"password": PW}, headers={"Origin": "https://testserver"})   # other scheme
    assert r.status_code == 403
    r = anon.post("/login", json={"password": PW}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200


def test_too_many_wrong_passwords_wait(folders, pw_hash):
    c = TestClient(create_app(folders["snap"], pw_hash, SECRET))
    for _ in range(10):
        assert c.post("/login", json={"password": "bad"}).status_code == 401
    assert c.post("/login", json={"password": PW}).status_code == 429


def test_main_refuses_to_start_without_hash_and_secret(monkeypatch, capsys):
    from demobot.dash import __main__ as cli
    monkeypatch.delenv("DEMOBOT_DASH_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("DEMOBOT_DASH_SECRET", "x" * 40)
    assert cli.main(["serve", "--snap", "/nonexistent"]) == 1
    monkeypatch.setenv("DEMOBOT_DASH_PASSWORD_HASH", hash_password(PW, rounds=1000))
    monkeypatch.setenv("DEMOBOT_DASH_SECRET", "too-short")
    assert cli.main(["serve"]) == 1
    # hash: prints a hash the dashboard accepts
    answers = iter([PW, PW])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    capsys.readouterr()
    assert cli.main(["hash"]) == 0
    out = capsys.readouterr().out.strip()
    assert check_password(PW, out)


# ---------------------------------------------------------------- snapshot API
def test_every_api_returns_the_fake_snapshot(client, folders):
    for key in SNAP_ROUTES:
        r = client.get(f"/api/{key}")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store", key
        assert r.json() == _file(folders, f"{key}.json"), key
    accts = _file(folders, "accounts.json")["accounts"]
    assert len(accts) == 48 and len({a["id"] for a in accts}) == 48
    for a in accts:
        r = client.get(f"/api/account/{a['id']}")
        assert r.status_code == 200
        d = r.json()
        assert d == _file(folders, "acct", a["id"] + ".json")
        assert set(d["curves"]) == {"20", "30", "40", "50"} and all(len(v) <= 800 for v in d["curves"].values())
        assert len(d["trades"]) <= 600
    g = client.get("/api/grid").json()
    assert [x["name"] for x in g["exits"]] == list(grid.EXITS) and g["exits"][0]["ko"] == grid.exit_ko(0)
    assert {s["short"]: s["settings"] for s in g["strategies"]} == {"S2": 343, "N02": 735, "N04": 588}


def test_big_answers_are_gzipped(client):
    r = client.get("/api/accounts", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_the_fake_has_every_contract_file_with_the_exact_shapes(folders):
    names = set(os.listdir(folders["snap"]))
    assert {"status.json", "home.json", "accounts.json", "trades.json", "judge.json", "rank_meta.json", "acct"} <= names
    for strat in grid.STRATS:
        for tf in grid.TFS:
            z = _npz(folders, strat, tf)
            C = grid.NCOMBO[strat]
            assert z["stats"].shape == (3, 13, 8, C, 11) and z["stats"].dtype == np.float32
            assert z["luck95"].shape == (3, 13, 8) and z["luck95"].dtype == np.float32
            assert z["min_n"].shape == (3, 2) and z["min_n"].dtype == np.int32
            assert z["bounds_ms"].shape == (3, 2) and z["bounds_ms"].dtype == np.int64
            assert z["generated_ms"].shape == () and z["generated_ms"].dtype == np.int64
            with np.load(os.path.join(folders["data"], f"past5y_{strat}_{tf}.npz")) as p:
                assert p["stats"].shape == (6, 13, 8, C, 3)
    st = _file(folders, "status.json")
    assert st["phase"] == "live" and st["counts"]["settings"] == 1666 and st["leverages"] == [20, 30, 40, 50]
    j = _file(folders, "judge.json")
    assert len(j["rows"]) == 48 * 4 and j["verdict_ko"].startswith("실전 금지")


def test_missing_files_answer_missing(tmp_path, pw_hash):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(create_app(str(snap), None, SECRET, data_dir=str(tmp_path / "nodata")))
    for key in SNAP_ROUTES:
        r = c.get(f"/api/{key}")
        assert r.status_code == 200 and r.json() == {"missing": True}, key
    assert c.get("/api/account/fx-def-S2-15m").json() == {"missing": True}
    r = c.get("/api/rank?strat=N04&tf=30m")
    assert r.status_code == 200 and r.json()["missing"] is True
    # status only (the first minutes of a warm-up): that one is there, the rest still missing
    fake.build(str(snap), phase="warm", empty=True)
    assert c.get("/api/status").json()["phase"] == "warm"
    assert c.get("/api/home").json() == {"missing": True}


def test_account_ids_are_validated(client):
    for bad in ("ab", "x" * 41, "fx_def_S2", "fx.def", "fx%2F..%2Fstatus", "%2e%2e", "fx%20def"):
        assert client.get(f"/api/account/{bad}").status_code in (400, 404), bad
    for bad in ("ab", "x" * 41, "fx_def_S2", "fx.def", "fx%20def"):
        assert client.get(f"/api/account/{bad}").status_code == 400, bad
    r = client.get("/api/account/fx-def-S9-15m")          # well formed, not there
    assert r.status_code == 200 and r.json() == {"missing": True}


def test_snapshot_changes_are_picked_up_and_nan_becomes_null(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(create_app(str(snap), None, SECRET))
    (snap / "status.json").write_text('{"phase": "warm", "tick_seconds": NaN}')
    d = c.get("/api/status").json()
    assert d == {"phase": "warm", "tick_seconds": None}
    (snap / "status.json").write_text('{"phase": "live", "x": 1}')
    os.utime(snap / "status.json", (1e9 + 5, 1e9 + 5))
    assert c.get("/api/status").json()["phase"] == "live"
    # a broken file: the last good copy is kept
    (snap / "status.json").write_text('{"phase": ')
    os.utime(snap / "status.json", (1e9 + 9, 1e9 + 9))
    assert c.get("/api/status").json()["phase"] == "live"


def test_no_endpoint_writes_anything(client, folders):
    def listing():
        out = {}
        for root in (folders["snap"], folders["data"]):
            for p in glob.glob(os.path.join(root, "**"), recursive=True):
                out[p] = os.stat(p).st_mtime_ns
        return out
    before = listing()
    for key in SNAP_ROUTES:
        client.get(f"/api/{key}")
    client.get("/api/rank?strat=N02&tf=30m&exit=5&scope=BTCUSD&window=4w&win60=1&low_whip=1&min_ok=1")
    client.get("/api/account/ad-r26-S2-15m")
    assert listing() == before
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)("/api/status").status_code == 405


# ---------------------------------------------------------------- the ranking table
def _cell(folders, strat="S2_ST_ROC", tf="15m", w="26w", e=0, s="ALL"):
    z = _npz(folders, strat, tf)
    return z, z["stats"][grid.WINDOWS.index(w), e, grid.SCOPES.index(s)].astype(float)


def _all_rows(client, query):
    rows, off = [], 0
    while True:
        d = client.get(f"/api/rank?{query}&limit=200&offset={off}").json()
        rows += d["rows"]
        off += 200
        if off >= d["total"]:
            return d, rows


def test_rank_rows_carry_labels_marks_and_derived_fields(client, folders):
    d = client.get("/api/rank").json()
    assert (d["strategy"], d["tf"], d["window"], d["exit"], d["scope"], d["sort"]) == ("S2_ST_ROC", "15m", "26w", 0, "ALL", "plateau")
    assert d["total"] == 343 and len(d["rows"]) == 50 and d["past5y"] is True
    z, cell = _cell(folders)
    luck = float(z["luck95"][1, 0, 0])
    plateau = grid.plateau(cell[:, 0], cell[:, 2], "S2_ST_ROC", int(z["min_n"][1, 0]))   # the study's score
    assert d["luck95"] == pytest.approx(luck, abs=1e-5)
    assert d["bounds_ms"] == [int(x) for x in z["bounds_ms"][1]] and d["min_n"] == int(z["min_n"][1, 0])
    for r in d["rows"]:
        c = r["c"]
        n, wins, mR, mG, aw, al = cell[c, 0], cell[c, 1], cell[c, 2], cell[c, 3], cell[c, 6], cell[c, 7]
        assert r["label"] == grid.combo_label("S2_ST_ROC", c)
        assert r["n"] == int(n) and r["win_rate"] == pytest.approx(wins / n, abs=1e-4)
        assert r["breakeven_win"] == pytest.approx(al / (aw + al), abs=1e-4)
        assert r["cost_R"] == pytest.approx(mG - mR, abs=1e-4)
        assert r["beats_luck"] == bool(mR > luck)
        assert r["min_ok"] == bool(n >= d["min_n"])
        if r["plateau"] is not None:
            assert r["plateau"] == pytest.approx(plateau[c], abs=1e-3)
        assert set(r["past"]) == set(d["periods"])
    # the three marked settings are found by their labels
    for flag, c in (("is_default", grid.default_combo("S2_ST_ROC")), ("is_friend", grid.friend_combo("S2_ST_ROC")),
                    ("is_pick", grid.PICK[("S2_ST_ROC", "15m")])):
        rows = client.get("/api/rank?q=" + grid.combo_label("S2_ST_ROC", c).replace(" ", "+")).json()["rows"]
        row = next(r for r in rows if r["c"] == c)
        assert row[flag] is True
    assert not any(r["is_friend"] for r in _all_rows(client, "strat=N02")[1])     # N02 has no friend value


@pytest.mark.parametrize("sort", ["plateau", "mean_R", "win_rate", "n", "mdd_R", "whip", "mean_G"])
def test_rank_sort_order(client, sort):
    for q, desc in ((f"sort={sort}", sort not in ("mdd_R", "whip")), (f"sort={sort}&dir=asc", False),
                    (f"sort={sort}&dir=desc", True)):
        d, rows = _all_rows(client, f"strat=N04&tf=30m&window=live&{q}")
        assert len(rows) == d["total"] == 588
        vals = [r[sort] for r in rows]
        finite = [v for v in vals if v is not None]
        assert vals[:len(finite)] == finite, "empty values come last"
        assert finite == sorted(finite, reverse=desc), q
        assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))


def test_rank_filters(client, folders):
    z, cell = _cell(folders, "N02_ST_KST", "15m", "26w", 1, "BTCUSD")
    n = cell[:, 0]
    wr = np.where(n > 0, cell[:, 1] / np.where(n > 0, n, 1), -1)
    base = "strat=N02&tf=15m&window=26w&exit=1&scope=BTCUSD"
    d, rows = _all_rows(client, base + "&win60=1")
    assert d["total"] == int((wr >= 0.6).sum()) > 0
    assert all(r["win_rate"] >= 0.6 for r in rows)
    min_n = int(z["min_n"][1, 1])                                   # the per-coin minimum
    d, rows = _all_rows(client, base + "&min_ok=1")
    assert d["total"] == int((n >= min_n).sum()) and all(r["n"] >= min_n and r["min_ok"] for r in rows)
    d, rows = _all_rows(client, base + "&min_ok=1&low_whip=1")
    group = cell[n >= min_n, 5]
    assert d["whip_median"] == pytest.approx(float(np.median(group)), abs=1e-4)
    assert d["total"] == int((group <= np.median(group)).sum())
    assert all(r["whip"] <= d["whip_median"] + 1e-6 for r in rows)
    d, rows = _all_rows(client, base + "&q=st+10%2F6")
    assert d["total"] > 0 and all("st 10/6" in r["label"].lower() for r in rows)
    assert d["total"] == sum("st 10/6" in grid.combo_label("N02_ST_KST", c).lower() for c in range(735))
    d = client.get("/api/rank?" + base + "&q=nothing+like+this").json()
    assert d["total"] == 0 and d["rows"] == []


def test_rank_paging_and_the_limit_cap(client):
    full = client.get("/api/rank?strat=S2&limit=200").json()
    assert len(full["rows"]) == 200
    pages = []
    for off in range(0, 200, 30):
        pages += client.get(f"/api/rank?strat=S2&limit=30&offset={off}").json()["rows"]
    assert [r["c"] for r in pages[:200]] == [r["c"] for r in full["rows"]]
    last = client.get("/api/rank?strat=S2&limit=200&offset=300").json()
    assert len(last["rows"]) == 43 and last["rows"][0]["rank"] == 301
    assert client.get("/api/rank?strat=S2&offset=5000").json()["rows"] == []
    assert client.get("/api/rank?limit=201").status_code == 400
    assert client.get("/api/rank?limit=0").status_code == 400


@pytest.mark.parametrize("query", [
    "strat=S9", "strat=s2", "tf=1h", "exit=13", "exit=-1", "exit=house2", "scope=BTC", "scope=all", "window=1y",
    "sort=pnl", "dir=up", "limit=abc", "limit=-5", "offset=-1", "offset=1e3", "min_ok=maybe", "win60=2",
    "low_whip=yes%20please", "q=%3Cscript%3E", "q=" + "a" * 41, "nope=1", "strat=S2&strat=N02",
])
def test_rank_bad_parameters_are_400(client, query):
    assert client.get("/api/rank?" + query).status_code == 400


def test_rank_takes_full_names_and_exit_names_and_scopes(client, folders):
    d = client.get("/api/rank?strat=N04_ST_KLINGER&tf=30m&exit=tp1.5R_sl2atr&scope=XRPUSD&window=4w").json()
    assert (d["strategy"], d["exit"], d["exit_name"], d["scope"]) == ("N04_ST_KLINGER", 6, "tp1.5R_sl2atr", "XRPUSD")
    assert d["exit_ko"] == "익절 1.5R · 손절 2ATR" and d["total"] == 588
    z, cell = _cell(folders, "N04_ST_KLINGER", "30m", "4w", 6, "XRPUSD")
    assert d["min_n"] == int(z["min_n"][2, 1])                     # the per-coin minimum
    # crash months were computed only for the house exit in the fake 5-year file
    r = d["rows"][0]
    assert r["past"]["2022-05"]["mean_R"] is None and r["past"]["2021-23"]["mean_R"] is not None


def test_rank_without_5y_file_or_with_a_bad_shape(tmp_path, folders):
    snap = tmp_path / "snap"
    snap.mkdir()
    os.link(os.path.join(folders["snap"], "rank_S2_ST_ROC_15m.npz"), snap / "rank_S2_ST_ROC_15m.npz")
    c = TestClient(create_app(str(snap), None, SECRET, data_dir=str(tmp_path / "nodata")))
    d = c.get("/api/rank").json()
    assert d["past5y"] is False and all(r["past"] is None for r in d["rows"])
    # a cell whose luck line is not computed yet (NaN) and settings without trades: empty values, never an error
    z = _npz(folders, "N02_ST_KST", "30m")
    z["luck95"][:] = np.nan
    z["stats"][0, 0, 0, :5] = np.nan
    np.savez(snap / "rank_N02_30m.npz", **z)                          # the engine's short file name
    d = c.get("/api/rank?strat=N02&tf=30m&window=live&sort=mean_R").json()
    assert d["luck95"] is None and all(r["beats_luck"] is None for r in d["rows"])
    rows = _all_rows(c, "strat=N02&tf=30m&window=live&sort=mean_R")[1]
    assert [r["c"] for r in rows[-5:]] == [0, 1, 2, 3, 4] and rows[-1]["n"] == 0 and rows[-1]["mean_R"] is None
    np.savez(snap / "rank_N04_ST_KLINGER_15m.npz", stats=np.zeros((3, 13, 8, 10, 11), np.float32))
    d = c.get("/api/rank?strat=N04").json()
    assert d["missing"] is True and d["bad_shape"] is True


# ---------------------------------------------------------------- the page
def _static_files(ext):
    out = []
    for p in glob.glob(os.path.join(STATIC, "**", "*" + ext), recursive=True):
        if os.sep + "vendor" + os.sep not in p:
            out.append(p)
    return out


def test_static_js_builds_dom_from_text_only_and_calls_no_outside_host():
    files = _static_files(".js")
    assert len(files) >= 10
    for p in files:
        src = open(p, encoding="utf-8").read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function"):
            assert bad not in src, f"{os.path.basename(p)} uses {bad}"
        assert not re.search(r"\beval\s*\(", src), p
        assert not re.search(r"setTimeout\(\s*['\"`]", src), p
        for m in re.finditer(r"https?://([^/\s\"'`)]+)", src):
            assert m.group(1) == "www.w3.org", f"{os.path.basename(p)} names an outside host {m.group(1)}"
        assert "toLocaleString" not in src and "Intl." not in src, p


def test_html_and_css_load_nothing_from_outside():
    for p in _static_files(".html"):
        src = open(p, encoding="utf-8").read()
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", src), f"inline script in {p}"
        assert not re.search(r"\son\w+\s*=", src), f"inline handler in {p}"
        for m in re.finditer(r"(?:src|href|action)=\"([^\"]+)\"", src):
            assert m.group(1).startswith(("/", "#")), f"{os.path.basename(p)}: {m.group(1)}"
    for p in _static_files(".css"):
        src = open(p, encoding="utf-8").read()
        for m in re.finditer(r"url\(([^)]*)\)", src):
            assert m.group(1).strip("'\"").startswith("data:"), f"{os.path.basename(p)}: {m.group(1)[:40]}"
    # the demo lab's own css takes its colours from the tokens only (both skins)
    demo = open(os.path.join(STATIC, "demo.css"), encoding="utf-8").read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", demo) and "rgb(" not in demo and "hsl(" not in demo
    tokens = open(os.path.join(STATIC, "tokens.css"), encoding="utf-8").read()
    assert ':root:not([data-skin="classic"])' in tokens                # both skins kept


def test_served_html_has_the_csp_and_the_demo_badge(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp
    assert "http" not in csp
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert "데모 랩" in r.text and 'type="module" src="/static/js/app.js"' in r.text
    for path in ("/static/js/app.js", "/static/demo.css", "/static/vendor/lightweight-charts.standalone.production.js"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-security-policy"] == CSP, path
    assert client.get("/api/status").headers["content-security-policy"] == CSP


def test_every_screen_module_exists_and_mounts():
    app_js = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    names = re.search(r"const SCREENS = \{([^}]*)\}", app_js).group(1)
    for name in re.findall(r"(\w+): \"(\w+)\"", names):
        p = os.path.join(STATIC, "js", "screens", name[1] + ".js")
        assert os.path.exists(p), p
        assert "export async function mount(" in open(p, encoding="utf-8").read(), p
    for menu in ("홈", "순위표", "계좌", "거래 기록", "판정", "서버 상태", "어떻게 돌아가나"):
        assert f'ko: "{menu}"' in app_js


def test_the_fake_is_deterministic(tmp_path, folders):
    fake.build(str(tmp_path / "again"))
    for name in ("accounts.json", "judge.json", "home.json", "status.json"):
        with open(tmp_path / "again" / name, "rb") as a, open(os.path.join(folders["snap"], name), "rb") as b:
            assert a.read() == b.read(), name
    a, b = _npz(folders, "N02_ST_KST", "30m"), np.load(tmp_path / "again" / "rank_N02_ST_KST_30m.npz")
    assert np.array_equal(a["stats"], b["stats"], equal_nan=True)
    assert math.isfinite(float(a["luck95"][1, 0, 0]))
