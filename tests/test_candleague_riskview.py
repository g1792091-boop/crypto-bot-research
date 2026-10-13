"""candleague 위험 점검, server side: candleague/riskview.py (league.json key ``risk``) written by runner.write_snapshots next to ``decision``.

Hand-made rows (the snapshot's accounts: wallet, bust flag, open position) and closed trades; every number is checked by hand or against a plain
Python reference written independently of the module (loops, no numpy):
  * (1) the open positions: long / short, per coin, the largest same-side cluster ("롱 11개 중 BTC·ETH·SOL 9개"), the flag (>= 80% one side AND
    >= 10 open: both edges), the margin and the "every open stop hits at once" loss as separate wallets and as ONE wallet, the rebuilt margin
    against dash.rebuild_open, what is left out (stop already in profit, no stop, no leverage);
  * (2) the worst that happened: worst trade over its wallet BEFORE it, losing streaks, the equal-weight basket drawdown (accounts without a trade
    still count, trades of one instant are one step, the order of the input changes nothing), liquidations, busts, the share ended by the stop;
  * (3) the days with >= 80% of the entries on one side (UTC day edge, the minimum of 10 entries, the coin twin as the reference);
  * the kinds shown (실전 후보, 대조, the next 메인 kinds up to four, 메인 전체), DeepSeek money both ways (nothing leaks), JSON without NaN,
    deterministic, odd input, a million trades quickly, the sentence (counts, no advice), the limits, the module's hygiene;
  * runner.write_snapshots carrying the key in a league with a lineup only and never stopping the snapshot."""

from __future__ import annotations

import copy
import json
import math
import os
import random
import re
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from candleague import riskview as RV  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague import summary as SM  # noqa: E402

H, DAY, MIN = 3_600_000, 86_400_000, 60_000
T0 = (1_791_000_000_000 // DAY) * DAY
EQ = 1000.0
LU = [{"role": s[1:], "suffix": s, "label_ko": lab, "short_ko": sh} for s, lab, sh in (
    ("-fq", "메인 · 구조 확실히 무너지면 빠른 손절 (실전 후보)", "빠른 손절"), ("-nv", "메인 · 매매법 자체 판단으로 청산", "자체 판단"),
    ("-sw", "메인 · 반대 신호 나오면 스위칭", "스위칭"), ("-tg", "메인 · 구조 무너지면 손절 좁힘", "손절 좁힘"),
    ("-iv", "메인 · 처음 손절을 자체 무효화 가격에", "자체 무효화"), ("-ld", "대조 · 계단 · 손절 최대 2 ATR", "계단"),
    ("-ldc", "대조 · 계단 · 동전 던지기", "계단 동전"), ("-fqc", "대조 · 메인 빠른 손절의 동전 던지기 짝", "빠른 손절 동전"),
    ("-ldt", "필터 · 대조에 BTC 4시간 추세 방향만", "추세 필터"))]
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]


# ---------------------------------------------------------------- builders
def pos(sym="BTCUSDT", side=1, entry=100.0, stop=97.0, lev=30):
    return {"symbol": sym, "side": side, "entry": entry, "stop": stop, "tp": None, "since": T0, "lev": lev}


def row(aid, role, wallet=EQ, kind="core", opened=None, size=1.0, bust=False, pick=None):
    return {"id": aid, "role": role, "kind": kind, "wallet": wallet, "size": size, "bust": bust, "open": opened, "pick": pick or aid.rsplit("-", 1)[0]}


def tr(side, entry, exit_, pnl, sym="BTCUSDT", why="SL", lev=30):
    return {"symbol": sym, "side": side, "entry_time": entry, "exit_time": exit_, "pnl": pnl, "roe": pnl / 100.0, "leverage": lev, "exit_reason": why}


def views(rows, book=None, lineup=LU, eq=EQ, ds=False):
    return RV.risk_views(book or {}, rows, lineup, eq, ds)


def kind(out, suffix):
    return next(k for k in out["kinds"] if k["suffix"] == suffix)


def opens_row(role, specs, wallet=EQ):
    """One row per spec (sym, side, entry, stop, lev) for the role, ids <role>-0..."""
    return [row(f"p{i}-{role}", role, wallet, opened=pos(*s)) for i, s in enumerate(specs)]


# ---------------------------------------------------------------- (1) the open positions
def test_counts_per_coin_and_the_largest_same_side_cluster():
    specs = ([("BTCUSDT", 1)] * 4 + [("ETHUSDT", 1)] * 3 + [("SOLUSDT", 1)] * 2 + [("DOGEUSDT", 1), ("LTCUSDT", 1), ("BTCUSDT", -1)])
    rows = opens_row("fq", [(s, d, 100.0, 97.0, 30) for s, d in specs]) + [row("x1-fq", "fq"), row("x2-fq", "fq")]
    n = kind(views(rows), "-fq")["now"]
    assert (n["open"], n["long"], n["short"], n["same_side"]) == (12, 11, 1, 1)
    assert n["same_side_share"] == pytest.approx(11 / 12, abs=1e-6) and n["crowded"] is True
    assert [(c["coin"], c["long"], c["short"]) for c in n["coins"]] == [("BTC", 4, 1), ("ETH", 3, 0), ("SOL", 2, 0), ("DOGE", 1, 0), ("LTC", 1, 0)]
    assert n["cluster"] == {"side": 1, "side_n": 11, "coins": ["BTC", "ETH", "SOL"], "n": 9, "text_ko": "롱 11개 중 BTC·ETH·SOL 9개"}
    assert kind(views(rows), "-fq")["accounts"] == 14                       # the two accounts without a position are accounts too


def test_the_cluster_may_be_the_short_side_and_says_all_when_the_side_has_few_coins():
    # 3 longs on three coins (top three = 3) against 5 shorts on one coin (top = 5): the short side is the larger cluster
    specs = [("BTCUSDT", 1), ("ETHUSDT", 1), ("SOLUSDT", 1)] + [("BTCUSDT", -1)] * 5
    n = kind(views(opens_row("fq", [(s, d, 100.0, 97.0 if d > 0 else 103.0, 30) for s, d in specs])), "-fq")["now"]
    assert n["cluster"] == {"side": -1, "side_n": 5, "coins": ["BTC"], "n": 5, "text_ko": "숏 5개 모두 BTC"}
    assert n["same_side"] == -1 and n["crowded"] is False                  # 5 of 8: neither 10 open nor 80%
    # a tie goes to the long side, and the coin order of a tie is alphabetical
    specs = [("ETHUSDT", 1), ("BTCUSDT", 1), ("ETHUSDT", -1), ("BTCUSDT", -1)]
    n = kind(views(opens_row("fq", [(s, d, 100.0, 97.0 if d > 0 else 103.0, 30) for s, d in specs])), "-fq")["now"]
    assert n["cluster"]["side"] == 1 and n["cluster"]["coins"] == ["BTC", "ETH"] and n["same_side"] is None and n["same_side_share"] == 0.5


