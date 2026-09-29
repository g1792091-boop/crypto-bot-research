"""Parity test: fg_fast numpy ports must equal the original FINGRAD implementations."""
import time

import numpy as np
import pandas as pd

import fg_fast
import fg_indicators as fg


def synth(n=3000, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.002, n)))
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.0005, n))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    vol = rng.uniform(1, 100, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol,
                         "open_time": np.arange(n) * 900000})


def same(a, b, name):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.allclose(np.nan_to_num(a, nan=-1e9), np.nan_to_num(b, nan=-1e9), rtol=1e-9, atol=1e-9)
    print(f"{name:14s} {'OK' if ok else 'MISMATCH'}")
    assert ok, name


df = synth()
t = time.time(); l1, d1, u1, lo1 = fg.supertrend(df, 10, 6.0); t1 = time.time() - t
t = time.time(); l2, d2, u2, lo2 = fg_fast.supertrend(df, 10, 6.0); t2 = time.time() - t
print(f"supertrend orig {t1:.2f}s fast {t2:.3f}s")
same(l1, l2, "st line"); same(d1, d2, "st dir"); same(u1, u2, "st upper"); same(lo1, lo2, "st lower")

t = time.time(); p1, pd1 = fg.parabolic_sar(df); t1 = time.time() - t
t = time.time(); p2, pd2 = fg_fast.parabolic_sar(df); t2 = time.time() - t
print(f"psar orig {t1:.2f}s fast {t2:.3f}s")
same(p1, p2, "psar"); same(pd1, pd2, "psar dir")

t = time.time(); h1 = fg.heikin_ashi(df); t1 = time.time() - t
t = time.time(); h2 = fg_fast.heikin_ashi(df); t2 = time.time() - t
print(f"heikin orig {t1:.2f}s fast {t2:.3f}s")
for c in ["ha_open", "ha_close", "ha_high", "ha_low"]:
    same(h1[c], h2[c], c)

t = time.time(); a1, b1 = fg.aroon(df, 25); t1 = time.time() - t
t = time.time(); a2, b2 = fg_fast.aroon(df, 25); t2 = time.time() - t
print(f"aroon orig {t1:.2f}s fast {t2:.3f}s")
same(a1, a2, "aroon up"); same(b1, b2, "aroon down")

t = time.time(); c1 = fg.cci(df, 20); t1 = time.time() - t
t = time.time(); c2 = fg_fast.cci(df, 20); t2 = time.time() - t
print(f"cci orig {t1:.2f}s fast {t2:.3f}s")
same(c1, c2, "cci")
print("ALL PARITY OK")
