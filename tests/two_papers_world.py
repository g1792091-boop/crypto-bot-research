"""Two paper bots (owners 10-19, docs/live15-mexc-ko.md): the standard live world of tests/livebots_world.py, but MEXC
switched at SWITCH (T0 + 4h30, its start record names the second paper database) from 규칙봇 15 (-50 %, live-ac.db) to
its -35 % twin (live15-mexc.db). Bybit follows the -50 % bot all along. Made by the bots' own schema code.

paper -50 % (live-ac.db, standard):  t1 BTC +20 (T0+1h) · t2 ETH short +15 · t3 SOL -60 SL · t4 DOGE +10 · t5 LTC short +12 LOCK
                                     · t6 BCH +8 · open BTC long (T0+9h)
paper -35 % (live15-mexc.db, account since T0+1h30):
                                     u2 ETH short +15 · u3 SOL -140 SL · u4 DOGE +10 · u5 LTC short -140 SL (the -50 % bot WON
                                     it: the entry that parted) · u6 BCH +8 · u7 SOL long +6 (T0+7h30, only this bot) · open
                                     BTC long (T0+9h, its stop at -35 %)
mexc (config paper_db = live15-mexc.db; starts: LIVE_SINCE without a paper_db, SWITCH with it):
                                     ETH (t2) +1.3 · DOGE (t4) +0.9 before the switch, then LTC (u5) -4.3 · BCH (u6) +0.6 ·
                                     SOL (u7) +0.5 · open BTC long (T0+9h)
bybit: the standard one (t2, t3, t6, an extra and an old trade; open BTC long), its start record names live-ac.db.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from paperbot.executor import ExecStore
from paperbot.models import Position
from paperbot.store3 import Store3
from tests import livebots_world as W

H, MIN, DAY, T0, NOW = W.H, W.MIN, W.DAY, W.T0, W.NOW
ACCOUNT, FLIP = W.ACCOUNT, W.FLIP
SWITCH = T0 + 4 * H + 30 * MIN
P2_SINCE = T0 + H + 30 * MIN
STOP50 = {"mode": "roe", "roe": 0.5, "net": True}
STOP35 = {"mode": "roe", "roe": 0.35, "net": True}
# (name, symbol, side, entry ms, pnl, roe, strategy, timeframe, exit reason)
PAPER2 = [
    ("u2", "ETHUSDT", -1, T0 + 2 * H, 15.0, 0.0375, "N03_ADX_GC", "15m", "LOCK"),
    ("u3", "SOLUSDT", 1, T0 + 3 * H, -140.0, -0.35, "S2_ST_ROC", "30m", "SL"),
    ("u4", "DOGEUSDT", 1, T0 + 4 * H, 10.0, 0.025, "N03_ADX_GC", "1h", "LOCK"),
    ("u5", "LTCUSDT", -1, T0 + 5 * H, -140.0, -0.35, "S2_ST_ROC", "4h", "SL"),
    ("u6", "BCHUSDT", 1, T0 + 6 * H, 8.0, 0.02, "N03_ADX_GC", "15m", "LOCK"),
    ("u7", "SOLUSDT", 1, T0 + 7 * H + 30 * MIN, 6.0, 0.015, "S2_ST_ROC", "30m", "LOCK"),
]


def deploy_config(name: str) -> dict:
    """The owners' real config file (deploy/combo.live15.json / combo.live15-mexc.json): the run record the bot writes."""
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", name), encoding="utf-8") as fh:
        return json.load(fh)


def _run(path: str, config: dict, since: int) -> None:
    s = Store3(path)
    s.put_state("combo_run", since, {"version": "combo-v2", "brackets": "example", "taker_fee": 0.0005,
                                     "members": [f"{i}. {m['strategy']}" for i, m in enumerate(W.MEMBERS, 1)], "config": config})
    s.close()


