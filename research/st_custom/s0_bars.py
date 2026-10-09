"""Stage 0: bars. 15m per coin 2020-01 .. 2026-09-29 (pre2021 cache before 2021-01-01, the binance cache from
2021-01-01; XRP from the raw Binance zips), 30m from 15m (complete 2-bar groups aligned to UTC), 4h from 15m (bins
partial from data gaps kept, the last bin only if complete). Bars without trades (volume 0) are dropped as in
research/binance_data/build.py (an exchange halt is a real gap). 5m (INTRABAR, addendum 1) with `5m`.

    python3 -B research/st_custom/s0_bars.py [5m]
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

PRE = os.path.join(C.REPO, "data", "pre2021")
BIN = os.path.join(C.SCR, "binance", "bars")
XRP_RAW = {"15m": os.path.join(C.SCR, "xrp_raw"), "5m": os.path.join(C.SCR, "xrp_raw5m")}
SPLIT = pd.Timestamp("2021-01-01", tz="UTC")
END = pd.Timestamp("2026-09-30", tz="UTC")


def read_csv(path):
    d = pd.read_csv(path, float_precision="round_trip")
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    return d[["ts", "open", "high", "low", "close", "volume"]]


def read_kline_zip(path):
    """Copy of research/binance_data/build.read_kline_zip: header line or not; open time in ms or us."""
    with zipfile.ZipFile(path) as z:
        frames = []
        for n in [n for n in z.namelist() if n.lower().endswith(".csv")]:
            data = z.read(n)
            header = 0 if data[:1].isalpha() else None
            d = pd.read_csv(io.BytesIO(data), header=header, usecols=range(6), float_precision="round_trip")
            d.columns = ["t", "open", "high", "low", "close", "volume"]
            t = d["t"].to_numpy(np.int64)
            t = np.where(t >= 10 ** 14, t // 1000, t)
            out = pd.DataFrame({"ts": pd.to_datetime(t, unit="ms", utc=True)})
            for k in ("open", "high", "low", "close", "volume"):
                out[k] = d[k].to_numpy(float)
            frames.append(out)
    return pd.concat(frames, ignore_index=True)


def clean(d):
    d = d.sort_values("ts", kind="mergesort").drop_duplicates("ts", keep="last")
    d = d[(d["volume"] > 0) & (d["ts"] < END)]
    return d.reset_index(drop=True)


def xrp_series(tf):
    files = sorted(f for f in os.listdir(XRP_RAW[tf]) if f.endswith(".zip"))
    # monthly first, daily files win on a repeated open time (as build.py's gap fill)
    monthly = [f for f in files if f.count("-") == 3]
    daily = [f for f in files if f.count("-") == 4]
    parts = [read_kline_zip(os.path.join(XRP_RAW[tf], f)) for f in monthly + daily]
    return pd.concat(parts, ignore_index=True), dict(monthly=len(monthly), daily=len(daily))


def merged(coin, tf):
    name = f"{coin.lower()}-{tf}.csv.gz"
    pre = clean(read_csv(os.path.join(PRE, name)))
    info = {"pre_rows": len(pre)}
    if coin == "XRPUSD" and tf == "15m":
        new, inf = xrp_series(tf)
        info.update(inf)
        new = clean(new)
    elif coin == "XRPUSD" and tf == "5m":
        new, inf = xrp_series(tf)
        info.update(inf)
        new = clean(new)
    else:
        new = clean(read_csv(os.path.join(BIN, name)))
    # overlap check (2021-01 .. 2021-08: both sources are Binance USD-M futures klines)
    ov = pre[pre["ts"] >= SPLIT].merge(new, on="ts", suffixes=("_a", "_b"))
    if len(ov):
        rel = max(float(np.max(np.abs(ov[f"{k}_a"] / ov[f"{k}_b"] - 1))) for k in ("open", "high", "low", "close"))
        info.update(overlap_rows=len(ov), overlap_max_rel_ohlc=rel,
                    overlap_pre_only=int((~pre[pre["ts"] >= SPLIT]["ts"].isin(new["ts"])).sum()),
                    overlap_new_only=int((~new[new["ts"] < pre["ts"].max()]["ts"].isin(pre["ts"])).sum()))
    if coin == "XRPUSD" and new["ts"].min() < SPLIT:
        # the raw XRP files start in 2020: use them for the whole range; the pre2021 file is the cross-check
        out = new
        info["source"] = "xrp raw zips (whole range); pre2021 used as a check"
    else:
        out = pd.concat([pre[pre["ts"] < SPLIT], new[new["ts"] >= SPLIT]], ignore_index=True)
        info["source"] = "pre2021 < 2021-01-01 <= binance cache"
    out = clean(out)
    info.update(rows=len(out), first=str(out["ts"].iloc[0]), last=str(out["ts"].iloc[-1]))
    return out, info


def to_arrays(d):
    return dict(ts=d["ts"].astype("int64").to_numpy() if d["ts"].dtype != np.int64 else d["ts"].to_numpy(),
                o=d["open"].to_numpy(float), h=d["high"].to_numpy(float), l=d["low"].to_numpy(float),
                c=d["close"].to_numpy(float), v=d["volume"].to_numpy(float))


def ns(d):
    return d["ts"].to_numpy().astype("datetime64[ns]").astype(np.int64)


def agg(b15, minutes, complete):
    """Group 15m (or 5m) bars into UTC-aligned bins of `minutes`; complete=True keeps only full bins."""
    ts = b15["ts"]
    step = minutes * C.NS_MIN
    key = ts // step
    brk = np.flatnonzero(np.diff(key)) + 1
    st = np.r_[0, brk]
    en = np.r_[brk, len(ts)]
    base = int(np.median(np.diff(ts[:1000])))
    cnt = en - st
    need = step // base
    out = dict(ts=key[st] * step, o=b15["o"][st], h=np.maximum.reduceat(b15["h"], st),
               l=np.minimum.reduceat(b15["l"], st), c=b15["c"][en - 1], v=np.add.reduceat(b15["v"], st))
    if complete:
        keep = cnt == need
    else:
        keep = np.ones(len(st), bool)
        keep[-1] = cnt[-1] == need
    return {k: v[keep] for k, v in out.items()}, int((~keep).sum())


def main(which="15m"):
    meta = {}
    if which == "15m":
        for coin in C.COINS:
            d, info = merged(coin, "15m")
            b = dict(ts=ns(d), o=d["open"].to_numpy(float), h=d["high"].to_numpy(float), l=d["low"].to_numpy(float),
                     c=d["close"].to_numpy(float), v=d["volume"].to_numpy(float))
            C.save_npz(C.bars_path(coin, "15m"), **b)
            b30, drop30 = agg(b, 30, True)
            C.save_npz(C.bars_path(coin, "30m"), **b30)
            b4, drop4 = agg(b, 240, False)
            C.save_npz(C.bars_path(coin, "4h"), **b4)
            gaps = np.diff(b["ts"]) // (15 * C.NS_MIN)
            info.update(bars30=len(b30["ts"]), dropped_incomplete_30m=drop30, bars4h=len(b4["ts"]),
                        gaps_15m=int((gaps > 1).sum()), missing_15m=int((gaps[gaps > 1] - 1).sum()))
            meta[coin] = info
            C.log(coin, info)
        C.save_json(os.path.join(C.WORK, "bars_meta.json"), meta)
        C.save_json(os.path.join(C.OUT, "bars_meta.json"), meta)
    else:
        for coin in C.COINS:
            d, info = merged(coin, "5m")
            b = dict(ts=ns(d), o=d["open"].to_numpy(float), h=d["high"].to_numpy(float), l=d["low"].to_numpy(float),
                     c=d["close"].to_numpy(float), v=d["volume"].to_numpy(float))
            C.save_npz(C.bars_path(coin, "5m"), **b)
            meta[coin] = info
            C.log(coin, info)
        C.save_json(os.path.join(C.OUT, "bars_meta_5m.json"), meta)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "15m")
