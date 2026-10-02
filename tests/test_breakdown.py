"""paperbot/breakdown.py: by coin, sessions, windows, volatility spike (descriptive, read-only)."""
import dataclasses

from paperbot import breakdown as BD
from paperbot.models import TradeRecord
from paperbot.store3 import Store3

H = 3_600_000
# 2026-10-05 is a Monday; 01:00 UTC = 10:00 KST (asia session, weekday)
MON_UTC1 = 1_791_162_000_000


def _rec(sym, tf, strat, entry, pnl, sig_ts):
    return TradeRecord(strategy_id=strat, symbol=sym, timeframe=tf, side=1, signal_ts=sig_ts, entry_time=entry,
                       entry_price=100.0, exit_time=entry + H, exit_price=101.0, exit_reason="LOCK", qty=1.0,
                       leverage=20, tier="best", margin=5.0, stop_price=99.0, tp_price=0.0, liq_price=95.0,
                       fees=0.1, funding=0.0, pnl=pnl, roe=pnl / 5.0, price_move=0.01, mae_price=99.5,
                       mfe_price=101.5, equity_after=5000 + pnl, score=0.0, context={}, strategy_style="",
                       stop_initial=99.0, lock_roe=None)


def _db(tmp_path):
    st = Store3(str(tmp_path / "p.db"))
    for aid, kind in (("A@1h", "strategy"), ("B@1h", "strategy"), ("RANDOM_1@1h", "random"), ("A@1h~c1", "copy")):
        st.add_account(aid, aid.split("@")[0], "1h", kind, 0, "v3")
    # ATR history: 60 BTC 1h signals of normal size, then one big one at the last trade's bar
    sig = []
    for k in range(60):
        sig.append({"bar_close": MON_UTC1 - (60 - k) * H, "timeframe": "1h", "strategy": "A", "symbol": "BTCUSDT",
                    "side": 1, "atr": 1.0 + 0.01 * (k % 7), "ref_price": 100.0, "ref_time": 0, "delay_ms": 0, "status": "SUBMITTED"})
    big = MON_UTC1 + 2 * H
    sig.append({**sig[0], "bar_close": big, "atr": 5.0})
    st.log_signals(sig)
    for k in range(40):                                  # A on BTC: 40 weekday-asia trades, winners
        st.trade("A@1h", _rec("BTCUSDT", "1h", "A", MON_UTC1 + k * 60_000, 10.0, MON_UTC1 - (60 - k % 60) * H - 1))
    for k in range(12):                                  # B on ETH: 12 losers on Saturday
        st.trade("B@1h", _rec("ETHUSDT", "1h", "B", MON_UTC1 + 5 * 24 * H + k * 60_000, -5.0, None))
    st.trade("A@1h", _rec("BTCUSDT", "1h", "A", big + 1000, -20.0, big - 1))       # the spike entry
    st.trade("A@1h", _rec("BTCUSDT", "1h", "A", MON_UTC1 + 1000, 7.0, MON_UTC1 - 4 * H - 1))   # k=56: atr 1.00
    st.trade("RANDOM_1@1h", _rec("BTCUSDT", "1h", "RANDOM_1", MON_UTC1, 3.0, None))
    st.trade("A@1h~c1", _rec("BTCUSDT", "1h", "A", MON_UTC1, 999.0, None))          # extras are left out
    st.commit()
    return st


def test_report_by_coin_sessions_and_volatility(tmp_path):
    st = _db(tmp_path)
    rep = BD.report(st.conn, min_n=30, min_top=10)
    assert rep["trades"] == 54
    btc = rep["by_coin"]["BTCUSDT"]
    assert btc["strategies"]["n"] == 42 and btc["strategies"]["pnl"] == 387.0
    assert btc["coin_flips"]["n"] == 1 and btc["best"][0]["account"] == "A@1h"
    assert rep["by_coin"]["ETHUSDT"]["best"][0]["n"] == 12 and rep["by_coin"]["ETHUSDT"]["strategies"]["status"] != "ok"
    prim = {(c["day"], c["session"]): c for c in rep["sessions"]["primary"]}
    assert prim[("weekday", "asia")]["n"] == 42 and prim[("weekend", "asia")]["n"] == 12
    vol = rep["volatility"]
    assert vol["spike"]["n"] == 1 and vol["spike"]["pnl"] == -20.0
    assert vol["normal"]["n"] == 1 and vol["normal"]["pnl"] == 7.0 and vol["unknown"] == 52
    b = BD.brief(rep)
    assert set(b) >= {"by_coin", "sessions", "windows", "volatility"} and len(b["by_coin"]["BTCUSDT"]["best"]) == 1


def test_vol_tag_needs_history_and_exact_signal():
    s = {("BTCUSDT", "1h"): ([1000 + k for k in range(10)], [0.01] * 10)}
    assert BD.vol_tag(s, "BTCUSDT", "1h", 1008) is None          # under 50 earlier signals
    assert BD.vol_tag(s, "ETHUSDT", "1h", 1008) is None and BD.vol_tag(s, "BTCUSDT", "1h", None) is None


def test_empty_db(tmp_path):
    st = Store3(str(tmp_path / "e.db"))
    rep = BD.report(st.conn)
    assert rep["trades"] == 0 and rep["by_coin"] == {} and rep["sessions"] is None
    assert dataclasses.is_dataclass(TradeRecord)
