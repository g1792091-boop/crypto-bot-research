"""Lab tests the agent staff can ask for: five-year what-if tests run by code (no model).

A strategy room's specialist may request ONE of a few fixed test templates. Code runs it on the
cached five-year signals and decides with a fixed gate; nobody (not the approver, not the owners'
chat) can overrule the gate.

Templates (``TEMPLATES``; nothing else can be requested):
  stop_atr        initial stop at k x ATR14 instead of 2 x ATR (k in 1.5, 2.5, 3.0). Sizing follows
                  the stop like the paper engine does (a wider stop can mean a lower leverage tier).
  lock_start      first profit-lock level of the stepped ladder (0.15, 0.20 or 0.30 instead of
                  0.10); the step stays 0.05 and the trigger gap 0.02 (paperbot.ladder.LadderSpec).
  skip_tag        do not take signals that carry one entry-context tag of paperbot.cards.TAGS (only
                  tags computable from past bars). Tags are computed causally for every signal
                  with paperbot.context.entry_context + ADX/DI, like sigservice.chart_context, and
                  tested with the SAME cards.TAGS functions on a card-like dict.
  timeframe_only  descriptive: the strategy's results per timeframe under the current rules. It
                  never passes the gate (every account already is one strategy on one timeframe).

Outcomes per signal are the paper v3 exits of research/strategy_profiles/profiles.py
(``_sizer`` and ``_scan`` imported and parameterised; there is no second exit engine here):
every sized signal of the strategy on the six coins, entry at the next bar's open + slippage,
stop k x ATR14, leverage from ``size_position``, the stepped profit lock, real costs, no
account and no position limit. With the default parameters the numbers equal profiles.json
(tests/test_labtests.py checks this against profiles._job).

Periods (signal bar time, UTC):
  1  2021-08-01 .. 2024-07-01   (profiles.py "is")
  2  2024-07-01 .. 2026-09-30   (profiles.py "cf")
  3  2020-01-01 .. 2021-08-01   only when the pre-2021 cache is present
Per period: trades and mean net ROE per trade for the current rule (baseline) and the change
(variant), the difference, and a one-sided week-block bootstrap p for "the change is better"
(2,000 resamples of Monday 00:00 UTC weeks, both arms resampled together; p = (1 + resamples
with difference <= 0) / 2,001).

``gate(result, n_trials_so_far)`` passes only if ALL of:
  (a) period-1 improvement with one-sided p < 0.05 / max(1, n_trials_so_far)  (Bonferroni over
      the room's number of tests, stated in the reasons; actions.copy_check re-judges a stored
      test with the room's CURRENT count when it is proposed),
  (b) period 2 improves too, with p < 0.05 and >= 100 variant trades,
  (c) period 3 improves too when it has data (baseline >= 30 trades there); a variant that keeps
      fewer than 30 of them there is "not replicated", not "no data",
  (d) the variant's own mean ROE per trade > 0 in periods 1 and 2,
  (e) >= 300 variant trades in period 1,
  (f) stop_atr only: the improvement is not just the leverage change. ROE on margin is
      leverage x price return, and size_position picks a lower leverage for a wider stop, so a
      losing strategy "loses less" with any wider stop. The mean return per unit of notional
      (ROE / leverage) must improve too, in periods 1 and 2.
Per arm the table also shows mean leverage, return per notional and P&L on equity (ROE x the
tier's margin share: 50x/40x 40%, 30x 30%, 20x 20%).

LabData reads ``sig_<tf>_<COIN>.npz`` files (keys ts [int64 ns, bar open, UTC], o, h, l, c, atr,
s__<STRATEGY>) as written by research/paper_rules/rules_bt.py ``signals`` or
``python -m paperbot.agents.labdata build``; the pre-2021 cache (same format) is optional.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import time
from collections import OrderedDict
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd

from .. import cards, sweepsig
from ..context import HTF, REGIME_N, entry_context
from ..ladder import LadderSpec

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILES_PY = os.path.join(ROOT, "research", "strategy_profiles", "profiles.py")

TFS = ("5m", "15m", "30m", "1h", "4h")
BASE_K = 2.0
BASE_LADDER = LadderSpec()
N_BOOT = 2000
ALPHA = 0.05
MIN_TRADES_P1 = 300
MIN_TRADES_P2 = 100
MIN_TRADES_P3 = 30

# (id, start, end, cache). Signal bar time in [start, end).
PERIODS = (("1", "2021-08-01", "2024-07-01", "main"),
           ("2", "2024-07-01", "2026-09-30", "main"),
           ("3", "2020-01-01", "2021-08-01", "pre2021"))

# cards.TAGS names computable from past bars at the signal (entry-context tags only)
SKIP_TAGS = ("추세 반대 진입", "상위 봉 추세 반대", "횡보장 진입", "추세 약함 (ADX 20 미만)", "DI 방향 반대",
             "많이 오른/내린 뒤 추격", "최근 범위 끝에서 진입")
TAG_TESTS = {name: test for name, test in cards.TAGS if name in SKIP_TAGS}
assert set(TAG_TESTS) == set(SKIP_TAGS), "SKIP_TAGS must be cards.TAGS names"

TEMPLATES = {
    "stop_atr": {"k": (1.5, 2.5, 3.0)},
    "lock_start": {"first_lock": (0.15, 0.20, 0.30)},
    "skip_tag": {"tag": SKIP_TAGS},
    "timeframe_only": {},
}
DESCRIPTIVE = ("timeframe_only",)

# for the prompts / packets: what each template means, in plain Korean
TEMPLATE_HELP_KO = {
    "stop_atr": "처음 손절폭을 k x ATR로 바꿔 보기 (지금 2 ATR). k는 1.5, 2.5, 3.0 중 하나.",
    "lock_start": "계단식 익절의 첫 잠금 수익률을 바꿔 보기 (지금 10%). first_lock은 0.15, 0.20, 0.30 중 하나. "
                  "계단 간격 5%, 발동 여유 2%는 그대로.",
    "skip_tag": "진입 순간의 차트 상황 태그 하나가 붙은 신호를 건너뛰어 보기. tag는 " + ", ".join(SKIP_TAGS) + " 중 하나.",
    "timeframe_only": "시간봉별 성적을 지금 규칙 그대로 보여 주기 (설명용, 통과 판정 없음).",
}

_STRAT_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


class SpecError(ValueError):
    """A test request outside the allowed templates/values (message in Korean)."""


# ---------------------------------------------------------------------------------------------
# the paper v3 exit engine of research/strategy_profiles/profiles.py
# ---------------------------------------------------------------------------------------------
_P = None


def profiles_module():
    """research/strategy_profiles/profiles.py, loaded once under a private module name (it puts
    the repo root and research/paper_rules on sys.path itself, for rules_bt)."""
    global _P
    if _P is None:
        name = "_paperbot_lab_profiles"
        mod = sys.modules.get(name)
        if mod is None:
            spec = importlib.util.spec_from_file_location(name, PROFILES_PY)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        _P = mod
    return _P


def signal_outcomes(b: dict, sg: np.ndarray, lo: int, n_end: int, tf: str, k_stop: float = BASE_K,
                    ladder: Optional[LadderSpec] = None, sizer=None) -> dict:
    """Per-signal paper v3 outcome for signals on bars [lo, n_end - 1) (entry bar i + 1 < n_end),
    exactly as profiles._job does for one strategy: sized with profiles._sizer(k_stop), exits from
    profiles._scan in the same growing look-ahead passes. Returns arrays idx, side, lev, roe,
    reason (0 stop, 1 lock, 2 liquidation, 3 still open), held (bars), done (sized and closed)."""
    P = profiles_module()
    RB = P.RB
    L = sweepsig.lib()
    n = len(b["ts"])
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    lo, n_end = int(lo), int(min(n_end, n))
    idx = np.nonzero(sg[lo:max(lo, n_end - 1)])[0] + lo
    a = b["atr"][idx]
    ok = np.isfinite(a) & (a > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
    idx = idx[ok]
    side = sg[idx].astype(int)
    raw = b["o"][idx + 1]
    sizer = sizer or P._sizer(k_stop)
    ll = np.array([sizer(int(s), float(x)) for s, x in zip(side, b["atr"][idx] / raw)]).reshape(-1, 2)
    lev, liq_frac = ll[:, 0], ll[:, 1]
    sized = lev > 0
    res = {k: np.full(len(idx), np.nan) for k in ("held", "roe", "reason")}
    todo = np.nonzero(sized)[0]
    for H in (64, 512, 4096):                                  # the passes of profiles._job
        if not len(todo):
            break
        nxt = []
        step = max(32, 256_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            r = P._scan(b, idx[sel], side[sel], lev[sel], liq_frac[sel], H, n, f_bar, k_stop=k_stop, ladder=ladder)
            keep = r["done"] | (H == 4096) | (idx[sel] + H >= n - 1)
            for k in ("held", "roe", "reason"):
                res[k][sel[keep]] = r[k][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    done = sized & (res["reason"] < 3)
    return dict(idx=idx, side=side, lev=lev, roe=res["roe"], reason=res["reason"], held=res["held"],
                sized=sized, done=done)


# ---------------------------------------------------------------------------------------------
# causal entry context per signal (for skip_tag)
# ---------------------------------------------------------------------------------------------
class _Bar:
    """Just the fields paperbot.context reads (a light stand-in for models.Bar)."""
    __slots__ = ("open", "high", "low", "close")

    def __init__(self, o, h, lo, c):
        self.open, self.high, self.low, self.close = o, h, lo, c


def _htf_groups(ts_ms: np.ndarray, o, h, lo, c, htf_ms: int):
    """Higher-timeframe bars aggregated from the timeframe's own bars (UTC-aligned bins,
    like resample_ohlcv); a leading bin that opened before the first bar is dropped, as
    recorder.build_frames does. Returns (bin open ms, list of _Bar)."""
    if not len(ts_ms):
        return np.zeros(0, np.int64), []
    g = ts_ms // htf_ms
    starts = np.r_[0, np.nonzero(np.diff(g))[0] + 1]
    g_open = g[starts] * htf_ms
    go = o[starts]
    gh = np.maximum.reduceat(h, starts)
    gl = np.minimum.reduceat(lo, starts)
    gc = c[np.r_[starts[1:] - 1, len(c) - 1]]
    keep = g_open >= ts_ms[0]
    bars = [_Bar(float(a), float(b_), float(x), float(y)) for a, b_, x, y, k in zip(go, gh, gl, gc, keep) if k]
    return g_open[keep], bars


def contexts_for(b: dict, tf: str, idx: Sequence[int], adx=None) -> dict:
    """{i: ctx} for signal bars ``i``: the chart situation on the bar's close from that bar and
    earlier bars only, built like sigservice.chart_context (last REGIME_N + 60 bars of the
    timeframe, last REGIME_N[htf] + 5 closed higher-timeframe bars, ADX/DI 14 of the locked
    indicator code, floats rounded to 6 places)."""
    L = sweepsig.lib()
    idx = sorted({int(i) for i in idx})
    if not idx:
        return {}
    n_reg = REGIME_N.get(tf, 60)
    win = n_reg + 60
    tf_ms = L.tf_minutes(tf) * 60_000
    ts_ms = (np.asarray(b["ts"], np.int64) // 1_000_000)
    o, h, lo, c = (np.asarray(b[k], float) for k in ("o", "h", "l", "c"))
    if adx is None:
        adx = adx_arrays(b)
    a_adx, a_pdi, a_mdi = adx
    live: dict = {}                    # bar objects of the current windows only (idx is sorted)
    oldest = 0

    def bar(j):
        x = live.get(j)
        if x is None:
            x = live[j] = _Bar(float(o[j]), float(h[j]), float(lo[j]), float(c[j]))
        return x
    htf = HTF.get(tf)
    g_open, gbars = (_htf_groups(ts_ms, o, h, lo, c, L.tf_minutes(htf) * 60_000) if htf
                     else (np.zeros(0, np.int64), []))
    g_close = g_open + (L.tf_minutes(htf) * 60_000 if htf else 0)
    n_h = REGIME_N.get(htf, 30) + 5 if htf else 0
    out = {}
    for i in idx:
        s0 = max(0, i - win + 1)
        for j in range(oldest, s0):
            live.pop(j, None)
        oldest = max(oldest, s0)
        bars = [bar(j) for j in range(s0, i + 1)]
        k = int(np.searchsorted(g_close, ts_ms[i] + tf_ms, side="right")) if htf else 0
        hb = gbars[max(0, k - n_h):k] if k else []
        ctx = entry_context(tf, bars, hb)
        for key, arr in (("adx", a_adx), ("di_plus", a_pdi), ("di_minus", a_mdi)):
            v = float(arr[i])
            ctx[key] = v if np.isfinite(v) else None
        out[i] = {k2: (round(v, 6) if isinstance(v, float) else v) for k2, v in ctx.items()}
    return out


def adx_arrays(b: dict):
    """ADX, +DI, -DI (14) over the whole cached series (the indicator is causal)."""
    L = sweepsig.lib()
    df = pd.DataFrame({"open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"]})
    adx, pdi, mdi = L.fg.adx_dmi(df, 14)
    return adx.to_numpy(float), pdi.to_numpy(float), mdi.to_numpy(float)


def has_tag(tag: str, side: int, ctx: dict) -> bool:
    """cards.TAGS test on a card-like dict holding only what is known at entry."""
    c = {"side": int(side), "ctx": ctx or {}, "reason": None, "best_roe": None, "hold_bars": None}
    return cards._safe(TAG_TESTS[tag], c)


def tag_bits(side: int, ctx: dict) -> int:
    """Bit k set when SKIP_TAGS[k] applies to a ``side`` entry in ``ctx``."""
    return sum(1 << k for k, tag in enumerate(SKIP_TAGS) if has_tag(tag, side, ctx))


# ---------------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------------
class LabData:
    """Signal caches for the lab. ``main_dir``: periods 1-2 (default env LAB_DATA_DIR);
    ``pre2021_dir``: period 3 (default env LAB_PRE2021_DIR, else ``<main_dir>/pre2021`` if
    present). Everything is read-only; loaded arrays, outcomes and per-bar tag bits are cached
    in memory (a few bars files at a time)."""

    COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
    BAR_KEYS = ("ts", "o", "h", "l", "c", "atr")

    def __init__(self, main_dir: Optional[str] = None, pre2021_dir: Optional[str] = None,
                 max_cached: int = 12):
        self.main_dir = main_dir or os.environ.get("LAB_DATA_DIR") or None
        if pre2021_dir is None:
            pre2021_dir = os.environ.get("LAB_PRE2021_DIR") or None
            if pre2021_dir is None and self.main_dir and os.path.isdir(os.path.join(self.main_dir, "pre2021")):
                pre2021_dir = os.path.join(self.main_dir, "pre2021")
        self.pre2021_dir = pre2021_dir
        self.max_cached = max_cached
        self._bars: "OrderedDict[tuple, dict]" = OrderedDict()
        self._sig: dict = {}
        self._out: "OrderedDict[tuple, dict]" = OrderedDict()
        self._bits: dict = {}
        self._adx: dict = {}
        self._sizers: dict = {}

    @classmethod
    def from_env(cls) -> Optional["LabData"]:
        d = cls()
        return d if d.available() else None

    def dir_of(self, source: str) -> Optional[str]:
        return self.main_dir if source == "main" else self.pre2021_dir

    def path(self, source: str, tf: str, coin: str) -> Optional[str]:
        d = self.dir_of(source)
        return os.path.join(d, f"sig_{tf}_{coin}.npz") if d else None

    def coins(self, source: str, tf: str) -> list[str]:
        return [c for c in self.COINS if (p := self.path(source, tf, c)) and os.path.exists(p)]

    def available(self, source: str = "main") -> bool:
        return any(self.coins(source, tf) for tf in TFS)

    def info(self) -> dict:
        return {"main_dir": self.main_dir, "pre2021_dir": self.pre2021_dir,
                "main": {tf: self.coins("main", tf) for tf in TFS},
                "pre2021": {tf: self.coins("pre2021", tf) for tf in TFS} if self.pre2021_dir else {}}

    def strategies(self, tf: str = "1h") -> list[str]:
        for source in ("main", "pre2021"):
            cs = self.coins(source, tf)
            if cs:
                with np.load(self.path(source, tf, cs[0])) as z:
                    return [k[3:] for k in z.files if k.startswith("s__")]
        return []

    def bars(self, source: str, tf: str, coin: str) -> Optional[dict]:
        key = (source, tf, coin)
        if key in self._bars:
            self._bars.move_to_end(key)
            return self._bars[key]
        p = self.path(source, tf, coin)
        if not p or not os.path.exists(p):
            return None
        with np.load(p) as z:
            b = {k: np.asarray(z[k]) for k in self.BAR_KEYS}
        b["ts"] = b["ts"].astype(np.int64)
        for k in ("o", "h", "l", "c", "atr"):
            b[k] = b[k].astype(float)
        self._bars[key] = b
        while len(self._bars) > self.max_cached:
            old, _ = self._bars.popitem(last=False)
            self._sig = {k: v for k, v in self._sig.items() if k[:3] != old}
            self._adx.pop(old, None)
        return b

    def signal(self, source: str, tf: str, coin: str, strategy: str) -> Optional[np.ndarray]:
        key = (source, tf, coin, strategy)
        if key not in self._sig:
            p = self.path(source, tf, coin)
            if not p or not os.path.exists(p):
                return None
            with np.load(p) as z:
                k = f"s__{strategy}"
                self._sig[key] = np.asarray(z[k]).astype(np.int8) if k in z.files else None
        return self._sig[key]

    def sizer(self, k_stop: float):
        if k_stop not in self._sizers:
            self._sizers[k_stop] = profiles_module()._sizer(k_stop)
        return self._sizers[k_stop]

    def outcomes(self, source: str, tf: str, coin: str, strategy: str, lo: int, n_end: int,
                 k_stop: float = BASE_K, first_lock: float = BASE_LADDER.first_lock) -> Optional[dict]:
        key = (source, tf, coin, strategy, lo, n_end, float(k_stop), float(first_lock))
        if key in self._out:
            self._out.move_to_end(key)
            return self._out[key]
        b, sg = self.bars(source, tf, coin), self.signal(source, tf, coin, strategy)
        if b is None or sg is None:
            return None
        lad = None if first_lock == BASE_LADDER.first_lock else LadderSpec(first_lock=float(first_lock))
        r = signal_outcomes(b, sg, lo, n_end, tf, k_stop=float(k_stop), ladder=lad, sizer=self.sizer(float(k_stop)))
        self._out[key] = r
        while len(self._out) > 8 * self.max_cached:
            self._out.popitem(last=False)
        return r

    def _adx_of(self, key: tuple, b: dict):
        if key not in self._adx:
            self._adx[key] = adx_arrays(b)
        return self._adx[key]

    def contexts(self, source: str, tf: str, coin: str, idx: Sequence[int]) -> dict:
        """{i: ctx} of signal bars (not cached; for inspection)."""
        b = self.bars(source, tf, coin)
        return contexts_for(b, tf, idx, self._adx_of((source, tf, coin), b))

    def tagged(self, source: str, tf: str, coin: str, idx: np.ndarray, side: np.ndarray, tag: str) -> np.ndarray:
        """True where a ``side`` entry on bar ``idx`` carries ``tag`` (cached as bits per bar)."""
        key = (source, tf, coin)
        b = self.bars(source, tf, coin)
        bits = self._bits.get(key)
        if bits is None:
            bits = self._bits[key] = np.full((2, len(b["ts"])), -1, np.int16)   # rows: long, short
        idx = np.asarray(idx, np.int64)
        miss = np.unique(idx[bits[0, idx] < 0])
        if len(miss):
            for i, ctx in contexts_for(b, tf, miss, self._adx_of(key, b)).items():
                bits[0, i], bits[1, i] = tag_bits(1, ctx), tag_bits(-1, ctx)
        row = np.where(np.asarray(side) > 0, bits[0, idx], bits[1, idx])
        return ((row >> SKIP_TAGS.index(tag)) & 1).astype(bool)


# ---------------------------------------------------------------------------------------------
# specs
# ---------------------------------------------------------------------------------------------
def normalize_spec(spec: Any, strategy: Optional[str] = None) -> dict:
    """The allowed form of a test request, or SpecError (Korean message). ``strategy`` (the
    room's strategy) is enforced when given: a room can only test its own strategy."""
    if not isinstance(spec, dict):
        raise SpecError("시험 요청은 JSON 객체여야 합니다.")
    t = spec.get("template")
    if not isinstance(t, str) or t not in TEMPLATES:
        raise SpecError(f"없는 시험 종류입니다: {str(t)[:40]!r}. 가능한 것: {', '.join(TEMPLATES)}.")
    s = spec.get("strategy")
    if strategy is not None:
        if s not in (None, "", strategy):     # a tuple: == only, never a hash (a list value is fine)
            raise SpecError("이 방의 전략만 시험할 수 있습니다.")
        s = strategy
    if not isinstance(s, str) or not _STRAT_RE.match(s):
        raise SpecError("시험할 전략 이름이 없습니다.")
    out: dict = {"template": t, "strategy": s}
    tf = spec.get("timeframe")
    if t in DESCRIPTIVE:
        if tf not in (None, ""):
            if tf not in TFS:
                raise SpecError(f"시간봉은 {', '.join(TFS)} 중 하나여야 합니다.")
            out["timeframe"] = tf
    else:
        if tf not in TFS:
            raise SpecError(f"시간봉(timeframe)을 {', '.join(TFS)} 중 하나로 정해야 합니다.")
        out["timeframe"] = tf
    for name, allowed in TEMPLATES[t].items():
        v = spec.get(name)
        if name == "tag":
            v = v.strip() if isinstance(v, str) else v
            if v not in allowed:
                raise SpecError(f"tag는 다음 중 하나여야 합니다: {', '.join(allowed)}.")
            out[name] = v
        else:
            try:
                x = float(v) if not isinstance(v, bool) else float("nan")
            except (TypeError, ValueError, OverflowError):
                x = float("nan")
            hit = [a for a in allowed if abs(x - a) < 1e-9]
            if not hit:
                raise SpecError(f"{name}은(는) {', '.join(str(a) for a in allowed)} 중 하나여야 합니다.")
            out[name] = hit[0]
    return out


def spec_hash(spec: dict) -> str:
    canon = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def describe_ko(spec: dict) -> str:
    t = spec.get("template")
    tf = spec.get("timeframe")
    where = f"{spec.get('strategy')} {tf}" if tf else f"{spec.get('strategy')} (모든 시간봉)"
    if t == "stop_atr":
        what = f"처음 손절폭 {BASE_K:g} ATR → {spec['k']:g} ATR"
    elif t == "lock_start":
        what = f"첫 익절 잠금 {BASE_LADDER.first_lock:.0%} → {spec['first_lock']:.0%}"
    elif t == "skip_tag":
        what = f"'{spec['tag']}' 신호 건너뛰기"
    elif t == "timeframe_only":
        what = "시간봉별 성적 보기 (설명용)"
    else:
        what = str(t)
    return f"{where}: {what}"


# ---------------------------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------------------------
def week_of(ts_ns: np.ndarray) -> np.ndarray:
    """Monday-start UTC week number (1970-01-01 was a Thursday)."""
    days = np.asarray(ts_ns, np.int64) // 86_400_000_000_000
    return (days + 3) // 7


def block_bootstrap(week_b: np.ndarray, roe_b: np.ndarray, week_v: np.ndarray, roe_v: np.ndarray,
                    n_boot: int = N_BOOT, seed: int = 0) -> dict:
    """Difference of mean ROE per trade (variant - baseline) and the one-sided p that it is
    <= 0, resampling whole weeks (both arms together) with replacement."""
    roe_b, roe_v = np.asarray(roe_b, float), np.asarray(roe_v, float)
    if not len(roe_b) or not len(roe_v):
        return {"diff": None, "p": None, "weeks": 0}
    diff = float(roe_v.mean() - roe_b.mean())
    weeks = np.union1d(week_b, week_v)
    W = len(weeks)
    ib, iv = np.searchsorted(weeks, week_b), np.searchsorted(weeks, week_v)
    sb, cb = np.bincount(ib, roe_b, W), np.bincount(ib, None, W)
    sv, cv = np.bincount(iv, roe_v, W), np.bincount(iv, None, W)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, W, size=(n_boot, W))
    with np.errstate(invalid="ignore", divide="ignore"):
        d = sv[pick].sum(1) / cv[pick].sum(1) - sb[pick].sum(1) / cb[pick].sum(1)
    not_better = int((~(d > 0)).sum())                   # NaN (an empty arm) counts against
    return {"diff": diff, "p": (1 + not_better) / (n_boot + 1), "weeks": int(W)}


