"""ana-syn (분석 additions): 조합 시너지 보강 (/api/v4/synplus: 같이 망하는 날, 같이 들어간 진입, 다음 기간에도 통할까, 한
계좌로 합치면) and the 청산 이유 tab (/api/v4/exits: exit reasons per group, 역행·순행). Read-only, descriptive; the math on
hand-computed cases, the waiting states (filling bars, never a ranking of zeros), DeepSeek with counts and shares only,
the endpoint shapes, and the cards rendered in node with a tiny DOM (tests/anasyn_dom.mjs)."""
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from anasyn_world import DAY, HOUR, MIN, blank, build, kst, trade  # noqa: E402
from paperbot.agents import synergy as SY  # noqa: E402
from paperbot.dash import more as MORE  # noqa: E402
from paperbot.dash.more import exits as EX  # noqa: E402
from paperbot.dash.more import synplus as SP  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
MONEY = re.compile(r"pnl|usd|usdt|money|equity|_eq\b|mean_eq|wallet|balance|roe|margin|mfe_r", re.I)
T0 = kst(2026, 10, 5, 0, 30)


def _keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", k
            yield from _keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _keys(v, f"{path}[{i}]")


def _read(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """30 KST days of the v4 run shape (tests/anasyn_world.py) and both views computed once."""
    db = str(tmp_path_factory.mktemp("anasyn") / "paper3.db")
    info = build(db, days=30)
    return {"db": db, **info, "syn": SP.view(db, info["now"]),
            "exits": {g: EX.exits_view(db, info["now"], g) for g in ("core", "ds200", "reel")}}


# ---------------------------------------------------------------- 같이 망하는 날: the pair counts by hand
def test_pair_counts_by_hand():
    M = np.array([[-1.0, -2.0, 3.0, 0.0, -1.0],
                  [-1.0, 2.0, -3.0, 1.0, -2.0],
                  [1.0, 1.0, 1.0, 1.0, 1.0]])
    t = SP.pair_counts(M, worst_share=0.4)                       # ceil(0.4 x 5) = 2 worst days
    assert t["worst_days"] == 2
    # 0 lost on days 0, 1, 4; 1 on 0, 2, 4; 2 never
    assert t["either"][0, 1] == 4 and t["both"][0, 1] == 2 and t["cover"][0, 1] == 2   # day 1 (0 lost, 1 won), day 2
    assert t["either"][0, 2] == 3 and t["both"][0, 2] == 0 and t["cover"][0, 2] == 3
    # 0's two worst: day 1 (-2) and day 0 (-1; ties go to the earlier day); 1 lost on day 0 only -> 1 of 2
    # 1's two worst: day 2 (-3) and day 4 (-2); 0 lost on day 4 -> 1 of 2; 2 has no losing day: no worst days
    assert list(t["bad_n"]) == [2, 2, 0] and t["bad_hit"][0, 1] == 1 and t["bad_hit"][1, 0] == 1
    rows, k = SP.pair_rows(["a", "b", "c"], M, min_days=1)
    r = {(x["a"], x["b"]): x for x in rows}
    assert k == 1                                                 # the default share: ceil(0.2 x 5) = 1
    ab = r[("a", "b")]
    assert ab["co_loss"] == pytest.approx(0.5) and ab["cover"] == pytest.approx(0.5)
    assert ab["bad_ab"] == 0.0 and ab["bad_ba"] == 0.0           # 0's worst (day 1): 1 won; 1's worst (day 2): 0 won
    ac = r[("a", "c")]
    assert ac["co_loss"] == 0.0 and ac["cover"] == 1.0 and ac["bad_ab"] == 0.0 and ac["bad_ba"] is None
    assert (ab["bad_a_days"], ab["bad_b_days"], ac["bad_b_days"]) == (1, 1, 0)       # each side's own denominator
    assert ("b", "c") in r and len(SP.pair_rows(["a", "b", "c"], M)[0]) == 0    # 5 losing days needed by default


def test_coloss_waits_for_14_days_and_ranks_pairs():
    rng = np.random.default_rng(3)
    names = {"a": "에이", "b": "비"}
    M = rng.normal(0, 1, size=(4, 13))
    w = SP.coloss(["a", "b", "c", "d"], M, [], None, names)
    assert w["waiting"] and w["days"] == 13 and w["need_days"] == 14 and "together" not in w
    base = rng.normal(0, 1, size=30)
    M = np.vstack([base, base + 0.01, -base, rng.normal(0, 1, size=30)])
    F = rng.normal(0, 1, size=(3, 30))
    out = SP.coloss(["a", "b", "c", "d"], M, ["f1", "f2", "f3"], F, names)
    assert not out.get("waiting") and out["pairs"] == 6 and out["worst_days"] == 6
    assert out["together"][0]["units"] == ["a", "b"] and out["together"][0]["names"] == ["에이", "비"]
    assert out["together"][0]["co_loss"] == pytest.approx(1.0, abs=0.1)
    top_cover = out["cover_best"][0]
    assert set(top_cover["units"]) in ({"a", "c"}, {"b", "c"}) and top_cover["co_loss"] == 0.0
    assert out["coin_flips"]["units"] == 3 and out["coin_flips"]["pairs"] == 3
    assert 0 <= out["median"]["co_loss"] <= 1


# ---------------------------------------------------------------- 다음 기간에도 통할까: no look-ahead
def test_all_scores_is_every_combination():
    rng = np.random.default_rng(5)
    U = rng.normal(0, 10, size=(6, 9))
    cap = np.full(6, 1000.0)
    got = np.sort(SP.all_scores(U, cap))
    want = []
    for k in range(2, 6):
        for c in itertools.combinations(range(6), k):
            want.append(SY.curve_numbers(U[list(c)].sum(axis=0)[None, :], np.array([cap[list(c)].sum()]))[3][0])
    assert len(got) == 15 + 20 + 15 + 6 and got == pytest.approx(np.sort(want))


def test_walk_forward_chooses_on_the_first_half_only():
    rng = np.random.default_rng(7)
    U = rng.normal(0, 10, size=(7, 24))
    cap = np.full(7, 1000.0)
    h = 12
    a = SP.walk_once(U, cap, h)
    best = SY.search(U[:, :h], cap, keep=1)[0]
    assert a["combo"] == list(best[1]) and a["first_score"] == pytest.approx(best[0], abs=1e-3)
    c = a["combo"]
    s2 = SY.curve_numbers(U[c][:, h:].sum(axis=0)[None, :], np.array([cap[c].sum()]))[3][0]
    assert a["second_score"] == pytest.approx(s2, abs=1e-3)
    pop = SP.all_scores(U[:, h:], cap)
    assert a["combos"] == len(pop) and a["second_median"] == pytest.approx(np.median(pop), abs=1e-3)
    assert a["second_p75"] == pytest.approx(np.quantile(pop, 0.75), abs=1e-3)
    assert a["beat_share"] == pytest.approx(np.mean(pop < s2 - 1e-12), abs=1e-3)
    # the second half never changes the choice (no look-ahead): turn it upside down, the same combination is chosen
    V = U.copy()
    V[:, h:] = -V[:, h:] * 3
    assert SP.walk_once(V, cap, h)["combo"] == c
    days = [f"2026-10-{d:02d}" for d in range(1, 25)]
    w = SP.walk(list("abcdefg"), U, cap, days, [], None, None, {})
    assert w["first"] == {"from": "2026-10-01", "to": "2026-10-12", "days": 12}
    assert w["second"] == {"from": "2026-10-13", "to": "2026-10-24", "days": 12}
    assert w["strategies"]["units"] == [list("abcdefg")[i] for i in c]
    assert SP.walk(list("abcdefg"), U[:, :19], cap, days[:19], [], None, None, {})["waiting"]


# ---------------------------------------------------------------- 같이 들어간 진입: hand-built entries
def _agree_db(path):
    accts = [("A@15m", "strategy"), ("A@1h", "strategy"), ("B@15m", "strategy"), ("C@1h", "strategy"),
             ("D@4h", "strategy"), ("RANDOM_1@15m", "random"), ("RANDOM_1@1h", "random")]
    st = blank(path, T0, accts)
    t = T0 + 2 * DAY

    def m(x):
        return t + x * MIN
    trade(st, "A@15m", m(0), m(60), 10.0)                        # B (+10) and C (-14) within 15 min
    trade(st, "A@1h", m(-30), m(90), -6.0)                       # C (-14) and B (+10) within 60 min
    trade(st, "B@15m", m(10), m(40), -5.0)                       # A (0) only; D closed at +5: no opposite
    trade(st, "C@1h", m(-14), m(100), 4.0)                       # A (twice: one name) and B
    trade(st, "D@4h", m(-100), m(5), 2.0, side=-1)               # the only short: alone
    trade(st, "RANDOM_1@15m", m(5), m(20), -1.0)                 # A, B within 15 min; D closed exactly at +5
    trade(st, "RANDOM_1@1h", m(-20), m(30), 3.0)                 # A, B, C within 60 min; D open
    st.commit()
    st.close()
    return t + DAY


def test_agreement_buckets_by_hand(tmp_path):
    db = str(tmp_path / "paper3.db")
    now = _agree_db(db)
    import sqlite3
    c = sqlite3.connect(db)
    rows = SP._trades(c, 0, ("15m", "30m", "1h", "4h"))
    c.close()
    assert len(rows) == 7 and {r["side"] for r in rows} == {1, -1}
    out = SP.agreement(rows, [], need=1)
    B = out["buckets"]
    n = lambda k, who="strategies": B[k][who]["trades"]          # noqa: E731
    assert (n("alone"), n("two"), n("three_plus")) == (1, 1, 3)         # D / B / A@15m, A@1h, C
    assert (n("opposite"), n("no_opposite")) == (3, 2)                   # D open at A, A@1h, C; not at B (closed at +5)
    assert (n("tf_none"), n("tf_one"), n("tf_two_plus")) == (4, 1, 0)    # A@1h holds long at A@15m's entry
    three = B["three_plus"]["strategies"]
    assert three["win_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert three["mean_roe"] == pytest.approx((0.010 - 0.006 + 0.004) / 3, abs=1e-4)
    assert three["mean_eq"] == pytest.approx((10 - 6 + 4) / 3 / 5000, abs=1e-5)       # pnl / equity before
    assert B["three_plus"]["share"] == pytest.approx(0.6) and three["small"]
    # the coin flips: counted against the 36's entries; an exit at the same instant is not open
    assert (n("three_plus", "coin_flips"), n("alone", "coin_flips")) == (2, 0)
    assert (n("opposite", "coin_flips"), n("no_opposite", "coin_flips")) == (1, 1)
    assert (n("tf_one", "coin_flips"), n("tf_none", "coin_flips")) == (1, 1)            # RANDOM_1@1h holds at +5
    assert out["all"]["strategies"]["trades"] == 5 and out["all"]["coin_flips"]["trades"] == 2
    assert SP.agreement(rows, [])["waiting"] and SP.agreement(rows, [])["need_trades"] == 30
    # a position open now counts as an entry (and as a holding)
    opens = [{"account": "E@15m", "kind": "strategy", "strategy": "E", "tf": "15m", "symbol": "BTCUSDT", "side": -1,
              "entry": rows[0]["entry"] - 50 * MIN, "exit": now, "margin": 10.0, "open": True}]
    o2 = SP.agreement(rows, opens, need=1)["buckets"]
    assert o2["opposite"]["strategies"]["trades"] == 4 and o2["alone"]["strategies"]["trades"] == 0   # D meets E's short


# ---------------------------------------------------------------- 한 계좌로 합치면: the sweep by hand
def test_merged_account_by_hand():
    iv = lambda s, side, a, b, m: {"symbol": s, "side": side, "entry": a * HOUR, "exit": b * HOUR, "margin": m}  # noqa
    out = SP.merged([iv("BTC", 1, 0, 10, 100), iv("BTC", -1, 5, 15, 200), iv("ETH", 1, 20, 22, 50)], 0, 24 * HOUR)
    assert out["busy_hours"] == 17 and out["cancel_hours"] == 5 and out["cancel_share"] == pytest.approx(5 / 17, abs=1e-3)
    assert out["peak_margin"] == 300 and out["peak_ts"] == 5 * HOUR
    # an exit and an entry at the same instant do not overlap (exits first); clipped to [start, now]
    out = SP.merged([iv("BTC", 1, 0, 10, 100), iv("BTC", -1, 5, 15, 200), iv("BTC", 1, 15, 16, 400),
                     iv("ETH", -1, 20, 30, 50)], 0, 24 * HOUR)
    assert out["busy_hours"] == 20 and out["cancel_hours"] == 5 and out["peak_margin"] == 400 and out["peak_ts"] == 15 * HOUR
    assert SP.merged([], 0, HOUR) == {"busy_hours": 0, "cancel_hours": 0, "cancel_share": None, "peak_margin": 0,
                                      "peak_ts": None}


# ---------------------------------------------------------------- the whole view
def test_synplus_view_on_a_month(world):
    v = world["syn"]
    assert v["label"] == "설명용, 판정 아님" and v["group"] == "core" and v["days"] == 30
    co, ag, wf, oa = v["coloss"], v["agree"], v["walk"], v["one_account"]
    assert not co.get("waiting") and co["pairs"] > 0 and len(co["together"]) == SP.TOP_PAIRS
    assert all(0 <= r["co_loss"] <= 1 and 0 <= r["cover"] <= 1 for r in co["together"] + co["cover_best"])
    assert co["together"][0]["co_loss"] >= co["together"][-1]["co_loss"]
    assert co["coin_flips"]["units"] == 12
    assert not ag.get("waiting") and set(ag["buckets"]) == set(SP.AGREE_KEYS + SP.OPP_KEYS + SP.TF_KEYS)
    for keys in (SP.AGREE_KEYS, SP.OPP_KEYS, SP.TF_KEYS):                # each cut adds up to every trade
        assert sum(ag["buckets"][k]["strategies"]["trades"] for k in keys) == ag["trades"]
        assert sum(ag["buckets"][k]["coin_flips"]["trades"] for k in keys) == ag["flip_trades"]
    assert not wf.get("waiting") and wf["first"]["days"] == 15 and wf["second"]["days"] == 15
    assert wf["strategies"]["combos"] == sum(math.comb(36, k) for k in range(2, 6))
    assert 2 <= len(wf["strategies"]["units"]) <= 5 and wf["coin_flips"]["combos"] == sum(math.comb(12, k) for k in range(2, 6))
    assert not oa.get("waiting") and len(oa["combos"]) == SP.TOP_COMBOS
    c0 = oa["combos"][0]
    assert c0["accounts"] == 4 * len(c0["units"]) and c0["capital"] == pytest.approx(5000.0 * c0["accounts"])
    assert c0["peak_x_one"] == pytest.approx(c0["peak_margin"] / 5000.0, abs=0.01)
    assert 0 <= c0["cancel_share"] <= 1 and c0["cancel_hours"] <= c0["busy_hours"]
    assert oa["coin_flips"]["accounts"] == 12
    # the same top list as the 조합 시너지 view (agents/synergy.search over the same days)
    from paperbot.dash.analysis import ro_connect
    c = ro_connect(world["db"])
    top = SY.analyse(c, world["now"], shuffles=0)["top"][:3]
    c.close()
    assert [x["units"] for x in oa["combos"]] == [t["units"] for t in top]
    json.dumps(v, allow_nan=False)                                       # finite numbers only
    assert v["runtime_s"] < 20


def test_synplus_waits_with_its_real_thresholds(tmp_path):
    db = str(tmp_path / "paper3.db")
    info = build(db, days=6, seed=3)
    v = SP.view(db, info["now"])
    assert v["coloss"]["waiting"] and v["coloss"]["need_days"] == 14 and v["coloss"]["days"] == 6
    assert v["walk"]["waiting"] and v["walk"]["need_days"] == 20
    assert "together" not in v["coloss"] and "strategies" not in v["walk"]
    assert not v["agree"].get("waiting")                                   # trades come before days
    empty = str(tmp_path / "empty.db")
    blank(empty, T0, [("A@15m", "strategy"), ("B@15m", "strategy"), ("RANDOM_1@15m", "random")]).close()
    e = SP.view(empty, T0 + 2 * DAY)
    assert e["agree"]["waiting"] and e["agree"]["trades"] == 0 and e["agree"]["need_trades"] == 30
    assert e["one_account"]["waiting"] and e["one_account"]["avg_trades"] == 0 and "combos" not in e["one_account"]
    assert SP.view(str(tmp_path / "none.db"), T0)["error"] == "paper3.db 없음"


# ---------------------------------------------------------------- 청산 이유
def test_lock_steps_and_labels():
    assert EX.lock_key(0.10, 0.10, 0.05) == ("LOCK1", 1) and EX.lock_key(0.15, 0.10, 0.05) == ("LOCK2", 2)
    assert EX.lock_key(0.25, 0.10, 0.05) == ("LOCK4", 4) and EX.lock_key(0.30, 0.10, 0.05) == ("LOCK5+", 5)
    assert EX.lock_key(0.55, 0.10, 0.05) == ("LOCK5+", 5) and EX.lock_key(None, 0.1, 0.05) == ("LOCK?", 99)
    assert EX.reason_label("LOCK2", 0.10, 0.05, False) == "익절 잠금 2단계 (+15%)"
    assert EX.reason_label("LOCK5+", 0.10, 0.05, False) == "익절 잠금 5단계 이상 (+30%~)"
    assert EX.reason_label("SL", 0.1, 0.05, False) == "손절" and EX.reason_label("TP", 0.1, 0.05, True).startswith("목표가")
    assert EX.reason_label("WEIRD", 0.1, 0.05, False) == "기타 (WEIRD)"
    keys = sorted(["LIQ", "LOCK2", "TP", "LOCK1", "SL", "LOCK5+", "WEIRD", "TIME"], key=EX._sort_key)
    assert keys == ["SL", "LOCK1", "LOCK2", "LOCK5+", "TP", "TIME", "LIQ", "WEIRD"]


def _exits_db(path):
    accts = [("A@15m", "strategy"), ("B@1h", "strategy"), ("F1_RSI_DIV@15m", "ds200"), ("RANDOM_1@15m", "random")]
    st = blank(path, T0, accts)
    t = T0 + DAY
    # entry 100, first stop 99 (1 point = 1R); prices in points
    trade(st, "A@15m", t, t + HOUR, 30.0, reason="LOCK", lock_roe=0.10, mae_price=99.85, mfe_price=101.0)   # mae 0.15
    trade(st, "A@15m", t + 2 * HOUR, t + 3 * HOUR, 20.0, reason="LOCK", lock_roe=0.15, mae_price=99.1,
          mfe_price=101.5)                                                                     # mae 0.9: near the stop
    trade(st, "B@1h", t, t + HOUR, 50.0, reason="LOCK", lock_roe=0.40, mae_price=99.6, mfe_price=103.0)    # mae 0.4
    trade(st, "B@1h", t + 2 * HOUR, t + 4 * HOUR, -40.0, reason="SL", mae_price=98.8, mfe_price=101.2)     # 1.2R up
    trade(st, "A@15m", t + 5 * HOUR, t + 6 * HOUR, -20.0, reason="SL", mae_price=99.0, mfe_price=100.3)    # 0.3R
    trade(st, "A@15m", t + 7 * HOUR, t + 8 * HOUR, -1000.0, reason="LIQ", mae_price=97.0, mfe_price=100.0,
          equity_after=5.0)                                                                    # the bust
    trade(st, "A@15m", t + 9 * HOUR, t + 10 * HOUR, 5.0, reason="LOCK", lock_roe=0.10, stop_initial=100.0)  # no stop
    for i in range(3):
        trade(st, "F1_RSI_DIV@15m", t + i * HOUR, t + i * HOUR + 30 * MIN, -10.0 if i else 12.0,
              reason="SL" if i else "LOCK", lock_roe=None if i else 0.10, mae_price=99.5, mfe_price=100.6)
    trade(st, "RANDOM_1@15m", t, t + HOUR, -10.0, reason="SL", mae_price=98.9, mfe_price=100.5)
    st.commit()
    st.close()
    return t + DAY


def test_exit_reasons_by_hand(tmp_path, monkeypatch):
    db = str(tmp_path / "paper3.db")
    now = _exits_db(db)
    monkeypatch.setattr(EX, "MIN_TRADES", 1)
    v = EX.exits_view(db, now, "core")
    assert v["trades"] == 7 and v["flip_trades"] == 1 and not v.get("waiting") and v["house_exits"]
    R = {r["key"]: r for r in v["reasons"]}
    assert [r["key"] for r in v["reasons"]] == ["SL", "LOCK1", "LOCK2", "LOCK5+", "LIQ"]
    assert R["LOCK1"]["group"]["trades"] == 2 and R["LOCK1"]["group"]["share"] == pytest.approx(2 / 7, abs=1e-4)
    assert R["LOCK1"]["ko"] == "익절 잠금 1단계 (+10%)" and R["LOCK5+"]["group"]["trades"] == 1
    assert R["SL"]["group"]["win_rate"] == 0 and R["SL"]["group"]["mean_roe"] == pytest.approx((-0.04 - 0.02) / 2)
    assert R["SL"]["coin_flips"] == {"trades": 1, "share": 1.0, "win_rate": 0.0, "median_hold_bars": 4.0,
                                     "mean_roe": pytest.approx(-0.01)}
    # holding time in the trade's own bars: SL 2 h on 1h (2) and 1 h on 15m (4) -> 3; LOCK5+ 1 h on 1h -> 1
    assert R["SL"]["group"]["median_hold_bars"] == 3.0 and R["LOCK5+"]["group"]["median_hold_bars"] == 1.0
    assert R["LOCK1"]["group"]["median_hold_bars"] == 4.0 and R["LIQ"]["group"]["median_hold_bars"] == 4.0
    assert R["LOCK2"]["coin_flips"] == {"trades": 0} and v["busts"] == 1 and v["flip_busts"] == 0
    ex = v["excursion"]["group"]
    assert ex["no_stop"] == 1                                    # a stop at the entry price: no distance, left out
    w = ex["winners"]
    assert w["n"] == 3 and [b["n"] for b in w["mae"]] == [1, 1, 0, 1, 0]          # 0.15 / 0.4 / 0.9
    assert w["near_stop"] == pytest.approx(1 / 3, abs=1e-4) and w["near_n"] == 1 and w["small"]
    lo = ex["losers"]
    assert lo["n"] == 3 and [b["n"] for b in lo["mae"]] == [0, 0, 0, 0, 3] and lo["deep"] == 1.0
    assert [b["n"] for b in lo["mfe"]] == [1, 1, 0, 1]                              # 0.0 (LIQ) / 0.3 / 1.2 R
    assert lo["one_r"] == pytest.approx(1 / 3, abs=1e-4) and lo["median_mfe_r"] == pytest.approx(0.3)
    # losers lasted 2 / 4 / 4 bars: all in 2-5, none gone within 2 bars, median 4
    assert lo["hold_n"] == 3 and [b["n"] for b in lo["hold"]] == [0, 3, 0, 0, 0]
    assert lo["median_hold_bars"] == 4.0 and lo["quick"] == 0.0
    assert sum(b["share"] for b in w["mae"]) == pytest.approx(1.0, abs=1e-3)
    json.dumps(v, allow_nan=False)


def test_deepseek_exits_carry_counts_and_shares_only(tmp_path, monkeypatch, world):
    db = str(tmp_path / "paper3.db")
    now = _exits_db(db)
    monkeypatch.setattr(EX, "MIN_TRADES", 1)
    v = EX.exits_view(db, now, "ds200")
    assert v["no_money"] and v["trades"] == 3 and v["flip_trades"] == 1
    for out in (v, world["exits"]["ds200"]):
        bad = [p for p, k in _keys(out) if MONEY.search(str(k)) and k != "no_money"]
        assert not bad, bad
        assert "mean_roe" not in json.dumps(out) and "median_mfe_r" not in json.dumps(out)
    R = {r["key"]: r for r in v["reasons"]}
    assert R["SL"]["group"] == {"trades": 2, "share": pytest.approx(2 / 3, abs=1e-4), "win_rate": 0.0,
                                "median_hold_bars": 2.0}                 # 30 min on 15m: a count, not money
    assert v["excursion"]["group"]["losers"]["one_r"] == 0.0           # shares stay: 0.6R < 1R
    core = world["exits"]["core"]
    assert not core.get("no_money") and any("mean_roe" in r["group"] for r in core["reasons"])


def test_exits_wait_and_the_reel_uses_its_own_exits(tmp_path, world):
    db = str(tmp_path / "paper3.db")
    now = _exits_db(db)
    v = EX.exits_view(db, now, "core")
    assert v["waiting"] and v["trades"] == 7 and v["min_trades"] == 20      # a filling bar, not a table of zeros
    r = world["exits"]["reel"]
    assert not r["house_exits"] and r["lock"] is None
    assert {x["key"] for x in r["reasons"]} <= {"SL", "TP", "TIME", "LIQ", "EOD"}
    assert all(not x["key"].startswith("LOCK") for x in r["reasons"])
    c = world["exits"]["core"]
    assert sum(x["group"]["trades"] for x in c["reasons"]) == c["trades"]
    assert sum(x["group"].get("share") or 0 for x in c["reasons"]) == pytest.approx(1.0, abs=1e-3)
    assert EX.exits_view(str(tmp_path / "none.db"), now, "core")["error"] == "paper3.db 없음"


# ---------------------------------------------------------------- routes
def test_routes_are_registered_and_answer(world):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    assert "synplus" in MORE.MODULES and "exits" in MORE.MODULES
    app = fastapi.FastAPI()
    done = MORE.register_all(app, data=None, rooms=None, db=world["db"], daily_db=None, agents_db=None,
                             checkpoint_db=None, candles=None, frames=None)
    assert done["synplus"]["routes"] == ["/api/v4/synplus"] and done["exits"]["routes"] == ["/api/v4/exits"]
    c = TestClient(app)
    s = None
    for _ in range(20):                                                   # a first answer may be 'pending'
        s = c.get("/api/v4/synplus").json()
        if not s.get("pending"):
            break
        assert s["note"]
    assert set(s) >= {"coloss", "agree", "walk", "one_account", "label", "computed_at"}
    e = c.get("/api/v4/exits").json()
    for _ in range(20):
        if not e.get("pending"):
            break
        e = c.get("/api/v4/exits").json()
    assert e["group"] == "core" and e["reasons"]
    d = c.get("/api/v4/exits?group=ds200").json()
    for _ in range(20):
        if not d.get("pending"):
            break
        d = c.get("/api/v4/exits?group=ds200").json()
    assert d["no_money"] is True and d["group"] == "ds200"
    assert c.get("/api/v4/exits?group=flip").status_code == 400            # never silently the 36


def test_routes_share_the_dashboards_one_at_a_time_worker(tmp_path):
    pytest.importorskip("fastapi")
    from paperbot.dash.app import create_app
    db = str(tmp_path / "paper3.db")
    blank(db, T0, [("A@15m", "strategy")]).close()
    app = create_app(db, None, b"s" * 32)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/api/v4/synplus", "/api/v4/exits"} <= paths
    assert type(app.state.analysis).__name__ == "Heavy"


# ---------------------------------------------------------------- the page
def _render(kind: str, data: dict, group: str = "core") -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    base = "file://" + SCREENS
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\n"
              f"const E = await import('{base}/analysis-exits.js'); const P = await import('{base}/analysis-synplus.js');\n"
              f"const d = {json.dumps(data)};\n"
              f"const env = {{verdictTs: null, group: '{group}', ctx: {{href: () => '#', alive: () => true}}, track() {{}}}};\n"
              f"const nodes = '{kind}' === 'syn' ? P.render(d, env) : E.exits(d, env);\n"
              "console.log(JSON.stringify(D.walk(nodes)));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_exits_page_words(world):
    core = _render("exits", world["exits"]["core"])
    t = core["text"]
    assert "어떻게 끝났나" in t and "역행·순행" in t and "평균 ROE" in t and "익절 잠금 1단계 (+10%)" in t
    assert "손절선 80% 가까이 갔다 왔어요" in t and "1R(손절 거리만큼) 넘게 이기고 있었어요" in t and "참고" in t
    assert "설명용, 판정 아님" in t and "채워지는 중" not in t
    # holding time replaces the 0 % / 100 % win column and the always-100 % losers chart
    assert "보통 걸린 시간" in t and "손절까지 걸린 시간 (봉)" in t and "2봉 안에 끝났어요" in t
    assert t.count("손절선 쪽으로 밀린 정도") == 1 and "이긴 비율" not in t
    assert any("ax-b core" in c for c in core["classes"]) and any("ax-b flip" in c for c in core["classes"])
    ds = _render("exits", world["exits"]["ds200"], "ds200")["text"]
    assert "돈 숫자 없음" in ds and "평균 ROE" not in ds and "가운데 값은" not in ds and "USDT" not in ds
    assert not re.search(r"ROE [−+]?\d", ds)
    assert "보통 걸린 시간" in ds and "손절까지 걸린 시간 (봉)" in ds          # bars are a count: fine for DeepSeek
    wait = _render("exits", {"group": "core", "trades": 3, "flip_trades": 2, "min_trades": 20, "waiting": True})["text"]
    assert "채워지는 중" in wait and "끝난 거래 20건 필요" in wait and "이유별 성적" not in wait
    reel = _render("exits", world["exits"]["reel"], "reel")["text"]
    assert "릴스는 자기 규칙으로" in reel and "익절 잠금" not in reel


def test_synplus_page_words(world, tmp_path):
    full = _render("syn", world["syn"])
    t = full["text"]
    for plate in ("같이 망하는 날", "같이 들어간 진입", "다음 기간에도 통할까", "한 계좌로 합치면"):
        assert plate in t
    assert "채워지는 중" not in t and "동전 봇" in t and "참고" in t and "모의 · 실제 시세" in t
    assert "봉 합의" in t and "USDT" in t                       # the margin card's money carries assume() (above)
    db = str(tmp_path / "paper3.db")
    info = build(db, days=6, seed=3)
    early = _render("syn", SP.view(db, info["now"]))["text"]
    assert "채워지는 중" in early and "하루 손익 14일 필요" in early and "하루 손익 20일 필요" in early
    assert "같이 망한 쌍" not in early and "앞 절반 최고 조합" not in early        # no ranking before the days
    err = _render("syn", {"error": "paper3.db 없음"})["text"]
    assert "paper3.db 없음" in err


def test_wiring_tokens_and_honesty_words():
    a = _read("analysis.js")
    assert 'import * as E from "./analysis-exits.js";' in a
    i, j = a.index('{id: "risk"'), a.index('{id: "exits"')
    assert i < j < a.index('{id: "map"')                                  # right after 손익비·위험
    assert re.search(r'\{id: "exits", label: "청산 이유", path: "/api/v4/exits", render: E\.exits, groups: "groups"', a)
    r = _read("analysis-rules.js")
    assert r.count("out.push(synPlus(env));") == 2                         # also under the day-0 waiting card
    s = _read("analysis-synplus.js")
    assert "env.ctx.timeout(() => { if (!dead) ask(); }, RETRY_MS);" in s and "const RETRY_MS = 3000;" in s
    assert "env.track(() => { dead = true; });" in s
    for f in ("analysis-synplus.js", "analysis-exits.js"):
        src = _read(f)
        assert "innerHTML" not in src and "toLocaleString" not in src
        assert not re.search(r"합격(?!·불합격을 뜻하지)|통과|추천|하세요", src), f
    css = _read("analysis-anasyn.css")
    assert '@import url("analysis-anasyn.css");' in _read("analysis.css")
    for m in re.finditer(r"font-size:\s*([^;}]+)", css):
        assert m.group(1).strip().startswith("var(--t-"), m.group(0)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
