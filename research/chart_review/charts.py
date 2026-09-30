"""Blind chart review sample and charts (research/chart_review/PREREG_CHART.md).

    SWEEP_DATA=<rebuilt sweep data> python3 research/chart_review/charts.py <out_dir>

Writes, per strategy: trades_<S>.pkl (all selection-window trades), key_<S>.csv (the 60
sampled trade IDs with their results; NOT to be opened before the notes are committed),
and grid_<S>_NN.png (4 charts per image, prices only up to the signal bar).
"""

from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.gridspec import GridSpecFromSubplotSpec  # noqa: E402

TF, H, LOOKBACK, PER_CLASS = "15m", 16, 100, 30
STRATS = {"V45_AMB": "V45", "V39_ALL": "V39", "DOGE_L": "DOGE"}


def lib():
    from paperbot import sweepsig
    return sweepsig.lib()


def overlays(L, name, df):
    """Indicator series for the chart, per strategy (what each strategy uses)."""
    import pine_indicators as pi
    h, lo, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    out = {"price": {}, "p1": {}, "p2": {}, "p1_kind": "", "p2_kind": ""}
    if name in ("V45_AMB", "V39_ALL"):
        a, b = ((14, 6.0), (14, 3.0)) if name == "V45_AMB" else ((10, 3.0), (10, 6.0))
        l1, d1 = pi.exchange_supertrend(h, lo, c, a[0], a[1])
        l2, d2 = pi.exchange_supertrend(h, lo, c, b[0], b[1])
        out["price"] = {f"ST({a[0]},{a[1]:g})": (l1, d1), f"ST({b[0]},{b[1]:g})": (l2, d2)}
        _m, _s, hist = pi.pine_macd(c, 12, 26, 9)
        raw = pi.pine_stoch(c, h, lo, 14)
        k = pi.pine_sma(raw, 3 if name == "V45_AMB" else 4)
        d = pi.pine_sma(k, 3 if name == "V45_AMB" else 2)
        out["p1"], out["p1_kind"] = {"MACD hist": hist}, "hist"
        out["p2"], out["p2_kind"] = {"Stoch K": k, "Stoch D": d}, "osc"
    else:
        import doge_strategy as ds
        p = L.doge_params(TF)
        d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["ts"], utc=True)))[
            ["open", "high", "low", "close", "volume"]]
        ind = ds.compute_indicators(d, p)
        out["price"] = {k: (ind[k].to_numpy(float), None) for k in ("ema_short", "ema_fast", "ema_slow", "ema_trend")}
        out["p1"], out["p1_kind"] = {"StochRSI K": ind["K"].to_numpy(float), "StochRSI D": ind["D"].to_numpy(float)}, "osc"
        out["p2"], out["p2_kind"] = {"RSI": ind["rsi26"].to_numpy(float)}, "rsi"
    return out


def htf_trend(L, df):
    """1h supertrend(14,6) direction of the last 1h bar closed by each 15m bar's close."""
    import pine_indicators as pi
    dh = L.resample_ohlcv(df, "1h")
    _l, dirs = pi.exchange_supertrend(dh["high"].to_numpy(float), dh["low"].to_numpy(float),
                                      dh["close"].to_numpy(float), 14, 6.0)
    hclose = L.htf_close_ns(dh["ts"], "1h")
    cclose = L._utc_ns(df["ts"]) + np.timedelta64(15, "m")
    j = np.searchsorted(hclose, cclose, side="right") - 1
    return np.where(j >= 0, dirs[np.clip(j, 0, len(dirs) - 1)], 0)


