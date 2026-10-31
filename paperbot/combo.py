"""합친 봇 (combined bot): ONE paper account that trades several strategies, for the order executor to follow.

Owners' rules (2026-10-17): several strategies in one account, the rule bot's default numbers and the candidate
league's custom numbers alike; at most one open position; when two strategies signal at the same moment the better
spot is entered; fixed leverage, BTC 40x and every other coin 30x.

    python -m paperbot.combo run --config /etc/paperbot/combo.json
    python -m paperbot.combo check-config --config /etc/paperbot/combo.json
    python -m paperbot.combo status --db /var/lib/paperbot/combo/combo.db

It is a separate process with its own database; nothing of the rule bot changes (its trading files are pinned for
the 30-day verdict, paperbot/runinfo.py):
- 1m bars: the rule bot's ``live_bars`` in paper3.db (read-only), the bars its own accounts stepped on;
- default-number signals: the rule bot's ``signal_log`` rows (status SUBMITTED) of the member strategies, exactly the
  signals its accounts got (2 x ATR14 stop distance, the reference price read right after the computation, the
  signal's chart context with its entry strength);
- custom-number signals: computed here at each 5m boundary with the same functions the candidate league uses
  (``paramshadow.param_module(name).signals(df, tf, **numbers)`` for the 36, ``research/fullgrid/ds_defs.py``
  ``signals`` for DeepSeek) on the same chart frames as the rule bot (``recorder.build_frames`` for the 36,
  ``dssig.frame`` for DeepSeek), from 5m bars built from those same 1m bars (history from Binance at start);
- the friend's strategy (member ``FRIEND_ROC``, owners 2026-10-24, paperbot/friendsig.py): computed here at each close
  of its timeframe from Binance's closed klines, as research/friendroc/code/frfamily.py computes it;
- its own database (paperbot.store3 schema, paperbot.accounts state): the executor follows it unchanged with
  ``"paper_db": <this db>, "account": "COMBO@mix", "entry_source": "paper"``.

The account (``ComboEngine``: paperbot.engine.PaperEngine with three changes)
- size (``FixedLevPolicy``): leverage fixed per coin (``leverage``: BTCUSDT 40, the rest 30); margin = leverage % of
  equity (``margin: "leverage"``) or a fixed share; a stop-out may cost at most ``max_loss_frac`` (15%) of equity,
  fees and slippage included: a larger size is cut to fit (``loss_cap: "shrink"``) or the entry is refused
  (``"skip"``); the stop must sit inside the liquidation price by max(``liq_buffer_atr`` x ATR, ``liq_buffer_min_frac``
  x price), else the entry is refused (isolated margin: the liquidation distance depends on the leverage only);
- stop (``stop``): ``{"mode": "atr", "atr": 2}`` k x ATR14 of the signal bar (the house stop);
  ``{"mode": "atr_fit", "atr": 2, "min_atr": 1}`` the same, pulled in to the widest stop the leverage allows when it
  does not fit (refused below ``min_atr`` x ATR); ``{"mode": "roe", "roe": 0.5}`` a fixed ROE (-50% at the coin's
  leverage, before costs: BTC 1.25%, others 1.67% of price);
- the take-profit is the house ladder (``ladder``: lock ``first_lock`` net ROE when the best net ROE reaches
  ``first_lock + trigger_gap``, then ``step`` steps; owners: 10% at 11%); or, with ``take_profit_roe`` (the 레인지
  봇, owners 10-26, ``ladder`` null), one fixed take-profit at that net ROE on the fill (exit "TP");
- one position; the signals of one step compete by ``rank`` (default: entry strength score, then the longer
  timeframe, then the member order of the config). The score is the 5-year entry study's quality score of the
  signal's strength features (paperbot/levrule.py: mean quintile 1-5); a signal without one (DeepSeek, a strategy
  without a strength definition) counts as ``no_score`` (3, the middle). The research found no edge in it; it is the
  owners' rule. Every losing candidate is recorded (outcomes: SKIPPED "lower score than entered signal").

Conditions (``when``, owners 2026-10-17: the 5-year fit): a member may trade only some of its signals. ``when`` is a
list of conditions; a signal goes in when ANY of them holds, a condition holds when ALL of its keys do:
``symbol`` (a coin or a list), ``side`` ("long" / "short"), ``session`` (KST hours of the bar close: "asia" 09-17,
"europe" 17-22, "us" 22-06, "dawn" 06-09; one or a list), ``weekend`` (true: KST Saturday/Sunday, false: weekdays),
``btc_trend`` ("with" / "against": the last closed BTC 4h bar's close above / below its EMA(50) agrees with the side
or not, the candidate league's gate g1, ``BtcTrend``). A filtered signal is logged FILTERED and reaches neither account.
When the BTC trend cannot be read (Binance down), a condition that needs it does not hold.

Early exit (``early_exit``, owners 2026-10-17: "추세가 꺾이면 빠른 손절", no switching): with "own", a signal of the
open position's own strategy on its coin in the other direction closes it at the open of the minute that starts at
that signal's bar close; with "any", a signal of any member does. Every member signal counts, inside its conditions
or not. Nothing is entered in that minute (no switch into the other side). Exit reason "REV". Off by default.

A coin-flip twin ``COMBOFLIP@mix`` (``flip_twin``) gets every signal at the same moment with a side drawn from a hash
of the signal: what the same rules earn without the strategies' direction (the yardstick of every other analysis).

Lateness: a signal is submitted before the 1m step that opens at its bar's close (the rule bot's order); one whose
reference price is older than ``max_signal_age_s`` when it would be submitted (a restart's catch-up) is recorded
REJECTED "late" and never traded (the executor would not follow it either). Missed minutes are replayed from
live_bars, so exits and ladder steps stay exact.

No orders are ever sent. The Binance key, if set, is the rule bot's read-only key (leverage brackets, fee rate).
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import hashlib
import json
import math
import os
import sys
import time
import warnings
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

import numpy as np

from .accounts import AccountBook
from .aggregate import Aggregator, TF_MS
from .config import DS200_DEFS, DS200_IDS, DS_WINDOW_5M, V3_STOP_ATR, V3_SYMBOLS, V3_TRADE_TFS, v3_settings
from .engine import PaperEngine
from .ladder import net_roe, roe_price, tighten
from .ladder2 import ComboLadder
from .margin import Brackets, liquidation_price
from .models import Bar, Signal
from .notify import CRITICAL, INFO, WARN, ConsoleNotifier, Notifier
from . import rmember as RM
from .sizing import SizeDecision, tp_from_roe
from .store3 import Store3

VERSION = "combo-v2"
ACCOUNT = "COMBO@mix"
FLIP_ACCOUNT = "COMBOFLIP@mix"
KIND = "combo"
FLIP_KIND = "combo_flip"
DEFAULT_CONFIG = "/etc/paperbot/combo.json"
STATE_KEY = "combo"
MIN = 60_000
FIVE = 300_000
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
STOP_MODES = ("atr", "atr_fit", "roe")
RANK_KEYS = ("score", "timeframe", "order")
LOSS_CAPS = ("shrink", "skip")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES_FILE = os.path.join(ROOT, "candleague", "data", "candidates_owner.json")
DS_DEFS_FILE = os.path.join(ROOT, "research", "fullgrid", "ds_defs.py")
DS_TFS_OF = {d[0]: d[2] for d in DS200_DEFS}
KO_SIDE = {1: "롱", -1: "숏"}
KO_TF = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
KO_EXIT = {"SL": "손절", "LOCK": "계단 익절", "TP": "익절", "LIQ": "강제청산", "HALT": "멈춤 청산", "MANUAL": "수동 청산",
           "REV": "빠른 청산(반대 신호)", "JUDGE": "감독 청산(추세 판단 뒤집힘)", "TIME": "감독 청산(시간 정리)",
           "SWITCH": "전환 전 포지션 정리", "STALE": "잠금 전 시간 정리"}
TIME_HOLD_KO = "보유 한도 청산"      # TIME in a bot with max_hold_bars and no trend supervisor ('VWAP 개선판')
GATES_NOW_KEY = "gates_now"         # state: what the entry gates read for every coin (the live site's VWAP screen)
EARLY_EXITS = (None, "own", "any")
KO_EARLY = {None: "없음(고정 손절과 계단 익절만)", "own": "같은 매매법이 반대 신호를 내면 바로 청산",
            "any": "합친 매매법 중 하나라도 반대 신호를 내면 바로 청산"}
KST_MS = 9 * 3_600_000
H4 = 4 * 3_600_000
BTC_EMA = 50                        # candleague/rulex.py GATE_EMA
SESSIONS = {"asia": (9, 17), "europe": (17, 22), "us": (22, 6), "dawn": (6, 9)}       # KST hours [from, to)
KO_SESSION = {"asia": "아시아(09-17시)", "europe": "유럽(17-22시)", "us": "미국(22-06시)", "dawn": "새벽(06-09시)"}
WHEN_KEYS = ("symbol", "side", "session", "weekend", "btc_trend")
SIDES = {"long": 1, "short": -1}
FRIEND = "FRIEND_ROC"               # the friend's strategy (paperbot/friendsig.py FRIEND), computed by this bot
FRIEND_HIGHER = ("roc_any", "rsi_roc_all", "rsi_roc_1h")   # its member key ``higher`` (friendsig.HIGHER_MODES): the
FRIEND_ONE_HIGHER = {"rsi_roc_1h": ("15m", "30m")}         # first = default; one-higher-bar modes: the member timeframes


class ComboError(ValueError):
    """A configuration the combined bot refuses (message in Korean)."""


# ====================================================================== members
@dataclass(frozen=True)
class Member:
    """One strategy of the account. ``numbers`` None: the rule bot's default numbers (its signal_log rows);
    a dict: custom numbers, computed here."""
    label: str
    kind: str                  # "core" (the 36) | "ds" (DeepSeek) | "friend" (FRIEND_ROC, paperbot/friendsig.py)
    name: str
    tf: str
    numbers: Optional[dict]
    order: int
    pick: Optional[str] = None
    when: Optional[tuple] = None       # conditions (parse_when): ((("symbol", ("SOLUSDT",)), ("side", 1)), ...)
    research: Optional[RM.RSpec] = None   # a setting of the 5-year search (paperbot/rmember.py)
    no_chase: bool = False     # owners 2026-10-19 "고점 추격 롱, 저점 추격 숏 안 하게": chase_check before the entry
    higher: Optional[str] = None   # FRIEND_ROC only (FRIEND_HIGHER): its higher-bar rule, "roc_any" by default

    @property
    def custom(self) -> bool:
        return self.numbers is not None

    @property
    def needs_btc(self) -> bool:
        return any(k == "btc_trend" for c in (self.when or ()) for k, _ in c)

    def describe(self) -> str:
        what = "기본값(규칙봇 신호)" if not self.custom else \
            "커스텀값 " + ", ".join(f"{k}={v}" for k, v in sorted(self.numbers.items()))
        if self.kind == "friend":
            from .friendsig import FRIEND_KO, higher_words
            what = f"{FRIEND_KO}: EMA21·EMA52·RSI26·ROC9, {higher_words(self.tf, self.higher)} (이 봇이 바이낸스 끝난 봉으로 계산)"
        out = f"{self.order}. {self.name} {KO_TF.get(self.tf, self.tf)} - {what}" + (f" [{self.pick}]" if self.pick else "")
        if self.when:
            out += " | 조건: " + " 또는 ".join(describe_condition(c) for c in self.when)
        if self.research:
            out += " | " + RM.describe(self.research)
        if self.no_chase:
            out += " | " + CHASE_KO
        return out

    def allows(self, symbol: str, side: int, bar_close: int, btc: Optional[Callable[[int], Optional[int]]] = None
               ) -> tuple[bool, str]:
        """(trade it, why not). ``btc(bar_close)``: the BTC 4h trend sign (+1 / -1) or None when unknown."""
        if not self.when:
            return True, ""
        sign = btc(bar_close) if (btc is not None and self.needs_btc) else None
        for c in self.when:
            if condition_holds(c, symbol, side, bar_close, sign):
                return True, ""
        if self.needs_btc and sign is None:
            return False, "조건 밖(BTC 4시간 추세를 못 읽음)"
        return False, "조건 밖"


def kst_session(ms: int) -> str:
    hr = ((int(ms) + KST_MS) // 3_600_000) % 24
    for name, (a, b) in SESSIONS.items():
        if (a <= hr < b) if a < b else (hr >= a or hr < b):
            return name
    raise AssertionError(hr)


def us_open_ko(mins: int, pre: int = 0) -> str:
    """The NYSE-open pause in words: 나스닥 개장 뒤 30분 / 나스닥 개장 앞 30분·뒤 30분."""
    parts = ([f"앞 {int(pre)}분"] if pre else []) + ([f"뒤 {int(mins)}분"] if mins else [])
    return "나스닥 개장 " + "·".join(parts)


def us_open_pause(ts: int, mins: int, pre: int = 0) -> str:
    """'' or why minute ts (ms) is inside the NYSE-open pause: from ``pre`` minutes before the open (09:30 New York, DST
    aware, weekdays, not on NYSE full-day holidays) to ``mins`` minutes after it: no new entry then (owners 2026-10-19
    "나스닥 개장하고 30분"; 10-21 night "나스닥 개장전 30분도": pre 30, 22:00~23:00 KST on summer time). Only entries
    stop: the trend judgment, the pullback watch, the supervisor and open positions go on."""
    from datetime import datetime, timezone
    from .sessions import NY, NYSE_HOLIDAYS
    mins, pre = int(mins or 0), int(pre or 0)
    local = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).astimezone(NY)
    if local.weekday() >= 5 or local.strftime("%Y-%m-%d") in NYSE_HOLIDAYS:
        return ""
    since = (local - local.replace(hour=9, minute=30, second=0, microsecond=0)).total_seconds()
    if not -pre * 60 <= since < mins * 60:
        return ""
    if not pre:
        return f"나스닥 개장 뒤 {mins}분 진입 안 함 (뉴욕 09:30 개장)"
    a, b = 9 * 60 + 30 - pre, 9 * 60 + 30 + mins
    return f"{us_open_ko(mins, pre)} 진입 안 함 (뉴욕 {a // 60:02d}:{a % 60:02d}~{b // 60:02d}:{b % 60:02d}, 09:30 개장)"


def kst_weekend(ms: int) -> bool:
    return ((int(ms) + KST_MS) // 86_400_000 + 3) % 7 >= 5          # day 0 (1970-01-01) was a Thursday: +3 -> Monday 0 .. Sunday 6


# no_chase members (owners 2026-10-19 "고점에서 추격 롱, 저점에서 추격 숏은 안 하게"): no long in the top 20% of the coin's
# 7-day range or the top 10% of its 24-hour range (shorts: the bottoms), both windows ending at the last hour closed before
# the signal bar's close, at the signal's reference price. The same test as the owners' check on the rule bot's own entries
# (10-19: the four settings that take it lost almost only on such entries); fewer than 20 of the 24 hours read: no entry.
HOUR_MS = 3_600_000
CHASE_24H, CHASE_24H_MIN, CHASE_24H_HI, CHASE_24H_LO = 24, 20, 0.9, 0.1
CHASE_7D, CHASE_7D_MIN, CHASE_7D_HI, CHASE_7D_LO = 168, 150, 0.8, 0.2
CHASE_KO = "추격 진입 막기(롱은 7일 범위 위 20%·24시간 고점 쪽 10% 안이면, 숏은 아래쪽이면 진입 안 함)"


def chase_hours(conn, symbol: str, bar_close: int) -> dict:
    """{hour index: (high, low)} of the rule bot's 1m bars (paper3.db live_bars) in the 7 days before the hour of
    ``bar_close``."""
    k = int(bar_close) // HOUR_MS
    rows = conn.execute("SELECT ts / 3600000, MAX(high), MIN(low) FROM live_bars WHERE symbol = ? AND ts >= ? AND ts < ? "
                        "GROUP BY ts / 3600000", (symbol, (k - CHASE_7D) * HOUR_MS, k * HOUR_MS)).fetchall()
    return {int(h): (float(hi), float(lo)) for h, hi, lo in rows if hi is not None and lo is not None}


def chase_check(hours: dict, bar_close: int, side: int, price: float) -> tuple[Optional[bool], str]:
    """(True: a chase, why) / (False, '') / (None, why: too few hours to tell)."""
    k = int(bar_close) // HOUR_MS

    def rng(n):
        v = [hours[j] for j in range(k - n, k) if j in hours]
        return (max(a for a, _ in v), min(b for _, b in v), len(v)) if v else None

    r24, r7 = rng(CHASE_24H), rng(CHASE_7D)
    if not (r24 and r24[2] >= CHASE_24H_MIN):
        return None, "추격 판단에 쓸 24시간 1분봉이 모자람"
    p24 = (price - r24[1]) / max(r24[0] - r24[1], 1e-12)
    if side > 0 and p24 >= CHASE_24H_HI:
        return True, f"롱인데 24시간 고점 쪽({p24:.0%} 위치)"
    if side < 0 and p24 <= CHASE_24H_LO:
        return True, f"숏인데 24시간 저점 쪽({p24:.0%} 위치)"
    if r7 and r7[2] >= CHASE_7D_MIN:
        p7 = (price - r7[1]) / max(r7[0] - r7[1], 1e-12)
        if side > 0 and p7 >= CHASE_7D_HI:
            return True, f"롱인데 7일 범위 위 20% 안({p7:.0%} 위치)"
        if side < 0 and p7 <= CHASE_7D_LO:
            return True, f"숏인데 7일 범위 아래 20% 안({p7:.0%} 위치)"
    return False, ""


def condition_holds(cond: tuple, symbol: str, side: int, bar_close: int, btc_sign: Optional[int]) -> bool:
    for k, v in cond:
        if k == "symbol" and symbol not in v:
            return False
        if k == "side" and int(side) != v:
            return False
        if k == "session" and kst_session(bar_close) not in v:
            return False
        if k == "weekend" and kst_weekend(bar_close) != v:
            return False
        if k == "btc_trend" and (btc_sign is None or (btc_sign == int(side)) != (v == "with")):
            return False
    return True


def describe_condition(cond: tuple) -> str:
    parts = []
    for k, v in cond:
        if k == "symbol":
            parts.append("/".join(s.replace("USDT", "") for s in v))
        elif k == "side":
            parts.append("롱만" if v > 0 else "숏만")
        elif k == "session":
            parts.append("/".join(KO_SESSION[s] for s in v))
        elif k == "weekend":
            parts.append("주말(토·일)" if v else "평일")
        elif k == "btc_trend":
            parts.append("BTC 4시간 추세와 같은 방향" if v == "with" else "BTC 4시간 추세와 반대 방향")
    return "(" + " + ".join(parts) + ")" if parts else "(항상)"


def parse_when(raw, where: str) -> Optional[tuple]:
    """Config ``when`` -> a hashable tuple of conditions (each a tuple of (key, value) in WHEN_KEYS order).
    None or [] means every signal. Raises ComboError (Korean)."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ComboError(f"{where}: when은 조건 목록([{{...}}, ...])입니다")
    out = []
    for i, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            raise ComboError(f"{where}: when {i}번째 조건이 {{...}} 형식이 아닙니다")
        unknown = sorted(set(c) - set(WHEN_KEYS))
        if unknown:
            raise ComboError(f"{where}: when에 없는 조건 이름 {', '.join(unknown)} (있는 것: {', '.join(WHEN_KEYS)})")
        items = []
        for k in WHEN_KEYS:
            if k not in c:
                continue
            v = c[k]
            if k == "symbol":
                v = (v,) if isinstance(v, str) else tuple(v) if isinstance(v, list) else None
                if not v or any(s not in V3_SYMBOLS for s in v):
                    raise ComboError(f"{where}: when symbol은 규칙봇 6개 코인 중에서({', '.join(V3_SYMBOLS)})")
            elif k == "side":
                v = SIDES.get(v) if isinstance(v, str) else None
                if v is None:
                    raise ComboError(f'{where}: when side는 "long" 또는 "short"입니다')
            elif k == "session":
                v = (v,) if isinstance(v, str) else tuple(v) if isinstance(v, list) else None
                if not v or any(s not in SESSIONS for s in v):
                    raise ComboError(f"{where}: when session은 {', '.join(SESSIONS)} 중에서(한국 시간)")
            elif k == "weekend":
                if not isinstance(v, bool):
                    raise ComboError(f"{where}: when weekend는 true(주말만) 또는 false(평일만)입니다")
            elif k == "btc_trend":
                if v not in ("with", "against"):
                    raise ComboError(f'{where}: when btc_trend는 "with"(같은 방향) 또는 "against"(반대)입니다')
            items.append((k, v))
        out.append(tuple(items))
    return tuple(out) or None


