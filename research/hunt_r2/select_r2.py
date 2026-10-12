"""Hunt round 2 selection (PREREG_HUNT_R2.md section 4, 3.6, 3.7): Stage 0 (anchors), Stage A (coarse plateau with the
fixed-size neighbourhood), the two no-skill nulls replayed through the whole search, the step-down hurdle and the box
check. Select period only (2021-01-01 .. 2024-01-01).

Signals come from the event store (store_r2.py) and run through the unchanged round-1 engine by its public functions
only: ``hunt.run_signals(mk, [(sig, 0)], r, cost, ...)`` on signal dicts {tf, k, j, side} that round 2 builds itself
(never a round-2 spec dict into round 1's spec-based path, 11). ``hunt.series`` / ``fill_index`` give the signal bars,
ATR14, the 장세 label and the fill bar, exactly as ``hunt.system_signals`` uses them.

Pure rules (tested on hand-made tables): ``anchor_slot`` (4.1), ``plateau`` / ``stage_a`` (4.0, 4.2), ``foreign_masks``
(3.6 two names), ``rank_candidates`` (4.2), ``null_rank_scores`` / ``step_down`` (4.3), ``box_check`` / ``box_best``
(4.4). Null constructions (4.3): ``FlipTable`` ((b′): one coin per signal-bar close shared by every coin and system),
``delta_days`` / ``Spans`` / ``shift_sig`` / ``choose_delta`` ((a′): whole-week common shift, per-coin circular wrap,
drops counted, redraw above 10%).

CHOICES (where the text leaves room; each also in ``CHOICES`` of the output):
"""

from __future__ import annotations

import hashlib
import math
import os
import sys
import time
from collections import OrderedDict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402
from research.hunt_r2 import store_r2 as ST  # noqa: E402

R_BASE = H.R_BASE                       # r = 0.5% (W 2)
MIN_POS = 72                            # 4.0 W5-ok (2 x 36 select months)
N_REP = 200                             # 4.3: replicates per null
HURDLE_Q = 95.0                         # 4.3: 95th percentile (numpy linear)
MAX_PICKS = 30                          # 4.4 / 5: three batches of 10
DROP_MAX = 0.10                         # 4.3 (a′): redraw when more than 10% of the replicate's events are dropped
NEAR_WEEKS = 8                          # 4.3 (a′): effective shifts within 8 weeks of 0 or of L_c are listed
WEEK_MS = 7 * H.DAY_MS
GRID_MS = H.TF_MS["15m"]                # every signal-bar close of 15m-4h lies on the 15m grid
FAM_RANK = {f: i for i, f in enumerate(L.FAMILY_ORDER)}
GATE_RANK = {"G1": 0, "NONE": 1}
BOX_MIN_SHARE = 2.0 / 3.0               # 4.4: at least 2/3 of the box points with n >= 72 and no bust

