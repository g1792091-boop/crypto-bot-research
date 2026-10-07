"""Crash-day replays: every signal of the 36 locked strategies entered on the crash day (UTC) and in the 24 h before
(positions open into the crash), 15m/30m/1h/4h, six coins, house exit at fixed 20/30/40/50x (profiles._scan, as s2).
Nominal fill = the engine's (stop price, or the open when a bar gaps through). Pessimistic fill = the extreme of the 5m
bar in which the stop price is first crossed (a stop-market order slipping to the worst print of that 5 minutes).
Loss per trade as % of equity: risk rule r: r * R * d / loss_per_notional; margin rule: L^2/100 * R * d; floored at
-margin (isolated: a fill beyond the liquidation price is a liquidation that loses the whole margin).
One-position traders (per strategy x tf, greedy, coin order) over the 48 h window: summed % equity per rule.

    python3 -I -B s4_crash.py <workdir> <signals_dir> <out_dir>
"""
import importlib.util
import os
import sys

sys.dont_write_bytecode = True
WD = sys.argv[1]
sys.path.insert(0, WD)
sys.path.append('/root/.local/lib/python3.11/site-packages')
REPO = '/home/user/crypto-bot-research'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'research', 'paper_rules'))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import common as C  # noqa: E402

spec = importlib.util.spec_from_file_location('profiles_ro', os.path.join(REPO, 'research', 'strategy_profiles', 'profiles.py'))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
RB = P.RB
from paperbot import sweepsig  # noqa: E402

SIG, OUT = sys.argv[2], sys.argv[3]
DAYS = ["2021-05-19", "2022-06-13", "2022-11-08", "2022-11-09", "2024-08-05", "2025-10-10"]
TFS = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
COINS = RB.COINS
NS_MIN = 60 * 10**9
LEVS = (20, 30, 40, 50)
SLIP = RB.SETTINGS.slippage_frac


def bars(tf, coin):
    z = np.load(os.path.join(SIG, f"sig_{tf}_{coin}.npz"))
    return z, {k: z[k] for k in ("ts", "o", "h", "l", "c", "atr")}


def market_rows(day):
    t0 = pd.Timestamp(day).value
    t1 = t0 + 86400 * 10**9
    rows = []
    for coin in COINS:
        _, b5 = bars("5m", coin)
        s = (b5["ts"] >= t0) & (b5["ts"] < t1)
        if not s.any():
            continue
        o, h, lo, c = b5["o"][s], b5["h"][s], b5["l"][s], b5["c"][s]
        r = dict(day=day, coin=coin, day_low_vs_open=lo.min() / o[0] - 1, day_high_vs_open=h.max() / o[0] - 1,
                 max_5m_range=((h - lo) / o).max(), max_5m_drop=((lo - o) / o).min(), max_5m_rise=((h - o) / o).max())
        for tf in TFS:
            _, b = bars(tf, coin)
            st = (b["ts"] >= t0) & (b["ts"] < t1)
            if st.any():
                rng = (b["h"][st] - b["l"][st]) / b["atr"][np.nonzero(st)[0] - 1]
                r[f"max_bar_range_atr_{tf}"] = np.nanmax(rng)
                r[f"atr_pct_{tf}_before"] = b["atr"][np.nonzero(st)[0][0] - 1] / b["c"][np.nonzero(st)[0][0] - 1]
        rows.append(r)
    return rows


def pessimistic_exit(b5, ts_entry, ts_exit_bar, tf_min, side, stop_px):
    """Worst 5m print inside the tf exit bar after the stop price is crossed (or the stop itself if none)."""
    t0 = ts_exit_bar
    t1 = ts_exit_bar + tf_min * NS_MIN
    i0, i1 = np.searchsorted(b5["ts"], [t0, t1])
    lo, hi = b5["l"][i0:i1], b5["h"][i0:i1]
    if side == 1:
        hit = np.nonzero(lo <= stop_px)[0]
        return lo[hit[0]] if len(hit) else stop_px
    hit = np.nonzero(hi >= stop_px)[0]
    return hi[hit[0]] if len(hit) else stop_px


