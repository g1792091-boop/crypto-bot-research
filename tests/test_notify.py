"""The Telegram text of alerts (paperbot/notify.py; owners' layout 2026-10-04): the engine's, the feed's and the
runner's English lines reach the owners in Korean (a title '<what> · <whom>', short lines, the KST time), one emoji
first, the copies and new-strategy accounts by name, and the noisy operational lines held for the silent digest."""
import urllib.parse

import pytest

from paperbot import notify
from paperbot.agents.roster3 import STRATEGY_KO
from paperbot.config import V4_ACCOUNTS
from paperbot.notify import (CRITICAL, INFO, WARN, Digest, ListNotifier, Router, TelegramNotifier, ko, money, render,
                             telegram_text, usd, who)

T = 1790985600000          # 2026-10-03 00:00 UTC = 09:00 KST
S2 = STRATEGY_KO["S2_ST_ROC"]
TG_SENDS_DEFAULT = notify.TG_SENDS_DB      # before the autouse fixture blanks it


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setattr(notify, "_clock", lambda: (T + 12 * 3_600_000 + 15 * 60_000) / 1000)   # 10/03 21:15 KST
    monkeypatch.delenv("PAPERBOT_TG_SENDS_DB", raising=False)     # never count a test's sends on a real server
    monkeypatch.setattr(notify, "TG_SENDS_DB", "")


def test_number_helpers():
    assert usd(84.2) == "+$84" and usd(-18.4) == "-$18" and usd(0) == "+$0" and usd(1500) == "+$1,500"
    assert money(1500.0) == "$1,500" and money(3980.12) == "$3,980" and money(-5) == "-$5"
    assert notify.day_ko("2026-10-03") == "10/03" and notify.day_ko("20261003") == "10/03" and notify.day_ko("d") == "d"
    assert notify.secs_ko(45) == "45초" and notify.secs_ko(412) == "7분" and notify.secs_ko(7300) == "약 2시간"
    assert notify.now_kst() == "10/03 21:15" and notify.hm(T) == "09:00"


def test_account_names_copies_and_new_strategies_read_as_names():
    assert who("S2_ST_ROC@15m") == f"{S2} 15분"
    assert who("S2_ST_ROC@1h~c1") == f"복제 {S2} 1시간"              # was the raw id / '1h~c1'
    assert who("NL2@15m") == "새 매매법 NL2 15분"
    assert who("RANDOM_3@1h") == "동전 봇 3 1시간"
    assert who("S2_ST_ROC@1h", kind="copy") == f"복제 {S2} 1시간"
    assert who("weird") == "weird"


def test_engine_and_feed_lines_in_korean():
    assert ko("[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 1500.00") == \
        f"모의 강제청산 · {S2} 15분\n\nSOL 25배\n증거금 $1,500 전액 손실\n10/03 21:15"       # never '$1500.00'
    assert ko("[S2_ST_ROC@1h~c1] LIQUIDATED SOLUSDT 15x lost margin 610.00").startswith(f"모의 강제청산 · 복제 {S2} 1시간\n")
    assert ko("[RANDOM_2@15m] BUST: bust: equity 9.50 below 10.00") == "동전 봇 2 15분 파산 · 잔고 $9 (파산선 $10)"
    assert ko("[S2_ST_ROC@1h] drawdown 31.0% (level 30%), equity 3450.00") == f"{S2} 1시간 낙폭 -30% · 잔고 $3,450"
    assert ko(f"signal workers did not answer within 120s; signals skipped at {T} for 15m, 30m") == \
        "신호 건너뜀 · 09:00 봉\n\n신호 계산이 120초 안에 안 끝남\n건너뛴 봉: 15분, 30분\n계산 프로세스를 새로 띄움 · 봇은 계속 돎"
    assert ko(f"data gap at {T}: no bar for ['BTCUSDT', 'ETHUSDT']") == "1분봉 빠짐 · 09:00\n\nBTC, ETH\n그 코인은 그 1분을 건너뜀"
    assert ko(f"DOGEUSDT: exchange returned no bars for 3 min from {T}") == "바이낸스 1분봉 없음 · DOGE\n\n09:00부터 3분 동안"
    assert ko("no new closed bars for 245s") == "시세 끊김\n\n새 1분봉이 4분째 안 들어옴\n10/03 21:15"
    assert ko("local clock off by 1250 ms from Binance; using server time") == \
        "서버 시계 어긋남\n\n바이낸스와 1.25초 차이\n바이낸스 시각으로 계산 중 (조치 불필요)"
    assert ko("Binance blocked this server: HTTP 451 Unavailable For Legal Reasons") == \
        "바이낸스 접속 차단\n\n봇이 멈췄습니다\n응답: HTTP 451 (지역 제한)\n10/03 21:15"
    # anything else goes out unchanged; a wording helper never stops an alert
    for t in ("에이전트 알림 · 방", "[NEW@15m] LIQUIDATED x", "🔔 가격 알림 · BTC 65,000 돌파"):
        assert ko(t) == t
    odd = "signal workers did not answer within 120s; signals skipped at 99999999999999999999999 for 15m"
    assert ko(odd) == odd


def test_the_six_english_messages_are_korean():
    assert ko("paper v3 resumed: 156 accounts, brackets: Binance leverageBracket (live), taker fee 0.0500%") == \
        "▶️ 봇 재시작 · 계좌 156개\n\n이어서 돌림\n레버리지 구간: 바이낸스 실시간\n수수료 0.05%"
    assert ko("paper v3 started: 156 accounts, brackets: file b.json, taker fee 0.0400%").startswith(
        "▶️ 봇 시작 · 계좌 156개\n\n새로 시작\n레버리지 구간: 파일 b.json\n수수료 0.04%")
    assert ko("[S2_ST_ROC@15m] ENGINE HALTED: manual kill. Operator action required.") == \
        f"계좌 정지 · {S2} 15분\n\n이유: 수동 정지\n운영자 확인 필요\n10/03 21:15"
    assert ko("[extra] extras code failed to load: ImportError: cannot import name 'X' from 'paperbot.newlab_live'") == \
        f"추가 계좌 코드 오류\n\n추가 계좌가 저장된 상태로 멈춤\n원래 계좌 {V4_ACCOUNTS}개는 그대로 돎\n오류: ImportError (newlab_live)"
    hook = ko("[extra] boundary hook failed (KeyError: 'NL2@15m')")
    assert hook.startswith("추가 계좌 코드 오류\n\n") and hook.endswith("오류: KeyError") and "extra" not in hook
    from paperbot.flow import gap_text
    assert gap_text([["BTCUSDT", 1756684800000, 1756771200000], ["ETHUSDT", 1, 2]]) == \
        "주문 흐름 기록 구멍 2곳\n\n바이낸스 보관 30일이 지나 다시 받을 수 없음\n첫 구멍: BTC 9/01~9/02"
    import inspect
    from paperbot import liqstream
    src = inspect.getsource(liqstream)
    assert "청산 기록 끊김 후 복구" in src and "liquidation stream was down" not in src
    for text in (ko("[extra] extras could not start: RuntimeError: x"),):
        assert all(w not in text for w in ("extras", "failed", "load"))


