"""The owners' stepped lock (exit "ladderU|<k>", 2026-10-13: 13% -> lock 10%, 20% -> 15%, 25% -> 20%, 30% -> 25% ...), the stop cap and the
coin-flip twin of the owner-exit league."""

from __future__ import annotations

import copy
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_rulex as TR  # noqa: E402  (hand-built paths, the league's replay, synthetic strategies)
from candleague import candidates as C  # noqa: E402
from candleague import exits as X  # noqa: E402
from candleague import league as L  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as R  # noqa: E402
from paperbot.engine import engine_state, restore_engine  # noqa: E402

SIDES = pytest.mark.parametrize("side", [1, -1])


def test_the_lock_levels_are_the_owners_numbers():
    below = [0.0, 0.05, 0.1299, 0.12999999]
    assert all(X.user_lock_for(b) is None for b in below)
    table = [(0.13, 0.10), (0.1999, 0.10), (0.20, 0.15), (0.2499, 0.15), (0.25, 0.20), (0.2999, 0.20), (0.30, 0.25), (0.35, 0.30), (0.50, 0.45)]
    for best, lock in table:
        assert X.user_lock_for(best) == pytest.approx(lock), best
    locks = [X.user_lock_for(b / 1000) for b in range(130, 900)]
    assert locks == sorted(locks)                                        # it only ever tightens


def test_the_exit_name_is_known_with_the_stops_the_study_has_and_reads_in_korean():
    for k in X.STOPS:
        name = f"ladderU|{k:g}"
        assert X.known(name) and X.spec(name)["stop_atr"] == k and X.spec(name)["ladder"] and X.spec(name)["tp_kind"] == X.TP_NONE
    for bad in ("ladderU|5", "ladderU|2.0", "ladderU|", "ladderU", "ladderX|2"):
        assert not X.known(bad), bad
    assert "13%→10%" in X.exit_ko("ladderU|2.5") and "손절 2.5 ATR" in X.exit_ko("ladderU|2.5")
    assert X.EXITS == X.EXITS and "ladderU|2" not in X.BY_NAME           # the 84 rules are the same; the owners' ladder is built on demand
    e = X.make_engine("ladderU|3", {"BTCUSDT": TR.WIDE}, {"BTCUSDT": TR.SP["BTCUSDT"]})
    assert isinstance(e, X.UserLadder) and e.s.tp_mode == "ladder"


def _band_path(lev, side, lo_arm, hi_arm, fall_to=0.0):
    """Flat, a one-minute climb to the middle of the band of best net ROE [lo_arm, hi_arm), five flat minutes, a one-minute fall."""
    fl = TR.fill_of(side)
    top = side * (TR.LD.roe_price(side, fl, lev, 0.5 * (lo_arm + hi_arm), TR.RT) - TR.P0)
    j = TR.J0 + 10
    return (TR.Path().hold(0, 0).bar(j, o=0, c=top, b=top, w=0).hold(j + 1, top, j + 6)
            .bar(j + 6, o=top, c=fall_to, b=top, w=fall_to).hold(j + 7, fall_to), top, j + 6)


BANDS = [(0.13, 0.20, 0.10), (0.20, 0.25, 0.15), (0.25, 0.30, 0.20), (0.30, 0.35, 0.25), (0.40, 0.45, 0.35)]


@SIDES
@pytest.mark.parametrize("lo,hi,lock", BANDS)
def test_the_lock_exits_at_the_owners_locked_net_roe_on_a_hand_path(side, lo, hi, lock):
    a = TR.acct(None, exit_="ladderU|2", role=RX.ROLE_BASE_LIVE)
    lev = TR._probe_leverage(a, side)
    path, top, jx = _band_path(lev, side, lo, hi)
    e = TR.run(a, path, side)
    assert len(e.trades) == 1
    t = e.trades[0]
    assert (t.exit_reason, t.exit_time) == ("LOCK", TR.at(jx) + TR.MIN - 1)
    want = TR.LD.roe_price(side, TR.fill_of(side), lev, lock, TR.RT)
    assert t.lock_roe == pytest.approx(lock) and t.exit_price == pytest.approx(want * (1 - side * TR.SLIP), rel=1e-12)
    assert t.pnl > 0 and t.leverage == lev


@SIDES
def test_below_13_percent_there_is_no_lock_and_the_position_stays_open(side):
    a = TR.acct(None, exit_="ladderU|2", role=RX.ROLE_BASE_LIVE)
    lev = TR._probe_leverage(a, side)
    path, _top, _jx = _band_path(lev, side, 0.07, 0.12)          # best net ROE about 9.5%: no lock yet
    assert not TR.run(a, path, side).trades
    # one band up (the band holds 12.9%?): the rule bot's ladder is armed at 12%, the owners' at 13%
    edge, _t, _j = _band_path(lev, side, 0.120, 0.128)
    assert not TR.run(a, edge, side).trades                                                    # 12.4%: not armed
    assert TR.run(TR.acct(None, exit_="ladder|2", role=RX.ROLE_BASE_LIVE), edge, side).trades  # the rule bot's ladder is armed at 12%


@SIDES
def test_a_restart_in_the_middle_of_a_locked_position_gives_the_same_trade(side):
    a = TR.acct(None, exit_="ladderU|2", role=RX.ROLE_BASE_LIVE)
    lev = TR._probe_leverage(a, side)
    path, _top, _jx = _band_path(lev, side, 0.20, 0.25)
    ref = TR.run(a, path, side)
    assert ref.trades and ref.trades[0].lock_roe == pytest.approx(0.15)
    e = RX.make_engine(a, TR.BR, TR.SP)
    sigs = {TR.C0: [TR.sig(TR.C0, side, aid=a["id"])]}
    restored = False
    for t, bars, fund in path.steps(side):
        if not restored and e.position is not None and e.position.lock_roe is not None:
            snap = json.loads(json.dumps(engine_state(e)))
            e = RX.make_engine(a, TR.BR, TR.SP)
            restore_engine(e, snap)
            restored = True
        for s in e.pending:
            if "ref_price" not in s.meta:
                s.meta["ref_price"] = float(bars["BTCUSDT"].open)
        e.step(bars, fund)
        for s in sigs.pop(t + TR.MIN, []):
            e.submit(copy.deepcopy(s))
        if e.trades:
            break
    assert restored and e.trades
    x, y = ref.trades[0], e.trades[0]
    assert (x.exit_time, x.exit_reason, x.exit_price, x.pnl, x.lock_roe) == (y.exit_time, y.exit_reason, y.exit_price, y.pnl, y.lock_roe)


# ---------------------------------------------------------------- the account lineup: ladder first, stop cap, coin twin
LINEUP = {"enabled": True, "owner_exits": [
    {"suffix": "-ld", "exit": "ladderU", "label_ko": "계단 익절 · 실전 후보"},
    {"suffix": "-ldc", "exit": "ladderU", "coin_of": "-ld", "label_ko": "계단 · 동전 던지기"},
    {"suffix": "-ld2", "exit": "ladderU", "stop_max": 2, "label_ko": "계단 · 손절 최대 2 ATR"},
    {"suffix": "-e", "label_ko": "지금 청산"},
    {"suffix": "-tp10", "exit": "roe10", "stop_max": 2, "label_ko": "고정 +10% (손절 최대 2 ATR)"},
    {"suffix": "-wk", "weekend_off": True, "label_ko": "주말 쉬는 계좌"}]}


def _cands(*picks):
    out = []
    for name, tf, exit_ in picks:
        out.append({"id": f"core-{name}-{tf}-1", "kind": "core", "name": name, "tf": tf,
                    "combo": {k: C._plain(v) for k, v in C.default_combo("core", name).items()}, "exit": exit_, "source": {"rank": 1}})
    return out


