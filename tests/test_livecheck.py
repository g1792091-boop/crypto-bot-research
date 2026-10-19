"""실거래 일일 점검 (paperbot/livecheck.py, paperbot/livereplay.py): hand-made databases in the real schemas (the paper
bot's paperbot.store3, the executor's paperbot.executor.ExecStore), an injected replay and market, no network."""

import json
import os
import re
import sqlite3
import time
from dataclasses import asdict
from typing import Optional

import pytest

from paperbot import livecheck as LC
from paperbot import livereplay as LR
from paperbot.models import Signal, SignalOutcome, TradeRecord
from paperbot.notify import CRITICAL, INFO, WARN, ListNotifier, telegram_text
from paperbot.store3 import Store3

MIN = 60_000
H1 = 3_600_000
DAY = 86_400_000
W0, W1 = LC.window_of("2026-10-20")            # Tuesday 09:00 KST -> Wednesday 09:00 KST
NOW = W1 + 10 * MIN
BTC, SOL = "BTCUSDT", "SOLUSDT"


# ====================================================================== builders
def trade(entry, exit_, pnl, symbol=BTC, side=1, reason="LOCK", roe=None, entry_price=100.0, exit_price=101.0,
          strategy="F15_LON_BRK", tf="1h"):
    return TradeRecord(strategy_id=strategy, symbol=symbol, timeframe=tf, side=side, signal_ts=entry - 1,
                       entry_time=entry, entry_price=entry_price, exit_time=exit_, exit_price=exit_price,
                       exit_reason=reason, qty=1.0, leverage=40, tier="best", margin=10.0, stop_price=99.0,
                       tp_price=float("nan"), liq_price=90.0, fees=0.1, funding=0.0, pnl=pnl,
                       roe=(pnl / 10.0) if roe is None else roe, price_move=0.01, mae_price=99.5, mfe_price=101.5,
                       equity_after=1000 + pnl, score=3.0)


def sig(ts, symbol=BTC, side=1, member="F15_LON_BRK@1h#1~abc", strategy="F15_LON_BRK", tf="1h"):
    return Signal(ts=ts - 1, symbol=symbol, timeframe=tf, strategy_id=strategy, side=side, stop_price=0.0,
                  meta={"member": member})


def paper_db(path, trades=(), account=LC.ACCOUNT, signals=(), outcomes=(), position=None, config=None,
             run_ts=None, heartbeat=None, flip=()):
    s = Store3(str(path))
    for t in trades:
        s.trade(account, t)
    for t in flip:
        s.trade(LC.FLIP_ACCOUNT, t)
    for row in signals:
        s.log_signals([row])
    for o in outcomes:
        s.outcome(account, o)
    engines = {account: {"wallet": 1000.0 + sum(t.pnl for t in trades), "position": position},
               LC.FLIP_ACCOUNT: {"wallet": 1000.0, "position": None}}
    s.put_state("accounts", NOW - 2 * MIN, {"last_ts": NOW - 2 * MIN, "engines": engines})
    if config is not None:
        s.put_state("combo_run", run_ts or W0 - DAY, {"config": config, "taker_fee": 0.0005})
    if heartbeat is not None:
        s.put_state("heartbeat", heartbeat, {"last_step": heartbeat})
    s.commit()
    s.conn.close()
    return str(path)


def sigrow(bar_close, status="SUBMITTED", symbol=BTC, side=1, member="F15_LON_BRK@1h#1~abc", tf="1h", why=""):
    d = {"source": "custom", "strategy": member.split("@")[0]}
    if why:
        d["why"] = why
    return {"bar_close": bar_close, "timeframe": tf, "strategy": member, "symbol": symbol, "side": side, "atr": 1.0,
            "ref_price": 100.0, "ref_time": bar_close + 2000, "delay_ms": 2000, "status": status, "data": d}


def exec_db(path, trades=(), equity=(), halted=False, light_red=(), trade_open=None, state_ts=None, live_since=None):
    from paperbot.executor import ExecStore
    st = ExecStore(str(path), lock=False)
    for t in trades:
        st.trade_open(t)
        if t.get("exit_ts") is not None:
            st.trade_close(t["key"], t["exit_ts"], "paper 청산", t["pnl"], t)
            if t.get("fills"):
                st.fills(t["key"], t["fills"])
            if t.get("commission") is not None:
                st.trade_costs(t["key"], {"pnl": t["pnl"], "realized": t["pnl"] + t["commission"],
                                          "commission": t["commission"], "funding": t.get("funding", 0.0),
                                          "slippage": 0.0, "real_cost": t["commission"], "assumed_cost": 0.0,
                                          "ok": True})
    for ts, eq in equity:
        st.equity(ts, eq, eq, 0.0)
    for k in light_red:
        st.event(k[1], "WARN", "light_red", "신호등 빨강", {"key": k[0]})
    risk = {"halted": halted, "halt_reason": "낙폭 50%" if halted else "", "peak_equity": 120.0, "last_equity": 110.0}
    st.put_state("bot", state_ts or NOW - MIN, {"trade": trade_open, "done": [], "loops": 5, "mode": "mainnet",
                                                "account": LC.ACCOUNT, "risk": risk})
    st.put_state("meta", W0 - DAY, {"mode": "mainnet", "account": LC.ACCOUNT, "exchange": "bybit",
                                    "live_since": live_since or W0 - DAY})
    st.commit()
    st.close()
    return str(path)


def xtrade(paper_entry, symbol=BTC, side=1, entry_price=100.05, exit_price=100.95, pnl=0.5, qty=1.0,
           commission=None, fee=0.00055, entry_ts=None, exit_ts=None, key=None, fills=True):
    key = key or f"{LC.ACCOUNT}|{symbol}|{paper_entry}"
    entry_ts = entry_ts or paper_entry + 3_000
    exit_ts = exit_ts or paper_entry + H1
    t = {"key": key, "symbol": symbol, "side": side, "qty": qty, "leverage": 40, "entry_ts": entry_ts,
         "entry_price": entry_price, "stop_initial": 99.0, "exit_ts": exit_ts, "pnl": pnl}
    if fills:
        open_side, close_side = ("BUY", "SELL") if side > 0 else ("SELL", "BUY")
        t["fills"] = [{"id": paper_entry // 1000, "symbol": symbol, "side": open_side, "qty": qty,
                       "price": entry_price, "commission": qty * entry_price * fee, "commissionAsset": "USDT",
                       "realizedPnl": 0.0, "time": entry_ts},
                      {"id": paper_entry // 1000 + 1, "symbol": symbol, "side": close_side, "qty": qty,
                       "price": exit_price, "commission": qty * exit_price * fee, "commissionAsset": "USDT",
                       "realizedPnl": side * (exit_price - entry_price) * qty, "time": exit_ts}]
        t["commission"] = commission if commission is not None else qty * (entry_price + exit_price) * fee
    return t


def info(name, db, n=20, share=0.85, budget=100.0):
    return LC.ExecInfo(name=name, config="-", unit=f"paperbot-executor-{name}", db=str(db), light_n=n,
                       light_min=share, exchange=name, budget=budget, kill_file="/nonexistent/STOP")


def sources(tmp_path, paper, execs=(), shadows="/nonexistent/shadow-*.db"):
    return LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=str(paper), rule_db=str(tmp_path / "paper3.db"),
                      combo_config=str(tmp_path / "combo.json"), cache=str(tmp_path / "cache.db"),
                      shadow_glob=shadows, executors=list(execs))


def result(signals=(), trades=(), open_position=None, seeded=True, end=None, notes=()):
    return LR.ReplayResult(w0=W0, w1=W1, end=end or W1 + MIN, source="live", seeded=seeded, signals=list(signals),
                           trades=list(trades), open_position=open_position, notes=list(notes))


def rsig(bar_close, status="SUBMITTED", symbol=BTC, side=1, member="F15_LON_BRK@1h#1~abc", tf="1h", why=""):
    return {"bar_close": bar_close, "tf": tf, "strategy": member, "symbol": symbol, "side": side, "status": status,
            "why": why, "name": member.split("@")[0]}


def rtrade(entry, exit_, roe, symbol=BTC, side=1, reason="LOCK", strategy="F15_LON_BRK", tf="1h"):
    return {"entry_time": entry, "exit_time": exit_, "symbol": symbol, "side": side, "strategy": strategy, "tf": tf,
            "member": None, "reason": reason, "roe": roe, "pnl": roe * 10, "entry_price": 100.0, "exit_price": 101.0,
            "fees": 0.1, "funding": 0.0, "qty": 1.0}


CFG = {"paper_db": "x", "db": "y", "members": []}


# ====================================================================== time and windows
def test_the_checked_day_runs_from_0900_kst_to_0900_kst():
    w0, w1 = LC.window_of("2026-10-19")
    assert LC.kst(w0, "%Y-%m-%d %H:%M") == "2026-10-19 09:00" and w1 - w0 == DAY
    assert LC.default_day(w1 + 10 * MIN) == "2026-10-19"            # 09:10 KST: the day that just ended
    assert LC.default_day(w1 - 10 * MIN) == "2026-10-18"            # 08:50 KST: that day is not over yet
    assert LC.kst_day(w0) == "10/19(월)" and LC.kst_dt(w0 + 8 * H1 + 30 * MIN) == "10/19 17:30"


# ====================================================================== light and win windows
def _closed(wins, losses, start=W0 - 30 * DAY):
    out, t, i = [], start, 0
    for k in range(wins + losses):
        pnl = 1.0 if k < wins else -1.0
        out.append({"id": k + 1, "entry_time": t, "exit_time": t + H1, "pnl": pnl, "roe": pnl / 10, "symbol": BTC,
                    "side": 1})
        t += 2 * H1
        i += 1
    return out


def test_signal_light_building_green_and_red_like_the_executor():
    assert LC.light_state(_closed(10, 2), 20, 0.85)["state"] == "building"
    g = LC.light_state(_closed(17, 3), 20, 0.85)                 # exactly 85%: green (executor: wins >= need x n)
    assert g["state"] == "green" and g["wins"] == 17
    assert LC.light_state(_closed(17, 3), 20, 0.90)["state"] == "red"
    assert LC.light_state(_closed(16, 4), 20, 0.85)["state"] == "red"
    assert LC.light_state(_closed(5, 5), 0, 0.85)["state"] == "off"
    # the newest 20 by exit time: 4 old losses fall out of the window
    tr = [dict(t, pnl=-1.0) for t in _closed(4, 0, start=W0 - 60 * DAY)] + _closed(20, 0)
    assert LC.light_state(tr, 20, 0.9)["state"] == "green"
    # at a time: only trades closed by then
    assert LC.light_state(tr, 20, 0.9, at=W0 - 60 * DAY + 3 * H1)["state"] == "building"
    assert "근거 쌓는 중(12/20번" in LC.light_text(LC.light_state(_closed(12, 0), 20, 0.85))
    assert LC.light_text(g) == "신호등 초록(최근 20번 17승 85%, 기준 85%)"


def test_paper_win_windows_and_the_40_trade_checkpoint(tmp_path):
    trs = []
    t = W0 - 40 * DAY
    for k in range(45):
        pnl = -1.0 if k in (3, 10, 30, 42) else 2.0
        trs.append(trade(t, t + H1, pnl))
        t += 12 * H1
    path = paper_db(tmp_path / "p.db", trades=trs)
    conn = LC.open_ro(path)
    p = LC.paper_report(conn, W0, W1)
    conn.close()
    assert p["n"] == 45 and p["wins"] == 41
    assert p["last20"]["wins"] == 18 and p["last40"]["wins"] == 37
    assert p["first40"]["wins"] == 37                                  # 37/40 = 92.5%
    assert LC.checkpoint_line(p).startswith("- 판단(첫 40번): 37승 92.5% → 늘리기 검토")
    few = {"n": 12, "wins": 11, "rate": 11 / 12}
    line = LC.checkpoint_line(few)
    assert "거래 40번에서 88% 이상이면 늘리기 검토 / 82~88% 계속 지켜보기 / 82% 미만 멈추고 다시 생각" in line
    assert "28번 남음" in line and "11/12승 92%" in line
    # 88% or more: 36 of 40 (35 is 87.5%); 82% or more: 33 of 40 (82.5%); 32 is 80%
    for wins, word in ((36, "늘리기 검토"), (35, "계속 지켜보기"), (33, "계속 지켜보기"), (32, "멈추고 다시 생각")):
        p = {"n": 40, "wins": wins, "rate": wins / 40, "first40": {"wins": wins, "rate": wins / 40}, "last40": None}
        assert word in LC.checkpoint_line(p), (wins, word)


# ====================================================================== costs
def test_matching_by_key_then_by_coin_side_and_time():
    paper = [{"symbol": BTC, "side": 1, "entry_time": W0 + H1, "id": 1},
             {"symbol": BTC, "side": 1, "entry_time": W0 + 3 * H1, "id": 2},
             {"symbol": SOL, "side": -1, "entry_time": W0 + 5 * H1, "id": 3}]
    assert LC.match_paper({"key": f"{LC.ACCOUNT}|{BTC}|{W0 + 3 * H1}", "symbol": BTC, "side": 1,
                           "entry_ts": W0 + 9 * H1}, paper)["id"] == 2
    assert LC.match_paper({"key": "other", "symbol": BTC, "side": 1, "entry_ts": W0 + H1 + 4 * MIN}, paper)["id"] == 1
    assert LC.match_paper({"key": "other", "symbol": BTC, "side": 1, "entry_ts": W0 + H1 + 6 * MIN}, paper) is None
    assert LC.match_paper({"key": "other", "symbol": SOL, "side": 1, "entry_ts": W0 + 5 * H1}, paper) is None


def test_cost_maths_bps_fees_and_flags():
    ex = info("bybit", "-")
    paper = {"entry_price": 100.0, "exit_price": 101.0, "roe": 0.4, "strategy": "S", "tf": "1h"}
    et = xtrade(W0, entry_price=100.05, exit_price=100.95)       # long: paid 5 bps more, got 4.95 bps less
    row = LC.cost_row(ex, et, paper, et["fills"])
    assert row["entry_bps"] == pytest.approx(5.0) and row["exit_bps"] == pytest.approx(4.9505, abs=1e-3)
    assert row["fee_rate"] == pytest.approx(0.00055) and row["matched"]
    s = LC.cost_summary([row], ex.fee)
    assert s["side_bps"] == pytest.approx(4.975, abs=1e-3) and not s["flags"]
    short = xtrade(W0, side=-1, entry_price=99.9, exit_price=101.1)   # short: sold 10 bps lower, bought back higher
    r2 = LC.cost_row(ex, short, paper, short["fills"])
    assert r2["entry_bps"] == pytest.approx(10.0) and r2["exit_bps"] == pytest.approx(9.90099, abs=1e-4)
    s2 = LC.cost_summary([row, r2], ex.fee)
    assert any("미끄러짐" in f for f in s2["flags"])
    pricey = xtrade(W0, fee=0.0007)
    s3 = LC.cost_summary([LC.cost_row(ex, pricey, paper, pricey["fills"])], ex.fee)
    assert any("수수료가 0.070%로 가정 0.055%" in f for f in s3["flags"])
    mexc = info("mexc", "-")
    m = xtrade(W0, fee=0.0008)
    assert not LC.cost_summary([LC.cost_row(mexc, m, paper, m["fills"])], mexc.fee)["flags"]   # MEXC 0.08% assumed
    lone = LC.cost_row(ex, et, None, et["fills"])
    assert any("짝이 없는 실거래 1번" in f for f in LC.cost_summary([lone], ex.fee)["flags"])
    nofill = xtrade(W0, fills=False)
    r4 = LC.cost_row(ex, nofill, paper, [])
    assert r4["entry_bps"] == pytest.approx(5.0) and r4["exit_bps"] is None and r4["fee_rate"] is None


