"""Luck / multiple-testing verifier, step 3 (bot level): re-derive B_sel_with20 (the 20 with-cells of shortlist.csv, one
position over all coins, w35) with the study's own cell_rows / one_position, then

  1. its SEL / CONF / LATE / FWD reads vs goalpath.csv,
  2. the CONF per-trade mean with a month-clustered and a day-block-bootstrap 95 % interval (raw and with payback),
  3. coin-flip twin: separate path (as the study) and paired on the same taken trades (month-clustered t),
  4. the SAME 20 (strategy, entry tf) with NO trend filter (cond ALL) and AGAINST the trend (cond A): does the
     with-trend condition matter at all in the bot?
  5. 30-day goal bootstrap re-run with other seeds; growth-optimal margin; the shift needed for a x6 median.

    python3 lm_bot.py   -> lm_bot.txt, lm_bot_trades_CONF.csv (taken CONF trades of B, for the null step)"""
import os
import sys

FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
MY = "/dev/shm/claude_verify_lm"
sys.path.insert(0, FY)
import fy_common                         # noqa: E402
fy_common.SHM = MY
import goalpath as GP                    # noqa: E402
from cellsig import *                    # noqa: E402,F401

OUTD = os.path.dirname(os.path.abspath(__file__))
PBR = 35.0 * PAYBACK
out = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    out.append(s)


def month_ci(T, col="w35_roe", add=0.0):
    x = T[col].to_numpy(float) + add
    mon = month_of(T.t.to_numpy(np.int64))
    n = len(x)
    mu = x.mean()
    u = pd.Series(x - mu).groupby(mon).sum().to_numpy() / n
    M = len(u)
    se = np.sqrt((u ** 2).sum() * M / (M - 1))
    return mu, se, mu / se, M


def day_boot_ci(T, col="w35_roe", add=0.0, nb=4000, seed=7):
    x = T[col].to_numpy(float) + add
    d = T.t.to_numpy(np.int64) // DAY
    ud, inv = np.unique(d, return_inverse=True)
    s = np.bincount(inv, weights=x)
    c = np.bincount(inv)
    rng = np.random.default_rng(seed)
    v = np.empty(nb)
    for b in range(nb):
        ii = rng.integers(0, len(ud), len(ud))
        v[b] = s[ii].sum() / c[ii].sum()
    return np.quantile(v, [0.025, 0.975])


def specs_B(cond="W"):
    sel = pd.read_csv(os.path.join(FY, "shortlist.csv"))
    return [(r["name"], r.etf, r.htf, r.source.split(":")[0], r.source.split(":")[1], cond)
            for _, r in sel[sel.cond == "W"].iterrows()]


