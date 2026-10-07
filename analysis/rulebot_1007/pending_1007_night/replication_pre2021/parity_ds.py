"""DS path parity: build a 5y DS signal npz the way repl_sig does (lib_c.entries, long wins) from the Binance bars,
run repl_sim.job on it and compare with the verified fyds_<tf>.pkl.gz.
    python3 -I -B parity_ds.py <binance_bars_dir> <lens_out_dir> <tf> <tmp_dir>
"""
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa
import pandas as pd  # noqa
import repl_sig as G  # noqa
import repl_sim as S  # noqa

bars, lens, tf, tmp = sys.argv[1:5]
os.makedirs(tmp, exist_ok=True)
E = G.C.env()
L, fg = E["L"], E["fg"]


def read(coin):
    df = L.read_ohlcv(os.path.join(bars, f"{coin.lower()}-{tf}.csv.gz"))
    df = df[df["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
    df.attrs["tf"] = tf
    return df


T = pd.read_pickle(os.path.join(lens, f"fyds_{tf}.pkl.gz"))
btc = read("BTCUSD")
for coin in S.COINS:
    df = read(coin)
    sig = G.C.entries(df, tf, None if coin == "BTCUSD" else {"BTCUSD": btc}, coin)
    arrs = dict(ts=G.FS.RB._ns(df["ts"]), o=df["open"].to_numpy(float), h=df["high"].to_numpy(float),
                l=df["low"].to_numpy(float), c=df["close"].to_numpy(float), atr=fg.atr(df, 14).to_numpy(float))
    for name, (lg, sh) in sig.items():
        arrs["s__" + name] = np.where(lg, 1, np.where(sh, -1, 0)).astype(np.int8)
    np.savez_compressed(os.path.join(tmp, f"sig_{tf}_{coin}.npz"), **arrs)
    _, _, d, _ = S.job((tmp, "ds", tf, coin, "2021-08-01", "2026-09-30", 0))
    t = T[T.coin == coin]
    m = d.merge(t, on=["strategy", "ts", "side"], how="outer", suffixes=("", "_t"), indicator=True)
    both = m[m._merge == "both"]
    ok = both.v4n_R.notna() & both.v4n_R_t.notna()
    print(dict(coin=coin, mine=len(d), theirs=len(t), both=len(both), lev_agree=float((both.v4n_lev == both.v4n_lev_t).mean()),
               maxdR=float(np.abs(both.v4n_R - both.v4n_R_t)[ok].max()),
               maxdG=float(np.nanmax(np.abs(both.v4n_gross - both.v4n_gross_t)))), flush=True)
    os.remove(os.path.join(tmp, f"sig_{tf}_{coin}.npz"))
