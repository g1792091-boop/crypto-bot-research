"""The live Telegram messages and checks with a second, DIFFERENT paper bot (owners 10-23, docs/vwap-bot-ko.md): the
추세판단 봇 and 'VWAP 개선판' itself (tests/vwap_world.py: the real VWAP bot on deploy/combo.vwap.json). One executor follows
the VWAP bot from its switch, the other stays on the trend bot; before that the VWAP bot runs paper-only.

1 names · 2 the hold-limit exit's words · 3 two bots' entries of one minute never merge · 4 each executor's light from its
own bot · 5 alarms · 6 the paper-only stage (no flood on the first pass) · 7 the VWAP entry's gates line · 8 the morning
check's VWAP part, executors counted on one bot each · 9 the pauses of both bots · 10 the preview · 12 못 탄 신호 of the
VWAP bot (column ``paper``, group ``gate``, its own config, the shared budget)."""
from __future__ import annotations

import json
import sqlite3

import pytest

from paperbot import livecheck as LC
from paperbot import livemissed as LM
from paperbot.notify import ListNotifier
from tests import vwap_world as VW

H, MIN, DAY, T0, NOW = VW.H, VW.MIN, VW.DAY, VW.T0, VW.NOW
V5 = VW.V5
UNITS = lambda unit: ("active", "enabled")            # noqa: E731  (every unit meant to run)
TREND_KEY = f"COMBO@mix|BTCUSDT|{V5}"
VWAP_KEY = f"COMBO@mix#vwap|BTCUSDT|{V5}"


