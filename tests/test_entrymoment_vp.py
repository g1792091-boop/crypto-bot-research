"""agents/entrymoment.py 매물대 (owners' request 2026-10-06): the kind of the price level ahead and its ATR distance (the
S/R marks recorded with the signal), the value-area position of the entry (200 complete bars of the trade's timeframe
built from 1m live_bars up to the signal bar only), their place in the briefs, the dashboard's 매물대 view next to the
coin flips and the 5-year entry study A's 매물대 rows (read only). Hand-computed small cases; no look-ahead."""

import json
import os

import numpy as np
import pytest

from paperbot.agents import entrymoment as EM
from paperbot.config import REEL_NAME
from test_agents_v4 import V4World
from test_rooms import DAY, HOUR, MIN, QUIET, S, SPEC, QueueRunner, World, analysis, challenge, kst, rec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M15 = 15 * MIN
T0 = kst(2026, 10, 7, 9, 0)                     # the close of trade A's signal bar (a 15m boundary)
CANDLE_DIMS = ("wick_with", "streak", "body", "wick_against", "close_loc", "pattern")


# ------------------------------------------------------------------ the definitions
def test_the_new_dimensions_and_their_edges():
    assert EM.VP_DIMS == ("sr_ahead", "sr_room", "va_pos") and all(d in EM.DIMS for d in EM.VP_DIMS)
    assert EM.BUCKETS["sr_ahead"] == ("매물대", "스윙", "전일·전주", "라운드", "상위 봉", "unknown")
    assert EM.BUCKETS["sr_room"] == ("바로 앞", "가까움", "보통", "멂", "unknown")
    assert EM.BUCKETS["va_pos"] == ("매물대 위", "70% 구간 안", "매물대 아래", "최다 가격 근처", "unknown")
    assert EM.ROOM_EDGES == (0.5, 1.0, 2.0) and EM.POC_NEAR_ATR == 0.25
    for d in EM.VP_DIMS:
        assert d in EM.HOW_TO_READ
    # every sr.py KIND code has its group; 51-53 (POC, VAH, VAL) are the 매물대
    from paperbot.entry_marks import KIND_KO
    assert set(EM.SR_GROUP_OF_KIND) == set(KIND_KO)
    assert {k for k, g in EM.SR_GROUP_OF_KIND.items() if g == "매물대"} == {51, 52, 53}


def test_the_value_area_constants_are_the_studys():
    try:
        from paperbot.entry_marks import sr_module
        SR = sr_module()
    except Exception as exc:  # noqa: BLE001  (the research module needs its own vendored deps)
        pytest.skip(f"research/entry_study/sr.py not loadable here: {exc}")
    assert (EM.VP_BARS, EM.VP_BINS, EM.VP_SHARE) == (SR.VP_BARS, SR.VP_BINS, SR.VP_SHARE)
    assert SR.FAMILY_NAME[EM.VP_FAMILY] == "volume_profile"


def test_brief_drop_keeps_the_new_three_after_the_candle_details():
    drop = EM.BRIEF_DROP
    assert set(drop) == set(EM.DIMS) - {"strength"}
    for d in EM.VP_DIMS:
        assert all(drop.index(c) < drop.index(d) for c in (*CANDLE_DIMS, "liq", "weekday", "hold", "funding"))
        assert all(drop.index(d) < drop.index(s) for s in EM.STAGE_DIMS + ("volatility",))


# ------------------------------------------------------------------ the level ahead (recorded marks)
@pytest.mark.parametrize("kind,group", [(51, "매물대"), (52, "매물대"), (53, "매물대"), (11, "스윙"), (12, "스윙"),
                                        (21, "전일·전주"), (32, "전일·전주"), (40, "라운드"), (61, "상위 봉"),
                                        (62, "상위 봉"), (0, "unknown"), (99, "unknown"), (51.5, "unknown")])
def test_sr_ahead_groups_the_kind(kind, group):
    assert EM.sr_ahead_bucket({"sr": {"room_kind": kind, "room": 1.0}}) == group


@pytest.mark.parametrize("room,bucket", [(0.0, "바로 앞"), (0.4999, "바로 앞"), (0.5, "가까움"), (0.99, "가까움"),
                                         (1.0, "보통"), (1.999, "보통"), (2.0, "멂"), (10.0, "멂")])