def test_ladder_stop_cap_and_coin_twin_accounts():
    cfg = RX.normalize_owner(LINEUP)
    cands = _cands(("S2_ST_ROC", "15m", "tp3R|4"), ("S2_ST_ROC", "30m", "tp3R|2"), ("S2_ST_ROC", "1h", "roe10|2"))
    accts = RX.owner_accounts(cands, cfg)
    by = {a["id"]: a for a in accts}
    wide, narrow, same = "core-S2_ST_ROC-15m-1", "core-S2_ST_ROC-30m-1", "core-S2_ST_ROC-1h-1"
    # a pick with a 4 ATR stop: the ladder on that stop, the ladder on 2 ATR, a coin twin of the first, +10% on 2 ATR
    assert (by[wide + "-ld"]["exit"], by[wide + "-ld2"]["exit"], by[wide + "-tp10"]["exit"], by[wide + "-e"]["exit"]) == \
           ("ladderU|4", "ladderU|2", "roe10|2", "tp3R|4")
    coin = by[wide + "-ldc"]
    assert coin["coin"] is True and coin["of"] == wide + "-ld" and coin["exit"] == "ladderU|4" and coin["role"] == "ldc"
    assert coin["combo"] == by[wide + "-ld"]["combo"] and coin["size"] == 1.0
    # a pick whose stop is already 2 ATR: no second ladder account (it would be the first), no duplicate of its own +10% exit
    assert wide + "-ld2" in by and narrow + "-ld2" not in by and narrow + "-ld" in by and narrow + "-tp10" in by
    assert same + "-tp10" not in by                                       # roe10|2 is that pick's own exit
    assert by[narrow + "-ldc"]["of"] == narrow + "-ld"
    assert all(a["combo"] == next(c for c in cands if c["id"] == a["pick"])["combo"] for a in accts)      # every account has the pick's numbers
    assert by[wide + "-wk"].get("weekend_off") and not by[wide + "-ld"].get("weekend_off")
    assert RX.check(cands, cfg) == []
    # the lineup order is the file's order: the ladder first
    assert [x["suffix"] for x in RX.lineup(accts)][:3] == ["-ld", "-ldc", "-ld2"]


@pytest.mark.parametrize("bad", [
    {"suffix": "-x1", "exit": "ladderU", "coin_of": "-nope", "label_ko": "x"},                    # no such entry
    {"suffix": "-x1", "exit": "ladderU", "stop_max": 5, "label_ko": "x"},                         # not one of the stops
    {"suffix": "-x1", "stop_max": 2, "label_ko": "x"},                                           # a stop cap needs an exit
    {"suffix": "-x1", "exit": "ladderU", "coin_of": "-ldc", "label_ko": "x"},                     # a coin twin of a coin twin
    {"suffix": "-x1", "coin_of": "-ld", "label_ko": "x"},                                        # a coin twin needs an exit
])
def test_a_bad_stop_cap_or_coin_twin_is_refused(bad):
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"].append(bad)
    with pytest.raises(RX.RuleConfigError):
        RX.normalize_owner(doc)


def test_the_coin_twin_takes_one_seeded_side_at_the_ladders_signal_times():
    cfg = RX.normalize_owner(LINEUP)
    accts = RX.owner_accounts(TR._rule_cands("15m", "tp3R|2"), cfg)
    by, notes = RX.chunk_rule(TR.LIB, TR.PS.FrameSource(TR.DATA), accts, TR.TP.SYMS, TR.START, TR.START + TR.DAY, TR.START, TR.StubStrategies())
    sigs = {}
    for close, items in by.items():
        for aid, o in items:
            if isinstance(o, TR.Signal):
                sigs.setdefault((aid, o.symbol, close), []).append(o.side)
    pid = "core-S2-15m-1"
    base = {k[1:]: v for k, v in sigs.items() if k[0] == pid + "-ld"}
    coin = {k[1:]: v for k, v in sigs.items() if k[0] == pid + "-ldc"}
    assert base and set(coin) == set(base) and all(len(v) == 1 for v in coin.values())
    for (sym, close), v in coin.items():
        assert v == [L.flip_side(pid + "-ldc", close)]
    assert {v[0] for v in coin.values()} == {1, -1}
    assert not notes


def test_the_fingerprint_sees_the_ladder_exit_and_the_coin_flag():
    from candleague import runner as RN
    cfg = RX.normalize_owner(LINEUP)
    cands = _cands(("S2_ST_ROC", "15m", "tp3R|4"))
    accts = RX.owner_accounts(cands, cfg)
    fp = RN.fingerprint(accts)
    other = copy.deepcopy(accts)
    for a in other:
        if a["id"].endswith("-ldc"):
            a["coin"] = False
    assert RN.fingerprint(other) != fp
    other = copy.deepcopy(accts)
    for a in other:
        if a["id"].endswith("-ld"):
            a["exit"] = "ladderU|3"
    assert RN.fingerprint(other) != fp


def test_the_owner_candidates_file_is_the_38_picks_plus_eleven_weak_clue_picks():
    base = C.load()
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    assert owner[:len(base)] == base and len(base) == 38 and len(owner) == 49
    weak = owner[len(base):]
    assert all(c["source"]["tier"] == "weak" and c["source"]["passed"] is False and not c["source"]["watch"] for c in weak)
    assert sorted(c["name"] for c in weak) == sorted(["N02_ST_KST", "N12_ICHI_AO", "N07_ICHI_CMO", "N04_ST_KLINGER", "N23_HA_ST", "N21_ST_RSI_ADX",
                                                      "F3_BOS", "F15_ORB", "F4_FAN", "F6_VWAP_FAIL", "F15_LON_BRK"])
    assert not any("test_mean" in c["source"] for c in weak if c["kind"] == "ds")             # no DeepSeek money figure (D11)
    cfg = RX.normalize_owner(LINEUP)
    accts = RX.owner_accounts(owner, cfg)
    assert len({a["id"] for a in accts}) == len(accts) and RX.check(owner, cfg) == []


def test_every_pick_of_the_owner_file_has_numbers_other_than_the_default():
    """The owners asked that every account of the new league run the chosen custom numbers, so none may be the default set."""
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    same = [c["id"] for c in owner if all(C._plain(C.default_combo(c["kind"], c["name"])[k]) == C._plain(v) for k, v in c["combo"].items())]
    assert same == []


def test_the_quick_stop_entry_builds_for_every_owner_pick_and_runs_the_studys_rule():
    """The owners asked for a quick stop when the view breaks: the study's F6 (swing 3, loss of at least 0.5 R) as one more account kind."""
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"].insert(5, {"suffix": "-fq", "rule": "F6.w3.d0.5", "label_ko": "빠른 손절 (관점 무너지면)"})
    cfg = RX.normalize_owner(doc)
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, cfg)
    fq = [a for a in accts if a["role"] == "fq"]
    assert len(fq) == len(owner) and all(a["rule"]["id"] == "F6.w3.d0.5" and a["exit"] == next(c for c in owner if c["id"] == a["pick"])["exit"] for a in fq)
    assert RX.check(owner, cfg) == [] and RX.rule_needs(fq[0]["rule"])["sw"] == [3]


