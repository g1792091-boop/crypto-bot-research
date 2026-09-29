"""Fast re-implementation of fg_indicators.rolling_volume_profile_poc(full_series=True).
Same edges / searchsorted / even-split logic, evaluated per window with numpy."""
import numpy as np
import pandas as pd


def poc_series(df: pd.DataFrame, lookback: int = 100, bins: int = 32) -> np.ndarray:
    lookback = max(10, int(lookback)); bins = max(8, int(bins))
    lo = df["low"].to_numpy(float); hi = df["high"].to_numpy(float)
    cl = df["close"].to_numpy(float); vo = np.maximum(0.0, df["volume"].to_numpy(float))
    n = len(lo)
    out = np.full(n, np.nan)
    wl = pd.Series(lo).rolling(lookback).min().to_numpy()
    wh = pd.Series(hi).rolling(lookback).max().to_numpy()
    for i in range(lookback - 1, n):
        L, H = wl[i], wh[i]
        if not (np.isfinite(L) and np.isfinite(H)) or H <= L:
            continue
        edges = np.linspace(L, H, bins + 1)
        s = slice(i - lookback + 1, i + 1)
        rl, rh, rc, v = lo[s], hi[s], cl[s], vo[s]
        flat = rh <= rl
        left = np.clip(np.searchsorted(edges, rl, side="right") - 1, 0, None)
        right = np.minimum(bins - 1, np.searchsorted(edges, rh, side="left"))
        cnt = np.maximum(1, right - left + 1)
        prof = np.zeros(bins + 1)
        # difference-array accumulation of volume/count over [left, right]
        w = np.where(flat, 0.0, v / cnt)
        np.add.at(prof, left, w)
        np.add.at(prof, right + 1, -w)
        prof = np.cumsum(prof)[:bins]
        if flat.any():
            fi = np.clip(np.searchsorted(edges, rc[flat], side="right") - 1, 0, bins - 1)
            np.add.at(prof, fi, v[flat])
        k = int(np.argmax(prof))
        out[i] = (edges[k] + edges[k + 1]) / 2.0
    return out


if __name__ == "__main__":
    import sys, os, time
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bt"))
    import fg_indicators as fg
    from run import load_csv
    D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    for sym in ("btcusd", "bchusd"):
        df = load_csv(os.path.join(D, f"{sym}-15m-ohlcv.csv"), 15).iloc[5000:8000].reset_index(drop=True)
        t0 = time.time(); ref = fg.rolling_volume_profile_poc(df, 100, 32, full_series=True).to_numpy(); t1 = time.time()
        mine = poc_series(df, 100, 32); t2 = time.time()
        m = np.isfinite(ref)
        print(sym, "windows", m.sum(), "nan-pattern equal", np.array_equal(np.isfinite(ref), np.isfinite(mine)),
              "max abs diff", np.nanmax(np.abs(ref[m] - mine[m])), "exact equal", int((ref[m] == mine[m]).sum()),
              f"orig {t1-t0:.1f}s fast {t2-t1:.2f}s")
