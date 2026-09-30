"""Cross-sectional strategies on a wide coin universe (research/universe/PREREG_UNIVERSE.md).

    python3 research/universe/xs.py selftest
    python3 research/universe/xs.py run

Data: data/universe/klines_1d*.csv.gz (every USDT perpetual in the public archive, delisted ones
included). Each rebalance picks the universe from information up to that day only.
"""

from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "research", "famous"))

import famous as FM  # noqa: E402  (boot_p, bh, summarize, windows)

DATA = os.path.join(ROOT, "data", "universe")
SIDE_COST = 0.0007
LONG_FUNDING_DAY = 0.0003
MIN_HISTORY = 60
EXCLUDE = {"USDCUSDT", "BUSDUSDT", "TUSDUSDT", "FDUSDUSDT", "USDPUSDT", "DAIUSDT", "BTCDOMUSDT", "DEFIUSDT",
           "BLUEBIRDUSDT", "FOOTBALLUSDT", "ALLUSDT"}
STABLE_VOL = 0.005  # 30-day daily return std below this -> treated as a stable/index product

STRATEGIES = []
for n in (20, 50):
    for lb in (7, 28):
        STRATEGIES.append((f"B1_LS_N{n}_L{lb}", "ls", n, lb, None))
        for k in (1, 3):
            STRATEGIES.append((f"B2_TOP{k}_N{n}_L{lb}", "top", n, lb, k))
    STRATEGIES.append((f"B3_REV1D_N{n}", "rev", n, 1, None))
LONG_ONLY_PREFIX = "B2_"


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    files = sorted(glob.glob(os.path.join(DATA, "klines_1d*.csv.gz")))
    d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    d["date"] = pd.to_datetime(d["open_time"], unit="ms").dt.normalize()
    d = d[~d["symbol"].isin(EXCLUDE)].drop_duplicates(["symbol", "date"], keep="last")
    close = d.pivot(index="date", columns="symbol", values="close").astype(float).sort_index()
    qvol = d.pivot(index="date", columns="symbol", values="quote_volume").astype(float).reindex(close.index)
    return close, qvol


def universe_at(close: pd.DataFrame, qvol: pd.DataFrame, i: int, n: int) -> list[str]:
    """Top-n symbols by 30-day mean quote volume on day i, among those with >= MIN_HISTORY days
    of closes up to day i, a close on day i, and 30-day return std >= STABLE_VOL."""
    if i < MIN_HISTORY:
        return []
    hist = close.iloc[max(0, i - MIN_HISTORY + 1): i + 1]
    ok = hist.notna().sum() >= MIN_HISTORY
    ok &= close.iloc[i].notna()
    vol30 = close.iloc[max(0, i - 30): i + 1].ffill().pct_change(fill_method=None).std()
    ok &= vol30 >= STABLE_VOL
    qv = qvol.iloc[max(0, i - 29): i + 1].mean()[ok[ok].index]
    return list(qv.sort_values(ascending=False).index[:n])