def margin_frac(lev: np.ndarray) -> np.ndarray:
    """Share of equity put up as margin at each leverage (the paper v3 tiers of rules_bt.SETTINGS:
    50x/40x 40%, 30x 30%, 20x 20%)."""
    P = profiles_module()
    by_lev = {int(x): float(t.margin_frac) for t in P.RB.SETTINGS.tiers for x in t.leverages}
    lev = np.asarray(lev, float)
    out = np.full(len(lev), np.nan)
    for x, f in by_lev.items():
        out[np.isclose(lev, x)] = f
    return out


def _arm(roe: np.ndarray, reason: np.ndarray, held: np.ndarray, lev: Optional[np.ndarray] = None) -> dict:
    n = int(len(roe))
    if not n:
        return {"trades": 0, "mean_roe": None, "win_rate": None, "stop_share": None, "lock_share": None,
                "liq_share": None, "median_hold_bars": None, "mean_lev": None, "mean_ret_notional": None,
                "mean_pnl_equity": None}
    out = {"trades": n, "mean_roe": float(np.mean(roe)), "win_rate": float(np.mean(roe > 0)),
           "stop_share": float(np.mean(reason == 0)), "lock_share": float(np.mean(reason == 1)),
           "liq_share": float(np.mean(reason == 2)), "median_hold_bars": float(np.median(held))}
    if lev is not None and len(lev) == n:
        lev = np.asarray(lev, float)
        mf = margin_frac(lev)
        out["mean_lev"] = float(np.mean(lev))
        out["mean_ret_notional"] = float(np.mean(roe / lev))          # price return per unit of notional
        out["mean_pnl_equity"] = float(np.nanmean(roe * mf)) if np.isfinite(mf).any() else None
    return out


