"""Loss cards in paper v4 (paperbot/cards.py): the reel and the 5m coin flips trade the reel's own exits (fixed stop
from the signal, band target, 96-bar time exit "TIME", no ladder), so their cards carry the trade's own stop and no
ladder facts; every other card (the 36, DeepSeek, the 15m-4h coin flips, the extras) is byte-identical to v3."""

import hashlib
import json
import sqlite3

from paperbot import cards as C
from paperbot.cards import OWN_EXIT_SKIPPED_TAGS, REASON_KO, TAGS, card, cards_from_db, own_exits, tag_stats
from paperbot.daily3 import SCHEMA

RT = 0.0014
SR = {"room": 1.2, "floor": 0.8, "level_before_lock": 1, "support_before_stop": 1, "breakout": 0,
      "lock_px": 101.0, "stop_px": 98.0, "floor_px": 99.0, "close": 100.0}


def trade(**over):
    t = {"strategy_id": "N17_KC_RSI", "symbol": "BTCUSDT", "timeframe": "15m", "side": 1, "signal_ts": 899_999,
         "entry_time": 900_000, "entry_price": 100.0, "exit_time": 900_000 + 15 * 60_000, "exit_price": 99.2,
         "exit_reason": "SL", "leverage": 40, "roe": -0.38, "pnl": -38.0, "mfe_price": 100.1, "mae_price": 99.2,
         "context": {"regime": "trend_down", "htf_regime": "trend_down", "adx": 34.0, "di_plus": 12.0,
                     "di_minus": 30.0, "ema20_dist_atr": -2.5, "range_pct": 0.05}}
    t.update(over)
    return t


def reel(**over):
    """A REEL_H1@5m trade: long, own stop 98.5 (swing low - 0.05 ATR), timed out after 96 5m bars."""
    t = trade(strategy_id="REEL_H1", timeframe="5m", exit_reason="TIME", exit_time=900_000 + 96 * 300_000,
              exit_price=99.6, leverage=30, roe=-0.15, pnl=-15.0, mfe_price=104.5, mae_price=98.7,
              stop_price=98.5, stop_initial=98.5, tp_price=101.0, context={"regime": "box", "sr": dict(SR)})
    t.update(over)
    return t


# The core cards, computed with paperbot/cards.py at HEAD 5bc7e5f (before the v4 change). A change to any of them is a
# change for the 36: the hash must stay.
CORE_CASES = [
    ("N17_KC_RSI@15m", trade()),
    ("X@1h", trade(side=-1, timeframe="1h", exit_reason="LIQ", mfe_price=98.0, context={})),
    ("X@1h", trade(context=None, mfe_price=None, mae_price=None)),
    ("A@15m", trade(pnl=12.0, roe=0.12, exit_reason="LOCK", context={"regime": "trend_up", "adx": 30, "di_plus": 30,
                                                                   "di_minus": 10})),
    ("B@4h", trade(timeframe="4h", mfe_price=106.0, stop_initial=98.0,
                   context={"regime": "box", "sr": dict(SR), "strength": {"features": [{"name": "x", "value": 1.0}]}})),
    ("B@30m", trade(timeframe="30m", context={"sr": {"error": "boom"}})),
    ("RANDOM_1@15m", trade(strategy_id="RANDOM_1", context={"sr": dict(SR)})),
    ("F9_FVG@1h", trade(strategy_id="F9_FVG", timeframe="1h", context={"sr": dict(SR)})),
]
CORE_SHA = "1e432a6d7a872a2e1f69131d4b739d73250d7312e07462f99d30878c09533c56"


def _core_dump(kinds=None) -> str:
    out = {"cards": [card(a, t, RT, names_ko={"N17_KC_RSI": "켈트너·RSI"},
                          **({"kind": kinds[k]} if kinds else {})) for k, (a, t) in enumerate(CORE_CASES)]}
    out["stats"] = tag_stats([card(a, t, RT) for a, t in CORE_CASES])
    out["stats_empty"] = tag_stats([])
    return json.dumps(out, sort_keys=True, ensure_ascii=False, default=str)


def test_core_cards_are_byte_identical_to_v3():
    assert hashlib.sha256(_core_dump().encode()).hexdigest() == CORE_SHA
    kinds = ["strategy", "strategy", "strategy", "strategy", "strategy", "strategy", "random", "ds200"]
    assert _core_dump(kinds) == _core_dump()                    # their kinds keep the house card


