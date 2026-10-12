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
              hz=None, lvl=float("nan")):
    """Sections 4-6 in plain Python, stateless: every rule input is recomputed from the raw bars at each check. No stepped
    lock (the picks use none). Returns (d, j, reason, lev, price, [per-check records])."""
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
    # ---- the check schedule: (minute, last schedule bar), merged when minutes coincide
    checks = []
    if fam:
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
        return bool(fire), (a, s, int(bool(z))), dict(ref=ref_out, armed=bool(armed), ema_before=bool(ema_before), comp=comp, **ci)

    mfe = fill
    fpaid = 0.0
    for j in range(e, end):
        entry_bar = j == e
        fire = False
        info = None
        if fam and not entry_bar and j in by_j:
            kk, _last = by_j[j]
            rule_fire, strat, info = evaluate(kk)
            fire = rule_fire
            if plc:
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
        if price >= 0:
            gross = side * qty * (price - fill)
            if gross < -margin:
                liquidate = True
            else:
                wallet += gross - qty * price * (maker if at_tp else taker)
                rc_ = KX.R_TP if at_tp else (code if code is not None else KX.R_SL)
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
                     float(off["lvl"][q]) if v.fam in (KX.F11, KX.F12) else float("nan"))


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
                "checks": out[5], "both": out[6], "num": num, "den": den, "trace": trace, "v": v}

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
    assert t["trace"][:3, 5].tolist() == [0.0, 0.0, 0.0]  # z = 0 always
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
    """The same coin with every minute from index ``idx`` on replaced by another random path (OHLC and mark); the
    timestamps, the minutes before and the funding stay."""
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
    return c


