"""candleague/dash.py, the 포지션 / 터미널 / 순위표 routes: an open position's size, margin and liquidation price rebuilt
from the snapshot equal the engine's own numbers (50x, 40x, 30x, 20x, a 1/4 account, a wallet that is not 5,000),
the "왜 N배" texts, the catch-up and old-snapshot flags, the 1m / 5m candles, /api/sparks and /api/pnl, and DeepSeek
money (D11): never a number in a DeepSeek money field while the snapshot hides it, nor under DS_MONEY_STRICT."""

from __future__ import annotations

import json
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from candleague import dash as D  # noqa: E402
from candleague import exits as X  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague.live import Live  # noqa: E402
from paperbot.models import Bar, Signal  # noqa: E402

MIN = 60_000
T0 = 1_791_000_000_000 // MIN * MIN
EX = D.load_exchange()


def _engine_entry(exit_name, sym, price, side, stop_frac, group, size=1.0, wallet=None, funding=None):
    """A league engine (exits.make_engine with the study's exchange.json) after one signal filled at ``price``."""
    from paperbot.config import V3_SYMBOLS
    brackets, specs, _src = RN.load_exchange(RN.EXCHANGE_FILE, V3_SYMBOLS)
    e = X.make_engine(exit_name, brackets, specs, book="t", size=size)
    if wallet is not None:
        e.wallet = wallet
    k = X.spec(exit_name)["stop_atr"]
    dist = price * stop_frac
    e.submit(Signal(ts=T0 - 1, symbol=sym, timeframe="15m", strategy_id="S2_ST_ROC", side=side, stop_price=0.0,
                    tier="best", atr=dist / k, meta={"stop_dist": dist, "lev_group": group, "ref_price": price}))
    bar = Bar(sym, T0, T0 + MIN - 1, price, price * 1.0001, price * 0.9999, price)
    e.step({sym: bar})
    assert e.position is not None, e.outcomes[-1].detail
    if funding is not None:
        t = T0 + 8 * 60 * MIN
        e.step({sym: Bar(sym, t, t + MIN - 1, price, price * 1.0001, price * 0.9999, price)}, {sym: funding})
    return e


def _row(acct, e):
    return RN.account_rows(None, [acct], {acct["id"]: e}, ds_money=True, book={acct["id"]: []})[0]


CASES = [  # exit, symbol, price, side, stop as a share of the price, group, size, wallet before, expected leverage
    ("ladder|2", "BTCUSDT", 61234.5, 1, 0.004, "best", 1.0, None, 50),
    ("tp2R|1.5", "ETHUSDT", 2412.37, -1, 0.005, "best", 1.0, 4321.09, 40),
    ("roe20|2", "BTCUSDT", 61234.5, -1, 0.005, "normal", 1.0, None, 30),
    ("ladder|2", "ETHUSDT", 2412.37, 1, 0.02, "normal", 1.0, 5873.4, 20),
    ("ladder|2", "BTCUSDT", 61234.5, 1, 0.005, "best", 0.25, 5012.5, 50),
    ("swing3|2", "SOLUSDT", 141.234, -1, 0.006, "normal", 0.25, 4999.99, 30),
]


@pytest.mark.parametrize("case", CASES)
def test_rebuilt_size_margin_and_liquidation_equal_the_engines(case):
    exit_name, sym, price, side, stop_frac, group, size, wallet, lev = case
    e = _engine_entry(exit_name, sym, price, side, stop_frac, group, size, wallet)
    p = e.position
    assert p.leverage == lev
    acct = {"id": "core-S2_ST_ROC-15m-1" + ("-q" if size != 1.0 else ""), "role": "quarter" if size != 1.0 else "cand",
            "kind": "core", "name": "S2_ST_ROC", "tf": "15m", "exit": exit_name, "combo": {}, "size": size}
    row = _row(acct, e)
    r = D.rebuild_open(row["open"], row["wallet"], size, EX)
    assert r["exact"] is False
    assert r["qty"] == pytest.approx(p.qty, rel=1e-12)
    assert r["margin"] == pytest.approx(p.margin_initial, rel=1e-12)
    assert r["liq"] == pytest.approx(p.liq_price, rel=1e-12)
    assert r["equity_at_entry"] == pytest.approx(e.wallet + p.entry_fee, rel=1e-12)
    doc = D.positions_doc({"accounts": [row], "ds_money": True, "generated_ms": T0, "done_ms": T0, "start_ms": T0}, EX)
    q = doc["positions"][0]
    assert q["margin_pct"] == pytest.approx(lev / 100 * size, rel=1e-3)
    assert q["stop_pnl"] == pytest.approx(side * p.qty * (p.stop_price - p.entry_price), rel=1e-12)
    assert q["stop_pnl"] < 0 and q["stop_is_lock"] is False
    assert q["liq_dist_entry"] == pytest.approx(abs(p.liq_price - p.entry_price) / p.entry_price)
    assert q["notional"] == pytest.approx(p.qty * p.entry_price) and q["coin"] == sym[:-1]
    if math.isnan(p.tp_price):
        assert q["tp"] is None and q["tp_pnl"] is None
    else:
        assert q["tp_pnl"] == pytest.approx(side * p.qty * (p.tp_price - p.entry_price))
    assert f"{lev}배" in q["why"]["head_ko"]


