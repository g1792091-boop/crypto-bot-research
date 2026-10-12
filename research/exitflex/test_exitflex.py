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
               funding=True):
    """A seeded random walk of 1m bars: gaps (missing minutes), jumps, a mark price that differs from the last price and
    8-hourly funding, in the layout of data.py's npz."""
    rng = np.random.default_rng(seed)
    n = int(n_days * 1440)
    ts = start_ms + np.arange(n, dtype=np.int64) * MIN
    ret = rng.normal(0, vol, n)
    ret = np.where(rng.random(n) < jump_p, rng.normal(0, 10 * vol, n), ret)
    c = price0 * np.exp(np.cumsum(ret))
    o = np.r_[price0, c[:-1]]
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
    keep[0] = True
    return {"ts": ts[keep], "o": o[keep], "h": h[keep], "l": lo[keep], "c": c[keep], "v": v[keep], "mo": mo[keep],
            "mh": mh[keep], "ml": ml[keep], "mc": mc[keep], "fund": fund[keep]}


def write_folder(path, coins: dict):
    os.makedirs(os.path.join(path, "1m"), exist_ok=True)
    for sym, d in coins.items():
        np.savez(os.path.join(path, "1m", f"{sym}.npz"), **d)
    return path


def path_coin(segments, p0=100.0, start_ms=DX.PERIOD_MS["select"][0], gaps=(), spread=0.0, fund_at=None):
    """A hand-built path: ``segments`` = [(minutes, target price), ...] linear in the last price from the previous
    close; open = the previous close; high / low = the extremes of open and close widened by ``spread``. ``gaps`` = minute
    offsets to delete. ``fund_at`` = {minute offset: funding rate}. Mark = last price."""
    cl, prev = [], p0
    for n, tgt in segments:
        for k in range(1, n + 1):
            cl.append(prev + (tgt - prev) * k / n)
        prev = tgt
    cl = np.array(cl)
    n = len(cl)
    o = np.r_[p0, cl[:-1]]
    h, lo = np.maximum(o, cl) + spread, np.minimum(o, cl) - spread
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


@pytest.fixture(scope="module")
def vendor():
    from paperbot import sweepsig
    sweepsig.lib()
    return True


def build_world(coins: dict, tmp, prov_kw=None, pick=None, f11=None):
    """Market + provider + PickData for a dict of coins {sym: arrays} (the first ones of SYMBOLS)."""
    syms = tuple(coins)
    assert syms == SYMS[:len(syms)]
    folder = write_folder(str(tmp), coins)
    prov = Prov(folder, syms, **(prov_kw or {}))
    mk = DX.Market.from_arrays([coins[s] for s in syms], EX, symbols=syms)
    pick = pick or make_pick()
    pd_ = DX.PickData(mk, pick, prov, f11=f11)
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
        self.xl, self.xs = list(pdata.b_xl[a:b]), list(pdata.b_xs[a:b])
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


