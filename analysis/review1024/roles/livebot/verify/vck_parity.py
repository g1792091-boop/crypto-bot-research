"""Verifier: the live trend bot's own log (10-22 design, bar close >= 2026-10-22 15:00 UTC) vs the B0 replay, both
directions (logged -> replay, and replay -> logged: a replay signal the bot never logged would hint at look-ahead in
the bitmaps). Run (no -I): python3 vck_parity.py <live-ac.db>  (sqlite read-only)"""
import os, sys, json, sqlite3
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import lb_core as L
from lb_core import *  # noqa
DB = sys.argv[1]
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = []
for i, bc, tf, strat, sym, side, ref, reft, st, data in c.execute(
        "select id, bar_close, timeframe, strategy, symbol, side, ref_price, ref_time, status, data from signal_log where bar_close >= ?",
        (L.P_OOS[0],)):
    d = json.loads(data)
    rows.append(dict(id=i, t=bc, tf=tf, name=d.get("strategy") or strat.split("@")[0], symbol=sym, side=side, status=st,
                     why=d.get("why", ""), source=d.get("source"), ref=ref, ref_time=reft))
D = pd.DataFrame(rows)
mem = set(L.MEMBERS18)
D = D[[(a, b) in mem for a, b in zip(D.name, D.tf)]].copy()
D["coin"] = D.symbol.map({s: i for i, s in enumerate(COINS)})
print("logged rows (18 members, since 10-22 15:00 UTC):", len(D), D.status.value_counts().to_dict(), "sources", D.source.value_counts().to_dict())
KO = [("주말", "blk"), ("나스닥", "blk"), ("경제", "blk"), ("추격", "chase"), ("못 읽어", "na"), ("보류(", "hold"),
      ("추세가", "against"), ("힘 약함", "weak"), ("끝물", "tired"), ("돌파형", "breakout"), ("너무 뻗음", "far_htf"),
      ("진입 자리 아님", "far_etf"), ("RSI", "rsi")]
def code(w, s):
    if s == "SUBMITTED":
        return ""
    for k, cc in KO:
        if k in str(w):
            return cc
    return "?" + str(w)[:30]
D["code"] = [code(w, s) for w, s in zip(D.why, D.status)]
end = ext_end()
S = L.candidates("B0", period=(L.P_OOS[0] - 30 * DAY, FWD[1]), keep_all=True)
S = S[(S.t >= L.P_OOS[0]) & (S.t < end)]
M = D.merge(S[["name", "tf", "coin", "side", "t", "why", "p0"]].rename(columns={"why": "rwhy"}),
            on=["name", "tf", "coin", "side", "t"], how="left")
print("found in replay:", M.rwhy.notna().sum(), "/", len(M), "  same first reason:", (M.code == M.rwhy).sum())
pd.set_option("display.width", 250)
print(M.loc[M.code != M.rwhy, ["t", "name", "tf", "symbol", "side", "status", "code", "rwhy", "why"]].assign(t=lambda x: kst(x.t)).to_string(max_colwidth=50))
X = S.merge(D[["name", "tf", "coin", "side", "t"]], on=["name", "tf", "coin", "side", "t"], how="left", indicator=True)
X = X[X._merge == "left_only"]
print("replay signals NOT in the log:", len(X))
if len(X):
    print(X[["t", "name", "tf", "symbol", "side", "why"]].assign(t=lambda x: kst(x.t)).to_string())
# ref price vs the replay's p0 (entry minute open) on logged rows
mm = M.rwhy.notna()
rel = (M.ref[mm] / M.p0[mm] - 1) * 1e4
print("ref_price vs replay p0 (bp): median", round(float(rel.median()), 2), "mean", round(float(rel.mean()), 2), "max |.|", round(float(rel.abs().max()), 1))
print("ref_time - bar close (s): median", float(((M.ref_time - M.t) / 1000).median()))
# paper trades of the trend bot since then
T = pd.DataFrame([dict(json.loads(d), id=i, acct=a) for i, a, d in
                  c.execute("select id, account_id, data from trades where entry_time >= ?", (L.P_OOS[0],))])
print("trades accounts:", T.acct.value_counts().to_dict() if len(T) else {})
P = T[T.acct == "COMBO@mix"].sort_values("entry_time") if len(T) else T
A = L.taken(S[S.why == ""].assign(dummy=0)) if (S.why == "").any() else S.iloc[:0]
print("paper trades:", len(P), " replay one-position trades:", len(A))
for _, p in P.iterrows():
    q = A[(A.t == p.entry_time) & (A.symbol == p.symbol)]
    print(" paper", kst(p.entry_time), p.symbol, p.strategy_id, p.timeframe, int(p.side), f"roe {p.roe:+.3f}", p.exit_reason,
          "| replay", (f"{q.iloc[0]['name']} {q.iloc[0].tf} {int(q.iloc[0].side)} roe {q.iloc[0].tb_roe:+.3f}" if len(q) else "-"))
for _, r in A.iterrows():
    if not ((P.entry_time == r.t) & (P.symbol == r.symbol)).any():
        print(" replay only:", kst(r.t), r.symbol, r["name"], r.tf, int(r.side), round(r.tb_roe, 3))
