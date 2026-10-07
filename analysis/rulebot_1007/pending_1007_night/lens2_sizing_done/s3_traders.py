"""Q2/Q3: drawdown and ruin of one-position "traders" (one strategy x timeframe set, six coins, one position at a time)
on the 5-year signals, by day-block bootstrap, under sizing rules x edge scenarios.

    python3 -I -B s3_traders.py <workdir> <lev_dir> <out_dir> [B]

Sequences (which signals a trader takes depends on exit times, so per leverage policy):
  K{L}: risk rule, requested leverage L, walks down 50/40/30/20 to the first L whose stop fits (liq buffer, bracket);
        skipped if not even 20x fits. K20f10: 20x, else 10x (the only way most 4h signals fit).
  M{L}: margin rule (margin L% of equity, all live checks incl. 15% max loss), walks down 50/40/30/20 <= L, else skip.
Trade outcome = the 5-year house exit (2 ATR stop + ROE ladder) at the leverage actually used (s2_rerun.py).
Pnl / equity per trade: K: r * R * d / loss_per_notional(d) (a full stop-out costs r); M: L^2/100 * R * d.
Edge scenarios (per trader, on its own trade list): asis (5-year house result), net0 (R - mean R), mcost (gross R
demeaned minus the trade's own cost: gross edge 0, what the rules show), plus01 (R - mean R + 0.1).
Bootstrap: circular 7-day blocks of calendar days 2021-08-01..2026-09-30 (zero-trade days included), horizons 30 and
76 days (10/17 -> 12/31), same block draws for every variant of a trader. Ruin50 / ruin25 = equity at any trade below
50% / 25% of the start (intraday path within a day at trade resolution; drawdown peak taken at day starts).
"""
import os
import sys

sys.dont_write_bytecode = True
WD = sys.argv[1]
sys.path.insert(0, WD)
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import common as C  # noqa: E402