def _seed(spec: dict, period: str) -> int:
    return int(hashlib.sha256((spec_hash(spec) + "|" + period).encode()).hexdigest()[:8], 16)


def _source_range(L, ts: np.ndarray, tf: str, periods: list[tuple]) -> tuple[int, int]:
    """[lo, n_end) like rules_bt.window_bounds over the union of this cache's periods."""
    lo = max(int(np.searchsorted(ts, pd.Timestamp(periods[0][1]).value, side="left")), L.warmup_bars(tf))
    n_end = int(np.searchsorted(ts, pd.Timestamp(periods[-1][2]).value, side="left"))
    return lo, n_end


def _collect(spec: dict, data: LabData, tf: str, variant: Optional[dict]) -> dict:
    """Per period: concatenated baseline (and variant) trades over the coins."""
    L = sweepsig.lib()
    strat = spec["strategy"]
    acc = {pid: {"b": [], "v": [], "coins": [], "skipped": 0, "start": s, "end": e, "source": src}
           for pid, s, e, src in PERIODS}
    for source in ("main", "pre2021"):
        pers = [p for p in PERIODS if p[3] == source]
        for coin in data.coins(source, tf):
            b = data.bars(source, tf, coin)
            if data.signal(source, tf, coin, strat) is None:
                continue
            lo, n_end = _source_range(L, b["ts"], tf, pers)
            if n_end - 1 <= lo:
                continue
            base = data.outcomes(source, tf, coin, strat, lo, n_end)
            starts = np.array([pd.Timestamp(p[1]).value for p in pers[1:]], np.int64)
            lab = np.searchsorted(starts, b["ts"][base["idx"]], side="right")
            d = base["done"]
            var = None
            tagged = None
            if variant is not None:
                if variant["template"] == "skip_tag":
                    tagged = np.zeros(len(base["idx"]), bool)
                    tagged[d] = data.tagged(source, tf, coin, base["idx"][d], base["side"][d], variant["tag"])
                else:
                    var = data.outcomes(source, tf, coin, strat, lo, n_end, k_stop=variant.get("k", BASE_K),
                                        first_lock=variant.get("first_lock", BASE_LADDER.first_lock))
            for k, (pid, *_rest) in enumerate(pers):
                a = acc[pid]
                m = d & (lab == k)
                a["coins"].append(coin)
                a["b"].append((b["ts"][base["idx"][m]], base["roe"][m], base["reason"][m], base["held"][m],
                               base["lev"][m]))
                if variant is None:
                    continue
                if tagged is not None:
                    mv = m & ~tagged
                    a["skipped"] += int((m & tagged).sum())
                    a["v"].append((b["ts"][base["idx"][mv]], base["roe"][mv], base["reason"][mv], base["held"][mv],
                                   base["lev"][mv]))
                else:
                    labv = np.searchsorted(starts, b["ts"][var["idx"]], side="right")
                    mv = var["done"] & (labv == k)
                    a["v"].append((b["ts"][var["idx"][mv]], var["roe"][mv], var["reason"][mv], var["held"][mv],
                                   var["lev"][mv]))
    return acc


