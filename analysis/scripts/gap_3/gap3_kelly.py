"""GAP-3: quantify the leverage / target decision (Kelly) on the empirical stage-1 trade shapes.

Extends critic/work/kelly.py:
  * exact Kelly (argmax_f mean log(1+f*y)) next to the 2nd-order mu/(s^2+mu^2);
  * liquidation flag corrected for the MAE-exit-bar artefact (ENG-3 / audit_engine B4 / verify_data DATA-2);
    the raw engine flag is kept as a sensitivity;
  * the isolated-margin payoff at the implementation leverage (5x vs 50x): at 50x a position is liquidated
    when MAE <= -1.5% whatever the margin size, which changes the payoff shape (critical for Option B: no stop);
  * mu confidence intervals: iid t and a calendar-day cluster bootstrap (captures cross-symbol co-timing);
  * trade rates pooled over symbols (kelly.py) AND in one account with one position at a time
    (portfolio.single_account selection rule, verified against the delivered function);
  * a concurrent multi-symbol (daily-aggregated) Kelly for the half-Kelly regime;
  * Option B IS (618) and OOS (1936) trade vectors from the pre-registered Gap-1 run.
Outputs -> ../out/*.csv, stdout -> ../out/gap3_stdout.txt (via shell redirect)."""
import os, sys, math, json
import numpy as np, pandas as pd
from scipy.optimize import minimize_scalar

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bt"))
from portfolio import single_account  # noqa: E402

OUT = os.path.join(HERE, "..", "out")
R = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/repro/results"
LN20 = math.log(20.0)
SEED = 20260929
NSIM = 20000
WANT15 = [("S6_EMA_DMI_ADX", "F_sl2.0_tp3.0"), ("S2_ST_ROC", "F_sl2.0_tp2.0"), ("N17_KC_RSI", "F_sl1.0_tp1.5"),
          ("N08_ICHI_WR", "T_sl1.5_tr2.5"), ("N08_ICHI_WR", "L50_sl20"), ("N17_KC_RSI", "L50_sl20")]
WANT5 = [("V45_EXACT_AMB", "F_sl2.0_tp3.0"), ("V45_EXACT_AMB_G1", "F_sl2.0_tp3.0"), ("V45_EXACT_AMB_G1", "L50_sl15")]
COLS = ["strategy", "exit", "symbol", "side", "net", "gross", "mae", "sl_dist", "reason", "hold", "entry_ts", "exit_ts"]
pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 400)


# ------------------------------------------------------------------ data
def load_ledgers():
    cache = os.path.join(OUT, "cand_ledgers.csv")
    if os.path.exists(cache):
        A = pd.read_csv(cache)
    else:
        parts = []
        for ch in pd.read_csv(os.path.join(R, "trades_IS_15m_all5.csv"), usecols=COLS, chunksize=200000):
            m = ch.set_index(["strategy", "exit"]).index.isin(WANT15)
            parts.append(ch[m])
        t15 = pd.concat(parts); t15["tf"] = "15m_IS"
        t5 = pd.read_csv(os.path.join(R, "trades_ALL_5m_v45g1.csv"), usecols=COLS)
        t5 = t5[t5.set_index(["strategy", "exit"]).index.isin(WANT5)].copy(); t5["tf"] = "5m_ALL"
        bs = []
        for nm in ("B_IS", "B_OOS"):
            b = pd.read_csv(os.path.join(OUT, f"{nm}_ledger.csv"))
            b["tf"] = "5m_" + nm.split("_")[1]
            bs.append(b[COLS + ["tf"]])
        A = pd.concat([t15, t5] + bs, ignore_index=True)
        A.to_csv(cache, index=False)
    A["entry_ts"] = pd.to_datetime(A["entry_ts"], utc=True)
    A["exit_ts"] = pd.to_datetime(A["exit_ts"], utc=True)
    A["key"] = A["strategy"] + "|" + A["exit"]
    return A


