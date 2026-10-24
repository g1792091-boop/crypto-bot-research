"""Combined one-position bots from the H1-picked cells (fw_search.py, search_picks.csv) and their goal path.

For each pre-declared pick set (w35 entry TOP10, w35 family TOP5, a2 entry TOP10, a2 family TOP5, and each TOP1), the
bot takes every trend-aligned signal of the picked cells, ONE position at a time over all six coins (a signal is taken
when its entry minute is after the previous trade's exit; same minute: pick rank, then coin order). Read on H2 (the
out-of-sample half), on H1 (in-sample, for reference) and the coin-flip twin bot (same entries, opposite side).
Goal path: compounded account at margins 5 % .. 100 % of equity (35x for w35, 30x for a2), the growth-optimal margin,
and a 30-day day-block bootstrap (rolesdata.goal_bootstrap math): P(reach x6), P(lose 50 % first), P(lose 90 % first).

Writes combo_accounts.csv, combo_goal.csv, combo_trades_<set>.csv (H2 trades of each set), combo.json.
Run: python3 fw_combo.py"""
import json
import numba
from fw_lib import *  # noqa: F401,F403

MARGINS = (0.05, 0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0)


def cell_rows(S, cells):
    """Rows of S that are trend-aligned signals of any of the cells (list of dicts: level E/F, key, tf, htf, src,
    rank); column prio = rank of the first cell that holds the row."""
    out = []
    for c in cells:
        a, b = c["key"].split("|")
        m = (S.tf.to_numpy() == c["tf"]) & ((S.name.to_numpy() == a) if c["level"] == "E" else (S.role.to_numpy() == a))
        m &= (state(S, c["src"], c["htf"]) * S.side.to_numpy()) == 1
        X = S[m].copy()
        X["prio"] = c["rank"]
        X["cell"] = f"{c['key']}@{c['htf']}:{c['src']}"
        out.append(X)
    X = pd.concat(out, ignore_index=True).sort_values(["e", "prio", "coin"])
    return X.drop_duplicates(["coin", "e", "side"]).reset_index(drop=True)


@numba.njit(cache=True)
def _boot(by_flat, by_start, by_len, draws, margin, target):
    nb, h = draws.shape
    hit = l50 = l90 = 0
    finals = np.empty(nb)
    for b in range(nb):
        eq = 1.0
        half = False
        done = False
        for j in range(h):
            di = draws[b, j]
            for q in range(by_start[di], by_start[di] + by_len[di]):
                eq *= 1.0 + margin * by_flat[q]
                if not done:
                    if eq >= target:
                        hit += 1
                        done = True
                    else:
                        if eq <= 0.5 and not half:
                            l50 += 1
                            half = True
                        if eq <= 0.1:
                            l90 += 1
                            done = True
        finals[b] = eq
    return hit / nb, l50 / nb, l90 / nb, np.median(finals)


def goal(T, v, margin, days, n_boot=20000, seed=20261024, side_col="", horizon=30, target=6.0):
    """Same math as rolesdata.goal_bootstrap (day blocks incl. days without trades), compiled."""
    T = T.sort_values("t")
    r = np.maximum(T[f"{v}{side_col}_roe"].to_numpy(float), -1.0)
    d = T.t.to_numpy(np.int64) // DAY
    lo, hi = days[0] // DAY, (days[1] - 1) // DAY
    nd = int(hi - lo + 1)
    order = np.argsort(d, kind="stable")
    r, d = r[order], d[order]
    lens = np.array([(d == lo + i).sum() for i in range(nd)], np.int64)
    starts = np.r_[0, np.cumsum(lens)[:-1]].astype(np.int64)
    rng = np.random.default_rng(seed)
    draws = np.stack([rng.integers(0, nd, horizon) for _ in range(n_boot)])
    p, l5, l9, med = _boot(r, starts, lens, draws, margin, target)
    return {"p_x6": p, "p_lose50_first": l5, "p_lose90_first": l9, "median_x": med, "days_in_sample": nd,
            "trades_in_sample": len(r)}


def add_roe(X):
    for v in ("w35", "a2", "w30", "w35s20"):
        for s in ("", "_opp"):
            X[f"{v}{s}_roe"] = np.maximum(LEV[v] * X[f"{v}{s}_r"], -1.0)
    return X


