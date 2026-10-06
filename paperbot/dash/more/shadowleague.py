"""그림자 리그 (#/league): 5년 시험에서 실패했는데도 두 분이 지켜보고 싶은 아이디어를, 실제 봉 위에서 가상 거래로만 따라가는 기록을
보여 줍니다. 참고용, 판정 아님: 331개 모의 계좌가 아니고, 11/04 판정에 들어가지 않고, 다중 검정 보정에 세지 않고, 주문이 없습니다.

    GET /api/v4/shadowleague[?member=<id>]   멤버 카드들 + 고른 멤버 하나의 자세한 기록 (읽기만, 몇 초 캐시)

기록은 에이전트 실행(15분마다, AGENTS_SHADOW_LEAGUE=1일 때만)이 agents3.db 옆의 ``shadow_league.db``에 씁니다. 여기서는 그 파일을 읽기
전용으로만 엽니다(``mode=ro`` + ``query_only``, 짧은 timeout, 한 번 읽는 동안 하나의 시점(BEGIN)으로 읽어서 쓰는 쪽이 중간에 커밋해도 표끼리
어긋나지 않음). 이 모듈은 봇 쪽 코드(paperbot/shadowleague)를 가져오지 않습니다: 표 모양(DDL)만 알고, 그 모양에서 읽습니다.

못 읽은 것을 '없음'으로 보이지 않기 (CONTRACT §1):
  - ``state: "not_started"``  파일이 아직 없거나(스위치가 한 번도 안 켜짐) 멤버 줄이 없음. 켜는 법을 함께 보냅니다.
  - ``state: "error"``        파일은 있는데 읽지 못함(망가짐, 표가 없음, 잠김, 권한, 예상 못 한 모든 오류) + 이유. 0이나 빈 목록으로 바뀌지 않음.
  - ``state: "ok"``           읽었음. 그 안에서도 표 하나가 없으면(옛 모양/새 모양 파일) 그 부분만 ``unavailable`` 이유와 함께 빠지고, 나머지는 보임.
이 화면의 5년 시험 숫자(``studies``)는 커밋된 파일(paperbot/dash/data/league_studies.json)에서 오며, DB가 없거나 못 읽어도 함께 보냅니다.
시간은 UTC 밀리초, 퍼센트는 퍼센트 단위(1.5 = 1.5%), 1배 기준·비용 뒤(gross는 비용 전). 숫자가 있는 덩어리마다 ``label_ko`` = 참고용, 판정 아님.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from typing import Any, Optional

LABEL = "참고용, 판정 아님"
DB_NAME = "shadow_league.db"
ENV_PATH = "PAPERBOT_SHADOW_LEAGUE_DB"         # an explicit file (tests, a data folder that is not next to agents3.db)
STUDY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "league_studies.json")
TTL_S = 5.0
TIMEOUT_S = 2.0
STALE_MS = 3 * 3_600_000          # no tick for this long reads 'off' (the bot's own rule, league.STALE_MS)
DAY_MS = 86_400_000
TFS = ("15m", "30m", "1h", "4h")
SCOPES = TFS + ("all",)
KNOWN_SCHEMA = 2                  # the newest table shape this reader knows (store.SCHEMA_VERSION on the bot side)
MIN_TRADES = 30                   # the same floor as the 30-day verdict's (checkpoint.MIN_TRADES): under it, 표본 적음
LAST_TRADES = 50
LAST_SIGNALS = 50
MAX_POINTS = 600                  # a longer per-trade curve is thinned for the page (the last point is always kept)
START_EQUITY = 5000.0

STATUS_KO = {"off": "꺼짐", "waiting": "시작 전", "warming": "워밍업 중", "recording": "기록 중", "error": "오류",
             "halted": "멈춤(정의가 바뀜)"}
SIDE_KO = {1: "롱", -1: "숏"}
REASON_KO = {"TP": "목표 도달", "SL": "손절", "TIME": "48봉 시간 청산", "EOD": "자료 끝"}
SIGNAL_KO = {"candidate": "후보", "pending_entry": "다음 봉 시가 진입 대기", "taken": "진입함", "busy": "보유 중이라 건너뜀",
             "skip_entry": "시가가 이미 손절·목표 밖이라 건너뜀", "skip_no_target": "목표 구간 없음",
             "skip_stop_far": "손절이 3 ATR보다 멂", "skip_rr": "손익비 2 미만", "not_chosen": "같은 봉의 다른 신호가 우선"}
# tables the page needs; a missing one switches only its own block off (the file is an older or a newer shape)
NEEDED = ("members", "series_state", "signals", "trades", "clones", "account_daily")

# The members this page knows by name: explicit and short (a new idea is one more entry here and its study in the JSON).
KNOWN_MEMBERS = {
    "zoneflip": {
        "name_ko": "영상 매매법 (매물대 지지→저항 전환)",
        "short_ko": "영상 매매법",
        "source_ko": "인스타 릴스 parkdando_",
        "blurb_ko": ("거래량이 쌓인 가격대를 3번 이상 지켜 준 뒤 그 가격대가 깨지고, 되돌아와 다시 막히면 깨진 쪽으로 들어가는 규칙입니다. "
                     "5년 시험에서 실패했고(8칸 중 통과 0), 지금은 같은 규칙을 실제 봉에서 가상 거래로만 지켜봅니다."),
        "study": "zoneflip",
    },
}
SWITCH = {
    "name": "AGENTS_SHADOW_LEAGUE", "value": "1", "file": "/etc/paperbot/agents.env",
    "how_ko": ("켜고 끄는 곳은 이 화면의 버튼이 아니라 서버의 설정 파일입니다. 서버의 /etc/paperbot/agents.env 에 AGENTS_SHADOW_LEAGUE=1 한 줄을 적으면 "
               "다음 15분 차례부터 기록을 시작하고, 0으로 바꾸거나 줄을 지우면 멈춥니다(쌓인 기록은 남습니다). 서버 설정을 바꾸는 쪽에 부탁해 주세요."),
}
OFF_KO = {
    "never": "아직 켜지 않았어요: 기록을 한 번도 시작하지 않았습니다.",
    "stale": "꺼져 있는 것 같아요: 마지막 기록이 오래됐습니다(3시간 넘게 새 기록이 없음).",
}

_lock = threading.Lock()
_cache: dict = {}
_studies: dict = {"key": None, "doc": None}


# ---------------------------------------------------------------- small helpers
def _f(x: Any, nd: Optional[int] = 4) -> Optional[float]:
    """A finite float (rounded), else None."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, nd) if nd is not None else v