def test_the_rules_file_the_owners_install_builds_the_final_lineup():
    """candleague/data/rules_owner_exits.json is copied to /etc/candleague/rules.json at the install: twenty-six account kinds on the 49 picks."""
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    cfg = RX.normalize_owner(doc)
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, cfg)
    assert doc["enabled"] is True
    assert [e["suffix"] for e in doc["owner_exits"]] == ["-fq", "-nv", "-sw", "-tg", "-iv", "-ot", "-ld", "-ldc", "-fqc", "-ldp", "-ld1", "-ldt", "-ldv", "-fqt",
                                                         "-fqv", "-sb", "-l5", "-l20", "-e", "-tp10", "-gb", "-ma", "-ts", "-ch", "-oc", "-wk", "-fq40", "-fq50", "-ld40", "-ld50"]
    ks = [float(c["exit"].split("|")[1]) for c in owner]
    native = sum(1 for c in owner if RX.native_supported(c))                                  # -fq, -nv, -tg: the 49 picks of the 27 strategies with their own structure (16 from the study's code, 11 from candleague/native_more*.py)
    levels = sum(1 for c in owner if RX.native_levels_supported(c))                          # -iv, -ot: the 13 picks of the 7 strategies with a level and a target
    # 49 picks x 20 kinds that every pick has (+ -ld40 -ld50), 49 x 8 kinds that need the strategy's own structure (-fq -nv -tg -fqc -fqt -fqv, + -fq40 -fq50), 13 x 2 that need its own level and target
    want = 49 * 20 + 8 * native + 2 * levels - sum(1 for k in ks if k <= 2) - sum(1 for k in ks if k <= 1)  # -ldp is -ld when k <= 2; -ld1 is -ld when k <= 1
    assert len(owner) == 49 and native == 49 and levels == 13 and len(accts) == want == 1384
    assert len({a["id"] for a in accts}) == len(accts) and RX.check(owner, cfg) == []
    assert all(a["combo"] == next(c for c in owner if c["id"] == a["pick"])["combo"] for a in accts)
    assert sum(1 for a in accts if a.get("coin")) == 49 + 49 and sum(1 for a in accts if a["role"] == "cand") == 49
    by = {a["id"]: a for a in accts}
    wide = next(c["id"] for c in owner if c["exit"].split("|")[1] == "4")
    assert (by[wide + "-ld"]["exit"], by[wide + "-ldp"]["exit"], by[wide + "-ld1"]["exit"]) == ("ladderU|2", "ladderU|4", "ladderU|1")
    assert by[wide + "-ldc"]["of"] == wide + "-ld"                                      # the coin twin is the primary's
    # the three structure accounts run the owners' ladder with the stop at most 2 ATR, for every pick (none is dropped as a duplicate of -ld)
    for suffix, rule, tight, n in (("-sb", "F1.w3.a", None, 49), ("-tg", "F11.a", 0.5, 49), ("-fq", "F11.a.d0.5", None, 49), ("-nv", "F11.a", None, 49), ("-sw", "F3.a", None, 49)):
        group = [a for a in accts if a["id"].endswith(suffix)]
        assert len(group) == n, suffix
        assert all(a["rule"]["id"] == rule and a.get("tighten") == tight and a["exit"] == by[a["pick"] + "-ld"]["exit"] for a in group), suffix
        if suffix in ("-tg", "-fq", "-nv"):                                  # each strategy's own structure (no shared fallback)
            assert all(RX.native_supported(a) for a in group), suffix
    lu = {x["suffix"]: x for x in RX.lineup(accts)}
    assert "tighten" not in lu["-fq"] and lu["-tg"]["tighten"] == 0.5 and lu["-tg"]["short_ko"] == "손절 좁힘"
    mains = [x["suffix"] for x in RX.lineup(accts) if x["label_ko"].startswith("메인")]
    ctrl = [x["suffix"] for x in RX.lineup(accts) if x["label_ko"].startswith("대조")]
    assert mains == ["-fq", "-nv", "-sw", "-tg", "-iv", "-ot"] and ctrl == ["-ld", "-ldc", "-fqc", "-ldp", "-ld1"]               # the strategy-own structures are the main ones; the old stop is the control
    assert lu["-sb"]["label_ko"].startswith("연구")                                                       # the same swing for every strategy is a research comparison


# ---------------------------------------------------------------- a rule on the owners' ladder: the quick stop and the narrowing stop (owners 2026-10-13)
def _ruled(rule, tighten=None, exit_="ladderU|2"):
    a = TR.acct(rule, exit_=exit_)
    if tighten is not None:
        a["tighten"] = tighten
    return a


def test_a_rule_account_on_the_owners_ladder_is_the_ladder_engine_with_the_rule_step_order():
    e = RX.make_engine(_ruled("F6.w3.d0.5"), TR.BR, TR.SP)
    assert isinstance(e, RX.RuleUserLadder) and isinstance(e, X.UserLadder) and e.rx_rule["id"] == "F6.w3.d0.5" and e.rx_tighten is None
    assert RX.make_engine(_ruled("F1.w3.a", 0.5), TR.BR, TR.SP).rx_tighten == 0.5
    w = _ruled(None)
    w["weekend_off"] = True
    assert isinstance(RX.make_engine(w, TR.BR, TR.SP), RX.RuleUserLadder)          # the weekend gate keeps the owners' ladder


@SIDES
@pytest.mark.parametrize("lo,hi,lock", BANDS)
def test_the_owners_lock_still_works_under_a_rule_that_does_not_fire(side, lo, hi, lock):
    a = _ruled("F6.w3.d0.5")
    lev = TR._probe_leverage(a, side)
    path, _top, jx = _band_path(lev, side, lo, hi)
    e = TR.run(a, path, side)
    assert len(e.trades) == 1 and (e.trades[0].exit_reason, e.trades[0].exit_time) == ("LOCK", TR.at(jx) + TR.MIN - 1)
    assert e.trades[0].lock_roe == pytest.approx(lock)


@SIDES
def test_the_quick_stop_closes_at_the_next_minute_only_below_half_the_stop_distance(side):
    seed = {"ref": TR.P0 - side * 100}
    a = _ruled("F6.w3.d0.5")
    for off, fires in ((-120, False), (-140, True)):                   # both break the reference; only the second is down more than 0.5 R net
        e = TR.run(a, TR.Path(), side, sigs=((TR.C0, TR.sig(TR.C0, side, seed)),), recs=[TR.rec(TR.chk(1), side, off)])
        assert bool(e.trades) is fires
        if fires:
            t = TR.exits_at(e, TR.J0 + 60)
            assert t.exit_price == pytest.approx(TR.P0 * (1 - side * TR.SLIP), rel=1e-12)            # the open of that minute, with slippage
    e = TR.run(a, TR.Path().hold(130, 700), side, sigs=((TR.C0, TR.sig(TR.C0, side, {"ref": TR.P0 + side * 500})),), recs=[TR.rec(TR.chk(1), side, 300)])
    assert not e.trades                                               # in profit, no break: nothing


@SIDES
def test_the_narrowing_stop_halves_the_stop_when_the_structure_breaks_and_holds_it(side):
    seed = {"ref": TR.P0 - side * 100}
    a = _ruled("F1.w3.a", 0.5)
    sigs = ((TR.C0, TR.sig(TR.C0, side, seed)),)
    path = TR.Path().bar(TR.J0 + 80, o=0, c=-250, b=0, w=-250).hold(TR.J0 + 81, -250)
    # no break: the stop stays where the pick put it (2 ATR = 400 away)
    e = TR.run(a, path, side, sigs=sigs, recs=[TR.rec(TR.chk(1), side, 50)])
    assert not e.trades and e.position.stop_price == pytest.approx(TR.P0 - side * TR.R)                 # the fall to -250 stays inside the 400 stop
    # a break at a shallow loss: the stop moves to half the distance from the fill (200), and the fall to -250 is stopped there
    e = TR.run(a, path, side, sigs=sigs, recs=[TR.rec(TR.chk(1), side, -120)])
    assert len(e.trades) == 1
    t = e.trades[0]
    assert t.exit_reason == "SL" and t.exit_time == TR.at(TR.J0 + 80) + TR.MIN - 1
    assert t.exit_price == pytest.approx((TR.P0 - side * 0.5 * TR.R) * (1 - side * TR.SLIP), rel=1e-12) and t.stop_price == pytest.approx(TR.P0 - side * 0.5 * TR.R)


@SIDES
def test_the_narrowing_stop_closes_at_once_when_the_price_is_already_past_the_narrow_stop(side):
    seed = {"ref": TR.P0 - side * 100}
    a = _ruled("F1.w3.a", 0.5)
    sigs = ((TR.C0, TR.sig(TR.C0, side, seed)),)
    path = TR.Path().hold(TR.J0 + 10, -300)                                           # -300 is inside the 2 ATR stop (-400), outside the narrowed one (-200)
    e = TR.run(a, path, side, sigs=sigs, recs=[TR.rec(TR.chk(1), side, -300)])
    t = TR.exits_at(e, TR.J0 + 60, reason="SL")
    assert t.exit_price == pytest.approx((TR.P0 + side * -300) * (1 - side * TR.SLIP), rel=1e-12)           # the open of that minute, with slippage


@SIDES
def test_the_narrowing_never_loosens_a_stop_the_lock_already_moved(side):
    a = _ruled("F1.w3.a", 0.5)
    lev = TR._probe_leverage(a, side)
    path, top, _jx = _band_path(lev, side, 0.13, 0.20)
    path = TR.Path().bar(TR.J0 + 10, o=0, c=top, b=top, w=0).hold(TR.J0 + 11, top)           # climbs to the lock band and stays (no fall)
    e = TR.run(a, path, side, sigs=((TR.C0, TR.sig(TR.C0, side, {"ref": TR.P0 - side * 100})),), recs=[TR.rec(TR.chk(1), side, -500)])
    assert not e.trades or e.trades[0].exit_reason == "LOCK"                                 # the locked stop (+10%) is tighter than the narrow one: it is not moved back
    p = e.position
    if p is not None:
        assert (p.stop_price - (TR.P0 - side * 0.5 * TR.R)) * side > 0 and p.lock_roe == pytest.approx(0.10)


