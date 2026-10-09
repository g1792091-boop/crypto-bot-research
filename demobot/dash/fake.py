"""A complete, realistic FAKE snapshot folder for developing and testing the demo lab dashboard (never the real bot).

    python -m demobot.dash.fake OUTDIR [--past5y DIR] [--seed 7] [--phase live|warm] [--empty] [--views 40]

Writes every file of demobot/CONTRACT.md sections 4 and 7 (status, home, accounts, acct/<id> for the 48 accounts plus
two neutral private ones, trades, judge, views, rank_<STRAT>_<tf>.npz for the 3 strategies x 2 timeframes with the
exact shapes (grid.NEXIT exits), rank_meta) and, with
--past5y, a fake past5y_<STRAT>_<tf>.npz per strategy and timeframe into that folder. Deterministic (seeded); the
numbers are made up and only shaped like the engine's. --empty writes only status.json (the first minutes of a warm-up).
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import sys

import numpy as np

from .. import grid

UTC = datetime.timezone.utc
FIXED_NOW_MS = int(datetime.datetime(2026, 10, 18, 5, 15, tzinfo=UTC).timestamp() * 1000)
NOW_MS = FIXED_NOW_MS          # build(now_ms=...) moves it (the module's functions read this one clock)
DAY = 86_400_000
HOUR = 3_600_000
LIVE_DAYS = 9.4
SEED_USD = 1000.0
TAKER, SLIP, FUND8 = 0.0005, 0.0002, 0.0001
PRICE = {"BTCUSD": 112_400.0, "ETHUSD": 4_120.0, "SOLUSD": 211.0, "DOGEUSD": 0.2412, "LTCUSD": 104.6,
         "BCHUSD": 561.0, "XRPUSD": 2.61}
ATR_PCT = {"15m": 0.0035, "30m": 0.005}
TF_KO = {"15m": "15분", "30m": "30분"}
TF_MS = {"15m": 15 * 60_000, "30m": 30 * 60_000}
SHORTS = ("S2", "N02", "N04")
KIND_KO = {"fixed": "고정", "adaptive": "자동 교체", "friend": "친구 규칙", "flip": "동전 던지기", "private": "비공개 매매법"}
PERIODS = ("2020", "2021-23", "2024-26", "2020-03", "2022-05", "2022-11")
HOUSE_KO = grid.exit_ko(0)


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _write_npz(path: str, **arrays) -> None:
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **arrays)
    os.replace(tmp, path)


def _r(x, nd=4):
    return None if x is None or not math.isfinite(x) else round(float(x), nd)


def _kst(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone(datetime.timedelta(hours=9))).strftime("%m/%d %H:%M")


def coin_ko(c: str) -> str:
    return grid.coin_ko(c)


# ---------------------------------------------------------------- the 48 accounts (+ 2 private)
def account_specs() -> list:
    out = []

    def add(aid, kind, sub, short, tf, name, rule_ko, combo=None):
        strat = grid.LONG.get(short)
        out.append({"id": aid, "kind": kind, "sub": sub, "short": short, "strategy": strat, "tf": tf, "name": name,
                    "rule_ko": rule_ko, "combo": combo})

    for s in SHORTS:
        for tf in grid.TFS:
            c = grid.default_combo(grid.LONG[s])
            add(f"fx-def-{s}-{tf}", "fixed", "default", s, tf, f"{s} 기본값 · {TF_KO[tf]}",
                f"기본값 그대로 ({grid.combo_label(grid.LONG[s], c)})", c)
    for s in ("S2", "N04"):
        for tf in grid.TFS:
            c = grid.friend_combo(grid.LONG[s])
            add(f"fx-fr-{s}-{tf}", "fixed", "friend", s, tf, f"{s} 친구 값 · {TF_KO[tf]}",
                f"친구가 쓰는 값 그대로 ({grid.combo_label(grid.LONG[s], c)})", c)
    for s in SHORTS:
        for tf in grid.TFS:
            c = grid.PICK[(grid.LONG[s], tf)]
            add(f"fx-pk-{s}-{tf}", "fixed", "pick", s, tf, f"{s} 5년 1등 값 · {TF_KO[tf]}",
                f"5년 연구의 1등 값 그대로 ({grid.combo_label(grid.LONG[s], c)})", c)
    adaptive = {"r26": ("자동 · 5거래마다(26주)", "닫힌 거래 5건마다, 최근 26주 주변 평균 1등 설정으로 바꿈 (코인 모두 함께)"),
                "r4": ("자동 · 5거래마다(4주)", "닫힌 거래 5건마다, 최근 4주 주변 평균 1등 설정으로 바꿈 (코인 모두 함께)"),
                "r26c": ("자동 · 코인별(26주)", "닫힌 거래 5건마다, 코인마다 그 코인의 최근 26주 1등 설정으로 바꿈"),
                "wk": ("자동 · 매주(26주)", "매주 월요일 09:00, 최근 26주 주변 평균 1등 설정으로 바꿈 (코인 모두 함께)")}
    for sub, (nm, rule) in adaptive.items():
        for s in SHORTS:
            for tf in grid.TFS:
                add(f"ad-{sub}-{s}-{tf}", "adaptive", sub, s, tf, f"{s} {nm} · {TF_KO[tf]}", rule)
    for s in SHORTS:
        for tf in grid.TFS:
            add(f"fr-{s}-{tf}", "friend", "rule", s, tf, f"{s} 친구 규칙 · 매주 · {TF_KO[tf]}",
                "매주 월요일, 코인·배수마다 지난 26주에 돈을 번 (설정 × 청산) 중 낙폭이 가장 작은 것을 일주일 돌림")
    for tf in grid.TFS:
        add(f"cf-{tf}", "flip", "flip", None, tf, f"동전 던지기 · {TF_KO[tf]}",
            "아무 봉에서 아무 방향으로 들어가고 사다리로 나감 (운 비교용)")
    # private plug-ins (CONTRACT 7.2): neutral names only, never a real plug-in's name or rules
    for i, tf in enumerate(grid.TFS, 1):
        add(f"pv-p{i}-{tf}", "private", f"p{i}", None, tf, f"비공개 {i} · {TF_KO[tf]}",
            f"서버에만 있는 매매법 {i} (규칙은 공개하지 않습니다)")
    return out


def _label(strat, c) -> str:
    return grid.combo_label(strat, int(c))


def _percoin_ko(pairs) -> str:
    return f"코인별 {len(pairs)}개 (" + ", ".join(f"{coin_ko(k)} {v}" for k, v in pairs) + ")"


class _Acct:
    """One fake account: shared entries, four leverage wallets, its curve, decisions and current settings."""

    def __init__(self, spec, rng, live_start):
        self.spec, self.rng, self.live_start = spec, rng, live_start
        strat = spec["strategy"]
        self.settings_now, self.decisions = [], []
        self.line_setting = {}
        r = rng
        if spec["kind"] == "flip":
            self.setting_ko = "무작위 진입"
            self.settings_now = [{"coin": "ALL", "L": None, "setting_ko": "무작위 진입", "exit_ko": HOUSE_KO}]
        elif spec["kind"] == "private":
            self.setting_ko = "비공개 설정"
            self.settings_now = [{"coin": "ALL", "L": None, "setting_ko": "비공개 설정", "exit_ko": "비공개 청산"}]
        elif spec["kind"] == "fixed":
            self.setting_ko = _label(strat, spec["combo"])
            self.settings_now = [{"coin": "ALL", "L": None, "setting_ko": self.setting_ko, "exit_ko": HOUSE_KO}]
        elif spec["sub"] == "r26c":
            pairs = [(c, _label(strat, r.integers(grid.NCOMBO[strat]))) for c in grid.COINS]
            self.setting_ko = _percoin_ko(pairs)
            self.settings_now = [{"coin": c, "L": None, "setting_ko": v, "exit_ko": HOUSE_KO} for c, v in pairs]
        elif spec["kind"] == "friend":
            rows, by_l = [], {}
            for L in grid.LEVS:
                pairs = []
                for c in grid.COINS:
                    lab = _label(strat, r.integers(grid.NCOMBO[strat]))
                    ex = grid.exit_ko(int(r.integers(grid.NEXIT)))
                    rows.append({"coin": c, "L": L, "setting_ko": lab, "exit_ko": ex})
                    pairs.append((c, f"{lab} · {ex}"))
                by_l[str(L)] = _percoin_ko(pairs)
            self.settings_now, self.line_setting = rows, by_l
            self.setting_ko = "코인·배수마다 따로 (28개)"
        else:
            self.setting_ko = _label(strat, r.integers(grid.NCOMBO[strat]))
            self.settings_now = [{"coin": "ALL", "L": None, "setting_ko": self.setting_ko, "exit_ko": HOUSE_KO}]
        self._entries()
        self._lines()
        self._decisions()

    # entries shared by the four lines
    def _entries(self):
        r, spec = self.rng, self.spec
        tf = spec["tf"]
        n = int(r.integers(30, 80) if tf == "15m" else r.integers(16, 44))
        if spec["kind"] == "flip":
            n = int(n * 1.3)
        span = NOW_MS - self.live_start
        sig = np.sort(r.uniform(0, span * 0.985, n)).astype(np.int64) + self.live_start
        sig = (sig // TF_MS[tf]) * TF_MS[tf]
        self.entries = []
        win_p = 0.36 if spec["kind"] != "flip" else 0.33
        n_open = int(r.integers(0, 4))
        for i, t in enumerate(sig):
            coin = grid.COINS[int(r.integers(len(grid.COINS)))]
            side = 1 if r.random() < 0.5 else -1
            entry_ms = int(t) + TF_MS[tf]
            px = PRICE[coin] * float(np.exp(r.normal(0, 0.03)))
            d = float(r.uniform(0.004, 0.02))
            stop = px * (1 - side * d)
            is_open = i >= n - n_open
            if is_open:
                Rg = float(r.normal(0.1, 0.6))
                reason, exit_ms, exit_px = "open", None, None
            else:
                if r.random() < win_p:
                    Rg = float(r.lognormal(0.35, 0.55))
                    reason = "lock" if Rg < 1.2 else ("tp" if self._tp() else "lock")
                else:
                    Rg = -float(r.uniform(0.85, 1.04))
                    reason = "stop"
                    if r.random() < 0.05:
                        reason, Rg = "time", float(r.normal(-0.2, 0.3))
                hold = float(r.uniform(0.6, 30.0)) * HOUR
                exit_ms = min(int(entry_ms + hold), NOW_MS - 60_000)
                exit_px = px * (1 + side * d * Rg)
            hours = ((exit_ms or NOW_MS) - entry_ms) / HOUR
            self.entries.append({"coin": coin, "side": side, "signal_ms": int(t), "entry_ms": entry_ms, "entry": px,
                                 "stop": stop, "d": d, "Rg": Rg, "reason": reason, "exit_ms": exit_ms,
                                 "exit": exit_px, "hours": hours, "open": is_open})

    def _tp(self):
        return self.spec["kind"] == "friend" and self.rng.random() < 0.5

    def _lines(self):
        r, spec = self.rng, self.spec
        tf = spec["tf"]
        self.lines, self.curves, self.trades = {}, {}, []
        for L in grid.LEVS:
            wallet, peak, max_dd = SEED_USD, SEED_USD, 0.0
            trades = wins = liqs = skipped = streak = worst = 0
            sumR = 0.0
            ruined = False
            events = []                                       # (time, wallet after) for the curve
            open_val, n_open = 0.0, 0
            buf = 1.0 / L - 0.004
            for e in self.entries:
                if ruined:
                    break
                if e["d"] > 0.9 * buf:
                    skipped += 1
                    continue
                margin = wallet * L / 100.0
                notional = margin * L
                cost_r = 2 * (TAKER + SLIP) / e["d"]
                funding = notional * FUND8 * e["hours"] / 8.0 * (1 if r.random() < 0.7 else -1)
                Rg = e["Rg"]
                reason = e["reason"]
                if not e["open"] and L == 50 and r.random() < 0.03:
                    reason, Rg = "liq", -buf / e["d"]
                pnl = notional * e["d"] * Rg - notional * 2 * (TAKER + SLIP) - funding
                if reason == "liq":
                    pnl = -margin
                    liqs += 1
                R = Rg - cost_r
                setting = self.setting_ko if spec["kind"] != "friend" else self.settings_now[
                    grid.LEVS.index(L) * 7 + grid.COINS.index(e["coin"])]["setting_ko"]
                exit_ko = self.settings_now[0]["exit_ko"] if spec["kind"] != "friend" else self.settings_now[
                    grid.LEVS.index(L) * 7 + grid.COINS.index(e["coin"])]["exit_ko"]
                row = {"key": f"{e['coin']}|{tf}|{e['signal_ms']}|{e['side']}|{L}", "L": L, "coin": e["coin"],
                       "side": e["side"], "signal_ms": e["signal_ms"], "entry_ms": e["entry_ms"],
                       "entry": _r(e["entry"], 6), "stop": _r(e["stop"], 6), "exit_ms": e["exit_ms"],
                       "exit": _r(e["exit"], 6) if e["exit"] is not None else None,
                       "status": "open" if e["open"] else "closed", "reason": "open" if e["open"] else reason,
                       "pnl": _r(pnl, 2), "roe": _r(pnl / margin, 4), "R": _r(R, 3), "margin": _r(margin, 2),
                       "funding": _r(-funding, 2), "setting_ko": setting, "exit_ko": exit_ko}
                self.trades.append(row)
                if e["open"]:
                    open_val += pnl
                    n_open += 1
                    continue
                wallet += pnl
                trades += 1
                sumR += R
                if R > 0:
                    wins += 1
                    streak = 0
                else:
                    streak += 1
                    worst = max(worst, streak)
                peak = max(peak, wallet)
                max_dd = max(max_dd, (peak - wallet) / peak * 100)
                events.append((e["exit_ms"], wallet))
                if wallet < SEED_USD * 0.1:
                    ruined = True
            equity = wallet + (open_val if not ruined else 0.0)
            today0 = NOW_MS - (NOW_MS + 9 * HOUR) % DAY
            before = [w for t, w in events if t < today0]
            today_pnl = equity - (before[-1] if before else SEED_USD)
            self.lines[str(L)] = {
                "equity": _r(equity, 2), "wallet": _r(wallet, 2), "pnl": _r(equity - SEED_USD, 2),
                "pnl_pct": _r((equity - SEED_USD) / SEED_USD * 100, 2), "today_pnl": _r(today_pnl, 2),
                "trades": trades, "wins": wins, "win_rate": _r(wins / trades, 4) if trades else None,
                "mean_R": _r(sumR / trades, 3) if trades else None, "max_dd": _r(max_dd / 100, 4),   # a 0-1 ratio
                "open": 0 if ruined else n_open, "liqs": liqs, "skipped": skipped, "worst_streak": worst,
                "ruined": ruined, "setting_ko": self.line_setting.get(str(L), self.setting_ko)}
            # the curve: hourly points, wallet plus a little open value
            pts, j, w = [], 0, SEED_USD
            ev = sorted(events)
            for t in range(self.live_start, NOW_MS + 1, HOUR):
                while j < len(ev) and ev[j][0] <= t:
                    w = ev[j][1]
                    j += 1
                pts.append([t, _r(w + (0 if ruined else float(r.normal(0, 0.004)) * w), 2)])
            pts.append([NOW_MS, _r(equity, 2)])
            self.curves[str(L)] = pts[-800:]
        self.trades.sort(key=lambda t: (t["exit_ms"] or NOW_MS + 1, t["entry_ms"], t["L"]), reverse=True)
        self.trades = self.trades[:600]

    def _decisions(self):
        r, spec = self.rng, self.spec
        if spec["kind"] in ("fixed", "flip", "private"):
            return
        strat = spec["strategy"]
        win = "4주" if spec["sub"] == "r4" else "26주"
        closed = sorted({e["exit_ms"] for e in self.entries if not e["open"]})
        if spec["sub"] in ("r26", "r4", "r26c"):
            times = closed[4::5]
        else:                                                  # Mondays 00:00 UTC since the live start
            first = self.live_start - (self.live_start - 4 * DAY) % (7 * DAY) + 7 * DAY
            times = list(range(first, NOW_MS, 7 * DAY))
        prev = {}
        for t in times:
            if spec["kind"] == "friend":
                for L in grid.LEVS:
                    for c in grid.COINS:
                        to = f"{_label(strat, r.integers(grid.NCOMBO[strat]))} · {grid.exit_ko(int(r.integers(grid.NEXIT)))}"
                        self.decisions.append({"t_ms": int(t), "coin": c, "L": L,
                                               "from_ko": prev.get((c, L), "처음"), "to_ko": to,
                                               "why_ko": f"지난 26주 {L}배 수익 + 낙폭 최소 ({_r(float(r.uniform(4, 30)), 1)}%)"})
                        prev[(c, L)] = to
                continue
            coins = grid.COINS if spec["sub"] == "r26c" else ("ALL",)
            for c in coins:
                if spec["sub"] == "r26c" and r.random() < 0.6:
                    continue
                to = _label(strat, r.integers(grid.NCOMBO[strat]))
                n = int(r.integers(300, 2400) if win == "26주" else r.integers(40, 300))
                self.decisions.append({"t_ms": int(t), "coin": c, "L": None, "from_ko": prev.get(c, self.setting_ko),
                                       "to_ko": to, "why_ko": f"최근 {win} 주변 평균 1등 ({_r(float(r.normal(-0.04, 0.05)), 3):+.3f}R, {n:,}건)".replace("-", "−")})
                prev[c] = to
        self.decisions.sort(key=lambda d: d["t_ms"], reverse=True)

    def row(self) -> dict:
        s = self.spec
        return {"id": s["id"], "kind": s["kind"], "sub": s["sub"], "name": s["name"], "strategy": s["strategy"],
                "short": s["short"], "tf": s["tf"], "rule_ko": s["rule_ko"], "setting_ko": self.setting_ko,
                "lines": self.lines, "switches": len(self.decisions),
                "last_switch_ms": self.decisions[0]["t_ms"] if self.decisions else None}

    def detail(self) -> dict:
        return {**self.row(), "generated_ms": NOW_MS, "curves": self.curves, "trades": self.trades,
                "decisions": self.decisions, "settings_now": self.settings_now}


# ---------------------------------------------------------------- ranking arrays
def _exit_arrays():
    """Per exit of grid.EXITS (read at call time: 13 or 14 exits, CONTRACT 7.1): the payoff of a win in R, the stop
    distance in ATR, and a trade-count factor (faster exits: more trades)."""
    X, K, NF = [], [], []
    for name in grid.EXITS:
        m = re.fullmatch(r"tp([\d.]+)R_sl([\d.]+)atr", name)
        if name == "house":
            x, k, nf = 1.6, 2.0, 1.0
        elif m:
            x, k = float(m.group(1)), float(m.group(2))
            nf = 1.3 - 0.12 * x - 0.04 * k
        else:                                    # e.g. half1R_be_1.5R: half at 1R, the rest at 1.5R or break-even
            x, k, nf = 1.0, 2.0, 1.1
        X.append(x)
        K.append(k)
        NF.append(nf)
    return np.array(X), np.array(K), np.array(NF)


def _combo_shape(strat):
    C = grid.NCOMBO[strat]
    t = np.array([grid.combo_tuple(strat, c) for c in range(C)], float)
    u = t / (np.array(grid.SHAPE[strat], float) - 1)
    return C, u


def fake_rank(strat, tf, rng, live_start):
    EXIT_X, EXIT_K, EXIT_NF = _exit_arrays()
    C, u = _combo_shape(strat)
    W, E, S = len(grid.WINDOWS), grid.NEXIT, len(grid.SCOPES)
    edge = (0.03 * np.sin(2.4 * u[:, 0] + 0.6) * np.cos(1.9 * u[:, 1] - 0.4) + 0.025 * (u[:, 2] - 0.5)
            + (0.015 * np.cos(3.0 * u[:, 3]) if u.shape[1] > 3 else 0.0) + {"S2": 0.0, "N02": -0.01, "N04": 0.005}[grid.SHORT[strat]]
            + (0.01 if tf == "30m" else 0.0))
    sig = 1.7 / (1 + 1.3 * u[:, 1]) * (1 + 0.35 * (1 - u[:, 0]))
    whip0 = np.clip(0.06 + 0.42 * (1 - u[:, 1]) * (0.65 + 0.35 * (1 - u[:, 0])), 0.02, 0.8)
    bars_day = 96 if tf == "15m" else 48
    days = np.array([(NOW_MS - live_start) / DAY, 182.0, 28.0])
    p0 = 0.006 if tf == "15m" else 0.0085
    coinf = np.array([1.0, 1.05, 1.15, 1.1, 0.95, 0.9, 1.05])
    atr = ATR_PCT[tf]
    cost = 2 * (TAKER + SLIP) / (EXIT_K * atr) + FUND8 * 1.5                 # (E,) cost in R per trade
    rate = (days[:, None, None, None] * bars_day * p0 * EXIT_NF[None, :, None, None] * coinf[None, None, :, None]
            * sig[None, None, None, :])
    n = rng.poisson(rate).astype(np.float64)                                 # (W,E,7,C)
    g = (edge[None, None, None, :] + rng.normal(0, 0.03, (W, 1, 7, 1)) + rng.normal(0, 0.02, (W, E, 7, C))
         + 0.012 * (EXIT_K[None, :, None, None] - 2))
    x = EXIT_X[None, :, None, None]
    p = np.clip((1 + g) / (1 + x), 0.03, 0.97)
    wins = rng.binomial(n.astype(np.int64), p).astype(np.float64)
    costb = cost[None, :, None, None]
    aw = np.where(wins > 0, x * rng.uniform(0.9, 1.05, n.shape) - costb, np.nan)
    aw = np.where(np.arange(E)[None, :, None, None] == 0, rng.lognormal(0.5, 0.15, n.shape) - costb, aw)
    aw = np.where(wins > 0, aw, np.nan)
    al = np.where(n - wins > 0, rng.uniform(0.93, 1.03, n.shape) + costb, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_R = np.where(n > 0, (wins * np.nan_to_num(aw) - (n - wins) * np.nan_to_num(al)) / np.where(n > 0, n, 1), np.nan)
    mean_G = np.where(n > 0, mean_R + costb + rng.normal(0, 0.004, n.shape), np.nan)
    mdd = np.where(n > 0, np.sqrt(n) * 1.25 * rng.uniform(0.7, 1.4, n.shape) + np.maximum(0, -np.nan_to_num(mean_R)) * n * 0.55, 0.0)
    whip = np.clip(whip0[None, None, None, :] + rng.normal(0, 0.03, n.shape), 0.0, 0.95)
    opn = (rng.random((1, E, 7, C)) < 0.12).astype(np.float64).repeat(W, 0)
    nsig = n + opn + rng.poisson(n * 0.12)
    # pooled scope
    N = n.sum(2)
    Wn = wins.sum(2)
    with np.errstate(invalid="ignore", divide="ignore"):
        mR = np.where(N > 0, np.nansum(n * np.nan_to_num(mean_R), 2) / np.where(N > 0, N, 1), np.nan)
        mG = np.where(N > 0, np.nansum(n * np.nan_to_num(mean_G), 2) / np.where(N > 0, N, 1), np.nan)
        AW = np.where(Wn > 0, np.nansum(wins * np.nan_to_num(aw), 2) / np.where(Wn > 0, Wn, 1), np.nan)
        L_ = N - Wn
        AL = np.where(L_ > 0, np.nansum((n - wins) * np.nan_to_num(al), 2) / np.where(L_ > 0, L_, 1), np.nan)
        WH = np.where(nsig.sum(2) > 0, (whip * nsig).sum(2) / np.maximum(nsig.sum(2), 1), whip.mean(2))
    MDD = np.sqrt((mdd ** 2).sum(2)) * 1.15
    stats = np.full((W, E, S, C, 11), np.nan, np.float64)
    for k, (pool, per) in enumerate(((N, n), (Wn, wins), (mR, mean_R), (mG, mean_G), (MDD, mdd), (WH, whip),
                                     (AW, aw), (AL, al))):
        stats[:, :, 0, :, k] = pool
        stats[:, :, 1:, :, k] = per
    stats[:, :, 0, :, 9] = opn.sum(2)
    stats[:, :, 1:, :, 9] = opn
    stats[:, :, 0, :, 10] = nsig.sum(2)
    stats[:, :, 1:, :, 10] = nsig
    scale = 1.0 if tf == "15m" else 0.5
    min_n = np.array([[int(30 * scale) or 15, 8], [int(300 * scale), int(50 * scale)], [int(60 * scale), 12]], np.int32)
    # plateau: grid.plateau for every (window, exit, scope) at once (one matrix product instead of 312 calls)
    M = grid.neighbour_matrix(strat)
    nn = stats[..., 0].reshape(-1, C).T                                    # (C, W*E*S)
    mm = stats[..., 2].reshape(-1, C).T
    num = M @ np.where(nn >= 1, np.nan_to_num(mm), 0.0).astype(np.float32)
    den = M @ (nn >= 1).astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        sc = (num / den).T.reshape(W, E, S, C)
    need = np.where(np.arange(S)[None, :] == 0, min_n[:, :1], min_n[:, 1:])[:, None, :, None]    # (W,1,S,1)
    stats[..., 8] = np.where(stats[..., 0] >= need, sc, np.nan)
    luck = np.zeros((W, E, S), np.float32)
    for w in range(W):
        for e in range(E):
            for s in range(S):
                nn1 = stats[w, e, s, :, 0]
                med = float(np.median(nn1[nn1 > 0])) if (nn1 > 0).any() else 1.0
                luck[w, e, s] = -cost[e] + 2.9 * 1.25 * (EXIT_X[e] ** 0.5) / math.sqrt(max(med, 1.0)) * 0.7
    bounds = np.array([[live_start, NOW_MS], [NOW_MS - 182 * DAY, NOW_MS], [NOW_MS - 28 * DAY, NOW_MS]], np.int64)
    return {"stats": stats.astype(np.float32), "luck95": luck, "min_n": min_n, "bounds_ms": bounds,
            "generated_ms": np.int64(NOW_MS - 40_000)}


def fake_past(strat, tf, rng):
    EXIT_X, EXIT_K, EXIT_NF = _exit_arrays()
    C, u = _combo_shape(strat)
    P, S = len(PERIODS), len(grid.SCOPES)
    edge = 0.03 * np.sin(2.4 * u[:, 0] + 0.6) * np.cos(1.9 * u[:, 1] - 0.4) + 0.025 * (u[:, 2] - 0.5)
    years = np.array([1.0, 3.0, 2.75, 1 / 12, 1 / 12, 1 / 12])
    base = (700 if tf == "15m" else 420) * years
    n = rng.poisson(base[:, None, None, None] * EXIT_NF[None, :, None, None] * np.where(np.arange(S) == 0, 7, 1)[None, None, :, None]
                    * (1.7 / (1 + 1.3 * u[:, 1]))[None, None, None, :]).astype(np.float64)
    cost = 2 * (TAKER + SLIP) / (EXIT_K * ATR_PCT[tf])
    mean = (edge[None, None, None, :] - cost[None, :, None, None] + rng.normal(0, 0.05, (P, 1, S, 1))
            + rng.normal(0, 0.6, n.shape) / np.sqrt(np.maximum(n, 1)))
    x = EXIT_X[None, :, None, None]
    wr = np.clip((1 + mean + cost[None, :, None, None]) / (1 + x) + rng.normal(0, 0.02, n.shape), 0.02, 0.98)
    out = np.stack([n, np.where(n > 0, wr, np.nan), np.where(n > 0, mean, np.nan)], -1)
    out[3:, 1:] = np.nan                                     # crash months: only the house exit was computed
    return {"stats": out.astype(np.float32)}


# ---------------------------------------------------------------- the view log (CONTRACT 7.3)
VIEW_MEMOS = ("4시간 저항대 다시 시험, 거래량 줄어듦", "펀딩 과열이라 숏 쪽", "주말이라 얕게만", "어제 고점 돌파 실패",
              "<b>태그</b>도 글자로 보여야 합니다", "", "", "1시간 다이버전스", "CME 갭 메우기 기대", "발표 전이라 짧게",
              "지지선 세 번째 터치", "")
VIEW_RULES_KO = (
    "기준 가격 = 관점 시각 다음 15분봉의 시가",
    "방향: 4시간 · 24시간 · 48시간 뒤 15분 종가가 말한 방향으로 움직였으면 맞힘",
    "도달: 48시간 안에 15분봉이 가장 가까운 구간 끝을 건드렸나",
    "구간 바로 진입: 가장 가까운 구간 끝에 지정가 (메이커 0.02%)",
    "15분 종가 확인 진입: 구간을 건드린 뒤 15분 종가가 다시 그 끝의 진입 쪽에서 닫히면 시장가 (수수료 0.05% + 슬리피지 0.02%)",
    "손절: 적은 값, 없으면 가장 먼 구간에서 0.3% 밖 · 목표: 적은 값 (첫째에서 절반), 없으면 1R 절반 · 본전 · 2R",
    "들어간 뒤 48시간이면 정리 · 48시간 안에 못 들어가면 놓침 · 잔고 %는 20배, 두 분 규칙(증거금 20%)",
    "판정은 끝난 관점 30개부터: 방향 적중률이 50%보다 높고 (한쪽 이항검정 p < 0.05), 진입 방식의 평균 R > 0이며 주 단위 부트스트랩 하한도 > 0",
)
VIEW_COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
VIEW_COIN_P = (0.36, 0.24, 0.16, 0.09, 0.07, 0.04, 0.04)


def _binom_p(hit: int, n: int) -> float:
    """One-sided P(X >= hit) for X ~ Binomial(n, 1/2)."""
    return sum(math.comb(n, k) for k in range(hit, n + 1)) / 2 ** n


def _follow(rng, mode, view, zone_edge, stop, age_ms, reach_ms):
    """One follow mode's result (touch: a limit at the zone edge; confirm: a later close back on the trade side)."""
    out = {"status": "waiting", "entry_ms": None, "entry": None, "stop": None, "exit_ms": None, "R": None,
           "wallet20_pct": None, "legs_ko": ""}
    if reach_ms is None or (mode == "confirm" and rng.random() < 0.3):
        out["status"] = "missed" if age_ms >= 48 * HOUR else "waiting"
        return out
    entry_ms = reach_ms + (0 if mode == "touch" else int(rng.integers(1, 8)) * 15 * 60_000)
    if entry_ms > NOW_MS:
        return out
    side = view["side"]
    entry = zone_edge * (1 + side * (0 if mode == "touch" else float(rng.uniform(0.0005, 0.002))))
    dist = abs(entry - stop) / entry
    out.update(entry_ms=int(entry_ms), entry=_r(entry, 6), stop=_r(stop, 6))
    hold = float(rng.uniform(1, 40)) * HOUR
    if entry_ms + hold > NOW_MS:
        out["status"] = "open"
        out["legs_ko"] = "들어가 있음"
        return out
    u = rng.random()
    if u < 0.45:
        R, legs = -1.0 - (0.06 if mode == "confirm" else 0.03), "손절"
    elif u < 0.7:
        R, legs = 0.5 - 0.05, "절반 1R 익절 → 나머지 본전"
    elif u < 0.9:
        R, legs = 1.5 - 0.06, "절반 1R 익절 → 나머지 2R 익절"
    else:
        R, legs = float(rng.normal(0.1, 0.5)), "48시간 시간 정리"
    out.update(status="closed", exit_ms=int(entry_ms + hold), R=_r(R, 3), wallet20_pct=_r(R * dist * 4 * 100, 2),
               legs_ko=legs)
    return out


