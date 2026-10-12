"""Track 2 reads (PREREG_HIWR.md section 14): reported beside the verdict, never a pass. Read-only research code.

``run(ctx)`` is called by ``hiwr.py test`` (after test.json and the verdict exist) or ``hiwr.py reads``; it returns
(public, private). hiwr.py D11-checks the public part (DeepSeek picks: counts, win rates and labels only) and writes the
private part outside the repository. This module is not imported by ``select``; its pin line is appended before
test.json exists (17.3). A read changed after the test is post hoc (DEVIATIONS.md).

Reads, per pick (the registered exit, tier, fill, buffer, weekend rule, costs and SEL f* unless a read changes one):
* R1 with weekends: weekend entries allowed, its own f* from SEL with weekends; trade list and account, SEL and TEST.
* R2 other tiers: the pick's TP price, stop and fill at each other tier whose after-fee ROE range (2.1, same fill)
  contains that price: trade list, f* and margin % (SEL), trade list and account at that f* (TEST).
* R3 loose buffer: stop room with 0.2% only (no ATR term), with the liquidation count; trade list SEL / TEST, the
  TEST account at the registered f*.
* R4 gross reading: TP at ROE / L (2.1 gross), its own f* from SEL; trade list and account, SEL and TEST.
* R5 coins: old six, new 24, the 22 still-listed coins, the 8 proxy coins; label "carried by the old six" when the
  new-24 TEST mean r <= 0.
* R6 extra 2020: trade list and account at f* on 2020.
* R7 maker realism: pierce 0.01% and 0.02% beyond T; the share of maker TP exits whose pierce was under 0.02%; the
  share of TP fills inside the entry minute and the result when those must wait for a later minute; the taker version
  of a maker pick at the same ROE step.
* R8 goal board: month multiples at f* by research/fullgrid/sizing.py's month bootstrap (4 weekly blocks drawn,
  10,000 draws, its seed 20261010; reimplemented here with the same rule): P(month >= x2, x5, x10, x100), median, and
  the period's compounding; SEL and TEST.
* R9 DD bootstrap: the 95th percentile of the week-block bootstrap max DD and the share over the cap at f* and f_path,
  SEL and TEST (TEST draws seeded as 8.4 with period "TEST"); the TEST account at f_path. f_path and f* are
  recomputed on SEL here and checked against the registered f*.
* R10 flat by Saturday: positions still open at Saturday 00:00 UTC close at the last minute before it (a market exit);
  trade list and account, TEST.
* R11 splits and counts: per year, side and coin; hold times; liquidations; skipped candidates by reason.
* R12 live sizes: the TEST account at f* from $100, $300 and $500: the quantity-step rounding error per trade and the
  trades whose rounded notional falls below the minimum.
* R13 streaks: losing-streak lengths of the TEST trade list (entry order) and of the TEST account.
* R14 forward band: 5th..95th percentiles of TEST rolling windows of 50, 100 and 200 trades (win rate, mean r) and of
  30-day account multiples; the block's sha256 is printed (it is hashed before any paper account uses it).
Choices: the variant sizes of R1 / R2 / R4 use f95 draws seeded with "<pick id>|<read>"; R10's per-trade close is the
close of the last minute before Saturday 00:00 UTC.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os

import numpy as np

YEAR_MS = 365 * 86_400_000
SIZING_SEED = 20261010               # research/fullgrid/sizing.py SEED
MONTH_WEEKS, MONTH_DRAWS = 4, 10_000
GOALS = (("x2", 2.0), ("x5", 5.0), ("x10", 10.0), ("x100", 100.0))
LIVE_WALLETS = (100.0, 300.0, 500.0)
BAND_WINDOWS = (50, 100, 200)
BAND_Q = (5, 25, 50, 75, 95)
SAT0 = 5 * 86_400_000                # Saturday 00:00 UTC, from the Monday origin
_FC: dict = {}                       # funding cumsum of the coin one_trade last used


# ------------------------------------------------------------------ one trade, plain Python (R7 wait, R10)
def trade_py(a: dict, e: int, end: int, coin_end: bool, sg: float, S: float, T: float, Q: float, slip: float,
             maker: bool, pierce: float, F: float, tp_from: int) -> tuple:
    """walk.trade_one written plainly, with one option: take-profit checks only from minute ``tp_from`` on (``e``: the
    rule; ``e + 1``: a TP fill inside the entry minute must wait, R7). (event code, gross return)."""
    o, h, lo, c, mo, mh, ml = (a[k] for k in ("o", "h", "l", "c", "mo", "mh", "ml"))
    Tq = T * (1.0 + sg * pierce)
    for j in range(e, end):
        tp_on = j >= tp_from
        if j > e:
            if (mo[j] - Q) * sg <= 0:
                return 8 * j + 0, 0.0
            if (o[j] - S) * sg <= 0:
                return 8 * j + 1, sg * (o[j] * (1.0 - sg * slip) / F - 1.0)
            if tp_on:
                if maker:
                    if (o[j] - Tq) * sg > 0:
                        return 8 * j + 2, sg * (T / F - 1.0)
                elif (o[j] - T) * sg >= 0:
                    return 8 * j + 2, sg * (o[j] * (1.0 - sg * slip) / F - 1.0)
        if (lo[j] <= S) if sg > 0 else (h[j] >= S):
            return 8 * j + 3, sg * (S * (1.0 - sg * slip) / F - 1.0)
        if (ml[j] <= Q) if sg > 0 else (mh[j] >= Q):
            return 8 * j + 4, 0.0
        if tp_on:
            if maker:
                if (h[j] > Tq) if sg > 0 else (lo[j] < Tq):
                    return 8 * j + 5, sg * (T / F - 1.0)
            elif (h[j] >= T) if sg > 0 else (lo[j] <= T):
                return 8 * j + 5, sg * (T * (1.0 - sg * slip) / F - 1.0)
    if coin_end and end > e:
        return 8 * (end - 1) + 6, sg * (c[end - 1] * (1.0 - sg * slip) / F - 1.0)
    return -1, 0.0


def outcome_r(fc: np.ndarray, e: int, code: int, g: float, sg: float, F: float, L: float, maker: bool,
              tk: float, mk: float) -> float | None:
    """The net result of a trade from its event code and gross return (walk._outcome); None when unresolved."""
    if code < 0:
        return None
    ph = code % 8
    x = code // 8
    fund = -sg * (fc[x] - fc[e]) / F
    if ph in (0, 4) or g < -1.0 / L:
        return -1.0 / L - tk + fund
    fee = mk if (maker and ph in (2, 5)) else tk
    return g - tk - fee * (1.0 + sg * g) + fund


# ------------------------------------------------------------------ the pick's candidates on one period
@contextlib.contextmanager
def loose_buffer(W):
    """R3: stop room with 0.2% of the fill only (walk.BUF_ATR 0 while the block runs)."""
    old = W.BUF_ATR
    W.BUF_ATR = 0.0
    try:
        yield
    finally:
        W.BUF_ATR = old


def pick_list(H, mk, fdir: str, pick: dict, cfg: dict, weekend_rule: bool = True, pierce: float = 0.0,
              details: bool = False) -> dict:
    """The pick's trade list on one market (8.1) at exit ``cfg`` from tables over its candidate bars only (a row's walk
    does not depend on other rows, so these equal the full tables' rows), with the account candidates; ``details``
    also keeps per-trade rows for R7 / R10 / R11 / R12."""
    W, R = H.W, H.R
    H.use_frames(fdir)
    combo = H.cell_grid(pick["kind"], pick["name"])[2][pick["row"]]
    tf = pick["tf"]
    per = mk.period
    parts, extra = [], []
    tt = np.array([cfg["t"]] if cfg["fill"] == 0 else [], float)
    tm = np.array([cfg["t"]] if cfg["fill"] == 1 else [], float)
    weekend_dropped = 0
    for c, sym in enumerate(mk.syms):
        if not os.path.exists(H.D.frame_path(fdir, sym, tf)):
            continue
        close, atr = H.frame_atr(sym, tf)
        lo, sh = H.raw_signals(pick["kind"], pick["name"], sym, tf, combo)
        ok = (close >= per[0]) & (close < per[1])
        ok[:R.WARMUP_BARS] = False
        bars = np.flatnonzero(ok & (np.asarray(lo, bool) | np.asarray(sh, bool)))
        if not len(bars):
            continue
        arr = mk.arrays(c)
        T = W.Tables(arr, close, atr, bars, per[1], mk.ended[c], W.first_tier_liqd(H.CX()[sym]["br"]), tt, tm,
                     pierce=pierce)
        rows_all, sides_all = H.cand_rows(T, lo, sh, weekend_rule=False)
        rows, sides = H.cand_rows(T, lo, sh, weekend_rule=weekend_rule)
        weekend_dropped += len(rows_all) - len(rows)
        pt = H.pair_trades(T, rows, sides, cfg, c)
        parts.append(pt)
        if details:
            x = W.trade_list(T, rows, sides, cfg)
            has = x["skip"] != 4
            extra.append({"coin": np.full(int(has.sum()), c), "rows": rows[has], "code": x["code"][has],
                          "ent": T.ent[rows[has]], "p0": T.p0[rows[has]], "atr": T.atr[rows[has]],
                          "F": T.x[1]["F"][rows[has], sides[has]], "side": sides[has], "skip": x["skip"][has]})
    tr = H.cat_trades(parts)
    tr["weekend_dropped"] = weekend_dropped
    if details:
        tr["details"] = {k: (np.concatenate([e[k] for e in extra]) if extra else np.zeros(0)) for k in
                         ("coin", "rows", "code", "ent", "p0", "atr", "F", "side", "skip")}
    tr["cand"] = H.candidates_of(tr["acct"])
    return tr


def acct(H, mk, tr: dict, cfg: dict, f: float, w0: float = 1000.0) -> dict:
    return H.A.account(mk.store, tr["cand"], mk.coins, cfg, f, mk.period, w0=w0)


def acct_short(H, res: dict) -> dict:
    s = H.account_summary(res)
    s.pop("counts", None)
    return s


def variant_cfg(W, cfg: dict, **kw) -> dict:
    out = dict(cfg)
    out.update(kw)
    if "L" in kw:
        out["Li"] = W.LEVS.index(kw["L"])
    return out


# ------------------------------------------------------------------ R8 month bootstrap (sizing.py's rule)
def weekly_growth(H, exit_ms, ret, period) -> np.ndarray:
    W = H.W
    w0, w1 = (period[0] - W.MONDAY0) // W.WEEK, (period[1] - 1 - W.MONDAY0) // W.WEEK
    g = np.ones(int(w1 - w0 + 1))
    if len(ret):
        wk = (np.asarray(exit_ms, np.int64) - W.MONDAY0) // W.WEEK - w0
        np.multiply.at(g, np.clip(wk, 0, len(g) - 1).astype(int), np.maximum(1.0 + np.asarray(ret), 0.0))
    return g


def goal_board(H, res: dict, period) -> dict:
    g = weekly_growth(H, res["exit_ms"], res["feff"] * res["r"], period)
    rng = np.random.default_rng(SIZING_SEED)
    idx = rng.integers(0, len(g), size=(MONTH_DRAWS, MONTH_WEEKS))
    m = np.prod(g[idx], axis=1)
    out = {f"share_month_{k}": float((m >= v).mean()) for k, v in GOALS}
    out.update(median_month=float(np.median(m)), period_multiple=float(res["final"] / res["w0"]))
    return out


# ------------------------------------------------------------------ R10 flat by Saturday
def next_saturday(H, t_ms: int) -> int:
    W = H.W
    k = (int(t_ms) - W.MONDAY0) // W.WEEK
    sat = W.MONDAY0 + k * W.WEEK + SAT0
    return sat if sat > t_ms else sat + W.WEEK


def saturday_store(H, mk):
    """mk's minutes split at every Saturday 00:00 UTC: a segment that ends at a Saturday closes an open position at its
    last minute (coin-end rule); the coin's last segment keeps the coin's own end."""
    A, W = H.A, H.W
    segs, kinds, owner, starts = [], [], [], []
    for c in range(len(mk.syms)):
        a = mk.arrays(c)
        ts = a["ts"]
        if not len(ts):
            continue
        wk = (ts - W.MONDAY0 - SAT0) // W.WEEK          # changes at every Saturday 00:00
        cut = np.flatnonzero(np.diff(wk)) + 1
        bounds = np.r_[0, cut, len(ts)]
        for i in range(len(bounds) - 1):
            s0, s1 = int(bounds[i]), int(bounds[i + 1])
            segs.append({k: a[k][s0:s1] for k in ("ts", "o", "h", "l", "c", "mo", "mh", "ml", "fund")})
            last = i == len(bounds) - 2
            kinds.append(1 if (not last or mk.ended[c]) else 0)
            owner.append(c)
            starts.append(s0)
    return A.Store(segs, kinds), np.asarray(owner, np.int64), np.asarray(starts, np.int64)


def flat_by_saturday(H, mk, tr: dict, cfg: dict, f: float) -> dict:
    A = H.A
    store, owner, starts = saturday_store(H, mk)
    cand = tr["cand"]
    seg = np.empty(len(cand["coin"]), np.int64)
    eloc = np.empty(len(cand["coin"]), np.int64)
    for q in range(len(cand["coin"])):
        c = int(cand["coin"][q])
        ss = np.flatnonzero(owner == c)
        k = ss[np.searchsorted(starts[ss], cand["e"][q], side="right") - 1]
        seg[q], eloc[q] = k, cand["e"][q] - starts[k]
    c2 = A.candidates(cand["coin"], seg, eloc, cand["side"], cand["D"], cand["atr"], cand["fill_ms"])
    res = A.account(store, c2, mk.coins, cfg, f, mk.period)
    # the trade list: each taken trade of the rule's list, its end moved to the next Saturday
    d = tr["details"]
    rs = []
    for i in range(len(d["coin"])):
        if d["skip"][i] != 0:
            continue
        c = int(d["coin"][i])
        a = mk.arrays(c)
        e = int(d["ent"][i])
        sg = 1.0 if d["side"][i] == 0 else -1.0
        F = float(d["F"][i])
        sat = next_saturday(H, int(a["ts"][e]))
        end_sat = int(np.searchsorted(a["ts"], sat))
        end = min(end_sat, len(a["ts"]))
        coin_end = end < len(a["ts"]) or mk.ended[c]
        r = one_trade(H, mk, c, e, end, coin_end, sg, F, d["p0"][i], d["atr"][i], cfg, e)
        if r is not None:
            rs.append(r)
    rs = np.asarray(rs, float)
    return {"trade_list": {"n": int(len(rs)), "win": float((rs > 0).mean()) if len(rs) else None,
                           "mean": float(rs.mean()) if len(rs) else None},
            "account": acct_short(H, res)}


def one_trade(H, mk, c: int, e: int, end: int, coin_end: bool, sg: float, F: float, p0: float, atr: float, cfg: dict,
              tp_from: int) -> float | None:
    """One trade of the pick's exit at the first bracket (as the trade list) by ``trade_py``; r or None (unresolved)."""
    W = H.W
    a = mk.arrays(c)
    key = (id(mk), c)
    if key not in _FC:
        _FC.clear()
        _FC[key] = np.cumsum(a["mo"] * a["fund"])
    fc = _FC[key]
    fam, v = W.STOPS[cfg["k"]]
    S = p0 - sg * v * (atr if fam == "atr" else p0)
    T = F * (1.0 + sg * cfg["t"])
    liqd = W.first_tier_liqd(H.CX()[mk.syms[c]]["br"])[0 if sg > 0 else 1, cfg["Li"]]
    Q = F * (1.0 - sg * liqd)
    code, g = trade_py(a, e, end, coin_end, sg, S, T, Q, W.SLIP, cfg["fill"] == 1, 0.0, F, tp_from)
    return outcome_r(fc, e, code, g, sg, F, float(cfg["L"]), cfg["fill"] == 1, W.TAKER, W.MAKER)