def test_which_accounts_have_their_own_exits():
    assert own_exits("reel", "REEL_H1", "5m") and own_exits("random", "RANDOM_2", "5m")
    for kind, name, tf in (("random", "RANDOM_2", "15m"), ("ds200", "F9_FVG", "1h"), ("strategy", "DOGE", "4h"),
                           ("copy", "N17_KC_RSI", "15m"), ("newlab", "NL1", "30m")):
        assert not own_exits(kind, name, tf), (kind, name, tf)
    # without the account's kind (a bare trades table, triggers.py): by name
    assert own_exits(None, "REEL_H1", "5m") and own_exits(None, "RANDOM_3", "5m")
    assert not own_exits(None, "RANDOM_3", "1h") and not own_exits(None, "F9_FVG", "15m")


def test_time_exit_has_a_korean_name():
    assert REASON_KO["TIME"] == "시간 청산"
    assert card("REEL_H1@5m", reel(), RT, kind="reel")["reason_ko"] == "시간 청산"


def test_reel_card_takes_its_own_stop_and_no_ladder_facts():
    c = card("REEL_H1@5m", reel(), RT, kind="reel")
    assert c["exits"] == "reel" and "사다리·잠금 없음" in c["exits_ko"]
    # best ROE 30 x 4.5% is far above the first lock (+12%), but the reel has no lock
    assert c["best_roe"] > 0.12 and c["touched_first_lock"] is None
    assert c["stop_price"] == 98.5 and c["stop_ko"] == "이 거래 자신의 손절 98.5 (진입가에서 1.50% 아래)"
    assert c["hold_bars"] == 96
    # the level behind (99.0) is closer than the own stop (98.5): "지지선 뒤 손절" by the trade's own stop
    assert "지지선 뒤 손절" in c["tags"] and not set(OWN_EXIT_SKIPPED_TAGS) & set(c["tags"])
    assert c["sr"]["stop_px"] == 98.5 and c["sr"]["support_before_stop"] == 1
    assert "lock_px" not in c["sr"] and "level_before_lock" not in c["sr"]
    assert c["ctx"]["sr"]["lock_px"] == 101.0                       # the recorded marks themselves are kept
    # an own stop beyond the level: no tag, although the 2 ATR stop of the marks (98.0) would say so
    far = card("REEL_H1@5m", reel(stop_initial=99.5, stop_price=99.5), RT, kind="reel")
    assert "지지선 뒤 손절" not in far["tags"] and far["sr"]["support_before_stop"] == 0
    # the stop the trade opened with wins over a later one; a missing stop is said so
    assert card("R@5m", reel(stop_initial=98.0, stop_price=99.0), RT, kind="reel")["stop_price"] == 98.0
    none = card("R@5m", reel(stop_initial=None, stop_price=float("nan")), RT, kind="reel")
    assert none["stop_price"] is None and none["stop_ko"] == "이 거래 자신의 손절 (기록 없음)"
    assert "지지선 뒤 손절" not in none["tags"]


def test_five_minute_coin_flip_card_without_kind_is_an_own_exit_card():
    c = card("RANDOM_1@5m", reel(strategy_id="RANDOM_1"), RT)
    assert c["exits"] == "reel" and c["touched_first_lock"] is None and c["stop_price"] == 98.5
    h = card("RANDOM_1@15m", trade(strategy_id="RANDOM_1", mfe_price=106.0), RT)
    assert "exits" not in h and h["touched_first_lock"] is True and "stop_ko" not in h


def test_house_card_keeps_the_ladder_tags():
    c = card("B@4h", trade(timeframe="4h", context={"sr": dict(SR)}), RT, kind="strategy")
    assert "저항 바로 앞 진입" in c["tags"] and "지지선 뒤 손절" in c["tags"]
    assert c["sr"]["lock_px"] == 101.0 and "exits" not in c


