"""candleague/summary.py decision_views: the pre-registered decision protocol (league.json key ``decision``), on hand-made accounts and trades
(no network).

  * the three tests by hand on tiny examples: 메인 vs 대조 (pairs by symbol + side + entry time, the day as the unit, the halves), a gate
    kind's kept vs dropped trades (and the gate account that is busy at another time), a real kind against its coin twin (paired WITHOUT the side);
  * the day-cluster bootstrap: deterministic (a constant seed), the number of days is the unit, p is never 0;
  * Holm-Bonferroni on a known set, and over the whole family of rows;
  * the verdict rules: few (n < 300), wait (a preview before day 28), pass, fail (each failed condition named), the halves rule;
  * the one-sentence summary, an empty book, a league without lineup, NaN / None ROEs;
  * the DeepSeek money rule (D11) both ways: with ds_money off nothing of a DeepSeek account reaches any number, with it on it does;
  * a performance smoke with about a million trades; write_snapshots carrying the key in a league with a lineup and not otherwise."""

from __future__ import annotations

import json
import os
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from candleague import candidates as C  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague import summary as SM  # noqa: E402

MIN, H, DAY = 60_000, 3_600_000, 86_400_000
T0 = (1_791_000_000_000 // DAY) * DAY                  # a UTC midnight: day d starts at T0 + d * DAY
P1, P2, P3, DS = "core-X-1h-1", "core-Y-1h-1", "core-Z-1h-1", "ds-F5_BOX-1h-1"
KEYS = ("role", "suffix", "label_ko", "group", "test", "n", "mean_diff", "ci_lo", "ci_hi", "p_one_sided", "p_holm", "half1", "half2",
        "same_sign_halves", "verdict", "reason_ko")


def at(day, hour=0, minute=0):
    return T0 + day * DAY + hour * H + minute * MIN


def kind(role, label, short=None):
    return {"role": role, "suffix": f"-{role}", "label_ko": label, "short_ko": short or role}


LU = [kind("fq", "메인 · 구조 확실히 무너지면 빠른 손절 (실전 후보)", "빠른 손절"), kind("nv", "메인 · 매매법 자체 판단", "자체 판단"),
      kind("ld", "대조 · 계단 · 손절 최대 2 ATR", "계단"), kind("ldc", "대조 · 계단 · 동전 던지기", "계단 동전"),
      kind("fqc", "대조 · 메인 빠른 손절의 동전 던지기 짝", "빠른 손절 동전"), kind("ldt", "필터 · 대조에 BTC 추세", "필터 추세"),
      kind("fqt", "필터 · 빠른 손절에 BTC 추세", "빠른 추세"), kind("gb", "큰 수익 반납 보호", "수익 보호")]


def trade(sym, side, entry, exit_, roe):
    return {"symbol": sym, "side": side, "entry_time": entry, "exit_time": exit_, "roe": roe, "pnl": None if roe is None else roe * 100.0,
            "exit_reason": "SL"}


def accts_of(spec, kind_of_pick=None):
    """{pick: [roles]} -> account dicts (a pick whose id starts with 'ds-' is a DeepSeek one)."""
    out = []
    for pick, roles in spec.items():
        for r in roles:
            out.append({"id": f"{pick}-{r}", "pick": pick, "role": r, "kind": "ds" if pick.startswith("ds-") else "core", "name": "X", "tf": "1h"})
    return out


def run(book, spec, now_day=30, ds_money=False, lineup=LU, start=T0):
    return SM.decision_views(book, accts_of(spec), lineup, start, at(now_day), ds_money)


def rows_by(d, test):
    return {r["suffix"]: r for r in d["rows"] if r["test"] == test}


def small(monkeypatch, min_pairs=3):
    monkeypatch.setattr(SM, "DECISION_MIN_PAIRS", min_pairs)


# ---------------------------------------------------------------- (a) 메인 vs 대조 by hand
def main_example():
    """fq against ld on six days. ld ROE / fq ROE: -10 -> 0, 5 -> 25, 10 -> 5, -20 -> -5, 0 -> 10, 20 -> 25 (points of ROE), so the pair
    differences are +10 +20 -5 +15 +10 +5. Not pairs: a different side, a different entry minute, a trade the other kind does not have."""
    ld = [trade("BTCUSDT", 1, at(0, 1), at(0, 3), -0.10), trade("ETHUSDT", 1, at(1, 1), at(1, 3), 0.05), trade("BTCUSDT", -1, at(2, 1), at(2, 3), 0.10),
          trade("BTCUSDT", 1, at(3, 1), at(3, 3), -0.20), trade("SOLUSDT", 1, at(4, 1), at(4, 3), 0.00), trade("BTCUSDT", 1, at(5, 1), at(5, 3), 0.20),
          trade("BTCUSDT", 1, at(6, 1), at(6, 3), 0.50),                       # same coin and time, but the fq trade went short
          trade("BTCUSDT", 1, at(7, 1), at(7, 3), 0.50),                       # the fq trade entered a minute later
          trade("BTCUSDT", 1, at(8, 1), at(8, 3), 0.50)]                       # fq has no trade here
    fq = [trade("BTCUSDT", 1, at(0, 1), at(0, 3), 0.00), trade("ETHUSDT", 1, at(1, 1), at(1, 3), 0.25), trade("BTCUSDT", -1, at(2, 1), at(2, 3), 0.05),
          trade("BTCUSDT", 1, at(3, 1), at(3, 3), -0.05), trade("SOLUSDT", 1, at(4, 1), at(4, 3), 0.10), trade("BTCUSDT", 1, at(5, 1), at(5, 3), 0.25),
          trade("BTCUSDT", -1, at(6, 1), at(6, 3), -0.90), trade("BTCUSDT", 1, at(7, 1, 1), at(7, 3), -0.90),
          trade("ETHUSDT", 1, at(9, 1), at(9, 3), -0.90)]                      # ld has no trade here
    return {f"{P1}-ld": ld, f"{P1}-fq": fq}


def test_main_vs_control_by_hand(monkeypatch):
    small(monkeypatch)
    d = run(main_example(), {P1: ["fq", "ld"]})
    assert set(d) >= {"phase", "days", "checkpoints", "min_pairs", "alpha", "rows", "rules_ko", "summary_ko"}
    assert d["checkpoints"] == {"observe_day": 14, "decide_day": 28} and d["alpha"] == 0.05 and d["phase"] == "decide" and d["days"] == 30
    r = rows_by(d, "main_vs_control")["-fq"]
    assert all(k in r for k in KEYS)
    assert (r["role"], r["label_ko"], r["group"], r["vs_suffix"]) == ("fq", LU[0]["label_ko"], "main", "-ld")
    assert r["n"] == 6 and r["n_days"] == 6                                          # the unmatched trades are not pairs; one pair per UTC day
    assert r["mean_diff"] == pytest.approx(0.55 / 6)                                  # +10 +20 -5 +15 +10 +5 over 6
    assert r["half1"] == pytest.approx(0.25 / 3) and r["half2"] == pytest.approx(0.30 / 3)      # the first three pairs, the last three
    assert r["same_sign_halves"] is True
    assert r["ci_lo"] <= r["mean_diff"] <= r["ci_hi"] and r["ci_lo"] > 0
    assert 1 / (SM.N_BOOT + 1) <= r["p_one_sided"] < 0.02                           # a resample of six days is rarely not positive (it needs the -5 day often)
    assert r["p_holm"] == pytest.approx(min(1.0, len(d["rows"]) * r["p_one_sided"]), abs=1e-5)     # rank 1 of the whole family
    assert r["verdict"] == "pass" and r["reason_ko"].startswith("통과")
    # a main kind without accounts is a row too: nothing to compare, 표본 부족(0/3)
    nv = rows_by(d, "main_vs_control")["-nv"]
    assert (nv["n"], nv["mean_diff"], nv["p_one_sided"], nv["p_holm"], nv["verdict"]) == (0, None, None, None, "few")
    assert nv["reason_ko"] == "표본 부족(0/3)" and nv["same_sign_halves"] is False
    # the control is not tested against itself, a research kind (gb) is not a 메인 kind
    assert "-ld" not in rows_by(d, "main_vs_control") and "-gb" not in rows_by(d, "main_vs_control")


def test_unit_is_the_utc_day_of_the_main_trades_exit(monkeypatch):
    """Two pairs on the same UTC day are one cluster; the control's own exit time does not matter."""
    small(monkeypatch)
    ld, fq = [], []
    for d in range(5):
        for k in range(3):                                                         # three pairs a day, the control exits two days later
            e = at(d, 1, k * 10)
            ld.append(trade("BTCUSDT", 1, e, at(d + 2, 5), 0.0))
            fq.append(trade("BTCUSDT", 1, e, at(d, 3, k * 10), 0.1))
    d = run({f"{P1}-ld": ld, f"{P1}-fq": fq}, {P1: ["fq", "ld"]})
    r = rows_by(d, "main_vs_control")["-fq"]
    assert (r["n"], r["n_days"]) == (15, 5) and r["mean_diff"] == pytest.approx(0.1)
    assert r["p_one_sided"] == pytest.approx(1 / (SM.N_BOOT + 1), abs=1e-6)
    # a pair that crosses midnight (exit at 23:59 vs 00:00) lands on its own day
    ld, fq = [], []
    for k, ex in enumerate((at(0, 23, 59), at(1, 0, 0), at(1, 0, 1), at(2, 12), at(3, 12), at(4, 12))):
        ld.append(trade("BTCUSDT", 1, at(0, k), ex, 0.0))
        fq.append(trade("BTCUSDT", 1, at(0, k), ex, 0.1))
    r = rows_by(run({f"{P1}-ld": ld, f"{P1}-fq": fq}, {P1: ["fq", "ld"]}), "main_vs_control")["-fq"]
    assert (r["n"], r["n_days"]) == (6, 5)


def test_day_cluster_bootstrap_resamples_whole_days():
    """_boot_stats on per-day [sum, count]: every statistic is a mean of whole days, so it stays inside the range of the days' sums."""
    s = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    c = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    v = SM._boot_stats(123, [s, c])
    assert len(v) == SM.N_BOOT and v.min() >= 1.0 and v.max() <= 5.0 and abs(v.mean() - 3.0) < 0.1
    # two days of ten and one trade: a resample is a ratio of sums, not a mean of day means
    s2, c2 = np.array([10.0, 1.0]), np.array([10.0, 1.0])
    assert set(np.unique(np.round(SM._boot_stats(1, [s2, c2]), 9))) == {1.0}
    # the two-group form is mean1 - mean2 inside the same resample
    v = SM._boot_stats(5, [np.array([1.0, 1.0]), np.array([1.0, 1.0]), np.array([0.0, 0.0]), np.array([1.0, 1.0])])
    assert np.allclose(v, 1.0)
    # fewer than DECISION_MIN_DAYS days: no p, no interval
    assert SM._boot_result(1, [s[:4], c[:4]], 4) == (None, None, None)
    lo, hi, p = SM._boot_result(1, [s, c], 5)
    assert 1.0 <= lo <= hi <= 5.0 and p == pytest.approx(1 / (SM.N_BOOT + 1))
    lo, hi, p = SM._boot_result(1, [-s, c], 5)                                      # all days negative: every resample is <= 0
    assert p == 1.0 and hi < 0


def test_bootstrap_is_deterministic_and_does_not_depend_on_the_clock(monkeypatch):
    small(monkeypatch)
    book = main_example()
    a = run(book, {P1: ["fq", "ld"]})
    b = run(book, {P1: ["fq", "ld"]})
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    later = run(book, {P1: ["fq", "ld"]}, now_day=45)                                # another day of the clock: the same numbers
    for x, y in zip(a["rows"], later["rows"]):
        assert {k: v for k, v in x.items() if k not in ("reason_ko",)} == {k: v for k, v in y.items() if k not in ("reason_ko",)}
    reordered = {k: book[k] for k in reversed(list(book))}                           # the book's own order does not matter
    assert json.dumps(run(reordered, {P1: ["fq", "ld"]}), sort_keys=True) == json.dumps(a, sort_keys=True)
    # the seed is a constant string per row: the numbers are the same in another process / run
    assert SM._seed("decision", "main_vs_control", "-fq", "-ld") == SM._seed("decision", "main_vs_control", "-fq", "-ld")
    assert SM._seed("decision", "main_vs_control", "-fq", "-ld") != SM._seed("decision", "vs_coin", "-fq", "-fqc")
    json.dumps(a, allow_nan=False)                                                   # strict JSON: no NaN, no Infinity


# ---------------------------------------------------------------- (b) a gate kind: kept vs dropped
def filter_example():
    """P1: ld took six trades, the gate kind ldt the first, second and fifth (+ one trade of its own that ld did not take: ld was busy).
    P2: ldt exists and took nothing, so both of ld's trades are dropped. P3: no ldt account, its ld trade is not used.
    kept ROE .10 .20 .30 (mean .20); dropped -.10 -.20 .00 | .50 -.10 (mean .02); the difference is .18."""
    ld1 = [trade("BTCUSDT", 1, at(0, 1), at(0, 3), 0.10), trade("BTCUSDT", 1, at(1, 1), at(1, 3), 0.20), trade("BTCUSDT", -1, at(2, 1), at(2, 3), -0.10),
           trade("BTCUSDT", 1, at(3, 1), at(3, 3), -0.20), trade("ETHUSDT", 1, at(4, 1), at(4, 3), 0.30), trade("BTCUSDT", 1, at(5, 1), at(5, 3), 0.00)]
    ldt1 = [ld1[0], ld1[1], ld1[4], trade("BTCUSDT", 1, at(9, 1), at(9, 3), 0.90)]
    ld2 = [trade("BTCUSDT", 1, at(6, 1), at(6, 3), 0.50), trade("BTCUSDT", 1, at(7, 1), at(7, 3), -0.10)]
    ld3 = [trade("BTCUSDT", 1, at(8, 1), at(8, 3), 5.00)]
    fq1 = [trade("BTCUSDT", 1, at(0, 1), at(0, 3), 0.40), trade("BTCUSDT", 1, at(1, 1), at(1, 3), -0.40)]
    fqt1 = [fq1[0]]
    return {f"{P1}-ld": ld1, f"{P1}-ldt": ldt1, f"{P2}-ld": ld2, f"{P2}-ldt": [], f"{P3}-ld": ld3, f"{P1}-fq": fq1, f"{P1}-fqt": fqt1}


SPEC_F = {P1: ["ld", "ldt", "fq", "fqt"], P2: ["ld", "ldt"], P3: ["ld"]}


def test_filter_kept_vs_dropped_by_hand(monkeypatch):
    small(monkeypatch)
    d = run(filter_example(), SPEC_F)
    f = rows_by(d, "filter_kept_vs_dropped")
    assert list(f) == ["-ldt", "-fqt"]                                              # every gate kind (label starts 필터), in the lineup's order
    r = f["-ldt"]
    assert (r["vs_suffix"], r["group"]) == ("-ld", "research")
    assert (r["n_kept"], r["n_dropped"], r["n"]) == (3, 5, 3)                       # n is the smaller group
    assert r["mean_kept"] == pytest.approx(0.20) and r["mean_dropped"] == pytest.approx(0.02) and r["mean_diff"] == pytest.approx(0.18)
    assert r["n_days"] == 8
    # the halves cut the eight trades by exit time: days 0-3 (kept .10 .20, dropped -.10 -.20), days 4-7 (kept .30, dropped 0 .50 -.10)
    assert r["half1"] == pytest.approx(0.15 - (-0.15)) and r["half2"] == pytest.approx(0.30 - 0.4 / 3)
    assert r["same_sign_halves"] is True
    assert "근사 비교" in r["reason_ko"] and "다른 때 포지션 중" in r["reason_ko"]       # the gate account can be busy at another time
    # the fq gate kind is compared with the fq kind
    q = f["-fqt"]
    assert q["vs_suffix"] == "-fq" and (q["n_kept"], q["n_dropped"], q["n"]) == (1, 1, 1) and q["mean_diff"] == pytest.approx(0.80)
    assert q["half1"] is None and q["half2"] is None and q["same_sign_halves"] is False       # each half holds only kept or only dropped
    assert q["verdict"] == "few" and q["reason_ko"].startswith("표본 부족(1/3)")
    # p comes from the day-cluster bootstrap of the difference of two means
    assert 0 < r["p_one_sided"] <= 1 and r["ci_lo"] < r["mean_diff"] < r["ci_hi"]


def test_filter_without_one_side_has_no_difference(monkeypatch):
    small(monkeypatch)
    book = {f"{P1}-ld": [trade("BTCUSDT", 1, at(i, 1), at(i, 3), 0.1) for i in range(6)]}
    book[f"{P1}-ldt"] = list(book[f"{P1}-ld"])                                       # the gate kept everything: nothing dropped
    r = rows_by(run(book, {P1: ["ld", "ldt"]}), "filter_kept_vs_dropped")["-ldt"]
    assert (r["n_kept"], r["n_dropped"], r["n"], r["mean_diff"], r["p_one_sided"], r["half1"]) == (6, 0, 0, None, None, None)
    assert r["verdict"] == "few"
    book[f"{P1}-ldt"] = []                                                           # the gate took nothing: all dropped
    r = rows_by(run(book, {P1: ["ld", "ldt"]}), "filter_kept_vs_dropped")["-ldt"]
    assert (r["n_kept"], r["n_dropped"], r["mean_diff"]) == (0, 6, None) and r["mean_dropped"] == pytest.approx(0.1)


def test_a_label_that_starts_with_the_filter_word_is_a_gate_kind(monkeypatch):
    small(monkeypatch)
    lu = LU + [kind("zz", "필터 · 새 필터", "새 필터"), kind("ldv", "필터 · 대조에 변동성", "변동성")]
    ld = [trade("BTCUSDT", 1, at(i, 1), at(i, 3), 0.1 * i) for i in range(6)]
    book = {f"{P1}-ld": ld, f"{P1}-ldv": ld[:3], f"{P1}-zz": ld[:2]}
    f = rows_by(run(book, {P1: ["ld", "ldv", "zz"]}, lineup=lu), "filter_kept_vs_dropped")
    assert list(f) == ["-ldt", "-fqt", "-zz", "-ldv"]
    assert f["-ldv"]["vs_suffix"] == "-ld" and (f["-ldv"]["n_kept"], f["-ldv"]["n_dropped"]) == (3, 3)
    assert f["-zz"]["vs_suffix"] == "-ld"                                           # no kind "-z": the control


# ---------------------------------------------------------------- (c) against the coin twin
def coin_example():
    """fq vs fqc: entries match on (pick, symbol, entry time) WITHOUT the side. Differences +.40 +.10 | +.20 -.10 0, one coin trade a minute
    off, one unmatched fq trade."""
    fq = [trade("BTCUSDT", 1, at(0, 1), at(0, 3), 0.30), trade("ETHUSDT", -1, at(1, 1), at(1, 3), -0.20), trade("BTCUSDT", 1, at(2, 1), at(2, 3), 0.10),
          trade("BTCUSDT", 1, at(3, 1), at(3, 3), 0.25), trade("SOLUSDT", 1, at(4, 1), at(4, 3), 0.00), trade("BTCUSDT", 1, at(5, 1), at(5, 3), 0.15),
          trade("BTCUSDT", 1, at(6, 1), at(6, 3), 0.80)]
    fqc = [trade("BTCUSDT", -1, at(0, 1), at(0, 3), -0.10), trade("ETHUSDT", 1, at(1, 1), at(1, 3), -0.30), trade("BTCUSDT", 1, at(2, 1, 1), at(2, 3), 0.99),
           trade("BTCUSDT", -1, at(3, 1), at(3, 3), 0.05), trade("SOLUSDT", 1, at(4, 1), at(4, 3), 0.10), trade("BTCUSDT", -1, at(5, 1), at(5, 3), 0.15)]
    ld = [trade("BTCUSDT", 1, at(i, 1), at(i, 3), 0.1) for i in range(6)]
    ldc = [trade("BTCUSDT", -1, at(i, 1), at(i, 3), 0.1 if i % 2 else 0.3) for i in range(6)]
    return {f"{P1}-fq": fq, f"{P1}-fqc": fqc, f"{P1}-ld": ld, f"{P1}-ldc": ldc}


def test_vs_coin_pairs_without_the_side(monkeypatch):
    small(monkeypatch)
    d = run(coin_example(), {P1: ["fq", "fqc", "ld", "ldc"]})
    c = rows_by(d, "vs_coin")
    assert list(c) == ["-fq", "-ld"] and [c[k]["vs_suffix"] for k in c] == ["-fqc", "-ldc"]
    r = c["-fq"]
    assert r["n"] == 5 and r["n_days"] == 5
    assert r["mean_diff"] == pytest.approx(0.12)                                    # (.40 + .10 + .20 - .10 + 0) / 5
    assert r["half1"] == pytest.approx(0.25) and r["half2"] == pytest.approx(0.10 / 3) and r["same_sign_halves"] is True
    assert (r["role"], r["group"], r["label_ko"]) == ("fq", "main", LU[0]["label_ko"])
    # -ld vs -ldc: six pairs, differences -.2 0 -.2 0 -.2 0
    q = c["-ld"]
    assert q["n"] == 6 and q["mean_diff"] == pytest.approx(-0.1) and q["verdict"] == "fail" and q["same_sign_halves"] is False
    assert q["group"] == "control" and q["p_one_sided"] > 0.5
    assert "진입 방향" not in q["reason_ko"] or q["reason_ko"].startswith("실패")
    # matched WITH the side (the main-vs-control key) the same trades would give one pair only: the coin twin differs in the side by design
    book = coin_example()
    with_side = {(t["symbol"], t["side"], t["entry_time"]) for t in book[f"{P1}-fqc"]} & {(t["symbol"], t["side"], t["entry_time"]) for t in book[f"{P1}-fq"]}
    assert len(with_side) == 1 and r["n"] == 5


def test_vs_coin_rows_exist_only_when_both_kinds_are_in_the_lineup(monkeypatch):
    small(monkeypatch)
    lu = [k for k in LU if k["suffix"] != "-fqc"]
    c = rows_by(run(coin_example(), {P1: ["fq", "ld", "ldc"]}, lineup=lu), "vs_coin")
    assert list(c) == ["-ld"]
    lu = [k for k in LU if k["suffix"] not in ("-fqc", "-ldc")]
    assert rows_by(run(coin_example(), {P1: ["fq", "ld"]}, lineup=lu), "vs_coin") == {}


# ---------------------------------------------------------------- Holm
def test_holm_on_a_known_set():
    assert SM.holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])     # 4x .005, 3x .01, 2x .03, then max(.06, 1x .04)
    assert SM.holm([0.5, 0.6]) == [1.0, 1.0]                                                   # capped at 1
    assert SM.holm([0.02, 0.02]) == pytest.approx([0.04, 0.04])
    assert SM.holm([0.001]) == [0.001] and SM.holm([]) == []
    adj = SM.holm([0.0005, 0.011, 0.012, 0.2, 0.9])
    assert adj == pytest.approx([0.0025, 0.044, 0.044, 0.4, 0.9]) and adj == sorted(adj)       # non-decreasing in the p order
    assert all(a >= p for a, p in zip(adj, [0.0005, 0.011, 0.012, 0.2, 0.9]))


