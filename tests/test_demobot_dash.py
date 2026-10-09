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
SNAP_ROUTES = ("status", "home", "accounts", "trades", "judge", "rank_meta", "views")


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
    assert len(accts) == 50 and len({a["id"] for a in accts}) == 50          # the 48 + two private (CONTRACT 7.2)
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
            E = grid.NEXIT                                          # 14 since CONTRACT 7.1
            assert z["stats"].shape == (3, E, 8, C, 11) and z["stats"].dtype == np.float32
            assert z["luck95"].shape == (3, E, 8) and z["luck95"].dtype == np.float32
            assert z["min_n"].shape == (3, 2) and z["min_n"].dtype == np.int32
            assert z["bounds_ms"].shape == (3, 2) and z["bounds_ms"].dtype == np.int64
            assert z["generated_ms"].shape == () and z["generated_ms"].dtype == np.int64
            with np.load(os.path.join(folders["data"], f"past5y_{strat}_{tf}.npz")) as p:
                assert p["stats"].shape == (6, E, 8, C, 3)
    st = _file(folders, "status.json")
    assert st["phase"] == "live" and st["counts"]["settings"] == 1666 and st["leverages"] == [20, 30, 40, 50]
    j = _file(folders, "judge.json")
    assert len(j["rows"]) == 50 * 4 and j["verdict_ko"].startswith("실전 금지")
    v = _file(folders, "views.json")
    assert set(v["summary"]) >= {"n", "n_done", "need", "verdict_ko", "dir", "reached_rate", "follow"}
    assert set(v["summary"]["follow"]) == {"touch", "confirm"} and set(v["summary"]["dir"]) == {"4h", "24h", "48h"}
    ts = [x["t_ms"] for x in v["views"]]
    assert 0 < len(ts) <= 300 and ts == sorted(ts, reverse=True)
    for x in v["views"]:
        assert x["side"] in (1, -1) and x["coin"] in grid.COINS and x["status"] in ("watching", "done", "cancelled")
        assert any(x["zones"][k] for k in ("A", "B", "C"))
        assert set(x["follow"]) == {"touch", "confirm"}
        assert all(f["status"] in ("waiting", "open", "closed", "missed") for f in x["follow"].values())


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
    "strat=S9", "strat=s2", "tf=1h", f"exit={grid.NEXIT}", "exit=99", "exit=-1", "exit=house2", "scope=BTC", "scope=all", "window=1y",
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
    for menu in ("홈", "순위표", "계좌", "거래 기록", "판정", "관점 기록", "서버 상태", "어떻게 돌아가나"):
        assert f'ko: "{menu}"' in app_js


def test_the_fake_is_deterministic(tmp_path, folders):
    fake.build(str(tmp_path / "again"))
    for name in ("accounts.json", "judge.json", "home.json", "status.json"):
        with open(tmp_path / "again" / name, "rb") as a, open(os.path.join(folders["snap"], name), "rb") as b:
            assert a.read() == b.read(), name
    a, b = _npz(folders, "N02_ST_KST", "30m"), np.load(tmp_path / "again" / "rank_N02_ST_KST_30m.npz")
    assert np.array_equal(a["stats"], b["stats"], equal_nan=True)
    assert math.isfinite(float(a["luck95"][1, 0, 0]))


# ---------------------------------------------------------------- round 2 (CONTRACT section 7)
def test_views_route_needs_login_and_returns_the_snapshot(anon, client, folders, tmp_path):
    assert anon.get("/api/views").status_code == 401
    d = client.get("/api/views").json()
    assert d == _file(folders, "views.json")
    assert any("<b>" in v["memo"] for v in d["views"])           # a memo with markup comes back as plain text data
    s = d["summary"]
    assert s["n_done"] >= 30 and not s["verdict_ko"].startswith("표본 부족")
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(create_app(str(snap), None, SECRET))
    assert c.get("/api/views").json() == {"missing": True}
    few = fake.fake_views(np.random.default_rng(1), 8)            # under 30 finished views: 표본 부족
    assert few["summary"]["verdict_ko"].startswith("표본 부족") and few["summary"]["n_done"] < 30


def test_private_accounts_are_in_the_fake_with_neutral_names(folders):
    accts = _file(folders, "accounts.json")["accounts"]
    pv = [a for a in accts if a["kind"] == "private"]
    assert len(pv) == 2 and all(a["id"].startswith("pv-") for a in pv)
    assert all(a["name"].startswith("비공개 ") and a["strategy"] is None for a in pv)
    assert set(pv[0]["lines"]) == {"20", "30", "40", "50"}
    home = _file(folders, "home.json")
    assert "private" in [k["kind"] for k in home["by_kind"]]
    labels = open(os.path.join(STATIC, "js", "labels.js"), encoding="utf-8").read()
    assert 'pv: "private"' in labels and '"비공개 매매법"' in labels


def test_rank_with_14_exits_and_a_13_exit_5y_file(tmp_path, folders):
    assert grid.NEXIT == 14 and grid.EXITS[13] == "half1R_be_1.5R"
    c = TestClient(create_app(folders["snap"], None, SECRET, data_dir=folders["data"]))
    for ex in ("13", "half1R_be_1.5R"):
        d = c.get(f"/api/rank?strat=S2&exit={ex}").json()
        assert d["exit"] == 13 and d["exit_ko"] == grid.exit_ko(13) and d["total"] == 343 and d["past5y_exit"] is True
    g = c.get("/api/grid").json()
    assert len(g["exits"]) == grid.NEXIT and g["exits"][13]["ko"] == grid.exit_ko(13)
    # a 5-year file written before exit 13 existed: the exit's 5-year columns are empty, the others still filled
    data = tmp_path / "data"
    data.mkdir()
    with np.load(os.path.join(folders["data"], "past5y_S2_ST_ROC_15m.npz")) as p:
        np.savez(data / "past5y_S2_15m.npz", stats=p["stats"][:, :13])
    c = TestClient(create_app(folders["snap"], None, SECRET, data_dir=str(data)))
    d = c.get("/api/rank?strat=S2&exit=13").json()
    assert d["past5y"] is True and d["past5y_exit"] is False
    assert all(v["mean_R"] is None and v["n"] is None for r in d["rows"] for v in r["past"].values())
    d = c.get("/api/rank?strat=S2&exit=0").json()
    assert d["past5y_exit"] is True and any(r["past"]["2021-23"]["mean_R"] is not None for r in d["rows"])
    # a ranking file written before exit 13 existed: that exit is 'not there yet', the others still work
    snap = tmp_path / "snap"
    snap.mkdir()
    z = _npz(folders)
    np.savez(snap / "rank_S2_15m.npz", **{**z, "stats": z["stats"][:, :13], "luck95": z["luck95"][:, :13]})
    c = TestClient(create_app(str(snap), None, SECRET, data_dir=str(data)))
    d = c.get("/api/rank?strat=S2&exit=13").json()
    assert d["missing"] is True and d["exit_not_in_file"] is True
    d = c.get("/api/rank?strat=S2&exit=12").json()
    assert d["total"] == 343 and d["luck95"] is not None


# ---------------------------------------------------------------- round 3 (CONTRACT section 8)
NEW_FILES = {"costs": "costs.json", "regime": "regime.json", "backup": "backup.json", "watch": "watch.json",
             "review": "review.json", "telegram": "telegram.json"}
NEW_ROUTES = [f"/api/{k}" for k in NEW_FILES] + ["/api/bars?coin=BTCUSD", "/api/bars?coin=ETHUSD&tf=30m", "/api/coins"]


def _bars_file(folders, coin="BTCUSD"):
    with np.load(os.path.join(folders["snap"], "bars", coin + ".npz")) as z:
        return {k: z[k] for k in z.files}


