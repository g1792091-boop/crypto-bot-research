"""A synthetic paper3.db / daily3.db for the debate room's tests and its dry-run measurement: the real account set of the
restarted run (36 strategies x 4 timeframes + 12 coin flips = 156 accounts), a few days of closed trades with both
leverage tiers, alerts, the account state and nightly reports. Not market data: only the shape and the size."""
import json
import os
import sqlite3

import numpy as np

from paperbot import daily3
from paperbot.agents.roster3 import STRATEGY_KO
from paperbot.models import TradeRecord
from paperbot.store3 import Store3

DAY = 86_400_000
TFS = ("15m", "30m", "1h", "4h")
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")


def make_world(folder, now_ms, days=10, per_day=150, seed=7, nightly=True, v4=False):
    """Returns {"paper": path, "daily": path, "start": ms}. ``per_day`` closed trades a day over all accounts.
    ``v4``: the paper v4 run's 331 accounts (config.v4_account_defs: the 36 x 4, DeepSeek, the reel, 15 coin flips)
    and the frozen group alert lines ('[ds200] ...': no account), for the debate room on the v4 shape."""
    rng = np.random.default_rng(seed)
    start = now_ms - int(days * DAY)
    paper, daily = os.path.join(str(folder), "paper3.db"), os.path.join(str(folder), "daily3.db")
    st = Store3(paper)
    version = "paper-v4" if v4 else "paper-v3"
    if v4:
        from paperbot.config import v4_account_defs
        defs = v4_account_defs(list(STRATEGY_KO))
        ids = [(f"{d['strategy']}@{d['timeframe']}", d["strategy"], d["timeframe"], d["kind"], d["data"]) for d in defs]
    else:
        ids = [(f"{s}@{tf}", s, tf, "strategy", None) for s in STRATEGY_KO for tf in TFS]
        ids += [(f"RANDOM_{i}@{TFS[i % 4]}", f"RANDOM_{i}", TFS[i % 4], "random", None) for i in range(12)]
    for a, s, tf, k, data in ids:
        st.add_account(a, s, tf, k, start, version, data=data)
    ids = [x[:4] for x in ids]
    st.put_state("run", start, {"taker_fee": 0.0005, "initial_equity": 5000.0, "settings": version})
    eng = {a: {"wallet": 5000.0, "bust": False} for a, *_ in ids}
    total = int(days * per_day)
    times = np.sort(rng.integers(start + 1, now_ms - 60_000, total))
    for i, t in enumerate(times):
        a, s, tf, k = ids[int(rng.integers(0, len(ids)))]
        best = rng.random() < 0.25
        lev = int(rng.choice([50, 40, 30, 20] if best else [30, 20]))
        r = float(rng.normal(0.002 if best else 0.0, 0.01))
        margin = eng[a]["wallet"] * lev / 100
        pnl = r * margin * lev
        eng[a]["wallet"] = max(11.0, eng[a]["wallet"] + pnl)
        st.trade(a, TradeRecord(
            strategy_id=s, symbol=COINS[i % 6], timeframe=tf, side=1 if i % 2 else -1, signal_ts=int(t) - 90_000,
            entry_time=int(t) - 60_000, entry_price=100.0, exit_time=int(t), exit_price=100.0,
            exit_reason="LOCK" if pnl > 0 else "SL", qty=1.0, leverage=lev, tier="best" if best else "normal",
            margin=margin, stop_price=99.0, tp_price=0.0, liq_price=90.0, fees=0.5, funding=0.0, pnl=pnl, roe=pnl / margin,
            price_move=0.0, mae_price=99.5, mfe_price=100.5, equity_after=eng[a]["wallet"], score=0.0, context={}))
    st.put_state("accounts", now_ms, {"engines": eng})
    st.alert(now_ms - 3_600_000, "WARN", "계좌 N17_KC_RSI@15m 낙폭 경고")
    st.alert(now_ms - 7_200_000, "INFO", "시작 알림")
    if v4:
        from paperbot.sigservice import DS_TIMEOUT_TEXT, REFUSED_TEXT
        st.alert(now_ms - 1_800_000, "WARN", DS_TIMEOUT_TEXT.format(secs=60, boundary=now_ms - 1_800_000, tfs="15m"))
        st.alert(now_ms - 1_700_000, "CRITICAL", REFUSED_TEXT.format(group="ds200", why="pin mismatch lib_c.py"))
        st.alert(now_ms - 1_600_000, "CRITICAL", "[F9_FVG@15m] LIQUIDATED BTCUSDT 30x lost margin 1500.00")
    st.commit()
    st.conn.close()
    d = sqlite3.connect(daily)
    d.executescript(daily3.SCHEMA)
    if nightly:
        for k in range(1, int(days)):
            day = _day(start + k * DAY)
            d.execute("INSERT INTO reports (day, ts, data) VALUES (?,?,?)",
                      (day, start + k * DAY + 3_600_000, json.dumps({"day": day, "missing_bars": 0,
                       "parity": {"accounts": len(ids), "mismatched_accounts": 0}})))
    d.commit()
    d.close()
    return {"paper": paper, "daily": daily, "start": start}


def _day(ms):
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")
