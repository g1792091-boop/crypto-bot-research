"""Hunt round 2 select-only reads (PREREG_HUNT_R2.md section 6), written after ``picks.json`` is hashed and before
``test.json`` exists, to ``research/hunt_r2/out/pretest_reads.json`` (public; DeepSeek rows labels, counts, ranks and
numbers only) and a private file outside the repository (D11, its sha256 in the public file). They read select bars
only (2021-01-01 .. 2024-01-01) and choose nothing. They run whether or not any name is taken.

* **CSCV / PBO** (as W R4 (2)) over the real Stage 0 and Stage A runs only: 12 blocks of 3 months, all 924 half / half
  splits; Stage 0 and Stage A replayed on the in-sample (IS) half (position minimum 36); the replay's rank-1 and top-10
  candidate peaks, their out-of-sample (OOS) relative rank among the selectable systems (omega = average rank /
  (N + 1)), PBO = share of splits with logit(omega) <= 0, the slope of OOS on IS. Stage A ran only at each name's real
  anchor: ``mode="strict"`` gives a name whose IS anchor moved no candidate in that split (counted ``anchor_moved``);
  ``mode="fixed"`` uses the real anchor's lattice whatever the IS anchor (printed beside, labelled).
* **Null summary:** per rank the q50 / q75 / q90 / q95 of the rank-r null score in each null (public at ranks held by
  F1, F2 or F5 candidates or by no real candidate), the null candidates per replicate, the (a′) drop shares, redraws
  and near-zero shifts, and N_eff (the number of independent draws from the null's pooled per-point P_c distribution
  whose expected maximum equals the null's mean rank-1 score).
* **Momentum comparison (c′):** one deterministic replay of Stage 0 + A with every event's side = sign(close[t] -
  close[t - 20]) on the system's timeframe (a zero or undefined return drops the event), base cost; per real
  candidate the (c′) P_c of the same point at the same anchor and the rank-r score of the (c′) search; label "no
  better than plain momentum at the same times" when the real P_c is not above that (c′) P_c. Removes nothing.
* **Selection lift on 2023:** Stage 0 + A chosen on 2021-2022 (position minimum 48) from the same runs' monthly ln M,
  measured on 2023: per name H(peak) - median H over the name's coarse lattice; the median and the share above 0.
* **Leave-one-year-out:** Stage 0 + A chosen on each pair of years (minimum 48); per name how often the full-period
  peak or one of its coarse neighbours returns.
* **Near-miss table:** names that failed exactly one condition (the candidate rule, one null only, the box plateau).
* **Spike ratio:** S / P_c and S by year (2021, 2022, 2023) for each pick and each candidate.
* **Weekend map:** Stage A rerun on the real anchors under the O1 weekend-skip machine; what it would have picked
  (never tested here).
* **Four-timeframe weekend table (owners (j)):** every name at its anchor gate on each of its timeframes, default and
  coarse-peak numbers, 주말 포함 / 주말 제외 (O1) / O1b: S, median monthly multiple, positions, max drawdown, S2;
  aggregates over F1, F2 and F5 by timeframe.
* **Select-only owner board:** the 10 highest-ranked candidates (taken or not), coarse peak beside the anchor
  default: the R1 goal board's headline cell, the size fixed on select, controls (a) and (b) seeds 1-100 at the
  headline cell, R24 at 20 / 30 / 40x (controls seeds 1-50), O1 / O1b, and custom minus default (monthly d, its mean
  and a month 90% CI). Labelled "고르는 기간 성적, 골라서 부풀려진 값, 시험 아님". Multiples only.

IS quantities of a run (from its 36 monthly ln M at base cost and cost x2, positions per month, bust month): S = mean
ln M over the IS months, S2 the same at cost x2, n = positions opened in IS months, bust = the bust month is an IS
month, median_M = median of exp(ln M) over the IS months; the OOS score is the mean ln M over the OOS months.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import pickle
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt import reads_a as RA  # noqa: E402
from research.hunt import reads_o as RO  # noqa: E402
from research.hunt_r2 import confirm_r2 as CF  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402

N_BLOCKS, BLOCK_MONTHS, CSCV_MIN_POS, TOP = 12, 3, 36, 10
WF_MIN_POS = 48                       # 6: the 24-month reads (2023 lift, leave-one-year-out)
MOM_BARS = 20                         # 6 (c′): sign of the 20-bar close-to-close return
BOARD_TOP = 10                        # 6: the 10 highest-ranked candidates (taken or not)
BOARD_CTL_SEEDS, BOARD_LEV_SEEDS = 100, 50
BOARD_LABEL = "고르는 기간 성적, 골라서 부풀려진 값, 시험 아님"
MOMENTUM_LABEL = "no better than plain momentum at the same times"
VARIANTS = ("base", "O1", "O1b")
VARIANT_KO = {"base": "주말 포함", "O1": "주말 제외 (O1)", "O1b": "주말 롱만 제외 (O1b)"}
DS_NOTE = "DeepSeek row: figures in the private file (D11)"
CHOICES = [
    "6 CSCV: Stage A ran only at each name's real anchor (4.1); 'strict' gives a name whose in-sample anchor moved no "
    "candidate in that split (counted anchor_moved); 'fixed' uses the real anchor's lattice whatever the in-sample "
    "anchor; both printed, labelled. The same two modes are printed for the 2023 lift and leave-one-year-out.",
    "6 CSCV quantities: in-sample S and S2 = mean ln M over the in-sample months; n = positions opened in in-sample "
    "months; bust = the bust month is in-sample; median_M over the in-sample months; OOS score = mean ln M over the "
    "OOS months; omega = average rank / (N + 1) among the selectable systems; PBO = share of splits with "
    "logit(omega) <= 0; slope = rank-1 peak's OOS mean ln M regressed on its in-sample mean ln M.",
    "6 null summary: the pooled per-point P_c distribution = every existing coarse point's fixed-size P_c at each "
    "replicate's own anchor, all names, all replicates of that null; the expected maximum of n draws is "
    "sum_i x_(i) ((i / N)^n - ((i - 1) / N)^n); N_eff solved by bisection on log n (None when the mean rank-1 score "
    "lies above every pooled value).",
    "6 (c′): the replay keeps the 3.7 removals and the default-in-effect rule; its own Stage 0 chooses its anchors; "
    "the 'same point at the same anchor' runs Stage A at the real anchor under (c′) when the (c′) anchor differs.",
    "6 2023 lift: per name with an in-sample (2021-2022) peak; H = mean monthly ln M over 2023 at base cost; the "
    "median H over the name's existing coarse points at the anchor.",
    "6 near-miss: 'candidate rule' = a peak exists but P_c(peak) <= P_c(default); 'one null only' = the hurdle label "
    "'failed (a′)' or 'failed (b′)'; 'box plateau' = taken, box failed.",
    "6 owner board: windows are the select period's UTC calendar months (fresh $1,000 each, open positions closed at "
    "the window end as reads_a does); the headline cell is machine B at r = 5% (touch x5); the size fixed on select is "
    "hunt.size_fixed_on_select over the A / B cells; control draws use round 2's seed parts (period 'select'); R24 "
    "runs reads_a.run_lev; custom minus default is on the tested machine (r = 0.5%, $5,000).",
]


# ------------------------------------------------------------------ CSCV machinery (shared by the 24-month reads)
def splits(n_blocks: int = N_BLOCKS, block: int = BLOCK_MONTHS) -> np.ndarray:
    """(924, 36) bool: the IS months of every half / half split, in itertools.combinations order."""
    out = []
    for c in itertools.combinations(range(n_blocks), n_blocks // 2):
        m = np.zeros(n_blocks * block, bool)
        for b in c:
            m[b * block:(b + 1) * block] = True
        out.append(m)
    return np.asarray(out)


def _is_stats(lnM: np.ndarray, pos: np.ndarray, bust_m: np.ndarray, IS: np.ndarray) -> tuple:
    """Per system (rows) and split (columns): IS mean ln M, IS positions, IS bust, OOS mean ln M."""
    w = IS.astype(float)
    k = w.sum(axis=1)
    S = lnM @ w.T / k
    O = lnM @ (1.0 - w).T / np.maximum(IS.shape[1] - k, 1)
    n = pos @ w.T
    bust = np.zeros(S.shape, bool)
    has = bust_m >= 0
    bust[has] = IS[:, bust_m[has]].T
    return S, n, bust, O


def omega(x: float, pool: np.ndarray) -> float:
    """Relative rank of x in the pool (x included in it): average rank / (N + 1)."""
    lt = float((pool < x).sum())
    eq = float((pool == x).sum())
    return (lt + (eq + 1.0) / 2.0) / (len(pool) + 1.0)


def _prep(units: dict, names_order: list, IS: np.ndarray) -> tuple:
    """Per name the IS / OOS statistics of every Stage 0 row and coarse point for the IS masks ``IS`` (splits, 36);
    and the pool of OOS scores of the selectable systems (Stage 0 systems and the non-default coarse points)."""
    prep, pool_O = {}, []
    for nm in names_order:
        u = units[nm]
        lat = L.coarse(nm)
        rows = u["stage0"]
        r_lnM = np.asarray([r["lnM"] for r in rows], float)
        r_pos = np.asarray([r["pos_month"] for r in rows], float)
        r_bm = np.asarray([r["bust_month"] for r in rows], np.int64)
        rS, rn, rb, rO = _is_stats(r_lnM, r_pos, r_bm, IS)
        r_med = np.stack([np.median(np.exp(r_lnM[:, m]), axis=1) for m in IS], axis=1)
        ex = np.asarray(u["exists"], bool)
        npt = len(lat)
        lnM = np.zeros((npt, IS.shape[1]))
        lnM2 = np.zeros((npt, IS.shape[1]))
        pos = np.zeros((npt, IS.shape[1]))
        bm = np.full(npt, -1, np.int64)
        for i in np.flatnonzero(ex):
            lnM[i], lnM2[i], pos[i], bm[i] = u["lnM"][i], u["lnM2"][i], u["pos_month"][i], u["bust_month"][i]
        S, n, bust, O = _is_stats(lnM, pos, bm, IS)
        S2 = lnM2 @ IS.astype(float).T / IS.sum(axis=1)
        prep[nm] = dict(rows=rows, rS=rS, rn=rn, rb=rb, r_med=r_med, S=S, S2=S2, n=n, bust=bust, O=O, ex=ex, lat=lat)
        pool_O.append(rO)                                         # Stage 0: every default system
        sel = ex.copy()
        sel[lat.default] = False                                   # the default point is the Stage 0 system there
        pool_O.append(O[sel])
    return prep, np.concatenate(pool_O, axis=0) if pool_O else np.zeros((0, len(IS)))


def replay(prep: dict, units: dict, names_order: list, s: int, min_pos: int, mode: str) -> dict:
    """Stage 0 + Stage A replayed on split ``s`` of ``prep``: per name the 4.2 result (absent when the IS anchor
    moved in strict mode), the ranked candidates and the names whose IS anchor moved."""
    anchors, per, moved = {}, {}, []
    for nm in names_order:
        p = prep[nm]
        rows = [{"tf": r["tf"], "gate": r["gate"], "S": p["rS"][i, s], "n": p["rn"][i, s],
                 "bust": bool(p["rb"][i, s]), "median_M": p["r_med"][i, s], "min_pos": min_pos}
                for i, r in enumerate(p["rows"])]
        a = SR.anchor_slot(rows)
        if a != units[nm]["anchor"]:
            moved.append(nm)
            if mode == "strict":
                continue
        anchors[nm] = (units[nm]["anchor_tf"], units[nm]["anchor_gate"])
    fm = SR.foreign_masks(names_order, anchors)
    cands = []
    for nm in anchors:
        p = prep[nm]
        st = SR.stage_a(p["lat"], p["S"][:, s], p["n"][:, s], p["bust"][:, s], p["ex"], S2=p["S2"][:, s],
                        default_eff=units[nm]["default_eff"], foreign=fm.get(nm), min_pos=min_pos)
        if st["candidate"]:
            cands.append({"name": nm, "family": p["lat"].family, "P": st["P_peak"], "P2": st["P2_peak"],
                          "peak": st["peak"]})
        per[nm] = st
    return {"per": per, "ranked": SR.rank_candidates(cands), "moved": moved}


def cscv(units: dict, names_order: list, mode: str = "strict", top: int = TOP) -> dict:
    """``units`` = the real search's ``select_r2.name_unit(real=True)`` results by name."""
    IS = splits(N_BLOCKS, BLOCK_MONTHS)
    nsp = len(IS)
    prep, pool = _prep(units, names_order, IS)
    w1, w10, is1, oos1, top1 = [], [], [], [], []
    moved = {nm: 0 for nm in names_order}
    for s in range(nsp):
        rp = replay(prep, units, names_order, s, CSCV_MIN_POS, mode)
        for nm in rp["moved"]:
            moved[nm] += 1
        ranked = rp["ranked"]
        if not ranked:
            continue
        col = pool[:, s]
        oms = [omega(prep[c["name"]]["O"][c["peak"], s], col) for c in ranked[:top]]
        c1 = ranked[0]
        w1.append(oms[0])
        w10.append(float(np.mean(oms)))
        is1.append(float(prep[c1["name"]]["S"][c1["peak"], s]))
        oos1.append(float(prep[c1["name"]]["O"][c1["peak"], s]))
        top1.append(c1["name"])
    w1a = np.asarray(w1)
    with np.errstate(divide="ignore"):
        lam = np.log(w1a / (1.0 - w1a)) if len(w1a) else w1a
    slope = intercept = None
    if len(is1) >= 2 and np.ptp(is1) > 0:
        slope, intercept = (float(x) for x in np.polyfit(np.asarray(is1), np.asarray(oos1), 1))
    return {"mode": mode, "splits": nsp, "splits_with_candidate": len(w1), "systems": int(pool.shape[0]),
            "pbo": float((lam <= 0).mean()) if len(lam) else None,
            "median_omega_rank1": float(np.median(w1a)) if len(w1a) else None,
            "mean_omega_top10": float(np.mean(w10)) if w10 else None,
            "slope_oos_on_is": slope, "intercept": intercept, "anchor_moved": moved,
            "rank1_names": {nm: top1.count(nm) for nm in sorted(set(top1))},
            "per_split": {"omega_rank1": w1, "mean_omega_top10": w10, "is_rank1": is1, "oos_rank1": oos1}}


