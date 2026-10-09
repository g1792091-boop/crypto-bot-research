"""Telegram of the demo lab bot ("데모 랩"): the wording (``render``), the outbox (``Outbox``) and the sender.

CONTRACT.md section 5. The engine queues events (``Outbox.queue``), this module words them in Korean at once and
stores the text in the table ``outbox`` of demo.db; ``Outbox.flush`` sends the oldest unsent rows with the demo lab's
own Telegram bot (a NEW bot, never the rule bot's). Delivery never stops the engine: ``flush`` never raises on a
network or Telegram error, it keeps the error text (token removed) on the row and tries again later; a row Telegram
refused 5 times, or one that could not go out for 24 hours, is given up.

Where the messages go: ``DEMOBOT_TG_CHAT`` holds one to four chat ids separated by commas (``parse_chats``): by
default the two owners' private chats with the bot (positive numbers), or a group (-100...), or a mix. Every message
goes to every listed chat; the outbox remembers per row which chats already have it (column ``sent_to``), so a failure
in one chat is retried for that chat only and nobody gets a message twice. Commands (the view log) are read only from
the listed chats: anyone else who finds the bot is ignored.

Wording (the rule bot's Telegram redesign of 2026-10-04 is the reference): plain text (no parse_mode), the first
line says what happened and may start with one emoji, then short lines; times are KST '%m/%d %H:%M'; coins without
the quote ('BTC', not 'BTCUSD'); no emoji inside the lines. Every message is silent (disable_notification), as the
owners chose for the rule bot ("전부 다 무음으로", 2026-10-05). Telegram allows 4096 characters: a long list is cut
and ends with '외 N건은 대시보드에서'.

The token is read from the environment only (DEMOBOT_TG_TOKEN, DEMOBOT_TG_CHAT; /etc/demobot/demobot.env) and is
never logged, printed or stored: every error text goes through ``redact``.

View log ("관점 기록장", CONTRACT.md 7.3): ``render`` words the replies (``view_ack``, ``view_err``, ``view_cancel``,
``view_list``, ``view_help``, ``view_done``; queued like every message, so all listed chats see them: one shared log)
and ``poll_commands`` reads the owners' lines (getUpdates, only the chats of ``DEMOBOT_TG_CHAT``; never raises).

Round 3 (CONTRACT.md 8.1, 8.8, 8.9): ``pass`` says that the 4-week confirmation period started and when it can end
at the earliest; ``confirm_done`` gives its result ("실전 후보" or why it failed); ``warn`` knows the outside watch's
``dead`` / ``rank`` / ``backup`` and ``warn_clear`` says one of them recovered (demobot/watch.py sends both itself);
``daily`` adds the confirmations, the candidates, the measured entry cost against the assumed 2 bps and the market
regime of each coin; ``weekly`` (8.10) is the finished week's review ("주간 회의록"), Monday 09:00 KST.

    python -m demobot.notify test      # sends '🧪 데모 랩 테스트 메시지' to every chat of DEMOBOT_TG_CHAT
    python -m demobot.notify chatid    # lists the people and groups that wrote to the bot (to fill DEMOBOT_TG_CHAT)

Both read the two keys from the environment, else from /etc/demobot/demobot.env (``--env-file``), so the owners
never paste the token anywhere but the server's editor.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from . import grid as G

API = "https://api.telegram.org"
ENV_FILE = "/etc/demobot/demobot.env"
LIMIT = 4000                 # Telegram's limit is 4096 (UTF-16 units; an emoji counts 2): a margin
LINE_MAX = 600               # one list line at most (a runaway setting text cannot eat the message)
MAX_TRIES = 5                # Telegram refused a row this many times: given up (error kept)
MIN_GAP_S = 1.0              # at most one message a second
PER_MINUTE = 18              # per chat: Telegram allows about 20 a minute in one group
MAX_CHATS = 4                # DEMOBOT_TG_CHAT: at most this many chats
TIMEOUT_S = 10.0
BACKOFF_S = 30.0             # after a failure the outbox waits 30 s, 60 s, 120 s ... (at most BACKOFF_MAX_S)
BACKOFF_MAX_S = 900.0
STALE_MS = 24 * 3600_000     # an unsent row older than this is given up (no flood of old ticks after an outage)
WARN_EVERY_MS = 3600_000     # warn: at most one per 'what' per hour
KEEP_MS = 30 * 86400_000     # sent (and given-up) rows are deleted after 30 days
PRUNE_EVERY_MS = 3600_000
MORE = "외 {n}건은 대시보드에서"
TEST_TEXT = "🧪 데모 랩 테스트 메시지"

TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
WINDOW_KO = {"live": "실시간", "26w": "26주", "4w": "4주"}
REASON_KO = {"stop": "손절", "lock": "잠금 익절", "liq": "강제청산", "tp": "익절", "time": "시간 청산",
             "open": "보유 중"}
KIND_KO = {"fixed": "고정", "adaptive": "자동", "friend": "친구 규칙", "flip": "동전 던지기"}
WARN_KO = {"data": "시세 자료 빠짐", "stalled": "멈춤 (새 봉 처리 안 됨)", "error": "오류",
           "disk": "디스크 공간 부족",
           # the outside watch (demobot/watch.py, CONTRACT.md 8.8)
           "dead": "엔진이 멈춤 (15분 계산이 안 돎)", "rank": "순위표가 안 만들어짐", "backup": "밤 백업이 안 됨"}
CLEAR_KO = {"dead": "엔진이 다시 돎", "rank": "순위표가 다시 만들어짐", "backup": "밤 백업이 다시 됨",
            "data": "시세 자료 다시 정상", "stalled": "다시 돎", "error": "오류 없어짐", "disk": "디스크 공간 다시 넉넉함"}
TREND_KO = {"up": "상승 추세", "down": "하락 추세", "range": "횡보"}
VOL_KO = {"high": "변동 큼", "normal": "변동 보통", "low": "변동 작음"}
WEEKDAY_KO = "월화수목금토일"
CONFIRM_DAYS, CONFIRM_MAX_DAYS, CONFIRM_NEED = 28, 56, 20     # CONTRACT.md 8.1 (the wording only)


# ---------------------------------------------------------------- number and name helpers
def _num(x) -> Optional[float]:
    """A finite float, or None (None, NaN, text, bool)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def kst(ms, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(int(ms) / 1000 + 9 * 3600))


def day_ko(ms) -> str:
    """The KST date with its weekday: '11/07(토)'."""
    t = time.gmtime(int(ms) / 1000 + 9 * 3600)
    return f"{time.strftime('%m/%d', t)}({WEEKDAY_KO[t.tm_wday]})"


def share(x) -> str:
    """A 0..1 ratio as a percent (max_dd 0.123 -> '12.3%')."""
    v = _num(x)
    return "-" if v is None else f"{v * 100:.1f}%"


def px(x) -> str:
    """A price with the decimals its size needs: 62,345.1 · 2,345.67 · 2.5123 · 0.21345."""
    v = _num(x)
    if v is None:
        return "-"
    a = abs(v)
    d = 5 if a < 1 else 4 if a < 10 else 2 if a < 1000 else 1
    return f"{v:,.{d}f}"


def usd(x) -> str:
    """Signed dollars and cents: '+$12.30', '-$5.10' (never '$-5.10')."""
    v = _num(x)
    if v is None:
        return "-"
    return f"{'-' if v < 0 else '+'}${abs(v):,.2f}"


