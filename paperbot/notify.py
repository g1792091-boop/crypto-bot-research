"""Alert delivery. The engine never depends on delivery succeeding.

Telegram wording (owners' redesign 2026-10-04; plain text, Telegram gets no parse_mode): the engine's, the feed's
and the runner's lines stay as they are in the alerts table and the dashboard (English, trading files); they are
worded here, at the Telegram edge (``telegram_text``): a title line '<what> · <whom>', a blank line, short lines,
the KST time last where the line itself has none. One emoji first: the level mark (🚨 CRITICAL, ⚠ WARN) unless
the text already starts with its own emoji (🔔, 📈, ✅ …). Sound comes only from the level (INFO = silent).

``Router`` holds the live runner's noisy lines (1m gaps, clock skew, signal timeouts) for the hourly digest and
rings only past a threshold; real emergencies (liquidation, job failure, …) are never held.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Optional, Protocol

INFO = "INFO"
WARN = "WARN"
CRITICAL = "CRITICAL"
# what a Telegram message starts with, by level (the owners may route every level to one chat); skipped when
# the text already starts with an emoji of its own
PREFIX = {CRITICAL: "🚨 ", WARN: "⚠ ", INFO: ""}
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}

_clock = time.time          # seconds; tests and the sample generator pin it (the KST time line of a message)


# ---------------------------------------------------------------- number and name helpers (every sender uses them)
def usd(x: float) -> str:
    """Signed whole dollars: '+$1,500', '-$18' (never '$-18')."""
    return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"


def money(x: float) -> str:
    """Whole dollars without a plus: '$1,500', '-$5' (never '$1500.00')."""
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


def kst(ms, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(int(ms) / 1000 + 9 * 3600))


def _kst(ms: str) -> str:
    return kst(int(ms))


def hm(ms) -> str:
    return kst(ms, "%H:%M")


def now_kst() -> str:
    """'10/04 21:15' (KST) of the moment the message goes out."""
    return kst(int(_clock() * 1000))


def day_ko(day: str) -> str:
    """'2026-10-03' or '20261003' -> '10/03'; anything else unchanged."""
    m = re.fullmatch(r"\d{4}-?(\d{2})-?(\d{2})", str(day))
    return f"{m[1]}/{m[2]}" if m else str(day)


def secs_ko(s: float) -> str:
    """412 -> '7분', 45 -> '45초', 7300 -> '약 2시간'."""
    s = float(s)
    if s < 60:
        return f"{s:.0f}초"
    if s < 7200:
        return f"{round(s / 60)}분"
    return f"약 {round(s / 3600)}시간"


def coin(symbol: str) -> str:
    return str(symbol).replace("USDT", "")


def _coins(text: str) -> str:
    """"['BTCUSDT', 'ETHUSDT']" -> "BTC, ETH"."""
    return ", ".join(re.findall(r"(\w+?)USDT", text)) or text


def _strategy_ko() -> dict:
    try:
        from .agents.roster3 import STRATEGY_KO
        return STRATEGY_KO
    except Exception:  # noqa: BLE001  (names are cosmetic)
        return {}


def who(book: str, kind: Optional[str] = None) -> str:
    """An account as the owners read it: 'S2_ST_ROC@15m' -> '슈퍼트렌드·ROC 15분', a copy 'S2_ST_ROC@1h~c1' ->
    '복제 슈퍼트렌드·ROC 1시간', a new-strategy account 'NL2@15m' -> '새 매매법 NL2 15분', 'RANDOM_3@1h' ->
    '동전 봇 3 1시간'. ``kind`` (accounts.kind) decides when given; anything unknown is returned as it came."""
    strat, _, tf = str(book).partition("@")
    copy = re.fullmatch(r"(.+?)~c(\d+)", tf)
    if copy:
        tf = copy[1]
    if tf not in TF_KO:
        return book
    t = TF_KO[tf]
    if kind == "random" or (kind is None and strat.startswith("RANDOM_")):
        return f"동전 봇 {strat.rsplit('_', 1)[-1]} {t}"
    if kind == "newlab" or (kind is None and re.fullmatch(r"NL\d+", strat)):
        return f"새 매매법 {strat} {t}"
    name = _strategy_ko().get(strat, strat)
    if kind == "copy" or (kind is None and copy):
        return f"복제 {name} {t}"
    return f"{name} {t}"


_who = who          # the old name


def starts_with_emoji(text: str) -> bool:
    c = (text or " ")[0]
    return ord(c) >= 0x1F000 or unicodedata.category(c) == "So" or c in "ℹ"


def _floor(x) -> float:
    """A bust balance in whole dollars rounded down ($9.50 below a $10 line must not read '$10')."""
    import math
    return float(math.floor(float(x)))


def _one_line(text: str) -> str:
    return " · ".join(x for x in text.split("\n") if x.strip())


# ---------------------------------------------------------------- wording of single lines
def _halt_ko(reason: str) -> str:
    if reason == "manual kill":
        return "수동 정지"
    m = re.fullmatch(r"drawdown ([\d.]+)% reached halt level (\d+)%", reason)
    if m:
        return f"낙폭 {float(m[1]):.0f}% (정지선 {m[2]}%)"
    m = re.fullmatch(r"bust: equity (-?[\d.]+) below ([\d.]+)", reason)
    if m:
        return f"파산 (잔고 {money(float(m[1]))})"
    return reason


def _http_ko(err: str) -> str:
    m = re.search(r"HTTP (\d{3})", err)
    if not m:
        return err.split("\n")[0][:120]
    return f"HTTP {m[1]}" + (" (지역 제한)" if m[1] == "451" else " (접근 거부)" if m[1] == "403" else "")


def _brackets_ko(src: str) -> str:
    if src.startswith("Binance leverageBracket"):
        return "바이낸스 실시간"
    if src.startswith("file "):
        return f"파일 {src[5:]}"
    if src.startswith("EXAMPLE"):
        return "예시 표 (시험용, 거래소 자료 아님)"
    return src


def _accounts_n() -> int:
    try:
        from .config import V3_ACCOUNTS
        return int(V3_ACCOUNTS)
    except Exception:  # noqa: BLE001
        return 156


def _code_error(kind: str, what: str, head: str, body: str) -> str:
    mod = re.search(r"from '([\w.]+)'", what)
    where = f" ({mod[1].rsplit('.', 1)[-1]})" if mod else ""
    return f"{head}\n\n{body}\n원래 계좌 {_accounts_n()}개는 그대로 돎\n오류: {kind}{where}"


def _codes_ko() -> dict:
    try:
        from .extras import CODES_KO
        return CODES_KO
    except Exception:  # noqa: BLE001
        return {}


def _reason_ko(rest: str) -> str:
    """'parent_bust: 원본 계좌 S2_ST_ROC@1h 파산' -> '원본 계좌가 파산' (extras.CODES_KO), else the detail."""
    code, _, detail = rest.partition(": ")
    got = _codes_ko().get(code.strip())
    if got:
        return got
    if code.startswith("fault"):
        return f"코드 오류 ({detail.split(':')[0] or code})"
    return (detail or code).strip() or "알 수 없음"


def _extra_state(m) -> str:
    what = m[2]
    if what == "멈춤":
        return (f"추가 계좌 멈춤 · {who(m[1])}\n\n새 진입 없음 (열린 포지션은 규칙대로)\n이유: {_reason_ko(m[4])}\n"
                f"{now_kst()}")
    return f"추가 계좌 정지 · {who(m[1])}\n\n동결 (저장된 상태 그대로)\n이유: {_reason_ko(m[4])}\n{now_kst()}"


def _new_account(m) -> str:
    label, aid, pid = m[1], m[2], m[3]
    if "~c" in aid:
        rule = label.split(" · ", 1)[1] if " · " in label else ""
        body = f"바꾼 한 가지: {rule}\n" if rule else ""
    else:
        trial = re.search(r"장부 #(\d+)", label)
        body = f"새 매매법 (장부 #{trial[1]})\n" if trial else ""
    return f"🆕 새 계좌 시작 · {who(aid)}\n\n{body}제안 #{pid} (두 분 승인)"


def _run_started(m) -> str:
    fresh = m[1] == "started"
    fee = float(m[4])
    return (f"▶️ 봇 {'시작' if fresh else '재시작'} · 계좌 {m[2]}개\n\n"
            f"{'새로 시작' if fresh else '이어서 돌림'}\n레버리지 구간: {_brackets_ko(m[3])}\n수수료 {fee:g}%")


def _tfs(text: str) -> str:
    return ", ".join(TF_KO.get(t.strip(), t.strip()) for t in text.split(","))


# The English lines of the engine, the feed and the runner (trading files, kept as they are: the alerts table,
# the dashboard and the parity golden read them) and the extras' lines, as Telegram words them. Applied per line
# of a message (``ko``); a format may return several lines. Anything else is unchanged.
KO_LINES = (
    (r"\[([^\]]+)\] LIQUIDATED (\w+?)(?:USDT)? (\d+)x lost margin ([\d.]+)",
     lambda m: f"강제청산 · {who(m[1])}\n\n{m[2]} {m[3]}배\n증거금 {money(float(m[4]))} 전액 손실\n{now_kst()}"),
    (r"\[([^\]]+)\] BUST: bust: equity (-?[\d.]+) below ([\d.]+)",
     lambda m: f"{who(m[1])} 파산 · 잔고 {money(_floor(m[2]))} (파산선 {money(float(m[3]))})"),
    (r"\[([^\]]+)\] drawdown ([\d.]+)% \(level (\d+)%\), equity (-?[\d.]+)",
     lambda m: f"{who(m[1])} 낙폭 -{m[3]}% · 잔고 {money(float(m[4]))}"),
    (r"\[([^\]]+)\] ENGINE HALTED: (.*?)\.? Operator action required\.",
     lambda m: f"계좌 정지 · {who(m[1])}\n\n이유: {_halt_ko(m[2])}\n운영자 확인 필요\n{now_kst()}"),
    (r"engine resumed by operator$", lambda m: "계좌 다시 시작 (운영자)"),
    (r"signal workers did not answer within (\d+)s; signals skipped at (\d+) for (.+)",
     lambda m: f"신호 건너뜀 · {hm(m[2])} 봉\n\n신호 계산이 {m[1]}초 안에 안 끝남\n건너뛴 봉: {_tfs(m[3])}\n"
               "계산 프로세스를 새로 띄움 · 봇은 계속 돎"),
    (r"data gap at (\d+): no bar for (.+)",
     lambda m: f"1분봉 빠짐 · {hm(m[1])}\n\n{_coins(m[2])}\n그 코인은 그 1분을 건너뜀"),
    (r"(\w+?)USDT: exchange returned no bars for (\d+) min from (\d+)",
     lambda m: f"바이낸스 1분봉 없음 · {m[1]}\n\n{hm(m[3])}부터 {m[2]}분 동안"),
    (r"no new closed bars for (\d+)s", lambda m: f"시세 끊김\n\n새 1분봉이 {secs_ko(int(m[1]))}째 안 들어옴\n{now_kst()}"),
    (r"market data flowing again", lambda m: f"✅ 시세 다시 들어옴\n{now_kst()}"),
    (r"Binance blocked this server: (.*)",
     lambda m: f"바이낸스 접속 차단\n\n봇이 멈췄습니다\n응답: {_http_ko(m[1])}\n{now_kst()}"),
    (r"local clock off by (-?\d+) ms from Binance; using server time",
     lambda m: f"서버 시계 어긋남\n\n바이낸스와 {round(abs(int(m[1])) / 1000, 2):g}초 차이\n바이낸스 시각으로 계산 중 (조치 불필요)"),
    (r"paper v3 (started|resumed): (\d+) accounts, brackets: (.+), taker fee ([\d.]+)%", _run_started),
    (r"\[extra\] extras code failed to load: (\w+)(?::\s*(.*))?",
     lambda m: _code_error(m[1], m[2] or "", "추가 계좌 코드 오류", "추가 계좌가 저장된 상태로 멈춤")),
    (r"\[extra\] extras could not start: (\w+)(?::\s*(.*))?",
     lambda m: _code_error(m[1], m[2] or "", "추가 계좌 시작 실패", "추가 계좌는 신호 없이 규칙대로만 돎")),
    (r"\[extra\] boundary hook failed \((\w+)(?::\s*(.*))?\)",
     lambda m: _code_error(m[1], m[2] or "", "추가 계좌 코드 오류",
                           "이번 경계의 추가 계좌 처리만 되돌림 (3번 실패하면 중지)")),
    (r"\[extra\] (\S+): 다시 정상 운영 \((.*?)(?: 해소)?\)$",
     lambda m: f"✅ 추가 계좌 재개 · {who(m[1])}\n\n{m[2]} 끝"),
    (r"\[extra\] (\S+): (멈춤|정지)\((.*?)\) — (.*)", _extra_state),
    (r"\[extra\] 새 paper 계좌 시작: (.*) \((\S+)\), 제안 #(\d+)$", _new_account),
    (r"\[extra\] agents3\.db가 예전 것으로 바뀐 것 같아 새 계좌 시작을 멈춤\. 확인 후 extras\.json에 (.*?) ?를 넣으세요",
     lambda m: "새 추가 계좌 시작 멈춤\n\n에이전트 장부(agents3.db)가 예전 것으로 바뀐 듯\n돌던 계좌는 그대로 돕니다\n"
               f"운영자: extras.json에 {m[1]} 넣기"),
    (r"\[extra\] inbox\.db\(승인·거절 클릭 기록\)가 예전 것으로 바뀐 것 같아 .*?extras\.json에 (.*?) ?를 넣으세요",
     lambda m: "새 추가 계좌 시작 멈춤\n\n승인 클릭 기록(inbox.db)이 예전 것으로 바뀐 듯\n백업 뒤에 누른 승인·거절은 다시 눌러야 함\n"
               f"돌던 계좌는 그대로 돕니다\n운영자: 그다음 extras.json에 {m[1]} 넣기"),
    (r"\[extra\] (\S+@\S+): (.*)", lambda m: f"추가 계좌 · {who(m[1])}\n\n{m[2]}"),
    (r"\[extra\] (.*)", lambda m: f"추가 계좌: {m[1]}"),
    # the last line of a digest (Digest here, extras.py): the screen that lists the rest
    (r"외 (\d+)건 \(대시보드 알림 목록\)$", lambda m: f"외 {m[1]}건 (대시보드 '서버 상태 → 경고')"),
)


def ko(text: str) -> str:
    """The Korean text of a known alert line (KO_LINES); any other text unchanged. Never raises."""
    try:
        for pat, fmt in KO_LINES:
            m = re.match(pat, text, re.S)
            if m:
                return fmt(m)
    except Exception:  # noqa: BLE001  (a wording helper must never stop an alert)
        pass
    return text


# ---------------------------------------------------------------- wording of whole messages (digests, bundles)
_BUST = re.compile(r"\[([^\]]+)\] BUST: bust: equity (-?[\d.]+) below ([\d.]+)")
_DD = re.compile(r"\[([^\]]+)\] drawdown ([\d.]+)% \(level (\d+)%\), equity (-?[\d.]+)")
_MORE = re.compile(r"외 (\d+)건 \(대시보드 알림 목록\)$")
_SCREEN = "(대시보드 '서버 상태 → 경고')"


def _digest_ko(lines: list[str], extras: bool) -> str:
    busts, dds, other, ops, more = [], [], [], 0, 0
    for ln in lines:
        b, d, mo = _BUST.match(ln), _DD.match(ln), _MORE.match(ln)
        if b:
            busts.append(f"- {who(b[1])} · 잔고 {money(_floor(b[2]))} (파산선 {money(float(b[3]))})")
        elif d:
            dds.append((int(d[3]), float(d[2]), f"- {who(d[1])} · -{d[3]}% · 잔고 {money(float(d[4]))}"))
        elif mo:
            more = int(mo[1])
        elif ln.startswith("[extra]"):
            ops += 1                       # operational notes (codes, ms boundaries): the count only
        elif ln.strip():
            other.append("- " + _one_line(ko(ln)))
    if extras:
        title = "📉 추가 계좌 경고 · 지난 1시간"
    elif busts or dds:
        title = "📉 파산·낙폭 모음 · 지난 1시간"
    else:
        title = "📋 알림 모음 · 지난 1시간"
    L = [title]
    if busts:
        L += ["", f"파산 {len(busts)}건"] + busts
    if dds:
        L += ["", f"낙폭 경고 {len(dds)}건"] + [x[2] for x in sorted(dds, key=lambda x: (-x[0], -x[1]))]
    if other:
        L += ["", f"{'그 밖의 알림' if busts or dds else '알림'} {len(other)}건"] + other
    if ops:
        L += ["", f"운영 메모 {ops}건 {_SCREEN}"]
    if more:
        L += ["", f"외 {more}건 {_SCREEN}"]
    return "\n".join(L)


def _urgent_item(t: str) -> str:
    m = re.match(KO_LINES[0][0], t)
    if m:
        return f"- 강제청산 · {who(m[1])} · {m[2]} {m[3]}배 · -{money(float(m[4]))}"
    m = re.match(r"\[extra\] (\S+): 다시 정상 운영 \((.*?)(?: 해소)?\)$", t)
    if m:
        return f"- 재개 · {who(m[1])} ({m[2]} 끝)"
    m = re.match(r"\[extra\] (\S+): (멈춤|정지)\((.*?)\) — (.*)", t, re.S)
    if m:
        return f"- {m[2]} · {who(m[1])} ({_reason_ko(m[4])})"
    first = ko(t).split("\n")
    return "- " + " · ".join(x for x in first[:3] if x.strip())


def render(text: str) -> str:
    """The Telegram wording of a whole message: the two hourly digests and the extras' bundle are regrouped,
    any other message is worded line by line (``ko``). Never raises."""
    try:
        lines = text.split("\n")
        if lines[0].startswith("알림 모음: "):
            return _digest_ko(lines[1:], extras=False)
        if lines[0].startswith("추가 계좌 알림 모음: "):
            return _digest_ko(lines[1:], extras=True)
        m = re.match(r"추가 계좌 긴급 알림 (\d+)건$", lines[0])
        if m:
            body = [ln for ln in lines[1:] if ln.strip()]
            items = [_urgent_item(ln) if not _MORE.match(ln) else f"외 {_MORE.match(ln)[1]}건 {_SCREEN}" for ln in body]
            return "\n".join([f"추가 계좌 긴급 {m[1]}건", ""] + items + [now_kst()])
        return "\n".join(ko(line) for line in lines)
    except Exception:  # noqa: BLE001
        return text


_RESUMED = re.compile(r"\[extra\] \S+: 다시 정상 운영 \(")


def level_for(level: str, text: str) -> str:
    """Good news never rings: an extra account back to normal (alone, or a bundle of only those) goes silent."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if level == CRITICAL and lines:
        if _RESUMED.match(lines[0]) and len(lines) == 1:
            return INFO
        if re.match(r"추가 계좌 긴급 알림 \d+건$", lines[0]) and lines[1:] and all(_RESUMED.match(x) for x in lines[1:]):
            return INFO
    return level


