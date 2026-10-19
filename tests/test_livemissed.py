"""paperbot/livemissed.py: 못 탄 신호 성적, the 1-minute watcher's pass over every signal the paper account did not take (by
group: 한 번에 하나 · 연구 조건 밖 · 돌파 없음 · 쉬는 시간 · 늦음·재시작) and the paper trades the executors did not follow, the
morning check's one line and the owners' ``show``.

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
On the research world (the same bot with five research settings, its research data on these prices and a US macro release:
every FILTERED / WAITING row and the late REJECTED outcome written by combo.py's own code):
- each group is stored and simulated (research filter, signal-bar size, switched-off bucket in words, break that never came
  labelled "돌파를 안 기다리고 바로 탔다면", macro pause, late), or rebuild_failed with its reason (a setting no longer in the
  config, the swing window's bars missing, a break confirmed too late);
- the rebuilt signal of an ENTERED research swing-stop signal equals the one the bot built and gives the bot's own trade;
- the labels equal combo.resolve_members' on live settings; the executors' misses from the paper result (their own
  reasons); an older livecheck.db is altered in place; the oldest unfinished first under the cap; the morning line.
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


@pytest.fixture(autouse=True)
def _no_server_executors(monkeypatch):
    """The executors of this machine's /etc configs are never read here: a test names its own."""
    monkeypatch.setattr(LC, "load_executors", lambda *a, **k: [])


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
    m, t = next(g for g in s["groups"] if g["id"] == "one"), s["taken"]
    assert (m["n"], m["closed"], m["wins"], m["losses"], m["open"], m["no_data"], m["moments"]) == (4, 2, 1, 1, 1, 1, 3)
    assert m["roe_sum"] == pytest.approx(-0.28) and m["roe_mean"] == pytest.approx(-0.14) and m["win_rate"] == 0.5 and m["small"]
    assert (t["n"], t["closed"], t["wins"], t["open"], t["roe_sum"]) == (2, 1, 1, 1, pytest.approx(0.1))
    assert m["read_ko"] == "한 번에 하나 규칙이 막은 신호: 가상 1승 1패 · 순ROE 합 −28.0% → 이번엔 막은 게 손해를 줄였어요 · 표본 적음 · 대부분 운"
    assert [g["id"] for g in s["groups"]] == list(LM.GROUPS) and s["all"]["n"] == 4
    assert next(g for g in s["groups"] if g["id"] == "research")["read_ko"] == "연구 조건이 막은 신호: 이 기간에 없어요"
    big = [{"t": 10, "state": "closed", "roe": 0.1, "pnl": 1.0, "grp": "research"} for _ in range(12)] + \
          [{"t": 10, "state": "closed", "roe": -0.2, "pnl": -2.0, "grp": "research"} for _ in range(9)]
    r = next(g for g in LM.summary_of(big, [], None, 0)["groups"] if g["id"] == "research")
    assert r["read_ko"] == "연구 조건이 막은 신호: 가상 12승 9패 · 순ROE 합 −60.0% → 이번엔 막은 게 손해를 줄였어요"   # 21 closed: no small word
    assert LM.read_ko("nobreak", {**r, "roe_sum": 0.3}).endswith("→ 이번엔 돌파를 기다린 게 이익을 놓쳤어요")
    assert LM.read_ko("exec", {**r, "roe_sum": 0.3}).startswith("실행기가 안 따라간 페이퍼 거래: 페이퍼 결과 12승 9패")
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
    for words in ("못 탄 신호 성적 (기록 전체", "실제로 탄 거래: 3번 · 2승 1패 (승률 67%)", "- 한 번에 하나 3개 · 진행 중 1: 한 번에 하나 규칙이 막은 신호: 가상 1승 1패",
                  "표본 적음(20번 미만)", "[한 번에 하나] SOL 롱 OBV_S 15분 · 이미 BTC 롱 보유 중 → ✅ +", "계단 익절",
                  "그때 탄 거래: BTC 롱 +19.8%", "ETH 숏 OBV_S 15분 · 같은 분에 BTC 롱 신호가 먼저 들어감 → ❌ −22.2% 손절",
                  "가상 결과예요: 페이퍼 봇과 같은 엔진·같은 1분봉으로", "필터는 5년 시험에서", "펀딩비는 빠져 있어요"):
        assert words in text, words
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE missed")
    conn.commit()
    conn.close()
    code, text = LM.show_text(db, world.paper_db, NOW)
    assert code == 1 and "missed 표가 없음" in text


