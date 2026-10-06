"""Tiny synthetic agents3.db / debate.db for the 운 vs 실력 tests and the screenshot harness (luck-calc).

make_agents(path, newlab=[status...], tests=[(room, status)...], hyps=[correct True/False/None...])
make_debate(path, hits=[True/False...], base_rate=None)
Both write only the given file (a temporary one in tests)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperbot.agents import rooms_db as R  # noqa: E402

T0 = 1_791_300_000_000


def make_agents(path: str, newlab=(), tests=(), hyps=()) -> str:
    c = R.open_agents(path)
    try:
        R.ensure_rooms(c, ts=T0)
        for i, st in enumerate(newlab):
            R.add_trial_with_result(c, R.LAB_ROOM, None, "newlab", {"timeframe": "1h", "n": i}, st,
                                    {"ledger": {"n": i}}, ts=T0 + i)
        for i, (room, st) in enumerate(tests):
            R.add_trial_with_result(c, room, room.split(":", 1)[-1], "test", {"template": "t", "n": i}, st,
                                    {"gate": {"pass": st == "passed"}}, ts=T0 + 1000 + i)
        for i, ok in enumerate(hyps):
            spec = {"by": "researcher", "text": f"h{i}",
                    "prediction": {"metric": "win_rate", "timeframe": "1h", "direction": "above", "value": 0.5,
                                   "after_trades": 30}}
            tid = R.add_trial(c, "strat:S5_DONCHIAN_MFI", "S5_DONCHIAN_MFI", "hypothesis", spec, ts=T0 + 2000 + i)
            if ok is not None:
                R.add_trial_result(c, tid, "graded", {"status": "graded", "correct": bool(ok)}, ts=T0 + 3000 + i)
        c.commit()
    finally:
        c.close()
    return path


def make_debate(path: str, hits=(), base_rate=None) -> str:
    from paperbot.agents.debate import DB
    db = DB(path)
    try:
        for i, hit in enumerate(hits):
            params = {"kind": "strategy_roe_sign", "params": {"strategy": "S5_DONCHIAN_MFI", "tf": "1h", "op": ">", "n": 10}}
            if base_rate is not None:
                params["params"]["base_rate"] = base_rate
            db.conn.execute("INSERT INTO debate_hypotheses (round_id, ts, speaker, kind, params_json, horizon, status, outcome, "
                            "graded_ts) VALUES (?,?,?,?,?,?,?,?,?)",
                            (1, T0 + i, "bull", "strategy_roe_sign", json.dumps(params), "", "graded",
                             "hit" if hit else "miss", T0 + 5000 + i))
        db.conn.commit()
    finally:
        db.conn.close()
    return path


if __name__ == "__main__":   # quick look
    p = sys.argv[1] if len(sys.argv) > 1 else "/tmp/agents3.db"
    make_agents(p, newlab=["failed"] * 5, tests=[("strat:S5", "failed")], hyps=[True, False])
    print(sqlite3.connect(p).execute("SELECT kind, COUNT(*) FROM trials GROUP BY kind").fetchall())
