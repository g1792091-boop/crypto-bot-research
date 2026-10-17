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
  ``first_lock + trigger_gap``, then ``step`` steps; owners: 10% at 11%);
- one position; the signals of one step compete by ``rank`` (default: entry strength score, then the longer
  timeframe, then the member order of the config). The score is the 5-year entry study's quality score of the
  signal's strength features (paperbot/levrule.py: mean quintile 1-5); a signal without one (DeepSeek, a strategy
  without a strength definition) counts as ``no_score`` (3, the middle). The research found no edge in it; it is the
  owners' rule. Every losing candidate is recorded (outcomes: SKIPPED "lower score than entered signal").

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
from .margin import Brackets, liquidation_price
from .models import Bar, Signal
from .notify import CRITICAL, INFO, WARN, ConsoleNotifier, Notifier
from .sizing import SizeDecision
from .store3 import Store3

VERSION = "combo-v1"
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
KO_EXIT = {"SL": "손절", "LOCK": "계단 익절", "LIQ": "강제청산", "HALT": "멈춤 청산", "MANUAL": "수동 청산"}


class ComboError(ValueError):
    """A configuration the combined bot refuses (message in Korean)."""


# ====================================================================== members
@dataclass(frozen=True)
class Member:
    """One strategy of the account. ``numbers`` None: the rule bot's default numbers (its signal_log rows);
    a dict: custom numbers, computed here."""
    label: str
    kind: str                  # "core" (the 36) | "ds" (DeepSeek)
    name: str
    tf: str
    numbers: Optional[dict]
    order: int
    pick: Optional[str] = None

    @property
    def custom(self) -> bool:
        return self.numbers is not None

    def describe(self) -> str:
        what = "기본값(규칙봇 신호)" if not self.custom else \
            "커스텀값 " + ", ".join(f"{k}={v}" for k, v in sorted(self.numbers.items()))
        return f"{self.order}. {self.name} {KO_TF.get(self.tf, self.tf)} - {what}" + (f" [{self.pick}]" if self.pick else "")


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