CHOICES = [
    "3.6 default in effect: the event list compared is the system's signal list as the engine receives it (all 30 "
    "coins; coin, signal bar, side; after the gate, the both-sides rule, ATR14 > 0 and a fill bar); in a null "
    "replicate the transformed lists are compared. A point with the default's list is never a peak or a pick and its "
    "run is the default's run (the engine is deterministic); equal lists of two non-default points share one run and "
    "stay separate points.",
    "3.6 / 4.2: the default point and every default in effect are excluded from the peak search (3.6 'can never be a "
    "peak'); a name whose best plateau is its default therefore has a peak whose P_c is not above the default's and "
    "is no candidate, as 4.2 says.",
    "3.6 two names: a system is 'reached' by a name when it is that name's default (run at every slot) or a coarse "
    "point at that name's anchor; a system reached by two names of one family code at the same (timeframe, gate) "
    "can be the peak only of the name nearer in log distance (tie: the earlier name in W 5 order).",
    "4.0: a position that exists keeps its own S when n >= 72 (busted or not); min(S, 0) when n < 72; a position "
    "outside the lattice, failing valid_r2 or removed under 3.7 counts 0. 4.2 'at least half of the existing coarse "
    "neighbours' with no existing neighbour holds (0 >= 0).",
    "4.2 ties of the peak: higher P_c, then P_c2, then S, then the earlier lattice point; nulls drop P_c2 and S2 "
    "everywhere (4.3).",
    "4.3 (b′): heads = the first byte of sha256('hunt-r2-null|b|<i>|<close_ms>') even (keep the side); tails reverses "
    "it, for every coin and system with an event at that signal-bar close.",
    "4.3 (a′): the shift moves each system's signal list (after the gate, ATR14 and fill filters) by Δ inside the "
    "coin's span [s_c, s_c + L_c); s_c / e_c = first / last close in the select period with a 장세 label, ATR14 > 0, "
    "a fill bar and at least 300 bars of the series before it (W 3.1 warm-up); landing bars need a label, ATR14 > 0 and "
    "a fill bar (no bar at that close = dropped). Two events of one coin landing on one bar: one event when they have "
    "the same side, none when opposite (W 3.2's both-sides rule), counted 'collided'.",
    "4.3 (a′) redraw: the 10% share is taken over the events of every system the search can run (each name's 8 "
    "default systems and every coarse point at every slot, both gates; post gate / ATR / fill), so Δ_i is fixed before "
    "any engine run of the replicate.",
    "4.4 box plateau: medians and the 2/3 share over the box points that exist (valid_r2 and not removed under 3.7), "
    "the centre included; box best ties: the earlier box point.",
]


# ------------------------------------------------------------------ pure rules
def anchor_slot(rows: list) -> int:
    """4.1: index into ``rows`` (dicts tf, gate, S, n, bust, median_M) of the anchor: the highest S among n >= 72 and
    no bust; if none qualifies, the highest S overall. Ties: higher median_M, then 15m < 30m < 1h < 4h, then G1."""
    def key(i):
        r = rows[i]
        return (-r["S"], -r["median_M"], H.TF_ORDER.index(r["tf"]), GATE_RANK[r["gate"]])
    qual = [i for i, r in enumerate(rows) if r["n"] >= rows[i].get("min_pos", MIN_POS) and not r["bust"]]
    pool = qual or list(range(len(rows)))
    return sorted(pool, key=key)[0]


def point_values(S: np.ndarray, n: np.ndarray, exists: np.ndarray, min_pos: int = MIN_POS) -> np.ndarray:
    """4.0: the value of each point when it is a one-step position of another: S (n >= min_pos), min(S, 0)
    (n < min_pos), 0 when it does not exist."""
    with np.errstate(invalid="ignore"):
        v = np.where(n >= min_pos, S, np.minimum(S, 0.0))
    return np.where(exists, v, 0.0)


def plateau(S: np.ndarray, n: np.ndarray, nb: np.ndarray, exists: np.ndarray, min_pos: int = MIN_POS) -> np.ndarray:
    """4.2 P_c (4.4 P_f): median of S(x) and the values of x's 2k one-step positions (always 2k + 1 values; NaN for a
    point that does not exist)."""
    v = point_values(S, n, exists, min_pos)
    cols = np.where(nb >= 0, v[np.maximum(nb, 0)], 0.0) if nb.shape[1] else np.zeros((len(S), 0))
    allv = np.concatenate([np.where(exists, S, 0.0)[:, None], cols], axis=1)
    P = np.median(allv, axis=1)
    return np.where(exists, P, np.nan)


