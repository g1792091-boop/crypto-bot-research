"""Independent rebuild of OBV20@4h>RSI@1h|a2 from the raw 1m data (verifier, look-ahead / time-alignment lens).

Nothing from the study's code or derived files is used here: raw Binance USDT-M 1m bars (fg1m npz to 2026-09-30, the
daily 1m kline zips for 2026-10-01 .. 10-22, read as CSV text), the rule bot's live_bars.csv for 10-23 .. 10-24 (extracted
by the verifier into its own empty folder, read as CSV), bars made with pandas resample, my own RSI / OBV / SMA / ATR,
higher-bar alignment with merge_asof on bar CLOSE times, and my own 1m walk of the a2 exit.

Variants written for the look-ahead tests (all with the same walk):
  ok       trend = last 4h bar whose close <= the 1h signal bar's close (the study's claim)
  la4h     trend = the NEXT 4h bar (the one still forming / closing after the signal) -> deliberate look-ahead
  la1h     RSI cross of the NEXT 1h bar used at this bar's close -> deliberate look-ahead
  d1, d5   entry 1 / 5 minutes late (robustness of the fill time)

Output: indep_rows.csv (one row per coin x 1h bar x variant with a signal), printed summaries.
    python3 indep.py <live_bars.csv>
"""
import glob
import io
import os
import sys
import zipfile

import numpy as np
import pandas as pd

SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
FG = f"{SCR}/fg1m/1m"
KL = f"{SCR}/newlive/data/klines"
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
MIN = 60_000
T0 = int(pd.Timestamp("2020-01-01", tz="UTC").value // 10**6)
GRID_END = int(pd.Timestamp("2026-10-23", tz="UTC").value // 10**6)
COST = 2 * (0.00042 + 0.0002)
PAYBACK = 2 * 0.9 * 0.00042
LEV = 30.0
WARM = 300
HERE = os.path.dirname(os.path.abspath(__file__))


def ms(s):
    return int(pd.Timestamp(s, tz="UTC").value // 10**6)


def load_live(path):
    lb = pd.read_csv(path, usecols=["ts", "symbol", "open", "high", "low", "close", "volume"])
    lb = lb[lb.ts >= GRID_END]
    return lb


def raw_minutes(coin, lb, end):
    z = np.load(f"{FG}/{coin}.npz")
    a = pd.DataFrame({k: z[k] for k in ("ts", "o", "h", "l", "c", "v", "fund")})
    parts = [a]
    t = ms("2026-10-01")
    while t < GRID_END:
        day = str(pd.Timestamp(t, unit="ms").date())
        nm = f"{coin}-1m-{day}"
        with zipfile.ZipFile(f"{KL}/{nm}/{nm}.zip") as zf:
            raw = zf.read(zf.namelist()[0]).decode("ascii")
        d = pd.read_csv(io.StringIO(raw), header=0 if raw.startswith("open_time") else None, usecols=range(6))
        d.columns = ["ts", "o", "h", "l", "c", "v"]
        d["fund"] = 0.0
        parts.append(d)
        t += 86_400_000
    x = lb[lb.symbol == coin].rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})
    x = x[["ts", "o", "h", "l", "c", "v"]].copy()
    x["fund"] = 0.0
    parts.append(x)
    m = pd.concat(parts, ignore_index=True)
    m["ts"] = m.ts.astype(np.int64)
    m = m.drop_duplicates("ts", keep="first").sort_values("ts")
    m = m[(m.ts >= T0) & (m.ts < end)]
    first = int(m.ts.iloc[0])
    full = np.arange(first, end, MIN, dtype=np.int64)
    m = m.set_index("ts").reindex(full)
    miss = m.c.isna().to_numpy()
    pc = m.c.ffill()
    for k in ("o", "h", "l", "c"):
        m[k] = m[k].where(~miss, pc)
    m["v"] = m.v.fillna(0.0)
    m["fund"] = m.fund.fillna(0.0)
    return m, int(miss.sum()), first


def resample(m, rule, nmin, first):
    idx = pd.to_datetime(m.index.to_numpy(), unit="ms", utc=True)
    d = pd.DataFrame({"o": m.o.to_numpy(), "h": m.h.to_numpy(), "l": m.l.to_numpy(), "c": m.c.to_numpy(),
                      "v": m.v.to_numpy()}, index=idx)
    b = d.resample(rule, label="left", closed="left", origin="epoch").agg(
        {"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"})
    cnt = d.c.resample(rule, label="left", closed="left", origin="epoch").count()
    b["open_ms"] = (b.index.view(np.int64) // 10**6).astype(np.int64)
    b = b[(cnt.to_numpy() == nmin) & (b.open_ms.to_numpy() >= first)].reset_index(drop=True)
    b["close_ms"] = b.open_ms + nmin * MIN
    return b


def rma(x, n):
    """Pine rma: SMA seed of the first n finite values, then alpha 1/n."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    fin = np.flatnonzero(np.isfinite(x))
    if len(fin) < n:
        return out
    s = fin[0]
    out[s + n - 1] = x[s:s + n].mean()
    for i in range(s + n, len(x)):
        out[i] = out[i - 1] + (x[i] - out[i - 1]) / n
    return out


def rsi(c, n=14):
    d = np.r_[np.nan, np.diff(c)]
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    up[0] = dn[0] = np.nan
    au, ad = rma(up, n), rma(dn, n)
    with np.errstate(all="ignore"):
        r = 100 - 100 / (1 + au / ad)
        r = np.where(ad == 0, 100.0, np.where(au == 0, 0.0, r))
    return np.where(np.isfinite(au) & np.isfinite(ad), r, np.nan)


def atr(h, l, c, n=14):
    pc = np.r_[np.nan, c[:-1]]
    tr = np.where(np.isfinite(pc), np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))), h - l)
    return rma(tr, n)


def lock_for(best):
    if best < 0.12 - 1e-12:
        return None
    return 0.10 + 0.05 * np.floor((best - 0.12) / 0.05 + 1e-9)


def walk(o, h, l, c, cumf, e, s, atrd, n):
    p0 = o[e]
    f0 = cumf[e - 1]
    best = -1e9
    lk = None
    i = e
    while i < n:
        Fp = s * (cumf[i - 1] - f0)
        level = max(-atrd, -1.0 / LEV + COST + Fp)
        if lk is not None:
            level = max(level, lk / LEV + COST + Fp)
        if s > 0:
            up, dn = h[i] / p0 - 1.0, l[i] / p0 - 1.0
        else:
            up, dn = 1.0 - l[i] / p0, 1.0 - h[i] / p0
        op = s * (o[i] / p0 - 1.0)
        F = s * (cumf[i] - f0)
        if dn <= level:
            ret = min(level, op) - COST - F
            return max(ret, -1.0 / LEV) * LEV, i - e, (1 if lk is not None else 0), best
        r_up = LEV * (up - COST - F)
        if r_up > best:
            best = r_up
            lk2 = lock_for(best)
            if lk2 is not None:
                lk = lk2
        i += 1
    i = n - 1
    F = s * (cumf[i] - f0)
    return max(s * (c[i] / p0 - 1.0) - COST - F, -1.0 / LEV) * LEV, i - e, 3, best


def main(live_path):
    lb = load_live(live_path)
    end = int(min(lb[lb.symbol == c].ts.max() for c in COINS)) + MIN
    rows = []
    info = {}
    for coin in COINS:
        m, nmiss, first = raw_minutes(coin, lb, end)
        ts = m.index.to_numpy(np.int64)
        o, h, l, c = (m[k].to_numpy(float) for k in ("o", "h", "l", "c"))
        cumf = np.cumsum(m.fund.to_numpy(float))
        n = len(ts)
        b1 = resample(m, "1h", 60, first)
        b4 = resample(m, "4h", 240, first)
        # 4h trend: OBV vs SMA20 of OBV
        c4 = b4.c.to_numpy(float)
        ob = np.cumsum(np.sign(np.nan_to_num(np.r_[np.nan, np.diff(c4)])) * b4.v.to_numpy(float))
        sma = pd.Series(ob).rolling(20, min_periods=20).mean().to_numpy()
        st = np.sign(ob - sma)
        st = np.where(np.isfinite(st), st, 0)
        st[:WARM] = 0
        b4["st"] = st.astype(int)
        b4["obv"], b4["obv_sma20"] = ob, sma
        # 1h timing: RSI14 cross up 30 (long) / cross down 70 (short)
        c1 = b1.c.to_numpy(float)
        r = rsi(c1, 14)
        rp = np.r_[np.nan, r[:-1]]
        with np.errstate(invalid="ignore"):
            lg = (r > 30) & (rp <= 30)
            sh = (r < 70) & (rp >= 70)
        sig = np.where(lg, 1, np.where(sh, -1, 0))
        sig[:WARM] = 0
        b1["sig"], b1["rsi"], b1["rsi_prev"] = sig, r, rp
        b1["atr"] = atr(b1.h.to_numpy(float), b1.l.to_numpy(float), c1, 14)
        b1["sig_next"] = np.r_[sig[1:], 0]                       # la1h: the next bar's cross (look-ahead)
        # alignment on close times: last 4h bar with close <= the 1h bar's close
        k4 = b4[["close_ms", "st"]].rename(columns={"close_ms": "k"}).astype(np.int64).sort_values("k")
        a = pd.merge_asof(b1[["close_ms"]].rename(columns={"close_ms": "k"}).astype(np.int64), k4, on="k",
                          direction="backward", allow_exact_matches=True)
        b1["st4"] = a.st.fillna(0).astype(int).to_numpy()
        b1["k4"] = pd.merge_asof(b1[["close_ms"]].rename(columns={"close_ms": "k"}).astype(np.int64),
                                 k4.assign(j=np.arange(len(k4))), on="k", direction="backward").j.fillna(-1).astype(int).to_numpy()
        jn = np.clip(b1.k4.to_numpy() + 1, 0, len(b4) - 1)
        b1["st4_la"] = np.where(b1.k4.to_numpy() + 1 < len(b4), b4.st.to_numpy()[jn], 0)   # la4h: next 4h bar (forming)
        pos = {int(t): i for i, t in enumerate(ts)} if False else None
        e_of = ((b1.close_ms.to_numpy() - ts[0]) // MIN).astype(np.int64)                # minute index of the close
        info[coin] = {"missing_minutes_filled": nmiss, "first": str(pd.Timestamp(first, unit="ms")),
                      "n1h": len(b1), "n4h": len(b4)}
        for var in ("ok", "la4h", "la1h", "d1", "d5"):
            sg = b1.sig_next.to_numpy() if var == "la1h" else b1.sig.to_numpy()
            tr = b1.st4_la.to_numpy() if var == "la4h" else b1.st4.to_numpy()
            delay = {"d1": 1, "d5": 5}.get(var, 0)
            for i in np.flatnonzero((sg != 0) & (tr == sg)):
                e = int(e_of[i]) + delay
                if e <= 0 or e >= n or not np.isfinite(b1.atr.iat[i]):
                    continue
                atrd = 2.0 * float(b1.atr.iat[i]) / o[e - delay]
                s = int(sg[i])
                roe, k, why, best = walk(o, h, l, c, cumf, e, s, atrd, n)
                roe_o, k_o, why_o, _ = walk(o, h, l, c, cumf, e, -s, atrd, n)
                rows.append((var, coin, int(b1.close_ms.iat[i]), s, roe, k, why, roe_o, why_o, best,
                             float(b1.rsi_prev.iat[i]), float(b1.rsi.iat[i]), float(b1.atr.iat[i]), o[e]))
        print(coin, info[coin], flush=True)
    R = pd.DataFrame(rows, columns=["var", "coin", "t_ms", "side", "roe", "k", "why", "roe_opp", "why_opp", "best",
                                    "rsi_prev", "rsi", "atr", "p0"])
    R.to_csv(os.path.join(HERE, "indep_rows.csv"), index=False)
    return R, info


if __name__ == "__main__":
    main(sys.argv[1])
