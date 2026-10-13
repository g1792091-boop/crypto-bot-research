"""candleague/monthsim.py monthsim_views: the 한 달 시뮬 block (league.json key ``monthsim``), on hand-made accounts and trades (no network).

  * the daily series by hand: an account's daily return = the day's closed P&L over the wallet before the day (start wallet equity0 plus the
    earlier P&L), 0 on a day without a close; the kind's basket = the plain mean over its accounts that have a closed trade; only whole UTC days up
    to the last complete day (today's open day is left out);
  * the day resampling against known answers (a constant return, two equally likely days, one bad day among ten) and the exact outputs
    (percentiles in order, p_x2 / p_x4 / p_below_half / p_loss, observed and linear multiples);
  * "few": fewer than 7 distinct days or 30 trades -> counts and the Korean message, never a percentile; the boundary itself is enough;
  * edge_vs_coin (the paired day draws, its 90% interval, the coin reaching the median) and the single-account cross-section by hand;
  * deterministic (sha256 seeds, no clock), JSON-safe, odd inputs, a lineup without the kinds;
  * the DeepSeek money rule (D11) both ways; a performance smoke with about a million trades;
  * runner.write_snapshots carrying the key in a league with a lineup (and not otherwise), following the DeepSeek switch, and a failure leaving
    only ``monthsim_error``."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from candleague import monthsim as MS  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402

H, DAY = 3_600_000, 86_400_000
T0 = (1_791_000_000_000 // DAY) * DAY                  # a UTC midnight: day d starts at T0 + d * DAY
SUFFIXES = ("-fq", "-fqc", "-ld", "-ldc")
LU = [{"role": s[1:], "suffix": s, "label_ko": lab, "short_ko": short} for s, lab, short in (
    ("-fq", "메인 · 구조 확실히 무너지면 빠른 손절 (실전 후보)", "빠른 손절"), ("-fqc", "대조 · 메인 빠른 손절의 동전 던지기 짝", "빠른 손절 동전"),
    ("-ld", "대조 · 계단 · 손절 최대 2 ATR", "계단"), ("-ldc", "대조 · 계단 · 동전 던지기", "계단 동전"))]
EQ = 1000.0


def at(day, hour=0):
    return T0 + day * DAY + hour * H


def trades_of(rets, per_day=3, eq0=EQ, day0=0):
    """One account's closed trades from daily returns: day d's P&L = wallet * r split over ``per_day`` trades (None = no close that day)."""
    w, out = eq0, []
    for d, r in enumerate(rets):
        if r is None:
            continue
        pnl = w * r
        n = per_day[d] if isinstance(per_day, (list, tuple)) else per_day
        out += [{"exit_time": at(day0 + d, 2 + j), "pnl": pnl / n, "roe": 0.0} for j in range(n)]
        w += pnl
    return out


def world(series, extra=None):
    """{suffix: daily returns (one account) or [daily returns, ...] (several accounts)} -> (accts, book). ``extra``: [(suffix, kind, rets)]."""
    accts, book = [], {}
    items = [(s, "core", r) for s, v in series.items() for r in (v if v and isinstance(v[0], (list, tuple)) else [v])] + list(extra or [])
    for i, (s, kind, rets) in enumerate(items):
        aid = f"{kind}-P{i}-1h-1{s}"
        accts.append({"id": aid, "pick": f"{kind}-P{i}", "role": s[1:], "kind": kind})
        book[aid] = trades_of(rets)
    return accts, book


def run(series, days=None, ds_money=False, extra=None, lineup=LU):
    """The block for ``series`` ({suffix: daily returns | [daily returns, ...]}) on ``days`` complete days (default: the length of the first series)."""
    accts, book = world(series, extra)
    first = next(iter(series.values()))
    n = days if days is not None else len(first[0] if isinstance(first[0], (list, tuple)) else first)
    return MS.monthsim_views(book, accts, lineup, T0, at(n, 12), ds_money, EQ), accts, book


def by(d):
    return {k["suffix"]: k for k in d["kinds"]}


def flat(x, n=10):
    return [x] * n


# ---------------------------------------------------------------- the daily series by hand
def test_account_day_returns_by_hand():
    """day 0: +60 +40 on 1000 -> +10%; day 1: no close -> 0; day 2: -110 on 1100 -> -10%; day 3: +99 on 990 -> +10%."""
    day = np.array([0, 0, 2, 3])
    pnl = np.array([60.0, 40.0, -110.0, 99.0])
    r, n, seen = MS._account_days(day, pnl, 0, 4, 1000.0)
    assert r == pytest.approx([0.10, 0.0, -0.10, 0.10]) and n == 4 and seen.tolist() == [True, False, True, True]
    # the P&L of a day before the window counts in the wallet but not in the trades
    r, n, seen = MS._account_days(np.array([-1, 1]), np.array([500.0, 150.0]), 0, 2, 1000.0)
    assert r == pytest.approx([0.0, 0.10]) and n == 1 and seen.tolist() == [False, True]
    # a wallet that is gone stays at 0 (never a division by zero, never below -100%)
    r, n, _ = MS._account_days(np.array([0, 1, 2]), np.array([-1500.0, 50.0, 50.0]), 0, 3, 1000.0)
    assert r.tolist() == [-1.0, 0.0, 0.0] and n == 3


def test_observed_multiple_is_the_compounded_basket_and_a_kind_with_few_days_still_has_the_fact():
    d, _a, _b = run({"-fq": [0.10, None, -0.10, 0.10]}, days=4)
    k = by(d)["-fq"]
    assert (k["status"], k["days"], k["window_days"], k["n_accounts"], k["n_trades"]) == ("few", 3, 4, 1, 9)
    assert k["observed_multiple"] == pytest.approx(1.1 * 1.0 * 0.9 * 1.1, abs=1e-4)
    assert all(k[f] is None for f in MS.FEW_FIELDS)                                  # no percentile, no probability, no linear multiple
    assert k["few_ko"] == "아직 자료가 모자랍니다 (3일, 9건 · 7일 · 30건부터)"


def test_basket_is_the_plain_mean_of_the_accounts_with_a_closed_trade():
    # two accounts: +10% and +30% on day 0 -> the basket is +20%; a third account without any trade is not part of the mean
    accts, book = world({"-fq": [[0.10, 0.0], [0.30, 0.0]]})
    accts.append({"id": "core-Q-1h-1-fq", "pick": "core-Q", "role": "fq", "kind": "core"})
    book["core-Q-1h-1-fq"] = []
    d = MS.monthsim_views(book, accts, LU, T0, at(2, 12), False, EQ)
    k = by(d)["-fq"]
    assert k["n_accounts"] == 2 and k["observed_multiple"] == pytest.approx(1.20, abs=1e-4)
    # a different start wallet changes the returns (the P&L is in dollars): the same P&L on 2000 is half the return
    d2 = MS.monthsim_views(book, accts, LU, T0, at(2, 12), False, 2000.0)
    assert by(d2)["-fq"]["observed_multiple"] == pytest.approx(1.10, abs=1e-4) and d2["equity0"] == 2000.0


def test_the_window_is_whole_utc_days_up_to_the_last_complete_one():
    accts, book = world({"-fq": [0.01] * 5})
    book[accts[0]["id"]] += [{"exit_time": at(5, 1), "pnl": 500.0}]                   # a close on today's open day (day 5)
    d = MS.monthsim_views(book, accts, LU, T0, at(5, 12), False, EQ)
    k = by(d)["-fq"]
    assert d["window_days"] == 5 and d["through_ms"] == at(5) and d["start_ms"] == T0
    assert k["n_trades"] == 15 and k["observed_multiple"] == pytest.approx(1.01 ** 5, abs=1e-4)      # today's trade is not counted
    d = MS.monthsim_views(book, accts, LU, T0, at(6, 0), False, EQ)                     # the next day has begun: day 5 is complete
    assert by(d)["-fq"]["n_trades"] == 16 and d["window_days"] == 6
    # now before the start: an empty window, nothing breaks
    d = MS.monthsim_views(book, accts, LU, at(5), at(4), False, EQ)
    assert d["window_days"] == 0 and d["through_ms"] is None and by(d)["-fq"]["status"] == "few" and by(d)["-fq"]["n_trades"] == 0
    # no start / no clock: the window is the first to the last day with a trade of these kinds
    d = MS.monthsim_views(book, accts, LU, None, None, False, EQ)
    assert d["window_days"] == 6 and d["start_ms"] is None and by(d)["-fq"]["n_trades"] == 16


# ---------------------------------------------------------------- the day resampling against known answers
def test_constant_daily_return_gives_one_certain_outcome():
    for r, x2, x4, half, loss in ((0.03, 1.0, 0.0, 0.0, 0.0), (-0.03, 0.0, 0.0, 1.0, 1.0), (0.05, 1.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0, 0.0)):
        d, _a, _b = run({"-fq": flat(r)})
        k = by(d)["-fq"]
        assert k["status"] == "ok" and k["days"] == 10 and k["n_trades"] == 30 and k["n_accounts"] == 1
        want = (1 + r) ** 30
        assert all(v == pytest.approx(want, abs=1e-3) for v in k["percentiles"].values()), (r, k["percentiles"])
        assert (k["p_x2"], k["p_x4"], k["p_below_half"], k["p_loss"]) == (x2, x4, half, loss)
        assert k["observed_multiple"] == pytest.approx((1 + r) ** 10, abs=1e-3)
        assert k["linear_multiple"] == pytest.approx(max(0.0, 1 + ((1 + r) ** 10 - 1) * 3), abs=1e-3)       # the average daily gain x 30, not compounded


def test_two_equally_likely_days_are_binomial():
    """Days +10% / -10%, five of each: a 30-day path with k winning days ends at 1.1^k * 0.9^(30-k), k ~ Binomial(30, 1/2)."""
    d, _a, _b = run({"-fq": [0.10, -0.10] * 5})
    k = by(d)["-fq"]
    loss_k = 15                                                                       # 1.1^k * 0.9^(30-k) < 1  <=>  k <= 15
    p_loss = sum(math.comb(30, i) for i in range(loss_k + 1)) / 2 ** 30
    assert k["p_loss"] == pytest.approx(p_loss, abs=0.04)
    p = k["percentiles"]
    assert p["p05"] < p["p25"] < p["p50"] < p["p75"] < p["p95"]
    assert p["p50"] == pytest.approx(1.1 ** 15 * 0.9 ** 15, rel=0.2) and k["p_x4"] == pytest.approx(
        sum(math.comb(30, i) for i in range(30 + 1) if 1.1 ** i * 0.9 ** (30 - i) >= 4) / 2 ** 30, abs=0.01)


def test_the_unit_is_the_day_not_the_trade():
    """One day in ten loses 50%, the other nine gain 1%. Every draw of 30 days has k ~ Binomial(30, 0.1) bad days."""
    rets = [0.01] * 9 + [-0.50]
    d, _a, _b = run({"-fq": rets})
    k = by(d)["-fq"]
    pk = lambda lo, hi: sum(math.comb(30, i) * 0.1 ** i * 0.9 ** (30 - i) for i in range(lo, hi + 1))  # noqa: E731
    assert k["p_loss"] == pytest.approx(pk(1, 30), abs=0.03)                         # one bad day already ends below 1 (1.01^29 * 0.5 < 1)
    assert k["p_below_half"] == pytest.approx(pk(2, 30), abs=0.03)                    # two bad days end below one half; one does not (0.668)
    assert k["percentiles"]["p95"] <= 1.01 ** 30 + 1e-6                               # nothing beats 30 good days


def test_percentiles_are_ordered_and_the_probabilities_agree_with_them():
    rng = np.random.default_rng(4)
    d, _a, _b = run({s: list(rng.normal(0.01, 0.04, 20)) for s in SUFFIXES})
    for k in d["kinds"]:
        p = k["percentiles"]
        assert p["p05"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p95"]
        for f in ("p_x2", "p_x4", "p_below_half", "p_loss"):
            assert 0.0 <= k[f] <= 1.0
        assert k["p_x4"] <= k["p_x2"] and k["p_below_half"] <= k["p_loss"]
        if p["p05"] > 1.0:
            assert k["p_loss"] <= 0.05 + 1e-9
        if p["p50"] >= 2.0:
            assert k["p_x2"] >= 0.5 - 1e-9
        if p["p50"] < 1.0:
            assert k["p_loss"] >= 0.5 - 1e-9


# ---------------------------------------------------------------- too little data
def test_few_days_or_few_trades_give_the_counts_and_no_numbers():
    # six days with plenty of trades: not enough days
    d, _a, _b = run({"-fq": flat(0.02, 6)})
    k = by(d)["-fq"]
    assert k["status"] == "few" and k["days"] == 6 and k["few_ko"] == "아직 자료가 모자랍니다 (6일, 18건 · 7일 · 30건부터)"
    assert all(k[f] is None for f in MS.FEW_FIELDS) and k["edge_vs_coin"] == {"status": "none"}       # (the twin has no account at all here)
    # seven days but 29 trades: not enough trades
    accts, book = world({"-fq": []})
    book[accts[0]["id"]] = trades_of(flat(0.02, 7), per_day=[5, 4, 4, 4, 4, 4, 4])
    assert len(book[accts[0]["id"]]) == 29
    k = by(MS.monthsim_views(book, accts, LU, T0, at(7, 12), False, EQ))["-fq"]
    assert k["status"] == "few" and (k["days"], k["n_trades"]) == (7, 29) and k["percentiles"] is None and k["few_ko"].endswith("(7일, 29건 · 7일 · 30건부터)")
    # exactly 7 days and 30 trades is enough
    book[accts[0]["id"]] = trades_of(flat(0.02, 7), per_day=[6, 4, 4, 4, 4, 4, 4])
    k = by(MS.monthsim_views(book, accts, LU, T0, at(7, 12), False, EQ))["-fq"]
    assert k["status"] == "ok" and (k["days"], k["n_trades"]) == (7, 30) and k["few_ko"] is None and set(k["percentiles"]) == set(MS.PCT_KEYS)
    # the distinct days with a close are what counts: ten calendar days, only six of them with closes
    d, _a, _b = run({"-fq": [0.02, None, 0.02, None, 0.02, None, 0.02, None, 0.02, 0.02]})
    k = by(d)["-fq"]
    assert (k["days"], k["window_days"], k["status"]) == (6, 10, "few")
    # the headline says so, with the counts and nothing else
    assert d["headline_ko"] == "실전 후보는 아직 자료가 모자랍니다 (6일, 18건 · 7일 · 30건부터)"


def test_a_kind_the_lineup_has_not_is_none_and_the_headline_moves_on():
    d, _a, _b = run({"-ld": flat(0.01), "-ldc": flat(0.0)}, lineup=[k for k in LU if k["suffix"] in ("-ld", "-ldc")])
    assert by(d)["-fq"]["status"] == "none" and by(d)["-fqc"]["status"] == "none" and by(d)["-ld"]["status"] == "ok"
    assert by(d)["-fq"]["edge_vs_coin"] == {"status": "none"} and by(d)["-fq"]["label_ko"] is None
    assert d["headline_ko"].startswith("대조 10일 · 30건: 한 달(30일) 이어진다고 해 본 중앙값은 ")
    d = MS.monthsim_views({}, [], None, T0, at(3), False, EQ)
    assert [k["status"] for k in d["kinds"]] == ["none"] * 4 and d["headline_ko"] == "아직 자료가 없습니다."
    json.dumps(d, allow_nan=False)


# ---------------------------------------------------------------- the headline and the notes
def test_headline_is_counts_and_the_median_only():
    d, _a, _b = run({"-fq": flat(0.01), "-fqc": flat(0.0)})
    m = by(d)["-fq"]["percentiles"]["p50"]
    assert d["headline_ko"] == f"실전 후보 10일 · 30건: 한 달(30일) 이어진다고 해 본 중앙값은 {m:.2f}배 (${EQ:,.0f} → ${EQ * m:,.0f}), 동전 짝은 1.00배입니다."
    for word in ("보장", "확실", "약속", "벌 수", "수익을 낼"):
        assert word not in d["headline_ko"]
    n = " ".join(d["note_ko"])
    for word in ("독립", "같은 비중", "열려 있는 포지션", "7일", "30건", "약속이나 예측이 아닙니다"):
        assert word in n, word
    assert d["note_ko"] == MS.notes_ko() and d["horizon_days"] == 30 and d["boot"] == 2000 and d["goal_multiple"] == 4.0 and d["ci_level"] == 0.9
    assert (d["min_days"], d["min_trades"]) == (7, 30) and d["ds_in_stats"] is False


# ---------------------------------------------------------------- the coin twin
def test_edge_is_zero_when_real_and_coin_are_the_same_series():
    rng = np.random.default_rng(1)
    r = list(rng.normal(0.0, 0.05, 14))
    d, _a, _b = run({"-fq": r, "-fqc": r})
    e = by(d)["-fq"]["edge_vs_coin"]
    assert e["status"] == "ok" and e["diff"] == 0.0 and e["lo"] == 0.0 and e["hi"] == 0.0 and e["zero_in_interval"] is True
    assert 0.5 <= e["coin_reaches_real_median"] <= 0.6 and e["p_real_beats_coin"] == 0.0        # identical months: the coin reaches the median as often as the real kind, never loses to it
    assert by(d)["-fqc"]["edge_vs_coin"] is None and by(d)["-ld"]["edge_vs_coin"] == {"status": "none"}      # a coin kind has none; no -ld account


def test_edge_uses_the_same_day_draws_for_both_kinds():
    """The real kind is the coin's noise plus a steady +0.5% a day: because the draws are shared the difference is clear, however noisy the days."""
    rng = np.random.default_rng(2)
    coin = list(rng.normal(0.0, 0.06, 15))
    real = [c + 0.005 for c in coin]
    d, _a, _b = run({"-fq": real, "-fqc": coin})
    e = by(d)["-fq"]["edge_vs_coin"]
    assert e["status"] == "ok" and e["diff"] > 0.05 and e["lo"] > 0 and e["hi"] >= e["diff"] >= e["lo"] and e["zero_in_interval"] is False
    assert e["p_real_beats_coin"] > 0.99 and e["coin_reaches_real_median"] < 0.5
    assert e["real_median"] == by(d)["-fq"]["percentiles"]["p50"] and e["coin_median"] == by(d)["-fqc"]["percentiles"]["p50"]
    assert e["diff"] == pytest.approx(e["real_median"] - e["coin_median"], abs=1e-4) and e["ci_level"] == 0.9
    # a certain edge: the coin earns nothing, the real kind +2% a day, no noise -> one point
    d, _a, _b = run({"-fq": flat(0.02), "-fqc": flat(0.0)})
    e = by(d)["-fq"]["edge_vs_coin"]
    assert e["diff"] == pytest.approx(1.02 ** 30 - 1, abs=1e-3) and e["lo"] == pytest.approx(e["diff"], abs=1e-3) and e["hi"] == pytest.approx(e["diff"], abs=1e-3)
    assert e["coin_reaches_real_median"] == 0.0 and e["p_real_beats_coin"] == 1.0


