"""매매법 성적표와 개선 후보 장부: the improvement loop around the combined paper bot (paperbot/combo.py, account
COMBO@mix, "A+C 합본") that the two real-money executors follow (Bybit $100, MEXC $100, owners 2026-10-19).

    python -m paperbot.liveimprove score [--since YYYY-MM-DD]
                                         [--by strategy|member|coin|side|reg5|hb|stop|entry|invert|all]
    python -m paperbot.liveimprove candidates [--dry-run] [--since YYYY-MM-DD]
    python -m paperbot.liveimprove ledger list
    python -m paperbot.liveimprove ledger set ID --status "백테스트 시험" --note "..." [--backtest-ok] [--shadow-ok]
    python -m paperbot.liveimprove weekly [--dry-run] [--since YYYY-MM-DD]
    python -m paperbot.liveimprove preview [--loud]

1. 매매법 성적표 (``score``): the paper account's closed trades since ``--since`` (09:00 KST of that date; default: its
   first trade), per strategy (27) and per setting (95, numbered from 1 as the paper bot's member_order; the
   reference's members are keyed from 0, livecheck.ref_member), and the same table cut by coin, side, BTC 4h regime
   (reg5), KST 4-hour block (hb), stop type, entry style and invert. A row: trades, wins, win rate, average net ROE,
   losses and their median net ROE, the backtest reference's fit win rate and its honest one
   (deploy/combo.live-ac.expected.json: the twin fitted on 2020-24 only, read on unseen 2025-26; a strategy with fewer
   than ``HONEST_MIN_N`` unseen trades uses the overall 75%; a reference made for another config than the running one,
   livecheck.ref_config_problem, is not loaded at all: ``load_ref`` raises and nothing is scored, sent or written),
   and a status word from a one-sided binomial test of the live wins against the honest rate: "표본 작음" under
   ``SMALL_N`` trades, "주의" at p < 0.05, "확실히 나쁨" only at
   p < 0.05 / (rows of the table) (27 for the strategies: with 27 strategies 1-2 "주의" by luck alone are normal),
   else "기대 안". The executor columns: for the trades each executor followed (livecheck.match_paper), its net ROE
   against the paper's on the same trades (what costs and slippage take).
2. 개선 후보 장부 (``candidates``, and every ``weekly``): cells where live losses concentrate beyond the reference
   (strategy, strategy x coin, strategy x reg5, strategy x side, coin x side, hb) with at least ``CAND_MIN_N`` live
   trades and a one-sided binomial p < 0.05 against the lower of the honest rate and the cell's fit rate (the fit
   rate only when the reference has ``HONEST_MIN_N`` trades in that cell). The number of cells tested is reported
   with each pass (about 5% of them come out by luck). Flagged cells holding exactly the same trades are one
   candidate (the most specific cell; the others named in its question). A new cell becomes a ledger row (status
   발견) with a research question in Korean; a cell already in the ledger only gets its live evidence refreshed. The
   status moves only by hand (``ledger set``): 발견 -> 백테스트 시험 -> 그림자 시험 -> 채택 / 기각, with notes and
   dates, and 채택 only when the owners' pre-registered rule holds (``ADOPT_RULE``). The fixed rules
   (``FIXED_RULES``) are never cells.
3. ``weekly`` (deploy/paperbot-liveimprove.timer, Mondays 09:30 KST): one Korean Telegram message, sent only through
   livecheck ``_notifier()`` (the live chat and sound rules live there), first line "📊 주간 성적표 · 10/13~10/19"
   (the 7 trading days that ended at 09:00): the scoreboard's top and bottom, new candidates and the open ledger
   items with their next step. Silent (INFO) unless a strategy or the whole account is "확실히 나쁨" (CRITICAL, first
   line "🚨 ..."; the other tables' own bars stay in ``score``: nine tables a week would ring by luck). It stores the
   week's scorecard (``snapshots``, ``weeks``) and the ledger in its own SQLite file (``--db``, default
   /var/lib/paperbot/liveimprove.db; see ``SCHEMA``, for the dashboard later). ``--dry-run`` prints and writes nothing.
   ``preview`` prints the message of a hand-made first week (no database at all; ``--loud``: with a strategy that is
   "확실히 나쁨").

Read-only towards every bot: their databases are opened read-only (mode=ro) with ``PRAGMA query_only``, the
executors' configs are read as plain JSON (livecheck.load_executors; never their key file), no exchange is called and
no order is sent. Nothing here changes a bot or a config: the owners decide.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import livecheck as LC

ACCOUNT = LC.ACCOUNT
DEFAULT_DB = "/var/lib/paperbot/liveimprove.db"
EXPECTED = Path(__file__).resolve().parent.parent / "deploy" / "combo.live-ac.expected.json"
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")     # paperbot/rmember.py SYMS
ALPHA = 0.05
SMALL_N = 10                       # fewer live trades in a row than this: "표본 작음" (no verdict)
HONEST_MIN_N = 30                  # a strategy's (or a reference cell's) own number is used from this many trades on
CAND_MIN_N = 8                     # live trades a cell needs to become a candidate
ADOPT_MIN_N = 20                   # adoption rule (a)
SHADOW_DAYS, SHADOW_TRADES = 14, 20       # adoption rule (c): two weeks or 20 trades
CHECK_N = 40                       # the owners' first real checkpoint (livecheck CHECK_N)
TOP_N = 3                          # strategies named at the top and at the bottom of the weekly message
SMALL, OK, WATCH, BAD = "표본 작음", "기대 안", "주의", "확실히 나쁨"
STATUSES = ("발견", "백테스트 시험", "그림자 시험", "채택", "기각")
OPEN = ("발견", "백테스트 시험", "그림자 시험")
FLOW = {"발견": ("백테스트 시험", "기각"), "백테스트 시험": ("그림자 시험", "기각"), "그림자 시험": ("채택", "기각"),
        "기각": ("발견",), "채택": ()}
ALIASES = {"found": "발견", "reopen": "발견", "backtest": "백테스트 시험", "백테스트": "백테스트 시험",
           "shadow": "그림자 시험", "그림자": "그림자 시험", "adopt": "채택", "adopted": "채택", "reject": "기각",
           "rejected": "기각"}
CUTS = ("strategy", "member", "coin", "side", "reg5", "hb", "stop", "entry", "invert")
CUT_KO = {"strategy": "매매법별", "member": "세팅별", "coin": "코인별", "side": "방향별", "reg5": "BTC 4시간 장세별",
          "hb": "한국 시간 4시간대별", "stop": "손절 방식별", "entry": "진입 방식별", "invert": "방향 뒤집기별"}
CELL_KINDS = ("strategy", "strategy_coin", "strategy_reg5", "strategy_side", "coin_side", "hb")
KIND_KO = {"strategy": "매매법", "strategy_coin": "매매법x코인", "strategy_reg5": "매매법x장세",
           "strategy_side": "매매법x방향", "coin_side": "코인x방향", "hb": "4시간대"}
# never a candidate: the owners' fixed rules (a cell kind that would change one is refused by find_candidates)
FIXED_RULES = ("레버리지", "계단 익절", "증거금 40%", "한 번에 포지션 하나", "코인 6개", "주말 쉬기",
               "미국 지표 ±30분 진입 없음")
ENTRY_KO = {"now": "즉시 진입", "break": "돌파 확인 뒤 진입"}
QUESTION_TAIL = "2020-24와 2025-26 둘 다 좋아지나? 거래 수는 얼마나 줄어드나?"
ADOPT_RULE = ("채택 규칙(미리 정함, 셋 다 맞아야 채택)",
              f"(a) 실거래에서 그 칸 거래 {ADOPT_MIN_N}번 이상, p<0.05",
              "(b) 백테스트에서 2020-24와 2025-26을 따로 돌려 둘 다 좋아짐",
              f"(c) 바꾼 그림자 페이퍼 봇이 2주 이상 또는 거래 {SHADOW_TRADES}번 이상 돌고, 지금 페이퍼 봇보다 나쁘지 않음",
              "자동으로 바뀌는 것은 없습니다. 두 분이 정합니다.")
LUCK_NOTE = "매매법 27개를 한꺼번에 보면 운만으로도 1~2개는 \"주의\"가 나옵니다. 정상입니다."


# ====================================================================== small helpers
def kst_hb(ms: int) -> int:
    """The KST 4-hour block of a time (0 = 00-04시), paperbot/rmember.py ``hb``."""
    return int(((int(ms) // 1000 + 9 * 3600) // 3600) % 24) // 4


def kst_date(ms: int) -> str:
    return LC.kst(ms, "%Y-%m-%d")


def _int(x) -> Optional[int]:
    try:
        return None if x is None else int(x)
    except (TypeError, ValueError):
        return None


def stop_name(rstop) -> Optional[str]:
    """["atr", 2.0] -> "atr2" (the reference's stop type)."""
    try:
        return f"{rstop[0]}{float(rstop[1]):g}"
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def stop_ko(name: Optional[str]) -> str:
    """"atr2" -> "ATR 2배" (ATR = 평균 변동폭), "pct2" -> "2% 고정", "swing10" -> "스윙 10봉"."""
    if not name:
        return "모름"
    for kind, fmt in (("atr", "ATR {}배"), ("pct", "{}% 고정"), ("swing", "스윙 {}봉")):
        if name.startswith(kind):
            return fmt.format(name[len(kind):])
    return name


def pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.0%}"


