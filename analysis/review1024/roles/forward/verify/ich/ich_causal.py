"""Adversarial check, part 2: are the ENTRY signals and the 1d trend states behind the 574 pooled H2 rows (a2 family
top 5) free of look-ahead?

  1  every core / DeepSeek row: is the same (strategy, tf, bar close, coin, side) in the rule bot's live signal log
     (the bot produced it in real time, so it cannot have used later bars)?
  2  every row NOT in the live log (library entries incl. the timing oscillators O1-O7, candles C1-C4, FRIEND_ROC, any
     unlogged core / ds): the strategy recomputed on bars CUT at the signal bar (last 3,000 bars, nothing after it;
     BTC context and higher bars cut the same way) must still give the same side on that last bar
  3  the 1d states of the three 4h cells (c_T5_ST10_3, Jlive, l_OBV_S) recomputed on 1d bars cut at the last closed
     1d bar (<= t) and compared with the stored state
  4  merged-entry counts under several keys; permutation p / BH q from the study's own files

    python3 ich_causal.py        (from this folder, without -I)
"""
import json
import os
import sys

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from fw_lib import *  # noqa: F401,F403
import build_signals as BS  # noqa: E402
import build_states as BST  # noqa: E402

OUTD = os.path.dirname(os.path.abspath(__file__))
FWD = "/home/user/crypto-bot-research/analysis/review1024/roles/forward"
CELLS = [("other", "4h", "1d", "c_T5_ST10_3"), ("breakout", "4h", "1d", "Jlive"), ("range", "4h", "1d", "l_OBV_S"),
         ("timing", "1h", "4h", "c_N07_ICHI_CMO"), ("reversal", "1h", "4h", "c_N07_ICHI_CMO")]
WIN = 3000
REP = {}

S = load("sig")
S = S[S.role != "trend"].reset_index(drop=True)
parts = []
for role, tf, htf, src in CELLS:
    D = S[(S.role == role) & (S.tf == tf)].copy()
    st = state(D, src, htf)
    w = (st.astype(int) * D.side.to_numpy(int)) == 1
    r = roe(D, "a2")
    ok = (D.t.to_numpy() >= SPLIT) & (D.a2_why.to_numpy() != 3) & np.isfinite(r) & (D.a2_k.to_numpy() >= 0)
    P_ = D[w & ok].copy()
    P_["cell"] = f"{role}|{tf}@{htf}:{src}"
    P_["roe_a2"] = r[w & ok]
    P_["state_src"], P_["state_htf"] = src, htf
    parts.append(P_)
P = pd.concat(parts, ignore_index=True)
assert len(P) == 574, len(P)

# ---------------------------------------------------------------- 4 merged counts + day CI
REP["merge"] = {}
for nm, key in (("cell_coin_e_side", ["cell", "coin", "e", "side"]), ("coin_tf_e_side", ["coin", "tf", "e", "side"]),
                ("coin_e_side", ["coin", "e", "side"]), ("name_coin_tf_e_side", ["name", "coin", "tf", "e", "side"])):
    U = P.drop_duplicates(key)
    REP["merge"][nm] = {"n": len(U), "mean": float(U.roe_a2.mean()), "nS": int((U.side < 0).sum()),
                        "mean_S": float(U.roe_a2[U.side < 0].mean()), "nL": int((U.side > 0).sum()),
                        "mean_L": float(U.roe_a2[U.side > 0].mean()),
                        "day_ci": day_boot_ci(U.roe_a2.to_numpy(), U.day.to_numpy())}
REP["pooled_day_ci"] = day_boot_ci(P.roe_a2.to_numpy(), P.day.to_numpy())

# ---------------------------------------------------------------- 1 live-log membership
F = RD.forward("rule")
F = F[F.tf.isin(TFS) & (F.coin >= 0)]
logged = set(zip(F.strategy, F.tf, F.t.astype(np.int64), F.coin.astype(int), F.side.astype(int)))
logged_cells = set(zip(F.strategy, F.tf))
P["in_log"] = [(n, tf, int(t), int(c), int(s)) in logged for n, tf, t, c, s in
               zip(P.name, P.tf, P.t, P.coin, P.side)]
P["cell_logged"] = [(n, tf) in logged_cells for n, tf in zip(P.name, P.tf)]
REP["live_log"] = {"rows": len(P), "in_live_log": int(P.in_log.sum()),
                   "core_ds_rows": int(P.set.isin(["core", "ds"]).sum()),
                   "core_ds_in_log": int((P.set.isin(["core", "ds"]) & P.in_log).sum()),
                   "core_ds_cell_logged_but_row_missing": int((P.set.isin(["core", "ds"]) & P.cell_logged & ~P.in_log).sum()),
                   "by_set": P.groupby("set").in_log.agg(["size", "sum"]).astype(int).to_dict("index")}
log("live log", REP["live_log"])

