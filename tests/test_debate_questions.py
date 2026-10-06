"""The debate room's question bank (paperbot/agents/debate_questions.py): one concrete, code-built question per round,
read-only, on the paper v4 shape (tests/debate_world.make_world(v4=True)) with a few planted trades so every kind has
its evidence. Every handle passes the lab's own checks, 5m is never offered, the rotation and the per-day limit hold,
and a question's section stays within its token budget."""

import json
import sqlite3

import pytest

from paperbot.agents import debate_packet as P
from paperbot.agents import debate_questions as Q
from paperbot.agents import labtests as LT
from paperbot.agents import newlab as NL
from paperbot.agents import rooms_db as R
from paperbot.models import TradeRecord
from paperbot.store3 import Store3

from debate_world import make_world

DAY, HOUR, MIN = 86_400_000, 3_600_000, 60_000
NOW = 1_791_158_400_000 + 10 * DAY + 14 * HOUR    # 2026-10-15 14:00 UTC = 23:00 KST
S = "N17_KC_RSI"
WORST = f"{S}@1h"
BUST = "S5_DONCHIAN_MFI@4h"
ENTRY = {"family": "ema_cross", "params": {"fast": 9, "slow": 21}}


def _rec(strat, tf, pnl, exit_time, side=1, context=None, symbol="BTCUSDT", margin=500.0):
    return TradeRecord(
        strategy_id=strat, symbol=symbol, timeframe=tf, side=side, signal_ts=exit_time - 3 * HOUR - 1,
        entry_time=exit_time - 3 * HOUR, entry_price=100.0, exit_time=exit_time, exit_price=99.0 if pnl < 0 else 101.0,
        exit_reason="SL" if pnl < 0 else "LOCK", qty=1.0, leverage=30, tier="normal", margin=margin, stop_price=99.0,
        tp_price=0.0, liq_price=90.0, fees=0.5, funding=0.0, pnl=pnl, roe=pnl / margin, price_move=0.0,
        mae_price=99.5, mfe_price=100.5, equity_after=5000.0 + pnl, score=0.0, context=context or {})


def rich_world(tmp_path):
    """The v4 shape plus: today's 5 big losses of the 36 (4 of them against the trend), a strategy account far below
    its coin flips, a week of '추세 반대 진입' trades that lose more than they win, a US-session 1h cell where most of
    the 36 lose, a bust of one of the 36, 5m losses of the reel and a 5m coin flip (never offered)."""
    w = make_world(tmp_path, NOW, days=4, per_day=80, v4=True)
    st = Store3(w["paper"])
    down = {"regime": "trend_down"}
    strategies = sorted({r[0].split("@")[0] for r in st.conn.execute("SELECT account_id FROM accounts WHERE kind = 'strategy'")})
    for k, (strat, tf) in enumerate([(S, "15m"), (S, "1h"), ("V45_AMB", "30m"), ("N02_ST_KST", "4h"),
                                     ("S2_ST_ROC", "1h")]):
        st.trade(f"{strat}@{tf}", _rec(strat, tf, -900.0 - k, NOW - (k + 1) * 10 * MIN, side=1,
                                       context=down if k < 4 else {}))
    for k in range(35):                                     # the worst account: 35 losing trades
        st.trade(WORST, _rec(S, "1h", -20.0, NOW - 3 * DAY + k * HOUR, side=1 if k % 2 else -1,
                             context=down if k % 3 == 0 else {}))
    for k in range(40):                                     # a week of the tag: 30 losers, 10 winners
        strat = strategies[k % 6]
        st.trade(f"{strat}@30m", _rec(strat, "30m", -15.0 if k < 30 else 12.0, NOW - 5 * DAY + k * HOUR, side=1,
                                      context=down))
    for i, strat in enumerate(strategies[:14]):             # the US session (UTC 16-24) on 1h: 14 strategies lose
        for k in range(6):
            entry = (NOW - 14 * HOUR) - 2 * DAY + 18 * HOUR + k * MIN + i          # UTC 18:00 two days ago
            st.trade(f"{strat}@1h", _rec(strat, "1h", -5.0, entry + 3 * HOUR, side=1))
    for k in range(5):                                      # 5m: the reel and a 5m coin flip lose big today
        st.trade("REEL_H1@5m", _rec("REEL_H1", "5m", -5000.0, NOW - k * MIN, context=down))
    flips = [r[0] for r in st.conn.execute("SELECT account_id FROM accounts WHERE kind = 'random' AND timeframe = '5m'")]
    for k in range(3):
        st.trade(flips[0], _rec(flips[0].split("@")[0], "5m", -4000.0, NOW - k * MIN, context=down))
    eng = json.loads(st.conn.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()[0])["engines"]
    eng[WORST]["wallet"] = 900.0
    eng[BUST] = {"wallet": 11.0, "bust": True}
    st.put_state("accounts", NOW, {"engines": eng})
    st.commit()
    st.conn.close()
    agents = str(tmp_path / "agents3.db")
    c = R.open_agents(agents)
    R.add_trial_with_result(c, R.LAB_ROOM, None, "newlab", NL.normalize_spec({"timeframe": "1h", "entry": ENTRY}),
                            "failed", {"ledger": {"checks": {"a": False, "b": True, "c": False, "d": True, "e": False,
                                                             "f": False}}}, ts=NOW - DAY)
    tid = R.add_trial(c, f"strat:{S}", S, "test", LT.normalize_spec({"template": "stop_atr", "timeframe": "1h", "k": 2.5}, S),
                      ts=NOW - DAY)
    R.add_trial_result(c, tid, "failed", {"gate": {"pass": False}}, ts=NOW - DAY)
    c.close()
    return {**w, "agents": agents}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return rich_world(tmp_path_factory.mktemp("dq"))