def test_edge_interval_is_wide_with_few_noisy_days():
    rng = np.random.default_rng(3)
    d, _a, _b = run({"-fq": list(rng.normal(0.0, 0.08, 10)), "-fqc": list(rng.normal(0.0, 0.08, 10))})
    e = by(d)["-fq"]["edge_vs_coin"]
    assert e["hi"] - e["lo"] > 0.3 and e["zero_in_interval"] is True                       # ten noisy days cannot tell a real kind from its coin


def test_edge_needs_both_kinds_and_the_real_kind_keeps_its_own_numbers():
    d, _a, _b = run({"-fq": flat(0.01)}, extra=[("-fqc", "core", flat(0.01, 3))])           # the coin twin has only three days
    k, c = by(d)["-fq"], by(d)["-fqc"]
    assert k["status"] == "ok" and c["status"] == "few" and k["edge_vs_coin"] == {"status": "few"} and c["percentiles"] is None
    assert d["headline_ko"].endswith("입니다.") and "동전 짝은" not in d["headline_ko"]


def test_pair_draws_come_from_the_real_kinds_name():
    # the same series in both kinds of a pair gives the same percentiles (shared draws); another pair's seed differs
    r = [0.05, -0.04, 0.02, -0.06, 0.07, -0.01, 0.03, -0.05, 0.04, 0.0]
    d, _a, _b = run({"-fq": r, "-fqc": r, "-ld": r, "-ldc": r})
    k = by(d)
    assert k["-fq"]["percentiles"] == k["-fqc"]["percentiles"] and k["-ld"]["percentiles"] == k["-ldc"]["percentiles"]
    assert k["-fq"]["percentiles"] != k["-ld"]["percentiles"]
    assert MS._seed("monthsim-v1", "-fq") == int(hashlib.sha256(b"monthsim-v1|-fq").hexdigest()[:8], 16) != MS._seed("monthsim-v1", "-ld")