def pct(x) -> str:
    """A percent value (4.2 means 4.2 %): '+4.2%'."""
    v = _num(x)
    return "-" if v is None else f"{v:+.1f}%"


def rr(x) -> str:
    v = _num(x)
    return "-" if v is None else f"{v:+.2f}R"


def rate(x) -> str:
    """A win rate given as a share (0.41) or as a percent (41.0): '41%'."""
    v = _num(x)
    if v is None:
        return "-"
    return f"{v * 100 if abs(v) <= 1 else v:.0f}%"


def count(x) -> str:
    v = _num(x)
    return "-" if v is None else f"{int(round(v)):,}"


def coin(c) -> str:
    """'BTCUSD' -> 'BTC' (grid.coin_ko); 'BTCUSDT' -> 'BTC'; 'ALL' -> '전체 코인'."""
    s = str(c or "").strip()
    if s.upper() == "ALL":
        return "전체 코인"
    if s.endswith("USDT"):
        return s[:-4]
    if s.endswith("USD") and len(s) > 3:
        return G.coin_ko(s)
    return s or "?"


def side_ko(s) -> str:
    v = _num(s)
    return "롱" if v is not None and v > 0 else "숏" if v is not None and v < 0 else "?"


def tf_ko(tf) -> str:
    return TF_KO.get(str(tf), str(tf or ""))


def strat_short(s) -> str:
    return G.SHORT.get(str(s), str(s or ""))


def exit_label(e) -> str:
    """'house' / 'tp1.5R_sl2atr' / an exit index -> the Korean label (grid.exit_ko); anything else as given."""
    try:
        if isinstance(e, str) and e in G.EXITS:
            return G.exit_ko(e)
        if isinstance(e, int) and not isinstance(e, bool) and 0 <= e < G.NEXIT:
            return G.exit_ko(e)
    except Exception:  # noqa: BLE001  (labels are cosmetic)
        pass
    return str(e or "")


def _lev_sorted(d) -> list:
    """{'20': x, '30': y} -> [(20, x), (30, y)] by leverage."""
    out = []
    for k, v in (d or {}).items():
        try:
            out.append((int(k), v))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def _clip(s: str, n: int = LINE_MAX) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _fit(head: list, sections: list, tail: list) -> str:
    """head lines, then each (title, item lines) section after a blank line, then tail lines. Longer than ``LIMIT``:
    every section first gets an equal share of the room (what one leaves over goes to the others, in order), the rest
    of its items are left out and '외 N건은 대시보드에서' says how many."""
    sections = [(t, [_clip(x) for x in items]) for t, items in sections if items]
    full = list(head)
    for title, items in sections:
        full += ["", title] + items
    full += tail
    text = "\n".join(full)
    if len(text) <= LIMIT or not sections:
        return text[:LIMIT]
    total = sum(len(items) for _, items in sections)
    room = LIMIT - len("\n".join(head)) - len("\n".join(tail)) - len(MORE) - 24
    take, used = [0] * len(sections), [0] * len(sections)

    def grow(i: int, budget: int) -> None:
        title, items = sections[i]
        while take[i] < len(items):
            add = len(items[take[i]]) + 1 + (len(title) + 2 if take[i] == 0 else 0)
            if used[i] + add > budget:
                return
            used[i] += add
            take[i] += 1

    share = room // len(sections)
    for i in range(len(sections)):
        grow(i, share)
    for i in range(len(sections)):
        grow(i, used[i] + room - sum(used))
    lines = list(head)
    for (title, items), k in zip(sections, take):
        if k:
            lines += ["", title] + items[:k]
    lines += ["", MORE.format(n=total - sum(take))] + list(tail)
    return "\n".join(lines)[:LIMIT]


# ---------------------------------------------------------------- the messages (CONTRACT.md section 5)
def _start(p: dict, now_ms: Optional[int]) -> list:
    n = count(p.get("accounts") or 48)
    if str(p.get("phase")) == "warm":
        L = ["▶️ 데모 랩 시작 · 준비 중", "지난 26주 시세를 채우는 중 (10~15분)", f"계좌 {n}개 · 모의 거래만 · 주문 없음"]
    else:
        L = [f"▶️ 데모 랩 시작 · 계좌 {n}개"]
        ls = _num(p.get("live_start_ms"))
        if ls:
            again = now_ms is not None and now_ms - ls > 30 * 60_000
            L.append(f"{'이어서 돌림 · ' if again else ''}실시간 시작 {kst(ls)}")
        L.append("모의 거래만 · 주문 없음 · 결과는 대시보드에서")
    return L


def _trade_line(t: dict, closed: bool) -> str:
    name = str(t.get("name") or t.get("account") or "?")
    what = f"{coin(t.get('coin'))} {side_ko(t.get('side'))}"
    setting = str(t.get("setting_ko") or "").strip()
    ex = str(t.get("exit_ko") or "").strip()
    rule = " / ".join(x for x in (setting, ex) if x)
    if not closed:
        return f"- {name}: {what} {px(t.get('entry'))}" + (f" · {rule}" if rule else "")
    reason = t.get("reason")
    why = REASON_KO.get(str(reason), str(reason or "청산"))
    r = _num(t.get("R"))
    parts = [f"- {name}: {what} {px(t.get('entry'))} → {px(t.get('exit'))} {why}" + (f" {rr(r)}" if r is not None else "")]
    lev = [f"{L}배 {usd(v)}" for L, v in _lev_sorted(t.get("pnl_by_L")) if _num(v) is not None]
    if lev:
        parts.append(" · ".join(lev))
    if rule:
        parts.append(rule)
    return " · ".join(parts)


def _tick(p: dict) -> str:
    opens = [t for t in (p.get("opens") or []) if isinstance(t, dict)]
    closes = [t for t in (p.get("closes") or []) if isinstance(t, dict)]
    if not opens and not closes:
        return ""
    what = " · ".join(x for x in (f"진입 {len(opens)}" if opens else "", f"청산 {len(closes)}" if closes else "") if x)
    head = [f"🧪 데모 랩 모의 거래 · {what}"]
    bar = _num(p.get("bar_ms"))
    if bar:
        head.append(f"{kst(bar)} 봉")
    return _fit(head, [(f"진입 {len(opens)}", [_trade_line(t, False) for t in opens]),
                       (f"청산 {len(closes)}", [_trade_line(t, True) for t in closes])], [])


def _switch(p: dict, now_ms: Optional[int]) -> str:
    name = str(p.get("name") or p.get("account") or "?")
    items = []
    for it in p.get("items") or []:
        if not isinstance(it, dict):
            continue
        where = coin(it.get("coin") or "ALL")
        L = _num(it.get("L"))
        if L:
            where += f" {int(L)}배"
        line = f"- {where}: {it.get('from_ko') or '-'} → {it.get('to_ko') or '-'}"
        if it.get("why_ko"):
            line += f" · {it['why_ko']}"
        items.append(line)
    tail = [kst(now_ms)] if now_ms else []
    return _fit([f"🔁 설정 바꿈 · {name}"], [(f"바뀐 곳 {len(items)}", items)], tail)


