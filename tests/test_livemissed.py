"""paperbot/livemissed.py: 못 탄 신호 성적, the 1-minute watcher's pass over the paper account's SKIPPED signals (one
position at a time, or another signal of the same minute went in) and the owners' ``show``.

On the world where the combined paper bot really ran (tests/livesim_world.py: BTC long entered with an ETH short of the same
minute skipped, a SOL long skipped while BTC was open, a DOGE long skipped beside a BCH long):
- the pass stores one row per skipped signal: why in the owners' words ("이미 BTC 롱 보유 중"), the virtual result of the paper
  bot's own engine (the same numbers as paperbot/livesim.py), the trade that had the place with its result; entered
  signals and the coin-flip twin's skips are not rows;
- an open virtual trade is simulated again every pass until it closes, then never again; the trade that had the place is
  refreshed while it is open;
- errors are stored with their reason (a row, or the pass in missed_meta) and tried again later; the pass never raises;
  the work per pass is capped and said; no 1m bars -> no_data;
- the CLI: ``show`` (summary and rows in Korean, 수집 전 without the file) and ``run``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livesim_world as W  # noqa: E402
from paperbot import livecheck as LC  # noqa: E402
from paperbot import livemissed as LM  # noqa: E402
from paperbot import livesim as LS  # noqa: E402
from paperbot.livepnl import open_ro  # noqa: E402

MIN, DAY = W.MIN, W.DAY
NOW = W.END + 5 * MIN


def _src(w, folder):
    return LC.Sources(db=os.path.join(folder, "livecheck.db"), paper_db=w.paper_db, rule_db=w.rule_db, combo_config="/nonexistent/combo.json")


def _rows(conn) -> dict:
    return {r["symbol"]: r for r in LM.read_rows(conn, 0)}


@pytest.fixture
def world(tmp_path):
    w = W.build(str(tmp_path / "w"))
    yield w
    w.close()


def test_the_pass_stores_each_skipped_signal_with_why_result_and_the_trade_taken(world, tmp_path):
    src = _src(world, str(tmp_path))
    conn = LC.open_out(src.db)
    try:
        res = LM.missed_pass(src, conn, NOW, log=lambda s: None)
        assert (res["new"], res["errors"], res["capped"], res["rows"]) == (3, 0, False, 3) and "error" not in res
        rows = _rows(conn)
        assert set(rows) == {"ETHUSDT", "SOLUSDT", "DOGEUSDT"}                   # skipped only, COMBO@mix only
        trades = {t["symbol"]: t for t in LM.read_paper(open_ro(world.paper_db), 0)["trades"]}
        btc = trades["BTCUSDT"]
        sol, eth, doge = rows["SOLUSDT"], rows["ETHUSDT"], rows["DOGEUSDT"]
        assert (sol["why_kind"], sol["why"]) == ("held", "이미 BTC 롱 보유 중")
        assert (eth["why_kind"], eth["why"]) == ("lost", "같은 분에 BTC 롱 신호가 먼저 들어감")
        assert doge["why"] == "같은 분에 BCH 롱 신호가 먼저 들어감"
        assert (sol["state"], sol["reason"], sol["win"]) == ("closed", "LOCK", True) and sol["reason_ko"] == "계단 익절"
        assert (eth["state"], eth["reason"], eth["win"]) == ("closed", "SL", False)
        assert doge["state"] == "open" and doge["roe"] < 0 and doge["exit_ts"] is None and doge["hold_ms"] > 0
        for r in (sol, eth):
            assert r["taken"]["id"] == btc["id"] and r["taken"]["state"] == "closed" and r["taken"]["roe"] == btc["roe"]
            assert r["hold_ms"] == r["exit_ts"] - r["entry_ts"] and r["t"] == r["step_ts"] and r["sims"] == 1
        # the same numbers as livesim on the same signal, with the wallet of that moment (BTC still open: the initial 1,000)
        pc = open_ro(world.paper_db)
        sig = json.loads(pc.execute("SELECT data FROM outcomes WHERE account_id = ? AND symbol = 'SOLUSDT'", (LM.ACCOUNT,)).fetchone()[0])["signal"]
        run = json.loads(pc.execute("SELECT data FROM state WHERE k = 'combo_run'").fetchone()[0])
        pc.close()
        rc = open_ro(world.rule_db)
        direct = LS.simulate_db(LS.rig_of(run["config"], taker_fee=run["taker_fee"]), LS.signal_of(sig), rc, sol["step_ts"], wallet=1000.0)
        rc.close()
        assert (sol["roe"], sol["pnl"], sol["exit_ts"], sol["exit_price"]) == (direct["exit"]["roe"], direct["exit"]["pnl"],
                                                                               direct["exit"]["ts"], direct["exit"]["price"])
        stored = conn.execute("SELECT wallet, data, signal FROM missed WHERE symbol = 'SOLUSDT'").fetchone()
        assert stored[0] == 1000.0 and json.loads(stored[2]) == sig and json.loads(stored[1])["funding"] == "excluded"
        path = LM.read_path(conn, sol["key"])
        assert path[0]["t"] == sol["entry_ts"] and path[-1]["exit"] is True and path[-1]["roe"] == sol["roe"]
        assert any(p["lock"] for p in path) and LM.read_path(conn, "nope") == []
        assert conn.execute("SELECT wallet FROM missed WHERE symbol = 'DOGEUSDT'").fetchone()[0] == pytest.approx(trades["ETHUSDT"]["equity_after"])
        k, ts, meta = conn.execute("SELECT k, ts, data FROM missed_meta WHERE k = 'pass'").fetchone()
        meta = json.loads(meta)
        assert ts == NOW and meta["state"] == "ok" and meta["config"] == "기록" and meta["funding"] == "excluded"
        assert json.loads(conn.execute("SELECT data FROM missed_meta WHERE k = 'first'").fetchone()[0])["since"] == LM.window_start(NOW)
    finally:
        conn.close()


def test_open_rows_are_simulated_again_until_closed_then_never_again(tmp_path, monkeypatch):
    w = W.build(str(tmp_path / "w"), until=W.B1 + 20 * MIN)          # SOL skipped at B1+15m while BTC is still open
    src = _src(w, str(tmp_path))
    conn = LC.open_out(src.db)
    calls = []
    real = LS.simulate_db
    monkeypatch.setattr(LS, "simulate_db", lambda *a, **k: calls.append(a[1].symbol) or real(*a, **k))
    try:
        t1 = W.B1 + 21 * MIN
        LM.missed_pass(src, conn, t1)
        sol = _rows(conn)["SOLUSDT"]
        assert sol["state"] == "open" and sol["sims"] == 1 and sol["last_ts"] == W.B1 + 19 * MIN
        assert sol["taken"]["state"] == "open" and sol["taken"]["id"] is None and sol["why"] == "이미 BTC 롱 보유 중"
        assert sol["taken"]["roe"] is not None                                 # the open BTC position's net ROE at its last mark
        w.run_to(W.B1 + 40 * MIN)                                          # BTC closed (LOCK), SOL still open
        LM.missed_pass(src, conn, W.B1 + 41 * MIN)
        sol = _rows(conn)["SOLUSDT"]
        assert sol["state"] == "open" and sol["sims"] == 2 and sol["taken"]["state"] == "closed" and sol["taken"]["reason"] == "LOCK"
        w.run_to(W.END)
        res = LM.missed_pass(src, conn, NOW)
        sol = _rows(conn)["SOLUSDT"]
        assert sol["state"] == "closed" and sol["sims"] == 3 and res["closed"] >= 1
        before = conn.execute("SELECT * FROM missed WHERE symbol = 'SOLUSDT'").fetchone()
        calls.clear()
        LM.missed_pass(src, conn, NOW + MIN)
        LM.missed_pass(src, conn, NOW + 2 * MIN)
        assert "SOLUSDT" not in calls and "ETHUSDT" not in calls and calls == ["DOGEUSDT", "DOGEUSDT"]     # only the open one
        assert conn.execute("SELECT * FROM missed WHERE symbol = 'SOLUSDT'").fetchone() == before           # closed: never again
    finally:
        conn.close()
        w.close()


def test_errors_are_stored_with_their_reason_and_tried_again_later(world, tmp_path, monkeypatch):
    src = _src(world, str(tmp_path))
    conn = LC.open_out(src.db)
    try:
        def boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr(LS, "simulate_db", boom)
        res = LM.missed_pass(src, conn, NOW, log=lambda s: None)
        rows = _rows(conn)
        assert res["errors"] == 3 and {r["state"] for r in rows.values()} == {"error"}
        assert rows["SOLUSDT"]["error"] == "RuntimeError: boom" and rows["SOLUSDT"]["why"] == "이미 BTC 롱 보유 중"
        assert LM.result_ko(rows["SOLUSDT"]) == "못 읽음 (RuntimeError: boom)"
        monkeypatch.undo()
        LM.missed_pass(src, conn, NOW + MIN)                          # within RETRY_MS: not yet
        assert {r["state"] for r in _rows(conn).values()} == {"error"}
        LM.missed_pass(src, conn, NOW + LM.RETRY_MS + MIN)
        rows = _rows(conn)
        assert (rows["SOLUSDT"]["state"], rows["ETHUSDT"]["state"], rows["DOGEUSDT"]["state"]) == ("closed", "closed", "open")
        assert rows["SOLUSDT"]["error"] == "" and rows["SOLUSDT"]["sims"] == 2
    finally:
        conn.close()


def test_a_missing_rule_file_or_config_is_a_row_error_a_missing_paper_db_or_a_broken_pass_never_raises(world, tmp_path, monkeypatch):
    src = _src(world, str(tmp_path))
    src.rule_db = str(tmp_path / "nope-paper3.db")
    conn = LC.open_out(src.db)
    try:
        LM.missed_pass(src, conn, NOW)
        r = _rows(conn)["SOLUSDT"]
        assert r["state"] == "error" and r["error"].startswith("규칙봇 1분봉 파일을 못 읽음")
    finally:
        conn.close()
    (tmp_path / "b").mkdir()
    src = _src(world, str(tmp_path / "b"))
    src.paper_db = str(tmp_path / "nope-live-ac.db")
    conn = LC.open_out(src.db)
    try:
        res = LM.missed_pass(src, conn, NOW)
        assert "error" not in res and res["new"] == 0
        assert json.loads(conn.execute("SELECT data FROM missed_meta WHERE k = 'pass'").fetchone()[0])["state"] == "no_paper"
        src.paper_db = world.paper_db
        monkeypatch.setattr(LM, "read_paper", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
        conn.execute("CREATE TABLE other_pass (x INTEGER)")
        conn.commit()
        conn.execute("INSERT INTO other_pass VALUES (1)")            # another watcher pass's work, not committed yet
        said = []
        res = LM.missed_pass(src, conn, NOW, log=said.append)
        assert res["error"] == "OperationalError: database is locked" and said and "실패" in said[0]
        meta = json.loads(conn.execute("SELECT data FROM missed_meta WHERE k = 'pass'").fetchone()[0])
        assert meta["state"] == "error" and "locked" in meta["error"]
        assert conn.execute("SELECT COUNT(*) FROM other_pass").fetchone()[0] == 1          # never rolled back by this pass
    finally:
        conn.close()
    monkeypatch.undo()
    (tmp_path / "c").mkdir()
    src = _src(world, str(tmp_path / "c"))
    conn = LC.open_out(src.db)
    monkeypatch.setattr(LM, "config_of", lambda paper, f: (None, None, ""))
    try:
        LM.missed_pass(src, conn, NOW)
        r = _rows(conn)["SOLUSDT"]
        assert r["state"] == "error" and "설정을 못 읽음" in r["error"]
    finally:
        conn.close()



def test_the_work_per_pass_is_capped_and_said(world, tmp_path):
    src = _src(world, str(tmp_path))
    conn = LC.open_out(src.db)
    said = []
    try:
        res = LM.missed_pass(src, conn, NOW, cap=1, log=said.append)
        assert (res["new"], res["capped"], res["left"]) == (1, True, 2) and len(_rows(conn)) == 1
        assert said and "1개만 계산" in said[0] and "남은 2개" in said[0]
        res = LM.missed_pass(src, conn, NOW + MIN, cap=1, log=said.append)
        assert (res["new"], res["left"]) == (1, 1) and len(_rows(conn)) == 2            # oldest first: ETH, then SOL
        meta = json.loads(conn.execute("SELECT data FROM missed_meta WHERE k = 'pass'").fetchone()[0])
        assert meta["capped"] is True and meta["left"] == 1
        res = LM.missed_pass(src, conn, NOW + 2 * MIN, cap=2, log=said.append)
        assert (res["new"], res["capped"]) == (1, False) and _rows(conn)["DOGEUSDT"]["state"] == "open"
        res = LM.missed_pass(src, conn, NOW + 3 * MIN, cap=1, log=said.append)
        assert (res["resim"], res["new"]) == (1, 0) and _rows(conn)["DOGEUSDT"]["sims"] == 2    # an open one goes first
    finally:
        conn.close()


def test_no_rule_bars_at_the_entry_minute_is_no_data(world, tmp_path):
    with sqlite3.connect(world.rule_db) as c:
        c.execute("DELETE FROM live_bars WHERE symbol = 'SOLUSDT'")
    src = _src(world, str(tmp_path))
    conn = LC.open_out(src.db)
    try:
        LM.missed_pass(src, conn, NOW)
        r = _rows(conn)["SOLUSDT"]
        assert r["state"] == "no_data" and r["roe"] is None and LM.result_ko(r) == "1분봉 없음" and "1분봉이 없어요" in r["note"]
    finally:
        conn.close()


def test_the_dry_run_copy_in_memory_works_too(world):
    conn = sqlite3.connect(":memory:")
    res = LM.missed_pass(LC.Sources(db="-", paper_db=world.paper_db, rule_db=world.rule_db, combo_config="-"), conn, NOW)
    assert res["new"] == 3 and len(_rows(conn)) == 3
    conn.close()


def test_window_start_is_seven_kst_days():
    mon_0930_kst = W.T0 + 30 * MIN                       # 2026-10-19 09:30 KST (Monday)
    assert LM.window_start(mon_0930_kst) == W.T0 - 9 * W.H - 6 * DAY      # 10/13 00:00 KST
    assert LM.window_start(W.T0 - 9 * W.H) == W.T0 - 9 * W.H - 6 * DAY   # 10/19 00:00 KST exactly
    assert LM.window_start(W.T0 - 9 * W.H - 1) == W.T0 - 9 * W.H - 7 * DAY


def test_summary_counts_and_words():
    rows = [{"t": 10, "state": "closed", "roe": 0.12, "pnl": 5.0, "symbol": "BTCUSDT", "side": 1, "step_ts": 10},
            {"t": 10, "state": "closed", "roe": -0.4, "pnl": -9.0, "symbol": "BTCUSDT", "side": 1, "step_ts": 10},
            {"t": 20, "state": "open", "roe": 0.03, "pnl": None, "symbol": "ETHUSDT", "side": -1, "step_ts": 20},
            {"t": 30, "state": "no_data", "roe": None, "pnl": None, "symbol": "SOLUSDT", "side": 1, "step_ts": 30},
            {"t": 1, "state": "closed", "roe": 0.5, "pnl": 9.0, "symbol": "SOLUSDT", "side": 1, "step_ts": 1}]
    trades = [{"entry_time": 5, "roe": 0.1, "pnl": 1.0}, {"entry_time": 2, "roe": -0.3, "pnl": -2.0}]
    s = LM.summary_of(rows, trades, 7, since=5)
    m, t = s["missed"], s["taken"]
    assert (m["n"], m["closed"], m["wins"], m["losses"], m["open"], m["no_data"], m["moments"]) == (4, 2, 1, 1, 1, 1, 3)
    assert m["roe_sum"] == pytest.approx(-0.28) and m["roe_mean"] == pytest.approx(-0.14) and m["win_rate"] == 0.5 and m["small"]
    assert (t["n"], t["closed"], t["wins"], t["open"], t["roe_sum"]) == (2, 1, 1, 1, pytest.approx(0.1))
    assert LM.taken_ko(None) == "그때 탄 거래: 기록 못 찾음"
    assert LM.taken_ko({"symbol": "BTCUSDT", "side": 1, "state": "closed", "roe": 0.12}) == "그때 탄 거래: BTC 롱 +12.0%"
    assert LM.taken_ko({"symbol": "ETHUSDT", "side": -1, "state": "open", "roe": -0.031}) == "그때 탄 거래: ETH 숏 진행 중 −3.1%"
    assert LM.result_ko({"state": "closed", "win": False, "roe": -0.38, "reason_ko": "손절"}) == "❌ −38.0% 손절"
    assert LM.result_ko({"state": "open", "roe": 0.04}) == "진행 중 +4.0%"


def test_cli_run_and_show(world, tmp_path, capsys):
    db = str(tmp_path / "livecheck.db")
    code, text = LM.show_text(db, world.paper_db, NOW)
    assert code == 1 and "1분 감시가 아직 기록 전" in text
    args = ["--db", db, "--paper-db", world.paper_db, "--rule-db", world.rule_db, "--combo-config", "/nonexistent/combo.json"]
    assert LM.main(["run"] + args) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["new"] == 3 and out["errors"] == 0
    assert LM.main(["show", "--days", "0"] + args) == 0
    text = capsys.readouterr().out
    for words in ("못 탄 신호 성적 (기록 전체", "실제로 탄 거래: 3번 · 끝남 3 (2승 1패, 승률 67%)", "못 탄 신호(가상): 3개 · 끝남 2 (1승 1패, 승률 50%)",
                  "진행 중 1", "표본 적음(20번 미만)", "SOL 롱 OBV_S 15분 · 이미 BTC 롱 보유 중 → ✅ +", "계단 익절",
                  "그때 탄 거래: BTC 롱 +19.8%", "ETH 숏 OBV_S 15분 · 같은 분에 BTC 롱 신호가 먼저 들어감 → ❌ −22.2% 손절",
                  "가상 결과예요: 페이퍼 봇과 같은 엔진·같은 1분봉으로", "펀딩비는 빠져 있어요"):
        assert words in text, words
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE missed")
    conn.commit()
    conn.close()
    code, text = LM.show_text(db, world.paper_db, NOW)
    assert code == 1 and "missed 표가 없음" in text
