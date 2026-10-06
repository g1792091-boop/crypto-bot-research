"""The idea factory's hand-off end to end, on real files, through both services' own code paths (install rehearsal
findings 10/06):

1. wiring: the debate service (debate.py, DEBATE_MODE=factory; only the HTTP transport is fake) creates
   debate_lab_ideas, stores the round's idea and queues it at the slot pick; the agents tick (rooms.tick with the
   lab intake on and --debate-db) pulls it through labintake.pull_debate into lab_intake and runs the real 5-year
   test on the noise lab; the debate service reads the result back from agents3.db (sync_lab) into debate.db and
   into the next packet. No stub table, no hand-made row, no direct enqueue.
2. the permission trap: paperbot-debate.service has ReadOnlyPaths=/var/lib/paperbot and agents3.db / daily3.db are
   WAL files with no -shm between two writer runs. rooms_db.open_ro (plain mode=ro) cannot read such a file there;
   the debate process opens every agents3.db / paper3.db / daily3.db through the immutable fallback
   (debate_packet.open_ro, packets3._ro). Run as an unprivileged uid (root: a forked child as nobody) on read-only
   copies: the factory still sees the ledger (a repeat of a tested idea is 'duplicate', not 'ok'), a whole factory
   round runs, and the lab's result is read back. The debate process never writes agents3.db (results travel
   agents -> agents3.db -> read by the debate service), so nothing has to be routed through the agents tick.
"""
import json
import os
import shutil
import sqlite3
import tempfile
import traceback

import pytest

from paperbot import checkpoint as CP
from paperbot.agents import actions as A
from paperbot.agents import debate as D
from paperbot.agents import debate_factory as DF
from paperbot.agents import debate_packet as P
from paperbot.agents import labintake as LI
from paperbot.agents import labtests as LT
from paperbot.agents import packets3
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.notify import ListNotifier

from test_debate import KEY, Clock, Fake, ok_body
from test_debate_factory_round import factory_answer
from test_labintake import NOISE
from test_newlab import _write
from test_rooms import HOUR, MIN, QUIET, START, QueueRunner, World

IDEA = {"engine": "newlab", "spec": NOISE, "claim": "볼린저 되돌림은 4시간봉에서 동전보다 낫다", "pro": "찬성 근거",
        "con": "반대 근거", "con_check": "⑥", "backs": None, "weak": []}
T0 = QUIET - 7 * HOUR                      # 08:00 KST: inside the 09:00 slot (two picks a day)
VERDICT_DAY = "2026-10-05"                 # a verdict already given (the next one is 30 days on)


@pytest.fixture(scope="module")
def noise(tmp_path_factory):
    return LT.LabData(_write(str(tmp_path_factory.mktemp("wiring_noise")), coins=("BTCUSD", "ETHUSD"), pre=False))


def debate_env(paths, debate_dir):
    return {"ANTHROPIC_API_KEY": KEY, "DEBATE_MODEL": "claude-sonnet-5-5", "DEBATE_EFFORT": "low",
            "DEBATE_MODE": "factory", "DEBATE_LAB_PER_DAY": "2", "DEBATE_MONTHLY_USD_CAP": "70",
            "DEBATE_DAILY_USD_CAP": "3", "DEBATE_PAPER_DB": paths["paper"], "DEBATE_DAILY_DB": paths["daily"],
            "DEBATE_AGENTS_DB": paths["agents"], "DEBATE_CHECKPOINT_DB": os.path.join(debate_dir, "no_cp.db"),
            "DEBATE_DIR": debate_dir}


def debate_service(env, *answers, at):
    cfg = D.config_from_env(env)
    svc = D.Service(cfg, D.DB(cfg.debate_db), ListNotifier(), transport=Fake(*answers), clock=Clock(at),
                    sleep=lambda s: None, out=lambda *_: None)
    svc.start()
    return svc