def bot(X, v, per, side_col="", blocks=False):
    a, b = PERIOD[per]
    Y = X[(X.t >= a) & (X.t < b) & (X[f"{v}{side_col}_why"] != 3)]
    if blocks:
        Y = Y[Y.blk == 0]
    Y = Y.reset_index(drop=True)
    if not len(Y):
        return Y
    took = RD.one_position(Y, v, side_col=side_col, priority="prio")
    return Y[took]


def growth(T, v, side_col=""):
    r = np.maximum(T[f"{v}{side_col}_roe"].to_numpy(float), -1.0)
    ms_ = np.linspace(0.01, 1.0, 100)
    g = np.array([np.mean(np.log(np.maximum(1 + m * r, 1e-12))) for m in ms_])
    i = int(np.argmax(g))
    return ms_[i], g[i]


def main():
    S = add_roe(load("sig"))
    P = pd.read_csv(os.path.join(HERE, "search_picks.csv"))
    sets = {}
    for (v, lab), g in P.groupby(["exit", "level"]):
        cells = g.sort_values("rank").to_dict("records")
        for c in cells:
            c["level"] = lab
        sets[f"{v}_{lab}_top{'10' if lab == 'E' else '5'}"] = (v, cells)
        sets[f"{v}_{lab}_top1"] = (v, [c for c in cells if c["top1"]] or cells[:1])
    acc, gl = [], []
    summary = {}
    for name, (v, cells) in sets.items():
        X = cell_rows(S, cells)
        for per in ("H2", "H1", "all"):
            for blocks in (False, True):
                for sc in ("", "_opp"):
                    T = bot(X, v, per, sc, blocks)
                    if not len(T):
                        continue
                    A = RD.account(T, v, margin=0.4, side_col=sc, start=PERIOD[per][0], end=PERIOD[per][1])
                    mopt, gopt = growth(T, v, sc)
                    row = {"set": name, "exit": v, "period": per, "blocks": blocks, "side": "opp" if sc else "signal",
                           **A, "nL": int((T.side > 0).sum()), "nS": int((T.side < 0).sum()),
                           "roe_L": T.loc[T.side > 0, f"{v}{sc}_roe"].mean() if sc == "" else
                           T.loc[T.side < 0, f"{v}{sc}_roe"].mean(),
                           "roe_S": T.loc[T.side < 0, f"{v}{sc}_roe"].mean() if sc == "" else
                           T.loc[T.side > 0, f"{v}{sc}_roe"].mean(),
                           "roe_payback": A["mean_roe"] + LEV[v] * PAYBACK,
                           "kelly_margin": mopt, "kelly_g": gopt,
                           "x30_at_kelly": float(np.exp(gopt * A["per_day"] * 30))}
                    acc.append(row)
                    if per == "H2" and not blocks:
                        T.to_csv(os.path.join(HERE, f"combo_trades_{name}{'_opp' if sc else ''}.csv"), index=False,
                                 columns=["t", "coin", "name", "tf", "side", "cell", "prio", f"{v}{sc}_roe",
                                          f"{v}{sc}_k", f"{v}{sc}_why", "blk"], float_format="%.5g")
                    if per in ("H2", "all") and sc == "" and not blocks:
                        for m in MARGINS:
                            Am = RD.account(T, v, margin=m, start=PERIOD[per][0], end=PERIOD[per][1])
                            G = goal(T, v, m, PERIOD[per])
                            gl.append({"set": name, "exit": v, "period": per, "margin": m, "exposure_x": LEV[v] * m,
                                       "final_x_sample": Am["final_x"], "max_dd_sample": Am["max_dd"], **G})
        log(name, "done")
    A = pd.DataFrame(acc)
    A.to_csv(os.path.join(HERE, "combo_accounts.csv"), index=False, float_format="%.5g")
    G = pd.DataFrame(gl)
    G.to_csv(os.path.join(HERE, "combo_goal.csv"), index=False, float_format="%.5g")
    json.dump({"sets": {k: [f"{c['key']}@{c['htf']}:{c['src']}" for c in v[1]] for k, v in sets.items()}},
              open(os.path.join(HERE, "combo.json"), "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
