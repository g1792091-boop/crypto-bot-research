"""5y DS signal npz for a few definitions (same construction as parity_ds.py, which matched fyds pickles exactly at 4h).
    python3 -I -B ds5y_sig.py <binance_bars_dir> <out_dir> <names,comma>
"""
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa
import pandas as pd  # noqa
import repl_sig as G  # noqa

bars, out, names = sys.argv[1], sys.argv[2], set(sys.argv[3].split(","))
os.makedirs(out, exist_ok=True)
E = G.C.env()
L, fg = E["L"], E["fg"]
for tf in ("15m", "30m", "1h", "4h"):
    def read(coin):
        df = L.read_ohlcv(os.path.join(bars, f"{coin.lower()}-{tf}.csv.gz"))
        df = df[df["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
        df.attrs["tf"] = tf
        return df
    btc = read("BTCUSD")
    for coin in G.COINS:
        df = read(coin)
        sig = G.C.entries(df, tf, None if coin == "BTCUSD" else {"BTCUSD": btc}, coin)
        arrs = dict(ts=G.FS.RB._ns(df["ts"]), o=df["open"].to_numpy(float), h=df["high"].to_numpy(float),
                    l=df["low"].to_numpy(float), c=df["close"].to_numpy(float), atr=fg.atr(df, 14).to_numpy(float))
        for name, (lg, sh) in sig.items():
            if name in names:
                arrs["s__" + name] = np.where(lg, 1, np.where(sh, -1, 0)).astype(np.int8)
        np.savez_compressed(os.path.join(out, f"sig_{tf}_{coin}.npz"), **arrs)
        print(tf, coin, len(df), flush=True)
