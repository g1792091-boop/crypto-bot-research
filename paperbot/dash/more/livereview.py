"""실거래 › 검토 (#/review, "2주 검토": the 추세판단 봇's review day; owners 10/21 "대시보드 화면들 더 멋있게 모든 필요한 화면
부분들 다 추가로 만들어줘"). The owners froze the trend bot's rules for two weeks from its start (docs/trend-bot-ko.md 5);
this is what they open on the review day: did the new rules work, and did each new rule help? Read-only, like every
실거래 tab: nothing here changes a rule (that is the owners' decision).

    GET /api/v4/livebots/trendreview   (5 s cache; the page asks every 60 s, every 15 s while virtual results are left)
        bot      the start (the bot's ``trend_since``), the 2-week freeze: day N of 14, the review date, days left
        record   the paper account COMBO@mix and its coin-flip twin COMBOFLIP@mix (the same entries at the same moments,
                 the side by a coin: the yardstick) since the start: trades, wins (= 첫 잠금까지 간 거래), net P&L, net
                 ROE sum; ``luck``: the gap of the two win rates against what luck leaves (``two_band``: 90 %, both
                 sides noisy), drawn as a band around the coin's rate; inside = the gap is within luck
        execs    both real executors' closed trades entered since the start (their own databases: n, wins, P&L, real
                 money only when the executor runs on mainnet), whether one holds a position now
        days     per KST day from the start: signals, passed the checks (waited for a pullback, or went in at once:
                 바로 진입, the owners' config since 10-22), pullback touched (a config that waits), entered, the paper's closed trades and P&L of the day (and the twin's); ``curve``: the cumulative P&L
                 and net ROE sum of both accounts, trade by trade
        funnel   the same funnel over the whole span and what stopped the rest (livetrend.BLOCK's categories)
        whatif   새 규칙이 도왔나? (가상, below)
        split    the paper record by role (livetrend.ROLE), member, coin, side, exit reason and entry timeframe

What-ifs (가상: arithmetic on the rule bot's 1m bars, never a trade; funding left out; as if the account were flat):
    trend   the signals the trend judge stopped (보류 · 반대 · 힘 약함 · 끝물; with 보류 허용, owners 10-22 trend.hold_entry,
            no 보류: ``rule_ko`` says so), entered at the signal's price
    spot    the signals the entry checks stopped (EMA20 · RSI · 돌파형 초입), entered at the signal's price
    nopull  the signals whose pullback never came, entered at the signal's price
    judge / time   the supervisor's exits (추세 뒤집힘 · 시간 정리), held instead
    pull    the pulled entries entered at the signal's price instead; and the entry price the pullback won (real numbers)
nopull and pull exist only while a config waits for its pullback (trend.pullback_wait): the owners' config enters at once
since 10-22, so their tiles say so (``off``, like time since 10-21 night) and judge only what came before.
The replay is the 규칙 점검 tab's (dash/more/liveinsight.py ``_hold``: dash/more/livetape.py ``rebuild`` with the engine's
own functions, the result booked by ``booked_roe``), here on 1m bars read once per coin per answer: the same net ROE stop
(``_virtual``'s rule: ladder.roe_price from the signal's price, the fill = that price with the slippage against) and the
same ladder; a held trade keeps its own entry, stop, liquidation price and size. Results: won (the first lock reached),
lost (the stop), open (neither yet), or why it could not be told. The yardstick of trend / spot / nopull is the bot's own
trades held the same way (the supervisor and the fast stop left out on both sides); judge / time / pull compare the
same trades. Verdicts never overclaim: under SMALL_N decided results 아직 판단 못 함; a gap luck can make is 운 범위 안
(a-c: the blocked side's virtual win rate against the bot's, ``two_band``; judge / time / pull: how often the rule's way
was better, a sign count inside the Binomial(n, 50 %) 5 %-95 % band). Work is bounded: a decided result is kept (the
bars before an exit do not change), an open one a minute; at most BUDGET_S seconds of replays per answer (the rest
``pending``, continued at the next ask), the newest GROUP_MAX signals of a what-if.

States (CONTRACT 1.6): no file / no table = missing; the running paper bot is not the trend bot (``combo_run`` without
``trend``) = off; no judgment yet = missing with the reason; unreadable = error. Never a zero for an unread value; a
what-if that cannot be worked out says why (못 함). Times are UTC ms, ratios are ratios (0.1 = 10 %), money is the
paper's USDT (the executors': their exchange's USDT).
"""
from __future__ import annotations

import bisect
import itertools
import json
import math
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Optional

from . import livebots as L
from . import livetrend as LT

ACCOUNT, FLIP = L.ACCOUNT, L.FLIP_ACCOUNT
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
FREEZE_DAYS = LT.FREEZE_DAYS
TF_MS = LT.TF_MS
SMALL_N = L.SMALL[0]                 # under 20 trades / decided results: 표본 적음 · 아직 판단 못 함
MORE_N = L.SMALL[1]                  # under 40: still says so
LUCK_QS = (0.05, 0.95)               # the band a coin leaves to luck (a sign count against 50 %)
Z90 = 1.6448536269514722             # two-sided 90 % (the gap of two win rates luck leaves: ``two_band``)
BUDGET_S = 4.0                       # seconds of replays per answer (the rest is worked on at the next ask)
GROUP_MAX = 1500                     # signals of one what-if replayed at most (the newest)
ROWS_KEEP = 12                       # rows of a what-if sent (the newest)
CURVE_MAX = 300
MEMO_MAX = 20_000
OPEN_TTL_S = 60.0                    # an undecided replay is worked out again after this (liveinsight HOLD_OPEN_TTL_S)
LOCKED_TTL_S = 300.0                 # one past its first lock, still running
NODATA_TTL_S = 600.0                 # no bar at its entry minute (bars can come late)
HOLD_MAX_MS = 14 * DAY               # liveinsight.HOLD_MAX_MS: a virtual trade is followed at most this long
ROLES = L.TREND_ROLES                # 눌림 · 자리 · 돌파 · 횡보 · 추세 (owners 10-22)
OTHER_ROLE = "그 밖"
FUNDING_KO = "펀딩비는 넣지 않았어요 (비율이 기록에 없어요)"
NOTE_KO = ("가상 = 규칙봇 1분봉으로 다시 계산한 결과예요(실제 체결 아님) · 같은 손절(순ROE −50%) · 같은 계단 익절 · "
           "계좌가 비어 있었다고 치고(한 번에 하나 규칙은 빼고) · " + FUNDING_KO)
