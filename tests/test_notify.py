"""The Telegram text of alerts (paperbot/notify.py): the engine's and the feed's English lines reach the owners in
Korean, with the Korean strategy names and KST times, and a level mark instead of '[WARN]'."""
import urllib.parse

from paperbot import notify
from paperbot.agents.roster3 import STRATEGY_KO
from paperbot.notify import CRITICAL, INFO, WARN, Digest, TelegramNotifier, ko

T = 1790985600000          # 2026-10-03 00:00 UTC = 09:00 KST


def test_known_english_alert_lines_read_in_korean():
    s2 = STRATEGY_KO["S2_ST_ROC"]
    assert ko("[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 123.45") == \
        f"{s2} · 15분 강제청산: SOL 25배, 증거금 $123.45 손실"
    assert ko("[RANDOM_2@5m] BUST: bust: equity 9.50 below 10.00") == "동전 봇 2 · 5분 파산: 잔고 $9.50 ($10.00 미만), 계좌 정지"
    assert ko("[S2_ST_ROC@1h] drawdown 31.0% (level 30%), equity 3450.00") == \
        f"{s2} · 1시간 낙폭 31.0% (30% 경고선), 잔고 $3450.00"
    assert ko(f"signal workers did not answer within 120s; signals skipped at {T} for 5m, 15m") == \
        "신호 계산이 120초 안에 끝나지 않아 10/03 09:00(한국) 봉 신호를 건너뜀: 5분, 15분. 계산 프로세스를 새로 띄우고 봇은 계속 돕니다"
    assert ko(f"data gap at {T}: no bar for ['BTCUSDT', 'ETHUSDT']") == "1분봉 빠짐 10/03 09:00(한국): BTC, ETH. 그 코인은 그 1분을 건너뜀"
    assert ko(f"DOGEUSDT: exchange returned no bars for 3 min from {T}") == "DOGE: 바이낸스가 10/03 09:00(한국)부터 3분 동안 1분봉을 주지 않음"
    assert ko("no new closed bars for 312s") == "새 1분봉이 312초째 들어오지 않음"
    # anything else (the agents' and the backup's Korean texts, an unknown line) goes out unchanged
    for t in ("[에이전트 알림] 직원 회의가 멈췄습니다", "[extra] boundary hook failed (X)", "[NEW@15m] LIQUIDATED x"):
        assert ko(t) == t
    # a wording helper never stops an alert: a line it cannot word is sent as it came
    odd = "signal workers did not answer within 120s; signals skipped at 99999999999999999999999 for 5m"
    assert ko(odd) == odd


def test_telegram_text_has_a_level_mark_and_korean_wording(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_CRITICAL", "111")
    sent = []

    class Resp:
        def read(self):
            return b"{}"

    def urlopen(url, data=None, timeout=None):
        sent.append(urllib.parse.parse_qs(data.decode()))
        return Resp()
    monkeypatch.setattr(notify.urllib.request, "urlopen", urlopen)
    n = TelegramNotifier()
    assert n.send(CRITICAL, "[S2_ST_ROC@15m] LIQUIDATED SOLUSDT 25x lost margin 123.45") is True
    assert n.send(WARN, f"data gap at {T}: no bar for ['BTCUSDT']") is True
    assert n.send(INFO, "📊 주간 성적표") is True
    texts = [d["text"][0] for d in sent]
    assert texts[0] == f"🚨 {STRATEGY_KO['S2_ST_ROC']} · 15분 강제청산: SOL 25배, 증거금 $123.45 손실"
    assert texts[1] == "⚠ 1분봉 빠짐 10/03 09:00(한국): BTC. 그 코인은 그 1분을 건너뜀"
    assert texts[2] == "📊 주간 성적표"                         # silent, and no '[INFO]' in front
    assert [d["disable_notification"][0] for d in sent] == ["false", "false", "true"]


def test_digest_reaches_telegram_in_korean_and_points_to_the_alert_screen(monkeypatch):
    """The Digest's own text stays as it is (the stored record, tests/test_extras_parity.py's golden); its lines are
    worded at the Telegram edge, one by one, the pointer too (extras.py writes the same pointer)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_CRITICAL", "111")
    sent = []

    class Resp:
        def read(self):
            return b"{}"
    monkeypatch.setattr(notify.urllib.request, "urlopen",
                        lambda url, data=None, timeout=None: sent.append(urllib.parse.parse_qs(data.decode())) or Resp())
    d = Digest(TelegramNotifier(), every_ms=1, max_lines=1)
    d.flush(0)
    d.add("[S2_ST_ROC@1h] drawdown 31.0% (level 30%), equity 3450.00")
    d.add("[RANDOM_2@5m] BUST: bust: equity 9.50 below 10.00")
    text = d.flush(10)
    assert text.splitlines() == ["알림 모음: 낙폭 1 · 파산 1", "[S2_ST_ROC@1h] drawdown 31.0% (level 30%), equity 3450.00",
                                 "외 1건 (대시보드 알림 목록)"]
    assert sent[0]["text"][0].splitlines() == [
        "알림 모음: 낙폭 1 · 파산 1", f"{STRATEGY_KO['S2_ST_ROC']} · 1시간 낙폭 31.0% (30% 경고선), 잔고 $3450.00",
        "외 1건 (대시보드 '서버 상태 → 경고')"]
    assert sent[0]["disable_notification"] == ["true"]
