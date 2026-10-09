"""Demo lab bot Telegram (demobot/notify.py) and its server kit (deploy/demobot/, docs/demobot/INSTALL_KO.md).

render(): every kind of CONTRACT.md section 5 in Korean, coin names without the quote, one emoji at most and only at
the start, under Telegram's 4096 characters even with 200 trades. Outbox: queue / flush order, limit, pacing, errors
kept and retried, giving up after 5 tries, warn at most once per 'what' an hour, never raising, the token never
stored. The deploy kit statically: the units' sandbox lines, nothing of the rule bot touched, no env file printed."""
import io
import json
import re
import shutil
import sqlite3
import subprocess
import unicodedata
import urllib.error
from pathlib import Path

import pytest

from demobot import notify as N

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "deploy" / "demobot"
DOC = REPO / "docs" / "demobot" / "INSTALL_KO.md"
T0 = 1_791_590_400_000          # 2026-10-10 00:00 UTC = 09:00 KST
TOKEN = "9" * 10 + ":" + "TESTONLY" * 5          # token-shaped, built here (no literal token in the repo)


def trade(i=0, closed=False, coin="BTCUSD", side=1):
    t = {"account": f"ad-r26-S2-15m-{i}", "name": "S2 자동 · 5거래마다(26주) · 15분", "coin": coin, "side": side,
         "entry": 62345.12, "exit": None, "reason": None, "setting_ko": "ST 14/2 ROC 50",
         "exit_ko": "사다리(규칙봇 방식)", "pnl_by_L": None, "R": None}
    if closed:
        t.update({"name": "S2 친구 값 · 15분", "coin": "DOGEUSD", "side": -1, "entry": 0.21345, "exit": 0.20871,
                  "reason": "lock", "setting_ko": "ST 8/3 ROC 37", "exit_ko": "익절 1.5R · 손절 2ATR",
                  "pnl_by_L": {"20": 12.3, "30": 18.45, "40": 24.6, "50": -30.75}, "R": 1.5})
    return t


DAILY = {"day": "2026-10-10", "live_days": 3.25, "trades_24h": 57,
         "best": [{"id": "fx-fr-S2-15m", "name": "S2 친구 값 · 15분", "L": 50, "pnl_pct": 12.34, "pnl": 123.4}],
         "worst": [{"id": "cf-15m", "name": "동전 던지기 · 15분", "L": 50, "pnl_pct": -45.6}],
         "by_kind": [{"kind": "fixed", "kind_ko": "고정", "mean_pnl_pct": {"20": 1.2, "30": 1.8, "40": 2.3, "50": -2.9}},
                     {"kind": "flip", "mean_pnl_pct": {"20": -1.0, "30": -1.5, "40": -2.0, "50": -2.5}}],
         "passed": 0,
         "leaders": [{"strategy": "S2_ST_ROC", "tf": "15m", "window": "26w", "exit": "house",
                      "label": "ST 20/2 ROC 50", "n": 312, "mean_R": 0.051, "win_rate": 0.41, "luck95": 0.03,
                      "beats_luck": True},
                     {"strategy": "N04_ST_KLINGER", "tf": "30m", "window": "4w", "exit": "tp1.5R_sl2atr",
                      "label": "ST 8/3 KVOx1 sig 13", "n": 120, "mean_R": 0.02, "win_rate": 0.5, "luck95": 0.06,
                      "beats_luck": False}]}
SWITCH = {"account": "fr-S2-15m", "name": "S2 친구 규칙 · 15분", "items": [
    {"coin": "ALL", "L": None, "from_ko": "ST 10/6 ROC 9", "to_ko": "ST 20/2 ROC 50",
     "why_ko": "최근 26주 주변 평균 1등 (-0.05R, 1,234건)"},
    {"coin": "BTCUSD", "L": 20, "from_ko": "ST 10/6 ROC 9", "to_ko": "ST 8/3 ROC 37", "why_ko": "26주 수익 + 낙폭 최소"}]}
PASS = {"account": "fx-fr-S2-15m", "name": "S2 친구 값 · 15분", "L": 20,
        "checks": [{"name_ko": "실시간 거래 100건 이상", "ok": True, "value_ko": "134건"},
                   {"name_ko": "운 기준 넘음", "ok": True, "value_ko": "+0.08R"}]}
SAMPLES = {
    "start": {"phase": "live", "accounts": 48, "live_start_ms": T0},
    "tick": {"bar_ms": T0, "opens": [trade(0), trade(1, coin="ETHUSD", side=-1)], "closes": [trade(2, closed=True)]},
    "switch": SWITCH, "daily": DAILY, "warn": {"what": "data", "detail_ko": "15분봉 2개 빠짐 (BTC, ETH)"},
    "pass": PASS}


def emoji_ok(text: str) -> bool:
    """At most one emoji, and only at the very start of the message."""
    return not any(unicodedata.category(c) == "So" or ord(c) >= 0x1F000 for c in text[3:])


