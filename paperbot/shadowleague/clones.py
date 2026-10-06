"""Coin-flip clones: what the same trade earns when the entry time is random (the live coin-flip band).

For every virtual trade of a member there are K = 50 clones. A clone has the trade's coin, timeframe and side and the
trade's stop and target DISTANCES (fractions of the entry price, like the study's coin flips, lib_zoneflip.py
flip_sums), and enters at the open of a bar chosen at random within +-5 days of the real entry bar (never the same bar),
with the same slippage, fees, funding and the same fixed stop / target / 48-bar exit (sim.exit_trade).

Honesty rules:
  * the random choice is made by an RNG seeded from the trade's id (and nothing else), so a clone is the same whenever it
    is made, in any order, on any machine; it never looks at a price;
  * a clone's entry bar may lie after the real trade: it waits ('pending') until that bar and the bars of its own
    holding have closed; nothing is simulated on bars that have not closed, and a decided clone never changes;
  * the entry bar is never earlier than the first bar the series ever held (the same for every clone of every trade).
The study's coin flips drew the entry bar from the whole period; here the band is local in time (+-5 days) so it tracks
the weather the live trade was in. This is a different, live-friendly design, labelled as such.
"""

from __future__ import annotations

import hashlib

import numpy as np

from .sim import step_trade

SEED = 20261006                 # the study's seed (lib_zoneflip.SEED); the RNG stream is derived from it and the trade id
DEFAULT_K = 50
DEFAULT_DAYS = 5
DAY_MS = 86_400_000


class EntryBarGone(Exception):
    """The clone's entry bar is older than the oldest bar the league still holds: it must not be simulated on another bar."""


def window_bars(tf_ms: int, days: int = DEFAULT_DAYS) -> int:
    return (days * DAY_MS) // tf_ms


def seed_parts(trade_id: str) -> list[int]:
    h = hashlib.sha256(trade_id.encode("utf-8")).digest()
    return [SEED, int.from_bytes(h[:4], "big"), int.from_bytes(h[4:8], "big")]


def draw_offsets(trade_id: str, nb: int, k: int, min_offset: int) -> list[int]:
    """K bar offsets in [-nb, nb] without 0 and not below ``min_offset`` (the clone must not enter before the series'
    first bar), drawn with replacement from the trade's own RNG stream. Fewer than K only when almost no bar is allowed."""
    rng = np.random.default_rng(seed_parts(trade_id))
    draws = rng.integers(-nb, nb + 1, size=max(64, 40 * k)).tolist()
    ok = [x for x in draws if x != 0 and x >= min_offset]
    return ok[:k]


def make_clones(member_id: str, trade: dict, tf_ms: int, first_bar_ms: int, now_ms: int, k: int = DEFAULT_K,
                days: int = DEFAULT_DAYS) -> list[dict]:
    """The clone rows (status 'pending') of one trade. ``trade`` needs trade_id, coin, tf, side, entry_ms, sl_dist,
    tp_dist."""
    nb = window_bars(tf_ms, days)
    min_off = -((int(trade["entry_ms"]) - int(first_bar_ms)) // tf_ms)
    rows = []
    for i, off in enumerate(draw_offsets(trade["trade_id"], nb, k, min_off)):
        rows.append({"clone_id": f"{trade['trade_id']}#{i:02d}", "member_id": member_id, "trade_id": trade["trade_id"],
                     "k": i, "coin": trade["coin"], "tf": trade["tf"], "side": int(trade["side"]),
                     "sl_dist": float(trade["sl_dist"]), "tp_dist": float(trade["tp_dist"]), "offset_bars": int(off),
                     "target_ms": int(trade["entry_ms"]) + int(off) * tf_ms, "status": "pending",
                     "created_ms": int(now_ms)})
    return rows


def resolve_clone(clone: dict, bars: dict, cost, now_ms: int) -> dict | None:
    """Simulate one clone on the stored bars. Returns the row update, or None when its entry bar has not closed yet.
    The update has status 'closed' once the stop, the target or the 48th bar is in the bars, else 'pending' with the entry
    filled in (so the league knows a position would be open)."""
    t, o, h, l, c = bars["t"], bars["o"], bars["h"], bars["l"], bars["c"]
    if len(t) and int(clone["target_ms"]) < int(t[0]):
        raise EntryBarGone(clone["clone_id"])       # pruned: league._prune keeps the bars a pending clone needs
    e = int(np.searchsorted(t, int(clone["target_ms"]), side="left"))
    if e >= len(t):
        return None
    side = int(clone["side"])
    entry = o[e] * (1.0 + side * cost.slip_side)
    stop = entry * (1.0 - side * float(clone["sl_dist"]))
    tgt = entry * (1.0 + side * float(clone["tp_dist"]))
    decided, tr = step_trade(side, e, entry, stop, tgt, o, h, l, c, cost)
    row = {"status": "pending", "entry_ms": int(t[e]), "entry_px": float(entry)}
    if decided:
        row.update(status="closed", exit_ms=int(t[tr["exit_idx"]]), exit_px=tr["exit_px"], reason=tr["reason"],
                   hold=tr["hold"], gross_raw=tr["gross_raw"], gross=tr["gross"], fee=tr["fee"], funding=tr["funding"],
                   net=tr["net"], mae=tr["mae"], resolved_ms=int(now_ms))
    return row