def fake_views(rng, n: int = 40) -> dict:
    views = []
    times = np.sort(rng.uniform(NOW_MS - 21 * DAY, NOW_MS - 20 * 60_000, n)).astype(np.int64)
    for i, t in enumerate(times, 1):
        t = int(t) // 60_000 * 60_000
        coin = str(rng.choice(VIEW_COINS, p=VIEW_COIN_P))
        side = 1 if rng.random() < 0.5 else -1
        px = PRICE[coin] * float(np.exp(rng.normal(0, 0.02)))
        step = px * float(rng.uniform(0.002, 0.005))
        dec = 1 if px > 1000 else 2 if px > 10 else 4
        rd = lambda x: round(x, dec)                                   # noqa: E731
        zones = {}
        for k, (lab, mult) in enumerate((("A", 1), ("B", 2), ("C", 3))):
            if lab != "B" and rng.random() < 0.35:
                zones[lab] = None
                continue
            near = px - side * mult * step
            width = 0.0 if lab == "C" and rng.random() < 0.5 else step * float(rng.uniform(0.15, 0.4))
            lo, hi = (near - width, near) if side > 0 else (near, near + width)
            zones[lab] = [rd(lo), rd(hi)]
        live = [z for z in zones.values() if z]
        nearest = max(z[1] for z in live) if side > 0 else min(z[0] for z in live)
        farthest = min(z[0] for z in live) if side > 0 else max(z[1] for z in live)
        given_stop = rng.random() < 0.7
        stop = rd(farthest * (1 - side * float(rng.uniform(0.003, 0.006)))) if given_stop else None
        stop_used = stop if stop is not None else farthest * (1 - side * 0.003)
        targets = [rd(px + side * 2 * step), rd(px + side * 4 * step)] if rng.random() < 0.5 else []
        age = NOW_MS - t
        cancelled = rng.random() < 0.05
        status = "cancelled" if cancelled else "done" if age >= 48 * HOUR else "watching"
        dirs = {}
        for hkey, hh in (("4h", 4), ("24h", 24), ("48h", 48)):
            dirs[hkey] = None if cancelled or age < hh * HOUR else _r(float(rng.normal(0.06, 0.55) * math.sqrt(hh / 4)), 2)
        reach_ms = None
        if not cancelled and rng.random() < 0.68:
            reach_ms = t + int(float(rng.uniform(0.25, 30)) * HOUR) // (15 * 60_000) * (15 * 60_000)
            if reach_ms > NOW_MS:
                reach_ms = None
        reached = None if cancelled or (reach_ms is None and age < 48 * HOUR) else reach_ms is not None
        view = {"id": i, "t_ms": t, "entered_ms": t + int(rng.integers(5, 90)) * 1000, "coin": coin, "side": side,
                "zones": zones, "stop": stop, "targets": targets, "memo": str(VIEW_MEMOS[i % len(VIEW_MEMOS)]),
                "status": status, "ref_price": _r(px, 6), "dir": dirs, "reached": reached, "reached_ms": reach_ms}
        if cancelled:
            view["follow"] = {m: {"status": "missed", "entry_ms": None, "entry": None, "stop": None, "exit_ms": None,
                                  "R": None, "wallet20_pct": None, "legs_ko": "취소됨"} for m in ("touch", "confirm")}
        else:
            view["follow"] = {m: _follow(rng, m, view, nearest, stop_used, age, reach_ms) for m in ("touch", "confirm")}
        views.append(view)
    views.reverse()                                                  # newest first
    live_views = [v for v in views if v["status"] != "cancelled"]
    done = [v for v in live_views if v["status"] == "done"]
    summ_dir = {}
    for hkey in ("4h", "24h", "48h"):
        vals = [v["dir"][hkey] for v in live_views if v["dir"][hkey] is not None]
        hit = sum(1 for x in vals if x > 0)
        summ_dir[hkey] = {"n": len(vals), "hit": hit, "rate": _r(hit / len(vals), 4) if vals else None,
                          "p": _r(_binom_p(hit, len(vals)), 4) if len(vals) >= 10 else None}
    reached = [v["reached"] for v in done if v["reached"] is not None]
    follow = {}
    for m in ("touch", "confirm"):
        fs = [v["follow"][m] for v in live_views]
        rs = [f["R"] for f in fs if f["status"] == "closed"]
        w = 1.0
        for f in fs:
            if f["status"] == "closed":
                w *= 1 + f["wallet20_pct"] / 100
        mean = float(np.mean(rs)) if rs else None
        follow[m] = {"n": len(fs), "entered": sum(1 for f in fs if f["entry_ms"] is not None),
                     "mean_R": _r(mean, 3) if rs else None,
                     "win_rate": _r(sum(1 for x in rs if x > 0) / len(rs), 4) if rs else None,
                     "sum_R": _r(float(np.sum(rs)), 3) if rs else 0.0,
                     "ci_low": _r(mean - 1.8 * float(np.std(rs)) / math.sqrt(len(rs)), 3) if len(rs) >= 5 else None,
                     "wallet20_pct": _r((w - 1) * 100, 2)}
    need = 30
    if len(done) < need:
        verdict = f"표본 부족 ({len(done)}/{need})"
    else:
        d24 = summ_dir["24h"]
        verdict = (f"방향 24시간 적중 {d24['rate'] * 100:.1f}% (p {d24['p']:.2f}) · 바로 진입 평균 "
                   f"{follow['touch']['mean_R']:+.3f}R · 확인 진입 평균 {follow['confirm']['mean_R']:+.3f}R: "
                   "아직 실력이라 말하기 어렵습니다").replace("-", "−")
    return {"generated_ms": NOW_MS, "rules_ko": list(VIEW_RULES_KO),
            "summary": {"n": len(live_views), "n_done": len(done), "need": need, "verdict_ko": verdict, "dir": summ_dir,
                        "reached_rate": _r(sum(reached) / len(reached), 4) if reached else None, "follow": follow},
            "views": views[:300]}


