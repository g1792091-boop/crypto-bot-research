"""Wave 2 part B: 비용 점검 (/api/v4/costs, dash/more/costs.py), 판정 감도 (/api/v4/power, dash/more/power.py) and the page
side of the batch (분석 › 비용, the verdict stage, coin flips inside the 순위표 list, the signals group table).

Costs: per group the per-trade split (before costs / fees / funding / after, as shares of margin) for every group and
money sums ONLY for core / reel / extra (DeepSeek and coin flips are counted, never summed in money: owners' D10 / D11);
the 36 against their same-bar coin flips per timeframe; the reel's 5m flips apart; incremental sums that survive a new
database; stop slippage (daily3.db stop_slips) and order-book cost (fill_costs) against the paper's 2 bp, labelled as
estimates; an empty world; the route behind the login, cached and small."""

import json
import os
import sqlite3
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import _ro_uri, create_app, hash_password  # noqa: E402
from paperbot.dash.more import costs as C  # noqa: E402
from paperbot.dash.more import power as P  # noqa: E402
from paperbot.models import TradeRecord  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
HOUR = 3_600_000
PW = "costs horse battery"
SECRET = b"c" * 32
START = 1_790_000_000_000

ACCOUNTS = [("A@15m", "strategy", {}), ("B@1h", "strategy", {}), ("F3_BOS@15m", "ds200", {"family": "F3"}),
            ("REEL_H1@5m", "reel", {"family": "REEL"}), ("RANDOM_1@5m", "random", {}), ("RANDOM_1@15m", "random", {}),
            ("RANDOM_2@1h", "random", {})]
# (account, pnl after costs, fees, funding, margin, reason)
TRADES = [("A@15m", 50.0, 3.0, 1.0, 100.0, "LOCK"), ("A@15m", -40.0, 3.0, 0.0, 100.0, "SL"),
          ("B@1h", -20.0, 2.0, -0.5, 50.0, "SL"),
          ("F3_BOS@15m", 10.0, 3.0, 0.0, 100.0, "LOCK"),
          ("REEL_H1@5m", 5.0, 1.0, 0.0, 100.0, "BAND"),
          ("RANDOM_1@5m", -3.0, 1.0, 0.0, 100.0, "SL"),
          ("RANDOM_1@15m", -10.0, 3.0, 0.0, 100.0, "SL"), ("RANDOM_2@1h", -100.0, 0.0, 0.0, 100.0, "LIQ")]


def _trade(st, aid, t, pnl, fees, funding, margin, reason, eq):
    strat, tf = aid.split("@")
    st.trade(aid, TradeRecord(
        strategy_id=strat, symbol="BTCUSDT", timeframe=tf, side=1, signal_ts=t - HOUR, entry_time=t - 30 * 60_000,
        entry_price=100.0, exit_time=t, exit_price=101.0, exit_reason=reason, qty=1.0, leverage=30, tier="normal",
        margin=margin, stop_price=99.0, tp_price=0.0, liq_price=95.0, fees=fees, funding=funding, pnl=pnl,
        roe=pnl / margin, price_move=0.01, mae_price=99.5, mfe_price=101.5, equity_after=eq, score=0.0, context={}))


