"""paperbot/dscheck.py, the DeepSeek nightly recompute check (non-trading), on synthetic data: the live rows a trailing
window gives agree with the full-history recompute; flips, missing and extra rows are mismatches (exit 1); a
mismatch whose own chart bar the live service read differently (live_bars) is the documented 1-bar data difference;
a boundary without any live row is uncovered, a whole silent day fails; paper3.db is never written; the pins and the
contained load; the kline cache; the unit files."""

import json
import re
import sqlite3
import sys
import types
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from paperbot import dscheck as D
from paperbot import sweepsig
from paperbot.store3 import Store3

REPO = Path(__file__).resolve().parent.parent
DAY = "2026-09-20"
D0 = int(pd.Timestamp(DAY, tz="UTC").timestamp() * 1000)
W = {"15m": 600, "1h": 1200}                         # small live windows (5m bars) for the synthetic runs
TFS = ("15m", "1h")
FIVE = 300_000


# ---------------------------------------------------------------- a stand-in for lib_c (window-independent rules)
def _entries(df, tf, ctx, coin):
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    prev = np.r_[np.nan, c[:-1]]
    with np.errstate(invalid="ignore"):
        up, dn = c > prev * 1.002, c < prev * 0.998
        brk = h > pd.Series(h).rolling(5).max().shift(1).to_numpy()
    f14l = np.zeros(len(c), bool)
    f14s = np.zeros(len(c), bool)
    if ctx and "BTCUSD" in ctx and coin != "BTCUSD":
        b = ctx["BTCUSD"]
        bup = pd.Series(b["close"].to_numpy(float) > np.r_[np.nan, b["close"].to_numpy(float)[:-1]],
                        index=b["ts"].to_numpy())
        al = bup.astype(float).reindex(df["ts"].to_numpy()).fillna(0.0).to_numpy() > 0
        f14l, f14s = al & dn, ~al & up & (coin != "XX")
    return {"D_UP": (up, dn), "D_BRK": (brk, np.zeros(len(c), bool)), "F14_SMT": (f14l, f14s)}


FAKE = types.SimpleNamespace(DEFS=[("D_UP", "F1", TFS), ("D_BRK", "F2", ("15m",)), ("F14_SMT", "F14", TFS)],
                             COINS=D.COINS, entries=_entries)


def synth(seed=1, start=D0 - 2000 * FIVE, end=D0 + 86_400_000):
    """6 coins of 5m bars (random walks), a few zero-volume bars."""
    out = {}
    ts = np.arange(start, end, FIVE, dtype=np.int64)
    for k, coin in enumerate(D.COINS):
        r = np.random.default_rng(seed * 10 + k)
        c = 100.0 * np.exp(np.cumsum(r.normal(0, 0.003, len(ts))))
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) * (1 + np.abs(r.normal(0, 0.001, len(ts))))
        lo = np.minimum(o, c) * (1 - np.abs(r.normal(0, 0.001, len(ts))))
        v = r.uniform(1, 10, len(ts))
        v[r.integers(0, len(ts), 5)] = 0.0
        out[D.symbol_of(coin)] = (ts, o, h, lo, c, v)
    return out


def live_sides(bars, tf, lib):
    """What the live service logs: per boundary of the day, the last bar of a trailing window of W[tf] 5m bars."""
    rows = []
    src = D.FrameSource(bars)
    btc_all = src.load("BTCUSDT", 0, 2**62)
    for b in range(D0 + D.TF_MS[tf], D0 + 86_400_000 + 1, D.TF_MS[tf]):
        for coin in D.COINS:
            sym = D.symbol_of(coin)
            cols = src.load(sym, 0, b)
            cols = tuple(a[-W[tf]:] for a in cols)
            df = D.frame(cols, tf, lib)
            ctx = None
            if coin != "BTCUSD":
                bc = tuple(a[(a0 >= b - 100 * D.TF_MS[tf]) & (a0 < b)] for a0 in [btc_all[0]] for a in btc_all)
                ctx = {"BTCUSD": D.frame(bc, tf, lib)}
            R = _entries(df, tf, ctx, coin)
            for d, _f, tfs in FAKE.DEFS:
                if tf not in tfs:
                    continue
                lg, sh = R[d]
                side = 1 if lg[-1] else (-1 if sh[-1] else 0)
                if side:
                    rows.append({"bar_close": b, "timeframe": tf, "strategy": d, "symbol": sym, "side": side,
                                 "atr": 1.0, "ref_price": 100.0, "ref_time": b + 9000, "delay_ms": 9000,
                                 "status": "SUBMITTED", "data": {}})
    return rows


@pytest.fixture(scope="module")
def lib():
    return sweepsig.lib()