def weights(close: pd.DataFrame, qvol: pd.DataFrame, kind: str, n: int, lb: int, k) -> pd.DataFrame:
    """Target weights decided at day i's close (held over day i+1)."""
    idx = close.index
    w = pd.DataFrame(np.nan, index=idx, columns=close.columns)
    days = range(len(idx)) if kind == "rev" else [i for i in range(len(idx)) if idx[i].dayofweek == 6]
    for i in days:
        u = universe_at(close, qvol, i, n)
        if len(u) < max(10, n // 2):
            continue
        r = (close.iloc[i][u] / close.iloc[i - lb][u] - 1).dropna()
        if len(r) < 10:
            continue
        x = pd.Series(0.0, index=close.columns)
        q = max(1, len(r) // 5)
        order = r.sort_values(ascending=False)
        if kind == "ls":
            x[order.index[:q]] = 0.5 / q
            x[order.index[-q:]] = -0.5 / q
        elif kind == "rev":
            x[order.index[-q:]] = 0.5 / q
            x[order.index[:q]] = -0.5 / q
        else:
            top = order.index[:k]
            for s in top:
                if order[s] > 0:
                    x[s] = 1.0 / k
        w.iloc[i] = x
    return w.ffill().fillna(0.0)


def portfolio(close: pd.DataFrame, w: pd.DataFrame) -> pd.Series:
    """Daily net return. A symbol with no close on a day contributes 0 that day; its weight is
    dropped (the position is treated as closed at its last close)."""
    r = close.ffill().pct_change(fill_method=None).fillna(0.0)
    held = w.shift(1).fillna(0.0).where(close.notna(), 0.0)
    turn = (held - held.shift(1).fillna(0.0)).abs().sum(1)
    return (held * r).sum(1) - SIDE_COST * turn - LONG_FUNDING_DAY * held.clip(lower=0).sum(1)


def benchmark(close: pd.DataFrame, qvol: pd.DataFrame, n: int) -> pd.Series:
    """Equal-weight long of the same top-n universe, rebalanced weekly (for long-only strategies)."""
    idx = close.index
    w = pd.DataFrame(np.nan, index=idx, columns=close.columns)
    for i in range(len(idx)):
        if idx[i].dayofweek != 6:
            continue
        u = universe_at(close, qvol, i, n)
        if len(u) < max(10, n // 2):
            continue
        x = pd.Series(0.0, index=close.columns)
        x[u] = 1.0 / len(u)
        w.iloc[i] = x
    return portfolio(close, w.ffill().fillna(0.0))


def evaluate(close, qvol) -> pd.DataFrame:
    rows, bench = [], {}
    for k_, (sid, kind, n, lb, k) in enumerate(STRATEGIES):
        port = portfolio(close, weights(close, qvol, kind, n, lb, k))
        isw = FM.window(port, *FM.IS)
        r = {"id": sid, **{f"is_{a}": b for a, b in FM.summarize(isw).items()}, "is_p": FM.boot_p(isw, 2000 + k_),
             "is_half1_mean_pct": 100 * isw[isw.index < FM.HALF].mean(),
             "is_half2_mean_pct": 100 * isw[isw.index >= FM.HALF].mean()}
        if sid.startswith(LONG_ONLY_PREFIX):
            if n not in bench:
                bench[n] = benchmark(close, qvol, n)
            diff = (isw - FM.window(bench[n], *FM.IS)).dropna()
            r.update({"vs_bench_mean_pct": 100 * diff.mean(),
                      "vs_bench_half1_pct": 100 * diff[diff.index < FM.HALF].mean(),
                      "vs_bench_half2_pct": 100 * diff[diff.index >= FM.HALF].mean()})
        cw = FM.window(port, *FM.CONF)
        r.update({f"cf_{a}": b for a, b in FM.summarize(cw).items()})
        if sid.startswith(LONG_ONLY_PREFIX):
            dc = (cw - FM.window(bench[n], *FM.CONF)).dropna()
            r["cf_vs_bench_mean_pct"] = 100 * dc.mean()
        for lev in (1, 2, 3, 5):
            x = FM.window(port, FM.IS[0], FM.CONF[1]) * lev
            eq = (1 + x.clip(lower=-1)).cumprod()
            r[f"mdd_{lev}x_pct"] = 100 * float((eq / eq.cummax() - 1).min())
        r["worst_day_pct"] = 100 * float(FM.window(port, FM.IS[0], FM.CONF[1]).min())
        rows.append(r)
    t = pd.DataFrame(rows)
    t["bh_pass"] = FM.bh(t["is_p"].to_numpy(), 0.10)
    t["halves_ok"] = (t["is_half1_mean_pct"] > 0) & (t["is_half2_mean_pct"] > 0)
    lo = t["id"].str.startswith(LONG_ONLY_PREFIX)
    t["bench_ok"] = ~lo | ((t["vs_bench_mean_pct"] > 0) & (t["vs_bench_half1_pct"] > 0) & (t["vs_bench_half2_pct"] > 0))
    t["is_pass"] = t["bh_pass"] & (t["is_mean_day_pct"] > 0) & t["halves_ok"] & t["bench_ok"]
    t["cf_ok"] = (t["cf_mean_day_pct"] > 0) & (~lo | (t["cf_vs_bench_mean_pct"] > 0))
    t["candidate"] = t["is_pass"] & t["cf_ok"]
    return t


def run() -> None:
    close, qvol = load()
    print("symbols", close.shape[1], "days", close.shape[0], close.index.min(), close.index.max(), flush=True)
    t = evaluate(close, qvol)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    t.to_csv(os.path.join(out, "results.csv"), index=False)
    pd.set_option("display.width", 250)
    print(t.T.to_string())


def selftest() -> None:
    rng = np.random.default_rng(0)
    idx = pd.date_range("2021-01-01", "2026-08-31", freq="D")
    syms = [f"C{i}USDT" for i in range(60)]
    ret = rng.normal(0, 0.03, (len(idx), len(syms)))
    close = pd.DataFrame(100 * np.cumprod(1 + ret, axis=0), index=idx, columns=syms)
    close.iloc[:400, 50:] = np.nan  # late listings
    close.iloc[1500:, 5] = np.nan  # a delisting
    qvol = pd.DataFrame(rng.uniform(1e6, 1e8, close.shape), index=idx, columns=syms).where(close.notna())
    u = universe_at(close, qvol, 300, 50)
    assert len(u) == 50 and not any(s in u for s in syms[50:]), "late listings must be excluded"
    assert "C5USDT" not in universe_at(close, qvol, 1600, 50)
    w = weights(close, qvol, "ls", 20, 7, None)
    assert abs(w.iloc[-1].sum()) < 1e-9 and abs(w.iloc[-1].abs().sum() - 1) < 1e-9
    # No lookahead: weights up to day d do not change when later data is removed.
    w2 = weights(close.iloc[:1000], qvol.iloc[:1000], "ls", 20, 7, None)
    assert np.allclose(w.iloc[:1000].to_numpy(), w2.to_numpy())
    p = portfolio(close, w)
    assert np.isfinite(p).all()
    t = evaluate(close, qvol)
    assert len(t) == len(STRATEGIES)
    print("selftest ok", len(STRATEGIES), "strategies")


if __name__ == "__main__":
    selftest() if sys.argv[1] == "selftest" else run()
