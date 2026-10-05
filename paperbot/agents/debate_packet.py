"""The 24-hour debate room's input: ONE compact JSON packet built by code from the bot's databases, read-only.

Sources (all opened read-only, ``mode=ro``; when the debate service's user cannot create the -shm file of a WAL
database that is not being written, the open falls back to ``immutable=1``, which is only used when ``mode=ro`` fails):
paper3.db (accounts, trades, state), daily3.db (nightly checks, shadows), agents3.db (the staff's recent meetings),
checkpoint.db (the 30-day verdict, if it exists). The builders are the staff's own (packets3, leveval, riskreward,
shock): the same numbers the agent rooms read, narrowed to what one short debate can use.

The packet has a core (always) and one topic section chosen by code (a rotating agenda; anything unusual jumps the
queue, but never twice in a row for the same reason), and is trimmed to ``MAX_PACKET_TOKENS`` (an estimate: the real
count is in the API's usage fields). Nothing in it is a model's text except the debate's own earlier notes, which are
labelled as such. Nothing here writes anywhere.
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
from typing import Any, Optional

DAY_MS = 86_400_000
KST_MS = 9 * 3_600_000
MAX_PACKET_TOKENS = 3500           # the packet alone (the stable system prompt, ~2k, comes on top); owners pay per token
MIN_N = 30                         # below this many trades an account's numbers are 'small sample' (packets3 default)
OBSERVE_UNTIL = "2026-10-26"       # the owners' observation period for the 195 -> 156 accounts

# (key, Korean name) in agenda order
TOPICS = (
    ("lev", "좋은 자리 vs 보통 레버리지 묶음"),
    ("rank", "상위·하위 매매법과 표본 크기"),
    ("exits", "청산 방식과 손익 구조"),
    ("nightly", "밤 점검과 데이터 품질"),
    ("tf", "봉(15분·30분·1시간·4시간)별 차이"),
    ("coin", "코인별 차이"),
    ("shadow", "그림자 비교(다른 규칙이었다면)"),
    ("risk", "파산·낙폭·가격 충격 위험"),
    ("ideas", "새 매매법 연구실에 줄 아이디어"),
)
TOPIC_KO = dict(TOPICS)


# ---------------------------------------------------------------- reading
def open_ro(path: Optional[str]) -> Optional[sqlite3.Connection]:
    """A read-only connection (rows as sqlite3.Row), or None when the file is missing or unreadable."""
    if not path or not os.path.exists(path):
        return None
    base = "file:" + urllib.parse.quote(os.path.abspath(path))
    for flags in ("?mode=ro", "?mode=ro&immutable=1"):
        conn = None
        try:
            conn = sqlite3.connect(base + flags, uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
            return conn
        except sqlite3.Error:
            if conn is not None:
                conn.close()
    return None


def estimate_tokens(text: str) -> int:
    """A conservative token estimate without any API call: ASCII (dense JSON numbers and punctuation) about 2.8
    characters per token, Hangul and other characters about one token each (Claude's tokenizer splits Korean
    finely). The real number is the API's ``usage.input_tokens``, shown by ``status`` after the first round."""
    ascii_n = sum(1 for ch in text if ord(ch) < 128)
    return int(ascii_n / 2.8 + (len(text) - ascii_n)) + 1


def _r(x: Any, n: int = 4) -> Any:
    try:
        return None if x is None else round(float(x), n)
    except (TypeError, ValueError):
        return None