def _world(tmp_path, trades=TRADES, slips=True):
    db, ddb = str(tmp_path / "p.db"), str(tmp_path / "d.db")
    st = Store3(db)
    for aid, kind, data in ACCOUNTS:
        s, tf = aid.split("@")
        st.add_account(aid, s, tf, kind, START, "paper-v4", None, data)
    st.put_state("run", START, {"initial_equity": 5000.0, "taker_fee": 0.0005})
    for i, (aid, pnl, fees, fund, margin, reason) in enumerate(trades):
        _trade(st, aid, START + (i + 1) * HOUR, pnl, fees, fund, margin, reason, 5000.0 + pnl)
    if slips:
        st.fill_costs([{"ts": START + HOUR, "account_id": "A@15m", "symbol": "BTCUSDT", "event": "entry", "status": "ok",
                        "notional": 3000.0, "slip_best": 0.0001},
                       {"ts": START + 2 * HOUR, "account_id": "A@15m", "symbol": "BTCUSDT", "event": "exit", "status": "ok",
                        "notional": 3000.0, "slip_best": 0.0005},
                       {"ts": START + 3 * HOUR, "account_id": "B@1h", "symbol": "BTCUSDT", "event": "entry", "status": "ok",
                        "notional": 1500.0, "slip_best": 0.0003}])
    st.commit()
    st.conn.close()
    if slips:
        d = sqlite3.connect(ddb)
        d.execute("CREATE TABLE stop_slips (key TEXT PRIMARY KEY, day TEXT NOT NULL, account_id TEXT NOT NULL, strategy TEXT, "
                  "timeframe TEXT, symbol TEXT NOT NULL, exit_reason TEXT NOT NULL, exit_time INTEGER NOT NULL, "
                  "status TEXT NOT NULL, paper_bps REAL, real_bps REAL, diff_usd REAL, data TEXT NOT NULL)")
        rows = [("k1", "A@15m", "SL", "ok", 2.0, 6.0, 1.5), ("k2", "B@1h", "SL", "ok", 2.0, 1.0, -0.2),
                ("k3", "RANDOM_1@15m", "SL", "ok", 2.0, 30.0, 9.0), ("k4", "A@15m", "LOCK", "no_trades", 2.0, None, None)]
        for k, aid, r, s, pb, rb, du in rows:
            d.execute("INSERT INTO stop_slips VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (k, "2026-09-22", aid, None, None, "BTCUSDT", r, START + 2 * HOUR, s, pb, rb, du, "{}"))
        d.commit()
        d.close()
    return db, ddb


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return _world(tmp_path_factory.mktemp("costs"))


def _view(db, ddb):
    c = sqlite3.connect(_ro_uri(db), uri=True)
    d = sqlite3.connect(_ro_uri(ddb), uri=True) if os.path.exists(ddb) else None
    try:
        return C.costs(c, d, C.Sums(), START + 100 * HOUR)
    finally:
        c.close()
        if d is not None:
            d.close()


# ---------------------------------------------------------------- the numbers
def test_per_trade_split_for_every_group_and_money_only_for_the_main_groups(world):
    v = _view(*world)
    g = v["groups"]
    assert set(g) == {"core", "flip_same", "ds200", "reel", "flip5"}
    core = g["core"]
    assert (core["accounts"], core["trades"], core["liq"], core["wins"]) == (2, 3, 0, 1)
    # money: after = sum pnl, before = pnl + fees + funding (engine.py _finish)
    assert core["money"] == {"before": pytest.approx(-10.0 + 8.0 + 0.5), "fees": 8.0, "funding": 0.5, "after": -10.0}
    # per trade, shares of margin: fees (0.03 + 0.03 + 0.04) / 3, after (0.5 - 0.4 - 0.4) / 3
    assert core["per_trade"]["fees"] == pytest.approx(0.1 / 3, abs=1e-6)
    assert core["per_trade"]["after"] == pytest.approx(-0.3 / 3, abs=1e-6)
    pt = core["per_trade"]
    assert pt["before"] == pytest.approx(pt["after"] + pt["fees"] + pt["funding"], abs=1e-5)
    assert g["reel"]["money"]["after"] == 5.0
    for k in ("ds200", "flip_same", "flip5"):                     # counted, never summed in money (D10 / D11)
        assert "money" not in g[k] and g[k]["per_trade"] is not None
    assert g["flip_same"]["trades"] == 2 and g["flip_same"]["liq"] == 1 and g["flip5"]["trades"] == 1
    # the 36 against their same-bar coin flips per timeframe
    assert set(v["by_tf"]["core"]) == {"15m", "1h"} and set(v["by_tf"]["flip_same"]) == {"15m", "1h"}
    assert "money" not in v["by_tf"]["flip_same"]["15m"] and "money" in v["by_tf"]["core"]["15m"]
    assert v["fees"]["slippage"] == pytest.approx(0.0002)


def test_slippage_is_an_estimate_against_the_paper_2bp_with_money_only_for_main_accounts(world):
    v = _view(*world)
    s = v["stops"]
    assert s["ready"] and s["exits"] == 4 and s["estimated"] == 3 and s["paper_assume_bps"] == pytest.approx(2.0)
    assert s["real_median_bps"] == pytest.approx(6.0) and s["worse_than_paper"] == 2
    assert s["extra_cost_main_usd"] == pytest.approx(1.3)       # the coin flip's 9.0 is not summed in money
    assert s["by_reason"]["SL"]["n"] == 3
    b = v["book"]
    assert b["ready"] and b["reads"] == 3
    assert b["by_event"]["entry"]["n"] == 2 and b["by_event"]["entry"]["median_bps"] == pytest.approx(2.0)
    assert b["by_event"]["exit"]["over_paper"] == 1
    assert "추정" in v["note"]


def test_incremental_sums_read_only_new_trades_and_restart_on_a_new_database(world, tmp_path):
    db, _ = world
    sums = C.Sums()
    c = sqlite3.connect(_ro_uri(db), uri=True)
    sums.update(c)
    first = sums.last_id
    assert first == len(TRADES) and sum(int(a[0]) for a in sums.acc.values()) == len(TRADES)
    sums.update(c)                                                # nothing new: unchanged
    assert sums.last_id == first and sum(int(a[0]) for a in sums.acc.values()) == len(TRADES)
    c.close()
    small, _ = _world(tmp_path, trades=TRADES[:2], slips=False)   # a smaller max id = a new database
    c2 = sqlite3.connect(_ro_uri(small), uri=True)
    sums.update(c2)
    c2.close()
    assert sums.last_id == 2 and sum(int(a[0]) for a in sums.acc.values()) == 2


def test_an_empty_world_and_missing_records_answer_quietly(tmp_path):
    db, ddb = _world(tmp_path, trades=[], slips=False)
    v = _view(db, ddb)
    assert v["ready"] and all(x["trades"] == 0 and x["per_trade"] is None for x in v["groups"].values())
    assert v["stops"]["ready"] is False and v["book"]["ready"] is True and v["book"]["reads"] == 0


# ---------------------------------------------------------------- power
def test_power_view_has_the_five_edges_per_judged_timeframe_and_the_deepseek_line():
    from paperbot.agents import power as AP
    v = P.view(AP.load(), "딥시크: 검정력 표 없음")
    assert v["ready"] and v["edges"] == [0.0, 0.01, 0.02, 0.05, 0.1]
    assert set(v["tfs"]) == {"15m", "30m", "1h", "5m"} and "4h" not in v["tfs"]      # 4h is observation only
    for x in v["tfs"].values():
        assert [r["edge"] for r in x["rows"]] == v["edges"]
        for r in x["rows"]:
            assert 0 <= r["d30"] <= r["d60"] + 1e-9 <= r["d90"] + 2e-9 <= 1 + 2e-9
    assert v["tfs"]["5m"]["reel"] is True and v["reel"]["alpha"] == pytest.approx(0.005)
    assert v["core"]["alpha"] == pytest.approx(0.07) and v["deepseek"]
    assert P.view(None)["ready"] is False and P.view({"version": 1})["ready"] is False
    assert len(json.dumps(v)) < 20_000


# ---------------------------------------------------------------- the routes
@pytest.fixture
def client(world, tmp_path):
    db, ddb = world
    app = create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], daily_db=ddb,
                     inbox_db=str(tmp_path / "inbox.db"))
    return TestClient(app), app