@pytest.mark.parametrize("longs, shorts, crowded", [(9, 0, False), (10, 0, True), (8, 2, True), (7, 3, False), (2, 8, True), (5, 5, False), (79, 20, False), (80, 20, True)])
def test_the_flag_needs_ten_open_and_eighty_percent_the_edges(longs, shorts, crowded):
    specs = [("BTCUSDT", 1, 100.0, 97.0, 30)] * longs + [("ETHUSDT", -1, 100.0, 103.0, 30)] * shorts
    n = kind(views(opens_row("fq", specs)), "-fq")["now"]
    assert n["open"] == longs + shorts and n["crowded"] is crowded


def test_nothing_open_is_none_not_zero_shares():
    n = kind(views([row("a-fq", "fq"), row("b-fq", "fq")]), "-fq")["now"]
    assert n["open"] == 0 and n["same_side"] is None and n["same_side_share"] is None and n["cluster"] is None and n["coins"] == [] and n["crowded"] is False
    assert n["margin"]["sum"] == 0.0 and n["margin"]["separate_pct"] == 0.0 and n["stop"]["loss"] == 0.0 and n["lev_mean"] is None


def test_margin_and_the_stop_loss_by_hand_for_separate_wallets_and_for_one():
    # wallet 1000, 30x, size 1: margin share 30%, the entry fee 0.3 x 30 x 0.0005 of the equity at entry is already out of the wallet
    frac = 0.3
    margin = 1000.0 / (1 - frac * 30 * RV.TAKER_FEE) * frac
    loss = margin * 30 * 0.03                                               # a 3% stop at 30x on that margin
    rows = [row("a-fq", "fq", 1000.0, opened=pos("BTCUSDT", 1, 100.0, 97.0, 30)),
            row("b-fq", "fq", 1000.0, opened=pos("ETHUSDT", -1, 100.0, 103.0, 30)),        # a short: stop above the entry, the same loss
            row("c-fq", "fq", 2000.0), row("d-fq", "fq", 1000.0)]
    n = kind(views(rows), "-fq")["now"]
    wallets = 5000.0
    assert n["margin"]["n"] == 2 and n["margin"]["sum"] == pytest.approx(2 * margin, abs=0.01) and n["margin"]["wallets"] == wallets and n["margin"]["wallet_mean"] == 1250.0
    assert n["margin"]["separate_pct"] == pytest.approx(2 * margin / wallets, abs=1e-6) and n["margin"]["shared_pct"] == pytest.approx(2 * margin / 1250.0, abs=1e-6)
    s = n["stop"]
    assert (s["n"], s["locked"], s["no_stop"]) == (2, 0, 0) and s["loss"] == pytest.approx(2 * loss, abs=0.01)
    assert s["long_loss"] == pytest.approx(loss, abs=0.01) and s["short_loss"] == pytest.approx(loss, abs=0.01)
    assert s["separate_pct"] == pytest.approx(2 * loss / wallets, abs=1e-6) and s["shared_pct"] == pytest.approx(2 * loss / 1250.0, abs=1e-6)
    assert s["shared_pct"] == pytest.approx(s["separate_pct"] * 4, abs=1e-5)         # one wallet instead of four: four times the share
    assert s["worst_acct_pct"] == pytest.approx(loss / 1000.0, abs=1e-6)             # the account that is hit hardest
    assert n["lev_mean"] == 30.0 and n["lev_max"] == 30.0 and n["margin"]["exact"] is False


def test_what_is_left_out_of_the_stop_loss_and_why():
    rows = [row("a-fq", "fq", opened=pos("BTCUSDT", 1, 100.0, 97.0, 30)),         # counted
            row("b-fq", "fq", opened=pos("BTCUSDT", 1, 100.0, 101.0, 30)),        # the stop is above the entry: a locked gain, not a loss
            row("c-fq", "fq", opened=pos("BTCUSDT", -1, 100.0, 99.0, 30)),        # a short whose stop is below the entry: locked
            row("d-fq", "fq", opened={**pos(), "stop": None}),                    # no stop at all
            row("e-fq", "fq", opened={**pos(), "lev": None}),                     # no leverage: no margin, no loss, still an open position
            row("f-fq", "fq", wallet=None, opened=pos())]                         # no wallet: the same
    n = kind(views(rows), "-fq")["now"]
    assert n["open"] == 6 and n["long"] == 5 and n["short"] == 1
    assert (n["stop"]["n"], n["stop"]["locked"], n["stop"]["no_stop"]) == (1, 2, 1) and n["margin"]["n"] == 4 and n["margin"]["missing"] == 2
    one = kind(views(rows[:1]), "-fq")["now"]["stop"]["loss"]
    assert n["stop"]["loss"] == one                                                # only the first one counts


@pytest.mark.parametrize("size", [1.0, 0.25])
def test_the_rebuilt_margin_is_the_one_the_dashboard_rebuilds(size):
    from candleague import dash as D
    assert RV.TAKER_FEE == D.TAKER_FEE
    for lev, wallet in ((50, 1000.0), (40, 1234.5), (30, 876.5), (20, 1000.0)):
        o = pos("BTCUSDT", 1, 100.0, 97.0, lev)
        mine = kind(views([row("a-fq", "fq", wallet, opened=o, size=size)]), "-fq")["now"]["margin"]["sum"]
        theirs = D.rebuild_open(o, wallet, size, None)["margin"]               # the same rule without the order-size rounding
        assert mine == pytest.approx(theirs, rel=1e-6, abs=0.01), (lev, wallet)
    ex = D.load_exchange()                                                      # with the real order steps the rounding moves it by a hair
    if ex:
        o = pos("BTCUSDT", 1, 60000.0, 59000.0, 30)
        assert kind(views([row("a-fq", "fq", 1000.0, opened=o, size=size)]), "-fq")["now"]["margin"]["sum"] == pytest.approx(D.rebuild_open(o, 1000.0, size, ex)["margin"], rel=0.02)


