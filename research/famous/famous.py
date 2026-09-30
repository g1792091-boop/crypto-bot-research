"""Well-known strategies not in the 37-strategy sweep (research/famous/PREREG_FAMOUS.md).

    python3 research/famous/famous.py selftest
    SWEEP_DATA=<rebuilt sweep data> python3 research/famous/famous.py run <out_dir>

Daily strategies use daily bars (UTC days). A position decided at day t's close earns day t+1's
close-to-close return. The volatility breakout uses 5-minute bars inside each UTC day.
"""

from __future__ import annotations

import json
import os
import re
import sys

import numpy as np
import pandas as pd

COINS = ["BTC", "ETH", "SOL", "LTC", "BCH", "DOGE", "XRP"]
TRADABLE = ["BTC", "ETH", "SOL", "LTC", "BCH", "DOGE"]  # XRP is record-only for the owners
SIDE_COST = 0.0005 + 0.0002  # taker fee + adverse slippage, per side
LONG_FUNDING_DAY = 0.0003  # 0.01% per 8h paid by longs; shorts receive nothing (conservative)
LONG_FUNDING_STAMP = 0.0001
IS = (pd.Timestamp("2021-08-01"), pd.Timestamp("2024-06-30"))
HALF = pd.Timestamp("2023-01-01")
CONF = (pd.Timestamp("2024-07-01"), pd.Timestamp("2026-09-28"))
BOOT = 10000

# Owners' rules at the base tier (20% margin x 20x): take profit at 10% net ROE, stop when the loss
# reaches 15% of the account = 3.75% adverse price move.
OWN_TP = 0.10 / 20 + 2 * SIDE_COST
OWN_SL = 0.15 / (0.20 * 20)
OWN_EXPOSURE = 0.20 * 20


# ------------------------------------------------------------------ data
def load_daily(root: str) -> dict[str, pd.DataFrame]:
    out = {}
    for c in COINS:
        d = pd.read_csv(os.path.join(root, "full", f"{c.lower()}usd-1d.csv"))
        d["date"] = pd.to_datetime(d["ts"], utc=True).dt.tz_localize(None).dt.normalize()
        out[c] = d.set_index("date")[["open", "high", "low", "close"]].astype(float)
    return out


def load_5m(root: str, coin: str) -> pd.DataFrame:
    d = pd.read_csv(os.path.join(root, "full", f"{coin.lower()}usd-5m.csv"))
    d["t"] = pd.to_datetime(d["ts"], utc=True).dt.tz_localize(None)
    d["date"] = d["t"].dt.normalize()
    return d[["t", "date", "open", "high", "low", "close"]]


# ------------------------------------------------------------------ positions (daily)
def donchian(d: pd.DataFrame, n: int, m: int) -> pd.Series:
    """Turtle-style: enter on a close beyond the prior n-day channel, exit on the prior m-day
    opposite channel. Position in {-1, 0, 1}, known at the day's close."""
    hi_n, lo_n = d["high"].rolling(n).max().shift(1), d["low"].rolling(n).min().shift(1)
    hi_m, lo_m = d["high"].rolling(m).max().shift(1), d["low"].rolling(m).min().shift(1)
    c = d["close"].to_numpy()
    pos = np.zeros(len(d))
    p = 0
    for i in range(len(d)):
        if np.isnan(hi_n.iat[i]) or np.isnan(hi_m.iat[i]):
            pos[i] = 0
            continue
        if p > 0 and c[i] < lo_m.iat[i]:
            p = 0
        elif p < 0 and c[i] > hi_m.iat[i]:
            p = 0
        if p <= 0 and c[i] > hi_n.iat[i]:
            p = 1
        elif p >= 0 and c[i] < lo_n.iat[i]:
            p = -1
        pos[i] = p
    return pd.Series(pos, index=d.index)


def weekly_mask(idx: pd.DatetimeIndex) -> np.ndarray:
    """Rebalance at Sunday's close (the position then applies from Monday)."""
    return (idx.dayofweek == 6)


def tsmom(d: pd.DataFrame, lb: int) -> pd.Series:
    r = d["close"] / d["close"].shift(lb) - 1
    sig = np.sign(r).where(weekly_mask(d.index))
    return sig.ffill().fillna(0)