def _pc(x: Any, nd: int = 4) -> Optional[float]:
    """A fraction at 1x as percent."""
    v = _f(x, None)
    return None if v is None else round(100.0 * v, nd)


def _i(x: Any) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _mean(xs: list) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def pctl(vals: list, q: float) -> Optional[float]:
    """The q-th percentile (0-100) of a list with linear interpolation (numpy's default), None for an empty list."""
    v = sorted(vals)
    n = len(v)
    if not n:
        return None
    pos = q / 100.0 * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


# ---------------------------------------------------------------- the committed 5-year study numbers
def load_studies(path: str = STUDY_FILE) -> tuple:
    """(studies dict | None, reason | None): the committed 5-year results, re-read when the file changes. A missing, unreadable
    or differently shaped file is a reason, never an empty dict."""
    try:
        st = os.stat(path)
    except OSError:
        return None, "5년 시험 숫자 파일이 없어요"
    key = (path, st.st_mtime_ns, st.st_size)
    with _lock:
        if _studies["key"] == key and _studies["doc"] is not None:
            return _studies["doc"], None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None, "5년 시험 숫자 파일을 읽지 못했어요"
    if not isinstance(doc, dict) or doc.get("version") != 1 or not isinstance(doc.get("studies"), dict):
        return None, "5년 시험 숫자 파일의 모양이 달라요"
    with _lock:
        _studies.update(key=key, doc=doc["studies"])
    return doc["studies"], None


# ---------------------------------------------------------------- opening the file
def default_path(ctx: Any) -> Optional[str]:
    """Where shadow_league.db is: an explicit file (ctx.shadow_league_db, else the PAPERBOT_SHADOW_LEAGUE_DB variable), else
    next to the agents database (the bot's store.default_path), else next to the paper database."""
    p = getattr(ctx, "shadow_league_db", None) or os.environ.get(ENV_PATH)
    if p:
        return str(p)
    for attr in ("agents_db", "db"):
        base = getattr(ctx, attr, None)
        if base:
            return os.path.join(os.path.dirname(os.path.abspath(base)), DB_NAME)
    return None


