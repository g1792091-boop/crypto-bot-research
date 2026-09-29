import numpy as np
from common import build_sparse, first_hit, load
rng = np.random.default_rng(1)
df = load("dogeusd", "1h")
h = df.high.values; l = df.low.values; o = df.open.values
n = len(h); cap = 2160
K = int(np.ceil(np.log2(cap + 1)))
mx, mn = build_sparse(h, l, K)
e = rng.integers(0, n - cap, 3000)
tp = rng.choice([0.002, 0.005, 0.02, 0.1, 0.3], len(e)); ds = rng.choice([0.01, 0.045, 0.195, 0.5], len(e))
up = o[e] * (1 + ds); dn = o[e] * (1 - tp)
j = first_hit(mx, mn, e, e + cap, up, dn)
bad = 0
for i in range(len(e)):
    seg = np.where((h[e[i]:e[i]+cap] >= up[i]) | (l[e[i]:e[i]+cap] <= dn[i]))[0]
    jb = e[i] + seg[0] if len(seg) else e[i] + cap
    bad += jb != j[i]
print("mismatches", bad, "of", len(e), "timeouts", int((j == e + cap).sum()))
