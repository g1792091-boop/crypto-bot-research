"""candleague 조건별 성적 (the exploratory look at WHERE a structure works), server side: the entry stamps ``g1`` / ``g2`` that
rulex.chunk_rule writes into every signal's ctx, runner.condition_trades that reads them back from the stored trades of four kinds, and
summary.conditions_views (league.json key ``conditions``). Hand-made accounts and trades, synthetic bars, no network.

  * the stamps: g1 (BTC 4h trend alignment of the side actually traded) and g2 (ATR% percentile in the 20-80% band) as True / False / None,
    equal to the gate helpers' yes / no, causal (a later BTC bar changes nothing), written for every account of a group that has gate data and
    omitted when it has none (and then nothing extra is loaded), in the stored trade; no entry, stop, size or the account fingerprint depends on
    them; after a restart in the middle of the run the stamps are identical;
  * the buckets by hand and against a plain Python reference: weekday / weekend (Sat-Sun UTC), session by the ENTRY time, side, coin, chart
    timeframe, BTC trend, volatility, hold time (the edges), n / wins / win rate / mean ROE per kind, the few rule (n < 30: no mean),
    the difference to the coin twin in the same bucket with its day-cluster interval (deterministic), the counts (n_cells, expected_lucky,
    good / bad), the sentence (counts and the biggest gap with its n, no recommendation), JSON without NaN;
  * DeepSeek money (D11) both ways, the reader sees only the four kinds' accounts, a missing kind, unusable rows, a million trades quickly;
  * runner.condition_trades on a real trades table (SQL path = json.loads path) and write_snapshots carrying the key in a league with a lineup
    only, never stopping the snapshot."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_rulex as TR  # noqa: E402  (synthetic bars, the league's replay, synthetic strategies)
import test_candleague_user_ladder as UL  # noqa: E402  (the lineup document)
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague import summary as SM  # noqa: E402

H, DAY = 3_600_000, 86_400_000
MIN = 60_000
T0 = (1_791_000_000_000 // DAY) * DAY                  # a UTC Monday midnight? checked below: day d starts at T0 + d * DAY
KINDS = ("-fq", "-fqc", "-ld", "-ldc")
LU = [{"role": s[1:], "suffix": s, "label_ko": lab, "short_ko": sh} for s, lab, sh in (
    ("-fq", "메인 · 구조 확실히 무너지면 빠른 손절 (실전 후보)", "빠른 손절"), ("-ld", "대조 · 계단 · 손절 최대 2 ATR", "계단"),
    ("-ldc", "대조 · 계단 · 동전 던지기", "동전"), ("-fqc", "대조 · 메인 빠른 손절의 동전 던지기 짝", "동전"),
    ("-nv", "메인 · 매매법 자체 판단", "자체 판단"))]
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def at(day, hour=0, minute=0):
    return T0 + day * DAY + hour * H + minute * MIN


def weekday_of(ms):
    return ((ms // DAY) + 3) % 7                         # 0 = Monday


def test_the_fixture_day_zero_is_a_known_weekday():
    assert weekday_of(T0) in range(7)                    # the tests below never rely on which one: they use weekday_of


def acct(pick, role, tf="1h", kind="core"):
    return {"id": f"{pick}-{role}", "pick": pick, "role": role, "kind": kind, "name": "X", "tf": tf}


def accounts(picks=(("core-A-1h-1", "1h", "core"),), kinds=("fq", "fqc", "ld", "ldc")):
    return [acct(p, r, tf, kind) for p, tf, kind in picks for r in kinds]


def row(sym, side, entry, hold_h, roe, g1=None, g2=None):
    return (sym, side, int(entry), int(entry + hold_h * H), roe, g1, g2)


def views(book, accts=None, now_day=20, ds_money=False, lineup=LU):
    return SM.conditions_views(book, accts if accts is not None else accounts(), lineup, T0, at(now_day), ds_money)


def bucket(d, dim, bid):
    dm = next(x for x in d["dims"] if x["id"] == dim)
    return next(b for b in dm["buckets"] if b["id"] == bid)


# ---------------------------------------------------------------- the dimensions against a plain Python reference
def classify(r, tf):
    """The buckets of one row in plain Python, written independently of the vectorised code."""
    sym, side, entry, ext, roe, g1, g2 = r
    wd = weekday_of(entry) >= 5
    hour = (entry % DAY) // H
    hold = (ext - entry) / H
    return {"weekday": "weekend" if wd else "weekday", "session": ("asia", "europe", "us")[hour // 8], "side": "long" if side > 0 else "short",
            "coin": sym[:-4].lower(), "tf": tf, "g1": "with" if g1 is True or g1 == 1 else "against" if g1 is False or g1 == 0 else "unknown",
            "g2": "normal" if g2 is True or g2 == 1 else "odd" if g2 is False or g2 == 0 else "unknown",
            "hold": "h0" if hold < 1 else "h1" if hold < 4 else "h2" if hold <= 18 else "h3"}


def random_world(seed=3, n=500, days=20, picks=(("core-A-1h-1", "1h", "core"), ("core-B-15m-1", "15m", "core"), ("core-C-4h-1", "4h", "core"))):
    rng = np.random.default_rng(seed)
    accts = accounts(picks)
    book, tfs = {}, {}
    for a in accts:
        tfs[a["id"]] = a["tf"]
        ent = T0 + rng.integers(0, days * 1440, n) * MIN
        hold = rng.integers(1, 1500, n) / 60.0
        book[a["id"]] = [(str(rng.choice(COINS)), int(rng.choice([1, -1])), int(e), int(e + h * H), float(rng.normal(0.002, 0.05)),
                          [True, False, None, 1, 0][int(rng.integers(0, 5))], [True, False, None][int(rng.integers(0, 3))])
                         for e, h in zip(ent, hold)]
    return accts, book, tfs


def test_every_bucket_matches_a_plain_python_count():
    accts, book, tfs = random_world()
    d = views(book, accts)
    ref: dict = {}
    for a in accts:
        sfx = "-" + a["role"]
        for r in book[a["id"]]:
            for dim, b in classify(r, tfs[a["id"]]).items():
                c = ref.setdefault((dim, b, sfx), [0, 0, 0.0])
                c[0] += 1
                c[1] += r[4] > 0
                c[2] += r[4]
    seen = 0
    for dim in d["dims"]:
        for b in dim["buckets"]:
            for sfx, cell in b["kinds"].items():
                n, w, t = ref.get((dim["id"], b["id"], sfx), [0, 0, 0.0])
                assert (cell["n"], cell["wins"]) == (n, w), (dim["id"], b["id"], sfx)
                assert cell["few"] is (n < 30)
                if n >= 30:
                    assert cell["mean"] == pytest.approx(t / n, abs=1e-7) and cell["win_rate"] == pytest.approx(w / n, abs=1e-4)
                else:
                    assert cell["mean"] is None and cell["win_rate"] is None
                seen += 1
    assert seen > 80
    # every reference bucket with trades is in the output (an empty bucket is left out)
    out = {(dim["id"], b["id"]) for dim in d["dims"] for b in dim["buckets"]}
    assert {(k[0], k[1]) for k in ref} == out
    # the differences: real - twin in the same bucket, only when both have 30
    for dim in d["dims"]:
        for b in dim["buckets"]:
            for real, twin in (("-fq", "-fqc"), ("-ld", "-ldc")):
                x, y = b["kinds"][real], b["kinds"][twin]
                df = b["diffs"][real]
                assert (df["n"], df["n_twin"]) == (x["n"], y["n"])
                if x["n"] >= 30 and y["n"] >= 30:
                    assert df["few"] is False and df["diff"] == pytest.approx(x["mean"] - y["mean"], abs=2e-7)
                else:
                    assert df["few"] is True and df["diff"] is None and df["lo"] is None and df["flag"] is None
    assert [x["id"] for x in d["dims"]] == ["weekday", "session", "side", "coin", "tf", "g1", "g2", "hold"]
    assert [x["ko"] for x in d["dims"]] == ["요일", "시간대", "방향", "코인", "봉", "BTC 추세", "변동성", "보유시간"]
    assert [b["ko"] for b in bucket_list(d, "tf")] == ["15m", "1h", "4h"]                       # the chart lengths in their natural order, only those present
    assert [b["ko"] for b in bucket_list(d, "coin")] == sorted((b["ko"] for b in bucket_list(d, "coin")), key=lambda c: -sum(
        k["n"] for bb in bucket_list(d, "coin") if bb["ko"] == c for k in bb["kinds"].values()))


def bucket_list(d, dim):
    return next(x for x in d["dims"] if x["id"] == dim)["buckets"]


def day_with(weekday):
    return next(dd for dd in range(1, 8) if weekday_of(at(dd)) == weekday)


def test_the_edges_of_weekday_session_and_hold_time():
    fri = day_with(4)
    tue = day_with(1)
    rows = [row("BTCUSDT", 1, at(fri, 23, 59), 2, 0.01), row("BTCUSDT", 1, at(fri + 1), 2, 0.01), row("BTCUSDT", 1, at(fri + 2, 23, 59), 2, 0.01),
            row("BTCUSDT", 1, at(fri + 3), 2, 0.01)]                                      # Fri 23:59 weekday, Sat 00:00 weekend, Sun 23:59 weekend, Mon 00:00 weekday
    d = views({"core-A-1h-1-fq": rows})
    assert {b["id"]: b["kinds"]["-fq"]["n"] for b in bucket_list(d, "weekday")} == {"weekday": 2, "weekend": 2}
    assert [classify(r, "1h")["weekday"] for r in rows] == ["weekday", "weekend", "weekend", "weekday"]
    rows = [row("BTCUSDT", 1, at(tue, 7, 59), 2, 0.01), row("BTCUSDT", 1, at(tue, 8), 2, 0.01),                  # 07:59 asia, 08:00 europe
            row("BTCUSDT", 1, at(tue, 15, 59), 2, 0.01), row("BTCUSDT", 1, at(tue, 16), 2, 0.01),                # 15:59 europe, 16:00 us
            row("BTCUSDT", 1, at(tue), 2, 0.01), row("BTCUSDT", 1, at(tue, 23, 59), 2, 0.01)]                    # 00:00 asia, 23:59 us
    d = views({"core-A-1h-1-fq": rows})
    assert {b["id"]: b["kinds"]["-fq"]["n"] for b in bucket_list(d, "session")} == {"asia": 2, "europe": 2, "us": 2}
    assert [classify(r, "1h")["session"] for r in rows] == ["asia", "europe", "europe", "us", "asia", "us"]
    assert [b["ko"] for b in bucket_list(d, "session")] == ["아시아", "유럽", "미국"]
    # hold time: < 1 h, 1-4 h, 4-18 h (18 h itself), over 18 h
    start = at(tue, 12)
    holds = {"h0": [0.999], "h1": [1.0, 3.999], "h2": [4.0, 18.0], "h3": [18.0 + 1 / 3600]}
    rows = [row("BTCUSDT", 1, start, h, 0.01) for hs in holds.values() for h in hs]
    d = views({"core-A-1h-1-fq": rows})
    got = {b["id"]: b["kinds"]["-fq"]["n"] for b in bucket_list(d, "hold")}
    assert got == {k: len(v) for k, v in holds.items()}
    assert next(x for x in d["dims"] if x["id"] == "hold")["after_entry"] is True                  # known only after the entry: said so
    assert all(not x["after_entry"] for x in d["dims"] if x["id"] != "hold")


def test_the_session_and_weekday_follow_the_entry_not_the_exit():
    sat = day_with(5)
    rows = [row("BTCUSDT", 1, at(sat - 1, 23, 30), 3, 0.01)]                           # enters Friday 23:30, exits Saturday 02:30
    d = views({"core-A-1h-1-fq": rows})
    assert bucket(d, "weekday", "weekday")["kinds"]["-fq"]["n"] == 1 and bucket(d, "session", "us")["kinds"]["-fq"]["n"] == 1
    assert not any(b["id"] == "weekend" for b in bucket_list(d, "weekday"))


def test_btc_trend_and_volatility_buckets_read_the_stamps_with_unknown():
    rows = [row("BTCUSDT", 1, at(1, h), 2, 0.01, g1, g2) for h, (g1, g2) in enumerate(
        [(True, True), (True, False), (False, None), (None, True), (1, 0), (0, 1), (None, None)])]
    d = views({"core-A-1h-1-fq": rows})
    g1 = {b["id"]: b["kinds"]["-fq"]["n"] for b in bucket_list(d, "g1")}
    g2 = {b["id"]: b["kinds"]["-fq"]["n"] for b in bucket_list(d, "g2")}
    assert g1 == {"with": 3, "against": 2, "unknown": 2} and g2 == {"normal": 3, "odd": 2, "unknown": 2}
    assert [b["ko"] for b in bucket_list(d, "g1")] == ["일치", "불일치", "모름"] and [b["ko"] for b in bucket_list(d, "g2")] == ["보통", "아님", "모름"]
    assert [b["unknown"] for b in bucket_list(d, "g1")] == [False, False, True]
    # trades from before the stamps existed (None everywhere): one unknown bucket, nothing else
    old = views({"core-A-1h-1-fq": [row("BTCUSDT", 1, at(1, h), 2, 0.01) for h in range(5)]})
    assert [b["id"] for b in bucket_list(old, "g1")] == ["unknown"] and [b["id"] for b in bucket_list(old, "g2")] == ["unknown"]


# ---------------------------------------------------------------- few, differences, the interval, the counts
def paired_book(n_days=12, per_day=4, gap=0.05, twin_noise=0.0, picks=(("core-A-1h-1", "1h", "core"),), seed=1):
    """-fq = -fqc + gap on every signal (the same coin and entry time), and -ld = -ldc: the pairs share their day."""
    rng = np.random.default_rng(seed)
    book = {}
    for pick, _tf, _k in picks:
        for dd in range(n_days):
            for j in range(per_day):
                e = at(dd) + (30 + j * (1380 // per_day)) * MIN                                   # spread over the day, never into the next
                base = float(rng.normal(0, 0.03)) if twin_noise else 0.0
                sym = COINS[j % 3]
                book.setdefault(f"{pick}-fqc", []).append(row(sym, 1, e, 2, base))
                book.setdefault(f"{pick}-fq", []).append(row(sym, 1, e, 2, base + gap))
                book.setdefault(f"{pick}-ldc", []).append(row(sym, -1, e, 2, base))
                book.setdefault(f"{pick}-ld", []).append(row(sym, -1, e, 2, base))
    return book


def test_a_bucket_under_30_trades_is_few_and_shows_no_mean():
    book = paired_book(n_days=7, per_day=4)                        # 28 trades per kind
    d = views(book)
    cell = bucket(d, "weekday", "weekday")["kinds"]["-fq"], bucket(d, "weekday", "weekend")["kinds"]["-fq"]
    for c in cell:
        assert c["few"] is True and c["mean"] is None and c["win_rate"] is None and c["n"] > 0 and c["wins"] is not None
    assert d["n_cells"] == 0 and "아직 칸마다 비교할 만큼 거래가 쌓이지 않았습니다" in d["headline_ko"]
    book = paired_book(n_days=8, per_day=4)                        # 32 trades per kind: the single-bucket dimension 'tf' has 32 >= 30
    d = views(book)
    one = bucket(d, "tf", "1h")
    assert one["kinds"]["-fq"]["n"] == 32 and one["kinds"]["-fq"]["few"] is False and one["kinds"]["-fq"]["mean"] == pytest.approx(0.05)
    # exactly 29 and 30 in a bucket, and a twin short of 30 makes the difference few
    for n, few in ((29, True), (30, False)):
        d = views({"core-A-1h-1-fq": [row("BTCUSDT", 1, at(1, 1) + i * MIN, 1, 0.01) for i in range(n)],
                   "core-A-1h-1-fqc": [row("BTCUSDT", 1, at(1, 1) + i * MIN, 1, 0.0) for i in range(30)]})
        c = bucket(d, "tf", "1h")
        assert c["kinds"]["-fq"]["few"] is few and (c["kinds"]["-fq"]["mean"] is None) is few
        assert c["diffs"]["-fq"]["few"] is few and (c["diffs"]["-fq"]["diff"] is None) is few
        assert c["kinds"]["-fqc"]["few"] is False


def test_the_difference_to_the_coin_twin_and_its_day_cluster_interval():
    d = views(paired_book(n_days=12, per_day=4, gap=0.05, twin_noise=1.0), now_day=12)
    for dim in d["dims"]:
        for b in dim["buckets"]:
            df = b["diffs"]["-fq"]
            if not df["few"] and not b["unknown"]:
                assert df["diff"] == pytest.approx(0.05, abs=1e-6)                    # the same signals, +5 points exactly: no noise in the difference
                assert df["lo"] == pytest.approx(0.05, abs=1e-6) and df["hi"] == pytest.approx(0.05, abs=1e-6) and df["flag"] == "good"
    # the control has no effect over its twin: the interval holds 0, no flag
    ld = [b["diffs"]["-ld"] for dim in d["dims"] for b in dim["buckets"] if not b["diffs"]["-ld"]["few"] and not b["unknown"]]
    assert ld and all(x["diff"] == 0 and x["flag"] is None and x["lo"] <= 0 <= x["hi"] for x in ld)
    # a difference that is noise: the interval is wide and contains it
    rng = np.random.default_rng(5)
    book = {}
    for dd in range(15):
        for j in range(6):
            e = at(dd, 1 + 3 * j)
            book.setdefault("core-A-1h-1-fq", []).append(row("BTCUSDT", 1, e, 2, float(rng.normal(0, 0.05))))
            book.setdefault("core-A-1h-1-fqc", []).append(row("BTCUSDT", 1, e, 2, float(rng.normal(0, 0.05))))
    x = bucket(views(book, now_day=15), "tf", "1h")["diffs"]["-fq"]
    assert x["lo"] < x["diff"] < x["hi"] and x["hi"] - x["lo"] > 0.01
    # under five days no interval and no flag (the difference itself is still shown)
    few_days = views(paired_book(n_days=4, per_day=12, gap=0.05), now_day=4)
    y = bucket(few_days, "tf", "1h")["diffs"]["-fq"]
    assert y["diff"] == pytest.approx(0.05) and y["lo"] is None and y["hi"] is None and y["flag"] is None and few_days["n_days"] == 4


def test_a_clearly_worse_kind_is_flagged_bad_and_the_counts_follow():
    book = paired_book(n_days=12, per_day=8, gap=-0.04, twin_noise=1.0)
    d = views(book, now_day=12)
    assert d["n_good"] == 0 and d["n_bad"] > 0 and d["n_bad"] <= d["n_cells"]
    assert d["expected_lucky"] == round(0.05 * d["n_cells"])
    flags = [b["diffs"]["-fq"]["flag"] for dim in d["dims"] for b in dim["buckets"] if not b["unknown"] and not b["diffs"]["-fq"]["few"]]
    assert flags and set(flags) == {"bad"}
    # n_cells = the differences shown (both pairs, no unknown bucket), n_good / n_bad = the flags among them
    shown = [df for dim in d["dims"] for b in dim["buckets"] if not b["unknown"] for df in b["diffs"].values() if not df["few"]]
    assert d["n_cells"] == len(shown) and d["n_bad"] == sum(x["flag"] == "bad" for x in shown) and d["n_good"] == sum(x["flag"] == "good" for x in shown)


def test_the_sentence_has_the_counts_and_the_biggest_gap_and_no_advice():
    d = views(paired_book(n_days=12, per_day=8, gap=0.05, twin_noise=1.0), now_day=12)
    s = d["headline_ko"]
    assert f"{d['n_cells']}칸 중" in s and f"{d['n_good']}개" in s and f"{d['n_bad']}개" in s and f"{d['expected_lucky']}개쯤" in s
    assert "가장 큰 차이:" in s and "+5.0%p" in s and "거래 " in s and "건 대 " in s
    for word in ("추천", "하세요", "쓰세요", "고르세요", "사세요", "권합니다", "유리", "이기"):
        assert word not in s and word not in d["note_ko"]
    # the caveat sentence says it: exploratory, many cells, luck, never the decision, only for picking the next test
    note = d["note_ko"]
    assert "탐색용" in note and "칸이 많아서 우연히 좋아 보이는 칸이 저절로 생기고" in note and "판정" in note and "쓰지 않고" in note and "다음에 따로 미리 정해서 시험할 것을 고르는 데만" in note
    # the biggest gap is the biggest |difference| among the shown cells
    shown = [(abs(df["diff"]), df["n"], df["n_twin"]) for dim in d["dims"] for b in dim["buckets"] if not b["unknown"] for df in b["diffs"].values() if not df["few"]]
    big = max(shown)
    assert f"거래 {big[1]}건 대 {big[2]}건" in s or any(f"거래 {n}건 대 {m}건" in s for a, n, m in shown if a == big[0])
    # no trades at all
    empty = views({})
    assert empty["headline_ko"] == "아직 닫힌 거래가 없어서 비교할 것이 없습니다" and empty["dims"] == [] and empty["n_cells"] == 0 and empty["n_days"] == 0


def test_the_unknown_bucket_is_no_condition_and_is_not_counted_or_flagged():
    book = paired_book(n_days=12, per_day=8, gap=0.05, twin_noise=1.0)            # every stamp is None: one 'unknown' bucket in g1 and g2
    d = views(book, now_day=12)
    for dim in ("g1", "g2"):
        (b,) = bucket_list(d, dim)
        assert b["unknown"] is True and b["diffs"]["-fq"]["flag"] is None and b["diffs"]["-fq"]["lo"] is None and b["diffs"]["-fq"]["diff"] == pytest.approx(0.05)
    counted = sum(1 for dim in d["dims"] for b in dim["buckets"] if not b["unknown"] for df in b["diffs"].values() if not df["few"])
    assert d["n_cells"] == counted


# ---------------------------------------------------------------- determinism, JSON, DeepSeek, kinds, rows
def test_deterministic_json_safe_and_independent_of_the_order_of_the_accounts():
    accts, book, _ = random_world(seed=9)
    a = views(book, accts)
    b = views(copy.deepcopy(book), list(reversed(accts)))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    json.dumps(a, allow_nan=False)                                              # no NaN / Infinity anywhere
    assert a["boot"] == 2000 and a["ci_level"] == 0.9 and a["min_n"] == 30 and a["min_days"] == 5 and a["days"] == 20
    assert set(a) >= {"days", "n_days", "n_cells", "expected_lucky", "ds_in_stats", "headline_ko", "note_ko", "kinds", "pairs", "dims", "n_good", "n_bad"}
    assert [p["real"] for p in a["pairs"]] == ["-fq", "-ld"] and [k["suffix"] for k in a["kinds"]] == list(KINDS)
    assert [k["role_ko"] for k in a["kinds"]] == ["실전 후보", "동전", "대조", "동전"]
    assert sum(k["n"] for k in a["kinds"]) == sum(len(v) for v in book.values()) and a["n_trades"]["-fq"] == a["kinds"][0]["n"]


def ds_world(scale):
    picks = (("core-A-1h-1", "1h", "core"), ("ds-F5_BOX-1h-1", "1h", "ds"))
    book = paired_book(n_days=12, per_day=8, gap=0.05, twin_noise=1.0, picks=picks)
    for aid in list(book):
        if aid.startswith("ds-"):
            book[aid] = [r[:4] + (r[4] * scale,) + r[5:] for r in book[aid]]
    return accounts(picks), book


def test_deepseek_money_is_left_out_and_in():
    seen = []
    accts, book1 = ds_world(1.0)
    _a, book5 = ds_world(5.0)

    def reader(book):
        def f(ids):
            seen.append(list(ids))
            return {i: book[i] for i in ids if i in book}
        return f
    off1 = views(reader(book1), accts, now_day=12)
    off5 = views(reader(book5), accts, now_day=12)
    assert json.dumps(off1, sort_keys=True) == json.dumps(off5, sort_keys=True) and off1["ds_in_stats"] is False
    assert all(not i.startswith("ds-") for ids in seen[:2] for i in ids) and len(seen[0]) == 4         # the reader never gets a DeepSeek account
    assert SM.conditions_ids(accts, LU, False) == [f"core-A-1h-1-{r}" for r in ("fq", "fqc", "ld", "ldc")]
    assert len(SM.conditions_ids(accts, LU, True)) == 8
    on1 = views(reader(book1), accts, now_day=12, ds_money=True)
    on5 = views(reader(book5), accts, now_day=12, ds_money=True)
    assert on1["ds_in_stats"] is True and json.dumps(on1, sort_keys=True) != json.dumps(on5, sort_keys=True)
    assert on1["n_trades"]["-fq"] == 2 * off1["n_trades"]["-fq"] and len(seen[2]) == 8
    assert str(0.25) not in json.dumps(off5)
    # a league of DeepSeek picks only, switch off: nothing to compare
    only = views(reader(book1), [a for a in accts if a["kind"] == "ds"], now_day=12)
    assert only["dims"] == [] and only["n_cells"] == 0 and sum(only["n_trades"].values()) == 0


def test_a_missing_kind_and_a_league_without_the_kinds():
    book = paired_book(n_days=12, per_day=8, gap=0.05, twin_noise=1.0)
    lu = [k for k in LU if k["suffix"] != "-fqc"]                                  # no coin twin of the quick stop
    d = views(book, accounts(kinds=("fq", "ld", "ldc")), lineup=lu, now_day=12)
    assert [p["real"] for p in d["pairs"]] == ["-ld"] and [k["suffix"] for k in d["kinds"]] == ["-fq", "-ld", "-ldc"]
    b = bucket(d, "tf", "1h")
    assert set(b["kinds"]) == {"-fq", "-ld", "-ldc"} and set(b["diffs"]) == {"-ld"}
    none = SM.conditions_views(book, accounts(kinds=("nv",)), [LU[-1]], T0, at(5))
    assert none["dims"] == [] and none["pairs"] == [] and none["kinds"] == [] and none["headline_ko"].startswith("아직 닫힌 거래가 없어서")
    assert SM.conditions_views({}, [], None, None, None)["days"] == 0


def test_unusable_rows_are_dropped_and_dict_rows_are_read():
    good = [row("BTCUSDT", 1, at(1, 1) + i * MIN, 1, 0.01) for i in range(40)]
    bad = [("BTCUSDT", 0, at(1), at(1) + H, 0.01, None, None), ("BTCUSDT", 1, at(1), at(1) + H, None, None, None),
           ("BTCUSDT", 1, at(1), at(1) + H, float("nan"), None, None), ("BTCUSDT", 1, None, at(1) + H, 0.01, None, None),
           ("BTCUSDT", 1, at(1) + H, at(1), 0.01, None, None)]                       # side 0, no / NaN ROE, no entry time, exit before entry
    d = views({"core-A-1h-1-fq": good + bad})
    assert d["n_trades"]["-fq"] == 40
    as_dict = [dict(zip(SM.COND_FIELDS, r)) for r in good]
    assert json.dumps(views({"core-A-1h-1-fq": as_dict}), sort_keys=True) == json.dumps(views({"core-A-1h-1-fq": good}), sort_keys=True)


def test_a_chart_length_outside_the_four_still_gets_its_bucket():
    accts = [acct("core-A-5m-1", r, "5m") for r in ("fq", "fqc")] + [acct("core-B-1h-1", r, "1h") for r in ("fq", "fqc")]
    book = {a["id"]: [row("BTCUSDT", 1, at(1, 1) + i * MIN, 1, 0.01) for i in range(31)] for a in accts}
    d = views(book, accts)
    assert [b["id"] for b in bucket_list(d, "tf")] == ["1h", "5m"] and sum(b["kinds"]["-fq"]["n"] for b in bucket_list(d, "tf")) == 62


def test_noise_alone_flags_about_the_expected_share_of_cells():
    """Calibration smoke: with no effect anywhere, the cells whose interval lies above 0 are a few percent, not a crowd."""
    tot = good = bad = 0
    for seed in range(12):
        accts, book, _ = random_world(seed=100 + seed, n=300, days=28)
        d = views(book, accts, now_day=28)
        tot, good, bad = tot + d["n_cells"], good + d["n_good"], bad + d["n_bad"]
    assert tot > 400 and 0.01 < good / tot < 0.15 and 0.01 < bad / tot < 0.15


def test_about_a_million_trades_in_about_a_second():
    rng = np.random.default_rng(2)
    n_picks, per = 49, 5100
    accts, book = [], {}
    for p in range(n_picks):
        tf = ("15m", "30m", "1h", "4h")[p % 4]
        for r in ("fq", "fqc", "ld", "ldc"):
            a = acct(f"core-S{p}-{tf}-1", r, tf)
            accts.append(a)
            ent = T0 + rng.integers(0, 400 * 1440, per) * MIN
            ext = ent + rng.integers(1, 1500, per) * MIN
            sym = rng.choice(COINS, per).tolist()
            side = rng.choice([1, -1], per).tolist()
            roe = rng.normal(0, 0.05, per).tolist()
            g1 = rng.choice([True, False, None], per).tolist()
            g2 = rng.choice([True, False, None], per).tolist()
            book[a["id"]] = list(zip(sym, side, ent.tolist(), ext.tolist(), roe, g1, g2))
    assert sum(map(len, book.values())) > 990_000
    t = time.perf_counter()
    d = SM.conditions_views(book, accts, LU, T0, T0 + 400 * DAY, False)
    took = time.perf_counter() - t
    assert took < 8.0, took                                                           # about 1 s here; the bound is for slow machines
    assert d["n_days"] > 300 and d["n_cells"] > 40 and sum(d["n_trades"].values()) > 990_000
    json.dumps(d, allow_nan=False)


# ---------------------------------------------------------------- the stamps in the signals (rulex.chunk_rule) and in the stored trades
def test_the_stamps_are_three_way_facts_equal_to_the_gates_yes_and_no():
    n = 120
    c = np.r_[np.linspace(100, 160, 80), np.linspace(160, 90, 40)]
    t = np.arange(n, dtype=np.int64) * RX.TF_MS["4h"] + RX.TF_MS["4h"]
    ms, sign = RX.gate_g1_arrays(t, c)
    st = lambda close_ms, side: RX.gate_g1_stamp(ms, sign, close_ms, side)                # noqa: E731
    assert st(int(t[70]), 1) is True and st(int(t[70]), -1) is False and st(int(t[-1]), -1) is True and st(int(t[-1]), 1) is False
    assert st(int(t[10]), 1) is None and st(int(t[10]), -1) is None and st(int(t[0]) - 1, 1) is None        # a cold EMA and no bar are unknown, not "against"
    for close_ms in (int(t[0]) - 1, int(t[10]), int(t[70]), int(t[70]) + 1, int(t[-1])):
        for side in (1, -1):
            assert RX.gate_g1(ms, sign, close_ms, side) == (st(close_ms, side) is True)     # the gate is exactly "the stamp is True"
    c2 = c.copy()
    c2[75:] = 1.0                                                                          # the future changes: the stamp at bar 74 does not
    ms2, sign2 = RX.gate_g1_arrays(t, c2)
    assert RX.gate_g1_stamp(ms2, sign2, int(t[74]), 1) == st(int(t[74]), 1)
    w = RX.GATE_WINDOW
    atr = np.linspace(0.001, 0.01, w + 10)
    mid = np.r_[np.linspace(0.001, 0.01, w - 1), [0.0055]]
    assert RX.gate_g2_stamp(atr, w + 5) is False and RX.gate_g2_stamp(atr, w - 2) is None                # the top of its window: outside; window not full: unknown
    assert RX.gate_g2_stamp(mid, w - 1) is True and RX.gate_g2_stamp(np.r_[mid[:-1], [0.0001]], w - 1) is False
    assert RX.gate_g2_stamp(np.r_[mid[:-1], [np.nan]], w - 1) is None
    for arr, i in ((atr, w + 5), (atr, w - 2), (mid, w - 1), (np.r_[mid[:-1], [0.0001]], w - 1), (np.r_[mid[:-1], [np.nan]], w - 1)):
        assert RX.gate_g2(arr, i) == (RX.gate_g2_stamp(arr, i) is True)


def lineup_accounts(gates=("g1", "g2"), coin_twins=True):
    doc = copy.deepcopy(UL.LINEUP)
    doc["owner_exits"] = [e for e in doc["owner_exits"] if e["suffix"] in ("-ld", "-ldc", "-ld2", "-e")]
    for g, sfx in (("g1", "-ldt"), ("g2", "-ldv")):
        if g in gates:
            doc["owner_exits"].append({"suffix": sfx, "exit": "ladderU", "stop_max": 2, "gate": g, "label_ko": f"필터 {g}"})
    return RX.owner_accounts(TR._rule_cands("15m", "tp3R|4"), RX.normalize_owner(doc))


class CountingSource:
    """The league's frame source that remembers what was loaded (to see that the stamps load nothing of their own)."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def load(self, sym, lo, hi):
        self.calls.append((sym, lo, hi))
        return self.inner.load(sym, lo, hi)