# ------------------------------------------------------------------ 24-month reads (2023 lift, leave-one-year-out)
def year_masks(n_months: int = 36) -> dict:
    yrs = np.arange(n_months) // 12
    return {"2021-2022": yrs < 2, "2021+2023": yrs != 1, "2022-2023": yrs > 0}


def lift_2023(units: dict, names_order: list, mode: str = "strict") -> dict:
    """6: chosen on 2021-2022, measured on 2023: per name H(peak) - median H over its coarse lattice."""
    IS = year_masks()["2021-2022"][None, :]
    prep, _ = _prep(units, names_order, IS)
    rp = replay(prep, units, names_order, 0, WF_MIN_POS, mode)
    per = {}
    for nm, st in rp["per"].items():
        if st["peak"] < 0:
            continue
        p = prep[nm]
        Hs = p["O"][:, 0]
        per[nm] = {"lift": float(Hs[st["peak"]] - np.median(Hs[p["ex"]])), "candidate": bool(st["candidate"]),
                   "peak": p["lat"].combos[st["peak"]]}
    lifts = np.asarray([v["lift"] for v in per.values()], float)
    return {"mode": mode, "names_with_peak": len(per), "anchor_moved": rp["moved"],
            "median_lift": float(np.median(lifts)) if len(lifts) else None,
            "share_above_0": float((lifts > 0).mean()) if len(lifts) else None, "per_name": per}


