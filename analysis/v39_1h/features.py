"""Chart bars and market context of the V3.9 1h study: 1h / 4h bars from the public 5m klines (fetch_bars.py five)
plus, after their end, the export's own 1m bars; the V3.9 signal; and simple context numbers at a signal's bar close
(only bars closed by then: no look-ahead). Used by window.py and fiveyear.py alike, so a filter rule means the same in
both."""
from __future__ import annotations

import importlib.util
import os

import numpy as np
import pandas as pd

import v39lib as L

HOUR = 3_600_000
_P = None


def v39_module():
    """research/entry_study/param_defs/V39_ALL.py: ``signals(df, tf)`` = the locked V3.9 signal bar for bar."""
    global _P
    if _P is None:
        p = os.path.join(L.REPO, "research", "entry_study", "param_defs", "V39_ALL.py")
        spec = importlib.util.spec_from_file_location("v39_param_defs", p)
        _P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_P)
    return _P


def indicators():
    v39_module()                      # puts the hash-checked vendored indicator modules on sys.path
    import fg_indicators as fg
    import pine_indicators as pi
    return fg, pi


def load5(five_dir: str, sym: str) -> dict:
    with np.load(os.path.join(five_dir, f"{sym}.npz")) as z:
        return {k: z[k] for k in z.files}


def agg(ts, o, h, l, c, step: int, bar_ms: int) -> pd.DataFrame:
    """UTC-aligned bins of ``step`` ms from bars of ``bar_ms``; a first / last bin not fully covered is dropped."""
    b = ts // step
    cut = np.flatnonzero(np.diff(b)) + 1
    st, en = np.r_[0, cut], np.r_[cut, len(ts)]
    df = pd.DataFrame({"open_ms": b[st] * step, "open": o[st], "high": np.maximum.reduceat(h, st),
                       "low": np.minimum.reduceat(l, st), "close": c[en - 1], "last_ms": ts[en - 1]})
    keep = np.ones(len(df), bool)
    if len(df) and ts[0] > df["open_ms"].iloc[0]:
        keep[0] = False
    if len(df) and df["last_ms"].iloc[-1] < df["open_ms"].iloc[-1] + step - bar_ms:
        keep[-1] = False
    df = df[keep].reset_index(drop=True)
    df["close_ms"] = df["open_ms"] + step
    return df.drop(columns=["last_ms"])


def hourly(five_dir: str, sym: str, live: dict | None = None) -> pd.DataFrame:
    """1h bars of ``sym``: from the 5m klines, then the export's 1m bars for the hours after them."""
    z = load5(five_dir, sym)
    df = agg(z["ts"], z["o"], z["h"], z["l"], z["c"], HOUR, 300_000)
    if live is not None and len(live["ts"]):
        x = agg(live["ts"], live["o"], live["h"], live["l"], live["c"], HOUR, 60_000)
        x = x[x["open_ms"] > df["open_ms"].iloc[-1]]
        df = pd.concat([df, x], ignore_index=True)
    return df


def four_hour(h1: pd.DataFrame) -> pd.DataFrame:
    ts = h1["open_ms"].to_numpy(np.int64)
    return agg(ts, h1["open"].to_numpy(float), h1["high"].to_numpy(float), h1["low"].to_numpy(float),
               h1["close"].to_numpy(float), 4 * HOUR, HOUR)