def ref_trade(S, br, ts, o, h, l, mo, mh, ml, fund, e, end, side, stop_dist, atr, best, equity, qty_step, min_notional,
              tp_kind, tp_val, tp_price, force_end, v, ch, i0, tf_ms, q15, q15bars=None, plc=None, seed_base=0, coin=0,
              hz=None):
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
        ref = None
        w = prm.get("w", 0)
        if fam in (KX.F1, KX.F6, KX.F8, KX.F9):
            ref = ch.ref_at(i0, bi, w, side)
        brk = ref is not None and side * (ref - px) > 0
        z = 0
        armed = False
        ema_before = False
        if fam == KX.F1:
            fire = brk
            z = ref is not None
        elif fam == KX.F2:
            em = ch.ema_of(prm["n"])
            ema_before = side * (ch.cl[i0] - em[i0]) > 0 or any(side * (ch.cl[i] - em[i]) > 0 for i in range(i0 + 1, bi))
            fire = ema_before and side * (em[bi] - ch.cl[bi]) > 0
            z = ema_before
        elif fam == KX.F3:
            flags = ch.sigs if side > 0 else ch.sigl
            fire = any(flags[i] for i in range(i0 + 1, bi + 1))
        elif fam == KX.F11:
            flags = ch.xl if side > 0 else ch.xs
            fire = any(flags[i] for i in range(i0 + 1, bi + 1))
        elif fam == KX.F4:
            lvl = X - side * prm["m"] * ch.atr[bi]
            fire = side * (lvl - px) > 0
        elif fam == KX.F5:
            armed = armed_at(kk, prm["P"])
            fire = armed and rc <= (1 - prm["g"]) * rpk
            z = armed
        elif fam == KX.F6:
            fire = brk and rc < -prm["d"]
            z = ref is not None
        elif fam == KX.F7:
            fire = ci["cc"] >= ch.cms[i0] + prm["N"] * tf_ms
        elif fam == KX.F8:
            armed = armed_at(kk, prm["P"])
            fire = armed and brk
            z = armed
        elif fam == KX.F9:
            armed = armed_at(kk, prm["P"])
            fire = brk and (armed or rc < -prm["d"])
            z = armed
        elif fam == KX.F10:
            fire = rc > 0 and ci["cc"] - ci["TX"] >= prm["N"] * tf_ms
        else:
            raise AssertionError(fam)
        a = PL.age_bucket_py(kk)
        s = 1 if rc >= 0 else 0
        return bool(fire), (a, s, int(bool(z))), dict(ref=ref, armed=bool(armed), ema_before=bool(ema_before), **ci)

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
    t = trade_args(mk, pdata, v, off, q, scale, period, force_end)
    c, a, b = t["c"], t["a"], t["b"]
    rp, PT, PF, QT, cst, cen, qst, qen = pdata.chart(v)
    num, den = KX.new_counts()
    trace = KX.new_trace(trace_rows)
    hz = np.zeros((KX.N_AGE, 2, 2)) if hz is None else np.ascontiguousarray(hz, dtype=np.float64)
    out = KX._trade_x(t["S"], mk.brs[c], t["tsc"], mk.cat["o"][a:b], mk.cat["h"][a:b], mk.cat["l"][a:b], mk.cat["mo"][a:b],
                      mk.cat["mh"][a:b], mk.cat["ml"][a:b], mk.cat["fund"][a:b], t["e"], b - a, t["side"],
                      t["stop_atr"] * t["atr"], t["atr"], t["best"], equity, mk.qty_steps[c], mk.min_notionals[c],
                      t["tp_kind"], t["tp_val"], t["ladder"], t["fl"], t["step"], t["gap"], tp_price, force_end, rp, t["i0"],
                      PT[cst[c]:cen[c]], PF[cst[c]:cen[c]], QT[qst[c]:qen[c]], plc, hz, int(seed), c, num, den, trace)
    return out, num, den, trace


def call_ref(mk, prov, pdata, v, off, q, scale=0.25, force_end=True, plc=False, hz=None, seed=0, equity=5000.0,
             tp_price=np.nan, period="select"):
    t = trade_args(mk, pdata, v, off, q, scale, period, force_end)
    c, a, b = t["c"], t["a"], t["b"]
    ch = RefChart(pdata, c)
    q15 = bool(v.q15) and pdata.tf in ("1h", "4h")
    q15bars = ref_q15(prov, pdata, c) if q15 else None
    if v.fam == KX.F2:
        ch.ema_of(v.params["n"])
    hzd = None
    if plc:
        hzd = {(i, j, k): hz[i, j, k] for i in range(KX.N_AGE) for j in range(2) for k in range(2)}
    return ref_trade(t["S"], mk.brs[c], t["tsc"], mk.cat["o"][a:b], mk.cat["h"][a:b], mk.cat["l"][a:b], mk.cat["mo"][a:b],
                     mk.cat["mh"][a:b], mk.cat["ml"][a:b], mk.cat["fund"][a:b], t["e"], b - a, t["side"],
                     t["stop_atr"] * t["atr"], t["atr"], t["best"], equity, mk.qty_steps[c], mk.min_notionals[c], t["tp_kind"],
                     t["tp_val"], tp_price, force_end, v, ch, t["i0"], pdata.tf_ms, q15, q15bars, plc, seed, c, hzd)


def compare_trade(mk, prov, pdata, v, off, q, **kw):
    """Run both and return a list of mismatch strings (empty = identical, including every check's frozen decision state)."""
    out, num, den, trace = call_trade_x(mk, pdata, v, off, q, trace_rows=2000, **kw)
    rd, rj, rr, rl, rp_, rrec = call_ref(mk, prov, pdata, v, off, q, **{k: val for k, val in kw.items() if k != "trace_rows"})
    bad = []
    d, j, r, lev, px, nk, both = out
    if not (abs(d - rd) <= 1e-9 * max(1.0, abs(rd)) and j == rj and r == rr and lev == rl and abs(px - rp_) <= 1e-9 * max(1.0, abs(rp_))):
        bad.append(f"trade: kernel {(d, j, r, lev, px)} ref {(rd, rj, rr, rl, rp_)}")
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
