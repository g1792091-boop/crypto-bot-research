"""Extra paper accounts, runtime side (paperbot/extras.py; docs/extra-accounts.md): the contract with the
agents side, the runner's own validation, activation checks and refusal codes, and the copies' rules."""

import copy
import itertools
import json
import os
import shutil
import sqlite3
import subprocess
import sys

import numpy as np
import pytest

from paperbot import extras as X
from paperbot.accounts import HeldEngine
from paperbot.engine import PaperEngine
from tests.extras_world import DAY, HOUR, MIN, T0, World, add_copy_proposal, names36, newlab_spec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================================ the contract literals
def test_contract_literals():
    assert X.content_key_copy({"template": "stop_atr", "k": 2.5}) == 'copy:{"k":2.5,"template":"stop_atr"}'
    assert X.content_key_copy({"template": "lock_start", "first_lock": 0.2}) == \
        'copy:{"first_lock":0.2,"template":"lock_start"}'
    assert X.content_key_copy({"template": "stop_atr", "k": 3.0}) == 'copy:{"k":3.0,"template":"stop_atr"}'
    assert X.content_key_copy({"template": "skip_tag", "tag": "추세 반대 진입"}) == \
        'copy:{"tag":"추세 반대 진입","template":"skip_tag"}'
    assert X.content_key_newlab("ab" * 32) == "newlab:" + "ab" * 32
    assert X.source(12, 1789990000000, 42, 1789900000000, 'copy:{"k":2.5,"template":"stop_atr"}') == {
        "proposal_id": 12, "proposal_ts": 1789990000000, "trial_id": 42, "trial_ts": 1789900000000,
        "content": 'copy:{"k":2.5,"template":"stop_atr"}'}
    # the runtime's own float is stored: 3 (int) in a proposal is the same rule as 3.0
    assert X.parse_rule({"template": "stop_atr", "k": 3}) == {"template": "stop_atr", "k": 3.0}
    assert X.content_key_copy(X.parse_rule({"template": "stop_atr", "k": 3})) == 'copy:{"k":3.0,"template":"stop_atr"}'
    assert X.copy_account_id("N17_KC_RSI", "15m", 1) == "N17_KC_RSI@15m~c1"
    assert X.newlab_account_id(1, "1h") == "NL1@1h"
    assert X.COPY_ID_RE.match("N17_KC_RSI@15m~c1").groupdict() == {"S": "N17_KC_RSI", "tf": "15m", "n": "1"}
    assert X.NEWLAB_ID_RE.match("NL1@1h").groupdict() == {"n": "1", "tf": "1h"}
    for bad in ("N17_KC_RSI@15m", "N17@1d~c1", "N17@15m~c0", "N17@15m~c10000", "NL0@1h", "NL1@2h"):
        assert not X.COPY_ID_RE.match(bad) and not X.NEWLAB_ID_RE.match(bad)
    for name in names36():
        assert not name.startswith("NL") and "~" not in name and "@" not in name
    assert X.PERMANENT == {"contract_missing", "contract_mismatch", "spec_invalid", "trial_status", "stale_run",
                           "owner_ok_missing", "owner_click_missing", "duplicate", "gate_now_fail", "parent_missing",
                           "parent_bust"}
    assert not (X.PERMANENT & X.TEMPORARY)
    assert set(X.CODES_KO) == X.PERMANENT | X.TEMPORARY


def test_copy_templates_subset_of_labtests():
    from paperbot.agents import labtests as LT
    for t, params in X.COPY_TEMPLATES.items():
        assert t in LT.TEMPLATES and t not in LT.DESCRIPTIVE
        (p, allowed), = params.items()
        assert set(LT.TEMPLATES[t]) == {p}
        assert tuple(map(float, allowed)) == tuple(map(float, LT.TEMPLATES[t][p])) if t != "skip_tag" else \
            tuple(allowed) == tuple(LT.TEMPLATES[t][p])
    assert X.SKIP_TAGS == LT.SKIP_TAGS
    assert set(LT.TEMPLATES) - set(X.COPY_TEMPLATES) == set(LT.DESCRIPTIVE)


def _ctx_battery(n=240, seed=7):
    rng = np.random.default_rng(seed)
    keys = ("regime", "htf_regime", "adx", "di_plus", "di_minus", "ema20_dist_atr", "range_pct")
    regimes = ("trend_up", "trend_down", "chop", "box", "unknown", None)
    out = [None, {}, {"regime": None}]
    for _ in range(n):
        c = {}
        for k in keys:
            if rng.random() < 0.25:
                continue                                    # a missing key
            if k in ("regime", "htf_regime"):
                c[k] = regimes[int(rng.integers(len(regimes)))]
            elif rng.random() < 0.1:
                c[k] = None
            else:
                c[k] = float(rng.choice([rng.uniform(-60, 60), 20.0, 2.0, -2.0, 0.9, 0.1, rng.uniform(0, 1)]))
        out.append(c)
    return out


def test_skip_hit_equals_labtests_has_tag():
    from paperbot.agents import labtests as LT
    n = 0
    for ctx in _ctx_battery():
        for side in (1, -1):
            for tag in X.SKIP_TAGS:
                assert X.skip_hit(tag, side, ctx) == LT.has_tag(tag, side, ctx), (tag, side, ctx)
                n += X.skip_hit(tag, side, ctx)
    assert n > 100                                          # the battery hits every way, not only misses
    from paperbot import cards
    assert set(X.SKIP_TAGS) <= {name for name, _ in cards.TAGS}


def test_newlab_v1_table_equals_newlab_signals():
    from paperbot.agents import newlab as NL
    from paperbot.agents import newlab_signals as NS
    g = X.NEWLAB_V1
    assert g["v"] == NL.GRAMMAR_VERSION
    assert g["tfs"] == NS.TFS and g["directions"] == NS.DIRECTIONS and g["max_filters"] == NS.MAX_FILTERS
    assert {k: (v[0], v[1]) for k, v in NS.FAMILIES.items()} == g["families"]
    assert {k: v[0] for k, v in NS.FILTERS.items()} == g["filters"]


