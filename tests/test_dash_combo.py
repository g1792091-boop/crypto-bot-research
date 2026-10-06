"""조합 성과 (#/combo; paperbot/dash/more/combo.py + combo_calc.py, screens/combo*.js): hand-computed combinations on a
hand-made paper3.db (equal and custom weights, the coin-flip baseline matched per timeframe, leave-one-out, the
closed-trade fallback), the pure numbers (drawdown, recovery, time under water, daily ratios gated by days, trade
numbers, inverse-volatility and equal-risk weights, correlation floors), the merged rules on a hand-made signal log
(B's skipped-while-busy signals count, A's skipped signals are only counted), the early-days words, DeepSeek kept out
(no unit, no id in any answer, a 400 with the reason), the endpoints through the app (read-only, background + cache),
and the page wiring (route, rail icon, 찾기, the optional 5-year module, 조합 시너지 rows as links, the two 최대 낙폭
labels)."""
import json
import os
import re
import sqlite3
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from combo_world import blank, build, equity, signal, trade  # noqa: E402

from paperbot.dash.more import combo as CB  # noqa: E402
from paperbot.dash.more import combo_calc as K  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
H, M, DAY = 3_600_000, 60_000, 86_400_000
A, B = "S1_EMA_RSI_CHOP@1h", "S2_ST_ROC@1h"
A4 = "S1_EMA_RSI_CHOP@4h"
F1, F2 = "RANDOM_1@1h", "RANDOM_2@1h"
DS = "F1_RSI_DIV@1h"


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return fh.read()


class _Data:
    """What Combo needs of dash.app.Data: a read-only connection (and a board for the picker)."""

    def __init__(self, db):
        self.db = db

    def conn(self):
        c = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c

    def board(self):
        from paperbot.dash.app import Data
        return Data(self.db).board()


def make_db(path, start):
    """Two strategy accounts on 1h (A, B), A's 4h account, two 1h coin flips and one DeepSeek account. Samples at
    start + 1..4 h; five closed trades (A: +100, -200, +300; B: +100, -150); a hand-made signal log."""
    st = blank(path, start, [(A, "strategy"), (B, "strategy"), (A4, "strategy"), (F1, "random"), (F2, "random"),
                             (DS, "ds200")])
    t = [start + k * H for k in range(1, 5)]
    for aid, vals in ((A, (5100, 4900, 5050, 5200)), (B, (4950, 5050, 5000, 4900)), (A4, (5000, 5000, 5000, 5000)),
                      (F1, (5000, 5100, 5100, 5100)), (F2, (4900, 4900, 4950, 5000)), (DS, (9000, 9100, 9200, 9300))):
        equity(st, aid, zip(t, vals))
    trade(st, A, start + 10 * M, t[0], 100.0, symbol="BTCUSDT", side=1)
    trade(st, A, t[0] + 10 * M, t[1], -200.0, symbol="ETHUSDT", side=-1, wallet=5100)
    trade(st, B, start + 20 * M, t[1], 100.0)
    trade(st, A, t[2], t[3], 300.0, symbol="BTCUSDT", side=1, wallet=4900)
    trade(st, B, t[2], t[3], -150.0, wallet=5100)
    trade(st, DS, start + 5 * M, t[2], 4000.0)                       # DeepSeek money: must never show here
    st.commit()
    return st, t


@pytest.fixture
def world(tmp_path):
    start = (int(time.time() * 1000) - 10 * H) // 300_000 * 300_000
    db = str(tmp_path / "paper3.db")
    st, t = make_db(db, start)
    st.close()
    c = CB.Combo(_Data(db))
    return c, start, t, db