def _cat(parts: list) -> tuple:
    """(ts, roe, reason, held, lev) of all coins."""
    if not parts:
        return (np.zeros(0, np.int64), np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0))
    return tuple(np.concatenate([p[j] for p in parts]) for j in range(5))


def _period_table(spec: dict, acc: dict, with_variant: bool) -> dict:
    out = {}
    for pid, s, e, src in PERIODS:
        a = acc[pid]
        row = {"start": s, "end": e, "cache": src, "available": bool(a["coins"]), "coins": a["coins"]}
        if not a["coins"]:
            row["why"] = "자료 없음" if src == "main" else "2021년 이전 자료가 없습니다"
            out[pid] = row
            continue
        tb, rb, qb, hb, lb = _cat(a["b"])
        row["baseline"] = _arm(rb, qb, hb, lb)
        if with_variant:
            tv, rv, qv, hv, lv = _cat(a["v"])
            row["variant"] = _arm(rv, qv, hv, lv)
            if spec["template"] == "skip_tag":
                row["skipped"] = a["skipped"]
            row.update(block_bootstrap(week_of(tb), rb, week_of(tv), rv, N_BOOT, _seed(spec, pid)))
            if spec["template"] == "stop_atr":
                # the same test on return per unit of notional (ROE / leverage): a wider stop gets a
                # lower leverage tier, which by itself shrinks a loss on margin
                nb = block_bootstrap(week_of(tb), rb / lb, week_of(tv), rv / lv, N_BOOT, _seed(spec, pid))
                row["diff_notional"], row["p_notional"] = nb["diff"], nb["p"]
        out[pid] = row
    return out