def test_holm_is_one_family_over_all_rows(monkeypatch):
    small(monkeypatch)
    book = {**main_example(), **{k: v for k, v in filter_example().items() if not k.startswith(P1 + "-fq") and k != f"{P1}-ld"},
            **{k: v for k, v in coin_example().items() if k.endswith(("-fqc", "-ldc"))}}
    book[f"{P1}-ld"] = main_example()[f"{P1}-ld"]
    d = run(book, {P1: ["fq", "ld", "ldt", "fqc", "ldc"], P2: ["ld", "ldt"], P3: ["ld"]})
    rows = d["rows"]
    assert {r["test"] for r in rows} == set(SM.TESTS) and d["n_tests"] == len(rows)
    ps = [1.0 if r["p_one_sided"] is None else r["p_one_sided"] for r in rows]
    want = SM.holm(ps)
    got = [r["p_holm"] for r in rows]
    for g, w, r in zip(got, want, rows):
        assert (g is None) if r["p_one_sided"] is None else g == pytest.approx(w, abs=1e-5)
    assert sum(r["p_one_sided"] is None for r in rows) >= 2                       # rows without a p still count in the family (as 1)
    assert all(r["p_holm"] >= r["p_one_sided"] for r in rows if r["p_holm"] is not None)


# ---------------------------------------------------------------- verdicts
def bulk(day_diffs, per_day=10, ctl=0.0):
    """fq / ld pairs: on day d, ``per_day`` pairs whose ROE differs by day_diffs[d]."""
    ld, fq = [], []
    for d, x in enumerate(day_diffs):
        for k in range(per_day):
            e = at(d, 1, k)
            ld.append(trade("BTCUSDT", 1, e, at(d, 5, k), ctl))
            fq.append(trade("BTCUSDT", 1, e, at(d, 5, k), ctl + x))
    return {f"{P1}-ld": ld, f"{P1}-fq": fq}


