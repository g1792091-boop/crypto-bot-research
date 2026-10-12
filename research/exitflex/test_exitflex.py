"""Tests T1-T5 of PREREG_EXITFLEX.md section 13 on SYNTHETIC data (seeded random walks and hand-built price paths).

    python -m pytest -q research/exitflex/test_exitflex.py

They print nothing but pass / fail and counts of cases, and use no real market price, so they carry no performance figure.
The real-data variants of T1, T3 and T5 are stages of runner_x.py (``check``); this file also tests that code on
synthetic series.

Layout
  harness   synthetic coins, a data folder, a provider (chart bars through run.build_frame, simple causal signals), a
            hand-built path builder, and ``ref_trade`` / ``ref_account``: a plain-Python, stateless re-implementation of
            sections 4-6 (it recomputes every rule input from the raw bars at each check) that the numba kernel is
            compared with.
  T1        parity with kernel._trade / kernel.account with every rule off.
  T2        every family on hand-built paths, the 5.4 edge cases, the q15 mapping, differential tests against ref_trade.
  T3        cut data against full data at several cut times (the two sides in fresh processes).
  T4        placebo: h = 0 and h = 1, reproducible draws, hand-computed hazard tables, frozen stratum.
  T5        causality of decisions: changing minute j and later, and the chart bars after the check, changes nothing at j.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, ROOT, os.path.join(ROOT, "research", "fullgrid")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import data_x as DX  # noqa: E402
import kernel_x as KX  # noqa: E402
import metrics as MT  # noqa: E402
import placebo as PL  # noqa: E402
from paperbot import ladder as LD  # noqa: E402  (the engine's stepped lock: the reference and the F13 tests read it, not the kernel)

K = KX.K
MIN = 60_000
HOUR = 3_600_000
R = DX.fg()
SYMS = DX.SYMBOLS
EX = R.exchange(DX.EXCHANGE, False)


# ====================================================================================================== harness
def synth_coin(seed, n_days=40, price0=100.0, vol=0.0012, drop=0.004, start_ms=DX.PERIOD_MS["select"][0], jump_p=0.002,
               funding=True, open_gap_p=0.0, outages=0):
    """A seeded random walk of 1m bars: gaps (missing minutes, and ``outages`` runs of 15-120 missing minutes), jumps, open
    gaps (an open far from the previous close), a mark price that differs from the last price and 8-hourly funding, in the
    layout of data.py's npz."""
    rng = np.random.default_rng(seed)
    n = int(n_days * 1440)
    ts = start_ms + np.arange(n, dtype=np.int64) * MIN
    ret = rng.normal(0, vol, n)
    ret = np.where(rng.random(n) < jump_p, rng.normal(0, 10 * vol, n), ret)
    c = price0 * np.exp(np.cumsum(ret))
    o = np.r_[price0, c[:-1]]
    if open_gap_p:
        o = np.where(rng.random(n) < open_gap_p, o * (1 + rng.normal(0, 0.05, n)), o)
    span = np.abs(rng.normal(0, vol, n))
    h, lo = np.maximum(o, c) * (1 + span), np.minimum(o, c) * (1 - span)
    mo, mc = o * (1 + rng.normal(0, 1e-4, n)), c * (1 + rng.normal(0, 1e-4, n))
    mh = np.maximum.reduce([mo, mc, h * (1 + rng.normal(0, 1e-4, n))])
    ml = np.minimum.reduce([mo, mc, lo * (1 + rng.normal(0, 1e-4, n))])
    fund = np.zeros(n)
    if funding:
        fm = (ts // MIN) % 480 == 0
        fund[fm] = rng.normal(1e-4, 8e-5, int(fm.sum()))
    v = rng.uniform(1, 5, n)
    keep = rng.random(n) > drop
    for _ in range(outages):
        a = int(rng.integers(500, n - 500))
        keep[a:a + int(rng.integers(15, 120))] = False
    keep[0] = True
    return {"ts": ts[keep], "o": o[keep], "h": h[keep], "l": lo[keep], "c": c[keep], "v": v[keep], "mo": mo[keep],
            "mh": mh[keep], "ml": ml[keep], "mc": mc[keep], "fund": fund[keep]}


def write_folder(path, coins: dict):
    os.makedirs(os.path.join(path, "1m"), exist_ok=True)
    for sym, d in coins.items():
        np.savez(os.path.join(path, "1m", f"{sym}.npz"), **d)
    return path


def path_coin(segments, p0=100.0, start_ms=DX.PERIOD_MS["select"][0], gaps=(), spread=0.0, fund_at=None, opens=None,
              highs=None, lows=None):
    """A hand-built path: ``segments`` = [(minutes, target price), ...] linear in the last price from the previous
    close; open = the previous close; high / low = the extremes of open and close widened by ``spread``. ``gaps`` = minute
    offsets to delete. ``fund_at`` = {minute offset: funding rate}. ``opens`` / ``highs`` / ``lows`` = {minute offset: price}
    overrides (an open gap, a spike up, a spike down). Mark = last price."""
    cl, prev = [], p0
    for n, tgt in segments:
        for k in range(1, n + 1):
            cl.append(prev + (tgt - prev) * k / n)
        prev = tgt
    cl = np.array(cl)
    n = len(cl)
    o = np.r_[p0, cl[:-1]]
    for m, v in (opens or {}).items():
        o[m] = v
    h, lo = np.maximum(o, cl) + spread, np.minimum(o, cl) - spread
    for m, v in (highs or {}).items():
        h[m] = max(h[m], v)
    for m, v in (lows or {}).items():
        lo[m] = min(lo[m], v)
    ts = start_ms + np.arange(n, dtype=np.int64) * MIN
    fund = np.zeros(n)
    for k, r in (fund_at or {}).items():
        fund[k] = r
    keep = np.ones(n, bool)
    for g in gaps:
        keep[g] = False
    d = {"ts": ts, "o": o, "h": h, "l": lo, "c": cl, "v": np.ones(n), "mo": o.copy(), "mh": h.copy(), "ml": lo.copy(),
         "mc": cl.copy(), "fund": fund}
    return {k: v[keep] for k, v in d.items()}


def filler(coin_like, n_minutes=0):
    """A flat, quiet coin that spans the same minutes (for the other coins of a one-coin test)."""
    n = len(coin_like["ts"])
    ts = coin_like["ts"].copy()
    z = np.full(n, 100.0)
    return {"ts": ts, "o": z.copy(), "h": z.copy(), "l": z.copy(), "c": z.copy(), "v": np.ones(n), "mo": z.copy(), "mh": z.copy(),
            "ml": z.copy(), "mc": z.copy(), "fund": np.zeros(n)}


class Prov:
    """A provider with the real chart bars (run.build_frame on a data folder) and test signals: ``sig`` maps (sym) to a
    function (df) -> (long flags, short flags); ``atr_const`` / ``ema_fn`` override the indicators; period ids as the
    study's (the first 300 bars of a coin are warm-up) unless ``warm`` is False."""

    def __init__(self, data_dir, symbols, sig=None, atr_const=None, ema_fn=None, best_fn=None, warm=True):
        self.data_dir, self.symbols, self.sig, self.atr_const, self.ema_fn = data_dir, symbols, sig, atr_const, ema_fn
        self.best_fn, self.warm = best_fn, warm
        self._fr = {}

    def frame(self, sym, tf):
        if (sym, tf) not in self._fr:
            self._fr[(sym, tf)] = R.build_frame(self.data_dir, sym, tf)
        return self._fr[(sym, tf)]

    def signals(self, pick, sym):
        df, _ = self.frame(sym, pick["tf"])
        if self.sig is not None:
            lo, sh = self.sig(sym, df)
            return np.asarray(lo, bool), np.asarray(sh, bool)
        import pandas as pd
        f, s = df["close"].ewm(span=5, adjust=False).mean(), df["close"].ewm(span=20, adjust=False).mean()
        up = (f > s) & (f.shift(1) <= s.shift(1))
        dn = (f < s) & (f.shift(1) >= s.shift(1))
        return up.to_numpy(bool), dn.to_numpy(bool)

    def best(self, pick, sym):
        df, _ = self.frame(sym, pick["tf"])
        if self.best_fn is not None:
            return self.best_fn(sym, df)
        r = ((df["high"] - df["low"]) / df["close"]).to_numpy(float)
        return r > 0.002, r > 0.003

    def atr(self, df):
        if self.atr_const is not None:
            return np.full(len(df), float(self.atr_const))
        return R._vendor_fg().atr(df, 14).to_numpy(float)

    def ema(self, df, n):
        if self.ema_fn is not None:
            return np.asarray(self.ema_fn(df, n), float)
        return R._vendor_fg().ema(df["close"], n).to_numpy(float)

    def period_ids(self, close_ms):
        pid = np.full(len(close_ms), -1, np.int8)
        for k, (lo, hi) in enumerate((DX.PERIOD_MS["select"], DX.PERIOD_MS["confirm"])):
            pid[(close_ms >= lo) & (close_ms < hi)] = k
        if self.warm:
            pid[:DX.WARMUP_BARS] = -1
        return pid


def make_pick(tf="1h", exit_name="tp3R|4", name="SYN"):
    return {"id": f"core-{name}-{tf}-1", "kind": "core", "name": name, "tf": tf, "combo": {}, "exit": exit_name,
            "exit_index": [e[0] for e in K.EXITS].index(exit_name), "rank": 1}


@pytest.fixture(scope="module", autouse=True)
def _clean_temp(tmp_path_factory):
    """Disk is tight: remove the test folders (synthetic data folders, cut folders) when the module is done."""
    yield
    import shutil
    shutil.rmtree(str(tmp_path_factory.getbasetemp()), ignore_errors=True)


@pytest.fixture(scope="module")
def vendor():
    from paperbot import sweepsig
    sweepsig.lib()
    return True


def build_world(coins: dict, tmp, prov_kw=None, pick=None, f11=None, strict_flags=True):
    """Market + provider + PickData for a dict of coins {sym: arrays} (the first ones of SYMBOLS)."""
    syms = tuple(coins)
    assert syms == SYMS[:len(syms)]
    folder = write_folder(str(tmp), coins)
    prov = Prov(folder, syms, **(prov_kw or {}))
    mk = DX.Market.from_arrays([coins[s] for s in syms], EX, symbols=syms)
    pick = pick or make_pick()
    pd_ = DX.PickData(mk, pick, prov, f11=f11, strict_flags=strict_flags)
    return mk, prov, pd_


# ----------------------------------------------------------------------------------- the reference simulator
def entry_index_py(ts, close):
    j0 = int(np.searchsorted(ts, close - MIN, side="left"))
    return -1 if j0 + 1 >= len(ts) else j0 + 1


class RefChart:
    """The raw per-bar lists of one coin's pick-timeframe bars (and 15m bars), straight from the frames."""

    def __init__(self, pdata, c, ema_n=None):
        a, b = pdata.cst[c], pdata.cen[c]
        self.cms = list(pdata.b_cms[a:b].astype(np.int64))
        self.cl, self.hi, self.lo = list(pdata.b_cl[a:b]), list(pdata.b_hi[a:b]), list(pdata.b_lo[a:b])
        self.atr = list(pdata.b_atr[a:b])
        self.sigl, self.sigs = list(pdata.b_sl[a:b]), list(pdata.b_ss[a:b])
        self.comp = pdata.b_comp[a:b].copy()                 # F11 component values (0 false, 1 true, 2 NaN), long then short
        self.ckind = pdata.ckind.copy()
        self.ema = {}
        self.pdata, self.c = pdata, c
        self.ts = pdata.market.ts(c)
        self.minute = [entry_index_py(self.ts, int(x)) for x in self.cms]       # independent of PickData
        n = len(self.cl)
        self.n = n

    def ema_of(self, n):
        if n not in self.ema:
            a, b = self.pdata.cst[self.c], self.pdata.cen[self.c]
            self.ema[n] = list(self.pdata.ema(n)[a:b])
        return self.ema[n]

    def swing_low(self, p, w):
        if p < w or p + w >= self.n:
            return False
        return all(self.lo[p] < self.lo[q] for q in range(p - w, p + w + 1) if q != p)

    def swing_high(self, p, w):
        if p < w or p + w >= self.n:
            return False
        return all(self.hi[p] > self.hi[q] for q in range(p - w, p + w + 1) if q != p)

    def start_ref(self, i0, w, side):
        """kernel.structure_levels at i0, written out: long = highest swing low below the close, short = lowest swing
        high above it, among swings at p in [i0 - 300, i0 - w]."""
        best = None
        for p in range(max(0, i0 - 300), i0 - w + 1):
            if side > 0 and self.swing_low(p, w) and self.lo[p] < self.cl[i0]:
                best = self.lo[p] if best is None or self.lo[p] > best else best
            if side < 0 and self.swing_high(p, w) and self.hi[p] > self.cl[i0]:
                best = self.hi[p] if best is None or self.hi[p] < best else best
        return best

    def ref_at(self, i0, bi, w, side):
        ref = self.start_ref(i0, w, side)
        for i in range(i0 + 1, bi + 1):
            p = i - w
            if p < 0:
                continue
            if side > 0 and self.swing_low(p, w) and (ref is None or self.lo[p] > ref):
                ref = self.lo[p]
            if side < 0 and self.swing_high(p, w) and (ref is None or self.hi[p] < ref):
                ref = self.hi[p]
        return ref


def pdata_zflag(ch, bi, side) -> bool:
    """F11's own 'can fire at this bar' flag of the chart bar bi (default 1)."""
    arr = ch.pdata.b_zl if side > 0 else ch.pdata.b_zs
    return bool(arr[ch.pdata.cst[ch.c] + bi] != 0)


def ref_trade(S, br, ts, o, h, l, mo, mh, ml, fund, e, end, side, stop_dist, atr, best, equity, qty_step, min_notional,
              tp_kind, tp_val, tp_price, force_end, v, ch, i0, tf_ms, q15, q15bars=None, plc=None, seed_base=0, coin=0,
              hz=None, lvl=float("nan"), lock=(False, 0.10, 0.05, 0.02)):
    """Sections 4-6 in plain Python, stateless: every rule input is recomputed from the raw bars at each check. The stepped lock
    (``lock`` = (on, first lock, step, gap); the picks use none, F13 does) is written with the engine's own paperbot/ladder.py
    (LadderSpec, net_roe, roe_price, tighten), not with the kernel's inline formulas. Returns (d, j, reason, lev, price,
    [per-check records])."""
    taker, slip, rt, maker = S[0], S[1], S[5], S[19]
    raw = o[e]
    fill = raw * (1 + side * slip)
    stop = raw - side * stop_dist
    ok, lev, margin, qty, liq = K._size.py_func(S, br, equity, side, fill, stop, atr, best, qty_step, min_notional)
    if not ok:
        return 0.0, e, KX.R_REJECT, 0, 0.0, []
    has_tp = tp_kind != KX.TP_NONE
    if tp_kind == KX.TP_R:
        tp = raw + side * tp_val * stop_dist
    elif tp_kind == KX.TP_STRUCT:
        tp = tp_price
        has_tp = np.isfinite(tp_price) and (tp_price - fill) * side > 0
    else:
        tp = fill * (1.0 + side * (tp_val / lev + rt))
    notional = qty * fill
    wallet = equity - notional * taker
    kb = K._bracket.py_func(br, qty * fill)
    fam = v.fam
    prm = v.params
    ruled = fam not in (KX.F_NONE, KX.F13)                     # F13 (the stepped lock) makes no decision at a chart close
    spec_ = LD.LadderSpec(first_lock=lock[1], step=lock[2], trigger_gap=lock[3])
    lock_roe = None
    # ---- the check schedule: (minute, last schedule bar), merged when minutes coincide
    checks = []
    if ruled:
        if q15:
            bars = [(k, m) for k, m in enumerate(zip(q15bars["cms"], q15bars["minute"])) if m[0] > ch.cms[i0]]
            sched = [(k, m[1]) for k, m in bars]
        else:
            sched = [(i, ch.minute[i]) for i in range(i0 + 1, ch.n)]
        for idx, m in sched:
            if m < 0:
                break
            jj = max(int(m), e + 1)
            if checks and checks[-1][0] == jj:
                checks[-1] = (jj, idx)
            else:
                checks.append((jj, idx))
    by_j = {jj: (n + 1, last) for n, (jj, last) in enumerate(checks)}
    cache = {}
    records = []

    def state_at(j):
        """X, T_X over minutes e .. j-1 and the funding paid before j (all recomputed)."""
        X, TX = fill, ts[e]
        for t in range(e, j):
            if side > 0 and h[t] > X:
                X, TX = h[t], ts[t]
            if side < 0 and l[t] < X:
                X, TX = l[t], ts[t]
        fp = 0.0
        for t in range(e + 1, j):
            if fund[t] != 0.0:
                fp += side * qty * mo[t] * fund[t]
        return X, TX, fp

    def rn(P, fp):
        return (side * (P - fill) - fill * (rt + fp / notional)) / stop_dist

    def check_info(kk):
        if kk in cache:
            return cache[kk]
        jj, last = checks[kk - 1]
        X, TX, fp = state_at(jj)
        if q15:
            cc, px, bi = q15bars["cms"][last], q15bars["cl"][last], int(q15bars["pt"][last])
        else:
            bi, cc, px = last, ch.cms[last], ch.cl[last]
        bi = max(bi, i0)
        rc, rpk = rn(px, fp), rn(X, fp)
        cache[kk] = dict(j=jj, last=last, X=X, TX=TX, fp=fp, bi=bi, cc=int(cc), px=px, rc=rc, rpk=rpk)
        return cache[kk]

    def armed_at(kk, P):
        return any(check_info(m)["rpk"] >= P for m in range(1, kk + 1))

    def evaluate(kk):
        ci = check_info(kk)
        bi, px, rc, rpk, X = ci["bi"], ci["px"], ci["rc"], ci["rpk"], ci["X"]
        P12 = KX.F12_PARAMS

        def pm(name, default=0):
            return P12[name] if fam == KX.F12 else prm.get(name, default)

        def prev_bi():
            return i0 if kk == 1 else check_info(kk - 1)["bi"]

        def c_ref(w):
            ref = ch.ref_at(i0, bi, w, side)
            return ref, (ref is not None and side * (ref - px) > 0)

        def c_ema(n):
            em = ch.ema_of(n)
            before = side * (ch.cl[i0] - em[i0]) > 0 or any(side * (ch.cl[i] - em[i]) > 0 for i in range(i0 + 1, bi))
            return before, bool(before and side * (em[bi] - ch.cl[bi]) > 0)

        def c_f3():
            flags = ch.sigs if side > 0 else ch.sigl
            return any(flags[i] for i in range(prev_bi() + 1, bi + 1))

        def c_f11():
            base_c = 0 if side > 0 else KX.NC
            fire = False
            for i in range(prev_bi() + 1, bi + 1):
                for c in range(KX.NC):
                    kd = ch.ckind[base_c + c]
                    val = ch.comp[i, base_c + c]
                    if kd == KX.CK_NONE or val == 2:
                        continue
                    if kd == KX.CK_EVENT:
                        fire = fire or val == 1
                    elif val == 1 and any(ch.comp[t, base_c + c] == 0 for t in range(i0, i)):
                        fire = True
                if not math.isnan(lvl) and not math.isnan(ch.cl[i]) and side * (lvl - ch.cl[i]) > 0:
                    if any((not math.isnan(ch.cl[t])) and side * (lvl - ch.cl[t]) <= 0 for t in range(i0, i)):
                        fire = True
            # the precondition: a finite level, an event component, or a state component armed before the check bar
            zf = not math.isnan(lvl)
            for c in range(KX.NC):
                kd = ch.ckind[base_c + c]
                if kd == KX.CK_EVENT or (kd == KX.CK_STATE and any(ch.comp[t, base_c + c] == 0 for t in range(i0, bi))):
                    zf = True
            zflag = pdata_zflag(ch, bi, side)
            return fire, bool(zf and zflag)

        def c_f4(m):
            return side * ((X - side * m * ch.atr[bi]) - px) > 0

        def c_f10(N):
            return rc > 0 and ci["cc"] - ci["TX"] >= N * tf_ms

        armed15 = lambda P: armed_at(kk, P)   # noqa: E731
        fire, z, comp = False, 0, 0
        armed, ema_before, ref_out = False, False, None
        if fam == KX.F1:
            ref_out, brk = c_ref(prm["w"])
            fire, z = brk, ref_out is not None
        elif fam == KX.F2:
            ema_before, fire = c_ema(prm["n"])
            z = ema_before
        elif fam == KX.F3:
            fire = c_f3()
        elif fam == KX.F11:
            fire, z = c_f11()
        elif fam == KX.F4:
            fire = c_f4(prm["m"])
        elif fam == KX.F5:
            armed = armed15(prm["P"])
            fire, z = armed and rc <= (1 - prm["g"]) * rpk, armed
        elif fam == KX.F6:
            ref_out, brk = c_ref(prm["w"])
            fire, z = brk and rc < -prm["d"], ref_out is not None and rc < -prm["d"]
        elif fam == KX.F7:
            fire = ci["cc"] >= ch.cms[i0] + prm["N"] * tf_ms
        elif fam == KX.F7H:
            fire = ci["cc"] >= ch.cms[i0] + prm["H"] * 3_600_000
        elif fam == KX.F8:
            ref_out, brk = c_ref(prm["w"])
            armed = armed15(prm["P"])
            fire, z = armed and brk, armed and ref_out is not None
        elif fam == KX.F9:
            ref_out, brk = c_ref(prm["w"])
            armed = armed15(prm["P"])
            fire, z = brk and (armed or rc < -prm["d"]), ref_out is not None and (armed or rc < -prm["d"])
        elif fam == KX.F10:
            fire = c_f10(prm["N"])
        elif fam == KX.F12:
            ref_out, brk = c_ref(P12["w"])
            ema_before, e_fire = c_ema(P12["n"])
            armed = armed15(P12["P"])
            f11_fire, z11 = c_f11()
            bits = {KX.CB_F1: brk, KX.CB_F2: e_fire, KX.CB_F3: c_f3(), KX.CB_F4: c_f4(P12["m"]),
                    KX.CB_F5: armed and rc <= (1 - P12["g"]) * rpk, KX.CB_F6: brk and rc < -P12["d"],
                    KX.CB_F7H: ci["cc"] >= ch.cms[i0] + P12["H"] * 3_600_000, KX.CB_F10: c_f10(P12["N"]), KX.CB_F11: f11_fire}
            comp = sum(b for b, on in bits.items() if on)
            fire = comp != 0
            z = ref_out is not None or ema_before or armed or z11
        else:
            raise AssertionError(fam)
        a = PL.age_bucket_py(kk)
        s = 1 if rc >= 0 else 0
        clock = fam == KX.F12 and ci["cc"] >= ch.cms[i0] + P12["H"] * 3_600_000          # F12's own 8-hour clock check (prereg 6)
        return bool(fire), (a, s, int(bool(z))), dict(ref=ref_out, armed=bool(armed), ema_before=bool(ema_before), comp=comp, clock=bool(clock), **ci)

    mfe = fill
    fpaid = 0.0
    for j in range(e, end):
        entry_bar = j == e
        fire = False
        info = None
        if ruled and not entry_bar and j in by_j:
            kk, _last = by_j[j]
            rule_fire, strat, info = evaluate(kk)
            fire = rule_fire
            if plc:
                if info["clock"]:
                    fire = True                                    # probability 1 at the clock check, no draw
                else:
                    u = PL.draw_u_py(seed_base, coin, info["cc"])
                    fire = u < hz[strat]
            info["fire"] = fire
            info["rule_fire"] = rule_fire
            info["strat"] = strat
            info["k"] = kk
        if not entry_bar and fund[j] != 0.0:
            pay = side * qty * mo[j] * fund[j]
            wallet -= pay
            margin -= pay
            fpaid += pay
            liq = K._liq.py_func(side, qty, fill, margin, br[kb, 2], br[kb, 3])
        if side > 0:
            mfe = max(mfe, h[j])
        else:
            mfe = min(mfe, l[j])
        price, liquidate, at_tp, code = -1.0, False, False, None
        if not entry_bar:
            if (mo[j] - liq) * side <= 0:
                liquidate = True
            elif (o[j] - stop) * side <= 0:
                price = o[j] * (1 - side * slip)
            elif has_tp and (o[j] - tp) * side > 0:
                price, at_tp = o[j], True
            if info is not None:
                info["survived"] = (not liquidate) and price < 0
                records.append(info)
            if not liquidate and price < 0:
                if fire:
                    price, code = o[j] * (1 - side * slip), (KX.R_RAND if plc else KX.R_RULE)
                elif force_end and j == end - 1:
                    price, code = o[j] * (1 - side * slip), KX.R_END
        if not liquidate and price < 0:
            hit_stop = (l[j] <= stop) if side > 0 else (h[j] >= stop)
            hit_tp = has_tp and ((h[j] > tp) if side > 0 else (l[j] < tp))
            hit_liq = (ml[j] <= liq) if side > 0 else (mh[j] >= liq)
            if hit_stop:
                price = stop * (1 - side * slip)
            elif hit_liq:
                liquidate = True
            elif hit_tp:
                price, at_tp = tp, True
            elif lock[0] and not entry_bar:                  # the stepped lock: from the next minute, only tightens (paperbot/ladder.py)
                fr = fpaid / notional
                armed_roe = spec_.lock_for(LD.net_roe(side, fill, mfe, lev, rt, fr))
                if armed_roe is not None and (lock_roe is None or armed_roe > lock_roe + 1e-12):
                    stop = LD.tighten(side, stop, LD.roe_price(side, fill, lev, armed_roe, rt, fr))
                    lock_roe = armed_roe
        if price >= 0:
            gross = side * qty * (price - fill)
            if gross < -margin:
                liquidate = True
            else:
                wallet += gross - qty * price * (maker if at_tp else taker)
                rc_ = KX.R_TP if at_tp else (code if code is not None else (KX.R_LOCK if lock_roe is not None else KX.R_SL))
                return wallet - equity, j, rc_, lev, price, records
        if liquidate:
            wallet -= margin
            return wallet - equity, j, KX.R_LIQ, lev, 0.0, records
    return wallet - equity, end - 1, KX.R_OPEN, lev, 0.0, records


def ref_q15(prov, pdata, c):
    """The 15m bars of coin c for the reference: close ms, close, minute index (independent), latest pick bar closed."""
    sym = pdata.market.symbols[c]
    df, close = prov.frame(sym, "15m")
    close = np.asarray(close, np.int64)
    ts = pdata.market.ts(c)
    pcl = np.asarray(pdata.frames[c][1], np.int64)
    return {"cms": list(close), "cl": list(df["close"].to_numpy(float)),
            "minute": [entry_index_py(ts, int(x)) for x in close],
            "pt": [int(np.searchsorted(pcl, x, side="right")) - 1 for x in close]}


def trade_args(mk, pdata, v, off, q, scale=0.25, period="select", force_end=True):
    """The arguments of one _trade_x call for offered signal q (what account_x passes), plus its pieces."""
    c = int(off["coin"][q])
    a, b = int(mk.starts[c]), int(mk.period_end(period)[c]) if force_end else int(mk.ends[c])
    tsc = mk.cat["ts"][a:b]
    e = K._entry_index(tsc, off["close"][q])
    stop_atr, tp_kind, tp_val, ladder, fl, step, gap = KX.exit_of_pick(pdata.pick, v)
    return dict(c=c, a=a, b=b, tsc=tsc, e=int(e), side=int(off["side"][q]), atr=float(off["atr"][q]), best=bool(off["best"][q]),
                stop_atr=stop_atr, tp_kind=tp_kind, tp_val=tp_val, ladder=ladder, fl=fl, step=step, gap=gap, S=mk.S(scale),
                i0=int(off["i0"][q]))


def call_trade_x(mk, pdata, v, off, q, scale=0.25, force_end=True, plc=False, hz=None, seed=0, trace_rows=0, equity=5000.0,
                 tp_price=np.nan, period="select"):
    if v.fam in (KX.F11, KX.F12) and v.mode == "b":
        tp_price = float(pdata.targets(off)[q])
    return KX.simulate_trade(mk, pdata, v, off, q, scale, period, force_end, plc, hz, seed, trace_rows, equity, tp_price)


def call_ref(mk, prov, pdata, v, off, q, scale=0.25, force_end=True, plc=False, hz=None, seed=0, equity=5000.0,
             tp_price=np.nan, period="select"):
    t = trade_args(mk, pdata, v, off, q, scale, period, force_end)
    if v.fam in (KX.F11, KX.F12) and v.mode == "b":
        tp_price = float(pdata.targets(off)[q])
    c, a, b = t["c"], t["a"], t["b"]
    ch = RefChart(pdata, c)
    q15 = bool(v.q15) and pdata.tf in ("1h", "4h")
    q15bars = ref_q15(prov, pdata, c) if q15 else None
    if v.fam in (KX.F2, KX.F12):
        ch.ema_of(KX.F12_PARAMS["n"] if v.fam == KX.F12 else v.params["n"])
    hzd = None
    if plc:
        hzd = {(i, j, k): hz[i, j, k] for i in range(KX.N_AGE) for j in range(2) for k in range(2)}
    return ref_trade(t["S"], mk.brs[c], t["tsc"], mk.cat["o"][a:b], mk.cat["h"][a:b], mk.cat["l"][a:b], mk.cat["mo"][a:b],
                     mk.cat["mh"][a:b], mk.cat["ml"][a:b], mk.cat["fund"][a:b], t["e"], b - a, t["side"],
                     t["stop_atr"] * t["atr"], t["atr"], t["best"], equity, mk.qty_steps[c], mk.min_notionals[c], t["tp_kind"],
                     t["tp_val"], tp_price, force_end, v, ch, t["i0"], pdata.tf_ms, q15, q15bars, plc, seed, c, hzd,
                     float(off["lvl"][q]) if v.fam in (KX.F11, KX.F12) else float("nan"), (t["ladder"], t["fl"], t["step"], t["gap"]))


def compare_trade(mk, prov, pdata, v, off, q, **kw):
    """Run both and return a list of mismatch strings (empty = identical, including every check's frozen decision state)."""
    out, num, den, trace = call_trade_x(mk, pdata, v, off, q, trace_rows=2000, **kw)
    rd, rj, rr, rl, rp_, rrec = call_ref(mk, prov, pdata, v, off, q, **{k: val for k, val in kw.items() if k != "trace_rows"})
    bad = []
    d, j, r, lev, px, nk, both, cm = out
    if not (abs(d - rd) <= 1e-9 * max(1.0, abs(rd)) and j == rj and r == rr and lev == rl and abs(px - rp_) <= 1e-9 * max(1.0, abs(rp_))):
        bad.append(f"trade: kernel {(d, j, r, lev, px)} ref {(rd, rj, rr, rl, rp_)}")
    want_cm = int(rrec[-1]["comp"]) if (rr == KX.R_RULE and rrec) else 0
    if cm != want_cm:
        bad.append(f"component mask: kernel {cm} ref {want_cm}")
    rnum, rden = np.zeros((KX.N_AGE, 2, 2), np.int64), np.zeros((KX.N_AGE, 2, 2), np.int64)   # the hazard counts, from the reference's records
    for rec in rrec:
        if rec.get("survived") and not rec["clock"]:
            rden[rec["strat"]] += 1
            rnum[rec["strat"]] += int(rec["fire"])
    if not (np.array_equal(num, rnum) and np.array_equal(den, rden)):
        bad.append("hazard counts differ")
    for rec in rrec:                                        # every check that the position lived to see
        kk = rec["k"]
        row = trace[kk - 1]
        mine = (int(row[0]), int(row[2]), int(row[3]), int(row[4]), int(row[5]), int(row[11]))
        want = (rec["j"], int(rec["rule_fire"]), *rec["strat"], int(rec["fire"]))
        if mine != want:
            bad.append(f"check {kk}: kernel {mine} ref {want}")
        if rec["ref"] is not None and not (math.isnan(row[7]) and False) and abs(row[7] - rec["ref"]) > 1e-9 * max(1, abs(rec["ref"])):
            bad.append(f"check {kk}: ref level kernel {row[7]} ref {rec['ref']}")
    return bad


# ====================================================================================================== scenarios
START = DX.PERIOD_MS["select"][0]
FILL_SLIP = 0.0002


def mirror(segments, p0):
    """The mirror image of a hand-built path around 100 (long scenarios become short ones)."""
    return [(n, 200.0 - t) for n, t in segments], 200.0 - p0


def hours(*knots, p0=100.0, hour=60):
    """Segments that end hour b at knots[b] (linear inside the hour)."""
    return [(hour, k) for k in knots], p0


def pad_to(segments, minutes_multiple=240, extra_hours=6, price=None, hour=60):
    n = sum(m for m, _ in segments)
    last = segments[-1][1] if price is None else price
    out = list(segments) + [(hour * extra_hours, last)]
    n += hour * extra_hours
    rest = (-n) % minutes_multiple
    if rest:
        out.append((rest, last))
    return out


class Scen:
    """A one-coin world with hand-built prices and signals; the pick's timeframe tf; ATR14 = ``atr`` on every bar."""

    def __init__(self, tmp, segments, p0=100.0, tf="1h", exit_name="tp3R|4", longs=(), shorts=(), atr=0.3, ema=None, gaps=(),
                 fund_at=None, best=False, scale=0.25, sig_fn=None, side_mirror=False, opens=None, highs=None, lows=None,
                 pad=True, f11=None, strict_flags=True):
        if side_mirror:
            segments, p0 = mirror(segments, p0)
            longs, shorts = shorts, longs
            if ema is not None:
                ema = 200.0 - np.asarray(ema, float)
            opens = {m: 200.0 - v for m, v in (opens or {}).items()}
            highs, lows = ({m: 200.0 - v for m, v in (lows or {}).items()}, {m: 200.0 - v for m, v in (highs or {}).items()})
        seg = pad_to(segments, {"15m": 15, "30m": 30, "1h": 60, "4h": 240}[tf]) if pad else list(segments)
        self.coin = path_coin(seg, p0, gaps=gaps, fund_at=fund_at, opens=opens, highs=highs, lows=lows)
        self.p0 = p0
        lb, sb = set(longs), set(shorts)

        def sig(sym, df, lb=lb, sb=sb):
            n = len(df)
            a, b = np.zeros(n, bool), np.zeros(n, bool)
            for i in lb:
                a[i] = True
            for i in sb:
                b[i] = True
            return a, b
        ema_fn = None
        if ema is not None:
            ema_arr = np.asarray(ema, float)
            ema_fn = lambda df, n, ea=ema_arr: np.resize(ea, len(df)) if len(ea) < len(df) else ea[:len(df)]  # noqa: E731
        self.mk, self.prov, self.pd = build_world({"BTCUSDT": self.coin}, tmp, pick=make_pick(tf, exit_name),
                                                  prov_kw=dict(sig=sig_fn or sig, atr_const=atr, ema_fn=ema_fn, warm=False,
                                                               best_fn=(lambda s, df: (np.full(len(df), best), np.full(len(df), best)))),
                                                  f11=f11, strict_flags=strict_flags)
        self.scale = scale
        self.off = self.pd.offered("select", self.mk)

    def offset(self, ts_ms):
        return int((ts_ms - START) // MIN)

    def trade(self, vid, q=0, trace_rows=64, **kw):
        v = KX.variant_by_id(vid)
        out, num, den, trace = call_trade_x(self.mk, self.pd, v, self.off, q, scale=self.scale, trace_rows=trace_rows, **kw)
        j = out[1]
        return {"d": out[0], "j": j, "off": self.offset(self.mk.cat["ts"][j]), "reason": out[2], "lev": out[3], "px": out[4],
                "checks": out[5], "both": out[6], "comp": out[7], "num": num, "den": den, "trace": trace, "v": v}

    def account(self, vid, **kw):
        v = KX.variant_by_id(vid)
        r = KX.simulate(self.mk, self.pd, v, self.scale, "select", **kw)
        return r

    def open_at(self, offset):
        i = int(np.searchsorted(self.mk.cat["ts"], START + offset * MIN))
        return float(self.mk.cat["o"][i])


def expect_exit(s, t, offset, reason=KX.R_RULE, side=1):
    """The trade left at minute ``offset`` (minutes after the data start) by ``reason`` at that open with slippage."""
    assert t["reason"] == reason, (KX.REASON_NAMES[t["reason"]], t["off"])
    assert t["off"] == offset, (t["off"], offset)
    if reason in (KX.R_RULE, KX.R_RAND, KX.R_END):
        assert t["px"] == pytest.approx(s.open_at(offset) * (1 - side * FILL_SLIP), rel=1e-12)


def costs(S):
    return S[0], S[1], S[5], S[19]


# ====================================================================================================== T2: rule paths
MIR = [False, True]
H = lambda *knots: [(60, k) for k in knots]            # noqa: E731  hour b ends at knots[b]
FLAT = 100.0


def side_of(mir):
    return -1 if mir else 1


def last_offset(s):
    return s.offset(s.mk.cat["ts"][-1])


@pytest.mark.parametrize("mir", MIR)
def test_t2_f4_chandelier_level_and_timing(tmp_path, vendor, mir):
    seg = H(100, 100, 100, 101.0, 101.2, 100.6)
    s = Scen(tmp_path, seg, longs=[2], side_mirror=mir)
    assert len(s.off["coin"]) == 1 and s.off["side"][0] == side_of(mir)
    t = s.trade("F4.m1.5.a")                       # X = 101.2, level = 101.2 - 1.5 x 0.3 = 100.75; closes 101.0, 101.2, 100.6
    expect_exit(s, t, 360, side=side_of(mir))
    assert t["checks"] == 3 and t["trace"][2, 0] > 0
    assert t["trace"][0, 2] == 0 and t["trace"][1, 2] == 0 and t["trace"][2, 2] == 1      # not before the third check
    t = s.trade("F4.m3.a")                         # level 100.3: never reached; the hard stop and take-profit are far
    expect_exit(s, t, last_offset(s), KX.R_END, side=side_of(mir))
    # q15: the same drop inside an hour is seen at the first 15m close after it, levels still from the hour chart
    seg2 = H(100, 100, 100, 101.0, 101.2) + [(15, 100.6), (45, 100.6)]
    s2 = Scen(tmp_path / "q", seg2, longs=[2], side_mirror=mir)
    expect_exit(s2, s2.trade("F4.m1.5.a"), 360, side=side_of(mir))
    t = s2.trade("F4.m1.5.a.q15")
    expect_exit(s2, t, 315, side=side_of(mir))
    assert t["checks"] == 9


@pytest.mark.parametrize("mir", MIR)
def test_t2_f1_start_reference_ratchet_and_no_reference(tmp_path, vendor, mir):
    seg = ([(60, 100), (60, 100), (30, 99.5), (30, 100), (60, 101.0)] + H(101, 101, 101) + H(101, 101)
           + [(20, 100.7), (40, 101.0)] + H(101, 101) + H(101, 101) + [(20, 100.5), (40, 101.0)] + H(101, 101)
           + [(5, 100.65), (55, 100.65)])
    s = Scen(tmp_path, seg, longs=[6], side_mirror=mir)
    assert s.off["i0"][0] == 6
    sd = side_of(mir)
    t = s.trade("F1.w2.a")
    expect_exit(s, t, 1080, side=sd)                # 100.65 < 100.7: the swing at bar 9 raised the reference from 99.5
    tr = t["trace"]
    c = lambda x: 200.0 - x if mir else x             # noqa: E731
    assert tr[3, 7] == pytest.approx(c(99.5))         # k = 4 (bar 10): still the reference at entry (highest swing low)
    assert tr[4, 7] == pytest.approx(c(100.7))        # k = 5 (bar 11): the swing at bar 9 is confirmed and higher
    assert tr[9, 7] == pytest.approx(c(100.7))        # k = 10 (bar 16): a lower swing (100.5) does not lower it
    assert t["checks"] == 11
    t = s.trade("F1.w3.a")                            # no swing before entry; the swing at bar 9 is known at bar 12
    expect_exit(s, t, 1080, side=sd)
    t = s.trade("F1.w5.a")                            # no reference until bar 19: nothing to break
    expect_exit(s, t, last_offset(s), KX.R_END, side=sd)
    assert np.isnan(t["trace"][0, 7])


@pytest.mark.parametrize("mir", MIR)
def test_t2_f2_arm(tmp_path, vendor, mir):
    ema = np.full(40, 101.0)
    seg = H(100, 100, 100, 100.5, 100.6, 101.5, 100.8)
    s = Scen(tmp_path, seg, longs=[2], ema=ema, side_mirror=mir)
    t = s.trade("F2.n20.a")                           # bought below the average: closes below it do not fire until armed
    expect_exit(s, t, 420, side=side_of(mir))
    assert t["checks"] == 4
    ema2 = np.full(40, 99.0)
    s2 = Scen(tmp_path / "b", H(100, 100, 100, 98.9), longs=[2], ema=ema2, side_mirror=mir)
    expect_exit(s2, s2.trade("F2.n20.a"), 240, side=side_of(mir))      # armed at entry (above the average): first close below


def acct(s, vid, **kw):
    r = s.account(vid, **kw)
    out = []
    for q in range(len(r.status)):
        out.append(dict(status=int(r.status[q]), side=int(s.off["side"][q]), reason=int(r.reason[q]),
                        entry=s.offset(r.entry_ts[q]) if r.status[q] == 1 else None,
                        exit=s.offset(r.exit_ts[q]) if r.status[q] == 1 else None, bar=int(s.off["i0"][q])))
    return r, out


@pytest.mark.parametrize("mir", MIR)
def test_t2_f3_reversal_and_both_flags(tmp_path, vendor, mir):
    seg = H(100, 100, 100, 100.5, 100.8, 100.6, 100.0, 100.0)
    sd = side_of(mir)
    s = Scen(tmp_path, seg, longs=[2], shorts=[5], side_mirror=mir)
    r, a = acct(s, "F3.a")                            # the opposite signal closes the position and is entered at that open
    assert [x["status"] for x in a] == [1, 1]
    assert a[0]["reason"] == KX.R_RULE and a[0]["exit"] == 360 and a[1]["entry"] == 360
    assert a[0]["side"] == sd and a[1]["side"] == -sd
    assert MT.summarize(r, MT.month_edges("select"))["counts"][MT.COUNT_NAMES.index("entries_at_rule_minute")] == 1
    r, a = acct(s, "E0")                              # without the rule the second signal finds the account busy
    assert [x["status"] for x in a] == [1, 0]
    # both flags on one bar: the long is offered first
    s2 = Scen(tmp_path / "b", seg, longs=[2, 5], shorts=[5], side_mirror=mir, strict_flags=False)
    r, a = acct(s2, "F3.a")
    assert [x["status"] for x in a] == [1, 1, 0]
    assert a[0]["exit"] == 360 and a[0]["reason"] == KX.R_RULE and a[1]["entry"] == 360 and a[1]["side"] == 1
    assert a[2]["side"] == -1 and a[2]["bar"] == 5
    # the long that re-enters after a long closed is "no reversal"; after a short closed it is the reversal
    assert (a[0]["side"] == 1) == (not mir)


@pytest.mark.parametrize("mir", MIR)
def test_t2_f5_f8_arms_and_giveback_net_r(tmp_path, vendor, mir):
    seg = H(100, 100, 100, 101.5, 101.0, 100.7)
    s = Scen(tmp_path, seg, longs=[2], side_mirror=mir)
    sd = side_of(mir)
    S = s.mk.S(0.25)
    rt = S[5]
    raw = 100.0 if not mir else 100.0
    fill = raw * (1 + sd * FILL_SLIP)
    R_ = 4 * 0.3

    def rn(p):                                         # net R of the long path (the mirror has the same numbers)
        p = 200 - p if mir else p
        return (sd * (p - fill) - fill * rt) / R_
    P_hi = 101.5
    rpk, rc2, rc3 = rn(P_hi), rn(101.0), rn(100.7)
    assert rpk >= 1 and rc2 > 0.5 * rpk and rc3 <= 0.5 * rpk and rc2 <= 0.75 * rpk       # the hand-computed numbers
    t = s.trade("F5.P1.g50.a")                         # armed at the first close (Rpk 1.12 >= 1), fires at 0.45 <= 0.56
    expect_exit(s, t, 360, side=sd)
    assert t["trace"][0, 9] == pytest.approx(rpk) and t["trace"][1, 8] == pytest.approx(rc2) and t["trace"][2, 8] == pytest.approx(rc3)
    t = s.trade("F5.P1.g25.a")                         # keeps 75%: 0.70 <= 0.84 at the second close
    expect_exit(s, t, 300, side=sd)
    t = s.trade("F5.P1.5.g50.a")                       # never armed: Rpk 1.12 < 1.5
    expect_exit(s, t, last_offset(s), KX.R_END, side=sd)
    t = s.trade("F5.P2.g25.a")
    expect_exit(s, t, last_offset(s), KX.R_END, side=sd)


@pytest.mark.parametrize("mir", MIR)
def test_t2_f8_arm_then_break(tmp_path, vendor, mir):
    base = ([(60, 100), (60, 100), (30, 99.5), (30, 100), (60, 101.0)] + H(101, 101, 101) + H(101, 101)
            + [(20, 100.7), (40, 101.0)] + H(101, 101))
    # the break at bar 12 comes before any gain: F1 fires there, F8 (needs a 1R gain first) does not
    seg = base + [(5, 100.6), (55, 100.6)] + H(102.8) + [(5, 100.5), (55, 100.5)]
    s = Scen(tmp_path, seg, longs=[6], side_mirror=mir)
    sd = side_of(mir)
    expect_exit(s, s.trade("F1.w2.a"), 780, side=sd)
    t = s.trade("F8.w2.P1.a")                          # armed at bar 13 (X = 102.8 >= 101.02 + 1.2 + costs), fires at bar 14
    expect_exit(s, t, 15 * 60, side=sd)
    t = s.trade("F8.w2.P2.a")                          # 2R needs X >= 103.6: never armed
    expect_exit(s, t, last_offset(s), KX.R_END, side=sd)


@pytest.mark.parametrize("mir", MIR)
def test_t2_f6_loss_cut_only_below_minus_d(tmp_path, vendor, mir):
    pre = ([(60, 100), (60, 100), (30, 99.5), (30, 100), (60, 101.0)] + H(101, 101, 101) + H(101, 101)
           + [(20, 100.7), (40, 101.0)] + H(101, 101))
    sd = side_of(mir)
    sA = Scen(tmp_path / "a", pre + [(5, 100.6), (55, 100.6)], longs=[6], side_mirror=mir)    # Rc = -0.47: a small loss
    expect_exit(sA, sA.trade("F6.w2.d0"), 780, side=sd)
    expect_exit(sA, sA.trade("F6.w2.d0.5"), last_offset(sA), KX.R_END, side=sd)               # not below -0.5
    sB = Scen(tmp_path / "b", pre + [(5, 100.35), (55, 100.35)], longs=[6], side_mirror=mir)  # Rc = -0.68
    expect_exit(sB, sB.trade("F6.w2.d0"), 780, side=sd)
    expect_exit(sB, sB.trade("F6.w2.d0.5"), 780, side=sd)
    t = sA.trade("F6.w2.d0")
    raw = 200.0 - 101.0 if mir else 101.0
    fill = raw * (1 + sd * FILL_SLIP)
    px = 200.0 - 100.6 if mir else 100.6
    assert t["trace"][5, 8] == pytest.approx((sd * (px - fill) - fill * sA.mk.S(0.25)[5]) / 1.2, rel=1e-9)


@pytest.mark.parametrize("mir", MIR)
def test_t2_f7_time_stop_is_time_not_bars(tmp_path, vendor, mir):
    seg = H(*([100] * 18))
    s = Scen(tmp_path, seg, longs=[2], side_mirror=mir)
    expect_exit(s, s.trade("F7.N12.a"), 900, side=side_of(mir))                  # C0 + 12 bars = 180 + 720
    s2 = Scen(tmp_path / "g", seg, longs=[2], gaps=list(range(480, 540)), side_mirror=mir)   # bar 8 does not exist
    t = s2.trade("F7.N12.a")
    expect_exit(s2, t, 900, side=side_of(mir))                                   # still 12 hours later, not the 12th existing bar
    t = s.trade("F7.N48.b")                                                      # never: the period end closes it
    expect_exit(s, t, last_offset(s), KX.R_END, side=side_of(mir))


@pytest.mark.parametrize("mir", MIR)
def test_t2_f9_either_side_and_not_otherwise(tmp_path, vendor, mir):
    sd = side_of(mir)
    pre = [(60, 100)] * 4 + [(30, 99.8), (30, 100)] + [(60, 100)] * 4        # swing low 99.8 at bar 4 (w = 3), i0 = 8
    # (i) a gain of >= 1R, then a close below the reference: F8 part
    sA = Scen(tmp_path / "a", pre + H(101.5) + H(99.7), longs=[8], side_mirror=mir)
    t = sA.trade("F9.a")
    expect_exit(sA, t, 11 * 60, side=sd)
    # (ii) a small loss below the reference (-0.3R) and unarmed: nothing; then a loss deeper than 0.5R: the F6 part
    sB = Scen(tmp_path / "b", pre + H(99.7) + H(99.5), longs=[8], side_mirror=mir)
    t = sB.trade("F9.a")
    expect_exit(sB, t, 11 * 60, side=sd)
    assert t["trace"][0, 2] == 0 and t["trace"][0, 7] == pytest.approx(200 - 99.8 if mir else 99.8)
    # (iii) a gain of less than 1R and then a small loss below the reference: nothing
    sC = Scen(tmp_path / "c", pre + H(100.5) + H(99.7), longs=[8], side_mirror=mir)
    expect_exit(sC, sC.trade("F9.a"), last_offset(sC), KX.R_END, side=sd)


@pytest.mark.parametrize("mir", MIR)
def test_t2_f10_stall_only_in_profit(tmp_path, vendor, mir):
    sd = side_of(mir)
    s = Scen(tmp_path, H(100, 100, 100, 101.0) + H(*([101.0] * 12)), longs=[2], side_mirror=mir)
    t = s.trade("F10.N6.a")                           # the last new extreme is the minute 239; 600 - 239 >= 360 at bar 9's close
    expect_exit(s, t, 600, side=sd)
    assert t["checks"] == 7
    expect_exit(s, s.trade("F10.N12.a"), 960, side=sd)
    s2 = Scen(tmp_path / "l", H(100, 100, 100) + H(*([99.9] * 14)), longs=[2], side_mirror=mir)    # a loss after costs
    expect_exit(s2, s2.trade("F10.N6.a"), last_offset(s2), KX.R_END, side=sd)


@pytest.mark.parametrize("mir", MIR)
def test_t2_minute_j_never_enters_its_own_decision(tmp_path, vendor, mir):
    sd = side_of(mir)
    # F4: X = 101.2, level 100.75, the close 100.8 is above it; a spike high at the check minute 360 would raise X to 103
    seg = H(100, 100, 100, 101.0, 101.2, 100.8, 100.8, 100.8)
    s = Scen(tmp_path / "a", seg, longs=[2], highs={360: 103.0}, side_mirror=mir)
    t = s.trade("F4.m1.5.a")
    expect_exit(s, t, 420, side=sd)                   # the spike counts from the next check on (103 - 0.45 = 102.55 > 100.8)
    assert t["trace"][2, 2] == 0 and t["checks"] == 4
    # F5: Rpk = 0.53 < 1 at the check; a spike to 102 at minute 360 would arm it and 0.03 <= 0.5 x Rpk would fire
    seg = H(100, 100, 100, 100.8, 100.8, 100.2, 100.3, 100.3)
    s = Scen(tmp_path / "b", seg, longs=[2], highs={360: 102.0}, side_mirror=mir)
    expect_exit(s, s.trade("F5.P1.g50.a"), 420, side=sd)
    # F10: stalled since minute 239; at the check minute 600 a new high would reset the clock
    s = Scen(tmp_path / "c", H(100, 100, 100, 101.0) + H(*([101.0] * 12)), longs=[2], highs={600: 101.5}, side_mirror=mir)
    expect_exit(s, s.trade("F10.N6.a"), 600, side=sd)


F3_SEG = H(100, 100, 100, 100.5, 100.8, 100.6, 100.0, 100.0)        # the F3 check is at bar 5's close = minute 360


@pytest.mark.parametrize("mir", MIR)
@pytest.mark.parametrize("kind", ["stop_gap", "tp_gap", "liquidation"])
def test_t2_gaps_at_the_check_minute_beat_the_rule_and_do_not_free_the_minute(tmp_path, vendor, mir, kind):
    sd = side_of(mir)
    opens = {"stop_gap": {360: 98.0}, "tp_gap": {360: 104.0}, "liquidation": {360: 90.0}}[kind]
    s = Scen(tmp_path, F3_SEG, longs=[2], shorts=[5], opens=opens, side_mirror=mir)
    t = s.trade("F3.a")
    o360 = s.open_at(360)
    if kind == "stop_gap":
        assert t["reason"] == KX.R_SL and t["off"] == 360
        assert t["px"] == pytest.approx(o360 * (1 - sd * FILL_SLIP), rel=1e-12)
    elif kind == "tp_gap":
        assert t["reason"] == KX.R_TP and t["off"] == 360 and t["px"] == pytest.approx(o360, rel=1e-12)
    else:
        assert t["reason"] == KX.R_LIQ and t["off"] == 360 and t["px"] == 0.0
    # the check is in neither the numerator nor the denominator of the hazard
    assert t["den"].sum() == 2 and t["num"].sum() == 0            # only the checks of bars 3 and 4 (the position was open)
    r, a = acct(s, "F3.a")
    assert [x["status"] for x in a] == [1, 0]                      # the opposite signal fills at 360 and is skipped
    assert a[0]["exit"] == 360 and a[0]["reason"] != KX.R_RULE


@pytest.mark.parametrize("mir", MIR)
def test_t2_rule_comes_before_the_range_of_its_own_minute(tmp_path, vendor, mir):
    sd = side_of(mir)
    s = Scen(tmp_path, F3_SEG, longs=[2], shorts=[5], lows={360: 97.0}, side_mirror=mir)     # touches the stop (98.8) later in 360
    t = s.trade("F3.a")
    expect_exit(s, t, 360, KX.R_RULE, side=sd)                   # a rule exit at the open, not an SL at the stop
    s = Scen(tmp_path / "e", F3_SEG, longs=[2], shorts=[5], lows={359: 98.0}, side_mirror=mir)   # touched in the minute before the check
    t = s.trade("F3.a")
    assert t["reason"] == KX.R_SL and t["off"] == 359


@pytest.mark.parametrize("mir", MIR)
def test_t2_funding_is_paid_at_the_exit_minute_and_costs(tmp_path, vendor, mir):
    sd = side_of(mir)
    s = Scen(tmp_path, F3_SEG, longs=[2], shorts=[5], fund_at={360: 0.01}, side_mirror=mir)
    t = s.trade("F3.a")
    expect_exit(s, t, 360, KX.R_RULE, side=sd)
    S = s.mk.S(0.25)
    taker, slip = S[0], S[1]
    raw = s.open_at(180)
    fill = raw * (1 + sd * slip)
    stop = raw - sd * 4 * 0.3
    ok, lev, margin, qty, liq = K._size.py_func(S, s.mk.brs[0], 5000.0, sd, fill, stop, 0.3, False, s.mk.qty_steps[0],
                                                 s.mk.min_notionals[0])
    assert ok
    pay = sd * qty * s.open_at(360) * 0.01                        # the mark open of the exit minute
    price = t["px"]
    want = sd * qty * (price - fill) - qty * price * taker - qty * fill * taker - pay
    assert t["d"] == pytest.approx(want, rel=1e-9)


def test_t2_period_end_closes_and_rule_wins_the_same_minute(tmp_path, vendor):
    seg = H(*([100] * 15)) + [(1, 100)]                             # 901 minutes: the last minute is the open of bar 15
    s = Scen(tmp_path, seg, longs=[2], pad=False)
    assert s.mk.ts(0)[-1] == START + 900 * MIN
    t = s.trade("F7.N12.a")                                          # the check of bar 14's close is on the last minute
    expect_exit(s, t, 900, KX.R_RULE)
    t = s.trade("F7.N24.a")
    expect_exit(s, t, 900, KX.R_END)
    t = s.trade("E0")
    expect_exit(s, t, 900, KX.R_END)
    # a signal that fills on the last minute is not offered
    s2 = Scen(tmp_path / "x", seg, longs=[2, 14], pad=False)
    assert len(s2.off["coin"]) == 1


def test_t2_merged_checks_missing_minutes_and_same_minute_entry(tmp_path, vendor):
    seg = [(15 * 30, 100)]
    gaps = list(range(119, 134))                                     # bar 7's last minute and bar 8's first 14 minutes
    s = Scen(tmp_path, seg, tf="15m", longs=[4], shorts=[7], gaps=gaps, pad=False)
    assert [int(x) for x in s.off["fill"]] == [START + 75 * MIN, START + 135 * MIN]
    r, a = acct(s, "F3.a")
    # closes of bars 7 (120) and 8 (135) map to one minute (the one after the lone minute 134): one check, on bar 8
    assert a[0]["reason"] == KX.R_RULE and a[0]["exit"] == 135 and a[1]["entry"] == 135 and a[1]["status"] == 1
    t = s.trade("F3.a")
    assert t["checks"] == 3
    # the same path without the gap: the opposite signal is seen at its own close
    s2 = Scen(tmp_path / "n", seg, tf="15m", longs=[4], shorts=[7], pad=False)
    r, a = acct(s2, "F3.a")
    assert a[0]["exit"] == 120 and a[1]["entry"] == 120


def test_t2_q15_on_15m_and_30m_picks_equals_the_base_variant(tmp_path, vendor):
    for tf in ("15m", "30m"):
        coins = {"BTCUSDT": synth_coin(31, 12, 100.0, vol=0.0006, drop=0.01)}
        mk, prov, pd_ = build_world(coins, tmp_path / tf, pick=make_pick(tf), prov_kw=dict(warm=False))
        off = pd_.offered("select", mk)
        assert len(off["coin"]) > 10
        for base, q in (("F1.w3.a", "F1.w3.a.q15"), ("F4.m2.b", "F4.m2.b.q15"), ("F9.a", "F9.a.q15")):
            for qq in range(0, len(off["coin"]), 3):
                a = call_trade_x(mk, pd_, KX.variant_by_id(base), off, qq)[0]
                b = call_trade_x(mk, pd_, KX.variant_by_id(q), off, qq)[0]
                assert a == b


@pytest.mark.parametrize("mir", MIR)
def test_t2_only_rule_and_placebo_exits_free_their_minute(tmp_path, vendor, mir):
    # an ordinary intrabar stop at minute 360 does not free the fill at 360's open; the rule exit does
    seg = H(100, 100, 100, 100.5, 100.8, 100.6, 100.0, 100.0)
    s = Scen(tmp_path / "a", seg, longs=[2], shorts=[5], lows={360: 97.0}, side_mirror=mir)
    r, a = acct(s, "F3.a")
    assert a[0]["reason"] == KX.R_RULE and a[1]["status"] == 1
    s = Scen(tmp_path / "b", seg, longs=[2], shorts=[5], opens={359: 100.6}, lows={359: 97.0}, side_mirror=mir)
    r, a = acct(s, "F3.a")
    assert a[0]["reason"] == KX.R_SL and a[0]["exit"] == 359 and a[1]["status"] == 1


# ====================================================================================================== T1: parity
def acct_world(seed, ncoins=2, days=25, nsig=140, vol=0.0009, open_gap_p=0.0):
    prices = [100.0, 3000.0, 60.0, 0.1, 80.0, 250.0]
    coins = [synth_coin(seed * 10 + i, days, prices[i], vol=vol, drop=0.006, open_gap_p=open_gap_p) for i in range(ncoins)]
    mk = DX.Market.from_arrays(coins, EX)
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(ncoins):
        ts = coins[c]["ts"]
        for _ in range(nsig):
            j = int(rng.integers(50, len(ts) - 300))
            side = int(rng.choice([-1, 1]))
            px = float(coins[c]["o"][j])
            tp = px * (1 + side * rng.uniform(0.004, 0.03)) if rng.random() < 0.7 else np.nan
            rows.append((int(ts[j]) + int(rng.integers(0, 3)) * MIN, c, side, px * rng.uniform(0.001, 0.008), bool(rng.random() < 0.5), tp))
    rows.sort(key=lambda r: (r[0], r[1]))
    sig = dict(close=np.array([r[0] for r in rows], np.int64), coin=np.array([r[1] for r in rows], np.int64),
               side=np.array([r[2] for r in rows], np.int64), atr=np.array([r[3] for r in rows]),
               best=np.array([r[4] for r in rows]), tp=np.array([r[5] for r in rows]))
    return mk, sig


def kernel_account(mk, sig, S, ex_args):
    return K.account(S, mk.brs, mk.cat["ts"], mk.cat["o"], mk.cat["h"], mk.cat["l"], mk.cat["mo"], mk.cat["mh"], mk.cat["ml"],
                     mk.cat["fund"], mk.starts, mk.ends, sig["coin"], sig["close"], sig["side"], sig["atr"], sig["best"],
                     mk.qty_steps, mk.min_notionals, *ex_args, sig["tp"])


def kx_account(mk, sig, S, ex_args, force_end=False, rp=None, chart=None, plc=False, hz=None, seed=0, ends=None):
    PT, PF, QT = chart or KX.empty_chart()
    z = np.zeros(len(mk.symbols), np.int64)
    num, den = KX.new_counts()
    return KX.account_x(S, mk.brs, mk.cat["ts"], mk.cat["o"], mk.cat["h"], mk.cat["l"], mk.cat["mo"], mk.cat["mh"], mk.cat["ml"],
                        mk.cat["fund"], mk.starts, mk.ends if ends is None else ends, sig["coin"], sig["close"], sig["side"],
                        sig["atr"], sig["best"], np.zeros(len(sig["coin"]), np.int64), mk.qty_steps, mk.min_notionals, *ex_args,
                        sig["tp"], force_end, KX.rp_vector() if rp is None else rp, PT, PF, z, z, QT, z, z, plc,
                        np.zeros((KX.N_AGE, 2, 2)) if hz is None else hz, seed, num, den, np.zeros(2 * KX.NC, np.int8),
                        np.full(len(sig["coin"]), np.nan), 60_000)


@pytest.mark.parametrize("scale", [0.25, 1.0])
def test_t1_account_parity_all_84_exits(scale):
    kinds = set()
    for seed, vol, gp in ((3, 0.0009, 0.0), (4, 0.004, 0.003)):     # a calm world and a wild one (open gaps, liquidations, locks)
        mk, sig = acct_world(seed, vol=vol, open_gap_p=gp)
        S = mk.S(scale)
        for e in range(len(K.EXITS)):
            ex_args = K.exit_args(e)
            st, pnl, ext, rs, lv, w = kernel_account(mk, sig, S, ex_args)
            o = kx_account(mk, sig, S, ex_args)
            assert np.array_equal(st, o[0]) and np.array_equal(pnl, o[1]) and np.array_equal(ext, o[3])
            assert np.array_equal(rs, o[4]) and np.array_equal(lv, o[5]) and w == o[7], K.EXITS[e][0]
            kinds |= set(rs[st == 1].tolist())
            assert o[0].dtype == st.dtype and o[4].dtype == rs.dtype
    assert {K.R_SL, K.R_TP, K.R_LIQ, K.R_LOCK} <= kinds                # the kernel's own reasons were exercised


def test_t1_trade_parity_both_sides_both_groups_with_gaps_and_funding():
    mk, sig = acct_world(7, ncoins=2, days=30, nsig=60)
    n, nonrej = 0, 0
    for scale in (0.25, 1.0):
        S = mk.S(scale)
        for e in range(0, len(K.EXITS), 3):
            a = K.exit_args(e)
            for q in range(0, len(sig["coin"]), 5):
                c = int(sig["coin"][q])
                s0, s1 = int(mk.starts[c]), int(mk.ends[c])
                tsc = mk.cat["ts"][s0:s1]
                ei = K._entry_index(tsc, sig["close"][q])
                if ei < 0:
                    continue
                x = sig["atr"][q]
                args = (S, mk.brs[c], mk.cat["o"][s0:s1], mk.cat["h"][s0:s1], mk.cat["l"][s0:s1], mk.cat["mo"][s0:s1],
                        mk.cat["mh"][s0:s1], mk.cat["ml"][s0:s1], mk.cat["fund"][s0:s1], ei, s1 - s0, int(sig["side"][q]),
                        a[0] * x, x, bool(sig["best"][q]), 5000.0, mk.qty_steps[c], mk.min_notionals[c], *a[1:], sig["tp"][q])
                ref = K._trade(*args)
                PT, PF, QT = KX.empty_chart()
                got = KX._trade_x(S, mk.brs[c], tsc, *args[2:9], ei, s1 - s0, int(sig["side"][q]), a[0] * x, x, bool(sig["best"][q]),
                                  5000.0, mk.qty_steps[c], mk.min_notionals[c], *a[1:], sig["tp"][q], False, KX.rp_vector(), 0, PT,
                                  PF, QT, False, np.zeros((KX.N_AGE, 2, 2)), 0, c, *KX.new_counts(), KX.new_trace(0),
                                  np.zeros(2 * KX.NC, np.int8), float("nan"))
                assert tuple(got[:4]) == tuple(ref)
                n += 1
                nonrej += ref[2] != K.R_REJECT
    assert n > 500 and nonrej > 300


def test_t1_period_end_after_data_end_changes_nothing_and_force_end_only_adds_end():
    mk, sig = acct_world(5)
    S = mk.S(0.25)
    # tail signals whose positions are still open when the data ends
    rows = list(zip(sig["close"], sig["coin"], sig["side"], sig["atr"], sig["best"], sig["tp"]))
    for c in range(2):
        ts = mk.ts(c)
        for k, back in enumerate((90, 60, 30)):
            rows.append((int(ts[-back]), c, 1 if k % 2 == 0 else -1, float(mk.cat["o"][mk.starts[c] + len(ts) - back]) * 0.003, False, np.nan))
    rows.sort(key=lambda r: (r[0], r[1]))
    sig = dict(close=np.array([r[0] for r in rows], np.int64), coin=np.array([r[1] for r in rows], np.int64),
               side=np.array([r[2] for r in rows], np.int64), atr=np.array([r[3] for r in rows]),
               best=np.array([r[4] for r in rows]), tp=np.array([r[5] for r in rows]))
    ex_args = K.exit_args([e[0] for e in K.EXITS].index("tp3R|4"))
    ref = kernel_account(mk, sig, S, ex_args)
    a = kx_account(mk, sig, S, ex_args, force_end=False)
    assert np.array_equal(a[0], ref[0]) and np.array_equal(a[1], ref[1]) and a[7] == ref[5]
    b = kx_account(mk, sig, S, ex_args, force_end=True, ends=mk.ends)
    still_open = np.flatnonzero((a[4] == K.R_OPEN) & (a[0] == 1))
    assert len(still_open) >= 1
    first_open = int(still_open[0])
    # everything before the first position that was open at the data end is the same; that one is closed at the last open
    assert np.array_equal(a[1][:first_open], b[1][:first_open]) and np.array_equal(a[4][:first_open], b[4][:first_open])
    assert b[4][first_open] == KX.R_END and b[3][first_open] == mk.ts(int(sig["coin"][first_open]))[-1]
    assert b[6][first_open] == pytest.approx(mk.cat["o"][mk.ends[int(sig["coin"][first_open])] - 1] * (1 - int(sig["side"][first_open]) * 0.0002))


# ====================================================================================================== T2: differential
DIFF_WORLDS = {"15m": dict(days=12, vol=0.0006, exit="tp3R|4"), "30m": dict(days=16, vol=0.0004, exit="tp3R|4"),
               "1h": dict(days=30, vol=0.0003, exit="tp3R|4"), "4h": dict(days=80, vol=0.00015, exit="tp3R|2")}


def carve_merge_holes(coin, tf_min, k, seed):
    """Delete, at ``k`` random bar boundaries, the last minute of a bar and all but the last minute of the next bar: the closes
    of both bars then map to one minute (a merged check)."""
    rng = np.random.default_rng(seed)
    off = (coin["ts"] - START) // MIN
    keep = np.ones(len(off), bool)
    n_bars = int(off[-1]) // tf_min
    for b in rng.choice(np.arange(50, n_bars - 50), size=k, replace=False):
        m = int(b) * tf_min
        keep &= ~((off >= m - 1) & (off <= m + tf_min - 2))
    return {k_: v[keep] for k_, v in coin.items()}


def diff_world(tmp, tf, seed=21, ncoins=2, holes=True):
    w = DIFF_WORLDS[tf]
    prices = [100.0, 3000.0, 60.0]
    coins = {SYMS[i]: synth_coin(seed + i, w["days"], prices[i], vol=w["vol"], drop=0.003, open_gap_p=0.0004, outages=4)
             for i in range(ncoins)}
    tfm = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}[tf]
    if holes:
        coins = {k: carve_merge_holes(v, tfm, 12 if tf in ("15m", "30m") else 6, seed + 100 + i) for i, (k, v) in enumerate(coins.items())}
    return build_world(coins, tmp, pick=make_pick(tf, w["exit"]), prov_kw=dict(warm=False))


def random_hz(seed):
    rng = np.random.default_rng(seed)
    return np.where(rng.random((KX.N_AGE, 2, 2)) < 0.3, 0.0, rng.uniform(0.0, 0.25, (KX.N_AGE, 2, 2)))


@pytest.mark.parametrize("tf", ["15m", "30m", "1h", "4h"])
def test_t2_kernel_equals_the_plain_python_reference_on_random_paths(tmp_path, vendor, tf):
    """Every one of the 76 variants (and the placebo of every variant but F7) on random worlds with gaps, outages, open gaps,
    funding and a mark price: the numba kernel and the stateless plain-Python reference give the same trade and the same
    frozen decision (fire, stratum, reference) at every check."""
    mk, prov, pd_ = diff_world(tmp_path, tf)
    off = pd_.offered("select", mk)
    assert len(off["coin"]) >= 10
    rng = np.random.default_rng(5)
    n_cmp = n_rule = n_checks = 0
    for v in KX.variants():
        qs = rng.choice(len(off["coin"]), size=min(3, len(off["coin"])), replace=False)
        for q in qs:
            bad = compare_trade(mk, prov, pd_, v, off, int(q))
            assert not bad, (tf, v.id, int(q), bad[:3])
            out = call_trade_x(mk, pd_, v, off, int(q))[0]
            n_cmp += 1
            n_rule += out[2] == KX.R_RULE
            n_checks += out[5]
            if KX.has_placebo(v) if hasattr(KX, "has_placebo") else PL.has_placebo(v):
                hz = random_hz(int(q) + 7)
                bad = compare_trade(mk, prov, pd_, v, off, int(q), plc=True, hz=hz, seed=PL.seed_base(v.id, "select", int(q)))
                assert not bad, (tf, v.id, int(q), "placebo", bad[:3])
    assert n_cmp >= 200 and n_rule >= 40 and n_checks >= 400


@pytest.mark.parametrize("tf", ["15m", "30m", "1h", "4h"])
def test_t2_reference_world_exercises_merged_checks_and_missing_bins(tmp_path, vendor, tf):
    mk, prov, pd_ = diff_world(tmp_path, tf)
    dup = 0
    for c in range(2):
        ts = mk.ts(c)
        cl = pd_.frames[c][1]
        mins = np.asarray([entry_index_py(ts, int(x)) for x in cl])
        dup += int((np.diff(mins[mins >= 0]) == 0).sum())
    assert dup >= 4                                                  # several closes mapping to one minute exist in this world


# ====================================================================================================== T4: placebo
E0B = KX.Variant("E0b", KX.F_NONE, "E0b", "-", "b", False, {}, 0, 0)       # the base account of mode (b): no rule, no take-profit


def same_account(a, b):
    return all(np.array_equal(getattr(a, k), getattr(b, k)) for k in ("status", "pnl", "entry_ts", "exit_ts", "reason", "lev", "xpx")) \
        and a.wallet == b.wallet


@pytest.fixture(scope="module")
def world_1h(tmp_path_factory, vendor):
    return diff_world(tmp_path_factory.mktemp("w1h"), "1h")


@pytest.fixture(scope="module")
def world_4h(tmp_path_factory, vendor):
    return diff_world(tmp_path_factory.mktemp("w4h"), "4h")


@pytest.mark.parametrize("vid", ["F1.w3.a", "F1.w2.b", "F2.n20.b", "F3.a", "F4.m2.a.q15", "F5.P1.g50.b", "F6.w3.d0.5", "F8.w2.P1.a",
                                 "F9.b.q15", "F10.N6.a"])
def test_t4_zero_hazard_equals_the_modes_base_account(world_1h, vid):
    mk, prov, pd_ = world_1h
    v = KX.variant_by_id(vid)
    base = KX.simulate(mk, pd_, E0 if v.mode == "a" else E0B, 0.25, "select")
    plc = KX.simulate(mk, pd_, v, 0.25, "select", placebo=True, hz=np.zeros((KX.N_AGE, 2, 2)), seed_base=12345)
    assert same_account(base, plc)
    assert plc.num.sum() == 0 and plc.den.sum() > 0                       # checks were made, none exited


E0 = KX.E0


@pytest.mark.parametrize("vid", ["F1.w3.a", "F2.n20.b", "F3.b", "F4.m2.a.q15", "F5.P1.g50.b", "F9.a", "F10.N6.b"])
def test_t4_unit_hazard_exits_at_the_first_check(world_4h, vid):
    mk, prov, pd_ = world_4h
    v = KX.variant_by_id(vid)
    r = KX.simulate(mk, pd_, v, 0.25, "select", placebo=True, hz=np.ones((KX.N_AGE, 2, 2)), seed_base=1)
    ent = r.trades()
    assert len(ent) >= 5
    n_rand = 0
    for q in ent:
        c = int(r.sig["coin"][q])
        ts = mk.ts(c)
        e = int(np.searchsorted(ts, r.entry_ts[q]))
        i0 = int(r.sig["i0"][q])
        ch = RefChart(pd_, c)
        q15 = bool(v.q15) and pd_.tf in ("1h", "4h")
        if q15:
            q15b = ref_q15(prov, pd_, c)
            first = next(entry_index_py(ts, int(cc)) for cc in q15b["cms"] if cc > ch.cms[i0])
        else:
            first = ch.minute[i0 + 1]
        first = max(first, e + 1)
        j = int(np.searchsorted(ts, r.exit_ts[q]))
        if r.reason[q] == KX.R_RAND:
            assert j == first
            n_rand += 1
        else:
            assert j <= first
    assert n_rand >= 3


def test_t4_draws_depend_only_on_seed_coin_and_time():
    assert PL.splitmix64_py(0) == 0xE220A8397B1DCDAF                      # the standard splitmix64 stream for seed 0
    rng = np.random.default_rng(1)
    for _ in range(2000):
        base = int(rng.integers(0, 2 ** 32))
        coin = int(rng.integers(0, 6))
        t = int(rng.integers(1_600_000_000_000, 1_800_000_000_000))
        assert KX.draw_u(base, coin, t) == PL.draw_u_py(base, coin, t)
        t0 = t // 60_000 * 60_000
        assert KX.draw_u(base, coin, t0) == KX.draw_u(base, coin, t0 + 59_999)       # the minute is what counts
        assert 0.0 <= KX.draw_u(base, coin, t) < 1.0
    u = np.array([KX.draw_u(42, 3, 1_700_000_000_000 + 60_000 * k) for k in range(20000)])
    assert abs(u.mean() - 0.5) < 0.01 and abs(u.std() - 0.2887) < 0.01 and len(set(u.tolist())) == 20000
    assert KX.draw_u(42, 3, 1_700_000_000_000) != KX.draw_u(43, 3, 1_700_000_000_000)
    assert KX.draw_u(42, 3, 1_700_000_000_000) != KX.draw_u(42, 4, 1_700_000_000_000)
    assert KX.draw_u(42, 3, 1_700_000_000_000) != KX.draw_u(42, 3, 1_700_000_060_000)
    assert PL.seed_base("F1.w3.a", "select", 7) == R._seed("exitflex", "placebo", "F1.w3.a", "select", 7)     # no pick id in the seed
    assert [KX.age_bucket(k) for k in (1, 2, 3, 4, 5, 8, 9, 16, 17, 32, 33, 64, 65, 1000)] == [0, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7]
    assert all(KX.age_bucket(k) == PL.age_bucket_py(k) for k in range(1, 300))


def test_t4_placebo_account_is_reproducible_and_seed_dependent(world_1h):
    mk, prov, pd_ = world_1h
    v = KX.variant_by_id("F4.m2.a")
    hz = np.full((KX.N_AGE, 2, 2), 0.08)
    a = KX.simulate(mk, pd_, v, 0.25, "select", placebo=True, hz=hz, seed_base=11)
    b = KX.simulate(mk, pd_, v, 0.25, "select", placebo=True, hz=hz, seed_base=11)
    c = KX.simulate(mk, pd_, v, 0.25, "select", placebo=True, hz=hz, seed_base=12)
    assert same_account(a, b) and not same_account(a, c)
    with pytest.raises(ValueError):
        KX.simulate(mk, pd_, KX.variant_by_id("F7.N12.a"), 0.25, "select", placebo=True, hz=hz)
    assert not PL.has_placebo(KX.variant_by_id("F7.N24.b")) and PL.has_placebo(KX.variant_by_id("F3.a"))


def test_t4_hazard_tables_by_hand(tmp_path, vendor):
    seg = H(100, 100, 100, 101.5, 101.0, 100.7)
    s = Scen(tmp_path / "a", seg, longs=[2])
    t = s.trade("F5.P1.5.g50.a")             # never armed: its 8 checks all count in the denominator, none exits
    want = np.zeros((8, 2, 2), np.int64)
    want[0, 1, 0], want[1, 1, 0], want[2, 1, 0], want[3, 1, 0] = 1, 1, 2, 4
    assert np.array_equal(t["den"], want) and t["num"].sum() == 0
    t = s.trade("F5.P1.g50.a")               # armed at the first check; the RULE exit is the numerator of its stratum
    want = np.zeros((8, 2, 2), np.int64)
    want[0, 1, 1], want[1, 1, 1], want[2, 1, 1] = 1, 1, 1
    assert np.array_equal(t["den"], want)
    wn = np.zeros((8, 2, 2), np.int64)
    wn[2, 1, 1] = 1
    assert np.array_equal(t["num"], wn)
    hz = PL.hazard(t["num"], t["den"])
    assert hz[2, 1, 1] == 1.0 and hz[0, 1, 1] == 0.0 and hz[3, 1, 1] == 0.0
    # F6: loss-only exits; every check before the break is at a loss (s = 0) with a reference at hand (z = 1)
    pre = ([(60, 100), (60, 100), (30, 99.5), (30, 100), (60, 101.0)] + H(101, 101, 101) + H(101, 101)
           + [(20, 100.7), (40, 101.0)] + H(101, 101))
    s6 = Scen(tmp_path / "b", pre + [(5, 100.6), (55, 100.6)], longs=[6])
    t = s6.trade("F6.w2.d0")
    wd = np.zeros((8, 2, 2), np.int64)
    wd[0, 0, 1], wd[1, 0, 1], wd[2, 0, 1], wd[3, 0, 1] = 1, 1, 2, 2
    wn = np.zeros((8, 2, 2), np.int64)
    wn[3, 0, 1] = 1
    assert np.array_equal(t["den"], wd) and np.array_equal(t["num"], wn)
    t = s6.trade("F6.w2.d0.5")               # the same break is not deep enough: no numerator, the checks go on
    assert t["num"].sum() == 0 and t["den"].sum() > wd.sum()
    # a check whose minute gaps through the stop is in neither count
    s5 = Scen(tmp_path / "c", seg, longs=[2], opens={360: 98.0})
    t = s5.trade("F5.P1.g50.a")
    want = np.zeros((8, 2, 2), np.int64)
    want[0, 1, 1], want[1, 1, 1] = 1, 1
    assert t["reason"] == KX.R_SL and np.array_equal(t["den"], want) and t["num"].sum() == 0


@pytest.mark.parametrize("plc", [False, True])
def test_t4_stratum_is_taken_from_the_frozen_state(tmp_path, vendor, plc):
    seg = H(100, 100, 100, 100.8, 100.8, 100.2, 100.3, 100.3)
    hz = np.zeros((KX.N_AGE, 2, 2))
    for mode in (False, True):
        s = Scen(tmp_path / str(mode), seg, longs=[2], highs={360: 102.0}, side_mirror=mode)
        t = s.trade("F5.P1.g50.a", plc=plc, hz=hz, seed=3)
        tr = t["trace"]
        assert tr[2, 0] > 0 and int(tr[2, 5]) == 0 and tr[2, 6] == 0.0      # k = 3 at minute 360: not armed (its own spike is not seen)
        assert int(tr[3, 5]) == 1 and tr[3, 6] == 1.0                      # k = 4: the spike counts now
        if not plc:
            assert t["off"] == 420


def test_t4_realised_rates_audit_a7(world_1h):
    mk, prov, pd_ = world_1h
    v = KX.variant_by_id("F4.m2.a")
    hz = np.zeros((KX.N_AGE, 2, 2))
    hz[:, 1, 0] = 0.05
    hz[:, 0, 0] = 0.12
    num = np.zeros((KX.N_AGE, 2, 2), np.int64)
    den = np.zeros((KX.N_AGE, 2, 2), np.int64)
    for s_ in range(40):
        r = KX.simulate(mk, pd_, v, 0.25, "select", placebo=True, hz=hz, seed_base=PL.seed_base(v.id, "select", s_))
        num += r.num
        den += r.den
    assert den.sum() > 2000 and num.sum() > 100
    assert PL.audit_realised_rates(num, den, hz)
    assert not PL.audit_realised_rates(num, den, hz * 3.0)               # a wrong table is caught
    assert PL.binom_band_ok(50, 1000, 0.05, 1e-3) and not PL.binom_band_ok(100, 1000, 0.05, 1e-3)
    assert PL.binom_band_ok(500, 10000, 0.05, 1e-3) and not PL.binom_band_ok(700, 10000, 0.05, 1e-3)


def test_t4_two_picks_with_identical_inputs_give_identical_placebo_exits(world_1h):
    """The draw depends on (V, period, seed, coin, check close), not on the pick: two picks with the same coin, signals and hazard table
    (different ids) exit at the same checks."""
    mk, prov, pd_ = world_1h
    pd2 = DX.PickData(mk, dict(pd_.pick, id="core-OTHER-1h-9"), prov)
    for vid in ("F4.m2.b", "F1.w3.a", "F10.N6.a"):
        v = KX.variant_by_id(vid)
        hz = random_hz(5)
        a = KX.simulate(mk, pd_, v, 0.25, "select", placebo=True, hz=hz, seed_base=PL.seed_base(v.id, "select", 3))
        b = KX.simulate(mk, pd2, v, 0.25, "select", placebo=True, hz=hz, seed_base=PL.seed_base(v.id, "select", 3))
        assert same_account(a, b) and (a.reason == KX.R_RAND).sum() >= 3
    assert PL.seed_base("F1.w3.a", "select", 3) != PL.seed_base("F1.w3.a", "confirm", 3) != PL.seed_base("F1.w3.b", "confirm", 3)


# ====================================================================================================== T4: F12's clock, the draw key; T6: F12 against its components
def f12_variant(cmask, mode="a"):
    """F12 with only the components of ``cmask`` enabled (the component mask for tests, prereg 13)."""
    return KX.Variant(f"F12.mask{cmask}.{mode}", KX.F12, "F12", "A", mode, False, dict(KX.F12_PARAMS, cmask=cmask), 8, 0, True)


def splitmix64_by_hand(x):
    M = (1 << 64) - 1
    z = (x + 0x9E3779B97F4A7C15) & M
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M
    return z ^ (z >> 31)


def test_t4_the_draw_key_is_the_coin_priority_index_and_the_latest_closed_bar_of_the_check(tmp_path, vendor):
    # a hand-computed example: base 12345, DOGE (index 3 in the priority order BTC, ETH, SOL, DOGE, LTC, BCH), close 2024-01-02 03:15 UTC
    close_ms = 1_704_165_300_000
    key = 3 * 2 ** 36 + close_ms // 60_000
    want = (splitmix64_by_hand(splitmix64_by_hand(12345) ^ key) >> 11) / 2 ** 53
    assert KX.draw_u(12345, 3, close_ms) == want == PL.draw_u_py(12345, 3, close_ms) and SYMS.index("DOGEUSDT") == 3
    assert KX.draw_u(12345, 3, close_ms) != KX.draw_u(12345, 4, close_ms)                       # another coin index draws another u
    # on a built trade: the u of check k is the draw for (coin index, close of the check's latest closed chart bar)
    mk, prov, pd_ = diff_world(tmp_path, "1h")
    off = pd_.offered("select", mk)
    v = KX.variant_by_id("F4.m2.b")
    hz = np.zeros((KX.N_AGE, 2, 2))
    n_checked = 0
    for q in range(len(off["coin"])):
        c = int(off["coin"][q])
        out, _n, _d, tr = KX.simulate_trade(mk, pd_, v, off, q, 0.25, "select", True, True, hz, 777, 40)
        for k in range(min(int(out[5]), 5)):
            bar = int(np.searchsorted(pd_.b_cms[pd_.cst[c]:pd_.cen[c]], tr[k, 1]))
            assert pd_.b_cms[pd_.cst[c] + bar] == tr[k, 1]                                      # the check close is a chart bar's close
            want = (splitmix64_by_hand(splitmix64_by_hand(777) ^ (c * 2 ** 36 + int(tr[k, 1]) // 60_000)) >> 11) / 2 ** 53
            assert tr[k, 10] == want
            n_checked += 1
        if n_checked >= 40:
            break
    assert n_checked >= 20


@pytest.mark.parametrize("tf,tfm", [("15m", 15), ("30m", 30), ("1h", 60), ("4h", 240)])
def test_t4_the_f12_placebo_carries_f12s_eight_hour_clock(tmp_path, vendor, f11_on, tf, tfm):
    i0 = 3
    c0 = (i0 + 1) * tfm
    flat = [(c0 + 8 * 60 + 600, 100.0)]
    s = Scen(tmp_path / "a", flat, tf=tf, longs=[i0], f11=f11_provider([]), ema=np.full(40, 101.0))
    zero = np.zeros((KX.N_AGE, 2, 2))
    # h = 0 everywhere: it leaves at the clock check, with probability 1 and no draw (u = -1 in the trace); the rule leaves there too
    for vid in ("F12.a", "F12.b"):
        t = s.trade(vid, plc=True, hz=zero, seed=1)
        expect_exit(s, t, c0 + 8 * 60, KX.R_RAND)
        assert t["trace"][t["checks"] - 1, 10] == -1.0 and (t["trace"][:t["checks"] - 1, 10] >= 0).all()
        r = s.trade(vid)
        expect_exit(s, r, c0 + 8 * 60)
        assert r["comp"] == KX.CB_F7H
        # the hazard counts exclude the clock check: every check before it is in the denominator, none in the numerator
        assert r["den"].sum() == r["checks"] - 1 and r["num"].sum() == 0
        assert t["den"].sum() == t["checks"] - 1 and t["num"].sum() == 0
    # with h = 1 above it, nothing changes at the clock; with h = 1 everywhere it leaves at the first check (before the clock)
    t = s.trade("F12.a", plc=True, hz=np.ones((KX.N_AGE, 2, 2)), seed=1)
    assert t["off"] == c0 + tfm and t["checks"] == 1
    # a placebo of another family has no clock: with h = 0 it never leaves
    f = Scen(tmp_path / "b", flat, tf=tf, longs=[i0], ema=np.full(40, 101.0))
    assert f.trade("F4.m2.a", plc=True, hz=zero, seed=1)["reason"] == KX.R_END
    # a merged check is the clock check when any merged close is at or after C0 + 8 h
    if tf != "4h":
        gaps = list(range(c0 + 8 * 60 - 1, c0 + 8 * 60 + tfm - 1))                 # the closes at C0 + 8 h and the next one map to one minute
        m = Scen(tmp_path / "c", flat, tf=tf, longs=[i0], f11=f11_provider([]), ema=np.full(40, 101.0), gaps=gaps, pad=True)
        tm = m.trade("F12.a", plc=True, hz=zero, seed=1)
        assert tm["reason"] == KX.R_RAND and tm["off"] >= c0 + 8 * 60


def test_t4_no_f12_placebo_position_is_held_past_its_clock_check_on_random_worlds(tmp_path, vendor, f11_on):
    for tf in ("30m", "1h"):
        w = DIFF_WORLDS[tf]
        coins = {SYMS[i]: synth_coin(51 + i, w["days"], (100.0, 3000.0)[i], vol=w["vol"], drop=0.003, outages=2) for i in range(2)}
        mk, prov, pd_ = build_world(coins, tmp_path / tf, pick=make_pick(tf, w["exit"]), prov_kw=dict(warm=False), f11=causal_f11)
        for vid in ("F12.a", "F12.b"):
            v = KX.variant_by_id(vid)
            hz = random_hz(11) * 0.2
            for sd in range(3):
                r = KX.simulate(mk, pd_, v, 0.25, "select", placebo=True, hz=hz, seed_base=PL.seed_base(v.id, "select", sd))
                assert RX.audit_f12_clock(mk, pd_, r)
            r = KX.simulate(mk, pd_, v, 0.25, "select")
            assert RX.audit_f12_clock(mk, pd_, r) and (r.reason == KX.R_RULE).sum() > 3
            # the audit has teeth: a position held a day past its clock fails it
            k = int(np.flatnonzero(r.status == 1)[0])
            r.exit_ts = r.exit_ts.copy()
            r.exit_ts[k] = r.entry_ts[k] + 30 * 3_600_000
            assert not RX.audit_f12_clock(mk, pd_, r)


def test_t6_f12_with_one_component_enabled_equals_that_family_and_with_only_f11_equals_f11(tmp_path, vendor, f11_on):
    """The component mask of the tests: F12 at its fixed values with one component on gives the exits of that family at the same value
    (rule and placebo, both modes); F12 with only F11 on equals F11. F6 lies within F1."""
    def prov(pick, sym, df, close, sl, ss):
        n = len(df)
        rng = np.random.default_rng(len(df) + 5)
        c = df["close"].to_numpy(float)
        ema = df["close"].ewm(span=12, adjust=False).mean().to_numpy(float)
        lvl_l, lvl_s, tg_l, tg_s = (np.full(n, np.nan) for _ in range(4))
        lvl_l[sl], lvl_s[ss] = c[sl] * 0.99, c[ss] * 1.01
        tg_l[sl], tg_s[ss] = c[sl] * 1.012, c[ss] * 0.988
        return {"comp_long": [("state", (c < ema).astype(float)), ("event", (rng.random(n) < 0.04).astype(float))],
                "comp_short": [("state", (c > ema).astype(float)), ("event", (rng.random(n) < 0.04).astype(float))],
                "lvl_long": lvl_l, "lvl_short": lvl_s, "tgt_long": tg_l, "tgt_short": tg_s}
    pairs = [(KX.CB_F1, "F1.w3"), (KX.CB_F2, "F2.n20"), (KX.CB_F3, "F3"), (KX.CB_F4, "F4.m2"), (KX.CB_F5, "F5.P1.5.g50"),
             (KX.CB_F6, "F6.w3.d0.5"), (KX.CB_F7H, "F7h.H8"), (KX.CB_F10, "F10.N12"), (KX.CB_F11, "F11")]
    n_cmp = n_exit = 0
    for tf in ("30m", "1h"):
        w = DIFF_WORLDS[tf]
        coins = {SYMS[i]: synth_coin(61 + i, w["days"], (100.0, 3000.0)[i], vol=w["vol"], drop=0.003, open_gap_p=0.0004, outages=2) for i in range(2)}
        mk, prov_, pd_ = build_world(coins, tmp_path / tf, pick=make_pick(tf, w["exit"]), prov_kw=dict(warm=False), f11=prov)
        off = pd_.offered("select", mk)
        def no_target(pick, sym, df, close, sl, ss):                       # F12.b keeps the strategy's target where there is one; F1.b has none
            return dict(prov(pick, sym, df, close, sl, ss), tgt_long=None, tgt_short=None)
        pd_nt = DX.PickData(mk, pd_.pick, prov_, f11=no_target)
        for bit, fid in pairs:
            for mode in ("a", "b"):
                if fid.startswith("F6") and mode == "b":
                    continue
                fam = KX.variant_by_id(fid if fid.startswith("F6") else f"{fid}.{mode}")
                v12 = f12_variant(bit, mode)
                pdx = pd_ if (bit == KX.CB_F11 or mode == "a") else pd_nt
                for q in range(0, len(off["coin"]), max(1, len(off["coin"]) // 18)):
                    a = call_trade_x(mk, pdx, fam, off, q)[0]
                    b = call_trade_x(mk, pdx, v12, off, q)[0]
                    assert a[:7] == b[:7], (tf, fid, mode, q, a, b)
                    assert b[7] in (0, bit) and (b[7] == bit) == (b[2] == KX.R_RULE)
                    n_cmp += 1
                    n_exit += b[2] == KX.R_RULE
                    if KX.has_placebo(fam) and bit not in (KX.CB_F6, KX.CB_F7H):
                        hz = random_hz(q + 1)
                        pa = call_trade_x(mk, pdx, fam, off, q, plc=True, hz=hz, seed=q + 5)[0]
                        pb = call_trade_x(mk, pdx, v12, off, q, plc=True, hz=hz, seed=q + 5)[0]
                        assert pa[:7] == pb[:7] and pb[7] == 0, (tf, fid, mode, q, "placebo")
        # F6 lies within F1: whenever the full F12 fires F6, it fires F1 too
        for vid in ("F12.a", "F12.b"):
            for q in range(0, len(off["coin"]), max(1, len(off["coin"]) // 40)):
                out = call_trade_x(mk, pd_, KX.variant_by_id(vid), off, q)[0]
                if out[2] == KX.R_RULE and out[7] & KX.CB_F6:
                    assert out[7] & KX.CB_F1
    assert n_cmp >= 250 and n_exit >= 40


# ====================================================================================================== T2: F11 (the mechanics)
@pytest.fixture()
def f11_on():
    KX.register_f11(lambda *a, **k: None)
    yield
    KX.clear_f11()


def comp_arr(n, true_bars=(), nan_bars=(), default=0):
    a = np.full(n, float(default))
    for i in true_bars:
        a[i] = 1.0
    for i in nan_bars:
        a[i] = np.nan
    return a


def f11_provider(comps, lvl=None, tgt=None):
    """A test provider: ``comps`` = [(kind, dict(true_bars, nan_bars, default))], the same components for both sides;
    ``lvl`` / ``tgt`` = the price at the signal bars of a long (a short gets the mirror image 200 - price)."""
    def prov(pick, sym, df, close, sl, ss):
        n = len(df)
        cl = [(k, comp_arr(n, **kw)) for k, kw in comps]
        out = {"comp_long": cl, "comp_short": cl, "lvl_long": None, "lvl_short": None, "tgt_long": None, "tgt_short": None}
        for key, val in (("lvl", lvl), ("tgt", tgt)):
            if val is not None:
                a, b = np.full(n, np.nan), np.full(n, np.nan)
                a[np.flatnonzero(sl)] = val
                b[np.flatnonzero(ss)] = 200.0 - val
                out[key + "_long"], out[key + "_short"] = a, b
        return out
    return prov


def scen11(tmp, seg, comps, lvl=None, tgt=None, mir=False, **kw):
    return Scen(tmp, seg, longs=[2], side_mirror=mir, f11=f11_provider(comps, lvl, tgt), **kw)


@pytest.mark.parametrize("mir", MIR)
def test_t2_f11_event_component(tmp_path, vendor, f11_on, mir):
    seg = H(*([100] * 10))
    s = scen11(tmp_path, seg, [("event", dict(true_bars=(2, 5)))], mir=mir)      # true on the signal bar does not count
    expect_exit(s, s.trade("F11.a"), 360, side=side_of(mir))
    s = scen11(tmp_path / "b", seg, [("event", dict(true_bars=(2,)))], mir=mir)
    expect_exit(s, s.trade("F11.a"), last_offset(s), KX.R_END, side=side_of(mir))


@pytest.mark.parametrize("mir", MIR)
def test_t2_f11_state_component_arms_after_a_false_close(tmp_path, vendor, f11_on, mir):
    seg = H(*([100] * 10))
    # true on the signal bar and on bar 3: not armed; false at 4: armed; true at 5: fires
    s = scen11(tmp_path, seg, [("state", dict(true_bars=(2, 3, 5)))], mir=mir)
    expect_exit(s, s.trade("F11.a"), 360, side=side_of(mir))
    # false on the signal bar: armed at once, true at 3 fires at the first check
    s = scen11(tmp_path / "a", seg, [("state", dict(true_bars=(3,)))], mir=mir)
    expect_exit(s, s.trade("F11.a"), 240, side=side_of(mir))
    # a NaN neither fires nor arms: NaN at 4 leaves it unarmed, so the true at 5 does nothing
    s = scen11(tmp_path / "b", seg, [("state", dict(true_bars=(2, 3, 5), nan_bars=(4,)))], mir=mir)
    expect_exit(s, s.trade("F11.a"), last_offset(s), KX.R_END, side=side_of(mir))
    # two components: either fires
    s = scen11(tmp_path / "c", seg, [("state", dict(true_bars=(2, 3, 4, 5, 6))), ("event", dict(true_bars=(4,)))], mir=mir)
    expect_exit(s, s.trade("F11.a"), 300, side=side_of(mir))


@pytest.mark.parametrize("mir", MIR)
def test_t2_f11_level_test_is_fixed_at_the_signal_bar_and_armed(tmp_path, vendor, f11_on, mir):
    sd = side_of(mir)
    # the close is above the level at entry (armed); bar 4 closes below 99.0
    s = scen11(tmp_path, H(100, 100, 100, 99.5, 98.9, 99.5, 99.5, 99.5, 99.5, 99.5, 99.5, 99.5), [], lvl=99.0, mir=mir)
    expect_exit(s, s.trade("F11.a"), 300, side=sd)
    # the close starts below the level (not armed): below at 3 does nothing, above at 4 arms, below at 5 fires
    seg = H(100, 100, 100, 100.5, 101.5, 100.8, 100.8, 100.8, 100.8, 100.8, 100.8, 100.8)
    s = scen11(tmp_path / "b", seg, [], lvl=101.0, mir=mir)
    expect_exit(s, s.trade("F11.a"), 360, side=sd)
    # a NaN level is no level
    s = scen11(tmp_path / "c", seg, [], lvl=None, mir=mir)
    expect_exit(s, s.trade("F11.a"), last_offset(s), KX.R_END, side=sd)


@pytest.mark.parametrize("mir", MIR)
def test_t2_f11_modes_and_native_target(tmp_path, vendor, f11_on, mir):
    sd = side_of(mir)
    seg = H(100, 100, 100, 101.0, 102.5, 102.5, 102.5, 102.5, 102.5, 102.5)
    # F11.b: the strategy's target 102.0 (maker limit, filled at the level); F11.a: the pick's own 3R (103.6) is not reached
    s = scen11(tmp_path, seg, [], tgt=102.0, lvl=90.0, mir=mir)
    t = s.trade("F11.b")
    assert t["reason"] == KX.R_TP and t["px"] == pytest.approx(200 - 102.0 if mir else 102.0, rel=1e-12) and t["off"] == 280
    t = s.trade("F11.a")
    expect_exit(s, t, last_offset(s), KX.R_END, side=sd)
    # a target at or behind the fill is no target: F11.b has no take-profit at all (not the pick's either)
    s = scen11(tmp_path / "b", H(100, 100, 100, 101.0, 104.5, 104.5, 104.5, 104.5, 104.5, 104.5), [], tgt=99.0, lvl=90.0, mir=mir)
    expect_exit(s, s.trade("F11.b"), last_offset(s), KX.R_END, side=sd)
    t = s.trade("F11.a")                                              # the pick's 3R take-profit (103.6) is hit
    assert t["reason"] == KX.R_TP
    # NaN target: none
    s = scen11(tmp_path / "c", H(100, 100, 100, 101.0, 104.5, 104.5, 104.5, 104.5, 104.5, 104.5), [], tgt=None, lvl=90.0, mir=mir)
    expect_exit(s, s.trade("F11.b"), last_offset(s), KX.R_END, side=sd)


def test_t2_f11_merged_checks_fire_on_any_bar_and_placebo_has_no_precondition(tmp_path, vendor, f11_on):
    seg = [(15 * 30, 100)]
    gaps = list(range(119, 134))
    s = Scen(tmp_path, seg, tf="15m", longs=[4], shorts=[], gaps=gaps, pad=False,
             f11=f11_provider([("event", dict(true_bars=(7,)))]))
    t = s.trade("F11.a")                                  # bars 7 and 8 share the check; the event is on bar 7 only
    assert t["reason"] == KX.R_RULE and t["off"] == 135 and t["checks"] == 3
    t = s.trade("F11.a", plc=True, hz=np.zeros((KX.N_AGE, 2, 2)), seed=1)
    assert t["trace"][:3, 5].tolist() == [1.0, 1.0, 1.0]  # an event component can fire at every check: z = 1 (6)
    s2 = Scen(tmp_path / "s", seg, tf="15m", longs=[4], shorts=[], pad=False, f11=f11_provider([("state", dict(true_bars=(5, 6, 7, 8)))]))
    t = s2.trade("F11.a")                                 # armed at the signal bar (false there), true at 5: fires at the first check
    assert t["off"] == 90


def test_t2_f11_differential_against_the_reference(tmp_path, vendor, f11_on):
    """Random components (state and event, NaN, levels, targets) on random worlds: kernel and reference agree, both modes,
    rule and placebo."""
    def prov(pick, sym, df, close, sl, ss):
        n = len(df)
        rng = np.random.default_rng(len(df))
        c = df["close"].to_numpy(float)
        ema = df["close"].ewm(span=12, adjust=False).mean().to_numpy(float)
        st_long = np.where(rng.random(n) < 0.03, np.nan, (c < ema).astype(float))
        st_short = np.where(rng.random(n) < 0.03, np.nan, (c > ema).astype(float))
        ev_long = (rng.random(n) < 0.04).astype(float)
        ev_short = (rng.random(n) < 0.04).astype(float)
        atr = np.abs(np.diff(c, prepend=c[0])) + 1e-9
        lvl_l, lvl_s, tg_l, tg_s = (np.full(n, np.nan) for _ in range(4))
        lvl_l[sl] = c[sl] - 1.5 * np.maximum(atr[sl], 0.001 * c[sl])
        lvl_s[ss] = c[ss] + 1.5 * np.maximum(atr[ss], 0.001 * c[ss])
        tg_l[sl] = c[sl] * 1.01
        tg_s[ss] = c[ss] * 0.99
        return {"comp_long": [("state", st_long), ("event", ev_long)], "comp_short": [("state", st_short), ("event", ev_short)],
                "lvl_long": lvl_l, "lvl_short": lvl_s, "tgt_long": tg_l, "tgt_short": tg_s}
    for tf in ("30m", "1h"):
        w = DIFF_WORLDS[tf]
        coins = {SYMS[i]: synth_coin(41 + i, w["days"], (100.0, 3000.0)[i], vol=w["vol"], drop=0.003, open_gap_p=0.0004, outages=3)
                 for i in range(2)}
        coins = {k: carve_merge_holes(v, 30 if tf == "30m" else 60, 8, 7 + i) for i, (k, v) in enumerate(coins.items())}
        mk, prov_, pd_ = build_world(coins, tmp_path / tf, pick=make_pick(tf, w["exit"]), prov_kw=dict(warm=False), f11=prov)
        off = pd_.offered("select", mk)
        n_rule = n_tp = n_multi = n_f12 = 0
        for vid in ("F11.a", "F11.b", "F12.a", "F12.b"):
            v = KX.variant_by_id(vid)
            for q in range(0, len(off["coin"]), max(1, len(off["coin"]) // 25)):
                assert not compare_trade(mk, prov_, pd_, v, off, q), (tf, vid, q)
                out = call_trade_x(mk, pd_, v, off, q)[0]
                n_rule += out[2] == KX.R_RULE
                n_tp += out[2] == KX.R_TP
                if v.fam == KX.F12 and out[2] == KX.R_RULE:
                    n_f12 += 1
                    n_multi += bin(int(out[7])).count("1") >= 2
                    assert 0 < out[7] < 512
                else:
                    assert out[7] == 0
                hz = random_hz(q + 3)
                assert not compare_trade(mk, prov_, pd_, v, off, q, plc=True, hz=hz, seed=q + 99), (tf, vid, q, "placebo")
                assert call_trade_x(mk, pd_, v, off, q, plc=True, hz=hz, seed=q + 99)[0][7] == 0        # a placebo exit has no component
        assert n_rule >= 5 and n_tp >= 1 and n_f12 >= 3


# ====================================================================================================== T8: market-state labels (prereg 7)
def test_t8_market_state_labels_follow_regime5y_look_only_backwards_and_are_the_same_for_every_arm(tmp_path, vendor, monkeypatch):
    reg = DX.regime_module()
    assert (reg.ADX_TREND, reg.ADX_RANGE, reg.SLOPE_MIN, reg.VOL_Q, reg.VOL_DAYS, reg.VOL_MIN_DAYS) == (25.0, 20.0, 0.5, 0.80, 365, 180)
    assert DX.STATE_KO == {1: "추세장", 2: "횡보장", 3: "급변장", 4: "보통", 0: "모름"} and DX.STATE_ORDER == (1, 2, 3, 4, 0)
    coins = {SYMS[i]: synth_coin(131 + i, 420, (100.0, 3000.0)[i], vol=0.0006, drop=0.0, jump_p=0.0005) for i in range(2)}
    mk, prov, pd_ = build_world(coins, tmp_path, pick=make_pick("1h"), prov_kw=dict(warm=False))
    off = pd_.offered("select", mk)
    assert len(off["coin"]) > 200 and off["state"].dtype == np.int8
    seen = set()
    for c in range(2):
        df = pd_.frames[c][0]
        h, l, cl = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
        full = reg.regimes(h, l, cl, 60)["code"]
        a, b = pd_.cst[c], pd_.cen[c]
        assert np.array_equal(pd_.b_state[a:b], full)                                      # the labels are regime5y's own
        sel = off["coin"] == c
        assert np.array_equal(off["state"][sel], full[off["i0"][sel]])                        # a trade's label is its signal bar's
        seen |= set(off["state"][sel].tolist())
        cut = int(len(cl) * 0.6)                                                           # no look-ahead: bars 0..t only
        assert np.array_equal(reg.regimes(h[:cut], l[:cut], cl[:cut], 60)["code"], full[:cut])
        h2, l2, c2 = h.copy(), l.copy(), cl.copy()                                         # changing every bar after t changes nothing at t
        h2[cut:], l2[cut:], c2[cut:] = h[cut:] * 1.3, l[cut:] * 0.7, cl[cut:] * 1.1
        assert np.array_equal(reg.regimes(h2, l2, c2, 60)["code"][:cut], full[:cut])
    assert 0 in seen and len(seen) >= 3                                                    # 모름 (under 180 days of history) and several states occur
    # every arm labels the same signal the same way; the state table counts the closed trades once each
    edges = MT.month_edges("select")
    e0 = MT.summarize(KX.simulate(mk, pd_, KX.E0, 0.25, "select"), edges)
    key0 = dict(zip(zip(e0["tr_coin"].tolist(), e0["tr_side"].tolist(), e0["tr_fill"].tolist()), e0["tr_state"].tolist()))
    for vid in ("F3.a", "F4.m2.b", "F7h.H4.a"):
        sv = MT.summarize(KX.simulate(mk, pd_, KX.variant_by_id(vid), 0.25, "select"), edges)
        assert all(key0[k] == st for k, st in zip(zip(sv["tr_coin"].tolist(), sv["tr_side"].tolist(), sv["tr_fill"].tolist()), sv["tr_state"].tolist()) if k in key0)
        hs = MT.hold_by_state(sv["hold_h"], sv["tr_state"])
        assert list(hs) == ["추세장", "횡보장", "급변장", "보통", "모름"] and sum(x["n"] for x in hs.values()) == len(sv["hold_h"]) == sv["counts"][2]
        for code, name in DX.STATE_KO.items():
            m = sv["tr_state"] == code
            assert hs[name]["n"] == int(m.sum()) and hs[name]["few"] == (int(m.sum()) < 100)
            if m.any():
                assert hs[name]["median"] == float(np.median(sv["hold_h"][m])) and hs[name]["share_gt4"] == float((sv["hold_h"][m] > 4).mean())
    # pool_summary carries it, for the variant and for E0
    ps = MT.pool_summary({"p": sv}, {"p": e0})["all"]
    assert set(ps["hold_by_state"]) == set(ps["hold_by_state_e0"]) == {"추세장", "횡보장", "급변장", "보통", "모름"}
    # the thresholds are asserted at load: a copy of regime5y.py with another threshold is refused
    src = open(DX.REGIME_PATH, encoding="utf-8").read().replace("ADX_TREND, ADX_RANGE, SLOPE_MIN = 25.0, 20.0, 0.5", "ADX_TREND, ADX_RANGE, SLOPE_MIN = 26.0, 20.0, 0.5")
    assert src != open(DX.REGIME_PATH, encoding="utf-8").read()
    (tmp_path / "regime5y_changed.py").write_text(src)
    monkeypatch.setattr(DX, "REGIME_PATH", str(tmp_path / "regime5y_changed.py"))
    monkeypatch.setattr(DX, "_REGIME_MOD", None)
    with pytest.raises(AssertionError, match="ADX_TREND"):
        DX.regime_module()


# ====================================================================================================== T2: F7h, F12, the F11 coin flip; T4: strata z
@pytest.mark.parametrize("tf,tfm", [("15m", 15), ("30m", 30), ("1h", 60), ("4h", 240)])
@pytest.mark.parametrize("hrs", [4, 8, 16])
def test_t2_f7h_fires_at_the_first_close_at_or_after_c0_plus_h_also_when_that_bin_is_missing(tmp_path, vendor, tf, tfm, hrs):
    i0 = 3
    c0 = (i0 + 1) * tfm                                         # the signal bar's close (minutes after the data start)
    seg = [(c0 + hrs * 60 + 10 * 60, 100.0)]
    s = Scen(tmp_path / "a", seg, tf=tf, longs=[i0], pad=True)
    t = s.trade(f"F7h.H{hrs}.a")
    expect_exit(s, t, c0 + hrs * 60)                            # C0 + H is a close of every pick timeframe
    assert t["checks"] == hrs * 60 // tfm and t["d"] != 0
    # in bars: 4H on 15m, 2H on 30m, H on 1h, H / 4 on 4h
    assert hrs * 60 // tfm == {"15m": 4 * hrs, "30m": 2 * hrs, "1h": hrs, "4h": hrs // 4}[tf]
    # the bin that closes at C0 + H does not exist: the next close that exists acts
    gaps = list(range(c0 + hrs * 60 - tfm, c0 + hrs * 60))
    s2 = Scen(tmp_path / "b", seg, tf=tf, longs=[i0], pad=True, gaps=gaps)
    t2 = s2.trade(f"F7h.H{hrs}.b")
    expect_exit(s2, t2, c0 + hrs * 60 + tfm)
    # the stop and the take-profit still end it sooner; mode b has no take-profit: a rise through 3R does not end it
    s3 = Scen(tmp_path / "c", [(c0 + 60, 100.0), (60, 110.0), (hrs * 60 + 600, 110.0)], tf=tf, longs=[i0], pad=True)
    assert s3.trade(f"F7h.H{hrs}.a")["reason"] == KX.R_TP
    t3 = s3.trade(f"F7h.H{hrs}.b")
    assert t3["reason"] == KX.R_RULE and t3["off"] == c0 + hrs * 60


@pytest.mark.parametrize("mir", MIR)
def test_t4_strata_z_of_section_6_on_built_paths(tmp_path, vendor, mir, f11_on):
    sd = side_of(mir)
    pre = ([(60, 100), (60, 100), (30, 99.5), (30, 100), (60, 101.0)] + H(101, 101, 101) + H(101, 101) + [(20, 100.7), (40, 101.0)] + H(101, 101))
    sA = Scen(tmp_path / "a", pre + [(5, 100.6), (55, 100.6)], longs=[6], side_mirror=mir)        # a reference exists; Rc = -0.47 at the last check
    sB = Scen(tmp_path / "b", pre + [(5, 100.35), (55, 100.35)], longs=[6], side_mirror=mir)      # Rc = -0.68
    z = lambda t: t["trace"][:t["checks"], 5].tolist()                                            # noqa: E731
    tA1, tA0, tA5 = sA.trade("F6.w2.d0"), sA.trade("F6.w2.d0.5"), sA.trade("F1.w2.a")
    assert z(tA1)[-1] == 1 and z(tA0)[-1] == 0 and z(tA5)[-1] == 1                                # F6.d0.5 needs Rc < -0.5; F6.d0 any loss
    assert sB.trade("F6.w2.d0.5")["trace"][sB.trade("F6.w2.d0.5")["checks"] - 1, 5] == 1
    assert sum(z(sA.trade("F6.w2.d0.5"))) == 0                                                    # never below -0.5R: z = 0 at every check
    # F8: armed AND a reference; F9: a reference and (armed or Rc < -0.5)
    seg = ([(60, 100), (60, 100), (30, 99.5), (30, 100), (60, 101.0)] + H(101, 101, 101) + H(101, 101) + [(20, 100.7), (40, 101.0)] + H(101, 101)
           + [(5, 100.6), (55, 100.6)] + H(102.8) + [(5, 100.5), (55, 100.5)])
    s8 = Scen(tmp_path / "c", seg, longs=[6], side_mirror=mir)
    t8 = s8.trade("F8.w2.P1.a")
    k8 = t8["checks"]
    assert z(t8)[k8 - 1] == 1 and z(t8)[k8 - 2] == 1 and sum(z(t8)[:k8 - 2]) == 0                    # armed at bar 13, fires at bar 14
    assert sum(z(s8.trade("F8.w2.P2.a"))) == 0                                                    # never armed
    pre9 = [(60, 100)] * 4 + [(30, 99.8), (30, 100)] + [(60, 100)] * 4
    sa = Scen(tmp_path / "d", pre9 + H(101.5) + H(99.7), longs=[8], side_mirror=mir)
    ta = sa.trade("F9.a")
    assert z(ta) == [1, 1]                                                                         # armed at the first check (a gain of 1R)
    sb = Scen(tmp_path / "e", pre9 + H(99.7) + H(99.5), longs=[8], side_mirror=mir)
    tb = sb.trade("F9.a")
    assert z(tb) == [0, 1]                                                                         # unarmed and a small loss: z = 0; then below -0.5R
    sc = Scen(tmp_path / "f", pre9 + H(100.5) + H(99.7), longs=[8], side_mirror=mir)
    assert sum(z(sc.trade("F9.a"))) == 0                                                           # a gain under 1R is no arm; a loss over -0.5R never comes
    # F11: a state component counts only once armed (C3); an event component always; a finite level; the strategy's own flag
    seg11 = H(*([100] * 10))
    s11 = scen11(tmp_path / "g", seg11, [("state", dict(true_bars=(2, 3, 5)))], mir=mir)
    assert z(s11.trade("F11.a")) == [0, 0, 1]                                                      # true at i0 and 3: unarmed; false at 4; true at 5
    s11b = scen11(tmp_path / "h", seg11, [], lvl=None, mir=mir)                                    # a level-only strategy with a NaN level: no component
    assert sum(z(s11b.trade("F11.a"))) == 0
    s11c = scen11(tmp_path / "i", seg11, [], lvl=90.0, mir=mir)
    assert z(s11c.trade("F11.a")) == [1] * s11c.trade("F11.a")["checks"]
    def prov_flag(pick, sym, df, close, sl, ss):                                                   # F12_MSS_DISP style: its own flag false on bars 3 and 4
        out = f11_provider([("event", dict(true_bars=()))])(pick, sym, df, close, sl, ss)
        zf = np.ones(len(df), np.int8)
        zf[[3, 4]] = 0
        out["z_long"], out["z_short"] = zf, zf
        return out
    s11d = Scen(tmp_path / "j", seg11, longs=[2], side_mirror=mir, f11=prov_flag)
    assert z(s11d.trade("F11.a"))[:4] == [0, 0, 1, 1]
    # F12: z = 1 when a swing reference exists, F2 is armed, F5 is armed, or F11's z is 1; F3, F4, F7h and F10 set none
    ema_lo = np.full(40, 90.0)
    flat = H(*([100] * 14))
    s12 = Scen(tmp_path / "k", flat, longs=[2], side_mirror=mir, ema=np.full(40, 101.0), f11=f11_provider([]))     # no reference, F2 unarmed, nothing armed, no F11
    t12 = s12.trade("F12.a")
    expect_exit(s12, t12, 11 * 60, side=sd)                                                        # only the 8-hour clock fires: C0 = 3 h
    assert sum(z(t12)) == 0 and t12["comp"] == KX.CB_F7H
    s12b = Scen(tmp_path / "l", pre9 + H(100, 100, 100, 100, 100, 100, 100, 100), longs=[8], side_mirror=mir, ema=np.full(40, 101.0), f11=f11_provider([]))
    t12b = s12b.trade("F12.a")
    assert set(z(t12b)) == {1}                                                                     # the swing reference at 99.8 exists
    s12c = Scen(tmp_path / "m", flat, longs=[2], side_mirror=mir, ema=ema_lo, f11=f11_provider([]))
    assert set(z(s12c.trade("F12.a"))) == {1}                                                      # F2 armed (the close is above its average)
    s12d = Scen(tmp_path / "n", flat, longs=[2], side_mirror=mir, ema=np.full(40, 101.0), f11=f11_provider([], lvl=90.0))
    assert set(z(s12d.trade("F12.a"))) == {1}                                                      # F11's finite level


@pytest.mark.parametrize("mir", MIR)
def test_t2_f12_nine_components_one_exit_every_firing_component_recorded(tmp_path, vendor, mir, f11_on):
    sd = side_of(mir)
    pre9 = [(60, 100)] * 4 + [(30, 99.8), (30, 100)] + [(60, 100)] * 4
    no_f11 = f11_provider([])
    ema_lo = np.full(40, 90.0)
    # a close below the reference by a small loss: F1 alone; by more than 0.5R: F1 and F6 (the reference is shared)
    s1 = Scen(tmp_path / "a", pre9 + H(99.7) + H(99.7), longs=[8], side_mirror=mir, ema=ema_lo, f11=no_f11)
    t = s1.trade("F12.a")
    expect_exit(s1, t, 10 * 60, side=sd)
    assert t["comp"] == KX.CB_F1 and t["reason"] == KX.R_RULE
    s2 = Scen(tmp_path / "b", pre9 + H(99.5) + H(99.5), longs=[8], side_mirror=mir, ema=ema_lo, f11=no_f11)
    t = s2.trade("F12.a")
    expect_exit(s2, t, 10 * 60, side=sd)
    assert t["comp"] == KX.CB_F1 | KX.CB_F6 == 33
    # the mask is a record of the check, not an order: the same exit, price, minute and reason as F1 alone
    tf1 = s2.trade("F1.w3.a")
    assert tf1["off"] == t["off"] and tf1["px"] == t["px"] and tf1["reason"] == t["reason"] and tf1["comp"] == 0
    # the trade's wallet change is the one of a single rule exit: one fee, one slippage
    assert tf1["d"] == pytest.approx(t["d"], rel=1e-12)
    # F12.b has no fixed take-profit (the target of F11.b stays where there is one); F12.a keeps the pick's 3R
    s3 = Scen(tmp_path / "c", H(100, 100, 100, 104.0, 104.0, 104.0, 104.0, 104.0, 104.0, 104.0, 104.0, 104.0, 104.0), longs=[2], side_mirror=mir,
              ema=ema_lo, f11=no_f11)
    assert s3.trade("F12.a")["reason"] == KX.R_TP
    tb = s3.trade("F12.b")
    assert tb["reason"] == KX.R_RULE and tb["comp"] & KX.CB_F7H                                    # the 8-hour clock ends it
    # the account records the mask per signal; a RAND exit has none
    r = s2.account("F12.a")
    k = int(np.flatnonzero(r.reason == KX.R_RULE)[0])
    assert int(r.comp[k]) == 33
    r = s2.account("F12.a", placebo=True, hz=np.ones((KX.N_AGE, 2, 2)), seed_base=1)
    assert (r.reason == KX.R_RAND).any() and int(r.comp.sum()) == 0
    # metrics: components fired and fired alone, counted over the RULE exits
    s = MT.summarize(s2.account("F12.a"), MT.month_edges("select"))
    assert s["comp_fired"][0] == 1 and s["comp_alone"][0] == 0 and s["comp_fired"][5] == 1 and s["comp_alone"][5] == 0
    assert MT.COMP_LABELS == ("F1", "F2", "F3", "F4", "F5", "F6", "F7h", "F10", "F11")


@pytest.mark.parametrize("mir", MIR)
def test_t2_f12_first_trigger_wins_ties_record_every_component_and_components_act_alone(tmp_path, vendor, mir, f11_on):
    sd = side_of(mir)
    kw = dict(longs=[1], side_mirror=mir, ema=np.full(40, 90.0), f11=f11_provider([]))
    # a rise to 103, then 102.3: the chandelier (X - 2 ATR = 102.4) fires first, alone; the giveback (needs <= half the peak) does not yet
    s1 = Scen(tmp_path / "a", H(100, 100, 103, 102.3, 101.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0), **kw)
    t = s1.trade("F12.a")
    expect_exit(s1, t, 4 * 60, side=sd)
    assert t["comp"] == KX.CB_F4 and t["checks"] == 2          # the later firing of F5 is never recorded: the position is gone
    # a rise to 103, then 101.0 at once: F4 and F5 fire at the same check; one exit, both recorded, the same minute and price as F4 alone
    s2 = Scen(tmp_path / "b", H(100, 100, 103, 101.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0), **kw)
    t = s2.trade("F12.a")
    expect_exit(s2, t, 4 * 60, side=sd)
    assert t["comp"] == KX.CB_F4 | KX.CB_F5 == 24
    only4 = s2.trade("F4.m2.a")
    assert only4["off"] == t["off"] and only4["px"] == t["px"] and only4["d"] == pytest.approx(t["d"], rel=1e-12)
    # each component alone (the mask of the tests): the same exit as that family, and only the family's bit in the record
    for bit, vid in ((KX.CB_F4, "F4.m2.a"), (KX.CB_F5, "F5.P1.5.g50.a")):
        a = s2.trade(vid)
        v = f12_variant(bit)
        out = call_trade_x(s2.mk, s2.pd, v, s2.off, 0, scale=s2.scale, trace_rows=64)
        assert out[0][:7] == (a["d"], a["j"], a["reason"], a["lev"], a["px"], a["checks"], a["both"]) and out[0][7] == bit
    # the mask is a bit mask over the nine components in the reports' order
    assert [n for n, _b in KX.COMP_NAMES] == ["F1", "F2", "F3", "F4", "F5", "F6", "F7h", "F10", "F11"]
    # F3: the pick's opposite signal fires alone; F12.b has no fixed take-profit
    s3 = Scen(tmp_path / "c", H(100, 100, 100, 100, 100, 100), longs=[1], shorts=[3], side_mirror=mir, ema=np.full(40, 90.0), f11=f11_provider([]))
    t = s3.trade("F12.a")
    expect_exit(s3, t, 4 * 60, side=sd)                          # the signal bar 3 closes at 4 h
    assert t["comp"] == KX.CB_F3


def test_t2_f11_coin_flip_positions_use_mirrored_levels_and_targets():
    f = 99.98                                                    # the flip's fill (a short at 100 minus slippage)
    # the strategy is long with level 99.0 and target 102.0: a short flip gets 100.96 and 97.96 (mirrored around its own fill)
    inv, tgt = KX.flip_levels(1, -1, f, 99.0, 102.0)
    assert inv == pytest.approx(f + abs(f - 99.0)) and tgt == pytest.approx(f - (102.0 - f)) and inv > f > tgt
    assert KX.flip_levels(1, 1, f, 99.0, 102.0) == (99.0, 102.0)                                # a flip on the strategy's own side is the strategy's trade
    inv, tgt = KX.flip_levels(-1, 1, 100.02, 101.0, 98.0)                                       # a short strategy, a long flip
    assert inv == pytest.approx(100.02 - abs(100.02 - 101.0)) and tgt == pytest.approx(100.02 + (98.0 - 100.02) * -1.0 * 1)
    inv, tgt = KX.flip_levels(1, -1, f, 99.0, 99.5)                                             # a target at or behind the fill is no target
    assert math.isnan(tgt) and inv > f
    inv, tgt = KX.flip_levels(1, -1, f, float("nan"), float("nan"))
    assert math.isnan(inv) and math.isnan(tgt)                                                  # NaN in, none out (rule C7)


@pytest.mark.parametrize("mir", MIR)
def test_t2_f11_coin_flip_trade_fires_on_the_mirrored_level_and_target(tmp_path, vendor, f11_on, mir):
    sd = side_of(mir)
    flip_side = -sd
    f_flip = 100.0 * (1 + FILL_SLIP * flip_side)
    inv, tgt = KX.flip_levels(sd, flip_side, f_flip, 99.0 if not mir else 101.0, 102.0 if not mir else 98.0)
    # the flipped position is entered on the signal of the flip's side; its per-signal level and target are the mirrored ones
    def prov(pick, sym, df, close, sl, ss):
        n = len(df)
        lvl, tg = np.full(n, np.nan), np.full(n, np.nan)
        for i in np.flatnonzero(ss if flip_side < 0 else sl):
            lvl[i], tg[i] = inv, tgt
        key = "short" if flip_side < 0 else "long"
        return {"comp_long": [], "comp_short": [], "lvl_long": None, "lvl_short": None, "tgt_long": None, "tgt_short": None,
                f"lvl_{key}": lvl, f"tgt_{key}": tg}
    # (a) the price moves against the flip through its mirrored level: a rule exit at the first close beyond it
    seg = H(100, 100, 100, 100.5, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0)
    if flip_side > 0:
        seg = H(100, 100, 100, 99.5, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0)
    s = Scen(tmp_path / "a", seg, longs=[2] if flip_side > 0 else [], shorts=[2] if flip_side < 0 else [], f11=prov)
    t = s.trade("F11.a")
    assert t["reason"] == KX.R_RULE and t["off"] == 300                                         # the close of bar 4 (beyond the level) fires; bar 3 does not
    # (b) F11.b: the mirrored target is a maker limit at its level
    seg = H(100, 100, 100, 99.0, 97.5, 97.5, 97.5, 97.5, 97.5, 97.5)
    if flip_side > 0:
        seg = H(100, 100, 100, 101.0, 102.5, 102.5, 102.5, 102.5, 102.5, 102.5)
    s = Scen(tmp_path / "b", seg, longs=[2] if flip_side > 0 else [], shorts=[2] if flip_side < 0 else [], f11=prov)
    t = s.trade("F11.b")
    assert t["reason"] == KX.R_TP and t["px"] == pytest.approx(tgt, rel=1e-12)


# ====================================================================================================== T3: cut against full
def child_snapshot(data_dir, cut_ms, out_path, symbols, causal=True):
    """Run in a fresh process: the T3 snapshot of one side (cut or full data) with the synthetic provider."""
    import data_x as dx
    prov = Prov(data_dir, tuple(symbols), warm=False) if causal else NonCausalProv(data_dir, tuple(symbols), warm=False)
    snap = dx.snapshot(prov, tuple(symbols), int(cut_ms), [make_pick("1h"), make_pick("15m"), make_pick("4h")])
    np.savez(out_path, **{k.replace("/", "_"): v for k, v in snap.items()})


class NonCausalProv(Prov):
    """A deliberately wrong provider: its EMA looks one bar ahead. T3 must catch it."""

    def ema(self, df, n):
        return df["close"].ewm(span=n, adjust=False, min_periods=n).mean().shift(-1).to_numpy(float)


def run_side(data_dir, cut_ms, out_path, symbols, causal=True):
    code = ("import sys; sys.path.insert(0, %r); import test_exitflex as T; T.child_snapshot(%r, %d, %r, %r, %r)"
            % (HERE, data_dir, cut_ms, out_path, tuple(symbols), causal))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600,
                       env={**os.environ, "PYTHONPATH": ""})
    assert r.returncode == 0, r.stderr[-2000:]
    with np.load(out_path) as z:
        return {k: z[k] for k in z.files}


def test_t3_cut_arrays_agree_with_full_arrays_at_several_cut_times(tmp_path, vendor):
    syms = SYMS[:2]
    coins = {SYMS[0]: synth_coin(51, 45, 100.0, vol=0.0007, drop=0.003, outages=3), SYMS[1]: synth_coin(52, 45, 3000.0, vol=0.0007, drop=0.003, outages=3)}
    src = write_folder(str(tmp_path / "src"), coins)
    pin = "ab" * 32
    cuts = [START + (5 * 1440) * MIN, START + (12 * 1440 + 13 * 60 + 37) * MIN, START + (20 * 1440 + 7 * 60 + 5) * MIN,
            START + (30 * 1440) * MIN]
    for k, cut in enumerate(cuts):
        cdir = DX.write_cut(src, str(tmp_path / "work"), pin, cut, symbols=syms)
        assert DX.verify_cut(cdir, syms)
        for s_ in syms:                                              # the cut arrays hold no minute at or after the cut
            d = DX._load_npz(os.path.join(cdir, "1m", f"{s_}.npz"))
            assert d["ts"][-1] < cut and d["ts"][-1] >= cut - 5 * MIN
            full = DX._load_npz(os.path.join(src, "1m", f"{s_}.npz"))
            n = len(d["ts"])
            assert all(np.array_equal(d[key], full[key][:n]) for key in d)          # a prefix of the full arrays
        a = run_side(cdir, cut, str(tmp_path / f"cut{k}.npz"), syms)
        b = run_side(src, cut, str(tmp_path / f"full{k}.npz"), syms)
        assert sorted(a) == sorted(b) and len(a) > 100
        bad = [key for key in a if not np.array_equal(a[key], b[key], equal_nan=True)]
        assert not bad, bad[:5]
        # every cut frame's last bar closes at or before the cut
        for key in a:
            if key.endswith("|close_ms"):
                assert a[key][-1] <= cut
        shutil_rm(cdir)
    # the check has teeth: a provider that looks ahead is caught
    cut = cuts[1]
    cdir = DX.write_cut(src, str(tmp_path / "work"), pin, cut, symbols=syms)
    a = run_side(cdir, cut, str(tmp_path / "ncut.npz"), syms, causal=False)
    b = run_side(src, cut, str(tmp_path / "nfull.npz"), syms, causal=False)
    assert any(not np.array_equal(a[key], b[key], equal_nan=True) for key in a)
    shutil_rm(cdir)


def shutil_rm(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def test_t3_cut_folder_digest_and_pin(tmp_path):
    coins = {SYMS[0]: synth_coin(61, 5, 100.0)}
    src = write_folder(str(tmp_path / "src"), coins)
    pin_doc = DX.make_pin(src.replace("/1m", ""), str(tmp_path / "work"), symbols=(SYMS[0],)) if os.path.exists(os.path.join(src, "build.json")) else None
    assert pin_doc is None                                            # make_pin needs build.json, which data.py writes
    with open(os.path.join(src, "build.json"), "w") as fh:
        fh.write("{}")
    pin_doc = DX.make_pin(src, str(tmp_path / "work"), symbols=(SYMS[0],))
    DX.verify_data(pin_doc)
    cut = START + 2 * 1440 * MIN
    d1 = DX.write_cut(src, str(tmp_path / "work"), "cd" * 32, cut, symbols=(SYMS[0],))
    assert d1 == DX.cut_dir(str(tmp_path / "work"), "cd" * 32, cut) and DX.verify_cut(d1, (SYMS[0],))
    assert DX.write_cut(src, str(tmp_path / "work"), "cd" * 32, cut, symbols=(SYMS[0],)) == d1        # reused
    with np.load(os.path.join(d1, "1m", f"{SYMS[0]}.npz")) as z:
        arrays = {k: z[k] for k in z.files}
    arrays["o"] = arrays["o"].copy()
    arrays["o"][3] += 1e-9
    np.savez_compressed(os.path.join(d1, "1m", f"{SYMS[0]}.npz"), **arrays)
    assert not DX.verify_cut(d1, (SYMS[0],))                         # a changed byte is caught by the digest
    with pytest.raises(AssertionError):
        DX.assert_no_minute_at_or_after({SYMS[0]: {"ts": np.array([cut])}}, cut)
    with open(os.path.join(src, "build.json"), "w") as fh:
        fh.write("{ }")
    with pytest.raises(DX.PinError):
        DX.verify_data(pin_doc)                                      # any other file is refused
    with pytest.raises(DX.PinError):
        DX.load_pin(str(tmp_path / "nope.json"))


# ====================================================================================================== T5: causality of decisions
def rewrite_after(coin, idx, seed, vol=0.004):
    """The same coin with every minute from index ``idx`` on replaced by another random path (OHLC, mark and funding); the
    timestamps and the minutes before stay."""
    rng = np.random.default_rng(seed)
    c = {k: v.copy() for k, v in coin.items()}
    n = len(c["ts"]) - idx
    base = c["c"][idx - 1]
    cc = base * np.exp(np.cumsum(rng.normal(0, vol, n)))
    oo = np.r_[base, cc[:-1]] * (1 + rng.normal(0, vol / 4, n))
    span = np.abs(rng.normal(0, vol / 2, n))
    hh, ll = np.maximum(oo, cc) * (1 + span), np.minimum(oo, cc) * (1 - span)
    c["o"][idx:], c["c"][idx:], c["h"][idx:], c["l"][idx:] = oo, cc, hh, ll
    c["mo"][idx:], c["mc"][idx:], c["mh"][idx:], c["ml"][idx:] = oo, cc, hh, ll
    fm = c["fund"][idx:] != 0
    c["fund"][idx:] = np.where(fm, rng.normal(3e-4, 2e-4, n), 0.0)                  # the funding of minute j and later changes too (step 0)
    return c


MIDDLE = ["F1.w3.a", "F1.w3.a.q15", "F2.n20.a", "F3.a", "F4.m2.a", "F4.m2.a.q15", "F5.P1.5.g25.a", "F6.w3.d0.5", "F7.N24.a",
          "F7h.H8.a", "F8.w3.P1.a", "F9.a", "F9.a.q15", "F10.N6.a", "F11.a", "F11.b", "F12.a", "F12.b"]


def causal_f11(pick, sym, df, close, sl, ss):
    n = len(df)
    c = df["close"].to_numpy(float)
    ema = df["close"].ewm(span=12, adjust=False).mean().to_numpy(float)
    rng = np.random.default_rng(7)
    lvl_l, lvl_s, tg_l, tg_s = (np.full(n, np.nan) for _ in range(4))
    lvl_l[sl], lvl_s[ss] = c[sl] * 0.995, c[ss] * 1.005
    tg_l[sl], tg_s[ss] = c[sl] * 1.01, c[ss] * 0.99
    return {"comp_long": [("state", (c < ema).astype(float)), ("event", (rng.random(n) < 0.03).astype(float))],
            "comp_short": [("state", (c > ema).astype(float)), ("event", (rng.random(n) < 0.03).astype(float))],
            "lvl_long": lvl_l, "lvl_short": lvl_s, "tgt_long": tg_l, "tgt_short": tg_s}


def test_t5_decisions_do_not_depend_on_minute_j_or_anything_later(tmp_path, vendor, f11_on):
    """Synthetic paths, the whole pipeline recomputed: replace every minute from the check minute j on (and with them every
    chart bar closing after the check close) by another path. The frozen decision state of every check up to and including
    the one at j - fire flag, stratum, arm flag, reference level, Rc, Rpk, the placebo draw - is identical."""
    n_pairs = 0
    for tf in ("1h", "4h"):
        w = DIFF_WORLDS[tf]
        prices = (100.0, 3000.0)
        coins = {SYMS[i]: synth_coin(71 + i, w["days"], prices[i], vol=w["vol"], drop=0.003, outages=2) for i in range(2)}
        mk, prov, pd_ = build_world(coins, tmp_path / tf / "a", pick=make_pick(tf, w["exit"]), prov_kw=dict(warm=False), f11=causal_f11)
        off = pd_.offered("select", mk)
        rng = np.random.default_rng(3)
        for vid in MIDDLE:
            v = KX.variant_by_id(vid)
            done = 0
            for q in rng.permutation(len(off["coin"])):
                if done >= 2:
                    break
                for plc in (False, True) if PL.has_placebo(v) else (False,):
                    hz = random_hz(int(q))
                    out, num, den, trace = KX.simulate_trade(mk, pd_, v, off, int(q), 0.25, "select", True, plc, hz, 5, 6000)
                    nchk = out[5]
                    if nchk < 3:
                        break
                    for k in sorted({1, nchk // 2 + 1, nchk}):
                        j = int(trace[k - 1, 0])
                        c = int(off["coin"][q])
                        new_coin = rewrite_after(coins[SYMS[c]], j, seed=k * 31 + 1)
                        coins2 = dict(coins)
                        coins2[SYMS[c]] = new_coin
                        wdir = tmp_path / tf / f"{vid}_{plc}_{int(q)}_{k}"
                        mk2, prov2, pd2 = build_world(coins2, wdir, pick=make_pick(tf, w["exit"]),
                                                      prov_kw=dict(warm=False), f11=causal_f11)
                        pd2.chart(v)                                             # builds the 15m frames of a q15 variant
                        shutil_rm(str(wdir))                                     # the arrays are in memory; keep the disk free
                        off2 = pd2.offered("select", mk2)
                        hit = np.flatnonzero((off2["coin"] == c) & (off2["i0"] == off["i0"][q]) & (off2["side"] == off["side"][q]))
                        assert len(hit) == 1
                        out2, _n2, _d2, trace2 = KX.simulate_trade(mk2, pd2, v, off2, int(hit[0]), 0.25, "select", True, plc, hz, 5, 6000)
                        assert out2[5] >= k
                        assert np.array_equal(trace[:k], trace2[:k], equal_nan=True), (tf, vid, k, plc)
                        n_pairs += 1
                done += 1
    assert n_pairs >= 150


# ====================================================================================================== metrics, data and variants
import runner_x as RX  # noqa: E402


def test_variants_registry_matches_the_prereg_list(f11_on):
    vs = KX.variants()
    assert len(vs) == 88 and len({v.id for v in vs}) == 88
    ids = [v.id for v in vs]
    for must in ("F1.w3.a", "F1.w3.b.q15", "F2.n20.b", "F3.a", "F4.m1.5.a", "F4.m2.b.q15", "F5.P1.5.g25.a", "F6.w2.d0", "F6.w2.d0.5",
                 "F7.N24.b", "F7h.H8.a", "F7h.H4.b", "F7h.H16.a", "F8.w3.P1.a", "F9.a", "F9.b.q15", "F10.N6.a", "F11.a", "F11.b",
                 "F12.a", "F12.b", "F13.a", "F13.b", "F5.P1.g50.b"):
        assert must in ids
    assert ids[:6] == ["F1.w2.a", "F1.w2.b", "F1.w3.a", "F1.w3.b", "F1.w5.a", "F1.w5.b"]
    assert ids[-6:] == ["F11.a", "F11.b", "F12.a", "F12.b", "F13.a", "F13.b"]
    by = {}
    for v in vs:
        by.setdefault(v.famname + (".q15" if v.q15 else ""), []).append(v)
    assert {k: len(x) for k, x in by.items()} == {"F1": 6, "F1.q15": 6, "F2": 6, "F3": 2, "F4": 6, "F4.q15": 6, "F5": 12, "F6": 6, "F7": 6,
                                                  "F7h": 6, "F8": 12, "F9": 2, "F9.q15": 2, "F10": 4, "F11": 2, "F12": 2, "F13": 2}
    assert all(v.mode == "a" for v in by["F6"])
    assert {v.famname: v.group for v in vs} == {"F1": "S", "F2": "M", "F3": "O", "F4": "C", "F5": "G", "F6": "S", "F7": "T", "F7h": "T",
                                                "F8": "S", "F9": "S", "F10": "L", "F11": "N", "F12": "A", "F13": "P"}
    npar = {k: {v.nparams for v in x} for k, x in by.items()}
    assert npar["F3"] == {0} and npar["F11"] == {0} and npar["F9"] == {3} and npar["F9.q15"] == {4} and npar["F1"] == {1}
    assert npar["F1.q15"] == {2} and npar["F5"] == {2} and npar["F6"] == {2} and npar["F8"] == {2} and npar["F4.q15"] == {2}
    assert npar["F7h"] == {1} and npar["F12"] == {8} and npar["F13"] == {0}
    assert [v.order for v in vs] == list(range(1, 89))
    assert KX.F11_REGISTRY["modes"] == ("a", "b") and len(KX.variants(include_f11=False)) == 84      # F11 and F12 need the provider; F13 does not
    # 5.3: 74 variants outside F7, F7h and F13 reach the placebo step (F12 has one); the loss-cut categories; the default set D has 37
    assert sum(PL.has_placebo(v) for v in vs) == 74 and not any(PL.has_placebo(v) for v in by["F7"] + by["F7h"] + by["F13"])
    cls = {k: {MT.loss_class(v) for v in x} for k, x in by.items()}
    assert cls["F5"] == {"L0"} and cls["F8"] == {"L0"} and cls["F10"] == {"L0"} and cls["F9"] == {"L1"} and cls["F9.q15"] == {"L1"}
    assert cls["F1"] == {"L2"} and cls["F1.q15"] == {"L2"} and cls["F11"] == {"L3"} and cls["F12"] == {"L3"} and cls["F7h"] == {"L3"}
    assert cls["F13"] == {"L0"}
    assert {MT.loss_class(v) for v in by["F6"] if v.params["d"] == 0.5} == {"L1"} and {MT.loss_class(v) for v in by["F6"] if v.params["d"] == 0} == {"L2"}
    assert sum(MT.in_default_set(v) for v in vs) == 37 and not any(MT.in_default_set(v) for v in by["F12"])
    assert all(MT.in_default_set(v) for v in by["F13"]) and sum(MT.in_default_set(v) for v in vs if v.famname != "F13") == 35
    # F12's fixed values are the middle of each grid (5.2), the larger of a two-value grid
    assert KX.F12_PARAMS == {"w": 3, "n": 20, "m": 2.0, "P": 1.5, "g": 0.5, "d": 0.5, "H": 8, "N": 12}
    assert [b for _n, b in KX.COMP_NAMES] == [1, 2, 4, 8, 16, 32, 64, 128, 256]


def test_metrics_monthly_growth_and_Mp_identity():
    edges = MT.month_edges("select")
    assert len(edges) == 37 and MT.n_months("select") == 36 and MT.n_months("confirm") == 33
    assert edges[0] == DX.PERIOD_MS["select"][0] and edges[-1] == DX.PERIOD_MS["select"][1]
    ex = np.array([edges[1] - 1, edges[1] + 5, edges[4] + 10], np.int64)       # two trades in January/February, one in May
    pnl = np.array([100.0, -50.0, 400.0])
    g, W = MT.monthly_g(ex, pnl, 5000.0, edges)
    assert W[0] == 5100.0 and W[1] == 5050.0 and W[2] == 5050.0 and W[4] == 5450.0 and W[-1] == 5450.0
    assert g[0] == pytest.approx(math.log(5100 / 5000)) and g[1] == pytest.approx(math.log(5050 / 5100)) and g[2] == 0.0
    assert g.sum() == pytest.approx(math.log(5450 / 5000))
    g0, _ = MT.monthly_g(np.zeros(0, np.int64), np.zeros(0), 5000.0, edges)
    assert (g0 == 0).all()


def test_metrics_bootstrap_holm_and_selection_rule():
    rng = np.random.default_rng(0)
    up = rng.normal(0.01, 0.002, 33)
    assert MT.block_bootstrap_p(up, 1) == pytest.approx(1 / 2001)               # a plainly positive series: the smallest p
    assert MT.block_bootstrap_p(-up, 1) == pytest.approx(1.0, abs=1e-3)
    assert MT.block_bootstrap_p(up, 7) == MT.block_bootstrap_p(up, 7)             # same seed, same p
    m = MT.block_means(up, 500, 3)
    assert m.shape == (500,) and abs(m.mean() - up.mean()) < 0.001
    lo, hi = MT.block_bootstrap_ci(up, 3)
    assert lo < up.mean() < hi
    noisy = rng.normal(0.0, 0.02, 33)
    assert 0.0 < MT.iid_bootstrap_p(noisy, 5) <= 1.0
    # Holm: one pair p < 0.05; two pairs: the smaller < 0.025, then the larger < 0.05
    assert MT.holm({"a": 0.04}) == {"a": True} and MT.holm({"a": 0.06}) == {"a": False}
    assert MT.holm({"a": 0.02, "b": 0.04}) == {"a": True, "b": True}
    assert MT.holm({"a": 0.03, "b": 0.04}) == {"a": False, "b": False}
    assert MT.holm({"a": 0.01, "b": 0.06}) == {"a": True, "b": False}
    # eligibility
    pl = np.linspace(-0.01, 0.01, 200)
    e = MT.eligibility(0.02, [0.01] * 14 + [-0.01] * 9, 100, 100, pl, False)
    assert e["eligible"] and e["need_picks"] == 14
    assert not MT.eligibility(0.02, [0.01] * 13 + [-0.01] * 10, 100, 100, pl, False)["eligible"]
    assert not MT.eligibility(0.02, [0.01] * 20, 99, 100, pl, False)["eligible"]
    assert not MT.eligibility(0.005, [0.01] * 20, 100, 100, pl, False)["eligible"]               # below the placebo's 95th percentile
    assert MT.eligibility(0.005, [0.01] * 20, 100, 100, None, True)["eligible"]                    # F7 has no placebo gate
    assert MT.eligibility(0.01, [0.01] * 9 + [-0.01] * 6, 10, 10, pl, True)["need_picks"] == 9
    # (the choice by hand and the default of 8.4 are tested in the T7 tests below)
    v = MT.confirm_verdict(True, 0.02, np.linspace(-0.01, 0.01, 200), False, 100, 100)
    assert v["pass"] and not MT.confirm_verdict(False, 0.02, np.linspace(-0.01, 0.01, 200), False, 100, 100)["pass"]
    assert not MT.confirm_verdict(True, 0.02, np.linspace(-0.01, 0.01, 200), False, 99, 100)["pass"]
    assert MT.confirm_verdict(True, 0.001, None, True, 100, 100)["pass"]


def test_metrics_summary_counts_and_changed_trades(world_1h):
    mk, prov, pd_ = world_1h
    edges = MT.month_edges("select")
    e0 = KX.simulate(mk, pd_, KX.E0, 0.25, "select")
    v = KX.simulate(mk, pd_, KX.variant_by_id("F4.m2.a"), 0.25, "select")
    s0, sv = MT.summarize(e0, edges), MT.summarize(v, edges)
    c = s0["counts"]
    assert int(c[0]) == int(c[1] + c[3] + c[4] + c[5] + c[6])                      # offered = entered + skipped + rejected + no fill + after bust
    assert float(s0["w_end"]) == pytest.approx(float(s0["w0"]) + s0["tr_pnl"].sum(), rel=1e-12)
    assert MT.changed_trades(s0, s0) == 0 and MT.changed_trades(sv, s0) > 0
    assert MT.pick_Mp(s0, s0) == 0.0
    assert MT.pick_Mp(sv, s0) == pytest.approx((math.log(float(sv["w_end"])) - math.log(float(s0["w_end"]))) / 36)
    ps = MT.pool_summary({"x": sv, "y": sv}, {"x": s0, "y": s0})
    assert set(ps) == {"all", "core"} and ps["all"]["M"] == pytest.approx(MT.pick_Mp(sv, s0))
    # the eighth pass: every entered trade also keeps its leverage and exit price (the extra reads), in the order of the other tr_ arrays
    ent = np.flatnonzero(v.status == 1)
    assert len(sv["tr_lev"]) == len(sv["tr_xpx"]) == len(sv["tr_pnl"]) == len(ent) > 0
    assert np.array_equal(sv["tr_lev"], v.lev[ent].astype(np.float64)) and np.array_equal(sv["tr_xpx"], v.xpx[ent].astype(np.float64), equal_nan=True)
    assert (sv["tr_lev"] > 0).all()
    ps2 = MT.pool_summary({"x": sv, "y": sv}, {"x": s0, "y": s0}, {"x": "core", "y": "ds"})
    assert set(ps2) == {"all", "core", "ds"} and ps2["core"]["n_picks"] == 1
    assert ps["all"]["hold"]["median"] == pytest.approx(float(np.median(sv["hold_h"])))
    assert ps["all"]["entered"] == 2 * int(sv["counts"][1])


def test_data_swings_and_reference_path_match_the_kernel(world_1h):
    mk, prov, pd_ = world_1h
    c = 0
    a, b = pd_.cst[c], pd_.cen[c]
    h, l, cl = pd_.b_hi[a:b], pd_.b_lo[a:b], pd_.b_cl[a:b]
    for w in (2, 3, 5):
        swl, swh, slo, shi = pd_.swings(w)
        swl, swh, slo, shi = swl[a:b], swh[a:b], slo[a:b], shi[a:b]
        tl, ts_ = K.structure_levels(h, l, cl, w, 300)
        assert np.array_equal(slo, ts_, equal_nan=True) and np.array_equal(shi, tl, equal_nan=True)
        rng = np.random.default_rng(w)
        for p in rng.integers(w, len(l) - w, 200):
            nb = [q for q in range(p - w, p + w + 1) if q != p]
            assert bool(swl[p]) == all(l[p] < l[q] for q in nb) and bool(swh[p]) == all(h[p] > h[q] for q in nb)
    off = pd_.offered("select", mk)
    v = KX.variant_by_id("F1.w3.a")
    swl, swh, slo, shi = pd_.swings(3)
    n_ok = 0
    for q in range(0, len(off["coin"]), 4):
        out, _n, _d, tr = call_trade_x(mk, pd_, v, off, q, trace_rows=2000)
        if out[5] < 3:
            continue
        cc = int(off["coin"][q])
        a2, b2 = pd_.cst[cc], pd_.cen[cc]
        i0, side = int(off["i0"][q]), int(off["side"][q])
        path = DX.ref_path(swl[a2:b2], swh[a2:b2], pd_.b_lo[a2:b2], pd_.b_hi[a2:b2], (slo if side > 0 else shi)[a2 + i0], 3, side, i0,
                           min(b2 - a2 - 1, i0 + out[5] + 400))
        for k in range(out[5]):
            kk_bar = int(np.searchsorted(pd_.b_cms[a2:b2], tr[k, 1]))                # the check close is the close of this bar
            if kk_bar - i0 < len(path):
                want = path[kk_bar - i0]
                assert (np.isnan(want) and np.isnan(tr[k, 7])) or want == tr[k, 7]
        n_ok += 1
    assert n_ok >= 3


def test_data_offered_signals_are_ordered_filtered_and_in_the_period(world_1h):
    mk, prov, pd_ = world_1h
    off = pd_.offered("select", mk)
    assert (np.diff(off["fill"]) >= 0).all()
    same = np.flatnonzero(np.diff(off["fill"]) == 0)
    assert (off["coin"][same] <= off["coin"][same + 1]).all()                       # ties: coin priority
    assert np.isfinite(off["atr"]).all() and (off["atr"] > 0).all()
    lo, hi = DX.PERIOD_MS["select"]
    assert (off["close"] >= lo).all() and (off["close"] < hi).all()
    pend = mk.period_end("select")
    for c in range(2):                                                               # fills open before the period's last minute
        sel = off["coin"] == c
        last_ts = mk.cat["ts"][pend[c] - 1]
        assert (off["fill"][sel] < last_ts).all()
    assert DX.PERIOD_MS["select"] == (R.PERIOD_MS[R.P_SELECT][1], R.PERIOD_MS[R.P_SELECT][2])
    assert DX.PERIOD_MS["confirm"] == (R.PERIOD_MS[R.P_TEST][1], R.PERIOD_MS[R.P_TEST][2])


def test_data_both_flags_on_one_bar_offer_the_long_first(tmp_path, vendor):
    s = Scen(tmp_path, H(*([100] * 8)), longs=[3], shorts=[3], strict_flags=False)
    assert s.off["side"].tolist() == [1, -1] and s.off["i0"].tolist() == [3, 3]
    # prereg 3: a bar with both flags stops the run when the assertion is on (the default)
    with pytest.raises(AssertionError, match="both a long and a short"):
        Scen(tmp_path / "strict", H(*([100] * 8)), longs=[3], shorts=[3])


def test_data_picks_are_the_38_of_the_prereg():
    ps = DX.picks()
    assert len(ps) == 38 and sum(p["pool"] == "core" for p in ps) == 23 and sum(p["pool"] == "ds" for p in ps) == 15
    ids = [p["id"] for p in ps]
    for must in ("core-DOGE-15m-1", "core-N03_ADX_GC-30m-3", "core-OBV_S-1h-3", "core-S4_BB_BBP-4h-1", "ds-F10_OTE-1h-1", "ds-F7_RF_ONLY-1h-3",
                 "ds-F9_FVG-4h-1"):
        assert must in ids
    byid = {p["id"]: p for p in ps}
    assert K.EXITS[byid["core-OBV_S-1h-3"]["exit_index"]][:3] == ("roe50|4", 4.0, K.TP_ROE)
    assert K.EXITS[byid["core-S4_BB_BBP-30m-1"]["exit_index"]][:3] == ("tp2R|2", 2.0, K.TP_R)
    tfs = [p["tf"] for p in ps if p["pool"] == "core"]
    assert (tfs.count("15m"), tfs.count("30m"), tfs.count("1h"), tfs.count("4h")) == (4, 7, 6, 6)
    tfs = [p["tf"] for p in ps if p["pool"] == "ds"]
    assert (tfs.count("15m"), tfs.count("30m"), tfs.count("1h"), tfs.count("4h")) == (1, 1, 6, 7)


def test_bar_ms_parameter_reproduces_the_replica_close_shift(tmp_path):
    """kernel_x takes the bar length: on 5-minute bars the fill is the first bar at or after the close (hc.py's shift)."""
    n = 40 * 288
    ts = START + np.arange(n, dtype=np.int64) * 300_000
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[100.0, c[:-1]]
    d = {"ts": ts, "o": o, "h": np.maximum(o, c) * 1.0005, "l": np.minimum(o, c) * 0.9995, "mo": o, "mh": np.maximum(o, c) * 1.0005,
         "ml": np.minimum(o, c) * 0.9995, "fund": np.zeros(n)}
    mk = DX.Market.from_arrays([d], EX)
    mk.bar_ms = 300_000
    closes = START + (np.arange(20, n - 50, 37)) * 300_000
    sig = dict(close=closes.astype(np.int64), coin=np.zeros(len(closes), np.int64), side=np.where(np.arange(len(closes)) % 2 == 0, 1, -1).astype(np.int64),
               atr=np.full(len(closes), 0.4), best=np.zeros(len(closes), bool), tp=np.full(len(closes), np.nan))
    a = K.account(mk.S(0.25), mk.brs, mk.cat["ts"], mk.cat["o"], mk.cat["h"], mk.cat["l"], mk.cat["mo"], mk.cat["mh"], mk.cat["ml"],
                  mk.cat["fund"], mk.starts, mk.ends, sig["coin"], sig["close"] - 240_000, sig["side"], sig["atr"], sig["best"],
                  mk.qty_steps, mk.min_notionals, *K.exit_args(0), sig["tp"])          # hc.py: every close shifted by 60,000 - bar_ms
    z = np.zeros(1, np.int64)
    PT, PF, QT = KX.empty_chart()
    num, den = KX.new_counts()
    b = KX.account_x(mk.S(0.25), mk.brs, mk.cat["ts"], mk.cat["o"], mk.cat["h"], mk.cat["l"], mk.cat["mo"], mk.cat["mh"], mk.cat["ml"],
                     mk.cat["fund"], mk.starts, mk.ends, sig["coin"], sig["close"], sig["side"], sig["atr"], sig["best"],
                     np.zeros(len(closes), np.int64), mk.qty_steps, mk.min_notionals, *K.exit_args(0), sig["tp"], False, KX.rp_vector(),
                     PT, PF, z, z, QT, z, z, False, np.zeros((KX.N_AGE, 2, 2)), 0, num, den, np.zeros(2 * KX.NC, np.int8),
                     np.full(len(closes), np.nan), 300_000)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]) and np.array_equal(a[2], b[3]) and np.array_equal(a[3], b[4])
    assert a[5] == b[7] and (a[0] == 1).sum() >= 5


# ====================================================================================================== runner: stages on a synthetic universe
SYN_VARIANTS = ["F1.w3.a", "F2.n20.b", "F3.a", "F4.m2.b", "F4.m2.a.q15", "F5.P1.g50.a", "F6.w2.d0", "F7.N12.a", "F7h.H8.a", "F8.w3.P1.a",
                "F9.a", "F10.N6.a", "F11.a", "F11.b", "F12.a", "F12.b", "F13.a", "F13.b"]


def syn_pick(kind, tf, exit_name, n=1):
    return {"id": f"{kind}-SYN-{tf}-{n}", "kind": kind, "pool": kind, "name": "SYN", "tf": tf, "combo": {}, "exit": exit_name,
            "exit_index": [e[0] for e in K.EXITS].index(exit_name), "rank": n}


def syn_cfg(tmp, period="select", stage=None, n_seeds=20, procs=1, variants=SYN_VARIANTS, seed=81, days=70):
    """A two-coin, four-pick (two per pool) synthetic universe in a temporary layout, as a runner Config."""
    start = DX.PERIOD_MS[period][0]
    coins = {SYMS[i]: synth_coin(seed + i, days, (100.0, 3000.0)[i], vol=0.0004, drop=0.003, start_ms=start, open_gap_p=0.0002, outages=2)
             for i in range(2)}
    folder = write_folder(str(tmp / "data"), coins)
    prov = Prov(folder, SYMS[:2], warm=False)
    mk = DX.Market.from_arrays([coins[s] for s in SYMS[:2]], EX, symbols=SYMS[:2])
    picks = [syn_pick("core", "1h", "tp3R|4"), syn_pick("core", "4h", "tp3R|2"), syn_pick("ds", "1h", "tp3R|4"), syn_pick("ds", "4h", "tp3R|2")]
    KX.register_f11(lambda *a, **k: None)
    lay = RX.Layout(base=str(tmp / "repo" / "exitflex"), root=str(tmp / "repo"), required=())      # $WORK lies outside the 'repository'
    os.makedirs(lay.out, exist_ok=True)
    pin = {"work": str(tmp / "work"), "data_dir": folder}
    cfg = RX.Config(lay, pin, "cd" * 32, stage or period, period, mk, picks, [KX.variant_by_id(v) for v in variants],
                    lambda pick: DX.PickData(mk, pick, prov, f11=causal_f11), n_seeds, procs)
    return cfg


FORCED_PAIRS = {("F1.w3.a", "core"), ("F4.m2.b", "core"), ("F11.a", "core"), ("F7.N12.a", "core"), ("F7h.H8.a", "core"), ("F12.a", "core"),
                ("F1.w3.a", "ds"), ("F4.m2.b", "ds"), ("F3.a", "ds"), ("F12.b", "ds"), ("F7h.H8.a", "ds"), ("F13.a", "core"), ("F13.b", "ds")}


def forced_gates(cfg, orig):
    """The step-1 gates with gates 1, 2 and 4 forced open for some pairs: a random-walk universe has no variant that beats E0, so
    this is how the synthetic run reaches step 2."""
    g = orig(cfg)
    for k in FORCED_PAIRS:
        if k in g:
            g[k] = dict(g[k], g1=True, g2=True, g4=True)
    return g


@pytest.fixture(scope="module")
def syn_select(tmp_path_factory, vendor):
    tmp = tmp_path_factory.mktemp("syn")
    cfg = syn_cfg(tmp)
    orig = RX.step1_gates
    RX.step1_gates = lambda c: forced_gates(c, orig)
    try:
        doc = RX.finish_select(cfg, {"n_seeds": 20})
    finally:
        RX.step1_gates = orig
    yield cfg, doc
    KX.clear_f11()


def test_runner_select_writes_the_documented_files_and_keeps_deepseek_money_private(syn_select):
    cfg, doc = syn_select
    out, work = cfg.lay.out, os.path.join(cfg.store.work, cfg.store.pin8)
    assert sorted(os.listdir(out)) == ["SELECT_KO.md", "select.json"]
    assert os.path.exists(os.path.join(work, "results", "select", "SELECT_TABLE.csv")) and os.path.exists(os.path.join(work, "ds_private", "select_ds.json"))
    assert os.path.isdir(os.path.join(work, "results", "select", "core-SYN-1h-1")) and not os.path.exists(os.path.join(work, "results", "select", "ds-SYN-1h-1"))
    assert os.path.isdir(os.path.join(work, "ds_private", "results", "select", "ds-SYN-1h-1"))
    j = json.load(open(os.path.join(out, "select.json")))
    assert j["pin"] == "cd" * 32 and j["n_seeds"] == 20 and j["f11"] is True and j["complete_menu"] is False
    assert j["ds_private_sha256"] == DX.sha256_file(os.path.join(work, "ds_private", "select_ds.json"))
    rp = os.path.join(work, "ds_private", "owner_report_select.md")
    assert j["ds_owner_report_sha256"] == DX.sha256_file(rp)                       # the private owner report: outside out/, hashed in select.json
    core, ds = j["pools"]["core"], j["pools"]["ds"]
    assert len(core["variants"]) == len(ds["variants"]) == len(SYN_VARIANTS)
    for pool in (core, ds):                                                         # choosable rows first, then the rest; canonical order inside each part
        flags = [r["eligible"] for r in pool["variants"]]
        assert flags == sorted(flags, reverse=True)
        for part in (True, False):
            orders = [r["order"] for r in pool["variants"] if r["eligible"] is part]
            assert orders == sorted(orders)
        for r in pool["variants"]:
            assert r["label"] == ("선택 가능" if r["eligible"] else "선택 불가") and r["loss_class"] in ("L0", "L1", "L2", "L3")
            assert set(r["gates"]) == {"g1", "g2", "g3", "g4"} and set(r["hold_by_state"]) == {"추세장", "횡보장", "급변장", "보통", "모름"}
            assert {"median", "p90", "share_gt4", "share_gt8", "share_gt18"} <= set(r["hold"])
            assert (r["gates"]["g3"] == "n/a") == (r["family"] in ("F7", "F7h", "F13"))
            assert r["gates"]["g3"] != "not_run" or not r["step2"]
        assert set(pool["e0"]["hold_by_state"]) == {"추세장", "횡보장", "급변장", "보통", "모름"}
    f12 = [r for r in core["variants"] if r["family"] == "F12"]
    assert f12 and all(set(r["comp_fired"]) == set(MT.COMP_LABELS) and set(r["comp_alone"]) == set(MT.COMP_LABELS) for r in f12)
    for r in core["variants"]:                                                      # growth only on choosable core rows (8.2 item 6)
        assert ("M" in r and "live" in r) == r["eligible"]
    assert os.path.exists(os.path.join(work, "results", "select", "core_not_choosable.json")) == any(not r["eligible"] for r in core["variants"])
    assert MT.d11_problems(select_doc=j, select_md=open(os.path.join(out, "SELECT_KO.md"), encoding="utf-8").read()) == []
    for r in ds["variants"]:                                    # D11: no money in a DeepSeek row
        assert set(r) <= RX.DS_ALLOWED and MT.ds_whitelist_ok(r) and "M" not in r and "live" not in r and "placebo" not in r
    assert set(ds["e0"]) <= MT.DS_E0_ALLOWED and set(ds) <= MT.DS_POOL_ALLOWED
    txt = open(os.path.join(out, "SELECT_KO.md"), encoding="utf-8").read()
    assert "코어 23개" in txt and "딥시크 15개" in txt and txt.count("장세별 보유시간") == 2 and "F12(아홉 가지 동시)" in txt
    priv = json.load(open(os.path.join(work, "ds_private", "select_ds.json")))
    assert "M" in next(iter(priv["pools"]["ds"]["variants"].values()))
    ds_part = txt.split("## 딥시크 15개")[1]
    assert "월 +" not in ds_part and "로그" not in ds_part and "월 -" not in ds_part
    assert "지금 청산(E0): 보유시간 중앙값" in txt                              # E0 row first: hold hours and entries lead
    # the private owner report: DeepSeek money on choosable rows only, in the committed table's order, no p value, never in a committed file
    rtxt = open(rp, encoding="utf-8").read()
    P = priv["pools"]["ds"]
    assert [ln.split("|")[1].strip() for ln in rtxt.splitlines() if ln.startswith("| F")] == [r["id"] for r in ds["variants"]]
    for r in ds["variants"]:
        line = next(ln for ln in rtxt.splitlines() if ln.startswith(f"| {r['id']} |"))
        assert (("선택 가능" in line) == r["eligible"]) and (("%" in line) == r["eligible"])
    committed_lines = {x.strip() for x in txt.splitlines()} | {x.strip() for x in open(os.path.join(out, "select.json"), encoding="utf-8").read().splitlines()}
    assert "p값" not in rtxt and not any(ln.strip() in committed_lines for ln in rtxt.splitlines() if len(ln.strip()) >= 20 and any(ch.isalnum() for ch in ln))
    assert rtxt.strip().splitlines()[-1] == RX.OWNER_REPORT_LAST_LINE and "id로" in RX.OWNER_REPORT_LAST_LINE
    for r in f12:                                                                    # F12's component counts split by the pick's timeframe (15m, 30m, 1h, 4h)
        assert set(r["comp_by_tf"]) == {"1h", "4h"} and all(set(c) == {"fired", "alone", "n_picks"} for c in r["comp_by_tf"].values())
        assert [sum(c["fired"].values()) for c in r["comp_by_tf"].values()] and sum(sum(c["fired"].values()) for c in r["comp_by_tf"].values()) == sum(r["comp_fired"].values())
    assert RX.audit_a8(cfg.lay, "select", cfg.pin["work"], cfg.pin_hash)
    assert RX.audit_a9(cfg, {p["id"]: [v.id for v in cfg.variants] for p in cfg.picks})
    assert RX.audit_a9_file(cfg.lay.out_file("select.json")) == [] and RX.audit_a9_file(cfg.lay.out_file("SELECT_KO.md")) == []
    assert RX.audit_a8_file(cfg.lay.out_file("SELECT_KO.md")) == [] and RX.audit_a8_file(cfg.lay.out_file("select.json")) == []


def test_select_report_tells_the_owners_about_the_hunt_read_before_they_choose(syn_select):
    """17 item 4a (pin-blocker): SELECT_KO.md carries the fixed line HUNT_READ_KO near the top, before any table: that the main session
    opened the round-1 hunt results (with test-period outcomes of chandelier-exit trend systems) before the pre-registration was hashed, and
    what the dated addendum of section 15 says. The line holds no number of any result and passes audit A8."""
    cfg, doc = syn_select
    txt = open(cfg.lay.out_file("SELECT_KO.md"), encoding="utf-8").read()
    assert RX.HUNT_READ_KO in txt and txt.count(RX.HUNT_READ_KO) == 1
    assert txt.index(RX.HUNT_READ_KO) < txt.index("## 코어") and txt.index(RX.HUNT_READ_KO) < txt.index("지금 청산(E0): 보유시간 중앙값")
    line = RX.HUNT_READ_KO
    for must in ("사냥 시험", "2026-10-12", "06:38 UTC", "샹들리에", "2024-01~2026-09", "4번", "12번", "01:48 UTC", "어떤 선택에도 쓰지 않았고"):
        assert must in line, must
    # the exit menu was in git before the results existed, except F13 (added about 07:51 UTC at the owners' request from the rule bot's own ladder)
    for must in ("13번(계단 잠금)을 뺀 나머지", "약 07:51 UTC", "요청(오늘 오후 말씀)", "paperbot/ladder.py", "숫자는 쓰지 않았습니다"):
        assert must in line, must
    assert "딥시크" not in line and "%" not in line and "배" not in line.replace("검증을 맡은", "")
    assert MT.audit_text(line) == [] and RX.audit_a8_file(cfg.lay.out_file("SELECT_KO.md")) == []
    assert RX.select_report_ko(doc) == txt                                                       # the report is a function of the json


def test_runner_step2_runs_exactly_the_placebos_that_pass_gates_1_2_4(syn_select):
    cfg, doc = syn_select
    gates = forced_gates(cfg, RX.step1_gates)
    pairs = set(RX.step2_pairs(cfg, gates))
    for pool in ("core", "ds"):
        for r in doc["pools"][pool]["variants"]:
            v = KX.variant_by_id(r["id"])
            g = gates[(r["id"], pool)]
            want = PL.has_placebo(v) and g["g1"] and g["g2"] and g["g4"]
            assert ((r["id"], pool) in pairs) == bool(want) == r["step2"]
            for p in cfg.pool_picks(pool):
                have = all(cfg.store.has(p, r["id"], RX.plc_tag(a, b)) for a, b in RX.seed_blocks(20))
                assert have == r["step2"]
            if not PL.has_placebo(v):
                assert r["gates"]["g3"] == "n/a"
            elif not r["step2"]:
                assert r["eligible"] is False and r["gates"]["g3"] == "not_run"
    assert len(pairs) >= 1                                                           # the synthetic universe exercised step 2


def test_runner_two_steps_give_the_same_eligible_set_as_running_every_placebo(syn_select):
    """T4: running every placebo and running only those of step 2 give the same eligible set."""
    cfg, doc = syn_select
    gates = forced_gates(cfg, RX.step1_gates)
    all_pairs = [(v.id, pool) for pool in cfg.pool_names() for v in cfg.variants if PL.has_placebo(v)]
    for pid in cfg.by_id:                                            # every placebo, also those step 2 skipped
        RX.run_pick_step2(cfg, cfg.by_id[pid], [vid for vid, pool in all_pairs if pool == cfg.by_id[pid]["pool"]])
    for pool in cfg.pool_names():
        e0q = RX._pool_load(cfg, pool, "E0", "q25")
        e0live = RX._pool_load(cfg, pool, "E0", "q100")
        full_eligible = []
        for v in cfg.variants:
            row, _m, _ps = RX.variant_row(cfg, v, pool, e0q, e0live, gates, set(all_pairs))
            if row["eligible"]:
                full_eligible.append(v.id)
        assert sorted(full_eligible) == sorted(doc["pools"][pool]["eligible_ids"])


def test_runner_resume_computes_only_the_missing_files_and_is_the_same_with_two_processes(syn_select, tmp_path):
    cfg, doc = syn_select
    p = cfg.picks[0]
    path = cfg.store.path(p, "F4.m2.b", "q25")
    before = DX.sha256_file(cfg.store.path(p, "F3.a", "q25"))
    mtime = os.path.getmtime(cfg.store.path(p, "F3.a", "q25"))
    with np.load(path) as z:
        g_before = z["g"].copy()
    os.remove(path)
    assert RX.run_pick_step1(cfg, p) == 1                                         # only the missing file is made again
    with np.load(path) as z:
        assert np.array_equal(z["g"], g_before)
    assert DX.sha256_file(cfg.store.path(p, "F3.a", "q25")) == before and os.path.getmtime(cfg.store.path(p, "F3.a", "q25")) == mtime
    assert RX.run_pick_step1(cfg, p) == 0
    # a fresh store with two processes gives the same numbers
    cfg2 = syn_cfg(tmp_path, procs=2)
    cfg2.variants = [v for v in cfg2.variants if v.id in ("F1.w3.a", "F3.a", "F5.P1.g50.a")]
    cfg2.pin = dict(cfg2.pin, work=str(tmp_path / "work2"))
    cfg2.store = RX.Store(cfg2.pin["work"], cfg2.pin_hash, "select")
    RX.run_tasks(cfg2, [(1, pid, None) for pid in cfg2.by_id], "test")
    for pid, pk in cfg2.by_id.items():
        for arm in ("E0", "F1.w3.a", "F3.a", "F5.P1.g50.a"):
            for tag in ("q25", "q100"):
                a, b = cfg2.store.load(pk, arm, tag), cfg.store.load(cfg.by_id[pid], arm, tag)
                assert all(np.array_equal(a[k], b[k]) for k in a)
    KX.register_f11(lambda *a, **k: None)


def test_runner_audits_pass_on_the_synthetic_run(syn_select):
    cfg, doc = syn_select
    pv = {pid: [v.id for v in cfg.variants] for pid in cfg.by_id}
    a2, a4, n = RX.audit_counts_and_wallet(cfg, pv)
    assert a2 and a4 and n == len(cfg.by_id) * (len(cfg.variants) + 1) * 2
    assert RX.audit_placebo_rates(cfg, cfg.picks, [v.id for v in cfg.variants])
    assert RX.audit_e0_against_kernel(cfg, cfg.picks)
    p = cfg.picks[0]
    pdata = cfg.make_pickdata(p)
    for vid in ("F1.w3.a", "F3.a", "F4.m2.a.q15", "F7.N12.a", "F11.a"):
        v = KX.variant_by_id(vid)
        assert RX.audit_check_minutes(cfg, pdata, v, KX.simulate(cfg.market, pdata, v, 0.25, "select"))
    v = KX.variant_by_id("F4.m2.b")
    plc = KX.simulate(cfg.market, pdata, v, 0.25, "select", placebo=True, hz=np.full((KX.N_AGE, 2, 2), 0.1), seed_base=3)
    assert (plc.reason == KX.R_RAND).any() and RX.audit_check_minutes(cfg, pdata, v, plc)
    # the audit has teeth: a changed exit price is caught
    res = KX.simulate(cfg.market, pdata, KX.variant_by_id("F3.a"), 0.25, "select")
    k = np.flatnonzero(res.reason == KX.R_RULE)[0]
    res.xpx[k] *= 1.0001
    assert not RX.audit_check_minutes(cfg, pdata, KX.variant_by_id("F3.a"), res)


def test_runner_real_data_checks_run_on_the_synthetic_universe(syn_select):
    cfg, doc = syn_select
    r = RX.check_t1(cfg)
    assert len(r) == 4 and all(ok for _p, ok in r)
    t5 = RX.check_t5(cfg, per_pool=40)
    assert set(t5) == {"core", "ds"} and all(n >= 40 and bad == 0 for n, bad in t5.values())


def test_t5_draws_go_on_until_each_pick_and_variant_has_its_pairs_and_stop_at_the_cap(syn_select, monkeypatch):
    """The dry run of 2026-10-12 found 285 DeepSeek pairs with one round of draws: a drawn trade without a check gives no pair. The draws
    for one (pick, variant) go on until ``per`` pairs are found, at most ``T5_DRAW_CAP`` x ``per`` draws, so a pool reaches its 500
    (here 40) pairs when its trades often have no check, and a pick whose trades never have one cannot loop forever."""
    cfg, _doc = syn_select
    real = RX.causality_pair
    calls = {"n": 0}

    def sparse(*a, **k):
        calls["n"] += 1
        return None if calls["n"] % 3 else real(*a, **k)

    monkeypatch.setattr(RX, "causality_pair", sparse)
    t5 = RX.check_t5(cfg, per_pool=40)
    assert all(n >= 40 and bad == 0 for n, bad in t5.values())
    none_calls = {"n": 0}

    def none(*a, **k):
        none_calls["n"] += 1
        return None

    monkeypatch.setattr(RX, "causality_pair", none)
    t5 = RX.check_t5(cfg, per_pool=40)
    assert all(n == 0 and bad == 0 for n, bad in t5.values())
    # the cap exactly: T5_DRAW_CAP x per draws for every pick and variant, each draw one call per mode (two for a variant with a placebo)
    vs = [KX.variant_by_id(i) for i in RX.MIDDLE_VARIANTS if i in {x.id for x in cfg.variants}]
    modes = sum(2 if PL.has_placebo(v) else 1 for v in vs)
    want = sum(RX.T5_DRAW_CAP * max(1, math.ceil(40 / (len(cfg.pool_picks(pl)) * len(vs)))) * len(cfg.pool_picks(pl)) * modes
               for pl in cfg.pool_names())
    assert none_calls["n"] == want > 0


def test_placebo_steps_print_no_pick_and_no_file_count(tmp_path, capsys):
    """Prereg 14 and 16.7: while a placebo step runs, a pick's number of new placebo files would show how many variants of its pool passed
    gates 1, 2 and 4, so the quiet lines give the count done and the seconds only; the step-1 lines keep the pick and the count."""
    class C:
        procs = 1
    tasks = [(2, "core-X-15m-1", ["F1.w3.a"]), (2, "core-Y-1h-1", [])]
    old = RX._worker
    try:
        RX._worker = lambda t: (t[1], 7 * len(t[2]))
        RX.run_tasks(C(), tasks, "select step 2", quiet=True)
        out = capsys.readouterr()
        text = out.out + out.err
        assert "core-X" not in text and "new files" not in text and "[select step 2] 2/2" in text
        RX.run_tasks(C(), tasks, "select step 1")
        out = capsys.readouterr()
        assert "core-X-15m-1 (7 new files" in out.out + out.err
    finally:
        RX._worker = old


def test_runner_timing_writes_seconds_and_applies_the_seed_rule(tmp_path, vendor, monkeypatch):
    cfg = syn_cfg(tmp_path)
    doc = RX.run_timing(cfg)
    assert doc["n_variants_timed"] == len([v for v in cfg.variants if PL.has_placebo(v)]) == 14
    assert doc["n_seeds"] == 200 and doc["projected_step2_hours"] == pytest.approx(doc["sum_placebo_one_seed_seconds"] * 4 * 200 / 4 / 3600)
    assert json.load(open(cfg.lay.out_file("timing.json")))["pick"] == cfg.picks[0]["id"]
    monkeypatch.setattr(RX, "TIMING_LIMIT_HOURS", 1e-9)
    assert RX.run_timing(cfg)["n_seeds"] == 100
    KX.clear_f11()


# ====================================================================================================== runner: pin, chain, choice, confirm
def pin_layout(tmp, files=None, required=True):
    """A temporary exitflex folder with a pin file and a PREREG_EXITFLEX.sha256 listing ``files``."""
    base = tmp / "exitflex"
    os.makedirs(base / "out", exist_ok=True)
    (base / "PREREG_EXITFLEX.md").write_text("pre-registration")
    data = tmp / "fg"
    os.makedirs(data / "1m", exist_ok=True)
    (data / "build.json").write_text("{}")
    np.savez(data / "1m" / "BTCUSDT.npz", ts=np.arange(3))
    pin_doc = DX.make_pin(str(data), str(tmp / "work"), symbols=("BTCUSDT",))
    (base / "data_pin.json").write_text(json.dumps(pin_doc))
    lay = RX.Layout(base=str(base), root=str(tmp), required=("exitflex/PREREG_EXITFLEX.md", "exitflex/data_pin.json") if required else ())
    lines = [f"{DX.sha256_file(str(base / n))}  {n}" for n in (files if files is not None else ["PREREG_EXITFLEX.md", "data_pin.json"])]
    (base / "PREREG_EXITFLEX.sha256").write_text("\n".join(lines) + "\n")
    return lay, pin_doc


def pin_add(lay, name):
    p = os.path.join(lay.base, name) if not os.path.isabs(name) else name
    with open(lay.sha_file, "a") as fh:
        fh.write(f"{DX.sha256_file(p)}  {os.path.relpath(p, lay.base)}\n")


def test_runner_refuses_without_the_pin_and_on_any_mismatch(tmp_path):
    lay = RX.Layout(base=str(tmp_path / "e"), root=str(tmp_path), required=())
    os.makedirs(lay.base)
    with pytest.raises(RX.StageRefused, match="data_pin.json missing"):
        RX.gate_pin(lay)
    with pytest.raises(RX.StageRefused, match="data_pin.json missing"):
        RX.stage_select(lay, 1)
    with pytest.raises(RX.StageRefused, match="data_pin.json missing"):
        RX.stage_confirm(lay, 1)
    lay, pin = pin_layout(tmp_path / "a")
    os.remove(lay.sha_file)
    with pytest.raises(RX.StageRefused, match="pin file missing"):
        RX.gate_pin(lay)
    lay, pin = pin_layout(tmp_path / "b")
    p, ph = RX.gate_pin(lay)
    assert p["data_dir"] == pin["data_dir"] and ph == DX.sha256_file(lay.pin_file)
    (tmp_path / "b" / "exitflex" / "PREREG_EXITFLEX.md").write_text("changed")
    with pytest.raises(RX.StageRefused, match="hash mismatch"):
        RX.gate_pin(lay)
    lay, pin = pin_layout(tmp_path / "c", files=["PREREG_EXITFLEX.md"])
    with pytest.raises(RX.StageRefused, match="not pinned"):
        RX.gate_pin(lay)
    lay, pin = pin_layout(tmp_path / "d")
    (tmp_path / "d" / "fg" / "build.json").write_text("{ }")                   # another data file than the pinned one
    with pytest.raises(RX.StageRefused, match="build.json"):
        RX.gate_pin(lay)
    assert RX.gate_pin(lay, verify_data=False)[0]["work"]
    # the lines for the pin file
    lay, pin = pin_layout(tmp_path / "e")
    assert any(l.endswith("research/exitflex/data_x.py") is False for l in []) or isinstance(RX.pin_lines(lay), list)


def test_runner_chain_each_stage_needs_the_previous_stages_file_with_its_pinned_hash(tmp_path):
    lay, pin = pin_layout(tmp_path)
    t = lay.out_file("timing.json")
    with pytest.raises(RX.StageRefused, match="timing.json missing"):
        RX.require_pinned_file(lay, t, "timing.json")
    RX.write_json(t, {"n_seeds": 200})
    with pytest.raises(RX.StageRefused, match="not pinned"):
        RX.require_pinned_file(lay, t, "timing.json")
    pin_add(lay, t)
    assert RX.require_pinned_file(lay, t, "timing.json") == DX.sha256_file(t)
    RX.write_json(t, {"n_seeds": 100})                                          # changed after it was pinned
    with pytest.raises(RX.StageRefused, match="not pinned"):
        RX.require_pinned_file(lay, t, "timing.json")
    with pytest.raises(RX.StageRefused, match="hash mismatch"):                  # and every stage's gate sees that a pinned file changed
        RX.gate_pin(lay, verify_data=False)
    RX.write_json(t, {"n_seeds": 200})
    # choice needs select.json, SELECT_KO.md, timing.json and sent.json pinned; confirm needs those and choice.json
    with pytest.raises(RX.StageRefused, match="select.json missing"):
        RX.stage_choice(lay, {})
    with pytest.raises(RX.StageRefused, match="select.json missing"):
        RX.stage_confirm(lay, 1)
    RX.write_json(lay.out_file("select.json"), {"pin": "x", "pools": {}})
    with pytest.raises(RX.StageRefused, match="select.json is not pinned"):
        RX.stage_choice(lay, {})
    pin_add(lay, lay.out_file("select.json"))
    for name, body in (("SELECT_KO.md", "report"), ("sent.json", None)):
        with pytest.raises(RX.StageRefused, match=f"{name} missing"):
            RX.stage_choice(lay, {})
        if body:
            open(lay.out_file(name), "w").write(body)
        else:
            RX.write_json(lay.out_file(name), {"sent_utc": "2026-10-12T12:00:00Z"})
        with pytest.raises(RX.StageRefused, match=f"{name} is not pinned"):
            RX.stage_choice(lay, {})
        pin_add(lay, lay.out_file(name))
    with pytest.raises(RX.StageRefused, match="choice.json missing"):
        RX.stage_confirm(lay, 1)


# ====================================================================================================== T7: selection logic
def fake_row(vid, group, nparams, order, eligible, med, dset=True, step2=True, g=("pass", "pass", "pass", "pass")):
    return {"id": vid, "group": group, "nparams": nparams, "order": order, "eligible": eligible, "in_default_set": dset,
            "hold": {"median": med, "p90": med * 2, "share_gt4": 0.5, "share_gt8": 0.3, "share_gt18": 0.1}, "step2": step2,
            "gates": dict(zip(("g1", "g2", "g3", "g4"), g))}


def fake_select(pin="ab" * 32):
    """A select.json-shaped document with no real figure: hold medians chosen to exercise the default of 8.4."""
    core = [fake_row("F5.P1.g25.a", "G", 2, 5, True, 6.0), fake_row("F5.P1.g25.b", "G", 2, 6, True, 6.0),
            fake_row("F8.w2.P1.a", "S", 2, 20, True, 7.0), fake_row("F10.N6.a", "L", 1, 60, True, 9.0),
            fake_row("F4.m2.a", "C", 1, 40, True, 2.0, dset=False),                  # shortest hold but L3: never by default
            fake_row("F9.a", "S", 3, 70, False, 1.0, g=("pass", "pass", "pass", "fail")), fake_row("F2.n20.a", "M", 1, 30, True, 3.0, dset=False)]
    ds = [fake_row("F5.P1.g25.a", "G", 2, 5, True, 6.0), fake_row("F8.w2.P1.a", "S", 2, 20, True, 5.0), fake_row("F9.a", "S", 3, 70, True, 5.0)]
    doc = {"pin": pin, "complete_menu": True, "pools": {}}
    for pool, rows in (("core", core), ("ds", ds)):
        doc["pools"][pool] = {"variants": rows, "eligible_ids": [r["id"] for r in rows if r["eligible"]],
                              "default_ids": MT.default_choice(rows)}
    return doc


SENT = {"sent_utc": "2026-10-12T12:00:00Z", "sent_kst": "2026-10-12T21:00:00+09:00", "ds_report_shown_utc": "2026-10-12T11:58:00Z",
        "ds_report_shown_kst": "2026-10-12T20:58:00+09:00", "channel": "chat", "freeze_note": "x"}


def when(hours):
    return RX._utc(RX._parse_utc(SENT["sent_utc"]) + __import__("datetime").timedelta(hours=hours))


def msg(hours, **answers):
    return {"time_utc": when(hours), "text": "답", "answers": answers}


def test_t7_gates_per_pool_and_the_clock_families_have_no_placebo_gate():
    pl = np.linspace(-0.01, 0.01, 200)
    ok = lambda n_pos, n, **kw: MT.eligibility(0.02, [0.01] * n_pos + [-0.01] * (n - n_pos), 100, 100, pl, False)   # noqa: E731
    assert ok(14, 23)["eligible"] and not ok(13, 23)["eligible"] and ok(14, 23)["need_picks"] == 14
    assert ok(9, 15)["eligible"] and not ok(8, 15)["eligible"] and ok(9, 15)["need_picks"] == 9
    assert not MT.eligibility(0.02, [0.01] * 13 + [0.0] * 10, 100, 100, pl, False)["eligible"]       # a zero M_p does not count
    assert MT.eligibility(0.005, [0.01] * 20, 100, 100, None, True)["eligible"]                         # F7, F7h: no gate 3
    assert not MT.eligibility(0.005, [0.01] * 20, 100, 100, None, False)["eligible"]
    assert not MT.eligibility(-0.001, [0.01] * 20, 100, 100, None, True)["eligible"] and not MT.eligibility(0.02, [0.01] * 20, 99, 100, None, True)["eligible"]
    rows = [dict(gates=dict(zip(("g1", "g2", "g3", "g4"), g))) for g in (
        ("fail", "pass", "not_run", "pass"), ("fail", "fail", "not_run", "fail"), ("pass", "fail", "not_run", "pass"), ("pass", "pass", "not_run", "fail"),
        ("pass", "pass", "fail", "pass"), ("pass", "pass", "pass", "pass"), ("pass", "pass", "n/a", "pass"), ("pass", "fail", "not_run", "fail"))]
    assert MT.gate_failure_counts(rows) == {"gate1": 2, "gate2": 2, "gate4": 1, "gate3": 1}          # counted in sequence


def test_t7_default_of_8_4_uses_set_d_hold_hours_the_group_rule_and_none():
    doc = fake_select()
    core, ds = doc["pools"]["core"]["variants"], doc["pools"]["ds"]["variants"]
    # F4.m2.a (2 h) and F2 (3 h) are L3 outside D; F9 is not choosable; F5.P1.g25.a and .b tie at 6 h: fewer parameters tie, then canonical order
    assert MT.default_choice(core) == ["F5.P1.g25.a", "F8.w2.P1.a"]                 # shortest hold; the second from a different group
    assert MT.default_choice(ds) == ["F8.w2.P1.a", "F5.P1.g25.a"]                   # F8 and F9 tie at 5 h: fewer parameters first
    assert MT.default_choice([dict(r, eligible=False) for r in core]) == []
    assert MT.default_choice([r for r in core if r["id"].startswith("F5")]) == ["F5.P1.g25.a"]       # one group only: one variant
    only_l3 = [r for r in core if not r["in_default_set"]]
    assert MT.default_choice(only_l3) == []                                         # L2 and L3 are never taken by default
    tie = [fake_row("A", "S", 2, 9, True, 4.0), fake_row("B", "S", 1, 8, True, 4.0), fake_row("C", "G", 0, 7, True, 4.0)]
    assert MT.default_choice(tie) == ["C", "B"]                                      # ties: fewer parameters, then the canonical order
    assert MT.default_choice(core, standing=["F5.P1.g25.a"]) == ["F8.w2.P1.a"]       # a rerun that voided one id: the standing id's group is skipped
    assert MT.default_choice(core, standing=["F5.P1.g25.a", "F8.w2.P1.a"]) == []
    # the default ranks by hold only: no money field is read
    assert all("M" not in r for r in core)


def test_t7_choice_flow_deadlines_defaults_none_and_late_messages():
    sel = fake_select()
    now = RX._parse_utc(when(10))
    # an answer before the deadline in each pool: kept; the default is not used
    c = RX.build_choice(sel, SENT, {"messages": [msg(5, core=["F8.w2.P1.a", "F4.m2.a"], ds="없음")]}, now)
    assert c["core"] == ["F8.w2.P1.a", "F4.m2.a"] and c["ds"] == [] and c["pools"]["core"]["default_used"] is False
    assert c["pools"]["ds"]["answer"] == "없음" and c["pools"]["ds"]["deadline_utc"] == when(48)
    # no answer before the deadline passes: refused; after it the default applies, but 없음 stays none
    with pytest.raises(RX.StageRefused, match="deadline"):
        RX.build_choice(sel, SENT, {"messages": []}, RX._parse_utc(when(47.9)))
    c = RX.build_choice(sel, SENT, {"messages": [msg(5, ds="없음")]}, RX._parse_utc(when(48)))
    assert c["core"] == sel["pools"]["core"]["default_ids"] and c["pools"]["core"]["default_used"] is True
    assert c["ds"] == [] and c["pools"]["ds"]["default_used"] is False
    # an answer timed at or after the deadline does not count (and is quoted); before the sending it is no answer either
    c = RX.build_choice(sel, SENT, {"messages": [msg(48, core=["F4.m2.a"]), msg(-1, core=["F2.n20.a"]), msg(60, ds=["F9.a"])]}, RX._parse_utc(when(100)))
    assert c["core"] == sel["pools"]["core"]["default_ids"] and c["ds"] == sel["pools"]["ds"]["default_ids"]
    assert [x["pool"] for x in c["late_messages"]] == ["core", "ds"] and all(c["pools"][p]["default_used"] for p in ("core", "ds"))
    # a question moves the deadline of the pools it concerns to at least 24 h after the question
    qs = [{"time_utc": when(47), "text": "어느 것?", "pools": ["core"]}]
    with pytest.raises(RX.StageRefused, match="core: no answer yet"):
        RX.build_choice(sel, SENT, {"messages": [], "questions": qs}, RX._parse_utc(when(70.9)))
    c = RX.build_choice(sel, SENT, {"messages": [msg(5, ds=["F9.a"])], "questions": qs}, RX._parse_utc(when(71)))
    assert c["pools"]["core"]["deadline_utc"] == when(71) and c["pools"]["ds"]["deadline_utc"] == when(48) and c["ds"] == ["F9.a"]
    c = RX.build_choice(sel, SENT, {"messages": [msg(60, core=["F4.m2.a"])], "questions": qs}, RX._parse_utc(when(71)))
    assert c["core"] == ["F4.m2.a"] and c["pools"]["core"]["default_used"] is False             # received before the moved deadline
    # an unclear answer is refused; the latest answer before the deadline counts
    with pytest.raises(RX.StageRefused, match="unclear"):
        RX.build_choice(sel, SENT, {"messages": [msg(5, core=[])]}, now)
    c = RX.build_choice(sel, SENT, {"messages": [msg(5, core=["F4.m2.a"], ds=["F9.a"]), msg(9, core=["F2.n20.a"])]}, now)
    assert c["core"] == ["F2.n20.a"] and c["pools"]["core"]["answer_time_utc"] == when(9)
    # sent_kst must be sent_utc + 9 h
    with pytest.raises(RX.StageRefused, match="sent_kst"):
        RX.build_choice(sel, dict(SENT, sent_kst="2026-10-12T20:00:00+09:00"), {"messages": []}, now)


def test_t7_choice_validation_refuses_each_kind_of_wrong_choice():
    sel = fake_select()
    base = RX.build_choice(sel, SENT, {"messages": [msg(5, core=["F8.w2.P1.a", "F4.m2.a"], ds=["F9.a"])]}, RX._parse_utc(when(10)))
    doc = dict(base, sent_utc=SENT["sent_utc"])
    assert MT.validate_choice_doc(sel, doc, SENT) == []
    def bad(**ch):
        d = json.loads(json.dumps(doc))
        for k, v in ch.items():
            d[k] = v
        return MT.validate_choice_doc(sel, d, SENT)
    assert any("not choosable" in b for b in bad(core=["NOPE.a"]))                                      # unknown id
    assert any("not choosable" in b for b in bad(core=["F9.a"]))                                         # not choosable in core
    assert any("at most 2" in b for b in bad(core=["F8.w2.P1.a", "F4.m2.a", "F2.n20.a"]))               # three ids
    assert any("different groups" in b for b in bad(core=["F5.P1.g25.a", "F5.P1.g25.b"]))                # two ids of one group
    assert any("send time" in b for b in bad(sent_utc="2026-10-12T13:00:00Z"))                           # not sent.json's time
    d = json.loads(json.dumps(doc))                                                                      # 'default used' with an answer before the deadline
    d["pools"]["core"].update(default_used=True, answer_times_utc=[when(5)])
    assert any("answer was timed before the deadline" in b for b in MT.validate_choice_doc(sel, d, SENT))
    d = json.loads(json.dumps(doc))                                                                      # a default that differs from 8.4's output
    d["pools"]["core"].update(default_used=True, answer_times_utc=[], answer_time_utc=None, answer=None)
    d["core"] = ["F10.N6.a"]
    assert any("differ from 8.4" in b for b in MT.validate_choice_doc(sel, d, SENT))
    d["core"] = sel["pools"]["core"]["default_ids"]
    assert MT.validate_choice_doc(sel, d, SENT) == []
    d = json.loads(json.dumps(doc))
    d["pools"]["core"].update(answer=None)                                                               # no answer and no default
    assert any("no answer recorded" in b for b in MT.validate_choice_doc(sel, d, SENT))
    # a rerun (section 14): ids that are still choosable stand; a swapped or dropped one is refused; a pool answered 없음 stays none
    first = json.loads(json.dumps(doc))
    sel2 = json.loads(json.dumps(sel))
    for r in sel2["pools"]["core"]["variants"]:
        r["eligible"] = r["id"] != "F4.m2.a" and r["eligible"]
    sel2["pools"]["core"]["eligible_ids"] = [r["id"] for r in sel2["pools"]["core"]["variants"] if r["eligible"]]
    r2 = RX.build_choice(sel2, SENT, {"messages": [msg(5, core=["F2.n20.a"])]}, RX._parse_utc(when(10)), first)
    assert r2["core"] == ["F8.w2.P1.a", "F2.n20.a"] and r2["ds"] == ["F9.a"]                           # F8 stands, the voided F4 is replaced
    assert MT.validate_choice_doc(sel2, dict(r2, sent_utc=SENT["sent_utc"]), SENT, first) == []
    swapped = dict(r2, core=["F10.N6.a", "F2.n20.a"], sent_utc=SENT["sent_utc"])
    assert any("cannot be swapped or dropped" in b for b in MT.validate_choice_doc(sel2, swapped, SENT, first))
    none_first = dict(first, core=[], pools=dict(first["pools"], core=dict(first["pools"]["core"], answer="없음")))
    assert any("stays none" in b for b in MT.validate_choice_doc(sel2, dict(r2, core=["F2.n20.a"], sent_utc=SENT["sent_utc"]), SENT, none_first))
    r2d = RX.build_choice(sel2, SENT, {"messages": []}, RX._parse_utc(when(48)), first)               # no replacement by the new deadline: the default fills the free place
    assert r2d["core"][0] == "F8.w2.P1.a" and len(r2d["core"]) == 2 and r2d["core"][1] != "F8.w2.P1.a" and r2d["ds"] == ["F9.a"]
    assert MT.validate_choice_doc(sel2, dict(r2d, sent_utc=SENT["sent_utc"]), SENT, first) == []


def test_t7_stage_choice_writes_choice_json_from_the_pinned_chain(tmp_path):
    lay, pin = pin_layout(tmp_path)
    ph = DX.sha256_file(lay.pin_file)
    sel = fake_select(ph)
    RX.write_json(lay.out_file("select.json"), sel)
    open(lay.out_file("SELECT_KO.md"), "w").write("report")
    RX.write_json(lay.out_file("timing.json"), {"n_seeds": 200})
    RX.write_json(lay.out_file("sent.json"), SENT)
    for n in ("select.json", "SELECT_KO.md", "timing.json", "sent.json"):
        pin_add(lay, lay.out_file(n))
    figure_text = "딥시크 F9.a 월 3.5%라서 그걸로 하고 싶었는데, 지갑 2배도 보여서요. 코어는 F8.w2.P1.a 로 갈게요"
    inp = {"messages": [dict(msg(5, core=["F8.w2.P1.a"], ds="없음"), text=figure_text)],
           "questions": [{"time_utc": when(2), "text": "정말요? F9.a 와 F5.P1.g25.a 중에서요", "pools": ["ds"]}],
           "material_received": ["ANALYSIS_KO.md", "STRATEGIES_KO.md", "STRATEGY_EVAL_KO.md"], "freeze_breaches": []}
    doc = RX.stage_choice(lay, inp, now_utc=when(10))
    j = json.load(open(lay.out_file("choice.json")))
    # the DeepSeek money figures of the owners' words are replaced by the marker before the file is written; the rest is verbatim; the hash of the original is private
    assert j["messages"][0]["text"] == "딥시크 F9.a 월 [딥시크 금액 삭제]라서 그걸로 하고 싶었는데, 지갑 [딥시크 금액 삭제]도 보여서요. 코어는 F8.w2.P1.a 로 갈게요"
    assert j["redacted_figures"] == 2 and j["ds_report_shown_utc"] == SENT["ds_report_shown_utc"] and MT.audit_text("\n".join(MT.json_strings(j))) == []
    om = json.load(open(os.path.join(pin["work"], DX.pin8(ph), "ds_private", "owner_messages.json")))
    assert om["items"][0]["sha256_unredacted"] == __import__("hashlib").sha256(figure_text.encode("utf-8")).hexdigest() and "3.5" not in json.dumps(om)
    assert j["core"] == ["F8.w2.P1.a"] and j["ds"] == [] and j["sent_utc"] == SENT["sent_utc"] and j["sent_kst"] == SENT["sent_kst"]
    assert j["select_sha256"] == DX.sha256_file(lay.out_file("select.json")) and j["sent_sha256"] == DX.sha256_file(lay.out_file("sent.json"))
    assert j["questions"] == inp["questions"] and j["material_received"] == ["ANALYSIS_KO.md", "STRATEGIES_KO.md", "STRATEGY_EVAL_KO.md"] and len(j["messages"]) == 1
    assert j["pools"]["ds"]["deadline_utc"] == when(48) and j["pools"]["core"]["answer"] == ["F8.w2.P1.a"]
    # an id that is not choosable is refused; so is an input file that changed select.json after it was pinned
    with pytest.raises(RX.StageRefused, match="not choosable"):
        RX.stage_choice(lay, {"messages": [msg(5, core=["F9.a"], ds="없음")]}, now_utc=when(10))
    # 8.3: material_received names, at least, the three files of the full grid's per-trade results
    for lacking in ([], ["ANALYSIS_KO.md"], ["ANALYSIS_KO.md", "STRATEGIES_KO.md"]):
        with pytest.raises(RX.StageRefused, match="material_received"):
            RX.stage_choice(lay, dict(inp, material_received=lacking), now_utc=when(10))
    assert MT.material_problems({"material_received": ["x/ANALYSIS_KO.md (2024-2026 trades)", "STRATEGIES_KO.md", "STRATEGY_EVAL_KO.md", "more"]}) == []
    # a choice that is already pinned is not written again
    pin_add(lay, lay.out_file("choice.json"))
    with pytest.raises(RX.StageRefused, match="already pinned|hash mismatch"):
        RX.stage_choice(lay, inp, now_utc=when(10))
    lines = [ln for ln in open(lay.sha_file).read().splitlines() if not ln.endswith("choice.json")]
    open(lay.sha_file, "w").write("\n".join(lines) + "\n")
    RX.write_json(lay.out_file("select.json"), dict(sel, extra=1))
    with pytest.raises(RX.StageRefused, match="hash mismatch"):
        RX.stage_choice(lay, inp, now_utc=when(10))


def test_t7_d11_whitelist_refuses_a_planted_deepseek_money_figure_or_p_value():
    row = {"id": "F1.w3.a", "family": "F1", "group": "S", "hold": {"median": 5.0, "p90": 9.0, "share_gt4": 0.5, "share_gt8": 0.2, "share_gt18": 0.0},
           "entered": 100, "entered_e0": 90, "win_share": 0.4, "reasons": {"SL": 3, "RULE": 50}, "gates": {"g1": "pass", "g2": "pass", "g3": "pass", "g4": "pass"},
           "hold_by_state": {"추세장": {"n": 4, "median": 3.0, "p90": 4.0, "share_gt4": 0.0, "share_gt8": 0.0, "share_gt18": 0.0, "few": True}},
           "comp_fired": {"F1": 3}, "label": "선택 가능", "eligible": True, "claim": "x"}
    sel = {"pools": {"core": {"variants": [dict(row, M=0.01)]}, "ds": {"n_picks": 15, "e0": {"hold": row["hold"], "entered": 1, "skipped": 0, "win_share": 0.4},
                                                                         "variants": [row], "eligible_ids": [], "default_ids": [], "gate_fail_counts": {}}}}
    conf = {"e0": {"ds": {"hold": row["hold"], "entered": 10}}, "pairs": {"F1.w3.a|core": dict(row, M=0.01, p_block=0.01),
                                                                           "F1.w3.a|ds": {k: v for k, v in row.items() if k != "gates"} | {"pass": True, "label": "PASS"}}}
    md = "## 코어 23개\n월 +1.20% 로그 0.01\n## 딥시크 15개\n| F1.w3.a | 5.0 | 선택 가능 |\n"
    assert MT.d11_problems(sel, conf, md, md) == []                                   # the allowed fields pass (core may show money)
    for planted in ({"M": 0.01}, {"M_pct_month": 1.2}, {"live": {"M": 0.1}}, {"p_block": 0.03}, {"interval95": [0, 1]}, {"final_multiple_median": 2.0},
                    {"max_dd_median": 0.3}, {"busts": 1}, {"D": [0.1]}, {"qa": {}}, {"hold": {"median": 1, "M": 0.5}}):
        s2 = json.loads(json.dumps(sel))
        s2["pools"]["ds"]["variants"][0].update(planted)
        assert MT.d11_problems(s2, None, None, None), planted
        c2 = json.loads(json.dumps(conf))
        c2["pairs"]["F1.w3.a|ds"].update(planted)
        assert MT.d11_problems(None, c2, None, None), planted
    s3 = json.loads(json.dumps(sel))
    s3["pools"]["ds"]["e0"]["M"] = 0.1
    assert MT.d11_problems(s3, None, None, None)
    for line in ("월 +1.20%", "p = 0.03", "로그 성장 0.01", "최종 배수 2.1", "최대 낙폭 30%", "파산 2개", "구간 [0.1, 0.2]", "$5,200"):
        assert MT.d11_problems(None, None, f"## 딥시크 15개\n{line}\n", None), line
        assert MT.d11_problems(None, None, None, f"### F1 (딥시크)\n## 딥시크\n{line}\n"), line
        assert not MT.d11_problems(None, None, f"## 코어 23개\n{line}\n## 딥시크 15개\nok\n", None), line      # core text may show money


def test_t7_free_text_tripwire_and_redaction():
    flagged = ["딥시크 F9.a 월 3.5%로 하겠습니다", "ds-F10_OTE-1h-1 은 지갑 2배", "DeepSeek 성장 0.4 정도", "딥시크 낙폭 12 라서", "ds-F1_PVT_DIV-1h-1 drawdown 30", "딥시크 2x 였지요",
               "딥시크 p값 0.03"]
    clean = ["딥시크 F9.a 로 하겠습니다", "코어는 월 3.5% 입니다", "ds-F10_OTE-1h-1 과 ds-F9_FVG-4h-1 중 2개", "딥시크 4시간 넘게 든 비율", "## 딥시크 15개", "딥시크 F9.a [딥시크 금액 삭제]"]
    assert all(MT.audit_text(x) == [x] for x in flagged) and all(MT.audit_text(x) == [] for x in clean)
    for x in flagged:
        red, n = MT.redact_ds_money(x)
        assert n >= 1 and MT.audit_text(red) == [] and MT.DS_MARKER in red
        for ident in ("F9.a", "ds-F10_OTE-1h-1", "ds-F1_PVT_DIV-1h-1"):
            assert (ident in x) == (ident in red)                                          # identifiers keep their digits
    for x in clean:
        assert MT.redact_ds_money(x) == (x, 0)                                             # the rest stays verbatim
    assert MT.redact_ds_money("코어 월 3.5%\n딥시크 월 3.5%\n")[0] == "코어 월 3.5%\n딥시크 월 [딥시크 금액 삭제]\n"
    assert list(MT.json_strings({"a": ["x", {"b": "y"}], "c": 3})) == ["x", "y"]


def test_t7_choice_needs_the_private_report_shown_at_or_before_the_sending():
    sel = fake_select()
    now = RX._parse_utc(when(10))
    ok = {"messages": [msg(5, core=["F8.w2.P1.a"], ds=["F9.a"])]}
    RX.build_choice(sel, SENT, ok, now)
    with pytest.raises(RX.StageRefused, match="ds_report_shown_utc missing"):
        RX.build_choice(sel, {k: v for k, v in SENT.items() if not k.startswith("ds_report")}, ok, now)
    with pytest.raises(RX.StageRefused, match="shown after"):
        RX.build_choice(sel, dict(SENT, ds_report_shown_utc="2026-10-12T12:01:00Z", ds_report_shown_kst="2026-10-12T21:01:00+09:00"), ok, now)
    with pytest.raises(RX.StageRefused, match="ds_report_shown_kst"):
        RX.build_choice(sel, dict(SENT, ds_report_shown_kst="2026-10-12T20:00:00+09:00"), ok, now)
    core_only = {"pin": sel["pin"], "pools": {"core": sel["pools"]["core"]}}                       # no DeepSeek pool: nothing to show
    RX.build_choice(core_only, {k: v for k, v in SENT.items() if not k.startswith("ds_report")}, {"messages": [msg(5, core=["F8.w2.P1.a"])]}, now)


def test_t7_a8_and_a9_run_on_each_file_before_it_is_sent(tmp_path):
    row = {"id": "F1.w3.a", "family": "F1", "group": "S", "hold": {"median": 5.0, "p90": 9.0, "share_gt4": 0.5, "share_gt8": 0.2, "share_gt18": 0.0},
           "entered": 100, "entered_e0": 90, "closed": 7, "win_share": 0.4, "reasons": {"SL": 3, "RULE": 4}, "eligible": True,
           "hold_by_state": {st: {"n": n, "median": 3.0, "p90": 4.0, "share_gt4": 0.0, "share_gt8": 0.0, "share_gt18": 0.0, "few": True}
                             for st, n in zip(("추세장", "횡보장", "급변장", "보통", "모름"), (3, 2, 0, 1, 1))}}
    e0 = {k: row[k] for k in ("hold", "entered", "closed", "win_share", "reasons", "hold_by_state")} | {"skipped": 1}
    def write(name, body):
        p = tmp_path / name
        p.write_text(body if isinstance(body, str) else json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return str(p)
    sel = {"pools": {"ds": {"n_picks": 15, "e0": e0, "variants": [row], "eligible_ids": ["F1.w3.a"], "default_ids": [], "gate_fail_counts": {}}}}
    p = write("select.json", sel)
    assert RX.audit_a8_file(p) == [] and RX.audit_a9_file(p) == []
    bad_sel = json.loads(json.dumps(sel))
    bad_sel["pools"]["ds"]["variants"][0]["M"] = 0.01
    assert RX.audit_a8_file(write("select.json", bad_sel))
    bad_sel = json.loads(json.dumps(sel))
    bad_sel["pools"]["ds"]["variants"][0]["hold_by_state"]["보통"]["n"] = 5                        # the state counts no longer sum to the closed trades
    assert RX.audit_a9_file(write("select.json", bad_sel))
    write("select.json", sel)
    ds_part = "\n".join(RX.state_table_ko(sel["pools"]["ds"]))
    md = f"## 딥시크 15개\n\n### 딥시크 15개: 장세별 보유시간\n\n{ds_part}\n"
    pm = write("SELECT_KO.md", md)
    assert RX.audit_a8_file(pm) == [] and RX.audit_a9_file(pm) == []                                 # the table in the report equals the json's
    assert RX.audit_a9_file(write("SELECT_KO.md", md.replace("| 3 / 3.0", "| 4 / 3.0")))
    assert RX.audit_a8_file(write("SELECT_KO.md", md + "딥시크 F9.a 월 +3.1%\n"))
    # free text anywhere: sent, choice, a DEVIATIONS entry
    assert RX.audit_a8_file(write("sent.json", {"freeze_note": "x", "note": "딥시크 F9.a 3% 라서"}))
    assert RX.audit_a8_file(write("sent.json", {"freeze_note": "x", "note": "딥시크 F9.a [딥시크 금액 삭제] 라서"})) == []
    assert RX.audit_a8_file(write("DEVIATIONS.md", "old entry\n딥시크 지갑 2배\n## exitflex entry\nok\n"), after="## exitflex entry") == []
    assert RX.audit_a8_file(write("DEVIATIONS.md", "old entry\n딥시크 지갑 2배\n## exitflex entry\nok\n"))
    # the command line prints pass / fail only and returns the verdict
    assert RX.main(["audit-file", "--path", str(tmp_path / "select.json"), "--path", str(tmp_path / "sent.json")]) in (0, 1)
    write("sent.json", {"freeze_note": "x"})
    assert RX.main(["audit-file", "--path", str(tmp_path / "select.json"), "--path", str(tmp_path / "sent.json")]) == 0
    write("sent.json", {"freeze_note": "딥시크 F9 월 4%"})
    assert RX.main(["audit-file", "--path", str(tmp_path / "sent.json")]) == 1


def test_t7_claims_and_the_loss_categories(f11_on):
    assert MT.claim_of("F7.N24.a") == MT.claim_of("F7h.H8.b") == "beats E0 by holding less; no claim about reading the market"
    assert MT.claim_of("F11.a") == "the strategy's own exit beats E0 and a random exit with its timing profile"
    assert MT.claim_of("F12.b") == MT.claim_of("F12.a") == (
        "this fixed combination of the nine exits, of which at most seven can end a trade on a 1h or 4h pick and at most eight on a 15m or 30m pick "
        "(F6 never moves the exit, F10 acts only on 15m and 30m picks), beats E0 and a random exit with the same 8-hour clock and timing profile")
    assert "all nine exits at once" not in MT.claim_of("F12.a") and MT.CLAIM_F12_LIMITS.startswith("No claim that stacking beats a single rule")
    assert MT.claim_of("F9.a") == MT.claim_of("F1.w3.a") == "beats E0 and beats a random exit with its timing profile"
    assert [RX.claim_key(KX.variant_by_id(v)) for v in ("F7.N12.a", "F7h.H4.a", "F11.a", "F12.a", "F3.a")] == ["f7", "f7", "f11", "f12", "rule"]
    # the runner's English claims are the metrics' (one source), and the Korean F12 claim keeps the 7 / 8 legs, the 8-hour clock and the three limits
    assert RX.CLAIM_EN == {"rule": MT.claim_of("F9.a"), "f11": MT.claim_of("F11.b"), "f12": MT.claim_of("F12.b"), "f7": MT.claim_of("F7h.H8.a"),
                           "f13": MT.claim_of("F13.a")}
    assert MT.claim_of("F13.a") == MT.claim_of("F13.b") == MT.CLAIM_F13 and RX.claim_key(KX.variant_by_id("F13.b")) == "f13"
    ko = RX.CLAIM_KO["f12"]
    assert all(x in ko for x in ("최대 7개", "최대 8개", "F6", "F10", "8시간", "단일 규칙", "모든 매매법", "최고의 청산"))


def test_runner_confirm_runs_the_chosen_pairs_and_keeps_deepseek_money_private(tmp_path_factory, syn_select, vendor):
    scfg, sdoc = syn_select
    tmp = tmp_path_factory.mktemp("conf")
    cfg = syn_cfg(tmp, period="confirm", n_seeds=20, seed=91, days=70)
    cfg.variants = [KX.variant_by_id(v) for v in SYN_VARIANTS]
    choice = {"core": ["F1.w3.a", "F7.N12.a", "F12.a"][:2], "ds": ["F3.a", "F12.b"],
              "pools": {"core": {"default_used": False}, "ds": {"default_used": True}},
              "freeze_breaches": ["테스트용 위반 기록"], "late_messages": [{"pool": "core", "time_utc": "2026-10-20T00:00:00Z", "answer": ["F5.P1.g25.a"]}]}
    RX.write_json(cfg.lay.out_file("choice.json"), {**choice, "pin": cfg.pin_hash})
    sel0 = {"pin": cfg.pin_hash, "modules": RX.loaded_module_hashes(cfg.lay.root), "engine": DX.engine_fingerprint(cfg.market),
            "pools": {"core": {"default_ids": ["F1.w3.a"]}, "ds": {"default_ids": ["F3.a"]}}}
    RX.write_json(cfg.lay.out_file("select.json"), sel0)
    sel = json.load(open(cfg.lay.out_file("select.json")))
    doc = RX.finish_confirm(cfg, sel, choice)
    assert sorted(doc["pairs"]) == ["F1.w3.a|core", "F12.b|ds", "F3.a|ds", "F7.N12.a|core"]
    for key, r in doc["pairs"].items():
        assert r["pass"] == (r["holm_significant"] and r["beats_placebo_p95"] and r["entries_ok"]) and r["label"] in ("PASS", "FAIL")
        assert set(r["hold_by_state"]) == {"추세장", "횡보장", "급변장", "보통", "모름"} and "hold_by_state_e0" in r
        assert r["chosen_by"] == ("default" if r["pool"] == "ds" else "owners")
        assert r["default_would_take"] == (key in ("F1.w3.a|core", "F3.a|ds"))
    assert set(doc["e0"]) == {"core", "ds"} and doc["freeze_breaches"] == choice["freeze_breaches"] and len(doc["late_messages"]) == 1
    core1 = doc["pairs"]["F1.w3.a|core"]
    assert 0.0 < core1["p_block"] <= 1.0 and 0.0 < core1["p_iid"] <= 1.0
    f7 = doc["pairs"]["F7.N12.a|core"]
    assert f7["beats_placebo_p95"] is True and f7["claim"].startswith("beats E0 by holding less")      # F7: no placebo gate
    assert "interval95" in core1 and "qa" in core1 and core1["qa"]["p95"] == core1["p95_gate"] and f7["qa"] is None
    f12 = doc["pairs"]["F12.b|ds"]
    assert set(f12["comp_fired"]) == set(MT.COMP_LABELS) and f12["claim"] == MT.claim_of("F12.b")
    for k in ("F3.a|ds", "F12.b|ds"):                                                                   # D11: labels, counts, win share, hold hours only
        ds = doc["pairs"][k]
        assert MT.ds_whitelist_ok(ds) and not any(x in ds for x in ("M", "M_pct_month", "interval95", "D", "live", "qa", "p95_gate", "p_block", "p_iid"))
    assert MT.d11_problems(confirm_doc=json.load(open(cfg.lay.out_file("confirm.json"))),
                           report_md=open(cfg.lay.out_file("REPORT_KO.md"), encoding="utf-8").read()) == []
    priv = json.load(open(os.path.join(cfg.store.private_dir(), "confirm_ds.json")))
    assert "M" in priv["pairs"]["F3.a|ds"] and "p_block" in priv["pairs"]["F3.a|ds"]
    e0p = priv["e0"]["ds"]                                                       # prereg 3: E0's own DeepSeek figures, private only
    assert set(e0p) == {"max_dd_median", "final_multiple_median", "growth_per_month_log", "growth_pct_month", "live_growth_pct_month", "live_busts"}
    assert "e0" not in doc["pairs"] and "growth_pct_month" not in json.dumps(doc)
    assert doc["ds_private_sha256"] == DX.sha256_file(os.path.join(cfg.store.private_dir(), "confirm_ds.json"))
    rp = os.path.join(cfg.store.private_dir(), "owner_report_confirm.md")
    assert doc["ds_owner_report_sha256"] == DX.sha256_file(rp) and "p값" not in open(rp, encoding="utf-8").read()
    rtxt = open(rp, encoding="utf-8").read()
    assert rtxt.index("지금 청산(E0), ds") < rtxt.index("F3.a|ds") and f"{e0p['growth_pct_month']:+.2f}%" in rtxt
    assert RX.audit_a8(cfg.lay, "confirm", cfg.pin["work"], cfg.pin_hash)
    # the report: hold hours first, PASS/FAIL, the chooser, the freeze breach and the late message; no DeepSeek money
    rep = open(cfg.lay.out_file("REPORT_KO.md"), encoding="utf-8").read()
    assert "동결 위반" in rep and "테스트용 위반 기록" in rep and "choice.json 해시 뒤에 받은 소유자 메시지" in rep and "기본값이 고름" in rep and "두 분이 고름" in rep
    sec = rep.split("### F1.w3.a")[1]
    import re
    assert sec.index("보유시간 중앙값") < re.search(r"\*\*(PASS|FAIL)\*\*", sec).start()                  # hold hours before the verdict
    assert rep.count("장세별 보유시간") == 2
    assert RX.HUNT_READ_KO in rep and rep.index(RX.HUNT_READ_KO) < rep.index("## 코어")         # 17 item 4a: the hunt read is told in the confirm report too
    # Holm over the four pairs is applied as written in 9, DeepSeek p values included
    ps = {k: (r["p_block"] if r["pool"] == "core" else priv["pairs"][k]["p_block"]) for k, r in doc["pairs"].items()}
    assert {k: r["holm_significant"] for k, r in doc["pairs"].items()} == MT.holm(ps, 0.05)
    # the block bootstrap of the first pair reproduces from its seed and its monthly series
    assert core1["p_block"] == MT.block_bootstrap_p(np.array(core1["D"]), DX.seed_of("exitflex", "confirm", "F1.w3.a", "core"))
    assert len(core1["D"]) == 33
    # a module file that changed since the select run is refused
    sel2 = dict(sel, modules={"research/library/lib.py": "0" * 64})
    with pytest.raises(RX.StageRefused, match="module files changed"):
        RX.finish_confirm(cfg, sel2, choice)
    real = RX.loaded_module_hashes(ROOT)
    assert "research/library/lib.py" in real and "research/search/search.py" in real and len(real) >= 8
    KX.clear_f11()


# ====================================================================================================== review fixes: report, guards, pins, cut, T8, confirm checks
def test_review_report_is_read_only_byte_stable_and_computes_nothing(syn_select, monkeypatch):
    """'report' rewrites select.json / SELECT_KO.md from the finished files: byte for byte the same (no commit hash or time in the
    document), never a run, and a missing result file is a refusal that leaves the folder as it was."""
    cfg, doc = syn_select
    orig = RX.step1_gates
    monkeypatch.setattr(RX, "step1_gates", lambda c: forced_gates(c, orig))
    monkeypatch.setattr(RX, "run_tasks", lambda *a, **k: (_ for _ in ()).throw(AssertionError("report must not run tasks")))
    paths = [cfg.lay.out_file("select.json"), cfg.lay.out_file("SELECT_KO.md")]
    before = [open(p, "rb").read() for p in paths]
    assert b'"commit"' not in before[0]
    info = os.path.join(cfg.store.work, cfg.store.pin8, "results", "select", "run_info.json")
    assert "commit" in json.load(open(info))                                      # the commit goes to a side file
    RX.report_select(cfg, {"n_seeds": 20})
    assert [open(p, "rb").read() for p in paths] == before
    # a missing result file: refused, nothing is computed or created
    p = cfg.picks[2]
    gone = cfg.store.path(p, "F4.m2.b", "q100")
    held = gone + ".held"
    os.rename(gone, held)
    try:
        with pytest.raises(RX.StageRefused, match="step 1 is incomplete"):
            RX.report_select(cfg, {"n_seeds": 20})
        assert not os.path.exists(gone)
    finally:
        os.rename(held, gone)
    assert [open(p_, "rb").read() for p_ in paths] == before
    # the report configuration has no market and cannot compute a pick
    lay = cfg.lay
    try:
        rc = RX.report_config(lay, "select", cfg.pin, cfg.pin_hash, 20)
        assert rc.market is None and len(rc.variants) == 88
        with pytest.raises(RuntimeError, match="read-only"):
            rc.make_pickdata(rc.picks[0])
    finally:
        KX.register_f11(lambda *a, **k: None)


def test_review_report_and_select_refuse_over_a_pinned_or_existing_output(tmp_path):
    lay, pin = pin_layout(tmp_path)
    RX.write_json(lay.out_file("timing.json"), {"n_seeds": 20})
    pin_add(lay, lay.out_file("timing.json"))
    RX.guard_select_outputs(lay, False)                                          # nothing there yet: allowed
    RX.write_json(lay.out_file("select.json"), {"pools": {}})
    with pytest.raises(RX.StageRefused, match="select.json already exists or is pinned"):
        RX.guard_select_outputs(lay, False)                                      # the select stage runs once
    pin_add(lay, lay.out_file("select.json"))
    with pytest.raises(RX.StageRefused, match="already pinned"):                 # 'report' does not rewrite a pinned file
        RX.stage_report(lay)
    # a section 14 rerun: needs select.json, a DEVIATIONS entry naming select_r2, no select_r2.json and no confirm.json
    lay2, _ = pin_layout(tmp_path / "r")
    with pytest.raises(RX.StageRefused, match="needs the first select.json"):
        RX.guard_select_outputs(lay2, True)
    RX.write_json(lay2.out_file("select.json"), {"pools": {}})
    with pytest.raises(RX.StageRefused, match="select_r2"):
        RX.guard_select_outputs(lay2, True)
    open(os.path.join(lay2.base, "DEVIATIONS.md"), "w").write("2026-10-13 bug in x; select_r2 follows\n")
    RX.guard_select_outputs(lay2, True)
    RX.write_json(lay2.out_file("confirm.json"), {})
    with pytest.raises(RX.StageRefused, match="before any confirm"):
        RX.guard_select_outputs(lay2, True)
    os.remove(lay2.out_file("confirm.json"))
    RX.write_json(lay2.out_file("select_r2.json"), {})
    with pytest.raises(RX.StageRefused, match="select_r2.json already exists"):
        RX.guard_select_outputs(lay2, True)
    with pytest.raises(RX.StageRefused, match="confirm_r2"):
        RX.require_deviation_entry(lay2, "confirm_r2")


def test_review_make_pin_is_refused_over_a_pinned_data_pin(tmp_path, monkeypatch):
    lay, pin = pin_layout(tmp_path)
    monkeypatch.setattr(RX, "Layout", lambda *a, **k: lay)
    data = tmp_path / "fg"
    with pytest.raises(RX.StageRefused, match="already listed"):
        RX.main(["make-pin", "--data-dir", str(data), "--work", str(tmp_path / "work")])
    assert json.load(open(lay.pin_file)) == pin                                  # untouched


def test_review_unknown_stage_names_are_refused_and_the_periods_are_explicit():
    assert RX.STAGE_PERIOD == {"timing": "select", "select": "select", "select_r2": "select", "check": "select", "confirm": "confirm",
                               "confirm_r2": "confirm"}
    with pytest.raises(ValueError, match="unknown stage"):
        RX.real_config(None, "selct", {}, "", 1, 1)
    with pytest.raises(ValueError, match="unknown stage"):
        RX.real_config(None, "t3-202201010000", {}, "", 1, 1)


def test_review_pins_cover_the_engine_inputs_and_every_code_file_of_the_folder(tmp_path):
    for f in ("paperbot/config.py", "paperbot/ladder.py", "paperbot/margin.py", "paperbot/levrule.py", "paperbot/entry_marks.py",
              "paperbot/sweepsig.py", "research/fullgrid/grid.py", "research/fullgrid/memo.py"):
        assert f in RX.REQUIRED_PINS and os.path.exists(os.path.join(ROOT, f))
    lines = RX.pin_lines(RX.Layout())
    assert all(any(x.endswith("  " + f) for x in lines) for f in ("paperbot/config.py", "research/fullgrid/memo.py", "research/exitflex/runner_x.py"))
    lay, pin = pin_layout(tmp_path)
    RX.gate_pin(lay, verify_data=False)
    open(os.path.join(lay.base, "helper.py"), "w").write("x = 1\n")             # a code file of the folder that is not pinned
    with pytest.raises(RX.StageRefused, match=r"not pinned \(code of this folder\): .*helper.py"):
        RX.gate_pin(lay, verify_data=False)
    pin_add(lay, "helper.py")
    RX.gate_pin(lay, verify_data=False)


def test_review_cut_folder_is_opened_by_the_select_process_and_made_elsewhere(tmp_path, monkeypatch):
    import inspect
    import shutil
    src = write_folder(str(tmp_path / "src"), {SYMS[0]: synth_coin(61, 5, 100.0)})
    work, ph, cut = str(tmp_path / "work"), "cd" * 32, START + 2 * 1440 * MIN
    assert "src_dir" not in inspect.signature(DX.open_cut).parameters         # it cannot read the full arrays
    with pytest.raises(DX.CutMissing):
        DX.open_cut(work, ph, cut, symbols=(SYMS[0],))
    d = DX.write_cut(src, work, ph, cut, symbols=(SYMS[0],))
    assert DX.open_cut(work, ph, cut, symbols=(SYMS[0],)) == d
    t3 = DX.write_cut(src, work, ph, cut, symbols=(SYMS[0],), prefix="t3cut")      # test T3's folder has its own name
    assert t3 != d and os.path.basename(t3).startswith("t3cut-") and os.path.basename(d).startswith("cut-")
    shutil.rmtree(t3)
    assert DX.open_cut(work, ph, cut, symbols=(SYMS[0],)) == d                      # removing T3's folder never touches the select cut
    with pytest.raises(DX.CutMissing):
        DX.open_cut(work, "ef" * 32, cut, symbols=(SYMS[0],))
    with np.load(os.path.join(d, "1m", f"{SYMS[0]}.npz")) as z:
        arrays = {k: z[k] for k in z.files}
    arrays["o"] = arrays["o"].copy()
    arrays["o"][3] += 1e-9
    np.savez_compressed(os.path.join(d, "1m", f"{SYMS[0]}.npz"), **arrays)
    with pytest.raises(DX.PinError):
        DX.open_cut(work, ph, cut, symbols=(SYMS[0],))
    # the runner makes a missing cut in a separate make-cut process, and refuses when that process fails
    calls = []
    lay = RX.Layout(base=str(tmp_path / "e"), root=str(tmp_path))
    pin = {"work": work}

    class Done:
        def __init__(self, rc):
            self.returncode, self.stdout, self.stderr = rc, "", "boom"

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return Done(1)
    monkeypatch.setattr(RX.subprocess, "run", fake_run)
    with pytest.raises(RX.StageRefused, match="make-cut failed"):
        RX.ensure_cut(lay, pin, ph)
    assert calls and calls[0][1].endswith("runner_x.py") and calls[0][2] == "make-cut"


def test_review_a5_checks_the_cut_folder_and_the_arrays_the_select_process_loaded(tmp_path):
    import types
    coins = {s: synth_coin(70 + i, 3, 100.0 + i) for i, s in enumerate(SYMS)}
    src = write_folder(str(tmp_path / "src"), coins)
    ph = "ab" * 32
    d = DX.write_cut(src, str(tmp_path / "work"), ph, DX.SELECT_CUT_MS)
    mk = types.SimpleNamespace(data_dir=d, symbols=SYMS, ts=lambda i: coins[SYMS[i]]["ts"])
    cfg = types.SimpleNamespace(market=mk)
    pin = {"work": str(tmp_path / "work")}
    assert RX.audit_a5(cfg, pin, ph, "select") is True and RX.audit_a5(cfg, pin, ph, "confirm") is True
    late = types.SimpleNamespace(data_dir=d, symbols=SYMS, ts=lambda i: np.array([DX.SELECT_CUT_MS]))
    assert RX.audit_a5(types.SimpleNamespace(market=late), pin, ph, "select") is False       # a minute at the cut was loaded
    other = types.SimpleNamespace(data_dir=str(tmp_path / "src"), symbols=SYMS, ts=mk.ts)
    assert RX.audit_a5(types.SimpleNamespace(market=other), pin, ph, "select") is False      # not the cut folder
    assert RX.audit_a5(cfg, pin, "cd" * 32, "select") is False                              # no cut folder of that pin
    shutil_rm(str(tmp_path / "work"))


def test_review_engine_fingerprint_is_byte_stable_and_the_confirm_refuses_a_difference(syn_select):
    cfg, doc = syn_select
    fp = DX.engine_fingerprint(cfg.market)
    assert set(fp) == {"S", "brackets_sha256"} and set(fp["S"]) == {"0.25", "1.0"} and len(fp["S"]["0.25"]) == 20
    assert json.loads(json.dumps(fp)) == fp and doc["engine"] == fp
    mk2 = DX.Market.from_arrays([synth_coin(5, 2, 100.0)], R.exchange(DX.EXCHANGE, False), symbols=SYMS[:1])
    assert DX.engine_fingerprint(None) == DX.engine_fingerprint(mk2)                  # rebuilt from the files: the same document
    RX.check_engine_unchanged(cfg, {"engine": fp})
    bad = json.loads(json.dumps(fp))
    bad["S"]["1.0"][3] += 1e-9
    with pytest.raises(RX.StageRefused, match="engine inputs changed since the select run: S"):
        RX.check_engine_unchanged(cfg, {"engine": bad})
    with pytest.raises(RX.StageRefused, match="brackets_sha256"):
        RX.check_engine_unchanged(cfg, {"engine": dict(fp, brackets_sha256="0" * 64)})
    with pytest.raises(RX.StageRefused, match="no engine fingerprint"):
        RX.check_engine_unchanged(cfg, {})


def test_review_select_rows_carry_live_size_hazard_and_the_placebo_beside_the_growth(syn_select):
    cfg, doc = syn_select
    for pool in ("core", "ds"):
        for r in doc["pools"][pool]["variants"]:
            assert {"median", "p90", "share_gt4", "share_gt8", "share_gt18"} <= set(r["hold_live"]) and r["entered_live"] >= 0
            assert set(r["hazard"]) == {"num", "den"} and np.array(r["hazard"]["num"]).shape == (KX.N_AGE, 2, 2)
            assert np.array(r["hazard"]["num"]).sum() <= np.array(r["hazard"]["den"]).sum()
            if pool == "ds":
                assert MT.ds_whitelist_ok(r) and "placebo" not in r and "p95_gate" not in r and "Mp" not in r
    with_plc = [r for r in doc["pools"]["core"]["variants"] if r["eligible"] and r["step2"]]
    for r in with_plc:                                                             # prereg 7: the placebo's 5th, 50th, 95th beside the growth
        assert r["placebo"]["p05"] <= r["placebo"]["p50"] <= r["placebo"]["p95"] and r["p95_gate"] == pytest.approx(r["placebo"]["p95"])
        assert len(r["Mp"]) == 2
    txt = open(cfg.lay.out_file("SELECT_KO.md"), encoding="utf-8").read()
    if with_plc:
        assert "무작위 청산 5/50/95%" in txt
    assert MT.d11_problems(select_doc=doc, select_md=txt) == []
    assert RX.audit_a8_file(cfg.lay.out_file("select.json")) == []


def test_review_t8_real_check_has_teeth_and_passes_on_the_synthetic_universe(syn_select):
    cfg, doc = syn_select
    res = RX.check_t8(cfg, per_pool=20)
    assert set(res) == {"core", "ds"} and all(n >= 10 and bad == 0 for n, bad in res.values())
    rng = np.random.default_rng(5)
    n = 1500
    c = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    h, lo = c * (1 + np.abs(rng.normal(0, 0.004, n))), c * (1 - np.abs(rng.normal(0, 0.004, n)))
    reg = DX.regime_module()
    code = reg.regimes(h, lo, c, 240)["code"]
    assert len(set(code[1100:].tolist())) >= 2                                      # the series reaches states other than 모름
    assert all(RX.label_causal_pair(reg, h, lo, c, i0, 240, int(code[i0]), rng) for i0 in (1090, 1200, 1300, 1400, 1499))

    class LookAhead:                                                                # a label that reads the next bar: must be caught
        @staticmethod
        def regimes(h_, l_, c_, tf):
            out = np.zeros(len(c_), np.int8)
            out[:-1] = (c_[1:] > c_[:-1]).astype(np.int8)
            return {"code": out}
    la = LookAhead.regimes(h, lo, c, 240)["code"]
    assert any(not RX.label_causal_pair(LookAhead, h, lo, c, i0, 240, int(la[i0]), rng) for i0 in range(100, 400))


def test_review_t3_snapshot_carries_the_market_state_arrays_at_every_bar_and_signal_bar(tmp_path, vendor):
    syms = SYMS[:1]
    coins = {SYMS[0]: synth_coin(51, 30, 100.0, vol=0.0007, drop=0.003, outages=2)}
    src = write_folder(str(tmp_path / "src"), coins)
    snap = run_side(src, START + 25 * 1440 * MIN, str(tmp_path / "full.npz"), syms)
    for tf in DX.TFS:
        for name in ("state", "adx", "slope", "atrp", "vol_q"):
            assert f"{SYMS[0]}|{tf}|{name}" in snap
    sigs = [k for k in snap if k.endswith("|state") and k.startswith("core-")]
    assert sigs and all(set(np.unique(snap[k]).tolist()) <= {-1, 0, 1, 2, 3, 4} for k in sigs)


def test_review_confirm_refuses_before_computing_on_a_changed_module_or_engine(tmp_path_factory, syn_select, vendor):
    scfg, sdoc = syn_select
    tmp = tmp_path_factory.mktemp("conf2")
    cfg = syn_cfg(tmp, period="confirm", n_seeds=20, seed=93, days=70)
    cfg.variants = [KX.variant_by_id(v) for v in SYN_VARIANTS]
    choice = {"core": ["F1.w3.a"], "ds": ["F3.a"], "pools": {"core": {"default_used": False}, "ds": {"default_used": False}}}
    fp = DX.engine_fingerprint(cfg.market)
    ok_sel = {"pin": cfg.pin_hash, "modules": RX.loaded_module_hashes(cfg.lay.root), "engine": fp, "pools": {"core": {}, "ds": {}}}
    results = os.path.join(cfg.store.work, cfg.store.pin8, "results")
    for bad_sel, msg_ in ((dict(ok_sel, modules={"research/library/lib.py": "0" * 64}), "module files changed"),
                          (dict(ok_sel, engine=dict(fp, brackets_sha256="0" * 64)), "engine inputs changed"),
                          ({k: v for k, v in ok_sel.items() if k != "engine"}, "no engine fingerprint")):
        with pytest.raises(RX.StageRefused, match=msg_):
            RX.finish_confirm(cfg, bad_sel, choice)
        assert not os.path.exists(results) and not os.path.exists(os.path.join(cfg.store.private_dir(), "results"))     # nothing was computed
    KX.clear_f11()


# ====================================================================================================== F13: the engine's stepped lock
# PREREG_EXITFLEX 5.2 (F13): the pick's hard stop and the rule bot's stepped lock (paperbot/ladder.py: first lock 10% net ROE, 5% steps, a step
# arms at lock + 2%; net ROE after costs on isolated margin; applies from the next minute; only tightens), with the pick's own fixed
# take-profit kept (F13.a) or none (F13.b). No rule decision, no check, no placebo. The expected prices below are written with the
# engine's own module (``LD``), not with the kernel's inline formulas.
LEV13 = 30                     # best=False at quarter size with a 4 ATR stop on a price of 100: the first candidate (30x) fits
RT13 = 0.0014                  # the round trip of taker fee and slippage (S[5])
FILL13 = 100.0 * (1 + FILL_SLIP)           # a long's fill at the open of 100


def lock_px(side, fill, roe, fr=0.0, lev=LEV13):
    """The stop price that locks net ROE ``roe`` (the engine's roe_price)."""
    return LD.roe_price(side, fill, lev, roe, RT13, fr)


def f13_path(peak, fall_to=99.0, climb=20, fall=40, flat=0):
    """Three flat hours (the signal bar is the third: the fill is the open of minute 180), ``flat`` flat minutes, a climb to ``peak`` over
    ``climb`` minutes and a fall to ``fall_to`` over ``fall`` minutes."""
    return H(100, 100, 100) + ([(flat, 100.0)] if flat else []) + [(climb, peak), (fall, fall_to)]


def first_cross(s, side, level, after):
    """The first minute after ``after`` whose range touches ``level`` against the position (a low at or under it for a long)."""
    o, h, l = s.mk.cat["o"], s.mk.cat["h"], s.mk.cat["l"]
    for j in range(after + 1, len(o)):
        if (side > 0 and l[j] <= level) or (side < 0 and h[j] >= level):
            return j
    raise AssertionError("never crossed")


def peak_minute(s, side):
    ext = s.mk.cat["h"][:600] if side > 0 else -s.mk.cat["l"][:600]
    return int(np.argmax(ext))


def exit_price_at(s, j, side, level):
    """The exit price of a stop at ``level`` in minute j: the open (with slippage) when the open is already beyond it, else the level."""
    o = float(s.mk.cat["o"][j])
    if (o - level) * side <= 0:
        return o * (1 - side * FILL_SLIP)
    return level * (1 - side * FILL_SLIP)


@pytest.mark.parametrize("mir", MIR)
@pytest.mark.parametrize("pick_exit", ["tp3R|4", "roe50|4"])
@pytest.mark.parametrize("n", range(7))
def test_t2_f13_the_lock_arms_at_12_and_steps_with_the_best_price(tmp_path, vendor, mir, pick_exit, n):
    """The best price between +12% + 5% x n and +12% + 5% x (n + 1) net ROE locks 10% + 5% x n (12 -> 10, 17 -> 15, 22 -> 20, 27 -> 25, 32 -> 30
    ...): a fall to that price exits there as a LOCK, at the next minute that touches it, with slippage, taker; mode b gives the same trade."""
    side = side_of(mir)
    arm = lambda k: lock_px(1, FILL13, 0.12 + 0.05 * k)            # noqa: E731  the long's arming prices
    peak = 0.5 * (arm(n) + arm(n + 1))                              # inside the band of step n (a margin of +-0.08, far above the mirror's rounding)
    s = Scen(tmp_path, f13_path(peak), longs=[2], side_mirror=mir, exit_name=pick_exit)
    t, tb, t0 = s.trade("F13.a"), s.trade("F13.b"), s.trade("E0")
    assert t["lev"] == LEV13 and s.off["side"][0] == side
    fill = s.open_at(180) * (1 + side * FILL_SLIP)
    want = lock_px(side, fill, 0.10 + 0.05 * n)
    jp = peak_minute(s, side)
    j = first_cross(s, side, want, jp)
    assert t["reason"] == KX.R_LOCK and t["off"] == j > jp
    assert t["px"] == pytest.approx(exit_price_at(s, j, side, want), rel=1e-12)
    # never below the locked ROE: the exit price is the lock price less the slippage of any stop
    assert side * (t["px"] / (1 - side * FILL_SLIP) - want) >= -1e-9 * want
    assert (tb["j"], tb["reason"], tb["px"], tb["d"]) == (t["j"], t["reason"], t["px"], t["d"])        # no take-profit was reached: a and b agree
    assert t0["reason"] != KX.R_LOCK and t0["d"] != t["d"]                                           # E0 has no lock: the trade differs
    if n == 0 and not mir and pick_exit == "tp3R|4":                       # the long's numbers written out
        assert fill == pytest.approx(100.02, rel=1e-12)
        assert t["px"] == pytest.approx(100.02 * (1 + 0.10 / 30 + 0.0014) * (1 - 0.0002), rel=1e-12)
    # a gain of at least +12% that falls back to the lock pays at least the locked ROE less the stop's own slippage (positive wallet change)
    assert t["d"] > 0


@pytest.mark.parametrize("mir", MIR)
def test_t2_f13_below_the_first_trigger_there_is_no_lock_and_the_hard_stop_works(tmp_path, vendor, mir):
    side = side_of(mir)
    arm0 = lock_px(1, FILL13, 0.12)
    s = Scen(tmp_path, f13_path(arm0 - 0.06, fall_to=97.0, fall=60), longs=[2], side_mirror=mir)
    for vid in ("F13.a", "F13.b"):
        t = s.trade(vid)
        stop = 100.0 - side * 4 * 0.3
        assert t["reason"] == KX.R_SL and t["px"] == pytest.approx(stop * (1 - side * FILL_SLIP), rel=1e-12) and t["d"] < 0
    # and +12% reached exactly by the best price (the trigger itself, with the kernel's 1e-12 tolerance) arms the first lock
    s2 = Scen(tmp_path / "x", f13_path(arm0 + 0.01, fall_to=97.0, fall=60), longs=[2], side_mirror=mir)
    t = s2.trade("F13.a")
    assert t["reason"] == KX.R_LOCK


@pytest.mark.parametrize("mir", MIR)
def test_t2_f13_the_lock_is_raised_by_the_best_price_of_a_minute_and_applies_from_the_next_minute(tmp_path, vendor, mir):
    """A wick up to the band of step 1 in minute 190 (low back under the lock price in the same minute) raises the lock after that
    minute; the minute itself does not exit (the order of the high and the low is unknown: the low is taken first); the next minute opens
    beyond the new stop and exits at its open as a LOCK, with slippage."""
    side = side_of(mir)
    arm = lambda k: lock_px(1, FILL13, 0.12 + 0.05 * k)            # noqa: E731
    wick = 0.5 * (arm(1) + arm(2))
    s = Scen(tmp_path, H(100, 100, 100, 100, 100, 100), longs=[2], highs={190: wick}, lows={190: 99.9}, side_mirror=mir)
    for vid in ("F13.a", "F13.b"):
        t = s.trade(vid)
        assert t["reason"] == KX.R_LOCK and t["off"] == 191, (vid, KX.REASON_NAMES[t["reason"]], t["off"])
        assert t["px"] == pytest.approx(s.open_at(191) * (1 - side * FILL_SLIP), rel=1e-12)
    # the same wick below the first trigger: no lock, the flat path runs to the period end
    s2 = Scen(tmp_path / "w", H(100, 100, 100, 100, 100, 100), longs=[2], highs={190: arm(0) - 0.06}, lows={190: 99.9}, side_mirror=mir)
    t = s2.trade("F13.a")
    expect_exit(s2, t, last_offset(s2), KX.R_END, side=side)


@pytest.mark.parametrize("mir", MIR)
def test_t2_f13_the_same_minute_hits_the_hard_stop_before_the_lock_can_exist(tmp_path, vendor, mir):
    """Minute 190 reaches the arming price and the hard stop: the stop wins (SL, not LOCK), whatever the order inside the minute."""
    side = side_of(mir)
    s = Scen(tmp_path, H(100, 100, 100, 100, 100, 100), longs=[2], highs={190: lock_px(1, FILL13, 0.20)}, lows={190: 98.0}, side_mirror=mir)
    for vid in ("F13.a", "F13.b"):
        t = s.trade(vid)
        assert t["reason"] == KX.R_SL and t["off"] == 190
        assert t["px"] == pytest.approx((100.0 - side * 1.2) * (1 - side * FILL_SLIP), rel=1e-12)


@pytest.mark.parametrize("mir", MIR)
@pytest.mark.parametrize("pick_exit,tp_at", [("tp3R|4", 103.6), ("roe50|4", None)])
def test_t2_f13_a_keeps_the_picks_take_profit_and_b_has_none(tmp_path, vendor, mir, pick_exit, tp_at):
    side = side_of(mir)
    s = Scen(tmp_path, H(100, 100, 100) + [(150, 110.0)], longs=[2], side_mirror=mir, exit_name=pick_exit)
    ta, tb = s.trade("F13.a"), s.trade("F13.b")
    fill = s.open_at(180) * (1 + side * FILL_SLIP)
    tp = 100.0 + side * 3 * 1.2 if tp_at else fill * (1.0 + side * (0.5 / LEV13 + RT13))      # 3R from the reference; net ROE 50%
    assert ta["reason"] == KX.R_TP and ta["px"] == pytest.approx(tp, rel=1e-12)
    assert ta["off"] == first_cross_tp(s, side, tp)
    expect_exit(s, tb, last_offset(s), KX.R_END, side=side)                                        # a climb never gives back: the lock never exits
    assert tb["both"] == 0 and ta["both"] == 0


def first_cross_tp(s, side, tp):
    h, l = s.mk.cat["h"], s.mk.cat["l"]
    for j in range(181, len(h)):
        if (side > 0 and h[j] > tp) or (side < 0 and l[j] < tp):
            return j
    raise AssertionError


@pytest.mark.parametrize("mir", MIR)
def test_t2_f13_lock_and_take_profit_in_the_same_minute(tmp_path, vendor, mir):
    """(1) A minute that touches the take-profit and would arm the lock: the take-profit exits (maker), the lock is not raised. In mode b,
    with no take-profit, the same minute raises the lock to the step of its high and the next open below it exits as a LOCK.
    (2) A minute that touches both the take-profit and the lock stop: the stop wins (the kernel's stop-first rule), counted as 'both'."""
    side = side_of(mir)
    tp = 100.0 + side * 3.6
    s = Scen(tmp_path, H(100, 100, 100, 100, 100, 100), longs=[2], highs={190: 104.0}, side_mirror=mir)
    ta, tb = s.trade("F13.a"), s.trade("F13.b")
    assert ta["reason"] == KX.R_TP and ta["off"] == 190 and ta["px"] == pytest.approx(tp, rel=1e-12) and ta["both"] == 0
    assert tb["reason"] == KX.R_LOCK and tb["off"] == 191                                       # the lock stepped far up with the 104
    assert tb["px"] == pytest.approx(s.open_at(191) * (1 - side * FILL_SLIP), rel=1e-12)
    # (2) lock 10% armed by a climb to inside the first band, then a minute at the lock's side with a high through the take-profit
    arm = lambda k: lock_px(1, FILL13, 0.12 + 0.05 * k)            # noqa: E731
    top = 0.5 * (arm(0) + arm(1))
    s2 = Scen(tmp_path / "b", H(100, 100, 100) + [(20, top), (30, top), (30, top)], longs=[2], highs={210: 104.0}, lows={210: 100.3},
              side_mirror=mir)
    fill = s2.open_at(180) * (1 + side * FILL_SLIP)
    want = lock_px(side, fill, 0.10)
    for vid, both in (("F13.a", 1), ("F13.b", 0)):
        t = s2.trade(vid)
        assert t["reason"] == KX.R_LOCK and t["off"] == 210, (vid, KX.REASON_NAMES[t["reason"]], t["off"])
        assert t["px"] == pytest.approx(want * (1 - side * FILL_SLIP), rel=1e-12) and t["both"] == both


@pytest.mark.parametrize("mir", MIR)
def test_t2_f13_the_lock_counts_funding_in_its_net_roe(tmp_path, vendor, mir):
    """Funding paid before the lock is armed moves both the arming price and the locked price by the funding share of the notional."""
    side = side_of(mir)
    rate = 0.003 * side                               # the position pays 0.3% of its notional (the sign follows the side)
    notional_share = side * 100.0 * rate / (100.0 * (1 + side * FILL_SLIP))        # funding paid / notional entry (mark open 100 at minute 195)
    arm = lambda k: lock_px(1, FILL13, 0.12 + 0.05 * k, fr=notional_share)         # noqa: E731  (the long's arming prices; fr is the same for the mirror)
    peak = 0.5 * (arm(0) + arm(1))
    s = Scen(tmp_path, f13_path(peak, flat=15), longs=[2], side_mirror=mir, fund_at={195: rate})
    t = s.trade("F13.a")
    fill = s.open_at(180) * (1 + side * FILL_SLIP)
    fr = side * float(s.mk.cat["mo"][195]) * rate / fill
    assert fr == pytest.approx(0.003, rel=2e-3)
    want = lock_px(side, fill, 0.10, fr=fr)
    jp = peak_minute(s, side)
    assert t["reason"] == KX.R_LOCK and t["off"] == first_cross(s, side, want, jp)
    assert t["px"] == pytest.approx(exit_price_at(s, t["off"], side, want), rel=1e-12)
    # the same path with no funding: the price moved less than the funding-adjusted trigger, so the first lock is the same step but
    # nothing arms below the shifted trigger: a peak under the shifted arming price exits by the hard stop
    peak_lo = 0.5 * (lock_px(1, FILL13, 0.12) + arm(0))        # above the no-funding trigger, below the funding-shifted one
    s2 = Scen(tmp_path / "lo", f13_path(peak_lo, fall_to=97.0, fall=60, flat=15), longs=[2], side_mirror=mir, fund_at={195: rate})
    assert s2.trade("F13.a")["reason"] == KX.R_SL


def test_t2_f13_exit_tuples_of_every_pick_exit_are_the_stop_the_lock_and_the_take_profit():
    """kernel_x.exit_of_pick for F13 on each of the 84 pick exits: the pick's stop; the pick's take-profit in a and none in b; the engine's lock
    (10%, 5%, 2%) in both; F13.b equals the kernel's own 'ladder|k' rule, and F13.a on tp2R equals 'ladder_tp2R'."""
    fa, fb = KX.variant_by_id("F13.a"), KX.variant_by_id("F13.b")
    names = [e[0] for e in K.EXITS]
    assert (fa.group, fb.group, fa.famname, fa.nparams, fa.mode, fb.mode, fa.q15) == ("P", "P", "F13", 0, "a", "b", False)
    for i, e in enumerate(K.EXITS):
        stop_atr, kind, val = K.exit_args(i)[:3]
        k = e[1]
        a, b = KX.exit_of_pick({"exit_index": i}, fa), KX.exit_of_pick({"exit_index": i}, fb)
        assert a == (stop_atr, kind, val, True, 0.10, 0.05, 0.02) and b == (stop_atr, KX.TP_NONE, 0.0, True, 0.10, 0.05, 0.02), e[0]
        assert b == K.exit_args(names.index(f"ladder|{k:g}"))
        if e[0].startswith("tp2R|"):
            assert a == K.exit_args(names.index(f"ladder_tp2R|{k:g}"))
    assert KX.F13_LOCK == (0.10, 0.05, 0.02) == (LD.LadderSpec().first_lock, LD.LadderSpec().step, LD.LadderSpec().trigger_gap)
    # E0 and the other families are unchanged: the pick's own exit stays what it was
    assert KX.exit_of_pick({"exit_index": 0}, KX.E0) == K.exit_args(0)
    # the chart side: no rule vector, no chart arrays
    assert KX.rp_vector()[KX.RP_FAM] == 0 and fa.rp(900_000, False)[KX.RP_FAM] == 0 and np.array_equal(fa.rp(900_000, False), KX.rp_vector())


@pytest.mark.parametrize("scale", [0.25, 1.0])
def test_t1_f13_account_equals_the_kernels_lock_on_every_pick_exit(scale):
    """T1 for F13: the numba kernel_x with the F13 exit tuple equals ``kernel.account`` run with the same arguments (trade, exit minute,
    reason, leverage, final wallet), on both worlds and both sizes, for every fourth of the 84 pick exits in both modes."""
    kinds = set()
    for seed, vol, gp in ((3, 0.0009, 0.0), (4, 0.004, 0.003)):
        mk, sig = acct_world(seed, vol=vol, open_gap_p=gp)
        S = mk.S(scale)
        for i in range(0, len(K.EXITS), 4):
            for vid in ("F13.a", "F13.b"):
                ex_args = KX.exit_of_pick({"exit_index": i}, KX.variant_by_id(vid))
                st, pnl, ext, rs, lv, w = kernel_account(mk, sig, S, ex_args)
                o = kx_account(mk, sig, S, ex_args)
                assert np.array_equal(st, o[0]) and np.array_equal(pnl, o[1]) and np.array_equal(ext, o[3])
                assert np.array_equal(rs, o[4]) and np.array_equal(lv, o[5]) and w == o[7], (K.EXITS[i][0], vid)
                kinds |= set(rs[st == 1].tolist())
    assert {K.R_LOCK, K.R_SL, K.R_TP} <= kinds


def test_t1_f13_b_is_the_full_grids_ladder_rule_and_f13_a_on_tp2r_is_its_ladder_tp2r():
    mk, sig = acct_world(6)
    S = mk.S(0.25)
    names = [e[0] for e in K.EXITS]
    for pick_exit, vid, equal_to in (("tp3R|4", "F13.b", "ladder|4"), ("roe50|3", "F13.b", "ladder|3"), ("tp2R|2.5", "F13.a", "ladder_tp2R|2.5"),
                                      ("tp2R|1", "F13.a", "ladder_tp2R|1")):
        ex_args = KX.exit_of_pick({"exit_index": names.index(pick_exit)}, KX.variant_by_id(vid))
        a = kernel_account(mk, sig, S, ex_args)
        b = kernel_account(mk, sig, S, K.exit_args(names.index(equal_to)))
        assert all(np.array_equal(x, y) for x, y in zip(a[:5], b[:5])) and a[5] == b[5], (pick_exit, vid, equal_to)


@pytest.mark.parametrize("tf", ["15m", "1h"])
def test_t2_f13_kernel_equals_the_plain_python_reference_on_random_paths(tmp_path, vendor, tf):
    """The numba kernel and the stateless reference (the lock written with paperbot/ladder.py) give the same trade for F13.a and F13.b, on
    random worlds with gaps, outages, open gaps, funding and a mark price."""
    mk, prov, pd_ = diff_world(tmp_path, tf)
    off = pd_.offered("select", mk)
    assert len(off["coin"]) >= 10
    n = n_lock = 0
    for vid in ("F13.a", "F13.b"):
        v = KX.variant_by_id(vid)
        for q in range(min(len(off["coin"]), 40)):
            bad = compare_trade(mk, prov, pd_, v, off, q)
            assert not bad, (tf, vid, q, bad[:3])
            out = call_trade_x(mk, pd_, v, off, q)[0]
            n += 1
            n_lock += out[2] == KX.R_LOCK
    assert n >= 60 and n_lock >= 8, (n, n_lock)


def test_t4_f13_has_no_placebo_and_is_never_a_step_2_pair():
    for vid in ("F13.a", "F13.b"):
        v = KX.variant_by_id(vid)
        assert not PL.has_placebo(v) and not KX.has_placebo(v)
    assert not any(PL.has_placebo(v) for v in KX.variants() if v.famname == "F13") and PL.has_placebo(KX.variant_by_id("F5.P1.g50.a"))
    # gate 3 does not apply to it: the same eligibility path as F7 and F7h (no_gate3), M > 0, 60% of the picks, entries
    pl = np.linspace(-0.01, 0.01, 200)
    assert MT.eligibility(0.005, [0.01] * 14 + [-0.01] * 9, 100, 100, None, RX.no_placebo_gate(KX.variant_by_id("F13.a")))["eligible"]
    assert not MT.eligibility(0.005, [0.01] * 14 + [-0.01] * 9, 100, 100, None, RX.no_placebo_gate(KX.variant_by_id("F3.a")))["eligible"]
    assert all(RX.no_placebo_gate(KX.variant_by_id(v)) for v in ("F7.N12.a", "F7h.H8.b", "F13.a", "F13.b"))
    assert not any(RX.no_placebo_gate(KX.variant_by_id(v)) for v in ("F1.w3.a", "F4.m2.b", "F5.P1.g50.a", "F9.a", "F10.N6.a"))


def test_t4_f13_refuses_a_placebo_run(tmp_path, vendor):
    s = Scen(tmp_path, H(100, 100, 100, 100.5, 100.8, 100.6, 100.0, 100.0), longs=[2])
    with pytest.raises(ValueError, match="no placebo"):
        s.account("F13.a", placebo=True)


def test_t5_the_real_data_list_holds_only_variants_with_checks_and_f13_is_checked_on_synthetic_paths_only(f11_on):
    """``check_t5`` samples (trade, check) pairs and ``causality_pair`` skips a trade without a check, which is every F13 trade: F13 is not in the list
    (a sample of it would count nothing), and its causality is the synthetic-path test below (prereg T5)."""
    ids = {v.id for v in KX.variants()}
    assert all(i in ids for i in RX.MIDDLE_VARIANTS) and len(set(RX.MIDDLE_VARIANTS)) == len(RX.MIDDLE_VARIANTS) == 18
    assert not any(i.startswith("F13.") for i in RX.MIDDLE_VARIANTS) and {"F12.a", "F12.b", "F11.a", "F11.b"} <= set(RX.MIDDLE_VARIANTS)


def test_t5_f13_the_stop_in_force_at_minute_j_depends_only_on_minutes_before_j(tmp_path, vendor):
    """Causality of the lock: replace every minute from the exit minute x on (OHLC, mark and funding) by another path: no exit before x is
    possible and the minutes up to x - 1 are unchanged; replace every minute from x + 1 on: the trade is identical."""
    w = DIFF_WORLDS["1h"]
    coins = {SYMS[i]: synth_coin(71 + i, w["days"], (100.0, 3000.0)[i], vol=w["vol"], drop=0.003, outages=2) for i in range(2)}
    mk, prov, pd_ = build_world(coins, tmp_path / "a", pick=make_pick("1h", w["exit"]), prov_kw=dict(warm=False))
    off = pd_.offered("select", mk)
    rng = np.random.default_rng(9)
    n_same = n_before = n_lock = 0
    for vid in ("F13.a", "F13.b"):
        v = KX.variant_by_id(vid)
        for q in rng.permutation(len(off["coin"]))[:25]:
            out = KX.simulate_trade(mk, pd_, v, off, int(q), 0.25, "select", True)[0]
            d, x, r = out[0], out[1], out[2]
            c = int(off["coin"][q])
            if r in (KX.R_REJECT, KX.R_OPEN) or x < 3 or x + 2 >= len(coins[SYMS[c]]["ts"]):
                continue
            n_lock += r == KX.R_LOCK
            for idx, same in ((x + 1, True), (x, False)):
                new = rewrite_after(coins[SYMS[c]], idx, seed=int(q) * 7 + 1, vol=0.004)
                mins = {k: new[k] for k in ("o", "h", "l", "mo", "mh", "ml", "fund")}
                out2 = KX.simulate_trade(mk, pd_, v, off, int(q), 0.25, "select", True, minutes=mins)[0]
                if same:
                    assert out2[:5] == out[:5], (vid, int(q), out[:5], out2[:5])
                    n_same += 1
                else:
                    assert out2[1] >= x, (vid, int(q), out2[1], x)        # nothing of minute x or later can have ended the trade earlier
                    n_before += 1
    assert n_same >= 20 and n_before >= 20 and n_lock >= 5, (n_same, n_before, n_lock)


def test_t7_f13_is_group_p_l0_in_set_d_and_the_claim_is_the_locks(f11_on):
    vs = KX.variants()
    f13 = [v for v in vs if v.famname == "F13"]
    assert [v.id for v in f13] == ["F13.a", "F13.b"] and {v.group for v in f13} == {"P"} and {v.nparams for v in f13} == {0}
    assert {MT.loss_class(v) for v in f13} == {"L0"} and all(MT.in_default_set(v) for v in f13)
    assert all(not any(MT.in_default_set(v) for v in vs if v.famname == "F12") for _ in (0,))
    assert sum(MT.in_default_set(v) for v in vs) == 37 and len(vs) == 88 and sum(PL.has_placebo(v) for v in vs) == 74
    assert [v.id for v in vs][-2:] == ["F13.a", "F13.b"] and [v.order for v in vs] == list(range(1, 89))
    want = ("closes by the engine's stepped profit lock: after +12% net ROE it never gives back below +10%, except by the slippage of a "
            "stop and at a gapped open, which can lie anywhere; it reads no structure and makes no claim beyond that")
    assert MT.claim_of("F13.a") == MT.claim_of("F13.b") == MT.CLAIM_F13 == want == RX.CLAIM_EN["f13"]
    assert RX.claim_key(KX.variant_by_id("F13.b")) == "f13" and "10%" in RX.CLAIM_KO["f13"] and "12%" in RX.CLAIM_KO["f13"]
    assert RX.FAMILY_KO["F13"] and "계단" in RX.FAMILY_KO["F13"]
    # F12 does not contain F13: its nine components are F1, F2, F3, F4, F5, F6, F7h, F10, F11
    assert [n for n, _b in KX.COMP_NAMES] == ["F1", "F2", "F3", "F4", "F5", "F6", "F7h", "F10", "F11"] and "F13" not in KX.F12_PARAMS


def test_t7_the_default_of_8_4_can_take_f13_and_ranks_it_by_hold_like_any_set_d_variant():
    fast = fake_row("F13.a", "P", 0, 1, True, 1.0)
    rows = [fast, fake_row("F13.b", "P", 0, 2, True, 3.0), fake_row("F5.P1.g25.a", "G", 2, 3, True, 6.0), fake_row("F1.w3.a", "S", 1, 4, True, 0.5)]
    rows[0]["in_default_set"] = rows[1]["in_default_set"] = True
    rows[2]["in_default_set"] = True
    rows[3]["in_default_set"] = False                                   # F1 is L2: outside set D, whatever its hold
    assert MT.default_choice(rows) == ["F13.a", "F5.P1.g25.a"]          # F13.b is the same group as F13.a: skipped for the second place


def test_runner_counts_of_the_prereg_follow_from_the_code(f11_on):
    """5.3's counts, recomputed from the code: 88 variants, 89 arms, 6,764 step-1 accounts, 74 variants with a placebo and 562,400 placebo accounts at
    most, 228 + 15,200 for the confirm, 37 variants in the default set D; and the PREREG text says the same numbers."""
    vs = KX.variants()
    picks = DX.picks()
    core, ds = [p for p in picks if p["kind"] == "core"], [p for p in picks if p["kind"] == "ds"]
    assert (len(core), len(ds), len(vs), len(vs) + 1) == (23, 15, 88, 89)
    assert (len(vs) + 1) * len(picks) * len(RX.SIZES) == 6764
    n_plc = sum(PL.has_placebo(v) for v in vs)
    assert n_plc == 74 and n_plc * len(core) * 200 == 340_400 and n_plc * len(ds) * 200 == 222_000 and n_plc * len(picks) * 200 == 562_400
    assert (1 + 2) * len(picks) * 2 == 228 and 2 * len(picks) * 200 == 15_200
    assert sum(MT.in_default_set(v) for v in vs) == 37
    assert [v.id for v in vs if not PL.has_placebo(v)] == [v.id for v in vs if v.famname in ("F7", "F7h", "F13")]
    text = open(os.path.join(HERE, "PREREG_EXITFLEX.md"), encoding="utf-8").read()
    for must in ("| **total** | | | | **88** |", "89 x 38 x 2 = 6,764 accounts", "562,400", "37\n    variants", "(E0 and 88 variants = 89 arms)",
                 "228 accounts", "15,200"):
        assert must in text, must
    readme = open(os.path.join(HERE, "README_KO.md"), encoding="utf-8").read()
    assert "88가지" in readme and "1~13번" in readme and "13번" in readme and "86가지" not in readme
