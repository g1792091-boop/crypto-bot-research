"""GAP-3 supplement.
(1) Win-rate tilt model: an edge enters as a higher probability of the exit's winning outcome, with the
    winners' and losers' empirical size distributions kept (physically consistent for ladder / fixed SL-TP,
    unlike a mean shift, which for a sigma=0.25% ladder moves every trade by > 1 sigma).
    Reports: mean win/loss, break-even WR, the maximum mu the exit can deliver (WR=100%), the WR needed for
    mu=+0.05/+0.10%, Kelly under tilt, and the WR needed for a median x20 in 30 days at 40%x50x and at full Kelly.
(2) Option B MAE tail: liquidation shares at 5/10/20/25/50x (isolated, mmr 0.5%).
(3) Check that the solver's n*E[log g] criterion matches the bootstrap median.
(4) Sanity: delivered portfolio.single_account at 50x/40% on each candidate (raw liquidation flag)."""
import os, sys, math
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "bt"))
import gap3_kelly as G  # noqa: E402
from portfolio import single_account  # noqa: E402

OUT = G.OUT
LN20 = G.LN20
pd.set_option("display.width", 260); pd.set_option("display.max_rows", 400)


def wkelly(w, l, p, fmax_extra=None):
    """exact Kelly for mixture: winners w with prob p (uniform within), losers l with prob 1-p."""
    mu = p * w.mean() + (1 - p) * l.mean()
    if mu <= 0:
        return 0.0
    fmax = 0.999999 / max(-l.min(), 1e-12)
    from scipy.optimize import minimize_scalar
    obj = lambda f: -(p * np.mean(np.log1p(f * w)) + (1 - p) * np.mean(np.log1p(f * l)))
    return float(minimize_scalar(obj, bounds=(0, fmax), method="bounded", options=dict(xatol=1e-6)).x)


def user_g_tilt(w, lw, l, ll, p, m=0.4, L=50):
    gw = G.user_lg(w, lw, m, L).mean(); gl = G.user_lg(l, ll, m, L).mean()
    return p * gw + (1 - p) * gl


