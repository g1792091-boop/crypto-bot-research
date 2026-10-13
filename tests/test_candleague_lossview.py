"""candleague 손실 해부, server side: candleague/lossview.py (league.json key ``losses``) written by runner.write_snapshots next to ``risk``.

Hand-made closed trades; every number is checked by hand:
  * the loss types: every type, the ORDER of the rules (first match wins), the edges (best = 0.3R / 1R, hold = 12 h, a missing field), a short;
  * a kind's counts, the breakdowns (coin, side, leverage, KST hour band, weekday / weekend), the streak, the same-signal clusters (kinds are never
    mixed), the 10 biggest losses with their replay key, the small-sample flag, the pooled group equal to the sum of the kinds;
  * DeepSeek money both ways (without ``ds_money`` the account is left out of every figure), empty input, JSON without NaN, deterministic;
  * runner.write_snapshots carrying the key in a league with a lineup only, and a failure of the block never stopping the snapshot."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from candleague import lossview as LV  # noqa: E402
from candleague import runner as RN  # noqa: E402
import test_candleague_riskview as RT  # noqa: E402  (its hand-made rows, lineup and fake league)

H, DAY, T0 = RT.H, RT.DAY, RT.T0
KST = dt.timezone(dt.timedelta(hours=9))


def loss(kind="direct", side=1, entry_t=None, hold_h=2.0, why="SL", sym="BTCUSDT", lev=30, roe=-0.5, pnl=-50.0, **over):
    """A losing trade whose type is `kind`, with entry 100 and R = 2 (stop 98 for a long, 102 for a short)."""
    entry_t = T0 + 3 * H if entry_t is None else entry_t
    e, r = 100.0, 2.0
    mfe, mae, ex = e + side * 0.2, e - side * 0.4, e - side * 2.0                      # direct: best 0.1R, exit at the stop
    if kind == "gave_back":
        mfe = e + side * 2.5
    elif kind == "gave_back_small":
        mfe = e + side * 1.0
    elif kind == "gap":
        ex = e - side * 2.5                                                              # end = -1.25R
    elif kind == "liq":
        why, ex = "LIQ", e - side * 3.0
    elif kind == "rule_exit":
        why, ex = "RULE", e - side * 1.0
    elif kind == "slow":
        hold_h, ex = 13.0, e - side * 1.5
    t = {"symbol": sym, "side": side, "entry_time": entry_t, "entry_price": e, "exit_time": entry_t + int(hold_h * H), "exit_price": ex, "exit_reason": why,
         "leverage": lev, "pnl": pnl, "roe": roe, "stop_initial": e - side * r, "tp_price": None, "mae_price": mae, "mfe_price": mfe}
    t.update(over)
    return t


def win(entry_t=None, roe=0.3):
    return {**loss(entry_t=entry_t), "roe": roe, "pnl": 30.0, "exit_reason": "TP", "exit_price": 104.0}


def views(book, rows, ds=False, lu=None):
    return json.loads(json.dumps(LV.loss_views(book, rows, RT.LU if lu is None else lu, ds), allow_nan=False))


def kind(b, suffix):
    return next(k for k in b["kinds"] if k["suffix"] == suffix)


def types_of(k):
    return {t["id"]: t["n"] for t in k["types"]}


# ---------------------------------------------------------------- the loss types
@pytest.mark.parametrize("name", ["liq", "gave_back", "gave_back_small", "rule_exit", "gap", "slow", "direct"])
@pytest.mark.parametrize("side", [1, -1])
def test_every_type_for_a_long_and_a_short(name, side):
    assert LV.classify(loss(name, side)) == {"gave_back_small": "gave_back_small"}.get(name, name)


def test_the_order_of_the_rules_first_match_wins():
    c = LV.classify
    assert c(loss("liq", mfe_price=110.0)) == "liq"                                      # a forced liquidation beats "earned and lost it"
    assert c(loss("liq", stop_initial=None)) == "liq"                                    # ... and needs no other field
    assert c(loss("gave_back", why="RULE")) == "gave_back"                               # earned >= 1R beats the rule exit
    assert c(loss("gave_back_small", why="RULE")) == "gave_back_small"
    assert c(loss("rule_exit", exit_price=96.0)) == "rule_exit"                          # a rule exit beats "bigger than the stop" ...
    assert c(loss("rule_exit", hold_h=20)) == "rule_exit"                                # ... and "held long"
    assert c(loss("gave_back", exit_price=96.0, hold_h=20)) == "gave_back"
    assert c(loss("gap", hold_h=20)) == "gap"                                            # slippage beats "held long"
    assert c(loss("slow")) == "slow" and c(loss("direct")) == "direct"


def test_the_edges():
    base = dict(stop_initial=90.0)                                                       # R = 10
    assert LV.classify(loss(mfe_price=110.0, **base)) == "gave_back"                      # best = 1.0 exactly
    assert LV.classify(loss(mfe_price=109.9, **base)) == "gave_back_small"
    assert LV.classify(loss(mfe_price=103.0, **base)) == "gave_back_small"                # best = 0.3 exactly
    assert LV.classify(loss(mfe_price=102.9, **base)) == "direct"
    assert LV.classify(loss(hold_h=12.0, mfe_price=100.0, exit_price=98.0)) == "direct"   # exactly 12 h is not "more than 12 h"
    assert LV.classify(loss(hold_h=12.01, mfe_price=100.0, exit_price=98.0)) == "slow"
    assert LV.classify(loss(exit_price=97.6, mfe_price=100.0)) == "gap"                   # end = -1.2R
    assert LV.classify(loss(exit_price=97.8, mfe_price=100.0)) == "direct"                # end = -1.1R
    assert LV.classify(loss(mfe_price=95.0)) == "direct"                                  # a best price below the entry is 0R, never negative


@pytest.mark.parametrize("field", ["entry_price", "exit_price", "stop_initial", "mfe_price", "entry_time", "exit_time", "side"])
def test_a_missing_field_is_unknown_never_a_guess(field):
    for bad in (None, float("nan")):
        t = loss()
        t[field] = bad
        assert LV.classify(t) == "unknown"


def test_zero_risk_is_unknown():
    assert LV.classify(loss(stop_initial=100.0)) == "unknown"


def test_the_definitions_are_exposed_in_the_rule_order():
    b = views({}, [])
    assert [t["id"] for t in b["types"]] == list(LV.TYPE_IDS) and b["types"][0]["id"] == "liq" and b["types"][-1]["id"] == "unknown"
    assert all(t["ko"] and t["explain_ko"] for t in b["types"])
    assert [t["ko"] for t in b["types"][:7]] == ["강제청산", "벌었다가 놓침", "조금 벌었다가 놓침", "규칙 청산으로 잃음", "손절보다 크게 잃음", "오래 끌다 잃음", "처음부터 불리하게 감"]


# ---------------------------------------------------------------- a kind's numbers
def world():
    """fq: A1 (loss gap long ETH 40x, loss on SOL, win, loss), A2 and A3 lose on the SAME signal as A1's first loss; ld: B1 loses on that signal too."""
    sig = T0 + 3 * H                                                                     # 12:00 UTC = 21:00 KST (band 18-24)
    a1 = [loss("gap", 1, sig, sym="ETHUSDT", lev=40, roe=-0.9, pnl=-90.0),
          loss("gave_back", -1, sig + 20 * H, sym="SOLUSDT", lev=50, roe=-0.2, pnl=-20.0),     # +20 h = 09:00 KST next day
          win(sig + 40 * H),
          loss("direct", 1, sig + 60 * H, sym="ETHUSDT", lev=30, roe=-0.4, pnl=-40.0)]
    a2 = [loss("gap", 1, sig, sym="ETHUSDT", lev=40, roe=-0.8, pnl=-80.0), loss("liq", 1, sig + 5 * H, sym="BTCUSDT", lev=50, roe=-1.0, pnl=-100.0)]
    a3 = [loss("direct", 1, sig, sym="ETHUSDT", lev=40, roe=-0.3, pnl=-30.0)]
    b1 = [loss("direct", 1, sig, sym="ETHUSDT", lev=40, roe=-0.5, pnl=-50.0)]
    book = {"p1-fq": a1, "p2-fq": a2, "p3-fq": a3, "p1-ld": b1}
    for v in book.values():
        v.sort(key=lambda t: t["exit_time"])
    rows = [RT.row(a, a.rsplit("-", 1)[1], pick=a.rsplit("-", 1)[0]) for a in book]
    rows[0]["name"], rows[0]["tf"] = "OBV", "1h"
    return book, rows, sig


