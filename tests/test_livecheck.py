"""실거래 일일 점검 (paperbot/livecheck.py, paperbot/livereplay.py): hand-made databases in the real schemas (the paper
bot's paperbot.store3, the executor's paperbot.executor.ExecStore), an injected replay and market, no network."""

import json
import os
import sqlite3
from dataclasses import asdict

import pytest

from paperbot import livecheck as LC
from paperbot import livereplay as LR
from paperbot.models import Signal, SignalOutcome, TradeRecord
from paperbot.notify import CRITICAL, INFO, ListNotifier, telegram_text
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
    assert "멈춤(낙폭 50%)" in text and "사람이 풀어야 합니다" in text
    assert "livecheck show 결과를 개발자에게 보내 주세요" in text and "거래소 앱의 체결 내역" in text


def test_a_crash_of_the_replay_still_sends_the_rest(tmp_path, capsys):
    src, _rep = _setup(tmp_path)

    def broken(*a):
        raise KeyError("members")
    out = LC.run_check(src, day="2026-10-20", now_ms=NOW, replay=broken, notifier=ListNotifier())
    assert "대조: 못 함 — 다시 계산 중 오류(KeyError: 'members'); 개발자에게 알려 주세요" in out["text"]
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
    assert "대조: 못 함 — 바이낸스에 연결하지 못해 다시 계산을 못 했습니다(URLError: no route)" in out["text"]
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