def test_tag_stats_of_own_exit_cards_leave_out_the_ladder_tags():
    own = [card("REEL_H1@5m", reel(), RT, kind="reel"), card("REEL_H1@5m", reel(pnl=8.0, roe=0.08), RT, kind="reel")]
    st = tag_stats(own)
    tags = [r["tag"] for r in st]
    assert not set(OWN_EXIT_SKIPPED_TAGS) & set(tags) and len(tags) == len(TAGS) - len(OWN_EXIT_SKIPPED_TAGS)
    note = next(r["note"] for r in st if r["tag"] == "지지선 뒤 손절")
    assert "이 거래 자신의 손절" in note and "2 ATR" not in note
    mixed = tag_stats(own + [card("A@15m", trade(), RT)])    # a list with house cards: v3 rows, notes say both rules
    assert len(mixed) == len(TAGS)
    assert next(r["note"] for r in mixed if r["tag"] == "지지선 뒤 손절") == C.TAG_NOTES["지지선 뒤 손절"] + C.MIXED_OWN_KO


def test_cards_from_db_passes_the_kind_and_skips_stop_whatifs_for_own_exits(tmp_path):
    from paperbot.store3 import Store3
    path = str(tmp_path / "p.db")
    st = Store3(path)
    st.add_account("REEL_H1@5m", "REEL_H1", "5m", "reel", 0, "v")
    st.add_account("RANDOM_1@5m", "RANDOM_1", "5m", "random", 0, "v")
    st.add_account("N17_KC_RSI@15m", "N17_KC_RSI", "15m", "strategy", 0, "v")
    st.commit()
    st.close()
    db = sqlite3.connect(path)
    for aid, t in (("REEL_H1@5m", reel()), ("RANDOM_1@5m", reel(strategy_id="RANDOM_1")),
                   ("N17_KC_RSI@15m", trade())):
        db.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                   "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (aid, t["symbol"], t["entry_time"], t["exit_time"], t["exit_reason"], t["leverage"], t["pnl"],
                    t["roe"], 900.0, json.dumps(t)))
    db.commit()
    daily = sqlite3.connect(str(tmp_path / "d.db"))
    daily.executescript(SCHEMA)
    for aid, tf in (("REEL_H1@5m", "5m"), ("N17_KC_RSI@15m", "15m")):     # a stray row for the reel is never read
        daily.execute("INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (f"stop2.5|{aid}|BTCUSDT|900000", "d", "stop2.5", aid, "BTCUSDT", tf, 1, None, 0.10, "LOCK", 1,
                       "{}"))
    got = {c["account_id"]: c for c in cards_from_db(db, RT, daily_conn=daily)}
    assert got["REEL_H1@5m"]["exits"] == "reel" and got["REEL_H1@5m"]["if_stop"] == {}
    assert got["REEL_H1@5m"]["reason_ko"] == "시간 청산" and got["RANDOM_1@5m"]["exits"] == "reel"
    assert got["N17_KC_RSI@15m"]["if_stop"] == {"2.5": {"roe": 0.10, "exit_reason": "LOCK", "resolved": True}}
    assert "exits" not in got["N17_KC_RSI@15m"]
    # a bare trades table (no accounts): the name decides
    bare = sqlite3.connect(str(tmp_path / "b.db"))
    bare.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, entry_time INT, "
                 "exit_time INT, exit_reason TEXT, leverage INT, pnl REAL, roe REAL, equity_after REAL, data TEXT)")
    t = reel()
    bare.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                 "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 ("REEL_H1@5m", "BTCUSDT", t["entry_time"], t["exit_time"], "TIME", 30, t["pnl"], t["roe"], 900.0,
                  json.dumps(t)))
    [c] = cards_from_db(bare, RT, daily_conn=daily)
    assert c["exits"] == "reel" and c["if_stop"] == {}


def test_tag_stats_of_a_mixed_list_say_how_own_exit_trades_are_measured():
    house = {"pnl": -1.0, "tags": ["지지선 뒤 손절"], "exits": None}
    own = {"pnl": -2.0, "tags": ["지지선 뒤 손절"], "exits": C.OWN_EXITS}
    mixed = {r["tag"]: r["note"] for r in C.tag_stats([house, own])}
    assert mixed["지지선 뒤 손절"] == C.TAG_NOTES["지지선 뒤 손절"] + C.MIXED_OWN_KO
    assert mixed["저항 바로 앞 진입"] == C.TAG_NOTES["저항 바로 앞 진입"] + C.MIXED_SKIPPED_KO
    assert mixed["돌파 진입"] == C.TAG_NOTES["돌파 진입"]
    plain = {r["tag"]: r["note"] for r in C.tag_stats([house])}
    assert plain == {k: C.TAG_NOTES.get(k) for k in plain}                  # house-only lists: unchanged
