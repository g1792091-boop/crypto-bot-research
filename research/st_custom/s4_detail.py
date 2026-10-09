"""Stage 4 (pass 2): detail for the combos that are reported (per strategy x timeframe x variant: the 3 pooled picks,
the 7 per-coin picks, the default and the friend's values), per coin x timeframe x period, plus the luck baseline's
random signal sets (SEARCH).

Per combo: trades, wins, sum net R, sum gross R, signals, longs/shorts; weekly n and sum net R (bootstrap); daily sum
net R by signal day (pooled drawdown); the coin's own max drawdown in signal order; crash-window sums (2020-03,
2022-05, 2022-11).
Luck: for each pick, 50 random sets on this coin's SEARCH bars (same numbers of longs and shorts as the pick's trades
on this coin; for a per-coin pick only on its own coin), outcomes from the pick's variant table (HTF / CHOP: bars
where the filter allows the side; STFLIP: the pick's own Supertrend; MAKER: filled bars).

    python3 -B research/st_custom/s4_detail.py [procs]
"""
import os
import sys
import time
import zlib
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import s2_signals as S2  # noqa: E402

DET_DIR = os.path.join(C.WORK, "detail")
os.makedirs(DET_DIR, exist_ok=True)
NLUCK = 50


def det_path(coin, tf, per):
    return os.path.join(DET_DIR, f"{coin}_{tf}_{per}.npz")


def detail_sets(picks):
    """{(strat, tf, variant): (combos list, pick list [(scope, rank, coin, combo)])}"""
    out = {}
    for (strat, tf, var), g in picks.groupby(["strategy", "tf", "variant"]):
        combos = [C.combo_index(strat, C.DEFAULT_IDX[strat])]
        if strat in C.FRIEND_IDX:
            combos.append(C.combo_index(strat, C.FRIEND_IDX[strat]))
        pl = []
        for r in g.itertuples():
            combos.append(int(r.combo))
            pl.append((r.scope, int(r.rank), r.coin, int(r.combo)))
        out[(strat, tf, var)] = (sorted(set(combos)), pl)
    return out


class Tables:
    """Per-bar outcome tables of one coin x tf x period (both sides) for every variant."""

    def __init__(self, coin, tf, per):
        self.coin, self.tf, self.per = coin, tf, per
        self.bt = C.load_bars(coin, tf)
        self.b15 = C.load_bars(coin, "15m")
        z = np.load(os.path.join(C.OUTC_DIR, f"{coin}_{tf}.npz"))
        self.O = {k: z[k] for k in z.files}
        ts = self.bt["ts"]
        self.N = len(ts)
        self.lo, self.hi = S2.period_range(ts, per)
        self.s0 = max(0, self.lo - C.WARM)
        self.s1 = min(self.N, self.hi + C.SPILL)
        self.last15 = S2.tf_last15(coin, tf, self.bt, self.b15)
        gi = np.arange(self.lo, self.hi)
        self.okbar = self.O["valid"][self.lo:self.hi] & (gi - self.s0 >= C.WARM)
        self.bars = gi[self.okbar]
        self._tp = None
        self._dir = {}
        self.df = None

    def tpsl(self):
        if self._tp is None:
            O, b15 = self.O, self.b15
            R = np.full((len(C.TPSL_CFG), 2, self.N), np.nan, np.float32)
            G = np.full((len(C.TPSL_CFG), 2, self.N), np.nan, np.float32)
            for si, sd in enumerate((1, -1)):
                idx = self.bars
                side = np.full(len(idx), sd, np.int64)
                e = O["e"][idx].astype(np.int64)
                atr = O["atr"][idx]
                lev, liq, _f = C.lev_liq(self.coin, side, atr / b15["o"][e])
                r, g = C.tpsl_outcomes(b15, e, side, atr, lev, liq)
                R[:, si, idx] = r
                G[:, si, idx] = g
            self._tp = (R, G)
        return self._tp

    def direction(self, a, m):
        if (a, m) not in self._dir:
            if self.df is None:
                self.df = C.frame(self.bt, self.tf, self.s0, self.s1)
            self._dir[(a, m)] = C.fg_fast.supertrend(self.df, a, m)[1].to_numpy(float)
        return self._dir[(a, m)]

    def outcome(self, strat, c, vname, gi, sd):
        """(R, G, ok) arrays for signals at bars gi with sides sd under variant vname."""
        O = self.O
        si = np.where(sd > 0, 0, 1)
        if vname in ("main", "htf", "chop"):
            R = np.where(si == 0, O["R_0"][gi], O["R_1"][gi]).astype(float)
            G = np.where(si == 0, O["gross_0"][gi], O["gross_1"][gi]).astype(float)
            ok = np.where(si == 0, O["reason_0"][gi], O["reason_1"][gi]) != 3
            if vname == "htf":
                ok &= np.where(si == 0, O["htf_0"][gi], O["htf_1"][gi])
            elif vname == "chop":
                ok &= O["chop"][gi]
            return R, G, ok
        if vname == "maker":
            R = np.where(si == 0, O["mR_0"][gi], O["mR_1"][gi]).astype(float)
            G = np.where(si == 0, O["mG_0"][gi], O["mG_1"][gi]).astype(float)
            ok = np.where(si == 0, O["mfill_0"][gi] & (O["mreason_0"][gi] != 3),
                          O["mfill_1"][gi] & (O["mreason_1"][gi] != 3))
            return R, G, ok
        if vname == "stflip":
            t = C.combo_tuple(strat, c)
            d = self.direction(C.ST_ATR[t[0]], C.ST_MULT[t[1]])
            R, G = S2.stflip_outcomes(d, self.s0, gi, sd, O, self.b15, self.last15)
            return R, G, np.isfinite(R)
        j = S2.VARIANTS.index(vname) - 5
        TR, TG = self.tpsl()
        R = TR[j, si, gi].astype(float)
        G = TG[j, si, gi].astype(float)
        return R, G, np.isfinite(R)