def resolve_members(specs: list, picks_file: str = CANDIDATES_FILE, core: Optional[list] = None) -> list[Member]:
    """Config ``members`` -> Members. A spec is {"strategy", "tf"} (default numbers), {"strategy", "tf", "numbers"}
    (custom numbers) or {"pick": "<candidate league id>"} (that pick's custom numbers). Custom numbers equal to the
    defaults become a default member (the rule bot's own signals). Raises ComboError (Korean) on anything wrong."""
    if not isinstance(specs, list) or not specs:
        raise ComboError("members(매매법 목록)가 비어 있습니다")
    core = core_names() if core is None else core
    picks = None
    out, seen = [], set()
    for i, sp in enumerate(specs, 1):
        if not isinstance(sp, dict):
            raise ComboError(f"members {i}번째 항목이 {{...}} 형식이 아닙니다")
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
            kind = "core" if name in core else ("ds" if name in DS200_IDS else None)
            if kind is None:
                raise ComboError(f"{name}은(는) 규칙봇 36개에도 딥시크 44개에도 없는 매매법입니다")
            numbers = sp.get("numbers")
            if numbers is not None and not isinstance(numbers, dict):
                raise ComboError(f"{name}의 numbers는 {{이름: 값}} 형식입니다")
        if tf not in V3_TRADE_TFS:
            raise ComboError(f"{name}의 봉 {tf}: 15m/30m/1h/4h만 됩니다")
        if kind == "ds" and tf not in DS_TFS_OF.get(name, ()):
            raise ComboError(f"딥시크 {name}은(는) {tf}에서 돌지 않습니다")
        if numbers is not None:
            want = default_numbers(kind, name)
            unknown = sorted(set(numbers) - set(want))
            if unknown:
                raise ComboError(f"{name}에 없는 숫자 이름: {', '.join(unknown)} (있는 것: {', '.join(sorted(want))})")
            full = {**want, **numbers}
            numbers = None if all(_same(full[k], want[k]) for k in want) else full
        key = (kind, name, tf, json.dumps(numbers, sort_keys=True))
        if key in seen:
            raise ComboError(f"{name} {tf}가 같은 숫자로 두 번 들어 있습니다")
        seen.add(key)
        label = pick or (f"{name}@{tf}" if numbers is None else f"{name}@{tf}~" +
                         hashlib.sha1(json.dumps(numbers, sort_keys=True).encode()).hexdigest()[:6])
        out.append(Member(label=label, kind=kind, name=name, tf=tf, numbers=numbers, order=i, pick=pick))
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
    ladder: dict = field(default_factory=lambda: {"first_lock": 0.10, "step": 0.05, "trigger_gap": 0.01})
    rank: tuple = RANK_KEYS
    no_score: float = 3.0
    flip_twin: bool = True
    symbols: tuple = V3_SYMBOLS
    poll_s: float = 2.0
    max_signal_age_s: float = 150.0
    picks_file: str = CANDIDATES_FILE
    brackets_file: Optional[str] = None
    telegram: bool = True

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
        elif not (0 < self.stop_atr <= 10):
            out.append("stop.atr는 0~10입니다")
        lad = self.ladder
        if not (0 < float(lad.get("first_lock", 0)) < 1 and 0 < float(lad.get("step", 0)) < 1
                and 0 < float(lad.get("trigger_gap", 0)) < 1):
            out.append("ladder의 first_lock, step, trigger_gap은 0~1 사이 비율입니다")
        bad = [r for r in self.rank if r not in RANK_KEYS]
        if bad or not self.rank:
            out.append(f"rank는 {', '.join(RANK_KEYS)}의 순서입니다")
        if not 30 <= float(self.max_signal_age_s) <= 170:
            out.append("max_signal_age_s는 30~170초입니다(실행기는 180초 넘은 진입을 따라가지 않습니다)")
        bad = [s for s in self.symbols if s not in V3_SYMBOLS]
        if bad:
            out.append(f"symbols: 규칙봇 6개 코인만 됩니다({', '.join(bad)})")
        return out


def settings_of(cfg: ComboConfig, **over):
    """The engine rules: paper v4's (fees, slippage, bust, no drawdown halt) with the combined bot's ladder, loss cap
    and liquidation buffer. Its own version string, so its ledger never mixes with the rule bot's."""
    lad = cfg.ladder
    kw = dict(version=VERSION, initial_equity=float(cfg.initial_equity), symbols=tuple(cfg.symbols),
              symbol_priority=tuple(cfg.symbols), ladder_first_lock=float(lad["first_lock"]),
              ladder_step=float(lad["step"]), ladder_trigger_gap=float(lad["trigger_gap"]),
              liq_buffer_atr_mult=float(cfg.liq_buffer_atr), liq_buffer_min_frac=float(cfg.liq_buffer_min_frac),
              max_loss_frac=float(cfg.max_loss_frac), bust_below=0.01 * float(cfg.initial_equity))
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
        if sig.atr is not None:
            buffer = max(buffer, self.s.liq_buffer_atr_mult * sig.atr)
        if (stop - liq) * side < buffer:
            return SizeDecision(False, reasons=reasons + [f"{lev}x: stop {stop:.6g} too close to liq {liq:.6g}"])
        return SizeDecision(True, "combo", lev, margin, qty, liq, qty * per, reasons)

    def take_profit(self, sig, entry, dec):
        return math.nan                   # ladder: no take-profit order


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
        if c.stop_mode == "roe":
            dist = raw * float(c.stop["roe"]) / lev
            rule = f"ROE -{float(c.stop['roe']):.0%} at {lev}x"
        else:
            if atr is None or not atr > 0:
                return None, (sig, "no ATR for the stop")
            dist = c.stop_atr * atr
            rule = f"{c.stop_atr:g} x ATR"
            if c.stop_mode == "atr_fit":
                # the sizing checks the stop against the liquidation price of the FILL (the reference price plus
                # slippage): widest distance from the reference price = fill x L - slippage - buffer (a hair less)
                fill = raw * (1 + sig.side * self.s.slippage_frac)
                notional = self.wallet * c.margin_frac(lev) * lev
                room = liq_distance(sig.side, fill, lev, max(notional, 1.0), self.brackets[sig.symbol]) * fill
                buffer = max(self.s.liq_buffer_min_frac * fill, self.s.liq_buffer_atr_mult * atr)
                widest = (room - abs(fill - raw) - buffer) * (1 - 1e-6)
                if dist > widest:
                    if widest < float(c.stop.get("min_atr", 1.0)) * atr:
                        return None, (sig, f"{lev}x: even {float(c.stop.get('min_atr', 1.0)):g} x ATR does not fit "
                                           f"inside liquidation")
                    rule = f"{c.stop_atr:g} x ATR pulled in to {widest / atr:.2f} x ATR (fits {lev}x)"
                    dist = widest
        return replace(sig, meta={**sig.meta, "stop_dist": dist, "stop_rule": rule}), None


