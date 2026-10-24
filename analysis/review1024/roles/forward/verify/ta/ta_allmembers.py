"""Verifier: every forward signal of the 18 members -- live judge/check on truncated 300-bar windows vs the table's
tj_why_1022; presence both ways vs the rule bot's raw signal_log; my own one-position loop for a2 / w35.
Usage: python3 ta_allmembers.py <signal_log_csv>"""
import sys, os, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fw_lib import *  # noqa
from fw_combo import add_roe
from paperbot import trendjudge as TJ
import ta_handwalk_lib as HW

S = add_roe(load("sig"))
cfg = json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))
mem = cfg["members"]
mm = np.zeros(len(S), bool)
for it in mem:
    mm |= (S.name.to_numpy() == it["strategy"]) & (S.tf.to_numpy() == it["tf"])
M = S[mm].reset_index(drop=True)
rules = TJ.TrendRules.from_dict(cfg["trend"])
fg, pi = TJ.lib()
HTF = {"30m": "1h", "1h": "4h", "4h": "1d"}
cacheJ, cacheS = {}, {}
why = []
for q, r in M.iterrows():
    coin = COINS[int(r.coin)]
    g = grid(coin)
    t, tf, side = int(r.t), r.tf, int(r.side)
    h = HTF[tf]
    th = t - (t - T0) % (TF_MIN[h] * MIN)
    kj = (coin, h, th)
    if kj not in cacheJ:
        cacheJ[kj] = TJ.judge_frame(HW.mybars(g, TF_MIN[h], th), coin, h, rules, fg, pi)
    ks = (coin, tf, t)
    if ks not in cacheS:
        sb = HW.mybars(g, TF_MIN[tf], t)
        cacheS[ks] = (TJ.spot_frame(sb, tf, fg), float(sb.close.iloc[-1]))
    sp, px = cacheS[ks]
    w, _ = TJ.check(rules, r["name"], tf, side, px, cacheJ[kj], sp)
    why.append(w)
M["live_pass"] = np.array([w == "" for w in why])
M["tab_pass"] = M.tj_why_1022.to_numpy() == ""
print("member signals", len(M), "table pass", M.tab_pass.sum(), "live-fn pass", M.live_pass.sum(),
      "agree", (M.live_pass == M.tab_pass).mean())
print(M.loc[M.live_pass != M.tab_pass, ["t", "coin", "name", "tf", "side", "tj_why_1022"]].assign(live=[why[i] for i in np.flatnonzero(M.live_pass != M.tab_pass)]).to_string())
# presence vs the raw rule bot signal log
SL = pd.read_csv(sys.argv[1], usecols=["bar_close", "timeframe", "strategy", "symbol", "side", "status"])
SL = SL[SL.symbol.isin(COINS)]
mk = set((m["strategy"], m["tf"]) for m in mem)
SLm = SL[[(a, b) in mk for a, b in zip(SL.strategy, SL.timeframe)]]
logkeys = set(zip(SLm.bar_close, SLm.timeframe, SLm.strategy, SLm.symbol, SLm.side))
tabkeys = set(zip(M.t, M.tf, M.name, np.asarray(COINS)[M.coin.astype(int)], M.side.astype(int)))
lo = SLm.bar_close.min()
tab_in = {k for k in tabkeys if k[0] >= lo and k[0] <= SLm.bar_close.max()}
print("log member rows", len(SLm), "log span", kst(lo), kst(SLm.bar_close.max()))
print("table signals in log span", len(tab_in), "found in log", len(tab_in & logkeys), "log rows not in table",
      len(logkeys - tabkeys))
print(sorted(logkeys - tabkeys)[:20])
print(sorted(tab_in - logkeys)[:20])
# my own one-position loop, compare with RD.one_position
for v in ("a2", "w35"):
    X = M[M.tab_pass & (M[f"{v}_why"] != 3) & (M.t >= PERIOD["all"][0]) & (M.t < PERIOD["all"][1])].copy()
    X["prio"] = X.coin.astype(int) * 10 + X.tf.map({t: i for i, t in enumerate(TFS)}).astype(int)
    X = X.sort_values(["e", "prio"]).reset_index(drop=True)
    busy, took = -1, []
    for i, r in X.iterrows():
        if r.e > busy:
            took.append(i)
            busy = r.e + r[f"{v}_k"]
    Tm = X.loc[took]
    roe = np.maximum(30.0 * Tm[f"{v}_r"] if v == "a2" else 35.0 * Tm[f"{v}_r"], -1)
    eq = np.cumprod(1 + 0.4 * roe.to_numpy())
    h1 = Tm.t < SPLIT
    print(v, "my one-position:", len(Tm), "mean", round(roe.mean(), 5), "win", round((roe > 0).mean(), 4), "final x", round(eq[-1], 4),
          "H1", int(h1.sum()), round(roe[h1].mean(), 5), "H2", int((~h1).sum()), round(roe[~h1].mean(), 5))
