"""Loss cards: what a losing trade looked like, built by code at every close (no AI).

A card joins the stored trade (trades.data in paper3.db), the chart situation on the
signal bar (``ctx`` from sigservice.chart_context), the best and worst point during
the trade, fixed descriptive tags, and, once the nightly check has run, what a 1.5,
2.5 or 3 ATR stop would have done (daily3 ``stop*`` shadows).

``tag_stats`` compares how often each tag appears in a strategy's losses and in its
winning trades; a tag much more common in losses is what the strategy's specialist
looks at first. The tags are fixed here and are descriptions, not rules to trade on.

The last three tags read the entry marks of the signal (``ctx["sr"]``, entry_marks.py:
research/entry_study/sr.py on the signal bar). The pre-registered entry study measured
exactly these on five years of signals and found no effect on the outcome
(RESULTS_ENTRY_A.md); TAG_NOTES says so wherever the tags are explained. The card also
carries the strategy's entry-strength numbers (``ctx["strength"]``), equally descriptive.

"경제지표 발표 전후" marks a trade whose entry or exit lies from 30 minutes before to 2 hours
after a US macro release in data/macro_events.csv (events.py: CPI, FOMC, NFP, PCE); the
releases it matched are in ``card["macro"]``. No file or no events there: the tag is never set.

Paper v4: the reel (kind "reel", REEL_H1@5m) and the three 5m coin flips (RANDOM_k@5m) trade the reel's own exits
(paperbot/reel_engine.py: a fixed stop from the signal, a Bollinger-band target, a time exit "TIME"; no ladder, no
lock). Their cards (``own_exits``) carry ``exits = "reel"``, the trade's own stop (``stop_price``, ``stop_ko``) and
no ladder facts: ``touched_first_lock`` is None, the tags that read the first lock price (OWN_EXIT_SKIPPED_TAGS)
are not set, "지지선 뒤 손절" is measured against the trade's own stop instead of 2 ATR, and the nightly stop
what-ifs are not looked up (daily3 computes none for them). Every other card is exactly as before.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Iterable, Optional

from . import events
from .aggregate import TF_MS
from .config import REEL_NAME, REEL_TF, v4_exits
from .ladder import net_roe

REGIME_KO = {"trend_up": "상승 추세", "trend_down": "하락 추세", "box": "박스권", "chop": "방향 없는 횡보",
             "unknown": "뚜렷하지 않음"}
REASON_KO = {"SL": "손절", "LIQ": "강제청산", "LOCK": "익절 잠금", "TP": "익절", "HALT": "정지", "END": "종료",
             "TIME": "시간 청산"}
FIRST_LOCK = 0.12
STOP_VARIANTS = (1.5, 2.5, 3.0)
MACRO_BEFORE_MS = 30 * 60_000      # entry or exit from 30 min before a release ...
MACRO_AFTER_MS = 2 * 3_600_000     # ... to 2 h after it (both edges included)
MACRO_TAG = "경제지표 발표 전후"

# (tag, test on the card fields). Descriptions only; fixed before any paper result.
TAGS = (
    ("강제청산", lambda c: c["reason"] == "LIQ"),
    ("수익 났다가 손절", lambda c: c["reason"] == "SL" and c["best_roe"] is not None and c["best_roe"] >= 0.05),
    ("진입 직후 바로 손절", lambda c: c["reason"] == "SL" and c["hold_bars"] is not None and c["hold_bars"] <= 1
     and (c["best_roe"] or 0) < 0.02),
    ("추세 반대 진입", lambda c: _against(c["side"], c["ctx"].get("regime"))),
    ("상위 봉 추세 반대", lambda c: _against(c["side"], c["ctx"].get("htf_regime"))),
    ("횡보장 진입", lambda c: c["ctx"].get("regime") in ("chop", "box")),
    ("추세 약함 (ADX 20 미만)", lambda c: c["ctx"].get("adx") is not None and c["ctx"]["adx"] < 20),
    ("DI 방향 반대", lambda c: None not in (c["ctx"].get("di_plus"), c["ctx"].get("di_minus"))
     and (c["ctx"]["di_plus"] - c["ctx"]["di_minus"]) * c["side"] < 0),
    ("많이 오른/내린 뒤 추격", lambda c: c["ctx"].get("ema20_dist_atr") is not None
     and c["ctx"]["ema20_dist_atr"] * c["side"] >= 2.0),
    ("최근 범위 끝에서 진입", lambda c: c["ctx"].get("range_pct") is not None
     and ((c["side"] > 0 and c["ctx"]["range_pct"] >= 0.9) or (c["side"] < 0 and c["ctx"]["range_pct"] <= 0.1))),
    # entry study marks (sr.py; "resistance" / "support" as seen from the trade side: for a short
    # the level ahead is below the price and the one behind is above)
    ("저항 바로 앞 진입", lambda c: _sr(c).get("level_before_lock") == 1),
    ("지지선 뒤 손절", lambda c: _sr(c).get("support_before_stop") == 1),
    ("돌파 진입", lambda c: _sr(c).get("breakout") == 1),
    # US macro release calendar (events.py, data/macro_events.csv)
    (MACRO_TAG, lambda c: bool(c.get("macro"))),
)
SR_NOTE = "진입 연구에서 수익과 관계없다고 나온 설명용 표시"
TAG_NOTES = {
    "저항 바로 앞 진입": "진입 방향으로 가장 가까운 가격선이 첫 익절 잠금 가격(+12%)보다 가까움. " + SR_NOTE,
    "지지선 뒤 손절": "반대쪽 가장 가까운 가격선이 손절 가격(2 ATR)보다 가까움: 손절이 그 선 너머. " + SR_NOTE,
    "돌파 진입": "신호 봉 종가가 가격선 하나를 진입 방향으로 넘어섬. " + SR_NOTE,
    MACRO_TAG: "진입 또는 청산 시각이 미국 경제지표 발표(CPI, FOMC, 고용보고서, PCE) 30분 전부터 2시간 후 사이. "
               "발표 일정 파일(data/macro_events.csv)에 등록된 일정만 봄. 설명용 표시이며 매매 규칙 아님",
}

# Accounts with the reel's own exits (paper v4: the reel and the 5m coin flips; config.v4_exits). Their cards
# leave out what only the house ladder has, and read the stop from the trade itself.
OWN_EXITS = "reel"
OWN_EXIT_SKIPPED_TAGS = ("저항 바로 앞 진입",)            # reads the ladder's first lock price (+12%)
OWN_EXITS_KO = "릴스 청산: 신호가 정한 고정 손절 · 직전 5분봉 볼린저 윗선 익절 · 96봉(8시간) 뒤 시간 청산 (사다리·잠금 없음)"
OWN_TAG_NOTES = {
    **{k: v for k, v in TAG_NOTES.items() if k not in OWN_EXIT_SKIPPED_TAGS},
    "지지선 뒤 손절": "반대쪽 가장 가까운 가격선이 이 거래 자신의 손절 가격(신호가 정한 가격)보다 가까움: 손절이 그 선 너머. "
                  + SR_NOTE,
}

MIXED_OWN_KO = " (5분봉 자체 청산 거래는 그 거래 자신의 손절 가격 기준)"
MIXED_SKIPPED_KO = " (5분봉 자체 청산 거래에는 익절 잠금이 없어 이 표시가 붙지 않음)"


def _sr(c: dict) -> dict:
    """The signal side's support / resistance marks ({} when not recorded or failed)."""
    sr = c["ctx"].get("sr")
    return sr if isinstance(sr, dict) else {}