def main():
    A = G.load_ledgers()
    order = [f"{s}|{e}" for s, e in G.WANT15 + G.WANT5] + ["B_IS|maker64_nostop", "B_OOS|maker64_nostop"]
    rows = []
    for key in order:
        g = A[A.key == key]
        sa = G.take_single(g)
        days = (g.exit_ts.max() - g.entry_ts.min()).total_seconds() / 86400
        n30 = len(sa) / days * 30
        x = sa.net.to_numpy(); liq = G.liq_flag(sa, 50)
        win = x > 0
        w, l, lw, ll = x[win], x[~win], liq[win], liq[~win]
        be = -l.mean() / (w.mean() - l.mean())
        p_for = lambda mu: (mu - l.mean()) / (w.mean() - l.mean())
        # WR needed for x20 at user sizing (tilt): n30 * g(p) >= ln20
        def solve_p(fun):
            if n30 * fun(1.0) < LN20:
                return np.nan
            lo, hi = 0.0, 1.0
            for _ in range(60):
                mid = (lo + hi) / 2
                (hi, lo) = (mid, lo) if n30 * fun(mid) >= LN20 else (hi, mid)
            return hi
        p_user = solve_p(lambda p: user_g_tilt(w, lw, l, ll, p))
        def fk_g(p):
            f = wkelly(w, l, p)
            return p * np.mean(np.log1p(f * w)) + (1 - p) * np.mean(np.log1p(f * l)) if f > 0 else 0.0
        p_fk = solve_p(fk_g)
        r = dict(key=key, n_sa=len(sa), n30_sa=n30, wr_obs=win.mean(), mean_win_pct=w.mean() * 100,
                 mean_loss_pct=l.mean() * 100, max_mu_at_wr100_pct=w.mean() * 100, breakeven_wr=be,
                 wr_for_mu005=p_for(0.0005), wr_for_mu010=p_for(0.0010),
                 kelly_tilt_mu005=(wkelly(w, l, p_for(0.0005)) if p_for(0.0005) <= 1 else np.nan),
                 kelly_tilt_mu010=(wkelly(w, l, p_for(0.0010)) if p_for(0.0010) <= 1 else np.nan),
                 wr_req_x20_user40x50=p_user,
                 mu_req_x20_user_pct=(p_user * w.mean() + (1 - p_user) * l.mean()) * 100 if p_user == p_user else np.nan,
                 wr_req_x20_fullKelly=p_fk,
                 mu_req_x20_fullKelly_pct=(p_fk * w.mean() + (1 - p_fk) * l.mean()) * 100 if p_fk == p_fk else np.nan)
        rows.append(r)
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(OUT, "gap3_tilt.csv"), index=False)
    print("######## TILT MODEL (single-account subsets)")
    print(T.round(4).to_string(index=False))

    # (2) B MAE tail
    print("\n######## Option B: share of trades whose MAE reaches the isolated liquidation distance 1/L-0.5%")
    for nm in ("B_IS", "B_OOS"):
        b = pd.read_csv(os.path.join(OUT, f"{nm}_ledger.csv"))
        q = {f"L{L}": float((b.mae <= -(1 / L - 0.005)).mean() * 100) for L in (5, 10, 15, 20, 25, 33, 50, 60)}
        print(f"  {nm}: n={len(b)}  MAE quantiles 1/5/25/50%: "
              f"{np.percentile(b.mae,1)*100:.2f} / {np.percentile(b.mae,5)*100:.2f} / {np.percentile(b.mae,25)*100:.2f} / "
              f"{np.percentile(b.mae,50)*100:.2f}%  min {b.mae.min()*100:.2f}%   liq% {q}")

    # (3) solver criterion vs bootstrap median
    print("\n######## solver check: at mu_req (user 40%x50x single, liq fixed) the bootstrap median should be ~20")
    Q = pd.read_csv(os.path.join(OUT, "gap3_required_edge.csv"))
    rng = np.random.default_rng(1)
    for key in ("S6_EMA_DMI_ADX|F_sl2.0_tp3.0", "V45_EXACT_AMB_G1|F_sl2.0_tp3.0", "V45_EXACT_AMB_G1|L50_sl15",
                "N17_KC_RSI|L50_sl20", "B_OOS|maker64_nostop"):
        g = A[A.key == key]; sa = G.take_single(g)
        days = (g.exit_ts.max() - g.entry_ts.min()).total_seconds() / 86400
        n30 = int(round(len(sa) / days * 30))
        mreq = Q[(Q.key == key) & (Q.case == "user40x50_single_liqfix")].mu_req_pct.iloc[0] / 100
        y = sa.net.to_numpy() - sa.net.mean() + mreq
        lg = G.user_lg(y, G.liq_flag(sa, 50), 0.4, 50)
        s = G.boot30(lg, n30, rng, 40000)
        print(f"  {key:32s} n30={n30:4d} mu_req={mreq*100:.4f}%  exp(n*E[log])={math.exp(n30*lg.mean()):7.2f}  "
              f"bootstrap median={math.exp(np.median(s)):7.2f}  P(>=20)={np.mean(s>=LN20):.3f}  P(<0.5)={np.mean(s<math.log(.5)):.3f}")

    # (4) delivered single_account (raw engine liquidation flag) over the whole ledger span
    print("\n######## delivered portfolio.single_account, lev 50 / 5, margin 40%, start 1000 (raw liquidation flag)")
    for key in order:
        g = A[A.key == key][["symbol", "entry_ts", "exit_ts", "net", "mae"]]
        r50 = single_account(g, lev=50.0); r5 = single_account(g, lev=5.0)
        print(f"  {key:32s} L50: final {r50['final']:.4g} taken {r50['taken']} liq {r50['liq']} days {r50['days']:.0f} | "
              f"L5: final {r5['final']:.4g} mdd {r5['mdd']:.2f}")


if __name__ == "__main__":
    main()
