"""실거래 › 그림자, the 추세판단 봇's shadows (owners 10/21: rule variants side by side, at no money cost, so the 2-week
review decides with numbers; docs/trend-bot-ko.md "그림자 비교 봇"). Read-only, part of GET /api/v4/livebots/shadows
(``trend``).

Each shadow is deploy/combo.trend.json with ONE change, its own database (/var/lib/paperbot/combo/shadow-<id>.db, the same
store3 shape, account COMBO@mix), no Telegram, run by paperbot-combo-shadow@<id> (deploy/paperbot-combo-shadow@.service):
    trend-wait   trend.pullback_wait true   되돌림 기다림 (owners 10-22: the live bot enters at once since its new design)
The 10/21 design's three (trend-time, trend-now, trend-vote4: its old members) are the old bots' shadows now
(livebots.SHADOWS, folded): their configs left the repository with the new design.

A shadow starts fresh with its own $1,000 wallet when it is first turned on, the live paper's wallet carries over from the
bots before it: they are compared by trade, never by dollars. Each shadow counts from its own start (its first start on
its database: state ``combo`` trend_since, like livebots.trend_bot), and the live paper next to it counts from that same
moment (or the live trend bot's own start when that is later): closed trades, win rate, mean and summed net ROE, entries per
KST weekday, the exit-reason mix, the deepest fall of the summed net ROE, the summed net ROE line. Under ``SMALL_N`` closed
trades on either side: 표본 적음 · 아직 판단 못 함.

What a shadow really runs is checked from its own start record (state ``combo_run`` config) against the live bot's: the keys
that differ are listed (``cfg_diff``), so a shadow left behind by a later change of the live config says so.

Not there yet: no database = 아직 안 켬 with the one command that starts it; a database without records = 첫 기록 전; the
systemd unit's state (livecheck.unit_state, '' when systemctl cannot be asked) tells 켜는 중 and 꺼져 있음 apart. Never a
zero for what was not read."""
from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
from typing import Callable, Optional

from . import livebots as L

UNIT = "paperbot-combo-shadow@{id}"
START_KO = "sudo systemctl start paperbot-combo-shadow@{id}"
STOP_KO = "sudo systemctl stop paperbot-combo-shadow@{id}"
SMALL_N = 20                              # under 20 closed trades (either side): no conclusion yet
SMALL_KO = "표본 적음 · 아직 판단 못 함"
MIN_WEEKDAY_DAYS = 0.5                    # entries a weekday only once half a KST weekday has gone by
WAIT_KO = "켜면 약 2분 기다렸다가 돌기 시작해요 (바이낸스 요청은 실거래 봇이 먼저, 여럿이면 2분씩 하나씩 차례로)"
NOT_TREND_KO = "실거래 페이퍼가 지금 추세판단 봇이 아니라 견줄 수 없어요"
# (id, database file, name, the one config key, its value, the one difference, the live bot's way) in the owners' words
TREND_SHADOWS = (
    {"id": "trend-wait", "file": "shadow-trend-wait.db", "name_ko": "되돌림 기다림", "key": "trend.pullback_wait",
     "value": True,
     "diff_ko": "검사를 통과한 신호에서 진입 봉 하나 동안 0.25 ATR 되돌림을 기다렸다가 진입(장대봉이면 0.5 ATR), 안 오면 버림",
     "live_ko": "실거래 봇은 검사를 통과한 신호에 그 분에 바로 진입 (10/22 새 설계)"},
)
SKIP_KEYS = ("db", "name", "telegram", "paper_db")       # what every shadow sets itself (deploy/paperbot-combo-shadow@.service)
# the VWAP 개선판's own (owners 10-26 "둘 다 해줘": research/opentime REPORT_KO.md, its A3 passed only through the light)
VWAP_SHADOWS = (
    {"id": "vwap-4h", "file": "shadow-vwap-4h.db", "name_ko": "4시간 정리", "key": "unlocked_close_min", "value": 240,
     "diff_ko": "진입 4시간 안에 첫 잠금(순ROE +10%)에 못 닿으면 그 분 시가에 시장가로 닫음",
     "live_ko": "실거래 VWAP 봇은 손절 · 계단 익절 · 보유 한도(30분봉 48시간 · 1시간봉 96시간)로만 닫음"},
)
HOLD_KO = "보유 한도 청산"                 # paperbot/combo.TIME_HOLD_KO, the VWAP bot's word for TIME
NOT_VWAP_KO = "VWAP 개선판 페이퍼 기록이 아직 없어 견줄 수 없어요"
NO_LIGHT_KO = "VWAP 봇을 따라가는 실행기에 신호등이 없어 모든 거래를 따라간다고 셌어요"