def stale_wal(path: str) -> bool:
    """A restored copy (rollback-journal header) with an old non-empty -wal next to it: sqlite would read it as damaged."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(20)
        return len(head) == 20 and head[:16] == b"SQLite format 3\x00" and head[18] == 1 and os.path.getsize(path + "-wal") > 0
    except OSError:
        return False


def open_ro(path: str) -> sqlite3.Connection:
    """A read-only connection (autocommit, so the caller opens one BEGIN for a consistent read). FileNotFoundError when the
    file is not there, sqlite3.Error / OSError when it cannot be read."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if stale_wal(path):
        raise sqlite3.DatabaseError("restored database with an old -wal next to it")
    uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=TIMEOUT_S, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def reason_ko(exc: BaseException) -> str:
    """A plain-Korean reason for a read that failed (the raw text goes next to it, for whoever fixes it)."""
    msg = str(exc).lower()
    if isinstance(exc, PermissionError) or "unable to open" in msg:
        return "파일을 열지 못했어요(읽기 권한이나 위치를 확인해야 해요)"
    if "not a database" in msg or "malformed" in msg or "corrupt" in msg or "old -wal" in msg:
        return "기록 파일이 망가졌거나 데이터베이스 파일이 아니에요"
    if "no such table" in msg or "no such column" in msg:
        return "기록 파일에 있어야 할 표가 없어요(만들다 만 파일이거나 모양이 달라요)"
    if "locked" in msg or "busy" in msg:
        return "쓰는 쪽이 잡고 있어서 이번엔 못 읽었어요(잠시 뒤 다시 읽어요)"
    return "읽는 중 문제가 생겼어요"


def _err(path: Optional[str], exc: BaseException) -> dict:
    return {"state": "error", "reason": f"{type(exc).__name__}: {exc}", "reason_ko": reason_ko(exc), "path": path}


def _tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# ---------------------------------------------------------------- statuses, cards
def _status(row: dict, series: Optional[list], now_ms: int) -> tuple:
    """(status, counts, off_why): the bot's rules (view._status): halted > off (never ticked, or no tick for 3 hours) > the
    series' own."""
    count = {"recording": 0, "warming": 0, "waiting": 0, "error": 0}
    for s in series or []:
        count[s["status"]] = count.get(s["status"], 0) + 1
    count["total"] = len(series or [])
    if row.get("halted"):
        return "halted", count, None
    if row.get("activated_ms") is None or row.get("last_tick_ms") is None:
        return "off", count, "never"
    if now_ms - int(row["last_tick_ms"]) > STALE_MS:
        return "off", count, "stale"
    if series is None:                       # the table of the series' states is missing: the status cannot be known
        return "error", count, None
    if count["recording"]:
        return "recording", count, None
    if count["error"] and not count["warming"] and not count["waiting"]:
        return "error", count, None
    if count["warming"] or not series:
        return "warming", count, None
    return "waiting", count, None


def trade_stats(trades: list) -> dict:
    """Open / closed counts and the closed trades' numbers (percent, 1x, after costs; gross = before costs)."""
    closed = [t for t in trades if t.get("status") == "closed"]
    nets = [v for v in (_f(t.get("net"), None) for t in closed) if v is not None]
    gross = [v for v in (_f(t.get("gross_raw"), None) for t in closed) if v is not None]
    n = len(nets)
    return {"open": sum(1 for t in trades if t.get("status") == "open"), "closed": len(closed),
            "wins": sum(1 for v in nets if v > 0), "win_pct": round(100.0 * sum(1 for v in nets if v > 0) / n, 4) if n else None,
            "avg_net_pct": _pc(_mean(nets)) if n else None, "avg_gross_pct": _pc(_mean(gross)) if gross else None,
            "sum_net_pct": _pc(sum(nets)) if n else None, "need": MIN_TRADES, "small": len(closed) < MIN_TRADES}


def _spec(row: dict) -> tuple:
    """(the member's stored definition, readable?)."""
    try:
        spec = json.loads(row.get("spec_json") or "")
        return (spec, True) if isinstance(spec, dict) else ({}, False)
    except (TypeError, ValueError):
        return {}, False


def _account_spec(spec: dict) -> dict:
    a = spec.get("account") if isinstance(spec.get("account"), dict) else {}
    start = _f(a.get("start_equity"), None) or START_EQUITY
    margin = _f(a.get("margin_frac"), None) or 0.2
    lev = _f(a.get("leverage"), None) or 20
    liq = _f(a.get("liq_adverse"), None) or (1 / 20 - 0.005)
    return {"start_equity": start, "margin_frac": margin, "leverage": lev, "exposure": round(margin * lev, 4), "liq_adverse": round(liq, 6)}


def _known(member_id: str) -> dict:
    return KNOWN_MEMBERS.get(member_id) or {}


def _tick_errors(tick: Optional[dict]) -> list:
    """The last tick's problems in plain Korean next to the bot's own words."""
    out = []
    for raw in (tick or {}).get("errors") or []:
        raw = str(raw)
        m = re.search(r"(\d+) clones wait for an entry bar that is no longer stored", raw)
        ko = (f"동전 던지기 {m.group(1)}개가 들어갈 봉이 이미 지워져서 기다리는 중입니다" if m else
              "시세를 받지 못했습니다" if re.search(r"fetch|http|timeout|timed out|klines", raw, re.I) else "실행 중 문제가 있었습니다")
        out.append({"ko": ko, "raw": raw})
    return out


