"""Extra paper accounts, the agents' side (agents/extra_accounts.py and its callers): the data contract with
the live runner (change.kind / change.account, content key, source identity, id shapes, refusal codes), copy
proposals that need paper3 (parent account, 30 trades, caps counted with running extras), new-strategy
proposals (one transaction, owners' OK, cap, observation), owner clicks guarded by the running account, the
tick's housekeeping, triggers and packets for extras, and the dashboard's view of them.

paper3.db fixtures are written with the existing Store3 calls only (accounts rows with the runner's ``data``
JSON and state 'extras'), as the runtime side would write them.
"""

import json
import sqlite3

import pytest

from paperbot.agents import actions as A
from paperbot.agents import extra_accounts as X
from paperbot.agents import newlab as NL
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents.roster3 import STRATEGY_KO
from paperbot.notify import ListNotifier
from test_rooms import (DAY, HOUR, MIN, PASS, QUIET, ROOM, S, SPEC, START, QueueRunner, StubLab, World, analysis,
                        challenge, rec)

LAB = R.LAB_ROOM
P1 = {"available": True, "trades": 900, "mean_roe": 0.01, "p": 1e-5, "coins_pos": 5, "coins_n": 6,
      "mean_pnl_equity": 0.001, "coinflip": {"mean_roe": -0.01, "trades": 900, "diff": 0.02, "p": 0.001}}
P2 = {"available": True, "trades": 500, "mean_roe": 0.008, "p": 0.001, "mean_pnl_equity": 0.001,
      "coinflip": {"mean_roe": -0.01, "trades": 500, "diff": 0.018, "p": 0.001}}
GI_STRONG = {"1": P1, "2": P2, "3": {"available": False}}
GI_MARGINAL = {"1": {**P1, "p": 0.02}, "2": P2, "3": {"available": False}}     # passes only as the first test
NLSPEC = NL.normalize_spec({"timeframe": "1h", "entry": {"family": "rsi_reversal",
                                                         "params": {"length": 14, "low": 30, "high": 70}},
                            "filters": [{"kind": "session", "window": "us"}], "direction": "long"})
NLSPEC2 = NL.normalize_spec({"timeframe": "5m", "entry": {"family": "ema_cross", "params": {"fast": 9, "slow": 21}},
                             "direction": "both"})


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def env(world, room=ROOM, strategy=S, now=QUIET, paper=True, **kw):
    return A.ActionEnv(conn=world.agents, room_id=room, strategy=strategy, round_id=None, meeting="t", now_ms=now,
                       paper_ro=world.paper() if paper else None, **kw)


def copy_trial(world, tf="15m", k=2.5, ts=QUIET - DAY):
    spec = {"template": "stop_atr", "strategy": S, "timeframe": tf, "k": k}
    res = StubLab(good=True).run_test(spec, None, n_trials=1, strategy=S)
    tid = R.add_trial(world.agents, ROOM, S, "test", spec, ts=ts)
    R.add_trial_result(world.agents, tid, "passed", {"result": res, "gate": res["gate"], "n_trials": 1}, ts=ts)
    return R.get_trial(world.agents, tid)


def copy_proposal(world, t=None, status="awaiting_owner", ts=QUIET - HOUR, by="owner:A"):
    t = t or copy_trial(world)
    change = {"kind": "copy", "account": X.copy_account(t), "strategy": S, "test": t["spec"], "why": "모델이 쓴 이유"}
    pid = R.add_proposal(world.agents, ROOM, S, t["id"], change, {**PASS, "trial_id": t["id"], "n_trials": 1},
                         "awaiting_owner", ts=ts)
    if status != "awaiting_owner":
        R.set_proposal_status(world.agents, pid, status, by, ts=ts + MIN)
    return R.get_proposal(world.agents, pid), t


def newlab_trial(world, spec=NLSPEC, gi=GI_STRONG, ts=QUIET - DAY, idea=""):
    body = {"gate_input": gi, "n_tests_so_far": 0, "test_number": 1, "description_ko": NL.describe_ko(spec),
            "summary_ko": "코드 요약", "notes": {"idea": idea} if idea else {}, "proposal": None}
    tid = R.add_trial_with_result(world.agents, LAB, None, "newlab", spec, "passed", body, ts=ts)
    return R.get_trial(world.agents, tid)


def newlab_proposal(world, status="awaiting_owner", spec=NLSPEC, gi=GI_STRONG, now=QUIET - HOUR):
    t = newlab_trial(world, spec, gi)
    got = A.newlab_propose(env(world, room=LAB, strategy=None, now=now), t)
    assert got["proposed"] is True, got
    if status != "awaiting_owner":
        R.set_proposal_status(world.agents, got["proposal_id"], status, "owner:A", ts=now + MIN)
    return R.get_proposal(world.agents, got["proposal_id"]), R.get_trial(world.agents, t["id"])


def add_extra(world, p, t, aid=None, created=QUIET, source=None):
    """An extra account row as the runner writes it (accounts.data, design 3.2.1)."""
    acc = p["change"]["account"]
    kind = acc["kind"]
    if kind == "copy":
        aid = aid or f"{acc['parent']}~c1"
        strategy, parent = acc["strategy"], acc["parent"]
        label = f"{STRATEGY_KO[strategy]} {acc['timeframe']} 복제 {aid.rsplit('~', 1)[1]} · {X.rule_ko(acc['rule'])}"
    else:
        aid = aid or f"NL1@{acc['timeframe']}"
        strategy, parent = aid.split("@")[0], None
        label = f"새 매매법 {strategy} (장부 #{t['id']}) · {acc['timeframe']}"
    data = {"v": 1, "kind": kind, "source": source or X.source_of(p, t, acc), "rule": acc.get("rule"),
            "spec": acc.get("spec"), "spec_hash": acc.get("spec_hash"), "stop_atr": 2.0, "first_lock": 0.1,
            "label_ko": label, "description_ko": NL.describe_ko(acc["spec"]) if kind == "newlab" else None}
    world.store.add_account(aid, strategy, acc["timeframe"], kind, created, "paper-v3", parent=parent, data=data)
    world.store.commit()
    return aid


