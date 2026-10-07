import pickle, sys, collections, statistics as st
rows = pickle.load(open(sys.argv[1], "rb"))
g = collections.defaultdict(lambda: collections.defaultdict(list))
for x in rows:
    if x["kind"] in ("strategy", "ds200"):
        g[(x["kind"], x["strat"], x["tf"])][x["run"]].append(x["R"])
out = []
for k, byrun in g.items():
    allR = [r for v in byrun.values() for r in v]
    cells = {run: (len(v), st.mean(v)) for run, v in byrun.items()}
    pos_runs = sum(1 for n, m in cells.values() if m > 0)
    out.append((k, len(allR), st.mean(allR), sum(allR), cells, pos_runs, len(cells)))
tf = sys.argv[2]
sel = [o for o in out if o[0][2] == tf]
sel.sort(key=lambda o: -o[2])
for k, n, m, s, cells, pr, nr in sel:
    c = "  ".join(f"{run}:{cells[run][0]:>2}/{cells[run][1]:+.2f}" if run in cells else f"{run}:  -   " for run in ("v3a", "v3b", "v4"))
    print(f"{k[0][:3]} {k[1]:18} n={n:3} meanR={m:+.3f} sumR={s:+6.2f} pos={pr}/{nr}  {c}")