class BtcTrend:
    """The BTC 4h trend of the candidate league's gate g1 (candleague/rulex.py ``gate_g1_arrays``): the close of each
    closed 4h bar against the EMA(50) of closes (pandas ewm span 50, adjust=False, from the first fetched bar), +1 above,
    -1 below, 0 for the first 50 bars. ``sign_at(t)``: the last bar closed at or before t (None when that bar is missing,
    the fetch failed or the EMA is cold). ``fetch()``: Binance BTCUSDT 4h klines, oldest first (rows [open_ms, open,
    high, low, close, ...], the bar still forming included); fetched again only when a newer 4h bar should be there."""

    def __init__(self, fetch: Callable[[], list], now_ms: Callable[[], int]):
        self.fetch, self.now_ms = fetch, now_ms
        self.close_ms = np.zeros(0, np.int64)
        self.sign = np.zeros(0, np.int8)
        self.errors: list[str] = []

    def _load(self) -> None:
        now = self.now_ms()
        rows = [r for r in self.fetch() if int(r[0]) + H4 <= now]
        c = np.array([float(r[4]) for r in rows])
        ema, y, a = np.empty(len(c)), 0.0, 2.0 / (BTC_EMA + 1)
        for k in range(len(c)):
            y = c[k] if k == 0 else (1 - a) * y + a * c[k]
            ema[k] = y
        sign = np.sign(c - ema).astype(np.int8)
        sign[~(np.isfinite(c) & np.isfinite(ema))] = 0
        sign[:BTC_EMA] = 0
        self.close_ms = np.array([int(r[0]) + H4 for r in rows], np.int64)
        self.sign = sign

    def sign_at(self, t: int) -> Optional[int]:
        need = int(t) - int(t) % H4                                # the 4h close at or before t
        if not len(self.close_ms) or int(self.close_ms[-1]) < need:
            try:
                self._load()
            except Exception as exc:  # noqa: BLE001  unknown: the conditions that need it do not hold
                self.errors.append(f"BTC 4h klines failed: {type(exc).__name__}: {exc}"[:300])
        j = int(np.searchsorted(self.close_ms, int(t), side="right")) - 1
        if j < 0 or int(self.close_ms[j]) < need or int(self.sign[j]) == 0:
            return None
        return int(self.sign[j])


_DS_MOD: list = []


def ds_defs():
    """research/fullgrid/ds_defs.py, loaded once under a private name (as candleague.candidates.ds_defs)."""
    if not _DS_MOD:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_paperbot_combo_ds_defs", DS_DEFS_FILE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _DS_MOD.append(mod)
    return _DS_MOD[0]


def core_names() -> list[str]:
    from . import sweepsig
    from .sigservice import strategy_names
    return strategy_names(sweepsig.lib())


def params_of(kind: str, name: str) -> list[dict]:
    if kind == "core":
        from .paramshadow import param_module
        return list(param_module(name).PARAMS)
    return [dict(p) for p in ds_defs().DEFS[name]]


def default_numbers(kind: str, name: str) -> dict:
    return {p["name"]: p["default"] for p in params_of(kind, name)}