def _daily(p: dict) -> str:
    day = str(p.get("day") or "")
    m = re.fullmatch(r"\d{4}-(\d{2})-(\d{2})", day)
    head = [f"📋 데모 랩 하루 요약 · {m[1]}/{m[2]}" if m else "📋 데모 랩 하루 요약"]
    sub = []
    ld = _num(p.get("live_days"))
    if ld is not None:
        sub.append(f"실시간 {ld:.1f}일째")
    if _num(p.get("trades_24h")) is not None:
        sub.append(f"지난 24시간 거래 {count(p.get('trades_24h'))}건")
    if sub:
        head.append(" · ".join(sub))

    def acct(a) -> str:
        L = _num(a.get("L"))
        money = f" ({usd(a['pnl'])})" if _num(a.get("pnl")) is not None else ""
        return f"- {a.get('name') or a.get('id') or '?'}{f' {int(L)}배' if L else ''} {pct(a.get('pnl_pct'))}{money}"

    best = [acct(a) for a in (p.get("best") or [])[:3] if isinstance(a, dict)]
    worst = [acct(a) for a in (p.get("worst") or [])[:3] if isinstance(a, dict)]
    kinds = []
    for k in p.get("by_kind") or []:
        if not isinstance(k, dict):
            continue
        name = k.get("kind_ko") or KIND_KO.get(str(k.get("kind")), str(k.get("kind") or "?"))
        vals = " · ".join(f"{L}배 {pct(v)}" for L, v in _lev_sorted(k.get("mean_pnl_pct")))
        kinds.append(f"- {name} {vals}".rstrip())
    leaders = []
    for x in (p.get("leaders") or [])[:8]:
        if not isinstance(x, dict):
            continue
        where = f"{strat_short(x.get('strategy'))} {tf_ko(x.get('tf'))}".strip()
        win = WINDOW_KO.get(str(x.get("window")), str(x.get("window") or ""))
        rule = " · ".join(s for s in (str(x.get("label") or ""), exit_label(x.get("exit"))) if s)
        luck = "운보다 나음" if x.get("beats_luck") else "운과 구별 안 됨"
        leaders.append(f"- {where}{f' ({win})' if win else ''}: {rule} · {rr(x.get('mean_R'))} · "
                       f"승률 {rate(x.get('win_rate'))} · {count(x.get('n'))}건 · 운 기준 {rr(x.get('luck95'))} → {luck}")
    regime = []
    for r in p.get("regime") or []:
        if not isinstance(r, dict):
            continue
        tr, vo = r.get("trend"), r.get("vol")
        parts = [TREND_KO.get(str(tr), str(tr)) if tr else "", VOL_KO.get(str(vo), str(vo)) if vo else ""]
        regime.append(f"- {coin(r.get('coin'))} " + (" · ".join(x for x in parts if x) or "아직 모름"))
    passed = int(_num(p.get("passed")) or 0)
    tail = ["", f"우리 기준 통과 {passed}개" + (" (실제 돈은 두 분이 정합니다)" if passed else "")]
    conf, cand = _num(p.get("confirming")), _num(p.get("candidates"))
    if conf is not None or cand is not None:
        tail.append(f"확인 기간 중 {count(conf or 0)}줄 · 실전 후보 {count(cand or 0)}줄"
                    + (" (실제 돈은 두 분이 정합니다)" if cand else ""))
    if "costs" in p:
        tail.append(_cost_line(p.get("costs")))
    tail.append("통과 전에는 실제 돈 금지")
    return _fit(head, [("수익 위", best), ("수익 아래", worst), ("종류별 평균 수익", kinds),
                       ("순위표 1등 vs 운 (운 기준: 무작위 1등의 95% 선)", leaders),
                       ("시장 국면 (4시간 추세 · 15분 변동)", regime)], tail)


def _cost_line(c) -> str:
    """'실제 진입 비용 (호가창, 중앙값) 3.1bp · 가정 2bp보다 1.1bp 큼' (1bp = 0.01%)."""
    c = c if isinstance(c, dict) else {}
    a = _num(c.get("assumed_bps"))
    a = 2.0 if a is None else a
    m = _num(c.get("median_entry_bps"))
    if m is None:
        return f"실제 진입 비용: 아직 잰 거래 없음 (가정 {a:g}bp, 1bp = 0.01%)"
    d = m - a
    cmp_ = "가정과 같음" if abs(d) < 0.05 else f"가정 {a:g}bp보다 {abs(d):.1f}bp {'큼' if d > 0 else '작음'}"
    return f"실제 진입 비용 (호가창, 중앙값) {m:.1f}bp · {cmp_} (1bp = 0.01%)"


def _weekly(p: dict) -> str:
    """The finished week's review (CONTRACT.md 8.10, payload {"week": {...}}), short: the summary sentences, what the
    owners have to decide, one line each for the judgment, the stop rules, the costs and the views."""
    w = p.get("week") if isinstance(p.get("week"), dict) else {}
    label = str(w.get("week_ko") or "").strip()
    head = [f"📅 데모 랩 주간 회의록{f' · {label}' if label else ''}"]
    summary = [_clip(str(x).strip(), 400) for x in (w.get("summary_ko") or []) if str(x or "").strip()][:6]
    head += summary or ["이번 주 요약 없음"]
    decide = [f"- {_clip(str(x).strip(), 400)}" for x in (w.get("decide_ko") or []) if str(x or "").strip()]
    j = w.get("judge") if isinstance(w.get("judge"), dict) else None
    st = w.get("stops") if isinstance(w.get("stops"), dict) else None
    v = w.get("views") if isinstance(w.get("views"), dict) else None
    tail = [""]
    if not decide:
        tail += ["두 분이 정할 것: 없음", ""]
    tail.append(f"판정: 우리 기준 통과 {count(j.get('passed'))}줄 · 확인 기간 중 {count(j.get('confirming'))}줄 · "
                f"실전 후보 {count(j.get('candidates'))}줄" if j else "판정: 기록 없음")
    net = _num(st.get("net_pct")) if st else None
    tail.append(f"정지 규칙: 썼다면 줄마다 평균 {net:+.1f}%p (+면 정지 규칙을 쓴 쪽이 나음)" if net is not None
                else "정지 규칙: 기록 없음")
    tail.append(_cost_line(w.get("costs")))
    if v:
        r24 = _num(v.get("dir24_rate"))
        tail.append(f"관점: {count(v.get('n') or 0)}개 · 끝남 {count(v.get('done') or 0)}개 · 24시간 방향 적중 "
                    + (rate(r24) if r24 is not None else "-"))
    else:
        tail.append("관점: 기록 없음")
    tail += ["자세한 내용: 대시보드의 주간 회의록", "실제 돈을 쓸지는 두 분이 정합니다 (봇은 주문하지 않음)"]
    return _fit(head, [("두 분이 정할 것", decide)], tail)


def _warn(p: dict, now_ms: Optional[int]) -> list:
    what = str(p.get("what") or "")
    L = [f"⚠ 데모 랩 경고 · {WARN_KO.get(what, what or '알림')}"]
    if p.get("detail_ko"):
        L.append(_clip(str(p["detail_ko"]), 1500))
    L.append("규칙봇과는 별개 · 주문 없음")
    if now_ms:
        L.append(kst(now_ms))
    return L


def _warn_clear(p: dict, now_ms: Optional[int]) -> list:
    what = str(p.get("what") or "")
    if what in CLEAR_KO:
        title = CLEAR_KO[what]
    else:
        title = f"'{WARN_KO.get(what, what)}' 경고 풀림" if what else "경고 풀림"
    L = [f"✅ 데모 랩 회복 · {title}"]
    if p.get("detail_ko"):
        L.append(_clip(str(p["detail_ko"]), 1500))
    if now_ms:
        L.append(kst(now_ms))
    return L


