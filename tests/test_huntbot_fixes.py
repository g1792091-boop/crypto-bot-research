"""Regression tests for the huntbot review findings (feed, Telegram health, ledger, run.db, deploy kit). No network: a
fake Binance answers; synthetic bars only.

- a broken HTTP reply (IncompleteRead) is a network error (retried), not a pass-killing exception
- a pass that fails half way leaves no hole: each coin is committed on its own, a rollback forgets the cached newest
  bar per coin; the first mark waits until every coin's history is complete (a lost head is fetched again); holes
  inside the stored bars are fetched again (Binance's own gaps at most GAP_TRIES times)
- one bad exchangeInfo body ends no coin; a coin end needs END_READS reads over END_SPAN_MS without a new bar; an end
  the feed set is undone when the coin trades again within REVIVE_MS; ``feed coin-reset`` undoes it by hand
- the lag warning goes out while no cycle runs (the feed stopped), once, and 'back' when the mark moves again
- a repaint is written once
- run.db: a closed trade that changes later is recorded as changed (or gone); DeepSeek rows carry no money (the full
  versions are in <private>/trades_full.db)
- deploy: the dashboard sees only snap/ and not /etc/huntbot, may use netlink for its address wait; the install copies
  only the rule-bot files the signal path loads, refuses order code, waits for the apt lock
"""

from __future__ import annotations

import http.client
import json
import os
import re
import sqlite3
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
TESTS = os.path.dirname(os.path.abspath(__file__))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from huntbot import binance as BN  # noqa: E402
from huntbot import config as CFG  # noqa: E402
from huntbot import feed as FD  # noqa: E402
from huntbot import notify as NT  # noqa: E402
from huntbot.ledger import Ledger  # noqa: E402
from huntbot.store import Store  # noqa: E402

from test_huntbot import FakeExchange, T0, make_feed  # noqa: E402

FIVE, DAY, HOUR = CFG.FIVE, CFG.DAY, 3_600_000
D = os.path.join(ROOT, "deploy", "huntbot")


def _n_bars(st, sym):
    return st.conn.execute("SELECT COUNT(*) FROM bars_5m WHERE symbol = ?", (sym,)).fetchone()[0]


def _full(st, fd, sym):
    """Stored bars from the warm-up start to the newest one, without a hole."""
    a, b = st.first_open(sym), st.max_open(sym)
    return a == fd.warmup_ms and _n_bars(st, sym) == (b - a) // FIVE + 1


