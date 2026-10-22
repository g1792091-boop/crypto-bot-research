"""실거래 › 재현 비교 (#/expect; owners 10/21 night: the 추세판단 봇 replayed on 7/1~10/20 before it went live): the replay
(data/trend_replay_0701_1020.json: the bot's exact rules on real Binance 1m bars, every entry and exit, the costs split)
next to what the live bot really does since its start. As live trades come in: does the live bot behave like the replay,
and does the cost problem the replay showed play out (about break-even before costs, the slippage and the fees taking
the rest)? Read-only, like every 실거래 tab: nothing here changes a rule (that is the owners' decision).

    GET /api/v4/livebots/replayref   (5 s cache; the page asks every 60 s)
        ref      the replay: its window, what it is (``what``), every caveat (``honest_ko``), its setup
        entries  진입 횟수: the replay's entries a weekday and the histogram of its 80 weekdays against the paper's entries
                 since the start (KST weekdays, a partial day as its fraction; weekend entries apart), with the band the
                 replay leaves for that many weekdays (``entries_band``: exact, 5 %-95 %)
        funnel   깔때기: signals -> after the pauses and the chase block -> passed the checks -> pullback touched (the
                 paper's only while its config waits: the owners' enters at once since 10-22) -> entered, the replay's
                 against the paper's since the start (livereview's own funnel, never the bot's
                 rules again), and where the rest stopped in livetrend.BLOCK's categories
        results  거래 결과: n, win rate (net P&L > 0), mean / median net ROE, the exits by reason with their median hold:
                 the replay, the paper, each executor (an executor's close that followed the paper takes the paper
                 trade's reason: livebots.pairs_of); the band the replay leaves for the mean of n trades (``walks``)
        costs    비용 쪼개기: per trade, the mean net ROE before costs -> slippage -> fees (-> funding) -> net. The replay's
                 from the file; the paper's from its own records (the fees it booked; the slippage its fills carry at the
                 engine's rate, engine.py: entry ref x (1 + side x slip), a market or stop exit x (1 - side x slip));
                 each executor's from its exchange fills (commission, the slippage it measured against the price it
                 saw when deciding, funding: livepnl.trade_costs) on the trades whose fills were read
        split    나눠 보기: by member, coin and side, the replay's count and mean net ROE against each live account's
        curve    누적: the cumulative net ROE sum by trade number, the replay's 89 and each live account's, with the band
                 the replay leaves at each trade number (``walks``)

The bands are deterministic. Entries: the replay's weekday histogram as one weekday's distribution, a partial weekday
thinned to its fraction (each entry of a day falls in the elapsed part with that chance), convolved over the live
weekdays; 5 %-95 % of the sum. Net ROE: WALKS random walks of the replay's 89 net ROEs drawn with replacement, each walk
its own fixed seed (the first n steps of a walk never depend on how long it is drawn), 5 %-95 % of the cumulative sum at
every trade number; the band of a mean is that of the sum / n. Verdicts never overclaim: under SMALL_N live trades
표본 적음 · 아직 판단 못 함; otherwise only inside / above / below "재현이라면 보통 이 범위".

The reference file is read relative to the repository (paperbot/events.py's PATH rule), once per change of the file.
The paper bot's database is PAPERBOT_LIVE_PAPER_DB, the executors' their own (livebots.paths / sources), all read-only
(livebots.open_ro: mode=ro, query_only). States (CONTRACT 1.6): no paper file / table = missing; the running paper bot
is not the trend bot (``combo_run`` without ``trend``) = off; the trend bot's start not recorded yet = missing; no
reference file = missing; unreadable = error. Never a zero for an unread value: a stage the live records cannot tell is
None with the reason. Times are UTC ms, ratios are ratios (0.1 = 10 %); ROE is net P&L / margin.
"""
from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from . import livebots as L
from . import livereview as LR
from . import livetrend as LT

ACCOUNT = L.ACCOUNT
REF_PATH = Path(__file__).resolve().parents[3] / "data" / "trend_replay_0701_1020.json"
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
SMALL_N = L.SMALL[0]                 # under 20 live trades: 표본 적음 · 아직 판단 못 함
QS = (0.05, 0.95)                    # the band: what the replay gives 90 % of the time
SEED = 20261021                      # the walks' fixed seed (the day the replay was made)
WALKS = 2000                         # random walks of the replay's trades (the net ROE bands)
WALK_STEP = 50                       # walks are drawn this many trades at a time (a longer live record: one more step)
FEW_DAYS = 5                         # under this many live weekdays the entries band is wide (said so)
DAYS_KEEP = 60                       # live KST days listed (the newest)
NO_SLIP_EXIT = ("LIQ", "TP")         # the paper engine's exits filled without slippage (a liquidation, a maker take-profit)
EXITS = ("LOCK", "TIME", "SL", "REV", "JUDGE", "LIQ", "OTHER")
EXIT_KO = dict(LT.EXIT_GROUP)
# the funnel's stages, the replay's file keys and the live funnel's (livereview.funnel_of)
STAGES = (("signals", "신호", "signals"), ("after_time", "쉬는 시간·추격 막기 뒤", "after_time_rules"),
          ("passed", "추세·자리 검사 통과", "passed_check"), ("touched", "되돌림 닿음", "pullback_touched"),
          ("entered", "진입", "entered"))
