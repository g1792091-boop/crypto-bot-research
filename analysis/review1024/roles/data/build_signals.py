"""Every signal of every coded strategy on 15m / 30m / 1h / 4h bars of the extended grid (2020-01 .. 2026-10-24 14:00
UTC), plus the trend sources on 1d bars (for the latch states of build_states.py):

  core    the 36 locked strategies (research/entry_study/param_defs via research/fullgrid/run.core_module, defaults;
          sha256-checked against DEFS_BC.sha256), as the rule bot's core accounts
  ds      the 44 DeepSeek definitions (research/fullgrid/ds_defs.py, default numbers = lib_c), only on the timeframes
          each is defined for (ds_defs.TFS_OF); F14_SMT reads BTC's bars of the same timeframe
  lib     the 40 library entries (research/library/lib.py entries; the +F200 twins are not kept), incl. the 7 timing
          oscillators O1 .. O7
  friend  FRIEND_ROC (the friend's 15m rule generalised: EMA21 > EMA52, RSI26 > 50, ROC9 crossing 0, the last closed
          higher bar's ROC9 on either of two higher timeframes; as analysis/review1024/roles/map/measure_roles.py)

A signal = (bar close, side) known at the bar's close; a bar that is both long and short is long (lib) or dropped (ds,
as the code does). Output OUT/signals/<coin>.npz, compressed bitmaps: <tf>_<sid>_L / <tf>_<sid>_S = np.packbits of the
bool per bar (bar number nb = 0 .. <tf>_n - 1 of the coin's whole bars on tf), <tf>_e0 = the entry minute (bar close,
minutes from T0) of bar 0, so a signal's e = e0 + nb x tf minutes. unpack() below decodes one. OUT/signals/names.csv:
sid, set, name. 1d holds the trend sources only (core + lib; DeepSeek and FRIEND_ROC are not defined on 1d).

    python3 build_signals.py [procs]"""
from common import *

LIB_SKIP = ("+F200",)
NAMES = None                     # set once in the parent before the workers fork


def names_table():
    E = libs()
    run, lib = E["run"], E["lib"]
    ds = run.ds_module()
    rows = [("core", n) for n in run.core_names()] + [("ds", n) for n in ds.DEFS]
    df = bars("BTCUSDT", "4h").iloc[:600].copy()
    df.attrs["tf"] = "4h"
    rows += [("lib", k) for k in lib.entries(df, E["fg"], E["pi"]) if not k.endswith("+F200")]
    rows += [("friend", "FRIEND_ROC")]
    T = pd.DataFrame(rows, columns=["set", "name"])
    T.insert(0, "sid", np.arange(len(T), dtype=np.int16))
    assert T.name.is_unique
    return T


def friend_signals(df, coin, tf, B):
    """FRIEND_ROC as measure_roles.friend_signals; B = {htf: bars}."""
    fg = libs()["fg"]
    c = df["close"].astype(float).reset_index(drop=True)
    e21, e52 = fg.ema(c, 21).to_numpy(float), fg.ema(c, 52).to_numpy(float)
    rsi, roc = fg.rsi(c, 26).to_numpy(float), fg.roc(c, 9).to_numpy(float)
    rocp = np.r_[np.nan, roc[:-1]]
    with np.errstate(invalid="ignore"):
        up = (e21 > e52) & (rsi > 50) & (rocp <= 0) & (roc > 0)
        dn = (e21 < e52) & (rsi < 50) & (rocp >= 0) & (roc < 0)
    higher = {"15m": ("1h", "4h"), "30m": ("1h", "4h"), "1h": ("4h", "1d"), "4h": ("1d", "1d")}[tf]
    bc = close_ms(df, tf)
    H = []
    for htf in higher:
        dh = B[htf]
        r = fg.roc(dh["close"].astype(float).reset_index(drop=True), 9).to_numpy(float)
        j = last_closed(close_ms(dh, htf), bc)
        H.append(np.where(j >= 60, r[np.maximum(j, 1)], np.nan))
    with np.errstate(invalid="ignore"):
        L = up & ((H[0] > 0) | (H[1] > 0))
        S = dn & ((H[0] < 0) | (H[1] < 0))
    L[:200] = False
    S[:200] = False
    return L, S & ~L