@SIDES
def test_a_restart_with_a_narrowed_stop_gives_the_same_trade(side):
    from paperbot import paramshadow as PS
    seed = {"ref": TR.P0 - side * 100}
    a = _ruled("F1.w3.a", 0.5)
    path = TR.Path().bar(TR.J0 + 80, o=0, c=-250, b=0, w=-250).hold(TR.J0 + 81, -250)
    ref = TR.run(a, path, side, sigs=((TR.C0, TR.sig(TR.C0, side, seed)),), recs=[TR.rec(TR.chk(1), side, -120)])
    assert ref.trades
    steps = path.steps(side)
    cut = TR.at(TR.J0 + 70)                                          # after the narrowing (minute 180), before the stop is hit (minute 200)
    first, rest = [x for x in steps if x[0] < cut], [x for x in steps if x[0] >= cut]
    by = {TR.C0: [(a["id"], TR.sig(TR.C0, side, seed, aid=a["id"]))], TR.chk(1): [(a["id"], RX.RuleClose(TR.rec(TR.chk(1), side, -120)))]}
    e = RX.make_engine(a, TR.BR, TR.SP)
    PS.replay_day({a["id"]: e}, set(), by, first, TR.BR)
    assert e.position is not None and e.position.signal.meta["ctx"].get("rx_narrowed") == 1
    snap = json.loads(json.dumps(engine_state(e)))
    e = RX.make_engine(a, TR.BR, TR.SP)
    restore_engine(e, snap)
    PS.replay_day({a["id"]: e}, {a["id"]}, {}, rest, TR.BR)
    assert e.trades
    x, y = ref.trades[0], e.trades[0]
    assert (x.exit_time, x.exit_reason, x.exit_price, x.pnl) == (y.exit_time, y.exit_reason, y.exit_price, y.pnl)


@pytest.mark.parametrize("bad", [
    {"suffix": "-x1", "exit": "roe10", "rule": "F6.w3.d0.5", "label_ko": "x"},                    # only the owners' ladder takes a rule
    {"suffix": "-x1", "exit": "ladderU", "rule": "F1.w3.b", "label_ko": "x"},                     # mode b has no lock
    {"suffix": "-x1", "exit": "ladderU", "rule": "F13.a", "label_ko": "x"},                       # F13 is another lock
    {"suffix": "-x1", "exit": "ladderU", "rule": "F1.w3.a", "tighten": 0, "label_ko": "x"},
    {"suffix": "-x1", "exit": "ladderU", "rule": "F1.w3.a", "tighten": 1.5, "label_ko": "x"},
    {"suffix": "-x1", "exit": "ladderU", "tighten": 0.5, "label_ko": "x"},                       # narrowing needs a rule
    {"suffix": "-x1", "rule": "F1.w3.a", "tighten": 0.5, "label_ko": "x"},                       # ... on the owners' ladder
    {"suffix": "-x1", "exit": "ladderU", "rule": "F1.w3.a", "coin_of": "-ld", "label_ko": "x"},   # a rule account is not a coin twin
])
def test_a_bad_rule_on_the_ladder_or_narrowing_is_refused(bad):
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"].append(bad)
    with pytest.raises(RX.RuleConfigError):
        RX.normalize_owner(doc)


def test_rule_accounts_on_the_ladder_are_built_for_every_pick_and_the_signals_carry_the_capped_stop():
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"][3:3] = [{"suffix": "-tg", "exit": "ladderU", "stop_max": 2, "rule": "F1.w3.a", "tighten": 0.5, "label_ko": "x"},
                               {"suffix": "-fq", "exit": "ladderU", "stop_max": 2, "rule": "F6.w3.d0.5", "label_ko": "y"}]
    cfg = RX.normalize_owner(doc)
    cands = TR._rule_cands("15m", "tp3R|4")
    accts = RX.owner_accounts(cands, cfg)
    by = {a["id"]: a for a in accts}
    pid = "core-S2-15m-1"
    assert (by[pid + "-tg"]["exit"], by[pid + "-fq"]["exit"], by[pid + "-ld"]["exit"]) == ("ladderU|2", "ladderU|2", "ladderU|4") or by[pid + "-ld"]["exit"] == "ladderU|4"
    assert by[pid + "-tg"]["tighten"] == 0.5 and "tighten" not in by[pid + "-fq"] and by[pid + "-tg"]["ox"]["tighten"] == 0.5
    assert RX.check(cands, cfg) == []
    out, notes = RX.chunk_rule(TR.LIB, TR.PS.FrameSource(TR.DATA), accts, TR.TP.SYMS, TR.START, TR.START + TR.DAY, TR.START, TR.StubStrategies())
    sigs = [(aid, o) for items in out.values() for aid, o in items if isinstance(o, TR.Signal)]
    for sfx in ("-tg", "-fq"):
        mine = [o for aid, o in sigs if aid == pid + sfx]
        assert mine and all(o.meta["stop_dist"] == pytest.approx(2.0 * o.atr) for o in mine)
        assert all("rx0" in o.meta for o in mine)                                              # a rule account gets the rule's seed at its signals
    wide = [o for aid, o in sigs if aid == pid + "-ld"]
    assert wide and all(o.meta["stop_dist"] == pytest.approx(4.0 * o.atr) for o in wide)
    assert not notes


def test_the_fingerprint_sees_the_narrowing():
    from candleague import runner as RN
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"].append({"suffix": "-tg", "exit": "ladderU", "stop_max": 2, "rule": "F1.w3.a", "tighten": 0.5, "label_ko": "x"})
    accts = RX.owner_accounts(_cands(("S2_ST_ROC", "15m", "tp3R|4")), RX.normalize_owner(doc))
    other = copy.deepcopy(accts)
    for a in other:
        if a["id"].endswith("-tg"):
            a["tighten"] = 0.3
    assert RN.fingerprint(other) != RN.fingerprint(accts)


# ---------------------------------------------------------------- the strategy's own judgement (F11) on the owners' ladder
def test_the_native_table_is_the_study_codes_table():
    import importlib
    import sys
    d = RX.native_dir()
    if d not in sys.path:
        sys.path.insert(0, d)
    native, native_ds = importlib.import_module("native"), importlib.import_module("native_ds")
    assert sorted(RX.NATIVE_STUDY["core"]) == sorted(native.SPEC) and sorted(RX.NATIVE_STUDY["ds"]) == sorted(native_ds.NAMES)
    assert set(RX.NATIVE_COVERS["core"]) == set(RX.NATIVE_STUDY["core"]) | set(RX.NATIVE_MORE["core"]) and len(RX.NATIVE_COVERS["core"]) + len(RX.NATIVE_COVERS["ds"]) == 27
    assert not set(RX.NATIVE_MORE["core"]) & set(native.SPEC) and not set(RX.NATIVE_MORE["ds"]) & set(native_ds.NAMES)       # the study's code is not duplicated


def test_the_native_exit_account_is_made_only_for_picks_whose_strategy_has_one():
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    accts = RX.owner_accounts(owner, RX.normalize_owner(doc))
    nv = [a for a in accts if a["role"] == "nv"]
    covered = [c for c in owner if RX.native_supported(c)]
    assert len(nv) == len(covered) == 49 and {a["pick"] for a in nv} == {c["id"] for c in covered}
    assert all(a["rule"]["id"] == "F11.a" and a["exit"].startswith("ladderU|") and float(a["exit"].split("|")[1]) <= 2 for a in nv)
    weak = {c["id"] for c in owner if c["source"].get("tier") == "weak"}
    assert len(weak) == 11 and weak <= {a["pick"] for a in nv}              # the eleven weak-clue picks have the league's own structure (native_more*.py) and so these accounts


def test_f12_and_mode_b_of_f11_are_refused_on_the_ladder():
    for rule in ("F12.a", "F11.b", "F12.b"):
        doc = copy.deepcopy(LINEUP)
        doc["owner_exits"].append({"suffix": "-x1", "exit": "ladderU", "rule": rule, "label_ko": "x"})
        with pytest.raises(RX.RuleConfigError):
            RX.normalize_owner(doc)