# ================================================================ every not-entered signal (the research world)
NOW_R = W.END_R + 5 * MIN


@pytest.fixture(scope="module")
def rworld(tmp_path_factory):
    from pathlib import Path

    from paperbot import events
    d = tmp_path_factory.mktemp("rworld")
    csv = d / "macro.csv"
    csv.write_text(W.MACRO_CSV, encoding="utf-8")
    old = events.PATH
    events.PATH = Path(csv)
    events.reset()
    try:
        w = W.build(str(d / "w"), until=W.END_R, research=True)
    finally:
        events.PATH = old
        events.reset()
    yield w
    w.close()


def _rpass(w, folder, **kw):
    src = LC.Sources(db=os.path.join(folder, "livecheck.db"), paper_db=w.paper_db, rule_db=w.rule_db, combo_config="-",
                     executors=kw.pop("executors", []))
    conn = LC.open_out(src.db)
    res = LM.missed_pass(src, conn, kw.pop("now", NOW_R), log=lambda s: None, **kw)
    return src, conn, res


def _by(conn) -> dict:
    return {(r["grp"], r["symbol"], (r["t"] - W.T0) // MIN): r for r in LM.read_rows(conn, 0)}


def test_every_group_is_stored_and_simulated_with_its_why(rworld, tmp_path):
    _src, conn, res = _rpass(rworld, str(tmp_path))
    try:
        assert "error" not in res and res["errors"] == 0 and res["rows"] == 9
        rows = _by(conn)
        r0 = (W.R0 - W.T0) // MIN
        want = {("research", "BTCUSDT", r0): ("filter", "연구 조건 밖 (필요: 주말만)", "LOCK"),
                ("pause", "ETHUSDT", r0): ("macro", "경제 발표 앞뒤 30분: 소비자물가(CPI) 2026-10-19T04:00:00Z", "SL"),
                ("research", "SOLUSDT", r0 + 45): ("disp", "연구 조건 밖: 신호봉 크기", "SL"),
                ("research", "LTCUSDT", r0 + 60): ("off", "끈 구간: 시각 14시", "LOCK"),
                ("nobreak", "DOGEUSDT", r0 + 75): ("nobreak", "돌파 없음(신호봉 시간 안에)", "LOCK"),
                ("late", "SOLUSDT", r0 + 105): ("late", "기준 가격이 200초 지나 진입 안 함 (재시작 따라잡기 등)", "LOCK")}
        for k, (kind, why, reason) in want.items():
            r = rows[k]
            assert (r["why_kind"], r["why"], r["state"], r["reason"]) == (kind, why, "closed", reason), (k, r)
            assert r["entry_ts"] == r["t"] and r["taken"] is None and r["sims"] == 1
        assert rows[("nobreak", "DOGEUSDT", r0 + 75)]["how_ko"] == "돌파를 안 기다리고 바로 탔다면 (가상)"
        assert rows[("nobreak", "DOGEUSDT", r0 + 75)]["side"] == -1 and rows[("research", "LTCUSDT", r0 + 60)]["stop_rule"].startswith("swing 2 bars")
        assert rows[("research", "BTCUSDT", r0)]["leverage"] == 40 and rows[("research", "BTCUSDT", r0)]["stop_rule"].startswith("2 x ATR")
        assert {k[0] for k in rows} == {"one", "research", "pause", "nobreak", "late"}            # no exec: no executor named
        assert not any(r["symbol"] == "BCHUSDT" and r["t"] == W.R0 + 120 * MIN for r in rows.values())   # entered: not a row
    finally:
        conn.close()


def test_a_rebuilt_signal_is_the_bots_own_and_gives_its_trade(rworld):
    """The research swing-stop setting the bot ENTERED at R0+120m: rebuilt from its signal_log row like a filtered one would be,
    it equals the signal the bot built (stop rule, swing window from the bars it stepped on, reference price …) and the
    simulation gives the bot's own trade."""
    import dataclasses
    pc, rc = open_ro(rworld.paper_db), open_ro(rworld.rule_db)
    try:
        run = json.loads(pc.execute("SELECT data FROM state WHERE k = 'combo_run'").fetchone()[0])
        rig, mm = LS.rig_of(run["config"], taker_fee=run["taker_fee"]), LM.member_map(run["config"])
        cur = pc.execute("SELECT * FROM signal_log WHERE strategy LIKE 'F12_MSS_DISP@%'")
        row = dict(zip([c[0] for c in cur.description], cur.fetchone()))
        step, data = pc.execute("SELECT step_ts, data FROM outcomes WHERE account_id = ? AND status = 'ENTERED' AND step_ts = ?",
                                (LM.ACCOUNT, W.R0 + 120 * MIN)).fetchone()
        bot = json.loads(data)["signal"]
        sig, why = LM.rebuild(row, rig, mm, rc, row["bar_close"])
        assert why is None
        mine = json.loads(json.dumps(dataclasses.asdict(sig), default=str))
        for k in ("ts", "symbol", "timeframe", "strategy_id", "side", "score", "atr"):
            assert mine[k] == bot[k], k
        for k in ("ref_price", "ref_time", "rstop", "rswing", "member", "member_order", "research"):
            assert mine["meta"][k] == bot["meta"][k], k
        trades = [json.loads(d) for (d,) in pc.execute("SELECT data FROM trades WHERE account_id = ? ORDER BY exit_time", (LM.ACCOUNT,))]
        t = trades[-1]
        r = LS.simulate_db(rig, sig, rc, step, wallet=trades[-2]["equity_after"])
        assert (r["entry"]["price"], r["entry"]["stop"], r["exit"]["ts"], r["exit"]["price"], r["exit"]["reason"]) == \
            (t["entry_price"], t["stop_initial"], t["exit_time"], t["exit_price"], t["exit_reason"])
        assert r["exit"]["roe"] == pytest.approx(t["roe"], abs=1e-12) and r["exit"]["pnl"] == pytest.approx(t["pnl"], abs=1e-9)
    finally:
        pc.close()
        rc.close()


def test_labels_equal_the_bots_own_resolve_members_on_live_settings():
    from paperbot import combo as C
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "combo.live-ac.json"), encoding="utf-8") as fh:
        sub = json.load(fh)["members"][:3]
    ms = C.resolve_members(sub, C.CANDIDATES_FILE)
    mm = LM.member_map({"members": sub})
    assert [(m.label, m.order) for m in ms] == [(k, v[0]) for k, v in mm["research"].items()]
    assert all(mm["research"][m.label][1] == m.research for m in ms)


