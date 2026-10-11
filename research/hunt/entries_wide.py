"""Trend hunt WIDE (research/hunt/PREREG_HUNT_WIDE.md, W2-W4): the entry EVENTS of every coded entry, ready for the
hunt machine (PREREG_HUNT sections 6-10). Signals only: nothing here sizes, fills, exits or scores a trade.

    from research.hunt import entries_wide as EW
    bars = EW.build_bars(ts, o, h, l, c, v, "1h", qv=qv)        # UTC bins of one coin's 5m bars (PREREG_HUNT 4)
    btc = EW.build_bars(*btc_arrays, "1h")                     # BTC on the same timeframe (F3 F14_SMT context)
    for spec in EW.systems():                                  # the system list (W4), stable ids
        ev = EW.events_on(spec, bars, "ETHUSDT", btc)          # {"long", "short", "raw_long", "raw_short"}
    ok = EW.gate_ok(bars, spec["gate"])                        # G1: the bar's 장세 label is 추세장; NONE: every bar

Families (W2; each long and short; the strategies' own exits / take-profits / stops are not used here):
  F1  E1 Donchian 55 + volume, E2 Bollinger squeeze release, E3 ATR expansion: PREREG_HUNT section 5, main number
      (``hunt_raw``; volume = the 5m bars' QUOTE volume, PREREG_HUNT 2).
  F2  the full grid's 36 core strategies (research/fullgrid/run.core_names()) at run.default_combo.
  F3  the 44 DeepSeek definitions (research/fullgrid/ds_defs.py via run.ds_module()) at default values, on the
      timeframes the full grid defines them on (ds_defs.TFS_OF: the five F15 session definitions have no 4h).
  F4  the 38 watch picks (research/fullgrid/diag/watch_sel.json; the candidate league's candleague/data/
      candidates.json carries the same 38 combos), their own numbers, their own timeframe.
  F2-F4 call exactly what research/fullgrid/run.signals calls: core_module(name).signals(df, tf, **combo) and
  ds_module().signals(df, tf, name, ctx, coin, cache, **combo) with coin = symbol minus its last letter and
  ctx = {"BTCUSD": BTC frame of the same timeframe} for every coin but BTCUSDT. The frame is the full grid's
  (columns ts open high low close volume, attrs["tf"]), built from the 5m bars, volume = BASE volume (the full grid's
  1m archive column ``v``), so every number the definitions compare means what it meant in the full grid.

Event rule (one rule for every family): the long (short) event of bar t = the side's signal array is True on bar t
and False on bar t-1 (the previous bar of the array; bar 0: previous = False). For an array that marks single bars
(a cross, a breakout) this is the array itself; for a state array (true for as long as a condition holds) it is the
first bar where the state turns on; a run of consecutive True bars gives one event, at its first bar. This is
PREREG_HUNT section 5's own definition ("true on bar t and false on bar t-1"), so F1 and F2-F4 follow one rule.
``events_on`` returns the raw arrays too (``raw_long`` / ``raw_short``); ``ARRAY_KIND`` documents which strategies'
arrays are single-bar events and which are states (``classify`` measures it on synthetic bars; tests check it).

Timing: a signal / event on bar t is known at the bar's close, close_ms[t] = open_ms[t] + the timeframe (the UTC
bin's scheduled end, also when the bin has missing 5m bars). bars.first5[t] = index of the first 5m bar with open
>= close_ms[t] (the hunt machine's fill bar, PREREG_HUNT 7.1); len(ts) when there is none.

Bars (PREREG_HUNT 4 and the full grid's run.build_frame): UTC bins of the 5m bars (4h at 00, 04, .. 20 UTC); open =
first 5m open, high / low = extremes, close = last 5m close, volume = sum; a bin without a 5m bar is no bar; a bin with
missing 5m bars inside is kept (partial); the first bin is dropped when the data starts after its open and the last
bin when the data ends before its last 5m slot (a bin is never used before it is complete: no look-ahead).

Systems (W4): (entry, timeframe, gate) for F1-F3 on 15m / 30m / 1h / 4h (F3 where defined) and F4 on its own
timeframe, gates G1 and NONE: (3 + 36) x 4 x 2 + (39 x 4 + 5 x 3) x 2 + 38 x 2 = 312 + 342 + 76 = 730 systems
(the design's "740" counted 44 x 4 DeepSeek cells; ds_defs raises on F15_* 4h, so those 5 x 2 systems do not exist).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
FULLGRID = os.path.join(ROOT, "research", "fullgrid")
WATCH_SEL = os.path.join(FULLGRID, "diag", "watch_sel.json")
LEAGUE_CANDIDATES = os.path.join(ROOT, "candleague", "data", "candidates.json")

TFS = ("15m", "30m", "1h", "4h")
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
FIVE_MS = 300_000
FAMILIES = ("F1", "F2", "F3", "F4")
GATES = ("G1", "NONE")
HUNT_NAMES = ("E1", "E2", "E3")
HUNT_MAIN = {"E1": {"channel": 55}, "E2": {"window": 120}, "E3": {"threshold": 1.5}}
E1_VOL_LEN, E1_VOL_MULT = 20, 2.0
E2_BB_LEN, E2_BB_K, E2_PCT = 20, 2.0, 20.0
E3_FAST, E3_SLOW, E3_SIDE_LEN = 14, 100, 20
N_SYSTEMS = 730


# ------------------------------------------------------------------ the full grid's code, read-only
def fullgrid_run():
    """research/fullgrid/run.py, loaded by path under the name its own tests use (one module object per process)."""
    mod = sys.modules.get("fullgrid_run")
    if mod is None:
        spec = importlib.util.spec_from_file_location("fullgrid_run", os.path.join(FULLGRID, "run.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["fullgrid_run"] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop("fullgrid_run", None)
            raise
    return mod


def _regime5y():
    from paperbot.dash.tools import regime5y
    return regime5y


# ------------------------------------------------------------------ bars
class Bars:
    """One coin's bars on one timeframe, built from its 5m bars. Arrays per bar: open_ms, close_ms, o, h, l, c, v (base
    volume), qv (quote volume; NaN when not given), n5 (5m bars in the bin), first5 (index of the first 5m bar with
    open >= close_ms, the fill bar)."""

    def __init__(self, tf, open_ms, o, h, l, c, v, qv, n5, first5, n_five):
        self.tf = tf
        self.open_ms = open_ms
        self.close_ms = open_ms + TF_MS[tf]
        self.o, self.h, self.l, self.c, self.v, self.qv = o, h, l, c, v, qv
        self.n5, self.first5, self.n_five = n5, first5, n_five
        self._df = None

    def __len__(self) -> int:
        return len(self.open_ms)

    @property
    def df(self) -> pd.DataFrame:
        """The full grid's frame (run.build_frame's columns and dtypes; volume = base volume). Callers get a copy: a
        definition that edits its frame cannot change the next one's."""
        if self._df is None:
            df = pd.DataFrame({"ts": pd.to_datetime(self.open_ms, unit="ms", utc=True), "open": self.o,
                               "high": self.h, "low": self.l, "close": self.c, "volume": self.v})
            df.attrs["tf"] = self.tf
            self._df = df
        d = self._df.copy()
        d.attrs["tf"] = self.tf
        return d