def _card(row: dict, series: Optional[list], trades: Optional[list], sig: Optional[dict], late: Optional[int],
          now_ms: int, missing: list) -> dict:
    mid = row["member_id"]
    status, count, off_why = _status(row, series, now_ms)
    known = _known(mid)
    spec, spec_ok = _spec(row)
    act = row.get("activated_ms")
    start = int(row["start_ms"])
    skipped = pending = total = taken = None
    if sig is not None:
        total = sum(sig.values())
        taken = sig.get("taken", 0)
        skipped = sum(v for k, v in sig.items() if k.startswith("skip_") or k in ("busy", "not_chosen"))
        pending = sig.get("pending_entry", 0) + sig.get("candidate", 0)
    warm = [{"coin": s["coin"], "tf": s["tf"], "have": s.get("warm_have"), "need": s.get("warm_need"), "note": s.get("note")}
            for s in (series or []) if s["status"] == "warming"]
    errs = [{"coin": s["coin"], "tf": s["tf"], "note": s.get("note")} for s in (series or []) if s["status"] == "error"]
    return {
        "member_id": mid, "name_ko": known.get("name_ko") or row.get("name_ko") or mid, "db_name_ko": row.get("name_ko"),
        "short_ko": known.get("short_ko") or row.get("name_ko") or mid, "blurb_ko": known.get("blurb_ko", ""),
        "source_ko": known.get("source_ko", ""), "label_ko": LABEL, "status": status, "status_ko": STATUS_KO[status],
        "off_why": off_why, "off_ko": OFF_KO.get(off_why) if off_why else None, "halted_ko": row.get("halted") or None,
        "started_at_ms": start, "activated_ms": act, "last_tick_ms": row.get("last_tick_ms"),
        "days": round(max(0.0, (now_ms - start) / DAY_MS), 2), "starts_in_days": round((start - now_ms) / DAY_MS, 2) if start > now_ms else 0.0,
        "series": count if series is not None else None, "warming": warm, "errors": errs,
        "signals": ({"total": total, "taken": taken, "skipped": skipped, "pending": pending, "late": late}
                    if sig is not None else None),
        "trades": trade_stats(trades) if trades is not None else None,
        "spec_ok": spec_ok, "tables_missing": missing, "study": spec.get("study") or known.get("study") or None,
    }


# ---------------------------------------------------------------- the curves
def per_trade_curve(trades: list, clones: list) -> dict:
    """The member against its coin-flip clones, one point per trade whose every clone is decided, in exit order: the cumulative
    sum of net percent (1x, after costs) and the 10 / 50 / 90 % of the clone worlds (world k = the k-th clone of every trade).
    Same rules as the bot's view.curves: K = the fewest clones any trade has; a trade waits (``awaiting_clones``) until all of
    its clones are closed."""
    by: dict = {}
    for c in clones:
        by.setdefault(c["trade_id"], []).append(c)
    for v in by.values():
        v.sort(key=lambda x: int(x["k"]))
    kmax = min([len(v) for v in by.values()] or [0])
    closed = [t for t in trades if t.get("status") == "closed"]
    comp = []
    for t in closed:
        cl = by.get(t["trade_id"])
        if not cl or not kmax or _f(t.get("net"), None) is None or _i(t.get("exit_ms")) is None:
            continue
        flips = [_f(x.get("net"), None) for x in cl[:kmax]]
        if any(x.get("status") != "closed" for x in cl[:kmax]) or any(v is None for v in flips):
            continue
        comp.append((int(t["exit_ms"]), str(t["trade_id"]), float(t["net"]) * 100.0, [v * 100.0 for v in flips]))
    comp.sort(key=lambda x: (x[0], x[1]))
    pts = []
    cum_m = 0.0
    cum_f = [0.0] * kmax
    for i, (ms, _tid, net, flips) in enumerate(comp):
        cum_m += net
        cum_f = [a + b for a, b in zip(cum_f, flips)]
        p10, p50, p90 = pctl(cum_f, 10), pctl(cum_f, 50), pctl(cum_f, 90)
        pts.append({"n": i + 1, "ms": ms, "member_cum_pct": round(cum_m, 4), "flip_p10": round(p10, 4), "flip_p50": round(p50, 4),
                    "flip_p90": round(p90, 4), "member_avg_pct": round(cum_m / (i + 1), 4), "flip_avg_p50": round(p50 / (i + 1), 4)})
    position = None
    if pts:
        last = pts[-1]
        position = ("below" if last["member_cum_pct"] < last["flip_p10"] else "above" if last["member_cum_pct"] > last["flip_p90"] else "inside")
    shown = pts
    if len(pts) > MAX_POINTS:                        # thin the line for the page: every k-th point and always the last
        step = int(math.ceil(len(pts) / MAX_POINTS))
        shown = [p for i, p in enumerate(pts) if i % step == 0 or i == len(pts) - 1]
    return {"unit_ko": "거래 1회당 %를 더한 누적(1배, 비용 뒤)", "n": len(comp), "clones_per_trade": kmax,
            "awaiting_clones": len(closed) - len(comp), "points": shown, "thinned": len(shown) != len(pts), "position": position,
            "label_ko": LABEL,
            "note_ko": "동전 던지기 = 같은 코인·봉·방향·손절·목표 거리로 ±5일 안 무작위 봉에 들어간 가상 거래 (거래마다 최대 50개). 가운데 선은 중앙값, 띠는 10~90%."}


