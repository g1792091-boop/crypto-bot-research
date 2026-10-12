"""exitflex data side (research/exitflex/PREREG_EXITFLEX.md sections 2, 3, 13).

* the pin (``data_pin.json``): the sha256 of ``fg1m/build.json`` and of each coin file; ``verify_data`` refuses any other file;
* the select cut: the 1m arrays cut at 2024-01-01 00:00 UTC (minutes that open before it) written as their own data folder
  ``$WORK/<pin8>/cut-<cut time>/1m/<SYM>.npz`` (``cut.json`` holds the pin hash, the cut and a digest of every array), so
  that every ``run.py`` cache keyed by the data folder sees a different key for cut and full data;
* stage cache folders ``$WORK/<pin8>/<stage>/`` (deleted when a stage starts, ``run.FRAME_DIR`` points into them);
* the 23 picks, their chart bars, signals, leverage groups and the offered signals of a period (prereg 3);
* the chart arrays the kernel reads for each variant (swings, EMA, starting references, 15m bars of q15 variants);
* ``snapshot`` for test T3 (the last 50 chart bars before a cut, compared between cut and full data, the market-state codes included);
* the market state of each signal bar (prereg 7): ``regime_codes`` runs ``paperbot/dash/tools/regime5y.py`` (loaded by path, its
  thresholds asserted equal to the pre-registered values) on the pick's own chart bars of each coin; ``PickData.offered`` carries the
  code of every offered signal's bar in the column ``state`` (int8: 모름 0, 추세장 1, 횡보장 2, 급변장 3, 보통 4).

Nothing here prints or saves a performance figure. Loading is ``research/fullgrid/data.py`` ``load`` through
``research/fullgrid/run.py`` unchanged.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sys

import numpy as np
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FG = os.path.join(ROOT, "research", "fullgrid")
for _p in (HERE, ROOT, FG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kernel_x as KX  # noqa: E402

K = KX.K
MIN = 60_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
TFS = ("15m", "30m", "1h", "4h")
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
PIN_PATH = os.path.join(HERE, "data_pin.json")
WATCH_SEL = os.path.join(FG, "diag", "watch_sel.json")
CANDIDATES = os.path.join(ROOT, "candleague", "data", "candidates.json")
EXCHANGE = os.path.join(FG, "exchange.json")


def _ms(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


# Periods are set by the signal bar's close (UTC): select [2021-01-01, 2024-01-01), confirm [2024-01-01, 2026-10-01)
PERIOD_MS = {"select": (_ms("2021-01-01"), _ms("2024-01-01")), "confirm": (_ms("2024-01-01"), _ms("2026-10-01"))}
SELECT_CUT_MS = PERIOD_MS["select"][1]
WARMUP_BARS = 300
EQUITY = 5000.0


class PinError(RuntimeError):
    pass


# ------------------------------------------------------------------ market state at the signal bar (prereg 7)
REGIME_PATH = os.path.join(ROOT, "paperbot", "dash", "tools", "regime5y.py")
REGIMES_DEF_PATH = os.path.join(FG, "regimes.py")        # pinned as the definition of the labels; never imported
ST_UNKNOWN, ST_TREND, ST_RANGE, ST_SHOCK, ST_NORMAL = 0, 1, 2, 3, 4
STATE_KO = {ST_TREND: "추세장", ST_RANGE: "횡보장", ST_SHOCK: "급변장", ST_NORMAL: "보통", ST_UNKNOWN: "모름"}
STATE_ORDER = (ST_TREND, ST_RANGE, ST_SHOCK, ST_NORMAL, ST_UNKNOWN)
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
_REGIME_MOD = None


def regime_module():
    """paperbot/dash/tools/regime5y.py loaded by path (the label code of the dashboard's 장세 switch), with its thresholds
    asserted equal to the values of prereg section 7 at load."""
    global _REGIME_MOD
    if _REGIME_MOD is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("regime5y_x", REGIME_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        want = dict(ADX_N=14, EMA_N=50, SLOPE_BARS=10, ADX_TREND=25.0, ADX_RANGE=20.0, SLOPE_MIN=0.5, VOL_Q=0.80, VOL_DAYS=365,
                    VOL_MIN_DAYS=180, UNKNOWN=0, TREND=1, RANGE=2, SHOCK=3, NORMAL=4)
        for k, v in want.items():
            if getattr(mod, k) != v:
                raise AssertionError(f"regime5y.{k} = {getattr(mod, k)!r}, prereg 7 says {v!r}")
        _REGIME_MOD = mod
    return _REGIME_MOD


_STATE_CACHE: dict = {}


def regime_arrays(sym: str, tf: str, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    """``regime5y.regimes(high, low, close, TF_MIN[tf])`` of every chart bar of one coin and timeframe, each value from bars 0..t only:
    {code (int8, ST_*), adx, slope, atrp, vol_q}. Cached in this process by the arrays' identity."""
    key = (sym, tf, len(close), float(close[-1]) if len(close) else 0.0, float(np.sum(close)), float(np.sum(high)), float(np.sum(low)))
    if key not in _STATE_CACHE:
        if len(_STATE_CACHE) > 64:
            _STATE_CACHE.clear()
        r = regime_module().regimes(np.asarray(high, float), np.asarray(low, float), np.asarray(close, float), TF_MIN[tf])
        _STATE_CACHE[key] = {"code": np.ascontiguousarray(r["code"], np.int8),
                             **{k: np.ascontiguousarray(r[k], float) for k in ("adx", "slope", "atrp", "vol_q")}}
    return _STATE_CACHE[key]


def regime_codes(sym: str, tf: str, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """The 장세 code (int8, ST_*) of every chart bar of one coin and timeframe, from bars 0..t only
    (``regime5y.regimes(high, low, close, TF_MIN[tf])["code"]``). Cached in this process by the arrays' identity."""
    return regime_arrays(sym, tf, high, low, close)["code"]


# ------------------------------------------------------------------ hashes and the pin
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def array_digest(arrays: dict) -> str:
    """sha256 over the arrays' names, dtypes, shapes and bytes in sorted name order (file bytes of an npz carry
    timestamps, so the digest is taken over the content)."""
    h = hashlib.sha256()
    for k in sorted(arrays):
        a = np.ascontiguousarray(arrays[k])
        h.update(f"{k}|{a.dtype.str}|{a.shape}".encode())
        h.update(a.view(np.uint8).reshape(-1) if a.size else b"")
    return h.hexdigest()


def pin8(pin_sha: str) -> str:
    return pin_sha[:8]


def pin_sha(path: str | None = None) -> str:
    """The pin hash: sha256 of the bytes of data_pin.json."""
    path = path or PIN_PATH
    if not os.path.exists(path):
        raise PinError(f"pin file missing: {path}")
    return sha256_file(path)


def load_pin(path: str | None = None) -> dict:
    path = path or PIN_PATH
    if not os.path.exists(path):
        raise PinError(f"pin file missing: {path}")
    with open(path) as fh:
        doc = json.load(fh)
    for k in ("data_dir", "work", "build_json_sha256", "coins"):
        if k not in doc:
            raise PinError(f"pin file lacks {k}")
    return doc


def make_pin(data_dir: str, work: str, symbols=SYMBOLS) -> dict:
    """The content of data_pin.json for a local copy of the study's 1m arrays: the sha256 of build.json and of each coin
    file (read from the files; compare them with the values the pre-registration names before pinning)."""
    return {"version": 1, "data_dir": os.path.abspath(data_dir), "work": os.path.abspath(work),
            "build_json_sha256": sha256_file(os.path.join(data_dir, "build.json")),
            "coins": {s: sha256_file(os.path.join(data_dir, "1m", f"{s}.npz")) for s in symbols}}


def verify_data(pin: dict, data_dir: str | None = None) -> None:
    """Refuse any file other than the pinned ones (build.json and every coin file)."""
    d = data_dir or pin["data_dir"]
    got = sha256_file(os.path.join(d, "build.json"))
    if got != pin["build_json_sha256"]:
        raise PinError("build.json does not match the pin")
    for s, want in pin["coins"].items():
        if sha256_file(os.path.join(d, "1m", f"{s}.npz")) != want:
            raise PinError(f"{s}.npz does not match the pin")


# ------------------------------------------------------------------ cut data folder, stage folders
CUT_PREFIX = "cut"            # the select run's own cut folder; test T3 uses "t3cut" so that it never touches it


def cut_name(cut_ms: int, prefix: str = CUT_PREFIX) -> str:
    return prefix + "-" + dt.datetime.fromtimestamp(cut_ms / 1000, dt.timezone.utc).strftime("%Y%m%d%H%M")


def cut_dir(work: str, pin_hash: str, cut_ms: int, prefix: str = CUT_PREFIX) -> str:
    return os.path.join(work, pin8(pin_hash), cut_name(cut_ms, prefix))


def stage_dir(work: str, pin_hash: str, stage: str) -> str:
    return os.path.join(work, pin8(pin_hash), stage)


def fresh_stage(work: str, pin_hash: str, stage: str) -> str:
    """A stage deletes its own cache folder before it starts (prereg 13)."""
    d = stage_dir(work, pin_hash, stage)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def _load_npz(path: str) -> dict:
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def write_cut(src_dir: str, work: str, pin_hash: str, cut_ms: int, symbols=SYMBOLS, min_free_mb: int = 250,
              prefix: str = CUT_PREFIX) -> str:
    """Write the arrays of ``src_dir`` cut at ``cut_ms`` (minutes that open before it) as their own data folder and return
    it. An existing folder with the same pin, cut and digests is reused. The arrays are stored compressed (disk is tight).
    Fails before writing when less than the expected size plus ``min_free_mb`` is free. This is the only function that reads the
    full arrays for a cut; the select process never calls it (it calls ``open_cut``; the folder is made by the separate
    ``make-cut`` step, audit A5)."""
    out = cut_dir(work, pin_hash, cut_ms, prefix)
    meta_path = os.path.join(out, "cut.json")
    if os.path.exists(meta_path):
        meta = json.load(open(meta_path))
        if meta.get("pin") == pin_hash and meta.get("cut_ms") == cut_ms and sorted(meta["coins"]) == sorted(symbols):
            if verify_cut(out, symbols):
                return out
        shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(out, "1m"), exist_ok=True)
    os.makedirs(work, exist_ok=True)
    free = shutil.disk_usage(work).free
    est = sum(os.path.getsize(os.path.join(src_dir, "1m", f"{s}.npz")) for s in symbols) * 0.45
    if free < est + min_free_mb * 1_000_000:
        shutil.rmtree(out, ignore_errors=True)
        raise OSError(f"not enough disk for the cut data: {free / 1e6:.0f} MB free, about {est / 1e6:.0f} MB needed")
    coins = {}
    for s in symbols:
        d = _load_npz(os.path.join(src_dir, "1m", f"{s}.npz"))
        n = int(np.searchsorted(d["ts"], cut_ms, side="left"))
        c = {k: np.ascontiguousarray(v[:n]) for k, v in d.items()}
        del d
        tmp = os.path.join(out, "1m", f"{s}.tmp.npz")
        np.savez_compressed(tmp, **c)
        os.replace(tmp, os.path.join(out, "1m", f"{s}.npz"))
        coins[s] = {"minutes": n, "digest": array_digest(c)}
        del c
    with open(meta_path + ".tmp", "w") as fh:
        json.dump({"pin": pin_hash, "cut_ms": int(cut_ms), "coins": coins}, fh, indent=1)
    os.replace(meta_path + ".tmp", meta_path)
    return out


class CutMissing(PinError):
    """The cut folder does not exist (or is not the one of this pin and cut): run the ``make-cut`` step first."""


def open_cut(work: str, pin_hash: str, cut_ms: int, symbols=SYMBOLS, prefix: str = CUT_PREFIX) -> str:
    """The existing cut folder of this pin and cut time, verified (digests; no minute at or after the cut). It reads only the cut
    arrays, never the full ones: a select process that opens a cut has not loaded a minute at or after the cut (audit A5)."""
    out = cut_dir(work, pin_hash, cut_ms, prefix)
    meta_path = os.path.join(out, "cut.json")
    if not os.path.exists(meta_path):
        raise CutMissing(f"cut data folder missing: {out} (run the make-cut step first)")
    meta = json.load(open(meta_path))
    if meta.get("pin") != pin_hash or meta.get("cut_ms") != cut_ms or sorted(meta["coins"]) != sorted(symbols):
        raise CutMissing(f"cut data folder {out} belongs to another pin, cut or coin set (run the make-cut step)")
    if not verify_cut(out, symbols):
        raise PinError(f"cut data folder {out} does not match its digests")
    return out


def verify_cut(folder: str, symbols=SYMBOLS) -> bool:
    """The cut folder's arrays match their digests and none holds a minute at or after the cut (audit A5)."""
    meta = json.load(open(os.path.join(folder, "cut.json")))
    for s in symbols:
        d = _load_npz(os.path.join(folder, "1m", f"{s}.npz"))
        if array_digest(d) != meta["coins"][s]["digest"] or len(d["ts"]) != meta["coins"][s]["minutes"]:
            return False
        if len(d["ts"]) and int(d["ts"][-1]) >= meta["cut_ms"]:
            return False
    return True


def assert_no_minute_at_or_after(arrays_by_coin: dict, cut_ms: int) -> None:
    """Audit A5: no array loaded by the select process holds a minute at or after the cut."""
    for s, d in arrays_by_coin.items():
        if len(d["ts"]) and int(d["ts"][-1]) >= cut_ms:
            raise AssertionError(f"{s}: a minute at or after the cut is loaded")


def free_mb(path: str) -> float:
    return shutil.disk_usage(path).free / 1e6


# ------------------------------------------------------------------ the study's code (research/fullgrid)
_FG = {}


def fg():
    """research/fullgrid/run.py as module ``run`` (the name sizing.py imports it under)."""
    if "run" not in _FG:
        if FG not in sys.path:
            sys.path.insert(0, FG)
        import run as R  # noqa: E402
        if not os.path.abspath(R.__file__).startswith(FG):
            raise RuntimeError("module 'run' is not research/fullgrid/run.py")
        _FG["run"] = R
    return _FG["run"]


def sizing():
    fg()
    import sizing as SZ  # noqa: E402
    return SZ


def seed_of(*parts) -> int:
    """run._seed: the first 8 hex digits of the sha256 of the '|'-joined parts."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# ------------------------------------------------------------------ picks (prereg 3)
def _tup(c: dict) -> dict:
    return {k: (tuple(v) if isinstance(v, list) else v) for k, v in c.items()}


def picks(watch_sel: str | None = None, candidates: str | None = None, pool: str | None = None) -> list:
    """The 38 rows of watch_sel.json (23 ``core`` and 15 ``ds``; ``pool`` = 'core' or 'ds' keeps one): id
    ``<kind>-<name>-<tf>-<rank>`` (checked against candleague's candidates.json, whose fields id, kind, name, tf, exit and
    combo are the only ones read), kind, name, tf, combo, exit name, its index in kernel.EXITS and the pool."""
    rows = json.load(open(watch_sel or WATCH_SEL))
    names = [e[0] for e in K.EXITS]
    out = []
    for r in rows:
        out.append({"id": f"{r['kind']}-{r['name']}-{r['tf']}-{int(r['rank'])}", "kind": r["kind"], "pool": r["kind"],
                    "name": r["name"], "tf": r["tf"], "combo": _tup(json.loads(r["combo"])), "exit": r["exit"],
                    "exit_index": names.index(r["exit"]), "rank": int(r["rank"])})
    cpath = candidates or CANDIDATES
    if os.path.exists(cpath):
        cands = json.load(open(cpath))["candidates"]
        by_id = {c["id"]: c for c in cands}
        if sorted(by_id) != sorted(p["id"] for p in out):
            raise RuntimeError("candidates.json and watch_sel.json disagree on the picks")
        for p in out:
            c = by_id[p["id"]]
            if (c["kind"], c["name"], c["tf"], c["exit"]) != (p["kind"], p["name"], p["tf"], p["exit"]) or _tup(c["combo"]) != p["combo"]:
                raise RuntimeError(f"{p['id']}: candidates.json and watch_sel.json disagree")
    if len(out) != 38 or sum(p["kind"] == "core" for p in out) != 23:
        raise RuntimeError(f"expected 23 core and 15 ds picks, got {len(out)}")
    return [p for p in out if pool in (None, p["pool"])]


def pick_by_id(pid: str) -> dict:
    return next(p for p in picks() if p["id"] == pid)


# ------------------------------------------------------------------ providers: chart bars, signals, leverage groups
class RealProvider:
    """The study's own chart bars (run.frame), signals (run.signals on the pinned param_defs), leverage groups
    (run.best_flags), ATR14 and EMA (fg_indicators), period ids (run.period_ids), for one data folder."""

    def __init__(self, data_dir: str, cache_dir: str):
        self.R = fg()
        self.data_dir = data_dir
        self.R.FRAME_DIR[0] = os.path.join(cache_dir, "frames")
        os.makedirs(self.R.FRAME_DIR[0], exist_ok=True)
        self.symbols = SYMBOLS

    def frame(self, sym: str, tf: str) -> tuple:
        return self.R.frame(self.data_dir, sym, tf)

    def signals(self, pick: dict, sym: str) -> tuple:
        return self.R.signals(self.data_dir, pick["kind"], pick["name"], sym, pick["tf"], pick["combo"])

    def best(self, pick: dict, sym: str) -> tuple:
        if pick["kind"] == "ds":                       # DeepSeek is always 'normal' (run.trade_table, the league)
            n = len(self.frame(sym, pick["tf"])[0])
            return np.zeros(n, bool), np.zeros(n, bool)
        return self.R.best_flags(self.data_dir, pick["name"], sym, pick["tf"])

    def atr(self, df) -> np.ndarray:
        return self.R._vendor_fg().atr(df, 14).to_numpy(float)

    def ema(self, df, n: int) -> np.ndarray:
        return self.R._vendor_fg().ema(df["close"], n).to_numpy(float)

    def period_ids(self, close_ms: np.ndarray) -> np.ndarray:
        return self.R.period_ids(close_ms)


def period_code(period: str) -> int:
    return {"select": 0, "confirm": 1}[period]


# ------------------------------------------------------------------ swings and the reference path
@njit
def swing_flags(h, l, k):
    """(swing high, swing low) flags per bar: strictly beyond the k bars on each side (kernel.structure_levels' own test).
    A swing at bar p is known at bar p + k."""
    n = len(h)
    ph = np.zeros(n, np.int8)
    pl = np.zeros(n, np.int8)
    for p in range(k, n - k):
        hi = True
        lo = True
        for j in range(p - k, p + k + 1):
            if j == p:
                continue
            if not h[p] > h[j]:
                hi = False
            if not l[p] < l[j]:
                lo = False
        ph[p] = 1 if hi else 0
        pl[p] = 1 if lo else 0
    return ph, pl


@njit
def ref_path(swl, swh, lo, hi, start, w, side, i0, i_end):
    """F1's reference (prereg 5.2) at every bar i0 .. i_end of a position opened on signal bar i0: ``start`` (the
    structure_levels output at i0, NaN none), then at every bar i > i0 a swing at p = i - w that lies above (long: swing
    low higher than the reference; short: swing high lower) or meets no reference replaces it. Index 0 = bar i0."""
    out = np.full(i_end - i0 + 1, np.nan)
    ref = start
    out[0] = ref
    for i in range(i0 + 1, i_end + 1):
        p = i - w
        if p >= 0:
            if side > 0:
                if swl[p] == 1:
                    if np.isnan(ref) or lo[p] > ref:
                        ref = lo[p]
            else:
                if swh[p] == 1:
                    if np.isnan(ref) or hi[p] < ref:
                        ref = hi[p]
        out[i - i0] = ref
    return out


# ------------------------------------------------------------------ the market: minutes of all coins, exchange numbers
def exchange_numbers(ex: dict) -> tuple:
    """(bracket arrays per coin, quantity steps, minimum notionals) from ``run.exchange``'s dict, in run.SYMBOLS order."""
    R = fg()
    brs = np.stack([ex[s][0] for s in R.SYMBOLS]) if R._same_shape(ex) else R._pad(ex)
    return brs, np.array([ex[s][1] for s in R.SYMBOLS]), np.array([ex[s][2] for s in R.SYMBOLS])


def engine_fingerprint(market=None, exchange_path: str = EXCHANGE) -> dict:
    """The numbers that fix every account and that live in files outside the pinned arrays: the settings vector ``S`` of both sizes
    (``config.v3_settings`` through ``kernel.settings_vector``, margin fractions times the scale) and a digest of the bracket,
    quantity-step and minimum-notional arrays (``exchange.json`` through ``paperbot.margin.Brackets``). The select run writes it
    into select.json; the confirm stage refuses on any difference. With ``market`` None it is rebuilt from the files, which gives the
    same document byte for byte. No performance figure is in it."""
    if market is None:
        brs, qty, mn = exchange_numbers(fg().exchange(exchange_path, False))
        S = {s: sizing().size_vector(s) for s in (0.25, 1.0)}
    else:
        brs, qty, mn = market.brs, market.qty_steps, market.min_notionals
        S = {s: market.S(s) for s in (0.25, 1.0)}
    return {"S": {str(s): [float(x) for x in np.asarray(v, float)] for s, v in S.items()},
            "brackets_sha256": array_digest({"brs": np.asarray(brs, float), "qty": np.asarray(qty, float), "min_notional": np.asarray(mn, float)})}


class Market:
    """The coins' 1m arrays concatenated (kernel.account's layout), the exchange numbers and the period ends."""

    def __init__(self, data_dir: str | None = None, symbols=SYMBOLS, minutes=None, exchange=None, exchange_path=EXCHANGE):
        R = fg()
        self.data_dir = data_dir
        self.symbols = tuple(symbols)
        if minutes is None:
            cat, starts, ends = R.all_minutes(data_dir)
        else:
            cat, starts, ends = minutes
        self.cat = cat
        self.starts = np.asarray(starts, np.int64)
        self.ends = np.asarray(ends, np.int64)
        ex = exchange if exchange is not None else R.exchange(exchange_path, False)
        self.brs, self.qty_steps, self.min_notionals = exchange_numbers(ex)
        self._S = {}
        self._pend = {}
        self.bar_ms = MIN                       # bar length of the minute arrays (the study runs 1m bars only)

    def ts(self, c: int) -> np.ndarray:
        return self.cat["ts"][self.starts[c]:self.ends[c]]

    def S(self, scale: float) -> np.ndarray:
        if scale not in self._S:
            self._S[scale] = sizing().size_vector(scale)
        return self._S[scale]

    def period_end(self, period: str) -> np.ndarray:
        """Per coin the exclusive end index (absolute) of the period's minutes: those that open before its end."""
        if period not in self._pend:
            hi = PERIOD_MS[period][1]
            self._pend[period] = np.array([self.starts[c] + np.searchsorted(self.ts(c), hi, side="left")
                                           for c in range(len(self.symbols))], np.int64)
        return self._pend[period]

    @classmethod
    def from_arrays(cls, coins: list, exchange: dict, symbols=None) -> "Market":
        """Build from a list of per-coin dicts (ts, o, h, l, mo, mh, ml, fund) - synthetic data for tests."""
        cat = {k: np.concatenate([c[k] for c in coins]) for k in ("ts", "o", "h", "l", "mo", "mh", "ml", "fund")}
        starts, ends, pos = [], [], 0
        for c in coins:
            starts.append(pos)
            pos += len(c["ts"])
            ends.append(pos)
        return cls(None, symbols or SYMBOLS[:len(coins)], (cat, starts, ends), exchange)


# ------------------------------------------------------------------ one pick: chart bars, signals, offered signals
def _tri(a) -> np.ndarray:
    """0 / 1 / 2 (NaN) int8 values of a component array (booleans, or floats with NaN for 'unknown')."""
    a = np.asarray(a)
    if a.dtype == bool:
        return a.astype(np.int8)
    a = a.astype(float)
    return np.where(np.isnan(a), 2, (a != 0).astype(np.int8)).astype(np.int8)


def normalize_f11(ret, n: int) -> dict:
    """The provider's return value as a dict of lists / arrays of length ``n`` (see kernel_x.register_f11)."""
    nan = np.full(n, np.nan)
    if isinstance(ret, dict):
        out = {"comp_long": list(ret.get("comp_long") or []), "comp_short": list(ret.get("comp_short") or []),
               "lvl_long": ret.get("lvl_long"), "lvl_short": ret.get("lvl_short"), "tgt_long": ret.get("tgt_long"),
               "tgt_short": ret.get("tgt_short")}
    else:
        lx, sx, tl, ts_ = ret
        out = {"comp_long": [("event", lx)], "comp_short": [("event", sx)], "lvl_long": None, "lvl_short": None,
               "tgt_long": tl, "tgt_short": ts_}
    for k in ("lvl_long", "lvl_short", "tgt_long", "tgt_short"):
        out[k] = nan if out[k] is None else np.asarray(out[k], float)
    for k in ("z_long", "z_short"):                          # optional: the strategy's own 'can fire at this bar' flag
        out[k] = np.ones(n, np.int8) if not isinstance(ret, dict) or ret.get(k) is None else (np.asarray(ret[k]) != 0).astype(np.int8)
    for k in ("comp_long", "comp_short"):
        if len(out[k]) > KX.NC:
            raise ValueError(f"F11: at most {KX.NC} components per side")
        for kind, arr in out[k]:
            if kind not in ("state", "event") or len(arr) != n:
                raise ValueError("F11: a component is (kind in 'state' / 'event', array of one value per chart bar)")
    return out


class PickData:
    """A pick's chart data over all coins (concatenated) and the arrays each variant's kernel run reads. ``f11`` = the
    provider of the strategy's own exit (kernel_x.register_f11), or None."""

    def __init__(self, market: Market, pick: dict, provider, f11=None, strict_flags: bool = True):
        self.market, self.pick, self.provider = market, pick, provider
        self.strict_flags = strict_flags
        self.tf = pick["tf"]
        self.tf_ms = TF_MS[self.tf]
        n_c = len(market.symbols)
        cl_ms, cl, hi, lo, atr, mn, sl, ss, bl, bs, pid, tl, ts_, ll, ls, zl, zs, stt = ([] for _ in range(18))
        comps = []
        self.frames = []
        for c, sym in enumerate(market.symbols):
            df, close = provider.frame(sym, self.tf)
            self.frames.append((df, close))
            lo_s, sh_s = provider.signals(pick, sym)
            b_l, b_s = provider.best(pick, sym)
            n = len(df)
            cl_ms.append(np.asarray(close, np.float64))
            cl.append(df["close"].to_numpy(float))
            hi.append(df["high"].to_numpy(float))
            lo.append(df["low"].to_numpy(float))
            atr.append(provider.atr(df))
            stt.append(regime_codes(sym, self.tf, df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)))
            mn.append(self._minute_of(market.ts(c), np.asarray(close, np.int64), market.bar_ms))
            sl.append(np.asarray(lo_s, np.int8))
            ss.append(np.asarray(sh_s, np.int8))
            bl.append(np.asarray(b_l, bool))
            bs.append(np.asarray(b_s, bool))
            pid.append(np.asarray(provider.period_ids(np.asarray(close, np.int64)), np.int8))
            if f11 is not None:
                r = normalize_f11(f11(pick, sym, df, close, np.asarray(lo_s, bool), np.asarray(sh_s, bool)), n)
                comps.append(r)
                tl.append(r["tgt_long"])
                ts_.append(r["tgt_short"])
                ll.append(r["lvl_long"])
                ls.append(r["lvl_short"])
                zl.append(r["z_long"])
                zs.append(r["z_short"])
            else:
                nan = np.full(n, np.nan)
                zl.append(np.ones(n, np.int8))
                zs.append(np.ones(n, np.int8))
                comps.append(None)
                tl.append(nan)
                ts_.append(nan)
                ll.append(nan)
                ls.append(nan)
        self.n_bars = [len(x) for x in cl]
        self.cst = np.r_[0, np.cumsum(self.n_bars)[:-1]].astype(np.int64)
        self.cen = np.cumsum(self.n_bars).astype(np.int64)
        cat = np.concatenate
        self.b_cms, self.b_cl, self.b_hi, self.b_lo, self.b_atr, self.b_min = (cat(cl_ms), cat(cl), cat(hi), cat(lo), cat(atr),
                                                                              cat(mn).astype(np.float64))
        self.b_sl, self.b_ss = cat(sl), cat(ss)
        self.b_tl, self.b_ts, self.b_ll, self.b_ls = cat(tl), cat(ts_), cat(ll), cat(ls)
        self.b_zl, self.b_zs = cat(zl), cat(zs)
        self.b_state = cat(stt).astype(np.int8)
        self.best_l, self.best_s, self.pid = cat(bl), cat(bs), cat(pid)
        # F11 component columns (0 false, 1 true, 2 NaN) and kinds
        self.b_comp = np.zeros((len(self.b_cl), 2 * KX.NC), np.int8)
        self.ckind = np.zeros(2 * KX.NC, np.int8)
        if f11 is not None:
            for side_i, key in enumerate(("comp_long", "comp_short")):
                for k in range(KX.NC):
                    kinds = {r[key][k][0] for r in comps if len(r[key]) > k}
                    lens = {len(r[key]) for r in comps}
                    if len(lens) != 1 or len(kinds) > 1:
                        raise ValueError("F11: the components of a strategy must be the same for every coin")
                    if kinds:
                        self.ckind[side_i * KX.NC + k] = KX.CK_STATE if kinds == {"state"} else KX.CK_EVENT
                        self.b_comp[:, side_i * KX.NC + k] = cat([_tri(r[key][k][1]) for r in comps])
        self._sw: dict = {}
        self._ema: dict = {}
        self._q = None
        self._off: dict = {}
        self._chart: dict = {}
        self._n_coins = n_c

    @staticmethod
    def _minute_of(ts: np.ndarray, close_ms: np.ndarray, bar_ms: int = MIN) -> np.ndarray:
        """kernel._entry_index of every close: the minute that opens at the close, one later when the minute before it is
        missing, -1 when the data ends first (``bar_ms``: the bar length of the minute arrays, 60,000 for 1m)."""
        j = np.searchsorted(ts, close_ms - bar_ms, side="left") + 1
        j[j >= len(ts)] = -1
        return j

    # ---- per-width / per-EMA caches
    def swings(self, w: int) -> tuple:
        """(swing low flags, swing high flags, starting reference long, starting reference short) over all coins."""
        if w not in self._sw:
            sl, sh, lo_, hi_ = [], [], [], []
            for c in range(self._n_coins):
                a, b = self.cst[c], self.cen[c]
                h, l, cl = self.b_hi[a:b], self.b_lo[a:b], self.b_cl[a:b]
                ph, pl = swing_flags(h, l, w)
                tl, ts_ = K.structure_levels(h, l, cl, int(w), K.STRUCT_LOOKBACK)
                sl.append(pl)
                sh.append(ph)
                lo_.append(ts_)                       # highest confirmed swing low below the close (start, long)
                hi_.append(tl)                        # lowest confirmed swing high above the close (start, short)
            self._sw[w] = (np.concatenate(sl), np.concatenate(sh), np.concatenate(lo_), np.concatenate(hi_))
        return self._sw[w]

    def ema(self, n: int) -> np.ndarray:
        if n not in self._ema:
            self._ema[n] = np.concatenate([self.provider.ema(self.frames[c][0], n) for c in range(self._n_coins)])
        return self._ema[n]

    def q15(self) -> tuple:
        """(QT, qst, qen) for picks on 1h / 4h: the coins' 15m chart bars with the index of the latest pick-timeframe bar
        closed at or before each close."""
        if self._q is None:
            rows, qst, qen, pos = [], [], [], 0
            for c, sym in enumerate(self.market.symbols):
                df, close = self.provider.frame(sym, "15m")
                close = np.asarray(close, np.int64)
                pcl = np.asarray(self.frames[c][1], np.int64)
                m = np.empty((len(df), KX.NQT))
                m[:, KX.Q_CMS] = close
                m[:, KX.Q_CL] = df["close"].to_numpy(float)
                m[:, KX.Q_MIN] = self._minute_of(self.market.ts(c), close, self.market.bar_ms)
                m[:, KX.Q_PT] = np.searchsorted(pcl, close, side="right") - 1
                rows.append(m)
                qst.append(pos)
                pos += len(df)
                qen.append(pos)
            self._q = (np.ascontiguousarray(np.vstack(rows)), np.array(qst, np.int64), np.array(qen, np.int64))
        return self._q

    # ---- chart arrays of one variant
    def chart(self, v) -> tuple:
        """(rp, PT, PF, QT, cst, cen, qst, qen) the kernel reads for variant ``v`` (a Variant; E0 reads none)."""
        n_c = self._n_coins
        if v.fam in (KX.F_NONE, KX.F13):                    # no chart data: E0, and F13 (the stepped lock, an exit tuple)
            PT, PF, QT = KX.empty_chart()
            z = np.zeros(n_c, np.int64)
            return KX.rp_vector(), PT, PF, QT, z, z, z, z
        q15 = bool(v.q15) and self.tf in ("1h", "4h")
        key = (v.params.get("w", 0) if v.fam in (KX.F1, KX.F6, KX.F8, KX.F9, KX.F12) else 0,
               v.params.get("n", 0) if v.fam in (KX.F2, KX.F12) else 0, q15, v.fam in (KX.F3, KX.F11, KX.F12),
               v.fam in (KX.F11, KX.F12))
        if key not in self._chart:
            self._chart.clear()                                # keep one set: a chart is up to ~100 MB
            n = len(self.b_cl)
            PT = np.empty((n, KX.NPT))
            PT[:, KX.C_CMS], PT[:, KX.C_CL], PT[:, KX.C_ATR] = self.b_cms, self.b_cl, self.b_atr
            PT[:, KX.C_LO], PT[:, KX.C_HI], PT[:, KX.C_MIN] = self.b_lo, self.b_hi, self.b_min
            PT[:, KX.C_EMA] = self.ema(key[1]) if key[1] else np.nan
            PF = np.zeros((n, KX.NPF), np.int8)
            if key[0]:
                swl, swh, slo, shi = self.swings(key[0])
                PF[:, KX.P_SWL], PF[:, KX.P_SWH] = swl, swh
                PT[:, KX.C_SLO], PT[:, KX.C_SHI] = slo, shi
            else:
                PT[:, KX.C_SLO] = np.nan
                PT[:, KX.C_SHI] = np.nan
            PF[:, KX.P_SIGL], PF[:, KX.P_SIGS] = self.b_sl, self.b_ss
            PF[:, KX.P_ZL], PF[:, KX.P_ZS] = 1, 1
            if key[4]:
                PF[:, KX.P_CL0:KX.P_CL0 + 2 * KX.NC] = self.b_comp
                PF[:, KX.P_ZL], PF[:, KX.P_ZS] = self.b_zl, self.b_zs
            if q15:
                QT, qst, qen = self.q15()
            else:
                QT, qst, qen = np.zeros((0, KX.NQT)), np.zeros(n_c, np.int64), np.zeros(n_c, np.int64)
            self._chart[key] = (PT, PF, QT, qst, qen)
        PT, PF, QT, qst, qen = self._chart[key]
        return v.rp(self.tf_ms, q15), PT, PF, QT, self.cst, self.cen, qst, qen

    # ---- offered signals (prereg 3)
    def offered(self, period: str, market: Market | None = None) -> dict:
        """Every long and short signal of the period whose ATR14 is finite and > 0 and whose fill minute opens before the
        period's last minute, sorted by (fill time, coin priority); the long first when both sides are true on one bar
        of one coin (the per-trade order of run.per_trade: coin, bar, side)."""
        if period in self._off:
            return self._off[period]
        market = market or self.market
        pend = market.period_end(period)
        code = period_code(period)
        cols = {k: [] for k in ("coin", "close", "side", "atr", "best", "i0", "fill", "state")}
        for c in range(len(market.symbols)):
            a, b = self.cst[c], self.cen[c]
            sel = self.pid[a:b] == code
            il = np.flatnonzero((self.b_sl[a:b] == 1) & sel)
            is_ = np.flatnonzero((self.b_ss[a:b] == 1) & sel)
            if self.strict_flags and np.intersect1d(il, is_).size:         # prereg 3: no pick carries both flags on one bar
                raise AssertionError(f"{self.pick['id']}: a bar carries both a long and a short flag")
            idx = np.r_[il, is_]
            side = np.r_[np.ones(len(il), np.int64), -np.ones(len(is_), np.int64)]
            o = np.argsort(idx, kind="stable")                    # run.per_trade order
            idx, side = idx[o], side[o]
            atr = self.b_atr[a:b][idx]
            close = self.b_cms[a:b][idx].astype(np.int64)
            tsp = market.cat["ts"][market.starts[c]:pend[c]]
            j0 = np.searchsorted(tsp, close - market.bar_ms, side="left")
            e = j0 + 1
            ok = np.isfinite(atr) & (atr > 0) & (e <= len(tsp) - 2)
            idx, side, atr, close, e = idx[ok], side[ok], atr[ok], close[ok], e[ok]
            cols["coin"].append(np.full(len(idx), c, np.int64))
            cols["close"].append(close)
            cols["side"].append(side)
            cols["atr"].append(atr)
            cols["best"].append(np.where(side > 0, self.best_l[a:b][idx], self.best_s[a:b][idx]).astype(np.bool_))
            cols["i0"].append(idx.astype(np.int64))
            cols["fill"].append(tsp[e] if len(e) else np.zeros(0, np.int64))
            cols["state"].append(self.b_state[a:b][idx].astype(np.int8))
        out = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in cols.items()}
        order = np.lexsort((out["coin"], out["fill"])) if len(out["coin"]) else np.zeros(0, np.int64)
        out = {k: np.ascontiguousarray(v[order]) for k, v in out.items()}
        out["coin"] = out["coin"].astype(np.int64)
        out["close"] = out["close"].astype(np.int64)
        out["side"] = out["side"].astype(np.int64)
        out["i0"] = out["i0"].astype(np.int64)
        out["best"] = out["best"].astype(np.bool_)
        out["state"] = out["state"].astype(np.int8)
        ix = (self.cst[out["coin"]] + out["i0"]) if len(order) else np.zeros(0, np.int64)
        out["tp_idx"] = ix
        out["lvl"] = np.where(out["side"] > 0, self.b_ll[ix], self.b_ls[ix]) if len(ix) else np.zeros(0)
        self._off[period] = out
        return out

    def targets(self, off: dict) -> np.ndarray:
        """F11's per-signal target price (NaN none): the strategy's target array at the signal bar, by side."""
        ix = off["tp_idx"]
        return np.where(off["side"] > 0, self.b_tl[ix], self.b_ts[ix]) if len(ix) else np.zeros(0)


