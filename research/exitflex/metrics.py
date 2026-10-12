"""exitflex metrics (research/exitflex/PREREG_EXITFLEX.md sections 7-9).

Pure functions on an account's arrays: no file is read, nothing is printed. The wallet is realised at exits (no mark to
market). W_0 = $5,000 at the period start; W_m is the wallet after every trade that exited before the end of UTC month m;
g_m = ln(W_m / W_(m-1)); after a bust the later g_m are 0 (no later trade is taken).

Primary metric for pick p, variant V: M_p(V) = mean over the period's months of [g_m(V) - g_m(E0)] at quarter size, which is
[ln W_end(V) - ln W_end(E0)] / months. Pooled: M(V) = mean over the picks; the monthly pooled difference D_m(V) is the mean over
the picks of [g_m(V) - g_m(E0)].

``summarize`` turns one ``kernel_x.Result`` into a flat dict of numpy arrays (the content of one result file); the other
functions combine summaries of the picks: pooled and per pool (``core`` 23 picks, ``ds`` 15 picks; this study runs the core
pool only, the DeepSeek rule D11 excludes the other).
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np

import data_x as DX
import kernel_x as KX

HOLD_HOURS = (4, 8, 18)
MIN_PICK_SHARE = 0.6
N_BOOT = 2000
BLOCK = 3
REASONS = ("NONE", "SL", "LOCK", "LIQ", "OPEN", "REJECT", "NOFILL", "NOATR", "TP", "RULE", "RAND", "END")


# ------------------------------------------------------------------ months
def month_edges(period: str) -> np.ndarray:
    """UTC month starts (ms) from the period's start to its end, inclusive: months + 1 values."""
    lo, hi = DX.PERIOD_MS[period]
    d = dt.datetime.fromtimestamp(lo / 1000, dt.timezone.utc)
    out = [lo]
    while out[-1] < hi:
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        d = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
        out.append(int(d.timestamp() * 1000))
    return np.array(out, np.int64)


def n_months(period: str) -> int:
    return len(month_edges(period)) - 1