def _line_name(p: dict) -> str:
    name = str(p.get("name") or p.get("account") or "?")
    L = _num(p.get("L"))
    return f"{name}{f' {int(L)}배' if L else ''}"


def _pass(p: dict, now_ms: Optional[int]) -> str:
    head = [f"🏁 우리 기준 통과 · {_line_name(p)}"]
    end = _num(p.get("confirm_end_ms"))
    if end:
        head.append(f"4주 확인 기간 시작 · 빨라도 {day_ko(end)}에 끝남 (한국 시간)")
    checks = []
    for c in p.get("checks") or []:
        if not isinstance(c, dict):
            continue
        ok = c.get("ok")
        mark = "" if ok is None else " (충족)" if ok else " (미달)"
        val = f": {c['value_ko']}" if c.get("value_ko") not in (None, "") else ""
        checks.append(f"- {c.get('name_ko') or '?'}{val}{mark}")
    tail = ["", "데모 계좌의 모의 거래 결과입니다"]
    if end:
        tail += ["확인 기간: 지금부터 새로 들어간 거래만 다시 셉니다",
                 f"{CONFIRM_DAYS}일 안에 거래 {CONFIRM_NEED}건이 안 되면 {CONFIRM_NEED}건이 될 때까지 늘어납니다 "
                 f"(최대 {CONFIRM_MAX_DAYS // 7}주)",
                 "확인 기간을 통과해야 '실전 후보'입니다"]
    tail.append("실제 돈을 쓸지는 두 분이 정합니다 (봇은 주문하지 않음)")
    if now_ms:
        tail.append(kst(now_ms))
    return _fit(head, [("기준", checks)], tail)


def _window_lines(p: dict) -> list:
    w = p.get("window") if isinstance(p.get("window"), dict) else {}
    start, dec = _num(p.get("start_ms")), _num(p.get("decided_ms"))
    span = f"{kst(start, '%m/%d')} ~ {kst(dec, '%m/%d')}" if start and dec else \
        f"{kst(start, '%m/%d')}부터" if start else ""
    money = f"수익 {usd(w.get('pnl'))}" + (f" ({pct(w['pnl_pct'])})" if _num(w.get("pnl_pct")) is not None else "")
    L = [f"확인 기간 {span}" if span else "확인 기간"]
    if w:
        L.append(f"거래 {count(w.get('n'))}건 · 평균 {rr(w.get('mean_R'))} · {money} · 최대 낙폭 {share(w.get('max_dd'))}")
    return L


def _confirm_done(p: dict) -> list:
    res = str(p.get("result") or "")
    who = _line_name(p)
    if res == "confirmed":
        return ([f"✅ 확인 기간 통과 · {who}", "이제 '실전 후보'입니다"] + _window_lines(p) +
                ["실전 후보는 봇의 판정일 뿐입니다", "실제 돈을 쓸지는 두 분이 정합니다 (정하기 전에는 실제 돈 금지)"])
    if res == "failed":
        why = str(p.get("why_ko") or "").strip()
        return ([f"❌ 확인 기간 실패 · {who}", _clip(f"이유: {why}", 800) if why else "이유: 기록 없음"]
                + _window_lines(p) +
                ["다음에 우리 기준을 다시 통과하면 확인 기간이 새로 시작됩니다", "실제 돈 금지 그대로"])
    return ([f"🏁 확인 기간 끝 · {who}", "결과를 알 수 없음 · 대시보드의 판정 화면을 보세요"] + _window_lines(p) +
            ["실제 돈 금지 그대로"])


# ---------------------------------------------------------------- the view log ("관점 기록장", CONTRACT.md 7.3)
VIEW_STATUS_KO = {"watching": "지켜보는 중", "done": "끝남", "cancelled": "취소됨"}
FOLLOW_KO = {"touch": "구간 바로 진입", "confirm": "15분 종가 확인 진입"}
FOLLOW_STATUS_KO = {"waiting": "진입 대기", "open": "보유 중", "closed": "청산", "missed": "진입 못 함 (48시간 안에)"}
VIEW_USAGE = "관점 [MM/DD HH:MM] 코인 롱|숏 [A 가격(-가격)] [B …] [C …] [손절 가격] [목표 가격[,가격]] [메모 글]"
VIEW_EXAMPLES = ("관점 BTC 숏 B 84750-84840 C 85300 손절 85600",
                 "관점 10/10 14:00 ETH 롱 A 3,050~3,060 손절 3,010 목표 3,120,3,180 메모 지지선 반등")


def pct2(x) -> str:
    """A small move in percent: '+0.41%'."""
    v = _num(x)
    return "-" if v is None else f"{v:+.2f}%"


def pz(x) -> str:
    """A view price as typed: px() without trailing zeros ('84,750', '0.21345', '2.5')."""
    t = px(x)
    return t.rstrip("0").rstrip(".") if "." in t else t


def _zone(z) -> Optional[str]:
    """[lo, hi] / [x, x] / x -> '84,750~84,840' / '85,300'; None when empty."""
    if z is None:
        return None
    if isinstance(z, (list, tuple)):
        vals = [v for v in (_num(x) for x in z) if v is not None]
        if not vals:
            return None
        lo, hi = min(vals), max(vals)
        return pz(lo) if lo == hi else f"{pz(lo)}~{pz(hi)}"
    return pz(z) if _num(z) is not None else None


def zones_text(zones) -> str:
    """{'A': None, 'B': [84750, 84840], 'C': [85300, 85300]} -> 'B 84,750~84,840 · C 85,300'."""
    if not isinstance(zones, dict):
        return "-"
    parts = [f"{k} {t}" for k in sorted(zones) if (t := _zone(zones[k]))]
    return " · ".join(parts) or "-"


def _view_head(emoji: str, what: str, p: dict) -> str:
    vid = p.get("id")
    num = f" #{vid}" if vid not in (None, "") else ""
    return f"{emoji} 관점{num} {what} · {coin(p.get('coin'))} {side_ko(p.get('side'))}"


def _view_ack(p: dict) -> list:
    L = [_view_head("📝", "기록", p)]
    t = _num(p.get("t_ms"))
    if t:
        L.append(f"{kst(t)} 기준 (한국 시간)")
    L.append(f"구간 {zones_text(p.get('zones'))}")
    stop = _num(p.get("stop"))
    L.append(f"손절 {pz(stop)}" if stop is not None else "손절 없음: 가장 먼 구간에서 0.3% 바깥으로 계산")
    targets = [pz(v) for v in (p.get("targets") or []) if _num(v) is not None]
    L.append(f"목표 {', '.join(targets)}" if targets else "목표 없음: 1R에 절반 · 본전 · 나머지 2R")
    if p.get("memo"):
        L.append(_clip(f"메모 {p['memo']}", 500))
    L += [_clip(f"- {n}", 300) for n in (p.get("notes_ko") or []) if n]
    vid = p.get("id")
    L.append("48시간 동안 따라가며 채점합니다" + (f" · 취소: 취소 {vid}" if vid not in (None, "") else ""))
    return L


