"""PREREG7.md: the friend's exact rule as the owners gave it on 10/24 night (P7): 15m EMA21 vs EMA52, RSI26 vs 50, ROC9 crossing 0, and
on BOTH the last closed 1h and 4h bar RSI26 on the same side of 50 and ROC9 on the same side of 0; 40x on every coin, net ROE -50 %
stop, the ladder 12 -> 10 then 5 % steps; one position, the entry blocks, margin 40 %; the TetherMax payback (90 %) read per trade.
Then nine entry / trend candidates G1 .. G9 one at a time and the 28 pairs of G1 .. G8, picked on 2020-03 .. 2024-12, read once on
2025-01 .. 2026-09.

    python3 -I frrun.py build     (once, for the P features' helpers)
    python3 -I frand.py           -> research/friendroc/results10.json

`and_signals(tf, rsi_mode)` returns the same frame shape as frfamily.signals (t, coin, side, e, vr, adx4h, block, ...) for the
live bot's parity check."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frcore import _ind
from frrun import MARGIN, take, rnd, coin_flip
from frloss import PER, COST, FL, STEP, GAP, coin_features
from frdeep import walk3, per_stats, btc_arrays
from frp30 import weekdays
import hashlib
from types import SimpleNamespace

TF_MIN.setdefault("1d", 1440)
LEV40 = 40.0
TAKER = 0.00042
REFUND = LEV40 * 2 * TAKER * 0.90                         # TetherMax 90 %, net ROE per trade
VCUT = 0.64
SEED, DRAWS = 20261024, 2000


def coin_and(coin, tf, rsi_mode, btc):
    k = TF_MIN[tf]
    df = bars(coin, tf)
    c = df.close.to_numpy(float)
    I = _ind(c)
    bc = df.ts.to_numpy(np.int64) + k * MIN
    e21, e52, rsi, roc = I["e21"], I["e52"], I["rsi"], I["roc"]
    rocp, e21p, e52p = prev(roc), prev(e21), prev(e52)
    with np.errstate(invalid="ignore"):
        up = (e21 > e52) & (rsi > 50) & (rocp <= 0) & (roc > 0)
        dn = (e21 < e52) & (rsi < 50) & (rocp >= 0) & (roc < 0)
    warm = np.arange(len(c)) >= WARM15
    hl, hs, H = [], [], {}
    for htf in ("1h", "4h"):
        dh = bars(coin, htf)
        Ih = _ind(dh.close.to_numpy(float))
        hc = dh.ts.to_numpy(np.int64) + TF_MIN[htf] * MIN
        j = np.searchsorted(hc, bc, side="right") - 1
        ok = j >= WARMH
        jj = np.maximum(j, 1)
        r, s, sp = (np.where(ok, v, np.nan) for v in (Ih["roc"][jj], Ih["rsi"][jj], Ih["rsi"][jj - 1]))
        H[htf] = (r, s)
        with np.errstate(invalid="ignore"):
            if rsi_mode == "lt50":
                hl.append((s > 50) & (r > 0)); hs.append((s < 50) & (r < 0))
            else:                                               # G9: RSI26 lower / higher than the bar before
                hl.append((s > sp) & (r > 0)); hs.append((s < sp) & (r < 0))
    L = warm & up & hl[0] & hl[1]
    S = warm & dn & hs[0] & hs[1]
    g = grid(coin)
    e = (bc - T0) // MIN
    i = np.flatnonzero((L | S) & (e < g["n"]))
    side = np.where(L[i], 1, -1)
    v = df.volume.to_numpy(float)
    vm = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    R = pd.DataFrame({"t": bc[i], "coin": COINS.index(coin), "side": side, "e": e[i], "bar_open": df.ts.to_numpy(np.int64)[i],
                      "close": c[i], "e21": e21[i], "e21p": e21p[i], "e52": e52[i], "e52p": e52p[i], "rsi": rsi[i], "roc": roc[i],
                      "rocp": rocp[i], "1h_roc": H["1h"][0][i], "4h_roc": H["4h"][0][i], "1h_rsi": H["1h"][1][i], "4h_rsi": H["4h"][1][i]})
    R["entry_px"] = g["o"][R.e.to_numpy()]
    with np.errstate(all="ignore"):
        R["vr"] = v[i] / vm[i]
    F = coin_features(coin, R)
    for col in ("adx4h", "adx15", "p24_side", "p7_side", "chase"):
        R[col] = F[col].to_numpy()
    with np.errstate(invalid="ignore"):
        R["slope_with"] = np.where(side > 0, (e21[i] > e21p[i]) & (e52[i] > e52p[i]), (e21[i] < e21p[i]) & (e52[i] < e52p[i]))
    jb = np.searchsorted(btc["ts15"], R.bar_open.to_numpy(np.int64))
    okb = (jb < len(btc["ts15"])) & (btc["ts15"][np.minimum(jb, len(btc["ts15"]) - 1)] == R.bar_open.to_numpy(np.int64))
    R["btc_gap_side"] = np.where(okb, side * btc["gap15"][np.minimum(jb, len(btc["ts15"]) - 1)], np.nan)
    dd = bars(coin, "1d")
    Id = _ind(dd.close.to_numpy(float))
    jd = np.searchsorted(dd.ts.to_numpy(np.int64) + 1440 * MIN, R.t.to_numpy(np.int64), side="right") - 1
    okd = jd >= 52
    with np.errstate(invalid="ignore"):
        R["d1_with"] = np.where(okd, side * (Id["e21"][np.maximum(jd, 0)] - Id["e52"][np.maximum(jd, 0)]) > 0, np.nan)
    return R


def and_signals(tf="15m", rsi_mode="lt50"):
    btc = btc_arrays()
    R = pd.concat([coin_and(c, tf, rsi_mode, btc) for c in COINS], ignore_index=True)
    R = R.iloc[np.lexsort((R.coin.to_numpy(), R.t.to_numpy()))].reset_index(drop=True)
    R["block"] = [blocked(int(x)) for x in R.t.to_numpy()]
    return R


def outcomes40(R, sides=("own",)):
    bt = grid("BTCUSDT")
    bc_, bo_ = (np.ascontiguousarray(bt[x], dtype=np.float64) for x in ("c", "o"))
    out = {}
    for sn in sides:
        r = np.zeros(len(R)); k = np.zeros(len(R), np.int64); w = np.zeros(len(R), np.int8)
        for ci in range(6):
            g = grid(COINS[ci])
            cumf = np.cumsum(g["fund"])
            o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
            for side in (1, -1):
                m = ((R.coin == ci) & (R.side * (1 if sn == "own" else -1) == side)).to_numpy()
                if m.any():
                    a = walk3(o, h, l, c, cumf, R.e.to_numpy(np.int64)[m], side, LEV40, COST, FL, STEP, GAP, -0.5, 9.0, 0.0, 0,
                              np.zeros(1, bool), False, bc_, bo_, 0.0, g["n"])
                    r[m], k[m], w[m] = a
        out[sn] = {"r": r, "k": k, "why": w}
    return out


def gates(R):
    with np.errstate(invalid="ignore"):
        g1 = ~(R.adx4h.to_numpy() < 20)
        g2 = ~(R.vr.to_numpy() > VCUT)
        chase = (R.p24_side.to_numpy() >= 0.9) | (R.p7_side.to_numpy() >= 0.8)   # p*_side: 1 = the chasing end (PREREG2 F5)
        return {"G1 4시간 ADX 20 미만 금지": g1, "G2 조용한 봉만": g2, "G3 G1 + G2": g1 & g2,
                "G4 15분 EMA 둘 다 진입 방향으로 기울어야": R.slope_with.to_numpy(bool),
                "G5 추격 금지": ~chase, "G6 15분 ADX 20 미만 금지": ~(R.adx15.to_numpy() < 20),
                "G7 BTC 15분 EMA 같은 방향": ~(R.btc_gap_side.to_numpy() < 0),
                "G8 1일봉 EMA 같은 방향": ~(R.d1_with.to_numpy() == 0)}


def read(t, own, use, opp=None, refund=REFUND):
    out = {}
    for pn, (a, z) in PER.items():
        m = use & (t >= a) & (t < z)
        idx = take(t, own["k"], m)
        roe0 = LEV40 * own["r"][idx]
        roe = roe0 + refund
        months = (z - a) / DAY / 30.44
        d = {"n": int(len(idx)), "per_weekday": rnd(len(idx) / weekdays(a, z), 2), "win": rnd((roe > 0).mean(), 4),
             "avg_win_pct": rnd(roe[roe > 0].mean() * 100, 1), "avg_loss_pct": rnd(roe[roe <= 0].mean() * 100, 1),
             "roe_pct": rnd(roe.mean() * 100, 3), "roe_pct_no_payback": rnd(roe0.mean() * 100, 3),
             "liquidated": int((own["r"][idx] <= -1 / LEV40 + 1e-12).sum())}
        x = np.maximum(MARGIN * roe, -1.0)
        eq = np.cumprod(1 + x)
        d["mult40"] = rnd(eq[-1], 4)
        d["maxdd40"] = rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3)
        if opp is not None and pn in ("select", "confirm", "oct2026") and len(idx):
            growth = np.log1p(np.maximum(MARGIN * roe0, -1 + 1e-12)).sum()
            d["twin"] = coin_flip(SimpleNamespace(t=t), m, own, opp, LEV40, roe0.mean(), growth)["pct_below"]
        out[pn] = d
    return out


def short_goal(t, own, use, margins=(0.4, 0.6, 1.0)):
    a, z = ms("2020-03-01"), ms("2026-10-23")
    idx = take(t, own["k"], use & (t >= a) & (t < z))
    roe = LEV40 * own["r"][idx] + REFUND
    tt = t[idx]
    out = {}
    for mg in margins:
        lg = np.log(np.maximum(1 + mg * roe, 1e-9))
        cs = np.r_[0, np.cumsum(lg)]
        hits = {51: 0, 10: 0, 4: 0}
        ruin = n = 0
        ends = []
        for s in range(0, len(idx), 3):
            if tt[s] + 90 * DAY > z:
                break
            e = np.searchsorted(tt, tt[s] + 90 * DAY)
            path = cs[s + 1:e + 1] - cs[s]
            if not len(path):
                continue
            n += 1
            for x in hits:
                hits[x] += int(path.max() >= np.log(x))
            ruin += int(path.min() <= np.log(0.1))
            ends.append(path[-1])
        out[f"m{int(mg * 100)}"] = {"starts": n, **{f"x{x}": rnd(v / n, 4) for x, v in hits.items()}, "to_10pct_or_less": rnd(ruin / n, 3),
                                    "end_median": rnd(float(np.exp(np.median(ends))), 3)}
    return out


def main():
    want = open(os.path.join(RES_DIR, "PREREG7.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG7.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG7.md changed after it was frozen"
    R = and_signals("15m", "lt50")
    print("signal rows", len(R), R.block.value_counts().to_dict(), flush=True)
    R = R[R.block == ""].reset_index(drop=True)
    t = R.t.to_numpy(np.int64)
    O = outcomes40(R, ("own", "opp"))
    every = np.ones(len(R), bool)
    res = {"prereg7_sha256": sha, "refund_net_roe_pct": rnd(REFUND * 100, 3), "free_signals": int(len(R))}
    P7 = read(t, O["own"], every, O["opp"])
    P7["verdict"] = {"select_positive": bool(P7["select"]["roe_pct"] > 0), "confirm_positive": bool(P7["confirm"]["roe_pct"] > 0),
                     "confirm_twin_975": bool((P7["confirm"].get("twin") or 0) >= 0.975)}
    P7["verdict"]["edge"] = all(P7["verdict"].values())
    P7["short_goal"] = short_goal(t, O["own"], every)
    res["P7"] = P7

    def line(nm, d):
        return f"{nm:24s} " + " | ".join(f"{p[:4]} n{d[p]['n']} {d[p]['per_weekday']}/d w{d[p]['win']} aw{d[p]['avg_win_pct']} al{d[p]['avg_loss_pct']} "
                                          f"roe{d[p]['roe_pct']} (no pb {d[p]['roe_pct_no_payback']}) x40 {d[p]['mult40']} dd{d[p]['maxdd40']}"
                                          f"{' tw ' + str(d[p].get('twin')) if d[p].get('twin') is not None else ''}" for p in PER)

    print(line("P7", P7), flush=True)
    print("P7 verdict", P7["verdict"], "short goal", P7["short_goal"], flush=True)
    # the candidates
    G = gates(R)
    n7 = P7["select"]["n"]
    cand = {}
    for nm, m in G.items():
        cand[nm] = read(t, O["own"], m)
    R9 = and_signals("15m", "falling")
    R9 = R9[R9.block == ""].reset_index(drop=True)
    O9 = outcomes40(R9)
    cand["G9 1시간·4시간 RSI26 하락(직전 봉보다 낮음)"] = read(R9.t.to_numpy(np.int64), O9["own"], np.ones(len(R9), bool))
    for nm, d in cand.items():
        d["better_both_halves"] = bool(d["select"]["roe_pct"] > P7["select"]["roe_pct"] and d["confirm"]["roe_pct"] > P7["confirm"]["roe_pct"])
        print(line(nm, d), "| better both" if d["better_both_halves"] else "", flush=True)
    ok = [nm for nm, d in cand.items() if d["select"]["n"] >= 0.3 * n7]
    pick1 = max(ok, key=lambda nm: cand[nm]["select"]["roe_pct"])
    pairs = {}
    names = list(G)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            nm = f"{names[i][:2]} + {names[j][:2]}"
            pairs[nm] = read(t, O["own"], G[names[i]] & G[names[j]])
    okp = [nm for nm, d in pairs.items() if d["select"]["n"] >= 0.3 * n7]
    pick2 = max(okp, key=lambda nm: pairs[nm]["select"]["roe_pct"])
    for nm in sorted(okp, key=lambda nm: -pairs[nm]["select"]["roe_pct"])[:5]:
        print(line("pair " + nm, pairs[nm]), flush=True)
    res["candidates"], res["pairs"] = cand, pairs
    res["pick_single"], res["pick_pair"] = pick1, pick2
    res["recommend_single"] = bool(cand[pick1]["confirm"]["roe_pct"] > P7["confirm"]["roe_pct"])
    res["recommend_pair"] = bool(pairs[pick2]["confirm"]["roe_pct"] > P7["confirm"]["roe_pct"])
    # the picks in full: twin and the short goal
    for key, nm, mask_ in (("pick_single_full", pick1, G.get(pick1)), ("pick_pair_full", pick2, None)):
        if key == "pick_pair_full":
            a_, b_ = [n for n in names if n[:2] in pick2.split(" + ")]
            mask_ = G[a_] & G[b_]
        if mask_ is None:                                        # G9 is its own signal set
            continue
        d = read(t, O["own"], mask_, O["opp"])
        d["short_goal"] = short_goal(t, O["own"], mask_)
        res[key] = d
        print(line(key + " " + nm, d), flush=True)
        print("   short goal", d["short_goal"], flush=True)
    print("picks", pick1, res["recommend_single"], "|", pick2, res["recommend_pair"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results10.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