def test_prefix_is_skipped_when_the_text_has_its_own_emoji():
    assert telegram_text(WARN, "🔔 가격 알림 · BTC 65,000 돌파") == (WARN, "🔔 가격 알림 · BTC 65,000 돌파")   # not '⚠ 🔔'
    assert telegram_text(WARN, "재계산 못 함 · 10/03") == (WARN, "⚠ 재계산 못 함 · 10/03")
    assert telegram_text(CRITICAL, "[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 10.00")[1].startswith("🚨 모의 강제청산 · ")
    assert telegram_text(INFO, "paper v3 resumed: 1 accounts, brackets: x, taker fee 0.05%")[1].startswith("▶️ 봇 재시작")
    assert telegram_text(INFO, "ℹ️ 재시작 변경 · 코드 버전")[1].startswith("ℹ️")


def test_loud_and_silent_by_type():
    """Sound comes only from the level: emergencies stay loud, good news and digests are silent."""
    loud = ["[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 10.00",
            "[S2_ST_ROC@15m] ENGINE HALTED: manual kill. Operator action required.",
            "Binance blocked this server: HTTP 451",
            "[extra] S2_ST_ROC@1h~c1: 멈춤(새 진입 없음, 열린 포지션은 규칙대로 관리) — parent_bust: 원본 계좌 파산"]
    for t in loud:
        assert telegram_text(CRITICAL, t)[0] == CRITICAL
    # an extra back to normal: silent (was a loud 🚨), alone or in a bundle of only those
    lvl, text = telegram_text(CRITICAL, "[extra] NL2@15m: 다시 정상 운영 (관찰 기간 해소)")
    assert lvl == INFO and text == "✅ 추가 계좌 재개 · 새 매매법 NL2 15분\n\n관찰 기간 끝"
    two = "추가 계좌 긴급 알림 2건\n[extra] NL2@15m: 다시 정상 운영 (관찰 기간 해소)\n[extra] NL3@1h: 다시 정상 운영 (멈춤 해소)"
    assert telegram_text(CRITICAL, two)[0] == INFO
    mixed = "추가 계좌 긴급 알림 2건\n[S2_ST_ROC@1h~c1] LIQUIDATED SOLUSDT 15x lost margin 610.00\n" \
            "[extra] NL2@15m: 다시 정상 운영 (관찰 기간 해소)"
    lvl, text = telegram_text(CRITICAL, mixed)
    assert lvl == CRITICAL and text == (f"🚨 추가 계좌 긴급 2건 · 모의 강제청산 1\n\n- 강제청산 · 복제 {S2} 1시간 · SOL 15배 · -$610\n"
                                        "- 재개 · 새 매매법 NL2 15분 (관찰 기간 끝)\n10/03 21:15")


def test_extras_lines_drop_codes():
    t = telegram_text(CRITICAL, "[extra] S2_ST_ROC@1h~c1: 멈춤(새 진입 없음, 열린 포지션은 규칙대로 관리) — "
                                "parent_bust: 원본 계좌 S2_ST_ROC@1h 파산")[1]
    assert t == f"🚨 추가 계좌 멈춤 · 복제 {S2} 1시간\n\n새 진입 없음 (열린 포지션은 규칙대로)\n이유: 원본 계좌가 파산\n10/03 21:15"
    t = telegram_text(INFO, "[extra] 새 paper 계좌 시작: 슈퍼트렌드·ROC 1시간 복제 c1 · 손절 2.5 ATR (S2_ST_ROC@1h~c1), 제안 #12")[1]
    assert t == f"🆕 새 계좌 시작 · 복제 {S2} 1시간\n\n바꾼 한 가지: 손절 2.5 ATR\n제안 #12 (두 분 승인)"
    t = telegram_text(CRITICAL, "[extra] agents3.db가 예전 것으로 바뀐 것 같아 새 계좌 시작을 멈춤. 확인 후 "
                                "extras.json에 \"agents_ack\": \"trial 1 · proposal 2\" 를 넣으세요")[1]
    assert t.startswith("🚨 새 추가 계좌 시작 멈춤\n\n") and t.endswith('운영자: extras.json에 "agents_ack": "trial 1 · proposal 2" 넣기')


def _telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_CRITICAL", "111")
    sent = []

    class Resp:
        def read(self):
            return b"{}"
    monkeypatch.setattr(notify.urllib.request, "urlopen",
                        lambda url, data=None, timeout=None: sent.append(urllib.parse.parse_qs(data.decode())) or Resp())
    return sent


def test_telegram_text_has_one_mark_and_korean_wording(monkeypatch):
    sent = _telegram(monkeypatch)
    n = TelegramNotifier()
    assert n.send(CRITICAL, "[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 123.45") is True
    assert n.send(WARN, f"data gap at {T}: no bar for ['BTCUSDT']") is True
    assert n.send(INFO, "📊 주간 성적표") is True
    assert n.send(CRITICAL, "[extra] NL2@15m: 다시 정상 운영 (관찰 기간 해소)") is True
    texts = [d["text"][0] for d in sent]
    assert texts[0] == f"🚨 모의 강제청산 · {S2} 15분\n\nSOL 25배\n증거금 $123 전액 손실\n10/03 21:15"
    assert texts[1] == "⚠ 1분봉 빠짐 · 09:00\n\nBTC\n그 코인은 그 1분을 건너뜀"
    assert texts[2] == "📊 주간 성적표"                         # silent, and no '[INFO]' in front
    assert [d["disable_notification"][0] for d in sent] == ["true", "true", "true", "true"]   # all silent (owners)


def test_every_message_is_silent_unless_the_env_turns_sound_on(monkeypatch):
    """Owners 2026-10-05: every Telegram message silent. TELEGRAM_SOUND=1 brings back the level rule (INFO only)."""
    sent = _telegram(monkeypatch)
    monkeypatch.delenv("TELEGRAM_SOUND", raising=False)
    quiet = TelegramNotifier()
    for level in (CRITICAL, WARN, INFO):
        assert quiet.send(level, "x") is True
    monkeypatch.setenv("TELEGRAM_SOUND", "1")
    loud = TelegramNotifier()
    for level in (CRITICAL, WARN, INFO):
        assert loud.send(level, "x") is True
    monkeypatch.setenv("TELEGRAM_SOUND", "0")
    assert TelegramNotifier().send(CRITICAL, "x") is True
    assert [d["disable_notification"][0] for d in sent] == ["true"] * 3 + ["false", "false", "true"] + ["true"]