def test_funding_after_the_entry_moves_the_numbers_only_a_little():
    """Funding is paid from the wallet and the margin: the rebuild is then "진입 때 기준" and stays close."""
    e = _engine_entry("ladder|2", "BTCUSDT", 61234.5, 1, 0.005, "normal", funding=0.0005)
    p = e.position
    assert p.funding_paid > 0
    row = _row({"id": "a", "role": "cand", "kind": "core", "name": "S2_ST_ROC", "tf": "15m", "exit": "ladder|2",
                "combo": {}}, e)
    r = D.rebuild_open(row["open"], row["wallet"], 1.0, EX)
    assert abs(r["margin"] / p.margin_initial - 1) < 0.005 and abs(r["liq"] / p.liq_price - 1) < 0.005


def test_engine_fields_are_used_when_the_snapshot_carries_them():
    o = {"symbol": "BTCUSDT", "side": -1, "entry": 60000.0, "stop": 60500.0, "tp": None, "since": T0, "lev": 30,
         "qty": 0.75, "margin_initial": 1500.0, "liq": 61700.0}
    r = D.rebuild_open(o, 4980.0, 1.0, EX)
    assert r == {"qty": 0.75, "margin": 1500.0, "equity_at_entry": 5000.0, "liq": 61700.0, "exact": True}


def test_why_texts_say_what_the_leverage_tells():
    core = {"kind": "core", "role": "cand"}
    ds = {"kind": "ds", "role": "cand"}
    assert D.why_lev(core, 50, 0.5, 0.016)["group_ko"] == "좋은 자리"
    assert "50배가 안전 검사에 걸려 40배" in D.why_lev(core, 40, 0.4, 0.02)["lev_ko"]
    w30 = D.why_lev(core, 30, 0.3, 0.03)
    assert w30["group_ko"] is None and "기록에 자리 표시 없음" in w30["lev_ko"]
    assert w30["head_ko"] == "보통 또는 좋은 자리 · 30배 · 증거금 30% · 진입 때 청산까지 3.0%"
    d30 = D.why_lev(ds, 30, 0.3, 0.03)
    assert d30["group_ko"] == "보통 자리" and "늘 보통 자리" in d30["lev_ko"]
    assert "20배" in D.why_lev(ds, 20, 0.2, 0.045)["lev_ko"]
    q = D.why_lev({"kind": "core", "role": "quarter"}, 30, 0.075, 0.03)
    assert "증거금 7.5%" in q["head_ko"] and "1/4" in q["sub_ko"]
    assert "방향만 동전" in D.why_lev({"kind": "core", "role": "flip"}, 20, 0.2, 0.04)["sub_ko"]


# ---------------------------------------------------------------- the routes
def _snapshot(snap, ds_money, generated_ms, done_ms, started_ms=None):
    """A small league: a core pick and a DeepSeek pick, each with an open position and closed trades."""
    e1 = _engine_entry("ladder|2", "BTCUSDT", 61234.5, 1, 0.005, "normal", wallet=5100.0)
    e2 = _engine_entry("tp2R|2", "ETHUSDT", 2412.37, -1, 0.004, "normal", wallet=4800.0)
    accts = [{"id": "core-S2-15m-1", "role": "cand", "kind": "core", "name": "S2_ST_ROC", "tf": "15m", "exit": "ladder|2",
              "combo": {}},
             {"id": "ds-F5_BOX-15m-1", "role": "cand", "kind": "ds", "name": "F5_BOX", "tf": "15m", "exit": "tp2R|2",
              "combo": {}}]
    eng = {"core-S2-15m-1": e1, "ds-F5_BOX-15m-1": e2}
    book = {"core-S2-15m-1": [{"exit_time": T0 - 3 * 3_600_000, "pnl": 150.0, "side": 1, "symbol": "BTCUSDT"},
                              {"exit_time": T0 - 2 * 3_600_000, "pnl": -50.0, "side": -1, "symbol": "BTCUSDT"}],
            "ds-F5_BOX-15m-1": [{"exit_time": T0 - 3_600_000, "pnl": -200.0, "side": 1, "symbol": "ETHUSDT"}]}
    for aid, tr in book.items():
        for t in tr:
            t.update({k: None for k in RN.TRADE_KEYS if k not in t})
    rows = RN.account_rows(None, accts, eng, ds_money=ds_money, book=book)
    doc = {"generated_ms": generated_ms, "done_ms": done_ms, "start_ms": T0 - 86_400_000, "started_ms": started_ms,
           "accounts": rows, "judge": {}, "ds_money": ds_money, "watch": {}}

    class _Conn:                                      # runner.trade_book reads closed trades from the book given
        pass
    trades = RN.trade_book(_Conn(), accts, ds_money, T0 - 86_400_000, book=book)
    (snap / "league.json").write_text(json.dumps(doc))
    (snap / "trades.json").write_text(json.dumps(trades))
    return doc


