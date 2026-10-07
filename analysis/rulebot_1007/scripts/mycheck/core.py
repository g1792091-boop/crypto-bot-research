import csv, sys, collections, math, statistics as st
D = sys.argv[1]
RUNS = {"v3a": "run-20261005T014624Z", "v3b": "run-20261005T183457Z", "v4": "current"}
rows = []
for tag, r in RUNS.items():
    kind = {a["account_id"]: a["kind"] for a in csv.DictReader(open(f"{D}/{r}/accounts.csv"))}
    for t in csv.DictReader(open(f"{D}/{r}/trades.csv")):
        e = float(t["entry_price"]); si = t["stop_initial"] or t["stop_price"]
        risk = float(t["qty"]) * abs(e - float(si))
        R = float(t["pnl"]) / risk if risk > 0 else float("nan")
        rows.append(dict(run=tag, acc=t["account_id"], kind=kind.get(t["account_id"], "?"), strat=t["strategy_id"],
                         tf=t["timeframe"], R=R, pnl=float(t["pnl"]), side=int(t["side"]), sym=t["symbol"],
                         ex=t["exit_reason"], lev=int(t["leverage"]), fees=float(t["fees"]),
                         stopfrac=abs(e - float(si)) / e))
import pickle; pickle.dump(rows, open(sys.argv[2], "wb"))
def agg(g):
    Rs = [x["R"] for x in g]; w = [r for r in Rs if r > 0]; l = [r for r in Rs if r <= 0]
    return dict(n=len(Rs), win=len(w)/len(Rs), meanR=st.mean(Rs), sumR=sum(Rs),
                pf=(sum(w)/-sum(l)) if l and sum(l) < 0 else float("inf"),
                aw=st.mean(w) if w else 0, al=st.mean(l) if l else 0, pnl=sum(x["pnl"] for x in g))
print("== by run x kind x tf (mean R per trade)")
g = collections.defaultdict(list)
for x in rows: g[(x["run"], x["kind"], x["tf"])].append(x)
for k in sorted(g):
    a = agg(g[k]); print(f"{k[0]:4} {k[1]:8} {k[2]:4} n={a['n']:5} win={a['win']:.0%} meanR={a['meanR']:+.3f} avgW={a['aw']:+.2f} avgL={a['al']:+.2f} PF={a['pf']:.2f} pnl={a['pnl']:+.0f}")
print("== stop distance (% of price) and cost share by tf: median stopfrac, fees/risk")
g2 = collections.defaultdict(list)
for x in rows: g2[x["tf"]].append(x)
for k in sorted(g2):
    sf = [x["stopfrac"] for x in g2[k]]
    print(k, f"median stop {st.median(sf)*100:.2f}%  roundtrip cost/stop ~{0.0014/st.median(sf):.0%}")