def max_drawdown(equities: list, start_equity: float) -> dict:
    """The deepest fall from a peak, over the day-end equity points (the start counts as the first peak): percent, and the
    index (into ``equities``) of the trough; None when it never fell."""
    peak = float(start_equity)
    worst, at = 0.0, None
    for i, e in enumerate(equities):
        peak = max(peak, e)
        dd = (peak - e) / peak if peak > 0 else 0.0
        if dd > worst:
            worst, at = dd, i
    return {"max_dd_pct": round(100.0 * worst, 4), "trough_index": at}


def account_view(rows: list, acct: dict) -> dict:
    """The owners'-style virtual account per scope from the stored day-end rows (the bot recomputes them from the trade rows)."""
    start = acct["start_equity"]
    by: dict = {}
    for r in rows:
        by.setdefault(r["scope"], []).append(r)
    scopes = {}
    for sc in SCOPES:
        rs = sorted(by.get(sc, []), key=lambda r: int(r["day_ms"]))
        pts = [{"day_ms": int(r["day_ms"]), "equity": _f(r["equity"], 2), "ret_pct": _f(r["ret_pct"], 4),
                "taken": _i(r["taken"]), "liquidated": _i(r["liquidated"])} for r in rs]
        eq = [float(r["equity"]) for r in rs if _f(r["equity"], None) is not None]
        if not rs or not eq:
            scopes[sc] = {"points": [], "asof_ms": None, "start_equity": start, "last": None, "label_ko": LABEL}
            continue
        dd = max_drawdown(eq, start)
        last = pts[-1]
        scopes[sc] = {"points": pts, "asof_ms": _i(rs[-1]["asof_ms"]), "start_equity": start, "label_ko": LABEL,
                      "last": {"equity": last["equity"], "x": round(eq[-1] / start, 4), "ret_pct": last["ret_pct"],
                               "taken": last["taken"], "liquidated": last["liquidated"], "max_dd_pct": dd["max_dd_pct"],
                               "trough_day_ms": pts[dd["trough_index"]]["day_ms"] if dd["trough_index"] is not None else None}}
    return {"scopes": scopes, "start_equity": start, "margin_frac": acct["margin_frac"], "leverage": acct["leverage"],
            "exposure": acct["exposure"], "liq_adverse": acct["liq_adverse"], "label_ko": LABEL}


# ---------------------------------------------------------------- the member's detail
def _trade_row(t: dict, act: Optional[int]) -> dict:
    side = 1 if _f(t.get("side"), None) and float(t["side"]) > 0 else -1
    reason = t.get("reason")
    acct = {"taken": bool(t["acct_taken"]) if t.get("acct_taken") is not None else None, "ret_pct": _pc(t.get("acct_ret")),
            "equity": _f(t.get("acct_equity"), 2), "liquidated": bool(t["acct_liq"]) if t.get("acct_liq") is not None else None}
    return {"trade_id": t["trade_id"], "coin": t["coin"], "tf": t["tf"], "side": side, "side_ko": SIDE_KO[side], "status": t["status"],
            "signal_ms": t.get("signal_ms"), "entry_ms": t.get("entry_ms"), "entry_px": _f(t.get("entry_px"), 8), "stop_px": _f(t.get("stop_px"), 8),
            "target_px": _f(t.get("target_px"), 8), "exit_ms": t.get("exit_ms"), "exit_px": _f(t.get("exit_px"), 8), "reason": reason,
            "reason_ko": REASON_KO.get(reason, reason) if reason else None, "hold_bars": t.get("hold"), "gross_pct": _pc(t.get("gross_raw")),
            "net_pct": _pc(t.get("net")), "stop_dist_pct": _pc(t.get("sl_dist")), "target_dist_pct": _pc(t.get("tp_dist")), "account": acct,
            "recorded_ms": t.get("recorded_ms"),
            "late": bool(act is not None and _i(t.get("signal_ms")) is not None and int(t["signal_ms"]) < int(act)), "label_ko": LABEL}