def test_digest_text_stays_the_record_and_reaches_telegram_grouped(monkeypatch):
    """The Digest's own text stays as it is (the stored record, tests/test_extras_parity.py's golden); Telegram gets
    it regrouped: busts, drawdowns by level, whole dollars, the pointer to the alert screen. A coin flip's line stays
    in the record and is only counted in Telegram (owners' D10, paper v4)."""
    sent = _telegram(monkeypatch)
    d = Digest(TelegramNotifier(), every_ms=1, max_lines=3)
    d.flush(0)
    d.add("[S2_ST_ROC@1h] drawdown 20.4% (level 20%), equity 3980.12")
    d.add("[RANDOM_2@15m] BUST: bust: equity 8.40 below 10.00")
    d.add("[N07_ICHI_CMO@4h] drawdown 40.2% (level 40%), equity 2990.80")
    d.add("[S2_ST_ROC@4h] drawdown 30.1% (level 30%), equity 3495.55")
    text = d.flush(10)
    # the coin flip's line would push S2_ST_ROC@4h past the cut: it gets a count line instead (jobs review 3)
    assert text.splitlines() == ["알림 모음: 낙폭 3 · 파산 1", "[S2_ST_ROC@1h] drawdown 20.4% (level 20%), equity 3980.12",
                                 "[N07_ICHI_CMO@4h] drawdown 40.2% (level 40%), equity 2990.80",
                                 "[S2_ST_ROC@4h] drawdown 30.1% (level 30%), equity 3495.55",
                                 "동전 계좌 경고 1건 · 계좌 1개: 파산 1 (대시보드 알림 목록)"]
    assert sent[0]["text"][0] == (
        "📉 파산·낙폭 모음 · 지난 1시간\n\n낙폭 경고 3건\n"
        f"- {STRATEGY_KO['N07_ICHI_CMO']} 4시간 · -40% · 잔고 $2,991\n- {S2} 4시간 · -30% · 잔고 $3,496\n"
        f"- {S2} 1시간 · -20% · 잔고 $3,980\n\n개수만 (계좌별 줄은 대시보드)\n- 동전 계좌 1개 · 파산 1")
    assert sent[0]["disable_notification"] == ["true"]
    # no coin flip in the listed places: the record, its cut and '외 N건' as before (v3 shape)
    for b in ("S2_ST_ROC@1h", "S2_ST_ROC@4h", "N07_ICHI_CMO@4h", "N07_ICHI_CMO@1h"):
        d.add(f"[{b}] drawdown 20.4% (level 20%), equity 3980.12")
    d.add("[RANDOM_2@15m] BUST: bust: equity 8.40 below 10.00")
    assert d.flush(20).splitlines()[1:] == ["[S2_ST_ROC@1h] drawdown 20.4% (level 20%), equity 3980.12",
                                            "[S2_ST_ROC@4h] drawdown 20.4% (level 20%), equity 3980.12",
                                            "[N07_ICHI_CMO@4h] drawdown 20.4% (level 20%), equity 3980.12",
                                            "외 2건 (대시보드 알림 목록)"]
    assert sent[1]["text"][0].endswith("잔고 $3,980\n\n외 2건 (대시보드 '서버 › 알림 기록')")


def test_extras_digest_counts_operational_notes_only(monkeypatch):
    from paperbot.extras import ExtrasDigest
    sent = _telegram(monkeypatch)
    xd = ExtrasDigest(TelegramNotifier())
    xd.add("[S2_ST_ROC@1h~c1] drawdown 20.3% (level 20%), equity 3985.40")
    xd.add("[extra] NL2@15m: 아직 신호를 계산하지 않음 (워밍업 중)")
    xd.add("[extra] 경계 1759580400000: 시간 예산을 넘어 이번에는 새 계좌 확인을 건너뜀")
    xd.flush(0, force=True)
    text = sent[0]["text"][0]
    assert text == (f"📉 추가 계좌 경고 · 지난 1시간\n\n낙폭 경고 1건\n- 복제 {S2} 1시간 · -20% · 잔고 $3,985\n\n"
                    "운영 메모 2건 (대시보드 '서버 › 알림 기록')")
    assert "1759580400000" not in text and "NL2@15m" not in text


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_router_holds_gaps_for_the_digest_and_rings_once_past_the_threshold():
    out = ListNotifier()
    d = Digest(out)
    clk = Clock(T)
    r = Router(out, d, clock=clk)
    for k in range(4):
        assert r.send(WARN, f"data gap at {T + k * 60_000}: no bar for ['SOLUSDT', 'LTCUSDT']") is None
    assert out.messages == [] and d.notes["gaps"].startswith("1분봉 빠짐 8분: ")
    r.send(WARN, f"BTCUSDT: exchange returned no bars for 3 min from {T}")
    assert [lv for lv, _ in out.messages] == [WARN]                       # 11 coin-minutes: one loud message
    assert out.messages[0][1].startswith("1분봉 빠짐 많음 · 11분\n\n")
    r.send(WARN, f"data gap at {T}: no bar for ['SOLUSDT']")
    assert len(out.messages) == 1                                          # not again before the digest goes out
    d.flush(T, force=True)
    assert out.messages[-1][0] == INFO and "1분봉 빠짐 12분: SOL 5분 · LTC 4분 · BTC 3분" in out.messages[-1][1]
    r.send(WARN, f"data gap at {T}: no bar for ['SOLUSDT']")
    assert d.notes["gaps"].startswith("1분봉 빠짐 1분: ")                   # counted afresh after the digest
    # emergencies and other lines pass at once
    r.send(CRITICAL, "[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 10.00")
    r.send(WARN, "no new closed bars for 245s")
    assert [lv for lv, _ in out.messages[-2:]] == [CRITICAL, WARN]


def test_router_clock_skew_once_a_day_and_only_above_5s():
    out = ListNotifier()
    d = Digest(out)
    clk = Clock(T)
    r = Router(out, d, clock=clk)
    r.send(WARN, "local clock off by 1250 ms from Binance; using server time")
    assert out.messages == [] and "서버 시계 어긋남 1.25초" in d.notes["skew"]
    for _ in range(3):
        r.send(WARN, "local clock off by 6000 ms from Binance; using server time")
    assert [lv for lv, _ in out.messages] == [WARN]
    clk.t += 86_400_000
    r.send(WARN, "local clock off by -7000 ms from Binance; using server time")
    assert len(out.messages) == 2                                          # the next KST day: told again