# ====================================================================== parity
def test_parity_same_missing_extra_and_different_with_causes():
    live_sig = [rsig(W0 + H1), rsig(W0 + 2 * H1, status="FILTERED", why="연구 조건을 못 읽음: oi"),
                rsig(W0 + 3 * H1, symbol=SOL)]
    rep_sig = [rsig(W0 + H1), rsig(W0 + 2 * H1), rsig(W0 + 4 * H1, symbol=SOL),
               rsig(W1 - 30 * MIN, status="WAITING", tf="1h")]
    live_sig.append(rsig(W1 - 30 * MIN, status="BROKE", tf="1h"))     # broke after the replay stopped: same
    ctx = LC.Context(live_signals=live_sig, replay_signals=rep_sig, replay_end=W1 + MIN, w0=W0)
    s = LC.compare_signals(live_sig, rep_sig, ctx)
    assert s["same"] == 2
    assert [x["t"] for x in s["different"]] == [W0 + 2 * H1] and "시장 자료를 못 읽음" in s["different"][0]["why"]
    assert [x["t"] for x in s["missing_live"]] == [W0 + 4 * H1] and s["missing_live"][0]["why"] == ""
    assert [x["t"] for x in s["extra_live"]] == [W0 + 3 * H1]
    assert LC.parity_flags(s, {}) == 2

    live_tr = [rtrade(W0 + H1, W0 + 2 * H1, 0.10), rtrade(W0 + 5 * H1, W0 + 6 * H1, 0.10),
               rtrade(W0 + 8 * H1, W0 + 9 * H1, 0.10, symbol=SOL)]
    rep_tr = [rtrade(W0 + H1, W0 + 2 * H1, 0.11),                    # 1 point of ROE apart: same
              rtrade(W0 + 5 * H1, W0 + 5 * H1 + 10 * MIN, -0.35, reason="SL"),
              rtrade(W0 + 7 * H1, W0 + 10 * H1, 0.2)]
    ctx.live_busy = [(t["entry_time"], t["exit_time"]) for t in live_tr]
    ctx.replay_busy = [(t["entry_time"], t["exit_time"]) for t in rep_tr]
    tr = LC.compare_trades(live_tr, rep_tr, ctx)
    assert tr["same"] == 1
    d = tr["different"][0]
    assert d["t"] == W0 + 5 * H1 and "청산 이유" in d["what"] and "순ROE" in d["what"]
    assert tr["missing_live"][0]["t"] == W0 + 7 * H1 and tr["missing_live"][0]["why"] == ""
    assert tr["extra_live"][0]["t"] == W0 + 8 * H1 and "다른 포지션" in tr["extra_live"][0]["why"]
    lines = LC.parity_lines({"signals": s, "trades": tr, "notes": []})
    assert lines[0] == "대조(다시 계산): 거래 1/4 같음 · 신호 2/5 같음"
    joined = "\n".join(lines)
    assert "- 거래 결과 다름 14:00 BTC 롱 F15_LON_BRK 1시간: 기록 계단 익절 +10.0% / 재계산 손절 -35.0%" in joined
    assert "- 거래 재계산에만 있음 16:00 BTC 롱 F15_LON_BRK 1시간 (재계산 계단 익절 +20.0%)" in joined
    assert "- 신호 기록에만 있음 12:00 SOL 롱 F15_LON_BRK 1시간 (진입 신호)" in joined


def test_parity_causes_restart_late_and_open_positions():
    rep = [rsig(W0 + H1 + k * 10 * MIN) for k in range(6)]
    live = [rsig(W0 + 30 * MIN), rsig(W0 + 3 * H1)]
    ctx = LC.Context(live_signals=live, replay_signals=rep + live, restarts=[W0 + 2 * H1 + 5 * MIN], w0=W0)
    s = LC.compare_signals(live, rep + live, ctx)
    assert len(s["missing_live"]) == 6 and all("다시 시작" in x["why"] for x in s["missing_live"])
    assert LC.parity_flags(s, {}) == 0
    none = {"same": 0, "different": [], "missing_live": [], "extra_live": []}
    lines = LC.parity_lines({"signals": s, "trades": none, "notes": []})
    assert any(ln.startswith("- 신호 재계산에만 있음 6개(10:00~10:50) — 10:00~10:50 페이퍼 봇 기록이 없음") for ln in lines)
    # the same silence without a restart is NOT explained (it could be a bug)
    ctx2 = LC.Context(live_signals=live, replay_signals=rep + live, w0=W0)
    assert LC.parity_flags(LC.compare_signals(live, rep + live, ctx2), {}) == 6
    # a signal the record refused as late
    ctx3 = LC.Context(live_outcomes=[{"status": "REJECTED", "reason": "late", "ts": W0 + H1, "bar_close": W0 + H1}])
    assert "늦게 받아" in LC.explain(W0 + H1, ctx3)
    # open positions: the entry is compared, the exit once both are known
    ctx4 = LC.Context(live_last=W1 + 9 * MIN, w0=W0)
    o = {"entry_time": W1 - H1, "symbol": BTC, "side": 1, "strategy": "S", "tf": "1h"}
    tr = LC.compare_trades([], [], ctx4, live_open=o, rep_open=dict(o))
    assert tr["same"] == 1 and tr["open"] == 1
    tr = LC.compare_trades([], [rtrade(W1 - H1, W1 - 30 * MIN, -0.3, reason="SL")], ctx4, live_open=o)
    assert tr["different"] and tr["different"][0]["what"] == ["청산 시각"]
    # a carried-in trade when the replay had no 09:00 snapshot
    ctx5 = LC.Context(seeded=False, w0=W0)
    tr = LC.compare_trades([rtrade(W0 - 2 * H1, W0 + H1, 0.1)], [], ctx5)
    assert "빈 계좌로 시작" in tr["extra_live"][0]["why"]


def test_a_break_awaited_since_before_0900_is_explained():
    live = [rsig(W0 + 20 * MIN, why="돌파 확인")]
    ctx = LC.Context(live_signals=live, replay_signals=[], w0=W0, prebreak={(W0 + 20 * MIN, BTC, 1)})
    s = LC.compare_signals(live, [], ctx)
    assert s["extra_live"][0]["why"] == LC.PREBREAK and LC.parity_flags(s, {}) == 0
    tr = LC.compare_trades([rtrade(W0 + 20 * MIN, W0 + H1, 0.1)], [], ctx)
    assert tr["extra_live"][0]["why"] == LC.PREBREAK


# ====================================================================== the whole morning check
def _setup(tmp_path, halted=False, paper_trades=None, fee=0.00055, flags_sig=False):
    paper_tr = paper_trades if paper_trades is not None else [
        trade(W0 - 3 * DAY, W0 - 3 * DAY + H1, 3.0),
        trade(W0 + 8 * H1, W0 + 9 * H1, 4.0, symbol=SOL, strategy="F15_ASIA_BRK", tf="30m"),
        trade(W0 + 10 * H1, W0 + 11 * H1, -2.0)]
    sigs = [sigrow(W0 + 8 * H1, symbol=SOL, member="F15_ASIA_BRK@30m#2~def", tf="30m"), sigrow(W0 + 10 * H1)]
    paper = paper_db(tmp_path / "live-ac.db", trades=paper_tr, signals=sigs, config=CFG,
                     flip=[trade(W0 + 8 * H1, W0 + 9 * H1, -4.0, symbol=SOL)])
    xb = [xtrade(W0 + 8 * H1, symbol=SOL, entry_price=100.03, exit_price=100.98, pnl=0.4, fee=fee),
          xtrade(W0 + 10 * H1, entry_price=100.02, exit_price=100.97, pnl=-0.3, fee=fee)]
    byb = exec_db(tmp_path / "bybit.db", trades=xb, equity=[(W0 - DAY, 100.0), (NOW - MIN, 100.1)], halted=halted,
                  light_red=[("k1", W0 + 3 * H1)])
    mx = exec_db(tmp_path / "mexc.db", trades=[], equity=[(W0 - DAY, 100.0)])
    src = sources(tmp_path, paper, [info("bybit", byb), info("mexc", mx, share=0.9)])
    rep = result(signals=[rsig(W0 + 8 * H1, symbol=SOL, member="F15_ASIA_BRK@30m#2~def", tf="30m"),
                          rsig(W0 + 10 * H1)] + ([rsig(W0 + 12 * H1)] if flags_sig else []),
                 trades=[rtrade(W0 + 8 * H1, W0 + 9 * H1, 0.4, symbol=SOL, strategy="F15_ASIA_BRK", tf="30m"),
                         rtrade(W0 + 10 * H1, W0 + 11 * H1, -0.2)])
    return src, rep


def test_quiet_morning_message_is_silent_and_written(tmp_path):
    src, rep = _setup(tmp_path)
    seen = {}

    def replay(cfg, a, b, bars, seed, taker):
        seen.update(cfg=cfg, a=a, b=b, taker=taker)
        return rep
    n = ListNotifier()
    out = LC.run_check(src, day="2026-10-20", now_ms=NOW, replay=replay, notifier=n)
    assert seen == {"cfg": CFG, "a": W0, "b": W1, "taker": 0.0005}       # the config the paper bot recorded
    assert out["level"] == INFO and not out["loud"] and out["sent"] is True
    assert len(n.messages) == 1 and n.messages[0][0] == INFO
    text = n.messages[0][1]
    assert text.splitlines()[0] == "📋 실거래 일일 점검 · 이상 없음"
    assert text.splitlines()[1] == "10/20(화) 09:00 ~ 10/21(수) 09:00"
    assert "대조(다시 계산): 거래 2/2 같음 · 신호 2/2 같음" in text
    assert "- 바이비트 2번 +$0.10: 진입 +2.5bps · 청산 +2.5bps · 수수료 0.055%(가정 0.055%) · 펀딩 +$0.00" in text
    assert "- MEXC: 어제 닫힌 거래 없음" in text
    assert "- 페이퍼: 거래 3번 · 2승(67%) · 손익 +$5.00 (어제 2번 1승 +$2.00)" in text
    assert "- 바이비트: 거래 2번 · 1승(50%) · 실현 +$0.10 · 잔고 $100.10 · 정상" in text
    assert "  신호등 근거 쌓는 중(3/20번, 그동안 모두 따라감) · 신호등이 거른 진입 1번" in text
    assert "- 동전 쌍둥이(참고): 거래 1번 · 0승(0%) · 손익 -$4.00" in text
    assert "37번 남음" in text and "※ 20번 미만은 표본이 작아" in text
    assert "지난 7일" not in text                                      # Wednesday 09:00: no weekly part
    assert telegram_text(INFO, text) == (INFO, text)                   # the notifier sends it as written
    conn = sqlite3.connect(src.db)
    day = conn.execute("SELECT day, level, loud, sent FROM days").fetchall()
    costs = conn.execute("SELECT exchange, symbol, entry_bps FROM costs ORDER BY entry_ts").fetchall()
    scores = dict(conn.execute("SELECT who, trades FROM scores").fetchall())
    conn.close()
    assert day == [("2026-10-20", INFO, 0, 1)]
    assert [(c[0], c[1]) for c in costs] == [("bybit", SOL), ("bybit", BTC)] and costs[0][2] == pytest.approx(3.0)
    assert scores == {"bybit": 2, "mexc": 0, "paper": 3}


def test_loud_when_parity_or_costs_flag_or_an_executor_is_halted(tmp_path):
    src, rep = _setup(tmp_path, halted=True, fee=0.0007, flags_sig=True)
    n = ListNotifier()
    out = LC.run_check(src, day="2026-10-20", now_ms=NOW, replay=lambda *a: rep, notifier=n)
    assert out["level"] == CRITICAL
    text = n.messages[0][1]
    lv, body = telegram_text(CRITICAL, text)
    assert lv == CRITICAL and body.startswith("🚨 실거래 일일 점검 · 확인할 것 3개")
    assert "- 대조에서 이유를 모르는 차이 1개" in text and "- 바이비트 실행기 멈춤" in text
    assert "- 바이비트 수수료가 0.070%로 가정 0.055%보다 높습니다" in text
    assert "- 신호 재계산에만 있음 21:00 BTC 롱 F15_LON_BRK 1시간 (진입 신호)" in text
    assert "멈춤(낙폭 50%)" in text and "지금 할 일: 멈춘 실행기는 이유를 확인한 뒤 사람이 풉니다" in text
    assert "지금 할 일: 대조 차이 전체를 개발자에게 보내 주세요" in text and "지금 할 일: 거래소 앱의 체결 내역" in text


def test_a_crash_of_the_replay_still_sends_the_rest(tmp_path, capsys):
    src, _rep = _setup(tmp_path)

    def broken(*a):
        raise KeyError("members")
    out = LC.run_check(src, day="2026-10-20", now_ms=NOW, replay=broken, notifier=ListNotifier())
    assert "대조: 못 함 — 다시 계산 중 오류가 났습니다. 개발자에게 알려 주세요" in out["text"]
    assert out["text"].endswith("자세히: KeyError: 'members'")                  # raw text only on the last line
    assert "성적표(시작부터)" in out["text"] and "KeyError" in capsys.readouterr().err


def test_dry_run_writes_nothing_and_sends_nothing(tmp_path):
    src, rep = _setup(tmp_path)
    n = ListNotifier()
    out = LC.run_check(src, day="2026-10-20", now_ms=NOW, replay=lambda *a: rep, notifier=n, dry_run=True)
    assert not n.messages and out["sent"] is None and not os.path.exists(src.db)
    assert out["text"].startswith("📋 실거래 일일 점검")


def test_binance_down_and_missing_databases(tmp_path):
    src, _rep = _setup(tmp_path)

    def down(*a):
        raise LR.MarketDown("URLError: no route")
    out = LC.run_check(src, day="2026-10-20", now_ms=NOW, replay=down, notifier=ListNotifier())
    assert "대조: 못 함 — 바이낸스에 연결하지 못해 다시 계산을 못 했습니다" in out["text"]
    assert out["text"].endswith("자세히: URLError: no route")
    assert out["text"].splitlines()[0] == "📋 실거래 일일 점검 · 대조는 못 함" and out["level"] == INFO
    gone = LC.Sources(db=str(tmp_path / "o.db"), paper_db=str(tmp_path / "none.db"), rule_db="/nonexistent",
                      combo_config="/nonexistent", shadow_glob="/nonexistent/*.db",
                      executors=[info("bybit", tmp_path / "nobybit.db"), info("mexc", tmp_path / "nomexc.db")])
    out = LC.run_check(gone, day="2026-10-20", now_ms=NOW, replay=lambda *a: result(), notifier=ListNotifier())
    t = out["text"]
    assert "대조: 못 함 — 페이퍼 봇 DB(" in t and "- 페이퍼: DB를 못 읽음" in t
    assert "- 바이비트: 기록 없음(아직 시작 전)" in t and "- MEXC: 기록 없음(아직 시작 전)" in t


