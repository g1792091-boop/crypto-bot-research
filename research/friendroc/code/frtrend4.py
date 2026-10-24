"""PREREG10.md: the owners' manual style (PREREG8 M: 15m friend signal, 1h OR 4h ROC9, 35x, screen +10 % / -20 %, stop first, one
position, the entry blocks, margin 40 %, the TetherMax payback 90 % per trade) with all four bigger-trend conditions at once (T4):
the last closed 1d EMA21 / EMA52 with the side, the last closed 4h ADX14 >= 20, BTC's 15m EMA21 / EMA52 not against the side, and
the signal bar's EMA21 and EMA52 both moving the trade's way (PREREG7 G8, G1, G7, G4). Each condition alone is read for reference.

    python3 -I frtrend4.py        -> research/friendroc/results14.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frcore import _ind
from frrun import rnd
from frloss import PER
from frfamily import signals
from frdeep import btc_arrays
from frbracket import run, detail
from frmanual2 import LEV, TP
import hashlib

TF_MIN.setdefault("1d", 1440)
HORIZONS = {"1시간": 60, "4시간": 240, "24시간": 1440}
OWNER_TRADES = {"10/21 20:15 롱": ("2026-10-21 20:15", 1), "10/23 00:00 숏": ("2026-10-23 00:00", -1)}   # KST signal-bar closes


def trend_columns(R):
    """frand.coin_and's slope_with, btc_gap_side and d1_with for the P frame's rows (same definitions)."""
    btc = btc_arrays()
    slope = np.zeros(len(R), bool)
    bgap = np.full(len(R), np.nan)
    d1 = np.full(len(R), np.nan)
    for ci, coin in enumerate(COINS):
        m = (R.coin == ci).to_numpy()
        if not m.any():
            continue
        t = R.t.to_numpy(np.int64)[m]
        s = R.side.to_numpy()[m]
        df = bars(coin, "15m")
        I = _ind(df.close.to_numpy(float))
        bc = df.ts.to_numpy(np.int64) + 15 * MIN
        i = np.searchsorted(bc, t)
        assert (bc[i] == t).all()
        e21, e52 = I["e21"], I["e52"]
        e21p, e52p = prev(e21), prev(e52)
        with np.errstate(invalid="ignore"):
            slope[m] = np.where(s > 0, (e21[i] > e21p[i]) & (e52[i] > e52p[i]), (e21[i] < e21p[i]) & (e52[i] < e52p[i]))
        bo = t - 15 * MIN
        jb = np.minimum(np.searchsorted(btc["ts15"], bo), len(btc["ts15"]) - 1)
        okb = btc["ts15"][jb] == bo
        bgap[m] = np.where(okb, s * btc["gap15"][jb], np.nan)
        dd = bars(coin, "1d")
        Id = _ind(dd.close.to_numpy(float))
        jd = np.searchsorted(dd.ts.to_numpy(np.int64) + 1440 * MIN, t, side="right") - 1
        with np.errstate(invalid="ignore"):
            d1[m] = np.where(jd >= 52, s * (Id["e21"][np.maximum(jd, 0)] - Id["e52"][np.maximum(jd, 0)]) > 0, np.nan)
    R = R.copy()
    R["slope_with"], R["btc_gap_side"], R["d1_with"] = slope, bgap, d1
    return R


def conditions(R):
    is_btc = (R.coin == COINS.index("BTCUSDT")).to_numpy()
    with np.errstate(invalid="ignore"):
        c = {"1일봉 EMA 같은 방향": ~(R.d1_with.to_numpy() == 0),
             "4시간 ADX 20 이상": ~(R.adx4h.to_numpy() < 20),
             "BTC 15분 EMA 같은 방향": is_btc | ~(R.btc_gap_side.to_numpy() < 0),
             "15분 EMA 둘 다 진입 방향으로 기울기": R.slope_with.to_numpy(bool)}
    return c


def direction(R, use):
    """Share of signals (no one-position pass) whose price went the trade's way 1 h / 4 h / 24 h after the entry (frwhy)."""
    t = R.t.to_numpy(np.int64)
    side = R.side.to_numpy()
    fwd = {h: np.full(len(R), np.nan) for h in HORIZONS}
    for ci in range(6):
        g = grid(COINS[ci])
        m = (R.coin == ci).to_numpy()
        e = R.e.to_numpy(np.int64)[m]
        for hn, mins in HORIZONS.items():
            j = np.minimum(e + mins - 1, g["n"] - 1)
            fwd[hn][m] = side[m] * (g["c"][j] / g["o"][e] - 1)
    out = {}
    for pn, (a, z) in PER.items():
        m = use & (t >= a) & (t < z)
        out[pn] = {"signals": int(m.sum())} | {hn: rnd(float(np.mean(fwd[hn][m] > 0)), 4) if m.any() else None for hn in HORIZONS}
    return out