def v39_signals(h1: pd.DataFrame) -> pd.DataFrame:
    """Every V3.9 1h signal of the frame: close_ms, side, ATR14 (the bot's stop unit), best flag (entry-quality group
    of levrule, computed as the full-grid study does: mean quintile of the strength features >= 4)."""
    fg, _pi = indicators()
    P = v39_module()
    df = pd.DataFrame({"ts": pd.to_datetime(h1["open_ms"], unit="ms", utc=True), "open": h1["open"],
                       "high": h1["high"], "low": h1["low"], "close": h1["close"], "volume": 1.0})
    df.attrs["tf"] = "1h"
    lo, sh = P.signals(df, "1h")
    atr = fg.atr(df, 14).to_numpy(float)
    bl, bs = best_flags(df)
    rows = []
    close = h1["close_ms"].to_numpy(np.int64)
    for side, m, best in ((1, np.asarray(lo, bool), bl), (-1, np.asarray(sh, bool), bs)):
        idx = np.flatnonzero(m)
        idx = idx[idx >= 300]                       # the first 300 bars only warm the indicators up (full grid)
        rows.append(pd.DataFrame({"bar": idx, "close_ms": close[idx], "side": side, "atr": atr[idx],
                                  "best": best[idx], "close": h1["close"].to_numpy(float)[idx]}))
    return pd.concat(rows, ignore_index=True).sort_values(["close_ms", "side"]).reset_index(drop=True)


def best_flags(df: pd.DataFrame) -> tuple:
    """(best_long, best_short) per bar: research/fullgrid/run.py best_flags on this frame."""
    from paperbot import levrule
    from paperbot.entry_marks import strength_module
    n = len(df)
    no = (np.zeros(n, bool), np.zeros(n, bool))
    try:
        smod = strength_module("V39_ALL")
        cell = levrule.edges().get("V39_ALL|1h")
        arrays = smod.strength(df.copy(), "1h")
    except Exception:  # noqa: BLE001  as live: no strength -> normal
        return no
    if smod is None or not cell:
        return no
    out = []
    for k in (0, 1):
        tot, cnt = np.zeros(n), np.zeros(n)
        for f in smod.FEATURES:
            e = cell.get(f["name"])
            if e is None:
                continue
            v = np.asarray(arrays[f["name"]][k], float)
            ok = np.isfinite(v)
            sv = np.where(ok, v if e["higher_is_stronger"] else -v, 0.0)
            q = 1 + np.searchsorted(np.asarray(e["edges"], float), sv, side="right")
            tot += np.where(ok, q, 0)
            cnt += ok
        with np.errstate(invalid="ignore", divide="ignore"):
            out.append((cnt > 0) & (tot / np.maximum(cnt, 1) >= 4))
    return tuple(out)


