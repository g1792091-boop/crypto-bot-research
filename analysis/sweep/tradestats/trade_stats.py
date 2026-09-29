"""Descriptive trade statistics (win rate, payoff, PF, drawdown, long vs short) for every strategy x TF,
using the sweep's own signals, engine and costs. DESCRIPTIVE ONLY: not a gate, not used to select anything.
Exits: TIME_H (H=16 bars) and ATR_SL2_TP3 (stop 2 ATR / target 3 ATR, max 64 bars). One position per coin,
1x notional per trade, cost 0.14% round trip + funding 0.01%/8h. Splits: is / oos / final (cached signals)."""
import sys, os, glob, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); SW = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SW, "harness"))
import sweep_lib as L
import fg_indicators as fg

H = 16
EXITS = [e for e in L.exit_set(H) if e[0] in ("TIME_H", "ATR_SL2_TP3")]
SIGFILES = {"is": {"5m": "discover_g5m/out/signals_is_5m_sub*.npz", "15m": "discover_g15_30/out/signals_is_15m.npz",
                   "30m": "discover_g15_30/out/signals_is_30m.npz", "1h": "discover_g1h_4h_1d/out/signals_is_1h.npz",
                   "4h": "discover_g1h_4h_1d/out/signals_is_4h.npz", "1d": "discover_g1h_4h_1d/out/signals_is_1d.npz"}}
for sp in ("oos", "final"):
    SIGFILES[sp] = {tf: f"holdout/out/signals_{sp}_{tf}{'_sub*' if tf == '5m' else ''}.npz" for tf in L.TFS}

def mdd(x):
    c = np.cumsum(x); peak = np.maximum.accumulate(np.r_[0.0, c])[1:]
    return float((peak - c).max()) if len(c) else np.nan

def stats(tr, panel):
    if len(tr) == 0:
        return dict(trades=0)
    tr = tr.copy()
    tr["ets"] = [panel[s]["ts"].iloc[i] for s, i in zip(tr["symbol"], tr["entry_idx"])]
    tr = tr.sort_values("ets")
    net, gross = tr["net"].to_numpy(float), tr["gross"].to_numpy(float)
    w = net > 0; wg = gross > 0
    aw = net[w].mean() if w.any() else np.nan; al = net[~w].mean() if (~w).any() else np.nan
    lo, sh = tr["side"].to_numpy() > 0, tr["side"].to_numpy() < 0
    yrs = (tr["ets"].iloc[-1] - tr["ets"].iloc[0]).days / 365.25 or np.nan
    return dict(trades=len(tr), n_long=int(lo.sum()), n_short=int(sh.sum()), trades_per_year=len(tr) / yrs,
                win_rate=w.mean(), win_rate_gross=wg.mean(), avg_win=aw, avg_loss=al,
                payoff=abs(aw / al) if al and np.isfinite(al) else np.nan,
                pf_net=net[w].sum() / -net[~w].sum() if (~w).any() else np.inf,
                pf_gross=gross[wg].sum() / -gross[~wg].sum() if (~wg).any() else np.inf,
                exp_gross=gross.mean(), exp_net=net.mean(), cost_per_trade=(gross - net).mean(),
                sum_net=net.sum(), sum_gross=gross.sum(), mdd_net=mdd(net),
                exp_net_long=net[lo].mean() if lo.any() else np.nan, exp_net_short=net[sh].mean() if sh.any() else np.nan,
                exp_gross_long=gross[lo].mean() if lo.any() else np.nan, exp_gross_short=gross[sh].mean() if sh.any() else np.nan,
                coins_pos=int((tr.groupby("symbol")["net"].sum() > 0).sum()))

def run(tf):
    rows = []; global TR; TR = []
    for sp in ("is", "oos", "final"):
        panel = L.load_panel(tf, sp)
        sigs = {}
        for f in sorted(glob.glob(os.path.join(SW, SIGFILES[sp][tf]))):
            for k, v in L.load_signals(f).items():
                sigs.setdefault(k, {}).update(v)
        atrs = {c: fg.atr(df, 14).to_numpy(float) for c, df in panel.items()}
        windows = {}
        for c, df in panel.items():
            lo, hi = L.signal_window(df, tf, sp, 0)
            if hi - lo > 2 * L.EXIT_CAP_MULT * H + 4:
                windows[c] = (lo, hi)
        for name, dsig in sigs.items():
            res = L._run_exits_panel(panel, dsig, tf, sp, H, atrs, windows, 0, EXITS)
            for ex, tr in res.items():
                rows.append(dict(tf=tf, split=sp, strategy=name, exit=ex, **stats(tr, panel)))
                if len(tr):
                    t = tr[["symbol", "side", "entry_idx", "gross", "net", "hold", "reason"]].copy()
                    t["ets"] = [panel[s_]["ts"].iloc[i] for s_, i in zip(t["symbol"], t["entry_idx"])]
                    t = t.assign(tf=tf, split=sp, strategy=name, exit=ex)
                    TR.append(t)
        print(tf, sp, len(sigs), "strategies", flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(HERE, f"trade_stats_{tf}.csv"), index=False)
    pd.concat(TR, ignore_index=True).drop(columns=["entry_idx"]).to_csv(os.path.join(HERE, f"trades_{tf}.csv.gz"), index=False)

if __name__ == "__main__":
    run(sys.argv[1])
