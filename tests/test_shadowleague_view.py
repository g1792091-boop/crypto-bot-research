"""view.py: what the dashboard reads. States (not_started / error / ok), the exact dict shapes, the curves against their
clones, the honest labels, and the 5-year study numbers against the committed result document."""

import json
import os
import re
import subprocess

import numpy as np
import pytest

from shadowleague_world import HOUR, T0, FakeExchange, make_member, now_after_bar, open_store
from test_shadowleague_league import ALL, START, ticks, world
from paperbot.shadowleague import LABEL_KO
from paperbot.shadowleague import account as AC
from paperbot.shadowleague import league as LG
from paperbot.shadowleague import study as SD
from paperbot.shadowleague import view as V
from paperbot.shadowleague.store import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """A league database after a whole synthetic run (6 trades, 60 clones, K = 10)."""
    tmp = tmp_path_factory.mktemp("view")
    ex, m, st = world(tmp)
    st, _ = ticks(st, ex, m, ALL)
    return {"path": st.path, "member": m, "now": ex.now_ms, "store": st}


# ------------------------------------------------------------------------------------------------ states
def test_no_database_is_not_started(tmp_path):
    p = str(tmp_path / "shadow_league.db")
    assert V.overview(p) == {"state": "not_started", "label_ko": LABEL_KO}
    assert V.member(p, "zoneflip") == {"state": "not_started", "label_ko": LABEL_KO}
    assert not os.path.exists(p)                                   # reading never creates the file


def test_a_database_without_any_member_is_not_started(tmp_path):
    st = open_store(tmp_path)
    st.close()
    assert V.overview(st.path)["state"] == "not_started"
    assert V.member(st.path, "zoneflip")["state"] == "not_started"


def test_an_unreadable_database_is_an_error_with_a_reason_never_empty(tmp_path):
    p = tmp_path / "shadow_league.db"
    p.write_bytes(b"this is not a database " * 200)
    for out in (V.overview(str(p)), V.member(str(p), "zoneflip")):
        assert out["state"] == "error" and out["reason"] and out["label_ko"] == LABEL_KO
    (tmp_path / "dir.db").mkdir()
    assert V.overview(str(tmp_path / "dir.db"))["state"] == "error"
    st = open_store(tmp_path, "cut.db")
    st.conn.execute("DROP TABLE trades")                           # a half-migrated or damaged file
    st.add_member("zoneflip", "x", "d", {}, "h", 0, 0)
    st.close()
    out = V.overview(str(tmp_path / "cut.db"))
    assert out["state"] == "error" and "trades" in out["reason"]


def test_reading_is_read_only(db):
    V.overview(db["path"], db["now"])
    V.member(db["path"], db["member"].member_id, db["now"])
    ro = V._open(db["path"])[0]
    with pytest.raises(Exception):
        ro.execute("DELETE FROM trades")
    ro.close()
    assert db["store"].conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 6


# ------------------------------------------------------------------------------------------------ the shapes
CARD_KEYS = {"member_id", "name_ko", "blurb_ko", "label_ko", "status", "status_ko", "halted_ko", "started_at_ms",
             "activated_ms", "last_tick_ms", "days", "series", "warming", "errors", "signals", "trades", "study"}


def test_the_member_card_shape(db):
    o = V.overview(db["path"], db["now"])
    assert o["state"] == "ok" and o["label_ko"] == LABEL_KO and o["schema_version"] == 2
    assert set(o) == {"state", "label_ko", "as_of_ms", "schema_version", "last_tick", "members"}
    c = o["members"][0]
    assert set(c) == CARD_KEYS and c["member_id"] == "test" and c["label_ko"] == LABEL_KO
    assert c["status"] == "recording" and c["status_ko"] == "기록 중"
    assert c["started_at_ms"] == START and c["activated_ms"] and c["days"] == pytest.approx((db["now"] - START) / 86_400_000, abs=0.01)
    assert set(c["signals"]) == {"total", "taken", "skipped", "pending", "late"} and c["signals"]["taken"] == 6
    assert set(c["trades"]) == {"open", "closed", "wins", "win_pct", "avg_net_pct", "avg_gross_pct", "sum_net_pct"}
    assert c["trades"]["closed"] == 6 and c["trades"]["open"] == 0 and c["trades"]["wins"] == 2
    assert c["series"] == {"recording": 1, "warming": 0, "waiting": 0, "error": 0, "total": 1}
    assert c["study"]["verdict"] == "FAIL" and c["study"]["verdict_ko"] == "실패"
    json.dumps(o)                                                  # plain values only