# ---------------------------------------------------------------- client
def test_broken_http_reply_is_retried_like_a_network_error():
    calls = []

    def fetch(url, headers, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise http.client.IncompleteRead(b"partial")
        if len(calls) == 2:
            raise http.client.BadStatusLine("x")
        return 200, b"[]", {}
    c = BN.Client(fetch=fetch, sleep=lambda s: None)
    assert c.klines("BTCUSDT", 0, 99) == [] and len(calls) == 3


# ---------------------------------------------------------------- feed: no hole after a failure
def test_a_pass_failing_half_way_leaves_no_hole(tmp_path):
    ex, st, fd, clock = make_feed(tmp_path, now=T0 + 6 * FIVE)
    orig = ex.fetch
    boom = {"on": True}

    def fetch(url, headers, timeout):                      # ETH's mark klines break (a parsing error, not network)
        if boom["on"] and "ETHUSDT" in url and "markPriceKlines" in url:
            raise RuntimeError("bad body")
        return orig(url, headers, timeout)
    fd.client.fetch = fetch
    info = fd.cycle()                                       # the first pass = the history download
    assert any("ETHUSDT" in e for e in info["errors"])
    assert _full(st, fd, "BTCUSDT") and _full(st, fd, "ETHUSDT")   # what was stored stays (committed per coin)
    boom["on"] = False
    ex.now += 2 * FIVE
    clock[0] = ex.now / 1000
    fd.cycle()
    assert _full(st, fd, "BTCUSDT") and _full(st, fd, "ETHUSDT")
    assert st.complete_ms() is not None


def test_rollback_forgets_the_cached_newest_bar(tmp_path):
    st = Store(str(tmp_path / "s.db"))
    st.insert_bars("BTCUSDT", [(T0 + i * FIVE, 1, 2, 0.5, 1.5, 10, 100) for i in range(5)])
    assert st.max_open("BTCUSDT") == T0 + 4 * FIVE
    st.rollback()
    assert st.max_open("BTCUSDT") is None                   # the next pass starts from the warm-up start again


def test_whole_pass_failure_in_run_forever_leaves_no_hole(tmp_path):
    ex, st, fd, clock = make_feed(tmp_path, now=T0 + 6 * FIVE)
    orig_cc = fd.compute_complete
    state = {"n": 0}

    def cc(now=None):                                       # the first pass dies after storing everything
        state["n"] += 1
        if state["n"] == 1:
            raise sqlite3.OperationalError("disk I/O error")
        return orig_cc(now)
    fd.compute_complete = cc

    class Stop(Exception):
        pass

    def sleep(s):
        if state["n"] >= 2:
            raise Stop
        ex.now += 2 * FIVE
        clock[0] = ex.now / 1000
    with pytest.raises(Stop):
        fd.run_forever(sleep=sleep)
    assert _full(st, fd, "BTCUSDT") and _full(st, fd, "ETHUSDT") and st.complete_ms() is not None


def test_a_failed_commit_forgets_the_cached_newest_bar_so_nothing_is_skipped(tmp_path):
    """ETH's bars are inserted, then the commit fails (disk full, I/O error) and is rolled back: the next pass must
    fetch them again (a kept cache of ETH's newest bar would start after them: a hole for good)."""
    ex, st, fd, clock = make_feed(tmp_path, now=T0 + 6 * FIVE)
    orig_fetch, orig_commit = ex.fetch, st.commit
    state = {"armed": False, "fails": 0}

    def fetch(url, headers, timeout):
        if "ETHUSDT" in url and "markPriceKlines" in url and state["fails"] == 0:
            state["armed"] = True                               # ETH's bars are in the open transaction now
        return orig_fetch(url, headers, timeout)

    def commit():
        if state["armed"] and state["fails"] < 2:
            state["fails"] += 1
            raise sqlite3.OperationalError("disk I/O error")
        state["armed"] = False
        return orig_commit()
    fd.client.fetch = fetch
    st.commit = commit
    info = fd.cycle()
    assert state["fails"] == 2 and any("ETHUSDT" in e for e in info["errors"])
    assert _n_bars(st, "ETHUSDT") == 0 and st.max_open("ETHUSDT") is None     # rolled back AND forgotten
    ex.now += 2 * FIVE
    clock[0] = ex.now / 1000
    fd.cycle()
    assert _full(st, fd, "BTCUSDT") and _full(st, fd, "ETHUSDT") and st.complete_ms() is not None


def test_first_mark_waits_for_the_history_and_a_lost_head_is_fetched(tmp_path):
    ex, st, fd, clock = make_feed(tmp_path, now=T0 + 6 * FIVE)
    lost = fd.warmup_ms + 300 * FIVE                        # ETH's first 300 bars were lost (stored from here on)
    rows = [ex.bar("ETHUSDT", t) for t in range(lost, T0 + 6 * FIVE - FIVE, FIVE)]
    st.insert_bars("ETHUSDT", [(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[7]) for r in rows])
    st.commit()
    fd.refresh_exchange(force=True)
    calls = []
    orig = fd.client.fetch

    def fetch(url, headers, timeout):
        calls.append(url)
        return orig(url, headers, timeout)
    fd.client.fetch = fetch
    fd.cycle()
    assert _full(st, fd, "ETHUSDT") and _full(st, fd, "BTCUSDT")
    assert st.complete_ms() == T0 + 5 * FIVE
    assert set(st.get("history_ok")) == {"BTCUSDT", "ETHUSDT"}
    # a coin listed after the warm-up start: one look at the exchange, then fine
    st2 = Store(str(tmp_path / "s2.db"), clock=lambda: clock[0])
    fd2 = FD.Feed(st2, fd.client, ["BTCUSDT"], fd.warmup_ms, clock=lambda: clock[0], log=lambda m: None)
    ex.start = fd.warmup_ms + 100 * FIVE
    rows = [ex.bar("BTCUSDT", t) for t in range(ex.start, T0, FIVE)]
    st2.insert_bars("BTCUSDT", [(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[7]) for r in rows])
    assert fd2.check_history("BTCUSDT") and st2.first_open("BTCUSDT") == ex.start


def test_holes_are_fetched_again_and_binance_gaps_tried_at_most_three_times(tmp_path):
    ex, st, fd, clock = make_feed(tmp_path, now=T0 + 6 * FIVE)
    fd.backfill()
    a = fd.warmup_ms + 50 * FIVE
    st.conn.execute("DELETE FROM bars_5m WHERE symbol = 'BTCUSDT' AND open_ms >= ? AND open_ms < ?", (a, a + 7 * FIVE))
    st.commit()
    assert st.gaps("BTCUSDT", fd.warmup_ms) == [(a, a + 7 * FIVE)]
    assert fd.repair_gaps("BTCUSDT") == {"holes": 1, "bars": 7}
    assert st.gaps("BTCUSDT", fd.warmup_ms) == [] and _full(st, fd, "BTCUSDT")
    # a hole Binance itself has: tried GAP_TRIES times, then left alone
    b = fd.warmup_ms + 90 * FIVE
    st.conn.execute("DELETE FROM bars_5m WHERE symbol = 'ETHUSDT' AND open_ms >= ? AND open_ms < ?", (b, b + 2 * FIVE))
    st.commit()
    ex.missing["ETHUSDT"] = {b, b + FIVE}
    got = [fd.repair_gaps("ETHUSDT")["holes"] for _ in range(FD.GAP_TRIES + 2)]
    assert got == [1] * FD.GAP_TRIES + [0, 0]


# ---------------------------------------------------------------- feed: coin ends
def test_one_bad_exchange_info_body_ends_no_coin(tmp_path):
    ex, st, fd, clock = make_feed(tmp_path, now=T0 + 6 * FIVE)
    fd.backfill()
    orig = ex.fetch
    bodies = [{"symbols": []}, {"symbols": [{"symbol": "ETHUSDT", "status": "TRADING"}]}]

    def fetch(url, headers, timeout):
        if "exchangeInfo" in url and bodies:
            return 200, json.dumps(bodies.pop(0)).encode(), {}
        return orig(url, headers, timeout)
    fd.client.fetch = fetch
    for _ in range(2):
        assert fd.refresh_exchange(force=True) == {}
    assert fd.trading() == ["BTCUSDT", "ETHUSDT"]
    assert all(c["end_ms"] is None and c["trading"] == 1 for c in st.coins().values())
    assert any("exchangeInfo ignored" in r["msg"] for r in st.recent_log())


def test_coin_end_undone_when_trading_again_and_by_hand(tmp_path):
    ex, st, fd, clock = make_feed(tmp_path, now=T0 + 6 * FIVE)
    fd.backfill()
    last = st.max_open("ETHUSDT")
    ex.status["ETHUSDT"] = "SETTLING"
    ex.missing["ETHUSDT"] = {last + i * FIVE for i in range(1, 2000)}
    t = T0 + 6 * FIVE
    for k in range(1, FD.END_READS + 1):
        clock[0] = (t + k * HOUR + 20_000) / 1000
        ex.now = int(clock[0] * 1000)
        fd.cycle()
    assert st.coins()["ETHUSDT"]["end_ms"] == last and fd.trading() == ["BTCUSDT"]
    # it trades again within REVIVE_MS: the end is undone and the coin polled again from its newest bar
    ex.status["ETHUSDT"] = "TRADING"
    ex.missing["ETHUSDT"] = set()
    clock[0] += (HOUR + 60_000) / 1000
    ex.now = int(clock[0] * 1000)
    fd.cycle()
    assert st.coins()["ETHUSDT"]["end_ms"] is None and fd.trading() == ["BTCUSDT", "ETHUSDT"]
    assert st.max_open("ETHUSDT") > last and _full(st, fd, "ETHUSDT")
    # ended again; trading again only after REVIVE_MS: not re-added, until coin-reset by hand
    ex.status["ETHUSDT"] = "SETTLING"
    last = st.max_open("ETHUSDT")
    ex.missing["ETHUSDT"] = {last + i * FIVE for i in range(1, 2000)}
    for k in range(1, FD.END_READS + 1):
        clock[0] += HOUR / 1000
        ex.now = int(clock[0] * 1000)
        fd.cycle()
    assert st.coins()["ETHUSDT"]["end_ms"] == last
    ex.status["ETHUSDT"] = "TRADING"
    clock[0] += (FD.REVIVE_MS + HOUR) / 1000
    ex.now = int(clock[0] * 1000)
    fd.cycle()
    c = st.coins()["ETHUSDT"]
    assert c["end_ms"] == last and "coin-reset" in (c["note"] or "") and fd.trading() == ["BTCUSDT"]
    c = fd.coin_reset("ETHUSDT")
    assert c["end_ms"] is None and c["trading"] == 1 and fd.trading() == ["BTCUSDT", "ETHUSDT"]


def test_feed_command_coin_reset(tmp_path, monkeypatch):
    ex, st, fd, clock = make_feed(tmp_path, now=T0 + 6 * FIVE)
    fd.backfill()
    st.set_coin("ETHUSDT", trading=0, end_ms=T0)
    st.commit()
    uni = tmp_path / "u.json"
    uni.write_text(json.dumps({"symbols": ["BTCUSDT", "ETHUSDT"]}))
    monkeypatch.setenv("HUNTBOT_DATA", str(tmp_path))
    monkeypatch.setenv("HUNTBOT_UNIVERSE", str(uni))
    monkeypatch.setenv("HUNTBOT_WARMUP_START", "2025-01-01")
    assert FD.main(["coin-reset", "ETHUSDT"]) == 0
    c = Store(str(tmp_path / "store.db")).coins()["ETHUSDT"]
    assert c["end_ms"] is None and c["trading"] == 1


# ---------------------------------------------------------------- Telegram health without cycles
def test_lag_warning_goes_out_while_no_cycle_runs():
    from huntbot import runner as RN
    now = [CFG.day_ms("2026-10-20") + 2 * HOUR]                 # 11:00 KST (the summary hour is past)
    rdb = sqlite3.connect(":memory:")
    rdb.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    sent = []
    nt = NT.Notifier(rdb, sender=sent.append)
    feed = {"mark": now[0] - 60_000, "hb": now[0] - 30_000}      # then the feed dies
    store = types.SimpleNamespace(complete_ms=lambda: feed["mark"], heartbeats=lambda: {"feed": {"ts_ms": feed["hb"]}})
    cycles = []
    R = types.SimpleNamespace(out=lambda m: None, systems=[], cells={}, procs=1, ledger=types.SimpleNamespace(gen=1),
                              store=store, lineup_path="/nonexistent", done_ms=None, now_ms=lambda: now[0],
                              lineup={"accounts": []}, fwd=CFG.FORWARD_START_MS, last_counts={}, notifier=nt)

    def cycle(comp):
        cycles.append(comp)
        R.done_ms = comp
        return {"seconds": 0, "phase": {}, "errors": []}
    R.cycle = cycle

    def sleep_until(limit):
        def sleep(s):
            now[0] += int(s * 1000)
            if now[0] >= limit:
                raise KeyboardInterrupt
        return sleep
    t0 = now[0]
    with pytest.raises(KeyboardInterrupt):
        RN.Runner.run_forever(R, poll_s=5.0, sleep=sleep_until(t0 + 150 * 60_000))
    warn = [t for t in sent if t.startswith("⚠ 자료 지연")]
    assert len(cycles) == 1 and len(warn) == 1, (len(cycles), sent)
    assert "늦습니다" in warn[0]
    # the feed comes back: one 'back' message, no more warnings
    feed["mark"], feed["hb"] = now[0], now[0]
    with pytest.raises(KeyboardInterrupt):
        RN.Runner.run_forever(R, poll_s=5.0, sleep=sleep_until(now[0] + 10 * 60_000))
    assert [t.split("\n")[0] for t in sent].count("✅ 자료 다시 들어옴 · 추세 사냥") == 1
    assert len([t for t in sent if t.startswith("⚠ 자료 지연")]) == 1


def test_a_feed_never_heard_from_is_told():
    rdb = sqlite3.connect(":memory:")
    rdb.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    sent = []
    nt = NT.Notifier(rdb, sender=sent.append)
    now = CFG.day_ms("2026-10-20")
    R = types.SimpleNamespace(store=types.SimpleNamespace(complete_ms=lambda: None, heartbeats=lambda: {}),
                              started_ms=now - 40 * 60_000, done_ms=None, now_ms=lambda: now)
    out = nt.check_health(R)
    assert len(out) == 1 and "huntbot-feed" in out[0] and "40분" in out[0]


# ---------------------------------------------------------------- ledger
def test_a_repaint_is_written_once(tmp_path):
    led = Ledger(str(tmp_path / "events.db"), "h")
    item = ("F2:X:15m", "BTCUSDT", "LONG", T0, "vanished")
    assert led.log_repaints([item]) == 1 and led.log_repaints([item, item]) == 0
    led.commit()
    assert led.counts()["repaints"] == 1
    # an events.db written before the rule, with repeats: folded when opened
    p = str(tmp_path / "old.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE repaints (ts_ms INTEGER NOT NULL, gen INTEGER NOT NULL, cell TEXT NOT NULL, "
              "symbol TEXT NOT NULL, side TEXT NOT NULL, bar_close_ms INTEGER NOT NULL, kind TEXT NOT NULL)")
    c.executemany("INSERT INTO repaints VALUES (?, 1, 'C', 'BTCUSDT', 'LONG', ?, 'vanished')",
                  [(i, T0) for i in range(5)] + [(9, T0 + FIVE)])
    c.commit()
    c.close()
    assert Ledger(p, "h").counts()["repaints"] == 2


# ---------------------------------------------------------------- run.db: changed trades, D11
def _runner(tmp_path, systems):
    from huntbot import bench as B
    st = Store(str(tmp_path / "store.db"))
    clock = B.FakeClock(T0)
    return B.make_test_runner(str(tmp_path), st, ["BTCUSDT"], CFG.day_ms("2025-01-01"), clock, systems=systems), clock


def _t(coin, in_ms, pnl, open_=False):
    return {"i": 0, "coin": coin, "side": 1, "pick_no": 0, "signal_close_ms": in_ms - FIVE, "in_ms": in_ms,
            "out_ms": in_ms + HOUR, "open": open_, "reason": "stop", "stop_source": "chandelier", "p0": 100.0,
            "fill": 100.05, "d0": 2.0, "first_stop": 98.0, "q1": 12.5, "lev": 5, "u": 25.0, "eq_entry": 5000.0,
            "exit_px": 103.0, "adds": 1, "adds_tried": 1, "pnl": pnl, "price_pnl": pnl, "fees": 1.0, "funding": 0.0,
            "r_mult": pnl / 25.0, "large": 1, "cut": 0}


MONEY = {"pnl", "price_pnl", "fill", "p0", "exit_px", "first_stop", "stop_now", "fees", "funding", "u", "eq_entry",
         "r_mult", "q1", "lev", "d0"}


def test_changed_and_gone_closed_trades_are_recorded_and_deepseek_rows_carry_no_money(tmp_path):
    core = {"id": "F2:FAKE:15m:NONE", "family": "F2", "name": "FAKE", "kind": "core", "tf": "15m", "gate": "NONE",
            "combo": {}}
    ds = {"id": "F3:DS:15m:NONE", "family": "F3", "name": "DS", "kind": "ds", "tf": "15m", "gate": "NONE", "combo": {}}
    r, clock = _runner(tmp_path, [core, ds])
    a, b = _t("BTCUSDT", T0 - 5 * HOUR, 12.0), _t("BTCUSDT", T0 - 3 * HOUR, -4.0)
    res = {core["id"]: {"trades": [a, b]}, ds["id"]: {"trades": [dict(a, pnl=7.0)]}}
    assert r.record_trades(res, {}, T0) == []
    r.done_ms = T0
    assert r.trade_change_counts()["changed"] == 0
    # the same cycle again: nothing new; then data for the past changes one trade and removes another
    assert r.record_trades(res, {}, T0) == []
    res2 = {core["id"]: {"trades": [dict(a, pnl=11.5, q1=12.4)]}, ds["id"]: {"trades": [dict(a, pnl=7.0)]}}
    ch = r.record_trades(res2, {}, T0 + FIVE)
    assert sorted(c["kind"] for c in ch) == ["changed", "gone"]
    cnt = r.trade_change_counts()
    assert cnt["changed"] == 2 and cnt["gone"] == 1
    row = r.rdb.execute("SELECT data, revisions FROM trades_seen WHERE account = ? AND tkey LIKE ?",
                        (core["id"], f"%|{a['in_ms']}|%")).fetchone()
    assert json.loads(row[0])["pnl"] == 12.0 and row[1] == 1                # the first version stays, counted
    new = r.rdb.execute("SELECT data FROM trade_changes WHERE kind = 'changed'").fetchone()[0]
    assert json.loads(new)["pnl"] == 11.5
    # D11: the DeepSeek system's row in run.db has no money; the private file has it
    d = json.loads(r.rdb.execute("SELECT data FROM trades_seen WHERE account = ?", (ds["id"],)).fetchone()[0])
    assert not (set(d) & MONEY) and d["coin"] == "BTCUSDT"
    p = sqlite3.connect(os.path.join(str(tmp_path), "private", "trades_full.db"))
    assert json.loads(p.execute("SELECT data FROM trades_full").fetchone()[0])["pnl"] == 7.0


def test_changed_text_hides_deepseek_money(tmp_path):
    from huntbot import systems as S
    systems, aliases = S.system_list()
    by_id = {s["id"]: s for s in systems}
    dsid = next(s["id"] for s in systems if s["kind"] == "ds")
    accts = S.parse_lineup({"accounts": [{"system": dsid, "label": "정식", "variant": "r0.5"},
                                         {"system": "F1:E1:1h:NONE", "label": "참고", "variant": "r0.5"}]},
                           by_id, aliases)
    R = types.SimpleNamespace(lineup={"accounts": accts})
    t = _t("ETHUSDT", T0, 9.5)
    ch = [{"account": f"lineup:{accts[0]['id']}", "tkey": f"ETHUSDT|1|{T0}|x", "kind": "changed", "trade": t},
          {"account": f"lineup:{accts[1]['id']}", "tkey": f"ETHUSDT|1|{T0}|x", "kind": "changed", "trade": t}]
    txt = NT.changed_text(R, ch, T0)
    ds_line = next(x for x in txt.split("\n") if "ETH" in x and "정식" in x)
    core_line = next(x for x in txt.split("\n") if "ETH" in x and "참고" in x)
    assert "$" not in ds_line and "+$9.50" in core_line


# ---------------------------------------------------------------- deploy kit
def _read(name):
    with open(os.path.join(D, name), encoding="utf-8") as fh:
        return fh.read()


def test_dashboard_sees_only_snap_and_not_the_env_file():
    u = _read("huntbot-dash.service")
    assert "TemporaryFileSystem=/var/lib/huntbot:ro" in u and "BindReadOnlyPaths=/var/lib/huntbot/snap" in u
    assert re.search(r"^InaccessiblePaths=.*-/etc/huntbot", u, re.M)
    assert not re.search(r"^ReadOnlyPaths=/var/lib/huntbot\s*$", u, re.M)
    fam = re.search(r"^RestrictAddressFamilies=(.*)$", u, re.M).group(1).split()
    assert "AF_NETLINK" in fam                              # `ip -4 -o addr show` in the address wait needs it
    assert "ip -4 -o addr show" in u


def _install_lists():
    sh = _read("install_huntbot.sh")
    pb = re.search(r'PAPERBOT_FILES="([^"]+)"', sh, re.S).group(1).replace("\\\n", " ").split()
    drop = re.search(r'DROP="([^"]+)"', sh, re.S).group(1).replace("\\\n", " ").split()
    return sh, pb, drop


def test_install_copies_only_the_rule_bot_files_the_signal_path_loads():
    from research.hunt import hunt as H
    sh, pb, drop = _install_lists()
    loaded = {f for f in H.signal_path_files("wide") if f.startswith("paperbot/")}
    assert loaded and loaded <= set(pb), sorted(loaded - set(pb))
    assert not any(p.endswith(("binance.py", "testnet.py", "live.py", "live3.py", "executor.py", "mainnet.py"))
                   for p in pb)
    assert " paperbot " not in sh.replace("\\\n", " ") and not re.search(r"[\s\"]paperbot[\s\"]", sh)


def test_install_copy_holds_no_order_code():
    import subprocess
    sh, pb, drop = _install_lists()
    paths = re.search(r'CODE_PATHS="([^"]+)"', sh, re.S).group(1).replace("\\\n", " ").replace("$PAPERBOT_FILES", "")
    paths = paths.split() + pb
    files = subprocess.run(["git", "ls-files", "--", *paths], cwd=ROOT, capture_output=True, text=True).stdout.split()
    files = [f for f in files if not any(f == d or f.startswith(d + "/") for d in drop)
             and f.endswith((".py", ".js", ".sh"))]
    rx = re.compile(re.search(r"ORDER_RE='([^']+)'", sh).group(1))
    assert len(files) > 100
    bad = [f for f in files if rx.search(open(os.path.join(ROOT, f), encoding="utf-8", errors="replace").read())]
    assert not bad, bad
    assert 'grep -rlE "$ORDER_RE"' in sh                       # and the install checks the real copy again


def test_apt_waits_for_the_lock():
    sh = _read("install_huntbot.sh")
    assert 'APT_LOCK="-o DPkg::Lock::Timeout=600"' in sh and sh.count("apt-get $APT_LOCK") == 2
    doc = open(os.path.join(ROOT, "docs", "huntbot-ko.md"), encoding="utf-8").read()
    line = next(x for x in doc.splitlines() if x.startswith("apt-get"))
    assert line.count("-o DPkg::Lock::Timeout=600") == 2 and "Could not get lock" in doc


# ---------------------------------------------------------------- the status screen shows the new counts
def test_status_screen_shows_changed_trades_and_repaints(tmp_path):
    import shutil
    import subprocess
    import test_huntbot_dash as TD
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    st = {"generated_ms": T0, "complete_ms": T0, "forward_start_ms": CFG.FORWARD_START_MS, "warmup_start_ms": T0,
          "run": {"errors": [], "phase": {}}, "feed": {"coins": [], "log": [], "stalled": []}, "engine": {},
          "universe": {}, "lineup": {}, "systems": {}, "server": {},
          "events": {"events": 10, "generation": 1, "repaints": 2},
          "trades_changed": {"changed": 3, "gone": 1, "last": []}}
    fx = {"status": st, "lineup": {"accounts": []}, "systems": {"rows": []}, "positions": {"rows": []},
          "trades": {"recent": []}, "system": {"row": {"id": "F1:E1:1h:NONE"}, "trades": []}}
    shim = tmp_path / "shim.mjs"
    src = TD.SHIM.replace("out[route] = txt.length;", 'out[route] = route === "status" ? txt : txt.length;')
    assert src != TD.SHIM
    shim.write_text(src)
    env = dict(os.environ, FIX=json.dumps(fx), APP="file://" + os.path.join(TD.STATIC, "js", "app.js"))
    r = subprocess.run([node, str(shim)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    res = json.loads(r.stdout)
    txt = res["out"]["status"]
    assert "나중에 바뀐 거래" in txt and "3건 (그중 사라진 것 1건)" in txt and "2개 (기록은 처음 본 대로 유지)" in txt
