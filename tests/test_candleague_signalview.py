"""candleague 신호, server side: candleague/signalview.py (league.json key ``signals``) written by runner.write_snapshots.

Hand-made closed trades (entry time, side, symbol) and open positions (since, side, symbol): the last entry per coin and kind, whether it is
still open, the entries today (UTC) and in the last 24 hours (both edges), the accounts that entered at the same moment, the newest entry of any
kind per coin, DeepSeek money both ways, JSON without NaN, deterministic, the module's hygiene, and runner.write_snapshots carrying the key."""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_riskview as RT  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague import signalview as SV  # noqa: E402

DAY, H, T0, LU = RT.DAY, RT.H, RT.T0, RT.LU
NOW = T0 + 10 * H                                   # 10:00 UTC on the day T0 starts


def tr(side, entry, sym="BTCUSDT"):
    return {"symbol": sym, "side": side, "entry_time": entry, "exit_time": entry + H, "pnl": 1.0, "roe": 0.01, "leverage": 20, "exit_reason": "SL"}


def op(sym, side, since):
    return {"symbol": sym, "side": side, "entry": 100.0, "stop": 99.0, "tp": None, "since": since, "lev": 20}


def kind(out, sfx):
    return next(k for k in out["kinds"] if k["suffix"] == sfx)


def cell(out, sfx, coin):
    return next(c for c in kind(out, sfx)["coins"] if c["coin"] == coin)


def world():
    rows = [RT.row("a-fq", "fq", opened=op("ETHUSDT", -1, NOW - 2 * H)), RT.row("b-fq", "fq"), RT.row("a-ld", "ld"), RT.row("a-fqc", "fqc"), RT.row("a-ldc", "ldc")]
    book = {"a-fq": [tr(1, NOW - 30 * H), tr(1, NOW - 5 * H), tr(-1, T0 - 1)],              # BTC: the newest at -5h; T0 - 1 is the day before
            "b-fq": [tr(1, NOW - 5 * H), tr(1, NOW - 3 * H, "SOLUSDT")],                      # b also entered BTC at -5h: n_at 2
            "a-ld": [tr(-1, NOW - 25 * H, "DOGEUSDT"), tr(1, NOW - 24 * H, "DOGEUSDT"), tr(1, T0, "LTCUSDT")],
            "a-fqc": [], "a-ldc": [tr(1, NOW - 9 * H, "BCHUSDT")]}
    return book, rows


def test_last_entry_per_coin_and_kind():
    book, rows = world()
    out = SV.signal_views(book, rows, LU, NOW)
    assert out["coins"] == ["BTC", "ETH", "SOL", "DOGE", "LTC", "BCH"] and out["ref_ms"] == NOW and out["day_start_ms"] == T0
    btc = cell(out, "-fq", "BTC")
    assert (btc["ms"], btc["age_ms"], btc["side"], btc["n_at"], btc["open"], btc["open_n"]) == (NOW - 5 * H, 5 * H, 1, 2, False, 0)
    eth = cell(out, "-fq", "ETH")                                           # the open short entered 2 hours ago
    assert (eth["ms"], eth["side"], eth["open"], eth["open_n"], eth["n_at"]) == (NOW - 2 * H, -1, True, 1, 1) and eth["pick"] == "a"
    sol = cell(out, "-fq", "SOL")
    assert sol["ms"] == NOW - 3 * H and sol["pick"] == "b" and sol["open"] is False
    never = cell(out, "-fq", "DOGE")
    assert never["ms"] is None and never["age_ms"] is None and never["side"] is None and never["open"] is None and never["h24"] == 0
    assert cell(out, "-ld", "DOGE")["side"] == 1 and cell(out, "-ld", "DOGE")["ms"] == NOW - 24 * H       # the newest of two on DOGE
    assert cell(out, "-fqc", "BTC")["ms"] is None and kind(out, "-fqc")["total"] == 0


def test_counts_today_and_24h_with_both_edges():
    book, rows = world()
    out = SV.signal_views(book, rows, LU, NOW)
    fq = kind(out, "-fq")
    # fq entries: a: -30h, -5h, T0-1 (yesterday), the open ETH at -2h; b: -5h, -3h  -> 6 in all
    assert fq["total"] == 6 and fq["open_n"] == 1 and fq["accounts"] == 2
    assert fq["today"] == 4 and fq["h24"] == 5       # today: -5h, -5h, -3h, -2h; the last 24h also holds T0 - 1 ms (yesterday 23:59), not the -30h one
    ld = kind(out, "-ld")
    assert ld["total"] == 3 and ld["today"] == 1                              # only T0 itself is today: the day starts AT 00:00 UTC (inclusive)
    assert ld["h24"] == 1 and cell(out, "-ld", "DOGE")["h24"] == 0            # NOW - 24h is outside the last 24 hours (exclusive), NOW - 25h too; T0 (LTC) is inside
    assert cell(out, "-ld", "LTC")["h24"] == 1
    # an entry in the future of the snapshot's time is not counted
    book["a-ld"].append(tr(1, NOW + H))
    assert kind(SV.signal_views(book, rows, LU, NOW), "-ld")["today"] == 1