def test_counts_types_and_the_money():
    book, rows, _ = world()
    b = views(book, rows)
    f = kind(b, "-fq")
    assert (f["accounts"], f["trades"], f["losses"], f["n"]) == (3, 7, 6, 6)
    assert f["loss_share"] == pytest.approx(6 / 7, abs=1e-6)
    assert f["mean_loss_roe"] == pytest.approx((-0.9 - 0.2 - 0.4 - 0.8 - 1.0 - 0.3) / 6, abs=1e-6) and f["worst_loss_roe"] == -1.0
    assert f["loss_money"] == pytest.approx(-360.0)
    assert types_of(f) == {"liq": 1, "gave_back": 1, "gave_back_small": 0, "rule_exit": 0, "gap": 2, "slow": 0, "direct": 2, "unknown": 0}
    assert [t["id"] for t in f["types"]] == list(LV.TYPE_IDS)                              # every type, in the rule order, also with 0
    assert sum(t["share"] for t in f["types"] if t["share"]) == pytest.approx(1.0, abs=1e-5)
    assert next(t for t in f["types"] if t["id"] == "gap")["mean_roe"] == pytest.approx(-0.85)
    assert next(t for t in f["types"] if t["id"] == "slow")["mean_roe"] is None and next(t for t in f["types"] if t["id"] == "slow")["share"] == 0
    assert f["group"] == "main" and f["live"] is True and kind(b, "-ld")["group"] == "control" and kind(b, "-ld")["live"] is False