def stage_a(lat, S, n, bust, exists, S2=None, default_eff=None, foreign=None, min_pos: int = MIN_POS) -> dict:
    """4.2 on one name's coarse lattice at its anchor. Arrays over the lattice points; ``S2`` None = a null replay (no
    cost x2 conditions, 4.3). Returns P, P2, the eligibility mask, the peak (-1 when none), candidate and P_c values."""
    S, n = np.asarray(S, float), np.asarray(n, float)
    bust, exists = np.asarray(bust, bool), np.asarray(exists, bool)
    npt = len(S)
    nb = lat.nb
    use2 = S2 is not None
    P = plateau(S, n, nb, exists, min_pos)
    S2 = np.asarray(S2, float) if use2 else None
    P2 = plateau(S2, n, nb, exists, min_pos) if use2 else None
    with np.errstate(invalid="ignore"):
        w5 = exists & (n >= min_pos) & (S > 0) & ~bust
        if use2:
            w5 &= S2 > 0
        ex = (nb >= 0) & exists[np.maximum(nb, 0)]
        okp = (n >= min_pos) & ~bust
        n_ex = ex.sum(axis=1)
        n_ok = (ex & okp[np.maximum(nb, 0)]).sum(axis=1)
        half = 2 * n_ok >= n_ex
        elig = w5 & (P > 0) & half
        if use2:
            elig &= P2 > 0
        if lat.k <= 2:
            pos = S > 0
            if use2:
                pos &= S2 > 0
            elig &= ~(ex & ~pos[np.maximum(nb, 0)]).any(axis=1)
    peakable = elig.copy()
    peakable[lat.default] = False
    if default_eff is not None:
        peakable &= ~np.asarray(default_eff, bool)
    if foreign is not None:
        peakable &= ~np.asarray(foreign, bool)
    idx = np.flatnonzero(peakable)
    peak = -1
    if len(idx):
        p2 = P2[idx] if use2 else np.zeros(len(idx))
        order = np.lexsort((idx, -S[idx], -p2, -P[idx]))
        peak = int(idx[order[0]])
    P_def = float(P[lat.default])
    cand = bool(peak >= 0 and P[peak] > P_def)
    return {"P": P, "P2": P2, "eligible": elig, "peak": peak, "candidate": cand, "P_default": P_def,
            "P_peak": float(P[peak]) if peak >= 0 else None,
            "P2_peak": float(P2[peak]) if (peak >= 0 and use2) else None,
            "S_peak": float(S[peak]) if peak >= 0 else None, "n_points": int(npt)}


def rank_candidates(cands: list, use_s2: bool = True) -> list:
    """4.2: candidates (dicts name, family, P, P2) by P_c highest first; ties higher P_c2 (real search only), then
    W 5 family order, then name (ASCII)."""
    return sorted(cands, key=lambda c: (-c["P"], -(c.get("P2") or 0.0) if use_s2 else 0.0, FAM_RANK[c["family"]],
                                        c["name"]))


def null_rank_scores(replicates: list, n_ranks: int) -> np.ndarray:
    """4.3: per replicate (a list of its candidates' P_c), the rank-r score for r = 1..n_ranks (0 when fewer)."""
    out = np.zeros((len(replicates), n_ranks))
    for i, ps in enumerate(replicates):
        s = sorted((float(p) for p in ps), reverse=True)[:n_ranks]
        out[i, :len(s)] = s
    return out


def step_down(real_P: list, null_a: np.ndarray, null_b: np.ndarray, q: float = HURDLE_Q) -> list:
    """4.3: walk the ranked real candidates; rank r is taken only when every higher rank was taken and its P_c is above
    the q-th percentile (numpy linear) of the rank-r scores of both nulls. Returns per rank {taken, label, thr_a,
    thr_b}."""
    out, stopped = [], False
    for r, p in enumerate(real_P, start=1):
        ta = float(np.percentile(null_a[:, r - 1], q)) if null_a.shape[1] >= r else 0.0
        tb = float(np.percentile(null_b[:, r - 1], q)) if null_b.shape[1] >= r else 0.0
        if stopped:
            out.append({"rank": r, "taken": False, "label": "not taken (below a failed rank)", "thr_a": ta, "thr_b": tb})
            continue
        fa, fb = not p > ta, not p > tb
        if fa or fb:
            stopped = True
            lab = "failed both" if (fa and fb) else ("failed (a′)" if fa else "failed (b′)")
            out.append({"rank": r, "taken": False, "label": lab, "thr_a": ta, "thr_b": tb})
        else:
            out.append({"rank": r, "taken": True, "label": "taken", "thr_a": ta, "thr_b": tb})
    return out


