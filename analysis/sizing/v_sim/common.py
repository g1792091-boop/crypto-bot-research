"""Independent verifier code (does not import the sim code). Reads only sweep/data/is."""
import os
import numpy as np
import pandas as pd

SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad"
ISD = os.path.join(SCR, "sweep", "data", "is")
COINS = ["btcusd", "ethusd", "solusd", "xrpusd", "dogeusd", "ltcusd", "bchusd"]
TFMIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
HB = {"5m": 16, "15m": 16, "1h": 16, "4h": 4, "1d": 4}
LAM = {"5m": 8.0, "15m": 4.5, "1h": 1.5, "4h": 3 / 7, "1d": 1.5 / 7}
T0 = pd.Timestamp("2021-08-01", tz="UTC")
T1 = pd.Timestamp("2024-07-01", tz="UTC")

TAKER, MAKER, SLIP, FUND8, MMR = 0.0005, 0.0002, 0.0002, 0.0001, 0.005


def load(tf):
    out = {}
    for c in COINS:
        p = os.path.join(ISD, f"{c}-{tf}.csv")
        assert "/data/is/" in p
        df = pd.read_csv(p, usecols=["ts", "open", "high", "low", "close"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df[df.ts < T1].reset_index(drop=True)
        # my own ATR: Wilder via ewm(alpha=1/14, adjust=False) (seeding differs from the sim's SMA seed)
        pc = df.close.shift(1)
        tr = np.maximum(df.high - df.low, np.maximum((df.high - pc).abs(), (df.low - pc).abs()))
        tr.iloc[0] = df.high.iloc[0] - df.low.iloc[0]
        df["atrp"] = tr.ewm(alpha=1 / 14, adjust=False).mean() / df.close
        out[c] = df
    return out


def admissible(df, tf):
    H = HB[tf]
    n = len(df)
    ts = df.ts.values.astype("datetime64[m]").astype(np.int64)
    t = np.arange(n)
    ok = (t + H < n) & (t >= 60)
    tH = np.minimum(t + H, n - 1)
    ok &= (ts[tH] - ts) == H * TFMIN[tf]
    ok &= df.ts.values >= np.datetime64(T0.tz_localize(None))
    return ok


def exits(o, h, l, c, side, dl, sd, td, order="colour"):
    """o,h,l,c: (n, H) path arrays for bars t+1..t+H; entry = o[:,0]. side +-1 (n,).
    dl liquidation distance, sd stop distance (inf = none), td TP distance (price fractions), arrays (n,).
    Sequential over bars with an alive mask. Returns exit bar index j (0-based), code (1 tp,2 stop,3 liq,4 time), gross g."""
    n, H = o.shape
    E = o[:, 0]
    alive = np.ones(n, bool)
    code = np.full(n, 4, np.int8)
    g = np.zeros(n)
    jx = np.full(n, H - 1)
    useStop = sd < dl
    for j in range(H):
        # side-adjusted moves relative to entry
        op = side * (o[:, j] / E - 1)
        if side is not None:
            fav = np.where(side > 0, h[:, j] / E - 1, 1 - l[:, j] / E)
            adv = np.where(side > 0, 1 - l[:, j] / E, h[:, j] / E - 1)
        # 1) open gaps
        m = alive & (-op >= dl)
        code[m] = 3; g[m] = -dl[m]; jx[m] = j; alive &= ~m
        m = alive & useStop & (-op >= sd)
        code[m] = 2; g[m] = op[m]; jx[m] = j; alive &= ~m
        m = alive & (op >= td)
        code[m] = 1; g[m] = op[m]; jx[m] = j; alive &= ~m
        # 2) intrabar
        a_stop = useStop & (adv >= sd)
        a_liq = (~a_stop) & (adv >= dl)
        a_any = a_stop | a_liq
        f_tp = fav >= td
        if order == "colour":
            bull = c[:, j] >= o[:, j]
            advfirst = np.where(side > 0, bull, ~bull)
        elif order == "adv":
            advfirst = np.ones(n, bool)
        else:
            advfirst = np.zeros(n, bool)
        adv_win = alive & a_any & (advfirst | ~f_tp)
        tp_win = alive & f_tp & ~adv_win
        m = adv_win & a_stop
        code[m] = 2; g[m] = -sd[m]; jx[m] = j
        m = adv_win & a_liq
        code[m] = 3; g[m] = -dl[m]; jx[m] = j
        code[tp_win] = 1; g[tp_win] = td[tp_win]; jx[tp_win] = j
        alive &= ~(adv_win | tp_win)
    m = alive
    g[m] = side[m] * (c[m, H - 1] / E[m] - 1)
    return jx, code, g


def equity_ret(code, g, jx, M, L, tfm, c_in=TAKER + SLIP):
    """Per-trade equity return. Fees on NOTIONAL N = M*L."""
    N = M * L
    fund = FUND8 * (jx + 1) * tfm / 480.0
    c_out = np.where(code == 1, MAKER, TAKER + SLIP)
    r = N * (g - c_in - c_out - fund)
    r = np.where(code == 3, -M - N * (c_in + fund), r)
    return r
