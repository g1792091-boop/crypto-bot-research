"""INTRABAR (PREREG_ADDENDUM_1.md): evaluate the strategy on the FORMING signal-timeframe bar at every 5m close before
the bar's own close, enter at the next 5m open the first time the signal is true inside a bar (and was not true for
the previous complete bar), stop 2 x ATR14 computed with the forming bar as the last bar, house exits.

Forming-bar values. All earlier bars are complete, so every indicator at the forming bar i is one step of its
recursion from the complete state at i-1, with bar i's inputs replaced by the forming ones:
  * true range, ROC, Klinger volume force, hl2: the locked formulas, same operation order, on the forming h/l/c/v;
  * Wilder RMA (ATR) and EMA (Klinger): value_f = value_full[i] + alpha * (input_f - input_full[i]);
    rolling SMA (KST): value_f = value_full[i] + (input_f - input_full[i]) / length.
    These are the recursions' own one-step identities; when the forming bar equals the complete bar the change
    is exactly 0, so the full-bar value is reproduced exactly (unit test), otherwise they agree with a full
    recomputation to ~1e-15 relative;
  * Supertrend: the locked loop body (fg_fast.supertrend) applied once from final bands / direction at i-1;
  * signal logic: the param_defs rules (flip vs the complete i-1 direction, crosses vs complete i-1 values,
    recent(x, 2) = x at i or the complete x at i-1, short &= ~long).
Exits on 5m bars for the intrabar entries AND for the bar-close comparison of the same values (same granularity;
the main 15m-checked numbers are reported next to them). DEVIATIONS.md I14.

    python3 -B research/st_custom/intrabar.py test            # unit test (forming == complete bar)
    python3 -B research/st_custom/intrabar.py run [procs]
"""
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import s2_signals as S2  # noqa: E402

IB_DIR = os.path.join(C.WORK, "intrabar")
os.makedirs(IB_DIR, exist_ok=True)
F_BAR5 = C.FUNDING_8H * 5 / 480.0
PASSES5 = (288, 2304, 18432, 147456)
_fg = C.fg
_fgf = C.fg_fast


def _gt(a, b):
    with np.errstate(invalid="ignore"):
        return a > b


def _lt(a, b):
    with np.errstate(invalid="ignore"):
        return a < b


def _ge(a, b):
    with np.errstate(invalid="ignore"):
        return a >= b


def _le(a, b):
    with np.errstate(invalid="ignore"):
        return a <= b


