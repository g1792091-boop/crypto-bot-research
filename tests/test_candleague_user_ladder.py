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
    """candleague/data/rules_owner_exits.json is copied to /etc/candleague/rules.json at the install: ten account kinds on the 49 picks."""
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    cfg = RX.normalize_owner(doc)
    owner = C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))
    accts = RX.owner_accounts(owner, cfg)
    assert doc["enabled"] is True
    assert [e["suffix"] for e in doc["owner_exits"]] == ["-ld", "-ldc", "-ld2", "-e", "-ma", "-tp10", "-gb", "-fq", "-oc", "-wk"]
    assert len(owner) == 49 and len(accts) == 49 * 10 - sum(1 for c in owner if float(c["exit"].split("|")[1]) <= 2) == 478
    assert len({a["id"] for a in accts}) == len(accts) and RX.check(owner, cfg) == []
    assert all(a["combo"] == next(c for c in owner if c["id"] == a["pick"])["combo"] for a in accts)
    assert sum(1 for a in accts if a.get("coin")) == 49 and sum(1 for a in accts if a["role"] == "cand") == 49
