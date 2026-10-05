"""ana8B (분석 additions): the 45-question checklist file, the '지정가 진입' block, entry drift, per-strategy shadows
and the losing-streak context. All read-only and descriptive; DeepSeek is counted and given rates, never money."""
import itertools
import json
import os
import re
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paperbot.dash import analysis as AN  # noqa: E402
from paperbot.dash.more import drift as DR  # noqa: E402
from paperbot.dash.more import shadowplus as SP  # noqa: E402
from paperbot.dash.more import streaks as SK  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
MONEY = re.compile(r"pnl|usd|usdt|money|equity|_eq\b|mean_eq|wallet|balance", re.I)


def _keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", k
            yield from _keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _keys(v, f"{path}[{i}]")


def _no_money(obj):
    bad = [p for p, k in _keys(obj) if MONEY.search(str(k))]
    assert not bad, bad


# ---------------------------------------------------------------- (2) the 45 questions
def test_questions45_file_has_45_rows_with_valid_statuses():
    with open(AN.QUESTIONS_FILE, encoding="utf-8") as fh:
        raw = json.load(fh)
    qs = raw["questions"]
    assert len(qs) == 45 and sorted(q["n"] for q in qs) == list(range(1, 46))
    assert raw["source"] and re.match(r"^\d{4}-\d{2}-\d{2}$", raw["updated"])
    for q in qs:
        assert q["status"] in AN.STATUSES, q
        assert q["q"].strip() and q["where"].strip() and q["group"].strip()
        assert len(q["q"]) <= 300 and len(q["where"]) <= 200 and len(q["note"]) <= 300 and len(q["group"]) <= 60
        assert not re.search(r"합격|불합격|통과|pass|fail", q["note"] + q["where"], re.I) or "판정" in q["note"] + q["where"]
    view = AN.questions()
    assert view["ready"] and view["total"] == 45 and sum(view["counts"].values()) == 45
    assert "checking" in AN.STATUSES                  # 확인 중: an unverified item is never a guessed status
    # the page knows every status word
    with open(os.path.join(V4, "screens", "analysis-rules.js"), encoding="utf-8") as fh:
        js = fh.read()
    for st in AN.STATUSES:
        assert re.search(rf"\b{st}: \[", js), st


# ---------------------------------------------------------------- (8) streak math
def _brute(n, q, k):
    tot = 0.0
    for seq in itertools.product((0, 1), repeat=n):             # 1 = loss
        run = best = 0
        for x in seq:
            run = run + 1 if x else 0
            best = max(best, run)
        if best >= k:
            ones = sum(seq)
            tot += q ** ones * (1 - q) ** (n - ones)
    return tot


def test_longest_run_probability_is_exact():
    assert SK.p_longest_run_ge(3, 0.5, 2) == pytest.approx(3 / 8)        # HHT THH HHH
    for n in range(0, 11):
        for q in (0.3, 0.5, 0.62):
            for k in range(0, 6):
                assert SK.p_longest_run_ge(n, q, k) == pytest.approx(_brute(n, q, k), abs=1e-12), (n, q, k)
    assert SK.p_longest_run_ge(10, 0.0, 1) == 0.0 and SK.p_longest_run_ge(10, 1.0, 10) == 1.0
    assert SK.p_longest_run_ge(5, 0.5, 6) == 0.0
    # a 9-loss run in 100 trades at a 40% win rate is common (the owners' question), at 70% it is rare
    assert 0.25 < SK.p_longest_run_ge(100, 0.6, 9) < 0.6
    assert SK.p_longest_run_ge(100, 0.3, 9) < 0.01
    assert SK.runs([1, -1, 0, -2, 3, -1]) == {"n": 6, "wins": 2, "longest": 3, "now": 1}