def main():
    want = open(os.path.join(RES_DIR, "PREREG10.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG10.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG10.md changed after it was frozen"
    A = trend_columns(signals("15m"))
    res = {"prereg10_sha256": sha}
    # the owners' two hand trades inside the data (the blocks do not apply to the lookup)
    CA = conditions(A)
    doge = COINS.index("DOGEUSDT")
    res["owner_trades"] = {}
    for nm, (ts, sd) in OWNER_TRADES.items():
        t0 = ms(ts) - KST
        hit = np.flatnonzero(((A.coin == doge) & (A.t == t0) & (A.side == sd)).to_numpy())
        if not len(hit):
            res["owner_trades"][nm] = None
            print(nm, "no signal row", flush=True)
            continue
        q = int(hit[0])
        row = {k: bool(v[q]) for k, v in CA.items()} | {"all_four": bool(all(v[q] for v in CA.values())), "block": A.block.iat[q]}
        res["owner_trades"][nm] = row
        print(nm, row, flush=True)
    R = A[A.block == ""].reset_index(drop=True)
    C = conditions(R)
    every = np.ones(len(R), bool)
    t4 = np.logical_and.reduce(list(C.values()))
    O = run(R, TP, -0.20)
    Oo = run(R, TP, -0.20, flip=True)
    arms = {"M 조건 없음": every} | {f"+ {k}": v for k, v in C.items()} | {"T4 네 조건 모두": t4}
    res["pass_share"] = {k: rnd(float(v.mean()), 4) for k, v in arms.items()}
    res["arms"] = {}
    for nm, use in arms.items():
        d = detail(R, O, use, Oo if nm in ("M 조건 없음", "T4 네 조건 모두") else None)
        d["direction"] = direction(R, use)
        res["arms"][nm] = d
        print(f"== {nm} (pass {res['pass_share'][nm]:.1%})", flush=True)
        for p in PER:
            v = d[p]
            print(f"  {p:8s} n{v['n']} {v['per_weekday']}/d w{v['win']} be{v['breakeven_win']} aw{v['avg_win_pct']} al{v['avg_loss_pct']} "
                  f"roe{v['roe_pct']} (no pb {v['roe_pct_no_payback']}) x40 {v['mult40']} dd{v['maxdd40']} twin {v.get('twin')} | dir {d['direction'][p]}",
                  flush=True)
        print("  months", d["months"], "goal90", d["goal90"], flush=True)
    T = res["arms"]["T4 네 조건 모두"]
    T["doge"] = detail(R, O, t4 & (R.coin == doge).to_numpy())
    print("  T4 doge", {p: (T["doge"][p]["n"], T["doge"][p]["win"], T["doge"][p]["roe_pct"], T["doge"][p]["mult40"]) for p in PER}, flush=True)
    v = {"select_positive": bool(T["select"]["roe_pct"] > 0), "confirm_positive": bool(T["confirm"]["roe_pct"] > 0),
         "confirm_twin_975": bool(T["confirm"].get("twin") is not None and T["confirm"]["twin"] >= 0.975)}
    v["earns"] = all(v.values())
    res["verdict"] = v | {"text": "과거 기록상 버는 구조" if v["earns"] else "아님"}
    print("verdict", res["verdict"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results14.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