MIDDLE = ["F1.w3.a", "F1.w3.a.q15", "F2.n20.a", "F3.a", "F4.m2.a", "F4.m2.a.q15", "F5.P1.5.g25.a", "F6.w3.d0.5", "F7.N24.a",
          "F8.w3.P1.a", "F9.a", "F9.a.q15", "F10.N6.a", "F11.a", "F11.b"]


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
    assert len(vs) == 86 and len({v.id for v in vs}) == 86
    ids = [v.id for v in vs]
    for must in ("F1.w3.a", "F1.w3.b.q15", "F2.n20.b", "F3.a", "F4.m1.5.a", "F4.m2.b.q15", "F5.P1.5.g25.a", "F6.w2.d0", "F6.w2.d0.5",
                 "F7.N24.b", "F7h.H8.a", "F7h.H4.b", "F7h.H16.a", "F8.w3.P1.a", "F9.a", "F9.b.q15", "F10.N6.a", "F11.a", "F11.b",
                 "F12.a", "F12.b", "F5.P1.g50.b"):
        assert must in ids
    assert ids[:6] == ["F1.w2.a", "F1.w2.b", "F1.w3.a", "F1.w3.b", "F1.w5.a", "F1.w5.b"]
    assert ids[-4:] == ["F11.a", "F11.b", "F12.a", "F12.b"]
    by = {}
    for v in vs:
        by.setdefault(v.famname + (".q15" if v.q15 else ""), []).append(v)
    assert {k: len(x) for k, x in by.items()} == {"F1": 6, "F1.q15": 6, "F2": 6, "F3": 2, "F4": 6, "F4.q15": 6, "F5": 12, "F6": 6, "F7": 6,
                                                  "F7h": 6, "F8": 12, "F9": 2, "F9.q15": 2, "F10": 4, "F11": 2, "F12": 2}
    assert all(v.mode == "a" for v in by["F6"])
    assert {v.famname: v.group for v in vs} == {"F1": "S", "F2": "M", "F3": "O", "F4": "C", "F5": "G", "F6": "S", "F7": "T", "F7h": "T",
                                                "F8": "S", "F9": "S", "F10": "L", "F11": "N", "F12": "A"}
    npar = {k: {v.nparams for v in x} for k, x in by.items()}
    assert npar["F3"] == {0} and npar["F11"] == {0} and npar["F9"] == {3} and npar["F9.q15"] == {4} and npar["F1"] == {1}
    assert npar["F1.q15"] == {2} and npar["F5"] == {2} and npar["F6"] == {2} and npar["F8"] == {2} and npar["F4.q15"] == {2}
    assert npar["F7h"] == {1} and npar["F12"] == {8}
    assert [v.order for v in vs] == list(range(1, 87))
    assert KX.F11_REGISTRY["modes"] == ("a", "b") and len(KX.variants(include_f11=False)) == 82
    # 5.3: 74 variants outside F7 and F7h reach the placebo step (F12 has one); the loss-cut categories; the default set D has 35
    assert sum(PL.has_placebo(v) for v in vs) == 74 and not any(PL.has_placebo(v) for v in by["F7"] + by["F7h"])
    cls = {k: {MT.loss_class(v) for v in x} for k, x in by.items()}
    assert cls["F5"] == {"L0"} and cls["F8"] == {"L0"} and cls["F10"] == {"L0"} and cls["F9"] == {"L1"} and cls["F9.q15"] == {"L1"}
    assert cls["F1"] == {"L2"} and cls["F1.q15"] == {"L2"} and cls["F11"] == {"L3"} and cls["F12"] == {"L3"} and cls["F7h"] == {"L3"}
    assert {MT.loss_class(v) for v in by["F6"] if v.params["d"] == 0.5} == {"L1"} and {MT.loss_class(v) for v in by["F6"] if v.params["d"] == 0} == {"L2"}
    assert sum(MT.in_default_set(v) for v in vs) == 35 and not any(MT.in_default_set(v) for v in by["F12"])
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
    rows = [dict(id="A", group="S", nparams=2, order=3, eligible=True, M=0.02), dict(id="B", group="S", nparams=1, order=2, eligible=True, M=0.02),
            dict(id="C", group="C", nparams=3, order=9, eligible=True, M=0.01), dict(id="D", group="T", nparams=0, order=20, eligible=False, M=0.5)]
    assert MT.choose_variants(rows) == ["B", "C"]                                  # ties: fewer parameters; second from another group
    assert MT.choose_variants([dict(r, eligible=False) for r in rows]) == []
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
                "F9.a", "F10.N6.a", "F11.a", "F11.b", "F12.a", "F12.b"]


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
    lay = RX.Layout(base=str(tmp / "exitflex"), root=str(tmp), required=())
    os.makedirs(lay.out, exist_ok=True)
    pin = {"work": str(tmp / "work"), "data_dir": folder}
    cfg = RX.Config(lay, pin, "cd" * 32, stage or period, period, mk, picks, [KX.variant_by_id(v) for v in variants],
                    lambda pick: DX.PickData(mk, pick, prov, f11=causal_f11), n_seeds, procs)
    return cfg


FORCED_PAIRS = {("F1.w3.a", "core"), ("F4.m2.b", "core"), ("F11.a", "core"), ("F7.N12.a", "core"), ("F7h.H8.a", "core"), ("F12.a", "core"),
                ("F1.w3.a", "ds"), ("F4.m2.b", "ds"), ("F3.a", "ds"), ("F12.b", "ds"), ("F7h.H8.a", "ds")}


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
            assert (r["gates"]["g3"] == "n/a") == (r["family"] in ("F7", "F7h"))
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
    assert "p값" not in rtxt and not any(ln.strip() in txt or ln.strip() in json.dumps(j) for ln in rtxt.splitlines() if len(ln.strip()) >= 20)
    assert RX.audit_a8(cfg.lay, "select", cfg.pin["work"], cfg.pin_hash)
    assert RX.audit_a9(cfg, {p["id"]: [v.id for v in cfg.variants] for p in cfg.picks})


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
    # choice needs select.json pinned; confirm needs select.json and choice.json
    with pytest.raises(RX.StageRefused, match="select.json missing"):
        RX.stage_choice(lay, [], [])
    with pytest.raises(RX.StageRefused, match="select.json missing"):
        RX.stage_confirm(lay, 1)
    RX.write_json(lay.out_file("select.json"), {"pin": "x", "pools": {}})
    with pytest.raises(RX.StageRefused, match="select.json is not pinned"):
        RX.stage_choice(lay, [], [])
    pin_add(lay, lay.out_file("select.json"))
    with pytest.raises(RX.StageRefused, match="choice.json missing"):
        RX.stage_confirm(lay, 1)


