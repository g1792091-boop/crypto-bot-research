"""candleague owner-exit league (owners 2026-10-12: "규칙봇은 그대로 두고 커스텀값봇들을 익절기준이랑 손절기준을 좀 바꾸고 싶어서").

The rules file's second form, ``{"enabled": true, "owner_exits": [...]}`` (candleague/rulex.py ``normalize_owner``, ``owner_accounts``):
per pick its current exit (``-e``) and, on the same signals, 이동평균 이탈 (``-ma``, F2.n50.b), 고정 익절 ROE 50% (``-tp50``, "roe50|<k>",
none for a pick whose own exit is already that), 큰 수익 반납 보호 (``-gb``, F5.P1.g50.a) and 주말 쉬는 계좌 (``-wk``: the current
exit, no new entry from a signal bar closing Saturday 00:00 to Monday 00:00 UTC). Tested here:
  * the config: the account list on the real 38 picks, ids, roles, sizes, exits, the duplicate roe50 skip, the refusals, the
    fingerprint, the file switch (no file / not enabled / the study's own form still as before);
  * the weekend gate at the window's edges on the engine (and an open position managed through the weekend);
  * the roe50 take-profit price (the engine's net-ROE price at the fill and the leverage) and its exit;
  * the league end to end on synthetic bars: every kind exits as it should, the weekend account has no weekend entry while the
    current-exit account does and is its exact twin before the weekend, a stop and restart at awkward times gives the same trades,
    a restart in the middle of an open F2 / F5 position restores its rule state (and a damaged one is corrected from the bars);
  * the snapshot (lineup, judge "na", the watch summary without WATCH_PREREG checkpoints, hold hours), Telegram (the owners'
    words, the leaders per pick) and the DeepSeek money rules (nothing loosened: hidden stays hidden everywhere);
  * the dashboard (node, the DOM stand-in of test_candleague_rank_ui): 5계좌 비교 grouped per pick with the owners' labels, 요약,
    점검 진행 and 순위표 in the owner-exit league, DeepSeek money hidden, and the labels back to the five usual accounts after it."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from candleague import candidates as C  # noqa: E402
from candleague import dash as D  # noqa: E402
from candleague import exits as X  # noqa: E402
from candleague import notify as N  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague import summary as SM  # noqa: E402
from paperbot import paramshadow as PS  # noqa: E402
from paperbot import sweepsig  # noqa: E402
from paperbot.models import Bar, Signal  # noqa: E402
from paperbot.sizing import tp_from_roe  # noqa: E402

import test_candleague_rank_ui as RANK  # noqa: E402  (the DOM stand-in)
import test_candleague_rulex as RT  # noqa: E402  (hand-built bars, brackets, the rule account helpers)
import test_paramshadow as TP  # noqa: E402  (synthetic 5m bars, 1m steps)

MIN, DAY = 60_000, 86_400_000
OWNER = {"enabled": True, "owner_exits": [
    {"suffix": "-e", "label_ko": "지금 청산"},
    {"suffix": "-ma", "rule": "F2.n50.b", "label_ko": "이동평균 이탈"},
    {"suffix": "-tp50", "exit": "roe50", "label_ko": "고정 익절 ROE 50%"},
    {"suffix": "-gb", "rule": "F5.P1.g50.a", "label_ko": "큰 수익 반납 보호"},
    {"suffix": "-wk", "weekend_off": True, "label_ko": "주말 쉬는 계좌"}]}
LABELS = ("지금 청산", "이동평균 이탈", "고정 익절 ROE 50%", "큰 수익 반납 보호", "주말 쉬는 계좌")
SUFFIXES = ("-e", "-ma", "-tp50", "-gb", "-wk")


def cfg(**kw):
    return RX.normalize_config({**OWNER, **kw})


# ---------------------------------------------------------------- the config and the accounts
def test_owner_accounts_on_the_real_picks():
    cands = C.load()
    accts = RX.accounts(cands, cfg())
    by = {a["id"]: a for a in accts}
    roe = [c for c in cands if c["exit"].startswith("roe50|")]
    assert len(cands) == 38 and len(roe) == 1
    assert len(accts) == 38 * 5 - len(roe) == 189 and len(by) == len(accts) and RX.check(cands, cfg()) == []
    assert all(C.ID_RE.match(a["id"]) and a["size"] == 1.0 for a in accts)
    for c in cands:
        k = c["exit"].split("|")[1]
        mine = [a for a in accts if a["pick"] == c["id"]]
        want = [s for s in SUFFIXES if not (s == "-tp50" and c["exit"] == f"roe50|{k}")]
        assert [a["id"] for a in mine] == [c["id"] + s for s in want]                     # the file's order, per pick
        e = by[c["id"] + "-e"]
        assert (e["role"], e["rule"]["family"], e["exit"], e["of"], e.get("weekend_off")) == ("cand", None, c["exit"], c["id"], None)
        assert e["source"].get("band") == c["source"].get("band") and e["source"]["rank"] == c["source"]["rank"]   # the pick's own record
        for a in mine:
            assert all(a[q] == c[q] for q in ("kind", "name", "tf", "combo"))
            if a is not e:
                assert a["of"] == e["id"] and "band" not in a["source"]
        ma, gb, wk = by[c["id"] + "-ma"], by[c["id"] + "-gb"], by[c["id"] + "-wk"]
        assert (ma["role"], ma["rule"]["id"], ma["exit"]) == ("ma", "F2.n50.b", c["exit"])
        assert (gb["role"], gb["rule"]["id"], gb["exit"]) == ("gb", "F5.P1.g50.a", c["exit"])
        assert (wk["role"], wk["rule"]["family"], wk["exit"], wk["weekend_off"]) == ("wk", None, c["exit"], True)
        if c not in roe:
            tp = by[c["id"] + "-tp50"]
            assert (tp["role"], tp["rule"]["family"], tp["exit"]) == ("tp50", None, f"roe50|{k}")      # the pick's own stop multiple
            assert X.spec(tp["exit"])["stop_atr"] == X.spec(c["exit"])["stop_atr"]
    assert roe[0]["id"] + "-tp50" not in by                                                  # no duplicate of its own exit
    lu = RX.lineup(accts)
    assert [x["role"] for x in lu] == ["cand", "ma", "tp50", "gb", "wk"] and [x["label_ko"] for x in lu] == list(LABELS)
    assert [x["accounts"] for x in lu] == [38, 38, 37, 38, 38] and all(x["desc_ko"] and x["why_ko"] and x["short_ko"] for x in lu)
    assert "EMA(50)" in lu[1]["desc_ko"] and "+50%" in lu[2]["desc_ko"] and "+1R" in lu[3]["desc_ko"] and "토 00:00" in lu[4]["desc_ko"]
    # only the current-exit accounts are judged as the pick; the study's forward checks find nothing of theirs
    assert {a["role"] for a in accts} == {"cand", "ma", "tp50", "gb", "wk"}


def test_the_file_switch_and_the_other_forms_stay_as_they_were(tmp_path):
    cands = C.load()
    path = tmp_path / "rules.json"
    assert RX.load_accounts(str(tmp_path / "none.json"), cands) is None
    assert RN.league_accounts(str(tmp_path / "none.json"), cands) == C.accounts(cands)       # no file: the candidate league
    path.write_text(json.dumps({**OWNER, "enabled": False}))
    assert RX.load_accounts(str(path), cands) is None and RN.league_accounts(str(path), cands) == C.accounts(cands)
    path.write_text(json.dumps(OWNER, ensure_ascii=False))
    got = RN.league_accounts(str(path), cands)
    assert [a["id"] for a in got] == [a["id"] for a in RX.accounts(cands, cfg())]
    # the exit study's form is untouched
    path.write_text(json.dumps({"enabled": True, "pools": {"core": "F2.n50.b", "ds": None}}))
    old = RX.load_accounts(str(path), cands)
    assert len(old) == 23 * 5 + 15 * 3 and not any(a.get("ox") or a.get("weekend_off") for a in old)
    assert RX.lineup(old) is None and RX.lineup(C.accounts(cands)) is None
    # the fingerprint: the weekend switch is part of it; an account without it is fingerprinted as before
    accts = RX.accounts(cands, cfg())
    no_wk = [{k: v for k, v in a.items() if k != "weekend_off"} for a in accts]
    assert RN.fingerprint(accts) != RN.fingerprint(no_wk)
    assert RN.fingerprint([{k: v for k, v in a.items() if k != "ox"} for a in accts]) == RN.fingerprint(accts)   # words never restart it
    # the command line
    assert RX.main(["check", "--rules", str(tmp_path / "x.json")]) == 0
    path.write_text(json.dumps(OWNER, ensure_ascii=False))
    assert RX.main(["check", "--rules", str(path)]) == 0


@pytest.mark.parametrize("bad", [
    {"pools": {"core": "F2.n50.b"}},                                                   # both forms
    {"no_entry_from_ms": {"core": 1_800_000_000_000}},                                 # the study's C1 stop
    {"owner_exits": []},
    {"owner_exits": [{"suffix": "-ma", "rule": "F2.n50.b", "label_ko": "x"}]},           # no current-exit account
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-e2", "label_ko": "b"}]},       # two of them
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-e", "rule": "F3.a", "label_ko": "b"}]},   # a repeated suffix
    {"owner_exits": [{"suffix": "e", "label_ko": "a"}]},
    {"owner_exits": [{"suffix": "-E", "label_ko": "a"}]},
    {"owner_exits": [{"suffix": "-e", "label_ko": ""}]},
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-x", "rule": "F2.n50.b", "exit": "roe50", "label_ko": "b"}]},
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-x", "exit": "roe55", "label_ko": "b"}]},
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-x", "exit": "roe50|2", "label_ko": "b"}]},
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-x", "exit": "swing3", "label_ko": "b"}]},  # no structure level here
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-x", "rule": "F2.n50.c", "label_ko": "b"}]},
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-flip", "rule": "F3.a", "label_ko": "b"}]},  # another league's role
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-x", "weekend_off": "yes", "label_ko": "b"}]},
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-x", "weekend": True, "label_ko": "b"}]},       # a typo is refused
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}, {"suffix": "-x", "size": 0, "label_ko": "b"}]},
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}], "picks": ["nope"]},
    {"owner_exits": [{"suffix": "-e", "label_ko": "a"}], "enabled": "yes"},
])
def test_refusals_say_why(bad, tmp_path):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({"enabled": True, "owner_exits": OWNER["owner_exits"], **bad}, ensure_ascii=False))
    with pytest.raises(RX.RuleConfigError):
        RX.load_accounts(str(p), C.load())


def test_a_smaller_lineup_and_listed_picks():
    cands = C.load()
    one = RX.accounts(cands, RX.normalize_config({"owner_exits": [{"suffix": "-e", "label_ko": "지금"}, {"suffix": "-lad", "exit": "ladder", "label_ko": "계단"}],
                                                  "picks": [cands[0]["id"]]}))
    k = cands[0]["exit"].split("|")[1]
    assert [(a["id"], a["exit"], a["role"]) for a in one] == [(cands[0]["id"] + "-e", cands[0]["exit"], "cand"),
                                                              (cands[0]["id"] + "-lad", f"ladder|{k}", "lad")]


# ---------------------------------------------------------------- the weekend gate
FRI = 1_704_412_800_000                       # 2024-01-05 00:00 UTC, a Friday
SAT, MON = FRI + DAY, FRI + 3 * DAY


def test_is_weekend_at_the_edges():
    assert not RX.is_weekend(SAT - 1) and RX.is_weekend(SAT) and RX.is_weekend(MON - 1) and not RX.is_weekend(MON)
    assert not RX.is_weekend(SAT - 7 * DAY - 1) and RX.is_weekend(SAT + 7 * DAY)
    # the same days as the studies' weekend (research/exitflex/extra/common.is_weekend: Monday = 0)
    for t in range(FRI - 3 * DAY, FRI + 9 * DAY, 3_600_000):
        assert RX.is_weekend(t) == (((t // DAY) + 3) % 7 >= 5)


def _bar(t, o, h=None, lo=None, c=None):
    h = o if h is None else h
    lo = o if lo is None else lo
    c = o if c is None else c
    return {RT.SYM: Bar(RT.SYM, t, t + MIN - 1, o, h, lo, c, mark_open=o, mark_high=h, mark_low=lo, mark_close=c)}


def _wk_acct(weekend=True, exit_="tp3R|2"):
    a = RT.acct(None, exit_=exit_, aid="wk")
    if weekend:
        a["weekend_off"] = True
    return a


def _enter(a, close, fill_at=None):
    """A fresh engine of account ``a``, one long signal whose bar closes at ``close``, stepped at ``fill_at`` (default: the close)."""
    e = RX.make_engine(a, RT.BR, RT.SP)
    e.submit(RT.sig(close, 1, aid=a["id"]))
    _step(e, _bar(close if fill_at is None else fill_at, RT.P0))
    return e


def _step(e, bars):
    PS.stamp_ref(e, bars)                     # as the league's replay does: the fill minute's open is the signal's reference
    e.step(bars)


@pytest.mark.parametrize("close,entered", [
    (SAT - 15 * MIN, True),          # Friday 23:45: before the window
    (SAT, False),                    # Saturday 00:00: the window starts here
    (SAT + DAY + 12 * 3_600_000, False),
    (MON - 15 * MIN, False),         # Sunday 23:45
    (MON, True),                     # Monday 00:00: the window has ended
])
def test_the_weekend_account_takes_no_new_entry_from_a_bar_closing_in_the_window(close, entered):
    e = _enter(_wk_acct(), close)
    assert (e.position is not None) == entered
    if not entered:
        assert [(o.status, o.reason) for o in e.outcomes] == [("REJECTED", RX.WEEKEND_REASON)]
    plain = _enter(_wk_acct(weekend=False), close)                   # the current-exit account enters every one
    assert plain.position is not None and type(plain).__name__ == "PaperEngine"
    assert type(e).__name__ == "LockEngine" and e.rx_rule is None and e.rx_weekend_off


def test_the_window_is_read_on_the_signal_bars_close_not_on_the_fill():
    # a bar closing Friday 23:45 whose coin minutes were missing fills on Saturday: allowed (the bar closed before the window)
    assert _enter(_wk_acct(), SAT - 15 * MIN, fill_at=SAT + 10 * MIN).position is not None


def test_an_open_position_is_managed_through_the_weekend():
    a = _wk_acct()
    e = _enter(a, SAT - 15 * MIN)
    p = e.position
    assert p is not None
    e.outcomes.clear()
    e.submit(RT.sig(SAT + 60 * MIN, 1, aid="wk"))                     # a Saturday signal while holding: skipped, as always
    _step(e, _bar(SAT + 60 * MIN, RT.P0))
    assert [(o.status, o.reason) for o in e.outcomes] == [("SKIPPED", "in position")] and e.position is p
    _step(e, _bar(SAT + 61 * MIN, RT.P0, lo=RT.P0 - RT.R * 1.5))      # Saturday: the stop is hit and the position closes
    assert e.position is None and e.trades[-1].exit_reason == "SL" and SAT <= e.trades[-1].exit_time < MON
    e.outcomes.clear()
    e.submit(RT.sig(SAT + 120 * MIN, 1, aid="wk"))                    # flat on Saturday: refused by the weekend gate
    _step(e, _bar(SAT + 120 * MIN, RT.P0))
    assert e.position is None and e.outcomes[0].status == "REJECTED"


# ---------------------------------------------------------------- the roe50 take-profit
@pytest.mark.parametrize("side", [1, -1])
def test_the_roe50_account_takes_profit_at_the_engines_net_roe_price(side):
    a = RT.acct(None, exit_="roe50|2", aid="tp50")
    e = RX.make_engine(a, RT.BR, RT.SP)
    assert type(e).__name__ == "PaperEngine" and e.s.tp_mode == "fixed" and e.s.default_tp_roe == 0.5
    t = RT.C0
    e.submit(RT.sig(t, side, aid="tp50"))
    _step(e, _bar(t, RT.P0))
    p = e.position
    fill = RT.P0 * (1 + side * e.s.slippage_frac)
    assert p.entry_price == pytest.approx(fill) and p.stop_price == pytest.approx(RT.P0 - side * RT.R)      # the pick's stop (k x ATR)
    want = tp_from_roe(side, p.entry_price, p.leverage, 0.5, round_trip=e.s.round_trip_cost)
    assert p.tp_price == pytest.approx(want) and want == pytest.approx(fill * (1 + side * (0.5 / p.leverage + e.s.round_trip_cost)))
    # the price moves through it: the trade closes at the take-profit limit with at least +50% net ROE
    beyond = want * (1 + side * 0.001)
    _step(e, _bar(t + MIN, RT.P0, h=max(RT.P0, beyond), lo=min(RT.P0, beyond), c=RT.P0))
    tr = e.trades[-1]
    assert (tr.exit_reason, tr.exit_price) == ("TP", pytest.approx(want))
    assert 0.5 - 1e-9 <= tr.roe <= 0.5 + e.s.round_trip_cost * p.leverage


# ---------------------------------------------------------------- the league, end to end on synthetic bars (a weekend inside)
DATA = {s: TP._synth5(i + 3, TP.P0[s], days=TP.HIST_DAYS + 9) for i, s in enumerate(TP.SYMS)}
START = TP.D0                                  # 2026-10-05 00:00 UTC, a Monday
LSAT, LMON = START + 5 * DAY, START + 7 * DAY
END = START + 8 * DAY
LIB = sweepsig.lib()


def _combo(name):
    return {k: C._plain(v) for k, v in C.default_combo("core", name).items()}


CANDS = [{"id": "core-S2-15m-1", "kind": "core", "name": "S2_ST_ROC", "tf": "15m", "combo": _combo("S2_ST_ROC"), "exit": "tp3R|2",
          "source": {"rank": 1, "band": {"30": {"p5": -0.01, "median": 0.0}}}},
         {"id": "core-S1-1h-1", "kind": "core", "name": "S1_EMA_RSI_CHOP", "tf": "1h", "combo": _combo("S1_EMA_RSI_CHOP"),
          "exit": "roe50|2", "source": {"rank": 1}}]
P1 = "core-S2-15m-1"


def _league(db, **kw):
    kw.setdefault("start_ms", START)
    return RN.League(RN.open_db(str(db)), RX.accounts(CANDS, cfg()), TP.BRACKETS, TP.SPECS, LIB, PS.FrameSource(DATA),
                     TP._steps_from(DATA), TP.SYMS, log=lambda s: None, **kw)


def _trades(lg, only=None):
    out = []
    for a, d in lg.conn.execute("SELECT account, data FROM trades ORDER BY account, exit_time, rowid"):
        if only is None or a in only:
            t = json.loads(d)
            out.append((a, t["entry_time"], t["exit_time"], t["exit_reason"], round(t["pnl"], 8)))
    return out


@pytest.fixture(scope="module")
def whole(tmp_path_factory):
    lg = _league(tmp_path_factory.mktemp("own") / "a.db")
    lg.advance(END)
    return lg


def test_every_kind_exits_as_it_should_in_the_league(whole):
    assert [a["id"] for a in whole.accts] == [P1 + s for s in SUFFIXES] + ["core-S1-1h-1" + s for s in ("-e", "-ma", "-gb", "-wk")]
    rows = [(a, json.loads(d)) for a, d in whole.conn.execute("SELECT account, data FROM trades")]
    reasons = {}
    for a, t in rows:
        reasons.setdefault(a, set()).add(t["exit_reason"])
    assert reasons[P1 + "-e"] <= {"SL", "TP", "LIQ"} and "TP" in reasons[P1 + "-e"]
    assert "RULE" in reasons[P1 + "-ma"] and "TP" not in reasons[P1 + "-ma"]           # mode b: no take-profit, the EMA exit
    assert "RULE" in reasons[P1 + "-gb"]                                                 # mode a: the give-back exit, the pick's TP kept
    assert "RULE" not in reasons[P1 + "-tp50"] | reasons[P1 + "-wk"] | reasons[P1 + "-e"]
    tp = [t for a, t in rows if a == P1 + "-tp50" and t["exit_reason"] == "TP"]
    assert tp and all(t["roe"] >= 0.5 - 1e-9 for t in tp)
    assert all(t["roe"] < 0.5 for a, t in rows if a == P1 + "-tp50" and t["exit_reason"] != "TP")
    # every account sizes at the league's live size
    assert {whole.engines[a["id"]].s.tiers[0].margin_frac for a in whole.accts} == {0.5}
    # the -gb account's rule fires only after the peak reached +1R: every RULE exit's best price was at least 1R away
    for a, t in rows:
        if a == P1 + "-gb" and t["exit_reason"] == "RULE":
            r = abs(t["entry_price"] - t["stop_initial"])
            assert abs(t["mfe_price"] - t["entry_price"]) >= r * 0.99


def test_the_weekend_account_skips_weekend_entries_and_is_the_current_exits_twin_before(whole):
    rows = _trades(whole)
    e = [r for r in rows if r[0] == P1 + "-e"]
    wk = [r for r in rows if r[0] == P1 + "-wk"]
    assert any(LSAT <= r[1] < LMON for r in e)                                          # the current exit did enter on the weekend
    assert not any(LSAT <= r[1] < LMON for r in wk)                                     # the weekend account did not
    assert [r[1:] for r in e if r[1] < LSAT] == [r[1:] for r in wk if r[1] < LSAT] and any(r[1] < LSAT for r in e)
    assert any(r[1] >= LMON for r in wk)                                                # and trades again from Monday
    days = {d: (o, en, sk, rj) for a, d, o, en, sk, rj, _c in whole.conn.execute("SELECT * FROM acct_day WHERE account = ?", (P1 + "-wk",))}
    assert days[LSAT][1] == 0 and days[LSAT + DAY][1] == 0 and days[LSAT][3] + days[LSAT + DAY][3] > 0      # refused, counted as rejected


def test_a_stop_and_restart_at_awkward_times_gives_the_same_trades(tmp_path, whole):
    db = tmp_path / "b.db"
    lg = _league(db)
    t = START
    for step in (7, 3, 25, 1, 40, 13, 90, 5, 288, 71, 600):
        t = min(END, t + step * RN.FIVE)
        lg.advance(t)
        lg = _league(db)
        assert lg.done == t and lg.restore_notes == []
    lg.advance(END)
    assert _trades(lg) == _trades(whole) and len(_trades(whole)) > 50


@pytest.mark.parametrize("suffix,key", [("-ma", "arm"), ("-gb", "armed")])
def test_a_restart_in_the_middle_of_an_open_rule_position_restores_its_state(tmp_path, whole, suffix, key):
    """F2 (EMA arm) and F5 (the +1R arm): restart while the position is open, the stored state equals its recomputation from the
    bars; damage it and the restore corrects it, so the later trades are the whole run's."""
    db = tmp_path / "c.db"
    lg = _league(db)
    aid, t = P1 + suffix, START
    while t < END:
        t += 3 * RN.FIVE
        lg.advance(t)
        p = lg.engines[aid].position
        if p is not None and p.signal.meta.get("rx") and (suffix == "-ma" or p.signal.meta["rx"].get("armed")):
            break
    p = lg.engines[aid].position
    assert p is not None and key in p.signal.meta["rx"]
    rx = json.loads(json.dumps(p.signal.meta["rx"]))
    again = _league(db)
    assert again.restore_notes == [] and again.engines[aid].position.signal.meta["rx"] == rx
    st = RN._get(again.conn, "engines")
    bad = st[aid]["position"]["signal"]["meta"]["rx"]
    bad[key] = not bad[key]
    bad["x"] = bad["x"] * (1.01 if p.side < 0 else 0.99)                                # a wrong arm and a wrong extreme
    RN._put(again.conn, "engines", st)
    again.conn.commit()
    fixed = _league(db)
    assert fixed.restore_notes and aid in fixed.restore_notes[0] and key in fixed.restore_notes[0]
    assert fixed.engines[aid].position.signal.meta["rx"][key] == rx[key]
    fixed.advance(END)
    assert _trades(fixed) == _trades(whole)


