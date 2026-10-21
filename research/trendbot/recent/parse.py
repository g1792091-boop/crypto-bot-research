"""Parse the downloaded 1m kline zips (untrusted data: read as CSV only) into one npz per coin.
Output: ROOT/cache/<COIN>-1m.npz with arrays ts (open ms, int64), o, h, l, c, v (float64), sorted, de-duplicated.
Run: python3 -I parse.py ROOT"""
import glob
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import COINS, np, pd  # noqa: E402

ROOT = sys.argv[1]
os.makedirs(f"{ROOT}/cache", exist_ok=True)


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        assert len(names) == 1, (path, z.namelist())
        raw = z.read(names[0]).decode("ascii")
    first = raw.split("\n", 1)[0]
    header = 0 if first.startswith("open_time") else None
    d = pd.read_csv(io.StringIO(raw), header=header, usecols=range(6))
    d.columns = ["ts", "o", "h", "l", "c", "v"]
    return d


for coin in COINS:
    parts = [read_zip(p) for p in sorted(glob.glob(f"{ROOT}/data/{coin}-1m-*/{coin}-1m-*.zip"))]
    d = pd.concat(parts, ignore_index=True)
    d["ts"] = d["ts"].astype(np.int64)
    d = d.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    ts = d["ts"].to_numpy(np.int64)
    gaps = np.diff(ts) != 60_000
    print(coin, len(d), pd.to_datetime(ts[0], unit="ms"), pd.to_datetime(ts[-1], unit="ms"), "gaps:", int(gaps.sum()),
          [(str(pd.to_datetime(ts[i], unit='ms')), int((ts[i + 1] - ts[i]) // 60000)) for i in np.where(gaps)[0][:10]])
    np.savez(f"{ROOT}/cache/{coin}-1m.npz", ts=ts, o=d["o"].to_numpy(float), h=d["h"].to_numpy(float),
             l=d["l"].to_numpy(float), c=d["c"].to_numpy(float), v=d["v"].to_numpy(float))