# the what-ifs in the order the page shows them: (id, title, the rule in words, how the virtual result is made)
WHATIF = (
    ("trend", "추세 판단", "상위 봉(30분 진입은 1시간, 1시간 진입은 4시간, 4시간 진입은 일봉) 판단이 보류·반대·힘 약함·끝물이면 진입 안 함",
     "추세 판단에 걸린 신호를 신호 가격에 들어갔다면 (가상)"),
    ("spot", "진입 자리 검사", "상위 EMA20에서 너무 뻗음 · 진입 봉 EMA20에서 멂 · RSI 과열/침체 · 돌파형은 추세 초입만",
     "진입 자리 검사에 걸린 신호를 신호 가격에 들어갔다면 (가상)"),
    ("nopull", "되돌림 기다림 (버린 신호)", "진입 봉 하나 동안 0.25 ATR(장대봉 0.5 ATR) 되돌림을 기다리고, 안 오면 버림",
     "되돌림이 안 와서 버린 신호를 신호 가격에 들어갔다면 (가상)"),
    ("judge", "감독: 추세 뒤집힘 청산", "첫 잠금 전에 상위 봉 판단이 반대(3/4)로 바뀌면 청산",
     "추세 뒤집힘으로 닫은 거래를 손절·계단 익절대로 붙잡았다면 (가상)"),
    ("time", "감독: 시간 정리", "진입 봉 4개 안에 첫 잠금(+10%)을 못 가면 청산 · 10/21 밤에 뺌 (그 전에 닫힌 거래만)",
     "시간 정리로 닫은 거래를 손절·계단 익절대로 붙잡았다면 (가상)"),
    ("pull", "되돌림 진입가", "신호 가격이 아니라 되돌림 가격에 들어감",
     "되돌림으로 들어간 거래를 신호 가격에 바로 들어갔다면 (가상) · 진입가 차이는 실제 숫자"),
)
BLOCKED = {"trend": ("trend",), "spot": ("spot",), "nopull": ("nopull",)}
# the owners took the 시간 정리 exit out on 10/21 night (trend.time_bars null): its tile says so, and judges only the trades
# it closed before that
TIME_OFF_RULE_KO = "10/21 밤 뺀 규칙 · 그 전엔 진입 봉 4개 안에 첫 잠금(+10%)을 못 가면 청산했어요"
TIME_OFF_KO = "지금 봇에는 없는 규칙이라 새로 판정할 거래가 없어요"
# owners 10-22: 보류 허용 (trend.hold_entry: a 보류 no longer stops a signal) and 바로 진입 (trend.pullback_wait false: no
# pullback wait; the shadow trend-wait still waits): the tiles say what the running config does
TREND_HOLD_RULE_KO = ("상위 봉(30분 진입은 1시간, 1시간 진입은 4시간, 4시간 진입은 일봉) 판단이 반대·힘 약함·끝물이면 진입 안 함 "
                      "(보류는 받음: 10/22 보류 허용)")
PULL_OFF_RULE_KO = {"nopull": "10/22부터 바로 진입이라 되돌림을 기다리지 않아요 · 그 전엔 진입 봉 하나 동안 0.25 ATR 되돌림을 기다리고, 안 오면 버렸어요",
                    "pull": "10/22부터 바로 진입이라 되돌림 가격에 들어가지 않아요 · 그 전엔 신호 가격이 아니라 되돌림 가격에 들어갔어요"}
PULL_OFF_KO = "지금 봇은 바로 진입이라 새로 판정할 신호가 없어요 (되돌림 기다림은 그림자 trend-wait에서 비교해요)"

_lock = threading.Lock()
_memo: "OrderedDict[str, tuple]" = OrderedDict()


# ================================================================ small helpers
def _json(x) -> dict:
    return L._j(x)


def _f(x) -> Optional[float]:
    return L._f(x)


def kst_day0(ms: int) -> int:
    return int(ms) - (int(ms) + KST_MS) % DAY


def _trades(conn, account: str, since: int) -> list:
    """The account's closed trades entered since ``since``, oldest exit first (TradeRecord fields + ``_id``)."""
    rows = conn.execute("SELECT id, data FROM trades WHERE account_id = ? AND entry_time >= ? ORDER BY exit_time, id",
                        (account, int(since))).fetchall()
    out = []
    for tid, data in rows:
        t = _json(data)
        if t and _f(t.get("pnl")) is not None:
            out.append({**t, "_id": int(tid)})
    return out


def rec_of(trades: list) -> dict:
    """n, wins (net P&L > 0: the executors' rule), losses, win rate, net P&L, net ROE sum and mean, best / worst."""
    n = len(trades)
    wins = sum(1 for t in trades if float(t.get("pnl") or 0) > 0)
    roes = [r for r in (_f(t.get("roe")) for t in trades) if r is not None]
    return {"n": n, "wins": wins, "losses": n - wins, "win_rate": wins / n if n else None,
            "pnl": sum(float(t.get("pnl") or 0) for t in trades), "roe_sum": sum(roes), "roe_mean": sum(roes) / len(roes) if roes else None,
            "best": max(roes) if roes else None, "worst": min(roes) if roes else None, "small": n < SMALL_N}


def band(n: int, p: Optional[float]) -> Optional[list]:
    """[low, high] wins of n tries a coin with win rate p gives 90 % of the time (Binomial 5 %-95 %)."""
    if not n or p is None:
        return None
    if p <= 0:
        return [0, 0]
    if p >= 1:
        return [n, n]
    lo, hi = L.binom_quantiles(int(n), float(p), LUCK_QS)
    return [int(lo), int(hi)]


def where_in(k: int, b: Optional[list]) -> Optional[str]:
    if b is None:
        return None
    return "above" if k > b[1] else "below" if k < b[0] else "inside"


def two_band(w1: int, n1: int, w2: int, n2: int) -> Optional[dict]:
    """Two win rates (both noisy: neither side is taken as exact): the gap luck leaves, 90 % two-sided, both sides from
    one pooled rate (the normal form of two binomials). -> {"half": the gap luck leaves, "band": side 2's rate +- half
    (clipped to 0..1), "where": side 1 above / below / inside it}; None without trades on a side."""
    if not n1 or not n2:
        return None
    p = (w1 + w2) / (n1 + n2)
    half = Z90 * math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    r1, r2 = w1 / n1, w2 / n2
    gap = r1 - r2
    where = "above" if gap > half + 1e-12 else "below" if gap < -half - 1e-12 else "inside"
    return {"half": half, "band": [max(0.0, r2 - half), min(1.0, r2 + half)], "where": where, "gap": gap}