def signal_rows(day):
    t0 = pd.Timestamp(day).value - 86400 * 10**9
    t1 = pd.Timestamp(day).value + 86400 * 10**9
    L = sweepsig.lib()
    rows = []
    for tf, tm in TFS.items():
        for coin in COINS:
            z, b = bars(tf, coin)
            _, b5 = bars("5m", coin)
            n = len(b["ts"])
            f_bar = RB.FUNDING_8H * tm / 480.0
            ck = C.coin_key(coin)
            for key in (k for k in z.files if k.startswith("s__")):
                sg = z[key]
                ent_ts = b["ts"] + tm * NS_MIN
                idx = np.nonzero((sg != 0) & (ent_ts >= t0) & (ent_ts < t1))[0]
                idx = idx[(idx + 1 < n) & np.isfinite(b["atr"][idx]) & (b["atr"][idx] > 0)]
                if not len(idx):
                    continue
                side = sg[idx].astype(int)
                raw = b["o"][idx + 1]
                atr = b["atr"][idx]
                fill = raw * (1 + side * SLIP)
                d = (raw * SLIP + 2 * atr) / fill
                a = atr / fill
                stop0 = raw - side * 2 * atr
                for Lv in LEVS:
                    mM = C.margin_rule(ck, side, d, a, Lv)
                    mK = C.risk_rule(ck, side, d, a, Lv, 0.02)
                    for mode, m in (("M", mM), ("K", mK)):
                        liq = np.clip(m["liq"], 1e-6, None)
                        r = P._scan(b, idx, side, np.full(len(idx), float(Lv)), liq, 4096, n, f_bar)
                        for j in range(len(idx)):
                            if not r["done"][j]:
                                continue
                            ret = r["roe"][j] / Lv
                            R = ret / d[j]
                            ex_bar_ts = b["ts"][idx[j] + int(r["held"][j])]
                            stopped_at_initial = r["reason"][j] == 0
                            pess_R = R
                            if stopped_at_initial:
                                px = pessimistic_exit(b5, ent_ts[idx[j]], ex_bar_ts, tm, side[j], stop0[j])
                                ex = px * (1 - side[j] * SLIP)
                                pr = side[j] * (ex / fill[j] - 1) - C.TAKER * (1 + ex / fill[j])
                                pess_R = max(pr, -1.0 / Lv) / d[j]
                            rows.append(dict(day=day, tf=tf, coin=coin, strategy=key[3:], ts=int(b["ts"][idx[j]]),
                                             ent=int(ent_ts[idx[j]]), ex=int(ex_bar_ts + tm * NS_MIN), side=side[j],
                                             d=d[j], L=Lv, mode=mode, ok=bool(m["ok"][j]), R=R, pess_R=pess_R,
                                             reason=int(r["reason"][j]), liq_frac=liq[j]))
    return pd.DataFrame(rows)


def loss_pct(df, R):
    lpn = C.loss_per_notional(df.d.values, df.side.values)
    if (df["mode"].values == "K").all():
        return 0.02 * R * df.d.values / lpn
    return (df.L.values ** 2 / 100.0) * R * df.d.values


def main():
    os.makedirs(OUT, exist_ok=True)
    mk, sg = [], []
    for day in DAYS:
        mk += market_rows(day)
        sg.append(signal_rows(day))
        print(day, flush=True)
    pd.DataFrame(mk).to_csv(os.path.join(OUT, "s4_crash_market.csv"), index=False)
    S = pd.concat(sg, ignore_index=True)
    # % equity per trade: risk 2% (mode K) and margin L% (mode M), nominal and pessimistic, isolated floor
    for col, src in (("eqf", "R"), ("eqf_pess", "pess_R")):
        v = np.empty(len(S))
        for mode in ("K", "M"):
            s = S["mode"].values == mode
            v[s] = loss_pct(S[s], S[src].values[s])
        S[col] = v
    S.to_pickle(os.path.join(OUT, "s4_crash_signals.pkl"))
    # summaries: trades entered on the crash day itself and the 24 h before, executable at L only
    S["on_day"] = S.ent >= S.day.map(lambda x: pd.Timestamp(x).value)
    summ = []
    for (day, tf, mode, L), g in S[S.ok].groupby(["day", "tf", "mode", "L"]):
        summ.append(dict(day=day, tf=tf, mode=mode, L=L, n=len(g), sl_share=(g.reason == 0).mean(),
                         mean_R=g.R.mean(), worst_R=g.R.min(), worst_pess_R=g.pess_R.min(),
                         mean_eq=g.eqf.mean(), worst_eq=g.eqf.min(), worst_eq_pess=g.eqf_pess.min(),
                         liq_nominal=int((g.reason == 2).sum()),
                         liq_pess=int(((g.pess_R * g.d) <= -1.0 / g.L + 1e-12).sum())))
    summ = pd.DataFrame(summ)
    summ.to_csv(os.path.join(OUT, "s4_crash_summary.csv"), index=False)
    # one-position traders over the 48 h window, executable trades only, greedy in entry order
    order = {c: i for i, c in enumerate(COINS)}
    tr = []
    for (day, tf, mode, L, strat), g in S[S.ok].groupby(["day", "tf", "mode", "L", "strategy"]):
        g = g.assign(pr=g.coin.map(order)).sort_values(["ent", "pr"])
        free = -1
        tot, totp, n = 0.0, 0.0, 0
        for r in g.itertuples():
            if r.ent < free:
                continue
            tot += r.eqf
            totp += r.eqf_pess
            n += 1
            free = r.ex
        tr.append(dict(day=day, tf=tf, mode=mode, L=L, strategy=strat, n=n, sum_eq=tot, sum_eq_pess=totp))
    tr = pd.DataFrame(tr)
    tr.to_csv(os.path.join(OUT, "s4_crash_traders.csv"), index=False)
    agg = tr.groupby(["day", "tf", "mode", "L"]).agg(traders=("strategy", "size"), trades=("n", "sum"),
                                                      med_sum=("sum_eq", "median"), worst_sum=("sum_eq", "min"),
                                                      worst_sum_pess=("sum_eq_pess", "min"),
                                                      share_lose10=("sum_eq_pess", lambda x: (x <= -0.10).mean()),
                                                      share_lose25=("sum_eq_pess", lambda x: (x <= -0.25).mean())
                                                      ).reset_index()
    agg.to_csv(os.path.join(OUT, "s4_crash_traders_agg.csv"), index=False)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(mk).round(4).to_string(index=False))
    print(summ.round(3).to_string(index=False))
    print(agg.round(3).to_string(index=False))


main()