def hand_off(tmp_path, noise):
    """The whole path once: debate round -> slot pick -> agents tick (pull + 5-year test) -> read-back."""
    world = World(tmp_path)
    ddir = str(tmp_path / "debate")
    svc = debate_service(debate_env(world.paths, ddir), ok_body(factory_answer(0, idea=IDEA)), at=T0)
    assert svc.tick(force=True) == "round"
    iid, status, queue, kind = svc.db.conn.execute(
        "SELECT id, check_status, queue_status, round_kind FROM debate_lab_ideas").fetchone()
    assert (status, queue, kind) == ("ok", "candidate", "factory")
    svc.clock.t = QUIET                                     # 15:00: the 09:00 slot has closed
    assert svc.factory_upkeep(QUIET)["pick"]["queued"] == iid
    svc.db.close()
    # the agents tick, its own code path: rooms.tick -> labintake.tick -> pull_debate (debate.db read-only)
    pol = RM.RoomsPolicy(lab_intake_debate_per_day=2, debate_db=os.path.join(ddir, "debate.db"))
    RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], QueueRunner({}),
            lab=noise, policy=pol, now_ms=QUIET + MIN, clock_ms=lambda: QUIET + MIN,
            debate_db=os.path.join(ddir, "debate.db"))
    return world, ddir, iid


def test_a_debate_idea_reaches_the_lab_and_its_result_comes_back(tmp_path, noise):
    world, ddir, iid = hand_off(tmp_path, noise)
    cards = LI.view(world.agents, "debate")
    assert [(c["source_ref"], c["status"]) for c in cards] == [(f"debate:{iid}", "tested")]
    assert A.newlab_count(world.agents) == 1 and cards[0]["trial_id"]
    # the debate service's next upkeep reads the result back (agents3.db read-only) and the next packet carries it
    svc = debate_service(debate_env(world.paths, ddir), at=QUIET + 30 * MIN)
    assert svc.factory_upkeep(QUIET + 30 * MIN)["synced"] == 1
    lab, trial, side, line = svc.db.conn.execute(
        "SELECT lab_status, lab_trial_id, settled_side, lab_result_ko FROM debate_lab_ideas WHERE id = ?",
        (iid,)).fetchone()
    assert (lab, trial) == ("tested", cards[0]["trial_id"]) and side in ("찬성", "반대") and line
    ro = P.open_ro(world.paths["agents"])
    try:
        rb = DF.readback(svc.db.conn, ro, QUIET + 30 * MIN, 2)
    finally:
        ro.close()
    assert rb["record"]["tested"] == 1 and rb["recent_results"] and rb["lab"]["tests_so_far"] == 1
    svc.db.close()


# ------------------------------------------------------------------ the permission trap
def _as_unprivileged(fn):
    """Run ``fn`` in a forked child as an unprivileged uid (nobody when we are root; else ourselves, which a 0555
    directory already blocks from creating a -shm file). Returns fn's JSON-able result or {'error': ...}."""
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:                                                   # the child
        os.close(r)
        try:
            if os.geteuid() == 0:
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
            out = {"ok": fn()}
        except BaseException as exc:  # noqa: BLE001
            out = {"error": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()[-3000:]}
        os.write(w, json.dumps(out, default=str).encode())
        os._exit(0)
    os.close(w)
    data = b""
    while True:
        chunk = os.read(r, 65536)
        if not chunk:
            break
        data += chunk
    os.close(r)
    os.waitpid(pid, 0)
    return json.loads(data)


def _wal_copy(src: str, dst: str) -> None:
    """A clean WAL-mode copy (no -wal / -shm next to it: what a WAL file looks like between two writer runs)."""
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        s.backup(d)
        d.execute("PRAGMA journal_mode=WAL")
        d.commit()
    finally:
        s.close()
        d.close()
    assert not os.path.exists(dst + "-wal") and not os.path.exists(dst + "-shm")