def edited_select(syn_select_doc, tmp, eligible):
    """A copy of the synthetic select.json with chosen ids marked eligible (core and ds), written to a pinned layout."""
    lay, pin = pin_layout(tmp)
    ph = DX.sha256_file(lay.pin_file)
    doc = json.loads(json.dumps(syn_select_doc, default=RX._json_default))
    doc["pin"] = ph
    for pool in ("core", "ds"):
        P = doc["pools"][pool]
        want = eligible.get(pool, [])
        for r in P["variants"]:
            r["eligible"] = r["id"] in want
            r["mark_default"] = r["id"] in eligible.get(pool + "_default", want[:2])
        P["eligible_ids"] = list(want)
        P["default_ids"] = eligible.get(pool + "_default", want[:2])           # in rank order
    RX.write_json(lay.out_file("select.json"), doc)
    pin_add(lay, lay.out_file("select.json"))
    return lay, doc, ph


def test_runner_choice_validates_eligibility_pool_size_and_groups(syn_select, tmp_path):
    cfg, sdoc = syn_select
    lay, doc, ph = edited_select(sdoc, tmp_path, {"core": ["F1.w3.a", "F4.m2.b", "F11.a", "F6.w2.d0"], "ds": ["F3.a", "F1.w3.a"],
                                                  "ds_default": ["F3.a", "F1.w3.a"], "core_default": ["F4.m2.b", "F1.w3.a"]})
    out = RX.stage_choice(lay, ["F1.w3.a", "F4.m2.b"], ["F3.a"], "두 개 골랐습니다", "2026-10-13T01:00:00Z", "2026-10-13T10:00:00+09:00",
                          "2026-10-12T12:00:00Z")
    j = json.load(open(lay.out_file("choice.json")))
    assert j["core"] == ["F1.w3.a", "F4.m2.b"] and j["ds"] == ["F3.a"] and j["message"] == "두 개 골랐습니다" and j["default_used"] is False
    assert j["select_sha256"] == DX.sha256_file(lay.out_file("select.json")) and j["pin"] == ph
    with pytest.raises(RX.StageRefused, match="different groups"):
        RX.stage_choice(lay, ["F1.w3.a", "F11.a"] if False else ["F1.w3.a", "F6.w2.d0"], [])        # both structure (S)
    with pytest.raises(RX.StageRefused, match="not eligible"):
        RX.stage_choice(lay, ["F5.P1.g50.a"], [])
    with pytest.raises(RX.StageRefused, match="at most 2"):
        RX.stage_choice(lay, ["F1.w3.a", "F4.m2.b", "F11.a"], [])
    with pytest.raises(RX.StageRefused, match="not eligible"):
        RX.stage_choice(lay, [], ["F11.a"])                                         # eligible in core only
    # the default: 48 h after the report was sent, and then the marks of select.json
    with pytest.raises(RX.StageRefused, match="48 h"):
        RX.stage_choice(lay, [], [], use_default=True, report_sent_utc="2026-10-12T12:00:00Z", now_utc="2026-10-14T11:59:00Z")
    d = RX.stage_choice(lay, [], [], use_default=True, report_sent_utc="2026-10-12T12:00:00Z", now_utc="2026-10-14T12:00:00Z")
    assert d["default_used"] is True and d["core"] == ["F4.m2.b", "F1.w3.a"] and d["ds"] == ["F3.a", "F1.w3.a"]
    with pytest.raises(RX.StageRefused, match="48 h|report"):
        RX.stage_choice(lay, [], [], use_default=True)


