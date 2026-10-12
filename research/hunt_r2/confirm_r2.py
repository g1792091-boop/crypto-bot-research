"""Hunt round 2 test step (PREREG_HUNT_R2.md section 7, 10.1, 10.4): one confirm look, hunt-r2 v1.

Each tested pick runs once on the test period (2024-01-01 .. 2026-10-01) at r = 0.5%, base cost and cost x2; its
anchor default (same family, name, timeframe and gate, the default numbers) runs once at base cost and cost x2 as the
comparator of 7.2. Nothing else of round 2 runs on the test period here.

Signals: round 2's own events (``entries_r2.SeriesEvents`` on the installed series, the W 3.2 edge before the gate)
turned into the engine's signal dicts {tf, k, j, side} exactly as ``hunt.system_signals`` does (period, both-sides
rule, gate, ATR14 > 0, a fill bar). Round 2 never passes a spec dict to round 1's spec-based path (11); the engine is
used through ``hunt.run_signals``, ``control_a``, ``control_b``, ``boot_p``, ``seed_rank_p``, ``bh`` and ``rng_of`` on
these dicts only.

7.1 R2 PASS, per pick: P0 (>= 2 positions per test month, a position open in >= 80% of months, no bust), P1 (median
monthly multiple >= 1 and mean monthly ln M > 0), P3 (the same at cost x2), P4 (max drawdown < 50%), the seed-rank
parts of controls (a) random times, (b) coin-flip sides, (b-c) one coin per signal-bar close shared by all coins (1,000
seeds each) and (a-c) the common whole-week circular shift (every shift of 4 .. floor((L - 28) / 7) weeks, L = the test
period in days: 136 shifts), and a BH-significant p within its batch. p = max(p_a, p_b); p_x = the larger of the
one-sided month bootstrap p of mean d_m (100,000 resamples) and the one-sided t_32 p of mean d_m. Batch n + 1 is tested
only when at least 5 picks of batch n PASS.

7.2 TUNED BETTER: d_tune,m = ln M_m(pick) - ln M_m(anchor default) (base cost); p_tune = the larger of the bootstrap
p ("tune" seed parts) and the t_32 p; BH per batch over the tested picks' p_tune; TUNED BETTER = BH-significant and
mean d_tune at cost x2 > 0. Every tested pick carries one of three labels with the mean d_tune and its month 90% CI.

Seeds: sha256 of ("hunt-r2", system id, control, period, r, seed) joined as ``hunt.seed_int`` joins them; the
bootstrap seed has "boot" as the seed part; the tuning bootstrap uses control "tune" (CI: seed part "ci").
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt_r2 import entries_r2 as E  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402

SEED_TAG = "hunt-r2"
N_SEEDS = 1000                    # 7.1: controls (a), (b), (b-c), seeds 1-1,000 each
N_BOOT = 100_000                  # 7.1 / 7.2: month bootstrap resamples
AC_MIN_WEEKS = 4                  # 7.1 (a-c): whole-week shifts from 4 weeks ...
AC_EDGE_DAYS = 28                 # ... to floor((L - 28) / 7) weeks
CI_CONF = 0.90                    # 7.2: month 90% CI of mean d_tune
P_ALPHA = H.P_ALPHA               # 0.05: seed-rank parts
BH_Q = H.BH_Q                     # 0.10: BH per batch
BATCH_TRIGGER = H.BATCH_TRIGGER   # 5: batch n + 1 only when >= 5 of batch n PASS
CTL_TASK_SEEDS = 25               # control seeds per worker task
RANK_PARTS = ("a", "b", "bc", "ac")
CONTROL_NAMES = {"a": "(a) random times", "b": "(b) coin-flip sides",
                 "bc": "(b-c) one coin per signal-bar close shared by all coins",
                 "ac": "(a-c) common whole-week circular shift inside each coin's valid test span"}
TUNE_LABELS = {"better": ("tuning beat the textbook numbers", "커스텀이 기본값을 이김"),
               "worse": ("worse than the textbook numbers", "기본값보다 나쁨"),
               "not_shown": ("not shown to beat the textbook numbers", "기본값보다 낫다고 말할 만큼은 아님")}
VERDICT_NOTE = ("R2 PASS and TUNED BETTER are reported beside v1 PASS, WIDE PASS and track 2, never merged with them; "
                "four studies share one 33-month period (2024-01 .. 2026-09).")
BATCH_LABELS = H.BATCH_LABELS

CHOICES = [
    "7.1 (b-c): one fair coin per distinct signal-bar close (ms) of the pick's gated signals, drawn in ascending close "
    "order from the seed's PCG64 (heads = uniform < 0.5 keeps the side); every coin's event at that close flips "
    "together.",
    "7.1 (a-c): the shift of 4.3 (a′) applied over the test period (select_r2.shift_sig on the test market): each "
    "coin's span s_c .. e_c = its first / last test-period signal-bar close with a 장세 label, ATR14 > 0, a fill bar "
    "and the 300-bar warm-up; L_c floored to whole weeks; landing bars without a label, ATR14 > 0 or a fill bar are "
    "dropped and counted; two events of one coin landing on one bar: one event when they agree, none when opposite "
    "(W 3.2), counted 'collided'. Shifts 4 .. floor((L - 28) / 7) weeks, L = the test period in days.",
    "7.1 p: the t_32 p is scipy's one-sided Student t survival function of mean / (sd(ddof 1) / sqrt(n)) with n - 1 "
    "degrees of freedom; a zero sd gives p = 0 when the mean is > 0, else 1 (the bootstrap p then decides).",
    "7.1 d_m as H 12 (round 1's judge): the pick's monthly ln M minus the mean over seeds of each month's control ln M.",
    "7.2: the month 90% CI of mean d_tune is the 5th and 95th percentile of 100,000 resampled means (months with "
    "replacement, seed part 'ci'); 'worse than the textbook numbers' when its upper end is below 0.",
    "7.2: the anchor default is run on the test period by round 2's own events with the default numbers at the pick's "
    "timeframe and gate (system id R2:<family>:<name>:<tf>:<gate>:<default combo sha>); it is a comparator only.",
    "10.1 lineup: round 1's rule (g) as hunt.lineup_of computes it (정식 = PASS; 참고 = mean ln M > 0, median M >= 1, "
    "mean d_m above 0 against (a) and (b), cost x2 mean ln M > 0, max drawdown < 50%, no bust, best month < 50% of the "
    "total log gain).",
]


# ------------------------------------------------------------------ systems
def system_of(row: dict, role: str = "pick") -> dict:
    """A picks.json pick row (5) as the system dict the test step runs; its id is checked against the numbers."""
    fam, name = row["family"], row["name"]
    tf, gate = row["anchor"]["tf"], row["anchor"]["gate"]
    combo = row["peak"]
    sid = L.system_id(fam, name, tf, gate, combo)
    if row.get("id") and row["id"] != sid:
        raise RuntimeError(f"picks.json row {name}: id {row['id']} does not match its numbers ({sid})")
    out = {"id": sid, "family": fam, "name": name, "strategy": name, "kind": L.KIND_OF[fam], "tf": tf, "gate": gate,
           "combo": combo, "role": role}
    for k in ("pick_no", "batch", "rank"):
        if row.get(k) is not None:
            out[k] = int(row[k])
    return out


def default_system_of(sys_: dict) -> dict:
    """7.2: the pick's anchor default (same family, name, timeframe and gate; the default numbers)."""
    combo = L.default_combo(sys_["name"])
    sid = L.system_id(sys_["family"], sys_["name"], sys_["tf"], sys_["gate"], combo)
    return {"id": sid, "family": sys_["family"], "name": sys_["name"], "strategy": sys_["name"], "kind": sys_["kind"],
            "tf": sys_["tf"], "gate": sys_["gate"], "combo": combo, "role": "anchor default (comparator)"}