def weekday_days(a: int, b: int) -> float:
    """KST weekdays (Monday to Friday) between ms a and b, in days (a partial day counts its part)."""
    if b <= a:
        return 0.0
    n, day = 0, L.kst_day(a)
    while True:
        d0 = L.kst_day_start(day)
        if d0 >= b:
            break
        if (day + 3) % 7 < 5:                     # kst_day 0 = 1970-01-01, a Thursday (3)
            n += max(0, min(b, d0 + L.DAY) - max(a, d0))
        day += 1
    return n / L.DAY


def record(trades: list, start: int, now: int, position: Optional[dict] = None, words: Optional[dict] = None) -> dict:
    """One side of the comparison over [start, now]: the closed trades entered at or after ``start`` (oldest first),
    by trade and net ROE (each wallet is its own), the entries per KST weekday (the open position counts as an entry);
    ``words``: exit reasons said otherwise for this bot (the VWAP 개선판's TIME is its hold limit)."""
    ts = [t for t in trades if (L._i(t.get("entry_time")) or 0) >= int(start)]
    n = len(ts)
    wins = sum(1 for t in ts if (L._f(t.get("pnl")) or 0) > 0)
    roes = [L._f(t.get("roe")) for t in ts]
    known = [r for r in roes if r is not None]
    cum = peak = dd = 0.0
    curve = [[int(start), 0.0]] if known else []
    for t, r in zip(ts, roes):
        if r is None:
            continue
        cum += r
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
        curve.append([L._i(t.get("exit_time")), cum])
    exits: dict = {}
    for t in ts:
        k = t.get("exit_reason") or "OTHER"
        exits[k] = exits.get(k, 0) + 1
    opened = bool(position) and (L._i(position.get("entry_time")) or 0) >= int(start)
    entries = n + (1 if opened else 0)
    wd = weekday_days(int(start), int(now))
    return {"trades": n, "wins": wins, "win_rate": wins / n if n else None,
            "roe_n": len(known), "roe_mean": sum(known) / len(known) if known else None, "roe_sum": sum(known) if known else None,
            "max_dd_roe": dd if known else None, "entries": entries, "open": opened, "weekday_days": wd,
            "per_weekday": entries / wd if wd >= MIN_WEEKDAY_DAYS else None,
            "exits": [{"reason": k, "reason_ko": (words or {}).get(k) or L.EXIT_KO.get(k, k), "n": v}
                      for k, v in sorted(exits.items(), key=lambda kv: (-kv[1], kv[0]))],
            "curve": L.thin(curve)}


def _flat(cfg: dict) -> dict:
    """A start record's config as {key: value} (trend.* with the TrendRules defaults filled in), json-normalised."""
    from ...trendjudge import TrendRules
    out = {k: json.dumps(v, sort_keys=True, default=str) for k, v in cfg.items() if k not in SKIP_KEYS and k != "trend"}
    own = cfg.get("trend") if isinstance(cfg.get("trend"), dict) else {}
    tr = {**json.loads(json.dumps(dataclasses.asdict(TrendRules()), default=str)), **own}
    out.update({f"trend.{k}": json.dumps(v, sort_keys=True, default=str) for k, v in tr.items()})
    return out