# ---------------------------------------------------------------- render
def test_every_kind_is_korean_short_and_has_one_emoji_at_most_at_the_start():
    for kind, payload in SAMPLES.items():
        text = N.render(kind, payload, now_ms=T0)
        assert text and len(text) < 4096, kind
        assert re.search(r"[가-힣]", text.split("\n")[0]), kind          # the first line says what happened, in Korean
        assert emoji_ok(text), (kind, text)
        assert "USD" not in text and TOKEN not in text, kind


def test_tick_bundles_entries_and_exits_one_line_each():
    text = N.render("tick", SAMPLES["tick"])
    lines = text.split("\n")
    assert lines[0] == "🧪 데모 랩 모의 거래 · 진입 2 · 청산 1"
    assert lines[1] == "10/10 09:00 봉"                                   # KST
    opens = [ln for ln in lines if ln.startswith("- ") and "→" not in ln]
    closes = [ln for ln in lines if ln.startswith("- ") and "→" in ln]
    assert len(opens) == 2 and len(closes) == 1
    assert "BTC 롱 62,345.1" in opens[0] and "ETH 숏" in opens[1] and "ST 14/2 ROC 50" in opens[0]
    assert "사다리(규칙봇 방식)" in opens[0]
    c = closes[0]
    assert c.startswith("- S2 친구 값 · 15분: DOGE 숏 0.21345 → 0.20871 잠금 익절 +1.50R")
    assert "20배 +$12.30 · 30배 +$18.45 · 40배 +$24.60 · 50배 -$30.75" in c
    assert "ST 8/3 ROC 37" in c and "익절 1.5R · 손절 2ATR" in c


@pytest.mark.parametrize("reason,ko", [("stop", "손절"), ("lock", "잠금 익절"), ("liq", "강제청산"), ("tp", "익절"),
                                       ("time", "시간 청산")])
def test_exit_reasons_in_korean(reason, ko):
    t = dict(trade(closed=True), reason=reason)
    assert f" {ko} " in N.render("tick", {"bar_ms": T0, "opens": [], "closes": [t]})


def test_tick_with_200_trades_is_cut_below_the_limit_and_says_how_many_are_left():
    text = N.render("tick", {"bar_ms": T0, "opens": [trade(i) for i in range(100)],
                             "closes": [trade(i, closed=True) for i in range(100)]})
    assert len(text) < 4096
    assert text.split("\n")[0].endswith("진입 100 · 청산 100")
    shown = sum(1 for ln in text.split("\n") if ln.startswith("- "))
    m = re.search(r"외 (\d+)건은 대시보드에서$", text)
    assert m and shown + int(m[1]) == 200 and shown >= 10
    assert "\n진입 100\n" in text and "\n청산 100\n" in text           # both sections get room


def test_tick_without_trades_is_empty_and_one_huge_line_is_clipped():
    assert N.render("tick", {"bar_ms": T0, "opens": [], "closes": []}) == ""
    t = dict(trade(), setting_ko="x" * 10_000)
    assert len(N.render("tick", {"bar_ms": T0, "opens": [t] * 20, "closes": []})) < 4096


def test_start_switch_warn_pass():
    warm = N.render("start", {"phase": "warm", "accounts": 48, "live_start_ms": 0})
    assert warm.startswith("▶️ 데모 랩 시작 · 준비 중") and "주문 없음" in warm
    live = N.render("start", SAMPLES["start"], now_ms=T0 + 86_400_000)
    assert live.startswith("▶️ 데모 랩 시작 · 계좌 48개") and "이어서 돌림 · 실시간 시작 10/10 09:00" in live
    sw = N.render("switch", SWITCH, now_ms=T0)
    assert sw.startswith("🔁 설정 바꿈 · S2 친구 규칙 · 15분")
    assert "- 전체 코인: ST 10/6 ROC 9 → ST 20/2 ROC 50 · 최근 26주" in sw and "- BTC 20배: " in sw
    for what, ko in N.WARN_KO.items():
        w = N.render("warn", {"what": what, "detail_ko": "자세히"}, now_ms=T0)
        assert w.startswith(f"⚠ 데모 랩 경고 · {ko}") and "자세히" in w and w.endswith("10/10 09:00")
    p = N.render("pass", PASS, now_ms=T0)
    assert p.startswith("🏁 우리 기준 통과 · S2 친구 값 · 15분 20배")
    assert "- 실시간 거래 100건 이상: 134건 (충족)" in p and "실제 돈을 쓸지는 두 분이 정합니다" in p