def _spec_battery():
    """Canonical specs (every family and grid value, every filter kind and value) and near misses."""
    from paperbot.agents import newlab as NL
    out = []
    g = X.NEWLAB_V1
    tfs, dirs = g["tfs"], g["directions"]
    for k, (fam, (names, grid)) in enumerate(g["families"].items()):
        for j, combo in enumerate(grid):
            out.append({"v": "newlab-v1", "timeframe": tfs[(k + j) % 5], "entry": {"family": fam,
                        "params": dict(zip(names, combo))}, "filters": [], "direction": dirs[(k + j) % 3]})
    fl = []
    for kind, params in g["filters"].items():
        for combo in itertools.product(*params.values()):
            fl.append({"kind": kind, **dict(zip(params, combo))})
    for i, f in enumerate(fl):
        base = copy.deepcopy(out[i % len(out)])
        base["filters"] = [f]
        out.append(base)
        other = fl[(i * 7 + 3) % len(fl)]
        if other["kind"] != f["kind"]:
            two = copy.deepcopy(base)
            two["filters"] = sorted([f, other], key=lambda x: x["kind"])
            out.append(two)
            rev = copy.deepcopy(base)
            rev["filters"] = sorted([f, other], key=lambda x: x["kind"], reverse=True)    # unsorted: not canonical
            out.append(rev)
    canon = list(out)
    for i, s in enumerate(canon[:60]):                       # near misses
        a = copy.deepcopy(s)
        a["timeframe"] = a["timeframe"].upper()
        b = copy.deepcopy(s)
        b["direction"] = "Both"
        c = copy.deepcopy(s)
        c["extra"] = 1
        d = copy.deepcopy(s)
        d["v"] = "newlab-v2"
        e = copy.deepcopy(s)
        e.pop("filters")
        f = copy.deepcopy(s)
        if f["entry"]["params"]:
            k0 = next(iter(f["entry"]["params"]))
            f["entry"]["params"][k0] = f["entry"]["params"][k0] + 1
        h = copy.deepcopy(s)
        h["entry"]["family"] = "ema_crossover"
        out += [a, b, c, d, e, f, h, {"timeframe": s["timeframe"], "entry": s["entry"], "direction": s["direction"]}]
    out += [None, "x", [], {"v": "newlab-v1"}]
    return out, NL


def test_check_newlab_v1_matches_normalize_spec():
    specs, NL = _spec_battery()
    ok = 0
    for s in specs:
        try:
            canon = NL.normalize_spec(s) if isinstance(s, dict) else None
        except NL.SpecError:
            canon = None
        same = canon is not None and json.dumps(canon, sort_keys=True) == json.dumps(s, sort_keys=True)
        assert (X.check_newlab_v1(s) is None) == same, s
        ok += same
    assert ok > 80


def test_spec_sha_equals_newlab_spec_hash():
    from paperbot.agents import newlab as NL
    from paperbot.agents import rooms_db as R
    for i in range(10):
        s = newlab_spec(i)
        assert X.check_newlab_v1(s) is None
        assert X.spec_sha(s) == NL.spec_hash(s) == R.spec_hash(s)


def test_names_equal_roster():
    from paperbot import sweepsig
    from paperbot.agents.roster3 import STRATEGY_KO
    from paperbot.sigservice import strategy_names
    assert set(strategy_names(sweepsig.lib())) == set(STRATEGY_KO) and len(STRATEGY_KO) == 36


# ============================================================================ activation
@pytest.fixture
def world(tmp_path):
    w = World(tmp_path, hist=True)
    w.process(T0)
    yield w
    w.close()


def _created(w):
    return {a["account_id"]: a for a in w.extras_rows()}


def test_activation_happy_path(world):
    w = world
    rules = [("V45_AMB", "15m", {"template": "stop_atr", "k": 2.5}),
             ("N17_KC_RSI", "5m", {"template": "lock_start", "first_lock": 0.2}),
             ("S2_ST_ROC", "1h", {"template": "skip_tag", "tag": "추세 반대 진입"})]
    pids = [w.copy_proposal(s, tf, r) for s, tf, r in rules]
    npid, ntid = w.newlab_proposal(1)
    B = T0 + 5 * MIN
    w.run(T0 + MIN, B)
    rows = _created(w)
    assert list(rows) == ["V45_AMB@15m~c1", "N17_KC_RSI@5m~c2", "S2_ST_ROC@1h~c3", "NL1@1h"]
    for (s, tf, r), (pid, tid), aid in zip(rules, pids, list(rows)[:3]):
        a = rows[aid]
        assert (a["strategy"], a["timeframe"], a["kind"], a["created_ts"], a["parent"]) == (s, tf, "copy", B, f"{s}@{tf}")
        assert a["settings_version"] == "paper-v3"
        d = json.loads(a["data"])
        t = w.R.get_trial(w.agents, tid)
        p = w.R.get_proposal(w.agents, pid)
        assert d["source"] == X.source(pid, p["ts"], tid, t["ts"], X.content_key_copy(X.parse_rule(r)))
        assert d["rule"] == X.parse_rule(r) and d["kind"] == "copy" and d["v"] == 1 and d["spec"] is None
        assert d["activation"]["boundary"] == B and d["activation"]["decided_by"] == "owner:A"
        assert d["activation"]["owner_click_ts"] == p["ts"]
        assert d["label_ko"].endswith(X.rule_ko(X.parse_rule(r)))
        e = w.book.engines[aid]
        assert isinstance(e, X.GuardedEngine) and e.wallet == w.book.s.initial_equity
        assert e.position is None and not e.pending
        assert w.state()["created"][str(pid)]["account_id"] == aid
    nl = rows["NL1@1h"]
    d = json.loads(nl["data"])
    assert nl["strategy"] == "NL1" and nl["parent"] is None and nl["created_ts"] == B
    assert d["spec"] == newlab_spec(1) and d["spec_hash"] == X.spec_sha(newlab_spec(1))
    assert d["label_ko"] == "새 매매법 NL1 (장부 #4) · 1시간" and d["description_ko"]
    assert set(d["code"]) == {"newlab_signals", "context", "recorder", "lib"} and d["window_5m"] == 1200
    assert d["activation"]["gate"]["n_strict"] == 1
    assert w.book.engines["N17_KC_RSI@5m~c2"].s.ladder_first_lock == 0.2
    assert w.book.engines["N17_KC_RSI@5m"].s is w.book.s and type(w.book.engines["N17_KC_RSI@5m"]) is PaperEngine
    alerts = [r[0] for r in w.store.conn.execute("SELECT text FROM alerts WHERE text LIKE '[extra] 새 paper 계좌 시작%'")]
    assert len(alerts) == 4 and ("INFO", alerts[0]) in w.notifier.messages
    assert w.state()["counts"] == {"copy": 3, "newlab": 1} and w.state()["refused"] == {}
    # the engine joins at the step ts = B
    w.process(B)
    assert w.book.engines["NL1@1h"]._last_mark                         # it stepped
    # nothing is created twice (identity = proposal row)
    w.run(B + MIN, B + 15 * MIN)
    assert len(w.extras_rows()) == 4


