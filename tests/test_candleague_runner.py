"""candleague/runner.py on the shadow's synthetic bars: a day at once equals the same day in 5-minute pieces; a stop
and restart equals one run; another candidate list starts over; the judging rule; DeepSeek money stays hidden."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_paramshadow as TP  # noqa: E402
from candleague import candidates as C  # noqa: E402
from candleague import runner as RN  # noqa: E402
from paperbot import paramshadow as PS  # noqa: E402
from paperbot import sweepsig  # noqa: E402

data = {s: TP._synth5(i + 3, TP.P0[s]) for i, s in enumerate(TP.SYMS)}
START = TP.D0


def _accts(exit_="tp1R|1", st_mult=None):
    combo = C.default_combo("core", "S2_ST_ROC")
    if st_mult is not None:
        combo["st_mult"] = st_mult
    cand = {"id": "core-S2-15m-1", "kind": "core", "name": "S2_ST_ROC", "tf": "15m",
            "combo": {k: C._plain(v) for k, v in combo.items()}, "exit": exit_, "source": {}}
    return C.accounts([cand])


def _league(db, accts=None):
    return RN.League(RN.open_db(str(db)), accts or _accts(), TP.BRACKETS, TP.SPECS, sweepsig.lib(),
                     PS.FrameSource(data), TP._steps_from(data), TP.SYMS, start_ms=START, log=lambda s: None)


def _trades(lg):
    return [(a, json.loads(d)["entry_time"], json.loads(d)["exit_reason"], round(json.loads(d)["pnl"], 8))
            for a, d in lg.conn.execute("SELECT account, data FROM trades ORDER BY account, exit_time")]


def test_a_day_at_once_equals_five_minute_pieces(tmp_path):
    one = _league(tmp_path / "a.db")
    one.advance(START + 2 * TP.DAY)
    many = _league(tmp_path / "b.db")
    for t in range(START + RN.FIVE, START + 2 * TP.DAY + 1, 7 * RN.FIVE):
        many.advance(t)
    many.advance(START + 2 * TP.DAY)
    assert _trades(one) == _trades(many) and len(_trades(one)) > 5
    assert {a: e.wallet for a, e in one.engines.items()} == {a: e.wallet for a, e in many.engines.items()}


def test_stop_and_restart_equals_one_run(tmp_path):
    full = _league(tmp_path / "a.db")
    full.advance(START + 3 * TP.DAY)
    part = _league(tmp_path / "b.db")
    part.advance(START + TP.DAY + 13 * RN.FIVE)
    again = _league(tmp_path / "b.db")                        # a new process on the same database
    assert again.done == START + TP.DAY + 13 * RN.FIVE
    again.advance(START + 3 * TP.DAY)
    assert _trades(again) == _trades(full)


def test_another_candidate_list_starts_over(tmp_path):
    lg = _league(tmp_path / "a.db")
    lg.advance(START + TP.DAY)
    assert _trades(lg)
    lg2 = _league(tmp_path / "a.db", _accts(st_mult=9.0))
    assert lg2.done == START and _trades(lg2) == []


def test_judging_rule():
    def row(i, role, n, m, kind="core", name="X", tf="15m"):
        return {"id": i, "role": role, "kind": kind, "name": name, "tf": tf, "trades": n, "mean_ret": m}
    rows = [row("c1", "cand", 40, 0.01), row("c1-flip", "flip", 40, -0.002), row("base-core-X-15m", "base", 50, 0.004),
            row("c2", "cand", 12, 0.05), row("c2-flip", "flip", 12, 0.0),
            row("c3", "cand", 35, 0.003), row("c3-flip", "flip", 35, 0.001)]
    j = RN.judge(rows)
    assert j["c1"]["verdict"] == "ok" and j["c2"]["verdict"] == "early"
    assert j["c3"]["verdict"] == "not_yet" and j["c3"]["beats_base"] is False and j["c3"]["beats_flip"] is True


def test_deepseek_money_is_hidden_unless_allowed(tmp_path):
    lg = _league(tmp_path / "a.db")
    lg.advance(START + TP.DAY)
    accts = [dict(a, kind="ds") if a["role"] == "cand" else a for a in lg.accts]
    rows = RN.account_rows(lg.conn, accts, lg.engines)
    cand = next(r for r in rows if r["role"] == "cand")
    assert cand["wallet"] is None and cand["mean_ret"] is None and cand["trades"] > 0
    shown = next(r for r in RN.account_rows(lg.conn, accts, lg.engines, ds_money=True) if r["role"] == "cand")
    assert shown["wallet"] is not None
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, START + TP.DAY + 60_000)
    assert json.load(open(tmp_path / "snap" / "league.json"))["done_ms"] == doc["done_ms"] == START + TP.DAY


def test_final_end_waits_for_the_5m_bar():
    t = RN.FIVE * 1000
    assert RN.final_end(t + RN.SETTLE_MS) == t and RN.final_end(t + RN.SETTLE_MS - 1) == t - RN.FIVE
    assert RN.START_MS == 1_790_812_800_000
