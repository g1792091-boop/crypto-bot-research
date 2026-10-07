"""DS house-exit check: my ATR14 + my simulator on the DS signal list; optional regeneration of signals with lib_c.
python3 -I -B run_ds.py <bars_dir> <their_out_dir> <tf> <out_csv> [regen_coin]"""
import importlib.util
import os
import sys
import time
import warnings

sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import mysim  # noqa: E402

bars_dir, their, tf, out = sys.argv[1:5]
regen = sys.argv[5] if len(sys.argv) > 5 else None
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
T = pd.read_pickle(os.path.join(their, f"fyds_{tf}.pkl.gz"))
for c in ("strategy", "coin"):
    T[c] = T[c].astype(str)
rows = []
t0 = time.time()
BARS = {}
for coin in COINS:
    df = pd.read_csv(os.path.join(bars_dir, f"{coin.lower()}-{tf}.csv.gz"))
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df[df["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
    BARS[coin] = df
    ts = df["ts"].dt.tz_localize(None).astype("datetime64[ns]").astype(np.int64).to_numpy()
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().to_numpy()
    pos = {int(t): i for i, t in enumerate(ts)}
    g = T[T["coin"] == coin]
    cache = {}
    for st, t_, side in zip(g["strategy"].to_numpy(), g["ts"].to_numpy(), g["side"].to_numpy()):
        i = pos.get(int(t_))
        if i is None or i + 1 >= len(o):
            continue
        side = int(side)
        raw, a = o[i + 1], atr[i]
        k = (side, round(a / raw, 7))
        if k not in cache:
            cache[k] = mysim.lev_for(side, raw, a)
        lev, liq = cache[k]
        fill = raw * (1 + side * mysim.SLIP)
        sf = abs(fill - (raw - side * 2 * a)) / fill
        if lev == 0:
            rows.append((st, coin, int(t_), side, 0, np.nan, np.nan, sf))
            continue
        lev, liq = mysim.lev_for(side, raw, a)
        r = mysim.sim_one(o, h, l, c, i, side, a, lev, liq, tf)
        if r is None:
            continue
        rows.append((st, coin, int(t_), side, lev, r[0], r[1], sf))
    print(coin, len(rows), f"{time.time()-t0:.0f}s", flush=True)
D = pd.DataFrame(rows, columns=["strategy", "coin", "ts", "side", "lev", "ret", "gross", "stop_frac"])
D["R"], D["gR"], D["tf"] = D["ret"] / D["stop_frac"], D["gross"] / D["stop_frac"], tf
D.to_csv(out, index=False)
M = D.merge(T[["strategy", "coin", "ts", "v4n_lev", "v4n_R", "v4n_gross", "stop_frac", "v4n_done"]], on=["strategy", "coin", "ts"],
            suffixes=("", "_t"))
ok = (M["lev"] > 0) & M["v4n_done"].astype(bool) & (M["v4n_lev"] > 0)
print("rows", len(D), "lev agree", float((M["lev"] == M["v4n_lev"]).mean()), "stop_frac rel diff p99",
      float((M["stop_frac"] / M["stop_frac_t"] - 1).abs().quantile(0.99)))
d = (M.loc[ok, "R"] - M.loc[ok, "v4n_R"]).abs()
print("R |diff| median", d.median(), "p99", d.quantile(0.99), "share>0.01", float((d > 0.01).mean()))
print("my mean R", D.loc[D.lev > 0, "R"].mean(), "gross", D.loc[D.lev > 0, "gR"].mean(), "theirs",
      T.loc[(T.v4n_lev > 0) & T.v4n_done.astype(bool), "v4n_R"].mean(), "sized share", float((D.lev > 0).mean()))
if regen:
    REPO = '/home/user/crypto-bot-research'
    spec = importlib.util.spec_from_file_location('lib_c_ro', os.path.join(REPO, 'research', 'deepseek200', 'lib_c.py'))
    C = importlib.util.module_from_spec(spec)
    sys.modules['lib_c_ro'] = C
    spec.loader.exec_module(C)
    E = C.env()
    L = E["L"]
    df = L.read_ohlcv(os.path.join(bars_dir, f"{regen.lower()}-{tf}.csv.gz"))
    df = df[df["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
    df.attrs["tf"] = tf
    btc = L.read_ohlcv(os.path.join(bars_dir, f"btcusd-{tf}.csv.gz"))
    btc = btc[btc["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
    btc.attrs["tf"] = tf
    sig = C.entries(df, tf, None if regen == "BTCUSD" else {"BTCUSD": btc}, regen)
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).astype("datetime64[ns]").astype(np.int64).to_numpy()
    S0 = pd.Timestamp("2021-08-01").value
    mine = set()
    for name, (lg, sh) in sig.items():
        s = np.where(lg, 1, np.where(sh, -1, 0))
        for i in np.nonzero(s)[0]:
            if ts[i] >= S0 and i + 1 < len(ts) - 1:
                mine.add((name, int(ts[i]), int(s[i])))
    th = set(zip(T.loc[T.coin == regen, "strategy"], T.loc[T.coin == regen, "ts"].astype(np.int64), T.loc[T.coin == regen, "side"].astype(int)))
    print("regen", regen, tf, "mine", len(mine), "theirs", len(th), "both", len(mine & th), "only mine", len(mine - th), "only theirs", len(th - mine))