def leave_one_year_out(units: dict, names_order: list, full_peaks: dict, mode: str = "strict") -> dict:
    """6: per name how often (0-3) the full-period peak or one of its coarse neighbours returns when Stage 0 + A is
    chosen on each pair of years."""
    masks = year_masks()
    IS = np.asarray([masks[k] for k in masks])
    prep, _ = _prep(units, names_order, IS)
    per = {nm: {"returns": 0, "pairs": {}} for nm, pk in full_peaks.items() if pk is not None and pk >= 0}
    moved = {}
    for s, key in enumerate(masks):
        rp = replay(prep, units, names_order, s, WF_MIN_POS, mode)
        moved[key] = rp["moved"]
        for nm in per:
            st = rp["per"].get(nm)
            pk = full_peaks[nm]
            lat = L.coarse(nm)
            got = None if st is None else st["peak"]
            back = bool(got is not None and got >= 0 and (got == pk or got in set(int(x) for x in lat.nb[pk]
                                                                                   if x >= 0)))
            per[nm]["pairs"][key] = "anchor moved" if st is None else ("no peak" if got < 0 else
                                                                       ("returns" if back else "elsewhere"))
            per[nm]["returns"] += int(back)
    return {"mode": mode, "anchor_moved": moved, "per_name": per,
            "names": len(per), "share_returning_3_of_3": float(np.mean([v["returns"] == 3 for v in per.values()]))
            if per else None}


