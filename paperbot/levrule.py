"""Which leverage group a signal requests under the "quality_v1" rule (owners 2026-10-04, "B로 가자";
docs/paper-v3-rules-change-1.md; config.V3_LEVERAGE_RULE).

- A strategy signal is "best" when the entry-quality tier of its recorded strength is "best": the mean period-1
  quintile of its strength features (``meta["ctx"]["strength"]``, written by sigservice / entry_marks) against the
  5-year entry study's frozen edges (paperbot/quality_edges.json) is >= 4. Every other signal is "normal": tier
  good / base, or no score at all (no_strength, strength_error, no_edges, no_values). A strategy x timeframe without
  edges (e.g. DOGE at 4h, a new-strategy account) is therefore always "normal".
- A coin-flip signal (strategy ``RANDOM_<seed>``) has no strength: it is "best" with probability
  config.V3_P_BEST[timeframe] (the share of strategy signals that are "best" on the 5-year data), one draw per
  signal, seeded by (salt, seed, timeframe, coin, bar close) so a replay draws the same.
- ``meta["lev_group"]`` ("best" / "normal"), when a signal carries it, wins over both (tests and the checkpoint's
  engine check use it; the live signal service never sets it).

``settings.tier_chain(group)`` then gives the candidates (sizing.size_position). The scoring below is the same as
obsshadows.quality_score (the observation shadow of docs/observation-shadows-2.md); it is kept here, in a trading
file (runinfo.TRADING_FILES), so that shadow code changes never touch sizing. tests/test_levrule.py checks both agree.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import zlib
from typing import Any, Optional

import numpy as np

from .config import QUALITY_GROUPS, V3_P_BEST, V3_SYMBOLS, Settings

RANDOM_PREFIX = "RANDOM_"
# salt of the coin-flip group draw (independent of the coin-flip signal's own fire / side draws)
GROUP_SALT = 20261004
QUALITY_EDGES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quality_edges.json")
_EDGES: Optional[dict] = None
TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


def edges() -> dict:
    """{"<strategy>|<tf>": {feature: {"higher_is_stronger": bool, "edges": [4 floats]}}} (loaded once)."""
    global _EDGES
    if _EDGES is None:
        with open(QUALITY_EDGES_PATH) as fh:
            _EDGES = json.load(fh)["cells"]
    return _EDGES


def quintile(value, cuts, higher_is_stronger: bool) -> Optional[int]:
    """1..5 (5 = strongest) against the period-1 edges of the SIGNED feature (x -1 when lower is stronger); a
    value equal to an edge goes up (numpy searchsorted side="right"). None when missing or not finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return 1 + bisect.bisect_right(list(cuts), v if higher_is_stronger else -v)


def quality_tier(score: float) -> str:
    """>= 4 best, 2 < score < 4 good, <= 2 base (obsshadows.quality_tier)."""
    if score >= 4:
        return "best"
    if score > 2:
        return "good"
    return "base"


def quality_score(strength, strategy: str, timeframe: str, cells: Optional[dict] = None) -> dict:
    """{"score", "tier", "reason"}: the mean quintile over the strategy's features that have a value and edges;
    tier None with a reason when there is nothing to score (no_strength / strength_error / no_edges / no_values)."""
    if not isinstance(strength, dict) or not strength:
        return {"score": None, "tier": None, "reason": "no_strength"}
    if "error" in strength:
        return {"score": None, "tier": None, "reason": "strength_error"}
    cell = (edges() if cells is None else cells).get(f"{strategy}|{timeframe}")
    if not cell:
        return {"score": None, "tier": None, "reason": "no_edges"}
    qs: dict = {}
    for f in strength.get("features") or []:
        if not isinstance(f, dict):
            continue
        e = cell.get(f.get("name"))
        if e is None:
            continue
        q = quintile(f.get("value"), e["edges"], bool(e["higher_is_stronger"]))
        if q is not None:
            qs[f["name"]] = q
    if not qs:
        return {"score": None, "tier": None, "reason": "no_values"}
    score = sum(qs.values()) / len(qs)
    return {"score": score, "tier": quality_tier(score), "reason": None}


def quality_group(strength, strategy: str, timeframe: str, cells: Optional[dict] = None) -> dict:
    """quality_score plus "group": "best" only for tier best, else "normal"."""
    q = quality_score(strength, strategy, timeframe, cells)
    return {**q, "group": "best" if q["tier"] == "best" else "normal"}


def _coin_key(symbol: str) -> int:
    return V3_SYMBOLS.index(symbol) if symbol in V3_SYMBOLS else 100 + zlib.crc32(symbol.encode()) % 1_000_000


def coin_flip_seed(strategy: str) -> Optional[int]:
    """The seed k of a coin-flip account's strategy name RANDOM_k, else None."""
    if not isinstance(strategy, str) or not strategy.startswith(RANDOM_PREFIX):
        return None
    try:
        return int(strategy[len(RANDOM_PREFIX):])
    except ValueError:
        return None


def coin_flip_best(seed: int, timeframe: str, symbol: str, bar_close: int, p: Optional[float] = None) -> bool:
    """The coin-flip signal's group draw: True ("best") with probability ``p`` (default V3_P_BEST[timeframe], 0
    for a timeframe without one). Deterministic per (seed, timeframe, coin, bar close in minutes)."""
    p = V3_P_BEST.get(timeframe, 0.0) if p is None else p
    rng = np.random.default_rng([GROUP_SALT, int(seed), TF_MIN.get(timeframe, 0), _coin_key(symbol),
                                 int(bar_close) // 60_000])
    return bool(rng.random() < p)


def _get(sig: Any, name: str, default=None):
    return sig.get(name, default) if isinstance(sig, dict) else getattr(sig, name, default)


def signal_group(sig: Any) -> dict:
    """{"group", "source", ...} of a Signal (or the dict of one, as paper3.db stores pending signals). Never
    raises: anything unexpected is "normal" with reason "error"."""
    try:
        return _signal_group(sig)
    except Exception as exc:  # noqa: BLE001  sizing must go on: no score -> normal
        return {"group": "normal", "source": "error", "score": None, "tier": None, "reason": "error",
                "error": f"{type(exc).__name__}: {exc}"[:200]}


def _signal_group(sig: Any) -> dict:
    meta = _get(sig, "meta") or {}
    forced = meta.get("lev_group") if isinstance(meta, dict) else None
    if forced in QUALITY_GROUPS:
        return {"group": forced, "source": "meta"}
    strategy, tf = _get(sig, "strategy_id", ""), _get(sig, "timeframe", "")
    seed = coin_flip_seed(strategy)
    if seed is not None:
        best = coin_flip_best(seed, tf, _get(sig, "symbol", ""), int(_get(sig, "ts", 0)) + 1)
        return {"group": "best" if best else "normal", "source": "coin_flip", "p_best": V3_P_BEST.get(tf, 0.0)}
    ctx = meta.get("ctx") if isinstance(meta, dict) else None
    strength = ctx.get("strength") if isinstance(ctx, dict) else None
    return {**quality_group(strength, strategy, tf), "source": "quality"}


def requested_tier(settings: Settings, sig: Any) -> str:
    """The tier / group the sizing starts from: the signal's own ``tier`` with "tier_walk" (as before), its group
    (``signal_group``) with "quality_v1"."""
    if settings.leverage_rule == "quality_v1":
        return signal_group(sig)["group"]
    return _get(sig, "tier") or "best"