def test_status_off_warming_recording_error_halted(db, tmp_path):
    now = db["now"]
    assert V.overview(db["path"], now)["members"][0]["status"] == "recording"
    assert V.overview(db["path"], now + LG.STALE_MS + 1)["members"][0]["status"] == "off"      # nobody has ticked for hours
    # warming
    from shadowleague_world import series_arrays
    ex = FakeExchange(coins=("BTC",), tfs=("1h",), arrays={("BTC", "1h"): {k: v[:150] for k, v in series_arrays("BTC", "1h").items()}})
    m = make_member(start_ms=T0 + 100 * HOUR)
    st = open_store(tmp_path, "warm.db")
    ex.now_ms = now_after_bar("1h", 149)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    c = V.overview(st.path, ex.now_ms)["members"][0]
    assert c["status"] == "warming" and c["warming"] == [{"coin": "BTC", "tf": "1h", "have": 150, "need": 300,
                                                         "note": "워밍업 중 (150봉 더 필요)"}]
    # error: the feed fails from the start
    ex2, m2, st2 = world(tmp_path, name="err.db")
    ex2.fail = 99
    ex2.now_ms = now_after_bar("1h", 1099)
    LG.League(st2, (m2,), ex2.get).tick(ex2.now_ms)
    c = V.overview(st2.path, ex2.now_ms)["members"][0]
    assert c["status"] == "error" and c["errors"][0]["coin"] == "BTC" and "TimeoutError" in c["errors"][0]["note"]
    # waiting (before the start date)
    ex3, m3, st3 = world(tmp_path, name="wait.db")
    ex3.now_ms = now_after_bar("1h", 899)
    LG.League(st3, (m3,), ex3.get).tick(ex3.now_ms)
    assert V.overview(st3.path, ex3.now_ms)["members"][0]["status"] == "waiting"
    # halted
    st3.halt_member("test", "정의가 바뀜")
    assert V.overview(st3.path, ex3.now_ms)["members"][0]["status"] == "halted"
    # never ticked: off
    st4 = open_store(tmp_path, "never.db")
    st4.add_member("test", "x", "d", json.loads(json.dumps(m.spec())), m.spec_sha256(), START, 0)
    assert V.overview(st4.path, 10 ** 13)["members"][0]["status"] == "off"


def test_a_late_start_marks_the_signals_computed_before_the_switch_was_turned_on(tmp_path):
    ex, m, st = world(tmp_path)
    ex.now_ms = now_after_bar("1h", 1539)                           # switched on 539 bars after the start date
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    c = V.overview(st.path, ex.now_ms)["members"][0]
    assert c["signals"]["total"] > 0 and c["signals"]["late"] == c["signals"]["total"]
    ex.now_ms = now_after_bar("1h", 1700)
    LG.League(st, (m,), ex.get).tick(ex.now_ms)
    d = V.member(st.path, "test", ex.now_ms)
    assert [t["late"] for t in d["trades"] if t["signal_ms"] < st.member("test")["activated_ms"]]
    assert all(t["late"] is False for t in d["trades"] if t["signal_ms"] >= st.member("test")["activated_ms"])


DETAIL_KEYS = {"state", "label_ko", "as_of_ms", "card", "curve", "table", "trades", "signals", "comparison", "study"}
TRADE_KEYS = {"trade_id", "coin", "tf", "side", "side_ko", "status", "signal_ms", "entry_ms", "entry_px", "stop_px", "target_px",
              "exit_ms", "exit_px", "reason", "reason_ko", "hold_bars", "gross_pct", "net_pct", "stop_dist_pct",
              "target_dist_pct", "account", "recorded_ms", "late", "label_ko"}
TABLE_KEYS = {"coin", "tf", "status", "status_ko", "note", "last_bar_ms", "warm_have", "warm_need", "signals", "taken", "open",
              "closed", "wins", "avg_net_pct", "sum_net_pct"}