def _setup_refusal(w, code):
    """Make the first approved proposal fail exactly with ``code``. Returns (pid, where) where 'refused' means
    state.refused[pid], 'db' the database state of the poll."""
    R = w.R
    if code == "contract_missing":
        pid, tid = w.copy_proposal(click=True)
        # a legacy row: same proposal shape but no account (a new row written the old way)
        t = R.get_trial(w.agents, tid)
        pid = R.add_proposal(w.agents, "strat:V45_AMB", "V45_AMB", tid, {"strategy": "V45_AMB", "test": t["spec"]},
                             {"pass": True}, "awaiting_owner", ts=w.now)
        R.add_approval(w.inbox, pid, "approve", "A", ts=w.now)
        R.set_proposal_status(w.agents, pid, "approved", "owner:A", ts=w.now)
        R.set_proposal_status(w.agents, 1, "rejected", "code", ts=w.now)
        return pid, "refused"
    if code == "contract_mismatch":
        pid, tid = w.copy_proposal(approve=False, click=False)
        t = R.get_trial(w.agents, tid)
        acct = {"v": 1, "kind": "copy", "trial_id": tid, "strategy": "V45_AMB", "timeframe": "15m",
                "parent": "V45_AMB@15m", "rule": {"template": "stop_atr", "k": 1.5}}        # not the trial's rule
        pid = R.add_proposal(w.agents, "strat:V45_AMB", "V45_AMB", tid, {"kind": "copy", "account": acct},
                             {"pass": True}, "awaiting_owner", ts=w.now)
        R.add_approval(w.inbox, pid, "approve", "A", ts=w.now)
        R.set_proposal_status(w.agents, pid, "approved", "owner:A", ts=w.now)
        return pid, "refused"
    if code == "spec_invalid":
        tid = R.add_trial_with_result(w.agents, "strat:V45_AMB", "V45_AMB", "test",
                                      {"template": "stop_atr", "strategy": "V45_AMB", "timeframe": "15m", "k": 2.0},
                                      "passed", {"result": {"ok": True}, "n_trials": 1}, ts=w.now)
        acct = {"v": 1, "kind": "copy", "trial_id": tid, "strategy": "V45_AMB", "timeframe": "15m",
                "parent": "V45_AMB@15m", "rule": {"template": "stop_atr", "k": 2.0}}
        pid = R.add_proposal(w.agents, "strat:V45_AMB", "V45_AMB", tid, {"kind": "copy", "account": acct},
                             {"pass": True}, "awaiting_owner", ts=w.now)
        R.add_approval(w.inbox, pid, "approve", "A", ts=w.now)
        R.set_proposal_status(w.agents, pid, "approved", "owner:A", ts=w.now)
        return pid, "refused"
    if code == "trial_status":
        pid, tid = w.newlab_proposal(0)
        R.add_trial_result(w.agents, tid, "passed", {"gate_input": {}}, ts=w.now)   # latest status not 'proposed'
        return pid, "refused"
    if code == "stale_run":
        return w.copy_proposal(ts=T0 - HOUR)[0], "refused"
    if code == "owner_ok_missing":
        return w.copy_proposal(click=False, decided_by="approver")[0], "refused"
    if code == "owner_click_missing":
        return w.copy_proposal(click=False)[0], "refused"
    if code == "duplicate":
        w.copy_proposal()
        w.boundary(T0 + 5 * MIN)
        w.agents.execute("UPDATE proposals SET status = 'rejected' WHERE id = 1")   # (the tick's own move)
        w.agents.commit()
        return w.copy_proposal()[0], "refused"
    if code == "gate_now_fail":
        import tests.extras_harness as H
        res = copy.deepcopy(H.COPY_RESULT)
        res["periods"]["1"]["p"] = 0.004                # passes at n <= 12 only
        old, H.COPY_RESULT = H.COPY_RESULT, res
        try:
            pid, tid = w.copy_proposal()
        finally:
            H.COPY_RESULT = old
        for _ in range(30):            # many tests in the room since: the stored pass fails at the count now
            R.add_trial(w.agents, "strat:V45_AMB", "V45_AMB", "test", {"x": _}, ts=w.now)
        return pid, "refused"
    if code == "parent_missing":
        return w.copy_proposal("V45_AMB", "30m")[0], "refused"
    if code == "parent_bust":
        w.book.engines["V45_AMB@15m"].bust = True
        return w.copy_proposal()[0], "refused"
    if code == "observing":
        w.ext.cfg.observe_days = 30
        return w.copy_proposal()[0], "db"
    if code == "paused":
        w.ext.cfg.pause_activation = True
        return w.copy_proposal()[0], "db"
    if code == "agents_unreadable":
        pid = w.copy_proposal()[0]
        w.ext.cfg.agents_db = os.path.join(w.tmp, "nope", "agents3.db")
        return pid, "db"
    if code == "inbox_unreadable":
        pid = w.copy_proposal()[0]
        w.ext.cfg.inbox_db = os.path.join(w.tmp, "nope", "inbox.db")
        return pid, "refused"
    if code == "agents_regressed":
        pid = w.copy_proposal(approve=False)[0]
        w.boundary(T0 + 5 * MIN)                       # fingerprint recorded
        w.agents.close()
        os.remove(w.agents_path)
        w.agents = R.open_agents(w.agents_path)        # an older (here: empty) agents3.db with ids re-used
        return w.copy_proposal()[0], "db"
    if code == "stale_ok":
        w.ext.state["since"] = w.now + HOUR            # the feature started after this approval
        return w.copy_proposal()[0], "refused"
    if code == "reject_pending":
        pid = w.copy_proposal()[0]
        R.add_approval(w.inbox, pid, "reject", "B", ts=w.now)
        return pid, "refused"
    if code == "gate_disagree":
        pid = w.copy_proposal()[0]
        from paperbot.agents import actions as A
        real = A.current_gate
        w._restore = (A, "current_gate", real)
        A.current_gate = lambda env, t: ({"pass": True}, 99)
        return pid, "refused"
    if code == "gate_code_unavailable":
        pid = w.copy_proposal()[0]

        def boom():
            raise ImportError("no agents code")
        w.ext.activator._gate_modules = boom
        return pid, "refused"
    if code == "parent_trades":
        w.ext.activator.min_parent_trades = None       # the real rule: 30 closed trades
        return w.copy_proposal()[0], "refused"
    if code == "cap_strategy":
        w.copy_proposal()
        w.boundary(T0 + 5 * MIN)
        return w.copy_proposal("V45_AMB", "5m", {"template": "stop_atr", "k": 3.0})[0], "refused"
    if code == "cap_copy_total":
        X_CAP = X.CAP_COPY_TOTAL
        w._cap = X_CAP
        X.CAP_COPY_TOTAL = 1
        w.copy_proposal()
        w.boundary(T0 + 5 * MIN)
        return w.copy_proposal("N17_KC_RSI", "15m")[0], "refused"
    if code == "cap_newlab_total":
        w._ncap = X.CAP_NEWLAB_TOTAL
        X.CAP_NEWLAB_TOTAL = 1
        w.newlab_proposal(0)
        w.boundary(T0 + 5 * MIN)
        return w.newlab_proposal(2)[0], "refused"
    if code == "newlab_unavailable":
        pid = w.newlab_proposal(6)[0]                   # 4h: a window longer than the history kept
        w.ext._newlab_source().windows["4h"] = 10 ** 9
        return pid, "refused"
    if code == "id_conflict":
        pid = w.copy_proposal()[0]
        # an account row with the next id already exists (written outside the runtime)
        w.store.add_account("V45_AMB@15m~c1", "V45_AMB", "15m", "copy_other", T0, "paper-v3", None, {})
        w.store.commit()
        return pid, "refused"
    raise KeyError(code)