def _group_row(key: dict, ts: list, sg: dict) -> dict:
    st = trade_stats(ts)
    return {**key, "signals": sum(sg.values()), "taken": sg.get("taken", 0), "open": st["open"], "closed": st["closed"], "wins": st["wins"],
            "avg_net_pct": st["avg_net_pct"], "sum_net_pct": st["sum_net_pct"]}


def table_views(series: Optional[list], trades: Optional[list], sigs: Optional[list], coins: tuple, tfs: tuple) -> dict:
    """Every coin x timeframe of the member (coin-major), plus the totals per coin and per timeframe. A cell without a stored
    series says 'waiting' (nothing has run there yet), never a zero that looks recorded."""
    smap = {(s["coin"], s["tf"]): s for s in (series or [])}
    sg: dict = {}
    for r in sigs or []:
        sg.setdefault((r["coin"], r["tf"]), {})[r["status"]] = r["n"]
    tr: dict = {}
    for t in trades or []:
        tr.setdefault((t["coin"], t["tf"]), []).append(t)
    cells = []
    for coin in coins:
        for tf in tfs:
            s = smap.get((coin, tf))
            ts, g = tr.get((coin, tf), []), sg.get((coin, tf), {})
            st = s["status"] if s else "waiting"
            cells.append({**_group_row({"coin": coin, "tf": tf}, ts, g), "status": st, "status_ko": STATUS_KO.get(st, st),
                          "stored": s is not None, "note": s.get("note") if s else None, "last_bar_ms": s.get("last_bar_ms") if s else None,
                          "warm_have": s.get("warm_have") if s else 0, "warm_need": s.get("warm_need") if s else 0})
    by_coin = [_group_row({"coin": c}, [t for t in (trades or []) if t["coin"] == c],
                          _merge([v for (cc, _tf), v in sg.items() if cc == c])) for c in coins]
    by_tf = [_group_row({"tf": tf}, [t for t in (trades or []) if t["tf"] == tf],
                        _merge([v for (_c, ff), v in sg.items() if ff == tf])) for tf in tfs]
    return {"cells": cells, "by_coin": by_coin, "by_tf": by_tf}


def _merge(dicts: list) -> dict:
    out: dict = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def comparison(trades: list, study: Optional[dict]) -> list:
    """Per timeframe: the live record next to the 5-year study's three periods (参考, 판정 아님)."""
    out = []
    for tf in TFS:
        st = trade_stats([t for t in trades if t["tf"] == tf])
        live = {"trades": st["closed"], "win_pct": st["win_pct"], "net_pct": st["avg_net_pct"], "gross_pct": st["avg_gross_pct"]}
        out.append({"tf": tf, "live": live, "study": (study or {}).get("main", {}).get(tf), "study_p12": (study or {}).get("p12", {}).get(tf),
                    "study_vs_flip": (study or {}).get("vs_flip", {}).get(tf), "label_ko": LABEL})
    return out


def _grid(spec: dict, series: Optional[list]) -> tuple:
    """(coins, timeframes) of the member: its stored definition, else what its series say."""
    seen = series or []
    coins = [str(c) for c in spec["coins"]] if isinstance(spec.get("coins"), list) and spec["coins"] else sorted({s["coin"] for s in seen})
    tfs = ([str(t) for t in spec["tfs"]] if isinstance(spec.get("tfs"), list) and spec["tfs"] else
           sorted({s["tf"] for s in seen}, key=lambda t: (TFS.index(t) if t in TFS else len(TFS), t)))
    return tuple(coins), tuple(tfs)


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list:
    return [dict(r) for r in conn.execute(sql, args)]