def paper2_db(path: str, heartbeat: int = NOW - 2 * MIN) -> str:
    s = Store3(path)
    s.add_account(ACCOUNT, "combo", "mix", "combo", P2_SINCE, "combo-v2")
    s.add_account(FLIP, "combo", "mix", "combo_flip", P2_SINCE, "combo-v2")
    eq = 1000.0
    for _n, sym, side, t, pnl, roe, strat, tf, reason in PAPER2:
        eq += pnl
        s.trade(ACCOUNT, W._trade(sym, side, t, pnl, roe, eq, strat, tf, reason))
        from paperbot.models import SignalOutcome
        sig = W._signal(sym, tf, strat, side, t)
        s.outcome(ACCOUNT, SignalOutcome(sig, "ENTERED", "ok", t, {"fill": 100.0}))
    sig = W._signal("BTCUSDT", "1h", "S2_ST_ROC", 1, T0 + 9 * H)
    pos = Position(signal=sig, symbol="BTCUSDT", side=1, qty=0.25, entry_price=62000.0, entry_time=T0 + 9 * H, leverage=40,
                   tier="base", margin=387.0, margin_initial=387.5, stop_price=62000.0 * (1 - (0.35 / 40 - 0.0014)), tp_price=0.0,
                   liq_price=60600.0, entry_fee=7.75, funding_paid=0.5, stop_initial=62000.0 * (1 - (0.35 / 40 - 0.0014)), lock_roe=None)
    engines = {ACCOUNT: {"wallet": eq, "peak_equity": 1033.0, "max_drawdown": 0.14, "halted": False, "halt_reason": "", "bust": False,
                         "warned": [], "last_mark": {"BTCUSDT": 62100.0}, "position": asdict(pos), "pending": [], "n_trades": len(PAPER2)},
               FLIP: {"wallet": 1000.0, "peak_equity": 1000.0, "max_drawdown": 0.0, "halted": False, "halt_reason": "", "bust": False,
                      "warned": [], "last_mark": {}, "position": None, "pending": [], "n_trades": 0}}
    s.put_state("accounts", NOW - 2 * MIN, {"last_ts": NOW - 2 * MIN, "engines": engines})
    s.put_state("heartbeat", heartbeat, {"last_step": NOW - 2 * MIN, "queue": 0})
    s.close()
    _run(path, deploy_config("combo.live15-mexc.json"), P2_SINCE)
    return path


def mexc2_db(path: str, paper2: str) -> str:
    st = ExecStore(path, lock=False)
    st.put_state("meta", T0, {"mode": "mainnet", "account": ACCOUNT, "since": T0, "exchange": "mexc", "live_since": W.LIVE_SINCE})
    st.event(W.LIVE_SINCE, "INFO", "start", "시작")
    W._live(st, W._k("ETHUSDT", T0 + 2 * H), "ETHUSDT", -1, T0 + 2 * H, 1.3, 0.4)
    W._live(st, W._k("DOGEUSDT", T0 + 4 * H), "DOGEUSDT", 1, T0 + 4 * H, 0.9, 0.2)
    st.event(SWITCH, "INFO", "start", f"시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB {paper2}), mainnet", {"paper_db": paper2})
    W._live(st, W._k("LTCUSDT", T0 + 5 * H), "LTCUSDT", -1, T0 + 5 * H, -4.3, 0.2)
    W._live(st, W._k("BCHUSDT", T0 + 6 * H), "BCHUSDT", 1, T0 + 6 * H, 0.6, 0.1)
    W._live(st, W._k("SOLUSDT", T0 + 7 * H + 30 * MIN), "SOLUSDT", 1, T0 + 7 * H + 30 * MIN, 0.5, 0.1)
    open_t = {"key": W._k("BTCUSDT", T0 + 9 * H), "symbol": "BTCUSDT", "side": 1, "qty": 0.025, "leverage": 40,
              "stop": 61610.0, "stop_initial": 61610.0, "status": "open", "entry_ts": T0 + 9 * H + 15_000, "entry_price": 62012.0,
              "entry_time": T0 + 9 * H, "paper_entry": 62000.0, "mode": "mainnet", "stop_algo_id": "m1"}
    st.trade_open(open_t)
    st.equity(T0 + 9 * H, 98.0, 98.0, 0.0)
    st.put_state("bot", NOW - 4_000, {"trade": open_t, "done": [], "loops": 9100, "mode": "mainnet", "account": ACCOUNT,
                                      "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 0, "last_equity": 98.0,
                                               "peak_equity": 100.0, "trades": 5}})
    st.close()
    return path


def build(folder: str) -> dict:
    """The world's files in ``folder``: the dashboard's paths (``paper2`` included) and the -35 % bot's database."""
    p = W.build_world(folder)
    _run(p["paper"], deploy_config("combo.live15.json"), T0)
    p["paper2"] = paper2_db(os.path.join(folder, "live15-mexc.db"))
    os.remove(p["mexc_db"])
    mexc2_db(p["mexc_db"], p["paper2"])
    st = ExecStore(p["bybit_db"], lock=False)                  # Bybit's start record (this code) names the -50 % bot
    st.event(W.LIVE_SINCE + MIN, "INFO", "start", "시작", {"paper_db": p["paper"]})
    st.close()
    with open(p["mexc_config"], encoding="utf-8") as fh:
        d = json.load(fh)
    d["paper_db"] = p["paper2"]
    with open(p["mexc_config"], "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    return p


def infos(p: dict) -> list:
    return W.exec_infos(p)
