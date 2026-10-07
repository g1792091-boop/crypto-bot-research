import numpy as np
rng = np.random.default_rng(7)

def ctest(d, cl, B=4000):
    d = np.asarray(d, float); cl = np.asarray(cl)
    u, inv = np.unique(cl, return_inverse=True)
    s = np.bincount(inv, d); n = len(d); obs = d.mean()
    flips = rng.choice([-1, 1], size=(B, len(u)))
    p2 = (np.abs(flips @ s / n) >= abs(obs) - 1e-12).mean()
    bs = [s[ix].sum() / np.bincount(inv, minlength=len(u))[ix].sum()
          for ix in (rng.integers(0, len(u), len(u)) for _ in range(2000))]
    return obs, np.percentile(bs, 2.5), np.percentile(bs, 97.5), p2, len(u)


