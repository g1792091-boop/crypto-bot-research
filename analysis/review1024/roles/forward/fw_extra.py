"""Extra reads for the report (no selection):
  1. the friend's principle per signal: WITH minus AGAINST the live judge (Jdir, auto mapping), all non-trend entries,
     day-cluster bootstrap 95 % CI, per half and per side (long / short), four exits (w35, w30, w35s20, a2);
  2. the payoff shape of the owners' exit (w35) on trend-aligned entries: average win, average loss, stop share;
  3. what a bot would need for x6 in 30 days with that payoff shape (win rate by trades/day and margin);
  4. the same principle split for the 5 years (from ../data/baseline_5y.csv, descriptive).
Writes extra.json.  Run: python3 fw_extra.py"""
import json
from fw_lib import *  # noqa: F401,F403
from fw_prespec_bots import auto_state


def diff_ci(x, y, dx, dy, n_boot=4000, seed=3):
    """CI of mean(x) - mean(y) resampling UTC days (both groups share the day draw)."""
    days = np.unique(np.r_[dx, dy])
    ix = {d: i for i, d in enumerate(days)}
    gx = np.array([ix[d] for d in dx])
    gy = np.array([ix[d] for d in dy])
    sx, cx = np.bincount(gx, x, len(days)), np.bincount(gx, minlength=len(days)).astype(float)
    sy, cy = np.bincount(gy, y, len(days)), np.bincount(gy, minlength=len(days)).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(days), (n_boot, len(days)))
    d = sx[idx].sum(1) / cx[idx].sum(1) - sy[idx].sum(1) / cy[idx].sum(1)
    return float(np.mean(x) - np.mean(y)), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)), \
        float(np.mean(d <= 0))


def main():
    S = load("sig")
    S = S[S.role != "trend"].reset_index(drop=True)
    side = S.side.to_numpy()
    al = auto_state(S, "Jdir") * side
    out = {"principle": []}
    for v in ("w35", "w30", "w35s20", "a2"):
        r = roe(S, v)
        for per in ("all", "H1", "H2"):
            for sd in ("both", "long", "short"):
                a, b = PERIOD[per]
                m = (S.t.to_numpy() >= a) & (S.t.to_numpy() < b) & np.isfinite(r)
                if sd != "both":
                    m &= side == (1 if sd == "long" else -1)
                w, g = m & (al == 1), m & (al == -1)
                d, lo, hi, p = diff_ci(r[w], r[g], S.day.to_numpy()[w], S.day.to_numpy()[g])
                out["principle"].append({"exit": v, "period": per, "side": sd, "n_with": int(w.sum()),
                                         "n_against": int(g.sum()), "with": float(np.mean(r[w])),
                                         "against": float(np.mean(r[g])), "diff": d, "lo": lo, "hi": hi,
                                         "p_diff_le0": p, "with_payback": float(np.mean(r[w]) + LEV[v] * PAYBACK)})
    # payoff shape (w35, trend-aligned, whole period)
    r = roe(S, "w35")
    w = (al == 1) & np.isfinite(r)
    why = S.w35_why.to_numpy()
    out["payoff_w35_with"] = {"n": int(w.sum()), "win_rate": float(np.mean(r[w] > 0)),
                              "avg_win": float(np.mean(r[w][r[w] > 0])), "avg_loss": float(np.mean(r[w][r[w] <= 0])),
                              "stop_share": float(np.mean(why[w] == 0)), "lock_share": float(np.mean(why[w] == 1)),
                              "mean": float(np.mean(r[w])),
                              "median_hold_min": float(np.median(S.w35_k.to_numpy()[w]))}
    W, L = out["payoff_w35_with"]["avg_win"], out["payoff_w35_with"]["avg_loss"]
    need = []
    for tpd in (2, 4, 6, 8, 12):
        for mg in (0.2, 0.4, 0.6, 1.0):
            n = 30 * tpd
            ps = np.linspace(0.5, 1.0, 501)
            g = ps * np.log1p(mg * W) + (1 - ps) * np.log1p(mg * L)
            ok = ps[g * n >= np.log(6)]
            need.append({"trades_per_day": tpd, "margin": mg, "exposure_x": 35 * mg,
                         "win_rate_needed": float(ok[0]) if len(ok) else None,
                         "mean_roe_needed": float(ok[0] * W + (1 - ok[0]) * L) if len(ok) else None})
    out["need_w35"] = need
    out["payoff_note"] = "W, L = average win / loss ROE of trend-aligned forward entries under w35"
    # 5-year descriptive split
    B = pd.read_csv(os.path.join(HERE, "..", "data", "baseline_5y.csv"))
    x = B[B.role != "trend"]
    wavg = lambda c, n: float(np.nansum(x[c] * x[n]) / np.nansum(x[n]))    # noqa: E731
    out["five_year_entries"] = {"n_with": int(x.n_with.sum()), "with": wavg("roe_with", "n_with"),
                                "n_against": int(x.n_against.sum()), "against": wavg("roe_against", "n_against"),
                                "neutral": wavg("roe_nodir", "n_nodir"), "all": wavg("w35_roe", "n"),
                                "coinflip": wavg("w35_opp_roe", "n")}
    json.dump(out, open(os.path.join(HERE, "extra.json"), "w"), indent=1)
    P = pd.DataFrame(out["principle"])
    print(P.round(4).to_string())
    print(json.dumps({k: out[k] for k in ("payoff_w35_with", "five_year_entries")}, indent=1))
    print(pd.DataFrame(need).to_string())


if __name__ == "__main__":
    main()
