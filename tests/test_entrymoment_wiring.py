"""Wiring of the 2026-10-04 additions into the meeting packets: ``coins.entry_moment`` (Wednesday coin and regime
meeting) and ``specialist.entry_moment`` (a strategy room), ``cost.real_slippage`` (Monday cost meeting,
slipcost.week_packet through ``daily_ro``) and the weekly checkpoint rehearsal (checkpoint_preview.latest_summary)
next to the checkpoint verdict. All read-only and bounded."""

import json
import os

import pytest

from paperbot.agents import entrymoment as EM
from paperbot.agents import meetings as M
from paperbot.agents import rooms as RM
from test_new_meetings import MON, V45, WED, bulk, tpol
from test_rooms import DAY, HOUR, MIN, NOTE, QUIET, S, SPEC, QueueRunner, World, analysis, challenge, team_answer

LEAD = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def _stop_row(aid, sym, real_bps, diff, t):
    return {"account_id": aid, "strategy": aid.split("@")[0], "timeframe": aid.split("@")[1], "symbol": sym,
            "side": 1, "exit_reason": "SL", "exit_time": t, "entry_time": t - HOUR, "qty": 1.0, "notional": 100.0,
            "stop": 99.0, "paper_exit": 98.98, "assumed_bps": 2.0, "paper_bps": 2.0, "status": "ok",
            "first_px": 98.99, "first_bps": 1.0, "est_px": 98.9, "real_bps": real_bps, "diff_usd": diff,
            "est_source": "trades", "thin": False}


def test_cost_packet_carries_the_nightly_real_slippage_bounded(world):
    bulk(world, 10, MON - HOUR, pnl=0.05)
    pk = M.cost_packet(world.paper(), MON)                                  # no daily_ro: says there is no record
    assert "기록 없음" in pk["real_slippage"]["stop_slippage"]["note"]
    for k, (bps, diff) in enumerate(((8.0, 0.1), (20.0, 0.4))):
        t = MON - (k + 2) * HOUR
        world.daily.execute("INSERT INTO stop_slips VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (f"k{k}", "2026-10-04", f"{S}@15m", S, "15m", "BTCUSDT", "SL", t, "ok", 2.0, bps, diff,
                             json.dumps(_stop_row(f"{S}@15m", "BTCUSDT", bps, diff, t))))
    world.daily.commit()
    for i, sym in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT")):
        for aid in (f"{S}@15m", f"{V45}@1h"):
            row = {"ts": MON - HOUR - i * MIN, "account_id": aid, "symbol": sym, "event": "entry", "status": "ok",
                   "notional": 100.0, "slip_best": 0.0001, "order_side": 1, "best": 100.0, "spread": 0.0002,
                   "enough": True, "filled_notional": 100.0, "book_ts": i,
                   "book": [[100.0, 1.0], [100.1, 50.0]]}
            world.store.conn.execute("INSERT INTO fill_costs (ts, account_id, symbol, event, status, notional, "
                                     "slip_best, data) VALUES (?,?,?,?,?,?,?,?)",
                                     (row["ts"], aid, sym, "entry", "ok", 100.0, 0.0001, json.dumps(row)))
    world.store.commit()
    pk = M.cost_packet(world.paper(), MON, daily_ro=world.daily)
    rs = pk["real_slippage"]
    assert rs["stop_slippage"]["exits"] == 2 and rs["stop_slippage"]["overall"]["real_bps_worst"] == 20.0
    sc = rs["size_costs"]
    assert len(sc["rows"]) == M.SLIP_ROWS and sc["rows_left_out"] == 14 - M.SLIP_ROWS
    assert sc["rows"][0]["x2"]["exact"] == 1                                   # walked on the recorded levels
    assert len(json.dumps(rs, ensure_ascii=False)) < 9_000


def test_the_cost_meeting_passes_the_daily_db(world):
    bulk(world, 250, MON - HOUR)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("cost_review",), cost_review_hour_kst=11))
    runner = QueueRunner({"exec_cost": [team_answer("e")], "ops_auditor": [team_answer("o")], "team_lead": [LEAD]})
    world.tick(runner, MON, policy=pol)
    rs = runner.calls[0]["packet"]["cost"]["real_slippage"]
    assert "stop_slippage" in rs and "size_costs" in rs
    assert "real_slippage" in runner.calls[0]["system"]                         # the prompt explains it


