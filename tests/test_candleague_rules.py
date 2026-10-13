"""candleague 익절·손절·배수 / 왜 이 성적인가 / 묶음 레이스 (owners 2026-10-12): the server side.

  * summary.longest_run_p / run_quantile / losing_runs: the chance of a losing run, checked against counting every
    sequence; summary.cost_of: fees + funding rebuilt from the price move, the leverage and the net ROE equal the
    engine's own (a real league engine's closed trade, a liquidation); summary.account_insight with and without money;
    summary.race: medians and the 동전 band from equity lines;
  * dash.atr14 = lib.fg.atr (Wilder's average of the true range); dash.max_stop = the edge of paperbot.sizing's loss
    check; dash.rule_steps; dash.lev_now against size_position; tp_info / breakeven; best_ok; atr_table drops the bar
    still forming; rules_doc;
  * the routes /api/insight, /api/race and /api/rules (with ?wait=1, with the live feed off), and DeepSeek money (the
    existing ds_money rule, and DS_MONEY_STRICT): no P&L, cost, leverage or equity of a hidden DeepSeek account."""

from __future__ import annotations

import itertools
import json
import math
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from candleague import dash as D  # noqa: E402
from candleague import exits as X  # noqa: E402
from candleague import summary as SM  # noqa: E402
from candleague.live import Live  # noqa: E402
import test_candleague_api_positions as AP  # noqa: E402  (its engine helper and small snapshot)

T0 = AP.T0
EX = D.load_exchange()


# ---------------------------------------------------------------- losing runs
def _brute(n, q, run):
    p = 0.0
    for seq in itertools.product((True, False), repeat=n):           # True = a win
        if SM.losing_runs(seq)[0] >= run:
            p += math.prod((1 - q) if w else q for w in seq)
    return p


@pytest.mark.parametrize("n,q,run", [(6, 0.5, 2), (8, 0.7, 3), (10, 0.65, 5), (7, 0.3, 1), (9, 0.9, 9)])
def test_longest_run_chance_equals_counting_every_sequence(n, q, run):
    assert SM.longest_run_p(n, q, run) == pytest.approx(_brute(n, q, run), abs=1e-12)


def test_run_quantiles_and_runs():
    assert SM.losing_runs([True, False, False, True, False, False, False]) == (3, 3)
    assert SM.losing_runs([False, True]) == (1, 0) and SM.losing_runs([]) == (0, 0)
    assert SM.longest_run_p(0, 0.5, 1) is None and SM.longest_run_p(5, None, 2) is None and SM.longest_run_p(3, 0.5, 4) == 0.0
    # 3R picks win about a third of the time: 6-10 losses in a row are the usual longest run over 30-100 trades
    assert SM.run_quantile(30, 0.65, 0.5) == 6 and SM.run_quantile(100, 0.7, 0.5) == 10
    for n, q in ((40, 0.7), (100, 0.65)):
        u, r = SM.run_quantile(n, q, 0.5), SM.run_quantile(n, q, 0.9)
        assert u < r
        assert SM.longest_run_p(n, q, u + 1) <= 0.5 < SM.longest_run_p(n, q, u)
        assert SM.longest_run_p(n, q, r + 1) <= 0.1 < SM.longest_run_p(n, q, r)


# ---------------------------------------------------------------- costs of a trade
def _closed(exit_name, sym, price, side, stop_frac, group, move, funding=None):
    """A league engine's real closed trade: entered as test_candleague_api_positions does, then a bar to ``move``."""
    from paperbot.models import Bar
    e = AP._engine_entry(exit_name, sym, price, side, stop_frac, group, funding=funding)
    t = T0 + 9 * 60 * AP.MIN
    px = price * (1 + move)
    e.step({sym: Bar(sym, t, t + AP.MIN - 1, px, max(px, price) * 1.0001, min(px, price) * 0.9999, px)})
    assert e.position is None and e.trades, "the bar must close the position"
    tr = e.trades[-1]
    return tr, {"symbol": tr.symbol, "side": tr.side, "entry_price": tr.entry_price, "exit_price": tr.exit_price,
                "exit_reason": tr.exit_reason, "leverage": tr.leverage, "pnl": tr.pnl, "roe": tr.roe}


