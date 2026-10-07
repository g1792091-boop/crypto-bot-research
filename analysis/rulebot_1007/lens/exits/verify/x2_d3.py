import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
ex = sys.argv[1]
out = []
for run in ["run-20261005T014624Z", "current"]:
    D = pd.read_csv(os.path.join(ex, run, "d3_shadows.csv"), low_memory=False)
    T = pd.read_csv(os.path.join(ex, run, "trades.csv"), low_memory=False)
    A = pd.read_csv(os.path.join(ex, run, "accounts.csv"))
    kind = dict(zip(A.account_id, A.kind))
    T["bar"] = T.signal_ts + 1
    T["sf"] = (T.entry_price - T.stop_initial).abs()/T.entry_price
    sf = {(r.account_id, r.symbol, int(r.bar)): r.sf for r in T.itertuples()}
    D = D[D.kind.isin(["base","lev10","lev20","lock30","timestop","lock15","lock20"])].copy()
    D["acct"] = D.key.str.split("|").str[1]
    D["bar"] = D.key.str.split("|").str[3].astype("int64")
    D["lev"] = D.data.map(lambda s: json.loads(s).get("leverage") if isinstance(s,str) and s.startswith("{") else np.nan)
    D["sf"] = [sf.get((a,s,b), np.nan) for a,s,b in zip(D.acct, D.symbol, D.bar)]
    D["R"] = D.roe/(D.lev*D.sf)
    D["akind"] = D.acct.map(kind)
    D["run"] = run
    out.append(D)
D = pd.concat(out)
print("rows without sf:", D.sf.isna().sum(), "of", len(D))
base = D[D.kind=="base"][["run","acct","symbol","bar","R","resolved","lev","timeframe","akind","roe"]].rename(columns={"R":"Rb","resolved":"rb","lev":"levb","roe":"roeb"})
res = []
for v in ["lev10","lock30","timestop","lev20"]:
    V = D[D.kind==v][["run","acct","symbol","bar","R","resolved","roe"]].merge(base, on=["run","acct","symbol","bar"])
    V["d"] = V.R - V.Rb
    V["unres"] = (V.resolved==0)
    V = V[V.rb==1]
    pr = V[(V.resolved==1) & V.R.notna() & V.Rb.notna()]
    for (run, ak), g in pr.groupby(["run","akind"]):
        if ak not in ("strategy",): continue
        tot = len(g)
        for tf, h in g.groupby("timeframe"):
            r = cboot(h.d, h.bar//3600_000); r6 = cboot(h.d, h.bar//(6*3600_000))
            res.append(dict(variant=v, run=run, kind=ak, tf=tf, n=len(h), unresolved=int(V[(V.run==run)&(V.akind==ak)&(V.timeframe==tf)].unres.sum()),
                            dR=r["mean"], lo1h=r["lo"], hi1h=r["hi"], lo6h=r6["lo"], hi6h=r6["hi"], G6=r6["G"], lev_base_med=h.levb.median(),
                            share50=(h.levb==50).mean()))
        res.append(dict(variant=v, run=run, kind=ak, tf="ALL", n=tot, dR=g.d.mean()))
    allp = pr[pr.akind=="strategy"]
    res.append(dict(variant=v, run="ALLRUNS", kind="strategy", tf="ALL", n=len(allp), dR=allp.d.mean()))
    # duplicates: same run/symbol/bar/tf/side-equivalent trade counted in several accounts (same base roe)
    dd = allp.drop_duplicates(["run","symbol","bar","timeframe","roeb","roe"])
    res.append(dict(variant=v, run="ALLRUNS_dedup", kind="strategy", tf="ALL", n=len(dd), dR=dd.d.mean()))
R = pd.DataFrame(res)
pd.set_option("display.width", 250)
print(R.round(3).to_string())
R.to_csv("x2_d3_pairs.csv", index=False)