def test_the_detail_shape(db):
    d = V.member(db["path"], "test", db["now"])
    assert set(d) == DETAIL_KEYS and d["state"] == "ok" and d["label_ko"] == LABEL_KO
    assert set(d["card"]) == CARD_KEYS
    assert set(d["curve"]) == {"per_trade", "account"}
    pt = d["curve"]["per_trade"]
    assert set(pt) == {"unit_ko", "n", "clones_per_trade", "awaiting_clones", "points", "label_ko", "note_ko"}
    assert pt["clones_per_trade"] == 10 and pt["n"] + pt["awaiting_clones"] == 6
    for p in pt["points"]:
        assert set(p) == {"n", "ms", "member_cum_pct", "flip_p10", "flip_p50", "flip_p90", "member_avg_pct", "flip_avg_p50"}
        assert p["flip_p10"] <= p["flip_p50"] <= p["flip_p90"]
    ac = d["curve"]["account"]
    assert set(ac) == {"unit_ko", "scopes", "label_ko"} and set(ac["scopes"]) == {"15m", "30m", "1h", "4h", "all"}
    s = ac["scopes"]["1h"]
    assert set(s) == {"points", "asof_ms", "start_equity", "label_ko", "worlds"} and s["start_equity"] == 5000.0
    assert s["points"] and set(s["points"][0]) == {"day_ms", "member_equity", "member_ret_pct", "flip_p10", "flip_p50", "flip_p90",
                                                  "taken", "liquidated"}
    assert ac["scopes"]["15m"]["points"] == []                      # no trades there: empty, not invented
    assert len(d["table"]) == 1 and set(d["table"][0]) == TABLE_KEYS
    assert len(d["trades"]) == 6 and set(d["trades"][0]) == TRADE_KEYS
    assert set(d["trades"][0]["account"]) == {"taken", "ret_pct", "equity", "liquidated"}
    assert [t["entry_ms"] for t in d["trades"]] == sorted((t["entry_ms"] for t in d["trades"]), reverse=True)   # newest first
    assert set(d["signals"][0]) == {"signal_id", "coin", "tf", "side", "side_ko", "bar_ms", "plan_entry", "stop", "target", "rr",
                                    "touches", "status", "status_ko"}
    assert [c["tf"] for c in d["comparison"]] == ["15m", "30m", "1h", "4h"]
    assert set(d["comparison"][0]) == {"tf", "live", "study", "study_p12", "study_vs_flip", "label_ko"}
    assert d["study"]["verdict"] == "FAIL"
    json.dumps(d)


def test_the_table_covers_every_coin_and_timeframe_even_before_anything_ran(tmp_path):
    st = open_store(tmp_path)
    m = LG.ZONEFLIP
    st.add_member(m.member_id, m.name_ko, m.detector.id, m.spec(), m.spec_sha256(), m.start_ms, 0)
    d = V.member(st.path, "zoneflip", 1)
    assert [(r["coin"], r["tf"]) for r in d["table"]] == [(c, tf) for c in ("BTC", "ETH", "SOL", "DOGE", "LTC", "BCH")
                                                           for tf in ("15m", "30m", "1h", "4h")]
    assert {r["status"] for r in d["table"]} == {"waiting"} and d["card"]["status"] == "off"
    assert d["trades"] == [] and d["curve"]["per_trade"]["points"] == [] and d["curve"]["per_trade"]["n"] == 0
    assert all(c["live"]["net_pct"] is None and c["live"]["trades"] == 0 for c in d["comparison"])