def make_cls(cfg: ComboConfig):
    """The engine class AccountBook builds (accounts.AccountBook._make calls it like PaperEngine)."""
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
    want = {(m.name, m.tf): m for m in members if not m.custom}
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

    def __init__(self, members: list[Member], symbols, lib=None):
        self.members = [m for m in members if m.custom]
        self.symbols = list(symbols)
        self._lib = lib
        self.agg = Aggregator(["5m"])
        self.keep = self.window_need() + 12 if self.members else 0
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
        if not self.members or bar.symbol not in self.hist:
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
        return out

    def frame(self, m: Member, symbol: str, boundary: int):
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
                 funding: Optional[FundingFeed] = None, fetch_5m: Optional[Callable] = None):
        self.cfg, self.members, self.book, self.store = cfg, members, book, store
        self.notifier, self.custom, self.now_ms, self.prices, self.funding = notifier, custom, now_ms, prices, funding
        self.fetch_5m = fetch_5m
        st = store.get_state(STATE_KEY)
        st = st[1] if st else {}
        self.cursor: Optional[int] = st.get("cursor")
        self.queue: list[Queued] = [Queued(int(q["bar_close"]), q["signal"]) for q in st.get("queue", [])]
        self.counts: dict = st.get("counts", {})
        self.errors = 0

    # ---- state
    def _save_state(self, ts: int) -> None:
        self.store.put_state(STATE_KEY, ts, {
            "cursor": self.cursor, "queue": [{"bar_close": q.bar_close, "signal": q.signal} for q in self.queue],
            "counts": self.counts, "version": VERSION,
            "members": [m.label for m in self.members]})

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
            self.queue.append(Queued(int(row["bar_close"]), dataclasses.asdict(sig)))
            self._log(sig, "SUBMITTED", "rule")
        self.cursor = int(top)
        now = self.now_ms()
        if self.funding is not None:
            self.funding.poll(now)
        n = 0
        for ts in sorted(minutes):
            self._submit_due(ts)
            before = {aid: (e.position.entry_time if e.position else None, len(e.trades))
                      for aid, e in self.book.engines.items()}
            self.book.step(ts, minutes[ts], self.funding.take(ts) if self.funding else None)
            self._tell(before)
            for b in minutes[ts].values():
                if self.custom is not None:
                    self.custom.add_1m(b)
            boundary = ts + MIN
            if boundary % FIVE == 0 and self.custom is not None and self.custom.members:
                self._custom(boundary)
            self._save_state(ts)                 # the queue and the cursor with the engines, in one commit
            self.book.save(ts)
            n += 1
        if rows and not minutes:
            self._save_state(self.book.last_ts or 0)
            self.book.save(self.book.last_ts or 0)
        self.store.put_state("heartbeat", now, {"last_step": self.book.last_ts, "queue": len(self.queue)})
        self.store.commit()
        return n

    def _submit_due(self, ts: int) -> None:
        """Signals whose bar closed at or before this minute's open go in now (the engine fills them in this step)."""
        keep, now = [], self.now_ms()
        for q in self.queue:
            if q.bar_close > ts:
                keep.append(q)
                continue
            sig = _sig_from(q.signal)
            age = now - int(sig.meta.get("ref_time") or q.bar_close)
            label = sig.meta.get("member", sig.strategy_id)
            for aid, e in self.book.engines.items():
                s = sig if aid == ACCOUNT else replace(sig, side=flip_side(aid, sig), meta=dict(sig.meta))
                if age > self.cfg.max_signal_age_s * 1000:
                    e._record(s, "REJECTED", "late", ts, age_ms=age)
                    continue
                e.submit(s)
            self._count(label, "late" if age > self.cfg.max_signal_age_s * 1000 else "submitted")
        self.queue = keep

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
            bid, ask = px.get(g["symbol"], (None, None))
            ref = ask if g["side"] > 0 else bid
            sig = make_signal(self.cfg, m, boundary, g["symbol"], g["side"], g["atr"], ref, ready, ready - boundary,
                              g["ctx"], "custom")
            self.queue.append(Queued(boundary, dataclasses.asdict(sig)))
            self._log(sig, "SUBMITTED", "custom")

    def _log(self, sig: Signal, status: str, source: str) -> None:
        self.store.log_signals([{
            "bar_close": sig.ts + 1, "timeframe": sig.timeframe, "strategy": sig.meta.get("member", sig.strategy_id),
            "symbol": sig.symbol, "side": sig.side, "atr": sig.atr, "ref_price": sig.meta.get("ref_price"),
            "ref_time": sig.meta.get("ref_time"), "delay_ms": sig.meta.get("delay_ms"), "status": status,
            "data": {"source": source, "score": sig.meta.get("score_raw"), "strategy": sig.strategy_id}}])

    # ---- messages
    def _tell(self, before: dict) -> None:
        e = self.book.engines.get(ACCOUNT)
        if e is None or not self.cfg.telegram:
            return
        was_entry, was_n = before.get(ACCOUNT, (None, 0))
        for t in e.trades[was_n:]:
            self.notifier.send(INFO, (
                f"[합친 봇 페이퍼] 청산 {t.symbol} {KO_SIDE.get(t.side, t.side)} {t.strategy_id} "
                f"{KO_TF.get(t.timeframe, t.timeframe)}: {KO_EXIT.get(t.exit_reason, t.exit_reason)}, "
                f"순ROE {t.roe:+.1%}, ${t.pnl:+,.2f}, 지갑 ${t.equity_after:,.2f}"))
        p = e.position
        if p is not None and p.entry_time != was_entry:
            m = p.signal.meta
            self.notifier.send(INFO, (
                f"[합친 봇 페이퍼] 진입 {p.symbol} {KO_SIDE.get(p.side, p.side)} {p.signal.strategy_id} "
                f"{KO_TF.get(p.signal.timeframe, p.signal.timeframe)} ({m.get('member')}), {p.leverage}배, "
                f"증거금 ${p.margin:,.2f}, 손절 {p.stop_price:.6g} ({m.get('stop_rule', '')}), "
                f"점수 {p.signal.score:.2f}"))


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


