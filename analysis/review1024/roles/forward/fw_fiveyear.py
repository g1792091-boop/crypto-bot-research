"""A third, independent read of the forward picks: the same cells on the 5-year data (2020-03 .. 2026-10-22, never
used to pick them), per year and the last 15 months, with the coin-flip twin. Also the trend-only picks and the
pre-specified sets (the friend's OBV 4h + StochRSI 1h, the trend bot's 18 members with the live judge).
Writes fiveyear_picks.csv.  Run: python3 fw_fiveyear.py"""
import json
from fw_lib import *  # noqa: F401,F403

JK = ("V39", "S6", "OBV", "N12", "raw3", "dir", "adx", "adx_prev")


def load_cells(cells):
    """5-year signals of the cells' entries with the needed states (one frame per (names, tf))."""
    out = []
    for c in cells:
        a, _ = c["key"].split("|")
        if c["level"] == "E":
            S = RD.signals(names=[a], tfs=[c["tf"]], period="five")
        else:
            S = RD.signals(roles_=[a], tfs=[c["tf"]], period="five")
        if not len(S):
            continue
        S = RD.add_outcomes(S, ("w35", "a2"), opp=True)
        if c["src"].startswith("J"):
            J = RD.add_judge(S[["t", "e", "coin", "tf", "side"]], htf=c["htf"], check=False)
            for k in JK:
                S[f"J{c['htf']}_{k}"] = J[f"tj_{k}"].to_numpy()
        else:
            kind, nm = c["src"].split("_", 1)
            S = RD.add_states(S, c["htf"], [nm], kind=kind)
        al = state(S, c["src"], c["htf"]) * S.side.to_numpy()
        S["al"] = al
        S["cell"] = c["label"]
        S["year"] = pd.to_datetime(S.t, unit="ms").dt.year
        keep = ["cell", "t", "year", "coin", "side", "al"] + [f"{v}{s}_{x}" for v in ("w35", "a2") for s in ("", "_opp")
                                                            for x in ("r", "why")]
        out.append(S[keep])
    return out


def allbars(c):
    """Every bar close of tf in the 5 years, following the source's state (rows with state 0 dropped)."""
    a, b = RD.PERIODS["five"]
    rows = []
    for ci, coin in enumerate(COINS):
        z = RD._sigfile(coin)
        n, e0, tfm = int(z[f"{c['tf']}_n"]), int(z[f"{c['tf']}_e0"]), TF_MIN[c["tf"]]
        nb = np.arange(300, n)
        e = e0 + nb.astype(np.int64) * tfm
        t = T0 + e * MIN
        m = (t >= a) & (t < b)
        rows.append(pd.DataFrame({"tf": c["tf"], "coin": np.int8(ci), "side": np.int8(1), "t": t[m], "e": e[m], "nb": nb[m]}))
    S = pd.concat(rows, ignore_index=True)
    if c["src"].startswith("J"):
        J = RD.add_judge(S[["t", "e", "coin", "tf", "side"]], htf=c["htf"], check=False)
        for k in JK:
            S[f"J{c['htf']}_{k}"] = J[f"tj_{k}"].to_numpy()
    else:
        kind, nm = c["src"].split("_", 1)
        S = RD.add_states(S, c["htf"], [nm], kind=kind)
    st = state(S, c["src"], c["htf"])
    S = S[st != 0].copy()
    S["side"] = st[st != 0].astype(np.int8)
    S = RD.add_outcomes(S, ("w35", "a2"), opp=True)
    S["al"] = 1
    S["cell"] = c["label"]
    S["year"] = pd.to_datetime(S.t, unit="ms").dt.year
    return S


def main():
    P = pd.read_csv(os.path.join(HERE, "search_picks.csv"))
    cells = [{"level": r.level, "key": r.key, "tf": r.tf, "htf": r.htf, "src": r.src,
              "label": f"{r.exit}-{r.level}{r['rank']}:{r.key}@{r.htf}:{r.src}"} for _, r in P.iterrows()]
    to = json.load(open(os.path.join(HERE, "trendonly.json")))
    for v_, d_ in to.items():
        for i_, r_ in enumerate(d_["top5"][:1]):
            cells.append({"level": "B", "key": f"ALLBARS|{r_['tf']}", "tf": r_["tf"], "htf": r_["htf"], "src": r_["src"],
                          "label": f"trendonly-{v_}-1: {r_['tf']} 모든 봉 + {r_['src']} {r_['htf']}"})
    cells.append({"level": "E", "key": "O4_STOCHRSI_ZONE|1h", "tf": "1h", "htf": "4h", "src": "c_OBV_S",
                  "label": "friend: O4_STOCHRSI_ZONE 1h + OBV 4h"})
    rows = []
    for c in cells:
        if c["level"] == "B":
            fr = [allbars(c)]
        else:
            fr = load_cells([c])
        if not fr:
            continue
        D = fr[0]
        for v in ("w35", "a2"):
            r = np.maximum(LEV[v] * D[f"{v}_r"].to_numpy(), -1.0)
            ro = np.maximum(LEV[v] * D[f"{v}_opp_r"].to_numpy(), -1.0)
            ok = (D[f"{v}_why"].to_numpy() != 3) & np.isfinite(r)
            for per, m in [("5y", np.ones(len(D), bool)), ("late15m", D.t.to_numpy() >= ms("2025-07-01"))] + \
                    [(str(y), D.year.to_numpy() == y) for y in range(2020, 2027)]:
                for cl, code in (("with", 1), ("against", -1), ("all", None)):
                    mm = ok & m & ((D.al.to_numpy() == code) if code is not None else True)
                    if not mm.any():
                        continue
                    sd = D.side.to_numpy()[mm]
                    rows.append({"cell": c["label"], "exit": v, "period": per, "class": cl, "n": int(mm.sum()),
                                 "mean": float(np.mean(r[mm])), "win": float(np.mean(r[mm] > 0)),
                                 "opp": float(np.nanmean(ro[mm])), "mean_L": float(np.mean(r[mm][sd > 0])) if (sd > 0).any() else np.nan,
                                 "mean_S": float(np.mean(r[mm][sd < 0])) if (sd < 0).any() else np.nan,
                                 "nL": int((sd > 0).sum()), "nS": int((sd < 0).sum())})
        log(c["label"], len(D))
        for coin in COINS:
            drop(coin)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(HERE, "fiveyear_picks.csv"), index=False, float_format="%.5g")


if __name__ == "__main__":
    main()