# ================================================================ the record and the coin-flip twin
def luck_of(real: dict, flip: dict) -> dict:
    """진짜 방향 vs 동전 방향: is the gap of the win rates more than luck leaves (``two_band``)? Under SMALL_N trades it
    never says more than 표본 적음."""
    if not real["n"] or not flip["n"]:
        return {"state": "none", "ko": "둘 중 하나가 아직 닫힌 거래가 없어서 견줄 수 없어요", "band_rate": None, "where": None}
    tb = two_band(real["wins"], real["n"], flip["wins"], flip["n"])
    where = tb["where"]
    small = real["n"] < SMALL_N
    if small:
        ko = f"표본 적음: 대부분 운이에요 (거래 {real['n']}번)" + (" · 지금 차이도 운 범위 안이에요" if where == "inside"
                                                             else " · 차이가 보여도 아직 믿기 어려워요")
    elif where == "inside":
        ko = "동전과의 차이는 운으로도 생기는 크기예요"
    else:
        ko = f"진짜 방향이 동전보다 운 범위를 넘게 {'앞서요' if where == 'above' else '뒤져요'}"
        if real["n"] < MORE_N:
            ko += f" (거래 {real['n']}번: {MORE_N}번까지는 더 봐야 해요)"
    return {"state": "ok", "ko": ko, "band_rate": tb["band"], "half": tb["half"], "where": where, "small": small,
            "gap": tb["gap"], "roe_gap": real["roe_sum"] - flip["roe_sum"], "n": real["n"]}


def exec_since(p: dict, since: int, now: int) -> list:
    """Both executors' closed trades entered since the start while they followed the trend bot (their own records and start
    records: livepapers segments; owners 10-23, an executor moved to the 'VWAP 개선판' counts here only its trend-bot
    trades, ``other`` says which bot it follows now, since when and how many of its trades are that bot's), their names
    from their configs."""
    from ... import livepapers as LP
    configs = {ex: L.read_config(p[ck]) for ex, _ko, _dk, ck in L.EXECS}
    out = []
    for ex, ko, dk, ck in L.slots(configs):
        r = L.read_exec(p[dk], now)
        if r.get("state") != "ok":
            out.append({"id": ex, "name_ko": ko, "state": r.get("state"), "reason_ko": r.get("reason_ko"), "reason": r.get("reason")})
            continue
        main = p.get("paper")
        segs = LP.segments(r.get("starts") or [], main) if main else [[None, None]]
        mine = (lambda t: LP.followed_at(segs, main, t.get("entry_ts"))) if main else (lambda t: True)      # noqa: E731
        xs = [t for t in r.get("trades") or [] if (t.get("entry_ts") or 0) >= since and t.get("pnl") is not None and mine(t)]
        here = LP.same(LP.current(segs), main) if main else True
        row = {"id": ex, "name_ko": ko, "state": "ok", "mode": r.get("mode"), "real": r.get("mode") == "mainnet",
               "n": len(xs), "wins": sum(1 for t in xs if t["pnl"] > 0), "pnl": sum(t["pnl"] for t in xs),
               # its open position is the trend bot's only while it follows the trend bot
               "open": r.get("position") is not None and here, "stale": r.get("stale"), "halted": bool(r.get("halted")),
               "balance": r.get("last_equity"), "estimated": sum(1 for t in xs if t.get("est"))}
        if main and len(segs) > 1:
            rest = [t for t in r.get("trades") or [] if (t.get("entry_ts") or 0) >= since and t.get("pnl") is not None and not mine(t)]
            ref = LP.current(segs) if not here else next((sp for _f, sp in reversed(segs) if not LP.same(sp, main)), None)
            row["other"] = {"bot_ko": _bot_name(ref), "now": not here, "since": segs[-1][0] if not here else None, "n": len(rest)}
        out.append(row)
    return out


def _bot_name(path: Optional[str]) -> str:
    """A paper bot's short name from its start record (livecheck.paper_name: "VWAP 개선판"), else "다른 페이퍼 봇"."""
    if not path:
        return "다른 페이퍼 봇"
    try:
        conn = L.open_ro(path)
    except (OSError, sqlite3.Error):
        return "다른 페이퍼 봇"
    try:
        _ts, run = LT._state(conn, "combo_run")
    finally:
        conn.close()
    cfg = (run or {}).get("config") if isinstance(run, dict) else None
    from ... import livepapers as LP
    return LP.bot_short((cfg or {}).get("name"), (cfg or {}).get("stop")) if isinstance(cfg, dict) else "다른 페이퍼 봇"


# ================================================================ signals: the days and the funnel
def _sig(row: tuple) -> dict:
    bc, tf, member, sym, side, atr, ref, status, data = row
    d = _json(data)
    why = d.get("why")
    if status == "SUBMITTED":
        cat = "entered" if why == "되돌림 확인" else "submitted"
    else:
        cat = L.why_cat(status, why)[0]
    tr = d.get("trend") if isinstance(d.get("trend"), dict) else {}
    return {"t": int(bc), "tf": tf, "member": member, "strategy": d.get("strategy") or str(member).split("@")[0], "symbol": sym,
            "side": int(side), "atr": _f(atr), "ref": _f(ref), "price": _f(tr.get("price")), "status": status, "cat": cat, "why": why}


def _counts(sigs: list) -> dict:
    """signals (the pulled entry's own row left out: counted at its signal), passed, touched, and what stopped the rest."""
    n = passed = touched = 0
    block: dict = {}
    for s in sigs:
        if s["cat"] == "entered":
            continue
        n += 1
        if (s["status"] in ("WAITING", "BROKE") or s["cat"] == "nopull"
                or (s["status"] == "SUBMITTED" and str(s["why"] or "").startswith(LT.PASSED_NOW))):     # 바로 진입 (10-22)
            passed += 1
        if s["status"] == "BROKE":
            touched += 1
        if s["status"] == "FILTERED":
            g = LT.BLOCK_OF.get(s["cat"], "other")
            block[g] = block.get(g, 0) + 1
    return {"signals": n, "passed": passed, "touched": touched, "block": block}


