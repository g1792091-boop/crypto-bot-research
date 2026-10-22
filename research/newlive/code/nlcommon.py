"""Shared helpers of the new-live member study (research/newlive): paths, the 1m grid extended past the verified fg1m
files with the October daily files of download.sh, the candidate labels.
Run every script with python3 -I (the repo and the five-year code are put on sys.path explicitly, as
research/trendbot/fiveyear/code/fycommon.py does; data files are read as arrays / CSV only)."""
import os, sys
sys.path.append("/root/.local/lib/python3.11/site-packages")      # user site (dateutil), dropped by -I
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
assert os.path.isfile(os.path.join(REPO, "deploy", "combo.trend.json")), REPO
FYCODE = os.path.join(REPO, "research", "trendbot", "fiveyear", "code")
for _p in (REPO, FYCODE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import glob, io, json, zipfile
import numpy as np
import pandas as pd
import fycommon as FY                                    # the five-year study's helpers (agg, df_of, ms, sha256, grid)
from fycommon import COINS, MIN, FIVE, HOUR, TF_MS, T0, FG, ms, sha256, agg, df_of

SCR = FY.SCR
NL = f"{SCR}/newlive"
DATA = f"{NL}/data"                 # download.sh: klines/<name>/<name>.zip, mark/..., funding/... (+ .CHECKSUM, ok)
SIG = f"{NL}/signals"               # signals_all.py: one npz per label
JUDGE = f"{NL}/judge"               # judge_all.py: one npz per coin
RUNS = f"{NL}/runs"
FYREF = f"{NL}/fy_ref"              # the five-year code re-run (its outputs were removed from the scratchpad)
T_FG_END = FY.T_FG_END              # fg1m: last minute 2026-09-30 23:59
T_FY_END = FY.T_OCT_END             # the five-year study's data end (exclusive): 2026-10-21 00:00
DAY = 86_400_000


def _ok_days(kind):
    out = {}
    for d in glob.glob(f"{DATA}/{kind}/*-1m-2026-*"):
        if os.path.isfile(f"{d}/ok"):
            coin, _, day = os.path.basename(d).split("-", 2)
            out.setdefault(coin, set()).add(day)
    return out


def data_end():
    """Exclusive end (ms) of the extended data: the last day, contiguous from 2026-10-01, for which all six coins have
    checksum-verified kline AND mark-price files."""
    k, m = _ok_days("klines"), _ok_days("mark")
    t = T_FG_END
    while True:
        day = str(pd.Timestamp(t, unit="ms").date())
        if all(day in k.get(c, ()) and day in m.get(c, ()) for c in COINS):
            t += DAY
        else:
            return t


DATA_END = data_end()


def funding_files():
    return {c: sorted(glob.glob(f"{DATA}/funding/{c}-fundingRate-*/ok")) for c in COINS}


def _read_zip_csv(p, ncol=6):
    with zipfile.ZipFile(p) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        assert len(names) == 1, (p, z.namelist())
        raw = z.read(names[0]).decode("ascii")
    return raw


def read_days(coin, kind, end):
    """Daily 1m files of ``kind`` (klines | mark) from 2026-10-01 to ``end`` (exclusive), read as CSV only."""
    parts = []
    t = T_FG_END
    while t < end:
        day = str(pd.Timestamp(t, unit="ms").date())
        name = f"{coin}-1m-{day}"
        p = f"{DATA}/{kind}/{name}/{name}.zip"
        assert os.path.isfile(f"{DATA}/{kind}/{name}/ok"), f"missing {kind} {name} (run download.sh)"
        raw = _read_zip_csv(p)
        d = pd.read_csv(io.StringIO(raw), header=0 if raw.startswith("open_time") else None, usecols=range(6))
        d.columns = ["ts", "o", "h", "l", "c", "v"]
        parts.append(d)
        t += DAY
    d = pd.concat(parts, ignore_index=True)
    d["ts"] = d["ts"].astype(np.int64)
    return d.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def read_funding(coin):
    """Monthly funding files after fg1m (2026-10 when published): (calc_time ms, rate)."""
    rows = []
    for okf in sorted(glob.glob(f"{DATA}/funding/{coin}-fundingRate-*/ok")):
        d = os.path.dirname(okf)
        raw = _read_zip_csv(f"{d}/{os.path.basename(d)}.zip")
        f = pd.read_csv(io.StringIO(raw), header=0 if raw.startswith("calc_time") else None)
        rows.append(np.c_[f.iloc[:, 0].to_numpy(np.int64), f.iloc[:, -1].to_numpy(float)])
    return np.concatenate(rows) if rows else np.zeros((0, 2))


def load_grid(coin, end=None, oct_mark="mark"):
    """1m bars on the full minute grid T0 .. end (exclusive, default DATA_END), as fycommon.load_grid: fg1m to
    2026-09-30, then the October daily klines (rows as Binance gives them, as the five-year study read them) and the
    daily mark-price klines (``oct_mark="last"``: the last price instead, the five-year study's October form). Funding
    after September only from a published monthly file (none for 2026-10 yet: 0). Minutes before the coin's first bar
    are NaN; a missing minute inside the series is a flat bar at the previous close with volume 0."""
    end = DATA_END if end is None else int(end)
    assert end <= DATA_END, (end, DATA_END)
    z = np.load(f"{FG}/1m/{coin}.npz")
    ts = z["ts"]
    n = (end - T0) // MIN
    idx = (ts - T0) // MIN
    assert ((ts - T0) % MIN == 0).all() and (np.diff(ts) > 0).all()
    keep = idx < n
    idx = idx[keep]
    out = {}
    for k in ("o", "h", "l", "c", "v", "mo", "mh", "ml", "mc", "fund"):
        a = np.full(n, np.nan)
        a[idx] = z[k][keep]
        out[k] = a
    if end > T_FG_END:
        d = read_days(coin, "klines", end)
        j = (d["ts"].to_numpy() - T0) // MIN
        ok = (j >= 0) & (j < n)
        for k in ("o", "h", "l", "c", "v"):
            out[k][j[ok]] = d[k].to_numpy(float)[ok]
        if oct_mark == "last":
            for k, src in (("mo", "o"), ("mh", "h"), ("ml", "l"), ("mc", "c")):
                out[k][j[ok]] = d[src].to_numpy(float)[ok]
        else:
            mk = read_days(coin, "mark", end)
            jm = (mk["ts"].to_numpy() - T0) // MIN
            okm = (jm >= 0) & (jm < n)
            for k, src in (("mo", "o"), ("mh", "h"), ("ml", "l"), ("mc", "c")):
                out[k][jm[okm]] = mk[src].to_numpy(float)[okm]
            miss = ok.copy()
            miss[ok] = np.isnan(out["mc"][j[ok]])             # a kline minute without a mark row: the last price
            for k, src in (("mo", "o"), ("mh", "h"), ("ml", "l"), ("mc", "c")):
                out[k][j[miss]] = d[src].to_numpy(float)[miss]
        out["fund"][j[ok]] = 0.0
        if oct_mark != "last":
            fr = read_funding(coin)
            if len(fr):
                jf = (fr[:, 0].astype(np.int64) - T0) // MIN
                okf = (jf >= (T_FG_END - T0) // MIN) & (jf < n)
                out["fund"][jf[okf]] = fr[okf, 1]
    have = ~np.isnan(out["c"])
    first = int(np.argmax(have))
    filled = np.zeros(n, bool)
    miss = np.flatnonzero(~have[first:]) + first
    if len(miss):
        last_idx = np.maximum.accumulate(np.where(have, np.arange(n), -1))
        src = last_idx[miss]
        for k in ("o", "h", "l", "c"):
            out[k][miss] = out["c"][src]
        for k in ("mo", "mh", "ml", "mc"):
            out[k][miss] = out["mc"][src]
        out["v"][miss] = 0.0
        out["fund"][miss] = 0.0
        filled[miss] = True
    out["fund"] = np.nan_to_num(out["fund"])
    out["filled"] = filled
    out["first"] = first
    out["n"] = n
    out["end"] = end
    return out


def data_manifest():
    """What the extended data holds (recorded with every output)."""
    fund = {c: [os.path.basename(os.path.dirname(p)) for p in v] for c, v in funding_files().items()}
    return {"fg1m_end_exclusive": "2026-10-01", "data_end_exclusive": str(pd.Timestamp(DATA_END, unit="ms")),
            "last_minute": str(pd.Timestamp(DATA_END - MIN, unit="ms")),
            "october_klines_days": len(_ok_days("klines").get("BTCUSDT", ())),
            "october_mark_days": len(_ok_days("mark").get("BTCUSDT", ())),
            "october_funding_files": fund,
            "october_funding": ("from the monthly file" if all(fund.values()) else
                                "none published (data.binance.vision has monthly funding files only; 2026-10 appears "
                                "after the month ends; the REST API is not reachable here): 0 after 2026-09-30")}


# ====================================================================== labels
def label_of(name, tf, pick=None):
    return f"{name}@{tf}" + (f"#{pick}" if pick else "")


def parse_label(label):
    base, _, pick = label.partition("#")
    name, tf = base.split("@")
    return name, tf, (pick or None)


def sig_path(label):
    return f"{SIG}/{label.replace('@', '_at_').replace('#', '__')}.npz"