DB_STATES = {"observing": "observing", "paused": "paused", "agents_unreadable": "missing",
             "agents_regressed": "regressed"}


@pytest.mark.parametrize("code", sorted(X.PERMANENT | X.TEMPORARY))
def test_refusal_codes(tmp_path, code):
    w = World(tmp_path, hist=True)
    try:
        w.process(T0)
        before = {a["account_id"] for a in w.extras_rows()}
        pid, where = _setup_refusal(w, code)
        B = T0 + 10 * MIN
        w.boundary(B)
        new = {a["account_id"] for a in w.extras_rows()} - before
        assert not any(w.ext.extras[a].source.get("proposal_id") == pid for a in new if a in w.ext.extras)
        if where == "db":
            assert w.state()["agents_db"] == DB_STATES[code]
            assert not new
        else:
            rf = w.refused(pid)
            assert rf is not None, w.state()["refused"]
            assert rf["code"] == code and rf["permanent"] == (code in X.PERMANENT)
            assert rf["proposal_ts"] == w.R.get_proposal(w.agents, pid)["ts"]
            assert rf["since"] == B
        lvl = [r for r in w.store.conn.execute("SELECT level, text FROM alerts WHERE text LIKE ?", (f"%#{pid}:%{code}%",))]
        if where == "refused":
            assert lvl and lvl[0][0] == ("WARN" if code in X.PERMANENT or code == "id_conflict" else "INFO")
    finally:
        r = getattr(w, "_restore", None)
        if r:
            setattr(r[0], r[1], r[2])
        if hasattr(w, "_cap"):
            X.CAP_COPY_TOTAL = w._cap
        if hasattr(w, "_ncap"):
            X.CAP_NEWLAB_TOTAL = w._ncap
        w.close()


def test_refusal_alert_once_and_entry_removed_when_no_longer_approved(world):
    w = world
    pid = w.copy_proposal(click=False)[0]
    for k in range(3):
        w.boundary(T0 + (5 + 5 * k) * MIN)
    n = w.store.conn.execute("SELECT COUNT(*) FROM alerts WHERE text LIKE ?", (f"%#{pid}:%",)).fetchone()[0]
    assert n == 1 and w.refused(pid)["code"] == "owner_click_missing"
    w.R.set_proposal_status(w.agents, pid, "rejected", "code", ts=w.now)
    w.boundary(T0 + 25 * MIN)
    assert w.refused(pid) is None


def test_reused_proposal_id_other_ts_is_new_identity(world):
    w = world
    pid, tid = w.copy_proposal()
    w.boundary(T0 + 5 * MIN)
    a = _created(w)["V45_AMB@15m~c1"]
    # a restored agents3.db re-used proposal id 1 for another proposal (another ts): a new identity
    w.agents.close()
    os.remove(w.agents_path)
    w.agents = w.R.open_agents(w.agents_path)
    w.now += HOUR
    pid2, _ = w.copy_proposal("N17_KC_RSI", "15m")
    assert pid2 == pid
    w.ext.cfg.agents_ack = X.fingerprint_text({"trial": [1, w.now], "proposal": [1, w.now]})
    w.boundary(T0 + 2 * HOUR)
    rows = _created(w)
    assert "N17_KC_RSI@15m~c2" in rows and json.loads(a["data"])["source"]["proposal_ts"] != \
        json.loads(rows["N17_KC_RSI@15m~c2"]["data"])["source"]["proposal_ts"]