@pytest.fixture(scope="module")
def cands(world):
    return Q.candidates(world["paper"], world["daily"], world["agents"], NOW)


def by_kind(cands):
    out = {}
    for q in cands:
        out.setdefault(q.kind, []).append(q)
    return out


def test_every_kind_builds(cands):
    k = by_kind(cands)
    assert set(k) == set(Q.KINDS)
    big = k["big_losses"][0]
    assert big.question_ko.startswith("오늘 가장 크게 잃은 거래 5개") and len(big.evidence["losses"]) == 5
    assert big.evidence["window"] == "오늘(한국 시간)" and "추세 반대 진입" in big.claim_ko
    assert {"tag", "losses", "wins", "loss_share", "win_share"} <= set(big.evidence["tags_in_window"][0])
    assert big.key.startswith(f"big_losses:{P.kst_day(NOW)}:")
    worst = k["worst_vs_flip"][0]
    assert worst.evidence["account"] == WORST and worst.evidence["gap_to_coin_flips"] < 0
    assert worst.evidence["tested_here"][0]["test"]["template"] == "stop_atr"            # its room's earlier test
    assert worst.key == f"worst_vs_flip:{WORST}" and worst.n_evidence >= 35
    tag = k["loss_tag"][0]
    assert tag.evidence["tag"]["tag"] == "추세 반대 진입" and tag.evidence["tag"]["losses"] >= 30
    assert "건너뛰면 덜 잃나" in tag.question_ko and len(tag.handles["labtest"]) >= 1
    cell = k["session_cell"][0]
    assert cell.evidence["cell"]["session"] == "us" and cell.evidence["cell"]["timeframe"] == "1h"
    assert cell.evidence["cell"]["losing"] >= 12
    assert {f["window"] for f in cell.handles["newlab_filters"]} == {"asia", "europe"}
    ev = k["event"][0]
    assert ev.evidence["account"] == BUST and "파산" in ev.question_ko
    retro = k["retro"][0]
    assert retro.evidence["why_fail"]["tests"] == 1 and retro.evidence["why_fail"]["failed"]["⑥"] == 1
    assert "ema_cross" not in retro.handles["newlab_entries"] and retro.handles["newlab_entries"]


def test_every_handle_passes_the_lab_checks_and_5m_is_never_offered(cands):
    from paperbot.agents.actions import lab_strategies
    n = 0
    for q in cands:
        assert set(q.handles.get("strategies") or []) <= set(lab_strategies()), q.kind
        for h in q.handles.get("labtest") or []:
            assert h["timeframe"] in Q.TFS and h["template"] != "timeframe_only", (q.kind, h)
            assert h["strategy"] in lab_strategies(), (q.kind, h)
            assert LT.normalize_spec(h) == LT.normalize_spec(h, h["strategy"]) == {**h}, (q.kind, h)
            n += 1
        for f in q.handles.get("newlab_filters") or []:
            tf = q.handles.get("timeframe") or "1h"
            sp = NL.normalize_spec({"timeframe": tf, "entry": ENTRY, "filters": [f]})
            assert sp["filters"] == [f], (q.kind, f)
            n += 1
        for fam in q.handles.get("newlab_entries") or []:
            assert fam in NL.FAMILIES
        text = json.dumps(q.section(), ensure_ascii=False)
        assert '"5m"' not in text and "REEL_H1" not in text and "RANDOM_" not in text, q.kind
    assert n >= 10
    big = by_kind(cands)["big_losses"][0]
    assert all(c["tf"] in Q.TFS for c in big.evidence["losses"])                       # the reel's -5,000 is not here
    assert all(h["tag"] == "추세 반대 진입" for h in big.handles["labtest"] if h["template"] == "skip_tag")
    assert {"kind": "trend_ema", "length": 200} in big.handles["newlab_filters"]


def test_each_section_stays_within_its_token_budget(cands):
    for q in cands:
        assert q.tokens() <= Q.EVIDENCE_TOKENS, (q.kind, q.tokens())
        assert P.estimate_tokens(P.compact_json(q.evidence)) <= 900
    huge = Q.Question("loss_tag", "k", "질문", "주장", {"rows": [{"t": "가" * 300, "n": i} for i in range(200)],
                                                        "more": "나" * 3000}, {"labtest": [{"x": i} for i in range(30)]})
    Q._trim(huge)
    assert huge.tokens() <= Q.EVIDENCE_TOKENS and len(huge.handles["labtest"]) == Q.MAX_LAB_HANDLES