def test_signals_are_the_same_for_every_kind_and_the_stop_is_the_picks():
    accts = RX.accounts(CANDS[:1], cfg())
    by, _notes = RX.chunk_rule(LIB, PS.FrameSource(DATA), accts, TP.SYMS, START, START + DAY, START)
    sigs = {}
    for close, items in by.items():
        for aid, o in items:
            if isinstance(o, Signal):
                sigs.setdefault(aid, []).append((close, o.symbol, o.side, round(o.meta["stop_dist"] / o.atr, 9)))
    assert len({tuple(v) for v in sigs.values()}) == 1 and len(sigs) == 5 and sigs[P1 + "-e"]     # same signals, same 2 ATR stop
    assert {s[3] for s in sigs[P1 + "-e"]} == {2.0}
    recs = {aid for items in by.values() for aid, o in items if isinstance(o, RX.RuleClose)}
    assert recs == {P1 + "-ma", P1 + "-gb"}                                              # chart records only where a rule decides


# ---------------------------------------------------------------- the snapshot, Telegram, DeepSeek money
def test_the_snapshot_carries_the_lineup_and_judges_nothing(tmp_path, whole):
    doc = RN.write_snapshots(str(tmp_path / "snap"), whole, END + MIN)
    assert [x["label_ko"] for x in doc["lineup"]] == list(LABELS) and [x["suffix"] for x in doc["lineup"]] == list(SUFFIXES)
    rows = {r["id"]: r for r in doc["accounts"]}
    assert rows[P1 + "-ma"]["role_ko"] == "이동평균 이탈" and rows[P1 + "-wk"]["weekend_off"] is True
    assert rows[P1 + "-e"]["pick"] == P1 and rows[P1 + "-e"]["hold"]["n"] > 0 and rows[P1 + "-e"]["counts"]["entered"] > 0
    assert doc["judge"][P1 + "-e"]["verdict"] == "na" and set(doc["judge"]) == {P1 + "-e", "core-S1-1h-1-e"}
    assert "band" in doc["judge"][P1 + "-e"] or rows[P1 + "-e"]["trades"] < 30                 # the warning light still reads the pick's band
    w = doc["watch"]
    assert w["checkpoints"] == [] and w["owner"] is True and w["roles"][:1] == ["cand"]
    core = w["pools"]["core"]
    assert core["picks"] == 2 and {"ma", "tp50", "gb", "wk"} <= set(core["roles"]) and core["roles"]["ma"]["n"] > 0
    assert core["hold"]["ma"]["median_h"] is not None and core["hold"]["ma"]["n"] == core["roles"]["ma"]["n"]
    assert {r for r in core["weeks"][0] if r != "week_ms"} == {"cand", "ma", "tp50", "gb", "wk"}
    race = SM.race(whole.accts, json.load(open(tmp_path / "snap" / "trades.json")), START, END)
    assert {"cand", "ma", "tp50", "gb", "wk"} <= set(race["pools"]["core"]["roles"])
    # the candidate league's snapshot has no lineup and keeps its checkpoints
    plain = SM.watch_summary(C.accounts(CANDS), {}, END, False)
    assert plain["owner"] is False and len(plain["checkpoints"]) == 3


