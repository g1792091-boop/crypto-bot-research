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
                 pad=True):
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
                                                               best_fn=(lambda s, df: (np.full(len(df), best), np.full(len(df), best)))))
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
    s2 = Scen(tmp_path / "b", seg, longs=[2, 5], shorts=[5], side_mirror=mir)
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
def acct_world(seed, ncoins=2, days=25, nsig=140, vol=0.0009):
    prices = [100.0, 3000.0, 60.0, 0.1, 80.0, 250.0]
    coins = [synth_coin(seed * 10 + i, days, prices[i], vol=vol, drop=0.006) for i in range(ncoins)]
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
                        np.zeros((KX.N_AGE, 2, 2)) if hz is None else hz, seed, num, den)


@pytest.mark.parametrize("scale", [0.25, 1.0])
def test_t1_account_parity_all_84_exits(scale):
    kinds = set()
    for seed, vol in ((3, 0.0009), (4, 0.004)):                    # a calm world and a wild one (liquidations, locks)
        mk, sig = acct_world(seed, vol=vol)
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
                                  PF, QT, False, np.zeros((KX.N_AGE, 2, 2)), 0, c, *KX.new_counts(), KX.new_trace(0))
                assert tuple(got[:4]) == tuple(ref)
                n += 1
                nonrej += ref[2] != K.R_REJECT
    assert n > 500 and nonrej > 300


def test_t1_period_end_after_data_end_changes_nothing_and_force_end_only_adds_end():
    mk, sig = acct_world(5)
    S = mk.S(0.25)
    ex_args = K.exit_args([e[0] for e in K.EXITS].index("tp3R|3"))
    a = kx_account(mk, sig, S, ex_args, force_end=False)
    b = kx_account(mk, sig, S, ex_args, force_end=True, ends=mk.ends)
    still_open = a[4] == K.R_OPEN
    assert still_open.any()
    # the first entered trade is identical until the first one that was open at the data end
    first_open = int(np.flatnonzero(still_open)[0])
    assert np.array_equal(a[1][:first_open], b[1][:first_open]) and np.array_equal(a[4][:first_open], b[4][:first_open])
    assert b[4][first_open] == KX.R_END and b[3][first_open] == mk.ts(int(sig["coin"][first_open]))[-1]