def test_breakdowns():
    book, rows, sig = world()
    f = kind(views(book, rows), "-fq")
    by = lambda rows_, key: next(r for r in rows_ if r["key"] == key)
    assert [(r["key"], r["n"]) for r in f["by_coin"]] == [("ETH", 4), ("BTC", 1), ("SOL", 1)]
    assert by(f["by_coin"], "ETH")["share"] == pytest.approx(4 / 6, abs=1e-6) and by(f["by_coin"], "ETH")["mean_roe"] == pytest.approx((-0.9 - 0.4 - 0.8 - 0.3) / 4)
    assert [(r["key"], r["n"]) for r in f["by_side"]] == [(1, 5), (-1, 1)] and f["by_side"][0]["label_ko"] == "롱"
    assert [(r["key"], r["n"]) for r in f["by_lev"]] == [(30, 1), (40, 3), (50, 2)] and all(isinstance(r["key"], int) for r in f["by_lev"])
    # the KST hour of each entry, worked out with datetime: 4 at sig, 1 at sig + 5 h, 1 at +20 h, 1 at +60 h (the win at +40 h is not a loss)
    hours = [dt.datetime.fromtimestamp((sig + x) / 1000, KST).hour for x in (0, 0, 0, 5 * H, 20 * H, 60 * H)]
    band = lambda h_: "0-6" if h_ < 6 else "6-12" if h_ < 12 else "12-18" if h_ < 18 else "18-24"
    want = {}
    for h_ in hours:
        want[band(h_)] = want.get(band(h_), 0) + 1
    assert {r["key"]: r["n"] for r in f["by_hour"]} == want and [r["key"] for r in f["by_hour"]] == [k for k in ("0-6", "6-12", "12-18", "18-24") if k in want]
    wk = [dt.datetime.fromtimestamp((sig + x) / 1000, KST).weekday() >= 5 for x in (0, 0, 0, 5 * H, 20 * H, 60 * H)]
    assert {r["key"]: r["n"] for r in f["by_week"]} == {k: v for k, v in (("weekday", wk.count(False)), ("weekend", wk.count(True))) if v}


