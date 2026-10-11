"""후보 리그 engine: every league account's signals and paper trades, day chunks then minute steps (CONTRACT.md 1).

The machinery is paperbot.paramshadow's (the custom-value shadow, which replays the rule bot's own way): chart frames
from final 5m klines as the live service builds them (``chart_frame``, live warm-up window), signals submitted after
the 1m step that ends at the bar's close, ``replay_day`` stepping only busy engines. What differs: each account has
its own numbers (combo) AND its own exit (candleague.exits: stop k x ATR14 in the signal, the engine set up for the
take-profit rule, a structure level on the signal for a structure rule); DeepSeek strategies come from the study's
research/fullgrid/ds_defs.py (leverage group "normal", as the study); a coin-flip account takes its candidate's
signal times with a seeded side.
"""

from __future__ import annotations

import hashlib
import math
import warnings
from typing import Callable, Iterable

import numpy as np

from paperbot.paramshadow import _strength_feats, chart_frame
from paperbot.models import Signal

from . import candidates as C
from . import exits as X

MIN = 60_000
FIVE = 300_000
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}


def flip_side(account_id: str, close_ms: int) -> int:
    """The coin-flip account's side for a signal: sha256 of its id and the bar close (reproducible on restarts)."""
    return 1 if hashlib.sha256(f"{account_id}|{close_ms}".encode()).digest()[0] & 1 else -1


class Strategies:
    """Signal functions per (kind, name): core from the hash-checked param_defs, DeepSeek from ds_defs."""

    def __init__(self):
        self._core, self._strength = {}, {}

    def core(self, name: str):
        if name not in self._core:
            from paperbot.paramshadow import param_module
            self._core[name] = param_module(name)
        return self._core[name]

    def strength(self, name: str):
        if name not in self._strength:
            from paperbot.entry_marks import strength_module
            try:
                self._strength[name] = strength_module(name)
            except Exception:  # noqa: BLE001  live sizes such a strategy 'normal'
                self._strength[name] = None
        return self._strength[name]

    def signals(self, acct: dict, df, sym: str, frames_btc) -> tuple:
        from paperbot.entry_marks import _contained
        with _contained(), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            combo = {k: (tuple(v) if isinstance(v, list) else v) for k, v in acct["combo"].items()}   # as the study
            if acct["kind"] == "core":
                lo, sh = self.core(acct["name"]).signals(df, acct["tf"], **combo)
            else:
                ctx = None if sym == "BTCUSDT" else {"BTCUSD": frames_btc}
                lo, sh = C.ds_defs().signals(df, acct["tf"], acct["name"], ctx=ctx, coin=sym[:-1], cache={}, **combo)
        return np.asarray(lo, bool), np.asarray(sh, bool)


def chunk_signals(lib, source, accts: list[dict], symbols: Iterable[str], start: int, end: int, run_start: int,
                  strategies: Strategies | None = None, log: Callable[[str], None] = lambda s: None) -> tuple:
    """Signals of every account whose chart bar closed in (max(start, run_start), end]: ({bar close: [(account id,
    Signal)]}, [notes]). Accounts with the same (kind, name, tf, combo) share one signal computation."""
    from paperbot.sigservice import window_5m
    S = strategies or Strategies()
    by_close: dict[int, list] = {}
    notes: list[str] = []
    for tf in sorted({a["tf"] for a in accts}, key=lambda t: TF_MS[t]):
        span, w = TF_MS[tf], lib.warmup_bars(tf)
        group = [a for a in accts if a["tf"] == tf]
        frames = {}
        for sym in symbols:
            cols = source.load(sym, start - window_5m(lib, tf) * FIVE, end)
            frames[sym] = chart_frame(lib, cols, tf)
        for sym in symbols:
            df = frames[sym]
            if len(df) <= w:
                notes.append(f"{sym} {tf}: 차트 봉 {len(df)}개(필요 {w + 1}개 이상), 이 구간 신호 없음")
                continue
            t_open = (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)
            close = t_open + span
            idx = np.flatnonzero((close > max(start, run_start)) & (close <= end) & (np.arange(len(df)) >= w))
            if not len(idx):
                continue
            atr = lib.fg.atr(df, 14).to_numpy(float)
            h, lo_, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
            cache: dict = {}
            strength: dict = {}
            for a in group:
                if a["role"] == "flip":
                    continue
                key = (a["kind"], a["name"], repr(sorted(a["combo"].items())))
                if key not in cache:
                    try:
                        cache[key] = S.signals(a, df, sym, frames.get("BTCUSDT"))
                    except Exception as exc:  # noqa: BLE001  live (strict=False): a failing rule gives no signal
                        notes.append(f"{a['id']} {sym} {tf}: 신호 계산 실패 ({type(exc).__name__}), 이 구간 신호 없음")
                        cache[key] = (np.zeros(len(df), bool), np.zeros(len(df), bool))
                lo, sh = cache[key]
                side = np.where(lo, 1, np.where(sh, -1, 0))[idx]
                smod = S.strength(a["name"]) if a["kind"] == "core" else None
                if smod is not None and a["name"] not in strength:
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            strength[a["name"]] = {"arrays": smod.strength(df.copy(), tf)}
                    except Exception as exc:  # noqa: BLE001  live: a failed strength sizes 'normal'
                        strength[a["name"]] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
                spec = X.spec(a["exit"])
                flips = [f for f in accts if f["role"] == "flip" and f.get("of") == a["id"]]
                for hpos in np.flatnonzero(side):
                    i = int(idx[hpos])
                    at = float(atr[i])
                    if not (math.isfinite(at) and at > 0):
                        continue                       # live: NO_ATR, never traded
                    for acct, s in [(a, int(side[hpos]))] + [(f, flip_side(f["id"], int(close[i]))) for f in flips]:
                        meta = {"stop_dist": spec["stop_atr"] * at, "account": acct["id"],
                                "ctx": {"strength": _strength_feats(strength.get(a["name"]), smod, i, s)}}
                        if spec["tp_kind"] == X.TP_STRUCT:
                            meta["tp_struct"] = X.structure_level(h, lo_, c, i, int(spec["tp_val"]), s)
                        sig = Signal(ts=int(close[i]) - 1, symbol=sym, timeframe=tf, strategy_id=a["name"], side=s,
                                     stop_price=0.0, tier="best", atr=at, meta=meta)
                        by_close.setdefault(int(close[i]), []).append((acct["id"], sig))
        log(f"signals {tf}: {sum(len(v) for v in by_close.values())} so far")
    return by_close, notes


def make_engines(accts: list[dict], brackets: dict, specs: dict) -> dict:
    """{account id: engine}: each account's exit rule on the paper bot's engine."""
    return {a["id"]: X.make_engine(a["exit"], brackets, specs, book=a["id"], size=a.get("size", 1.0)) for a in accts}