def test_new_routes_need_the_login(anon):
    for path in NEW_ROUTES:
        r = anon.get(path)
        assert r.status_code == 401, path
        assert "bars" not in r.text and "coins" not in r.text and "items" not in r.text


def test_new_snapshot_routes_return_the_files_and_take_no_parameters(client, folders):
    for key, name in NEW_FILES.items():
        r = client.get(f"/api/{key}")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store", key
        assert r.json() == _file(folders, name), key
        assert client.get(f"/api/{key}?x=1").status_code == 400, key
    assert client.get("/api/coins?coin=BTCUSD").status_code == 400
    # the existing routes pass the new fields of section 8 through as they are
    j = client.get("/api/judge").json()
    assert {"confirm", "candidates", "lines_judged", "multi_note_ko", "stop_rules_ko"} <= set(j)
    assert all("stops" in r and "confirm" in r for r in j["rows"])
    home = client.get("/api/home").json()
    assert {"goal", "regime_now", "costs_now"} <= set(home)
    assert "deadman" in client.get("/api/status").json()
    a = client.get("/api/account/fx-def-S2-15m").json()
    assert {"curves_stops", "stop_events"} <= set(a)


def test_new_files_missing_answer_missing(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(create_app(str(snap), None, SECRET, data_dir=str(tmp_path / "nodata")))
    for key in NEW_FILES:
        r = c.get(f"/api/{key}")
        assert r.status_code == 200 and r.json() == {"missing": True}, key
    assert c.get("/api/coins").json() == {"missing": True}
    r = c.get("/api/bars?coin=SOLUSD&tf=30m")
    assert r.status_code == 200 and r.json() == {"missing": True, "coin": "SOLUSD", "tf": "30m"}
    # --empty (the first minutes of a warm-up): status only, with the dead-man field; everything new still missing
    fake.build(str(snap), phase="warm", empty=True)
    assert sorted(os.listdir(snap)) == ["status.json"]
    assert c.get("/api/status").json()["deadman"]["configured"] is True
    assert c.get("/api/costs").json() == {"missing": True} and c.get("/api/bars?coin=BTCUSD").json()["missing"] is True


@pytest.mark.parametrize("query", [
    "", "coin=BTC", "coin=btcusd", "coin=BTCUSDT", "coin=..%2Fstatus", "coin=BTCUSD&tf=1h", "coin=BTCUSD&tf=15M",
    "coin=BTCUSD&from=-1", "coin=BTCUSD&from=1e12", "coin=BTCUSD&to=abc", "coin=BTCUSD&from=" + "9" * 16,
    "coin=BTCUSD&from=20&to=10", "coin=BTCUSD&limit=0", "coin=BTCUSD&limit=3001", "coin=BTCUSD&limit=x",
    "coin=BTCUSD&nope=1", "coin=BTCUSD&coin=ETHUSD", "coin=BTCUSD&tf=15m&tf=30m",
])
def test_bars_bad_parameters_are_400(client, query):
    assert client.get("/api/bars?" + query).status_code == 400


def test_bars_range_clamp_limit_and_the_30m_pairing(client, folders):
    z = _bars_file(folders, "ETHUSD")
    ts = z["ts"]
    d = client.get("/api/bars?coin=ETHUSD").json()                 # no range: the newest 3000 of the whole file
    assert d["n"] == 3000 and d["truncated"] is True and len(ts) > 3000
    assert d["first_ms"] == int(ts[0]) and d["last_ms"] == int(ts[-1]) and d["bars"][-1][0] == int(ts[-1])
    assert d["bars"][0] == [int(ts[-3000]), float(z["o"][-3000]), float(z["h"][-3000]), float(z["l"][-3000]),
                            float(z["c"][-3000])]
    lo, hi = int(ts[100]), int(ts[199])
    d = client.get(f"/api/bars?coin=ETHUSD&from={lo}&to={hi}").json()
    assert d["n"] == 100 and d["truncated"] is False and [b[0] for b in d["bars"]] == [int(t) for t in ts[100:200]]
    d = client.get(f"/api/bars?coin=ETHUSD&from={lo}&to={hi}&limit=10").json()
    assert d["n"] == 10 and d["truncated"] is True and d["bars"][-1][0] == hi            # the newest of the range
    d = client.get("/api/bars?coin=ETHUSD&from=0&to=4000000000000").json()               # clamped to the file
    assert d["from_ms"] == int(ts[0]) and d["to_ms"] == int(ts[-1])
    d = client.get("/api/bars?coin=ETHUSD&from=1&to=2").json()                            # before the file: nothing
    assert d["n"] == 0 and d["bars"] == []
    # 30m: hh:00 + hh:15 and hh:30 + hh:45
    d = client.get(f"/api/bars?coin=ETHUSD&tf=30m&from={lo}&to={hi}").json()
    assert d["tf"] == "30m" and d["n"] > 0
    for t, o, h, l, c in d["bars"]:
        assert t % (30 * 60_000) == 0
        i = int(np.searchsorted(ts, t))
        assert ts[i] == t and ts[i + 1] == t + 15 * 60_000
        assert (o, h, l, c) == (z["o"][i], max(z["h"][i], z["h"][i + 1]), min(z["l"][i], z["l"][i + 1]), z["c"][i + 1])


def test_bars_from_an_odd_file(tmp_path):
    snap = tmp_path / "snap"
    (snap / "bars").mkdir(parents=True)
    M = 15 * 60_000
    t0 = 1_795_000_000_000 // (2 * M) * (2 * M)
    ts = np.array([t0 + 3 * M, t0, t0 + M, t0 + 2 * M, t0 + 4 * M, t0 + 6 * M, t0 + 7 * M], np.int64)   # unsorted, gap
    o = np.array([4, 1, 2, 3, 5, 7, 8], float)
    c = o + 0.5
    c[3] = np.nan                                                                          # a broken bar is left out
    np.savez(snap / "bars" / "BTCUSD.npz", ts=ts, o=o, h=o + 1, l=o - 1, c=c)
    cl = TestClient(create_app(str(snap), None, SECRET))
    d = cl.get("/api/bars?coin=BTCUSD").json()
    assert [b[0] for b in d["bars"]] == [t0, t0 + M, t0 + 3 * M, t0 + 4 * M, t0 + 6 * M, t0 + 7 * M]
    d = cl.get("/api/bars?coin=BTCUSD&tf=30m").json()
    # pairs: (t0, t0+M) and (t0+6M, t0+7M); t0+2M is broken, t0+4M has no partner
    assert [b[0] for b in d["bars"]] == [t0, t0 + 6 * M]
    assert d["bars"][0] == [t0, 1.0, 3.0, 0.0, 2.5]
    np.savez(snap / "bars" / "ETHUSD.npz", ts=ts, o=o[:3], h=o, l=o, c=o)                 # lengths differ
    assert cl.get("/api/bars?coin=ETHUSD").json() == {"missing": True, "bad_shape": True, "coin": "ETHUSD", "tf": "15m"}
    np.savez(snap / "bars" / "SOLUSD.npz", t=ts, o=o, h=o, l=o, c=o)                       # wrong names
    assert cl.get("/api/bars?coin=SOLUSD").json()["bad_shape"] is True


def test_coins_view_sums_the_account_trades(client, folders):
    d = client.get("/api/coins").json()
    assert [c["coin"] for c in d["coins"]] == list(grid.COINS) and d["accounts"] == 50 and d["trade_cap"] == 600
    want = {}
    for a in _file(folders, "accounts.json")["accounts"]:
        for t in _file(folders, "acct", a["id"] + ".json")["trades"]:
            w = want.setdefault((t["coin"], a["id"], t["L"]), [0, 0.0, 0])
            w[0] += t["status"] == "closed"
            w[1] += t["pnl"]
            w[2] += t["status"] == "open"
    seen = 0
    for c in d["coins"]:
        for ln in c["lines"]:
            n, pnl, op = want[(c["coin"], ln["id"], ln["L"])]
            assert (ln["trades"], ln["open"]) == (n, op) and ln["pnl"] == pytest.approx(pnl, abs=0.02)
            seen += 1
        assert c["total"]["trades"] == sum(x["trades"] for x in c["lines"])
        assert [x["pnl"] for x in c["lines"]] == sorted((x["pnl"] for x in c["lines"]), reverse=True)
    assert seen == len(want)
    assert d["partial_accounts"] == sum(1 for a in _file(folders, "accounts.json")["accounts"]
                                        if len(_file(folders, "acct", a["id"] + ".json")["trades"]) >= 600)


def test_grid_dims_for_the_settings_map(client):
    for s in client.get("/api/grid").json()["strategies"]:
        shape = [len(x["values"]) for x in s["dims"]]
        assert int(np.prod(shape)) == s["settings"] and all(x["ko"] for x in s["dims"])
        strat = grid.LONG[s["short"]]
        assert tuple(s["default_idx"]) == grid.DEFAULT_IDX[strat]
        assert grid.combo_tuple(strat, 100) == tuple(int(x) for x in np.unravel_index(100, shape))


def test_new_endpoints_write_nothing(client, folders):
    def listing():
        return {p: os.stat(p).st_mtime_ns for p in glob.glob(os.path.join(folders["snap"], "**"), recursive=True)}
    before = listing()
    for path in NEW_ROUTES + ["/api/bars?coin=XRPUSD&tf=30m&from=0&to=9999999999999&limit=50"]:
        assert client.get(path).status_code == 200, path
    assert listing() == before
    for path in ("/api/bars", "/api/coins", "/api/costs"):
        assert client.post(path).status_code == 405


def test_the_fake_writes_section_8_with_the_contract_shapes(folders):
    st = _file(folders, "status.json")
    assert set(st["deadman"]) == {"configured", "last_ok_ms", "last_error"}
    sv = st["server"]                                                            # 8.13
    assert set(sv) == {"mem_total_mb", "mem_avail_mb", "swap_used_mb", "load", "cpus", "rule_bot"}
    assert len(sv["load"]) == 3 and sv["cpus"] >= 1 and sv["rule_bot"]
    assert all(set(u) == {"unit", "active", "mem_mb"} and u["unit"].startswith("paperbot-") for u in sv["rule_bot"])
    live0 = st["live_start_ms"]
    # bars: 7 coins, 15m from live start - 7 days to now, contract dtypes
    for coin in grid.COINS:
        z = _bars_file(folders, coin)
        assert set(z) == {"ts", "o", "h", "l", "c"} and z["ts"].dtype == np.int64
        assert all(z[k].dtype == np.float64 and z[k].shape == z["ts"].shape for k in "ohlc")
        assert z["ts"][0] <= live0 - 7 * 86_400_000 and z["ts"][-1] == st["generated_ms"] - 15 * 60_000
        assert (np.diff(z["ts"]) == 15 * 60_000).all() and (z["h"] >= np.maximum(z["o"], z["c"])).all()
        assert (z["l"] <= np.minimum(z["o"], z["c"])).all()
    accts = _file(folders, "accounts.json")["accounts"]
    for a in accts:
        for L, ln in a["lines"].items():
            assert set(ln["stops"]) == {"equity", "pnl", "pnl_pct", "max_dd", "trades", "mean_R", "blocked", "halted_ms",
                                        "day_pauses", "streak_pauses"}
            p = ln["parts"]
            assert set(p) == {"gross", "fees", "funding", "open"}
            assert ln["pnl"] == pytest.approx(p["gross"] - p["fees"] + p["funding"] + p["open"], abs=0.05)
    assert any(a["lines"][L]["stops"]["halted_ms"] for a in accts for L in a["lines"])        # a stop-rule halt
    d = _file(folders, "acct", "fx-def-S2-15m.json")
    assert set(d["curves_stops"]) == {"20", "30", "40", "50"} and all(len(v) <= 800 for v in d["curves_stops"].values())
    assert len(d["stop_events"]) <= 200 and {e["what"] for e in d["stop_events"]} <= {"halt", "day", "streak"}
    ts = [e["t_ms"] for e in d["stop_events"]]
    assert ts == sorted(ts, reverse=True)
    for t in d["trades"]:
        assert {"cost_bps", "through_bps", "trend", "vol", "fee", "notional", "funding"} <= set(t)
        assert t["trend"] in ("up", "down", "range", None) and t["vol"] in ("high", "normal", "low", None)
        if t["status"] == "open":
            assert t["funding"] == 0
    assert any(t["cost_bps"] is not None for t in d["trades"])
    since = _file(folders, "costs.json")["since_ms"]
    early = [t for a in accts for t in _file(folders, "acct", a["id"] + ".json")["trades"] if t["entry_ms"] < since]
    assert early and all(t["cost_bps"] is None for t in early)          # before the order book log: not measured
    # private maker accounts: maker fills with through_bps, some only touched
    pv = _file(folders, "acct", "pv-p1-15m.json")["trades"]
    assert all(t["through_bps"] is not None and t["cost_bps"] is None for t in pv)
    assert any(t["through_bps"] < 1 for t in pv) and any(t["through_bps"] >= 1 for t in pv)
    # judge: the three confirmation stories, candidates, stop-rule columns
    j = _file(folders, "judge.json")
    assert {c["status"] for c in j["confirm"]} == {"confirming", "confirmed", "failed"}
    assert j["lines_judged"] == len(j["rows"]) and j["multi_note_ko"] and len(j["stop_rules_ko"]) == 3
    assert j["verdict_ko"].startswith("실전 금지") and "실전 후보" in j["verdict_ko"]
    for c in j["confirm"]:
        assert 0 <= c["progress"] <= 1 and c["need_n"] == 20 and c["min_end_ms"] == c["start_ms"] + 28 * 86_400_000
        assert (c["decided_ms"] is None) == (c["status"] == "confirming")
    assert j["candidates"] and all(set(x) == {"id", "name", "L", "decided_ms", "window", "costs", "stops"}
                                   for x in j["candidates"])
    assert any(x["costs"]["entry_bps"] is not None for x in j["candidates"])
    for r in j["rows"]:
        assert set(r["stops"]) == {"pnl_pct", "max_dd", "ours_pass"}
        assert r["confirm"] is None or set(r["confirm"]) == {"status", "start_ms", "end_ms"}
    # costs (8.3)
    c = _file(folders, "costs.json")
    assert c["sizes"] == [500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000] and c["assumed_bps"] == 2.0
    for x in c["coins"]:
        for side in ("buy_bps", "sell_bps"):
            assert all(len(x[side][k]) == len(c["sizes"]) for k in ("median", "p90", "last"))
    assert any(None in x["buy_bps"]["last"] for x in c["coins"])                    # a size past the 500 levels
    assert all(len(s["points"]) <= 800 and all(len(p) == 3 for p in s["points"]) for s in c["series"])
    assert c["lines"] and c["maker"] and any(m["touch_only"] > 0 for m in c["maker"]) and c["notes_ko"]
    # regime (8.5)
    rg = _file(folders, "regime.json")
    assert [x["coin"] for x in rg["now"]] == list(grid.COINS) and len(rg["history"]) == 7
    for h in rg["history"]:
        assert h["points"][0][0] <= live0 - 7 * 86_400_000 and all(len(p) == 3 for p in h["points"])
    assert all(set(x["trend"]) == {"up", "down", "range"} and set(x["vol"]) == {"high", "normal", "low"} for x in rg["lines"])
    # home (8.1, 8.7)
    home = _file(folders, "home.json")
    g = home["goal"]
    assert g["stages_ko"] == ["설치", "데모 진행", "우리 기준 통과", "확인 기간", "실전 후보"] and g["stage"] == 4
    assert g["line_ko"].startswith("12/31까지") and set(g["closest"]) == {"id", "name", "L", "ok", "of", "missing_ko"}
    assert {"confirming", "candidates"} <= set(home["totals"]) and home["regime_now"] == rg["now"]
    assert home["costs_now"]["assumed_bps"] == 2.0
    # backup / watch (8.8)
    b = _file(folders, "backup.json")
    assert set(b) == {"last_ok_ms", "last_try_ms", "bytes", "tables", "encrypted", "error_ko"}
    w = _file(folders, "watch.json")
    assert w["ok"] is True and {x["what"] for x in w["items"]} == {"dead", "rank", "backup"}
    # weekly review (8.10): the current week and two finished ones, newest first
    rv = _file(folders, "review.json")["weeks"]
    assert [x["final"] for x in rv] == [False, True, True] and rv[0]["start_ms"] > rv[1]["start_ms"]
    for x in rv:
        assert x["end_ms"] - x["start_ms"] == 7 * 86_400_000 and (x["start_ms"] + 9 * 3_600_000) % 86_400_000 == 0
        assert {"numbers", "judge", "stops", "costs", "regime", "views", "decide_ko", "summary_ko"} <= set(x)
        assert 3 <= len(x["summary_ko"]) <= 6 and len(x["regime"]) == 7
    # Telegram history (8.11)
    tg = _file(folders, "telegram.json")["items"]
    assert 50 <= len(tg) <= 300 and [x["ts_ms"] for x in tg] == sorted((x["ts_ms"] for x in tg), reverse=True)
    assert len({x["kind"] for x in tg}) >= 8 and {x["status"] for x in tg} == {"sent", "queued", "error"}
    assert any("<b>" in x["text"] for x in tg)                                      # markup stays text


def test_fake_trades_sit_on_the_fake_candles(folders):
    bars = {c: _bars_file(folders, c) for c in grid.COINS}
    M = 15 * 60_000
    checked = 0
    for aid in ("fx-def-S2-15m", "fr-N04-30m", "pv-p2-30m"):
        for t in _file(folders, "acct", aid + ".json")["trades"][:150]:
            z = bars[t["coin"]]
            i = int(np.searchsorted(z["ts"], t["entry_ms"]))
            assert z["ts"][i] == t["entry_ms"]
            assert z["l"][i] * 0.9997 <= t["entry"] <= z["h"][i] * 1.0003
            if t["status"] == "closed" and t["reason"] not in ("liq", "time"):
                j = int(np.searchsorted(z["ts"], t["exit_ms"] - M))
                assert z["l"][j] * 0.999 <= t["exit"] <= z["h"][j] * 1.001 or t["reason"] == "lock"
            checked += 1
    assert checked > 100


NEW_SCREENS = {"trade": "거래 차트", "regime": "시장 국면", "costs": "실제 비용", "compare": "비교", "review": "주간 회의록",
               "telegram": "알림 기록", "map": "설정 지도", "coins": "코인별"}


def test_new_screens_are_routed_in_the_menu_and_build_dom_from_text_only():
    app_js = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    screens = dict(re.findall(r"(\w+): \"(\w+)\"", re.search(r"const SCREENS = \{([^}]*)\}", app_js).group(1)))
    for name in NEW_SCREENS:
        assert screens.get(name) == name, name
        src = open(os.path.join(STATIC, "js", "screens", name + ".js"), encoding="utf-8").read()
        assert "export async function mount(" in src, name
        # the same scan as for every other file: no markup from strings, no outside host, no eval
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function"):
            assert bad not in src, f"{name}.js uses {bad}"
        assert not re.search(r"\beval\s*\(", src) and "toLocaleString" not in src and "Intl." not in src, name
        assert not re.findall(r"https?://(?!www\.w3\.org)", src), name
    for ko in NEW_SCREENS.values():
        if ko != "거래 차트":                                       # reached from a trade row, not from the menu
            assert f'ko: "{ko}"' in app_js, ko
    # the trade route carries the account and the trade key (both URI-encoded): #/trade/<id>/<key>
    assert "arg2" in app_js and "decodeURIComponent" in app_js
    # every new screen is explained in the howto, in Korean
    howto = open(os.path.join(STATIC, "js", "screens", "howto.js"), encoding="utf-8").read()
    for ko in list(NEW_SCREENS.values()) + ["확인 기간", "정지 규칙", "12/31", "서버 같이 쓰기"]:
        assert ko in howto, ko
    # Telegram text is shown as text (pre-wrap), never parsed
    tg = open(os.path.join(STATIC, "js", "screens", "telegram.js"), encoding="utf-8").read()
    assert 'h("pre", {class: "tg-text"}, String(x.text' in tg
    css = open(os.path.join(STATIC, "demo.css"), encoding="utf-8").read()
    assert re.search(r"\.tg-text \{[^}]*white-space: pre-wrap", css)


def test_status_screen_reads_the_section_8_status_blocks():
    src = open(os.path.join(STATIC, "js", "screens", "status.js"), encoding="utf-8").read()
    for key in ("/api/backup", "/api/watch", "st.deadman", "st.server", "규칙봇 여유 있음", "여유가 줄었음: 개발자에게 화면 보내기",
                "알 수 없음", "mem_avail_mb", "rule_bot"):
        assert key in src, key


def test_the_fake_is_deterministic_for_section_8(tmp_path, folders):
    fake.build(str(tmp_path / "again"))
    for name in ("costs.json", "regime.json", "review.json", "telegram.json", "backup.json", "watch.json",
                 os.path.join("acct", "pv-p1-15m.json")):
        with open(tmp_path / "again" / name, "rb") as a, open(os.path.join(folders["snap"], name), "rb") as b:
            assert a.read() == b.read(), name
    for coin in grid.COINS:
        a, b = _bars_file(folders, coin), np.load(tmp_path / "again" / "bars" / f"{coin}.npz")
        assert all(np.array_equal(a[k], b[k]) for k in "ohlc") and np.array_equal(a["ts"], b["ts"])


# ---------------------------------------------------------------- round 4 part A (CONTRACT 9.1-9.4, 9.8, 9.9)
import gzip  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from demobot.dash import live as live_mod  # noqa: E402
from demobot.dash.live import Live, RateLimiter  # noqa: E402

PART_A_FILES = {"positions": "positions.json", "calendar": "calendar.json", "signals_now": "signals_now.json",
                "dataq": "dataq.json", "timeline": "timeline.json"}
PART_A_SCREENS = {"terminal": "터미널", "positions": "포지션", "charts": "여러 차트", "market": "시장", "signals": "신호",
                  "dataq": "데이터 점검", "timeline": "타임라인"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test reaches Binance: the one door (live._OPENER) refuses."""
    class Shut:
        def open(self, *a, **k):
            raise AssertionError("a test tried to reach the network")
    monkeypatch.setattr(live_mod, "_OPENER", Shut())


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeBinance:
    """Canned Binance answers by path; .fail = "net" / "bad" makes every call fail that way; .calls records them."""

    def __init__(self, delay=0.0):
        self.calls, self.fail, self.delay = [], None, delay
        self.lock = threading.Lock()

    def __call__(self, path, params):
        with self.lock:
            self.calls.append((path, dict(params)))
        if self.delay:
            time.sleep(self.delay)
        if self.fail == "net":
            raise live_mod.NetError("URLError")
        if self.fail == "bad":
            return {"code": -1}
        sym = params.get("symbol", "")
        base = {"BTCUSDT": 100_000.0, "ETHUSDT": 4_000.0}.get(sym, 10.0)
        if path == "/fapi/v1/ticker/24hr":
            return {"symbol": sym, "lastPrice": str(base), "priceChangePercent": "1.5", "quoteVolume": "123456789.5",
                    "highPrice": str(base * 1.02), "lowPrice": str(base * 0.97)}
        if path == "/fapi/v1/premiumIndex":
            return [{"symbol": grid.binance_symbol(c), "markPrice": "1.0", "lastFundingRate": "0.0001",
                     "nextFundingTime": 1_800_028_800_000} for c in grid.COINS] + [{"symbol": "OTHERUSDT"}]
        if path == "/fapi/v1/openInterest":
            return {"symbol": sym, "openInterest": "5000.5"}
        if path == "/fapi/v1/klines":
            n, step = int(params["limit"]), live_mod.TF_MS[params["interval"]]
            rows = [[1_700_000_000_000 + i * step, "1", "2", "0.5", "1.5", "10", 0, "0", 1, "0", "0", "0"] for i in range(n)]
            return rows + [["x"], [1, "nan", "2", "0.5", "1.5", "10"]]          # junk rows are skipped
        if path == "/fapi/v1/fundingRate":
            return [{"fundingTime": 1_799_990_000_000 + i * 28_800_000, "fundingRate": "0.0001"} for i in range(3)]
        if path == "/futures/data/openInterestHist":
            return [{"timestamp": 1_799_900_000_000 + i * 3_600_000, "sumOpenInterest": str(100 + i),
                     "sumOpenInterestValue": str((100 + i) * base)} for i in range(25)]
        if path == "/futures/data/globalLongShortAccountRatio":
            return [{"timestamp": 1_799_900_000_000 + i * 3_600_000, "longShortRatio": "1.5", "longAccount": "0.6"}
                    for i in range(24)]
        raise AssertionError(path)

    def count(self, path):
        return sum(1 for p, _ in self.calls if p == path)


def _live(mode="on", fb=None, clock=None, bars=None):
    clock = clock or Clock()
    lim = RateLimiter(clock=clock, sleep=clock.sleep)
    return Live(mode, fetch=fb or FakeBinance(), bars=bars, limiter=lim, clock=clock), clock


def _live_client(folders, live):
    return TestClient(create_app(folders["snap"], None, SECRET, data_dir=folders["data"], live=live))


def test_part_a_routes_need_the_login(anon):
    for path in [f"/api/{k}" for k in PART_A_FILES] + ["/api/live", "/api/klines?coin=BTCUSD", "/api/market",
                                                       "/api/export", "/api/export/fx-def-S2-15m.csv"]:
        r = anon.get(path)
        assert r.status_code == 401, path
        assert "positions" not in r.text and "coins" not in r.text and "account" not in r.text


def test_part_a_snapshot_routes_return_the_files_and_take_no_parameters(client, folders, tmp_path):
    for key, name in PART_A_FILES.items():
        r = client.get(f"/api/{key}")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store", key
        assert r.json() == _file(folders, name), key
        assert client.get(f"/api/{key}?coin=BTCUSD").status_code == 400, key
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(create_app(str(snap), None, SECRET, live=Live("off")))
    for key in PART_A_FILES:
        assert c.get(f"/api/{key}").json() == {"missing": True}, key
    assert c.get("/api/export").json() == {"missing": True, "ids": []}
    assert c.get("/api/export/fx-def-S2-15m.csv").status_code == 404


def test_the_fake_writes_part_a_with_the_contract_shapes(folders):
    snap = folders["snap"]
    st = _file(folders, "status.json")
    now, live0 = st["generated_ms"], st["live_start_ms"]
    accts = {a["id"]: a for a in _file(folders, "accounts.json")["accounts"]}
    files = {aid: _file(folders, "acct", aid + ".json") for aid in accts}
    # positions.json (9.2): every open trade of every line, nothing else; by_coin counts the 20x lines
    pos = _file(folders, "positions.json")
    keys = {"id", "name", "kind", "L", "coin", "side", "tf", "entry_ms", "entry", "stop", "target", "margin", "notional",
            "unreal", "roe", "R", "last", "stop_dist_pct", "held_ms", "setting_ko", "exit_ko"}
    assert pos["generated_ms"] == now and pos["positions"]
    opened = {(aid, t["key"]) for aid, d in files.items() for t in d["trades"] if t["status"] == "open"}
    seen = set()
    for p in pos["positions"]:
        assert set(p) == keys and p["coin"] in grid.COINS and p["side"] in (1, -1) and p["L"] in grid.LEVS
        assert p["tf"] == accts[p["id"]]["tf"] and p["kind"] == accts[p["id"]]["kind"]
        # the trade key the page derives (signal bar = the bar before the entry) finds the account's open trade
        key = f"{p['coin']}|{p['tf']}|{p['entry_ms'] - (900_000 if p['tf'] == '15m' else 1_800_000)}|{p['side']}|{p['L']}"
        t = next(x for x in files[p["id"]]["trades"] if x["key"] == key)
        assert t["status"] == "open" and t["entry"] == p["entry"] and t["pnl"] == p["unreal"] and t["roe"] == p["roe"]
        assert p["held_ms"] == now - p["entry_ms"] and p["stop_dist_pct"] >= 0
        assert (p["target"] is not None) == p["exit_ko"].startswith("익절 ")
        seen.add((p["id"], key))
    assert seen == opened
    for b in pos["by_coin"]:
        mine = [p for p in pos["positions"] if p["coin"] == b["coin"]]
        assert b["long"] == sum(1 for p in mine if p["L"] == 20 and p["side"] > 0)
        assert b["short"] == sum(1 for p in mine if p["L"] == 20 and p["side"] < 0)
        assert b["unreal"] == pytest.approx(sum(p["unreal"] for p in mine), abs=0.05)
    assert [b["coin"] for b in pos["by_coin"]] == list(grid.COINS)
    # calendar.json (9.3) and acct daily: the same closed trades, by KST day
    cal = _file(folders, "calendar.json")["days"]
    assert cal[0]["day"] <= cal[-1]["day"] and len({d["day"] for d in cal}) == len(cal)
    assert len(cal) == (now + 9 * 3_600_000) // 86_400_000 - (live0 + 9 * 3_600_000) // 86_400_000 + 1
    daily = {}
    for d in files.values():
        assert set(d["daily"]) <= {x["day"] for x in cal}
        for day, row in d["daily"].items():
            assert set(row) == {"20", "30", "40", "50"}
            daily[day] = daily.get(day, 0.0) + sum(row.values())
    for d in cal:
        assert set(d) == {"day", "trades", "wins", "pnl_sum", "lines_up", "lines_down", "by_kind", "best", "worst"}
        assert d["pnl_sum"] == pytest.approx(daily.get(d["day"], 0.0), abs=1.0)
        assert d["wins"] <= d["trades"] and d["lines_up"] + d["lines_down"] <= 200
        assert {k["kind"] for k in d["by_kind"]} == {"fixed", "adaptive", "friend", "flip", "private"}
        if d["trades"]:
            assert set(d["best"]) == {"id", "name", "L", "pnl"} and d["best"]["pnl"] >= d["worst"]["pnl"]
    # home.json equity_total / pnl_total (9.3): hourly, at most 800, pnl = equity - 200 x $1,000; ends at the wallets
    home = _file(folders, "home.json")
    eq, pt = home["equity_total"], home["pnl_total"]
    assert 2 <= len(eq) <= 800 and len(pt) == len(eq) and eq[-1][0] == now
    assert [x[0] for x in eq] == sorted(x[0] for x in eq)
    assert all(b[1] == pytest.approx(a[1] - 200 * 1000.0, abs=0.02) for a, b in zip(eq, pt))
    assert eq[0][1] == pytest.approx(200 * 1000.0) and eq[-1][1] == pytest.approx(
        sum(ln["wallet"] for a in accts.values() for ln in a["lines"].values()), abs=1.0)
    # signals_now.json (9.4)
    sig = _file(folders, "signals_now.json")
    assert set(sig["bar_ms"]) == {"15m", "30m"} and sig["bar_ms"]["30m"] % 1_800_000 == 0
    assert len(sig["votes"]) == len(grid.COINS) * 2 * 3
    for v in sig["votes"]:
        assert v["settings"] == grid.NCOMBO[v["strategy"]] and 0 < len(v["history"]) <= 96
        assert [v["long"], v["short"]] == v["history"][-1][1:] and v["history"][-1][0] == sig["bar_ms"][v["tf"]]
        assert all(0 <= x[1] <= v["settings"] and 0 <= x[2] <= v["settings"] for x in v["history"])
    rec = sig["recent"]
    assert 0 < len(rec) <= 200 and [r["t_ms"] for r in rec] == sorted((r["t_ms"] for r in rec), reverse=True)
    for r in rec[:30]:
        for a in r["accounts"]:
            assert any(t["coin"] == r["coin"] and t["side"] == r["side"] and t["signal_ms"] == r["t_ms"] and t["L"] == 20
                       for t in files[a["id"]]["trades"])
    # dataq.json and timeline.json (9.9)
    dq = _file(folders, "dataq.json")
    assert set(dq) == {"generated_ms", "coins", "ticks", "errors", "issues", "rank_ms", "warm_issues"}
    assert [c["coin"] for c in dq["coins"]] == list(grid.COINS) and len(dq["ticks"]) == 192
    for c in dq["coins"]:
        assert set(c) == {"coin", "bars_expected", "bars_have", "bars_missing", "last_bar_ms", "lag_s", "funding_last_ms",
                          "depth_rows", "depth_last_ms"}
        assert c["bars_have"] + c["bars_missing"] == c["bars_expected"]
    assert all(len(t) == 3 for t in dq["ticks"])
    assert [e[0] for e in dq["errors"]] == sorted((e[0] for e in dq["errors"]), reverse=True) and len(dq["errors"]) <= 50
    tl = _file(folders, "timeline.json")["events"]
    assert [e["t_ms"] for e in tl] == sorted((e["t_ms"] for e in tl), reverse=True)
    whats = {e["what"] for e in tl}
    assert whats <= {"start", "update", "plugins", "warm", "live", "pass", "confirmed", "failed"}
    assert {"live", "pass", "confirmed", "failed"} <= whats and all(e["t_ms"] <= now for e in tl)
    # export (9.9): a few accounts, UTF-8 with BOM, every trade of every line
    ex = _file(folders, "export", "index.json")
    assert ex["files"] and all(n.endswith(".csv.gz") for n in ex["files"])
    for n in ex["files"]:
        with open(os.path.join(snap, "export", n), "rb") as fh:
            raw = gzip.decompress(fh.read())
        assert raw.startswith("﻿".encode())
        text = raw.decode("utf-8-sig")
        lines = text.splitlines()
        assert lines[0].startswith("account,name,L,coin,side")
        tkeys = {t["key"] for t in files[n[:-7]]["trades"]}
        assert len(lines) - 1 >= len(tkeys) and all(k in text for k in sorted(tkeys)[:50])


def test_the_fake_is_deterministic_for_part_a(tmp_path, folders):
    facts = fake.build(str(tmp_path / "again"))
    assert facts["positions"] > 0 and facts["exports"] >= 3
    for name in list(PART_A_FILES.values()) + ["home.json", os.path.join("acct", "fx-def-S2-15m.json"),
                                               os.path.join("export", "index.json"),
                                               os.path.join("export", "fx-def-S2-15m.csv.gz")]:
        with open(tmp_path / "again" / name, "rb") as a, open(os.path.join(folders["snap"], name), "rb") as b:
            assert a.read() == b.read(), name


def test_export_serves_the_csv_as_an_attachment(client, folders):
    d = client.get("/api/export").json()
    want = sorted(n[:-7] for n in _file(folders, "export", "index.json")["files"])
    assert d["ids"] == want and d["generated_ms"] == _file(folders, "export", "index.json")["generated_ms"]
    aid = want[0]
    r = client.get(f"/api/export/{aid}.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == f'attachment; filename="demolab-{aid}.csv"'
    with open(os.path.join(folders["snap"], "export", aid + ".csv.gz"), "rb") as fh:
        assert r.content == gzip.decompress(fh.read())
    assert r.headers["content-security-policy"] == CSP and r.headers["cache-control"] == "no-store"
    # a well-formed id that is not an account, an account without a file, bad names and parameters
    assert client.get("/api/export/fx-def-S9-15m.csv").status_code == 404
    no_file = next(a["id"] for a in _file(folders, "accounts.json")["accounts"] if a["id"] not in want)
    assert client.get(f"/api/export/{no_file}.csv").status_code == 404
    for bad in ("fx_def.csv", "ab.csv", "x" * 41 + ".csv", f"{aid}.txt", aid, f"{aid}.csv.gz", "..%2Fstatus.csv"):
        assert client.get(f"/api/export/{bad}").status_code in (400, 404), bad
    for bad in ("fx_def.csv", "ab.csv", "x" * 41 + ".csv", f"{aid}.txt", aid):
        assert client.get(f"/api/export/{bad}").status_code == 400, bad
    assert client.get(f"/api/export/{aid}.csv?x=1").status_code == 400
    assert client.get("/api/export?x=1").status_code == 400
    assert client.post(f"/api/export/{aid}.csv").status_code == 405


@pytest.mark.parametrize("query", [
    "", "coin=BTC", "coin=btcusd", "coin=BTCUSDT", "coin=BTCUSD&tf=2h", "coin=BTCUSD&tf=1M", "coin=BTCUSD&tf=15M",
    "coin=BTCUSD&limit=0", "coin=BTCUSD&limit=1001", "coin=BTCUSD&limit=abc", "coin=BTCUSD&limit=-5", "coin=BTCUSD&limit=1e3",
    "coin=BTCUSD&nope=1", "coin=BTCUSD&coin=ETHUSD", "coin=BTCUSD&tf=1m&tf=5m", "coin=" + "B" * 41,
])
def test_klines_bad_parameters_are_400(folders, query):
    lv, _ = _live()
    c = _live_client(folders, lv)
    assert c.get("/api/klines?" + query).status_code == 400
    assert lv.requests == 0                                           # refused before anything is asked


def test_live_and_market_take_no_parameters(folders):
    lv, _ = _live()
    c = _live_client(folders, lv)
    for path in ("/api/live?coin=BTCUSD", "/api/market?x=1", "/api/live?live=1&live=2"):
        assert c.get(path).status_code == 400, path
    assert lv.requests == 0


def test_live_answer_and_its_cache(folders):
    fb = FakeBinance()
    lv, clock = _live("on", fb)
    c = _live_client(folders, lv)
    d = c.get("/api/live").json()
    assert d["stale"] is False and d["source"] == "binance" and [x["coin"] for x in d["coins"]] == list(grid.COINS)
    btc = d["coins"][0]
    assert set(btc) == {"coin", "price", "change_pct", "quote_volume", "high", "low", "mark", "funding_rate",
                        "next_funding_ms", "open_interest", "ok"}
    assert (btc["price"], btc["change_pct"], btc["funding_rate"], btc["open_interest"], btc["ok"]) == (100_000.0, 1.5, 0.0001, 5000.5, True)
    n = len(fb.calls)
    assert fb.count("/fapi/v1/ticker/24hr") == 7 and fb.count("/fapi/v1/premiumIndex") == 1 and fb.count("/fapi/v1/openInterest") == 7
    clock.t += 3.0                                                    # inside the 5 s cache: no new request
    assert c.get("/api/live").json() == d and len(fb.calls) == n
    clock.t += 3.0                                                    # 6 s: tickers again, open interest still cached (30 s)
    c.get("/api/live")
    assert fb.count("/fapi/v1/ticker/24hr") == 14 and fb.count("/fapi/v1/openInterest") == 7
    clock.t += 30.0
    c.get("/api/live")
    assert fb.count("/fapi/v1/openInterest") == 14
    # every request asked Binance's public USD-M paths with the coin's symbol only
    assert {p for p, _ in fb.calls} <= live_mod.PATHS
    assert {q.get("symbol") for p, q in fb.calls if q} <= {grid.binance_symbol(c_) for c_ in grid.COINS}


def test_live_keeps_the_last_good_answer_when_binance_fails(folders):
    fb = FakeBinance()
    lv, clock = _live("on", fb)
    c = _live_client(folders, lv)
    good = c.get("/api/live").json()
    fb.fail = "net"
    clock.t += 6.0
    d = c.get("/api/live").json()
    assert d["stale"] is True and d["coins"] == good["coins"] and d["generated_ms"] == good["generated_ms"]
    n = len(fb.calls)
    clock.t += 1.0                                                    # a failure is not retried before the cache time is up
    assert c.get("/api/live").json()["stale"] is True and len(fb.calls) == n
    fb.fail = None
    clock.t += 5.0
    assert c.get("/api/live").json()["stale"] is False
    # garbage answers are failures too; with nothing good yet: unavailable, never an error page
    fb2 = FakeBinance()
    fb2.fail = "bad"
    lv2, _ = _live("on", fb2)
    d = _live_client(folders, lv2).get("/api/live").json()
    assert d["unavailable"] is True and d["stale"] is True and d["coins"] == []
    fb3 = FakeBinance()
    fb3.fail = "net"
    lv3, _ = _live("on", fb3)
    c3 = _live_client(folders, lv3)
    assert c3.get("/api/klines?coin=ETHUSD&tf=1h&limit=5").json()["unavailable"] is True
    assert c3.get("/api/market").json()["unavailable"] is True
    assert len(fb3.calls) <= 3                                        # a network error stops a build at once


def test_klines_answer_cache_and_whitelists(folders):
    fb = FakeBinance()
    lv, clock = _live("on", fb)
    c = _live_client(folders, lv)
    d = c.get("/api/klines?coin=ETHUSD&tf=4h&limit=7").json()
    assert (d["coin"], d["tf"], d["limit"], d["stale"]) == ("ETHUSD", "4h", 7, False)
    b = d["bars"]
    assert set(b) == {"t", "o", "h", "l", "c", "v"} and len(b["t"]) == 7 and all(len(b[k]) == 7 for k in "ohlcv")
    assert b["t"] == sorted(b["t"]) and b["c"][0] == 1.5 and b["v"][0] == 10.0
    assert fb.calls[-1] == ("/fapi/v1/klines", {"symbol": "ETHUSDT", "interval": "4h", "limit": 7})
    assert c.get("/api/klines?coin=ETHUSD&tf=4h&limit=7").json() == d and fb.count("/fapi/v1/klines") == 1
    c.get("/api/klines?coin=ETHUSD&tf=4h&limit=8")                    # another limit: its own cache entry
    assert fb.count("/fapi/v1/klines") == 2
    clock.t += 11.0
    c.get("/api/klines?coin=ETHUSD&tf=4h&limit=7")
    assert fb.count("/fapi/v1/klines") == 3
    d = c.get("/api/klines?coin=XRPUSD").json()                       # defaults: 15m, 500
    assert (d["tf"], d["limit"], len(d["bars"]["t"])) == ("15m", 500, 500)
    for tf in live_mod.KLINE_TFS:
        assert c.get(f"/api/klines?coin=SOLUSD&tf={tf}&limit=1000").status_code == 200
    # the cache keeps at most KLINES_KEEP answers
    for lim in range(1, live_mod.KLINES_KEEP + 10):
        c.get(f"/api/klines?coin=BTCUSD&tf=1m&limit={lim}")
    assert sum(1 for k in lv._cache if k[0] == "k") <= live_mod.KLINES_KEEP


def test_market_answer(folders):
    fb = FakeBinance()
    lv, clock = _live("on", fb)
    c = _live_client(folders, lv)
    d = c.get("/api/market").json()
    assert d["stale"] is False and [x["coin"] for x in d["coins"]] == list(grid.COINS)
    btc = d["coins"][0]
    assert btc["ok"] is True and len(btc["funding"]) == 3 and len(btc["oi_hist"]) == 25 and len(btc["ls_ratio"]) == 24
    assert btc["oi_change_24h_pct"] == pytest.approx((124 / 100 - 1) * 100)
    assert (btc["ls_now"], btc["long_share"], btc["price"]) == (1.5, 0.6, 100_000.0)
    n = len(fb.calls)
    assert fb.count("/fapi/v1/fundingRate") == 7 and fb.count("/futures/data/globalLongShortAccountRatio") == 7
    clock.t += 50.0
    c.get("/api/market")
    assert fb.count("/fapi/v1/fundingRate") == 7                      # cached 60 s
    clock.t += 11.0
    c.get("/api/market")
    assert fb.count("/fapi/v1/fundingRate") == 14 and len(fb.calls) > n


def test_rate_limit_is_four_requests_a_second_overall(folders):
    clock = Clock()
    lim = RateLimiter(clock=clock, sleep=clock.sleep)
    stamps = []
    for _ in range(13):
        lim.acquire()
        stamps.append(clock.t)
    assert all(sum(1 for s in stamps if t <= s < t + 1.0) <= 4 for t in stamps)
    assert stamps[-1] - stamps[0] >= 3.0 - 1e-9                      # 13 requests need at least 3 seconds
    # the whole dashboard shares one limiter: /api/live (15 requests) then /api/market (21) stay under 4 a second
    fb = FakeBinance()
    lv, clock = _live("on", fb)
    seen = []

    def stamped(path, params):
        seen.append(clock.t)
        return fb(path, params)
    lv._fetch = stamped
    c = _live_client(folders, lv)
    c.get("/api/live")
    c.get("/api/market")
    assert len(seen) == 36 and all(sum(1 for s in seen if t <= s < t + 1.0) <= 4 for t in seen)
    # the real limiter (no fake clock): 6 acquisitions take about a second
    real = RateLimiter()
    t0 = time.monotonic()
    for _ in range(6):
        real.acquire()
    assert time.monotonic() - t0 >= 0.9


def test_one_refresh_at_a_time_and_the_others_get_the_last_answer():
    fb = FakeBinance(delay=0.05)
    lv = Live("on", fetch=fb, limiter=RateLimiter(n=1000))
    out = []
    ths = [threading.Thread(target=lambda: out.append(lv.klines("BTCUSD", "15m", 5))) for _ in range(8)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert len(out) == 8 and all(o["bars"]["t"] for o in out) and fb.count("/fapi/v1/klines") == 1


def test_binance_get_only_asks_binance(monkeypatch):
    with pytest.raises(ValueError):
        live_mod.binance_get("/api/v3/account", {})
    with pytest.raises(ValueError):
        live_mod.binance_get("https://evil.example/fapi/v1/klines", {})
    seen = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b'{"ok": 1}'

    class Rec:
        def open(self, req, timeout):
            seen.update(url=req.full_url, ua=req.get_header("User-agent"), timeout=timeout)
            return Resp()
    monkeypatch.setattr(live_mod, "_OPENER", Rec())
    assert live_mod.binance_get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "15m", "limit": 3}) == {"ok": 1}
    assert seen["url"] == "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=3"
    assert seen["ua"] == "demobot-dash" and seen["timeout"] == 5.0
    # a redirect is refused (never followed to another host)
    with pytest.raises(live_mod.NetError):
        live_mod._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example/")


def test_live_off_and_the_env_switch(folders, monkeypatch):
    for path in ("/api/live", "/api/market", "/api/klines?coin=BTCUSD"):
        assert _live_client(folders, Live("off")).get(path).json() == {"off": True}, path
    monkeypatch.setenv("DEMOBOT_DASH_LIVE", "off")
    c = TestClient(create_app(folders["snap"], None, SECRET, data_dir=folders["data"]))
    assert c.get("/api/live").json() == {"off": True}
    monkeypatch.setenv("DEMOBOT_DASH_LIVE", "fake")
    c = TestClient(create_app(folders["snap"], None, SECRET, data_dir=folders["data"]))
    assert c.get("/api/live").json()["source"] == "fake"
    monkeypatch.delenv("DEMOBOT_DASH_LIVE")
    assert create_app(folders["snap"], None, SECRET).state.live.mode == "on"         # the default
    with pytest.raises(ValueError):
        Live("sometimes")
    # the page still asks only this server
    assert "connect-src 'self'" in CSP and "binance" not in CSP


def test_fake_live_mode_is_built_from_the_bars(folders):
    clock = Clock(1_800_000_000.0)
    snap = create_app(folders["snap"], None, SECRET, data_dir=folders["data"]).state.snap
    lv = Live("fake", bars=lambda coin: snap.bars(coin, "15m"), clock=clock, limiter=RateLimiter(clock=clock, sleep=clock.sleep))
    c = _live_client(folders, lv)
    d = c.get("/api/live").json()
    assert d["source"] == "fake" and d["stale"] is False and all(x["ok"] for x in d["coins"])
    for x in d["coins"]:
        last = float(_bars_file(folders, x["coin"])["c"][-1])
        assert abs(x["price"] / last - 1) < 0.01 and x["low"] <= x["price"] <= x["high"]
        assert x["next_funding_ms"] % (8 * 3_600_000) == 0 and x["next_funding_ms"] > clock.t * 1000
    assert c.get("/api/live").json() == d                              # deterministic for one clock
    z = _bars_file(folders, "BTCUSD")
    for tf, lim in (("1m", 50), ("5m", 30), ("15m", 40), ("30m", 20), ("1h", 24), ("4h", 10), ("1d", 5)):
        b = c.get(f"/api/klines?coin=BTCUSD&tf={tf}&limit={lim}").json()["bars"]
        n = len(b["t"])
        assert 0 < n <= lim and b["t"] == sorted(set(b["t"])), tf
        assert all(t % live_mod.TF_MS[tf] == 0 for t in b["t"]), tf
        assert all(hh >= max(o, cc) - 1e-9 and ll <= min(o, cc) + 1e-9 for o, hh, ll, cc in zip(b["o"], b["h"], b["l"], b["c"])), tf
        assert b["t"][-1] < int(z["ts"][-1]) + 900_000 and min(b["l"]) >= float(z["l"].min()) - 1e-9, tf
    b15 = c.get("/api/klines?coin=BTCUSD&tf=15m&limit=3").json()["bars"]
    assert b15["t"] == [int(x) for x in z["ts"][-3:]] and b15["c"] == [float(x) for x in z["c"][-3:]]
    m = c.get("/api/market").json()
    assert m["source"] == "fake" and len(m["coins"]) == 7 and all(len(x["ls_ratio"]) == 24 for x in m["coins"])
    # no bars file: unavailable, never an error
    empty = Live("fake", bars=lambda coin: None)
    assert empty.live()["unavailable"] is True and empty.klines("BTCUSD", "15m", 10)["unavailable"] is True


def test_part_a_endpoints_write_nothing(folders):
    def listing():
        return {p: os.stat(p).st_mtime_ns for p in glob.glob(os.path.join(folders["snap"], "**"), recursive=True)}
    before = listing()
    lv, _ = _live("on")
    c = _live_client(folders, lv)
    for path in [f"/api/{k}" for k in PART_A_FILES] + ["/api/live", "/api/klines?coin=BTCUSD&tf=1h", "/api/market",
                                                       "/api/export", "/api/export/fx-def-S2-15m.csv"]:
        assert c.get(path).status_code == 200, path
    assert listing() == before


def test_part_a_screens_are_routed_and_build_dom_from_text_only():
    app_js = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    screens = dict(re.findall(r"(\w+): \"(\w+)\"", re.search(r"const SCREENS = \{([^}]*)\}", app_js).group(1)))
    menu = re.search(r"const MENU = \[(.*?)\n\];", app_js, re.S).group(1)
    entries = re.findall(r'\{id: "(\w+)", ko: "([^"]+)"(?:, group: "(\w+)")?', menu)
    # the live group first, in this order; data check and timeline in the info group
    assert [e[0] for e in entries[:5]] == ["terminal", "positions", "charts", "market", "signals"]
    assert all(e[2] == "live" for e in entries[:5])
    groups = {e[0]: e[2] for e in entries}
    assert groups["dataq"] == "info" and groups["timeline"] == "info"
    for name, ko in PART_A_SCREENS.items():
        assert screens.get(name) == name, name
        assert (name, ko) in [(e[0], e[1]) for e in entries], name
        src = open(os.path.join(STATIC, "js", "screens", name + ".js"), encoding="utf-8").read()
        assert "export async function mount(" in src and "needCss()" in src, name
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function"):
            assert bad not in src, f"{name}.js uses {bad}"
        assert not re.search(r"\beval\s*\(", src) and "toLocaleString" not in src and "Intl." not in src, name
        assert not re.findall(r"https?://(?!www\.w3\.org)", src), name
        assert "binance.com" not in src, name                          # the browser never asks Binance
    kit = open(os.path.join(STATIC, "js", "live-kit.js"), encoding="utf-8").read()
    assert "innerHTML" not in kit and '"/static/live.css"' in kit and "binance.com" not in kit
    css = open(os.path.join(STATIC, "live.css"), encoding="utf-8").read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and "rgb(" not in css and "hsl(" not in css
    assert not re.search(r"font-size:\s*\d", css) and "url(" not in css
    # the terminal reads what the contract gives it
    term = open(os.path.join(STATIC, "js", "screens", "terminal.js"), encoding="utf-8").read()
    for key in ("/api/live", "/api/klines", "/api/positions", "/api/calendar", "/api/signals_now", "/api/trades",
                "/api/judge", "pnl_total", "by_coin", "next_tick_ms", "goal", "ctx.every(5000", "ctx.every(60000",
                '"15m"', "확인 기간", "체결", "포지션"):
        assert key in term, key
    # the CSV buttons (9.9) and the trade chart found from a position
    for name in ("account", "trades"):
        src = open(os.path.join(STATIC, "js", "screens", name + ".js"), encoding="utf-8").read()
        assert "/api/export" in src and "CSV 내려받기" in src, name
    trade = open(os.path.join(STATIC, "js", "screens", "trade.js"), encoding="utf-8").read()
    assert "query.at" in trade and "positions" in trade