def verdict_of(day_diffs, now_day, per_day=10):
    d = run(bulk(day_diffs, per_day), {P1: ["fq", "ld"]}, now_day=now_day)
    return d, rows_by(d, "main_vs_control")["-fq"]


def test_few_when_under_300_pairs_in_either_phase():
    for now in (10, 20, 40):
        d, r = verdict_of([0.05] * 29, now, per_day=10)                              # 290 pairs
        assert (r["n"], r["verdict"], r["reason_ko"]) == (290, "few", "표본 부족(290/300)"), now
    d, r = verdict_of([0.05] * 30, 40)
    assert r["n"] == 300 and r["verdict"] == "pass"                                  # 300 is enough


def test_wait_before_day_28_is_a_preview_never_pass_or_fail():
    for now, phase in ((0, "observe"), (14, "observe"), (27, "observe")):
        d, r = verdict_of([0.05] * 30, now)
        assert d["phase"] == phase == "observe" and r["verdict"] == "wait" and "미리보기" in r["reason_ko"] and "28일째" in r["reason_ko"], now
        assert not any(x["verdict"] in ("pass", "fail") for x in d["rows"])
        assert d["summary_ko"] == f"아직 판정 시점이 아닙니다 ({now}일째, 28일째에 판정)"
        assert d["counts"]["pass"] == d["counts"]["fail"] == 0
    d, r = verdict_of([-0.05] * 30, 20)                                              # even a clear loser is only "wait" before day 28
    assert r["verdict"] == "wait"
    d, r = verdict_of([0.05] * 30, 28)                                               # day 28 is the decision day
    assert d["phase"] == "decide" and r["verdict"] == "pass"