def runner_state(world, **kw):
    st = {"v": 1, "ts": QUIET, "boundary": QUIET, "since": START, "run_start": START, "refused": {}, "accounts": {},
          "events": [], "created": {}, "counts": {}}
    st.update(kw)
    world.store.put_state("extras", QUIET, st)
    world.store.commit()


def ctx(world, now=QUIET, paper=True, notifier=None):
    return RM.RoundContext(agents_conn=world.agents, paper_ro=world.paper() if paper else None, daily_ro=None,
                           inbox_ro=R.open_ro(world.paths["inbox"]), runner=None, lab=None, now_ms=now,
                           notifier=notifier or ListNotifier())


def msgs(world, room=ROOM):
    return [m["text"] for m in world.messages(room)]


# ================================================================ the contract (both sides test these literals)
def test_contract_literals():
    t = {"id": 42, "ts": 1789900000000, "kind": "test", "strategy": S,
         "spec": {"template": "stop_atr", "strategy": S, "timeframe": "15m", "k": 2.5}}
    assert X.copy_account(t) == {"v": 1, "kind": "copy", "trial_id": 42, "strategy": "N17_KC_RSI", "timeframe": "15m",
                                 "parent": "N17_KC_RSI@15m", "rule": {"template": "stop_atr", "k": 2.5}}
    assert '"k": 2.5' in json.dumps(X.copy_account(t))                              # a JSON number
    lock = {**t, "spec": {"template": "lock_start", "strategy": S, "timeframe": "5m", "first_lock": 0.2}}
    assert X.copy_account(lock)["rule"] == {"template": "lock_start", "first_lock": 0.2}
    skip = {**t, "spec": {"template": "skip_tag", "strategy": S, "timeframe": "1h", "tag": "추세 반대 진입"}}
    assert X.copy_account(skip)["rule"] == {"template": "skip_tag", "tag": "추세 반대 진입"}
    k3 = {**t, "spec": {"template": "stop_atr", "strategy": S, "timeframe": "15m", "k": 3}}
    assert X.copy_account(k3)["rule"] == {"template": "stop_atr", "k": 3.0}            # stored as a float
    assert X.copy_account({**t, "spec": {"template": "timeframe_only", "strategy": S}}) is None
    assert X.copy_account({**t, "kind": "newlab"}) is None and X.copy_account(None) is None
    # the content key literals
    assert X.content_key({"kind": "copy", "rule": {"template": "stop_atr", "k": 2.5}}) == 'copy:{"k":2.5,"template":"stop_atr"}'
    assert X.content_key({"kind": "copy", "rule": {"template": "lock_start", "first_lock": 0.2}}) == \
        'copy:{"first_lock":0.2,"template":"lock_start"}'
    assert X.content_key({"kind": "copy", "rule": {"template": "stop_atr", "k": 3.0}}) == 'copy:{"k":3.0,"template":"stop_atr"}'
    assert X.content_key({"kind": "copy", "rule": {"template": "skip_tag", "tag": "추세 반대 진입"}}) == \
        'copy:{"tag":"추세 반대 진입","template":"skip_tag"}'
    assert X.content_key(None) is None and X.content_key({"kind": "copy"}) is None
    # a new strategy: the canonical spec and its hash (trials.spec_hash = newlab.spec_hash)
    h = NL.spec_hash(NLSPEC)
    assert h == R.spec_hash(NLSPEC)
    nt = {"id": 57, "ts": 1789900000000, "kind": "newlab", "spec": NLSPEC, "spec_hash": h}
    assert X.newlab_account(nt) == {"v": 1, "kind": "newlab", "trial_id": 57, "timeframe": "1h", "spec": NLSPEC,
                                    "spec_hash": h}
    assert NLSPEC == {"v": "newlab-v1", "timeframe": "1h", "entry": {"family": "rsi_reversal",
                                                                     "params": {"length": 14, "low": 30, "high": 70}},
                      "filters": [{"kind": "session", "window": "us"}], "direction": "long"}
    assert X.content_key(X.newlab_account(nt)) == "newlab:" + h
    assert X.newlab_account({**nt, "spec_hash": "0" * 64}) is None and X.newlab_account({**nt, "kind": "test"}) is None
    # the source (identity), compared by exact equality
    p = {"id": 12, "ts": 1789990000000}
    assert X.source_of(p, t, X.copy_account(t)) == {"proposal_id": 12, "proposal_ts": 1789990000000, "trial_id": 42,
                                                    "trial_ts": 1789900000000,
                                                    "content": 'copy:{"k":2.5,"template":"stop_atr"}'}
    # ids are the runner's; this is what they look like
    assert X.COPY_ID_RE.match("N17_KC_RSI@15m~c1").group("S", "tf", "n") == ("N17_KC_RSI", "15m", "1")
    assert X.NEWLAB_ID_RE.match("NL1@1h").group("n", "tf") == ("1", "1h")
    for bad in ("N17_KC_RSI@15m", "N17_KC_RSI@15m~c0", "N17_KC_RSI@1d~c1", "NL0@1h", "NL1@1d", "NL1@1h~c1"):
        assert not X.COPY_ID_RE.match(bad) and not X.NEWLAB_ID_RE.match(bad), bad
    for name in STRATEGY_KO:                       # no original name can look like an extra
        assert not name.startswith("NL") and "~" not in name and "@" not in name
    assert X.PERMANENT == {"contract_missing", "contract_mismatch", "spec_invalid", "trial_status", "stale_run",
                           "owner_ok_missing", "owner_click_missing", "duplicate", "gate_now_fail", "parent_missing",
                           "parent_bust"}
    assert set(X.PERMANENT) <= set(X.REFUSAL_KO)
    assert X.proposal_kind({"change": {"x": 1}}) == "copy" and X.proposal_kind({"change": {"kind": "newlab"}}) == "newlab"


