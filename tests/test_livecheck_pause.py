"""⏸ 진입 쉼 시작 · 🔔 끝 (owners 10/19): the paper bot's own entry pauses (the KST weekend with no_weekend, ±
macro_blackout_min around each US macro release in data/macro_events.csv) told by the watcher (paperbot/livecheck.py
pause_spans, pause_pass): one quiet message when a pause starts and one when it ends, overlapping or touching pauses as
one, only within 10 minutes after the moment, once each, the open-position line only with a position, the next pause
within 24 hours on the end message, off with PAPERBOT_LIVE_PAUSE_MSGS=0. Release files are hand-made; no network."""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot import events  # noqa: E402
from paperbot import livecheck as LC  # noqa: E402
from paperbot.notify import INFO, ListNotifier, silent, telegram_text  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

T0, DAY, H, MIN = W.T0, W.DAY, W.H, W.MIN               # T0: Monday 10/19 09:00 KST
CPI = T0 + 3 * DAY + 12 * H + 30 * MIN                   # Thursday 10/22 21:30 KST
NFP = T0 + 4 * DAY + 12 * H + 30 * MIN                   # Friday 10/23 21:30 KST
LATE = T0 + 4 * DAY + 14 * H + 45 * MIN                  # Friday 10/23 23:45 KST: its pause runs into the weekend
SAT = T0 + 4 * DAY + 15 * H                              # Saturday 10/24 00:00 KST
MON = SAT + 2 * DAY                                      # Monday 10/26 00:00 KST
PCE = T0 + 7 * DAY + 12 * H + 30 * MIN                   # Monday 10/26 21:30 KST
CFG = W.CONFIG                                           # deploy/combo.live-ac.json's rules: no_weekend, 30 minutes
POS = "열린 포지션은 손절·잠금 그대로 관리돼요"
NO_TG = {"base": None, "over": None, "over_exists": False, "over_mtime": None}     # never the server's env files


@pytest.fixture
def releases(tmp_path, monkeypatch):
    """releases(*[(ms, kind)]): the macro calendar paperbot/events.py reads (an empty one by default)."""
    def put(*evs):
        f = tmp_path / "macro.csv"
        f.write_text("ts_utc,kind,source_url\n" + "".join(
            f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ms / 1000))},{kind},https://www.bls.gov/x\n" for ms, kind in evs),
            encoding="utf-8")
        monkeypatch.setattr(events, "PATH", f)
        events.reset()
    put()
    monkeypatch.delenv(LC.PAUSE_MSGS_ENV, raising=False)
    monkeypatch.delenv(LC.WAIT_MSGS_ENV, raising=False)
    yield put
    events.reset()


def src_of(tmp_path, position: bool = True, config: dict = None, name: str = "w") -> LC.Sources:
    """The paper bot's database (its position, its own config record: combo_run, none when ``config`` is None) and an
    empty livecheck.db."""
    d = tmp_path / name
    d.mkdir()
    paper = W.paper_db(str(d / "live-ac.db"), with_position=position)
    s = Store3(paper)
    if config is None:
        s.conn.execute("DELETE FROM state WHERE k = 'combo_run'")
    else:
        s.put_state("combo_run", T0, {"config": config})
    s.commit()
    s.conn.close()
    return LC.Sources(db=str(d / "livecheck.db"), paper_db=paper, rule_db=str(d / "paper3.db"), combo_config="-")


def run(src, now, send=None):
    conn = LC.open_out(src.db)
    note = ListNotifier()
    try:
        out = LC.pause_pass(src, conn, now, send or note.send)
    finally:
        conn.close()
    assert all(lv == INFO for _k, _key, lv, _t in out)
    return out


def texts(out):
    return [t for _k, _key, _lv, t in out]