# ------------------------------------------------------------------ transforms for replays through the engine
class Momentum:
    """(c′): side = sign(close[j] - close[j - 20]) on the system's own series; zero or undefined: dropped."""

    def apply(self, ctx, sig: dict) -> tuple:
        k, j = np.asarray(sig["k"], np.int64), np.asarray(sig["j"], np.int64)
        side = np.zeros(len(k), np.int64)
        ok = np.zeros(len(k), bool)
        for kk in np.unique(k):
            sel = k == kk
            s_, o_ = RO.momentum_from_closes(ctx.ser(sig["tf"], int(kk)).bars.c, j[sel], MOM_BARS)
            side[sel], ok[sel] = s_, o_
        keep = ok & (side != 0)
        out = SR.canon_sig(sig["tf"], k[keep], j[keep], side[keep])
        return out, {"events": int(len(k)), "dropped": int((~keep).sum())}


def close_of(ctx, sig: dict) -> np.ndarray:
    out = np.zeros(len(sig["k"]), np.int64)
    for kk in np.unique(sig["k"]):
        sel = sig["k"] == kk
        out[sel] = ctx.ser(sig["tf"], int(kk)).bars.close_ms[np.asarray(sig["j"])[sel]]
    return out


class WeekendSkip:
    """O1 / O1b machine: first-unit entries whose signal bar closes Sat 00:00 .. Mon 00:00 UTC skipped (O1b: longs
    only); the machine is otherwise unchanged."""

    def __init__(self, variant: str):
        self.variant = variant

    def apply(self, ctx, sig: dict) -> tuple:
        if self.variant == "base":
            return sig, {"events": int(len(sig["k"])), "dropped": 0}
        sk = RO.skip_mask(self.variant, close_of(ctx, sig), sig["side"])
        keep = ~sk
        out = SR.canon_sig(sig["tf"], np.asarray(sig["k"])[keep], np.asarray(sig["j"])[keep],
                           np.asarray(sig["side"])[keep])
        return out, {"events": int(len(sig["k"])), "dropped": int(sk.sum())}


_P: dict = {}            # state inherited by forked workers: ctx, transforms, anchors, rows


def _unit_task(task) -> dict:
    name, which, anchor, real = task
    ctx = _P["ctx"]
    tr = Momentum() if which == "mom" else WeekendSkip(which)
    u = SR.name_unit(ctx, name, transform=tr, real=real, anchor=anchor)
    return u if real else SR.compact(u)


# ------------------------------------------------------------------ null summary (6)
def expected_max(sorted_x: np.ndarray, n: float) -> float:
    N = len(sorted_x)
    i = np.arange(1, N + 1, dtype=float)
    w = (i / N) ** n - ((i - 1) / N) ** n
    return float((sorted_x * w).sum())


def n_eff(pooled, target: float):
    x = np.sort(np.asarray(pooled, float))
    if not len(x) or not np.isfinite(target):
        return None
    if target <= expected_max(x, 1.0):
        return 1.0
    if target >= x[-1]:
        return None
    lo, hi = 0.0, 1.0
    while expected_max(x, math.exp(hi)) < target and hi < 40:
        hi *= 2
    for _ in range(80):
        mid = (lo + hi) / 2
        if expected_max(x, math.exp(mid)) < target:
            lo = mid
        else:
            hi = mid
    return float(math.exp((lo + hi) / 2))


def null_summary(parts_sel: str | None, names_order: list, n_rep: int, public_ranks: set, picks_pub: dict) -> tuple:
    """(public, private) of the null summary from the select step's null part files."""
    pub, priv = {"nulls": {}}, {"nulls": {}}
    R = max(SR.MAX_PICKS, len([r for r in picks_pub.get("names", []) if r.get("candidate")]))
    for null in ("a", "b"):
        reps, pooled, ncand, missing = [], [], [], 0
        for i in range(1, n_rep + 1):
            units = {}
            for nm in names_order:
                p = os.path.join(parts_sel, f"null_{null}", f"{i:03d}", f"{nm}.json") if parts_sel else None
                if not p or not os.path.exists(p):
                    missing += 1
                    continue
                with open(p) as fh:
                    units[nm] = SR.expand(json.load(fh))
            if len(units) < len(names_order):
                continue
            s = SR.search(units, names_order, real=False)
            for st in s["per_name"].values():
                P = np.asarray(st["P"], float)
                pooled.extend(P[np.isfinite(P)].tolist())
            reps.append([c["P"] for c in s["ranked"]])
            ncand.append(len(s["ranked"]))
        if not reps:
            pub["nulls"][null] = priv["nulls"][null] = {"status": "null part files not found: not computed",
                                                        "missing_units": missing}
            continue
        sc = SR.null_rank_scores(reps, R)
        q = {str(r): {f"q{p}": float(np.percentile(sc[:, r - 1], p)) for p in (50, 75, 90, 95)}
             for r in range(1, R + 1)}
        mean1 = float(sc[:, 0].mean())
        ne = n_eff(pooled, mean1)
        full = {"replicates": len(reps), "missing_units": missing, "percentiles_by_rank": q,
                "candidates_per_replicate": {"mean": float(np.mean(ncand)), "median": float(np.median(ncand)),
                                             "min": int(min(ncand)), "max": int(max(ncand)),
                                             "share_with_any": float(np.mean([c > 0 for c in ncand]))},
                "mean_rank1_score": mean1, "pooled_points": len(pooled), "N_eff": ne}
        priv["nulls"][null] = full
        pub["nulls"][null] = dict(full, percentiles_by_rank={r: v for r, v in q.items() if int(r) in public_ranks})
    sh = picks_pub.get("null_shifts") or {}
    if sh:
        shares = [v["draws"][-1]["share_dropped"] for v in sh.values() if v.get("draws")]
        pub["a_prime_shifts"] = priv["a_prime_shifts"] = {
            "replicates": len(sh), "redrawn": int(sum(1 for v in sh.values() if v.get("j"))),
            "share_dropped": {"median": float(np.median(shares)), "max": float(np.max(shares))} if shares else None,
            "near_zero_coins_per_replicate": {"mean": float(np.mean([sum(len(x) for x in (v.get("near_zero") or {})
                                                                         .values()) for v in sh.values()]))}}
    return pub, priv