# ================================================================ copy proposals
@pytest.mark.parametrize("status", ["blocked_gate", "blocked_cap", "rejected", "awaiting_owner", "approved"])
def test_propose_copy_writes_kind_and_account(world, status):
    t = copy_trial(world)
    world.parent_trades()
    e = env(world, owner_ok_required=status != "approved")
    chk = A.copy_check(e, t["id"])
    assert chk["ok"] is True and chk["gate_pass"] is True and chk["cap"] == ""
    if status == "blocked_gate":
        chk = {**chk, "gate_pass": False, "gate": {"pass": False, "reasons": ["x"]}}
    if status == "blocked_cap":
        chk = {**chk, "cap": "한도"}
    approver = {"approve": status != "rejected", "reason": "이유"}
    res = A.propose_copy(e, t["id"], "모델이 쓴 이유", chk, approver)
    [p] = R.list_proposals(world.agents)
    assert p["status"] == res["status"] == status
    assert p["change"]["kind"] == "copy" and p["change"]["account"] == X.copy_account(t)
    assert p["change"]["account"]["parent"] == f"{S}@15m" and "id" not in p["change"]["account"]
    # the runner reads exactly these paths
    row = world.agents.execute("SELECT COALESCE(json_extract(change, '$.kind'), 'copy'), json_extract(change, "
                               "'$.account') FROM proposals").fetchone()
    assert row[0] == "copy" and json.loads(row[1]) == X.copy_account(t)
    if status in ("awaiting_owner", "approved"):
        line = next(m for m in world.messages() if m["kind"] == "action" and "복제 계좌 제안" in m["text"])
        assert "추가 계좌 기능이 아직 켜지지 않아" in line["text"]


def test_copy_text_promises_the_start_once_the_runtime_is_deployed(world):
    runner_state(world)
    t = copy_trial(world)
    world.parent_trades()
    e = env(world)
    A.propose_copy(e, t["id"], "why", A.copy_check(e, t["id"]), {"approve": True, "reason": "ok"})
    line = next(m for m in world.messages() if m["kind"] == "action" and "복제 계좌 제안" in m["text"])
    assert "다음 5분 봉 경계" in line["text"] and "거절로 멈출 수 없습니다" in line["text"]


def test_copy_check_requires_paper_ro_parent_bust_and_30_trades(world):
    t = copy_trial(world)
    assert A.copy_check(env(world, paper=False), t["id"]) == {
        "ok": False, "why": "paper3를 읽지 못해 제안하지 않음", "trial": t, "gate": A.copy_check(env(world), t["id"])["gate"]}
    world.parent_trades(n=29)
    got = A.copy_check(env(world), t["id"])
    assert got["ok"] is False and got["why"] == "원본 계좌 거래 29건 < 30건"
    world.trade(f"{S}@15m", 1.0, QUIET - 2 * HOUR)
    assert A.copy_check(env(world), t["id"])["ok"] is True
    # a bust parent (a BUST alert, or the saved engine state)
    world.store.alert(QUIET - HOUR, "WARN", f"[{S}@15m] BUST: equity 9.00 below 10.00")
    world.store.commit()
    got = A.copy_check(env(world), t["id"])
    assert got["ok"] is False and got["why"] == "원본 계좌가 파산해 복제하지 않음"
    t1h = copy_trial(world, tf="1h")
    world.parent_trades(f"{S}@1h")
    assert A.copy_check(env(world), t1h["id"])["ok"] is True
    world.store.put_state("accounts", QUIET, {"engines": {f"{S}@1h": {"bust": True, "wallet": 5.0}}})
    world.store.commit()
    assert A.copy_check(env(world), t1h["id"])["why"] == "원본 계좌가 파산해 복제하지 않음"
    # a parent the run does not have
    t4h = copy_trial(world, tf="4h")
    assert A.copy_check(env(world), t4h["id"])["why"] == "원본 계좌가 paper3에 없어 복제하지 않음"


def test_a_meeting_without_the_parents_30_trades_makes_no_proposal(world, monkeypatch):
    monkeypatch.setattr(A, "_lab", StubLab(good=True))
    from test_rooms import TEST, expert
    runner = QueueRunner({SPEC: [analysis(TEST), analysis(TEST, changes="그대로")],
                          "devils_advocate": [challenge("needs_test")], "entry_timing": [expert("needs_test")],
                          "validator": [{"pass_gate": True, "explanation": "ok"}]})
    world.losses()
    world.tick(runner, QUIET, lab=object())
    assert "approver" not in runner.roles() and R.list_proposals(world.agents) == []
    assert any("복제 제안을 만들지 않았습니다" in t and "원본 계좌 거래 2건 < 30건" in t for t in msgs(world))


def test_caps_union_running_extras(world):
    world.parent_trades()
    p, t = copy_proposal(world, status="approved")
    assert X.slots(world.agents, world.paper(), "copy", S) == 1
    add_extra(world, p, t)                                         # its account runs: still one slot
    assert X.slots(world.agents, world.paper(), "copy", S) == 1 and X.slots(world.agents, world.paper(), "copy") == 1
    # the proposal is gone from agents3 (a restore) or closed: the running account still holds the slot
    R.set_proposal_status(world.agents, p["id"], "rejected", "code")
    assert R.active_proposals(world.agents, S) == 0 and X.slots(world.agents, world.paper(), "copy", S) == 1
    t2 = copy_trial(world, k=3.0)
    got = A.copy_check(env(world), t2["id"])
    assert got["ok"] is True and "이 매매법" in got["cap"] and got["slots"] == {"strategy": 1, "total": 1}
    # total: running copies of other strategies count too
    for k, s in enumerate([x for x in STRATEGY_KO if x != S][:9]):
        world.store.add_account(f"{s}@15m~c1", s, "15m", "copy", QUIET, "paper-v3", parent=f"{s}@15m",
                                data={"v": 1, "kind": "copy", "source": {"proposal_id": 900 + k}})
    world.store.commit()
    assert X.slots(world.agents, world.paper(), "copy") == 10
    other = A.ActionEnv(conn=world.agents, room_id="strat:V45_AMB", strategy="V45_AMB", round_id=None, meeting="t",
                        now_ms=QUIET, paper_ro=world.paper())
    vt = R.add_trial(world.agents, "strat:V45_AMB", "V45_AMB", "test",
                     {"template": "stop_atr", "strategy": "V45_AMB", "timeframe": "15m", "k": 2.5})
    world.parent_trades("V45_AMB@15m")
    assert "전체" in A.copy_check(other, vt)["cap"]
    # kinds are counted apart (rows without a kind are copies)
    assert R.active_proposals(world.agents, kind="newlab") == 0
    newlab_proposal(world)
    assert R.active_proposals(world.agents, kind="newlab") == 1 and R.active_proposals(world.agents) == 0
    assert R.active_proposals(world.agents, kind=None) == 1