# ---------------------------------------------------------------- the pure numbers
def test_curve_numbers_by_hand():
    t = [0, DAY, 2 * DAY, 3 * DAY, 4 * DAY]
    n = K.curve_numbers(t, [100, 110, 99, 105, 121], 100)
    assert n["ret"] == pytest.approx(0.21) and n["pnl"] == pytest.approx(21)
    assert n["mdd_pct"] == pytest.approx(11 / 110, abs=1e-6) and n["mdd_usd"] == pytest.approx(11)
    assert n["mdd_peak_ts"] == DAY and n["mdd_trough_ts"] == 2 * DAY
    assert n["recovered"] is True and n["recovery_days"] == pytest.approx(2.0)      # 99 at day 2 -> 121 at day 4
    assert n["under_water_share"] == pytest.approx(0.5)                              # days 2-3 and 3-4 of four
    assert n["longest_under_water_days"] == pytest.approx(3.0)                      # from the day-1 peak to day 4
    fall = K.curve_numbers([0, DAY, 2 * DAY], [100, 90, 80], 100)
    assert fall["mdd_pct"] == pytest.approx(0.2) and fall["mdd_peak_ts"] == 0 and fall["recovered"] is False
    assert fall["recovery_days"] is None
    flat = K.curve_numbers([0, DAY], [100, 100], 100)
    assert flat["mdd_pct"] == 0.0 and flat["recovered"] is None and flat["under_water_share"] == 0.0


def test_daily_numbers_and_the_five_day_gate():
    d = {"days": ["d1", "d2", "d3", "d4", "d5"], "pnl": [10, -5, 20, -10, 5], "ret": [0.01, -0.005, 0.02, -0.01, 0.005],
         "partial_last": False}
    n = K.daily_numbers(d, 0.02, 0.01)
    r = np.array(d["ret"])
    assert n["worst_day"] == {"day": "d4", "pnl": -10, "ret": -0.01} and n["win_days_n"] == 3 and n["win_days"] == 0.6
    assert n["daily_vol"] == pytest.approx(r.std(ddof=1), abs=1e-6)
    assert n["sharpe_like"] == pytest.approx(r.mean() / r.std(ddof=1), abs=1e-4)                # daily, not annualised
    assert n["sortino_like"] == pytest.approx(r.mean() / np.sqrt(np.mean(np.minimum(r, 0) ** 2)), abs=1e-4)
    assert n["calmar_like"] == pytest.approx(2.0)
    short = K.daily_numbers({**d, "days": d["days"][:2], "pnl": d["pnl"][:2], "ret": d["ret"][:2]}, 0.02, 0.01)
    assert short["sharpe_like"] is None and short["sortino_like"] is None and short["daily_vol"] is None
    assert short["calmar_like"] is None and short["ratio_min_days"] == 5 and short["worst_day"]["pnl"] == -5


def test_day_ends_cut_at_korea_midnight():
    start = K.kst_midnight_after(0) - 2 * H            # 22:00 KST
    t = [start, start + H, start + 3 * H, start + 5 * H]
    d = K.day_ends(t, [100, 110, 90, 95], start, start + 5 * H, 100)
    assert len(d["days"]) == 2 and d["partial_last"] is True
    assert d["pnl"] == pytest.approx([10, -15])        # 22:00-00:00 ends at 110, then 95 by 03:00 (still going)


def test_trade_numbers_by_hand():
    n = K.trade_numbers([10, -5, 20, -5, -5])
    assert n["trades"] == 5 and n["wins"] == 2 and n["win_rate"] == 0.4 and n["avg_trade"] == 3
    assert n["profit_factor"] == 2.0 and n["payoff"] == 3.0 and n["max_losing_streak"] == 2
    assert K.trade_numbers([5, 6])["profit_factor"] is None and K.trade_numbers([])["win_rate"] is None


def test_weights_equal_custom_inverse_volatility_and_equal_risk():
    rng = np.random.default_rng(1)
    a = rng.normal(0, 0.02, 40)
    b = rng.normal(0, 0.01, 40)
    assert K.weights("eq", [a, b])["w"] == [0.5, 0.5]
    assert K.weights("custom", [a, b], [30, 10])["w"] == [0.75, 0.25]
    bad = K.weights("custom", [a, b], [0, 0])
    assert bad["used"] == "eq" and bad["note"]
    iv = K.weights("invvol", [a, b])
    sa, sb = a.std(ddof=1), b.std(ddof=1)
    assert iv["used"] == "invvol" and iv["w"][0] == pytest.approx((1 / sa) / (1 / sa + 1 / sb))
    rp = K.weights("rp", [a, b, rng.normal(0, 0.03, 40)])
    assert rp["used"] == "rp" and all(x == pytest.approx(1 / 3, abs=2e-3) for x in rp["risk_share"])   # equal risk
    few = K.weights("invvol", [a[:5], b[:5]])
    assert few["used"] == "eq" and "1시간 기록" in few["note"]
    flat = K.weights("rp", [a, np.zeros(40)])
    assert flat["used"] == "eq" and "움직이지 않은" in flat["note"]
    cov = np.array([[0.04, 0.0], [0.0, 0.01]])
    assert K.erc(cov) == pytest.approx([1 / 3, 2 / 3])          # uncorrelated: equal risk = inverse volatility


