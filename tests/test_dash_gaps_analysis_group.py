"""gapA: the 분석 tab's group switch (기존 36 / 딥시크 44 / 5분봉). ``?group=`` on /api/analysis/risk and
/api/analysis/map (paperbot/dash/analysis.py), the segment on screens/analysis.js, and the honesty rules: DeepSeek is
counts and rates only (no money, nothing per definition), the coin flips are only the baseline line, an old caller
without ``?group=`` gets the 36 exactly as before."""

import json
import os
import re
import sqlite3
import sys

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.config import DS200_IDS, REEL_NAME  # noqa: E402
from paperbot.dash import analysis as AN  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dash import SECRET, _store  # noqa: E402

PW = "correct horse battery"
V4 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static", "v4")
DS = DS200_IDS[0]


def _copy_trade(c, account, strategy, tf, kind, win=False):
    """One more account of ``kind`` with a copy of the fixture's one closed trade (a winner when ``win``)."""
    c.execute("INSERT INTO accounts (account_id, strategy, timeframe, kind, created_ts, settings_version, parent, data) "
              "VALUES (?, ?, ?, ?, 0, 'paper-v4', NULL, '{}')", (account, strategy, tf, kind))
    cols = [r[1] for r in c.execute("PRAGMA table_info(trades)") if r[1] != "id"]
    row = dict(zip(cols, c.execute(f"SELECT {', '.join(cols)} FROM trades WHERE account_id = 'A@15m'").fetchone()))
    d = json.loads(row["data"].replace("NaN", "null"))
    d.update(strategy_id=strategy, timeframe=tf)
    if win:
        d.update(pnl=abs(d["pnl"]), roe=abs(d["roe"]), exit_reason="TP", exit_price=100.5)
        row.update(pnl=abs(row["pnl"]), roe=abs(row["roe"]), exit_reason="TP")
    row.update(account_id=account, data=json.dumps(d))
    c.execute(f"INSERT INTO trades ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[k] for k in cols])


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "paper3.db")
    _store(db).close()
    c = sqlite3.connect(db)
    _copy_trade(c, f"{DS}@15m", DS, "15m", "ds200", win=True)
    _copy_trade(c, f"{REEL_NAME}@5m", REEL_NAME, "5m", "reel", win=True)
    _copy_trade(c, "RANDOM_1@5m", "RANDOM_1", "5m", "random")
    c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
              "equity_after, data) SELECT 'RANDOM_1@15m', symbol, entry_time, exit_time, exit_reason, leverage, pnl, "
              "roe, equity_after, replace(data, '\"strategy_id\": \"A\"', '\"strategy_id\": \"RANDOM_1\"') FROM trades "
              "WHERE account_id = 'A@15m'")
    c.commit()
    c.close()
    app = create_app(db, hash_password(PW), SECRET,
                     candles=lambda s, i, n: [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}])
    cl = TestClient(app)
    assert cl.post("/api/login", json={"password": PW}).status_code == 200
    return cl


def _keys(x, out=None):
    out = set() if out is None else out
    if isinstance(x, dict):
        for k, v in x.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(x, list):
        for v in x:
            _keys(v, out)
    return out


def _strip(d):
    return {k: v for k, v in d.items() if k not in ("computed_at", "stale")}


def test_old_callers_get_the_36_exactly_as_before(client):
    for path in ("/api/analysis/risk", "/api/analysis/map"):
        old = client.get(path).json()
        core = client.get(path + "?group=core").json()
        assert _strip(old) == _strip(core), path
        assert old["group"] == "core"
    risk = client.get("/api/analysis/risk").json()
    assert risk["trades"] == 1 and risk["flip_trades"] == 1            # A@15m and the 15m flip, never the 5m flip
    assert [s["strategy"] for s in risk["strategies"]] == ["A"]          # only the 36's (DeepSeek and the reel apart)
    mp = client.get("/api/analysis/map").json()
    assert mp["strategy"]["trades"] == 1 and set(mp["coin_flips"]["by_timeframe"]) == {"15m"}


def test_a_wrong_group_is_refused_never_silently_the_36(client):
    for bad in ("flip", "all", "전체", "random", "core;drop"):
        for path in ("/api/analysis/risk", "/api/analysis/map"):
            r = client.get(f"{path}?group={bad}")
            assert r.status_code == 400, (path, bad)
    assert client.get("/api/analysis/risk?group=DS200").status_code == 200    # case does not matter


def test_deepseek_is_counts_and_rates_only(client):
    risk = client.get("/api/analysis/risk?group=ds200").json()
    assert risk["group"] == "ds200" and risk["no_money"] is True
    assert risk["trades"] == 1 and risk["all"]["win_rate"] == 1.0 and risk["flip_trades"] == 1
    assert risk["strategies"] == []                                      # nothing per DeepSeek definition
    assert risk["drawdown"]["busted"] == [] and "busted_n" in risk["drawdown"]
    assert not (_keys(risk) & AN.MONEY_KEYS), _keys(risk) & AN.MONEY_KEYS
    mp = client.get("/api/analysis/map?group=ds200").json()
    assert mp["group"] == "ds200" and mp["no_money"] is True and mp["strategy"]["trades"] == 1
    assert mp["strategy"]["by_coin"]["BTC"]["win_rate"] == 1.0
    assert not (_keys(mp) & AN.MONEY_KEYS), _keys(mp) & AN.MONEY_KEYS
    assert "entry_buckets" not in mp


