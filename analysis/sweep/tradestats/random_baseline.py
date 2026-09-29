"""Random-entry baseline with the same engine, exits and costs: random +/-1 signals, 5 years (is+oos+final)."""
import sys, os, warnings, numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "harness"))
import sweep_lib as L, fg_indicators as fg
H = 16; EX = [e for e in L.exit_set(H) if e[0] in ("TIME_H", "ATR_SL2_TP3")]
tf = sys.argv[1]; target = int(sys.argv[2]); seeds = int(sys.argv[3])
P = {sp: L.load_panel(tf, sp) for sp in ("is", "oos", "final")}
A = {sp: {c: fg.atr(df, 14).to_numpy(float) for c, df in p.items()} for sp, p in P.items()}
W = {}
for sp, p in P.items():
    W[sp] = {}
    for c, df in p.items():
        lo, hi = L.signal_window(df, tf, sp, 0)
        if hi - lo > 2 * L.EXIT_CAP_MULT * H + 4: W[sp][c] = (lo, hi)
nbars = sum(hi - lo for sp in W for (lo, hi) in W[sp].values())
rate = target / nbars * 1.3
rows = []
for s in range(seeds):
    rng = np.random.default_rng([s, 777])
    res = {e[0]: [] for e in EX}
    for sp, p in P.items():
        dsig = {c: np.where(rng.random(len(df)) < rate, rng.choice([-1, 1], len(df)), 0).astype(np.int8) for c, df in p.items()}
        r = L._run_exits_panel(p, dsig, tf, sp, H, A[sp], W[sp], 0, EX)
        for k, v in r.items(): res[k].append(v)
    for k, v in res.items():
        t = pd.concat(v); net = t.net.to_numpy(); lo = t.side.to_numpy() > 0; w = net > 0
        rows.append(dict(tf=tf, seed=s, exit=k, trades=len(t), win_rate=w.mean(), pf_net=net[w].sum() / -net[~w].sum(),
                         pf_gross=t.gross[t.gross > 0].sum() / -t.gross[t.gross <= 0].sum(), exp_net=net.mean() * 100,
                         exp_gross=t.gross.mean() * 100, exp_net_long=net[lo].mean() * 100, exp_net_short=net[~lo].mean() * 100))
pd.DataFrame(rows).to_csv(os.path.join(HERE, f"random_{tf}.csv"), index=False)