def test_router_signal_timeouts_first_loud_then_counted():
    out = ListNotifier()
    d = Digest(out)
    clk = Clock(T)
    r = Router(out, d, clock=clk)
    line = "signal workers did not answer within 120s; signals skipped at {} for 15m, 30m"
    r.send(WARN, line.format(T))
    for k in range(1, 4):
        clk.t = T + k * 300_000
        r.send(WARN, line.format(clk.t))
    assert [lv for lv, _ in out.messages] == [WARN]
    assert d.notes["timeouts"] == "신호 건너뜀 3번 더 (마지막 09:15 봉: 15분, 30분)"
    clk.t += Router.TIMEOUT_QUIET_MS
    r.send(WARN, line.format(clk.t))
    assert [lv for lv, _ in out.messages] == [WARN, WARN]                  # quiet for 6 hours: loud again


def test_router_signal_timeouts_that_keep_coming_keep_ringing():
    """96 timeouts, one at every 15m boundary for 24 h (the worker pool hangs at each boundary): the quiet period
    runs from the last LOUD one, and every 12th further timeout rings again (review M3: it used to ring once)."""
    out = ListNotifier()
    d = Digest(out)
    clk = Clock(T)
    r = Router(out, d, clock=clk)
    line = "signal workers did not answer within 120s; signals skipped at {} for 15m"
    for k in range(96):
        clk.t = T + k * 900_000
        r.send(WARN, line.format(clk.t))
        d.flush(clk.t)
    loud = [t for lv, t in out.messages if lv == WARN]
    assert len(loud) == 8                                                  # at 0 h, 3 h, 6 h, ... 21 h
    assert "지난 소리 알림 뒤 11번 더 건너뜀" in loud[1] and loud[0].count("\n") == 0
    assert render(loud[1]).startswith("신호 건너뜀 · ") and "지난 소리 알림 뒤 11번 더" in render(loud[1])
    assert len([t for lv, t in out.messages if lv == INFO and "신호 건너뜀" in render(t)]) >= 16   # digest counts too


def test_router_signal_timeouts_every_5h_ring_after_6h_since_the_last_loud():
    out = ListNotifier()
    r = Router(out, Digest(out), clock=Clock(T))
    line = "signal workers did not answer within 120s; signals skipped at {} for 1h"
    for k in range(5):                     # 0, 5, 10, 15, 20 h: before, only the first rang
        r.clock.t = T + k * 5 * 3_600_000
        r.send(WARN, line.format(r.clock.t))
    assert len([1 for lv, _ in out.messages if lv == WARN]) == 3          # 0 h, 10 h, 20 h


def test_digest_without_notes_is_unchanged():
    out = ListNotifier()
    d = Digest(out, every_ms=1)
    d.add("[S2_ST_ROC@1h] drawdown 20.4% (level 20%), equity 3980.12")
    assert d.flush(0, force=True) == "알림 모음: 낙폭 1\n[S2_ST_ROC@1h] drawdown 20.4% (level 20%), equity 3980.12"


# ---------------------------------------------------------------- Telegram 429 and bursts of emergencies (M-2)
def _telegram_429(monkeypatch, refuse):
    """urlopen that accepts, except the requests ``refuse(n)`` (n = 1-based request number) answers with a 429
    'retry after' its value in seconds (a JSON body like Telegram's)."""
    import io
    import urllib.error
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_CRITICAL", "111")
    calls, sent = [], []

    class Resp:
        def read(self):
            return b"{}"

    def fake(url, data=None, timeout=None):
        calls.append(urllib.parse.parse_qs(data.decode()))
        wait = refuse(len(calls))
        if wait is not None:
            body = ('{"ok":false,"error_code":429,"parameters":{"retry_after":%d}}' % wait).encode()
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {"Retry-After": str(wait)}, io.BytesIO(body))
        sent.append(calls[-1])
        return Resp()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    return calls, sent


def test_telegram_send_waits_once_on_429_and_never_longer_than_30s(monkeypatch):
    calls, sent = _telegram_429(monkeypatch, lambda n: 7 if n == 1 else None)
    slept = []
    n = TelegramNotifier(sleep=slept.append)
    assert n.send(WARN, "no new closed bars for 245s") is True
    assert slept == [7.0] and len(calls) == 2 and len(sent) == 1
    calls, sent = _telegram_429(monkeypatch, lambda n: 35)          # longer than RETRY_WAIT_MAX_S: no wait
    slept.clear()
    assert n.send(WARN, "no new closed bars for 245s") is False
    assert slept == [] and len(calls) == 1
    calls, sent = _telegram_429(monkeypatch, lambda n: 3)           # refused again after the wait: given up
    assert n.send(WARN, "x") is False and slept == [3.0] and len(calls) == 2


