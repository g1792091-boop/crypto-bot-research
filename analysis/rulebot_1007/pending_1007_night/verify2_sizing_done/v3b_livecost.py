"""Ruin at r 1/2% under today's (live, quiet market) cost per trade instead of the 5-year cost.
python3 -I -B v3b_livecost.py <fy36_dir> <out_real_dir>   (reuses v3_ruin.py functions)"""
import sys, os
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "v3_ruin.py")).read().rsplit("\nmain()", 1)[0]
sys.argv = [sys.argv[0], sys.argv[1], "out", "2000"] + sys.argv[2:]
OR = sys.argv[4]
exec(src)
te = pd.read_csv(os.path.join(OR, "trades_enriched.csv"))
te = te[te.kind.isin(["strategy", "ds200"])]
D = load()
D["cR"] = D.gR - D.R
k = {}
for tf in ("15m", "30m"):
    live = te[te.timeframe == tf].cost_all_R.median()
    fy = D[D.tf == tf].cR.median()
    k[tf] = live / fy
    print(tf, "live median cost_all_R", round(live, 3), "5y median", round(fy, 3), "factor", round(k[tf], 2),
          "live n", int((te.timeframe == tf).sum()))
res = []
for si, s in enumerate(sorted(D.strategy.unique())):
    a = D[(D.strategy == s) & D.tf.isin(["15m", "30m"])]
    if len(a) < 30:
        continue
    rng = np.random.default_rng([20261008, si, 7])
    idx = stationary_idx(rng, 76, 10)
    t = greedy(a, rng)
    kk = t.tf.map(k).values
    for e, Rv in (("mcost", t.R.values - t.gR.mean()), ("mcost_live", t.R.values - t.gR.mean() - (kk - 1) * t.cR.values)):
        for r in (0.01, 0.02):
            G, m = day_tables(t, r * Rv * t.d.values / lpn(t.d.values))
            res.append(dict(s=s, e=e, r=r, meanR=Rv.mean(), **stats(G, m, idx)))
r = pd.DataFrame(res)
print(r.groupby(["e", "r"]).agg(meanR=("meanR", "mean"), ruin50=("ruin50", "mean"), med=("med_end", "median")).round(3))