def cmd_run(args) -> int:
    from .binance import BinanceREST
    from .live import _notifier
    from .live3 import book_prices, fetch_5m
    cfg = ComboConfig.from_file(args.config)
    probs = cfg.problems()
    if probs:
        raise SystemExit("설정 문제: " + "; ".join(probs))
    members = resolve_members(cfg.members, cfg.picks_file)
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
    custom = CustomSignals(members, syms) if any(m.custom for m in members) else None
    now = rest.server_time()
    runner = ComboRunner(cfg, members, book, store, notifier, custom, lambda: int(time.time() * 1000),
                         lambda: book_prices(rest, syms), None, fetch_5m=lambda s, a, b: fetch_5m(rest, s, a, b))
    if runner.cursor is None or book.last_ts is None:
        runner.start_at()
    # funding from the first minute not stepped yet: a rate already paid before a restart is never paid again
    runner.funding = FundingFeed(rest, syms, start=(book.last_ts if book.last_ts is not None else now) + MIN)
    if custom is not None:                       # closed 5m bars up to now; later gaps are filled at each boundary
        custom.fill_gaps(runner.fetch_5m, now - now % FIVE)
    store.put_state("combo_run", now, {"version": VERSION, "brackets": src, "taker_fee": settings.taker_fee,
                                       "members": [m.describe() for m in members], "config": dataclasses.asdict(cfg)})
    store.commit()
    notifier.send(INFO, f"[합친 봇 페이퍼] 시작: 매매법 {len(members)}개({sum(m.custom for m in members)}개 커스텀값), "
                        f"BTC {cfg.lev_of('BTCUSDT')}배·나머지 {cfg.lev_of('ETHUSDT')}배, 손절 {stop_text(cfg)}, "
                        f"포지션 1개, 지갑 ${book.engines[ACCOUNT].wallet:,.2f}")
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
                text = f"[합친 봇 페이퍼] 오류(다시 시도): {type(exc).__name__}: {exc}"[:300]
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