def chunk(accts, day0=0, days=1, source=None):
    src = source or TR.PS.FrameSource(TR.DATA)
    return RX.chunk_rule(TR.LIB, src, accts, TR.TP.SYMS, TR.START + day0 * TR.DAY, TR.START + (day0 + days) * TR.DAY, TR.START, TR.StubStrategies())


def signals(by):
    return [(aid, o) for items in by.values() for aid, o in items if isinstance(o, TR.Signal)]


def test_every_signal_of_every_account_carries_the_two_stamps_when_the_group_has_gate_data():
    accts = lineup_accounts()
    assert {a["gate"] for a in accts if a.get("gate")} == {"g1", "g2"} and len(accts) == 6
    by, notes = chunk(accts, days=2)
    sigs = signals(by)
    assert sigs and not notes
    for aid, o in sigs:
        ctx = o.meta["ctx"]
        assert "strength" in ctx and set(ctx) == {"strength", "g1", "g2"}, aid                # every account, not only the gate accounts
        assert ctx["g1"] in (True, False, None) and ctx["g2"] in (True, False, None)
        assert all(v is None or isinstance(v, bool) for v in (ctx["g1"], ctx["g2"]))
    vals = {(k, o.meta["ctx"][k]) for _a, o in sigs for k in ("g1", "g2")}
    assert {("g1", True), ("g1", False), ("g2", True), ("g2", False)} <= vals                 # the synthetic bars do show both states
    # the stamp of the side actually traded: a coin twin flipped to the other side carries that side's g1
    by_key = {}
    for aid, o in sigs:
        by_key.setdefault((o.symbol, o.ts), {})[aid.rsplit("-", 1)[-1]] = o
    flipped = [(v["ld"], v["ldc"]) for v in by_key.values() if "ld" in v and "ldc" in v and v["ld"].side != v["ldc"].side]
    assert flipped
    for real, twin in flipped:
        assert real.meta["ctx"]["g2"] == twin.meta["ctx"]["g2"]                                # ATR% does not depend on the side
    same = [(v["ld"], v["ldc"]) for v in by_key.values() if "ld" in v and "ldc" in v and v["ld"].side == v["ldc"].side]
    assert all(a.meta["ctx"] == b.meta["ctx"] or a.meta["ctx"]["strength"] != b.meta["ctx"]["strength"] for a, b in same)
    # the gate accounts' own decision (meta["gate"]) is what it was: the stamp is True exactly where the gate passed
    for aid, o in sigs:
        if "gate" in o.meta:
            assert o.meta["gate"]["g1"] is (o.meta["ctx"]["g1"] is True) and o.meta["gate"]["g2"] is (o.meta["ctx"]["g2"] is True)