# the live funnel's blocks at the signal (combo._entry_block and the trend bot's pauses: before the trend and spot checks)
AT_SIGNAL = ("pause", "chase", "member_pause", "coin_pause", "daily")
# the replay's reasons in the live funnel's categories (livetrend.BLOCK ids)
REF_BLOCK = {"weekend": "pause", "macro": "pause", "us_open": "pause", "chase": "chase", "adx<20": "trend", "adx_tired": "trend",
             "htf_hold(held<2/raw flip)": "trend", "htf_hold(votes<3)": "trend", "htf_opposite": "trend",
             "breakout_not_early": "spot", "etf_ema_far": "spot", "htf_ema_far": "spot"}
SIDE_ID = {"long": 1, "short": -1}
NEED = ("what", "honest_ko", "window_kst", "window_ms", "setup", "entries", "funnel", "trades", "trade_list")
REF_MISSING_KO = "재현 기준 파일(data/trend_replay_0701_1020.json)이 없어요"
REF_BAD_KO = "재현 기준 파일을 읽지 못했어요"
PAPER_SLIP_KO = "페이퍼의 미끄러짐은 규칙에 넣은 가정(한쪽 0.02%)이에요 · 실거래 칸이 거래소 체결로 잰 값이에요"
# the replay ran with the 시간 정리 exit (trend.time_bars 4: no first lock within 4 entry bars -> closed); the owners took it
# out on 10/21 night (time_bars null): every comparison with the replay says so (time_note_ko)
TIME_GONE_KO = ("재현은 시간 정리(진입 봉 4개 안에 첫 잠금을 못 가면 청산)가 있던 규칙으로 돌린 숫자예요 · 10/21 밤 그 규칙을 "
                "뺐어요: 재현의 시간 정리 {n}번은 지금 봇이라면 손절 · 계단 익절 · 추세 뒤집힘 청산으로 끝났을 거예요")
TIME_KEPT_KO = "재현은 시간 정리(진입 봉 4개 안에 첫 잠금을 못 가면 청산)를 넣고 돌린 숫자예요 (지금 설정과 같음)"
EXEC_BEFORE_KO = ("실거래의 '비용 전'은 주문 직전 본 가격 기준이에요 (페이퍼보다 늦게 들어간 차이는 비용 전 안에 들어 있어요 · "
                  "비용 탭에서 따로 봐요)")

_lock = threading.Lock()
_ref: dict = {}
_walks: dict = {}


# ================================================================ small helpers
def _f(x) -> Optional[float]:
    return L._f(x)


def _r(x: Optional[float], nd: int = 6) -> Optional[float]:
    return None if x is None else round(float(x), nd)


def _mean(xs: list) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _median(xs: list) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return float(xs[m]) if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def pct(x: Optional[float], dec: int = 1) -> str:
    """A ratio as a signed percent with the true minus: -0.0044 -> "−0.4%"."""
    if x is None:
        return "—"
    v = round(float(x) * 100, dec)
    return (f"{v:+.{dec}f}%" if v else f"{0:.{dec}f}%").replace("-", "−")


def pp(x: Optional[float], dec: int = 1) -> str:
    """An amount in percentage points (a cost): 0.0448 -> "4.5%p"."""
    return "—" if x is None else f"{float(x) * 100:.{dec}f}%p".replace("-", "−")


def kst_day0(ms: int) -> int:
    return LR.kst_day0(ms)


# ================================================================ the reference file
def load_ref(path=None) -> dict:
    """{"state": "ok", "d": the file} once per change of the file; missing / error with the reason otherwise."""
    path = str(path or REF_PATH)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return {"state": "missing", "reason_ko": REF_MISSING_KO, "path": path}
    except OSError as exc:
        return {"state": "error", "reason_ko": REF_BAD_KO, "reason": f"{type(exc).__name__}: {exc}"[:200], "path": path}
    key = (path, st.st_mtime_ns, st.st_size)
    with _lock:
        hit = _ref.get(path)
        if hit and hit[0] == key:
            return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        miss = [k for k in NEED if k not in d] if isinstance(d, dict) else list(NEED)
        if miss:
            raise ValueError(f"missing keys: {', '.join(miss)}")
        if not d["trade_list"] or not d["entries"].get("hist_weekdays"):
            raise ValueError("no trades or no weekday histogram")
        out = {"state": "ok", "d": d, "key": key}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        out = {"state": "error", "reason_ko": REF_BAD_KO, "reason": f"{type(exc).__name__}: {exc}"[:200], "path": path}
    with _lock:
        _ref[path] = (key, out)
    return out


# ================================================================ 진입 횟수 and its band
def weekday_fracs(since: int, now: int) -> list:
    """[(KST day start, the part of it elapsed since ``since``: 0..1)] of every KST weekday from the start to now."""
    out = []
    d0 = kst_day0(since)
    while d0 < now:
        d1 = d0 + DAY
        if not L.kst_weekend(d0):
            f = (min(int(now), d1) - max(int(since), d0)) / DAY
            if f > 0:
                out.append((d0, min(1.0, f)))
        d0 = d1
    return out


def day_pmf(hist: dict) -> list:
    """The replay's weekday histogram ({"0": 27, "1": 27, ...}) as one weekday's distribution [p(0), p(1), ...]."""
    h = {int(k): int(v) for k, v in hist.items()}
    n = sum(h.values())
    return [h.get(k, 0) / n for k in range(max(h) + 1)]


def thin(p: list, f: float) -> list:
    """A day's distribution over the elapsed part ``f`` of it: each entry falls in it with chance f."""
    if f >= 1:
        return list(p)
    q = [0.0] * len(p)
    for k, pk in enumerate(p):
        for j in range(k + 1):
            q[j] += pk * math.comb(k, j) * f ** j * (1 - f) ** (k - j)
    return q