def test_daily_summary():
    d = N.render("daily", DAILY)
    lines = d.split("\n")
    assert lines[0] == "📋 데모 랩 하루 요약 · 10/10" and lines[1] == "실시간 3.2일째 · 지난 24시간 거래 57건"
    assert "- S2 친구 값 · 15분 50배 +12.3% (+$123.40)" in d and "- 동전 던지기 · 15분 50배 -45.6%" in d
    assert "- 고정 20배 +1.2% · 30배 +1.8% · 40배 +2.3% · 50배 -2.9%" in d and "- 동전 던지기 20배 -1.0%" in d
    assert ("- S2 15분 (26주): ST 20/2 ROC 50 · 사다리(규칙봇 방식) · +0.05R · 승률 41% · 312건 · "
            "운 기준 +0.03R → 운보다 나음") in d
    assert "N04 30분 (4주): ST 8/3 KVOx1 sig 13 · 익절 1.5R · 손절 2ATR" in d and "운과 구별 안 됨" in d
    assert lines[-2:] == ["우리 기준 통과 0개", "통과 전에는 실제 돈 금지"]
    d2 = N.render("daily", dict(DAILY, passed=2))
    assert "우리 기준 통과 2개 (실제 돈은 두 분이 정합니다)" in d2 and d2.endswith("통과 전에는 실제 돈 금지")


@pytest.mark.parametrize("kind", list(SAMPLES) + ["other"])
@pytest.mark.parametrize("payload", [None, {}, {"opens": "x", "closes": [None, 3], "items": [1], "best": [None],
                                                 "checks": "?", "L": "abc", "bar_ms": "?", "live_days": float("nan")}])
def test_render_never_raises(kind, payload):
    out = N.render(kind, payload)
    assert isinstance(out, str) and len(out) < 4096


def test_helpers():
    assert N.coin("BTCUSD") == "BTC" and N.coin("DOGEUSDT") == "DOGE" and N.coin("ALL") == "전체 코인"
    assert N.px(62345.12) == "62,345.1" and N.px(0.21345) == "0.21345" and N.px(None) == "-"
    assert N.usd(-5.1) == "-$5.10" and N.usd(1234.5) == "+$1,234.50"
    assert N.exit_label("tp1.5R_sl2atr") == "익절 1.5R · 손절 2ATR" and N.exit_label(0) == "사다리(규칙봇 방식)"
    assert N.rate(0.415) == "42%" and N.rate(41.5) == "42%"


