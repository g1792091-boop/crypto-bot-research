"""OBV 추세형 study (PLAN.md): the accounts. One position at a time over the six coins, the signals of one cell in time
order (same minute: the rule bot's coin order), compounding, through analysis/v39_1h/sim.py (PaperEngine's rules,
checked trade for trade there) on 5m bars (5 years) or 1m bars with mark prices (the recent windows).

Exit / sizing set-ups (PLAN 3):
  RBX  the rule bot: quality leverage (best 50/40x, normal 30/20x, margin = leverage %), stop 2 ATR, ladder 12 -> 10
       then every 5 %, Binance paper costs, from $5,000;
  CVX  the custom-value candidate's own exit (league "-e"): CV30 take-profit 3 R, CV1h net ROE +50 %, stop 4 ATR, the
       same sizing as RBX, from $5,000;
  TBX  the Toobit plan: 40 % margin, BTC 40x / others 30x, stop 2.5 ATR, ladder 12 -> 10 then every 5 %, Toobit costs
       (taker 0.06 % + slippage 0.03 % per side; a fixed take-profit closes at market), no entry when the stop sits
       beyond liquidation, from $50; and its 7 changes T* (PLAN 3).
Nothing here trades: research code reading arrays only.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import replace

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "analysis", "v39_1h"))
import v39lib as L  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import sim  # noqa: E402
from sim import Variant as V  # noqa: E402

SYMBOLS = L.SYMBOLS
M5 = 300_000
DAY = 86_400_000
TOOBIT_STEPS = {"BTCUSDT": 0.001, "ETHUSDT": 0.001, "SOLUSDT": 0.01, "DOGEUSDT": 1.0, "LTCUSDT": 0.001,
                "BCHUSDT": 0.001}       # analysis/v39_1h/extras.py TOOBIT_STEPS["A"]


def ms(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").value // 1_000_000)


PERIODS = {"y2020": (ms("2020-01-01"), ms("2021-01-01")), "pick": (ms("2021-01-01"), ms("2024-01-01")),
           "check": (ms("2024-01-01"), ms("2026-10-01")), "oct": (ms("2026-10-01"), ms("2026-10-27")),
           "rbwin": (ms("2026-10-06"), ms("2026-10-27")), "lgwin": (ms("2026-10-13 09:00"), ms("2026-10-27"))}

_TB = dict(lev_btc=40, lev_alt=30, frac=0.40)
EXITS = {
    "T0": V("T0", "투비트 계획: 손절 2.5 ATR · 계단 12→10", stop_atr=2.5, **_TB),
    "Ts1.5": V("Ts1.5", "손절 1.5 ATR", stop_atr=1.5, **_TB),
    "Ts2": V("Ts2", "손절 2 ATR", stop_atr=2.0, **_TB),
    "Ts3": V("Ts3", "손절 3 ATR", stop_atr=3.0, **_TB),
    "Ts4": V("Ts4", "손절 4 ATR", stop_atr=4.0, **_TB),
    "Tf10": V("Tf10", "고정 익절 +10%", stop_atr=2.5, ladder=False, tp="ROE", tp_val=0.10, **_TB),
    "Tf15": V("Tf15", "고정 익절 +15%", stop_atr=2.5, ladder=False, tp="ROE", tp_val=0.15, **_TB),
    "TL8": V("TL8", "계단 10→8", stop_atr=2.5, first_lock=0.08, **_TB),
}
RBX = V("RBX", "규칙봇: 품질 레버리지 · 손절 2 ATR · 계단 12→10")
CVX = {"CV30": V("CVX", "커스텀 원래: 익절 3R · 손절 4 ATR", stop_atr=4.0, ladder=False, tp="R", tp_val=3.0),
       "CV1h": V("CVX", "커스텀 원래: 순 +50% 익절 · 손절 4 ATR", stop_atr=4.0, ladder=False, tp="ROE", tp_val=0.50),
       "CV4h": V("CVX", "커스텀 원래: 익절 3R · 손절 1.5 ATR", stop_atr=1.5, ladder=False, tp="R", tp_val=3.0)}


def exchange():
    from paperbot.margin import Brackets
    with open(os.path.join(REPO, "research", "fullgrid", "exchange.json")) as fh:
        doc = json.load(fh)
    br = {p["symbol"]: sim.bracket_array(Brackets.from_binance(p)) for p in doc["brackets"] if p["symbol"] in SYMBOLS}
    specs = {s: {"qty_step": float(doc["specs"][s]["qty_step"]), "min_notional": float(doc["specs"][s]["min_notional"])}
             for s in SYMBOLS}
    return br, specs


class Book:
    """Bars of the six coins and the two cost set-ups."""

    def __init__(self, arrays: dict, bar_ms: int):
        from paperbot.config import v3_settings
        self.A, self.bar_ms = arrays, bar_ms
        self.S0 = v3_settings()
        self.br, self.specs_bin = exchange()
        self.Sv_bin = sim.settings_vector(self.S0)
        tb = replace(self.S0, taker_fee=0.0006, slippage_frac=0.0003)
        tb = replace(tb, maker_fee=tb.taker_fee + tb.slippage_frac)
        self.Sv_tb = sim.settings_vector(tb)
        self.specs_tb = {s: {"qty_step": q, "min_notional": 5.0} for s, q in TOOBIT_STEPS.items()}
        self.mmr = {s: float(self.br[s][0, 2]) for s in SYMBOLS}

    @classmethod
    def five(cls, work: str):
        A = {}
        for s in SYMBOLS:
            with np.load(os.path.join(work, f"a5_{s}.npz")) as z:
                a = {k: z[k] for k in z.files}
            a.update(mo=a["o"], mh=a["h"], ml=a["l"])
            A[s] = a
        return cls(A, M5)

    @classmethod
    def minute(cls, m1_dir: str, five_work: str):
        """1m bars with mark prices; funding from the 5m arrays (moved to the 1m bar of the same minute)."""
        A = {}
        for s in SYMBOLS:
            with np.load(os.path.join(m1_dir, f"{s}.npz")) as z:
                a = {k: z[k] for k in z.files}
            with np.load(os.path.join(five_work, f"a5_{s}.npz")) as z:
                t5, f5 = z["ts"], z["fund"]
            f = np.zeros(len(a["ts"]))
            nz = np.flatnonzero(f5 != 0)
            j = np.searchsorted(a["ts"], t5[nz])
            ok = (j < len(a["ts"]))
            ok[ok] &= a["ts"][j[ok]] == t5[nz][ok]
            np.add.at(f, j[ok], f5[nz][ok])
            a["fund"] = f
            A[s] = a
        return cls(A, 60_000)

    def entry_index(self, G: pd.DataFrame) -> np.ndarray:
        e = np.empty(len(G), np.int64)
        for s in SYMBOLS:
            m = (G["symbol"] == s).to_numpy()
            e[m] = np.searchsorted(self.A[s]["ts"], G.loc[m, "close_ms"].to_numpy(np.int64))
        return e

    def account(self, G: pd.DataFrame, v, mode: str, start: float, bust: float, e_idx: np.ndarray | None = None,
                side: np.ndarray | None = None, raw_px: np.ndarray | None = None) -> pd.DataFrame:
        """``mode`` 'bin' (RBX / CVX: the rule's sizing, Binance costs) or 'tb' (Toobit plan). ``side``: other sides
        (the coin-flip twin). ``raw_px``: the entry reference price per signal (the bot's logged ref_price; default
        the open of the bar starting at the signal close). Rows: one per trade taken."""
        Sv = self.Sv_bin if mode == "bin" else self.Sv_tb
        specs = self.specs_bin if mode == "bin" else self.specs_tb
        if e_idx is None:
            e_idx = self.entry_index(G)
        sides = G["side"].to_numpy(int) if side is None else side
        syms = G["symbol"].to_numpy()
        atrs = G["atr"].to_numpy(float)
        bests = G["best"].to_numpy(bool)
        wallet, busy, entered = start, -1, -1
        rows = []
        for k in range(len(G)):
            s = syms[k]
            A = self.A[s]
            e = int(e_idx[k])
            if e >= len(A["ts"]):
                continue
            t_fill = int(A["ts"][e])
            if t_fill <= busy or t_fill == entered:
                continue
            raw = float(A["o"][e]) if raw_px is None else float(raw_px[k])
            sd, atr = int(sides[k]), float(atrs[k])
            if mode == "tb":
                lev = v.lev_btc if s == "BTCUSDT" else v.lev_alt
                if v.stop_atr * atr / raw >= 1.0 / lev - self.mmr[s]:
                    continue                                   # the Toobit liquidation guard: no entry
            r = sim.run_one(Sv, self.br[s], A, e, raw, sd, atr, bool(bests[k]) and side is None, wallet, specs[s], v,
                            s, bar_ms=self.bar_ms)
            if r["reason"] == "REJECTED":
                continue
            busy = int(A["ts"][int(r["j"])]) if r["reason"] != "OPEN" else 2 ** 62
            entered = t_fill
            before = wallet
            wallet += r["pnl"]
            rows.append((k, s, sd, t_fill, r["exit_ts"], r["reason"], r["lev"], r["roe"], r["pnl"], before, wallet,
                         r["lock_roe"]))
            if wallet < bust:
                break
        return pd.DataFrame(rows, columns=["k", "symbol", "side", "entry_ts", "exit_ts", "reason", "lev", "roe", "pnl",
                                           "before", "after", "lock"])


def stats(T: pd.DataFrame, start: float, bust: float) -> dict:
    if not len(T):
        return {"n": 0, "win": np.nan, "mean_roe": np.nan, "avg_win": np.nan, "avg_loss": np.nan, "x": 1.0,
                "mdd": 0.0, "bust": False, "liq": 0, "short_share": np.nan}
    eq = np.r_[start, T["after"].to_numpy(float)]
    peak = np.maximum.accumulate(eq)
    w = T["pnl"] > 0
    ret = T["pnl"] / T["before"]
    return {"n": int(len(T)), "win": float(w.mean()), "mean_roe": float(T["roe"].mean()),
            "avg_win": float(ret[w].mean()) if w.any() else np.nan,
            "avg_loss": float(ret[~w].mean()) if (~w).any() else np.nan,
            "x": float(eq[-1] / start), "mdd": float(((peak - eq) / peak).max()), "bust": bool(eq[-1] < bust),
            "liq": int((T["reason"] == "LIQ").sum()), "short_share": float((T["side"] < 0).mean())}