def test_the_newest_entry_of_any_kind_per_coin():
    book, rows = world()
    last = {x["coin"]: x for x in SV.signal_views(book, rows, LU, NOW)["last"]}
    assert (last["BTC"]["suffix"], last["BTC"]["name_ko"], last["BTC"]["ms"]) == ("-fq", "빠른 손절", NOW - 5 * H)
    assert last["ETH"]["open"] is True and last["ETH"]["open_n"] == 1 and last["BCH"]["suffix"] == "-ldc" and last["BCH"]["side"] == 1
    assert last["DOGE"]["suffix"] == "-ld" and last["LTC"]["suffix"] == "-ld"
    book2 = {"a-ld": [tr(1, NOW - H)], "a-fq": [tr(-1, NOW - H)]}                # a tie: the kind order decides (실전 후보 first)
    rows2 = [RT.row("a-fq", "fq"), RT.row("a-ld", "ld")]
    assert next(x for x in SV.signal_views(book2, rows2, LU, NOW)["last"] if x["coin"] == "BTC")["suffix"] == "-fq"


def test_deepseek_money_both_ways_and_odd_input():
    book, rows = world()
    rows.append(RT.row("d-fq", "fq", kind="ds", opened=op("BTCUSDT", 1, NOW - H)))
    book["d-fq"] = [tr(1, NOW - H)]
    assert cell(SV.signal_views(book, rows, LU, NOW, False), "-fq", "BTC")["ms"] == NOW - 5 * H
    on = SV.signal_views(book, rows, LU, NOW, True)
    assert cell(on, "-fq", "BTC")["ms"] == NOW - H and kind(on, "-fq")["accounts"] == 3 and on["ds_in_stats"] is True
    assert "딥시크 계좌는 금액 숨김" in " ".join(SV.signal_views(book, rows, LU, NOW)["note_ko"])
    weird = {"a-fq": [{"symbol": None, "side": 1, "entry_time": 1}, {"symbol": "BTCUSDT", "side": 0, "entry_time": 5}, {"symbol": "BTCUSDT", "side": 1, "entry_time": None}, "x"]}
    w = SV.signal_views({"a-fq": [t for t in weird["a-fq"] if isinstance(t, dict)]}, [RT.row("a-fq", "fq", opened={"symbol": "BTCUSDT", "side": 1})], LU, NOW)
    assert kind(w, "-fq")["total"] == 0 and kind(w, "-fq")["open_n"] == 1                # an open position without a start time is not an entry we can date
    assert SV.signal_views(None, None, None)["kinds"] == [] and SV.signal_views({}, [], LU, NOW)["headline_ko"] == "아직 보여 줄 계좌 종류가 없습니다"


def test_json_deterministic_headline_and_hygiene():
    book, rows = world()
    a = SV.signal_views(book, rows, LU, NOW)
    assert json.dumps(a, allow_nan=False) == json.dumps(SV.signal_views(book, list(reversed(rows)), LU, NOW), allow_nan=False)
    assert a["headline_ko"].startswith("빠른 손절: 오늘(UTC) 진입 4건, 최근 24시간 5건, 지금 열린 포지션 1개")
    text = " ".join(SV.signal_rules_ko() + SV.signal_notes_ko(False)) + a["headline_ko"]
    assert "진입" in text and "전략의 조건" in text and not any(w in text for w in ("사세요", "파세요", "추천", "권합니다"))
    src = open(os.path.join(ROOT, "candleague", "signalview.py"), encoding="utf-8").read()
    assert "5,000" not in src and "5000" not in src and "binance.com" not in src


def test_write_snapshots_carries_the_signals(tmp_path):
    lg = RT.fake_league(tmp_path)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, RT.NOW, ds_money=False)
    saved = json.load(open(tmp_path / "snap" / "league.json"))
    assert saved["signals"] == doc["signals"] and "signals_error" not in doc and doc["signals"]["ref_ms"] == RT.NOW
    fq = kind(doc["signals"], "-fq")
    assert fq["total"] == 4 and fq["open_n"] == 1 and cell(doc["signals"], "-fq", "BTC")["open"] is True       # 3 closed + the open one; the DeepSeek pick is left out