def test_the_coin_meeting_has_entry_moment_and_the_lead_sees_the_rehearsal(world, tmp_path):
    bulk(world, 250, WED - HOUR, context={"regime": "trend_up"})
    os.makedirs(tmp_path / "rehearsal")
    summary = {"status": "ok", "as_of": "2026-10-07", "days": 5, "finished_utc": "2026-10-07T04:00:00Z",
               "runtime_s": 812.5, "min_trades": 10, "bots": 500, "accounts_in_snapshot": 195, "tested": 40,
               "counts": {"1차 합격": 1}, "warnings": ["x" * 400] * 5,
               "zero_rate_accounts": [f"A{k}@5m" for k in range(9)], "out": "/var/lib/paperbot/rehearsal/x.db"}
    with open(tmp_path / "rehearsal" / "latest.json", "w") as fh:
        json.dump(summary, fh)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("coin_review",), coin_review_hour_kst=11))
    runner = QueueRunner({"coin_compare": [team_answer("c")], "regime_perf": [team_answer("r")], "team_lead": [LEAD]})
    world.tick(runner, WED, policy=pol)
    em = runner.calls[0]["packet"]["coins"]["entry_moment"]
    assert em["trades"] == 250 and em["all"]["hold"]["2h-8h"]["n"] == 250
    assert em["multiple_comparisons"]["buckets_examined"] > 0 and EM.compact_bytes(em) < EM.MAX_BYTES
    assert "가설" in runner.calls[0]["system"] and "entry_moment" in runner.calls[0]["system"]
    lead = runner.calls[-1]["packet"]
    reh = lead["board"]["checkpoint"]["rehearsal"]
    assert reh["available"] is True and reh["status"] == "ok" and reh["accounts_in_snapshot"] == 195
    assert reh["zero_rate_accounts"] == {"count": 9, "first": ["A0@5m", "A1@5m", "A2@5m", "A3@5m", "A4@5m"]}
    assert len(reh["warnings"]) == 3 and all(len(w) <= 160 for w in reh["warnings"]) and "out" not in reh
    assert "공식 판정이 아님" in reh["note"]


def test_no_rehearsal_file_is_said_plainly(world):
    ctx = RM.RoundContext(agents_conn=world.agents, paper_ro=world.paper(), daily_ro=None, inbox_ro=None,
                          runner=None, lab=None, now_ms=QUIET)
    out = RM._rehearsal(ctx)
    assert out["available"] is False and "기록 없음" in out["note"]
    assert RM._rehearsal(ctx) is out                                          # once per tick


def test_a_specialist_sees_its_own_entry_moment_brief(world):
    for k in range(7):
        world.trade(f"{S}@15m", 3.0, QUIET - 2 * DAY + k * HOUR)
    world.trade(f"{V45}@1h", 3.0, QUIET - 2 * DAY)
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE)], "devils_advocate": [challenge("agree")]})
    world.tick(runner, QUIET, policy=RM.RoomsPolicy(triggers=tpol(enabled=("loss_cluster",))))
    em = runner.calls[0]["packet"]["specialist"]["entry_moment"]
    assert em["trades"] == 10 and em["buckets"]["hold"]["2h-8h"]["n"] == 10
    assert EM.compact_bytes(em) < EM.BRIEF_MAX_BYTES and "가설" in em["note"]
    assert "entry_moment" in runner.calls[0]["system"]


def test_the_rehearsal_brief_reads_the_v4_keys_and_names_the_real_numbers(world, tmp_path):
    """L4: the rehearsal's runtime projection, expected/missing accounts and per-group rows reach the staff; the note
    says the summary's own trades and bots (2,000 by default) next to the real verdict's, never '500'."""
    from paperbot import checkpoint as CK
    os.makedirs(tmp_path / "rehearsal")
    summary = {"status": "ok", "as_of": "2026-10-28", "days": 23, "runtime_s": 900.0, "min_trades": 10,
               "bots": CK.REHEARSAL_BOTS, "verdict_runtime_s": 600.0, "projected_runtime_s_real": 3000.0,
               "n_bots_real": CK.N_BOTS, "accounts_expected": 241, "accounts_in_snapshot": 239,
               "missing_accounts": [f"M{k}@1h" for k in range(7)],
               "by_group": {"core": {"expected": 144, "found": 144, "tested": 100, "counts": {}},
                            "ds200": {"expected": 132, "found": 130, "tested": 3, "counts": {}}}}
    with open(tmp_path / "rehearsal" / "latest.json", "w") as fh:
        json.dump(summary, fh)
    ctx = RM.RoundContext(agents_conn=world.agents, paper_ro=world.paper(), daily_ro=None, inbox_ro=None,
                          runner=None, lab=None, now_ms=QUIET)
    out = RM._rehearsal(ctx)
    assert out["available"] and out["projected_runtime_s_real"] == 3000.0 and out["n_bots_real"] == CK.N_BOTS
    assert out["accounts_expected"] == 241 and out["by_group"]["ds200"]["found"] == 130
    assert out["missing_accounts"] == {"count": 7, "first": ["M0@1h", "M1@1h", "M2@1h", "M3@1h", "M4@1h"]}
    assert out["projected_runtime_s_day30"] == round(3000.0 * 30 / 23, 1) and out["timeout_s"] == 8 * 3600
    assert f"동전 봇 {CK.REHEARSAL_BOTS:,}개" in out["note"] and f"{CK.N_BOTS:,}개" in out["note"]
    assert "500개" not in out["note"]