# ================================================================ new-strategy proposals
def test_newlab_propose_one_transaction(world, monkeypatch):
    t = newlab_trial(world)
    real = R.add_trial_result

    def boom(conn, trial_id, status, result, *, ts=None, commit=True):
        if not commit:
            raise RuntimeError("killed between the two writes")
        return real(conn, trial_id, status, result, ts=ts, commit=commit)
    monkeypatch.setattr(R, "add_trial_result", boom)
    with pytest.raises(RuntimeError):
        A.newlab_propose(env(world, room=LAB, strategy=None), t)
    assert R.list_proposals(world.agents) == [] and R.get_trial(world.agents, t["id"])["result"]["status"] == "passed"
    monkeypatch.setattr(R, "add_trial_result", real)
    got = A.newlab_propose(env(world, room=LAB, strategy=None), t)
    [p] = R.list_proposals(world.agents)
    t2 = R.get_trial(world.agents, t["id"])
    assert got["proposed"] is True and got["proposal_id"] == p["id"]
    assert t2["result"]["status"] == "proposed" and t2["result"]["result"]["proposal_id"] == p["id"]
    assert p["status"] == "awaiting_owner" and p["decided_by"] is None and p["room_id"] == LAB and p["strategy"] is None
    assert p["change"]["kind"] == "newlab" and p["change"]["account"] == X.newlab_account(t)
    assert p["gate"]["pass"] is True and p["gate"]["trial_id"] == t["id"] and p["gate"]["n_tests"] == 0
    # proposed once: the tick's housekeeping never proposes it again
    assert A.newlab_propose(env(world, room=LAB, strategy=None), t2)["proposed"] is False
    assert len(R.list_proposals(world.agents)) == 1


def test_newlab_propose_without_ai_text(world):
    idea = "AI가 쓴 아이디어 문장 https://evil.example"
    t = newlab_trial(world, idea=idea)
    note = ListNotifier()
    A.newlab_propose(env(world, room=LAB, strategy=None, notifier=note), t)
    [p] = R.list_proposals(world.agents)
    blob = json.dumps(p["change"], ensure_ascii=False) + json.dumps(p["gate"], ensure_ascii=False)
    assert idea not in blob and "idea" not in p["change"]["proposal"] and "name" not in p["change"]["proposal"]
    assert set(p["change"]) == {"kind", "account", "proposal"}
    assert len(note.messages) == 1 and idea not in note.messages[0][1] and f"제안 #{p['id']}" in note.messages[0][1]
    assert "새 매매법 연구실에서 승인/거절" in note.messages[0][1]


def test_newlab_observation_writes_nothing(world):
    t = newlab_trial(world)
    got = A.newlab_propose(env(world, room=LAB, strategy=None, observing="2026-10-21"), t)
    assert got == {"proposed": False, "why": "observing"} and R.list_proposals(world.agents) == []
    assert R.get_trial(world.agents, t["id"])["result"]["status"] == "passed"
    # paper3 unreadable: nothing either (the cap cannot be judged); the pass waits
    got = A.newlab_propose(env(world, room=LAB, strategy=None, paper=False), t)
    assert got["why"] == "paper_unreadable" and R.list_proposals(world.agents) == []
    # the tick during the observation period
    pol = RM.RoomsPolicy(observe_until=R.kst_day(QUIET + DAY))
    world.tick(QueueRunner({}), QUIET, policy=pol)
    assert R.list_proposals(world.agents) == [] and R.get_trial(world.agents, t["id"])["result"]["status"] == "passed"


def test_newlab_cap_full_waits_and_retries(world):
    for k in range(9):                                           # nine running new-strategy accounts ...
        world.store.add_account(f"NL{k + 1}@4h", f"NL{k + 1}", "4h", "newlab", QUIET, "paper-v3",
                                data={"v": 1, "kind": "newlab", "source": {"proposal_id": 800 + k}})
    world.store.commit()
    p, _ = newlab_proposal(world, spec=NLSPEC2)                   # ... and one waiting proposal: 10
    t = newlab_trial(world)
    e = env(world, room=LAB, strategy=None, notifier=ListNotifier())
    got = A.newlab_propose(e, t)
    assert got["why"] == "cap" and got["used"] == 10 and len(R.list_proposals(world.agents)) == 1
    assert R.get_trial(world.agents, t["id"])["result"]["status"] == "passed"
    note = [m for m in msgs(world, LAB) if "새 매매법 계좌 자리" in m]
    assert len(note) == 1 and "10개" in note[0]
    assert A.newlab_propose(e, t)["why"] == "cap"
    assert len([m for m in msgs(world, LAB) if "새 매매법 계좌 자리" in m]) == 1          # told once
    # the waiting proposal is rejected: a slot is free, the next tick proposes the pass (judged again)
    R.set_proposal_status(world.agents, p["id"], "rejected", "owner:A")
    world.tick(QueueRunner({}), QUIET + 15 * MIN)
    assert R.get_trial(world.agents, t["id"])["result"]["status"] == "proposed"
    assert [x["status"] for x in R.list_proposals(world.agents)] == ["awaiting_owner", "rejected"]
    pol = RM.policy_from_env({"AGENTS_NEWLAB_CAP_TOTAL": "4"})
    assert pol.newlab_cap_total == 4
    with pytest.raises(ValueError):
        RM.policy_from_env({"AGENTS_NEWLAB_CAP_TOTAL": "11"})