def test_hour_and_weekday_edges_in_kst():
    # KST = UTC + 9: 14:59:59 UTC -> 23:59:59 KST (band 18-24), 15:00 UTC -> 00:00 KST of the next day (band 0-6)
    d0 = (T0 // DAY) * DAY
    for utc_off, want in ((14 * H + 3_599_000, "18-24"), (15 * H, "0-6"), (20 * H, "0-6"), (21 * H - 1, "0-6"), (21 * H, "6-12"), (3 * H - 1, "6-12"), (3 * H, "12-18")):
        t = loss(entry_t=d0 + utc_off)
        b = views({"p-fq": [t]}, [RT.row("p-fq", "fq")])
        assert [r["key"] for r in kind(b, "-fq")["by_hour"]] == [want], utc_off
    # the day of the week follows the KST date: pick a Friday 16:00 UTC (= Saturday 01:00 KST)
    d = dt.datetime(2026, 10, 9, 16, 0, tzinfo=dt.timezone.utc)                           # a Friday
    assert d.weekday() == 4
    b = views({"p-fq": [loss(entry_t=int(d.timestamp() * 1000))]}, [RT.row("p-fq", "fq")])
    assert [r["key"] for r in kind(b, "-fq")["by_week"]] == ["weekend"]
    b = views({"p-fq": [loss(entry_t=int((d - dt.timedelta(hours=2)).timestamp() * 1000))]}, [RT.row("p-fq", "fq")])   # Friday 23:00 KST
    assert [r["key"] for r in kind(b, "-fq")["by_week"]] == ["weekday"]


def test_streak_by_exit_time_and_clusters_never_mix_kinds():
    book, rows, sig = world()
    b = views(book, rows)
    f, ld = kind(b, "-fq"), kind(b, "-ld")
    # A1 in exit order: loss (sig+2h), loss (+22h), win, loss -> 2; A2: loss, loss -> 2; A3 1.  The tie goes to the smaller id.
    assert f["streak"] == {"max": 2, "account": "p1-fq"} and ld["streak"] == {"max": 1, "account": "p1-ld"}
    # the signal (ETH, long, sig): A1 + A2 + A3 lose on it in the fq kind (3 accounts); the other 4 losses are single signals; B1 is another kind
    assert f["cluster"] == {"signals": 4, "multi": 1, "biggest": 3, "multi_share": pytest.approx(3 / 6, abs=1e-6)}
    assert ld["cluster"] == {"signals": 1, "multi": 0, "biggest": 1, "multi_share": 0.0}
    p = next(k for k in b["kinds"] if k["pooled"])
    assert p["pooled"] is True and p["name_ko"] == "모든 종류 합계" and p["group"] == "all"
    assert p["cluster"] == {"signals": 5, "multi": 1, "biggest": 3, "multi_share": pytest.approx(3 / 7, abs=1e-6)}   # 4 accounts on the signal, but 3 + 1 by kind
    assert (p["accounts"], p["trades"], p["losses"]) == (4, 8, 7) and p["loss_money"] == pytest.approx(-410.0)
    assert p["streak"]["max"] == 2 and p["worst_loss_roe"] == -1.0
    assert {r["key"]: r["n"] for r in p["by_coin"]} == {"ETH": 5, "BTC": 1, "SOL": 1}      # 4 (fq) + 1 (ld) on ETH
    assert types_of(p)["direct"] == types_of(f)["direct"] + types_of(ld)["direct"]


def test_the_ten_biggest_losses_with_a_replay_key():
    trades = [loss(entry_t=T0 + i * 7 * H, roe=-0.05 * (i + 1), pnl=-5.0 * (i + 1), sym=RT.COINS[i % 6]) for i in range(14)]
    book = {"p-fq": trades}
    row = RT.row("p-fq", "fq", pick="pickA")
    row["name"], row["tf"] = "OBV", "4h"
    w = kind(views(book, [row]), "-fq")["worst"]
    assert len(w) == 10 and [x["roe"] for x in w] == [round(-0.05 * i, 6) for i in range(14, 4, -1)]
    first = w[0]
    assert first["account"] == "p-fq" and first["pick"] == "pickA" and first["name"] == "OBV" and first["tf"] == "4h"
    assert first["at"] == first["entry_time"] == trades[13]["entry_time"] and first["exit_time"] == trades[13]["exit_time"]
    assert first["type_id"] == "direct" and first["exit_reason"] == "SL" and first["leverage"] == 30 and first["side"] == 1 and first["symbol"] == trades[13]["symbol"]
    assert set(first) == {"account", "pick", "name", "tf", "symbol", "side", "entry_time", "exit_time", "roe", "type_id", "exit_reason", "leverage", "at"}


def test_small_samples_are_flagged_never_judged():
    few = {"p-fq": [loss(entry_t=T0 + i * 4 * H) for i in range(LV.MIN_LOSSES - 1)]}
    k = kind(views(few, [RT.row("p-fq", "fq")]), "-fq")
    assert k["small"] is True and k["n"] == LV.MIN_LOSSES - 1
    enough = {"p-fq": [loss(entry_t=T0 + i * 4 * H) for i in range(LV.MIN_LOSSES)]}
    assert kind(views(enough, [RT.row("p-fq", "fq")]), "-fq")["small"] is False
    assert "표본 적음" in views(few, [RT.row("p-fq", "fq")])["headline_ko"]


def test_a_win_or_an_unknown_roe_is_not_a_loss_and_breaks_a_streak():
    t = [loss(entry_t=T0 + i * 4 * H) for i in range(5)]
    t[2] = {**t[2], "roe": None}
    k = kind(views({"p-fq": t}, [RT.row("p-fq", "fq")]), "-fq")
    assert (k["trades"], k["losses"], k["streak"]["max"]) == (5, 4, 2)
    z = {**loss(), "roe": 0.0}                                                            # a flat trade is not a loss
    assert kind(views({"p-fq": [z]}, [RT.row("p-fq", "fq")]), "-fq")["losses"] == 0


# ---------------------------------------------------------------- DeepSeek money, empty input, determinism
def test_deepseek_accounts_are_left_out_without_ds_money():
    book = {"core-fq": [loss(roe=-0.1, pnl=-10.0)], "ds-fq": [loss(roe=-0.9, pnl=-900.0), loss(entry_t=T0 + 40 * H, roe=-0.8, pnl=-800.0)]}
    rows = [RT.row("core-fq", "fq"), RT.row("ds-fq", "fq", kind="ds")]
    off = views(book, rows, ds=False)
    f = kind(off, "-fq")
    assert (f["accounts"], f["losses"], f["loss_money"], f["worst_loss_roe"]) == (1, 1, -10.0, -0.1) and off["ds_in_stats"] is False
    assert "-900" not in json.dumps(off) and "ds-fq" not in json.dumps(off)
    assert any("딥시크" in t for t in off["note_ko"])
    on = views(book, rows, ds=True)
    g = kind(on, "-fq")
    assert (g["accounts"], g["losses"], g["loss_money"]) == (2, 3, -1710.0) and on["ds_in_stats"] is True and not any("딥시크" in t for t in on["note_ko"])


def test_a_kind_with_only_hidden_accounts_is_left_out():
    b = views({"ds-fq": [loss()]}, [RT.row("ds-fq", "fq", kind="ds")])
    assert b["kinds"] == [] and "아직" in b["headline_ko"]


def test_empty_input_and_accounts_without_trades():
    assert LV.loss_views({}, [], None)["kinds"] == [] and LV.loss_views(None, None, [])["kinds"] == []
    b = views({"a-fq": [], "a-ld": []}, [RT.row("a-fq", "fq"), RT.row("a-ld", "ld")])
    f = kind(b, "-fq")
    assert (f["trades"], f["losses"], f["loss_share"], f["mean_loss_roe"], f["worst_loss_roe"], f["loss_money"]) == (0, 0, None, None, None, None)
    assert f["worst"] == [] and f["by_coin"] == [] and f["streak"] == {"max": None, "account": None} and f["cluster"]["signals"] == 0 and f["cluster"]["multi_share"] is None
    assert all(t["n"] == 0 and t["share"] is None for t in f["types"]) and f["small"] is True
    assert "아직 진 거래가 없습니다" in b["headline_ko"]
    assert next(k for k in b["kinds"] if k["pooled"])["losses"] == 0                                                  # the pooled group of two empty kinds


def test_odd_input_never_raises_and_json_has_no_nan():
    junk = [{"roe": float("nan")}, {"roe": -0.1}, {"roe": -0.1, "side": "x", "symbol": None, "entry_time": "a", "leverage": float("inf"), "pnl": float("nan")}, {}]
    b = LV.loss_views({"a-fq": junk, "b-fq": None}, [RT.row("a-fq", "fq"), RT.row("b-fq", "fq")], RT.LU)
    json.dumps(b, allow_nan=False)
    f = kind(b, "-fq")
    assert f["losses"] == 2 and types_of(f)["unknown"] == 2


def test_deterministic_and_order_free():
    book, rows, _ = world()
    a = views(book, rows)
    assert a == views(book, rows) and a == views(dict(reversed(list(book.items()))), list(reversed(rows)))


def test_the_sentence_counts_and_does_not_advise():
    book, rows, _ = world()
    s = views(book, rows)["headline_ko"]
    assert s.startswith("빠른 손절") and "6건이 손실" in s and "표본 적음" in s
    for bad in ("해야", "하세요", "추천", "권합니다", "사세요", "팔"):
        assert bad not in s
    assert all(not any(bad in t for bad in ("추천합니다", "하세요")) for t in views(book, rows)["note_ko"])


def test_module_hygiene():
    src = open(os.path.join(ROOT, "candleague", "lossview.py"), encoding="utf-8").read()
    for bad in ("import time", "import random", "sqlite3", "conn.execute", "datetime"):
        assert bad not in src, bad


# ---------------------------------------------------------------- runner.write_snapshots
def test_write_snapshots_carries_the_losses_next_to_the_risk(tmp_path):
    lg = RT.fake_league(tmp_path)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, RT.NOW, ds_money=False)
    saved = json.load(open(tmp_path / "snap" / "league.json"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    assert saved["losses"] == doc["losses"] and "risk" in saved and "losses_error" not in doc
    f = kind(saved["losses"], "-fq")
    # the fake league: 3 trades per account (+20 -60 -30 at 100 -> 99, stop 98, best 101): 2 losses; the DeepSeek pick is left out
    assert (f["accounts"], f["trades"], f["losses"]) == (1, 3, 2) and types_of(f)["gave_back_small"] == 2
    assert "ds-F5" not in json.dumps(saved["losses"])
    on = RN.write_snapshots(str(tmp_path / "snap2"), lg, RT.NOW, ds_money=True)["losses"]
    assert kind(on, "-fq")["accounts"] == 2 and kind(on, "-fq")["losses"] == 4


def test_a_failing_block_never_stops_the_snapshot_and_other_leagues_have_none(tmp_path, monkeypatch):
    lg = RT.fake_league(tmp_path)

    def boom(*a, **k):
        raise ValueError("kaputt")
    monkeypatch.setattr(LV, "loss_views", boom)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, RT.NOW, ds_money=False)
    assert "losses" not in doc and doc["losses_error"] == "ValueError: kaputt"
    assert "risk" in doc and "decision" in doc and os.path.exists(tmp_path / "snap" / "league.json")
    monkeypatch.undo()
    lg2 = RT.fake_league(tmp_path, owner=False, name="b.db")
    d2 = RN.write_snapshots(str(tmp_path / "snap3"), lg2, RT.NOW, ds_money=True)
    assert "losses" not in d2 and "losses_error" not in d2
