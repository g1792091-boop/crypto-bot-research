"""장세 문지기 (regime gate) test, pre-registered in research/regimegate/PREREG_REGIMEGATE.md: do the owners' market
rules (trend strategies only in a trending market, reversion strategies only in a ranging one) make the signals they let
through better than the signals they block? Read-only research: public price data in, files out. No exchange key, no
order, no database of the bots; nothing on the trading path imports this file.

    python3 research/regimegate/gate.py history --data DATA --work WORK --out OUT [--procs N]
    python3 research/regimegate/gate.py forward --data DATA --fwd FWD --out OUT [--last-day 2026-10-30] [--procs N]
    python3 research/regimegate/gate.py report  --out OUT

history  Every signal of the 80 strategies' default numbers (rule bot 36 and DeepSeek 44; 15m 30m 1h 4h; six coins;
         signal bars closing 2021-01-01 .. 2026-09-30) as its own trade, looked up in the full grid's outcome tables
         (WORK = the full grid's work folder with frames/ and outcomes/; run.py trade_table: live sizing, $5,000, all
         costs), at the live exit (ladder|2) and at the 4 ATR + 3R exit (tp3R|4), with the signal bar's market state
         (research/fullgrid/regimes.py coin_states + tag). OUT/parts/history/<tf>_<SYMBOL>.npz, then OUT/history.json.
forward  The same for the rule bot's 36 on the live run's days: signal bars closing 2026-10-05 18:35 UTC .. the
         --last-day 00:00 UTC, 1m data to the end of --last-day (the full-grid archive DATA plus Binance's daily 1m and
         mark-price files of October in FWD/raw; October funding is not in the public archive yet: 0), the same kernel
         (each signal alone, $5,000): FWD/1m, FWD/frames, FWD/outcomes, OUT/parts/forward/*, OUT/forward.json.
report   OUT/RESULTS_KO.md from whichever of history.json / forward.json exists, and OUT/decision.json when both do.

The gates (PREREG 4): G1 by 장세 (trend and other classes only in 추세장, reversion only in 횡보장), G2 by 변동성
(trend and other only when 큼, reversion only when 작음), G3 none blocked (the baseline: every line's all-signal mean).
Per gate and line: allowed mean - blocked mean > 0 with a one-sided block bootstrap p < 0.05 (UTC weeks in history,
UTC days in forward), the allowed mean > 0, at least MIN_N allowed and blocked trades, and above a coin-flip control
(1,000 draws blocking the same number of signals of every strategy x timeframe cell at random).

DeepSeek money (means, sums, differences) stays out of every output unless FULLGRID_DS_MONEY=1 (owners' D11): a line
holding any DeepSeek trade keeps its counts, win rates, p-values and pass flags only.
"""

from __future__ import annotations

import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(_v, "1")     # one thread per worker process: the pool is the parallelism