# ---------------------------------------------------------------- (2) the worst that happened
def world_two_accounts():
    """A: +100 -200 -300 +50 -10 at t = 1..5 (wallet 1000 > 1100 > 900 > 600 > 650 > 640); B: -100 at 2.5, +300 at 4.5 (1000 > 900 > 1200)."""
    a = [tr(1, T0 + i * H, T0 + (i + 1) * H, p, "BTCUSDT", why) for i, (p, why) in enumerate(((100, "TP"), (-200, "SL"), (-300, "LIQ"), (50, "LOCK"), (-10, "SL")))]
    b = [tr(-1, T0 + 2 * H, T0 + int(2.5 * H), -100, "ETHUSDT", "SL"), tr(-1, T0 + 4 * H, T0 + int(4.5 * H), 300, "ETHUSDT", "RULE")]
    return {"p0-fq": a, "p1-fq": b}


def test_worst_trade_streak_drawdown_liquidation_and_the_stop_share_by_hand():
    book = world_two_accounts()
    rows = [row("p0-fq", "fq", 640.0), row("p1-fq", "fq", 1200.0)]
    w = kind(views(rows, book), "-fq")["worst"]
    assert (w["trades"], w["accounts"]) == (7, 2)
    t = w["trade"]
    assert t["pct"] == pytest.approx(-300 / 900, abs=1e-6) and t["pnl"] == -300 and t["coin"] == "BTC" and t["side"] == 1 and t["reason"] == "LIQ"
    assert t["account"] == "p0-fq" and t["exit_ms"] == T0 + 3 * H and t["lev"] == 30
    # B's worst is -100 / 1000 = -10%: not the worst; A's -200 / 1100 = -18.2%: not the worst either
    assert w["streak"] == {"max": 2, "median": 1.5, "now_max": 1, "account": "p0-fq"}
    assert w["dd"]["acct_worst"] == pytest.approx(500 / 1100, abs=1e-6) and w["dd"]["acct_worst_id"] == "p0-fq" and w["dd"]["accounts"] == 2
    # the average wallet: 1000 + (running sum of both accounts' P&L) / 2 -> 1050, 950, 900, 750, 775, 925, 920: peak 1050, trough 750
    assert w["dd"]["basket"] == pytest.approx(300 / 1050, abs=1e-6)
    assert (w["liq_n"], w["sl_n"], w["lock_n"], w["bust"]) == (1, 3, 1, 0) and w["stop_share"] == pytest.approx(3 / 7, abs=1e-6)


def test_an_account_without_a_trade_still_counts_in_the_basket_and_a_bust_is_counted():
    book = world_two_accounts()
    rows = [row("p0-fq", "fq", 640.0), row("p1-fq", "fq", 1200.0), row("p2-fq", "fq", 1000.0), row("p3-fq", "fq", 0.0, bust=True)]
    w = kind(views(rows, book), "-fq")["worst"]
    # four accounts, two of them never traded: the sum of P&L over 4: 1000 + cum / 4 -> peak 1025, trough 1000 - 500/4 = 875
    assert w["dd"]["basket"] == pytest.approx((1025 - 875) / 1025, abs=1e-6) and w["dd"]["accounts"] == 4 and w["bust"] == 1 and w["accounts"] == 2


def test_trades_of_one_instant_are_one_step_and_the_input_order_changes_nothing():
    # +300 and -300 at the same instant on two accounts: the average wallet does not move (no spurious peak between the two)
    a = [tr(1, T0, T0 + H, 300), tr(1, T0 + H, T0 + 2 * H, -100)]
    b = [tr(1, T0, T0 + H, -300), tr(1, T0 + H, T0 + 2 * H, -100)]
    rows = [row("a-fq", "fq"), row("b-fq", "fq")]
    for book, rws in (({"a-fq": a, "b-fq": b}, rows), ({"b-fq": b, "a-fq": a}, rows[::-1])):
        w = kind(views(rws, book), "-fq")["worst"]
        assert w["dd"]["basket"] == pytest.approx(100 / 1000, abs=1e-6)             # only the second step: 1000 -> 900
    assert views(rows, {"a-fq": a, "b-fq": b}) == views(rows[::-1], {"b-fq": b, "a-fq": a})


def test_no_trade_at_all_is_none_not_zero():
    w = kind(views([row("a-fq", "fq")]), "-fq")["worst"]
    assert w["trades"] == 0 and w["trade"] is None and w["streak"]["max"] is None and w["dd"]["basket"] is None and w["stop_share"] is None
    assert w["liq_n"] == 0 and w["sl_n"] == 0


def test_a_run_of_wins_has_no_streak_and_a_zero_trade_breaks_a_streak():
    rows = [row("a-fq", "fq"), row("b-fq", "fq")]
    wins = [tr(1, T0 + i * H, T0 + (i + 1) * H, 10) for i in range(4)]
    mixed = [tr(1, T0 + i * H, T0 + (i + 1) * H, p) for i, p in enumerate((-1, -1, 0, -1, -1, -1, 5))]
    w = kind(views(rows, {"a-fq": wins, "b-fq": mixed}), "-fq")["worst"]
    assert w["streak"]["max"] == 3 and w["streak"]["account"] == "b-fq" and w["streak"]["now_max"] == 0 and w["streak"]["median"] == 1.5
    only = kind(views(rows[:1], {"a-fq": wins}), "-fq")["worst"]
    assert only["streak"]["max"] == 0 and only["trade"]["pct"] > 0                 # all wins: the "worst" trade is the smallest win, said as it is


def test_the_wallet_before_the_trade_is_the_realised_wallet_not_the_start():
    # +1000 then -1000: the second trade loses 50% of the wallet it had, not 100% of the start wallet
    t = [tr(1, T0, T0 + H, 1000), tr(1, T0 + H, T0 + 2 * H, -1000)]
    w = kind(views([row("a-fq", "fq")], {"a-fq": t}), "-fq")["worst"]
    assert w["trade"]["pct"] == pytest.approx(-0.5, abs=1e-6)
    assert w["dd"]["acct_worst"] == pytest.approx(1000 / 2000, abs=1e-6)


def test_a_wallet_gone_is_a_drawdown_of_one_and_no_division_by_zero():
    t = [tr(1, T0, T0 + H, -1000), tr(1, T0 + H, T0 + 2 * H, -50)]               # the wallet is 0 before the second one
    out = views([row("a-fq", "fq", 0.0, bust=True)], {"a-fq": t})
    w = kind(out, "-fq")["worst"]
    assert w["trade"]["pct"] == pytest.approx(-1.0, abs=1e-6) and w["dd"]["acct_worst"] == 1.0 and w["dd"]["basket"] == 1.0
    json.dumps(out, allow_nan=False)


