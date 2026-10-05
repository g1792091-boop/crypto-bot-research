"""agents/entrymoment.py for the v4 groups (owners' request 2026-10-06 00:45 KST): DeepSeek (kind ds200, core
timeframes) and the reel (5m) are analysed too, the reel next to its three 5m coin flips; 추세 초입·중간·막판
(trend_stage), range position and trend alignment with fixed edges; DeepSeek and the coin flips without money."""

import json

import pytest

from paperbot.agents import entrymoment as EM
from paperbot.config import REEL_NAME, REEL_TF
from test_agents_v4 import LEAD, V4World
from test_rooms import HOUR, QUIET, QueueRunner, S, team_answer

UP = {"regime": "trend_up", "htf_regime": "trend_up", "ema20_dist_atr": 0.5, "range_pct": 0.2}


# ------------------------------------------------------------------ B: bucket edges
@pytest.mark.parametrize("x,long_b,short_b", [
    (-0.01, "역방향", "초입"), (0.0, "초입", "초입"), (0.99, "초입", "역방향"), (1.0, "중간", "역방향"),
    (1.99, "중간", "역방향"), (2.0, "막판", "역방향"), (-1.0, "역방향", "중간"), (-2.0, "역방향", "막판"),
    (-1.5, "역방향", "중간"), (3.0, "막판", "역방향")])
def test_trend_stage_edges_for_longs_and_shorts(x, long_b, short_b):
    assert EM.trend_stage_bucket({"ema20_dist_atr": x}, 1) == long_b
    assert EM.trend_stage_bucket({"ema20_dist_atr": x}, -1) == short_b


def test_stage_edges_are_the_named_constants():
    assert EM.STAGE_EDGES == (0.0, 1.0, 2.0) and EM.RANGE_EDGES == (0.33, 0.67)
    assert EM.BUCKETS["trend_stage"] == ("역방향", "초입", "중간", "막판", "unknown")
    assert EM.BUCKETS["range_pos"] == ("아래쪽", "가운데", "위쪽", "unknown")
    assert EM.BUCKETS["trend_align"] == ("같은 방향", "반대", "횡보·불분명", "unknown")
    for d in EM.STAGE_DIMS:
        assert d in EM.DIMS and d in EM.BRIEF_DROP and d in EM.HOW_TO_READ
    assert set(EM.BRIEF_DROP) == set(EM.DIMS) - {"strength"}


@pytest.mark.parametrize("rp,long_b,short_b", [
    (0.0, "아래쪽", "위쪽"), (0.32, "아래쪽", "위쪽"), (0.33, "가운데", "위쪽"), (0.34, "가운데", "가운데"), (0.5, "가운데", "가운데"),
    (0.66, "가운데", "가운데"), (0.67, "위쪽", "가운데"), (0.68, "위쪽", "아래쪽"), (1.0, "위쪽", "아래쪽")])
def test_range_pos_edges_for_longs_and_shorts(rp, long_b, short_b):
    assert EM.range_pos_bucket({"range_pct": rp}, 1) == long_b
    assert EM.range_pos_bucket({"range_pct": rp}, -1) == short_b


def test_trend_align_for_longs_and_shorts():
    f = EM.trend_align_bucket
    assert f({"regime": "trend_up"}, 1) == "같은 방향" and f({"regime": "trend_up"}, -1) == "반대"
    assert f({"regime": "trend_down", "htf_regime": "trend_down"}, -1) == "같은 방향"
    assert f({"regime": "trend_up", "htf_regime": "trend_down"}, 1) == "반대"       # either against: 반대
    assert f({"regime": "box", "htf_regime": "trend_up"}, 1) == "같은 방향"
    assert f({"regime": "chop", "htf_regime": "unknown"}, 1) == "횡보·불분명"
    assert f({"regime": "box"}, -1) == "횡보·불분명"


