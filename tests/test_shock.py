"""Shock test (agents/shock.py, owners approved 2026-10-04): the open positions of the strategy accounts (the engines'
state, as the dashboard reads them) under instantaneous ±5/10/20% moves per coin and all coins together, with the
engine's own order (liquidation at the position's liquidation price first, then the stop filled at the SHOCKED
price: gap-through-stop), the totals, the share of equity, the busts, and where it is shown: the Friday risk packet
(``survival.shock``), the risk officer's daily view (``board.shock``) and the dashboard-ready table."""

import hashlib
import json

import pytest

from paperbot.agents import rooms as RM
from paperbot.agents import shock as SH

from test_new_meetings import bulk, tpol
from test_rooms import HOUR, QueueRunner, START, World, kst, team_answer

S, V45 = "N17_KC_RSI", "V45_AMB"
FRI = kst(2026, 10, 9, 11, 5)
SET = {"taker_fee": 0.0005, "slippage_frac": 0.0002, "bust_below": 10.0}


def pos(side=1, qty=10.0, entry=100.0, margin=100.0, stop=98.0, liq=90.0, wallet=5000.0, price=100.0):
    return {"account": "A@15m", "symbol": "BTCUSDT", "side": side, "qty": qty, "entry": entry, "margin": margin,
            "stop": stop, "liq": liq, "wallet": wallet, "price": price}


def engine(sym, side, qty, entry, margin, stop, liq, wallet=5000.0, lock=None):
    return {"wallet": wallet, "bust": False, "last_mark": {sym: entry},
            "position": {"symbol": sym, "side": side, "qty": qty, "entry_price": entry, "entry_time": START + HOUR,
                         "leverage": 20, "margin": margin, "stop_price": stop, "liq_price": liq, "lock_roe": lock}}


def seed(w, now=FRI):
    eng = {f"{S}@15m": engine("BTCUSDT", 1, 10.0, 100.0, 100.0, 98.0, 90.0),
           f"{S}@1h": engine("BTCUSDT", 1, 5.0, 100.0, 55.0, 95.0, 89.0, wallet=60.0),
           f"{V45}@1h": engine("ETHUSDT", -1, 1.0, 2000.0, 100.0, 2040.0, 2090.0),
           f"{V45}@15m": {"wallet": 5000.0, "bust": False, "position": None},
           "RANDOM_1@15m": engine("BTCUSDT", 1, 10.0, 100.0, 100.0, 98.0, 90.0)}       # coin flips: left out
    w.store.put_state("accounts", now - 60_000, {"engines": eng})
    w.store.live_bars([{"ts": now - 120_000, "symbol": "BTCUSDT", "open": 100.0, "high": 100.0, "low": 100.0,
                        "close": 100.0, "processed_at": now},
                       {"ts": now - 120_000, "symbol": "ETHUSDT", "open": 2000.0, "high": 2000.0, "low": 2000.0,
                        "close": 2000.0, "processed_at": now}])
    w.store.commit()


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_the_engines_order_liquidation_then_the_stop_at_the_shocked_price():
    # -5%: through the stop (98) but not the liquidation price (90): filled at 95, not at 98 (gap)
    r = SH.apply(pos(), -0.05, SET)
    fill = 95 * (1 - 0.0002)
    assert r["outcome"] == "stopped" and r["change"] == pytest.approx(10 * (fill - 100) - 10 * fill * 0.0005)
    assert r["change"] < 10 * (98 - 100)                                     # worse than a fill at the stop
    # -10%: at the liquidation price: the whole margin
    r = SH.apply(pos(), -0.10, SET)
    assert r["outcome"] == "liquidated" and r["change"] == pytest.approx(-100.0)
    # +10%: stays open, the unrealised P&L moves
    r = SH.apply(pos(), 0.10, SET)
    assert r["outcome"] == "open" and r["change"] == pytest.approx(100.0) and not r["busted"]
    # a short: +5% passes its liquidation price (2090) at 2100
    sh = pos(side=-1, qty=1.0, entry=2000.0, stop=2040.0, liq=2090.0, price=2000.0)
    assert SH.apply(sh, 0.05, SET)["outcome"] == "liquidated" and SH.apply(sh, 0.02, SET)["outcome"] == "stopped"
    assert SH.apply(sh, -0.05, SET)["change"] == pytest.approx(100.0)
    # a stop filled so far away that the loss passes the margin is a liquidation (engine._close)
    deep = pos(margin=30.0, liq=50.0, stop=99.0)
    assert SH.apply(deep, -0.10, SET)["outcome"] == "liquidated"
    # the price now is not the entry: the change is measured from the equity now
    moved = pos(price=104.0)
    assert SH.apply(moved, 0.0, SET)["change"] == pytest.approx(0.0)
    # a small wallet ends below the bust line
    assert SH.apply(pos(wallet=60.0, margin=55.0, qty=5.0, stop=95.0, liq=89.0), -0.10, SET)["busted"] is True


