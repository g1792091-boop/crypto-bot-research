# Read-only: VWAP 30m x judge (round 8) - confirm R of the select-best judges, and friend-style judges. Writes nothing.
import os, sys, json
import numpy as np
CODE = "/home/user/crypto-bot-research/research/vwap30/code"
sys.path.insert(0, CODE)
import vwgate as G
OUT8 = G.OUT8
lab = G.VWAP30
a = np.load(os.path.join(OUT8, "scan", f"{lab}.npz"))["out"].astype(float)
b = np.load(os.path.join(OUT8, "cscan", f"{lab}.npz"))["out"].astype(float)
LABELS = sorted(f[:-4] for f in os.listdir(os.path.join(OUT8, "cscan")) if f.endswith(".npz"))
GATES = ([f"L|{l}|{a}" for l in LABELS for a in G.AGES] + [f"J|{t}|{n}" for t in G.JTF for n in G.JNM]
         + [f"I|{w}|{t}|{i}" for w in ("own", "BTC") for t in G.ITF for i in G.IND])
gates = GATES + ["none"]
print(a.shape, b.shape, len(gates))
def R(x):
    n = x[..., 0] + x[..., 1]
    with np.errstate(all="ignore"):
        return (x[..., 2] + x[..., 3]) / n, n
rs, ns = R(a); rc, nc = R(b)
sel = json.load(open(os.path.join(OUT8, "select8.json")))
for r in sel["vwap_best_gates"][:12]:
    gi = gates.index(r["gate"]); j = r["exit"]
    print(f'{r["gate"]:<60} ex{j:2d} sel n{int(ns[gi,j]):5d} R{rs[gi,j]:+.3f} | conf n{int(nc[gi,j]):4d} R{rc[gi,j]:+.3f}  (2025 R {b[gi,j,2]/max(b[gi,j,0],1):+.3f}, 2026 R {b[gi,j,3]/max(b[gi,j,1],1):+.3f})')
print("--- friend/trend-type judges on VWAP 30m (best select exit per judge; confirm R)")
for g in [x for x in gates if any(k in x for k in ("FRIEND3", "|OBV", "RSI26", "MOM", "J|"))][:60]:
    gi = gates.index(g)
    j = int(np.nanargmax(np.where(ns[gi] >= 300, rs[gi], -9)))
    print(f'{g:<40} ex{j:2d} sel n{int(ns[gi,j]):5d} R{rs[gi,j]:+.3f} | conf n{int(nc[gi,j]):4d} R{rc[gi,j]:+.3f} | none same exit conf R{rc[-1,j]:+.3f}')