def test_correlation_needs_its_points_and_movement():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    m, n = K.corr(np.vstack([x, 2 * x, -x, np.zeros(4)]), 3)
    assert n == 4 and m[0][1] == 1.0 and m[0][2] == -1.0 and m[0][3] is None and m[3][3] is None
    m2, n2 = K.corr(np.vstack([x[:2], x[:2]]), 3)
    assert n2 == 2 and m2[0][1] is None


# ---------------------------------------------------------------- one combination, by hand
def test_equal_weights_by_hand(world):
    c, start, t, _db = world
    d = c.combo(f"{A},{B}", "eq", None, now=t[3] + M)
    assert d["basis"] == "mark" and d["capital"] == 10000 and d["method"]["used"] == "eq"
    s = d["stats"]
    # combined = A + B: 10000, 10050, 9950, 10050, 10100
    assert s["ret"] == pytest.approx(0.01) and s["pnl"] == pytest.approx(100)
    assert s["mdd_pct"] == pytest.approx(100 / 10050, abs=1e-6) and s["mdd_usd"] == pytest.approx(100)
    assert s["mdd_trough_ts"] == t[1] and s["recovered"] is True and s["recovery_days"] == pytest.approx(1 / 24, abs=1e-3)
    # closed trades in exit order: +100 (A), -200 (A), +100 (B), +300 (A), -150 (B)
    assert s["trades"] == 5 and s["wins"] == 3 and s["avg_trade"] == pytest.approx(30)
    assert s["profit_factor"] == pytest.approx(500 / 350, abs=1e-4) and s["payoff"] == pytest.approx((500 / 3) / 175, abs=1e-4)
    assert s["days"] == 1 and s["sharpe_like"] is None                        # one day: no ratio
    u = {x["key"]: x for x in d["units"]}
    assert u[A]["pnl"] == pytest.approx(200) and u[B]["pnl"] == pytest.approx(-100)
    assert u[A]["share"] == pytest.approx(2.0) and u[B]["share"] == pytest.approx(-1.0)
    assert u[A]["weight"] == 0.5 and u[A]["scale"] == 1.0
    # the coin-flip baseline: the same timeframe's flips one for one (RANDOM_1 for A, RANDOM_2 for B)
    f = d["flips"]
    assert f["picked"] == [[F1], [F2]] and f["reused"] == 0 and f["ret"] == pytest.approx(0.01)
    assert f["mdd_pct"] == pytest.approx(0.01) and "pnl" not in f
    loo = {x["key"]: x for x in d["loo"]}
    assert loo[A]["ret"] == pytest.approx(-0.02) and loo[B]["ret"] == pytest.approx(0.04)          # the other alone
    # diversification: members' own max drawdown $ (A 5100 -> 4900 = 200, B 5050 -> 4900 = 150) / the combined 100
    assert d["div_ratio"] == pytest.approx(3.5)
    assert d["curve"]["combined"][-1] == pytest.approx(0.01) and len(d["curve"]["members"]) == 2


def test_custom_weights_scale_each_member(world):
    c, _start, t, _db = world
    d = c.combo(f"{A},{B}", "custom", "75,25", now=t[3] + M)
    u = {x["key"]: x for x in d["units"]}
    assert u[A]["scale"] == 1.5 and u[B]["scale"] == 0.5
    # 1.5 A + 0.5 B: 10000, 10125, 9875, 10075, 10250
    assert d["stats"]["ret"] == pytest.approx(0.025) and d["stats"]["mdd_usd"] == pytest.approx(250)
    assert d["stats"]["avg_trade"] == pytest.approx((150 - 300 + 50 + 450 - 75) / 5)


