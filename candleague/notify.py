"""후보 리그 Telegram, in the rule bot's wording (paperbot/notify.py, owners' redesign 2026-10-04): one emoji first, a
title line '<what> · 후보 리그' (or '<what> · <pick>'), a blank line, short lines, the KST time last; plain text; every
message silent (owners 2026-10-05, "전부 다 무음으로"). Sent: a 09:00 KST summary once a day once the league is caught up
(the two pools against their 기본값 and 동전, the next checkpoint, the picks doing best and worst, the counts), a notice
when an account goes bust and one when a core pick falls below its forward band (WATCH_PREREG 3.1), both once the league
is caught up (a catch-up finds them in past prices: they wait for it), and after a start-over that recomputed a span
from the league's start (2026-10-12: from the install time) one '🔄 새로 시작' notice once it has caught up, with the new
record's bust and warning counts in it instead of separate bust and warning notices for that span. Token and chat from
the environment (CANDLEAGUE_TG_TOKEN, CANDLEAGUE_TG_CHAT: 1-4 chat ids, comma separated); without them nothing is sent.
DeepSeek money follows the snapshot (CANDLEAGUE_DS_MONEY, shown by default since the owners' 2026-10-11 request).
The owner-exit league (owners 2026-10-12, the snapshot's ``lineup``) says in the summary, per pool, each exit's trades, win share,
mean per trade and median hold, and how many picks each exit leads by wallet; a bust names the account's kind in the owners' words
('도지 봇 15분 이동평균 이탈')."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Callable, Optional

TAG = "[후보 리그]"                    # log lines; every Telegram title line names 후보 리그
NAME = "후보 리그"
KST = 9 * 3_600_000
SUMMARY_HOUR_KST = 9
TOP = 3
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
ROLE_KO = {"cand": "후보", "quarter": "1/4 크기", "exitonly": "청산만 바꾼 기본값", "base": "기본값", "flip": "동전 던지기"}
META_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "strategies_ko.json")
_KO: dict = {}


def send_telegram(token: str, chat: str, text: str, timeout: float = 15.0) -> None:
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true",
                                   "disable_notification": "true"}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=timeout).read()


def strat_ko(name: str) -> str:
    """The strategy's Korean name (candleague/data/strategies_ko.json), else its code."""
    if not _KO:
        try:
            with open(META_FILE) as fh:
                _KO.update({k: v["ko"] for k, v in json.load(fh)["strategies"].items()})
        except (OSError, ValueError, KeyError):
            _KO["_"] = ""
    return _KO.get(name) or name


def pick_ko(r: dict) -> str:
    """'도지 봇 15분' (+ the role when it is not the pick itself; in the owner-exit league always its kind: '도지 봇 15분 이동평균 이탈')."""
    s = f"{strat_ko(r['name'])} {TF_KO.get(r['tf'], r['tf'])}"
    if r.get("role_ko"):
        return f"{s} {r['role_ko']}"
    return s if r.get("role", "cand") == "cand" else f"{s} {ROLE_KO.get(r['role'], r['role'])}"


def best_counts(doc: dict) -> tuple:
    """Owner-exit league: per pick, which of its accounts has the largest wallet (closed trades; a pick none of whose accounts has
    closed a trade, or with a hidden or tied wallet, is left out): ({role: picks where it leads}, picks counted, picks left out
    for hidden money)."""
    by: dict = {}
    for a in doc.get("accounts") or []:
        if a.get("pick") and a.get("role_ko"):
            by.setdefault(a["pick"], []).append(a)
    lead, n, hidden = {}, 0, 0
    for rows in by.values():
        if any(r.get("wallet") is None for r in rows):
            hidden += any(r.get("trades") for r in rows)
            continue
        if not any(r.get("trades") for r in rows):
            continue
        top = max(r["wallet"] for r in rows)
        win = [r for r in rows if abs(r["wallet"] - top) < 1e-9]
        if len(win) != 1:
            continue
        n += 1
        lead[win[0]["role"]] = lead.get(win[0]["role"], 0) + 1
    return lead, n, hidden