@pytest.fixture
def world(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"))
    yield w
    w.close()


def _pass(w, now, **kw):
    conn = LC.open_out(w.src().db)
    sent = []
    try:
        got = LC.trade_pass(w.src(**kw), conn, now, None, lambda lv, tx: sent.append((lv, tx)) or True, units=UNITS)
    finally:
        conn.close()
    return got


def _watch(w, now, **kw):
    n = ListNotifier()
    out = LC.run_watch(w.src(**kw), now_ms=now, notifier=n, units=UNITS, exists=lambda p: False,
                       tg={"base": None, "over": None, "over_exists": False, "over_mtime": None})
    return out, n.messages


# ---------------------------------------------------------------- 1 · 3 · 7: names, separate entries, the gates line
def test_two_bots_entering_one_coin_in_one_minute_are_two_messages_each_with_its_own_executor(world):
    w = world
    got = _pass(w, V5 + 4 * MIN)
    entries = {key: text for kind, key, _lv, text in got if kind == "entry"}
    assert set(entries) == {TREND_KEY, VWAP_KEY}
    trend, vwap = entries[TREND_KEY], entries[VWAP_KEY]
    assert trend.startswith("🟢 진입 · BTC 롱 · 40배\nS2_ST_ROC 1시간")
    assert "\n추세판단 봇 62,000 · 손절" in trend and "MEXC     ✅ 62,012" in trend and "바이비트" not in trend
    lines = vwap.split("\n")
    assert lines[0] == "🟢 진입 · BTC 롱 · 30배" and lines[1] == "VWAP 복귀 실패 30분"
    assert lines[2] == "4시간 상승(상승 3·하락 0·중립 1) · 변동성 30분 ATR 0.45% (30일 80% 위치 0.62%)"
    assert lines[3].startswith("VWAP 개선판 67,") and "· 손절 " in lines[3] and "(-1.62%)" in lines[3]
    assert lines[4].startswith("바이비트 ✅ ") and "MEXC" not in vwap and "페이퍼만" not in vwap
    # the same rows again (the next pass, a restart of the watcher): nothing twice, the keys as they were
    assert [k for k, *_r in _pass(w, V5 + 5 * MIN) if k == "entry"] == []
    c = sqlite3.connect(w.src().db)
    keys = sorted(r[0] for r in c.execute("SELECT key FROM trade_msgs WHERE kind = 'entry'"))
    c.close()
    assert TREND_KEY in keys and VWAP_KEY in keys


def test_without_the_second_file_every_message_is_as_before(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"), follow=False)
    try:
        got = _pass(w, V5 + 4 * MIN, paper2_db=str(tmp_path / "no-vwap.db"))
        (text,) = [t for kind, _k, _lv, t in got if kind == "entry"]
        assert text.split("\n")[2].startswith("페이퍼   62,000") and "추세판단 봇" not in text
    finally:
        w.close()


def test_a_bots_name_on_its_lock_and_win_and_its_executors_light_from_its_own_trades(world):
    w = world
    _pass(w, V5 + 4 * MIN)                                   # the entries told
    vb = w.vb
    p0 = vb.price("BTCUSDT", vb.t)
    vb.move("BTCUSDT", vb.t + 20 * MIN, p0 * 1.007)
    vb.run_to(vb.t + 21 * MIN)
    pos = vb.engine().position
    held = w.held["bybit"]
    held["stop"] = round(held["entry_price"] * pos.stop_price / pos.entry_price, 6)      # Bybit's stop follows the lock
    w.advance(vb.t)
    lock = [t for kind, key, _lv, t in _pass(w, vb.t) if kind == "lock" and key == VWAP_KEY]
    assert len(lock) == 1 and lock[0].startswith("🔒 잠금 시작 · BTC 롱 · +10% 확보\nVWAP 개선판 · 바이비트 손절 ")
    w.hold_v5("win")
    w.advance(vb.t + 3 * MIN)
    got = _pass(w, vb.t)
    (win,) = [t for kind, key, _lv, t in got if kind == "exit"]
    lines = win.split("\n")
    assert lines[0].startswith("✅ 청산 · BTC 롱 · 순ROE +10.")
    assert lines[1].startswith("VWAP 개선판 · VWAP 복귀 실패 30분 · ") and "잠금 +10% 청산" in lines[1]
    assert lines[2].startswith("바이비트 +$") and "MEXC" not in win
    # Bybit's own light (N 4, 75 %) on the VWAP bot's last 4 trades: v2 lost, v3 won, v4 lost, v5 won = 50 %: red
    assert lines[3].endswith("· 신호등 바이비트 🔴")
    vt = LC.PaperSet(w.p["paper"]).trades(w.p["vwap"])
    assert LC.light_state(vt, 4, 0.75)["state"] == "red"


# ---------------------------------------------------------------- 2: the hold limit's words, the trend bot's stay
@pytest.mark.parametrize("drift,kind", [(1.0025, "exit"), (0.997, "card")])
def test_the_vwap_hold_limit_says_so_with_its_why(tmp_path, drift, kind):
    w = VW.VwapWorld(str(tmp_path / "w"))
    try:
        _pass(w, V5 + 4 * MIN)
        vb = w.vb
        p0 = vb.price("BTCUSDT", vb.t)
        vb.move("BTCUSDT", vb.t + 60 * MIN, p0 * drift)
        vb.run_to(V5 + 96 * 30 * MIN + 2 * MIN)
        w.settle("v5")
        rec = w.vtrades["v5"]
        assert rec.exit_reason == "TIME" and rec.exit_time == V5 + 48 * H and rec.context["exit_why"] == "96봉(48시간) 지남"
        w.advance(rec.exit_time + 5 * MIN)
        out, sent = _watch(w, rec.exit_time + 5 * MIN)
        text = next(t for _lv, t in sent if ("BTC 롱" in t and ("✅ 청산" in t or "❌ 청산" in t)))
        if kind == "exit":
            assert "VWAP 개선판 · VWAP 복귀 실패 30분 · 48.0시간 보유 · 보유 한도 청산(96봉(48시간) 지남)" in text
        else:
            assert "❌ 청산 · BTC 롱 · 순ROE -" in text and "VWAP 개선판 · VWAP 복귀 실패 30분 · 목록 1번 · 48.0시간 보유" in text
            assert "→ 보유 한도 청산(96봉(48시간) 지남) 18:00" in text and "이 봇의 5년 기준표가 없어요" in text
        assert "감독 청산" not in text
    finally:
        w.close()


def test_the_trend_bots_time_exit_keeps_its_words():
    trend = VW.deploy_config("combo.trend.json")
    vwap = VW.deploy_config("combo.vwap.json")
    t = {"reason": "TIME", "exit_why": "x", "strategy": "S3_CMO_SANDWICH"}
    assert LC.exit_reason_text(LC.with_bot([dict(t)], trend)[0]) == "감독 청산(시간 정리)"
    assert LC.exit_reason_text(LC.with_bot([dict(t)], vwap)[0]) == "보유 한도 청산(x)"
    assert LC.with_bot([dict(t)], trend)[0].keys() == t.keys()
    assert LC.with_bot([dict(t)], vwap)[0]["strategy_ko"] == "CMO·샌드위치 캔들"
    row = {"key": "vwap#x", "t": 1, "state": "closed", "reason": "TIME", "data": json.dumps({"time_ko": "보유 한도 청산"}),
           "taken": json.dumps({"reason": "TIME"}), "grp": "gate", "paper": "vwap"}
    out = LM.row_out(row)
    assert out["reason_ko"] == "보유 한도 청산" and out["taken"]["reason_ko"] == "보유 한도 청산" and out["paper"] == "vwap"
    assert LM.row_out({**row, "data": "{}", "paper": None})["reason_ko"] == "감독 청산(시간 정리)"


# ---------------------------------------------------------------- 6: paper-only first
def test_the_paper_only_stage_floods_nothing_old_then_tells_its_own_trades(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"), follow=False, until=VW.V4 + 45 * MIN)
    try:
        v4 = w.vtrades["v4"]
        assert v4.pnl < 0 and VW.V4 + 45 * MIN - v4.exit_time < LC.CARD_SEND_MS      # fresh enough to be sent...
        out, sent = _watch(w, VW.V4 + 45 * MIN)
        assert not [t for _lv, t in sent if "VWAP" in t]                                # ...but it was there before
        c = sqlite3.connect(w.src().db)
        card = c.execute("SELECT sent, data FROM loss_cards WHERE key = ?", (f"COMBO@mix#vwap|LTCUSDT|{VW.V4}",)).fetchone()
        seen = c.execute("SELECT v FROM live_state WHERE k = 'paper_seen:vwap'").fetchone()
        c.close()
        assert card is not None and card[0] is None and json.loads(card[1])["paper_only"] is True
        assert int(seen[0]) == VW.V4 + 45 * MIN
        # its next entry: told, marked paper-only, no executor line
        w.advance(V5 + 4 * MIN)
        out, sent = _watch(w, V5 + 4 * MIN)
        (vwap,) = [t for _lv, t in sent if t.startswith("🟢") and "VWAP 개선판" in t]
        assert vwap.endswith("\n" + LC.PAPER_ONLY_KO) and "바이비트" not in vwap and "MEXC" not in vwap
        (trend,) = [t for _lv, t in sent if t.startswith("🟢") and "추세판단 봇" in t]
        assert "MEXC     ✅" in trend and "바이비트 " in trend and LC.PAPER_ONLY_KO not in trend   # both follow the trend bot
        # its loss: a card that says so, quiet even as its second loss in a row (no money on it)
        w.hold_v5("loss")
        w.advance(w.vb.t + 4 * MIN)
        out, sent = _watch(w, w.vb.t)
        ((lv, card),) = [(lv, t) for lv, t in sent if "❌ 청산 · BTC 롱" in t]
        assert lv == LC.INFO and not card.startswith("🚨") and "지금 할 일" not in card
        assert f"\n{LC.PAPER_ONLY_KO}\n판정: 연속 손실 2번째" in card and "바이비트" not in card
    finally:
        w.close()


# ---------------------------------------------------------------- 5: alarms
def test_a_stalled_vwap_bot_names_its_own_unit(world):
    w = world
    w.stale_vwap(NOW - 30 * MIN)
    conds, judged, _s = LC.watch_conditions(w.src(), NOW, UNITS, exists=lambda p: False)
    c = next(x for x in conds if x.key == "paper2_stale:vwap")
    assert c.level == LC.CRITICAL and c.text.startswith("VWAP 개선판 페이퍼 봇이 10분 넘게 아무것도 쓰지 않습니다")
    assert "바이비트는 이 페이퍼를 따라가서" in c.text
    assert c.text.endswith("지금 할 일: sudo systemctl status paperbot-combo-vwap · sudo journalctl -u paperbot-combo-vwap -n 50")
    assert "paperbot-combo-mexc" not in c.text and "paper2_stale:" in judged


def test_a_stalled_paper_only_bot_is_a_quiet_note(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"), follow=False)
    try:
        w.stale_vwap(NOW - 30 * MIN)
        conds, judged, _s = LC.watch_conditions(w.src(), NOW, UNITS, exists=lambda p: False)
        c = next(x for x in conds if x.key == "paper2_quiet:vwap")
        assert c.level == LC.INFO and c.text.startswith("⚠ VWAP 개선판 페이퍼 봇이 10분 넘게")
        assert "아직 따라가는 실행기가 없어 돈과는 상관없어요" in c.text and "paperbot-combo-vwap" in c.text
        assert not [x for x in conds if x.key.startswith("paper2_stale")] and "paper2_quiet:" in judged
    finally:
        w.close()


def test_the_main_bots_alarm_and_a_halt_name_their_bot_when_two_run(world):
    w = world
    st = w.st["bybit"]
    st.put_state("bot", NOW + 15 * MIN, {"trade": None, "done": [], "loops": 1, "mode": "mainnet", "account": "COMBO@mix",
                                        "risk": {"halted": True, "halt_reason": "비상 정지 파일이 있습니다", "halt_kinds": ["kill"],
                                                 "halted_ts": NOW + 10 * MIN, "last_equity": 80.0}})
    st.commit()
    w.vb.run_to(NOW + 15 * MIN)
    conds, _j, _s = LC.watch_conditions(w.src(), NOW + 15 * MIN, UNITS, exists=lambda p: False)
    by = {x.key: x for x in conds}
    assert by["paper_stale"].text.startswith("추세판단 봇 페이퍼 봇이 10분 넘게 아무것도 쓰지 않습니다")
    assert by["paper_stale"].recover == "✅ 추세판단 봇 페이퍼 봇 기록이 다시 들어옵니다"
    halt = next(x for x in conds if x.key.startswith("halt:bybit:")).text
    assert "\n페이퍼(VWAP 개선판) 거래 4번(표본 작음)" in halt
    # one paper bot: the alarm as it always was
    conds, _j, _s = LC.watch_conditions(w.src(paper2_db=str(w.folder) + "/none.db", executors=[
        x for x in w.infos() if x.name == "mexc"]), NOW + 15 * MIN, UNITS, exists=lambda p: False)
    assert next(x for x in conds if x.key == "paper_stale").text.startswith("페이퍼 봇이 10분 넘게")


def test_the_unit_of_a_paper_bot_by_its_file():
    assert "sudo systemctl status paperbot-combo-vwap" in LC.paper_unit_todo("/var/lib/paperbot/combo/vwap.db")
    assert "sudo systemctl status paperbot-combo-mexc" in LC.paper_unit_todo("/var/lib/paperbot/combo/live15-mexc.db")
    other = LC.paper_unit_todo("/var/lib/paperbot/combo/other.db")
    assert "systemctl list-units 'paperbot-combo*'" in other and "other.db" in other
    assert LC.memory_lines([], ("paperbot-combo-vwap",))[1].endswith("paperbot-combo-mexc·paperbot-combo-vwap·실행기는 끄지 않기")
    assert "paperbot-combo-vwap" not in "\n".join(LC.memory_lines([]))


def test_did_not_follow_names_the_bot(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"), until=V5 + 5 * MIN, light=(4, 0.5), skip=("v5", "trend_open"))
    try:
        conds, _j, _s = LC.watch_conditions(w.src(), V5 + 5 * MIN, UNITS, exists=lambda p: False)
        by = {x.key: x for x in conds if x.key.startswith("follow:")}
        b = by[f"follow:bybit:{TREND_KEY}"].text
        m = by[f"follow:mexc:{TREND_KEY}"].text
        assert "\nVWAP 개선판 진입 18:00 BTC 롱 VWAP 복귀 실패 30분 (5분 지남)\n" in b
        assert "신호등 초록(최근 4번 2승 50%, 기준 50%)" in b
        assert "\n추세판단 봇 진입 18:00 BTC 롱 S2_ST_ROC 1시간 (5분 지남)\n" in m
    finally:
        w.close()


def test_start_and_light_messages_name_the_paper_bot(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"), until=VW.SWITCH - 10 * MIN)
    try:
        conn = LC.open_out(w.src().db)
        sent = []
        send = lambda lv, tx: sent.append(tx) or True     # noqa: E731
        try:
            assert LC.changes_pass(w.src(), conn, VW.SWITCH - 10 * MIN, None, send) == []      # the first look
            w.advance(VW.SWITCH + MIN)
            w.st["mexc"].event(VW.SWITCH + 30_000, "INFO", "start", "시작", {"paper_db": w.p["paper"]})
            w.st["mexc"].commit()
            LC.changes_pass(w.src(), conn, VW.SWITCH + MIN, None, send)
            assert ("▶️ 바이비트 실행기 켜짐 · 잔고 $101.60 · 신호등 근거 쌓는 중(3/4번, 그동안 모두 따라감) · "
                    "따라가는 페이퍼: VWAP 개선판") in sent
            assert "▶️ MEXC 실행기 켜짐 · 잔고 $102.40 · 따라가는 페이퍼: 추세판단 봇" in sent
            w.advance(VW.V4 + 45 * MIN)                     # v4 lost: Bybit's light (4 / 75 %) on the VWAP bot turns red
            sent.clear()
            LC.changes_pass(w.src(), conn, VW.V4 + 45 * MIN, None, send)
            assert sent == ["🚦 신호등 · 바이비트 ⚪→🔴 · VWAP 개선판 최근 4번 2승(50%) · 기준 75%\n"
                            + LC.LIGHT_WORD["red"]]
        finally:
            conn.close()
    finally:
        w.close()


# ---------------------------------------------------------------- 8: the morning check
@pytest.fixture
def morning(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"), until=T0 + DAY + 9 * MIN)
    conn = LC.open_out(w.src().db)
    try:
        LM.missed_pass(w.src(), conn, T0 + DAY + 9 * MIN)        # the watcher's last pass before the check
    finally:
        conn.close()
    r = LC.run_check(w.src(), day="2026-10-19", now_ms=T0 + DAY + 10 * MIN, no_replay=True, notifier=ListNotifier())
    yield w, r
    w.close()


def test_the_morning_check_has_the_vwap_bots_own_part(morning):
    w, r = morning
    text = r["text"]
    part = text[text.index("\nVWAP 개선판 (바이비트가 따라감)\n"):].split("\n\n")[0].strip().split("\n")
    v = w.vtrades
    roe = sum(v[k].roe for k in ("v1", "v2", "v3", "v4"))
    assert part[0] == "VWAP 개선판 (바이비트가 따라감)"
    assert part[1] == f"- 어제: 거래 4번 · 2승 2패 · 순ROE 합 {LC.fmt_roe(roe)}"
    assert part[2].startswith("- 시작부터: 거래 4번 · 2승(50%) · 손익 -$")
    be = abs(v["v2"].roe) / (v["v1"].roe + abs(v["v2"].roe))
    assert part[3] == (f"- 본전 승률 {be:.0%}(이 봇 거래 4번: 평균 이익 {LC.fmt_roe(v['v1'].roe)} · 평균 손실 "
                       f"{LC.fmt_roe(v['v2'].roe)}) · 아직 표본 적음 · 참고: 5년 기준 본전 승률 79%")
    assert part[4] == "- 늘리기 기준(두 분): 실거래 50번 승률 80% 이상이고 페이퍼와 비슷할 때 · 지금 실거래 바이비트 1번 0승(0%)"
    assert part[5].startswith("- 바이비트(VWAP 개선판 따라간 거래): 거래 1번 · 0승(0%) · 실현 -$")
    assert part[6] == "  그 밖에 추세판단 봇 따라간 거래 2번 · 2승 · 실현 +$1.60"
    assert part[7].startswith("  신호등 빨강(최근 4번 2승 50%, 기준 75%)")
    assert part[8] == "- 조건이 막은 신호(어제) 4개: 4시간 추세 반대 1 · 변동성 높음 1 · 주말·발표·나스닥 1 · 못 읽음 1"
    assert part[9].startswith("- VWAP 조건이 막은 신호 어제 3개(가상): 2승 1패")
    assert part[9].endswith("· 실제로 탄 거래 2승 2패 진행 1")
    assert "- 오늘 진입 쉬는 시간(두 봇 같음): " in text
    assert r["report"]["bots"][0]["path"] == w.p["vwap"] and r["report"]["bots"][0]["gates"]["vote"] == 1


def test_the_morning_score_lines_never_mix_the_two_bots(morning):
    w, r = morning
    score = r["text"][r["text"].index("성적표(시작부터)"):].split("\n\n")[0]
    assert "- 추세판단 봇(MEXC가 따라감): 거래 6번" in score
    assert "- MEXC: 거래 3번 · 3승(100%)" in score and "바이비트" not in score
    by = {x["name"]: x for x in r["report"]["executors"]}
    assert by["bybit"]["era"]["n"] == 1 and by["bybit"]["before"]["n"] == 2 and by["bybit"]["trades"] == 3
    assert "era" not in by["mexc"]


def test_the_paper_only_morning_part(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"), follow=False, until=T0 + DAY + 9 * MIN)
    try:
        r = LC.run_check(w.src(), day="2026-10-19", now_ms=T0 + DAY + 10 * MIN, no_replay=True, notifier=ListNotifier())
        text = r["text"]
        assert "- 추세판단 봇(바이비트·MEXC가 따라감): 거래 6번" in text and "- 바이비트: 거래 2번 · 2승(100%)" in text
        part = text[text.index("\nVWAP 개선판 (따라가는 실행기 없음)\n"):].strip().split("\n")
        assert part[4] == "- 늘리기 기준(두 분): 실거래 50번 승률 80% 이상이고 페이퍼와 비슷할 때 · 아직 따라가는 실행기 없음"
        assert part[5].startswith("- 조건이 막은 신호(어제) 4개") and not [ln for ln in part if "신호등" in ln]
    finally:
        w.close()


def test_the_monday_week_lines_split_each_executor_by_the_bot_it_followed(morning):
    w, r = morning
    src = w.src()
    w1 = T0 + DAY
    pc = LC.open_ro(src.paper_db)
    paper = LC.paper_report(pc, T0, w1)
    pc.close()
    ps = LC.PaperSet(src.paper_db, paper["trades"])
    segs = LC.exec_segs(src, src.executors)
    execs = [LC.exec_report(ex, paper["trades"], T0, w1, w1, ps=ps) for ex in src.executors]
    lines = LC.week_lines(None, "2026-10-19", w1, execs, paper, src.executors, {}, ps=ps, segs=segs,
                          bots=LC.bot_paths(src, segs))
    assert lines[1] == "- 추세판단 봇: 거래 6번 · 5승(83%) · 손익 +$5.00"
    assert lines[2].startswith("- VWAP 개선판: 거래 4번 · 2승(50%) · 손익 -$")
    assert lines[3].startswith("- 바이비트(추세판단 봇): 거래 2번 · 2승 · 실현 +$1.60")
    assert lines[4].startswith("- 바이비트(VWAP 개선판): 거래 1번 · 0승 · 실현 -$")
    assert lines[5].startswith("- MEXC(추세판단 봇): 거래 3번 · 3승 · 실현 +$2.40")
    one = LC.week_lines(None, "2026-10-19", w1, execs, paper, src.executors, {})         # one paper bot: as always
    assert one[1] == "- 페이퍼: 거래 6번 · 5승(83%) · 손익 +$5.00" and one[2].startswith("- 바이비트: 거래 3번")


def test_mexc_may_be_the_one_that_switches(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"), who="mexc", until=V5 + 4 * MIN)
    try:
        entries = {k: t for kind, k, _lv, t in _pass(w, V5 + 4 * MIN) if kind == "entry"}
        assert "MEXC     ✅" in entries[VWAP_KEY] and "바이비트" not in entries[VWAP_KEY]
        assert "바이비트 ✅" in entries[TREND_KEY] and "MEXC" not in entries[TREND_KEY]
    finally:
        w.close()


# ---------------------------------------------------------------- 9: the pauses
SAT = LC.window_of("2026-10-23")[0] + 15 * H                  # Saturday 10/24 00:00 KST


def _pause(w, now):
    conn = LC.open_out(w.src().db)
    try:
        return LC.pause_pass(w.src(), conn, now, lambda lv, tx: True)
    finally:
        conn.close()


def test_the_same_pause_of_both_bots_is_one_message(world):
    (msg,) = _pause(world, SAT + MIN)
    assert msg[0] == "pause" and msg[1] == str(SAT)
    assert msg[3] == "⏸ 주말 진입 쉼 시작 · 월 00:00까지\n열린 포지션은 손절·잠금 그대로 관리돼요\n적용: 추세판단 봇·VWAP 개선판 모두"


def test_different_pauses_are_told_for_each_bot(world):
    world.set_vwap_config(no_weekend=False)
    (msg,) = _pause(world, SAT + MIN)
    assert msg[1] == str(SAT) and msg[3].endswith("\n적용: 추세판단 봇만")
    world.set_vwap_config(no_weekend=True)
    trend = VW.deploy_config("combo.trend.json")
    VW._run(world.p["paper"], {**trend, "no_weekend": False}, T0)
    (msg,) = _pause(world, SAT + 2 * MIN)
    assert msg[1] == f"vwap#{SAT}" and msg[3].endswith("\n적용: VWAP 개선판만")


# ---------------------------------------------------------------- 10: the preview
def test_the_vwap_preview(monkeypatch):
    import urllib.request
    from paperbot import livepreview as PV

    def no_network(*a, **k):
        raise AssertionError("the preview must not reach the network")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    items = PV.scenes("vwap")
    texts = [t for _s, _lv, t in items]
    first = texts[0].split("\n")
    assert first[0] == "🟢 진입 · SOL 롱 · 30배" and first[1] == "VWAP 복귀 실패 30분" and first[-1] == LC.PAPER_ONLY_KO
    assert any(t.startswith("▶️ 바이비트 실행기 켜짐") and t.endswith("따라가는 페이퍼: VWAP 개선판") for t in texts)
    same = [t for t in texts if t.startswith("🟢 진입 · BTC 롱")]
    assert len(same) == 2 and "추세판단 봇 " in same[0] and "WOO X Pro ✅" in same[0] and "VWAP 개선판 " in same[1]
    assert any("보유 한도 청산(96봉(48시간) 지남)" in t for t in texts)
    assert any(t.startswith("❌ 청산 · ETH 롱") and "VWAP 개선판 · VWAP 복귀 실패 30분" in t for t in texts)
    morning = next(t for t in texts if "실거래 일일 점검" in t)
    assert "\nVWAP 개선판 (바이비트가 따라감)\n" in morning and "- 조건이 막은 신호(어제) 3개" in morning
    assert any("paperbot-combo-vwap" in t for t in texts)
    assert texts[-1].endswith("적용: 추세판단 봇·VWAP 개선판 모두")
    assert LC.main(["preview", "--vwap"]) == 0


# ---------------------------------------------------------------- 12: 못 탄 신호 of the VWAP bot
def test_the_vwap_bots_missed_signals_are_its_own_rows(world):
    w = world
    conn = LC.open_out(w.src().db)
    try:
        res = LM.missed_pass(w.src(), conn, NOW)
        assert not res.get("error") and res["vwap"]["new"] == 3
        main = LM.read_rows(conn, 0)
        rows = {r["why_kind"]: r for r in LM.read_rows(conn, 0, paper="vwap")}
    finally:
        conn.close()
    assert main and all(r["paper"] is None for r in main) and not [r for r in main if r["key"].startswith("vwap#")]
    assert set(rows) == {"gate_vote", "gate_vol", "gate_unread"}
    for kind, sym, side, won in (("gate_vote", "ETHUSDT", 1, True), ("gate_vol", "SOLUSDT", -1, False),
                                 ("gate_unread", "BCHUSDT", 1, True)):
        r = rows[kind]
        assert r["key"].startswith("vwap#") and r["paper"] == "vwap" and r["grp"] == "gate" and r["symbol"] == sym
        assert r["grp_ko"] == "VWAP 조건이 막음" and r["state"] == "closed" and r["win"] is won
        # simulated on the VWAP bot's own rules: 30x, its 2 ATR stop (the signal's ATR 0.8 % of the price)
        assert r["leverage"] == 30 and abs(abs(r["stop"] / r["entry_price"] - 1) - 0.016) < 0.0005
    assert rows["gate_vote"]["gates"]["vote"]["text"] == "4시간 하락(상승 0·하락 3·중립 1)"
    assert rows["gate_vol"]["gates"]["vol"]["text"] == "변동성 30분 ATR 0.51% (30일 80% 위치 0.43%)"
    assert rows["gate_vote"]["why_kind_ko"] == "4시간 추세 반대" and rows["gate_vol"]["reason"] == "SL"
    code, text = LM.show_text(w.src().db, w.p["vwap"], NOW, 7, 30, None, paper="vwap")
    assert code == 0 and "- VWAP 조건이 막음 3개" in text and "[VWAP 조건] ETH 롱 VWAP_FAIL" not in text
    assert "[VWAP 조건] ETH 롱 F6_VWAP_FAIL 30분 · 4시간 추세 반대: 상승 0·하락 3·중립 1" in text
    code, main = LM.show_text(w.src().db, w.p["paper"], NOW, 7, 30, None)
    assert code == 0 and "VWAP" not in main


def test_the_shared_budget_takes_the_main_bot_first_and_leaves_the_vwap_bot_its_half(world):
    w = world
    conn = LC.open_out(w.src().db)
    try:
        res = LM.missed_pass(w.src(), conn, NOW, cap=4)
        assert res["capped"] and res["new"] == 4 and res["vwap"]["new"] == 2 and res["vwap"]["capped"]
        res2 = LM.missed_pass(w.src(), conn, NOW + MIN, cap=60)
        assert res2["vwap"]["new"] == 1
    finally:
        conn.close()


def test_the_vwap_morning_line_and_the_column_on_an_older_table(world, tmp_path):
    w = world
    conn = LC.open_out(w.src().db)
    try:
        LM.missed_pass(w.src(), conn, NOW)
        vt = LC.PaperSet(w.p["paper"]).trades(w.p["vwap"])
        line = LM.morning_line(conn, vt, V5, *LC.window_of("2026-10-19"), paper="vwap")
        assert line == "VWAP 조건이 막은 신호 어제 3개(가상): 2승 1패 · 실제로 탄 거래 2승 2패 진행 1"
        assert "VWAP" not in (LM.morning_line(conn, [], None, *LC.window_of("2026-10-19")) or "")
    finally:
        conn.close()
    old = sqlite3.connect(str(tmp_path / "old.db"))
    old.execute("CREATE TABLE missed (key TEXT PRIMARY KEY, t INTEGER NOT NULL, step_ts INTEGER NOT NULL, member TEXT, "
                "strategy TEXT, tf TEXT, symbol TEXT NOT NULL, side INTEGER NOT NULL, why_kind TEXT NOT NULL, why TEXT NOT NULL, "
                "state TEXT NOT NULL, sims INTEGER NOT NULL DEFAULT 0, first_ts INTEGER NOT NULL, updated_ts INTEGER NOT NULL, "
                "signal TEXT NOT NULL)")
    assert LM.read_rows(old, 0, paper="vwap") == [] and LM.read_rows(old, 0) == []
    LM._schema(old)
    assert "paper" in {r[1] for r in old.execute("PRAGMA table_info(missed)")}
    old.close()


def test_an_executor_that_did_not_follow_the_vwap_bot_is_a_vwap_row(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"), skip=("v4",))
    try:
        conn = LC.open_out(w.src().db)
        try:
            LM.missed_pass(w.src(), conn, NOW)
            rows = LM.read_rows(conn, 0, paper="vwap")
            main = LM.read_rows(conn, 0)
        finally:
            conn.close()
        ex = [r for r in rows if r["grp"] == "exec"]
        assert [(r["key"], r["executor"]) for r in ex] == [(f"exec:bybit|COMBO@mix#vwap|LTCUSDT|{VW.V4}", "bybit")]
        assert not [r for r in main if "#vwap" in r["key"]]
    finally:
        w.close()