@pytest.mark.parametrize("case", [("tp3R|2", "BTCUSDT", 61234.5, 1, 0.004, "normal", 0.02, None),
                                  ("tp2R|1.5", "ETHUSDT", 2412.37, -1, 0.005, "best", 0.02, 0.0004),
                                  ("ladder|2", "SOLUSDT", 141.234, 1, 0.006, "normal", -0.02, -0.0003)])
def test_costs_rebuilt_from_the_trade_equal_the_engines_fees_and_funding(case):
    tr, t = _closed(*case)
    assert SM.cost_of(t) == pytest.approx(tr.fees + tr.funding, rel=1e-9, abs=1e-9)


def test_cost_of_a_liquidation_and_of_a_trade_without_numbers():
    margin, fee, fund = 1500.0, 22.5, 3.0
    t = {"side": 1, "entry_price": 100.0, "exit_price": 98.4, "exit_reason": "LIQ", "leverage": 50,
         "pnl": -margin - fee - fund, "roe": (-margin - fee - fund) / margin}
    assert SM.cost_of(t) == pytest.approx(fee + fund)
    assert SM.cost_of({**t, "pnl": None}) is None and SM.cost_of({**t, "roe": 0.0}) is None and SM.cost_of({}) is None


# ---------------------------------------------------------------- one account's insight
def _trades():
    """Newest first, as trades.json keeps them: L L W L W L (oldest .. newest) with prices, leverage, P&L and ROE."""
    rows = []
    for i, (pnl, reason, lev) in enumerate([(-100.0, "SL", 30), (-80.0, "SL", 20), (300.0, "TP", 30), (-90.0, "SL", 30),
                                            (240.0, "TP", 20), (-110.0, "SL", 50)]):
        e = 100.0
        side = 1
        margin = 1000.0
        x = e * (1 + (pnl + 20.0) / margin / lev)              # 20 USDT of fees in each trade
        rows.append({"symbol": "BTCUSDT", "side": side, "entry_time": T0 + i * 1000, "exit_time": T0 + i * 1000 + 500,
                     "entry_price": e, "exit_price": x, "exit_reason": reason, "leverage": lev, "pnl": pnl, "roe": pnl / margin})
    return rows[::-1]


def test_account_insight_with_money():
    ins = SM.account_insight(_trades(), total=6)
    assert ins["n"] == 6 and ins["total"] == 6 and ins["capped"] is False and ins["wins"] == 2 and ins["losses"] == 4
    assert ins["reasons"] == {"SL": 4, "TP": 2} and ins["reason_pnl"] == {"SL": -380.0, "TP": 540.0}
    assert ins["lev"] == {"30": 3, "20": 2, "50": 1}
    assert ins["avg_win"] == 270.0 and ins["avg_loss"] == 95.0 and ins["breakeven"] == pytest.approx(95 / 365)
    assert ins["net"] == 160.0 and ins["costs"] == pytest.approx(120.0) and ins["gross"] == pytest.approx(280.0) and ins["cost_n"] == 6
    assert [b["pnl"] for b in ins["big"]] == [-110.0, -100.0, -90.0] and ins["big_share"] == pytest.approx(300 / 380)
    st = ins["streak"]
    assert st["max"] == 2 and st["cur"] == 1 and st["p"] == pytest.approx(SM.longest_run_p(6, 4 / 6, 2))
    assert st["usual"] == SM.run_quantile(6, 4 / 6, 0.5) and st["rare"] == SM.run_quantile(6, 4 / 6, 0.9)
    assert SM.account_insight(_trades(), total=250)["capped"] is True
    empty = SM.account_insight(None, total=0)
    assert empty["n"] == 0 and empty["streak"]["max"] == 0 and empty["streak"]["p"] is None and empty["big"] == []


def test_account_insight_without_money_keeps_counts_and_labels_only():
    hidden = [{**t, "pnl": None, "roe": None, "entry_price": None, "exit_price": None, "win": t["pnl"] > 0} for t in _trades()]
    ins = SM.account_insight(hidden, total=6, hidden=True)
    assert ins["hidden"] is True and ins["wins"] == 2 and ins["reasons"] == {"SL": 4, "TP": 2} and ins["streak"]["max"] == 2
    for k in ("lev", "reason_pnl", "avg_win", "avg_loss", "breakeven", "net", "costs", "gross", "big", "big_share"):
        assert ins[k] is None, k
    # hidden wins even when a stray P&L is still in the list (the server's switch decides, not the data)
    leak = SM.account_insight(_trades(), total=6, hidden=True)
    assert leak["lev"] is None and leak["net"] is None and leak["big"] is None