def test_rebuild_failed_never_guesses(rworld, tmp_path):
    import shutil
    d = tmp_path / "copy"
    d.mkdir()
    for f in ("live-ac.db", "paper3.db"):
        shutil.copy(os.path.join(rworld.folder, f), d / f)
    paper, rule = str(d / "live-ac.db"), str(d / "paper3.db")
    with sqlite3.connect(paper) as c:              # the config changed: the disp setting (order 6) is gone
        ts, data = c.execute("SELECT ts, data FROM state WHERE k = 'combo_run'").fetchone()
        run = json.loads(data)
        run["config"]["members"] = [m for m in run["config"]["members"] if m.get("cell") != "t-disp"]
        c.execute("UPDATE state SET data = ? WHERE k = 'combo_run'", (json.dumps(run),))
    with sqlite3.connect(rule) as c:               # five minutes of the LTC swing window are missing from the rule bot's file
        c.execute("DELETE FROM live_bars WHERE symbol = 'LTCUSDT' AND ts >= ? AND ts < ?", (W.R0 + 40 * MIN, W.R0 + 45 * MIN))
    w = type("W", (), {"paper_db": paper, "rule_db": rule})()
    _src, conn, res = _rpass(w, str(tmp_path))
    try:
        rows = _by(conn)
        r0 = (W.R0 - W.T0) // MIN
        sol, ltc = rows[("research", "SOLUSDT", r0 + 45)], rows[("research", "LTCUSDT", r0 + 60)]
        assert sol["state"] == "rebuild_failed" and sol["note"] == "지금 설정에 없는 연구 매매법이에요 (설정이 바뀌었어요)"
        assert ltc["state"] == "rebuild_failed" and ltc["note"] == "스윙 손절 창(30분)의 규칙봇 1분봉이 5분 빠져 있어요"
        assert LM.result_ko(ltc) == "다시 못 만듦 (스윙 손절 창(30분)의 규칙봇 1분봉이 5분 빠져 있어요)"
        assert sol["roe"] is None and ltc["entry_ts"] is None                              # nothing made up
        assert rows[("research", "BTCUSDT", r0)]["state"] == "closed"                      # the others as before
        before = conn.execute("SELECT updated_ts FROM missed WHERE key = ?", (sol["key"],)).fetchone()[0]
        LM.missed_pass(_src, conn, NOW_R + 30 * MIN, log=lambda s: None)                  # retried only after RETRY_SLOW_MS
        assert conn.execute("SELECT updated_ts FROM missed WHERE key = ?", (sol["key"],)).fetchone()[0] == before
    finally:
        conn.close()