def wr(wins: int, n: int) -> str:
    """'17/20 (85%)': the shared way to show a win rate."""
    return f"{wins}/{n} ({wins / n:.0%})" if n else "0/0"


TF_ORDER = ("15m", "30m", "1h", "4h")


def tfs_of(trades: list) -> list:
    return sorted({t["tf"] for t in trades if t.get("tf")}, key=lambda x: TF_ORDER.index(x) if x in TF_ORDER else 9)


def with_tf(name: str, tfs) -> str:
    """'N03_ADX_GC 15분·30분': a strategy as the owners see it (name + the Korean timeframes it traded)."""
    tfs = [LC.KO_TF.get(x, x) for x in (tfs or [])]
    return f"{name} {'·'.join(tfs)}" if tfs else name


def roe_txt(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:+.1%}"


def p_txt(p: Optional[float]) -> str:
    if p is None:
        return ""
    if p < 0.0001:
        return "p<0.0001"
    return f"p={p:.4f}" if p < 0.001 else f"p={p:.3f}"


def _w(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s, width: int, right: bool = False) -> str:
    s = str(s)
    gap = " " * max(0, width - _w(s))
    return gap + s if right else s + gap


# ====================================================================== statistics
def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p): the one-sided p-value of k wins or fewer when the true win rate is p."""
    if n <= 0 or k >= n:
        return 1.0
    if k < 0:
        return 0.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    terms = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq
             for i in range(k + 1)]
    top = max(terms)
    return min(1.0, math.exp(top) * sum(math.exp(t - top) for t in terms))


def verdict(n: int, wins: int, p0: Optional[float], family: int) -> tuple[str, Optional[float]]:
    """(status word, p). One-sided binomial test of ``wins`` of ``n`` against the rate ``p0``; "확실히 나쁨" only
    below 0.05 / ``family`` (the rows tested together), "주의" below 0.05."""
    if n < SMALL_N or p0 is None:
        return SMALL, None
    p = binom_cdf(wins, n, p0)
    if p < ALPHA / max(1, family):
        return BAD, p
    if p < ALPHA:
        return WATCH, p
    return OK, p


# ====================================================================== the reference (combo.live-ac.expected.json)
def load_ref(path: Optional[str] = None, combo_config: Optional[str] = None) -> dict:
    """The 5-year reference. ``livecheck.RefConfigMismatch`` (a ValueError whose text is the Korean reason) when it
    was made for another config than the running one (livecheck.ref_config_problem: ``combo_config``, by default
    PAPERBOT_LIVE_COMBO_CONFIG or /etc/paperbot/combo.json), so no scorecard compares the bot with another bot."""
    with open(path or EXPECTED, encoding="utf-8") as fh:
        ref = json.load(fh)
    why = LC.ref_config_problem(ref, combo_config)
    if why:
        raise LC.RefConfigMismatch(why)
    return ref


def honest_overall(ref: dict) -> float:
    return float(ref["overall"]["honest"]["win_2025_26"])


def strategy_honest(ref: dict, name: str) -> tuple[float, str]:
    """(honest win rate, where it comes from): the strategy's own unseen 2025-26 rate from HONEST_MIN_N trades on,
    else the overall one."""
    h = (ref["strategies"].get(name) or {}).get("honest_2025_26")
    if h and h[1] is not None and int(h[0]) >= HONEST_MIN_N:
        return float(h[1]), f"이 매매법 {int(h[0])}번"
    return honest_overall(ref), "전체"


def _pair_win(pair, min_n: int = 1) -> tuple[Optional[float], int]:
    if not pair or pair[1] is None:
        return None, 0
    n = int(pair[0])
    return (float(pair[1]) if n >= min_n else None), n


def family_size(ref: dict, cut: str) -> int:
    """The rows a table tests together (the reference's universe, not what live trading has shown so far)."""
    return {"strategy": len(ref["strategies"]), "member": len(ref["members"]), "coin": len(ref.get("symbols") or SYMS),
            "side": 2, "reg5": len(ref.get("reg5_names") or range(5)), "hb": 6,
            "stop": max(1, len(ref.get("stops") or {})), "entry": 2, "invert": 2}.get(cut, 1)


def _members_win(ref: dict, field: str, value) -> Optional[float]:
    n = w = 0.0
    for m in ref["members"].values():
        if m.get(field) == value and m.get("trades") and m.get("win") is not None:
            n += m["trades"]
            w += m["trades"] * m["win"]
    return (w / n) if n else None


def expect(ref: dict, cut: str, key: Optional[str]) -> tuple[Optional[float], float, str]:
    """(fit win rate or None, honest win rate, honest source) of one scorecard row."""
    hon, src = honest_overall(ref), "전체"
    fit = None
    if key is None:
        return fit, hon, src
    o = ref["overall"]["fit"]
    syms = list(ref.get("symbols") or SYMS)
    if cut == "strategy":
        s = ref["strategies"].get(key)
        if s:
            fit = s.get("win")
            hon, src = strategy_honest(ref, key)
    elif cut == "member":
        m = ref_of_order(ref, key)
        if m:
            fit = m.get("win")
            hon, src = strategy_honest(ref, m["strategy"])
    elif cut == "coin":
        if key in syms:
            fit = _pair_win(o.get("by_sym", {}).get(str(syms.index(key))))[0]
    elif cut == "side":
        fit = _pair_win(o.get("by_side", {}).get(key))[0]
    elif cut == "reg5":
        fit = _pair_win(o.get("by_reg5", {}).get(key))[0]
    elif cut == "hb":
        fit = _pair_win(o.get("by_hb", {}).get(key))[0]
    elif cut == "stop":
        fit = (ref.get("stops", {}).get(key) or {}).get("win")
    elif cut == "entry":
        fit = _members_win(ref, "entry", key)
    elif cut == "invert":
        fit = _members_win(ref, "invert", key == "1")
    return fit, hon, src


def ref_of_order(ref: dict, order) -> Optional[dict]:
    """The reference of a setting by the paper bot's number (member_order counts from 1; the reference's
    ``members`` from 0, livecheck.ref_member)."""
    o = _int(order)
    return None if o is None else (ref.get("members") or {}).get(str(o - 1))


def row_label(ref: dict, cut: str, key: Optional[str]) -> str:
    if key is None:
        return "모름(기록 없음)"
    if cut == "member":
        m = ref_of_order(ref, key)
        if not m:
            return f"세팅 #{key}"
        return (f"{m['strategy']} {LC.KO_TF.get(m['tf'], m['tf'])} · {stop_ko(m.get('stop'))} · "
                f"{ENTRY_KO.get(m.get('entry'), m.get('entry'))}" + (" · 방향 반대" if m.get("invert") else "")
                + f" (#{key})")
    if cut == "coin":
        return LC.coin(key)
    if cut == "side":
        return LC.KO_SIDE.get(int(key), key)
    if cut == "reg5":
        names = ref.get("reg5_names") or []
        i = int(key)
        return names[i] if 0 <= i < len(names) else key
    if cut == "hb":
        h = int(key) * 4
        return f"{h:02d}~{h + 4:02d}시"
    if cut == "stop":
        return stop_ko(key)
    if cut == "entry":
        return ENTRY_KO.get(key, key)
    if cut == "invert":
        return "방향 반대로" if key == "1" else "방향 그대로"
    return key


def ref_mismatch(run_config: Optional[dict], ref: dict) -> str:
    """'' when the paper bot's running config (its combo_run record) has the reference's settings, else why not."""
    if not run_config or not isinstance(run_config.get("members"), list):
        return ""
    ms = run_config["members"]
    if len(ms) != len(ref["members"]):
        return f"세팅 수가 다름(페이퍼 봇 {len(ms)}개, 기준표 {len(ref['members'])}개)"
    for j, m in enumerate(ms):
        x = ref["members"].get(str(j)) or {}
        if (m.get("strategy"), m.get("tf")) != (x.get("strategy"), x.get("tf")) \
                or (m.get("stop") and stop_name(m["stop"]) != x.get("stop")):
            return f"세팅 #{j}가 다름"
    return ""


# ====================================================================== reading the bots (read-only)
def open_ro(path: str) -> Optional[sqlite3.Connection]:
    """livecheck.open_ro (mode=ro, immutable when a WAL file has no writer) with query_only on: no statement on this
    connection can write."""
    conn = LC.open_ro(path)
    if conn is not None:
        conn.execute("PRAGMA query_only = ON")
    return conn


def entered_signals(conn, account: str = ACCOUNT) -> dict:
    """{(entry minute, symbol): signal} of the ENTERED outcomes (the paper engine records the entry at the step it
    entered: the trade's entry_time)."""
    out = {}
    try:
        rows = conn.execute("SELECT step_ts, symbol, data FROM outcomes WHERE account_id = ? AND status = 'ENTERED' "
                            "ORDER BY id", (account,)).fetchall()
    except sqlite3.Error:
        return out
    for ts, sym, data in rows:
        try:
            out[(int(ts), sym)] = json.loads(data).get("signal") or {}
        except (ValueError, TypeError, AttributeError):
            continue
    return out


def member_order(meta: dict) -> Optional[int]:
    """The setting's number as the paper bot counts it (from 1): member_order, else the label's '#N'
    (livecheck.build_card)."""
    order = _int(meta.get("member_order"))
    if order is None and "#" in str(meta.get("member", "")):
        order = _int(str(meta["member"]).split("#")[1].split("~")[0])
    return order


def read_paper(conn, ref: dict, account: str = ACCOUNT) -> list:
    """The account's closed trades (livecheck.paper_trades), each with its setting, regime, KST block, stop type,
    entry style and invert (from its ENTERED signal and the reference's members)."""
    trades = LC.paper_trades(conn, account)
    sigs = entered_signals(conn, account)
    for t in trades:
        meta = (sigs.get((t["entry_time"], t["symbol"])) or {}).get("meta") or {}
        dims = meta.get("rdims") or {}
        t["member"] = meta.get("member")
        t["order"] = member_order(meta)
        t["reg5"] = _int(dims.get("reg5"))
        t["hb"] = _int(dims.get("hb"))
        if t["hb"] is None:
            t["hb"] = kst_hb(t["entry_time"])
        m = LC.ref_member(ref, t["order"], t["strategy"], t["tf"])
        if m is None:
            t["order"] = None                          # not a setting of the reference (the config changed)
        m = m or {}
        t["stop"] = stop_name(meta.get("rstop")) or m.get("stop")
        t["entry"] = m.get("entry")
        t["invert"] = m.get("invert")
    return trades


def live_roe(et: dict) -> Optional[float]:
    """An executor trade's net ROE: P&L over its margin (qty x entry price / leverage)."""
    try:
        margin = float(et["qty"]) * float(et["entry_price"]) / float(et["leverage"])
        return float(et["pnl"]) / margin if margin > 0 else None
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def exec_follow(infos: list, paper: list) -> dict:
    """{executor name: {paper trade id: {"live_roe", "paper_roe", "win"}}} of the executor's closed trades matched to
    the paper trade they followed (livecheck.match_paper); None when its database cannot be read."""
    out: dict = {}
    for ex in infos:
        conn = open_ro(ex.db)
        if conn is None:
            out[ex.name] = None
            continue
        got = {}
        try:
            for et in LC.exec_trades(conn):
                if et.get("exit_ts") is None or et.get("pnl") is None:
                    continue
                pt = LC.match_paper(et, paper, ex.account)
                if pt is None:
                    continue
                got[pt["id"]] = {"live_roe": live_roe(et), "paper_roe": float(pt["roe"]), "pnl": float(et["pnl"]),
                                 "win": float(et["pnl"]) > 0}
        finally:
            conn.close()
        out[ex.name] = got
    return out


# ====================================================================== 1. the scorecard
def key_of(cut: str, t: dict) -> Optional[str]:
    if cut == "strategy":
        return t.get("strategy") or None
    if cut == "member":
        return None if t.get("order") is None else str(t["order"])
    if cut == "coin":
        return t["symbol"]
    if cut == "side":
        return str(int(t["side"]))
    if cut == "reg5":
        return None if t.get("reg5") is None else str(t["reg5"])
    if cut == "hb":
        return str(t["hb"])
    if cut == "stop":
        return t.get("stop")
    if cut == "entry":
        return t.get("entry")
    if cut == "invert":
        return None if t.get("invert") is None else ("1" if t["invert"] else "0")
    raise ValueError(cut)


def stats(trades: list) -> dict:
    n = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    lost = [float(t["roe"]) for t in trades if t["pnl"] <= 0]
    return {"n": n, "wins": wins, "win": (wins / n) if n else None,
            "avg_roe": statistics.fmean(float(t["roe"]) for t in trades) if n else None, "losses": n - wins,
            "loss_roe_median": statistics.median(lost) if lost else None, "pnl": sum(float(t["pnl"]) for t in trades),
            "tfs": tfs_of(trades)}


def exec_cols(trades: list, follow: dict) -> dict:
    """Per executor, over the row's trades it followed: n, wins, average live and paper net ROE, live - paper."""
    out = {}
    for name, got in (follow or {}).items():
        if got is None:
            continue
        xs = [got[t["id"]] for t in trades if t["id"] in got]
        both = [x for x in xs if x["live_roe"] is not None]
        live = statistics.fmean(x["live_roe"] for x in both) if both else None
        paper = statistics.fmean(x["paper_roe"] for x in both) if both else None
        out[name] = {"n": len(xs), "wins": sum(1 for x in xs if x["win"]), "pnl": sum(x.get("pnl", 0.0) for x in xs),
                     "live_roe": live, "paper_roe": paper, "leak": (live - paper) if both else None}
    return out


def _order(cut: str, ref: dict, key: Optional[str]):
    if key is None:
        return (1, 0, "")
    if cut == "member":
        return (0, int(key), "")
    if cut == "coin":
        syms = list(ref.get("symbols") or SYMS)
        return (0, syms.index(key) if key in syms else 99, key)
    if cut == "side":
        return (0, -int(key), "")
    if cut in ("reg5", "hb", "invert"):
        return (0, int(key), "")
    if cut == "entry":
        return (0, 0 if key == "now" else 1, key)
    return (0, 0, key)


def table(trades: list, ref: dict, cut: str, follow: Optional[dict] = None) -> list:
    """The rows of one cut. The strategy table lists every reference strategy (none traded yet: 0)."""
    groups: dict = {}
    for t in trades:
        groups.setdefault(key_of(cut, t), []).append(t)
    if cut == "strategy":
        for name in ref["strategies"]:
            groups.setdefault(name, [])
    fam = family_size(ref, cut)
    rows = []
    for key, ts in groups.items():
        st = stats(ts)
        fit, hon, src = expect(ref, cut, key)
        word, p = verdict(st["n"], st["wins"], hon, fam)
        label = with_tf(key, st["tfs"]) if cut == "strategy" and key else row_label(ref, cut, key)
        rows.append({"cut": cut, "key": key, "label": label, **st, "fit": fit, "honest": hon,
                     "honest_src": src, "p": p, "status": word, "family": fam, "exec": exec_cols(ts, follow)})
    if cut == "strategy":
        rows.sort(key=lambda r: (-r["n"], r["key"]))
    else:
        rows.sort(key=lambda r: _order(cut, ref, r["key"]))
    return rows


def overall(trades: list, ref: dict, follow: Optional[dict] = None) -> dict:
    """The whole account: against fit / honest / break-even, and the last 20 and 40 trades against the reference's
    rolling 5th percentiles (fit and honest). Its status uses the strategy table's bar (0.05 / 27 for "확실히 나쁨"):
    it is looked at again every week."""
    st = stats(trades)
    fit, hon = float(ref["overall"]["fit"]["win"]), honest_overall(ref)
    fam = family_size(ref, "strategy")
    word, p = verdict(st["n"], st["wins"], hon, fam)
    by_exit = sorted(trades, key=lambda t: (t["exit_time"], t["id"]))
    roll = {}
    for w in (20, 40):
        if len(by_exit) >= w:
            wins = sum(1 for t in by_exit[-w:] if t["pnl"] > 0)
            f5 = int(ref["overall"]["fit"][f"rolling{w}_wins"]["p5"])
            h5 = int(ref["overall"]["honest"][f"rolling{w}_wins"]["p5"])
            roll[w] = {"wins": wins, "fit_p5": f5, "honest_p5": h5}
    return {"cut": "overall", "key": "all", "label": "전체", **st, "fit": fit, "honest": hon, "honest_src": "전체",
            "break_even": float(ref.get("break_even_win") or 0.776), "p": p, "status": word, "family": fam,
            "roll": roll, "exec": exec_cols(trades, follow)}


def scorecard(trades: list, ref: dict, follow: Optional[dict] = None, cuts=CUTS) -> dict:
    return {"overall": overall(trades, ref, follow), "cuts": {c: table(trades, ref, c, follow) for c in cuts}}


def bad_rows(card: dict) -> list:
    """The "확실히 나쁨" rows that make the weekly message loud: the whole account and the strategy table (both at
    0.05 / 27). The other tables show their own bar in ``score`` only: with nine tables looked at every week, a bar
    per table would ring by luck far too often."""
    rows = [card["overall"]] + list(card["cuts"].get("strategy", []))
    return [r for r in rows if r["status"] == BAD]


def roll_line(o: dict) -> list:
    out = []
    for w, r in sorted(o.get("roll", {}).items()):
        if r["wins"] < r["honest_p5"]:
            how = "드물게 낮음"
        elif r["wins"] < r["fit_p5"]:
            how = "맞춘 기간보다 낮음, 처음 보는 기간 기준 보통"
        else:
            how = "정상 범위"
        out.append(f"최근 {w}번 {wr(r['wins'], w)} → {how} (하위 5%: 맞춘 {r['fit_p5']}승 · 처음 보는 기간 "
                   f"{r['honest_p5']}승)")
    return out


def overall_lines(o: dict, head: str = "전체") -> list:
    if not o["n"]:
        return [f"{head}: 아직 닫힌 거래 없음"]
    st = o["status"] + (f"({p_txt(o['p'])})" if o["p"] is not None else "")
    out = [f"{head}: {wr(o['wins'], o['n'])} · 손익 {LC.usd(o['pnl'])} · 평균 순ROE {roe_txt(o['avg_roe'])}",
           f"기준: 맞춘 {o['fit']:.0%} · 처음 보는 기간 {o['honest']:.0%} · 본전 {o['break_even']:.1%} → {st}"]
    out += roll_line(o)
    if o["n"] < CHECK_N:
        out.append(f"첫 진짜 점검은 거래 {CHECK_N}번(지금 {o['n']}번). 그 전 차이는 대부분 운입니다.")
    return out


def table_lines(rows: list, cut: str, execs: list, show_empty: bool = False) -> list:
    """One cut as fixed-width text (Korean characters count double)."""
    shown = [r for r in rows if r["n"] or show_empty]
    if not shown:
        return [f"[{CUT_KO[cut]}] 아직 거래 없음"]
    names = [(ex.name, ex.label) for ex in execs]
    lw = max(10, min(44, max(_w(r["label"]) for r in shown)))
    head = (_pad("이름", lw) + _pad("거래", 5, True) + _pad("승", 5, True) + _pad("승률", 6, True)
            + _pad("평균ROE", 9, True) + _pad("진거래", 7, True) + _pad("진ROE중간", 11, True)
            + _pad("맞춘", 6, True) + _pad("처음보는", 10, True) + "  " + _pad("상태", 20))
    for _n, label in names:
        head += "  " + _pad(f"{label} 실제-페이퍼", 18)
    out = [f"[{CUT_KO[cut]}]", head]
    any_overall = False
    for r in shown:
        hon = pct(r["honest"]) + ("*" if r["honest_src"] == "전체" else "")
        any_overall = any_overall or r["honest_src"] == "전체"
        st = "거래 없음" if not r["n"] else r["status"] + (f"({p_txt(r['p'])})" if r["p"] is not None else "")
        ln = (_pad(r["label"][:44], lw) + _pad(r["n"], 5, True) + _pad(r["wins"], 5, True)
              + _pad(pct(r["win"]), 6, True)
              + _pad(roe_txt(r["avg_roe"]), 9, True) + _pad(r["losses"], 7, True)
              + _pad(roe_txt(r["loss_roe_median"]), 11, True) + _pad(pct(r["fit"]), 6, True) + _pad(hon, 10, True)
              + "  " + _pad(st, 20))
        for name, _label in names:
            e = (r.get("exec") or {}).get(name)
            if not e or not e["n"]:
                cell = "-"
            elif e["leak"] is None:
                cell = f"{e['n']}번"
            else:
                cell = f"{e['n']}번 {e['leak'] * 100:+.1f}%p"
            ln += "  " + _pad(cell, 18)
        out.append(ln.rstrip())
    hidden = len(rows) - len(shown)
    if hidden:
        out.append(f"(거래 없는 줄 {hidden}개는 뺐습니다)")
    fam = rows[0]["family"] if rows else 1
    out.append(f"이 표의 \"확실히 나쁨\" 기준: p < 0.05 / {fam} = {ALPHA / fam:.4f}")
    if any_overall:
        out.append(f"* 처음 보는 기간 거래가 {HONEST_MIN_N}번 미만이라 전체 승률을 씀")
    return out


READ_HOW = (
    "읽는 법",
    "- 상태: 실거래 승 수를 '처음 보는 기간'(2020-24에만 맞춘 쌍둥이의 2025-26) 승률과 비교합니다. p는 그 승률이 "
    "맞을 때 이만큼 적게 이길 확률입니다(작을수록 운으로 보기 어려움).",
    f"- {SMALL}: 거래 {SMALL_N}번 미만. 판단하지 않습니다.",
    f"- {WATCH}: p<0.05. " + LUCK_NOTE,
    f"- {BAD}: p가 0.05를 표의 줄 수로 나눈 값보다 작음(매매법 표는 0.05/27 = 0.0019). 여러 줄을 함께 본 운을 빼도 나쁩니다.",
    f"- {OK}: 기대 범위 안.",
    "- 맞춘: 전체 기간에 맞춘 백테스트 승률(낙관). 처음보는: 처음 보는 기간 승률(정직). 본전은 77.6%입니다.",
    "- 실제-페이퍼: 실행기가 따라간 같은 거래에서 실제 순ROE - 페이퍼 순ROE(%p, 증거금 대비). -면 비용·미끄러짐으로 샌 것.",
)


# ====================================================================== 2. candidates
def cells_of(trades: list) -> dict:
    """{(kind, key tuple): trades} of every candidate cell a trade falls in."""
    out: dict = {}
    for t in trades:
        s, sym, side = t.get("strategy") or "?", t["symbol"], int(t["side"])
        keys = [("strategy", (s,)), ("strategy_coin", (s, sym)), ("strategy_side", (s, side)),
                ("coin_side", (sym, side)), ("hb", (int(t["hb"]),))]
        if t.get("reg5") is not None:
            keys.append(("strategy_reg5", (s, int(t["reg5"]))))
        for k in keys:
            out.setdefault(k, []).append(t)
    return out


def cell_id(kind: str, key: tuple) -> str:
    return ":".join([kind] + [str(x) for x in key])


def _reg5_name(ref: dict, v) -> str:
    names = ref.get("reg5_names") or []
    return names[v] if isinstance(v, int) and 0 <= v < len(names) else str(v)


def cell_label(ref: dict, kind: str, key: tuple, tfs=()) -> str:
    """The cell in the owners' words; a strategy with the Korean timeframes its live trades in the cell had."""
    s = with_tf(key[0], tfs) if kind.startswith("strategy") else ""
    if kind == "strategy":
        return s
    if kind == "strategy_coin":
        return f"{s} {LC.coin(key[1])}"
    if kind == "strategy_side":
        return f"{s} {LC.KO_SIDE.get(key[1], key[1])}"
    if kind == "strategy_reg5":
        return f"{s} · BTC 4시간 '{_reg5_name(ref, key[1])}' 장세"
    if kind == "coin_side":
        return f"모든 매매법 {LC.coin(key[0])} {LC.KO_SIDE.get(key[1], key[1])}"
    if kind == "hb":
        return f"모든 매매법 한국 시간 {key[0] * 4:02d}~{key[0] * 4 + 4:02d}시"
    return cell_id(kind, key)


def question(ref: dict, kind: str, key: tuple, tfs=()) -> str:
    """The research question a ledger row carries (Korean, ready to run as a backtest)."""
    if kind == "strategy":
        return f"{with_tf(key[0], tfs)} 손보기(손절·진입 방식 바꾸기, 또는 끄기): {QUESTION_TAIL}"
    if kind == "strategy_reg5":
        return f"BTC 4시간 '{_reg5_name(ref, key[1])}' 장세에서 {with_tf(key[0], tfs)} 끄기: {QUESTION_TAIL}"
    if kind == "hb":
        return f"한국 시간 {key[0] * 4:02d}~{key[0] * 4 + 4:02d}시에 모든 매매법 새 진입 끄기: {QUESTION_TAIL}"
    return f"{cell_label(ref, kind, key, tfs)} 끄기: {QUESTION_TAIL}"


def cell_expect(ref: dict, kind: str, key: tuple) -> tuple[float, Optional[float], float, str]:
    """(rate tested against, fit rate or None, honest rate, its source). The lower of the honest rate and the cell's
    fit rate; the fit rate only when the reference has HONEST_MIN_N trades in the cell."""
    o = ref["overall"]["fit"]
    syms = list(ref.get("symbols") or SYMS)
    fit, fit_n = None, 0
    if kind.startswith("strategy"):
        hon, src = strategy_honest(ref, key[0])
        s = ref["strategies"].get(key[0]) or {}
        if kind == "strategy":
            fit, fit_n = s.get("win"), int(s.get("trades") or 0)
        elif kind == "strategy_coin" and key[1] in syms:
            fit, fit_n = _pair_win((s.get("by_sym") or {}).get(str(syms.index(key[1]))))
        elif kind == "strategy_side":
            fit, fit_n = _pair_win((s.get("by_side") or {}).get(str(key[1])))
        elif kind == "strategy_reg5":
            fit, fit_n = _pair_win((s.get("by_reg5") or {}).get(str(key[1])))
    else:
        hon, src = honest_overall(ref), "전체"
        if kind == "hb":
            fit, fit_n = _pair_win(o.get("by_hb", {}).get(str(key[0])))
    if fit is not None and fit_n >= HONEST_MIN_N and float(fit) < hon:
        return float(fit), fit, hon, f"맞춘 기간 이 칸 {fit_n}번"
    return hon, fit, hon, f"처음 보는 기간 {src}"


KIND_PREF = ("strategy_coin", "strategy_side", "strategy_reg5", "strategy", "coin_side", "hb")   # most specific first


def find_candidates(trades: list, ref: dict) -> dict:
    """The weekly pass: every cell with CAND_MIN_N live trades is tested; the ones at p < 0.05 are candidates.
    A cell inside a flagged strategy is kept only when it is more lopsided (smaller p) than the strategy itself.
    Flagged cells made of exactly the same trades are one candidate: the most specific cell (KIND_PREF), the others
    named in its question (the live trades cannot tell them apart; the backtest can)."""
    tested, ids = [], {}
    for (kind, key), ts in cells_of(trades).items():
        if kind not in CELL_KINDS:
            continue                                   # the fixed rules are never candidates
        n = len(ts)
        if n < CAND_MIN_N:
            continue
        wins = sum(1 for t in ts if t["pnl"] > 0)
        p0, fit, hon, src = cell_expect(ref, kind, key)
        p = binom_cdf(wins, n, p0)
        tfs = tfs_of(ts)
        cid = cell_id(kind, key)
        ids[cid] = frozenset(t["id"] for t in ts)
        tested.append({"cell": cid, "kind": kind, "key": list(key), "label": cell_label(ref, kind, key, tfs), "n": n,
                       "wins": wins, "expected": p0, "fit": fit, "honest": hon, "expected_src": src, "p": p,
                       "question": question(ref, kind, key, tfs), "same": []})
    m = len(tested)
    flagged = [c for c in tested if c["p"] < ALPHA]
    parent = {c["key"][0]: c["p"] for c in flagged if c["kind"] == "strategy"}
    by_trades: dict = {}
    for c in flagged:
        if c["kind"] in ("strategy_coin", "strategy_side", "strategy_reg5") and c["key"][0] in parent \
                and c["p"] >= parent[c["key"][0]]:
            continue
        by_trades.setdefault(ids[c["cell"]], []).append(c)
    keep = []
    for cs in by_trades.values():
        cs.sort(key=lambda c: (KIND_PREF.index(c["kind"]), c["p"]))
        c = cs[0]
        c["same"] = [x["label"] for x in cs[1:]]
        if c["same"]:
            c["question"] += f" 같은 거래가 보인 다른 칸도 함께 비교: {', '.join(c['same'])}."
        c["family"] = m
        c["survives"] = c["p"] < ALPHA / max(1, m)
        keep.append(c)
    keep.sort(key=lambda c: c["p"])
    return {"tested": m, "flagged": keep, "luck": m * ALPHA, "cells": {c["cell"]: c for c in tested}}


def evidence(cells: dict, ref: dict, cell: str) -> dict:
    """A ledger cell's live evidence now (any number of trades); ``cells``: cells_of(trades)."""
    kind, *rest = cell.split(":")
    for (k, key), ts in cells.items():
        if k == kind and [str(x) for x in key] == rest:
            wins = sum(1 for t in ts if t["pnl"] > 0)
            p0, _fit, _hon, _src = cell_expect(ref, k, key)
            return {"n": len(ts), "wins": wins, "expected": p0, "p": binom_cdf(wins, len(ts), p0)}
    return {"n": 0, "wins": 0, "expected": None, "p": None}


def rule_a(ev: Optional[dict]) -> bool:
    return bool(ev) and int(ev.get("n") or 0) >= ADOPT_MIN_N and ev.get("p") is not None and ev["p"] < ALPHA


# ====================================================================== liveimprove.db
SCHEMA = """
-- one row per scorecard line of a weekly pass (the dashboard reads the latest week)
CREATE TABLE IF NOT EXISTS snapshots (
    week TEXT NOT NULL,             -- KST date of the weekly pass (YYYY-MM-DD)
    cut TEXT NOT NULL,              -- overall | strategy | member | coin | side | reg5 | hb | stop | entry | invert
    cell TEXT NOT NULL,             -- the row: strategy name, setting number (from 1, as the paper bot counts),
                                    -- BTCUSDT, 1 / -1, 0-4, 0-5, atr2, now, 0 / 1 ('?': not known)
    label TEXT NOT NULL,            -- the row in Korean
    n INTEGER NOT NULL,             -- live paper trades, wins, win rate, average net ROE, losses, their median net ROE
    wins INTEGER NOT NULL,
    win REAL,
    avg_roe REAL,
    losses INTEGER NOT NULL,
    loss_roe_median REAL,
    fit_win REAL,                   -- the reference's fit win rate (optimistic)
    honest_win REAL,                -- the honest unseen 2025-26 win rate the status is tested against
    honest_src TEXT,                -- '전체' or '이 매매법 N번'
    p REAL,                         -- one-sided binomial p (NULL: fewer than 10 trades)
    family INTEGER,                 -- rows of the table ("확실히 나쁨" below 0.05 / family)
    status TEXT NOT NULL,           -- 표본 작음 | 기대 안 | 주의 | 확실히 나쁨
    exec TEXT NOT NULL DEFAULT '{}',-- JSON {executor: {n, wins, live_roe, paper_roe, leak}} on the trades it followed
    PRIMARY KEY (week, cut, cell)
);
-- one row per weekly pass
CREATE TABLE IF NOT EXISTS weeks (
    week TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    since INTEGER,                  -- first paper trade counted (ms UTC)
    trades INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    tested INTEGER NOT NULL,        -- candidate cells tested
    flagged INTEGER NOT NULL,       -- ... at p < 0.05
    new_items TEXT NOT NULL,        -- JSON list of the ledger ids this pass added
    level TEXT NOT NULL,
    text TEXT NOT NULL,             -- the Telegram message
    sent INTEGER
);
-- the improvement ledger: one row per candidate cell, its status set by hand only (ledger set)
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cell TEXT NOT NULL UNIQUE,      -- kind:key, e.g. strategy_coin:F5_BOX_RSI:SOLUSDT
    kind TEXT NOT NULL,             -- strategy | strategy_coin | strategy_reg5 | strategy_side | coin_side | hb
    label TEXT NOT NULL,
    found TEXT NOT NULL,            -- KST date found
    found_ts INTEGER NOT NULL,
    n INTEGER NOT NULL,             -- live evidence when found
    wins INTEGER NOT NULL,
    expected REAL NOT NULL,         -- the win rate it was tested against
    expected_src TEXT NOT NULL,
    p REAL NOT NULL,
    family INTEGER NOT NULL,        -- cells tested in that pass
    question TEXT NOT NULL,         -- the research question (Korean)
    status TEXT NOT NULL,           -- 발견 | 백테스트 시험 | 그림자 시험 | 채택 | 기각
    status_ts INTEGER NOT NULL,
    rule_b INTEGER NOT NULL DEFAULT 0,  -- the owners confirmed (b): the backtest improved 2020-24 and 2025-26
    rule_c INTEGER NOT NULL DEFAULT 0,  -- the owners confirmed (c): the shadow ran long enough, not worse
    latest TEXT NOT NULL DEFAULT '{}',  -- JSON {ts, n, wins, expected, p}: the evidence at the last pass
    note TEXT NOT NULL DEFAULT ''       -- the last note
);
CREATE TABLE IF NOT EXISTS ledger_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item INTEGER NOT NULL,          -- ledger.id
    ts INTEGER NOT NULL,
    day TEXT NOT NULL,              -- KST date
    old TEXT,                       -- NULL: found by the weekly pass
    new TEXT NOT NULL,
    note TEXT NOT NULL,
    who TEXT
);
"""


def open_out(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def ledger_rows(conn) -> list:
    if conn is None:
        return []
    try:
        cur = conn.execute("SELECT * FROM ledger ORDER BY id")
    except sqlite3.Error:
        return []
    cols = [c[0] for c in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        try:
            d["latest"] = json.loads(d.get("latest") or "{}")
        except ValueError:
            d["latest"] = {}
        out.append(d)
    return out


def ledger_log(conn, item: int) -> list:
    try:
        return conn.execute("SELECT day, old, new, note FROM ledger_log WHERE item = ? ORDER BY id", (item,)).fetchall()
    except sqlite3.Error:
        return []


def _who() -> str:
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or ""


def ledger_add(conn, flagged: list, now_ms: int) -> list:
    """New cells become 발견 rows (a cell already in the ledger is left as it is). Returns the new rows."""
    day = kst_date(now_ms)
    new = []
    for c in flagged:
        if conn.execute("SELECT 1 FROM ledger WHERE cell = ?", (c["cell"],)).fetchone():
            continue
        latest = {"ts": now_ms, "n": c["n"], "wins": c["wins"], "expected": c["expected"], "p": c["p"]}
        cur = conn.execute(
            "INSERT INTO ledger (cell, kind, label, found, found_ts, n, wins, expected, expected_src, p, family, "
            "question, status, status_ts, latest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c["cell"], c["kind"], c["label"], day, now_ms, c["n"], c["wins"], c["expected"], c["expected_src"], c["p"],
             c["family"], c["question"], "발견", now_ms, json.dumps(latest)))
        conn.execute("INSERT INTO ledger_log (item, ts, day, old, new, note, who) VALUES (?,?,?,?,?,?,?)",
                     (cur.lastrowid, now_ms, day, None, "발견",
                      f"주간 점검이 찾음: {wr(c['wins'], c['n'])}, 기대 {c['expected']:.0%}, {p_txt(c['p'])} "
                      f"(본 칸 {c['family']}개)", "liveimprove"))
        new.append(dict(c, id=cur.lastrowid, status="발견", latest=latest, found=day))
    conn.commit()
    return new


def ledger_refresh(conn, trades: list, ref: dict, now_ms: int) -> None:
    """Every ledger row's live evidence now (its status is never touched)."""
    cells = cells_of(trades)
    for row in ledger_rows(conn):
        ev = evidence(cells, ref, row["cell"])
        conn.execute("UPDATE ledger SET latest = ? WHERE id = ?", (json.dumps(dict(ev, ts=now_ms)), row["id"]))
    conn.commit()


class LedgerError(ValueError):
    """A status change the ledger refuses (message in Korean)."""


def set_status(conn, item: int, status: str, note: str, now_ms: Optional[int] = None, backtest_ok: bool = False,
               shadow_ok: bool = False, shadow_trades: Optional[int] = None, who: Optional[str] = None) -> dict:
    """The only way a ledger status changes: by hand, along FLOW, with a note. 채택 needs the adoption rule: (a) from
    the latest live evidence, (b) and (c) confirmed by the owners (``backtest_ok`` / ``shadow_ok``), and the shadow run
    of (c) long enough (two weeks in 그림자 시험, or ``shadow_trades`` >= 20)."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    row = next((r for r in ledger_rows(conn) if r["id"] == int(item)), None)
    if row is None:
        raise LedgerError(f"장부에 #{item}이 없습니다(python -m paperbot.liveimprove ledger list)")
    new = ALIASES.get(status.strip(), status.strip())
    if new not in STATUSES:
        raise LedgerError(f"상태는 {', '.join(STATUSES)} 중 하나입니다")
    if not (note or "").strip():
        raise LedgerError("메모(--note)를 꼭 적습니다: 무엇을 보고 바꾸는지")
    old = row["status"]
    if new == old:
        raise LedgerError(f"#{item}은 이미 '{old}'입니다")
    if new not in FLOW[old]:
        allowed = ", ".join(FLOW[old]) or "없음(끝난 항목)"
        raise LedgerError(f"'{old}' 다음은 {allowed}만 됩니다")
    rule_b = int(row["rule_b"]) or int(bool(backtest_ok))
    rule_c = int(row["rule_c"])
    if new == "발견":                                  # reopened: the owners' confirmations start over
        rule_b = rule_c = 0
    if new == "그림자 시험" and not backtest_ok:
        raise LedgerError("그림자 시험은 백테스트가 2020-24와 2025-26 둘 다 좋아졌을 때만 시작합니다(규칙 b). "
                          "확인했으면 --backtest-ok를 붙입니다")
    if new == "채택":
        missing = []
        if not rule_a(row["latest"]):
            ev = row["latest"] or {}
            missing.append(f"(a) 실거래 증거 부족: 지금 {ev.get('n', 0)}번 {ev.get('wins', 0)}승, {p_txt(ev.get('p')) or 'p 없음'}"
                           f" (필요: {ADOPT_MIN_N}번 이상, p<0.05)")
        if not rule_b:
            missing.append("(b) 백테스트 확인 없음(--backtest-ok)")
        days = (now_ms - int(row["status_ts"])) / LC.DAY
        if not shadow_ok:
            missing.append("(c) 그림자 결과 확인 없음(--shadow-ok: 지금 페이퍼 봇보다 나쁘지 않음)")
        elif days < SHADOW_DAYS and (shadow_trades or 0) < SHADOW_TRADES:
            missing.append(f"(c) 그림자 시험 {days:.0f}일째: 2주 또는 거래 {SHADOW_TRADES}번이 필요합니다"
                           "(--shadow-trades로 그림자 거래 수를 적습니다)")
        if missing:
            raise LedgerError("채택 규칙이 아직 맞지 않습니다:\n" + "\n".join(f"- {m}" for m in missing))
        rule_c = 1
    day = kst_date(now_ms)
    conn.execute("UPDATE ledger SET status = ?, status_ts = ?, rule_b = ?, rule_c = ?, note = ? WHERE id = ?",
                 (new, now_ms, rule_b, rule_c, note.strip(), int(item)))
    conn.execute("INSERT INTO ledger_log (item, ts, day, old, new, note, who) VALUES (?,?,?,?,?,?,?)",
                 (int(item), now_ms, day, old, new, note.strip(), who if who is not None else _who()))
    conn.commit()
    return {"id": int(item), "old": old, "new": new, "day": day}


def next_step(row: dict, full: bool = True) -> str:
    """What the owners do next with a ledger item (``full``: with the command)."""
    i, st = row["id"], row["status"]
    cmd = f"python -m paperbot.liveimprove ledger set {i}"
    if st == "발견":
        return "백테스트로 질문 확인(2020-24, 2025-26 따로)" + (
            f" → 시작하면 {cmd} --status \"백테스트 시험\" --note \"...\"" if full else "")
    if st == "백테스트 시험":
        return "둘 다 좋아지면 그림자 시험, 아니면 기각" + (
            f" → {cmd} --status \"그림자 시험\" --backtest-ok --note \"...\" / {cmd} --status 기각 --note \"...\""
            if full else "")
    if st == "그림자 시험":
        return f"2주 또는 거래 {SHADOW_TRADES}번 뒤 지금 봇과 비교 → 채택 또는 기각" + (
            f" → {cmd} --status 채택 --shadow-ok --note \"...\"" if full else "")
    return "끝난 항목"


def ledger_lines(rows: list, conn=None, full: bool = True) -> list:
    if not rows:
        return ["개선 후보 장부: 아직 비어 있음"]
    opened = [r for r in rows if r["status"] in OPEN]
    out = [f"개선 후보 장부 (열린 것 {len(opened)}개 / 전체 {len(rows)}개)"]
    for r in rows:
        head = f"#{r['id']} [{r['status']}] {r['label']} ({KIND_KO.get(r['kind'], r['kind'])}) · 찾은 날 {r['found']}"
        if not full or r["status"] not in OPEN:
            out.append(head + (f" · 메모: {r['note']}" if r.get("note") else ""))
            continue
        ev = r.get("latest") or {}
        out.append(head)
        out.append(f"   찾을 때: {wr(r['wins'], r['n'])}, 기대 {r['expected']:.0%}, {p_txt(r['p'])} (그 주 본 칸 "
                   f"{r['family']}개)")
        if ev.get("n") is not None:
            out.append(f"   지금: {wr(int(ev.get('wins') or 0), int(ev.get('n') or 0))}"
                       + (f", {p_txt(ev.get('p'))}" if ev.get("p") is not None else "")
                       + (" · 규칙 (a) 맞음" if rule_a(ev) else ""))
        out.append(f"   질문: {r['question']}")
        out.append(f"   다음: {next_step(r)}")
        if conn is not None:
            log = ledger_log(conn, r["id"])
            if len(log) > 1:
                out.append("   기록: " + " / ".join(f"{d} {new}" + (f"({n})" if n and old else "")
                                                   for d, old, new, n in log))
    return out


def save_week(conn, week: str, now_ms: int, since: Optional[int], card: dict, cand: dict, new: list, level: str,
              text: str, sent: Optional[bool]) -> None:
    conn.execute("DELETE FROM snapshots WHERE week = ?", (week,))
    rows = [card["overall"]] + [r for c in CUTS for r in card["cuts"].get(c, []) if r["n"] or c == "strategy"]
    for r in rows:
        conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (week, r["cut"], "?" if r["key"] is None else str(r["key"]), r["label"], r["n"], r["wins"],
                      r["win"], r["avg_roe"], r["losses"], r["loss_roe_median"], r["fit"], r["honest"],
                      r["honest_src"], r["p"], r["family"], r["status"], json.dumps(r.get("exec") or {})))
    o = card["overall"]
    conn.execute("INSERT OR REPLACE INTO weeks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (week, now_ms, since, o["n"], o["wins"], cand["tested"], len(cand["flagged"]),
                  json.dumps([r["id"] for r in new]), level, text, None if sent is None else int(bool(sent))))
    conn.commit()


# ====================================================================== gathering
@dataclass
class Sources:
    db: str = DEFAULT_DB
    paper_db: str = LC.PAPER_DB
    expected: str = str(EXPECTED)
    executors: Optional[list] = None              # None: the executors' configs (livecheck.load_executors)
    combo_config: Optional[str] = None            # the running config (load_ref's guard); None: livecheck's default


def since_ms(day: Optional[str]) -> Optional[int]:
    """--since YYYY-MM-DD: 09:00 KST of that date (the bots' day boundary)."""
    return None if not day else LC.window_of(day)[0]


def _day(s: str) -> str:
    try:
        LC.window_of(s)
    except ValueError:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD로 적습니다(예: 2026-10-19)")
    return s


def gather(src: Sources, since: Optional[int] = None) -> dict:
    """Everything the commands read, read-only: the reference, the paper trades since ``since`` (default: the first),
    the executors' followed trades, and what could not be read."""
    ref = load_ref(src.expected, src.combo_config)
    problems = []
    conn = open_ro(src.paper_db)
    trades, run_cfg = [], None
    if conn is None:
        problems.append(f"페이퍼 봇 DB({src.paper_db})를 못 읽음")
    else:
        try:
            trades = read_paper(conn, ref)
            _ts, run = LC.get_state(conn, "combo_run")
            run_cfg = (run or {}).get("config") if isinstance(run, dict) else None
        finally:
            conn.close()
    why = ref_mismatch(run_cfg, ref)
    if why:
        problems.append(f"기준표가 페이퍼 봇의 지금 설정과 다름({why}): 세팅별 줄과 손절·진입 구분은 믿지 마세요")
    first = min((t["entry_time"] for t in trades), default=None)
    start = since if since is not None else first
    window = [t for t in trades if start is None or t["entry_time"] >= start]
    infos = src.executors if src.executors is not None else LC.load_executors()
    follow = exec_follow(infos, trades)
    return {"ref": ref, "trades": window, "all": trades, "since": start, "infos": infos, "follow": follow,
            "problems": problems}


# ====================================================================== 3. the weekly message
def _strategy_line(r: dict) -> str:
    st = r["status"] + (f"({p_txt(r['p'])})" if r["p"] is not None else "")
    return f"- {r['label']}: {wr(r['wins'], r['n'])} · 손익 {LC.usd(r['pnl'])} · 기대 {r['honest']:.0%} · {st}"


def exec_lines(o: dict, infos: list, follow: Optional[dict] = None) -> list:
    out = []
    for ex in infos:
        if follow is not None and follow.get(ex.name) is None:
            out.append(f"- {ex.label}: 기록 없음(아직 시작 전이거나 읽을 수 없음)")
            continue
        e = (o.get("exec") or {}).get(ex.name)
        if not e or not e["n"]:
            out.append(f"- {ex.label}: 따라간 거래 없음")
            continue
        line = f"- {ex.label}: 따라감 {wr(e['wins'], e['n'])} · 실현 {LC.usd(e['pnl'])}"
        if e["leak"] is not None:
            line += f" · 순ROE가 페이퍼보다 {e['leak'] * 100:+.1f}%p"
        out.append(line)
    return out


def _md(ms: int) -> str:
    return LC.kst(ms, "%m/%d").lstrip("0").replace("/0", "/")


def week_span(now_ms: int) -> tuple[int, int]:
    """The 7 trading days (09:00 KST to 09:00 KST) that ended at the latest 09:00 KST."""
    w1 = LC.window_of(LC.default_day(now_ms))[1]
    return w1 - 7 * LC.DAY, w1


def compose_week(g: dict, card: dict, cand: dict, new: list, ledger: list, now_ms: int) -> tuple[str, str, list]:
    """(level, text, the "확실히 나쁨" rows). First line: '📊 주간 성적표 · 10/13~10/19'; loud ('🚨 …') only when a
    strategy or the whole account is "확실히 나쁨"."""
    from .notify import CRITICAL, INFO
    o = card["overall"]
    bad = bad_rows(card)
    since = g["since"]
    w0, w1 = week_span(now_ms)
    title = f"주간 성적표 · {_md(w0)}~{_md(w1 - LC.DAY)}"
    if bad:
        lines = [f"🚨 {title} · 확실히 나쁨 {len(bad)}개"]
        lines += [f"- {r['label']}: {wr(r['wins'], r['n'])} · 기대 {r['honest']:.0%} · {p_txt(r['p'])}" for r in bad]
        lines.append("끄기 전에 장부 순서(백테스트 → 그림자)를 밟습니다. 두 분이 정합니다.")
    else:
        lines = [f"📊 {title}"]
    for p in g["problems"]:
        lines.append(f"참고: {p}")
    if since is not None and since < w0:
        wk = stats([t for t in g["trades"] if w0 <= t["exit_time"] < w1])
        lines.append(f"이번 주 페이퍼: {wr(wk['wins'], wk['n'])} · 손익 {LC.usd(wk['pnl'])}")
    head = f"시작({_md(since)} {LC.kst(since)})부터" if since is not None else "시작부터"
    lines += overall_lines(o, head)
    rows = [r for r in card["cuts"]["strategy"] if r["n"]]

    def excess(r):                              # wins above (+) or below (-) what the honest rate expects
        return r["wins"] - r["n"] * r["honest"]
    top = sorted([r for r in rows if excess(r) > 0], key=lambda r: -excess(r))[:TOP_N]
    low = sorted([r for r in rows if excess(r) < 0], key=excess)[:TOP_N]
    if top:
        lines += ["", "기대보다 잘하는 매매법"] + [_strategy_line(r) for r in top]
    if low:
        lines += ["", "기대보다 못하는 매매법"] + [_strategy_line(r) for r in low]
    if rows:
        lines.append(f"※ {LUCK_NOTE}")
    if g["infos"]:
        lines += ["", "실거래(따라간 같은 거래, -%p = 비용·미끄러짐)"] + exec_lines(o, g["infos"], g["follow"])
    lines += ["", f"새 개선 후보 {len(new)}개 (본 칸 {cand['tested']}개, 운만으로도 약 {cand['luck']:.1f}개)"]
    for c in new:
        mark = " · 여러 칸 보정 뒤에도 남음" if c.get("survives") else ""
        tag = f"#{c['id']}" if isinstance(c["id"], int) else "(새)"           # a dry run numbers nothing
        lines.append(f"- {tag} {c['label']}: {wr(c['wins'], c['n'])} · 기대 {c['expected']:.0%} · {p_txt(c['p'])}{mark}")
        lines.append(f"  질문: {c['question']}")
    opened = [r for r in ledger if r["status"] in OPEN and r["id"] not in {c["id"] for c in new}]
    if opened:
        lines += ["", f"열린 장부 {len(opened)}개"]
        for r in opened:
            ev = r.get("latest") or {}
            now = f"지금 {wr(int(ev.get('wins') or 0), int(ev.get('n') or 0))}" + (" · 규칙 (a) 맞음" if rule_a(ev) else "")
            lines.append(f"- #{r['id']} [{r['status']}] {r['label']} · {now}")
            lines.append(f"  다음: {next_step(r, full=False)}")
    lines += ["", ADOPT_RULE[0]] + [f"- {x}" for x in ADOPT_RULE[1:4]] + [ADOPT_RULE[4]]
    lines.append("장부 바꾸기: python -m paperbot.liveimprove ledger set 번호 --status ... --note ...")
    lines.append("자세히: python -m paperbot.liveimprove score / ledger list")
    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3880] + "\n…(나머지: python -m paperbot.liveimprove score)"
    return (CRITICAL if bad else INFO), text, bad


# (setting number as the paper bot counts it, coin, side, BTC 4h regime, wins, losses) of the preview's week
PREVIEW_PLAN = ((5, "BTCUSDT", 1, 0, 9, 1), (12, "ETHUSDT", 1, 1, 6, 0), (7, "LTCUSDT", -1, 4, 5, 1),
                (30, "SOLUSDT", -1, 3, 2, 6), (30, "BTCUSDT", 1, 4, 4, 0), (10, "DOGEUSDT", 1, 1, 6, 3),
                (37, "BCHUSDT", -1, 2, 4, 1))


def preview(loud: bool = False, ref: Optional[dict] = None) -> dict:
    """The first Monday's message (10/26 09:30 KST) on a hand-made week of paper trades (net ROE +12.8% a win, -41.8%
    a loss: the reference's averages, on a $400 margin) and the two executors following most of them. No database
    is opened, nothing is sent or written. ``loud``: F10_M2022 wins 3 of 14."""
    ref = ref or load_ref()
    t0 = LC.window_of("2026-10-19")[0]
    now_ms = t0 + 7 * LC.DAY + 30 * LC.MIN
    keyed = []
    for g_i, (order, sym, side, reg5, w, l) in enumerate(PREVIEW_PLAN):
        if loud and order == 10:
            w, l = 3, 11
        n = w + l
        lost = {int((k + 0.5) * n / l) for k in range(l)} if l else set()      # losses spread through the week
        for j in range(n):
            keyed.append(((j + 0.5) / n, g_i, (order, sym, side, reg5, j not in lost)))
    items = [x for _pos, _g, x in sorted(keyed)]
    span = 4 * LC.DAY + 13 * LC.H1                      # Monday 10:00 to Friday 23:00 KST
    trades, bybit, mexc = [], {}, {}
    for i, (order, sym, side, reg5, won) in enumerate(items):
        m = ref_of_order(ref, order)
        t = t0 + LC.H1 + i * span // len(items)
        t -= t % LC.MIN
        roe = 0.128 if won else -0.418
        trades.append({"id": i + 1, "entry_time": t, "exit_time": t + 50 * LC.MIN, "reason": "LOCK" if won else "SL",
                       "pnl": round(400.0 * roe, 2), "roe": roe, "symbol": sym, "side": side,
                       "strategy": m["strategy"], "tf": m["tf"], "member": None, "order": order, "reg5": reg5,
                       "hb": kst_hb(t), "stop": m["stop"], "entry": m["entry"], "invert": m["invert"]})
        if i % 6:                                        # the signal light held some entries back
            bybit[i + 1] = {"live_roe": roe - 0.012, "paper_roe": roe, "pnl": round(40.0 * (roe - 0.012), 2),
                            "win": won}
        if i % 3:
            mexc[i + 1] = {"live_roe": roe - 0.02, "paper_roe": roe, "pnl": round(40.0 * (roe - 0.02), 2), "win": won}
    infos = [LC.ExecInfo(name=n, config="-", unit="-", db="-", light_n=20, light_min=s, exchange=n)
             for n, s in (("bybit", 0.85), ("mexc", 0.90))]
    follow = {"bybit": bybit, "mexc": mexc}
    g = {"ref": ref, "trades": trades, "all": trades, "since": trades[0]["entry_time"], "infos": infos,
         "follow": follow, "problems": []}
    card = scorecard(trades, ref, follow)
    cand = find_candidates(trades, ref)
    new = [dict(c, id=i + 1) for i, c in enumerate(cand["flagged"])]       # as an empty ledger would number them
    level, text, bad = compose_week(g, card, cand, new, [], now_ms)
    return {"level": level, "text": text, "bad": bad, "now_ms": now_ms, "card": card, "cand": cand}


def run_weekly(src: Sources, now_ms: Optional[int] = None, since: Optional[int] = None, dry_run: bool = False,
               notifier=None) -> dict:
    """The Monday pass. Returns {"level", "text", "bad", "new", "sent", "card", "cand"}."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    g = gather(src, since)
    card = scorecard(g["trades"], g["ref"], g["follow"])
    cand = find_candidates(g["trades"], g["ref"])
    week = kst_date(now_ms)
    if dry_run:
        ro = open_ro(src.db) if os.path.exists(src.db) else None
        try:
            ledger = ledger_rows(ro)
        finally:
            if ro is not None:
                ro.close()
        known = {r["cell"] for r in ledger}
        new = [dict(c, id="새") for c in cand["flagged"] if c["cell"] not in known]
        level, text, bad = compose_week(g, card, cand, new, ledger, now_ms)
        return {"level": level, "text": text, "bad": bad, "new": new, "sent": None, "card": card, "cand": cand}
    conn = open_out(src.db)
    try:
        new = ledger_add(conn, cand["flagged"], now_ms)
        ledger_refresh(conn, g["trades"], g["ref"], now_ms)
        ledger = ledger_rows(conn)
        level, text, bad = compose_week(g, card, cand, new, ledger, now_ms)
        n = notifier if notifier is not None else LC._notifier()
        got = n.send(level, text)
        sent = got is not False
        save_week(conn, week, now_ms, g["since"], card, cand, new, level, text, sent)
    finally:
        conn.close()
    return {"level": level, "text": text, "bad": bad, "new": new, "sent": sent, "card": card, "cand": cand}


def run_candidates(src: Sources, now_ms: Optional[int] = None, since: Optional[int] = None,
                   dry_run: bool = False) -> tuple[dict, list, list]:
    """The finder by hand: (finder result, new ledger rows, the ledger). Adds new cells unless ``dry_run``."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    g = gather(src, since)
    cand = find_candidates(g["trades"], g["ref"])
    if dry_run:
        ro = open_ro(src.db) if os.path.exists(src.db) else None
        try:
            ledger = ledger_rows(ro)
        finally:
            if ro is not None:
                ro.close()
        known = {r["cell"] for r in ledger}
        return cand, [dict(c, id="새") for c in cand["flagged"] if c["cell"] not in known], ledger
    conn = open_out(src.db)
    try:
        new = ledger_add(conn, cand["flagged"], now_ms)
        ledger_refresh(conn, g["trades"], g["ref"], now_ms)
        return cand, new, ledger_rows(conn)
    finally:
        conn.close()


# ====================================================================== commands
def _sources(a) -> Sources:
    paper = getattr(a, "paper_db", None)
    if not paper:
        try:                                     # the paper bot's own database (livecheck cmd_run)
            with open(a.combo_config, encoding="utf-8") as fh:
                paper = json.load(fh).get("db")
        except (OSError, ValueError, AttributeError):
            paper = None
    return Sources(db=a.db, paper_db=paper or LC.PAPER_DB, expected=a.expected, combo_config=a.combo_config)


def cmd_score(a) -> int:
    src = _sources(a)
    g = gather(src, since_ms(a.since))
    cuts = CUTS if a.by == "all" else (a.by,)
    card = scorecard(g["trades"], g["ref"], g["follow"], cuts=cuts)
    since = g["since"]
    print(f"매매법 성적표 · 페이퍼 {ACCOUNT}" + (f" · {LC.kst_day(since)} {LC.kst(since)}부터" if since else ""))
    for p in g["problems"]:
        print(f"참고: {p}")
    for ln in overall_lines(card["overall"]):
        print(ln)
    if g["infos"]:
        for ln in exec_lines(card["overall"], g["infos"], g["follow"]):
            print(ln)
    for c in cuts:
        print()
        for ln in table_lines(card["cuts"][c], c, g["infos"], show_empty=(c == "strategy")):
            print(ln)
    print()
    for ln in READ_HOW:
        print(ln)
    return 0


def cmd_candidates(a) -> int:
    src = _sources(a)
    cand, new, ledger = run_candidates(src, since=since_ms(a.since), dry_run=a.dry_run)
    print(f"개선 후보 찾기: 거래 {CAND_MIN_N}번 이상인 칸 {cand['tested']}개를 봄 · p<0.05 {len(cand['flagged'])}개 "
          f"(운만으로도 약 {cand['luck']:.1f}개는 나옴)")
    print(f"고정 규칙은 후보가 아닙니다: {', '.join(FIXED_RULES)}")
    newcells = {c["cell"] for c in new}
    for c in cand["flagged"]:
        tag = "새로" if c["cell"] in newcells else "이미 장부에"
        mark = " · 여러 칸 보정 뒤에도 남음" if c.get("survives") else ""
        print(f"- [{tag}] {c['label']} ({KIND_KO[c['kind']]}): {c['n']}번 {c['wins']}승, 기대 {c['expected']:.0%}"
              f"({c['expected_src']}), {p_txt(c['p'])}{mark}")
        print(f"  질문: {c['question']}")
    if a.dry_run:
        print("(--dry-run: 장부에 쓰지 않았습니다)")
    elif new:
        print(f"장부에 {len(new)}개를 '발견'으로 적었습니다: " + ", ".join(f"#{c['id']}" for c in new))
    print()
    for ln in ADOPT_RULE:
        print(ln)
    return 0


def cmd_ledger(a) -> int:
    if a.lcmd == "list":
        conn = open_ro(a.db) if os.path.exists(a.db) else None
        try:
            for ln in ledger_lines(ledger_rows(conn), conn):
                print(ln)
        finally:
            if conn is not None:
                conn.close()
        print()
        for ln in ADOPT_RULE:
            print(ln)
        return 0
    if not os.path.exists(a.db):
        print(f"{a.db}가 없습니다(아직 주간 점검 전)")
        return 1
    conn = open_out(a.db)
    try:
        r = set_status(conn, a.id, a.status, a.note, backtest_ok=a.backtest_ok, shadow_ok=a.shadow_ok,
                       shadow_trades=a.shadow_trades)
    except LedgerError as exc:
        print(f"바꾸지 않았습니다: {exc}")
        return 2
    finally:
        conn.close()
    print(f"#{r['id']}: {r['old']} → {r['new']} ({r['day']})")
    return 0


def cmd_weekly(a) -> int:
    src = _sources(a)
    out = run_weekly(src, since=since_ms(a.since), dry_run=a.dry_run)
    print(f"[{out['level']}]")
    print(out["text"])
    if a.dry_run:
        print("(--dry-run: 보내지도 쓰지도 않았습니다)")
    elif out["sent"] is False:
        print("텔레그램 전송 실패(기록은 저장함)", file=sys.stderr)
    return 0


def cmd_preview(a) -> int:
    out = preview(loud=a.loud, ref=load_ref(a.expected))
    print(f"[미리 보기: 손으로 만든 한 주 · {out['level']} · 보내지도 쓰지도 않음]")
    print(out["text"])
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.liveimprove", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--db", default=DEFAULT_DB, help="liveimprove.db (its own snapshots and ledger)")
        p.add_argument("--paper-db", default=None, help="the paper bot's database (default: combo.json's db)")
        p.add_argument("--combo-config", default=LC.running_combo_config())
        p.add_argument("--expected", default=str(EXPECTED), help="the backtest reference")
        p.add_argument("--since", type=_day, default=None, help="YYYY-MM-DD: count trades from 09:00 KST of that "
                                                                "date (default: the first trade)")
    s = sub.add_parser("score", help="매매법 성적표 (prints only)")
    common(s)
    s.add_argument("--by", choices=CUTS + ("all",), default="strategy")
    c = sub.add_parser("candidates", help="find candidate cells and add new ones to the ledger")
    common(c)
    c.add_argument("--dry-run", action="store_true", help="print only: nothing written")
    lg = sub.add_parser("ledger", help="the improvement ledger")
    lsub = lg.add_subparsers(dest="lcmd", required=True)
    ll = lsub.add_parser("list")
    ll.add_argument("--db", default=DEFAULT_DB)
    ls = lsub.add_parser("set", help="change one item's status by hand")
    ls.add_argument("id", type=int)
    ls.add_argument("--status", required=True, help=" / ".join(STATUSES))
    ls.add_argument("--note", required=True)
    ls.add_argument("--backtest-ok", action="store_true", help="(b) held: both 2020-24 and 2025-26 improved")
    ls.add_argument("--shadow-ok", action="store_true", help="(c) held: the shadow was not worse")
    ls.add_argument("--shadow-trades", type=int, default=None, help="trades the shadow made (for (c))")
    ls.add_argument("--db", default=DEFAULT_DB)
    w = sub.add_parser("weekly", help="the Monday pass: one Telegram message, snapshot and ledger")
    common(w)
    w.add_argument("--dry-run", action="store_true", help="print only: no Telegram, nothing written")
    pv = sub.add_parser("preview", help="the weekly message on a hand-made week (no database, nothing written)")
    pv.add_argument("--loud", action="store_true", help="the week with a strategy that is surely bad")
    pv.add_argument("--expected", default=str(EXPECTED), help="the backtest reference")
    a = ap.parse_args(argv)
    try:
        return {"score": cmd_score, "candidates": cmd_candidates, "ledger": cmd_ledger, "weekly": cmd_weekly,
                "preview": cmd_preview}[a.cmd](a)
    except LC.RefConfigMismatch as exc:          # the reference is another config's: nothing compared, sent or written
        print(f"{exc}: 성적표·개선 후보·주간 메시지를 만들지 않았어요 (보내지도 쓰지도 않음)")
        return 0 if a.cmd == "weekly" else 1      # the Monday timer: not a failure of the run


if __name__ == "__main__":
    sys.exit(main())