def test_pass_needs_every_condition_and_fail_names_the_failed_ones():
    d, r = verdict_of([0.05] * 30, 30)
    assert r["verdict"] == "pass" and r["p_holm"] < 0.05 and r["mean_diff"] > 0 and r["same_sign_halves"] is True
    assert r["reason_ko"].startswith("통과: 300쌍, 평균 차이 +5.0%p, 우연 보정 후 p=") and "앞 절반 +5.0%p · 뒤 절반 +5.0%p" in r["reason_ko"]
    # the mean is negative: fail, and the reason says so
    d, r = verdict_of([-0.02] * 30, 30)
    assert r["verdict"] == "fail" and "평균 차이가 플러스가 아님(−2.0%p)" in r["reason_ko"] and r["reason_ko"].startswith("실패")
    assert d["counts"]["fail"] >= 1
    # the mean is exactly zero: not a pass
    d, r = verdict_of([0.0] * 30, 30)
    assert r["verdict"] == "fail" and "플러스가 아님" in r["reason_ko"] and r["p_one_sided"] == 1.0
    # positive mean, but the second half is negative: only the halves rule fails
    d, r = verdict_of([0.08] * 15 + [-0.01] * 15, 30)
    assert r["mean_diff"] == pytest.approx(0.035) and r["p_holm"] < 0.05 and r["half1"] == pytest.approx(0.08) and r["half2"] == pytest.approx(-0.01)
    assert r["same_sign_halves"] is False and r["verdict"] == "fail"
    assert "앞 절반(+8.0%p)과 뒤 절반(−1.0%p) 중 플러스가 아닌 쪽이 있음" in r["reason_ko"]
    assert "평균 차이" not in r["reason_ko"] and "우연 보정" not in r["reason_ko"]
    # and the other way round (the second half carries it)
    d, r = verdict_of([-0.01] * 15 + [0.08] * 15, 30)
    assert r["verdict"] == "fail" and r["same_sign_halves"] is False and r["half1"] < 0 < r["half2"]
    # positive in both halves, but a few lucky days: the corrected p is too large and the reason names it
    wobble = [0.30 if i % 2 == 0 else -0.25 for i in range(30)]
    d, r = verdict_of(wobble, 30)
    assert r["mean_diff"] > 0 and r["half1"] > 0 and r["half2"] > 0 and r["same_sign_halves"] is True
    assert r["p_holm"] >= 0.05 and r["verdict"] == "fail" and "우연 보정 후 p=" in r["reason_ko"] and "0.05보다 작아야 통과" in r["reason_ko"]
    assert "평균 차이가 플러스가 아님" not in r["reason_ko"] and "절반" not in r["reason_ko"]
    # several conditions at once are all named in the one sentence
    d, r = verdict_of([-0.30 if i % 2 == 0 else 0.25 for i in range(30)], 30)
    assert r["verdict"] == "fail" and "플러스가 아님" in r["reason_ko"] and "우연 보정" in r["reason_ko"] and r["reason_ko"].count("실패") == 1