def xs_positions(daily: dict, lb: int, mode: str) -> dict[str, pd.Series]:
    """Cross-sectional momentum over the tradable coins, weekly. mode 'top1': long the strongest
    coin if its lookback return > 0, else cash. mode 'ls2': long top 2, short bottom 2 (0.25 each)."""
    idx = daily[TRADABLE[0]].index
    for c in TRADABLE[1:]:
        idx = idx.intersection(daily[c].index)
    close = pd.DataFrame({c: daily[c]["close"].reindex(idx) for c in TRADABLE})
    r = close / close.shift(lb) - 1
    w = pd.DataFrame(np.nan, index=idx, columns=TRADABLE)
    wk = weekly_mask(idx)
    for i in np.flatnonzero(wk):
        row = r.iloc[i]
        if row.isna().any():
            continue
        order = row.sort_values(ascending=False).index
        x = pd.Series(0.0, index=TRADABLE)
        if mode == "top1":
            if row[order[0]] > 0:
                x[order[0]] = 1.0
        else:
            x[list(order[:2])] = 0.25
            x[list(order[-2:])] = -0.25
        w.iloc[i] = x
    w = w.ffill().fillna(0.0)
    return {c: w[c] for c in TRADABLE}


def daily_returns(d: pd.DataFrame, pos: pd.Series) -> pd.Series:
    """Net return earned on day t by the position held from day t-1's close."""
    r = d["close"].pct_change()
    held = pos.shift(1).fillna(0)
    turn = held.diff().abs().fillna(held.abs())
    return held * r - SIDE_COST * turn - LONG_FUNDING_DAY * held.clip(lower=0)


def spells(d: pd.DataFrame, pos: pd.Series) -> pd.DataFrame:
    """Holding spells for leverage tables: entry at the signal day's close, exit at the close of
    the last held day. MAE and the owners' TP/SL path use daily highs and lows (stop first)."""
    held = pos.shift(1).fillna(0).to_numpy()
    c, h, lo = (d[k].to_numpy() for k in ("close", "high", "low"))
    rows, i, n = [], 1, len(d)
    while i < n:
        if held[i] == 0:
            i += 1
            continue
        s, w, j = np.sign(held[i]), abs(held[i]), i
        while j + 1 < n and held[j + 1] == held[i]:
            j += 1
        entry = c[i - 1]
        adverse = (entry - lo[i:j + 1].min()) / entry if s > 0 else (h[i:j + 1].max() - entry) / entry
        ret = s * (c[j] / entry - 1) - 2 * SIDE_COST - (LONG_FUNDING_DAY * (j - i + 1) if s > 0 else 0)
        own = np.nan
        for k in range(i, j + 1):
            fav = (h[k] / entry - 1) if s > 0 else (1 - lo[k] / entry)
            adv = (1 - lo[k] / entry) if s > 0 else (h[k] / entry - 1)
            if adv >= OWN_SL:
                own = -OWN_SL - 2 * SIDE_COST
                break
            if fav >= OWN_TP:
                own = OWN_TP - 2 * SIDE_COST
                break
        if np.isnan(own):
            own = ret
        rows.append({"date": d.index[i], "side": s, "weight": w, "days": j - i + 1, "ret": ret,
                     "mae": adverse, "own_ret": own})
        i = j + 1
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ volatility breakout (5m)
def vol_breakout(d1: pd.DataFrame, m5: pd.DataFrame, k: float, sides: str, ma_filter: bool) -> pd.DataFrame:
    """Larry Williams volatility breakout per UTC day: trigger = day open +/- k x previous day's
    range; the first trigger touched is entered (both in one 5m bar: the worse of the two is
    taken); exit at the day's last 5m close. sides 'both' or 'long'. ma_filter: long only when the
    previous day's close is above its 5-day moving average (the common Korean variant)."""
    prev_rng = (d1["high"] - d1["low"]).shift(1)
    ma5_ok = (d1["close"] > d1["close"].rolling(5).mean()).shift(1).fillna(False).astype(bool)
    out = []
    for date, g in m5.groupby("date", sort=True):
        if date not in d1.index or np.isnan(prev_rng.get(date, np.nan)) or len(g) < 200:
            continue
        o = g["open"].iat[0]
        tl, ts = o + k * prev_rng[date], o - k * prev_rng[date]
        allow_short = sides == "both"
        allow_long = (not ma_filter) or bool(ma5_ok.get(date, False))
        hi, lo, op, cl = (g[x].to_numpy() for x in ("high", "low", "open", "close"))
        t = g["t"].to_numpy()
        hit_l = np.flatnonzero(hi >= tl) if allow_long else np.array([], int)
        hit_s = np.flatnonzero(lo <= ts) if allow_short else np.array([], int)
        il = hit_l[0] if len(hit_l) else None
        is_ = hit_s[0] if len(hit_s) else None
        if il is None and is_ is None:
            out.append({"date": date, "side": 0, "ret": 0.0, "mae": 0.0, "own_ret": 0.0})
            continue
        cands = []
        for side, idx, trig in ((1, il, tl), (-1, is_, ts)):
            if idx is None:
                continue
            fill = max(trig, op[idx]) if side > 0 else min(trig, op[idx])
            entry = fill * (1 + side * 0.0002)
            exit_ = cl[-1] * (1 - side * 0.0002)
            ret = side * (exit_ / entry - 1) - 2 * 0.0005
            h0 = pd.Timestamp(t[idx]).hour
            stamps = int(h0 < 8) + int(h0 < 16)  # funding at 08:00 and 16:00 UTC while held
            ret -= LONG_FUNDING_STAMP * stamps if side > 0 else 0
            path_hi, path_lo = hi[idx:], lo[idx:]
            adverse = (entry - path_lo.min()) / entry if side > 0 else (path_hi.max() - entry) / entry
            own = ret
            for a, b in zip(path_hi, path_lo):
                fav = (a / entry - 1) if side > 0 else (1 - b / entry)
                adv = (1 - b / entry) if side > 0 else (a / entry - 1)
                if adv >= OWN_SL:
                    own = -OWN_SL - 2 * SIDE_COST
                    break
                if fav >= OWN_TP:
                    own = OWN_TP - 2 * SIDE_COST
                    break
            cands.append((idx, side, ret, adverse, own))
        cands.sort(key=lambda x: (x[0], x[2]))  # earliest; same bar -> the worse return first
        idx, side, ret, adverse, own = cands[0]
        out.append({"date": date, "side": side, "ret": ret, "mae": adverse, "own_ret": own})
    return pd.DataFrame(out).set_index("date")