class Full:
    """Full-series (complete bars) indicator states of one combo on one series df (RangeIndex)."""

    def __init__(self, strat, c, df):
        self.strat = strat
        ov = C.overrides(strat, c)
        self.ov = ov
        self.h = df["high"].to_numpy(float)
        self.l = df["low"].to_numpy(float)
        self.c = df["close"].to_numpy(float)
        self.v = df["volume"].to_numpy(float)
        self.tr = _fg.true_range(df).to_numpy(float)
        self.atr14 = _fg.atr(df, 14).to_numpy(float)
        a, m = ov["st_atr_len"], float(ov["st_mult"])
        self.a, self.m = a, m
        self.atr_st = _fg.atr(df, a).to_numpy(float)
        _line, d, fu, fl = _fgf.supertrend(df, a, m)
        self.d, self.fu, self.fl = d.to_numpy(float), fu.to_numpy(float), fl.to_numpy(float)
        close = df["close"]
        if strat == "S2_ST_ROC":
            self.rl = ov["roc_len"]
            self.roc = _fg.roc(close, self.rl).to_numpy(float)
        elif strat == "N02_ST_KST":
            self.rls = tuple(ov["kst_roc_lens"])
            self.sls = (10, 10, 10, 15)
            self.sigl = ov["kst_signal_len"]
            self.rocs = [_fg.roc(close, r).to_numpy(float) for r in self.rls]
            self.smas = [_fg.sma(_fg.roc(close, r), s).to_numpy(float) for r, s in zip(self.rls, self.sls)]
            line, sig = _fg.kst(close, self.rls, self.sls, self.sigl)
            self.line, self.sig = line.to_numpy(float), sig.to_numpy(float)
        else:
            fast, slow = ov["kvo_lens"]
            self.fast, self.slow, self.sigl = fast, slow, ov["kvo_signal_len"]
            hlc3 = (df["high"] + df["low"] + df["close"]) / 3.0
            self.hlc3 = hlc3.to_numpy(float)
            trend = pd.Series(np.where(hlc3.diff().fillna(0.0) >= 0.0, 1.0, -1.0), index=df.index)
            spread = (df["high"] - df["low"]).replace(0, np.nan)
            force = trend * df["volume"] * ((2.0 * df["close"] - df["high"] - df["low"]) / spread).fillna(0.0) * 100.0
            self.force = force.to_numpy(float)
            self.ef = _fg.ema(force, fast).to_numpy(float)
            self.es = _fg.ema(force, slow).to_numpy(float)
            line, sig = _fg.klinger_oscillator(df, fast, slow, self.sigl)
            self.line, self.sig = line.to_numpy(float), sig.to_numpy(float)
        lg, sh = C.load_param_def(strat).signals(df, df.attrs.get("tf", ""), **ov)
        self.long, self.short = np.asarray(lg, bool), np.asarray(sh, bool)

    # ------------------------------------------------------------------ one step
    def forming(self, p, h, l, c, v):
        """Forming-bar evaluation at series positions p (>= 1) with forming high/low/close/volume.
        Returns (long, short, atr14_forming)."""
        pc = self.c[p - 1]
        with np.errstate(invalid="ignore"):
            tr = np.maximum(np.maximum(h - l, np.abs(h - pc)), np.abs(l - pc))
        tr = np.where(np.isfinite(tr), tr, h - l)
        atr14 = self.atr14[p] + (1.0 / 14) * (tr - self.tr[p])
        atr_st = self.atr_st[p] + (1.0 / self.a) * (tr - self.tr[p])
        # supertrend loop body (fg_fast.supertrend), once
        hl2 = (h + l) / 2.0
        bu = hl2 + self.m * atr_st
        bl = hl2 - self.m * atr_st
        fu_prev, fl_prev, prev_close = self.fu[p - 1], self.fl[p - 1], pc
        with np.errstate(invalid="ignore"):
            fu = np.where((~np.isfinite(fu_prev)) | (bu < fu_prev) | (prev_close > fu_prev), bu, fu_prev)
            fl = np.where((~np.isfinite(fl_prev)) | (bl > fl_prev) | (prev_close < fl_prev), bl, fl_prev)
            prev_dir = self.d[p - 1]
            prev_dir = np.where(np.isfinite(prev_dir), prev_dir, np.where(c >= fl, 1.0, -1.0))
            d = np.where((prev_dir < 0) & (c > fu), 1.0, np.where((prev_dir > 0) & (c < fl), -1.0, prev_dir))
        d = np.where(np.isfinite(atr_st), d, np.nan)
        dp = self.d[p - 1]
        if self.strat == "S2_ST_ROC":
            r = (c / self.c[p - self.rl] - 1.0) * 100.0
            rp = self.roc[p - 1]
            flip_up = _gt(d, 0) & _le(dp, 0)
            flip_dn = _lt(d, 0) & _ge(dp, 0)
            roc_up = _gt(r, 0.0) & _le(rp, 0.0)
            roc_dn = _lt(r, 0.0) & _ge(rp, 0.0)
            lg = _gt(d, 0) & _gt(r, 0) & (flip_up | roc_up)
            sh = _lt(d, 0) & _lt(r, 0) & (flip_dn | roc_dn)
        elif self.strat == "N02_ST_KST":
            comps = []
            for k, (rl, sl) in enumerate(zip(self.rls, self.sls)):
                rf = (c / self.c[p - rl] - 1.0) * 100.0
                smaf = self.smas[k][p] + (rf - self.rocs[k][p]) / sl
                comps.append(smaf * float(k + 1))
            line = comps[0] + comps[1] + comps[2] + comps[3]
            sig = self.sig[p] + (line - self.line[p]) / self.sigl
            lp, sp = self.line[p - 1], self.sig[p - 1]
            up = _gt(line, sig) & _le(lp, sp)
            dn = _lt(line, sig) & _ge(lp, sp)
            up_p = _gt(lp, sp) & _le(self.line[p - 2], self.sig[p - 2])
            dn_p = _lt(lp, sp) & _ge(self.line[p - 2], self.sig[p - 2])
            flip_up = _gt(d, 0) & _le(dp, 0)
            flip_dn = _lt(d, 0) & _ge(dp, 0)
            lg = _gt(d, 0) & (up | up_p) & (up | flip_up)
            sh = _lt(d, 0) & (dn | dn_p) & (dn | flip_dn)
        else:
            hlc3 = (h + l + c) / 3.0
            dif = hlc3 - self.hlc3[p - 1]
            trend = np.where(dif >= 0.0, 1.0, -1.0)
            spread = np.where((h - l) == 0, np.nan, h - l)
            ratio = (2.0 * c - h - l) / spread
            ratio = np.where(np.isnan(ratio), 0.0, ratio)
            force = trend * v * ratio * 100.0
            af, as_, ag = 2.0 / (self.fast + 1.0), 2.0 / (self.slow + 1.0), 2.0 / (self.sigl + 1.0)
            ef = self.ef[p] + af * (force - self.force[p])
            es = self.es[p] + as_ * (force - self.force[p])
            line = ef - es
            sig = self.sig[p] + ag * (line - self.line[p])
            lp, sp = self.line[p - 1], self.sig[p - 1]
            up = _gt(line, sig) & _le(lp, sp)
            dn = _lt(line, sig) & _ge(lp, sp)
            up_p = _gt(lp, sp) & _le(self.line[p - 2], self.sig[p - 2])
            dn_p = _lt(lp, sp) & _ge(self.line[p - 2], self.sig[p - 2])
            flip_up = _gt(d, 0) & _le(dp, 0)
            flip_dn = _lt(d, 0) & _ge(dp, 0)
            lg = _gt(d, 0) & (up | up_p) & (up | flip_up)
            sh = _lt(d, 0) & (dn | dn_p) & (dn | flip_dn)
        lg = np.asarray(lg, bool)
        sh = np.asarray(sh, bool) & ~lg
        return lg, sh, atr14


