"""The 195 original accounts are byte-identical with the extras code (tests/extras_harness.py).

The golden file tests/data/extras_parity_golden.json was written on the base commit (before any runtime
edit) by ``python -m tests.extras_harness --write-golden``: the canonical dump of the 195 for a logical run
(R0), a run with a restart (R0r), a timed run with a 30-minute outage and a catch-up burst (T0), and two crash
points (K1: killed instead of the 195's boundary save; K2: killed right after it). Here the new tree runs
the same feed (each run in its own process, in parallel) and must give exactly the same dump:

    R1 / R1r   new code, no extras                            == R0 / R0r
    R2 / R2r   new code, 3 copies and 10 new-strategy accounts == R0 / R0r
    T2         timed, extras charged 40 s per newlab compute and 5 s per poll   == T0
    T2x        T2 with the live-boundary gate off (negative control)            != T0
    K1 K2      crash points with extras off and on (K1x, K2x)                  == K1 / K2
    K3..K6     killed inside the extras hook (phase 1 before its save, inside the newlab compute,
               after a creation before the phase-2 save, after the phase-2 save) == K2
    T2c        the step loop charged (an order-book fetch costs 300 ms, a Telegram send 2 s), with extras
               == T1c, the same without extras (the extras fetch no book and send nothing before a 195 compute)
    T2cx       T2c with the step loop before that fix (every engine's fill may fetch a book)  != T1c

Then the extras themselves are checked on the R2 / R2r / T2 / crash databases.
"""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests import extras_harness as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = ("accounts", "steps", "signal_log", "alerts", "digest_items", "digest", "total")


def _golden():
    with open(H.GOLDEN) as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    g = _golden()
    have = H.versions()
    if (g["versions"]["numpy"], g["versions"]["pandas"]) != (have["numpy"], have["pandas"]):
        pytest.skip(f"PARITY GOLDEN NOT CHECKED: it was written with numpy {g['versions']['numpy']} / pandas "
                    f"{g['versions']['pandas']}, this machine has {have['numpy']} / {have['pandas']}. Regenerate it "
                    "on the base commit (python -m tests.extras_harness --write-golden), never by hand.")
    assert g["harness_version"] == H.HARNESS_VERSION and g["t0"] == H.T0 and g["crash_at"] == H.crash_boundary()
    work = tmp_path_factory.mktemp("parity")

    def one(name):
        out = os.path.join(str(work), f"{name}.json")
        r = subprocess.run([sys.executable, "-m", "tests.extras_harness", "--new-run", name,
                            "--work", os.path.join(str(work), name), "--json", out],
                           cwd=ROOT, capture_output=True, text=True, timeout=1500)
        if r.returncode != 0:
            raise RuntimeError(f"{name} failed:\n{r.stderr[-4000:]}")
        with open(out) as fh:
            return name, json.load(fh)
    workers = max(1, min(4, os.cpu_count() or 1))
    order = sorted(H.NEW_RUNS + H.CHARGED_RUNS, key=lambda n: n[0] != "R" and n[0] != "T")   # the long runs first
    with ThreadPoolExecutor(workers) as ex:
        res = dict(ex.map(one, order))
    return g["runs"], res


@pytest.mark.parametrize("name", [n for n in H.NEW_RUNS if n != "T2x"])
def test_195_equal_golden(results, name):
    golden, res = results
    r = res[name]
    want = golden[r["golden"]]
    got = r["dump"]
    diff = [k for k in KEYS if got[k] != want[k]]
    accounts = sorted(a for a in want["accounts"] if want["accounts"][a] != got["accounts"].get(a))
    assert not diff and not accounts, f"{name} vs {r['golden']}: keys {diff}, accounts {accounts[:10]}"
    assert len(got["accounts"]) == 195


def test_negative_control_sees_a_timing_leak(results):
    golden, res = results
    got, want = res["T2x"]["dump"], golden["T0"]
    assert got["signal_log"] != want["signal_log"]               # phase 2 at catch-up boundaries made the 195 late
    assert got["total"] != want["total"]