# ------------------------------------------------------------------ statistics
def window(s: pd.Series, a: pd.Timestamp, b: pd.Timestamp) -> pd.Series:
    return s[(s.index >= a) & (s.index <= b)]


def boot_p(x: pd.Series, seed: int) -> float:
    """One-sided p for mean > 0: resample calendar months with replacement, centred under the null."""
    x = x.dropna()
    months = x.groupby(x.index.to_period("M"))
    sums = months.sum().to_numpy()
    counts = months.size().to_numpy()
    mu = x.mean()
    rng = np.random.default_rng(seed)
    k = len(sums)
    idx = rng.integers(0, k, size=(BOOT, k))
    bs = (sums[idx] - mu * counts[idx]).sum(1) / counts[idx].sum(1)
    return float((bs >= mu).mean())


def bh(p: np.ndarray, q: float) -> np.ndarray:
    n = len(p)
    order = np.argsort(p)
    ok = p[order] <= q * np.arange(1, n + 1) / n
    kmax = np.max(np.flatnonzero(ok)) + 1 if ok.any() else 0
    out = np.zeros(n, bool)
    out[order[:kmax]] = True
    return out


def summarize(port: pd.Series) -> dict:
    x = port.dropna()
    eq = (1 + x).cumprod()
    dd = float((eq / eq.cummax() - 1).min()) if len(eq) else np.nan
    return {"days": len(x), "mean_day_pct": 100 * x.mean(), "ann_ret_pct": 100 * ((1 + x).prod() ** (365 / max(len(x), 1)) - 1),
            "sharpe": float(x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else np.nan, "max_dd_pct": 100 * dd}


# ------------------------------------------------------------------ run
STRATEGIES = [
    # id, family, description
    ("A1_turtle20", "daily", "Donchian 20/10, long+short"),
    ("A1_turtle55", "daily", "Donchian 55/20, long+short"),
    ("A2_tsmom7", "daily", "7-day time-series momentum, weekly, long+short"),
    ("A2_tsmom28", "daily", "28-day time-series momentum, weekly, long+short"),
    ("A3_rot7", "xs", "strongest coin by 7-day return, long only, weekly"),
    ("A3_rot28", "xs", "strongest coin by 28-day return, long only, weekly"),
    ("A4_ls7", "xs", "long top 2 / short bottom 2 by 7-day return, weekly"),
    ("A4_ls28", "xs", "long top 2 / short bottom 2 by 28-day return, weekly"),
    ("B1_vb_both", "vb", "volatility breakout k=0.5, long+short, exit at day close"),
    ("B2_vb_long", "vb", "volatility breakout k=0.5, long only"),
    ("B3_vb_long_ma5", "vb", "volatility breakout k=0.5, long only, previous close above MA5"),
]
LONG_ONLY = {"A3_rot7", "A3_rot28", "B2_vb_long", "B3_vb_long_ma5"}


def run(out: str) -> None:
    root = os.environ["SWEEP_DATA"]
    os.makedirs(out, exist_ok=True)
    daily = load_daily(root)
    per_coin, sp = {}, {}
    for sid, fam, _ in STRATEGIES:
        per_coin[sid], sp[sid] = {}, []
        if fam == "daily":
            for c in COINS:
                d = daily[c]
                if sid.startswith("A1"):
                    n, m = (20, 10) if sid.endswith("20") else (55, 20)
                    pos = donchian(d, n, m)
                else:
                    pos = tsmom(d, int(sid.split("tsmom")[1]))
                per_coin[sid][c] = daily_returns(d, pos)
                sp[sid].append(spells(d, pos).assign(coin=c))
        elif fam == "xs":
            lb = int(re.findall(r"\d+", sid.split("_")[1])[0])
            w = xs_positions(daily, lb, "top1" if sid.startswith("A3") else "ls2")
            for c in TRADABLE:
                d = daily[c].reindex(w[c].index)
                per_coin[sid][c] = daily_returns(d, w[c])
                sp[sid].append(spells(d, w[c]).assign(coin=c))
    vb = {"B1_vb_both": ("both", False), "B2_vb_long": ("long", False), "B3_vb_long_ma5": ("long", True)}
    for c in COINS:
        m5 = load_5m(root, c)
        for sid, (sides, maf) in vb.items():
            t = vol_breakout(daily[c], m5, 0.5, sides, maf)
            per_coin[sid][c] = t["ret"]
            sp[sid].append(t[t["side"] != 0].reset_index().assign(coin=c, weight=1.0, days=1))
        print("vb", c, flush=True)
    # Benchmarks for long-only strategies.
    bench = {}
    ew = pd.concat({c: daily[c]["close"].pct_change() for c in TRADABLE}, axis=1).mean(1)
    bench["A3"] = ew - LONG_FUNDING_DAY
    oc = {}
    for c in COINS:
        d = daily[c]
        oc[c] = d["close"] / d["open"] - 1 - 2 * SIDE_COST - 2 * LONG_FUNDING_STAMP
    bench["B"] = pd.concat(oc, axis=1)

    rows = []
    for k, (sid, fam, desc) in enumerate(STRATEGIES):
        pc = pd.concat(per_coin[sid], axis=1)
        port = pc.sum(1) if fam == "xs" else pc.mean(1)
        isw = window(port, *IS)
        r = {"id": sid, "desc": desc, **{f"is_{a}": b for a, b in summarize(isw).items()},
             "is_p": boot_p(isw, 1000 + k),
             "is_half1_mean_pct": 100 * isw[isw.index < HALF].mean(),
             "is_half2_mean_pct": 100 * isw[isw.index >= HALF].mean()}
        if fam != "xs":
            cm = window(pc, *IS).mean()
            r["coins_pos"] = int((cm > 0).sum())
            r["coin_mean_pct"] = json.dumps({c: round(100 * v, 4) for c, v in cm.items()})
        else:
            r["coins_pos"] = np.nan
        if sid in LONG_ONLY:
            if fam == "xs":
                b = window(bench["A3"], *IS)
            else:
                active = pc.notna()
                b = window(bench["B"].where(active).mean(1), *IS)
            diff = (isw - b.reindex(isw.index)).dropna()
            r["vs_bench_mean_pct"] = 100 * diff.mean()
            r["vs_bench_half1_pct"] = 100 * diff[diff.index < HALF].mean()
            r["vs_bench_half2_pct"] = 100 * diff[diff.index >= HALF].mean()
        cw = window(port, *CONF)
        r.update({f"conf_{a}": b for a, b in summarize(cw).items()})
        if fam != "xs":
            r["conf_coins_pos"] = int((window(pc, *CONF).mean() > 0).sum())
        # Leverage tables (descriptive): per spell, margin ROE at leverage L; liquidation when
        # the adverse move reaches 1/L - 0.5%.
        s = pd.concat(sp[sid], ignore_index=True)
        s = s[(s["date"] >= IS[0]) & (s["date"] <= CONF[1])]
        r["spells"] = len(s)
        r["spell_win_pct"] = 100 * (s["ret"] > 0).mean()
        for L in (1, 3, 5, 10, 20):
            liq = s["mae"] >= (1 / L - 0.005)
            roe = np.where(liq, -1.0, np.maximum(L * s["ret"], -1.0))
            r[f"liq_rate_{L}x"] = 100 * liq.mean()
            r[f"roe_mean_{L}x_pct"] = 100 * roe.mean()
        r["owners_rules_mean_acct_pct"] = 100 * OWN_EXPOSURE * s["own_ret"].mean()
        r["owners_rules_win_pct"] = 100 * (s["own_ret"] > 0).mean()
        rows.append(r)
        pc.to_pickle(os.path.join(out, f"daily_{sid}.pkl"))
        s.to_pickle(os.path.join(out, f"spells_{sid}.pkl"))
    t = pd.DataFrame(rows)
    t["bh_pass"] = bh(t["is_p"].to_numpy(), 0.10)
    t["coins_ok"] = t["coins_pos"].isna() | (t["coins_pos"] >= 4)
    t["halves_ok"] = (t["is_half1_mean_pct"] > 0) & (t["is_half2_mean_pct"] > 0)
    lo = t["id"].isin(LONG_ONLY)
    t["bench_ok"] = ~lo | ((t["vs_bench_mean_pct"] > 0) & (t["vs_bench_half1_pct"] > 0) & (t["vs_bench_half2_pct"] > 0))
    t["is_pass"] = t["bh_pass"] & (t["is_mean_day_pct"] > 0) & t["coins_ok"] & t["halves_ok"] & t["bench_ok"]
    t["conf_ok"] = (t["conf_mean_day_pct"] > 0) & (t["conf_coins_pos"].isna() | (t["conf_coins_pos"] >= 4))
    t["candidate"] = t["is_pass"] & t["conf_ok"]
    rdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(rdir, exist_ok=True)
    t.to_csv(os.path.join(rdir, "results.csv"), index=False)
    pd.set_option("display.width", 250)
    print(t.drop(columns=["coin_mean_pct"]).T.to_string())


# ------------------------------------------------------------------ self-test (synthetic data only)
def selftest() -> None:
    idx = pd.date_range("2021-01-01", periods=400, freq="D")
    up = pd.DataFrame({"open": np.arange(400) + 100.0, "close": np.arange(400) + 100.5}, index=idx)
    up["high"], up["low"] = up["close"] + 0.2, up["open"] - 0.2
    pos = donchian(up, 20, 10)
    assert pos.iloc[25:].eq(1).all(), "steady uptrend must be long"
    r = daily_returns(up, pos)
    assert r.iloc[30:].gt(0).all()
    tp = tsmom(up, 7)
    assert tp.iloc[20:].eq(1).all()
    s = spells(up, pos)
    assert len(s) == 1 and s["side"].iat[0] == 1
    # Volatility breakout on a day that rises through the trigger and closes at the high.
    d1 = pd.DataFrame({"open": [100.0, 100.0], "high": [102.0, 105.0], "low": [98.0, 99.9],
                       "close": [100.0, 105.0]}, index=pd.to_datetime(["2022-01-01", "2022-01-02"]))
    t = pd.date_range("2022-01-02", periods=288, freq="5min")
    px = np.linspace(100, 105, 288)
    m5 = pd.DataFrame({"t": t, "date": t.normalize(), "open": px, "high": px + 0.01, "low": px - 0.01, "close": px})
    v = vol_breakout(d1, m5, 0.5, "both", False)
    assert v["side"].iat[0] == 1 and v["ret"].iat[0] > 0.02, v
    x = pd.Series(np.r_[np.full(300, 0.001), np.full(300, -0.001)], index=pd.date_range("2022-01-01", periods=600))
    assert boot_p(x.iloc[:300] + np.random.default_rng(0).normal(0, 0.01, 300), 1) < 0.5
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1] == "selftest":
        selftest()
    else:
        run(sys.argv[2])