def days_of(sigs: list, entered: list, skipped: list, real: list, flip: list, since: int, now: int) -> list:
    out = []
    d0 = kst_day0(since)
    while d0 <= now:
        d1 = d0 + DAY
        c = _counts([s for s in sigs if d0 <= s["t"] < d1])
        rd = [t for t in real if d0 <= int(t["exit_time"]) < d1]
        fd = [t for t in flip if d0 <= int(t["exit_time"]) < d1]
        out.append({"d0": d0, "today": d0 <= now < d1, "signals": c["signals"], "passed": c["passed"], "touched": c["touched"],
                    "entered": sum(1 for e in entered if d0 <= e["t"] < d1), "held": sum(1 for x in skipped if d0 <= x < d1),
                    "n": len(rd), "wins": sum(1 for t in rd if float(t["pnl"]) > 0), "pnl": sum(float(t["pnl"]) for t in rd),
                    "roe": sum(float(t.get("roe") or 0) for t in rd), "flip_n": len(fd), "flip_pnl": sum(float(t["pnl"]) for t in fd),
                    "flip_roe": sum(float(t.get("roe") or 0) for t in fd)})
        d0 = d1
    return out


def curve_of(trades: list, since: int) -> list:
    """[[ms, cumulative net P&L, cumulative net ROE sum]] from the start, trade by trade (closing order)."""
    pts, pnl, roe = [[int(since), 0.0, 0.0]], 0.0, 0.0
    for t in trades:
        pnl += float(t["pnl"])
        roe += float(t.get("roe") or 0)
        pts.append([int(t["exit_time"]), pnl, roe])
    return L.thin(pts, CURVE_MAX)


def funnel_of(sigs: list, entered: list, skipped: list) -> dict:
    c = _counts(sigs)
    block = dict(c["block"])
    if skipped:
        block["one"] = block.get("one", 0) + len(skipped)
    return {"signals": c["signals"], "passed": c["passed"], "touched": c["touched"], "entered": len(entered),
            "blocked": [{"id": k, "ko": ko, "n": block[k]} for k, ko in LT.BLOCK if block.get(k)]}


# ================================================================ 나눠 보기
def _exit_group(t: dict) -> str:
    r = t.get("exit_reason")
    return r if r in dict(LT.EXIT_GROUP) else "OTHER"


def split_of(trades: list, cfg: dict) -> dict:
    def rows(key, order=None, extra=None):
        by: dict = {}
        for t in trades:
            by.setdefault(key(t), []).append(t)
        keys = [k for k in (order or []) if k in by] + sorted((k for k in by if k not in (order or [])), key=lambda k: (-len(by[k]), str(k)))
        out = []
        for k in keys:
            r = rec_of(by[k])
            out.append({"id": k, **{x: r[x] for x in ("n", "wins", "losses", "win_rate", "pnl", "roe_sum", "roe_mean", "small")},
                        **((extra or {}).get(k) or {})})
        return out
    labels = [f"{m.get('strategy')}@{m.get('tf')}" for m in cfg.get("members") or [] if isinstance(m, dict)]
    mem_extra = {f"{s}@{tf}": {"strategy": s, "tf": tf, "role": LT.ROLE.get(s)}
                 for s, tf in ((str(lab).split("@")[0], str(lab).split("@")[1]) for lab in labels)}
    for t in trades:
        lab = f"{t.get('strategy_id')}@{t.get('timeframe')}"
        mem_extra.setdefault(lab, {"strategy": t.get("strategy_id"), "tf": t.get("timeframe"), "role": LT.ROLE.get(t.get("strategy_id"))})
    members = rows(lambda t: f"{t.get('strategy_id')}@{t.get('timeframe')}", labels, mem_extra)
    have = {m["id"] for m in members}
    for lab in labels:                                   # a member without a trade yet: shown, never a zero record
        if lab not in have:
            members.append({"id": lab, "n": 0, "wins": 0, "losses": 0, "win_rate": None, "pnl": None, "roe_sum": None,
                            "roe_mean": None, "small": True, **mem_extra[lab]})
    members.sort(key=lambda m: labels.index(m["id"]) if m["id"] in labels else len(labels))     # the config's order
    return {"role": rows(lambda t: LT.ROLE.get(t.get("strategy_id")) or OTHER_ROLE, list(ROLES) + [OTHER_ROLE]),
            "member": members,
            "coin": rows(lambda t: t.get("symbol"), list(L.COINS)),
            "side": rows(lambda t: int(t.get("side") or 0), [1, -1]),
            "exit": rows(_exit_group, [k for k, _ko in LT.EXIT_GROUP], {k: {"ko": ko} for k, ko in LT.EXIT_GROUP}),
            "tf": rows(lambda t: t.get("timeframe"), ["30m", "1h", "4h"])}


# ================================================================ the replays (가상)
def _memo_get(key: str) -> Optional[dict]:
    with _lock:
        hit = _memo.get(key)
        if hit is None or (hit[0] is not None and time.time() >= hit[0]):
            return None
        _memo.move_to_end(key)
        return hit[1]


def _memo_put(key: str, out: dict) -> None:
    st = out.get("state")
    if out.get("exit"):
        ttl = None
    elif st == "won":
        ttl = LOCKED_TTL_S
    elif st == "open":
        ttl = OPEN_TTL_S
    elif st == "no_data":
        ttl = NODATA_TTL_S
    else:
        return                                           # a file that could not be read: tried again next time
    with _lock:
        _memo[key] = (None if ttl is None else time.time() + ttl, out)
        _memo.move_to_end(key)
        while len(_memo) > MEMO_MAX:
            _memo.popitem(last=False)


class Bars:
    """The rule bot's 1m bars (livetape.read_bars), read once per coin per answer from the earliest minute needed."""

    def __init__(self, path: str, now: int):
        self.path, self.now, self.lo, self.got = path, int(now), {}, {}

    def want(self, symbol: str, t: int) -> None:
        e0 = int(t) - int(t) % MIN
        self.lo[symbol] = min(self.lo.get(symbol, e0), e0)

    def of(self, symbol: str) -> dict:
        if symbol not in self.got:
            from . import livetape as T
            lo = self.lo.get(symbol, self.now)
            src = T.read_bars(self.path, symbol, lo, self.now - self.now % MIN + MIN)
            self.got[symbol] = {"src": src, "ts": [r["ts"] for r in src.get("rows") or []]}
        return self.got[symbol]