# ---------------------------------------------------------------- 묶음 레이스
def test_race_medians_and_the_coin_flip_band():
    start = T0
    H = 3_600_000
    accts = [{"id": f"c{i}", "kind": "core", "role": "cand"} for i in range(3)] + \
            [{"id": f"f{i}", "kind": "core", "role": "flip"} for i in range(4)] + \
            [{"id": "d0", "kind": "ds", "role": "cand"}]
    book = {"c0": {"equity": [[start, 5000.0], [start + H + 1, 5100.0]]},
            "c1": {"equity": [[start, 5000.0], [start + 2 * H, 4800.0]]},
            "c2": {"equity": [[start, 5000.0]]},
            "f0": {"equity": [[start, 5000.0], [start + H, 4000.0]]}, "f1": {"equity": [[start, 5000.0], [start + H, 4500.0]]},
            "f2": {"equity": [[start, 5000.0], [start + H, 5500.0]]}, "f3": {"equity": [[start, 5000.0], [start + H, 6000.0]]},
            "d0": {"equity": None}}
    r = SM.race(accts, book, start, start + 3 * H)
    assert r["t"] == [start, start + H, start + 2 * H, start + 3 * H] and r["step_ms"] == H
    c = r["pools"]["core"]["roles"]["cand"]
    assert c["n"] == 3 and c["median"] == [5000.0, 5000.0, 5000.0, 5000.0]
    assert r["pools"]["core"]["roles"]["cand"]["median"][2] == 5000.0
    f = r["pools"]["core"]["roles"]["flip"]
    assert f["median"][1] == 5000.0 and f["p25"][1] == 4375.0 and f["p75"][1] == 5625.0 and f["p25"][0] == 5000.0
    assert "p25" not in c
    assert r["pools"]["ds"] == {"money": False, "roles": {}}
    # long spans: at most max_points + 1 steps, whole hours
    long = SM.race(accts, book, start, start + 1000 * H, max_points=300)
    assert len(long["t"]) <= 302 and long["step_ms"] % H == 0 and long["t"][-1] == start + 1000 * H


# ---------------------------------------------------------------- the rule numbers
def test_atr14_is_the_engines_atr():
    import pandas as pd
    rnd = random.Random(7)
    c = [100.0]
    for _ in range(199):
        c.append(c[-1] * (1 + rnd.gauss(0, 0.004)))
    h = [x * (1 + abs(rnd.gauss(0, 0.002))) for x in c]
    lo = [x * (1 - abs(rnd.gauss(0, 0.002))) for x in c]
    df = pd.DataFrame({"high": h, "low": lo, "close": c})
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    want = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1]        # sweep_lib fg.atr = rma(true_range, 14)
    assert D.atr14(h, lo, c) == pytest.approx(want, rel=1e-12)
    assert D.atr14(h[:14], lo[:14], c[:14]) is None


def test_max_stop_is_the_edge_of_the_loss_check():
    from paperbot.sizing import size_position
    st = D._settings(D.LIVE_EXIT, 1.0)
    br = EX["brackets"]["BTCUSDT"]
    for margin, lev in ((0.5, 50), (0.4, 40), (0.3, 30), (0.2, 20)):
        d = D.max_stop(margin, lev)
        for frac, ok in ((0.995, True), (1.005, False)):
            dec = size_position(st, 5000.0, 1, 100.0, 100.0 * (1 - d * frac), "best", br, atr=1e-6, qty_step=0.0)
            loss_fail = any(f"{lev}x: stop loss" in r for r in dec.reasons)
            assert loss_fail is (not ok), (lev, frac, dec.reasons)
    assert [round(D.max_stop(m, l) * 100, 2) for m, l in ((0.5, 50), (0.4, 40), (0.3, 30), (0.2, 20))] == [0.48, 0.82, 1.55, 3.63]