# ------------------------------------------------------------------ test T3: the last 50 chart bars before a cut
def snapshot(provider, symbols, cut_ms: int, picks_list: list, n_last: int = 50, widths=(2, 3, 5), emas=(10, 20, 50),
             f11=None) -> dict:
    """The arrays test T3 compares between cut and full data: for every coin and timeframe the last ``n_last`` chart bars
    that close at or before ``cut_ms``: close ms, OHLC, ATR14, EMA(10, 20, 50), the swing flags with their confirmation bar
    (bars whose swing is not confirmed by the last bar read -1), the starting references of F1, F1's reference path from
    each of these bars to the last bar (long and short), the 15m bars, and for every pick its two signal flags and its two
    leverage groups on those bars - and, with an F11 provider, its components of both sides, levels and targets. Returned as a
    flat dict of numpy arrays."""
    out = {}
    for sym in symbols:
        for tf in TFS:
            df, close = provider.frame(sym, tf)
            close = np.asarray(close, np.int64)
            i_last = int(np.searchsorted(close, cut_ms, side="right")) - 1
            idx = np.arange(max(0, i_last - n_last + 1), i_last + 1)
            key = f"{sym}|{tf}|"
            out[key + "close_ms"] = close[idx]
            for col in ("open", "high", "low", "close"):
                out[key + col] = df[col].to_numpy(float)[idx]
            out[key + "atr"] = provider.atr(df)[idx]
            rg = regime_arrays(sym, tf, df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float))
            out[key + "state"] = rg["code"][idx]
            for name in ("adx", "slope", "atrp", "vol_q"):          # prereg 13 T3: ADX14, EMA50 slope, ATR% and its threshold at every bar
                out[key + name] = rg[name][idx]
            for n in emas:
                out[key + f"ema{n}"] = provider.ema(df, n)[idx]
            h, l, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
            for w in widths:
                ph, pl = swing_flags(h, l, w)
                known = idx + w <= i_last
                out[key + f"swl{w}"] = np.where(known, pl[idx], -1)
                out[key + f"swh{w}"] = np.where(known, ph[idx], -1)
                out[key + f"conf{w}"] = np.where(known, close[np.minimum(idx + w, i_last)], -1)
                tl, ts_ = K.structure_levels(h, l, c, int(w), K.STRUCT_LOOKBACK)
                out[key + f"start_lo{w}"] = ts_[idx]
                out[key + f"start_hi{w}"] = tl[idx]
                rl = np.empty(len(idx))
                rs = np.empty(len(idx))
                for k, i0 in enumerate(idx):
                    rl[k] = ref_path(pl, ph, l, h, ts_[i0], w, 1, int(i0), i_last)[-1]
                    rs[k] = ref_path(pl, ph, l, h, tl[i0], w, -1, int(i0), i_last)[-1]
                out[key + f"ref_long{w}"] = rl
                out[key + f"ref_short{w}"] = rs
    for p in picks_list:
        for c, sym in enumerate(symbols):
            df, close = provider.frame(sym, p["tf"])
            close = np.asarray(close, np.int64)
            i_last = int(np.searchsorted(close, cut_ms, side="right")) - 1
            idx = np.arange(max(0, i_last - n_last + 1), i_last + 1)
            lo, sh = provider.signals(p, sym)
            bl, bs = provider.best(p, sym)
            key = f"{p['id']}|{sym}|"
            out[key + "close_ms"] = close[idx]
            out[key + "sig_long"], out[key + "sig_short"] = np.asarray(lo, bool)[idx], np.asarray(sh, bool)[idx]
            code = regime_codes(sym, p["tf"], df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float))
            out[key + "state"] = np.where(np.asarray(lo, bool)[idx] | np.asarray(sh, bool)[idx], code[idx], -1).astype(np.int8)   # at every signal bar
            out[key + "best_long"], out[key + "best_short"] = np.asarray(bl, bool)[idx], np.asarray(bs, bool)[idx]
            if f11 is not None:
                r = normalize_f11(f11(p, sym, df, close, np.asarray(lo, bool), np.asarray(sh, bool)), len(df))
                for side_name in ("long", "short"):
                    for k, (kind, arr) in enumerate(r["comp_" + side_name]):
                        out[key + f"comp_{side_name}{k}_{kind}"] = _tri(arr)[idx]
                    out[key + "lvl_" + side_name] = r["lvl_" + side_name][idx]
                    out[key + "tgt_" + side_name] = r["tgt_" + side_name][idx]
    return out


def snapshot_equal(a: dict, b: dict) -> list:
    """Names of the arrays that differ between two snapshots (empty = equal); NaNs compare equal."""
    bad = [k for k in sorted(set(a) | set(b)) if k not in a or k not in b or a[k].shape != b[k].shape
           or not np.array_equal(a[k], b[k], equal_nan=True)]
    return bad
