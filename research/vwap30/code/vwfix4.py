"""참고 read, continued from vwfix3.py (no selection, every variant shown): 'VWAP 개선판' (PREREG_FWD1.md candidate A) with a
"no entry in a quiet / sideways market" rule, six ways of telling one, on the rule bot's run (to the data end), 2020-03 ..
2024-12 and 2025-01 .. 2026-09, trades per month next to each:
  H1 the trend bot's 4h vote must be WITH the side (a neutral 4h vote counts as sideways)
  H2 the trend bot's 1h vote must be with the side
  H3 4h ADX(14) below 20 (the trend bot's 4h judge file)
  H4 Choppiness Index (30m, 14) above 61.8
  H5 Kaufman efficiency ratio (30m, 20 bars) below 0.3
  H6 1h Bollinger band width (20, 2) in the lowest 30 % of the last 30 days

    python3 -I vwfix4.py   -> research/vwap30/fix4.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwfix2 import *


def quiet_values(coin, t):
    """(4h ADX, CHOP 30m, ER 30m, 1h BBW percentile) known at the signal times t (closed bars only)."""
    Z = np.load(os.path.join(JUDGE_DIR, f"{coin}.npz"))
    tc = Z["4h_tclose"]
    j = np.searchsorted(tc, t, side="right") - 1
    ok = (j >= 0) & (t - tc[np.maximum(j, 0)] < 2 * 240 * MIN)
    adx4 = np.where(ok, Z["4h_adx"].astype(float)[np.maximum(j, 0)], np.nan)
    df = bars(coin, "30m")
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    rs = lambda x, n, f: getattr(pd.Series(x).rolling(n), f)().to_numpy()
    with np.errstate(all="ignore"):
        chop = 100 * np.log10(rs(tr, 14, "sum") / (rs(h, 14, "max") - rs(l, 14, "min"))) / np.log10(14)
        er = np.abs(c - np.r_[np.full(20, np.nan), c[:-20]]) / rs(np.abs(np.diff(c, prepend=c[0])), 20, "sum")
    tcl = df.ts.to_numpy(np.int64) + 30 * MIN
    k = np.searchsorted(tcl, t, side="right") - 1
    chop_t, er_t = chop[np.maximum(k, 0)], er[np.maximum(k, 0)]
    d1 = bars(coin, "1h")
    c1 = d1.close.to_numpy(float)
    m = pd.Series(c1).rolling(20).mean().to_numpy()
    sd = pd.Series(c1).rolling(20).std(ddof=0).to_numpy()
    with np.errstate(all="ignore"):
        bbw = 4 * sd / m
    pct = pd.Series(bbw).rolling(720, min_periods=360).rank(pct=True).to_numpy()
    t1 = d1.ts.to_numpy(np.int64) + 60 * MIN
    k1 = np.searchsorted(t1, t, side="right") - 1
    return adx4, chop_t, er_t, pct[np.maximum(k1, 0)]


def main():
    lib = sweepsig.lib()
    parts = []
    for coin in COINS:
        R = rows_tf(coin, "30m", lib)
        O = outcomes_tf(coin, R, 30)
        R["r"], R["x"] = O["base"]
        R["adx4"], R["chop"], R["er"], R["bbw_pct"] = quiet_values(coin, R.t.to_numpy())
        parts.append(R)
        print("built", coin, len(R), flush=True)
    R = pd.concat(parts, ignore_index=True)
    t, coin = R.t.to_numpy(), R.coin.to_numpy()
    kst = pd.to_datetime(t + KST, unit="ms")
    wd = np.asarray(kst.dayofweek < 5)
    usop = np.array([bool(us_open_pause(int(x), 30, 30)) for x in t])
    macro = np.array([bool(EV.near(int(x), 30 * MIN, 30 * MIN)) for x in t])
    A = wd & ~usop & ~macro & ~(R.j4h.to_numpy() < 0) & ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy())
    lev_cap = 0.3 * np.minimum(LEVP, 0.5 / (2.0 * R.atrf.to_numpy() + COST_RT))
    V = [("A 그대로", A),
         ("H1 4시간 추세가 같은 방향일 때만(중립=횡보)", A & (R.j4h.to_numpy() > 0)),
         ("H2 1시간 추세가 같은 방향일 때만", A & (R.j1h.to_numpy() > 0)),
         ("H3 4시간 ADX 20 미만 금지", A & ~(R.adx4.to_numpy() < 20)),
         ("H4 초피니스 61.8 초과 금지", A & ~(R.chop.to_numpy() > 61.8)),
         ("H5 효율 비율 0.3 미만 금지", A & ~(R.er.to_numpy() < 0.3)),
         ("H6 1시간 볼린저 폭 하위 30% 금지", A & ~(R.bbw_pct.to_numpy() < 0.3))]
    per = {"17일": (START, DATA_END - MIN), "2020-03~2024-12": SEL, "2025-01~2026-09": (ms("2025-01-01"), ms("2026-10-01"))}
    months = {pn: (z - a) / DAY / 30.44 for pn, (a, z) in per.items()}
    res = {}
    for name, mask in V:
        row = {}
        for pn, (a, z) in per.items():
            m = mask & (t >= a) & (t < z)
            x = account2(t, coin, R.r.to_numpy(), R.x.to_numpy(), m, lev_cap)
            x["per_month"] = round(x["n"] / months[pn], 1)
            row[pn] = x
        res[name] = row
        print(name, " | ".join(f"{pn[:4]} n{v['n']}(월{v['per_month']}) {v['wins']}승{v['losses']}패 손절평균{v['avg_loss_roe']} "
                               f"net{v['avg_net_pct']} x{v['mult']} dd{v['maxdd']}" for pn, v in row.items()), flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "fix4.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