def test_too_few_days_cannot_give_a_p_value():
    d = run(bulk([0.05] * 3, per_day=100), {P1: ["fq", "ld"]}, now_day=30)           # 300 pairs on only three days
    r = rows_by(d, "main_vs_control")["-fq"]
    assert (r["n"], r["n_days"], r["p_one_sided"], r["p_holm"], r["ci_lo"]) == (300, 3, None, None, None)
    assert r["verdict"] == "fail" and "거래가 있는 날이 5일보다 적어" in r["reason_ko"]
    d = run(bulk([0.05] * 3, per_day=100), {P1: ["fq", "ld"]}, now_day=20)
    assert rows_by(d, "main_vs_control")["-fq"]["verdict"] == "wait"


def test_halves_are_split_by_exit_time_whatever_the_input_order(monkeypatch):
    small(monkeypatch)
    book = main_example()
    shuffled = {k: [v[i] for i in (4, 0, 8, 2, 6, 1, 7, 3, 5)] for k, v in book.items()}
    a = rows_by(run(book, {P1: ["fq", "ld"]}), "main_vs_control")["-fq"]
    b = rows_by(run(shuffled, {P1: ["fq", "ld"]}), "main_vs_control")["-fq"]
    assert (a["half1"], a["half2"], a["mean_diff"]) == (b["half1"], b["half2"], b["mean_diff"])
    # odd counts: the second half has the extra pair; one pair has no halves to compare
    five = {k: v[:5] for k, v in book.items()}
    r = rows_by(run(five, {P1: ["fq", "ld"]}), "main_vs_control")["-fq"]
    assert r["n"] == 5 and r["half1"] == pytest.approx(0.30 / 2) and r["half2"] == pytest.approx(0.20 / 3)
    one = {k: v[:1] for k, v in book.items()}
    r = rows_by(run(one, {P1: ["fq", "ld"]}), "main_vs_control")["-fq"]
    assert r["n"] == 1 and r["half1"] is None and r["same_sign_halves"] is False