def test_missing_or_odd_context_is_unknown_never_a_crash():
    for ctx in ({}, {"ema20_dist_atr": None, "range_pct": None, "regime": None}, {"ema20_dist_atr": "x"},
                {"ema20_dist_atr": float("nan"), "range_pct": float("inf")}, {"regime": "", "htf_regime": 3}):
        b = EM.stage_buckets({"context": ctx}, 1)
        assert set(b.values()) == {"unknown"}, ctx
    assert set(EM.stage_buckets({"context": "not a dict"}, -1).values()) == {"unknown"}
    assert set(EM.stage_buckets({}, 1).values()) == {"unknown"}


# ------------------------------------------------------------------ A: DeepSeek and the reel get rows
@pytest.fixture
def w(tmp_path):
    w = V4World(tmp_path)
    w.trade(f"{S}@15m", 5.0, QUIET - 5 * HOUR, context=UP)
    w.trade("F3_BOS@15m", -4.0, QUIET - 4 * HOUR, side=-1,
            context={"regime": "trend_up", "ema20_dist_atr": -2.5, "range_pct": 0.1})
    w.trade("F9_FVG@1h", 3.0, QUIET - 3 * HOUR, context=UP)
    w.trade(f"{REEL_NAME}@5m", 2.0, QUIET - 2 * HOUR, context={"ema20_dist_atr": 1.2})     # 5m: htf / range missing
    w.trade(f"{REEL_NAME}@5m", -1.0, QUIET - 90 * 60_000, context={})
    w.trade("RANDOM_1@5m", -3.0, QUIET - HOUR, context={"ema20_dist_atr": 2.4, "regime": "chop"})
    w.trade("RANDOM_2@5m", 1.0, QUIET - HOUR, context={"ema20_dist_atr": 1.5})
    w.trade("RANDOM_1@15m", 7.0, QUIET - HOUR, context=UP)                                 # a core flip
    return w


def test_default_is_the_36_only_and_unchanged(w):
    feat = EM.features(w.paper(), QUIET)
    assert [(r["kind"], r["strategy"]) for r in feat["rows"]] == [("strategy", S)]
    b = feat["rows"][0]["b"]
    assert (b["trend_stage"], b["range_pos"], b["trend_align"]) == ("초입", "아래쪽", "같은 방향")
    assert feat["coverage"]["trend_stage"] == 1


def test_deepseek_and_reel_rows_are_analysed(w):
    ds = EM.features(w.paper(), QUIET, kinds=("ds200",))
    assert sorted(r["strategy"] for r in ds["rows"]) == ["F3_BOS", "F9_FVG"]
    short = next(r for r in ds["rows"] if r["strategy"] == "F3_BOS")["b"]
    # a short 2.5 ATR below EMA20 is 2.5 ATR along its way: 막판; range_pct 0.1 seen from a short: 위쪽; regime up: 반대
    assert (short["trend_stage"], short["range_pos"], short["trend_align"]) == ("막판", "위쪽", "반대")
    reel = EM.features(w.paper(), QUIET, kinds=("reel",), timeframes=EM.REEL_TFS)
    assert [r["strategy"] for r in reel["rows"]] == [REEL_NAME, REEL_NAME]
    b0, b1 = reel["rows"][0]["b"], reel["rows"][1]["b"]
    assert (b0["trend_stage"], b0["range_pos"], b0["trend_align"]) == ("중간", "unknown", "unknown")
    assert {b1[d] for d in EM.STAGE_DIMS} == {"unknown"}
    # without the 5m timeframe the reel has nothing (the core timeframes only)
    assert EM.features(w.paper(), QUIET, kinds=("reel",))["rows"] == []
    assert EM.REEL_TFS == (REEL_TF,)


def test_the_reel_is_set_next_to_its_three_5m_flips(w):
    v = EM.group_dash_view(w.paper(), QUIET, "reel")
    assert v["group"] == "reel" and v["trades"] == 2 and v["flip_trades"] == 2      # the 15m flip is not the reel's
    assert v["all"]["trend_stage"]["중간"]["n"] == 1
    assert v["coin_flips"]["trend_stage"] == {"중간": {"n": 1, "wr": 1.0, "roe": pytest.approx(0.02), "small": True},
                                              "막판": {"n": 1, "wr": 0.0, "roe": pytest.approx(-0.06), "small": True}}
    assert v["flip_all"]["n"] == 2 and "eq" not in json.dumps(v["coin_flips"]) and v["coin_flips_note"]
    assert "no_money" not in v and "eq" in v["all"]["hold"]["2h-8h"]                # the reel keeps its own eq


