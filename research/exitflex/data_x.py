"""exitflex data side (research/exitflex/PREREG_EXITFLEX.md sections 2, 3, 13).

* the pin (``data_pin.json``): the sha256 of ``fg1m/build.json`` and of each coin file; ``verify_data`` refuses any other file;
* the select cut: the 1m arrays cut at 2024-01-01 00:00 UTC (minutes that open before it) written as their own data folder
  ``$WORK/<pin8>/cut-<cut time>/1m/<SYM>.npz`` (``cut.json`` holds the pin hash, the cut and a digest of every array), so
  that every ``run.py`` cache keyed by the data folder sees a different key for cut and full data;
* stage cache folders ``$WORK/<pin8>/<stage>/`` (deleted when a stage starts, ``run.FRAME_DIR`` points into them);
* the 23 picks, their chart bars, signals, leverage groups and the offered signals of a period (prereg 3);
* the chart arrays the kernel reads for each variant (swings, EMA, starting references, 15m bars of q15 variants);
* ``snapshot`` for test T3 (the last 50 chart bars before a cut, compared between cut and full data).

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
def cut_name(cut_ms: int) -> str:
    return "cut-" + dt.datetime.fromtimestamp(cut_ms / 1000, dt.timezone.utc).strftime("%Y%m%d%H%M")


def cut_dir(work: str, pin_hash: str, cut_ms: int) -> str:
    return os.path.join(work, pin8(pin_hash), cut_name(cut_ms))


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


def write_cut(src_dir: str, work: str, pin_hash: str, cut_ms: int, symbols=SYMBOLS, min_free_mb: int = 250) -> str:
    """Write the arrays of ``src_dir`` cut at ``cut_ms`` (minutes that open before it) as their own data folder and return
    it. An existing folder with the same pin, cut and digests is reused. The arrays are stored compressed (disk is tight).
    Fails before writing when less than the expected size plus ``min_free_mb`` is free."""
    out = cut_dir(work, pin_hash, cut_ms)
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


def picks(watch_sel: str | None = None, candidates: str | None = None) -> list:
    """The 23 core rows of watch_sel.json: id ``core-<name>-<tf>-<rank>`` (checked against candleague's candidates.json),
    name, tf, combo, exit name and index in kernel.EXITS."""
    rows = [r for r in json.load(open(watch_sel or WATCH_SEL)) if r["kind"] == "core"]
    names = [e[0] for e in K.EXITS]
    out = []
    for r in rows:
        out.append({"id": f"core-{r['name']}-{r['tf']}-{int(r['rank'])}", "kind": "core", "name": r["name"], "tf": r["tf"],
                    "combo": _tup(json.loads(r["combo"])), "exit": r["exit"], "exit_index": names.index(r["exit"]),
                    "rank": int(r["rank"])})
    if len(out) != 23:
        raise RuntimeError(f"expected 23 core picks, got {len(out)}")
    cpath = candidates or CANDIDATES
    if os.path.exists(cpath):
        cands = [c for c in json.load(open(cpath))["candidates"] if c["kind"] == "core"]
        if sorted(c["id"] for c in cands) != sorted(p["id"] for p in out):
            raise RuntimeError("candidates.json and watch_sel.json disagree on the core picks")
    return out


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
        return self.R.signals(self.data_dir, "core", pick["name"], sym, pick["tf"], pick["combo"])

    def best(self, pick: dict, sym: str) -> tuple:
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
        self.brs = np.stack([ex[s][0] for s in R.SYMBOLS]) if R._same_shape(ex) else R._pad(ex)
        self.qty_steps = np.array([ex[s][1] for s in R.SYMBOLS])
        self.min_notionals = np.array([ex[s][2] for s in R.SYMBOLS])
        self._S = {}
        self._pend = {}

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
class PickData:
    """A pick's chart data over all coins (concatenated) and the arrays each variant's kernel run reads."""

    def __init__(self, market: Market, pick: dict, provider, f11=None):
        self.market, self.pick, self.provider = market, pick, provider
        self.tf = pick["tf"]
        self.tf_ms = TF_MS[self.tf]
        n_c = len(market.symbols)
        cl_ms, cl, hi, lo, atr, mn, sl, ss, bl, bs, pid, xl, xs, tl, ts_ = ([] for _ in range(15))
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
            mn.append(self._minute_of(market.ts(c), np.asarray(close, np.int64)))
            sl.append(np.asarray(lo_s, np.int8))
            ss.append(np.asarray(sh_s, np.int8))
            bl.append(np.asarray(b_l, bool))
            bs.append(np.asarray(b_s, bool))
            pid.append(np.asarray(provider.period_ids(np.asarray(close, np.int64)), np.int8))
            if f11 is not None:
                a, b, ta, tb = f11(pick, sym, df, close, np.asarray(lo_s, bool), np.asarray(sh_s, bool))
                xl.append(np.asarray(a, np.int8))
                xs.append(np.asarray(b, np.int8))
                tl.append(np.asarray(ta, float))
                ts_.append(np.asarray(tb, float))
            else:
                xl.append(np.zeros(n, np.int8))
                xs.append(np.zeros(n, np.int8))
                tl.append(np.full(n, np.nan))
                ts_.append(np.full(n, np.nan))
        self.n_bars = [len(x) for x in cl]
        self.cst = np.r_[0, np.cumsum(self.n_bars)[:-1]].astype(np.int64)
        self.cen = np.cumsum(self.n_bars).astype(np.int64)
        cat = np.concatenate
        self.b_cms, self.b_cl, self.b_hi, self.b_lo, self.b_atr, self.b_min = (cat(cl_ms), cat(cl), cat(hi), cat(lo), cat(atr),
                                                                              cat(mn).astype(np.float64))
        self.b_sl, self.b_ss, self.b_xl, self.b_xs = cat(sl), cat(ss), cat(xl), cat(xs)
        self.b_tl, self.b_ts = cat(tl), cat(ts_)
        self.best_l, self.best_s, self.pid = cat(bl), cat(bs), cat(pid)
        self._sw: dict = {}
        self._ema: dict = {}
        self._q = None
        self._off: dict = {}
        self._chart: dict = {}
        self._n_coins = n_c

    @staticmethod
    def _minute_of(ts: np.ndarray, close_ms: np.ndarray) -> np.ndarray:
        """kernel._entry_index of every close: the minute that opens at the close, one later when the minute before it is
        missing, -1 when the data ends first."""
        j = np.searchsorted(ts, close_ms - MIN, side="left") + 1
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
                m[:, KX.Q_MIN] = self._minute_of(self.market.ts(c), close)
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
        if v.fam == KX.F_NONE:
            PT, PF, QT = KX.empty_chart()
            z = np.zeros(n_c, np.int64)
            return KX.rp_vector(), PT, PF, QT, z, z, z, z
        q15 = bool(v.q15) and self.tf in ("1h", "4h")
        key = (v.params.get("w", 0) if v.fam in (KX.F1, KX.F6, KX.F8, KX.F9) else 0,
               v.params.get("n", 0) if v.fam == KX.F2 else 0, q15, v.fam == KX.F11 or v.fam == KX.F3)
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
            PF[:, KX.P_XL], PF[:, KX.P_XS] = self.b_xl, self.b_xs
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
        cols = {k: [] for k in ("coin", "close", "side", "atr", "best", "i0", "fill")}
        for c in range(len(market.symbols)):
            a, b = self.cst[c], self.cen[c]
            sel = self.pid[a:b] == code
            il = np.flatnonzero((self.b_sl[a:b] == 1) & sel)
            is_ = np.flatnonzero((self.b_ss[a:b] == 1) & sel)
            idx = np.r_[il, is_]
            side = np.r_[np.ones(len(il), np.int64), -np.ones(len(is_), np.int64)]
            o = np.argsort(idx, kind="stable")                    # run.per_trade order
            idx, side = idx[o], side[o]
            atr = self.b_atr[a:b][idx]
            close = self.b_cms[a:b][idx].astype(np.int64)
            tsp = market.cat["ts"][market.starts[c]:pend[c]]
            j0 = np.searchsorted(tsp, close - MIN, side="left")
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
        out = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in cols.items()}
        order = np.lexsort((out["coin"], out["fill"])) if len(out["coin"]) else np.zeros(0, np.int64)
        out = {k: np.ascontiguousarray(v[order]) for k, v in out.items()}
        out["coin"] = out["coin"].astype(np.int64)
        out["close"] = out["close"].astype(np.int64)
        out["side"] = out["side"].astype(np.int64)
        out["i0"] = out["i0"].astype(np.int64)
        out["best"] = out["best"].astype(np.bool_)
        out["tp_idx"] = (self.cst[out["coin"]] + out["i0"]) if len(order) else np.zeros(0, np.int64)
        self._off[period] = out
        return out

    def targets(self, off: dict) -> np.ndarray:
        """F11's per-signal target price (NaN none): the pick's target array at the signal bar, by side."""
        ix = off["tp_idx"]
        return np.where(off["side"] > 0, self.b_tl[ix], self.b_ts[ix]) if len(ix) else np.zeros(0)


# ------------------------------------------------------------------ test T3: the last 50 chart bars before a cut
def snapshot(provider, market: Market, cut_ms: int, picks_list: list, n_last: int = 50, widths=(2, 3, 5), emas=(10, 20, 50)) -> dict:
    """The arrays test T3 compares between cut and full data: for every coin and timeframe the last ``n_last`` chart bars
    that close at or before ``cut_ms``: close ms, OHLC, ATR14, EMA(10, 20, 50), the swing flags with their confirmation bar
    (bars whose swing is not confirmed by the last bar read -1), the starting references of F1, F1's reference path from
    each of these bars to the last bar (long and short), the 15m bars, and for every pick its two signal flags and its two
    leverage groups on those bars. Returned as a flat dict of numpy arrays."""
    out = {}
    for sym in market.symbols:
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
        for c, sym in enumerate(market.symbols):
            df, close = provider.frame(sym, p["tf"])
            close = np.asarray(close, np.int64)
            i_last = int(np.searchsorted(close, cut_ms, side="right")) - 1
            idx = np.arange(max(0, i_last - n_last + 1), i_last + 1)
            lo, sh = provider.signals(p, sym)
            bl, bs = provider.best(p, sym)
            key = f"{p['id']}|{sym}|"
            out[key + "close_ms"] = close[idx]
            out[key + "sig_long"], out[key + "sig_short"] = np.asarray(lo, bool)[idx], np.asarray(sh, bool)[idx]
            out[key + "best_long"], out[key + "best_short"] = np.asarray(bl, bool)[idx], np.asarray(bs, bool)[idx]
    return out


def snapshot_equal(a: dict, b: dict) -> list:
    """Names of the arrays that differ between two snapshots (empty = equal); NaNs compare equal."""
    bad = [k for k in sorted(set(a) | set(b)) if k not in a or k not in b or a[k].shape != b[k].shape
           or not np.array_equal(a[k], b[k], equal_nan=True)]
    return bad