def _start_usd(doc: dict) -> str:
    """The start wallet as "$5,000" / "$1,000": the snapshot's ``equity0``, else this process's ``CANDLEAGUE_EQUITY`` (exits.start_equity)."""
    v = doc.get("equity0") if isinstance(doc, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0 or v == float("inf"):
        from .exits import start_equity
        v = start_equity()
    return f"${v:,.0f}"


def owner_lines(doc: dict) -> list[str]:
    """The owner-exit league's part of the 09:00 summary: per pool every exit's trades, win share, mean per trade (hidden for
    DeepSeek unless its money is shown) and median hold hours, then how many picks each exit leads by wallet."""
    lu = doc.get("lineup") or []
    w = doc.get("watch") or {}
    lines = ["", f"청산 비교 (같은 신호 · 계좌마다 {_start_usd(doc)}에서 시작)"]
    for kind, ko in (("core", "기존 36"), ("ds", "딥시크")):
        p = (w.get("pools") or {}).get(kind)
        if not p or not p.get("picks"):
            continue
        lines += ["", f"{ko} 묶음 (후보 {p['picks']}개)"]
        for x in lu:
            st = (p.get("roles") or {}).get(x["role"]) or {}
            hold = (p.get("hold") or {}).get(x["role"]) or {}
            n, wins = int(st.get("n") or 0), int(st.get("wins") or 0)
            mean = "금액 숨김" if not p.get("money") else f"한 번 평균 {_pct(st.get('mean'))}"
            win = f"승률 {round(100 * wins / n)}%" if n else "승률 -"
            held = "" if hold.get("median_h") is None else f" · 보유 중앙 {hold['median_h']:.1f}시간"
            lines.append(f"  {x['label_ko']}: 거래 {n:,}번 · {win} · {mean}{held}")
    lead, n, hidden = best_counts(doc)
    if n:
        lines += ["", f"후보마다 잔고 1등 ({n}개 후보, 닫힌 거래 기준)",
                  "  " + " · ".join(f"{x['label_ko']} {lead.get(x['role'], 0)}" for x in lu)]
    if hidden:
        lines.append(f"(딥시크 후보 {hidden}개는 금액 숨김 설정이라 1등 세기에서 빠짐)")
    return lines


def _pct(x: Optional[float], dec: int = 2) -> str:
    return "-" if x is None else f"{x * 100:+.{dec}f}%".replace("-", "−")


def _kst(ms: int, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime((ms + KST) / 1000))


def _mark(ok: Optional[bool]) -> str:
    return "—" if ok is None else "▲" if ok else "▼"


def _day(doc: dict, now_ms: int) -> int:
    """The league's day in Korea (the start's KST date = 1일째 = D+0), as the dashboard's day pill counts it."""
    start = doc.get("start_ms") or doc["done_ms"]
    return max(1, (now_ms + KST) // 86_400_000 - (int(start) + KST) // 86_400_000 + 1)


def start_line(doc: dict, now_ms: int) -> str:
    """'D+1 · 10/11 12:00 시작부터 2일째': the league starts at its install time (owners 2026-10-12)."""
    n = _day(doc, now_ms)
    start = doc.get("start_ms")
    return f"D+{n - 1} · {_kst(int(start)) + ' 시작부터 ' if start else ''}{n}일째"


def summary_text(doc: dict, now_ms: Optional[int] = None) -> str:
    """The 09:00 KST summary (rule bot wording)."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    acc = doc["accounts"]
    cands = [r for r in acc if r["role"] == "cand"]
    w = doc.get("watch") or {}
    lines = [f"📊 아침 요약 · {NAME}", "", start_line(doc, now_ms), f"{_kst(doc['done_ms'])} KST까지 처리"]
    today = next((c for c in w.get("checkpoints", []) if -1 < c.get("days_left", 1) <= 0), None)
    if today:                                                 # the checkpoint's day: its numbers are final from 09:00 KST
        lines.append(f"📌 오늘 {today['ko']} 날입니다 · 확정 결과는 대시보드 '점검 진행' 맨 위")
    nxt = next((c for c in w.get("checkpoints", []) if c.get("days_left", 0) > 0), None)
    if nxt:
        lines.append(f"다음 점검: {nxt['ko'].replace(' 점검', '')} {_kst(nxt['ms'], '%m/%d')} · {int(-(-nxt['days_left'] // 1))}일 남음")
    if doc.get("lineup"):                                     # the owner-exit league (owners 2026-10-12): the exits side by side
        lines += owner_lines(doc)
        busts = sum(1 for r in acc if r["bust"])
        open_ = sum(1 for r in acc if r.get("open"))
        warn = sum(1 for j in (doc.get("judge") or {}).values() if (j.get("band") or {}).get("below"))
        lines += ["", f"경고등 {warn} · 파산 {busts} · 열린 포지션 {open_} (계좌 {len(acc)}개)",
                  "후보마다 계좌 비교는 대시보드 '5계좌 비교'"]
        if doc.get("lag_s", 0) > 3600:
            lines.append(f"⚠ 자료가 {doc['lag_s'] // 3600}시간 늦습니다 (바이낸스 연결 확인)")
        lines += [f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"]
        return "\n".join(lines)
    for kind, ko in (("core", "기존 36"), ("ds", "딥시크")):
        p = (w.get("pools") or {}).get(kind)
        if not p:
            continue
        c = p["roles"]["cand"]
        mean = "금액 숨김" if not p.get("money") else f"한 번 평균 {_pct(c['mean'])}"
        lines += ["", f"{ko} 묶음 (후보 {p['picks']}개)", f"  후보 거래 {c['n']:,}번 · {mean}",
                  f"  기본값보다 {_mark(p['c2']['beats_base'])} · 동전보다 {_mark(p['c2']['beats_flip'])}"]
    ranked = sorted((r for r in cands if r["trades"] and r["mean_ret"] is not None), key=lambda r: -r["mean_ret"])
    if ranked:
        def row(i, r):
            wal = "" if r.get("wallet") is None else f" · ${r['wallet']:,.0f}"
            return f"{i}. {pick_ko(r)} · {_pct(r['mean_ret'])} · {r['trades']}번{wal}"
        lines += ["", "잘 되는 후보"] + [row(i + 1, r) for i, r in enumerate(ranked[:TOP])]
        worst = [r for r in ranked[::-1][:TOP] if r not in ranked[:TOP]]
        if worst:
            lines += ["안 되는 후보"] + [row(i + 1, r) for i, r in enumerate(worst)]
    if ranked and max(r["trades"] for r in ranked[:TOP]) < 30:
        lines.append("(거래 30번 전이라 운이 큽니다. 판단은 하지 않습니다)")
    hidden = sum(1 for r in cands if r["mean_ret"] is None and r["trades"])
    if hidden:
        lines.append(f"(딥시크 후보 {hidden}개는 금액 숨김 설정이라 순위에서 빠짐)")
    judge = doc.get("judge") or {}
    ok = sum(1 for j in judge.values() if j.get("verdict") == "ok")
    warn = sum(1 for j in judge.values() if (j.get("band") or {}).get("below"))
    busts = sum(1 for r in acc if r["bust"])
    open_ = sum(1 for r in acc if r.get("open"))
    lines += ["", f"기준 통과 {ok} · 경고등 {warn} · 파산 {busts} · 열린 포지션 {open_}"]
    if doc.get("lag_s", 0) > 3600:
        lines.append(f"⚠ 자료가 {doc['lag_s'] // 3600}시간 늦습니다 (바이낸스 연결 확인)")
    lines += [f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"]
    return "\n".join(lines)


def bust_text(rows: list[dict], now_ms: int) -> str:
    head = f"🚨 {NAME} 파산 · {pick_ko(rows[0])}" if len(rows) == 1 else f"🚨 {NAME} 파산 {len(rows)}개"
    lines = [head, ""]
    if len(rows) > 1:
        lines += [f"- {pick_ko(r)}" for r in rows]
    lines += ["잔고가 $10 아래로 내려가 이 계좌는 멈췄습니다", f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"]
    return "\n".join(lines)


RESTART_SPAN_MS = 30 * 60_000      # a start-over that recomputed more than this from its start says so once


def restart_text(doc: dict, meta: dict, now_ms: int) -> str:
    """'🔄 새로 시작 · 후보 리그': the league started over from its start and has caught up (sent once, then live)."""
    acc = doc["accounts"]
    start = int(meta.get("start_ms") or doc.get("start_ms") or doc["done_ms"])
    busts = sum(1 for r in acc if r["bust"])
    warn = sum(1 for j in (doc.get("judge") or {}).values() if (j.get("band") or {}).get("below"))
    trades = sum(int(r.get("trades") or 0) for r in acc)
    lines = [f"🔄 새로 시작 · {NAME}", "",
             f"{_kst(start)} KST 시작부터 모든 계좌 {_start_usd(doc)}으로 다시 계산했습니다",
             f"{_kst(doc['done_ms'])} KST까지 따라잡았고, 이제 5분마다 이어 갑니다",
             f"새 기록: 닫힌 거래 {trades:,}번 · 파산 {busts} · 경고등 {warn}" + (" (대시보드에서 확인)" if busts or warn else "")]
    if meta.get("backup"):
        lines.append("이전 기록은 서버에 복사해 두었습니다 (대시보드에는 안 나옴)")
    lines += [f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"]
    return "\n".join(lines)


def band_text(r: dict, b: dict, now_ms: int) -> str:
    return "\n".join([f"⚠ {NAME} 경고등 · {pick_ko(r)}", "",
                      f"거래 {b['n']}번 기준 한 번 평균 {_pct(r['mean_ret'])}",
                      f"백테스트 예상 하위 5% {_pct(b['p5'])}보다 낮음",
                      "알림일 뿐 판정 아님 (기존 36 후보 23개 중 1개쯤은 운으로도 켜짐)",
                      f"{NAME} · 종이 매매 (실제 돈 아님)", "", f"{_kst(now_ms)} KST"])


class Notifier:
    """Decides what to send after each pass; remembers what it sent in the league database (kv)."""

    def __init__(self, conn, sender: Optional[Callable[[str], None]] = None):
        self.conn = conn
        token = os.environ.get("CANDLEAGUE_TG_TOKEN")
        chats = [c.strip() for c in os.environ.get("CANDLEAGUE_TG_CHAT", "").split(",") if c.strip()][:4]

        def send_all(text):
            for i, chat in enumerate(chats, 1):         # one chat failing (blocked, stale id, 429) never stops the others
                try:
                    send_telegram(token, chat, text)
                except Exception as exc:  # noqa: BLE001
                    print(f"{TAG} telegram failed for chat {i} of {len(chats)}: {type(exc).__name__}", flush=True)
        self.sender = sender or (send_all if token and chats else None)

    def _get(self, k):
        row = self.conn.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
        return json.loads(row[0]) if row else None

    def _put(self, k, v):
        self.conn.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, json.dumps(v)))
        self.conn.commit()

    def after_pass(self, doc: dict, now_ms: int, caught_up: bool) -> list[str]:
        """Messages for this pass (sent when a sender is set): once the league is caught up, new busts and warning
        lights (or, the first time after a start-over that recomputed a span, one '새로 시작' notice that counts them),
        and the day's summary from 09:00 KST. Returns the texts."""
        out = []
        meta = self._get("meta") or {}
        reset = meta.get("reset_ms")
        restarted = reset is not None and self._get("start_told") != reset      # (re)started, not yet said
        acc = {r["id"]: r for r in doc["accounts"]}
        if caught_up and restarted:
            if reset - int(meta.get("start_ms") or reset) > RESTART_SPAN_MS:
                out.append(restart_text(doc, meta, now_ms))
                self._put("busts_told", sorted(r["id"] for r in doc["accounts"] if r["bust"]))
                self._put("band_told", sorted(cid for cid, j in (doc.get("judge") or {}).items()
                                              if (j.get("band") or {}).get("below") and cid in acc))
            self._put("start_told", reset)
        elif caught_up:
            seen = set(self._get("busts_told") or [])
            new = [r for r in doc["accounts"] if r["bust"] and r["id"] not in seen]
            if new:
                out.append(bust_text(new, now_ms))
                self._put("busts_told", sorted(seen | {r["id"] for r in new}))
            told = set(self._get("band_told") or [])
            low = [(cid, j["band"]) for cid, j in doc.get("judge", {}).items()
                   if j.get("band") and j["band"]["below"] and cid not in told and cid in acc]
            for cid, b in low:
                out.append(band_text(acc[cid], b, now_ms))
            if low:
                self._put("band_told", sorted(told | {cid for cid, _b in low}))
        day = time.strftime("%Y-%m-%d", time.gmtime((now_ms + KST) / 1000))
        hour = time.gmtime((now_ms + KST) / 1000).tm_hour
        if caught_up and hour >= SUMMARY_HOUR_KST and self._get("summary_day") != day:
            out.append(summary_text(doc, now_ms))
            self._put("summary_day", day)
        if self.sender:
            for text in out:
                try:
                    self.sender(text)
                except Exception as exc:  # noqa: BLE001  a Telegram outage never stops the league
                    print(f"[후보 리그] telegram failed: {type(exc).__name__}", flush=True)
        return out
