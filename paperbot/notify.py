"""Alert delivery. The engine never depends on delivery succeeding.

Telegram wording (owners' redesign 2026-10-04; plain text, Telegram gets no parse_mode): the engine's, the feed's
and the runner's lines stay as they are in the alerts table and the dashboard (English, trading files); they are
worded here, at the Telegram edge (``telegram_text``): a title line '<what> · <whom>', a blank line, short lines,
the KST time last where the line itself has none. One emoji first: the level mark (🚨 CRITICAL, ⚠ WARN) unless
the text already starts with its own emoji (🔔, 📈, ✅ …).

Sound (owners' decision 2026-10-05 21:15 KST, "전부 다 무음으로"): EVERY message goes silent; the level mark and the
first line still say how urgent it is. ``TELEGRAM_SOUND=1`` in the env file brings back the level-based sound
(CRITICAL and WARN ring, INFO silent); the words 'loud' / '소리' below describe that optional mode.

``Router`` holds the live runner's noisy lines (1m gaps, clock skew, signal timeouts) for the hourly digest and
rings only past a threshold; real emergencies (liquidation, job failure, …) are never held: the first CRITICAL of a
step goes at once and the further ones of the same step go together at its end, one loud message ('긴급 알림 N건',
every line kept), so a gap that liquidates 30 accounts is not 30 messages (Telegram allows about 20 a minute in a
group). Telegram's 429 'retry after N s' is honoured: ``TelegramNotifier.send`` (the oneshot jobs) waits once, at
most ``RETRY_WAIT_MAX_S``; the live runner's ``Router`` never sleeps in the trading loop and sends the refused
message again on a later step, once N seconds have passed (review 2026-10-04, M-2).

Paper v4 (owners' D10, 2026-10-05): a paper liquidation's first line says 모의 ('모의 강제청산 · …'; a bundle:
'긴급 N건 · 모의 강제청산 k'), liquidations stay loud for every group; the hourly digest lists the lines of the 36, the
reel and the extras and gives the DeepSeek accounts and the coin flips one count line per group (``Digest``); the
start line names the run and its split by group ('▶️ 봇 시작 · 모의 v4 · 계좌 331개', '매매법 144 · 딥시크 171 · …');
the DeepSeek definitions and the reel are named from paperbot/groups.py (``who``).

Gap pass (G27, G13): the v4 groups' frozen alert texts (paperbot/sigservice.py ``DS_TIMEOUT_TEXT`` and the rest) are
worded here, and the Router keeps the DeepSeek timeouts in the hourly digest (one count line; ONE loud WARN a KST day
once ``Router.DS_TIMEOUT_LOUD`` of them have come). Every message Telegram accepts adds 1 to ``tg_sends(day, kind, n)``
(``count_send``) in its own file tgsends.db beside paper3.db (never in paper3.db).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
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

# Paper v4's group alert texts as patterns (gap G27). The texts are FROZEN in paperbot/sigservice.py (a trading file
# in the shared hash set: fixed at day 0), which also holds these patterns (``DS_TIMEOUT_RE`` ...). The Router takes
# sigservice's own pattern when it can import it (``group_pattern``); these copies serve the processes that never load
# the signal service (failalert, the dashboard, the trade alerts), and tests/test_notify.py checks they equal
# sigservice's, so a changed text fails a test instead of slipping past the digest.
DS_TIMEOUT_RE = r"^\[ds200\] DeepSeek signal workers timed out after (\d+)s; DeepSeek signals skipped at (\d+) for (.+)$"
DS_FAILED_RE = r"^\[ds200\] DeepSeek signals failed at (\d+) \((.*)\); the other groups run on$"
REEL_FAILED_RE = r"^\[reel\] 5m signals \(reel and 5m coin flips\) failed at (\d+) \((.*)\); the other groups run on$"
REFUSED_RE = r"^\[(ds200|reel)\] signal code refused, this group's signals stop \(the other groups run on\): (.*)$"
GROUP_PATTERNS = {"DS_TIMEOUT_RE": DS_TIMEOUT_RE, "DS_FAILED_RE": DS_FAILED_RE, "REEL_FAILED_RE": REEL_FAILED_RE,
                  "REFUSED_RE": REFUSED_RE}


def group_pattern(name: str) -> "re.Pattern":
    """sigservice's frozen pattern ``name`` when the signal service can be imported (the live runner has it loaded
    already), else this module's copy. Never raises for a missing module."""
    try:
        from . import sigservice
        return re.compile(getattr(sigservice, name))
    except Exception:  # noqa: BLE001  (a light process without pandas / the signal service: the copy)
        return re.compile(GROUP_PATTERNS[name])