def box_check(S, S2, n, bust, exists, min_pos: int = MIN_POS) -> dict:
    """4.4: the box is a plateau when the median S over its points > 0, the median S2 > 0 and at least 2/3 of its
    points have n >= 72 and no bust."""
    ex = np.asarray(exists, bool)
    S, S2, n, bust = (np.asarray(x)[ex] for x in (S, S2, n, bust))
    m = len(S)
    med, med2 = (float(np.median(S)), float(np.median(S2))) if m else (float("nan"), float("nan"))
    good = int(((n >= min_pos) & ~bust.astype(bool)).sum())
    ok = bool(m and med > 0 and med2 > 0 and 3 * good >= 2 * m)
    why = [] if ok else [w for w, bad in (("median S", not med > 0), ("median S2", not med2 > 0),
                                          ("positions", not 3 * good >= 2 * max(m, 1))) if bad]
    return {"plateau": ok, "median_S": med, "median_S2": med2, "points": m, "good": good, "why": why,
            "label": None if ok else "spike between coarse points"}


def box_best(bx, S, n, exists, min_pos: int = MIN_POS) -> int:
    """4.4 read: the box point with the highest P_f (median of S(y) and its 2k one-step box positions; outside 0)."""
    P = plateau(np.asarray(S, float), np.asarray(n, float), bx.nb, np.asarray(exists, bool), min_pos)
    Pm = np.where(np.isfinite(P), P, -np.inf)
    return int(np.argmax(Pm)) if np.isfinite(P).any() else -1


def foreign_masks(names_order: list, anchors: dict) -> dict:
    """3.6 one system, two names: {name: bool mask over its coarse points} of points the name may not take as its
    peak (another name of its family code reaches the same system and is nearer in log distance, or ties and comes
    earlier). ``anchors`` = {name: (tf, gate)}."""
    out = {}
    groups: dict = {}
    for n in names_order:
        if n in L.CODE_OF:
            groups.setdefault(L.CODE_OF[n], []).append(n)
    for code, grp in groups.items():
        for n in grp:
            lat = L.coarse(n)
            mask = np.zeros(len(lat), bool)
            for p, combo in enumerate(lat.combos):
                cs = L.canon(combo)
                for m in grp:
                    if m == n:
                        continue
                    lm = L.coarse(m)
                    reached = cs == L.canon(lm.combos[lm.default]) or (
                        anchors.get(m) == anchors.get(n) and any(cs == L.canon(c) for c in lm.combos))
                    if reached and L.owner_of_shared(code, combo, grp) != n:
                        mask[p] = True
            out[n] = mask
    return out