def test_sr_room_edges(room, bucket):
    assert EM.sr_room_bucket({"sr": {"room": room, "room_kind": 40}}) == bucket


def test_missing_or_failed_marks_are_unknown():
    for ctx in ({}, {"sr": None}, {"sr": "x"}, {"sr": {"error": "ValueError: x", "room": 0.2, "room_kind": 51}},
                {"sr": {"room": None, "room_kind": None}}, {"sr": {"room": "x", "room_kind": "y"}},
                {"sr": {"room": float("nan"), "room_kind": True}}, {"sr": {"room": -1.0}}):
        assert EM.sr_buckets({"context": ctx}) == {"sr_ahead": "unknown", "sr_room": "unknown"}, ctx
    assert EM.sr_buckets({"context": "not a dict"}) == {"sr_ahead": "unknown", "sr_room": "unknown"}


# ------------------------------------------------------------------ the value area (hand-computed)
def test_value_area_hand_case_ties_go_up_and_gaps_are_crossed():
    # bins of width 1 over [0, 10]: typical prices 5.0 (v 4), 6.5 (v 3), 4.5 (v 3), 2.5 (v 5), 8.5 (v 1)
    # -> hist [0,0,5,0,3,4,3,0,1,0]; POC = bin 2; 70% of 16 = 11.2: bin 3 (tie 0/0 -> up), 4 (3), 5 (4) -> 12
    h = [10, 6.5, 4.5, 2.5, 8.5]
    l = [0, 6.5, 4.5, 2.5, 8.5]
    c = [5, 6.5, 4.5, 2.5, 8.5]
    v = [4, 3, 3, 5, 1]
    assert EM.value_area(h, l, c, v, bins=10) == pytest.approx((2.5, 6.0, 2.0))


def test_value_area_poc_tie_is_the_lowest_and_an_exhausted_side_is_skipped():
    # tp 1.5 (v 2), 7.5 (v 2), 5.0 (v 1): POC tie -> bin 1; grows up through the empty bins to bin 7 (5 of 5)
    assert EM.value_area([10, 1.5, 7.5], [0, 1.5, 7.5], [5, 1.5, 7.5], [1, 2, 2], bins=10) == pytest.approx(
        (1.5, 8.0, 1.0))
    # POC in the top bin: no bin above, so it grows down: bin 9 (5) + bin 8 (2) = 7 of 8 >= 5.6
    assert EM.value_area([10, 9.5, 8.5], [0, 9.5, 8.5], [0.5, 9.5, 8.5], [1, 5, 2], bins=10) == pytest.approx(
        (9.5, 10.0, 8.0))
    assert EM.value_area([1, 1], [1, 1], [1, 1], [3, 3]) is None             # zero range
    assert EM.value_area([2, 1], [1, 0], [1, 1], [0, float("nan")]) is None    # no volume


def test_value_area_matches_the_study_code_on_random_bars():
    try:
        from paperbot.entry_marks import sr_module
        SR = sr_module()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"research/entry_study/sr.py not loadable here: {exc}")
    rng = np.random.default_rng(7)
    for _ in range(5):
        c = 100 + np.cumsum(rng.normal(0, 0.3, 260))
        h = c + rng.uniform(0, 0.5, 260)
        l = c - rng.uniform(0, 0.5, 260)
        v = rng.uniform(0, 10, 260)
        v[rng.integers(0, 260, 20)] = np.nan
        ref = SR.volume_profile(h, l, c, v, np.array([259]))[0]
        s = slice(260 - EM.VP_BARS, 260)
        assert EM.value_area(h[s], l[s], c[s], v[s]) == pytest.approx(tuple(ref), rel=1e-12)


@pytest.mark.parametrize("close,bucket", [(2.9, "최다 가격 근처"), (3.0, "최다 가격 근처"), (2.0, "최다 가격 근처"),
                                          (3.1, "70% 구간 안"), (6.0, "70% 구간 안"), (6.01, "매물대 위"),
                                          (1.99, "매물대 아래")])
def test_va_pos_buckets(close, bucket):
    # POC 2.5, VAH 6, VAL 2, ATR 2: within 0.5 of the POC is 최다 가격 근처 (it wins over the VAL edge at 2.0)
    assert EM.va_pos_bucket(close, 2.0, (2.5, 6.0, 2.0)) == bucket