# ---------------------------------------------------------------- (3) the days the entries piled up on one side
def entries(day, longs, shorts, hour=1):
    return [tr(1, T0 + day * DAY + hour * H + i * MIN, T0 + day * DAY + hour * H + i * MIN + H, 1.0) for i in range(longs)] + \
           [tr(-1, T0 + day * DAY + hour * H + (longs + i) * MIN, T0 + day * DAY + hour * H + (longs + i) * MIN + H, 1.0) for i in range(shorts)]


def spread(trades, role, n_acc=10):
    """Deal the trades over n_acc accounts (the way a day's entries come from many accounts)."""
    book = {f"p{i}-{role}": [] for i in range(n_acc)}
    for j, t in enumerate(trades):
        book[f"p{j % n_acc}-{role}"].append(t)
    for v in book.values():
        v.sort(key=lambda t: t["exit_time"])
    return book, [row(k, role) for k in book]


def test_the_share_of_days_with_eighty_percent_one_side_by_hand():
    t = entries(0, 10, 0) + entries(1, 8, 2) + entries(2, 7, 3) + entries(3, 5, 0) + entries(4, 1, 9)
    book, rows = spread(t, "fq")
    d = kind(views(rows, book), "-fq")["days"]
    # day 0: 10/0 crowded long; day 1: 8/2 = 80% crowded long (the edge); day 2: 7/3 no; day 3: 5 entries: too few to count; day 4: 1/9 crowded short
    assert (d["total"], d["eligible"], d["crowded"], d["long"], d["short"]) == (5, 4, 3, 2, 1) and d["share"] == 0.75
    assert d["lopsided"] == {"day_ms": T0, "n": 10, "share": 1.0, "side": 1}      # the largest share (day 0 and day 4 tie on n: the later day wins)
    assert d["min_trades"] == 10 and d["threshold"] == 0.8


def test_the_most_lopsided_day_is_the_largest_share_then_the_most_entries_then_the_later_day():
    t = entries(0, 9, 1) + entries(1, 18, 2) + entries(2, 1, 9) + entries(3, 12, 0)
    book, rows = spread(t, "fq")
    d = kind(views(rows, book), "-fq")["days"]
    assert d["lopsided"] == {"day_ms": T0 + 3 * DAY, "n": 12, "share": 1.0, "side": 1}
    t = entries(0, 10, 0) + entries(1, 0, 10)
    book, rows = spread(t, "fq")
    assert kind(views(rows, book), "-fq")["days"]["lopsided"]["day_ms"] == T0 + DAY      # a full tie: the later day, and its side is short
    assert kind(views(rows, book), "-fq")["days"]["lopsided"]["side"] == -1


def test_the_day_is_the_utc_day_of_the_entry_and_midnight_belongs_to_the_next_day():
    # ten entries at 23:59:59.999 and ten at 00:00:00.000: two days with ten each, not one day of twenty
    late = [tr(1, T0 + DAY - 1, T0 + DAY + H, 1.0) for _ in range(10)]
    early = [tr(-1, T0 + DAY, T0 + DAY + H, 1.0) for _ in range(10)]
    book, rows = spread(late + early, "fq")
    d = kind(views(rows, book), "-fq")["days"]
    assert (d["total"], d["eligible"], d["crowded"], d["long"], d["short"]) == (2, 2, 2, 1, 1)


def test_days_without_a_dated_entry_or_a_side_are_not_counted():
    t = entries(0, 10, 0) + [{**tr(1, T0, T0 + H, 1.0), "entry_time": None}, {**tr(1, T0, T0 + H, 1.0), "side": 0}, {**tr(1, T0, T0 + H, 1.0), "side": None}]
    book, rows = spread(t, "fq")
    d = kind(views(rows, book), "-fq")["days"]
    assert d["total"] == 1 and d["eligible"] == 1 and d["crowded"] == 1
    none = kind(views([row("a-fq", "fq")]), "-fq")["days"]
    assert (none["total"], none["eligible"], none["crowded"], none["share"], none["lopsided"]) == (0, 0, 0, None, None)


def test_the_coin_twin_is_the_reference_for_random_directions():
    real, rr = spread(entries(0, 10, 0) + entries(1, 10, 0) + entries(2, 5, 5) + entries(3, 6, 4), "fq")
    twin, tw = spread(entries(0, 5, 5) + entries(1, 6, 4) + entries(2, 5, 5) + entries(3, 4, 6), "fqc")
    out = views(rr + tw, {**real, **twin})
    d = kind(out, "-fq")["days"]
    assert (d["eligible"], d["crowded"]) == (4, 2)
    assert d["coin_ref"] == {"suffix": "-fqc", "name_ko": "빠른 손절 동전", "eligible": 4, "crowded": 0, "share": 0.0}
    assert all(k["suffix"] != "-fqc" for k in out["kinds"])                       # the twin is a reference, not a row of its own