@SIDES
def test_the_strategys_own_view_breaking_closes_the_position_on_the_owners_ladder(side):
    k = TR.key_of(side)
    a = TR.acct("F11.a", exit_="ladderU|2")
    assert isinstance(RX.make_engine(a, TR.BR, TR.SP), RX.RuleUserLadder)
    e = TR.run(a, TR.Path(), side, sigs=((TR.C0, TR.nsig(side, ["event"], [0])),),
               recs=[TR.nrec(TR.chk(1), side, 0, **{k: [0]}), TR.nrec(TR.chk(2), side, 0, **{k: [1]})])
    TR.exits_at(e, TR.J0 + 120)                                              # the second hourly check: the strategy's own judgement fires
    # the owners' lock still works under it: a climb into the +20% band and a fall is the locked +15%, not the rule
    lev = TR._probe_leverage(a, side)
    path, _top, jx = _band_path(lev, side, 0.20, 0.25)
    e = TR.run(a, path, side, sigs=((TR.C0, TR.nsig(side, ["event"], [0])),), recs=[TR.nrec(TR.chk(1), side, 0, **{k: [0]})])
    assert e.trades and e.trades[0].exit_reason == "LOCK" and e.trades[0].lock_roe == pytest.approx(0.15)


@SIDES
def test_the_switching_account_closes_on_the_strategys_opposite_signal_and_enters_the_other_way_in_the_same_minute(side):
    from paperbot import paramshadow as PS
    a = TR.acct("F3.a", exit_="ladderU|2")
    e = RX.make_engine(a, TR.BR, TR.SP)
    c1 = TR.chk(1)
    by = {TR.C0: [(a["id"], TR.sig(TR.C0, side, aid=a["id"]))],
          c1: [(a["id"], RX.RuleClose(TR.rec(c1, side, 0, **{("sf" if side > 0 else "lf"): True}))), (a["id"], TR.sig(c1, -side, aid=a["id"]))]}
    PS.replay_day({a["id"]: e}, set(), by, TR.Path().steps(side), TR.BR)
    assert [(t.side, t.exit_reason, t.exit_time) for t in e.trades] == [(side, "RULE", TR.at(TR.J0 + 60))]
    assert e.position is not None and e.position.side == -side and e.position.entry_time == TR.at(TR.J0 + 60)         # switched at that minute
    # no opposite flag: nothing happens, and the signal of the other side that arrives while holding is skipped as ever
    e = RX.make_engine(a, TR.BR, TR.SP)
    PS.replay_day({a["id"]: e}, set(), {TR.C0: by[TR.C0], c1: [by[c1][1]]}, TR.Path().steps(side), TR.BR)
    assert not e.trades and e.position.side == side


# ---------------------------------------------------------------- F11 with a loss condition: the strategy's own structure, only at a net loss deeper than d x R
def test_f11_with_a_loss_depth_is_written_and_read_like_the_studys_ids():
    r = RX.parse_rule("F11.a.d0.5")
    assert r["family"] == "F11" and r["mode"] == "a" and r["d"] == 0.5 and r["id"] == "F11.a.d0.5" and RX.rule_needs(r)["nat"] is True
    assert RX.parse_rule("F11.a")["id"] == "F11.a" and "d" not in RX.parse_rule("F11.a")                     # the study's own ids are as before
    for bad in ("F11.a.d", "F11.a.q15", "F11.a.d-1", "F11.c.d0.5", "F11.a.d0.5.q15"):
        with pytest.raises(RX.RuleConfigError):
            RX.parse_rule(bad)
    assert RX.native_ids() == ["F11.a", "F11.b", "F12.a", "F12.b"] and len(RX.study_ids()) + len(RX.native_ids()) == 86


@SIDES
def test_f11_with_a_loss_depth_fires_only_when_the_strategys_own_view_broke_and_the_loss_is_deep_enough(side):
    k = TR.key_of(side)
    a = TR.acct("F11.a.d0.5", exit_="ladderU|2")
    assert TR.rn(side, -120) > -0.5 > TR.rn(side, -140)                         # the same two depths the F6 test uses
    ev = lambda off, v: TR.nrec(TR.chk(1), side, off, **{k: [v]})              # noqa: E731
    # an event component true at a shallow loss: not enough, the event is gone at the next check
    e = TR.run(a, TR.Path(), side, sigs=((TR.C0, TR.nsig(side, ["event"], [0])),), recs=[ev(-120, 1), TR.nrec(TR.chk(2), side, -150, **{k: [0]})])
    assert not e.trades
    # the same event at a deep loss: closed at the next minute
    e = TR.run(a, TR.Path(), side, sigs=((TR.C0, TR.nsig(side, ["event"], [0])),), recs=[ev(-140, 1)])
    TR.exits_at(e, TR.J0 + 60)
    # a state that stays broken: shallow at the first check (no), deep at the second (yes)
    e = TR.run(a, TR.Path(), side, sigs=((TR.C0, TR.nsig(side, ["state"], [0])),),
               recs=[ev(-120, 1), TR.nrec(TR.chk(2), side, -150, **{k: [1]})])
    TR.exits_at(e, TR.J0 + 120)
    # a deep loss and the view not broken: nothing
    e = TR.run(a, TR.Path(), side, sigs=((TR.C0, TR.nsig(side, ["state"], [0])),), recs=[ev(-300, 0)])
    assert not e.trades
    # without the loss depth the same shallow event closes it (the study's F11.a)
    e = TR.run(TR.acct("F11.a", exit_="ladderU|2"), TR.Path(), side, sigs=((TR.C0, TR.nsig(side, ["event"], [0])),), recs=[ev(-120, 1)])
    TR.exits_at(e, TR.J0 + 60)


@SIDES
def test_the_strategys_own_structure_narrows_the_stop_instead_of_closing(side):
    k = TR.key_of(side)
    a = _ruled("F11.a", 0.5)
    sigs = ((TR.C0, TR.nsig(side, ["event"], [0])),)
    path = TR.Path().bar(TR.J0 + 80, o=0, c=-250, b=0, w=-250).hold(TR.J0 + 81, -250)
    # no break: the stop stays at 2 ATR (400) and the fall to -250 does not reach it
    e = TR.run(a, path, side, sigs=sigs, recs=[TR.nrec(TR.chk(1), side, 0, **{k: [0]})])
    assert not e.trades and e.position.stop_price == pytest.approx(TR.P0 - side * TR.R)
    # the strategy's own view breaks at the first check (any loss): the stop moves to half the distance, and the fall is stopped there
    e = TR.run(a, path, side, sigs=sigs, recs=[TR.nrec(TR.chk(1), side, -50, **{k: [1]})])
    assert len(e.trades) == 1
    t = e.trades[0]
    assert t.exit_reason == "SL" and t.exit_time == TR.at(TR.J0 + 80) + TR.MIN - 1
    assert t.exit_price == pytest.approx((TR.P0 - side * 0.5 * TR.R) * (1 - side * TR.SLIP), rel=1e-12)


# ---------------------------------------------------------------- the first stop at the strategy's own level, and its own target (owners 2026-10-13)
def _own(**flags):
    a = TR.acct(flags.pop("rule", None), exit_="ladderU|2")
    a.update(flags)
    return a


def _entered(a, side, **meta):
    """The position the engine opens for a hand signal carrying ``meta`` (the path stays flat, nothing closes)."""
    s = TR.sig(TR.C0, side, aid=a["id"], **meta)
    e = TR.run(a, TR.Path(), side, sigs=((TR.C0, s),))
    assert e.position is not None
    return e.position


@SIDES
def test_the_own_level_stop_sits_just_beyond_the_level_between_the_floor_and_the_cap(side):
    a = _own(own_stop=True)
    # ATR 200, 2 ATR cap = 400, floor 0.5 ATR = 100, buffer 0.1 ATR = 20
    for level_off, want in ((-300, 320), (-50, 100), (-1000, 400), (-100, 120)):
        p = _entered(a, side, native_inv=TR.P0 + side * level_off)
        assert p.stop_price == pytest.approx(TR.P0 - side * want), level_off
        assert p.signal.meta["ctx"]["stop_src"] == "own" and p.stop_initial == p.stop_price
    for bad in (None, float("nan"), TR.P0 - side * -300 + 0 * side):                              # none, NaN, and a level on the wrong side of the price
        meta = {} if bad is None else {"native_inv": bad}
        if bad is not None and not (bad != bad):
            meta = {"native_inv": TR.P0 - side * -300}                                           # P0 + side * 300: beyond the price in the profit direction
        p = _entered(a, side, **meta)
        assert p.stop_price == pytest.approx(TR.P0 - side * TR.R) and p.signal.meta["ctx"]["stop_src"] == "atr"
    # the plain ladder account of the same signal keeps the 2 ATR stop whatever the level says
    p = _entered(TR.acct(None, exit_="ladderU|2"), side, native_inv=TR.P0 - side * 300)
    assert p.stop_price == pytest.approx(TR.P0 - side * TR.R)