# ------------------------------------------------------------------ owner board (6)
def _board_run(parts, infos, a, b, cell):
    """One fresh-account calendar-month window of a board cell (reads_a's machines; a window market of the select
    coins, as reads_a's ``run`` builds it)."""
    mk = _P["mk"]
    run = lambda what, x, y, **kw: H.run_engine(what, x, y, mks={"select": mk}, universe=list(mk.syms), **kw)  # noqa
    machine, x = cell
    if machine == "L":
        return RA.run_lev(run, parts, infos, a, b, int(x), RA.GOAL_START, path="day", close_end=True)
    r, ov = RA.cell_overrides(machine, x)
    wparts, _ = RA._window_parts(parts, infos, a, b)
    return run(wparts, a, b, r=r, start_wallet=RA.GOAL_START, overrides=ov, path="day", close_end=True)


def _bits(res) -> int:
    return RA.bits_of(res["end"] / RA.GOAL_START, res["peak"] / RA.GOAL_START, res["bust"])


def _board_task(task):
    """Worker: one board row (peak or default of a candidate), a cell list and an optional control and seed chunk:
    per seed and cell the window bits and closed-end multiples (windows outer, so each window market is built once)."""
    key, cells, ctl, seeds = task
    mk, syms = _P["mk"], list(_P["mk"].syms)
    sig, sid = _P["board_sig"][key], _P["board_id"][key]
    draws = {}
    for s in (seeds or (None,)):
        if ctl is None:
            sg = sig
        else:
            rng = H.rng_of(*CF.seed_parts(sid, ctl, mk.period, H.R_BASE, s))
            sg = H.control_a(mk, sig, rng) if ctl == "a" else H.control_b(sig, rng)
        draws[s] = ([(sg, 1)], [RA.sig_info(H, syms, sg)])
    out = {(s, cell): ([], []) for s in draws for cell in cells}
    for a, b in _P["wins"]:
        for s, (parts, infos) in draws.items():
            for cell in cells:
                res = _board_run(parts, infos, a, b, cell)
                out[(s, cell)][0].append(_bits(res))
                out[(s, cell)][1].append(res["end"] / RA.GOAL_START)
    return key, ctl, out


def _cells_summary(bits, mult) -> dict:
    bits = np.asarray(bits, np.int64)
    m = np.asarray(mult, float)
    n = len(bits)
    if not n:
        return {"n_windows": 0}
    cols = RA.cols_from_bits(bits)
    k5 = int(cols["touch_x5"].sum())
    return {"n_windows": int(n), "shares": {c: float(v.mean()) for c, v in cols.items()
                                            if c in ("end_ge_x2", "end_ge_x5", "touch_x2", "touch_x5", "touch_x10",
                                                     "bust")},
            "touch_x5_ci95": list(RA.clopper_pearson(k5, n)), "median_multiple": float(np.median(m)),
            "mean_ln_multiple": float(np.mean(np.log(np.maximum(m, 1e-12))))}


