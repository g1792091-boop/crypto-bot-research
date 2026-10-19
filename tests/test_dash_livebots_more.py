"""실거래 screen, the owners' 10/19 additions (dash/more/livebots.py, read-only): 순위 (rank), 일정 (calendar), 지도 (map_view,
band), 비용 (costs) and 관제's "왜 지금 진입 안 하나" (whynow), on the hand-made live world (tests/livebots_world.py) and a
macro release file of the test's own.

- 순위: per strategy of the config the bot runs, the paper record and open position, the executors' followed trades, the
  7-day signals by what became of them, the 5-year numbers and the status word; a strategy traded under an earlier config
  is listed apart, never mixed in;
- 일정: the weekend and the ±30-minute macro pause exactly as paperbot/combo.py decides them (kst_weekend word for word, the
  same events file and window), the pause windows ahead, a file that runs out soon is said;
- 지도: exact binomial bands (checked against brute force), the wins so far, the cuts next to their 5-year numbers;
- 비용 and 지금: from the 거래 rows and the bots' own states; nothing there yet = missing, never zero.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

import livebots_world as W  # noqa: E402
from paperbot import combo as C  # noqa: E402
from paperbot import events  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from test_dash import SECRET, _store  # noqa: E402

NOW = W.NOW
H, MIN, DAY = W.H, W.MIN, W.DAY
PW = "correct horse battery"
FOMC = events.parse_ts("2026-10-28T18:00:00Z")          # data/macro_events.csv: FOMC statement, 14:00 ET
SAT_NOON_KST = events.parse_ts("2026-10-24T03:00:00Z")  # Saturday 12:00 KST
MON_KST = events.parse_ts("2026-10-25T15:00:00Z")       # Monday 00:00 KST


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    L._cache.clear()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")   # the run's own config (in the database)
    yield
    L._cache.clear()


@pytest.fixture
def world(tmp_path):
    return W.build_world(str(tmp_path / "w"))


@pytest.fixture
def rich(tmp_path, monkeypatch):
    p = W.build_world(str(tmp_path / "r"))
    m = W.live_checks(p, str(tmp_path / "r"), rich=True)
    for k, v in W.env_more_of(m).items():
        monkeypatch.setenv(k, v)
    return p


@pytest.fixture
def macro(tmp_path, monkeypatch):
    def use(*rows):
        f = tmp_path / "macro_events.csv"
        f.write_text("ts_utc,kind,source_url\n" + "".join(f"{ts},{k},https://example.org/{k}\n" for ts, k in rows), encoding="utf-8")
        monkeypatch.setattr(events, "PATH", f)
        events.reset()
    yield use
    events.reset()


# ---------------------------------------------------------------- 순위
def test_rank_lists_every_strategy_of_the_config_with_its_records(rich):
    r = L.rank(rich, NOW)
    assert r["combo"]["state"] == "ok" and r["n_strategies"] == 2 and r["n_settings"] == 3
    rows = {x["strategy"]: x for x in r["rows"]}
    s2, n3 = rows["S2_ST_ROC"], rows["N03_ADX_GC"]
    assert s2["in_config"] and n3["in_config"] and [m["order"] for m in s2["members"]] == [1, 3]
    assert s2["tfs"] == ["30m", "1h"]                                     # timeframes shortest first
    assert (s2["paper"]["n"], s2["paper"]["wins"], s2["paper"]["pnl"]) == (3, 2, -28.0)       # t1 +20, t3 -60, t5 +12
    assert s2["open"]["symbol"] == "BTCUSDT" and n3["open"] is None and r["open"]["strategy_id"] == "S2_ST_ROC"
    assert s2["sig"]["week"] == {"signals": 5, "entered": 3, "skipped": 1, "rejected": 1}
    assert n3["sig"]["week"] == {"signals": 9, "entered": 3, "filtered": 5, "waiting": 1} and n3["sig"]["last_stage"] == "waiting"
    assert n3["bt"]["type_ko"] == "추세" and n3["bt"]["win"] == 0.9516 and n3["bt"]["honest_win"] == 0.8363 and n3["bt_rank"] == 1
    assert math.isclose(n3["bt"]["per_week"], 10.72 / (30.44 / 7))
    assert s2["bt"] is None and s2["bt_rank"] is None                     # not a strategy of the 5-year reference
    assert n3["status"]["status"] == "주의" and n3["live"]["bybit"]["n"] >= 1
    assert r["ref"]["state"] == "ok" and r["ref"]["fit_win"] == 0.9132 and r["ref"]["honest_win"] == 0.7497


def test_rank_keeps_strategies_of_an_earlier_config_apart(rich):
    r = L.rank(rich, NOW)
    out = [x for x in r["rows"] if not x["in_config"]]
    assert [x["strategy"] for x in out] == r["unknown_strategies"] == ["F12_MSS_DISP", "F4_FAN", "N08_ICHI_WR"]
    assert all(x["members"] == [] and x["bt_rank"] is None for x in out)
    f4 = next(x for x in out if x["strategy"] == "F4_FAN")
    assert f4["status"]["status"] == "확실히 나쁨" and f4["paper"]["n"] == 10 and f4["paper"]["wins"] == 1
    assert [x["strategy"] for x in r["rows"][:2]] == ["S2_ST_ROC", "N03_ADX_GC"]   # the config's own first


def test_rank_says_what_it_could_not_read(tmp_path):
    p = W.build_world(str(tmp_path / "w"))
    os.remove(p["paper"])
    r = L.rank(p, NOW)
    assert r["combo"]["state"] == "missing" and "rows" not in r


# ---------------------------------------------------------------- 일정
def test_the_weekend_rule_is_the_bots_word_for_word():
    for ms in range(SAT_NOON_KST - 9 * DAY, SAT_NOON_KST + 9 * DAY, 37 * MIN):
        assert L.kst_weekend(ms) == C.kst_weekend(ms), ms
    assert L.weekend_span(SAT_NOON_KST) == (MON_KST - 2 * DAY, MON_KST)
    assert L.weekend_span(MON_KST - 1) == (MON_KST - 2 * DAY, MON_KST)        # Sunday 23:59 KST: still that weekend
    assert L.weekend_span(MON_KST) == (MON_KST + 5 * DAY, MON_KST + 7 * DAY)   # Monday: the next one


def test_calendar_pauses_around_a_release_like_the_bot(world, macro):
    macro(("2026-10-28T18:00:00Z", "FOMC"), ("2026-11-06T13:30:00Z", "NFP"), ("2027-01-13T13:30:00Z", "CPI"))
    c = L.calendar(world, FOMC - 10 * MIN)
    assert c["rules"] == {"macro_blackout_min": 30, "no_weekend": True}
    m = c["now"]["macro"]
    assert c["now"]["paused"] and m["kind"] == "FOMC" and (m["pause_from"], m["pause_to"]) == (FOMC - 30 * MIN, FOMC + 30 * MIN)
    assert c["now"]["pause_until"] == FOMC + 30 * MIN and "FOMC" in c["now"]["pause_ko"]
    # the same window the paper bot uses: events.near(ts, w, w), both edges included
    for ts in (FOMC - 30 * MIN, FOMC + 30 * MIN, FOMC - 31 * MIN, FOMC + 31 * MIN):
        assert (L.calendar(world, ts)["now"]["macro"] is not None) == bool(events.near(ts, 30 * MIN, 30 * MIN)), ts
    free = L.calendar(world, FOMC + 2 * H)
    assert not free["now"]["paused"] and free["now"]["next"]["why"] == "weekend"
    assert [x["when"] for x in free["items"]] == ["past", "later"]           # the CPI of 1/13 is past 21 days
    assert free["events"]["low"] is False and free["events"]["state"] == "ok"
    late = L.calendar(world, events.parse_ts("2026-12-10T00:00:00Z"))       # 34 days of dates left: next year's are due
    assert late["events"]["low"] is True and late["events"]["last_ms"] == events.parse_ts("2027-01-13T13:30:00Z")


def test_calendar_on_the_weekend_and_its_spans(world, macro):
    macro(("2026-10-28T18:00:00Z", "FOMC"))
    c = L.calendar(world, SAT_NOON_KST)
    assert c["now"]["weekend"] and c["now"]["paused"] and c["now"]["pause_until"] == MON_KST
    assert c["now"]["pause_ko"].startswith("주말")
    spans = c["spans"]
    assert spans[0] == {"from": MON_KST - 2 * DAY, "to": MON_KST, "why": "weekend", "ko": "주말(토·일, 한국 시간)"}
    assert any(s["why"] == "macro" and s["from"] == FOMC - 30 * MIN for s in spans)
    assert [s["from"] for s in spans] == sorted(s["from"] for s in spans)
    assert c["now"]["next"]["why"] == "macro"                                 # the next start after now


def test_calendar_without_a_release_file_says_so(world, macro, monkeypatch, tmp_path):
    monkeypatch.setattr(events, "PATH", tmp_path / "none.csv")
    events.reset()
    c = L.calendar(world, NOW)
    assert c["items"] == [] and c["events"]["low"] is True and c["events"]["last_ms"] is None


# ---------------------------------------------------------------- 지도
def _brute_q(n, p, q):
    c = 0.0
    for k in range(n + 1):
        c += math.comb(n, k) * p ** k * (1 - p) ** (n - k)
        if c >= q - 1e-12:
            return k
    return n


def test_binomial_bands_are_exact():
    for n in (1, 2, 7, 20, 40, 63):
        for p in (0.7497, 0.9132):
            assert L.binom_quantiles(n, p) == [_brute_q(n, p, q) for q in L.BAND_QS], (n, p)
            for k in (0, n // 2, n - 1):
                brute = sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k + 1))
                assert math.isclose(L.binom_cdf(n, k, p), brute, rel_tol=1e-9, abs_tol=1e-15)
    assert L.binom_cdf(10, -1, 0.5) == 0.0 and L.binom_cdf(10, 10, 0.5) == 1.0
    ns = L.band_ns(2000)
    assert len(ns) <= L.BAND_POINTS + 1 and ns[:60] == list(range(1, 61)) and ns[-1] == 2000 and ns == sorted(set(ns))
    assert L.band_ns(40) == list(range(1, 41))


def test_map_draws_the_wins_so_far_against_the_bands(rich):
    m = L.map_view(rich, NOW)
    b = m["band"]
    assert (b["fit"], b["honest"], b["break_even"]) == (0.9132, 0.7497, 0.776)
    paper = b["accounts"]["paper"]
    assert paper["n"] == 48 and paper["points"][-1][:2] == [paper["n"], paper["wins"]]
    assert b["n_max"] == 48 + L.BAND_AHEAD and len(b["honest_band"]) == len(b["ns"]) == len(b["fit_band"])
    assert math.isclose(paper["p_honest"], L.binom_cdf(48, paper["wins"], 0.7497))
    assert set(b["accounts"]) == {"paper", "bybit", "mexc"}
    coin = {r["key"]: r for r in m["cuts"]["coin"]}
    assert list(coin)[:6] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]
    assert coin["BTCUSDT"]["bt_n"] == 1250 and coin["ETHUSDT"]["n"] == 15 and coin["BTCUSDT"]["label"] == "BTC"
    assert [r["label"] for r in m["cuts"]["reg5"][:5]] == ["강상승", "약상승", "강하락", "약하락", "횡보"]
    hb = {r["key"]: r for r in m["cuts"]["hb"]}
    assert hb["1"]["label"] == "04~08시" and hb["1"]["n"] is None and hb["1"]["bt_n"] == 816   # no live trade there yet


def test_map_before_any_trade_still_draws_the_bands(tmp_path):
    p = W.build_world(str(tmp_path / "w"))
    os.remove(p["paper"])
    m = L.map_view(p, NOW)
    assert m["paper"]["state"] == "missing" and m["band"]["n_max"] == L.BAND_MIN_N and "paper" not in m["band"]["accounts"]


# ---------------------------------------------------------------- 비용 · 지금
def test_costs_follow_the_trades_tab(world):
    co = L.costs(world, NOW)
    b, m = co["accts"]["bybit"], co["accts"]["mexc"]
    assert b["state"] == "ok" and (b["n"], b["matched"]) == (5, 3) and m["n"] == 3 and m["matched"] == 3
    tr = L.trade_rows(world, NOW)["accts"]["bybit"]["rows"]
    assert math.isclose(b["diff_total"], sum(r["diff"] for r in tr if r.get("diff") is not None))
    assert math.isclose(b["fees"], sum(r["commission"] for r in tr if r.get("commission") is not None))
    assert {x["kind"] for x in b["missed"]} == {"halted", "none"} and {x["kind"] for x in m["missed"]} == {"entry_check", "late"}
    assert sum(x["n"] for x in b["missed"]) == 2                            # t4 (halted) and t5 (no record); t1 was before the start


def test_costs_say_an_unreadable_executor(world):
    os.remove(world["mexc_db"])
    co = L.costs(world, NOW)
    assert co["accts"]["mexc"]["state"] == "missing" and co["accts"]["bybit"]["state"] == "ok"


def test_whynow_lists_what_stands_before_the_next_entry(world, macro):
    macro(("2026-10-28T18:00:00Z", "FOMC"))
    w = L.whynow(world, NOW)
    ids = [i["id"] for i in w["items"]]
    assert ids[:4] == ["weekend", "macro", "paper", "position"] and ids.count("exec") == 2 and ids.count("light") == 2
    pos = next(i for i in w["items"] if i["id"] == "position")
    assert pos["ok"] is False and pos["detail"]["symbol"] == "BTCUSDT" and not w["ready"]
    assert w["head_ko"].startswith("지금은 새 진입 안 해요") and "포지션" in w["head_ko"]
    halt = [i for i in w["items"] if i["id"] == "halt"]
    assert [i["ok"] for i in halt] == [True, False] and halt[1]["who"] == "mexc"     # mexc halted at T0+8h
    assert w["last_signal"]["stage"] == "waiting" and w["last_signal"]["symbol"] == "BCHUSDT"
    wk = L.whynow(world, SAT_NOON_KST)
    assert wk["items"][0]["ok"] is False and "주말" in wk["head_ko"]


def test_whynow_is_ready_when_nothing_stands_in_the_way(tmp_path, macro):
    macro(("2026-10-28T18:00:00Z", "FOMC"))
    p = W.build_world(str(tmp_path / "w"))
    W.paper_db(p["paper"] + ".2", with_position=False, extra_wins=[True] * 20)
    os.replace(p["paper"] + ".2", p["paper"])
    for k in ("bybit_db", "mexc_db"):
        os.remove(p[k])
    w = L.whynow(p, NOW)
    blocked = [i["ko"] for i in w["items"] if i["ok"] is False]
    assert blocked == ["바이비트 실행기 기록을 못 읽음", "MEXC 실행기 기록을 못 읽음"] and not w["ready"]


# ---------------------------------------------------------------- routes
@pytest.fixture
def client(tmp_path, world, monkeypatch):
    for k, v in W.env_of(world).items():
        monkeypatch.setenv(k, v)
    base = tmp_path / "data"
    base.mkdir()
    dbp = str(base / "paper3.db")
    _store(dbp).close()
    app = create_app(dbp, hash_password(PW), SECRET, candles=lambda s, i, n: [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}])
    return TestClient(app)


def test_the_new_routes_are_behind_the_login_and_answer(client):
    paths = ("/api/v4/livebots/rank", "/api/v4/livebots/calendar", "/api/v4/livebots/map", "/api/v4/livebots/costs", "/api/v4/livebots/now")
    for path in paths:
        assert client.get(path, follow_redirects=False).status_code in (401, 302, 307), path
    assert client.post("/api/login", json={"password": PW}).status_code == 200
    got = {path: client.get(path) for path in paths}
    assert all(r.status_code == 200 for r in got.values()), {k: r.status_code for k, r in got.items()}
    assert got["/api/v4/livebots/rank"].json()["n_settings"] == 3
    assert got["/api/v4/livebots/now"].json()["ready"] is False
    assert set(got["/api/v4/livebots/costs"].json()["accts"]) == {"bybit", "mexc"}