def test_scenarios_per_coin_and_all_coins(world):
    seed(world)
    book = SH.positions(world.paper())
    assert {p["account"] for p in book["positions"]} == {f"{S}@15m", f"{S}@1h", f"{V45}@1h"}   # no coin flips
    assert book["prices"] == {"BTCUSDT": {"price": 100.0, "source": "live_bars"},
                              "ETHUSDT": {"price": 2000.0, "source": "live_bars"}}
    assert book["equity_total"] == pytest.approx(5000 + 60 + 5000 + 5000)
    rows = {(r["coin"], r["shock"]): r for r in SH.run(book, s=SET)}
    assert set(c for c, _s in rows) == {"BTC", "ETH", "ALL"} and len(rows) == 18
    b10 = rows[("BTC", -0.10)]
    assert (b10["positions"], b10["liquidated"], b10["stopped"], b10["open"]) == (2, 1, 1, 0)
    assert b10["busted"] == 1                                                     # S@1h: wallet 60 -> under 10
    a10 = rows[("ALL", -0.10)]
    assert a10["positions"] == 3 and a10["open"] == 1                            # the short gains
    want = sum(SH.apply(p, -0.10, SET)["change"] for p in book["positions"])
    assert a10["change_usd"] == pytest.approx(want, abs=0.01)
    assert a10["share_of_equity"] == pytest.approx(want / 15060, abs=1e-4)
    assert a10["worst"][0]["account"] == f"{S}@15m" and a10["worst"][0]["change_usd"] == pytest.approx(-100.0)
    assert rows[("ETH", 0.05)]["liquidated"] == 1 and rows[("ETH", 0.05)]["positions"] == 1
    assert SH.exposure(book)["BTC"] == {"long": 2, "short": 0, "margin": 155.0, "notional": 1500.0}


def test_packets_and_dashboard_view_are_compact_and_read_only(world):
    seed(world)
    digest = lambda: hashlib.sha256(open(world.paths["paper"], "rb").read()).hexdigest()  # noqa: E731
    before = digest()
    pk = SH.packet(world.paper())
    assert pk["open_positions"] == 3 and set(pk["table"]) == {"BTC", "ETH", "ALL"}
    assert set(pk["table"]["ALL"]) == {"-20%", "-10%", "-5%", "+5%", "+10%", "+20%"}
    assert dict(zip(pk["columns"], pk["table"]["BTC"]["-10%"])) == {
        "positions": 2, "liquidated": 1, "stopped": 1, "change_usd": pytest.approx(-100 - 50.09 - 0.225, abs=0.01),
        "share_of_equity": pytest.approx((-100 - 50.09 - 0.225) / 15060, abs=1e-4), "busted": 1}
    assert set(pk["worst_accounts"]) == {"ALL -20%", "ALL +20%"}
    assert len(json.dumps(pk, ensure_ascii=False)) < 4_000 and "갭" in pk["how_to_read"]
    c = SH.compact(world.paper())
    assert set(c["all_coins"]) == {"-20%", "-10%", "+10%", "+20%"} and c["worst_scenario"]["shock"] < 0
    assert len(json.dumps(c, ensure_ascii=False)) < 1_500
    d = SH.dash_view(world.paper())
    assert len(d["rows"]) == 18 and d["shocks"] == list(SH.SHOCKS) and d["prices"]["BTCUSDT"]["price"] == 100.0
    assert digest() == before
    assert SH.packet(None) == {"error": "paper3.db 없음", "label": SH.LABEL}


def test_no_open_positions_and_no_prices(world):
    world.store.put_state("accounts", FRI, {"engines": {f"{S}@15m": {"wallet": 5000.0, "position": None}}})
    world.store.commit()
    pk = SH.packet(world.paper())
    assert pk["open_positions"] == 0 and pk["note"].startswith("지금 열린 포지션이 없음")
    # without live bars the engines' last mark is the price now
    world.store.put_state("accounts", FRI, {"engines": {f"{S}@15m": engine("BTCUSDT", 1, 1.0, 100.0, 10.0, 98.0, 90.0)}})
    world.store.commit()
    assert SH.positions(world.paper())["prices"]["BTCUSDT"] == {"price": 100.0, "source": "engine_mark"}


def test_the_friday_risk_packet_and_the_risk_officers_daily_view(world):
    seed(world)
    bulk(world, 250, FRI - HOUR, aid=f"{V45}@15m")
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("risk_review",), risk_review_hour_kst=11))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
    runner = QueueRunner({"risk_officer": [team_answer("r", "survival.shock.table.ALL.-10%")],
                          "validator": [team_answer("v")], "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=FRI, clock_ms=lambda: FRI)
    assert [(r["trigger"], r["status"]) for r in out["rounds"]] == [("risk_review", "done")]
    pk = runner.calls[0]["packet"]
    assert pk["survival"]["shock"]["open_positions"] == 3 and pk["survival"]["readiness"]["headline"].startswith(
        "실거래 조건: 충족")
    assert pk["board"]["shock"]["open_positions"] == 3 and "shock" in RM.TEAM_VIEW["risk_officer"]
    assert "survival.shock" in runner.calls[0]["system"]
    from paperbot.agents import rooms_db as R
    said = {m["role"]: m["text"] for m in R.room_messages(world.agents, "team:risk", limit=50)}
    assert "[사실]" in said["risk_officer"]                                      # survival.shock.* is code's