# ---------------------------------------------------------------- outbox
class Clock:
    def __init__(self, t_ms=T0):
        self.t = t_ms / 1000

    def time(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s

    def advance(self, s):
        self.t += s

    slept: list


def box(conn=None, clock=None):
    clock = clock or Clock()
    clock.slept = []
    conn = conn or sqlite3.connect(":memory:")
    return N.Outbox(conn, clock=clock.time, sleep=clock.sleep, monotonic=clock.time), conn, clock


class Sender:
    def __init__(self, fail=None):
        self.sent, self.fail, self.calls = [], fail, 0

    def __call__(self, token, chat, text):
        self.calls += 1
        if self.fail:
            f = self.fail(self.calls) if callable(self.fail) else self.fail
            if f is not None:
                raise f
        self.sent.append((token, chat, text))


def rows(conn):
    return conn.execute("SELECT id, kind, sent_ms, tries, error FROM outbox ORDER BY id").fetchall()


def test_queue_stores_the_rendered_text_and_flush_sends_in_order_paced():
    ob, conn, clk = box()
    for i in range(3):
        ob.queue("warn", {"what": f"w{i}", "detail_ko": f"#{i}"})
    ob.queue("tick", {"bar_ms": T0, "opens": [], "closes": []})          # nothing happened: not stored
    stored = conn.execute("SELECT text, payload FROM outbox ORDER BY id").fetchall()
    assert len(stored) == 3 and stored[0][0] == N.render("warn", {"what": "w0", "detail_ko": "#0"}, now_ms=T0)
    assert json.loads(stored[0][1])["what"] == "w0"
    s = Sender()
    assert ob.flush(TOKEN, "-100123", send=s) == 3
    assert [t.split("\n")[1] for _, _, t in s.sent] == ["#0", "#1", "#2"]
    assert all(r[2] is not None for r in rows(conn))
    assert clk.slept and all(x <= 1.0 for x in clk.slept) and sum(clk.slept) >= 2.0     # 1 a second
    st = ob.state()
    assert st == {"configured": True, "queued": 0, "last_ok_ms": st["last_ok_ms"], "last_error": None}
    assert st["last_ok_ms"] >= T0


def test_flush_respects_the_limit_and_the_minute_budget():
    ob, conn, clk = box()
    for i in range(30):
        ob.queue("warn", {"what": f"w{i}"})
    s = Sender()
    assert ob.flush(TOKEN, "c", limit=2, send=s) == 2
    assert ob.flush(TOKEN, "c", limit=30, send=s) == N.PER_MINUTE - 2      # about 20 a minute per group
    clk.advance(61)
    assert ob.flush(TOKEN, "c", limit=30, send=s) == 30 - N.PER_MINUTE
    assert len(s.sent) == 30 and ob.state()["queued"] == 0


def test_not_configured_sends_nothing_and_keeps_the_queue(monkeypatch):
    monkeypatch.delenv("DEMOBOT_TG_TOKEN", raising=False)
    monkeypatch.delenv("DEMOBOT_TG_CHAT", raising=False)
    ob, conn, _ = box()
    assert ob.state()["configured"] is False
    ob.queue("start", SAMPLES["start"])
    s = Sender()
    assert ob.flush("", "", send=s) == 0 and ob.flush(TOKEN, " ", send=s) == 0 and s.calls == 0
    assert ob.state()["queued"] == 1 and ob.state()["configured"] is False


def test_error_is_kept_and_retried_after_a_pause():
    ob, conn, clk = box()
    ob.queue("start", SAMPLES["start"])
    ob.queue("warn", {"what": "data"})
    s = Sender(fail=lambda n: RuntimeError("boom") if n == 1 else None)
    assert ob.flush(TOKEN, "c", send=s) == 0                          # first try failed: stops, never raises
    r = rows(conn)[0]
    assert r[2] is None and r[3] == 1 and r[4] == "RuntimeError: boom"
    assert ob.state()["last_error"] == "RuntimeError: boom" and ob.state()["queued"] == 2
    assert ob.flush(TOKEN, "c", send=s) == 0 and s.calls == 1          # paused (30 s)
    clk.advance(N.BACKOFF_S + 1)
    assert ob.flush(TOKEN, "c", send=s) == 2                          # same order: the failed one first
    assert "▶️" in s.sent[0][2] and rows(conn)[0][4] == "RuntimeError: boom"     # the error stays on the row
    assert ob.state()["last_error"] is None


def test_gives_up_a_row_after_5_refusals_and_moves_on():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data"})
    ob.queue("warn", {"what": "disk"})
    s = Sender(fail=lambda n: N.TelegramError("HTTP 400: Bad Request: message is too long") if n <= 5 else None)
    for _ in range(5):
        assert ob.flush(TOKEN, "c", send=s) == 0
        clk.advance(N.BACKOFF_MAX_S + 1)
    assert rows(conn)[0][3] == 5 and rows(conn)[1][3] == 0 and s.calls == 5
    assert ob.state()["queued"] == 1
    assert ob.flush(TOKEN, "c", send=s) == 1 and s.calls == 6          # the first one is not tried again
    assert rows(conn)[0][2] is None and rows(conn)[1][2] is not None


def test_transient_errors_do_not_count_a_try_and_429_waits_as_asked():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data"})
    s = Sender(fail=N.TelegramError("HTTP 429: Too Many Requests", transient=True, retry_after=100))
    assert ob.flush(TOKEN, "c", send=s) == 0
    assert rows(conn)[0][3] == 0 and "429" in rows(conn)[0][4]
    clk.advance(60)
    assert ob.flush(TOKEN, "c", send=s) == 0 and s.calls == 1         # still inside retry_after
    clk.advance(41)
    s.fail = None
    assert ob.flush(TOKEN, "c", send=s) == 1


@pytest.mark.parametrize("exc", [OSError("network down"), ValueError("x"), urllib.error.URLError("dns"),
                                 TimeoutError(), Exception("anything")])
def test_flush_never_raises_when_send_throws(exc):
    ob, conn, _ = box()
    ob.queue("warn", {"what": "error"})
    assert ob.flush(TOKEN, "c", send=Sender(fail=exc)) == 0
    assert ob.flush(TOKEN, "c", send=lambda *a: False) == 0                # a sender saying False is a failure too


def test_flush_and_state_never_raise_on_a_broken_database():
    ob, conn, _ = box()
    ob.queue("warn", {"what": "error"})
    conn.close()
    assert ob.flush(TOKEN, "c", send=Sender()) == 0
    assert ob.state()["last_error"].startswith("db:")


def test_the_token_never_lands_in_the_table_or_the_state():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data"})
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    ob.flush(TOKEN, "c", send=Sender(fail=RuntimeError(f"failed {url} and {TOKEN.replace(':', '%3A')}")))
    dump = "\n".join(str(x) for x in conn.execute("SELECT * FROM outbox").fetchall())
    assert TOKEN not in dump and TOKEN.split(":")[1] not in dump and "<token>" in dump
    assert TOKEN not in json.dumps(ob.state())
    other = "1234567:" + "abcdefghij" * 3                     # any token-shaped text, even an unknown one
    assert N.redact(f"x {other} y") == "x <token> y"


def test_api_errors_carry_no_token(monkeypatch):
    def http_error(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     io.BytesIO(b'{"ok":false,"description":"Bad Request: chat not found"}'))
    monkeypatch.setattr(N.urllib.request, "urlopen", http_error)
    with pytest.raises(N.TelegramError) as ei:
        N.send_message(TOKEN, "c", "hi")
    assert str(ei.value) == "HTTP 400: Bad Request: chat not found" and not ei.value.transient
    assert ei.value.__suppress_context__

    def busy(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {},
                                     io.BytesIO(b'{"ok":false,"description":"Too Many Requests",'
                                                b'"parameters":{"retry_after":7}}'))
    monkeypatch.setattr(N.urllib.request, "urlopen", busy)
    with pytest.raises(N.TelegramError) as ei:
        N.send_message(TOKEN, "c", "hi")
    assert ei.value.transient and ei.value.retry_after == 7.0

    def down(req, timeout=None):
        raise urllib.error.URLError(f"cannot reach {req.full_url}")
    monkeypatch.setattr(N.urllib.request, "urlopen", down)
    with pytest.raises(N.TelegramError) as ei:
        N.send_message(TOKEN, "c", "hi")
    assert ei.value.transient and TOKEN not in str(ei.value) and "<token>" in str(ei.value)


def test_send_message_is_plain_silent_and_without_preview(monkeypatch):
    seen = {}
    monkeypatch.setattr(N, "api", lambda token, method, params, timeout: seen.update(m=method, p=params, t=timeout))
    N.send_message(TOKEN, "-100", "안녕")
    assert seen["m"] == "sendMessage" and seen["t"] == N.TIMEOUT_S
    assert seen["p"] == {"chat_id": "-100", "text": "안녕", "disable_web_page_preview": "true",
                         "disable_notification": "true"}
    assert "parse_mode" not in seen["p"]


def test_warn_at_most_once_per_what_per_hour():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data", "detail_ko": "a"})
    ob.queue("warn", {"what": "data", "detail_ko": "b"})
    ob.queue("warn", {"what": "disk", "detail_ko": "c"})
    clk.advance(59 * 60)
    ob.queue("warn", {"what": "data", "detail_ko": "d"})
    assert [r[1] for r in rows(conn)] == ["warn", "warn"]
    clk.advance(2 * 60)
    ob.queue("warn", {"what": "data", "detail_ko": "e"})
    texts = [t for (t,) in conn.execute("SELECT text FROM outbox ORDER BY id")]
    assert len(texts) == 3 and "e" in texts[-1].split("\n")[1]
    ob.queue("start", SAMPLES["start"])
    ob.queue("start", SAMPLES["start"])                                     # only warn is limited
    assert len(rows(conn)) == 5


def test_queue_joins_the_callers_transaction_or_commits_itself(tmp_path):
    path = tmp_path / "demo.db"
    conn = sqlite3.connect(path, isolation_level=None)                     # as demobot/store.connect
    ob, _, _ = box(conn)
    conn.execute("BEGIN IMMEDIATE")
    ob.queue("start", SAMPLES["start"])
    conn.execute("ROLLBACK")
    assert rows(conn) == []
    ob.queue("start", SAMPLES["start"])
    other = sqlite3.connect(path)
    assert other.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1
    conn2 = sqlite3.connect(tmp_path / "b.db")                               # default (implicit transactions)
    ob2, _, _ = box(conn2)
    ob2.queue("start", SAMPLES["start"])
    assert not conn2.in_transaction


def test_old_rows_are_pruned_and_stale_ones_given_up():
    ob, conn, clk = box()
    ob.queue("warn", {"what": "data"})
    ob.flush(TOKEN, "c", send=Sender())
    clk.advance(10)
    ob.queue("warn", {"what": "disk"})                                     # never sent (no chat yet)
    clk.advance(25 * 3600)
    ob.flush("", "", send=Sender())
    ob.queue("warn", {"what": "error"})
    s = Sender()
    assert ob.flush(TOKEN, "c", send=s) == 1 and "오류" in s.sent[0][2]   # the 25-hour-old one is not sent
    assert rows(conn)[1][3] == N.MAX_TRIES and "24시간" in rows(conn)[1][4]
    clk.advance(31 * 86400)
    ob.flush(TOKEN, "c", send=Sender())
    assert rows(conn) == []                                                # sent and given-up rows: 30 days


def test_state_reads_the_environment_before_any_flush(monkeypatch):
    monkeypatch.setenv("DEMOBOT_TG_TOKEN", TOKEN)
    monkeypatch.setenv("DEMOBOT_TG_CHAT", "-100")
    ob, _, _ = box()
    assert ob.state() == {"configured": True, "queued": 0, "last_ok_ms": None, "last_error": None}


def test_outbox_table_shape():
    _, conn, _ = box()
    cols = [(r[1], r[2], r[4]) for r in conn.execute("PRAGMA table_info(outbox)")]
    assert cols == [("id", "INTEGER", None), ("ts_ms", "INTEGER", None), ("kind", "TEXT", None),
                    ("payload", "TEXT", None), ("text", "TEXT", None), ("sent_ms", "INTEGER", None),
                    ("tries", "INTEGER", "0"), ("error", "TEXT", None)]
    N.Outbox(conn)                                                         # twice: no error


# ---------------------------------------------------------------- CLI
def test_cli_test_message(capsys):
    out = []
    assert N.cmd_test(TOKEN, "-100", send=lambda t, c, x: out.append(x), out=print) == 0
    assert out[0].startswith("🧪 데모 랩 테스트 메시지\n")
    assert "보냈습니다" in capsys.readouterr().out
    fail = N.TelegramError("HTTP 401: Unauthorized")

    def bad(t, c, x):
        raise RuntimeError(f"{fail} {TOKEN}")
    assert N.cmd_test(TOKEN, "-100", send=bad) == 1
    o = capsys.readouterr().out
    assert TOKEN not in o and "토큰이 틀렸습니다" in o
    assert N.cmd_test("", "-100") == 2 and N.cmd_test(TOKEN, "") == 2
    assert "sudoedit" in capsys.readouterr().out


def test_cli_chatid_lists_groups_and_never_the_token(capsys):
    updates = [{"update_id": 1, "my_chat_member": {"chat": {"id": -555, "title": "데모 랩", "type": "group"}}},
               {"update_id": 2, "message": {"chat": {"id": -555, "title": "데모 랩", "type": "group"},
                                            "migrate_to_chat_id": -1001234567890}},
               {"update_id": 3, "message": {"chat": {"id": -1001234567890, "title": "데모 랩", "type": "supergroup"}}},
               {"update_id": 4, "message": {"chat": {"id": 42, "first_name": "Kim", "type": "private"}}}]

    def call(token, method, params):
        return {"username": "demolab_test_bot"} if method == "getMe" else updates
    assert N.cmd_chatid(TOKEN, call=call) == 0
    o = capsys.readouterr().out
    assert TOKEN not in o and "/start@demolab_test_bot" in o
    assert "방 번호 -1001234567890   이름 데모 랩   (supergroup)" in o
    assert "-1001234567890 로 바뀜" in o and "방 번호 42   이름 Kim   (private)" in o
    assert o.index("supergroup") < o.index("private")                     # groups first
    assert N.cmd_chatid(TOKEN, call=lambda t, m, p: {} if m == "getMe" else []) == 0
    assert "최근 메시지가 없습니다" in capsys.readouterr().out
    assert N.cmd_chatid("") == 2


def test_credentials_from_the_env_file(tmp_path):
    f = tmp_path / "demobot.env"
    f.write_text(f"# c\nDEMOBOT_TG_TOKEN='{TOKEN}'\nDEMOBOT_TG_CHAT=\"-100\"\nDEMOBOT_DASH_SECRET=zzz\n", encoding="utf-8")
    assert N.credentials(str(f), env={}) == (TOKEN, "-100")
    assert N.credentials(str(f), env={"DEMOBOT_TG_TOKEN": "a", "DEMOBOT_TG_CHAT": "b"}) == ("a", "b")
    assert N.credentials(str(tmp_path / "missing"), env={}) == ("", "")
    assert "DEMOBOT_DASH_SECRET" not in N.read_env_file(str(f))


# ---------------------------------------------------------------- the server kit (static)
def unit(name) -> dict:
    out: dict = {}
    sec = ""
    for ln in (KIT / name).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            sec = ln
            continue
        k, _, v = ln.partition("=")
        out.setdefault(sec, {}).setdefault(k, []).append(v)
    return out


HARDENING = {"NoNewPrivileges": "yes", "PrivateTmp": "yes", "ProtectSystem": "strict", "ProtectHome": "yes",
             "PrivateDevices": "yes", "RestrictSUIDSGID": "yes"}
RULE_BOT_HIDDEN = {"-/etc/paperbot", "-/var/lib/paperbot", "-/var/backups/paperbot"}


def test_engine_unit():
    svc = unit("demobot-live.service")["[Service]"]
    assert svc["User"] == ["demobot"] and svc["WorkingDirectory"] == ["/opt/demobot/app"]
    assert svc["EnvironmentFile"] == ["/etc/demobot/demobot.env"]
    assert svc["ExecStart"] == ["/opt/demobot/venv/bin/python -m demobot run"]
    for k, v in {"Nice": "10", "CPUQuota": "30%", "MemoryMax": "900M", "MemoryHigh": "700M", "Restart": "always",
                 "RestartSec": "20", **HARDENING}.items():
        assert svc[k] == [v], k
    assert svc["ReadWritePaths"] == ["/var/lib/demobot"]
    assert set(svc["InaccessiblePaths"][0].split()) >= RULE_BOT_HIDDEN
    env = " ".join(svc["Environment"]).split()
    assert {"OPENBLAS_NUM_THREADS=1", "OMP_NUM_THREADS=1", "MKL_NUM_THREADS=1"} <= set(env)


def test_dashboard_unit_is_read_only_and_waits_for_the_tailscale_address():
    u = unit("demobot-dash.service")
    svc = u["[Service]"]
    assert svc["User"] == ["demobot"] and svc["MemoryMax"] == ["300M"]
    assert svc["ExecStart"] == ["/opt/demobot/venv/bin/python -m demobot.dash --host ${DEMOBOT_DASH_HOST} "
                                "--port ${DEMOBOT_DASH_PORT}"]
    for k, v in HARDENING.items():
        assert svc[k] == [v], k
    assert "ReadWritePaths" not in svc                                       # writes nothing
    assert svc["TemporaryFileSystem"] == ["/var/lib/demobot:ro"] and svc["BindReadOnlyPaths"] == ["/var/lib/demobot/snap"]
    assert set(svc["InaccessiblePaths"][0].split()) >= RULE_BOT_HIDDEN | {"-/etc/demobot"}
    assert "DEMOBOT_TG_TOKEN" in svc["UnsetEnvironment"][0].split()
    pre = " ".join(svc["ExecStartPre"])
    assert "ip -4 -o addr show" in pre and "$$DEMOBOT_DASH_HOST" in pre
    assert any(not p.startswith("-") and "exit 1" in p for p in svc["ExecStartPre"])   # empty host: refuse
    assert "tailscaled.service" in u["[Unit]"]["After"][0]


def test_rank_unit_is_a_capped_oneshot_with_the_engines_sandbox():
    u = unit("demobot-rank.service")
    svc = u["[Service]"]
    live = unit("demobot-live.service")["[Service]"]
    assert svc["Type"] == ["oneshot"] and svc["ExecStart"] == ["/opt/demobot/venv/bin/python -m demobot rank"]
    for k in ("User", "Group", "UMask", "WorkingDirectory", "EnvironmentFile", "Environment", "UnsetEnvironment",
              "ReadWritePaths", "InaccessiblePaths", "RestrictAddressFamilies"):
        assert svc[k] == live[k], k                                        # same sandbox and env handling
    for k, v in {"Nice": "15", "CPUQuota": "50%", "MemoryHigh": "800M", "MemoryMax": "1000M",
                 "TimeoutStartSec": "40min", **HARDENING}.items():
        assert svc[k] == [v], k
    assert svc["ReadWritePaths"] == ["/var/lib/demobot"]
    assert set(svc["InaccessiblePaths"][0].split()) >= RULE_BOT_HIDDEN
    assert "Restart" not in svc and "[Install]" not in u                    # started by its timer only


def test_rank_timer_hourly_at_minute_7():
    u = unit("demobot-rank.timer")
    t = u["[Timer]"]
    assert t["OnCalendar"] == ["*-*-* *:07:00"] and t["OnBootSec"] == ["10min"]
    assert t["Persistent"] == ["false"] and t["RandomizedDelaySec"] == ["0"]
    assert t["Unit"] == ["demobot-rank.service"] and u["[Install]"]["WantedBy"] == ["timers.target"]


def unit_files():
    return sorted(list(KIT.glob("*.service")) + list(KIT.glob("*.timer")))


def test_the_kit_has_the_four_units():
    assert {p.name for p in unit_files()} == {"demobot-live.service", "demobot-dash.service", "demobot-rank.service",
                                              "demobot-rank.timer"}


@pytest.mark.parametrize("path", unit_files(), ids=lambda p: p.name)
def test_units_mention_the_rule_bot_only_to_hide_it(path):
    for ln in path.read_text(encoding="utf-8").splitlines():
        if "paperbot" in ln:
            assert ln.startswith("InaccessiblePaths="), ln


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="no systemd-analyze")
def test_units_verify():
    r = subprocess.run(["systemd-analyze", "verify", *map(str, unit_files())], capture_output=True, text=True)
    problems = [ln for ln in (r.stdout + r.stderr).splitlines()
                if ln.strip() and "is not executable" not in ln and "/opt/demobot/venv" not in ln]
    assert problems == []