def test_only_the_last_50_trades_are_listed(tmp_path):
    st = open_store(tmp_path)
    m = make_member()
    st.add_member(m.member_id, m.name_ko, m.detector.id, m.spec(), m.spec_sha256(), START, 0)
    for i in range(60):
        st.add_trade({"trade_id": f"t{i:02d}", "member_id": "test", "coin": "BTC", "tf": "1h", "side": 1, "signal_ms": 1000 + i,
                      "entry_ms": 2000 + i, "entry_px": 100.0, "stop_px": 99.0, "target_px": 103.0, "sl_dist": 0.01,
                      "tp_dist": 0.03, "status": "closed", "exit_ms": 3000 + i, "exit_px": 103.0, "reason": "TP", "hold": 3,
                      "gross_raw": 0.03, "gross": 0.0296, "fee": 0.001, "funding": 0.0, "net": 0.0286, "mae": -0.001,
                      "mfe": 0.03, "recorded_ms": 1, "closed_ms": 2})
    d = V.member(st.path, "test", 10 ** 13)
    assert len(d["trades"]) == V.LAST_TRADES == 50
    assert d["trades"][0]["trade_id"] == "t59" and d["trades"][-1]["trade_id"] == "t10"
    assert d["card"]["trades"]["closed"] == 60                      # the card counts all of them


# ------------------------------------------------------------------------------------------------ the curves
def test_the_per_trade_curve_is_the_member_sum_against_the_clone_worlds(db):
    st = db["store"]
    d = V.member(db["path"], "test", db["now"])
    pt = d["curve"]["per_trade"]
    trades = {t["trade_id"]: t for t in st.trades("test")}
    cl = {}
    for c in st.clones_of("test"):
        cl.setdefault(c["trade_id"], {})[c["k"]] = c
    ready = sorted((t for t in trades.values() if t["status"] == "closed" and all(x["status"] == "closed" for x in cl[t["trade_id"]].values())),
                   key=lambda t: (t["exit_ms"], t["trade_id"]))
    assert pt["n"] == len(ready) == len(pt["points"]) and pt["n"] >= 1
    cum = np.cumsum([t["net"] * 100 for t in ready])
    worlds = np.cumsum([[cl[t["trade_id"]][k]["net"] * 100 for k in range(10)] for t in ready], axis=0)
    for i, p in enumerate(pt["points"]):
        assert p["n"] == i + 1 and p["ms"] == ready[i]["exit_ms"]
        assert p["member_cum_pct"] == pytest.approx(cum[i], abs=1e-3)
        assert p["flip_p10"] == pytest.approx(np.percentile(worlds[i], 10), abs=1e-3)
        assert p["flip_p50"] == pytest.approx(np.percentile(worlds[i], 50), abs=1e-3)
        assert p["flip_p90"] == pytest.approx(np.percentile(worlds[i], 90), abs=1e-3)
        assert p["member_avg_pct"] == pytest.approx(cum[i] / (i + 1), abs=1e-3)


def test_a_trade_whose_clones_are_not_all_decided_is_counted_as_waiting_not_dropped_silently(tmp_path):
    ex, m, st = world(tmp_path, k=50)
    ticks(st, ex, m, [1259])                                       # clones that enter later are still pending
    d = V.member(st.path, "test", ex.now_ms)
    pt = d["curve"]["per_trade"]
    assert d["card"]["trades"]["closed"] == 1 and pt["n"] == 0 and pt["awaiting_clones"] == 1 and pt["points"] == []


def test_the_account_curve_matches_the_stored_daily_equity_and_has_a_clone_band(db):
    st = db["store"]
    d = V.member(db["path"], "test", db["now"])
    sc = d["curve"]["account"]["scopes"]["1h"]
    stored = {r["day_ms"]: r["equity"] for r in st.conn.execute("SELECT * FROM account_daily WHERE scope = '1h'")}
    assert sc["worlds"] == 10 and sc["asof_ms"] > START
    for p in sc["points"]:
        assert p["day_ms"] % AC.DAY_MS == 0 and p["flip_p10"] <= p["flip_p50"] <= p["flip_p90"]
        if p["day_ms"] + AC.DAY_MS <= sc["asof_ms"]:                # whole days before the cut: the member's stored equity
            assert p["member_equity"] == pytest.approx(stored[p["day_ms"]], abs=0.01)
    assert sc["points"][0]["day_ms"] == AC.day_start(START)