def unit_test(coin="BTCUSD", per="TEST", combos=None):
    """Forming bar = complete bar at every position: signals equal the locked full-series signals exactly, and the
    forming ATR14 equals the full ATR14 exactly."""
    out = []
    for tf in C.TFS:
        bt = C.load_bars(coin, tf)
        lo, hi = S2.period_range(bt["ts"], per)
        s0, s1 = max(0, lo - C.WARM), min(len(bt["ts"]), hi + C.SPILL)
        df = C.frame(bt, tf, s0, s1)
        for strat in C.STRATS:
            cl = combos.get((strat, tf), []) if combos else []
            cl = sorted(set([C.combo_index(strat, C.DEFAULT_IDX[strat])] + cl +
                            ([C.combo_index(strat, C.FRIEND_IDX[strat])] if strat in C.FRIEND_IDX else [])))
            for c in cl:
                F = Full(strat, c, df)
                p = np.arange(60, len(df))
                lg, sh, a14 = F.forming(p, F.h[p], F.l[p], F.c[p], F.v[p])
                ok_l = np.array_equal(lg, F.long[p])
                ok_s = np.array_equal(sh, F.short[p])
                fin = np.isfinite(F.atr14[p])
                ok_a = np.array_equal(a14[fin], F.atr14[p][fin])
                out.append(dict(coin=coin, tf=tf, period=per, strategy=strat, combo=c, label=C.combo_label(strat, c),
                                bars=len(p), long_signals=int(F.long[p].sum()), short_signals=int(F.short[p].sum()),
                                long_equal=ok_l, short_equal=ok_s, atr14_equal=ok_a,
                                long_mismatch=int((lg != F.long[p]).sum()), short_mismatch=int((sh != F.short[p]).sum())))
                C.log(out[-1])
    return out


