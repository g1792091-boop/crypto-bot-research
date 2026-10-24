"""Shared pieces of the combinations review: window splits, coin-flip side baselines, market-removed numbers and
separate-wallet paths. See cb_combos.py for the usage."""
from __future__ import annotations

import numpy as np
import pandas as pd

import cb_lib as L

RNG = np.random.default_rng(L.SEED)
N_RAND_SETS = 2000
N_RAND_MERGED = 1000
N_FLIP = 300
KS = (1, 2, 3, 5, 10)
MIN_PICK_TRADES = 3
MIN_PICK_SIGNALS = 5
OWNERS6 = [("V39_ALL", "1h"), ("OBV_S", "30m"), ("N24_DMI", "30m"), ("N05_PSAR_POC", "30m"),
           ("S3_CMO_SANDWICH", "30m"), ("OBV_S", "4h")]
GOAL_X, GOAL_DAYS = 6.0, 30


# ============================================================================================== periods and splits
class Split:
    """A way to cut a window [a, b) into a pick part and a test part.
    half  : pick = trades entered and closed before the middle; test = trades entered after the middle.
    altE  : pick = trades entered on even UTC days (KST 09:00 to 09:00), test = odd days.  altO: the reverse.
    """

    def __init__(self, name: str, a: int, b: int):
        self.name, self.a, self.b = name, int(a), int(b)
        self.mid = (self.a + self.b) // 2

    def masks(self, entry, exit_):
        entry = np.asarray(entry, np.int64)
        exit_ = np.asarray(exit_, np.float64)
        inside = (entry >= self.a) & (entry < self.b)
        if self.name == "half":
            return inside & (entry < self.mid) & (exit_ < self.mid), inside & (entry >= self.mid)
        par = (entry // L.DAY_MS) % 2
        p0 = 0 if self.name == "altE" else 1
        return inside & (par == p0), inside & (par != p0)

    def test_days(self) -> float:
        if self.name == "half":
            return (self.b - self.mid) / L.DAY_MS
        p0 = 0 if self.name == "altE" else 1
        tot, d = 0, (self.a // L.DAY_MS) * L.DAY_MS
        while d < self.b:
            lo, hi = max(d, self.a), min(d + L.DAY_MS, self.b)
            if (d // L.DAY_MS) % 2 != p0:
                tot += hi - lo
            d += L.DAY_MS
        return tot / L.DAY_MS

    def pick_days(self) -> float:
        return (self.b - self.a) / L.DAY_MS - self.test_days()

    def test_day_edges(self):
        """UTC day boundaries inside the test part (for daily returns)."""
        if self.name == "half":
            lo = self.mid
            edges = [lo] + [d for d in range((lo // L.DAY_MS + 1) * L.DAY_MS, self.b, L.DAY_MS)] + [self.b]
            return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1) if edges[i + 1] - edges[i] > 3_600_000]
        p0 = 0 if self.name == "altE" else 1
        out, d = [], (self.a // L.DAY_MS) * L.DAY_MS
        while d < self.b:
            lo, hi = max(d, self.a), min(d + L.DAY_MS, self.b)
            if (d // L.DAY_MS) % 2 != p0 and hi - lo > 3_600_000:
                out.append((lo, hi))
            d += L.DAY_MS
        return out


# ============================================================================================== market baselines
def side_baselines(sig: pd.DataFrame, trades: pd.DataFrame, split: Split, bot: str) -> dict:
    """Coin-flip baseline per side for the test part: what an entry of that side earned on average at the same kind
    of moment. rule: every replayed signal of the window part turned to that side (own result when the signal had that
    side, the opposite-side replay otherwise), per timeframe. league: the coin-twin accounts' trades per side."""
    out = {}
    if bot == "rule":
        _, te = split.masks(sig.bar_close, sig.exit_time.fillna(split.b))
        s = sig[te & sig.kind.isin(["strategy", "ds200", "random"])]
        for tf, g in s.groupby("tf"):
            long_r = np.where(g.side > 0, g.wallet_ret, g.f_wallet_ret)
            short_r = np.where(g.side < 0, g.wallet_ret, g.f_wallet_ret)
            out[("rule", tf, 1)] = float(np.nanmean(long_r))
            out[("rule", tf, -1)] = float(np.nanmean(short_r))
    else:
        c = trades[(trades.bot == "league") & trades.is_coin]
        _, te = split.masks(c.entry_time, c.exit_time)
        c = c[te]
        for sd in (1, -1):
            v = c[c.side == sd].wallet_ret
            out[("league", "*", sd)] = float(v.mean()) if len(v) else float("nan")
    return out


def market_numbers(rets, sides, tfs, bots, base: dict) -> dict:
    """Long/short split and market-removed numbers of a set of trades (wallet_ret units).
    excess  = mean over trades of (return - coin-flip baseline of the same side): skill beyond side and costs.
    neutral = excess + the average of the long and short baselines: the per-trade return in a market with no trend."""
    r = np.asarray(rets, float)
    sd = np.asarray(sides, int)
    if len(r) == 0:
        return {"n_long": 0, "n_short": 0, "mean_long": np.nan, "mean_short": np.nan, "excess": np.nan,
                "neutral": np.nan}
    b = np.array([base.get((bo, tf if bo == "rule" else "*", s), np.nan) for bo, tf, s in zip(bots, tfs, sd)])
    bn = np.array([np.nanmean([base.get((bo, tf if bo == "rule" else "*", 1), np.nan),
                               base.get((bo, tf if bo == "rule" else "*", -1), np.nan)]) for bo, tf in zip(bots, tfs)])
    ex = r - b
    return {"n_long": int((sd > 0).sum()), "n_short": int((sd < 0).sum()),
            "mean_long": float(r[sd > 0].mean()) if (sd > 0).any() else np.nan,
            "mean_short": float(r[sd < 0].mean()) if (sd < 0).any() else np.nan,
            "excess": float(np.nanmean(ex)), "neutral": float(np.nanmean(ex + bn))}


# ============================================================================================== paths
def path_from_events(events, t0: int, day_edges, weights=None):
    """events: list of (exit_time, member index, wallet_ret). Separate wallets, value = sum_k w_k * W_k.
    Returns final value, max drawdown, daily returns over day_edges."""
    if weights is None:
        weights = {}
    ev = sorted(events, key=lambda x: x[0])
    members = sorted({m for _, m, _ in ev} | set(weights))
    w = {m: weights.get(m, 1.0) for m in members}
    tot_w = sum(w.values()) or 1.0
    W = {m: 1.0 for m in members}
    V = 1.0 if not members else sum(w[m] * W[m] for m in members) / tot_w
    peak, mdd = V, 0.0
    times, vals = [t0], [V]
    for t, m, r in ev:
        old = W[m]
        W[m] = old * (1.0 + r)
        V += w[m] * (W[m] - old) / tot_w
        peak = max(peak, V)
        mdd = min(mdd, V / peak - 1.0)
        times.append(t)
        vals.append(V)
    times, vals = np.array(times), np.array(vals)
    daily = []
    for lo, hi in day_edges:
        i0 = int(np.searchsorted(times, lo, side="right")) - 1
        i1 = int(np.searchsorted(times, hi, side="right")) - 1
        v0, v1 = vals[max(i0, 0)], vals[max(i1, 0)]
        daily.append(v1 / v0 - 1.0)
    return float(V), float(mdd), daily




def sig_side_base(sig: pd.DataFrame, mask) -> dict:
    """Coin-flip side baseline from replayed signals selected by ``mask`` (see side_baselines)."""
    s = sig[np.asarray(mask) & sig.kind.isin(["strategy", "ds200", "random"]).to_numpy()]
    out = {}
    for tf, g in s.groupby("tf"):
        out[("rule", tf, 1)] = float(np.nanmean(np.where(g.side > 0, g.wallet_ret, g.f_wallet_ret)))
        out[("rule", tf, -1)] = float(np.nanmean(np.where(g.side < 0, g.wallet_ret, g.f_wallet_ret)))
    return out


# ============================================================================================== one-position engine
class Merged:
    """One wallet, one position at a time, over replayed signals. A signal is taken when the wallet is flat at its bar
    close; same-minute signals in the given priority order; a signal the house sizing rejects is passed over.
    The trade's result is its replay (exit time, wallet return at the house margin)."""

    def __init__(self, S: pd.DataFrame):
        self.S = S.reset_index(drop=True)
        self.bc = S.bar_close.to_numpy(np.int64)
        self.wr = S.wallet_ret.to_numpy(float)
        self.et = S.exit_time.to_numpy(float)
        self.fw = S.f_wallet_ret.to_numpy(float)
        self.fe = S.f_exit_time.to_numpy(float)
        self.side = S.side.to_numpy(int)

    def run(self, idx, flip=None):
        """idx: row indices already in priority order. Returns (final, taken rows, returns, sides, exit times)."""
        free = -1.0
        W = 1.0
        rows, rets, sides, exits = [], [], [], []
        for n, i in enumerate(idx):
            if self.bc[i] <= free:
                continue
            if flip is not None and flip[n]:
                r, e, sd = self.fw[i], self.fe[i], -self.side[i]
            else:
                r, e, sd = self.wr[i], self.et[i], self.side[i]
            if not np.isfinite(r) or not np.isfinite(e):
                continue
            W *= 1.0 + r
            free = e
            rows.append(i)
            rets.append(r)
            sides.append(sd)
            exits.append(e)
        return W, rows, rets, sides, exits


def daily_from_trades(exits, rets, t0, day_edges):
    """Daily returns of a single compounding wallet from its trades' exit times and returns."""
    ev = [(e, 0, r) for e, r in zip(exits, rets)]
    _, mdd, daily = path_from_events(ev, t0, day_edges, {0: 1.0})
    return mdd, daily


# ============================================================================================== frequency-matched draws
def buckets_by_count(counts: dict, groups: dict = None, q: int = 5) -> dict:
    """Bucket id per item: quintile of its pick-part trade (or signal) count, within its group (e.g. bot).
    Random picks drawn from the same buckets trade about as often as the real pick, so "it traded less, so it lost
    less fees" cannot pass as skill."""
    out = {}
    groups = groups or {k: "" for k in counts}
    by_g = {}
    for k in counts:
        by_g.setdefault(groups[k], []).append(k)
    for g, ks in by_g.items():
        v = np.array([counts[k] for k in ks], float)
        ranks = v.argsort().argsort() / max(len(v) - 1, 1)
        b = np.minimum((ranks * q).astype(int), q - 1)
        for k, bi in zip(ks, b):
            out[k] = f"{g}|{bi}"
    return out


def matched_draw(picked, bucket: dict, members_of: dict):
    """One random set: for every picked item, a random item from the same bucket (no repeats when possible)."""
    need = {}
    for p in picked:
        need[bucket[p]] = need.get(bucket[p], 0) + 1
    out = []
    for b, n in need.items():
        pool = members_of[b]
        if n <= len(pool):
            out += list(RNG.choice(pool, n, replace=False))
        else:
            out += list(RNG.choice(pool, n, replace=True))
    return out