def conv(a: list, b: list) -> list:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x:
            for j, y in enumerate(b):
                out[i + j] += x * y
    return out


def quantile_int(pmf: list, q: float) -> int:
    """The smallest count whose cumulative chance reaches ``q``."""
    c = 0.0
    for k, x in enumerate(pmf):
        c += x
        if c >= q - 1e-12:
            return k
    return len(pmf) - 1


def entries_band(hist: dict, fracs: list) -> Optional[dict]:
    """5 %-95 % of the replay's total entries over these weekdays (each a fraction 0..1): {lo, hi, mean}; None without one."""
    fr = [f for f in fracs if f > 0]
    if not fr:
        return None
    p = day_pmf(hist)
    tot = [1.0]
    for f in fr:
        tot = conv(tot, thin(p, f))
    mean_day = sum(k * x for k, x in enumerate(p))
    return {"lo": quantile_int(tot, QS[0]), "hi": quantile_int(tot, QS[1]), "mean": mean_day * sum(fr), "days": sum(fr)}


def where_in(x: Optional[float], lo: Optional[float], hi: Optional[float]) -> Optional[str]:
    if x is None or lo is None or hi is None:
        return None
    return "above" if x > hi + 1e-12 else "below" if x < lo - 1e-12 else "inside"


def entries_of(ref: dict, times: list, since: int, now: int) -> dict:
    """진입 횟수: the replay's numbers, the live entries since the start (weekdays as fractions, the weekend apart), the band."""
    e = ref["entries"]
    wk = e.get("weekdays") or {}
    hist = e["hist_weekdays"]
    rep = {"weekdays": wk.get("days"), "entries": wk.get("entries"), "per_weekday": _f(wk.get("mean")), "median": _f(wk.get("median")),
           "max": wk.get("max"), "weekend_entries": e.get("weekend_entries"),
           "hist": [[int(k), int(v)] for k, v in sorted(hist.items(), key=lambda kv: int(kv[0]))],
           "by_month": [{"month": m, **v} for m, v in sorted((e.get("by_month") or {}).items())]}
    fracs = weekday_fracs(since, now)
    wd_days = sum(f for _d, f in fracs)
    times = sorted(int(t) for t in times if int(t) >= since)
    weekend = [t for t in times if L.kst_weekend(t)]
    weekday = [t for t in times if not L.kst_weekend(t)]
    days, d0 = [], kst_day0(since)
    while d0 < now:
        d1 = d0 + DAY
        n = sum(1 for t in times if d0 <= t < d1)
        f = (min(int(now), d1) - max(int(since), d0)) / DAY
        days.append({"d0": d0, "weekend": L.kst_weekend(d0), "frac": round(min(1.0, f), 4), "n": n, "today": d0 <= now < d1})
        d0 = d1
    full = [x for x in days if not x["weekend"] and x["frac"] >= 0.999]
    top = max([k for k, _v in rep["hist"]] + [x["n"] for x in full] + [0])
    live_hist = [[k, sum(1 for x in full if x["n"] == k)] for k in range(top + 1)]
    live = {"weekdays": round(wd_days, 4), "weekday_days": len(fracs), "full_weekdays": len(full), "entries": len(weekday),
            "weekend_entries": len(weekend), "all": len(times), "per_weekday": len(weekday) / wd_days if wd_days > 0 else None,
            "hist": live_hist, "days": days[-DAYS_KEEP:]}
    band = entries_band(hist, [f for _d, f in fracs])
    if band:
        band["where"] = where_in(len(weekday), band["lo"], band["hi"])
    return {"replay": rep, "live": live, "band": band, "ko": entries_ko(live, band), "weekend_ko": weekend_ko(live, rep)}


def weekdays_ko(d: float) -> str:
    """The weekdays since the start in words: "평일 2.5일"; under one day in hours ("평일 3시간", "평일 30분"), never 0.0일."""
    if d >= 1:
        return f"평일 {d:.1f}일"
    m = d * 24 * 60
    return f"평일 {m:.0f}분" if m < 60 else f"평일 {m / 60:.0f}시간"


def entries_ko(live: dict, band: Optional[dict]) -> str:
    if band is None:
        return "아직 평일이 지나지 않아 견줄 수 없어요 (재현에선 평일에만 들어갔어요)"
    d, k, lo, hi = live["weekdays"], live["entries"], band["lo"], band["hi"]
    rng = f"재현이라면 보통 {lo}~{hi}번" if lo != hi else f"재현이라면 보통 {lo}번"
    tail = {"inside": "그 안이에요", "above": "보통 범위보다 많아요", "below": "보통 범위보다 적어요"}[band["where"]]
    if d < 1:                                            # the first day: a fraction of a weekday reads in hours
        return f"새 규칙 시작 뒤 {weekdays_ko(d)} 동안 {k}번 들어갔어요 · {rng} · {tail} (아직 하루도 안 돼 진입이 없어도 보통이에요)"
    few = f" ({weekdays_ko(d)}뿐이라 범위가 넓어요)" if d < FEW_DAYS else ""
    return f"{weekdays_ko(d)} 동안 {k}번 들어갔어요 · {rng} · {tail}{few}"


def time_note_ko(d: dict, cfg: Optional[dict]) -> str:
    """The replay's 시간 정리 against the running config (``trend.time_bars`` null = taken out, 10/21 night)."""
    tr = (cfg or {}).get("trend") if isinstance((cfg or {}).get("trend"), dict) else {}
    if "time_bars" in tr and tr["time_bars"] is None:
        n = (((d.get("trades") or {}).get("by_reason") or {}).get("TIME") or {}).get("n")
        return TIME_GONE_KO.format(n=n if n is not None else "몇")
    return TIME_KEPT_KO