# ---------------------------------------------------------------------------------------------
# run + gate
# ---------------------------------------------------------------------------------------------
def _failed(status: str, message: str, spec: Any, t0: float) -> dict:
    r = {"ok": False, "status": status, "error": message, "spec": spec,
         "runtime_s": round(time.time() - t0, 2)}
    r["gate"] = gate(r, 1)
    r["summary_ko"] = f"시험을 하지 못했습니다: {message}"
    return r


def run_test(spec: dict, data: Optional[LabData], *, n_trials: int = 1, strategy: Optional[str] = None) -> dict:
    """Run one test. Never raises for a bad request or missing data: returns ``ok: False`` with a
    Korean ``error``. ``n_trials``: this room's number of tests including this one (Bonferroni of
    the gate; the caller may re-run ``gate(result, n)`` with its own count)."""
    t0 = time.time()
    try:
        sp = normalize_spec(spec, strategy)
    except SpecError as exc:
        return _failed("bad_spec", str(exc), spec, t0)
    if data is None or not data.available():
        return _failed("no_data", "5년 시험 자료(신호 캐시)가 이 서버에 없습니다.", sp, t0)
    tfs = [sp["timeframe"]] if sp.get("timeframe") else list(TFS)
    if not any(data.signal(src, tf, c, sp["strategy"]) is not None
               for tf in tfs for src in ("main",) for c in data.coins(src, tf)):
        return _failed("no_data", f"{sp['strategy']} 신호가 시험 자료에 없습니다.", sp, t0)
    result: dict = {"ok": True, "status": "done", "spec": sp, "spec_hash": spec_hash(sp),
                    "template": sp["template"], "strategy": sp["strategy"], "timeframe": sp.get("timeframe"),
                    "description_ko": describe_ko(sp), "n_boot": N_BOOT,
                    "block": "week (Monday 00:00 UTC)", "p_rule": "(1 + resamples with diff <= 0) / (n_boot + 1)",
                    "outcomes": "paper v3 per signal, research/strategy_profiles/profiles.py _sizer/_scan",
                    "data": {"main_dir": data.main_dir, "pre2021": bool(data.pre2021_dir and data.available("pre2021"))}}
    if sp["template"] in DESCRIPTIVE:
        result["baseline_rule"] = {"k": BASE_K, "first_lock": BASE_LADDER.first_lock}
        result["timeframes"] = {tf: _period_table(sp, _collect(sp, data, tf, None), False) for tf in tfs}
    else:
        tf = sp["timeframe"]
        result["baseline_rule"] = {"k": BASE_K, "first_lock": BASE_LADDER.first_lock}
        result["variant_rule"] = {"k": sp.get("k", BASE_K),
                                  "first_lock": sp.get("first_lock", BASE_LADDER.first_lock),
                                  **({"skip_tag": sp["tag"]} if "tag" in sp else {})}
        result["periods"] = _period_table(sp, _collect(sp, data, tf, sp), True)
    result["n_trials"] = max(1, int(n_trials or 1))
    result["gate"] = gate(result, result["n_trials"])
    result["runtime_s"] = round(time.time() - t0, 2)
    result["summary_ko"] = summary_ko(result)
    return result