def partial_test(coin="BTCUSD", per="TEST", combos=None, n=60, seed=11):
    """Forming bar != complete bar: the one-step evaluation agrees with the locked code recomputed on the series
    truncated at the bar with the bar replaced by the forming one (random partial bars, n positions per combo)."""
    rng = np.random.default_rng(seed)
    out = []
    for tf in C.TFS:
        bt = C.load_bars(coin, tf)
        lo, hi = S2.period_range(bt["ts"], per)
        s0 = max(0, lo - C.WARM)
        df_all = C.frame(bt, tf, s0, min(len(bt["ts"]), s0 + 4000))
        for strat in C.STRATS:
            cl = combos.get((strat, tf), []) if combos else []
            cl = sorted(set([C.combo_index(strat, C.DEFAULT_IDX[strat])] + cl +
                            ([C.combo_index(strat, C.FRIEND_IDX[strat])] if strat in C.FRIEND_IDX else [])))
            for c in cl:
                F = Full(strat, c, df_all)
                # positions near signals (so that the test covers the edge cases), plus random ones
                sigp = np.flatnonzero((F.long | F.short)[700:3900]) + 700
                ps = np.unique(np.concatenate([rng.choice(sigp, min(n // 2, len(sigp)), replace=False),
                                               rng.integers(700, 3900, n // 2)]))
                bad, bad_atr, maxrel = 0, 0, 0.0
                for p in ps:
                    o_, h_, l_, c_, v_ = (df_all[k].iloc[p] for k in ("open", "high", "low", "close", "volume"))
                    hf = o_ + rng.random() * (h_ - o_) if h_ > o_ else h_
                    lf = o_ - rng.random() * (o_ - l_) if l_ < o_ else l_
                    hf, lf = max(hf, o_), min(lf, o_)
                    cf = lf + rng.random() * (hf - lf)
                    vf = v_ * (0.2 + 0.8 * rng.random())
                    d2 = df_all.iloc[:p + 1].copy()
                    d2.iloc[p, d2.columns.get_loc("high")] = hf
                    d2.iloc[p, d2.columns.get_loc("low")] = lf
                    d2.iloc[p, d2.columns.get_loc("close")] = cf
                    d2.iloc[p, d2.columns.get_loc("volume")] = vf
                    d2.attrs["tf"] = tf
                    lg2, sh2 = C.load_param_def(strat).signals(d2, tf, **C.overrides(strat, c))
                    a2 = _fg.atr(d2, 14).to_numpy(float)[p]
                    lg, sh, a14 = F.forming(np.array([p]), np.array([hf]), np.array([lf]), np.array([cf]),
                                            np.array([vf]))
                    bad += int(lg[0] != bool(lg2[p])) + int(sh[0] != bool(sh2[p]))
                    rel = abs(a14[0] / a2 - 1)
                    maxrel = max(maxrel, rel)
                    bad_atr += int(rel > 1e-12)
                out.append(dict(coin=coin, tf=tf, strategy=strat, combo=c, label=C.combo_label(strat, c),
                                positions=len(ps), signal_mismatches=bad, atr14_rel_gt_1e12=bad_atr,
                                atr14_max_rel=maxrel))
                C.log(out[-1])
    return out


def test_combos():
    """Default, friend and every pick (pooled and per-coin, main variant) per strategy x tf."""
    import pandas as pd
    p = os.path.join(C.OUT, "picks.csv")
    if not os.path.exists(p):
        return None
    P = pd.read_csv(p)
    P = P[P.variant == "main"]
    return {(s, tf): sorted(set(int(x) for x in g.combo)) for (s, tf), g in P.groupby(["strategy", "tf"])}


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "test":
    tc = test_combos()
    res = unit_test(combos=tc) + unit_test(coin="DOGEUSD", per="EXTRA", combos=tc)
    part = partial_test(combos=tc, n=40)
    C.save_json(os.path.join(C.OUT, "intrabar_unit_test.json"), dict(complete_bar=res, partial_bar=part))
    print("ALL EQUAL" if all(r["long_equal"] and r["short_equal"] and r["atr14_equal"] for r in res) else "MISMATCH")
    print("PARTIAL OK" if all(r["signal_mismatches"] == 0 and r["atr14_rel_gt_1e12"] == 0 for r in part)
          else "PARTIAL MISMATCH")


# ------------------------------------------------------------------ run
def ib_sets(picks, coin_picks=False):
    """{(strat, tf): [(set name, combo)]}: default, friend, pooled picks (main variant) [, per-coin picks]."""
    out = {}
    for strat in C.STRATS:
        for tf in C.TFS:
            L = [("default", C.combo_index(strat, C.DEFAULT_IDX[strat]))]
            if strat in C.FRIEND_IDX:
                L.append(("friend", C.combo_index(strat, C.FRIEND_IDX[strat])))
            g = picks[(picks.strategy == strat) & (picks.tf == tf) & (picks.variant == "main")]
            for r in g[g.scope == "pooled"].itertuples():
                L.append((f"pick{r.rank}", int(r.combo)))
            if coin_picks:
                for r in g[g.scope == "coin"].itertuples():
                    L.append((f"coinpick_{r.coin}", int(r.combo)))
            out[(strat, tf)] = L
    return out


def ib_path(coin, tf, per):
    return os.path.join(IB_DIR, f"{coin}_{tf}_{per}.npz")


def sub5(bt, b5, tf, gi):
    """5m indices (n x nsub) of the sub-bars of tf bars gi; complete flag."""
    nsub = C.TF_MIN[tf] // 5
    t = bt["ts"][gi][:, None] + np.arange(nsub)[None, :] * 5 * C.NS_MIN
    k = np.searchsorted(b5["ts"], t)
    kc = np.minimum(k, len(b5["ts"]) - 1)
    ok = np.all(b5["ts"][kc] == t, axis=1)
    return kc, ok


def ib_job(args):
    coin, tf, per, sets = args
    if os.path.exists(ib_path(coin, tf, per)):
        return coin, tf, per, "cached", 0
    t0 = time.time()
    try:
        os.nice(5)
    except OSError:
        pass
    bt = C.load_bars(coin, tf)
    b5 = C.load_bars(coin, "5m")
    O = np.load(os.path.join(C.OUTC_DIR, f"{coin}_{tf}.npz"))
    valid = O["valid"]
    ts = bt["ts"]
    lo, hi = S2.period_range(ts, per)
    s0, s1 = max(0, lo - C.WARM), min(len(ts), hi + C.SPILL)
    df = C.frame(bt, tf, s0, s1)
    nsub = C.TF_MIN[tf] // 5
    step_ns = C.TF_MIN[tf] * C.NS_MIN
    a_, b_ = C.PERIODS[per]
    week0 = int(C.week_of([C.ts_ns(a_)])[0])
    nweek = int(C.week_of([C.ts_ns(b_) - 1])[0]) - week0 + 1
    p_all = np.arange(lo, hi) - s0
    p_all = p_all[(p_all >= max(C.WARM, 2))]
    gi_all = p_all + s0
    k5, comp = sub5(bt, b5, tf, gi_all)
    # forming bars at steps j = 0 .. nsub-2 (after the (j+1)-th 5m close)
    H5 = np.maximum.accumulate(b5["h"][k5], axis=1)
    L5 = np.minimum.accumulate(b5["l"][k5], axis=1)
    V5 = np.cumsum(b5["v"][k5], axis=1)
    C5 = b5["c"][k5]
    # 5m aggregate of the whole bar vs the tf bar (data consistency, reported)
    agg_same = (np.abs(H5[:, -1] / bt["h"][gi_all] - 1) < 1e-12) & (np.abs(L5[:, -1] / bt["l"][gi_all] - 1) < 1e-12) \
        & (np.abs(C5[:, -1] / bt["c"][gi_all] - 1) < 1e-12)
    res = {}
    out_meta = dict(bars=int(len(gi_all)), bars_5m_complete=int(comp.sum()),
                    bars_5m_agg_equal_ohlc=int((agg_same & comp).sum()))
    for strat in C.STRATS:
        for setn, c in sets[(strat, tf)]:
            if setn.startswith("coinpick_") and setn != f"coinpick_{coin}":
                continue
            F = Full(strat, c, df)
            trades = []    # (kind, side, gi, j, entry5, atr, kept)
            for sd, full_sig in ((1, F.long), (-1, F.short)):
                prev_true = full_sig[p_all - 1]
                first_j = np.full(len(p_all), -1)
                for j in range(nsub - 1):
                    lg, sh, a14 = F.forming(p_all, H5[:, j], L5[:, j], C5[:, j], V5[:, j])
                    hit = (lg if sd > 0 else sh) & comp & ~prev_true & (first_j < 0)
                    first_j = np.where(hit, j, first_j)
                    if j == 0:
                        A14 = np.full((nsub - 1, len(p_all)), np.nan)
                    A14[j] = a14
                ii = np.flatnonzero(first_j >= 0)
                jj = first_j[ii]
                e5 = k5[ii, jj + 1]
                trades.append(("ib", sd, gi_all[ii], jj, e5, A14[jj, ii], full_sig[p_all[ii]]))
                # bar-close entries of the same values (signal at the complete bar, entry at the next tf bar open)
                pc = np.flatnonzero(full_sig[p_all] & valid[gi_all])
                tnext = ts[gi_all[pc]] + step_ns
                e5c = np.searchsorted(b5["ts"], tnext)
                okc = e5c < len(b5["ts"])
                okc[okc] &= b5["ts"][e5c[okc]] == tnext[okc]
                pc, e5c = pc[okc], e5c[okc]
                trades.append(("bc", sd, gi_all[pc], np.full(len(pc), -1), e5c, F.atr14[p_all[pc]],
                               np.ones(len(pc), bool)))
            for kind in ("ib", "bc"):
                parts = [t for t in trades if t[0] == kind]
                side = np.concatenate([np.full(len(t[2]), t[1]) for t in parts]).astype(np.int64)
                gi = np.concatenate([t[2] for t in parts])
                jj = np.concatenate([t[3] for t in parts])
                e5 = np.concatenate([t[4] for t in parts]).astype(np.int64)
                atr = np.concatenate([t[5] for t in parts])
                kept = np.concatenate([t[6] for t in parts])
                okk = np.isfinite(atr) & (atr > 0)
                side, gi, jj, e5, atr, kept = side[okk], gi[okk], jj[okk], e5[okk], atr[okk], kept[okk]
                raw = b5["o"][e5]
                lev, liq, _fe = C.lev_liq(coin, side, atr / raw)
                r = C.run_scan(b5, e5, side, lev, liq, C.K_STOP * atr, f_bar=F_BAR5, passes=PASSES5)
                done = r["done"]
                R, G = r["R"][done], r["gross"][done]
                wk = C.week_of(ts[gi[done]]) - week0
                key = f"{strat}|{setn}|{kind}"
                res[key + "|stats"] = np.array([done.sum(), (R > 0).sum(), R.sum(), G.sum(), len(done),
                                                (~kept).sum(), (~kept[done]).sum(),
                                                (R[~kept[done]] > 0).sum(), R[~kept[done]].sum(),
                                                R[kept[done]].sum(), kept[done].sum()], float)
                res[key + "|wn"] = np.bincount(wk, minlength=nweek)[:nweek]
                res[key + "|ws"] = np.bincount(wk, weights=R, minlength=nweek)[:nweek]
                res[key + "|combo"] = np.array([c])
                if kind == "ib":
                    res[key + "|steps"] = np.bincount(jj, minlength=nsub - 1)
                    ib_rec = dict(gi=gi, side=side, raw=raw, kept=kept, R=r["R"], done=done)
                else:
                    # pair kept intrabar trades with the bar-close trade of the same bar and side
                    kb = gi * 2 + (side > 0)
                    ka = ib_rec["gi"] * 2 + (ib_rec["side"] > 0)
                    pos = np.searchsorted(np.sort(kb), ka)
                    order = np.argsort(kb)
                    kbs = kb[order]
                    m = (pos < len(kbs))
                    m[m] &= kbs[np.minimum(pos[m], len(kbs) - 1)] == ka[m]
                    m &= ib_rec["kept"]
                    jb = order[pos[m]]
                    bps = ib_rec["side"][m] * (raw[jb] - ib_rec["raw"][m]) / raw[jb] * 1e4
                    both = ib_rec["done"][m] & done[jb]
                    dR = ib_rec["R"][m][both] - r["R"][jb][both]
                    res[f"{strat}|{setn}|pair"] = np.array([m.sum(), bps.sum(), (bps * bps).sum(), np.median(bps)
                                                            if len(bps) else np.nan, both.sum(), dR.sum(),
                                                            (dR * dR).sum()], float)
    C.save_npz(ib_path(coin, tf, per), meta=np.array([str(out_meta)]), **res)
    return coin, tf, per, str(out_meta), round(time.time() - t0, 1)


def ib_run(procs, coin_picks):
    import pandas as pd
    picks = pd.read_csv(os.path.join(C.OUT, "picks.csv"))
    sets = ib_sets(picks, coin_picks)
    jobs = [(c, tf, per, sets) for tf in C.TFS for per in C.PERIOD_ORDER for c in C.COINS]
    jobs.sort(key=lambda j: (j[1] != "15m", {"SEARCH": 0, "TEST": 1, "EXTRA": 2}[j[2]]))
    with Pool(procs, maxtasksperchild=1) as p:
        for r in p.imap_unordered(ib_job, jobs):
            C.log(*r)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "run":
    ib_run(int(sys.argv[2]) if len(sys.argv) > 2 else 3, "--coinpicks" in sys.argv)


def ib_report():
    """out/intrabar.csv: pooled over coins (per-coin picks: their coin) per strategy x tf x set x period."""
    import pandas as pd
    picks = pd.read_csv(os.path.join(C.OUT, "picks.csv"))
    sets = ib_sets(picks, True)
    PR = pd.read_csv(os.path.join(C.OUT, "pick_results.csv"))
    rows = []
    for (strat, tf), L in sets.items():
        for setn, c in L:
            coins = [setn.split("_", 1)[1]] if setn.startswith("coinpick_") else list(C.COINS)
            for per in C.PERIOD_ORDER:
                agg = {}
                wk = {}
                for coin in coins:
                    z = np.load(ib_path(coin, tf, per))
                    for kind in ("ib", "bc"):
                        k = f"{strat}|{setn}|{kind}"
                        agg[kind] = agg.get(kind, 0) + z[k + "|stats"]
                        wn, ws = z[k + "|wn"].astype(float), z[k + "|ws"].astype(float)
                        if kind in wk:
                            wk[kind] = (wk[kind][0] + wn, wk[kind][1] + ws)
                        else:
                            wk[kind] = (wn, ws)
                    agg["pair"] = agg.get("pair", 0) + np.nan_to_num(z[f"{strat}|{setn}|pair"])
                    agg["steps"] = agg.get("steps", 0) + z[f"{strat}|{setn}|ib|steps"]
                ib, bc, pr = agg["ib"], agg["bc"], agg["pair"]
                lo_i, hi_i = C.boot_ci(*wk["ib"], 2000, 1)
                lo_b, hi_b = C.boot_ci(*wk["bc"], 2000, 2)
                scope = coins[0] if len(coins) == 1 else "ALL"
                setkey = "coinpick" if setn.startswith("coinpick_") else setn
                m = PR[(PR.strategy == strat) & (PR.tf == tf) & (PR.variant == "main") & (PR.set == setkey) &
                       (PR.combo == c) & (PR.scope == scope) & (PR.period == per)]
                n_pair = pr[0]
                rows.append(dict(
                    strategy=strat, tf=tf, set=setkey, scope=scope, combo=c, label=C.combo_label(strat, c), period=per,
                    ib_signals=int(ib[4]), ib_trades=int(ib[0]), ib_vanished_share=ib[5] / ib[4] if ib[4] else np.nan,
                    ib_win_rate=ib[1] / ib[0] if ib[0] else np.nan, ib_gross_R=ib[3] / ib[0] if ib[0] else np.nan,
                    ib_cost_R=(ib[3] - ib[2]) / ib[0] if ib[0] else np.nan, ib_net_R=ib[2] / ib[0] if ib[0] else np.nan,
                    ib_ci_lo=lo_i, ib_ci_hi=hi_i,
                    ib_net_R_kept=ib[9] / ib[10] if ib[10] else np.nan,
                    ib_net_R_vanished=ib[8] / ib[6] if ib[6] else np.nan,
                    ib_win_rate_vanished=ib[7] / ib[6] if ib[6] else np.nan,
                    ib_first_step_share=(agg["steps"][0] / agg["steps"].sum()) if agg["steps"].sum() else np.nan,
                    bc5_trades=int(bc[0]), bc5_win_rate=bc[1] / bc[0] if bc[0] else np.nan,
                    bc5_gross_R=bc[3] / bc[0] if bc[0] else np.nan, bc5_cost_R=(bc[3] - bc[2]) / bc[0] if bc[0] else np.nan,
                    bc5_net_R=bc[2] / bc[0] if bc[0] else np.nan, bc5_ci_lo=lo_b, bc5_ci_hi=hi_b,
                    main15_net_R=float(m.net_R.iloc[0]) if len(m) else np.nan,
                    main15_trades=int(m.trades.iloc[0]) if len(m) else 0,
                    entry_diff_bps_mean=pr[1] / n_pair if n_pair else np.nan,
                    entry_diff_bps_sd=np.sqrt(max(pr[2] / n_pair - (pr[1] / n_pair) ** 2, 0)) if n_pair else np.nan,
                    kept_pairs=int(n_pair), kept_pair_dR_mean=pr[5] / pr[4] if pr[4] else np.nan))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(C.OUT, "intrabar.csv"), index=False, float_format="%.5g")
    return df


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "report":
    print(ib_report().to_string())