def build_bars(ts, o, h, l, c, v, tf: str, qv=None) -> Bars:
    """UTC bins of one coin's 5m bars (open times ``ts`` in ms, strictly increasing, on the 5m grid)."""
    if tf not in TF_MS:
        raise ValueError(f"timeframe {tf!r} not in {TFS}")
    ts = np.asarray(ts, np.int64)
    if len(ts) and (np.any(np.diff(ts) <= 0) or np.any(ts % FIVE_MS)):
        raise ValueError("5m open times must be strictly increasing multiples of 5 minutes")
    arr = [np.asarray(x, np.float64) for x in (o, h, l, c, v)]
    q = np.full(len(ts), np.nan) if qv is None else np.asarray(qv, np.float64)
    if any(len(x) != len(ts) for x in arr + [q]):
        raise ValueError("5m arrays differ in length")
    step = TF_MS[tf]
    if not len(ts):
        e = np.zeros(0)
        return Bars(tf, np.zeros(0, np.int64), e, e, e, e, e, e, np.zeros(0, np.int64), np.zeros(0, np.int64), 0)
    b = ts // step
    cut = np.flatnonzero(np.diff(b)) + 1
    st = np.r_[0, cut]
    en = np.r_[cut, len(ts)]
    O = arr[0][st]
    H = np.maximum.reduceat(arr[1], st)
    L = np.minimum.reduceat(arr[2], st)
    C = arr[3][en - 1]
    V = np.add.reduceat(arr[4], st)
    QV = np.add.reduceat(q, st)
    open_ms = b[st] * step
    keep = np.ones(len(st), bool)
    if ts[0] > open_ms[0]:
        keep[0] = False
    if ts[-1] < open_ms[-1] + step - FIVE_MS:
        keep[-1] = False
    open_ms = open_ms[keep]
    first5 = np.searchsorted(ts, open_ms + step, side="left").astype(np.int64)
    return Bars(tf, open_ms, O[keep], H[keep], L[keep], C[keep], V[keep], QV[keep], (en - st)[keep].astype(np.int64),
                first5, len(ts))


