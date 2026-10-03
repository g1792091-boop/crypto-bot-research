"""events.py (macro release calendar) and the cards tag "경제지표 발표 전후".

The event dates below are test fixtures chosen to sit on both sides of a US daylight-saving
change; they are not claimed to be real release dates."""

import pytest

from paperbot import cards, events
from paperbot.cards import MACRO_AFTER_MS, MACRO_BEFORE_MS, MACRO_TAG, TAGS, card, tag_stats

RT = 0.0014
MIN = 60_000
URL = "https://www.bls.gov/schedule/news_release/cpi.htm"
FED = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

# 2026: DST ends Sun 1 Nov; 2027: DST starts Sun 14 Mar.
EDT_CPI = events.et_to_utc("2026-10-30", kind="CPI")      # Friday before the change: UTC-4
EST_CPI = events.et_to_utc("2026-11-06", kind="CPI")      # Friday after the change: UTC-5
EST_FOMC = events.et_to_utc("2027-03-10", kind="FOMC")    # Wednesday before the spring change: UTC-5
EDT_FOMC = events.et_to_utc("2027-03-17", kind="FOMC")    # Wednesday after it: UTC-4


@pytest.fixture
def calendar(tmp_path, monkeypatch):
    def use(text):
        p = tmp_path / "macro_events.csv"
        if text is not None:
            p.write_text(text, encoding="utf-8")
        monkeypatch.setattr(events, "PATH", p)
        events.reset()
        return p
    yield use
    events.reset()


def csv_text(*rows):
    return "ts_utc,kind,source_url\n" + "".join(f"{ts},{k},{u}\n" for ts, k, u in rows)


def trade(entry, exit_, **over):
    t = {"strategy_id": "N17_KC_RSI", "symbol": "BTCUSDT", "timeframe": "15m", "side": 1, "signal_ts": entry - 1,
         "entry_time": entry, "entry_price": 100.0, "exit_time": exit_, "exit_price": 99.2,
         "exit_reason": "SL", "leverage": 40, "roe": -0.38, "pnl": -38.0, "mfe_price": 100.1, "mae_price": 99.2,
         "context": {}}
    t.update(over)
    return t


def test_et_to_utc_follows_daylight_saving():
    assert EDT_CPI == "2026-10-30T12:30:00Z" and EST_CPI == "2026-11-06T13:30:00Z"
    assert EST_FOMC == "2027-03-10T19:00:00Z" and EDT_FOMC == "2027-03-17T18:00:00Z"
    assert events.et_to_utc("2026-07-14", "08:30") == "2026-07-14T12:30:00Z"
    assert events.main(["line", "nfp", "2026-12-04", URL]) == 0


def test_parse_reads_lines_and_reports_bad_ones():
    text = ("# comment line\n\n" + csv_text(
        (EST_CPI, "CPI", URL),
        ("2026-10-30T08:30:00-04:00", "cpi", URL),       # offset form, lower-case kind
        (EDT_FOMC, "FOMC", FED),
        ("2026-11-06T13:30:00Z", "CPI", URL),            # duplicate of the first
        ("2026-13-01T00:00:00Z", "NFP", URL),            # bad date
        ("2026-12-04T13:30:00Z", "GDP", URL),            # unknown kind
        ("2026-12-04T13:30:00Z", "NFP", ""),             # no source
    ) + "2026-12-04T13:30:00Z,NFP\n")
    evs, probs = events.parse(text)
    assert [(e.ts_utc, e.kind) for e in evs] == [(EDT_CPI, "CPI"), (EST_CPI, "CPI"), (EDT_FOMC, "FOMC")]
    assert evs[0].source_url == URL and evs[0].as_dict()["name_ko"] == "소비자물가(CPI)"
    assert len(probs) == 5 and all(p.startswith("line ") for p in probs)
    assert "duplicate" in probs[0] and "bad ts_utc" in probs[1] and "GDP" in probs[2]
    assert events.parse("time,kind,url\n2026-11-06T13:30:00Z,CPI,x\n")[0] == []
    assert events.parse("") == ([], [])
    assert events.parse("ts_utc,kind,source_url\n") == ([], [])


def test_near_includes_both_edges(calendar):
    calendar(csv_text((EST_CPI, "CPI", URL), (EDT_FOMC, "FOMC", FED)))
    t = events.parse_ts(EST_CPI)
    assert [e.kind for e in events.near(t - 30 * MIN, 30 * MIN, 120 * MIN)] == ["CPI"]
    assert events.near(t - 30 * MIN - 1, 30 * MIN, 120 * MIN) == []
    assert [e.kind for e in events.near(t + 120 * MIN, 30 * MIN, 120 * MIN)] == ["CPI"]
    assert events.near(t + 120 * MIN + 1, 30 * MIN, 120 * MIN) == []
    assert len(events.all_events()) == 2 and events.problems() == []


def test_missing_csv_means_no_events_and_no_tag(calendar):
    calendar(None)
    assert events.all_events() == [] and events.near(0, 10**15, 10**15) == []
    t = events.parse_ts(EST_CPI)
    c = card("N17_KC_RSI@15m", trade(t, t + 15 * MIN), RT)
    assert c["macro"] == [] and MACRO_TAG not in c["tags"]