@pytest.fixture(scope="module")
def world(lib):
    bars = synth()
    rows = [r for tf in TFS for r in live_sides(bars, tf, lib)]
    return bars, rows


def make_db(path, rows, created=D0 - 86_400_000, kind="ds200", extra=()):
    st = Store3(str(path))
    for d, _f, tfs in FAKE.DEFS:
        for tf in tfs:
            st.add_account(f"{d}@{tf}", d, tf, kind, created, "v")
    st.add_account("N17_KC_RSI@15m", "N17_KC_RSI", "15m", "strategy", created, "v")
    st.log_signals(list(rows) + [{"bar_close": D0 + 900_000, "timeframe": "15m", "strategy": "N17_KC_RSI",
                                  "symbol": "BTCUSDT", "side": 1, "atr": 1.0, "ref_price": 1.0, "ref_time": 0,
                                  "delay_ms": 0, "status": "SUBMITTED", "data": {}}] + list(extra))
    st.commit()
    st.close()
    return D.connect_ro(str(path))


def check(conn, bars, lib, **kw):
    return D.run_check(conn, D.FrameSource(bars), D0, C=FAKE, lib=lib, tfs=TFS, windows=W, now_ms=D0 + 2 * 86_400_000,
                       **kw)


# ---------------------------------------------------------------- the comparison
def test_live_rows_of_trailing_windows_agree_with_the_full_history(tmp_path, world, lib):
    bars, rows = world
    assert len(rows) > 100
    conn = make_db(tmp_path / "p.db", rows)
    rep = check(conn, bars, lib)
    assert rep["status"] == "ok" and D.exit_code(rep) == 0
    assert rep["n_mismatch"] == 0 and rep["data"] == [] and rep["live_rows"] == len(rows)
    assert rep["checked"] >= len(rows) and rep["agree"] == rep["checked"]
    assert rep["history_5m"] == {"15m": 900, "1h": 1800} and rep["unchecked"] == {}
    assert any(k[2] == "F14_SMT" for k in [(r["timeframe"], r["bar_close"], r["strategy"]) for r in rows])
    assert rep["line"].startswith(f"딥시크 밤 재계산 {DAY} (UTC): 불일치 0 · 일치 ")


def _mutate(rows, i, **kw):
    out = [dict(r) for r in rows]
    out[i].update(kw)
    return out