# ---------------------------------------------------------------- single accounts
def test_single_account_is_the_cross_section_of_the_accounts_own_scaled_multiples():
    rets = [flat(0.01), flat(0.0), flat(-0.01)]
    d, _a, _b = run({"-fq": rets})
    s = by(d)["-fq"]["single_account"]
    want = np.array([1.01 ** 30, 1.0, 0.99 ** 30])                                  # ln multiple x 30 / 10 days, each account on its own
    assert s["n"] == 3 and s["days"] == 10
    assert (s["p05"], s["p50"], s["p95"]) == pytest.approx(tuple(np.percentile(want, [5, 50, 95])), abs=1e-3)
    assert (s["min"], s["max"]) == pytest.approx((0.99 ** 30, 1.01 ** 30), abs=1e-3)
    # the basket of the three is flat (the mean of +1%, 0, -1%) but the single accounts are far apart: that is the point of the line
    k = by(d)["-fq"]
    assert k["percentiles"]["p05"] == pytest.approx(k["percentiles"]["p95"], abs=2e-3) and s["max"] - s["min"] > 0.5
    # accounts that never traded are not in it; a kind with too little data has none
    assert by(run({"-fq": flat(0.01, 3)})[0])["-fq"]["single_account"] is None


def test_single_account_is_not_a_mix_of_accounts():
    """Account A earns on the first five days and B on the last five. A day-by-day pick of 'a random account' would mix them; the block must
    report only each account's own total."""
    a = [0.02] * 5 + [0.0] * 5
    b = [0.0] * 5 + [0.02] * 5
    s = by(run({"-fq": [a, b]})[0])["-fq"]["single_account"]
    assert s["n"] == 2 and s["min"] == pytest.approx(1.02 ** 15, abs=1e-3) and s["max"] == pytest.approx(s["min"], abs=1e-9)     # both end at their own 1.02^5, scaled x3


