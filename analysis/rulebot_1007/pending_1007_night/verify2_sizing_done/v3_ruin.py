"""Independent ruin / confidence check (Z4, Z5, Z6, Z8, Z9).

python3 -I -B v3_ruin.py <fy36_dir> <out_dir> [B]

Data: lens/fiveyear fy36_<tf>.pkl.gz (NOT the sizing analyst's lev pickles): every signal of the 36 locked strategies
2021-08-01..2026-09-30, outcome = house exit at the v4 'normal' leverage (repo size_position, 30x then 20x margin rule,
example brackets). Leverage barely changes R (v2_levR.py), so the same R is used for every sizing rule.
Executable set: v4n sized (stop inside liq at 20x/30x, 15% check). Margin-rule policies M20..M50: own feasibility walk
(live inferred brackets, 1 ATR buffer, 15% max loss) over the same signals.
One position per strategy over 6 coins and the chosen timeframes; greedy, ties broken RANDOMLY (seeded).
Bootstrap: STATIONARY bootstrap of calendar days (geometric block length, mean 10 days), trades kept on their ENTRY day,
zero-trade days included, 2,000 paths, horizons 30 / 76 days. Sensitivity: iid days (mean block 1) and mean 28.
Edges per strategy-sequence: asis; net0 = R - mean(R); mcost = R - mean(gross R) (gross mean 0, net = -own cost);
plus01 = R - mean(R) + 0.1.
Equity per trade: risk rule f = r * R * d / (d + exit slip + 2 taker); margin rule f = L^2/100 * R * d, floored at
-L/100 (isolated margin).
"""
import os
import sys