# ------------------------------------------------------------------ R7 maker realism
def maker_realism(H, mk, fdir, pick, cfg, tr: dict) -> dict:
    W = H.W
    out = {}
    for d_ in (0.0001, 0.0002):
        t2 = pick_list(H, mk, fdir, pick, cfg, pierce=d_)
        out[f"pierce_{d_ * 100:g}pct"] = H.list_stats(t2)
    d = tr["details"]
    tp_sh, tp_in, n_tp = 0, 0, 0
    wait_r = []
    ok = d["skip"] == 0
    r_rule = tr["r"][tr["skip"] == 0]
    for i in np.flatnonzero(ok):
        code = int(d["code"][i])
        if code < 0 or (code % 8) not in (2, 5):
            continue
        n_tp += 1
        c = int(d["coin"][i])
        a = mk.arrays(c)
        j = code // 8
        sg = 1.0 if d["side"][i] == 0 else -1.0
        T = float(d["F"][i]) * (1.0 + sg * cfg["t"])
        x = (a["o"][j] if code % 8 == 2 else (a["h"][j] if sg > 0 else a["l"][j]))
        if sg * (x / T - 1.0) < 0.0002:
            tp_sh += 1
        if j == int(d["ent"][i]):
            tp_in += 1
            e = int(d["ent"][i])
            r = one_trade(H, mk, c, e, len(a["ts"]), mk.ended[c], sg, float(d["F"][i]), d["p0"][i], d["atr"][i], cfg,
                          e + 1)
            wait_r.append(r)
    out["maker_tp_exits"] = n_tp
    out["share_pierce_under_0.02pct"] = (tp_sh / n_tp) if n_tp and cfg["fill"] == 1 else None
    out["tp_fills_in_entry_minute"] = tp_in
    out["share_tp_in_entry_minute"] = tp_in / n_tp if n_tp else None
    if tp_in:
        # the rule's list with those trades replaced by their wait-for-a-later-minute results (dropped when open)
        others = []
        idx_in = set()
        for i in np.flatnonzero(ok):
            code = int(d["code"][i])
            if code >= 0 and (code % 8) in (2, 5) and code // 8 == int(d["ent"][i]):
                idx_in.add(int(i))
        k = 0
        rs = []
        for i in np.flatnonzero(ok):
            if int(i) in idx_in:
                if wait_r[k] is not None:
                    rs.append(wait_r[k])
                k += 1
            else:
                others.append(i)
        rr = np.r_[np.asarray(rs, float), r_rule[np.searchsorted(np.flatnonzero(ok), np.asarray(others, int))]
                   if others else np.zeros(0)]
        out["wait_later_minute"] = {"n": int(len(rr)), "win": float((rr > 0).mean()) if len(rr) else None,
                                    "mean": float(rr.mean()) if len(rr) else None}
    if cfg["fill"] == 1:
        ct = variant_cfg(W, cfg, fill=0, fill_name="taker", t=W.tp_move(cfg["L"], cfg["roe"], 0))
        out["taker_same_roe"] = H.list_stats(pick_list(H, mk, fdir, pick, ct))
    return out