def test_flipped_missing_and_extra_rows_are_mismatches(tmp_path, world, lib):
    bars, rows = world
    # flip
    conn = make_db(tmp_path / "a.db", _mutate(rows, 3, side=-rows[3]["side"]))
    rep = check(conn, bars, lib)
    assert rep["status"] == "mismatch" and D.exit_code(rep) == 1 and rep["n_mismatch"] == 1
    m = rep["mismatches"][0]
    assert m["kind"] == "flip" and m["def"] == rows[3]["strategy"] and m["live"] == -rows[3]["side"]
    assert m["recomputed"] == rows[3]["side"] and "recorded for 0 of" in m["data"]     # no live bars: not excused
    assert "불일치 1건 (예: " in rep["line"] and "KST 실시간" in rep["line"]
    # missing: a covered boundary (other rows there) without one of its signals
    i = next(k for k, r in enumerate(rows) if sum(x["bar_close"] == r["bar_close"] and x["timeframe"] == r["timeframe"]
                                                   for x in rows) >= 2)
    conn = make_db(tmp_path / "b.db", rows[:i] + rows[i + 1:])
    rep = check(conn, bars, lib)
    assert rep["n_mismatch"] == 1 and rep["mismatches"][0]["kind"] == "missing"
    assert rep["mismatches"][0]["live"] == 0 and rep["mismatches"][0]["recomputed"] == rows[i]["side"]
    # extra: a signal the recompute does not have, at a covered boundary
    have = {(r["timeframe"], r["bar_close"], r["strategy"], r["symbol"]) for r in rows}
    r0 = rows[0]
    sym = next(s for s in ("ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "BTCUSDT")
               if (r0["timeframe"], r0["bar_close"], "D_UP", s) not in have)
    extra = dict(r0, strategy="D_UP", symbol=sym, side=1)
    conn = make_db(tmp_path / "c.db", rows + [extra])
    rep = check(conn, bars, lib)
    assert rep["n_mismatch"] == 1 and rep["mismatches"][0]["kind"] == "extra" and rep["mismatches"][0]["recomputed"] == 0


def test_a_mismatch_on_a_bar_live_read_differently_is_a_data_difference(tmp_path, world, lib):
    bars, rows = world
    r = next(x for x in rows if x["timeframe"] == "15m" and x["strategy"] != "F14_SMT")
    bad = _mutate(rows, rows.index(r), side=-r["side"])
    sym, bo = r["symbol"], r["bar_close"] - 900_000
    ts, o, h, lo, c, v = D.FrameSource(bars).load(sym, bo, r["bar_close"])

    def minutes(n, bump):
        out = []
        for m in range(n):
            k = m // 5
            out.append({"ts": bo + m * 60_000, "symbol": sym, "open": o[k] if m % 5 == 0 else c[k], "high": h[k],
                        "low": lo[k], "close": c[k], "volume": v[k] / 5, "mark_open": None, "mark_high": None,
                        "mark_low": None, "mark_close": None, "close_time": bo + m * 60_000 + 59_999,
                        "processed_at": 0})
        out[-1]["close"] = c[2] * (1 - bump)              # the bar's last minute read early: another close
        return out

    def with_live_bars(path, live):
        conn = make_db(path, bad)
        conn.close()
        st = Store3(str(path))
        st.live_bars(live)
        st.commit()
        st.close()
        return D.connect_ro(str(path))

    # every minute recorded, and one differs from the final bars: explained
    rep = check(with_live_bars(tmp_path / "a.db", minutes(15, 0.0)), bars, lib)
    assert rep["n_mismatch"] == 1 and "live bar equals the final bar" in rep["mismatches"][0]["data"]
    rep = check(with_live_bars(tmp_path / "b.db", minutes(15, 0.01)), bars, lib)
    assert rep["status"] == "ok" and D.exit_code(rep) == 0 and rep["n_mismatch"] == 0
    assert len(rep["data"]) == 1 and "close live" in rep["data"][0]["data"] and "자료 차이 1건(설명됨)" in rep["line"]
    # a minute missing: nothing is excused
    rep = check(with_live_bars(tmp_path / "c.db", minutes(15, 0.01)[:14]), bars, lib)
    assert rep["n_mismatch"] == 1 and "recorded for 14 of 15 minutes" in rep["mismatches"][0]["data"]


def full_record(override=None, drop=()):
    """live3's "dsrun:<day>" record of DAY: every DeepSeek boundary of TFS "ran" with all six coins computed, then
    ``override`` {(boundary, tf): entry} and ``drop`` (boundary, tf) pairs left out."""
    out = {"v": 1, "day": DAY, "tfs": {}}
    for tf in TFS:
        for b in range(D0 + D.TF_MS[tf], D0 + 86_400_000 + 1, D.TF_MS[tf]):
            if (b, tf) in drop:
                continue
            e = (override or {}).get((b, tf), {"s": "ran", "ok": sorted(D.symbol_of(c) for c in D.COINS)})
            out["tfs"].setdefault(tf, {})[str(b)] = e
    return out


def _alert_db(path, rows, alerts=(), state=None):
    conn = make_db(path, rows)
    conn.close()
    st = Store3(str(path))
    for ts, text in alerts:
        st.alert(ts, "WARN", text)
    if state:
        st.put_state(*state)
    st.commit()
    st.close()
    return D.connect_ro(str(path))


def test_the_frozen_texts_are_the_signal_services():
    from paperbot import live3, sigservice
    assert D.DS_TIMEOUT_RE == sigservice.DS_TIMEOUT_RE and D.DS_FAILED_RE == sigservice.DS_FAILED_RE
    assert D.DS_RUN_KEY == live3.DS_RUN_KEY
    assert re.match(D.DS_TIMEOUT_RE, sigservice.DS_TIMEOUT_TEXT.format(secs="60", boundary=D0, tfs="15m, 1h"))
    assert re.match(D.DS_FAILED_RE, sigservice.DS_FAILED_TEXT.format(boundary=D0, error="x"))
    src = Path(live3.__file__).read_text(encoding="utf-8")
    assert 'f"5m history incomplete at {boundary}; signals skipped"' in src
    assert re.match(D.INCOMPLETE_RE, f"5m history incomplete at {D0}; signals skipped")


def test_uncovered_boundaries_silent_days_and_runs_without_ds(tmp_path, world, lib):
    bars, rows = world
    b = rows[0]["bar_close"], rows[0]["timeframe"]
    rest = [r for r in rows if (r["bar_close"], r["timeframe"]) != b]
    # review finding 1: a boundary with no DeepSeek row while the recompute fired is ONE mismatch ...
    rep = check(make_db(tmp_path / "a.db", rest), bars, lib)
    assert rep["status"] == "mismatch" and D.exit_code(rep) == 1 and rep["uncovered_boundaries"] == 1
    assert rep["n_mismatch"] == 1 and rep["mismatches"][0]["kind"] == "uncovered"
    assert rep["mismatches"][0]["n"] == sum(1 for r in rows if (r["bar_close"], r["timeframe"]) == b)
    assert "경계에 실시간 딥시크 기록 없음" in rep["line"] and "건너뜀 알림 없음" in rep["line"]
    # ... unless the live service said it skipped it: the frozen timeout text, the failure text, the history alert, or
    # its own run record
    from paperbot import sigservice
    for i, (alerts, state) in enumerate([
            ([(b[0] + 70_000, sigservice.DS_TIMEOUT_TEXT.format(secs="60", boundary=b[0], tfs=f"{b[1]}, 4h"))], None),
            ([(b[0] + 9_000, sigservice.DS_FAILED_TEXT.format(boundary=b[0], error="RuntimeError: x"))], None),
            ([(b[0] + 1_000, f"5m history incomplete at {b[0]}; signals skipped")], None),
            ((), (D.DS_RUN_KEY + DAY, b[0], full_record({b: {"s": "timeout"}})))]):
        rep = check(_alert_db(tmp_path / f"x{i}.db", rest, alerts, state), bars, lib)
        assert rep["status"] == "ok" and rep["n_excused"] == 1 and rep["n_mismatch"] == 0, (i, rep["line"])
        assert "기록 없는 경계 1개(그중 알림 있는 건너뜀 1개)" in rep["line"]
    # a timeout of another boundary, another timeframe, or a "ran" record excuses nothing
    for i, (alerts, state) in enumerate([
            ([(b[0], sigservice.DS_TIMEOUT_TEXT.format(secs="60", boundary=b[0] + 3_600_000, tfs=b[1]))], None),
            ([(b[0], sigservice.DS_TIMEOUT_TEXT.format(secs="60", boundary=b[0], tfs="4h"))], None),
            ((), (D.DS_RUN_KEY + DAY, b[0], full_record({b: {"s": "ran"}}))),
            ((), (D.DS_RUN_KEY + DAY, b[0], full_record()))]):
        rep = check(_alert_db(tmp_path / f"y{i}.db", rest, alerts, state), bars, lib)
        assert rep["status"] == "mismatch" and rep["n_excused"] == 0, i
    # the silent rule per timeframe: the 1h job logged nothing all day, the 15m one ran (review: was "ok")
    rep = check(make_db(tmp_path / "h.db", [r for r in rows if r["timeframe"] != "1h"]), bars, lib)
    assert rep["status"] == "silent" and rep["silent_tfs"] == ["1h"] and D.exit_code(rep) == 1
    assert "1h 실시간 딥시크 신호 기록 0건" in rep["line"] and rep["agree"] > 0
    # no DeepSeek row at all on a day the accounts existed: silent
    rep = check(make_db(tmp_path / "b.db", []), bars, lib)
    assert rep["status"] == "silent" and D.exit_code(rep) == 1 and "신호 기록 0건" in rep["line"]
    assert rep["silent_tfs"] == list(TFS)
    # the accounts started during the day: earlier bars are not compared, no silent rule
    created = D0 + 12 * 3_600_000
    rep = check(make_db(tmp_path / "c.db", [r for r in rows if r["bar_close"] > created], created=created), bars, lib)
    assert rep["status"] == "ok" and rep["before_start"] > 0 and rep["n_mismatch"] == 0
    rep = check(make_db(tmp_path / "d.db", [], created=created), bars, lib)
    assert rep["status"] == "mismatch" and rep["checked"] == 0 and rep["uncovered"] > 0      # started, then nothing
    assert not rep["silent_tfs"] and {m["kind"] for m in rep["mismatches"]} == {"uncovered"}
    # a v3 database (no ds200 account) and accounts made after the day: nothing to check, exit 0, lib_c not needed
    v3 = make_db(tmp_path / "e.db", [], kind="strategy")
    rep = D.run_check(v3, D.FrameSource({}), D0, C=None, tfs=TFS, windows=W)
    assert rep["status"] == "no_accounts" and D.exit_code(rep) == 0 and "딥시크 계좌 없음" in rep["line"]
    later = make_db(tmp_path / "f.db", [], created=D0 + 2 * 86_400_000)
    assert D.run_check(later, D.FrameSource({}), D0, C=None, tfs=TFS, windows=W)["status"] == "no_accounts"


def test_the_live_job_record_decides_which_coins_are_compared(tmp_path, world, lib):
    """live3's dsrun:<day> record (trading owner's contract): "ran" compares exactly its ok coins; F14_SMT is excused
    on a coin listed under "err"; timeout / failed / refused / incomplete and a coin under "no" are uncovered with the
    record's reason; a DeepSeek boundary absent from an existing record is a failure; the heuristic only without one."""
    from paperbot import sigservice
    bars, rows = world
    every = sorted(D.symbol_of(c) for c in D.COINS)
    key = lambda b, i: (D.DS_RUN_KEY + DAY, b, full_record(**i))       # noqa: E731
    # a complete "ran" record and every row: the same answer as without a record
    rep = check(_alert_db(tmp_path / "r0.db", rows, (), key(D0, {})), bars, lib)
    assert rep["status"] == "ok" and rep["record"] and rep["n_mismatch"] == 0 and rep["agree"] == rep["checked"] > 0
    b = rows[0]["bar_close"], rows[0]["timeframe"]
    rest = [r for r in rows if (r["bar_close"], r["timeframe"]) != b]
    # every skip status of the record excuses the boundary, with its reason (no alert needed)
    for st in ("timeout", "failed", "refused", "incomplete"):
        rep = check(_alert_db(tmp_path / f"s{st}.db", rest, (), key(D0, {"override": {b: {"s": st}}})), bars, lib)
        assert rep["status"] == "ok" and rep["n_excused"] == 1 and rep["n_mismatch"] == 0, (st, rep["line"])
        assert rep["excused"][0]["data"] == f"live job record: {st}"
    # the record overrides the heuristic: a "ran" boundary without rows is "missing" per coin, even with a timeout
    # alert for it (the alert is the heuristic's, used only without a record)
    alert = [(b[0] + 70_000, sigservice.DS_TIMEOUT_TEXT.format(secs="60", boundary=b[0], tfs=b[1]))]
    rep = check(_alert_db(tmp_path / "m.db", rest, alert, key(D0, {})), bars, lib)
    assert rep["status"] == "mismatch" and rep["n_excused"] == 0
    assert {m["kind"] for m in rep["mismatches"]} == {"missing"}
    # a boundary absent from the record while the DeepSeek accounts were open: ONE "unrecorded" failure (with or
    # without rows, with or without an alert)
    for i, rr in enumerate((rows, rest)):
        rep = check(_alert_db(tmp_path / f"u{i}.db", rr, alert, key(D0, {"drop": (b,)})), bars, lib)
        assert rep["status"] == "mismatch" and D.exit_code(rep) == 1 and rep["n_mismatch"] == 1, rep["line"]
        assert rep["mismatches"][0]["kind"] == "unrecorded" and rep["mismatches"][0]["bar_close"] == b[0]
        assert "작업 기록에 없음" in rep["line"]
    # a coin the job listed under "no" (not computed) is uncovered with its reason, the other coins are compared
    sol = D.symbol_of("SOLUSD")
    fired = [r for r in rows if r["symbol"] == sol]
    assert fired
    b2 = fired[0]["bar_close"], fired[0]["timeframe"]
    no_sol = [r for r in rows if not ((r["bar_close"], r["timeframe"]) == b2 and r["symbol"] == sol)]
    entry = {"s": "ran", "ok": [s for s in every if s != sol], "no": {sol: "warm-up"}}
    rep = check(_alert_db(tmp_path / "n.db", no_sol, (), key(D0, {"override": {b2: entry}})), bars, lib)
    assert rep["status"] == "ok" and rep["n_excused"] == 1 and "warm-up" in rep["excused"][0]["data"], rep["line"]
    rep = check(_alert_db(tmp_path / "n2.db", no_sol, (), key(D0, {})), bars, lib)      # computed: a mismatch
    assert rep["status"] == "mismatch" and {m["kind"] for m in rep["mismatches"]} == {"missing"}
    # F14_SMT missing on a coin whose job reported an F14 problem ("err"): excused; without the err entry: missing
    f14 = [r for r in rows if r["strategy"] == D.F14]
    assert f14
    b3, s3 = (f14[0]["bar_close"], f14[0]["timeframe"]), f14[0]["symbol"]
    no_f14 = [r for r in rows if not ((r["bar_close"], r["timeframe"]) == b3 and r["symbol"] == s3
                                      and r["strategy"] == D.F14)]
    entry = {"s": "ran", "ok": every, "err": {s3: "F14_SMT: no BTC bars"}}
    rep = check(_alert_db(tmp_path / "f.db", no_f14, (), key(D0, {"override": {b3: entry}})), bars, lib)
    assert rep["status"] == "ok" and rep["n_excused"] == 1 and "no BTC bars" in rep["excused"][0]["data"]
    rep = check(_alert_db(tmp_path / "f2.db", no_f14, (), key(D0, {})), bars, lib)
    assert rep["status"] == "mismatch" and rep["mismatches"][0]["def"] == D.F14
    # "err" excuses only F14_SMT: another definition missing on that coin is still a mismatch
    other = [r for r in rows if r["strategy"] != D.F14 and r["symbol"] == s3]
    if other:
        b4 = other[0]["bar_close"], other[0]["timeframe"]
        drop1 = [r for r in rows if r is not other[0]]
        entry = {"s": "ran", "ok": every, "err": {s3: "F14_SMT: no BTC bars"}}
        rep = check(_alert_db(tmp_path / "f3.db", drop1, (), key(D0, {"override": {b4: entry}})), bars, lib)
        assert rep["status"] == "mismatch" and rep["mismatches"][0]["kind"] == "missing"
    # a record of another day leaves this day to the heuristic (no record of it)
    other_day = (D.DS_RUN_KEY + "2026-09-19", D0, {"v": 1, "day": "2026-09-19", "tfs": {}})
    rep = check(_alert_db(tmp_path / "o.db", rows, (), other_day), bars, lib)
    assert rep["status"] == "ok" and not rep["record"]


def test_a_coin_with_too_little_history_is_not_compared(tmp_path, world, lib):
    bars, rows = world
    short = dict(bars)
    ts, *rest = bars["SOLUSDT"]
    keep = ts >= D0 - 100 * FIVE
    short["SOLUSDT"] = (ts[keep], *(a[keep] for a in rest))
    rep = check(make_db(tmp_path / "p.db", rows), short, lib)
    assert rep["status"] == "ok" and set(rep["unchecked"]["15m"]) == {"SOLUSDT"}
    assert "live window 600" in rep["unchecked"]["15m"]["SOLUSDT"] and "못 본 코인·봉 2개" in rep["line"]


def test_paper_db_is_opened_read_only(tmp_path, world, lib):
    bars, rows = world
    path = tmp_path / "p.db"
    conn = make_db(path, rows)
    before = path.read_bytes()
    check(conn, bars, lib)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO alerts VALUES (0, 'INFO', 'x')")
    assert path.read_bytes() == before
    with pytest.raises(D.DsCheckError):
        D.connect_ro(str(tmp_path / "none.db"))
    # review nit 10: a "?" in the path never drops the read-only mode (no stray file is made)
    odd = tmp_path / "we?ird.db"
    make_db(odd, rows).close()
    c = D.connect_ro(str(odd))
    with pytest.raises(sqlite3.OperationalError):
        c.execute("INSERT INTO alerts VALUES (0, 'INFO', 'x')")
    assert not (tmp_path / "we").exists()


def test_cli_writes_the_one_line_summary_and_exits_by_status(tmp_path, world, lib, monkeypatch):
    bars, rows = world
    d = tmp_path / "bars"
    d.mkdir()
    for sym, (ts, o, h, lo, c, v) in bars.items():
        pd.DataFrame({"ts": pd.to_datetime(ts, unit="ms", utc=True), "open": o, "high": h, "low": lo, "close": c,
                      "volume": v}).to_csv(d / f"{sym[:-1].lower()}-5m.csv.gz", index=False)
    monkeypatch.setattr(D, "load_lib_c", lambda: FAKE)
    monkeypatch.setattr(D, "DS_WINDOW_5M", W)
    db = tmp_path / "p.db"
    make_db(db, _mutate(rows, 0, side=-rows[0]["side"])).close()
    out = tmp_path / "out"
    code = D.main(["run", "--db", str(db), "--out", str(out), "--day", DAY, "--bars-dir", str(d), "--tfs", "15m,1h"])
    assert code == 1
    line = (out / "last.txt").read_text(encoding="utf-8")
    assert line.count("\n") == 1 and line.startswith(f"딥시크 밤 재계산 {DAY} (UTC): 불일치 1건")
    assert D.read_summary(str(out)) == line.strip()
    full = json.loads((out / "days" / f"{DAY}.json").read_text(encoding="utf-8"))
    assert full["n_mismatch"] == 1 and json.loads((out / "last.json").read_text(encoding="utf-8")) == full
    assert D.main(["show", "--out", str(out)]) == 0
    # the check cannot run (no bar files): exit 2 and a line saying so
    code = D.main(["run", "--db", str(db), "--out", str(out), "--day", DAY, "--bars-dir", str(tmp_path / "x"),
                   "--tfs", "15m,1h"])
    assert code == 2 and "점검 못 함" in (out / "last.txt").read_text(encoding="utf-8")
    assert D.main(["run", "--db", str(db), "--out", str(out), "--day", "2999-01-01"]) == 2     # not ended yet
    assert D.read_summary(str(tmp_path / "never")) is None
    # review finding 3: no paper3.db at all (fresh server, mid-reset) is "nothing to check", exit 0, no warning
    out2 = tmp_path / "out2"
    assert D.main(["run", "--db", str(tmp_path / "missing.db"), "--out", str(out2), "--day", DAY]) == 0
    assert "paper3.db 없음" in D.read_summary(str(out2))
    assert json.loads((out2 / "last.json").read_text(encoding="utf-8"))["status"] == "no_accounts"


# ---------------------------------------------------------------- bars
def test_frame_drops_zero_volume_bars_and_partial_bins(lib):
    ts = np.arange(D0 + 2 * FIVE, D0 + 2 * FIVE + 12 * FIVE, FIVE, dtype=np.int64)    # starts mid 15m bin
    o = np.arange(12, dtype=float) + 100
    v = np.ones(12)
    v[4] = 0.0
    df = D.frame((ts, o, o + 1, o - 1, o, v), "15m", lib)
    opens = D._open_ms(df)
    assert opens[0] == D0 + 3 * FIVE and (opens % 900_000 == 0).all()
    assert df["open"].iloc[0] == 101.0 and df["volume"].iloc[0] == 3.0      # the partial first bin dropped
    assert df["open"].iloc[1] == 105.0 and df["volume"].iloc[1] == 2.0      # the zero-volume 5m bar left out
    assert opens[-1] + 900_000 <= ts[-1] + FIVE


class FakeRest:
    def __init__(self, bars):
        self.bars, self.calls = bars, []

    def klines(self, symbol, interval, start_time=None, limit=1500):
        self.calls.append((symbol, start_time))
        ts, o, h, lo, c, v = self.bars[symbol]
        i = np.searchsorted(ts, start_time)
        return [[int(ts[k]), str(o[k]), str(h[k]), str(lo[k]), str(c[k]), str(v[k]), int(ts[k]) + FIVE - 1]
                for k in range(i, min(i + limit, len(ts)))]


def test_rest_source_caches_final_bars_and_extends_its_span(tmp_path):
    bars = synth(start=D0 - 4000 * FIVE)
    now = [D0 + 3 * 3_600_000]
    rest = FakeRest(bars)
    src = D.RestSource(str(tmp_path / "c" / "bars5m.db"), rest=rest, now_ms=lambda: now[0], pause=0)
    got = src.load("BTCUSDT", D0 - 2000 * FIVE, D0 + 86_400_000)
    assert got[0][0] == D0 - 2000 * FIVE and got[0][-1] + FIVE + D.SETTLE_MS <= now[0]   # unsettled bars not taken
    n = len(rest.calls)
    assert n == 2                                                       # 1500 + the rest
    again = src.load("BTCUSDT", D0 - 1000 * FIVE, D0 + 3_600_000)
    assert len(rest.calls) == n and np.array_equal(again[4], bars["BTCUSDT"][4][
        (bars["BTCUSDT"][0] >= D0 - 1000 * FIVE) & (bars["BTCUSDT"][0] < D0 + 3_600_000)])
    now[0] = D0 + 86_400_000 + 1_800_000                                # the next night: only the new bars
    full = src.load("BTCUSDT", D0 - 3000 * FIVE, D0 + 86_400_000)
    assert len(full[0]) == 3000 + 288 and src.requests == len(rest.calls) <= n + 3
    with sqlite3.connect(str(tmp_path / "c" / "bars5m.db")) as c:
        assert c.execute("SELECT lo, hi FROM spans").fetchone() == (D0 - 3000 * FIVE, D0 + 86_400_000)


# ---------------------------------------------------------------- pins and the real lib_c
def test_pins_refuse_a_changed_file(tmp_path, monkeypatch):
    want = D.wanted_pins()
    assert D.LIB_C in want and D.PREREG in want and len(want) >= 6
    assert set(D.check_pins(want)) >= {"research/deepseek200/lib_c.py", "research/library/lib.py"}
    with pytest.raises(D.DsCheckError, match="lib_c.py"):
        D.check_pins(want, lib_c_bytes=b"# changed\n")
    bad = tmp_path / "ds_pins.json"
    pins = json.loads(Path(D.PINS).read_text())
    pins["lib_c.py"] = "0" * 64
    bad.write_text(json.dumps(pins))
    monkeypatch.setattr(D, "PINS", str(bad))
    with pytest.raises(D.DsCheckError, match="disagree"):
        D.wanted_pins()


def test_real_lib_c_loads_contained_and_agrees_with_the_live_job(tmp_path, monkeypatch):
    """The pinned lib_c, loaded contained, recomputed on full history, against paperbot.dssig.ds_job (the live job) at
    the real 15m window for a few boundaries: no mismatch."""
    from paperbot import dssig
    monkeypatch.setattr(D, "_C", None)
    sweepsig.lib()                                     # loaded once per process, as the service does first
    path, filters = list(sys.path), list(warnings.filters)
    C = D.load_lib_c()
    assert sys.path == path and warnings.filters == filters and C is D.load_lib_c()
    assert [d[0] for d in C.DEFS] == [d[0] for d in dssig.DS200_DEFS] and D._PINS["research/deepseek200/lib_c.py"]
    n = D.history_5m("15m") + 288
    bars = {}
    for k, coin in enumerate(D.COINS):
        ts, o, h, lo, c, v = dssig._synth5m(n, D0 + 86_400_000, 7 + k)
        bars[D.symbol_of(coin)] = (ts, o, h, lo, c, v)
    rows = []
    for b in (D0 + 4 * 900_000, D0 + 40 * 900_000, D0 + 96 * 900_000):
        for coin in D.COINS:
            sym = D.symbol_of(coin)
            ts, *cols = bars[sym]
            keep = ts + FIVE <= b
            job = (sym, "15m", b, ts[keep], *(a[keep] for a in cols))
            bt, *bcols = bars["BTCUSDT"]
            bk = bt + FIVE <= b
            job += (None if coin == "BTCUSD" else (bt[bk], *(a[bk] for a in bcols)),)
            r = dssig.ds_job(job)
            assert r["ready"], r
            rows += [{"bar_close": b, "timeframe": "15m", "strategy": d, "symbol": sym, "side": s, "atr": 1.0,
                      "ref_price": 1.0, "ref_time": b, "delay_ms": 0, "status": "SUBMITTED", "data": {}}
                     for d, s in r["sides"].items()]
    assert rows
    st = Store3(str(tmp_path / "p.db"))
    for d, _f, tfs in dssig.DS200_DEFS:
        if "15m" in tfs:
            st.add_account(f"{d}@15m", d, "15m", "ds200", D0 - 86_400_000, "v")
    st.log_signals(rows)
    # the other boundaries of the day were not computed here: the live job's own record says why (excused)
    from paperbot import sigservice
    for b in range(D0 + 900_000, D0 + 86_400_000 + 1, 900_000):
        if b not in (D0 + 4 * 900_000, D0 + 40 * 900_000, D0 + 96 * 900_000):
            st.alert(b + 61_000, "WARN", sigservice.DS_TIMEOUT_TEXT.format(secs="60", boundary=b, tfs="15m"))
    st.commit()
    st.close()
    rep = D.run_check(D.connect_ro(str(tmp_path / "p.db")), D.FrameSource(bars), D0, tfs=("15m",),
                      now_ms=D0 + 2 * 86_400_000)
    assert rep["pins"] and rep["n_mismatch"] == 0, rep["mismatches"][:5]
    assert rep["checked"] >= len(rows) and rep["agree"] == rep["checked"] and rep["uncovered_boundaries"] >= 80
    assert rep["status"] == "ok" and rep["n_excused"] >= 1


# ---------------------------------------------------------------- the units
def _unit(name):
    out, sec = {}, ""
    for ln in (REPO / "deploy" / name).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            sec = ln
            continue
        out.setdefault(sec, []).append(ln)
    return out


def test_dscheck_units_are_nightly_read_only_and_hooked_to_the_failure_warning():
    u = _unit("paperbot-dscheck.service")
    svc, unit = u["[Service]"], u["[Unit]"]
    assert "OnFailure=paperbot-failed@%n.service" in unit
    for k in ("Type=oneshot", "User=paperbot", "Group=paperbot", "Nice=15", "IOSchedulingClass=idle", "MemoryMax=1G",
              "NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=strict"):
        assert k in svc, k
    assert not any(ln.startswith(("EnvironmentFile=", "PassEnvironment=")) for ln in svc)
    ex = next(ln for ln in svc if ln.startswith("ExecStart="))
    assert "-m paperbot.dscheck run" in ex and "--db /var/lib/paperbot/paper3.db" in ex
    assert "--out /var/lib/paperbot/dscheck" in ex
    assert any(ln.startswith("TimeoutStartSec=") for ln in svc)
    paths = {k: next(ln for ln in svc if ln.startswith(k + "=")).split("=", 1)[1].split()
             for k in ("ReadWritePaths", "ReadOnlyPaths", "InaccessiblePaths")}
    assert "-/var/lib/paperbot/paper3.db" in paths["ReadOnlyPaths"] and "/opt/crypto-bot-research" in paths["ReadOnlyPaths"]
    for hidden in ("-/etc/paperbot", "-/var/lib/paperbot/exec", "-/var/backups/paperbot", "-/var/lib/paperbot/.claude"):
        assert hidden in paths["InaccessiblePaths"], hidden
    t = _unit("paperbot-dscheck.timer")
    assert "OnCalendar=*-*-* 00:30:00 UTC" in t["[Timer]"] and "Persistent=true" in t["[Timer]"]
    assert "WantedBy=timers.target" in t["[Install]"]
    # not on the trading path: no hash set names it
    from paperbot import runinfo
    hashed = set(runinfo.TRADING_FILES) | set(runinfo.EXTRA_FILES) | {f for fs in runinfo.GROUP_FILES.values() for f in fs}
    assert "paperbot/dscheck.py" not in hashed
    assert not re.search(r"^from \.(engine|policy|accounts|sigservice|live3) ", (REPO / "paperbot" / "dscheck.py")
                         .read_text(encoding="utf-8"), re.M)
