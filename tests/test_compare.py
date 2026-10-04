import json
import sqlite3

from paperbot.agents import compare as C

DAY = 86_400_000
T0 = 1_790_000_000_000          # a weekday


def card(sym, side, tf, pnl, hour_kst=10, day=0, regime="추세장", reason="손절", hold=30, best=None, lock=False):
    entry = T0 - T0 % DAY - 9 * 3_600_000 + hour_kst * 3_600_000 + day * DAY
    return {"account_id": f"S@{tf}", "symbol": sym, "side": side, "side_ko": "롱" if side > 0 else "숏",
            "timeframe": tf, "pnl": pnl, "roe": pnl / 1000, "entry_time": entry, "regime_ko": regime,
            "reason_ko": reason, "hold_min": hold, "best_roe": best, "touched_first_lock": lock, "tags": []}


def test_win_loss_compare_splits_and_marks_small_groups():
    cs = [card("BTCUSDT", 1, "15m", 100, reason="익절 잠금", hold=90),
          card("BTCUSDT", 1, "15m", 80, reason="익절 잠금", hold=60),
          card("ETHUSDT", -1, "5m", -50, hour_kst=23, best=0.13, lock=True),
          card("ETHUSDT", -1, "5m", -60, hour_kst=23, regime="박스권")]
    r = C.win_loss_compare(cs, min_n=3)
    assert r["trades"] == 4 and r["all"]["win_rate"] == 0.5 and r["all"]["pnl"] == 70.0
    assert r["by_coin"]["BTC"] == {"trades": 2, "wins": 2, "losses": 0, "win_rate": 1.0, "pnl": 180.0, "small": True}
    assert r["by_side"]["숏"]["losses"] == 2 and r["by_session"]["미국장(22-05)"]["losses"] == 2
    assert r["by_regime"]["박스권"]["trades"] == 1
    assert r["held"]["win_hold_min"] == 75.0 and r["held"]["losses_that_touched_first_lock"] == 1
    assert r["held"]["win_exit_reasons"] == {"익절 잠금": 2}
    assert C.win_loss_compare([]) == {"trades": 0}


def _db(tmp_path):
    c = sqlite3.connect(str(tmp_path / "p.db"))
    c.executescript("CREATE TABLE accounts (account_id TEXT, strategy TEXT, timeframe TEXT, kind TEXT);"
                    "CREATE TABLE state (k TEXT, ts INTEGER, data TEXT);")
    eng = {}
    for i, s in enumerate(("A", "B", "C", "D")):
        for tf in ("5m", "15m"):
            c.execute("INSERT INTO accounts VALUES (?,?,?,?)", (f"{s}@{tf}", s, tf, "strategy"))
            eng[f"{s}@{tf}"] = {"wallet": 5000 + (3 - i) * 100 * (1 if tf == "5m" else 2), "bust": False}
    c.execute("INSERT INTO accounts VALUES ('RANDOM_1@5m', 'RANDOM_1', '5m', 'random')")
    eng["RANDOM_1@5m"] = {"wallet": 4900}
    c.execute("INSERT INTO state VALUES ('accounts', 1, ?)", (json.dumps({"engines": eng}),))
    c.commit()
    return c


def test_ranking_picks_top_and_bottom_without_overlap(tmp_path):
    c = _db(tmp_path)
    r = C.ranking(c, 5000.0, 0.0014, k=2, cards_fn=lambda s: [card("BTCUSDT", 1, "5m", 10)])
    assert [(p["strategy"], p["group"], p["rank"]) for p in r["picked"]] == [("A", "상위", 1), ("B", "상위", 2),
                                                                             ("D", "하위", 4), ("C", "하위", 3)]
    assert r["picked"][0]["pnl"] == 900.0 and r["picked"][0]["accounts"] == {"5m": 300.0, "15m": 600.0}
    assert r["coin_flips"]["mean_pnl"] == -100.0 and r["strategies"] == 4
    r3 = C.ranking(c, 5000.0, 0.0014, k=3, cards_fn=lambda s: [])
    assert len(r3["picked"]) == 4                                    # 4 strategies: no one twice


def test_ranking_text_compares_per_account_numbers_with_the_coin_flip_mean(tmp_path):
    from paperbot.agents import rooms as RM
    r = C.ranking(_db(tmp_path), 5000.0, 0.0014, k=2, cards_fn=lambda s: [card("BTCUSDT", 1, "5m", 10)])
    assert r["picked"][0]["pnl_per_account"] == 450.0 and r["coin_flips"]["mean_pnl_per_strategy"] == -400.0
    assert r["coin_flips"]["accounts_per_strategy"] == 4                 # 15m / 30m / 1h / 4h (5m removed 2026-10-04)
    text = RM.compose_ranking(r, None)
    # a strategy's sum is over its accounts, the coin-flip mean is one account's: both are shown per account
    assert "A: +$900 (계좌당 +$450)" in text
    assert "동전 봇 계좌당 평균 -$100 (4개 합으로 치면 -$400)" in text