def test_weekend_and_a_late_break_through_the_bots_own_writers(rworld, tmp_path):
    """The bot's own _log / _restate write a weekend-filtered signal (_submit_due's words) and a break confirmed too late
    (_breaks' words): the weekend one is a pause signal simulated at its minute; the late break cannot be rebuilt (its break
    minute is not recorded): rebuild_failed, never a guess."""
    from paperbot import combo as C
    run = rworld.run
    t = W.R0 + 150 * MIN
    m = next(x for x in rworld.members if x.order == 1)
    sig = C.make_signal(rworld.cfg, m, t, "ETHUSDT", -1, 5.0, W.price("ETHUSDT", t, rworld.paths), t + 20_000, 20_000, {}, "rule")
    run._log(sig, "SUBMITTED", "rule")
    run._restate(sig, "FILTERED", "주말(한국 시간 토·일) 진입 안 함")
    b = next(x for x in rworld.members if x.order == 5)
    sig2 = C.make_signal(rworld.cfg, b, t, "LTCUSDT", 1, 0.16, W.price("LTCUSDT", t, rworld.paths), t + 20_000, 20_000, {}, "custom")
    run._log(sig2, "WAITING", "custom", "돌파 확인 대기")
    run._restate(sig2, "FILTERED", "돌파 확인이 늦음(재시작 따라잡기)", expect=("WAITING",))
    rworld.store.commit()
    try:
        _src, conn, _res = _rpass(rworld, str(tmp_path))
        rows = _by(conn)
        k = (t - W.T0) // MIN
        wk, lb = rows[("pause", "ETHUSDT", k)], rows[("late", "LTCUSDT", k)]
        assert (wk["why_kind"], wk["why"], wk["entry_ts"]) == ("weekend", "주말(한국 시간 토·일) 진입 안 함", t) and wk["state"] in ("closed", "open")
        assert (lb["why_kind"], lb["state"]) == ("late_break", "rebuild_failed") and "돌파 확인 시각이 기록에 없어요" in lb["note"]
        conn.close()
    finally:
        with sqlite3.connect(rworld.paper_db) as c:
            c.execute("DELETE FROM signal_log WHERE bar_close = ?", (t,))