def test_id_conflict_loud(world):
    w = world
    pid, tid = w.copy_proposal()
    w.boundary(T0 + 5 * MIN)
    x = w.ext.extras["V45_AMB@15m~c1"]
    x.data["source"]["trial_ts"] += 1                      # same proposal row, another trial: not "created"
    w.boundary(T0 + 10 * MIN)
    rf = w.refused(pid)
    assert rf["code"] == "id_conflict" and not rf["permanent"]
    assert w.store.conn.execute("SELECT level FROM alerts WHERE text LIKE '%id_conflict%'").fetchone()[0] == "WARN"
    assert len(w.extras_rows()) == 1


def test_duplicate_spec_and_copy(world):
    w = world
    w.copy_proposal()
    w.newlab_proposal(0)
    w.boundary(T0 + 5 * MIN)
    w.R.set_proposal_status(w.agents, 1, "rejected", "code", ts=w.now)
    w.R.set_proposal_status(w.agents, 2, "rejected", "code", ts=w.now)
    p3 = w.copy_proposal()[0]
    # the same spec again in another trial (the lab never tests a hash twice; a restore could)
    p4 = w.newlab_proposal(0)[0]
    w.boundary(T0 + 10 * MIN)
    assert w.refused(p3)["code"] == "duplicate" and w.refused(p4)["code"] == "duplicate"
    assert len(w.extras_rows()) == 2


def test_stale_run_and_observation(tmp_path):
    w = World(tmp_path, observe_days=21, hist=True)
    w.process(T0)
    early = w.copy_proposal(ts=T0 + DAY)[0]                 # written during the observation period
    w.boundary(T0 + 2 * DAY)
    assert w.state()["agents_db"] == "observing" and not w.extras_rows()
    w.now = T0 + 22 * DAY
    late = w.copy_proposal("N17_KC_RSI", "15m")[0]
    w.boundary(T0 + 22 * DAY + 5 * MIN)
    assert w.refused(early)["code"] == "stale_run" and w.refused(early)["permanent"]
    assert [a["account_id"] for a in w.extras_rows()] == ["N17_KC_RSI@15m~c1"]
    assert w.state()["observe_until"] == T0 + 21 * DAY
    w.close()


def test_owner_ok_judged_at_decision_time(tmp_path):
    w = World(tmp_path, owner_ok_days=1, hist=True)
    w.process(T0)
    early = w.copy_proposal(click=False, decided_by="approver", ts=T0 + HOUR)[0]
    w.now = T0 + 2 * DAY
    late = w.copy_proposal("N17_KC_RSI", "15m", click=False, decided_by="approver")[0]
    w.boundary(T0 + 2 * DAY + 5 * MIN)
    assert w.refused(early)["code"] == "owner_ok_missing"             # needed an owner then, even if polled later
    assert [a["account_id"] for a in w.extras_rows()] == ["N17_KC_RSI@15m~c1"]
    # a new-strategy account always needs the owners
    nl = w.newlab_proposal(0, click=False, decided_by="approver")[0]
    w.boundary(T0 + 2 * DAY + 10 * MIN)
    assert w.refused(nl)["code"] == "owner_ok_missing"
    w.close()


def test_owner_click_required(world):
    w = world
    p1 = w.copy_proposal(click=False)[0]
    p2 = w.copy_proposal("N17_KC_RSI", "15m", author="B")[0]
    w.R.add_approval(w.inbox, p1, "approve", "Z", ts=w.now)       # another author's click is not the decision's
    p3 = w.copy_proposal("S2_ST_ROC", "15m", author="")[0]        # decided_by "owner" (no author)
    assert w.R.get_proposal(w.agents, p3)["decided_by"] == "owner"
    w.boundary(T0 + 5 * MIN)
    assert w.refused(p1)["code"] == "owner_click_missing"
    assert {a["account_id"] for a in w.extras_rows()} == {"N17_KC_RSI@15m~c1", "S2_ST_ROC@15m~c2"}


def test_stale_ok_and_fresh_click(tmp_path):
    w = World(tmp_path, start_at=T0 + 3 * HOUR, hist=True)
    w.process(T0 + 3 * HOUR)
    pid = w.copy_proposal(ts=T0 + HOUR)[0]                         # approved before the feature started
    w.boundary(T0 + 3 * HOUR + 5 * MIN)
    assert w.refused(pid)["code"] == "stale_ok" and not w.refused(pid)["permanent"]
    w.R.add_approval(w.inbox, pid, "approve", "A", ts=T0 + 3 * HOUR + 6 * MIN)     # one more click
    w.boundary(T0 + 3 * HOUR + 10 * MIN)
    rows = w.extras_rows()
    assert [a["account_id"] for a in rows] == ["V45_AMB@15m~c1"]
    assert json.loads(rows[0]["data"])["activation"]["owner_click_ts"] == T0 + 3 * HOUR + 6 * MIN
    w.close()


def test_reject_sticky(world):
    w = world
    pid = w.copy_proposal()[0]
    w.R.add_approval(w.inbox, pid, "reject", "B", ts=w.now + 1)
    w.R.add_approval(w.inbox, pid, "approve", "A", ts=w.now + 2)       # a later approve does not undo it
    w.boundary(T0 + 5 * MIN)
    assert w.refused(pid)["code"] == "reject_pending" and not w.extras_rows()
    # a reject click older than the proposal row belongs to an earlier proposal with that id
    w2 = w.copy_proposal("N17_KC_RSI", "15m")[0]
    w.inbox.execute("UPDATE approvals SET ts = ? WHERE proposal_id = ? AND decision = 'reject'", (0, pid)) \
        if False else None
    w.R.add_approval(w.inbox, w2, "reject", "B", ts=w.now - 10 * MIN)
    w.boundary(T0 + 10 * MIN)
    assert [a["account_id"] for a in w.extras_rows()] == ["N17_KC_RSI@15m~c1"]