# ---------------------------------------------------------------- 2 truncation test for rows not in the live log
todo = P[~P.in_log]
trunc = []
for ci, coin in enumerate(COINS):
    sub = todo[todo.coin == ci]
    if not len(sub):
        continue
    B = {tf: bars(coin, tf) for tf in TFS + ("1d",)}
    drop(coin)
    btc = None
    if coin != "BTCUSDT":
        btc = {tf: bars("BTCUSDT", tf) for tf in TFS}
        drop("BTCUSDT")
    for (tf, t), g in sub.groupby(["tf", "t"]):
        raw = B[tf]
        bc = close_ms(raw, tf)
        i = int(np.searchsorted(bc, t))
        assert bc[i] == t, (coin, tf, t)
        lo = max(0, i - WIN + 1)
        rawc = raw.iloc[lo:i + 1].reset_index(drop=True)
        Bc = {h: B[h][close_ms(B[h], h) <= t].reset_index(drop=True) for h in B}
        btcc = None
        if btc is not None:
            bb = btc[tf]
            bbc = close_ms(bb, tf)
            j = int(np.searchsorted(bbc, t))
            btcc = bb.iloc[max(0, j - WIN + 1):j + 1].reset_index(drop=True)
            assert close_ms(btcc, tf)[-1] == t
        names = set(g.name)
        sig = BS.coin_signals(coin, tf, rawc, btcc, Bc, only=names)
        for _, r in g.iterrows():
            lg, sh = sig.get(r["name"], (None, None))
            if lg is None:
                cut = "missing"
            else:
                cut = 1 if bool(lg[-1]) else (-1 if bool(sh[-1]) else 0)
            trunc.append({"coin": coin, "tf": tf, "t": int(t), "name": r["name"], "set": r["set"], "cell": r.cell,
                          "side": int(r.side), "cut_side": cut, "roe_a2": r.roe_a2})
    log("trunc", coin, len(sub))
T = pd.DataFrame(trunc)
T.to_csv(os.path.join(OUTD, "ich_trunc.csv"), index=False)
T["same"] = T.cut_side.astype(str) == T.side.astype(str)
REP["truncation"] = {"rows": len(T), "same_side_on_cut_bars": int(T.same.sum()),
                     "by_set": T.groupby("set").same.agg(["size", "sum"]).astype(int).to_dict("index"),
                     "mismatches": T[~T.same].head(30).astype(str).to_dict("records"),
                     "mismatch_roe_mean": float(T.roe_a2[~T.same].mean()) if (~T.same).any() else None}
log("trunc", REP["truncation"]["rows"], REP["truncation"]["same_side_on_cut_bars"])

# ---------------------------------------------------------------- 3 1d states of the 4h cells on cut 1d bars
E = libs()
pi = E["pi"]
run = E["run"]
d1 = []
P4 = P[P.tf == "4h"]
for ci, coin in enumerate(COINS):
    sub = P4[P4.coin == ci]
    if not len(sub):
        continue
    D1 = bars(coin, "1d")
    drop(coin)
    c1 = close_ms(D1, "1d")
    for t, g in sub.groupby("t"):
        j = int(np.searchsorted(c1, t, side="right") - 1)       # last 1d bar with close <= t
        cut = D1.iloc[:j + 1].reset_index(drop=True)
        h, l_, c = (cut[k].to_numpy(float) for k in ("high", "low", "close"))
        _l, d3 = pi.exchange_supertrend(h, l_, c, 10, 3.0)
        st_t5 = int(np.sign(d3[-1])) if d3[-1] in (1, -1) else 0
        ja = BST.judge_arrays(cut, "1d")
        dirv, adx, adxp = float(ja["j_dir"][-1]), float(ja["j_adx"][-1]), float(ja["j_adx"][-2])
        jlive = int(dirv) if (adx >= 20 and not (adx > 40 and adx < adxp)) else 0
        lg, sh = run.core_module("OBV_S").signals(as_chart(cut, "1d"), "1d")
        lat = BST.latch_of(np.asarray(lg, bool), np.asarray(sh, bool) & ~np.asarray(lg, bool))
        row0 = g.iloc[0]
        for src, mine in (("c_T5_ST10_3", st_t5), ("Jlive", jlive), ("l_OBV_S", int(lat[-1]))):
            stored = int(state(g.iloc[[0]], src, "1d")[0])
            d1.append({"coin": coin, "t": int(t), "src": src, "stored": stored, "cut": mine,
                       "bar_close": int(c1[j]), "t_minus_close_h": (t - int(c1[j])) / HOUR})
D1R = pd.DataFrame(d1)
D1R.to_csv(os.path.join(OUTD, "ich_1d_states.csv"), index=False)
REP["d1_states"] = {"checks": len(D1R), "equal": int((D1R.stored == D1R.cut).sum()),
                    "by_src": D1R.assign(eq=D1R.stored == D1R.cut).groupby("src").eq.agg(["size", "sum"]).astype(int)
                    .to_dict("index"),
                    "mismatches": D1R[D1R.stored != D1R.cut].head(20).astype(str).to_dict("records")}
log("1d", REP["d1_states"]["checks"], REP["d1_states"]["equal"])

# ---------------------------------------------------------------- 4b permutation p and BH from the study files
N = pd.read_csv(os.path.join(FWD, "search_perm.csv"))
J = json.load(open(os.path.join(FWD, "search.json")))["summary"]
TO = json.load(open(os.path.join(FWD, "trendonly.json")))
act = J["a2_F"]["topk_h2_pooled"]
REP["perm"] = {"n_perm": len(N), "actual": act, "p_ge": float(np.mean(N["a2_F_topk_h2"] >= act)),
               "null_median": float(N["a2_F_topk_h2"].median()), "null_p95": float(N["a2_F_topk_h2"].quantile(0.95)),
               "trendonly_keys": list(TO.keys())[:10]}
print(json.dumps(REP, indent=1, default=str))
json.dump(REP, open(os.path.join(OUTD, "ich_causal.json"), "w"), indent=1, default=str)
