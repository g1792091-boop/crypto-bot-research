"""Stitch raw Astral pulls into continuous per-symbol files and run the data gates.
raw files: ../data_oos/raw/{sym}_{tf}_p{k}.csv  (k=1 newest). Output ../data_oos/{sym}-{tf}-ohlcv.csv
Gates (pre-registered): (G1) every raw file sha256 == Astral artifact sha (checked by caller, listed in
../data_oos/raw/SHA_EXPECTED.txt); (G2) overlapping bars between consecutive pulls identical;
(G3) 5m resampled to open-labelled 15m (complete 3-bar buckets) equals the 15m file OHLC on >= 98% of
common bars (rel tol 1e-9); (G4) fetched 15m equals the existing delivered 15m file on the common range
(reported; revisions flagged); (G5) no 5m bar at/after 2026-05-12T00:00Z (strictly before the IS 5m data)."""
import glob, hashlib, os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.environ.get("SC_RAW", os.path.join(HERE, "..", "data_oos", "raw")); OUT = os.environ.get("SC_OUT", os.path.join(HERE, "..", "data_oos"))
ISD = "/home/user/crypto-bot-research/data"
SYMS = ("btcusd", "ethusd", "solusd")


def rd(p):
    d = pd.read_csv(p)
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    return d


def main():
    rep = {}
    exp = {}
    ef = os.path.join(RAW, "SHA_EXPECTED.txt")
    if os.path.exists(ef):
        for line in open(ef):
            if line.strip():
                h, f = line.split()
                exp[f] = h
    for f in sorted(glob.glob(os.path.join(RAW, "*.csv"))):
        b = os.path.basename(f); h = hashlib.sha256(open(f, "rb").read()).hexdigest()
        rep.setdefault("G1_sha", {})[b] = dict(sha=h, expected=exp.get(b), ok=(exp.get(b) == h))
    for sym in SYMS:
        for tf in ("5m", "15m"):
            parts = sorted(glob.glob(os.path.join(RAW, f"{sym}_{tf}_p*.csv")))
            if not parts:
                continue
            frames = [rd(p) for p in parts]
            ov = []
            for a, b in zip(frames[:-1], frames[1:]):   # a newer, b older
                m = a.merge(b, on="timestamp", suffixes=("_a", "_b"))
                same = all(np.allclose(m[c + "_a"], m[c + "_b"], rtol=0, atol=0) for c in ("open", "high", "low", "close"))
                ov.append(dict(common=int(len(m)), identical=bool(same)))
            d = pd.concat(frames).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
            step = pd.Timedelta(tf.replace("m", "min"))
            dt = d.timestamp.diff().dropna()
            gaps = dt[dt != step]
            rep.setdefault("files", {})[f"{sym}_{tf}"] = dict(
                parts=[os.path.basename(p) for p in parts], rows_per_part=[len(x) for x in frames], G2_overlap=ov,
                rows=int(len(d)), first=str(d.timestamp.iloc[0]), last=str(d.timestamp.iloc[-1]),
                n_gaps=int(len(gaps)), max_gap_min=float(gaps.max() / pd.Timedelta("1min")) if len(gaps) else 0.0,
                gaps_top=[(str(d.timestamp[i - 1]), float(dt[i] / pd.Timedelta("1min"))) for i in gaps.sort_values(ascending=False).index[:5]],
                flat_bars=int(((d.high == d.low)).sum()))
            out = d.copy(); out["timestamp"] = out.timestamp.dt.strftime("%Y-%m-%dT%H:%M:%S+0000")
            out.to_csv(os.path.join(OUT, f"{sym}-{tf}-ohlcv.csv"), index=False)
        # G3 resample check
        p5, p15 = os.path.join(OUT, f"{sym}-5m-ohlcv.csv"), os.path.join(OUT, f"{sym}-15m-ohlcv.csv")
        if os.path.exists(p5) and os.path.exists(p15):
            d5 = rd(p5).set_index("timestamp"); d15 = rd(p15).set_index("timestamp")
            g = d5.resample("15min", label="left", closed="left")
            r = pd.DataFrame(dict(open=g.open.first(), high=g.high.max(), low=g.low.min(), close=g.close.last(),
                                  volume=g.volume.sum(), cnt=g.open.count()))
            r = r[r.cnt == 3]
            j = r.join(d15, rsuffix="_f", how="inner")
            ok = np.ones(len(j), bool)
            for c in ("open", "high", "low", "close"):
                ok &= np.isclose(j[c], j[c + "_f"], rtol=1e-9, atol=0)
            vol_ok = np.isclose(j.volume, j.volume_f, rtol=1e-6)
            rep.setdefault("G3_resample", {})[sym] = dict(common_complete_bars=int(len(j)), ohlc_match=float(ok.mean()),
                                                          volume_match=float(vol_ok.mean()), pass_98=bool(ok.mean() >= 0.98))
            # G4 vs delivered 15m
            e15 = rd(os.path.join(ISD, f"{sym}-15m-ohlcv.csv")).set_index("timestamp")
            k = d15.join(e15, rsuffix="_e", how="inner")
            ok4 = np.ones(len(k), bool)
            for c in ("open", "high", "low", "close"):
                ok4 &= np.isclose(k[c], k[c + "_e"], rtol=1e-9, atol=0)
            rep.setdefault("G4_vs_delivered15m", {})[sym] = dict(common=int(len(k)), ohlc_match=float(ok4.mean()),
                                                                 first_mismatch=[str(x) for x in k.index[~ok4][:5]])
            # G5
            rep.setdefault("G5_before_IS", {})[sym] = bool(d5.index.max() < pd.Timestamp("2026-05-12T00:00Z"))
            # 15m warm-up coverage before first 5m bar
            rep.setdefault("warmup_15m_bars_before_5m_start", {})[sym] = int((d15.index < d5.index.min()).sum())
    json.dump(rep, open(os.path.join(OUT, "gates.json"), "w"), indent=1, default=str)
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main()