def _pct(x: Optional[float], signed: bool = False) -> str:
    if x is None or not math.isfinite(x):
        return "없음"
    return f"{x * 100:+.2f}%" if signed else f"{x * 100:.2f}%"


def _pp(x: Optional[float]) -> str:
    return "없음" if x is None or not math.isfinite(x) else f"{x * 100:+.2f}%p"


def _pv(p: Optional[float]) -> str:
    return "없음" if p is None else f"{p:.4f}"


def gate(result: dict, n_trials_so_far: int) -> dict:
    """The code gate for a copy proposal. Only code decides; nobody can override it."""
    n = max(1, int(n_trials_so_far or 0))
    alpha1 = ALPHA / n
    base = {"pass": False, "n_trials": n, "alpha_period1": alpha1, "checks": {}}
    if not isinstance(result, dict) or not result.get("ok"):
        return {**base, "reasons": ["시험이 끝나지 않아 통과할 수 없습니다."]}
    if result.get("template") in DESCRIPTIVE or "periods" not in result:
        return {**base, "reasons": ["설명용 시험이라 복사 계정 제안에 쓸 수 없습니다."]}
    P = result["periods"]
    p1, p2, p3 = P.get("1", {}), P.get("2", {}), P.get("3", {})

    def num(row, *keys):
        x = row
        for k in keys:
            x = x.get(k) if isinstance(x, dict) else None
        return x if isinstance(x, (int, float)) and math.isfinite(x) else None

    d1, pv1, d2, pv2 = num(p1, "diff"), num(p1, "p"), num(p2, "diff"), num(p2, "p")
    checks, reasons = {}, []
    checks["a"] = d1 is not None and pv1 is not None and d1 > 0 and pv1 < alpha1
    reasons.append(f"① 1기간 개선 {_pp(d1)}, p={_pv(pv1)} — 기준 p < {alpha1:.4g} "
                   f"(0.05 ÷ 이 방의 시험 {n}번, 여러 번 시험한 만큼 기준을 엄격하게): "
                   f"{'통과' if checks['a'] else '미달'}")
    nv2 = int(num(p2, "variant", "trades") or 0)
    checks["b"] = d2 is not None and pv2 is not None and d2 > 0 and pv2 < ALPHA and nv2 >= MIN_TRADES_P2
    reasons.append(f"② 2기간도 같은 방향 {_pp(d2)}, p={_pv(pv2)}, 바꾼 규칙 거래 {nv2:,}건 — 기준 p < 0.05, "
                   f"거래 {MIN_TRADES_P2}건 이상: {'통과' if checks['b'] else '미달'}")
    nb3, nv3 = int(num(p3, "baseline", "trades") or 0), int(num(p3, "variant", "trades") or 0)
    if p3.get("available") and nb3 >= MIN_TRADES_P3:
        d3 = num(p3, "diff")
        checks["c"] = nv3 >= MIN_TRADES_P3 and d3 is not None and d3 > 0
        few = f", 바꾼 규칙 거래 {nv3:,}건뿐(기준 {MIN_TRADES_P3}건)" if nv3 < MIN_TRADES_P3 else ""
        reasons.append(f"③ 3기간(2020~2021년 7월)도 같은 방향 {_pp(d3)}{few}: {'통과' if checks['c'] else '미달'}")
    else:
        checks["c"] = True
        why = "자료 없음" if not p3.get("available") else f"지금 규칙 거래 {MIN_TRADES_P3}건 미만"
        reasons.append(f"③ 3기간(2020~2021년 7월): {why}이라 판단에서 뺌")
    m1, m2 = num(p1, "variant", "mean_roe"), num(p2, "variant", "mean_roe")
    checks["d"] = m1 is not None and m2 is not None and m1 > 0 and m2 > 0
    reasons.append(f"④ 바꾼 규칙 자체가 돈을 버는지: 거래당 평균 1기간 {_pct(m1, True)}, 2기간 {_pct(m2, True)} "
                   f"— 둘 다 0보다 커야 함: {'통과' if checks['d'] else '미달'}")
    nv1 = int(num(p1, "variant", "trades") or 0)
    checks["e"] = nv1 >= MIN_TRADES_P1
    reasons.append(f"⑤ 1기간 거래 수 {nv1:,}건 — 기준 {MIN_TRADES_P1}건 이상: {'통과' if checks['e'] else '미달'}")
    if result.get("template") == "stop_atr":
        n1, n2 = num(p1, "diff_notional"), num(p2, "diff_notional")
        checks["f"] = n1 is not None and n2 is not None and n1 > 0 and n2 > 0
        reasons.append(f"⑥ 레버리지 차이를 뺀 가격 수익률도 나아졌는지(거래당, 명목금액 기준): 1기간 "
                       f"{_pp(n1)}, 2기간 {_pp(n2)} — 둘 다 0보다 커야 함 (넓은 손절은 레버리지가 낮아져 "
                       f"손실만 작아 보일 수 있음): {'통과' if checks['f'] else '미달'}")
    else:
        checks["f"] = True
    ok = all(checks[k] for k in "abcdef")
    return {**base, "pass": bool(ok), "checks": {k: bool(v) for k, v in checks.items()}, "reasons": reasons}