def test_router_bundles_30_liquidations_of_a_step_and_waits_out_a_429_without_sleeping(monkeypatch):
    """Telegram takes about 20 messages a minute in a group: 19 earlier messages, then a gap liquidates 30 accounts
    in one step. The first liquidation goes at once, the other 29 together at the step's end (one loud message,
    every account named); that message gets a 429 (retry after 35 s) and is sent again on a later step once the
    35 s have passed. The trading loop never sleeps."""
    monkeypatch.setattr(notify.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept in the loop")))
    window = {"open": True}
    calls, sent = _telegram_429(monkeypatch, lambda n: None if n <= 20 or not window["open"] else 35)
    tg = TelegramNotifier()
    clk = Clock(T)
    d = Digest(tg)
    r = Router(tg, d, clock=clk)
    for k in range(19):
        r.send(WARN, f"no new closed bars for {200 + k}s")
    books = [f"{name}@15m" for name in list(STRATEGY_KO)[:30]]
    assert len(books) == 30
    for b in books:
        r.send(CRITICAL, f"[{b}] LIQUIDATED SOLUSDT 50x lost margin 2500.00")
    assert len(sent) == 20                                   # 19 + the first liquidation, at once
    d.flush(clk.t)                                           # the step's end: the other 29 in one message -> 429
    assert len(calls) == 21 and len(sent) == 20 and len(r.pending) == 1
    clk.t += 10_000
    d.flush(clk.t)                                           # 10 s later: still waiting, nothing sent
    assert len(calls) == 21
    window["open"] = False                                   # the minute is over: Telegram accepts again
    clk.t += 26_000
    d.flush(clk.t)
    assert len(calls) == 22 and len(sent) == 21 and r.pending == []
    bundle = sent[-1]
    assert bundle["disable_notification"] == ["true"]                    # every message silent (owners 2026-10-05)
    text = bundle["text"][0]
    # T2: the bundle says the step's total, the first liquidation having gone alone
    assert text.startswith("🚨 긴급 29건 · 모의 강제청산 29\n같은 때 모두 30건 (첫 1건은 따로 보냄)\n\n")
    assert text.count("- 강제청산 · ") == 29
    for b in books[1:]:
        assert who(b) in text
    assert who(books[0]) in sent[19]["text"][0]


def test_router_urgent_lines_isolated_go_at_once_and_big_bursts_are_split():
    out = ListNotifier()
    d = Digest(out)
    r = Router(out, d, clock=Clock(T))
    r.send(CRITICAL, "[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 10.00")
    d.flush(T)
    r.send(CRITICAL, "[S2_ST_ROC@1h] LIQUIDATED SOLUSDT 25x lost margin 10.00")
    assert [lv for lv, _ in out.messages] == [CRITICAL, CRITICAL]           # one per step: each at once
    d.flush(T)
    for k in range(101):
        r.send(CRITICAL, f"[RANDOM_{k}@15m] LIQUIDATED BTCUSDT 50x lost margin 10.00")
    d.flush(T)
    msgs = out.messages[2:]
    assert [lv for lv, _ in msgs] == [CRITICAL] * 4                          # 1 at once + 40 + 40 + 20
    assert [m.split("\n")[0] for _, m in msgs[1:]] == ["긴급 알림 40건 · 총 101건", "긴급 알림 40건 · 총 101건",
                                                       "긴급 알림 20건 · 총 101건"]
    lines = [ln for _, m in msgs for ln in m.split("\n") if "LIQUIDATED" in ln]
    assert len(lines) == 101 and len(set(lines)) == 101
    assert len(telegram_text(CRITICAL, msgs[1][1])[1]) < 4096


def test_router_digest_waits_out_a_429_too(monkeypatch):
    monkeypatch.setattr(notify.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept in the loop")))
    calls, sent = _telegram_429(monkeypatch, lambda n: 20 if n == 1 else None)
    tg = TelegramNotifier()
    clk = Clock(T)
    d = Digest(tg, every_ms=1)
    r = Router(tg, d, clock=clk)
    d.flush(clk.t)
    d.add("[RANDOM_2@15m] BUST: bust: equity 8.40 below 10.00")
    d.flush(clk.t + 5)
    assert len(calls) == 1 and sent == [] and len(r.pending) == 1
    clk.t += 21_000
    d.flush(clk.t)
    assert len(sent) == 1 and "파산" in sent[0]["text"][0]


# ---------------------------------------------------------------- paper v4 (owners' D10, plan T3-T7)
def test_v4_accounts_read_as_names_deepseek_reel_and_5m_coin_flips():
    from paperbot import groups as G
    from paperbot.config import DS200_DEFS, DS200_FAMILY, REEL_NAME
    for d, fam, tfs in DS200_DEFS:                                   # every one of the 44 definitions
        for tf in tfs:
            assert who(f"{d}@{tf}") == who(f"{d}@{tf}", kind="ds200") == \
                f"딥시크 {d} ({G.DS_FAMILY_KO[fam]}) {notify.TF_KO[tf]}"
    assert who("F9_FVG@15m") == "딥시크 F9_FVG (FVG·오더 블록) 15분" and DS200_FAMILY["F15_ASIA_BRK"] == "F15"
    assert who("F15_ASIA_BRK@1h") == "딥시크 F15_ASIA_BRK (세션 레인지·시가 편향) 1시간"
    assert who(f"{REEL_NAME}@5m") == who(f"{REEL_NAME}@5m", kind="reel") == G.REEL_KO and "5분" in G.REEL_KO
    assert who("RANDOM_1@5m") == who("RANDOM_1@5m", kind="random") == "동전 봇 1 5분"
    assert who("F9_FVG@15m~c1") == "복제 딥시크 F9_FVG (FVG·오더 블록) 15분"
    assert who("S2_ST_ROC@15m") == f"{S2} 15분"                       # the 36 unchanged
    # a liquidation of any group is loud and says 모의 first
    for book in ("F9_FVG@15m", f"{REEL_NAME}@5m", "RANDOM_1@5m", "S2_ST_ROC@4h"):
        lvl, text = telegram_text(CRITICAL, f"[{book}] LIQUIDATED SOLUSDT 30x lost margin 1500.00")
        assert lvl == CRITICAL and text.startswith(f"🚨 모의 강제청산 · {who(book)}\n")


def test_the_v4_start_line_names_the_run_and_its_split():
    from paperbot.config import V4_ACCOUNTS, V4_GROUP_ACCOUNTS
    assert V4_GROUP_ACCOUNTS == {"core": 144, "ds200": 171, "reel": 1, "flip": 15} and V4_ACCOUNTS == 331
    assert ko(f"paper v4 started: {V4_ACCOUNTS} accounts, brackets: Binance leverageBracket (live), taker fee 0.0500%") == (
        "▶️ 봇 시작 · 모의 v4 · 계좌 331개\n\n새로 시작\n매매법 144 · 딥시크 171 · 5분 단타 1 · 동전 15\n"
        "레버리지 구간: 바이낸스 실시간\n수수료 0.05%\n10/03 21:15")                  # T8: the KST time last
    # resumed with two extra accounts; a split carried by the line itself wins
    assert ko("paper v4 resumed: 333 accounts, brackets: file b.json, taker fee 0.0400%").split("\n")[3] == \
        "매매법 144 · 딥시크 171 · 5분 단타 1 · 동전 15 · 추가 계좌 2"
    assert ko("paper v4 resumed: 333 accounts (core 144, ds200 171, reel 1, flip 15, extra 2), brackets: x, "
              "taker fee 0.04%").split("\n")[:4] == ["▶️ 봇 재시작 · 모의 v4 · 계좌 333개", "", "이어서 돌림",
                                                    "매매법 144 · 딥시크 171 · 5분 단타 1 · 동전 15 · 추가 계좌 2"]
    # fewer accounts than the v4 shape: no made-up split; v3 lines unchanged; never in English
    assert ko("paper v4 started: 12 accounts, brackets: x, taker fee 0.05%") == \
        "▶️ 봇 시작 · 모의 v4 · 계좌 12개\n\n새로 시작\n레버리지 구간: x\n수수료 0.05%\n10/03 21:15"
    assert ko("paper v3 started: 156 accounts, brackets: x, taker fee 0.05%").startswith("▶️ 봇 시작 · 계좌 156개\n")
    assert telegram_text(INFO, "paper v5 resumed: 400 accounts, brackets: x, taker fee 0.05%")[1].startswith(
        "▶️ 봇 재시작 · 모의 v5 · 계좌 400개")


def test_digest_lists_the_36_and_the_reel_and_counts_deepseek_and_coin_flips(monkeypatch):
    """171 DeepSeek drawdown lines no longer push the 36's and the reel's lines out of the 15 listed (plan T6): one
    count line in the record; Telegram lists the 36, the reel and the extras and counts DeepSeek and the coin flips."""
    from paperbot.config import DS200_IDS, REEL_NAME
    sent = _telegram(monkeypatch)
    d = Digest(TelegramNotifier(), every_ms=1)
    d.flush(0)
    for k, ds in enumerate(list(DS200_IDS) * 4):
        d.add(f"[{ds}@{('15m', '30m', '1h', '4h')[k % 4]}] drawdown 20.{k % 10}% (level 20%), equity 3990.00")
    d.add("[F9_FVG@15m] BUST: bust: equity 8.00 below 10.00")
    d.add("[RANDOM_1@5m] drawdown 30.0% (level 30%), equity 3500.00")
    d.add("[S2_ST_ROC@1h] drawdown 40.4% (level 40%), equity 2980.12")
    d.add(f"[{REEL_NAME}@5m] BUST: bust: equity 9.00 below 10.00")
    d.add("[S2_ST_ROC@1h~c1] drawdown 20.0% (level 20%), equity 3999.00")
    text = d.flush(10)
    lines = text.splitlines()
    assert lines[0] == "알림 모음: 낙폭 179 · 파산 2"
    assert lines[1:5] == ["[RANDOM_1@5m] drawdown 30.0% (level 30%), equity 3500.00",       # the record keeps it
                          "[S2_ST_ROC@1h] drawdown 40.4% (level 40%), equity 2980.12",
                          f"[{REEL_NAME}@5m] BUST: bust: equity 9.00 below 10.00",
                          "[S2_ST_ROC@1h~c1] drawdown 20.0% (level 20%), equity 3999.00"]
    # counted as accounts at their deepest line (T1): the 44 ids x 4 lines above fall on 44 books (44 is a multiple
    # of 4, so each id always gets the same timeframe), plus F9_FVG@15m's bust: 45 accounts, not 177 lines
    assert lines[5:] == ["딥시크 계좌 경고 177건 · 계좌 45개: 파산 1 · 낙폭 44 (대시보드 알림 목록)"]
    tg = sent[0]["text"][0]
    assert tg.startswith("📉 파산·낙폭 모음 · 지난 1시간\n\n파산 1건\n- 릴스 5분 단타")
    assert f"- {S2} 1시간 · -40% · 잔고 $2,980" in tg and f"- 복제 {S2} 1시간 · -20%" in tg
    assert tg.endswith("개수만 (계좌별 줄은 대시보드)\n- 딥시크 계좌 45개 · 파산 1 · 낙폭 44\n- 동전 계좌 1개 · 낙폭 1")
    assert "F9_FVG" not in tg and len(tg) < 4096
    assert notify.count_only_group("[F9_FVG@15m] drawdown") == "ds200" and notify.count_only_group("[RANDOM_3@4h] x") == "flip"
    for line in ("[S2_ST_ROC@15m] x", f"[{REEL_NAME}@5m] x", "[F9_FVG@15m~c1] x", "[NL2@15m] x", "gaps", "[extra] x"):
        assert notify.count_only_group(line) is None


def test_digest_coin_flip_lines_never_hide_a_core_or_reel_line_past_the_cut(monkeypatch):
    """Jobs review 3: 15 coin-flip lines first in the hour used to fill the 15 listed places, so the 36's bust and
    the reel's -40% fell into '외 N건'. When the flips would push such a line past the cut they get a count line;
    when nothing would be hidden the record lists them as before (the v3 parity record)."""
    from paperbot.config import DS200_IDS, REEL_NAME
    sent = _telegram(monkeypatch)
    d = Digest(TelegramNotifier(), every_ms=1)
    d.flush(0)
    flips = [f"[RANDOM_{k}@{tf}] drawdown {lv}.5% (level {lv}%), equity {5000 - 10 * lv:.2f}"
             for k in (1, 2, 3) for tf in ("5m", "15m") for lv in (20, 30)] + \
            [f"[RANDOM_{k}@30m] drawdown 20.1% (level 20%), equity 3990.00" for k in (1, 2, 3)]
    assert len(flips) == 15
    for t in flips:
        d.add(t)
    d.add("[RANDOM_1@5m] drawdown 40.2% (level 40%), equity 2990.00")
    d.add("[RANDOM_2@5m] BUST: bust: equity 9.00 below 10.00")
    d.add("[S2_ST_ROC@15m] BUST: bust: equity 8.00 below 10.00")
    d.add(f"[{REEL_NAME}@5m] drawdown 41.0% (level 40%), equity 2950.00")
    d.add(f"[{list(DS200_IDS)[0]}@15m] drawdown 20.0% (level 20%), equity 4000.00")
    text = d.flush(10)
    lines = text.splitlines()
    assert lines[1:3] == ["[S2_ST_ROC@15m] BUST: bust: equity 8.00 below 10.00",
                          f"[{REEL_NAME}@5m] drawdown 41.0% (level 40%), equity 2950.00"]
    assert lines[3:] == ["딥시크 계좌 경고 1건 · 계좌 1개: 낙폭 1 (대시보드 알림 목록)",
                         "동전 계좌 경고 17건 · 계좌 9개: 파산 1 · 낙폭 8 (대시보드 알림 목록)"]
    tg = sent[0]["text"][0]
    assert f"파산 1건\n- {who('S2_ST_ROC@15m')} · 잔고 $8" in tg
    assert f"낙폭 경고 1건\n- {who(REEL_NAME + '@5m')} · -40% · 잔고 $2,950" in tg
    assert tg.endswith("- 딥시크 계좌 1개 · 낙폭 1\n- 동전 계좌 9개 · 파산 1 · 낙폭 8") and "외 " not in tg
    # nothing hidden: the flips stay listed in the record exactly as before
    for t in flips[:3] + ["[S2_ST_ROC@15m] BUST: bust: equity 8.00 below 10.00"]:
        d.add(t)
    assert d.flush(20).splitlines()[1:] == flips[:3] + ["[S2_ST_ROC@15m] BUST: bust: equity 8.00 below 10.00"]
    # more than 15 core lines and no flip in the first 15: the cut and '외 N건' as before
    for k in range(16):
        d.add(f"[S2_ST_ROC@{('15m', '30m', '1h', '4h')[k % 4]}~c{k}] drawdown 20.0% (level 20%), equity 4000.00")
    d.add(flips[0])
    lines = d.flush(30).splitlines()
    assert len(lines) == 17 and lines[-1] == "외 2건 (대시보드 알림 목록)"


def test_digest_lists_an_account_once_at_its_deepest_level(monkeypatch):
    """T1: one step crossing -20% and -30% at the same balance (and a bust after a drawdown) is one line per account
    in Telegram, the deepest; the count-only groups count accounts, not lines."""
    sent = _telegram(monkeypatch)
    d = Digest(TelegramNotifier(), every_ms=1)
    d.flush(0)
    for b in ("S2_ST_ROC@15m", "S2_ST_ROC@1h"):
        d.add(f"[{b}] drawdown 31.2% (level 30%), equity 3478.00")
        d.add(f"[{b}] drawdown 31.2% (level 20%), equity 3478.00")
    d.add("[S2_ST_ROC@30m] drawdown 22.0% (level 20%), equity 3900.00")
    d.add("[S2_ST_ROC@30m] BUST: bust: equity 9.00 below 10.00")
    for lv in (20, 30):
        d.add(f"[RANDOM_1@5m] drawdown 31.0% (level {lv}%), equity 3450.00")
        d.add(f"[RANDOM_2@15m] drawdown 31.0% (level {lv}%), equity 3450.00")
    d.flush(10)
    tg = sent[0]["text"][0]
    assert tg.count(who("S2_ST_ROC@15m")) == 1 and tg.count(who("S2_ST_ROC@1h")) == 1
    assert f"낙폭 경고 2건\n- {who('S2_ST_ROC@15m')} · -30% · 잔고 $3,478\n- {who('S2_ST_ROC@1h')} · -30%" in tg
    assert f"파산 1건\n- {who('S2_ST_ROC@30m')} · 잔고 $9" in tg and "-20%" not in tg
    assert tg.endswith("개수만 (계좌별 줄은 대시보드)\n- 동전 계좌 2개 · 낙폭 2")
    assert notify.group_count(["[F9_FVG@15m] drawdown 31% (level 20%), equity 1", "[F9_FVG@15m] drawdown 31% (level 30%),"
                               " equity 1", "[F9_FVG@30m] BUST: bust: equity 1 below 10", "[F9_FVG@30m] drawdown 20.0% "
                               "(level 20%), equity 4000"]) == (2, "파산 1 · 낙폭 1")


def test_router_bundles_a_120_liquidation_burst_of_every_group_loud(monkeypatch):
    """A gap that liquidates 120 accounts of every group in one step (plan T7): the first at once, the other 119 in
    3 loud bundles (40 lines each at most), every account named, each bundle's first line saying 모의, each under
    Telegram's 4,096 characters."""
    from paperbot.config import DS200_IDS, REEL_NAME
    monkeypatch.setattr(notify.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept in the loop")))
    calls, sent = _telegram_429(monkeypatch, lambda n: None)
    tg = TelegramNotifier()
    d = Digest(tg)
    r = Router(tg, d, clock=Clock(T))
    books = ([f"{x}@15m" for x in list(STRATEGY_KO)[:36]] + [f"{x}@30m" for x in DS200_IDS]
             + [f"{x}@1h" for x in list(DS200_IDS)[:35]] + [f"{REEL_NAME}@5m"] + [f"RANDOM_{k}@5m" for k in (1, 2, 3)]
             + [f"RANDOM_{k}@{tf}" for k in (1,) for tf in ("15m",)])
    assert len(books) == 120
    for b in books:
        r.send(CRITICAL, f"[{b}] LIQUIDATED BTCUSDT 30x lost margin 1500.00")
    d.flush(T)
    texts = [s["text"][0] for s in sent]
    assert len(texts) == 4 and all(s["disable_notification"] == ["true"] for s in sent)   # silent (owners 2026-10-05)
    assert texts[0].startswith("🚨 모의 강제청산 · ")
    assert [t.split("\n")[0] for t in texts[1:]] == ["🚨 긴급 40건 · 모의 강제청산 40", "🚨 긴급 40건 · 모의 강제청산 40",
                                                     "🚨 긴급 39건 · 모의 강제청산 39"]
    assert all(t.split("\n")[1] == "같은 때 모두 120건 (첫 1건은 따로 보냄)" for t in texts[1:])
    assert sum(t.count("\n- 강제청산 · ") for t in texts[1:]) == 119 and max(len(t) for t in texts) < 4096
    for b in books:
        assert any(who(b) in t for t in texts)


def test_no_v3_shape_numbers_in_the_telegram_texts():
    """Restart-path text (plan P13 grep rule): the counts come from the database or the run shape, never 156 / 144
    in a string the code sends (docstrings and comments may quote examples)."""
    import ast
    import os
    import re as _re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ("paperbot/notify.py", "paperbot/tradealerts.py", "paperbot/failalert.py"):
        src = open(os.path.join(root, rel), encoding="utf-8").read()
        tree = ast.parse(src)
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        texts = [n.value for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
        assert texts and not [t for t in texts if _re.search(r"\b(156|144)\b", t)], rel
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value in (156, 144)], rel
        assert "V3_ACCOUNTS" not in src, rel


# ---------------------------------------------------------------- gap pass: DeepSeek timeouts (G27), send counter (G13)
def test_group_patterns_equal_the_frozen_sigservice_texts():
    """notify's copies of the v4 group patterns are sigservice's (the frozen texts, a trading file): a changed text
    fails here, not silently in the digest; the frozen texts themselves match them."""
    from paperbot import sigservice as SS
    for name, pat in notify.GROUP_PATTERNS.items():
        assert getattr(SS, name) == pat, name
        assert notify.group_pattern(name).pattern == pat
    import re
    texts = {"DS_TIMEOUT_RE": SS.DS_TIMEOUT_TEXT.format(secs="60", boundary=T, tfs="15m, 30m"),
             "DS_FAILED_RE": SS.DS_FAILED_TEXT.format(boundary=T, error="ValueError: x"),
             "REEL_FAILED_RE": SS.REEL_FAILED_TEXT.format(boundary=T, error="ReelError: y"),
             "REFUSED_RE": SS.REFUSED_TEXT.format(group="ds200", why="pin mismatch lib_c.py")}
    for name, text in texts.items():
        assert re.match(notify.GROUP_PATTERNS[name], text), (name, text)
    # Korean wording; none of them is read as the core group's timeout
    assert ko(texts["DS_TIMEOUT_RE"]) == ("딥시크 신호 건너뜀 · 09:00 봉\n\n딥시크 신호 계산이 60초 안에 안 끝남\n"
                                         "건너뛴 봉: 15분, 30분\n매매법·5분 단타 신호는 정상 · 봇은 계속 돎")
    assert ko(texts["DS_FAILED_RE"]).startswith("딥시크 신호 실패 · 09:00 봉\n\n오류: ValueError: x\n")
    assert ko(texts["REEL_FAILED_RE"]).startswith("5분 단타 신호 실패 · 09:00 봉\n")
    assert ko(texts["REFUSED_RE"]).startswith("딥시크 신호 코드 거부 · 이 무리 신호 멈춤\n\n이유: pin mismatch lib_c.py")
    assert not notify._TIMEOUT.match(texts["DS_TIMEOUT_RE"])


def test_router_counts_deepseek_timeouts_in_the_digest_and_rings_once_a_day_past_the_threshold():
    from paperbot import sigservice as SS
    out = ListNotifier()
    d = Digest(out)
    clk = Clock(T)
    r = Router(out, d, clock=clk)

    def ds(t):
        return SS.DS_TIMEOUT_TEXT.format(secs="60", boundary=t, tfs="15m, 30m")
    for k in range(Router.DS_TIMEOUT_LOUD - 1):
        clk.t = T + k * 900_000
        assert r.send(WARN, ds(clk.t)) is None
    assert out.messages == [] and r.timeouts == 0 and r.last_timeout is None      # the 36's timeout rule untouched
    # T5: the bar's time and timeframe together, then the seconds; the same 'not affected' words as the WARN
    assert d.notes["ds_timeouts"] == (f"딥시크 신호 건너뜀 {Router.DS_TIMEOUT_LOUD - 1}번 (마지막 11:30 · 15분·30분봉 · "
                                      "60초 안에 계산 못 끝냄 · 매매법·5분 단타 신호는 정상)")
    clk.t += 900_000
    r.send(WARN, ds(clk.t))
    assert [lv for lv, _ in out.messages] == [WARN]
    assert out.messages[0][1].startswith(f"딥시크 신호 건너뜀 많음 · 오늘 {Router.DS_TIMEOUT_LOUD}번\n\n"
                                         "마지막 11:45 · 15분·30분봉 · 60초 안에 계산 못 끝냄\n매매법·5분 단타 신호는 정상")
    for k in range(5):
        r.send(WARN, ds(clk.t))
    assert len(out.messages) == 1                                                 # once a KST day
    d.flush(clk.t, force=True)
    assert "딥시크 신호 건너뜀 17번" in out.messages[-1][1] and "ds_timeouts" not in d.notes
    r.send(WARN, ds(clk.t))
    assert d.notes["ds_timeouts"].startswith("딥시크 신호 건너뜀 1번")              # counted afresh after the digest
    clk.t = T + 86_400_000
    for k in range(Router.DS_TIMEOUT_LOUD):
        r.send(WARN, ds(clk.t))
    assert len(out.messages) == 3                                                 # the next KST day: once more
    # the core group's timeout still rings first as before
    r.send(WARN, f"signal workers did not answer within 120s; signals skipped at {clk.t} for 15m")
    assert len(out.messages) == 4 and r.timeouts == 0 and r.last_timeout == clk.t


def test_every_accepted_telegram_message_is_counted_and_the_count_never_fails_a_send(monkeypatch, tmp_path):
    import sqlite3
    db = tmp_path / "tgsends.db"
    monkeypatch.setenv("PAPERBOT_TG_SENDS_DB", str(db))
    calls, sent = _telegram_429(monkeypatch, lambda n: 7 if n == 1 else None)
    n = TelegramNotifier(sleep=lambda s: None)
    assert n.send(WARN, "no new closed bars for 245s") is True                    # refused once, then accepted
    assert n.send(INFO, "📈 모의 진입") is True
    assert n.send(CRITICAL, "[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 10.00") is True
    c = sqlite3.connect(str(db))
    assert sorted(c.execute("SELECT day, kind, n FROM tg_sends")) == [
        ("2026-10-03", "CRITICAL", 1), ("2026-10-03", "INFO", 1), ("2026-10-03", "WARN", 1)]
    n.send(INFO, "x")
    assert c.execute("SELECT n FROM tg_sends WHERE kind = 'INFO'").fetchone() == (2,)
    # the dashboard's query (paperbot/dash/app.py telegram_counts) on this table
    assert c.execute("SELECT COALESCE(SUM(n), 0) FROM tg_sends WHERE day = ?", ("2026-10-03",)).fetchone() == (4,)
    c.close()
    # a counter that cannot be written (a locked table, a missing folder) never fails or delays the send
    lock = sqlite3.connect(str(db))
    lock.execute("BEGIN EXCLUSIVE")
    assert n.send(INFO, "y") is True and notify.count_send("INFO") is False
    lock.rollback()
    lock.close()
    monkeypatch.setenv("PAPERBOT_TG_SENDS_DB", str(tmp_path / "missing" / "tgsends.db"))
    assert n.send(INFO, "z") is True and notify.count_send("INFO") is False
    monkeypatch.delenv("PAPERBOT_TG_SENDS_DB")
    assert notify.tg_sends_path() is None                        # the autouse fixture: no default folder in tests
    # the place and the schema the dashboard reads (dash/app.py TG_SENDS_FILE next to paper3.db), never paper3.db
    import os
    from paperbot.dash import app as dash_app
    assert os.path.basename(TG_SENDS_DEFAULT) == dash_app.TG_SENDS_FILE == "tgsends.db"
    assert os.path.dirname(TG_SENDS_DEFAULT) == "/var/lib/paperbot" and "paper3" not in TG_SENDS_DEFAULT
    cols = sqlite3.connect(str(db)).execute("PRAGMA table_info(tg_sends)").fetchall()
    assert [(c[1], c[2], c[5]) for c in cols] == [("day", "TEXT", 1), ("kind", "TEXT", 2), ("n", "INTEGER", 0)]


def test_telegram_text_points_at_the_v4_dashboard_places():
    """A5: the v3 tab names some senders still write (checkpoint.py is pinned, so its verdict text is rewritten here)
    become the v4 UI's places."""
    from paperbot import notify as N
    _lvl, t = N.telegram_text("INFO", "30일 판정\n\n자세히: 대시보드 순위표 '체크포인트 판정'")
    assert t.endswith("자세히: 대시보드 홈 › 판정") and "체크포인트 판정'" not in t
    _lvl, t = N.telegram_text("INFO", "청산 3건\n외 2건 — 대시보드 '오늘 체결'")
    assert "대시보드 '거래 › 포지션 › 체결 기록'" in t and "오늘 체결" not in t
    for old, _new in N.V4_POINTERS:
        assert old not in N.telegram_text("WARN", "x " + old)[1]