def is_ds(sys_: dict) -> bool:
    return sys_.get("family") == "F3" or sys_.get("kind") == "ds"


# ------------------------------------------------------------------ round 2's events -> signal dicts
_EV: dict = {}           # (system id, sym) -> (series object, long events, short events)
_SIG: dict = {}          # (market key, system id, gate) -> signals


def clear_caches() -> None:
    _EV.clear()
    _SIG.clear()


def events_of(sys_: dict, sym: str) -> tuple:
    """Ungated (long, short) events of the system on the coin's installed series (entries_r2, W 3.2 edge, warm-up)."""
    ser = H.series(sym, sys_["tf"])
    key = (sys_["id"], sym)
    hit = _EV.get(key)
    if hit is not None and hit[0] is ser:
        return hit[1], hit[2]
    btc = None
    if sys_["kind"] == "ds" and sym != "BTCUSDT":
        btc = H.series("BTCUSDT", sys_["tf"]).bars
    el, es = E.SeriesEvents(sys_["name"], ser.bars, sym, btc).events(sys_["combo"])
    _EV[key] = (ser, np.asarray(el, bool), np.asarray(es, bool))
    return _EV[key][1], _EV[key][2]


def signals(mk, sys_: dict, gate: str | None = None) -> dict:
    """The system's gated signals in the market's period, as hunt.system_signals builds them (coin, longs before
    shorts, signal bar), from round 2's events. Counts: events, both sides, gated out, no ATR, no fill."""
    gate = gate or sys_["gate"]
    key = (mk.key, sys_["id"], gate)
    hit = _SIG.get(key)
    if hit is not None:
        return hit
    tf = sys_["tf"]
    K, J, S = [], [], []
    cnt = {"events": 0, "both": 0, "gated_out": 0, "no_atr": 0, "no_fill": 0, "gated": 0}
    for k, s in enumerate(mk.syms):
        ser = H.series(s, tf)
        lg, sh = events_of(sys_, s)
        cm = ser.bars.close_ms
        inper = (cm >= mk.start) & (cm < mk.end)
        both = lg & sh & inper
        lg, sh = lg & inper & ~both, sh & inper & ~both
        cnt["events"] += int(lg.sum() + sh.sum() + 2 * both.sum())
        cnt["both"] += int(both.sum())
        g = H.gate_mask(ser, gate)
        atr_ok = np.isfinite(ser.atr) & (ser.atr > 0)
        _, f_ok = H.fill_index(mk, k, ser)
        for side, ev in ((1, lg), (-1, sh)):
            cnt["gated_out"] += int((ev & ~g).sum())
            cnt["no_atr"] += int((ev & g & ~atr_ok).sum())
            cnt["no_fill"] += int((ev & g & atr_ok & ~f_ok).sum())
            jj = np.flatnonzero(ev & g & atr_ok & f_ok)
            K.append(np.full(len(jj), k, np.int64))
            J.append(jj.astype(np.int64))
            S.append(np.full(len(jj), side, np.int64))
    cat = lambda xs: np.concatenate(xs) if xs else np.zeros(0, np.int64)  # noqa: E731
    out = {"tf": tf, "k": cat(K), "j": cat(J), "side": cat(S), "counts": cnt}
    cnt["gated"] = int(len(out["k"]))
    _SIG[key] = out
    return out


