"""Owners 10/26: "제발 내 목표 수익률을 이루는 자동매매봇을 위해 최선을 다해줘 … 내목표 수익률을 위해 다양하게 테스트해봐".
The goal is x6 in a month; at margin 40 % a win adds about 4.9 % to the wallet and a loss takes about 19.7 %, so x6 needs many
wins in a row: the levers left are MORE trades in the market where the strategy works and the same win rate. Fixed by the
owners: BTC 40x / others 30x, margin 40 %, one position, market orders only (an entry is the next 5-minute open after a touch),
the six coins, NYSE open and macro releases +-30 min without entry. Kept from 17 ~ 20절: TP net +10 %, stop net ROE -50 %.

Set-ups (a set-up arms at a bar close and waits for its pullback; the first coin whose 5-minute bar touches its level is
entered at the next 5-minute open, unless that minute is blocked; every waiting set-up is dropped at an entry):
  signal   the strategy's signal bar (F7_RF_TRIPLE: the first bar of the three agreeing), ref = the bar's close, wait W hours
  state    every bar close while the three still agree (within H hours of the last signal, or the whole run), ref = that close
  re       after a take-profit, while the three still agree on the last closed bar of the source frame and the trend checks hold,
           a new set-up from the exit price (up to R per signal, wait W hours)
Trend checks at arming: the coin's 1h V3.9 supertrend (10, 3) on the trade's side; BTC's own 1h supertrend on the side.
Sources: 1h custom 80 / 9.0 (the account in the photos), 1h defaults, 4h custom 50 / 4.5, 4h defaults, 30m / 15m defaults and
with 80 / 9.0; one source or several together (one position).
`--parity` replays the current set-up the way timing.run does (commit to one signal, blocks at the signal) and stops on a
difference (run it before the stages).
Reads: the two live windows (the owners' rule: chosen there), October, and every KST month 2025-01 .. 2026-09 (a fresh wallet each
month: the x6 count, the median month, the months that lost).
Run: python3 hunt.py --bars FIVE5M_DIR --work WORK_DIR [--parity] [--stage A,B,...]"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import pick as PK  # noqa: E402
import sim as S  # noqa: E402
import study as ST  # noqa: E402

FIVE, HOUR = 300_000, 3_600_000
KST = 9 * HOUR
FRAME_MS = {"15m": 900_000, "30m": 1_800_000, "1h": HOUR, "4h": 4 * HOUR}
SOURCES = {"1h_c": ("1h", "c"), "1h_d": ("1h", "d"), "4h_c": ("4h", "c"), "4h_d": ("4h", "d"),
           "30m_d": ("30m", "d"), "30m_x": ("30m", "x"), "15m_d": ("15m", "d"), "15m_x": ("15m", "x")}
SOURCE_KO = {"1h_c": "1시간 찾은 값(80·9.0)", "1h_d": "1시간 기본값", "4h_c": "4시간 찾은 값(50·4.5)", "4h_d": "4시간 기본값",
             "30m_d": "30분 기본값", "30m_x": "30분 80·9.0", "15m_d": "15분 기본값", "15m_x": "15분 80·9.0"}
MONTHS = [str(p) for p in pd.period_range("2025-01", "2026-09", freq="M")]
OCT = (ST.ms("2026-09-30 15:00"), PK.END)


def kst_month(m: str) -> tuple:
    a = pd.Timestamp(f"{m}-01 00:00", tz="Asia/Seoul")
    return int(a.value // 1_000_000), int((a + pd.offsets.MonthBegin(1)).value // 1_000_000)


class World:
    def __init__(self, bars: str, work: str):
        self.m5, self.h, self.st = {}, {}, {}
        for c in ST.COINS:
            z = np.load(os.path.join(bars, "5m", f"{c}.npz"))
            self.m5[c] = {k: z[k] for k in ("ts", "o", "h", "l", "c", "fund")}
            self.h[c] = dict(np.load(os.path.join(work, "hunt", f"{c}.npz")))
            self.st[c] = np.load(os.path.join(work, "prep", f"{c}_trend.npz"))["st1h"]
        b = np.load(os.path.join(work, "hunt", "blocks.npz"))
        self.grid = b["grid"]
        self.blk = {k: b[k] for k in ("us_open", "macro", "weekend")}
        self.cache = {}

    def rsi5(self, coin: str) -> np.ndarray:
        """Wilder RSI(14) of the 5-minute closes (known at each bar's close)."""
        key = ("rsi5", coin)
        if key not in self.cache:
            c = pd.Series(self.m5[coin]["c"])
            d = c.diff()
            up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
            dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
            self.cache[key] = (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).to_numpy()
        return self.cache[key]

    def ema5(self, coin: str, n: int) -> np.ndarray:
        key = ("ema5", coin, n)
        if key not in self.cache:
            self.cache[key] = pd.Series(self.m5[coin]["c"]).ewm(span=n, adjust=False).mean().to_numpy()
        return self.cache[key]

    def blocked(self, t: int, weekend_off: bool) -> bool:
        k = int((t - self.grid[0]) // FIVE)
        if k < 0 or k >= len(self.grid) or self.grid[k] != t:
            return False
        return bool(self.blk["us_open"][k] or self.blk["macro"][k] or (weekend_off and self.blk["weekend"][k]))

    def st_at(self, coin: str, t: int) -> int:
        """The coin's 1h supertrend side on the last 1h bar closed at or before t."""
        h = self.h[coin]
        i = int(np.searchsorted(h["1h_ts"] + HOUR, t, side="right")) - 1
        return int(self.st[coin][i]) if i >= 0 else 0

    def state_at(self, coin: str, src: str, t: int) -> int:
        tf, nk = SOURCES[src]
        h = self.h[coin]
        i = int(np.searchsorted(h[f"{tf}_ts"] + FRAME_MS[tf], t, side="right")) - 1
        return int(h[f"{tf}_{nk}_state"][i]) if i >= 0 else 0

    def atr1h_at(self, coin: str, t: int) -> float:
        h = self.h[coin]
        i = int(np.searchsorted(h["1h_ts"] + HOUR, t, side="right")) - 1
        return float(h["1h_atr"][i])


def touched(W: World, cfg: dict, p: dict, c: str, side: int, i0: int, i1: int) -> np.ndarray:
    """Which 5-minute bars of [i0, i1) give the entry (at the next open), by the config's entry style:
      fixed   the low (short: high) reaches the set-up's level: ref - k x ATR (the default)
      trail   the pullback is measured from the best price since the set-up armed (the higher of ref and every high before
              the bar; short: the lower of ref and the lows): the low reaches it - k x ATR
      rsi5    the 5-minute RSI(14) closes at or under x (short: at or over 100 - x)
      ema5    the low reaches the 5-minute EMA(n) of the bar before (short: the high)
      fixed+rsi5 / trail+rsi5  both: the level was reached at or before the bar and the RSI condition holds on it"""
    m = W.m5[c]
    style = cfg.get("entry", "fixed")
    if style == "fixed":
        return (m["l"][i0:i1] <= p["level"]) if side > 0 else (m["h"][i0:i1] >= p["level"])
    out = None
    if style.startswith("trail") or style.startswith("fixed"):
        if style.startswith("trail"):
            ia = int(np.searchsorted(m["ts"], p["armed"]))
            ia = min(ia, i0)
            if side > 0:
                best = np.maximum.accumulate(np.r_[p["ref"], m["h"][ia:i1 - 1]])
                hit = m["l"][ia:i1] <= best - cfg["k"] * p["atr"]
            else:
                best = np.minimum.accumulate(np.r_[p["ref"], m["l"][ia:i1 - 1]])
                hit = m["h"][ia:i1] >= best + cfg["k"] * p["atr"]
            out = hit[i0 - ia:]
        else:
            out = (m["l"][i0:i1] <= p["level"]) if side > 0 else (m["h"][i0:i1] >= p["level"])
        if "+rsi5" in style:                                     # the level reached at or before, the RSI on this bar
            out = np.maximum.accumulate(out) & rsi_ok(W, cfg, c, side, i0, i1)
        return out
    if style == "rsi5":
        return rsi_ok(W, cfg, c, side, i0, i1)
    if style == "ema5":
        e = W.ema5(c, cfg["ema_n"])
        prev = e[max(i0 - 1, 0):i1 - 1]
        if i0 == 0:
            prev = np.r_[e[0], prev]
        return (m["l"][i0:i1] <= prev) if side > 0 else (m["h"][i0:i1] >= prev)
    raise ValueError(style)


def rsi_ok(W: World, cfg: dict, c: str, side: int, i0: int, i1: int) -> np.ndarray:
    r = W.rsi5(c)[i0:i1]
    x = cfg["rsi_x"]
    return (r <= x) if side > 0 else (r >= 100 - x)


def arming_events(W: World, cfg: dict, a: int, b: int) -> list:
    """(t, coin order, coin, side, ref, atr, kind, src, sig_t) sorted by time: every signal (and, in the state mode, every bar
    close while the state holds) of the config's sources in [a - wait, b)."""
    ev = []
    lo = a - int(max(cfg["wait_h"], cfg.get("state_h") or 0, 4) * HOUR) - 4 * HOUR
    for ci, c in enumerate(ST.COINS):
        h = W.h[c]
        for src in cfg["sources"]:
            tf, nk = SOURCES[src]
            close_t = h[f"{tf}_ts"] + FRAME_MS[tf]
            sel = (close_t >= lo) & (close_t < b)
            idx = np.flatnonzero(sel)
            sig, state = h[f"{tf}_{nk}_sig"], h[f"{tf}_{nk}_state"]
            last_sig = {1: None, -1: None}
            # the last signal before the window, for the state mode's "within H hours"
            pre = np.flatnonzero((sig != 0) & (close_t < lo))
            for j in pre[::-1][:50]:
                s = int(sig[j])
                if last_sig[s] is None:
                    last_sig[s] = int(close_t[j])
            for i in idx:
                t = int(close_t[i])
                if sig[i] != 0:
                    last_sig[int(sig[i])] = t
                    ev.append((t, ci, c, int(sig[i]), float(h[f"{tf}_c"][i]), float(h[f"{tf}_atr"][i]), "signal", src, t))
                elif cfg.get("state") and state[i] != 0:
                    s = int(state[i])
                    ls = last_sig[s]
                    if ls is None or (cfg.get("state_h") and t - ls > cfg["state_h"] * HOUR):
                        continue
                    ev.append((t, ci, c, s, float(h[f"{tf}_c"][i]), float(h[f"{tf}_atr"][i]), "state", src, ls))
    ev.sort(key=lambda e: (e[0], e[1]))
    return ev


def checks_ok(W: World, cfg: dict, coin: str, side: int, t: int) -> bool:
    if cfg.get("st1h", True) and W.st_at(coin, t) != side:
        return False
    if cfg.get("btc", False) and W.st_at("BTCUSDT", t) != side:
        return False
    return True


def run(W: World, cfg: dict, a: int, b: int) -> tuple:
    """One wallet, one position over set-ups armed in [a, b). Returns (trades frame, summary)."""
    ev = arming_events(W, cfg, a, b)
    k, wait = cfg["k"], int(cfg["wait_h"] * HOUR)
    weekend_off = cfg.get("weekend_off", True)
    tp, stop = cfg.get("tp", 0.10), cfg.get("stop", 0.50)
    re_max, re_wait, re_k = cfg.get("re", 0), int(cfg.get("re_wait_h", cfg["wait_h"]) * HOUR), cfg.get("re_k", k)
    pending = {}                     # (coin, side) -> dict(level, until, armed, sig_t, src, kind, re_n)
    failed = set()                   # commit mode: (armed, coin, side) refused by the liquidation check
    out, eq = [], 1.0
    now = a                          # the next 5-minute open the account can act on
    e = 0
    ts_m = {c: W.m5[c]["ts"] for c in ST.COINS}
    while True:
        pending = {key: p for key, p in pending.items() if p["until"] > now}
        # arm every set-up whose bar closed at or before `now`
        while e < len(ev) and ev[e][0] <= now:
            t, ci, c, side, ref, atr, kind, src, sig_t = ev[e]
            e += 1
            if t < a or t + wait <= now:
                continue
            if not checks_ok(W, cfg, c, side, t):
                continue
            if cfg.get("commit"):                                # timing.run: blocks at the signal, one signal at a time
                if pending or W.blocked(t, weekend_off) or (t, c, side) in failed:
                    continue
            pending[(c, side)] = dict(level=ref - side * k * atr, ref=ref, atr=atr, until=t + wait, armed=t, sig_t=sig_t, src=src, kind=kind,
                                      re_n=0, ci=ci)
        pending = {key: p for key, p in pending.items() if p["until"] > now}
        nxt = ev[e][0] if e < len(ev) else None
        if not pending:
            if nxt is None or nxt >= b:
                break
            now = max(now, int(math.ceil(nxt / FIVE) * FIVE))
            continue
        # scan 5-minute bars from `now` until the next arming or the earliest expiry
        horizon = min([p["until"] for p in pending.values()] + ([nxt] if nxt is not None else []))
        horizon = max(horizon, now + FIVE)
        best = None                  # (touch bar open ms, coin order, key, entry index)
        for key, p in pending.items():
            c, side = key
            m = W.m5[c]
            i0 = int(np.searchsorted(ts_m[c], now))
            i1 = int(np.searchsorted(ts_m[c], min(horizon, p["until"])))
            if i1 <= i0:
                continue
            seg = touched(W, cfg, p, c, side, i0, i1)
            hit = np.flatnonzero(seg)
            for jj in hit:
                j = i0 + int(jj) + 1
                if j >= len(m["o"]):
                    break
                if not cfg.get("commit") and W.blocked(int(ts_m[c][j]), weekend_off):
                    continue
                cand = (int(ts_m[c][i0 + int(jj)]), p["ci"], key, j)
                if best is None or cand[:2] < best[:2]:
                    best = cand
                break
        if best is None:
            now = horizon
            if now >= b and nxt is None:
                break
            if now >= b and not pending:
                break
            if now >= b + wait:
                break
            continue
        _, _, key, j = best
        c, side = key
        p = pending[key]
        m = W.m5[c]
        lev = 40.0 if c == "BTCUSDT" else 30.0
        fill = m["o"][j] * (1 + side * S.SLIP)
        atr1 = W.atr1h_at(c, int(m["ts"][j]))
        dist = (stop / lev - S.RT) * fill
        if dist + atr1 > (1.0 / lev - 0.005) * fill:              # the liquidation check (as pick.py / timing.run)
            del pending[key]
            if cfg.get("commit"):                                # timing.run tries the next coin of the same bar
                failed.add((p["armed"], c, side))
                now = p["armed"]
                while e > 0 and ev[e - 1][0] >= now:
                    e -= 1
            continue
        res = S.run_position(m, j, side, lev, fill, "tp10", 0.0, None, tp_roe=tp, stop_roe=stop)
        exit_t = int(m["ts"][res["exit_i"]])
        if res["reason"] == "END":
            break
        eq *= 1 + 0.40 * max(res["roe"], -1.0)
        out.append(dict(t=int(m["ts"][j]), coin=c, side=side, roe=res["roe"], reason=res["reason"], kind=p["kind"],
                        src=p["src"], wait_h=(int(m["ts"][j]) - p["armed"]) / HOUR,
                        hold_h=(exit_t - int(m["ts"][j])) / HOUR, re_n=p["re_n"]))
        pending = {}
        now = exit_t + FIVE
        if re_max and res["reason"] == "TP" and p["re_n"] < re_max and now < b:
            if W.state_at(c, p["src"], now) == side and checks_ok(W, cfg, c, side, now):
                pending[key] = dict(level=res["exit_px"] - side * re_k * atr1, ref=res["exit_px"], atr=atr1, until=now + re_wait, armed=now,
                                    sig_t=p["sig_t"], src=p["src"], kind="re", re_n=p["re_n"] + 1, ci=p["ci"])
        # set-ups armed while the position was open are not taken (the bot ignores signals while it holds one)
        while e < len(ev) and ev[e][0] < now:
            e += 1
        if now >= b and not pending:
            break
    T = pd.DataFrame(out)
    w = int((T.roe > 0).sum()) if len(T) else 0
    return T, {"n": int(len(T)), "w": w, "l": int(len(T) - w), "x": float(eq)}


# ---------------------------------------------------------------------- parity with timing.run (commit mode)
def parity(W: World) -> None:
    """The current set-up the way timing.run replays it (commit to the first signal, blocks and weekend at the signal close):
    17절's 31-1 x3.60 / 19-1 x2.02 and 19절's months."""
    want = {"rulebot": (31, 1, 3.5957), "league": (19, 1, 2.0227), "2026-06": (37, 10, 0.6571), "2026-09": (35, 17, 0.1286)}
    cfg = dict(BASE, commit=True)
    for wn, (wa, wb) in list(PK.LIVE.items()) + [(m, kst_month(m)) for m in ("2026-06", "2026-09")]:
        s = run(W, cfg, wa, wb)[1]
        w, l_, x = want[wn]
        print("parity", wn, s, "want", want[wn], flush=True)
        if (s["w"], s["l"]) != (w, l_) or abs(s["x"] - x) > 0.002:
            raise SystemExit(f"parity failed on {wn}")


def months_read(T: pd.DataFrame) -> dict:
    if not len(T):
        s = pd.Series(1.0, index=MONTHS)
    else:
        mo = pd.to_datetime(T.t + KST, unit="ms").dt.strftime("%Y-%m")
        x = {}
        for m_, g in T.groupby(mo):
            eq = 1.0
            for r in g.roe.to_numpy():
                eq *= 1 + 0.40 * max(r, -1.0)
            x[m_] = eq
        s = pd.Series(x).reindex(MONTHS).fillna(1.0)
    return {"x6": int((s >= 6).sum()), "x3": int((s >= 3).sum()), "x2": int((s >= 2).sum()), "up": int((s > 1).sum()),
            "half": int((s <= 0.5).sum()), "median": float(s.median()),
            "geo": float(math.exp(np.log(np.maximum(s, 1e-6)).mean())), "best": float(s.max()), "worst": float(s.min()),
            "by_month": {k: round(float(v), 3) for k, v in s.items()}}


def evaluate(W: World, cfg: dict) -> dict:
    r = {}
    for wn, (wa, wb) in PK.LIVE.items():
        T, s = run(W, cfg, wa, wb)
        s["per_day"] = s["n"] / ((wb - wa) / 86_400_000)
        r[wn] = s
    T, s = run(W, cfg, *OCT)
    r["oct"] = s
    T, s = run(W, cfg, kst_month(MONTHS[0])[0], kst_month(MONTHS[-1])[1])
    r["months"] = months_read(T)
    r["months"]["win"] = s["w"] / max(s["n"], 1)
    r["months"]["per_month"] = s["n"] / len(MONTHS)
    r["live"] = min(r["rulebot"]["x"], r["league"]["x"])
    return r


BASE = dict(sources=("1h_c",), k=0.25, wait_h=2, st1h=True, btc=False, weekend_off=True, tp=0.10, stop=0.50)


MODES = {"한 신호씩": True, "모든 코인 대기": False}   # commit: wait for one signal at a time (timing.run) / every coin waits


def stages() -> dict:
    """name -> list of (label, cfg)."""
    st = {"A": [], "B": [], "C": [], "D": []}
    for mn, cm in MODES.items():
        for wk in (True, False):
            for btc in (False, True):
                st["A"].append((f"지금 구조 · {mn} · 주말 {'쉼' if wk else '포함'}" + (" · BTC" if btc else ""),
                                dict(BASE, commit=cm, weekend_off=wk, btc=btc)))
        for btc in (False, True):                             # B: re-entry after a take-profit
            for re in (1, 2, 3, 5, 10):
                for re_wait in (1, 2, 4):
                    for re_k in (0.0, 0.25, 0.5):
                        st["B"].append((f"재진입 {re}번 · {re_wait}시간 · 되돌림 {re_k} · {mn}" + (" · BTC" if btc else ""),
                                        dict(BASE, commit=cm, btc=btc, re=re, re_wait_h=re_wait, re_k=re_k)))
        for btc in (False, True):                             # C: entries while the three still agree
            for sh in (3, 6, 12, 24, None):
                for k in (0.25, 0.5):
                    st["C"].append((f"상태 진입 {sh or '계속'}시간 · 되돌림 {k} · {mn}" + (" · BTC" if btc else ""),
                                    dict(BASE, commit=cm, btc=btc, state=True, state_h=sh, k=k, wait_h=1)))
        for src in SOURCES:                                   # D: other frames, alone and with 1h
            for btc in (False, True):
                st["D"].append((f"{SOURCE_KO[src]} 혼자 · {mn}" + (" · BTC" if btc else ""),
                                dict(BASE, commit=cm, sources=(src,), btc=btc)))
                if src != "1h_c":
                    st["D"].append((f"1시간 찾은 값 + {SOURCE_KO[src]} · {mn}" + (" · BTC" if btc else ""),
                                    dict(BASE, commit=cm, sources=("1h_c", src), btc=btc)))
    st["E"] = []                                              # E: TP / pullback / wait / stop / weekend on the leading families
    fams = {"1시간 · BTC": dict(BASE, commit=True, btc=True),
            "1시간 + 4시간 찾은 값 · BTC": dict(BASE, commit=True, btc=True, sources=("1h_c", "4h_c"))}
    for fn, f in fams.items():
        for tp in (0.08, 0.10, 0.12, 0.15):
            for k in (0.15, 0.25, 0.35):
                for w in (1, 2, 3):
                    for stop in (0.40, 0.50):
                        for wk in (True, False):
                            st["E"].append((f"{fn} · 익절 {tp:.2f} · 되돌림 {k} · {w}시간 · 손절 {stop:.2f} · 주말 "
                                            f"{'쉼' if wk else '포함'}",
                                            dict(f, tp=tp, k=k, wait_h=w, stop=stop, weekend_off=wk)))
    st["F"] = []                                              # F: the neighbourhood of E's leader (shallower, shorter pullbacks)
    for tp in (0.09, 0.10, 0.11):
        for k in (0.05, 0.10, 0.15, 0.20, 0.25):
            for w in (0.5, 1, 1.5, 2):
                for wk in (True, False):
                    st["F"].append((f"1시간 · BTC · 익절 {tp:.2f} · 되돌림 {k} · {w}시간 · 주말 {'쉼' if wk else '포함'}",
                                    dict(BASE, commit=True, btc=True, tp=tp, k=k, wait_h=w, weekend_off=wk)))
    F1 = dict(BASE, commit=True, btc=True, k=0.20, wait_h=1)  # G: entry styles on the 21절 recommendation
    st["G"] = [("추천(F1): 신호 종가에서 0.2 ATR · 1시간", F1)]
    for w in (1, 2):
        for k in (0.15, 0.2, 0.25, 0.3, 0.4, 0.5):
            st["G"].append((f"신호 뒤 최고가(숏은 최저가)에서 {k} ATR 되돌림 · {w}시간", dict(F1, entry="trail", k=k, wait_h=w)))
        for x in (20, 25, 30, 35, 40):
            st["G"].append((f"5분 RSI {x} 이하(숏 {100 - x} 이상) · {w}시간", dict(F1, entry="rsi5", rsi_x=x, wait_h=w)))
        for n in (9, 20, 50):
            st["G"].append((f"5분 EMA{n} 닿음 · {w}시간", dict(F1, entry="ema5", ema_n=n, wait_h=w)))
        for x in (30, 40):
            st["G"].append((f"0.2 ATR 되돌림 + 5분 RSI {x} 이하 · {w}시간", dict(F1, entry="fixed+rsi5", rsi_x=x, wait_h=w)))
            st["G"].append((f"최고가에서 0.2 ATR + 5분 RSI {x} 이하 · {w}시간",
                            dict(F1, entry="trail+rsi5", rsi_x=x, k=0.2, wait_h=w)))
    return st


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--stage", default="A,B,C,D")
    ap.add_argument("--out", default="hunt.json")
    ap.add_argument("--parity", action="store_true")
    a = ap.parse_args(argv)
    W = World(a.bars, a.work)
    if a.parity:
        parity(W)
        return 0
    path = os.path.join(a.work, a.out)
    res = json.load(open(path)) if os.path.exists(path) else {}
    allst = stages()
    t0 = time.time()
    for sn in a.stage.split(","):
        rows = res.get(sn, [])
        done = {r["label"] for r in rows}
        for label, cfg in allst[sn]:
            if label in done:
                continue
            r = {"label": label, "cfg": {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.items()},
                 **evaluate(W, cfg)}
            rows.append(r)
            res[sn] = rows
            json.dump(res, open(path, "w"), ensure_ascii=False, indent=1)
            mo = r["months"]
            print(f"{sn} {label} | RB {r['rulebot']['w']}-{r['rulebot']['l']} x{r['rulebot']['x']:.2f} "
                  f"| LG {r['league']['w']}-{r['league']['l']} x{r['league']['x']:.2f} | OCT {r['oct']['w']}-{r['oct']['l']} "
                  f"x{r['oct']['x']:.2f} | 21m x6 {mo['x6']} x2 {mo['x2']} up {mo['up']} med {mo['median']:.2f} "
                  f"win {mo['win'] * 100:.1f}% n/mo {mo['per_month']:.0f} | {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