# ------------------------------------------------------------------ helpers
def liq_flag(g, L, fixed=True):
    ld = 1.0 / L - 0.005
    raw = g["mae"].to_numpy() <= -ld
    if not fixed:
        return raw
    stop_exit = g["reason"].isin(["SL", "TRAIL", "LOCK"]).to_numpy()
    artefact = stop_exit & (g["sl_dist"].to_numpy() < ld) & (g["gross"].to_numpy() > -ld)
    return raw & ~artefact


def exact_kelly(y):
    """argmax_f mean log(1 + f*y), f >= 0 (notional as a multiple of equity, cross margin)."""
    if y.mean() <= 0:
        return 0.0
    fmax = 0.999999 / max(-y.min(), 1e-12)
    r = minimize_scalar(lambda f: -np.mean(np.log1p(f * y)), bounds=(0.0, fmax), method="bounded",
                        options=dict(xatol=1e-6))
    return float(r.x)


def lev_shape(y, liq, L):
    """per-unit-notional payoff of an ISOLATED position at leverage L: loss capped at the margin (1/L of
    notional); a liquidated position loses the whole margin."""
    return np.where(liq, -1.0 / L, np.maximum(y, -1.0 / L))


def user_lg(y, liq, m, L):
    roe = np.where(liq, -1.0, np.maximum(-1.0, L * y))
    return np.log(np.maximum(1e-300, 1.0 + m * roe))


def take_single(g):
    """portfolio.single_account selection rule (portfolio.py:21-35): sort by entry_ts, symbol; skip while busy."""
    t = g.sort_values(["entry_ts", "symbol"]).reset_index(drop=True)
    keep = np.zeros(len(t), bool)
    busy = np.datetime64("1970-01-01")
    et = t["entry_ts"].dt.tz_localize(None).to_numpy(); xt = t["exit_ts"].dt.tz_localize(None).to_numpy()
    for k in range(len(t)):
        if et[k] < busy:
            continue
        keep[k] = True; busy = xt[k]
    return t[keep].reset_index(drop=True)