def test_monday_adds_the_week_and_shadow_lines(tmp_path):
    day = "2026-10-25"                                # Sunday 09:00 -> Monday 09:00 KST
    w0, w1 = LC.window_of(day)
    paper = paper_db(tmp_path / "live-ac.db", trades=[trade(w0 - 2 * DAY, w0 - 2 * DAY + H1, 3.0),
                                                      trade(w0 + H1, w0 + 2 * H1, 2.0)], config=CFG)
    byb = exec_db(tmp_path / "bybit.db", trades=[xtrade(w0 + H1)], equity=[(w0, 100.0)])
    for name in ("shadow-b", "shadow-ac32"):
        paper_db(tmp_path / f"{name}.db", trades=[trade(w0 + H1, w0 + 2 * H1, 1.0)])
    src = sources(tmp_path, paper, [info("bybit", byb)], shadows=str(tmp_path / "shadow-*.db"))
    out = LC.run_check(src, day=day, now_ms=w1 + 10 * MIN, replay=lambda *a: result(), notifier=ListNotifier())
    t = out["text"]
    assert "지난 7일(10/19(월) 09:00 ~ 10/26(월) 09:00)" in t
    assert "- 페이퍼: 거래 2번 · 2승(100%) · 손익 +$5.00" in t
    assert "- 바이비트: 거래 1번 · 1승 · 실현 +$0.50 · 평균 진입 +5.0 / 청산 +5.0bps · 수수료 0.055%" in t
    assert "- 대조: 점검한 1일 중 이유를 모르는 차이가 있던 날 0일" in t
    assert "- 그림자 B 안정형(참고): 거래 1번 · 1승(100%) · 손익 +$1.00" in t
    assert "- 그림자 32개(참고): 거래 1번" in t


def test_show_prints_the_stored_day(tmp_path, capsys):
    src, rep = _setup(tmp_path, flags_sig=True)
    LC.run_check(src, day="2026-10-20", now_ms=NOW, replay=lambda *a: rep, notifier=ListNotifier())
    assert LC.main(["show", "--db", src.db, "--day", "2026-10-20"]) == 0
    got = capsys.readouterr().out
    assert got.startswith("2026-10-20 [CRITICAL] 텔레그램 보냄") and "signal missing_live" in got


def test_command_line_dry_run_without_replay(tmp_path, capsys):
    src, _rep = _setup(tmp_path)
    (tmp_path / "combo.json").write_text(json.dumps({"db": src.paper_db, "paper_db": str(tmp_path / "paper3.db")}))
    assert LC.main(["run", "--day", "2026-10-20", "--dry-run", "--no-replay", "--db", src.db,
                    "--combo-config", str(tmp_path / "combo.json"), "--shadows", "/nonexistent/*.db"]) == 0
    got = capsys.readouterr().out
    assert got.startswith("[INFO]\n📋 실거래 일일 점검 · 대조는 못 함")
    assert "대조: 못 함 — 이번에는 다시 계산을 건너뜀(--no-replay)" in got and "- 페이퍼: 거래 3번" in got
    assert not os.path.exists(src.db)


def test_executor_configs_are_read_as_json_with_fallbacks(tmp_path):
    good = tmp_path / "executor.json"
    good.write_text(json.dumps({"exchange": "bybit", "db": "/x/b.db", "signal_light_n": 20,
                                "signal_light_min_win": 0.85, "budget_usd": 100, "account": LC.ACCOUNT,
                                "risk": {"kill_file": "/var/lib/paperbot/STOP", "max_drawdown_pct": 0.5}}))
    got = LC.load_executors((("bybit", str(good), "u1", "/fb/b.db", 20, 0.85),
                             ("mexc", str(tmp_path / "missing.json"), "u2", "/fb/m.db", 20, 0.9)))
    assert (got[0].db, got[0].light_n, got[0].light_min, got[0].budget, got[0].fee) == ("/x/b.db", 20, 0.85, 100.0,
                                                                                        0.00055)
    assert got[1].problem
    assert (got[1].db, got[1].light_min, got[1].fee, got[1].label) == ("/fb/m.db", 0.9, 0.0008, "MEXC")


# ====================================================================== the replay's market (no network)
class FakeREST:
    """BinanceREST's endpoints over a fixed series; counts calls."""

    def __init__(self, n_min=5000, t0=W0 - 3 * DAY):
        self.t0, self.n = t0, n_min
        self.calls = []

    def klines(self, symbol, interval, start_time=None, limit=1500):
        self.calls.append(("klines", symbol, interval, start_time))
        ms = LR.IV_MS[interval]
        t = max(start_time, self.t0)
        t += (-t) % ms
        out = []
        while len(out) < limit and t < self.t0 + self.n * MIN:
            out.append([t, "1", "2", "0.5", "1.5", "10", t + ms - 1])
            t += ms
        return out

    def funding_rates(self, symbol, start_time=None, limit=1000):
        self.calls.append(("funding", symbol))
        return [{"fundingTime": t, "fundingRate": "0.0001"} for t in range(self.t0, self.t0 + self.n * MIN, 8 * H1)
                if t >= start_time][:limit]

    def flow_stats(self, dataset, symbol, period, start_time=None, end_time=None, limit=500):
        self.calls.append(("oi", symbol))
        first = start_time - start_time % 300_000 + 300_000
        return [{"timestamp": t, "sumOpenInterest": "5"} for t in range(first, end_time, 300_000)][:limit]


def test_binance_market_paginates_and_caches_between_nights(tmp_path):
    rest = FakeREST()
    now = rest.t0 + 5000 * MIN + 10 * MIN
    m = LR.BinanceMarket(rest=rest, cache=str(tmp_path / "c.db"), pause=0, now_ms=lambda: now)
    rows = m.klines(BTC, "1m", rest.t0, rest.t0 + 4000 * MIN)
    assert len(rows) == 4000 and rows[0][0] == rest.t0 and rows[-1][0] == rest.t0 + 3999 * MIN
    first = len(rest.calls)
    assert first == 3                                                   # 1500 + 1500 + 1000
    again = m.klines(BTC, "1m", rest.t0 + 1000 * MIN, rest.t0 + 4500 * MIN)
    assert len(again) == 3500 and len(rest.calls) == first + 1           # only the new 500 minutes fetched
    assert len(m.funding(BTC, rest.t0, rest.t0 + 2 * DAY)) == 6
    assert len(m.oi(BTC, rest.t0, rest.t0 + 2 * DAY)) == 575              # 576 five-minute points, paged by 500
    m.close()
    assert LR.missing_runs([0, 60_000, 180_000], 0, 300_000, MIN) == [(120_000, 180_000), (240_000, 300_000)]


def test_binance_market_failure_is_market_down(tmp_path):
    from paperbot.binance import BinanceError

    class Down:
        def klines(self, *a, **k):
            raise BinanceError("gave up after retries (URLError)")
    m = LR.BinanceMarket(rest=Down(), cache=None, pause=0)
    with pytest.raises(LR.MarketDown):
        m.klines(BTC, "1h", W0, W1)


def test_the_replay_reads_the_paper_bots_own_records(tmp_path):
    """signals_of / outcomes_of / trades_of on the paper bot's schema (the record side of the comparison)."""
    s = Store3(str(tmp_path / "r.db"))
    s.log_signals([sigrow(W0, status="SUBMITTED"), sigrow(W0 + H1, status="FILTERED", why="끈 구간: hr=5"),
                   sigrow(W1, status="WAITING"), sigrow(W1 + H1)])
    sg = sig(W0 + H1)
    s.outcome(LC.ACCOUNT, SignalOutcome(signal=sg, status="ENTERED", reason="", step_ts=W0 + H1))
    s.trade(LC.ACCOUNT, trade(W0 + H1, W0 + 2 * H1, 1.0))
    s.commit()
    got = LR.signals_of(s.conn, W0, W1)
    assert [(x["bar_close"], x["status"], x["why"]) for x in got] == [
        (W0 + H1, "FILTERED", "끈 구간: hr=5"), (W1, "WAITING", "")]
    outs = LR.outcomes_of(s.conn, LC.ACCOUNT)
    assert outs[0]["member"] == "F15_LON_BRK@1h#1~abc" and outs[0]["bar_close"] == W0 + H1
    tr = LR.trades_of(s.conn, LC.ACCOUNT, outs)
    assert tr[0]["member"] == "F15_LON_BRK@1h#1~abc" and tr[0]["reason"] == "LOCK" and tr[0]["roe"] == 0.1
    assert asdict(sg)["meta"] == {"member": "F15_LON_BRK@1h#1~abc"}
    s.conn.close()


def test_no_stale_numbers_and_no_order_code_in_the_new_modules():
    import re
    for mod in (LC, LR):
        src = open(mod.__file__, encoding="utf-8").read()
        assert not re.search(r"^\s*(from\s+\S*\b(executor|testnet|mainnet|risk|bybit|mexc)\b\s+import|"
                             r"import\s+\S*\b(executor|testnet|mainnet|bybit|mexc)\b|"
                             r"from\s+\.+\s+import\s+.*\b(executor|testnet|mainnet|risk|bybit|mexc)\b)", src, re.M)
        assert "executor.env" not in src


# ====================================================================== 실시간 감시 (watch)
T = W0 + 5 * H1                      # "now" of the watch tests


class Units:
    """systemctl as the watcher sees it: name -> (ActiveState, UnitFileState)."""

    def __init__(self, **states):
        self.states = states

    def __call__(self, unit):
        return self.states.get(unit, ("active", "enabled"))


class FailingNotifier(ListNotifier):
    def __init__(self):
        super().__init__()
        self.fail = True

    def send(self, level, text):
        if self.fail:
            return False
        super().send(level, text)
        return True


def position(entry, symbol=BTC, side=1):
    sig_ = {"strategy_id": "F15_LON_BRK", "timeframe": "1h"}
    return {"symbol": symbol, "side": side, "entry_time": entry, "signal": sig_}


def rule_db(path, last_bar):
    s = Store3(str(path))
    s.live_bars([{"ts": last_bar, "symbol": BTC, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                  "processed_at": last_bar + MIN + 1000}])
    s.commit()
    s.conn.close()
    return str(path)


def watch_setup(tmp_path, entry=T - 5 * MIN, past=(), x_trades=(), hb=T - MIN, bar=T - 2 * MIN, bybit=None,
                halted=False, trade_open=None, state_ts=T - MIN, live_since=W0 - DAY):
    paper = paper_db(tmp_path / "live-ac.db", trades=list(past), heartbeat=hb,
                     position=position(entry) if entry else None)
    rule = rule_db(tmp_path / "paper3.db", bar)
    byb = bybit or exec_db(tmp_path / "bybit.db", trades=list(x_trades), halted=halted, trade_open=trade_open,
                           state_ts=state_ts, live_since=live_since)
    src = LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=paper, rule_db=rule, combo_config="-",
                     executors=[info("bybit", byb)])
    src.executors[0].unit = "paperbot-executor"
    return src


def fresh(src, now):
    """The paper bot and the rule bot still running at ``now``."""
    conn = sqlite3.connect(src.paper_db)
    conn.execute("INSERT OR REPLACE INTO state VALUES ('heartbeat', ?, '{}')", (now - MIN,))
    conn.commit()
    conn.close()
    conn = sqlite3.connect(src.rule_db)
    conn.execute("INSERT OR IGNORE INTO live_bars (ts, symbol, open, high, low, close, processed_at) "
                 "VALUES (?, 'BTCUSDT', 1, 1, 1, 1, ?)", (now - 2 * MIN, now - MIN))
    conn.commit()
    conn.close()


def msgs(n, start):
    return [(lv, m) for lv, m in n.messages if m.startswith(start)]


def keys(out, event="fire"):
    return [k for e, k, _lvl, _t in out if e == event]


def _set_bot(path, **kw):
    conn = sqlite3.connect(path)
    ts, data = conn.execute("SELECT ts, data FROM state WHERE k = 'bot'").fetchone()
    data = json.loads(data)
    risk = data["risk"]
    for k, v in kw.items():
        if k in ("ts",):
            ts = v
        elif k == "trade":
            data["trade"] = v
        else:
            risk[k] = v
    conn.execute("UPDATE state SET ts = ?, data = ? WHERE k = 'bot'", (ts, json.dumps(data)))
    conn.commit()
    conn.close()