def test_early_days_say_so_and_the_closed_trade_fallback(tmp_path):
    start = (int(time.time() * 1000) - 10 * H) // 300_000 * 300_000
    db = str(tmp_path / "closed.db")
    st = blank(db, start, [(A, "strategy"), (B, "strategy"), (F1, "random"), (F2, "random")])
    trade(st, A, start + M, start + H, 50.0)
    trade(st, B, start + M, start + 2 * H, -20.0)
    st.commit()
    st.close()
    d = CB.Combo(_Data(db)).combo(f"{A},{B}", "invvol", None, now=start + 3 * H)
    assert d["basis"] == "closed" and "닫힌 거래" in d["basis_ko"]
    assert d["stats"]["pnl"] == pytest.approx(30) and d["stats"]["trades"] == 2
    assert d["small"]["early"] is True and d["small"]["words"] == "거래 2건 · 아직 판단하기 이릅니다"
    assert d["method"]["used"] == "eq" and d["method"]["note"]                # no samples: equal, and says why
    assert d["corr"]["day"]["m"][0][1] is None and d["corr"]["day"]["n"] == 1


def test_units_are_checked_and_deepseek_stays_out(world):
    c, _start, t, _db = world
    c.book.refresh_accounts()
    from fastapi import HTTPException
    for bad, word in (([DS, A], "딥시크"), ([F1, A], "동전 봇"), ([A], "2개 이상"), (["S1_EMA_RSI_CHOP", A], "두 번"),
                      (["NOPE", A], "모르는")):
        with pytest.raises(HTTPException) as e:
            CB.parse_units(c.book, ",".join(bad))
        assert e.value.status_code == 400 and word in e.value.detail, bad
    with pytest.raises(HTTPException):
        CB.custom_of("50", CB.parse_units(c.book, f"{A},{B}"))
    d = c.combo(f"{A},{B}", "eq", None, now=t[3] + M)
    text = json.dumps(d, ensure_ascii=False)
    assert "F1_RSI_DIV" not in text and d["ds_note"].startswith("딥시크 171개")
    assert d["stats"]["pnl"] == pytest.approx(100)                            # DeepSeek's +4,000 is not in it
    u = c.units(now=t[3] + M)
    assert "F1_RSI_DIV" not in json.dumps(u) and u["ds_note"] and {s["id"] for s in u["strategies"]} == {"S1_EMA_RSI_CHOP", "S2_ST_ROC"}
    assert u["five_year_view"] in (True, False)


def test_same_bet_reads_overlap_and_says_why_it_is_only_a_reference(world):
    c, _start, t, _db = world
    sb = c.combo(f"{A},{B}", "eq", None, now=t[3] + M)["same_bet"]
    assert sb["window_days"] == 7 and sb["rules"] == {"min_days": 7.0, "min_trades": 20}
    p = sb["pairs"][0]
    assert {p["a"], p["b"]} == {A, B} and p["sufficient"] is False and set(p["why"]) == {"days", "trades"}


# ---------------------------------------------------------------- merged rules on a hand-made signal log
def _rules_db(path):
    start = (int(time.time() * 1000) - 20 * H) // H * H
    T = start + 6 * H
    st = blank(path, start, [(A, "strategy"), (B, "strategy"), (A4, "strategy"), ("S2_ST_ROC@4h", "strategy"),
                             (F1, "random"), (F2, "random"), (DS, "ds200")])
    trade(st, A, T, T + H, 100.0, symbol="BTCUSDT", side=1)                # a1
    trade(st, A, T + 3 * H, T + 4 * H, -50.0, symbol="ETHUSDT", side=-1)   # a2
    trade(st, A, T + 6 * H, T + 7 * H, 30.0, symbol="BTCUSDT", side=1)     # a3
    trade(st, F1, T, T + H, -20.0, symbol="BTCUSDT", side=1)              # a coin flip on the same bar as a1
    for bar, sym, side in ((T, "BTCUSDT", 1), (T + 3 * H, "ETHUSDT", -1), (T + 6 * H, "BTCUSDT", 1), (T + H, "BTCUSDT", 1)):
        signal(st, "S1_EMA_RSI_CHOP", "1h", bar, sym, side)               # A's own (T + 1h: skipped while busy)
    signal(st, "S2_ST_ROC", "1h", T - 30 * M, "BTCUSDT", 1)               # B agrees with a1 within A's bar
    signal(st, "S2_ST_ROC", "4h", T + H, "ETHUSDT", -1)                   # 2 h before a2: outside the bar, latest = same
    signal(st, "S2_ST_ROC", "4h", T + 4 * H, "BTCUSDT", -1)               # B's latest BTC before a3 is short
    signal(st, "S1_EMA_RSI_CHOP", "4h", T - 2 * H, "BTCUSDT", 1)           # A's 4h: long BTC
    signal(st, "F1_RSI_DIV", "1h", T, "BTCUSDT", 1)                         # DeepSeek: never read here
    st.commit()
    st.close()
    return T + 8 * H