def test_gate_strict_count_and_hwm(tmp_path, monkeypatch):
    w = World(tmp_path, hist=True)
    w.process(T0)
    pid = w.copy_proposal()[0]
    # (a) a strict count query that fails: the whole poll is unreadable (never a count of 0)
    real = X.Activator.Q_ROOM_TESTS
    monkeypatch.setattr(X.Activator, "Q_ROOM_TESTS", "SELECT COUNT(*) FROM no_such_table WHERE room_id = ?")
    w.boundary(T0 + 5 * MIN)
    assert w.state()["agents_db"] == "unreadable" and not w.extras_rows()
    monkeypatch.setattr(X.Activator, "Q_ROOM_TESTS", real)
    # (b) the agents' function reads another n (e.g. its count failed open): disagree
    from paperbot.agents import actions as A
    monkeypatch.setattr(A, "current_gate", lambda env, t: ({"pass": True}, 1 + 41))
    w.boundary(T0 + 10 * MIN)
    assert w.refused(pid)["code"] == "gate_disagree"
    monkeypatch.undo()
    w.close()
    # (c) after an agents3 restore with fewer tests, the high-water mark judges: p 0.004 passes at n <= 12 only
    w = World(tmp_path / "c", hist=True)
    w.process(T0)
    import tests.extras_harness as H
    res = copy.deepcopy(H.COPY_RESULT)
    res["periods"]["1"]["p"] = 0.004
    monkeypatch.setattr(H, "COPY_RESULT", res)
    for k in range(19):
        w.R.add_trial(w.agents, "strat:V45_AMB", "V45_AMB", "test", {"other": k}, ts=w.now)
    w.copy_proposal(approve=False)
    w.boundary(T0 + 5 * MIN)
    assert w.state()["hwm"]["room_tests"]["strat:V45_AMB"] == 20
    w.agents.close()
    os.remove(w.agents_path)
    w.agents = w.R.open_agents(w.agents_path)
    w.now += HOUR
    pid = w.copy_proposal()[0]
    w.ext.cfg.agents_ack = X.fingerprint_text({"trial": [1, w.now], "proposal": [1, w.now]})
    w.boundary(T0 + 2 * HOUR)
    assert w.refused(pid)["code"] == "gate_now_fail"                  # judged with n = 20, not 1
    assert w.state()["hwm"]["room_tests"]["strat:V45_AMB"] == 20         # marks never go down
    w.close()


def test_fingerprint_regressed_until_ack(world):
    w = world
    w.copy_proposal(approve=False)
    w.boundary(T0 + 5 * MIN)
    fp = w.state()["fingerprint"]
    assert fp["trial"][0] == 1 and fp["proposal"][0] == 1
    w.agents.close()
    os.remove(w.agents_path)
    w.agents = w.R.open_agents(w.agents_path)
    w.now += HOUR
    pid = w.copy_proposal()[0]
    w.boundary(T0 + 2 * HOUR)
    assert w.state()["agents_db"] == "regressed" and not w.extras_rows()
    crit = [m for m in w.notifier.messages if m[0] == "CRITICAL" and "agents_ack" in m[1]]
    assert len(crit) == 1
    w.boundary(T0 + 2 * HOUR + 5 * MIN)
    assert len([m for m in w.notifier.messages if m[0] == "CRITICAL" and "agents_ack" in m[1]]) == 1   # once
    text = X.fingerprint_text({"trial": [1, w.now], "proposal": [1, w.now]})
    assert text in crit[0][1]
    w.ext.cfg.agents_ack = text
    w.boundary(T0 + 2 * HOUR + 10 * MIN)
    assert [a["account_id"] for a in w.extras_rows()] == ["V45_AMB@15m~c1"]
    assert w.state()["fingerprint"]["proposal"] == [pid, w.now]


def test_pause_activation_reread_without_restart(tmp_path):
    cfg = tmp_path / "extras.json"
    cfg.write_text(json.dumps({"pause_activation": True, "observe_days": 0, "owner_ok_days": 1}))
    w = World(tmp_path, config_path=str(cfg), hist=True)
    assert w.ext.cfg.observe_days == 21 and w.ext.cfg.owner_ok_days == 60      # the file cannot lower them
    t = T0 + 22 * DAY
    w.now = t
    w.process(t)
    pid = w.copy_proposal()[0]
    w.boundary(t + 5 * MIN)
    assert w.state()["agents_db"] == "paused" and not w.extras_rows()
    cfg.write_text(json.dumps({"pause_activation": False}))
    os.utime(cfg, (1, 1))                                  # a new mtime
    w.boundary(t + 10 * MIN)
    assert [a["account_id"] for a in w.extras_rows()] == ["V45_AMB@15m~c1"] and w.refused(pid) is None
    cfg.write_text("{not json")
    os.utime(cfg, (2, 2))
    w.boundary(t + 15 * MIN)                               # a broken file keeps the last good config + one WARN
    assert w.ext.cfg.pause_activation is False
    assert w.store.conn.execute("SELECT COUNT(*) FROM alerts WHERE text LIKE '%extras.json를 읽지 못해%'").fetchone()[0] == 1
    w.close()


def test_half_configured_turns_activation_off(tmp_path):
    cfg = tmp_path / "extras.json"
    cfg.write_text(json.dumps({"agents_db": str(tmp_path / "agents3.db")}))
    w = World(tmp_path, config_path=str(cfg), hist=True)
    assert not w.ext.cfg.activation
    assert any("하나만" in m for (m,) in w.store.conn.execute("SELECT text FROM alerts"))
    w.close()


def test_parent_trades_from_paper3_after_restart(tmp_path):
    w = World(tmp_path, hist=True, min_parent_trades=None)
    w.process(T0)
    for k in range(80):
        w.store.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, "
                             "pnl, roe, equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             ("V45_AMB@15m", "BTCUSDT", k, k + 1, "SL", 20, -1.0, -0.1, 5000.0, "{}"))
    w.store.commit()
    w.close()
    w = World(tmp_path, hist=True, min_parent_trades=None)            # a restart: engine trade lists are empty
    assert len(w.book.engines["V45_AMB@15m"].trades) == 0
    w.process(T0)
    w.copy_proposal()
    w.boundary(T0 + 5 * MIN)
    assert [a["account_id"] for a in w.extras_rows()] == ["V45_AMB@15m~c1"]
    w.close()


def test_activation_only_on_live_boundaries(tmp_path):
    w = World(tmp_path, hist=True, skip_before=T0 + HOUR)
    w.process(T0)
    w.copy_proposal()
    w.boundary(T0 + 5 * MIN)                               # before the restart's catch-up end: not live
    assert not w.extras_rows()
    w.runner.skip_before = None
    w.boundary(T0 + 10 * MIN, age_ms=121_000)              # more than 120 s old at hook entry: not live
    assert not w.extras_rows()
    w.boundary(T0 + 15 * MIN, age_ms=119_000)
    assert [a["account_id"] for a in w.extras_rows()] == ["V45_AMB@15m~c1"]
    w.close()