def test_stamps_follow_the_traded_side_and_the_signal_bar_close_without_look_ahead():
    accts = lineup_accounts()
    by, _ = chunk(accts, days=1)
    base = {(aid, o.symbol, o.ts, o.side): dict(o.meta["ctx"]) for aid, o in signals(by)}
    # a longer chunk that ends later reproduces the earlier chunk's stamps exactly
    by3, _ = chunk(accts, days=3)
    longer = {(aid, o.symbol, o.ts, o.side): dict(o.meta["ctx"]) for aid, o in signals(by3)}
    assert all(longer[k] == v for k, v in base.items())
    # every stamp is a function of the closed bars up to the signal close: g1 equals the helper on the BTC 4h chart cut at the signal close
    from paperbot.sigservice import window_5m
    src = TR.PS.FrameSource(TR.DATA)
    cols4 = src.load("BTCUSDT", TR.START - window_5m(TR.LIB, "4h") * RX.FIVE, TR.START + 3 * TR.DAY)
    f4 = RX.rule_frame(TR.LIB, cols4, "4h", TR.START + 3 * TR.DAY)
    ms4 = (f4["ts"].astype("int64") // 1_000_000).to_numpy(np.int64) + RX.TF_MS["4h"]
    g = RX.gate_g1_arrays(ms4, f4["close"].to_numpy(float))
    for (aid, sym, ts, side), ctx in list(longer.items())[:60]:
        assert ctx["g1"] == RX.gate_g1_stamp(g[0], g[1], ts + 1, side)


def test_no_gate_data_no_stamps_and_nothing_extra_is_loaded():
    base_src = CountingSource(TR.PS.FrameSource(TR.DATA))
    plain = lineup_accounts(gates=())
    by, _ = chunk(plain, days=2, source=base_src)
    sigs = signals(by)
    assert sigs and all(set(o.meta["ctx"]) == {"strength"} and "gate" not in o.meta for _a, o in sigs)           # the keys are omitted
    n_plain = len(base_src.calls)
    assert n_plain == len(TR.TP.SYMS)                                                           # one load per coin, nothing else
    # g2 only: ATR% comes from the frames already loaded, so still no extra load; g1 is omitted
    only2 = CountingSource(TR.PS.FrameSource(TR.DATA))
    by, _ = chunk(lineup_accounts(gates=("g2",)), days=2, source=only2)
    assert len(only2.calls) == n_plain
    assert all(set(o.meta["ctx"]) == {"strength", "g2"} for _a, o in signals(by))
    # g1 present: exactly one more load (the BTC 4h chart), the same one the g1 gate account needs anyway
    both = CountingSource(TR.PS.FrameSource(TR.DATA))
    by, _ = chunk(lineup_accounts(gates=("g1",)), days=2, source=both)
    assert len(both.calls) == n_plain + 1 and all(set(o.meta["ctx"]) == {"strength", "g1", "g2"} for _a, o in signals(by))


def test_the_stamps_change_no_entry_stop_size_or_fingerprint():
    accts = lineup_accounts()
    before = copy.deepcopy(accts)
    fp = RN.fingerprint(accts)
    by, _ = chunk(accts, days=2)
    assert accts == before and RN.fingerprint(accts) == fp                                       # the accounts (and so the fingerprint) never see the stamps
    fp_gate = {a["id"]: (a.get("gate"), a["exit"], a["size"], a["rule"]["id"] if a["rule"].get("family") else None) for a in accts}
    assert fp_gate == {a["id"]: (a.get("gate"), a["exit"], a["size"], a["rule"]["id"] if a["rule"].get("family") else None) for a in before}
    # a signal without the stamps (what the code made before) enters exactly the same: strip them and compare the stop distance, ATR, side and gate flags
    for _aid, o in signals(by):
        stripped = {k: v for k, v in o.meta.items() if k != "ctx"}
        assert set(stripped) <= {"stop_dist", "account", "gate", "style", "rx0", "native_inv", "native_tgt", "native_s"}
        assert o.meta["stop_dist"] > 0 and o.atr > 0


def run_league(db, accts, stops, strip=False):
    """A League over the synthetic bars, advanced to each of ``stops`` in turn; a new League object (a restart) over the same file between them."""
    lg = None
    for t in stops:
        lg = RN.League(RN.open_db(str(db)), accts, TR.TP.BRACKETS, TR.TP.SPECS, TR.LIB, TR.PS.FrameSource(TR.DATA), TR.TP._steps_from(TR.DATA),
                       TR.TP.SYMS, start_ms=TR.START, log=lambda s: None, db_path=str(db))
        assert (len(stops) == 1 or t == stops[0]) or not lg.reset                                 # a restart continues, it does not start over
        lg.strategies = TR.StubStrategies()
        if strip:                                                                                 # the signals as they were before the stamps existed
            real = RX.chunk_rule

            def no_stamps(*a, **k):
                by, notes = real(*a, **k)
                for items in by.values():
                    for _aid, o in items:
                        if isinstance(o, TR.Signal):
                            o.meta["ctx"].pop("g1", None)
                            o.meta["ctx"].pop("g2", None)
                return by, notes
            RX_chunk = RX.chunk_rule
            RX.chunk_rule = no_stamps
            try:
                lg.advance(t)
            finally:
                RX.chunk_rule = RX_chunk
        else:
            lg.advance(t)
    return lg


def stored(lg):
    return [(a, json.loads(d)) for a, d in lg.conn.execute("SELECT account, data FROM trades ORDER BY account, exit_time, rowid")]


def test_stored_trades_carry_the_stamps_and_a_restart_gives_identical_ones(tmp_path):
    accts = lineup_accounts()
    end = TR.START + 3 * TR.DAY
    whole = run_league(tmp_path / "w.db", accts, [end])
    a = stored(whole)
    assert len(a) > 50
    stamped = [t for _aid, t in a if "g1" in t["context"]]
    assert len(stamped) == len(a)                                                                # the engine copies ctx into every stored trade
    assert {t["context"]["g1"] for t in stamped} <= {True, False, None} and {t["context"]["g2"] for t in stamped} <= {True, False, None}
    assert {t["context"]["g2"] for t in stamped} == {True, False}
    # restarts at awkward times (a new process on the same database), mid-position included
    pieces = run_league(tmp_path / "p.db", accts, [TR.START + 7 * RN.FIVE, TR.START + 100 * RN.FIVE, TR.START + 250 * RN.FIVE, TR.START + 700 * RN.FIVE, end])
    b = stored(pieces)
    assert [(x, t["entry_time"], t["exit_time"], t["context"]) for x, t in a] == [(x, t["entry_time"], t["exit_time"], t["context"]) for x, t in b]
    assert RN.fingerprint(accts) == whole.meta["fingerprint"] == pieces.meta["fingerprint"]
    # the trades themselves are what they were without any stamp: prices, sizes and P&L of every account
    plain = run_league(tmp_path / "s.db", accts, [end], strip=True)
    c = stored(plain)
    assert not any("g1" in t["context"] for _x, t in c)
    keep = ("symbol", "side", "entry_time", "entry_price", "exit_time", "exit_price", "exit_reason", "qty", "leverage", "margin", "stop_price", "pnl", "roe")
    assert [(x, {k: t[k] for k in keep}) for x, t in a] == [(x, {k: t[k] for k in keep}) for x, t in c]


# ---------------------------------------------------------------- runner.condition_trades and write_snapshots
def conditions_db(tmp_path, name="c.db"):
    conn = RN.open_db(str(tmp_path / name))
    rows = {}
    for aid, ctxs in (("core-A-1h-1-fq", [{"g1": True, "g2": False}, {"g1": False, "g2": None}, {}, None]), ("core-A-1h-1-fqc", [{"g1": None, "g2": True}]),
                      ("core-A-1h-1-nv", [{"g1": True, "g2": True}]), ("ds-F5_BOX-1h-1-fq", [{"g1": True, "g2": True}])):
        for i, ctx in enumerate(ctxs):
            data = {"strategy_id": "S", "symbol": "BTCUSDT" if i % 2 == 0 else "ETHUSDT", "side": 1 if i % 3 else -1, "entry_time": T0 + i * H, "exit_time": T0 + (i + 1) * H,
                    "roe": 0.01 * (i + 1), "pnl": 1.0, "tp_price": float("nan"), "context": ctx if ctx is not None else {}}
            if ctx is None:
                del data["context"]                                                              # a trade written before the context existed at all
            conn.execute("INSERT INTO trades VALUES (?, ?, ?)", (aid, data["exit_time"], json.dumps(data)))
            rows.setdefault(aid, []).append((data["symbol"], data["side"], data["entry_time"], data["exit_time"], data["roe"],
                                             (ctx or {}).get("g1"), (ctx or {}).get("g2")))
    conn.commit()
    return conn, rows


def test_condition_trades_reads_only_the_given_accounts_the_same_way_with_and_without_sql(tmp_path):
    conn, rows = conditions_db(tmp_path)
    ids = ["core-A-1h-1-fq", "core-A-1h-1-fqc", "core-A-1h-1-ld"]
    sql = RN.condition_trades(conn, ids)
    py = RN.condition_trades(conn, ids, sql=False)
    assert set(sql) == set(ids) and set(py) == set(ids) and sql["core-A-1h-1-ld"] == []           # nothing of the nv or the DeepSeek account
    norm = lambda x: {k: [tuple(None if v is None else (bool(v) if i >= 5 else v) for i, v in enumerate(r)) for r in v] for k, v in x.items()}   # noqa: E731
    assert norm(sql) == norm(py) == {k: [tuple(r) for r in rows[k]] for k in ("core-A-1h-1-fq", "core-A-1h-1-fqc")} | {"core-A-1h-1-ld": []}
    assert sql["core-A-1h-1-fq"][0][5] in (True, 1) and sql["core-A-1h-1-fq"][3][5:] == (None, None)      # no context at all: unknown
    # exit order, and a long id list is read in pieces
    many = [f"x{i}" for i in range(900)] + ids
    assert set(RN.condition_trades(conn, many)) == set(many) and len(RN.condition_trades(conn, many)["core-A-1h-1-fq"]) == 4
    # the summary reads the same from either
    accts = accounts()
    d_sql = SM.conditions_views(lambda i: RN.condition_trades(conn, i), accts, LU, T0, at(3))
    d_py = SM.conditions_views(lambda i: RN.condition_trades(conn, i, sql=False), accts, LU, T0, at(3))
    assert json.dumps(d_sql, sort_keys=True) == json.dumps(d_py, sort_keys=True) and d_sql["n_trades"] == {"-fq": 4, "-fqc": 1, "-ld": 0, "-ldc": 0}


def test_condition_trades_falls_back_when_sqlite_cannot_read_a_row(tmp_path):
    conn, _rows = conditions_db(tmp_path)
    conn.execute("INSERT INTO trades VALUES ('core-A-1h-1-ld', ?, ?)", (T0, '{"symbol": "BTCUSDT", "side": 1, "entry_time": 1, "exit_time": 2, "roe": 0.5, "context": {"g1": true}}'))
    conn.commit()
    ok = RN.condition_trades(conn, ["core-A-1h-1-ld"])
    assert len(ok["core-A-1h-1-ld"]) == 1
    # a SQLite without the JSON functions: the same rows through json.loads
    class NoJson:
        def __init__(self, c):
            self.c = c

        def execute(self, sql, *a):
            if "json_extract" in sql:
                raise sqlite3.OperationalError("no such function: json_extract")
            return self.c.execute(sql, *a)
    again = RN.condition_trades(NoJson(conn), ["core-A-1h-1-ld", "core-A-1h-1-fq"])
    assert again["core-A-1h-1-ld"] == [("BTCUSDT", 1, 1, 2, 0.5, True, None)] and len(again["core-A-1h-1-fq"]) == 4


def fake_league(tmp_path, owner=True, name="a.db"):
    conn = RN.open_db(str(tmp_path / name))
    lu = {r["role"]: r for r in LU}
    accts, book = [], {}
    for pick, kind, tf in (("core-A-1h-1", "core", "1h"), ("ds-F5_BOX-1h-1", "ds", "1h")):
        for role in ("fq", "fqc", "ld", "ldc"):
            a = {"id": f"{pick}-{role}", "pick": pick, "role": role, "kind": kind, "name": "X", "tf": tf, "combo": {}, "exit": "ladderU|2", "of": pick,
                 "size": 1.0, "source": {}}
            if owner:
                a["ox"] = {**lu[role], "kind": "x", "desc_ko": "d", "why_ko": "w", "tp": None, "weekend_off": False, "size": 1.0, "rule": None}
            accts.append(a)
            book[a["id"]] = []
            for i in range(3):
                t = {"symbol": "BTCUSDT", "side": 1, "entry_time": T0 + i * 2 * H, "exit_time": T0 + (i * 2 + 1) * H, "roe": 0.02 * (i - 1), "pnl": 2.0 * (i - 1),
                     "exit_reason": "SL", "entry_price": 100.0, "exit_price": 101.0, "leverage": 10, "stop_initial": 99.0, "tp_price": float("nan"),
                     "mae_price": 99.5, "mfe_price": 101.5, "equity_after": 0.0, "margin": 100.0, "context": {"g1": bool(i % 2), "g2": True}}
                book[a["id"]].append(t)
                conn.execute("INSERT INTO trades VALUES (?, ?, ?)", (a["id"], t["exit_time"], json.dumps(t)))
    conn.commit()
    engines = {a["id"]: SimpleNamespace(position=None, wallet=RN.EQUITY + sum(t["pnl"] for t in book[a["id"]]), bust=False) for a in accts}
    return SimpleNamespace(conn=conn, accts=accts, engines=engines, done=T0 + 2 * DAY, start_ms=T0, meta={"started_ms": T0, "notes": []}, advanced_ms=None)


NOW = T0 + 2 * DAY + MIN


def test_write_snapshots_carries_conditions_next_to_decision_in_a_league_with_a_lineup(tmp_path):
    lg = fake_league(tmp_path)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=False)
    saved = json.load(open(tmp_path / "snap" / "league.json"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    assert saved["conditions"] == doc["conditions"] and "decision" in saved and "kinds" in saved
    c = saved["conditions"]
    assert c["ds_in_stats"] is False and c["n_trades"] == {"-fq": 3, "-fqc": 3, "-ld": 3, "-ldc": 3} and c["days"] == 2      # the core pick only
    assert [b["id"] for b in bucket_list(c, "g1")] == ["with", "against"] and bucket_list(c, "g1")[0]["kinds"]["-fq"]["n"] == 1
    on = RN.write_snapshots(str(tmp_path / "snap2"), lg, NOW, ds_money=True)["conditions"]
    assert on["ds_in_stats"] is True and on["n_trades"]["-fq"] == 6
    assert "conditions_error" not in doc


def test_write_snapshots_has_no_conditions_without_a_lineup_and_never_stops_on_a_failure(tmp_path, monkeypatch):
    lg = fake_league(tmp_path, owner=False)
    assert RX.lineup(lg.accts) is None
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, NOW, ds_money=True)
    assert "conditions" not in doc and "conditions_error" not in doc
    lg = fake_league(tmp_path, owner=True, name="b.db")

    def boom(*a, **k):
        raise ValueError("boom")
    monkeypatch.setattr(SM, "conditions_views", boom)
    doc = RN.write_snapshots(str(tmp_path / "snap2"), lg, NOW, ds_money=True)
    assert "conditions" not in doc and doc["conditions_error"] == "ValueError: boom" and "decision" in doc          # the rest of the snapshot is written
    assert "conditions" not in json.load(open(tmp_path / "snap2" / "league.json")) and os.path.exists(tmp_path / "snap2" / "trades.json")