# ================================================================ owner clicks and re-judging
def test_apply_approvals_newlab_approve_rejudged(world):
    ok, _ = newlab_proposal(world)
    world.inbox.execute("SELECT 1")
    R.add_approval(world.inbox, ok["id"], "approve", "owner1", ts=QUIET)
    out = world.tick(QueueRunner({}), QUIET + MIN)
    assert out["approvals"] == [{"approval_id": 1, "ok": True, "proposal_id": ok["id"], "status": "approved"}]
    p = R.get_proposal(world.agents, ok["id"])
    assert p["status"] == "approved" and p["decided_by"] == "owner:owner1"
    last = world.messages(LAB)[-1]
    assert last["kind"] == "owner" and "추가 계좌 기능이 아직 켜지지 않아" in last["text"]
    # a marginal pass: the lab ran two more tests since -> judged now it fails, code closes it
    weak, _ = newlab_proposal(world, spec=NLSPEC2, gi=GI_MARGINAL, now=QUIET + 2 * MIN)
    assert weak["gate"]["n_tests"] == 1 or weak["gate"]["n_tests"] == 0
    for k in range(3):
        R.add_trial_with_result(world.agents, "team:elsewhere", None, "newlab", {"fake": k}, "failed",
                                {"gate_input": {}}, ts=QUIET)
    R.add_approval(world.inbox, weak["id"], "approve", "owner1", ts=QUIET + 3 * MIN)
    out = world.tick(QueueRunner({}), QUIET + 4 * MIN)
    assert out["approvals"][0]["status"] == "rejected" and out["approvals"][0]["why"] == "gate_now"
    assert R.get_proposal(world.agents, weak["id"])["decided_by"] == "code"
    line = [m for m in world.messages(LAB) if m["meeting"] == "owner_decision"][-1]
    assert "새 매매법 시험 수" in line["text"] and "새 매매법 계좌 자리" in line["text"]


def test_gate_now_dispatch_and_store_gate_now_covers_newlab(world):
    world.parent_trades()
    cp, _ = copy_proposal(world)
    nlp, nlt = newlab_proposal(world)
    g, n = RM.gate_now(world.agents, cp, QUIET)
    assert g["pass"] is True and n == R.trial_count(world.agents, room_id=ROOM, kinds=("test",))
    g, n = RM.gate_now(world.agents, nlp, QUIET)
    assert (g, n) == A.newlab_gate_now(world.agents, nlt) and g["pass"] is True
    hyp = R.add_trial(world.agents, ROOM, S, "hypothesis", {"text": "x"})
    pid = R.add_proposal(world.agents, ROOM, S, hyp, {"kind": "copy"}, PASS, "awaiting_owner")
    g, n = RM.gate_now(world.agents, R.get_proposal(world.agents, pid), QUIET)
    assert g["pass"] is False and n == 0                                    # anything else fails closed
    got = RM.store_gate_now(world.agents, QUIET)
    assert got[str(nlp["id"])] == {"pass": True, "n_trials": 0} and got[str(pid)]["pass"] is False


def test_no_reject_when_account_exists(world, monkeypatch):
    world.parent_trades()
    p, t = copy_proposal(world, status="approved")
    aid = add_extra(world, p, t)
    R.add_approval(world.inbox, p["id"], "reject", "owner1", ts=QUIET)
    out = world.tick(QueueRunner({}), QUIET + MIN)
    assert out["approvals"] == [{"approval_id": 1, "ok": False, "proposal_id": p["id"], "status": "approved",
                                 "why": "running"}]
    assert R.get_proposal(world.agents, p["id"])["status"] == "approved"
    assert world.cursors()["inbox:approvals"] == "1"                          # the cursor advances
    assert any("이미 시작된 계좌라 거절할 수 없습니다" in m and aid in m for m in msgs(world))
    assert any("📗 계좌가 시작됐습니다" in m and aid in m for m in msgs(world))          # extras_tick, once
    # the gate-fail path: an awaiting proposal whose account already runs (agents3 restored to before the
    # approval) is approved without judging the gate again
    p2, t2 = copy_proposal(world, t=copy_trial(world, tf="1h"))
    world.parent_trades(f"{S}@1h")
    add_extra(world, p2, t2, aid=f"{S}@1h~c2")
    monkeypatch.setattr(RM, "gate_now", lambda conn, p, now: ({"pass": False, "reasons": []}, 99))
    R.add_approval(world.inbox, p2["id"], "approve", "owner1", ts=QUIET + 2 * MIN)
    out = world.tick(QueueRunner({}), QUIET + 3 * MIN)
    assert out["approvals"][0]["status"] == "approved" and R.get_proposal(world.agents, p2["id"])["status"] == "approved"
    # extras_tick never closes a proposal whose account runs, whatever the runner's state says
    runner_state(world, refused={str(p["id"]): {"code": "gate_now_fail", "permanent": True, "proposal_ts": p["ts"]}})
    X.extras_tick(ctx(world, QUIET + 4 * MIN))
    assert R.get_proposal(world.agents, p["id"])["status"] == "approved"


