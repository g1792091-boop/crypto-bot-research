"""Regressions for the live-review confirm pass (2026-10): the order keys readable through /proc at every executor
start (the executor and the drill now run as their own user), and nine smaller protection gaps. Fake exchange only:
every test here runs with sockets blocked (one test runs a real `setpriv` child process, only as root)."""

import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

import pytest

from fakefutures import FakeFutures
from paperbot import executor as X
from paperbot import launchcheck as L
from paperbot import risk as R
from paperbot.executor import ExecStore, Paper3Source, Refused
from paperbot.notify import CRITICAL, WARN
from paperbot.testnet import ProtectionError, TestnetClient, place_stop
from test_executor import BTC, T0, World
from test_launchcheck import Server, fixes, st
from test_live_mainnet import Live, Paper
from test_live_review_fixes import mainnet_with_open_trade, partial_reduce_only

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def w(tmp_path):
    world = World(tmp_path)
    yield world
    world.store.close()


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def loops(w, n):
    errors = []
    for _ in range(n):
        try:
            w.loop()
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    return errors


class Timeline:
    """A notifier that records how many exchange requests had been made when each alert was sent."""

    def __init__(self, fake):
        self.fake, self.messages = fake, []

    def send(self, level, text):
        self.messages.append((len(self.fake.calls), level, text))


def call_index(fake, method, path, after=0):
    return next(i for i, c in enumerate(fake.calls) if i >= after and c[:2] == (method, path))


# ------------------------------------------------------------------ 1. the order keys: the executor's own user
def _unit(rel):
    return [x.strip() for x in _read(rel).splitlines() if x.strip() and not x.lstrip().startswith("#")]


def test_the_executor_runs_as_its_own_user_never_the_agents_and_dashboard_user():
    unit = _unit("deploy/paperbot-executor.service")
    for line in ("User=paperbot-exec", "Group=paperbot", "UMask=0027", "EnvironmentFile=/etc/paperbot/executor.env",
                 "ReadWritePaths=/var/lib/paperbot/exec", "NoNewPrivileges=yes", "ProtectSystem=strict",
                 "LimitCORE=0"):
        assert line in unit, line
    assert not [x for x in unit if x.startswith("ReadWritePaths=") and x != "ReadWritePaths=/var/lib/paperbot/exec"]
    for svc in sorted(os.listdir(os.path.join(REPO, "deploy"))):
        if not svc.endswith(".service") or svc == "paperbot-executor.service":
            continue
        lines = _unit(f"deploy/{svc}")
        assert "User=paperbot-exec" not in lines, svc                         # nothing else runs as the executor
        assert "EnvironmentFile=/etc/paperbot/executor.env" not in lines, svc  # and nothing else gets its keys
    for svc in ("deploy/paperbot-agents.service", "deploy/paperbot-dash.service"):
        assert "User=paperbot" in _unit(svc), svc                              # the agents and the dashboard: paperbot
    wrapper = _read("deploy/paperbot-exec.sh")
    assert "--uid=paperbot-exec --gid=paperbot" in wrapper and "--uid=paperbot " not in wrapper
    assert "EnvironmentFile=/etc/paperbot/executor.env" in wrapper and "ReadWritePaths=/var/lib/paperbot/exec" in wrapper


def test_install_sh_makes_the_executor_user_and_keeps_the_key_file_root_only():
    body = _read("deploy/install.sh").split("cat <<'NEXT'")[0]
    lines = [x.strip() for x in body.splitlines()]
    make_user = body.index("useradd --system --gid paperbot --no-create-home --home-dir /var/lib/paperbot/exec")
    assert body.index("useradd --system --create-home --home-dir /var/lib/paperbot") < make_user  # group paperbot first
    assert '[ "$(id -u paperbot-exec)" = "$(id -u paperbot)" ]' in body                # never the same user
    assert "install -d -o paperbot-exec -g paperbot -m 750 /var/lib/paperbot/exec" in lines
    assert "chown -R paperbot-exec:paperbot /var/lib/paperbot/exec" in lines           # earlier files move over
    assert "chmod -R u+rwX,g+rX,g-w,o-rwx /var/lib/paperbot/exec" in lines             # group reads, never writes
    assert 'install -o root -g root -m 600 "$APP/deploy/executor.env.example" /etc/paperbot/executor.env' in lines
    assert ("[ -f /etc/paperbot/executor.env ] && chmod 600 /etc/paperbot/executor.env && "
            "chown root:root /etc/paperbot/executor.env") in lines
    assert make_user < body.index("install -d -o paperbot-exec -g paperbot -m 750 /var/lib/paperbot/exec")


@pytest.mark.skipif(not sys.platform.startswith("linux") or os.geteuid() != 0 or not shutil.which("setpriv"),
                    reason="needs root and setpriv to run processes as two users")
def test_a_process_of_another_user_cannot_read_the_keys_even_in_the_same_group():
    """What the dedicated user relies on (Linux): /proc/<pid>/environ is readable by the same user only, from the
    process's first instruction (no start-up window), whatever groups the two users share."""
    owner, other, group = 64101, 64102, 64100
    target = subprocess.Popen(["setpriv", f"--reuid={owner}", f"--regid={group}", "--clear-groups", "env",
                               "LIVE_API_SECRET=never-readable-by-paperbot", "sleep", "20"], cwd="/")
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with open(f"/proc/{target.pid}/status") as fh:
                    if f"Uid:\t{owner}" in fh.read():
                        break
            except OSError:
                pass
            time.sleep(0.05)

        def read_as(uid):
            return subprocess.run(["setpriv", f"--reuid={uid}", f"--regid={group}", "--clear-groups", "cat",
                                   f"/proc/{target.pid}/environ"], capture_output=True, cwd="/", timeout=10)
        same, another = read_as(owner), read_as(other)
        assert b"never-readable-by-paperbot" in same.stdout                     # the test can see the keys at all
        assert another.returncode != 0 and b"never-readable" not in another.stdout
    finally:
        target.kill()
        target.wait()