def _view_err(p: dict) -> list:
    body = str(p.get("text_ko") or "").strip()
    L = ["❓ 관점을 기록하지 못했습니다"]
    L += [_clip(body, 1500)] if body else [f"쓰는 법: {VIEW_USAGE}", f"예: {VIEW_EXAMPLES[0]}"]
    L.append("자세한 쓰는 법: 관점도움")
    return L


def _view_cancel(p: dict) -> list:
    vid = p.get("id")
    num = f" #{vid}" if vid not in (None, "") else ""
    if p.get("ok"):
        return [f"🗑 관점{num} 취소했습니다", "채점과 결과에서 빠집니다"]
    return [f"❓ 관점{num} 취소 안 됨", "없는 번호이거나 이미 끝난 관점입니다 · 목록: 관점목록"]


def _view_list(p: dict) -> str:
    items = []
    for v in p.get("views") or []:
        if not isinstance(v, dict):
            continue
        t = _num(v.get("t_ms"))
        line = (f"- #{v.get('id', '?')} {kst(t) + ' ' if t else ''}{coin(v.get('coin'))} {side_ko(v.get('side'))}"
                f" · {VIEW_STATUS_KO.get(str(v.get('status')), str(v.get('status') or '?'))}")
        if _num(v.get("dir24")) is not None:
            line += f" · 24시간 {pct2(v['dir24'])}"
        if _num(v.get("touch_R")) is not None:
            line += f" · 구간 진입 {rr(v['touch_R'])}"
        items.append(line)
    if not items:
        return "📒 관점 목록\n아직 기록한 관점이 없습니다 · 쓰는 법: 관점도움"
    return _fit([f"📒 관점 목록 · 최근 {len(items)}개"], [("번호 · 시각 · 코인 · 상태", items)],
                ["", "방향은 말한 쪽으로 움직인 %, 취소: 취소 번호"])


def _view_help() -> list:
    return ["📖 관점 기록장 쓰는 법", "이 봇에게 한 줄로 보냅니다 (두 분 모두 확인 답장을 받습니다):", VIEW_USAGE, "",
            "- 시각은 한국 시간, 빼면 받은 시각", "- 코인: BTC ETH SOL DOGE LTC BCH XRP",
            "- 구간 A·B·C 중 하나 이상, 범위는 84750-84840 또는 84750~84840 (쉼표 가능)",
            "- 손절을 빼면 가장 먼 구간에서 0.3% 바깥, 목표를 빼면 1R에 절반 · 본전 · 나머지 2R", "",
            "예시", VIEW_EXAMPLES[0], VIEW_EXAMPLES[1], "",
            "그 밖에", "- 취소 12: 12번 관점 취소", "- 관점목록: 최근 10개", "- 관점도움: 이 설명", "",
            "채점: 4·24·48시간 뒤 말한 방향으로 움직였는지, 구간에 닿았는지, 두 가지 따라 하기",
            "(구간 바로 진입 / 15분 종가 확인 진입)의 결과. 끝난 관점 30개 전에는 '표본 부족'입니다.",
            "기록은 이 서버에만 남고 GitHub에는 올라가지 않습니다."]


def _follow_line(mode: str, f) -> str:
    name = FOLLOW_KO.get(mode, mode)
    if not isinstance(f, dict) or not f:
        return f"- {name}: -"
    st = str(f.get("status") or "")
    parts = [FOLLOW_STATUS_KO.get(st, st or "-")]
    if st in ("open", "closed") and _num(f.get("entry")) is not None:
        parts.append(f"진입 {pz(f['entry'])}")
    if _num(f.get("R")) is not None:
        parts.append(rr(f["R"]) + (" (진행 중)" if st == "open" else ""))
    if _num(f.get("wallet20_pct")) is not None:
        parts.append(f"20배 잔고 {pct(f['wallet20_pct'])}")
    if f.get("legs_ko"):
        parts.append(str(f["legs_ko"]))
    return _clip(f"- {name}: " + " · ".join(parts), 400)


def _view_done(p: dict) -> list:
    d = p.get("dir") if isinstance(p.get("dir"), dict) else {}
    L = [_view_head("📊", "결과", p),
         "말한 방향으로 " + " · ".join(f"{h} {pct2(d.get(k))}"
                                     for k, h in (("4h", "4시간"), ("24h", "24시간"), ("48h", "48시간"))),
         "구간 도달 " + ("예" if p.get("reached") is True else "아니오" if p.get("reached") is False else "-"),
         _follow_line("touch", p.get("touch")), _follow_line("confirm", p.get("confirm"))]
    if p.get("summary_ko"):
        L.append(_clip(str(p["summary_ko"]), 1000))
    return L


def render(kind: str, payload: dict, now_ms: Optional[int] = None) -> str:
    """The Korean Telegram text of one event (CONTRACT.md sections 5, 7.3 and 8). ``now_ms`` (optional) adds the KST time to
    the kinds that carry no time of their own. Pure (no I/O, no clock); never raises; '' for a tick with no trade."""
    p = payload if isinstance(payload, dict) else {}
    try:
        if kind == "start":
            text = "\n".join(_start(p, now_ms) + ([kst(now_ms)] if now_ms else []))
        elif kind == "tick":
            text = _tick(p)
        elif kind == "switch":
            text = _switch(p, now_ms)
        elif kind == "daily":
            text = _daily(p)
        elif kind == "warn":
            text = "\n".join(_warn(p, now_ms))
        elif kind == "warn_clear":
            text = "\n".join(_warn_clear(p, now_ms))
        elif kind == "pass":
            text = _pass(p, now_ms)
        elif kind == "confirm_done":
            text = "\n".join(_confirm_done(p))
        elif kind == "weekly":
            text = _weekly(p)
        elif kind == "view_ack":
            text = "\n".join(_view_ack(p))
        elif kind == "view_err":
            text = "\n".join(_view_err(p))
        elif kind == "view_cancel":
            text = "\n".join(_view_cancel(p))
        elif kind == "view_list":
            text = _view_list(p)
        elif kind == "view_help":
            text = "\n".join(_view_help())
        elif kind == "view_done":
            text = "\n".join(_view_done(p))
        else:
            body = p.get("detail_ko") or p.get("text") or ""
            text = f"🧪 데모 랩 알림 · {kind}" + (f"\n{body}" if body else "")
    except Exception as exc:  # noqa: BLE001  (a wording slip must never stop the engine)
        text = f"🧪 데모 랩 알림 · {kind}\n(문장을 만들지 못함: {type(exc).__name__})"
    return text[:LIMIT]


# ---------------------------------------------------------------- the chats
def parse_chats(chat) -> list:
    """``DEMOBOT_TG_CHAT`` -> the chat ids as strings: '123456789, 987654321' -> ['123456789', '987654321'] (comma
    separated; blanks and repeats dropped, order kept, at most ``MAX_CHATS``). An int works too."""
    out: list = []
    for part in str(chat if chat is not None else "").split(","):
        c = part.strip()
        if c and c not in out:
            out.append(c)
    return out[:MAX_CHATS]


# ---------------------------------------------------------------- the sender
_TOKEN_RE = re.compile(r"\d{5,}(?::|%3A)[A-Za-z0-9_-]{20,}", re.IGNORECASE)


def redact(text, token: Optional[str] = None) -> str:
    """``text`` without the bot token (its exact value, URL-quoted, and anything shaped like a bot token)."""
    s = str(text)
    t = (token or "").strip()
    if len(t) >= 8:
        s = s.replace(t, "<token>").replace(urllib.parse.quote(t, safe=""), "<token>")
    return _TOKEN_RE.sub("<token>", s)


