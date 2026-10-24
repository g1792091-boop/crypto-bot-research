"""Look-ahead verifier, step 5: the research 1m grid vs the rule bot's own 1m bars (export current/live_bars.csv, read
in memory from the zip given as argv[1]; nothing extracted, nothing executed). Compares o/h/l/c on every overlapping
minute of the forward window per coin, and separately on the minutes the hand-checked trades walked through."""
import sys
import io
import zipfile
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa

zp = sys.argv[1]
with zipfile.ZipFile(zp) as z:
    with z.open("current/live_bars.csv") as f:
        LB = pd.read_csv(io.TextIOWrapper(f), usecols=["ts", "symbol", "open", "high", "low", "close"])
print("live_bars rows", len(LB), "symbols", sorted(LB.symbol.unique()))
print("range KST", kst([LB.ts.min(), LB.ts.max()]))
H = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "la_handcheck.csv"))
for coin in COINS:
    g = grid(coin)
    x = LB[LB.symbol == coin].drop_duplicates("ts").sort_values("ts")
    i = ((x.ts.to_numpy(np.int64) - T0) // MIN)
    ok = (i >= 0) & (i < len(g["o"]))
    i = i[ok]
    x = x[ok]
    out = {}
    for k, col in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
        d = np.abs(g[k][i] / x[col].to_numpy(float) - 1)
        out[k] = (int((d > 1e-9).sum()), float(np.nanmax(d)))
    fw = (x.ts >= FWD_A) & (x.ts < DATA_END)
    # minutes walked by the hand-checked trades of this coin
    hc = H[H.coin == coin]
    walked = set()
    for _, r in hc.iterrows():
        e = (pd.Timestamp(r.t_kst).value // 10**6 - 9 * HOUR - T0) // MIN
        walked.update(range(int(e), int(e) + int(max(r.k_mine, r.k_opp_mine)) + 1))
    w = np.isin(i, np.fromiter(walked, np.int64)) if walked else np.zeros(len(i), bool)
    dw = {k: int((np.abs(g[k][i[w]] / x[col].to_numpy(float)[w] - 1) > 1e-9).sum()) for k, col in
          (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))}
    print(coin, "overlap minutes", len(i), "in fwd window", int(fw.sum()), "of", int((DATA_END - FWD_A) // MIN),
          "| mismatches (n, max rel)", out, "| walked minutes covered", int(w.sum()), "of", len(walked), "mismatch", dw)
    drop(coin)