# ---------------------------------------------------------------- determinism and safety
def test_same_data_same_numbers_whatever_the_clock_hour():
    rng = np.random.default_rng(9)
    series = {s: list(rng.normal(0.004, 0.03, 12)) for s in SUFFIXES}
    accts, book = world(series)
    a = MS.monthsim_views(book, accts, LU, T0, at(12, 1), False, EQ)
    b = MS.monthsim_views(book, accts, LU, T0, at(12, 20), False, EQ)                 # a different hour of the same day: the same window
    c = MS.monthsim_views(book, accts, LU, T0, at(12, 1), False, EQ)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) == json.dumps(c, sort_keys=True)
    # the book's order of trades does not matter (days are binned, not walked)
    shuffled = {k: list(reversed(v)) for k, v in book.items()}
    assert json.dumps(MS.monthsim_views(shuffled, accts, LU, T0, at(12, 1), False, EQ), sort_keys=True) == json.dumps(a, sort_keys=True)


def test_json_safe_with_odd_trades_and_a_busted_account():
    rng = np.random.default_rng(5)
    accts, book = world({"-fq": [list(rng.normal(0.01, 0.03, 12)) for _ in range(3)], "-fqc": list(rng.normal(0, 0.03, 12))})
    bad = [{"exit_time": None, "pnl": 5.0}, {"exit_time": at(2), "pnl": None}, {"exit_time": float("nan"), "pnl": 1.0}, {"exit_time": at(3), "pnl": float("inf")},
           {"exit_time": "x", "pnl": 3.0}, {"pnl": 1.0}, {"exit_time": at(4, 1)}]
    book[accts[0]["id"]] = bad + book[accts[0]["id"]]
    accts.append({"id": "core-W-1h-1-fq", "pick": "core-W", "role": "fq", "kind": "core"})     # an account that lost everything on day 2
    book["core-W-1h-1-fq"] = [{"exit_time": at(0, 3), "pnl": 10.0}, {"exit_time": at(2, 3), "pnl": -1010.0}, {"exit_time": at(5, 3), "pnl": 40.0}]
    d = MS.monthsim_views(book, accts, LU, T0, at(12, 5), False, EQ)
    k = by(d)["-fq"]
    assert k["status"] == "ok" and k["n_accounts"] == 4 and k["single_account"]["min"] == 0.0 and all(math.isfinite(v) for v in k["percentiles"].values())
    text = json.dumps(d, allow_nan=False)
    assert "NaN" not in text and "Infinity" not in text
    # a trade with a missing pnl is not counted, a hand-made string is not a number
    assert k["n_trades"] == 3 * 36 + 3                                                  # three accounts of 12 days x 3 trades, plus the busted one's three
    # an empty book / no accounts
    d = MS.monthsim_views({}, [], LU, T0, at(20), False, EQ)
    assert all(k["status"] == "none" and k["n_trades"] == 0 and k["observed_multiple"] is None for k in d["kinds"]) and d["window_days"] == 20
    json.dumps(d, allow_nan=False)