@SIDES
def test_the_own_level_stop_is_the_sizing_input_and_the_trade_closes_there(side):
    a = _own(own_stop=True)
    path = TR.Path().bar(TR.J0 + 30, o=0, c=-340, b=0, w=-340).hold(TR.J0 + 31, -340)
    sigs = ((TR.C0, TR.sig(TR.C0, side, aid=a["id"], native_inv=TR.P0 - side * 300)),)
    e = TR.run(a, path, side, sigs=sigs)
    assert len(e.trades) == 1
    t = e.trades[0]
    assert t.exit_reason == "SL" and t.exit_price == pytest.approx((TR.P0 - side * 320) * (1 - side * TR.SLIP), rel=1e-12)
    # the same fall does not touch the plain account's 400 stop
    assert not TR.run(TR.acct(None, exit_="ladderU|2"), path, side, sigs=((TR.C0, TR.sig(TR.C0, side)),)).trades


@SIDES
def test_the_own_target_is_a_limit_beyond_the_fill_and_the_lock_stays(side):
    a = _own(rule="F11.a", own_target=True)
    p = _entered(a, side, rx0={}, native_tgt=TR.P0 + side * 500, native_s=side)
    assert p.tp_price == pytest.approx(TR.P0 + side * 500)
    p = _entered(a, side, rx0={}, native_tgt=TR.P0 - side * 50, native_s=side)                  # behind the fill: no take-profit
    assert p.tp_price != p.tp_price
    p = _entered(_own(rule="F11.a"), side, rx0={}, native_tgt=TR.P0 + side * 500, native_s=side)  # without the flag the target is not used (F11.a)
    assert p.tp_price != p.tp_price
    # the target is hit: a limit fill (maker) at the target price
    path = TR.Path().bar(TR.J0 + 30, o=0, c=600, b=600, w=0).hold(TR.J0 + 31, 600)
    e = TR.run(a, path, side, sigs=((TR.C0, TR.sig(TR.C0, side, {}, aid=a["id"], native_tgt=TR.P0 + side * 500, native_s=side)),))
    assert e.trades and e.trades[0].exit_reason == "TP" and e.trades[0].exit_price == pytest.approx(TR.P0 + side * 500)
    # a climb into the lock band that falls back first is still the owners' lock
    lev = TR._probe_leverage(a, side)
    path, _top, _jx = _band_path(lev, side, 0.20, 0.25)
    e = TR.run(a, path, side, sigs=((TR.C0, TR.sig(TR.C0, side, {}, aid=a["id"], native_tgt=TR.P0 + side * 5000, native_s=side)),))
    assert e.trades and e.trades[0].exit_reason == "LOCK" and e.trades[0].lock_roe == pytest.approx(0.15)


def test_the_two_kinds_exist_only_for_the_strategies_with_a_level_and_a_target_and_the_table_is_the_study_codes():
    import importlib
    import sys
    d = RX.native_dir()
    if d not in sys.path:
        sys.path.insert(0, d)
    native_ds = importlib.import_module("native_ds")
    assert sorted(RX.NATIVE_LEVELS["ds"]) == sorted(native_ds.LEVEL_STRATEGIES) and set(RX.NATIVE_LEVELS["core"]) <= set(RX.NATIVE_COVERS["core"])
    assert "Only N13_3OUTSIDE and N19_FIB_CHOP have a level; only they have a target" in importlib.import_module("native").__doc__.replace("\n", " ").replace("  ", " ")
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, RX.normalize_owner(doc))
    for role, flag in (("iv", "own_stop"), ("ot", "own_target")):
        group = [a for a in accts if a["role"] == role]
        want = [c for c in owner if RX.native_levels_supported(c)]
        assert len(group) == len(want) == 13 and all(a.get(flag) is True and a["exit"].startswith("ladderU|") for a in group)
        assert {a["pick"] for a in group} == {c["id"] for c in want}
    assert all(a["rule"]["id"] == "F11.a" for a in accts if a["role"] == "ot") and all(a["rule"]["family"] is None for a in accts if a["role"] == "iv")


@pytest.mark.parametrize("bad", [
    {"suffix": "-x1", "exit": "ladderU", "own_stop": True, "rule": "F1.w3.a", "label_ko": "x"},                    # own_stop is not a rule account
    {"suffix": "-x1", "exit": "ladderU", "own_stop": True, "coin_of": "-ld", "label_ko": "x"},
    {"suffix": "-x1", "own_stop": True, "label_ko": "x"},                                                          # needs the owners' ladder
    {"suffix": "-x1", "exit": "ladderU", "own_target": True, "label_ko": "x"},                                     # own_target needs an F11 rule
    {"suffix": "-x1", "exit": "ladderU", "own_target": True, "rule": "F1.w3.a", "label_ko": "x"},
    {"suffix": "-x1", "exit": "ladderU", "own_target": True, "rule": "F11.a", "tighten": 0.5, "label_ko": "x"},
    {"suffix": "-x1", "exit": "ladderU", "own_stop": "yes", "label_ko": "x"},
])
def test_a_bad_own_stop_or_own_target_entry_is_refused(bad):
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"].append(bad)
    with pytest.raises(RX.RuleConfigError):
        RX.normalize_owner(doc)


def test_the_fingerprint_sees_the_own_stop_and_the_own_target():
    from candleague import runner as RN
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"] += [{"suffix": "-iv", "exit": "ladderU", "stop_max": 2, "own_stop": True, "label_ko": "x"},
                           {"suffix": "-ot", "exit": "ladderU", "stop_max": 2, "rule": "F11.a", "own_target": True, "label_ko": "y"}]
    cands = [{**c, "kind": "ds", "name": "F5_BOX", "id": "ds-F5_BOX-4h-1", "combo": {}} for c in _cands(("S2_ST_ROC", "4h", "tp3R|4"))]
    accts = RX.owner_accounts(cands, RX.normalize_owner(doc))
    assert {a["role"] for a in accts} >= {"iv", "ot"}
    base = RN.fingerprint(accts)
    for suffix, flag in (("-iv", "own_stop"), ("-ot", "own_target")):
        other = copy.deepcopy(accts)
        for a in other:
            if a["id"].endswith(suffix):
                a.pop(flag)
        assert RN.fingerprint(other) != base


def test_chunk_rule_hands_the_strategys_own_level_to_an_own_stop_account_without_a_rule():
    saved = RX.NATIVE["provider"]
    try:
        def prov(a, sym, df, close_ms, lo, sh, btc):
            n = len(df)
            return {"comp_long": [], "comp_short": [], "lvl_long": np.full(n, 111.0), "lvl_short": np.full(n, 222.0),
                    "tgt_long": np.full(n, 333.0), "tgt_short": np.full(n, 444.0)}
        RX.register_native(prov)
        doc = copy.deepcopy(LINEUP)
        doc["owner_exits"].append({"suffix": "-iv", "exit": "ladderU", "stop_max": 2, "own_stop": True, "label_ko": "x"})
        cfg = RX.normalize_owner(doc)
        accts = RX.owner_accounts(TR._rule_cands("15m", "tp3R|4"), cfg)
        iv = next(a for a in accts if a["id"].endswith("-iv")) if any(a["id"].endswith("-iv") for a in accts) else None
        assert iv is None                                                       # the stub pick is not one of the seven strategies: no account
        base = next(a for a in accts if a["id"].endswith("-ld"))
        iv = {**base, "id": base["id"][:-3] + "-iv", "role": "iv", "own_stop": True, "exit": "ladderU|2"}
        by, notes = RX.chunk_rule(TR.LIB, TR.PS.FrameSource(TR.DATA), [iv], TR.TP.SYMS, TR.START, TR.START + TR.DAY, TR.START, TR.StubStrategies())
        sigs = [o for items in by.values() for aid, o in items if isinstance(o, TR.Signal)]
        assert sigs and not any(isinstance(o, RX.RuleClose) for items in by.values() for _a, o in items)       # signals only: no rule, no chart records
        for o in sigs:
            want = (111.0, 333.0) if o.side > 0 else (222.0, 444.0)
            assert (o.meta["native_inv"], o.meta["native_tgt"]) == want and o.meta["stop_dist"] == pytest.approx(2.0 * o.atr) and "rx0" not in o.meta
        assert not notes
    finally:
        RX.NATIVE["provider"] = saved