def test_195_equal_with_the_step_loop_charged(results):
    """An extra's entry or exit in the minute before a boundary must not fetch an order book (a REST call that
    ran before the 195's compute and moved their ref_time / delay_ms), and an extra's Telegram line must not be
    sent inside the step: with both charged to the clock, the 195 are equal with and without the extras."""
    _, res = results
    base, got, leak = res["T1c"], res["T2c"], res["T2cx"]
    diff = [k for k in KEYS if got["dump"][k] != base["dump"][k]]
    accounts = sorted(a for a in base["dump"]["accounts"] if base["dump"]["accounts"][a] != got["dump"]["accounts"][a])
    assert not diff and not accounts, f"T2c vs T1c: keys {diff}, accounts {accounts[:10]}"
    assert got["depth_calls"] == base["depth_calls"] > 0          # the extras added no order-book fetch
    # negative control: the leaky step loop is seen by the same comparison
    assert leak["depth_calls"] > base["depth_calls"]
    assert leak["dump"]["signal_log"] != base["dump"]["signal_log"] and leak["dump"]["total"] != base["dump"]["total"]
    # the extras still get their records: a book fetched for the 195 in the same step, else 'skipped'
    c = _db(results, "T2c")
    st = dict(c.execute("SELECT status, COUNT(*) FROM fill_costs WHERE account_id IN (SELECT account_id FROM accounts "
                        "WHERE kind IN ('copy', 'newlab')) GROUP BY status").fetchall())
    c.close()
    assert st.get("ok", 0) > 0 and st.get("skipped", 0) > 0


def _db(results, name):
    return sqlite3.connect(f"file:{results[1][name]['db']}?mode=ro", uri=True)


def _extras(conn):
    return conn.execute("SELECT account_id, kind, created_ts, parent, data FROM accounts "
                        "WHERE kind NOT IN ('strategy', 'random') ORDER BY rowid").fetchall()


def test_extras_created_at_the_first_live_boundary(results):
    from paperbot.extras import content_key_copy, content_key_newlab, parse_rule, source
    for name in ("R2", "R2r", "T2"):
        c = _db(results, name)
        rows = _extras(c)
        first = H.T0 + (H.APPROVE_AT + 2) * H.MIN
        late = H.T0 + (H.LATE_APPROVE_AT + 4) * H.MIN
        assert [r[0] for r in rows] == ["V45_AMB@15m~c1", "N23_HA_ST@5m~c2", "N12_ICHI_AO@1h~c3"] + \
            [f"NL{k}@{H.NEWLAB_SPECS[k - 1][0]}" for k in range(1, 11)], name
        assert [r[2] for r in rows] == [first] * 12 + [late]
        ag = sqlite3.connect(H.scenario_paths(results[1][name]["db"])[0])
        for aid, kind, created, parent, data in rows:
            d = json.loads(data)
            pid = d["source"]["proposal_id"]
            p_ts, tid = ag.execute("SELECT ts, trial_id FROM proposals WHERE id = ?", (pid,)).fetchone()
            t_ts = ag.execute("SELECT ts FROM trials WHERE id = ?", (tid,)).fetchone()[0]
            content = content_key_copy(parse_rule(d["rule"])) if kind == "copy" else content_key_newlab(d["spec_hash"])
            assert d["source"] == source(pid, p_ts, tid, t_ts, content)
        c.close()


def test_copy_rules_in_the_run(results):
    from paperbot.agents import labtests as LT
    c = _db(results, "R2")
    first = H.T0 + (H.APPROVE_AT + 2) * H.MIN
    # stop_atr 2.5: every entry's stop is ref - side x 2.5 x atr
    n = 0
    for data, in c.execute("SELECT data FROM outcomes WHERE account_id = 'V45_AMB@15m~c1' AND status = 'ENTERED'"):
        s = json.loads(data)["signal"]
        assert s["stop_price"] == pytest.approx(s["meta"]["ref_price"] - s["side"] * 2.5 * s["atr"], rel=1e-12)
        n += 1
    # lock_start 0.20: the copy's locks start at 0.20 (the parent's at 0.10)
    locks = [r[0] for r in c.execute("SELECT json_extract(data, '$.lock_roe') FROM trades "
                                     "WHERE account_id = 'N23_HA_ST@5m~c2' AND exit_reason = 'LOCK'")]
    assert all(x >= 0.2 - 1e-9 for x in locks)
    # skip_tag: FILTERED exactly where labtests.has_tag is true, on the parent's signals after the start
    rows = c.execute("SELECT bar_close, symbol, side, data FROM signal_log WHERE strategy = 'N12_ICHI_AO' AND "
                     "timeframe = '1h' AND status = 'SUBMITTED' AND bar_close > ?", (first,)).fetchall()
    filt = {(r[0], r[1]) for r in c.execute("SELECT step_ts, symbol FROM outcomes WHERE account_id = "
                                             "'N12_ICHI_AO@1h~c3' AND status = 'FILTERED'")}
    want = {(bc, sym) for bc, sym, side, data in rows
            if LT.has_tag("추세 반대 진입", side, json.loads(data).get("ctx") or {})}
    assert filt == want and rows
    reasons = {r[0] for r in c.execute("SELECT reason FROM outcomes WHERE status = 'FILTERED'")}
    assert reasons <= {"copy rule: skip_tag"}
    c.close()
    assert n >= 1


