"""Principle-level reads on the forward data (NO selection: every group is fixed by role, mapping and judge before
looking). Writes in this folder:
  principle_roles.csv      role x mapping x judge x period x class (all / with / against / neutral)
  principle_sources.csv    every trend source (5 judge variants + 52 condition + 52 latch) x mapping, entries pooled
  baseline_trend.csv       follow each trend source at EVERY bar (no entry strategy) = trend luck of the period
  rulebot_split.csv        the rule bot's real paper trades (house exits) split by the live judge
  prespec.csv              pre-specified sets: the friend's OBV 4h + StochRSI 1h, the live trend bot's 18 members
  principle.json           key numbers for the report
Run: python3 fw_principle.py"""
import json
from fw_lib import *  # noqa: F401,F403

CLASSES = ("all", "with", "against", "neutral")


def stats(D, m, a, per):
    """Per-signal stats of rows m (each signal a separate trade) under w35 and a2; a = alignment (+1 with, -1 against,
    0 neutral) of the rows."""
    o = {"n": int(m.sum()), "per_day": m.sum() / DAYS[per]}
    if not m.any():
        return o
    side = D.side.to_numpy()[m]
    o["long_share"] = float(np.mean(side > 0))
    for v in ("w35", "a2"):
        x, y = roe(D, v)[m], roe(D, v, True)[m]
        o[f"{v}"] = np.nanmean(x)
        o[f"{v}_win"] = np.nanmean(np.where(np.isfinite(x), x > 0, np.nan))
        o[f"{v}_opp"] = np.nanmean(y)
        o[f"{v}_L"] = np.nanmean(x[side > 0]) if (side > 0).any() else np.nan
        o[f"{v}_S"] = np.nanmean(x[side < 0]) if (side < 0).any() else np.nan
    o["nL"], o["nS"] = int((side > 0).sum()), int((side < 0).sum())
    lo, hi = day_boot_ci(roe(D, "w35")[m], D.day.to_numpy()[m])
    o["w35_lo"], o["w35_hi"] = lo, hi
    return o