def held(t: dict, rules: dict, ref_fill: bool, bars: dict, now: int, LI) -> dict:
    """liveinsight._hold on bars already read: the trade ``t`` held from its own entry under its stop and the ladder until
    the stop, the lock or the bars' end (livetape.rebuild; no supervisor, no reverse-signal exit). -> {state: won | lost |
    open | no_data | missing | error, roe (booked at the exit; won but still running: the lock, a floor), lock, exit,
    why_ko}."""
    from . import livetape as T
    from ...ladder import net_roe
    src = bars["src"]
    if src.get("state") != "ok":
        return {"state": src.get("state") or "error", "why_ko": src.get("reason_ko"), "reason": src.get("reason")}
    e0 = int(t["entry_time"]) - int(t["entry_time"]) % MIN
    end = min(int(now) - int(now) % MIN, e0 + HOLD_MAX_MS)
    rows = src.get("rows") or []
    i = bisect.bisect_left(bars["ts"], e0)
    if i >= len(rows) or rows[i]["ts"] != e0:
        return {"state": "no_data", "why_ko": "진입한 분의 1분봉이 규칙봇 기록에 없어요"}
    tt = {**t, "exit_reason": "HOLD", "exit_time": end}
    rb = T.rebuild(tt, itertools.islice(rows, i, None), rules, ref_fill, [], until=end)
    x, lock = rb.get("exit"), rb.get("lock")
    out = {"lock": lock, "exit": None, "why_ko": None}
    if x:
        out.update(state="won" if rb.get("locks") else "lost", roe=LI.booked_roe(t, x["price"], x["reason"], rules["taker_fee"]),
                   exit={"t": x["t"], "price": x["price"], "reason": x["reason"], "reason_ko": L.EXIT_KO.get(x["reason"], x["reason"])})
    elif lock is not None:
        out.update(state="won", roe=lock, floor=True)
    else:
        last = rb["minutes"][-1] if rb.get("minutes") else None
        out.update(state="open", roe=last[6] if last else net_roe(int(t["side"]), float(t["entry_price"]), float(t["entry_price"]),
                                                                float(t["leverage"]), rules["round_trip"]))
        if e0 + HOLD_MAX_MS <= end:
            out["why_ko"] = "14일이 지나도 손절에도 첫 잠금에도 닿지 않았어요"
    return out


def _key(rule_db: str, t: dict, rules: dict, ref_fill: bool) -> str:
    return json.dumps([rule_db, t.get("symbol"), t.get("side"), t.get("entry_time"), t.get("entry_price"), t.get("stop_initial"),
                       t.get("liq_price"), t.get("leverage"), t.get("qty"), t.get("margin"), t.get("fees"), t.get("exit_price"),
                       bool(ref_fill), rules.get("taker_fee"), rules.get("round_trip")], default=str)


def virtual_t(price: Optional[float], side: int, symbol: str, t0: int, cfg: dict, rules: dict, LI, lev: Optional[int] = None) -> tuple:
    """(trade dict, None) of a signal entered at its price (liveinsight._virtual's rule: the config's net ROE stop through
    ladder.roe_price from that price, the fill with the slippage against), or (None, why in Korean)."""
    from ...ladder import roe_price
    sr, lev = LI.stop_roe(cfg), lev or LI.lev_of(cfg, symbol)
    if price is None or not side:
        return None, "신호 기록에 참고 가격이 없어 다시 만들지 못했어요"
    if sr is None or not lev:
        return None, "이 설정의 손절(ATR)은 신호 기록만으로 다시 만들지 않아요"
    if rules.get("spec") is None:
        return None, "봇 설정에 계단 익절 숫자가 없어 다시 계산하지 못해요"
    net = (cfg.get("stop") or {}).get("net") is True
    stop = roe_price(int(side), float(price), int(lev), -sr, rules["round_trip"] if net else 0.0)
    return {"side": int(side), "entry_price": float(price) * (1 + int(side) * rules["slippage"]), "entry_time": int(t0),
            "leverage": int(lev), "stop_initial": stop, "liq_price": None, "qty": None, "margin": None, "symbol": symbol,
            "fees": None, "exit_price": None}, None


class Replays:
    """The jobs of one answer: memo first, then the bars read once per coin, then the replays under the time budget."""

    def __init__(self, rule_db: str, now: int, LI, budget_s: float = BUDGET_S):
        self.rule_db, self.now, self.LI, self.budget = rule_db, int(now), LI, budget_s
        self.jobs: list = []
        self.bars = Bars(rule_db, now)
        self.done = self.pending = self.memo = 0

    def add(self, t: dict, rules: dict, ref_fill: bool) -> dict:
        """A result slot filled by run(): {"state": ...} at once when the memo has it."""
        k = _key(self.rule_db, t, rules, ref_fill)
        hit = _memo_get(k)
        if hit is not None:
            self.memo += 1
            return dict(hit)
        slot = {"state": "pending"}
        self.jobs.append((k, t, rules, ref_fill, slot))
        self.bars.want(t["symbol"], t["entry_time"])
        return slot

    def run(self) -> None:
        t0 = time.monotonic()
        for k, t, rules, ref_fill, slot in self.jobs:
            if time.monotonic() - t0 >= self.budget:
                self.pending += 1
                continue
            out = held(t, rules, ref_fill, self.bars.of(t["symbol"]), self.now, self.LI)
            _memo_put(k, out)
            slot.clear()
            slot.update(out)
            self.done += 1


def _cf_out(cf: dict) -> dict:
    return {k: cf.get(k) for k in ("state", "roe", "floor", "why_ko") if cf.get(k) is not None or k == "state"} | \
        ({"exit": {"t": cf["exit"]["t"], "reason": cf["exit"]["reason"]}} if cf.get("exit") else {})


def _dec(cf: dict) -> bool:
    return cf.get("state") in ("won", "lost") and _f(cf.get("roe")) is not None


def _tally(cfs: list) -> dict:
    dec = [c for c in cfs if _dec(c)]
    won = sum(1 for c in dec if c["state"] == "won")
    roes = [float(c["roe"]) for c in dec]
    return {"n": len(cfs), "decided": len(dec), "won": won, "lost": len(dec) - won,
            "open": sum(1 for c in cfs if c.get("state") == "open"), "pending": sum(1 for c in cfs if c.get("state") == "pending"),
            "unknown": sum(1 for c in cfs if c.get("state") not in ("won", "lost", "open", "pending")),
            "win_rate": won / len(dec) if dec else None, "roe_sum": sum(roes), "roe_mean": sum(roes) / len(roes) if roes else None}