def test_no_phase2_after_195_timeout(world):
    w = world
    w.copy_proposal()
    B = T0 + 5 * MIN
    w.service.timeout_at.add((B, "5m"))
    w.run(T0 + MIN, B)
    assert w.runner.signal_timeouts == 1 and not w.extras_rows()
    w.run(B, B + 5 * MIN)
    assert [a["account_id"] for a in w.extras_rows()] == ["V45_AMB@15m~c1"]


# ============================================================================ copies
def _make_copy(w, strategy="V45_AMB", tf="15m", rule=None):
    w.copy_proposal(strategy, tf, rule)
    B = T0 + 15 * MIN
    w.run(T0 + MIN, B)
    aid = f"{strategy}@{tf}~c1"
    assert aid in w.book.engines
    return aid, B


CTX = {"regime": "trend_down", "htf_regime": "chop", "adx": 25.0, "di_plus": 20.0, "di_minus": 25.0}


def test_copy_stop_atr_signal_and_parent_untouched(world):
    w = world
    aid, B = _make_copy(w)
    B2 = B + 15 * MIN
    w.service.fire[(B2, "15m")] = [("V45_AMB@15m", 1, "BTCUSDT", dict(CTX))]
    w.run(B, B2)
    parent = w.book.engines["V45_AMB@15m"].pending[0]
    snap = copy.deepcopy(parent)
    c = w.book.engines[aid].pending[0]
    assert c.meta["stop_dist"] == pytest.approx(2.5 * 0.2) and parent.meta["stop_dist"] == pytest.approx(0.4)
    assert c.meta["account"] == aid and parent.meta["account"] == "V45_AMB@15m"
    assert c.meta["ctx"] == parent.meta["ctx"] and c.meta["ctx"] is not parent.meta["ctx"]
    assert c.meta is not parent.meta
    w.run(B2, B2 + 3 * MIN)                                   # entry
    pc, pp = w.book.engines[aid].position, w.book.engines["V45_AMB@15m"].position
    assert pc is not None and pp is not None
    ref = parent.meta["ref_price"]
    assert pc.stop_initial == pytest.approx(ref - 1 * 2.5 * 0.2) and pp.stop_initial == pytest.approx(ref - 2 * 0.2)
    w.run(B2 + 3 * MIN, B2 + 6 * MIN, px=95.0)                # both stopped out
    assert w.book.engines[aid].trades and w.book.engines["V45_AMB@15m"].trades
    assert snap == parent and snap.meta == parent.meta        # the parent's signal never changed
    assert pp.signal.meta == snap.meta


def test_copy_lock_start_settings_and_lock_levels(world):
    w = world
    aid, B = _make_copy(w, "N17_KC_RSI", "5m", {"template": "lock_start", "first_lock": 0.2})
    e, par = w.book.engines[aid], w.book.engines["N17_KC_RSI@5m"]
    assert e.s.ladder_first_lock == 0.2 and e.s.ladder_step == par.s.ladder_step == 0.05
    assert e.s.ladder_trigger_gap == par.s.ladder_trigger_gap and par.s is w.book.s
    assert e.s.initial_equity == w.book.s.initial_equity
    B2 = B + 5 * MIN
    w.service.fire[(B2, "5m")] = [("N17_KC_RSI@5m", 1, "ETHUSDT", {})]
    w.run(B, B2 + MIN)
    lev = par.position.leverage
    # a move that arms the parent's first lock (net ROE >= 0.12) but not the copy's (>= 0.22)
    move = (0.17 / lev) + 0.0015
    w.run(B2 + MIN, B2 + 3 * MIN, px=100.0 * (1 + move), hi=0.0, lo=0.0)
    assert par.position.lock_roe == pytest.approx(0.10) and e.position.lock_roe is None


def test_copy_skip_tag_filtered_outcome(world):
    w = world
    aid, B = _make_copy(w, "S2_ST_ROC", "15m", {"template": "skip_tag", "tag": "추세 반대 진입"})
    B2 = B + 15 * MIN
    w.service.fire[(B2, "15m")] = [("S2_ST_ROC@15m", 1, "BTCUSDT", dict(CTX)),                # long in a downtrend
                                   ("S2_ST_ROC@15m", -1, "ETHUSDT", dict(CTX))]               # short: no tag
    w.run(B, B2)
    rows = w.store.conn.execute("SELECT status, reason, step_ts, symbol, data FROM outcomes WHERE account_id = ?",
                                (aid,)).fetchall()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [("FILTERED", "copy rule: skip_tag", B2, "BTCUSDT")]
    d = json.loads(rows[0][4])
    assert d["detail"] == {"tag": "추세 반대 진입"} and d["signal"]["meta"]["account"] == aid
    assert [s.symbol for s in w.book.engines[aid].pending] == ["ETHUSDT"]
    assert len(w.book.engines["S2_ST_ROC@15m"].pending) == 2
    # a missing chart context means no tag: the copy takes the trade (Q-6)
    B3 = B2 + 15 * MIN
    w.service.fire[(B3, "15m")] = [("S2_ST_ROC@15m", 1, "SOLUSDT", {})]
    w.run(B2, B3)
    assert "SOLUSDT" in [s.symbol for s in w.book.engines[aid].pending] or w.book.engines[aid].position is not None


def test_copy_gets_only_signals_after_creation(world):
    w = world
    w.copy_proposal()
    B = T0 + 15 * MIN
    w.service.fire[(B, "15m")] = [("V45_AMB@15m", 1, "BTCUSDT", {})]       # the parent signals at the creation boundary
    w.run(T0 + MIN, B)
    aid = "V45_AMB@15m~c1"
    assert w.book.engines[aid].pending == [] and len(w.book.engines["V45_AMB@15m"].pending) == 1
    B2 = B + 15 * MIN
    w.service.fire[(B2, "15m")] = [("V45_AMB@15m", -1, "ETHUSDT", {})]
    w.run(B, B2)
    assert [s.symbol for s in w.book.engines[aid].pending] == ["ETHUSDT"]


