"""After PREREG4 (no new pre-registration; a read for the owners' Monday start): the friend's rules on 4h bars with the 4h ADX filter
and the friend's exits (net ROE -50 % stop, 10 % lock then 5 % steps), 30x, against the coin-flip twin (is there a direction skill
before costs?), and what each trade nets when part of the taker fee comes back later (TetherMax payback, outside the bot: the bot
still trades with 0.042 % in its levels, so the exits stay as they are and the refund is added per trade). P (15m) next to it.

    python3 -I frfee.py          -> research/friendroc/results6.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import ROWS, MARGIN, take, rnd, coin_flip
from frloss import PER, LEV
from frfamily import signals, outcomes, filt
from types import SimpleNamespace

TAKER, SLIP = 0.00042, 0.0002
FINAL_TAKERS = (0.00042, 0.0003, 0.0002, 0.0001, 0.0)       # the taker each side after the payback
PERIODS = ("select", "confirm", "oct2026", "last19")


def read(R, own, opp, use, twin=True):
    t = R.t.to_numpy(np.int64)
    out = {}
    for pn in PERIODS:
        a, z = PER[pn]
        m = use & (t >= a) & (t < z)
        idx = take(t, own["k"], m)
        roe = LEV * own["r"][idx]
        months = (z - a) / DAY / 30.44
        d = {"n": len(idx), "gross_roe_pct": rnd((roe.mean() + LEV * 2 * (TAKER + SLIP)) * 100, 2)}
        for f in FINAL_TAKERS:
            back = LEV * 2 * (TAKER - f)                            # refunded per trade, net ROE
            r2 = roe + back
            d[f"final{f * 100:.3f}"] = {"roe_pct": rnd(r2.mean() * 100, 2), "win": rnd((r2 > 0).mean(), 3),
                                        "month_m20_pct": rnd(0.2 * r2.mean() * 100 * len(idx) / months, 1),
                                        "month_m40_pct": rnd(0.4 * r2.mean() * 100 * len(idx) / months, 1)}
        if twin and len(idx):
            growth = np.log1p(np.maximum(MARGIN * roe, -1 + 1e-12)).sum()
            d["twin"] = coin_flip(SimpleNamespace(t=t), m, own, opp, LEV, roe.mean(), growth)
        out[pn] = d
    # months from 1 at margin 20 / 40 %, 2025-01 .. 2026-09, final taker 0.042 / 0.02 / 0.01 %
    idx = take(t, own["k"], use & (t >= ms("2025-01-01")) & (t < ms("2026-10-01")))
    mon = np.asarray(pd.to_datetime(t[idx] + KST, unit="ms").strftime("%Y-%m"))
    roe = LEV * own["r"][idx]
    for f in (0.00042, 0.0002, 0.0001):
        r2 = roe + LEV * 2 * (TAKER - f)
        for mg in (0.2, 0.4):
            x = np.maximum(mg * r2, -1.0)
            v = np.array([np.prod(1 + x[mon == q]) for q in pd.period_range("2025-01", "2026-09", freq="M").strftime("%Y-%m")])
            out[f"months2025_final{f * 100:.3f}_m{int(mg * 100)}"] = {"median": rnd(np.median(v), 3), "up": int((v > 1).sum()), "n": len(v),
                                                                     "worst": rnd(v.min(), 3), "best": rnd(v.max(), 3),
                                                                     "all": rnd(float(np.prod(v)), 3)}
    return out


def main():
    res = {}
    R4 = signals("4h")
    R4 = R4[R4.block == ""].reset_index(drop=True)
    O4 = outcomes(R4, -0.50, 0.10, 0.05, sides=("own", "opp"))
    res["4h_F4_friend_exits"] = read(R4, O4["own"], O4["opp"], filt(R4, "F4"))
    A = pd.read_pickle(ROWS)
    A = A[A.P & (A.block == "")].reset_index(drop=True)
    own = {q: A[f"L30_c042_own_{q}"].to_numpy() for q in ("r", "k", "why")}
    opp = {q: A[f"L30_c042_opp_{q}"].to_numpy() for q in ("r", "k", "why")}
    res["P_15m"] = read(A, own, opp, np.ones(len(A), bool))
    for nm, x in res.items():
        print(nm)
        for pn in PERIODS:
            d = x[pn]
            print(f"  {pn:8s} n{d['n']} gross {d['gross_roe_pct']} twin {d.get('twin', {}).get('pct_below')} |",
                  " | ".join(f"{k[5:]}: {v['roe_pct']} m20 {v['month_m20_pct']}" for k, v in d.items() if k.startswith("final")), flush=True)
        for k, v in x.items():
            if k.startswith("months"):
                print("  ", k, v, flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results6.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