def test_the_scripts_handle_the_ranking_timer():
    text = {p.name: p.read_text(encoding="utf-8") for p in scripts()}
    inst = text["install_demobot.sh"]
    assert "demobot-rank.service demobot-rank.timer" in inst                 # both files installed
    assert re.search(r'SWAP_UNITS="[^"]*demobot-rank\.timer', inst)          # paused for the code swap
    enable = inst[inst.index('if [ "$DB_EXISTED" = 1 ]; then'):]
    assert "systemctl enable --quiet demobot-live.service demobot-rank.timer" in enable    # same 'ready' rule
    assert "demobot-rank.timer" in text["on.sh"] and "systemctl start --no-block demobot-rank.service" in text["on.sh"]
    assert "disable --now --quiet demobot-live.service demobot-dash.service demobot-rank.timer" in text["off.sh"]
    assert "/etc/systemd/system/demobot-rank.timer" in text["uninstall.sh"]
    assert "systemctl start demobot-rank.service" in text["warm.sh"]


def scripts():
    return sorted(KIT.glob("*.sh"))


def code_lines(p: Path):
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def test_scripts_never_start_or_stop_a_rule_bot_unit_and_never_print_an_env_file():
    assert {p.name for p in scripts()} >= {"install_demobot.sh", "capacity_check.sh", "on.sh", "off.sh", "update.sh",
                                           "uninstall.sh", "warm.sh", "firewall.sh"}
    for p in scripts():
        for ln in code_lines(p):
            if re.search(r"systemctl\s+(\S+\s+)*(start|stop|restart|enable|disable|kill|mask|reload|try-restart)\b", ln):
                assert "paperbot" not in ln, (p.name, ln)
            if "/etc/paperbot" in ln or "/var/lib/paperbot" in ln:
                assert "InaccessiblePaths" in ln, (p.name, ln)              # only to hide them (warm.sh)
            assert not re.search(r"\b(cat|less|more|head|tail)\b[^|<]*\.env\b", ln), (p.name, ln)
            assert not re.search(r"\b(cat|less|more|head|tail)\b[^|<]*\$ENVF", ln), (p.name, ln)
            if re.search(r"\b(echo|printf)\b", ln):                     # a secret's VALUE is never printed
                assert not re.search(r"\$\((env)?val\s+DEMOBOT_(TG_TOKEN|DASH_SECRET|DASH_PASSWORD_HASH)\)", ln), ln
                assert not re.search(r"\$\{?[HS]\}?\b", ln) or p.name != "on.sh", ln