def test_the_debate_process_reads_wal_files_in_a_read_only_directory(tmp_path, noise):
    world, ddir, iid = hand_off(tmp_path, noise)
    ro_dir, rw_dir = tempfile.mkdtemp(dir="/tmp"), tempfile.mkdtemp(dir="/tmp")
    try:
        ro = {k: os.path.join(ro_dir, f"{k}.db") for k in ("paper", "daily", "agents")}
        for k, dst in ro.items():
            _wal_copy(world.paths[k], dst)
            os.chmod(dst, 0o444)
        # checkpoint.db (a WAL file a timer writes) with the first verdict, as the checkpoint job stores it
        ro["checkpoint"] = os.path.join(ro_dir, "checkpoint.db")
        c = sqlite3.connect(ro["checkpoint"])
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(CP.SCHEMA)
        c.execute("INSERT INTO verdicts (date, ts, snapshot_sha256, data) VALUES (?, ?, ?, ?)",
                  (VERDICT_DAY, CP.day_ms(VERDICT_DAY), "x" * 64, json.dumps({"date": VERDICT_DAY})))
        c.commit()
        c.close()
        os.chmod(ro["checkpoint"], 0o444)
        os.chmod(ro_dir, 0o555)                                    # ReadOnlyPaths=/var/lib/paperbot
        shutil.copy(os.path.join(ddir, "debate.db"), os.path.join(rw_dir, "debate.db"))
        c = sqlite3.connect(os.path.join(rw_dir, "debate.db"))     # the result not read back yet
        c.execute("UPDATE debate_lab_ideas SET lab_status = NULL, lab_trial_id = NULL, settled_side = NULL")
        c.commit()
        c.close()
        os.chmod(os.path.join(rw_dir, "debate.db"), 0o666)
        os.chmod(rw_dir, 0o777)                                    # ReadWritePaths=/var/lib/paperbot/debate
        env = {**debate_env(ro, rw_dir), "DEBATE_CHECKPOINT_DB": ro["checkpoint"]}
        at = QUIET + 2 * HOUR

        def child():
            out = {"rooms_db_open_ro": R.open_ro(ro["agents"]) is not None}
            a = P.open_ro(ro["agents"])
            out["ledger"] = R.trial_count(a, kinds=("newlab",))
            a.close()
            d = packets3._ro(ro["daily"])
            out["daily"] = d is not None and d.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] > 0
            d.close()
            # the packet's checkpoint block: the frozen reader sees no verdict here, the debate's own read does
            out["frozen_reader_ready"] = bool(CP.dashboard_view(ro["checkpoint"]).get("ready"))
            out["checkpoint"] = P._checkpoint(ro["checkpoint"], at, START)
            svc = debate_service(env, ok_body(factory_answer(1, idea=IDEA)), at=at)
            out["synced"] = svc.factory_upkeep(at).get("synced")
            out["result"] = list(svc.db.conn.execute("SELECT lab_status, settled_side FROM debate_lab_ideas "
                                                     "WHERE id = ?", (iid,)).fetchone())
            out["tick"] = svc.tick(force=True)
            out["errors"] = [r[0] for r in svc.db.conn.execute(
                "SELECT error FROM debate_rounds WHERE status = 'error'")]
            out["new_idea"] = list(svc.db.conn.execute(
                "SELECT check_status, check_ko FROM debate_lab_ideas ORDER BY id DESC LIMIT 1").fetchone())
            svc.db.close()
            return out

        got = _as_unprivileged(child)
        assert "error" not in got, got
        got = got["ok"]
        assert got["rooms_db_open_ro"] is False         # the trap is real here: a plain mode=ro open reads nothing
        assert got["ledger"] == 1 and got["daily"]
        assert got["frozen_reader_ready"] is False                 # checkpoint.dashboard_view: the same trap
        assert got["checkpoint"]["verdict_exists"] is True
        assert got["checkpoint"]["next"] > VERDICT_DAY             # the next verdict, not the one already given
        assert got["synced"] == 1 and got["result"][0] == "tested" and got["result"][1] in ("찬성", "반대")
        assert got["tick"] == "round" and got["errors"] == []
        # the same idea again: the ledger is seen, so it is the tested one ('duplicate'), never a new 'ok' candidate
        assert got["new_idea"][0] == "duplicate", got["new_idea"]
        assert not [f for f in os.listdir(ro_dir) if f.endswith(("-wal", "-shm", "-journal"))]   # nothing written
    finally:
        for d in (ro_dir, rw_dir):
            os.chmod(d, 0o755)
            shutil.rmtree(d, ignore_errors=True)


def test_the_debate_service_never_opens_agents3_writable_or_through_a_plain_read_only_open():
    """A grep gate on the debate process's modules: every agents3 / paper3 / daily3 open is debate_packet.open_ro or
    packets3._ro (the immutable fallback); no rooms_db.open_ro / open_agents, no write to agents3.db."""
    import inspect
    from paperbot.agents import debate_grade, debate_questions
    for mod in (D, DF, P, debate_questions, debate_grade):
        src = inspect.getsource(mod)
        for bad in ("R.open_ro(", "R.open_agents(", "open_agents(", "rooms_db.open_ro("):
            assert bad not in src, (mod.__name__, bad)
    src = inspect.getsource(packets3._ro)
    assert "immutable=1" in src