# the replay ran on the 10/21 design (its members: 30m and 1h entries, 보류 = no entry, the pullback wait); the owners' 10/22
# design (deploy/combo.trend.json: 18 members, 4h entries on the closed daily bar, 보류 허용, 바로 진입) differs: every
# comparison with the replay says how, from the running config (design_note_ko)
DESIGN_KO = "재현은 10/21 설계(진입 매매법 {n}개 · 30분·1시간 진입 · 보류면 진입 안 함 · 되돌림 기다림)로 돌린 숫자예요"


def design_note_ko(d: dict, cfg: Optional[dict]) -> Optional[str]:
    """How the running config differs from the design the replay ran on: its 4h entries, 보류 허용, 바로 진입 (and then its
    member count); None for a config of the replay's design."""
    tr = (cfg or {}).get("trend") if isinstance((cfg or {}).get("trend"), dict) else {}
    members = [m for m in (cfg or {}).get("members") or [] if isinstance(m, dict)]
    n_ref = (d.get("setup") or {}).get("members")
    diffs = []
    if any(m.get("tf") == "4h" for m in members):
        diffs.append("4시간 진입(끝난 일봉 판단)")
    if tr.get("hold_entry"):
        diffs.append("보류 허용")
    if tr.get("pullback_wait", True) is False:
        diffs.append("바로 진입(되돌림 안 기다림)")
    if not diffs:
        return None
    if members and isinstance(n_ref, int) and len(members) != n_ref:
        diffs.insert(0, f"진입 매매법 {len(members)}개")
    return (DESIGN_KO.format(n=n_ref if isinstance(n_ref, int) else "10") + f" · 지금 봇과 다른 점: {' · '.join(diffs)} · 진입 "
            "횟수·결과가 다를 수 있어 참고로만 봐요")


def weekend_ko(live: dict, rep: dict) -> str:
    n = live["weekend_entries"]
    if n:
        return f"주말에 {n}번 들어갔어요 · 재현은 주말 {rep.get('weekend_entries') or 0}번 (주말엔 쉬는 규칙)"
    return f"주말 진입 없음 · 재현도 주말 {rep.get('weekend_entries') or 0}번 (주말엔 쉬는 규칙)"