def test_the_default_start_wallet_is_the_leagues():
    from candleague import exits as X
    accts, book = world({"-fq": flat(0.0, 3)})
    assert MS.monthsim_views(book, accts, LU, T0, at(3, 12))["equity0"] == float(X.start_equity())
    assert MS.monthsim_views(book, accts, LU, T0, at(3, 12), False, 0)["equity0"] == float(X.start_equity())      # an unusable value falls back


# ---------------------------------------------------------------- DeepSeek money (D11)
def ds_world(scale):
    """A core account and a DeepSeek one in every kind, both with the same days; the DeepSeek returns are ``scale`` times larger."""
    base = [0.01, -0.02, 0.03, 0.0, 0.015, -0.01, 0.02, 0.01, -0.005, 0.02]
    series = {s: list(base) for s in SUFFIXES}
    extra = [(s, "ds", [x * scale for x in base]) for s in SUFFIXES]
    return series, extra


def test_deepseek_money_is_left_out_and_in():
    s1, e1 = ds_world(1.0)
    s5, e5 = ds_world(5.0)
    off1, off5 = run(s1, extra=e1, ds_money=False)[0], run(s5, extra=e5, ds_money=False)[0]
    assert json.dumps(off1, sort_keys=True) == json.dumps(off5, sort_keys=True)          # nothing of a DeepSeek P&L or count reaches the block
    assert off1["ds_in_stats"] is False and by(off1)["-fq"]["n_accounts"] == 1 and by(off1)["-fq"]["n_trades"] == 30
    alone = run(s1, ds_money=False)[0]
    assert json.dumps(alone, sort_keys=True) == json.dumps(off1, sort_keys=True)          # exactly the core-only block
    on1, on5 = run(s1, extra=e1, ds_money=True)[0], run(s5, extra=e5, ds_money=True)[0]
    assert on1["ds_in_stats"] is True and by(on1)["-fq"]["n_accounts"] == 2 and by(on1)["-fq"]["n_trades"] == 60
    assert json.dumps(on1, sort_keys=True) != json.dumps(on5, sort_keys=True)
    assert by(on5)["-fq"]["observed_multiple"] > by(on1)["-fq"]["observed_multiple"]      # the DeepSeek account is in the mean
    # a league of DeepSeek picks only, switch off: no account of any kind
    accts, book = world({}, e1)
    only = MS.monthsim_views(book, accts, LU, T0, at(10, 12), False, EQ)
    assert all(k["status"] == "none" and k["n_trades"] == 0 and k["n_accounts"] == 0 for k in only["kinds"]) and only["headline_ko"] == "아직 자료가 없습니다."
    # the hidden block is the core-only block, so no DeepSeek P&L can be in it
    assert json.dumps(off5, sort_keys=True) == json.dumps(alone, sort_keys=True)