# ------------------------------------------------------------------ signals from the store
class Ctx:
    """The select market and the per-(timeframe, coin) masks the signals and the nulls read."""

    def __init__(self, mk, root: str, part: str = "coarse"):
        self.mk, self.root, self.part = mk, root, part
        self.syms = list(mk.syms)
        self.start, self.end = int(mk.start), int(mk.end)
        self._ok, self._spans = {}, {}

    def ser(self, tf: str, k: int):
        return H.series(self.syms[k], tf)

    def ok(self, tf: str, k: int) -> np.ndarray:
        """ATR14 > 0 and a fill bar in the period (hunt.system_signals' filters after the gate)."""
        key = (tf, k)
        m = self._ok.get(key)
        if m is None:
            ser = self.ser(tf, k)
            _, f_ok = H.fill_index(self.mk, k, ser)
            m = self._ok[key] = np.isfinite(ser.atr) & (ser.atr > 0) & f_ok
        return m

    def span(self, tf: str, k: int) -> dict:
        """4.3 (a′): the coin's valid span on the timeframe (s_c, e_c, L_c in ms) and the landing mask."""
        key = (tf, k)
        sp = self._spans.get(key)
        if sp is None:
            ser = self.ser(tf, k)
            cm = ser.bars.close_ms
            warm = np.arange(len(cm)) >= ST.E.EW.fullgrid_run().WARMUP_BARS
            land = self.ok(tf, k) & (ser.code != H.UNKNOWN)
            valid = land & (cm >= self.start) & (cm < self.end) & warm
            idx = np.flatnonzero(valid)
            if len(idx):
                s_c, e_c = int(cm[idx[0]]), int(cm[idx[-1]])
                Lc = ((e_c - s_c) // WEEK_MS) * WEEK_MS
            else:
                s_c = e_c = Lc = 0
            sp = self._spans[key] = {"cm": cm, "land": land & (cm >= self.start) & (cm < self.end), "s": s_c,
                                     "e": e_c, "L": int(Lc)}
        return sp


_UNITS: "OrderedDict" = OrderedDict()
UNITS_LRU = 12


def load_units(root: str, part: str, name: str, tf: str, syms: list) -> list:
    """The store units of one (name, timeframe), one per coin in universe order (kept in a small per-process cache)."""
    key = (root, part, name, tf, tuple(syms))
    u = _UNITS.pop(key, None)
    if u is None:
        u = [ST.StoreUnit(ST.unit_dir(root, part, name, tf, s)) for s in syms]
    _UNITS[key] = u
    while len(_UNITS) > UNITS_LRU:
        _UNITS.popitem(last=False)
    return u


def canon_sig(tf: str, k, j, side) -> dict:
    """Signal dict in hunt.system_signals' order: coin, then longs before shorts, then signal bar."""
    k, j, side = (np.asarray(x, np.int64) for x in (k, j, side))
    o = np.lexsort((j, -side, k))
    return {"tf": tf, "k": k[o], "j": j[o], "side": side[o]}


def store_sig(ctx: Ctx, units: list, ci: int, gate: str, tf: str) -> dict:
    """The system's gated signals from the store: the gate (G1 flag), then ATR14 > 0 and a fill bar."""
    K, J, S = [], [], []
    for k, u in enumerate(units):
        j, side, g1 = u.events(ci)
        keep = ctx.ok(tf, k)[j]
        if gate == "G1":
            keep &= g1 == 1
        elif gate != "NONE":
            raise ValueError(f"gate {gate!r}")
        J.append(j[keep].astype(np.int64))
        S.append(side[keep].astype(np.int64))
        K.append(np.full(int(keep.sum()), k, np.int64))
    cat = lambda xs: np.concatenate(xs) if xs else np.zeros(0, np.int64)  # noqa: E731
    return {"tf": tf, "k": cat(K), "j": cat(J), "side": cat(S)}


def sig_hash(sig: dict) -> str:
    h = hashlib.sha256(sig["tf"].encode())
    for x in ("k", "j", "side"):
        h.update(np.ascontiguousarray(np.asarray(sig[x], np.int64)).tobytes())
    return h.hexdigest()


# ------------------------------------------------------------------ nulls (4.3)
def flip_heads(i: int, close_ms: int) -> bool:
    """(b′) replicate i: True = heads = keep the side."""
    return hashlib.sha256(f"hunt-r2-null|b|{i}|{int(close_ms)}".encode()).digest()[0] % 2 == 0


class FlipTable:
    """(b′) replicate i: one fair coin per signal-bar close (the 15m grid of the period), shared by every coin and every
    system with an event at that close."""

    def __init__(self, i: int, start_ms: int, end_ms: int):
        self.i, self.start = int(i), int(start_ms)
        n = (int(end_ms) - self.start) // GRID_MS + 1
        self.reverse = np.fromiter((not flip_heads(i, self.start + q * GRID_MS) for q in range(n)), bool, n)

    def apply(self, ctx: Ctx, sig: dict) -> tuple:
        if not len(sig["k"]):
            return sig, {"events": 0, "flipped": 0}
        side = np.asarray(sig["side"]).copy()
        flipped = 0
        for k in np.unique(sig["k"]):
            sel = sig["k"] == k
            cm = ctx.ser(sig["tf"], int(k)).bars.close_ms[sig["j"][sel]]
            rev = self.reverse[(cm - self.start) // GRID_MS]
            side[sel] = np.where(rev, -side[sel], side[sel])
            flipped += int(rev.sum())
        return canon_sig(sig["tf"], sig["k"], sig["j"], side), {"events": int(len(side)), "flipped": flipped}


def delta_days(i: int, j: int = 0) -> int:
    """(a′) replicate i, draw j: 7 x (9 + (first 8 bytes of sha256('hunt-r2-null|a|<i>|<j>'), little-endian, mod
    140)) days, uniform over whole weeks in 63 .. 1,036 days."""
    u = int.from_bytes(hashlib.sha256(f"hunt-r2-null|a|{i}|{j}".encode()).digest()[:8], "little")
    return 7 * (9 + u % 140)


def landing(sp: dict, cm_events: np.ndarray, delta_ms: int) -> tuple:
    """(a′) landing bar indices (-1 = no bar) and their validity for events closing at ``cm_events``."""
    if sp["L"] <= 0:
        return np.full(len(cm_events), -1, np.int64), np.zeros(len(cm_events), bool)
    t = sp["s"] + np.mod(np.asarray(cm_events, np.int64) - sp["s"] + int(delta_ms), sp["L"])
    cm = sp["cm"]
    idx = np.searchsorted(cm, t)
    exact = (idx < len(cm)) & (cm[np.minimum(idx, len(cm) - 1)] == t)
    idx = np.where(exact, idx, -1)
    valid = exact & sp["land"][np.maximum(idx, 0)]
    return idx, valid


def shift_sig(ctx: Ctx, sig: dict, delta_ms: int) -> tuple:
    """(a′): every event of coin k moves to s_c + ((t - s_c + Δ) mod L_c), side kept, not re-gated; landing bars
    without a label, ATR14 > 0 or a fill bar are dropped; collisions resolved by W 3.2 (same side: one; opposite:
    none). Returns (signals, counts)."""
    tf = sig["tf"]
    K, J, S = [], [], []
    n_drop = n_coll = 0
    for k in np.unique(sig["k"]):
        sel = sig["k"] == k
        sp = ctx.span(tf, int(k))
        idx, valid = landing(sp, sp["cm"][sig["j"][sel]], delta_ms)
        side = sig["side"][sel]
        n_drop += int((~valid).sum())
        idx, side = idx[valid], side[valid]
        if len(idx):
            o = np.lexsort((side, idx))
            idx, side = idx[o], side[o]
            first = np.r_[True, idx[1:] != idx[:-1]]
            grp = np.cumsum(first) - 1
            smin = np.minimum.reduceat(side, np.flatnonzero(first))
            smax = np.maximum.reduceat(side, np.flatnonzero(first))
            cnt = np.bincount(grp)
            keep_g = smin == smax
            n_coll += int(((cnt - 1) * keep_g).sum() + (cnt * ~keep_g).sum())
            idx, side = idx[first][keep_g], smin[keep_g]
        J.append(idx.astype(np.int64))
        S.append(side.astype(np.int64))
        K.append(np.full(len(idx), int(k), np.int64))
    cat = lambda xs: np.concatenate(xs) if xs else np.zeros(0, np.int64)  # noqa: E731
    out = canon_sig(tf, cat(K), cat(J), cat(S))
    return out, {"events": int(len(sig["k"])), "dropped": n_drop, "collided": n_coll}


class ShiftA:
    """(a′) replicate i with its chosen shift (``choose_delta``): ``apply`` = ``shift_sig``."""

    def __init__(self, i: int, days: int):
        self.i, self.days = int(i), int(days)

    def apply(self, ctx: Ctx, sig: dict) -> tuple:
        return shift_sig(ctx, sig, self.days * H.DAY_MS)


def drop_share(ctx: Ctx, hist: dict, delta_ms: int) -> tuple:
    """(a′) share of the events of ``hist`` ({(tf, k): (bar indices, counts)}) whose landing bar is not valid."""
    tot = drop = 0
    for (tf, k), (bars, cnt) in hist.items():
        if not len(bars):
            continue
        sp = ctx.span(tf, k)
        _, valid = landing(sp, sp["cm"][bars], delta_ms)
        tot += int(cnt.sum())
        drop += int(cnt[~valid].sum())
    return (drop / tot if tot else 0.0), drop, tot


def choose_delta(ctx: Ctx, hist: dict, i: int, max_share: float = DROP_MAX, max_draws: int = 1000) -> dict:
    """(a′) replicate i: Δ_i with redraws j = 1, 2, ... while more than ``max_share`` of the events are dropped; the
    coins whose effective shift lies within 8 weeks of 0 or of L_c (per timeframe)."""
    draws = []
    for j in range(max_draws):
        d = delta_days(i, j)
        share, drop, tot = drop_share(ctx, hist, d * H.DAY_MS)
        draws.append({"j": j, "days": d, "share_dropped": share, "dropped": drop, "events": tot})
        if share <= max_share:
            break
    else:
        raise RuntimeError(f"(a′) replicate {i}: no shift with at most {max_share:.0%} dropped in {max_draws} draws")
    dms = draws[-1]["days"] * H.DAY_MS
    near = {}
    for tf in H.TF_ORDER:
        lst = []
        for k, s in enumerate(ctx.syms):
            sp = ctx.span(tf, k)
            if sp["L"] <= 0:
                continue
            eff = dms % sp["L"]
            if eff < NEAR_WEEKS * WEEK_MS or sp["L"] - eff < NEAR_WEEKS * WEEK_MS:
                lst.append(s)
        if lst:
            near[tf] = lst
    return {"i": i, "days": draws[-1]["days"], "j": draws[-1]["j"], "draws": draws, "near_zero": near}


# ------------------------------------------------------------------ engine runs (round 1's public functions)
def run_sig(mk, sig: dict, cost: str = "base", detail: bool = False) -> dict:
    out = H.run_signals(mk, [(sig, 0)], R_BASE, cost, detail=detail, days=False)
    res = {"S": float(out["mean_lnM"]), "median_M": float(out["median_M"]), "n": int(out["n_positions"]),
           "bust": bool(out["bust"]), "max_dd": float(out["max_dd"]), "candidates": int(out["candidates"])}
    if detail:
        nm = out["months"]
        res["lnM"] = list(map(float, out["lnM"]))
        res["pos_month"] = list(out.get("positions_by_month") or [0] * nm)
        res["bust_month"] = mk.months.index(out["bust_month"]) if out["bust"] else -1
        res["win_share"] = out.get("win_share")
    return res


# ------------------------------------------------------------------ one name: Stage 0 + Stage A
def name_unit(ctx: Ctx, name: str, transform=None, real: bool = False, anchor: int | None = None) -> dict:
    """Stage 0 (the name's default systems on every slot) and Stage A (every coarse point at the anchor) for the real
    search (``real``: base + cost x2, the monthly series) or one null replicate (``transform`` = FlipTable /
    a function sig -> (sig, counts); base only). Arrays over the coarse points; NaN where a point does not exist."""
    lat = L.coarse(name)
    t0 = time.time()
    tfs = L.tfs_of(name)
    rows, counts = [], {"events": 0, "dropped": 0, "collided": 0, "flipped": 0}
    removed_all = {}
    nrun = [0]

    def run(sig, cost, detail):
        nrun[0] += 1
        return run_sig(ctx.mk, sig, cost, detail=detail)

    def tr(sig):
        if transform is None:
            return sig
        s2, c = transform.apply(ctx, sig)
        for k_, v in c.items():
            counts[k_] = counts.get(k_, 0) + v
        return s2

    for tf in tfs:
        units = load_units(ctx.root, ctx.part, name, tf, ctx.syms)
        rem = ST.removed_of(units)
        removed_all[tf] = rem
        if lat.default in rem:
            raise RuntimeError(f"{name} {tf}: the default combo raises ({rem[lat.default]}): a bug (3.7)")
        for gate in L.GATES:
            sig = tr(store_sig(ctx, units, lat.default, gate, tf))
            out = run(sig, "base", real)
            out.update({"tf": tf, "gate": gate, "hash": sig_hash(sig)})
            rows.append(out)
    a = anchor_slot(rows) if anchor is None else int(anchor)
    tf, gate = rows[a]["tf"], rows[a]["gate"]
    units = load_units(ctx.root, ctx.part, name, tf, ctx.syms)
    rem = removed_all[tf]
    npt = len(lat)
    exists = np.ones(npt, bool)
    for i in rem:
        exists[i] = False
    S, n, bust, med = (np.full(npt, np.nan) for _ in range(4))
    S2 = np.full(npt, np.nan) if real else None
    lnM = [None] * npt if real else None
    lnM2 = [None] * npt if real else None
    pos = [None] * npt if real else None
    bm = np.full(npt, -1, np.int64) if real else None
    hashes = [None] * npt
    by_hash: dict = {}
    d_hash = rows[a]["hash"]
    for i in range(npt):
        if not exists[i]:
            continue
        if i == lat.default:
            sig = None
            h = d_hash
        else:
            sig = tr(store_sig(ctx, units, i, gate, tf))
            h = sig_hash(sig)
        hashes[i] = h
        if h == d_hash and h not in by_hash:
            by_hash[h] = dict(rows[a])
            if real:
                dsig = tr(store_sig(ctx, units, lat.default, gate, tf))
                by_hash[h]["x2"] = run(dsig, "x2", True)
        if h not in by_hash:
            o = run(sig, "base", real)
            if real:
                o["x2"] = run(sig, "x2", True)
            by_hash[h] = o
        o = by_hash[h]
        S[i], n[i], bust[i], med[i] = o["S"], o["n"], o["bust"], o["median_M"]
        if real:
            S2[i] = o["x2"]["S"]
            lnM[i], lnM2[i], pos[i], bm[i] = o["lnM"], o["x2"]["lnM"], o["pos_month"], o["bust_month"]
    deff = np.asarray([h == d_hash and i != lat.default for i, h in enumerate(hashes)], bool)
    groups: dict = {}
    for i, h in enumerate(hashes):
        if h is not None and h != d_hash:
            groups.setdefault(h, []).append(i)
    dups = [g for g in groups.values() if len(g) > 1]
    for r in rows:
        r.pop("x2", None)
    res = {"name": name, "family": lat.family, "anchor": a, "anchor_tf": tf, "anchor_gate": gate,
           "stage0": rows, "S": S, "n": n, "bust": np.where(np.isnan(bust), False, bust).astype(bool),
           "median_M": med, "exists": exists, "default_eff": deff, "dup_groups": dups,
           "removed": {t: {str(k_): v for k_, v in r_.items()} for t, r_ in removed_all.items() if r_},
           "counts": counts, "runs": nrun[0], "seconds": round(time.time() - t0, 3)}
    if real:
        res.update({"S2": S2, "lnM": lnM, "lnM2": lnM2, "pos_month": pos, "bust_month": bm})
    return res


def search(units: dict, names_order: list, real: bool, min_pos: int = MIN_POS) -> dict:
    """Stage A over every name from its unit (real search or one replicate): the two-name masks, each name's 4.2
    result, and the candidates ranked."""
    anchors = {nm: (u["anchor_tf"], u["anchor_gate"]) for nm, u in units.items()}
    fm = foreign_masks(names_order, anchors)
    per, cands = {}, []
    for nm in names_order:
        u = units.get(nm)
        if u is None:
            continue
        lat = L.coarse(nm)
        st = stage_a(lat, u["S"], u["n"], u["bust"], u["exists"], S2=u.get("S2") if real else None,
                     default_eff=u["default_eff"], foreign=fm.get(nm), min_pos=min_pos)
        per[nm] = st
        if st["candidate"]:
            cands.append({"name": nm, "family": u["family"], "P": st["P_peak"], "P2": st["P2_peak"],
                          "peak": st["peak"]})
    return {"per_name": per, "ranked": rank_candidates(cands, use_s2=real), "foreign": fm}


def box_unit(ctx: Ctx, name: str, tf: str, gate: str, bx, removed: dict) -> dict:
    """4.4: every box point at the anchor, base and cost x2 (box store part)."""
    units = load_units(ctx.root, "box", name, tf, ctx.syms)
    npt = len(bx)
    exists = np.ones(npt, bool)
    for i in removed:
        exists[i] = False
    S, S2, n, bust = (np.full(npt, np.nan) for _ in range(4))
    for i in range(npt):
        if not exists[i]:
            continue
        sig = store_sig(ctx, units, i, gate, tf)
        o, o2 = run_sig(ctx.mk, sig, "base"), run_sig(ctx.mk, sig, "x2")
        S[i], S2[i], n[i], bust[i] = o["S"], o2["S"], o["n"], o["bust"]
    bust = np.where(np.isnan(bust), False, bust).astype(bool)
    chk = box_check(S, S2, n, bust, exists)
    chk["best"] = box_best(bx, S, n, exists)
    chk.update({"S": S, "S2": S2, "n": n, "bust": bust, "exists": exists})
    return chk
