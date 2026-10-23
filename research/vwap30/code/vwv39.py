"""참고 read: V3.9 1h (the rule bot's 22 wins 1 loss on the owners' 10/23 photo) at the rule bot's form (2 ATR stop + its
ladder, margin 30 % x 30x, every day, one position), with 'VWAP 개선판' (A) next to it: how far each trade went against
the entry before it closed (the worst net ROE at 30x on the 1m path, "물림"), how wins and losses split, the break-even
win rate, on the rule bot's run (2026-10-05 19:30 UTC .. the data end), 2020-03 .. 2024-12 and 2025-01 .. 2026-09.

    python3 -I vwv39.py   -> research/vwap30/v39.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwadd as AD
from vwadd import *
from multiprocessing import Pool

AD.PHOTO = [("V39_ALL", "1h", "V3.9 1시간")]


def mae_roe(coin, R):
    """Worst net ROE at 30x reached on the 1m path from the entry minute to the exit minute (incl.)."""
    g = grid(coin)
    out = np.zeros(len(R))
    for q, (e, s, x) in enumerate(zip(R.e.to_numpy(), R.side.to_numpy(), R.x.to_numpy())):
        p0 = g["o"][e]
        lo = g["l"][e:e + x + 1] if s > 0 else g["h"][e:e + x + 1]
        adverse = np.nanmin(s * (lo / p0 - 1))
        out[q] = LEVP * (adverse - COST_RT)
    return out


def book(R, a, z, every_day):
    R = R[(R.t >= a) & (R.t < z)]
    if not every_day:
        R = R[time_ok(R.t.to_numpy())]
    t, coin = R.t.to_numpy(), R.coin.to_numpy()
    o = np.lexsort((coin, t))
    ext = t[o] + (R.x.to_numpy()[o] + 1) * MIN
    idx = o[_take(t[o], ext, np.ones(len(o), bool))]
    return R.iloc[idx]


def summary(B):
    roe = LEVP * B.r.to_numpy()
    mae = B.mae.to_numpy()
    w, l = roe > 0, roe <= 0
    eq = np.cumprod(1 + 0.3 * np.minimum(B.lev.to_numpy(), LEVP) / LEVP * roe) if len(B) else np.array([1.0])
    aw, al = (float(roe[w].mean()) if w.any() else 0.0), (float(roe[l].mean()) if l.any() else 0.0)
    out = {"n": int(len(B)), "wins": int(w.sum()), "losses": int(l.sum()),
           "win": round(float(w.mean()), 4) if len(B) else None,
           "avg_win_roe_pct": round(aw * 100, 1), "avg_loss_roe_pct": round(al * 100, 1),
           "breakeven_win": round(-al / (aw - al), 4) if (aw - al) else None,
           "avg_net_pct": round(float(B.r.mean() * 100), 4) if len(B) else None,
           "mult_margin30": round(float(eq[-1]), 4),
           "wins_first_against": {}}
    for th in (0.1, 0.2, 0.3, 0.4):
        out["wins_first_against"][f"ROE -{int(th * 100)}% 이상 물림"] = round(float((mae[w] <= -th).mean()), 4) if w.any() else None
    out["wins_mae_median_pct"] = round(float(np.median(mae[w]) * 100), 1) if w.any() else None
    out["losses_mae_median_pct"] = round(float(np.median(mae[l]) * 100), 1) if l.any() else None
    return out


def main():
    lib = sweepsig.lib()
    with Pool(2) as pool:
        sig = dict(pool.map(AD.sig_job, COINS))
    rs = []
    for coin in COINS:
        R = rows_of(coin, "1h", sig[coin][("V39_ALL", "1h")])
        R["r"], R["x"] = outcomes_k(coin, R, 60)
        R["mae"] = mae_roe(coin, R)
        rs.append(R)
    V = pd.concat(rs, ignore_index=True)
    V["lev"] = np.minimum(LEVP, 0.5 / (2.0 * V.atrf.to_numpy() + COST_RT))
    print("V3.9 rows", len(V), flush=True)
    parts = []
    for coin in COINS:
        R = rows_tf(coin, "30m", lib)
        R["r"], R["x"] = outcomes_tf(coin, R, 30)["base"]
        R = R[time_ok(R.t.to_numpy()) & gates(R)].reset_index(drop=True)
        R["mae"] = mae_roe(coin, R)
        parts.append(R)
    A = pd.concat(parts, ignore_index=True)
    A["lev"] = np.minimum(LEVP, 0.5 / (2.0 * A.atrf.to_numpy() + COST_RT))
    res = {"data_end": DATA_END}
    for pn, (a, z) in PERS.items():
        res[pn] = {"V3.9 1시간 (규칙봇처럼 매일)": summary(book(V, a, z, True)),
                   "V3.9 1시간 (평일·발표·개장 금지)": summary(book(V, a, z, False)),
                   "VWAP 개선판 A": summary(book(A, a, z, False))}
        for k, v in res[pn].items():
            print(pn, k, json.dumps(v, ensure_ascii=False), flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "v39.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