def test_telegram_names_the_owners_exits(tmp_path, whole):
    doc = RN.write_snapshots(str(tmp_path / "snap"), whole, END + MIN, ds_money=True)
    text = N.summary_text(doc, END + MIN)
    assert "청산 비교" in text and "잔고 1등" not in text and "5계좌 비교" not in text and "28일째 판정" in text     # short: the decision's schedule and kinds, not every kind
    assert any(x["short_ko"] in text for x in doc["lineup"][:4]) and "판정 일정" in text and "대시보드 '판정'" in text
    assert "기준 통과" not in text and "다음 점검" not in text and text.startswith("📊 아침 요약 · 후보 리그")
    lead, n, hid = N.best_counts(doc)
    assert n == sum(lead.values()) and hid == 0 and n >= 1
    row = next(r for r in doc["accounts"] if r["id"] == P1 + "-ma")
    assert "이동평균 이탈" in N.bust_text([row], END) and "지금 청산" in N.pick_ko(next(r for r in doc["accounts"] if r["id"] == P1 + "-e"))
    # the candidate league's words are unchanged
    plain = {"name": "S2_ST_ROC", "tf": "15m", "role": "quarter"}
    assert N.pick_ko(plain).endswith("1/4 크기") and N.pick_ko({**plain, "role": "cand"}).endswith("15분")