def cfg_diff(main_cfg: Optional[dict], shadow_cfg: Optional[dict], trend: bool = True) -> Optional[list]:
    """The keys where the shadow's start record differs from the live bot's ([{key, main, shadow}]), None when either
    is unreadable (``trend``: a trend bot's shadow, which must carry its trend rules)."""
    if not isinstance(main_cfg, dict) or not isinstance(shadow_cfg, dict) or (trend and not isinstance(shadow_cfg.get("trend"), dict)):
        return None
    a, b = _flat(main_cfg), _flat(shadow_cfg)
    return [{"key": k, "main": json.loads(a[k]) if k in a else None, "shadow": json.loads(b[k]) if k in b else None}
            for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]


def _cfg_of(path: str) -> Optional[dict]:
    """The config of a database's start record (state ``combo_run``), None when unreadable."""
    try:
        conn = L.open_ro(path)
    except (OSError, sqlite3.Error):
        return None
    try:
        if "state" not in L._tables(conn):
            return None
        row = conn.execute("SELECT data FROM state WHERE k = 'combo_run'").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    cfg = L._j(row[0]).get("config") if row else None
    return cfg if isinstance(cfg, dict) else None


def _unit_word(active: str) -> Optional[bool]:
    """True running (or in its 2-minute start wait), False stopped, None when systemd could not be asked."""
    if active in ("active", "activating", "reloading"):
        return True
    if active in ("inactive", "failed", "deactivating"):
        return False
    return None


def trend_shadows(p: dict, now: int, shadow_dir: str, units: Optional[Callable] = None) -> dict:
    """The ``trend`` part of /api/v4/livebots/shadows: the live trend bot and its shadows, each from its own start."""
    if units is None:
        from ... import livecheck as LC
        units = LC.unit_state
    tb = L.trend_bot(p["paper"])
    main = L.read_paper(p["paper"], [L.ACCOUNT], now)
    ma = (main.get("accounts") or {}).get(L.ACCOUNT) if main.get("state") == "ok" else None
    since = tb["since"] if tb else None
    rows = []
    for spec in TREND_SHADOWS:
        sid = spec["id"]
        path = os.path.join(shadow_dir, spec["file"])
        try:
            active = (units(UNIT.format(id=sid) + ".service") or ("", ""))[0] or ""
        except Exception:  # noqa: BLE001  systemd not reachable: unknown, never "off"
            active = ""
        run = _unit_word(active)
        row = {k: spec[k] for k in ("id", "name_ko", "key", "value", "diff_ko", "live_ko")}
        row.update(unit=UNIT.format(id=sid), start_ko=START_KO.format(id=sid), stop_ko=STOP_KO.format(id=sid), path=path,
                   running=run, unit_state=active or None)
        sh = L.read_paper(path, [L.ACCOUNT], now)
        sa = (sh.get("accounts") or {}).get(L.ACCOUNT) if sh.get("state") == "ok" else None
        if sh.get("state") == "error":
            row.update(state="error", state_ko="그림자 기록을 못 읽음", reason_ko=sh.get("reason_ko"), reason=sh.get("reason"))
        elif not (sa and sa.get("known")):
            exists = os.path.exists(path)
            if run:
                row.update(state="starting", state_ko="켜는 중 · 첫 기록 전 (켠 뒤 약 2분이면 돌기 시작해요)")
            elif not exists:
                row.update(state="off", state_ko="아직 안 켬")
            else:
                row.update(state="empty", state_ko="기록 파일은 있지만 아직 첫 기록 전 (켰다면 약 2분 뒤 생겨요)")
        else:
            stb = L.trend_bot(path)
            start = (stb or {}).get("since") or sa.get("since_ms") or sh.get("started_ms") or 0
            frm = max(int(start), int(since or 0))
            mine = record(sa.get("trades") or [], frm, now, sa.get("position"))
            other = record((ma or {}).get("trades") or [], frm, now, (ma or {}).get("position")) if (tb and ma) else None
            diff = cfg_diff((tb or {}).get("config"), _cfg_of(path))
            small = mine["trades"] < SMALL_N or other is None or other["trades"] < SMALL_N
            row.update(state="ok", state_ko="꺼져 있음 (기록은 꺼지기 전까지)" if run is False else "도는 중" if run else None,
                       since_ms=int(start), from_ms=frm, as_of_ms=sh.get("as_of_ms"), stale=sh.get("stale"),
                       name_cfg=sh.get("name_ko"), wallet=sa.get("wallet"), shadow=mine, main=other,
                       main_ko=None if other is not None else (NOT_TREND_KO if not tb else (main.get("reason_ko") or "실거래 페이퍼 기록을 못 읽음")),
                       small=small, small_ko=SMALL_KO if small else None, cfg_diff=diff,
                       cfg_ok=None if diff is None else [d["key"] for d in diff] == [spec["key"]],
                       position=bool(sa.get("position")))
        rows.append(row)
    off = [r["id"] for r in rows if r["state"] in ("off", "empty") or (r["state"] == "ok" and r["running"] is False)]
    return {"on": tb is not None, "name": tb["name"] if tb else None, "since": since,
            "review_ms": tb["freeze_until"] if tb else None, "main": {k: main.get(k) for k in ("state", "reason_ko", "as_of_ms", "stale")},
            "main_ko": None if tb else NOT_TREND_KO, "small_n": SMALL_N, "small_ko": SMALL_KO, "wait_ko": WAIT_KO,
            "shadows": rows,
            "start_all_ko": ("sudo systemctl start " + " ".join(UNIT.format(id=i) for i in off)) if off else None}


