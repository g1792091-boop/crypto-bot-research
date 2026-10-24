"""Which checks of the trend bot removed winners and which removed losers?
1) whatif_checks.csv: every B0 candidate signal (18 members, 2020-03 .. 10-24), each check on its own; for the signals
   that fail ONLY that check (all other B0 checks pass) the mean net ROE if it had been taken alone (the bot's exits,
   no one-position rule), next to the signals that pass every check and the same rows' opposite side; per period.
2) whatif_live.csv: the live log rows (forward_trendbot, both designs + the wait shadow) with the replay's outcome of
   each signal (own and opposite side, the bot's exits), then per member and per logged reason.
3) whatif_members_fwd.csv: per member over the forward 19 days (rule-bot live signals): signals, passed, mean ROE.
Run: python3 lb_whatif.py"""
import lb_core as L
from lb_core import *  # noqa: F401,F403

B0_USE = ["blk", "na", "against", "chase", "weak", "tired", "breakout", "far_htf", "far_etf", "rsi"]   # hold allowed


def summarize(G):
    return pd.Series({"n": len(G), "roe": G.tb_roe.mean(), "opp_roe": G.tb_opp_roe.mean(), "win": (G.tb_roe > 0).mean(),
                      "short": (G.side < 0).mean()})


def part1():
    S = L.candidates("B0", keep_all=True)
    S = S[(S.tb_why != 3) & (S.tb_opp_why != 3) & S.period.ne("")].reset_index(drop=True)
    F = S[[f"f_{k}" for k in B0_USE]].to_numpy()
    nfail = F.sum(1)
    out = []
    for pn in ("select", "confirm", "late", "fwd"):
        P = S.period.to_numpy() == pn
        G = S[P & (nfail == 0)]
        out.append({"period": pn, "check": "PASS_ALL", **summarize(G)})
        for j, k in enumerate(B0_USE):
            only = P & (nfail == 1) & F[:, j]
            anyf = P & F[:, j]
            out.append({"period": pn, "check": k, "kind": "only", **summarize(S[only])})
            out.append({"period": pn, "check": k, "kind": "any", **summarize(S[anyf])})
        # the 보류 entries the 10-22 design allows (pass everything else, j_dir == 0)
        H = S[P & (nfail == 0) & (S.j_dir == 0)]
        out.append({"period": pn, "check": "hold_entries_allowed", **summarize(H)})
        W = S[P & (nfail == 0) & (S.j_dir != 0)]
        out.append({"period": pn, "check": "with_trend_entries", **summarize(W)})
    O = pd.DataFrame(out)
    O.to_csv(os.path.join(L.LB, "whatif_checks.csv"), index=False, float_format="%.5g")
    # per member in the forward 19 days and over the 5 years (passed signals, alone)
    M = []
    for pn in ("select", "confirm", "late", "fwd"):
        P = (S.period == pn) & (nfail == 0)
        for (nm, tf), G in S[P].groupby(["name", "tf"]):
            M.append({"period": pn, "member": f"{nm}@{tf}", **summarize(G),
                      "hold_share": (G.j_dir == 0).mean()})
    pd.DataFrame(M).to_csv(os.path.join(L.LB, "whatif_members.csv"), index=False, float_format="%.5g")
    return O


def part2():
    D = RD.forward("trendbot")
    D = D.rename(columns={"strategy": "name"})
    D = D[D.coin >= 0].copy()
    D["e"] = D.e.astype(np.int64)
    D["force"] = np.minimum(np.where(L.judge_exit_minute(D, L.HTF_OF) < 0, 2**62, L.judge_exit_minute(D, L.HTF_OF)),
                            np.where(L.rev_exit_minute(D) < 0, 2**62, L.rev_exit_minute(D)))
    D["force"] = np.where(D.force >= 2**62, -1, D.force)
    r, k, w = L.run_walk(D, "force")
    ro, ko, wo = L.run_walk(D, "force", opp=True)
    lev = lev_of(D.coin.to_numpy())
    D["tb_roe"], D["tb_why"], D["tb_opp_roe"], D["tb_opp_why"] = lev * r, w, lev * ro, wo
    D["design"] = np.where(D.t >= L.P_OOS[0], "10-22", "10-21")
    cols = ["bot", "design", "t_kst", "name", "tf", "symbol", "side", "status", "why", "tj_why_1021", "tj_why_1022",
            "tb_roe", "tb_why", "tb_opp_roe", "tb_opp_why", "tr_roe", "tr_exit_reason"]
    D[cols].to_csv(os.path.join(L.LB, "whatif_live.csv"), index=False, float_format="%.4g")
    return D


if __name__ == "__main__":
    O = part1()
    pd.set_option("display.width", 220)
    print(O.to_string())
    D = part2()
    print(D.groupby(["bot", "design", "status"]).agg(n=("tb_roe", "size"), roe=("tb_roe", "mean"), opp=("tb_opp_roe", "mean")))