# ---------------------------------------------------------------- the summary sentence, empty and odd inputs
def test_summary_sentences():
    assert verdict_of([0.05] * 30, 5)[0]["summary_ko"] == "아직 판정 시점이 아닙니다 (5일째, 28일째에 판정)"
    d, _r = verdict_of([-0.05] * 30, 30)
    assert d["summary_ko"].startswith("통과한 것 0개: 새 구조에서 우위를 찾지 못했습니다") and d["counts"]["pass"] == 0
    d, r = verdict_of([0.05] * 30, 30)
    assert d["counts"]["pass"] == 1 and d["summary_ko"].startswith("통과 1개: 메인 1개(빠른 손절)가 대조를 이겼습니다")
    assert "표본 부족" in d["summary_ko"]                                              # the other rows have no pairs
    d = run({}, {P1: ["fq", "ld"]}, now_day=30)
    assert "표본이 모자라" in d["summary_ko"] and d["counts"]["few"] == d["n_tests"] > 0
    assert d["summary_ko"].count("0개") == 0                                         # honest: not "found nothing", but "could not judge"
    # only the coin test passes: no claim about the new structure
    book = {f"{P1}-ld": [trade("BTCUSDT", 1, at(d_, 1, k), at(d_, 5, k), 0.10) for d_ in range(30) for k in range(10)]}
    book[f"{P1}-ldc"] = [trade("BTCUSDT", -1, t["entry_time"], t["exit_time"], 0.0) for t in book[f"{P1}-ld"]]
    d = run(book, {P1: ["ld", "ldc"]}, now_day=30)
    assert d["counts"]["pass"] == 1 and "방향 실력 1개(계단)가 동전 던지기를 이겼습니다" in d["summary_ko"]
    assert "새 구조(메인)에서는 우위를 찾지 못했습니다" in d["summary_ko"]
    # the rules are in the block, short and plain, with the numbers of the constants
    rules = d["rules_ko"]
    assert len(rules) == 6 and rules == SM.decision_rules_ko()
    text = "\n".join(rules)
    for need in ("거래당 순수익 차이", "같은 날 거래는 묶어서 계산", "우연 보정", "28일째 한 번만 판정", "300개 이상", "0.05보다", "앞 절반과 뒤 절반", "우위 없음", "실전에 쓰지 않습니다"):
        assert need in text, need


def test_empty_inputs_and_odd_trades():
    d = SM.decision_views({}, [], None, None, None, False)
    assert d["rows"] == [] and d["phase"] == "observe" and d["days"] == 0 and d["n_tests"] == 0
    assert d["summary_ko"] == "아직 판정 시점이 아닙니다 (0일째, 28일째에 판정)"
    d = run({}, {P1: ["fq", "ld", "ldt", "fqc", "ldc"]}, now_day=3)
    assert all(r["n"] == 0 and r["verdict"] == "few" and r["p_one_sided"] is None and r["mean_diff"] is None for r in d["rows"])
    assert all(r["reason_ko"].startswith("표본 부족(0/300)") for r in d["rows"])
    json.dumps(d, allow_nan=False)
    # None / NaN ROE and a missing exit time never reach a number; days are counted from the start (a clock before the start is day 0)
    ld = [trade("BTCUSDT", 1, at(i, 1), at(i, 3), 0.0) for i in range(8)]
    fq = [trade("BTCUSDT", 1, at(i, 1), at(i, 3), 0.1) for i in range(8)]
    fq[0]["roe"] = None
    fq[1]["roe"] = float("nan")
    fq[2]["exit_time"] = None
    ld[3]["roe"] = float("inf")
    d = run({f"{P1}-ld": ld, f"{P1}-fq": fq}, {P1: ["fq", "ld"]}, now_day=-5)
    r = rows_by(d, "main_vs_control")["-fq"]
    assert d["days"] == 0 and r["n"] == 4 and r["mean_diff"] == pytest.approx(0.1)
    json.dumps(d, allow_nan=False)
    # a trade without the key fields is skipped, not an error
    bad = {f"{P1}-ld": [{"roe": 0.1, "exit_time": at(0, 3)}], f"{P1}-fq": [{"roe": 0.2, "exit_time": at(0, 3)}]}
    assert rows_by(run(bad, {P1: ["fq", "ld"]}), "main_vs_control")["-fq"]["n"] == 1
    # an account that is not in the lineup (an old role) is ignored; the input is not modified
    book = main_example()
    keep = json.dumps(book, sort_keys=True)
    run(book, {P1: ["fq", "ld", "old"]})
    assert json.dumps(book, sort_keys=True) == keep