def test_va_pos_unknown_without_area_or_atr():
    assert EM.va_pos_bucket(3.0, 2.0, None) == "unknown"
    assert EM.va_pos_bucket(3.0, float("nan"), (2.5, 6.0, 2.0)) == "unknown"
    assert EM.va_pos_bucket(3.0, 0.0, (2.5, 6.0, 2.0)) == "unknown"


def _bars(n, gap_at=None, with_v=True):
    key = np.arange(n, dtype=np.int64) + 1000
    if gap_at is not None:
        key[gap_at:] += 1
    b = {"key": key, "h": np.full(n, 101.0), "l": np.full(n, 99.0), "c": np.full(n, 100.0)}
    if with_v:
        b["v"] = np.ones(n)
    return b


def test_va_at_needs_200_complete_consecutive_bars_ending_at_the_signal_bar():
    assert EM.va_at(_bars(199), 198) is None
    assert EM.va_at(_bars(200), 199) is not None
    assert EM.va_at(_bars(200, gap_at=50), 199) is None                    # a missing bar inside the window
    assert EM.va_at(_bars(260, gap_at=50), 259) is not None                # the gap is older than 200 bars
    assert EM.va_at(_bars(200, with_v=False), 199) is None
    b = _bars(300)
    b["h"][250:] = 500.0                                                   # bars after the signal bar
    b["v"][250:] = 1e9
    assert EM.va_at(b, 249) == EM.va_at(_bars(250), 249)


# ------------------------------------------------------------------ end to end on live_bars (no look-ahead)
def _bar15(t0, o, h, l, c, vol):
    rows = []
    for k in range(15):
        mo = o if k == 0 else (o + c) / 2
        mc = c if k == 14 else (o + c) / 2
        mh, ml = max(mo, mc), min(mo, mc)
        if k == 5:
            ml = l
        if k == 10:
            mh = h
        rows.append((t0 + k * MIN, "BTCUSDT", mo, mh, ml, mc, vol))
    return rows


GREEN = (99.8, 100.5, 99.5, 100.2)
RED = (100.2, 100.5, 99.5, 99.8)