# ---------------------------------------------------------------- performance
def big_world(roles, n_picks, n_trades, seed=7):
    rng = np.random.default_rng(seed)
    accts, book = [], {}
    for p in range(n_picks):
        pick = f"core-S{p}-15m-1"
        exit_ = T0 + np.sort(rng.integers(0, 30 * DAY - H, n_trades)) + H
        for r in roles:
            aid = f"{pick}-{r}"
            accts.append({"id": aid, "pick": pick, "role": r, "kind": "core"})
            pnl = rng.normal(0.2, 8.0, n_trades)
            book[aid] = [{"symbol": "BTCUSDT", "side": 1, "entry_time": int(e) - H, "exit_time": int(e), "roe": float(x) / 100, "pnl": float(x), "exit_reason": "SL"}
                         for e, x in zip(exit_, pnl)]
    return accts, book


def test_about_a_million_trades_in_a_second_or_two():
    roles = ["fq", "nv", "sw", "tg", "iv", "ot", "ld", "ldc", "fqc", "ldt", "ldv", "fqt", "fqv", "ldp", "ld1", "sb", "l5", "l20", "e", "tp10", "gb",
             "ma", "ts", "ch", "oc", "wk"]
    accts, book = big_world(roles, 40, 1000)                                            # 26 kinds x 40 picks x 1000 trades: the whole book
    assert sum(map(len, book.values())) > 1_000_000
    lu = [{"role": r, "suffix": f"-{r}", "label_ko": f"메인 · {r}", "short_ko": r} for r in roles]
    t = time.perf_counter()
    d = MS.monthsim_views(book, accts, lu, T0, T0 + 31 * DAY, False, EQ)
    took = time.perf_counter() - t
    assert took < 6.0, took                                                              # about 0.2 s here; the bound is for slow machines
    assert [k["status"] for k in d["kinds"]] == ["ok"] * 4 and by(d)["-fq"]["n_trades"] == 40_000 and by(d)["-fq"]["edge_vs_coin"]["status"] == "ok"
    # every trade of the four kinds only (the other 22 are never read): the four kinds alone with a million trades
    accts, book = big_world(["fq", "fqc", "ld", "ldc"], 40, 6250)
    assert sum(map(len, book.values())) == 1_000_000
    t = time.perf_counter()
    d = MS.monthsim_views(book, accts, LU, T0, T0 + 31 * DAY, False, EQ)
    took = time.perf_counter() - t
    assert took < 6.0, took
    assert by(d)["-fq"]["n_trades"] == 250_000 and by(d)["-ld"]["status"] == "ok"
    json.dumps(d, allow_nan=False)