def test_launchcheck_checks_the_executor_user(tmp_path):
    srv = Server(tmp_path)
    states = srv.units
    good = L.check_executor_user(srv.ctx(), states)
    assert st(good) == [L.OK] and "paperbot-exec" in good[0][1]
    assert L.check_executor_user(srv.ctx(), {}) == []                         # executor not installed: nothing to say
    states[L.EXECUTOR]["User"] = "paperbot"                                     # the unit of an older install.sh
    assert any("paperbot 사용자로 돕니다" in f for f in fixes(L.check_executor_user(srv.ctx(), states)))
    states[L.EXECUTOR]["User"] = ""                                             # no User=: root
    assert any("root 사용자로 돕니다" in f for f in fixes(L.check_executor_user(srv.ctx(), states)))
    states[L.EXECUTOR]["User"] = L.EXEC_USER
    srv.uids[L.EXEC_USER] = srv.uids["paperbot"]                                 # the same uid as paperbot
    assert any("같은 사용자 번호" in f for f in fixes(L.check_executor_user(srv.ctx(), states)))
    del srv.uids[L.EXEC_USER]
    assert "가 없습니다" in fixes(L.check_executor_user(srv.ctx(), states))[0]
    srv.uids[L.EXEC_USER] = 997
    exec_dir = os.path.join(srv.lib, "exec")
    srv.owners[exec_dir] = (0o750, "paperbot", "paperbot")                      # paperbot could change its records
    assert any(exec_dir in f for f in fixes(L.check_executor_user(srv.ctx(), states)))
    srv.owners[exec_dir] = (0o770, L.EXEC_USER, "paperbot")                     # group may write: no
    assert fixes(L.check_executor_user(srv.ctx(), states))
    srv.owners[exec_dir] = (0o750, L.EXEC_USER, "paperbot")
    paper = srv.make_db(start=None)
    srv.owners[paper] = (0o600, "paperbot", "paperbot")                         # the executor could not follow it
    assert any("chmod g+r" in f for f in fixes(L.check_executor_user(srv.ctx(), states)))
    sections, _secrets, _cmd = L.run_checks(srv.ctx(), "before", agents="no")
    assert any(title.startswith("주문 실행기 사용자") for title, _lines in sections)


def test_launchcheck_wants_the_executor_files_owned_by_the_executor_user(tmp_path):
    srv = Server(tmp_path)
    assert st(L.check_data_dir(srv.ctx())) == [L.OK]
    db = os.path.join(srv.lib, "exec", "executor-testnet.db")
    open(db, "w").close()
    srv.owners[db] = (0o640, L.EXEC_USER, "paperbot")
    assert st(L.check_data_dir(srv.ctx())) == [L.OK]
    srv.owners[db] = (0o644, "paperbot", "paperbot")                            # left by an older install
    f = fixes(L.check_data_dir(srv.ctx()))
    assert len(f) == 1 and db in f[0] and f"sudo chown -R paperbot-exec:paperbot {srv.lib}/exec" in f[0]


def test_the_executor_reads_paper3_db_it_cannot_create_files_next_to(tmp_path):
    """The executor's user may read paper3.db but not create its -wal/-shm (the paper runner's folder): a WAL
    database whose writer stopped (no -wal, no -shm) is read immutable, nothing is created; while the writer runs
    the normal read sees what is only in its -wal yet."""
    paper = Paper(str(tmp_path / "paper3.db"))
    paper.enter(T0, qty=5.0, leverage=20)
    paper.s.close()
    path = str(tmp_path / "paper3.db")
    assert not os.path.exists(path + "-wal") and not os.path.exists(path + "-shm")
    intent, ts = Paper3Source(path, "S1@15m").read()
    assert intent.symbol == BTC and ts == T0
    assert not os.path.exists(path + "-wal") and not os.path.exists(path + "-shm")
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("UPDATE state SET ts = ? WHERE k = 'accounts'", (T0 + 60_000,))
    writer.commit()                                                             # only in the -wal so far
    try:
        assert Paper3Source(path, "S1@15m").read()[1] == T0 + 60_000
    finally:
        writer.close()


def test_the_executor_database_goes_back_to_rollback_mode_on_a_clean_close(tmp_path):
    """The nightly backup and the owners' read-only commands run as paperbot: they can read the executor's files
    (group) but not create a -wal/-shm in its folder, which a read-only open of a WAL database needs once the writer
    is gone."""
    path = str(tmp_path / "exec.db")
    store = ExecStore(path)
    store.event(1, "INFO", "x", "y")
    store.close()
    with open(path, "rb") as fh:
        head = fh.read(20)
    assert (head[18], head[19]) == (1, 1) and not os.path.exists(path + "-wal")
    store = ExecStore(path)                                                     # and WAL again while it runs
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    store.close()