# ---------------------------------------------------------------- the other files
def judge_rows(accts, rank_luck) -> tuple:
    rows, passed = [], 0
    for a in accts:
        s = a.spec
        for L in grid.LEVS:
            ln = a.lines[str(L)]
            n, mR, dd = ln["trades"], ln["mean_R"], ln["max_dd"] * 100
            luck = rank_luck.get((s["strategy"], s["tf"]), 0.0) if s["strategy"] else 0.0
            ours = [{"name_ko": "실시간 거래 100건 이상", "ok": n >= 100, "value_ko": f"{n}건"},
                    {"name_ko": "평균 R (수수료 후) 0보다 큼", "ok": bool(mR is not None and mR > 0),
                     "value_ko": "—" if mR is None else f"{mR:+.3f}R".replace("-", "−")},
                    {"name_ko": "운 기준선 위", "ok": bool(mR is not None and mR > luck),
                     "value_ko": "—" if mR is None else f"{mR:+.3f}R (기준 {luck:+.3f}R)".replace("-", "−")},
                    {"name_ko": "최대 낙폭 35% 이하", "ok": dd <= 35, "value_ko": f"{dd:.1f}%"},
                    {"name_ko": "파산 없음", "ok": not ln["ruined"], "value_ko": "파산" if ln["ruined"] else "없음"}]
            weeks_plus = int(a.rng.integers(0, 2))
            friend = {"pass": None, "checks": []}
            if s["kind"] != "flip":
                fchecks = [{"name_ko": "지난주 고른 설정으로 이번 주 +", "ok": ln["today_pnl"] > 0 and ln["pnl"] > 0,
                            "value_ko": ("+" if ln["pnl"] >= 0 else "−") + f"${abs(ln['pnl']):,.2f}"},
                           {"name_ko": "4주 연속 +", "ok": False, "value_ko": f"{weeks_plus}주 / 4주"},
                           {"name_ko": "최대 낙폭 30% 이하", "ok": dd <= 30, "value_ko": f"{dd:.1f}%"}]
                friend = {"pass": all(c["ok"] for c in fchecks), "checks": fchecks}
            ok = all(c["ok"] for c in ours)
            passed += ok
            rows.append({"id": s["id"], "name": s["name"], "L": L, "ours": {"pass": ok, "checks": ours},
                         "friend": friend})
    return rows, passed


