"""후보 리그 Telegram, in the rule bot's wording (paperbot/notify.py, owners' redesign 2026-10-04): one emoji first, a
title line '<what> · 후보 리그' (or '<what> · <pick>'), a blank line, short lines, the KST time last; plain text; every
message silent (owners 2026-10-05, "전부 다 무음으로"). Sent: a 09:00 KST summary once a day once the league is caught up
(the two pools against their 기본값 and 동전, the next checkpoint, the picks doing best and worst, the counts), a notice
when an account goes bust and one when a core pick falls below its forward band (WATCH_PREREG 3.1). Token and chat from
the environment (CANDLEAGUE_TG_TOKEN, CANDLEAGUE_TG_CHAT: 1-4 chat ids, comma separated); without them nothing is sent.
DeepSeek money follows the snapshot (CANDLEAGUE_DS_MONEY, shown by default since the owners' 2026-10-11 request)."""

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
    """'도지 봇 15분' (+ the role when it is not the pick itself)."""
    s = f"{strat_ko(r['name'])} {TF_KO.get(r['tf'], r['tf'])}"
    return s if r.get("role", "cand") == "cand" else f"{s} {ROLE_KO.get(r['role'], r['role'])}"


def _pct(x: Optional[float], dec: int = 2) -> str:
    return "-" if x is None else f"{x * 100:+.{dec}f}%".replace("-", "−")


def _kst(ms: int, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime((ms + KST) / 1000))


def _mark(ok: Optional[bool]) -> str:
    return "—" if ok is None else "▲" if ok else "▼"


def _day(doc: dict) -> int:
    return max(1, int((doc["done_ms"] - doc.get("start_ms", doc["done_ms"])) // 86_400_000) + 1)


def summary_text(doc: dict, now_ms: Optional[int] = None) -> str:
    """The 09:00 KST summary (rule bot wording)."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    acc = doc["accounts"]
    cands = [r for r in acc if r["role"] == "cand"]
    w = doc.get("watch") or {}
    lines = [f"📊 아침 요약 · {NAME}", "", f"10/01부터 {_day(doc)}일째 · {_kst(doc['done_ms'])} KST까지 처리"]
    today = next((c for c in w.get("checkpoints", []) if -1 < c.get("days_left", 1) <= 0), None)
    if today:                                                 # the checkpoint's day: its numbers are final from 09:00 KST
        lines.append(f"📌 오늘 {today['ko']} 날입니다 · 확정 결과는 대시보드 '점검 진행' 맨 위")
    nxt = next((c for c in w.get("checkpoints", []) if c.get("days_left", 0) > 0), None)
    if nxt:
        lines.append(f"다음 점검: {nxt['ko'].replace(' 점검', '')} {_kst(nxt['ms'], '%m/%d')} · {int(-(-nxt['days_left'] // 1))}일 남음")
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
        """Messages for this pass (sent when a sender is set): new busts, and the day's summary from 09:00 KST once
        the league is caught up. Returns the texts."""
        out = []
        seen = set(self._get("busts_told") or [])
        new = [r for r in doc["accounts"] if r["bust"] and r["id"] not in seen]
        if new:
            out.append(bust_text(new, now_ms))
            self._put("busts_told", sorted(seen | {r["id"] for r in new}))
        told = set(self._get("band_told") or [])
        acc = {r["id"]: r for r in doc["accounts"]}
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
