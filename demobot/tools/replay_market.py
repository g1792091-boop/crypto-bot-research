"""Replay market (development and tests only, never on the server): serves recorded Binance USD-M 15m bars and
funding from local files with a settable clock, through the same interface as paperbot.binance.BinanceREST.

Data folder (SCR) layout as in the research session: binance/bars/<coin>usd-15m.csv.gz (2021-), binance/funding/,
xrp_raw/*.zip (Binance XRPUSDT 15m kline zips), and the repo's data/pre2021/<coin>usd-15m.csv.gz (before 2021).
Override SCR with the env DEMOBOT_REPLAY_DATA."""
import io, os, zipfile, glob
import numpy as np, pandas as pd

SCR = os.environ.get("DEMOBOT_REPLAY_DATA",
                     "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad")
PRE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "pre2021")
SPLIT = 1609459200000          # 2021-01-01
M15 = 900_000

def _xrp():
    files = sorted(glob.glob(f"{SCR}/xrp_raw/*.zip"))
    monthly = [f for f in files if os.path.basename(f).count("-") == 3]
    daily = [f for f in files if os.path.basename(f).count("-") == 4]
    fr = []
    for p in monthly + daily:
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if not n.lower().endswith(".csv"):
                    continue
                data = z.read(n)
                header = 0 if data[:1].isalpha() else None
                d = pd.read_csv(io.BytesIO(data), header=header, usecols=range(6))
                d.columns = ["t", "o", "h", "l", "c", "v"]
                t = d["t"].to_numpy(np.int64)
                d["t"] = np.where(t >= 10**14, t // 1000, t)
                fr.append(d)
    d = pd.concat(fr).sort_values("t").drop_duplicates("t", keep="last")
    return d

def load(t0_ms, t1_ms):
    out = {}
    for coin in ("BTC", "ETH", "SOL", "DOGE", "LTC", "BCH", "XRP"):
        if coin == "XRP":
            d = _xrp()
        else:
            parts = []
            if t0_ms < SPLIT and os.path.exists(f"{PRE}/{coin.lower()}usd-15m.csv.gz"):
                p0 = pd.read_csv(f"{PRE}/{coin.lower()}usd-15m.csv.gz")
                p0["t"] = pd.to_datetime(p0["ts"], utc=True).astype("int64") // 10**6
                parts.append(p0[p0.t < SPLIT])
            if t1_ms > SPLIT:
                p1 = pd.read_csv(f"{SCR}/binance/bars/{coin.lower()}usd-15m.csv.gz")
                p1["t"] = pd.to_datetime(p1["ts"], utc=True).astype("int64") // 10**6
                parts.append(p1)
            d = pd.concat(parts)
            d = d.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})
        d = d[(d.t >= t0_ms) & (d.t < t1_ms) & (d.v > 0)]
        out[coin + "USDT"] = d[["t", "o", "h", "l", "c", "v"]].to_numpy(float)
    return out

def load_funding():
    out = {}
    for p in glob.glob(f"{SCR}/binance/funding/*.csv"):
        sym = os.path.basename(p)[:-4]
        d = pd.read_csv(p)
        out[sym] = d
    return out

class FakeREST:
    def __init__(self, bars, funding, clock):
        self.bars, self.funding, self.clock = bars, funding, clock
        self.calls = 0
    def klines(self, symbol, interval, start_time=None, limit=1500):
        assert interval == "15m"
        self.calls += 1
        a = self.bars[symbol]
        now = self.clock()
        a = a[a[:, 0] <= now]          # bars opened by now (the last one may be forming)
        if start_time is not None:
            a = a[a[:, 0] >= start_time][:limit]
        else:
            a = a[-limit:]
        return [[int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), int(r[0]) + M15 - 1] for r in a]
    def funding_rates(self, symbol, start_time=None, limit=1000):
        self.calls += 1
        d = self.funding.get(symbol)
        if d is None:
            return []
        tcol = [c for c in d.columns if "time" in c.lower() or c == "ts"][0]
        rcol = [c for c in d.columns if "rate" in c.lower()][0]
        t = d[tcol]
        if not np.issubdtype(t.dtype, np.number):
            t = pd.to_datetime(t, utc=True).astype("int64") // 10**6
        t = t.to_numpy(np.int64)
        r = d[rcol].to_numpy(float)
        m = t <= self.clock()
        if start_time is not None:
            m &= t >= start_time
        idx = np.flatnonzero(m)[:limit]
        return [{"fundingTime": int(t[i]), "fundingRate": str(r[i])} for i in idx]
    def depth(self, symbol, limit=500):
        """A synthetic order book around the open of the bar that is forming now (replay only: real books are not
        archived). Spread 1 tick-ish (0.5 bp), each level 0.5 bp apart, size growing with distance."""
        self.calls += 1
        a = self.bars[symbol]
        a = a[a[:, 0] <= self.clock()]
        if not len(a):
            return {"bids": [], "asks": []}
        mid = float(a[-1][1])
        step = mid * 0.5e-4
        base = 40_000.0 / mid
        bids = [[mid - step * (i + 0.5), base * (1 + 0.15 * i)] for i in range(limit)]
        asks = [[mid + step * (i + 0.5), base * (1 + 0.15 * i)] for i in range(limit)]
        return {"bids": bids, "asks": asks}