# ------------------------------------------------------------------ R11 / R13 / R14
def splits(H, mk, tr: dict) -> dict:
    ok = tr["skip"] == 0
    r, side, coin, ent, ext = tr["r"][ok], tr["side"][ok], tr["coin"][ok], tr["entry_ms"][ok], tr["exit_ms"][ok]
    st = lambda x: {"n": int(len(x)), "win": float((x > 0).mean()) if len(x) else None,  # noqa: E731
                    "mean": float(x.mean()) if len(x) else None}
    yr = (np.asarray(ent) // 1000).astype("datetime64[s]").astype("datetime64[Y]").astype(int) + 1970
    hold = (np.asarray(ext) - np.asarray(ent)) / 60_000.0
    return {"per_year": {str(y): st(r[yr == y]) for y in np.unique(yr)},
            "per_side": {"long": st(r[side == 0]), "short": st(r[side == 1])},
            "per_coin": {mk.syms[c]: st(r[coin == c]) for c in np.unique(coin)},
            "hold_minutes": {f"q{q}": float(np.percentile(hold, q)) for q in (5, 25, 50, 75, 95)} if len(hold) else {},
            "liquidations": int((tr["kind"][ok] == H.W.X_LIQ).sum())}


def streaks(r) -> dict:
    r = np.asarray(r, float)
    out, k = [], 0
    for x in r:
        if x <= 0:
            k += 1
        elif k:
            out.append(k)
            k = 0
    if k:
        out.append(k)
    out = np.asarray(out, int)
    return {"streaks": int(len(out)), "max": int(out.max()) if len(out) else 0,
            "counts": {str(v): int((out == v).sum()) for v in np.unique(out)}}


def band(H, tr: dict, res: dict, period) -> dict:
    ok = tr["skip"] == 0
    order = np.lexsort((tr["side"][ok], tr["coin"][ok], tr["entry_ms"][ok]))
    r = tr["r"][ok][order]
    out = {}
    for w in BAND_WINDOWS:
        if len(r) < w:
            out[f"trades_{w}"] = None
            continue
        cs = np.r_[0.0, np.cumsum(r)]
        cw = np.r_[0, np.cumsum(r > 0)]
        mean = (cs[w:] - cs[:-w]) / w
        win = (cw[w:] - cw[:-w]) / w
        out[f"trades_{w}"] = {"win": {f"q{q}": float(np.percentile(win, q)) for q in BAND_Q},
                              "mean": {f"q{q}": float(np.percentile(mean, q)) for q in BAND_Q}}
    day = 86_400_000
    days = np.arange(period[0], period[1] + 1, day)
    wal = np.full(len(days), res["w0"])
    if res["n"]:
        after = res["W"] + res["N"] * res["r"]
        k = np.searchsorted(res["exit_ms"], days, side="right") - 1
        wal = np.where(k >= 0, after[np.maximum(k, 0)], res["w0"])
    if len(wal) > 30:
        m30 = wal[30:] / wal[:-30]
        out["account_30d_multiple"] = {f"q{q}": float(np.percentile(m30, q)) for q in BAND_Q}
    return out


def labels_only(obj, H):
    """D11: drop every float that is not a win rate or a share (counts, labels and those stay)."""
    if isinstance(obj, dict):
        return {k: (labels_only(v, H) if not isinstance(v, float) or (k in H.DS_FLOAT_KEYS or k.startswith("share"))
                    else None) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [labels_only(v, H) for v in obj if not isinstance(v, float)]
    return obj


# ------------------------------------------------------------------ run
_RUN: dict = {}                      # the reads' markets and folders (inherited by the forked workers)


def pick_file(pdir: str, i: int, pid: str) -> str:
    return os.path.join(pdir, f"{i:04d}_{hashlib.sha256(pid.encode()).hexdigest()[:12]}.json")


def _pick_job(i: int) -> str:
    """One pick's reads, written to its own file in the work folder (a restart skips the picks done)."""
    import traceback
    c = _RUN
    pick = c["picks"][i]
    path = pick_file(c["pdir"], i, pick["id"])
    if os.path.exists(path):
        return ""
    try:
        out = one_pick(c["H"], c["mks"], c["fdir"], c["groups"], pick)
        c["H"].write_json(path, out)
        return f"{pick['id']} done"
    except Exception:  # noqa: BLE001  one pick's failure does not stop the others; it is listed as missing
        return f"ERROR {pick['id']}: " + traceback.format_exc()[-1500:]


def run(ctx: dict) -> tuple:
    """Every pick's reads, in parallel (``args.procs``), one file per pick in the work folder; picks already done are
    skipped. ``args.reads_hours``: no pick is started after that many hours; reads.json then lists the picks not done
    as missing (the verdict is unaffected)."""
    import concurrent.futures as cf
    import multiprocessing as mp
    import time
    H = ctx["H"]
    D = H.D
    args, kits, log = ctx["args"], ctx["kits"], ctx["log"]
    picks = ctx["picks"]
    picks_sha = H.sha256_file(H.rpath(H.PICKS_REL))
    work = H.work_dir(args, f"reads_{picks_sha[:16]}")
    tfs = sorted({p["tf"] for p in picks}, key=H.TFS.index)
    fsel = os.path.join(work, "frames_sel")
    ftest = os.path.join(args.work, f"test_{picks_sha[:16]}", "frames_test")
    if not os.path.isdir(ftest):
        ftest = os.path.join(work, "frames_test")
    procs = max(1, getattr(args, "procs", 1) or 1)
    H.frames_stage("SEL", kits, fsel, tfs, procs)
    H.frames_stage("TEST", kits, ftest, tfs, procs)
    mks = {"SEL": H.CTX.get("SEL") or H.market("SEL", kits), "TEST": H.CTX.get("TEST") or H.market("TEST", kits),
           "EXTRA": H.market("EXTRA", kits)}
    cx = H.CX()
    old6, proxy = set(D.OLD_SIX), {s for s in H.SYMBOLS if cx[s]["proxy"]}
    groups = {"old_six": old6, "new_24": set(H.SYMBOLS) - old6, "still_listed_22": set(H.SYMBOLS) - proxy,
              "proxy_8": proxy}
    pdir = os.path.join(work, "picks")
    os.makedirs(pdir, exist_ok=True)
    _RUN.clear()
    _RUN.update(H=H, mks=mks, fdir={"SEL": fsel, "TEST": ftest, "EXTRA": fsel}, groups=groups, picks=picks, pdir=pdir)
    hours = getattr(args, "reads_hours", None)
    deadline = time.time() + float(hours) * 3600 if hours is not None else None
    todo = [i for i, p in enumerate(picks) if not os.path.exists(pick_file(pdir, i, p["id"]))]
    log(f"[reads] {len(todo)} of {len(picks)} picks to do, {procs} at once"
        + (f", no new pick after {hours} h" if hours is not None else ""))
    stopped = 0
    with cf.ProcessPoolExecutor(min(procs, max(1, len(todo))), mp_context=mp.get_context("fork")) as ex:
        pending, nxt = set(), 0
        while nxt < len(todo) or pending:
            while nxt < len(todo) and len(pending) < procs and (deadline is None or time.time() < deadline):
                pending.add(ex.submit(_pick_job, todo[nxt]))
                nxt += 1
            if not pending:
                stopped = len(todo) - nxt
                break
            done, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for f in done:
                msg = f.result()
                if msg:
                    log(f"[reads] {msg}")
    full, summary, missing = {}, [], []
    for i, pick in enumerate(picks):
        path = pick_file(pdir, i, pick["id"])
        if not os.path.exists(path):
            missing.append(pick["id"])
            continue
        out = H.load_json(path)
        full[pick["id"]] = out
        tf = pick["tf"]
        if not H.is_ds(pick):
            l1 = out["R1"]["TEST"]["list"]
            summary.append(f"{pick['name']} {H.TF_KO[tf]}: 주말 포함(R1) 확인 기간 승률 {H._pct(l1.get('win'))}, "
                           f"매매당 평균 {H._pct(l1.get('mean'), 3)}")
        else:
            summary.append(f"{pick['name']} (딥시크) {H.TF_KO[tf]}: 참고 계산 끝 (숫자는 비공개)")
    if missing:
        summary.append(f"참고 계산이 끝나지 않은 것 {len(missing)}개 (시간 한도 또는 오류; 판정과 관계없음)")
    public = {"what": "PREREG_HIWR 14: reads, reported beside the verdict, never a pass",
              "picks": {pid: (labels_only(v, H) if v["kind"] == "ds" else v) for pid, v in full.items()},
              "R14_sha256": {pid: v["R14_sha256"] for pid, v in full.items()}, "summary_ko": summary,
              "missing": missing, "not_started_after_deadline": stopped}
    return public, {"picks": full, "missing": missing}


def one_pick(H, mks: dict, fdir: dict, groups: dict, pick: dict) -> dict:
    """All reads of one pick (section 14), as a JSON-ready dict."""
    W, A = H.W, H.A
    cfgs = H.exit_configs()
    cx = H.CX()
    fsel, ftest = fdir["SEL"], fdir["TEST"]
    pid, tf = pick["id"], pick["tf"]
    cfg = cfgs[pick["ci"]]
    cap = A.CAP[tf]
    f = float(pick["f_star"])
    out = {"id": pid, "kind": pick["kind"], "name": pick["name"], "tf": tf}
    base = {p: pick_list(H, mks[p], fdir[p], pick, cfg, details=(p == "TEST")) for p in ("SEL", "TEST", "EXTRA")}
    acc_base = {p: acct(H, mks[p], base[p], cfg, f) for p in ("SEL", "TEST", "EXTRA")}
    # R9 (and the f* recheck)
    sz = H.size_pair(mks["SEL"], base["SEL"]["cand"], cfg, tf, pid)
    fp = sz["f_path"]["f"]
    r9 = {"f_star_recomputed": sz["f_star"]["f"], "f_star_registered": f,
          "f_star_same": bool(abs(sz["f_star"]["f"] - f) < 1e-9), "f_path": fp}
    for p in ("SEL", "TEST"):
        draws = A.boot_draws(mks[p].period, pid, p, H.N_F95)
        for lab, ff in (("f_star", f), ("f_path", fp)):
            res = acc_base[p] if lab == "f_star" else acct(H, mks[p], base[p], cfg, ff)
            bd = A.boot_dd(res, mks[p].period, draws) if ff > 0 and res["n"] else np.zeros(1)
            r9[f"{p}_{lab}"] = {"boot_q95": float(np.quantile(bd, 0.95)), "share_over_cap": float((bd > cap).mean()),
                                "dd": res["dd"]}
            if p == "TEST" and lab == "f_path":
                r9["TEST_account_f_path"] = acct_short(H, res)
    out["R9"] = r9
    # R1 with weekends
    we = {p: pick_list(H, mks[p], fdir[p], pick, cfg, weekend_rule=False) for p in ("SEL", "TEST")}
    szw = H.size_pair(mks["SEL"], we["SEL"]["cand"], cfg, tf, f"{pid}|R1")
    fw = szw["f_star"]["f"]
    out["R1"] = {"f_star": fw, "margin_pct": szw["f_star"]["margin_pct"],
                 **{p: {"list": H.list_stats(we[p]), "account": acct_short(H, acct(H, mks[p], we[p], cfg, fw))
                        if fw > 0 else None} for p in ("SEL", "TEST")}}
    # R2 other tiers whose after-fee ROE range contains the TP price (same fill)
    rt = W.RT_TAKER if cfg["fill"] == 0 else W.RT_MAKER
    r2 = {}
    for L2 in W.LEVS:
        if L2 == cfg["L"]:
            continue
        roe = (cfg["t"] - rt) * L2
        lo_, hi_ = W.ROE_STEPS[L2][0], W.ROE_STEPS[L2][-1]
        if not (lo_ - 1e-9 <= roe <= hi_ + 1e-9):
            r2[f"L{L2}"] = {"in_range": False, "roe": roe}
            continue
        c2 = variant_cfg(W, cfg, L=L2, roe=roe)
        s2 = pick_list(H, mks["SEL"], fsel, pick, c2)
        z2 = H.size_pair(mks["SEL"], s2["cand"], c2, tf, f"{pid}|R2|L{L2}")
        f2 = z2["f_star"]["f"]
        t2 = pick_list(H, mks["TEST"], ftest, pick, c2)
        r2[f"L{L2}"] = {"in_range": True, "roe": roe, "SEL": H.list_stats(s2), "f_star": f2,
                        "margin_pct": z2["f_star"]["margin_pct"], "TEST": H.list_stats(t2),
                        "TEST_account": acct_short(H, acct(H, mks["TEST"], t2, c2, f2)) if f2 > 0 else None}
    out["R2"] = r2
    # R3 loose buffer
    with loose_buffer(W):
        l3 = {p: pick_list(H, mks[p], fdir[p], pick, cfg) for p in ("SEL", "TEST")}
        a3 = acct(H, mks["TEST"], l3["TEST"], cfg, f)
    out["R3"] = {"SEL": H.list_stats(l3["SEL"]), "TEST": H.list_stats(l3["TEST"]),
                 "TEST_account": acct_short(H, a3), "TEST_account_liquidations": int((a3["kind"] == W.X_LIQ).sum())}
    # R4 gross reading
    cg = variant_cfg(W, cfg, t=W.tp_move(cfg["L"], cfg["roe"], cfg["fill"], "gross"), reading="gross")
    g4 = {p: pick_list(H, mks[p], fdir[p], pick, cg) for p in ("SEL", "TEST")}
    z4 = H.size_pair(mks["SEL"], g4["SEL"]["cand"], cg, tf, f"{pid}|R4")
    f4 = z4["f_star"]["f"]
    out["R4"] = {"t": cg["t"], "f_star": f4, **{p: {"list": H.list_stats(g4[p]), "account": acct_short(
        H, acct(H, mks[p], g4[p], cg, f4)) if f4 > 0 else None} for p in ("SEL", "TEST")}}
    # R5 coins
    r5 = {}
    for p in ("SEL", "TEST"):
        names = np.asarray(mks[p].syms)
        ok = base[p]["skip"] == 0
        for gname, members in groups.items():
            m = ok & np.isin(names[base[p]["coin"].astype(int)] if len(base[p]["coin"]) else np.zeros(0, bool),
                             list(members))
            x = base[p]["r"][m]
            r5.setdefault(gname, {})[p] = {"n": int(len(x)), "win": float((x > 0).mean()) if len(x) else None,
                                           "mean": float(x.mean()) if len(x) else None}
    nt = r5["new_24"]["TEST"]["mean"]
    r5["carried_by_old_six"] = bool(nt is None or nt <= 0)
    out["R5"] = r5
    # R6 extra 2020
    out["R6"] = {"list": H.list_stats(base["EXTRA"]), "account": acct_short(H, acc_base["EXTRA"])}
    # R7 maker realism
    out["R7"] = maker_realism(H, mks["TEST"], ftest, pick, cfg, base["TEST"])
    # R8 goal board
    out["R8"] = {p: goal_board(H, acc_base[p], mks[p].period) for p in ("SEL", "TEST")}
    # R10 flat by Saturday
    out["R10"] = flat_by_saturday(H, mks["TEST"], base["TEST"], cfg, f)
    # R11 splits and counts
    out["R11"] = {p: dict(splits(H, mks[p], base[p]), skipped=dict(
        {k: v for k, v in H.list_stats(base[p]).items() if k.startswith("skip_")},
        weekend=int(base[p]["weekend_dropped"]), **{f"account_{k}": v for k, v in acc_base[p]["counts"].items()},
        account_bracket_cut=int(acc_base[p]["n_cut"]))) for p in ("SEL", "TEST")}
    # R12 live sizes
    r12 = {}
    for w0 in LIVE_WALLETS:
        res = acct(H, mks["TEST"], base["TEST"], cfg, f, w0=w0)
        cand = base["TEST"]["cand"]
        errs, below = [], 0
        st_ = mks["TEST"].store
        for i, q in enumerate(res["taken"]):
            c = int(cand["coin"][q])
            sg = 1.0 if cand["side"][q] > 0 else -1.0
            F = st_.o[st_.off[c] + cand["e"][q]] * (1.0 + sg * W.SLIP)
            step = cx[mks["TEST"].syms[c]]["qty_step"]
            qty = res["N"][i] / F
            rq = math.floor(qty / step + 1e-9) * step
            errs.append(rq / qty - 1.0)
            if rq * F < cx[mks["TEST"].syms[c]]["min_notional"]:
                below += 1
        errs = np.asarray(errs)
        r12[f"wallet_{int(w0)}"] = {"trades": res["n"], "mean_size_error": float(errs.mean()) if len(errs) else None,
                                    "worst_size_error": float(errs.min()) if len(errs) else None,
                                    "below_min_notional_after_rounding": int(below),
                                    "minimum_notional_skips": res["counts"].get("minimum notional", 0)}
    out["R12"] = r12
    # R13 streaks
    okt = base["TEST"]["skip"] == 0
    order = np.lexsort((base["TEST"]["side"][okt], base["TEST"]["coin"][okt], base["TEST"]["entry_ms"][okt]))
    out["R13"] = {"trade_list": streaks(base["TEST"]["r"][okt][order]), "account": streaks(acc_base["TEST"]["r"])}
    # R14 forward band
    r14 = band(H, base["TEST"], acc_base["TEST"], mks["TEST"].period)
    out["R14"] = r14
    out["R14_sha256"] = hashlib.sha256(json.dumps(H._jsonable(r14), sort_keys=True).encode()).hexdigest()
    return H._jsonable(out)