def test_watch_a_paper_entry_not_followed_alarms_once_and_rearms(tmp_path):
    src = watch_setup(tmp_path)
    n = ListNotifier()
    key = f"{LC.ACCOUNT}|{BTC}|{T - 5 * MIN}"
    out = LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert keys(out) == [f"follow:bybit:{key}"]
    level, text = msgs(n, "실거래가 페이퍼를")[0]
    assert level == CRITICAL and text.startswith("실거래가 페이퍼를 따라가지 않았습니다 · 바이비트")
    assert "페이퍼 진입 13:55 BTC 롱 F15_LON_BRK 1시간 (5분 지남)" in text
    assert "신호등 근거 쌓는 중(0/20번, 그동안 모두 따라감) · 멈춤 아님" in text
    assert "실행기 기록: 이 진입에 대한 기록 없음" in text
    assert text.splitlines()[-1].startswith("지금 할 일: 거래소 앱에서 포지션을 확인하고 sudo journalctl -u "
                                            "paperbot-executor -n 50")
    assert telegram_text(CRITICAL, text)[1].startswith("🚨 실거래가 페이퍼를 따라가지 않았습니다")
    assert LC.run_watch(src, now_ms=T + 2 * MIN, notifier=n, units=Units(), exists=lambda p: False) == []
    assert len(msgs(n, "실거래가 페이퍼를")) == 1                          # once per condition
    # the executor followed after all: the condition clears without a message
    from paperbot.executor import ExecStore
    st = ExecStore(src.executors[0].db, lock=False)
    st.trade_open({"key": key, "symbol": BTC, "side": 1, "qty": 1.0, "leverage": 40, "entry_ts": T})
    st.commit()
    st.close()
    out = LC.run_watch(src, now_ms=T + 4 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert keys(out, "clear") == [f"follow:bybit:{key}"] and len(msgs(n, "실거래가 페이퍼를")) == 1
    conn = sqlite3.connect(src.db)
    assert conn.execute("SELECT active FROM watch WHERE key = ?", (f"follow:bybit:{key}",)).fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM seen").fetchone() == (3,)
    conn.close()


def test_watch_follow_is_quiet_when_the_executor_may_skip_the_entry(tmp_path):
    reds = [trade(W0 - 30 * DAY + k * H1, W0 - 30 * DAY + k * H1 + 30 * MIN, -1.0 if k < 5 else 1.0)
            for k in range(20)]                                       # 15/20 = 75% < 85%: red
    cases = {
        "red light": dict(past=reds),
        "halted": dict(halted=True),
        "too fresh": dict(entry=T - 2 * MIN),
        "before the executor went live": dict(live_since=T - 2 * MIN),
    }
    for name, kw in cases.items():
        d = tmp_path / name.replace(" ", "_")
        d.mkdir()
        src = watch_setup(d, **kw)
        out = LC.run_watch(src, now_ms=T, notifier=ListNotifier(), units=Units(), exists=lambda p: False)
        assert not [k for k in keys(out) if k.startswith("follow:")], name
    (tmp_path / "x").mkdir()
    src = watch_setup(tmp_path / "x")
    out = LC.run_watch(src, now_ms=T, notifier=ListNotifier(), units=Units(), exists=lambda p: True)  # kill file
    assert not keys(out)
    out = LC.run_watch(src, now_ms=T, notifier=ListNotifier(), exists=lambda p: False,
                       units=Units(**{"paperbot-executor": ("inactive", "disabled")}))   # stopped on purpose
    assert not keys(out)
    greens = [trade(W0 - 30 * DAY + k * H1, W0 - 30 * DAY + k * H1 + 30 * MIN, 1.0) for k in range(20)]
    (tmp_path / "g").mkdir()
    src = watch_setup(tmp_path / "g", past=greens)
    n = ListNotifier()
    out = LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert keys(out) == [f"follow:bybit:{LC.ACCOUNT}|{BTC}|{T - 5 * MIN}"]
    assert "신호등 초록(최근 20번 20승 100%, 기준 85%)" in msgs(n, "실거래가 페이퍼를")[0][1]


def test_watch_a_closed_paper_trade_and_the_executors_own_words(tmp_path):
    entry = T - 20 * MIN
    src = watch_setup(tmp_path, entry=None, past=[trade(entry, T - 10 * MIN, 1.0)])
    from paperbot.executor import ExecStore
    st = ExecStore(src.executors[0].db, lock=False)
    st.event(entry + 200_000, "WARN", "late", "paper 진입이 200초 전이라 따라 하지 않습니다",
             {"key": f"{LC.ACCOUNT}|{BTC}|{entry}"})
    st.commit()
    st.close()
    n = ListNotifier()
    LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    text = msgs(n, "실거래가 페이퍼를")[0][1]
    assert "(20분 지남, 페이퍼는 이미 청산)" in text
    assert "실행기 기록: paper 진입이 200초 전이라 따라 하지 않습니다" in text
    # an hour later the trade is out of the window: cleared silently
    fresh(src, T + H1)
    _set_bot(src.executors[0].db, ts=T + H1 - MIN)
    out = LC.run_watch(src, now_ms=T + H1, notifier=n, units=Units(), exists=lambda p: False)
    assert keys(out, "clear") == [f"follow:bybit:{LC.ACCOUNT}|{BTC}|{entry}"]
    assert len(msgs(n, "실거래가 페이퍼를")) == 1


def test_watch_open_position_without_a_stop_and_a_stale_executor(tmp_path):
    t = {"key": "k1", "symbol": SOL, "side": -1, "qty": 0.5, "status": "open", "entry_ts": T - 3 * MIN,
         "stop_algo_id": None}
    src = watch_setup(tmp_path, entry=None, trade_open=t, state_ts=T - 15 * MIN)
    n = ListNotifier()
    out = LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert sorted(keys(out)) == ["stale:bybit", "stop:bybit:k1"]
    msgs = dict((m.split("\n")[0], m) for _l, m in n.messages)
    assert "바이비트 실거래 포지션에 손절 기록이 없습니다" in msgs
    assert "SOL 숏 0.5 · 진입 13:57, 3분 전 · 상태 open" in msgs["바이비트 실거래 포지션에 손절 기록이 없습니다"]
    stale = msgs["바이비트 실행기가 10분 넘게 기록을 남기지 않습니다"]
    assert "마지막 기록: 13:45, 15분 전 · 서비스 상태: 켜져 있음" in stale
    assert "sudo systemctl status paperbot-executor" in stale
    # the stop is recorded and the state is fresh again: both clear, each with a silent line
    _set_bot(src.executors[0].db, ts=T + MIN, trade=dict(t, stop_algo_id="a1"))
    fresh(src, T + 2 * MIN)
    out = LC.run_watch(src, now_ms=T + 2 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert sorted(keys(out, "clear")) == ["stale:bybit", "stop:bybit:k1"]
    assert sorted(m for lv, m in n.messages[2:]) == ["✅ 바이비트 실행기 기록이 다시 들어옵니다",
                                                     "✅ 바이비트 포지션의 손절이 기록됐거나 포지션이 닫혔습니다"]
    assert all(lv == INFO for lv, _m in n.messages[2:])
    # stale again: re-armed, sent again
    fresh(src, T + 20 * MIN)
    out = LC.run_watch(src, now_ms=T + 20 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert keys(out) == ["stale:bybit"]
    # an executor stopped on purpose (disabled and inactive) is not stale
    fresh(src, T + 40 * MIN)
    out = LC.run_watch(src, now_ms=T + 40 * MIN, notifier=n, exists=lambda p: False,
                       units=Units(**{"paperbot-executor": ("inactive", "disabled")}))
    assert keys(out, "clear") == ["stale:bybit"]


def test_watch_paper_heartbeat_and_rule_bars(tmp_path):
    src = watch_setup(tmp_path, entry=None, hb=T - 12 * MIN, bar=T - 7 * MIN)
    n = ListNotifier()
    out = LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert sorted(keys(out)) == ["paper_stale", "rule_bars"]
    texts = "\n".join(m for _l, m in n.messages)
    assert "페이퍼 봇이 10분 넘게 아무것도 쓰지 않습니다\n마지막 기록: 13:48, 12분 전" in texts
    assert "규칙봇 1분봉이 5분 넘게 들어오지 않습니다\n마지막 1분봉: 13:54, 6분 전" in texts
    # an unreadable paper database: still loud (no heartbeat), the follow checks are not judged
    os.remove(src.paper_db)
    gone = LC.Sources(db=str(tmp_path / "w2.db"), paper_db=src.paper_db, rule_db=src.rule_db, executors=src.executors)
    out = LC.run_watch(gone, now_ms=T, notifier=ListNotifier(), units=Units(), exists=lambda p: False)
    assert "paper_stale" in keys(out)


def test_rule_bars_wait_while_the_restarted_rule_bot_catches_up(tmp_path):
    """An update restarts paperbot-live3 (owners 10-19: 🚨 at 14:05, ✅ at 14:07): no alarm in its first 10 minutes
    unless its newest bar is 15 minutes old; an alarm already sent is neither repeated nor cleared meanwhile."""
    def run(src, now, up, units=None):
        return LC.run_watch(src, now_ms=now, notifier=ListNotifier(), units=units or Units(),
                            exists=lambda p: False, started=lambda u: up if u == "paperbot-live3" else None)

    for d in "abc":
        (tmp_path / d).mkdir()
    src = watch_setup(tmp_path / "a", entry=None, bar=T - 7 * MIN)
    assert "rule_bars" not in keys(run(src, T, T - 3 * MIN))                  # restarted 3 min ago: catching up
    assert "rule_bars" in keys(run(src, T, T - 12 * MIN))                     # 12 min ago: loud
    assert keys(run(src, T + MIN, T), "clear") == []                          # restarted again: no false ✅
    late = watch_setup(tmp_path / "b", entry=None, bar=T - 17 * MIN)
    assert "rule_bars" in keys(run(late, T, T - 3 * MIN))                     # 16 min without a bar: loud anyway
    starting = watch_setup(tmp_path / "c", entry=None, bar=T - 7 * MIN)
    out = run(starting, T, T - 3 * MIN, Units(**{"paperbot-live3": ("activating", "enabled")}))
    assert "rule_bars" in keys(out)                                           # not running (a crash loop): loud


def test_watch_drawdown_rearms_below_20_and_good_news_once(tmp_path):
    src = watch_setup(tmp_path, entry=None)
    db = src.executors[0].db
    n = ListNotifier()

    def run(now):
        fresh(src, now)
        return LC.run_watch(src, now_ms=now, notifier=n, units=Units(), exists=lambda p: False)
    _set_bot(db, ts=T, last_equity=74.0, peak_equity=100.0)
    assert keys(run(T)) == ["dd:bybit"]
    assert n.messages[-1][1].startswith("바이비트 실거래 잔고가 최고점보다 26% 줄었습니다\n잔고 $74.00 · 최고 $100.00\n50%가 되면")
    _set_bot(db, ts=T + 2 * MIN, last_equity=78.0)                    # 22%: still the same alarm, nothing sent
    assert run(T + 2 * MIN) == [] and len(n.messages) == 1
    _set_bot(db, ts=T + 4 * MIN, last_equity=82.0)                    # 18%: cleared, re-armed
    assert keys(run(T + 4 * MIN), "clear") == ["dd:bybit"] and n.messages[-1][0] == INFO
    _set_bot(db, ts=T + 6 * MIN, last_equity=74.0)
    assert keys(run(T + 6 * MIN)) == ["dd:bybit"] and len(n.messages) == 3
    _set_bot(db, ts=T + 8 * MIN, last_equity=151.0, peak_equity=151.0)
    out = run(T + 8 * MIN)
    assert keys(out) == ["good:bybit:0.5"] and keys(out, "clear") == ["dd:bybit"]
    good = [m for lv, m in n.messages if m.startswith("🎉")]
    assert good == ["🎉 바이비트 실거래 잔고가 처음으로 시작보다 +50%가 됐습니다\n잔고 $151.00 (시작 $100.00)"]
    assert [lv for lv, m in n.messages if m.startswith("🎉")] == [INFO]
    _set_bot(db, ts=T + 10 * MIN, last_equity=120.0, peak_equity=151.0)
    _set_bot(db, ts=T + 12 * MIN, last_equity=160.0, peak_equity=160.0)
    assert keys(run(T + 12 * MIN)) == []                              # once only, even after a dip
    _set_bot(db, ts=T + 14 * MIN, last_equity=205.0, peak_equity=205.0)
    assert keys(run(T + 14 * MIN)) == ["good:bybit:1"]


def test_watch_unsent_alarm_is_retried_and_dry_run_writes_nothing(tmp_path):
    src = watch_setup(tmp_path, entry=None, hb=T - 30 * MIN)
    n = FailingNotifier()
    LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    n.fail = False
    out = LC.run_watch(src, now_ms=T + 2 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert keys(out) == ["paper_stale"] and len(n.messages) == 1          # Telegram refused it first: sent now
    (tmp_path / "d").mkdir()
    src2 = watch_setup(tmp_path / "d", entry=None, hb=T - 30 * MIN)
    out = LC.run_watch(src2, now_ms=T, dry_run=True, units=Units(), exists=lambda p: False)
    assert keys(out) == ["paper_stale"] and not os.path.exists(src2.db)


def test_the_morning_check_names_the_paper_bots_stopped_span_from_the_watch(tmp_path):
    src, _rep = _setup(tmp_path)
    conn = LC.open_out(src.db)
    hb = W0 + 3 * H1
    for k in range(0, 31, 2):                                         # 12:00 .. 12:30 heartbeat stuck at 12:00
        conn.execute("INSERT INTO seen VALUES (?,?,?,?,?)", (hb + k * MIN, hb, hb, hb, "{}"))
    conn.execute("INSERT INTO seen VALUES (?,?,?,?,?)", (hb + 32 * MIN, hb + 31 * MIN, hb, hb, "{}"))
    conn.commit()
    conn.close()
    assert LC.down_spans(src.db, W0, W1) == [(hb, hb + 31 * MIN)]
    rep = result(signals=[rsig(W0 + 8 * H1, symbol=SOL, member="F15_ASIA_BRK@30m#2~def", tf="30m"),
                          rsig(W0 + 10 * H1), rsig(hb + 15 * MIN)],
                 trades=[rtrade(W0 + 8 * H1, W0 + 9 * H1, 0.4, symbol=SOL, strategy="F15_ASIA_BRK", tf="30m"),
                         rtrade(W0 + 10 * H1, W0 + 11 * H1, -0.2)])
    out = LC.run_check(src, day="2026-10-20", now_ms=NOW, replay=lambda *a: rep, notifier=ListNotifier())
    assert out["level"] == INFO
    assert "- 신호 재계산에만 있음 12:15 BTC 롱 F15_LON_BRK 1시간 (진입 신호) — 그때 페이퍼 봇이 멈춰 있었음(12:00~12:31, 감시 기록)" \
        in out["text"]


def test_watch_command_line_dry_run(tmp_path, capsys):
    src = watch_setup(tmp_path, entry=None, hb=W0 - 30 * DAY)
    (tmp_path / "combo.json").write_text(json.dumps({"db": src.paper_db, "paper_db": src.rule_db}))
    assert LC.main(["watch", "--dry-run", "--db", src.db, "--combo-config", str(tmp_path / "combo.json")]) == 0
    got = capsys.readouterr().out
    assert "[fire CRITICAL] paper_stale\n페이퍼 봇이 10분 넘게 아무것도 쓰지 않습니다" in got


# ====================================================================== 3부: 손실 카드, 기대 이탈, 멈춤 요약, 서버 상태
EXP = {"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"], "break_even_win": 0.776,
       "config_sha256": "x",
       "overall": {"fit": {"rolling20_wins": {"p5": 16}, "rolling40_wins": {"p5": 33}, "streaks": {"longest": 3}},
                   "honest": {"rolling20_wins": {"p5": 12}, "rolling40_wins": {"p5": 25}, "streaks": {"longest": 5}}},
       "strategies": {"F15_LON_BRK": {"type": "돌파", "win": 0.9, "honest_2025_26": [40, 0.8],
                                      "loss_roe_median": -0.45, "loss_roe_worst": -0.6, "hours_to_stop_median": 1.5,
                                      "hours_to_stop_p90": 6.0, "by_reg5": {"0": [50, 0.92], "4": [30, 0.70]},
                                      "by_sym": {"0": [60, 0.9], "2": [3, 0.3]}}},
       "members": {"0": {"strategy": "F15_LON_BRK", "tf": "1h", "stop": "atr3"}}}
MEMBER = "F15_LON_BRK@1h#1~abc"


def entered(entry, symbol=BTC, side=1, reg5=0, hr=14, rstop=("atr", 3.0)):
    meta = {"member": MEMBER, "member_order": 1, "rdims": {"reg5": reg5, "hr": hr, "sym": 0}, "rstop": list(rstop)}
    return SignalOutcome(signal=Signal(ts=entry - 1, symbol=symbol, timeframe="1h", strategy_id="F15_LON_BRK",
                                       side=side, stop_price=0.0, meta=meta), status="ENTERED", reason="",
                         step_ts=entry)


def loss(entry, exit_, roe=-0.4, symbol=BTC, side=1, mfe=100.4):
    t = trade(entry, exit_, roe * 10, symbol=symbol, side=side, reason="SL", roe=roe, exit_price=99.0)
    t.stop_initial, t.mfe_price = 99.0, mfe
    return t


def card_setup(tmp_path, trades, outcomes, x_trades=(), red=(), now=None, exp=EXP):
    paper = paper_db(tmp_path / "live-ac.db", trades=trades, outcomes=outcomes, heartbeat=(now or T) - MIN)
    rule = rule_db(tmp_path / "paper3.db", (now or T) - 2 * MIN)
    byb = exec_db(tmp_path / "bybit.db", trades=list(x_trades), state_ts=(now or T) - MIN)
    mx = exec_db(tmp_path / "mexc.db", light_red=list(red), state_ts=(now or T) - MIN)
    (tmp_path / "exp.json").write_text(json.dumps(exp))
    return LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=paper, rule_db=rule, combo_config="-",
                      expected=str(tmp_path / "exp.json"),
                      executors=[info("bybit", byb), info("mexc", mx, share=0.9)])


def test_reference_member_keys_count_from_zero_and_must_agree():
    exp = LC.load_expected()
    assert exp is not None and exp["members"]["0"]["strategy"] == "F12_MSS_DISP"
    assert LC.ref_member(exp, 1, "F12_MSS_DISP", "1h")["stop"] == "atr2"      # member_order 1 = members["0"]
    assert LC.ref_member(exp, 1, "F12_MSS_DISP", "30m") is None
    assert LC.weak_cell([30, 0.70], 0.9, 0.776) and LC.weak_cell([30, 0.81], 0.9, 0.776)
    assert not LC.weak_cell([30, 0.85], 0.9, 0.776) and not LC.weak_cell([3, 0.3], 0.9, 0.776)


def test_loss_card_contents_against_the_reference(tmp_path):
    entry, exit_ = T - 2 * H1, T - 30 * MIN
    key = f"{LC.ACCOUNT}|{BTC}|{entry}"
    src = card_setup(tmp_path, [trade(W0 - DAY, W0 - DAY + H1, 2.0), loss(entry, exit_, -0.4)], [entered(entry)],
                     x_trades=[xtrade(entry, entry_price=100.05, exit_price=98.97, pnl=-1.05, exit_ts=exit_ + 3000)],
                     red=[(key, entry + 2000)])
    n = ListNotifier()
    out = LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert [k for e, k, _l, _t in out if e == "card"] == [key]
    level, text = msgs(n, "❌ 청산")[0]
    assert level == INFO and text.split("\n") == [
        "❌ 청산 · BTC 롱 · 순ROE -40.0%",
        "F15_LON_BRK 1시간 · 돌파 · 세팅 1번 · 1.5시간 보유",
        "진입 12:00 → 손절 13:30 · 손절 atr3 거리 1.00% · 먼저 +16.0%까지",
        "장세 강상승 · 14시 · 백테스트 승률 90.0% (처음 보는 기간 80%)",
        "손실 보통 -45% / 최악 -60% · 손절까지 보통 1.5시간",
        "이 장세 92%(50번) · 이 코인 90%(60번)",
        "연속 손실 1번째 (백테스트 최장 3번, 처음 보는 기간 5번)",
        "바이비트 -$1.05 (-42.0%) · 진입 +5.0 / 청산 +3.0bps",
        "MEXC     ⛔ 신호등이 막음",
        "판정: 정상 범위 손실"]
    assert telegram_text(INFO, text) == (INFO, text)
    assert LC.run_watch(src, now_ms=T + 2 * MIN, notifier=n, units=Units(), exists=lambda p: False) == []
    conn = sqlite3.connect(src.db)
    row = conn.execute("SELECT label, loud, streak, sent, data FROM loss_cards").fetchone()
    conn.close()
    assert row[:4] == ("정상 범위 손실", 0, 1, 1)
    card = json.loads(row[4])
    assert card["reg5_cell"] == [50, 0.92] and card["executors"][1]["status"] == "blocked"


def test_card_labels_and_when_a_card_is_loud():
    t = {"id": 2, "entry_time": T - H1, "exit_time": T, "symbol": SOL, "side": 1, "strategy": "F15_LON_BRK",
         "tf": "1h", "pnl": -4.0, "roe": -0.4, "reason": "SL", "entry_price": 100.0, "leverage": 30,
         "stop_initial": 99.0, "mfe_price": 100.1}
    prev = {"id": 1, "entry_time": T - 3 * H1, "exit_time": T - 2 * H1, "pnl": -1.0}
    meta = {"member_order": 1, "rdims": {"reg5": 4, "hr": 3}}
    c = LC.build_card(t, meta, [t], EXP, [])
    assert c["label"] == "백테스트에서도 약한 자리" and c["weak"] == ["장세"] and not c["loud"]   # 70% in 횡보
    assert "→ 백테스트에서도 약한 자리" in LC.card_text(c) and "지금 할 일" not in LC.card_text(c)
    c = LC.build_card(t, meta, [prev, t], EXP, [])
    assert c["label"] == "연속 손실 2번째" and c["loud"]
    c = LC.build_card(dict(t, roe=-0.7), meta, [t], EXP, [])
    assert c["label"] == "평소보다 큰 손실" and c["loud"]
    gap = [{"status": "followed", "label": "바이비트", "pnl": -5.0, "entry_bps": 14.0, "exit_bps": 1.0,
            "exit_ts": T}]
    c = LC.build_card(t, meta, [prev, t], EXP, gap)
    assert c["label"] == "실거래-페이퍼 차이" and c["loud"]
    text = LC.card_text(c)
    assert text.startswith("🚨 ❌ 청산 · SOL 롱 · 순ROE -40.0%") and telegram_text(CRITICAL, text) == (CRITICAL, text)
    assert text.splitlines()[-1] == "지금 할 일: 거래소 앱의 체결 가격·시각을 페이퍼와 비교해 보세요"
    assert LC.live_gap([{"status": "followed", "pnl": 0.3, "entry_bps": 1.0, "exit_bps": 1.0, "exit_ts": T}], T)
    assert not LC.live_gap([{"status": "followed", "pnl": -3, "entry_bps": 4.0, "exit_bps": -2.0, "exit_ts": T}], T)
    no_ref = LC.build_card(dict(t, strategy="NEW"), meta, [t], EXP, [])
    assert "백테스트 기준표에 이 매매법이 없음" in LC.card_text(no_ref) and no_ref["label"] == "정상 범위 손실"


def test_a_card_waits_for_the_executor_to_close(tmp_path):
    entry, exit_ = T - H1, T - MIN
    open_x = xtrade(entry, fills=False)
    open_x["exit_ts"] = None
    src = card_setup(tmp_path, [loss(entry, exit_)], [entered(entry)], x_trades=[open_x])
    n = ListNotifier()
    LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert not msgs(n, "❌ 청산")                                    # the executor is still closing
    fresh(src, T + 2 * MIN)
    out = LC.run_watch(src, now_ms=T + 2 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert [e for e, *_ in out].count("card") == 1                   # 3 minutes after the paper exit at most
    assert "바이비트 아직 닫는 중" in msgs(n, "❌ 청산")[0][1]


def test_noise_stop_is_stored_and_shown_in_the_next_morning_check(tmp_path):
    day = "2026-10-20"
    w0, w1 = LC.window_of(day)
    entry, exit_ = w1 - 6 * H1, w1 - 5 * H1                         # 03:00 -> 04:00 KST, long 40x
    src = card_setup(tmp_path, [loss(entry, exit_)], [entered(entry)], now=exit_ + 10 * MIN)
    LC.run_watch(src, now_ms=exit_ + 10 * MIN, notifier=ListNotifier(), units=Units(), exists=lambda p: False)
    rows = []
    for k in range(240):                                             # 4 hours after the exit; +0.3% = +12% at 40x
        t = exit_ + k * MIN
        hi = 100.3 if k == 100 else 99.5
        rows.append({"ts": t, "symbol": BTC, "open": 99.5, "high": hi, "low": 99.0, "close": 99.5,
                     "processed_at": t + MIN})
    s = Store3(src.rule_db)
    s.live_bars(rows)
    s.commit()
    s.conn.close()
    out = LC.run_check(src, day=day, now_ms=w1 + 10 * MIN, replay=lambda *a: result(), notifier=ListNotifier())
    assert "손실 카드 1장" in out["text"]
    assert "- 10/21 04:00 BTC 롱 F15_LON_BRK -40.0% · 정상 범위 손실 · 노이즈 손절(4시간 안에 +12.0%까지 돌아감)" \
        in out["text"]
    conn = sqlite3.connect(src.db)
    assert conn.execute("SELECT noise, round(noise_roe, 3) FROM loss_cards").fetchone() == (1, 0.12)
    conn.close()
    # before the 4 hours are over the line says so
    c = {"exit_time": T, "symbol": BTC, "side": 1, "strategy": "S", "roe": -0.4, "label": "정상 범위 손실",
         "noise": None}
    assert LC.card_line(c, T + H1).endswith("노이즈 손절 확인은 다음 점검에서")
    assert LC.noise_check(src.rule_db, dict(c, exit_time=T + DAY), 40, 100.0, T + DAY + H1) is None
    assert LC.noise_check("/nonexistent", c, 40, 100.0, T + 29 * H1) == (-1, None)


def _paper_run(n_wins, n_losses, strategy="F15_LON_BRK", start=W0 - 20 * DAY, losses_last=True):
    out = []
    t = start
    pnls = [1.0] * n_wins + [-1.0] * n_losses if losses_last else [-1.0] * n_losses + [1.0] * n_wins
    for p in pnls:
        out.append(trade(t, t + 30 * MIN, p, strategy=strategy))
        t += 2 * H1
    return out


def test_drift_below_the_honest_range_is_loud_below_fit_is_a_note(tmp_path):
    assert LC.drift_line(LC.drift_state(_closed(10, 2), EXP)) == "- 기대 범위: 표본 작음(12번, 20번부터 봄)"
    conds, _j = LC.drift_conditions([dict(x, strategy="A") for x in _closed(10, 2)], EXP)
    assert conds == []                                               # small sample: no win-rate alarm
    cases = ((11, 9, "drift:20", CRITICAL), (15, 5, "drift_note:20", INFO), (17, 3, None, None))
    for wins, losses, key, level in cases:
        tr = [dict(x, strategy=f"S{i % 7}") for i, x in enumerate(_closed(wins, losses))]
        tr = tr[:-losses] + [dict(x, strategy=f"T{i}") for i, x in enumerate(tr[-losses:])] if losses else tr
        conds, _j = LC.drift_conditions(tr, EXP)
        got = [(c.key, c.level) for c in conds if c.key.startswith("drift")]
        assert got == ([(key, level)] if key else []), (wins, got)
    loud = [c for c in LC.drift_conditions(_closed(11, 9), EXP)[0] if c.key == "drift:20"][0]
    assert loud.text.startswith("기대 범위 밑 · 페이퍼 최근 20번 11승")
    line = LC.drift_line(LC.drift_state(_closed(17, 3), EXP))
    assert line == "- 기대 범위: 최근 20번 17승(백테스트 하위 5% 16승, 처음 보는 기간 12승) 범위 안"
    # one strategy with 3 losses in its last 5: a silent note (and the watcher de-duplicates it)
    src = card_setup(tmp_path, _paper_run(2, 3, start=W0 - 20 * DAY), [])
    n = ListNotifier()
    out = LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert "strat:F15_LON_BRK" in keys(out)
    note = [(lv, m) for lv, m in n.messages if "F15_LON_BRK 최근" in m]
    assert note == [(INFO, "📉 참고: F15_LON_BRK 최근 5번 중 3번 손실 (백테스트 승률 90%)")]
    again = LC.run_watch(src, now_ms=T + 2 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert "strat:F15_LON_BRK" not in keys(again)


def test_an_executor_losing_where_the_paper_won_twice_is_loud(tmp_path):
    a, b = W0 + H1, W0 + 3 * H1
    src = card_setup(tmp_path, [trade(a, a + H1, 3.0), trade(b, b + H1, 2.0)], [],
                     x_trades=[xtrade(a, pnl=-0.4), xtrade(b, pnl=-0.2)])
    n = ListNotifier()
    out = LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert "vs_paper:bybit" in keys(out) and "vs_paper:mexc" not in keys(out)
    m = [x for _l, x in n.messages if x.startswith("바이비트 실거래가 페이퍼가 이긴 거래에서")][0]
    assert m.startswith("바이비트 실거래가 페이퍼가 이긴 거래에서 2번 졌습니다(최근 20번 중)")
    assert "- 10/20 10:00 BTC 롱 F15_LON_BRK: 페이퍼 +$3.00, 실거래 -$0.40" in m


def test_halt_summary_names_the_rule_the_trades_and_the_guide(tmp_path):
    a, b, c = W0, W0 + H1, W0 + 2 * H1
    paper = [loss(a, a + 30 * MIN), loss(b, b + 30 * MIN), loss(c, c + 30 * MIN)]
    src = card_setup(tmp_path, paper, [entered(a), entered(b), entered(c)],
                     x_trades=[xtrade(x, exit_price=99.0, pnl=-1.0, exit_ts=x + 30 * MIN) for x in (a, b, c)])
    _set_bot(src.executors[0].db, ts=T, halted=True, halt_reason="연속 손실 3번", halted_ts=c + H1,
             halt_kinds=["streak"], last_equity=64.0)
    n = ListNotifier()
    LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    msg = [m for _l, m in n.messages if "실행기가 멈췄습니다" in m]
    assert len(msg) == 1
    m = msg[0]
    assert m.startswith("바이비트 실행기가 멈췄습니다 · 이유: 3연패(연속 손실 3번)\n멈춤 기록: 연속 손실 3번")
    assert "- 10/20 09:30 BTC 롱 F15_LON_BRK -40.0% (-$1.00) · 카드: 정상 범위 손실" in m
    assert "- 10/20 11:30 BTC 롱 F15_LON_BRK -40.0% (-$1.00) · 카드: 연속 손실 3번째" in m
    assert "잔고 $64.00 (시작 $100.00, -36.0%)" in m
    assert "페이퍼 거래 3번(표본 작음) · 신호등 근거 쌓는 중(3/20번, 그동안 모두 따라감)" in m
    assert f"- {LC.HALT_GUIDE[0]}" in m and f"- {LC.HALT_GUIDE[1]}" in m
    assert ("sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor clear-halt --config - "
            "--by 이름 --note \"이유\"") in m
    assert "sudo systemctl stop paperbot-executor-bybit" in m
    # the follow alarm stays quiet while halted; the summary is sent once and re-armed when the halt is lifted
    fresh(src, T + 2 * MIN)
    again = LC.run_watch(src, now_ms=T + 2 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert not [k for k in keys(again) if k.startswith("halt:")]
    _set_bot(src.executors[0].db, ts=T + 3 * MIN, halted=False, halted_ts=None, halt_kinds=None)
    fresh(src, T + 4 * MIN)
    out = LC.run_watch(src, now_ms=T + 4 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert [k for k in keys(out, "clear") if k.startswith("halt:")] and n.messages[-1][1].startswith("✅ 바이비트 실행기 멈춤")
    assert LC.halt_rule({"halt_kinds": ["drawdown"]}) == "낙폭 50%"
    assert LC.halt_rule({"halt_kinds": ["kill"]}) == "STOP 파일(비상 정지)"
    assert LC.halt_rule({"halt_reason": "알 수 없는 포지션"}) == "기타(알 수 없는 포지션)"


def test_halt_guide_quotes_are_the_owners_guide():
    from pathlib import Path
    guide = (Path(LC.ROOT) / "docs" / "live1019-start-ko.md").read_text(encoding="utf-8")
    safety = (Path(LC.ROOT) / "docs" / "live-safety.md").read_text(encoding="utf-8")
    for q in LC.HALT_GUIDE:
        assert q in guide, q
    assert "sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor clear-halt --config " in safety
    assert "--by 이름 --note \"이유\"" in safety and "### 3-5. 멈춤 풀기" in safety


def test_server_health_disk_and_memory(tmp_path):
    src = card_setup(tmp_path, [], [])
    units = [("paperbot-live3.service", 1_400 * 1024 ** 2), ("paperbot-agents.service", 900 * 1024 ** 2),
             ("paperbot-combo.service", 700 * 1024 ** 2), ("paperbot-combo-shadow@b.service", 300 * 1024 ** 2),
             ("candleague-live.service", 250 * 1024 ** 2), ("paperbot-executor.service", 90 * 1024 ** 2),
             ("paperbot-dash.service", 120 * 1024 ** 2)]
    state = {"disk": 1.5 * 1024 ** 3, "mem": 400 * 1024 ** 2}
    host = LC.Host(disk_free=lambda p: int(state["disk"]), mem_available=lambda: int(state["mem"]),
                   unit_memory=lambda: units, paths=("/",))
    n = ListNotifier()

    def run(now):
        fresh(src, now)
        _set_bot(src.executors[0].db, ts=now - MIN)
        _set_bot(src.executors[1].db, ts=now - MIN)
        return LC.run_watch(src, now_ms=now, notifier=n, units=Units(), exists=lambda p: False, host=host)
    out = run(T)
    assert sorted(keys(out)) == ["disk", "memory"]
    disk = [m for _l, m in n.messages if m.startswith("디스크 부족")][0]
    assert disk.startswith("디스크 부족 · / 남은 공간 1.5GB")
    mem = [m for _l, m in n.messages if m.startswith("메모리 부족")][0]
    assert mem.startswith("메모리 부족 · 남은 메모리 400MB")
    assert "많이 쓰는 순서: paperbot-live3 1.4GB, paperbot-agents 900MB, paperbot-combo 700MB" in mem
    first = mem.splitlines()[-1]
    assert first == ("지금 할 일: 실험부터 끄기 sudo systemctl stop paperbot-agents paperbot-combo-shadow@b "
                     "candleague-live")
    for keep in ("paperbot-live3", "paperbot-combo ", "paperbot-executor"):
        assert keep not in first.replace("paperbot-combo-shadow", "")
    assert "끄면 안 됨: paperbot-live3, paperbot-combo, paperbot-executor, paperbot-executor-mexc" in mem
    state.update(mem=600 * 1024 ** 2, disk=2.2 * 1024 ** 3)       # between the thresholds: still the same alarms
    assert run(T + 2 * MIN) == []
    state.update(mem=800 * 1024 ** 2, disk=3 * 1024 ** 3)
    out = run(T + 4 * MIN)
    assert sorted(keys(out, "clear")) == ["disk", "memory"]
    state.update(mem=300 * 1024 ** 2)
    assert keys(run(T + 6 * MIN)) == ["memory"]
    assert LC.memory_lines([("paperbot-live3.service", 10)])[-1].startswith("지금 할 일: 끌 만한 실험 서비스가")
    assert LC.memory_lines([])[0].startswith("(서비스별 메모리를 읽지 못함")


def test_unit_memory_parsing_and_meminfo(monkeypatch):
    import subprocess

    class P:
        def __init__(self, out):
            self.stdout = out
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        if cmd[1] == "list-units":
            return P("paperbot-live3.service loaded active running x\n"
                     "paperbot-agents.service loaded active running y\n")
        return P("Id=paperbot-live3.service\nMemoryCurrent=1048576\n\nId=paperbot-agents.service\n"
                 "MemoryCurrent=[not set]\n")
    monkeypatch.setattr(subprocess, "run", fake)
    assert LC._unit_memory() == [("paperbot-live3.service", 1048576)]
    assert calls[1][:5] == ["systemctl", "show", "-p", "Id", "-p"]
    assert LC._mem_available() is None or LC._mem_available() > 0
    assert LC._disk_free("/") is None or LC._disk_free("/") > 0


def test_reference_note_when_the_config_changed(tmp_path):
    cfg = tmp_path / "combo.json"
    cfg.write_text("{}")
    src = LC.Sources(combo_config=str(cfg), expected="-")
    assert "기준표가 지금 설정 파일과 다름" in LC.reference_notes({"config_sha256": "abc"}, src)[0]
    import hashlib
    assert LC.reference_notes({"config_sha256": hashlib.sha256(b"{}").hexdigest()}, src) == []
    assert "기준표" in LC.reference_notes(None, src)[0]
    from pathlib import Path
    live = Path(LC.ROOT) / "deploy" / "combo.live-ac.json"
    assert LC.reference_notes(LC.load_expected(), LC.Sources(combo_config=str(live))) == []


def test_the_morning_check_leaves_fresh_losses_to_the_watcher(tmp_path):
    entry, exit_ = T - H1, T - 30 * MIN
    src = card_setup(tmp_path, [loss(entry, exit_)], [entered(entry)])
    LC.run_check(src, day="2026-10-19", now_ms=T, replay=lambda *a: result(), notifier=ListNotifier())
    conn = sqlite3.connect(src.db)
    assert conn.execute("SELECT COUNT(*) FROM loss_cards").fetchone() == (0,)
    conn.close()
    n = ListNotifier()
    LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert msgs(n, "❌ 청산")


# ====================================================================== 4부: 실거래 텔레그램
def _tg(monkeypatch, env: dict, fail=(), code=400):
    """notify.TelegramNotifier's urlopen recorded; the chat ids in ``fail`` answer with HTTP ``code``."""
    import urllib.error
    import urllib.parse
    from paperbot import notify
    for k in ("TELEGRAM_CHAT_CRITICAL", "TELEGRAM_CHAT_WARN", "TELEGRAM_CHAT_INFO", "TELEGRAM_SOUND"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sent = []

    class Resp:
        def read(self):
            return b"{}"

    def urlopen(url, data=None, timeout=None):
        d = {k: v[0] for k, v in urllib.parse.parse_qs(data.decode()).items()}
        d["_url"] = url
        if d["chat_id"] in fail:
            raise urllib.error.HTTPError(url, code, "x", {"Retry-After": "3"}, None)
        sent.append(d)
        return Resp()
    monkeypatch.setattr(notify.urllib.request, "urlopen", urlopen)
    return sent


def test_several_private_chats_per_level_and_one_failing_never_stops_the_others(monkeypatch, capsys):
    from paperbot.notify import TelegramNotifier
    sent = _tg(monkeypatch, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_CRITICAL": "111, 222"})
    n = TelegramNotifier()
    assert n.send(INFO, "🟢 진입 · BTC 롱 · 40배") is True
    assert [d["chat_id"] for d in sent] == ["111", "222"]           # WARN / INFO fall back to the same two
    sent = _tg(monkeypatch, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_CRITICAL": "111,222"}, fail={"111"})
    n = TelegramNotifier(sleep=lambda s: None)
    assert n.send(CRITICAL, "a") is True and [d["chat_id"] for d in sent] == ["222"]
    assert capsys.readouterr().err.count("telegram send failed (chat 1 of 2): HTTP 400") == 1
    # accepted by one: never sent again (a 429 elsewhere does not repeat it to the chat that has it)
    sent = _tg(monkeypatch, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_CRITICAL": "111,222"}, fail={"111"}, code=429)
    assert TelegramNotifier(sleep=lambda s: None).send_once(CRITICAL, "b") == (True, None)
    assert [d["chat_id"] for d in sent] == ["222"]
    _tg(monkeypatch, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_CRITICAL": "111,222"}, fail={"111", "222"}, code=429)
    assert TelegramNotifier(sleep=lambda s: None).send_once(CRITICAL, "c") == (False, 3.0)


def test_sound_critical_rings_only_the_alarms(monkeypatch):
    from paperbot.notify import TelegramNotifier
    for mode, want in (("critical", ["false", "true", "true"]), ("CRITICAL", ["false", "true", "true"]),
                       ("1", ["false", "false", "true"]), ("0", ["true", "true", "true"]), (None, ["true"] * 3)):
        env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_CRITICAL": "111"}
        if mode is not None:
            env["TELEGRAM_SOUND"] = mode
        sent = _tg(monkeypatch, env)
        n = TelegramNotifier()
        for level in (CRITICAL, WARN, INFO):
            n.send(level, "x")
        assert [d["disable_notification"] for d in sent] == want, mode


def test_an_override_file_with_only_the_critical_line_reaches_every_level(monkeypatch):
    """live.env names the rule bot's room; /etc/paperbot/live-telegram.env sets only TELEGRAM_CHAT_CRITICAL (WARN and
    INFO empty in live.env, as the server guide leaves them): every live message goes to the owners' chats."""
    from paperbot.notify import TelegramNotifier
    sent = _tg(monkeypatch, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_CRITICAL": "111,222", "TELEGRAM_CHAT_WARN": "",
                             "TELEGRAM_CHAT_INFO": "", "TELEGRAM_SOUND": "critical"})
    n = LC._notifier()
    assert isinstance(n, TelegramNotifier)
    for level in (CRITICAL, WARN, INFO):
        assert n.send(level, "x") is True
    assert [d["chat_id"] for d in sent] == ["111", "222"] * 3
    # an empty CRITICAL (a blank line in the override) does not crash: the console, as before
    from paperbot.notify import ConsoleNotifier
    monkeypatch.setenv("TELEGRAM_CHAT_CRITICAL", "")
    assert isinstance(LC._notifier(), ConsoleNotifier)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert isinstance(LC._notifier(), ConsoleNotifier)


def test_the_paper_bot_leaves_its_raw_trade_lines_out_when_asked(monkeypatch):
    from types import SimpleNamespace
    from paperbot import combo as C
    pos = SimpleNamespace(entry_time=T, symbol=BTC, side=1, leverage=40, margin=40.0, stop_price=66_420.0,
                          signal=SimpleNamespace(meta={"member": "x"}, strategy_id="F15_LON_BRK", timeframe="1h",
                                                 score=3.0))
    eng = SimpleNamespace(trades=[], position=pos)
    me = SimpleNamespace(book=SimpleNamespace(engines={C.ACCOUNT: eng}), cfg=SimpleNamespace(telegram=True, tag="[t]"),
                         notifier=ListNotifier())
    monkeypatch.setenv("PAPERBOT_COMBO_TRADE_MSGS", "0")
    C.ComboRunner._tell(me, {C.ACCOUNT: (None, 0)})
    assert me.notifier.messages == []
    monkeypatch.delenv("PAPERBOT_COMBO_TRADE_MSGS")
    C.ComboRunner._tell(me, {C.ACCOUNT: (None, 0)})
    assert len(me.notifier.messages) == 1 and "진입 BTCUSDT 롱 F15_LON_BRK" in me.notifier.messages[0][1]


def test_chat_ids_lists_the_private_chats_and_never_the_token():
    import urllib.error
    ups = {"ok": True, "result": [
        {"message": {"date": 1792500000, "chat": {"id": 111, "type": "private", "first_name": "민수",
                                                  "username": "minsu"}}},
        {"message": {"date": 1792500600, "chat": {"id": -100123, "type": "supergroup", "title": "알림방"}}},
        {"message": {"date": 1792501200, "chat": {"id": 222, "type": "private", "first_name": "지현"}}},
        {"message": {"date": 1792499000, "chat": {"id": 111, "type": "private", "first_name": "민수"}}}]}
    text = LC.chat_ids_text("SECRET:TOKEN", fetch=lambda url: json.dumps(ups).encode())
    assert text.splitlines() == [
        "개인 채팅 (번호 · 이름 · 아이디 · 마지막 메시지)",
        f"222 · 지현 · - · {LC.kst_dt(1792501200000)}",
        f"111 · 민수 · @minsu · {LC.kst_dt(1792500000000)}",
        "live-telegram.env의 세 줄에 넣을 값: 222,111  (두 분 것만 남기세요)"]
    assert "SECRET" not in text and "-100123" not in text

    def refused(url):
        raise urllib.error.HTTPError(url, 401, f"Unauthorized {url}", {}, None)
    bad = LC.chat_ids_text("SECRET:TOKEN", fetch=refused)
    assert "SECRET" not in bad and "봇 토큰을 확인하세요" in bad
    assert "시작(Start)" in LC.chat_ids_text("SECRET:TOKEN", fetch=lambda url: b'{"ok": true, "result": []}')
    assert "TELEGRAM_BOT_TOKEN이 없습니다" in LC.chat_ids_text("")


# ---------------------------------------------------------------- the live bot (its own token, owners 10-19)
RULE_TOKEN, LIVE_TOKEN = "111:RULEBOTSECRET", "222:LIVEBOTSECRET"


def tg_files(tmp_path, over: Optional[str], base: Optional[str] = None, mtime_ago_ms: int = 60 * MIN):
    """live.env (the rule bot's room, an exchange key next to it) and, when given, live-telegram.env."""
    lp, op = tmp_path / "live.env", tmp_path / "live-telegram.env"
    lp.write_text(base if base is not None else
                  "# /etc/paperbot/live.env\nBINANCE_API_KEY=k\nBINANCE_API_SECRET=never-kept\n"
                  f'TELEGRAM_BOT_TOKEN="{RULE_TOKEN}"\nTELEGRAM_CHAT_CRITICAL=-1001234\nTELEGRAM_CHAT_WARN=\n'
                  "TELEGRAM_CHAT_INFO=\n", encoding="utf-8")
    if over is not None:
        op.write_text(over, encoding="utf-8")
        t = (time.time() * 1000 - mtime_ago_ms) / 1000
        os.utime(op, (t, t))
    return str(lp), str(op)


FULL = (f"TELEGRAM_BOT_TOKEN={LIVE_TOKEN}\nTELEGRAM_CHAT_CRITICAL=111,222\nTELEGRAM_CHAT_WARN=111,222\n"
        "TELEGRAM_CHAT_INFO=111,222\nTELEGRAM_SOUND=critical\nPAPERBOT_COMBO_TRADE_MSGS=0\n")


def test_the_live_bot_files_and_the_token_in_effect(tmp_path):
    lp, op = tg_files(tmp_path, FULL)
    t = LC.tg_files(lp, op)
    assert t["base"] == {"TELEGRAM_BOT_TOKEN": RULE_TOKEN, "TELEGRAM_CHAT_CRITICAL": "-1001234",
                         "TELEGRAM_CHAT_WARN": "", "TELEGRAM_CHAT_INFO": ""}          # the exchange key never kept
    eff = LC.tg_effective(t, environ={"TELEGRAM_BOT_TOKEN": "from-env", "TELEGRAM_CHAT_CRITICAL": "-1"})
    assert eff["TELEGRAM_BOT_TOKEN"] == LIVE_TOKEN and eff["TELEGRAM_CHAT_CRITICAL"] == "111,222"
    assert LC.tg_source(t) == "live-telegram.env(실거래 전용 봇)" and LC.tg_problem(t) is None
    # no override: live.env's bot; neither file readable: the environment
    t0 = LC.tg_files(lp, str(tmp_path / "missing.env"))
    assert LC.tg_effective(t0, environ={})["TELEGRAM_BOT_TOKEN"] == RULE_TOKEN and LC.tg_source(t0) == "live.env(규칙봇)"
    none = LC.tg_files(str(tmp_path / "x.env"), str(tmp_path / "y.env"))
    assert LC.tg_effective(none, environ={"TELEGRAM_BOT_TOKEN": "e"})["TELEGRAM_BOT_TOKEN"] == "e"
    assert LC.tg_problem(none) is None and LC.tg_problem(t0) is None
    # the token without the chat lines (commented out): live.env's room, where the new bot is not
    lp, op = tg_files(tmp_path, f"TELEGRAM_BOT_TOKEN={LIVE_TOKEN}\n#TELEGRAM_CHAT_CRITICAL=111,222\n")
    kind, text = LC.tg_problem(LC.tg_files(lp, op))
    assert kind == "token" and text.startswith("🚨 텔레그램 설정 · 실거래 전용 봇의 채팅 줄이 없습니다")
    assert "지금 할 일: chat-ids" in text and "SECRET" not in text
    # the same chats written out again are still live.env's room; the same token as live.env is not a new bot
    lp, op = tg_files(tmp_path, f"TELEGRAM_BOT_TOKEN={LIVE_TOKEN}\nTELEGRAM_CHAT_CRITICAL=-1001234\n")
    assert LC.tg_problem(LC.tg_files(lp, op))[0] == "token"
    lp, op = tg_files(tmp_path, f"TELEGRAM_BOT_TOKEN={RULE_TOKEN}\nTELEGRAM_SOUND=critical\n")
    assert LC.tg_problem(LC.tg_files(lp, op)) is None
    # live.env already wrote to an owner's PRIVATE chat (a positive id, the person's own): the same id under the new
    # bot is that person's chat with the new bot, not the rule bot's room (owners 10-19)
    priv = tmp_path / "priv"
    priv.mkdir()
    (priv / "live.env").write_text(f"TELEGRAM_BOT_TOKEN={RULE_TOKEN}\nTELEGRAM_CHAT_CRITICAL=8454602726\n",
                                   encoding="utf-8")
    (priv / "live-telegram.env").write_text(f"TELEGRAM_BOT_TOKEN={LIVE_TOKEN}\nTELEGRAM_CHAT_CRITICAL=8454602726\n",
                                            encoding="utf-8")
    t = LC.tg_files(str(priv / "live.env"), str(priv / "live-telegram.env"))
    assert LC.tg_problem(t) is None and "live-telegram.env(실거래 전용 봇)" in LC.tg_status(t)
    # an empty CRITICAL line sends nowhere
    lp, op = tg_files(tmp_path, f"TELEGRAM_BOT_TOKEN={LIVE_TOKEN}\nTELEGRAM_CHAT_CRITICAL=\n")
    kind, text = LC.tg_problem(LC.tg_files(lp, op))
    assert kind == "empty" and "비어 있습니다" in text and any(ln.startswith("지금 할 일:") for ln in text.split("\n"))


def test_the_watcher_says_once_through_live_env_bot_that_the_new_token_has_no_chats(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.executescript(LC.STATE_SCHEMA)
    base = {"TELEGRAM_BOT_TOKEN": RULE_TOKEN, "TELEGRAM_CHAT_CRITICAL": "-1001234"}
    half = {"base": base, "over": {"TELEGRAM_BOT_TOKEN": LIVE_TOKEN}, "over_exists": True, "over_mtime": T - 5 * MIN}
    rule, live = ListNotifier(), ListNotifier()
    assert LC.tg_pass(conn, T, half, rule.send, live.send) == []            # being filled in: 10 minutes' grace
    got = LC.tg_pass(conn, T + 6 * MIN, half, rule.send, live.send)
    assert [g[0] for g in got] == ["tg_setup"] and rule.messages[0][0] == CRITICAL and live.messages == []
    assert LC.tg_pass(conn, T + 7 * MIN, half, rule.send, live.send) == []  # once
    done = {**half, "over": {"TELEGRAM_BOT_TOKEN": LIVE_TOKEN, "TELEGRAM_CHAT_CRITICAL": "111,222"},
            "over_mtime": T + 8 * MIN}
    got = LC.tg_pass(conn, T + 9 * MIN, done, rule.send, live.send)
    assert got[0][0] == "tg_clear" and live.messages[0][1].startswith("✅ 텔레그램 설정이 맞춰졌습니다")
    assert len(rule.messages) == 1 and LC.tg_pass(conn, T + 10 * MIN, done, rule.send, live.send) == []
    # live.env's bot refused: tried again on the next pass
    conn.execute("DELETE FROM live_state")
    assert LC.tg_pass(conn, T + 20 * MIN, half, lambda lv, tx: False, live.send) == []
    assert LC.tg_pass(conn, T + 21 * MIN, half, rule.send, live.send)[0][0] == "tg_setup"
    # in a watcher pass (the notifier handed in carries both)
    src, _ = trade_world(tmp_path)
    n = ListNotifier()
    out = LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False,
                       tg={**half, "over_mtime": T - 11 * MIN})
    assert [o for o in out if o[0] == "tg_setup"] and msgs(n, "🚨 텔레그램 설정")
    out = LC.run_watch(src, now_ms=T + MIN, notifier=n, units=Units(), exists=lambda p: False,
                       tg={**half, "over_mtime": T - 11 * MIN})
    assert not [o for o in out if o[0] == "tg_setup"]


def test_the_setup_alarm_goes_out_with_live_env_bot_and_room(monkeypatch):
    sent = _tg(monkeypatch, {"TELEGRAM_BOT_TOKEN": LIVE_TOKEN, "TELEGRAM_CHAT_CRITICAL": "111,222",
                             "TELEGRAM_SOUND": "critical"})
    t = {"base": {"TELEGRAM_BOT_TOKEN": RULE_TOKEN, "TELEGRAM_CHAT_CRITICAL": "-1001234"}, "over": {}}
    assert LC.tg_base_send(t)(CRITICAL, "🚨 텔레그램 설정 · x") is True
    assert len(sent) == 1 and f"/bot{RULE_TOKEN}/" in sent[0]["_url"] and sent[0]["chat_id"] == "-1001234"
    assert sent[0]["disable_notification"] == "true"                  # live.env's own sound rule (all silent)
    assert LC.tg_base_send({"base": {"TELEGRAM_BOT_TOKEN": RULE_TOKEN}}) is None
    assert LC.tg_base_send({"base": None}) is None


def test_chat_ids_asks_with_the_token_in_effect_and_says_which_bot(tmp_path, monkeypatch, capsys):
    import urllib.request
    asked = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

    def urlopen(url, timeout=None):
        asked.append(url)
        if url.endswith("/getMe"):
            return Resp(json.dumps({"ok": True, "result": {"username": "our_live_bot"}}).encode())
        return Resp(json.dumps({"ok": True, "result": [
            {"message": {"date": 1792500000, "chat": {"id": 111, "type": "private", "first_name": "민수"}}}]}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "333:FROMENV")
    lp, op = tg_files(tmp_path, f"TELEGRAM_BOT_TOKEN={LIVE_TOKEN}\n")
    assert LC.main(["chat-ids", "--live-env", lp, "--live-telegram-env", op]) == 0
    out = capsys.readouterr().out
    assert all(f"/bot{LIVE_TOKEN}/" in u for u in asked) and len(asked) == 2
    assert out.splitlines()[0] == "봇: @our_live_bot · 토큰: live-telegram.env(실거래 전용 봇)"
    assert "111 · 민수" in out and "SECRET" not in out and "FROMENV" not in out
    asked.clear()
    assert LC.main(["chat-ids", "--live-env", lp, "--live-telegram-env", str(tmp_path / "none.env")]) == 0
    out = capsys.readouterr().out
    assert all(f"/bot{RULE_TOKEN}/" in u for u in asked) and "아직 규칙봇 토큰입니다" in out and "SECRET" not in out


def test_show_ends_with_where_the_live_messages_go(tmp_path, capsys):
    db = str(tmp_path / "livecheck.db")
    LC.open_out(db).close()
    lp, op = tg_files(tmp_path, FULL)
    LC.main(["show", "--db", db, "--live-env", lp, "--live-telegram-env", op])
    last = capsys.readouterr().out.rstrip().splitlines()[-1]
    assert last == "텔레그램 설정: live-telegram.env(실거래 전용 봇) → 채팅 2곳 · 🚨만 소리 · 페이퍼 봇 날것 진입·청산 줄 끔"
    lp, op = tg_files(tmp_path, f"TELEGRAM_BOT_TOKEN={LIVE_TOKEN}\n")
    LC.main(["show", "--db", db, "--live-env", lp, "--live-telegram-env", op])
    out = capsys.readouterr().out
    assert "⚠ 텔레그램 설정 · 실거래 전용 봇의 채팅 줄이 없습니다" in out and "SECRET" not in out
    LC.main(["show", "--db", db, "--live-env", lp, "--live-telegram-env", str(tmp_path / "none.env")])
    assert "live-telegram.env 없음" in capsys.readouterr().out
    LC.main(["show", "--db", db, "--live-env", str(tmp_path / "no.env"), "--live-telegram-env", op])
    assert "live.env를 못 읽음" in capsys.readouterr().out


def test_every_live_unit_loads_the_live_bot_file_after_its_own_and_install_never_writes_it():
    deploy = os.path.join(LC.ROOT, "deploy")
    live, exe = "/etc/paperbot/live.env", "/etc/paperbot/executor.env"
    for unit, own in (("paperbot-combo", live), ("paperbot-executor", exe), ("paperbot-executor-mexc", exe),
                      ("paperbot-livecheck", live), ("paperbot-livewatch", live), ("paperbot-liveimprove", live)):
        with open(os.path.join(deploy, unit + ".service"), encoding="utf-8") as fh:
            envs = [ln.split("=", 1)[1].strip() for ln in fh if ln.startswith("EnvironmentFile=")]
        assert envs[-1] == "-/etc/paperbot/live-telegram.env" and own in envs, unit
    with open(os.path.join(deploy, "paperbot-combo-shadow@.service"), encoding="utf-8") as fh:
        assert "live-telegram" not in fh.read()
    with open(os.path.join(deploy, "install.sh"), encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh if "live-telegram.env" in ln and not ln.strip().startswith("#")]
    assert lines == ["if [ -f /etc/paperbot/live-telegram.env ]; then",
                     "chown root:paperbot /etc/paperbot/live-telegram.env && chmod 640 /etc/paperbot/live-telegram.env"]
    with open(os.path.join(deploy, "live-telegram.env.example"), encoding="utf-8") as fh:
        ex = fh.read().splitlines()
    assert all(ln.startswith("#") for ln in ex if ln.strip())                     # nothing set by copying it
    keys = [ln for ln in ex if re.match(r"^#[A-Z_]+=", ln)]
    assert keys == ["#TELEGRAM_BOT_TOKEN=", "#TELEGRAM_CHAT_CRITICAL=111,222", "#TELEGRAM_CHAT_WARN=",
                    "#TELEGRAM_CHAT_INFO=", "#TELEGRAM_SOUND=critical", "#PAPERBOT_COMBO_TRADE_MSGS=0"]
    assert ex[ex.index("#TELEGRAM_BOT_TOKEN=") - 1] == (
        "# 실거래 전용 봇 토큰(@BotFather에서 새로 만든 봇). 이 줄과 채팅 줄 3개는 함께 넣습니다(새 봇은 규칙봇 방에 없으므로 "
        "채팅 줄 없이 토큰만 넣으면 보내기가 실패합니다)")


def test_money_prices_and_roe_as_the_owners_read_them():
    assert LC.fmt_price(67_250.4, BTC) == "67,250" and LC.fmt_price(2_612.3, "ETHUSDT") == "2,612.30"
    assert LC.fmt_price(0.245123, "DOGEUSDT") == "0.24512" and LC.fmt_price(182.35, SOL) == "182.35"
    assert LC.fmt_price(1234.5) == "1,234" and LC.fmt_price(5.5) == "5.50" and LC.fmt_price(None) == "-"
    assert (LC.fmt_usd(9.364), LC.fmt_usd(-1.5), LC.fmt_usd(40, sign=False)) == ("+$9.36", "-$1.50", "$40.00")
    assert LC.fmt_usd(1234.5, sign=False) == "$1,234.50"
    assert LC.fmt_roe(0.234) == "+23.4%" and LC.fmt_roe(-0.38) == "-38.0%"
    assert LC.strat_text("F15_LON_BRK", "1h", EXP) == "F15_LON_BRK 1시간 · 돌파"
    assert LC.strat_text("X", "30m", EXP) == "X 30분"


def trade_world(tmp_path, entry=T - MIN, **kw):
    """A paper position entered at ``entry`` (BTC long 40x at 67,250, stop 66,420) and two executors."""
    src = card_setup(tmp_path, [], [], **kw)
    conn = sqlite3.connect(src.paper_db)
    pos = {"symbol": BTC, "side": 1, "qty": 0.24, "entry_price": 67_250.0, "entry_time": entry, "leverage": 40,
           "stop_price": 66_420.0, "stop_initial": 66_420.0, "lock_roe": None,
           "signal": {"strategy_id": "F15_LON_BRK", "timeframe": "1h", "meta": {}}}
    conn.execute("INSERT OR REPLACE INTO state VALUES ('accounts', ?, ?)",
                 (T - MIN, json.dumps({"last_ts": T - MIN, "engines": {LC.ACCOUNT: {"wallet": 1000.0,
                                                                                    "position": pos}}})))
    conn.commit()
    conn.close()
    return src, pos


def set_position(src, pos):
    conn = sqlite3.connect(src.paper_db)
    conn.execute("UPDATE state SET data = ? WHERE k = 'accounts'",
                 (json.dumps({"last_ts": T, "engines": {LC.ACCOUNT: {"wallet": 1000.0, "position": pos}}}),))
    conn.commit()
    conn.close()


def x_entered(path, key, price=67_262.0, stop=66_431.0, qty=0.0238, moved=None):
    from paperbot.executor import ExecStore
    st = ExecStore(path, lock=False)
    st.trade_open({"key": key, "symbol": BTC, "side": 1, "qty": qty, "leverage": 40, "entry_ts": T,
                   "entry_price": price, "stop_initial": stop})
    st.commit()
    st.close()
    _set_bot(path, ts=T, trade={"key": key, "symbol": BTC, "side": 1, "status": "open", "qty": qty, "entry_ts": T,
                                "stop_initial": stop, "stop": moved or stop, "stop_algo_id": "a1"})


def run(src, now, n):
    fresh(src, now)
    for ex in src.executors:
        _set_bot(ex.db, ts=now - 2000)
    return LC.run_watch(src, now_ms=now, notifier=n, units=Units(), exists=lambda p: False)


def test_entry_waits_for_both_executors_then_one_message(tmp_path):
    entry = T - MIN
    src, _pos = trade_world(tmp_path, entry)
    key = f"{LC.ACCOUNT}|{BTC}|{entry}"
    n = ListNotifier()
    run(src, T, n)
    assert not msgs(n, "🟢")                                         # nobody answered yet
    x_entered(src.executors[0].db, key)
    run(src, T + 20_000, n)
    assert not msgs(n, "🟢")                                         # MEXC has not answered yet
    from paperbot.executor import ExecStore
    st = ExecStore(src.executors[1].db, lock=False)
    st.event(T + 25_000, "WARN", "light_red", "신호등 빨강", {"key": key})
    st.commit()
    st.close()
    run(src, T + 30_000, n)
    (lv, text), = msgs(n, "🟢")
    assert lv == INFO and text.split("\n") == [
        "🟢 진입 · BTC 롱 · 40배",
        "F15_LON_BRK 1시간 · 돌파",
        "페이퍼   67,250 · 손절 66,420 (-1.23%)",
        "바이비트 ✅ 67,262 · 증거금 $40.02 · 손절 66,431 · 포지션 1/1",
        "MEXC     ⛔ 신호등이 막음"]
    assert telegram_text(INFO, text) == (INFO, text)
    run(src, T + 90_000, n)
    assert len(msgs(n, "🟢")) == 1                                   # de-duplicated
    conn = sqlite3.connect(src.db)
    assert conn.execute("SELECT kind, sent_ts IS NOT NULL FROM trade_msgs").fetchall() == [("entry", 1)]
    conn.close()


def test_entry_after_three_minutes_without_an_answer_and_old_entries(tmp_path):
    entry = T - MIN
    src, _pos = trade_world(tmp_path, entry)
    n = ListNotifier()
    run(src, T, n)
    run(src, entry + 3 * MIN, n)
    (_lv, text), = msgs(n, "🟢")
    assert "바이비트 ⚠ 따라가지 않음 (알람 따로)" in text and "MEXC     ⚠ 따라가지 않음 (알람 따로)" in text
    _set_bot(src.executors[1].db, ts=T, halted=True)
    (tmp_path / "old").mkdir()
    src2, _p = trade_world(tmp_path / "old", T - 40 * MIN)          # first seen 40 minutes late: recorded only
    n2 = ListNotifier()
    run(src2, T, n2)
    assert not msgs(n2, "🟢")
    conn = sqlite3.connect(src2.db)
    assert conn.execute("SELECT sent_ts FROM trade_msgs WHERE kind = 'entry'").fetchall() == [(None,)]
    conn.close()
    # a halted executor is ⏸
    st = LC.entry_state(src.executors[1], LC.open_ro(src.executors[1].db), "k", [], T, True)
    assert st == {"state": "halted"}
    assert LC.entry_exec_line(src.executors[1], st, BTC) == "MEXC     ⏸ 멈춤 중이라 따라가지 않음"


def test_only_the_first_lock_and_the_exit_shows_the_final_lock(tmp_path):
    entry = T - H1
    src, pos = trade_world(tmp_path, entry)
    key = f"{LC.ACCOUNT}|{BTC}|{entry}"
    x_entered(src.executors[0].db, key)
    n = ListNotifier()
    run(src, T, n)                                                   # the entry (old enough to send)
    set_position(src, dict(pos, lock_roe=0.10, stop_price=67_430.0))
    run(src, T + MIN, n)
    assert not msgs(n, "🔒")                                         # Bybit has not moved its stop yet
    x_entered(src.executors[0].db, key, moved=67_430.0)
    run(src, T + 2 * MIN, n)
    (lv, text), = msgs(n, "🔒")
    assert lv == INFO and text == "🔒 잠금 시작 · BTC 롱 · +10% 확보\n바이비트 손절 66,431 → 67,430 · MEXC 따라가지 않음"
    set_position(src, dict(pos, lock_roe=0.13, stop_price=67_530.0))
    run(src, T + 3 * MIN, n)
    assert len(msgs(n, "🔒")) == 1                                   # later steps are not sent
    # the exit: Bybit still closing -> wait; then one message with the final lock
    set_position(src, None)
    x = T + 4 * MIN
    t = trade(entry, x, 93.6, roe=0.234, entry_price=67_250.0, exit_price=67_643.0)
    t.lock_roe, t.mfe_price = 0.13, 67_250 * (1 + 0.26 / 40)
    s = Store3(src.paper_db)
    s.trade(LC.ACCOUNT, t)
    s.commit()
    s.conn.close()
    run(src, x + MIN, n)
    assert not msgs(n, "✅ 청산")
    from paperbot.executor import ExecStore
    st = ExecStore(src.executors[0].db, lock=False)
    st.trade_close(key, x + 3000, "paper 청산", 9.36, {"key": key})
    st.commit()
    st.close()
    _set_bot(src.executors[0].db, ts=x, trade=None, last_equity=117.23)
    run(src, x + 2 * MIN, n)
    (lv, text), = msgs(n, "✅ 청산")
    lines = text.split("\n")
    assert lines[0] == "✅ 청산 · BTC 롱 · 순ROE +23.4%"
    assert lines[1] == "F15_LON_BRK 1시간 · 돌파 · 1.1시간 보유 · 잠금 +13% 청산 (최고 +26%)"
    assert lines[2] == "바이비트 +$9.36 (+23.4%) · 잔고 $117.23" and lines[3] == "MEXC     따라가지 않음"
    assert lines[4].startswith("오늘 1승 0패 · 지금까지 1번 1승(표본 작음) · 신호등 바이비트 ⚪ MEXC ⚪")
    run(src, x + 3 * MIN, n)
    assert len(msgs(n, "✅ 청산")) == 1


def test_light_changes_checkpoint_and_executor_start_stop(tmp_path):
    src = card_setup(tmp_path, _paper_run(17, 3), [])
    n = ListNotifier()
    run(src, T, n)                                                   # first look: recorded, nothing sent
    assert not msgs(n, "🚦") and not msgs(n, "▶️")
    s = Store3(src.paper_db)
    s.trade(LC.ACCOUNT, trade(T - 30 * MIN, T - 10 * MIN, -1.0))      # 16 of the last 20: Bybit 🟢 -> 🔴
    s.commit()
    s.conn.close()
    run(src, T + MIN, n)
    (lv, text), = msgs(n, "🚦")
    assert lv == INFO and text == ("🚦 신호등 · 바이비트 🟢→🔴 · 최근 20번 16승(80%) · 기준 85%\n"
                                   "새 진입을 따라가지 않습니다(페이퍼는 계속 거래, 기준을 넘으면 다시 따라감)")
    run(src, T + 2 * MIN, n)
    assert len(msgs(n, "🚦")) == 1
    # ▶️ / ⏹ from the executor's own start / SIGTERM events
    from paperbot.executor import ExecStore
    st = ExecStore(src.executors[1].db, lock=False)
    st.event(T + 2 * MIN, "INFO", "start", "시작")
    st.commit()
    st.close()
    run(src, T + 3 * MIN, n)                                         # the first start event seen: recorded
    st = ExecStore(src.executors[1].db, lock=False)
    st.event(T + 4 * MIN, "INFO", "sigterm", "끄라는 신호(SIGTERM)")
    st.commit()
    st.close()
    run(src, T + 5 * MIN, n)
    (lv, text), = msgs(n, "⏹")
    assert lv == INFO and text.startswith("⏹ MEXC 실행기 꺼짐 (끄라는 신호를 받음: 사람이 끔이나 서버 재시작)")
    # stopped by hand: no "quiet executor" alarm while systemd says it is not running
    _set_bot(src.executors[1].db, ts=T - 30 * MIN)
    fresh(src, T + 20 * MIN)
    out = LC.run_watch(src, now_ms=T + 20 * MIN, notifier=n, exists=lambda p: False,
                       units=Units(**{"paperbot-executor-mexc": ("inactive", "enabled")}))
    assert "stale:mexc" not in keys(out)
    st = ExecStore(src.executors[1].db, lock=False)
    st.event(T + 21 * MIN, "INFO", "start", "시작")
    st.commit()
    st.close()
    run(src, T + 22 * MIN, n)
    (lv, text), = msgs(n, "▶️")
    assert text.startswith("▶️ MEXC 실행기 켜짐 · 잔고 $110.00 · 신호등 빨강(최근 20번 16승 80%, 기준 90%)")


def test_checkpoint_at_the_40th_trade_loud_only_under_82(tmp_path):
    for wins, loud in ((35, False), (31, True)):
        d = tmp_path / f"w{wins}"
        d.mkdir()
        src = card_setup(d, _paper_run(wins, 39 - wins, losses_last=False), [])
        n = ListNotifier()
        run(src, T, n)
        assert not [m for _l, m in n.messages if "40번 도달" in m]
        s = Store3(src.paper_db)
        s.trade(LC.ACCOUNT, trade(T - 30 * MIN, T - 10 * MIN, 1.0))
        s.commit()
        s.conn.close()
        run(src, T + MIN, n)
        got = [(lv, m) for lv, m in n.messages if "40번 도달" in m]
        assert len(got) == 1
        lv, text = got[0]
        if loud:
            assert lv == CRITICAL and text.startswith("🚨 🏁 40번 도달 · 페이퍼 첫 40번 32승(80.0%) → 멈추고 다시 생각")
            assert text.splitlines()[-1].startswith("지금 할 일: 미리 정한 대로 멈추고 다시 생각합니다")
        else:
            assert lv == INFO and text.startswith("🏁 40번 도달 · 페이퍼 첫 40번 36승(90.0%) → 늘리기 검토")
        assert "미리 정한 기준: 88% 이상 늘리기 검토 / 82~88% 계속 지켜보기 / 82% 미만 멈추고 다시 생각" in text
        run(src, T + 2 * MIN, n)
        assert len([m for _l, m in n.messages if "40번 도달" in m]) == 1


def test_morning_rest_line_macro_releases_and_the_weekend():
    w0, w1 = LC.window_of("2026-10-28")                             # the day ahead: Thursday 10/29 09:00 ->
    assert LC.rest_line(w1, {"macro_blackout_min": 30}) == "- 오늘 진입 쉬는 시간: 21:00~22:00 PCE 물가"
    w0, w1 = LC.window_of("2026-10-27")                             # Wednesday 10/28 09:00 -> FOMC at 03:00
    assert LC.rest_line(w1, None) == "- 오늘 진입 쉬는 시간: 내일 02:30~03:30 FOMC 금리 결정"
    w0, w1 = LC.window_of("2026-10-29")                             # Friday 10/30 09:00
    assert LC.rest_line(w1, {}) == ("- 오늘 진입 쉬는 시간: 없음(미국 경제 발표 없음)\n"
                                    "- 주말(토·일 KST)은 진입하지 않습니다")
    assert "주말" not in LC.rest_line(w1, {"no_weekend": False})


def test_preview_prints_every_message_type_and_sends_nothing(monkeypatch):
    import urllib.request
    from paperbot import livepreview as PV

    def no_network(*a, **k):
        raise AssertionError("the preview must not reach the network")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    items = PV.scenes()
    text = PV.render(items)
    titles = {PV.kind_of(PV.shown(lv, t)[0]) for _s, lv, t in items}
    for kind in ("실행기 켜짐", "진입 대기", "진입", "잠금 시작", "청산(이김)", "손실 카드", "손실 카드(소리)", "신호등 바뀜",
                 "40번 도달", "참고", "좋은 소식", "다시 정상", "실행기 꺼짐(사람이 끔)", "아침 점검",
                 "아침 점검(확인할 것 있음)", "알람: 따라가지 않음", "알람: 실행기 조용함", "알람: 손절 기록 없음",
                 "알람: 디스크 부족", "알람: 메모리 부족", "알람: 페이퍼 봇 멈춤", "알람: 1분봉 멈춤",
                 "알람: 잔고 25% 하락", "알람: 실거래만 짐", "알람: 기대 범위 밑", "알람: 멈춤 요약",
                 "알람: 텔레그램 설정", "텔레그램 설정 맞춰짐", "진입 대기 → 결과(같은 메시지가 바뀜)", "진입 쉼 시작",
                 "진입 쉼 끝"):
        assert kind in titles, kind
    for block in text.split("\n\n━━ "):
        head, body = block.split("\n", 1)
        assert head.endswith(("· 소리 ━━", "· 무음 ━━"))
        assert ("소리" in head) == body.startswith("🚨"), head
        first = body.split("\n")[0]
        assert "~" not in first.split("·")[0] and "#" not in first           # no member label or hash
        if body.startswith("🚨") and not body.startswith("🚨 실거래 일일 점검"):
            assert any(ln.startswith("지금 할 일:") for ln in body.split("\n")), head
    assert "자세히:" not in text.split("\n")[0]
    assert LC.main(["preview"]) == 0


def test_the_preview_executor_tables_match_the_executor():
    from paperbot import livepreview as PV
    from paperbot.executor import ExecStore
    import tempfile
    d = tempfile.mkdtemp()
    real = ExecStore(os.path.join(d, "real.db"), lock=False)
    a = sqlite3.connect(os.path.join(d, "pv.db"))
    a.executescript(PV.EXEC_SCHEMA)
    for table in ("events", "requests", "trades", "halts", "state", "fills", "funding", "equity"):
        cols = [r[1] for r in real.conn.execute(f"PRAGMA table_info({table})")]
        assert cols == [r[1] for r in a.execute(f"PRAGMA table_info({table})")], table
    real.close()
    a.close()


# ---------------------------------------------------------------- 4. 못 탄 신호: one quiet line in the morning check
def test_the_morning_check_has_one_quiet_line_about_the_signals_not_taken(tmp_path, monkeypatch):
    """The watcher's pass (paperbot/livemissed.py) on the world where the combined bot really ran (tests/livesim_world.py,
    research mode: every group), then the morning check of that day: one line, never loud, nothing per signal; a day
    without such signals has no line."""
    import sys as _sys
    from pathlib import Path

    from paperbot import events
    from paperbot import livemissed as LM
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import livesim_world as W
    csv = tmp_path / "macro.csv"
    csv.write_text(W.MACRO_CSV, encoding="utf-8")
    monkeypatch.setattr(events, "PATH", Path(csv))
    events.reset()
    monkeypatch.setattr(LC, "load_executors", lambda *a, **k: [])
    w = W.build(str(tmp_path / "w"), until=W.END_R, research=True)
    w.close()
    src = LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=w.paper_db, rule_db=w.rule_db, combo_config=str(tmp_path / "no.json"),
                     cache=str(tmp_path / "cache.db"), shadow_glob=str(tmp_path / "shadow-*.db"), executors=[])
    conn = LC.open_out(src.db)
    LM.missed_pass(src, conn, W.END_R + 5 * W.MIN, log=lambda s: None)
    conn.close()
    n = ListNotifier()
    out = LC.run_check(src, day="2026-10-19", now_ms=W.T0 + W.DAY + 10 * W.MIN, no_replay=True, notifier=n)
    line = "어제 못 탄 신호 9개(가상): 한 번에 하나 1승 2패 · 연구 조건 2승 1패 · 돌파 없음 1승 0패 · 쉬는 시간 0승 1패 · 늦음 1승 0패 · 실제로 탄 거래 3승 1패"
    assert line in out["text"].splitlines() and out["level"] == INFO and not any("못 탄" in x for x in out["loud"])
    assert len(n.messages) == 1                                   # the morning message only: nothing per signal
    out = LC.run_check(src, day="2026-10-18", now_ms=W.T0 + 10 * W.MIN, no_replay=True, notifier=ListNotifier())
    assert "못 탄 신호" not in out["text"]
    events.reset()