def test_deepseek_money_stays_hidden_in_the_owner_exit_league(tmp_path, whole):
    """The same accounts as DeepSeek ones (the hiding reads the kind): with the snapshot's switch off nothing of their money leaves the
    engine, and the dashboard's strict mode strips it from a snapshot that shows it."""
    ds = [{**a, "kind": "ds"} for a in whole.accts]
    book = RN.closed_trades(whole.conn, ds)
    rows = RN.account_rows(whole.conn, ds, whole.engines, False, book)
    assert all(r["wallet"] is None and r["mean_ret"] is None and r["max_dd"] is None for r in rows)
    assert all(set(r["open"]) == {"symbol", "side", "since"} for r in rows if r["open"])
    assert all(r["hold"] is not None and r["role_ko"] for r in rows)                    # hold hours and labels stay (D11)
    tb = RN.trade_book(whole.conn, ds, False, START, book)
    assert all(v["equity"] is None and all(t["pnl"] is None and t["entry_price"] is None for t in v["trades"]) for v in tb.values())
    w = SM.watch_summary(ds, book, END, False)
    assert w["pools"]["ds"]["money"] is False and all(x["mean"] is None for x in w["pools"]["ds"]["roles"].values())
    doc = {"generated_ms": END, "done_ms": END, "start_ms": START, "lag_s": 0, "accounts": rows, "judge": {}, "watch": w,
           "ds_money": False, "lineup": RX.lineup(ds)}
    text = N.summary_text(doc, END)
    assert "금액 숨김" in text and "한 번 평균" not in text
    lead, n, hid = N.best_counts(doc)
    assert n == 0 and lead == {} and hid >= 1
    # the dashboard: strict mode strips a snapshot that shows DeepSeek money; the positions and the rules routes hide it
    shown = {**doc, "accounts": RN.account_rows(whole.conn, ds, whole.engines, True, book), "ds_money": True,
             "watch": SM.watch_summary(ds, book, END, True)}
    strict = D.strict_league(shown)
    assert all(a["wallet"] is None and a["mean_ret"] is None for a in strict["accounts"])
    assert all(x["mean"] is None for x in strict["watch"]["pools"]["ds"]["roles"].values())
    pos = D.positions_doc(doc, None)
    assert all(p["hidden"] and p["entry"] is None and p["lev"] is None for p in pos["positions"])
    rules = D.rules_doc({**doc, "accounts": [{**r, "exit_ko": X.exit_ko(r["exit"])} for r in rows]}, tb, None, None)
    pick = rules["picks"][P1 + "-e"]
    assert set(pick["roles"]) == {"cand", "ma", "tp50", "gb", "wk"} and all(x["used"] is None for x in pick["roles"].values())