def test_both_filter_vote_and_timeframe_rules_by_hand(tmp_path):
    db = str(tmp_path / "rules.db")
    now = _rules_db(db)
    c = CB.Combo(_Data(db))
    rows = lambda d: {r["id"]: r for r in d["rows"]}  # noqa: E731
    both = c.rules({"kind": "both", "a": A, "b": "S2_ST_ROC"}, now=now)
    r = rows(both)
    assert (r["rule"]["trades"], r["rule"]["pnl"], r["rule"]["win_rate"]) == (1, 100, 1.0)
    assert r["alone"]["trades"] == 3 and r["alone"]["pnl"] == 80 and r["dropped"]["trades"] == 2
    # coin flips: 3 accounts per timeframe, so no dollar sum next to A's (win rate and mean ROE only)
    assert r["flip_rule"]["trades"] == 1 and r["flip_rule"]["pnl"] is None and r["flip_rule"]["win_rate"] == 0.0
    assert r["flip_all"]["trades"] == 1 and r["flip_all"]["pnl"] is None and both["flip_money_ko"]
    assert r["rule"]["mean_roe"] == pytest.approx(100 / 1500, abs=1e-4)     # pnl / margin (30% of 5,000)
    assert both["busy_passed"] == 0 and "근사" in both["approx_ko"] and both["signal_rows"] == 8          # the DeepSeek row is skipped
    filt = c.rules({"kind": "filter", "a": A, "b": "S2_ST_ROC"}, now=now)
    assert rows(filt)["rule"]["trades"] == 2 and rows(filt)["rule"]["pnl"] == 50       # a1 + a2 (a3: B now short)
    assert filt["busy_passed"] == 1                                                    # T + 1h long BTC: B long
    vote = c.rules({"kind": "vote", "m": f"{A},{B}", "k": "2"}, now=now)
    assert rows(vote)["rule"]["trades"] == 1 and rows(vote)["alone"]["trades"] == 3
    tf = c.rules({"kind": "tf", "s": "S1_EMA_RSI_CHOP", "lo": "1h", "hi": "4h"}, now=now)
    assert rows(tf)["rule"]["trades"] == 2 and rows(tf)["rule"]["pnl"] == 130          # a1, a3 (4h long BTC)
    allx = c.rules({"kind": "tf", "s": "all", "lo": "1h", "hi": "4h"}, now=now)
    assert len(allx["per_strategy"]) == 2 and "flip_rule" not in rows(allx)
    from fastapi import HTTPException
    for q in ({"kind": "x"}, {"kind": "both", "a": "S1_EMA_RSI_CHOP", "b": B}, {"kind": "both", "a": A, "b": A},
              {"kind": "vote", "m": f"{A},{B}", "k": "3"}, {"kind": "tf", "lo": "4h", "hi": "1h"},
              {"kind": "both", "a": A, "b": DS}):
        with pytest.raises(HTTPException):
            CB.check_rules(c.book, q)


# ---------------------------------------------------------------- the 36 x 36 map
def test_map_has_no_ranking_before_its_days_and_finds_pairs_later(tmp_path):
    db = str(tmp_path / "w.db")
    info = build(db, days=8, strategies=["S1_EMA_RSI_CHOP", "S2_ST_ROC", "S3_CMO_SANDWICH", "S4_BB_BBP", "S5_DONCHIAN_MFI",
                                         "S6_EMA_DMI_ADX", "N01_ST_EMA"], ds_defs=1)
    c = CB.Combo(_Data(db))
    early = c.corr("strategy", None, "day", now=info["start"] + DAY)        # 2 KST days: under 3
    assert early["ready"] is False and early["top"] == [] and early["hedge"] == [] and early["n"] < early["need"]
    later = c.corr("strategy", None, "day", now=info["now"])
    assert later["ready"] is True and len(later["units"]) == 7 and len(later["m"]) == 7
    assert later["top"] and all(later["top"][i]["r"] >= later["top"][i + 1]["r"] for i in range(len(later["top"]) - 1))
    assert all(p["r"] < 0 for p in later["hedge"]) and later["early"] is False
    acct = c.corr("account", "4h", "hour", now=info["now"])
    assert acct["level"] == "account" and all(u["key"].endswith("@4h") for u in acct["units"])
    assert "F1_RSI_DIV" not in json.dumps(later) and later["overlap"]["window_days"] == 7


