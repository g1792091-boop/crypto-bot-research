"""PLAN.md 1: unit checks of the indicators (no trade numbers).
  - Klinger (TradingView form): the vectorized version vs a plain loop of the same formula and vs the library's Pine EMA
    (pine_indicators.pine_ema); cross-event overlap (+-1 bar) with two other Klinger forms: the vendored
    fg_indicators.klinger_oscillator (close-location volume force) and the original Klinger volume force
    (research/vwap30/code/vwfriend.klinger);
  - the OBV (SMA30) and V3.9 (supertrend 10/3) states vs the live trend bot's judge (paperbot/trendjudge.vote_arrays);
  - RSI26 / ROC9 vs frcore._ind.

    python3 -I f2checks.py                 -> checks.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from f2common import *
from frcore import _ind
from paperbot import trendjudge as TJ


def xs(a, b):
    ap, bp = prev(a), prev(b)
    with np.errstate(invalid="ignore"):
        return np.where((ap <= bp) & (a > b), 1, np.where((ap >= bp) & (a < b), -1, 0))


def overlap(x, y):
    """Share of x's cross bars with a same-direction cross of y within +-1 bar."""
    i = np.flatnonzero(x != 0)
    hit = np.zeros(len(i), bool)
    for d in (-1, 0, 1):
        j = np.clip(i + d, 0, len(y) - 1)
        hit |= y[j] == x[i]
    return rnd(hit.mean(), 4), int(len(i))


def main():
    L = sweepsig.lib()
    fg, pi = L.fg, L.pi
    res = {}
    df = bars("BTCUSDT", "1h")
    h, l, c, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    kv, ks = klinger_tv(h, l, c, v)
    kr, ksr = klinger_ref(h, l, c, v)
    hlc3 = (h + l + c) / 3
    sv = np.where(np.r_[np.nan, np.diff(hlc3)] >= 0, v, -v)
    kp = pi.pine_ema(sv, 34) - pi.pine_ema(sv, 55)
    ksp = pi.pine_ema(kp, 13)
    ok = np.isfinite(ks)
    scale = np.nanmax(np.abs(kv))
    res["klinger_tv_vs_loop"] = {"bars": int(ok.sum()), "max_abs_diff_over_max_abs": float(np.nanmax(np.abs(kv - kr)) / scale),
                                 "signal_max_abs_diff_over_max_abs": float(np.nanmax(np.abs(ks - ksr)) / scale),
                                 "nan_pattern_same": bool((np.isnan(kv) == np.isnan(kr)).all() and (np.isnan(ks) == np.isnan(ksr)).all())}
    res["klinger_tv_vs_pine_ema"] = {"max_abs_diff_over_max_abs": float(np.nanmax(np.abs(kv - kp)) / scale),
                                     "signal_max_abs_diff_over_max_abs": float(np.nanmax(np.abs(ks - ksp)) / scale)}
    assert res["klinger_tv_vs_loop"]["max_abs_diff_over_max_abs"] < 1e-9 and res["klinger_tv_vs_pine_ema"]["max_abs_diff_over_max_abs"] < 1e-9
    try:
        sys.path.insert(0, os.path.join(REPO, "research", "vwap30", "code"))
        from vwfriend import klinger as kl_orig
        orig_src = "research/vwap30/code/vwfriend.klinger"
    except Exception as ex:                               # the same formula, copied
        orig_src = f"copy (import failed: {type(ex).__name__})"

        def kl_orig(h, l, c, v):
            hlc = h + l + c
            trend = np.where(np.r_[False, hlc[1:] > hlc[:-1]], 1.0, -1.0)
            dm = h - l
            cm = np.empty(len(c)); cm[0] = dm[0]
            for i in range(1, len(c)):
                cm[i] = cm[i - 1] + dm[i] if trend[i] == trend[i - 1] else dm[i - 1] + dm[i]
            with np.errstate(all="ignore"):
                vf = np.where(cm > 0, v * np.abs(2 * dm / cm - 1) * trend * 100, 0.0)
            e = lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()
            kvo = e(vf, 34) - e(vf, 55)
            return kvo, e(kvo, 13)
    res["klinger_other_forms"] = {"original_source": orig_src}
    for coin, tf in (("BTCUSDT", "15m"), ("BTCUSDT", "1h"), ("SOLUSDT", "30m")):
        d = bars(coin, tf)
        a = d.ts.to_numpy(np.int64) >= ms("2021-01-01")
        h, l, c, v = (d[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
        x_tv = xs(*klinger_tv(h, l, c, v))
        x_fg = xs(*(s.to_numpy(float) for s in fg.klinger_oscillator(d, 34, 55, 13)))
        x_or = xs(*kl_orig(h, l, c, v))
        x_tv[~a] = 0; x_fg[~a] = 0; x_or[~a] = 0
        res["klinger_other_forms"][f"{coin[:-4]}_{tf}"] = {
            "tv_crosses": int((x_tv != 0).sum()), "fg_crosses": int((x_fg != 0).sum()), "orig_crosses": int((x_or != 0).sum()),
            "tv_in_fg_pm1": overlap(x_tv, x_fg)[0], "tv_in_orig_pm1": overlap(x_tv, x_or)[0], "fg_in_orig_pm1": overlap(x_fg, x_or)[0]}
    # states vs the live trend bot's judge
    for coin, tf in (("BTCUSDT", "1h"), ("ETHUSDT", "4h"), ("DOGEUSDT", "1h")):
        d = bars(coin, tf)
        F = tf_frame(coin, tf)
        va = TJ.vote_arrays(d, fg, pi)
        ok = np.arange(len(d)) >= WARM
        h, l, c, v = (d[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
        o = np.asarray(pi.obv(c, v)); om = np.asarray(pi.pine_sma(o, 30))
        mine_obv = np.where(o > om, 1, np.where(o < om, -1, 0))
        res[f"judge_{coin[:-4]}_{tf}"] = {"bars": int(ok.sum()),
                                          "obv_state_same": rnd((mine_obv[ok] == va["OBV"][ok]).mean(), 6),
                                          "v39_state_same": rnd((F["V"][ok] == va["V39"][ok]).mean(), 6)}
        I = _ind(c)
        rs = fg.rsi(pd.Series(c), 26).to_numpy(float)
        rc = fg.roc(pd.Series(c), 9).to_numpy(float)
        res[f"judge_{coin[:-4]}_{tf}"]["rsi_roc_same_as_frcore"] = bool(np.allclose(rs[ok], I["rsi"][ok], equal_nan=True)
                                                                          and np.allclose(rc[ok], I["roc"][ok], equal_nan=True))
    json.dump(res, open(os.path.join(F2_DIR, "checks.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