def _period_label(pid: str, row: dict) -> str:
    end = (pd.Timestamp(row["end"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return f"{pid}기간({row['start']}~{end})"


def summary_ko(result: dict) -> str:
    """Plain-Korean summary with code numbers only (for the room's code_result message)."""
    if not result.get("ok"):
        return f"시험을 하지 못했습니다: {result.get('error')}"
    lines = [f"[5년 시험] {result['description_ko']}"]
    if "timeframes" in result:
        for tf, per in result["timeframes"].items():
            parts = []
            for pid, row in per.items():
                if not row.get("available"):
                    continue
                bl = row["baseline"]
                parts.append(f"{pid}기간 {_pct(bl['mean_roe'], True)} ({bl['trades']:,}건)")
            lines.append(f"{tf}: 거래당 평균 " + (", ".join(parts) if parts else "자료 없음"))
        lines.append("판정: 설명용 시험이라 통과 판정이 없습니다.")
        return "\n".join(lines)
    for pid, row in result["periods"].items():
        lab = _period_label(pid, row)
        if not row.get("available"):
            lines.append(f"{lab}: {row.get('why', '자료 없음')}")
            continue
        bl, vr = row["baseline"], row["variant"]
        extra = f", 건너뛴 신호 {row['skipped']:,}건" if "skipped" in row else ""
        lines.append(f"{lab}: 지금 규칙 거래당 평균 {_pct(bl['mean_roe'], True)} ({bl['trades']:,}건) → "
                     f"바꾼 규칙 {_pct(vr['mean_roe'], True)} ({vr['trades']:,}건){extra}, "
                     f"차이 {_pp(row.get('diff'))}, p={_pv(row.get('p'))}")
        if result.get("template") == "stop_atr" and bl.get("mean_lev") and vr.get("mean_lev"):
            lines.append(f"  평균 레버리지 {bl['mean_lev']:.1f}배 → {vr['mean_lev']:.1f}배, 레버리지를 뺀 거래당 가격 "
                         f"수익률 {_pct(bl.get('mean_ret_notional'), True)} → {_pct(vr.get('mean_ret_notional'), True)} "
                         f"(차이 {_pp(row.get('diff_notional'))}, p={_pv(row.get('p_notional'))})")
    rows = [r for r in result["periods"].values() if r.get("available")]
    if result.get("template") == "skip_tag" and rows and not any(r.get("skipped") for r in rows):
        lines.append("이 태그가 붙은 신호가 5년 동안 한 번도 없어 바뀌는 것이 없습니다.")
    g = result.get("gate") or {}
    lines.append("판정: " + ("통과 (복사 계정 제안 가능)" if g.get("pass") else "통과 못함"))
    lines += [f"  {r}" for r in g.get("reasons", [])]
    lines.append("p는 '바꾼 규칙이 나아 보이는 게 우연일 가능성'입니다. 작을수록 우연이 아닐 가능성이 큽니다.")
    return "\n".join(lines)
