import json
import sqlite3

from paperbot.cards import TAGS, card, cards_from_db, tag_stats
from paperbot.daily3 import SCHEMA

RT = 0.0014


def trade(**over):
    t = {"strategy_id": "N17_KC_RSI", "symbol": "BTCUSDT", "timeframe": "15m", "side": 1, "signal_ts": 899_999,
         "entry_time": 900_000, "entry_price": 100.0, "exit_time": 900_000 + 15 * 60_000, "exit_price": 99.2,
         "exit_reason": "SL", "leverage": 40, "roe": -0.38, "pnl": -38.0, "mfe_price": 100.1, "mae_price": 99.2,
         "context": {"regime": "trend_down", "htf_regime": "trend_down", "adx": 34.0, "di_plus": 12.0,
                     "di_minus": 30.0, "ema20_dist_atr": -2.5, "range_pct": 0.05}}
    t.update(over)
    return t


def test_card_describes_a_counter_trend_stop():
    c = card("N17_KC_RSI@15m", trade(), RT, names_ko={"N17_KC_RSI": "켈트너·RSI"})
    assert c["name_ko"] == "켈트너·RSI" and c["side_ko"] == "롱" and c["reason_ko"] == "손절"
    assert abs(c["best_roe"] - 40 * (0.001 - RT)) < 1e-9 and not c["touched_first_lock"]
    assert c["hold_bars"] == 1 and c["regime_ko"] == "하락 추세"
    assert c["tags"] == ["진입 직후 바로 손절", "추세 반대 진입", "상위 봉 추세 반대", "DI 방향 반대"]


def test_card_tags_for_a_short_and_missing_context():
    c = card("X@1h", trade(side=-1, timeframe="1h", exit_reason="LIQ", mfe_price=98.0, context={}), RT)
    assert c["tags"][0] == "강제청산" and c["touched_first_lock"]
    assert card("X@1h", trade(context=None, mfe_price=None, mae_price=None), RT)["best_roe"] is None
    assert len({name for name, _ in TAGS}) == len(TAGS)


def test_tag_stats_rank_tags_more_common_in_losses():
    cards = [card("A@15m", trade(), RT) for _ in range(3)]
    win = trade(pnl=12.0, roe=0.12, exit_reason="LOCK", context={"regime": "trend_up", "adx": 30,
                                                                 "di_plus": 30, "di_minus": 10})
    cards += [card("A@15m", win, RT) for _ in range(2)]
    st = tag_stats(cards)
    top = {r["tag"] for r in st if r["loss_share"] == 1.0 and r["win_share"] == 0.0}
    assert top == {"진입 직후 바로 손절", "추세 반대 진입", "상위 봉 추세 반대", "DI 방향 반대"}
    assert [r["tag"] for r in st[:4]] == [n for n, _ in TAGS if n in top]     # ties keep the fixed order
    assert st[-1]["loss_share"] - st[-1]["win_share"] <= 0


def test_cards_from_db_joins_stop_variants(tmp_path):
    db = sqlite3.connect(str(tmp_path / "p.db"))
    db.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, entry_time INT, "
               "exit_time INT, exit_reason TEXT, leverage INT, pnl REAL, roe REAL, equity_after REAL, data TEXT)")
    for aid, t in (("N17_KC_RSI@15m", trade()), ("N17XKCXRSI@15m", trade()),
                   ("N17_KC_RSI@15m", trade(pnl=5.0, roe=0.05))):
        db.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, "
                   "roe, equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (aid, t["symbol"], t["entry_time"], t["exit_time"], t["exit_reason"], 40, t["pnl"], t["roe"],
                    900.0, json.dumps(t)))
    daily = sqlite3.connect(str(tmp_path / "d.db"))
    daily.executescript(SCHEMA)
    daily.execute("INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("stop2.5|N17_KC_RSI@15m|BTCUSDT|900000", "d", "stop2.5", "N17_KC_RSI@15m", "BTCUSDT", "15m",
                   1, None, 0.10, "LOCK", 1, "{}"))
    got = cards_from_db(db, RT, strategy="N17_KC_RSI", daily_conn=daily)
    assert len(got) == 1 and got[0]["account_id"] == "N17_KC_RSI@15m"   # '_' is not a wildcard
    assert got[0]["if_stop"] == {"2.5": {"roe": 0.10, "exit_reason": "LOCK", "resolved": True}}
    assert len(cards_from_db(db, RT, strategy="N17_KC_RSI", losses_only=False)) == 2
    assert len(cards_from_db(db, RT, timeframe="15m")) == 2
