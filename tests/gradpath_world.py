"""A small world for 졸업 길 (dash/more/gradpath.py): the ana-syn synthetic paper3.db (tests/anasyn_world.py) plus an
agents3.db with a hypothesis ledger and five-year trials (written with the agents' own rooms_db functions), an inbox.db
with an owner post in the lab room, and a debate.db with ideas (debate.DB's own schema). Not market data: only shapes."""
from __future__ import annotations

import os

from paperbot.agents import rooms_db as R

DAY = 86_400_000
HOUR = 3_600_000

FAILED_GATE = {"pass": False, "checks": {"a": True, "b": False}, "reasons": [
    "① 1기간 거래당 평균 ROE +1.2%, p=0.004 — 기준 p < 0.05: 통과",
    "② 1기간 거래 120건(기준 300건 이상), 플러스 코인 2/6(과반): 미달",
    "③ 2기간 거래당 평균 ROE −0.4%: 미달"]}


def build(folder: str, now: int, *, days: int = 2, agents: bool = True, inbox: bool = True, debate: bool = True,
          ideas: bool = True) -> dict:
    """Returns {"paper", "agents", "inbox", "debate", "start"}; a part that is off is None (its file is not made)."""
    from anasyn_world import build as build_paper
    os.makedirs(folder, exist_ok=True)
    paper = os.path.join(folder, "paper3.db")
    start = now - (days - 1) * DAY - 20 * HOUR
    build_paper(paper, days=days, start=start)
    out = {"paper": paper, "agents": None, "inbox": None, "debate": None, "start": start}
    if agents:
        out["agents"] = p = os.path.join(folder, "agents3.db")
        c = R.open_agents(p)
        R.ensure_rooms(c, ts=start)
        if ideas:
            t0 = start + HOUR
            R.add_trial(c, "strat:S5_DONCHIAN_MFI", "S5_DONCHIAN_MFI", "hypothesis",
                        {"text": "주말에는 손절이 더 자주 난다", "how_to_confirm": "주말 거래 30건"}, ts=t0)
            h2 = R.add_trial(c, "team:review", None, "hypothesis",
                             {"text": "BTC가 오르는 날 롱이 더 잘 된다", "how_to_confirm": "",
                              "prediction": {"kind": "x"}, "by": "analyst"}, ts=t0 + HOUR)
            R.add_trial_result(c, h2, "graded", {"status": "graded", "correct": True, "n": 40}, ts=t0 + 2 * HOUR)
            # five-year tests: a number test that failed, one descriptive, a new strategy that failed and one that passed
            R.add_trial_with_result(c, "strat:S5_DONCHIAN_MFI", "S5_DONCHIAN_MFI", "test",
                                    {"template": "stop_atr", "strategy": "S5_DONCHIAN_MFI", "timeframe": "1h", "k": 2.0},
                                    "failed", {"result": {"ok": True}, "gate": FAILED_GATE, "n_trials": 1}, ts=t0 + 3 * HOUR)
            R.add_trial_with_result(c, "team:lab", None, "newlab",
                                    {"v": "newlab-v1", "timeframe": "1h", "entry": "a", "filters": [], "direction": "long"},
                                    "failed", {"gate": FAILED_GATE, "description_ko": "1시간봉 돌파 + 거래량 필터",
                                               "test_number": 1, "n_tests_so_far": 0}, ts=t0 + 4 * HOUR)
            R.add_trial_with_result(c, "team:lab", None, "newlab",
                                    {"v": "newlab-v1", "timeframe": "4h", "entry": "b", "filters": [], "direction": "short"},
                                    "passed", {"gate": {"pass": True, "reasons": ["① 통과"]},
                                               "description_ko": "4시간봉 되돌림 숏", "test_number": 2,
                                               "n_tests_so_far": 1}, ts=t0 + 5 * HOUR)
            # a passed number test whose copy proposal waits for the owners (the extras harness's own writer)
            from extras_harness import add_copy_proposal
            add_copy_proposal(c, None, "S2_ST_ROC", "30m", {"template": "stop_atr", "k": 1.5}, t0 + 6 * HOUR,
                              approve=False, click=False)
        c.close()
    if inbox:
        out["inbox"] = p = os.path.join(folder, "inbox.db")
        c = R.open_inbox_rw(p)
        if ideas:
            R.add_owner_message(c, "team:lab", "A", "펀딩비가 크게 음수일 때 롱만 들어가는 매매법도 시험해 주세요", ts=start + 7 * HOUR)
            R.add_owner_message(c, "strat:S2_ST_ROC", "B", "이 방 글은 아이디어로 세지 않음", ts=start + 8 * HOUR)
        c.close()
    if debate:
        from paperbot.agents.debate import DB
        out["debate"] = p = os.path.join(folder, "debate", "debate.db")
        db = DB(p)
        if ideas:
            for k, (txt, tag) in enumerate((("시간대별로 좋은 자리 비율을 본다", "entry"),
                                            ("변동성이 낮을 때는 쉬기", "filter"))):
                db.conn.execute("INSERT INTO debate_ideas (round_id, ts, text, tag, status) VALUES (?,?,?,?, 'new')",
                                (k + 1, start + (9 + k) * HOUR, txt, tag))
            db.conn.commit()
        db.close()
    return out