def test_rule_steps():
    steps = D.rule_steps(EX)
    assert [s["lev"] for s in steps] == [50, 40, 30, 20] and [s["group"] for s in steps] == ["best", "best", "normal", "normal"]
    assert [s["margin"] for s in steps] == [0.5, 0.4, 0.3, 0.2] and [s["q_margin"] for s in steps] == [0.125, 0.1, 0.075, 0.05]
    assert all(s["q_max_stop"] > s["max_stop"] for s in steps)
    btc = [s["liq"]["BTCUSD"] for s in steps]
    assert btc == sorted(btc) and 0.015 < btc[0] < 0.017 and 0.045 < btc[-1] < 0.047 and set(steps[0]["liq"]) == set(D.RULE_COINS)
    assert D.rule_steps(None)[0]["liq"] == {}


def test_rule_steps_carry_the_exchanges_limit():
    """size_position's first check: the coin's bracket at the order's notional. With $5,000, 50x is a $125,000 order
    and LTC / BCH allow only 40x there (the 후보 account steps down), while the 1/4 account's $31,250 order allows 50x.
    The step table says so instead of a liquidation distance, and the leverage the engine gives agrees."""
    steps = D.rule_steps(EX)
    s50 = steps[0]
    assert s50["notional"] == pytest.approx(125_000.0) and s50["q_notional"] == pytest.approx(31_250.0)
    assert sorted(s50["blocked"]) == ["BCHUSD", "LTCUSD"] and s50["q_blocked"] == []
    assert s50["cap"]["LTCUSD"] == 40 and s50["cap"]["BCHUSD"] == 40 and s50["q_cap"]["LTCUSD"] == 50
    assert s50["liq"]["LTCUSD"] is None and s50["liq"]["BCHUSD"] is None
    assert s50["q_liq"]["LTCUSD"] == pytest.approx(0.0117, abs=5e-4) and s50["liq"]["BTCUSD"] == pytest.approx(s50["q_liq"]["BTCUSD"])
    # every other step is allowed everywhere at both sizes (exchange.json as committed)
    assert all(not s["blocked"] and not s["q_blocked"] for s in steps[1:])
    # a smaller order falls in a lower bracket: the 1/4 account's liquidation is farther on SOL / DOGE at 50x
    assert s50["q_liq"]["SOLUSD"] > s50["liq"]["SOLUSD"]
    # what the step table says is what the engine does: a tight stop at a 좋은 자리
    for sym in ("LTCUSDT", "BCHUSDT"):
        assert D.lev_now("tp3R|1", 1.0, "best", 100.0, 0.1, sym, EX) == 40
        assert D.lev_now("tp3R|1", 0.25, "best", 100.0, 0.1, sym, EX) == 50
    assert D.lev_now("tp3R|1", 1.0, "best", 100.0, 0.1, "BTCUSDT", EX) == 50
    assert D.rule_steps(None)[0]["blocked"] == [] and D.rule_steps(None)[0]["cap"] == {}


def test_why_40x_names_the_exchanges_limit():
    """A 40x LTC entry of a 후보 account ($5,000 wallet): the 50x order is $125,000 and the bracket allows 40x there,
    so the card says the exchange skipped 50x; BTC (150x there) keeps the safety-check wording; the 1/4 account's
    smaller order is not capped."""
    core = {"kind": "core", "role": "cand"}
    assert D._cap50(EX, "LTCUSDT", 5000.0, 1.0) == 40 and D._cap50(EX, "LTCUSDT", 5000.0, 0.25) == 50
    assert D._cap50(EX, "BTCUSDT", 5000.0, 1.0) >= 50 and D._cap50(None, "LTCUSDT", 5000.0, 1.0) is None
    w = D.why_lev(core, 40, 0.4, 0.014, cap50=D._cap50(EX, "LTCUSDT", 5000.0, 1.0))
    assert "거래소가 40배까지만 허용해 50배를 건너뛰고 40배" in w["lev_ko"] and w["group_ko"] == "좋은 자리"
    assert "50배가 안전 검사에 걸려 40배" in D.why_lev(core, 40, 0.4, 0.02, cap50=D._cap50(EX, "BTCUSDT", 5000.0, 1.0))["lev_ko"]