def owner_board(ctx, real_units: dict, top: list, procs: int) -> dict:
    """6 select-only owner board for ``top`` = [(rank, name, peak index)]: per candidate its peak and its anchor
    default (keys '<name>|peak', '<name>|default')."""
    mk = ctx.mk
    _P.update(mk=mk, wins=RA.calendar_windows(mk.start, mk.end), board_sig={}, board_id={})
    rows = {}
    for rank, nm, pk in top:
        u = real_units[nm]
        lat = L.coarse(nm)
        units = SR.load_units(ctx.root, ctx.part, nm, u["anchor_tf"], ctx.syms)
        for which, ci in (("peak", pk), ("default", lat.default)):
            key = f"{nm}|{which}"
            _P["board_sig"][key] = SR.store_sig(ctx, units, ci, u["anchor_gate"], u["anchor_tf"])
            _P["board_id"][key] = L.system_id(u["family"], nm, u["anchor_tf"], u["anchor_gate"], lat.combos[ci])
            rows[key] = {"rank": rank, "name": nm, "family": u["family"], "which": which,
                         "id": _P["board_id"][key], "numbers": lat.combos[ci]}
    head = ("B", RA.HEADLINE["r"])
    tasks = []
    for key in rows:
        tasks.append((key, RA.board_cells() + RA.lev_cells(), None, None))
        for ctl in ("a", "b"):
            for i in range(0, BOARD_CTL_SEEDS, 25):
                tasks.append((key, [head], ctl, tuple(range(i + 1, min(i + 25, BOARD_CTL_SEEDS) + 1))))
            for i in range(0, BOARD_LEV_SEEDS, 25):
                tasks.append((key, RA.lev_cells(), ctl, tuple(range(i + 1, min(i + 25, BOARD_LEV_SEEDS) + 1))))
    res = H.pmap(_board_task, tasks, procs, label="pretest owner board")
    acc: dict = {}
    for key, ctl, out in res:
        for (s, cell), v in out.items():
            acc.setdefault((key, ctl, cell), {})[s] = v
    board = {}
    for key, meta in rows.items():
        own = {cell: acc[(key, None, cell)][None] for cell in RA.board_cells() + RA.lev_cells()}
        cells = {RA.cell_key(*c): _cells_summary(*own[c]) for c in RA.board_cells()}
        inputs = [{"machine": c[0], "r": float(c[1]), "mean_ln_multiple": cells[RA.cell_key(*c)]["mean_ln_multiple"],
                   "bust_share": cells[RA.cell_key(*c)]["shares"]["bust"]} for c in RA.board_cells()
                  if cells[RA.cell_key(*c)]["n_windows"]]
        fixed = H.size_fixed_on_select(inputs)
        ent = dict(meta)
        ent["headline"] = dict(cells[RA.cell_key(*head)], cell=RA.cell_key(*head))
        for ctl in ("a", "b"):
            mat = acc.get((key, ctl, head)) or {}
            cb = np.asarray([mat[s][0] for s in sorted(mat)], np.int64)
            cc = RA.control_columns(np.asarray(own[head][0], np.int64), cb, "calendar",
                                    H.seed_int(CF.SEED_TAG, "ownerboard", meta["id"], ctl, "boot")) if len(cb) else {}
            ent["headline"][f"control_{ctl}"] = (cc.get("columns") or {}).get("touch_x5")
        ent["size_fixed_on_select"] = None if fixed is None else {
            "cell": RA.cell_key(fixed["machine"], fixed["r"]), **cells[RA.cell_key(fixed["machine"], fixed["r"])]}
        ent["r24"] = {}
        for c in RA.lev_cells():
            e = _cells_summary(*own[c])
            for ctl in ("a", "b"):
                mat = acc.get((key, ctl, c)) or {}
                cb = np.asarray([mat[s][0] for s in sorted(mat)], np.int64)
                e[f"control_{ctl}_touch_x5_pooled"] = float(RA.cols_from_bits(cb)["touch_x5"].mean()) \
                    if len(cb) else None
                e[f"control_{ctl}_seeds"] = int(len(cb))
            ent["r24"][RA.cell_key(*c)] = e
        ent["label"] = BOARD_LABEL
        board[key] = ent
    return board


def _cont(mk, sig) -> dict:
    o = H.run_signals(mk, [(sig, 0)], H.R_BASE, "base", detail=False)
    o2 = H.run_signals(mk, [(sig, 0)], H.R_BASE, "x2", detail=False)
    return {"S": float(o["mean_lnM"]), "median_M": float(o["median_M"]), "positions": int(o["n_positions"]),
            "max_dd": float(o["max_dd"]), "bust": bool(o["bust"]), "S2": float(o2["mean_lnM"]), "lnM": o["lnM"]}


def _four_tf_task(task) -> tuple:
    """Worker: one name, one timeframe: default and peak at the anchor gate, three weekend variants, base and x2."""
    nm, tf, gate, combos = task
    ctx = _P["ctx"]
    units = SR.load_units(ctx.root, ctx.part, nm, tf, ctx.syms)
    rem = SR.ST.removed_of(units)
    out = {}
    for which, ci in combos:
        if ci in rem:
            out[which] = {"removed": rem[ci]}
            continue
        sig = SR.store_sig(ctx, units, ci, gate, tf)
        out[which] = {}
        for v in VARIANTS:
            s2, cnt = WeekendSkip(v).apply(ctx, sig)
            r = _cont(ctx.mk, s2)
            r.pop("lnM")
            r["skipped"] = cnt["dropped"]
            out[which][v] = r
    return nm, tf, out


def four_tf_table(ctx, real_units: dict, peaks: dict, names_order: list, procs: int) -> dict:
    """6 (owners (j)): every name at its anchor gate on each of its timeframes, default and coarse peak, weekend
    variants; plus F1 / F2 / F5 aggregates by timeframe."""
    _P["ctx"] = ctx
    tasks = []
    for nm in names_order:
        u = real_units[nm]
        lat = L.coarse(nm)
        combos = [("at_default", lat.default)] + ([("at_peak", peaks[nm])] if peaks.get(nm, -1) >= 0 else [])
        for tf in L.tfs_of(nm):
            tasks.append((nm, tf, u["anchor_gate"], combos))
    res = H.pmap(_four_tf_task, tasks, procs, label="pretest four-timeframe weekend table")
    table = {}
    for nm, tf, out in res:
        table.setdefault(nm, {"family": real_units[nm]["family"], "gate": real_units[nm]["anchor_gate"],
                              "anchor_tf": real_units[nm]["anchor_tf"], "timeframes": {}})["timeframes"][tf] = out
    agg = {}
    for fam in ("F1", "F2", "F5"):
        for tf in H.TF_ORDER:
            for which in ("at_default", "at_peak"):
                for v in VARIANTS:
                    xs = [t["timeframes"][tf][which][v] for nm, t in table.items() if t["family"] == fam
                          and tf in t["timeframes"] and v in (t["timeframes"][tf].get(which) or {})]
                    if not xs:
                        continue
                    S = np.asarray([x["S"] for x in xs])
                    agg.setdefault(fam, {}).setdefault(tf, {}).setdefault(which, {})[v] = {
                        "names": len(xs), "median_S": float(np.median(S)), "share_S_above_0": float((S > 0).mean()),
                        "median_multiple": float(np.median([x["median_M"] for x in xs])),
                        "median_positions": float(np.median([x["positions"] for x in xs]))}
    return {"rows": table, "aggregates_F1_F2_F5": agg, "variants": VARIANT_KO}


