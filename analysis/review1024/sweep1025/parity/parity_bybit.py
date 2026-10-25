"""Parity: the draft config (combo.short5-down.json) run through the live bot's own code (paperbot/livereplay.replay_day:
ComboRunner + ComboEngine, research members computing their own signals) over 10/06-10/24 KST on the research 1m grid,
and compared trade by trade with the sweep's simulation of the same members (s4_combo: A gated to the down regime)."""
import os, sys, json, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "/home/user/crypto-bot-research"
sys.path.insert(0, REPO)
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import grid, COINS, ms, MIN, T0                      # noqa: E402
from paperbot import livereplay as LR                              # noqa: E402

IV = {"1m": 1, "5m": 5, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


class GridMarket:
    """Market protocol over the research 1m grid (+ live_bars extension): closed klines of any interval aggregated from
    1m, mark = last price, funding from the grid, no open interest."""

    def __init__(self):
        self.g = {c: grid(c) for c in COINS}
        self.calls = 0

    def klines(self, symbol, interval, start, end):
        self.calls += 1
        g = self.g[symbol]; k = IV[interval]
        i0 = max(int((start - T0) // MIN), 0); i0 -= i0 % k
        i1 = min(int((end - T0) // MIN) + k, g["n"]); i1 -= i1 % k
        if i1 <= i0:
            return []
        o = g["o"][i0:i1].reshape(-1, k)[:, 0]; c = g["c"][i0:i1].reshape(-1, k)[:, -1]
        h = np.nanmax(g["h"][i0:i1].reshape(-1, k), axis=1); l = np.nanmin(g["l"][i0:i1].reshape(-1, k), axis=1)
        v = np.nansum(g["v"][i0:i1].reshape(-1, k), axis=1)
        ts = T0 + np.arange(i0, i1, k, dtype=np.int64) * MIN
        ok = np.isfinite(o) & np.isfinite(c) & (ts >= start) & (ts <= end)
        return [[int(a), float(b), float(cc), float(d), float(e), float(f)] for a, b, cc, d, e, f in
                zip(ts[ok], o[ok], h[ok], l[ok], c[ok], v[ok])]

    def mark_klines(self, symbol, start, end):
        return [r[:5] for r in self.klines(symbol, "1m", start, end)]

    def funding(self, symbol, start, end):
        g = self.g[symbol]; i0 = max(int((start - T0) // MIN), 0); i1 = min(int((end - T0) // MIN), g["n"])
        f = g["fund"][i0:i1]; idx = np.flatnonzero(np.nan_to_num(f) != 0)
        return [(int(T0 + (i0 + i) * MIN), float(f[i])) for i in idx]

    def oi(self, symbol, start, end):
        return []

    def specs(self, symbols):
        return LR.file_specs(symbols)

    def brackets(self, cfg):
        return LR.file_brackets(list(cfg.symbols))


if __name__ == "__main__":
    cfg = json.load(open(os.path.join(HERE, "..", "draft_combo.short5-down.json")))
    w0 = ms("2026-10-05 15:00"); w1 = ms("2026-10-24 14:00"); now = ms("2026-10-24 14:12")
    t0 = time.time()
    res = LR.replay_day(cfg, GridMarket(), w0, w1, now_ms=now + 2 * MIN, tail_ms=0, taker_fee=0.000441,
                        log=lambda s: print(f"[{time.time() - t0:5.0f}s] {s}", flush=True))
    out = res.to_dict()
    json.dump(out, open(os.path.join(HERE, "parity_replay_bybit.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("trades", len(res.trades), "errors", res.errors[:5], "notes", res.notes, "minutes", res.minutes, flush=True)
