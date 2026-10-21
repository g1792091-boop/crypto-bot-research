"""Member signals of the 추세판단 봇 exactly as the live rule bot computes them: at every bar close (boundary) of the
member's timeframe, on the trailing live window of closed 5m bars (core: sigservice.window_5m -> recorder.build_frames
-> lib.compute_signals, last bar; DeepSeek: dssig.ds_job with config.DS_WINDOW_5M and BTC's bars for F14).
This is the 10-21 replay's signals.py (its output is signals.csv.gz here, 5,055 rows; sim.py reads it). It needs 1m bars
from 2026-02 on (DS_WINDOW_5M["1h"] is 125 days): bash download.sh ROOT "02 03 04 05 06 07 08 09"; about an hour on
4 cores. Output: ROOT/out/signals.csv (bar_close, tf, member, symbol, side).
Run: python3 -I signals.py ROOT [--quick N]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import COINS, FIVE, TF_MS, agg, load_1m, np, pd  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from multiprocessing import Pool  # noqa: E402

ROOT = sys.argv[1]
CORE = {"30m": ["N08_ICHI_WR", "N05_PSAR_POC", "N06_MACD_ORB", "S3_CMO_SANDWICH", "N20_EMA9_CHOP"],
        "1h": ["S3_CMO_SANDWICH"]}
DS = {"30m": ["F3_BOS", "F15_ORB"], "1h": ["F9_FVG", "F9_IFVG"]}
START = int(pd.Timestamp("2026-06-28 00:00", tz="UTC").value // 10**6)
END = int(pd.Timestamp("2026-10-21 00:00", tz="UTC").value // 10**6)   # last minute stepped: 10-20 23:59

F5 = {}
LIB = None


def init():
    global LIB
    from paperbot import sweepsig, dssig
    LIB = sweepsig.lib()
    dssig.verify()
    for c in COINS:
        F5[c] = agg(load_1m(ROOT, c), FIVE)


def core_job(coin, tf, boundary):
    from paperbot.recorder import build_frames
    from paperbot.sigservice import window_5m
    lib = LIB
    f = F5[coin]
    n = window_5m(lib, tf)
    end = int(np.searchsorted(f["ts"], boundary))            # 5m bars opening before boundary = closed at/before it
    sl = slice(end - n, end)
    df5 = pd.DataFrame({"ts": pd.to_datetime(f["ts"][sl], unit="ms", utc=True), "open": f["o"][sl], "high": f["h"][sl],
                        "low": f["l"][sl], "close": f["c"][sl], "volume": f["v"][sl]})
    df = build_frames(lib, df5, [tf])[tf]
    if len(df) <= lib.warmup_bars(tf):
        return None, "warm-up"
    last_open = int(df["ts"].iloc[-1].value // 1_000_000)
    if last_open + TF_MS[tf] != boundary:
        return None, "last bar mismatch"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sigs = lib.compute_signals({coin: df}, tf, CORE[tf], strict=False)
    errs = [str(w.message)[:200] for w in caught if str(w.message).split(" ", 1)[0] in lib.NAMES]
    out = {}
    for n_ in CORE[tf]:
        arr = sigs.get(n_, {}).get(coin)
        out[n_] = int(arr[-1]) if arr is not None else 0
    return out, ";".join(errs)


def ds_job_(coin, tf, boundary):
    from paperbot import dssig
    from paperbot.config import DS_WINDOW_5M
    f, b = F5[coin], F5["BTCUSDT"]
    n = DS_WINDOW_5M[tf]
    per = TF_MS[tf] // FIVE
    end = int(np.searchsorted(f["ts"], boundary))
    sl = slice(end - n, end)
    btc = None
    if coin != "BTCUSDT":
        bn = min(n, (dssig.BTC_TF_BARS + 2) * per)
        bend = int(np.searchsorted(b["ts"], boundary))
        bs = slice(bend - bn, bend)
        btc = (b["ts"][bs], b["o"][bs], b["h"][bs], b["l"][bs], b["c"][bs], b["v"][bs])
    r = dssig.ds_job((coin, tf, boundary, f["ts"][sl], f["o"][sl], f["h"][sl], f["l"][sl], f["c"][sl], f["v"][sl], btc))
    if not r.get("ready"):
        return None, r.get("why", "")
    sides = r.get("sides") or {}
    return {d: int(sides.get(d, 0)) for d in DS[tf]}, ";".join(r.get("errors") or [])


def work(task):
    coin, tf, kind, bounds = task
    rows, notes = [], []
    t0 = time.time()
    for bd in bounds:
        try:
            res, why = (core_job if kind == "core" else ds_job_)(coin, tf, int(bd))
        except Exception as exc:  # noqa: BLE001
            res, why = None, f"{type(exc).__name__}: {exc}"
        if res is None:
            notes.append((int(bd), why))
            continue
        if why:
            notes.append((int(bd), why))
        for name, side in res.items():
            if side:
                rows.append((int(bd), tf, name, coin, int(side)))
    return coin, tf, kind, rows, notes, time.time() - t0, len(bounds)


def main():
    quick = int(sys.argv[sys.argv.index("--quick") + 1]) if "--quick" in sys.argv else 0
    init()
    tasks = []
    for tf in ("30m", "1h"):
        ms = TF_MS[tf]
        bounds = np.arange(START + ms, END + 1, ms, dtype=np.int64)       # bar closes
        if quick:
            bounds = bounds[:quick]
        for kind in ("core", "ds"):
            for coin in COINS:
                for chunk in np.array_split(bounds, max(1, len(bounds) // 240)):
                    tasks.append((coin, tf, kind, chunk))
    print(f"{len(tasks)} tasks", flush=True)
    rows, notes = [], []
    t0 = time.time()
    with Pool(4) as pool:
        for k, (coin, tf, kind, r, nt, dt, nb) in enumerate(pool.imap_unordered(work, tasks), 1):
            rows += r
            notes += [(coin, tf, kind, b, w) for b, w in nt]
            if k % 10 == 0 or quick:
                print(f"{k}/{len(tasks)} {coin} {tf} {kind} {nb} bars {dt:.1f}s elapsed {time.time() - t0:.0f}s", flush=True)
    out = pd.DataFrame(rows, columns=["bar_close", "tf", "member", "symbol", "side"]).sort_values(
        ["bar_close", "tf", "member", "symbol"])
    name = "signals_quick.csv" if quick else "signals.csv"
    os.makedirs(f"{ROOT}/out", exist_ok=True)
    out.to_csv(f"{ROOT}/out/{name}", index=False)
    pd.DataFrame(notes, columns=["symbol", "tf", "kind", "bar_close", "note"]).to_csv(
        f"{ROOT}/out/{name.replace('.csv', '_notes.csv')}", index=False)
    print("signals", len(out), "notes", len(notes), "elapsed", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