def resample_1m_to_5m(ts, o, h, l, c, v):
    """5m bars from 1m bars (UTC bins; the W8 parity check builds the adapter's input this way). Every 5m bin with at
    least one minute is a bar (the archive's 5m klines also exist for partial intervals)."""
    ts = np.asarray(ts, np.int64)
    b = ts // FIVE_MS
    cut = np.flatnonzero(np.diff(b)) + 1
    st = np.r_[0, cut]
    en = np.r_[cut, len(ts)]
    return (b[st] * FIVE_MS, np.asarray(o, float)[st], np.maximum.reduceat(np.asarray(h, float), st),
            np.minimum.reduceat(np.asarray(l, float), st), np.asarray(c, float)[en - 1],
            np.add.reduceat(np.asarray(v, float), st))


# ------------------------------------------------------------------ events
def rising(x) -> np.ndarray:
    """x[t] and not x[t-1] (bar 0: not x[-1] = True)."""
    x = np.asarray(x, bool)
    out = x.copy()
    out[1:] &= ~x[:-1]
    return out


def _prev(x: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[:-k]
    return out


def _roll_prev(x: np.ndarray, n: int, fn) -> np.ndarray:
    """fn over the n values x[t-n .. t-1] (NaN where fewer than n earlier bars), exact (no running sums)."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) > n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)[:-1]       # row j = x[j .. j+n-1] -> value at t = j + n
        for a in range(0, len(w), 50_000):
            out[n + a:n + a + len(w[a:a + 50_000])] = fn(w[a:a + 50_000])
    return out


def _roll_now(x: np.ndarray, n: int, fn) -> np.ndarray:
    """fn over x[t-n+1 .. t] (NaN for the first n - 1 bars), exact."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)
        for a in range(0, len(w), 50_000):
            out[n - 1 + a:n - 1 + a + len(w[a:a + 50_000])] = fn(w[a:a + 50_000])
    return out


def wilder_atr(h, l, c, n: int) -> np.ndarray:
    """ATR by Wilder (paperbot/dash/tools/regime5y.adx_atr, the method PREREG_HUNT 4 names)."""
    return _regime5y().adx_atr(h, l, c, n)[1]


def _event_pair(cond_l: np.ndarray, cond_s: np.ndarray, defined: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """PREREG_HUNT 5: the condition is true on bar t and was false on bar t-1, both bars with every value defined."""
    d_prev = np.r_[False, defined[:-1]]
    lg = cond_l & defined & d_prev & ~np.r_[False, cond_l[:-1]]
    sh = cond_s & defined & d_prev & ~np.r_[False, cond_s[:-1]]
    return lg, sh


def hunt_raw(name: str, bars: Bars, value=None) -> tuple[np.ndarray, np.ndarray]:
    """F1 events (PREREG_HUNT section 5) on ``bars``; ``value`` = the main number (channel / window / threshold;
    the default is the main value, the v1 neighbours pass theirs). Already events (true on t, false on t-1)."""
    h, l, c, qv = bars.h, bars.l, bars.c, bars.qv
    with np.errstate(invalid="ignore", divide="ignore"):
        if name == "E1":
            n = int(HUNT_MAIN["E1"]["channel"] if value is None else value)
            hh = _roll_prev(h, n, lambda w: w.max(1))
            ll = _roll_prev(l, n, lambda w: w.min(1))
            vm = _roll_prev(qv, E1_VOL_LEN, lambda w: w.mean(1))
            vol_ok = qv >= E1_VOL_MULT * vm
            defined = np.isfinite(hh) & np.isfinite(ll) & np.isfinite(vm) & np.isfinite(qv) & np.isfinite(c)
            return _event_pair((c > hh) & vol_ok, (c < ll) & vol_ok, defined)
        if name == "E2":
            win = int(HUNT_MAIN["E2"]["window"] if value is None else value)
            mid = _roll_now(c, E2_BB_LEN, lambda w: w.mean(1))
            sd = _roll_now(c, E2_BB_LEN, lambda w: w.std(1))                 # population (ddof 0)
            up, lo = mid + E2_BB_K * sd, mid - E2_BB_K * sd
            bw = (up - lo) / mid
            pct = _roll_prev(bw, win, lambda w: np.percentile(w, E2_PCT, axis=1))   # over bw[t-win .. t-1], linear
            squeeze = _prev(bw) <= pct
            cl = (c > up) & (_prev(c) <= _prev(up))
            cs = (c < lo) & (_prev(c) >= _prev(lo))
            defined = np.isfinite(pct) & np.isfinite(_prev(bw)) & np.isfinite(up) & np.isfinite(_prev(up))
            return _event_pair(squeeze & cl, squeeze & cs, defined)
        if name == "E3":
            thr = float(HUNT_MAIN["E3"]["threshold"] if value is None else value)
            ratio = wilder_atr(h, l, c, E3_FAST) / wilder_atr(h, l, c, E3_SLOW)
            cross = (ratio >= thr) & (_prev(ratio) < thr)
            mom = c - _prev(c, E3_SIDE_LEN)
            defined = np.isfinite(ratio) & np.isfinite(_prev(ratio)) & np.isfinite(mom)
            return _event_pair(cross & (mom > 0), cross & (mom < 0), defined)
    raise ValueError(f"unknown hunt entry {name!r}")


def coin_of(sym: str) -> str:
    """The full grid's DeepSeek coin name: the symbol minus its last letter (BTCUSDT -> BTCUSD)."""
    return sym[:-1]


def grid_raw(kind: str, name: str, bars: Bars, sym: str, combo: dict, btc: Bars | None = None,
             cache: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """F2-F4 signal arrays, exactly as research/fullgrid/run.signals computes them on a frame (kind 'core' / 'ds')."""
    R = fullgrid_run()
    R.M.clear()                                   # the indicator memo is per series in the full grid too
    df = bars.df
    if kind == "core":
        lo, sh = R.core_module(name).signals(df, bars.tf, **combo)
    elif kind == "ds":
        if sym == "BTCUSDT":
            ctx = None
        else:
            if btc is None:
                raise ValueError(f"{name} on {sym}: the DeepSeek definitions take BTC bars of the same timeframe")
            if btc.tf != bars.tf:
                raise ValueError("BTC bars on another timeframe")
            ctx = {"BTCUSD": btc.df}
        lo, sh = R.ds_module().signals(df, bars.tf, name, ctx=ctx, coin=coin_of(sym),
                                       cache={} if cache is None else cache, **combo)
    else:
        raise ValueError(f"kind {kind!r}")
    lo, sh = np.asarray(lo, bool), np.asarray(sh, bool)
    if lo.shape != (len(bars),) or sh.shape != (len(bars),):
        raise ValueError(f"{name}: signal arrays of the wrong length")
    return lo, sh


def events_on(spec: dict, bars: Bars, sym: str, btc: Bars | None = None) -> dict:
    """{"long", "short"}: the system's entry events per bar of ``bars`` (ungated; ``gate_ok`` gives the gate), and
    {"raw_long", "raw_short"}: the signal arrays the events come from."""
    if bars.tf != spec["tf"]:
        raise ValueError(f"system {spec['id']} is on {spec['tf']}, the bars are {bars.tf}")
    if spec["kind"] == "hunt":
        lg, sh = hunt_raw(spec["name"], bars, next(iter(spec["combo"].values())) if spec["combo"] else None)
    else:
        lg, sh = grid_raw(spec["kind"], spec["name"], bars, sym, _combo_args(spec["combo"]), btc)
    return {"long": rising(lg), "short": rising(sh), "raw_long": lg, "raw_short": sh}


def events(spec: dict, five: dict, sym: str, btc_five: dict | None = None) -> tuple[Bars, dict]:
    """``events_on`` from 5m arrays ({ts, o, h, l, c, v[, qv]}); returns (bars, events)."""
    bars = build_bars(five["ts"], five["o"], five["h"], five["l"], five["c"], five["v"], spec["tf"], five.get("qv"))
    btc = None
    if btc_five is not None and spec["kind"] == "ds" and sym != "BTCUSDT":
        btc = build_bars(btc_five["ts"], btc_five["o"], btc_five["h"], btc_five["l"], btc_five["c"], btc_five["v"],
                         spec["tf"], btc_five.get("qv"))
    return bars, events_on(spec, bars, sym, btc)


def _combo_args(combo: dict) -> dict:
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in combo.items()}


# ------------------------------------------------------------------ gate, ATR
TREND = 1


def regime_code(bars: Bars) -> np.ndarray:
    """PREREG_HUNT 6: regime5y.regimes(high, low, close, TF_MIN[tf])["code"] on the coin's own bars (1 = 추세장)."""
    Y = _regime5y()
    return Y.regimes(bars.h, bars.l, bars.c, Y.TF_MIN[bars.tf])["code"]


def gate_ok(bars: Bars, gate: str, code: np.ndarray | None = None) -> np.ndarray:
    """Bars where an event passes the gate: G1 = the bar's label is 추세장 (TREND); NONE = every bar."""
    if gate == "NONE":
        return np.ones(len(bars), bool)
    if gate == "G1":
        Y = _regime5y()
        assert Y.TREND == TREND
        return (regime_code(bars) if code is None else code) == TREND
    raise ValueError(f"gate {gate!r}")


def atr14(bars: Bars) -> np.ndarray:
    """ATR14 (Wilder) of the signal timeframe: D0 = 2 x ATR14 (15m / 30m / 1h) or 1.5 x (4h); chandelier 3 x."""
    return wilder_atr(bars.h, bars.l, bars.c, 14)


# ------------------------------------------------------------------ systems
def watch_picks(path: str = WATCH_SEL) -> list[dict]:
    """The 38 watch picks: {kind, name, tf, rank, combo, cand_id} in the file's order (their exits are not used).
    Every pick's parameters must be exactly its strategy's parameters."""
    R = fullgrid_run()
    with open(path) as fh:
        rows = json.load(fh)
    out = []
    for r in rows:
        combo = json.loads(r["combo"]) if isinstance(r["combo"], str) else dict(r["combo"])
        names = [p["name"] for p in R.params_of(r["kind"], r["name"])]
        if sorted(combo) != sorted(names):
            raise ValueError(f"watch pick {r['kind']}-{r['name']}-{r['tf']}: parameters {sorted(combo)} != {names}")
        if r["tf"] not in TFS:
            raise ValueError(f"watch pick timeframe {r['tf']!r}")
        out.append({"kind": r["kind"], "name": r["name"], "tf": r["tf"], "rank": int(r["rank"]),
                    "combo": {k: combo[k] for k in names},
                    "cand_id": f"{r['kind']}-{r['name']}-{r['tf']}-{int(r['rank'])}"})
    return out


def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def _spec(family: str, name: str, kind: str, tf: str, gate: str, combo: dict, rank: int | None = None,
          cand_id: str | None = None) -> dict:
    sid = f"{family}-{name}-{tf}" + (f"-r{rank}" if rank is not None else "") + f"-{gate}"
    combo = {k: (list(v) if isinstance(v, tuple) else v) for k, v in combo.items()}
    core = {"family": family, "name": name, "kind": kind, "tf": tf, "gate": gate, "combo": combo}
    d = {"id": sid, "strategy": name, **core, "spec_sha": hashlib.sha256(_canon(core).encode()).hexdigest()[:16]}
    if rank is not None:
        d["rank"], d["cand_id"] = rank, cand_id
    return d


def systems() -> list[dict]:
    """Every WIDE system (W4) in a fixed order: family F1..F4; F1 E1, E2, E3; F2 run.core_names() (sorted); F3
    ds_defs.DEFS order; F4 watch_sel.json order; timeframes 15m, 30m, 1h, 4h; gates G1, NONE. ``id`` is stable
    (family-name-tf[-r<rank>]-gate) and ``spec_sha`` hashes everything that decides the events."""
    R = fullgrid_run()
    D = R.ds_module()
    out = []
    for name in HUNT_NAMES:
        for tf in TFS:
            for g in GATES:
                out.append(_spec("F1", name, "hunt", tf, g, HUNT_MAIN[name]))
    for name in R.core_names():
        combo = R.default_combo("core", name)
        for tf in TFS:
            for g in GATES:
                out.append(_spec("F2", name, "core", tf, g, combo))
    for name in D.DEFS:
        combo = R.default_combo("ds", name)
        for tf in TFS:
            if tf not in D.TFS_OF[name]:
                continue
            for g in GATES:
                out.append(_spec("F3", name, "ds", tf, g, combo))
    for p in watch_picks():
        for g in GATES:
            out.append(_spec("F4", p["name"], p["kind"], p["tf"], g, p["combo"], p["rank"], p["cand_id"]))
    ids = [s["id"] for s in out]
    if len(set(ids)) != len(ids):
        raise RuntimeError("system ids are not unique")
    return out


def entry_cells() -> list[dict]:
    """The distinct (entry, timeframe) of the systems (the gate does not change the events): one signal computation
    each per coin."""
    seen, out = set(), []
    for s in systems():
        key = (s["family"], s["name"], s["tf"], _canon(s["combo"]))
        if key not in seen:
            seen.add(key)
            out.append({k: s[k] for k in ("family", "name", "kind", "tf", "combo")} | {"rank": s.get("rank")})
    return out


# ------------------------------------------------------------------ event vs state (documentation)
def classify(lg: np.ndarray, sh: np.ndarray) -> dict:
    """How much of a raw signal array is continuation: True bars whose previous bar was True on the same side.
    'event' when none are (events == raw), 'state' when at least half are, else 'mixed' (events drop the
    continuation bars)."""
    n_true = int(lg.sum() + sh.sum())
    cont = int((lg[1:] & lg[:-1]).sum() + (sh[1:] & sh[:-1]).sum())
    share = cont / n_true if n_true else 0.0
    kind = "event" if cont == 0 else ("state" if share >= 0.5 else "mixed")
    return {"true_bars": n_true, "continuation": cont, "share": share, "kind": kind}