# ================================================================ the net ROE bands (fixed-seed walks of the replay)
def walks(vals: tuple, k_max: int, seed: int = SEED, reps: int = WALKS) -> dict:
    """{"lo": [...], "hi": [...]}: 5 %-95 % of the cumulative net ROE sum after k = 0..k_max trades drawn with replacement
    from ``vals`` (the replay's trades), ``reps`` walks each with its own seed (seed, walk): deterministic, and the first
    n steps of a walk do not depend on k_max. Cached."""
    k_max = max(1, -(-int(k_max) // WALK_STEP) * WALK_STEP)
    key = (hash(vals), len(vals), k_max, seed, reps)
    with _lock:
        hit = _walks.get(key)
    if hit is not None:
        return hit
    cols = [[0.0] * reps for _ in range(k_max + 1)]
    for r in range(reps):
        rng = random.Random(seed * 100_003 + r)
        c = 0.0
        for k, v in enumerate(rng.choices(vals, k=k_max), 1):
            c += v
            cols[k][r] = c
    lo_i, hi_i = max(0, math.ceil(QS[0] * reps) - 1), max(0, math.ceil(QS[1] * reps) - 1)
    lo, hi = [], []
    for col in cols:
        col.sort()
        lo.append(col[lo_i])
        hi.append(col[hi_i])
    out = {"lo": lo, "hi": hi, "k_max": k_max, "reps": reps, "seed": seed}
    with _lock:
        _walks[key] = out
        while len(_walks) > 8:
            _walks.pop(next(iter(_walks)))
    return out


def mean_band(w: dict, n: int) -> Optional[list]:
    """[low, high] of the mean net ROE of n trades the replay gives 90 % of the time."""
    if not n or n > w["k_max"]:
        return None
    return [w["lo"][n] / n, w["hi"][n] / n]


def verdict(n: int, mean: Optional[float], band: Optional[list]) -> dict:
    """The live mean net ROE against the replay's band: never more than 표본 적음 under SMALL_N trades."""
    if not n:
        return {"kind": "none", "ko": "아직 닫힌 거래가 없어요"}
    w = where_in(mean, *(band or (None, None)))
    if n < SMALL_N:
        return {"kind": "small", "where": w, "ko": f"표본 적음 · 아직 판단 못 함 (거래 {n}번 · {SMALL_N}번부터 봐요)"}
    if w is None:
        return {"kind": "na", "ko": "범위를 계산하지 못했어요"}
    rng = f"재현이라면 {n}번 평균이 보통 {pct(band[0])}~{pct(band[1])}"
    tail = {"inside": "그 안이에요", "above": "보통 범위보다 높아요", "below": "보통 범위보다 낮아요"}[w]
    return {"kind": w, "where": w, "ko": f"{rng} · {tail}"}


# ================================================================ trades in one shape: the replay's, the paper's, an executor's
def replay_rows(ref: dict) -> list:
    out = []
    for t in sorted(ref["trade_list"], key=lambda t: (t["entry_time"], t["exit_time"])):
        member = str(t.get("member") or "")
        out.append({"entry": int(t["entry_time"]), "exit": int(t["exit_time"]), "member": member or None, "symbol": t.get("symbol"),
                    "side": SIDE_ID.get(t.get("side"), 0), "reason": t.get("reason"), "roe": float(t["roe"]),
                    "before": _f(t.get("roe_before_costs")), "hold": round((int(t["exit_time"]) - int(t["entry_time"])) / MIN)})
    return out


def paper_row(t: dict, slip: float) -> dict:
    """One paper trade (a TradeRecord) with its costs as net ROE points: the fees it booked, the slippage its fills
    carry at the engine's rate (entry and market / stop exit), the funding it paid; before = net + all three."""
    side, qty, e, x = int(t.get("side") or 0), _f(t.get("qty")), _f(t.get("entry_price")), _f(t.get("exit_price"))
    m, roe = _f(t.get("margin")), _f(t.get("roe"))
    reason = t.get("exit_reason")
    row = {"entry": int(t.get("entry_time") or 0), "exit": int(t.get("exit_time") or 0),
           "member": f"{t.get('strategy_id')}@{t.get('timeframe')}" if t.get("strategy_id") else None, "symbol": t.get("symbol"),
           "side": side, "reason": reason, "roe": roe, "hold": round((int(t.get("exit_time") or 0) - int(t.get("entry_time") or 0)) / MIN),
           "before": None, "slip": None, "fee": None, "funding": None}
    if roe is None or not m or m <= 0 or not side or not qty or not e or x is None or _f(t.get("fees")) is None:
        return row
    raw_in = e / (1 + side * slip)
    raw_out = 0.0 if reason in NO_SLIP_EXIT else x / (1 - side * slip)
    s = qty * slip * (raw_in + raw_out) / m
    fee = float(t["fees"]) / m
    fund = (_f(t.get("funding")) or 0.0) / m
    row.update(slip=s, fee=fee, funding=fund, before=roe + s + fee + fund)
    return row


def exec_row(t: dict, pair: Optional[dict], cost_ok: Optional[int]) -> dict:
    """One executor trade (livebots._live_trade): its reason (a close that followed the paper takes the paper trade's),
    its member (the paper trade it followed), and its costs from the exchange's fills when they were read and measured."""
    reason = t.get("exit_reason")
    if reason == "PAPER" and pair:
        reason = pair.get("exit_reason") or reason
    m, roe = _f(t.get("margin")), _f(t.get("roe"))
    row = {"entry": int(t.get("entry_ts") or 0), "exit": int(t.get("exit_ts") or 0),
           "member": f"{pair.get('strategy_id')}@{pair.get('timeframe')}" if pair and pair.get("strategy_id") else None,
           "symbol": t.get("symbol"), "side": int(t.get("side") or 0), "reason": reason, "roe": roe, "est": bool(t.get("est")),
           "hold": round((int(t.get("exit_ts") or 0) - int(t.get("entry_ts") or 0)) / MIN),
           "before": None, "slip": None, "fee": None, "funding": None}
    com, sl = _f(t.get("commission")), _f(t.get("slippage"))
    if t.get("est") or roe is None or not m or m <= 0 or com is None or sl is None or cost_ok == 0:
        return row
    fund = -(_f(t.get("funding")) or 0.0) / m          # the exchange's funding income (+ received): a cost when paid
    row.update(slip=sl / m, fee=com / m, funding=fund, before=roe + sl / m + com / m + fund)
    return row


def _cost_ok(path: str) -> dict:
    """{trade key: cost_ok} of an executor's database (1: its fills measured the cost; 0: not), read-only; {} unread."""
    try:
        conn = L.open_ro(path)
    except (OSError, sqlite3.Error):
        return {}
    try:
        if "cost_ok" not in L._cols(conn, "trades"):
            return {}
        return {str(k): (None if v is None else int(v)) for k, v in conn.execute("SELECT key, cost_ok FROM trades")}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


# ================================================================ 거래 결과 · 비용 · 나눠 보기 · 누적
def record(rows: list) -> dict:
    """n, wins (net ROE > 0), win rate, mean / median net ROE, median hold, the exits by reason."""
    roes = [r["roe"] for r in rows if r["roe"] is not None]
    n = len(roes)
    wins = sum(1 for x in roes if x > 0)
    by: dict = {}
    for r in rows:
        k = r["reason"] if r["reason"] in EXITS[:-1] else "OTHER"
        by.setdefault(k, []).append(r)
    exits = [{"id": k, "ko": EXIT_KO.get(k, k), "n": len(by[k]), "share": len(by[k]) / len(rows),
              "roe_mean": _r(_mean([r["roe"] for r in by[k]])), "hold_med": _median([r["hold"] for r in by[k]])}
             for k in EXITS if k in by]
    return {"n": n, "wins": wins, "win_rate": wins / n if n else None, "roe_mean": _r(_mean(roes)), "roe_median": _r(_median(roes)),
            "hold_med": _median([r["hold"] for r in rows]), "exits": exits, "small": n < SMALL_N,
            "estimated": sum(1 for r in rows if r.get("est"))}


def costs_of(rows: list) -> dict:
    """The mean per trade of the rows whose costs are known: before -> slippage -> fees -> funding -> net (costs as
    positive net ROE points taken)."""
    ok = [r for r in rows if r["before"] is not None]
    if not ok:
        return {"n": 0, "of": len(rows), "before": None, "slip": None, "fee": None, "funding": None, "net": None, "cost": None}
    m = {k: _mean([r[k] for r in ok]) for k in ("before", "slip", "fee", "funding", "roe")}
    return {"n": len(ok), "of": len(rows), "before": _r(m["before"]), "slip": _r(m["slip"]), "fee": _r(m["fee"]),
            "funding": _r(m["funding"]), "net": _r(m["roe"]), "cost": _r(m["slip"] + m["fee"] + m["funding"]),
            "small": len(ok) < SMALL_N}


def replay_costs(ref: dict) -> dict:
    tr = ref["trades"]
    b, s, f, net = (_f(tr.get(k)) for k in ("roe_mean_before_costs", "slippage_roe_mean", "fee_roe_mean", "roe_mean"))
    return {"n": tr.get("n"), "of": tr.get("n"), "before": b, "slip": s, "fee": f, "funding": None, "net": net,
            "cost": (s or 0.0) + (f or 0.0) if s is not None or f is not None else None, "small": False}


def costs_ko(rep: dict) -> str:
    """The key sentence, from the file: what the replay made before costs, what the costs took."""
    b, c = rep.get("before"), rep.get("cost")
    if b is None or c is None:
        return "재현 파일에 비용을 나눈 숫자가 없어요"
    if abs(b) < 0.01:
        head = f"재현에서는 수수료·미끄러짐 전엔 거의 본전(거래당 {pct(b)})이었고"
    elif b > 0:
        head = f"재현에서는 수수료·미끄러짐 전엔 거래당 {pct(b)}를 벌었고"
    else:
        head = f"재현에서는 수수료·미끄러짐 전에도 거래당 {pct(b)}였고"
    return f"{head}, 비용이 거래당 {pp(c)}를 가져갔어요."


def live_costs_ko(c: dict) -> str:
    """A live account's costs in one line (the page puts the account's name in front)."""
    if c.get("state") not in (None, "ok"):
        return c.get("reason_ko") or "못 읽음"
    if not c.get("of"):
        return "새 규칙 뒤 닫힌 거래가 아직 없어요"
    if not c.get("n"):
        return f"체결 기록으로 비용을 잰 거래가 아직 없어요 (닫힌 거래 {c['of']}번)"
    fund = f" · 펀딩 {pp(c['funding'])}" if c.get("funding") and abs(c["funding"]) >= 0.0005 else ""
    small = f" · 표본 적음 (거래 {c['n']}번)" if c.get("small") else f" (거래 {c['n']}번)"
    return (f"비용 전 거래당 {pct(c['before'])} → 미끄러짐 {pp(c['slip'])} · 수수료 {pp(c['fee'])}{fund}"
            f" → 순 {pct(c['net'])}{small}")


def split_of(accts: dict) -> dict:
    """나눠 보기 by member, coin and side: each key's count and mean net ROE, the replay's and every live account's."""
    keys = {"member": lambda r: r["member"], "coin": lambda r: r["symbol"], "side": lambda r: r["side"] or None}
    out = {}
    for dim, key in keys.items():
        by: dict = {}
        for aid, rows in accts.items():
            for r in rows:
                if r["roe"] is None:
                    continue
                by.setdefault(key(r), {}).setdefault(aid, []).append(r["roe"])
        rows_out = []
        for k, per in by.items():
            row = {"id": k, **{aid: {"n": len(per.get(aid) or []), "mean": _r(_mean(per.get(aid) or []))} for aid in accts}}
            if dim == "member" and k:
                s, _sep, tf = str(k).partition("@")
                row.update(strategy=s, tf=tf, role=L.TREND_ROLE.get(s))
            rows_out.append(row)
        rows_out.sort(key=lambda r: (r["id"] is None, -r["replay"]["n"], -sum(r[a]["n"] for a in accts if a != "replay"), str(r["id"])))
        out[dim] = rows_out
    return out


def cum_of(rows: list) -> list:
    """[0, sum after trade 1, after trade 2, ...] of the net ROE, in closing order."""
    out, c = [0.0], 0.0
    for r in sorted((r for r in rows if r["roe"] is not None), key=lambda r: (r["exit"], r["entry"])):
        c += r["roe"]
        out.append(round(c, 6))
    return out


# ================================================================ 깔때기
NO_PULL_KO = "바로 진입이라 없음 (되돌림 안 기다림)"


def funnel_view(ref: dict, f: Optional[dict], skipped: Optional[int], entered_known: bool, pull: bool = True) -> dict:
    """The replay's stages and the paper's since the start (livereview.funnel_of), each as a count, its share of the signals
    and of the stage before; where the rest stopped, in livetrend.BLOCK's categories. ``pull`` false (the running config
    enters at once, owners 10-22): the paper has no pullback stage (NO_PULL_KO, never a 0), its entries against the checks
    passed."""
    rf = ref["funnel"]
    rep = [{"id": sid, "ko": ko, "n": rf.get(fk)} for sid, ko, fk in STAGES]
    rblock: dict = {}
    for src in ("blocked_at_signal", "check_failed"):
        for k, n in (rf.get(src) or {}).items():
            g = REF_BLOCK.get(k, "other")
            rblock[g] = rblock.get(g, 0) + int(n)
    if rf.get("no_pullback"):
        rblock["nopull"] = rblock.get("nopull", 0) + int(rf["no_pullback"])
    one = int(rf.get("skipped_in_position") or 0) + int(rf.get("skipped_lower_score") or 0)
    if one:
        rblock["one"] = one
    out = {"replay": _shares(rep), "replay_blocked": [{"id": k, "ko": ko, "n": rblock[k]} for k, ko in LT.BLOCK if rblock.get(k)],
           "replay_detail": {"blocked_at_signal": rf.get("blocked_at_signal") or {}, "check_failed": rf.get("check_failed") or {}}}
    if f is None:
        out.update(live=None, live_blocked=None, state="missing", reason_ko="신호 기록 표(signal_log)가 아직 없어요")
        return out
    blk = {b["id"]: b["n"] for b in f.get("blocked") or []}
    after = f["signals"] - sum(blk.get(k, 0) for k in AT_SIGNAL)
    live = [{"id": "signals", "n": f["signals"]}, {"id": "after_time", "n": after}, {"id": "passed", "n": f["passed"]},
            {"id": "touched", "n": f["touched"]}, {"id": "entered", "n": f["entered"] if entered_known else None}]
    if not pull and not f["touched"]:
        live[3] = {"id": "touched", "n": None, "why_ko": NO_PULL_KO}
    for x, (_sid, ko, _fk) in zip(live, STAGES):
        x["ko"] = ko
        if x["n"] is None and "why_ko" not in x:
            x["why_ko"] = "진입 기록 표(outcomes)가 없어 모름"
    live = _shares(live)
    if live[3]["n"] is None and live[4]["n"] is not None and live[2]["n"]:
        live[4]["of_prev"] = live[4]["n"] / live[2]["n"]           # 바로 진입: the entries out of the checks passed
    out.update(state="ok", live=live, live_blocked=f.get("blocked") or [], skipped={"replay": one, "live": skipped})
    return out


def _shares(stages: list) -> list:
    top = stages[0]["n"]
    prev = None
    for x in stages:
        n = x["n"]
        x["share"] = n / top if n is not None and top else None
        x["of_prev"] = n / prev if n is not None and prev else None
        prev = n
    return stages


# ================================================================ the answer
def _read_paper(path: str, now: int) -> dict:
    """The paper bot's start, config, trades, entries, signals since the start (one read-only snapshot)."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return {"state": "missing", "reason_ko": L.MISSING_KO}
    except (OSError, sqlite3.Error) as exc:
        return {"state": "error", "reason_ko": "페이퍼 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "state" not in tables:
            return {"state": "missing", "reason_ko": L.NO_TABLE_KO}
        _rt, run = LT._state(conn, "combo_run")
        cfg = (run or {}).get("config") if isinstance(run, dict) else None
        name = cfg.get("name") if isinstance(cfg, dict) else None
        if not (isinstance(cfg, dict) and cfg.get("trend") is not None):
            return {"state": "off", "name": name, "reason_ko": "지금 돌고 있는 페이퍼 봇은 추세판단 봇이 아니에요 (설정에 추세 판단이 없음)"}
        _ts, st = LT._state(conn, "trend")
        since = (st or {}).get("since")
        if since is None:
            _cs, cst = LT._state(conn, "combo")
            since = (cst or {}).get("trend_since")
        if since is None:
            return {"state": "missing", "name": name, "reason_ko": "추세판단 봇이 아직 첫 판단을 기록하지 않았어요 (켠 뒤 1~2분)"}
        since = int(since)
        trades = LR._trades(conn, ACCOUNT, since) if "trades" in tables else []
        sigs = [LR._sig(r) for r in conn.execute(
            "SELECT bar_close, timeframe, strategy, symbol, side, atr, ref_price, status, data FROM signal_log WHERE bar_close >= ? "
            "ORDER BY bar_close, id", (since,)).fetchall()] if "signal_log" in tables else None
        entered, skipped = None, None
        if "outcomes" in tables:
            entered, skipped = [], []
            for step, status in conn.execute("SELECT step_ts, status FROM outcomes WHERE account_id = ? AND step_ts >= ? "
                                             "AND status IN ('ENTERED', 'SKIPPED')", (ACCOUNT, since)).fetchall():
                (entered if status == "ENTERED" else skipped).append(int(step))
        pos_t = None
        _at, acc = LT._state(conn, "accounts")
        p = (((acc or {}).get("engines") or {}).get(ACCOUNT) or {}).get("position") if isinstance(acc, dict) else None
        if isinstance(p, dict) and L._i(p.get("entry_time")) is not None:
            pos_t = int(p["entry_time"])
    except sqlite3.Error as exc:
        return {"state": "error", "reason_ko": "페이퍼 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        conn.close()
    return {"state": "ok", "name": name, "since": since, "run": run or {}, "cfg": cfg, "trades": trades, "sigs": sigs,
            "entered": entered, "skipped": skipped, "pos_t": pos_t}


def _execs(p: dict, since: int, now: int) -> list:
    """Both executors since the start: [{id, name_ko, state, real, mode, rows}] (livebots.sources: their own records and
    the paper trade each close followed)."""
    try:
        _configs, _follows, _paper, execs = L.sources(p, now)
    except (OSError, sqlite3.Error, ValueError) as exc:
        why = f"{type(exc).__name__}: {exc}"[:200]
        return [{"id": ex, "name_ko": ko, "state": "error", "reason_ko": "실행기 기록을 읽지 못했어요", "reason": why, "rows": []}
                for ex, ko, _dk, _ck in L.EXECS]
    out = []
    for x in execs:
        r = x["record"]
        base = {"id": x["id"], "name_ko": x["name_ko"]}
        if r.get("state") != "ok":
            out.append({**base, "state": r.get("state"), "reason_ko": r.get("reason_ko"), "reason": r.get("reason"), "rows": []})
            continue
        pairs = L.pairs_of(x)
        dk = next(d for ex, _ko, d, _ck in L.EXECS if ex == x["id"])
        ok = _cost_ok(p[dk])
        rows = [exec_row(t, pairs.get(str(t["key"])), ok.get(str(t["key"])))
                for t in r.get("trades") or [] if (t.get("entry_ts") or 0) >= since and t.get("pnl") is not None]
        out.append({**base, "state": "ok", "mode": r.get("mode"), "real": r.get("mode") == "mainnet", "rows": rows,
                    "other_paper": not L.LP.same(x["paper_path"], p["paper"]), "notes": x.get("notes") or []})
    return out


def build(p: dict, now_ms: Optional[int] = None, ref_path=None) -> dict:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    p = {**L.paths(), **p}                               # (a caller may name only the paper database)
    pr = _read_paper(p["paper"], now)
    base = {"now_ms": now, "name": pr.get("name")}
    if pr["state"] != "ok":
        return {**base, **{k: pr.get(k) for k in ("state", "reason_ko", "reason")}}
    ref = load_ref(ref_path)
    if ref["state"] != "ok":
        return {**base, "state": ref["state"], "reason_ko": ref["reason_ko"], "reason": ref.get("reason")}
    d, since = ref["d"], pr["since"]
    from . import livetape as T
    slip = T.rules_of({"fees": None}, pr["run"])["slippage"]
    paper = [paper_row(t, slip) for t in pr["trades"]]
    execs = _execs(p, since, now)
    rep = replay_rows(d)
    # 진입 횟수: the entries the paper made (its outcomes; without that table its trades and the open position)
    times = pr["entered"] if pr["entered"] is not None else [r["entry"] for r in paper] + ([pr["pos_t"]] if pr["pos_t"] else [])
    entries = entries_of(d, times, since, now)
    entries["live"]["src"] = "outcomes" if pr["entered"] is not None else "trades"
    # 깔때기
    f = LR.funnel_of(pr["sigs"], pr["entered"] or [], [int(x) for x in pr["skipped"] or []]) if pr["sigs"] is not None else None
    funnel = funnel_view(d, f, len(pr["skipped"]) if pr["skipped"] is not None else None, pr["entered"] is not None,
                         L.trend_waits(pr.get("cfg")))
    # 거래 결과 with the band the replay leaves for each live account's n
    accts = {"replay": rep, "paper": paper, **{x["id"]: x["rows"] for x in execs if x["state"] == "ok"}}
    k_plot = max(len(rep), *(len(v) for v in accts.values()))
    w = walks(tuple(r["roe"] for r in rep), k_plot)
    res_rep = {**record(rep), "small": False}
    res_paper = record(paper)
    res_paper["band"] = mean_band(w, res_paper["n"])
    res_paper["verdict"] = verdict(res_paper["n"], res_paper["roe_mean"], res_paper["band"])
    ex_out = []
    for x in execs:
        head = {k: x.get(k) for k in ("id", "name_ko", "state", "reason_ko", "reason", "mode", "real", "other_paper", "notes")}
        if x["state"] != "ok":
            ex_out.append({**head, "record": None, "costs": None, "costs_ko": live_costs_ko(x)})
            continue
        rec = record(x["rows"])
        rec["band"] = mean_band(w, rec["n"])
        rec["verdict"] = verdict(rec["n"], rec["roe_mean"], rec["band"])
        c = costs_of(x["rows"])
        ex_out.append({**head, "record": rec, "costs": c, "costs_ko": live_costs_ko(c)})
    c_rep, c_paper = replay_costs(d), costs_of(paper)
    tr = d["trades"]
    return {**base, "state": "ok", "since": since,
            "ref": {"what": d["what"], "honest_ko": [*d["honest_ko"], time_note_ko(d, pr.get("cfg")),
                                                     *filter(None, [design_note_ko(d, pr.get("cfg"))])],
                    "window_kst": d["window_kst"], "window_ms": d["window_ms"],
                    "setup": d["setup"], "path": "data/trend_replay_0701_1020.json"},
            "entries": entries, "funnel": funnel,
            "results": {"replay": {**res_rep, "file": {"n": tr.get("n"), "win_rate": tr.get("win_rate"), "roe_mean": tr.get("roe_mean"),
                                                       "roe_median": tr.get("roe_median"), "judge_exits": tr.get("judge_exits")}},
                        "paper": res_paper, "execs": ex_out, "small_n": SMALL_N,
                        "band_how_ko": f"재현 {len(rep)}번의 순ROE에서 같은 수만큼 {WALKS}번 다시 뽑아 본 범위 (5~95%, 고정 씨앗)"},
            "costs": {"ko": costs_ko(c_rep), "replay": c_rep, "paper": c_paper, "paper_ko": live_costs_ko(c_paper),
                      "paper_slip_ko": PAPER_SLIP_KO, "exec_before_ko": EXEC_BEFORE_KO},
            "split": split_of(accts),
            "curve": {"replay": cum_of(rep), "paper": cum_of(paper), "execs": {x["id"]: cum_of(x["rows"]) for x in execs if x["state"] == "ok"},
                      "band": {"lo": [round(v, 6) for v in w["lo"][:k_plot + 1]], "hi": [round(v, 6) for v in w["hi"][:k_plot + 1]]}},
            "small_n": SMALL_N}


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/replayref")
    def get_livebots_replayref():
        """실거래 › 재현 비교: the trend bot's 7/1~10/20 replay against its live record since the start (entries, funnel,
        results, the costs split, by member / coin / side, the cumulative line); read-only, 5 s cache."""
        p = L.paths()
        key = "replayref:" + json.dumps([p, str(REF_PATH)], sort_keys=True)
        return L._cached(key, lambda: json_finite(build(p)))

    return {"routes": ["/api/v4/livebots/replayref"]}