# The Telegram send counter (gap G13; the dashboard's /api/v4/server shows today's and the week's count). Every
# message Telegram accepted adds 1 to tg_sends(day = KST date 'YYYY-MM-DD', kind = level) in its own file tgsends.db
# beside paper3.db (``TG_SENDS_DB``, or $PAPERBOT_TG_SENDS_DB; the dashboard reads it there, never paper3.db): paper3.db belongs to the live runner (another connection writing it
# could wait on the runner's open transaction inside the trading loop) and the agents' unit sees it read-only. One
# short connection, at most ``TG_SENDS_WAIT_S`` of busy wait, no fsync; a count that cannot be written is skipped,
# never the reason a send fails.
TG_SENDS_DB = "/var/lib/paperbot/tgsends.db"     # its own file next to paper3.db (dash/app.py TG_SENDS_FILE)
TG_SENDS_WAIT_S = 0.2
TG_SENDS_SCHEMA = "CREATE TABLE IF NOT EXISTS tg_sends(day TEXT, kind TEXT, n INTEGER, PRIMARY KEY(day, kind))"


def tg_sends_path() -> Optional[str]:
    """The counter database: $PAPERBOT_TG_SENDS_DB, else ``TG_SENDS_DB`` when its folder exists (none on a dev box)."""
    p = os.environ.get("PAPERBOT_TG_SENDS_DB") or TG_SENDS_DB
    return p if p and os.path.isdir(os.path.dirname(os.path.abspath(p))) else None


def count_send(kind: str, path: Optional[str] = None) -> bool:
    """Add 1 to today's (KST) ``kind`` count. True when written; False (never raises) when there is no counter
    database or it could not be written in ``TG_SENDS_WAIT_S``."""
    try:
        path = path or tg_sends_path()
        if not path:
            return False
        import sqlite3
        day = time.strftime("%Y-%m-%d", time.gmtime(_clock() + 9 * 3600))
        c = sqlite3.connect(path, timeout=TG_SENDS_WAIT_S)
        try:
            c.execute("PRAGMA synchronous=OFF")
            c.execute(TG_SENDS_SCHEMA)
            c.execute("INSERT INTO tg_sends(day, kind, n) VALUES(?, ?, 1) "
                      "ON CONFLICT(day, kind) DO UPDATE SET n = n + 1", (day, str(kind)))
            c.commit()
        finally:
            c.close()
        return True
    except Exception as exc:  # noqa: BLE001  (a count, never a lost message)
        print(f"telegram send counter not written: {type(exc).__name__}: {exc}"[:300], file=sys.stderr)
        return False


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


def _v4_label(strat: str) -> Optional[str]:
    """The paper v4 name of a DeepSeek definition ('딥시크 F9_FVG (FVG·오더 블록)') or of the reel, from the display
    module (paperbot/groups.py, imported only here, when a message is worded); None for anything else or when the
    module cannot be read (names are cosmetic)."""
    try:
        from .groups import label_ko
        return label_ko(strat)
    except Exception:  # noqa: BLE001
        return None


def _ds_ids() -> frozenset:
    """The 44 DeepSeek definition ids (config.DS200_FAMILY, already loaded by the runner); empty when unreadable."""
    global _DS_IDS
    if _DS_IDS is None:
        try:
            from .config import DS200_FAMILY
            _DS_IDS = frozenset(DS200_FAMILY)
        except Exception:  # noqa: BLE001
            return frozenset()
    return _DS_IDS


_DS_IDS: Optional[frozenset] = None


def _reel_name() -> str:
    try:
        from .config import REEL_NAME
        return REEL_NAME
    except Exception:  # noqa: BLE001
        return "REEL_H1"


def who(book: str, kind: Optional[str] = None) -> str:
    """An account as the owners read it: 'S2_ST_ROC@15m' -> '슈퍼트렌드·ROC 15분', a copy 'S2_ST_ROC@1h~c1' ->
    '복제 슈퍼트렌드·ROC 1시간', a new-strategy account 'NL2@15m' -> '새 매매법 NL2 15분', 'RANDOM_3@1h' ->
    '동전 봇 3 1시간' (the 5m ones too: 'RANDOM_1@5m' -> '동전 봇 1 5분'), a DeepSeek account 'F9_FVG@15m' ->
    '딥시크 F9_FVG (FVG·오더 블록) 15분', the reel 'REEL_H1@5m' -> '릴스 5분 단타 (볼린저 20·2 + 200선)' (its name
    already says 5분). ``kind`` (accounts.kind) decides when given; anything unknown is returned as it came."""
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
    name = _strategy_ko().get(strat)
    reel = strat == _reel_name()
    if name is None and (reel or strat in _ds_ids()):
        name = _v4_label(strat)
    name = name or strat
    if kind == "copy" or (kind is None and copy):
        return f"복제 {name} {t}"
    return name if reel and t in name else f"{name} {t}"


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