def test_routes_are_behind_the_login_cached_and_small(client):
    c, app = client
    assert c.get("/api/v4/costs").status_code == 401 and c.get("/api/v4/power").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    t = time.perf_counter()
    r = c.get("/api/v4/costs")
    assert r.status_code == 200 and time.perf_counter() - t < 5 and len(r.content) < 150_000
    d = r.json()
    assert d["groups"]["core"]["trades"] == 3 and "v" in app.state.more["costs"]["cache"]
    assert c.get("/api/v4/costs").json() == d
    p = c.get("/api/v4/power")
    assert p.status_code == 200 and p.json()["ready"] is True and len(p.content) < 20_000
    assert c.get("/api/v4/power").json() == p.json()


# ---------------------------------------------------------------- the page
def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as fh:
        return fh.read()


def test_the_cost_tab_labels_estimates_keeps_coin_flips_beside_and_no_money_for_ds_or_flips():
    an, js = _read("screens", "analysis.js"), _read("screens", "analysis-costs.js")
    assert '"/api/v4/costs"' in an and "C.costs" in an and 'label: "비용"' in an
    assert 'const MONEY = ["core", "reel", "extra"]' in js                   # the only groups with a USDT waterfall
    assert js.count("est()") >= 2 and '"추정"' in js and "ui.assume(" in js and "ui.refNote(" in js
    assert 'ROWS = ["core", "flip_same"' in js                              # the coin flips right under the 36


def test_the_verdict_stage_is_neutral_before_the_verdict_and_stamps_only_after():
    ck, stage = _read("screens", "checkpoint.js"), _read("screens", "checkpoint-stage.js")
    css = _read("screens", "checkpoint.css")
    assert "seatsCard()" in ck and "powerCard(ctx)" in ck and '"/api/v4/power"' in stage
    # the stamp and the luck dots live only in the after-verdict renderer
    after = ck[ck.index("function renderVerdict"):ck.index("// ================================================================ which view")]
    assert "stamp(v)" in after and "luckDots(v)" in after
    before = ck[:ck.index("function renderVerdict")]
    assert "stamp(" not in before.replace("import {seatsCard, powerCard, stamp, luckDots}", "")
    seat_css = css[css.index(".ck-seat {"):css.index(".ck-seat-legend")]
    assert "--up" not in seat_css and "--down" not in seat_css and "--good" not in seat_css   # trades, not a verdict
    assert "named: false" in stage                                           # DeepSeek seats carry no name


def test_coin_flips_sit_in_the_board_list_without_rank_numbers_and_deepseek_gets_one_median_line():
    board, hs = _read("screens", "board.js"), _read("screens", "home-shared.js")
    assert "flips: true" in board and "flips: true" not in _read("screens", "home.js")
    assert "export function withFlips" in hs and "_flipMed" in hs and 'st.sort === "ret"' in hs
    fr = hs[hs.index("export function flipRow"):hs.index("export function flipFoot")]
    assert "o.rk" not in fr and "_rk" not in fr and "title:" not in fr       # no rank, no board-motion decoration
    assert "!a._flip && !a._flipMed" in hs                                   # a search hides the markers


def test_the_signals_screen_has_the_group_by_timeframe_table():
    js = _read("screens", "signals.js")
    assert "signals_by_group" in js and "export function groupGrid" in js and '"묶음별 신호"' in js