class TelegramError(Exception):
    """A failed Bot API call; the message never holds the token. ``transient``: a network error, Telegram busy
    (5xx) or the rate limit (429; ``retry_after`` seconds): the row is tried again without counting a try."""

    def __init__(self, msg: str, transient: bool = False, retry_after: Optional[float] = None):
        super().__init__(msg)
        self.transient = transient
        self.retry_after = retry_after


def _http_detail(exc: urllib.error.HTTPError) -> tuple:
    try:
        body = json.loads(exc.read() or b"{}")
        desc = str(body.get("description") or exc.reason)
        ra = (body.get("parameters") or {}).get("retry_after")
        return desc, (float(ra) if ra is not None else None)
    except Exception:  # noqa: BLE001
        return str(getattr(exc, "reason", "") or ""), None


def api(token: str, method: str, params: Optional[dict] = None, timeout: float = TIMEOUT_S):
    """One Bot API call (POST, urllib); its ``result``. Raises ``TelegramError`` (token removed) on any failure."""
    url = f"{API}/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
            body = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        desc, ra = _http_detail(exc)
        raise TelegramError(redact(f"HTTP {exc.code}: {desc}", token)[:300],
                            transient=exc.code == 429 or exc.code >= 500, retry_after=ra) from None
    except Exception as exc:  # noqa: BLE001  (URLError, timeout, reset, bad JSON: the network)
        reason = getattr(exc, "reason", None) or exc
        raise TelegramError(redact(f"{type(exc).__name__}: {reason}", token)[:300], transient=True) from None
    if not isinstance(body, dict) or not body.get("ok"):
        desc = body.get("description") if isinstance(body, dict) else body
        raise TelegramError(redact(f"Telegram: {desc}", token)[:300])
    return body.get("result")


def send_message(token: str, chat: str, text: str, timeout: float = TIMEOUT_S):
    """sendMessage: plain text, silent, no link preview."""
    return api(token, "sendMessage", {"chat_id": chat, "text": text, "disable_web_page_preview": "true",
                                      "disable_notification": "true"}, timeout)


# ---------------------------------------------------------------- the outbox
OUTBOX_SCHEMA = ("CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, ts_ms INTEGER, kind TEXT, payload TEXT, "
                 "text TEXT, sent_ms INTEGER, tries INTEGER DEFAULT 0, error TEXT, sent_to TEXT)")
# sent_to: JSON list of the chats that already have the row (added to an older table by Outbox.__init__)
OUTBOX_INDEX = "CREATE INDEX IF NOT EXISTS outbox_unsent ON outbox(id) WHERE sent_ms IS NULL"


def _chat_list(raw) -> list:
    """The ``sent_to`` column -> list of chat ids ([] when empty or unreadable)."""
    try:
        v = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


class Outbox:
    """The queue of Telegram messages in demo.db (table ``outbox``).

    ``queue(kind, payload)`` words the event now (``render``) and stores it; ``flush(token, chat)`` sends the oldest
    unsent rows to every chat of ``chat`` (``parse_chats``); ``state()`` is the status.json "telegram" block. A row
    is sent (``sent_ms``) once every listed chat has it (``sent_to``). A write made while the caller's own
    transaction is open joins that transaction (the caller commits it); otherwise it is committed at once.
    ``clock`` (seconds), ``sleep`` and ``monotonic`` are injectable for tests."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic):
        self.conn = conn
        self._clock, self._sleep, self._mono = clock, sleep, monotonic
        self._write(OUTBOX_SCHEMA)
        if "sent_to" not in [r[1] for r in self.conn.execute("PRAGMA table_info(outbox)")]:
            self._write("ALTER TABLE outbox ADD COLUMN sent_to TEXT")          # an outbox made before round 3
        self._write(OUTBOX_INDEX)
        self._configured: Optional[bool] = None
        self._hold_until_ms: dict = {}    # chat -> paused until (ms) after a failure
        self._fails: dict = {}            # chat -> failures in a row
        self._sent_at: dict = {}          # chat -> monotonic times of its sends in the last minute
        self._last_send: Optional[float] = None
        self._last_prune_ms = 0

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _write(self, sql: str, args=()) -> None:
        was = self.conn.in_transaction
        self.conn.execute(sql, args)
        if not was and self.conn.in_transaction:
            self.conn.commit()

    # -------------------------------------------------- queue
    def queue(self, kind: str, payload: dict) -> None:
        """Word ``payload`` now and store it unsent. warn: at most one per ``what`` per hour (the later ones are
        dropped); a tick without trades is not stored."""
        payload = payload if isinstance(payload, dict) else {}
        now = self._now_ms()
        if kind == "warn":
            what = str(payload.get("what") or "")
            for (raw,) in self.conn.execute("SELECT payload FROM outbox WHERE kind = 'warn' AND ts_ms > ?",
                                            (now - WARN_EVERY_MS,)):
                try:
                    if str((json.loads(raw) or {}).get("what") or "") == what:
                        return
                except (TypeError, ValueError, AttributeError):
                    continue
        text = render(kind, payload, now_ms=now)
        if not text.strip():
            return
        self._write("INSERT INTO outbox(ts_ms, kind, payload, text, tries) VALUES(?, ?, ?, ?, 0)",
                    (now, str(kind), json.dumps(payload, ensure_ascii=False, default=str), text))

    # -------------------------------------------------- flush
    def _budget(self, chat: str) -> bool:
        """False when ``chat``'s minute budget (``PER_MINUTE``) is used up."""
        now = self._mono()
        self._sent_at[chat] = [t for t in self._sent_at.get(chat, []) if now - t < 60.0]
        return len(self._sent_at[chat]) < PER_MINUTE

    def _pace(self, chat: str) -> None:
        """Wait for the 1-a-second gap (over all chats) and count the send in ``chat``'s minute."""
        if self._last_send is not None:
            gap = MIN_GAP_S - (self._mono() - self._last_send)
            if gap > 0:
                self._sleep(gap)
        self._last_send = self._mono()
        self._sent_at.setdefault(chat, []).append(self._last_send)

    def _ready(self, chat: str, now_ms: int) -> bool:
        return now_ms >= self._hold_until_ms.get(chat, 0) and self._budget(chat)

    def _prune(self, now: int) -> None:
        if now - self._last_prune_ms < PRUNE_EVERY_MS:
            return
        self._last_prune_ms = now
        self._write("DELETE FROM outbox WHERE (sent_ms IS NOT NULL AND sent_ms < ?) "
                    "OR (sent_ms IS NULL AND tries >= ? AND ts_ms < ?)", (now - KEEP_MS, MAX_TRIES, now - KEEP_MS))

    def flush(self, token: str, chat: str, limit: int = 20, send: Optional[Callable] = None) -> int:
        """Send the oldest unsent rows (at most ``limit``) to every chat of ``chat`` (one message a second overall,
        ``PER_MINUTE`` a minute per chat); the number of rows that every chat now has. ``send(token, chat_id, text)``
        raises (or returns False) on failure; default: ``send_message``. A failure keeps its error on the row (token
        removed; with several chats it starts with the chat id), counts a try unless it was transient (network, 5xx,
        429) and pauses that chat only (30 s, doubling, at most 15 min): the other chats go on, and the paused one
        gets its rows later, in order, without anyone getting one twice. Never raises on network, Telegram or
        database errors."""
        token, chats = (token or "").strip(), parse_chats(chat)
        self._configured = bool(token and chats)
        done = 0
        try:
            now = self._now_ms()
            self._prune(now)
            if not self._configured or not any(self._ready(c, now) for c in chats):
                return 0
            self._write("UPDATE outbox SET tries = ?, error = ? WHERE sent_ms IS NULL AND tries < ? AND ts_ms < ?",
                        (MAX_TRIES, "24시간 안에 못 보내 건너뜀", MAX_TRIES, now - STALE_MS))
            rows = self.conn.execute("SELECT id, text, sent_to FROM outbox WHERE sent_ms IS NULL AND tries < ? "
                                     "ORDER BY id LIMIT ?", (MAX_TRIES, max(0, int(limit)))).fetchall()
            send = send or send_message
            for rid, text, sent_to in rows:
                if not any(self._ready(c, self._now_ms()) for c in chats):
                    break                           # every chat paused or out of its minute: the rest waits
                got = _chat_list(sent_to)
                for c in [c for c in chats if c not in got]:
                    if not self._ready(c, self._now_ms()):
                        continue                    # this chat gets the row later (it is still unsent)
                    self._pace(c)
                    try:
                        if send(token, c, text) is False:
                            raise TelegramError("send returned False")
                    except Exception as exc:  # noqa: BLE001  (delivery never stops the engine)
                        err = redact(str(exc) if isinstance(exc, TelegramError) else f"{type(exc).__name__}: {exc}",
                                     token)
                        err = (f"{c}: {err}" if len(chats) > 1 else err)[:300]
                        transient = bool(getattr(exc, "transient", False))
                        self._write("UPDATE outbox SET tries = tries + ?, error = ? WHERE id = ?",
                                    (0 if transient else 1, err, rid))
                        self._fails[c] = self._fails.get(c, 0) + 1
                        wait = min(BACKOFF_MAX_S, BACKOFF_S * 2 ** min(self._fails[c] - 1, 10))
                        ra = _num(getattr(exc, "retry_after", None))
                        self._hold_until_ms[c] = self._now_ms() + int(max(wait, ra or 0.0) * 1000)
                        continue
                    got.append(c)
                    self._write("UPDATE outbox SET sent_to = ? WHERE id = ?", (json.dumps(got), rid))
                    self._fails[c] = 0
                    self._hold_until_ms.pop(c, None)
                if all(c in got for c in chats):
                    self._write("UPDATE outbox SET sent_ms = ? WHERE id = ?", (self._now_ms(), rid))
                    done += 1
        except sqlite3.Error as exc:
            print(f"demobot outbox: {type(exc).__name__}: {exc}"[:300], file=sys.stderr)
        return done

    # -------------------------------------------------- state
    def state(self) -> dict:
        """{"configured", "queued", "last_ok_ms", "last_error"} for status.json. ``configured``: the last flush had a
        token and a chat (before any flush: the environment has both). Never raises."""
        configured = self._configured
        if configured is None:
            configured = bool(os.environ.get("DEMOBOT_TG_TOKEN", "").strip()
                              and parse_chats(os.environ.get("DEMOBOT_TG_CHAT", "")))
        out = {"configured": bool(configured), "queued": 0, "last_ok_ms": None, "last_error": None}
        try:
            c = self.conn
            out["queued"] = int(c.execute("SELECT COUNT(*) FROM outbox WHERE sent_ms IS NULL AND tries < ?",
                                          (MAX_TRIES,)).fetchone()[0])
            ok = c.execute("SELECT MAX(sent_ms), MAX(CASE WHEN sent_ms IS NOT NULL THEN id END) FROM outbox").fetchone()
            out["last_ok_ms"] = int(ok[0]) if ok[0] is not None else None
            err = c.execute("SELECT error FROM outbox WHERE sent_ms IS NULL AND error IS NOT NULL AND id > ? "
                            "ORDER BY id DESC LIMIT 1", (ok[1] or 0,)).fetchone()
            out["last_error"] = err[0] if err else None
        except sqlite3.Error as exc:
            out["last_error"] = f"db: {type(exc).__name__}"
        return out