# ---------------------------------------------------------------- write_snapshots
def fake_league(tmp_path, owner: bool, name="a.db", ds_scale=1.0):
    """A league with a real trades table: fq and ld on a core and a DeepSeek pick, a few trades on day 0 (the DeepSeek P&L is ``ds_scale`` times larger)."""
    conn = RN.open_db(str(tmp_path / name))
    lu = {r["role"]: r for r in LU}
    accts, book = [], {}
    for pick, kind_, name_, tf in (("core-X-1h-1", "core", "DOGE", "15m"), ("ds-F5_BOX-1h-1", "ds", "F5_BOX", "1h")):
        k = ds_scale if kind_ == "ds" else 1.0
        for role, ts in (("ld", [(1, 2, -10.0), (5, 6, 20.0)]), ("fq", [(1, 3, 10.0), (5, 7, 30.0)])):
            a = {"id": f"{pick}-{role}", "pick": pick, "role": role, "kind": kind_, "name": name_, "tf": tf, "combo": {}, "exit": "ladderU|2",
                 "of": pick, "size": 1.0, "source": {}}
            if owner:
                a["ox"] = {**lu[role], "kind": "x", "desc_ko": "d", "why_ko": "w", "tp": None, "weekend_off": False, "size": 1.0, "rule": None}
            accts.append(a)
            book[a["id"]] = []
            for e, x, pnl in ts:
                t = {"symbol": "BTCUSDT", "side": 1, "entry_time": at(0, e), "exit_time": at(0, x), "roe": pnl / 100, "pnl": pnl * k, "exit_reason": "SL"}
                book[a["id"]].append(t)
                data = {**t, "entry_price": 100.0, "exit_price": 101.0, "leverage": 10, "stop_initial": 99.0, "tp_price": float("nan"), "mae_price": 99.5,
                        "mfe_price": 101.5, "equity_after": 0.0, "margin": 100.0, "context": {}}
                conn.execute("INSERT INTO trades VALUES (?, ?, ?)", (a["id"], t["exit_time"], json.dumps(data)))
    conn.commit()
    engines = {a["id"]: SimpleNamespace(position=None, wallet=RN.EQUITY + sum(t["pnl"] for t in book[a["id"]]), bust=False) for a in accts}
    return SimpleNamespace(conn=conn, accts=accts, engines=engines, done=at(2), start_ms=T0, meta={"started_ms": T0, "notes": []}, advanced_ms=None)