def test_shipped_csv_parses_cleanly():
    events.reset()
    try:
        assert events.PATH.exists() and events.problems() == []
    finally:
        events.reset()


@pytest.mark.parametrize("release", [EDT_CPI, EST_CPI, EST_FOMC, EDT_FOMC])
def test_tag_on_and_off_at_window_edges(calendar, release):
    calendar(csv_text((EDT_CPI, "CPI", URL), (EST_CPI, "CPI", URL), (EST_FOMC, "FOMC", FED),
                      (EDT_FOMC, "FOMC", FED)))
    t = events.parse_ts(release)
    far = 3 * 24 * 60 * MIN

    def tagged(entry, exit_):
        return MACRO_TAG in card("A@15m", trade(entry, exit_), RT)["tags"]

    # entry at the edges (exit far away afterwards)
    assert tagged(t - MACRO_BEFORE_MS, t + far)
    assert not tagged(t - MACRO_BEFORE_MS - 1, t + far)
    assert tagged(t + MACRO_AFTER_MS, t + far)
    assert not tagged(t + MACRO_AFTER_MS + 1, t + far)
    # exit at the edges (entry far away before)
    assert tagged(t - far, t - MACRO_BEFORE_MS)
    assert not tagged(t - far, t - MACRO_BEFORE_MS - 1)
    assert tagged(t - far, t + MACRO_AFTER_MS)
    assert not tagged(t - far, t + MACRO_AFTER_MS + 1)


def test_card_macro_data_and_tag_order(calendar):
    calendar(csv_text((EST_CPI, "CPI", URL), (EDT_FOMC, "FOMC", FED)))
    t = events.parse_ts(EST_CPI)
    c = card("A@15m", trade(t - 10 * MIN, t + 20 * MIN, context={"regime": "chop"}), RT)
    assert c["macro"] == [{"kind": "CPI", "name_ko": "소비자물가(CPI)", "ts_utc": EST_CPI, "ts_ms": t,
                           "source_url": URL, "entry": True, "exit": True}]
    assert c["tags"][-1] == MACRO_TAG and c["tags"].index("횡보장 진입") < c["tags"].index(MACRO_TAG)
    only_exit = card("A@15m", trade(t - 5 * 60 * MIN, t + 5 * MIN), RT)["macro"]
    assert [(m["entry"], m["exit"]) for m in only_exit] == [(False, True)]
    # the tag is the last one and the existing tags keep their order
    names = [n for n, _ in TAGS]
    assert names[-1] == MACRO_TAG and names[:13] == [
        "강제청산", "수익 났다가 손절", "진입 직후 바로 손절", "추세 반대 진입", "상위 봉 추세 반대", "횡보장 진입",
        "추세 약함 (ADX 20 미만)", "DI 방향 반대", "많이 오른/내린 뒤 추격", "최근 범위 끝에서 진입",
        "저항 바로 앞 진입", "지지선 뒤 손절", "돌파 진입"]
    st = {r["tag"]: r for r in tag_stats([card("A@15m", trade(t, t + MIN), RT)])}
    assert st[MACRO_TAG]["losses"] == 1 and "30분 전부터 2시간 후" in st[MACRO_TAG]["note"]
    assert cards.MACRO_BEFORE_MS == 30 * MIN and cards.MACRO_AFTER_MS == 120 * MIN


def test_two_releases_close_together(calendar):
    nfp = events.et_to_utc("2027-01-08", kind="NFP")
    calendar(csv_text((nfp, "NFP", URL), (events.et_to_utc("2027-01-08", "10:00"), "PCE", URL)))
    t = events.parse_ts(nfp)
    c = card("A@15m", trade(t, t + 100 * MIN), RT)
    assert [m["kind"] for m in c["macro"]] == ["NFP", "PCE"] and c["tags"].count(MACRO_TAG) == 1


def test_a_calendar_filled_later_is_read_without_a_restart(calendar, monkeypatch):
    """2026-10-03: the file is read again when it changes (no restart of the dashboard or the agents)."""
    p = calendar("ts_utc,kind,source_url\n")
    assert events.all_events() == []
    monkeypatch.setattr(events, "RECHECK_S", 0.0)
    import os
    p.write_text(csv_text((EDT_CPI, "CPI", URL), (EST_FOMC, "FOMC", FED)), encoding="utf-8")
    os.utime(p, ns=(os.stat(p).st_mtime_ns + 10**9,) * 2)
    assert [e.kind for e in events.all_events()] == ["CPI", "FOMC"]
    t = events.parse_ts(EDT_CPI)
    up = events.upcoming(t - 3_600_000, days=200)
    assert [u["kind"] for u in up] == ["CPI", "FOMC"] and up[0]["hours_left"] == 1.0
    assert events.upcoming(t + 1, days=1) == []                 # past it, and the FOMC is months away
    # within RECHECK_S the stat is not repeated
    monkeypatch.setattr(events, "RECHECK_S", 3600.0)
    p.write_text("ts_utc,kind,source_url\n", encoding="utf-8")
    os.utime(p, ns=(os.stat(p).st_mtime_ns + 2 * 10**9,) * 2)
    assert len(events.all_events()) == 2