def test_capacity_check_is_read_only():
    text = "\n".join(code_lines(KIT / "capacity_check.sh"))
    for bad in ("systemctl start", "systemctl stop", "systemctl restart", "systemctl enable", "ufw allow",
                "useradd", "rm ", "mkdir", "install -d", "install -m", " > /", "tee "):
        assert bad not in text, bad
    assert not re.search(r"^\s*(sudo\s+)?apt(-get)?\s", text, re.M)          # only named in a hint, never run
    assert "같은 서버에 설치해도 됩니다" in text and "1536" in text and "3072" in text and "0.7" in text
    assert "약 500 MB" in text and "약 1.2 GB" in text and "순위표" in text


def test_install_copies_only_the_listed_paths_and_handles_the_env_file_safely():
    text = (KIT / "install_demobot.sh").read_text(encoding="utf-8")
    m = re.search(r'CODE_PATHS="([^"]+)"', text)
    paths = m[1].replace("\\\n", " ").split()
    assert paths == ["demobot", "paperbot", "third_party/sweep", "research/entry_study/param_defs",
                     "research/entry_study/DEFS_BC.sha256", "research/st_custom/out/picks.csv",
                     "research/st_custom/PREREG.md", "research/st_custom/PREREG.sha256"]
    for p in paths:
        assert (REPO / p).exists(), p
    assert "--exclude='paperbot/dash/static'" in text
    assert 'if [ ! -f "$ENVF" ]; then' in text and "-m 640" in text and "chown root:demobot \"$ENVF\"" in text
    assert 'if [ "$(id -u)" -ne 0 ]' in text and "app.old" in text and "app.new" in text
    assert "-m demobot selfcheck" in text and "unknown command" in text
    fw = (KIT / "firewall.sh").read_text(encoding="utf-8")
    assert "ufw allow in on tailscale0 to any port" in fw and "Anywhere on tailscale0" in fw
    assert 'bash "$HERE/firewall.sh"' in text and 'bash "$HERE/firewall.sh"' in (KIT / "on.sh").read_text(encoding="utf-8")