import argparse
import functools
import json
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FG = os.path.join(ROOT, "research", "fullgrid")
for _p in (ROOT, FG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import regimes as RG  # noqa: E402  (imports run.py as "run")
import run as R  # noqa: E402

K, DATA = R.K, R.DATA
DS_MONEY = os.environ.get("FULLGRID_DS_MONEY") == "1"
STYLE_PATH = os.path.join(HERE, "style_map.json")
PIN_FILE = os.path.join(HERE, "PREREG_REGIMEGATE.sha256")
CLASSES = ("trend", "reversion", "other")
CLASS_KO = {"trend": "추세형", "reversion": "되돌림형", "other": "그 밖(섞임·반전형·신호 부족)", "pooled": "전체"}
GROUPS = ("pooled",) + CLASSES
REGIME = ("모름", "추세장", "횡보장", "급변장", "보통")       # stored codes 0..4 (regime5y order)
VOL = ("모름", "작음", "보통", "큼")                           # stored codes 0..3
READS = ("ladder|2", "tp3R|4")                                 # the live exit first: the primary read
READ_KO = {"ladder|2": "지금 청산(2 ATR 손절 + 계단 익절)", "tp3R|4": "4 ATR 손절 + 3R 익절"}
READ_IDX = tuple([e[0] for e in K.EXITS].index(r) for r in READS)
GATES = {
    "G1": {"dim": "장세", "allow": {"trend": ("추세장",), "reversion": ("횡보장",), "other": ("추세장",)}},
    "G2": {"dim": "변동성", "allow": {"trend": ("큼",), "reversion": ("작음",), "other": ("큼",)}},
}
# descriptive only (PREREG 7): the same gate with the trend and reversion markets swapped
SWAPS = {f"{g}s": {"dim": v["dim"], "allow": {"trend": v["allow"]["reversion"], "reversion": v["allow"]["trend"],
                                               "other": v["allow"]["other"]}} for g, v in GATES.items()}
ALPHA = 0.05
N_BOOT = 2000
N_FLIP = 1000
MIN_N = {"history": 100, "forward": 30}
DAY = 86_400_000


def ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value // 1_000_000)


HIST_FROM, HIST_TO = R.PERIOD_MS[R.P_SELECT][1], R.PERIOD_MS[R.P_TEST][2]      # 2021-01-01 .. 2026-10-01
FWD_FROM = ms("2026-10-05 18:35")                                              # the rule bot v4 run's start
FWD_LAST_DAY = "2026-10-30"                                                    # PREREG 5.2: data to its end


# ------------------------------------------------------------------ strategies and their classes
@functools.lru_cache(maxsize=1)
def style() -> dict:
    with open(STYLE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def style_class(kind: str, name: str) -> str:
    return style()[kind][name]["class"]


@functools.lru_cache(maxsize=None)
def all_cells() -> tuple:
    """(kind, name, tf) of the 315 full-grid cells in run.cells() order (core first): a row's ``cell`` indexes this."""
    return tuple(R.cells())


def pin_problems() -> list[str]:
    """PREREG_REGIMEGATE.sha256 must exist and match (the rules run exactly as pinned before any result)."""
    if not os.path.exists(PIN_FILE):
        return ["PREREG_REGIMEGATE.sha256 missing: pin the files before running"]
    bad = []
    for line in open(PIN_FILE, encoding="utf-8"):
        if line.strip():
            h, f = line.split(None, 1)
            if R._sha(os.path.join(HERE, f.strip())) != h:
                bad.append(f"{f.strip()} does not match PREREG_REGIMEGATE.sha256")
    return bad


def code_stamp() -> dict:
    files = {f: R._sha(os.path.join(HERE, f)) for f in ("gate.py", "style_map.json", "PREREG_REGIMEGATE.md")
             if os.path.exists(os.path.join(HERE, f))}
    return {"fullgrid": R.code_stamp(), "regimegate": files}


# ------------------------------------------------------------------ per-signal tables
COLS = ("cell", "coin", "side", "close", "x0", "x1", "regime", "vol")


@functools.lru_cache(maxsize=4)
def coin_state(data_dir: str, sym: str, tf: str) -> dict:
    return RG.coin_states(data_dir, sym, tf)


def label_codes(close: np.ndarray, st: dict) -> tuple[np.ndarray, np.ndarray]:
    """(장세 code, 변동성 code) of each signal bar closing at ``close`` (one coin), as regimes.tag reads them."""
    if not len(close):
        return np.zeros(0, np.int8), np.zeros(0, np.int8)
    lab = RG.tag({"close": np.asarray(close, np.int64), "coin": np.zeros(len(close), int)}, [st])
    reg = np.array([REGIME.index(v) if v is not None else 0 for v in lab["장세"]], np.int8)
    vol = np.array([VOL.index(v) if v is not None else 0 for v in lab["변동성"]], np.int8)
    return reg, vol


def part_path(out: str, ev: str, tf: str, sym: str) -> str:
    return os.path.join(out, "parts", ev, f"{tf}_{sym}.npz")


def _sides(lo: np.ndarray, sh: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    il, is_ = np.flatnonzero(lo), np.flatnonzero(sh)
    return np.r_[il, is_], np.r_[np.ones(len(il), np.int8), -np.ones(len(is_), np.int8)]


def table_job(args) -> str:
    """Every default-number signal of one coin and timeframe, every cell of the evaluation: one row per signal with
    its two reads' P&L / $5,000 (NaN: not sized, still open at the data end, no ATR) and its market state."""
    ev, data_dir, work, out, tf, sym, lo_ms, hi_ms, ex = args
    path = part_path(out, ev, tf, sym)
    if os.path.exists(path):
        return ""
    t0 = time.time()
    ci = R.SYMBOLS.index(sym)
    _df, close = R.frame(data_dir, sym, tf)
    win = (close >= lo_ms) & (close < hi_ms)
    k0 = int(np.argmax(win)) if win.any() else 0
    oc = None
    if ev == "forward":
        oc = forward_outcomes(data_dir, work, sym, tf, lo_ms, hi_ms, ex)
        if not np.array_equal(oc["bars"], np.flatnonzero(win)):
            raise SystemExit(f"{work}/outcomes/{tf}_{sym}.npz is for other bars: remove FWD/outcomes and run again")
    rows = {k: [] for k in COLS}
    open_end = 0
    for c, (kind, name, ctf) in enumerate(all_cells()):
        if ctf != tf or (ev == "forward" and kind != "core"):
            continue
        lo, sh = R.signals(data_dir, kind, name, sym, tf, R.default_combo(kind, name))
        idx, side = _sides(np.asarray(lo, bool) & win, np.asarray(sh, bool) & win)
        col = np.where(side > 0, 0, 1)
        if ev == "history":
            P = R.trade_table(data_dir, work, kind, name, sym, tf)
            xs = [P[e][idx, col].astype(np.float64) for e in READ_IDX]
        else:
            bl, bs = R.best_flags(data_dir, name, sym, tf)
            best = np.where(side > 0, bl[idx], bs[idx])
            j = idx - k0
            xs = []
            for r in range(len(READS)):
                xs.append(np.where(best, oc[f"pnl{r}_best"][j, col], oc[f"pnl{r}_normal"][j, col]).astype(np.float64))
                rs = np.where(best, oc[f"reason{r}_best"][j, col], oc[f"reason{r}_normal"][j, col])
                open_end += int((rs == K.R_OPEN).sum())
        keep = np.isfinite(xs[0]) | np.isfinite(xs[1])
        n = int(keep.sum())
        for k, v in (("cell", np.full(n, c, np.int16)), ("coin", np.full(n, ci, np.int8)), ("side", side[keep]),
                     ("close", close[idx][keep].astype(np.int64)), ("x0", xs[0][keep]), ("x1", xs[1][keep])):
            rows[k].append(v)
    T = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in rows.items() if k not in ("regime", "vol")}
    T["regime"], T["vol"] = label_codes(T["close"], coin_state(data_dir, sym, tf))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez(path + ".tmp.npz", open_at_end=open_end, seconds=time.time() - t0, **T)
    os.replace(path + ".tmp.npz", path)
    return f"{ev} {tf} {sym}: {len(T['x0']):,} signals in {time.time() - t0:.0f}s"


def load_table(out: str, ev: str) -> dict:
    """The evaluation's signals of every part, concatenated; fails when a part is missing."""
    parts = []
    for tf in R.TFS:
        for sym in R.SYMBOLS:
            p = part_path(out, ev, tf, sym)
            if not os.path.exists(p):
                raise SystemExit(f"{p} missing: run '{ev}' first")
            with np.load(p) as z:
                parts.append({k: z[k] for k in COLS + ("open_at_end",)})
    T = {k: np.concatenate([p[k] for p in parts]) for k in COLS}
    T["open_at_end"] = int(sum(int(p["open_at_end"]) for p in parts))
    return T


# ------------------------------------------------------------------ forward data and outcomes
def build_forward_data(archive: str, fwd: str, last_day: str) -> None:
    """FWD/1m/<SYMBOL>.npz = the whole full-grid archive (2020-01 .. 2026-09, so every market state has its history)
    plus Binance's daily 1m and mark-price klines 2026-10-01 .. last_day (checksum-verified; as
    research/live_interim/replay/live_bt.py). Funding of the new days is 0: October's file is not in the archive yet."""
    days = [str(d.date()) for d in pd.date_range("2026-10-01", last_day, freq="D")]
    raw = os.path.join(fwd, "raw")
    end = ms(last_day) + DAY
    for sym in R.SYMBOLS:
        out = os.path.join(fwd, "1m", f"{sym}.npz")
        if os.path.exists(out):
            if DATA.load(fwd, sym)["ts"][-1] < end - 3_600_000:
                raise SystemExit(f"{out} ends before {last_day}: remove FWD/1m and run again")
            continue
        base = DATA.load(archive, sym)
        kl, mk = [], []
        for d in days:
            for kind, acc in (("klines", kl), ("markPriceKlines", mk)):
                rel = DATA.rel_daily(kind, sym, d)
                if DATA.fetch(raw, rel) != "ok":
                    raise SystemExit(f"{rel} is not published yet: run again later (PREREG 5.2)")
                acc.append(DATA.read_kline_zip(os.path.join(raw, rel)))
        k = pd.concat(kl).drop_duplicates("t", keep="last").sort_values("t").reset_index(drop=True)
        k = k[k["volume"] > 0].reset_index(drop=True)
        mkd = pd.concat(mk).drop_duplicates("t", keep="last").set_index("t").reindex(k["t"].to_numpy(np.int64))
        no_mark = mkd["open"].isna().to_numpy()
        new = {"ts": k["t"].to_numpy(np.int64), "fund": np.zeros(len(k))}
        for a, b in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
            new[a] = k[b].to_numpy(float)
        for a, b, fall in (("mo", "open", "o"), ("mh", "high", "h"), ("ml", "low", "l"), ("mc", "close", "c")):
            new[a] = np.where(no_mark, new[fall], mkd[b].to_numpy(float))
        if not new["ts"][0] > base["ts"][-1]:
            raise SystemExit(f"{sym}: October overlaps the archive")
        allv = {key: np.concatenate([base[key], new[key]]) for key in base}
        os.makedirs(os.path.dirname(out), exist_ok=True)
        np.savez(out + ".tmp.npz", **allv)
        os.replace(out + ".tmp.npz", out)
        print(f"[forward] {sym}: {len(new['ts']):,} October minutes, mark filled {int(no_mark.sum())}", flush=True)


def forward_outcomes(data_dir: str, work: str, sym: str, tf: str, lo_ms: int, hi_ms: int, ex: dict) -> dict:
    """Each chart bar closing in [lo_ms, hi_ms) as a signal, each side, alone, through the full grid's kernel for the
    two reads and both leverage groups (run.outcomes_job for these bars only): WORK/outcomes/<tf>_<SYMBOL>.npz."""
    path = os.path.join(work, "outcomes", f"{tf}_{sym}.npz")
    if os.path.exists(path):
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    d = R.minute_data(data_dir, sym)
    df, close = R.frame(data_dir, sym, tf)
    atr = R._vendor_fg().atr(df, 14).to_numpy(float)
    w = np.flatnonzero((close >= lo_ms) & (close < hi_ms))
    br, step, mn = ex[sym]
    S = K.settings_vector()
    nan = np.full(len(w), np.nan)
    res = {"bars": w, "close": close[w]}
    for r, e in enumerate(READ_IDX):
        assert K.EXITS[e][0] == READS[r]
        for g, flag in (("best", True), ("normal", False)):
            f = np.full(len(w), flag)
            p, _x, rs, _lv = K.outcomes(S, br, d["ts"], d["o"], d["h"], d["l"], d["mo"], d["mh"], d["ml"], d["fund"],
                                        close[w].astype(np.int64), atr[w], f, f, R.EQUITY, step, mn, *K.exit_args(e),
                                        nan, nan)
            res[f"pnl{r}_{g}"], res[f"reason{r}_{g}"] = p, rs
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez(path + ".tmp.npz", **res)
    os.replace(path + ".tmp.npz", path)
    return res


# ------------------------------------------------------------------ gates and statistics (pure)
def allowed_mask(gate: dict, cls: np.ndarray, regime: np.ndarray, vol: np.ndarray) -> np.ndarray:
    """True where the gate lets the signal through. ``cls``: class index per signal (CLASSES order)."""
    lab, names = (regime, REGIME) if gate["dim"] == "장세" else (vol, VOL)
    out = np.zeros(len(cls), bool)
    for c, states in gate["allow"].items():
        out |= (cls == CLASSES.index(c)) & np.isin(lab, [names.index(s) for s in states])
    return out


def boot_diff_p(block: np.ndarray, x: np.ndarray, allowed: np.ndarray, n_boot: int, seed: int) -> float | None:
    """One-sided block bootstrap p for mean(allowed) - mean(blocked) > 0: whole blocks (weeks or days) resampled; a
    resample without an allowed or a blocked signal counts against."""
    if not allowed.any() or allowed.all():
        return None
    _b, inv = np.unique(block, return_inverse=True)
    W = int(inv.max()) + 1
    a = allowed.astype(float)
    sa, na = np.bincount(inv, x * a, W), np.bincount(inv, a, W)
    sb, nb = np.bincount(inv, x * (1 - a), W), np.bincount(inv, 1 - a, W)
    rng = np.random.default_rng(seed)
    bad, done = 0, 0
    while done < n_boot:
        m = min(500, n_boot - done)
        pick = rng.integers(0, W, size=(m, W))
        with np.errstate(invalid="ignore", divide="ignore"):
            d = sa[pick].sum(1) / na[pick].sum(1) - sb[pick].sum(1) / nb[pick].sum(1)
        bad += int((~(d > 0)).sum())
        done += m
    return (1 + bad) / (n_boot + 1)


def flip_control(cell: np.ndarray, x: np.ndarray, blocked: dict, lines: np.ndarray, n_draws: int,
                 seed: int) -> dict:
    """Coin-flip control: each draw blocks, in every cell, as many signals as the gate blocked there, chosen at random
    (one random order per draw serves every gate). Returns {gate: (n_draws, lines) allowed - blocked mean}.
    ``lines``: (lines, cells) bool, a line = the union of its cells."""
    C = lines.shape[1]
    n_c = np.bincount(cell, minlength=C).astype(float)
    s_c = np.bincount(cell, x, minlength=C)
    start = np.cumsum(n_c) - n_c
    k_c = {g: np.bincount(cell, b.astype(float), minlength=C) for g, b in blocked.items()}
    L = lines.astype(float)
    NA = {g: L @ (n_c - k) for g, k in k_c.items()}
    NB = {g: L @ k for g, k in k_c.items()}
    S = L @ s_c
    out = {g: np.full((n_draws, lines.shape[0]), np.nan) for g in blocked}
    rng = np.random.default_rng(seed)
    cf = cell.astype(np.float64)
    rank = np.empty(len(cell), np.int64)
    for t in range(n_draws):
        order = np.argsort(cf + rng.random(len(cell)), kind="quicksort")     # by cell, random within a cell
        rank[order] = np.arange(len(cell)) - start[cell[order]].astype(np.int64)
        for g, k in k_c.items():
            blk = rank < k[cell]
            SB = L @ np.bincount(cell, x * blk, minlength=C)
            with np.errstate(invalid="ignore", divide="ignore"):
                out[g][t] = (S - SB) / NA[g] - SB / NB[g]
    return out


def line_stats(x, allowed, block, cell_in_line, cell, ds_line, seed, flips, min_n, money) -> dict:
    """One line's numbers and verdict (PREREG 6). ``flips``: this line's control draws."""
    m = cell_in_line[cell]
    xa, xb = x[m & allowed], x[m & ~allowed]
    na, nb = len(xa), len(xb)
    ma = float(xa.mean()) if na else None
    mb = float(xb.mean()) if nb else None
    diff = ma - mb if na and nb else None
    p = boot_diff_p(block[m], x[m], allowed[m], N_BOOT, seed) if na and nb else None
    fl = flips[np.isfinite(flips)]
    cp = float((1 + (fl >= diff).sum()) / (len(fl) + 1)) if diff is not None and len(fl) else None
    checks = {"trades": na >= min_n and nb >= min_n, "diff_positive": diff is not None and diff > 0,
              "boot": p is not None and p < ALPHA, "allowed_positive": ma is not None and ma > 0,
              "control": cp is not None and cp < ALPHA}
    d = {"n_all": int(m.sum()), "n_allowed": na, "n_blocked": nb,
         "share_blocked": nb / (na + nb) if na + nb else None,
         "win_allowed": float((xa > 0).mean()) if na else None, "win_blocked": float((xb > 0).mean()) if nb else None,
         "p": p, "control_p": cp, "checks": checks, "pass": all(checks.values())}
    if money or not ds_line:
        d.update({"mean_all": float(x[m].mean()) if m.any() else None, "mean_allowed": ma, "mean_blocked": mb,
                  "diff": diff, "control_q95": float(np.quantile(fl, 0.95)) if len(fl) else None})
    return d


def evaluate(T: dict, ev: str, cells: tuple, money: bool = DS_MONEY, n_flip: int = N_FLIP) -> dict:
    """Every line of one evaluation (PREREG 6, 7) from its signal table ``T`` (COLS) and the cell list."""
    cls_of = np.array([CLASSES.index(style_class(k, n)) for k, n, _tf in cells], np.int8)
    kind_of = np.array([k for k, _n, _tf in cells])
    tf_of = np.array([tf for _k, _n, tf in cells])
    universe = "all" if ev == "history" else "core"
    if ev == "history":
        block = (T["close"] - R.MONDAY0) // R.WEEK_MS
    else:
        block = T["close"] // DAY
    lines, keys = [], []

    def add(u, grp, tf, role):
        m = np.ones(len(cells), bool)
        if u != "all":
            m &= kind_of == u
        if grp != "pooled":
            m &= cls_of == CLASSES.index(grp)
        if tf != "all":
            m &= tf_of == tf
        if m.any():
            lines.append(m)
            keys.append({"universe": u, "group": grp, "tf": tf, "role": role})
    for grp in GROUPS:
        add(universe, grp, "all", "verdict")
    for tf in R.TFS:
        for grp in GROUPS:
            add(universe, grp, tf, "timeframe")
    if ev == "history":
        for u in ("core", "ds"):
            for grp in GROUPS:
                add(u, grp, "all", "universe")
    L = np.array(lines)
    known = (T["regime"] > 0) & (T["vol"] > 0)
    doc = {"evaluation": ev, "universe": universe, "ds_money": money, "open_at_end": int(T.get("open_at_end", 0)),
           "reads": {}}
    for r, read in enumerate(READS):
        xr = T[f"x{r}"]
        use = np.isfinite(xr) & known
        x, cell, blk = xr[use], T["cell"][use].astype(np.int64), block[use]
        reg, vol = T["regime"][use], T["vol"][use]
        cls = cls_of[cell]
        gates = {**GATES, **SWAPS}
        allow = {g: allowed_mask(spec, cls, reg, vol) for g, spec in gates.items()}
        flips = flip_control(cell, x, {g: ~a for g, a in allow.items() if g in GATES}, L, n_flip,
                             R._seed("regimegate|flip", ev, read))
        out = {"signals": int(np.isfinite(xr).sum()), "unknown_state": int((np.isfinite(xr) & ~known).sum()),
               "used": int(use.sum()), "lines": []}
        for g in gates:
            for li, key in enumerate(keys):
                if g in SWAPS and not (key["role"] == "verdict"):
                    continue
                ds_line = bool((kind_of[L[li]] == "ds").any())
                st = line_stats(x, allow[g], blk, L[li], cell, ds_line,
                                R._seed("regimegate", ev, read, g, key["universe"], key["group"], key["tf"]),
                                flips[g][:, li] if g in flips else np.zeros(0), MIN_N[ev], money)
                if g in SWAPS:
                    st["pass"] = None                                   # descriptive: no verdict
                    st.pop("checks")
                elif key["role"] != "verdict":
                    st["pass"] = None
                out["lines"].append({"gate": g, **key, **st})
        out["states"] = state_table(x, cls, reg, vol, kind_of[cell], ev, money)
        if ev == "history":
            out["years"] = year_table(x, cls, reg, vol, T["close"][use], kind_of[cell], money)
        doc["reads"][read] = out
    return doc


def state_table(x, cls, reg, vol, kind, ev, money) -> dict:
    """Per class and state (장세, 변동성): trades, win rate, mean (hidden where DeepSeek trades are in)."""
    out = {}
    for u in (("all", "core", "ds") if ev == "history" else ("core",)):
        mu = np.ones(len(x), bool) if u == "all" else kind == u
        show = money or u == "core"
        for c, cname in enumerate(CLASSES):
            for dim, lab, names in (("장세", reg, REGIME), ("변동성", vol, VOL)):
                for s in range(1, len(names)):
                    m = mu & (cls == c) & (lab == s)
                    d = {"n": int(m.sum()), "win": float((x[m] > 0).mean()) if m.any() else None}
                    if show:
                        d["mean"] = float(x[m].mean()) if m.any() else None
                    out[f"{u}|{cname}|{dim}|{names[s]}"] = d
    return out


def year_table(x, cls, reg, vol, close, kind, money) -> dict:
    """History, verdict universe, tf all: per UTC year and gate, the sign of allowed - blocked (core: the values)."""
    yr = pd.to_datetime(close, unit="ms", utc=True).year.to_numpy()
    out = {}
    for g, spec in GATES.items():
        a = allowed_mask(spec, cls, reg, vol)
        for y in np.unique(yr):
            for u in ("all", "core"):
                m = (yr == y) & (np.ones(len(x), bool) if u == "all" else kind == "core")
                xa, xb = x[m & a], x[m & ~a]
                if not len(xa) or not len(xb):
                    continue
                d = {"n_allowed": int(len(xa)), "n_blocked": int(len(xb)), "diff_positive": bool(xa.mean() > xb.mean())}
                if money or u == "core":
                    d["diff"] = float(xa.mean() - xb.mean())
                out[f"{g}|{u}|{int(y)}"] = d
    return out


def decide(hist: dict, fwd: dict) -> dict:
    """PREREG 8: a gate (pooled) or a class rule is a candidate filter only when its verdict line passes in history
    and in forward, per read."""
    def verdicts(doc):
        return {(read, ln["gate"], ln["group"]): ln["pass"] for read, rd in doc["reads"].items()
                for ln in rd["lines"] if ln["role"] == "verdict" and ln["gate"] in GATES}
    h, f = verdicts(hist), verdicts(fwd)
    rows = []
    for key in h:
        hp, fp = bool(h[key]), bool(f.get(key))
        word = ("candidate" if hp and fp else "not_confirmed" if hp else "forward_only" if fp else "fail")
        rows.append({"read": key[0], "gate": key[1], "group": key[2], "history": hp, "forward": fp, "result": word})
    return {"rows": rows, "candidates": [r for r in rows if r["result"] == "candidate"]}


# ------------------------------------------------------------------ stages
def run_tables(ev: str, data_dir: str, work: str, out: str, procs: int, lo_ms: int, hi_ms: int, ex) -> None:
    jobs = [(ev, data_dir, work, out, tf, s, lo_ms, hi_ms, ex) for tf in R.TFS for s in R.SYMBOLS]
    jobs.sort(key=lambda j: R.TFS.index(j[4]))
    t0 = time.time()
    for msg in R.run_pool(table_job, jobs, procs, ev, done=lambda j: os.path.exists(part_path(out, ev, j[4], j[5]))):
        if msg:
            print(f"[{ev} {(time.time() - t0) / 60:.0f}m] {msg}", flush=True)


def write_json(path: str, doc: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("history", "forward", "report"))
    ap.add_argument("--data", help="the full-grid 1m archive (research/fullgrid/data.py build)")
    ap.add_argument("--work", help="history: the full grid's work folder (frames/, outcomes/)")
    ap.add_argument("--fwd", help="forward: its own folder (raw/, 1m/, frames/, outcomes/)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--last-day", default=FWD_LAST_DAY)
    ap.add_argument("--exchange", default=os.path.join(FG, "exchange.json"))
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args(argv)
    if a.stage in ("history", "forward"):
        bad = pin_problems()
        if bad:
            print("[regimegate] " + "; ".join(bad), flush=True)
            return 2
    if a.stage == "history":
        R.FRAME_DIR[0] = os.path.join(a.work, "frames")
        run_tables("history", a.data, a.work, a.out, a.procs, HIST_FROM, HIST_TO, None)
        doc = evaluate(load_table(a.out, "history"), "history", all_cells())
        doc.update({"window": [R.PERIODS[R.P_SELECT][1], R.PERIODS[R.P_TEST][2]], "code": code_stamp()})
        write_json(os.path.join(a.out, "history.json"), doc)
    elif a.stage == "forward":
        if a.last_day != FWD_LAST_DAY:
            print(f"[regimegate] --last-day {a.last_day} is not the pre-registered {FWD_LAST_DAY}: a look, not the "
                  "verdict", flush=True)
        build_forward_data(a.data, a.fwd, a.last_day)
        R.FRAME_DIR[0] = os.path.join(a.fwd, "frames")        # never the archive's frames (same file names)
        hi = ms(a.last_day)
        for s in R.SYMBOLS:
            for tf in R.TFS:                                  # built once here; the workers only read them
                if R.frame(a.fwd, s, tf)[1][-1] < hi + DAY - 3_600_000:
                    raise SystemExit(f"{s} {tf}: frames end before {a.last_day}: remove FWD/frames and run again")
        run_tables("forward", a.fwd, a.fwd, a.out, a.procs, FWD_FROM, hi, R.exchange(a.exchange, False))
        doc = evaluate(load_table(a.out, "forward"), "forward", all_cells())
        doc.update({"window": ["2026-10-05 18:35", f"{a.last_day} 00:00"], "data_to": f"{a.last_day} 23:59",
                    "funding": "0 (October not in the archive)", "verdict_window": a.last_day == FWD_LAST_DAY,
                    "code": code_stamp()})
        write_json(os.path.join(a.out, "forward.json"), doc)
    docs = {ev: json.load(open(os.path.join(a.out, f"{ev}.json"), encoding="utf-8"))
            for ev in ("history", "forward") if os.path.exists(os.path.join(a.out, f"{ev}.json"))}
    if "history" in docs and "forward" in docs and docs["forward"].get("verdict_window"):
        docs["decision"] = decide(docs["history"], docs["forward"])
        write_json(os.path.join(a.out, "decision.json"), docs["decision"])
    with open(os.path.join(a.out, "RESULTS_KO.md"), "w", encoding="utf-8") as fh:
        fh.write(report_ko(docs))
    print(f"[regimegate] -> {a.out}/RESULTS_KO.md", flush=True)
    return 0


# ------------------------------------------------------------------ report (Korean)
def _pc(v, d=2) -> str:
    return "-" if v is None else f"{v * 100:+.{d}f}%"


def _p(v) -> str:
    return "-" if v is None else f"{v:.3f}"


def _w(v) -> str:
    return "-" if v is None else f"{v * 100:.0f}%"


GATE_KO = {"G1": "G1 장세 문지기(추세형·그 밖 → 추세장만, 되돌림형 → 횡보장만)",
           "G2": "G2 변동성 문지기(추세형·그 밖 → 출렁이는 장만, 되돌림형 → 조용한 장만)",
           "G1s": "G1 뒤바꿈(추세형 → 횡보장, 되돌림형 → 추세장; 참고)", "G2s": "G2 뒤바꿈(참고)"}
EV_KO = {"history": "과거 5년 9개월 (2021-01 ~ 2026-09, 규칙봇 36 + 딥시크 44)",
         "forward": "실전 기간 (2026-10-05 18:35 UTC ~, 규칙봇 36)"}


def report_ko(docs: dict) -> str:
    L = ["# 장세 문지기 시험 결과", "",
         "규칙은 결과 전에 고정한 `PREREG_REGIMEGATE.md`입니다. 거래당 = 신호 하나를 혼자 $5,000 계좌로 거래했을 때 손익 ÷"
         " $5,000 (수수료·슬리피지·펀딩 포함). 통과 = 막은 신호보다 들인 신호가 낫고(부트스트랩 p < 0.05), 들인 신호 평균이"
         " 플러스이고, 같은 수를 무작위로 막은 1,000번보다 낫고, 양쪽 모두 최소 건수 이상.",
         "딥시크가 섞인 줄은 두 분 규칙(D11)대로 돈 숫자 없이 건수·승률·p·판정만 보입니다.", ""]
    if "decision" in docs:
        L += ["## 최종 판정 (과거와 실전 모두 통과해야 후보)", "", "| 청산 | 문지기 | 묶음 | 과거 | 실전 | 결과 |",
              "|---|---|---|---|---|---|"]
        word = {"candidate": "**후보 필터** (paper만)", "not_confirmed": "확인 안 됨", "forward_only": "한 달만(후보 아님)",
                "fail": "실패"}
        for r in docs["decision"]["rows"]:
            L.append(f"| {READ_KO[r['read']]} | {r['gate']} | {CLASS_KO[r['group']]} | {'통과' if r['history'] else '-'} | "
                     f"{'통과' if r['forward'] else '-'} | {word[r['result']]} |")
        L.append("")
    for ev in ("history", "forward"):
        if ev not in docs:
            continue
        doc = docs[ev]
        L += [f"## {EV_KO[ev]}", ""]
        if ev == "forward":
            L += [f"자료 끝 {doc.get('data_to')}, 펀딩 {doc.get('funding')}, 끝까지 안 끝난 거래 {doc['open_at_end']}건(빠짐)."
                  + ("" if doc.get("verdict_window") else " **미리 정한 기간이 아니라 판정이 아닙니다.**"), ""]
        for read, rd in doc["reads"].items():
            L += [f"### {READ_KO[read]}", "",
                  f"신호 {rd['signals']:,}건 중 장세를 모르는 {rd['unknown_state']:,}건을 빼고 {rd['used']:,}건.", "",
                  "| 문지기 | 묶음 | 들임 | 막음 | 전부(G3) | 들임 평균 | 막음 평균 | 차이 | p | 무작위 p | 판정 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
            for ln in rd["lines"]:
                if ln["role"] != "verdict":
                    continue
                v = "-" if ln["pass"] is None else ("통과" if ln["pass"] else "못 넘음")
                L.append(f"| {ln['gate']} | {CLASS_KO[ln['group']]} | {ln['n_allowed']:,} ({_w(ln['win_allowed'])}) | "
                         f"{ln['n_blocked']:,} ({_w(ln['win_blocked'])}) | {_pc(ln.get('mean_all'))} | "
                         f"{_pc(ln.get('mean_allowed'))} | {_pc(ln.get('mean_blocked'))} | {_pc(ln.get('diff'))} | "
                         f"{_p(ln['p'])} | {_p(ln['control_p'])} | {v} |")
            L += ["", "봉별·묶음별 (참고, 판정 아님):", "",
                  "| 문지기 | 매매법 | 봉 | 묶음 | 들임 | 막음 | 들임 평균 | 차이 | p | 무작위 p |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for ln in rd["lines"]:
                if ln["role"] in ("timeframe", "universe"):
                    who = {"all": "전부", "core": "규칙봇", "ds": "딥시크"}[ln["universe"]]
                    L.append(f"| {ln['gate']} | {who} | {ln['tf'] if ln['tf'] != 'all' else '전부'} | "
                             f"{CLASS_KO[ln['group']]} | {ln['n_allowed']:,} | {ln['n_blocked']:,} | "
                             f"{_pc(ln.get('mean_allowed'))} | {_pc(ln.get('diff'))} | {_p(ln['p'])} | "
                             f"{_p(ln['control_p'])} |")
            L += ["", "묶음 × 장 상황 (참고): 건수, 승률, 거래당", "", "| 매매법 | 묶음 | 기준 | 장 | 건수 | 승률 | 거래당 |",
                  "|---|---|---|---|---|---|---|"]
            for key, d in rd["states"].items():
                u, c, dim, s = key.split("|")
                who = {"all": "전부", "core": "규칙봇", "ds": "딥시크"}[u]
                L.append(f"| {who} | {CLASS_KO[c]} | {dim} | {s} | {d['n']:,} | {_w(d['win'])} | {_pc(d.get('mean'))} |")
            if rd.get("years"):
                L += ["", "해마다 들임 − 막음 (참고)", "", "| 문지기 | 매매법 | 해 | 들임 | 막음 | 들임이 나음 | 차이 |",
                      "|---|---|---|---|---|---|---|"]
                for key, d in rd["years"].items():
                    g, u, y = key.split("|")
                    L.append(f"| {g} | {'전부' if u == 'all' else '규칙봇'} | {y} | {d['n_allowed']:,} | "
                             f"{d['n_blocked']:,} | {'예' if d['diff_positive'] else '아니오'} | {_pc(d.get('diff'))} |")
            L.append("")
        L += [f"문지기 설명: {'; '.join(GATE_KO.values())}.", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