def test_an_event_is_only_a_new_one(world):
    from paperbot.agents import packets3
    board = packets3.build(world["paper"], world["daily"], NOW)
    marks = P.agenda_marks(board, None)
    again = Q.candidates(world["paper"], world["daily"], world["agents"], NOW, board=board, seen=marks)
    assert "event" not in {q.kind for q in again}                                  # seen by the last ok round


def test_an_event_names_a_critical_alert_of_the_36_never_a_coin_flip(world):
    from paperbot.agents import packets3
    board = packets3.build(world["paper"], world["daily"], NOW)
    flip = next(a for a in board["league"]["15m"]["coin_flip_wallets"])
    board["today"]["alerts"] = [{"ts": NOW - MIN, "level": "CRITICAL", "text": f"[{flip}] LIQUIDATED BTCUSDT 30x"},
                                {"ts": NOW - 2 * MIN, "level": "CRITICAL", "text": f"[{WORST}] LIQUIDATED BTCUSDT 30x"}]
    paper = P.open_ro(world["paper"])
    try:
        q = Q.q_event(paper, board, NOW)
    finally:
        paper.close()
    assert q.evidence["account"] == WORST and q.handles["strategies"] == [S]
    assert len(q.evidence["last_losses"]) == 5 and {h["timeframe"] for h in q.handles["labtest"]} == {"1h"}


def _q(kind, key, n=1):
    return Q.Question(kind, key, f"{kind} 질문", "주장", {}, {}, n)


def test_pick_rotates_kinds_and_limits_a_key_to_three_rounds_a_day():
    cands = [_q("big_losses", "b1", 50), _q("worst_vs_flip", "w1", 40), _q("worst_vs_flip", "w2", 90),
             _q("loss_tag", "l1", 30), _q("retro", "r1")]
    asked, last, seen = {}, None, []
    morning = Q.kst_day_start(NOW) + HOUR                                           # 01:00 KST: 12 rounds, one day
    for k in range(12):
        now = morning + k * 45 * MIN
        q = Q.pick(cands, asked, last, now)
        assert q is not None and q.kind != last                                     # never the same kind twice in a row
        seen.append(q.key)
        asked[q.key] = Q.asked_record(asked.get(q.key), q, now)
        last = q.kind
    # rotation with the strongest of a kind first; each key 3 rounds a KST day; retro only when nothing else is fresh
    assert seen == ["b1", "w2", "l1", "b1", "w2", "l1", "b1", "w2", "l1", "w1", "r1", "w1"]
    assert asked["b1"] == {"day": P.kst_day(morning), "n": 3, "ts": morning + 6 * 45 * MIN, "n_evidence": 50,
                           "kind": "big_losses"}
    # an event jumps the queue; a forced round (6 hours without news) asks the retro question
    assert Q.pick(cands + [_q("event", "e1")], {}, "big_losses", NOW).key == "e1"
    assert Q.pick(cands, {}, None, NOW, force=True).key == "r1"
    # nothing fresh -> None (a free 'no_question' skip); the only fresh kind was the last one -> None too
    full = {q.key: {"day": P.kst_day(NOW), "n": 3} for q in cands}
    assert Q.pick(cands, full, None, NOW) is None
    assert Q.pick([_q("loss_tag", "l9")], {}, "loss_tag", NOW) is None


def test_the_three_a_day_limit_holds_across_kst_midnight_and_worst_vs_flip_refreshes():
    q = _q("loss_tag", "l1")
    late = Q.kst_day_start(NOW) + 23 * HOUR + 30 * MIN
    rec = None
    for i in range(3):
        rec = Q.asked_record(rec, q, late - i * MIN)
    assert not Q.eligible(q, {"l1": rec}, late) and Q.eligible(q, {"l1": rec}, late + HOUR)    # the next KST day
    w = _q("worst_vs_flip", "w1", 100)
    r = Q.asked_record(None, w, NOW)
    nxt = NOW + DAY
    assert not Q.eligible(w, {"w1": r}, nxt)                                        # the next day: not fresh yet
    assert Q.eligible(w, {"w1": r}, NOW + 3 * DAY)                                  # after 3 days
    assert Q.eligible(_q("worst_vs_flip", "w1", 150), {"w1": r}, nxt)               # or 50 more trades


def test_missing_databases_still_give_the_retro_question(tmp_path):
    w = make_world(tmp_path, NOW, days=1, per_day=10, v4=True)
    out = Q.candidates(w["paper"], w["daily"], str(tmp_path / "no_agents.db"), NOW)
    assert [q.kind for q in out][-1] == "retro" and out[-1].evidence["why_fail"]["tests"] == 0
    with sqlite3.connect(str(tmp_path / "empty.db")) as c:
        c.execute("CREATE TABLE x (y)")
    assert Q.q_retro(P.open_ro(str(tmp_path / "empty.db")), NOW).kind == "retro"