# ------------------------------------------------------------------ the whole pretest step
NUMBER_KEYS = ("peak", "default", "numbers", "combo")


def combo_like(v) -> bool:
    """A combo (numbers of an entry): a dict of numbers or lists of numbers, nothing nested deeper."""
    if not isinstance(v, dict) or not v:
        return False
    for x in v.values():
        xs = x if isinstance(x, (list, tuple)) else [x]
        if not all(isinstance(y, (int, float)) and not isinstance(y, bool) for y in xs):
            return False
    return True


def _ds_redact(obj):
    """A DeepSeek row in public: labels, counts and its numbers (combos) only (D11)."""
    if not isinstance(obj, dict):
        return RO.redact(obj)
    keep = {k: obj[k] for k in NUMBER_KEYS if k in obj and combo_like(obj[k])}
    r = RO.redact({k: v for k, v in obj.items() if k not in keep})
    r.update(keep)
    r["note"] = DS_NOTE
    return r


def pretest_run(ctx, real_units: dict, picks_pub: dict, picks_priv: dict, parts_sel: str | None, procs: int,
                names_order: list | None = None, n_rep: int | None = None) -> tuple:
    """(public, private) pretest_reads documents. ``ctx`` = the select market's ``select_r2.Ctx`` on the event store."""
    t0 = time.time()
    names_order = names_order or [r["name"] for r in picks_pub["names"]]
    n_rep = SR.N_REP if n_rep is None else int(n_rep)
    rows = {r["name"]: r for r in picks_pub["names"]}
    fam = {nm: real_units[nm]["family"] for nm in names_order}
    real = SR.search(real_units, names_order, real=True)
    peaks = {nm: real["per_name"][nm]["peak"] for nm in names_order}
    ranked = real["ranked"]
    rank_of = {c["name"]: r for r, c in enumerate(ranked, start=1)}
    ds_ranks = {r for nm, r in rank_of.items() if fam[nm] == "F3"}
    public_ranks = set(range(1, max(SR.MAX_PICKS, len(ranked)) + 1)) - ds_ranks
    pub, priv = {"choices": CHOICES}, {}

    n_months = len(real_units[names_order[0]]["stage0"][0]["lnM"]) if names_order else 0
    need = N_BLOCKS * BLOCK_MONTHS
    # CSCV (both modes)
    if n_months == need:
        full_cscv = {m: cscv(real_units, names_order, m) for m in ("strict", "fixed")}
        priv["cscv"] = full_cscv
        pub["cscv"] = {m: {k: v for k, v in c.items() if k != "per_split"} for m, c in full_cscv.items()}
    else:
        pub["cscv"] = {"status": f"not computed: the select period has {n_months} months, CSCV needs {need}"}
    # null summary
    pub["null_summary"], priv["null_summary"] = null_summary(parts_sel, names_order, n_rep, public_ranks, picks_pub)
    # 2023 lift, leave-one-year-out (counts and lifts; DeepSeek per-name lifts private)
    for key, fn in (("lift_2023", lambda m: lift_2023(real_units, names_order, m)),
                    ("leave_one_year_out", lambda m: leave_one_year_out(real_units, names_order, peaks, m))):
        if n_months != 36:
            pub[key] = {"status": f"not computed: the select period has {n_months} months, the read needs 36"}
            continue
        full = {m: fn(m) for m in ("strict", "fixed")}
        priv[key] = full
        pub[key] = {m: dict(v, per_name={nm: (x if fam[nm] != "F3" or key == "leave_one_year_out" else
                                              _ds_redact(x)) for nm, x in v["per_name"].items()})
                    for m, v in full.items()}
    # near-miss table
    nm_rows = []
    for nm in names_order:
        r = rows[nm]
        why = None
        if r["peak"] != "no peak" and not r["candidate"]:
            why = "candidate rule (P_c(peak) <= P_c(default))"
        elif r.get("hurdle") in ("failed (a′)", "failed (b′)"):
            why = f"one null only: {r['hurdle']}"
        elif r.get("box") and not r["box"].get("plateau"):
            why = "box plateau (spike between coarse points)"
        if why:
            nm_rows.append({"name": nm, "family": fam[nm], "rank": r.get("rank"), "failed": why,
                            "peak": r["peak"], "default": r["default"]})
    pub["near_miss"] = nm_rows
    # spike ratio and S by year (picks and candidates)
    sp_pub, sp_priv = {}, {}
    for c in ranked:
        nm, pk = c["name"], c["peak"]
        u = real_units[nm]
        lnm = np.asarray(u["lnM"][pk], float)
        by = {str(2021 + y): float(lnm[12 * y:12 * (y + 1)].mean()) for y in range(len(lnm) // 12)}
        S = float(lnm.mean())
        e = {"name": nm, "family": fam[nm], "rank": rank_of[nm], "pick": "pick_no" in rows[nm], "S": S,
             "P_c": c["P"], "spike_ratio": (S / c["P"]) if c["P"] else None, "S_by_year": by}
        sp_priv[nm] = e
        sp_pub[nm] = _ds_redact(e) if fam[nm] == "F3" else e
    pub["spike_ratio"], priv["spike_ratio"] = sp_pub, sp_priv
    # (c′) momentum replay and weekend map (engine runs on the store)
    _P["ctx"] = ctx
    SR._RUN["ctx"] = ctx
    mom = H.pmap(_unit_task, [(nm, "mom", None, False) for nm in names_order], procs, label="pretest (c′) replay")
    mom_units = {u["name"]: SR.expand(u) for u in mom}
    ms = SR.search(mom_units, names_order, real=False)
    redo = [(nm, "mom", real_units[nm]["anchor"], False) for nm in rank_of
            if mom_units[nm]["anchor"] != real_units[nm]["anchor"]]
    same_anchor = {u["name"]: SR.expand(u) for u in H.pmap(_unit_task, redo, procs, label="pretest (c′) at anchors")}
    cp_pub, cp_priv = {}, {}
    m_rank = [c["P"] for c in ms["ranked"]]
    for c in ranked:
        nm = c["name"]
        u = same_anchor.get(nm) or mom_units[nm]
        st = SR.stage_a(L.coarse(nm), u["S"], u["n"], u["bust"], u["exists"], default_eff=u["default_eff"])
        pc = float(st["P"][c["peak"]]) if np.isfinite(st["P"][c["peak"]]) else None
        r_ = rank_of[nm]
        e = {"name": nm, "family": fam[nm], "rank": r_, "real_P_c": c["P"], "momentum_P_c_same_point": pc,
             "momentum_rank_r_score": m_rank[r_ - 1] if r_ <= len(m_rank) else 0.0,
             "label": MOMENTUM_LABEL if (pc is not None and not c["P"] > pc) else None}
        cp_priv[nm] = e
        cp_pub[nm] = ({"name": nm, "family": "F3", "rank": r_, "label": e["label"], "note": DS_NOTE}
                      if fam[nm] == "F3" else e)
    pub["momentum_c_prime"] = {"candidates": cp_pub, "replay_candidates": len(ms["ranked"]),
                               "dropped_events": int(sum(u["counts"].get("dropped", 0) for u in mom_units.values()))}
    priv["momentum_c_prime"] = {"candidates": cp_priv, "rank_scores": m_rank}
    wk = H.pmap(_unit_task, [(nm, "O1", real_units[nm]["anchor"], True) for nm in names_order], procs,
                label="pretest weekend map")
    wk_units = {u["name"]: u for u in wk}
    ws = SR.search(wk_units, names_order, real=True)
    wm_pub, wm_priv = [], []
    for r_, c in enumerate(ws["ranked"], start=1):
        nm = c["name"]
        e = {"rank": r_, "name": nm, "family": fam[nm], "peak": L.coarse(nm).combos[c["peak"]],
             "same_peak_as_selection": bool(peaks.get(nm) == c["peak"]), "P_c": c["P"]}
        wm_priv.append(e)
        wm_pub.append({k: v for k, v in e.items() if k != "P_c"} if fam[nm] == "F3" else e)
    pub["weekend_map"] = {"what": "Stage A on the real anchors under O1 (weekend first-unit entries skipped): what it "
                                  "would have picked; never tested", "candidates": wm_pub,
                          "names_with_peak": int(sum(1 for st in ws["per_name"].values() if st["peak"] >= 0))}
    priv["weekend_map"] = {"candidates": wm_priv}
    # four-timeframe weekend table
    t4 = four_tf_table(ctx, real_units, peaks, names_order, procs)
    priv["four_timeframes"] = t4
    pub["four_timeframes"] = dict(t4, rows={nm: (t if t["family"] != "F3" else
                                                 {"family": "F3", "gate": t["gate"], "anchor_tf": t["anchor_tf"],
                                                  "timeframes": {tf: _ds_redact(x) for tf, x in
                                                                 t["timeframes"].items()}})
                                            for nm, t in t4["rows"].items()})
    # owner board
    top = [(rank_of[c["name"]], c["name"], c["peak"]) for c in ranked[:BOARD_TOP]]
    board = owner_board(ctx, real_units, top, procs) if top else {}
    cmd = {}
    for _rank, nm, pk in top:
        u = real_units[nm]
        d = np.asarray(u["lnM"][pk], float) - np.asarray(u["lnM"][L.coarse(nm).default], float)
        sid = L.system_id(fam[nm], nm, u["anchor_tf"], u["anchor_gate"], L.coarse(nm).combos[pk])
        cmd[nm] = {"mean_d": float(d.mean()), "ci90": CF.month_ci(d, H.seed_int(CF.SEED_TAG, sid, "custom_minus_default",
                                                                                 "select", H.R_BASE, "ci"))}
        for which, ci in (("peak", pk), ("default", L.coarse(nm).default)):
            units = SR.load_units(ctx.root, ctx.part, nm, u["anchor_tf"], ctx.syms)
            sig = SR.store_sig(ctx, units, ci, u["anchor_gate"], u["anchor_tf"])
            wk_ = {}
            for v in VARIANTS:
                s2, cnt = WeekendSkip(v).apply(ctx, sig)
                r = _cont(ctx.mk, s2)
                r.pop("lnM")
                wk_[v] = r
            board[f"{nm}|{which}"]["weekend"] = wk_
    for nm in cmd:
        board[f"{nm}|peak"]["custom_minus_default"] = cmd[nm]
    priv["owner_board"] = board
    pub["owner_board"] = {k: (_ds_redact(v) | {"name": v["name"], "rank": v["rank"], "which": v["which"],
                                               "numbers": v["numbers"]} if v["family"] == "F3" else v)
                          for k, v in board.items()}
    pub["owner_board_label"] = BOARD_LABEL
    pub["seconds"] = round(time.time() - t0, 1)
    return pub, priv


def load_real_units(parts_sel: str | None, names_order: list) -> dict | None:
    """The real search's units from the select step's part files (None when any is missing)."""
    out = {}
    for nm in names_order:
        p = os.path.join(parts_sel, "real", f"{nm}.pkl") if parts_sel else None
        if not p or not os.path.exists(p):
            return None
        with open(p, "rb") as fh:
            out[nm] = pickle.load(fh)
    return out
