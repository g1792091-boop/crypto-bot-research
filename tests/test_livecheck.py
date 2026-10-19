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
    level, text = n.messages[0]
    assert level == CRITICAL and text.startswith("실거래가 페이퍼를 따라가지 않았습니다 · 바이비트")
    assert "페이퍼 진입 13:55 BTC 롱 F15_LON_BRK 1시간 (5분 지남)" in text
    assert "신호등 근거 쌓는 중(0/20번, 그동안 모두 따라감) · 멈춤 아님" in text
    assert "실행기 기록: 이 진입에 대한 기록 없음" in text
    assert "다음: 거래소 앱에서 포지션을 확인하고 sudo journalctl -u paperbot-executor -n 50" in text
    assert telegram_text(CRITICAL, text)[1].startswith("🚨 실거래가 페이퍼를 따라가지 않았습니다")
    assert LC.run_watch(src, now_ms=T + 2 * MIN, notifier=n, units=Units(), exists=lambda p: False) == []
    assert len(n.messages) == 1                                         # once per condition
    # the executor followed after all: the condition clears without a message
    from paperbot.executor import ExecStore
    st = ExecStore(src.executors[0].db, lock=False)
    st.trade_open({"key": key, "symbol": BTC, "side": 1, "qty": 1.0, "leverage": 40, "entry_ts": T})
    st.commit()
    st.close()
    out = LC.run_watch(src, now_ms=T + 4 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert keys(out, "clear") == [f"follow:bybit:{key}"] and len(n.messages) == 1
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
    assert "신호등 초록(최근 20번 20승 100%, 기준 85%)" in n.messages[0][1]


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
    text = n.messages[0][1]
    assert "(20분 지남, 페이퍼는 이미 청산)" in text
    assert "실행기 기록: paper 진입이 200초 전이라 따라 하지 않습니다" in text
    # an hour later the trade is out of the window: cleared silently
    fresh(src, T + H1)
    _set_bot(src.executors[0].db, ts=T + H1 - MIN)
    out = LC.run_watch(src, now_ms=T + H1, notifier=n, units=Units(), exists=lambda p: False)
    assert keys(out, "clear") == [f"follow:bybit:{LC.ACCOUNT}|{BTC}|{entry}"] and len(n.messages) == 1


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
    level, text = n.messages[-1]
    assert level == INFO and text.startswith("🧾 손실 카드 · F15_LON_BRK 1시간 (#1, 돌파)")
    assert "BTC 롱 · 진입 10/20 12:00 → 청산 13:30 (1.5시간)" in text
    assert "순ROE -40.0% · 손절 · 손절 atr3, 거리 1.00%" in text
    assert "장세 강상승 · 진입 14시 · 먼저 +16.0%까지 갔음" in text
    assert "백테스트 승률 90.0% (처음 보는 2025-26 80%, 40번) · 손실 보통 -45% / 최악 -60% · 손절까지 보통 1.5시간" in text
    assert "이 장세 92%(50번) · 이 코인 90%(60번)" in text and "약한 자리" not in text
    assert "연속 손실 1번째 (백테스트 최장 3번, 처음 보는 기간 5번)" in text
    assert "바이비트: 따라감, 순ROE -42.0%, 진입 +5.0bps / 청산 +3.0bps" in text
    assert "MEXC: 신호등이 막음(따라가지 않음)" in text and text.endswith("판정: 정상 범위 손실")
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
    assert "→ 백테스트에서도 약한 자리" in LC.card_text(c)
    c = LC.build_card(t, meta, [prev, t], EXP, [])
    assert c["label"] == "연속 손실 2번째" and c["loud"]
    c = LC.build_card(dict(t, roe=-0.7), meta, [t], EXP, [])
    assert c["label"] == "평소보다 큰 손실" and c["loud"]
    gap = [{"status": "followed", "label": "바이비트", "pnl": -5.0, "entry_bps": 14.0, "exit_bps": 1.0,
            "exit_ts": T}]
    c = LC.build_card(t, meta, [prev, t], EXP, gap)
    assert c["label"] == "실거래-페이퍼 차이" and c["loud"]
    text = LC.card_text(c)
    assert text.startswith("손실 카드 · F15_LON_BRK 1시간") and telegram_text(CRITICAL, text)[1].startswith("🚨 손실 카드")
    assert LC.live_gap([{"status": "followed", "pnl": 0.3, "entry_bps": 1.0, "exit_bps": 1.0, "exit_ts": T}], T)
    assert not LC.live_gap([{"status": "followed", "pnl": -3, "entry_bps": 4.0, "exit_bps": -2.0, "exit_ts": T}], T)
    no_ref = LC.build_card(dict(t, strategy="NEW"), meta, [t], EXP, [])
    assert "백테스트 기준표에 이 매매법이 없음" in LC.card_text(no_ref) and no_ref["label"] == "정상 범위 손실"


def test_a_card_waits_for_the_executor_to_close(tmp_path):
    entry, exit_ = T - H1, T - 5 * MIN
    open_x = xtrade(entry, fills=False)
    open_x["exit_ts"] = None
    src = card_setup(tmp_path, [loss(entry, exit_)], [entered(entry)], x_trades=[open_x])
    n = ListNotifier()
    LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    assert not [m for _l, m in n.messages if "손실 카드" in m]
    fresh(src, T + 31 * MIN)
    out = LC.run_watch(src, now_ms=T + 31 * MIN, notifier=n, units=Units(), exists=lambda p: False)
    assert [e for e, *_ in out].count("card") == 1
    assert "바이비트: 따라감, 아직 닫는 중" in [m for _l, m in n.messages if "손실 카드" in m][0]


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
    first = [ln for ln in mem.splitlines() if ln.startswith("먼저 끌 것")][0]
    assert first == ("먼저 끌 것(실험): sudo systemctl stop paperbot-agents paperbot-combo-shadow@b "
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
    assert LC.memory_lines([("paperbot-live3.service", 10)])[1].startswith("끌 만한 실험 서비스가 켜져 있지 않습니다")
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
    assert [m for _l, m in n.messages if m.startswith("🧾 손실 카드")]
