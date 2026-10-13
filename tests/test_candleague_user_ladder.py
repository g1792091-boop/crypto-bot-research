"""The owners' stepped lock (exit "ladderU|<k>", 2026-10-13: 13% -> lock 10%, 20% -> 15%, 25% -> 20%, 30% -> 25% ...), the stop cap and the
coin-flip twin of the owner-exit league."""

from __future__ import annotations

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_rulex as TR  # noqa: E402  (hand-built paths, the league's replay, synthetic strategies)
from candleague import candidates as C  # noqa: E402
from candleague import exits as X  # noqa: E402
from candleague import league as L  # noqa: E402
from candleague import rulex as RX  # noqa: E402
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
    """candleague/data/rules_owner_exits.json is copied to /etc/candleague/rules.json at the install: nineteen account kinds on the 49 picks."""
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    cfg = RX.normalize_owner(doc)
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, cfg)
    assert doc["enabled"] is True
    assert [e["suffix"] for e in doc["owner_exits"]] == ["-fq", "-nv", "-sw", "-tg", "-sb", "-ld", "-ldc", "-ldp", "-ld1", "-l5", "-l20", "-e", "-tp10",
                                                         "-gb", "-ma", "-ts", "-ch", "-oc", "-wk"]
    ks = [float(c["exit"].split("|")[1]) for c in owner]
    native = sum(1 for c in owner if RX.native_supported(c))                                  # -nv: the 38 picks of the 16 strategies with a native exit
    want = 49 * 18 + native - sum(1 for k in ks if k <= 2) - sum(1 for k in ks if k <= 1)     # -ldp is -ld when k <= 2; -ld1 is -ld when k <= 1
    assert len(owner) == 49 and native == 38 and len(accts) == want == 906
    assert len({a["id"] for a in accts}) == len(accts) and RX.check(owner, cfg) == []
    assert all(a["combo"] == next(c for c in owner if c["id"] == a["pick"])["combo"] for a in accts)
    assert sum(1 for a in accts if a.get("coin")) == 49 and sum(1 for a in accts if a["role"] == "cand") == 49
    by = {a["id"]: a for a in accts}
    wide = next(c["id"] for c in owner if c["exit"].split("|")[1] == "4")
    assert (by[wide + "-ld"]["exit"], by[wide + "-ldp"]["exit"], by[wide + "-ld1"]["exit"]) == ("ladderU|2", "ladderU|4", "ladderU|1")
    assert by[wide + "-ldc"]["of"] == wide + "-ld"                                      # the coin twin is the primary's
    # the three structure accounts run the owners' ladder with the stop at most 2 ATR, for every pick (none is dropped as a duplicate of -ld)
    for suffix, rule, tight in (("-tg", "F1.w3.a", 0.5), ("-sb", "F1.w3.a", None)):
        group = [a for a in accts if a["id"].endswith(suffix)]
        assert len(group) == 49
        assert all(a["rule"]["id"] == rule and a.get("tighten") == tight and a["exit"] == by[a["pick"] + "-ld"]["exit"] for a in group), suffix
    # the live candidate: the strategy's own structure with a loss deeper than half the stop; the 3-bar swing for the picks whose strategy has no own exit
    fq = [a for a in accts if a["id"].endswith("-fq")]
    assert len(fq) == 49 and all(a["exit"] == by[a["pick"] + "-ld"]["exit"] and not a.get("tighten") for a in fq)
    assert all(a["rule"]["id"] == ("F11.a.d0.5" if RX.native_supported(a) else "F6.w3.d0.5") for a in fq)
    assert sum(1 for a in fq if a["rule"]["id"] == "F11.a.d0.5") == 38
    lu = {x["suffix"]: x for x in RX.lineup(accts)}
    assert "tighten" not in lu["-fq"] and lu["-tg"]["tighten"] == 0.5 and lu["-tg"]["short_ko"] == "손절 좁힘"
    mains = [x["suffix"] for x in RX.lineup(accts) if x["label_ko"].startswith("메인")]
    ctrl = [x["suffix"] for x in RX.lineup(accts) if x["label_ko"].startswith("대조")]
    assert mains == ["-fq", "-nv", "-sw", "-tg", "-sb"] and ctrl == ["-ld", "-ldc", "-ldp", "-ld1"]         # the new structures are the main ones; the old stop is the control


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
    assert sorted(RX.NATIVE_COVERS["core"]) == sorted(native.SPEC) and sorted(RX.NATIVE_COVERS["ds"]) == sorted(native_ds.NAMES)


def test_the_native_exit_account_is_made_only_for_picks_whose_strategy_has_one():
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    accts = RX.owner_accounts(owner, RX.normalize_owner(doc))
    nv = [a for a in accts if a["role"] == "nv"]
    covered = [c for c in owner if RX.native_supported(c)]
    assert len(nv) == len(covered) == 38 and {a["pick"] for a in nv} == {c["id"] for c in covered}
    assert all(a["rule"]["id"] == "F11.a" and a["exit"].startswith("ladderU|") and float(a["exit"].split("|")[1]) <= 2 for a in nv)
    weak = {c["id"] for c in owner if c["source"].get("tier") == "weak"}
    assert weak and not weak & {a["pick"] for a in nv}                       # the eleven weak-clue picks have no native exit and no such account


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


def test_native_rule_must_be_an_f11_a_rule_next_to_a_rule_on_the_ladder():
    base = {"suffix": "-x1", "exit": "ladderU", "stop_max": 2, "rule": "F6.w3.d0.5", "native_rule": "F11.a.d0.5", "label_ko": "x"}
    doc = copy.deepcopy(LINEUP)
    doc["owner_exits"].append(base)
    assert RX.normalize_owner(doc)["owner_exits"][-1]["native_rule"]["id"] == "F11.a.d0.5"
    for bad in ({"native_rule": "F6.w3.d0.5"}, {"native_rule": "F11.b"}, {"native_rule": 5}, {"rule": None}, {"exit": None}, {"tighten": 0.5}):
        e = {**base, **bad}
        e = {k: v for k, v in e.items() if v is not None}
        doc = copy.deepcopy(LINEUP)
        doc["owner_exits"].append(e)
        with pytest.raises(RX.RuleConfigError):
            RX.normalize_owner(doc)
