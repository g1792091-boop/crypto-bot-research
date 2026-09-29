"""Part 2: empirical zero-edge baseline of the user's bracket on real IS paths.

Entry: market order at the OPEN of a random bar, both long and short at every sampled bar
       (so market drift cancels -> zero edge by construction).
Bracket: TP at +10% ROE (price distance 10%/L); stop = liquidation (no stop, worst case),
         or a stop-market at 1.0x / 0.5x the liquidation distance.
Path resolution: (a) the TF's own bars; (b) 5m bars for TF >= 15m (same entries).
Same-bar TP+stop touch: 'adv' = adverse first (conservative), 'fav' = favourable first.
Gaps: bar open beyond the stop -> filled at the open (worse); beyond TP -> filled at TP level.
Isolated margin: liquidation loses the whole margin (ROE -100%) plus the entry fee and funding.
Costs: taker 0.05% + slippage 0.02% per market fill (0.14% round trip); variant: TP exit as maker 0.02%.
Funding 0.01%/8h of notional, always a cost.  Max hold 90 days, then closed at market (timeout).
"""
import sys, json, time
import numpy as np
import pandas as pd
from common import *

RNG = np.random.default_rng(20260929)
N_SAMPLE_BARS = 40000          # sampled bars per TF (x2 directions) for 5m..1h
CAP_DAYS = 90
SD1 = json.load(open(f"{OUT}/sd_1bar.json"))
VARIANTS = ["liq", "stop1.0", "stop0.5"]


def series_list(tf):
    """[(sym, off, df)] -- 1d uses 4 day-anchors (00,06,12,18 UTC) built from 1h to get >=20k entries."""
    out = []
    for sym in COINS:
        if tf == "1d":
            for off in (0, 6, 12, 18):
                out.append((sym, off, daily_offset_from_1h(sym, off)))
        else:
            out.append((sym, 0, load(sym, tf)))
    return out


def check_1d_offset0():
    worst = 0.0
    for sym in COINS:
        a = load(sym, "1d")
        b = daily_offset_from_1h(sym, 0)
        m = a.merge(b, on="ts", suffixes=("", "_b"))
        for k in ["open", "high", "low", "close"]:
            worst = max(worst, float(np.max(np.abs(m[k] / m[k + "_b"] - 1))))
        assert len(m) >= len(a) - 2, (sym, len(a), len(b), len(m))
    return worst


def run_block(o, h, l, c, tsec, mx, mn, e, dirs, cap, tfmin):
    """Per-entry results for every (L, variant)."""
    n = len(o)
    P = o[e]
    lg = dirs == 1
    res = {}
    for L in LEVS:
        dl, tp = d_liq(L), tp_dist(L)
        for sfrac in (1.0, 0.5):
            ds = sfrac * dl
            up = np.where(lg, P * (1 + tp), P * (1 + ds))
            dn = np.where(lg, P * (1 - ds), P * (1 - tp))
            limit = e + cap
            j = first_hit(mx, mn, e, limit, up, dn)
            hit = j < limit
            jj = np.minimum(j, n - 1)
            hj, lj, oj = h[jj], l[jj], o[jj]
            up_t, dn_t = hj >= up, lj <= dn
            tp_t = np.where(lg, up_t, dn_t)
            st_t = np.where(lg, dn_t, up_t)
            later = jj > e
            gap_up, gap_dn = later & (oj >= up), later & (oj <= dn)
            gap_st = np.where(lg, gap_dn, gap_up)
            gap_tp = np.where(lg, gap_up, gap_dn)
            amb = hit & tp_t & st_t & ~gap_st & ~gap_tp
            tp_adv = hit & ~gap_st & (gap_tp | (tp_t & ~st_t))
            tp_fav = hit & ~gap_st & (gap_tp | tp_t)
            st_fill = np.where(lg, np.minimum(dn, oj), np.maximum(up, oj))
            r_st = np.where(lg, st_fill / P - 1, 1 - st_fill / P)
            px_st_rel = st_fill / P
            last = np.minimum(limit - 1, n - 1)
            to_px = c[last]
            r_to = np.where(lg, to_px / P - 1, 1 - to_px / P)
            hours = np.where(hit, (tsec[jj] - tsec[e]) / 3600 + 0.5 * tfmin / 60,
                             (tsec[last] - tsec[e]) / 3600 + tfmin / 60)
            fund = L * FUND_8H * hours / 8
            entry_cost = L * C_MKT
            px_tp_rel = np.where(lg, 1 + tp, 1 - tp)
            roe_tp_t = L * tp - entry_cost - L * C_MKT * px_tp_rel - fund
            roe_tp_m = L * tp - entry_cost - L * MAKER * px_tp_rel - fund
            roe_to = L * r_to - entry_cost - L * C_MKT * (to_px / P) - fund
            roe_liq = -1.0 - entry_cost - fund
            gap_liq = r_st < -dl - 1e-12
            for var in (["liq", "stop1.0"] if sfrac == 1.0 else ["stop0.5"]):
                is_liq_if_stop = np.ones_like(hit) if var == "liq" else gap_liq
                roe_st = np.where(is_liq_if_stop, roe_liq,
                                  L * r_st - entry_cost - L * C_MKT * px_st_rel - fund)
                r_stop_exit = np.where(is_liq_if_stop, -1.0 / L, r_st)
                rec = {"amb": amb, "entrybar": hit & (jj == e), "hours": hours, "hit": hit,
                       "bars": np.where(hit, jj - e + 1, cap)}
                for mode, tpm in (("adv", tp_adv), ("fav", tp_fav)):
                    out = np.where(~hit, 3, np.where(tpm, 0, np.where(is_liq_if_stop, 2, 1)))
                    rec[f"out_{mode}"] = out.astype(np.int8)
                    rec[f"roe_{mode}"] = np.where(out == 0, roe_tp_t, np.where(out == 3, roe_to, roe_st))
                    rec[f"roem_{mode}"] = np.where(out == 0, roe_tp_m, np.where(out == 3, roe_to, roe_st))
                    rec[f"rx_{mode}"] = np.where(out == 0, tp, np.where(out == 3, r_to, r_stop_exit))
                res[(L, var)] = rec
    return res