NOW = at(2, 1)


def test_write_snapshots_carries_the_monthsim_in_a_league_with_a_lineup(tmp_path):
    lg = fake_league(tmp_path, True)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=True)
    saved = json.load(open(tmp_path / "snap" / "league.json"))
    assert saved["monthsim"] == doc["monthsim"] and "decision" in saved and "kinds" in saved and "monthsim_error" not in saved        # next to the other keys
    m = saved["monthsim"]
    assert m["equity0"] == RN.EQUITY and m["window_days"] == 2 and m["ds_in_stats"] is True and [k["suffix"] for k in m["kinds"]] == list(SUFFIXES)
    k = {x["suffix"]: x for x in m["kinds"]}
    assert k["-fq"]["status"] == "few" and k["-fq"]["n_trades"] == 4 and k["-fq"]["n_accounts"] == 2 and k["-fq"]["days"] == 1
    assert k["-fq"]["few_ko"] == "아직 자료가 모자랍니다 (1일, 4건 · 7일 · 30건부터)" and k["-fqc"]["status"] == "none"           # the fake league has no coin kinds
    assert k["-fq"]["observed_multiple"] == pytest.approx(1 + (40.0 / RN.EQUITY + 40.0 / RN.EQUITY) / 2, abs=1e-4)
    json.loads(open(tmp_path / "snap" / "league.json").read(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))   # no NaN / Infinity


def test_write_snapshots_monthsim_follows_the_deepseek_switch(tmp_path):
    one, big = fake_league(tmp_path, True, "a.db"), fake_league(tmp_path, True, "b.db", ds_scale=5.0)
    off1 = RN.write_snapshots(str(tmp_path / "s1"), one, NOW, ds_money=False)["monthsim"]
    off5 = RN.write_snapshots(str(tmp_path / "s5"), big, NOW, ds_money=False)["monthsim"]
    assert off1 == off5 and off1["ds_in_stats"] is False and off1["kinds"][0]["n_accounts"] == 1
    on1 = RN.write_snapshots(str(tmp_path / "s1"), one, NOW, ds_money=True)["monthsim"]
    on5 = RN.write_snapshots(str(tmp_path / "s5"), big, NOW, ds_money=True)["monthsim"]
    assert on1["kinds"][0]["n_accounts"] == 2 and on1 != on5


def test_write_snapshots_has_no_monthsim_without_a_lineup(tmp_path):
    lg = fake_league(tmp_path, False)
    assert RX.lineup(lg.accts) is None
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=True)
    saved = json.load(open(tmp_path / "snap" / "league.json"))
    assert "monthsim" not in doc and "monthsim" not in saved and "monthsim_error" not in saved


def test_a_failing_monthsim_never_stops_the_snapshot(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(MS, "monthsim_views", boom)
    lg = fake_league(tmp_path, True)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=True)
    saved = json.load(open(tmp_path / "snap" / "league.json"))
    assert "monthsim" not in saved and saved["monthsim_error"] == "RuntimeError: kaputt" and "decision" in saved and doc["kinds"]