# ---------------------------------------------------------------- commands from the owners' chats (CONTRACT.md 7.3)
_poll_err: dict = {"text": None, "t": 0.0}


def _poll_log(text: str) -> None:
    """One stderr line per distinct poll error, repeated at most every 10 minutes (an outage is not a log flood)."""
    now = time.time()
    if text != _poll_err["text"] or now - _poll_err["t"] > 600:
        _poll_err.update(text=text, t=now)
        print(f"demobot telegram poll: {text}"[:300], file=sys.stderr)


def poll_commands(token: str, chat: str, offset: int, timeout: int = 25, get: Optional[Callable] = None) -> tuple:
    """getUpdates (long poll ``timeout`` s, ``allowed_updates=["message"]``) from ``offset``; (new offset, items) with
    items ``{"update_id", "text", "date_ms", "from_name"}`` of the text messages of the chats listed in ``chat``
    (``parse_chats``, string compare) only: that is the security boundary, a stranger who finds the bot is ignored.
    The new offset is the last update id + 1 for every update seen, other chats included, so nothing is read twice.
    Never raises: on any error (network, Telegram, a bad answer) the old offset and [] (the error is logged once,
    token removed). ``get(token, method, params, timeout)`` defaults to ``api``."""
    token, want = (token or "").strip(), set(parse_chats(chat))
    try:
        off = int(offset or 0)
    except (TypeError, ValueError):
        off = 0
    if not token or not want:
        return off, []
    try:
        params = {"timeout": str(max(0, int(timeout))), "allowed_updates": json.dumps(["message"])}
        if off:
            params["offset"] = str(off)
        updates = (get or api)(token, "getUpdates", params, float(max(0, int(timeout))) + TIMEOUT_S)
        if not isinstance(updates, list):
            raise TelegramError(f"getUpdates answered {type(updates).__name__}")
        new, items = off, []
        for u in updates:
            if not isinstance(u, dict) or not isinstance(u.get("update_id"), int):
                continue
            new = max(new, u["update_id"] + 1)
            m = u.get("message")
            if not isinstance(m, dict) or not isinstance(m.get("chat"), dict):
                continue
            if str(m["chat"].get("id")) not in want or not isinstance(m.get("text"), str):
                continue
            frm = m.get("from") if isinstance(m.get("from"), dict) else {}
            items.append({"update_id": u["update_id"], "text": m["text"],
                          "date_ms": int(_num(m.get("date")) or 0) * 1000,
                          "from_name": str(frm.get("first_name") or "")})
        return new, items
    except Exception as exc:  # noqa: BLE001  (commands are optional; the engine runs on)
        _poll_log(redact(str(exc) if isinstance(exc, TelegramError) else f"{type(exc).__name__}: {exc}", token))
        return off, []


# ---------------------------------------------------------------- CLI
def read_env_file(path: str, keys=("DEMOBOT_TG_TOKEN", "DEMOBOT_TG_CHAT")) -> dict:
    """KEY=VALUE lines of the env file (quotes removed), only ``keys``; {} when it cannot be read."""
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, _, v = ln.partition("=")
                k, v = k.strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                if k in keys:
                    out[k] = v
    except OSError:
        return {}
    return out