def build(outdir: str, seed: int = 7, past5y_dir=None, phase: str = "live", empty: bool = False,
          now_ms: int = FIXED_NOW_MS, views: int = 40) -> dict:
    """Write the fake snapshot folder; returns a few facts about it (for tests). now_ms: the fake 'now' (rounded down
    to 15 minutes); the default is a fixed date so the files are the same on every run."""
    global NOW_MS
    NOW_MS = int(now_ms) // (15 * 60_000) * (15 * 60_000)
    rng = np.random.default_rng(seed)
    prng = np.random.default_rng(seed + 1)          # the 5-year files: their own stream, so writing them changes nothing else
    os.makedirs(outdir, exist_ok=True)
    live_start = NOW_MS - int(LIVE_DAYS * DAY) // (15 * 60_000) * (15 * 60_000)
    status = {
        "generated_ms": NOW_MS, "version": "demobot-1", "phase": phase, "live_start_ms": live_start,
        "history_start_ms": live_start - 182 * DAY,
        "last_bar_ms": {"15m": NOW_MS - 15 * 60_000, "30m": NOW_MS - 45 * 60_000}, "last_tick_ms": NOW_MS - 20_000,
        "tick_seconds": 41.7, "next_tick_ms": NOW_MS + 15 * 60_000 - 20_000, "data_ok": True,
        "data_issues": [f"XRPUSD 15분봉 1개 늦게 도착 ({_kst(NOW_MS - 2 * HOUR)}, 다시 받음)"], "errors": [],
        "coins": list(grid.COINS), "tfs": list(grid.TFS), "leverages": list(grid.LEVS), "seed": SEED_USD,
        "costs": {"taker": TAKER, "slippage": SLIP, "funding_8h_ranking": FUND8, "funding_accounts": "real"},
        "counts": {"settings": sum(grid.NCOMBO.values()), "players": sum(grid.NCOMBO.values()) * 14,
                   "cells_open": 214, "cells_total": sum(grid.NCOMBO.values()) * grid.NEXIT * 2 * len(grid.COINS),
                   "signals_24h": 18_442},
        "proc": {"rss_mb": 412.6, "cpu_pct": 11.8}, "db_mb": 1_284.3, "disk_free_mb": 31_870.0,
        "telegram": {"configured": True, "queued": 0, "last_ok_ms": NOW_MS - 15 * 60_000 + 30_000, "last_error": None}}
    if phase == "warm":
        status.update({"live_start_ms": None, "last_tick_ms": None, "next_tick_ms": None})
    _write_json(os.path.join(outdir, "status.json"), status)
    if empty:
        return {"accounts": 0}

    # ranks first (the home leaders and the judge's luck lines read them)
    leaders, rank_luck, files = [], {}, []
    for strat in grid.STRATS:
        for tf in grid.TFS:
            z = fake_rank(strat, tf, rng, live_start)
            name = f"rank_{strat}_{tf}.npz"
            _write_npz(os.path.join(outdir, name), **z)
            files.append(name)
            w, e = grid.WINDOWS.index("26w"), 0
            cell = z["stats"][w, e, 0].astype(float)
            c = grid.top(cell[:, 8])[0]
            luck = float(z["luck95"][w, e, 0])
            rank_luck[(strat, tf)] = round(luck, 3)
            n = int(cell[c, 0])
            mR = float(cell[c, 2])
            leaders.append({"strategy": strat, "tf": tf, "window": "26w", "exit": "house", "label": _label(strat, c),
                            "n": n, "mean_R": _r(mR, 4), "win_rate": _r(cell[c, 1] / n, 4) if n else None,
                            "luck95": _r(luck, 4), "beats_luck": bool(mR > luck)})
            if past5y_dir:
                os.makedirs(past5y_dir, exist_ok=True)
                _write_npz(os.path.join(past5y_dir, f"past5y_{strat}_{tf}.npz"), **fake_past(strat, tf, prng))
    _write_json(os.path.join(outdir, "rank_meta.json"), {
        "generated_ms": NOW_MS - 40_000, "build_seconds": 6.4, "files": files, "windows": list(grid.WINDOWS),
        "exits": list(grid.EXITS), "scopes": list(grid.SCOPES), "players": status["counts"]["players"],
        "luck_draws": 2000})

    accts = [_Acct(sp, rng, live_start) for sp in account_specs()]
    rows = [a.row() for a in accts]
    _write_json(os.path.join(outdir, "accounts.json"), {"generated_ms": NOW_MS, "live_start_ms": live_start,
                                                        "accounts": rows})
    for a in accts:
        _write_json(os.path.join(outdir, "acct", a.spec["id"] + ".json"), a.detail())
    all_trades = [{**t, "account": a.spec["id"], "name": a.spec["name"]} for a in accts for t in a.trades]
    all_trades.sort(key=lambda t: (t["exit_ms"] or NOW_MS + 1, t["entry_ms"]), reverse=True)
    _write_json(os.path.join(outdir, "trades.json"), {"generated_ms": NOW_MS, "trades": all_trades[:300]})

    jrows, passed = judge_rows(accts, rank_luck)
    _write_json(os.path.join(outdir, "judge.json"), {
        "generated_ms": NOW_MS,
        "verdict_ko": "실전 금지: 아직 통과한 계좌가 없습니다" if not passed else f"통과 {passed}개: 그래도 실전은 두 분이 정합니다",
        "rules_ko": {"ours": ["실시간 거래 100건 이상", "평균 R (수수료 후) 0보다 큼", "운 기준선 위",
                              "최대 낙폭 35% 이하", "파산 없음"],
                     "friend": ["지난 26주에 수익 + 낙폭 최소 설정을 일주일 돌려 +", "그렇게 4주 연속 +",
                                "최대 낙폭 30% 이하"]},
        "rows": jrows})

    lines = [(a, L, a.lines[str(L)]) for a in accts for L in grid.LEVS]
    lines.sort(key=lambda x: x[2]["pnl_pct"], reverse=True)
    pick = lambda xs: [{"id": a.spec["id"], "name": a.spec["name"], "L": L, "pnl_pct": ln["pnl_pct"]} for a, L, ln in xs]
    by_kind = []
    for kind, ko in KIND_KO.items():
        ks = [a for a in accts if a.spec["kind"] == kind]
        by_kind.append({"kind": kind, "kind_ko": ko, "accounts": len(ks),
                        "mean_pnl_pct": {str(L): _r(float(np.mean([a.lines[str(L)]["pnl_pct"] for a in ks])), 2)
                                         for L in grid.LEVS}})
    switches = sorted(({**d, "account": a.spec["id"], "name": a.spec["name"]} for a in accts for d in a.decisions),
                      key=lambda d: d["t_ms"], reverse=True)
    home = {"generated_ms": NOW_MS, "live_days": round((NOW_MS - live_start) / DAY, 2), "phase": phase,
            "totals": {"accounts": len(accts), "open_positions": sum(1 for t in all_trades if t["status"] == "open"),
                       "trades": sum(ln["trades"] for _a, _L, ln in lines), "passed": passed},
            "best": pick(lines[:5]), "worst": pick(lines[::-1][:5]), "by_kind": by_kind, "leaders": leaders,
            "recent_switches": switches[:10], "recent_trades": all_trades[:12]}
    _write_json(os.path.join(outdir, "home.json"), home)
    # the view log: its own random stream, so the number of views changes nothing else
    _write_json(os.path.join(outdir, "views.json"), fake_views(np.random.default_rng(seed + 2), views))
    return {"accounts": len(accts), "passed": passed, "trades": len(all_trades), "live_start_ms": live_start}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demobot.dash.fake", description=__doc__.splitlines()[0])
    ap.add_argument("outdir")
    ap.add_argument("--past5y", default=None, help="also write fake past5y_<STRAT>_<tf>.npz into this folder")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--phase", default="live", choices=["live", "warm"])
    ap.add_argument("--empty", action="store_true", help="only status.json (nothing else written yet)")
    ap.add_argument("--views", type=int, default=40, help="views in views.json (under 30 finished: 표본 부족)")
    ap.add_argument("--now", default=None, help="'now' for the current time, or epoch ms (default: a fixed date)")
    a = ap.parse_args(argv)
    now = FIXED_NOW_MS if a.now is None else int(datetime.datetime.now(UTC).timestamp() * 1000) if a.now == "now" else int(a.now)
    facts = build(a.outdir, seed=a.seed, past5y_dir=a.past5y, phase=a.phase, empty=a.empty, now_ms=now, views=a.views)
    print(f"fake snapshot written to {a.outdir}: {facts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