# ---------------------------------------------------------------- through the app
def _get(client, path, tries=40):
    for _ in range(tries):
        r = client.get(path)
        if r.status_code != 200 or not r.json().get("pending"):
            return r
        time.sleep(0.25)
    return r


def test_endpoints_answer_read_only_and_reject_bad_requests(world):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app
    _c, _start, _t, db = world
    before = os.stat(db).st_mtime_ns
    client = TestClient(create_app(db, None, b"s" * 32))
    u = _get(client, "/api/v4/combo/units").json()
    assert u["kmin"] == 2 and u["kmax"] == 8 and [m["id"] for m in u["methods"]] == ["eq", "custom", "invvol", "rp"]
    d = _get(client, f"/api/v4/combo?u={A},{B}&w=eq").json()
    assert d["k"] == 2 and d["label"] == "설명용, 판정 아님" and "computed_at" in d
    assert _get(client, f"/api/v4/combo?u={A},{DS}").status_code == 400
    assert _get(client, f"/api/v4/combo?u={A},{B}&w=custom&p=1").status_code == 400
    m = _get(client, "/api/v4/combo/corr?level=account&tf=1h&basis=hour").json()
    assert m["level"] == "account" and m["tf"] == "1h"
    r = _get(client, f"/api/v4/combo/rules?kind=both&a={A}&b=S2_ST_ROC").json()
    assert r["kind"] == "both" and len(r["rows"]) == 5
    assert _get(client, "/api/v4/combo/rules?kind=vote&m=" + A).status_code == 400
    assert os.stat(db).st_mtime_ns == before                                  # nothing written


# ---------------------------------------------------------------- the page
def test_route_rail_find_and_inventory():
    routes = _read(V4, "core", "routes.js")
    assert '{id: "strat", ko: "매매법", screens: ["strategies", "grid", "analysis", "combo"]}' in routes
    assert 'combo: {ko: "조합 성과", group: "strat", title: "조합 성과"}' in routes
    assert re.search(r"\n  combo: \(\) => \[R\(", routes)                    # its own rail icon
    assert "combo: \"조합 성과" in _read(V4, "core", "search.js")
    assert "## 조합 성과" in _read(V4, "INVENTORY.md")
    assert '"combo"' in _read(ROOT, "paperbot", "dash", "more", "__init__.py")


def test_page_rules_honesty_and_the_optional_5_year_module():
    js = {f: _read(V4, "screens", f) for f in os.listdir(os.path.join(V4, "screens")) if f.startswith("combo") and f.endswith(".js")}
    assert {"combo.js", "combo-build.js", "combo-map.js", "combo-rules.js", "combo-kit.js"} <= set(js)
    every = "".join(js.values())
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat",
                "localStorage"):
        assert bad not in every, bad
    main = js["combo.js"]
    i = main.index('import("./combo-5y.js")')
    assert "try {" in main[i - 80:i] and "catch" in main[i:i + 60] and "5년 백테스트 결과 준비 중" in main
    assert "render5y(ctx, slot)" in main and "five_year_view" in main
    assert "딥시크 171개 계좌는 돈 숫자를" in main
    build = js["combo-build.js"]
    assert "ui.refNote(verdictTs())" in build and "ui.assume()" in build and "설명용, 판정 아님" in build
    assert 'local.set("combo-pick"' in build and "env.setQuery(q)" in build                # remembered + in the address
    assert "연율화 안 함" in build and "예시" in build and "추천 아님" in build
    css = _read(V4, "screens", "combo.css")
    assert '@import url("analysis.css");' in css and ".cb-heat { display: block; max-width: none; }" in css


def test_synergy_rows_open_the_combination_and_the_two_drawdowns_are_named():
    rules = _read(V4, "screens", "analysis-rules.js")
    assert 'env.ctx.href("combo", "build", {u: r.units.join(","), from: "synergy"})' in rules
    assert "최대 낙폭 · 계좌 하나" in _read(V4, "screens", "grid-kit.js")
    assert "최대 낙폭 · 합친 곡선" in _read(V4, "screens", "strategies-detail.js")