def _against(side: int, regime: Optional[str]) -> bool:
    return (side > 0 and regime == "trend_down") or (side < 0 and regime == "trend_up")


def macro_near(entry_ms: int, exit_ms: int) -> list[dict]:
    """Releases within the window of the entry or the exit, oldest first, each with
    ``entry`` / ``exit`` saying which end of the trade was near it."""
    ends = {"entry": events.near(entry_ms, MACRO_BEFORE_MS, MACRO_AFTER_MS),
            "exit": events.near(exit_ms, MACRO_BEFORE_MS, MACRO_AFTER_MS)}
    out = {}
    for end, evs in ends.items():
        for e in evs:
            d = out.setdefault((e.ts_ms, e.kind), {**e.as_dict(), "entry": False, "exit": False})
            d[end] = True
    return [out[k] for k in sorted(out)]


def own_exits(kind: Optional[str], strategy: Optional[str], timeframe: Optional[str]) -> bool:
    """True for an account on the reel's own exits: by its kind when known (config.v4_exits), else by its name (the
    reel REEL_H1, or a coin flip RANDOM_k on 5m), for callers that have only the trade."""
    if kind:
        return v4_exits(kind, timeframe or "") == OWN_EXITS
    return strategy == REEL_NAME or (timeframe == REEL_TF and str(strategy or "").startswith("RANDOM_"))


