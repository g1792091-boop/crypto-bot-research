"""참고 read (not in PREREG.md, written after the step-7 verdict, chooses nothing): can the losing trades be told apart
before entry? The owners asked whether looking at every loss could turn 52 wins / 16 losses into 52 / 0.

On 30m, for every signal (not only the ones the one-position pass takes), label = the trade lost (net <= 0) under the
rule bot's exits (B1) and under B3. A gradient-boosted model with fixed settings (set here, before running) learns
from the entry-time features of the select period only; the confirm period is read once: AUC, and what happens to the
win rate / mean R / the account when the signals the model rates most likely to lose are skipped (cut-offs = the
select period's own prediction quantiles, so nothing is fitted on confirm).

    python3 -I vwlossml.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwstages import *
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=200, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=20261023, verbose=-1)
NUM = ["side", "kst_hour", "kst_dow", "vwap_age_h", "wick_frac", "body_atr", "close_vwap_atr", "brk_depth_atr",
       "bars_since_brk", "relvol", "vwap_slope_atr", "adx", "atrp", "day_pos", "ema4h50", "ema1d20", "p24", "p7",
       "chase", "fund_pay", "btc_bar", "btc4h_raw3"] + [f"j{h}_{n}" for h in ("1h", "4h") for n in ("V39", "S6", "OBV", "N12", "raw3")]
SKIP = (0.1, 0.2, 0.3, 0.5)


def X_of(F):
    X = F[NUM].astype(float).copy()
    X["atrp_rank"] = (F.atrp - F.atrp_q20) / (F.atrp_q80 - F.atrp_q20)
    X["coin"] = F.coin.map({c: i for i, c in enumerate(COINS)}).astype(float)
    return X


def main():
    b = Book("30m")
    X = X_of(b.F)
    out = {}
    sel, conf = period_mask(b, "select"), period_mask(b, "confirm")
    for nm, j in (("B1", EX_B1), ("B3", EX_B3)):
        y = (b.ret[:, j] <= 0).astype(int)
        mdl = lgb.LGBMClassifier(**PARAMS).fit(X[sel], y[sel])
        p = mdl.predict_proba(X)[:, 1]
        auc_in = roc_auc_score(y[sel], p[sel])
        auc = roc_auc_score(y[conf], p[conf])
        rows = []
        base_all = {"win": float(1 - y[conf].mean()), "avgR": float((b.ret[conf, j] / b.risk_dist(j)[conf]).mean())}
        for q in (0.0,) + SKIP:
            cut = np.quantile(p[sel], 1 - q) if q > 0 else np.inf
            keep = p <= cut if q > 0 else np.ones(len(p), bool)
            kc = keep & conf
            acc = metrics(b, keep, j, "confirm")
            rows.append(rnd({"skip_share_select": q, "kept_signals_confirm": int(kc.sum()),
                             "win_all_signals": float(1 - y[kc].mean()),
                             "avgR_all_signals": float((b.ret[kc, j] / b.risk_dist(j)[kc]).mean()),
                             "acct_n": acc["n"], "acct_per_weekday": acc["per_weekday"], "acct_win": acc["win"],
                             "acct_avgR": acc["avgR"], "acct_payoff": acc["payoff"], "acct_growth": acc["growth"],
                             "acct_maxdd": acc["maxdd"]}))
        imp = sorted(zip(X.columns, mdl.booster_.feature_importance("gain")), key=lambda t: -t[1])[:8]
        out[nm] = {"exit_ko": exit_name(j), "auc_select_in_sample": round(auc_in, 4), "auc_confirm": round(auc, 4),
                   "loss_share_confirm": round(float(y[conf].mean()), 4), "base_confirm_all_signals": rnd(base_all),
                   "skip": rows, "top_features": [(k, round(float(v), 1)) for k, v in imp]}
        print(nm, "AUC select(in) %.3f confirm %.3f" % (auc_in, auc), flush=True)
        for r in rows:
            print("  ", r, flush=True)
    json.dump({"params": PARAMS, "features": list(X.columns), "result": out},
              open(os.path.join(RES_DIR, "results_lossml.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