def test_runner_confirm_runs_the_chosen_pairs_and_keeps_deepseek_money_private(tmp_path_factory, syn_select, vendor):
    scfg, sdoc = syn_select
    tmp = tmp_path_factory.mktemp("conf")
    cfg = syn_cfg(tmp, period="confirm", n_seeds=20, seed=91, days=70)
    cfg.variants = [KX.variant_by_id(v) for v in SYN_VARIANTS]
    choice = {"core": ["F1.w3.a", "F7.N12.a"], "ds": ["F3.a"]}
    RX.write_json(cfg.lay.out_file("choice.json"), {**choice, "pin": cfg.pin_hash})
    RX.write_json(cfg.lay.out_file("select.json"), {"pin": cfg.pin_hash, "modules": RX.loaded_module_hashes(cfg.lay.root)})
    sel = json.load(open(cfg.lay.out_file("select.json")))
    doc = RX.finish_confirm(cfg, sel, choice)
    assert sorted(doc["pairs"]) == ["F1.w3.a|core", "F3.a|ds", "F7.N12.a|core"]
    for key, r in doc["pairs"].items():
        assert 0.0 < r["p_block"] <= 1.0 and 0.0 < r["p_iid"] <= 1.0
        assert r["pass"] == (r["holm_significant"] and r["beats_placebo_p95"] and r["entries_ok"]) and r["label"] in ("PASS", "FAIL")
    f7 = doc["pairs"]["F7.N12.a|core"]
    assert f7["beats_placebo_p95"] is True and f7["claim"].startswith("beats E0 by holding less")      # F7: no placebo gate
    assert "interval95" in doc["pairs"]["F1.w3.a|core"] and "qa" in doc["pairs"]["F1.w3.a|core"] and doc["pairs"]["F1.w3.a|core"]["qa"]["p95"] == doc["pairs"]["F1.w3.a|core"]["p95_gate"]
    assert doc["pairs"]["F7.N12.a|core"]["qa"] is None
    ds = doc["pairs"]["F3.a|ds"]
    assert not any(k in ds for k in ("M", "M_pct_month", "interval95", "D", "live", "qa", "p95_gate", "max_dd_median", "final_multiple_median"))
    assert RX.audit_a8([cfg.lay.out_file("confirm.json")])
    priv = json.load(open(os.path.join(cfg.store.private_dir(), "confirm_ds.json")))
    assert "M" in priv["pairs"]["F3.a|ds"] and doc["ds_private_sha256"] == DX.sha256_file(os.path.join(cfg.store.private_dir(), "confirm_ds.json"))
    # Holm over the three pairs is applied as written in 9
    ps = {k: r["p_block"] for k, r in doc["pairs"].items()}
    assert {k: r["holm_significant"] for k, r in doc["pairs"].items()} == MT.holm(ps, 0.05)
    # the block bootstrap of the first pair reproduces from its seed and its monthly series
    first = doc["pairs"]["F1.w3.a|core"]
    assert first["p_block"] == MT.block_bootstrap_p(np.array(first["D"]), DX.seed_of("exitflex", "confirm", "F1.w3.a", "core"))
    assert len(first["D"]) == 33
    # a module file that changed since the select run is refused
    sel2 = dict(sel, modules={"research/library/lib.py": "0" * 64})
    with pytest.raises(RX.StageRefused, match="module files changed"):
        RX.finish_confirm(cfg, sel2, choice)
    real = RX.loaded_module_hashes(ROOT)
    assert "research/library/lib.py" in real and "research/search/search.py" in real and len(real) >= 8
    KX.clear_f11()