# ---------------------------------------------------------------- the dashboard (node)
NODE = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
const LB = await import(`file://${S}/js/labels.js`);
const doc = cfg.routes["/api/league"];
LK.setLeague(doc);
const tick = () => new Promise((r) => setTimeout(r, 20));
const out = {roles: LB.ROLES.slice(), ko: {...LB.ROLE_KO}, ids: {}, screens: {}};
const ix = LK.index(doc);
for (const c of ix.cands) out.ids[c.id] = Object.fromEntries(Object.entries(ix.sets[c.id]).map(([r, a]) => [r, a ? a.id : null]));
for (const name of cfg.screens) {
  const mod = await import(`file://${S}/js/screens/${name}.js`);
  const el = document.createElement("div");
  el.dataset.screen = name;
  document.body.appendChild(el);
  const ctx = {params: {name, arg: null, query: {}}, alive: () => true, signal: null, api: async (p) => (await globalThis.fetch(p)).json(),
    meta: () => LK.getMeta(), onLeague: (fn) => fn(doc), onLive: () => () => {}, onPositions: () => () => {}, every: () => {},
    css: async () => null, wide() {}, setTitle() {}, setQuery() {}, href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
  await mod.mount(el, ctx);
  await tick();
  const rows = el.querySelectorAll("table.cl-cmp tbody tr").map((tr) => tr.children.map(txt));
  out.screens[name] = {text: txt(el), head: el.querySelectorAll("table.cl-cmp thead th").map(txt), rows,
    hidden: el.querySelectorAll("section").filter((s) => s.hidden).length};
}
const P = await import(`file://${S}/js/poskit.js`);
out.posGroups = P.POS_GROUPS.map((g) => g.id);
LK.setLeague({...doc, lineup: undefined});
out.after = {roles: LB.ROLES.slice(), cand: LB.ROLE_KO.cand, posGroups: P.POS_GROUPS.map((g) => g.id)};
console.log(JSON.stringify(out));
"""


def _ui_league(ds_money=True):
    lu = [{"role": r, "suffix": s, "label_ko": lb, "short_ko": sh, "desc_ko": f"{lb} 설명", "why_ko": "보려는 것", "kind": "x", "size": 1.0}
          for r, s, lb, sh in zip(("cand", "ma", "tp50", "gb", "wk"), SUFFIXES, LABELS, ("지금", "이동평균", "ROE 50%", "반납 보호", "주말 쉼"))]
    now = 1_791_763_200_000

    def acct(pid, kind, name, tf, exit_, suffix, role, trades, wallet, hold):
        return {"id": pid + suffix, "pick": pid, "role": role, "role_ko": dict(zip(SUFFIXES, LABELS))[suffix], "kind": kind, "name": name, "tf": tf,
                "exit": exit_, "exit_ko": "고정 익절 3R · 손절 2 ATR", "combo": {}, "of": pid if role == "cand" else pid + "-e", "size": 1.0,
                "source": {"rank": 1}, "trades": trades, "wins": trades // 2, "mean_ret": (wallet / 5000 - 1) / max(1, trades),
                "wallet": wallet, "max_dd": 0.1, "bust": False, "open": None, "hold": {"n": trades, "median": hold}}
    A = []
    for pid, kind, name, tf, exit_, w in (("core-DOGE-15m-1", "core", "DOGE", "15m", "tp3R|4", (5600.0, 6100.0, 5200.0, 5900.0, 5550.0)),
                                          ("core-OBV_S-1h-3", "core", "OBV_S", "1h", "roe50|4", (4800.0, 5100.0, None, 4700.0, 4900.0)),
                                          ("ds-F10_OTE-1h-1", "ds", "F10_OTE", "1h", "tp3R|2", (7777.77, 6666.66, 6123.45, 5432.1, 8888.88))):
        for (suffix, role), wal, hold in zip(zip(SUFFIXES, ("cand", "ma", "tp50", "gb", "wk")), w, (20.5, 6.0, 3.0, 9.0, 18.0)):
            if wal is None:
                continue                                                            # the roe50 pick has no -tp50 account
            A.append(acct(pid, kind, name, tf, exit_, suffix, role, 12, wal, hold))
    if not ds_money:
        for a in A:
            if a["kind"] == "ds":
                a.update(wallet=None, mean_ret=None, max_dd=None)
    roles = {r: {"n": 36, "wins": 18, "mean": 0.001 if ds_money else None} for r in ("cand", "ma", "tp50", "gb", "wk")}
    hold = {r: {"n": 36, "median_h": h, "share_gt8": 0.4, "share_gt18": 0.1} for r, h in zip(roles, (20.5, 6.0, 3.0, 9.0, 18.0))}
    pools = {"core": {"picks": 2, "accounts": 9, "money": True, "roles": roles, "hold": hold, "c2": {}, "c1_stop": None, "weeks": []},
             "ds": {"picks": 1, "accounts": 5, "money": ds_money, "roles": roles, "hold": hold, "c2": {}, "c1_stop": None, "weeks": []}}
    return {"generated_ms": now, "done_ms": now, "lag_s": 0, "start_ms": now - 2 * DAY, "started_ms": now - 2 * DAY, "accounts": A,
            "ds_money": ds_money, "lineup": lu, "judge": {"core-DOGE-15m-1-e": {"verdict": "na", "trades": 12}},
            "watch": {"checkpoints": [], "owner": True, "pools": pools, "strategies": {}, "picks": {}, "min_trades": 300}}


def _node(tmp_path, league, screens):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(NODE)
    routes = {"/api/league": league, "/api/meta": RANK.META, "/api/fills": {"fills": []}, "/api/insight": {"accounts": {}},
              "/api/checkpoints": {"due": [], "results": {}}, "/api/sparks": {"sparks": {}}}
    (tmp_path / "cfg.json").write_text(json.dumps({"static": RANK.STATIC, "routes": routes, "screens": screens}, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def test_the_dashboard_groups_each_picks_accounts_with_the_owners_words(tmp_path):
    out = _node(tmp_path, _ui_league(), ["compare", "home", "check", "rank"])
    assert out["roles"] == ["cand", "ma", "tp50", "gb", "wk"] and [out["ko"][r] for r in out["roles"]] == list(LABELS)
    assert out["ids"]["core-DOGE-15m-1-e"] == {r: "core-DOGE-15m-1" + s for r, s in zip(out["roles"], SUFFIXES)}
    assert out["ids"]["core-OBV_S-1h-3-e"]["tp50"] is None
    cmp_ = out["screens"]["compare"]
    assert cmp_["head"][1:] == list(LABELS) and len(cmp_["rows"]) == 3 and all(len(r) == 6 for r in cmp_["rows"])
    doge = next(r for r in cmp_["rows"] if "도지 봇" in r[0])
    assert doge[2].startswith("★ +22.0%") and "보유 6.0h" in doge[2] and doge[1].startswith("+12.0%")    # the best of the pick starred
    obv = next(r for r in cmp_["rows"] if "OBV" in r[0])
    assert obv[3] == "—"                                                                # its own exit is already roe50: no account
    t = cmp_["text"]
    assert "계좌 비교" in t and "5계좌 비교" not in t and "이동평균 > 지금" in t and "8시간 넘게" in t and "보유 중앙" in t       # the lineup's screen name is never "5계좌"
    assert all(lb in t for lb in LABELS) and "기본값보다" not in t
    home = out["screens"]["home"]["text"]
    assert "청산 비교" in home and "계좌 종류 5가지" in home and "판정 화면 보기" in home                # the hero: kinds side by side, the way to the decision
    assert "잔고 1등" not in home and "같은 손절" not in home and "미리 정한 점검 날짜가 없습니다" not in home      # the old league's wording is gone
    assert "청산 비교 리그" in out["screens"]["check"]["text"] and out["screens"]["check"]["hidden"] == 3
    assert "다른 청산" in out["screens"]["rank"]["text"]
    assert out["posGroups"] == ["all", "mc", "cand", "ma", "tp50", "gb", "wk", "core", "ds"]
    # a snapshot without a lineup: the candidate league's five accounts again
    assert out["after"]["roles"] == ["cand", "quarter", "exitonly", "base", "flip"] and out["after"]["cand"] == "후보"
    assert out["after"]["posGroups"] == ["all", "cand", "quarter", "exitonly", "base", "flip", "core", "ds"]


def test_the_dashboard_keeps_deepseek_money_hidden_in_the_owner_exit_league(tmp_path):
    out = _node(tmp_path, _ui_league(ds_money=False), ["compare", "home"])
    page = out["screens"]["compare"]["text"] + out["screens"]["home"]["text"]
    for leak in ("7,777.77", "6,666.66", "6,123.45", "5,432.10", "8,888.88", "+55.6%", "+33.3%", "+22.5%", "+8.6%", "+77.8%"):
        assert leak not in page, leak
    ds = next(r for r in out["screens"]["compare"]["rows"] if "OTE" in r[0] or "F10_OTE" in r[0])
    assert all(c.startswith("숨김") for c in ds[1:])
    assert "금액 숨김" in out["screens"]["compare"]["text"]