def draw(ax_spec, fig, df, ov, htf, t, tid):
    i = int(t["signal_idx"])
    a = max(0, i - LOOKBACK)
    x = np.arange(a, i + 1)
    gs = GridSpecFromSubplotSpec(4, 1, subplot_spec=ax_spec, height_ratios=[3, 0.7, 1, 1], hspace=0.05)
    ax, axv, ax1, ax2 = (fig.add_subplot(gs[k]) for k in range(4))
    o, h, lo, c, v = (df[k].to_numpy(float)[a:i + 1] for k in ("open", "high", "low", "close", "volume"))
    up = c >= o
    ax.vlines(x, lo, h, color=np.where(up, "#26a69a", "#ef5350"), linewidth=0.7)
    ax.bar(x, np.abs(c - o) + 1e-12, bottom=np.minimum(o, c), color=np.where(up, "#26a69a", "#ef5350"), width=0.7)
    for k, (line, dirs) in ov["price"].items():
        seg = line[a:i + 1]
        ax.plot(x, seg, linewidth=0.9, label=k)
    side = int(t["side"])
    # sl_dist is a fraction of the entry price (2 ATR / entry).
    entry = float(t["entry_px"])
    atr = float(t["sl_dist"]) * entry / 2
    sl = entry - side * 2 * atr
    tp = entry + side * 3 * atr
    ax.axhline(entry, color="k", linewidth=0.8, linestyle="--")
    ax.axhline(sl, color="red", linewidth=0.8)
    ax.axhline(tp, color="green", linewidth=0.8)
    ax.annotate("LONG" if side > 0 else "SHORT", xy=(i, entry), xytext=(i + 1, entry),
                color="blue" if side > 0 else "purple", fontsize=8, fontweight="bold")
    ax.set_xlim(a - 1, i + 6)
    ymin = min(lo.min(), sl, tp); ymax = max(h.max(), sl, tp)
    ax.set_ylim(ymin - (ymax - ymin) * 0.03, ymax + (ymax - ymin) * 0.03)
    trend = {1: "UP", -1: "DOWN"}.get(int(htf[i]), "?")
    ts = pd.Timestamp(df["ts"].iloc[i])
    ax.set_title(f"{tid}  {t['symbol']}  {'LONG' if side > 0 else 'SHORT'}  1h trend: {trend}  "
                 f"{ts:%Y-%m}", fontsize=9)
    ax.legend(fontsize=6, loc="upper left")
    axv.bar(x, v, color="grey", width=0.7)
    for axx, kind, series in ((ax1, ov["p1_kind"], ov["p1"]), (ax2, ov["p2_kind"], ov["p2"])):
        for k, s in series.items():
            seg = s[a:i + 1]
            if kind == "hist":
                axx.bar(x, seg, color=np.where(seg >= 0, "#26a69a", "#ef5350"), width=0.7)
                axx.axhline(0, color="k", linewidth=0.5)
            else:
                axx.plot(x, seg, linewidth=0.8, label=k)
        if kind == "osc":
            for lvl in (20, 50, 80):
                axx.axhline(lvl, color="grey", linewidth=0.4)
            axx.set_ylim(-5, 105)
        if kind == "rsi":
            for lvl in (48, 52):
                axx.axhline(lvl, color="grey", linewidth=0.4)
        axx.legend(fontsize=6, loc="upper left")
        axx.set_xlim(a - 1, i + 6)
    for axx in (ax, axv, ax1):
        axx.set_xticks([])
    for axx in (ax, axv, ax1, ax2):
        axx.tick_params(labelsize=6)
    ax2.set_xticks([])


def main(out_dir: str) -> None:
    L = lib()
    import fg_indicators as fg
    os.makedirs(out_dir, exist_ok=True)
    panel = L.load_panel(TF, "is")
    ex = [e for e in L.exit_set(H) if e[0] == "ATR_SL2_TP3"]
    atrs = {c: fg.atr(df, 14).to_numpy(float) for c, df in panel.items()}
    windows = {}
    for c, df in panel.items():
        lo, hi = L.signal_window(df, TF, "is", 0)
        if hi - lo > 2 * L.EXIT_CAP_MULT * H + 4:
            windows[c] = (lo, hi)
    sigs = L.compute_signals(panel, TF, list(STRATS))
    htfs = {c: htf_trend(L, df) for c, df in panel.items()}
    for k, (name, short) in enumerate(STRATS.items()):
        tr = L._run_exits_panel(panel, sigs[name], TF, "is", H, atrs, windows, 0, ex)["ATR_SL2_TP3"]
        tr = tr.reset_index(drop=True)
        tr["entry_ts"] = [panel[s]["ts"].iloc[j] for s, j in zip(tr["symbol"], tr["entry_idx"])]
        tr.to_pickle(os.path.join(out_dir, f"trades_{short}.pkl"))
        rng = np.random.default_rng([20260930, k])
        wins = tr.index[tr["net"] > 0].to_numpy()
        losses = tr.index[tr["net"] <= 0].to_numpy()
        pick = np.concatenate([rng.choice(wins, PER_CLASS, replace=False),
                               rng.choice(losses, PER_CLASS, replace=False)])
        rng.shuffle(pick)
        key = tr.loc[pick, ["symbol", "signal_idx", "side", "net", "reason"]].copy()
        key.insert(0, "id", [f"{short}-{n + 1:02d}" for n in range(len(pick))])
        key["trade_row"] = pick
        key.to_csv(os.path.join(out_dir, f"key_{short}.csv"), index=False)
        ovs = {c: overlays(L, name, df) for c, df in panel.items()}
        for g in range(0, len(pick), 4):
            fig = plt.figure(figsize=(16, 11), dpi=80)
            outer = fig.add_gridspec(2, 2, wspace=0.12, hspace=0.18)
            for q, row in enumerate(pick[g:g + 4]):
                t = tr.loc[row]
                tid = key["id"].iloc[g + q]
                draw(outer[q // 2, q % 2], fig, panel[t["symbol"]], ovs[t["symbol"]], htfs[t["symbol"]], t, tid)
            fig.savefig(os.path.join(out_dir, f"grid_{short}_{g // 4 + 1:02d}.png"), bbox_inches="tight")
            plt.close(fig)
        print(f"{name}: {len(tr)} trades, {len(pick)} sampled, {len(pick) // 4} images", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