def monthly_g(exit_ts: np.ndarray, pnl: np.ndarray, w0: float, edges: np.ndarray) -> tuple:
    """(g_m, W_m): monthly log growth and the wallet at each month end, from the trades in exit order."""
    m = len(edges) - 1
    cum = w0 + np.cumsum(pnl)
    k = np.searchsorted(exit_ts, edges[1:], side="left")      # trades that exited before each month end
    W = np.where(k > 0, cum[np.maximum(k - 1, 0)] if len(cum) else w0, w0)
    prev = np.r_[w0, W[:-1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        g = np.log(np.maximum(W, 1e-12) / np.maximum(prev, 1e-12))
    return g, W


# ------------------------------------------------------------------ one account
def summarize(res, edges: np.ndarray) -> dict:
    """The numbers of one account that every later table needs, as flat numpy arrays (one result file)."""
    st = res.status
    ent = np.flatnonzero(st == 1)
    closed = ent[res.reason[ent] != KX.R_OPEN]
    pnl, ex, en = res.pnl[ent], res.exit_ts[ent], res.entry_ts[ent]
    g, W = monthly_g(ex, pnl, res.w0, edges)
    eq = res.w0 + np.cumsum(res.pnl[closed])
    peak = np.maximum.accumulate(np.r_[res.w0, eq])
    dd = float(np.max(1 - np.r_[res.w0, eq] / peak)) if len(eq) else 0.0
    rsn = res.reason[ent]
    at_rule = 0
    if len(ent) > 1:
        prev_rule = (rsn[:-1] == KX.R_RULE) | (rsn[:-1] == KX.R_RAND)
        at_rule = int(((en[1:] == ex[:-1]) & prev_rule).sum())
    sig = res.sig
    return {
        "g": g, "W": W, "w0": np.float64(res.w0), "w_end": np.float64(res.wallet),
        "counts": np.array([len(st), len(ent), len(closed), int((st == 0).sum()), int((st == 2).sum()), int((st == 3).sum()),
                            int((st == 4).sum()), int(res.wallet < 10.0), int(res.both), at_rule,
                            int((res.pnl[closed] > 0).sum())], np.int64),
        "reasons": np.bincount(rsn, minlength=12).astype(np.int64),
        "hold_h": (ex - en) / 3_600_000.0, "max_dd": np.float64(dd),
        "tr_coin": sig["coin"][ent], "tr_side": sig["side"][ent], "tr_fill": en, "tr_exit": ex, "tr_reason": rsn.astype(np.int64),
        "tr_pnl": pnl, "num": res.num, "den": res.den}


COUNT_NAMES = ("offered", "entered", "closed", "skipped", "rejected", "no_fill", "after_bust", "bust", "both_touched",
               "entries_at_rule_minute", "wins")


def count(s: dict, name: str) -> int:
    return int(s["counts"][COUNT_NAMES.index(name)])


def pick_Mp(sv: dict, se: dict) -> float:
    """M_p: mean monthly g difference of V against E0 at the same size (0 for a pick with no offered signal)."""
    return float(np.mean(sv["g"] - se["g"]))


def changed_trades(sv: dict, se: dict) -> int:
    """V's trades with no E0 trade of the same (coin, side, fill minute, exit minute, exit reason)."""
    keys = set(zip(se["tr_coin"].tolist(), se["tr_side"].tolist(), se["tr_fill"].tolist(), se["tr_exit"].tolist(),
                   se["tr_reason"].tolist()))
    return sum(1 for k in zip(sv["tr_coin"].tolist(), sv["tr_side"].tolist(), sv["tr_fill"].tolist(), sv["tr_exit"].tolist(),
                              sv["tr_reason"].tolist()) if k not in keys)


def hold_stats(hold_h: np.ndarray) -> dict:
    if not len(hold_h):
        return {"median": float("nan"), "p90": float("nan"), **{f"share_gt{h}": float("nan") for h in HOLD_HOURS}}
    return {"median": float(np.median(hold_h)), "p90": float(np.percentile(hold_h, 90)),
            **{f"share_gt{h}": float((hold_h > h).mean()) for h in HOLD_HOURS}}


# ------------------------------------------------------------------ the picks together
def pool_of(pick: dict) -> str:
    return "ds" if pick.get("kind") == "ds" else "core"


def pooled_series(sv: dict, se: dict, ids: list) -> np.ndarray:
    """D_m: the mean over the picks of g_m(V) - g_m(E0); ids = pick ids present in both dicts."""
    return np.mean([sv[i]["g"] - se[i]["g"] for i in ids], axis=0)


def pool_summary(sv: dict, se: dict, pools: dict | None = None) -> dict:
    """V against E0 over the picks of ``sv`` / ``se`` ({pick id: summary}), pooled (key 'all') and per pool
    (``pools`` = {pick id: 'core'|'ds'}; default 'core' for all)."""
    ids = sorted(sv)
    pools = pools or {i: "core" for i in ids}
    out = {}
    for name, sel in [("all", ids)] + [(p, [i for i in ids if pools[i] == p]) for p in sorted(set(pools.values()))]:
        if not sel:
            continue
        mp = np.array([pick_Mp(sv[i], se[i]) for i in sel])
        holds = np.concatenate([sv[i]["hold_h"] for i in sel])
        holds0 = np.concatenate([se[i]["hold_h"] for i in sel])
        ch = sum(changed_trades(sv[i], se[i]) for i in sel)
        ent = sum(count(sv[i], "entered") for i in sel)
        out[name] = {
            "n_picks": len(sel), "M": float(mp.mean()), "median_Mp": float(np.median(mp)), "Mp": mp.tolist(), "ids": sel,
            "n_pos": int((mp > 0).sum()), "D": pooled_series(sv, se, sel),
            "entered": ent, "entered_e0": sum(count(se[i], "entered") for i in sel),
            "skipped": sum(count(sv[i], "skipped") for i in sel), "skipped_e0": sum(count(se[i], "skipped") for i in sel),
            "rejected": sum(count(sv[i], "rejected") for i in sel), "closed": sum(count(sv[i], "closed") for i in sel),
            "changed": ch, "changed_share": ch / ent if ent else 0.0,
            "entries_at_rule_minute": sum(count(sv[i], "entries_at_rule_minute") for i in sel),
            "reasons": np.sum([sv[i]["reasons"] for i in sel], axis=0).tolist(),
            "both_touched": sum(count(sv[i], "both_touched") for i in sel),
            "hold": hold_stats(holds), "hold_e0": hold_stats(holds0),
            "win_share": (sum(count(sv[i], "wins") for i in sel) / max(1, sum(count(sv[i], "closed") for i in sel))),
            "busts": sum(count(sv[i], "bust") for i in sel),
            "max_dd_median": float(np.median([float(sv[i]["max_dd"]) for i in sel])),
            "final_multiple_median": float(np.median([float(sv[i]["w_end"]) / float(sv[i]["w0"]) for i in sel]))}
    return out


# ------------------------------------------------------------------ selection (section 8)
def eligibility(M: float, Mp: list, entered: int, entered_e0: int, placebo_pooled: np.ndarray | None, is_f7: bool,
                min_share: float = MIN_PICK_SHARE) -> dict:
    """Section 8: M(V) > 0; M_p(V) > 0 on at least 60% of the picks; except F7, M(V) above the 95th percentile (numpy linear)
    of V's placebo pooled means; trades entered at quarter size >= E0's."""
    need = math.ceil(min_share * len(Mp) - 1e-9)
    c1 = M > 0
    c2 = int(sum(1 for m in Mp if m > 0)) >= need
    p95 = float(np.percentile(placebo_pooled, 95)) if placebo_pooled is not None and len(placebo_pooled) else float("nan")
    c3 = True if is_f7 else bool(placebo_pooled is not None and len(placebo_pooled) and M > p95)
    c4 = entered >= entered_e0
    return {"c1_M_positive": bool(c1), "c2_picks_positive": bool(c2), "c3_beats_placebo_p95": bool(c3), "c4_entries": bool(c4),
            "eligible": bool(c1 and c2 and c3 and c4), "p95": p95, "need_picks": need}


def choose_variants(rows: list, by: str = "M") -> list:
    """Section 8.4 (the default): per pool, at most 2 eligible variants: the highest M_P(V) (``by`` = 'M'; 'median_Mp'
    ranks by the median over the picks of M_p instead), then the highest from a different group. Ties go to fewer
    parameters, then to the canonical order. ``rows``: dicts with id, group, nparams, order, eligible and the ranking key."""
    el = [r for r in rows if r["eligible"]]
    key = lambda r: (-r[by], r["nparams"], r["order"])   # noqa: E731
    el.sort(key=key)
    if not el:
        return []
    first = el[0]
    other = [r for r in el if r["group"] != first["group"]]
    return [first["id"]] + ([other[0]["id"]] if other else [])


def claim_of(variant_id: str) -> str:
    """What a chosen variant may claim (section 8)."""
    if variant_id.startswith("F7."):
        return "beats E0 by holding less; no claim about reading the market"
    return "beats E0 and beats a random exit with its timing profile"


# ------------------------------------------------------------------ confirm (section 9)
def block_means(D: np.ndarray, n_boot: int, seed: int, block: int = BLOCK) -> np.ndarray:
    """Means of ``n_boot`` circular moving-block resamples of the monthly series D (blocks of ``block`` consecutive months,
    wrapping around the end; ceil(T / block) blocks, cut to T)."""
    D = np.asarray(D, float)
    T = len(D)
    rng = np.random.default_rng(seed)
    nb = -(-T // block)
    starts = rng.integers(0, T, size=(n_boot, nb))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % T).reshape(n_boot, nb * block)[:, :T]
    return D[idx].mean(axis=1)


def block_bootstrap_p(D: np.ndarray, seed: int, n_boot: int = N_BOOT, block: int = BLOCK) -> float:
    """One-sided p that the mean of D is <= 0: (1 + resamples with mean <= 0) / (n_boot + 1)."""
    m = block_means(D, n_boot, seed, block)
    return float((1 + int((m <= 0).sum())) / (n_boot + 1))


def iid_bootstrap_p(D: np.ndarray, seed: int, n_boot: int = N_BOOT) -> float:
    D = np.asarray(D, float)
    rng = np.random.default_rng(seed)
    m = D[rng.integers(0, len(D), size=(n_boot, len(D)))].mean(axis=1)
    return float((1 + int((m <= 0).sum())) / (n_boot + 1))


def block_bootstrap_ci(D: np.ndarray, seed: int, n_boot: int = N_BOOT, block: int = BLOCK, level: float = 95.0) -> tuple:
    """A percentile interval for M(V) from the block bootstrap (numpy percentile, linear)."""
    m = block_means(D, n_boot, seed, block)
    a = (100.0 - level) / 2.0
    return float(np.percentile(m, a)), float(np.percentile(m, 100.0 - a))


def holm(ps: dict, alpha: float = 0.05) -> dict:
    """Holm at ``alpha`` over {id: p}: with one test p < alpha; with two the smaller p < alpha / 2 and then the larger
    p < alpha. Returns {id: bool}."""
    order = sorted(ps, key=lambda i: ps[i])
    out = {i: False for i in ps}
    m = len(order)
    for r, i in enumerate(order):
        if ps[i] < alpha / (m - r):
            out[i] = True
        else:
            break
    return out


def confirm_verdict(sig: bool, M: float, placebo_pooled: np.ndarray | None, is_f7: bool, entered: int, entered_e0: int) -> dict:
    """PASS needs all three: Holm-significant; except F7, M(V) above the 95th percentile of the confirm-period placebo pooled
    means; trades entered at quarter size >= E0's."""
    p95 = float(np.percentile(placebo_pooled, 95)) if placebo_pooled is not None and len(placebo_pooled) else float("nan")
    c2 = True if is_f7 else bool(placebo_pooled is not None and len(placebo_pooled) and M > p95)
    c3 = entered >= entered_e0
    return {"holm": bool(sig), "beats_placebo_p95": bool(c2), "entries": bool(c3), "p95": p95,
            "pass": bool(sig and c2 and c3)}


def summarize_light(res, edges: np.ndarray) -> dict:
    """The part of ``summarize`` a placebo account keeps: monthly log growth, final wallet, counts, exit reasons, hold
    statistics (median, 90th percentile, shares held more than 4 / 8 / 18 h) and the maximum drawdown."""
    st = res.status
    ent = np.flatnonzero(st == 1)
    closed = ent[res.reason[ent] != KX.R_OPEN]
    g, _W = monthly_g(res.exit_ts[ent], res.pnl[ent], res.w0, edges)
    eq = res.w0 + np.cumsum(res.pnl[closed])
    peak = np.maximum.accumulate(np.r_[res.w0, eq])
    dd = float(np.max(1 - np.r_[res.w0, eq] / peak)) if len(eq) else 0.0
    hold = (res.exit_ts[ent] - res.entry_ts[ent]) / 3_600_000.0
    hs = hold_stats(hold)
    return {"g": g, "w_end": float(res.wallet), "max_dd": dd,
            "counts": np.array([len(st), len(ent), len(closed), int((st == 0).sum()), int((st == 2).sum()), int((st == 3).sum()),
                                int((st == 4).sum()), int(res.wallet < 10.0), int(res.both), 0,
                                int((res.pnl[closed] > 0).sum())], np.int64),
            "reasons": np.bincount(res.reason[ent], minlength=12).astype(np.int64),
            "hold": np.array([hs["median"], hs["p90"]] + [hs[f"share_gt{h}"] for h in HOLD_HOURS]),
            "num": res.num, "den": res.den}


def stack_light(items: list) -> dict:
    """Stack ``summarize_light`` results of several seeds: arrays get a leading seed axis; the hazard counts are summed."""
    out = {k: np.stack([np.asarray(it[k]) for it in items]) for k in ("g", "w_end", "max_dd", "counts", "reasons", "hold")}
    out["num"] = np.sum([it["num"] for it in items], axis=0)
    out["den"] = np.sum([it["den"] for it in items], axis=0)
    return out