# ---------------------------------------------------------------- the coin twin of a rule account, and the regime gates (owners 2026-10-13)
def test_the_coin_twin_of_the_quick_stop_trades_the_same_rule_on_the_coins_side():
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, RX.normalize_owner(doc))
    by = {a["id"]: a for a in accts}
    twins = [a for a in accts if a["role"] == "fqc"]
    assert len(twins) == 49 and all(a["coin"] is True and a["of"] == a["pick"] + "-fq" for a in twins)
    for a in twins:
        main = by[a["of"]]
        assert a["rule"]["id"] == main["rule"]["id"] == "F11.a.d0.5" and a["exit"] == main["exit"] and a["combo"] == main["combo"]
    assert RX.check(owner, RX.normalize_owner(doc)) == []


def test_chunk_rule_gives_a_coin_twin_of_a_rule_account_the_flipped_side_and_the_rule_seed():
    saved = RX.NATIVE["provider"]
    try:
        n_of = {}

        def prov(a, sym, df, close_ms, lo, sh, btc):
            n = len(df)
            n_of[a["id"]] = n
            return {"comp_long": [("state", np.zeros(n))], "comp_short": [("state", np.zeros(n))], "lvl_long": np.full(n, 90.0), "lvl_short": np.full(n, 110.0),
                    "tgt_long": None, "tgt_short": None}
        RX.register_native(prov)
        doc = copy.deepcopy(LINEUP)
        doc["owner_exits"] += [{"suffix": "-fq", "exit": "ladderU", "stop_max": 2, "rule": "F11.a.d0.5", "label_ko": "x"},
                               {"suffix": "-fqc", "exit": "ladderU", "coin_of": "-fq", "label_ko": "y"}]
        cands = [{**c, "kind": "ds", "name": "F5_BOX", "id": "ds-F5_BOX-15m-1"} for c in TR._rule_cands("15m", "tp3R|4")]
        accts = RX.owner_accounts(cands, RX.normalize_owner(doc))
        fq, fqc = (next(a for a in accts if a["id"].endswith(sfx)) for sfx in ("-fq", "-fqc"))
        by, notes = RX.chunk_rule(TR.LIB, TR.PS.FrameSource(TR.DATA), [fq, fqc], TR.TP.SYMS, TR.START, TR.START + TR.DAY, TR.START, TR.StubStrategies())
        sigs = {aid: [] for aid in (fq["id"], fqc["id"])}
        for close, items in by.items():
            for aid, o in items:
                if isinstance(o, TR.Signal):
                    sigs[aid].append((close, o))
        assert sigs[fq["id"]] and len(sigs[fqc["id"]]) == len(sigs[fq["id"]])
        for (c1, o1), (c2, o2) in zip(sigs[fq["id"]], sigs[fqc["id"]]):
            assert c1 == c2 and o2.side == L.flip_side(fqc["id"], c2) and o1.meta["native_s"] == o2.meta["native_s"] == o1.side
            assert "rx0" in o2.meta and o2.meta["style"] == "rule:F11.a.d0.5"
        assert not notes
    finally:
        RX.NATIVE["provider"] = saved


def test_the_gate_helpers_are_causal_and_fail_closed():
    # g1: a hand BTC 4h chart: rising closes (above the EMA once it is warm), then falling
    n = 120
    c = np.r_[np.linspace(100, 160, 80), np.linspace(160, 90, 40)]
    t = np.arange(n, dtype=np.int64) * RX.TF_MS["4h"] + RX.TF_MS["4h"]                    # bar close times
    ms, sign = RX.gate_g1_arrays(t, c)
    assert (sign[:RX.GATE_EMA] == 0).all() and sign[70] == 1 and sign[-1] == -1
    ok = lambda close_ms, side: RX.gate_g1(ms, sign, close_ms, side)                       # noqa: E731
    assert ok(int(t[70]), 1) and not ok(int(t[70]), -1) and ok(int(t[-1]), -1) and not ok(int(t[-1]), 1)
    assert ok(int(t[70]) + 1, 1) and not ok(int(t[10]), 1) and not ok(int(t[0]) - 1, 1)                # a bar closing later is not known yet; cold EMA and no bar: closed
    # the value at a signal never reads a later bar: changing the future leaves it
    c2 = c.copy()
    c2[75:] = 1.0
    ms2, sign2 = RX.gate_g1_arrays(t, c2)
    assert sign2[74] == sign[74] and RX.gate_g1(ms2, sign2, int(t[74]), 1) == RX.gate_g1(ms, sign, int(t[74]), 1)
    # g2: the percentile of the ATR% inside its last window
    w = RX.GATE_WINDOW
    atr = np.linspace(0.001, 0.01, w + 10)                                                  # rising: the newest value is always the top of its window
    assert not RX.gate_g2(atr, w + 5) and not RX.gate_g2(atr, w - 2)                          # at the top (> 80%), and the window is not full yet
    mid = np.r_[np.linspace(0.001, 0.01, w - 1), [0.0055]]
    assert RX.gate_g2(mid, w - 1) and not RX.gate_g2(np.r_[mid[:-1], [0.0001]], w - 1) and not RX.gate_g2(np.r_[mid[:-1], [np.nan]], w - 1)


@SIDES
def test_a_gate_account_enters_only_when_the_signal_passed_the_gate_and_says_so(side):
    for gate in RX.GATES:
        a = _own(gate=gate)
        # passed: the same entry as the plain account
        s = TR.sig(TR.C0, side, aid=a["id"], gate={"g1": True, "g2": True})
        e = TR.run(a, TR.Path(), side, sigs=((TR.C0, s),))
        assert e.position is not None
        # failed, absent or not known: no entry, a REJECTED outcome with the gate's name
        for meta in ({"g1": False, "g2": False}, {"g1": True, "g2": True} if False else {}, {"g1": None, "g2": None}):
            kw = {"gate": meta} if meta else {}
            e = TR.run(a, TR.Path(), side, sigs=((TR.C0, TR.sig(TR.C0, side, aid=a["id"], **kw)),))
            assert e.position is None and not e.trades
    # only its own gate counts
    a = _own(gate="g2")
    e = TR.run(a, TR.Path(), side, sigs=((TR.C0, TR.sig(TR.C0, side, aid=a["id"], gate={"g1": False, "g2": True})),))
    assert e.position is not None
    # a rule account with a gate (the quick stop's filter) is built with it
    assert RX.make_engine(_ruled("F11.a.d0.5") | {"gate": "g1"}, TR.BR, TR.SP).rx_gate == "g1"
    assert RX.make_engine(_own(gate="g2"), TR.BR, TR.SP).rx_gate == "g2" and getattr(RX.make_engine(_own(), TR.BR, TR.SP), "rx_gate", None) is None


def test_the_gate_kinds_exist_for_the_right_picks_and_the_fingerprint_sees_the_gate():
    from candleague import runner as RN
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, RX.normalize_owner(doc))
    for role, gate, n, rule in (("ldt", "g1", 49, None), ("ldv", "g2", 49, None), ("fqt", "g1", 49, "F11.a.d0.5"), ("fqv", "g2", 49, "F11.a.d0.5")):
        group = [a for a in accts if a["role"] == role]
        assert len(group) == n and all(a["gate"] == gate and a["exit"].startswith("ladderU|") for a in group)
        assert all((a["rule"]["id"] if a["rule"].get("family") else None) == rule for a in group)
    cands = [c for c in owner[:2]]
    small = [a for a in accts if a["pick"] in {c["id"] for c in cands}]
    base = RN.fingerprint(small)
    other = copy.deepcopy(small)
    for a in other:
        if a["role"] == "ldt":
            a["gate"] = "g2"
    assert RN.fingerprint(other) != base


