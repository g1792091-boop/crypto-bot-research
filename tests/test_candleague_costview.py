"""candleague 실제 비용, server side: candleague/costview.py (league.json key ``costs``) written by runner.write_snapshots next to ``risk``.

Hand-made trades with their entry / exit price, leverage, P&L and ROE; every number is checked by hand: the fees + funding the prices show, the
slippage the rules add (0.04% of notional), the round trip 0.14% x leverage, the share of the gross P&L, the cost per trade against the net ROE.
Also: LIQ trades left out, what cannot be derived is None, DeepSeek money both ways, the kinds shown, JSON without NaN, the module's hygiene,
and runner.write_snapshots carrying the key."""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_riskview as RT  # noqa: E402  (its hand-made world)
from candleague import costview as CV  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague import summary as SM  # noqa: E402

LU = RT.LU


def ct(side=1, entry=100.0, exit_=101.0, lev=20, margin=100.0, roe=0.19, why="SL", pnl=None):
    """A closed trade: margin 100, a 1% move at 20x = 20% before costs; ROE 0.19 means fees + funding took 1% of the margin ($1.00)."""
    return {"symbol": "BTCUSDT", "side": side, "entry_time": RT.T0, "exit_time": RT.T0 + RT.H, "entry_price": entry, "exit_price": exit_, "exit_reason": why,
            "leverage": lev, "pnl": margin * roe if pnl is None else pnl, "roe": roe}


def rows_for(roles=("fq", "ld", "ldc", "fqc"), kind="core", n=1):
    return [RT.row(f"p{i}-{r}", r, kind=kind) for r in roles for i in range(n)]


def kind(out, sfx):
    return next(k for k in out["kinds"] if k["suffix"] == sfx)


def test_one_trade_by_hand():
    book = {"p0-fq": [ct()]}
    out = CV.cost_views(book, rows_for(("fq",)), LU, 1000.0)
    k = kind(out, "-fq")
    # fees + funding $1.00 (0.20 - 0.19 of margin 100); slippage 0.04% of the 2,000 notional = $0.80
    assert (k["trades"], k["cost_n"], k["liq"], k["lev_n"]) == (1, 1, 0, 1)
    assert k["fee_funding"] == 1.0 and k["slip"] == 0.8 and k["cost"] == 1.8 and k["per_trade"] == 1.8
    assert k["net"] == 19.0 and k["gross"] == 20.8 and k["share"] == pytest.approx(1.8 / 20.8, abs=1e-6)
    assert k["rt_roe"] == pytest.approx(0.0014 * 20, abs=1e-9)                # the rule: 0.14% x leverage of the margin
    assert k["cost_roe"] == pytest.approx(0.01 + 0.0004 * 20, abs=1e-6) and k["net_roe"] == 0.19
    assert k["ratio"] == pytest.approx(0.018 / 0.19, abs=1e-5)
    assert k["live"] is True and k["name_ko"] == "빠른 손절" and k["pooled"] is False and len(out["kinds"]) == 1       # one kind: no pooled row


def test_a_short_and_a_loss_and_the_summary_cost_of_agree():
    t1, t2 = ct(side=-1, entry=100.0, exit_=99.0, lev=10, roe=0.095), ct(entry=100.0, exit_=98.0, lev=10, roe=-0.205)
    for t in (t1, t2):                                                       # per trade the same fees + funding as summary.cost_of
        k = CV.cost_views({"p0-fq": [t]}, rows_for(("fq",)), LU, 1000.0)["kinds"][0]
        assert k["fee_funding"] == pytest.approx(SM.cost_of(t), abs=0.01)
    k = CV.cost_views({"p0-fq": [t1, t2]}, rows_for(("fq",)), LU, 1000.0)["kinds"][0]
    # costs: short 0.10 - 0.095 = 0.005 -> $0.5; long -0.20 - (-0.205) = 0.005 -> $0.5; slippage 0.0004 x 1,000 each = $0.4 each
    assert k["fee_funding"] == 1.0 and k["slip"] == 0.8 and k["cost"] == 1.8 and k["net"] == pytest.approx(9.5 - 20.5)
    assert k["gross"] == pytest.approx(-11.0 + 1.8) and k["share"] is None      # gross <= 0: no share (the screen says 확인 못 함)
    assert k["net_roe"] == pytest.approx((0.095 - 0.205) / 2) and k["ratio"] is None                 # net ROE <= 0: no ratio


def test_what_cannot_be_derived_is_none_never_a_guess():
    bad = [ct(roe=0.0, pnl=0.0), {**ct(), "leverage": None}, {**ct(), "exit_price": None}, ct(why="LIQ", roe=-1.0, pnl=-100.0)]
    k = CV.cost_views({"p0-fq": bad}, rows_for(("fq",)), LU, 1000.0)["kinds"][0]
    assert k["trades"] == 4 and k["cost_n"] == 0 and k["liq"] == 1 and k["lev_n"] == 3          # LIQ (leverage known) counts, the rest is not derivable
    for key in ("fee_funding", "slip", "cost", "per_trade", "net", "gross", "share", "cost_roe", "net_roe", "ratio"):
        assert k[key] is None, key
    assert k["rt_roe"] == pytest.approx(0.028)                                  # the rule needs the leverage only
    empty = CV.cost_views({}, rows_for(("fq",)), LU, 1000.0)["kinds"][0]
    assert empty["trades"] == 0 and empty["rt_roe"] is None and empty["cost"] is None and "아직 없습니다" in CV.cost_views({}, rows_for(("fq",)), LU)["headline_ko"]