def verdict_blocked(v: dict, base: dict) -> dict:
    """Signals a rule stopped (their virtual results) against the bot's own trades held the same way."""
    if not v["n"]:
        return {"kind": "none", "ko": "이 규칙에 걸린 신호가 아직 없어요"}
    if v["decided"] < SMALL_N:
        return {"kind": "small", "ko": f"아직 판단 못 함 · 결정 난 가상 결과 {v['decided']}개 ({SMALL_N}개 미만이면 대부분 운)"}
    if base["decided"] < SMALL_N:
        return {"kind": "small", "ko": f"아직 판단 못 함 · 비교할 봇 거래가 {base['decided']}번 ({SMALL_N}번 미만)"}
    tb = two_band(v["won"], v["decided"], base["won"], base["decided"])
    w, half = tb["where"], tb["half"]
    if w == "inside":
        return {"kind": "luck", "ko": "걸린 신호와 탄 거래의 차이가 운 범위 안이에요 (도왔다고도 손해라고도 못 해요)", "half": half}
    if w == "below":
        return {"kind": "helped", "ko": "걸린 신호는 들어갔어도 탄 거래보다 덜 이겼을 거예요 (가상) · 이 규칙이 도운 쪽", "half": half}
    return {"kind": "hurt", "ko": "걸린 신호가 들어갔다면 탄 거래보다 더 이겼을 거예요 (가상) · 이 규칙이 손해 본 쪽", "half": half}


def verdict_paired(better: int, worse: int, decided: int, delta: float, n: int) -> dict:
    """The same trades two ways: how often the rule's way was better, against a coin (50 %); ``delta`` the net ROE sum gap;
    ``n`` the trades of the rule (decided or not)."""
    if not n:
        return {"kind": "none", "ko": "이 규칙으로 닫히거나 들어간 거래가 아직 없어요"}
    if not decided:
        return {"kind": "small", "ko": f"아직 판단 못 함 · {n}번 중 결정 난 비교가 아직 없어요"}
    if decided < SMALL_N:
        return {"kind": "small", "ko": f"아직 판단 못 함 · 결정 난 비교 {decided}번 ({SMALL_N}번 미만이면 대부분 운)"}
    m = better + worse
    b = band(m, 0.5) if m else None
    w = where_in(better, b) if b else "inside"
    pp = f"{delta * 100:+.1f}%p".replace("-", "−")
    if w == "inside":
        return {"kind": "luck", "ko": f"나았던 거래 {better}번 · 못했던 거래 {worse}번: 차이가 운 범위 안이에요 (순ROE 합 {pp})", "band": b}
    if w == "above":
        return {"kind": "helped", "ko": f"이 규칙이 도운 쪽이에요 · 나았던 거래 {better}번 · 못했던 거래 {worse}번 (순ROE 합 {pp})", "band": b}
    return {"kind": "hurt", "ko": f"이 규칙이 손해 본 쪽이에요 · 나았던 거래 {better}번 · 못했던 거래 {worse}번 (순ROE 합 {pp})", "band": b}


def _head(wid: str) -> dict:
    w = next(x for x in WHATIF if x[0] == wid)
    return {"id": wid, "ko": w[1], "rule_ko": w[2], "how_ko": w[3]}


def _na(wid: str, state: str, why: str, reason: Optional[str] = None) -> dict:
    return {**_head(wid), "state": state, "reason_ko": why, "reason": reason, "verdict": {"kind": "na", "ko": f"못 함 · {why}"}, "rows": []}