def member_detail(conn: sqlite3.Connection, row: dict, tables: set, now_ms: int, studies: Optional[dict]) -> dict:
    """The card and everything under it for one member. A missing table switches its block off with the reason."""
    mid = row["member_id"]
    spec, spec_ok = _spec(row)
    act = row.get("activated_ms")
    series = _rows(conn, "SELECT * FROM series_state WHERE member_id = ? ORDER BY coin, tf", (mid,)) if "series_state" in tables else None
    trades = _rows(conn, "SELECT * FROM trades WHERE member_id = ?", (mid,)) if "trades" in tables else None
    sig_counts = ({r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM signals WHERE member_id = ? GROUP BY status", (mid,))} if "signals" in tables else None)
    late = (conn.execute("SELECT COUNT(*) FROM signals WHERE member_id = ? AND bar_ms < ?", (mid, act)).fetchone()[0]
            if "signals" in tables and act is not None else (0 if "signals" in tables else None))
    missing = [t for t in NEEDED if t not in tables]
    card = _card(row, series, trades, sig_counts, late, now_ms, missing)
    acct = _account_spec(spec)
    coins, tfs = _grid(spec, series)
    study = (studies or {}).get(card["study"]) if card["study"] else None

    def off(table: str) -> dict:
        return {"state": "unavailable", "reason_ko": f"기록 파일에 '{table}' 표가 없어서 이 부분은 아직 보여 줄 수 없어요", "table": table}

    out: dict = {"state": "ok", "label_ko": LABEL, "as_of_ms": now_ms, "card": card, "account_spec": acct, "spec_ok": spec_ok}
    if trades is not None and "clones" in tables:
        clones = _rows(conn, "SELECT trade_id, k, status, net FROM clones WHERE member_id = ? ORDER BY trade_id, k", (mid,))
        out["per_trade"] = {"state": "ok", **per_trade_curve(trades, clones)}
    else:
        out["per_trade"] = off("clones" if trades is not None else "trades")
    out["account"] = ({"state": "ok", **account_view(_rows(conn, "SELECT scope, day_ms, equity, ret_pct, taken, liquidated, asof_ms FROM account_daily "
                                                                 "WHERE member_id = ? ORDER BY scope, day_ms", (mid,)), acct)}
                      if "account_daily" in tables else off("account_daily"))
    if trades is not None and series is not None:
        sigs = (_rows(conn, "SELECT coin, tf, status, COUNT(*) AS n FROM signals WHERE member_id = ? GROUP BY coin, tf, status", (mid,))
                if "signals" in tables else [])
        out["table"] = {"state": "ok", **table_views(series, trades, sigs, coins, tfs)}
    else:
        out["table"] = off("trades" if trades is None else "series_state")
    if trades is not None:
        last = sorted(trades, key=lambda t: (_i(t.get("entry_ms")) or 0, str(t["trade_id"])), reverse=True)[:LAST_TRADES]
        out["trades"] = {"state": "ok", "rows": [_trade_row(t, act) for t in last], "total": len(trades)}
        out["comparison"] = {"state": "ok", "rows": comparison(trades, study)}
    else:
        out["trades"] = out["comparison"] = off("trades")
    if "signals" in tables:
        sg = _rows(conn, "SELECT signal_id, coin, tf, side, bar_ms, plan_entry, stop, target, rr, touches, status FROM signals "
                         "WHERE member_id = ? ORDER BY bar_ms DESC, signal_id LIMIT ?", (mid, LAST_SIGNALS))
        out["signals"] = {"state": "ok", "rows": [{
            "signal_id": s["signal_id"], "coin": s["coin"], "tf": s["tf"], "side": 1 if float(s["side"]) > 0 else -1,
            "side_ko": SIDE_KO[1 if float(s["side"]) > 0 else -1], "bar_ms": s["bar_ms"], "plan_entry": _f(s["plan_entry"], 8),
            "stop": _f(s["stop"], 8), "target": _f(s["target"], 8), "rr": _f(s["rr"], 2), "touches": s["touches"], "status": s["status"],
            "status_ko": SIGNAL_KO.get(s["status"], s["status"])} for s in sg]}
    else:
        out["signals"] = off("signals")
    out["study"] = study
    out["study_key"] = card["study"]
    return out


# ---------------------------------------------------------------- the whole answer
def build(path: Optional[str], member_id: Optional[str] = None, now_ms: Optional[int] = None, studies_path: str = STUDY_FILE) -> dict:
    """The page's one answer: the state, the 5-year numbers (always), and, when the file is readable, every member's card and the
    chosen member's detail. Never raises: whatever goes wrong while reading is an error state with its reason."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    studies, study_why = load_studies(studies_path)
    base: dict = {"label_ko": LABEL, "now_ms": now, "path": path, "known": [{"member_id": k, **v} for k, v in KNOWN_MEMBERS.items()],
                  "studies": studies, "studies_state": "ok" if studies is not None else "error", "studies_reason_ko": study_why,
                  "switch": SWITCH, "min_trades": MIN_TRADES}
    if not path:
        return {**base, "state": "not_started", "reason": "no_path", "reason_ko": "기록 파일이 있을 곳을 알 수 없어요(서버 설정에 데이터베이스 위치가 없음)"}
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return {**base, "state": "not_started", "reason": "file_missing",
                "reason_ko": "기록 파일이 아직 없어요: 그림자 리그를 한 번도 켠 적이 없습니다."}
    except (sqlite3.Error, OSError) as exc:
        return {**base, **_err(path, exc)}
    try:
        conn.execute("BEGIN")                                    # one snapshot for every query below (the writer may commit meanwhile)
        tables = _tables(conn)
        if "members" not in tables:
            return {**base, "state": "error", "reason": "OperationalError: no such table: members",
                    "reason_ko": reason_ko(sqlite3.OperationalError("no such table")), "path": path}
        rows = _rows(conn, "SELECT * FROM members ORDER BY member_id")
        if not rows:
            return {**base, "state": "not_started", "reason": "no_member", "reason_ko": "기록 파일은 있지만 멤버가 아직 한 명도 없어요."}
        meta = {r["k"]: r["v"] for r in conn.execute("SELECT k, v FROM league_meta")} if "league_meta" in tables else {}
        tick = None
        try:
            tick = json.loads(meta["last_tick"]) if meta.get("last_tick") else None
        except (TypeError, ValueError):
            tick = None
        sv = _i(meta.get("schema_version"))
        picked = next((r for r in rows if r["member_id"] == member_id), None) if member_id else None
        chosen = picked or rows[0]
        cards, detail = [], None
        for r in rows:
            if r is chosen:
                try:
                    detail = member_detail(conn, r, tables, now, studies)
                    cards.append(detail["card"])
                except Exception as exc:  # noqa: BLE001  (one member's failure is its own error, never an empty card)
                    detail = {"state": "error", "reason": f"{type(exc).__name__}: {exc}", "reason_ko": reason_ko(exc)}
                    cards.append({"member_id": r["member_id"], "name_ko": _known(r["member_id"]).get("name_ko") or r["name_ko"], "state": "error"})
            else:
                try:
                    cards.append(_light_card(conn, r, tables, now))
                except Exception as exc:  # noqa: BLE001
                    cards.append({"member_id": r["member_id"], "name_ko": _known(r["member_id"]).get("name_ko") or r["name_ko"], "state": "error",
                                  "reason": f"{type(exc).__name__}: {exc}"})
        notes = []
        if sv is not None and sv > KNOWN_SCHEMA:
            notes.append(f"기록 파일이 이 화면보다 새 모양(버전 {sv})이에요. 아는 칸만 보여 줍니다.")
        if sv is not None and sv < KNOWN_SCHEMA:
            notes.append(f"기록 파일이 옛 모양(버전 {sv})이에요. 없는 표는 그 부분만 빠집니다(에이전트가 다음 실행에서 새 모양으로 올립니다).")
        if sv is None:
            notes.append("기록 파일에 모양 버전이 적혀 있지 않아요.")
        return {**base, "state": "ok", "as_of_ms": now, "schema_version": sv, "notes_ko": notes, "tables_missing": [t for t in NEEDED if t not in tables],
                "last_tick": ({**tick, "errors_ko": _tick_errors(tick)} if isinstance(tick, dict) else None), "members": cards,
                "selected": chosen["member_id"], "requested_missing": bool(member_id and not picked), "member": detail}
    except Exception as exc:  # noqa: BLE001  (anything unexpected is an error with its reason, never an empty success)
        return {**base, **_err(path, exc)}
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def _light_card(conn: sqlite3.Connection, row: dict, tables: set, now: int) -> dict:
    """A member's card without the detail (the members that are not the chosen one)."""
    mid, act = row["member_id"], row.get("activated_ms")
    series = _rows(conn, "SELECT * FROM series_state WHERE member_id = ?", (mid,)) if "series_state" in tables else None
    trades = _rows(conn, "SELECT status, net, gross_raw FROM trades WHERE member_id = ?", (mid,)) if "trades" in tables else None
    sig = ({r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM signals WHERE member_id = ? GROUP BY status", (mid,))}
           if "signals" in tables else None)
    late = (conn.execute("SELECT COUNT(*) FROM signals WHERE member_id = ? AND bar_ms < ?", (mid, act)).fetchone()[0]
            if "signals" in tables and act is not None else (0 if "signals" in tables else None))
    return _card(row, series, trades, sig, late, now, [t for t in NEEDED if t not in tables])


# ---------------------------------------------------------------- the route
def register(app, ctx) -> dict:
    path = default_path(ctx)

    @app.get("/api/v4/shadowleague")
    def get_shadowleague(member: Optional[str] = None):
        """그림자 리그: the members' cards and the chosen member's record (read-only, a few seconds' cache, honest states)."""
        from ..app import json_finite
        mid = member if member and len(member) <= 64 else None
        now = time.time()
        with _lock:
            hit = _cache.get(mid)
        if hit and now - hit[0] < TTL_S:
            return hit[1]
        out = json_finite(build(path, mid))
        with _lock:
            _cache[mid] = (now, out)
            if len(_cache) > 16:                                 # the cache is keyed by what a caller asked for: keep it small
                for k in sorted(_cache, key=lambda k: _cache[k][0])[:-8]:
                    _cache.pop(k, None)
        return out

    return {"routes": ["/api/v4/shadowleague"], "path": path}