def test_the_executors_misses_take_the_paper_result_with_their_own_reasons(rworld, tmp_path):
    trades = LM.read_paper(open_ro(rworld.paper_db), 0)["trades"]
    btc, eth, bch1, bch2 = trades
    key = lambda t: f"{LM.ACCOUNT}|{t['symbol']}|{t['entry_time']}"            # noqa: E731
    bybit = W.exec_db(str(tmp_path / "bybit.db"), "bybit", followed=[("BTCUSDT", 1, btc["entry_time"], 1.2), ("BCHUSDT", 1, bch1["entry_time"], 0.8)],
                      events=[(eth["entry_time"] + 20_000, "light_red", "신호등 빨강: 따라가지 않음", key(eth))])
    mexc = W.exec_db(str(tmp_path / "mexc.db"), "mexc", followed=[], halt_at=W.T0 + 2 * W.H, live_since=W.T0 + 30 * MIN)
    infos = [LC.ExecInfo(name=n, config="-", unit="-", db=p, light_n=20, light_min=0.85, exchange=n) for n, p in (("bybit", bybit), ("mexc", mexc))]
    _src, conn, res = _rpass(rworld, str(tmp_path), executors=infos)
    try:
        ex = {(r["executor"], r["symbol"], r["entry_ts"]): r for r in LM.read_rows(conn, 0) if r["grp"] == "exec"}
        assert ("bybit", "BTCUSDT", btc["entry_time"]) not in ex and ("bybit", "BCHUSDT", bch1["entry_time"]) not in ex   # followed
        e = ex[("bybit", "ETHUSDT", eth["entry_time"])]
        assert e["why"] == "바이비트: 신호등 빨강이라 따라가지 않았어요" and (e["state"], e["roe"], e["pnl"], e["reason"]) == \
            ("closed", eth["roe"], eth["pnl"], eth["reason"]) and e["how_ko"].startswith("페이퍼 거래의 결과")
        assert ex[("bybit", "BCHUSDT", bch2["entry_time"])]["why"].startswith("바이비트: 실행기 기록에 이유가 없어요")
        assert ("mexc", "BTCUSDT", btc["entry_time"]) not in ex                       # MEXC was not live yet then
        assert ex[("mexc", "ETHUSDT", eth["entry_time"])]["why"].startswith("MEXC: 실행기 기록에 이유가 없어요")    # before its halt
        assert ex[("mexc", "BCHUSDT", bch1["entry_time"])]["why"] == "MEXC: 그때 실행기가 멈춰 있었어요"
        assert res["exec"] == len(ex) == 5 and all(r["sims"] == 0 for r in ex.values())   # no simulation
        g = next(x for x in LM.summary_of(LM.read_rows(conn, 0), trades, None, 0)["groups"] if x["id"] == "exec")
        assert (g["n"], g["wins"], g["losses"]) == (5, 3, 2) and g["read_ko"].startswith("실행기가 안 따라간 페이퍼 거래: 페이퍼 결과 3승 2패")
    finally:
        conn.close()


OLD_SCHEMA = """CREATE TABLE missed (key TEXT PRIMARY KEY, t INTEGER NOT NULL, step_ts INTEGER NOT NULL, member TEXT, strategy TEXT, tf TEXT,
symbol TEXT NOT NULL, side INTEGER NOT NULL, why_kind TEXT NOT NULL, why TEXT NOT NULL, state TEXT NOT NULL, entry_ts INTEGER,
entry_price REAL, stop REAL, leverage INTEGER, margin REAL, exit_ts INTEGER, exit_price REAL, reason TEXT, roe_net REAL, pnl REAL,
best_roe REAL, last_ts INTEGER, wallet REAL, taken_id INTEGER, taken_state TEXT, taken_roe REAL, taken_pnl REAL, taken TEXT, error TEXT,
sims INTEGER NOT NULL DEFAULT 0, first_ts INTEGER NOT NULL, updated_ts INTEGER NOT NULL, signal TEXT NOT NULL, detail TEXT, data TEXT,
path TEXT);
CREATE INDEX missed_t ON missed (t);
CREATE TABLE missed_meta (k TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);"""