def whatifs(sigs: list, trades: list, meta: dict, run: dict, cfg: dict, rule_db: str, now: int, budget_s: float = BUDGET_S) -> dict:
    """새 규칙이 도왔나? (module docstring): {"items": [...], "work": {done, pending, memo, budget_s}, "note_ko", "base"}."""
    try:
        from . import liveinsight as LI
        from . import livetape as T
    except ImportError as exc:                           # the replay modules are not there: said, never a zero
        why = "다시 계산하는 모듈이 없어요"
        return {"items": [_na(w[0], "error", why, f"{type(exc).__name__}: {exc}"[:200]) for w in WHATIF], "work": None,
                "note_ko": NOTE_KO, "base": None}
    if not isinstance(cfg.get("ladder"), dict):
        why = "봇 설정에 계단 익절 숫자가 없어 다시 계산하지 못해요"
        return {"items": [_na(w[0], "missing", why) for w in WHATIF], "work": None, "note_ko": NOTE_KO, "base": None}
    rp = Replays(rule_db, now, LI, budget_s)
    vrules = T.rules_of({"fees": None}, run)
    # the bot's own trades held (the yardstick of a-c; judge / time are some of them)
    base_cf = []
    for t in trades:
        rules = T.rules_of(t, run)
        m = meta.get((t.get("symbol"), int(t.get("entry_time") or 0)))
        ref = True if m is None else m
        if None in (t.get("entry_price"), t.get("leverage"), t.get("stop_initial"), t.get("side")) or rules["spec"] is None:
            base_cf.append({"state": "unknown", "why_ko": "거래 기록에 진입가·손절선이 없어 다시 계산하지 못했어요"})
        else:
            base_cf.append(rp.add(t, rules, ref))
    # (e) the pulled entries at the signal's price: each trade's BROKE row (same member, coin and side, its bar before
    # the entry and within one entry bar of it)
    broke = [s for s in sigs if s["status"] == "BROKE"]
    pulls = []
    for t, cf in zip(trades, base_cf):
        lab, tf, e = f"{t.get('strategy_id')}@{t.get('timeframe')}", t.get("timeframe"), int(t.get("entry_time") or 0)
        span = TF_MS.get(tf, HOUR)
        cand = [s for s in broke if s["member"] == lab and s["symbol"] == t.get("symbol") and s["side"] == int(t.get("side") or 0)
                and s["t"] < e <= s["t"] + span]
        if not cand:
            continue
        s = cand[-1]
        price = s["ref"] if s["ref"] is not None else s["price"]
        vt, why = virtual_t(price, s["side"], s["symbol"], s["t"], cfg, vrules, LI, t.get("leverage"))
        at = rp.add(vt, vrules, True) if vt else {"state": "unknown", "why_ko": why}
        gain = None
        if vt and _f(t.get("entry_price")) and t.get("leverage"):
            gain = s["side"] * (vt["entry_price"] - float(t["entry_price"])) / float(t["entry_price"]) * float(t["leverage"])
        pulls.append({"t": t, "sig": s, "held": cf, "at": at, "gain": gain, "price": price})
    # (a)-(c) the stopped signals at their price, newest first, at most GROUP_MAX each
    groups = {}
    for wid, cats in BLOCKED.items():
        rows = [s for s in sigs if s["status"] == "FILTERED" and s["cat"] in cats]
        rows.reverse()
        capped = len(rows) > GROUP_MAX
        out = []
        for s in rows[:GROUP_MAX]:
            price = s["ref"] if s["ref"] is not None else s["price"]
            vt, why = virtual_t(price, s["side"], s["symbol"], s["t"], cfg, vrules, LI)
            out.append((s, rp.add(vt, vrules, True) if vt else {"state": "unknown", "why_ko": why}))
        groups[wid] = (out, capped, len(rows))
    rp.run()

    base = _tally(base_cf)
    actual = rec_of(trades)
    t_cfg = cfg.get("trend") if isinstance(cfg.get("trend"), dict) else {}
    no_pull = t_cfg.get("pullback_wait", True) is False           # 바로 진입 (owners 10-22): the pullback tiles say so
    items = []
    for wid, _ko, _rule, _how in WHATIF:
        if wid in BLOCKED:
            out, capped, n_all = groups[wid]
            v = _tally([cf for _s, cf in out])
            off = no_pull and wid == "nopull"
            head = {**_head(wid), **({"rule_ko": TREND_HOLD_RULE_KO} if wid == "trend" and t_cfg.get("hold_entry") else {}),
                    **({"rule_ko": PULL_OFF_RULE_KO[wid], "off": True} if off else {})}
            items.append({**head, "state": "ok", "n": n_all, "capped": capped, "virt": v,
                          "base": {k: base[k] for k in ("n", "decided", "won", "win_rate", "roe_sum", "roe_mean")},
                          "actual": {k: actual[k] for k in ("n", "wins", "win_rate", "roe_sum", "roe_mean")},
                          "verdict": {"kind": "off", "ko": PULL_OFF_KO} if off and not n_all else verdict_blocked(v, base),
                          "rows": [{"t": s["t"], "symbol": s["symbol"], "side": s["side"], "strategy": s["strategy"], "tf": s["tf"],
                                    "why": L.why_words(s["why"]), "cf": _cf_out(cf)} for s, cf in out[:ROWS_KEEP]]})
        elif wid in ("judge", "time"):
            pairs = [(t, cf) for t, cf in zip(trades, base_cf) if t.get("exit_reason") == wid.upper()]
            dec = [(t, cf) for t, cf in pairs if _dec(cf)]
            deltas = [float(t["roe"]) - float(cf["roe"]) for t, cf in dec if _f(t.get("roe")) is not None]
            better = sum(1 for d in deltas if d > 1e-9)
            worse = sum(1 for d in deltas if d < -1e-9)
            v = _tally([cf for _t, cf in pairs])
            act = [float(t["roe"]) for t, _cf in dec if _f(t.get("roe")) is not None]
            off = wid == "time" and isinstance(cfg.get("trend"), dict) and "time_bars" in cfg["trend"] and cfg["trend"]["time_bars"] is None
            items.append({**_head(wid), **({"rule_ko": TIME_OFF_RULE_KO, "off": True} if off else {}), "state": "ok", "n": len(pairs), "held": v,
                          "actual": {"n": len(pairs), "roe_sum": sum(act), "roe_mean": sum(act) / len(act) if act else None,
                                     "decided": len(act)},
                          "delta": sum(deltas), "better": better, "worse": worse,
                          "verdict": {"kind": "off", "ko": TIME_OFF_KO} if off and not pairs
                          else verdict_paired(better, worse, len(deltas), sum(deltas), len(pairs)),
                          "rows": [{"t": int(t["exit_time"]), "entry_time": int(t["entry_time"]), "symbol": t.get("symbol"),
                                    "side": t.get("side"), "strategy": t.get("strategy_id"), "tf": t.get("timeframe"), "roe": t.get("roe"),
                                    "why": (t.get("context") or {}).get("exit_why") if isinstance(t.get("context"), dict) else None,
                                    "cf": _cf_out(cf), "delta": (float(t["roe"]) - float(cf["roe"])) if _dec(cf) and _f(t.get("roe")) is not None
                                    else None} for t, cf in reversed(pairs[-ROWS_KEEP:])]})
        else:                                            # pull
            dec = [x for x in pulls if _dec(x["held"]) and _dec(x["at"])]
            deltas = [float(x["held"]["roe"]) - float(x["at"]["roe"]) for x in dec]
            better = sum(1 for d in deltas if d > 1e-9)
            worse = sum(1 for d in deltas if d < -1e-9)
            gains = [x["gain"] for x in pulls if x["gain"] is not None]
            items.append({**_head(wid), **({"rule_ko": PULL_OFF_RULE_KO[wid], "off": True} if no_pull else {}),
                          "state": "ok", "n": len(pulls), "of": len(trades),
                          "gain": {"n": len(gains), "sum": sum(gains), "mean": sum(gains) / len(gains) if gains else None},
                          "held": _tally([x["held"] for x in pulls]), "at": _tally([x["at"] for x in pulls]),
                          "delta": sum(deltas), "better": better, "worse": worse,
                          "flips": {"won_lost": sum(1 for x in dec if x["held"]["state"] == "won" and x["at"]["state"] == "lost"),
                                    "lost_won": sum(1 for x in dec if x["held"]["state"] == "lost" and x["at"]["state"] == "won")},
                          "verdict": {"kind": "off", "ko": PULL_OFF_KO} if no_pull and not pulls
                          else verdict_paired(better, worse, len(deltas), sum(deltas), len(pulls)),
                          "rows": [{"t": int(x["t"]["entry_time"]), "symbol": x["t"].get("symbol"), "side": x["t"].get("side"),
                                    "strategy": x["t"].get("strategy_id"), "tf": x["t"].get("timeframe"), "sig_t": x["sig"]["t"],
                                    "sig_price": x["price"], "entry_price": x["t"].get("entry_price"), "gain": x["gain"],
                                    "cf": _cf_out(x["held"]), "at": _cf_out(x["at"]),
                                    "delta": (float(x["held"]["roe"]) - float(x["at"]["roe"])) if _dec(x["held"]) and _dec(x["at"]) else None}
                                   for x in reversed(pulls[-ROWS_KEEP:])]})
    srcs = [g["src"] for g in rp.bars.got.values()]
    bad = next((x for x in srcs if x.get("state") != "ok"), None)
    rule_src = bad or (srcs[0] if srcs else None)
    if bad is not None:                                  # no bars at all: nothing could be replayed (못 함 + why, never a zero)
        why = bad.get("reason_ko") or "규칙봇 1분봉을 읽지 못했어요"
        for it in items:
            it["verdict"] = {"kind": "na", "ko": f"못 함 · {why}"}
            it["bars"] = bad.get("state")
    return {"items": items, "work": {"done": rp.done, "pending": rp.pending, "memo": rp.memo, "budget_s": budget_s},
            "rule_db": {k: rule_src.get(k) for k in ("state", "reason_ko", "reason")} if rule_src else None,
            "note_ko": NOTE_KO, "base": base, "small_n": SMALL_N}


