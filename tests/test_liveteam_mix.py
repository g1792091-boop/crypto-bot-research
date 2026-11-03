"""실거래 분석팀 on the three live bots (owners 11-01 "다 해줘": the AI team meets on 바이비트 봇 · 친구 15분 봇 · 레인지 봇).

On the 관제실's own test world (tests/test_dash_livedeck.py: the 레인지 봇 trading WOO X Pro with one closed trade and an
open short, the 바이비트 봇 installed without trades, the friend bot not installed):
- mix_sources reads the three bots through the 관제실's readers (each bot's record, every closed trade, the position, the
  goal and the month); one bot's broken files never hide the others
- the meetings: daily (every day from 09:00 KST about the day before, quiet without a closed trade), loss (a bot's last
  two closed trades both lost, within 3 days, once per pair), weekly (Monday from 10:00 KST)
- the packet (facts_mix) and the members' instructions (mix_prompt: read only, the owners' decisions fixed, no promise of
  the ×6 goal, no verdict before 20 trades), the meeting held with a fake runner and stored under the bots' own key
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from paperbot import liveteam as T  # noqa: E402
from paperbot.agents import runner as R  # noqa: E402
from tests.test_dash_livedeck import DAY0, H, NOW, world  # noqa: E402,F401  (the 관제실's test world)

DAY = T.DAY


def _src(now=NOW):
    return {"now": now, "mix": T.mix_sources(now)}


def test_the_three_bots_read_through_the_deck(world):
    mx = T.mix_sources(NOW)
    assert mx["state"] == "ok" and [b["id"] for b in mx["bots"]] == ["bybit", "mix", "range"]
    rng = mx["bots"][2]
    assert rng["position"]["state"] == "ok" and rng["position"]["coin"] == "SOL" and len(rng["_trades"]) == 1
    assert rng["_trades"][0]["pnl"] == pytest.approx(-3.5)
    assert mx["goal"]["target"] == 6 and mx["month"]["days_n"] in (28, 29, 30, 31)


def test_the_daily_meeting_its_packet_and_the_members_words(world):
    d0 = ((NOW + T.KST_MS) // DAY) * DAY - T.KST_MS                  # NOW's KST day
    src = _src()
    # before 09:00 KST: not yet; from 09:00: once a day, about the day before
    assert T.due_daily_mix({**src, "now": d0 + 8 * H}) is None
    key, focus = T.due_daily_mix({**src, "now": d0 + 9 * H})
    assert key == f"daily:mix:{T.kst_date(d0 - DAY)}" and focus == {"bot": "mix", "window": [d0 - DAY, d0]}
    # no bot with a record: no meeting
    assert T.due_daily_mix({"now": d0 + 10 * H, "mix": {"bots": [{"id": "x"}]}}) is None
    # the packet of the day the 레인지 봇 closed its trade
    ex = src["mix"]["bots"][2]["_trades"][0]["exit_ms"]
    e0 = ((ex + T.KST_MS) // DAY) * DAY - T.KST_MS
    pk = T.packet_for(src, "daily", {"bot": "mix", "window": [e0, e0 + DAY]})
    assert T.packet_mix(pk) and pk["bot"]["names"] == ["바이비트 봇", "친구 15분 봇", "레인지 봇"]
    assert pk["meeting"] == f"세 실거래 봇 하루 회의 ({T.kst_md(e0)})"
    (t,) = pk["trades"]
    assert (t["bot"], t["coin"], t["side"], t["pnl"]) == ("레인지 봇", "SOL", "숏", -3.5)
    b = {x["name"]: x for x in pk["bots"]}["레인지 봇"]
    assert b["window"] == {"n": 1, "wins": 0, "losses": 1, "unknown": 0, "pnl": -3.5}
    assert b["position"]["coin"] == "SOL" and b["position"]["side"] == "숏" and b["record_since_start"]["n"] == 1
    assert b["rules"]["entry_bar"] == "15분" and b["rules"]["trend_bar"] == "30분"
    assert pk["calendar"]["need"] == pytest.approx(6 ** (1 / 30) - 1) and "words" in pk
    assert any("2포지션" in x for x in pk["decisions"]) and any("지정가" in x for x in pk["decisions"])
    # the members' instructions: the three bots', read only, the decisions fixed, no promise, 20 trades
    for role in T.KIND_ROLES["daily"]:
        sp = T.prompt_for(role, pk)
        # (owners 11-03: the two WOO X Pro bots, the 바이비트 봇 off)
        assert sp == T.mix_prompt(role) and "레인지 봇 = WOO X Pro 1 · 친구 15분 봇 = WOO X Pro 2, 바이비트 봇은 꺼 둠" in sp
        assert "매매 권한이 없습니다" in sp and "약속하지 않습니다" in sp and f"{T.SMALL_N}번보다 적으면" in sp
    assert '"verdict"' in T.mix_prompt("lead") and '"luck"' in T.mix_prompt("risk")
    assert T.kind_ko("daily", "daily:mix:2026-11-01") == "실거래 봇 하루 회의" and T.KIND_ROLES["daily"] == ("risk", "stats", "lead")


def test_the_loss_meeting_once_per_pair():
    now = 1_800_000_000_000
    bot = {"id": "range", "name_ko": "레인지 봇",
           "_trades": [{"exit_ms": now - 2 * H, "pnl": -2.0, "coin": "SOL", "side": -1, "roe": -0.4, "why_ko": "손절"},
                       {"exit_ms": now - 5 * H, "pnl": -3.0, "coin": "ETH", "side": 1, "roe": -0.5, "why_ko": "손절"},
                       {"exit_ms": now - 9 * H, "pnl": 4.0, "coin": "ETH", "side": 1}]}
    key, focus = T.due_loss_mix({"now": now, "mix": {"bots": [{"id": "bybit"}, bot]}})
    assert key == f"loss:mix:range:{now - 5 * H}+{now - 2 * H}" and focus["bot"] == "mix" and focus["name_ko"] == "레인지 봇"
    assert [(x["coin"], x["side"], x["pnl"]) for x in focus["losses"]] == [("ETH", "롱", -3.0), ("SOL", "숏", -2.0)]
    pk = T.packet_for({"now": now, "mix": {"bots": [bot]}}, "loss", focus)
    assert pk["meeting"] == "레인지 봇 손실 회의" and len(pk["focus"]["losses"]) == 2 and len(pk["trades"]) == 3
    # the last one won / a P&L not read / older than 3 days: no meeting
    won = {**bot, "_trades": [{"exit_ms": now - H, "pnl": 1.0}] + bot["_trades"]}
    assert T.due_loss_mix({"now": now, "mix": {"bots": [won]}}) is None
    assert T.due_loss_mix({"now": now + 4 * DAY, "mix": {"bots": [bot]}}) is None
    unknown = {**bot, "_trades": [{"exit_ms": now - H, "pnl": None}, bot["_trades"][0]]}
    assert T.due_loss_mix({"now": now, "mix": {"bots": [unknown]}}) is None


def test_the_weekly_report_on_its_moment():
    mon = T.monday_09(1_800_000_000_000)
    src = {"now": mon + 2 * H, "mix": {"bots": [{"id": "range", "curve": [[mon - 2 * DAY, 100.0]]}]}}
    key, focus = T.due_weekly_mix(src)
    assert key == f"weekly:mix:{T.kst_date(mon)}" and focus == {"window": [mon - 7 * DAY, mon], "bot": "mix"}
    assert T.due_weekly_mix({**src, "now": mon + 30 * T.MIN}) is None             # (from 10:00 KST)
    assert T.due_weekly_mix({**src, "mix": {"bots": [{"id": "x"}]}}) is None      # (no bot with a record)


def test_held_with_a_fake_runner_quiet_without_trades(world, tmp_path):
    conn = T.connect(str(tmp_path / "team.db"))
    src = _src()
    ex = src["mix"]["bots"][2]["_trades"][0]["exit_ms"]
    e0 = ((ex + T.KST_MS) // DAY) * DAY - T.KST_MS
    day_after = {**src, "now": e0 + DAY + 10 * H}                                  # the morning after the losing trade
    keys = [k for _kind, k, _f in T.due(conn, day_after)]
    assert f"daily:mix:{T.kst_date(e0)}" in keys
    run = R.FakeRunner()
    got = T.tick(conn, day_after, run, T.BUDGET_DEFAULT, dry=True, only="daily", mix=True)
    assert got["state"] == "done" and got["key"] == f"daily:mix:{T.kst_date(e0)}"
    assert [c["role"] for c in run.calls] == ["risk", "stats", "lead"] and T.packet_mix(run.calls[0]["packet"]["facts"])
    row = conn.execute("SELECT kind, title, state FROM meetings WHERE key = ?", (got["key"],)).fetchone()
    assert row[0] == "daily" and row[1].startswith("세 실거래 봇 하루 회의") and row[2] == "done"
    # held once: not due again; a day without a closed trade is a quiet line without AI
    assert got["key"] not in [k for _kind, k, _f in T.due(conn, day_after)]
    quiet_day = {**src, "now": e0 + 3 * DAY + 10 * H}
    q = T.tick(conn, quiet_day, R.FakeRunner(), T.BUDGET_DEFAULT, dry=True, only="daily", mix=True)
    assert q["state"] == "quiet" and "어제 실거래 봇들이 닫은 거래가 없어" in q["why"]
    # by hand: run daily --force (always the three bots')
    f = T.tick(conn, day_after, R.FakeRunner(), T.BUDGET_DEFAULT, dry=True, only="daily", force=True)
    assert f["key"].startswith("daily:mix:manual:") and f["state"] in ("done", "quiet")
    conn.close()