def stop_text(cfg: ComboConfig) -> str:
    if cfg.stop_mode == "roe":
        return f"ROE -{float(cfg.stop['roe']):.0%}"
    if cfg.stop_mode == "atr_fit":
        return f"{cfg.stop_atr:g} ATR(안 맞으면 강제청산 안쪽으로 당김)"
    return f"{cfg.stop_atr:g} ATR"


def cmd_check(args) -> int:
    cfg = ComboConfig.from_file(args.config)
    probs = cfg.problems()
    try:
        members = resolve_members(cfg.members, cfg.picks_file)
    except ComboError as exc:
        probs.append(str(exc))
        members = []
    print(f"합친 봇 설정 {args.config}")
    print(f"- 따라 읽는 규칙봇 DB: {cfg.paper_db} / 자기 DB: {cfg.db}")
    print(f"- 배수: " + ", ".join(f"{s} {cfg.lev_of(s)}배" for s in cfg.symbols) +
          f" / 증거금: {'배수%' if cfg.margin == 'leverage' else f'{float(cfg.margin):.0%}'}")
    print(f"- 손절: {stop_text(cfg)} / 계단 익절: 순ROE {cfg.ladder['first_lock'] + cfg.ladder['trigger_gap']:.0%}에서 "
          f"{cfg.ladder['first_lock']:.0%} 잠금, 이후 {cfg.ladder['step']:.0%}씩")
    print(f"- 동시에 나온 신호: {' > '.join({'score': '진입 점수', 'timeframe': '긴 봉', 'order': '목록 순서'}[r] for r in cfg.rank)}")
    print(f"- 동전 쌍둥이 계좌: {'있음' if cfg.flip_twin else '없음'}")
    for m in members:
        print("  " + m.describe())
    for p in probs:
        print(f"[문제] {p}")
    print("준비됨" if not probs else "고칠 것이 있습니다")
    return 0 if not probs else 1


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
        for r in conn.execute("SELECT data FROM trades WHERE account_id = ? ORDER BY exit_time DESC LIMIT 10",
                              (ACCOUNT,)):
            t = json.loads(r[0])
            print(f"  {time.strftime('%m-%d %H:%M', time.gmtime(t['entry_time'] / 1000 + 9 * 3600))} {t['symbol']} "
                  f"{KO_SIDE.get(t['side'], t['side'])} {t['strategy_id']} {t['timeframe']} {t['leverage']}배 "
                  f"{KO_EXIT.get(t['exit_reason'], t['exit_reason'])} 순ROE {t['roe']:+.1%} ${t['pnl']:+,.2f}")
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