def test_an_executor_command_run_as_the_wrong_user_says_which_user(tmp_path, monkeypatch):
    def denied(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(X, "open", denied, raising=False)
    with pytest.raises(Refused) as e:
        ExecStore(str(tmp_path / "exec.db"))
    assert "sudo -u paperbot-exec" in str(e.value)


# ------------------------------------------------------------------ 2. docs/live-safety.md matches the code
def test_live_safety_doc_describes_the_executor_user_and_the_remaining_gaps():
    doc = _read("docs/live-safety.md")
    sec19 = doc.split("### 1-9.")[1].split("### 1-10.")[0]
    assert "paperbot-exec" in sec19 and "/proc/<번호>/environ" in sec19
    assert "켜지자마자 이것을 막습니다" not in doc                                 # the old, wrong claim
    assert "sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor clear-halt" in doc
    assert "sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.executor" not in doc
    sec5 = doc.split("## 5.")[1]
    assert "켜지는 순간" in sec5 and "paperbot-exec" in sec5 and "paper3.db" in sec5


# ------------------------------------------------------------------ 3. an adopted fill is cut to the risk-checked size
def test_an_adopted_entry_is_cut_to_the_risk_checked_size_not_the_paper_size(tmp_path):
    w = World(tmp_path, max_notional_usd=300.0)
    w.paper(stop=95.0)                                          # paper 5 x $100 = $500 > the $300 cap: 3 sent
    w.fake.fail("POST", "/fapi/v1/order", "503_before")
    w.fake.fail("GET", "/fapi/v1/order", "503_before", times=20)
    w.loop()
    assert w.ex.trade["status"] == "entering" and w.ex.trade["qty"] == 3.0 and w.ex.trade["planned_qty"] == 5.0
    w.fake.pos[BTC], w.fake.entry[BTC] = 5.0, 100.0            # the paper's size filled (an earlier send, late)
    w.fake.failures.clear()
    w.loop()
    assert w.fake.pos[BTC] == 3.0 and w.stops() == [(95.0, 3.0)] and w.events("oversize")
    w.store.close()


# ------------------------------------------------------------------ 4. the close goes first, the reference after
def test_a_failing_price_read_never_holds_back_a_kill_switch_close(w, tmp_path):
    w.paper(stop=95.0)
    w.loop()
    w.fake.fail("GET", "/fapi/v1/ticker/price", "503_before", times=10_000)
    (tmp_path / "STOP").write_text("")
    loops(w, 1)
    assert w.fake.pos[BTC] == 0 and w.ex.risk.halted and w.ex.trade is None
    assert w.store.conn.execute("SELECT json_extract(data, '$.exit_ref') FROM trades").fetchone()[0] == 100.0


def test_a_failing_price_read_never_holds_back_a_paper_exit(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.fail("GET", "/fapi/v1/ticker/price", "503_before", times=10_000)
    w.src.intent = None
    loops(w, 1)
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and "paper 청산" in w.trades()[0][2]


def test_nothing_is_read_between_the_close_decision_and_the_close(w, tmp_path):
    w.paper(stop=95.0)
    w.loop()
    n = len(w.fake.calls)
    (tmp_path / "STOP").write_text("")
    w.loop()
    close = next(i for i, c in enumerate(w.fake.calls) if i >= n and c[:2] == ("POST", "/fapi/v1/order"))
    assert w.fake.calls[close - 1][:2] == ("GET", "/fapi/v2/positionRisk")
    assert not [c for c in w.fake.calls[n:close] if c[1] == "/fapi/v1/ticker/price"]


# ------------------------------------------------------------------ 5. a new halt is saved at once
def test_a_new_halt_is_saved_before_the_rest_of_the_loop_can_fail(w, tmp_path):
    w.loop()
    (tmp_path / "STOP").write_text("")
    w.fake.fail("GET", "/fapi/v2/account", "503_before", times=10_000)        # the loop dies after the halt
    errors = loops(w, 1)
    assert errors and w.ex.risk.halted
    os.remove(tmp_path / "STOP")
    w.fake.failures.clear()
    w.restart()                                                                 # a crash and a restart
    assert w.ex.risk.halted and "비상 정지 파일" in w.ex.risk.halt_reason
    assert w.store.conn.execute("SELECT COUNT(*) FROM halts WHERE action = 'halt'").fetchone()[0] == 1


# ------------------------------------------------------------------ 6. transfers and the equity they are compared with
def deposit_after_the_account_read(fake, amount):
    orig, state = fake.route, {"armed": True}

    def route(m, path, q):
        out = orig(m, path, q)
        if state["armed"] and (m, path) == ("GET", "/fapi/v2/account"):
            state["armed"] = False
            fake.add_transfer(amount)                          # lands right after the account answer
        return out
    fake.route = route


def test_a_deposit_right_after_the_account_read_is_not_a_daily_loss(tmp_path):
    w = World(tmp_path, daily_max_loss_usd=100.0)
    w.loop()
    w.clock.t += 61_000                                        # the transfer scan is due this loop
    deposit_after_the_account_read(w.fake, 200.0)
    w.loop()
    assert not w.ex.risk.halted
    w.clock.t += 61_000
    w.loop()                                                   # applied by the next scan, in the equity too
    assert not w.ex.risk.halted and w.events("transfer")
    w.store.close()


def test_the_equity_is_read_again_after_the_confirming_transfer_read(tmp_path):
    """A withdrawal between the transfer scan and the account read looks like a $150 loss; the confirming read
    applies it, and also a deposit that landed after the account read: the equity must be read again, or that
    deposit reads as a loss."""
    w = World(tmp_path, daily_max_loss_usd=100.0)
    w.loop()
    w.clock.t += 61_000
    orig, state = w.fake.route, {"scan": True}

    def route(m, path, q):
        out = orig(m, path, q)
        if state["scan"] and (m, path) == ("GET", "/fapi/v1/income"):
            state["scan"] = False
            w.fake.add_transfer(-150.0)                        # after the loop's scan, before its account read
        return out
    w.fake.route = route
    deposit_after_the_account_read(w.fake, 150.0)
    w.loop()
    assert not w.ex.risk.halted and len(w.events("transfer")) == 2
    w.store.close()


# ------------------------------------------------------------------ 7. no account states is not "the paper is flat"
def test_a_paper3_db_without_account_states_never_closes_the_live_trade(tmp_path):
    paper = Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path, mode="testnet")
    try:
        ex = lv.executor()
        ex.start()
        paper.enter(T0, qty=5.0, leverage=20)
        lv.clock.t = T0 + 70_000
        ex.loop_once()
        assert lv.fake.pos[BTC] == 5.0
        paper.s.conn.execute("DELETE FROM state WHERE k = 'accounts'")    # a replaced or restored paper3.db
        paper.s.commit()
        ex.run(max_loops=3)
        assert lv.fake.pos[BTC] == 5.0 and lv.fake.covered(BTC) and ex.trade["status"] == "open"
        assert any(lvl == CRITICAL and "paper 계좌를 읽을 수 없습니다" in txt for lvl, txt in lv.note.messages)
    finally:
        lv.close()


# ------------------------------------------------------------------ 8. no alert in front of a stop
def test_the_partial_fill_alert_goes_out_after_the_stop(w):
    w.ex.notifier = tl = Timeline(w.fake)
    w.fake.partial = 0.6
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 3.0 and w.stops() == [(95.0, 3.0)]
    sent = next(i for i, lvl, txt in tl.messages if lvl == WARN and "일부만 체결" in txt)
    assert sent > call_index(w.fake, "POST", "/fapi/v1/algoOrder")


def test_a_missing_stop_is_put_back_before_its_alert_goes_out(w):
    w.paper(stop=95.0)
    w.loop()
    for o in w.fake.live_stops(BTC):
        o["algoStatus"] = "CANCELED"                          # someone cancelled it on the exchange
    w.ex.notifier = tl = Timeline(w.fake)
    n = len(w.fake.calls)
    w.loop()
    sent = next(i for i, lvl, txt in tl.messages if lvl == CRITICAL and "손절이 없습니다" in txt)
    assert sent > call_index(w.fake, "POST", "/fapi/v1/algoOrder", after=n) and w.fake.covered(BTC)


def test_the_halt_alert_goes_out_after_the_closes(w, tmp_path):
    w.paper(stop=95.0)
    w.loop()
    w.ex.notifier = tl = Timeline(w.fake)
    n = len(w.fake.calls)
    (tmp_path / "STOP").write_text("")
    w.loop()
    sent = next(i for i, lvl, txt in tl.messages if lvl == CRITICAL and "거래를 멈춥니다" in txt)
    assert sent > call_index(w.fake, "POST", "/fapi/v1/order", after=n) and w.fake.pos[BTC] == 0


# ------------------------------------------------------------------ 9. the POST answer alone never confirms a stop
def stop_never_rests(fake):
    orig = fake.route

    def route(m, path, q):
        out = orig(m, path, q)
        if (m, path) == ("POST", "/fapi/v1/algoOrder") and out[0] == 200:
            fake.algos.pop(out[1]["algoId"])                  # accepted, then not on the exchange at all
        return out
    fake.route = route


def test_a_stop_the_exchange_never_shows_is_not_confirmed(w):
    stop_never_rests(w.fake)
    w.paper(stop=95.0)
    w.loop()
    assert w.events("protect_failed") and w.fake.pos[BTC] == 0 and w.ex.trade is None
    fake = FakeFutures()
    stop_never_rests(fake)
    c = TestnetClient("k", "s", send=fake)
    c.market(BTC, "BUY", 1.0)
    with pytest.raises(ProtectionError):                       # the drill's path too
        place_stop(c, BTC, "SELL", 95.0, 1.0, waits=())


def test_a_new_stop_shown_only_a_moment_later_is_confirmed(w):
    orig, state = w.fake.route, {"hide": 0}

    def route(m, path, q):
        if (m, path) == ("POST", "/fapi/v1/algoOrder"):
            state["hide"] = 2
        elif state["hide"] and (m, path) == ("GET", "/fapi/v1/algoOrder"):
            state["hide"] -= 1
            return w.fake.err(-2013, "Order does not exist.")
        elif state["hide"] and (m, path) == ("GET", "/fapi/v1/openAlgoOrders"):
            state["hide"] -= 1
            return 200, []
        return orig(m, path, q)
    w.fake.route = route
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 5.0 and w.stops() == [(95.0, 5.0)] and not w.events("protect_failed")
    assert 0.2 in w.sleeps


# ------------------------------------------------------------------ 10. a failed gate at a restart with a trade open
def test_a_restart_with_a_trade_open_and_a_failed_gate_halts_and_closes_instead_of_exiting(tmp_path):
    paper, lv = mainnet_with_open_trade(tmp_path)
    try:
        lv.fake.restrictions["enableWithdrawals"] = True       # the key can withdraw now
        ex = lv.executor()
        ex.start()                                              # no Refused: exit 2 would leave the stop alone
        assert ex.risk.halted and ex.gates_failed and lv.events("mainnet_refused")
        assert any(lvl == CRITICAL and "닫고 멈춥니다" in txt for lvl, txt in lv.note.messages)
        lv.clock.t += 3_000
        ex.loop_once()
        assert lv.fake.pos[BTC] == 0 and ex.trade is None and not lv.fake.live_stops()
        lv.store.commit()
        planned = lv.store.conn.execute("SELECT planned FROM halts WHERE action = 'halt'").fetchall()
        assert planned == [(0,)]                               # counted as unplanned by stage-check
        lv.store.close()
        lv.store = ExecStore(lv.cfg.db)
        with pytest.raises(Refused):                            # nothing open any more: refused as before (exit 2)
            lv.executor().start()
    finally:
        lv.close()


# ------------------------------------------------------------------ 11. flat needs two readings that agree
def test_one_position_read_of_zero_after_a_partial_close_is_not_flat(w):
    w.paper(stop=95.0)
    w.loop()
    partial_reduce_only(w.fake, 0.6)
    orig, state = w.fake.route, {"armed": False}

    def route(m, path, q):
        if (m, path) == ("POST", "/fapi/v1/order") and q.get("reduceOnly") == "true":
            state["armed"] = True
        elif state["armed"] and (m, path) == ("GET", "/fapi/v2/positionRisk") and q.get("symbol") == BTC:
            state["armed"] = False
            return 200, [{"symbol": BTC, "positionAmt": "0", "entryPrice": "0", "markPrice": "100"}]
        return orig(m, path, q)
    w.fake.route = route
    w.src.intent = None
    w.loop()
    assert w.fake.pos[BTC] == 2.0 and w.fake.covered(BTC) and w.ex.trade is not None and w.events("not_flat")
    w.loop()                                                   # the next loop closes the rest
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and not w.fake.live_stops()


def test_a_position_read_lagging_a_full_close_is_read_again_for_longer(w):
    w.paper(stop=95.0)
    w.loop()
    orig, state = w.fake.route, {"stale": 0}

    def route(m, path, q):
        if (m, path) == ("POST", "/fapi/v1/order") and q.get("reduceOnly") == "true":
            state["stale"] = 3                                 # positionRisk shows the old size for ~1 s
        elif state["stale"] and (m, path) == ("GET", "/fapi/v2/positionRisk") and q.get("symbol") == BTC:
            state["stale"] -= 1
            return 200, [{"symbol": BTC, "positionAmt": "5.0", "entryPrice": "100", "markPrice": "100"}]
        return orig(m, path, q)
    w.fake.route = route
    w.src.intent = None
    w.loop()
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and not w.events("not_flat")


def test_flat_without_a_close_order_is_read_twice(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 94.0)                                # the exchange stop closed it
    w.sleeps.clear()
    w.ex._exit(w.ex.trade, "paper 청산")                        # finds it flat: no order, so read once more
    assert X.FLAT_CONFIRM_S in w.sleeps and w.ex.trade is None
    reads = [c for c in w.fake.calls if c[:2] == ("GET", "/fapi/v2/positionRisk") and c[2].get("symbol") == BTC]
    assert len(reads) >= 3


def test_the_risk_halt_kinds_of_a_gate_halt_keep_the_limits():
    st_ = R.RiskState(peak_equity=600.0, consecutive_losses=2)
    R.halt(st_, 1, "실거래 관문 실패", ["gate"])
    R.clear_halt(st_, equity=500.0)
    assert st_.peak_equity == 600.0 and st_.consecutive_losses == 2


def test_one_read_without_the_position_does_not_book_the_trade_or_cancel_its_stop(w):
    """The loop's all-symbols positionRisk misses the open position once (the stop did not fire): read again before
    cancelling the stop and forgetting the trade."""
    w.paper(stop=95.0)
    w.loop()
    orig, state = w.fake.route, {"armed": True}

    def route(m, path, q):
        if state["armed"] and (m, path) == ("GET", "/fapi/v2/positionRisk") and "symbol" not in q:
            state["armed"] = False
            return 200, []
        return orig(m, path, q)
    w.fake.route = route
    w.loop()
    assert w.fake.pos[BTC] == 5.0 and w.fake.covered(BTC) and w.ex.trade["status"] == "open" and not w.trades()[0][2]
    assert w.events("position_read") and not w.events("unknown_position")
    w.fake.set_price(BTC, 94.0)                                # a real stop-out is still booked at once
    w.loop()
    assert w.ex.trade is None and "거래소 손절" in w.trades()[0][2]


# ============================================================ confirm pass 2: the reviewers' findings on the above
def fail_the_next_cut(fake, times=4):
    """The entry fills, then the reduce-only orders after it get 503 before they reach the matching engine."""
    orig = fake.route

    def route(m, path, q):
        out = orig(m, path, q)
        if (m, path) == ("POST", "/fapi/v1/order") and q.get("reduceOnly") is None:
            fake.fail("POST", "/fapi/v1/order", "503_before", times=times)
        return out
    fake.route = route
    return orig


# ------------------------------------------------------------------ 3b. a cut that fails: stop first, cut again later
def test_a_failed_cut_of_an_adopted_entry_keeps_the_whole_position_stopped_and_is_tried_again(tmp_path):
    w = World(tmp_path, max_notional_usd=300.0)
    w.paper(stop=95.0)                                          # paper 5 x $100 > the $300 cap: 3 sent
    w.fake.fail("POST", "/fapi/v1/order", "503_before")
    w.fake.fail("GET", "/fapi/v1/order", "503_before", times=20)
    w.loop()
    assert w.ex.trade["status"] == "entering" and w.ex.trade["qty"] == 3.0 and w.ex.trade["risk_qty"] == 3.0
    w.fake.pos[BTC], w.fake.entry[BTC] = 5.0, 100.0            # the paper's size filled (an earlier send, late)
    w.fake.failures.clear()
    w.fake.fail("POST", "/fapi/v1/order", "503_before", times=4)   # and the cut fails too (the same outage)
    assert loops(w, 1)
    assert w.fake.pos[BTC] == 5.0 and w.fake.covered(BTC) and w.stops() == [(95.0, 5.0)]   # the stop came first
    assert w.ex.trade["status"] == "open" and w.ex.trade["trim_to"] == 3.0
    assert [r[0] for r in w.trades()] == [w.ex.trade["key"]]   # the trade has its row before anything can fail
    w.fake.failures.clear()
    w.restart()                                                # the pending cut is saved: a restart keeps it
    assert not loops(w, 1)
    assert w.fake.pos[BTC] == 3.0 and w.fake.covered(BTC) and "trim_to" not in w.ex.trade
    assert len(w.events("oversize")) == 1 and w.events("oversize_retry")   # alerted and counted once
    w.src.intent = None                                        # the paper exits: booked in the trades table
    assert not loops(w, 1)
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and "paper 청산" in w.trades()[0][2]
    w.store.close()


def test_a_failed_cut_right_after_an_entry_still_puts_the_stop_on_the_whole_position(w):
    orig = fail_the_next_cut(w.fake)
    w.fake.partial = 1.6                                       # the entry fills 8 of the 5 sent
    w.paper(stop=95.0)
    assert loops(w, 1)
    assert w.fake.pos[BTC] == 8.0 and w.fake.covered(BTC) and w.ex.trade["trim_to"] == 5.0
    assert not w.protected_after_first_stop()
    w.fake.route = orig
    w.fake.failures.clear()
    assert not loops(w, 1)
    assert w.fake.pos[BTC] == 5.0 and w.fake.covered(BTC) and "trim_to" not in w.ex.trade
    assert len(w.events("oversize")) == 1


# ------------------------------------------------------------------ 4b. no price read in front of a stop repair
def test_a_failing_price_read_never_holds_back_the_stop_of_a_grown_position(w):
    w.paper(stop=95.0)
    w.loop()
    w.fake.pos[BTC] = 7.0                                      # a late extra fill: 2 without a stop
    w.fake.fail("GET", "/fapi/v1/ticker/price", "503_before", times=10_000)
    assert not loops(w, 1)
    assert w.stops() == [(95.0, 7.0)] and w.fake.covered(BTC)
    w.fake.pos[BTC] = 12.0                                     # past the $1,000 cap: cut at the positionRisk mark
    assert not loops(w, 1)
    assert w.fake.pos[BTC] == 10.0 and w.stops() == [(95.0, 10.0)] and w.events("oversize")


def test_a_cap_check_without_any_price_waits_for_the_next_loop_and_is_not_forgotten(w):
    w.paper(stop=95.0)
    w.loop()
    orig = w.fake.route

    def route(m, path, q):
        status, data = orig(m, path, q)
        if path == "/fapi/v2/positionRisk" and status == 200:
            data = [{k: v for k, v in r.items() if k != "markPrice"} for r in data]
        return status, data
    w.fake.route = route
    w.fake.fail("GET", "/fapi/v1/ticker/price", "503_before", times=10_000)
    w.ex.trade["entry_price"] = None
    w.fake.pos[BTC] = 12.0                                     # $1,200 > the cap, and no price at all
    assert not loops(w, 1)
    assert w.fake.pos[BTC] == 12.0 and w.fake.covered(BTC) and w.events("cap_unchecked")   # the stop first
    assert w.ex.trade["qty"] == 12.0 and w.ex.trade["cap_base"] == 5.0
    w.fake.route = orig
    w.fake.failures.clear()
    assert not loops(w, 1)                                     # checked against the size before it grew
    assert w.fake.pos[BTC] == 10.0 and w.fake.covered(BTC) and "cap_base" not in w.ex.trade


# ------------------------------------------------------------------ 11b. -2021: the old stop stays until flat is sure
def test_a_stop_move_refused_with_2021_never_cancels_the_stop_on_one_read_of_zero(w):
    w.paper(stop=95.0)
    w.loop()
    assert w.stops() == [(95.0, 5.0)]
    w.fake.set_price(BTC, 98.0)
    w.paper(stop=99.0)                                         # the paper's lock: already past the price -> -2021
    orig, state = w.fake.route, {"armed": False}

    def route(m, path, q):
        out = orig(m, path, q)
        if (m, path) == ("POST", "/fapi/v1/algoOrder") and out[0] != 200:
            state["armed"] = True                              # -2021 answered
        elif state["armed"] and (m, path) == ("GET", "/fapi/v2/positionRisk") and q.get("symbol") == BTC:
            state["armed"] = False                             # one read of 0 while the position is open
            return 200, [{"symbol": BTC, "positionAmt": "0", "entryPrice": "0", "markPrice": "98"}]
        return out
    w.fake.route = route
    loops(w, 1)
    assert w.fake.pos[BTC] == 5.0 and w.stops() == [(95.0, 5.0)] and w.fake.covered(BTC)
    assert w.ex.trade["status"] == "open" and w.events("not_flat")
    w.fake.route = orig
    assert not loops(w, 1)                                     # the next loop closes it (still past the price)
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None and not w.fake.live_stops()


# ------------------------------------------------------------------ 10b. an unverifiable gate never sells the position
def waf_403(fake):
    orig = fake.route

    def route(m, path, q):
        if path == "/sapi/v1/account/apiRestrictions":
            return 403, {"code": None, "msg": "WAF limit violated"}
        return orig(m, path, q)
    fake.route = route


def test_a_permission_check_binance_does_not_let_through_never_sells_the_live_position(tmp_path):
    paper, lv = mainnet_with_open_trade(tmp_path)
    try:
        waf_403(lv.fake)
        ex = lv.executor()
        with pytest.raises(X.GateUnverified) as e:              # exit 1: systemd starts it again in 30 s
            ex.start()
        assert not isinstance(e.value, Refused) and not ex.risk.halted and not ex.gates_failed
        assert lv.fake.pos[BTC] == 5.0 and lv.fake.covered(BTC) and not lv.events("halt")
        assert any(lvl == CRITICAL and "닫지 않고" in txt for lvl, txt in lv.note.messages)
        lv.fake.wallet = 1_000.0                                 # a definite problem as well: halted and closed
        ex = lv.executor()
        ex.start()
        assert ex.risk.halted and ex.gates_failed
        lv.clock.t += 3_000
        ex.loop_once()
        assert lv.fake.pos[BTC] == 0 and ex.trade is None
    finally:
        lv.close()


def test_a_permission_check_binance_does_not_let_through_with_nothing_open_is_still_a_refusal(tmp_path):
    Paper(str(tmp_path / "paper3.db"))
    lv = Live(tmp_path)
    try:
        waf_403(lv.fake)
        with pytest.raises(Refused):                            # exit 2: nothing to protect, a person looks
            lv.executor().start()
    finally:
        lv.close()


# ------------------------------------------------------------------ 1b. the service never refuses its own database
def _run_cfg(tmp_path):
    from test_executor import risk_cfg
    return X.ExecConfig(account="V45_AMB@15m", paper_db=str(tmp_path / "paper3.db"), db=str(tmp_path / "exec.db"),
                        qty_scale=1.0, risk=risk_cfg(tmp_path))


def test_the_service_alerts_and_exits_1_when_it_cannot_open_its_database(tmp_path, monkeypatch):
    """``run`` under systemd: a folder it may not write (a restore, a half-done chown) is a fault, not an owner's
    command run as the wrong user. Exit 2 is never restarted; exit 1 is, and an alert goes out first."""
    from paperbot.notify import ListNotifier
    note = ListNotifier()
    cfg = _run_cfg(tmp_path)
    monkeypatch.setattr(X.ExecConfig, "from_file", staticmethod(lambda path: cfg))
    monkeypatch.setattr(X, "_notifier", lambda: note)

    def denied(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(X, "open", denied, raising=False)
    with pytest.raises(PermissionError):                        # not caught by main(): exit 1, restarted
        X.main(["run", "--config", "executor.json"])
    sent = [txt for lvl, txt in note.messages if lvl == CRITICAL]
    assert sent and "실행기 DB를 열 수 없어" in sent[0] and "chown -R paperbot-exec:paperbot" in sent[0]
    assert X.main(["clear-halt", "--config", "executor.json", "--by", "x"]) == 2   # an owner's command: refused
    monkeypatch.undo()


def test_the_service_alerts_when_its_database_opens_read_only(tmp_path, monkeypatch):
    from paperbot.notify import ListNotifier
    note = ListNotifier()
    cfg = _run_cfg(tmp_path)
    monkeypatch.setattr(X.ExecConfig, "from_file", staticmethod(lambda path: cfg))
    monkeypatch.setattr(X, "_notifier", lambda: note)

    def readonly(*a, **k):
        raise sqlite3.OperationalError("attempt to write a readonly database")
    monkeypatch.setattr(X.sqlite3, "connect", readonly)
    with pytest.raises(sqlite3.OperationalError):
        X.main(["run", "--config", "executor.json"])
    monkeypatch.undo()
    assert any(lvl == CRITICAL and "readonly" in txt for lvl, txt in note.messages)


# ------------------------------------------------------------ 1c. the upgrade leaves no WAL file the backup can't read
def test_install_sh_switches_old_wal_executor_databases_back_to_rollback_mode():
    body = _read("deploy/install.sh").split("cat <<'NEXT'")[0]
    chmod = body.index("chmod -R u+rwX,g+rX,g-w,o-rwx /var/lib/paperbot/exec")
    guard = body.index("if ! systemctl is-active --quiet paperbot-executor 2>/dev/null; then", chmod)
    switch = body.index("runuser -u paperbot-exec -- sqlite3 \"$db\" 'PRAGMA journal_mode=DELETE;'", guard)
    assert chmod < guard < switch < body.index('echo "== code version"')
    assert 'for db in /var/lib/paperbot/exec/*.db; do' in body[guard:switch]


@pytest.mark.skipif(not sys.platform.startswith("linux") or os.geteuid() != 0 or not shutil.which("setpriv")
                    or not shutil.which("sqlite3"), reason="needs root, setpriv and sqlite3 to run as two users")
def test_the_nightly_backup_reads_an_executor_database_the_old_code_left_in_wal_format(tmp_path):
    """The old executor (as paperbot, WAL, no switch back) stopped cleanly: WAL format, no -wal/-shm. install.sh gives
    the folder to paperbot-exec (group read only); the backup as paperbot cannot open the file read-only until the
    executor's user switched it back to rollback mode, which install.sh now does."""
    import tempfile
    exec_uid, paperbot, group = 64121, 64122, 64120
    root = tempfile.mkdtemp(dir="/tmp")
    try:
        os.chmod(root, 0o755)
        lib, out = os.path.join(root, "lib"), os.path.join(root, "backups")
        os.makedirs(os.path.join(lib, "exec"))
        os.makedirs(out)
        db = os.path.join(lib, "exec", "executor-testnet.db")
        c = sqlite3.connect(db)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE t (x)")
        c.execute("INSERT INTO t VALUES (1)")
        c.commit()
        c.close()
        assert not os.path.exists(db + "-wal") and open(db, "rb").read(20)[18] == 2
        for p, uid, mode in ((lib, paperbot, 0o750), (out, paperbot, 0o750),
                             (os.path.join(lib, "exec"), exec_uid, 0o750), (db, exec_uid, 0o640)):
            os.chown(p, uid, group)
            os.chmod(p, mode)

        def backup():
            return subprocess.run(["setpriv", f"--reuid={paperbot}", f"--regid={group}", "--clear-groups", "env",
                                   f"PAPERBOT_LIB={lib}", f"PAPERBOT_BACKUPS={out}", "sh",
                                   os.path.join(REPO, "deploy", "paperbot-backup.sh")],
                                  capture_output=True, text=True, cwd="/", timeout=60)
        before = backup()
        assert before.returncode != 0 and "executor-testnet.db failed" in before.stderr   # what the review found
        switch = subprocess.run(["setpriv", f"--reuid={exec_uid}", f"--regid={group}", "--clear-groups", "sqlite3", db,
                                 "PRAGMA journal_mode=DELETE;"], capture_output=True, text=True, cwd="/", timeout=30)
        assert switch.returncode == 0, switch.stderr                # install.sh's line, as the executor's user
        after = backup()
        assert after.returncode == 0, after.stderr
        day = os.listdir(out)
        assert len(day) == 1 and os.listdir(os.path.join(out, day[0])) == ["executor-testnet.db"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ 1d. launchcheck: the process, not only the unit file
def test_launchcheck_sees_an_executor_still_running_as_the_old_user(tmp_path):
    srv = Server(tmp_path)
    states = srv.units
    ex = states[L.EXECUTOR]
    ex.update(ActiveState="active", SubState="running", MainPID="4321")      # User= already the new one
    seen = {}
    ctx = srv.ctx(proc_uids=lambda pid: seen.setdefault(pid, (998, 998, 998, 998)))   # still paperbot (998)
    f = fixes(L.check_executor_user(ctx, states))
    assert seen == {4321: (998, 998, 998, 998)}
    assert len(f) == 1 and "pid 4321" in f[0] and "paperbot 사용자" in f[0]
    assert "sudo systemctl restart paperbot-executor" in f[0]
    ctx = srv.ctx(proc_uids=lambda pid: (997, 997, 997, 997))                # restarted: paperbot-exec
    assert st(L.check_executor_user(ctx, states)) == [L.OK]
    ctx = srv.ctx(proc_uids=lambda pid: None)                                 # unreadable: the unit decides
    assert st(L.check_executor_user(ctx, states)) == [L.OK]
    ex.update(ActiveState="inactive", SubState="dead", MainPID="0")
    ctx = srv.ctx(proc_uids=lambda pid: (998, 998, 998, 998))                # not running: nothing to compare
    assert st(L.check_executor_user(ctx, states)) == [L.OK]
    assert "MainPID" in L.UNIT_PROPS.split(",")


def test_an_adopted_entry_closed_at_once_keeps_its_entry_order_for_the_pnl(tmp_path):
    """The adopted entry's order id is looked up after the stop now (no read in front of it). When the stop cannot be
    confirmed and the trade is closed at once, the id still reaches the stored record, so the later fill read books
    the P&L from the trade's own fills (entry and close), not the wallet estimate."""
    import json
    w = World(tmp_path, max_notional_usd=600.0)
    fake, orig = w.fake, w.fake.route
    state = {"armed": True, "queued": None}

    def route(m, path, q):
        if state["queued"] is not None and not (m == "GET" and path == "/fapi/v1/order"):
            qq, state["queued"] = state["queued"], None
            orig("POST", "/fapi/v1/order", qq)                  # the backend executes the first send late
        if state["armed"] and (m, path) == ("POST", "/fapi/v1/order") and q.get("reduceOnly") is None:
            state["armed"], state["queued"] = False, dict(q)
            return 503, {"code": -1007, "msg": "Send status unknown; execution status unknown."}
        return orig(m, path, q)
    fake.route = route
    w.paper(stop=95.0)
    w.loop()                                                   # the entry's answer is lost; it executes late
    assert w.ex.trade["status"] == "entering"
    stop_never_rests(fake)                                     # adopted next loop, and no stop can be confirmed:
    loops(w, 1)                                                # closed at once
    assert w.events("recover") and w.events("protect_failed") and fake.pos[BTC] == 0 and w.ex.trade is None
    data = json.loads(w.store.conn.execute("SELECT data FROM trades").fetchone()[0])
    entry = fake.orders[fake.by_client[f"pb{data['base']}e"]]
    assert str(entry["orderId"]) in [str(x) for x in data["orders"]]
    loops(w, 1)                                                # the fill read again: now the trade's own fills
    assert w.store.conn.execute("SELECT pnl_source FROM trades").fetchone()[0] == "fills"
    w.store.close()
