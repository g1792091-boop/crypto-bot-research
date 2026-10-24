"""Adversarial check (luck and multiple testing) of the claim about P4 = the trend bot's 18 members + full 10-22 checks,
one-position bot, a2 exits (2 ATR, 30x).

Independent re-implementation of the one-position walk (own numba loop) over the study's signal table
(scratch forward/sig.pkl.gz, read only). Writes mt_p4.json next to this file.

  1. reproduce P4 a2 / w35 (all, H1, H2) with my own loop
  2. per-trade spread: t statistic and day-cluster bootstrap 95 % range of the mean
  3. coin-flip null on the SAME P4 entries: each signal's side drawn at random (iid, and per (coin, day) cluster),
     one-position bot rerun, p = P(null mean >= observed)
  4. family-wise: the 16 pre-declared bots (P1..P8 x a2/w35, no blocks) under one shared random side per signal;
     null distribution of the BEST of the 16 vs the observed best (+2.16 %); per-bot p values and BH
  5. random-member null: 18 random (strategy, tf) cells with the same tf mix (4 x 30m, 7 x 1h, 7 x 4h) and the same
     checks (tj_why_1022 == ''), a2 one-position bot; where does P4 sit
  6. selection demo: the 18 cells with the best IN-SAMPLE signal-level mean (same checks), bot on the same 19 days
Run (no -I, from this folder): python3 mt_p4.py [n_draws]"""
import json
import os
import sys

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa: F401,F403,E402
from fw_combo import add_roe  # noqa: E402
import numba  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
OUTF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mt_p4.json")
TFI = {t: i for i, t in enumerate(TFS)}


@numba.njit(cache=True)
def walk(e, k, order):
    took = np.zeros(len(e), np.bool_)
    busy = -1
    for q in order:
        if k[q] < 0:
            continue
        if e[q] > busy:
            took[q] = True
            busy = e[q] + k[q]
    return took


@numba.njit(cache=True)
def walk_mean(e, k_s, k_o, r_s, r_o, ok_s, ok_o, flip, order):
    """One-position mean ROE when row q takes the opposite side iff flip[q]."""
    busy = -1
    tot = 0.0
    n = 0
    for q in order:
        if flip[q]:
            if not ok_o[q] or k_o[q] < 0:
                continue
            if e[q] > busy:
                busy = e[q] + k_o[q]
                tot += r_o[q]
                n += 1
        else:
            if not ok_s[q] or k_s[q] < 0:
                continue
            if e[q] > busy:
                busy = e[q] + k_s[q]
                tot += r_s[q]
                n += 1
    return tot / max(n, 1), n


def arrays(X, v):
    lev = LEV[v]
    return dict(
        e=X.e.to_numpy(np.int64),
        k_s=X[f"{v}_k"].to_numpy(np.int64), k_o=X[f"{v}_opp_k"].to_numpy(np.int64),
        r_s=np.maximum(lev * X[f"{v}_r"].to_numpy(float), -1.0), r_o=np.maximum(lev * X[f"{v}_opp_r"].to_numpy(float), -1.0),
        ok_s=(X[f"{v}_why"].to_numpy() != 3), ok_o=(X[f"{v}_opp_why"].to_numpy() != 3),
        order=np.lexsort((X.coin.to_numpy().astype(int) * 10 + X.tf.map(TFI).to_numpy().astype(int),
                          X.e.to_numpy(np.int64))).astype(np.int64))


def bot_trades(X, v, per="all", opp=False):
    a, b = PERIOD[per]
    s = "_opp" if opp else ""
    Y = X[(X.t >= a) & (X.t < b) & (X[f"{v}{s}_why"] != 3)].reset_index(drop=True)
    prio = Y.coin.to_numpy().astype(int) * 10 + Y.tf.map(TFI).to_numpy().astype(int)
    order = np.lexsort((prio, Y.e.to_numpy(np.int64))).astype(np.int64)
    took = walk(Y.e.to_numpy(np.int64), Y[f"{v}{s}_k"].to_numpy(np.int64), order)
    T = Y[took].copy()
    T["roe"] = np.maximum(LEV[v] * T[f"{v}{s}_r"].to_numpy(float), -1.0)
    return T


def day_ci(x, d, nb=5000, seed=3):
    u, inv = np.unique(d, return_inverse=True)
    s = np.bincount(inv, weights=x)
    c = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), (nb, len(u)))
    m = s[idx].sum(1) / c[idx].sum(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)), float((m <= 0).mean())]