def test_spans_overlapping_or_touching_are_one(releases):
    releases((CPI, "CPI"), (CPI + 45 * MIN, "PCE"), (CPI + 105 * MIN, "NFP"), (LATE, "FOMC"), (PCE, "PCE"))
    got = LC.pause_spans(CFG, CPI - 2 * H, MON + DAY)
    assert [(s["from"], s["to"], s["weekend"], [e.kind for e in s["macro"]]) for s in got] == [
        (CPI - 30 * MIN, CPI + 135 * MIN, False, ["CPI", "PCE", "NFP"]),   # 21:00-22:00 + 21:45-22:45 + 22:45-23:45 (touching)
        (LATE - 30 * MIN, MON, True, ["FOMC"]),                           # Friday 23:15 into the weekend
        (PCE - 30 * MIN, PCE + 30 * MIN, False, ["PCE"])]
    assert got[1]["parts"][0].kind == "FOMC" and got[1]["parts"][1] == "weekend"          # in time order
    assert LC.pause_what(got[0], 30, CPI) == "CPI 발표 21:30 · PCE 발표 22:15 · NFP 발표 23:15 앞뒤 30분"
    assert LC.pause_what(got[1], 30, LATE) == "FOMC 발표 23:45 앞뒤 30분 + 주말"
    assert LC.pause_what(got[1], 30, LATE, times=False) == "FOMC 발표 앞뒤 30분 + 주말"
    # the rules come from the config: no weekend rule, no macro window, no config at all
    assert [(s["from"], s["to"]) for s in LC.pause_spans({**CFG, "no_weekend": False}, LATE - H, MON)] == \
        [(LATE - 30 * MIN, LATE + 30 * MIN)]
    assert [(s["from"], s["to"]) for s in LC.pause_spans({**CFG, "macro_blackout_min": None}, CPI - H, MON + DAY)] == [(SAT, MON)]
    assert LC.pause_spans(None, CPI - H, MON) == [] and LC.pause_spans({}, CPI - H, MON) == []
    # a weekend already running at the window's start is the whole weekend
    assert [(s["from"], s["to"]) for s in LC.pause_spans({"no_weekend": True}, MON - 5 * MIN, MON)] == [(SAT, MON)]


def test_a_macro_pause_starts_and_ends_once_each(tmp_path, releases):
    releases((CPI, "CPI"), (NFP, "NFP"))
    src = src_of(tmp_path, config=CFG)                                   # the paper account holds a position
    start = run(src, CPI - 28 * MIN)
    assert start == [("pause", str(CPI - 30 * MIN), INFO,
                      "⏸ 진입 쉼 시작 · CPI 발표 21:30 앞뒤 30분\n22:00까지 새 진입 없음 (열린 포지션은 손절·잠금 그대로 관리돼요)")]
    assert run(src, CPI - 27 * MIN) == [] and run(src, CPI) == []      # once; nothing in the middle
    end = run(src, CPI + 31 * MIN)
    assert end == [("resume", str(CPI + 30 * MIN), INFO,
                    "🔔 진입 쉼 끝 · 다시 진입할 수 있어요\n다음 쉼: 금 21:00~22:00 (NFP 발표 앞뒤 30분)")]
    assert run(src, CPI + 32 * MIN) == []
    lv, body = telegram_text(INFO, end[0][3])
    assert body == end[0][3] and silent(lv, "critical")                 # quiet in the live chats


def test_without_a_position_and_without_a_next_pause(tmp_path, releases):
    releases((CPI, "CPI"))
    src = src_of(tmp_path, position=False, config=CFG)
    assert texts(run(src, CPI - 30 * MIN)) == ["⏸ 진입 쉼 시작 · CPI 발표 21:30 앞뒤 30분\n22:00까지 새 진입 없음"]
    assert texts(run(src, CPI + 30 * MIN)) == ["🔔 진입 쉼 끝 · 다시 진입할 수 있어요"]     # the weekend is 26 hours away


def test_the_weekend_starts_and_ends(tmp_path, releases):
    releases((PCE, "PCE"))
    src = src_of(tmp_path, config=CFG)
    assert run(src, SAT + MIN) == [("pause", str(SAT), INFO, f"⏸ 주말 진입 쉼 시작 · 월 00:00까지\n{POS}")]
    assert run(src, SAT + DAY) == []
    assert run(src, MON + 2 * MIN) == [("resume", str(MON), INFO,
                                        "🔔 진입 쉼 끝 · 다시 진입할 수 있어요\n다음 쉼: 21:00~22:00 (PCE 발표 앞뒤 30분)")]
    flat = src_of(tmp_path, position=False, config=CFG, name="flat")
    assert texts(run(flat, SAT)) == ["⏸ 주말 진입 쉼 시작 · 월 00:00까지"]
    # Friday's resume names the weekend as the next pause
    assert texts(run(flat, NFP + 30 * MIN)) == []                                      # no release in this calendar
    releases((NFP, "NFP"))
    assert texts(run(flat, NFP + 30 * MIN)) == ["🔔 진입 쉼 끝 · 다시 진입할 수 있어요\n다음 쉼: 토 00:00~월 00:00 (주말)"]
    # no weekend rule in the paper bot's config: no weekend message
    off = src_of(tmp_path, config={**CFG, "no_weekend": False}, name="off")
    assert run(off, SAT + MIN) == [] and run(off, MON + MIN) == []