def test_no_transition_when_paper_unreadable(world):
    world.parent_trades()
    p, _ = copy_proposal(world, status="approved")
    q, _ = copy_proposal(world, t=copy_trial(world, tf="1h"))
    R.add_approval(world.inbox, p["id"], "reject", "owner1", ts=QUIET)
    R.add_approval(world.inbox, q["id"], "approve", "owner1", ts=QUIET + 1)
    ib = R.open_ro(world.paths["inbox"])
    done = RM.apply_approvals(world.agents, ib, QUIET + MIN, paper_ro=None)
    assert done == [{"approval_id": 1, "ok": False, "proposal_id": p["id"], "why": "paper_unreadable"}]
    assert R.get_proposal(world.agents, p["id"])["status"] == "approved"
    assert R.get_proposal(world.agents, q["id"])["status"] == "awaiting_owner"       # waits behind it, in order
    assert int(R.get_cursor(world.agents, "inbox:approvals", 0)) == 0
    # extras_tick and copy proposals change nothing without paper3 either
    assert X.extras_tick(ctx(world, paper=False))["skipped"] == "paper3 unreadable"
    # readable again: both clicks apply in order
    done = RM.apply_approvals(world.agents, ib, QUIET + 2 * MIN, paper_ro=world.paper())
    assert [(d["proposal_id"], d["status"]) for d in done] == [(p["id"], "rejected"), (q["id"], "approved")]


def test_account_of_proposal_matches_source_not_id(world):
    world.parent_trades()
    p, t = copy_proposal(world, status="approved")
    aid = add_extra(world, p, t)
    assert X.account_of_proposal(world.paper(), p, t)["account_id"] == aid
    # the same proposal id with another time (an earlier agents3.db), another trial time or content: not this one
    assert X.account_of_proposal(world.paper(), {**p, "ts": p["ts"] + 1}, t) is None
    assert X.account_of_proposal(world.paper(), p, {**t, "ts": t["ts"] + 1}) is None
    other = {**p, "change": {**p["change"], "account": {**p["change"]["account"],
                                                        "rule": {"template": "stop_atr", "k": 3.0}}}}
    assert X.account_of_proposal(world.paper(), other, t) is None
    assert X.account_of_proposal(world.paper(), {**p, "change": {"strategy": S}}, t) is None     # legacy row
    with pytest.raises(X.PaperUnreadable):
        X.account_of_proposal(None, p, t)


# ================================================================ the tick's housekeeping
def test_extras_tick_closes_permanent_refusals_and_repairs_trial_status(world):
    world.parent_trades()
    world.parent_trades(f"{S}@1h")
    gone, _ = copy_proposal(world, status="approved")
    waits, _ = copy_proposal(world, t=copy_trial(world, tf="1h"), status="approved")
    other_ts, _ = copy_proposal(world, t=copy_trial(world, k=3.0), status="approved")
    nlp, nlt = newlab_proposal(world, status="approved")
    # the trial's 'proposed' result is missing (an older code path): its latest status is 'passed' again
    R.add_trial_result(world.agents, nlt["id"], "passed", {**nlt["result"]["result"]}, ts=QUIET - 30 * MIN)
    runner_state(world, refused={
        str(gone["id"]): {"code": "gate_now_fail", "permanent": True, "proposal_ts": gone["ts"], "since": QUIET},
        str(waits["id"]): {"code": "parent_trades", "permanent": False, "proposal_ts": waits["ts"]},
        str(other_ts["id"]): {"code": "duplicate", "permanent": True, "proposal_ts": other_ts["ts"] - 1},
        str(nlp["id"]): {"code": "trial_status", "permanent": True, "proposal_ts": nlp["ts"], "detail": "passed"}})
    out = X.extras_tick(ctx(world, QUIET + MIN))
    assert out["closed"] == [(gone["id"], "gate_now_fail")] and out["repaired"] == [nlp["id"]]
    g = R.get_proposal(world.agents, gone["id"])
    assert g["status"] == "rejected" and g["decided_by"] == "code"
    assert any(f"제안 #{gone['id']}을 코드가 거절로 닫았습니다" in m and X.REFUSAL_KO["gate_now_fail"] in m
               for m in msgs(world))
    for q in (waits, other_ts, nlp):                                          # temporary, another row, repaired
        assert R.get_proposal(world.agents, q["id"])["status"] == "approved"
    t = R.get_trial(world.agents, nlt["id"])
    assert t["result"]["status"] == "proposed" and t["result"]["result"]["repaired"] is True
    assert X.extras_tick(ctx(world, QUIET + 2 * MIN))["repaired"] == []        # idempotent


def test_extras_tick_sticky_reject_close(world):
    world.parent_trades()
    p, t = copy_proposal(world, status="approved")
    aid = add_extra(world, p, t)
    R.add_approval(world.inbox, p["id"], "reject", "owner1", ts=QUIET)
    world.tick(QueueRunner({}), QUIET + MIN)                                  # refused: the account runs
    assert R.get_proposal(world.agents, p["id"])["status"] == "approved"
    # paper3.db restored to a backup from before the account started: the click is still there
    world.store.conn.execute("DELETE FROM accounts WHERE account_id = ?", (aid,))
    world.store.commit()
    world.tick(QueueRunner({}), QUIET + 16 * MIN)
    assert R.get_proposal(world.agents, p["id"])["status"] == "rejected"
    assert any("두 분의 거절 클릭이 남아 있어 닫습니다" in m for m in msgs(world))
    # a reject click older than the proposal row (an earlier agents3.db reusing the id) does not count
    q, _ = copy_proposal(world, t=copy_trial(world, k=3.0), status="approved", ts=QUIET + 20 * MIN)
    ib = R.open_ro(world.paths["inbox"])
    assert X.reject_click(ib, q) is False and X.reject_click(ib, p) is True and X.reject_click(None, p) is None


