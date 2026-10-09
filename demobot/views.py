"""View log ("관점 기록장", CONTRACT 7.3): owners type someone's market view into the Telegram group in one line;
the engine records it, follows the market on 15m bars and scores it with rules fixed before the first view.

Nothing here is specific to any person; the views themselves stay in the server database (table ``views``).
"""
from __future__ import annotations

import json
import math
import re
import time
from typing import Optional

import numpy as np

from . import accounts as A
from . import grid as G

M15 = 15 * 60 * 1000
H_MS = 3600 * 1000
KST = 9 * H_MS
WATCH_H = 48
NEED = 30
TAKER, SLIP, MAKER = 0.0005, 0.0002, 0.0002
DEFAULT_STOP_PAD = 0.003
L20 = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS views(id INTEGER PRIMARY KEY AUTOINCREMENT, t_ms INTEGER, entered_ms INTEGER, coin TEXT,
  side INTEGER, zones TEXT, stop REAL, targets TEXT, memo TEXT, status TEXT, text TEXT, from_name TEXT,
  done_sent INTEGER DEFAULT 0);
"""

RULES_KO = [
    "기준가: 관점 시각 다음 15분봉의 시가",
    "방향: 4시간·24시간·48시간 뒤 말한 방향으로 움직였으면 적중",
    "구간 도달: 48시간 안에 가장 가까운 구간 끝에 닿았는가",
    "구간 바로 진입: 가장 가까운 구간 끝에 지정가(메이커 수수료)",
    "15분 종가 확인 진입: 구간에 닿은 뒤 15분봉 종가가 구간 밖(진입 방향)으로 마감하면 그 종가에 진입",
    "손절: 적힌 값, 없으면 가장 먼 구간 바깥 0.3% · 목표: 적힌 값(첫째 절반, 둘째 나머지), 없으면 1R 절반·본전·2R",
    "진입 뒤 48시간이 지나면 종가 정리 · 수수료·미끄러짐 포함 · 20배(증거금 20%) 잔고 변화도 표시",
    "30개가 쌓이기 전에는 표본 부족. 30개부터: 방향 적중률이 동전(50%)보다 나은지, 따라 한 평균 R이 0보다 큰지",
]

COIN_ALIASES = {c[:-3]: c for c in G.COINS}
SIDE_WORDS = {"롱": 1, "long": 1, "매수": 1, "l": 1, "숏": -1, "short": -1, "매도": -1, "s": -1}


def ensure(conn) -> None:
    conn.executescript(SCHEMA)


# ------------------------------------------------------------------ parsing
def _num(tok: str) -> Optional[float]:
    t = tok.replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) and v > 0 else None


def _range(tok: str):
    t = tok.replace("~", "-").replace("–", "-")
    parts = [p for p in t.split("-") if p]
    vals = [_num(p) for p in parts]
    if not vals or any(v is None for v in vals) or len(vals) > 2:
        return None
    lo, hi = min(vals), max(vals)
    return [lo, hi]


def parse(text: str, now_ms: int, price_of=None):
    """('ok', view dict, notes) or ('err', message). price_of(coin) -> current price for a sanity check."""
    raw = text.strip()
    toks = raw.split()
    if not toks or toks[0] not in ("관점", "관점:"):
        return ("err", "첫 단어는 '관점'이어야 합니다")
    toks = toks[1:]
    notes = []
    t_ms = None
    # optional MM/DD and HH:MM (KST)
    if toks and re.fullmatch(r"\d{1,2}/\d{1,2}", toks[0]):
        md = toks.pop(0)
        hm = toks.pop(0) if toks and re.fullmatch(r"\d{1,2}:\d{2}", toks[0]) else "00:00"
        mo, dy = (int(x) for x in md.split("/"))
        hh, mi = (int(x) for x in hm.split(":"))
        now_k = time.gmtime((now_ms + KST) / 1000)
        year = now_k.tm_year
        try:
            import calendar
            t_ms = (calendar.timegm((year, mo, dy, hh, mi, 0)) * 1000) - KST
            if t_ms > now_ms + H_MS:            # a December view typed in January
                t_ms = (calendar.timegm((year - 1, mo, dy, hh, mi, 0)) * 1000) - KST
        except (ValueError, OverflowError):
            return ("err", f"날짜·시각을 읽지 못했습니다: {md} {hm}")
        if t_ms > now_ms + 5 * 60 * 1000:
            return ("err", "관점 시각이 지금보다 뒤입니다")
    elif toks and re.fullmatch(r"\d{1,2}:\d{2}", toks[0]):
        hh, mi = (int(x) for x in toks.pop(0).split(":"))
        day0 = ((now_ms + KST) // 86400000) * 86400000 - KST
        t_ms = day0 + (hh * 60 + mi) * 60000
        if t_ms > now_ms + 5 * 60 * 1000:
            t_ms -= 86400000
    if t_ms is None:
        t_ms = now_ms
        notes.append("시각 없음: 받은 시각 사용")
    if not toks:
        return ("err", "코인이 없습니다")
    c = toks.pop(0).upper().replace("/", "")
    for suf in ("USDT", "USD"):
        if c.endswith(suf) and len(c) > len(suf):
            c = c[:-len(suf)]
    coin = COIN_ALIASES.get(c)
    if coin is None:
        return ("err", f"코인을 모릅니다: {c} (BTC ETH SOL DOGE LTC BCH XRP)")
    if not toks or toks[0].lower() not in SIDE_WORDS:
        return ("err", "방향(롱/숏)이 없습니다")
    side = SIDE_WORDS[toks.pop(0).lower()]
    zones = {"A": None, "B": None, "C": None}
    stop = None
    targets = []
    memo = ""
    i = 0
    while i < len(toks):
        k = toks[i]
        ku = k.upper()
        if ku in ("A", "B", "C") and i + 1 < len(toks):
            r = _range(toks[i + 1])
            if r is None:
                return ("err", f"{ku} 구간 숫자를 읽지 못했습니다: {toks[i + 1]}")
            zones[ku] = r
            i += 2
        elif k in ("손절", "sl", "SL") and i + 1 < len(toks):
            stop = _num(toks[i + 1])
            if stop is None:
                return ("err", f"손절 숫자를 읽지 못했습니다: {toks[i + 1]}")
            i += 2
        elif k in ("목표", "익절", "tp", "TP") and i + 1 < len(toks):
            vals = []
            j = i + 1
            while j < len(toks) and len(vals) < 2:
                parts = toks[j].split("/")
                got = [_num(p) for p in parts if p]
                if not got or any(v is None for v in got):
                    break
                vals.extend(got)
                j += 1
            if not vals:
                return ("err", f"목표 숫자를 읽지 못했습니다: {toks[i + 1]}")
            targets = vals[:2]
            i = j
        elif k == "메모":
            memo = " ".join(toks[i + 1:])[:200]
            break
        else:
            return ("err", f"모르는 말: {k} (A/B/C 구간, 손절, 목표, 메모만 씁니다)")
    if not any(zones.values()):
        return ("err", "구간이 하나도 없습니다 (예: B 84750-84840)")
    if price_of is not None:
        p = price_of(coin)
        if p:
            vals = [v for z in zones.values() if z for v in z] + ([stop] if stop else []) + targets
            if any(abs(v / p - 1) > 0.3 for v in vals):
                return ("err", f"숫자가 지금 가격({p:,.6g})에서 30% 넘게 떨어져 있습니다. 숫자를 확인해 주세요")
    if stop is not None:
        far = _farthest(zones, side)
        if (side > 0 and stop >= far) or (side < 0 and stop <= far):
            notes.append("손절이 구간 안쪽: 그대로 사용")
    return ("ok", dict(t_ms=int(t_ms), coin=coin, side=side, zones=zones, stop=stop, targets=targets, memo=memo),
            notes)


def _farthest(zones, side):
    vals = [v for z in zones.values() if z for v in z]
    return min(vals) if side > 0 else max(vals)


def _nearest_edge(zones, side, ref):
    """The zone edge price closest to the reference price: where a limit order would wait."""
    best = None
    for z in zones.values():
        if not z:
            continue
        for v in z:
            if best is None or abs(v - ref) < abs(best - ref):
                best = v
    return best


# ------------------------------------------------------------------ storage
def add(conn, v: dict, text: str, from_name: str, now_ms: int) -> int:
    ensure(conn)
    cur = conn.execute("INSERT INTO views(t_ms, entered_ms, coin, side, zones, stop, targets, memo, status, text, "
                       "from_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (v["t_ms"], now_ms, v["coin"], v["side"], json.dumps(v["zones"]), v["stop"],
                        json.dumps(v["targets"]), v["memo"], "watching", text[:500], (from_name or "")[:40]))
    return int(cur.lastrowid)


def cancel(conn, vid: int) -> bool:
    ensure(conn)
    cur = conn.execute("UPDATE views SET status='cancelled' WHERE id=? AND status!='cancelled'", (vid,))
    return cur.rowcount > 0


def load_all(conn) -> list:
    ensure(conn)
    out = []
    for r in conn.execute("SELECT id, t_ms, entered_ms, coin, side, zones, stop, targets, memo, status, done_sent "
                          "FROM views ORDER BY id"):
        out.append(dict(id=r[0], t_ms=r[1], entered_ms=r[2], coin=r[3], side=r[4], zones=json.loads(r[5]),
                        stop=r[6], targets=json.loads(r[7] or "[]"), memo=r[8] or "", status=r[9],
                        done_sent=bool(r[10])))
    return out


# ------------------------------------------------------------------ scoring
def _reach(b, i, side, edge):
    """How bar i reaches the edge: 'open' (already through it at the open), 'touch' (trades through it), None."""
    if (side > 0 and b["o"][i] <= edge) or (side < 0 and b["o"][i] >= edge):
        return "open"
    if (side > 0 and b["l"][i] <= edge) or (side < 0 and b["h"][i] >= edge):
        return "touch"
    return None


def _follow(b, i0, i_end, side, zones, stop, targets, mode, ref):
    """One follow mode from 15m bar i0 (the reference bar) up to i_end (exclusive), CONTRACT 7.3.
    touch: limit at the nearest zone edge (maker; a bar opening through it fills at the open, taker); the stop
    counts in the entry bar, targets from the next bar. confirm: after the touch, the first 15m close back on the
    trade side of the edge (taker at that close); a stop touch before that close = missed; exits from the next bar."""
    out = dict(status="waiting", entry_ms=None, entry=None, stop=None, exit_ms=None, R=None, wallet20_pct=None,
               legs_ko="")
    edge = _nearest_edge(zones, side, ref)
    if edge is None:
        return out
    stp = stop if stop is not None else (_farthest(zones, side) * (1 - side * DEFAULT_STOP_PAD))
    n = len(b["ts"])
    last = min(i_end, n)
    f = fill = None
    maker = False
    touched = False
    for i in range(i0, last):
        how = _reach(b, i, side, edge)
        if mode == "touch":
            if how is not None:
                f = i
                fill, maker = (b["o"][i], False) if how == "open" else (edge, True)
                break
            continue
        touched = touched or how is not None
        if not touched:
            continue
        if (side > 0 and b["l"][i] <= stp) or (side < 0 and b["h"][i] >= stp):
            out["status"] = "missed"
            return out
        if (side > 0 and b["c"][i] > edge) or (side < 0 and b["c"][i] < edge):
            f, fill, maker = i, b["c"][i], False
            break
    if f is None:
        if i_end <= n:
            out["status"] = "missed"
        return out
    entry = float(fill) if maker else float(fill) * (1 + side * SLIP)
    if (side > 0 and stp >= entry) or (side < 0 and stp <= entry):
        out["status"] = "missed"           # already beyond the stop at the entry
        return out
    risk = abs(entry - stp)
    if len(targets) >= 2:
        t1, t2, half = targets[0], targets[1], True
    elif len(targets) == 1:
        t1, t2, half = targets[0], targets[0], False
    else:
        t1, t2, half = entry + side * risk, entry + side * 2 * risk, True
    legs = []
    cap = f + WATCH_H * 4
    stop_now = stp
    got1 = False
    j = f if mode == "touch" else f + 1
    while j < n and j <= cap:
        lo, hi, op = b["l"][j], b["h"][j], b["o"][j]
        if (side > 0 and lo <= stop_now) or (side < 0 and hi >= stop_now):
            gap = j > f and ((side > 0 and op <= stop_now) or (side < 0 and op >= stop_now))
            legs.append((1.0 - sum(x[0] for x in legs), j, op if gap else stop_now, "be" if got1 else "sl"))
            break
        if j > f:
            if not got1 and ((hi >= t1) if side > 0 else (lo <= t1)):
                if not half:
                    legs.append((1.0, j, t1, "tp"))
                    break
                legs.append((0.5, j, t1, "tp"))
                got1 = True
                stop_now = entry
                if (hi >= t2) if side > 0 else (lo <= t2):
                    legs.append((0.5, j, t2, "tp"))
                    break
            elif got1 and ((hi >= t2) if side > 0 else (lo <= t2)):
                legs.append((0.5, j, t2, "tp"))
                break
        j += 1
    out.update(entry_ms=int(b["ts"][f]), entry=float(entry), stop=float(stp))
    rem = 1.0 - sum(x[0] for x in legs)
    if rem > 1e-9:
        if cap < n:
            legs.append((rem, cap, b["c"][cap], "time"))
        else:
            px = b["c"][n - 1]
            pnl = rem * side * (px - entry) + sum(fr * side * (p - entry) for fr, _j, p, _k in legs)
            out.update(status="open", R=float(pnl / risk))
            return out
    pnl = 0.0
    fee = (MAKER if maker else TAKER) * entry
    for fr, _jj, p, kind in legs:
        px = p if kind == "tp" else p * (1 - side * SLIP)
        pnl += fr * side * (px - entry)
        fee += fr * (MAKER if kind == "tp" else TAKER) * px
    net = pnl - fee
    out.update(status="closed", exit_ms=int(b["ts"][legs[-1][1]]), R=float(net / risk),
               wallet20_pct=float(net / entry * (L20 * L20 / 100.0) * 100),
               legs_ko=" · ".join({"tp": "익절", "sl": "손절", "be": "본전", "time": "시간"}[k] for _f, _j, _p, k in legs))
    return out


def score(v: dict, b15: dict, now_ms: int) -> dict:
    """Scores of one view from the 15m bars of its coin."""
    ts = b15["ts"]
    out = dict(v)
    out.update(ref_price=None, dir={"4h": None, "24h": None, "48h": None}, reached=None, reached_ms=None,
               follow={"touch": None, "confirm": None})
    i0 = int(np.searchsorted(ts, v["t_ms"] + 1))     # first bar opening after the view time
    if i0 >= len(ts):
        return out
    ref = float(b15["o"][i0])
    out["ref_price"] = ref
    side = v["side"]
    for name, hrs in (("4h", 4), ("24h", 24), ("48h", 48)):
        k = i0 + hrs * 4 - 1
        if k < len(ts):
            out["dir"][name] = float(side * (b15["c"][k] / ref - 1) * 100)
    i_end = i0 + WATCH_H * 4
    edge = _nearest_edge(v["zones"], side, ref)
    for i in range(i0, min(i_end, len(ts))):
        if _reach(b15, i, side, edge) is not None:
            out["reached"] = True
            out["reached_ms"] = int(ts[i])
            break
    if out["reached"] is None and i_end <= len(ts):
        out["reached"] = False
    for mode in ("touch", "confirm"):
        out["follow"][mode] = _follow(b15, i0, i_end, side, v["zones"], v["stop"], v["targets"], mode, ref)
    finished = (i_end <= len(ts) and all(out["follow"][m]["status"] in ("closed", "missed")
                                         for m in ("touch", "confirm")))
    out["finished"] = bool(finished)
    return out


def _binom_p(k: int, n: int) -> Optional[float]:
    """One-sided P(X >= k) for X ~ Binomial(n, 0.5)."""
    if n <= 0:
        return None
    tot = 0.0
    for i in range(k, n + 1):
        tot += math.comb(n, i)
    return tot / 2 ** n


def summarize(scored: list) -> dict:
    live = [v for v in scored if v["status"] != "cancelled"]
    done = [v for v in live if v.get("finished")]
    summ = dict(n=len(live), n_done=len(done), need=NEED)
    d = {}
    for h in ("4h", "24h", "48h"):
        vals = [v["dir"][h] for v in live if v["dir"].get(h) is not None]
        hit = sum(1 for x in vals if x > 0)
        d[h] = dict(n=len(vals), hit=hit, rate=(hit / len(vals) if vals else None), p=_binom_p(hit, len(vals)))
    summ["dir"] = d
    rr = [v["reached"] for v in live if v["reached"] is not None]
    summ["reached_rate"] = (sum(rr) / len(rr)) if rr else None
    fol = {}
    for mode in ("touch", "confirm"):
        closed = [v["follow"][mode] for v in done if v["follow"][mode] and v["follow"][mode]["status"] == "closed"]
        Rs = [x["R"] for x in closed]
        wk_n, wk_s = A.week_blocks([dict(status="closed", exit_ms=x["exit_ms"], entry_ms=x["entry_ms"], R=x["R"])
                                    for x in closed])
        fol[mode] = dict(n=len(done), entered=len(closed), mean_R=(float(np.mean(Rs)) if Rs else None),
                         win_rate=(sum(1 for r in Rs if r > 0) / len(Rs) if Rs else None), sum_R=float(sum(Rs)),
                         ci_low=(A.boot_low(wk_n, wk_s) if len(Rs) >= 10 else None),
                         wallet20_pct=float(sum(x["wallet20_pct"] or 0 for x in closed)))
    summ["follow"] = fol
    if len(done) < NEED:
        summ["verdict_ko"] = f"표본 부족 ({len(done)}/{NEED})"
    else:
        p24 = d["24h"]["p"]
        good_dir = p24 is not None and p24 < 0.05
        good = [m for m in ("touch", "confirm") if fol[m]["mean_R"] is not None and fol[m]["mean_R"] > 0
                and fol[m]["ci_low"] is not None and fol[m]["ci_low"] > 0]
        parts = ["방향 적중이 동전보다 확실히 나음" if good_dir else "방향 적중이 동전과 구별 안 됨",
                 ("따라 하면 돈이 됨: " + ", ".join({"touch": "바로 진입", "confirm": "종가 확인"}[m] for m in good))
                 if good else "따라 해도 돈이 된다는 근거 없음"]
        summ["verdict_ko"] = " · ".join(parts)
    return summ


def snapshot(conn, b15_by_coin: dict, now_ms: int) -> tuple:
    """(views.json dict, newly finished views for Telegram)."""
    rows = load_all(conn)
    scored = []
    newly = []
    for v in rows:
        if v["status"] == "cancelled":
            s = dict(v, ref_price=None, dir={"4h": None, "24h": None, "48h": None}, reached=None, reached_ms=None,
                     follow={"touch": None, "confirm": None}, finished=False)
        else:
            b = b15_by_coin.get(v["coin"])
            s = score(v, b, now_ms) if b is not None and len(b["ts"]) else dict(v, ref_price=None, dir={},
                                                                                    reached=None, follow={})
            if s.get("finished"):
                s["status"] = "done"
                if not v["done_sent"]:
                    newly.append(s)
        scored.append(s)
    summ = summarize(scored)
    pub = []
    for s in sorted(scored, key=lambda x: -x["id"])[:300]:
        pub.append({k: s.get(k) for k in ("id", "t_ms", "entered_ms", "coin", "side", "zones", "stop", "targets",
                                          "memo", "status", "ref_price", "dir", "reached", "reached_ms", "follow")})
    return dict(generated_ms=now_ms, rules_ko=RULES_KO, summary=summ, views=pub), newly


def mark_done(conn, ids) -> None:
    conn.executemany("UPDATE views SET done_sent=1, status='done' WHERE id=?", [(int(i),) for i in ids])


# ------------------------------------------------------------------ commands
def handle(conn, item: dict, now_ms: int, price_of=None) -> list:
    """One Telegram message -> list of (kind, payload) to queue. Non-commands give []."""
    text = (item.get("text") or "").strip()
    if not text:
        return []
    first = text.split()[0]
    if first in ("관점도움", "/help"):
        return [("view_help", {})]
    if first == "관점목록":
        rows = load_all(conn)[-10:]
        return [("view_list", {"views": [dict(id=r["id"], t_ms=r["t_ms"], coin=r["coin"], side=r["side"],
                                               status=r["status"], dir24=None, touch_R=None) for r in rows[::-1]]})]
    if first == "취소":
        m = re.fullmatch(r"취소\s+#?(\d+)", text)
        if not m:
            return [("view_err", {"text_ko": "취소할 번호를 적어 주세요 (예: 취소 12)"})]
        vid = int(m.group(1))
        return [("view_cancel", {"id": vid, "ok": cancel(conn, vid)})]
    if first not in ("관점", "관점:"):
        return []
    res = parse(text, int(item.get("date_ms") or now_ms), price_of=price_of)
    if res[0] == "err":
        return [("view_err", {"text_ko": res[1]})]
    _ok, v, notes = res
    vid = add(conn, v, text, item.get("from_name", ""), now_ms)
    return [("view_ack", dict(id=vid, coin=v["coin"], side=v["side"], t_ms=v["t_ms"], zones=v["zones"], stop=v["stop"],
                              targets=v["targets"], memo=v["memo"], notes_ko=notes))]