def main():
    S = add_roe(load("sig"))
    S = S[(S.t >= PERIOD["all"][0]) & (S.t < PERIOD["all"][1])].reset_index(drop=True)
    side = S.side.to_numpy()
    tf = S.tf.to_numpy()
    nm = S.name.to_numpy()
    mem = json.load(open("/home/user/crypto-bot-research/deploy/combo.trend.json"))["members"]
    mm = np.zeros(len(S), bool)
    for it in mem:
        mm |= (nm == it["strategy"]) & (tf == it["tf"])
    chk = S.tj_why_1022.to_numpy() == ""
    P4 = mm & chk
    out = {"n_draws": N}

    # 1. reproduce
    rep = {}
    for v in ("a2", "w35"):
        for per in ("all", "H1", "H2"):
            for opp in (False, True):
                T = bot_trades(S[P4], v, per, opp)
                rep[f"{v}_{per}_{'opp' if opp else 'sig'}"] = {
                    "n": len(T), "mean": float(T.roe.mean()), "win": float((T.roe > 0).mean()),
                    "nL": int(((T.side * (-1 if opp else 1)) > 0).sum()), "nS": int(((T.side * (-1 if opp else 1)) < 0).sum())}
    out["reproduce"] = rep
    print(json.dumps(rep, indent=0))

    # 2. spread of the P4 a2 trades
    T = bot_trades(S[P4], "a2", "all")
    x = T.roe.to_numpy()
    d = (T.t.to_numpy(np.int64) // DAY)
    sd = float(x.std(ddof=1))
    out["p4_a2_spread"] = {"n": len(x), "mean": float(x.mean()), "sd": sd, "se": sd / np.sqrt(len(x)),
                           "t": float(x.mean() / (sd / np.sqrt(len(x)))), "day_ci_and_p_le0": day_ci(x, d),
                           "n_days": int(len(np.unique(d))), "worst": float(x.min()),
                           "mean_without_worst": float(np.sort(x)[1:].mean()),
                           "long_mean": float(x[T.side.to_numpy() > 0].mean()), "short_mean": float(x[T.side.to_numpy() < 0].mean()),
                           "nL": int((T.side > 0).sum()), "nS": int((T.side < 0).sum())}
    T2 = bot_trades(S[P4], "a2", "H2")
    x2 = T2.roe.to_numpy()
    out["p4_a2_H2_spread"] = {"n": len(x2), "mean": float(x2.mean()), "se": float(x2.std(ddof=1) / np.sqrt(len(x2))),
                              "day_ci_and_p_le0": day_ci(x2, T2.t.to_numpy(np.int64) // DAY)}
    print(out["p4_a2_spread"], out["p4_a2_H2_spread"])

    # 3. coin-flip null on the same P4 entries
    rng = np.random.default_rng(20261024)
    X = S[P4].reset_index(drop=True)
    for v in ("a2", "w35"):
        A = arrays(X, v)
        obs, nobs = walk_mean(A["e"], A["k_s"], A["k_o"], A["r_s"], A["r_o"], A["ok_s"], A["ok_o"],
                              np.zeros(len(X), np.bool_), A["order"])
        res = {}
        cl = (X.coin.to_numpy().astype(np.int64) * 100000 + X.t.to_numpy(np.int64) // DAY)
        uc, ci = np.unique(cl, return_inverse=True)
        for mode in ("iid", "coin_day"):
            vals = np.empty(N)
            for i in range(N):
                if mode == "iid":
                    f = rng.random(len(X)) < 0.5
                else:
                    f = (rng.random(len(uc)) < 0.5)[ci]
                vals[i] = walk_mean(A["e"], A["k_s"], A["k_o"], A["r_s"], A["r_o"], A["ok_s"], A["ok_o"], f, A["order"])[0]
            res[mode] = {"null_mean": float(vals.mean()), "null_p95": float(np.percentile(vals, 95)),
                         "null_p99": float(np.percentile(vals, 99)), "p": float((vals >= obs).mean()),
                         "p_null_pos": float((vals > 0).mean())}
        out[f"coinflip_P4_{v}"] = {"obs": obs, "n": nobs, **res}
        print(v, out[f"coinflip_P4_{v}"])

    # 4. family-wise over the 16 pre-declared bots
    nt = S.role.to_numpy() != "trend"
    from fw_prespec_bots import auto_state
    jd = auto_state(S, "Jdir") * side
    j4 = auto_state(S, "J4of4") * side
    fr = (nm == "O4_STOCHRSI_ZONE") & (tf == "1h") & ((state(S, "c_OBV_S", "4h") * side) == 1)
    fam = np.isin(S.role.to_numpy(), ["pullback", "range", "breakout"])
    sets = {"P1": nt & (jd == 1), "P2": nt & (jd == -1), "P3": nt, "P4": P4, "P5": fr, "P6": nt & (j4 == 1),
            "P7": fam & (jd == 1), "P8": fam & (tf == "30m") & (jd == 1)}
    cfg = []
    for k_, m in sets.items():
        idx = np.flatnonzero(m)
        X = S.iloc[idx].reset_index(drop=True)
        for v in ("a2", "w35"):
            A = arrays(X, v)
            o, n_ = walk_mean(A["e"], A["k_s"], A["k_o"], A["r_s"], A["r_o"], A["ok_s"], A["ok_o"],
                              np.zeros(len(X), np.bool_), A["order"])
            cfg.append((f"{k_}_{v}", idx, A, o, n_))
    obs_vec = np.array([c[3] for c in cfg])
    nulls = np.empty((N, len(cfg)))
    for i in range(N):
        f_all = rng.random(len(S)) < 0.5
        for j, (_, idx, A, _, _) in enumerate(cfg):
            nulls[i, j] = walk_mean(A["e"], A["k_s"], A["k_o"], A["r_s"], A["r_o"], A["ok_s"], A["ok_o"], f_all[idx],
                                    A["order"])[0]
    p_each = (nulls >= obs_vec).mean(0)
    best = obs_vec.max()
    mx = nulls.max(1)
    # studentised max: each bot's (mean - null mean) / null sd, so small-n bots do not dominate only by noise
    z_obs = (obs_vec - nulls.mean(0)) / nulls.std(0)
    z_null = (nulls - nulls.mean(0)) / nulls.std(0)
    out["family16"] = {
        "bots": {c[0]: {"obs": float(c[3]), "n": int(c[4]), "null_mean": float(nulls[:, j].mean()),
                        "null_sd": float(nulls[:, j].std()), "p": float(p_each[j]), "z": float(z_obs[j])}
                 for j, c in enumerate(cfg)},
        "best_obs": float(best), "best_name": cfg[int(obs_vec.argmax())][0],
        "p_best_raw_max": float((mx >= best).mean()), "null_best_median": float(np.median(mx)),
        "null_best_p95": float(np.percentile(mx, 95)), "p_null_best_positive": float((mx > 0).mean()),
        "z_best_obs": float(z_obs.max()), "z_best_name": cfg[int(z_obs.argmax())][0],
        "p_best_studentised": float((z_null.max(1) >= z_obs.max()).mean()),
        "bh_q": dict(zip([c[0] for c in cfg], [float(q) for q in bh(np.maximum(p_each, 1.0 / N))]))}
    print(json.dumps(out["family16"], indent=0))

    # 5. random-member null (same tf mix, same checks), a2 and w35
    cells = S[chk & np.isin(tf, ["30m", "1h", "4h"])].groupby(["name", "tf"]).size().reset_index()
    pool = {t: cells[cells.tf == t].name.to_numpy() for t in ("30m", "1h", "4h")}
    mix = {"30m": 4, "1h": 7, "4h": 7}
    key = pd.Series(np.arange(len(S)))
    cell_id = pd.factorize(S.name + "|" + S.tf)[0]
    lut = {n: i for i, n in enumerate(pd.unique(S.name + "|" + S.tf))}
    rm = {}
    for v in ("a2", "w35"):
        A0 = arrays(S, v)
        vals = np.empty(N)
        ns = np.empty(N)
        for i in range(N):
            pick = [lut[f"{n}|{t}"] for t, c in mix.items() for n in rng.choice(pool[t], c, replace=False)]
            m = np.isin(cell_id, pick) & chk
            k_s = np.where(m, A0["k_s"], -1)
            vals[i], ns[i] = walk_mean(A0["e"], k_s, A0["k_o"], A0["r_s"], A0["r_o"], A0["ok_s"], A0["ok_o"],
                                       np.zeros(len(S), np.bool_), A0["order"])
        obs = rep[f"{v}_all_sig"]["mean"]
        rm[v] = {"obs": obs, "pool_sizes": {t: int(len(p)) for t, p in pool.items()}, "null_mean": float(vals.mean()),
                 "null_median": float(np.median(vals)), "null_p90": float(np.percentile(vals, 90)),
                 "null_p95": float(np.percentile(vals, 95)), "share_null_ge_obs": float((vals >= obs).mean()),
                 "share_null_positive": float((vals > 0).mean()), "null_n_median": float(np.median(ns))}
        print("random members", v, rm[v])
    out["random_members"] = rm

    # 6. in-sample selection demo: best 18 cells (same tf mix) by signal-level mean of checked signals, whole period
    sel = {}
    for v in ("a2", "w35"):
        r = np.maximum(LEV[v] * S[f"{v}_r"].to_numpy(float), -1.0)
        D = pd.DataFrame({"cell": S.name + "|" + S.tf, "tf": tf, "r": r, "ok": chk & (S[f"{v}_why"].to_numpy() != 3)})
        G = D[D.ok & np.isin(tf, ["30m", "1h", "4h"])].groupby(["cell", "tf"]).r.agg(["mean", "size"]).reset_index()
        G = G[G["size"] >= 5]
        pick = []
        for t, c in mix.items():
            pick += G[G.tf == t].sort_values("mean", ascending=False).cell.head(c).tolist()
        m = np.isin((S.name + "|" + S.tf).to_numpy(), pick) & chk
        T = bot_trades(S[m], v, "all")
        sel[v] = {"n": len(T), "mean": float(T.roe.mean()), "win": float((T.roe > 0).mean()), "cells": pick}
        print("in-sample top18", v, sel[v]["n"], sel[v]["mean"])
    out["insample_top18"] = sel
    json.dump(out, open(OUTF, "w"), indent=1)


if __name__ == "__main__":
    main()