def test_newlab_rows_only_at_live_boundaries_and_filled(results):
    for name in ("R2", "R2r", "T2"):
        c = _db(results, name)
        created = dict((r[0], r[2]) for r in _extras(c))
        rows = c.execute("SELECT bar_close, timeframe, strategy, symbol, status, delay_ms, data FROM signal_log "
                         "WHERE strategy LIKE 'NL%'").fetchall()
        assert rows
        for bc, tf, strat, sym, status, delay, data in rows:
            aid = json.loads(data)["newlab"]["account_id"]
            assert aid == f"{strat}@{tf}" and bc > created[aid]
            assert delay <= 120_000 + H.NEWLAB_COST + 60_000, (name, bc, delay)    # computed only at live boundaries
            if status == "SUBMITTED" and bc < H.T0 + H.HOURS * H.HOUR:     # (the feed's last boundary has no next step)
                got = c.execute("SELECT COUNT(*) FROM outcomes WHERE account_id = ? AND step_ts = ? AND symbol = ?",
                                (aid, bc, sym)).fetchone()[0]
                assert got >= 1, (name, aid, bc)
        if name == "T2":                                   # none in the catch-up burst but its live last boundary
            resume = H.T0 + H.RESTART_T[0] * H.MIN
            burst = [r for r in rows if resume < r[0] < resume + H.RESTART_T[1] * H.MIN]
            assert not burst
        c.close()


def test_extras_survive_the_restart(results):
    for name in ("R2r", "T2"):
        c = _db(results, name)
        restart = H.T0 + (H.RESTART_R if name == "R2r" else H.RESTART_T[0]) * H.MIN
        assert c.execute("SELECT COUNT(*) FROM signal_log WHERE strategy LIKE 'NL%' AND bar_close > ?",
                         (restart,)).fetchone()[0] > 0
        assert c.execute("SELECT COUNT(*) FROM outcomes WHERE account_id LIKE '%~c%' AND step_ts > ?",
                         (restart,)).fetchone()[0] > 0
        st = json.loads(c.execute("SELECT data FROM state WHERE k = 'extras'").fetchone()[0])
        assert st["accounts"] == {} and st["health"]["errors"] == 0
        c.close()
    # the restored engines equal their saved states (compared by the harness right after book.load)
    for name, n in (("R2r", 13), ("T2", 13), ("K3", 12), ("K4", 12), ("K5", 12), ("K6", 13)):
        notes = results[1][name]["restore"]
        assert len(notes) == n and all(x.endswith(":same") for x in notes), (name, notes)


def test_crash_points_extras(results):
    at = H.crash_boundary()
    for name, created in (("K5", at + 5 * H.MIN), ("K6", at)):
        c = _db(results, name)
        rows = {r[0]: r[2] for r in _extras(c)}
        assert rows["NL10@30m"] == created, name           # K5: nothing durable, created at the next boundary
        st = json.loads(c.execute("SELECT data FROM state WHERE k = 'extras'").fetchone()[0])
        assert sum(1 for e in st["events"] if e["event"] == "created" and e["account_id"] == "NL10@30m") == 1
        c.close()
    c = _db(results, "K3")                                   # phase 1 lost at the kill: no copy outcome at at+1m
    assert c.execute("SELECT COUNT(*) FROM outcomes WHERE account_id LIKE '%~c%' AND step_ts = ?",
                     (at,)).fetchone()[0] == 0
    c.close()
    c = _db(results, "K6")
    assert c.execute("SELECT COUNT(*) FROM outcomes WHERE account_id LIKE '%~c%' AND step_ts = ?",
                     (at,)).fetchone()[0] > 0
    c.close()


def test_daily3_replay_with_extras_zero_mismatch(results):
    from paperbot import Brackets
    from paperbot.accounts import day_key
    from paperbot.config import V3_SYMBOLS, v3_settings
    from paperbot.daily3 import compare, day_signals, extras_of, replay, stored_trades
    day0 = H.T0 + 2 * H.HOUR                               # 2026-11-06 00:00 UTC
    feed = H.Feed(H.HOURS)
    steps = feed.steps(day0, day0 + H.DAY)
    br = {s: Brackets.example() for s in V3_SYMBOLS}
    for name in ("R2", "R2r"):
        c = _db(results, name)
        snap = json.loads(c.execute("SELECT data FROM state WHERE k = ?", (day_key(day0),)).fetchone()[0])
        ext = extras_of(c)
        assert len(ext) == 13
        rep = replay(v3_settings(), br, H.SPECS, snap, day_signals(c, day0, day0 + H.DAY, with_data=True), steps,
                     extras=ext)
        stored = stored_trades(c, day0, day0 + H.DAY)
        mism = compare({a: [t for t in ts if t.exit_time < day0 + H.DAY] for a, ts in rep.items()}, stored)
        assert mism == [], (name, [m["account_id"] for m in mism])
        assert sum(len(v) for a, v in stored.items() if a in ext) > 5
        c.close()