def cluster_se(x, g):
    xm = x.mean()
    s = pd.Series(x - xm).groupby(g).sum().values
    return float(np.sqrt((s ** 2).sum()) / len(x))


def aggregate(tf, reso, recs, groups, tfmin_tf):
    rows = []
    sd_bar = SD1[tf]
    bars_yr = 365 * 1440 / tfmin_tf
    for (L, var), r in recs.items():
        dl, tp = d_liq(L), tp_dist(L)
        ds = dl if var != "stop0.5" else 0.5 * dl
        row = dict(tf=tf, res=reso, L=L, variant=var, n=len(r["hours"]), tp_pct=100 * tp, stop_pct=100 * ds,
                   p0_brownian=ds / (tp + ds),
                   p_ambig=r["amb"].mean(), p_exit_entrybar=r["entrybar"].mean(),
                   med_hours=float(np.median(r["hours"])), mean_hours=float(r["hours"].mean()),
                   med_bars=float(np.median(r["bars"])), p_timeout=float((~r["hit"]).mean()))
        for mode in ("adv", "fav"):
            out, roe, roem, rx = r[f"out_{mode}"], r[f"roe_{mode}"], r[f"roem_{mode}"], r[f"rx_{mode}"]
            pt, ps, pl, po = [(out == k).mean() for k in range(4)]
            row.update({f"pTP_{mode}": pt, f"pSTOP_{mode}": ps, f"pLIQ_{mode}": pl, f"pTO_{mode}": po,
                        f"EROE_{mode}": roe.mean(), f"EROE_se_{mode}": cluster_se(roe, groups),
                        f"EROEmakerTP_{mode}": roem.mean(), f"Erx_{mode}": rx.mean()})
            W = roe[out == 0].mean() if pt > 0 else np.nan
            lossmask = (out == 1) | (out == 2)
            Lo = roe[lossmask].mean() if lossmask.any() else np.nan
            T = roe[out == 3].mean() if po > 0 else 0.0
            pstar = (-(1 - po) * Lo - po * T) / (W - Lo)
            row.update({f"winROE_{mode}": W, f"lossROE_{mode}": Lo, f"pstar_{mode}": pstar,
                        f"dp_{mode}": pstar - pt})
            dr = (pstar - pt) * (tp + ds)                     # extra mean signed price move at exit
            mu_h = dr / row["mean_hours"]
            snr_bar = mu_h * tfmin_tf / 60 / sd_bar
            row.update({f"req_drift_pct_{mode}": 100 * dr, f"req_snr_bar_{mode}": snr_bar,
                        f"req_ann_ir_{mode}": snr_bar * np.sqrt(bars_yr)})
            for M in MARGINS:
                row[f"Eeq_M{int(M*100)}_{mode}"] = M * roe.mean()
                row[f"Elog_M{int(M*100)}_{mode}"] = float(np.mean(np.log1p(M * roe)))
        rows.append(row)
    return rows