def _fill(world, start, end, vol=1.0):
    """Alternating 15m bars of range 1 (green on the parity of the bar closing at T0, red on the other), every 1m row
    with volume ``vol``."""
    green_par = ((T0 - M15) // M15) % 2
    rows, t = [], start
    while t < end:
        rows += _bar15(t, *(GREEN if (t // M15) % 2 == green_par else RED), vol)
        t += M15
    world.store.conn.executemany("INSERT INTO live_bars (ts, symbol, open, high, low, close, volume, processed_at) "
                                 "VALUES (?,?,?,?,?,?,?,0)", rows)
    world.store.commit()


@pytest.fixture
def vpw(tmp_path):
    w = World(tmp_path)
    _fill(w, T0 - 260 * M15, T0 + 10 * M15)
    # A: a long whose signal bar (green, close 100.2) closes at T0; a 매물대 0.3 ATR ahead
    w.store.trade(f"{S}@15m", rec(S, "15m", 4.0, T0 + 3 * HOUR, context={"sr": {"room": 0.3, "room_kind": 52}}))
    # B: a short on the next bar (red, close 99.8); a round number 1.5 ATR ahead
    w.store.trade(f"{S}@15m", rec(S, "15m", -3.0, T0 + M15 + 3 * HOUR, side=-1,
                                  context={"sr": {"room": 1.5, "room_kind": 40}}))
    # C: a signal bar with only 160 bars before it: no value area yet; no marks recorded
    w.store.trade(f"{S}@15m", rec(S, "15m", 1.0, T0 - 100 * M15 + 3 * HOUR))
    w.store.commit()
    return w


def test_the_value_area_of_alternating_bars_by_hand(vpw):
    # 200 bars = 100 green (tp 100.0667) + 100 red (tp 99.9333) of equal volume over [99.5, 100.5]: bins of 0.02,
    # green in bin 28, red in bin 21 -> POC tie -> bin 21 = 99.93; 50% there, grows up to bin 28: VAL 99.92, VAH 100.08
    t, o, h, l, c, v = EM.load_live_bars(vpw.paper(), ["BTCUSDT"], 0, T0 + DAY, volume=True)["BTCUSDT"]
    b = EM.resample(t, o, h, l, c, M15, v=v)
    i = int(np.searchsorted(b["key"], T0 // M15 - 1))
    assert b["v"][i] == pytest.approx(15.0)
    assert EM.va_at(b, i) == pytest.approx((99.93, 100.08, 99.92))


def test_features_give_each_trade_its_level_ahead_and_value_area(vpw):
    feat = EM.features(vpw.paper(), T0 + DAY)
    by = {r["roe"]: r["b"] for r in feat["rows"]}
    a, b_, c = by[4.0 / 50], by[-3.0 / 50], by[1.0 / 50]
    # A: close 100.2 > VAH 100.08 and 0.27 from the POC (ATR 1: more than 0.25) -> 매물대 위
    assert (a["sr_ahead"], a["sr_room"], a["va_pos"]) == ("매물대", "바로 앞", "매물대 위")
    # B: close 99.8, 0.13 from the POC 99.93 -> 최다 가격 근처 (a price position: the short's side does not matter)
    assert (b_["sr_ahead"], b_["sr_room"], b_["va_pos"]) == ("라운드", "보통", "최다 가격 근처")
    assert (c["sr_ahead"], c["sr_room"], c["va_pos"]) == ("unknown", "unknown", "unknown")
    assert feat["coverage"]["sr"] == 2 and feat["coverage"]["va"] == 2


def test_no_look_ahead_garbage_after_the_signal_bar_changes_nothing(vpw):
    before = EM.features(vpw.paper(), T0 + DAY)["rows"]
    vpw.store.conn.execute("UPDATE live_bars SET open = open * 3, high = high * 5, low = low / 2, close = close * 4, "
                           "volume = 1e9 WHERE ts >= ?", (T0,))
    vpw.store.commit()
    after = EM.features(vpw.paper(), T0 + DAY)["rows"]
    a0 = next(r for r in before if r["roe"] > 0.05)["b"]
    a1 = next(r for r in after if r["roe"] > 0.05)["b"]
    assert a1 == a0                                                        # trade A: every dimension, va_pos too


def test_a_missing_minute_inside_the_window_is_unknown_never_a_guess(vpw):
    vpw.store.conn.execute("DELETE FROM live_bars WHERE ts = ?", (T0 - 50 * M15 + 3 * MIN,))   # one bar incomplete
    vpw.store.commit()
    rows = EM.features(vpw.paper(), T0 + DAY)["rows"]
    assert {r["b"]["va_pos"] for r in rows} == {"unknown"}
    assert {r["b"]["sr_ahead"] for r in rows} == {"매물대", "라운드", "unknown"}     # the recorded marks still read


def test_bars_without_a_readable_volume_still_give_the_other_dimensions(vpw, monkeypatch):
    real = EM.load_live_bars
    monkeypatch.setattr(EM, "load_live_bars", lambda *a, volume=False, **k: {} if volume else real(*a, **k))
    rows = EM.features(vpw.paper(), T0 + DAY)["rows"]
    assert {r["b"]["va_pos"] for r in rows} == {"unknown"} and all(r["b"]["body"] != "unknown" for r in rows)


def test_no_volume_recorded_is_unknown(tmp_path):
    w = World(tmp_path)
    _fill(w, T0 - 260 * M15, T0 + 10 * M15, vol=None)
    w.store.trade(f"{S}@15m", rec(S, "15m", 4.0, T0 + 3 * HOUR))
    w.store.commit()
    b = EM.features(w.paper(), T0 + DAY)["rows"][0]["b"]
    assert b["va_pos"] == "unknown" and b["body"] != "unknown"           # the candle still reads the bars


# ------------------------------------------------------------------ the briefs
def _spread_rows(n=600, defs=7):
    rows = []
    for k in range(n):
        b = {d: EM.BUCKETS[d][(k * (i + 1) + k // 7) % len(EM.BUCKETS[d])] for i, d in enumerate(EM.DIMS)}
        rows.append({"kind": "strategy", "strategy": f"D{k % defs}", "timeframe": "15m", "symbol": "BTCUSDT",
                     "side": 1 if k % 3 else -1, "pnl": (k % 5) - 2.0, "roe": ((k % 5) - 2.0) / 50, "eq": None, "b": b})
    return rows


def test_a_specialist_brief_drops_candle_details_before_the_matmuldae_three():
    rows = _spread_rows()
    for cap in range(1_000, 2_401, 50):
        br = EM.strategy_brief_from({"rows": rows}, "D0", max_bytes=cap)
        assert EM.compact_bytes(br) <= cap
        left = br.get("left_out") or []
        if any(d in left for d in EM.VP_DIMS):
            assert all(c in left for c in CANDLE_DIMS + ("liq",)), (cap, left)
    br = EM.strategy_brief_from({"rows": rows}, "D0")
    assert "sr_room" in br["buckets"] and "va_pos" in br["buckets"] and "weekday" in br["left_out"]


def test_a_specialist_sees_the_new_dimensions_in_its_room(tmp_path):
    w = World(tmp_path)
    for k in range(7):
        w.trade(f"{S}@15m", 3.0, QUIET - 2 * DAY + k * HOUR, context={"sr": {"room": 0.2, "room_kind": 51}})
    w.losses()
    runner = QueueRunner({SPEC: [analysis("메모")], "devils_advocate": [challenge("agree")]})
    from test_new_meetings import tpol
    from paperbot.agents import rooms as RM
    w.tick(runner, QUIET, policy=RM.RoomsPolicy(triggers=tpol(enabled=("loss_cluster",))))
    em = runner.calls[0]["packet"]["specialist"]["entry_moment"]
    assert em["buckets"]["sr_ahead"]["매물대"]["n"] == 7 and em["buckets"]["sr_room"]["바로 앞"]["n"] == 7
    assert EM.compact_bytes(em) < EM.BRIEF_MAX_BYTES
    assert "sr_ahead" in runner.calls[0]["system"] and "va_pos" in runner.calls[0]["system"]


def test_the_prompts_explain_the_new_dimensions():
    for name in ("rooms_specialist.md", "rooms_meeting_coin.md", "rooms_team.md"):
        with open(os.path.join(ROOT, "paperbot", "agents", "prompts3", name), encoding="utf-8") as fh:
            txt = fh.read()
        assert "sr_ahead" in txt and "sr_room" in txt and "va_pos" in txt and "매물대" in txt, name
        assert "5년" in txt, name


# ------------------------------------------------------------------ the 매물대 view (hand-computed)
def _row(strategy, side, roe, ahead, room, va):
    return {"kind": "strategy", "strategy": strategy, "timeframe": "15m", "symbol": "BTCUSDT", "side": side,
            "pnl": roe * 50, "roe": roe, "eq": roe / 100, "b": {"sr_ahead": ahead, "sr_room": room, "va_pos": va}}


ROWS = [_row("A", 1, 0.10, "매물대", "바로 앞", "매물대 위"),
        _row("A", -1, -0.05, "매물대", "가까움", "70% 구간 안"),
        _row("B", 1, -0.02, "스윙", "바로 앞", "최다 가격 근처"),
        _row("B", 1, 0.04, "매물대", "바로 앞", "unknown"),
        _row("C", -1, -0.08, "unknown", "unknown", "매물대 아래")]
FLIPS = [_row("RANDOM_1", 1, -0.06, "매물대", "바로 앞", "매물대 위"),
         _row("RANDOM_2", -1, 0.02, "라운드", "멂", "70% 구간 안")]


def test_vp_from_by_hand():
    v = EM.vp_from(ROWS, FLIPS, "core", names_ko={"A": "에이"})
    m, f = v["mine"], v["coin_flips"]
    assert v["trades"] == 5 and v["flip_trades"] == 2 and v["all"]["n"] == 5
    assert list(m["buckets"]["sr_ahead"]) == ["매물대", "스윙", "unknown"]
    assert m["buckets"]["sr_ahead"]["매물대"] == {"n": 3, "wr": 0.667, "roe": pytest.approx(0.03), "small": True}
    assert m["under_vp"] == {"바로 앞": {"n": 2, "wr": 1.0, "roe": pytest.approx(0.07), "small": True},
                             "가까움": {"n": 1, "wr": 0.0, "roe": pytest.approx(-0.05), "small": True}}
    assert set(m["va_long"]) == {"매물대 위", "최다 가격 근처", "unknown"}
    assert set(m["va_short"]) == {"70% 구간 안", "매물대 아래"}
    assert f["buckets"]["sr_ahead"] == {"매물대": {"n": 1, "wr": 0.0, "roe": pytest.approx(-0.06), "small": True},
                                        "라운드": {"n": 1, "wr": 1.0, "roe": pytest.approx(0.02), "small": True}}
    ru = v["right_under"]
    # A: 1 of its 2 trades (+10%), B: 1 of 2 (+4%): the same count, the worse ROE first
    assert [(x["strategy"], x["n"], x["share"], x["strategy_n"]) for x in ru["rows"]] == [
        ("B", 1, 0.5, 2), ("A", 1, 0.5, 2)]
    assert ru["rows"][1]["name_ko"] == "에이" and ru["rows"][0]["strategy_roe"] == pytest.approx(0.01)
    assert ru["total"] == 2 and ru["all"]["n"] == 2 and ru["coin_flips"] == {
        "n": 1, "wr": 0.0, "roe": pytest.approx(-0.06), "small": True}
    # buckets compared (unknown left out): 2 + 2 + 4 in the three dimensions, 2 by distance, 2 long, 2 short
    assert v["multiple_comparisons"]["buckets_examined"] == 14
    assert v["multiple_comparisons"]["buckets_not_small"] == 0
    assert EM.vp_from(ROWS, FLIPS, min_n=1)["multiple_comparisons"]["buckets_not_small"] == 14
    s = json.dumps(v, ensure_ascii=False)
    assert '"eq"' not in s and '"pnl"' not in s and "no_money" not in v
    assert v["how_to_read"] == EM.VP_READ and "가설" in v["note"]


def test_vp_from_deepseek_is_marked_and_an_empty_group_says_so():
    assert EM.vp_from(ROWS, FLIPS, "ds200")["no_money"] is True
    e = EM.vp_from([], [], "reel")
    assert e["trades"] == 0 and e["note"] and "mine" not in e and e["group_label"] == EM.GROUP_LABEL_KO["reel"]


# ------------------------------------------------------------------ the 5-year study (read only)
def _desc(tmp_path, d15, r15, d1h):
    """sr_descriptive.json with the 매물대 line ``diff`` above / below each period's mean (-5%)."""
    def block(diff):
        return {"n_trades": 100, "mean_roe": -0.05,
                "room_type": [{"value": 1, "n": 60, "share": 0.6, "mean_roe": -0.05, "se_roe": 0.01},
                              {"value": 5, "n": 10, "share": 0.1, "mean_roe": -0.05 + diff, "se_roe": 0.01}]}
    by = {"15m": {str(p + 1): {"strategies_pooled": block(d15[p]), "random_null": block(r15[p])} for p in range(3)},
          "1h": {str(p + 1): {"strategies_pooled": block(d1h[p]), "random_null": block(d1h[p])} for p in range(3)}}
    path = tmp_path / "desc.json"
    path.write_text(json.dumps({"by_tf_period": by}), encoding="utf-8")
    return str(path)


def test_vp_study_by_hand(tmp_path):
    desc = _desc(tmp_path, (0.01, 0.002, 0.005), (0.01, -0.003, 0.004), (0.01, -0.01, 0.02))
    cand = tmp_path / "cand.json"
    cand.write_text(json.dumps({"trials": 10, "candidates": [
        {"test": "P1", "random_same_effect_p1": True, "mean0_p1": -0.03, "mean0_p2": -0.02, "mean0_p3": -0.04},
        {"test": "P1", "random_same_effect_p1": False, "mean0_p1": -0.01, "mean0_p2": 0.005, "mean0_p3": -0.02}]}),
        encoding="utf-8")
    s = EM.vp_study_5y(("15m", "1h", "4h"), desc, str(cand), str(tmp_path / "no_official.json"))
    assert s["available"] and s["tfs"] == ["15m", "1h"]                     # no 4h in the file: left out
    r15 = s["rows"][0]
    assert r15["same_sign_3"] is True and r15["random_same_sign_3"] is False
    p1 = r15["periods"][0]["strategies"]
    assert p1 == {"n": 10, "share": 0.1, "roe": -0.04, "se": 0.01, "all_n": 100, "all_roe": -0.05, "diff": 0.01}
    assert s["same_sign_3"] == 1 and s["random_same_sign_3"] == 0 and "매매법 1/2, 무작위 진입 0/2" in s["headline_ko"]
    c = s["candidates"]
    assert (c["tests"], c["candidates"], c["market_wide"], c["p2_candidates"]) == (10, 2, 1, 0)
    assert c["kept_side_roe_max"] == 0.005
    assert "후보 2개 중 1개" in s["verdict_ko"] and "모두 시장 전체" not in s["verdict_ko"]
    assert "손실입니다" not in s["verdict_ko"]                              # one kept side above 0: not said
    # one candidate is not market-wide: 'no edge found' is not said either, and no official run was read
    assert "찾지 못했습니다" not in s["verdict_ko"] and "가설" in s["verdict_ko"]
    assert s["official"] is None and s["same_conclusion"] is False and "사전 등록한 원래" not in s["verdict_ko"]


def _cand(path, trials, cands):
    path.write_text(json.dumps({"trials": trials, "candidates": cands}), encoding="utf-8")
    return str(path)


def test_vp_study_names_the_preregistered_run_and_the_rerun(tmp_path):
    desc = _desc(tmp_path, (0.01,) * 3, (0.01,) * 3, (0.01,) * 3)
    mw = {"test": "P1", "random_same_effect_p1": True, "mean0_p1": -0.03, "mean0_p2": -0.02, "mean0_p3": -0.04}
    rerun = _cand(tmp_path / "rerun.json", 12, [mw, mw, mw])
    official = _cand(tmp_path / "official.json", 10, [mw, {**mw, "mean0_p2": -0.05}])
    s = EM.vp_study_5y(("15m",), desc, rerun, official)
    v = s["verdict_ko"]
    assert s["official"]["tests"] == 10 and s["official"]["candidates"] == 2 and s["same_conclusion"] is True
    # each run with its own counts: the table's numbers are the re-run's, the document's the pre-registered run's
    assert "찾지 못했습니다" in v and "사전 등록한 원래 결과(검정 10개)에서는 세 기간을 통과한 후보 2개 중 2개" in v
    assert "다시 돌린 결과(검정 12개, 아래 표의 숫자)에서는 후보 3개 중 3개" in v and "−4.0% ~ −2.0%로 손실" in v
    # the official run with a candidate the random entries did not share: 'no edge found' is not said
    official2 = _cand(tmp_path / "official2.json", 10, [mw, {**mw, "random_same_effect_p1": False}])
    s = EM.vp_study_5y(("15m",), desc, rerun, official2)
    assert s["same_conclusion"] is False and "찾지 못했습니다" not in s["verdict_ko"]
    # a read file with no candidate is not 'could not read the file'
    s = EM.vp_study_5y(("15m",), desc, _cand(tmp_path / "zero.json", 12, []), official)
    assert "후보는 0개" in s["verdict_ko"] and "읽지 못함" not in s["verdict_ko"]
    assert "검정 10개, 후보 2개" in s["verdict_ko"]


def test_vp_study_missing_files(tmp_path):
    assert EM.vp_study_5y(desc_path=str(tmp_path / "nope.json"))["available"] is False
    desc = _desc(tmp_path, (0.01,) * 3, (0.01,) * 3, (0.01,) * 3)
    s = EM.vp_study_5y(("15m",), desc, str(tmp_path / "nope.json"), str(tmp_path / "nope2.json"))
    assert s["available"] and s["candidates"] is None and "설명용" in s["verdict_ko"]
    assert s["official"] is None and s["same_conclusion"] is False


def test_vp_study_reads_the_committed_files_honestly():
    s = EM.vp_study_5y()
    assert s["available"] and s["tfs"] == ["15m", "30m", "1h", "4h"]
    with open(EM.STUDY_DESC, encoding="utf-8") as fh:
        raw = json.load(fh)["by_tf_period"]["15m"]["1"]["strategies_pooled"]
    vp = next(r for r in raw["room_type"] if r["value"] == 5)
    got = s["rows"][0]["periods"][0]["strategies"]
    assert got["n"] == vp["n"] and got["roe"] == round(vp["mean_roe"], 4) and got["all_n"] == raw["n_trades"]
    # the plain lines come from the files' own counts: no timeframe is consistent, every candidate is market-wide
    assert s["same_sign_3"] == sum(r["same_sign_3"] for r in s["rows"])
    c = s["candidates"]
    assert c["candidates"] >= 1 and c["market_wide"] == c["candidates"] and c["kept_side_roe_max"] < 0
    assert "찾지 못했습니다" in s["verdict_ko"] and "설명용" in s["verdict_ko"]
    # the pre-registered run (RESULTS_ENTRY_A.md: 290 tests, 2 candidates) is named with its own counts, never the
    # re-run's 292 / 3 under the 'pre-registered' label
    with open(EM.STUDY_OFFICIAL_CAND, encoding="utf-8") as fh:
        off = json.load(fh)
    o = s["official"]
    assert (o["tests"], o["candidates"]) == (off["trials"], len(off["candidates"])) and o["market_wide"] == o["candidates"]
    assert f"사전 등록한 원래 결과(검정 {o['tests']}개)" in s["verdict_ko"] and s["same_conclusion"] is True
    with open(EM.STUDY_CAND, encoding="utf-8") as fh:
        assert f"다시 돌린 결과(검정 {json.load(fh)['trials']}개" in s["verdict_ko"]
    assert EM.vp_study_5y(("5m",))["tfs"] == ["5m"]


def test_the_study_files_are_only_read(tmp_path):
    before = {p: open(p, "rb").read() for p in (EM.STUDY_DESC, EM.STUDY_CAND, EM.STUDY_OFFICIAL_CAND)}
    EM._STUDY_CACHE.clear()
    EM.vp_study_5y()
    assert {p: open(p, "rb").read() for p in before} == before


# ------------------------------------------------------------------ the dashboard route
def test_the_vp_route_per_group(tmp_path):
    pytest.importorskip("fastapi")
    import time
    from test_dash_analysis import _client, _login
    w = V4World(tmp_path)
    t = int(time.time() * 1000) - 2 * HOUR
    mk = {"sr": {"room": 0.3, "room_kind": 51}}
    w.trade(f"{S}@15m", 5.0, t, context=mk)
    w.trade("RANDOM_1@15m", -2.0, t, context=mk)
    w.trade("F3_BOS@15m", -4.0, t, side=-1, context={"sr": {"room": 2.5, "room_kind": 61}})
    w.trade(f"{REEL_NAME}@5m", 2.0, t, context={"sr": {"room": 0.7, "room_kind": 11}})
    w.trade("RANDOM_3@5m", -2.0, t, context={"sr": {"room": 0.1, "room_kind": 53}})
    c = _client(w.paths["paper"], failalert_dir=str(tmp_path / "failalert"))
    _login(c)
    core = c.get("/api/analysis/vp").json()
    assert core["group"] == "core" and core["trades"] == 1 and core["flip_trades"] == 1
    assert core["mine"]["buckets"]["sr_ahead"]["매물대"]["n"] == 1 and core["right_under"]["coin_flips"]["n"] == 1
    assert core["study_5y"]["tfs"] == ["15m", "30m", "1h", "4h"] and core == c.get("/api/analysis/vp?group=core").json()
    ds = c.get("/api/analysis/vp?group=ds200")
    assert ds.status_code == 200 and ds.json()["no_money"] is True and ds.json()["trades"] == 1
    assert '"eq"' not in ds.text and '"pnl"' not in ds.text
    assert ds.json()["mine"]["buckets"]["sr_room"] == {"멂": {"n": 1, "wr": 0.0, "roe": pytest.approx(-0.08), "small": True}}
    reel = c.get("/api/analysis/vp?group=reel").json()
    assert reel["trades"] == 1 and reel["flip_trades"] == 1 and reel["study_5y"]["tfs"] == ["5m"]
    assert reel["coin_flips"]["buckets"]["sr_ahead"] == {"매물대": {"n": 1, "wr": 0.0, "roe": pytest.approx(-0.04),
                                                                    "small": True}}
    assert c.get("/api/analysis/vp?group=all").status_code == 400


def test_the_dashboard_files_name_the_view_and_the_dimensions():
    def read(rel):
        with open(os.path.join(ROOT, "paperbot", "dash", "static", "v4", rel), encoding="utf-8") as fh:
            return fh.read()
    an, where, vp = read("screens/analysis.js"), read("screens/analysis-where.js"), read("screens/analysis-vp.js")
    assert '{id: "vp", label: "매물대", path: "/api/analysis/vp", render: VP.vp, groups: "groups"' in an
    for k in ("sr_ahead", "sr_room", "va_pos", "cov.va"):
        assert k in where
    assert "d.study_5y" in vp and "s.verdict_ko" in vp and "W.flips" in vp and "va_long" in vp
    assert "innerHTML" not in vp and "toLocaleString" not in vp
    assert "/api/analysis/vp" in read("INVENTORY.md") and "analysis-vp.js" in read("INVENTORY.md")