def main():
    G = pd.read_csv(os.path.join(FY, "goalpath.csv"))
    GB = G[G.bot == "B_sel_with20"].set_index("period")
    S = GP.bot_rows(specs_B("W"))
    say("B rows (all periods)", len(S))
    took = {}
    for per in ("SEL", "CONF", "LATE", "FWD"):
        o, T = GP.read(S, per)
        took[per] = T
        g = GB.loc[per]
        say(f"{per}: trades {o['trades']} (study {int(g.trades)}), per_day {o['per_day']:.3f} ({g.per_day:.3f}), "
            f"mean {o['mean_roe']:.5f} ({g.mean_roe:.5f}), pb {o['mean_roe_pb']:.5f} ({g.mean_roe_pb:.5f}), "
            f"win {o['win']:.4f} ({g.win:.4f}), twin {o['opp_mean_roe']:.5f} ({g.opp_mean_roe:.5f}), "
            f"long share {o['long_share']:.3f}")
    T = took["CONF"]
    T.to_csv(os.path.join(OUTD, "lm_bot_trades_CONF.csv"), index=False,
             columns=["t", "e", "coin", "side", "name", "tf", "cell", "w35_roe", "w35_opp_roe", "w35_k"])
    for add, lab in ((0.0, "raw"), (PBR, "with payback")):
        mu, se, t, M = month_ci(T, add=add)
        lo, hi = day_boot_ci(T, add=add)
        say(f"CONF mean {lab}: {mu:.5f}, month-clustered se {se:.5f} (t {t:.2f}, {M} months), 95% CI "
            f"[{mu - 1.96 * se:.4f}, {mu + 1.96 * se:.4f}]; day-block bootstrap 95% [{lo:.4f}, {hi:.4f}]")
    # paired twin on the same taken trades
    Tp = T.assign(d=T.w35_roe - T.w35_opp_roe)
    mu, se, t, M = month_ci(Tp, "d")
    say(f"CONF paired (taken trades) side - opposite side: {mu:.5f} (opposite on the same trades "
        f"{T.w35_opp_roe.mean():.5f}), month-clustered t {t:.2f}, one-sided p {GP.pval(np.array([t]), np.array([M]))[0]:.4f}")
    # per-cell contribution of taken CONF trades
    say("CONF taken trades by cell:")
    say(T.groupby("cell").w35_roe.agg(["size", "mean"]).sort_values("size", ascending=False).round(4).to_string())
    say("CONF taken trades by entry tf:", T.groupby("tf").w35_roe.agg(["size", "mean"]).round(4).to_dict())

    # ---- the same 20 (strategy, tf) without the trend filter / against it
    for cond in ("ALL", "A"):
        Sx = GP.bot_rows(specs_B(cond))
        for per in ("SEL", "CONF", "LATE", "FWD"):
            r = GP.read(Sx, per)
            if not r:
                continue
            o, Tx = r
            extra = ""
            if per == "CONF":
                mu, se, t, M = month_ci(Tx)
                extra = f" month-se {se:.4f}"
            say(f"same 20 strategies, cond {cond}, {per}: trades {o['trades']} per_day {o['per_day']:.2f} mean "
                f"{o['mean_roe']:.5f} pb {o['mean_roe_pb']:.5f} twin {o['opp_mean_roe']:.5f}{extra}")

    # ---- goal bootstrap re-run, other seeds
    BB = pd.read_csv(os.path.join(FY, "goal_boot.csv"))
    bb = BB[(BB.bot == "B_sel_with20") & (BB.period == "CONF") & (BB.margin == 0.4)]
    say("study bootstrap (CONF, margin 0.4):")
    say(bb[["payback", "p_target", "p_lose50_first", "p_lose90_first", "median_final_x"]].to_string())
    for seed in (11, 22, 33):
        for pb in (False, True):
            Tb = T.assign(w35_roe=T.w35_roe + (PBR if pb else 0.0))
            g = RD.goal_bootstrap(Tb, "w35", margin=0.4, days=PER_SPAN["CONF"], n_boot=4000, seed=seed)
            say(f"seed {seed} payback {pb}: P(x6) {g['p_target']:.4f} P(-50 first) {g['p_lose50_first']:.4f} "
                f"P(-90 first) {g['p_lose90_first']:.4f} median x {g['median_final_x']:.3f}")
    # account at 40 % with payback over the whole CONF (compounded)
    a = RD.account(T.assign(w35_roe=T.w35_roe + PBR), "w35", margin=0.4)
    say(f"CONF compounded at margin 0.4 with payback: final x {a['final_x']:.3g}, max dd {a['max_dd']:.3f}")
    roe = T.w35_roe.to_numpy()
    pdays = len(T) / ((PER_SPAN['CONF'][1] - PER_SPAN['CONF'][0]) / DAY)
    for add in (0.0, PBR):
        m, x = GP.growth_opt(roe + add, pdays)
        say(f"growth-optimal margin (add {add:.4f}): {m:.2f}, 30-day median x {x:.3f}")
    # shift needed for a 30-day median x6 at the growth-optimal margin (finer grid than the study's 0.25)
    for base, lab in ((0.0, "raw"), (PBR, "payback")):
        need = None
        for sh in np.arange(0.0, 0.20, 0.0025):
            m, x = GP.growth_opt(roe + base + sh, pdays)
            if x >= 6.0:
                need = (sh, m, (roe + base + sh).mean())
                break
        say(f"shift for 30-day median x6 ({lab}): +{need[0] * 100:.2f} ROE pts, margin {need[1]:.2f}, "
            f"mean per trade then {need[2]:.4f}")
    open(os.path.join(OUTD, "lm_bot.txt"), "w").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
