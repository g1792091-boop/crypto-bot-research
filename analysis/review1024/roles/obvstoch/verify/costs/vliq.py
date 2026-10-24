"""Verifier: (1) how many friend-family a2 signals have a 2xATR stop beyond the 30x liquidation price (MMR 0.5 % / 1 %),
and the a2 family numbers when the exchange liquidates first (re-walk a2 with the stop capped at the liquidation price;
a trade stopped there loses the whole margin, -100 % ROE); (2) hold minutes and funding size per trade (w35)."""
import os, sys, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O
from oscore import *
from frloss import walk2
VC = "/dev/shm/claude_verify_cost"
HERE = os.path.dirname(os.path.abspath(__file__))
OUTJ = {}


def liq_walk(coin):
    G = RD._grid(coin); g = grid(coin); n = g["n"]
    o, h, l, c = g["o"], g["h"], g["l"], g["c"]; cumf = np.cumsum(g["fund"])
    res = {}
    for mmr in (0.005, 0.01):
        ld = 1.0 / 30 - mmr
        for tf in ("15m", "30m", "1h"):
            kk = TF_MIN[tf]; nb = n // kk; jt = np.arange(nb, dtype=np.int64); et = (jt + 1) * kk
            vt = (jt * kk >= g["first"]) & (et < n)
            atr = G[f"atr14_{tf}"]; atr = atr[:nb] if len(atr) >= nb else np.r_[atr, np.full(nb - len(atr), np.nan)]
            ok = vt & np.isfinite(atr); es = et[ok]; atrd = 2.0 * atr[ok] / o[es]
            beyond = atrd > ld
            atre = np.ascontiguousarray(np.minimum(atrd, ld))
            for lab, s in (("L", 1), ("S", -1)):
                a = walk2(o, h, l, c, cumf, es, s, 30.0, COST, FL, STEP, GAP, atre, -1.0, n)
                r = a[0].copy()
                r[beyond & (a[2] == 0)] = -1.0 / 30
                rr = np.full(nb, np.nan, np.float32); rr[ok] = r
                bb = np.zeros(nb, bool); bb[ok] = beyond
                res[f"{mmr}_{tf}_{lab}_r"] = rr; res[f"{mmr}_{tf}_beyond"] = bb
    np.savez(os.path.join(VC, f"liq_{coin}.npz"), **res)
    drop(coin); RD._GR.pop(coin, None)
    return coin


if __name__ == "__main__":
    from multiprocessing import get_context
    if "walk" in sys.argv:
        with get_context("fork").Pool(2) as pool:
            list(pool.imap_unordered(liq_walk, list(O.COINS)))
    # family A rows (with-trend), a2 at x1, the liquidation variants, and w35 hold / funding
    recs = []
    for per in ("SEL", "CONF", "FIVE", "FWD"):
        a, b = O.P[per]
        for (tf, htf) in O.MAPS:
            for T in O.OBV_TRENDS:
                for Ot in O.SRSI:
                    acc = {"base": [], "l05": [], "l10": [], "bey05": [], "bey10": [], "k": [], "nf_minus": []}
                    for coin in COINS:
                        Z = np.load(os.path.join(VC, f"{coin}.npz")); L = np.load(os.path.join(VC, f"liq_{coin}.npz"))
                        W = np.load(os.path.join(VC, f"walk_{coin}.npz"))
                        pre = f"{tf}_"; e = Z[pre + "e"]; t = T0 + e * MIN; tfm = TF_MIN[tf]
                        sig = Z[pre + "sig_" + Ot]; st = Z[f"{pre}st_{htf}_{T}"]
                        m = (t >= a) & (t < b) & (sig != 0) & (st == sig)
                        jt = np.clip(e // tfm - 1, 0, len(L[f"0.005_{tf}_L_r"]) - 1)
                        sd = sig[m]; jj = jt[m]
                        rb = np.where(sd > 0, Z[pre + "a2_L_r"][m], Z[pre + "a2_S_r"][m])
                        wb = np.where(sd > 0, Z[pre + "a2_L_w"][m], Z[pre + "a2_S_w"][m])
                        wo = np.where(sd > 0, Z[pre + "a2_S_w"][m], Z[pre + "a2_L_w"][m])
                        r05 = np.where(sd > 0, L[f"0.005_{tf}_L_r"][jj], L[f"0.005_{tf}_S_r"][jj])
                        r10 = np.where(sd > 0, L[f"0.01_{tf}_L_r"][jj], L[f"0.01_{tf}_S_r"][jj])
                        keep = np.isfinite(rb) & (wb != 3) & (wo != 3) & np.isfinite(r05)
                        acc["base"].append(30 * rb[keep]); acc["l05"].append(30 * r05[keep]); acc["l10"].append(30 * r10[keep])
                        acc["bey05"].append(L[f"0.005_{tf}_beyond"][jj][keep]); acc["bey10"].append(L[f"0.01_{tf}_beyond"][jj][keep])
                        j15 = np.clip(e // 15 - 1, 0, len(W["valid15"]) - 1)[m]
                        k = np.where(sd > 0, W["w35x1_L_k"][j15], W["w35x1_S_k"][j15])
                        r1 = np.where(sd > 0, W["w35x1_L_r"][j15], W["w35x1_S_r"][j15])
                        rn = np.where(sd > 0, W["w35nf_L_r"][j15], W["w35nf_S_r"][j15])
                        ww = np.where(sd > 0, W["w35x1_L_w"][j15], W["w35x1_S_w"][j15])
                        kp = np.isfinite(r1) & (ww != 3)
                        acc["k"].append(k[kp]); acc["nf_minus"].append(35 * (r1[kp] - rn[kp]))
                    q = {kk: np.concatenate(v) for kk, v in acc.items()}
                    recs.append(dict(period=per, tf=tf, htf=htf, trend=T, timing=Ot, n=len(q["base"]),
                                     a2=q["base"].mean(), a2_liq05=q["l05"].mean(), a2_liq10=q["l10"].mean(),
                                     beyond05=q["bey05"].mean(), beyond10=q["bey10"].mean(),
                                     hold_med=float(np.median(q["k"])), hold_mean=float(q["k"].mean()),
                                     fund_roe_mean=float(q["nf_minus"].mean()), fund_roe_absmean=float(np.abs(q["nf_minus"]).mean())))
    R = pd.DataFrame(recs)
    R.to_csv(os.path.join(HERE, "vliq_famA.csv"), index=False, float_format="%.6g")
    pd.set_option("display.width", 220)
    print(R.groupby("period")[["n", "a2", "a2_liq05", "a2_liq10", "beyond05", "beyond10", "hold_med", "hold_mean",
                               "fund_roe_mean", "fund_roe_absmean"]].mean().round(4).to_string())