def test_copy_rule_never_changes_the_parent_or_others(world):
    w = world
    aid, B = _make_copy(w)
    B2 = B + 15 * MIN
    w.service.fire[(B2, "15m")] = [("N17_KC_RSI@15m", 1, "BTCUSDT", {})]    # another strategy: not routed
    w.run(B, B2)
    assert w.book.engines[aid].pending == []


# ============================================================================ phases, rollback, isolation of load
def test_phase_rollback_undo(world, monkeypatch):
    w = world
    w.copy_proposal()
    w.newlab_proposal(0)
    real = X.Extras._event

    def boom(self, aid, event, *a, **k):
        real(self, aid, event, *a, **k)
        if event == "created" and aid.startswith("NL"):
            raise RuntimeError("injected after add_extra")
    monkeypatch.setattr(X.Extras, "_event", boom)
    before = copy.deepcopy(w.ext.state["created"])
    w.boundary(T0 + 5 * MIN)
    assert w.extras_rows() == [] and not any("~c" in a or a.startswith("NL") for a in w.book.engines)
    assert w.ext.extras == {} and w.ext.state["created"] == before
    assert w.ext.newlab is None or not w.ext.newlab.specs
    assert w.ext.state["health"]["errors"] == 1 and "injected" in w.ext.state["health"]["last_error"]
    assert w.store.conn.execute("SELECT COUNT(*) FROM alerts WHERE text LIKE '[extra]%실패%'").fetchone()[0] == 1
    assert w.store.conn.execute("SELECT COUNT(*) FROM alerts WHERE text LIKE '%새 paper 계좌 시작%'").fetchone()[0] == 0
    monkeypatch.setattr(X.Extras, "_event", real)
    w.boundary(T0 + 10 * MIN)                                  # retried at the next boundary
    assert [a["account_id"] for a in w.extras_rows()] == ["V45_AMB@15m~c1", "NL1@5m"]


def test_restart_reloads_extras_with_their_rules(tmp_path):
    w = World(tmp_path, hist=True)
    w.process(T0)
    w.copy_proposal("N17_KC_RSI", "5m", {"template": "lock_start", "first_lock": 0.3})
    w.newlab_proposal(0)
    w.run(T0 + MIN, T0 + 10 * MIN)
    st = {aid: json.dumps(w.ext.book.engines[aid].__dict__.get("wallet")) for aid in ("NL1@5m", "N17_KC_RSI@5m~c1")}
    w.close()
    w = World(tmp_path, hist=True)
    e = w.book.engines["N17_KC_RSI@5m~c1"]
    assert isinstance(e, X.GuardedEngine) and e.s.ladder_first_lock == 0.3
    assert isinstance(w.book.engines["NL1@5m"], X.GuardedEngine)
    assert "NL1@5m" in w.ext.newlab.specs and w.ext.extras["NL1@5m"].status == "active"
    assert json.dumps(w.book.engines["NL1@5m"].wallet) == st["NL1@5m"]
    w.close()


def test_load_failures_hold_or_suspend(tmp_path):
    w = World(tmp_path, hist=True)
    w.process(T0)
    w.copy_proposal()
    w.newlab_proposal(0)
    w.run(T0 + MIN, T0 + 10 * MIN)
    w.close()
    c = sqlite3.connect(os.path.join(str(tmp_path), "paper3.db"))
    d = json.loads(c.execute("SELECT data FROM accounts WHERE account_id = 'V45_AMB@15m~c1'").fetchone()[0])
    d["rule"] = {"template": "stop_atr", "k": 9.9}
    c.execute("UPDATE accounts SET data = ? WHERE account_id = 'V45_AMB@15m~c1'", (json.dumps(d),))
    d = json.loads(c.execute("SELECT data FROM accounts WHERE account_id = 'NL1@5m'").fetchone()[0])
    d["spec"]["direction"] = "Both"
    c.execute("UPDATE accounts SET data = ? WHERE account_id = 'NL1@5m'", (json.dumps(d),))
    c.commit()
    c.close()
    w = World(tmp_path, hist=True)
    assert type(w.book.engines["V45_AMB@15m~c1"]) is HeldEngine
    assert isinstance(w.book.engines["NL1@5m"], X.GuardedEngine) and "NL1@5m" not in w.ext.newlab.specs \
        if w.ext.newlab else True
    acc = w.state()["accounts"]
    assert acc["V45_AMB@15m~c1"]["status"] == "held" and acc["V45_AMB@15m~c1"]["code"] == "rule_invalid"
    assert acc["NL1@5m"] == {"status": "suspended", "code": "spec_invalid", "since": acc["NL1@5m"]["since"]}
    ev = [(e["account_id"], e["event"]) for e in w.state()["events"] if e["event"] != "created"]
    assert ev == [("V45_AMB@15m~c1", "held"), ("NL1@5m", "suspended")]
    assert sum(1 for m in w.notifier.messages if m[0] == "CRITICAL") == 2
    w.close()


def test_no_agents_import_at_load(tmp_path):
    w = World(tmp_path, hist=True)
    w.process(T0)
    w.copy_proposal()
    w.newlab_proposal(0)
    w.run(T0 + MIN, T0 + 10 * MIN)
    w.close()
    code = f"""
import sys, json
from paperbot.store3 import Store3
from paperbot.config import v3_settings
from paperbot.notify import ListNotifier
from paperbot.extras import Extras, Config
st = Store3({os.path.join(str(tmp_path), 'paper3.db')!r})
ext = Extras.start(st, ListNotifier(), 'x.db', v3_settings(), config=Config(), now_ms=lambda: 1)
hows = [ext.make_of(r) for r in st.accounts()]
assert sum(h is not None for h in hows) == 2, hows
bad = sorted(m for m in sys.modules if m.startswith('paperbot.agents') or m == 'paperbot.newlab_live')
print(json.dumps(bad))
"""
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == []


def test_status_command(world):
    w = world
    w.copy_proposal()
    w.boundary(T0 + 5 * MIN)
    w.store.commit()
    text = X.status_text(w.db)
    assert "V45_AMB@15m~c1" in text and "agents3 ok" in text