def cluster_ci(g, reps=5000, seed=SEED):
    d = g["entry_ts"].dt.floor("D")
    s = g.groupby(d)["net"].agg(["sum", "count"])
    S, C = s["sum"].to_numpy(), s["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(S), (reps, len(S)))
    means = S[idx].sum(1) / C[idx].sum(1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), float(means.std(ddof=1))


def max_concurrency(g):
    ev = np.concatenate([np.stack([g.entry_ts.astype("int64"), np.ones(len(g))], 1),
                         np.stack([g.exit_ts.astype("int64"), -np.ones(len(g))], 1)])
    ev = ev[np.lexsort((ev[:, 1], ev[:, 0]))]   # exits (-1) before entries at the same timestamp
    c = np.cumsum(ev[:, 1])
    tot = (g.exit_ts - g.entry_ts).dt.total_seconds().sum()
    span = (g.exit_ts.max() - g.entry_ts.min()).total_seconds()
    return int(c.max()), float(tot / span)


def boot30(lg, n30, rng, nsim=NSIM):
    if n30 <= 0:
        return np.zeros(nsim)
    return lg[rng.integers(0, len(lg), (nsim, n30))].sum(1)


def dist_stats(s):
    return dict(med=float(np.exp(np.median(s))), p05=float(np.exp(np.percentile(s, 5))),
                p95=float(np.exp(np.percentile(s, 95))), p_lt_half=float((s < math.log(0.5)).mean()),
                p_ge_20=float((s >= LN20).mean()))


def solve_mu(fun_g, n30, lo=-0.002, hi=0.03):
    """min mu with n30 * g(mu) >= ln 20 (g increasing in mu); None if not reached by hi."""
    if n30 * fun_g(hi) < LN20:
        return None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if n30 * fun_g(mid) >= LN20:
            hi = mid
        else:
            lo = mid
    return hi


# ------------------------------------------------------------------ main
def main():
    A = load_ledgers()
    rng = np.random.default_rng(SEED)
    rows, dist_rows, req_rows, port_rows = [], [], [], []
    order = [f"{s}|{e}" for s, e in WANT15 + WANT5] + ["B_IS|maker64_nostop", "B_OOS|maker64_nostop"]
    for key in order:
        g = A[A.key == key].sort_values(["entry_ts", "symbol"]).reset_index(drop=True)
        tf = g.tf.iloc[0]
        x = g.net.to_numpy(float)
        days = (g.exit_ts.max() - g.entry_ts.min()).total_seconds() / 86400
        n30_pool = len(x) / days * 30
        # single account (one position at a time across symbols)
        sa = take_single(g)
        chk = single_account(g[["symbol", "entry_ts", "exit_ts", "net", "mae"]], lev=1.0)
        assert chk["taken"] == len(sa), (key, chk["taken"], len(sa))
        n30_sa = len(sa) / days * 30
        xs = sa.net.to_numpy(float)
        mu, sd = x.mean(), x.std(ddof=1)
        se = sd / math.sqrt(len(x))
        lo_c, hi_c, se_c = cluster_ci(g)
        maxc, avgc = max_concurrency(g)
        wr = (x > 0).mean()
        skew = float(pd.Series(x).skew()); kurt = float(pd.Series(x).kurt())
        base = dict(key=key, tf=tf, n=len(x), days=round(days, 1), n30_pool=n30_pool, n_sa=len(sa), n30_sa=n30_sa,
                    mu_pct=mu * 100, sd_pct=sd * 100, skew=skew, exkurt=kurt, wr=wr,
                    ci_iid_lo=(mu - 1.96 * se) * 100, ci_iid_hi=(mu + 1.96 * se) * 100,
                    ci_clu_lo=lo_c * 100, ci_clu_hi=hi_c * 100, deff=(se_c / se) ** 2,
                    mu_sa_pct=xs.mean() * 100, sd_sa_pct=xs.std(ddof=1) * 100,
                    max_conc=maxc, avg_conc=avgc)
        liq50_fix, liq50_raw = liq_flag(g, 50), liq_flag(g, 50, fixed=False)
        liq5_fix = liq_flag(g, 5)
        base.update(liq50_fix_pct=liq50_fix.mean() * 100, liq50_raw_pct=liq50_raw.mean() * 100,
                    liq60_fix_pct=liq_flag(g, 60).mean() * 100, liq5_pct=liq5_fix.mean() * 100)
        print(f"\n=== {key} [{tf}] n={len(x)} days={days:.0f} pooled/30d={n30_pool:.0f} single-acct/30d={n30_sa:.0f}"
              f" maxconc={maxc} avgconc={avgc:.2f}")
        print(f"  mu={mu*100:+.4f}%  sd={sd*100:.3f}%  WR={wr:.3f} skew={skew:.2f} exkurt={kurt:.1f}  "
              f"CI95 iid [{(mu-1.96*se)*100:+.4f},{(mu+1.96*se)*100:+.4f}]  day-cluster [{lo_c*100:+.4f},{hi_c*100:+.4f}]"
              f" deff={(se_c/se)**2:.2f}  single-acct mu={xs.mean()*100:+.4f}%")
        print(f"  liq share: 50x fixed {liq50_fix.mean()*100:.2f}% (raw engine flag {liq50_raw.mean()*100:.2f}%), "
              f"60x fixed {liq_flag(g,60).mean()*100:.2f}%, 5x {liq5_fix.mean()*100:.3f}%")

        sa_liq50 = liq_flag(sa, 50); sa_liq5 = liq_flag(sa, 5)
        scen = [("emp", None), ("ci_hi", hi_c), ("+0.05", 0.0005), ("+0.10", 0.0010), ("+0.20", 0.0020)]
        for sname, target in scen:
            # pooled shape (all trades) and single-account subset, both mean-shifted to target
            y = x if target is None else x - mu + target
            ys = xs if target is None else xs - xs.mean() + target
            m_used = y.mean()
            k2 = m_used / (y.var(ddof=0) + m_used ** 2) if m_used > 0 else 0.0
            k_ex = exact_kelly(y)
            k5 = exact_kelly(lev_shape(y, liq5_fix, 5))
            k50 = exact_kelly(lev_shape(y, liq50_fix, 50))
            r = dict(base, scenario=sname, mu_used_pct=m_used * 100, kelly_2nd=k2, kelly_exact=k_ex,
                     kelly_5x=k5, kelly_50x_iso=k50, half_kelly_5x=k5 / 2, half_kelly_50x=k50 / 2,
                     margin_pct_halfK_at5x=k5 / 2 / 5 * 100, margin_pct_halfK_at50x=k50 / 2 / 50 * 100,
                     user20x_over_kelly=(20 / k_ex) if k_ex > 0 else np.inf)
            # growth per trade
            g_user_sa = user_lg(ys, sa_liq50, 0.4, 50)
            g_user_pool = user_lg(y, liq50_fix, 0.4, 50)
            fhk_sa = exact_kelly(lev_shape(ys, sa_liq5, 5)) / 2
            g_hk_sa = np.log1p(fhk_sa * lev_shape(ys, sa_liq5, 5))
            fhk50_sa = exact_kelly(lev_shape(ys, sa_liq50, 50)) / 2
            g_hk50_sa = np.log1p(fhk50_sa * lev_shape(ys, sa_liq50, 50))
            r.update(logg_user_per_trade=g_user_sa.mean(), logg_halfK_per_trade=g_hk_sa.mean(),
                     halfK_notional_sa=fhk_sa)
            rows.append(r)
            n_sa, n_pool = int(round(n30_sa)), int(round(n30_pool))
            for regime, lg, n in (("user_40%x50x_single", g_user_sa, n_sa), ("user_40%x50x_pooled", g_user_pool, n_pool),
                                  ("halfKelly@5x_single", g_hk_sa, n_sa), ("halfKelly@50x_single", g_hk50_sa, n_sa)):
                st = dist_stats(boot30(lg, n, rng))
                dist_rows.append(dict(key=key, scenario=sname, mu_used_pct=(ys.mean() if "single" in regime else y.mean()) * 100,
                                      regime=regime, trades_30d=n,
                                      notional=(20.0 if "user" in regime else (fhk_sa if "5x" in regime else fhk50_sa)),
                                      **st))
            # concurrent multi-symbol half-Kelly (daily aggregation over the whole span)
            gg = g.assign(y=y, day=g.exit_ts.dt.floor("D"))
            alldays = pd.date_range(g.entry_ts.min().floor("D"), g.exit_ts.max().floor("D"), freq="D")
            Rd = gg.groupby("day")["y"].sum().reindex(alldays, fill_value=0.0).to_numpy()
            fp = exact_kelly(Rd)
            sims = np.log1p((fp / 2) * Rd[rng.integers(0, len(Rd), (NSIM, 30))]).sum(1) if fp > 0 else np.zeros(NSIM)
            st = dist_stats(sims)
            port_rows.append(dict(key=key, scenario=sname, mu_used_pct=y.mean() * 100, kelly_per_trade=k_ex,
                                  kelly_per_position_concurrent=fp, ratio=(fp / k_ex if k_ex > 0 else np.nan),
                                  max_conc=maxc, halfK_total_notional_at_maxconc=fp / 2 * maxc, **st))

        # ---------------- required edge for a median x20 in 30 days
        sh = lambda arr, t: arr - arr.mean() + t
        cases = {
            "user40x50_single_liqfix": (lambda t: user_lg(sh(xs, t), sa_liq50, 0.4, 50).mean(), n30_sa),
            "user40x50_pooled_liqfix": (lambda t: user_lg(sh(x, t), liq50_fix, 0.4, 50).mean(), n30_pool),
            "user40x50_pooled_liqraw(kelly.py)": (lambda t: user_lg(sh(x, t), liq50_raw, 0.4, 50).mean(), n30_pool),
            "user30x50_single_liqfix": (lambda t: user_lg(sh(xs, t), sa_liq50, 0.3, 50).mean(), n30_sa),
            "user40x60_single_liqfix": (lambda t: user_lg(sh(xs, t), liq_flag(sa, 60), 0.4, 60).mean(), n30_sa),
            "fullKelly@5x_single": (lambda t: (lambda z: np.mean(np.log1p(exact_kelly(z) * z)))(lev_shape(sh(xs, t), sa_liq5, 5)), n30_sa),
            "fullKelly@5x_pooled(seq)": (lambda t: (lambda z: np.mean(np.log1p(exact_kelly(z) * z)))(lev_shape(sh(x, t), liq5_fix, 5)), n30_pool),
        }
        wins, losses = xs[xs > 0], xs[xs <= 0]
        cost_pct = float((g.gross - g.net).mean() * 100)   # fee + funding (slippage is inside gross)
        for cname, (fg, n30) in cases.items():
            m_req = solve_mu(fg, n30)
            p_req = ((m_req - losses.mean()) / (wins.mean() - losses.mean())) if m_req is not None else np.nan
            req_rows.append(dict(key=key, case=cname, trades_30d=n30, mu_req_pct=(m_req * 100 if m_req is not None else np.nan),
                                 gross_req_pct=(m_req * 100 + cost_pct if m_req is not None else np.nan),
                                 mu_obs_pct=mu * 100, sr_req=(m_req / sd if m_req is not None else np.nan),
                                 wr_obs=float((xs > 0).mean()), wr_req_tilt=p_req))
        # analytic Gaussian bound at full Kelly: n * mu^2 / (2 sd^2) >= ln 20
        for nm, n30, s_ in (("analytic_fullKelly_single", n30_sa, xs.std(ddof=1)), ("analytic_fullKelly_pooled", n30_pool, sd)):
            m_req = s_ * math.sqrt(2 * LN20 / n30)
            req_rows.append(dict(key=key, case=nm, trades_30d=n30, mu_req_pct=m_req * 100, gross_req_pct=m_req * 100 + cost_pct,
                                 mu_obs_pct=mu * 100, sr_req=m_req / s_, wr_obs=float((xs > 0).mean()), wr_req_tilt=np.nan))

    K = pd.DataFrame(rows); Dd = pd.DataFrame(dist_rows); Q = pd.DataFrame(req_rows); P = pd.DataFrame(port_rows)
    K.to_csv(os.path.join(OUT, "gap3_kelly.csv"), index=False)
    Dd.to_csv(os.path.join(OUT, "gap3_30d_dist.csv"), index=False)
    Q.to_csv(os.path.join(OUT, "gap3_required_edge.csv"), index=False)
    P.to_csv(os.path.join(OUT, "gap3_concurrent.csv"), index=False)

    print("\n\n######## TABLE 1: per-candidate stats (scenario=emp)")
    c1 = ["key", "tf", "n", "n30_pool", "n30_sa", "mu_pct", "ci_clu_lo", "ci_clu_hi", "ci_iid_lo", "ci_iid_hi", "deff", "sd_pct",
          "skew", "exkurt", "wr", "mu_sa_pct", "liq50_fix_pct", "liq50_raw_pct", "liq60_fix_pct", "liq5_pct", "max_conc", "avg_conc"]
    print(K[K.scenario == "emp"][c1].round(4).to_string(index=False))
    print("\n######## TABLE 2: Kelly notional leverage by scenario (x equity) and implied margin")
    c2 = ["key", "scenario", "mu_used_pct", "kelly_2nd", "kelly_exact", "kelly_5x", "kelly_50x_iso", "half_kelly_5x",
          "margin_pct_halfK_at5x", "half_kelly_50x", "margin_pct_halfK_at50x", "user20x_over_kelly"]
    print(K[c2].round(3).to_string(index=False))
    print("\n######## TABLE 3: 30-day multiple distributions")
    print(Dd.round(4).to_string(index=False))
    print("\n######## TABLE 4: concurrent multi-symbol Kelly (daily aggregation) and 30-day at half of it")
    print(P.round(4).to_string(index=False))
    print("\n######## TABLE 5: required net edge per trade for a median x20 in 30 days")
    print(Q.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
