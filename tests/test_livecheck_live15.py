"""규칙봇 15 (owners 10-19, live from 10-20) in the live side's Telegram words (paperbot/livecheck.py, livepreview.py):
the live executor configs (deploy/executor.live-*.json) have no signal light and no loss-streak or drawdown halt, and the
5-year reference (deploy/combo.live-ac.expected.json) is the A+C bot's. So no message says 연패 멈춤 / 낙폭 멈춤 / 신호등 /
A+C / 3 ATR / 그 뒤 3%씩, no 🚦 and no 🏁; an old config that has those halts and the light still reads as before."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paperbot import livecheck as LC  # noqa: E402
from paperbot.notify import CRITICAL, ListNotifier  # noqa: E402
from test_livecheck import (BTC, DAY, H1, MIN, T, W0, Units, _set_bot, card_setup, entered, exec_db, info,  # noqa: E402
                            loss, msgs, paper_db, rule_db, xtrade)

ROOT = Path(LC.ROOT)
DEPLOY = ROOT / "deploy"
# words of the old rules that must not reach the owners from 규칙봇 15's live side
OLD = ("연패면", "3연패", "낙폭 50%", "50%가 되면", "연패 멈춤", "신호등", "A+C", "3 ATR", "3%씩", "27개", "95개",
       "🚦", "🏁", "40번 도달", "88% 이상", "82% 미만", "멈추고 다시 생각")


def live_infos(tmp_path, dbs: dict) -> list:
    """The two executors as their live configs say (read by load_executors from deploy/), on test databases."""
    specs = tuple((n, str(DEPLOY / f"executor.live-{n}.json"), f"paperbot-executor-{n}", "/fb.db", 20, 0.85)
                  for n in ("bybit", "mexc"))
    out = LC.load_executors(specs)
    for e in out:
        e.db, e.kill_file = dbs[e.name], "/nonexistent/STOP"
    return out


def test_the_live_executor_configs_have_no_light_and_no_halt_of_their_own(tmp_path):
    specs = tuple((n, str(DEPLOY / f"executor.live-{n}.json"), "u", "/fb.db", 20, 0.85) for n in ("bybit", "mexc"))
    for e in LC.load_executors(specs):
        assert (e.light_n, e.max_dd, e.max_streak, e.max_loss, e.problem) == (0, None, None, 0.35, "")
        assert not e.light_on and e.auto_halts is False and e.kill_file == "/var/lib/paperbot/STOP"
    old = tmp_path / "old.json"
    d = json.loads((DEPLOY / "executor.live-bybit.json").read_text(encoding="utf-8"))
    d["risk"].update(max_consecutive_losses=3, max_drawdown_pct=0.5)
    d["signal_light_n"] = 20
    old.write_text(json.dumps(d), encoding="utf-8")
    (e,) = LC.load_executors((("bybit", str(old), "u", "/fb.db", 0, 0.85),))
    assert (e.light_n, e.max_dd, e.max_streak) == (20, 0.5, 3) and e.light_on and e.auto_halts is True
    (e,) = LC.load_executors((("bybit", str(tmp_path / "missing.json"), "u", "/fb.db", 0, 0.85),))
    assert e.problem and e.auto_halts is None and e.light_n == 0      # unreadable: the live configs' light (none)


def test_the_drawdown_alarm_says_there_is_no_halt_and_names_both_ways_to_stop(tmp_path):
    paper = paper_db(tmp_path / "live-ac.db", heartbeat=T - MIN)
    rule = rule_db(tmp_path / "paper3.db", T - 2 * MIN)
    byb = exec_db(tmp_path / "bybit.db", state_ts=T - MIN)
    mx = exec_db(tmp_path / "mexc.db", state_ts=T - MIN)
    src = LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=paper, rule_db=rule, combo_config="-",
                     executors=live_infos(tmp_path, {"bybit": byb, "mexc": mx}))
    _set_bot(byb, ts=T, last_equity=74.0, peak_equity=100.0)
    n = ListNotifier()
    LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    (lv, text), = msgs(n, "바이비트 실거래 잔고가")
    assert lv == CRITICAL and text.split("\n") == [
        "바이비트 실거래 잔고가 최고점보다 26% 줄었습니다", "잔고 $74.00 · 최고 $100.00",
        "잔고가 줄어도 실행기는 스스로 멈추지 않습니다(낙폭 멈춤 없음)",
        "지금 할 일: 두 분이 계속할지 정하세요(멈추려면 sudo systemctl stop paperbot-executor-bybit, 포지션은 거래소 손절이 "
        "지킴 · 두 실행기 모두 바로 닫고 멈추려면 sudo touch /nonexistent/STOP)"]
    # the old config (a 50% halt): as before; a config that could not be read: neither claimed
    old = info("bybit", byb)
    assert LC.dd_halt_words(old).startswith("50%가 되면 실행기가 스스로 멈춥니다\n지금 할 일:")
    unknown = info("bybit", byb, halts=False)
    unknown.problem = "설정 파일을 못 읽음"
    assert LC.dd_halt_words(unknown) == ("지금 할 일: 두 분이 계속할지 정하세요(멈추려면 sudo systemctl stop "
                                         "paperbot-executor-bybit, 포지션은 거래소 손절이 지킴)")


def test_a_losing_run_card_says_no_executor_halts_by_itself(tmp_path):
    a, b = T - 3 * H1, T - H1
    src = card_setup(tmp_path, [loss(a, a + 30 * MIN), loss(b, b + 30 * MIN)], [entered(a), entered(b)])
    src.executors = live_infos(tmp_path, {e.name: e.db for e in src.executors})
    n = ListNotifier()
    LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    loud = [(lv, m) for lv, m in n.messages if m.startswith("🚨 ❌ 청산")]
    assert len(loud) == 1 and loud[0][0] == CRITICAL
    assert loud[0][1].splitlines()[-1] == ("지금 할 일: 연패해도 실행기는 스스로 멈추지 않습니다. 계속할지 두 분이 정하세요"
                                          "(두 실행기 모두 바로 닫고 멈추려면 sudo touch /nonexistent/STOP)")
    for _lv, m in n.messages:
        assert "연패면" not in m and "신호등" not in m, m
    # the old configs (3 losses): as before; configs not known: neither claimed
    assert LC.streak_todo([info("bybit", "x"), info("mexc", "y")]) == "따로 할 일은 없습니다. 3연패면 실행기가 스스로 멈춥니다(9장)"
    assert LC.streak_todo(None) == "계속할지 두 분이 정하세요(손실 카드들의 판정을 같이 보세요)"


def test_a_halt_without_the_old_halts_names_its_own_reason_and_no_old_rule(tmp_path):
    a = W0
    src = card_setup(tmp_path, [loss(a, a + 30 * MIN)], [entered(a)],
                     x_trades=[xtrade(a, exit_price=99.0, pnl=-1.0, exit_ts=a + 30 * MIN)])
    src.executors = live_infos(tmp_path, {e.name: e.db for e in src.executors})
    _set_bot(src.executors[0].db, ts=T, halted=True, halt_reason="방향이 반대인 포지션 발견", halted_ts=a + H1,
             halt_kinds=["wrong_side"], last_equity=96.0)
    n = ListNotifier()
    LC.run_watch(src, now_ms=T, notifier=n, units=Units(), exists=lambda p: False)
    (lv, m), = [(lv, m) for lv, m in n.messages if "실행기가 멈췄습니다" in m]
    assert lv == CRITICAL and m.startswith("바이비트 실행기가 멈췄습니다 · 이유: 방향이 반대인 포지션(실행기 안전장치)")
    assert "안내:\n- " + LC.HALT_GUIDE_NO_AUTO[0] in m and f"- {LC.HALT_GUIDE[1]}" in m
    assert "3연패" not in m and "낙폭 50%" not in m and "신호등" not in m
    assert "페이퍼 거래 1번(표본 작음)\n" in m                     # no light after the paper's record
    # the rule of a halt with the executor's own numbers (its config, else the halt's record)
    old = info("bybit", "x")
    old.max_streak, old.max_dd = 4, 0.4
    assert LC.halt_rule({"halt_kinds": ["streak"], "halt_reason": "x"}, old) == "4연패(연속 손실 4번)"
    assert LC.halt_rule({"halt_kinds": ["drawdown"]}, old) == "낙폭 40%"
    assert LC.halt_rule({"halt_reason": "연속 손실 5번이 멈춤 기준 5번에 닿았습니다"}) == "5연패(연속 손실 5번)"
    assert LC.halt_rule({"halt_reason": "최고점 $120.00 대비 낙폭 31.0%가 멈춤 기준 30%에 닿았습니다"}) == "낙폭 30%"
    assert LC.halt_guide(old, {"halt_kinds": ["kill"]})[1] == LC.HALT_GUIDE          # an old config with halts


def test_no_light_words_in_trade_messages_and_no_light_or_checkpoint_in_the_morning(tmp_path):
    src = card_setup(tmp_path, [], [])
    src.executors = live_infos(tmp_path, {e.name: e.db for e in src.executors})
    paper = [{"exit_time": T - H1, "pnl": 3.0, "id": 1, "entry_time": T - 2 * H1}]
    assert LC.day_line(paper, T, src.executors) == "오늘 1승 0패 · 지금까지 1번 1승(표본 작음)"
    assert LC.day_line(paper, T, [info("bybit", "x")]).endswith(" · 신호등 바이비트 ⚪")       # an old config with the light
    r = {"label": "바이비트", "trades": 3, "wins": 3, "pnl": 1.0, "equity": 101.0, "light": LC.light_state([], 0, 0.85),
         "light_skips": 2}
    p = {"n": 45, "wins": 40, "rate": 40 / 45, "pnl": 9.0, "day": {"n": 0}, "first40": {"wins": 36, "rate": 0.9}}
    lines = LC.score_lines(p, [r], [], LC.REF_OTHER_CONFIG_KO)
    assert lines[2] == "- 바이비트: 거래 3번 · 3승(100%) · 실현 +$1.00 · 잔고 $101.00 · 정상"
    assert lines[3] == "※ 20번 미만은 표본이 작아 승률은 참고만 하세요" and len(lines) == 4
    assert not [ln for ln in lines if "신호등" in ln or "판단" in ln]


def test_the_morning_rest_line_has_the_nasdaq_open_of_the_config():
    cfg = json.loads((DEPLOY / "combo.live15.json").read_text(encoding="utf-8"))
    _w0, w1 = LC.window_of("2026-10-28")                            # Thursday 10/29 09:00 KST: PCE, Nasdaq at 22:30 (DST)
    assert LC.rest_line(w1, cfg) == "- 오늘 진입 쉬는 시간: 21:00~22:00 PCE 물가 · 22:30~23:00 나스닥 개장"
    _w0, w1 = LC.window_of("2026-11-03")                            # Wednesday 11/04: New York on winter time
    assert "23:30~00:00 나스닥 개장" in LC.rest_line(w1, cfg)
    _w0, w1 = LC.window_of("2026-11-25")                            # Thursday 11/26: Thanksgiving, NYSE closed
    assert "나스닥" not in LC.rest_line(w1, cfg)
    _w0, w1 = LC.window_of("2026-10-30")                            # Saturday: no open
    assert LC.us_open_span(w1, 30) is None and LC.us_open_span(w1 - DAY, None) is None
    assert "나스닥" not in LC.rest_line(LC.window_of("2026-10-28")[1], {"macro_blackout_min": 30})   # the A+C config


def test_the_preview_of_the_live15_world_has_none_of_the_old_rules(monkeypatch):
    import urllib.request
    from paperbot import livepreview as PV

    def no_network(*a, **k):
        raise AssertionError("the preview must not reach the network")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    items = PV.scenes()
    text = PV.render(items)
    titles = {PV.kind_of(PV.shown(lv, t)[0]) for _s, lv, t in items}
    for kind in ("실행기 켜짐", "진입", "잠금 시작", "청산(이김)", "손실 카드", "손실 카드(소리)", "실행기 꺼짐(사람이 끔)",
                 "진입 쉼 시작", "진입 쉼 끝", "좋은 소식", "다시 정상", "아침 점검", "아침 점검(확인할 것 있음)",
                 "알람: 따라가지 않음", "알람: 실행기 조용함", "알람: 손절 기록 없음", "알람: 디스크 부족", "알람: 메모리 부족",
                 "알람: 페이퍼 봇 멈춤", "알람: 1분봉 멈춤", "알람: 잔고 25% 하락", "알람: 실거래만 짐", "알람: 멈춤 요약",
                 "알람: 텔레그램 설정", "텔레그램 설정 맞춰짐"):
        assert kind in titles, kind
    for kind in ("신호등 바뀜", "40번 도달", "진입 대기", "알람: 기대 범위 밑"):
        assert kind not in titles, kind
    for w in OLD:
        assert w not in text, w
    assert "빠른 청산(반대 신호)" in text and "목록 12번" in text and "22:30~23:00 나스닥 개장" in text
    assert "잔고가 줄어도 실행기는 스스로 멈추지 않습니다(낙폭 멈춤 없음)" in text
    assert "지금 할 일: 연패해도 실행기는 스스로 멈추지 않습니다." in text
    assert text.count(LC.REF_OTHER_CONFIG_KO) >= 2                  # said on each loss card and once per morning check
    # the A+C world (its configs had the light and the halts): the old words, as before
    old = PV.render(PV.scenes("ac"))
    for w in ("3연패면 실행기가 스스로 멈춥니다(9장)", "50%가 되면 실행기가 스스로 멈춥니다", "🚦 신호등", "🏁 40번 도달",
              "- 3연패나 낙폭 50% 멈춤은 이유가 있어서 걸린 것입니다"):
        assert w in old, w
    assert LC.main(["preview"]) == 0 and LC.main(["preview", "--old"]) == 0


def test_the_morning_line_names_the_chase_block_not_research_settings():
    import sqlite3
    from paperbot import livemissed as LM
    conn = sqlite3.connect(":memory:")
    conn.executescript(LM.SCHEMA_TABLES)

    def row(k, t, grp, kind, pnl):
        conn.execute("INSERT INTO missed (key, t, step_ts, symbol, side, why_kind, why, state, pnl, first_ts, updated_ts, "
                     "signal, grp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (k, t, t, BTC, 1, kind, kind, "closed", pnl, t, t, "{}", grp))
    row("a", W0 + H1, "research", "chase", 3.0)
    row("b", W0 + 2 * H1, "research", "chase", -15.0)
    row("c", W0 + 3 * H1, "pause", "usopen", 3.0)
    line = LM.morning_line(conn, [], None, W0, W0 + DAY)
    assert line == "어제 못 탄 신호 3개(가상): 추격 막기 1승 1패 · 쉬는 시간 1승 0패 · 실제로 탄 거래 0승 0패"
    row("d", W0 + 4 * H1, "research", "filter", 3.0)                 # the A+C bot's research settings next to it
    assert "연구 조건·추격 막기 2승 1패" in LM.morning_line(conn, [], None, W0, W0 + DAY)