def _accounts_n() -> Optional[int]:
    """The run's original accounts (paper v4: 331, computed from config.V4_GROUPS, never typed; the runner refuses a
    database whose account set differs from it), or None when unreadable (the text then has no number)."""
    try:
        from .config import V4_ACCOUNTS
        return int(V4_ACCOUNTS)
    except Exception:  # noqa: BLE001
        return None


def _code_error(kind: str, what: str, head: str, body: str) -> str:
    mod = re.search(r"from '([\w.]+)'", what)
    where = f" ({mod[1].rsplit('.', 1)[-1]})" if mod else ""
    n = _accounts_n()
    return f"{head}\n\n{body}\n원래 계좌{f' {n}개' if n else ''}는 그대로 돎\n오류: {kind}{where}"


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


def _group_ko() -> dict:
    """{group: Korean name} of the paper v4 account groups (paperbot/groups.py GROUP_KO); {} when unreadable."""
    try:
        from .groups import GROUP_KO
        return dict(GROUP_KO)
    except Exception:  # noqa: BLE001  (names are cosmetic)
        return {}


def _split(total: int, given: Optional[str]) -> Optional[str]:
    """'매매법 144 · 딥시크 171 · 5분 단타 1 · 동전 15' (+ ' · 추가 계좌 n'): the banner's own split ('core 144, ds200
    171, ...' in brackets) when it carries one, else the paper v4 run shape (config.V4_GROUP_ACCOUNTS, the set the
    runner checks the database against) with the rest of ``total`` as extra accounts; None when neither fits."""
    ko_ = _group_ko()
    if given:
        pairs = re.findall(r"([a-z0-9_]+)\s+(\d+)", given)
        if pairs:
            return " · ".join(f"{ko_.get(g, g)} {n}" for g, n in pairs)
    try:
        from .config import V4_ACCOUNTS, V4_GROUP_ACCOUNTS
        rest = int(total) - int(V4_ACCOUNTS)
        if rest < 0:
            return None
        parts = [f"{ko_.get(g, g)} {n}" for g, n in V4_GROUP_ACCOUNTS.items()]
        return " · ".join(parts + ([f"{ko_.get('extra', 'extra')} {rest}"] if rest else []))
    except Exception:  # noqa: BLE001
        return None


def _run_started(m) -> str:
    """The runner's start line: 'paper v<N> (started|resumed): <n> accounts[ (<split>)], brackets: <src>, taker fee
    <x>%' (paper v4 and later also get the run name and the split by group)."""
    version, fresh, total, given, src, fee = int(m[1]), m[2] == "started", int(m[3]), m[4], m[5], float(m[6])
    run = f"모의 v{version} · " if version >= 4 else ""
    split = _split(total, given) if version >= 4 else None
    return (f"▶️ 봇 {'시작' if fresh else '재시작'} · {run}계좌 {total}개\n\n"
            f"{'새로 시작' if fresh else '이어서 돌림'}\n" + (f"{split}\n" if split else "")
            + f"레버리지 구간: {_brackets_ko(src)}\n수수료 {fee:g}%")


def _tfs(text: str) -> str:
    return ", ".join(TF_KO.get(t.strip(), t.strip()) for t in text.split(","))


def _bong(text: str) -> str:
    """'15m, 30m' -> '15분·30분봉' (T5: the timeframe reads as a bar, never next to the seconds)."""
    return "·".join(TF_KO.get(t.strip(), t.strip()) for t in text.split(",")) + "봉"


