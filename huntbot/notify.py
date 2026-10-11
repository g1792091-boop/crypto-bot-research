"""huntbot Telegram, in the candidate league's wording (candleague/notify.py): one emoji first, a title line
'<what> · 추세 사냥', a blank line, short lines, the KST time last; plain text; every message silent.

Only the lineup accounts are told about (entries, adds, exits); all other systems are recorded without messages.
Sent: an entry / add / exit of a lineup account (only once the runner is caught up: a catch-up or a newly filled lineup
marks what already happened as told without sending it, and sends one "lineup set" message instead); a lineup
account's closed trade that changed later (data for the past came in late, runner.py ``record_trades``); the 09:00 KST
summary once a day; a warning when the bars are more than 30 minutes late or the feed has not been heard from for 30
minutes (at most every 3 hours) and one when they are back. The health check (lag warning, summary) runs on every loop
of the runner, not only after a cycle: a feed that stopped moves no mark and starts no cycle. DeepSeek accounts (D11):
coin, side, add count and win / loss only, never money, price or stop.
Token and chats from HUNTBOT_TG_TOKEN / HUNTBOT_TG_CHAT (1-4 chat ids, comma separated); without them nothing is
sent (the texts are still made, for the tests and the log).
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Callable, Optional

from . import config as CFG
from . import systems as S

NAME = CFG.NAME
KST = 9 * 3_600_000
SUMMARY_HOUR_KST = 9
LAG_WARN_S = 30 * 60
LAG_WARN_MS = LAG_WARN_S * 1000
LAG_REPEAT_MS = 3 * 3_600_000
HEALTH_EVERY_MS = 30_000
FRESH_MS = 2 * 3_600_000            # an entry / exit older than this when first seen is marked told, not sent
REASON_KO = {"stop": "손절선", "stop_gap_open": "손절선 아래에서 시작한 봉 (갭)", "liquidation": "청산가 도달",
             "period_end_marked": "보유 중", "coin_end": "코인 거래 종료", "bust_close": "계좌 파산으로 정리"}
SRC_KO = {"first_stop": "첫 손절선", "add_moved_stop": "추가 진입으로 올린 손절선", "chandelier": "추적 손절선 (샹들리에)"}
SIDE_KO = {1: "롱", -1: "숏"}


def send_telegram(token: str, chat: str, text: str, timeout: float = 15.0) -> None:
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true",
                                   "disable_notification": "true"}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=timeout).read()


def _kst(ms: int, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime((ms + KST) / 1000))


def _px(x) -> str:
    if x is None:
        return "-"
    a = abs(x)
    return f"{x:,.{5 if a < 1 else 4 if a < 10 else 2 if a < 1000 else 1}f}"


def _usd(x, sign: bool = False) -> str:
    if x is None:
        return "-"
    s = f"${abs(x):,.2f}"
    return ("+" if x > 0 and sign else "−" if x < 0 else "") + s


def _coin(sym: str) -> str:
    return sym[:-4] if sym.endswith("USDT") else sym


def _dur(ms: int) -> str:
    m = max(0, int(ms // 60_000))
    if m < 60:
        return f"{m}분"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}시간 {m}분" if m else f"{h}시간"
    d, h = divmod(h, 24)
    return f"{d}일 {h}시간" if h else f"{d}일"


def acct_title(a: dict) -> str:
    name = (a.get("name") or "바구니") if a.get("basket") else S.label_ko(a["parts"][0][0])
    v = S.variants()[a["variant"]]["ko"]
    return f"{a['label']} · {name} ({v})"


def entry_text(a: dict, t: dict, now_ms: int) -> str:
    ds = a["ds"]
    lines = [f"🟢 진입 · {NAME}", acct_title(a), "", f"{_coin(t['coin'])} {SIDE_KO[t['side']]}"
             + ("" if ds else f" · {t['lev']}배")]
    if not ds:
        lines += [f"진입 {_px(t['fill'])} · 첫 손절 {_px(t['first_stop'])}",
                  f"위험 {_usd(t['u'])} (그때 지갑 {_usd(t['eq_entry'])})"]
    lines += [f"신호 봉 마감 {_kst(t['signal_close_ms'])} · 체결 봉 {_kst(t['in_ms'])}"]
    if ds:
        lines.append("(딥시크 매매법: 금액·가격은 보이지 않게 정해져 있음)")
    lines += [f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"]
    return "\n".join(lines)


def add_text(a: dict, t: dict, n: int, now_ms: int) -> str:
    lines = [f"➕ 추가 진입 {n}번째 · {NAME}", acct_title(a), "", f"{_coin(t['coin'])} {SIDE_KO[t['side']]}"]
    if not a["ds"] and t.get("stop_now") and t["stop_now"].get("stop") is not None:
        lines.append(f"지금 손절선 {_px(t['stop_now']['stop'])} ({SRC_KO.get(t['stop_now']['source'], '')})")
    lines += [f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"]
    return "\n".join(lines)


def exit_text(a: dict, t: dict, now_ms: int) -> str:
    ds = a["ds"]
    win = (t.get("pnl") or 0) > 0
    lines = [f"{'✅' if win else '🔴'} 청산 · {NAME}", acct_title(a), "",
             f"{_coin(t['coin'])} {SIDE_KO[t['side']]} · {REASON_KO.get(t['reason'], t['reason'])}"
             + (f" ({SRC_KO.get(t['stop_source'], '')})" if t["reason"] == "stop" else "")]
    if ds:
        lines.append(f"{'이김' if win else '짐'} · 추가 진입 {t['adds']}번")
    else:
        r = t.get("r_mult")
        lines += [f"손익 {_usd(t['pnl'], True)}" + (f" ({r:+.2f}R)" if r is not None else "")
                  + f" · 추가 진입 {t['adds']}번", f"진입 {_px(t['fill'])} → 청산 {_px(t['exit_px'])}"]
    lines += [f"보유 {_dur(t['out_ms'] - t['in_ms'] + 300_000)}", f"{NAME} · 종이 매매 (실제 돈 아님)", "",
              f"{_kst(now_ms)} KST"]
    return "\n".join(lines)


def lineup_set_text(R, now_ms: int) -> str:
    accts = R.lineup["accounts"]
    lines = [f"📋 라인업 · {NAME}", ""]
    if not accts:
        lines.append("라인업이 비었습니다. 전체 시스템 기록은 그대로 계속됩니다.")
    else:
        lines.append(f"계좌 {len(accts)}개를 화면 맨 앞에 보여 주고 진입·청산을 알립니다.")
        lines += [f"{i}. {acct_title(a)}" for i, a in enumerate(accts, 1)]
        lines.append("10/01부터의 기록은 이미 있습니다 (지난 체결은 따로 보내지 않음, 대시보드 '라인업').")
    lines += [f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"]
    return "\n".join(lines)


def changed_text(R, changes: list, now_ms: int) -> str:
    """Lineup accounts' closed trades that a later cycle gave differently (D11: no money for DeepSeek accounts)."""
    by_id = {a["id"]: a for a in R.lineup.get("accounts") or []}
    lines = [f"🔁 지난 거래 다시 계산됨 · {NAME}", "", "늦게 들어온 과거 자료(멈췄던 코인의 5분봉 등)로 다시 계산하니",
             "이미 닫힌 거래가 바뀌었습니다. 기록에는 처음 본 것과 바뀐 것이 모두 남습니다.", ""]
    kind_ko = {"changed": "바뀜", "gone": "사라짐", "back": "다시 나타남"}
    for c in changes[:6]:
        a = by_id.get(c["account"].split(":", 1)[1])
        coin, side, in_ms = c["tkey"].split("|")[:3]
        head = f"{acct_title(a)} · " if a else ""
        line = f"{head}{_coin(coin)} {SIDE_KO.get(int(side), side)} (진입 {_kst(int(in_ms))}) {kind_ko.get(c['kind'], c['kind'])}"
        t = c.get("trade")
        if t and a and not a["ds"] and t.get("pnl") is not None:
            line += f" · 지금 손익 {_usd(t['pnl'], True)}"
        lines.append(line)
    if len(changes) > 6:
        lines.append(f"외 {len(changes) - 6}건 (대시보드 '상태')")
    lines += [f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"]
    return "\n".join(lines)


def summary_text(R, now_ms: int, lineup_res: dict, counts: dict, lag_ms: Optional[int] = None) -> str:
    day = max(1, int((now_ms - R.fwd) // CFG.DAY) + 1)
    lines = [f"📊 아침 요약 · {NAME}", "", f"10/01부터 {day}일째 · {_kst(R.done_ms or now_ms)} KST까지 처리"]
    accts = R.lineup["accounts"]
    if not accts:
        lines += ["", "라인업 아직 없음 (픽 결과를 기다리는 중)"]
    else:
        lines += ["", f"라인업 {len(accts)}개 (정식 {sum(a['label'] == '정식' for a in accts)} · "
                      f"참고 {sum(a['label'] == '참고' for a in accts)})"]
        for i, a in enumerate(accts, 1):
            res = lineup_res.get(a["id"])
            if res is None:
                lines.append(f"{i}. {acct_title(a)} · 계산 오류")
                continue
            tr = res["trades"]
            closed = [t for t in tr if not t["open"]]
            wins = sum((t.get("pnl") or 0) > 0 for t in closed)
            open_n = len(tr) - len(closed)
            if a["ds"]:
                lines.append(f"{i}. {acct_title(a)} · 거래 {len(closed)} (이김 {wins}) · 열림 {open_n}")
            else:
                eq = res["equity_now"]
                lines.append(f"{i}. {acct_title(a)} · {_usd(eq)} (×{eq / 5000:.2f}) · 거래 {len(closed)} "
                             f"(이김 {wins}) · 열림 {open_n}")
    lines += ["", f"전체 기록 {counts.get('systems', 0)}개 시스템 · 열린 포지션 {counts.get('open', 0)}개"]
    if counts.get("trades_changed"):
        lines.append(f"나중에 다시 계산되어 바뀐 거래 {counts['trades_changed']}건 (대시보드 '상태')")
    if lag_ms is None:
        lag_ms = now_ms - R.done_ms if R.done_ms else None
    lag = lag_ms // 60_000 if lag_ms is not None else None
    if lag is not None and lag > 30:
        lines.append(f"⚠ 자료가 {lag}분 늦습니다")
    lines += [f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"]
    return "\n".join(lines)


class Notifier:
    """Decides what to send; remembers what it told in run.db (kv)."""

    def __init__(self, conn, sender: Optional[Callable[[str], None]] = None):
        self.conn = conn
        token = os.environ.get("HUNTBOT_TG_TOKEN")
        chats = [c.strip() for c in os.environ.get("HUNTBOT_TG_CHAT", "").split(",") if c.strip()][:4]

        def send_all(text):
            for i, chat in enumerate(chats, 1):
                try:
                    send_telegram(token, chat, text)
                except Exception as exc:  # noqa: BLE001  one chat failing never stops the others
                    print(f"{CFG.TAG} telegram failed for chat {i} of {len(chats)}: {type(exc).__name__}", flush=True)
        self.sender = sender or (send_all if token and chats else None)
        self.sent: list = []
        self.last_lineup_res: dict = {}

    def _get(self, k, d=None):
        row = self.conn.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
        return json.loads(row[0]) if row else d

    def _put(self, k, v):
        self.conn.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, json.dumps(v)))
        self.conn.commit()

    def _send(self, texts: list) -> None:
        self.sent += texts
        if self.sender:
            for t in texts:
                try:
                    self.sender(t)
                except Exception as exc:  # noqa: BLE001
                    print(f"{CFG.TAG} telegram failed: {type(exc).__name__}", flush=True)

    @staticmethod
    def keys_of(a: dict, t: dict) -> list:
        base = f"{a['id']}|{t['coin']}|{t['in_ms']}"
        out = [(base + "|in", "in", 0)]
        out += [(base + f"|add{n}", "add", n) for n in range(1, int(t.get("adds") or 0) + 1)]
        if not t["open"]:
            out.append((base + "|out", "out", 0))
        return out

    def after_lineup(self, R, mk, complete_ms: int, lineup_res: dict, caught_up: bool) -> list:
        now = R.now_ms()
        self.last_lineup_res = lineup_res
        told = dict(self._get("told", {}))
        lh = S.lineup_hash(R.lineup["accounts"])
        silent = self._get("lineup_hash") != lh or not caught_up
        texts = []
        for a in R.lineup["accounts"]:
            res = lineup_res.get(a["id"])
            if res is None:
                continue
            for t in res["trades"]:
                for key, what, n in self.keys_of(a, t):
                    if key in told:
                        continue
                    told[key] = now
                    when = t["in_ms"] if what != "out" else t["out_ms"]
                    if silent or now - when > FRESH_MS:
                        continue
                    if what == "in":
                        texts.append(entry_text(a, t, now))
                    elif what == "add":
                        texts.append(add_text(a, t, n, now))
                    else:
                        texts.append(exit_text(a, t, now))
        if self._get("lineup_hash") != lh:
            self._put("lineup_hash", lh)
            if R.lineup["accounts"] or self._get("lineup_hash_seen"):
                texts.insert(0, lineup_set_text(R, now))
            self._put("lineup_hash_seen", True)
        told = {k: v for k, v in told.items() if now - v < 60 * CFG.DAY}
        self._put("told", told)
        self._send(texts)
        return texts

    def after_trade_changes(self, R, changes: list) -> list:
        """Lineup accounts' closed trades that changed in this cycle (one message)."""
        if not changes:
            return []
        texts = [changed_text(R, changes, R.now_ms())]
        self._send(texts)
        return texts

    @staticmethod
    def _feed_state(R) -> tuple:
        """(the feed's mark, the feed's last heartbeat ms): from the store when the runner has one (a test stub may
        not: then the runner's own last mark)."""
        st = getattr(R, "store", None)
        if st is None:
            return getattr(R, "done_ms", None), None
        try:
            hb = (st.heartbeats().get("feed") or {}).get("ts_ms")
            return st.complete_ms(), hb
        except Exception:  # noqa: BLE001  a busy store: try again next loop
            return getattr(R, "done_ms", None), None

    def check_health(self, R, now: Optional[int] = None, force: bool = False) -> list:
        """Every loop of the runner: the lag warning (the feed's mark more than 30 minutes behind the clock, or no
        heartbeat from the feed for 30 minutes), the 'back' message, the 09:00 KST summary."""
        now = R.now_ms() if now is None else now
        if not force and now - getattr(self, "_health_ms", -HEALTH_EVERY_MS) < HEALTH_EVERY_MS:
            return []
        self._health_ms = now
        texts = []
        mark, hb = self._feed_state(R)
        lag_ms = now - int(mark) if mark is not None else None
        started = getattr(R, "started_ms", None)
        quiet_ms = now - int(hb) if hb is not None else (now - int(started) if started is not None and mark is None
                                                          else None)
        problem = None
        if lag_ms is not None and lag_ms > LAG_WARN_MS:
            problem = f"바이낸스 5분봉이 {lag_ms // 60_000}분 늦습니다"
        elif quiet_ms is not None and quiet_ms > LAG_WARN_MS:
            problem = f"자료 수집(huntbot-feed)에서 {quiet_ms // 60_000}분째 소식이 없습니다"
        warned = self._get("lag_warned_ms")
        if problem:
            if warned is None or now - warned > LAG_REPEAT_MS:
                texts.append("\n".join([f"⚠ 자료 지연 · {NAME}", "", problem,
                                        "서버의 huntbot-feed 상태를 확인하세요 (대시보드 '상태', "
                                        "journalctl -u huntbot-feed -n 50 --no-pager)",
                                        f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now)} KST"]))
                self._put("lag_warned_ms", now)
        elif warned is not None:
            texts.append("\n".join([f"✅ 자료 다시 들어옴 · {NAME}", "",
                                    f"지금 지연 {max(0, lag_ms or 0) // 60_000}분",
                                    f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now)} KST"]))
            self._put("lag_warned_ms", None)
        day = time.strftime("%Y-%m-%d", time.gmtime((now + KST) / 1000))
        hour = time.gmtime((now + KST) / 1000).tm_hour
        if getattr(R, "done_ms", None) and hour >= SUMMARY_HOUR_KST and self._get("summary_day") != day:
            texts.append(summary_text(R, now, self.last_lineup_res, getattr(R, "last_counts", {}) or {}, lag_ms))
            self._put("summary_day", day)
        self._send(texts)
        return texts

    def after_cycle(self, R, info: dict, caught_up: bool) -> list:
        """After a cycle: the same health check (the runner's loop also runs it when no cycle comes)."""
        return self.check_health(R, force=True)