@pytest.mark.parametrize("bad", [
    {"suffix": "-x1", "exit": "ladderU", "gate": "g3", "label_ko": "x"},
    {"suffix": "-x1", "gate": "g1", "label_ko": "x"},                                                 # needs the owners' ladder
    {"suffix": "-x1", "exit": "ladderU", "gate": "g1", "coin_of": "-ld", "label_ko": "x"},
])
def test_a_bad_gate_entry_is_refused(bad):
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"].append(bad)
    with pytest.raises(RX.RuleConfigError):
        RX.normalize_owner(doc)


def test_chunk_rule_stamps_every_gate_account_signal_with_the_two_gate_values():
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"] += [{"suffix": "-ldt", "exit": "ladderU", "stop_max": 2, "gate": "g1", "label_ko": "x"},
                           {"suffix": "-ldv", "exit": "ladderU", "stop_max": 2, "gate": "g2", "label_ko": "y"}]
    accts = [a for a in RX.owner_accounts(TR._rule_cands("15m", "tp3R|4"), RX.normalize_owner(doc)) if a.get("gate")]
    assert [a["gate"] for a in accts] == ["g1", "g2"]
    by, notes = RX.chunk_rule(TR.LIB, TR.PS.FrameSource(TR.DATA), accts, TR.TP.SYMS, TR.START, TR.START + TR.DAY, TR.START, TR.StubStrategies())
    sigs = [(aid, o) for items in by.values() for aid, o in items if isinstance(o, TR.Signal)]
    assert sigs and not notes and not any(isinstance(o, RX.RuleClose) for items in by.values() for _a, o in items)
    for _aid, o in sigs:
        assert set(o.meta["gate"]) == {"g1", "g2"} and all(isinstance(v, bool) for v in o.meta["gate"].values())
    one = {a["id"]: [(o.symbol, o.ts, o.side) for aid, o in sigs if aid == a["id"]] for a in accts}
    assert one[accts[0]["id"]] == one[accts[1]["id"]]                                           # the same signals, whatever the gate


# ---------------------------------------------------------------- review fixes (2026-10-13): lineup order, coin-twin validation, fingerprint, F11 words
def _real_rules():
    return json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))


def _entry(doc, suffix):
    return copy.deepcopy(next(e for e in doc["owner_exits"] if e["suffix"] == suffix))


def test_the_lineup_is_in_the_files_order_not_the_order_kinds_first_appear():
    doc = _real_rules()
    cfg = RX.normalize_owner(doc)
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, cfg)
    want = [e["suffix"] for e in doc["owner_exits"]]
    assert [x["suffix"] for x in RX.lineup(accts)] == want                 # -iv and -ot (only some picks have them) sit after -tg, as in the file
    assert [x["n"] for x in RX.lineup(accts)] == sorted(x["n"] for x in RX.lineup(accts))
    # shuffling the accounts (as a restart or a filter could) does not change the order
    assert [x["suffix"] for x in RX.lineup(list(reversed(accts)))] == want
    # the first pick lacks the own-level kinds: it is exactly the case the old first-appearance order got wrong
    first = [a for a in accts if a["pick"] == owner[0]["id"]]
    assert not any(a["id"].endswith(("-iv", "-ot")) for a in first) and [x["suffix"] for x in RX.lineup(first)] == [s for s in want if s not in ("-iv", "-ot", "-fq", "-nv", "-tg", "-fqc", "-fqt", "-fqv") or any(a["id"].endswith(s) for a in first)]


def test_a_coin_twin_must_follow_its_target_and_cannot_mirror_an_own_stop():
    doc = _real_rules()
    e, ld, ldc = _entry(doc, "-e"), _entry(doc, "-ld"), _entry(doc, "-ldc")
    RX.normalize_owner(dict(doc, owner_exits=[e, ld, ldc]))
    with pytest.raises(RX.RuleConfigError, match="must be listed before"):
        RX.normalize_owner(dict(doc, owner_exits=[e, ldc, ld]))
    iv = _entry(doc, "-iv")
    twin = dict(ldc, suffix="-ivc", coin_of="-iv")
    with pytest.raises(RX.RuleConfigError, match="cannot be a coin twin"):
        RX.normalize_owner(dict(doc, owner_exits=[e, ld, iv, twin]))


def test_a_coin_twin_inherits_the_weekend_switch():
    doc = _real_rules()
    e, ld, ldc = _entry(doc, "-e"), _entry(doc, "-ld"), _entry(doc, "-ldc")
    wk = dict(ld, suffix="-ldw", weekend_off=True)                     # the primary's ladder with no weekend entries, and its coin twin
    wkc = dict(ldc, suffix="-wkc", coin_of="-ldw")
    cfg = RX.normalize_owner(dict(doc, owner_exits=[e, ld, wk, wkc]))
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    by = {a["id"]: a for a in RX.owner_accounts(owner[:1], cfg)}
    pid = owner[0]["id"]
    assert by[pid + "-ldw"].get("weekend_off") and by[pid + "-wkc"].get("weekend_off") and by[pid + "-wkc"].get("coin")


def test_own_level_accounts_carry_the_native_hash_in_the_fingerprint(monkeypatch):
    from candleague import runner as R
    doc = _real_rules()
    cfg = RX.normalize_owner(doc)
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts([c for c in owner if RX.native_levels_supported(c)][:1], cfg)
    assert any(a.get("own_stop") for a in accts) and any(a.get("own_target") for a in accts)
    only = [a for a in accts if a.get("own_stop") or a.get("own_target")]
    monkeypatch.setattr(RX, "native_hash", lambda: "aaaa")
    f1 = R.fingerprint(only)
    monkeypatch.setattr(RX, "native_hash", lambda: "bbbb")
    assert R.fingerprint(only) != f1                                  # a changed native module restarts the league even for accounts without an F11 rule


def test_rule_ko_names_the_loss_depth_of_the_native_quick_stop():
    assert "손실 0.5R 이상" in RX.rule_ko(RX.parse_rule("F11.a.d0.5"))
    assert "손실" not in RX.rule_ko(RX.parse_rule("F11.a"))


@SIDES
@pytest.mark.parametrize("lev", [40, 50])
def test_a_leverage_comparison_account_takes_the_same_trade_at_its_one_leverage(side, lev):
    """The -fq40/-fq50/-ld40/-ld50 accounts: every entry at the one leverage (margin = leverage %), the 15% loss check lifted so the same
    trade is taken, and the same ladder; the quality-rule account's leverage and size differ, the lock net ROE is the same."""
    base = TR.acct(None, exit_="ladderU|2", role=RX.ROLE_BASE_LIVE)
    var = {**base, "id": "tv", "lev": lev}
    for lv in ("normal", "best"):
        e = RX.make_engine(var, TR.BR, TR.SP)
        assert [(t.name, t.margin_frac, t.leverages) for t in e.s.tiers] == [("best", lev / 100, (lev,)), ("normal", lev / 100, (lev,))] and e.s.max_loss_frac == 1.0
    assert TR._probe_leverage(var, side) == lev
    path, top, jx = _band_path(lev, side, 0.13, 0.20)
    e = TR.run(var, path, side)
    t = e.trades[0]
    assert t.leverage == lev and t.exit_reason == "LOCK" and t.lock_roe == pytest.approx(0.10) and t.pnl > 0
    b = TR.run(base, _band_path(TR._probe_leverage(base, side), side, 0.13, 0.20)[0], side).trades[0]
    assert t.lock_roe == b.lock_roe                                                  # the same ladder, whatever the leverage


def test_the_leverage_key_is_checked_and_restarts_the_league():
    base = {"suffix": "-fq40", "exit": "ladderU", "stop_max": 2, "rule": "F11.a.d0.5", "label_ko": "연구 · 빠른 손절을 40배로", "lev": 40}
    assert RX._owner_entry(base, 0)["lev"] == 40
    for bad in (29, 51, 40.5, True, "40"):
        with pytest.raises(RX.RuleConfigError):
            RX._owner_entry({**base, "lev": bad}, 0)
    for extra in ({"coin_of": "-fq"}, {"gate": "g1"}, {"tighten": 0.5}, {"weekend_off": True}, {"size": 0.5}):
        with pytest.raises(RX.RuleConfigError):
            RX._owner_entry({**base, **extra}, 0)
    a = {"id": "a", "kind": "core", "name": "N", "tf": "1h", "combo": {}, "exit": "ladderU|2", "role": "fq40"}
    assert R.fingerprint([a]) != R.fingerprint([{**a, "lev": 40}]) != R.fingerprint([{**a, "lev": 50}])
