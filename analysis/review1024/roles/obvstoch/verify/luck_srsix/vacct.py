"""Verifier: one-position account of OBV30@4h>SRSI_X@1h|a2 in the last 19 days, re-derived with my own loop (no
rolesdata.one_position / account), and its coin-flip distribution: random side per taken trade (same trades) and a
re-simulated one-position bot with random sides on the same signals (its own exit times). Also family long/short split
and each coin's move over the 19 days from the 1m grid. Writes vacct.json. Run from this folder: python3 vacct.py"""
import json
import os
import sys

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O  # noqa: E402
from oscore import *  # noqa: E402,F401,F403

O.CACHE = "/dev/shm/claude_verify_srsix"
HERE = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(4242)


def signals(D, period):
    tf, htf, T, Ot, X = "1h", "4h", "OBV30", "SRSI_X", "a2"
    a, b = O.P[period]
    rows = []
    for ci, coin in enumerate(COINS):
        Z = D[coin]
        G = RD._grid(coin)
        e = Z["1h_e"]
        t = T0 + e * MIN
        sig, st = Z["1h_sig_SRSI_X"], Z["1h_st_4h_OBV30"]
        m = (t >= a) & (t < b) & (sig != 0) & (st == sig)
        j = e[m] // 60 - 1
        for k_ in range(int(m.sum())):
            jj = j[k_]
            rows.append({"t": int(t[m][k_]), "e": int(e[m][k_]), "coin": ci, "side": int(sig[m][k_]),
                         "rL": float(G["a2_1h_L_r"][jj]), "rS": float(G["a2_1h_S_r"][jj]),
                         "kL": int(G["a2_1h_L_k"][jj]), "kS": int(G["a2_1h_S_k"][jj]),
                         "wL": int(G["a2_1h_L_why"][jj]), "wS": int(G["a2_1h_S_why"][jj])})
    S = pd.DataFrame(rows)
    S = S[np.isfinite(S.rL) & np.isfinite(S.rS) & (S.wL != 3) & (S.wS != 3)]
    return S.sort_values(["e", "coin"]).reset_index(drop=True)


def one_pos(e, k):
    took, busy = [], -1
    for i in range(len(e)):
        if k[i] >= 0 and e[i] > busy:
            took.append(i)
            busy = e[i] + k[i]
    return np.array(took, int)


def acct(roe, margin=0.4):
    eq = np.cumprod(1 + margin * np.maximum(roe, -1))
    pk = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float(eq[-1]), float((1 - eq / pk).max())


if __name__ == "__main__":
    D = O.load_all()
    out = {}
    S = signals(D, "FWD")
    lev = 30.0
    roe = lev * np.where(S.side > 0, S.rL, S.rS)
    opp = lev * np.where(S.side > 0, S.rS, S.rL)
    out["signals"] = len(S)
    out["mean_roe"] = float(roe.mean())
    out["mean_roe_pb"] = float(roe.mean() + lev * PAYBACK)
    k = np.where(S.side > 0, S.kL, S.kS)
    tk = one_pos(S.e.to_numpy(), k)
    out["taken"] = len(tk)
    for pb in (0.0, lev * PAYBACK):
        tag = "pb" if pb else "nopb"
        out[f"acct40_{tag}"] = acct(roe[tk] + pb)
        out[f"acct40_twin_{tag}"] = acct(opp[tk] + pb)
        out[f"taken_mean_{tag}"] = float((roe[tk] + pb).mean())
        # coin flip on the same taken trades
        fx = []
        for _ in range(20000):
            s = rng.integers(0, 2, len(tk)).astype(bool)
            fx.append(acct(np.where(s, roe[tk], opp[tk]) + pb)[0])
        fx = np.array(fx)
        out[f"flip_same_trades_p_ge_obs_{tag}"] = float(np.mean(fx >= out[f"acct40_{tag}"][0]))
        out[f"flip_same_trades_median_{tag}"] = float(np.median(fx))
        # coin-flip bot re-simulated: random side per signal, its own exit times, one position
        rL, rS = lev * S.rL.to_numpy(), lev * S.rS.to_numpy()
        kL, kS = S.kL.to_numpy(), S.kS.to_numpy()
        ee = S.e.to_numpy()
        fb, fm = [], []
        for _ in range(5000):
            s = rng.integers(0, 2, len(S)).astype(bool)
            kk = np.where(s, kL, kS)
            t2 = one_pos(ee, kk)
            r2 = np.where(s, rL, rS)[t2] + pb
            fb.append(acct(r2)[0])
            fm.append(r2.mean())
        fb = np.array(fb)
        out[f"flip_bot_p_final_ge_obs_{tag}"] = float(np.mean(fb >= out[f"acct40_{tag}"][0]))
        out[f"flip_bot_median_final_{tag}"] = float(np.median(fb))
        out[f"flip_bot_p_mean_ge_obs_{tag}"] = float(np.mean(np.array(fm) >= out[f"taken_mean_{tag}"]))
    # family long / short pooled (160 cells)
    acc = {1: [0.0, 0], -1: [0.0, 0]}
    shares = []
    for c in O.cells():
        if not (c[2] in O.OBV_TRENDS and c[3] in O.SRSI):
            continue
        R = O.rows(D, *c, "FWD")
        for sd in (1, -1):
            m = R["side"] == sd
            acc[sd][0] += R["roe"][m].sum()
            acc[sd][1] += int(m.sum())
        if len(R["side"]):
            shares.append((R["side"] < 0).mean())
    out["fam_long_pooled"] = acc[1][0] / acc[1][1]
    out["fam_short_pooled"] = acc[-1][0] / acc[-1][1]
    out["fam_short_share_pooled"] = acc[-1][1] / (acc[1][1] + acc[-1][1])
    out["fam_short_share_mean_of_cells"] = float(np.mean(shares))
    # market moves from the 1m grid: open of 10-05 15:00 UTC .. last close
    mk = {}
    for coin in COINS:
        g = grid(coin)
        i0 = int((ms("2026-10-05 15:00") - T0) // MIN)
        mk[coin] = float(g["c"][g["n"] - 1] / g["o"][i0] - 1)
        drop(coin)
    out["market_move"] = mk
    out["S5y"] = None
    S5 = signals(D, "FIVE")
    out["five_signals"] = len(S5)
    out["five_mean"] = float((lev * np.where(S5.side > 0, S5.rL, S5.rS)).mean())
    SC = signals(D, "CONF")
    out["conf_signals"] = len(SC)
    out["conf_mean"] = float((lev * np.where(SC.side > 0, SC.rL, SC.rS)).mean())
    SC2 = SC[SC.t < ms("2026-10-05 15:00")]
    out["conf_excl_fwd_signals"] = len(SC2)
    out["conf_excl_fwd_mean"] = float((lev * np.where(SC2.side > 0, SC2.rL, SC2.rS)).mean())
    json.dump(out, open(os.path.join(HERE, "vacct.json"), "w"), indent=1, default=float)
    print(json.dumps(out, indent=1, default=float))