def test_rule_words_of_the_position_card():
    """The position card's rule (why_lev): all four steps of a 좋은 자리, the exchange's limit and the two checks; a
    short line for the card face."""
    w = D.why_lev({"kind": "core", "role": "cand"}, 30, 0.3, 0.03)
    assert "50배(증거금 50%) → 40배(40%) → 30배(30%) → 20배(20%)" in w["rule_ko"] and "보통 자리는 30배 → 20배" in w["rule_ko"]
    assert "거래소가 그 주문 크기에 허용하는 배수" in w["rule_ko"] and "잔고의 15% 이하" in w["rule_ko"]
    assert w["rule_short_ko"] == "좋은 자리 50→40→30→20배 · 보통 30→20배 · 거래소 한도와 안전 검사를 통과한 첫 배수"


def test_leverage_now_follows_the_engines_rule():
    from paperbot.sizing import size_position
    price, sym = 60000.0, "BTCUSDT"
    for exit_name, atr_frac, group, size in (("tp3R|4", 0.0013, "best", 1.0), ("tp3R|4", 0.0013, "normal", 1.0),
                                             ("tp3R|1", 0.002, "best", 1.0), ("tp3R|4", 0.0013, "best", 0.25),
                                             ("ladder|2", 0.003, "best", 1.0), ("tp3R|4", 0.009, "normal", 1.0)):
        atr = price * atr_frac
        got = D.lev_now(exit_name, size, group, price, atr, sym, EX)
        dec = size_position(X.settings_for(exit_name, size=size), 5000.0, 1, price, price - X.stop_dist(exit_name, atr), group,
                            EX["brackets"][sym], atr=atr, qty_step=EX["steps"][sym])
        assert got == (dec.leverage if dec.ok else 0), (exit_name, atr_frac, group, size)
    # a 4 ATR stop of 0.52%: 50x fails the loss check, 40x passes; a normal spot starts at 30x; 1/4 size reaches 50x
    assert D.lev_now("tp3R|4", 1.0, "best", price, price * 0.0013, sym, EX) == 40
    assert D.lev_now("tp3R|4", 1.0, "normal", price, price * 0.0013, sym, EX) == 30
    assert D.lev_now("tp3R|4", 0.25, "best", price, price * 0.0013, sym, EX) == 50
    assert D.lev_now("tp3R|4", 1.0, "normal", price, price * 0.012, sym, EX) == 0           # 4.8% stop: no step passes
    assert D.lev_now("tp3R|4", 1.0, "normal", price, price * 0.0013, "XRPUSDT", EX) is None
    assert D.lev_now("tp3R|4", 1.0, "normal", price, 0.0, sym, EX) is None


def test_exit_words_breakeven_and_good_spots():
    assert D.tp_info("tp3R|4") == {"kind": "R", "val": 3.0, "first_lock": None, "stop_atr": 4.0}
    assert D.tp_info("roe50|4")["kind"] == "roe" and D.tp_info("roe50|4")["val"] == 0.5
    assert D.tp_info("ladder|2") == {"kind": "ladder", "val": None, "first_lock": 0.10, "stop_atr": 2.0}
    assert D.tp_info("ladder_tp2R|2")["kind"] == "ladder_R" and D.tp_info("swing3|2")["kind"] == "struct"
    assert D.breakeven(D.tp_info("tp3R|4")) == 0.25 and D.breakeven(D.tp_info("tp2R|2")) == pytest.approx(1 / 3)
    assert D.breakeven(D.tp_info("ladder|2")) is None and D.breakeven(D.tp_info("roe50|4")) is None
    # with costs: (d + cost) / (d + tp); 3R at a 1% stop and 0.14% round trip = 28.5%
    assert D.breakeven(D.tp_info("tp3R|4"), 0.01, 0.03, 0.0014) == pytest.approx(0.285)
    # the take-profit is a limit order (maker): a win costs 0.09%, a stop 0.14%: (d + c) / ((d + c) + (tp - w))
    assert D.breakeven(D.tp_info("tp3R|4"), 0.01, 0.03, 0.0014, 0.0009) == pytest.approx(0.0114 / 0.0405)
    assert D.breakeven(D.tp_info("tp3R|4"), 0.005, 0.015, 0.0014, 0.0009) == pytest.approx(0.0064 / 0.0205)
    assert D.breakeven(D.tp_info("tp3R|4"), 0.0002, 0.0006, 0.0014, 0.0009) == 1.0      # costs eat the take-profit
    assert D.best_ok({"kind": "core", "name": "DOGE", "tf": "15m"}) is True
    assert D.best_ok({"kind": "core", "name": "DOGE", "tf": "4h"}) is False                # no entry-strength edges there
    assert D.best_ok({"kind": "ds", "name": "F5_BOX", "tf": "15m"}) is False