def close_ms_of(mk, sig: dict) -> np.ndarray:
    """Signal-bar close (ms) of every signal."""
    out = np.zeros(len(sig["k"]), np.int64)
    for k in np.unique(sig["k"]):
        sel = sig["k"] == k
        out[sel] = H.series(mk.syms[int(k)], sig["tf"]).bars.close_ms[np.asarray(sig["j"])[sel]]
    return out


# ------------------------------------------------------------------ controls (7.1)
def seed_parts(sid: str, ctl: str, period: str, r: float, s) -> tuple:
    return (SEED_TAG, sid, ctl, period, float(r), s)


def control_bc(sig: dict, close_ms: np.ndarray, rng: np.random.Generator) -> dict:
    """(b-c): one fair coin per distinct signal-bar close, shared by every coin with a signal at that close."""
    u, inv = np.unique(np.asarray(close_ms, np.int64), return_inverse=True)
    heads = rng.random(len(u)) < 0.5
    side = np.asarray(sig["side"], np.int64)
    return {"tf": sig["tf"], "k": np.asarray(sig["k"]).copy(), "j": np.asarray(sig["j"]).copy(),
            "side": np.where(heads[inv], side, -side)}


def ac_weeks(mk) -> list:
    """(a-c): every whole-week shift from 4 weeks to floor((L - 28) / 7) weeks, L = the period in days."""
    L_days = (mk.end - mk.start) // H.DAY_MS
    return list(range(AC_MIN_WEEKS, (L_days - AC_EDGE_DAYS) // 7 + 1))


_T: dict = {"mk": {}, "sig": {}, "close": {}, "ctx": {}}     # set in the parent before a pmap (fork inherits it)


def control_sig(mk, sig: dict, sid: str, ctl: str, r: float, s) -> tuple:
    """One control draw: (signals, counts). ``s`` = seed number, or the shift in weeks for (a-c)."""
    if ctl == "ac":
        ctx = _T["ctx"].get(mk.key)
        if ctx is None:
            ctx = _T["ctx"][mk.key] = SR.Ctx(mk, None)
        return SR.shift_sig(ctx, sig, int(s) * 7 * H.DAY_MS)
    rng = H.rng_of(*seed_parts(sid, ctl, mk.period, r, s))
    if ctl == "a":
        return H.control_a(mk, sig, rng), {}
    if ctl == "b":
        return H.control_b(sig, rng), {}
    if ctl == "bc":
        close = _T["close"].get((mk.key, sid))
        if close is None:
            close = _T["close"][(mk.key, sid)] = close_ms_of(mk, sig)
        return control_bc(sig, close, rng), {}
    raise ValueError(f"control {ctl!r}")


def _ctl_task(task) -> tuple:
    mkey, sid, ctl, seeds, r = task
    mk = _T["mk"][mkey]
    sig = _T["sig"][(mkey, sid)]
    rows, cnt = [], {}
    for s in seeds:
        csig, c = control_sig(mk, sig, sid, ctl, r, s)
        for k, v in c.items():
            cnt[k] = cnt.get(k, 0) + int(v)
        rows.append(H.run_signals(mk, [(csig, 0)], r)["lnM"])
    return rows, cnt


def run_controls(mk, sys_: dict, sig: dict, r: float, procs: int, n_seeds: int | None = None,
                 ctls=RANK_PARTS) -> dict:
    """Every control of 7.1 for one system on one market: {ctl: (draws, months) monthly ln M}, the (a-c) weeks and
    its drop / collision counts."""
    n_seeds = N_SEEDS if n_seeds is None else int(n_seeds)
    sid = sys_["id"]
    _T["mk"][mk.key] = mk
    _T["sig"][(mk.key, sid)] = sig
    _T["close"][(mk.key, sid)] = close_ms_of(mk, sig)
    tasks = []
    weeks = ac_weeks(mk)
    for ctl in ctls:
        draws = weeks if ctl == "ac" else list(range(1, n_seeds + 1))
        for i in range(0, len(draws), CTL_TASK_SEEDS):
            tasks.append((mk.key, sid, ctl, tuple(draws[i:i + CTL_TASK_SEEDS]), float(r)))
    res = H.pmap(_ctl_task, tasks, procs, label=f"controls {sid} {mk.period} r={r:g}")
    out = {c: [] for c in ctls}
    cnt = {}
    for t, (rows, c) in zip(tasks, res):
        out[t[2]].extend(rows)
        if t[2] == "ac":
            for k, v in c.items():
                cnt[k] = cnt.get(k, 0) + v
    n_m = len(mk.months)
    out = {c: (np.asarray(v, float) if v else np.zeros((0, n_m))) for c, v in out.items()}
    out["ac_weeks"] = weeks if "ac" in ctls else []
    out["ac_counts"] = cnt
    out["gated"] = int(len(sig["k"]))
    return out


# ------------------------------------------------------------------ p-values (7.1, 7.2)
def t_p(d) -> float:
    """One-sided t p of mean d > 0 (n - 1 degrees of freedom; t_32 for 33 months)."""
    from scipy.stats import t as student
    d = np.asarray(d, float)
    n = len(d)
    if n < 2:
        return 1.0
    m, sd = float(d.mean()), float(d.std(ddof=1))
    if not np.isfinite(sd) or sd <= 0.0:
        return 0.0 if m > 0 else 1.0
    return float(student.sf(m / (sd / math.sqrt(n)), n - 1))


def boot_and_t(d, seed: int, n_boot: int | None = None) -> dict:
    """The larger of the one-sided month bootstrap p and the one-sided t p (7.1, 7.2)."""
    n_boot = N_BOOT if n_boot is None else int(n_boot)
    pb = H.boot_p(np.asarray(d, float), seed, n_boot)
    pt = t_p(d)
    p = max(pb, pt)
    return {"p_boot": float(pb), "p_t": float(pt), "p": float(p) if np.isfinite(p) else 1.0}


def month_ci(d, seed: int, n_boot: int | None = None, conf: float = CI_CONF) -> list:
    """Month bootstrap percentile interval of mean d (months resampled with replacement)."""
    n_boot = N_BOOT if n_boot is None else int(n_boot)
    d = np.asarray(d, float)
    if not len(d):
        return [None, None]
    rng = np.random.Generator(np.random.PCG64(seed))
    means = np.empty(n_boot)
    step = max(1, 2_000_000 // max(len(d), 1))
    for i in range(0, n_boot, step):
        m = min(step, n_boot - i)
        means[i:i + m] = d[rng.integers(0, len(d), size=(m, len(d)))].mean(axis=1)
    a = (1.0 - conf) / 2.0
    return [float(np.quantile(means, a)), float(np.quantile(means, 1.0 - a))]


def judge(base: dict, cost2: dict, ctl: dict, sid: str, period: str, r: float) -> dict:
    """7.1 per pick: P0, P1, P3, P4, p_a, p_b (each the larger of bootstrap and t), p = max(p_a, p_b), and the four
    seed-rank parts."""
    n_m = base["months"]
    lnM = np.asarray(base["lnM"], float)
    res = {"P0": bool(base["n_positions"] >= H.POS_PER_MONTH * n_m
                      and base["share_months_with_position"] >= H.MONTH_COVER and not base["bust"]),
           "P1": bool(base["median_M"] >= 1.0 and base["mean_lnM"] > 0),
           "P3": bool(cost2["median_M"] >= 1.0 and cost2["mean_lnM"] > 0),
           "P4": bool(base["max_dd"] < H.DD_MAX)}
    for c in ("a", "b"):
        seeds = np.asarray(ctl[c], float)
        d = lnM - seeds.mean(axis=0) if len(seeds) else lnM * 0.0
        pp = boot_and_t(d, H.seed_int(*seed_parts(sid, c, period, r, "boot")))
        res[f"p_boot_{c}"], res[f"p_t_{c}"], res[f"p_{c}"] = pp["p_boot"], pp["p_t"], pp["p"]
        res[f"mean_d_{c}"] = float(d.mean()) if len(d) else 0.0
    for c in RANK_PARTS:
        seeds = np.asarray(ctl[c], float)
        rp = H.seed_rank_p(base["mean_lnM"], seeds.mean(axis=1)) if len(seeds) else 1.0
        res[f"rank_p_{c}"] = float(rp)
        res[f"rank_ok_{c}"] = bool(rp < P_ALPHA)
        res[f"n_{c}"] = int(len(seeds))
    p = max(res["p_a"], res["p_b"])
    res["p"] = float(p) if np.isfinite(p) else 1.0
    return res


def tune_block(pick_base: dict, pick_x2: dict, def_base: dict, def_x2: dict, sid: str, period: str,
               r: float) -> dict:
    """7.2: d_tune per month (base cost), p_tune (larger of bootstrap and t), mean d_tune at cost x2, month 90% CI."""
    d = np.asarray(pick_base["lnM"], float) - np.asarray(def_base["lnM"], float)
    d2 = np.asarray(pick_x2["lnM"], float) - np.asarray(def_x2["lnM"], float)
    pp = boot_and_t(d, H.seed_int(*seed_parts(sid, "tune", period, r, "boot")))
    ci = month_ci(d, H.seed_int(*seed_parts(sid, "tune", period, r, "ci")))
    return {"d_tune": d.tolist(), "mean_d_tune": float(d.mean()) if len(d) else 0.0, "p_boot_tune": pp["p_boot"],
            "p_t_tune": pp["p_t"], "p_tune": pp["p"], "mean_d_tune_x2": float(d2.mean()) if len(d2) else 0.0,
            "ci90_mean_d_tune": ci}


def tune_label(tuned_better: bool, ci) -> dict:
    if tuned_better:
        k = "better"
    elif ci and ci[1] is not None and ci[1] < 0:
        k = "worse"
    else:
        k = "not_shown"
    return {"key": k, "en": TUNE_LABELS[k][0], "ko": TUNE_LABELS[k][1]}


# ------------------------------------------------------------------ one pick
def run_one(mk, sig: dict, r: float, cost: str, detail: bool, days: bool = False) -> dict:
    return H.run_signals(mk, [(sig, 0)], r, cost, detail=detail, days=days)


def pick_block(mk, sys_: dict, procs: int, r: float = H.R_BASE, n_seeds: int | None = None) -> dict:
    """7.1 and 7.2 for one tested pick on the test market: its runs, the four controls, the checks and the tuning
    comparison against its anchor default."""
    t0 = time.time()
    dsys = default_system_of(sys_)
    sig = signals(mk, sys_)
    dsig = signals(mk, dsys)
    base = run_one(mk, sig, r, "base", detail=True, days=True)
    cost2 = run_one(mk, sig, r, "x2", detail=True)
    dbase = run_one(mk, dsig, r, "base", detail=True)
    dcost2 = run_one(mk, dsig, r, "x2", detail=False)
    ctl = run_controls(mk, sys_, sig, r, procs, n_seeds)
    checks = judge(base, cost2, ctl, sys_["id"], mk.period, r)
    tune = tune_block(base, cost2, dbase, dcost2, sys_["id"], mk.period, r)
    return {"id": sys_["id"], "base": base, "cost2": cost2, "checks": checks, "tune": tune,
            "signal_counts": dict(sig["counts"]),
            "default": {"id": dsys["id"], "combo": dsys["combo"], "base": dbase, "cost2": dcost2,
                        "signal_counts": dict(dsig["counts"]),
                        "same_signals_as_pick": bool(SR.sig_hash(sig) == SR.sig_hash(dsig))},
            "controls": {f"{c}_mean_lnM": np.asarray(ctl[c], float).mean(axis=1).tolist() for c in RANK_PARTS}
            | {"seeds": int(N_SEEDS if n_seeds is None else n_seeds), "ac_weeks": ctl["ac_weeks"],
               "ac_counts": ctl["ac_counts"], "gated_signals": ctl["gated"],
               "names": dict(CONTROL_NAMES)},
            "coins_traded": list(base.get("coins_traded", [])), "seconds": round(time.time() - t0, 1)}


# ------------------------------------------------------------------ the walk over batches (7.1, 7.2, 10.1)
def batches_of(picks_doc: dict) -> list:
    """The batches of picks.json as lists of system dicts (membership fixed at select, 5)."""
    rows = {int(p["pick_no"]): p for p in picks_doc.get("picks", [])}
    nos = picks_doc.get("batches") or ([[n for n in sorted(rows)]] if rows else [])
    out = []
    for b, grp in enumerate(nos):
        out.append([dict(system_of(rows[int(n)]), batch=b + 1) for n in grp])
    return out


def test_walk(mk, picks_doc: dict, procs: int, block_fn=None) -> dict:
    """7.1 / 7.2 over the batches: batch 1 is tested; batch n + 1 only when >= 5 of batch n PASS. ``block_fn(sys)``
    returns a pick's block (the CLI resumes it from its part file); default ``pick_block``."""
    block_fn = block_fn or (lambda s: pick_block(mk, s, procs))
    batches = batches_of(picks_doc)
    blocks, tested, passing, tuned, info = {}, [], [], [], []
    for b, members in enumerate(batches):
        for p in members:
            blocks[p["id"]] = block_fn(p)
        sig = H.bh([blocks[p["id"]]["checks"].get("p", 1.0) for p in members], BH_Q)
        sig_t = H.bh([blocks[p["id"]]["tune"].get("p_tune", 1.0) for p in members], BH_Q)
        n_pass = n_tb = 0
        for p, s_, st_ in zip(members, sig, sig_t):
            blk = blocks[p["id"]]
            c, tu = blk["checks"], blk["tune"]
            c["bh_significant"] = bool(s_)
            c["batch"] = b + 1
            c["PASS"] = bool(all(c[x] for x in ("P0", "P1", "P3", "P4")) and
                             all(c[f"rank_ok_{x}"] for x in RANK_PARTS) and s_)
            tu["bh_significant"] = bool(st_)
            tu["TUNED_BETTER"] = bool(st_ and tu["mean_d_tune_x2"] > 0)
            tu["label"] = tune_label(tu["TUNED_BETTER"], tu["ci90_mean_d_tune"])
            if c["PASS"]:
                passing.append(p)
                n_pass += 1
            if tu["TUNED_BETTER"]:
                tuned.append(p)
                n_tb += 1
        tested += members
        opens = bool(n_pass >= BATCH_TRIGGER and b + 1 < len(batches))
        info.append({"batch": b + 1, "label": BATCH_LABELS[b] if b < len(BATCH_LABELS) else f"{b + 1}군",
                     "pick_nos": [int(p["pick_no"]) for p in members], "K": len(members), "passes": n_pass,
                     "tuned_better": n_tb, "bh_q": BH_Q, "opens_next": opens})
        if not opens:
            break
    tested_ids = {p["id"] for p in tested}
    untested = [p for grp in batches for p in grp if p["id"] not in tested_ids]
    verdict = {"r2_pass": bool(passing), "passing": [p["id"] for p in passing],
               "tuning_beat_textbook": bool(tuned), "tuned_better": [p["id"] for p in tuned],
               "batches_tested": [x["batch"] for x in info], "batches": info,
               "untested": [p["id"] for p in untested],
               "label": "picks tested", "note": VERDICT_NOTE}
    lineup = H.lineup_table(tested, blocks, "picks", verdict["passing"])
    return {"picks": tested, "untested": untested, "results": blocks, "verdict": verdict, "lineup": lineup}


def selection_failed_doc(picks_doc: dict) -> dict:
    """10.2: no candidate taken or every box failed: nothing runs on the test period, no ledger hypothesis."""
    return {"picks": [], "untested": [], "results": {},
            "verdict": {"r2_pass": False, "passing": [], "tuning_beat_textbook": False, "tuned_better": [],
                        "batches_tested": [], "batches": [], "untested": [],
                        "label": "round 2 fails at selection: nothing ran on the test period and no ledger "
                                 "hypothesis was added (4.3, 10.2)",
                        "select_label": picks_doc.get("label"), "note": VERDICT_NOTE},
            "lineup": {"rule": H.LINEUP_RULE, "picks": {}, "정식": [], "참고": [], "excluded": []}}


# ------------------------------------------------------------------ D11 (10.4)
NUMBER_KEYS = ("combo", "default_combo", "peak", "default", "numbers")
DS_PUBLIC_CHECKS = ("P0", "P1", "P3", "P4", "rank_ok_a", "rank_ok_b", "rank_ok_bc", "rank_ok_ac", "n_a", "n_b",
                    "n_bc", "n_ac", "bh_significant", "PASS", "batch")
DS_PUBLIC_TUNE = ("bh_significant", "TUNED_BETTER", "label")
DS_NOTE = "DeepSeek pick: figures in the private file (D11)"


def combo_like(v) -> bool:
    """A combo (the numbers of an entry): a dict of numbers or lists of numbers, nothing nested deeper."""
    if not isinstance(v, dict) or not v:
        return False
    for x in v.values():
        xs = x if isinstance(x, (list, tuple)) else [x]
        if not all(isinstance(y, (int, float, np.integer, np.floating)) and not isinstance(y, bool) for y in xs):
            return False
    return True


def d11_problems(doc, ds_ids: set, path: str = "test", under: bool = False) -> list:
    """10.4: no float under a DeepSeek row (a dict with family F3 / kind ds, or whose id / row names a DeepSeek
    system, or under a key that names one), except its numbers (combos) and win shares."""
    bad = []
    if isinstance(doc, dict):
        here = under or doc.get("family") == "F3" or doc.get("kind") == "ds" or \
            any(str(doc.get(k)) in ds_ids for k in ("id", "row") if k in doc)
        for k, v in doc.items():
            if k in ("win_share", "win_shares"):
                continue
            if here and k in NUMBER_KEYS and combo_like(v):
                continue
            hit = here or any(i in str(k) for i in ds_ids)
            bad += d11_problems(v, ds_ids, f"{path}.{k}", hit)
    elif isinstance(doc, (list, tuple)):
        for i, v in enumerate(doc):
            bad += d11_problems(v, ds_ids, f"{path}[{i}]", under)
    elif under and isinstance(doc, (float, np.floating)) and not isinstance(doc, bool):
        bad.append(path)
    return bad


def redact_block(blk: dict) -> dict:
    """A DeepSeek pick's public block: counts, labels and pass / fail flags only."""
    lab = H._labels_only
    tu = blk.get("tune") or {}
    return {"id": blk["id"], "note": DS_NOTE, "base": lab(blk["base"]), "cost2": lab(blk["cost2"]),
            "checks": {k: v for k, v in blk["checks"].items() if k in DS_PUBLIC_CHECKS},
            "tune": {k: tu[k] for k in DS_PUBLIC_TUNE if k in tu},
            "default": {"id": blk["default"]["id"], "combo": blk["default"]["combo"],
                        "base": lab(blk["default"]["base"]),
                        "same_signals_as_pick": blk["default"].get("same_signals_as_pick")},
            "signal_counts": blk.get("signal_counts"), "coins_traded": list(blk.get("coins_traded", []))}


def redact_test(full: dict) -> dict:
    """The public part of test.json: F1 / F2 / F5 picks in full, DeepSeek picks as counts, labels and their numbers."""
    out = {k: full[k] for k in ("picks", "untested", "verdict", "lineup")}
    out["results"] = {}
    for p in full["picks"]:
        blk = full["results"][p["id"]]
        out["results"][p["id"]] = redact_block(blk) if is_ds(p) else blk
    return out


def write_json(path: str, obj) -> str:
    return SR.write_json(path, obj)


def part_name(sys_: dict) -> str:
    return f"pick_{int(sys_.get('pick_no', 0)):02d}_{hashlib.sha256(sys_['id'].encode()).hexdigest()[:16]}.json"


def load_json(path: str):
    with open(path) as fh:
        return json.load(fh)