def test_the_deepseek_view_has_no_money(w):
    v = EM.group_dash_view(w.paper(), QUIET, "ds200")
    s = json.dumps(v, ensure_ascii=False)
    assert v["no_money"] is True and v["trades"] == 2 and v["group"] == "ds200"
    assert '"eq"' not in s and '"pnl"' not in s and "$" not in s
    assert v["all"]["trend_align"]["반대"]["n"] == 1 and set(v["all"]["hold"]["2h-8h"]) <= {"n", "wr", "roe", "small"}
    core = EM.group_dash_view(w.paper(), QUIET, "core")
    assert core["trades"] == 1 and "eq" in core["all"]["hold"]["2h-8h"] and "coin_flips" not in core
    assert EM.group_dash_view(w.paper(), QUIET, "nope")["group"] == "core"


def test_group_brief_is_money_free_per_family_and_bounded(w):
    rows = EM.features(w.paper(), QUIET, kinds=("ds200",))["rows"]
    br = EM.group_brief(rows, families={"F3_BOS": "F3", "F9_FVG": "F9"})
    assert set(br["families"]) == {"F3", "F9"} and br["families"]["F3"]["trend_stage"] == {
        "막판": {"n": 1, "wr": 0.0, "roe": pytest.approx(-0.08), "small": True}}
    assert '"eq"' not in json.dumps(br) and EM.compact_bytes(br) <= EM.GROUP_BRIEF_MAX_BYTES
    # many trades on many definitions: still under the cap
    many = [{**r, "strategy": f"D{k % 40}", "b": {**r["b"], "weekday": "월화수목금"[k % 5]}}
            for k in range(400) for r in rows[:1]]
    big = EM.group_brief(many, families={f"D{k}": f"F{k}" for k in range(40)}, max_bytes=3_000)
    assert EM.compact_bytes(big) <= 3_000 and big["left_out"]
    assert EM.group_brief([], flip_rows=[])["trades"] == 0


# ------------------------------------------------------------------ C: the group rooms
def test_a_deepseek_room_gets_its_entry_moment_without_money(tmp_path):
    w = V4World(tmp_path)
    w.ds_losses("F3_BOS@15m", 6)
    w.ds_losses("F16_FIB382@15m", 2)                          # another room's
    runner = QueueRunner({"spec_ds_structure": [team_answer("r")], "team_lead": [LEAD]})
    w.tick(runner, QUIET)
    pk = runner.calls[0]["packet"]["group_accounts"]
    em = pk["entry_moment"]
    assert em["trades"] == 6 and set(em["families"]) == {"F3"} and em["families"]["F3"]["n"] == 6
    assert '"eq"' not in json.dumps(em) and "coin_flips" not in em
    assert "시너지" in pk["core_only_note"] and "entry_moment" in pk["core_only_note"]
    assert len(json.dumps(pk, ensure_ascii=False)) < 40_000


def test_the_reel_room_gets_the_reel_next_to_its_5m_flips(tmp_path):
    w = V4World(tmp_path)
    w.ds_losses(f"{REEL_NAME}@5m", 3)
    w.trade("RANDOM_2@5m", 4.0, QUIET - HOUR, context={"ema20_dist_atr": 0.4})
    w.trade("RANDOM_1@15m", 4.0, QUIET - HOUR)                # a core flip: not the reel's comparison
    runner = QueueRunner({"spec_reel_5m": [team_answer("r")], "team_lead": [LEAD]})
    w.tick(runner, QUIET)
    pk = runner.calls[0]["packet"]["group_accounts"]
    em = pk["entry_moment"]
    assert em["trades"] == 3 and em["flip_trades"] == 1 and em["coin_flips"]["trend_stage"]["초입"]["n"] == 1
    assert "families" not in em and '"eq"' not in json.dumps(em)
    assert len(json.dumps(pk, ensure_ascii=False)) < 40_000