def main():
    t0 = time.time()
    print("1d offset-0 rebuilt from 1h vs official 1d file, max rel diff:", check_1d_offset0(), flush=True)
    all_rows = []
    entries_by_tf = {}
    for tf in TFS:
        tfmin = TF_MIN[tf]
        cap = int(CAP_DAYS * 1440 / tfmin)
        K = int(np.ceil(np.log2(cap + 1)))
        ser = series_list(tf)
        elig = np.array([max(0, len(df) - cap) for (_, _, df) in ser])
        tot = elig.sum()
        if tf in ("4h", "1d"):
            picks = [np.arange(m) for m in elig]
        else:
            flat = np.sort(RNG.choice(tot, size=N_SAMPLE_BARS, replace=False))
            bounds = np.r_[0, np.cumsum(elig)]
            picks = [flat[(flat >= bounds[i]) & (flat < bounds[i + 1])] - bounds[i] for i in range(len(ser))]
        recs, groups, ent = None, [], []
        for si, ((sym, off, df), eb) in enumerate(zip(ser, picks)):
            o, h, l, c = (df[k].values.astype(float) for k in ["open", "high", "low", "close"])
            tsec = df["ts"].values.astype("datetime64[s]").astype(np.int64)
            mx, mn = build_sparse(h, l, K)
            e = np.r_[eb, eb].astype(np.int64)
            dirs = np.r_[np.ones(len(eb)), -np.ones(len(eb))].astype(np.int8)
            r = run_block(o, h, l, c, tsec, mx, mn, e, dirs, cap, tfmin)
            if recs is None:
                recs = {k: {kk: [vv] for kk, vv in v.items()} for k, v in r.items()}
            else:
                for k, v in r.items():
                    for kk, vv in v.items():
                        recs[k][kk].append(vv)
            ci = COINS.index(sym)
            groups.append(ci * 100000 + tsec[e] // (7 * 86400))
            ent.append(pd.DataFrame({"sym": sym, "off": off, "ts": tsec[e], "dir": dirs}))
            del mx, mn
        recs = {k: {kk: np.concatenate(vv) for kk, vv in v.items()} for k, v in recs.items()}
        groups = np.concatenate(groups)
        entries_by_tf[tf] = pd.concat(ent, ignore_index=True)
        all_rows += aggregate(tf, tf, recs, groups, tfmin)
        print(f"{tf}: entries={len(groups)} cap_bars={cap} t={time.time()-t0:.0f}s", flush=True)

    # 5m-resolved paths for the same entries (TF >= 15m)
    cap5 = int(CAP_DAYS * 1440 / 5)
    K5 = int(np.ceil(np.log2(cap5 + 1)))
    recs5 = {tf: None for tf in TFS[1:]}
    grp5 = {tf: [] for tf in TFS[1:]}
    dropped = {tf: 0 for tf in TFS[1:]}
    for sym in COINS:
        df = load(sym, "5m")
        o, h, l, c = (df[k].values.astype(float) for k in ["open", "high", "low", "close"])
        tsec = df["ts"].values.astype("datetime64[s]").astype(np.int64)
        mx, mn = build_sparse(h, l, K5)
        for tf in TFS[1:]:
            en = entries_by_tf[tf]
            en = en[en["sym"] == sym]
            idx = np.searchsorted(tsec, en["ts"].values)
            ok = (idx < len(tsec)) & (tsec[np.minimum(idx, len(tsec) - 1)] == en["ts"].values) & (idx + cap5 <= len(tsec))
            dropped[tf] += int((~ok).sum())
            e = idx[ok].astype(np.int64)
            dirs = en["dir"].values[ok]
            r = run_block(o, h, l, c, tsec, mx, mn, e, dirs, cap5, 5)
            if recs5[tf] is None:
                recs5[tf] = {k: {kk: [vv] for kk, vv in v.items()} for k, v in r.items()}
            else:
                for k, v in r.items():
                    for kk, vv in v.items():
                        recs5[tf][k][kk].append(vv)
            grp5[tf].append(COINS.index(sym) * 100000 + tsec[e] // (7 * 86400))
        del mx, mn
        print(f"5m-resolved {sym} t={time.time()-t0:.0f}s", flush=True)
    for tf in TFS[1:]:
        rr = {k: {kk: np.concatenate(vv) for kk, vv in v.items()} for k, v in recs5[tf].items()}
        all_rows += aggregate(tf, "5m", rr, np.concatenate(grp5[tf]), TF_MIN[tf])
    print("5m-resolved dropped entries (no exact 5m bar or <90d left):", dropped)
    res = pd.DataFrame(all_rows)
    res.to_csv(f"{OUT}/bracket_zero_edge.csv", index=False)
    for tf, en in entries_by_tf.items():
        en.to_csv(f"{OUT}/entries_{tf}.csv.gz", index=False)
    print(f"done t={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