def test_a_friday_night_release_running_into_the_weekend_is_one_pause(tmp_path, releases):
    releases((LATE, "FOMC"))
    src = src_of(tmp_path, config=CFG)
    assert texts(run(src, LATE - 30 * MIN)) == [
        f"⏸ 진입 쉼 시작 · FOMC 발표 23:45 앞뒤 30분 + 주말\n월 00:00까지 새 진입 없음 ({POS})"]
    assert run(src, SAT) == [] and run(src, SAT + 15 * MIN) == []      # no weekend start, no end of the release's 00:15
    assert texts(run(src, MON)) == ["🔔 진입 쉼 끝 · 다시 진입할 수 있어요"]


def test_only_within_ten_minutes_after_the_moment(tmp_path, releases):
    releases((CPI, "CPI"))
    src = src_of(tmp_path, config=CFG)
    assert run(src, CPI - 30 * MIN - MIN) == []                         # before it
    assert len(run(src, CPI - 20 * MIN)) == 1                           # 10 minutes after: still told
    late = src_of(tmp_path, config=CFG, name="late")                    # the watcher was down at the start
    assert run(late, CPI - 19 * MIN) == []
    conn = LC.open_out(late.db)
    assert conn.execute("SELECT COUNT(*) FROM trade_msgs").fetchone() == (0,)       # nothing recorded either
    conn.close()
    assert texts(run(late, CPI + 40 * MIN)) == ["🔔 진입 쉼 끝 · 다시 진입할 수 있어요"]
    assert run(late, CPI + 41 * MIN + 10 * MIN) == []
    # a short pause the watcher missed the start of: only its end, never a start already over
    short = src_of(tmp_path, config={**CFG, "macro_blackout_min": 2}, name="short")
    assert texts(run(short, CPI + 3 * MIN)) == ["🔔 진입 쉼 끝 · 다시 진입할 수 있어요"]


def test_a_failed_send_is_tried_again_and_the_switch(tmp_path, releases, monkeypatch):
    releases((CPI, "CPI"))
    src = src_of(tmp_path, config=CFG)
    assert run(src, CPI - 29 * MIN, send=lambda lv, tx: False) == []
    assert len(run(src, CPI - 28 * MIN)) == 1
    monkeypatch.setenv(LC.PAUSE_MSGS_ENV, "0")
    assert run(src, CPI + 30 * MIN) == []
    monkeypatch.delenv(LC.PAUSE_MSGS_ENV)
    assert len(run(src, CPI + 31 * MIN)) == 1
    # the paper bot's config unknown (no record, no file): its rules are not guessed
    unknown = src_of(tmp_path, name="unknown")
    assert run(unknown, SAT) == [] and run(unknown, CPI - 30 * MIN) == []


def test_the_watcher_sends_them(tmp_path, releases):
    releases((CPI, "CPI"))
    p = W.build_world(str(tmp_path / "w"))
    src = LC.Sources(db=str(tmp_path / "w" / "livecheck.db"), paper_db=p["paper"], rule_db=str(tmp_path / "w" / "paper3.db"),
                     combo_config="-", executors=W.exec_infos(p))
    n = ListNotifier()
    kw = dict(notifier=n, units=lambda unit: ("active", "enabled"), exists=lambda path: False, tg=NO_TG)
    out = LC.run_watch(src, now_ms=SAT + MIN, **kw)
    assert [x for x in out if x[0] in ("pause", "resume")] == [("pause", str(SAT), INFO, f"⏸ 주말 진입 쉼 시작 · 월 00:00까지\n{POS}")]
    assert (INFO, f"⏸ 주말 진입 쉼 시작 · 월 00:00까지\n{POS}") in n.messages
    assert not [x for x in LC.run_watch(src, now_ms=SAT + 2 * MIN, **kw) if x[0] in ("pause", "resume")]
    dry = LC.run_watch(src, now_ms=MON + MIN, dry_run=True, tg=NO_TG, units=kw["units"], exists=kw["exists"])
    assert [x[0] for x in dry if x[0] in ("pause", "resume")] == ["resume"]
    out = LC.run_watch(src, now_ms=MON + MIN, **kw)                     # the dry run recorded nothing
    assert [x[0] for x in out if x[0] in ("pause", "resume")] == ["resume"]