def test_atr_table_uses_closed_bars_only():
    tf_ms = 900_000
    now = T0 // tf_ms * tf_ms + 300_000                      # 5 minutes into a 15m bar
    n = 40

    def klines(coin, tf, limit):
        t = [now // tf_ms * tf_ms - (n - 1 - i) * tf_ms for i in range(n)]
        c = [100.0] * (n - 1) + [500.0]                       # the forming bar jumps: it must not count
        return {"bars": {"t": t, "o": c, "h": [x + 1 for x in c], "l": [x - 1 for x in c], "c": c, "v": [1.0] * n}}

    tab = D.atr_table(klines, now, coins=("BTCUSD",), tfs=("15m",))
    x = tab["15m"]["BTCUSD"]
    assert x["price"] == 100.0 and x["atr"] == pytest.approx(2.0) and x["pct"] == pytest.approx(0.02)
    bad = D.atr_table(lambda c, t, l: {"bars": {}}, now, coins=("BTCUSD",), tfs=("15m",))
    assert bad == {"15m": {}}


# ---------------------------------------------------------------- the routes
def _league_files(snap, ds_money):
    """test_candleague_api_positions' small league (a core pick and a DeepSeek pick, closed trades, open positions),
    with the trades' prices, leverage and ROE filled in."""
    AP._snapshot(snap, ds_money, generated_ms=T0, done_ms=T0)
    book = json.loads((snap / "trades.json").read_text())
    for aid, b in book.items():
        for t in b["trades"]:
            if t.get("pnl") is not None:
                t.update(entry_price=100.0, exit_price=100.0 * (1 + t["side"] * (t["pnl"] + 10) / 1000 / 30), leverage=30,
                         roe=t["pnl"] / 1000, exit_reason="SL" if t["pnl"] < 0 else "TP")
            else:
                t.update(leverage=30, exit_reason="SL")
    (snap / "trades.json").write_text(json.dumps(book))


class _Klines(Live):
    """The fake live feed with a counter of klines calls (the ATR read)."""

    def __init__(self, now_ms):
        super().__init__(mode="fake", clock=lambda: now_ms / 1000)
        self.kcalls = 0

    def klines(self, coin, tf, limit, end=None):
        self.kcalls += 1
        return super().klines(coin, tf, limit, end)


def _client(snap, live, **kw):
    return TestClient(D.create_app(str(snap), "", b"x" * 32, live=live, open_=True, **kw), base_url="http://league.test")


def test_insight_route(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = _client(snap, _Klines(T0))
    assert c.get("/api/insight").json() == {"status": "준비 중", "accounts": {}}
    _league_files(snap, True)
    r = c.get("/api/insight").json()
    assert r["last_n"] == 200 and r["ds_money"] is True
    core = r["accounts"]["core-S2-15m-1"]
    assert core["n"] == 2 and core["wins"] == 1 and core["reasons"] == {"SL": 1, "TP": 1} and core["lev"] == {"30": 2}
    assert core["net"] == 100.0 and core["costs"] == pytest.approx(20.0) and core["hidden"] is False
    ds = r["accounts"]["ds-F5_BOX-15m-1"]
    assert ds["n"] == 1 and ds["net"] == -200.0 and ds["lev"] == {"30": 1}


@pytest.mark.parametrize("mode", ["snapshot", "strict"])
def test_deepseek_money_stays_hidden_on_the_new_routes(tmp_path, mode):
    """The snapshot's switch off (the engine already strips the money), or DS_MONEY_STRICT on a snapshot that shows it:
    no P&L, cost, leverage, equity or used leverage of a DeepSeek account on /api/insight, /api/race, /api/rules."""
    snap = tmp_path / "snap"
    snap.mkdir()
    _league_files(snap, mode == "strict")
    c = _client(snap, _Klines(T0), ds_strict=(mode == "strict"))
    ins = c.get("/api/insight").json()
    ds = ins["accounts"]["ds-F5_BOX-15m-1"]
    assert ins["ds_money"] is False and ds["hidden"] is True and ds["n"] == 1 and ds["reasons"] == {"SL": 1}
    for k in ("lev", "reason_pnl", "avg_win", "avg_loss", "breakeven", "net", "costs", "gross", "big", "big_share"):
        assert ds[k] is None, k
    assert ins["accounts"]["core-S2-15m-1"]["net"] == 100.0
    race = c.get("/api/race").json()
    assert race["pools"]["ds"] == {"money": False, "roles": {}} and race["pools"]["core"]["money"] is True
    rules = c.get("/api/rules?wait=1").json()
    assert rules["picks"]["ds-F5_BOX-15m-1"]["roles"]["cand"]["used"] is None and rules["hidden_accounts"] == 1
    assert rules["picks"]["core-S2-15m-1"]["roles"]["cand"]["used"] == {"30": 2}
    assert rules["used_all"] == {"cand": {"30": 2}}


def test_race_route(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = _client(snap, _Klines(T0))
    assert c.get("/api/race").json()["status"] == "준비 중"
    _league_files(snap, True)
    r = c.get("/api/race").json()
    assert r["start_ms"] == T0 - 86_400_000 and r["end_ms"] == T0 and r["step_ms"] == 3_600_000 and len(r["t"]) == 25
    assert r["pools"]["core"]["roles"]["cand"]["median"][-1] == 5100.0 and r["pools"]["ds"]["roles"]["cand"]["median"][-1] == 4800.0


def test_rules_route(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    live = _Klines(T0)
    c = _client(snap, live)
    assert c.get("/api/rules?wait=1").json()["status"] == "준비 중"
    _league_files(snap, True)
    r = c.get("/api/rules?wait=1").json()
    assert r["atr_loading"] is False and r["atr_source"] == "fake" and r["atr_ms"] == T0 and r["server_ms"] == T0
    assert [s["lev"] for s in r["steps"]] == [50, 40, 30, 20] and r["costs"]["max_loss"] == 0.15 and r["costs"]["round_trip"] == 0.0014
    assert r["base_exit"] == "ladder|2" and r["base_exit_ko"] == "계단 잠금 10%부터 · 손절 2 ATR"
    assert r["exits"] == {"ladder|2": 1, "tp2R|2": 1}
    p = r["picks"]["ds-F5_BOX-15m-1"]
    assert p["tp"]["kind"] == "R" and p["breakeven"] == pytest.approx(1 / 3) and p["best_ok"] is False and p["p_best"] == 0.0
    assert set(p["roles"]) == {"cand"} and p["roles"]["cand"]["exit_ko"] == "고정 익절 2R · 손절 2 ATR"
    assert set(p["now"]) == set(D.RULE_COINS)
    btc = p["now"]["BTCUSD"]
    atr = r["atr"]["15m"]["BTCUSD"]
    assert btc["stop_pct"] == pytest.approx(2 * atr["pct"]) and btc["tp_pct"] == pytest.approx(2 * btc["stop_pct"])
    # a stop costs the 0.14% round trip, the take-profit's limit order 0.09% (taker + slippage in, maker out)
    assert r["costs"]["win_cost"] == pytest.approx(0.0009) and r["costs"]["maker"] == 0.0002
    d = btc["stop_pct"]
    assert btc["be_cost"] == pytest.approx((d + 0.0014) / ((d + 0.0014) + (2 * d - 0.0009)))
    assert r["base_tp"] == D.tp_info("ladder|2")
    assert set(btc["lev"]["cand"]) == {"normal"} and btc["lev"]["cand"]["normal"] in (0, 20, 30)
    assert btc["lev"]["cand"]["normal"] == D.lev_now("tp2R|2", 1.0, "normal", atr["price"], atr["atr"], "BTCUSDT", EX)
    assert btc["lev"]["quarter"]["normal"] >= btc["lev"]["cand"]["normal"]
    core = r["picks"]["core-S2-15m-1"]
    assert core["tp"]["kind"] == "ladder" and core["breakeven"] is None and core["now"]["ETHUSD"]["be_cost"] is None
    assert set(core["now"]["ETHUSD"]["lev"]["cand"]) == ({"best", "normal"} if core["best_ok"] else {"normal"})
    # the ATRs are read once per ATR_TTL_S, not on every call
    n = live.kcalls
    assert n == len(D.RULE_TFS) * len(D.RULE_COINS)
    c.get("/api/rules")
    assert live.kcalls == n


def test_rules_route_without_the_live_feed(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    _league_files(snap, True)
    c = _client(snap, Live(mode="off"))
    r = c.get("/api/rules").json()
    assert r["atr"] is None and r["atr_loading"] is False and r["atr_ms"] is None
    assert all(p["now"] is None for p in r["picks"].values()) and len(r["steps"]) == 4


def test_new_routes_need_the_login(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    _league_files(snap, True)
    c = TestClient(D.create_app(str(snap), D.hash_password("pw-123"), b"x" * 32, live=Live(mode="off")), base_url="http://league.test")
    for path in ("/api/insight", "/api/race", "/api/rules"):
        assert c.get(path).status_code == 401, path


def test_rules_doc_on_the_league_shape():
    """rules_doc over the five accounts of a pick: each role's exit and size, the cell's 기본값 once per pick."""
    cand = {"id": "core-DOGE-15m-1", "role": "cand", "kind": "core", "name": "DOGE", "tf": "15m", "exit": "tp3R|4",
            "exit_ko": X.exit_ko("tp3R|4"), "size": 1.0}
    accts = [cand, {**cand, "id": "core-DOGE-15m-1-q", "role": "quarter", "size": 0.25, "of": cand["id"]},
             {**cand, "id": "core-DOGE-15m-1-x", "role": "exitonly", "of": cand["id"]},
             {**cand, "id": "core-DOGE-15m-1-flip", "role": "flip", "of": cand["id"]},
             {**cand, "id": "base-core-DOGE-15m", "role": "base", "exit": "ladder|2", "exit_ko": X.exit_ko("ladder|2")}]
    book = {"core-DOGE-15m-1-q": {"trades": [{"leverage": 50}, {"leverage": 30}]}, "base-core-DOGE-15m": {"trades": [{"leverage": 40}]}}
    atr = {"15m": {"BTCUSD": {"price": 60000.0, "atr": 78.0, "pct": 0.0013}}}
    r = D.rules_doc({"accounts": accts, "ds_money": True, "generated_ms": 1}, book, EX, atr)
    p = r["picks"]["core-DOGE-15m-1"]
    assert list(p["roles"]) == ["cand", "quarter", "exitonly", "base", "flip"]
    assert p["roles"]["quarter"]["size"] == 0.25 and p["roles"]["quarter"]["used"] == {"50": 1, "30": 1}
    assert p["roles"]["base"]["exit"] == "ladder|2" and p["roles"]["base"]["used"] == {"40": 1}
    assert p["best_ok"] is True and p["p_best"] == pytest.approx(0.2155)
    now = p["now"]["BTCUSD"]
    assert now["lev"]["cand"] == {"best": 40, "normal": 30} and now["lev"]["quarter"]["best"] == 50
    assert now["base_stop_pct"] == pytest.approx(2 * 78.0 / 60000.0) and now["stop_pct"] == pytest.approx(4 * 78.0 / 60000.0)
    assert r["used_all"] == {"quarter": {"50": 1, "30": 1}, "base": {"40": 1}, "cand": {}, "exitonly": {}, "flip": {}}
    assert D.rules_doc(None, None, EX, None) == {"status": "준비 중", "picks": {}}
    # a pick row without its exit (a hand-made or half-written snapshot) is left out of the picks and the exits count, never a KeyError
    bare = {k: v for k, v in cand.items() if k not in ("exit", "exit_ko")}
    both = D.rules_doc({"accounts": [bare, {**cand, "id": "core-LTC-15m-1"}], "ds_money": True, "generated_ms": 1}, {}, EX, atr)
    assert list(both["picks"]) == ["core-LTC-15m-1"] and both["exits"] == {"tp3R|4": 1}
    assert D.rules_doc({"accounts": [bare], "generated_ms": 1}, {}, EX, atr)["picks"] == {}
