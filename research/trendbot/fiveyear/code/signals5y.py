"""Member signals of the trend bot over the whole history, computed ONCE per coin and timeframe on the full series with
the rule bot's own library functions (core: recorder.build_frames -> sweep_lib.compute_signals; DeepSeek: dssig.frame ->
dssig.entries_frame with BTC's frame), instead of the live bot's trailing 5m windows (those would take ~70 CPU-hours,
~35 h on the 2 processes allowed here). The agreement with the trailing-window signals of the earlier replay is measured by compare_signals.py.
Output: out/signals5y.csv (bar_close, tf, member, symbol, side) for bar closes 2020-.. 2026-10-21.
Run: python3 -I signals5y.py [--procs 2] [--coins BTCUSDT,...]"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fycommon import *
import time, warnings
from multiprocessing import Pool

CORE = {"30m": ["N08_ICHI_WR", "N05_PSAR_POC", "N06_MACD_ORB", "S3_CMO_SANDWICH", "N20_EMA9_CHOP"],
        "1h": ["S3_CMO_SANDWICH"]}
DS = {"30m": ["F3_BOS", "F15_ORB"], "1h": ["F9_FVG", "F9_IFVG"]}


def five(coin):
    m = load_grid(coin, with_oct=True)
    return agg(m, FIVE)


def job(coin):
    from paperbot import sweepsig, dssig
    from paperbot.recorder import build_frames
    lib = sweepsig.lib()
    dssig.verify()
    t0 = time.time()
    f = five(coin)
    bf = f if coin == "BTCUSDT" else five("BTCUSDT")
    rows, log = [], []
    for tf in ("30m", "1h"):
        t1 = time.time()
        df = build_frames(lib, df_of(f), [tf])[tf]
        close = (df["ts"].astype("int64") // 1_000_000).to_numpy() + TF_MS[tf]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sigs = lib.compute_signals({coin: df}, tf, CORE[tf], strict=False)
        for n in CORE[tf]:
            a = sigs[n][coin]
            for k in np.flatnonzero(a):
                rows.append((int(close[k]), tf, n, coin, int(a[k])))
        t2 = time.time()
        bdf = dssig.frame(bf["ts"], bf["o"], bf["h"], bf["l"], bf["c"], bf["v"], tf=tf, lib=lib)
        dfd = dssig.frame(f["ts"], f["o"], f["h"], f["l"], f["c"], f["v"], tf=tf, lib=lib)
        closed = (dfd["ts"].astype("int64") // 1_000_000).to_numpy() + TF_MS[tf]
        R, notes = dssig.entries_frame(dfd, tf, dssig.coin_key(coin), None if coin == "BTCUSDT" else bdf)
        for d in DS[tf]:
            lg, sh = R[d]
            for k in np.flatnonzero(lg):
                rows.append((int(closed[k]), tf, d, coin, 1))
            for k in np.flatnonzero(sh & ~lg):
                rows.append((int(closed[k]), tf, d, coin, -1))
        log.append(f"{coin} {tf}: core {t2 - t1:.0f}s ds {time.time() - t2:.0f}s bars {len(df)}")
    return coin, rows, log, time.time() - t0


def main():
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 2
    coins = sys.argv[sys.argv.index("--coins") + 1].split(",") if "--coins" in sys.argv else COINS
    rows = []
    with Pool(procs) as pool:
        for coin, r, log, dt in pool.imap_unordered(job, coins):
            rows += r
            print("\n".join(log), f"| {coin} done {dt:.0f}s, {len(r)} signals", flush=True)
    out = pd.DataFrame(rows, columns=["bar_close", "tf", "member", "symbol", "side"]).sort_values(
        ["bar_close", "tf", "member", "symbol"])
    name = "signals5y.csv" if coins == COINS else f"signals5y_{'_'.join(coins)}.csv"
    out.to_csv(f"{OUT}/{name}", index=False)
    print(out.groupby(["tf", "member", "side"]).size().to_string())


if __name__ == "__main__":
    main()
