#!/usr/bin/env python3
"""Second pass: fill whole-day holes in the monthly archives from Binance daily archives.

- kline holes: any day touched by a gap > 1h between consecutive 5m bars -> daily klines/5m file
- mark holes: any day (up to the last bar with volume) with >= 12 bars lacking mark price -> daily markPriceKlines/5m file
Only inserts bars whose ts is absent (klines) or fills NaN mark values; never overwrites monthly data.
Also adds coverage fields about the period after real trading stopped. No trading outcomes computed.
"""
import json, os, sys, time
import numpy as np
import pandas as pd

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
import c30 as C  # noqa: E402

DAY = 86_400_000
STEP = 300_000


def dstr(d):
    return time.strftime("%Y-%m-%d", time.gmtime(d * DAY / 1000))


def ym(t):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t / 1000))


def fetch_days(sym, kind, days):
    """kind 'klines' or 'markPriceKlines'. Returns (DataFrame or None, {day: status})."""
    from concurrent.futures import ThreadPoolExecutor
    stat, frames = {}, []

    def one(d):
        ds = dstr(d)
        key = f"data/futures/um/daily/{kind}/{sym}/5m/{sym}-5m-{ds}.zip"
        dest = os.path.join(C.RAW, sym, "daily_" + kind, f"{sym}-5m-{ds}.zip")
        return d, dest, C.fetch_verified(key, dest, True)

    with ThreadPoolExecutor(C.NTHREADS) as ex:
        for d, dest, st in ex.map(one, sorted(days)):
            stat[dstr(d)] = st
            if st in ("404", "mismatch"):
                continue
            cols = [0, 1, 2, 3, 4, 5, 7] if kind == "klines" else [0, 1, 2, 3, 4]
            df = C.read_kline_zip(dest, cols)
            if df is not None:
                frames.append(df)
    if not frames:
        return None, stat
    df = pd.concat(frames, ignore_index=True)
    df = df[pd.to_numeric(df[0], errors="coerce").notna()]
    df[0] = C.to_ms(df[0].astype(np.int64).values)
    return df.drop_duplicates(0, keep="last"), stat