def _same(a, b) -> bool:
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return list(a if isinstance(a, (list, tuple)) else [a]) == list(b if isinstance(b, (list, tuple)) else [b])
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def load_picks(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {c["id"]: c for c in data.get("candidates", [])}


def resolve_members(specs: list, picks_file: str = CANDIDATES_FILE, core: Optional[list] = None,
                    allow_empty: bool = False) -> list[Member]:
    """Config ``members`` -> Members. A spec is {"strategy", "tf"} (default numbers), {"strategy", "tf", "numbers"}
    (custom numbers) or {"pick": "<candidate league id>"} (that pick's custom numbers), each with an optional ``when``
    (parse_when). Custom numbers equal to the defaults become a default member (the rule bot's own signals). Raises
    ComboError (Korean) on anything wrong. ``allow_empty`` (the 레인지 봇, owners 10-31: its own entries only): [] is []."""
    if allow_empty and specs == []:
        return []
    if not isinstance(specs, list) or not specs:
        raise ComboError("members(매매법 목록)가 비어 있습니다")
    core = core_names() if core is None else core
    picks = None
    out, seen = [], set()
    for i, sp in enumerate(specs, 1):
        if not isinstance(sp, dict):
            raise ComboError(f"members {i}번째 항목이 {{...}} 형식이 아닙니다")
        unknown = sorted(set(sp) - {"pick", "strategy", "tf", "numbers", "when", "stop", "entry", "invert", "filter",
                                    "disp", "off", "cell", "no_chase", "higher"})
        if unknown:
            raise ComboError(f"members {i}번째 항목에 알 수 없는 이름: {', '.join(unknown)}")
        pick = sp.get("pick")
        if pick:
            if picks is None:
                picks = load_picks(picks_file)
            c = picks.get(pick)
            if c is None:
                raise ComboError(f"커스텀값봇 매매법 {pick}이(가) {picks_file}에 없습니다")
            kind, name, tf, numbers = c["kind"], c["name"], c["tf"], dict(c["combo"])
        else:
            name, tf = sp.get("strategy"), sp.get("tf")
            if not name or not tf:
                raise ComboError(f"members {i}번째 항목에 strategy와 tf가 필요합니다(또는 pick)")
            kind = "friend" if name == FRIEND else ("core" if name in core else ("ds" if name in DS200_IDS else None))
            if kind is None:
                raise ComboError(f"{name}은(는) 규칙봇 36개에도 딥시크 44개에도 없는 매매법입니다")
            numbers = sp.get("numbers")
            if numbers is not None and not isinstance(numbers, dict):
                raise ComboError(f"{name}의 numbers는 {{이름: 값}} 형식입니다")
            if kind == "friend" and numbers is not None:
                raise ComboError(f"{name}은(는) 숫자를 바꾸지 않습니다(친구 규칙 그대로: EMA21·52, RSI26, ROC9)")
        if tf not in V3_TRADE_TFS:
            raise ComboError(f"{name}의 봉 {tf}: 15m/30m/1h/4h만 됩니다")
        if kind == "ds" and tf not in DS_TFS_OF.get(name, ()):
            raise ComboError(f"딥시크 {name}은(는) {tf}에서 돌지 않습니다")
        try:
            research = RM.parse_spec(sp, f"{name} {tf}")
        except RM.RSpecError as exc:
            raise ComboError(str(exc)) from None
        if research is not None and numbers is None:
            raise ComboError(f"{name} {tf}: 연구 설정(stop/entry/filter/off)은 numbers와 함께 적습니다")
        if numbers is not None:
            want = default_numbers(kind, name)
            unknown = sorted(set(numbers) - set(want))
            if unknown:
                raise ComboError(f"{name}에 없는 숫자 이름: {', '.join(unknown)} (있는 것: {', '.join(sorted(want))})")
            full = {**want, **numbers}
            # a research member always computes its own signals (the search's), even on the default numbers
            numbers = None if (research is None and all(_same(full[k], want[k]) for k in want)) else full
        higher = sp.get("higher")
        if higher is not None and kind != "friend":
            raise ComboError(f"{name}: higher는 {FRIEND}에만 씁니다(상위 봉 확인 방식)")
        if kind == "friend":
            higher = FRIEND_HIGHER[0] if higher is None else higher
            if higher not in FRIEND_HIGHER:
                raise ComboError(f"{name}의 higher는 {', '.join(FRIEND_HIGHER)} 중 하나입니다")
            if higher in FRIEND_ONE_HIGHER and tf not in FRIEND_ONE_HIGHER[higher]:
                raise ComboError(f"{name} {tf}: higher {higher}는 {'/'.join(FRIEND_ONE_HIGHER[higher])}에서만 씁니다")
        key = (kind, name, tf, json.dumps(numbers, sort_keys=True), research, higher)
        if key in seen:
            raise ComboError(f"{name} {tf}가 같은 숫자로 두 번 들어 있습니다(조건이 여럿이면 when 목록에 함께 적습니다)")
        seen.add(key)
        label = pick or (f"{name}@{tf}" if numbers is None else f"{name}@{tf}~" +
                         hashlib.sha1(json.dumps(numbers, sort_keys=True).encode()).hexdigest()[:6])
        if kind == "friend" and higher != FRIEND_HIGHER[0]:
            label = f"{name}@{tf}~{higher}"           # the default rule keeps the plain label
        if research is not None:
            label = f"{name}@{tf}#{i}~{RM.spec_tag(research)}"
            if sp.get("when"):
                raise ComboError(f"{label}: 연구 설정에는 when을 함께 쓰지 않습니다(filter/off를 씁니다)")
        when = parse_when(sp.get("when"), label)
        no_chase = sp.get("no_chase", False)
        if not isinstance(no_chase, bool):
            raise ComboError(f"{label}: no_chase는 true 또는 false입니다")
        if no_chase and research is not None:
            raise ComboError(f"{label}: 연구 설정에는 no_chase를 함께 쓰지 않습니다(off의 pos/posside를 씁니다)")
        out.append(Member(label=label, kind=kind, name=name, tf=tf, numbers=numbers, order=i, pick=pick, when=when,
                          research=research, no_chase=no_chase, higher=higher))
    return out


# ====================================================================== config
@dataclass
class ComboConfig:
    paper_db: str
    db: str
    members: list
    leverage: dict = field(default_factory=lambda: {"BTCUSDT": 40, "default": 30})
    margin: Any = "leverage"            # "leverage": margin = leverage % of equity; a number: that share
    initial_equity: float = 1000.0
    max_loss_frac: float = 0.15
    loss_cap: str = "shrink"
    stop: dict = field(default_factory=lambda: {"mode": "atr", "atr": V3_STOP_ATR})
    liq_buffer_atr: float = 1.0
    liq_buffer_min_frac: float = 0.002
    ladder: Optional[dict] = field(default_factory=lambda: {"first_lock": 0.10, "step": 0.05, "trigger_gap": 0.01})
    take_profit_roe: Optional[float] = None  # '레인지 봇' (owners 10-26, paperbot/rangebot.py): one fixed take-profit at
                                             # this net ROE (0.10 = +10 % after both sides' fees and slippage, the
                                             # ladder's definition), resting at its price; no ladder (``ladder`` null)
    rank: tuple = RANK_KEYS
    no_score: float = 3.0
    flip_twin: bool = True
    early_exit: Optional[str] = None    # None | "own" | "any" (the class docstring)
    early_exit_until_lock: bool = False  # the early exit only before the first lock (owners 10-19: the check on the rule
                                         # bot's entries; once +10% is locked the ladder alone decides)
    macro_blackout_min: Optional[int] = None   # no entry from N minutes before to N minutes after a US macro release
                                               # (data/macro_events.csv, paperbot/events.py): owners 2026-10-18 "30"
    us_open_pause_min: Optional[int] = None    # no entry from the NYSE open (09:30 New York, weekdays, not on NYSE
                                               # holidays) to N minutes after it: owners 2026-10-19 "나스닥 개장하고 30분"
    us_open_pre_min: Optional[int] = None      # ... and from N minutes before the open: owners 2026-10-21 night
                                               # "나스닥 개장전 30분도 진입금지" (22:00~23:00 KST on summer time)
    no_weekend: bool = False            # no entry on KST Saturday / Sunday (owners 2026-10-18); a position runs on
    symbols: tuple = V3_SYMBOLS
    poll_s: float = 2.0
    max_signal_age_s: float = 150.0
    picks_file: str = CANDIDATES_FILE
    brackets_file: Optional[str] = None
    telegram: bool = True
    name: str = ""                      # shown in the messages: "[합친 봇 페이퍼 <name>]" (two paper bots side by side)
    trend: Optional[dict] = None        # 추세판단 봇 (owners 10-21, paperbot/trendbot.py): the trend judge, entry checks,
                                        # pullback entry, pauses and the supervisor; None = none of it (every other bot)
    vote_gate: Optional[dict] = None    # 'VWAP 개선판' (owners 10-23, paperbot/entrygates.py): {"tf": "4h", "vote_min": 3}
                                        # no entry when the trend judges' vote on the last closed tf bar is against
    vol_gate: Optional[dict] = None     # ... {"atr": 14, "days": 30, "q": 0.8}: no entry when the signal bar's ATR% is
                                        # above its 30-day 80 % point; None = off (both)
    max_hold_bars: Optional[int] = None  # ... a position open this many bars of its own timeframe (30m: 96 = 48 h, 1h: 96
                                         # = 96 h) is closed at the next minute's open (exit "TIME"); None = no limit
    unlocked_close_min: Optional[int] = None  # owners 10-26 (VWAP shadow, research/opentime A3): a position not at its
                                              # first lock this many minutes after its entry is closed at that minute's
                                              # open (exit "STALE"); None = off (every live bot)
    adx_gate: Optional[dict] = None     # '친구 매매법' (owners 10-24, paperbot/friendsig.py): {"tf": "4h", "min": 20} no entry
                                        # when ADX(14) of the last closed tf bar is below min (research F4)
    quiet_gate: Optional[dict] = None   # ... {"bars": 20, "max_ratio": 0.64}: no entry when the signal bar's volume is above
                                        # 0.64 x the mean of the 20 bars before it (research V); None = off (both)
    range: Optional[dict] = None        # '레인지 봇' (owners 10-26, paperbot/rangebot.py): one signal at a time, the coin's and
                                        # BTC's 1h supertrend on the side, a 0.2 ATR pullback within 1 h at the next 5m open

    @classmethod
    def from_dict(cls, d: dict) -> "ComboConfig":
        d = dict(d)
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ComboError(f"알 수 없는 설정 항목: {', '.join(unknown)}")
        for k in ("rank", "symbols"):
            if k in d and d[k] is not None:
                d[k] = tuple(d[k])
        return cls(**d)

    @classmethod
    def from_file(cls, path: str) -> "ComboConfig":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    # ---- values
    @property
    def tag(self) -> str:
        return f"[합친 봇 페이퍼 {self.name}]" if self.name else "[합친 봇 페이퍼]"

    def lev_of(self, symbol: str) -> int:
        return int(self.leverage.get(symbol, self.leverage.get("default", 30)))

    def margin_frac(self, lev: int) -> float:
        return lev / 100.0 if self.margin == "leverage" else float(self.margin)

    @property
    def stop_mode(self) -> str:
        return str(self.stop.get("mode", "atr"))

    @property
    def stop_atr(self) -> float:
        return float(self.stop.get("atr", V3_STOP_ATR))

    @property
    def stop_net(self) -> bool:
        """``stop: {"mode": "roe", "roe": 0.5, "net": true}``: the loss at the stop is the ROE after fees and slippage of
        both sides (the ladder's definition); without "net" it is the price move x leverage (before costs)."""
        return self.stop_mode == "roe" and self.stop.get("net") is True

    @property
    def ladder_spec(self) -> Optional[ComboLadder]:
        return ComboLadder.of(self.ladder)

    def _net_stop_fits(self, roe: float, lev: int) -> bool:
        """A net ROE stop can sit inside the liquidation price at all: its distance from the fill (roe / lev - round
        trip + entry slippage) plus the buffer (``liq_buffer_min_frac``) is inside the isolated liquidation distance at
        the six coins' lowest first-tier maintenance rate (0.4 %, BTC / ETH). The sizing checks every entry against the
        coin's real brackets and refuses (records) one that does not fit; the stop is never moved."""
        s = v3_settings()
        return roe / lev - s.round_trip_cost + s.slippage_frac + float(self.liq_buffer_min_frac) < 1 / lev - 0.004

    def problems(self) -> list[str]:
        out = []
        if not self.paper_db:
            out.append("paper_db(규칙봇 paper3.db 경로)가 비어 있습니다")
        if not self.db:
            out.append("db(합친 봇 자기 DB 경로)가 비어 있습니다")
        elif self.paper_db and os.path.abspath(self.db) == os.path.abspath(self.paper_db):
            out.append("db는 paper3.db와 다른 파일이어야 합니다(합친 봇은 paper3.db를 읽기만 합니다)")
        for k, v in self.leverage.items():
            if not (isinstance(v, int) and 1 <= v <= 125):
                out.append(f"leverage {k}: 1~125 정수여야 합니다")
        if self.margin != "leverage" and not (isinstance(self.margin, (int, float)) and 0 < self.margin <= 1):
            out.append('margin은 "leverage"(배수%) 또는 0~1 사이 비율입니다')
        if not (isinstance(self.initial_equity, (int, float)) and self.initial_equity > 0):
            out.append("initial_equity는 0보다 커야 합니다")
        if not 0 < float(self.max_loss_frac) <= 1:
            out.append("max_loss_frac은 0~1 사이입니다(15% = 0.15)")
        if self.loss_cap not in LOSS_CAPS:
            out.append('loss_cap은 "shrink" 또는 "skip"입니다')
        if self.stop_mode not in STOP_MODES:
            out.append(f"stop.mode는 {', '.join(STOP_MODES)} 중 하나입니다")
        elif self.stop_mode == "roe":
            r = self.stop.get("roe")
            if not (isinstance(r, (int, float)) and 0 < r < 1):
                out.append("stop.roe는 0~1 사이 비율입니다(-50% = 0.5)")
            elif "net" in self.stop and not isinstance(self.stop["net"], bool):
                out.append("stop.net은 true(수수료 포함) 또는 false입니다")
            elif self.stop_net:
                rt = v3_settings().round_trip_cost
                worst = max(self.lev_of(s) for s in self.symbols) if self.symbols else 1
                if not float(r) / worst > 2 * rt:
                    out.append(f"stop.roe {float(r):.0%}(수수료 포함)는 {worst}배에서 수수료보다 작아 손절 자리가 없습니다")
                elif not self._net_stop_fits(float(r), worst):
                    out.append(f"stop.roe {float(r):.0%}(수수료 포함)는 {worst}배에서 강제청산 가격보다 멀어 "
                               f"모든 진입이 거절됩니다")
        elif not (0 < self.stop_atr <= 10):
            out.append("stop.atr는 0~10입니다")
        unknown = sorted(set(self.stop) - {"mode", "atr", "min_atr", "roe", "net"})
        if unknown:
            out.append(f"stop에 알 수 없는 이름: {', '.join(unknown)}")
        lad = self.ladder_spec
        if self.take_profit_roe is not None:
            tp = self.take_profit_roe
            if isinstance(tp, bool) or not (isinstance(tp, (int, float)) and 0 < tp < 1):
                out.append("take_profit_roe(고정 익절)는 0~1 사이 비율입니다(+10% = 0.1)")
            if self.ladder is not None:
                out.append("take_profit_roe(고정 익절)를 쓰면 ladder는 null입니다(계단 익절과 같이 쓰지 않음)")
        elif lad is None:
            out.append("ladder에 first_lock, step, trigger_gap이 필요합니다")
        if lad is not None:
            out += lad.problems()
            unknown = sorted(set(self.ladder) - {"first_lock", "step", "trigger_gap", "next_trigger", "next_gap"})
            if unknown:
                out.append(f"ladder에 알 수 없는 이름: {', '.join(unknown)}")
        bad = [r for r in self.rank if r not in RANK_KEYS]
        if bad or not self.rank:
            out.append(f"rank는 {', '.join(RANK_KEYS)}의 순서입니다")
        if not 30 <= float(self.max_signal_age_s) <= 170:
            out.append("max_signal_age_s는 30~170초입니다(실행기는 180초 넘은 진입을 따라가지 않습니다)")
        bad = [s for s in self.symbols if s not in V3_SYMBOLS]
        if bad:
            out.append(f"symbols: 규칙봇 6개 코인만 됩니다({', '.join(bad)})")
        if self.macro_blackout_min is not None and not (isinstance(self.macro_blackout_min, int)
                                                        and 0 < self.macro_blackout_min <= 240):
            out.append("macro_blackout_min은 1~240분(정수) 또는 null입니다")
        if self.us_open_pause_min is not None and not (isinstance(self.us_open_pause_min, int)
                                                       and not isinstance(self.us_open_pause_min, bool)
                                                       and 0 < self.us_open_pause_min <= 240):
            out.append("us_open_pause_min은 1~240분(정수) 또는 null입니다")
        if self.us_open_pre_min is not None and not (isinstance(self.us_open_pre_min, int)
                                                     and not isinstance(self.us_open_pre_min, bool)
                                                     and 0 < self.us_open_pre_min <= 240):
            out.append("us_open_pre_min은 1~240분(정수) 또는 null입니다")
        if self.early_exit not in EARLY_EXITS:
            out.append('early_exit는 null(끔), "own"(같은 매매법의 반대 신호), "any"(아무 매매법의 반대 신호)입니다')
        if not isinstance(self.early_exit_until_lock, bool):
            out.append("early_exit_until_lock은 true 또는 false입니다")
        elif self.early_exit_until_lock and not self.early_exit:
            out.append("early_exit_until_lock은 early_exit를 켰을 때만 씁니다")
        if self.trend is not None:
            from .trendbot import config_problems
            out += config_problems(self)
        if self.vote_gate is not None or self.vol_gate is not None:
            from .entrygates import gate_problems
            tfs = [str(m.get("tf", "")) for m in self.members if isinstance(m, dict)]
            out += gate_problems(self.vote_gate, self.vol_gate, tfs)
        if self.adx_gate is not None or self.quiet_gate is not None:
            from .friendsig import gate_problems as friend_gate_problems
            out += friend_gate_problems(self.adx_gate, self.quiet_gate)
        if self.range is not None:
            from .rangebot import config_problems as range_problems
            out += range_problems(self)
        if self.max_hold_bars is not None and not (isinstance(self.max_hold_bars, int)
                                                   and not isinstance(self.max_hold_bars, bool)
                                                   and 1 <= self.max_hold_bars <= 1000):
            out.append("max_hold_bars는 1~1000봉(정수) 또는 null입니다(그 매매법 봉 기준, 예: 96)")
        if self.unlocked_close_min is not None and not (isinstance(self.unlocked_close_min, int)
                                                        and not isinstance(self.unlocked_close_min, bool)
                                                        and 1 <= self.unlocked_close_min <= 10080):
            out.append("unlocked_close_min은 1~10080분(정수) 또는 null입니다(예: 4시간 → 240)")
        return out


def settings_of(cfg: ComboConfig, **over):
    """The engine rules: paper v4's (fees, slippage, bust, no drawdown halt) with the combined bot's ladder, loss cap
    and liquidation buffer. Its own version string, so its ledger never mixes with the rule bot's."""
    kw = dict(version=VERSION, initial_equity=float(cfg.initial_equity), symbols=tuple(cfg.symbols),
              symbol_priority=tuple(cfg.symbols), liq_buffer_atr_mult=float(cfg.liq_buffer_atr),
              liq_buffer_min_frac=float(cfg.liq_buffer_min_frac), max_loss_frac=float(cfg.max_loss_frac),
              bust_below=0.01 * float(cfg.initial_equity))
    if cfg.take_profit_roe is not None:
        # one take-profit at the net ROE (paperbot/sizing.tp_from_roe on the fill), filled at its price as a maker
        kw.update(tp_mode="fixed", default_tp_roe=float(cfg.take_profit_roe))
    else:
        lad = cfg.ladder
        kw.update(ladder_first_lock=float(lad["first_lock"]), ladder_step=float(lad["step"]),
                  ladder_trigger_gap=float(lad["trigger_gap"]))
    kw.update(over)
    return v3_settings(**kw)


# ====================================================================== sizing and the account
def _round_down(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step + 1e-9) * step


def liq_distance(side: int, entry: float, lev: int, notional: float, brackets: Brackets) -> float:
    """Liquidation distance as a fraction of the entry price for an isolated position at ``lev`` of ``notional``."""
    qty = notional / entry
    lp = liquidation_price(side, qty, entry, notional / lev, brackets.for_notional(notional))
    return abs(entry - lp) / entry


class FixedLevPolicy:
    """Leverage fixed per coin; margin = leverage % (or a fixed share) of equity; loss at the stop capped; stop
    inside liquidation. Same checks and loss formula as paperbot/sizing.size_position, one candidate only."""
    name = "combo"

    def __init__(self, settings, cfg: ComboConfig):
        self.s = settings
        self.c = cfg

    def size(self, equity, sig, entry, brackets, spec) -> SizeDecision:
        side, stop = sig.side, sig.stop_price
        if equity <= 0:
            return SizeDecision(False, reasons=["no equity"])
        if (entry - stop) * side <= 0:
            return SizeDecision(False, reasons=["stop on wrong side of entry"])
        lev = self.c.lev_of(sig.symbol)
        step, min_notional = spec.get("qty_step", 0.0), spec.get("min_notional", 0.0)
        reasons: list[str] = []
        qty = _round_down(equity * self.c.margin_frac(lev) * lev / entry, step)
        bracket = brackets.for_notional(qty * entry)
        if lev > bracket.max_leverage:
            caps = [t.notional_cap for t in brackets.tiers if t.max_leverage >= lev]
            if not caps:
                return SizeDecision(False, reasons=[f"{lev}x: no bracket allows it"])
            qty = _round_down(min(qty, max(caps) / entry), step)
            reasons.append(f"{lev}x: size cut to the bracket that allows it (${max(caps):,.0f})")
        exit_px = stop * (1 - side * self.s.slippage_frac)
        per = abs(entry - stop) + abs(stop - exit_px) + entry * self.s.taker_fee + exit_px * self.s.taker_fee
        cap = self.s.max_loss_frac * equity
        if qty * per > cap + 1e-9:
            if self.c.loss_cap == "skip":
                return SizeDecision(False, reasons=reasons + [
                    f"{lev}x: stop loss {qty * per:.2f} > {self.s.max_loss_frac:.0%} of equity"])
            q2 = _round_down(cap / per, step)
            reasons.append(f"{lev}x: size cut so the stop loses at most {self.s.max_loss_frac:.0%} of equity "
                           f"({qty * per:.2f} -> {q2 * per:.2f})")
            qty = q2
        notional = qty * entry
        if qty <= 0 or notional < min_notional:
            return SizeDecision(False, reasons=reasons + [f"{lev}x: below minimum order size"])
        margin = notional / lev
        bracket = brackets.for_notional(notional)
        liq = liquidation_price(side, qty, entry, margin, bracket)
        buffer = self.s.liq_buffer_min_frac * entry
        atr_mult = float(sig.meta.get("liq_buffer_atr", self.s.liq_buffer_atr_mult))    # research pct/swing: 0
        if sig.atr is not None:
            buffer = max(buffer, atr_mult * sig.atr)
        if (stop - liq) * side < buffer:
            return SizeDecision(False, reasons=reasons + [f"{lev}x: stop {stop:.6g} too close to liq {liq:.6g}"])
        return SizeDecision(True, "combo", lev, margin, qty, liq, qty * per, reasons)

    def take_profit(self, sig, entry, dec):
        if self.c.take_profit_roe is None:
            return math.nan               # ladder: no take-profit order
        # the fixed take-profit (레인지 봇): net ROE on the fill at the entry's leverage, both sides' costs counted
        return tp_from_roe(sig.side, entry, dec.leverage, float(self.c.take_profit_roe), round_trip=self.s.round_trip_cost)


def rank_key(cfg: ComboConfig, settings, sig: Signal) -> tuple:
    keys = []
    for r in cfg.rank:
        if r == "score":
            keys.append(-float(sig.score))
        elif r == "timeframe":
            keys.append(-TF_MIN.get(sig.timeframe, 0))
        elif r == "order":
            keys.append(int(sig.meta.get("member_order", 999)))
    pri = settings.symbol_priority
    idx = pri.index(sig.symbol) if sig.symbol in pri else len(pri)
    return tuple(keys) + (idx, sig.strategy_id, sig.timeframe)


class ComboEngine(PaperEngine):
    """PaperEngine with the combined bot's sizing (``FixedLevPolicy``), stop rule (``stop``) and ranking (``rank``)."""

    def __init__(self, settings, brackets, combo: Optional[ComboConfig] = None, **kw):
        if combo is None:
            raise ComboError("ComboEngine needs the combined bot's config")
        kw.pop("policy", None)
        super().__init__(settings, brackets, policy=FixedLevPolicy(settings, combo), **kw)
        self.combo = combo
        self.ladder2 = combo.ladder_spec
        self._exit_on: list[Signal] = []

    def exit_signal(self, sig: Signal) -> None:
        """A member's signal of this minute (entered or not, inside its conditions or not) for the early exit rule."""
        if self.combo.early_exit:
            self._exit_on.append(sig)

    def step(self, bars: dict[str, Bar], funding: Optional[dict[str, float]] = None) -> None:
        """``early_exit``: a signal against the open position (its coin, the other side, a bar closed after the entry;
        "own": the same member) closes it at this minute's open, and this minute enters nothing.
        ``max_hold_bars``: a position open that many bars of its own timeframe is closed at this minute's open ("TIME",
        the research's close of the last minute of its window); a signal of this minute may still enter (the research's
        next trade)."""
        p = self.position
        hold = hold_minutes(self.combo, p.signal.timeframe) if p is not None else None
        if hold and p.symbol in bars and bars[p.symbol].open_time - p.entry_time >= hold * MIN:
            bar = bars[p.symbol]
            ctx = dict(p.signal.meta.get("ctx") or {})
            ctx["exit_why"] = f"{self.combo.max_hold_bars}봉({hold_ko(hold)}) 지남"
            p.signal = replace(p.signal, meta={**p.signal.meta, "ctx": ctx})
            self._close_market(bar.open, bar.open_time, "TIME")
        lim = self.combo.unlocked_close_min
        p = self.position
        if lim and p is not None and p.lock_roe is None and p.symbol in bars and bars[p.symbol].open_time - p.entry_time >= lim * MIN:
            bar = bars[p.symbol]
            ctx = dict(p.signal.meta.get("ctx") or {})
            ctx["exit_why"] = f"{hold_ko(lim)} 안에 첫 잠금에 못 닿음"
            p.signal = replace(p.signal, meta={**p.signal.meta, "ctx": ctx})
            self._close_market(bar.open, bar.open_time, "STALE")
        trig, self._exit_on = self._exit_on, []
        p = self.position
        if trig and p is not None and self.combo.early_exit_until_lock and p.lock_roe is not None:
            trig = []                                   # +10% already locked: the ladder alone decides
        if trig and p is not None and p.symbol in bars:
            own = p.signal.meta.get("member", p.signal.strategy_id)
            hit = [g for g in trig if g.symbol == p.symbol and int(g.side) == -int(p.side) and g.ts + 1 > p.entry_time
                   and (self.combo.early_exit == "any" or g.meta.get("member", g.strategy_id) == own)]
            if hit:
                bar = bars[p.symbol]
                self._close_market(bar.open, bar.open_time, "REV")
                for g in self.pending:
                    self._record(g, "SKIPPED", "early exit this minute", bar.open_time)
                self.pending = []
        super().step(bars, funding)

    def _raise_lock(self, p) -> None:
        """PaperEngine._raise_lock with the config's ladder (paperbot/ladder2.py: the two-part form of 10-19 as well);
        the same best net ROE, funding and order of checks."""
        if self.ladder2 is None or not self.ladder2.two_part:
            return super()._raise_lock(p)
        fund = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
        rt = self.s.round_trip_cost
        best = net_roe(p.side, p.entry_price, p.mfe_price, p.leverage, rt, fund)
        lock = self.ladder2.lock_for(best)
        if lock is None or (p.lock_roe is not None and lock <= p.lock_roe + 1e-12):
            return
        p.stop_price = tighten(p.side, p.stop_price, roe_price(p.side, p.entry_price, p.leverage, lock, rt, fund))
        p.lock_roe = lock

    def _rank_key(self, sig: Signal) -> tuple:
        return rank_key(self.combo, self.s, sig)

    def _try_enter(self, sig: Signal, bar: Bar) -> bool:
        sig, why = self._with_stop(sig, bar)
        if sig is None:
            self._record_reject(why, bar)
            return False
        return super()._try_enter(sig, bar)

    def _record_reject(self, why, bar) -> None:
        sig, text = why
        self._record(sig, "REJECTED", "stop rule", bar.open_time, reasons=[text])

    def _with_stop(self, sig: Signal, bar: Bar):
        c = self.combo
        raw = float(sig.meta.get("ref_price", bar.open))
        lev = c.lev_of(sig.symbol)
        atr = sig.atr
        rstop = sig.meta.get("rstop")
        if rstop and rstop[0] in ("pct", "swing"):
            return self._research_stop(sig, raw, lev, rstop)
        stop_mode, stop_atr = c.stop_mode, c.stop_atr
        if rstop:                                   # research ["atr", k]: the house atr_fit with that k, at least 1 ATR
            stop_mode, stop_atr = "atr_fit", float(rstop[1])
        if stop_mode == "roe" and c.stop_net:
            # the stop loses roe of the margin after both sides' fees and slippage (the ladder's net ROE)
            dist = raw * (float(c.stop["roe"]) / lev - self.s.round_trip_cost)
            if not dist > 0:
                return None, (sig, f"{lev}x: ROE -{float(c.stop['roe']):.0%} is inside the fees")
            rule = f"ROE -{float(c.stop['roe']):.0%} net at {lev}x"
        elif stop_mode == "roe":
            dist = raw * float(c.stop["roe"]) / lev
            rule = f"ROE -{float(c.stop['roe']):.0%} at {lev}x"
        else:
            if atr is None or not atr > 0:
                return None, (sig, "no ATR for the stop")
            dist = stop_atr * atr
            rule = f"{stop_atr:g} x ATR"
            if stop_mode == "atr_fit":
                # the sizing checks the stop against the liquidation price of the FILL (the reference price plus
                # slippage): widest distance from the reference price = fill x L - slippage - buffer (a hair less)
                fill = raw * (1 + sig.side * self.s.slippage_frac)
                notional = self.wallet * c.margin_frac(lev) * lev
                room = liq_distance(sig.side, fill, lev, max(notional, 1.0), self.brackets[sig.symbol]) * fill
                buffer = max(self.s.liq_buffer_min_frac * fill, self.s.liq_buffer_atr_mult * atr)
                widest = (room - abs(fill - raw) - buffer) * (1 - 1e-6)
                if dist > widest:
                    min_atr = 1.0 if rstop else float(c.stop.get("min_atr", 1.0))
                    if widest < min_atr * atr:
                        return None, (sig, f"{lev}x: even {min_atr:g} x ATR does not fit inside liquidation")
                    rule = f"{stop_atr:g} x ATR pulled in to {widest / atr:.2f} x ATR (fits {lev}x)"
                    dist = widest
        return replace(sig, meta={**sig.meta, "stop_dist": dist, "stop_rule": rule}), None

    def _research_stop(self, sig: Signal, raw: float, lev: int, rstop):
        """Research pct / swing stops (ck3.trade_pct): from the fill, pulled in to 0.2 % of the fill inside the
        liquidation price, no ATR buffer. ``meta["rswing"]``: the lowest low / highest high of the swing window."""
        c = self.combo
        fill = raw * (1 + sig.side * self.s.slippage_frac)
        if rstop[0] == "pct":
            frac = float(rstop[1]) / 100.0
            rule = f"{float(rstop[1]):g}% of the fill"
        else:
            sw = sig.meta.get("rswing") or {}
            lv = sw.get("lo") if sig.side > 0 else sw.get("hi")
            if lv is None:
                return None, (sig, "no swing window for the stop")
            frac = max((raw - lv) / raw + 0.001 if sig.side > 0 else (lv - raw) / raw + 0.001, 0.003)
            rule = f"swing {float(rstop[1]):g} bars ({lv:.6g}) +0.1%"
        notional = max(self.wallet * c.margin_frac(lev) * lev, 1.0)
        room = liq_distance(sig.side, fill, lev, notional, self.brackets[sig.symbol]) * fill
        liq = fill - sig.side * room
        stop = RM.pct_stop(sig.side, raw, fill, frac, liq)
        if stop is None:
            return None, (sig, f"{lev}x: the stop does not fit inside liquidation")
        if abs(fill - stop) < frac * fill - 1e-12:
            rule += f", pulled in to {abs(fill - stop) / fill:.3%} (fits {lev}x)"
        dist = sig.side * (raw - stop)              # PaperEngine: stop = reference price - side x stop_dist
        return replace(sig, meta={**sig.meta, "stop_dist": dist, "stop_rule": rule, "liq_buffer_atr": 0.0}), None


def make_cls(cfg: ComboConfig):
    """The engine class AccountBook builds (accounts.AccountBook._make calls it like PaperEngine); the trend bot's
    engine (paperbot/trendbot.py TrendEngine: the supervisor's exits) when the config has ``trend``. The 레인지 봇
    (``range``) uses ComboEngine itself: its fixed take-profit is the settings' (``take_profit_roe``)."""
    if cfg.trend is not None:
        from .trendbot import TrendEngine
        return functools.partial(TrendEngine, combo=cfg)
    return functools.partial(ComboEngine, combo=cfg)


# ====================================================================== signals
def score_of(ctx: Optional[dict], strategy: str, tf: str) -> Optional[float]:
    """The 5-year entry study's quality score (1-5) of a signal's strength features, None when it has none."""
    try:
        from .levrule import quality_score
        s = quality_score((ctx or {}).get("strength"), strategy, tf)["score"]
        return None if s is None else float(s)
    except Exception:  # noqa: BLE001  ranking only: no score -> the middle
        return None


def flip_side(account: str, sig: Signal) -> int:
    h = hashlib.sha256(f"{account}|{sig.strategy_id}|{sig.timeframe}|{sig.symbol}|{sig.ts}".encode()).digest()
    return 1 if h[0] & 1 else -1


def make_signal(cfg: ComboConfig, member: Member, bar_close: int, symbol: str, side: int, atr: float,
                ref: Optional[float], ref_time: Optional[int], delay_ms: Optional[int], ctx: Optional[dict],
                source: str) -> Signal:
    score = score_of(ctx, member.name, member.tf)
    # only the entry strength of the chart context is kept (the rule bot's marks and levels stay in paper3.db): the
    # signal travels in the queue, the pending list and the position of every saved state
    keep = {k: v for k, v in (ctx or {}).items() if k in ("strength", "strength_error", "close")}
    meta = {"stop_dist": cfg.stop_atr * atr, "ref_time": ref_time, "delay_ms": delay_ms, "account": ACCOUNT,
            "member": member.label, "member_order": member.order, "source": source, "score_raw": score,
            "ctx": keep}
    if ref is not None:
        meta["ref_price"] = float(ref)
    return Signal(ts=int(bar_close) - 1, symbol=symbol, timeframe=member.tf, strategy_id=member.name, side=int(side),
                  stop_price=0.0, tier="best", score=cfg.no_score if score is None else score, atr=float(atr),
                  meta=meta)


def rule_rows(conn, cursor: int, members: list[Member], symbols) -> tuple[list[tuple[Member, dict]], int]:
    """New SUBMITTED signal_log rows of the default members (id > cursor) and the new cursor."""
    want = {(m.name, m.tf): m for m in members if not m.custom and m.kind != "friend"}
    top = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM signal_log").fetchone()[0])
    if not want or top <= cursor:
        return [], top
    cur = conn.execute("SELECT id, bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, delay_ms, "
                       "status, data FROM signal_log WHERE id > ? AND id <= ? ORDER BY id", (cursor, top))
    cols = [c[0] for c in cur.description]
    out = []
    for r in cur.fetchall():
        row = dict(zip(cols, r))
        m = want.get((row["strategy"], row["timeframe"]))
        if m is None or row["status"] != "SUBMITTED" or row["symbol"] not in symbols:
            continue
        if row["atr"] is None or row["ref_price"] is None:
            continue
        out.append((m, row))
    return out, top


def rule_signal(cfg: ComboConfig, m: Member, row: dict) -> Signal:
    try:
        data = json.loads(row.get("data") or "{}")
    except ValueError:
        data = {}
    return make_signal(cfg, m, int(row["bar_close"]), row["symbol"], int(row["side"]), float(row["atr"]),
                       row["ref_price"], row.get("ref_time"), row.get("delay_ms"), data.get("ctx"), "rule")


class CustomSignals:
    """Custom-number signals of the custom members, on 5m bars built from the 1m bars the accounts step on (history
    from Binance at start). Same frames and functions as the rule bot (36: ``recorder.build_frames`` on
    ``sigservice.window_5m`` bars; DeepSeek: ``dssig.frame`` on ``config.DS_WINDOW_5M`` bars, BTC's frame for F14_SMT)
    and the candidate league's custom-number signal functions."""

    def __init__(self, members: list[Member], symbols, lib=None, keep_min: int = 0):
        self.members = [m for m in members if m.custom]
        self.symbols = list(symbols)
        self._lib = lib
        self.agg = Aggregator(["5m"])
        # ``keep_min``: 5m bars kept even without a custom member (the 레인지 봇's own entries, paperbot/rangebot.py)
        self.keep = max(self.window_need() + 12 if self.members else 0, int(keep_min))
        self.hist = {s: deque(maxlen=max(self.keep, 1)) for s in self.symbols}
        self._mods: dict = {}
        self.errors: list[str] = []

    @property
    def lib(self):
        if self._lib is None:
            from . import sweepsig
            self._lib = sweepsig.lib()
        return self._lib

    def window(self, m: Member) -> int:
        if m.kind == "ds":
            return DS_WINDOW_5M[m.tf]
        from .sigservice import window_5m
        return window_5m(self.lib, m.tf)

    def window_need(self) -> int:
        return max((self.window(m) for m in self.members), default=0)

    # ---- data
    def bootstrap(self, symbol: str, rows) -> None:
        h = self.hist[symbol]
        for r in rows:
            if not h or int(r[0]) > h[-1][0]:
                h.append((int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

    def add_1m(self, bar: Bar) -> None:
        if not self.keep or bar.symbol not in self.hist:
            return
        for _tf, b5 in self.agg.add(bar):
            h = self.hist[b5.symbol]
            if b5.partial or (h and b5.open_time <= h[-1][0]):
                continue                    # a 5m bar missing minutes is taken from Binance instead (fill_gaps)
            if h and b5.open_time != h[-1][0] + FIVE:
                continue                    # a hole before it: fill_gaps fetches the run of closed 5m bars
            h.append((b5.open_time, b5.open, b5.high, b5.low, b5.close,
                      b5.volume if b5.volume is not None else np.nan))

    def fill_gaps(self, fetch: Callable[[str, int, int], list], boundary: int) -> None:
        """Closed 5m bars from Binance for every coin whose history does not reach ``boundary`` (a start, a gap, a
        5m bar missing minutes). ``fetch(symbol, start, end)``: rows (open_ms, o, h, l, c, v) with open in
        [start, end), as live3.fetch_5m."""
        for sym in self.symbols:
            if self.complete(sym, boundary):
                continue
            h = self.hist[sym]
            start = h[-1][0] + FIVE if h else boundary - self.keep * FIVE
            if boundary - start > self.keep * FIVE:
                h.clear()
                start = boundary - self.keep * FIVE
            try:
                self.bootstrap(sym, fetch(sym, start, boundary))
            except Exception as exc:  # noqa: BLE001  that coin waits for the next boundary
                self.errors.append(f"{sym}: 5m history from Binance failed: {type(exc).__name__}: {exc}"[:300])

    def complete(self, symbol: str, boundary: int) -> bool:
        h = self.hist.get(symbol)
        return bool(h) and h[-1][0] + FIVE == boundary

    def due(self, boundary: int) -> list[Member]:
        return [m for m in self.members if boundary % TF_MS[m.tf] == 0]

    def _cols(self, symbol: str, n: int):
        h = self.hist[symbol]
        a = np.array(list(h)[-n:], dtype=float) if len(h) else np.zeros((0, 6))
        if not len(a):
            return None
        return (a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])

    def _core_mod(self, name: str):
        if name not in self._mods:
            from .paramshadow import param_module
            self._mods[name] = param_module(name)
        return self._mods[name]

    # ---- compute
    def compute(self, boundary: int) -> list[dict]:
        """[{member, symbol, side, atr, ctx}] of the members due at ``boundary`` that fire on the bar just closed.
        Errors are collected in ``self.errors`` (one coin's computation skipped), never raised."""
        out = []
        self._frames = {}             # one chart frame per kind, timeframe and coin at this boundary (each member a copy)
        try:
            for m in self.due(boundary):
                for sym in self.symbols:
                    if not self.complete(sym, boundary):
                        self.errors.append(f"{m.label} {sym}: 5m history incomplete at {boundary}")
                        continue
                    try:
                        got = self._one(m, sym, boundary)
                    except Exception as exc:  # noqa: BLE001  one coin of one member skipped
                        self.errors.append(f"{m.label} {sym}: {type(exc).__name__}: {exc}"[:300])
                        continue
                    if got is not None:
                        out.append(got)
        finally:
            self._frames = {}
        return out

    def frame(self, m: Member, symbol: str, boundary: int):
        key = (m.kind, m.tf, symbol, boundary, self.window(m))
        cache = getattr(self, "_frames", None)
        if cache is not None and key in cache:
            return cache[key].copy()
        df = self._frame(m, symbol, boundary)
        if cache is not None:
            cache[key] = df.copy()
        return df

    def _frame(self, m: Member, symbol: str, boundary: int):
        need = self.window(m)
        cols = self._cols(symbol, need)
        if cols is None or len(cols[0]) < need:
            raise ComboError(f"warm-up: {0 if cols is None else len(cols[0])} of {need} 5m bars")
        if m.kind == "ds":
            from .dssig import frame
            df = frame(*cols, tf=m.tf, lib=self.lib)
        else:
            from .paramshadow import chart_frame
            df = chart_frame(self.lib, cols, m.tf)
        if not len(df):
            raise ComboError(f"no complete {m.tf} bar")
        last_open = int(df["ts"].iloc[-1].value // 1_000_000)
        if last_open + TF_MS[m.tf] != boundary:
            raise ComboError(f"last {m.tf} bar opens at {last_open}, expected {boundary - TF_MS[m.tf]}")
        return df

    def _btc_frame(self, m: Member, boundary: int):
        key = ("btc", m.tf, boundary, self.window(m))
        cache = getattr(self, "_frames", None)
        if cache is not None and key in cache:
            b = cache[key]
            return None if b is None else b.copy()
        b = self._btc_frame_new(m, boundary)
        if cache is not None:
            cache[key] = None if b is None else b.copy()
        return b

    def _btc_frame_new(self, m: Member, boundary: int):
        from .dssig import BTC_TF_BARS, frame
        cols = self._cols("BTCUSDT", self.window(m))
        if cols is None:
            return None
        since = max(int(cols[0][0]), boundary - BTC_TF_BARS * TF_MS[m.tf])
        keep = cols[0] >= since
        return frame(*(c[keep] for c in cols), tf=m.tf, lib=self.lib)

    def _one(self, m: Member, symbol: str, boundary: int) -> Optional[dict]:
        from .entry_marks import _contained
        df = self.frame(m, symbol, boundary)
        numbers = {k: (tuple(v) if isinstance(v, list) else v) for k, v in m.numbers.items()}
        with _contained(), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if m.kind == "core":
                lo, sh = self._core_mod(m.name).signals(df, m.tf, **numbers)
                side = int(bool(np.asarray(lo)[-1])) - int(bool(np.asarray(sh)[-1]))
            else:
                ctx = None
                if symbol != "BTCUSDT" and "BTCUSDT" in self.hist:
                    b = self._btc_frame(m, boundary)
                    ctx = {"BTCUSD": b} if b is not None and len(b) else None
                lo, sh = ds_defs().signals(df, m.tf, m.name, ctx=ctx, coin=symbol[:-1], cache={}, **numbers)
                side = 1 if bool(np.asarray(lo)[-1]) else (-1 if bool(np.asarray(sh)[-1]) else 0)
            atr = float(self.lib.fg.atr(df, 14).to_numpy(float)[-1])
        if not side:
            return None
        if not (math.isfinite(atr) and atr > 0):
            self.errors.append(f"{m.label} {symbol}: no ATR at {boundary}")
            return None
        ctx = {"close": float(df["close"].iloc[-1])}
        if m.kind == "core":
            try:
                from .entry_marks import strength_marks
                st = strength_marks(m.name, df, m.tf, side)
                if st is not None:
                    ctx["strength"] = st
            except Exception as exc:  # noqa: BLE001  ranking only
                ctx["strength_error"] = f"{type(exc).__name__}: {exc}"[:200]
        return {"member": m, "symbol": symbol, "side": side, "atr": atr, "ctx": ctx}


# ====================================================================== the runner
@dataclass
class Queued:
    bar_close: int
    signal: dict          # the Signal as JSON (dataclasses.asdict), so the queue survives a restart


def _sig_from(d: dict) -> Signal:
    return Signal(**d)


class FundingFeed:
    """Funding rates from Binance (public), bucketed to the minute that holds the funding time (paperbot/feed.py)."""

    def __init__(self, rest, symbols, start: int, every_ms: int = 600_000):
        self.rest, self.symbols, self.every_ms = rest, list(symbols), every_ms
        self.since = {s: start for s in self.symbols}
        self.rates: dict[int, dict[str, float]] = {}
        self.last = 0
        self.errors = 0

    def poll(self, now: int) -> None:
        if self.rest is None or now - self.last < self.every_ms:
            return
        self.last = now
        for s in self.symbols:
            try:
                rows = self.rest.funding_rates(s, start_time=self.since[s])
            except Exception:  # noqa: BLE001  funding is a small cost; the next poll tries again
                self.errors += 1
                continue
            for r in rows:
                ft = int(r["fundingTime"])
                if ft < self.since[s]:
                    continue
                self.rates.setdefault(ft - ft % MIN, {})[s] = float(r["fundingRate"])
                self.since[s] = ft + 1

    def take(self, ts: int) -> dict:
        out = {}
        for t in [k for k in self.rates if k <= ts]:
            out.update(self.rates.pop(t))       # a rate that arrived late is paid on the next step, as feed.py
        return out


def _bar(r: dict) -> Bar:
    return Bar(r["symbol"], int(r["ts"]), int(r["close_time"] if r.get("close_time") is not None else r["ts"] + MIN - 1),
               float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
               r.get("mark_open"), r.get("mark_high"), r.get("mark_low"), r.get("mark_close"),
               volume=r.get("volume"))


def read_paper(paper_db: str, cursor: int, after_ts: Optional[int], members: list[Member], symbols,
               max_minutes: int = 600):
    """One consistent read of paper3.db (one read transaction): new member signals and the stepped minutes after
    ``after_ts`` (at most ``max_minutes``), as {ts: {symbol: Bar}} in time order."""
    from .livepnl import open_ro
    conn = open_ro(paper_db)
    try:
        conn.execute("BEGIN")
        rows, top = rule_rows(conn, cursor, members, set(symbols))
        if after_ts is None:
            r = conn.execute("SELECT MAX(ts) FROM live_bars").fetchone()
            last = r[0] if r else None
            minutes: dict = {}
            return rows, top, minutes, last
        q = conn.execute("SELECT ts, symbol, open, high, low, close, volume, mark_open, mark_high, mark_low, "
                         "mark_close, close_time FROM live_bars WHERE ts > ? AND ts <= ? ORDER BY ts",
                         (int(after_ts), int(after_ts) + max_minutes * MIN))
        cols = [c[0] for c in q.description]
        minutes = {}
        for t in q.fetchall():
            row = dict(zip(cols, t))
            if row["symbol"] in symbols:
                minutes.setdefault(int(row["ts"]), {})[row["symbol"]] = _bar(row)
        return rows, top, minutes, None
    finally:
        conn.close()


class ComboRunner:
    """Steps the account(s) on the rule bot's stepped minutes, submitting each signal before the minute that opens at
    its bar's close."""

    def __init__(self, cfg: ComboConfig, members: list[Member], book: AccountBook, store: Store3, notifier: Notifier,
                 custom: Optional[CustomSignals], now_ms: Callable[[], int], prices: Callable[[], dict],
                 funding: Optional[FundingFeed] = None, fetch_5m: Optional[Callable] = None,
                 btc: Optional[BtcTrend] = None, rdata: Optional[RM.RData] = None, gates=None, picture_gates=None,
                 friend=None):
        self.cfg, self.members, self.book, self.store = cfg, members, book, store
        self.gates = gates                  # paperbot/entrygates.EntryGates (vote_gate / vol_gate) or friendsig.FriendGates
                                            # (adx_gate / quiet_gate) or both (friendsig.GateChain), None = off
        self.friend = friend                # paperbot/friendsig.FriendSignals (FRIEND_ROC members), None = none
        self.friend_wait: dict = {}         # bar close -> {(member label, symbol)} whose bars Binance has not given yet
        self.loss_review = any(m.kind == "friend" for m in members)   # the friend bot's loss lines and rows
        self._loss_lines: dict = {}         # (entry ms, symbol) -> the loss line of a trade closed this minute
        self.picture_gates = picture_gates  # the same gates again, own caches: the live site's picture (gates_now)
        self._pic_ts: Optional[int] = None
        self._gate_info: dict = {}          # what the gates read for the signal in hand (_entry_block -> _submit_due)
        self.notifier, self.custom, self.now_ms, self.prices, self.funding = notifier, custom, now_ms, prices, funding
        self.fetch_5m = fetch_5m
        self.btc = btc
        self.rdata = rdata
        self.by_label = {m.label: m for m in members}
        st = store.get_state(STATE_KEY)
        st = st[1] if st else {}
        self.cursor: Optional[int] = st.get("cursor")
        self.queue: list[Queued] = [Queued(int(q["bar_close"]), q["signal"]) for q in st.get("queue", [])]
        self.breaks: list[dict] = list(st.get("breaks", []))     # research "break" entries waiting for the break
        self.counts: dict = st.get("counts", {})
        self.errors = 0
        self._drop_old_members(st)

    def _drop_old_members(self, st: dict) -> None:
        """A new config on the same database (owners 10-19: the 15-strategy bot after the A+C bot): queued signals and
        break waits of members no longer in the config never trade; their WAITING rows are closed as FILTERED."""
        known = set(self.by_label)
        member_of = lambda d: (d.get("meta") or {}).get("member", d.get("strategy_id"))  # noqa: E731
        old_q = [q for q in self.queue if member_of(q.signal) not in known]
        old_b = [b for b in self.breaks if b.get("member") not in known]
        if not old_q and not old_b:
            return
        self.queue = [q for q in self.queue if member_of(q.signal) in known]
        self.breaks = [b for b in self.breaks if b.get("member") in known]
        for b in old_b:
            self._restate(_sig_from(b["signal"]), "FILTERED", "설정이 바뀌어 기다리던 돌파 신호를 버림", expect=("WAITING",))
        self.store.alert(self.now_ms(), WARN, f"[combo] 설정이 바뀜: 예전 매매법의 대기 신호 {len(old_q)}개, 돌파 대기 "
                                             f"{len(old_b)}개를 버렸습니다(진입 안 함)")
        self.store.commit()

    # ---- state
    def _save_state(self, ts: int) -> None:
        self.store.put_state(STATE_KEY, ts, {
            "cursor": self.cursor, "queue": [{"bar_close": q.bar_close, "signal": q.signal} for q in self.queue],
            "breaks": self.breaks, "counts": self.counts, "version": VERSION,
            "members": [m.label for m in self.members], **self._state_extra()})

    # ---- hooks of the trend bot (paperbot/trendbot.py TrendRunner); nothing here for every other bot
    def _state_extra(self) -> dict:
        """More of the runner's own state, saved with the queue in the same commit."""
        return {}

    def _before_step(self, ts: int, bars: dict) -> None:
        """Before the accounts step minute ts (the trend bot's supervisor)."""

    def _after_step(self, ts: int, bars: dict) -> None:
        """After the accounts stepped minute ts (the trend bot's pullback waits)."""

    def _divert(self, sig: Signal, ts: int, bar_close: int, bars: dict) -> bool:
        """True: this entry signal is not submitted now (the trend bot: filtered by its checks, or waiting for its
        pullback). It still counts for the early exit."""
        return False

    def _own_signals(self) -> bool:
        """The runner computes signals of its own at the 5m boundaries without a custom member (the 레인지 봇's)."""
        return False

    def _count(self, label: str, what: str) -> None:
        c = self.counts.setdefault(label, {})
        c[what] = c.get(what, 0) + 1

    # ---- loop
    def start_at(self) -> Optional[int]:
        """The first start: the rule bot's latest stepped minute and signal_log row (nothing older is replayed)."""
        rows, top, _m, last = read_paper(self.cfg.paper_db, 0, None, self.members, self.cfg.symbols)
        self.cursor = int(top)
        if self.book.last_ts is None and last is not None:
            self.book.last_ts = int(last)
        return self.book.last_ts

    def poll(self) -> int:
        """One read and every minute it brings. Returns the number of minutes stepped."""
        if self.cursor is None or self.book.last_ts is None:
            self.start_at()
            if self.book.last_ts is None:
                return 0
            self._save_state(self.book.last_ts)
            self.book.save(self.book.last_ts)
        rows, top, minutes, _ = read_paper(self.cfg.paper_db, int(self.cursor), self.book.last_ts, self.members,
                                           self.cfg.symbols)
        if top < int(self.cursor):           # paper3.db replaced (a new run): its ids start again
            self.store.alert(self.now_ms(), WARN, f"paper3.db signal_log ids went back ({self.cursor} -> {top})")
            self.cursor = 0
            rows, top, minutes, _ = read_paper(self.cfg.paper_db, 0, self.book.last_ts, self.members,
                                               self.cfg.symbols)
        for m, row in rows:
            sig = rule_signal(self.cfg, m, row)
            self._queue(m, sig, int(row["bar_close"]), "rule")
        self.cursor = int(top)
        now = self.now_ms()
        if self.funding is not None:
            self.funding.poll(now)
        n = 0
        for ts in sorted(minutes):
            if self.friend is not None:
                self._friend_try(final=ts)       # a signal of the bar that closed at ts enters at ts: its last try
            self._submit_due(ts, minutes[ts])
            before = {aid: (e.position.entry_time if e.position else None, len(e.trades))
                      for aid, e in self.book.engines.items()}
            self._before_step(ts, minutes[ts])
            self.book.step(ts, minutes[ts], self.funding.take(ts) if self.funding else None)
            if self.loss_review:
                self._loss_review(ts, minutes[ts], before)
            self._tell(before)
            self._after_step(ts, minutes[ts])
            for b in minutes[ts].values():
                if self.custom is not None:
                    self.custom.add_1m(b)
                if self.rdata is not None:
                    self.rdata.add_1m(b.symbol, b.open_time, b.open, b.high, b.low)
            if self.rdata is not None:
                self._breaks(ts, minutes[ts])
                if ts % (60 * MIN) == 0:
                    self.rdata.trim(ts)
            boundary = ts + MIN
            if boundary % FIVE == 0 and self.custom is not None and (self.custom.members or self._own_signals()):
                self._custom(boundary)
            if self.friend is not None:
                self._friend_due(boundary)
                self._friend_try()
            self._save_state(ts)                 # the queue and the cursor with the engines, in one commit
            self.book.save(ts)
            if self.picture_gates is not None:
                self._gates_picture(ts, now)
            n += 1
        late = self._friend_try() if self.friend is not None and self.friend_wait else 0
        if (rows and not minutes) or late:
            self._save_state(self.book.last_ts or 0)
            self.book.save(self.book.last_ts or 0)
        self.store.put_state("heartbeat", now, {"last_step": self.book.last_ts, "queue": len(self.queue)})
        self.store.commit()
        return n

    def _gates_picture(self, ts: int, now: int) -> None:
        """State ``gates_now`` for the live site (paperbot/entrygates.picture): what the entry gates read for every coin,
        two minutes after each 30-minute close (that close's entries are in by then) and at the first live minute after
        a start; live minutes only (a catch-up shows nothing old). Its own gates object: a slow or failing read here
        never touches an entry check."""
        if now - int(ts) > 10 * MIN or (self._pic_ts is not None and int(ts) % (30 * MIN) != 2 * MIN):
            return
        from .entrygates import picture
        tfs = sorted({m.tf for m in self.members}, key=lambda tf: TF_MIN.get(tf, 0))
        try:
            pic = picture(self.picture_gates, self.cfg.symbols, tfs, int(ts) + MIN)
        except Exception as exc:  # noqa: BLE001  the site says it could not read; the bot goes on
            pic = {"at": int(ts) + MIN, "error": f"{type(exc).__name__}: {exc}"[:300]}
        self._pic_ts = int(ts)
        self.store.put_state(GATES_NOW_KEY, int(ts), pic)

    def _submit_due(self, ts: int, bars: Optional[dict] = None) -> None:
        """Signals whose bar closed at or before this minute's open go in now (the engine fills them in this step)."""
        keep, now = [], self.now_ms()
        for q in self.queue:
            if q.bar_close > ts:
                keep.append(q)
                continue
            sig = _sig_from(q.signal)
            self._gate_info = {}
            why = "" if sig.meta.get("exit_only") else self._entry_block(sig, ts, q.bar_close, bars or {})
            if self._gate_info:                       # what the entry gates read: kept with the signal and the trade
                gi = self._gate_info
                sig = replace(sig, meta={**sig.meta, "gates": gi, "ctx": {**(sig.meta.get("ctx") or {}), "gates": gi}})
            if self.loss_review and not why and not sig.meta.get("exit_only"):
                sig = self._entry_facts(sig, ts, q.bar_close, bars or {})
            if why:
                self._restate(sig, "FILTERED", why, extra={"gates": self._gate_info} if self._gate_info else None)
                self._count(sig.meta.get("member", sig.strategy_id), "filtered")
                if not self.cfg.early_exit:
                    continue
                # never an entry, but the strategy still turned: with early_exit it may close the open position
                sig = replace(sig, meta={**sig.meta, "exit_only": True})
            if sig.meta.get("research") and not sig.meta.get("exit_only"):
                sig = self._research_entry(sig, ts, bars or {})
                if sig is None:
                    continue
            age = now - int(sig.meta.get("ref_time") or q.bar_close)
            label = sig.meta.get("member", sig.strategy_id)
            exit_only = bool(sig.meta.get("exit_only"))
            late = age > self.cfg.max_signal_age_s * 1000
            held = (not exit_only and not late) and self._divert(sig, ts, q.bar_close, bars or {})
            for aid, e in self.book.engines.items():
                s = sig if aid == ACCOUNT else replace(sig, side=flip_side(aid, sig), meta=dict(sig.meta))
                # at its own minute, late or not: the paper replays every minute. A pulled entry (trendbot.py) had its
                # turn at its signal's minute; again with its entry ts it would re-draw the coin-flip twin's side
                if self.cfg.early_exit and not sig.meta.get("pulled"):
                    e.exit_signal(s)
                if exit_only or held:
                    continue
                if late:
                    e._record(s, "REJECTED", "late", ts, age_ms=age)
                    continue
                e.submit(s)
            if not exit_only and not held:
                self._count(label, "late" if late else "submitted")
        self.queue = keep

    def _entry_block(self, sig: Signal, ts: int, bar_close: int, bars: dict) -> str:
        """'' or why minute ts takes no entry from this signal: the KST weekend, a US macro release, the NYSE open,
        the entry gates (higher-bar vote, volatility), then a no_chase member's chase (in that order; the first reason
        is the one logged)."""
        if self.cfg.no_weekend and kst_weekend(ts):
            return "주말(한국 시간 토·일) 진입 안 함"
        if self.cfg.macro_blackout_min:
            ev = self._macro_near(ts)
            if ev:
                return ev
        if self.cfg.us_open_pause_min or self.cfg.us_open_pre_min:
            why = us_open_pause(ts, int(self.cfg.us_open_pause_min or 0), int(self.cfg.us_open_pre_min or 0))
            if why:
                return why
        if self.gates is not None:
            why, self._gate_info = self.gates.check(sig.symbol, sig.timeframe, int(sig.side), int(bar_close))
            if why:
                return why
        m = self.by_label.get(sig.meta.get("member", sig.strategy_id))
        if m is not None and m.no_chase:
            return self._chase_block(sig, bar_close, bars)
        return ""

    def _chase_block(self, sig: Signal, bar_close: int, bars: dict) -> str:
        """'' or why a no_chase member's signal is a chase (or cannot be told: then no entry either)."""
        from .livepnl import open_ro
        price = sig.meta.get("ref_price")
        if not price and sig.symbol in bars:
            price = bars[sig.symbol].open
        if not price:
            return "추격 판단에 쓸 가격이 없음(진입 안 함)"
        try:
            conn = open_ro(self.cfg.paper_db)
            try:
                hours = chase_hours(conn, sig.symbol, bar_close)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001  unreadable bars: no entry, said so
            return f"추격 판단에 쓸 1분봉을 못 읽음(진입 안 함): {type(exc).__name__}"[:200]
        chase, why = chase_check(hours, bar_close, int(sig.side), float(price))
        if chase is None:
            return why + "(진입 안 함)"
        return "추격 진입 막기: " + why if chase else ""

    # ---- the friend's strategy (paperbot/friendsig.py)
    def _friend_due(self, boundary: int) -> None:
        """A close of a FRIEND_ROC member's timeframe: its coins wait for their bars (read at the next try)."""
        due = self.friend.due(boundary)
        if not due or self.now_ms() - boundary > self.cfg.max_signal_age_s * 1000:
            return                                   # catch-up: these would be late anyway
        self.friend_wait[int(boundary)] = {(m.label, s) for m in due for s in self.friend.symbols}

    def _friend_try(self, final: Optional[int] = None) -> int:
        """The FRIEND_ROC signals of the closes waiting for their bars: read once the bar has settled at Binance
        (``SETTLE_MS`` after its close), tried again at each poll while a bar is not there yet; at the minute that would
        enter them (``final``) the last try, then what is still missing is given up and said. Returns the signals
        queued."""
        if not self.friend_wait:
            return 0
        from .friendsig import SETTLE_MS as F_SETTLE
        now, n, px = self.now_ms(), 0, None
        for b in sorted(self.friend_wait):
            last = final is not None and b <= final
            if not last and now < b + F_SETTLE:
                continue
            got, left = self.friend.compute(b, self.friend_wait[b])
            for e in self.friend.errors:
                self.store.alert(now, WARN, f"[combo] friend signal: {e}"[:300])
            self.friend.errors.clear()
            if got and px is None:
                try:
                    px = self.prices()
                except Exception:  # noqa: BLE001  without a price the fill is the next minute's open
                    px = {}
            ready = self.now_ms()
            for g in got:
                m: Member = g["member"]
                bid, ask = (px or {}).get(g["symbol"], (None, None))
                ref = ask if g["side"] > 0 else bid
                sig = make_signal(self.cfg, m, b, g["symbol"], g["side"], g["atr"], ref, ready, ready - b, g["ctx"],
                                  "friend")
                vals = g["values"]
                sig = replace(sig, meta={**sig.meta, "friend": vals, "ctx": {**sig.meta["ctx"], "friend": vals}})
                self._queue(m, sig, b, "friend")
                n += 1
            if left and not last:
                self.friend_wait[b] = left
                continue
            del self.friend_wait[b]
            if left:
                self._friend_failed(b, left)
        return n

    def _friend_failed(self, bar_close: int, left: set) -> None:
        """A close whose bars could not be read before its entry minute: no signal from those coins, an alert each time,
        Telegram on the 1st / 10th / 100th."""
        self.ffails = getattr(self, "ffails", 0) + 1
        coins = ", ".join(s.replace("USDT", "") for s in self.cfg.symbols if any(x == s for _l, x in left))
        err = self.friend.bars.errors[-1] if self.friend.bars.errors else "끝난 봉을 아직 못 받음"
        when = time.strftime("%m-%d %H:%M", time.gmtime(bar_close / 1000 + 9 * 3600))
        msg = f"{self.cfg.tag} 친구 매매법 신호 봉을 못 읽어 건너뜀({self.ffails}번째): {when} KST {coins} · {err}"[:300]
        self.store.alert(self.now_ms(), WARN, msg)
        if self.ffails in (1, 10, 100) or self.ffails % 1000 == 0:
            self.notifier.send(WARN, msg)

    def _entry_facts(self, sig: Signal, ts: int, bar_close: int, bars: dict) -> Signal:
        """The loss review's entry values, kept in the signal's context (so the trade record has them): the 24 h range
        position of the entry minute's open (the rule bot's 1m bars in paper3.db, combo.chase_hours), BTC's open of the
        entry minute, the nearest US macro release."""
        from .friendsig import entry_facts
        from .livepnl import open_ro
        bar = bars.get(sig.symbol)
        price = bar.open if bar is not None else sig.meta.get("ref_price")
        btc = bars.get("BTCUSDT")
        try:
            conn = open_ro(self.cfg.paper_db)
            try:
                hours = chase_hours(conn, sig.symbol, bar_close)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001  review values only: the range position stays unknown
            hours = {}
        try:
            facts = entry_facts(hours, bar_close, int(sig.side), price, btc.open if btc is not None else None, ts)
        except Exception as exc:  # noqa: BLE001  review values only: never in the way of the entry
            facts = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        return replace(sig, meta={**sig.meta, "ctx": {**(sig.meta.get("ctx") or {}), "entry": facts}})

    def _loss_review(self, ts: int, bars: dict, before: dict) -> None:
        """Each losing trade of the account closed in minute ts: its loss review row (friendsig.loss_facts, table
        loss_review) and the line for its exit message; then an entry the liquidation buffer refused (_liq_refused)."""
        from .friendsig import loss_facts, loss_line, store_loss
        e = self.book.engines.get(ACCOUNT)
        if e is None:
            return
        btc = bars.get("BTCUSDT")
        for t in e.trades[before.get(ACCOUNT, (None, 0))[1]:]:
            if t.roe > 0:
                continue
            try:
                f = loss_facts(t, btc.close if btc is not None else None, e.s.round_trip_cost)
                line = loss_line(f)
                store_loss(self.store.conn, ACCOUNT, t, f, line)
            except Exception as exc:  # noqa: BLE001  the review never stops the minute
                self.store.alert(self.now_ms(), WARN, f"[combo] loss review: {type(exc).__name__}: {exc}"[:300])
                continue
            self._loss_lines[(int(t.entry_time), t.symbol)] = line
        self._liq_refused(ts)

    def _liq_refused(self, ts: int) -> None:
        """An entry of minute ts refused because the net ROE stop would sit too close to (or past) the liquidation price
        at the paper's size (the coin's Binance bracket: LTC and BCH once the wallet has about doubled): said as an alert
        each time, on Telegram the 1st / 10th / 100th time. The stop is never moved."""
        rows = self.store.conn.execute("SELECT symbol, data FROM outcomes WHERE account_id = ? AND step_ts = ? AND "
                                       "status = 'REJECTED' AND reason = 'sizing'", (ACCOUNT, int(ts))).fetchall()
        for sym, d in rows:
            try:
                det = json.loads(d).get("detail") or {}
            except (TypeError, ValueError):
                det = {}
            if not any("too close to liq" in str(r) for r in det.get("reasons") or []):
                continue
            self.lfails = getattr(self, "lfails", 0) + 1
            msg = (f"{self.cfg.tag} 진입 거절({self.lfails}번째): {sym.replace('USDT', '')} - 손절 자리가 강제청산 가격에 너무 "
                   f"가까움(지금 크기의 바이낸스 유지증거금 구간). 손절은 옮기지 않고 이 신호는 건너뜀")
            self.store.alert(self.now_ms(), WARN, msg)
            if self.lfails in (1, 10, 100) or self.lfails % 1000 == 0:
                self.notifier.send(WARN, msg)

    def _macro_near(self, ts: int) -> str:
        """'' or why minute ts is inside the macro blackout (an entry in that minute is not made)."""
        from . import events as EV
        w = int(self.cfg.macro_blackout_min) * MIN
        near = EV.near(int(ts), w, w)
        if not near:
            return ""
        e = near[0]
        return f"경제 발표 앞뒤 {self.cfg.macro_blackout_min}분: {EV.KIND_KO.get(e.kind, e.kind)} {e.ts_utc}"

    def _custom(self, boundary: int) -> None:
        now = self.now_ms()
        if now - boundary > self.cfg.max_signal_age_s * 1000:
            return                                   # catch-up: these would be late anyway (history still built)
        if self.fetch_5m is not None:
            self.custom.fill_gaps(self.fetch_5m, boundary)
        got = self.custom.compute(boundary)
        for e in self.custom.errors:
            self.store.alert(now, WARN, f"[combo] custom signal: {e}"[:300])
        self.custom.errors.clear()
        if not got:
            return
        try:
            px = self.prices()
        except Exception:  # noqa: BLE001  without a price the fill is the next minute's open
            px = {}
        ready = self.now_ms()
        for g in got:
            m: Member = g["member"]
            side = -g["side"] if (m.research and m.research.invert) else g["side"]
            bid, ask = px.get(g["symbol"], (None, None))
            ref = ask if side > 0 else bid
            sig = make_signal(self.cfg, m, boundary, g["symbol"], side, g["atr"], ref, ready, ready - boundary,
                              g["ctx"], "custom")
            if m.research is not None:
                self._research_signal(m, sig, boundary)
            else:
                self._queue(m, sig, boundary, "custom")

    # ---- research members (paperbot/rmember.py)
    def _research_failed(self, text: str) -> None:
        """A research rule could not be read (no trade): an alert each time, Telegram on the 1st / 10th / 100th."""
        self.rfails = getattr(self, "rfails", 0) + 1
        msg = f"{self.cfg.tag} 연구 조건을 못 읽어 진입 안 함({self.rfails}번째): {text}"[:300]
        self.store.alert(self.now_ms(), WARN, msg)
        if self.rfails in (1, 10, 100) or self.rfails % 1000 == 0:
            self.notifier.send(WARN, msg)

    def _research_errors(self) -> None:
        for e in self.rdata.errors:
            self._research_failed(e)
        self.rdata.errors.clear()

    def _research_signal(self, m: Member, sig: Signal, boundary: int) -> None:
        """A research member's signal at its bar close: the signal-time filter, then queued ("now") or waiting for
        the break ("break"). The displacement filter and the off buckets are read at the entry minute."""
        r = m.research
        try:
            tags = self.rdata.signal_tags(sig.symbol, sig.side, boundary)
        except Exception as exc:  # noqa: BLE001  without its tags the setting cannot be checked: no trade
            why = f"연구 조건을 못 읽음: {type(exc).__name__}: {exc}"[:200]
            self._log(sig, "FILTERED", "custom", why)
            self._count(m.label, "filtered")
            self._research_failed(f"{m.label} {sig.symbol}: {why}")
            return
        bad = RM.filter_fails(r, tags)
        if bad:
            self._log(sig, "FILTERED", "custom", "연구 조건 밖: " + ", ".join(bad))
            self._count(m.label, "filtered")
            return
        sig = replace(sig, meta={**sig.meta, "research": True, "rtags": tags, "rsig_t": boundary})
        if r.entry == "break":
            self.breaks.append({"member": m.label, "t0": boundary, "until": boundary + TF_MS[m.tf],
                                "level": None, "signal": dataclasses.asdict(sig)})
            self._log(sig, "WAITING", "custom", "돌파 확인 대기")
            return
        self._queue(m, sig, boundary, "custom")

    def _disp_ok(self, m: Member, sig: Signal, t0: int, open_t0: float) -> bool:
        tfm = RM.TF_MIN[m.tf]
        ts, o, h, l = self.rdata.window_1m(sig.symbol, t0 - tfm * MIN, t0)
        if len(ts) < tfm:
            return False                              # the search: no trade without the bar's minutes
        return RM.disp_ok(m.research.disp, sig.side, float(sig.atr or 0.0), h, l, float(o[0]), open_t0)

    def _research_entry(self, sig: Signal, ts: int, bars: dict) -> Optional[Signal]:
        """At the entry minute ts: the displacement filter ("now" entries), the off buckets and the swing window.
        None (logged FILTERED) when the setting does not trade it."""
        m = self.by_label.get(sig.meta.get("member"))
        if m is None or m.research is None:
            self._restate(sig, "FILTERED", "설정에 없는 연구 매매법(설정이 바뀜)")
            return None
        bar = bars.get(sig.symbol)
        if bar is None:
            return sig                                # the engine records it: no bar of its coin this minute
        r = m.research
        try:
            if r.disp and r.entry == "now" and not self._disp_ok(m, sig, ts, float(bar.open)):
                self._restate(sig, "FILTERED", "연구 조건 밖: 신호봉 크기")
                self._count(m.label, "filtered")
                return None
            dims = self.rdata.entry_dims(sig.symbol, sig.side, ts, float(bar.open), sig.meta["rtags"])
            hit = RM.off_hits(r, dims)
            if hit:
                self._restate(sig, "FILTERED", "끈 구간: " + ", ".join(hit))
                self._count(m.label, "filtered")
                return None
            meta = {**sig.meta, "rstop": list(r.stop), "rdims": dims}
            if r.stop[0] == "swing":
                w = int(r.stop[1]) * RM.TF_MIN[m.tf]
                _t, _o, h, l = self.rdata.window_1m(sig.symbol, ts - w * MIN, ts)
                if not len(_t):
                    raise RuntimeError("no 1m bars for the swing window")
                meta["rswing"] = {"lo": float(l.min()), "hi": float(h.max())}
        except Exception as exc:  # noqa: BLE001  unreadable: no trade
            why = f"연구 조건을 못 읽음: {type(exc).__name__}: {exc}"[:200]
            self._restate(sig, "FILTERED", why)
            self._count(m.label, "filtered")
            self._research_failed(f"{m.label} {sig.symbol}: {why}")
            return None
        finally:
            self._research_errors()
        return replace(sig, meta=meta)

    def _breaks(self, ts: int, bars: dict) -> None:
        """Research "break" entries: minute ts trades beyond the signal bar's high (long) / low (short) -> the entry
        is the next minute's open (queued for it); past the bar's tf minutes, the signal lapses."""
        if not self.breaks:
            return
        keep, now = [], self.now_ms()
        px = None
        for b in self.breaks:
            sig = _sig_from(b["signal"])
            m = self.by_label.get(b["member"])
            if m is None or ts >= b["until"]:
                self._restate(sig, "FILTERED", "돌파 없음(신호봉 시간 안에)", expect=("WAITING",))
                continue
            if ts < b["t0"]:
                keep.append(b)
                continue
            bar = bars.get(sig.symbol)
            if bar is None:
                keep.append(b)
                continue
            try:
                if b["level"] is None:
                    tfm = RM.TF_MIN[m.tf]
                    t_, _o, h, l = self.rdata.window_1m(sig.symbol, b["t0"] - tfm * MIN, b["t0"])
                    if not len(t_):
                        raise RuntimeError("no 1m bars of the signal bar")
                    b["level"] = float(h.max()) if sig.side > 0 else float(l.min())
                    if m.research.disp and not self._disp_ok(m, sig, b["t0"], float(bar.open)):
                        self._restate(sig, "FILTERED", "연구 조건 밖: 신호봉 크기", expect=("WAITING",))
                        self._count(m.label, "filtered")
                        continue
            except Exception as exc:  # noqa: BLE001
                why = f"연구 조건을 못 읽음: {type(exc).__name__}: {exc}"[:200]
                self._restate(sig, "FILTERED", why, expect=("WAITING",))
                self._research_failed(f"{b['member']} {sig.symbol}: {why}")
                continue
            broke = bar.high > b["level"] if sig.side > 0 else bar.low < b["level"]
            if not broke:
                keep.append(b)
                continue
            entry_t = ts + MIN
            if now - entry_t > self.cfg.max_signal_age_s * 1000:
                self._restate(sig, "FILTERED", "돌파 확인이 늦음(재시작 따라잡기)", expect=("WAITING",))
                continue
            if px is None:
                try:
                    px = self.prices()
                except Exception:  # noqa: BLE001  without a price the fill is the entry minute's open
                    px = {}
            bid, ask = px.get(sig.symbol, (None, None))
            ref = ask if sig.side > 0 else bid
            meta = {**sig.meta, "ref_time": now, "delay_ms": now - entry_t, "break_level": b["level"],
                    "break_minute": ts}
            meta.pop("ref_price", None)
            if ref is not None:
                meta["ref_price"] = float(ref)
            nsig = replace(sig, ts=entry_t - 1, meta=meta)
            self.queue.append(Queued(entry_t, dataclasses.asdict(nsig)))
            self._restate(sig, "BROKE", f"돌파 확인: {entry_t} 분에 진입 신호", expect=("WAITING",))
            self._log(nsig, "SUBMITTED", "custom", "돌파 확인")
        self.breaks = keep

    def _queue(self, m: Member, sig: Signal, bar_close: int, source: str) -> None:
        """Inside the member's conditions: queued for entry. Outside: logged FILTERED, and with ``early_exit`` queued
        as exit-only (it may close the open position, never opens one)."""
        if self._allowed(m, sig, source):
            self.queue.append(Queued(bar_close, dataclasses.asdict(sig)))
            self._log(sig, "SUBMITTED", source)
        elif self.cfg.early_exit:
            self.queue.append(Queued(bar_close, dataclasses.asdict(replace(sig, meta={**sig.meta, "exit_only": True}))))

    def _allowed(self, m: Member, sig: Signal, source: str) -> bool:
        """The member's conditions (``when``); a signal outside them is logged FILTERED and reaches no account."""
        ok, why = m.allows(sig.symbol, sig.side, sig.ts + 1, self.btc.sign_at if self.btc is not None else None)
        if self.btc is not None and self.btc.errors:
            for e in self.btc.errors:
                self.store.alert(self.now_ms(), WARN, f"[combo] {e}")
            self.btc.errors.clear()
        if not ok:
            self._log(sig, "FILTERED", source, why)
            self._count(m.label, "filtered")
        return ok

    def _restate(self, sig: Signal, status: str, why: str, expect: tuple = ("SUBMITTED",),
                 extra: Optional[dict] = None) -> None:
        """A later status of a signal already logged (signal_log keeps one row per bar, coin and member): a research
        member's signal filtered at its entry minute (its SUBMITTED row), or a break that never came (its WAITING
        row). A row in another status belongs to another signal of the same bar and is left alone. ``extra``: more
        keys for the row's data (the trend bot's judgment and checks)."""
        cur = self.store.conn.execute(
            "SELECT data, status FROM signal_log WHERE bar_close = ? AND timeframe = ? AND strategy = ? AND symbol = ?",
            (sig.ts + 1, sig.timeframe, sig.meta.get("member", sig.strategy_id), sig.symbol)).fetchone()
        if cur is None:
            self._log(sig, status, "custom", why, extra)
            return
        if cur[1] not in expect:
            return
        try:
            data = json.loads(cur[0] or "{}")
        except ValueError:
            data = {}
        data.update(extra or {})
        data["why"] = why
        self.store.conn.execute(
            "UPDATE signal_log SET status = ?, data = ? WHERE bar_close = ? AND timeframe = ? AND strategy = ? "
            "AND symbol = ?", (status, json.dumps(data, default=str), sig.ts + 1, sig.timeframe,
                               sig.meta.get("member", sig.strategy_id), sig.symbol))

    def _log(self, sig: Signal, status: str, source: str, why: str = "", extra: Optional[dict] = None) -> None:
        data = {"source": source, "score": sig.meta.get("score_raw"), "strategy": sig.strategy_id, **(extra or {})}
        if why:
            data["why"] = why
        self.store.log_signals([{
            "bar_close": sig.ts + 1, "timeframe": sig.timeframe, "strategy": sig.meta.get("member", sig.strategy_id),
            "symbol": sig.symbol, "side": sig.side, "atr": sig.atr, "ref_price": sig.meta.get("ref_price"),
            "ref_time": sig.meta.get("ref_time"), "delay_ms": sig.meta.get("delay_ms"), "status": status,
            "data": data}])

    # ---- messages
    def _tell(self, before: dict) -> None:
        e = self.book.engines.get(ACCOUNT)
        lines, self._loss_lines = self._loss_lines, {}
        if e is None or not self.cfg.telegram:
            return
        was_entry, was_n = before.get(ACCOUNT, (None, 0))
        if os.environ.get("PAPERBOT_COMBO_TRADE_MSGS", "").strip() == "0":
            # the live watcher's 🟢 / ✅ / ❌ messages (paperbot/livecheck.py) take their place; the friend bot's loss
            # review line still goes, on its own (the watcher's ❌ has no such line)
            for t in e.trades[was_n:]:
                line = lines.get((int(t.entry_time), t.symbol))
                if line:
                    self.notifier.send(INFO, f"{self.cfg.tag} {t.symbol.replace('USDT', '')} {KO_SIDE.get(t.side, t.side)} "
                                             f"순ROE {t.roe:+.1%} · {line}")
            return
        for t in e.trades[was_n:]:
            self.notifier.send(INFO, exit_text(self.cfg, t, lines.get((int(t.entry_time), t.symbol), "")))
        p = e.position
        if p is not None and p.entry_time != was_entry:
            self.notifier.send(INFO, entry_text(self.cfg, p))


# ====================================================================== message words (Telegram, check-config)
def stop_rule_ko(rule: Optional[str]) -> str:
    """The entry's stop rule (signal meta ``stop_rule``, kept in English in the records) in the owners' words."""
    import re
    r = str(rule or "")
    m = re.fullmatch(r"ROE -(\d+)% net at (\d+)x", r)
    if m:
        return f"순ROE -{m[1]}%(수수료·슬리피지 포함), {m[2]}배"
    m = re.fullmatch(r"ROE -(\d+)% at (\d+)x", r)
    if m:
        return f"ROE -{m[1]}%, {m[2]}배"
    m = re.fullmatch(r"([\d.]+) x ATR pulled in to ([\d.]+) x ATR \(fits (\d+)x\)", r)
    if m:
        return f"{m[1]} ATR을 {m[2]} ATR로 당김({m[3]}배 강제청산 안쪽)"
    m = re.fullmatch(r"([\d.]+) x ATR", r)
    if m:
        return f"{m[1]} ATR"
    return r


def exit_ko(cfg: "ComboConfig", reason: str) -> str:
    """An exit reason in words; TIME is the hold limit's (보유 한도 청산) in a bot with ``max_hold_bars`` and no trend
    supervisor (paperbot/livepapers.time_exit_ko says the same from a config dict)."""
    if reason == "TIME" and cfg.trend is None and cfg.max_hold_bars:
        return TIME_HOLD_KO
    return KO_EXIT.get(reason, reason)


def friend_bot(cfg: "ComboConfig") -> bool:
    """A bot with the friend's strategy (FRIEND_ROC): its own entry words and the loss line of its losing exits."""
    return any(isinstance(m, dict) and m.get("strategy") == FRIEND for m in (cfg.members or []))


def exit_text(cfg: "ComboConfig", t, loss: str = "") -> str:
    """The paper bot's own exit line (a TradeRecord); ``loss``: the friend bot's loss review line of a losing trade,
    on a line of its own."""
    why = (t.context or {}).get("exit_why") if isinstance(t.context, dict) else None
    if cfg.vote_gate or cfg.vol_gate or friend_bot(cfg) or cfg.range is not None:  # VWAP / friend / 레인지: owners' words
        return (f"{cfg.tag} 청산 {t.symbol.replace('USDT', '')} {KO_SIDE.get(t.side, t.side)} · {member_ko(t.strategy_id)} "
                f"{KO_TF.get(t.timeframe, t.timeframe)} · {exit_ko(cfg, t.exit_reason)}" + (f"({why})" if why else "")
                + f" · 순ROE {t.roe:+.1%}, {'+' if t.pnl >= 0 else '-'}${abs(t.pnl):,.2f}, 지갑 ${t.equity_after:,.2f}"
                + (f"\n{loss}" if loss else ""))
    return (f"{cfg.tag} 청산 {t.symbol} {KO_SIDE.get(t.side, t.side)} {t.strategy_id} "
            f"{KO_TF.get(t.timeframe, t.timeframe)}: {exit_ko(cfg, t.exit_reason)}"
            + (f"({why})" if why else "") + f", "
            f"순ROE {t.roe:+.1%}, {'+' if t.pnl >= 0 else '-'}${abs(t.pnl):,.2f}, 지갑 ${t.equity_after:,.2f}")


MEMBER_KO = {"F6_VWAP_FAIL": "VWAP 복귀 실패", "S3_CMO_SANDWICH": "CMO·샌드위치 캔들",   # the VWAP bot's two (10-23)
             FRIEND: "친구 매매법(EMA·RSI·ROC)",                                       # the friend bot's (10-24)
             "F7_RF_TRIPLE": "레인지 필터 3중 일치",                                    # the 레인지 봇's (10-26)
             "ROC50": "ROC 50선",                                                      # and its ROC entry (10-30)
             "EMA3": "추세 3개 일치"}                                                  # and 추세 3개 일치 (10-31)


def member_ko(strategy: str) -> str:
    """A strategy's name in the owners' words (the rule bot's names; the code when none is known)."""
    if strategy in MEMBER_KO:
        return MEMBER_KO[strategy]
    try:
        from .agents.roster3 import STRATEGY_KO
        return STRATEGY_KO.get(strategy, strategy)
    except Exception:  # noqa: BLE001  display only
        return strategy


def gates_text(g: Optional[dict]) -> str:
    """What the entry gates read at an entry ("4시간 상승(상승 3·하락 0·중립 1) · 변동성 30분 ATR 0.45% (30일 80% 위치
    0.62%)"); '' when the bot has none."""
    if not isinstance(g, dict):
        return ""
    parts = [str((g.get(k) or {}).get("text") or "") for k in ("vote", "vol", "adx", "quiet")]
    return " · ".join(x for x in parts if x)


def entry_text(cfg: "ComboConfig", p) -> str:
    """The paper bot's own entry line (an open Position). A bot with entry gates (the VWAP bot) names the strategy in
    the owners' words and says what the gates read; every other bot's line is as before."""
    m = p.signal.meta
    rule = stop_rule_ko(m.get("stop_rule"))
    if isinstance(m.get("friend"), dict):          # the friend bot: the signal bar's values, to check it on TradingView
        from .friendsig import signal_words
        return (f"{cfg.tag} 진입 {p.symbol.replace('USDT', '')} {KO_SIDE.get(p.side, p.side)} · "
                f"{member_ko(p.signal.strategy_id)} {KO_TF.get(p.signal.timeframe, p.signal.timeframe)} · {p.leverage}배, "
                f"증거금 ${p.margin:,.2f}, 손절 {p.stop_price:.6g}" + (f" ({rule})" if rule else "")
                + f"\n신호 봉: {signal_words(m['friend'])}")
    if isinstance(m.get("range"), dict):           # the 레인지 봇: the pullback it entered on and the two supertrends
        from .rangebot import entry_words
        return (f"{cfg.tag} 진입 {p.symbol.replace('USDT', '')} {KO_SIDE.get(p.side, p.side)} · "
                f"{member_ko(p.signal.strategy_id)} {KO_TF.get(p.signal.timeframe, p.signal.timeframe)} · {p.leverage}배, "
                f"증거금 ${p.margin:,.2f}, 손절 {p.stop_price:.6g}" + (f" ({rule})" if rule else "")
                + (f", 익절 {p.tp_price:.6g}" if p.tp_price == p.tp_price else "") + f"\n{entry_words(m['range'])}")
    if isinstance(m.get("gates"), dict):
        g = gates_text(m.get("gates"))
        return (f"{cfg.tag} 진입 {p.symbol.replace('USDT', '')} {KO_SIDE.get(p.side, p.side)} · "
                f"{member_ko(p.signal.strategy_id)} {KO_TF.get(p.signal.timeframe, p.signal.timeframe)} · {p.leverage}배, "
                f"증거금 ${p.margin:,.2f}, 손절 {p.stop_price:.6g}" + (f" ({rule})" if rule else "")
                + (f" · {g}" if g else ""))
    return (f"{cfg.tag} 진입 {p.symbol} {KO_SIDE.get(p.side, p.side)} {p.signal.strategy_id} "
            f"{KO_TF.get(p.signal.timeframe, p.signal.timeframe)} ({m.get('member')}), {p.leverage}배, "
            f"증거금 ${p.margin:,.2f}, 손절 {p.stop_price:.6g}" + (f" ({rule})" if rule else "")
            + f", 점수 {p.signal.score:.2f}")


def start_text(cfg: "ComboConfig", members: list, wallet: float) -> str:
    """The paper bot's start message: its name, its strategies and its rules as the running config says them."""
    nc = sum(m.no_chase for m in members)
    rest = ((["주말"] if cfg.no_weekend else [])
            + ([f"경제 발표 앞뒤 {cfg.macro_blackout_min}분"] if cfg.macro_blackout_min else [])
            + ([us_open_ko(cfg.us_open_pause_min or 0, cfg.us_open_pre_min or 0)]
               if cfg.us_open_pause_min or cfg.us_open_pre_min else []))
    pause = ("진입 쉼 " + "·".join(rest) + ", ") if rest else ""
    kinds = ([f"{sum(m.custom for m in members)}개 커스텀값"] if any(m.custom for m in members) else []) \
        + ([f"{sum(bool(m.when) for m in members)}개 조건 있음"] if any(m.when for m in members) else [])
    if cfg.vote_gate is not None or cfg.vol_gate is not None or friend_bot(cfg):   # a short list (VWAP, friend): names
        kinds = [" · ".join(f"{member_ko(m.name)} {KO_TF.get(m.tf, m.tf)}"
                            + {"rsi_roc_all": " 상위 봉 둘 다 RSI·ROC", "rsi_roc_1h": " 1시간 RSI·ROC"}.get(m.higher or "", "")
                            for m in members)] + kinds
    return (f"{cfg.tag} 시작: 매매법 {len(members)}개" + (f"({', '.join(kinds)})" if kinds else "") + ", "
            f"BTC {cfg.lev_of('BTCUSDT')}배·나머지 {cfg.lev_of('ETHUSDT')}배, 증거금 "
            f"{'배수%' if cfg.margin == 'leverage' else f'잔고의 {float(cfg.margin):.0%}'}, 손절 {stop_text(cfg)}, "
            f"{take_profit_text(cfg)}, "
            f"빠른 청산 {early_ko(cfg)}"
            f"{'(첫 잠금 전까지만)' if cfg.early_exit and cfg.early_exit_until_lock else ''}, "
            f"{f'추격 진입 막기 {nc}개, ' if nc else ''}"
            f"{trend_start_text(cfg.trend) if cfg.trend is not None else ''}"
            + "".join(f"{line}, " for line in gate_lines(cfg) + range_lines(cfg)) +
            f"포지션 1개, {pause}지갑 ${wallet:,.2f}")


def gate_lines(cfg: "ComboConfig") -> list[str]:
    """The entry gates and the time limit in the owners' words (empty when all are off)."""
    out = []
    if cfg.vote_gate is not None or cfg.vol_gate is not None:
        from .entrygates import vol_text, vote_text
        if isinstance(cfg.vote_gate, dict):
            out.append(vote_text(cfg.vote_gate))
        if isinstance(cfg.vol_gate, dict):
            out.append(vol_text(cfg.vol_gate))
    if cfg.adx_gate is not None or cfg.quiet_gate is not None:
        from .friendsig import adx_text, quiet_text
        if isinstance(cfg.adx_gate, dict):
            out.append(adx_text(cfg.adx_gate))
        if isinstance(cfg.quiet_gate, dict):
            out.append(quiet_text(cfg.quiet_gate))
    if isinstance(cfg.max_hold_bars, int) and not isinstance(cfg.max_hold_bars, bool):
        tfs = sorted({str(m.get("tf")) for m in cfg.members if isinstance(m, dict) and m.get("tf") in TF_MIN},
                     key=lambda tf: TF_MIN[tf])
        each = " · ".join(f"{KO_TF.get(tf, tf)} {hold_ko(cfg.max_hold_bars * TF_MIN[tf])}" for tf in tfs)
        out.append(f"보유 한도 {cfg.max_hold_bars}봉" + (f"({each})" if each else "") + ", 넘으면 시장가 청산")
    if isinstance(cfg.unlocked_close_min, int) and not isinstance(cfg.unlocked_close_min, bool):
        out.append(f"진입 {hold_ko(cfg.unlocked_close_min)} 안에 첫 잠금에 못 닿으면 시장가 청산")
    return out


def range_lines(cfg: "ComboConfig") -> list[str]:
    """The 레인지 봇's own rules in the owners' words (empty for every other bot)."""
    if cfg.range is None:
        return []
    from .rangebot import RangeError, RangeRules
    try:
        return RangeRules.from_dict(cfg.range).describe(range_on=bool(cfg.members))
    except (RangeError, TypeError):
        return []                                  # the problem is in check-config's list


def hold_minutes(cfg: "ComboConfig", tf: str) -> Optional[int]:
    """``max_hold_bars`` of a position's own timeframe in minutes (None: no limit)."""
    if not cfg.max_hold_bars or tf not in TF_MIN:
        return None
    return int(cfg.max_hold_bars) * TF_MIN[tf]


def hold_ko(minutes: int) -> str:
    return f"{minutes // 60}시간" if minutes % 60 == 0 else f"{minutes}분"


def trend_start_text(trend: dict) -> str:
    """The trend bot's part of the start line: the judged frames, 보류, the entry style."""
    t = trend if isinstance(trend, dict) else {}
    return ("추세 판단(30분→1시간·1시간→4시간·4시간→일봉)"
            + ("·보류 허용" if t.get("hold_entry") else "")
            + ("·되돌림 진입" if t.get("pullback_wait", True) else "·바로 진입") + "·감독 청산"
            + (f"(설계 {t['design']})" if t.get("design") else "") + ", ")


# ====================================================================== start
def build_book(cfg: ComboConfig, settings, brackets, store: Store3, notifier: Notifier, specs: dict) -> AccountBook:
    # saved by the runner after each minute together with its own state (save_every: never inside step)
    book = AccountBook(settings, brackets, store, notifier, specs, save_every=10 ** 12)
    cls = make_cls(cfg)
    restored = book.load(make_of=lambda row: {"cls": cls})
    now = int(time.time() * 1000)
    want = [(ACCOUNT, KIND)] + ([(FLIP_ACCOUNT, FLIP_KIND)] if cfg.flip_twin else [])
    for aid, kind in want:
        if aid not in book.engines:
            strategy, tf = aid.split("@")
            book.add_extra({"account_id": aid, "strategy": strategy, "timeframe": tf, "kind": kind, "parent": None,
                            "data": {"version": VERSION}}, now, cls=cls)
    store.commit()
    if not restored:
        store.put_state("run", now, {"settings": settings.version, "initial_equity": settings.initial_equity})
        store.commit()
    return book


def _brackets(cfg: ComboConfig, rest) -> tuple[dict, str]:
    from .live import load_brackets
    path = cfg.brackets_file
    if path and path.endswith("exchange.json"):        # research/fullgrid/exchange.json: {"brackets": [...]}
        with open(path) as fh:
            payload = json.load(fh)["brackets"]
        by = {p["symbol"]: Brackets.from_binance(p) for p in payload}
        return {s: by[s] for s in cfg.symbols}, f"file {path}"
    return load_brackets(rest, list(cfg.symbols), path, False)


KL_MS = {"1m": MIN, "1h": 3_600_000, "4h": H4}


def research_problems(cfg: ComboConfig, members: list) -> list[str]:
    if cfg.early_exit and any(m.research for m in members):
        return ["early_exit는 연구 설정(research) 매매법과 함께 쓰지 않습니다(탐색에 없던 규칙)"]
    return []


def research_data(rest, symbols) -> RM.RData:
    """RData on Binance (public endpoints): closed klines, settled funding, 5-minute open interest. Its own client:
    one retry and a 5 s timeout, so a failing endpoint costs seconds, not a minute, inside a boundary."""
    from .binance import BinanceREST, urllib_fetch
    rest = BinanceREST(base_url=rest.base, fetch=lambda u, h: urllib_fetch(u, h, timeout=5.0), max_retries=1,
                       backoff=0.5)

    def klines(symbol, interval, start, end):
        ms, out, t = KL_MS[interval], [], int(start)
        now = int(time.time() * 1000)
        while t < end:
            got = rest.klines(symbol, interval, start_time=t, limit=1500)
            got = [r for r in got if int(r[0]) < end and int(r[0]) + ms <= now]
            if not got:
                break
            out += [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in got]
            t = int(got[-1][0]) + ms
            if len(got) < 1500:
                break
            time.sleep(0.3)
        return out

    def funding(symbol, start):
        return [(int(r["fundingTime"]), float(r["fundingRate"])) for r in rest.funding_rates(symbol, start_time=start)]

    def oi(symbol, start, end):
        rows = rest.flow_stats("oi", symbol, "5m", start_time=start, end_time=end, limit=500)
        return [(int(r["timestamp"]), float(r["sumOpenInterest"])) for r in rows]

    return RM.RData(symbols, klines, funding, oi)


def cmd_run(args) -> int:
    from .binance import BinanceREST
    from .live import _notifier
    from .live3 import book_prices, fetch_5m
    cfg = ComboConfig.from_file(args.config)
    probs = cfg.problems()
    if probs:
        raise SystemExit("설정 문제: " + "; ".join(probs))
    members = resolve_members(cfg.members, cfg.picks_file, allow_empty=cfg.range is not None)
    notifier = _notifier() if cfg.telegram else ConsoleNotifier()
    rest = BinanceREST(api_key=os.environ.get("BINANCE_API_KEY"), api_secret=os.environ.get("BINANCE_API_SECRET"))
    syms = list(cfg.symbols)
    over = {}
    if rest.api_key and rest.api_secret:
        over["taker_fee"] = max(float(rest.commission_rate(s)["takerCommissionRate"]) for s in syms)
    settings = settings_of(cfg, **over)
    brackets, src = _brackets(cfg, rest)
    specs = rest.exchange_info(syms)
    os.makedirs(os.path.dirname(os.path.abspath(cfg.db)) or ".", exist_ok=True)
    store = Store3(cfg.db)
    book = build_book(cfg, settings, brackets, store, notifier, specs)
    keep_min = 0
    if cfg.range is not None:                    # the 레인지 봇's own entries read the same 5m history (rangebot.hist_need)
        from .rangebot import hist_need
        keep_min = hist_need(cfg.range)
    custom = CustomSignals(members, syms, keep_min=keep_min) if any(m.custom for m in members) or keep_min else None
    now = rest.server_time()
    btc = BtcTrend(lambda: rest.klines("BTCUSDT", "4h", limit=500), lambda: int(time.time() * 1000)) \
        if any(m.needs_btc for m in members) else None
    rdata = research_data(rest, syms) if any(m.research for m in members) else None
    if rdata is not None:
        probs = research_problems(cfg, members)
        if probs:
            raise SystemExit("설정 문제: " + "; ".join(probs))
        t_now = rest.server_time()
        for s in syms:                           # the 7-day 1m range of the rules, before the first signal
            try:
                rdata.ensure_1m(s, t_now - t_now % MIN - RM.RData.KEEP_1M * MIN, t_now - t_now % MIN)
            except Exception as exc:  # noqa: BLE001  fetched again at the first entry
                notifier.send(WARN, f"{cfg.tag} {s} 1분봉 7일치를 못 받음(첫 진입 때 다시): {exc}"[:300])
    runner_cls, extra = ComboRunner, {}
    if cfg.trend is not None:                    # 추세판단 봇 (paperbot/trendbot.py)
        from .trendbot import TrendRunner, make_judge
        runner_cls, extra = TrendRunner, {"judge": make_judge(cfg, rest)}
    if cfg.range is not None:                    # 레인지 봇 (paperbot/rangebot.py)
        from .rangebot import RangeRunner
        runner_cls = RangeRunner
    if cfg.vote_gate is not None or cfg.vol_gate is not None:      # 'VWAP 개선판' (paperbot/entrygates.py)
        from .entrygates import make_gates
        extra["gates"] = make_gates(cfg.vote_gate, cfg.vol_gate, rest)
        extra["picture_gates"] = make_gates(cfg.vote_gate, cfg.vol_gate, rest)   # the site's picture, own caches
    if friend_bot(cfg) or cfg.adx_gate is not None or cfg.quiet_gate is not None:   # '친구 매매법' (friendsig.py)
        from .friendsig import GateChain, make_friend
        extra["friend"], fgates = make_friend(cfg, members, rest)
        if fgates is not None:
            extra["gates"] = GateChain(extra["gates"], fgates) if extra.get("gates") is not None else fgates
    runner = runner_cls(cfg, members, book, store, notifier, custom, lambda: int(time.time() * 1000),
                        lambda: book_prices(rest, syms), None, fetch_5m=lambda s, a, b: fetch_5m(rest, s, a, b), btc=btc,
                        rdata=rdata, **extra)
    if runner.cursor is None or book.last_ts is None:
        runner.start_at()
    # funding from the first minute not stepped yet: a rate already paid before a restart is never paid again
    runner.funding = FundingFeed(rest, syms, start=(book.last_ts if book.last_ts is not None else now) + MIN)
    if custom is not None:                       # closed 5m bars up to now; later gaps are filled at each boundary
        custom.fill_gaps(runner.fetch_5m, now - now % FIVE)
    store.put_state("combo_run", now, {"version": VERSION, "brackets": src, "taker_fee": settings.taker_fee,
                                       "members": [m.describe() for m in members], "config": run_config(cfg)})
    store.commit()
    notifier.send(INFO, start_text(cfg, members, book.engines[ACCOUNT].wallet))
    stop = {"flag": False}

    def on_term(signum, frame):  # noqa: ARG001
        stop["flag"] = True

    import signal as _signal
    _signal.signal(_signal.SIGTERM, on_term)
    from .health import sd_notify
    sd_notify("READY=1")
    try:
        while not stop["flag"] and (args.max_polls is None or args.max_polls > 0):
            sd_notify("WATCHDOG=1")
            try:
                runner.poll()
            except Exception as exc:  # noqa: BLE001  a failing poll is retried; the state is per minute
                runner.errors += 1
                store.conn.rollback()
                text = f"{cfg.tag} 오류(다시 시도): {type(exc).__name__}: {exc}"[:300]
                store.alert(int(time.time() * 1000), WARN, text)
                store.commit()
                if runner.errors in (1, 10, 100):
                    notifier.send(WARN, text)
            if args.max_polls is not None:
                args.max_polls -= 1
            time.sleep(cfg.poll_s)
    finally:
        store.close()
    return 0


LATER_KEYS = ("adx_gate", "quiet_gate", "take_profit_roe", "range")   # config keys of 10-24 / 10-26: in a run record
                                                                        # only when set


def run_config(cfg: ComboConfig) -> dict:
    """The config as the run record (state ``combo_run``) keeps it: every field, except a key added later that is off
    (null), so the running bots' records stay as before (the live site compares them key by key)."""
    d = dataclasses.asdict(cfg)
    for k in LATER_KEYS:
        if d.get(k) is None:
            d.pop(k, None)
    return d


def early_ko(cfg: ComboConfig) -> str:
    """The early exit in words; with the fixed take-profit (레인지 봇) "없음" says so instead of the ladder."""
    if cfg.early_exit is None and cfg.take_profit_roe is not None:
        return "없음(고정 손절과 고정 익절만)"
    return KO_EARLY.get(cfg.early_exit, cfg.early_exit)


def take_profit_text(cfg: ComboConfig) -> str:
    """The take-profit in words: "고정 익절 순ROE +10%(…)" or "계단 익절 …" (the config's ladder)."""
    if cfg.take_profit_roe is not None:
        rt = v3_settings().round_trip_cost
        lv = sorted({cfg.lev_of(s) for s in cfg.symbols}, reverse=True)
        moves = ", ".join(f"{v}배 가격 {float(cfg.take_profit_roe) / v + rt:.2%}" for v in lv)
        return f"고정 익절 순ROE +{float(cfg.take_profit_roe):.0%}(수수료·슬리피지 포함: {moves}, 계단 없음)"
    lad = cfg.ladder_spec
    return f"계단 익절 {lad.describe() if lad is not None else '설정 오류'}"


def stop_text(cfg: ComboConfig) -> str:
    if cfg.range is not None and not cfg.members:      # the 레인지 봇 on its own entries only (owners 10-31)
        from .rangebot import own_stop_words
        words = own_stop_words(cfg.range)
        if words:
            return words
    if cfg.stop_net:
        rt = v3_settings().round_trip_cost
        lv = sorted({cfg.lev_of(s) for s in cfg.symbols}, reverse=True)
        moves = ", ".join(f"{v}배 가격 {float(cfg.stop['roe']) / v - rt:.2%}" for v in lv)
        return f"순ROE -{float(cfg.stop['roe']):.0%}(수수료·슬리피지 포함: {moves})"
    if cfg.stop_mode == "roe":                     # the exchange screen's ROE before fees (the friend bot's -20 % option)
        lv = sorted({cfg.lev_of(s) for s in cfg.symbols}, reverse=True)
        moves = ", ".join(f"{v}배 가격 {float(cfg.stop['roe']) / v:.2%}" for v in lv)
        return f"ROE -{float(cfg.stop['roe']):.0%}(수수료 전: {moves})"
    if cfg.stop_mode == "atr_fit":
        return f"{cfg.stop_atr:g} ATR(안 맞으면 강제청산 안쪽으로 당김)"
    return f"{cfg.stop_atr:g} ATR"


def cmd_check(args) -> int:
    cfg = ComboConfig.from_file(args.config)
    probs = cfg.problems()
    try:
        members = resolve_members(cfg.members, cfg.picks_file, allow_empty=cfg.range is not None)
    except ComboError as exc:
        probs.append(str(exc))
        members = []
    probs += research_problems(cfg, members)
    print(f"합친 봇 설정 {args.config}")
    print(f"- 따라 읽는 규칙봇 DB: {cfg.paper_db} / 자기 DB: {cfg.db}")
    print(f"- 배수: " + ", ".join(f"{s} {cfg.lev_of(s)}배" for s in cfg.symbols) +
          f" / 증거금: {'배수%' if cfg.margin == 'leverage' else f'{float(cfg.margin):.0%}'}")
    print(f"- 손절: {stop_text(cfg)} / {take_profit_text(cfg)}")
    score_ko = "추세 점수(판단 강도+자리+최근 성적)" if cfg.trend is not None else "진입 점수"
    print(f"- 동시에 나온 신호: {' > '.join({'score': score_ko, 'timeframe': '긴 봉', 'order': '목록 순서'}[r] for r in cfg.rank)}")
    print(f"- 동전 쌍둥이 계좌: {'있음' if cfg.flip_twin else '없음'}")
    print(f"- 빠른 청산: {early_ko(cfg)}"
          + (" (첫 잠금 +10% 전까지만, 잠긴 뒤에는 계단 익절만)" if cfg.early_exit and cfg.early_exit_until_lock else ""))
    nc = [m for m in members if m.no_chase]
    if nc:
        print(f"- 추격 진입 막기: {len(nc)}개 매매법 ({', '.join(m.label for m in nc)}) — {CHASE_KO}")
    if cfg.no_weekend:
        print("- 주말(한국 시간 토·일)에는 새로 진입하지 않음(열린 포지션은 손절·익절까지 그대로)")
    for line in gate_lines(cfg) + range_lines(cfg):
        print(f"- {line}")
    if friend_bot(cfg):
        print("- 손실 리뷰: 진 거래마다 청산 메시지에 '손실 이유 후보' 한 줄(BTC 움직임·손절 전 최고·보유 시간·4시간 ADX·"
              "거래량·24시간 범위 위치·경제 발표), 같은 값을 기록 loss_review 표에")
    if cfg.macro_blackout_min:
        from . import events as EV
        now = int(time.time() * 1000)
        nxt = [e for e in EV.all_events() if e.ts_ms >= now]
        print(f"- 경제 발표 앞뒤 {cfg.macro_blackout_min}분 진입 안 함: 앞으로 일정 {len(nxt)}개"
              + (f", 마지막 {nxt[-1].ts_utc}" if nxt else " (일정 없음: data/macro_events.csv를 채우세요)"))
        probs += [f"경제 발표 일정 파일: {p}" for p in EV.problems()]
    if cfg.us_open_pause_min or cfg.us_open_pre_min:
        pre, mins = int(cfg.us_open_pre_min or 0), int(cfg.us_open_pause_min or 0)
        kst = lambda m: f"{m // 60 % 24:02d}:{m % 60:02d}"                     # noqa: E731  minutes of the KST day
        summer, winter = (22 * 60 + 30 - pre, 22 * 60 + 30 + mins), (23 * 60 + 30 - pre, 23 * 60 + 30 + mins)
        print(f"- {us_open_ko(mins, pre)} 진입 안 함 (뉴욕 09:30 개장, 평일, 미국 휴장일 제외; 한국 시간 서머타임 "
              f"{kst(summer[0])}~{kst(summer[1])} / 겨울 {kst(winter[0])}~{kst(winter[1])}) · 추세 판단·청산은 계속")
    if cfg.trend is not None:
        from .trendjudge import TrendError, TrendRules
        try:
            for line in TrendRules.from_dict(cfg.trend).describe():
                print(f"- {line}")
        except (TrendError, TypeError):
            pass                                   # the problem is in probs
    for m in members:
        print("  " + m.describe())
    for p in probs:
        print(f"[문제] {p}")
    print("준비됨" if not probs else "고칠 것이 있습니다")
    return 0 if not probs else 1


GATE_GROUPS = (("추세 반대", ("추세 반대",)), ("변동성 높음", ("변동성 높음",)), ("주말", ("주말",)),
               ("경제 발표", ("경제 발표",)), ("나스닥 개장", ("나스닥 개장",)), ("못 읽음", ("못 읽음",)),
               ("ADX 약함", ("ADX 약함",)), ("거래량 많음", ("거래량 많음",)))      # the last two: the friend bot's gates


def gate_group(why: str) -> str:
    """A FILTERED reason (_entry_block's words) in a few words for the status command's count; anything else "기타"."""
    for name, keys in GATE_GROUPS:
        if any(k in why for k in keys):
            return name
    return "기타"


def _gate_status(conn, picture: bool = True) -> None:
    """The VWAP bot's part of ``status``: how many signals each reason kept out (all, and the last 24 hours), and the
    newest picture of what the gates read for every coin (state gates_now; ``picture`` False: the friend bot, which
    keeps none)."""
    now = int(time.time() * 1000)
    tot: dict = {}
    day: dict = {}
    for ts, d in conn.execute("SELECT bar_close, data FROM signal_log WHERE status = 'FILTERED'"):
        try:
            why = str((json.loads(d) or {}).get("why") or "")
        except (TypeError, ValueError):
            why = ""
        g = gate_group(why)
        tot[g] = tot.get(g, 0) + 1
        if ts is not None and now - int(ts) <= 86_400_000:
            day[g] = day.get(g, 0) + 1
    if tot:
        print("진입 안 한 신호(이유별, 전체 / 지난 24시간): " + " · ".join(f"{g} {tot[g]} / {day.get(g, 0)}" for g in sorted(tot)))
    else:
        print("진입 안 한 신호: 아직 없음")
    if not picture:
        return
    st = conn.execute("SELECT ts, data FROM state WHERE k = ?", (GATES_NOW_KEY,)).fetchone()
    if st is None:
        print("지금 코인별 조건: 아직 없음(켜진 뒤 첫 1분, 그다음 30분마다)")
        return
    pic = json.loads(st[1])
    at = pic.get("at")
    print(f"지금 코인별 조건 ({time.strftime('%m-%d %H:%M', time.gmtime(int(at) / 1000 + 9 * 3600)) if at else '?'} KST):"
          if not pic.get("error") else f"지금 코인별 조건: 못 읽음 ({pic['error']})")
    for sym, row in (pic.get("coins") or {}).items():
        v = row.get("vote") or {}
        parts = [v.get("text") or f"{v.get('tf', '')} 판단 못 읽음"]
        for tf, x in (row.get("vol") or {}).items():
            parts.append(("변동성 높음 · " if x.get("high") else "") + (x.get("text") or f"{tf} 변동성 못 읽음"))
        print(f"  {sym.replace('USDT', '')}: " + " · ".join(parts))


def cmd_status(args) -> int:
    from .livepnl import open_ro
    conn = open_ro(args.db)
    try:
        st = conn.execute("SELECT ts, data FROM state WHERE k = 'accounts'").fetchone()
        if st is None:
            print("아직 계좌 상태가 없습니다")
            return 1
        ts, data = int(st[0]), json.loads(st[1])
        print(f"마지막 1분봉: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(ts / 1000 + 9 * 3600))} KST")
        for aid, e in data["engines"].items():
            n, pnl, wins = conn.execute("SELECT COUNT(*), COALESCE(SUM(pnl), 0), COALESCE(SUM(pnl > 0), 0) FROM trades "
                                        "WHERE account_id = ?", (aid,)).fetchone()
            p = e.get("position")
            pos = "없음" if not p else (f"{p['symbol']} {KO_SIDE.get(p['side'], p['side'])} {p['leverage']}배 "
                                       f"진입 {p['entry_price']:.6g} 손절 {p['stop_price']:.6g} "
                                       f"({p['signal']['strategy_id']} {p['signal']['timeframe']})")
            print(f"{aid}: 지갑 ${e['wallet']:,.2f}, 거래 {n}번({wins}승), 손익 ${pnl:+,.2f}, 포지션 {pos}")
        print("매매법별 (받은 신호 / 진입 / 동시 신호에서 밀림 / 진입 거절):")
        sigs = dict(conn.execute("SELECT strategy, COUNT(*) FROM signal_log GROUP BY strategy").fetchall())
        outs: dict = {}
        for status, reason, d in conn.execute("SELECT status, reason, data FROM outcomes WHERE account_id = ?",
                                              (ACCOUNT,)):
            try:
                mem = json.loads(d)["signal"]["meta"].get("member", "?")
            except (ValueError, KeyError, TypeError):
                mem = "?"
            k = outs.setdefault(mem, {"ENTERED": 0, "SKIPPED": 0, "REJECTED": 0})
            k[status] = k.get(status, 0) + 1
        for mem in sorted(set(sigs) | set(outs)):
            o = outs.get(mem, {})
            print(f"  {mem}: {sigs.get(mem, 0)} / {o.get('ENTERED', 0)} / {o.get('SKIPPED', 0)} / {o.get('REJECTED', 0)}")
        run = conn.execute("SELECT data FROM state WHERE k = 'combo_run'").fetchone()
        rcfg = (json.loads(run[0]).get("config") or {}) if run else {}
        hold_bot = rcfg.get("trend") is None and bool(rcfg.get("max_hold_bars"))
        for r in conn.execute("SELECT data FROM trades WHERE account_id = ? ORDER BY exit_time DESC LIMIT 10",
                              (ACCOUNT,)):
            t = json.loads(r[0])
            why = TIME_HOLD_KO if (t["exit_reason"] == "TIME" and hold_bot) else KO_EXIT.get(t["exit_reason"], t["exit_reason"])
            print(f"  {time.strftime('%m-%d %H:%M', time.gmtime(t['entry_time'] / 1000 + 9 * 3600))} {t['symbol']} "
                  f"{KO_SIDE.get(t['side'], t['side'])} {t['strategy_id']} {t['timeframe']} {t['leverage']}배 "
                  f"{why} 순ROE {t['roe']:+.1%} ${t['pnl']:+,.2f}")
        if rcfg.get("vote_gate") is not None or rcfg.get("vol_gate") is not None:
            _gate_status(conn)
        elif rcfg.get("adx_gate") is not None or rcfg.get("quiet_gate") is not None:
            _gate_status(conn, picture=False)
        if any(isinstance(m, dict) and m.get("strategy") == FRIEND for m in rcfg.get("members") or []):
            from .friendsig import loss_status
            for line in loss_status(conn, int(time.time() * 1000)):
                print(line)
    finally:
        conn.close()
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.combo", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", default=DEFAULT_CONFIG)
    r.add_argument("--max-polls", type=int, default=None)
    c = sub.add_parser("check-config")
    c.add_argument("--config", default=DEFAULT_CONFIG)
    s = sub.add_parser("status")
    s.add_argument("--db", default="/var/lib/paperbot/combo/combo.db")
    a = ap.parse_args(argv)
    return {"run": cmd_run, "check-config": cmd_check, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