def _paper(path, accounts, trades=(), signals=()):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE accounts (account_id TEXT PRIMARY KEY, strategy TEXT NOT NULL, timeframe TEXT NOT NULL,
            kind TEXT NOT NULL, created_ts INTEGER NOT NULL, settings_version TEXT NOT NULL, parent TEXT,
            data TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
            entry_time INTEGER NOT NULL, exit_time INTEGER NOT NULL, exit_reason TEXT NOT NULL, leverage INTEGER NOT NULL,
            pnl REAL NOT NULL, roe REAL NOT NULL, equity_after REAL NOT NULL, data TEXT NOT NULL);
        CREATE TABLE signal_log (id INTEGER PRIMARY KEY AUTOINCREMENT, bar_close INTEGER NOT NULL,
            timeframe TEXT NOT NULL, strategy TEXT NOT NULL, symbol TEXT NOT NULL, side INTEGER NOT NULL, atr REAL,
            ref_price REAL, ref_time INTEGER, delay_ms INTEGER, status TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
            UNIQUE (bar_close, timeframe, strategy, symbol));
        CREATE INDEX siglog_tf ON signal_log (timeframe, bar_close);
        CREATE TABLE state (k TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_ts INTEGER);""")
    for aid, kind in accounts:
        s, tf = aid.split("@")
        c.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, 1000, 'v4', NULL, '{}')", (aid, s, tf, kind))
    for i, (aid, pnl) in enumerate(trades):
        c.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                  "equity_after, data) VALUES (?, 'BTCUSDT', ?, ?, 'SL', 30, ?, ?, 5000, '{}')",
                  (aid, 2000 + i, 3000 + i, pnl, pnl / 100))
    for i, (aid, side, ref, close, delay, status) in enumerate(signals):
        s, tf = aid.split("@")
        c.execute("INSERT INTO signal_log (bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, "
                  "delay_ms, status, data) VALUES (?, ?, ?, 'BTCUSDT', ?, 1.0, ?, 0, ?, ?, ?)",
                  (5000 + i, tf, s, side, ref, delay, status, json.dumps({"close": close})))
    c.commit()
    c.close()


def test_streak_context_per_group_with_the_coin_flip_band(tmp_path):
    db = str(tmp_path / "paper3.db")
    acc = [("A@15m", "strategy"), ("B@1h", "strategy"), ("F1_X@15m", "ds200"), ("REEL_H1@5m", "reel"),
           ("RANDOM_1@15m", "random"), ("RANDOM_2@1h", "random"), ("RANDOM_1@5m", "random")]
    tr = ([("A@15m", x) for x in (5, -1, -1, -1, -1, 3, -2)] + [("B@1h", x) for x in (1, 2, -1)]
          + [("F1_X@15m", x) for x in (-4, -4, 1, -4, -4, -4)] + [("RANDOM_1@15m", x) for x in (-1, -1, 1)]
          + [("RANDOM_2@1h", x) for x in (-1, -1, -1, -1, -1, 2)] + [("RANDOM_1@5m", x) for x in (-1, 1)])
    _paper(db, acc, tr)
    v = SK.streak_context(db, 10_000)
    core, ds, reel = v["groups"]["core"], v["groups"]["ds200"], v["groups"]["reel"]
    assert core["accounts"] == 2 and core["top"][0]["account_id"] == "A@15m" and core["top"][0]["longest"] == 4
    a = core["top"][0]
    assert a["trades"] == 7 and a["win_rate"] == pytest.approx(2 / 7, abs=1e-4)
    assert a["p_longest"] == pytest.approx(SK.p_longest_run_ge(7, 5 / 7, 4), abs=1e-4) and a["small"]
    assert core["now"]["account_id"] == "B@1h" and core["now"]["now"] == 1      # a tie: the rarer run (fewer trades)
    assert core["flip_band"] == {"accounts": 2, "min": 2, "median": 3.5, "max": 5}
    assert reel["flip_band"] == {"accounts": 1, "min": 1, "median": 1, "max": 1}
    assert ds["top"][0]["longest"] == 3 and 0 < core["any_account"]["p"] <= 1
    assert ds["unnamed"] and len(ds["top"]) == 1 and ds["top"][0]["account_id"] is None      # DeepSeek: group level only
    assert ds["now"]["account_id"] is None and core["top"][0]["account_id"]
    assert v["cite"].startswith("Schilling (1990)")
    _no_money(v)                                       # counts and rates only, DeepSeek included
    empty = str(tmp_path / "empty.db")
    _paper(empty, acc)
    e = SK.streak_context(empty, 10_000)               # day 0: every group says nothing yet
    assert all(g["with_trades"] == 0 and "top" not in g for g in e["groups"].values())


# ---------------------------------------------------------------- (5) entry drift
def test_drift_sql_on_a_synthetic_db(tmp_path):
    db = str(tmp_path / "paper3.db")
    acc = [("A@15m", "strategy"), ("F1_X@15m", "ds200"), ("REEL_H1@5m", "reel"), ("RANDOM_1@15m", "random")]
    sig = [("A@15m", 1, 100.05, 100.0, 3000, "SUBMITTED"),       # +5 bps (paid more on a long)
           ("A@15m", -1, 99.98, 100.0, 12000, "SUBMITTED"),      # short sold 2 bps lower: +2 bps
           ("A@15m", 1, 100.10, 100.0, 70000, "SUBMITTED"),      # +10 bps, slow
           ("A@15m", 1, 200.0, 100.0, 3000, "LATE"),             # not submitted: ignored
           ("RANDOM_1@15m", 1, 100.01, 100.0, 3000, "SUBMITTED"),  # +1 bp
           ("RANDOM_1@15m", -1, 100.0, 100.0, 3000, "SUBMITTED"),  # 0
           ("F1_X@15m", 1, 100.0, 100.0, 25000, "SUBMITTED"),
           ("REEL_H1@5m", 1, None, 100.0, 1000, "SUBMITTED")]    # no price: skipped
    _paper(db, acc, signals=sig)
    assert DR.drift_bps(1, 100.05, 100.0) == pytest.approx(5.0)
    assert DR.drift_bps(-1, 99.98, 100.0) == pytest.approx(2.0)
    assert DR.drift_bps(1, None, 100) is None and DR.drift_bps(0, 1, 1) is None
    assert [DR.bucket_of(x) for x in (0, 4999, 5000, 19999, 20000, 60000, None)] == \
        ["lt5", "lt5", "5to20", "5to20", "20to60", "gt60", None]
    v = DR.drift_view(db, 10_000)
    core = v["groups"]["core"]["timeframes"]["15m"]
    assert core["n"] == 3 and core["median"] == pytest.approx(5.0) and core["over"] is True and core["small"]
    assert core["p90"] == pytest.approx(9.0)
    assert set(core["by_delay"]) == {"lt5", "5to20", "gt60"} and core["by_delay"]["gt60"]["median"] == pytest.approx(10)
    flip = v["groups"]["flip"]["timeframes"]["15m"]
    assert flip["median"] == pytest.approx(0.5) and flip["over"] is False and "minus_flip" not in flip
    assert core["minus_flip"] == pytest.approx(4.5)
    assert v["groups"]["ds200"]["timeframes"]["15m"]["by_delay"]["20to60"]["n"] == 1
    assert v["groups"]["reel"]["all"] == {"n": 0} and v["signals"] == 6
    assert v["flag_bps"] == pytest.approx(3.0) and v["assumed_bps"] == pytest.approx(2.0)
    _no_money(v)
    empty = str(tmp_path / "empty.db")
    _paper(empty, acc)
    e = DR.drift_view(empty, 10_000)
    assert e["signals"] == 0 and all(g["all"] == {"n": 0} for g in e["groups"].values())
    assert DR.drift_view(str(tmp_path / "missing.db"), 1)["error"]


# ---------------------------------------------------------------- (4) limit entry
def _daily_shadows(path, rows):
    d = sqlite3.connect(path)
    d.executescript("""CREATE TABLE reports (day TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE shadows (key TEXT PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL, account_id TEXT NOT NULL,
            symbol TEXT NOT NULL, timeframe TEXT NOT NULL, side INTEGER NOT NULL, filled INTEGER, roe REAL,
            exit_reason TEXT, resolved INTEGER NOT NULL, data TEXT NOT NULL);""")
    for kind, aid, bc, filled, roe, resolved in rows:
        d.execute("INSERT INTO shadows VALUES (?, '2026-10-06', ?, ?, 'BTCUSDT', ?, 1, ?, ?, NULL, ?, ?)",
                  (f"{kind}|{aid}|BTCUSDT|{bc}", kind, aid, aid.split("@")[1], filled, roe, resolved,
                   json.dumps({"pnl_equity": None if roe is None else roe * 0.3})))
    d.commit()
    d.close()


def test_limit_entry_block_per_group_and_no_money(tmp_path):
    db = str(tmp_path / "paper3.db")
    _paper(db, [("A@15m", "strategy"), ("F1_X@15m", "ds200"), ("REEL_H1@5m", "reel"), ("RANDOM_1@15m", "random")])
    dd = str(tmp_path / "daily3.db")
    _daily_shadows(dd, [
        ("limit", "A@15m", 1, 1, 0.10, 1), ("base", "A@15m", 1, None, 0.05, 1),       # filled, better by +5%
        ("limit", "A@15m", 2, 1, -0.20, 1), ("base", "A@15m", 2, None, -0.30, 1),     # filled, better by +10%
        ("limit", "A@15m", 3, 0, None, 1), ("base", "A@15m", 3, None, 0.40, 1),       # missed a winner
        ("limit", "A@15m", 4, 0, None, 1),                                             # missed, no trade taken
        ("limit", "A@15m", 5, 1, None, 0),                                             # filled, still open
        ("limit", "F1_X@15m", 1, 1, 0.02, 1), ("base", "F1_X@15m", 1, None, 0.01, 1),
        ("limit", "RANDOM_1@15m", 1, 1, 0.5, 1)])                                       # coin flips: not in the block
    c, d = sqlite3.connect(db), sqlite3.connect(dd)
    v = SP.limit_entry(d, c, 0, 1_900_000_000_000)
    c.close()
    d.close()
    a = v["groups"]["core"]
    assert a["signals"] == 5 and a["filled"] == 3 and a["fill_rate"] == pytest.approx(0.6) and a["open"] == 1
    assert a["paired"] == 2 and a["paired_limit_roe"] == pytest.approx(-0.05) and a["paired_base_roe"] == pytest.approx(-0.125)
    assert a["paired_diff_roe"] == pytest.approx(0.075) and a["paired_better_share"] == 1.0 and a["small"]
    assert a["missed"] == 2 and a["missed_share"] == pytest.approx(0.4) and a["missed_traded"] == 1
    assert a["missed_base_roe"] == pytest.approx(0.40) and a["missed_base_win_share"] == 1.0
    assert v["groups"]["ds200"]["signals"] == 1 and v["groups"]["reel"] == {"signals": 0, "small": True}
    assert set(v["groups"]) == {"core", "ds200", "reel"} and v["signals"] == 6
    _no_money(v)                                        # ROE and counts only, for DeepSeek too
    assert SP.limit_entry(None, None, 0, 1)["error"]


# ---------------------------------------------------------------- (6) one strategy
def test_strategy_shadows_and_five_year_cells(tmp_path):
    cells = SP.levstop_cells("N01_ST_EMA")
    if cells.get("error"):
        pytest.skip("research/levstop/out/levstop.json not in this checkout")
    assert set(cells["by_tf"]) <= set(SP.LIVE_TFS) and cells["by_tf"]
    one = cells["by_tf"]["15m"]["30|2.0"]
    assert set(one) >= {"trades", "mean_roe", "mean_eq", "win_rate", "liq_share", "busts", "periods"}
    assert set(cells["by_tf"]["15m"]) == set(SP.LEVSTOP_ARMS)
    assert SP.levstop_cells("NO_SUCH")["by_tf"] == {}
    db = str(tmp_path / "paper3.db")
    _paper(db, [("A@15m", "strategy")])
    dd = str(tmp_path / "daily3.db")
    _daily_shadows(dd, [("base", "A@15m", 1, None, 0.05, 1), ("lock15", "A@15m", 1, None, 0.08, 1)])
    v = AN.shadows_view(db, dd, 1_900_000_000_000, strategy="A")
    assert v["strategy"] == "A" and v["core"] is True and v["base"]["trades"] == 1
    lock = next(g for g in v["groups"] if g["key"] == "lock")["rows"][0]
    assert lock["variant"] == "lock15" and lock["trades"] == 1 and lock["vs_base_eq"] == pytest.approx(0.009, abs=1e-5)
    assert "levstop" in v and "curves" not in v
    pooled = AN.shadows_view(db, dd, 1_900_000_000_000)
    assert "limit_entry" in pooled and set(pooled["limit_entry"]["groups"]) == {"core", "ds200", "reel"}


def test_the_pages_ship_the_new_modules_without_unsafe_dom():
    files = ("analysis-limit.js", "analysis-drift.js", "analysis-streak.js", "strategies-shadows.js")
    for f in files:
        with open(os.path.join(V4, "screens", f), encoding="utf-8") as fh:
            js = fh.read()
        assert not re.search(r"innerHTML|insertAdjacentHTML|outerHTML|DOMParser|eval\(|toLocaleString|Intl\.", js), f
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", js), f          # tokens only
        assert not re.search(r"합격|불합격|✓|✕", js), f                  # descriptive labels only
    with open(os.path.join(V4, "screens", "analysis-risk.js"), encoding="utf-8") as fh:
        assert 'from "./analysis-streak.js"' in fh.read()
    with open(os.path.join(V4, "screens", "analysis-rules.js"), encoding="utf-8") as fh:
        rules = fh.read()
        assert 'from "./analysis-limit.js"' in rules and 'from "./analysis-drift.js"' in rules
    with open(os.path.join(V4, "screens", "strategies-detail.js"), encoding="utf-8") as fh:
        assert 'from "./strategies-shadows.js"' in fh.read()
    with open(os.path.join(V4, "INVENTORY.md"), encoding="utf-8") as fh:
        assert "ana8B" in fh.read()