def main():
    S = load("sig")
    B = load("base")
    out = {}
    # ------------------------------------------------------------------ A. role x mapping x judge
    rows = []
    roles = sorted(S.role.unique())
    maps = list(MAPS) + [("auto", "auto")]
    for tf, htf in maps:
        if tf == "auto":
            parts = [(t_, h_) for t_, h_ in AUTO.items()]
        else:
            parts = [(tf, htf)]
        for j in JUDGES + ("JB",):
            if j == "JB" and tf != "auto":
                continue
            # alignment for every row under this mapping (NaN for rows outside it)
            a = np.full(len(S), -9, np.int8)
            for t_, h_ in parts:
                mt = S.tf.to_numpy() == t_
                if j == "JB":
                    w = S.tj_why_1022.to_numpy()
                    al = np.where(w == "", 1, np.where(w == "against", -1, 0)).astype(np.int8)
                else:
                    al = (state(S, j, h_) * S.side.to_numpy()).astype(np.int8)
                a[mt] = al[mt]
            for role in roles + ["ENTRY(추세형 제외)"]:
                mr = (S.role.to_numpy() != "trend") if role.startswith("ENTRY") else (S.role.to_numpy() == role)
                for per, (pa, pb) in PERIOD.items():
                    mp = (S.t.to_numpy() >= pa) & (S.t.to_numpy() < pb)
                    base = mr & mp & (a != -9)
                    for cl in CLASSES:
                        m = base if cl == "all" else base & (a == {"with": 1, "against": -1, "neutral": 0}[cl])
                        rows.append({"role": role, "tf": tf, "htf": htf, "judge": j, "period": per, "class": cl,
                                     **stats(S, m, a, per)})
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(HERE, "principle_roles.csv"), index=False, float_format="%.5g")
    log("principle_roles", len(R))

    # ------------------------------------------------------------------ B. every trend source, entries pooled
    rows = []
    srcs = list(JUDGES) + [f"c_{x}" for x in SOURCES] + [f"l_{x}" for x in SOURCES]
    ent = S.role.to_numpy() != "trend"
    for src in srcs:
        for tf, htf in list(MAPS) + [("auto", "auto")]:
            parts = list(AUTO.items()) if tf == "auto" else [(tf, htf)]
            a = np.full(len(S), -9, np.int8)
            for t_, h_ in parts:
                mt = S.tf.to_numpy() == t_
                a[mt] = (state(S, src, h_) * S.side.to_numpy())[mt]
            for per, (pa, pb) in PERIOD.items():
                mp = (S.t.to_numpy() >= pa) & (S.t.to_numpy() < pb) & ent & (a != -9)
                r = {"source": src, "tf": tf, "htf": htf, "period": per}
                for cl, code in (("with", 1), ("against", -1), ("neutral", 0)):
                    m = mp & (a == code)
                    x = roe(S, "w35")[m]
                    xa = roe(S, "a2")[m]
                    sd = S.side.to_numpy()[m]
                    r[f"n_{cl}"] = int(m.sum())
                    r[f"w35_{cl}"] = np.nanmean(x) if m.any() else np.nan
                    r[f"a2_{cl}"] = np.nanmean(xa) if m.any() else np.nan
                    r[f"w35_{cl}_L"] = np.nanmean(x[sd > 0]) if (sd > 0).any() else np.nan
                    r[f"w35_{cl}_S"] = np.nanmean(x[sd < 0]) if (sd < 0).any() else np.nan
                    r[f"nL_{cl}"], r[f"nS_{cl}"] = int((sd > 0).sum()), int((sd < 0).sum())
                rows.append(r)
    P = pd.DataFrame(rows)
    P["diff_w35"] = P.w35_with - P.w35_against
    P["diff_w35_L"] = P.w35_with_L - P.w35_against_L          # longs WITH an up trend vs longs AGAINST a down trend
    P["diff_w35_S"] = P.w35_with_S - P.w35_against_S
    P.to_csv(os.path.join(HERE, "principle_sources.csv"), index=False, float_format="%.5g")
    log("principle_sources", len(P))

    # ------------------------------------------------------------------ C. trend-only baseline at every bar
    rows = []
    for src in srcs:
        for tf, htf in MAPS:
            mt = B.tf.to_numpy() == tf
            st = state(B, src, htf)
            for per, (pa, pb) in PERIOD.items():
                mp = mt & (B.t.to_numpy() >= pa) & (B.t.to_numpy() < pb)
                r = {"source": src, "tf": tf, "htf": htf, "period": per, "n_bars": int(mp.sum())}
                for v in ("w35", "a2"):
                    L, Sx = roe(B, v), roe(B, v, True)
                    fol = np.where(st > 0, L, np.where(st < 0, Sx, np.nan))       # follow the trend side
                    r[f"{v}_follow"] = np.nanmean(fol[mp])
                    r[f"{v}_follow_L"] = np.nanmean(L[mp & (st > 0)]) if (mp & (st > 0)).any() else np.nan
                    r[f"{v}_follow_S"] = np.nanmean(Sx[mp & (st < 0)]) if (mp & (st < 0)).any() else np.nan
                    r[f"{v}_long_all"] = np.nanmean(L[mp])
                    r[f"{v}_short_all"] = np.nanmean(Sx[mp])
                r["share_up"] = float(np.mean(st[mp] > 0)) if mp.any() else np.nan
                r["share_down"] = float(np.mean(st[mp] < 0)) if mp.any() else np.nan
                rows.append(r)
    BT = pd.DataFrame(rows)
    BT.to_csv(os.path.join(HERE, "baseline_trend.csv"), index=False, float_format="%.5g")
    log("baseline_trend", len(BT))

    # ------------------------------------------------------------------ D. the rule bot's real trades
    F = RD.forward("rule")
    F = F[(F.taken == 1) & F.tr_roe.notna() & F.tf.isin(TFS) & (F.coin >= 0)].copy()
    F["is_flip"] = F.group.isin(["flip"])
    rows = []
    tot_loss = F.loc[~F.is_flip, "tr_pnl"].sum()
    for jcol, lab in (("tj_dir", "Jdir(auto)"), ("raw3", "Jraw3(auto)")):
        if jcol == "raw3":
            d = np.full(len(F), np.nan)
            for t_, h_ in AUTO.items():
                m = F.tf.to_numpy() == t_
                d[m] = F[f"j{h_}_raw3"].to_numpy()[m]
        else:
            d = F.tj_dir.to_numpy()
        al = np.sign(np.nan_to_num(d)) * F.side.to_numpy()
        for grp in ("strategies", "flip"):
            mg = F.is_flip.to_numpy() if grp == "flip" else ~F.is_flip.to_numpy()
            for rk in ("all", "trend", "nontrend"):
                mr = np.ones(len(F), bool) if rk == "all" else (F.role.to_numpy() == "trend") if rk == "trend" \
                    else (F.role.to_numpy() != "trend")
                for cl, code in (("all", None), ("with", 1), ("against", -1), ("neutral", 0)):
                    m = mg & mr & ((al == code) if code is not None else True)
                    x = F[m]
                    rows.append({"judge": lab, "group": grp, "roles": rk, "class": cl, "n": len(x),
                                 "tr_roe": x.tr_roe.mean(), "win": (x.tr_roe > 0).mean(), "pnl": x.tr_pnl.sum(),
                                 "share_of_loss": x.tr_pnl.sum() / tot_loss if grp == "strategies" else np.nan,
                                 "nL": int((x.side > 0).sum()), "nS": int((x.side < 0).sum()),
                                 "roe_L": x.tr_roe[x.side > 0].mean(), "roe_S": x.tr_roe[x.side < 0].mean(),
                                 "w35_recomp": (35 * x.w35_r).clip(lower=-1)[x.w35_why != 3].mean()})
    RB = pd.DataFrame(rows)
    RB.to_csv(os.path.join(HERE, "rulebot_split.csv"), index=False, float_format="%.5g")
    log("rulebot_split", len(RB))

    # ------------------------------------------------------------------ E. pre-specified sets (no selection)
    rows = []

    def pre(label, m, al, per_list=("all", "H1", "H2")):
        for per in per_list:
            pa, pb = PERIOD[per]
            mp = m & (S.t.to_numpy() >= pa) & (S.t.to_numpy() < pb)
            for cl, code in (("all", None), ("with", 1), ("against", -1), ("neutral", 0)):
                mm = mp & ((al == code) if code is not None else True)
                rows.append({"set": label, "period": per, "class": cl, **stats(S, mm, al, per)})

    side = S.side.to_numpy()
    for tf, htf in (("1h", "4h"), ("30m", "1h"), ("15m", "1h"), ("30m", "4h"), ("4h", "1d"), ("15m", "4h"),
                    ("1h", "1d")):
        m = (S.name.to_numpy() == "O4_STOCHRSI_ZONE") & (S.tf.to_numpy() == tf)
        pre(f"친구: OBV {htf} 추세 + 스토캐스틱RSI {tf}", m, (state(S, "c_OBV_S", htf) * side).astype(int))
    import json as _j
    mem = _j.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))["members"]
    mm = np.zeros(len(S), bool)
    for it in mem:
        mm |= (S.name.to_numpy() == it["strategy"]) & (S.tf.to_numpy() == it["tf"])
    w = S.tj_why_1022.to_numpy()
    alB = np.where(w == "", 1, np.where(w == "against", -1, 0))
    pre("추세판단 봇 18멤버(기본값) + 봇 전체 검사(10-22)", mm, alB)
    pre("추세판단 봇 18멤버(기본값) + 판단 방향만(Jdir auto)", mm, _auto_align(S, "Jdir"))
    nt = S.role.to_numpy() != "trend"
    pre("추세형 제외 모든 진입 + 봇 전체 검사(10-22)", nt, alB)
    for role in ("pullback", "range", "breakout", "reversal", "timing"):
        pre(f"{ROLE_KO[role]} 전부 + Jdir(auto)", S.role.to_numpy() == role, _auto_align(S, "Jdir"))
    PR = pd.DataFrame(rows)
    PR.to_csv(os.path.join(HERE, "prespec.csv"), index=False, float_format="%.5g")
    log("prespec", len(PR))

    # ------------------------------------------------------------------ key numbers
    out["n_signals"] = int(len(S))
    out["n_signals_entry"] = int(nt.sum())
    out["days"] = DAYS
    json.dump(out, open(os.path.join(HERE, "principle.json"), "w"), indent=1, default=float)


def _auto_align(S, src):
    a = np.zeros(len(S), np.int8)
    for t_, h_ in AUTO.items():
        mt = S.tf.to_numpy() == t_
        a[mt] = (state(S, src, h_) * S.side.to_numpy())[mt]
    return a


if __name__ == "__main__":
    main()