def test_the_real_lineup_has_a_row_per_tested_kind():
    """The league's real kinds (candleague/data/rules_owner_exits.json): the rows follow its labels, whatever the file holds."""
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json"), encoding="utf-8"))
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, RX.normalize_owner(doc))
    lu = RX.lineup(accts)
    d = SM.decision_views({}, accts, lu, T0, at(3), False)
    sfx = {k["suffix"] for k in lu}
    mains = [k["suffix"] for k in lu if SM.kind_group(k["label_ko"]) == "main" and k["suffix"] != "-ld"]
    gates = [k["suffix"] for k in lu if k["suffix"] in SM.GATE_SUFFIXES or k["label_ko"].startswith("필터")]
    coins = [r for r, c in SM.COIN_TWINS if r in sfx and c in sfx]
    got = {t: [r["suffix"] for r in d["rows"] if r["test"] == t] for t in SM.TESTS}
    assert got["main_vs_control"] == mains and got["filter_kept_vs_dropped"] == gates and got["vs_coin"] == coins
    assert len(mains) >= 4 and len(gates) >= 4 and len(coins) == 2
    assert len(d["rows"]) == d["n_tests"] and d["phase"] == "observe" and d["days"] == 3
    # and with trades: every gate kind compares with the right ungated kind
    vs = {r["suffix"]: r["vs_suffix"] for r in d["rows"] if r["test"] == "filter_kept_vs_dropped"}
    assert vs.get("-ldt") == "-ld" and vs.get("-ldv") == "-ld" and vs.get("-fqt") == "-fq" and vs.get("-fqv") == "-fq"


# ---------------------------------------------------------------- DeepSeek money (D11)
def ds_book(scale):
    """P1 (core) and DS (DeepSeek) both trade fq and ld on the same six days; the DeepSeek ROE is ``scale`` times larger."""
    book = {}
    for pick, k in ((P1, 1.0), (DS, scale)):
        ld = [trade("BTCUSDT", 1, at(i, 1), at(i, 3), 0.05 * k) for i in range(6)]
        fq = [trade("BTCUSDT", 1, at(i, 1), at(i, 3), (0.05 + 0.02 * (i + 1)) * k) for i in range(6)]
        coin = [trade("BTCUSDT", -1, at(i, 1), at(i, 3), -0.01 * k) for i in range(6)]
        book.update({f"{pick}-ld": ld, f"{pick}-fq": fq, f"{pick}-fqc": coin, f"{pick}-ldt": ld[:3]})
    return book


def test_deepseek_money_is_left_out_and_in(monkeypatch):
    small(monkeypatch)
    spec = {P1: ["fq", "ld", "fqc", "ldt"], DS: ["fq", "ld", "fqc", "ldt"]}
    off1 = run(ds_book(1.0), spec, ds_money=False)
    off5 = run(ds_book(5.0), spec, ds_money=False)
    assert json.dumps(off1, sort_keys=True) == json.dumps(off5, sort_keys=True)       # nothing of a DeepSeek ROE or count reaches the block
    assert off1["ds_in_stats"] is False
    assert rows_by(off1, "main_vs_control")["-fq"]["n"] == 6                          # the core pick's pairs only
    assert rows_by(off1, "vs_coin")["-fq"]["n"] == 6 and rows_by(off1, "filter_kept_vs_dropped")["-ldt"]["n_kept"] == 3
    on1 = run(ds_book(1.0), spec, ds_money=True)
    on5 = run(ds_book(5.0), spec, ds_money=True)
    assert on1["ds_in_stats"] is True and json.dumps(on1, sort_keys=True) != json.dumps(on5, sort_keys=True)
    assert rows_by(on1, "main_vs_control")["-fq"]["n"] == 12 and rows_by(on1, "filter_kept_vs_dropped")["-ldt"]["n_kept"] == 6
    assert rows_by(on1, "main_vs_control")["-fq"]["mean_diff"] == pytest.approx(0.07)  # both picks, the same ROE (scale 1): (.07 mean) each
    assert rows_by(on5, "main_vs_control")["-fq"]["mean_diff"] == pytest.approx((0.07 + 0.35) / 2)
    # a league of DeepSeek picks only, switch off: no pair at all
    only = run(ds_book(1.0), {DS: ["fq", "ld", "fqc", "ldt"]}, ds_money=False)
    assert all(r["n"] == 0 and r["mean_diff"] is None for r in only["rows"]) and only["counts"]["few"] == only["n_tests"]
    # the sentence and the reasons carry no figure of a hidden pick (they are made from the core rows)
    assert str(0.35) not in json.dumps(off5)


# ---------------------------------------------------------------- performance
def test_about_a_million_trades_in_a_few_seconds():
    roles = ["fq", "nv", "sw", "tg", "iv", "ot", "ld", "ldc", "fqc", "ldt", "ldv", "fqt", "fqv", "ldp", "ld1", "sb", "l5", "l20", "e", "tp10", "gb",
             "ma", "ts", "ch", "oc", "wk"]
    labels = {"fq": "메인", "nv": "메인", "sw": "메인", "tg": "메인", "iv": "메인", "ot": "메인", "ldt": "필터", "ldv": "필터", "fqt": "필터", "fqv": "필터"}
    lu = [kind(r, f"{labels.get(r, '대조' if r.startswith('ld') or r == 'fqc' else '연구')} · {r}") for r in roles]
    rng = np.random.default_rng(7)
    n_picks, n_trades = 40, 1000
    accts, book = [], {}
    for p in range(n_picks):
        pick = f"core-S{p}-15m-1"
        entry = T0 + np.arange(n_trades, dtype=np.int64) * 2 * H + p * MIN
        base = rng.normal(0, 0.1, n_trades)
        side = np.where(rng.random(n_trades) < 0.5, 1, -1)
        for r in roles:
            accts.append({"id": f"{pick}-{r}", "pick": pick, "role": r, "kind": "core"})
            idx = np.nonzero(rng.random(n_trades) < 0.6)[0] if r in ("ldt", "ldv", "fqt", "fqv") else np.arange(n_trades)
            roe = base + rng.normal(0, 0.05, n_trades)
            book[f"{pick}-{r}"] = [{"symbol": "BTCUSDT", "side": int(side[i]), "entry_time": int(entry[i]), "exit_time": int(entry[i]) + H,
                                    "roe": float(roe[i]), "pnl": float(roe[i]) * 100, "exit_reason": "SL"} for i in idx]
    total = sum(map(len, book.values()))
    assert total > 900_000
    t = time.perf_counter()
    d = SM.decision_views(book, accts, lu, T0, T0 + 30 * DAY, False)
    took = time.perf_counter() - t
    assert took < 8.0, took                                                           # about 0.6 s here; the bound is for slow machines
    assert d["n_tests"] == 12 and all(r["n"] > 10_000 for r in d["rows"])
    assert d["phase"] == "decide" and all(r["verdict"] in ("pass", "fail") for r in d["rows"])