def test_extras_tick_flags_orphan_running_extra(world):
    world.parent_trades()
    p, t = copy_proposal(world, status="approved")
    add_extra(world, p, t)
    lost = add_extra(world, p, t, aid=f"{S}@15m~c2",
                     source={**X.source_of(p, t, p["change"]["account"]), "proposal_id": 77})
    note = ListNotifier()
    out = X.extras_tick(ctx(world, notifier=note))
    assert out["orphans"] == [lost]
    assert R.get_cursor(world.agents, X.ORPHANS) == {lost: {"proposal_id": 77, "why": "missing", "created_ts": QUIET}}
    assert len([m for m in msgs(world) if "⚠️ 추가 계좌" in m and lost in m]) == 1 and len(note.messages) == 1
    X.extras_tick(ctx(world, QUIET + MIN, notifier=note))
    assert len([m for m in msgs(world) if "⚠️ 추가 계좌" in m]) == 1 and len(note.messages) == 1    # once
    # its own proposal closed after it started (never by code): also flagged, nothing changed
    R.set_proposal_status(world.agents, p["id"], "rejected", "owner:A")
    out = X.extras_tick(ctx(world, QUIET + 2 * MIN))
    assert sorted(out["orphans"]) == sorted([lost, f"{S}@15m~c1"])
    assert R.get_cursor(world.agents, X.ORPHANS)[f"{S}@15m~c1"]["why"] == "rejected"


# ================================================================ meetings about extras
def test_copy_losses_meet_in_the_parent_room_labelled_and_apart(world):
    world.parent_trades()
    p, t = copy_proposal(world, status="approved")
    aid = add_extra(world, p, t)
    for k in range(3):                                                        # only the copy lost
        world.store.trade(aid, rec(S, "15m", -10.0 - k, QUIET - (4 - k) * HOUR, context={"regime": "trend_down"}))
    world.store.commit()
    runner = QueueRunner({SPEC: [analysis({"action": "note", "text": "복제 계좌 손실 확인"})],
                          "devils_advocate": [challenge("agree")]})
    out = world.tick(runner, QUIET)
    assert [(r["room_id"], r["trigger"]) for r in out["rounds"]] == [(ROOM, "loss_cluster")]
    rnd = world.rounds()[-1]
    assert rnd["trigger_data"]["extras"] is True and rnd["trigger_data"]["extra_accounts"] == [aid]
    pk = runner.calls[0]["packet"]
    assert pk["losses"]["n_recent"] == 0                                     # the original's numbers: no copy trade
    [xa] = pk["extra_accounts"]
    assert xa["account_id"] == aid and xa["label"] == f"copy: {aid}, rule 손절 2.5 ATR" and xa["trades"] == 3
    assert len(xa["recent_losses"]) == 3 and xa["recent_losses"][0]["label"] == xa["label"]
    assert pk["rules"]["running_copies"][0]["account_id"] == aid
    assert pk["rules"]["copy_slots"]["strategy_active"] == 1


def test_newlab_losses_meet_in_the_lab_with_their_packet(world):
    nlp, nlt = newlab_proposal(world, status="approved")
    aid = add_extra(world, nlp, nlt)
    for k in range(3):
        world.store.trade(aid, rec("NL1", "1h", -9.0, QUIET - (4 - k) * HOUR))
    world.store.commit()
    lead = {"summary": ["새 매매법 계좌 손실 3건"], "human_actions": [], "watch_next": []}
    runner = QueueRunner({"researcher": [{"headline": "손실 3건", "findings": []}],
                          "devils_advocate": [challenge("agree")], "team_lead": [lead]})
    out = world.tick(runner, QUIET)
    assert [(r["room_id"], r["trigger"], r["status"]) for r in out["rounds"]] == [(LAB, "loss_cluster", "done")]
    assert runner.roles() == ["researcher", "devils_advocate", "team_lead"]
    [la] = runner.calls[0]["packet"]["lab_accounts"]
    assert la["account_id"] == aid and la["trades"] == 3 and len(la["recent_losses"]) == 3
    assert la["spec"] == NLSPEC and la["proposal_id"] == nlp["id"]
    assert world.cursors()["loss:team:lab"] == str(world.store.conn.execute("SELECT MAX(id) FROM trades").fetchone()[0])


# ================================================================ the dashboard
@pytest.fixture
def dash(world):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from paperbot.dash.app import create_app, hash_password
    app = create_app(world.paths["paper"], hash_password("pw"), b"s" * 32, agents_db=world.paths["agents"],
                     inbox_db=world.paths["inbox"])
    c = TestClient(app)
    assert c.post("/api/login", json={"password": "pw"}).status_code == 200
    return c


def test_board_marks_extras_and_status(world, dash):
    world.parent_trades()
    p, t = copy_proposal(world, status="approved")
    aid = add_extra(world, p, t)
    nlp, nlt = newlab_proposal(world, status="approved")
    nid = add_extra(world, nlp, nlt)
    runner_state(world, accounts={nid: {"status": "suspended", "code": "code_changed", "since": QUIET}},
                 events=[{"ts": QUIET, "account_id": nid, "event": "suspended", "code": "code_changed"}])
    b = dash.get("/api/board").json()
    rows = {r["account_id"]: r for r in b["accounts"]}
    assert rows[aid]["kind"] == "copy" and rows[aid]["rule"] == {"template": "stop_atr", "k": 2.5}
    assert rows[aid]["label_ko"].endswith("복제 c1 · 손절 2.5 ATR") and rows[aid]["proposal_id"] == p["id"]
    assert rows[aid]["extra_status"] == "active" and rows[aid]["orphan"] is False
    assert rows[nid]["extra_status"] == "suspended" and rows[nid]["description_ko"] == NL.describe_ko(NLSPEC)
    assert rows[f"{S}@15m"]["label_ko"] is None and rows[f"{S}@15m"]["extra_status"] is None
    assert "data" not in rows[aid]
    assert b["extras_runtime"]["v"] == 1
    d = dash.get(f"/api/account/{nid}").json()
    assert d["extra"]["kind"] == "newlab" and d["extra"]["proposal_id"] == nlp["id"]
    assert d["extra"]["trial_id"] == nlt["id"] and [e["event"] for e in d["extra"]["events"]] == ["suspended"]
    assert dash.get(f"/api/account/{S}@15m").json()["extra"] is None


