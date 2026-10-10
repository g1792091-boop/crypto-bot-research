"""후보 리그 Telegram: a 09:00 KST summary once a day and a notice when an account goes bust; every message starts with
[후보 리그] so it is never mistaken for the rule bot's or the demo lab's. Token and chat from the environment
(CANDLEAGUE_TG_TOKEN, CANDLEAGUE_TG_CHAT); without them nothing is sent. DeepSeek money stays hidden (the snapshot's
own rule)."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Callable, Optional

TAG = "[후보 리그]"
KST = 9 * 3_600_000
SUMMARY_HOUR_KST = 9
VERDICT_KO = {"early": "아직 판단 이름", "ok": "기준 통과", "not_yet": "기준 미달"}


def send_telegram(token: str, chat: str, text: str, timeout: float = 15.0) -> None:
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=timeout).read()


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{x * 100:+.2f}%"


def summary_text(doc: dict) -> str:
    acc = {r["id"]: r for r in doc["accounts"]}
    done = time.strftime("%m-%d %H:%M", time.gmtime((doc["done_ms"] + KST) / 1000))
    cands = [r for r in doc["accounts"] if r["role"] == "cand"]
    cands.sort(key=lambda r: (r["mean_ret"] is None, -(r["mean_ret"] or 0), -r["trades"]))
    lines = [f"{TAG} 아침 요약 ({done} KST까지)", f"후보 {len(cands)}개 · 10/01부터 종이 매매", ""]
    for r in cands[:10]:
        j = doc["judge"].get(r["id"], {})
        base = acc.get(f"base-{r['kind']}-{r['name']}-{r['tf']}")
        flip = acc.get(f"{r['id']}-flip")
        if r["mean_ret"] is None:
            money = f"{r['trades']}건 (딥시크: 금액 숨김)"
        else:
            money = (f"{r['trades']}건, 한 번 평균 {_pct(r['mean_ret'])}, 잔고 ${r['wallet']:,.0f}"
                     f" | 기본값 {_pct(base and base['mean_ret'])}, 동전 {_pct(flip and flip['mean_ret'])}")
        lines.append(f"- {r['name']} {r['tf']} ({r['exit_ko']}): {money} · {VERDICT_KO.get(j.get('verdict'), '-')}")
    if len(cands) > 10:
        lines.append(f"… 외 {len(cands) - 10}개는 대시보드에서")
    busts = [r["id"] for r in doc["accounts"] if r["bust"]]
    if busts:
        lines += ["", f"파산한 계좌 {len(busts)}개: " + ", ".join(busts[:8])]
    if doc.get("lag_s", 0) > 3600:
        lines += ["", f"주의: 자료가 {doc['lag_s'] // 3600}시간 늦습니다(바이낸스 연결 확인 필요)"]
    return "\n".join(lines)


class Notifier:
    """Decides what to send after each pass; remembers what it sent in the league database (kv)."""

    def __init__(self, conn, sender: Optional[Callable[[str], None]] = None):
        self.conn = conn
        token, chat = os.environ.get("CANDLEAGUE_TG_TOKEN"), os.environ.get("CANDLEAGUE_TG_CHAT")
        self.sender = sender or ((lambda text: send_telegram(token, chat, text)) if token and chat else None)

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
            out.append(f"{TAG} 파산: " + ", ".join(f"{r['name']} {r['tf']} ({r['role']})" for r in new)
                       + " - 잔고가 $10 아래로 내려가 이 계좌는 멈췄습니다(종이 매매, 실제 돈 아님)")
            self._put("busts_told", sorted(seen | {r["id"] for r in new}))
        day = time.strftime("%Y-%m-%d", time.gmtime((now_ms + KST) / 1000))
        hour = time.gmtime((now_ms + KST) / 1000).tm_hour
        if caught_up and hour >= SUMMARY_HOUR_KST and self._get("summary_day") != day:
            out.append(summary_text(doc))
            self._put("summary_day", day)
        if self.sender:
            for text in out:
                try:
                    self.sender(text)
                except Exception as exc:  # noqa: BLE001  a Telegram outage never stops the league
                    print(f"[후보 리그] telegram failed: {type(exc).__name__}", flush=True)
        return out