def job(args):
    coin, tf, per, sets = args
    if os.path.exists(det_path(coin, tf, per)):
        return coin, tf, per, "cached", 0
    t0 = time.time()
    try:
        os.nice(5)
    except OSError:
        pass
    Tb = Tables(coin, tf, per)
    ts = Tb.bt["ts"]
    a, b = C.PERIODS[per]
    week0 = int(C.week_of([C.ts_ns(a)])[0])
    nweek = int(C.week_of([C.ts_ns(b) - 1])[0]) - week0 + 1
    day0 = C.ts_ns(a) // (86400 * 10**9)
    nday = int((C.ts_ns(b) - C.ts_ns(a)) // (86400 * 10**9))
    crash = [(C.ts_ns(x), C.ts_ns(y)) for x, y in C.CRASH.values()]
    out = {}
    sigfile = S2.sig_path(coin, tf, per)
    for strat in C.STRATS:
        codes, offs = C.load_signals(sigfile, strat)
        for (st_, tf_, vname), (combos, pl) in sets.items():
            if st_ != strat or tf_ != tf:
                continue
            k = f"{strat}|{vname}"
            m = len(combos)
            stats = np.zeros((m, 8))
            wn = np.zeros((m, nweek), np.int32)
            ws = np.zeros((m, nweek), np.float32)
            dd = np.zeros((m, nday), np.float32)
            cr = np.zeros((m, len(crash), 4))
            mdd = np.zeros(m)
            for j, c in enumerate(combos):
                cc = codes[offs[c]:offs[c + 1]]
                gi = Tb.lo + cc // 2
                sd = np.where(cc % 2 == 1, 1, -1)
                R, G, ok = Tb.outcome(strat, c, vname, gi, sd)
                R, G = R[ok], G[ok]
                tsig = ts[gi[ok]]
                sdo = sd[ok]
                stats[j] = (len(R), (R > 0).sum(), R.sum(), G.sum(), (R * R).sum(), len(gi), (sdo > 0).sum(),
                            (sdo < 0).sum())
                wk = C.week_of(tsig) - week0
                wn[j] = np.bincount(wk, minlength=nweek)[:nweek]
                ws[j] = np.bincount(wk, weights=R, minlength=nweek)[:nweek]
                dy = (tsig // (86400 * 10**9) - day0).astype(np.int64)
                dd[j] = np.bincount(dy, weights=R, minlength=nday)[:nday]
                for q, (x0, x1) in enumerate(crash):
                    w = (tsig >= x0) & (tsig < x1)
                    cr[j, q] = (w.sum(), (R[w] > 0).sum(), R[w].sum(), G[w].sum())
                mdd[j] = C.max_dd(R)
            out[k + "|combos"] = np.array(combos)
            out[k + "|stats"] = stats
            out[k + "|wn"] = wn
            out[k + "|ws"] = ws
            out[k + "|day"] = dd
            out[k + "|crash"] = cr
            out[k + "|mdd"] = mdd
            # ---------------- luck (SEARCH only)
            if per != "SEARCH":
                continue
            lids, ls, ln = [], [], []
            pool = {}
            for (scope, rank, pcoin, c) in pl:
                if scope == "coin" and pcoin != coin:
                    continue
                j = combos.index(c)
                nl, ns = int(stats[j, 6]), int(stats[j, 7])
                key = c if vname == "stflip" else -1
                if key not in pool:
                    bars = Tb.bars
                    res = []
                    for sd_ in (1, -1):
                        R, G, ok = Tb.outcome(strat, c, vname, bars, np.full(len(bars), sd_))
                        res.append((bars[ok], R[ok]))
                    pool[key] = res
                rng = np.random.default_rng(zlib.crc32(f"{strat}|{tf}|{vname}|{scope}|{rank}|{coin}".encode()))
                s_ = np.zeros(NLUCK)
                n_ = np.zeros(NLUCK)
                for q in range(NLUCK):
                    for (bars_ok, Rok), cnt in zip(pool[key], (nl, ns)):
                        if cnt == 0 or len(Rok) == 0:
                            continue
                        pick = rng.choice(len(Rok), size=min(cnt, len(Rok)), replace=False)
                        s_[q] += Rok[pick].sum()
                        n_[q] += len(pick)
                lids.append(f"{scope}|{rank}|{pcoin}")
                ls.append(s_)
                ln.append(n_)
            out[k + "|luck_ids"] = np.array(lids)
            out[k + "|luck_s"] = np.array(ls)
            out[k + "|luck_n"] = np.array(ln)
    C.save_npz(det_path(coin, tf, per), week0=np.array([week0]), day0=np.array([day0]), **out)
    return coin, tf, per, "ok", round(time.time() - t0, 1)


if __name__ == "__main__":
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    picks = pd.read_csv(os.path.join(C.OUT, "picks.csv"))
    sets = detail_sets(picks)
    jobs = [(c, tf, per, sets) for tf in C.TFS for per in C.PERIOD_ORDER for c in C.COINS]
    jobs.sort(key=lambda j: (j[1] != "15m", {"SEARCH": 0, "TEST": 1, "EXTRA": 2}[j[2]]))
    with Pool(procs, maxtasksperchild=1) as p:
        for r in p.imap_unordered(job, jobs):
            C.log(*r)