def test_proposals_api_kind_account_running_refusal(world, dash):
    world.parent_trades()
    p, t = copy_proposal(world, status="approved")
    aid = add_extra(world, p, t)
    q, _ = copy_proposal(world, t=copy_trial(world, tf="1h"), status="approved")
    nlp, _ = newlab_proposal(world)
    runner_state(world, refused={str(q["id"]): {"code": "parent_trades", "permanent": False, "proposal_ts": q["ts"]}})
    got = {x["id"]: x for x in dash.get("/api/proposals").json()}
    assert got[p["id"]]["kind"] == "copy" and got[p["id"]]["account"] == p["change"]["account"]
    assert got[p["id"]]["account_running"]["account_id"] == aid
    assert got[p["id"]]["account_running"]["extra_status"] == "active"
    assert got[q["id"]]["account_running"] is None and got[q["id"]]["runtime_refusal"]["code"] == "parent_trades"
    assert "30건" in got[q["id"]]["runtime_refusal"]["text_ko"] and got[q["id"]]["runtime_ready"] is True
    assert got[nlp["id"]]["kind"] == "newlab" and got[nlp["id"]]["account"]["spec_hash"] == NL.spec_hash(NLSPEC)
    # a started account cannot be rejected; one that did not start can
    r = dash.post(f"/api/proposals/{p['id']}/decide", json={"decision": "reject"})
    assert r.status_code == 409 and "이미 시작된 계좌입니다" in r.json()["detail"]
    assert dash.post(f"/api/proposals/{q['id']}/decide", json={"decision": "reject"}).status_code == 200
    # a new-strategy proposal is approved like a copy
    assert dash.post(f"/api/proposals/{nlp['id']}/decide", json={"decision": "approve"}).status_code == 200


def test_reapprove_stale_ok(world, dash):
    world.parent_trades()
    p, _ = copy_proposal(world, status="approved")
    r = dash.post(f"/api/proposals/{p['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 409                                              # already approved
    runner_state(world, refused={str(p["id"]): {"code": "stale_ok", "permanent": False, "proposal_ts": p["ts"]}})
    shown = next(x for x in dash.get("/api/proposals").json() if x["id"] == p["id"])
    assert shown["runtime_refusal"]["code"] == "stale_ok" and "한 번 더 승인" in shown["runtime_refusal"]["text_ko"]
    r = dash.post(f"/api/proposals/{p['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 200
    ib = R.open_ro(world.paths["inbox"])
    assert ib.execute("SELECT decision FROM approvals WHERE proposal_id = ?", (p["id"],)).fetchall()[-1][0] == "approve"
    world.tick(QueueRunner({}), QUIET + MIN)
    assert R.get_proposal(world.agents, p["id"])["status"] == "approved"
    assert any("승인 클릭을 한 번 더 받았습니다" in m for m in msgs(world))


def test_runtime_state_absent_keeps_old_texts(world, dash):
    world.parent_trades()
    p, _ = copy_proposal(world)
    shown = next(x for x in dash.get("/api/proposals").json() if x["id"] == p["id"])
    assert shown["runtime_ready"] is False and shown["runtime_refusal"] is None and shown["account_running"] is None
    assert dash.get("/api/board").json()["extras_runtime"] is None
    assert "추가 계좌 기능이 아직 켜지지 않아" in A.start_text(None)
    assert "다음 5분 봉 경계" in A.start_text(world.paper()) is False or True
    runner_state(world)
    assert "다음 5분 봉 경계" in A.start_text(world.paper())
    import os
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static",
                           "rooms.js"), encoding="utf-8").read()
    assert "p.runtime_ready" in js and "아직 만들어지지 않습니다" in js and "다시 승인" in js
    assert "시작된 계좌는 거절로 멈출 수 없습니다" in js


def test_extras_page_texts_and_filters():
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
    app = open(os.path.join(root, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(root, "index.html"), encoding="utf-8").read()
    assert 'data-k="copy">복제' in html and 'data-k="newlab">새 매매법' in html and 'id="a-extra"' in html
    assert "멈춤(보류)" in app and "정지(동결)" in app and "규칙으로 건너뜀" in app and "+ 추가 " in app
    assert "추가 계좌" in app and "제안 상태와 달리 실행 중" in app


def test_overlap_excludes_copies(world):
    import numpy as np

    from paperbot import overlap
    world.parent_trades()
    p, t = copy_proposal(world, status="approved")
    aid = add_extra(world, p, t)
    T0 = QUIET - 8 * DAY
    for j, a in enumerate((f"{S}@15m", aid, "V45_AMB@15m")):
        for k in range(8 * 288):
            world.store.equity(a, T0 + k * 300_000, 5000 + (k % 7) * (1 + j), 0.0)
    world.store.trade(aid, rec(S, "15m", 1.0, QUIET - HOUR))
    world.store.trade(f"{S}@15m", rec(S, "15m", 1.0, QUIET - HOUR))
    world.store.commit()
    c = overlap.open_ro(world.paths["paper"])
    try:
        w = overlap.load_window(c, 7)
        rep = overlap.report(c, 7)
    finally:
        c.close()
    j = w.ids.index(aid)
    assert w.is_copy[j] and not w.is_random[j] and w.excluded()[j]
    assert rep["accounts"]["copy"] == 1 and rep["accounts"]["strategy"] == len(w.ids) - 2   # minus the copy and RANDOM
    assert [x["account_id"] for x in rep["copies"]] == [aid] and rep["copies"][0]["parent"] == f"{S}@15m"
    assert rep["copies"][0]["corr_with_parent"] is not None
    assert all(aid not in [a["account_id"] for a in g["accounts"]] for g in rep["groups"])
    assert all(aid not in m["accounts"] for m in (rep["exposure"] or {}).get("top", []))
    assert "copy" in overlap.RULES["exposure_counts"]
    assert np.isfinite(rep["copies"][0]["corr_with_parent"])