# ---------------------------------------------------------------- VWAP 개선판's shadows
def lit(trades: list, n: int, min_win: Optional[float]) -> list:
    """The paper trades an executor with the signal light (``n`` trades, ``min_win``) follows on this paper's own
    sequence: the light green or still building when each was entered (livegoalres.light_item's rule; n <= 0: all)."""
    closed = sorted([t for t in trades if t.get("exit_time") is not None and t.get("pnl") is not None],
                    key=lambda t: (t["exit_time"], t.get("id") or 0))
    out = []
    for t in trades:
        if t.get("entry_time") is None:
            continue
        prior = [c["pnl"] for c in closed if c["exit_time"] < t["entry_time"]][::-1]
        if L.light(n, min_win, prior)["state"] in ("green", "building", "off"):
            out.append(t)
    return out


def vwap_shadows(p: dict, now: int, shadow_dir: str, units: Optional[Callable] = None) -> dict:
    """The ``vwap`` part of /api/v4/livebots/shadows: the VWAP 개선판 paper and its shadows from each shadow's own start,
    every paper trade (``shadow`` / ``main``) and the trades its executor's signal light would have followed on each
    side's own sequence (``shadow_lit`` / ``main_lit``: the research's A3 helped only there, REPORT_KO.md)."""
    from ... import livepapers as LP
    from .livevwap import is_vwap
    if units is None:
        from ... import livecheck as LC
        units = LC.unit_state
    path0 = p.get("paper2")                                  # the second paper bot's file (livebots.paths), when it is VWAP
    read = L.read_paper(path0, [L.ACCOUNT], now) if path0 and os.path.exists(path0) else None
    on = bool(read) and read.get("state") == "ok" and is_vwap(read.get("_cfg"))
    ma = (read.get("accounts") or {}).get(L.ACCOUNT) if on else None
    lx = None                                                # the first executor that follows it with a signal light
    for _ex, ko, _dk, ck in (L.installed(p) if on else ()):
        c = L.read_config(p[ck]) if p.get(ck) else {}
        if c.get("state") == "ok" and LP.same(c.get("paper_db"), path0) and (L._i(c.get("signal_light_n")) or 0) > 0:
            lx = {"name_ko": ko, "config": c}
            break
    n = L._i((lx or {}).get("config", {}).get("signal_light_n")) or 0
    mw = L._f((lx or {}).get("config", {}).get("signal_light_min_win"))
    share = L.light(n, mw, [])["min_win"] if n else None
    light = {"n": n, "min_win": share, "exec_ko": lx["name_ko"] if lx else None,
             "ko": f"{lx['name_ko']} 신호등: 최근 {n}번 중 {round(share * 100)}% 넘게 이겼을 때만 따라감" if lx else NO_LIGHT_KO}
    main_cfg = _cfg_of(path0) if on else None
    rows = []
    for spec in VWAP_SHADOWS:
        sid = spec["id"]
        path = os.path.join(shadow_dir, spec["file"])
        try:
            active = (units(UNIT.format(id=sid) + ".service") or ("", ""))[0] or ""
        except Exception:  # noqa: BLE001  systemd not reachable: unknown, never "off"
            active = ""
        run = _unit_word(active)
        row = {k: spec[k] for k in ("id", "name_ko", "key", "value", "diff_ko", "live_ko")}
        row.update(unit=UNIT.format(id=sid), start_ko=START_KO.format(id=sid), stop_ko=STOP_KO.format(id=sid), path=path,
                   running=run, unit_state=active or None)
        sh = L.read_paper(path, [L.ACCOUNT], now)
        sa = (sh.get("accounts") or {}).get(L.ACCOUNT) if sh.get("state") == "ok" else None
        if sh.get("state") == "error":
            row.update(state="error", state_ko="그림자 기록을 못 읽음", reason_ko=sh.get("reason_ko"), reason=sh.get("reason"))
        elif not (sa and sa.get("known")):
            if run:
                row.update(state="starting", state_ko="켜는 중 · 첫 기록 전 (켠 뒤 약 2분이면 돌기 시작해요)")
            elif not os.path.exists(path):
                row.update(state="off", state_ko="아직 안 켬")
            else:
                row.update(state="empty", state_ko="기록 파일은 있지만 아직 첫 기록 전 (켰다면 약 2분 뒤 생겨요)")
        else:
            start = sa.get("since_ms") or sh.get("started_ms") or 0
            frm = max(int(start), int((ma or {}).get("since_ms") or 0))
            st_all, mt_all = sa.get("trades") or [], (ma or {}).get("trades") or []
            hold = {"TIME": HOLD_KO}                    # no trend supervisor: TIME is the hold limit (combo.exit_ko)
            mine = record(st_all, frm, now, sa.get("position"), hold)
            other = record(mt_all, frm, now, (ma or {}).get("position"), hold) if ma else None
            mine_lit = record(lit(st_all, n, mw), frm, now, words=hold)
            other_lit = record(lit(mt_all, n, mw), frm, now, words=hold) if ma else None
            diff = cfg_diff(main_cfg, _cfg_of(path), trend=False)
            small = mine["trades"] < SMALL_N or other is None or other["trades"] < SMALL_N
            row.update(state="ok", state_ko="꺼져 있음 (기록은 꺼지기 전까지)" if run is False else "도는 중" if run else None,
                       since_ms=int(start), from_ms=frm, as_of_ms=sh.get("as_of_ms"), stale=sh.get("stale"),
                       name_cfg=sh.get("name_ko"), wallet=sa.get("wallet"), shadow=mine, main=other,
                       shadow_lit=mine_lit, main_lit=other_lit,
                       main_ko=None if other is not None else (NOT_VWAP_KO if not on else (read.get("reason_ko") or "VWAP 페이퍼 기록을 못 읽음")),
                       small=small, small_ko=SMALL_KO if small else None, cfg_diff=diff,
                       cfg_ok=None if diff is None else [d["key"] for d in diff] == [spec["key"]],
                       position=bool(sa.get("position")))
        rows.append(row)
    off = [r["id"] for r in rows if r["state"] in ("off", "empty") or (r["state"] == "ok" and r["running"] is False)]
    return {"on": on, "name": read.get("name_ko") if on else None, "main_ko": None if on else NOT_VWAP_KO, "light": light,
            "small_n": SMALL_N, "small_ko": SMALL_KO, "wait_ko": WAIT_KO, "shadows": rows,
            "start_all_ko": ("sudo systemctl start " + " ".join(UNIT.format(id=i) for i in off)) if off else None}
