"""candleague 코인별, server side: candleague/coinview.py (league.json key ``coins``) written by runner.write_snapshots (via screens3.add_blocks).

Hand-made rows and closed trades; every number is checked by hand or against a plain-Python reference: per coin and kind the trades, wins, win rate,
mean ROE, long / short, P&L and its share of the kind (only when the kind's total is above zero), the difference to the coin twin in the SAME coin
(means pooled over the picks, n < 30 on either side marks it ``few``), the kinds shown and their order, DeepSeek money both ways (nothing leaks), JSON
without NaN, deterministic, the sentence and limits, hygiene, and the snapshot hook (key only in a league with a lineup; a failure never stops it)."""

from __future__ import annotations

import json
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_riskview as RT  # noqa: E402
from candleague import coinview as CV  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague import rulex as RX  # noqa: E402

T0, H, LU = RT.T0, RT.H, RT.LU


def t(sym, side, pnl, i=0):
    d = RT.tr(side, T0 + i * H, T0 + i * H + H // 2, pnl, sym)
    d["roe"] = pnl / 100.0
    return d


def world(n_fq=40, n_fqc=35):
    """fq: n_fq BTC trades (win +10 / loss -5), 5 ETH; fqc: n_fqc BTC trades with +2 each, 3 ETH; a DeepSeek fq account with a huge BTC win."""
    rows = [RT.row("a-fq", "fq"), RT.row("b-fq", "fq"), RT.row("a-fqc", "fqc"), RT.row("a-ld", "ld"), RT.row("a-ldc", "ldc"),
            RT.row("ds-fq", "fq", kind="ds", wallet=None)]
    book = {"a-fq": [t("BTCUSDT", 1 if i % 2 else -1, 10.0 if i % 4 else -5.0, i) for i in range(n_fq)] + [t("ETHUSDT", 1, 4.0, 90 + i) for i in range(5)],
            "b-fq": [], "a-fqc": [t("BTCUSDT", 1, 2.0, i) for i in range(n_fqc)] + [t("ETHUSDT", -1, -1.0, 90 + i) for i in range(3)],
            "a-ld": [t("SOLUSDT", 1, 3.0, i) for i in range(4)], "a-ldc": [], "ds-fq": [t("BTCUSDT", 1, 9999.0)]}
    return rows, book


def kind(out, sfx):
    return next(k for k in out["kinds"] if k["suffix"] == sfx)


def row(k, coin):
    return next(r for r in k["rows"] if r["coin"] == coin)


def test_per_coin_numbers_and_the_twin_difference_by_hand():
    rows, book = world()
    out = CV.coin_views(book, rows, LU, 1000.0, False)
    assert [k["suffix"] for k in out["kinds"]] == ["-fq", "-fqc", "-ld", "-ldc"]                      # -ldc has an account but no trade: still a kind
    assert out["min_n"] == 30 and out["equity0"] == 1000.0 and out["ds_in_stats"] is False
    fq = kind(out, "-fq")
    btc = row(fq, "BTC")
    wins = sum(1 for i in range(40) if i % 4)
    pnl = sum(10.0 if i % 4 else -5.0 for i in range(40))
    assert btc["n"] == 40 and btc["wins"] == wins and btc["win_rate"] == pytest.approx(wins / 40)
    assert btc["pnl"] == pytest.approx(pnl) and btc["mean_roe"] == pytest.approx(pnl / 100.0 / 40, abs=1e-6)
    assert btc["long"] + btc["short"] == 40 and btc["long"] == 20 and btc["few"] is False
    eth = row(fq, "ETH")
    assert eth["n"] == 5 and eth["few"] is True and eth["win_rate"] == 1.0 and eth["long"] == 5 and eth["short"] == 0
    total = pnl + 20.0
    assert fq["total"]["n"] == 45 and fq["total"]["pnl"] == pytest.approx(total) and btc["share"] == pytest.approx(pnl / total, abs=1e-6)
    assert eth["share"] == pytest.approx(20.0 / total, abs=1e-6)
    # the twin, same coin: 35 BTC trades at +2% each; the difference is a plain subtraction of the two means
    assert btc["twin"]["n"] == 35 and btc["twin"]["few"] is False and btc["twin"]["mean_roe"] == pytest.approx(0.02)
    assert btc["diff"] == pytest.approx(btc["mean_roe"] - 0.02, abs=1e-6) and btc["diff_few"] is False
    assert eth["twin"]["n"] == 3 and eth["diff_few"] is True and eth["diff"] == pytest.approx(0.04 - (-0.01), abs=1e-6)
    # the twin kind itself has no twin of its own; a coin without a trade is a row with n = 0 and None numbers (never 0)
    fqc = kind(out, "-fqc")
    assert fqc["twin"] is None and fqc["is_twin"] is True and row(fqc, "BTC")["diff"] is None
    z = row(fq, "SOL")
    assert z["n"] == 0 and z["mean_roe"] is None and z["win_rate"] is None and z["share"] is None and z["pnl"] is None and z["diff"] is None
    # -ld: 4 SOL trades, the twin -ldc has no trade at all in the coin: the twin block says n = 0 and no difference
    ld = kind(out, "-ld")
    assert row(ld, "SOL")["n"] == 4 and row(ld, "SOL")["twin"] == {"n": 0, "mean_roe": None, "few": True} and row(ld, "SOL")["diff"] is None
    assert out["coins"][0] == "BTC"                                                                     # most closed trades of the two real kinds first


def test_share_only_when_the_kind_total_is_above_zero():
    rows = [RT.row("a-fq", "fq")]
    book = {"a-fq": [t("BTCUSDT", 1, -10.0, 0), t("ETHUSDT", 1, 4.0, 1)]}
    k = kind(CV.coin_views(book, rows, LU, 1000.0), "-fq")
    assert all(r["share"] is None for r in k["rows"]) and k["total"]["pnl"] == -6.0


def test_deepseek_money_both_ways():
    rows, book = world()
    off = CV.coin_views(book, rows, LU, 1000.0, False)
    on = CV.coin_views(book, rows, LU, 1000.0, True)
    assert "9999" not in json.dumps(off) and kind(off, "-fq")["accounts"] == 2 and row(kind(off, "-fq"), "BTC")["n"] == 40
    assert kind(on, "-fq")["accounts"] == 3 and row(kind(on, "-fq"), "BTC")["n"] == 41 and on["ds_in_stats"] is True
    assert any("딥시크" in n for n in off["note_ko"]) and not any("딥시크" in n for n in on["note_ko"])


def test_odd_input_json_deterministic_and_the_sentence():
    rows, book = world()
    book["a-fq"].append({"symbol": "BTCUSDT", "side": 1, "pnl": float("nan"), "roe": 1.0})
    book["a-fq"].append({"symbol": None, "side": 1, "pnl": 1.0, "roe": 1.0})
    a = CV.coin_views(book, rows, LU, 1000.0, False)
    json.dumps(a, allow_nan=False)
    assert kind(a, "-fq")["skipped"] == 2 and row(kind(a, "-fq"), "BTC")["n"] == 40
    assert a["equity0"] == 1000.0 and CV.coin_views({}, rows, LU)["equity0"] > 0
    b = CV.coin_views(dict(reversed(list(book.items()))), list(reversed(rows)), LU, 1000.0, False)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    h = a["headline_ko"]
    assert "빠른 손절" in h and "동전 짝보다 높음" in h and "1개" in h                                      # BTC only is >= 30 on both sides
    assert not any(w in h + " ".join(a["rules_ko"] + a["note_ko"]) for w in ("추천", "사세요", "하세요 ", "5,000"))
    assert CV.coin_views({}, [], LU)["kinds"] == [] and CV.coin_views({}, rows, None)["kinds"] == []


def test_module_hygiene():
    src = open(os.path.join(ROOT, "candleague", "coinview.py"), encoding="utf-8").read()
    for bad in ("import time", "import random", "import datetime", "time.time", "os.environ", "open(", "5000", "5,000", "import sqlite3", "bootstrap"):
        assert bad not in src, bad


def test_write_snapshots_carries_coins_only_with_a_lineup_and_a_failure_never_stops_it(tmp_path, monkeypatch):
    lg = RT.fake_league(tmp_path)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, RT.NOW, ds_money=False)
    saved = json.load(open(tmp_path / "snap" / "league.json"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    assert saved["coins"] == doc["coins"] and "coins_error" not in doc and [k["suffix"] for k in doc["coins"]["kinds"]] == ["-fq", "-ld"]
    assert row(kind(doc["coins"], "-fq"), "BTC")["n"] == 3 and "decision" in saved
    on = RN.write_snapshots(str(tmp_path / "snap2"), lg, RT.NOW, ds_money=True)["coins"]
    assert row(kind(on, "-fq"), "BTC")["n"] == 6
    lg2 = RT.fake_league(tmp_path, owner=False, name="b.db")
    assert RX.lineup(lg2.accts) is None
    d2 = RN.write_snapshots(str(tmp_path / "snap3"), lg2, RT.NOW, ds_money=True)
    assert "coins" not in d2 and "coins_error" not in d2
    lg3 = RT.fake_league(tmp_path, name="c.db")
    monkeypatch.setattr(CV, "coin_views", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    d3 = RN.write_snapshots(str(tmp_path / "snap4"), lg3, RT.NOW, ds_money=True)
    assert "coins" not in d3 and d3["coins_error"] == "ValueError: boom" and "decision" in d3 and "timeline" in d3 and "dataq" in d3
    assert d3["dataq"]["status"] == "check" and any(e["key"] == "coins_error" for e in d3["dataq"]["errors"])     # the data check sees it
