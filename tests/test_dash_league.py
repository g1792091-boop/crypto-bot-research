"""그림자 리그 (#/league; /api/v4/shadowleague, dash/more/shadowleague.py; screens/league*.js). Read-only and descriptive:
a failed 5-year idea followed on live bars as virtual trades in shadow_league.db (the bot side writes it; this branch does not
carry the agents code, so tests/league_world.py builds the file from the bot's final DDL, reproduced verbatim).

- the world: the DDL's columns; the standard world is hand-computable (the arithmetic is written out below)
- states: no file / no member / never ticked / no new record for 3 hours / waiting / warming / recording / error / halted; an
  unreadable, damaged, empty, half-made, older or newer file; a failed read is an error with its reason and never a zero
- math: the per-trade curve (the member's running sum against the 10 / 50 / 90 % of the clone worlds), the owners' account's
  max drawdown, the coin x timeframe totals, the live-vs-study rows, the signal counts, all against hand-computed numbers
- the 5-year numbers (paperbot/dash/data/league_studies.json) against the committed result document, number by number, and its hashes
- the file is only read (no write, one snapshot per answer, a writer's open transaction does not block), the route is guarded
  by the login, the path is found next to agents3.db
- the screen: routes / rail / 찾기 / inventory wiring, no HTML parsing, no raw font sizes, and the cards rendered in node with the
  tiny DOM (tests/anasyn_dom.mjs): off says how it is turned on, an error says why and shows no zero
"""
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import league_world as W  # noqa: E402
from paperbot.dash import more as MORE  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import shadowleague as S  # noqa: E402
from test_dash import SECRET, _store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
DOCS = os.path.join(ROOT, "docs", "zoneflip-reel")
PW = "correct horse battery"
NOW = W.NOW


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@pytest.fixture(autouse=True)
def _fresh_cache():
    S._cache.clear()
    yield
    S._cache.clear()


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p)
    return p


def view(path, member=None, now=NOW):
    return S.build(path, member, now_ms=now)