class Context:
    """Context numbers at a 1h bar close for one coin (and BTC for the market direction)."""

    def __init__(self, h1: pd.DataFrame, btc_h1: pd.DataFrame):
        fg, pi = indicators()
        self.h1 = h1.reset_index(drop=True)
        c = self.h1["close"].to_numpy(float)
        hi, lo = self.h1["high"].to_numpy(float), self.h1["low"].to_numpy(float)
        self.close_ms = self.h1["close_ms"].to_numpy(np.int64)
        self.c = c
        self.ema20 = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()
        self.ema200 = pd.Series(c).ewm(span=200, adjust=False).mean().to_numpy()
        df = pd.DataFrame({"open": self.h1["open"], "high": hi, "low": lo, "close": c, "volume": 1.0})
        self.atr = fg.atr(df, 14).to_numpy(float)
        self.adx = np.asarray(pi.adx(hi, lo, c, 14, 14), float)
        self.rsi = np.asarray(pi.pine_rsi(c, 14), float)
        p20, m20 = pi.dmi(hi, lo, c, 20)                  # the DMI(20) V3.9 itself uses
        self.di_gap = np.asarray(p20, float) - np.asarray(m20, float)
        h4 = four_hour(self.h1)
        c4 = h4["close"].to_numpy(float)
        self.h4_close_ms = h4["close_ms"].to_numpy(np.int64)
        self.h4_c = c4
        self.h4_ema50 = pd.Series(c4).ewm(span=50, adjust=False).mean().to_numpy()
        self.h4_ema20 = pd.Series(c4).ewm(span=20, adjust=False).mean().to_numpy()
        _l, d = pi.exchange_supertrend(h4["high"].to_numpy(float), h4["low"].to_numpy(float), c4, 10, 3.0)
        self.h4_st = np.asarray(d, float)
        self.btc_ms = btc_h1["close_ms"].to_numpy(np.int64)
        self.btc_c = btc_h1["close"].to_numpy(float)

    def at(self, t: int, side: int) -> dict:
        """Numbers known at bar close ``t`` (ms) for a signal of ``side``; NaN where history is short."""
        i = int(np.searchsorted(self.close_ms, t, side="right")) - 1
        k = int(np.searchsorted(self.h4_close_ms, t, side="right")) - 1
        b = int(np.searchsorted(self.btc_ms, t, side="right")) - 1
        nan = float("nan")
        out = {}
        out["coin_24h"] = self.c[i] / self.c[i - 24] - 1 if i >= 24 else nan
        out["coin_4h"] = self.c[i] / self.c[i - 4] - 1 if i >= 4 else nan
        out["btc_24h"] = self.btc_c[b] / self.btc_c[b - 24] - 1 if b >= 24 else nan
        out["btc_4h"] = self.btc_c[b] / self.btc_c[b - 4] - 1 if b >= 4 else nan
        out["btc_7d"] = self.btc_c[b] / self.btc_c[b - 168] - 1 if b >= 168 else nan
        out["ext_ema20_atr"] = side * (self.c[i] - self.ema20[i]) / self.atr[i] if i >= 0 else nan
        out["above_ema200_1h"] = float(np.sign(self.c[i] - self.ema200[i])) if i >= 200 else nan
        out["atr_pct"] = self.atr[i] / self.c[i] if i >= 0 else nan
        out["adx14"] = self.adx[i] if i >= 0 else nan
        out["rsi14"] = self.rsi[i] if i >= 0 else nan
        out["di20_gap"] = side * self.di_gap[i] if i >= 0 else nan
        out["h4_ema50"] = float(np.sign(self.h4_c[k] - self.h4_ema50[k])) if k >= 50 else nan
        out["h4_ema20_50"] = float(np.sign(self.h4_ema20[k] - self.h4_ema50[k])) if k >= 50 else nan
        out["h4_st"] = float(self.h4_st[k]) if k >= 20 else nan
        out["hour_kst"] = int(((t // HOUR) + 9) % 24)
        return out


# Simple "skip this signal" rules for the loss question. Each takes the context dict and the side.
RULES = [
    ("no_long", "롱 안 함 (숏만)", lambda x, s: s > 0),
    ("h4_ema50_against", "4시간봉 종가가 EMA50 반대편이면 안 함", lambda x, s: x["h4_ema50"] * s < 0),
    ("h4_st_against", "4시간봉 슈퍼트렌드가 반대면 안 함", lambda x, s: x["h4_st"] * s < 0),
    ("h4_ema_cross_against", "4시간봉 EMA20/50이 반대면 안 함", lambda x, s: x["h4_ema20_50"] * s < 0),
    ("btc24_against", "BTC 24시간 흐름이 반대면 안 함", lambda x, s: x["btc_24h"] * s < 0),
    ("coin24_against", "그 코인 24시간 흐름이 반대면 안 함", lambda x, s: x["coin_24h"] * s < 0),
    ("ema200_against", "1시간봉 EMA200 반대편이면 안 함", lambda x, s: x["above_ema200_1h"] * s < 0),
    ("di20_against", "DMI(20) +DI/-DI가 신호 반대쪽이면 안 함", lambda x, s: x["di20_gap"] < 0),
    ("chase1", "EMA20에서 1 ATR 넘게 달아난 뒤면 안 함 (추격 금지)", lambda x, s: x["ext_ema20_atr"] > 1.0),
    ("adx_lo20", "ADX 20 미만이면 안 함", lambda x, s: x["adx14"] < 20),
    ("kst_12_17", "한국 시각 12~17시 신호는 안 함 (손실 시간대에 맞춘 규칙, 과적합 예시)",
     lambda x, s: 12 <= x["hour_kst"] <= 17),
]
