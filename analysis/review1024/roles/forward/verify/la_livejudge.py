"""Look-ahead verifier, step 7: the judgments the LIVE trend bot logged at the time (it cannot see the future) vs the
judge states the study reads from the states files for the same coin / higher bar (forward_trendbot + forward_ac)."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa

for which in ("trendbot", "ac"):
    F = RD.forward(which)
    lc = [c for c in F.columns if c.startswith("log_j_")]
    m = F.log_j_dir.notna() if "log_j_dir" in F else np.zeros(len(F), bool)
    X = F[m].copy()
    print(which, "rows", len(F), "with a logged judgment", len(X), "cols", lc[:14])
    if not len(X):
        continue
    X["coin"] = X.symbol.map({c: i for i, c in enumerate(COINS)}) if "coin" not in X else X.coin
    X = X[X.coin >= 0]
    h = X.log_j_tf.astype(str).to_numpy()
    # read the study's states at the bar the bot logged (by its bar close)
    out = {"dir": 0, "raw": 0, "V39": 0, "S6": 0, "OBV": 0, "N12": 0, "bar_le_t": 0, "n": 0}
    for i, r in X.reset_index(drop=True).iterrows():
        Z = RD._states(COINS[int(r.coin)], r.log_j_tf)
        bc = Z["ts"] + TF_MIN[r.log_j_tf] * MIN
        j = int(np.searchsorted(bc, int(r.log_j_bar_close)))
        if j >= len(bc) or bc[j] != int(r.log_j_bar_close):
            continue
        out["n"] += 1
        out["dir"] += int(Z["j_dir"][j] == r.log_j_dir)
        out["raw"] += int(Z["j_raw3"][j] == r.log_j_raw)
        for k in ("V39", "S6", "OBV", "N12"):
            out[k] += int(Z[f"j_{k}"][j] == r[f"log_j_{k}"])
        out["bar_le_t"] += int(int(r.log_j_bar_close) <= int(r.t))
        # the study's own (signal-time) judge on the same row
    print(which, out)
    if "tj_dir" in X:
        same = (np.nan_to_num(X.tj_dir.to_numpy()) == X.log_j_dir.to_numpy()) & (X.tj_htf.astype(str).to_numpy() == h)
        print(which, "study judge at the signal time == bot's logged judgment:", int(same.sum()), "/", len(X),
              "| htf differs:", int((X.tj_htf.astype(str).to_numpy() != h).sum()))