def approx(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


# ---------------------------------------------------------------- the world: the bot's final shape, verbatim
COLUMNS = {
    "account_daily": ["member_id", "scope", "day_ms", "equity", "ret_pct", "taken", "liquidated", "asof_ms"],
    "bars": ["coin", "tf", "t_ms", "open", "high", "low", "close", "volume", "atr"],
    "clones": ["clone_id", "member_id", "trade_id", "k", "coin", "tf", "side", "sl_dist", "tp_dist", "offset_bars", "target_ms", "status",
               "entry_ms", "entry_px", "exit_ms", "exit_px", "reason", "hold", "gross_raw", "gross", "fee", "funding", "net", "mae",
               "created_ms", "resolved_ms"],
    "feeds": ["coin", "tf", "first_bar_ms", "last_bar_ms", "n_ingested", "holes", "state", "error", "error_since_ms", "error_count",
              "last_fetch_ms", "last_ok_ms", "next_try_ms"],
    "league_meta": ["k", "v"],
    "members": ["member_id", "name_ko", "detector", "spec_json", "spec_sha256", "start_ms", "created_ms", "activated_ms", "last_tick_ms", "halted"],
    "series_state": ["member_id", "coin", "tf", "status", "last_bar_ms", "warm_have", "warm_need", "note", "updated_ms"],
    "signals": ["signal_id", "member_id", "coin", "tf", "side", "bar_ms", "break_ms", "plan_entry", "stop", "target", "rr", "touches", "atr",
                "zone_lo", "zone_hi", "tz_lo", "tz_hi", "status", "recorded_ms"],
    "trades": ["trade_id", "member_id", "coin", "tf", "side", "signal_ms", "entry_ms", "entry_px", "stop_px", "target_px", "sl_dist", "tp_dist",
               "status", "exit_ms", "exit_px", "reason", "hold", "gross_raw", "gross", "fee", "funding", "net", "mae", "mfe", "recorded_ms",
               "closed_ms", "acct_taken", "acct_ret", "acct_equity", "acct_liq"],
}


def _cols(path, table):
    c = sqlite3.connect(path)
    try:
        return [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
    finally:
        c.close()


def test_world_has_the_final_tables_and_columns(db, tmp_path):
    for table, cols in COLUMNS.items():
        assert _cols(db, table) == cols, table
    c = sqlite3.connect(db)
    idx = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'")}
    c.close()
    assert idx == {"clones_open", "clones_trade", "signals_member", "trades_member"}
    old = str(tmp_path / "v1.db")
    W.build(old, schema=1)
    c = sqlite3.connect(old)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    c.close()
    assert "clones" not in tables and "account_daily" not in tables
    assert "acct_taken" not in _cols(old, "trades") and _cols(old, "trades")[:26] == COLUMNS["trades"][:26]


# ---------------------------------------------------------------- the states
def test_no_file_is_not_started_and_says_how_it_is_turned_on(tmp_path):
    out = view(str(tmp_path / "nothing.db"))
    assert out["state"] == "not_started" and out["reason"] == "file_missing"
    assert "member" not in out and "members" not in out                       # nothing that looks like a record
    sw = out["switch"]
    assert sw["name"] == "AGENTS_SHADOW_LEAGUE" and sw["file"] == "/etc/paperbot/agents.env"
    assert "버튼이 아니라" in sw["how_ko"] and "설정 파일" in sw["how_ko"] and "AGENTS_SHADOW_LEAGUE=1" in sw["how_ko"]
    assert out["studies_state"] == "ok" and "zoneflip" in out["studies"]      # the 5-year card does not need the file
    assert [k["member_id"] for k in out["known"]] == ["zoneflip"]
    assert out["label_ko"] == "참고용, 판정 아님"


def test_no_place_to_look_is_not_started_too():
    out = S.build(None, None, now_ms=NOW)
    assert out["state"] == "not_started" and out["reason"] == "no_path"


def test_a_file_without_a_member_is_not_started(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    c = sqlite3.connect(p)
    c.executescript(W.ddl(2))
    c.commit()
    c.close()
    out = view(p)
    assert out["state"] == "not_started" and out["reason"] == "no_member"


def test_a_member_that_never_ticked_is_off_and_never(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p, ticked=False, with_data=False, start=NOW + 3 * W.H)
    out = view(p)
    c = out["member"]["card"]
    assert out["state"] == "ok" and c["status"] == "off" and c["status_ko"] == "꺼짐" and c["off_why"] == "never"
    assert "아직 켜지 않았어요" in c["off_ko"] and c["last_tick_ms"] is None and out["last_tick"] is None
    assert c["series"]["total"] == 0 and c["signals"]["total"] == 0 and c["trades"]["closed"] == 0   # real zeros: the tables exist


def test_no_new_record_for_three_hours_is_off_and_stale(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p, last_tick_ms=NOW - 3 * W.H - 1)
    c = view(p)["member"]["card"]
    assert c["status"] == "off" and c["off_why"] == "stale" and "3시간" in c["off_ko"]
    p2 = str(tmp_path / "fresh.db")
    W.build(p2, last_tick_ms=NOW - 3 * W.H + 60_000)                          # just inside: still recording
    assert view(p2)["member"]["card"]["status"] == "recording"


def test_waiting_before_the_start_date(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p, start=NOW + 3 * W.H, with_data=False, series_mode="waiting", activated=NOW - W.H)
    c = view(p)["member"]["card"]
    assert c["status"] == "waiting" and c["status_ko"] == "시작 전" and approx(c["starts_in_days"], 0.125, 0.006) and c["days"] == 0.0
    assert c["series"] == {"recording": 0, "warming": 0, "waiting": 24, "error": 0, "total": 24}


def test_warming_and_all_error_and_halted(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p, with_data=False)
    c = sqlite3.connect(p)
    c.execute("UPDATE series_state SET status = 'warming', warm_have = 120, warm_need = 300, note = '워밍업 중 (180봉 더 필요)'")
    c.commit()
    c.close()
    card = view(p)["member"]["card"]
    assert card["status"] == "warming" and card["status_ko"] == "워밍업 중" and len(card["warming"]) == 24
    assert card["warming"][0] == {"coin": "BCH", "tf": "15m", "have": 120, "need": 300, "note": "워밍업 중 (180봉 더 필요)"}
    c = sqlite3.connect(p)
    c.execute("UPDATE series_state SET status = 'error', note = '시세를 받지 못함'")
    c.commit()
    c.close()
    card = view(p)["member"]["card"]
    assert card["status"] == "error" and card["status_ko"] == "오류" and len(card["errors"]) == 24 and card["warming"] == []
    c = sqlite3.connect(p)
    c.execute("UPDATE members SET halted = '정의가 바뀜'")
    c.commit()
    c.close()
    card = view(p)["member"]["card"]
    assert card["status"] == "halted" and card["status_ko"] == "멈춤(정의가 바뀜)" and card["halted_ko"] == "정의가 바뀜"


def test_recording_standard_world(db):
    out = view(db)
    assert out["state"] == "ok" and out["selected"] == "zoneflip" and out["schema_version"] == 2 and out["notes_ko"] == []
    c = out["member"]["card"]
    assert c["status"] == "recording" and c["status_ko"] == "기록 중" and c["name_ko"] == "영상 매매법 (매물대 지지→저항 전환)"
    assert c["series"] == {"recording": 22, "warming": 1, "waiting": 0, "error": 1, "total": 24}
    assert c["started_at_ms"] == W.START and approx(c["days"], 5.12, 0.005) and c["starts_in_days"] == 0.0
    assert c["errors"] == [{"coin": "BCH", "tf": "15m", "note": "시세를 받지 못함 (2봉 늦음)"}]
    assert c["warming"] == [{"coin": "LTC", "tf": "4h", "have": 150, "need": 300, "note": "워밍업 중 (150봉 더 필요)"}]
    assert out["last_tick"]["bars_added"] == 8 and out["last_tick"]["errors_ko"][0]["ko"].startswith("동전 던지기 12개가 들어갈 봉이")
    assert "no longer stored" in out["last_tick"]["errors_ko"][0]["raw"]       # the bot's own words stay next to it


# ---------------------------------------------------------------- a failed read is an error with its reason, never a zero
def test_a_damaged_file_is_an_error_with_a_reason(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    with open(p, "wb") as fh:
        fh.write(b"this is not a database " * 50)
    out = view(p)
    assert out["state"] == "error" and "DatabaseError" in out["reason"] and "망가졌" in out["reason_ko"]
    assert "member" not in out and "members" not in out and "card" not in out     # no record that could read as 'nothing'
    assert out["studies_state"] == "ok"


def test_an_empty_or_half_made_file_is_an_error_not_not_started(tmp_path):
    p = str(tmp_path / "empty.db")
    open(p, "wb").close()
    out = view(p)
    assert out["state"] == "error" and "no such table: members" in out["reason"] and "표가 없어요" in out["reason_ko"]
    p2 = str(tmp_path / "other.db")
    c = sqlite3.connect(p2)
    c.execute("CREATE TABLE unrelated (a)")
    c.commit()
    c.close()
    assert view(p2)["state"] == "error"
    folder = str(tmp_path / "folder.db")
    os.makedirs(folder)
    out = view(folder)
    assert out["state"] == "error" and "폴더" in out["reason_ko"]


def test_permission_lock_and_surprises_are_errors(db, monkeypatch):
    def deny(path):
        raise PermissionError(13, "Permission denied", path)
    monkeypatch.setattr(S, "open_ro", deny)
    out = view(db)
    assert out["state"] == "error" and "PermissionError" in out["reason"] and "권한" in out["reason_ko"]

    def locked(path):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(S, "open_ro", locked)
    out = view(db)
    assert out["state"] == "error" and "잠시 뒤 다시" in out["reason_ko"]
    monkeypatch.undo()
    monkeypatch.setattr(S, "_tables", lambda conn: 1 / 0)                       # anything unexpected while reading
    out = view(db)
    assert out["state"] == "error" and "ZeroDivisionError" in out["reason"]


def test_one_members_failure_is_its_own_error_and_the_list_stays(db, monkeypatch):
    def boom(*a, **k):
        raise KeyError("trade_id")
    monkeypatch.setattr(S, "per_trade_curve", boom)
    out = view(db)
    assert out["state"] == "ok" and out["member"]["state"] == "error" and "KeyError" in out["member"]["reason"]
    assert [m["member_id"] for m in out["members"]] == ["zoneflip"] and out["members"][0]["state"] == "error"


def test_an_older_file_switches_off_only_the_blocks_whose_table_is_missing(tmp_path):
    p = str(tmp_path / "v1.db")
    W.build(p, schema=1)
    out = view(p)
    m = out["member"]
    assert out["state"] == "ok" and out["schema_version"] == 1 and "옛 모양" in out["notes_ko"][0]
    assert out["tables_missing"] == ["clones", "account_daily"]
    assert m["per_trade"]["state"] == "unavailable" and m["per_trade"]["table"] == "clones" and "points" not in m["per_trade"]
    assert m["account"]["state"] == "unavailable" and m["account"]["table"] == "account_daily" and "scopes" not in m["account"]
    assert "자료 표" not in json.dumps(m["table"]) and m["table"]["state"] == "ok" and len(m["table"]["cells"]) == 24
    assert m["trades"]["state"] == "ok" and m["trades"]["total"] == 6 and m["card"]["trades"]["closed"] == 5
    assert m["card"]["tables_missing"] == ["clones", "account_daily"]
    # the trade rows carry no account numbers of that older file: None, not 0
    assert m["trades"]["rows"][0]["account"] == {"taken": None, "ret_pct": None, "equity": None, "liquidated": None}


def test_a_half_made_file_has_no_zero_in_place_of_the_missing_table(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p)
    c = sqlite3.connect(p)
    c.execute("DROP TABLE trades")
    c.execute("DROP TABLE signals")
    c.commit()
    c.close()
    out = view(p)
    m = out["member"]
    assert out["state"] == "ok" and set(out["tables_missing"]) == {"trades", "signals"}
    assert m["card"]["trades"] is None and m["card"]["signals"] is None            # unknown, not 0
    for k in ("per_trade", "table", "trades", "comparison", "signals"):
        assert m[k]["state"] == "unavailable", k
    assert m["account"]["state"] == "ok"
    p2 = str(tmp_path / "noseries.db")
    W.build(p2)
    c = sqlite3.connect(p2)
    c.execute("DROP TABLE series_state")
    c.commit()
    c.close()
    card = view(p2)["member"]["card"]
    assert card["series"] is None and card["status"] == "error"                      # the status cannot be known: said, not guessed


def test_a_newer_file_still_reads_what_it_knows(tmp_path):
    p = str(tmp_path / "v3.db")
    W.build(p, version_row="3")
    c = sqlite3.connect(p)
    c.execute("ALTER TABLE trades ADD COLUMN something_new TEXT")
    c.execute("CREATE TABLE newer_table (a)")
    c.commit()
    c.close()
    out = view(p)
    assert out["state"] == "ok" and out["schema_version"] == 3 and "새 모양" in out["notes_ko"][0]
    assert out["member"]["card"]["trades"]["closed"] == 5 and out["member"]["per_trade"]["n"] == 4


def test_missing_version_row_and_bad_json_are_noted_not_fatal(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p, version_row=None)
    c = sqlite3.connect(p)
    c.execute("UPDATE members SET spec_json = '{not json'")
    c.execute("UPDATE league_meta SET v = 'nope' WHERE k = 'last_tick'")
    c.commit()
    c.close()
    out = view(p)
    assert out["state"] == "ok" and out["schema_version"] is None and "버전이 적혀 있지 않아요" in out["notes_ko"][0]
    assert out["last_tick"] is None and out["member"]["spec_ok"] is False
    assert len(out["member"]["table"]["cells"]) == 24                                  # coins and timeframes from the series, not the spec
    assert out["member"]["account_spec"]["start_equity"] == 5000.0


def test_members_list_unknown_member_and_requested_missing(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p)
    W.add_member(p, "second", "두 번째 아이디어 (DB 이름)", now=NOW)
    out = view(p)
    assert [m["member_id"] for m in out["members"]] == ["zoneflip", "second"]          # the members the page names first, then the rest by id
    assert out["selected"] == "zoneflip"                                              # the first one when none is asked for
    out = view(p, "second")
    sec = out["member"]
    assert out["selected"] == "second" and sec["card"]["name_ko"] == "두 번째 아이디어 (DB 이름)" and sec["card"]["blurb_ko"] == ""
    assert sec["study"] is None and not sec["card"]["study"]                           # no 5-year numbers the page does not know
    assert sec["card"]["status"] == "waiting" and sec["trades"]["total"] == 0 and sec["per_trade"]["n"] == 0
    other = [m for m in out["members"] if m["member_id"] == "zoneflip"][0]
    assert other["status"] == "recording" and other["trades"]["closed"] == 5          # the other card: still real numbers
    out = view(p, "no-such-member")
    assert out["requested_missing"] is True and out["selected"] == "zoneflip"


# ---------------------------------------------------------------- the math, against hand-computed numbers
def test_card_numbers_by_hand(db):
    c = view(db)["member"]["card"]
    # signals: 14 rows: taken 7, skipped (busy, skip_rr, skip_no_target, skip_stop_far, skip_entry, not_chosen) 6, pending_entry 1,
    # one bar before the activation (start + 1h < start + 2h) is 'late'
    assert c["signals"] == {"total": 14, "taken": 7, "skipped": 6, "pending": 1, "late": 1}
    t = c["trades"]
    # closed: T1 +1.0, T2 -0.5, T3 +0.2, T4 -0.8, T6 +0.4 (percent) -> sum 0.3, mean 0.06, 3 wins of 5 = 60 %; gross: 1.14 - 0.36 + 0.34 - 0.66 + 0.54 = 1.0 -> mean 0.2
    assert t["open"] == 1 and t["closed"] == 5 and t["wins"] == 3 and t["win_pct"] == 60.0 and t["need"] == 30 and t["small"] is True
    assert approx(t["sum_net_pct"], 0.3, 1e-9) and approx(t["avg_net_pct"], 0.06, 1e-9) and approx(t["avg_gross_pct"], 0.2, 1e-9)


def test_per_trade_curve_by_hand(db):
    pt = view(db)["member"]["per_trade"]
    # exit order of the four trades whose 50 clones are all decided: T1, T2, T3, T4 (T6's clones: ten pending -> awaiting 1)
    assert pt["state"] == "ok" and pt["n"] == 4 and pt["clones_per_trade"] == 50 and pt["awaiting_clones"] == 1 and pt["thinned"] is False
    # member cumulative %: 1.0, 0.5, 0.7, -0.1. World k after n trades: sum(C[:n]) + n * 1e-4 * k with C = -.0020, -.0010, -.0030, 0
    # percentile positions of 50 worlds: p10 -> 4.9, p50 -> 24.5, p90 -> 44.1 (linear interpolation)
    want = [(1.0, -0.2e-2 + 1e-4 * 4.9, -0.2e-2 + 1e-4 * 24.5, -0.2e-2 + 1e-4 * 44.1),
            (0.5, -0.3e-2 + 2e-4 * 4.9, -0.3e-2 + 2e-4 * 24.5, -0.3e-2 + 2e-4 * 44.1),
            (0.7, -0.6e-2 + 3e-4 * 4.9, -0.6e-2 + 3e-4 * 24.5, -0.6e-2 + 3e-4 * 44.1),
            (-0.1, -0.6e-2 + 4e-4 * 4.9, -0.6e-2 + 4e-4 * 24.5, -0.6e-2 + 4e-4 * 44.1)]
    assert len(pt["points"]) == 4
    for i, (p, (m, lo, mid, hi)) in enumerate(zip(pt["points"], want)):
        assert p["n"] == i + 1
        assert approx(p["member_cum_pct"], m, 1e-9) and approx(p["flip_p10"], lo * 100, 1e-3) and approx(p["flip_p50"], mid * 100, 1e-3) \
            and approx(p["flip_p90"], hi * 100, 1e-3), (i, p)
        assert approx(p["member_avg_pct"], m / (i + 1), 1e-4) and approx(p["flip_avg_p50"], mid * 100 / (i + 1), 1e-4)
    assert [p["ms"] for p in pt["points"]] == sorted(p["ms"] for p in pt["points"])
    last = pt["points"][-1]
    assert approx(last["flip_p10"], -0.404, 1e-9) and approx(last["flip_p50"], 0.38, 1e-9) and approx(last["flip_p90"], 1.164, 1e-9)
    assert pt["position"] == "inside" and pt["label_ko"] == "참고용, 판정 아님"


def test_percentile_is_numpys_linear_one():
    np = pytest.importorskip("numpy")
    rng = random.Random(5)
    for n in (1, 2, 3, 7, 50):
        xs = [rng.uniform(-9, 9) for _ in range(n)]
        for q in (0, 10, 50, 90, 100):
            assert approx(S.pctl(xs, q), float(np.percentile(xs, q)), 1e-9), (n, q)
    assert S.pctl([], 50) is None


def test_curve_position_above_below_and_the_complete_rule():
    def trade(i, net, exit_ms=None):
        return {"trade_id": f"t{i}", "status": "closed", "exit_ms": exit_ms or 1000 + i, "net": net}

    def clones(i, nets, status="closed"):
        return [{"trade_id": f"t{i}", "k": k, "status": status, "net": n} for k, n in enumerate(nets)]
    zeros = [0.0] * 5
    up = S.per_trade_curve([trade(1, 0.10)], clones(1, zeros))
    assert up["position"] == "above" and up["points"][0]["member_cum_pct"] == 10.0
    down = S.per_trade_curve([trade(1, -0.10)], clones(1, zeros))
    assert down["position"] == "below"
    # K is the fewest clones any trade has: the 5-clone trade limits the 6-clone one
    mixed = S.per_trade_curve([trade(1, 0.0), trade(2, 0.0)], clones(1, zeros) + clones(2, zeros + [0.5]))
    assert mixed["clones_per_trade"] == 5 and mixed["n"] == 2
    # one pending clone keeps the whole trade out; an open trade and a trade without clones too
    held = S.per_trade_curve([trade(1, 0.0), trade(2, 0.0)], clones(1, zeros) + clones(2, zeros)[:4] + [{"trade_id": "t2", "k": 4, "status": "pending", "net": None}])
    assert held["n"] == 1 and held["awaiting_clones"] == 1
    none = S.per_trade_curve([trade(1, 0.0)], [])
    assert none["n"] == 0 and none["clones_per_trade"] == 0 and none["awaiting_clones"] == 1 and none["position"] is None and none["points"] == []


def test_a_long_curve_is_thinned_but_keeps_its_last_point():
    trades = [{"trade_id": f"t{i}", "status": "closed", "exit_ms": 1000 + i, "net": 0.001} for i in range(1300)]
    cl = [{"trade_id": f"t{i}", "k": k, "status": "closed", "net": 0.0} for i in range(1300) for k in range(3)]
    pt = S.per_trade_curve(trades, cl)
    assert pt["n"] == 1300 and pt["thinned"] is True and len(pt["points"]) <= S.MAX_POINTS + 1
    assert pt["points"][-1]["n"] == 1300 and approx(pt["points"][-1]["member_cum_pct"], 130.0, 1e-6)
    assert [p["n"] for p in pt["points"]] == sorted(p["n"] for p in pt["points"])


def test_max_drawdown_by_hand():
    assert S.max_drawdown([5400.0, 4050.0], 5000.0) == {"max_dd_pct": 25.0, "trough_index": 1}          # 5400 -> 4050 = -25 %
    assert S.max_drawdown([4750.0], 5000.0) == {"max_dd_pct": 5.0, "trough_index": 0}                      # the start balance is the first peak
    assert S.max_drawdown([5100.0, 5200.0], 5000.0) == {"max_dd_pct": 0.0, "trough_index": None}
    d = S.max_drawdown([6000.0, 3000.0, 4500.0, 2400.0], 5000.0)                                          # peak 6000 -> 2400 = 60 %
    assert d == {"max_dd_pct": 60.0, "trough_index": 3}


def test_account_by_hand(db):
    a = view(db)["member"]["account"]
    assert a["state"] == "ok" and a["start_equity"] == 5000.0 and a["margin_frac"] == 0.2 and a["leverage"] == 20 and a["exposure"] == 4.0
    assert approx(a["liq_adverse"], 0.045, 1e-9)
    eq = [5000 * 1.04 * 0.98, 5000 * 1.04 * 0.98 * 1.008, 5000 * 1.04 * 0.98 * 1.008 * 0.968, 5000 * 1.04 * 0.98 * 1.008 * 0.968 * 1.016] * 1
    al = a["scopes"]["all"]
    assert [p["equity"] for p in al["points"]] == [round(e, 2) for e in eq] + [round(eq[-1], 2)] == [5096.0, 5136.77, 4972.39, 5051.95, 5051.95]
    assert [p["taken"] for p in al["points"]] == [2, 3, 4, 5, 5] and al["asof_ms"] == W.START + 5 * W.DAY
    last = al["last"]
    # day-end equity 5096 -> 5136.768 (peak) -> 4972.3722: a fall of 3.2 % exactly (the T4 loss, 4 x -0.8 %), trough on day 2
    assert approx(last["max_dd_pct"], 3.2, 1e-9) and last["trough_day_ms"] == W.START + 2 * W.DAY
    assert approx(last["x"], 1.0104, 1e-4) and approx(last["ret_pct"], 1.039, 1e-3) and last["liquidated"] == 0 and last["taken"] == 5
    s15 = a["scopes"]["15m"]["last"]
    assert s15["equity"] == 4000.0 and s15["x"] == 0.8 and s15["ret_pct"] == -20.0 and s15["liquidated"] == 1 and s15["max_dd_pct"] == 20.0
    for tf in ("30m", "1h", "4h"):                                       # no closed trade there: no points, no last, not a flat 5,000 line
        assert a["scopes"][tf] == {"points": [], "asof_ms": None, "start_equity": 5000.0, "last": None, "label_ko": "참고용, 판정 아님"}


def test_table_totals_by_hand(db):
    t = view(db)["member"]["table"]
    assert t["state"] == "ok" and len(t["cells"]) == 24 and [(x["coin"], x["tf"]) for x in t["cells"]][:5] == [("BTC", "15m"), ("BTC", "30m"), ("BTC", "1h"), ("BTC", "4h"), ("ETH", "15m")]
    cell = {(x["coin"], x["tf"]): x for x in t["cells"]}
    assert cell[("BTC", "15m")]["closed"] == 1 and cell[("BTC", "15m")]["avg_net_pct"] == 1.0 and cell[("BTC", "15m")]["wins"] == 1
    assert cell[("DOGE", "4h")]["open"] == 1 and cell[("DOGE", "4h")]["closed"] == 0 and cell[("DOGE", "4h")]["avg_net_pct"] is None
    assert cell[("LTC", "4h")]["status"] == "warming" and cell[("LTC", "4h")]["warm_have"] == 150 and cell[("BCH", "15m")]["status"] == "error"
    assert cell[("BCH", "15m")]["note"] == "시세를 받지 못함 (2봉 늦음)"
    by_tf = {x["tf"]: x for x in t["by_tf"]}
    # 15m: T1 +1.0, T2 -0.5, T6 +0.4 -> mean 0.3, sum 0.9, 2 wins of 3; 30m: T4 -0.8; 1h: T3 +0.2; 4h: T5 open
    assert by_tf["15m"]["closed"] == 3 and approx(by_tf["15m"]["avg_net_pct"], 0.3, 1e-9) and approx(by_tf["15m"]["sum_net_pct"], 0.9, 1e-9) and by_tf["15m"]["wins"] == 2
    assert by_tf["30m"]["avg_net_pct"] == -0.8 and by_tf["1h"]["avg_net_pct"] == 0.2 and by_tf["4h"]["closed"] == 0 and by_tf["4h"]["open"] == 1
    by_coin = {x["coin"]: x for x in t["by_coin"]}
    assert by_coin["BTC"]["closed"] == 2 and approx(by_coin["BTC"]["avg_net_pct"], 0.6, 1e-9)           # (1.0 + 0.2) / 2: pooled, not a mean of cells
    assert by_coin["DOGE"]["closed"] == 0 and by_coin["BCH"]["avg_net_pct"] is None and by_coin["BCH"]["signals"] == 0
    assert sum(x["closed"] for x in t["by_coin"]) == sum(x["closed"] for x in t["by_tf"]) == 5
    assert by_coin["ETH"]["signals"] == 3                                                                # ETH rows of the 14 signals: taken, busy, skip_entry


def test_a_series_that_was_never_stored_says_waiting_and_not_stored(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p)
    c = sqlite3.connect(p)
    c.execute("DELETE FROM series_state WHERE coin = 'SOL' AND tf = '1h'")
    c.commit()
    c.close()
    cell = {(x["coin"], x["tf"]): x for x in view(p)["member"]["table"]["cells"]}[("SOL", "1h")]
    assert cell["status"] == "waiting" and cell["stored"] is False and cell["closed"] == 0


def test_trades_and_signals_lists(db, tmp_path):
    m = view(db)["member"]
    rows = m["trades"]["rows"]
    assert m["trades"]["total"] == 6 and [r["trade_id"].split("|")[1] for r in rows] == ["T5", "T6", "T4", "T3", "T2", "T1"]     # newest entry first
    t1 = rows[-1]
    assert t1["coin"] == "BTC" and t1["tf"] == "15m" and t1["side"] == 1 and t1["side_ko"] == "롱" and t1["reason"] == "TP" and t1["reason_ko"] == "목표 도달"
    assert approx(t1["net_pct"], 1.0, 1e-9) and approx(t1["gross_pct"], 1.14, 1e-9) and t1["hold_bars"] == 11 and approx(t1["stop_dist_pct"], 0.6, 1e-9)
    assert t1["account"] == {"taken": True, "ret_pct": 4.0, "equity": 5200.0, "liquidated": False} and t1["late"] is False
    t5 = rows[0]
    assert t5["status"] == "open" and t5["net_pct"] is None and t5["exit_ms"] is None and t5["reason_ko"] is None and t5["account"]["ret_pct"] is None
    assert rows[2]["side_ko"] == "숏" and rows[2]["reason_ko"] == "손절" and rows[3]["reason_ko"] == "48봉 시간 청산"
    sg = m["signals"]["rows"]
    assert len(sg) == 14 and sg[0]["bar_ms"] >= sg[-1]["bar_ms"] and {s["status"] for s in sg} >= {"taken", "busy", "skip_rr", "pending_entry"}
    assert {s["status_ko"] for s in sg} >= {"진입함", "보유 중이라 건너뜀", "손익비 2 미만", "다음 봉 시가 진입 대기"}
    assert [s for s in sg if s["status"] == "skip_no_target"][0]["target"] is None and [s for s in sg if s["status"] == "skip_no_target"][0]["rr"] is None
    p = str(tmp_path / "late.db")                                             # activated after T1's signal bar: T1 reads 'late'
    W.build(p, activated=W.START + 4 * W.H)
    rows = view(p)["member"]["trades"]["rows"]
    assert [r["late"] for r in rows if r["trade_id"].endswith("T1")] == [True] and [r["late"] for r in rows if r["trade_id"].endswith("T2")] == [False]
    assert view(p)["member"]["card"]["signals"]["late"] == 2


def test_the_last_fifty_only(tmp_path):
    p = str(tmp_path / "rich.db")
    info = W.build_rich(p, now=NOW, days=20, seed=3, per_day=4)
    m = view(p)["member"]
    assert m["trades"]["total"] == info["trades"] > 50 and len(m["trades"]["rows"]) == 50
    ms = [r["entry_ms"] for r in m["trades"]["rows"]]
    assert ms == sorted(ms, reverse=True)
    assert m["card"]["trades"]["closed"] == info["closed"] and m["per_trade"]["n"] + m["per_trade"]["awaiting_clones"] == info["closed"]


def test_comparison_live_next_to_the_study_by_hand(db):
    cmp_ = view(db)["member"]["comparison"]["rows"]
    assert [r["tf"] for r in cmp_] == ["15m", "30m", "1h", "4h"]
    a = cmp_[0]
    # 15m closed: T1 +1.0, T2 -0.5, T6 +0.4 -> 3 trades, win 2/3, net 0.3, gross (1.14 - 0.36 + 0.54) / 3 = 0.44
    assert a["live"]["trades"] == 3 and approx(a["live"]["win_pct"], 200 / 3, 1e-3) and approx(a["live"]["net_pct"], 0.3, 1e-9) and approx(a["live"]["gross_pct"], 0.44, 1e-9)
    assert a["study"]["is"]["trades"] == 796 and a["study"]["is"]["net_pct"] == -0.10 and a["study"]["oos"]["win_pct"] == 22.0
    assert a["study_p12"] == 1.0 and a["study_vs_flip"] == {"main_pct": -0.13, "flip_pct": -0.14, "p": 0.35}
    d = cmp_[3]
    assert d["live"] == {"trades": 0, "win_pct": None, "net_pct": None, "gross_pct": None}           # no closed 4h trade: None, not 0 %


def test_everything_is_json_clean(db, tmp_path):
    out = view(db)
    json.dumps(out, allow_nan=False)
    bad = str(tmp_path / "nan.db")
    W.build(bad)
    c = sqlite3.connect(bad)
    c.execute("UPDATE trades SET net = 1e999 WHERE trade_id LIKE '%T1'")           # an infinite number in the file
    c.commit()
    c.close()
    from paperbot.dash.app import json_finite
    json.dumps(json_finite(view(bad)), allow_nan=False)


# ---------------------------------------------------------------- reading only: one snapshot, no write, no blocking
def test_the_reader_cannot_write(db):
    conn = S.open_ro(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO league_meta (k, v) VALUES ('x', 'y')")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE evil (a)")
    finally:
        conn.close()


def test_the_file_is_not_changed_by_reading(db):
    before = _sha(db)
    for _ in range(3):
        S._cache.clear()
        assert view(db)["state"] == "ok"
    assert _sha(db) == before and not os.path.exists(db + "-journal")


def test_one_snapshot_per_answer_even_when_the_writer_commits_in_between(db, monkeypatch):
    real = S._rows
    state = {"n": 0}

    def rows(conn, sql, args=()):
        out = real(conn, sql, args)
        state["n"] += 1
        if state["n"] == 1:                                    # right after the first read: the agents write another trade and commit
            w = sqlite3.connect(db, timeout=5, isolation_level=None)
            w.execute("INSERT INTO trades (trade_id, member_id, coin, tf, side, signal_ms, entry_ms, entry_px, stop_px, target_px, sl_dist, tp_dist, "
                      "status, recorded_ms) VALUES ('zoneflip|T9', 'zoneflip', 'BTC', '1h', 1, 1, 2, 1, 1, 1, .01, .02, 'open', 3)")
            w.close()
        return out
    monkeypatch.setattr(S, "_rows", rows)
    out = view(db)
    assert out["member"]["trades"]["total"] == 6 and out["member"]["card"]["trades"]["open"] == 1       # the new row is not in this answer
    monkeypatch.undo()
    S._cache.clear()
    assert view(db)["member"]["trades"]["total"] == 7                                                      # but is in the next one


def test_an_open_write_transaction_does_not_block_the_reader(db):
    w = sqlite3.connect(db, timeout=5, isolation_level=None)
    w.execute("BEGIN IMMEDIATE")
    w.execute("UPDATE members SET halted = 'uncommitted'")
    try:
        out = view(db)
        assert out["state"] == "ok" and out["member"]["card"]["halted_ko"] is None           # sees the committed state, does not wait
    finally:
        w.execute("ROLLBACK")
        w.close()


def test_a_restored_copy_with_an_old_wal_is_an_error(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    W.build(p, wal=False)
    with open(p + "-wal", "wb") as fh:
        fh.write(b"x" * 64)
    out = view(p)
    assert out["state"] == "error" and "-wal" in out["reason"]


# ---------------------------------------------------------------- where the file is, the route, the cache, the login
def test_the_file_is_found_next_to_agents3_then_paper3(tmp_path, monkeypatch):
    class Ctx:
        pass
    monkeypatch.delenv(S.ENV_PATH, raising=False)
    c = Ctx()
    assert S.default_path(c) is None
    c.db = str(tmp_path / "data" / "paper3.db")
    assert S.default_path(c) == str(tmp_path / "data" / "shadow_league.db")
    c.agents_db = str(tmp_path / "var" / "agents3.db")
    assert S.default_path(c) == str(tmp_path / "var" / "shadow_league.db")
    c.shadow_league_db = "/x/y/explicit.db"
    assert S.default_path(c) == "/x/y/explicit.db"
    del c.shadow_league_db
    monkeypatch.setenv(S.ENV_PATH, "/env/league.db")
    assert S.default_path(c) == "/env/league.db"


def test_module_is_registered_and_names_its_route():
    assert "shadowleague" in MORE.MODULES
    assert "/api/v4/shadowleague" in _read(ROOT, "paperbot", "dash", "more", "shadowleague.py")


@pytest.fixture
def client(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    dbp = str(base / "paper3.db")
    _store(dbp).close()
    agents = str(base / "agents3.db")
    sqlite3.connect(agents).close()
    league = str(base / "shadow_league.db")
    W.build(league)
    app = create_app(dbp, hash_password(PW), SECRET, agents_db=agents, candles=lambda s, i, n: [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}])
    c = TestClient(app)
    return c, league


def test_the_route_is_behind_the_login_and_answers_the_view(client):
    c, league = client
    r = c.get("/api/v4/shadowleague", follow_redirects=False)
    assert r.status_code in (401, 302, 307)                                        # like every /api route
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get("/api/v4/shadowleague")
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == "ok" and d["path"] == league and d["selected"] == "zoneflip" and d["member"]["card"]["trades"]["closed"] == 5
    assert c.get("/api/v4/shadowleague?member=" + "x" * 200).json()["selected"] == "zoneflip"          # a silly id is just 'none asked'
    assert c.get("/api/v4/shadowleague?member=nope").json()["requested_missing"] is True


def test_the_answer_is_cached_for_a_few_seconds_and_then_read_again(client):
    c, league = client
    c.post("/api/login", json={"password": PW})
    first = c.get("/api/v4/shadowleague").json()
    w = sqlite3.connect(league, isolation_level=None)
    w.execute("UPDATE members SET halted = 'stop'")
    w.close()
    assert c.get("/api/v4/shadowleague").json() == first                                   # the 5 s cache
    S._cache.clear()
    assert c.get("/api/v4/shadowleague").json()["member"]["card"]["status"] == "halted"


def test_the_route_says_not_started_and_error_for_real(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    dbp = str(base / "paper3.db")
    _store(dbp).close()
    app = create_app(dbp, hash_password(PW), SECRET, candles=lambda s, i, n: [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}])
    c = TestClient(app)
    c.post("/api/login", json={"password": PW})
    assert c.get("/api/v4/shadowleague").json()["state"] == "not_started"          # no file next to paper3.db
    with open(base / "shadow_league.db", "wb") as fh:
        fh.write(b"garbage" * 100)
    S._cache.clear()
    d = c.get("/api/v4/shadowleague").json()
    assert d["state"] == "error" and d["reason_ko"] and "member" not in d


# ---------------------------------------------------------------- the 5-year numbers: the committed file against the committed document
def _num(s):
    return float(s.replace("−", "-").replace("%", "").replace("+", "").replace("배", "").replace(",", "").strip())


def _study():
    with open(S.STUDY_FILE, encoding="utf-8") as fh:
        return json.load(fh)["studies"]["zoneflip"]


def test_the_study_numbers_are_the_result_documents_numbers():
    md = _read(DOCS, "RESULTS_ZONEFLIP.md")
    s = _study()
    sec = md.split("## 봉 길이별 결과 (본 규칙 MAIN)")[1].split("## 동전 던지기와 비교")[0]
    n = 0
    for tf, label in (("15m", "15분봉"), ("30m", "30분봉"), ("1h", "1시간봉"), ("4h", "4시간봉")):
        blk = sec.split(f"**{label}**")[1]
        head = blk.split("\n")[0]
        m = re.search(r"손절(?: 거리 중앙값)? ([\d.]+)~([\d.]+)%, 목표 ([\d.]+)~([\d.]+)%", head)
        assert s["distance_pct"][tf] == {"stop": [float(m.group(1)), float(m.group(2))], "target": [float(m.group(3)), float(m.group(4))]}
        for key, per in (("is", "1기"), ("oos", "2기"), ("pre", "3기")):
            line = [x for x in blk.split("\n") if x.startswith(f"| {per} |")][0]
            c = [x.strip().strip("*") for x in line.strip("|").split("|")]
            pos, of = [int(x) for x in c[8].split("/")]
            assert s["main"][tf][key] == {"trades": int(c[1]), "win_pct": _num(c[2]), "avg_win_pct": _num(c[3]), "avg_loss_pct": _num(c[4]),
                                          "pf": _num(c[5]), "net_pct": _num(c[6]), "gross_pct": _num(c[7]), "coins_positive": pos, "coins_of": of,
                                          "flip_net_pct": _num(c[9]), "account_x": _num(c[10])}, (tf, key)
            n += 1
    assert n == 12
    m = re.search(r"15분 (\d+\.\d+), 30분 (\d+\.\d+), 1시간 (\d+\.\d+), 4시간 (\d+\.\d+)", md)
    assert s["p12"] == dict(zip(("15m", "30m", "1h", "4h"), [float(x) for x in m.groups()]))
    blk = md.split("## 동전 던지기와 비교")[1].split("## 대조 설정")[0].split("\n")
    for tf, label in (("15m", "15분"), ("30m", "30분"), ("1h", "1시간"), ("4h", "4시간")):
        c = [x.strip() for x in [y for y in blk if y.startswith(f"| {label} |")][0].strip("|").split("|")]
        assert s["vs_flip"][tf] == {"main_pct": _num(c[1]), "flip_pct": _num(c[2]), "p": _num(c[3])}
    assert "## 판정: **실패**" in md and s["verdict"] == "FAIL" and s["verdict_ko"] == "실패"
    assert "통과 0칸" in md and s["cells"] == 8 and s["cells_passed"] == 0
    assert "MAIN 3,173, CTRL 6,755" in md and s["trades_main"] == 3173 and s["trades_ctrl"] == 6755
    assert "2026-10-06" in md and s["run_date"] == "2026-10-06"
    assert "기간 끝 0.007 ~ 0.41배, 최대 낙폭 84 ~ 99.6%" in md and "0.007 ~ 0.41배" in s["account_ko"] and "84 ~ 99.6%" in s["account_ko"]
    assert s["account_range"] == {"x_min": 0.007, "x_max": 0.41, "dd_min_pct": 84.0, "dd_max_pct": 99.6}
    # every loss in the table is a loss: the page counts 12 of 12 minus cells
    assert all(r["net_pct"] < 0 for tf in s["main"].values() for r in tf.values())


def test_the_study_hashes_are_the_documents_hashes():
    s = _study()
    assert s["prereg_sha256"] == _sha(os.path.join(DOCS, "PREREG_ZONEFLIP.md")) == "202d638e4a3d72aacc1d8ac601f9372f0ed4fdb5a923c5e8ecabadafaa642c8a"
    assert s["results_sha256"] == _sha(os.path.join(DOCS, "RESULTS_ZONEFLIP.md"))
    assert s["code_sha256"] == _sha(os.path.join(DOCS, "lib_zoneflip.py.txt")) and s["code_sha256"].startswith("b4a5f6d0")
    assert all(len(s[k]) == 64 for k in ("prereg_sha256", "results_sha256", "code_sha256"))
    assert s["where"].startswith("docs/zoneflip-reel/RESULTS_ZONEFLIP.md") and os.path.exists(os.path.join(ROOT, s["where"].split(" ")[0]))
    assert "실패" in s["one_line_ko"] or "통과 0칸" in s["one_line_ko"]


def test_the_study_file_failing_is_said_not_hidden(db, tmp_path):
    ok = view(db)
    assert ok["studies_state"] == "ok" and ok["member"]["study"]["verdict_ko"] == "실패" and ok["member"]["comparison"]["rows"][0]["study"] is not None
    for name, text, why in (("missing.json", None, "없어요"), ("broken.json", "{nope", "읽지 못했어요"), ("shape.json", json.dumps({"version": 2}), "모양이 달라요")):
        p = str(tmp_path / name)
        if text is not None:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text)
        out = S.build(db, None, now_ms=NOW, studies_path=p)
        assert out["state"] == "ok" and out["studies"] is None and out["studies_state"] == "error" and why in out["studies_reason_ko"]
        assert out["member"]["study"] is None and out["member"]["comparison"]["rows"][0]["study"] is None      # no invented numbers
        assert out["member"]["card"]["trades"]["closed"] == 5                                                    # the live record is untouched


def test_the_study_card_is_there_even_when_the_file_is_not(tmp_path):
    out = S.build(str(tmp_path / "nothing.db"), None, now_ms=NOW)
    assert out["studies"]["zoneflip"]["verdict"] == "FAIL"


# ---------------------------------------------------------------- the screen: wiring, safety, wording
def _routes_js():
    return _read(V4, "core", "routes.js")


def test_route_rail_find_and_inventory_wiring():
    r = _routes_js()
    assert '"strategies", "grid", "analysis", "compare", "path", "combo", "combo5y", "whatif", "league"]' in r
    assert 'league: {ko: "그림자 리그", group: "strat", title: "그림자 리그"},' in r
    assert re.search(r"\n  league: \(\) => \[R\(", r)                                                     # its own rail icon
    s = _read(V4, "core", "search.js")
    assert re.search(r'league: "[^"]*그림자[^"]*"', s)
    for f in ("league.js", "league.css", "league-kit.js", "league-member.js", "league-chart.js", "league-account.js", "league-table.js", "league-study.js"):
        assert os.path.exists(os.path.join(SCREENS, f)), f
    js = _read(SCREENS, "league.js")
    assert re.search(r"^export (async )?function mount\(el, ctx\)", js, re.M) and re.search(r"^export function unmount\(", js, re.M) and "export function update(" in js
    assert '"/api/v4/shadowleague' in js
    inv = _read(V4, "INVENTORY.md")
    for word in ("#/league", "/api/v4/shadowleague", "AGENTS_SHADOW_LEAGUE", "그림자 리그", "5년 시험은 이랬어요", "최대 낙폭", "league_studies.json"):
        assert word in inv, word


def _node(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    script = (f"const search = await import('{core}/search.js'); const routes = await import('{core}/routes.js');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_menu_strip_and_find_pick_the_screen_up_in_node():
    out = _node("""
    const items = Object.entries(routes.SCREENS).filter(([n, m]) => !m.hidden).map(([n, m]) => ({kind: 'screen', id: n, label: m.ko, code: n, words: `${m.title} ${search.ALIAS[n] || ''}`}));
    const find = (q) => search.rank(search.norm(q), items, 5).map((x) => x.id);
    const strat = routes.navGroups({wide: true}).find((g) => g.group === 'strat').items.map((it) => [it.id, it.ko]);
    console.log(JSON.stringify({shadow: find('그림자'), ssl: find('ㄱㄹㅈㄹㄱ'), movie: find('릴스'), strat, key: routes.keyOf('league'), g: routes.SCREENS.league,
      icon: typeof routes.screenIcon}));""")
    assert out["shadow"][0] == "league" and out["ssl"][0] == "league" and "league" in out["movie"]
    assert out["strat"][-1] == ["league", "그림자 리그"] and out["strat"][-2] == ["whatif", "만약 실험실"]
    assert out["key"] is None and out["g"] == {"ko": "그림자 리그", "group": "strat", "title": "그림자 리그"}


LEAGUE_JS = ("league.js", "league-kit.js", "league-member.js", "league-chart.js", "league-account.js", "league-table.js", "league-study.js")


def test_no_html_parsing_no_own_number_format_no_outside_hosts():
    for f in LEAGUE_JS:
        src = _read(SCREENS, f)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "createContextualFragment", "document.write", "eval(", "new Function"):
            assert bad not in src, (f, bad)
        assert "toLocaleString" not in src and "Intl.NumberFormat" not in src and "toFixed(" not in src, f
        assert not re.search(r"https?://", src), f
        assert "수수료·펀딩·슬리피지 포함" not in src and "지금 비교는 합격·불합격을 뜻하지 않습니다" not in src, f      # the captions are core/ui.js's
        for m in re.finditer(r"from \"(\.\./core/[^\"]+)\"", src):
            assert m.group(1) == "../core/pb.js", (f, m.group(1))


def test_css_only_tokens_and_sizes_from_the_scale():
    css = re.sub(r"/\*.*?\*/", "", _read(SCREENS, "league.css"), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\brgba?\(\s*\d", css) and "hsl(" not in css
    sizes = [m.group(1).strip() for m in re.finditer(r"font-size:\s*([^;}]+)", css)]
    for m in re.finditer(r"(?<![-\w])font:\s*([^;}]+)", css):
        v = m.group(1).strip()
        if not v.startswith(("inherit", "var(")):
            v = re.sub(r"^(?:(?:italic|normal|bold|\d00)\s+)*", "", v)
            sizes.append(re.match(r"(var\([^)]*\)|[\d.]+[a-z%]*)", v).group(1))
    assert sizes and all(re.fullmatch(r"var\(--t-(2xs|xs|sm|md|lg|xl|2xl)\)", x) for x in sizes), sizes
    assert 'overflow-x: auto' not in css.replace(".tbl-wrap", "")                           # no sideways page scroll of our own
    # every wide table scrolls inside its own box
    study = _read(SCREENS, "league-study.js")
    assert study.count('class: "tbl-wrap') >= 2 and "lg-stack" in study


def test_honest_words_are_in_the_screen():
    kit = _read(SCREENS, "league-kit.js")
    for w in ("진짜 계좌도, 돈도, 주문도 없어요", "을 받지 않아요. 여러 번 시험한 만큼의 보정에도 세지 않아요", "실제 주문이 아니에요", "참고용, 판정 아님", "솔직한 기대",
              "아직 켜지 않았어요", "서버의 설정 파일", "이 화면에는 버튼이 없어요", "기록 파일을 읽지 못했어요", "'거래 0건'처럼 보이지 않으려고", "자료 표 없음"):
        assert w in kit, w
    member = _read(SCREENS, "league-member.js")
    assert "progressBar(" in member and "닫힌 거래" in member and "표 없음" in member and "5년 시험과 나란히" in member
    study = _read(SCREENS, "league-study.js")
    assert "5년 시험은 이랬어요" in study and 'id: "lg-study"' in study and "prereg_sha256" in study and "못 읽음" in study
    chart = _read(SCREENS, "league-chart.js")
    assert "makeChart" in chart and "동전 던지기 중앙값" in chart and "10~90% 띠" in chart and "선 그리기 전" in chart
    acct = _read(SCREENS, "league-account.js")
    assert "ui.assume(" in acct and "최대 낙폭" in acct and "기록 전" in acct
    js = _read(SCREENS, "league.js")
    assert "새로 못 읽음" in js and "ctx.every(" in js and 'ctx.watch("summary"' in js        # the verdict date is the server's, never typed in
    for f in LEAGUE_JS:
        assert not re.search(r"합격(?!·불합격을 정하)|추천|하세요", _read(SCREENS, f).replace("합격·불합격을 정하는 비교가 아니에요", "")), f


# ---------------------------------------------------------------- the cards rendered in node (the tiny DOM)
def _render(call: str, data: dict) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    base = "file://" + SCREENS
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\n"
              f"const K = await import('{base}/league-kit.js'); const M = await import('{base}/league-member.js');\n"
              f"const C = await import('{base}/league-chart.js'); const A = await import('{base}/league-account.js');\n"
              f"const T = await import('{base}/league-table.js'); const Y = await import('{base}/league-study.js');\n"
              f"const d = {json.dumps(data)}; const m = d.member; const ctx = {{alive: () => true, track() {{}}}};\n"
              f"const nodes = ({call});\n"
              "console.log(JSON.stringify(D.walk(nodes)));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    out["text"] = re.sub(r"\s+", " ", out["text"])                     # the walk joins text nodes with a space: read it as one line
    return out


def test_off_card_says_how_it_is_turned_on(tmp_path):
    d = view(str(tmp_path / "nothing.db"))
    t = _render("K.notStartedCard(d)", d)["text"]
    assert "아직 켜지 않았어요" in t and "꺼짐" in t and "서버의 설정 파일" in t and "이 화면에는 버튼이 없어요" in t
    assert "AGENTS_SHADOW_LEAGUE=1" in t and "/etc/paperbot/agents.env" in t and "다음 15분 차례부터" in t
    assert "영상 매매법 (매물대 지지→저항 전환)" in t and not re.search(r"\d+건", t)           # no count of anything: nothing was recorded
    study = _render("Y.studyCard(d, {study: d.studies.zoneflip, comparison: null})", d)["text"]
    assert "5년 시험은 이랬어요" in study and "0 / 8" in study and "8칸 중 통과 0칸" in study
    assert "실패" in study and "202d638e" in study and "지금 (라이브)" in study
    assert "아직 기록이 없어요" in study and "표 없음" not in study and "읽지 못함" not in study           # nothing recorded: said so


def test_error_card_shows_the_reason_and_no_zero(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    with open(p, "wb") as fh:
        fh.write(b"garbage" * 100)
    d = view(p)
    t = _render("K.errorCard(d, () => {})", d)["text"]
    assert "기록 파일을 읽지 못했어요" in t and "망가졌" in t and "DatabaseError" in t and "다시 읽기" in t and "'거래 0건'처럼 보이지 않으려고" in t
    assert not re.search(r"\d+건", t.replace("'거래 0건'처럼", "")) and "기록 중" not in t
    study = _render("Y.studyCard(d, {study: d.studies.zoneflip, comparison: null})", d)["text"]
    assert "읽지 못함" in study and "아직 기록이 없어요" not in study                               # an unreadable record is not 'no record'


def test_member_card_words(db):
    d = view(db)
    t = _render("M.memberCard(d, m)", d)["text"]
    assert "영상 매매법 (매물대 지지→저항 전환)" in t and "기록 중" in t and "참고용, 판정 아님" in t and "5년 시험 실패" in t
    assert "닫힌 거래 30건까지" in t and "25건 더 쌓여야 해요" in t and "표본 적음" in t                       # 5 closed of 30: the waiting bar
    assert "기록 시작일" in t and "10월 7일" in t and "진입 7 · 건너뜀 6" in t and "뒤늦게 1" in t
    assert "BCH 15분" in t and "시세를 받지 못함 (2봉 늦음)" in t and "워밍업 중인 칸 1개" in t
    assert "−0.06%" not in t and "+0.06%" in t                                                              # 0.06 % a trade, signed
    big = str(db) + "2"
    W.build_rich(big, now=NOW, days=24, seed=2)
    d2 = view(big)
    t2 = _render("M.memberCard(d, m)", d2)["text"]
    assert "닫힌 거래 30건까지" not in t2                                                                      # past 30: no waiting bar


def test_member_card_when_off_halted_and_waiting(tmp_path):
    p = str(tmp_path / "a.db")
    W.build(p, ticked=False, with_data=False, start=NOW + 3 * W.H)
    t = _render("M.memberCard(d, m)", view(p))["text"]
    assert "꺼짐" in t and "아직 켜지 않았어요" in t and "AGENTS_SHADOW_LEAGUE=1" in t and "서버의 설정 파일" in t
    p2 = str(tmp_path / "b.db")
    W.build(p2, with_data=False, halted="정의가 바뀜")
    t = _render("M.memberCard(d, m)", view(p2))["text"]
    assert "멈춤(정의가 바뀜)" in t and "새 멤버" in t
    p3 = str(tmp_path / "c.db")
    W.build(p3, start=NOW + 3 * W.H, with_data=False, series_mode="waiting", activated=NOW - W.H)
    t = _render("M.memberCard(d, m)", view(p3))["text"]
    assert "시작 전" in t and "0.1일 뒤 시작" in t and "전이라 아직 기록할 봉이 없어요" in t


def test_cards_of_an_older_file_say_the_table_is_missing(tmp_path):
    p = str(tmp_path / "v1.db")
    W.build(p, schema=1)
    d = view(p)
    for call in ("C.curveCard(ctx, m, d)", "A.accountCard(ctx, m)"):
        t = _render(call, d)["text"]
        assert "자료 표 없음" in t and "읽지 못한 것을 0이나 '없음'으로 보이지 않으려고" in t
        assert "USDT" not in t and "5,000" not in t                                                         # no balance that was never read
    t = _render("T.tableCard(m)", d)["text"]
    assert "코인 × 봉" in t and "BTC" in t and "자료 표 없음" not in t
    p2 = str(tmp_path / "x.db")
    W.build(p2)
    c = sqlite3.connect(p2)
    c.execute("DROP TABLE trades")
    c.commit()
    c.close()
    d2 = view(p2)
    t = _render("M.memberCard(d, m)", d2)["text"]
    assert "표 없음" in t and "닫힌 거래 30건까지" not in t and not re.search(r"닫힌 거래\s+0", t)
    assert "자료 표 없음" in _render("T.tradesCard(m)", d2)["text"]


def test_curve_account_table_and_trades_words(db):
    d = view(db)
    t = _render("C.curveCard(ctx, m, d)", d)["text"]
    assert "누적 수익 곡선" in t and "이 멤버" in t and "동전 던지기 중앙값" in t and "동전 던지기 10~90% 띠" in t
    assert "거래 4건째까지" in t and "이 멤버 −0.10%" in t and "동전 중앙값 +0.38%" in t and "띠 −0.40% ~ +1.16%" in t
    assert "지금은 띠 안에 있어요" in t and "표본 적음" in t and "동전 던지기 쪽이 아직 다 안 끝난 거래 1건" in t
    a = _render("A.accountCard(ctx, m)", d)["text"]
    assert "5,000.00 USDT로 시작" in a and "증거금 20% × 20배" in a and "4.5% 거꾸로 가면 강제 청산" in a and "지금 잔고" in a and "5,051.95 USDT" in a
    assert "최대 낙폭" in a and "3.2%" in a and "모의 · 실제 시세 · 수수료·펀딩·슬리피지 포함" in a and "0.007 ~ 0.41배, 최대 낙폭 84 ~ 99.6%" in a
    tb = _render("T.tableCard(m)", d)["text"]
    assert "BTC" in tb and "오류" in tb and "워밍업" in tb and "150/300" in tb and "+열림" in tb and "합계" in tb and "+0.30%" in tb
    tr = _render("T.tradesCard(m)", d)["text"]
    assert "전체 6건 중 최근 6건" in tr and "열려 있음" in tr and "목표 도달" in tr and "손절" in tr and "48봉 시간 청산" in tr and "뒤늦게" not in tr
    sg = _render("T.signalsBlock(m)", d)["text"]
    assert "신호 기록" in sg and "최근 14개" in sg


def test_study_card_next_to_the_live_record(db):
    d = view(db)
    t = _render("Y.studyCard(d, m)", d)["text"]
    assert "5년 시험은 이랬어요" in t and "실패" in t and "0 / 8" in t and "12 / 12" in t and "3,173건" in t and "2026-10-06" in t
    assert "202d638e" in t and "지금 (라이브)" in t and "5년 시험 1기" in t and "−0.10%" in t and "796건" in t and "손절 0.5~0.8% · 목표 2.0~2.5%" in t
    assert "+0.30%" in t and "3건 · 승률 67%" in t and "표본 적음" in t                                       # 15m live: 3 trades, 0.3 %, small
    assert "이 규칙" in t and "동전 던지기 −0.14%" in t
    # the study card does not need the live record
    t2 = _render("Y.studyCard(d, {study: d.studies.zoneflip, comparison: {state: 'unavailable'}})", d)["text"]
    assert "표 없음" in t2 and "−0.10%" in t2
    broken = S.build(db, None, now_ms=NOW, studies_path=os.path.join(os.path.dirname(db), "nope.json"))
    t3 = _render("Y.studyCard(d, d.member)", broken)["text"]
    assert "못 읽음" in t3 and "5년 시험이 없었다는 뜻이 아니에요" in t3 and "−0.10%" not in t3
    unknown = _render("Y.studyCard(d, {study: null})", d)["text"]
    assert "자료 없음" in unknown and "아직 몰라요" in unknown


def test_head_card_words():
    t = _render("K.headCard({accounts: 331, verdictTs: Date.UTC(2026, 10, 4, 0, 0)})", view("/nonexistent/x.db"))["text"]
    assert "그림자 리그" in t and "331개 모의 계좌 중 하나가 아니에요" in t and "11/04 판정을 받지 않아요" in t and "실제 주문이 아니에요" in t and "참고용, 판정 아님" in t
    t = _render("K.headCard({})", view("/nonexistent/x.db"))["text"]
    assert "모의 계좌들 중 하나가 아니에요" in t and "30일 판정을 받지 않아요" in t


# ---------------------------------------------------------------- against the bot's own code (runs only where the agents code is merged)
def test_matches_the_bots_own_database_shape_and_view(tmp_path, monkeypatch):
    """When paperbot/shadowleague is on the branch (the merged install), a database written by the bot's own tick has exactly the
    tables, columns and indexes of tests/league_world.py, and this module's numbers equal the bot's view.py on it."""
    V = pytest.importorskip("paperbot.shadowleague.view")
    LG = pytest.importorskip("paperbot.shadowleague.league")
    TL = pytest.importorskip("test_shadowleague_league")
    monkeypatch.setattr(LG, "WORK_S", 1e6)
    monkeypatch.setattr(LG, "HARD_S", 1e6)
    ex, m, st = TL.world(tmp_path, k=10, coins=("BTC", "ETH"))
    st, _ = TL.ticks(st, ex, m, TL.ALL)
    path, now = st.path, ex.now_ms
    st.close()
    real, mine = sqlite3.connect(path), sqlite3.connect(":memory:")
    mine.executescript(W.ddl(2))
    q = "SELECT name FROM sqlite_master WHERE type = '{}' AND name NOT LIKE 'sqlite_%'"
    for kind in ("table", "index"):
        assert {r[0] for r in real.execute(q.format(kind))} == {r[0] for r in mine.execute(q.format(kind))}
    for (t,) in real.execute(q.format("table")):
        assert [tuple(r[1:]) for r in real.execute(f"PRAGMA table_info({t})")] == [tuple(r[1:]) for r in mine.execute(f"PRAGMA table_info({t})")], t
    real.close()
    mid = S.build(path, None, now_ms=now)["selected"]
    bot, out = V.member(path, mid, now), S.build(path, mid, now_ms=now)
    d = out["member"]
    assert out["state"] == d["state"] == "ok" and bot["state"] == "ok" and bot["card"]["trades"]["closed"] > 0
    for k in ("status", "series", "warming", "errors", "signals", "started_at_ms", "activated_ms", "last_tick_ms"):
        assert bot["card"][k] == d["card"][k], k
    for k, v in bot["card"]["trades"].items():
        assert v == d["card"]["trades"][k] or approx(v, d["card"]["trades"][k], 1e-9), k
    bp, dp = bot["curve"]["per_trade"], d["per_trade"]
    assert (bp["n"], bp["clones_per_trade"], bp["awaiting_clones"]) == (dp["n"], dp["clones_per_trade"], dp["awaiting_clones"]) and bp["points"]
    for x, y in zip(bp["points"], dp["points"]):
        assert all(approx(x[k], y[k], 1e-3) for k in x), (x, y)
    for sc, blk in bot["curve"]["account"]["scopes"].items():
        assert blk["asof_ms"] == d["account"]["scopes"][sc]["asof_ms"]
        for x, y in zip(blk["points"], d["account"]["scopes"][sc]["points"]):
            assert x["day_ms"] == y["day_ms"] and approx(x["member_equity"], y["equity"], 0.011) and (x["taken"], x["liquidated"]) == (y["taken"], y["liquidated"])
    for x, y in zip(bot["table"], d["table"]["cells"]):
        assert all(x[k] == y[k] for k in ("coin", "tf", "status", "signals", "taken", "open", "closed", "wins"))
    assert [t["trade_id"] for t in bot["trades"]] == [t["trade_id"] for t in d["trades"]["rows"]]
    assert bot["study"]["main"] == d["study"]["main"] and bot["study"]["prereg_sha256"] == d["study"]["prereg_sha256"]