# The English lines of the engine, the feed and the runner (trading files, kept as they are: the alerts table,
# the dashboard and the parity golden read them) and the extras' lines, as Telegram words them. Applied per line
# of a message (``ko``); a format may return several lines. Anything else is unchanged.
KO_LINES = (
    (r"\[([^\]]+)\] LIQUIDATED (\w+?)(?:USDT)? (\d+)x lost margin ([\d.]+)",
     lambda m: f"모의 강제청산 · {who(m[1])}\n\n{m[2]} {m[3]}배\n증거금 {money(float(m[4]))} 전액 손실\n{now_kst()}"),
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
    # paper v4's group texts (frozen in sigservice.py, G27): the other groups' signals are never affected
    (DS_TIMEOUT_RE,
     lambda m: f"딥시크 신호 건너뜀 · {hm(m[2])} 봉\n\n딥시크 신호 계산이 {m[1]}초 안에 안 끝남\n건너뛴 봉: {_tfs(m[3])}\n"
               "매매법·5분 단타 신호는 정상 · 봇은 계속 돎"),
    (DS_FAILED_RE,
     lambda m: f"딥시크 신호 실패 · {hm(m[1])} 봉\n\n오류: {m[2]}\n그 봉의 딥시크 신호만 빠짐 · 다른 무리는 계속 돎"),
    (REEL_FAILED_RE,
     lambda m: f"5분 단타 신호 실패 · {hm(m[1])} 봉\n\n오류: {m[2]}\n그 봉의 5분 단타·5분 동전 신호만 빠짐 · "
               "다른 무리는 계속 돎"),
    (REFUSED_RE,
     lambda m: f"{_group_ko().get(m[1], m[1])} 신호 코드 거부 · 이 무리 신호 멈춤\n\n이유: {m[2]}\n"
               "다른 무리는 계속 돎 · 이 무리의 열린 포지션은 규칙대로"),
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
    (r"paper v(\d+) (started|resumed): (\d+) accounts(?: \(([^)]*)\))?, brackets: (.+), taker fee ([\d.]+)%",
     _run_started),
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
_GROUPED = re.compile(r"(\S+) 계좌 경고 (\d+)건 · 계좌 (\d+)개: (.*) \(대시보드 알림 목록\)$")
_SCREEN = "(대시보드 '서버 상태 → 경고')"
_KIND_ORDER = ("파산", "강제청산", "정지", "낙폭", "기타")


def _deepest(texts) -> dict:
    """{account: kind} of per-account lines ('[X@15m] BUST ...', '[X@15m] drawdown ... (level 30%) ...'), each account
    once at its deepest line (a bust over any drawdown, -30% over -20%), so one step crossing two levels is one
    account, not two (T1). Lines without an account id count as one each. Never raises."""
    best: dict = {}
    for k, t in enumerate(texts):
        try:
            m = _BOOK.match(t) or re.match(r"\[([^\]]+)\] ", t)
            acct = m[0] if m else f"#{k}"
            kind = next((ko for key, ko in KO_KINDS if key in t), "기타")
            d = _DD.match(t)
            rank = (len(_KIND_ORDER) - _KIND_ORDER.index(kind), int(d[3]) if d else 0)
        except Exception:  # noqa: BLE001
            acct, kind, rank = f"#{k}", "기타", (0, 0)
        if acct not in best or rank >= best[acct][0]:
            best[acct] = (rank, kind)
    return {a: kind for a, (_, kind) in best.items()}


def group_count(texts) -> tuple:
    """(accounts, '파산 1 · 낙폭 3'): a count-only group's lines counted as accounts at their deepest line (T1)."""
    per: dict = {}
    for kind in _deepest(texts).values():
        per[kind] = per.get(kind, 0) + 1
    kinds = sorted(per, key=lambda k: _KIND_ORDER.index(k) if k in _KIND_ORDER else 99)
    return sum(per.values()), " · ".join(f"{k} {per[k]}" for k in kinds)


def _digest_ko(lines: list[str], extras: bool) -> str:
    busts, dds, other, ops, more, grouped = {}, {}, [], 0, 0, []
    counted: dict[str, list] = {}            # a coin flip's line (listed in the record): counted here (owners' D10)
    for ln in lines:
        b, d, mo, g = _BUST.match(ln), _DD.match(ln), _MORE.match(ln), _GROUPED.match(ln)
        cg = count_only_group(ln) if (b or d) and not extras else None
        if g:
            grouped.append(f"- {g[1]} 계좌 {g[3]}개 · {g[4]}")
        elif cg:
            counted.setdefault(cg, []).append(ln)
        elif b:
            busts[b[1]] = f"- {who(b[1])} · 잔고 {money(_floor(b[2]))} (파산선 {money(float(b[3]))})"
        elif d:
            # one line per account, its deepest level (one step can cross -20% and -30% at the same balance, T1)
            if d[1] not in dds or int(d[3]) >= dds[d[1]][0]:
                dds[d[1]] = (int(d[3]), float(d[2]), f"- {who(d[1])} · -{d[3]}% · 잔고 {money(float(d[4]))}")
        elif mo:
            more = int(mo[1])
        elif ln.startswith("[extra]"):
            ops += 1                       # operational notes (codes, ms boundaries): the count only
        elif ln.strip():
            other.append("- " + _one_line(ko(ln)))
    dds = [x for a, x in dds.items() if a not in busts]      # a bust is deeper than any drawdown level
    busts = list(busts.values())
    for cg, texts in counted.items():
        n, kinds = group_count(texts)
        grouped.append(f"- {COUNT_ONLY_KO.get(cg, cg)} 계좌 {n}개 · {kinds}")
    if extras:
        title = "📉 추가 계좌 경고 · 지난 1시간"
    elif busts or dds or grouped:
        title = "📉 파산·낙폭 모음 · 지난 1시간"
    else:
        title = "📋 알림 모음 · 지난 1시간"
    L = [title]
    if busts:
        L += ["", f"파산 {len(busts)}건"] + busts
    if dds:
        L += ["", f"낙폭 경고 {len(dds)}건"] + [x[2] for x in sorted(dds, key=lambda x: (-x[0], -x[1]))]
    if grouped:
        L += ["", "개수만 (계좌별 줄은 대시보드)"] + grouped
    if other:
        L += ["", f"{'그 밖의 알림' if busts or dds or grouped else '알림'} {len(other)}건"] + other
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
        m = re.match(r"(추가 계좌 )?긴급 알림 (\d+)건(?: · 총 (\d+)건)?$", lines[0])
        if m:
            body = [ln for ln in lines[1:] if ln.strip()]
            items = [_urgent_item(ln) if not _MORE.match(ln) else f"외 {_MORE.match(ln)[1]}건 {_SCREEN}" for ln in body]
            liq = sum(1 for ln in body if re.match(KO_LINES[0][0], ln))
            head = (f"{m[1] or ''}긴급 {m[2]}건" + (f" · 모의 강제청산 {liq}" if liq else "")
                    + (f"\n같은 때 모두 {int(m[3]):,}건 (첫 1건은 따로 보냄)" if m[3] else ""))
            return "\n".join([head, ""] + items + [now_kst()])
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


def sound_on(env=None) -> bool:
    """True only when the env file says TELEGRAM_SOUND=1 (default: every Telegram message is silent)."""
    return str((os.environ if env is None else env).get("TELEGRAM_SOUND", "")).strip() == "1"


def silent(level: str, sound: bool) -> bool:
    """Telegram's disable_notification: always, unless sound is on; then INFO only (CRITICAL and WARN ring)."""
    return (not sound) or level == INFO


class TelegramNotifier:
    """Sends to one chat per level. Token and chat ids come from the
    environment so they never land in the repository:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_CRITICAL, TELEGRAM_CHAT_WARN,
    TELEGRAM_CHAT_INFO (WARN and INFO fall back to CRITICAL's chat)."""

    def __init__(self, timeout: float = 10.0, retry_wait_max: Optional[float] = None, sleep=None) -> None:
        self.retry_wait_max = RETRY_WAIT_MAX_S if retry_wait_max is None else float(retry_wait_max)
        self.sleep = sleep or time.sleep
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        critical = os.environ["TELEGRAM_CHAT_CRITICAL"]
        self.chats = {
            CRITICAL: critical,
            # an empty value in the env file means "not set", not "chat id ''"
            WARN: os.environ.get("TELEGRAM_CHAT_WARN") or critical,
            INFO: os.environ.get("TELEGRAM_CHAT_INFO") or critical,
        }
        self.timeout = timeout
        self.sound = sound_on()

    def send(self, level: str, text: str) -> bool:
        """True when Telegram accepted the message; False when delivery failed (never raises). A 429 'retry after
        N s' with N <= ``retry_wait_max`` waits N seconds and tries once more (the oneshot jobs; the live runner's
        ``Router`` uses ``send_once`` and never sleeps)."""
        ok, wait = self.send_once(level, text)
        if ok or wait is None or wait > self.retry_wait_max:
            return ok
        self.sleep(wait)
        return self.send_once(level, text)[0]

    def send_once(self, level: str, text: str) -> tuple[bool, Optional[float]]:
        """One sendMessage: (accepted, None), or (False, seconds Telegram asked to wait) on a 429, (False, None) on
        any other failure. Never raises."""
        level, body = telegram_text(level, text)
        data = urllib.parse.urlencode({
            "chat_id": self.chats.get(level, self.chats[CRITICAL]),
            "text": body,
            "disable_notification": json.dumps(silent(level, self.sound)),
        }).encode()
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            urllib.request.urlopen(url, data=data, timeout=self.timeout).read()
        except urllib.error.HTTPError as exc:
            wait = retry_after(exc) if exc.code == 429 else None
            print(f"telegram send failed: HTTP {exc.code}" + (f", retry after {wait:g}s" if wait is not None else ""),
                  file=sys.stderr)
            return False, wait
        except Exception as exc:  # delivery failure must not stop trading logic
            print(f"telegram send failed: {type(exc).__name__}", file=sys.stderr)
            return False, None
        count_send(level)               # G13: never raises, never delays past TG_SENDS_WAIT_S
        return True, None


RETRY_WAIT_MAX_S = 30.0          # the longest a blocking send waits on a 429 (Telegram usually asks 5-40 s)
RETRY_DEFAULT_S = 5.0            # a 429 without a readable retry_after


def retry_after(exc: urllib.error.HTTPError) -> float:
    """Seconds a Telegram 429 asks to wait: the JSON body's parameters.retry_after, else the Retry-After header,
    else ``RETRY_DEFAULT_S``. Never raises."""
    try:
        body = json.loads(exc.read() or b"{}")
        v = (body.get("parameters") or {}).get("retry_after")
        if v is not None and float(v) >= 0:
            return float(v)
    except Exception:  # noqa: BLE001
        pass
    try:
        v = (exc.headers or {}).get("Retry-After")
        if v is not None and float(v) >= 0:
            return float(v)
    except Exception:  # noqa: BLE001
        pass
    return RETRY_DEFAULT_S


KO_KINDS = (("BUST", "파산"), ("drawdown", "낙폭"), ("ENGINE HALTED", "정지"), ("LIQUIDATED", "강제청산"))
# Owners' D10 (paper v4): the hourly digest lists the lines of the 36, the reel and the extras; the DeepSeek accounts
# and the coin flips get one count line per group. Worded here, without the display module: the digest runs in the
# runner's loop. The DeepSeek lines become one count line in the digest's own text (``RECORD_COUNT_GROUPS``: 171
# accounts would push the others out of the lines listed); a coin flip's line stays listed in that text exactly as in
# v3 (15 accounts; the record of a v3-shaped run stays byte-identical, tests/test_extras_parity.py) and Telegram
# counts it (``_digest_ko``).
COUNT_ONLY_KO = {"ds200": "딥시크", "flip": "동전"}
RECORD_COUNT_GROUPS = ("ds200",)
_BOOK = re.compile(r"\[([^\]~]+)@([0-9a-z]+)\] ")


def count_only_group(text: str) -> Optional[str]:
    """"ds200" / "flip" for a per-account line ('[F9_FVG@15m] drawdown ...', '[RANDOM_2@5m] BUST: ...') of a group
    the digest only counts; None for every other line (the 36, the reel, copies and new-lab accounts, the Router's
    notes). Never raises."""
    try:
        m = _BOOK.match(text)
        if not m or m[2] not in TF_KO:
            return None
        if re.fullmatch(r"RANDOM_\d+", m[1]):
            return "flip"
        return "ds200" if m[1] in _ds_ids() else None
    except Exception:  # noqa: BLE001
        return None


class Digest:
    """Collects per-account WARN messages (bust, drawdown levels) and sends them
    as one silent message per interval, so the original accounts (and the extras) cannot flood a phone. The
    DeepSeek accounts' lines (owners' D10, ``RECORD_COUNT_GROUPS``) become one count line, so they never push the
    36's and the reel's lines out of the ``max_lines`` listed; the coin flips' lines stay listed here and are counted
    in the Telegram wording, unless they would push another line past ``max_lines``: then they get a count line too.

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
        self.hooks: list = []           # called with now_ms at every flush, first (Router: the step's urgent lines)

    def add(self, text: str) -> None:
        self.items.append(text)

    def note(self, key: str, text: str) -> None:
        self.notes[key] = text

    def flush(self, now_ms: int, force: bool = False):
        for hook in list(self.hooks):
            try:
                hook(now_ms)
            except Exception as exc:  # noqa: BLE001  (a hook never stops the digest)
                print(f"digest hook failed: {type(exc).__name__}: {exc}", file=sys.stderr)
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
        listed, grouped = self.items, {}
        try:
            split = [(t, count_only_group(t)) for t in self.items]
            out = set(RECORD_COUNT_GROUPS)
            # the coin flips' lines stay listed as in v3, unless they would push a line of the 36, the reel or the
            # extras past the ``max_lines`` cut (5m flips cross the drawdown levels early): then they are counted
            # too (jobs review 3), so the cut never hides a core account's bust behind coin-flip lines
            rest = [g for _, g in split if g not in out]
            if "flip" in rest[:self.max_lines] and any(g != "flip" for g in rest[self.max_lines:]):
                out.add("flip")
            if any(g in out for _, g in split):
                listed = [t for t, g in split if g not in out]
                for t, g in split:
                    if g in out:
                        grouped.setdefault(g, []).append(t)
        except Exception:  # noqa: BLE001  (the digest goes out as before)
            listed, grouped = self.items, {}
        lines = listed[:self.max_lines]
        more = len(listed) - len(lines)
        group_lines = []
        for g in sorted(grouped, key=lambda g: list(COUNT_ONLY_KO).index(g) if g in COUNT_ONLY_KO else 99):
            n, kinds = group_count(grouped[g])      # accounts at their deepest line (T1)
            group_lines.append(f"{COUNT_ONLY_KO.get(g, g)} 계좌 경고 {len(grouped[g])}건 · 계좌 {n}개: {kinds}"
                               " (대시보드 알림 목록)")
        text = "\n".join([head] + lines + list(self.notes.values()) + group_lines
                         + ([f"외 {more}건 (대시보드 알림 목록)"] if more else []))
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
    - emergencies (CRITICAL): the first of a step goes at once; further ones of the same step go together at the
      step's end (``flush``, run by the digest flush at the end of every runner step) as ONE loud '긴급 알림 N건'
      message, every line kept (``URGENT_MAX_LINES`` a message);
    - Telegram's 429: the message waits in ``pending`` and is sent on a later step once 'retry after' has passed (at
      most ``RETRY_MAX`` refusals); the trading loop never sleeps for it.
    The alerts table (dashboard) has every line anyway: the runner writes it before sending."""

    GAP_LOUD = 10
    SKEW_LOUD_MS = 5_000
    TIMEOUT_QUIET_MS = 6 * 3_600_000
    TIMEOUT_RING_EVERY = 12
    DS_TIMEOUT_LOUD = 12            # DeepSeek timeouts in a KST day before its ONE loud WARN (about 3 h of 15m bars)
    URGENT_MAX_LINES = 40           # lines of one '긴급 알림 N건' message (about 2,000 characters; Telegram's limit 4,096)
    RETRY_MAX = 3                   # sends of one message refused with 429 before it is dropped (the alerts table has it)
    RETRY_WAIT_MAX_MS = 120_000     # the longest a 429 holds the queue (Telegram asks 5-40 s)
    PENDING_MAX = 100

    def __init__(self, forward: Notifier, digest: Digest, clock=None):
        self.forward, self.digest = forward, digest
        self.clock = clock or (lambda: int(_clock() * 1000))
        # the step's urgent lines: the first CRITICAL of a step goes at once, the rest at the step's end, together
        # (``flush``: the runner flushes the digest at the end of every step, and once more when it stops)
        self.urgent: list[str] = []
        self.urgent_sent = False
        # messages Telegram refused with 429, sent again once ``hold_until`` has passed: [level, text, sends]
        self.pending: list[list] = []
        self.hold_until = 0
        digest.hooks.append(self.flush)
        if digest.forward is forward:           # the digest's own message waits out a 429 too, never sleeping
            digest.forward = _Deliver(self)
        self.gaps: dict[str, int] = {}
        self.gap_loud = False
        self.skew_days: dict[str, str] = {}
        self.last_timeout: Optional[int] = None
        self.last_timeout_loud: Optional[int] = None
        self.timeouts = 0               # digest count (since the digest last went out)
        self.timeouts_since_loud = 0    # further timeouts since the last loud one
        # DeepSeek timeouts (G27): sigservice's frozen DS_TIMEOUT_TEXT, never the core group's timeout rule
        self.ds_re = group_pattern("DS_TIMEOUT_RE")
        self.ds_timeouts = 0            # digest count (since the digest last went out)
        self.ds_day: Optional[str] = None
        self.ds_today = 0
        self.ds_loud = False

    def send(self, level: str, text: str):
        try:
            if level != CRITICAL:
                for rule in (self._gap, self._skew, self._timeout, self._ds_timeout):
                    done, res = rule(level, text)
                    if done:
                        return res
            elif self.urgent_sent:
                self.urgent.append(text)        # a further emergency of this step: with the others at its end
                return None
            else:
                self.urgent_sent = True
        except Exception:  # noqa: BLE001  (a routing rule must never lose an alert)
            pass
        return self.deliver(level, text)

    def flush(self, now_ms: Optional[int] = None) -> None:
        """The step's end (``Digest.flush`` calls it first): the step's further urgent lines as one loud message
        (``URGENT_MAX_LINES`` a message), then the messages Telegram refused once their wait has passed. Never
        sleeps."""
        lines, self.urgent, self.urgent_sent = self.urgent, [], False
        for i in range(0, len(lines), self.URGENT_MAX_LINES):
            part = lines[i:i + self.URGENT_MAX_LINES]
            # the step's first emergency went alone: the bundle says the step's total (T2)
            self.deliver(CRITICAL, part[0] if len(part) == 1 else
                         "\n".join([f"긴급 알림 {len(part)}건 · 총 {len(lines) + 1}건"] + part))
        self.retry()

    def deliver(self, level: str, text: str, sends: int = 0):
        """Send now, or queue behind a 429 still being waited out. Returns the notifier's answer (False = queued
        or failed)."""
        if self.clock() < self.hold_until:
            self._queue(level, text, sends)
            return False
        ok, wait = self._post(level, text)
        if ok is False and wait is not None:
            self._queue(level, text, sends + 1, wait)
        return ok

    def retry(self) -> None:
        """Send the queued messages in order once the wait is over; a new 429 queues the rest again."""
        if not self.pending or self.clock() < self.hold_until:
            return
        todo, self.pending = self.pending, []
        for k, (level, text, sends) in enumerate(todo):
            if self.clock() < self.hold_until:  # refused again: the rest wait with it, in order
                self.pending.extend(todo[k:])
                return
            ok, wait = self._post(level, text)
            if ok is False and wait is not None:
                self._queue(level, text, sends + 1, wait)

    def _queue(self, level: str, text: str, sends: int, wait: Optional[float] = None) -> None:
        if wait is not None:
            self.hold_until = self.clock() + min(int(float(wait) * 1000), self.RETRY_WAIT_MAX_MS)
        if sends >= self.RETRY_MAX or len(self.pending) >= self.PENDING_MAX:
            print(f"telegram: dropped a {level} message after {sends} refused sends (in the alerts table)",
                  file=sys.stderr)
            return
        self.pending.append([level, text, sends])

    def _post(self, level: str, text: str) -> tuple:
        once = getattr(self.forward, "send_once", None)
        if once is not None:
            return once(level, text)
        return self.forward.send(level, text), None

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
            return True, self.deliver(WARN, f"1분봉 빠짐 많음 · {total}분\n\n{per}\n그 코인은 그 1분을 건너뜀 · 봇은 계속 돎\n"
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
            return True, self.deliver(level, text)
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
            return True, self.deliver(level, text)
        self.timeouts_since_loud += 1
        if "timeouts" not in self.digest.notes:
            self.timeouts = 0
        self.timeouts += 1
        self.digest.note("timeouts", f"신호 건너뜀 {self.timeouts}번 더 (마지막 {hm(m[1])} 봉: {_tfs(m[2])})")
        return True, None

    def _ds_timeout(self, level, text):
        """A DeepSeek timeout (owners' D10/D11: DeepSeek is counted, not rung): one count line in the hourly digest;
        ONE loud WARN in a KST day once ``DS_TIMEOUT_LOUD`` of them have come that day (DeepSeek keeps missing
        boundaries). The 36's signals are not affected by it (sigservice runs DeepSeek after the core orders)."""
        m = self.ds_re.match(text)
        if not m:
            return False, None
        day = kst(self.clock(), "%Y-%m-%d")
        if self.ds_day != day:
            self.ds_day, self.ds_today, self.ds_loud = day, 0, False
        self.ds_today += 1
        if "ds_timeouts" not in self.digest.notes:    # the digest went out: count afresh
            self.ds_timeouts = 0
        self.ds_timeouts += 1
        self.digest.note("ds_timeouts", f"딥시크 신호 건너뜀 {self.ds_timeouts}번 (마지막 {hm(m[2])} · {_bong(m[3])} · "
                                        f"{m[1]}초 안에 계산 못 끝냄 · 매매법·5분 단타 신호는 정상)")
        if self.ds_today >= self.DS_TIMEOUT_LOUD and not self.ds_loud:
            self.ds_loud = True
            return True, self.deliver(WARN, f"딥시크 신호 건너뜀 많음 · 오늘 {self.ds_today}번\n\n"
                                            f"마지막 {hm(m[2])} · {_bong(m[3])} · {m[1]}초 안에 계산 못 끝냄\n"
                                            "매매법·5분 단타 신호는 정상 · 봇은 계속 돎\n"
                                            "오늘 나머지는 매시 알림 모음(무음)에")
        return True, None


class _Deliver:
    """The digest's notifier once a Router wraps the same one: its messages go through ``Router.deliver`` (a 429
    queues them instead of waiting in the trading loop)."""

    def __init__(self, router: Router):
        self.router = router

    def send(self, level: str, text: str):
        return self.router.deliver(level, text)