# ---------------------------------------------------------------- a plain reference, independent of the module
def reference(rows, book, eq0):
    """The same numbers by plain loops: (worst pct, streak max, basket drawdown, days (total, eligible, crowded)) of one kind's accounts."""
    worst, streak = None, 0
    events, entries_ = [], []
    for r in rows:
        w, run = eq0, 0
        for t in book.get(r["id"], []):
            pct = t["pnl"] / w if w > 0 else 0.0
            worst = pct if worst is None else min(worst, pct)
            run = run + 1 if t["pnl"] < 0 else 0
            streak = max(streak, run)
            w += t["pnl"]
            events.append((t["exit_time"], t["pnl"]))
            if t.get("entry_time") is not None and t.get("side"):
                entries_.append((t["entry_time"] // DAY, 1 if t["side"] > 0 else -1))
    events.sort()
    n, cum, peak, dd, i = len(rows), 0.0, eq0, 0.0, 0
    while i < len(events):
        j = i
        while j < len(events) and events[j][0] == events[i][0]:
            cum += events[j][1]
            j += 1
        b = eq0 + cum / n
        peak = max(peak, b)
        dd = max(dd, (peak - b) / peak)
        i = j
    days = {}
    for d, s in entries_:
        c = days.setdefault(d, [0, 0])
        c[0 if s > 0 else 1] += 1
    elig = [c for c in days.values() if sum(c) >= RV.MIN_DAY_TRADES]
    crowd = [c for c in elig if max(c) >= RV.SAME_SIDE * sum(c) - 1e-9]
    return worst, streak, dd, (len(days), len(elig), len(crowd))


def random_world(seed, n_acc=6, n_tr=60, ties=False):
    rnd = random.Random(seed)
    rows, book = [], {}
    for i in range(n_acc):
        aid = f"p{i}-fq"
        ts = []
        for _ in range(n_tr):
            e = T0 + rnd.randrange(0, 6 * DAY) // (H if ties else 1) * (H if ties else 1)
            ts.append(tr(rnd.choice([1, -1]), e, e + rnd.randrange(1, 5) * H, round(rnd.uniform(-60, 70), 2)))
        ts.sort(key=lambda t: t["exit_time"])
        book[aid] = ts
        rows.append(row(aid, "fq", EQ + sum(t["pnl"] for t in ts)))
    return rows, book


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("ties", [False, True])
def test_every_closed_trade_number_equals_the_plain_reference(seed, ties):
    rows, book = random_world(seed, ties=ties)
    k = kind(views(rows, book), "-fq")
    worst, streak, dd, days = reference(rows, book, EQ)
    assert k["worst"]["trade"]["pct"] == pytest.approx(worst, abs=1e-6)
    assert k["worst"]["streak"]["max"] == streak
    assert k["worst"]["dd"]["basket"] == pytest.approx(dd, abs=1e-6)
    assert (k["days"]["total"], k["days"]["eligible"], k["days"]["crowded"]) == days
    assert k["trades"] == sum(len(v) for v in book.values()) == k["worst"]["trades"]


# ---------------------------------------------------------------- the kinds shown, the pool, DeepSeek
def lineup_world(per_kind=3, roles=("fq", "ld", "nv", "sw", "tg", "iv", "ldc", "fqc", "ldt")):
    rows, book = [], {}
    for role in roles:
        for i in range(per_kind):
            aid = f"p{i}-{role}"
            book[aid] = [tr(1, T0 + j * H, T0 + (j + 1) * H, 5.0 * (1 if (i + j) % 3 else -1)) for j in range(4)]
            rows.append(row(aid, role, EQ + sum(t["pnl"] for t in book[aid]), opened=pos(COINS[i % 6], 1 if i % 2 else -1, 100.0, 97.0 if i % 2 else 103.0, 30)))
    return rows, book


def test_the_kinds_shown_are_the_live_one_the_control_the_next_main_ones_and_the_pool():
    rows, book = lineup_world()
    out = views(rows, book)
    assert [k["suffix"] for k in out["kinds"]] == ["-fq", "-ld", "-nv", "-sw", None]                  # four kinds, then 메인 전체
    last = out["kinds"][-1]
    assert last["pooled"] is True and last["role"] == "main_all" and last["name_ko"] == "메인 전체" and last["group"] == "main" and last["live"] is False
    assert kind(out, "-fq")["live"] is True and kind(out, "-ld")["group"] == "control" and kind(out, "-nv")["group"] == "main"
    assert kind(out, "-fq")["name_ko"] == "빠른 손절" and kind(out, "-ld")["name_ko"] == "계단"
    # the pool: every 메인 kind of the lineup (fq, nv, sw, tg, iv: 5 x 3 accounts), not only the four shown
    assert last["accounts"] == 15 and last["trades"] == 60 and last["now"]["open"] == 15
    assert last["now"]["long"] + last["now"]["short"] == 15
    # no other kind (the coin twins, the filters) is a row
    assert "-ldc" not in [k["suffix"] for k in out["kinds"]] and "-ldt" not in [k["suffix"] for k in out["kinds"]]


def test_a_missing_kind_is_left_out_and_one_main_kind_has_no_pool():
    rows, book = lineup_world(roles=("fq", "ld"))
    out = views(rows, book)
    assert [k["suffix"] for k in out["kinds"]] == ["-fq", "-ld"]                                      # one 메인 kind: no pool
    rows, book = lineup_world(roles=("nv", "sw"))
    out = views(rows, book)
    assert [k["suffix"] for k in out["kinds"]] == ["-nv", "-sw", None] and not any(k["live"] for k in out["kinds"])
    assert "열린 포지션" in out["headline_ko"] and out["headline_ko"].startswith("자체 판단:")        # no live kind: the first one is the sentence's subject
    empty = views([], {})
    assert empty["kinds"] == [] and empty["headline_ko"] == "아직 보여 줄 계좌 종류가 없습니다" and views(rows, book, lineup=None)["kinds"] == []
    assert views(rows, book, lineup=[])["kinds"] == []


def ds_extra(role="fq", n=12, ds_id="ds-X-1h-1"):
    """DeepSeek accounts of the kind with big money, open positions and busted wallets."""
    rows, book = [], {}
    for i in range(n):
        aid = f"{ds_id}{i}-{role}"
        book[aid] = [tr(1, T0 + j * H, T0 + (j + 1) * H, -400.0 if j else 900.0, why="LIQ") for j in range(5)]
        rows.append(row(aid, role, kind="ds", wallet=77.0, bust=True, opened=pos("BCHUSDT", 1, 100.0, 50.0, 50)))
    return rows, book


def test_deepseek_money_never_leaks_without_the_switch_and_counts_with_it():
    rows, book = lineup_world()
    d_rows, d_book = ds_extra()
    base = views(rows, book)
    hidden = views(rows + d_rows, {**book, **d_book})
    assert json.dumps(hidden, sort_keys=True) == json.dumps(base, sort_keys=True)                    # identical: not even a count differs
    text = json.dumps(hidden, ensure_ascii=False)
    assert "ds-X" not in text and "BCH" not in json.dumps(kind(hidden, "-fq")["now"]["coins"]) and hidden["ds_in_stats"] is False
    on = views(rows + d_rows, {**book, **d_book}, ds=True)
    assert on["ds_in_stats"] is True and on != base
    f, f0 = kind(on, "-fq"), kind(base, "-fq")
    assert f["accounts"] == f0["accounts"] + 12 and f["now"]["open"] == f0["now"]["open"] + 12 and f["worst"]["liq_n"] == 60 and f["worst"]["bust"] == 12
    assert any(c["coin"] == "BCH" for c in f["now"]["coins"])
    # the pooled kind and the coin twin follow the same rule
    assert kind(on, None)["accounts"] == kind(base, None)["accounts"] + 12
    # a role that only DeepSeek accounts have is not a row without the switch
    only = views(d_rows, d_book)
    assert only["kinds"] == [] and views(d_rows, d_book, ds=True)["kinds"][0]["accounts"] == 12
    # the rows the snapshot has (DeepSeek money already hidden there: wallet None) change nothing either
    masked = [{**r, "wallet": None, "open": {"symbol": "BCHUSDT", "side": 1, "since": T0}} for r in d_rows]
    assert json.dumps(views(rows + masked, {**book, **d_book}), sort_keys=True) == json.dumps(base, sort_keys=True)


def test_the_two_small_rules_are_the_summary_modules_rules():
    for a in ({"kind": "core"}, {"kind": "ds"}, {}):
        for ds in (True, False):
            assert RV._shown(a, ds) == SM._shown(a, ds)
    for label in ("메인 · x", "대조 · x", "필터 · x", "연구 · x", "", None, "  메인 · 앞 공백"):
        assert RV._group(label) == SM.kind_group(label)


# ---------------------------------------------------------------- JSON, odd input, determinism, speed
def test_the_block_is_strict_json_and_deterministic_whatever_the_input_order():
    rows, book = lineup_world()
    out = views(rows, book)
    text = json.dumps(out, ensure_ascii=False, allow_nan=False)
    assert json.loads(text) == out
    shuffled_rows = rows[:]
    random.Random(3).shuffle(shuffled_rows)
    shuffled_book = dict(random.Random(4).sample(sorted(book.items()), len(book)))
    assert json.dumps(views(shuffled_rows, shuffled_book), sort_keys=True) == json.dumps(out, sort_keys=True)
    assert views(rows, book) == views(copy.deepcopy(rows), copy.deepcopy(book))


def test_odd_input_does_not_raise_and_says_dashes_not_zeros():
    rows = [
        {"id": "a-fq", "role": "fq", "kind": "core"},                                                          # no wallet, no open
        {"id": "b-fq", "role": "fq", "kind": "core", "wallet": float("nan"), "open": {"symbol": None, "side": "1", "entry": "x", "stop": float("nan"), "lev": True}},
        {"id": "c-fq", "role": "fq", "kind": "core", "wallet": 1000, "open": {"symbol": "BTCUSDT", "side": 0}},    # side unknown: not counted
        {"id": "d-fq", "role": "fq", "kind": "core", "wallet": 1000, "open": {"symbol": "BTCUSDT", "side": -1, "entry": 100, "stop": 0, "lev": 0}},
        {"role": "fq", "kind": "core"}, {"id": "z", "kind": "core"}, {"id": "y-zz", "role": "zz", "kind": "core"},
    ]
    book = {"a-fq": [{"pnl": None, "side": None, "entry_time": None, "exit_time": None}, {"pnl": float("nan")}, {}], "b-fq": None}
    out = views(rows, book, lineup=LU + [{"role": "x"}, {"suffix": "-q"}, {}])
    json.dumps(out, allow_nan=False)
    f = kind(out, "-fq")
    n = f["now"]
    assert f["accounts"] == 5 and (n["open"], n["long"], n["short"]) == (2, 1, 1)                  # the side-less position and the id-less rows are not counted
    # open positions the snapshot cannot size are still open positions, but the money figures are unknown (None), never a zero that reads as "safe"
    assert n["margin"]["n"] == 0 and n["margin"]["missing"] == 2 and n["margin"]["sum"] is None and n["margin"]["separate_pct"] is None and n["margin"]["shared_pct"] is None
    assert n["stop"]["loss"] is None and n["stop"]["separate_pct"] is None and n["stop"]["shared_pct"] is None and n["stop"]["worst_acct_pct"] is None
    assert n["lev_mean"] is None and n["cluster"]["coins"] == ["기타"]
    w = f["worst"]
    assert w["trades"] == 3 and w["liq_n"] == 0 and w["trade"]["pnl"] is None and w["trade"]["coin"] is None
    assert f["days"]["total"] == 0 and f["days"]["share"] is None


def test_open_positions_with_no_stop_at_all_have_no_stop_loss_figure_but_a_margin():
    rows = [row("a-fq", "fq", opened={**pos(), "stop": None}), row("b-fq", "fq", opened={**pos(), "stop": None})]
    n = kind(views(rows), "-fq")["now"]
    assert n["margin"]["n"] == 2 and n["margin"]["separate_pct"] > 0 and (n["stop"]["n"], n["stop"]["no_stop"]) == (0, 2)
    assert n["stop"]["loss"] is None and n["stop"]["shared_pct"] is None
    locked = [row("a-fq", "fq", opened=pos("BTCUSDT", 1, 100.0, 101.0, 30))]                        # every stop already on the winning side: a loss of 0 is true
    n = kind(views(locked), "-fq")["now"]
    assert n["stop"]["locked"] == 1 and n["stop"]["loss"] == 0.0 and n["stop"]["shared_pct"] == 0.0 and n["stop"]["worst_acct_pct"] is None


def test_a_million_trades_in_a_few_seconds():
    import numpy as np
    rng = np.random.default_rng(1)
    rows, book = [], {}
    for role in ("fq", "ld", "nv", "sw", "tg", "iv", "ldc", "fqc"):
        for p in range(49):
            aid = f"p{p}-{role}"
            n = 2500
            e = T0 + rng.integers(0, 30 * DAY, n)
            s = rng.choice([1, -1], n)
            pnl = rng.normal(0.3, 12, n)
            book[aid] = sorted(({"symbol": "BTCUSDT", "side": int(s[i]), "entry_time": int(e[i]), "exit_time": int(e[i]) + H, "pnl": float(pnl[i]), "roe": 0.0,
                                 "exit_reason": "SL", "leverage": 30} for i in range(n)), key=lambda t: t["exit_time"])
            rows.append(row(aid, role, EQ + float(pnl.sum()), opened=pos("BTCUSDT", int(s[0]), 100.0, 97.0, 30)))
    total = sum(map(len, book.values()))
    assert total > 900_000
    t = time.perf_counter()
    out = views(rows, book)
    took = time.perf_counter() - t
    assert took < 8.0, took                                                           # about 1 s here; the bound is for slow machines
    assert [k["suffix"] for k in out["kinds"]] == ["-fq", "-ld", "-nv", "-sw", None] and kind(out, "-fq")["trades"] == 49 * 2500


# ---------------------------------------------------------------- the words: counts only, the limits, the wallet
ADVICE = ("권합니다", "하세요", "줄이", "늘리", "사세요", "파세요", "피하", "추천", "해야", "좋습니다", "나쁩니다", "위험합니다", "안전")


def test_the_sentence_states_counts_and_never_advice():
    rows, book = lineup_world()
    specs = [("BTCUSDT", 1, 100.0, 97.0, 30)] * 11 + [("ETHUSDT", -1, 100.0, 103.0, 30)]
    big = opens_row("fq", specs)
    others = {k: v for k, v in book.items() if not k.endswith("-fq")}
    mine = {r["id"]: [tr(1, T0, T0 + H, -250.0), tr(1, T0 + H, T0 + 2 * H, 10.0)] for r in big}
    out = views(big + [r for r in rows if r["role"] != "fq"], {**others, **mine})
    s = out["headline_ko"]
    assert s.startswith("빠른 손절: 열린 포지션 12개 중 롱 11개 · 숏 1개 (한 방향 92%), 지금까지 한 거래 최악은 지갑의 −25.0%, 연속으로 진 최다는 1번 (닫힌 거래 24건 기준).")
    assert s.endswith(".") and ". " not in s                                 # one sentence
    for bad in ADVICE:
        assert bad not in s and all(bad not in t for t in out["rules_ko"] + out["note_ko"]), bad
    # nothing open, nothing closed
    z = views([row("a-fq", "fq")])["headline_ko"]
    assert z == "빠른 손절: 지금 열린 포지션이 없습니다 (계좌 1개), 아직 닫힌 거래가 없습니다."


def test_rules_and_limits_are_there_with_the_wallet_of_the_snapshot():
    out = views([row("a-fq", "fq")], eq=1000.0)
    assert out["equity0"] == 1000.0 and out["thresholds"] == {"same_side": 0.8, "min_open": 10, "min_day_trades": 10}
    notes = " ".join(out["note_ko"])
    assert "$1,000" in notes and "5,000" not in notes and "$5,000" not in " ".join(out["rules_ko"])
    assert "따로인 모의 지갑" in notes and "평가손익" in notes and "추정" in notes and "독립이 아닙니다" in notes and "딥시크" in notes     # the limits the owners asked for
    assert "$2,500" in " ".join(views([row("a-fq", "fq")], eq=2500.0)["note_ko"])
    assert "딥시크" not in " ".join(views([row("a-fq", "fq")], ds=True)["note_ko"]) and views([row("a-fq", "fq")], ds=True)["ds_in_stats"] is True
    assert len(out["rules_ko"]) == 6 and out["rules_ko"][1].startswith("쏠림 표시: 열린 포지션이 10개 이상이고 그중 80% 이상")
    assert RV.risk_rules_ko() == out["rules_ko"]
    # the default start wallet is the league's (exits.start_equity), never typed in here
    from candleague import exits as X
    assert RV.risk_views({}, [row("a-fq", "fq")], LU, None, False)["equity0"] == X.start_equity()


def test_the_module_is_pure():
    src = open(os.path.join(ROOT, "candleague", "riskview.py"), encoding="utf-8").read()
    for bad in ("import time", "import random", "import datetime", "from datetime", "time.time", "os.environ", "open(", "5000", "5,000", "import sqlite3"):
        assert bad not in src, bad
    assert "docs/candleague" not in src


# ---------------------------------------------------------------- runner.write_snapshots
def fake_league(tmp_path, owner=True, name="a.db", opened=True):
    """A league with a real trades table, the lineup on and open positions: a core pick's fq and ld (and a DeepSeek pick's, with big numbers)."""
    conn = RN.open_db(str(tmp_path / name))
    lu = {r["role"]: r for r in LU}
    accts, book, engines = [], {}, {}
    for pick, kind_, scale in (("core-A-1h-1", "core", 1.0), ("ds-F5_BOX-1h-1", "ds", 50.0)):
        for role in ("fq", "ld"):
            a = {"id": f"{pick}-{role}", "pick": pick, "role": role, "kind": kind_, "name": "X", "tf": "1h", "combo": {}, "exit": "ladderU|2", "of": pick, "size": 1.0, "source": {}}
            if owner:
                a["ox"] = {**lu[role], "kind": "x", "desc_ko": "d", "why_ko": "w", "tp": None, "weekend_off": False, "size": 1.0, "rule": None}
            accts.append(a)
            book[a["id"]] = []
            for i, p in enumerate((20.0, -60.0, -30.0)):
                t = {**tr(1, T0 + i * 2 * H, T0 + (i * 2 + 1) * H, p * scale, why="SL"), "entry_price": 100.0, "exit_price": 99.0, "stop_initial": 98.0,
                     "tp_price": float("nan"), "mae_price": 99.0, "mfe_price": 101.0, "equity_after": 0.0, "margin": 100.0, "context": {}}
                book[a["id"]].append(t)
                conn.execute("INSERT INTO trades VALUES (?, ?, ?)", (a["id"], t["exit_time"], json.dumps(t)))
            p = SimpleNamespace(symbol="BTCUSDT", side=1, entry_price=100.0, stop_price=97.0, tp_price=float("nan"), entry_time=T0 + 5 * H, leverage=30) if opened else None
            engines[a["id"]] = SimpleNamespace(position=p, wallet=RN.EQUITY + sum(t["pnl"] for t in book[a["id"]]), bust=False)
    conn.commit()
    return SimpleNamespace(conn=conn, accts=accts, engines=engines, done=T0 + 2 * DAY, start_ms=T0, meta={"started_ms": T0, "notes": []}, advanced_ms=None)


NOW = T0 + 2 * DAY + MIN


def test_write_snapshots_carries_the_risk_next_to_the_decision_in_a_league_with_a_lineup(tmp_path):
    lg = fake_league(tmp_path)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=False)
    saved = json.load(open(tmp_path / "snap" / "league.json"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    assert saved["risk"] == doc["risk"] and "decision" in saved and "kinds" in saved and "risk_error" not in doc
    r = saved["risk"]
    assert r["equity0"] == RN.EQUITY and r["ds_in_stats"] is False
    assert [k["suffix"] for k in r["kinds"]] == ["-fq", "-ld"]
    f = kind(r, "-fq")
    assert f["accounts"] == 1 and f["trades"] == 3 and f["now"]["open"] == 1 and f["now"]["long"] == 1 and f["now"]["cluster"]["text_ko"] == "롱 1개 모두 BTC"
    # the wallet is the engine's, 20 - 60 - 30 on the start wallet; the open position is rebuilt from it
    wallet = RN.EQUITY - 70.0
    frac = 0.3
    margin = wallet / (1 - frac * 30 * RV.TAKER_FEE) * frac
    assert f["now"]["margin"]["sum"] == pytest.approx(margin, abs=0.01) and f["now"]["stop"]["loss"] == pytest.approx(margin * 30 * 0.03, abs=0.01)
    assert f["worst"]["trade"]["pct"] == pytest.approx(-60.0 / (RN.EQUITY + 20.0), abs=1e-6) and f["worst"]["streak"]["max"] == 2
    # with the money switch the DeepSeek pick (50x the P&L) is in, and only then
    on = RN.write_snapshots(str(tmp_path / "snap2"), lg, NOW, ds_money=True)["risk"]
    assert on["ds_in_stats"] is True and kind(on, "-fq")["accounts"] == 2 and kind(on, "-fq")["worst"]["trade"]["pct"] < f["worst"]["trade"]["pct"]
    assert json.dumps(r, sort_keys=True) == json.dumps(RN.write_snapshots(str(tmp_path / "snap3"), lg, NOW, ds_money=False)["risk"], sort_keys=True)


def test_write_snapshots_has_no_risk_without_a_lineup_and_never_stops_on_a_failure(tmp_path, monkeypatch):
    lg = fake_league(tmp_path, owner=False)
    assert RX.lineup(lg.accts) is None
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=True)
    assert "risk" not in doc and "risk_error" not in doc
    lg = fake_league(tmp_path, owner=True, name="b.db")

    def boom(*a, **k):
        raise ValueError("boom")
    monkeypatch.setattr(RV, "risk_views", boom)
    doc = RN.write_snapshots(str(tmp_path / "snap2"), lg, NOW, ds_money=True)
    assert "risk" not in doc and doc["risk_error"] == "ValueError: boom" and "decision" in doc                       # the rest of the snapshot is written
    assert "risk" not in json.load(open(tmp_path / "snap2" / "league.json")) and os.path.exists(tmp_path / "snap2" / "trades.json")


def test_write_snapshots_with_nothing_open_says_so(tmp_path):
    lg = fake_league(tmp_path, opened=False)
    r = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=False)["risk"]
    f = kind(r, "-fq")
    assert f["now"]["open"] == 0 and f["now"]["cluster"] is None and "지금 열린 포지션이 없습니다" in r["headline_ko"]
    assert re.search(r"지갑의 −\d", r["headline_ko"]) is not None


# ---------------------------------------------------------------- a real league (the engine's own accounts, positions and trades)
def test_a_real_league_snapshot_agrees_with_the_snapshots_own_accounts_and_the_plain_reference(tmp_path):
    """The owner-exit league on synthetic bars (test_candleague_owner_exits' world) with 메인 labels: the open positions and wallets are the engine's."""
    import test_candleague_owner_exits as OE
    from candleague import dash as D
    owner = {"enabled": True, "owner_exits": [
        {"suffix": "-e", "label_ko": "메인 · 지금 청산"}, {"suffix": "-ma", "rule": "F2.n50.b", "label_ko": "메인 · 이동평균 이탈"},
        {"suffix": "-tp50", "exit": "roe50", "label_ko": "대조 · 고정 익절 ROE 50%"}, {"suffix": "-gb", "rule": "F5.P1.g50.a", "label_ko": "메인 · 큰 수익 반납 보호"},
        {"suffix": "-wk", "weekend_off": True, "label_ko": "대조 · 주말 쉬는 계좌"}]}
    lg = RN.League(RN.open_db(str(tmp_path / "real.db")), RX.accounts(OE.CANDS, RX.normalize_config(owner)), OE.TP.BRACKETS, OE.TP.SPECS, OE.LIB,
                   OE.PS.FrameSource(OE.DATA), OE.TP._steps_from(OE.DATA), OE.TP.SYMS, log=lambda s: None, start_ms=OE.START)
    lg.advance(OE.END)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, OE.END + MIN)
    assert "risk_error" not in doc
    r = json.loads(open(tmp_path / "snap" / "league.json").read(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))["risk"]
    assert [k["suffix"] for k in r["kinds"]] == ["-e", "-ma", "-gb", None]                       # no 실전 후보 / 대조 in this lineup: the 메인 kinds, then 메인 전체
    book = RN.closed_trades(lg.conn, lg.accts)
    opened = [a for a in doc["accounts"] if a["open"]]
    assert opened, "the synthetic run should leave positions open"
    rows_of = lambda roles: [a for a in doc["accounts"] if a["role"] in roles]          # noqa: E731
    for k in r["kinds"]:
        roles = ("cand", "ma", "gb") if k["pooled"] else (k["role"],)
        mine = rows_of(roles)
        o = [a for a in mine if a["open"]]
        assert k["accounts"] == len(mine) and k["now"]["open"] == len(o)
        assert k["now"]["long"] == sum(a["open"]["side"] > 0 for a in o) and k["now"]["short"] == sum(a["open"]["side"] < 0 for a in o)
        assert k["trades"] == sum(len(book[a["id"]]) for a in mine)
        # the margin is the dashboard's rebuilt margin (same rule, no order-size rounding) of every open position
        want = sum(D.rebuild_open(a["open"], float(a["wallet"]), float(a.get("size") or 1.0), None)["margin"] for a in o)
        assert k["now"]["margin"]["sum"] == pytest.approx(want, rel=1e-6, abs=0.01)
        worst, streak, dd, days = reference(mine, book, RN.EQUITY)
        if k["trades"]:
            assert k["worst"]["trade"]["pct"] == pytest.approx(worst, abs=1e-6) and k["worst"]["streak"]["max"] == streak
            assert k["worst"]["dd"]["basket"] == pytest.approx(dd, abs=1e-6) and (k["days"]["total"], k["days"]["eligible"], k["days"]["crowded"]) == days
        else:
            assert k["worst"]["trade"] is None
    # the stop of every open position is on the losing side or the winning side of its entry: the loss counts exactly the first kind
    for k in r["kinds"][:-1]:
        o = [a for a in rows_of((k["role"],)) if a["open"]]
        losing = [a for a in o if a["open"].get("stop") is not None and a["open"]["side"] * (a["open"]["stop"] - a["open"]["entry"]) < 0]
        assert k["now"]["stop"]["n"] == len(losing)