def test_kinds_order_and_the_pooled_sum():
    book = {f"p0-{r}": [ct(), ct(lev=40, roe=0.38, margin=50.0, exit_=101.0)] for r in ("fq", "ld", "ldc", "fqc")}
    out = CV.cost_views(book, rows_for() + rows_for(("nv",)), LU, 1000.0)
    assert [k["suffix"] for k in out["kinds"]] == ["-fq", "-ld", "-ldc", "-fqc", None]       # only the four; 자체 판단 (-nv) is not shown
    pooled = out["kinds"][-1]
    assert pooled["pooled"] is True and pooled["name_ko"] == CV.POOLED_KO and pooled["accounts"] == 4 and pooled["trades"] == 8 and pooled["cost_n"] == 8
    assert pooled["cost"] == pytest.approx(sum(k["cost"] for k in out["kinds"][:-1]), abs=0.02)
    assert pooled["rt_roe"] == pytest.approx(0.0014 * 30)                                      # leverage mean of 20 and 40
    assert out["assumptions"] == {"fee": 0.0005, "slip": 0.0002, "round_trip": pytest.approx(0.0014)}
    only = CV.cost_views(book, rows_for(("ld", "fqc")), LU, 1000.0)
    assert [k["suffix"] for k in only["kinds"]] == ["-ld", "-fqc", None] and not any(k["live"] for k in only["kinds"])


def test_deepseek_money_both_ways():
    book = {"p0-fq": [ct()], "d0-fq": [ct(margin=1000.0, pnl=190.0)]}
    rows = rows_for(("fq",)) + [RT.row("d0-fq", "fq", kind="ds")]
    off = kind(CV.cost_views(book, rows, LU, 1000.0, ds_money=False), "-fq")
    on = kind(CV.cost_views(book, rows, LU, 1000.0, ds_money=True), "-fq")
    assert off["accounts"] == 1 and off["trades"] == 1 and off["cost"] == 1.8 and on["accounts"] == 2 and on["trades"] == 2 and on["cost"] > 10
    assert CV.cost_views(book, rows, LU, 1000.0, False)["ds_in_stats"] is False and "딥시크 계좌는 금액 숨김" in " ".join(CV.cost_views(book, rows, LU)["note_ko"])
    assert "딥시크" not in " ".join(CV.cost_views(book, rows, LU, 1000.0, True)["note_ko"])


def test_json_deterministic_wallet_and_hygiene():
    book = {"p0-fq": [ct(), ct(side=-1, exit_=99.0, roe=0.19)], "p0-ld": [ct(lev=30, roe=0.28)]}
    a = CV.cost_views(book, rows_for(("fq", "ld")), LU, 1000.0)
    assert json.dumps(a, allow_nan=False) == json.dumps(CV.cost_views(book, list(reversed(rows_for(("fq", "ld")))), LU, 1000.0), allow_nan=False)
    assert a["equity0"] == 1000.0 and "$1,000" in " ".join(a["note_ko"]) and "5,000" not in json.dumps(a, ensure_ascii=False)
    assert CV.cost_views(book, rows_for(("fq",)), LU, 2500.0)["equity0"] == 2500.0 and "$2,500" in " ".join(CV.cost_views(book, [], LU, 2500.0)["note_ko"])
    assert CV.cost_views(None, None, None)["kinds"] == [] and CV.cost_views({}, [], LU)["headline_ko"] == "아직 보여 줄 계좌 종류가 없습니다"
    from paperbot.config import Settings
    s = Settings()
    assert (CV.TAKER_FEE, CV.SLIPPAGE) == (s.taker_fee, s.slippage_frac) and CV.ROUND_TRIP == pytest.approx(s.round_trip_cost)
    text = " ".join(CV.cost_rules_ko() + CV.cost_notes_ko(1000.0, False)) + a["headline_ko"]
    assert "추정" in text and not any(w in text for w in ("사세요", "파세요", "추천", "권합니다"))
    src = open(os.path.join(ROOT, "candleague", "costview.py"), encoding="utf-8").read()
    assert "5,000" not in src and "5000" not in src and "binance.com" not in src


def test_write_snapshots_carries_the_costs(tmp_path):
    lg = RT.fake_league(tmp_path)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, RT.NOW, ds_money=False)
    saved = json.load(open(tmp_path / "snap" / "league.json"))
    assert saved["costs"] == doc["costs"] and "costs_error" not in doc and doc["costs"]["equity0"] == RN.EQUITY
    k = kind(doc["costs"], "-fq")
    assert k["accounts"] == 1 and k["trades"] == 3 and k["cost_n"] == 3                 # the fake trades are all derivable; the DeepSeek pick is left out