# ------------------------------------------------------------------------------------------------ honesty
def test_every_block_with_numbers_is_labelled_for_reference_not_a_verdict(db):
    d = V.member(db["path"], "test", db["now"])
    assert LABEL_KO == "참고용, 판정 아님"
    for blk in (d, d["card"], d["curve"]["per_trade"], d["curve"]["account"], d["curve"]["account"]["scopes"]["1h"],
                d["trades"][0], *d["comparison"]):
        assert blk["label_ko"] == LABEL_KO
    assert d["study"]["verdict_ko"] == "실패" and "5년" in d["study"]["one_line_ko"]
    assert "예상" in d["study"]["honest_ko"] and "판정 아님" in d["study"]["honest_ko"]


def test_the_live_record_sits_next_to_the_study_per_timeframe(db):
    d = V.member(db["path"], "test", db["now"])
    one_h = next(c for c in d["comparison"] if c["tf"] == "1h")
    assert one_h["live"]["trades"] == 6 and one_h["study"]["is"]["trades"] == 180 and one_h["study_p12"] == 0.99
    assert one_h["study_vs_flip"] == {"main_pct": -0.35, "flip_pct": -0.15, "p": 0.93}
    assert next(c for c in d["comparison"] if c["tf"] == "15m")["live"]["net_pct"] is None      # no live trade: no number


# ------------------------------------------------------------------------------------------------ the 5-year numbers
def _results_text():
    for ref in ("claude/keen-pasteur-wav02u",):
        r = subprocess.run(["git", "-C", ROOT, "show", f"{ref}:docs/zoneflip-reel/RESULTS_ZONEFLIP.md"], capture_output=True)
        if r.returncode == 0:
            return r.stdout
    return None


def _num(x):
    x = x.replace("−", "-").replace("+", "").replace("%", "").replace("배", "").replace("*", "").strip()
    return float(x)


def test_the_study_numbers_are_the_committed_results():
    raw = _results_text()
    if raw is None:
        pytest.skip("branch claude/keen-pasteur-wav02u (the committed result document) is not in this clone")
    import hashlib
    assert hashlib.sha256(raw).hexdigest() == SD.STUDIES["zoneflip"]["results_sha256"]
    text = raw.decode("utf-8")
    sec = text[text.index("## 봉 길이별 결과"):text.index("## 동전 던지기와 비교")]
    tf_of = {"15분봉": "15m", "30분봉": "30m", "1시간봉": "1h", "4시간봉": "4h"}
    period = {"1기": "is", "2기": "oos", "3기": "pre"}
    tf, seen = None, 0
    for line in sec.splitlines():
        m = re.match(r"\*\*(15분봉|30분봉|1시간봉|4시간봉)\*\*", line)
        if m:
            tf = tf_of[m.group(1)]
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if tf and cells and cells[0] in period:
            got = SD.STUDIES["zoneflip"]["main"][tf][period[cells[0]]]
            pos, of = (int(x) for x in cells[8].replace(" ", "").split("/"))
            want = {"trades": int(cells[1].replace(",", "")), "win_pct": _num(cells[2]), "avg_win_pct": _num(cells[3]),
                    "avg_loss_pct": _num(cells[4]), "pf": _num(cells[5]), "net_pct": _num(cells[6]), "gross_pct": _num(cells[7]),
                    "coins_positive": pos, "coins_of": of, "flip_net_pct": _num(cells[9]), "account_x": _num(cells[10])}
            assert got == want, (tf, cells[0], got, want)
            seen += 1
    assert seen == 12
    fl = text[text.index("## 동전 던지기와 비교"):text.index("## 대조 설정")]
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in fl.splitlines() if re.match(r"\| (15분|30분|1시간|4시간) ", ln)]
    assert len(rows) == 4
    for r, key in zip(rows, ("15m", "30m", "1h", "4h")):
        assert SD.STUDIES["zoneflip"]["vs_flip"][key] == {"main_pct": _num(r[1]), "flip_pct": _num(r[2]), "p": _num(r[3])}
    p12 = re.search(r"15분 (\d\.\d+), 30분 (\d\.\d+), 1시간 (\d\.\d+), 4시간 (\d\.\d+)", text)
    assert [SD.STUDIES["zoneflip"]["p12"][k] for k in ("15m", "30m", "1h", "4h")] == [float(x) for x in p12.groups()]
    assert "3,173" in text and SD.STUDIES["zoneflip"]["trades_main"] == 3173 and SD.STUDIES["zoneflip"]["cells_passed"] == 0
