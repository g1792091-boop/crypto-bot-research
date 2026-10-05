"""The DeepSeek-200 forward shadow test (paperbot/shadow200.py, research/deepseek200/FORWARD_PREREG.md).

Synthetic bars only (lib_c.synth) for the pipeline, the stages and the job; the real 2020-21 bars of data/pre2021 for the
parity check with the 5-year result's period 3. Nothing here reads a bar after 2021."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3

import numpy as np
import pandas as pd
import pytest

from paperbot import shadow200 as S

DAY = S.DAY_MS
ANCHOR = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
T0 = ANCHOR + 80 * DAY
TEST_TFS = ("30m", "1h", "4h")
PRM = S.Params(stage_days=(3, 6, 12, 18), k_survivors=5, p1_min_trades=5, p2_min_trades=3, j_min_trades=5,
               coin_min_trades=1, coins_positive_min=1, bots=30, tfs=TEST_TFS)
END = T0 + 18 * DAY + 3 * 3_600_000


@pytest.fixture(scope="module")
def C():
    return S.load_lib_c()


def synth_frames(C, tfs=TEST_TFS, days=105, seed=0):
    frames = {}
    for i, coin in enumerate(S.COINS):
        for tf in tfs:
            n = int(days * 1440 / C.TF_MIN[tf])
            d = C.synth(n, tf, seed + 10 * i + len(tf), start="2021-01-01", vol=0.004 + 0.001 * i)
            frames[(coin, tf)] = d
    return frames


@pytest.fixture(scope="module")
def built(C, tmp_path_factory):
    """One database after a single run over the whole synthetic timeline (all four stages stored by the job)."""
    path = str(tmp_path_factory.mktemp("shadow") / "s.db")
    src = S.FrameSource(synth_frames(C))
    conn = S.connect(path)
    logs = []
    rc = S.run_once(conn, C, PRM, T0, ANCHOR, src, END, {"x": "y"}, log=logs.append)
    conn.close()
    return path, rc, logs, src


def copy_db(path, tmp_path):
    dst = str(tmp_path / "c.db")
    shutil.copy(path, dst)
    return dst


# ---------------------------------------------------------------- pins
def test_real_pins_hold():
    pins = S.verify_pins()
    assert pins["lib_c"] == json.load(open(S.SUMMARY))["code_sha256"]["lib_c.py"]
    assert pins["forward"] == open(S.FORWARD_SHA).read().split()[0]


def test_job_refuses_when_lib_c_or_the_prereg_differs(tmp_path):
    lib, fwd = tmp_path / "lib_c.py", tmp_path / "FORWARD_PREREG.md"
    shutil.copy(S.LIB_C, lib)
    shutil.copy(S.FORWARD_PREREG, fwd)
    kw = dict(lib_c=str(lib), forward=str(fwd))
    assert S.verify_pins(**kw)["forward"] == S.sha256_file(S.FORWARD_PREREG)
    lib.write_text(lib.read_text() + "\n# changed\n")
    with pytest.raises(S.PinError, match="lib_c"):
        S.verify_pins(**kw)
    shutil.copy(S.LIB_C, lib)
    fwd.write_text(fwd.read_text() + "x")
    with pytest.raises(S.PinError, match="forward"):
        S.verify_pins(**kw)
    with pytest.raises(S.PinError, match="unreadable"):
        S.verify_pins(forward=str(tmp_path / "missing.md"))


def test_main_refuses_without_computing_when_a_pin_differs(tmp_path, monkeypatch, capsys):
    def bad():
        raise S.PinError("hash differs")
    monkeypatch.setattr(S, "verify_pins", bad)
    db = tmp_path / "x" / "s.db"
    assert S.main(["run", "--db", str(db)]) == 2
    assert not db.exists() and "refused" in capsys.readouterr().err


def test_a_second_job_exits_quietly(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "s.db")
    monkeypatch.setattr(S, "verify_pins", lambda: {})
    with S.writer_lock(db):
        with pytest.raises(S.Busy):
            with S.writer_lock(db):
                pass
        assert S.main(["run", "--db", db]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_prereg_numbers_are_the_defaults():
    p = S.Params()
    assert (p.stage_days, p.k_survivors, p.family_cap, p.def_tf_cap) == ((30, 60, 120, 180), 30, 3, 1)
    assert (p.p1_min_trades, p.p1_p, p.p2_min_trades, p.j_min_trades) == (50, 0.01, 30, 100)
    assert (p.coins_positive_min, p.coin_min_trades, p.alpha, p.j2_alpha, p.n_total, p.bots) == (4, 10, 0.10, 0.05, 498, 2000)
    assert abs(p.stress_extra - 0.0007) < 1e-12
    assert S._iso(S.T0_MS).startswith("2026-10-05 00:00") and S._iso(S.ANCHOR_MS).startswith("2026-06-01 00:00")
    assert S.Params.from_json(p.to_json()) == p
    text = open(S.FORWARD_PREREG, encoding="utf-8").read()
    for token in ("K = 30", "N = 342 + 156 = 498", "2,000", "0.07%p", "p_loss", "2026-06-01", "2026-10-05 00:00 UTC"):
        assert token in text, token


# ---------------------------------------------------------------- statistics
def test_cluster_stats_is_the_5_year_mean_test(C):
    rng = np.random.default_rng(3)
    y = rng.normal(0.001, 0.01, 400)
    day_ms = (rng.integers(0, 40, 400) * DAY + 5).astype(np.int64)
    m, p = C.env()["SR"].mean_test(y, day_ms // DAY)
    s = S.cluster_stats(y, day_ms)
    assert abs(s["mean"] - m) < 1e-15 and abs(s["p_win"] - p) < 1e-12
    assert abs(s["p_win"] + s["p_loss"] - 1) < 1e-12
    assert S.cluster_stats(np.zeros(0), np.zeros(0, np.int64))["n"] == 0


def test_bh_reject_matches_the_checkpoint_and_counts_missing_as_one():
    from paperbot.checkpoint import bh
    rng = np.random.default_rng(1)
    for _ in range(20):
        p = np.sort(rng.random(30) ** 3)
        assert np.array_equal(S.bh_reject(p, 0.10), bh(p, 0.10)[1])
    p = np.array([0.0004, 0.003, 0.2])
    assert S.bh_reject(p, 0.10).tolist() == [True, True, False]
    assert S.bh_reject(p, 0.10, 498).tolist() == [False, False, False]          # 0.1 / 498 = 0.0002
    assert S.bh_reject([0.0001], 0.10, 498).tolist() == [True]
    assert S.bh_reject([], 0.1).tolist() == []


def test_week_index_is_monday_based():
    mon = int(pd.Timestamp("2026-10-05", tz="UTC").timestamp() * 1000)          # a Monday
    w = S.week_index(np.array([mon - 1, mon, mon + 6 * DAY, mon + 7 * DAY]))
    assert w[1] == w[2] == w[0] + 1 == w[3] - 1


def test_prune1_rule():
    prm = S.Params()
    stats = {"15m|A|X5_TRAIL2": {"n": 60, "mean": -0.002, "p_loss": 0.004},
             "15m|B|X5_TRAIL2": {"n": 49, "mean": -0.002, "p_loss": 0.001},      # too few trades
             "15m|C|X5_TRAIL2": {"n": 80, "mean": -0.001, "p_loss": 0.02},       # not clear enough
             "15m|D|X5_TRAIL2": {"n": 80, "mean": 0.002, "p_loss": 0.9},
             "15m|E|X5_TRAIL2": {"n": 0, "mean": None, "p_loss": 1.0}}
    assert S.prune1_dropped(stats, prm) == ["15m|A|X5_TRAIL2"]


def test_prune2_selection_caps_and_order(C):
    prm = S.Params()
    fam = lambda name: C.FAMILY[name]                                           # noqa: E731
    stats = {}
    t = 5.0
    for tf in ("15m", "30m"):                                                   # F4: 3 definitions x 2 tf x 2 exits = 12 configs
        for d in ("F4_PULL", "F4_PULL_RSI", "F4_FAN"):
            for x in ("X5_TRAIL2", "X2_SL15_TP3"):
                t -= 0.1
                stats[f"{tf}|{d}|{x}"] = {"n": 100, "mean": 0.001, "t": t}
    stats["1h|F1_RSI_DIV|X5_TRAIL2"] = {"n": 100, "mean": 0.001, "t": 0.5}
    stats["1h|F2_DEMARK|X5_TRAIL2"] = {"n": 29, "mean": 0.001, "t": 9.0}        # too few trades
    stats["1h|F6_VWAP_CROSS|X5_TRAIL2"] = {"n": 100, "mean": -0.001, "t": 9.0}  # negative mean
    chosen, pool = S._select_survivors(stats, set(), prm, fam)
    assert pool == 13
    assert sum(c.split("|")[1].startswith("F4") for c in chosen) == 3           # family cap 3
    assert len({tuple(c.split("|")[:2]) for c in chosen}) == len(chosen)        # one exit per (definition, tf)
    assert chosen[0] == "15m|F4_PULL|X5_TRAIL2" and chosen[-1] == "1h|F1_RSI_DIV|X5_TRAIL2"
    chosen2, _ = S._select_survivors(stats, {"15m|F4_PULL|X5_TRAIL2"}, prm, fam)
    assert "15m|F4_PULL|X5_TRAIL2" not in chosen2
    many = {f"1h|D{i}|X5_TRAIL2": {"n": 100, "mean": 0.001, "t": 3.0 - i / 100} for i in range(40)}
    assert len(S._select_survivors(many, set(), prm, lambda name: name)[0]) == 30


# ---------------------------------------------------------------- bars
def mk_rows(start, n, span):
    return pd.DataFrame({"ts": pd.to_datetime(start + np.arange(n) * span, unit="ms", utc=True), "open": 1.0, "high": 2.0,
                         "low": 0.5, "close": 1.5, "volume": 3.0})


def test_fetch_keeps_only_closed_bars_flags_backfill_and_reports_revisions():
    conn = S.connect(":memory:")
    span = S.TF_MS["1h"]
    df = mk_rows(ANCHOR, 10, span)
    src = S.FrameSource({("BTCUSD", "1h"): df})
    now = ANCHOR + 8 * span + S.SETTLE_MS                      # bars 0..7 closed (bar 7 closes at 8*span)
    new, rev = S.fetch_series(conn, src, "BTCUSD", "1h", ANCHOR, now)
    assert (new, rev) == (8, 0)
    assert conn.execute("SELECT MAX(open_ms) FROM bars").fetchone()[0] == ANCHOR + 7 * span
    # only the newest bar is a live bar; the older ones were first seen more than 30 minutes after their close
    flags = dict(conn.execute("SELECT open_ms, backfill FROM bars"))
    assert flags[ANCHOR + 7 * span] == 0 and flags[ANCHOR + 5 * span] == 1
    assert S.fetch_series(conn, src, "BTCUSD", "1h", ANCHOR, now) == (0, 0)             # idempotent
    changed = df.copy()
    changed.loc[7, "close"] = 1.7
    new, rev = S.fetch_series(conn, S.FrameSource({("BTCUSD", "1h"): changed}), "BTCUSD", "1h", ANCHOR, now)
    assert (new, rev) == (0, 1)
    assert conn.execute("SELECT close FROM bars WHERE open_ms=?", (ANCHOR + 7 * span,)).fetchone()[0] == 1.5   # stored kept
    assert conn.execute("SELECT code FROM events").fetchone()[0] == "bar_revised"
    new, _ = S.fetch_series(conn, src, "BTCUSD", "1h", ANCHOR, ANCHOR + 12 * span, flag_all=True)
    assert new == 2 and conn.execute("SELECT backfill FROM bars WHERE open_ms=?", (ANCHOR + 9 * span,)).fetchone()[0] == 1


def test_bars_without_trades_are_left_out_of_the_frame():
    conn = S.connect(":memory:")
    df = mk_rows(ANCHOR, 6, S.TF_MS["1h"])
    df.loc[3, "volume"] = 0.0
    S.fetch_series(conn, S.FrameSource({("BTCUSD", "1h"): df}), "BTCUSD", "1h", ANCHOR, ANCHOR + 99 * DAY)
    assert len(S.load_frame(conn, "BTCUSD", "1h")) == 5 and len(S.load_frame(conn, "BTCUSD", "1h", drop_no_trade=False)) == 6
    assert len(S.load_frame(conn, "BTCUSD", "1h", upto_close_ms=ANCHOR + 3 * S.TF_MS["1h"], drop_no_trade=False)) == 3


# ---------------------------------------------------------------- F14 and per-series errors
def test_btc_context_is_aligned_by_timestamp_and_f14_failures_cost_only_f14(C):
    eth = C.synth(1500, "1h", 5)
    btc = C.synth(1500, "1h", 6)
    ent, notes = S.compute_entries(C, eth, btc.iloc[700:].reset_index(drop=True), "ETHUSD", "1h")      # shifted history
    assert not notes and "F14_SMT" in ent
    empty = btc.iloc[:0]
    ent, notes = S.compute_entries(C, eth, empty, "ETHUSD", "1h")
    assert notes == ["F14_SMT: no BTC bars"] and set(ent) >= {"F1_RSI_DIV", "F14_SMT"}
    assert not ent["F14_SMT"][0].any() and not ent["F14_SMT"][1].any()
    ent, notes = S.compute_entries(C, btc, None, "BTCUSD", "1h")
    assert not notes

    class Boom:
        SEED = C.SEED

        @staticmethod
        def entries(df, tf, ctx, coin):
            if ctx is not None:
                raise IndexError("index -1 is out of bounds")
            return C.entries(df, tf, None, coin)
    ent, notes = S.compute_entries(Boom, eth, btc, "ETHUSD", "1h")
    assert len(notes) == 1 and "F14_SMT context failed" in notes[0] and "F1_RSI_DIV" in ent


def test_one_series_failing_never_stops_the_others(C, monkeypatch):
    prm = S.Params(stage_days=(3, 6, 12, 18), tfs=("1h",), bots=5)
    src = S.FrameSource(synth_frames(C, ("1h",)))
    orig = S.compute_entries

    def flaky(Cm, df, btc, coin, tf):
        if coin == "LTCUSD":
            raise RuntimeError("boom")
        return orig(Cm, df, btc, coin, tf)
    monkeypatch.setattr(S, "compute_entries", flaky)
    conn = S.connect(":memory:")
    rc = S.run_once(conn, C, prm, T0, ANCHOR, src, T0 + 5 * DAY, {}, stages=False, log=lambda s: None)
    assert rc == 0
    ev = conn.execute("SELECT level, code, detail FROM events").fetchall()
    assert [e[1] for e in ev] == ["signal_error"] and "LTCUSD@1h" in ev[0][2]
    done = {r[0] for r in conn.execute("SELECT coin FROM marks")}
    assert done == set(S.COINS) - {"LTCUSD"}


def test_a_stale_series_fails_the_run_and_a_fetch_error_does_not_stop_the_rest(C):
    prm = S.Params(stage_days=(3, 6, 12, 18), tfs=("1h",), bots=5)
    frames = synth_frames(C, ("1h",))

    class Src(S.FrameSource):
        def klines(self, coin, tf, start_ms, limit=1500):
            if coin == "SOLUSD":
                raise OSError("network down")
            return super().klines(coin, tf, start_ms, limit)
    conn = S.connect(":memory:")
    rc = S.run_once(conn, C, prm, T0, ANCHOR, Src(frames), T0 + 5 * DAY, {}, stages=False, log=lambda s: None)
    codes = [r[0] for r in conn.execute("SELECT code FROM events")]
    assert rc == 1 and "fetch_error" in codes and "stale" in codes
    assert conn.execute("SELECT COUNT(*) FROM marks").fetchone()[0] == 5


# ---------------------------------------------------------------- the whole pipeline
def test_pipeline_ran_and_stored_signals_trades_and_all_stages(built):
    path, rc, logs, _ = built
    conn = sqlite3.connect(path)
    assert rc == 0
    assert conn.execute("SELECT COUNT(*) FROM marks").fetchone()[0] == 18
    sig = conn.execute("SELECT COUNT(*), MIN(open_ms) FROM signals").fetchone()
    assert sig[0] > 200 and sig[1] >= T0                                        # nothing before T0
    assert conn.execute("SELECT COUNT(*) FROM signals WHERE backfill=0").fetchone()[0] < sig[0]
    tr = conn.execute("SELECT COUNT(*), SUM(net IS NULL) FROM trades").fetchone()
    assert tr[0] > 100 and not tr[1]
    assert {r[0] for r in conn.execute("SELECT DISTINCT exit FROM trades")} == {"X5_TRAIL2", "X2_SL15_TP3"}
    # every stored trade is final: its exit is a real exit or the 48-bar limit
    assert conn.execute("SELECT COUNT(*) FROM trades WHERE reason='EOD' AND hold<48").fetchone()[0] == 0
    stages = [r[0] for r in conn.execute("SELECT stage FROM snapshots ORDER BY created_ms, stage")]
    assert sorted(stages) == sorted(S.STAGES)
    assert [l for l in logs if l.startswith("stage ")] == [f"stage {s} stored" for s in S.STAGES]


def test_idempotent_and_anchored_incremental_runs_give_the_same_signals(C, built, tmp_path):
    path, _, _, src = built
    conn = S.connect(str(tmp_path / "inc.db"))
    for now in (T0 + 5 * DAY + 1234, T0 + 11 * DAY + 77, T0 + 11 * DAY + 100, END):       # 4 runs, one a pure repeat
        S.run_once(conn, C, PRM, T0, ANCHOR, src, now, {}, log=lambda s: None)
    one = sqlite3.connect(path)
    q = "SELECT tf, def, coin, open_ms, side FROM signals ORDER BY 1,2,3,4"
    assert conn.execute(q).fetchall() == one.execute(q).fetchall()
    q = "SELECT tf, def, exit, coin, signal_ms, net FROM trades ORDER BY 1,2,3,4,5"
    assert conn.execute(q).fetchall() == one.execute(q).fetchall()
    assert conn.execute("SELECT COUNT(*) FROM events WHERE level='CRITICAL'").fetchone()[0] == 0
    q = "SELECT result_sha FROM snapshots ORDER BY stage"
    assert conn.execute(q).fetchall() == one.execute(q).fetchall()                      # same stage results


def test_backfill_marks_everything_and_runs_no_stage(C, built, tmp_path):
    _, _, _, src = built
    conn = S.connect(str(tmp_path / "bf.db"))
    S.run_once(conn, C, PRM, T0, ANCHOR, src, END, {}, flag_all=True, stages=False, log=lambda s: None)
    assert conn.execute("SELECT COUNT(*) FROM bars WHERE backfill=0").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM signals WHERE backfill=0").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
    assert conn.execute("SELECT kind FROM runs").fetchone()[0] == "backfill"
    # a later normal run adds the stages on the same data
    S.run_once(conn, C, PRM, T0, ANCHOR, src, END, {}, log=lambda s: None)
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 4


def test_t0_and_parameters_cannot_change_in_an_existing_database(C, built):
    path, _, _, src = built
    conn = sqlite3.connect(path)
    with pytest.raises(S.PinError):
        S.init_meta(conn, S.Params(k_survivors=31, **{k: v for k, v in vars(PRM).items() if k != "k_survivors"}), T0, ANCHOR, 0)
    with pytest.raises(S.PinError):
        S.init_meta(conn, PRM, T0 + 1, ANCHOR, 0)
    S.init_meta(conn, PRM, T0, ANCHOR, 0)


def test_stage_results(C, built):
    path = built[0]
    conn = sqlite3.connect(path)
    p1, p2, j1, j2 = (S.get_snapshot(conn, s)["result"] for s in S.STAGES)
    t0 = T0
    assert p1["window_ms"] == [t0, t0 + 3 * DAY] and p2["window_ms"] == [t0, t0 + 6 * DAY]
    assert j1["window_ms"] == [t0 + 6 * DAY, t0 + 12 * DAY] and j2["window_ms"] == [t0 + 12 * DAY, t0 + 18 * DAY]
    judged = {S.config_id(*c) for c in S.judged_configs(C, PRM)}
    assert set(p1["stats"]) == judged and all(not c.startswith("4h|") for c in judged)
    assert set(p1["dropped"]) <= judged
    assert p2["survivors"] and len(p2["survivors"]) <= PRM.k_survivors
    assert not set(p2["survivors"]) & set(p1["dropped"])
    assert all(not c.startswith("4h|") for c in p2["survivors"])               # 4h is observation only
    assert j1["family_size"] == len(p2["survivors"]) and set(j1["rows"]) == set(p2["survivors"])
    for cid, r in j1["rows"].items():
        assert r["p_win"] is not None and 0 < r["p_win"] <= 1
        if r["guards"]["n_ok"]:
            assert 0 < r["p_coin_flip"] <= 1
            assert r["candidate"] == (r["pass_p"] and r["pass_coin_flip"] and r["guards"]["stress_ok"] and r["guards"]["coins_ok"]
                                      and r["guards"]["halves_ok"] and r["guards"]["week_ok"])
        else:
            assert r["p_coin_flip"] is None and not r["candidate"] and cid in j1["unjudgeable"]
    assert set(j1["strong"]) <= set(j1["candidates"])
    assert set(j2["candidates"]) <= set(j1["candidates"]) and j2["confirmed"] == j2["candidates"]
    assert set(j1["pruning_check"]) == {"survivors_mean", "survivors_trades", "others_mean", "others_trades"}


def test_judge_windows_use_only_their_own_trades(C, built):
    conn = sqlite3.connect(built[0])
    lo, hi = T0 + 6 * DAY, T0 + 12 * DAY
    tr, _ = S.window_trades(conn, C, PRM, lo, hi)
    assert len(tr) > 0
    assert tr["sig_close_ms"].min() >= lo and tr["sig_close_ms"].max() < hi
    assert (tr["tf"] != "4h").all()
    tr2, _ = S.window_trades(conn, C, PRM, lo, hi, {"1h|F4_PULL|X5_TRAIL2"})
    assert set(tr2["def"]) <= {"F4_PULL"} and set(tr2["exit"]) <= {"X5_TRAIL2"}
    # a window computed twice is identical (and its hash is stable)
    again, _ = S.window_trades(conn, C, PRM, lo, hi)
    assert S.trades_sha(again) == S.trades_sha(tr)


def test_open_trade_at_the_cutoff_is_valued_not_dropped(C, built):
    conn = sqlite3.connect(built[0])
    lo, hi = T0, T0 + 6 * DAY
    tr, _ = S.window_trades(conn, C, PRM, lo, hi)
    assert (~tr["closed"]).sum() >= 0
    opened = tr[~tr["closed"]]
    # an open trade is exited at the last bar of the window (valued with its exit cost), never later
    assert (opened["exit_ms"] <= hi - 1).all()


def test_coin_flip_is_seeded_and_bounded(C, built):
    conn = sqlite3.connect(built[0])
    lo, hi = T0 + 6 * DAY, T0 + 12 * DAY
    survivors = S.get_snapshot(conn, "prune2")["result"]["survivors"]
    cid = survivors[0]
    tf, name, x = cid.split("|")
    tr, ctxs = S.window_trades(conn, C, PRM, lo, hi, {cid})
    mean = float(tr["net"].mean())
    p1 = S.coin_flip_p(C, ctxs, tf, name, x, mean, PRM, "seed-a", 40)
    assert p1 == S.coin_flip_p(C, ctxs, tf, name, x, mean, PRM, "seed-a", 40)
    assert 1 / 41 <= p1 <= 1.0
    assert S.coin_flip_p(C, ctxs, tf, name, x, 10.0, PRM, "seed-a", 40) == 1 / 41       # nothing beats +1000% per trade
    assert S.coin_flip_p(C, ctxs, tf, name, x, -10.0, PRM, "seed-a", 40) >= 0.9         # (almost) every bot beats -1000%
    assert S.coin_flip_p(C, {}, tf, name, x, mean, PRM, "seed-a", 5) is None


# ---------------------------------------------------------------- stage commands by hand
def test_a_stage_is_stored_once_and_cannot_be_changed(C, built, tmp_path):
    db = copy_db(built[0], tmp_path)
    conn = S.connect(db)
    with pytest.raises(S.StageError, match="already stored"):
        S.run_stage(conn, C, "prune1", END)
    again = S.run_stage(conn, C, "prune1", END, store=False)                 # --dry-run: computes, stores nothing
    assert again["dropped"] == S.get_snapshot(conn, "prune1")["result"]["dropped"]
    conn.execute("UPDATE snapshots SET result_json = replace(result_json, '\"dropped\"', '\"droppedX\"') WHERE stage='prune1'")
    conn.commit()
    with pytest.raises(S.StageError, match="changed after"):
        S.get_snapshot(conn, "prune1")


def test_stage_order_and_data_readiness(C, built, tmp_path):
    db = str(tmp_path / "fresh.db")
    _, _, _, src = built
    conn = S.connect(db)
    S.run_once(conn, C, PRM, T0, ANCHOR, src, T0 + 2 * DAY, {}, log=lambda s: None)
    with pytest.raises(S.StageError, match="not complete"):
        S.run_stage(conn, C, "prune1", T0 + 2 * DAY)
    assert S.due_stages(conn, PRM, T0, T0 + 3 * DAY + 3_600_000) == []
    assert S.due_stages(conn, PRM, T0, T0 + 3 * DAY + 2 * 3_600_000) == ["prune1"]
    S.run_once(conn, C, PRM, T0, ANCHOR, src, T0 + 6 * DAY + 3 * 3_600_000, {}, log=lambda s: None)
    assert S.get_snapshot(conn, "prune1") and S.get_snapshot(conn, "prune2") and not S.get_snapshot(conn, "judge1")
    conn2 = S.connect(str(tmp_path / "fresh2.db"))
    S.run_once(conn2, C, PRM, T0, ANCHOR, src, T0 + 6 * DAY + 3 * 3_600_000, {}, stages=False, log=lambda s: None)
    with pytest.raises(S.StageError, match="needs prune1"):
        S.run_stage(conn2, C, "prune2", END)
    with pytest.raises(S.StageError, match="unknown"):
        S.run_stage(conn2, C, "judge3", END)


def test_the_stage_commands_run_by_hand(built, tmp_path, monkeypatch, capsys):
    db = copy_db(built[0], tmp_path)
    monkeypatch.setattr(S, "verify_pins", lambda: {})
    c = sqlite3.connect(db)
    c.execute("DELETE FROM snapshots WHERE stage IN ('judge1','judge2')")
    c.commit()
    c.close()
    end = str(END)
    assert S.main(["stage", "judge1", "--db", db, "--bots", "20", "--dry-run", "--now-ms", end]) == 0
    out = capsys.readouterr().out
    assert "judge1" in out and "저장하지 않음" in out
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2
    assert S.main(["stage", "judge1", "--db", db, "--bots", "20", "--now-ms", end]) == 0
    assert S.main(["stage", "judge2", "--db", db, "--bots", "20", "--now-ms", end]) == 0
    assert S.main(["stage", "judge2", "--db", db, "--now-ms", end]) == 2                   # already stored
    assert "already stored" in capsys.readouterr().err
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 4
    assert S.main(["interim", "--db", db, "--now-ms", end]) == 0
    assert "정보" in capsys.readouterr().out


def test_status_shows_counts_and_never_a_performance_number(built, capsys):
    conn = sqlite3.connect(built[0])
    text = S.status_text(conn, END)
    assert "signals" in text and "closed trades" in text and "stage prune1: stored" in text
    for word in ("mean", "p_win", "profit", "%", "net"):
        assert word not in text
    assert "T0 2021-03-22" in text


def test_interim_needs_prune2_and_is_information_only(C, built, tmp_path):
    conn = sqlite3.connect(built[0])
    out = S.interim(conn, C, END)
    assert out["note"].startswith("중간 점검") and set(out["stats"]) == set(S.get_snapshot(conn, "prune2")["result"]["survivors"])
    empty = S.connect(":memory:")
    S.init_meta(empty, PRM, T0, ANCHOR, 0)
    with pytest.raises(S.StageError, match="needs prune2"):
        S.interim(empty, C, END)


# ---------------------------------------------------------------- parity with the 5-year result (real 2020-21 bars)
@pytest.mark.skipif(not os.path.exists(os.path.join(S.PRE_DIR, "ethusd-4h.csv.gz")) or not os.path.exists(S.RESULTS),
                    reason="needs data/pre2021 and the 5-year results.csv")
def test_parity_with_the_5_year_period_3_on_real_bars():
    defs = {"F1_RSI_DIV", "F3_BOS", "F7_RF_TRIPLE", "F10_M2022", "F14_SMT", "F15_ORB", "F9_FVG", "F17_Z_HL"}
    out = S.parity(tfs=("4h", "1h"), defs=defs, log=lambda s: None)
    assert out["configs"] >= 30 and out["different"] == 0, [r for r in out["rows"] if not r["same"]][:3]
    assert any(r["n_here"] > 50 for r in out["rows"])


def test_the_job_has_no_account_order_or_telegram_code():
    text = open(S.__file__, encoding="utf-8").read()
    for word in ("from .notify", "import notify", "from .accounts", "AccountBook", "paper3.db", "api_key=", "signed=True", "newOrder"):
        assert word not in text, word


def test_modules_it_reads_are_not_edited_by_it():
    pins = S.verify_pins()
    assert hashlib.sha256(open(S.LIB_C, "rb").read()).hexdigest() == pins["lib_c"]


# ---------------------------------------------------------------- the real source, the command line, the operations files
def test_binance_source_reads_public_klines_only(C):
    import urllib.parse
    from paperbot.binance import BinanceREST
    span = S.TF_MS["1h"]
    seen = []

    def fake(url, headers):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        seen.append((urllib.parse.urlparse(url).path, headers, q))
        start = int(q["startTime"][0])
        rows = [[start + k * span, "1.0", "2.0", "0.5", "1.5", "7.0", start + k * span + span - 1, "0", 1, "0", "0", "0"] for k in range(5)]
        return 200, json.dumps(rows).encode(), {}
    conn = S.connect(":memory:")
    now = ANCHOR + 4 * span + S.SETTLE_MS
    new, _ = S.fetch_series(conn, S.BinanceSource(BinanceREST(fetch=fake)), "ETHUSD", "1h", ANCHOR, now)
    assert new == 4                                                           # the fifth bar is still forming
    path, headers, q = seen[0]
    assert path == "/fapi/v1/klines" and q["symbol"] == ["ETHUSDT"] and q["interval"] == ["1h"]
    assert "X-MBX-APIKEY" not in headers and "signature" not in q and "timestamp" not in q


def test_command_line_run_with_the_real_parameters_on_synthetic_files(C, tmp_path, monkeypatch, capsys):
    """The default T0 / anchor / parameters, 22 days after T0, files instead of Binance (synthetic bars, no real data)."""
    for i, coin in enumerate(S.COINS):
        for tf in S.TFS:
            n = int(150 * 1440 / C.TF_MIN[tf])
            x = C.synth(n, tf, 100 + 7 * i + len(tf), start="2026-06-01", vol=0.003 + 0.001 * i)
            x["ts"] = x["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            x.to_csv(tmp_path / f"{coin.lower()}-{tf}.csv.gz", index=False)
    monkeypatch.setattr(S, "verify_pins", lambda: {})
    now = int(pd.Timestamp("2026-10-27 00:02", tz="UTC").timestamp() * 1000)
    db = str(tmp_path / "x" / "shadow200.db")
    args = ["run", "--db", db, "--bars-dir", str(tmp_path), "--now-ms", str(now), "--pause", "0"]
    assert S.main(args) == 0
    before = sqlite3.connect(db).execute("SELECT COUNT(*), SUM(backfill) FROM signals").fetchone()
    assert before[0] > 1000 and S.main(args) == 0                               # a repeat changes nothing
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*), SUM(backfill) FROM signals").fetchone() == before
    assert c.execute("SELECT value FROM meta WHERE key='t0_ms'").fetchone()[0] == str(S.T0_MS)
    assert S.Params.from_json(c.execute("SELECT value FROM meta WHERE key='params'").fetchone()[0]) == S.Params()
    assert c.execute("SELECT MIN(open_ms) FROM bars").fetchone()[0] == S.ANCHOR_MS
    assert c.execute("SELECT MIN(open_ms) FROM signals").fetchone()[0] >= S.T0_MS
    assert c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0       # day 22: no stage is due
    capsys.readouterr()
    assert S.main(["status", "--db", db, "--now-ms", str(now)]) == 0
    assert "day 22.0" in capsys.readouterr().out
    assert S.main(["backfill", "--db", db, "--bars-dir", str(tmp_path), "--now-ms", str(now), "--pause", "0"]) == 0
    assert S.main(["stage", "prune1", "--db", db, "--now-ms", str(now)]) == 2   # day 30 has not come: its bars are missing
    assert "not complete" in capsys.readouterr().err


def test_operations_files():
    from paperbot import failalert, launchcheck, offsite
    assert "paperbot-shadow200.timer" in launchcheck.OPTIONAL_TIMERS and "paperbot-shadow200.service" in launchcheck.ALL_UNITS
    assert "paperbot-shadow200.timer" in launchcheck.ALL_UNITS
    name, again = failalert.JOBS_KO["paperbot-shadow200.service"]
    assert "그림자" in name and "paperbot.shadow200 status" in again
    assert "shadow200/shadow200" in offsite.DB_NAMES


def test_none_of_its_files_is_in_a_hashed_or_watched_list():
    """The shadow test adds files only: no file of the trading code, the extras, the gate, the shared signal input or
    the owners' rules documents (paperbot/runinfo.py) is one of them, so no deploy of it restarts a 30-day window."""
    from paperbot import runinfo
    mine = {"paperbot/shadow200.py", "tests/test_shadow200.py", "deploy/paperbot-shadow200.service",
            "deploy/paperbot-shadow200.timer", "research/deepseek200/FORWARD_PREREG.md", "research/deepseek200/FORWARD_PREREG.sha256"}
    for name in ("TRADING_FILES", "EXTRA_FILES", "EXTRA_GATE_FILES", "SHARED_SIGNAL_FILES", "RULES_FILES"):
        assert not mine & set(getattr(runinfo, name)), name