def coin_signals(coin, tf, raw, btc, B, only=None):
    """{name: (long, short)} on one coin / timeframe. only = a set of names (1d: the trend sources)."""
    E = libs()
    run, lib = E["run"], E["lib"]
    df = as_chart(raw, tf)
    out = {}
    run.M.clear()
    for name in run.core_names():
        if only is not None and name not in only:
            continue
        try:
            lg, sh = run.core_module(name).signals(df, tf)
            out[name] = (np.asarray(lg, bool), np.asarray(sh, bool))
        except Exception as exc:  # noqa: BLE001
            log("core", name, tf, coin, "ERR", repr(exc)[:200])
    run.M.clear()
    if tf != "1d":
        ds = run.ds_module()
        ctx = None if coin == "BTCUSDT" else {"BTCUSD": as_chart(btc, tf)}
        cache = {}
        for name in ds.DEFS:
            if tf not in ds.TFS_OF[name] or (only is not None and name not in only):
                continue
            try:
                lg, sh = ds.signals(df, tf, name, ctx=ctx, coin=coin[:-1], cache=cache)
                out[name] = (np.asarray(lg, bool), np.asarray(sh, bool))
            except Exception as exc:  # noqa: BLE001
                log("ds", name, tf, coin, "ERR", repr(exc)[:200])
        cache.clear()
    dfl = raw.copy()
    dfl.attrs["tf"] = tf
    for k, v in lib.entries(dfl, E["fg"], E["pi"]).items():
        if not k.endswith("+F200") and (only is None or k in only):
            out[k] = v
    if tf != "1d" and (only is None or "FRIEND_ROC" in only):
        out["FRIEND_ROC"] = friend_signals(raw, coin, tf, B)
    return out


def work(coin):
    t0 = time.time()
    B = {tf: bars(coin, tf) for tf in TFS + ("1d",)}
    drop(coin)
    btc = None
    if coin != "BTCUSDT":
        btc = {tf: bars("BTCUSDT", tf) for tf in TFS}
        drop("BTCUSDT")
    T = NAMES if NAMES is not None else names_table()
    sid = dict(zip(T.name, T.sid))
    trend = set(roles()["roles"]["trend_incl_dual"])
    arrs = {}
    for tf in TFS + ("1d",):
        raw = B[tf]
        sig = coin_signals(coin, tf, raw, None if btc is None else btc.get(tf), B,
                           only=trend if tf == "1d" else None)
        e = ((close_ms(raw, tf) - T0) // MIN).astype(np.int64)
        arrs[f"{tf}_e0"] = np.int64(e[0])
        arrs[f"{tf}_n"] = np.int64(len(e))
        cnt = 0
        for name, (lg, sh) in sig.items():
            lg = np.asarray(lg, bool)
            sh = np.asarray(sh, bool) & ~lg
            assert len(lg) == len(e)
            arrs[f"{tf}_{sid[name]}_L"] = np.packbits(lg)
            arrs[f"{tf}_{sid[name]}_S"] = np.packbits(sh)
            cnt += int(lg.sum() + sh.sum())
        log(coin, tf, len(sig), "strategies", cnt, "signals", f"{time.time() - t0:.0f}s")
    save_npz(os.path.join(OUT, "signals", f"{coin}.npz"), **arrs)
    return coin


def unpack(z, tf, sid, side, tfm=None):
    """(e, nb) of one strategy's signals on one coin file z (np.load of OUT/signals/<coin>.npz); side "L" / "S"."""
    key = f"{tf}_{sid}_{side}"
    if key not in z.files:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    n = int(z[f"{tf}_n"])
    nb = np.flatnonzero(np.unpackbits(z[key])[:n])
    return int(z[f"{tf}_e0"]) + nb * TF_MIN[tf], nb


if __name__ == "__main__":
    from multiprocessing import get_context
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    t0 = time.time()
    os.makedirs(os.path.join(OUT, "signals"), exist_ok=True)
    NAMES = names_table()
    drop("BTCUSDT")
    NAMES.to_csv(os.path.join(OUT, "signals", "names.csv"), index=False)
    with get_context("fork").Pool(procs) as pool:
        for c in pool.imap_unordered(work, COINS):
            log("done", c, f"{time.time() - t0:.0f}s")
    log("all", f"{time.time() - t0:.0f}s")
