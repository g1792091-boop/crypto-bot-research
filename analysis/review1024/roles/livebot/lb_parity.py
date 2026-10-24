"""Does the B0 replay match what the live trend bot logged? (10-22 design, from 10-23 00:00 KST)
- every logged signal of the 18 members: same pass / fail and same first reason code;
- the paper account's trades (COMBO@mix) vs the replay's one-position trades.
Run: python3 lb_parity.py <live-ac.db path>  (sqlite opened read-only)."""
import json
import sqlite3
import sys

import lb_core as L
from lb_core import *  # noqa: F401,F403

KO2CODE = [("주말", "blk"), ("나스닥", "blk"), ("경제", "blk"), ("추격", "chase"), ("못 읽어", "na"), ("보류(", "hold"),
           ("추세가", "against"), ("힘 약함", "weak"), ("끝물", "tired"), ("돌파형", "breakout"), ("너무 뻗음", "far_htf"),
           ("진입 자리 아님", "far_etf"), ("RSI", "rsi")]


def code_of(why, status):
    if status == "SUBMITTED":
        return ""
    for k, c in KO2CODE:
        if k in str(why):
            return c
    return "?"


def main(db):
    D = RD.forward("trendbot")
    D = D[(D.bot == "trend") & (D.t >= L.P_OOS[0])].copy()
    D["code"] = [code_of(w, s) for w, s in zip(D.why, D.status)]
    S = L.candidates("B0", period=(L.P_OOS[0] - 30 * DAY, FWD[1]), keep_all=True)
    S = S[S.t >= L.P_OOS[0]]
    M = D.merge(S[["name", "tf", "coin", "side", "t", "why", "tb_roe", "tb_why", "tb_opp_roe"]].rename(
        columns={"name": "strategy", "why": "rwhy"}), on=["strategy", "tf", "coin", "side", "t"], how="left")
    print("logged rows", len(D), "found in replay", M.rwhy.notna().sum())
    eq = (M.code == M.rwhy)
    print("same reason code:", eq.sum(), "/", len(M))
    print(M.loc[~eq, ["t_kst", "strategy", "tf", "symbol", "side", "status", "code", "rwhy", "why"]].to_string(max_colwidth=60))
    extra = S.merge(D[["strategy", "tf", "coin", "side", "t"]].rename(columns={"strategy": "name"}),
                    on=["name", "tf", "coin", "side", "t"], how="left", indicator=True)
    extra = extra[extra._merge == "left_only"]
    print("replay signals not in the log:", len(extra))
    if len(extra):
        print(extra[["t", "name", "tf", "symbol", "side", "why"]].head(20).to_string())
    # trades
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    T = pd.DataFrame([dict(json.loads(d), id=i, acct=a) for i, a, d in
                      c.execute("select id, account_id, data from trades where entry_time >= ?", (L.P_OOS[0],))])
    P = T[T.acct == "COMBO@mix"]
    A = L.taken(S[S.why == ""])
    print("\npaper trades since 10-23 00:00 KST:", len(P), " replay one-position trades:", len(A))
    for _, p in P.sort_values("entry_time").iterrows():
        q = A[(A.t == p.entry_time) & (A.symbol == p.symbol)]
        rr = q.iloc[0] if len(q) else None
        print(kst(p.entry_time), p.symbol, p.strategy_id, p.timeframe, int(p.side), "paper roe %.3f %s" % (p.roe, p.exit_reason),
              "| replay:", (f"{rr['name']} {rr.tf} {int(rr.side)} roe {rr.tb_roe:.3f} why {int(rr.tb_why)}" if rr is not None else "-"))
    for _, rr in A.iterrows():
        if not ((P.entry_time == rr.t) & (P.symbol == rr.symbol)).any():
            print("replay only:", kst(rr.t), rr.symbol, rr["name"], rr.tf, int(rr.side), round(rr.tb_roe, 3))


if __name__ == "__main__":
    main(sys.argv[1])
