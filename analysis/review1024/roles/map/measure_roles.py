"""Role map, measured part (analysis/review1024/roles/map): what each strategy's entries look like on 2021-01-01 ..
the data end, so the code-based role (추세형 / 횡보 자리 / 눌림 / 돌파 / 반전 / 타이밍) can be checked against behaviour.
No profit or loss is measured here (that is the other parts' job): only WHERE each signal fires.

Per strategy x timeframe (6 coins together), every signal bar of the period:
- prior20   share of signals whose side = the sign of close[t] - close[t-20] (the PROFILES.md '추세 비율';
            coin flip 0.5; >= 0.6 enters with the last move = trend / chase, <= 0.4 against it = pullback / fade)
- htf_with  share of signals whose side = the trend bot's judgment (3 of the 4 judges V39 / S6 / OBV / N12,
            paperbot/trendjudge.vote_arrays, the raw vote without the hold) on the last CLOSED higher bar
            (15m and 30m -> 1h, 1h -> 4h, 4h -> 1d); htf_against = opposite; htf_hold = no 3-of-4 side.
            agree = with / (with + against): the coin-flip value is 0.5 on the same signal times.
- ema_med   median of side * (close - EMA20) / ATR14 at the signal bar (positive = entering beyond EMA20 in the
            trade's direction, negative = entering on the other side of EMA20, i.e. buying below it / selling above)
- per_day   signals per day, 6 coins together

Sets: the 36 core strategies (research/entry_study/param_defs, the locked rules), the 44 DeepSeek definitions
(research/fullgrid/ds_defs.py, default numbers = lib_c), the 40 library entries (research/library/lib.py; the +F200
twins are the same entries filtered by EMA200 and are not measured separately), the friend's FRIEND_ROC
(research/friendroc/code/frfamily.tf_signals rules, higher mode roc_any) and the reel H1 on 5m (its 1h judge).

Data: research/newlive's 1m grid (research/vwap30/code/vwcommon.grid), bars built here on the UTC grid.
Run (from this folder, not with -I: pandas):  python3 measure_roles.py frames <scratch>  then
python3 measure_roles.py measure <scratch> [procs]   (writes roles_measured.csv next to this file)."""
import os
import sys
import time
import json
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
for _p in (REPO, os.path.join(REPO, "research", "vwap30", "code"), os.path.join(REPO, "research", "fullgrid")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
warnings.filterwarnings("ignore")
os.environ.setdefault("FULLGRID_MEMO_MB", "300")

import numpy as np
import pandas as pd

COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
TFS = ("15m", "30m", "1h", "4h")
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
HTF_OF = {"5m": "1h", "15m": "1h", "30m": "1h", "1h": "4h", "4h": "1d"}
MIN = 60_000
P0 = int(pd.Timestamp("2021-01-01", tz="UTC").value // 1_000_000)


def build_bars(g, k, T0):
    n = g["n"] // k * k
    o = g["o"][:n:k]
    c = g["c"][k - 1:n:k]
    h = np.nanmax(g["h"][:n].reshape(-1, k), axis=1)
    lo = np.nanmin(g["l"][:n].reshape(-1, k), axis=1)
    v = np.nansum(g["v"][:n].reshape(-1, k), axis=1)
    ts = T0 + np.arange(n // k, dtype=np.int64) * k * MIN
    first_bar = -(-g["first"] // k)
    sl = slice(first_bar, None)
    return pd.DataFrame({"ts": ts[sl], "open": o[sl], "high": h[sl], "low": lo[sl], "close": c[sl],
                         "volume": v[sl]}).reset_index(drop=True)


def cmd_frames(scr):
    import vwcommon as VW
    os.makedirs(os.path.join(scr, "frames"), exist_ok=True)
    for coin in COINS:
        g = VW.grid(coin)
        for tf, k in TF_MIN.items():
            df = build_bars(g, k, VW.T0)
            df.to_pickle(os.path.join(scr, "frames", f"{tf}_{coin}.pkl"))
            print(coin, tf, len(df), flush=True)
        VW._GRID.pop(coin, None)
    json.dump({"data_end": int(VW.DATA_END)}, open(os.path.join(scr, "frames", "meta.json"), "w"))


def load(scr, tf, coin):
    df = pd.read_pickle(os.path.join(scr, "frames", f"{tf}_{coin}.pkl"))
    return df


def as_chart(df, tf):
    d = df.copy()
    d["ts"] = pd.to_datetime(d["ts"].to_numpy(np.int64), unit="ms", utc=True)
    d.attrs["tf"] = tf
    return d


_LIB = {}


def libs():
    if not _LIB:
        import importlib.util
        from paperbot import sweepsig
        L = sweepsig.lib()
        spec = importlib.util.spec_from_file_location("fullgrid_run_roles", os.path.join(REPO, "research", "fullgrid", "run.py"))
        run = importlib.util.module_from_spec(spec)
        sys.modules["fullgrid_run_roles"] = run
        spec.loader.exec_module(run)
        sys.path.insert(0, os.path.join(REPO, "research", "search"))
        spec2 = importlib.util.spec_from_file_location("research_library_lib", os.path.join(REPO, "research", "library", "lib.py"))
        lib = importlib.util.module_from_spec(spec2)
        sys.modules["research_library_lib"] = lib
        spec2.loader.exec_module(lib)
        sys.path.insert(0, os.path.join(REPO, "research", "reel5m"))
        spec3 = importlib.util.spec_from_file_location("lib_reel5m_roles", os.path.join(REPO, "research", "reel5m", "lib_reel5m.py"))
        reel = importlib.util.module_from_spec(spec3)
        sys.modules["lib_reel5m_roles"] = reel
        spec3.loader.exec_module(reel)
        from paperbot import trendjudge as TJ
        _LIB.update(fg=L.fg, pi=L.pi, run=run, lib=lib, reel=reel, TJ=TJ)
    return _LIB


def htf_dir(scr, coin, htf):
    """(close ms of each htf bar, raw 3-of-4 direction) of the trend bot's judges."""
    E = libs()
    df = load(scr, htf, coin)
    arr = E["TJ"].vote_arrays(df, E["fg"], E["pi"])
    raw = E["TJ"].raw_votes(arr, 3)
    return df["ts"].to_numpy(np.int64) + TF_MIN[htf] * MIN, raw


def friend_signals(df, scr, coin, tf):
    E = libs()
    fg = E["fg"]
    c = df["close"].astype(float).reset_index(drop=True)
    e21, e52 = fg.ema(c, 21).to_numpy(float), fg.ema(c, 52).to_numpy(float)
    rsi, roc = fg.rsi(c, 26).to_numpy(float), fg.roc(c, 9).to_numpy(float)
    rocp = np.r_[np.nan, roc[:-1]]
    with np.errstate(invalid="ignore"):
        up = (e21 > e52) & (rsi > 50) & (rocp <= 0) & (roc > 0)
        dn = (e21 < e52) & (rsi < 50) & (rocp >= 0) & (roc < 0)
    higher = {"15m": ("1h", "4h"), "30m": ("1h", "4h"), "1h": ("4h", "1d"), "4h": ("1d", "1d")}[tf]
    bc = df["ts"].to_numpy(np.int64) + TF_MIN[tf] * MIN
    H = []
    for htf in higher:
        dh = load(scr, htf, coin)
        r = fg.roc(dh["close"].astype(float).reset_index(drop=True), 9).to_numpy(float)
        hc = dh["ts"].to_numpy(np.int64) + TF_MIN[htf] * MIN
        j = np.searchsorted(hc, bc, side="right") - 1
        H.append(np.where(j >= 60, r[np.maximum(j, 1)], np.nan))
    with np.errstate(invalid="ignore"):
        L = up & ((H[0] > 0) | (H[1] > 0))
        S = dn & ((H[0] < 0) | (H[1] < 0))
    L[:200] = False
    S[:200] = False
    return L, S & ~L


def reel_signals(df):
    E = libs()
    R = E["reel"]
    ind = R.indicators(df)
    P = R.Prep(ind, "SMA200", "CLOSE", "LONG")
    env = R.env()
    cost = env["L"]._cost("5m", R.MAX_HOLD)
    _tr, sigs, _sk = R.simulate(P, cost, 200, len(df) - 1, "open", trade=False)
    L = np.zeros(len(df), bool)
    for s in sigs:
        L[s["signal_idx"]] = True
    return L, np.zeros(len(df), bool)


def all_signals(scr, coin, tf):
    """{(set, name): (long, short)} for one coin and timeframe."""
    E = libs()
    run, lib = E["run"], E["lib"]
    raw = load(scr, tf, coin)
    df = as_chart(raw, tf)
    out = {}
    t0 = time.time()
    run.M.clear()
    for name in run.core_names():
        try:
            lg, sh = run.core_module(name).signals(df, tf)
            out[("core", name)] = (np.asarray(lg, bool), np.asarray(sh, bool))
        except Exception as exc:  # noqa: BLE001
            print("core", name, tf, coin, "ERR", exc, flush=True)
    run.M.clear()
    t1 = time.time()
    ds = run.ds_module()
    ctx = None if coin == "BTCUSDT" else {"BTCUSD": as_chart(load(scr, tf, "BTCUSDT"), tf)}
    cache = {}
    for name in ds.DEFS:
        if tf not in ds.TFS_OF[name]:
            continue
        try:
            lg, sh = ds.signals(df, tf, name, ctx=ctx, coin=coin[:-1], cache=cache)
            out[("ds", name)] = (np.asarray(lg, bool), np.asarray(sh, bool))
        except Exception as exc:  # noqa: BLE001
            print("ds", name, tf, coin, "ERR", exc, flush=True)
    cache.clear()
    t2 = time.time()
    dfl = raw.copy()
    dfl.attrs["tf"] = tf
    E2 = lib.entries(dfl, E["fg"], E["pi"])
    for k, v in E2.items():
        if not k.endswith("+F200"):
            out[("lib", k)] = v
    t3 = time.time()
    out[("friend", "FRIEND_ROC")] = friend_signals(raw, scr, coin, tf)
    print(f"{coin} {tf}: core {t1 - t0:.0f}s ds {t2 - t1:.0f}s lib {t3 - t2:.0f}s", flush=True)
    return raw, out


def measure_one(args):
    scr, coin, tf = args
    E = libs()
    if tf == "5m":
        raw = load(scr, "5m", coin)
        sig = {("reel", "REEL5M_BB_MA200"): reel_signals(raw)}
    else:
        raw, sig = all_signals(scr, coin, tf)
    fg = E["fg"]
    c = raw["close"].to_numpy(float)
    ema20 = fg.ema(raw["close"].astype(float).reset_index(drop=True), 20).to_numpy(float)
    atr = fg.atr(raw.reset_index(drop=True), 14).to_numpy(float)
    prior = np.sign(c - np.r_[np.full(20, np.nan), c[:-20]])
    bc = raw["ts"].to_numpy(np.int64) + TF_MIN[tf] * MIN
    hc, hraw = htf_dir(scr, coin, HTF_OF[tf])
    j = np.searchsorted(hc, bc, side="right") - 1
    hd = np.where(j >= 0, hraw[np.maximum(j, 0)], 0).astype(int)
    inper = bc >= P0
    days = (bc[inper][-1] - bc[inper][0]) / 86_400_000 if inper.any() else 0.0
    base_dir = hd[inper]
    rows = []
    for (st, name), (lg, sh) in sig.items():
        lg = np.asarray(lg, bool) & inper
        sh = np.asarray(sh, bool) & inper & ~lg
        side = np.where(lg, 1, np.where(sh, -1, 0))
        i = np.flatnonzero(side != 0)
        s = side[i]
        pr = prior[i]
        h = hd[i]
        with np.errstate(invalid="ignore", divide="ignore"):
            ed = s * (c[i] - ema20[i]) / atr[i]
        rows.append({"set": st, "name": name, "tf": tf, "coin": coin, "n": len(i), "n_long": int((s > 0).sum()),
                     "prior_with": int((pr == s).sum()), "prior_against": int((pr == -s).sum()),
                     "htf_with": int((h == s).sum()), "htf_against": int((h == -s).sum()), "htf_hold": int((h == 0).sum()),
                     "days": days, "ema_d": ed[np.isfinite(ed)].astype(np.float32).tolist(),
                     "base_up": int((base_dir > 0).sum()), "base_dn": int((base_dir < 0).sum()), "base_n": int(len(base_dir))})
    return rows


def cmd_measure(scr, procs=2):
    from multiprocessing import get_context
    tasks = [(scr, coin, tf) for tf in TFS for coin in COINS] + [(scr, coin, "5m") for coin in COINS]
    allrows = []
    t0 = time.time()
    with get_context("fork").Pool(procs) as pool:
        for rows in pool.imap_unordered(measure_one, tasks):
            allrows.extend(rows)
            print(f"done {rows[0]['coin'] if rows else '?'} {rows[0]['tf'] if rows else '?'} {time.time() - t0:.0f}s",
                  flush=True)
    R = pd.DataFrame(allrows)
    R.drop(columns=["ema_d"]).to_csv(os.path.join(scr, "roles_measured_bycoin.csv"), index=False)
    out = []
    for (st, name, tf), g in R.groupby(["set", "name", "tf"], sort=False):
        n = int(g.n.sum())
        ed = np.concatenate([np.asarray(x, float) for x in g.ema_d]) if n else np.zeros(0)
        pw, pa = int(g.prior_with.sum()), int(g.prior_against.sum())
        hw, ha, hh = int(g.htf_with.sum()), int(g.htf_against.sum()), int(g.htf_hold.sum())
        days = float(g.days.max())
        bu, bd, bn = int(g.base_up.sum()), int(g.base_dn.sum()), int(g.base_n.sum())
        out.append({"set": st, "name": name, "tf": tf, "n": n, "per_day": round(n / days, 3) if days else np.nan,
                    "long_share": round(int(g.n_long.sum()) / n, 3) if n else np.nan,
                    "prior20": round(pw / (pw + pa), 3) if pw + pa else np.nan,
                    "htf_agree": round(hw / (hw + ha), 3) if hw + ha else np.nan,
                    "htf_with": round(hw / n, 3) if n else np.nan, "htf_against": round(ha / n, 3) if n else np.nan,
                    "htf_hold": round(hh / n, 3) if n else np.nan,
                    "base_hold": round(1 - (bu + bd) / bn, 3) if bn else np.nan,
                    "ema_med": round(float(np.median(ed)), 3) if len(ed) else np.nan,
                    "ema_q25": round(float(np.quantile(ed, 0.25)), 3) if len(ed) else np.nan,
                    "ema_q75": round(float(np.quantile(ed, 0.75)), 3) if len(ed) else np.nan,
                    "coins": int((g.n > 0).sum())})
    M = pd.DataFrame(out)
    M.to_csv(os.path.join(HERE, "roles_measured.csv"), index=False)
    print(M.to_string(), flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "frames":
        cmd_frames(sys.argv[2])
    elif cmd == "measure":
        cmd_measure(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2)
    elif cmd == "one":
        rows = measure_one((sys.argv[2], sys.argv[3], sys.argv[4]))
        for r in rows:
            r.pop("ema_d")
            print(r)