sys.dont_write_bytecode = True
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FY, OUT = sys.argv[1], sys.argv[2]
B = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
os.makedirs(OUT, exist_ok=True)
TAKER, SLIP, E0 = 0.0005, 0.0002, 5000.0
TFMIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
DAYNS = 86400 * 10**9
T0 = pd.Timestamp("2021-08-01").value
ND = int((pd.Timestamp("2026-09-30").value - T0) // DAYNS)
BRK = {
    "BTC": [(1e12, 50, 0.004, 0.0)], "ETH": [(1e12, 50, 0.004, 0.0)],
    "SOL": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGE": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCH": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTC": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}


def lpn(d):
    stop = 1 - d
    ex = stop * (1 - SLIP)
    return d + (stop - ex) + TAKER + ex * TAKER


def mfeas(coin, side, d, a, L):
    n = np.full(d.shape, L * L / 100 * E0)
    t = BRK[coin]
    ml = np.zeros_like(n); mmr = np.zeros_like(n); cum = np.zeros_like(n); done = np.zeros(n.shape, bool)
    for capn, lev, m, c in t:
        s = (~done) & (n <= capn); ml[s], mmr[s], cum[s] = lev, m, c; done |= s
    margin = n / L
    lp = np.maximum((margin + cum - side * n) / (n * mmr - side * n), 0)
    lq = side * (1 - lp)
    return (ml >= L) & (lq - d >= np.maximum(a, 0.002)) & (n * lpn(d) / E0 <= 0.15)


def load():
    fr = []
    for tf in ("15m", "30m", "1h", "4h"):
        d = pd.read_pickle(os.path.join(FY, f"fy36_{tf}.pkl.gz"))
        d = d[(d.v4n_lev > 0) & d.v4n_done].copy()
        d = d[["strategy", "coin", "ts", "side", "stop_frac", "v4n_lev", "v4n_R", "v4n_gross", "v4n_held"]]
        d["strategy"] = d.strategy.astype(str)
        d["coin"] = d.coin.astype(str).str.replace("USD", "")
        d["tf"] = tf
        d["d"] = d.stop_frac.astype(float)
        a = (d.d * (1 + d.side * SLIP) - SLIP) / 2
        d["gR"] = d.v4n_gross.astype(float) / d.d
        d["R"] = d.v4n_R.astype(float)
        tfm = TFMIN[tf] * 60 * 10**9
        d["ent"] = d.ts + tfm
        d["ex"] = d.ts + (d.v4n_held.astype(np.int64) + 1) * tfm
        for top in (50, 40, 30, 20):     # margin-rule walk from 'top' down to 20
            lev = np.zeros(len(d))
            for L in [x for x in (50, 40, 30, 20) if x <= top]:
                for coin in d.coin.unique():
                    m = (d.coin == coin).values & (lev == 0)
                    if m.any():
                        ok = mfeas(coin, d.side.values[m], d.d.values[m], a.values[m], L)
                        idx = np.nonzero(m)[0][ok]
                        lev[idx] = L
            d[f"M{top}"] = lev
        fr.append(d.drop(columns=["stop_frac", "v4n_R", "v4n_gross", "v4n_held"]))
    return pd.concat(fr, ignore_index=True)


def greedy(a, rng, skip_p=0.0):
    a = a.assign(tb=rng.random(len(a))).sort_values(["ent", "tb"]).reset_index(drop=True)
    if skip_p > 0:
        a = a[rng.random(len(a)) >= skip_p].reset_index(drop=True)
    ent, ex = a.ent.values, a.ex.values
    take, i, n = [], 0, len(a)
    while i < n:
        take.append(i)
        i = int(np.searchsorted(ent, ex[i], side="left"))
        # entries at the exact exit time are allowed (same as a fresh bar)
    return a.iloc[take].reset_index(drop=True)


def day_tables(t, f):
    day = ((t.ent.values - T0) // DAYNS).astype(int)
    k = (day >= 0) & (day < ND)
    day, f = day[k], f[k]
    lg = np.log1p(np.maximum(f, -0.999999))
    G = np.bincount(day, lg, minlength=ND)
    m = np.zeros(ND)
    # within-day running minimum of the cumulative log return (trade resolution)
    order = np.argsort(day, kind="stable")
    day, lg = day[order], lg[order]
    cs = np.cumsum(lg)
    first = np.r_[True, day[1:] != day[:-1]]
    base = np.maximum.accumulate(np.where(first, np.arange(len(day)), 0))
    rel = cs - (cs[base] - lg[base])
    np.minimum.at(m, day, rel)
    return G, np.minimum(m, 0)


def stationary_idx(rng, H, mean_block):
    idx = np.empty((B, H), int)
    cur = rng.integers(0, ND, B)
    for h in range(H):
        if h == 0:
            idx[:, 0] = cur
            continue
        new = rng.random(B) < 1.0 / mean_block
        cur = np.where(new, rng.integers(0, ND, B), (cur + 1) % ND)
        idx[:, h] = cur
    return idx


def stats(G, m, idx):
    Gp = G[idx]
    cum = np.cumsum(Gp, 1)
    low = (cum - Gp) + m[idx]
    minlog = low.min(1)
    fin = np.exp(cum[:, -1])
    return dict(ruin50=np.mean(minlog < np.log(.5)), ruin25=np.mean(minlog < np.log(.25)), med_end=np.median(fin))


def edge(t, e):
    R, gR = t.R.values, t.gR.values
    return dict(asis=R, net0=R - R.mean(), mcost=R - gR.mean(), plus01=R - R.mean() + 0.1)[e]


def main():
    D = load()
    rng0 = np.random.default_rng(20261008)
    rows, seqrows, conf = [], [], []
    strategies = sorted(D.strategy.unique())
    TS = {"15m+30m": ("15m", "30m"), "1h": ("1h",), "4h": ("4h",)}
    for si, s in enumerate(strategies):
        for tsn, tfs in TS.items():
            a = D[(D.strategy == s) & D.tf.isin(tfs)]
            if len(a) < 30:
                continue
            rng = np.random.default_rng([20261008, si, len(tsn)])
            IDX = {(H, mb): stationary_idx(rng, H, mb) for H in (30, 76) for mb in ((10, 1, 28) if tsn == "15m+30m" else (10,))}
            seqs = {"K": greedy(a, rng)}
            for top in (20, 30, 40, 50):
                seqs[f"M{top}"] = greedy(a[a[f"M{top}"] > 0], rng)
            if tsn == "15m+30m":
                pd_full = len(seqs["K"]) / ND
                if pd_full > 2.5:
                    # proper thinning: skip signals BEFORE the greedy pass (a skipped signal frees the slot), tune p to ~2/day
                    lo, hi = 0.0, 0.999
                    for _ in range(14):
                        p = (lo + hi) / 2
                        n = len(greedy(a, np.random.default_rng([1, si]), p)) / ND
                        lo, hi = (p, hi) if n > 2.0 else (lo, p)
                    seqs["K_thin2"] = greedy(a, np.random.default_rng([2, si]), (lo + hi) / 2)
            for pol, t in seqs.items():
                if len(t) < 30:
                    continue
                seqrows.append(dict(strategy=s, tfset=tsn, policy=pol, n=len(t), per_day=len(t) / ND, mean_R=t.R.mean(),
                                    mean_gR=t.gR.mean(), mean_cost=(t.gR - t.R).mean(), stop_med=t.d.median()))
                for e in ("net0", "mcost", "plus01", "asis"):
                    Rv = edge(t, e)
                    if pol.startswith("K"):
                        variants = [(f"r{int(r*100)}", r * Rv * t.d.values / lpn(t.d.values)) for r in (0.01, 0.02, 0.03, 0.05)]
                    else:
                        L = t[pol].values
                        variants = [("L%", np.maximum(L * L / 100 * Rv * t.d.values, -L / 100))]
                    for size, f in variants:
                        G, m = day_tables(t, f)
                        for (H, mb), idx in IDX.items():
                            if mb != 10 and not (pol == "K" and size in ("r1", "r2")) and not (pol == "M30"):
                                continue
                            rows.append(dict(strategy=s, tfset=tsn, policy=pol, size=size, edge=e, H=H, mb=mb,
                                             per_day=len(t) / ND, **stats(G, m, idx)))
                if pol == "K" and tsn == "15m+30m":
                    conf += confidence(t, s, rng, IDX[(76, 10)])
        print(s, flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "v3_paths.csv"), index=False)
    pd.DataFrame(seqrows).to_csv(os.path.join(OUT, "v3_seq.csv"), index=False)
    pd.DataFrame(conf).to_csv(os.path.join(OUT, "v3_conf.csv"), index=False)


def confidence(t, s, rng, idx):
    out = []
    n = len(t)
    c = rng.integers(1, 6, n)
    d = t.d.values
    side = t.side.values
    a = (d * (1 + side * SLIP) - SLIP) / 2
    lp = lpn(d)
    Lmap = {1: 20, 2: 27, 3: 35, 4: 42, 5: 50}
    rmap = {1: 0.02, 2: 0.0275, 3: 0.035, 4: 0.0425, 5: 0.05}

    def walk(cap_arr, ladder):
        lev = np.zeros(n)
        for L in ladder:
            for coin in np.unique(t.coin.values):
                m = (t.coin.values == coin) & (lev == 0) & (L <= cap_arr)
                if m.any():
                    ok = mfeas(coin, side[m], d[m], a[m], L)
                    lev[np.nonzero(m)[0][ok]] = L
        return lev
    Lc = walk(np.array([Lmap[x] for x in c], float), (50, 42, 40, 35, 30, 27, 20))
    L30 = walk(np.full(n, 30.0), (30, 20))
    L35 = walk(np.full(n, 35.0), (35, 30, 27, 20))
    for info in ("null", "info"):
        for e in ("net0", "mcost", "plus01"):
            Rv = edge(t, e) + (0.05 * (c - 3) if info == "info" else 0)
            des = {"risk_conf_2to5": np.array([rmap[x] for x in c]) * Rv * d / lp,
                   "risk_flat_3.5": 0.035 * Rv * d / lp, "risk_flat_2": 0.02 * Rv * d / lp,
                   "margin_conf_20to50": Lc ** 2 / 100 * Rv * d, "margin_flat_30": L30 ** 2 / 100 * Rv * d,
                   "margin_flat_35": L35 ** 2 / 100 * Rv * d}
            for k, f in des.items():
                G, m = day_tables(t, f)
                out.append(dict(strategy=s, info=info, edge=e, design=k, meanL2=np.mean((Lc if k == "margin_conf_20to50" else L30 if k == "margin_flat_30" else L35) ** 2) if k.startswith("margin") else np.nan,
                                **stats(G, m, idx)))
    return out


main()
