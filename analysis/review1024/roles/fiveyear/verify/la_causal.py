"""Look-ahead tests of the data layer's code by CUTTING the data (lens: look-ahead / alignment / data errors).

Part 1 states: for every coin and higher timeframe (1h / 4h / 1d) and several cut bars i, the four judges, raw3, dir and
every condition state are recomputed by the study's own functions (build_states.judge_arrays / cond_states) on the
bars cut at bar i (no bar after i exists) and compared with the stored state table on the last 60 bars <= i. Equal =
no look-ahead in the indicator code (the stored table was computed on the whole history from the same first bar).
F7_RF_TRIPLE reads the next higher frame; it is given that frame cut at the same close.

Part 2 entry signals: for the entry-role strategies (core, DeepSeek, library, friend) on 15m / 30m / 1h / 4h, two
windows that START at the same bar s: A = bars s .. i + 300 (with the future), B = bars s .. i (cut). Signals on the
last 400 bars <= i must be equal in A and B; any difference is a strategy whose signal at a bar depends on later bars.

    python3 la_causal.py [coins...]   -> la_causal_states.csv, la_causal_signals.csv"""
import os
import sys
import time

DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, DATA)
import rolesdata as RD          # noqa: E402
import build_states as BS       # noqa: E402
import build_signals as BG      # noqa: E402
from common import *            # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(777)


def part_states(coin, out):
    B = {h: bars(coin, h) for h in HTFS}
    names = roles()["roles"]["trend_incl_dual"]
    for htf in HTFS:
        df = B[htf]
        Z = RD._states(coin, htf)
        assert len(Z["ts"]) == len(df) and (Z["ts"] == df.ts.to_numpy()).all()
        n = len(df)
        cuts = sorted(set(rng.integers(400, n - 2, 4).tolist() + [n // 2]))
        for i in cuts:
            cut = df.iloc[: i + 1].reset_index(drop=True)
            nx = BS.NEXT_HTF[htf]
            nxt = None
            if nx is not None:
                nb_ = B[nx]
                nb_ = nb_[close_ms(nb_, nx) <= close_ms(df, htf)[i]].reset_index(drop=True)
                nxt = (nx, nb_)
            J = BS.judge_arrays(cut, htf)
            S = BS.cond_states(cut, htf, nxt)
            lo = max(0, i - 59)
            for k in ("j_V39", "j_S6", "j_OBV", "j_N12", "j_raw3", "j_dir"):
                d = int((np.asarray(J[k][lo:i + 1]) != Z[k][lo:i + 1]).sum())
                out.append({"part": "state", "coin": coin, "tf": htf, "cut": i, "key": k, "n_cmp": i + 1 - lo, "n_diff": d})
            for k in names:
                d = int((np.asarray(S[k][lo:i + 1]) != Z[f"c_{k}"][lo:i + 1]).sum())
                out.append({"part": "state", "coin": coin, "tf": htf, "cut": i, "key": f"c_{k}", "n_cmp": i + 1 - lo,
                            "n_diff": d})
        log(coin, htf, "states cut-tested", cuts)
    drop(coin)


def part_signals(coin, out, NAMES):
    BG.NAMES = NAMES
    N = RD.names()
    entry = set(N.name[N.role.isin(["range", "pullback", "breakout", "reversal", "timing", "other"])])
    Ball = {tf: bars(coin, tf) for tf in TFS + ("1d",)}
    drop(coin)
    btc = None
    if coin != "BTCUSDT":
        btc = {tf: bars("BTCUSDT", tf) for tf in TFS}
        drop("BTCUSDT")
    for tf in TFS:
        raw = Ball[tf]
        n = len(raw)
        W = 6000 if tf in ("15m", "30m") else 3000
        cuts = rng.integers(W + 500, n - 400, 3)
        for i in cuts:
            s = i - W
            tA = close_ms(raw, tf)[i + 300] if i + 300 < n else close_ms(raw, tf)[-1]
            tB = close_ms(raw, tf)[i]
            res = {}
            for lab, end, tcut in (("A", i + 301, tA), ("B", i + 1, tB)):
                rw = raw.iloc[s:end].reset_index(drop=True)
                bt = None
                if btc is not None:
                    bb = btc[tf]
                    bt = bb[(bb.ts >= rw.ts.iloc[0]) & (bb.ts <= rw.ts.iloc[-1])].reset_index(drop=True)
                # higher frames for FRIEND_ROC: only bars closed by the window's last close
                Bc = {h: Ball[h][close_ms(Ball[h], h) <= tcut].reset_index(drop=True) for h in ("1h", "4h", "1d")}
                res[lab] = BG.coin_signals(coin, tf, rw, bt, Bc)
            m = W + 1                       # bars s .. i in both
            for name in sorted(set(res["A"]) & set(res["B"])):
                if name not in entry:
                    continue
                la, sa = (np.asarray(x, bool) for x in res["A"][name])
                lb, sb = (np.asarray(x, bool) for x in res["B"][name])
                lo = m - 400
                d = int((la[lo:m] != lb[lo:m]).sum() + (sa[lo:m] != sb[lo:m]).sum())
                nsig = int(la[lo:m].sum() + sa[lo:m].sum())
                out.append({"part": "signal", "coin": coin, "tf": tf, "cut": int(i), "key": name, "n_cmp": 400,
                            "n_diff": d, "n_sig_A": nsig, "n_sig_B": int(lb[lo:m].sum() + sb[lo:m].sum())})
        log(coin, tf, "signals cut-tested", cuts.tolist())


def main():
    coins = sys.argv[1:] or list(COINS)
    out = []
    t0 = time.time()
    NAMES = pd.read_csv(os.path.join(OUT, "signals", "names.csv"))
    for coin in coins:
        part_states(coin, out)
        pd.DataFrame(out).to_csv(os.path.join(HERE, "la_causal.csv"), index=False)
    for coin in coins[:3]:
        part_signals(coin, out, NAMES)
        pd.DataFrame(out).to_csv(os.path.join(HERE, "la_causal.csv"), index=False)
    D = pd.DataFrame(out)
    D.to_csv(os.path.join(HERE, "la_causal.csv"), index=False)
    print(D.groupby("part")[["n_cmp", "n_diff"]].sum())
    bad = D[D.n_diff > 0]
    print("rows with differences:", len(bad))
    print(bad.groupby(["part", "key", "tf"]).n_diff.sum().to_string())
    log("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