def test_the_reel_reads_5m_and_its_own_5m_coin_flips(client):
    risk = client.get("/api/analysis/risk?group=reel").json()
    assert risk["group"] == "reel" and risk["house_exits"] is False and risk["rules"] is None
    assert risk["trades"] == 1 and risk["flip_trades"] == 1                   # the 5m flip, not the 15m one
    assert risk["all"]["exit_share"]["TP"] == 1.0 and "LOCK" not in risk["all"]["exit_share"]
    assert "losers_reached_first_lock" not in risk["all"]                     # no ladder for the reel
    assert [s["strategy"] for s in risk["strategies"]] == [REEL_NAME]
    assert "릴스" in risk["strategies"][0]["name_ko"]
    assert set(risk["drawdown"]["timeframes"]) <= {"5m"}
    mp = client.get("/api/analysis/map?group=reel").json()
    assert set(mp["strategy"]["by_timeframe"]) == {"5m"} and set(mp["coin_flips"]["by_timeframe"]) == {"5m"}
    assert "pnl" in mp["strategy"]["all"]                                     # the reel's money is shown (D10)


def test_breakdown_per_group(client):
    old = client.get("/api/breakdown").json()
    core = client.get("/api/analysis/breakdown").json()
    assert core["group"] == "core" and core["trades"] == old["trades"] == 1
    assert core["by_coin"] == old["by_coin"]                                  # the same report for the 36
    ds = client.get("/api/analysis/breakdown?group=ds200").json()
    assert ds["group"] == "ds200" and ds["no_money"] is True and ds["trades"] == 1 and ds["flip_trades"] == 1
    assert not (_keys(ds) & AN.MONEY_KEYS), _keys(ds) & AN.MONEY_KEYS          # no money, no per-account 'best'
    assert ds["by_coin"]["BTCUSDT"]["strategies"]["win_rate"] == 1.0
    reel = client.get("/api/analysis/breakdown?group=reel").json()
    assert reel["trades"] == 1 and reel["flip_trades"] == 1                   # the 5m flip only
    assert reel["by_coin"]["BTCUSDT"]["coin_flips"]["n"] == 1 and "pnl" in reel["by_coin"]["BTCUSDT"]["strategies"]
    assert client.get("/api/analysis/breakdown?group=flip").status_code == 400


def test_group_routes_need_the_login(tmp_path):
    db = str(tmp_path / "paper3.db")
    _store(db).close()
    cl = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    for path in ("/api/analysis/risk?group=ds200", "/api/analysis/map?group=reel", "/api/analysis/breakdown?group=ds200"):
        assert cl.get(path).status_code == 401, path


def test_each_group_is_cached_apart(client):
    a = client.get("/api/analysis/risk?group=ds200").json()
    b = client.get("/api/analysis/risk?group=reel").json()
    c = client.get("/api/analysis/risk").json()
    assert (a["group"], b["group"], c["group"]) == ("ds200", "reel", "core")


def test_no_money_drops_every_money_key_at_any_depth():
    got = AN.no_money({"pnl": 1, "a": [{"worst_day": {"pnl": 2}, "win_rate": 0.5}], "equity": 3, "trades": 4})
    assert got == {"a": [{"win_rate": 0.5}], "trades": 4}


def test_missing_db_answers_an_error_per_group(tmp_path):
    db = str(tmp_path / "x" / "paper3.db")
    os.makedirs(os.path.dirname(db))
    cl = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    assert cl.post("/api/login", json={"password": PW}).status_code == 200
    for g in AN.AN_GROUPS:
        r = cl.get(f"/api/analysis/risk?group={g}")
        assert r.status_code == 200 and r.json().get("error"), g
    assert os.listdir(os.path.dirname(db)) == []


# ---------------------------------------------------------------- the page
def _read(name):
    with open(os.path.join(V4, "screens", name), encoding="utf-8") as fh:
        return fh.read()


def test_analysis_screen_has_the_group_switch():
    js = _read("analysis.js")
    m = re.search(r"const GROUPS = \[(.*?)\];", js, re.S)
    assert m, "GROUPS list in analysis.js"
    ids = re.findall(r'id: "([a-z0-9]+)"', m.group(1))
    assert ids == ["core", "ds200", "reel"]                              # no coin-flip group, no mixed 전체
    assert "group=" in js and '"an-group"' in js and "묶음" in js
    assert '"/api/analysis/breakdown"' in js                              # 코인·시간대 per group
    # the views that are only computed for the 36 say so instead of showing the 36 under another group's name
    assert "groups:" in js and "기존 36만" in js


def test_risk_and_map_never_print_deepseek_money():
    risk, where = _read("analysis-risk.js"), _read("analysis-where.js")
    assert "no_money" in risk and where.count("no_money") >= 2            # 손익비·위험, 지도, 코인·시간대
    kit = _read("analysis-kit.js")
    assert "noMoney" in kit                                              # cell() leaves the money out on request
    for src in (risk, where, kit, _read("analysis.js")):
        assert "innerHTML" not in src and "toLocaleString" not in src
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src.replace("#/", ""))