# ---------------------------------------------------------------- write_snapshots
def fake_league(tmp_path, owner: bool, name="a.db", ds_scale=1.0):
    """A league with a real trades table: fq (메인) and ld (대조) on a core and a DeepSeek pick; the DeepSeek ROE is ``ds_scale`` times larger.
    ld: 1h-2h -10%, 5h-6h +20%; fq: the same entries, 1h-3h +10%, 5h-7h +30% (so the differences are +20 and +10 points)."""
    conn = RN.open_db(str(tmp_path / name))
    lu = {r["role"]: r for r in LU}
    accts, book = [], {}
    for pick, kind_, name_, tf in ((P1, "core", "DOGE", "15m"), (DS, "ds", "F5_BOX", "1h")):
        k = ds_scale if kind_ == "ds" else 1.0
        for role, ts in (("ld", [(1, 2, -0.10), (5, 6, 0.20)]), ("fq", [(1, 3, 0.10), (5, 7, 0.30)])):
            a = {"id": f"{pick}-{role}", "pick": pick, "role": role, "kind": kind_, "name": name_, "tf": tf, "combo": {}, "exit": "ladderU|2",
                 "of": pick, "size": 1.0, "source": {}}
            if owner:
                a["ox"] = {**lu[role], "kind": "x", "desc_ko": "d", "why_ko": "w", "tp": None, "weekend_off": False, "size": 1.0, "rule": None}
            accts.append(a)
            book[a["id"]] = []
            for e, x, roe in ts:
                t = trade("BTCUSDT", 1, T0 + e * H, T0 + x * H, roe * k)
                book[a["id"]].append(t)
                data = {**t, "entry_price": 100.0, "exit_price": 101.0, "leverage": 10, "stop_initial": 99.0, "tp_price": float("nan"), "mae_price": 99.5,
                        "mfe_price": 101.5, "equity_after": 0.0, "margin": 100.0, "context": {}}
                conn.execute("INSERT INTO trades VALUES (?, ?, ?)", (a["id"], t["exit_time"], json.dumps(data)))
    conn.commit()
    engines = {a["id"]: SimpleNamespace(position=None, wallet=RN.EQUITY + sum(t["pnl"] for t in book[a["id"]]), bust=False) for a in accts}
    return SimpleNamespace(conn=conn, accts=accts, engines=engines, done=T0 + 2 * DAY, start_ms=T0, meta={"started_ms": T0, "notes": []}, advanced_ms=None)


NOW = T0 + 2 * DAY + MIN


def test_write_snapshots_carries_the_decision_in_a_league_with_a_lineup(tmp_path):
    lg = fake_league(tmp_path, True)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=True)
    saved = json.load(open(tmp_path / "snap" / "league.json"))
    assert saved["decision"] == doc["decision"] and "kinds" in saved and "pairs" in saved               # next to the other owner-league keys
    d = saved["decision"]
    assert d["phase"] == "observe" and d["days"] == 2 and d["checkpoints"] == {"observe_day": 14, "decide_day": 28} and d["min_pairs"] == 300
    assert [r["suffix"] for r in d["rows"]] == ["-fq"] and d["rows"][0]["test"] == "main_vs_control"
    r = d["rows"][0]
    assert r["n"] == 4 and r["mean_diff"] == pytest.approx(0.15) and r["verdict"] == "few" and r["reason_ko"] == "표본 부족(4/300)"
    assert d["ds_in_stats"] is True and d["summary_ko"] == "아직 판정 시점이 아닙니다 (2일째, 28일째에 판정)"
    json.loads(open(tmp_path / "snap" / "league.json").read(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))   # no NaN / Infinity
    # the day count is the engine's processed time (a league that is still catching up is not on day 30 yet)
    lg.done = T0 + 30 * DAY
    assert RN.write_snapshots(str(tmp_path / "snap2"), lg, NOW, ds_money=True)["decision"]["phase"] == "decide"


def test_write_snapshots_decision_follows_the_deepseek_switch(tmp_path):
    one, big = fake_league(tmp_path, True, "a.db"), fake_league(tmp_path, True, "b.db", ds_scale=5.0)
    off1 = RN.write_snapshots(str(tmp_path / "s1"), one, NOW, ds_money=False)["decision"]
    off5 = RN.write_snapshots(str(tmp_path / "s5"), big, NOW, ds_money=False)["decision"]
    assert off1 == off5 and off1["rows"][0]["n"] == 2 and off1["ds_in_stats"] is False
    on1 = RN.write_snapshots(str(tmp_path / "s1"), one, NOW, ds_money=True)["decision"]
    on5 = RN.write_snapshots(str(tmp_path / "s5"), big, NOW, ds_money=True)["decision"]
    assert on1["rows"][0]["n"] == 4 and on1 != on5


def test_write_snapshots_has_no_decision_without_a_lineup(tmp_path):
    lg = fake_league(tmp_path, False)
    assert RX.lineup(lg.accts) is None
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=True)
    saved = json.load(open(tmp_path / "snap" / "league.json"))
    assert "decision" not in doc and "decision" not in saved