def main():
    uni = json.load(open(os.path.join(C.OUT, "universe.json")))["universe"]
    state = C.load_state()
    for sym in uni:
        info = state[sym]
        if info.get("daily_fill") is not None:
            continue
        if C.free_bytes() < C.MIN_FREE:
            C.log(f"fill ABORT: free disk below 1 GB before {sym}")
            sys.exit(2)
        p5 = os.path.join(C.OUT, info["npz_5m"])
        z = np.load(p5)
        a = {k: z[k] for k in z.files}
        ts = a["ts"]
        nz = np.flatnonzero(a["v"] > 0)
        last_traded = int(ts[nz[-1]])
        # kline hole days
        d = np.diff(ts)
        kdays = set()
        for i in np.flatnonzero(d > 3_600_000):
            for dd in range(int((ts[i] + STEP) // DAY), int((ts[i + 1] - STEP) // DAY) + 1):
                kdays.add(dd)
        # mark hole days (only while the coin traded)
        nanmask = np.isnan(a["mc"]) & (ts <= last_traded)
        dd, cnt = np.unique(ts[nanmask] // DAY, return_counts=True)
        mdays = {int(x) for x, c in zip(dd, cnt) if c >= 12} | kdays
        fill = {"kline_days": [dstr(x) for x in sorted(kdays)], "mark_days": [dstr(x) for x in sorted(mdays)],
                "kline_rows_added": 0, "mark_bars_filled": 0, "daily_status": {}}
        changed = False
        if kdays:
            kdf, st = fetch_days(sym, "klines", kdays)
            fill["daily_status"]["klines"] = st
            if kdf is not None:
                kdf = kdf[~np.isin(kdf[0].values, ts)]
                kdf = kdf[(kdf[0] >= ts[0]) & (kdf[0] <= ts[-1])]
                if len(kdf):
                    n = len(kdf)
                    new = {"ts": kdf[0].values.astype(np.int64)}
                    for c, j in zip(["o", "h", "l", "c", "v", "qv"], [1, 2, 3, 4, 5, 7]):
                        new[c] = kdf[j].values.astype(np.float64)
                    for c in ["mo", "mh", "ml", "mc"]:
                        new[c] = np.full(n, np.nan, np.float64)
                    for k in a:
                        a[k] = np.concatenate([a[k], new[k]])
                    o = np.argsort(a["ts"], kind="stable")
                    a = {k: v[o] for k, v in a.items()}
                    ts = a["ts"]
                    fill["kline_rows_added"] = int(n)
                    changed = True
        if mdays:
            mdf, st = fetch_days(sym, "markPriceKlines", mdays)
            fill["daily_status"]["mark"] = st
            if mdf is not None:
                mdf = mdf.set_index(0)
                need = np.flatnonzero(np.isnan(a["mc"]))
                hit = np.isin(ts[need], mdf.index.values)
                idx = need[hit]
                if len(idx):
                    sub = mdf.loc[ts[idx]]
                    for c, j in zip(["mo", "mh", "ml", "mc"], [1, 2, 3, 4]):
                        a[c][idx] = sub[j].values.astype(np.float64)
                    fill["mark_bars_filled"] = int(len(idx))
                    changed = True
        if changed:
            tmp = p5 + ".tmp.npz"
            np.savez_compressed(tmp, **a)
            os.replace(tmp, p5)
        # refresh coverage fields
        ts = a["ts"]
        d = np.diff(ts)
        nz = np.flatnonzero(a["v"] > 0)
        info["rows"] = int(len(ts))
        info["missing_5m_bars_inside_span"] = int(((d // STEP) - 1)[d > STEP].sum())
        info["gaps_over_1h"] = int((d > 3_600_000).sum())
        info["largest_gap_hours"] = round(float(d.max() / 3_600_000), 2)
        info["off_grid_ts"] = int((ts % STEP != 0).sum())
        info["bars_without_mark"] = int(np.isnan(a["mc"]).sum())
        info["bars_without_mark_while_trading"] = int((np.isnan(a["mc"]) & (ts <= ts[nz[-1]])).sum())
        info["zero_volume_bars"] = int((a["v"] == 0).sum())
        info["last_nonzero_volume_bar"] = ym(int(ts[nz[-1]]))
        info["trailing_zero_volume_bars"] = int(len(ts) - 1 - nz[-1])
        info["trailing_zero_volume_days"] = round((len(ts) - 1 - nz[-1]) * 5 / 1440, 1)
        info["traded_to_range_end"] = bool(ts[nz[-1]] >= ts[-1] - DAY and info["last_month"] == C.RANGE_END)
        info["npz_5m_bytes"] = os.path.getsize(p5)
        info["sha256_5m"] = C.sha256_file(p5)
        # funding vs trading period
        pf = os.path.join(C.OUT, info["npz_funding"])
        f = np.load(pf)
        fts = f["ts"]
        lt = int(ts[nz[-1]])
        info["funding_rows_after_last_traded_bar"] = int((fts > lt).sum())
        fin = fts[fts <= lt]
        fd = np.diff(fin)
        info["funding_gaps_over_8h_while_trading"] = int((fd > 8 * 3_600_000 + 300_000).sum())
        info["funding_largest_gap_hours_while_trading"] = round(float(fd.max() / 3_600_000), 2) if len(fd) else None
        lm = time.strftime("%Y-%m", time.gmtime(lt / 1000))
        info["missing_months_funding_while_trading"] = [m for m in info["missing_months_funding"] if m <= lm]
        info["missing_months_klines_while_trading"] = [m for m in info["missing_months_klines"] if m <= lm]
        info["missing_months_mark_while_trading"] = [m for m in info["missing_months_mark"] if m <= lm]
        info["daily_fill"] = fill
        state[sym] = info
        C.save_state(state)
        C.write_manifest(state, uni)
        import shutil
        shutil.rmtree(os.path.join(C.RAW, sym), ignore_errors=True)
        C.log(f"fill {sym}: kline days {len(kdays)} rows+{fill['kline_rows_added']}, mark days {len(mdays)} "
              f"filled {fill['mark_bars_filled']}, now missing bars {info['missing_5m_bars_inside_span']}, "
              f"no-mark while trading {info['bars_without_mark_while_trading']}")
    C.write_manifest(state, uni)
    C.log("fill: finished")


if __name__ == "__main__":
    main()