# ================================================================ the answer
def freeze_of(since: int, now: int) -> dict:
    until = int(since) + FREEZE_DAYS * DAY
    left = until - int(now)
    return {"since": int(since), "until": until, "days": FREEZE_DAYS, "day_n": max(1, min(FREEZE_DAYS, (int(now) - int(since)) // DAY + 1)),
            "left_ms": left, "d_left": max(0, -(-left // DAY)), "done": left <= 0, "frac": max(0.0, min(1.0, (int(now) - int(since)) / (FREEZE_DAYS * DAY)))}


def build(p: dict, now_ms: Optional[int] = None, more: Optional[dict] = None, budget_s: float = BUDGET_S) -> dict:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    more = more or L.paths_more()
    p = {**L.paths(), **p}                               # (a caller may name only the paper database)
    path = p["paper"]
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return {"state": "missing", "reason_ko": L.MISSING_KO, "now_ms": now}
    except (OSError, sqlite3.Error) as exc:
        return {"state": "error", "reason_ko": "페이퍼 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200], "now_ms": now}
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "state" not in tables:
            return {"state": "missing", "reason_ko": L.NO_TABLE_KO, "now_ms": now}
        _rt, run = LT._state(conn, "combo_run")
        cfg = (run or {}).get("config") if isinstance(run, dict) else None
        base = {"now_ms": now, "name": cfg.get("name") if isinstance(cfg, dict) else None}
        if not (isinstance(cfg, dict) and cfg.get("trend") is not None):
            return {**base, "state": "off", "reason_ko": "지금 돌고 있는 페이퍼 봇은 추세판단 봇이 아니에요 (설정에 추세 판단이 없음)"}
        _ts, st = LT._state(conn, "trend")
        since = (st or {}).get("since")
        if since is None:
            _cs, cst = LT._state(conn, "combo")
            since = (cst or {}).get("trend_since")
        if since is None:
            return {**base, "state": "missing", "reason_ko": "추세판단 봇이 아직 첫 판단을 기록하지 않았어요 (켠 뒤 1~2분)"}
        since = int(since)
        real = _trades(conn, ACCOUNT, since) if "trades" in tables else []
        flip = _trades(conn, FLIP, since) if "trades" in tables else []
        sigs = [_sig(r) for r in conn.execute(
            "SELECT bar_close, timeframe, strategy, symbol, side, atr, ref_price, status, data FROM signal_log WHERE bar_close >= ? "
            "ORDER BY bar_close, id", (since,)).fetchall()] if "signal_log" in tables else None
        entered, skipped, meta = [], [], {}
        if "outcomes" in tables:
            for step, status, sym, data in conn.execute(
                    "SELECT step_ts, status, symbol, data FROM outcomes WHERE account_id = ? AND step_ts >= ? AND status IN ('ENTERED', 'SKIPPED')",
                    (ACCOUNT, since)).fetchall():
                if status == "SKIPPED":
                    skipped.append(int(step))
                    continue
                sig = _json(data).get("signal")
                m = sig.get("meta") if isinstance(sig, dict) and isinstance(sig.get("meta"), dict) else {}
                entered.append({"t": int(step), "symbol": sym})
                meta[(sym, int(step))] = m.get("ref_price") is not None
    except sqlite3.Error as exc:
        return {"state": "error", "reason_ko": "페이퍼 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200], "now_ms": now}
    finally:
        conn.close()
    r_rec, f_rec = rec_of(real), rec_of(flip)
    out = {**base, "state": "ok", "since": since, "bot": {"name": base["name"], **freeze_of(since, now)},
           "record": {"real": r_rec, "flip": f_rec, "luck": luck_of(r_rec, f_rec), "small_n": SMALL_N, "more_n": MORE_N,
                      "flip_on": "trades" in tables and (cfg.get("flip_twin", True) is not False)},
           "execs": exec_since(p, since, now), "curve": {"real": curve_of(real, since), "flip": curve_of(flip, since)},
           "split": split_of(real, cfg), "small_n": SMALL_N, **LT.entry_style(cfg, (st or {}).get("numbers"))}
    if sigs is None:
        out.update(days=None, funnel=None, signals_state={"state": "missing", "reason_ko": "신호 기록 표(signal_log)가 아직 없어요"})
        out["whatif"] = {"items": [_na(w[0], "missing", "신호 기록 표(signal_log)가 아직 없어요") if w[0] in BLOCKED or w[0] == "pull"
                                   else _na(w[0], "missing", "신호 기록 표가 없어 함께 계산하지 않았어요") for w in WHATIF],
                         "work": None, "note_ko": NOTE_KO, "base": None}
        return out
    out["days"] = days_of(sigs, entered, skipped, real, flip, since, now)
    out["funnel"] = funnel_of(sigs, entered, skipped)
    out["whatif"] = whatifs(sigs, real, meta, {"taker_fee": (run or {}).get("taker_fee"), "config": cfg}, cfg, more["rule_db"], now,
                            budget_s)
    return out


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/trendreview")
    def get_livebots_trendreview():
        """실거래 › 검토: the trend bot's 2-week review (its record against the coin-flip twin, day by day, did each new rule
        help (가상), the record split); read-only, 5 s cache."""
        p, more = L.paths(), L.paths_more()
        key = "trendreview:" + json.dumps([p, more], sort_keys=True)
        return L._cached(key, lambda: json_finite(build(p, more=more)))

    return {"routes": ["/api/v4/livebots/trendreview"]}