LEV, OUT = sys.argv[2], sys.argv[3]
B = int(sys.argv[4]) if len(sys.argv) > 4 else 2000
TFMIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
NS_MIN = 60 * 10**9
DAY = 86400 * 10**9
T0 = pd.Timestamp("2021-08-01").value
T1 = pd.Timestamp("2026-09-30").value
ND = int((T1 - T0) // DAY)
COIN_ORDER = {"BTCUSD": 0, "ETHUSD": 1, "SOLUSD": 2, "DOGEUSD": 3, "LTCUSD": 4, "BCHUSD": 5}
TFSETS = {"15m": ("15m",), "30m": ("30m",), "1h": ("1h",), "4h": ("4h",), "15m+30m": ("15m", "30m")}
RISKS = (0.01, 0.02, 0.03, 0.05)
HOR = (30, 76)
BLK = 7
EDGES = ("asis", "net0", "mcost", "plus01")


def policies():
    p = {}
    for L in (50, 40, 30, 20):
        p[f"K{L}"] = ("K", [x for x in (50, 40, 30, 20) if x <= L])
        p[f"M{L}"] = ("M", [x for x in (50, 40, 30, 20) if x <= L])
    p["K20f10"] = ("K", [20, 10])
    return p


POL = policies()


def load():
    D = {}
    for tf in TFMIN:
        d = pd.read_pickle(os.path.join(LEV, f"lev_{tf}.pkl"))
        d["strategy"] = d["strategy"].astype(str)
        d["coin"] = d["coin"].astype(str)
        D[tf] = d
    return D


def build_seq(frames, pol):
    """frames: list of (tf, df) of one strategy. Returns trade arrays of the greedy one-position sequence."""
    mode, levs = POL[pol]
    parts = []
    for tf, d in frames:
        used = np.zeros(len(d), int)
        for L in levs:
            ok = d[f"ok{mode}{L}"].values & (d[f"rs_{mode}{L}"].values < 3) & (used == 0)
            used[ok] = L
        sel = used > 0
        if not sel.any():
            continue
        dd = d[sel]
        u = used[sel]
        R = np.choose(np.searchsorted([10, 20, 30, 40, 50], u), [dd[f"R_{mode}{L}"].values for L in (10, 20, 30, 40, 50)])
        gR = np.choose(np.searchsorted([10, 20, 30, 40, 50], u), [dd[f"gR_{mode}{L}"].values for L in (10, 20, 30, 40, 50)])
        h = np.choose(np.searchsorted([10, 20, 30, 40, 50], u), [dd[f"h_{mode}{L}"].values for L in (10, 20, 30, 40, 50)])
        tfm = TFMIN[tf] * NS_MIN
        ent = dd.ts.values + tfm
        ex = dd.ts.values + (h.astype(np.int64) + 1) * tfm
        pr = dd.coin.map(COIN_ORDER).values + 10 * list(TFMIN).index(tf)
        parts.append(pd.DataFrame(dict(ent=ent, ex=ex, pr=pr, R=R.astype(float), gR=gR.astype(float),
                                       d=dd.stop_frac.values.astype(float), L=u, side=dd.side.values,
                                       coin=dd.coin.values, tf=tf)))
    if not parts:
        return None
    a = pd.concat(parts, ignore_index=True).sort_values(["ent", "pr"], kind="stable").reset_index(drop=True)
    a = a[np.isfinite(a.R) & np.isfinite(a.gR)].reset_index(drop=True)
    ent, ex = a.ent.values, a.ex.values
    take = []
    i = 0
    n = len(a)
    while i < n:
        take.append(i)
        i = int(np.searchsorted(ent, ex[i], side="left"))
    return a.iloc[take].reset_index(drop=True)


def edge_R(t, edge):
    R, gR = t.R.values, t.gR.values
    if edge == "asis":
        return R
    if edge == "net0":
        return R - R.mean()
    if edge == "mcost":
        return (gR - gR.mean()) - (gR - R)
    if edge == "plus01":
        return R - R.mean() + 0.1
    raise KeyError(edge)


def frac(t, Rv, mode, r=None):
    d = t.d.values
    if mode == "K":
        return r * Rv * d / C.loss_per_notional(d, t.side.values)
    return (t.L.values.astype(float) ** 2 / 100.0) * Rv * d


def day_arrays(t, f):
    day = ((t.ex.values - T0) // DAY).astype(int)
    keep = (day >= 0) & (day < ND)
    day, f = day[keep], f[keep]
    lg = np.log1p(np.maximum(f, -0.999999))
    G = np.bincount(day, weights=lg, minlength=ND)
    # intraday minimum of the running log sum within each day (trades are in time order)
    m = np.zeros(ND)
    if len(day):
        cs = np.cumsum(lg)
        first = np.r_[True, day[1:] != day[:-1]]
        start = np.where(first, cs - lg, np.nan)
        start = pd.Series(start).ffill().values
        rel = cs - start
        mins = pd.Series(rel).groupby(day).min()
        m[mins.index.values] = np.minimum(0.0, mins.values)
    return G, m


def paths_stats(G, m, idx):
    Gp = G[idx]
    cum = np.cumsum(Gp, axis=1)
    start = cum - Gp
    low = start + m[idx]
    runmax = np.maximum.accumulate(np.maximum(start, 0.0), axis=1)
    minlog = low.min(axis=1)
    mdd = 1 - np.exp((low - runmax).min(axis=1))
    fin = np.exp(cum[:, -1])
    return dict(final_med=np.median(fin), final_p05=np.quantile(fin, .05), final_p95=np.quantile(fin, .95),
                p_loss=np.mean(fin < 1), ruin50=np.mean(minlog < np.log(0.5)), ruin25=np.mean(minlog < np.log(0.25)),
                mdd_med=np.median(mdd), mdd_p95=np.quantile(mdd, .95))


def boot_idx(rng, H):
    nb = -(-H // BLK)
    st = rng.integers(0, ND, size=(B, nb))
    idx = (st[:, :, None] + np.arange(BLK)[None, None, :]) % ND
    return idx.reshape(B, -1)[:, :H]


def main():
    os.makedirs(OUT, exist_ok=True)
    D = load()
    strategies = sorted(set(D["15m"].strategy.unique()))
    if len(sys.argv) > 5:
        strategies = [x for x in strategies if x in sys.argv[5].split(",")]
    rows, trows, conf_rows = [], [], []
    seed = 20261007
    for s in strategies:
        for ts_name, tfs in TFSETS.items():
            frames = [(tf, D[tf][D[tf].strategy == s]) for tf in tfs]
            rng = np.random.default_rng([seed, strategies.index(s), list(TFSETS).index(ts_name)])
            IDX = {H: boot_idx(rng, H) for H in HOR}
            seqs = []
            for pol in POL:
                t = build_seq(frames, pol)
                if t is None or len(t) < 30:
                    continue
                seqs.append((pol, POL[pol][0], t))
                if pol in ("K30", "M30") and len(t) / ND > 2.0:
                    # thinned: each trade kept with p so that about 2 trades / day remain (AI skips)
                    keep = rng.random(len(t)) < 2.0 / (len(t) / ND)
                    seqs.append((pol + "_thin2", POL[pol][0], t[keep].reset_index(drop=True)))
            for pol, mode, t in seqs:
                lpn = C.loss_per_notional(t.d.values, t.side.values)
                trows.append(dict(strategy=s, tfset=ts_name, policy=pol, n=len(t), per_day=len(t) / ND,
                                  mean_R=t.R.mean(), mean_gR=t.gR.mean(), mean_cR=(t.gR - t.R).mean(),
                                  stop_med=np.median(t.d), L_mix=" ".join(f"{k}:{v}" for k, v in
                                                                          t.L.value_counts().sort_index().items()),
                                  M_loss_stop_med=np.median((t.L.values ** 2 / 100.0) * lpn) if mode == "M" else np.nan,
                                  worst_trade_R=t.R.min(), liq_gaps=int(((t.R * t.d) <= -1.0 / t.L + 1e-9).sum())))
                variants = []
                for edge in EDGES:
                    Rv = edge_R(t, edge)
                    if mode == "K":
                        for r in RISKS:
                            variants.append((edge, f"r{int(r*100)}", frac(t, Rv, "K", r)))
                    else:
                        variants.append((edge, "L%", frac(t, Rv, "M")))
                for edge, size, f in variants:
                    G, m = day_arrays(t, f)
                    for H in HOR:
                        st = paths_stats(G, m, IDX[H])
                        rows.append(dict(strategy=s, tfset=ts_name, policy=pol, size=size, edge=edge, H=H,
                                         n_trades=len(t), per_day=len(t) / ND, mean_f=f.mean(),
                                         worst_f=f.min(), **st))
                # Q3 confidence experiment on the K30 sequence (same exits for every sizing rule)
                if pol == "K30":
                    conf_rows += confidence(t, s, ts_name, IDX, rng)
        print(s, len(rows), flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "s3_paths.csv"), index=False)
    pd.DataFrame(trows).to_csv(os.path.join(OUT, "s3_sequences.csv"), index=False)
    pd.DataFrame(conf_rows).to_csv(os.path.join(OUT, "s3_confidence.csv"), index=False)


CONF_R = {1: 0.02, 2: 0.0275, 3: 0.035, 4: 0.0425, 5: 0.05}
CONF_L = {1: 20, 2: 27, 3: 35, 4: 42, 5: 50}


def confidence(t, s, ts_name, IDX, rng):
    """Same trades, five sizing designs, confidence 1..5 per trade. null: confidence independent of the outcome;
    info: confidence uniform but E[R | c] shifted by k * (c - 3) (k = 0.05R, mean unchanged)."""
    out = []
    n = len(t)
    c = rng.integers(1, 6, n)
    d = t.d.values
    side = t.side.values
    lpn = C.loss_per_notional(d, side)
    a = C.atr_from_stop(d, side)
    ck = np.array([C.coin_key(x) for x in t.coin.values])
    # margin rule by confidence leverage, walking down 50,40,30,20 (and the confidence level's own L) to fit
    Lc = np.array([CONF_L[x] for x in c], float)
    Lused = np.zeros(n)
    for L in (50, 42, 40, 35, 30, 27, 20):
        for coin in np.unique(ck):
            sel = (ck == coin) & (Lused == 0) & (L <= Lc)
            if sel.any():
                ok = C.margin_rule(coin, side[sel], d[sel], a[sel], L)["ok"]
                ii = np.nonzero(sel)[0][ok]
                Lused[ii] = L
    Lflat = np.zeros(n)
    for L in (30, 20):
        for coin in np.unique(ck):
            sel = (ck == coin) & (Lflat == 0)
            if sel.any():
                ok = C.margin_rule(coin, side[sel], d[sel], a[sel], L)["ok"]
                Lflat[np.nonzero(sel)[0][ok]] = L
    for info in ("null", "info"):
        for edge in ("mcost", "net0", "plus01"):
            Rv = edge_R(t, edge) + (0.05 * (c - 3) if info == "info" else 0.0)
            designs = {
                "risk_flat_3.5": 0.035 * Rv * d / lpn,
                "risk_conf_2to5": np.array([CONF_R[x] for x in c]) * Rv * d / lpn,
                "risk_flat_2": 0.02 * Rv * d / lpn,
                "margin_conf_20to50": np.where(Lused > 0, Lused ** 2 / 100.0 * Rv * d, 0.0),
                "margin_flat_30": np.where(Lflat > 0, Lflat ** 2 / 100.0 * Rv * d, 0.0),
            }
            for name, f in designs.items():
                G, m = day_arrays(t, f)
                for H in HOR:
                    st = paths_stats(G, m, IDX[H])
                    out.append(dict(strategy=s, tfset=ts_name, info=info, edge=edge, design=name, H=H,
                                    mean_f=f.mean(), sd_f=f.std(), **st))
    return out


main()