def _client(snap, now_ms, **kw):
    live = Live(mode="fake", clock=lambda: now_ms / 1000)
    return TestClient(D.create_app(str(snap), "", b"x" * 32, live=live, open_=True, **kw), base_url="http://league.test")


def _numbers(x):
    """Every number in a JSON tree (bools excluded)."""
    if isinstance(x, bool) or x is None:
        return []
    if isinstance(x, (int, float)):
        return [x]
    if isinstance(x, dict):
        return [n for v in x.values() for n in _numbers(v)]
    if isinstance(x, list):
        return [n for v in x for n in _numbers(v)]
    return []


def test_positions_route_times_and_flags(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = _client(snap, T0)
    r = c.get("/api/positions").json()
    assert r["status"] == "준비 중" and r["positions"] == [] and r["server_ms"] == T0
    _snapshot(snap, True, generated_ms=T0 - 120_000, done_ms=T0 - 180_000)
    r = c.get("/api/positions").json()
    assert r["server_ms"] == T0 and r["snap_age_s"] == 120 and r["lag_s"] == 180
    assert r["catching_up"] is False and r["old"] is False and r["ds_money"] is True and r["exact"] is False
    assert r["brackets"].startswith("exchange.json (")
    assert r["counts"] == {"open": 2, "long": 1, "short": 1, "hidden": 0, "by_coin": {"BTCUSD": {"long": 1, "short": 0},
                           "ETHUSD": {"long": 0, "short": 1}}, "by_role": {"cand": 2}, "by_kind": {"core": 1, "ds": 1}}
    p = {x["id"]: x for x in r["positions"]}
    assert p["core-S2-15m-1"]["pick"] == "core-S2-15m-1" and p["core-S2-15m-1"]["margin"] > 0
    assert p["ds-F5_BOX-15m-1"]["hidden"] is False and p["ds-F5_BOX-15m-1"]["why"]["group_ko"] == "보통 자리"
    # an install replaying from 10/01 (processed time well before the start), then an engine that stopped
    _snapshot(snap, True, generated_ms=T0 - 60_000, done_ms=T0 - 5 * 86_400_000, started_ms=T0 - 3_600_000)
    os.utime(snap / "league.json", ns=(10**18, 10**18))
    r = c.get("/api/positions").json()
    assert r["catching_up"] is True and r["old"] is False
    _snapshot(snap, True, generated_ms=T0 - 20 * 60_000, done_ms=T0 - 20 * 60_000)
    os.utime(snap / "league.json", ns=(2 * 10**18, 2 * 10**18))
    r = c.get("/api/positions").json()
    assert r["catching_up"] is False and r["old"] is True and r["snap_age_s"] == 1200
    live = c.get("/api/live").json()
    assert live["server_ms"] == T0 and len(live["coins"]) == 6


def test_short_candles_for_the_position_cards():
    now = T0
    for tf in ("1m", "5m"):
        assert D.klines_query({"coin": "BTCUSD", "tf": tf, "limit": "288"}, now_ms=now)["tf"] == tf
    k = Live(mode="fake", clock=lambda: now / 1000).klines("BTCUSD", "5m", 288)
    assert len(k["bars"]["t"]) == 288 and k["bars"]["t"][1] - k["bars"]["t"][0] == 300_000
    assert D.klines_query({"coin": "BTCUSD", "tf": "3m", "limit": "288"}, now_ms=now) is None


def test_sparks_and_realized_pnl(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = _client(snap, T0)
    assert c.get("/api/sparks").json()["sparks"] == {} and c.get("/api/pnl").json()["status"] == "준비 중"
    _snapshot(snap, True, generated_ms=T0, done_ms=T0)
    sp = c.get("/api/sparks").json()["sparks"]
    assert sp["core-S2-15m-1"][:3] == [5000.0, 5150.0, 5100.0] and len(sp["core-S2-15m-1"]) == 4   # + the wallet now
    assert sp["ds-F5_BOX-15m-1"][:2] == [5000.0, 4800.0]
    long_line = [[T0 + i * 1000, 5000.0 + i] for i in range(200)]
    s = D.spark(long_line)
    assert len(s) == D.SPARK_N and s[0] == 5000.0 and s[-1] == 5199.0 and s == sorted(s)
    assert D.spark([[T0, 5000.0]]) is None and D.spark(None) is None
    p = c.get("/api/pnl").json()
    assert p["role"] == "cand" and p["kind"] == "all" and p["accounts"] == 2 and p["hidden"] == 0
    assert p["total"] == -100.0 and p["trades"] == 3 and p["wins"] == 1 and p["losses"] == 2 and p["max_dd"] == 250.0
    assert [h[1] for h in p["hours"]] == [150.0, -50.0, -200.0] and all(h[0] % 3_600_000 == 0 for h in p["hours"])
    assert sum(d[2] for d in p["days"]) == 3 and all((d[0] + 9 * 3_600_000) % 86_400_000 == 0 for d in p["days"])
    core = c.get("/api/pnl?kind=core").json()
    assert core["total"] == 100.0 and core["accounts"] == 1
    assert c.get("/api/pnl?role=x").status_code == 400 and c.get("/api/pnl?kind=x").status_code == 400


def _ds_money_free(c):
    """No number in any DeepSeek money field of the new routes (counts, wins, times and labels only)."""
    pos = c.get("/api/positions").json()
    ds = [p for p in pos["positions"] if p["kind"] == "ds"]
    assert ds and all(p["hidden"] for p in ds)
    for p in ds:
        assert all(p[k] is None for k in D.POS_MONEY), p
        assert set(_numbers(p)) <= {p["since"], p["trades"], p["wins"], p["size"], p["side"]}   # labels and counts
    sp = c.get("/api/sparks").json()["sparks"]
    assert sp["ds-F5_BOX-15m-1"] is None and sp["core-S2-15m-1"]
    p = c.get("/api/pnl?kind=ds").json()
    assert p["hidden"] == 1 and p["accounts"] == 0 and p["total"] == 0 and p["hours"] == [] and p["days"] == []
    assert c.get("/api/pnl").json()["total"] == 100.0           # the core pick only
    return pos


def test_deepseek_money_hidden_when_the_snapshot_hides_it(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    _snapshot(snap, False, generated_ms=T0, done_ms=T0)
    c = _client(snap, T0)
    pos = _ds_money_free(c)
    assert pos["ds_money"] is False and pos["counts"]["hidden"] == 1


def test_deepseek_money_hidden_everywhere_under_the_strict_switch(tmp_path):
    """DS_MONEY_STRICT: a snapshot written with DeepSeek money shown is served as if the engine had hidden it."""
    snap = tmp_path / "snap"
    snap.mkdir()
    _snapshot(snap, True, generated_ms=T0, done_ms=T0)
    c = _client(snap, T0, ds_strict=True)
    _ds_money_free(c)
    lg = c.get("/api/league").json()
    assert lg["ds_money"] is False
    a = next(x for x in lg["accounts"] if x["kind"] == "ds")
    assert a["wallet"] is None and a["mean_ret"] is None and a["max_dd"] is None
    assert set(a["open"]) == {"symbol", "side", "since"}
    core = next(x for x in lg["accounts"] if x["kind"] == "core")
    assert core["wallet"] is not None and core["open"]["lev"]
    t = c.get("/api/trades/ds-F5_BOX-15m-1").json()
    assert t["equity"] is None and t["trades"][0]["pnl"] is None and t["trades"][0]["win"] is False
    assert all(t["trades"][0][k] is None for k in D.DS_TRADE_PRICES)
    fills = c.get("/api/fills").json()["fills"]
    assert [f["pnl"] for f in fills if f["account"].startswith("ds-")] == [None]
    assert {f["pnl"] for f in fills if f["account"].startswith("core-")} == {150.0, -50.0}
    # the same app without the switch shows the owners' choice (money shown)
    c2 = _client(snap, T0, ds_strict=False)
    assert next(x for x in c2.get("/api/league").json()["accounts"] if x["kind"] == "ds")["wallet"] is not None


def test_strict_summary_scrub_keeps_labels():
    w = {"pools": {"ds": {"roles": {"cand": {"n": 3, "wins": 1, "mean": -0.01}}, "c2": {"p": 0.2, "positive": False},
                       "weeks": [{"cand": {"n": 3, "wins": 1, "sum": -0.03, "up": False}}], "money": True},
                   "core": {"roles": {"cand": {"n": 2, "wins": 2, "mean": 0.02}}}},
         "strategies": {"F5_BOX": {"kind": "ds", "n": 3, "mean": -0.01, "beats_flip": True},
                        "S2_ST_ROC": {"kind": "core", "n": 2, "mean": 0.02}},
         "picks": {"ds-a": {"long": {"n": 1, "wins": 0, "mean": -0.02}}, "core-a": {"long": {"n": 1, "wins": 1, "mean": 0.02}}}}
    doc = {"ds_money": True, "accounts": [{"id": "ds-a", "kind": "ds", "wallet": 1.0, "mean_ret": 0.1, "max_dd": 0.1,
                                          "open": {"symbol": "BTCUSDT", "side": 1, "since": 1, "entry": 2.0, "lev": 30}},
                                         {"id": "core-a", "kind": "core", "wallet": 2.0}], "watch": w}
    s = D.strict_league(doc)
    ds = s["watch"]["pools"]["ds"]
    assert ds["roles"]["cand"] == {"n": 3, "wins": 1, "mean": None} and ds["c2"] == {"p": None, "positive": False}
    assert ds["weeks"][0]["cand"] == {"n": 3, "wins": 1, "sum": None, "up": False} and ds["money"] is False
    assert s["watch"]["pools"]["core"]["roles"]["cand"]["mean"] == 0.02
    assert s["watch"]["strategies"]["F5_BOX"] == {"kind": "ds", "n": 3, "mean": None, "beats_flip": True}
    assert s["watch"]["strategies"]["S2_ST_ROC"]["mean"] == 0.02
    assert s["watch"]["picks"]["ds-a"]["long"]["mean"] is None and s["watch"]["picks"]["core-a"]["long"]["mean"] == 0.02
    assert s["accounts"][0]["open"] == {"symbol": "BTCUSDT", "side": 1, "since": 1} and s["accounts"][1]["wallet"] == 2.0
    assert doc["accounts"][0]["wallet"] == 1.0                      # the cached original is not touched
    assert D.strict_league({**doc, "ds_money": False}) == {**doc, "ds_money": False}


@pytest.mark.parametrize("side", [1, -1])
def test_an_open_position_carries_its_best_and_worst_price_since_the_entry(side):
    """The snapshot's open position keeps the engine's best / worst price (mfe / mae) and /api/positions passes them on, so the cards can show the
    highest and the lowest ROE since the entry; a hidden DeepSeek position gets neither."""
    sym, price = "BTCUSDT", 61234.5
    e = _engine_entry("ladder|2", sym, price, side, 0.005, "normal", 1.0, 5000.0)
    t = T0 + MIN
    e.step({sym: Bar(sym, t, t + MIN - 1, price, price * 1.004, price * 0.9985, price * 1.001)})          # up to +0.4 %, down to -0.15 %
    assert e.position is not None
    p = e.position
    acct = {"id": "core-S2_ST_ROC-15m-1", "role": "cand", "kind": "core", "name": "S2_ST_ROC", "tf": "15m", "exit": "ladder|2", "combo": {}, "size": 1.0}
    row = _row(acct, e)
    assert row["open"]["mfe"] == p.mfe_price and row["open"]["mae"] == p.mae_price and row["open"]["mfe"] != row["open"]["mae"]
    doc = D.positions_doc({"accounts": [row], "ds_money": True, "generated_ms": T0, "done_ms": T0, "start_ms": T0}, EX)
    q = doc["positions"][0]
    assert q["mfe"] == p.mfe_price and q["mae"] == p.mae_price
    best = max(q["mfe"], q["mae"]) if side > 0 else min(q["mfe"], q["mae"])
    assert (q["mfe"] - price) * side > 0 and (q["mae"] - price) * side < 0 and best                       # the favourable and the adverse extreme
    ds = {**acct, "kind": "ds", "id": "ds-F5_BOX-1h-1"}
    hidden = D.positions_doc({"accounts": [{**row, **{k: ds[k] for k in ("id", "kind")}}], "ds_money": False, "generated_ms": T0, "done_ms": T0,
                              "start_ms": T0}, EX)["positions"][0]
    assert hidden["hidden"] is True and hidden["mfe"] is None and hidden["mae"] is None