def test_env_example_has_the_contract_keys_and_no_values():
    kv = dict(ln.split("=", 1) for ln in (KIT / "demobot.env.example").read_text(encoding="utf-8").splitlines()
              if ln and not ln.startswith("#"))
    assert set(kv) == {"DEMOBOT_TG_TOKEN", "DEMOBOT_TG_CHAT", "DEMOBOT_DASH_PASSWORD_HASH", "DEMOBOT_DASH_SECRET",
                       "DEMOBOT_DASH_HOST", "DEMOBOT_DASH_PORT", "DEMOBOT_DB", "DEMOBOT_SNAP"}
    assert all(kv[k] == "" for k in ("DEMOBOT_TG_TOKEN", "DEMOBOT_TG_CHAT", "DEMOBOT_DASH_PASSWORD_HASH",
                                     "DEMOBOT_DASH_SECRET"))
    assert kv["DEMOBOT_DASH_PORT"] == "8090" and kv["DEMOBOT_DASH_HOST"] == "127.0.0.1"
    assert kv["DEMOBOT_DB"] == "/var/lib/demobot/demo.db" and kv["DEMOBOT_SNAP"] == "/var/lib/demobot/snap"


@pytest.mark.skipif(not shutil.which("bash"), reason="no bash")
@pytest.mark.parametrize("path", scripts(), ids=lambda p: p.name)
def test_scripts_parse(path):
    subprocess.run(["bash", "-n", str(path)], check=True)
    if shutil.which("shellcheck"):
        r = subprocess.run(["shellcheck", "-S", "warning", str(path)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout


def test_owner_guide():
    text = DOC.read_text(encoding="utf-8")
    assert ("git clone --branch claude/keen-pasteur-wav02u --depth 1 "
            "https://github.com/g1792091-boop/crypto-bot-research /root/demobot-src") in text
    assert "SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env" in text
    assert "python -m demobot.notify chatid" in text and "demobot.dash hash" in text
    assert "openssl rand -hex 32" in text and "tailscale ip -4" in text and ":8090" in text
    assert "systemctl list-timers demobot-rank.timer" in text and "매시 7분" in text
    assert not re.search(r"\bcat\b[^\n|]*(\.env|/etc/demobot)", text)
    assert "cd /opt/crypto-bot-research" not in text and "deploy/install.sh" not in text   # the rule bot's kit