def shrink(obj: Any, max_list: int = 8, max_str: int = 160, depth: int = 0) -> Any:
    """A copy with long lists cut, long strings cut and floats rounded (a packet must stay small)."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        return {str(k): shrink(v, max_list, max_str, depth + 1) for k, v in list(obj.items())[:40]}
    if isinstance(obj, (list, tuple)):
        return [shrink(v, max_list, max_str, depth + 1) for v in list(obj)[:max_list]]
    if isinstance(obj, float):
        return round(obj, 5)
    if isinstance(obj, str):
        return obj if len(obj) <= max_str else obj[:max_str] + "…"
    return obj


def kst_day(ms: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- pieces
def _league(board: dict) -> dict:
    out = {}
    for tf, v in (board.get("league") or {}).items():
        out[tf] = {"median_wallet": v.get("median_wallet"), "above_start": v.get("above_start"),
                   "beat_all_coin_flips": v.get("beat_all_coin_flips"), "bust": v.get("bust"),
                   "open_positions": v.get("open_positions"), "strategy_accounts": v.get("strategy_accounts"),
                   "coin_flip_wallets": v.get("coin_flip_wallets")}
    return out


def _accounts_rows(board: dict, min_n: int) -> list[dict]:
    rows = []
    for aid, v in (board.get("pass_check") or {}).items():
        rows.append({"account": aid, "wallet": v.get("wallet"), "trades": v.get("trades"),
                     "small_sample": (v.get("trades") or 0) < min_n, "bust": bool(v.get("bust"))})
    return rows


def _rank(board: dict, min_n: int, k: int = 5) -> dict:
    """Top / bottom accounts by wallet (strategy x timeframe), each with its trade count and a small-sample flag."""
    rows = _accounts_rows(board, min_n)
    rows = [r for r in rows if r["wallet"] is not None]
    rows.sort(key=lambda r: -r["wallet"])
    by = []
    for strat, tfs in (board.get("by_strategy") or {}).items():
        n = sum((c.get("trades") or 0) for c in tfs.values())
        ws = [(c.get("trades") or 0, c.get("mean_roe")) for c in tfs.values() if c.get("mean_roe") is not None]
        if ws and sum(w for w, _ in ws):
            by.append({"strategy": strat, "trades": n,
                       "mean_roe": _r(sum(w * m for w, m in ws) / sum(w for w, _ in ws), 4),
                       "small_sample": n < min_n * 2})
    by.sort(key=lambda r: -(r["mean_roe"] if r["mean_roe"] is not None else -9))
    return {"accounts_top": rows[:k], "accounts_bottom": rows[-k:] if len(rows) > k else [],
            "strategies_top": by[:k], "strategies_bottom": by[-k:] if len(by) > k else [],
            "note": f"지갑 = 시작 5,000 USDT 기준. small_sample = 거래 {min_n}건 미만(우연일 수 있음)"}


def _tf(board: dict) -> dict:
    out: dict = {}
    for strat, tfs in (board.get("by_strategy") or {}).items():
        for tf, c in tfs.items():
            b = out.setdefault(tf, {"trades": 0, "w": 0.0, "wins": 0.0})
            n = c.get("trades") or 0
            b["trades"] += n
            if c.get("mean_roe") is not None:
                b["w"] += n * c["mean_roe"]
            if c.get("win_rate") is not None:
                b["wins"] += n * c["win_rate"]
    return {tf: {"trades": b["trades"], "mean_roe": _r(b["w"] / b["trades"], 4) if b["trades"] else None,
                 "win_rate": _r(b["wins"] / b["trades"], 3) if b["trades"] else None} for tf, b in out.items()}


def _exits(board: dict) -> dict:
    ex, st = board.get("exits") or {}, board.get("execution") or {}
    return {"reasons": ex.get("reasons"), "mean_roe_by_reason": ex.get("mean_roe_by_reason"),
            "lock_levels": ex.get("lock_levels"), "leverage_mix": ex.get("leverage"), "win_rate": ex.get("win_rate"),
            "fees_total": st.get("fees_total"), "funding_total": st.get("funding_total"),
            "cost_share_of_losses": st.get("cost_share_of_losses"), "signal_outcomes": st.get("signal_outcomes")}


def _nightly(board: dict) -> Optional[dict]:
    n = board.get("nightly")
    if not isinstance(n, dict):
        return None
    keep = {k: n.get(k) for k in ("day", "parity", "missing_bars", "mismatched_accounts", "mismatch_labels",
                                  "data_quality", "strength") if k in n}
    return shrink(keep, 6, 120)


def _alerts(board: dict, k: int = 5) -> list[dict]:
    return [{"level": a.get("level"), "text": str(a.get("text") or "")[:110]}
            for a in ((board.get("today") or {}).get("alerts") or [])[:k]]


def _shadows(daily: Optional[sqlite3.Connection], paper: Optional[sqlite3.Connection], start: int, now_ms: int) -> dict:
    from . import riskreward as RR
    if daily is None:
        return {"error": "daily3.db 없음"}
    sh = RR.shadow_summary(daily, paper, int(start), int(now_ms))
    cells = (sh.get("all") or {}) if isinstance(sh, dict) else {}
    rows = []
    for v, c in cells.items():
        if not isinstance(c, dict) or not c.get("trades"):
            continue
        rows.append({"variant": v, "trades": c.get("trades"), "vs_base_eq": _r(c.get("vs_base_eq"), 5),
                     "better_share": _r(c.get("better_share"), 2), "small": bool(c.get("small"))})
    rows.sort(key=lambda r: -(r["trades"] or 0))
    return {"rows": rows[:12], "note": "vs_base_eq = 그림자 규칙이 같은 거래에서 base보다 자금 대비 얼마나 달랐는지(설명용). "
                                       "small = 10건 미만"}


def _recent_meetings(agents: Optional[sqlite3.Connection], k: int = 4) -> list[dict]:
    if agents is None:
        return []
    try:
        rows = agents.execute("SELECT room_id, trigger, ended_ts, decision FROM rounds WHERE status = 'done' "
                              "AND decision IS NOT NULL ORDER BY round_id DESC LIMIT ?", (k,)).fetchall()
    except sqlite3.Error:
        return []
    return [{"room": r[0], "trigger": r[1], "ended_ts": r[2], "decision": str(r[3] or "")[:140]} for r in rows]


def _checkpoint(path: Optional[str], now_ms: int, start: Optional[int]) -> dict:
    """The 30-day verdict state: only whether a verdict exists and when the next one is (never the verdict itself:
    the debate does not conclude before day 30)."""
    out: dict = {"verdict_exists": False}
    if not path or start is None:
        return out
    try:
        from .. import checkpoint as CP
        view = CP.dashboard_view(path)
        out["verdict_exists"] = bool(view.get("ready"))
        k, last = 1, (CP.day_ms(view["date"]) if view.get("ready") else -1)
        while CP.checkpoint_ts(start, k) <= last:
            k += 1
        out["next"] = f"{CP.day_str(CP.checkpoint_ts(start, k))} 09:00 KST"
    except Exception:  # noqa: BLE001  (a missing file or table is a known state)
        pass
    return out


def unusual(board: dict, levrule: Optional[dict]) -> list[tuple[str, str]]:
    """[(topic key, why)] for the things that should jump the agenda, most urgent first (code only)."""
    out = []
    busts = (board.get("today") or {}).get("busts_total") or 0
    if busts:
        out.append(("risk", f"파산한 전략 계좌 {busts}개"))
    n = board.get("nightly") if isinstance(board.get("nightly"), dict) else {}
    par = n.get("parity")
    if (isinstance(par, dict) and (par.get("mismatched_accounts") or 0) > 0) or n.get("missing_bars"):
        out.append(("nightly", "밤 점검에 재계산 불일치나 빠진 1분봉이 있음"))
    crit = [a for a in ((board.get("today") or {}).get("alerts") or []) if a.get("level") == "CRITICAL"]
    if crit:
        out.append(("risk", f"긴급 알림 {len(crit)}건"))
    return out


# ---------------------------------------------------------------- the packet
def build(paper_path: Optional[str], daily_path: Optional[str], agents_path: Optional[str],
          checkpoint_path: Optional[str], now_ms: int, round_no: int = 0, recent_topics: tuple = (),
          last_notes: Optional[list] = None, last_turns: Optional[list] = None, scoreboard: Optional[dict] = None,
          min_n: int = MIN_N, max_tokens: int = MAX_PACKET_TOKENS) -> dict:
    """{"packet": dict, "topic": key, "topic_ko": str, "why": str, "tokens": estimate}. Raises FileNotFoundError when
    paper3.db is missing (there is nothing to debate then); every other source is optional and noted when absent."""
    if not paper_path or not os.path.exists(paper_path):
        raise FileNotFoundError("paper3.db")
    from . import packets3
    board = packets3.build(paper_path, daily_path, now_ms, min_n=min_n)
    paper, daily, agents = open_ro(paper_path), open_ro(daily_path), open_ro(agents_path)
    try:
        start = None
        if paper is not None:
            from ..checkpoint import run_facts
            try:
                start = run_facts(paper).get("start_ts")
            except (sqlite3.Error, TypeError, ValueError):
                start = None
        lev = None
        if paper is not None:
            from . import leveval as LV
            try:
                lev = LV.compact(LV.levrule_eval(paper, now_ms=now_ms, mix=False))
            except Exception as exc:  # noqa: BLE001  (a display never stops the debate)
                lev = {"error": f"규칙 B 평가를 만들지 못함: {type(exc).__name__}"}
        flags = unusual(board, lev)
        topic, why = TOPICS[round_no % len(TOPICS)][0], "정해진 순서(돌아가며)"
        for key, reason in flags:
            if list(recent_topics[:2]).count(key) < 2:             # an unusual thing jumps the queue, not forever
                topic, why = key, "이상 징후: " + reason
                break
        sections: dict = {}
        if topic == "lev":
            sections["levrule"] = lev
        elif topic == "rank":
            sections["rank"] = _rank(board, min_n)
        elif topic == "exits":
            sections["exits"] = _exits(board)
        elif topic == "nightly":
            sections["nightly_detail"] = _nightly(board)
        elif topic == "tf":
            sections["by_timeframe"] = _tf(board)
        elif topic == "coin":
            sections["by_coin"] = board.get("by_coin")
        elif topic == "shadow" and paper is not None:
            sections["shadows"] = _shadows(daily, paper, start or 0, now_ms)
        elif topic == "risk":
            from . import shock as SH
            try:
                sections["shock"] = SH.compact(paper)
            except Exception as exc:  # noqa: BLE001
                sections["shock"] = {"error": f"가격 충격 시험을 만들지 못함: {type(exc).__name__}"}
        elif topic == "ideas":
            sections["note"] = "이번 주제는 새 매매법 연구실에 줄 아이디어 찾기: 아래 자료에서 눈에 띈 점을 아이디어 후보로 바꿔 본다"
            sections["by_timeframe"] = _tf(board)
        meta = board.get("meta") or {}
        days = meta.get("days_running")
        today = board.get("today") or {}
        ex = board.get("execution") or {}
        ev = board.get("exits") or {}
        core = {
            "meta": {"now_kst": kst_day(now_ms), "run_day": None if days is None else f"D+{int(days)}",
                     "days_running": days, "accounts": meta.get("accounts"),
                     "run_restarted": meta.get("run_restarted"),
                     "observation": f"{OBSERVE_UNTIL}까지 관찰 기간: 195→156 계좌 규칙 변경 제안 금지(아이디어만)",
                     "checkpoint": _checkpoint(checkpoint_path, now_ms, start),
                     "units": "ROE·수익률은 비율(0.10 = +10%), 지갑은 USDT(시작 5,000)"},
            "league": _league(board),
            "totals": {"trades": sum(ev.get("reasons", {}).values()) if ev.get("reasons") else 0,
                       "win_rate": ev.get("win_rate"), "net_pnl": ex.get("net_pnl_total"),
                       "busts": today.get("busts_total")},
            "last_24h": {"trades": today.get("trades"), "net_pnl": today.get("net_pnl"), "wins": today.get("wins"),
                         "biggest_losses": (today.get("biggest_losses") or [])[:3]},
            "alerts": _alerts(board),
            "nightly": _nightly(board) if topic != "nightly" else {"see": "nightly_detail"},
            "recent_agent_meetings": _recent_meetings(agents),
            "topic": TOPIC_KO.get(topic),
            "unusual": [{"topic": TOPIC_KO[k], "why": w} for k, w in flags],
        }
        if scoreboard is not None:
            core["hypothesis_scoreboard"] = {"graded": scoreboard.get("graded"), "hit": scoreboard.get("hit"),
                                             "small_sample": scoreboard.get("small"), "open": (
                scoreboard.get("by_status") or {}).get("open", 0)}
        core["previous_debate_notes"] = {"note": "이 방 AI가 전에 쓴 정리: 사실이 아니라 의견. 같은 말을 되풀이하지 않기",
                                         "notes": list(last_notes or [])[:2], "last_turns": list(last_turns or [])[:2]}
        pk = {**core, **{k: v for k, v in sections.items() if v is not None}}
    finally:
        for c in (paper, daily, agents):
            if c is not None:
                c.close()
    pk = shrink(pk, 10, 200)
    # trim to the budget: drop the least needed pieces first, then cut lists harder
    for key in ("recent_agent_meetings", "alerts", "last_24h", "unusual"):
        if estimate_tokens(compact_json(pk)) <= max_tokens:
            break
        pk.pop(key, None)
    for ml, ms in ((6, 140), (4, 100), (3, 80)):
        if estimate_tokens(compact_json(pk)) <= max_tokens:
            break
        pk = shrink(pk, ml, ms)
    return {"packet": pk, "topic": topic, "topic_ko": TOPIC_KO[topic], "why": why,
            "tokens": estimate_tokens(compact_json(pk))}


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)



# ---------------------------------------------------------------- "did anything relevant change?" (no API call)
def fingerprint(paper_path: Optional[str], daily_path: Optional[str]) -> dict:
    """A few cheap numbers that say whether the bot's picture changed: the newest closed trade id, the newest
    non-INFO alert, the newest nightly report day and the number of bust accounts. Read-only; {} when unreadable."""
    out: dict = {}
    paper, daily = open_ro(paper_path), open_ro(daily_path)
    try:
        if paper is not None:
            try:
                r = paper.execute("SELECT MAX(id) FROM trades").fetchone()
                out["trade_id"] = int(r[0] or 0)
                r = paper.execute("SELECT MAX(ts) FROM alerts WHERE level != 'INFO'").fetchone()
                out["alert_ts"] = int(r[0] or 0)
                st = paper.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
                eng = json.loads(st[0]).get("engines", {}) if st else {}
                out["busts"] = sum(1 for e in eng.values() if isinstance(e, dict) and e.get("bust"))
            except (sqlite3.Error, TypeError, ValueError, AttributeError):
                pass
        if daily is not None:
            try:
                r = daily.execute("SELECT MAX(day) FROM reports").fetchone()
                out["nightly_day"] = str(r[0] or "")
            except sqlite3.Error:
                pass
    finally:
        for c in (paper, daily):
            if c is not None:
                c.close()
    return out


def changed(prev: Optional[dict], cur: dict, min_new_trades: int) -> tuple[bool, str]:
    """(relevant change?, Korean reason). Relevant: at least ``min_new_trades`` new closed trades, any new non-INFO
    alert, a new nightly report, a different bust count, or a database that was replaced (trade ids went back)."""
    if not prev or not cur:
        return True, "처음이거나 비교할 기록이 없음"
    new = cur.get("trade_id", 0) - prev.get("trade_id", 0)
    if new < 0:
        return True, "paper3.db가 새로 시작된 것으로 보임"
    if new >= min_new_trades:
        return True, f"새 청산 {new}건"
    if cur.get("alert_ts", 0) > prev.get("alert_ts", 0):
        return True, "새 경고 알림"
    if cur.get("nightly_day", "") != prev.get("nightly_day", ""):
        return True, "새 밤 점검"
    if cur.get("busts", 0) != prev.get("busts", 0):
        return True, "파산 계좌 수가 바뀜"
    return False, f"새 청산 {new}건(기준 {min_new_trades}건), 새 알림 없음, 새 밤 점검 없음"
