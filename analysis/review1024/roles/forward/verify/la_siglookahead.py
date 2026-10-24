"""Look-ahead verifier, step 3: do any of the 121 coded strategies (incl. the 22 entry strategies the rule bot does
not run live, so the 100 % live-log match does not cover them) use bars AFTER the signal bar?
For each coin x tf and a few cut bars inside the forward window: compute every strategy's signals on a window of bars
[cut-W, cut] and on [cut-W, cut+K] (same start, so the same warm-up) with the data layer's own code path
(build_signals.coin_signals), and compare the signals on bars cut-L .. cut. A difference = the signal at a bar
depends on later bars (look-ahead / repaint), or the code treats the last bar differently from the live bot.
Run from this folder without -I:  python3 la_siglookahead.py [cuts_per_tf] [coins]"""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
import build_signals as BS

NC = int(sys.argv[1]) if len(sys.argv) > 1 else 2
CO = sys.argv[2].split(",") if len(sys.argv) > 2 else list(COINS)
W, K, L = 2500, 120, 60


def window(df, i0, i1):
    return df.iloc[i0:i1 + 1].reset_index(drop=True)


def main():
    rng = np.random.default_rng(7)
    BS.NAMES = BS.names_table()
    rows = []
    allB = {}
    btcB = {tf: bars("BTCUSDT", tf) for tf in TFS}
    drop("BTCUSDT")
    for coin in CO:
        B = {tf: bars(coin, tf) for tf in TFS + ("1d",)}
        drop(coin)
        for tf in TFS:
            df = B[tf]
            bc = close_ms(df, tf)
            cand = np.flatnonzero((bc >= FWD_A) & (bc <= DATA_END - (K + 1) * TF_MIN[tf] * MIN))
            if tf == "4h":
                cand = np.flatnonzero((bc >= FWD_A - 30 * DAY) & (bc <= DATA_END - (K + 1) * 240 * MIN))
            for cut in rng.choice(cand, NC, replace=False):
                t_cut = int(bc[cut])
                outs = []
                for end in (cut, cut + K):
                    raw = window(df, cut - W, end)
                    t_end = int(close_ms(raw, tf)[-1])
                    Bh = {h: B[h][close_ms(B[h], h) <= t_end].reset_index(drop=True) for h in B}
                    btc = None
                    if coin != "BTCUSDT":
                        bb = btcB[tf]
                        bbc = close_ms(bb, tf)
                        j0 = int(np.searchsorted(bbc, close_ms(raw, tf)[0]))
                        j1 = int(np.searchsorted(bbc, t_end))
                        btc = bb.iloc[j0:j1 + 1].reset_index(drop=True)
                        assert len(btc) == len(raw), (coin, tf, len(btc), len(raw))
                    outs.append(BS.coin_signals(coin, tf, raw, btc, Bh))
                a, b = outs
                for name in a:
                    if name not in b:
                        continue
                    la, sa = np.asarray(a[name][0], bool), np.asarray(a[name][1], bool)
                    lb, sb = np.asarray(b[name][0], bool)[:len(la)], np.asarray(b[name][1], bool)[:len(sa)]
                    sl = slice(len(la) - L, len(la))
                    dl = int((la[sl] != lb[sl]).sum())
                    ds = int(((sa & ~la)[sl] != (sb & ~lb)[sl]).sum())
                    last = bool(la[-1] != lb[len(la) - 1] or (sa & ~la)[-1] != (sb & ~lb)[len(la) - 1])
                    rows.append({"coin": coin, "tf": tf, "cut_kst": str(kst([t_cut])[0]), "name": name,
                                 "n_sig_trunc": int(la[sl].sum() + (sa & ~la)[sl].sum()),
                                 "n_sig_full": int(lb[sl].sum() + (sb & ~lb)[sl].sum()),
                                 "diff_L": dl, "diff_S": ds, "diff_last_bar": last})
            log(coin, tf, "done")
    R = pd.DataFrame(rows)
    here = os.path.dirname(os.path.abspath(__file__))
    R.to_csv(os.path.join(here, "la_siglookahead.csv"), index=False)
    R["diff"] = R.diff_L + R.diff_S
    print("comparisons", len(R), "strategies", R.name.nunique(), "signals checked (trunc)", int(R.n_sig_trunc.sum()),
          "(full)", int(R.n_sig_full.sum()))
    bad = R[R["diff"] > 0]
    print("cells with any difference:", len(bad))
    if len(bad):
        print(bad.groupby(["name", "tf"]).agg(n=("diff", "size"), diff=("diff", "sum"), last=("diff_last_bar", "sum")).to_string())


if __name__ == "__main__":
    main()