def credentials(env_file: str = ENV_FILE, env=None) -> tuple:
    """(token, chat): the environment first, else the env file."""
    env = os.environ if env is None else env
    token, chat = (env.get("DEMOBOT_TG_TOKEN") or "").strip(), (env.get("DEMOBOT_TG_CHAT") or "").strip()
    if not token or not chat:
        f = read_env_file(env_file)
        token = token or f.get("DEMOBOT_TG_TOKEN", "").strip()
        chat = chat or f.get("DEMOBOT_TG_CHAT", "").strip()
    return token, chat


EDIT = "SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env"


def _hint(err: str) -> str:
    e = err.lower()
    if "401" in e or "unauthorized" in e:
        return "토큰이 틀렸습니다. BotFather의 토큰을 편집기 안에서 다시 넣으세요: " + EDIT
    if "initiate conversation" in e or "chat not found" in e:
        return ("번호가 틀렸거나, 그 사람이 아직 이 봇을 열어 시작(Start)을 누르지 않았습니다 (단체방이면 봇이 그 방에 "
                "없음). 시작을 누른 뒤 python -m demobot.notify chatid 로 번호를 다시 확인하세요.")
    if "blocked by the user" in e:
        return "그 사람이 이 봇을 차단했습니다. 텔레그램에서 봇의 차단을 풀고 시작(Start)을 누르세요."
    if "403" in e or "kicked" in e or "not a member" in e:
        return "봇이 그 단체방에서 빠졌습니다. 봇을 그 방에 다시 넣으세요."
    if "400" in e:
        return "번호가 틀렸습니다. python -m demobot.notify chatid 로 번호를 다시 찾으세요."
    return "서버의 인터넷 연결을 확인하고 잠시 뒤 다시 실행하세요."


def cmd_test(token: str, chat: str, send=send_message, out=print) -> int:
    """Send the test message to every chat of ``chat`` and say how it went for each; 0 when all got it."""
    chats = parse_chats(chat)
    if not token:
        out(f"DEMOBOT_TG_TOKEN이 비어 있습니다. 편집기 안에서 넣으세요: {EDIT}")
        return 2
    if not chats:
        out("DEMOBOT_TG_CHAT이 비어 있습니다. 먼저 번호를 찾으세요: python -m demobot.notify chatid")
        return 2
    text = f"{TEST_TEXT}\n여기로 데모 랩 알림이 옵니다 (모의 거래만, 주문 없음)\n{kst(int(time.time() * 1000))}"
    bad = 0
    for c in chats:
        try:
            send(token, c, text)
        except Exception as exc:  # noqa: BLE001
            err = redact(str(exc), token)
            out(f"보내지 못했습니다: {c} · {err}")
            out(f"  {_hint(err)}")
            bad += 1
            continue
        out(f"보냄: {c}")
    if bad:
        out(f"{len(chats)}곳 중 {bad}곳에 보내지 못했습니다. 위의 줄대로 고친 뒤 다시 하세요.")
        return 1
    out(f"보냈습니다 ({len(chats)}곳). 텔레그램을 확인하세요.")
    return 0


def chats_from_updates(updates) -> dict:
    """{chat id: (title, type, new id or None)} of the chats in getUpdates' result, the latest last."""
    seen: dict = {}
    for u in updates or []:
        if not isinstance(u, dict):
            continue
        for key in ("message", "edited_message", "channel_post", "my_chat_member", "chat_member"):
            m = u.get(key)
            chat = m.get("chat") if isinstance(m, dict) else None
            if not isinstance(chat, dict) or "id" not in chat:
                continue
            title = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
            moved = m.get("migrate_to_chat_id")
            prev = seen.pop(chat["id"], None)
            seen[chat["id"]] = (title or "?", chat.get("type", "?"), moved or (prev[2] if prev else None))
    return seen


def cmd_chatid(token: str, call=api, out=print) -> int:
    """List who wrote to the bot recently: people (private chats, '(개인)') first, then groups."""
    out("텔레그램 번호 찾기 (토큰은 화면에 내지 않습니다)")
    out("먼저: 두 분이 각자 텔레그램에서 이 봇을 열고 시작(Start)을 누르세요 (이미 눌렀으면 아무 말이나 한 번).")
    out("단체방을 쓰려면: 봇을 그 방에 넣고 그 방에 /start@봇아이디 를 보내세요.")
    if not token:
        out(f"DEMOBOT_TG_TOKEN이 비어 있습니다. 편집기 안에서 넣으세요: {EDIT}")
        return 2
    try:
        me = call(token, "getMe", {}) or {}
        if me.get("username"):
            out(f"이 봇의 아이디: @{me['username']}  (방에 보낼 것: /start@{me['username']})")
        updates = call(token, "getUpdates", {"limit": "100", "timeout": "0"}) or []
    except Exception as exc:  # noqa: BLE001
        err = redact(str(exc), token)
        out(f"텔레그램에 묻지 못했습니다: {err}")
        if "409" in err:
            out("다른 곳이 이 봇의 메시지를 읽고 있습니다. 데모 랩 엔진이 켜져 있으면 먼저 끄세요 "
                "(sudo bash /root/demobot-src/deploy/demobot/off.sh), 봇에게 다시 한 번 말한 뒤 이것을 다시 실행합니다. "
                "webhook이 걸린 봇이면 새로 만든 봇을 쓰세요 (규칙봇의 봇은 쓰지 않습니다).")
        else:
            out(_hint(err))
        return 1
    seen = chats_from_updates(updates)
    if not seen:
        out("")
        out("최근 메시지가 없습니다. 각자 봇을 열어 시작(Start)을 누르거나 아무 말이나 보낸 뒤 다시 실행하세요.")
        out("(텔레그램은 지난 24시간 메시지만 보여 줍니다. 엔진이 켜져 있으면 엔진이 먼저 읽어 가므로 off.sh로 끄고 합니다)")
        return 0
    out("")
    order = sorted(seen.items(), key=lambda kv: kv[1][1] != "private")
    for cid, (title, kind, moved) in order:
        if kind == "private":
            line = f"개인 번호 {cid}   이름 {title}   (개인)"
        else:
            line = f"방 번호 {cid}   이름 {title}   ({kind})"
        if moved:
            line += f"   -> 번호가 {moved} 로 바뀜: 이 새 번호를 쓰세요"
        out(line)
    out("")
    out("두 분의 (개인) 번호를 쉼표로 이어 DEMOBOT_TG_CHAT= 뒤에 넣습니다 (예: DEMOBOT_TG_CHAT=123456789,987654321):")
    out(f"  {EDIT}")
    out("단체방을 쓰면 그 방 번호(보통 -100으로 시작)를 넣거나 함께 적습니다 (최대 4개, 규칙봇 알림방이 아닌 방).")
    out("넣은 뒤: python -m demobot.notify test")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demobot.notify",
                                 description="demo lab Telegram: send a test message, or find the chat ids")
    ap.add_argument("cmd", choices=["test", "chatid"])
    ap.add_argument("--env-file", default=ENV_FILE,
                    help="read DEMOBOT_TG_TOKEN / DEMOBOT_TG_CHAT from here when they are not in the environment")
    a = ap.parse_args(argv)
    token, chat = credentials(a.env_file)
    if a.cmd == "test":
        return cmd_test(token, chat)
    return cmd_chatid(token)


if __name__ == "__main__":
    sys.exit(main())