def telegram_text(level: str, text: str) -> tuple[str, str]:
    """(level, text) exactly as Telegram gets them: the level after ``level_for``, the wording (``render``) and
    one level mark in front unless the text already starts with an emoji."""
    lvl = level_for(level, text)
    body = render(text)
    return lvl, ("" if starts_with_emoji(body) else PREFIX.get(lvl, f"[{lvl}] ")) + body


class Notifier(Protocol):
    # False: delivery failed (a notifier that cannot tell returns None)
    def send(self, level: str, text: str) -> Optional[bool]: ...


class NullNotifier:
    def send(self, level: str, text: str) -> None:
        pass


class ListNotifier:
    """Keeps messages in memory; used by tests and replays."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send(self, level: str, text: str) -> None:
        self.messages.append((level, text))


class ConsoleNotifier:
    def send(self, level: str, text: str) -> None:
        print(f"[{level}] {text}", file=sys.stderr)


class TelegramNotifier:
    """Sends to one chat per level. Token and chat ids come from the
    environment so they never land in the repository:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_CRITICAL, TELEGRAM_CHAT_WARN,
    TELEGRAM_CHAT_INFO (WARN and INFO fall back to CRITICAL's chat)."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        critical = os.environ["TELEGRAM_CHAT_CRITICAL"]
        self.chats = {
            CRITICAL: critical,
            # an empty value in the env file means "not set", not "chat id ''"
            WARN: os.environ.get("TELEGRAM_CHAT_WARN") or critical,
            INFO: os.environ.get("TELEGRAM_CHAT_INFO") or critical,
        }
        self.timeout = timeout

    def send(self, level: str, text: str) -> bool:
        """True when Telegram accepted the message; False when delivery failed (never raises)."""
        level, body = telegram_text(level, text)
        data = urllib.parse.urlencode({
            "chat_id": self.chats.get(level, self.chats[CRITICAL]),
            "text": body,
            "disable_notification": json.dumps(level == INFO),
        }).encode()
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            urllib.request.urlopen(url, data=data, timeout=self.timeout).read()
        except Exception as exc:  # delivery failure must not stop trading logic
            print(f"telegram send failed: {type(exc).__name__}", file=sys.stderr)
            return False
        return True


KO_KINDS = (("BUST", "파산"), ("drawdown", "낙폭"), ("ENGINE HALTED", "정지"), ("LIQUIDATED", "강제청산"))


class Digest:
    """Collects per-account WARN messages (bust, drawdown levels) and sends them
    as one silent message per interval, so the 156 original accounts (and the extras) cannot flood a phone.

    ``add`` never sends; ``flush(now_ms)`` sends when the interval has passed
    (or at once with ``force``) and returns the text it sent, if any. ``note(key, text)`` keeps one summary
    line per key (the Router's counts), replaced by the next note of that key and sent with the next flush."""

    def __init__(self, forward: Notifier, every_ms: int = 3_600_000, max_lines: int = 15):
        self.forward = forward
        self.every_ms = every_ms
        self.max_lines = max_lines
        self.items: list[str] = []
        self.notes: dict[str, str] = {}
        self.last_ms: int | None = None

    def add(self, text: str) -> None:
        self.items.append(text)

    def note(self, key: str, text: str) -> None:
        self.notes[key] = text

    def flush(self, now_ms: int, force: bool = False):
        if self.last_ms is None:
            self.last_ms = now_ms
        if not (self.items or self.notes) or (not force and now_ms - self.last_ms < self.every_ms):
            return None
        items = self.items + list(self.notes.values())
        counts = {}
        for t in items:
            kind = next((ko for key, ko in KO_KINDS if key in t), "기타")
            counts[kind] = counts.get(kind, 0) + 1
        head = "알림 모음: " + " · ".join(f"{k} {n}" for k, n in counts.items())
        lines = self.items[:self.max_lines]
        more = len(self.items) - len(lines)
        text = "\n".join([head] + lines + list(self.notes.values()) + ([f"외 {more}건 (대시보드 알림 목록)"] if more else []))
        self.forward.send(INFO, text)
        self.items = []
        self.notes = {}
        self.last_ms = now_ms
        return text


# ---------------------------------------------------------------- the live runner's noise rules
_GAP = re.compile(r"data gap at (\d+): no bar for (.+)")
_NOBARS = re.compile(r"(\w+?)USDT: exchange returned no bars for (\d+) min from (\d+)")
_SKEW = re.compile(r"local clock off by (-?\d+) ms from Binance")
_TIMEOUT = re.compile(r"signal workers did not answer within \d+s; signals skipped at (\d+) for (.+)")


class Router:
    """Between the live runner (feed, runner, book, extras) and Telegram (live3.cmd_run). Real emergencies pass at
    once; the noisy operational lines go to the hourly digest (silent) instead of ringing each time:

    - 1m bars missing (feed 'data gap', 'exchange returned no bars'): one count line in the digest; ONE loud WARN
      when ``GAP_LOUD`` or more coin-minutes are missing before the digest goes out;
    - clock skew: loud at most once a KST day and only above ``SKEW_LOUD_MS`` (the bot already uses Binance's
      time); a smaller skew is one digest line a day;
    - signal timeouts: the first is loud; the next ones are counted in the digest, and one rings again once
      ``TIMEOUT_QUIET_MS`` (6 h) have passed since the last LOUD one, or when it is the ``TIMEOUT_RING_EVERY``-th
      (12th) further timeout since the last loud one (about 3 h of timeouts at every 15m boundary). So timeouts that
      keep coming keep ringing (96 in 24 h: 8 loud), and an isolated one after 6 h rings as before.
    The alerts table (dashboard) has every line anyway: the runner writes it before sending."""

    GAP_LOUD = 10
    SKEW_LOUD_MS = 5_000
    TIMEOUT_QUIET_MS = 6 * 3_600_000
    TIMEOUT_RING_EVERY = 12

    def __init__(self, forward: Notifier, digest: Digest, clock=None):
        self.forward, self.digest = forward, digest
        self.clock = clock or (lambda: int(_clock() * 1000))
        self.gaps: dict[str, int] = {}
        self.gap_loud = False
        self.skew_days: dict[str, str] = {}
        self.last_timeout: Optional[int] = None
        self.last_timeout_loud: Optional[int] = None
        self.timeouts = 0               # digest count (since the digest last went out)
        self.timeouts_since_loud = 0    # further timeouts since the last loud one

    def send(self, level: str, text: str):
        try:
            if level != CRITICAL:
                for rule in (self._gap, self._skew, self._timeout):
                    done, res = rule(level, text)
                    if done:
                        return res
        except Exception:  # noqa: BLE001  (a routing rule must never lose an alert)
            pass
        return self.forward.send(level, text)

    def _gap(self, level, text):
        g, nb = _GAP.match(text), _NOBARS.match(text)
        if not (g or nb):
            return False, None
        if "gaps" not in self.digest.notes:          # the digest went out: count afresh
            self.gaps, self.gap_loud = {}, False
        if g:
            for c in re.findall(r"(\w+?)USDT", g[2]):
                self.gaps[c] = self.gaps.get(c, 0) + 1
        else:
            self.gaps[nb[1]] = self.gaps.get(nb[1], 0) + int(nb[2])
        total = sum(self.gaps.values())
        per = " · ".join(f"{c} {n}분" for c, n in sorted(self.gaps.items(), key=lambda x: -x[1]))
        self.digest.note("gaps", f"1분봉 빠짐 {total}분: {per} (그 코인은 그 1분을 건너뜀)")
        if total >= self.GAP_LOUD and not self.gap_loud:
            self.gap_loud = True
            return True, self.forward.send(WARN, f"1분봉 빠짐 많음 · {total}분\n\n{per}\n그 코인은 그 1분을 건너뜀 · 봇은 계속 돎\n"
                                                 "나머지는 매시 알림 모음(무음)에")
        return True, None

    def _skew(self, level, text):
        m = _SKEW.match(text)
        if not m:
            return False, None
        day = kst(self.clock(), "%Y-%m-%d")
        if abs(int(m[1])) > self.SKEW_LOUD_MS:
            if self.skew_days.get("loud") == day:
                return True, None
            self.skew_days["loud"] = day
            return True, self.forward.send(level, text)
        if self.skew_days.get("note") != day:
            self.skew_days["note"] = day
            self.digest.note("skew", f"서버 시계 어긋남 {round(abs(int(m[1])) / 1000, 2):g}초 (바이낸스 시각으로 계산 중)")
        return True, None

    def _timeout(self, level, text):
        m = _TIMEOUT.match(text)
        if not m:
            return False, None
        now = self.clock()
        self.last_timeout = now
        if (self.last_timeout_loud is None or now - self.last_timeout_loud >= self.TIMEOUT_QUIET_MS
                or self.timeouts_since_loud + 1 >= self.TIMEOUT_RING_EVERY):
            more = self.timeouts_since_loud
            self.timeouts = self.timeouts_since_loud = 0
            self.last_timeout_loud = now
            self.digest.notes.pop("timeouts", None)      # this loud one says it: the digest counts afresh
            if more:
                text = f"{text}\n지난 소리 알림 뒤 {more}번 더 건너뜀 · 계속되면 다시 알림"
            return True, self.forward.send(level, text)
        self.timeouts_since_loud += 1
        if "timeouts" not in self.digest.notes:
            self.timeouts = 0
        self.timeouts += 1
        self.digest.note("timeouts", f"신호 건너뜀 {self.timeouts}번 더 (마지막 {hm(m[1])} 봉: {_tfs(m[2])})")
        return True, None