def test_an_older_livecheck_db_is_altered_in_place(world, tmp_path):
    """The first version's table (no grp / executor) keeps working: read as group one before the pass, altered by it
    (PRAGMA table_info first, so every later pass leaves it alone), its rows group one."""
    db = str(tmp_path / "livecheck.db")
    c = sqlite3.connect(db)
    c.executescript(OLD_SCHEMA)
    c.execute("INSERT INTO missed (key, t, step_ts, symbol, side, why_kind, why, state, first_ts, updated_ts, signal, roe_net, pnl, exit_ts, "
              "entry_ts, reason) VALUES ('old|BTCUSDT|1', ?, ?, 'BTCUSDT', 1, 'held', '이미 ETH 롱 보유 중', 'closed', 1, 1, '{}', 0.12, 3.0, ?, ?, 'LOCK')",
              (NOW - DAY, NOW - DAY, NOW - DAY + 40 * MIN, NOW - DAY))
    c.commit()
    old = LM.read_rows(c, 0)
    assert old[0]["grp"] == "one" and old[0]["executor"] is None and old[0]["win"] is True
    LM.missed_pass(_src(world, str(tmp_path)), c, NOW, log=lambda s: None)
    cols = {r[1] for r in c.execute("PRAGMA table_info(missed)")}
    assert {"grp", "executor"} <= cols
    rows = {r["key"]: r for r in LM.read_rows(c, 0)}
    assert rows["old|BTCUSDT|1"]["grp"] == "one" and len(rows) == 4 and {r["grp"] for r in rows.values()} == {"one"}
    LM.missed_pass(_src(world, str(tmp_path)), c, NOW + MIN, log=lambda s: None)          # again: no second ALTER
    assert [r[1] for r in c.execute("PRAGMA table_info(missed)")].count("grp") == 1
    c.close()


def test_oldest_unfinished_first_and_a_time_budget(rworld, tmp_path):
    src, conn, res = _rpass(rworld, str(tmp_path), cap=2)
    try:
        assert (res["new"], res["left"], res["capped"]) == (2, 7, True)
        got = sorted((r["t"] - W.T0) // MIN for r in LM.read_rows(conn, 0))
        assert got == [15, 30]                                           # the two oldest signals of the week first
        res = LM.missed_pass(src, conn, NOW_R + MIN, budget_s=0.0, log=lambda s: None)
        assert res["capped"] and res["new"] == 0 and res["left"] == 7     # no time left: nothing this pass, said
        res = LM.missed_pass(src, conn, NOW_R + 2 * MIN, log=lambda s: None)
        assert res["new"] == 7 and not res["capped"]
    finally:
        conn.close()


def test_the_morning_line(rworld, tmp_path):
    _src, conn, _res = _rpass(rworld, str(tmp_path))
    try:
        trades = LM.read_paper(open_ro(rworld.paper_db), 0)["trades"]
        line = LM.morning_line(conn, trades, None, W.T0, W.T0 + DAY)
        assert line == ("어제 못 탄 신호 9개(가상): 한 번에 하나 1승 2패 · 연구 조건 2승 1패 · 돌파 없음 1승 0패 · 쉬는 시간 0승 1패 · "
                        "늦음 1승 0패 · 실제로 탄 거래 3승 1패")
        assert LM.morning_line(conn, trades, None, W.T0 + DAY, W.T0 + 2 * DAY) is None      # a day without: no line
        assert LM.morning_line(None, trades, None, W.T0, W.T0 + DAY) is None
    finally:
        conn.close()
