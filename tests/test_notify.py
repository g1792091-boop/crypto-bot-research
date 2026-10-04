"""The Telegram text of alerts (paperbot/notify.py; owners' layout 2026-10-04): the engine's, the feed's and the
runner's English lines reach the owners in Korean (a title '<what> · <whom>', short lines, the KST time), one emoji
first, the copies and new-strategy accounts by name, and the noisy operational lines held for the silent digest."""
import urllib.parse

import pytest

from paperbot import notify
from paperbot.agents.roster3 import STRATEGY_KO
from paperbot.notify import (CRITICAL, INFO, WARN, Digest, ListNotifier, Router, TelegramNotifier, ko, money, render,
                             telegram_text, usd, who)

T = 1790985600000          # 2026-10-03 00:00 UTC = 09:00 KST
S2 = STRATEGY_KO["S2_ST_ROC"]


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setattr(notify, "_clock", lambda: (T + 12 * 3_600_000 + 15 * 60_000) / 1000)   # 10/03 21:15 KST


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
        f"강제청산 · {S2} 15분\n\nSOL 25배\n증거금 $1,500 전액 손실\n10/03 21:15"       # never '$1500.00'
    assert ko("[S2_ST_ROC@1h~c1] LIQUIDATED SOLUSDT 15x lost margin 610.00").startswith(f"강제청산 · 복제 {S2} 1시간\n")
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
        "추가 계좌 코드 오류\n\n추가 계좌가 저장된 상태로 멈춤\n원래 계좌 156개는 그대로 돎\n오류: ImportError (newlab_live)"
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
    assert telegram_text(CRITICAL, "[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 10.00")[1].startswith("🚨 강제청산 · ")
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
    assert lvl == CRITICAL and text == (f"🚨 추가 계좌 긴급 2건\n\n- 강제청산 · 복제 {S2} 1시간 · SOL 15배 · -$610\n"
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
    assert texts[0] == f"🚨 강제청산 · {S2} 15분\n\nSOL 25배\n증거금 $123 전액 손실\n10/03 21:15"
    assert texts[1] == "⚠ 1분봉 빠짐 · 09:00\n\nBTC\n그 코인은 그 1분을 건너뜀"
    assert texts[2] == "📊 주간 성적표"                         # silent, and no '[INFO]' in front
    assert [d["disable_notification"][0] for d in sent] == ["false", "false", "true", "true"]


def test_digest_text_stays_the_record_and_reaches_telegram_grouped(monkeypatch):
    """The Digest's own text stays as it is (the stored record, tests/test_extras_parity.py's golden); Telegram gets
    it regrouped: busts, drawdowns by level, whole dollars, the pointer to the alert screen."""
    sent = _telegram(monkeypatch)
    d = Digest(TelegramNotifier(), every_ms=1, max_lines=3)
    d.flush(0)
    d.add("[S2_ST_ROC@1h] drawdown 20.4% (level 20%), equity 3980.12")
    d.add("[RANDOM_2@15m] BUST: bust: equity 8.40 below 10.00")
    d.add("[N07_ICHI_CMO@4h] drawdown 40.2% (level 40%), equity 2990.80")
    d.add("[S2_ST_ROC@4h] drawdown 30.1% (level 30%), equity 3495.55")
    text = d.flush(10)
    assert text.splitlines() == ["알림 모음: 낙폭 3 · 파산 1", "[S2_ST_ROC@1h] drawdown 20.4% (level 20%), equity 3980.12",
                                 "[RANDOM_2@15m] BUST: bust: equity 8.40 below 10.00",
                                 "[N07_ICHI_CMO@4h] drawdown 40.2% (level 40%), equity 2990.80", "외 1건 (대시보드 알림 목록)"]
    assert sent[0]["text"][0] == (
        "📉 파산·낙폭 모음 · 지난 1시간\n\n파산 1건\n- 동전 봇 2 15분 · 잔고 $8 (파산선 $10)\n\n낙폭 경고 2건\n"
        f"- {STRATEGY_KO['N07_ICHI_CMO']} 4시간 · -40% · 잔고 $2,991\n- {S2} 1시간 · -20% · 잔고 $3,980\n\n"
        "외 1건 (대시보드 '서버 상태 → 경고')")
    assert sent[0]["disable_notification"] == ["true"]


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
                    "운영 메모 2건 (대시보드 '서버 상태 → 경고')")
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
    assert bundle["disable_notification"] == ["false"]                   # CRITICAL stays loud
    text = bundle["text"][0]
    assert text.startswith("🚨 긴급 29건\n\n") and text.count("- 강제청산 · ") == 29
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
    assert [m.split("\n")[0] for _, m in msgs[1:]] == ["긴급 알림 40건", "긴급 알림 40건", "긴급 알림 20건"]
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