def _finite(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _own_stop(t: dict) -> Optional[float]:
    """The stop the trade was opened with (``stop_initial``; the reel never moves it), else its last stop."""
    return _finite(t.get("stop_initial")) or _finite(t.get("stop_price"))


def _own_support(c: dict) -> bool:
    """"지지선 뒤 손절" against the trade's own stop: the nearest level behind the signal close lies strictly closer
    than that stop (long: above it, short: below it)."""
    floor_px, stop = _finite(_sr(c).get("floor_px")), c.get("stop_price")
    return floor_px is not None and stop is not None and (floor_px - stop) * c["side"] > 0


OWN_TESTS = {"지지선 뒤 손절": _own_support}


def _own_exit_fields(c: dict, t: dict) -> None:
    """Replace the ladder facts of a card on the reel's own exits (see the module docstring)."""
    stop = _own_stop(t)
    c["exits"], c["exits_ko"] = OWN_EXITS, OWN_EXITS_KO
    c["touched_first_lock"] = None
    c["stop_price"] = stop
    if stop is not None and c["entry_price"]:
        dist = (c["entry_price"] - stop) / c["entry_price"] * c["side"]
        c["stop_ko"] = f"이 거래 자신의 손절 {stop:.6g} (진입가에서 {dist * 100:.2f}% {'아래' if c['side'] > 0 else '위'})"
    else:
        c["stop_ko"] = "이 거래 자신의 손절 (기록 없음)"
    if c["sr"] is not None:
        sr = {k: v for k, v in c["sr"].items() if k not in ("lock_px", "level_before_lock")}
        sr["stop_px"] = stop
        sr["support_before_stop"] = int(_own_support(c))
        c["sr"] = sr


def card(account_id: str, t: dict, round_trip: float, variants: Optional[dict] = None,
         names_ko: Optional[dict] = None, kind: Optional[str] = None) -> dict:
    """One trade (a stored ``trades.data`` dict) as a card. Works for any trade; the
    dashboard shows losses. ``kind``: the account's kind when the caller knows it (accounts.kind); an account on the
    reel's own exits (``own_exits``) gets the own-exit card."""
    side, lev, entry = int(t["side"]), float(t["leverage"]), float(t["entry_price"])
    tf = t.get("timeframe")
    hold_ms = t["exit_time"] - t["entry_time"]
    ctx = dict(t.get("context") or {})
    best = t.get("mfe_price")
    worst = t.get("mae_price")
    c = {
        "account_id": account_id, "strategy": t["strategy_id"],
        "name_ko": (names_ko or {}).get(t["strategy_id"], t["strategy_id"]),
        "timeframe": tf, "symbol": t["symbol"], "side": side, "side_ko": "롱" if side > 0 else "숏",
        "leverage": int(lev), "entry_time": t["entry_time"], "exit_time": t["exit_time"],
        "entry_price": entry, "exit_price": t["exit_price"], "reason": t["exit_reason"],
        "reason_ko": REASON_KO.get(t["exit_reason"], t["exit_reason"]), "roe": t["roe"], "pnl": t["pnl"],
        "hold_min": hold_ms / 60_000, "hold_bars": hold_ms / TF_MS[tf] if tf in TF_MS else None,
        "best_roe": net_roe(side, entry, best, lev, round_trip) if best else None,
        "worst_roe": net_roe(side, entry, worst, lev, round_trip) if worst else None,
        "ctx": ctx, "regime_ko": REGIME_KO.get(ctx.get("regime"), None),
        "htf_regime_ko": REGIME_KO.get(ctx.get("htf_regime"), None),
        "signal_bar_close": t["signal_ts"] + 1,
    }
    c["touched_first_lock"] = c["best_roe"] is not None and c["best_roe"] >= FIRST_LOCK
    sr, st = ctx.get("sr"), ctx.get("strength")
    c["sr"] = sr if isinstance(sr, dict) and "error" not in sr else None
    c["strength"] = st.get("features") if isinstance(st, dict) else None
    c["macro"] = macro_near(t["entry_time"], t["exit_time"])
    if own_exits(kind, t["strategy_id"], tf):
        _own_exit_fields(c, t)
        c["tags"] = [name for name, test in TAGS
                     if name not in OWN_EXIT_SKIPPED_TAGS and _safe(OWN_TESTS.get(name, test), c)]
    else:
        c["tags"] = [name for name, test in TAGS if _safe(test, c)]
    c["if_stop"] = variants or {}
    return c


def _safe(test, c) -> bool:
    try:
        return bool(test(c))
    except (TypeError, KeyError):
        return False


def tag_stats(cards: Iterable[dict]) -> list[dict]:
    """Per tag: share among losing trades vs among winning trades (same strategy/period)."""
    cards = list(cards)
    losses = [c for c in cards if c["pnl"] < 0]
    wins = [c for c in cards if c["pnl"] > 0]
    # only cards on the reel's own exits (the reel's or a 5m coin flip's page): no ladder tags, own-stop notes
    own = bool(cards) and all(c.get("exits") == OWN_EXITS for c in cards)
    notes = OWN_TAG_NOTES if own else TAG_NOTES
    if not own and any(c.get("exits") == OWN_EXITS for c in cards):
        # a mixed list (e.g. the coin flips' page: house-exit and 5m own-exit flips): the house notes, each saying how
        # the own-exit trades are measured where that differs (only lists holding an own-exit card get this)
        notes = {k: v + (MIXED_SKIPPED_KO if k in OWN_EXIT_SKIPPED_TAGS else MIXED_OWN_KO)
                 if OWN_TAG_NOTES.get(k) != v else v for k, v in TAG_NOTES.items()}
    out = []
    for name, _ in TAGS:
        if own and name in OWN_EXIT_SKIPPED_TAGS:
            continue
        nl = sum(name in c["tags"] for c in losses)
        nw = sum(name in c["tags"] for c in wins)
        out.append({"tag": name, "losses": nl, "loss_share": nl / len(losses) if losses else None,
                    "wins": nw, "win_share": nw / len(wins) if wins else None, "note": notes.get(name)})
    out.sort(key=lambda r: -((r["loss_share"] or 0) - (r["win_share"] or 0)))
    return out


def stop_variants(daily_conn: Optional[sqlite3.Connection], account_id: str, symbol: str,
                  bar_close: int) -> dict:
    """{"1.5": {"roe", "exit_reason", "resolved"}, ...} from daily3 shadows, if computed."""
    if daily_conn is None:
        return {}
    out = {}
    for k in STOP_VARIANTS:
        r = daily_conn.execute("SELECT roe, exit_reason, resolved FROM shadows WHERE key = ?",
                               (f"stop{k}|{account_id}|{symbol}|{bar_close}",)).fetchone()
        if r is not None:
            out[str(k)] = {"roe": r[0], "exit_reason": r[1], "resolved": bool(r[2])}
    return out


EXTRA_KINDS = ("copy", "newlab")


def cards_from_db(conn: sqlite3.Connection, round_trip: float, strategy: Optional[str] = None,
                  timeframe: Optional[str] = None, losses_only: bool = True, since_ms: int = 0,
                  limit: int = 200, daily_conn: Optional[sqlite3.Connection] = None,
                  names_ko: Optional[dict] = None, kinds: Optional[Iterable[str]] = None,
                  account_id: Optional[str] = None) -> list[dict]:
    """Cards of the latest closed trades, newest first. Filters: ``strategy`` and ``timeframe`` (the account's own
    columns: a copy account 'S@15m~c1' is strategy S on 15m), ``kinds`` (accounts.kind: 'strategy', 'random',
    'copy', 'newlab'), one ``account_id``. An extra account's card carries ``kind``, ``parent`` and its
    ``label_ko`` (also as ``name_ko``); a copy's stop what-ifs are its parent's (the nightly shadows are
    computed per signal of the parent, the copy repeats them)."""
    ks = [k for k in (kinds or ())]
    q = ("SELECT t.account_id, t.data, a.kind, a.parent, a.data FROM trades t "
         "LEFT JOIN accounts a ON a.account_id = t.account_id WHERE t.exit_time >= ?")
    args: list = [since_ms]
    if losses_only:
        q += " AND t.pnl < 0"
    if strategy:
        q += " AND a.strategy = ?"
        args.append(strategy)
    if timeframe:
        q += " AND a.timeframe = ?"
        args.append(timeframe)
    if ks:
        q += f" AND a.kind IN ({','.join('?' * len(ks))})"
        args.extend(ks)
    if account_id:
        q += " AND t.account_id = ?"
        args.append(account_id)
    q += " ORDER BY t.id DESC LIMIT ?"
    args.append(min(max(limit, 1), 2000))
    try:
        rows = [tuple(r) for r in conn.execute(q, args)]
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        rows = _rows_without_accounts(conn, strategy, timeframe, losses_only, since_ms, limit, account_id)
    out = []
    for aid, data, kind, parent, adata in rows:
        t = json.loads(data)
        shadow = parent if kind == "copy" and parent else aid
        if own_exits(kind, t.get("strategy_id"), t.get("timeframe")):
            v = {}                    # daily3 computes no stop what-ifs for the reel's own exits
        else:
            v = stop_variants(daily_conn, shadow, t["symbol"], t["signal_ts"] + 1)
        c = card(aid, t, round_trip, v, names_ko, kind=kind)
        if kind in EXTRA_KINDS:
            try:
                d = json.loads(adata) if adata else {}
            except (TypeError, ValueError):
                d = {}
            label = d.get("label_ko") if isinstance(d, dict) and isinstance(d.get("label_ko"), str) else None
            c.update(kind=kind, parent=parent, label_ko=label)
            if label:
                c["name_ko"] = label
        out.append(c)
    return out


def _rows_without_accounts(conn: sqlite3.Connection, strategy: Optional[str], timeframe: Optional[str],
                           losses_only: bool, since_ms: int, limit: int, account_id: Optional[str]) -> list[tuple]:
    """A trades table without an accounts table (a bare test database): filter by the account id's spelling."""
    q = "SELECT account_id, data FROM trades WHERE exit_time >= ?"
    args: list = [since_ms]
    if losses_only:
        q += " AND pnl < 0"
    esc = lambda x: x.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")  # noqa: E731
    if strategy:
        q += " AND account_id LIKE ? ESCAPE '\\'"
        args.append(f"{esc(strategy)}@%")
    if timeframe:
        q += " AND account_id LIKE ? ESCAPE '\\'"
        args.append(f"%@{esc(timeframe)}")
    if account_id:
        q += " AND account_id = ?"
        args.append(account_id)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(min(max(limit, 1), 2000))
    return [(r[0], r[1], None, None, None) for r in conn.execute(q, args)]
