"""Owners 10/26: "사진은 커스텀값봇 매매법인데 지금 돌아가는 추세봇에 추가로 넣고싶어 근데 그 대신 21승3패인데 왜 3패가 나왔는지
분석해주고 보완해서 돌리고 싶어" (candidate league account ds-F7_RF_TRIPLE-1h-1-tp10: 레인지 필터 3중 일치 1시간, custom numbers
rf_period 80 / rf_mult 9.0, 고정 익절 +10 %, 손절 최대 2 ATR).

Arms (PLAN.md, written before any five-year number of this file was seen; the forward reads came first):
  L0  the league account as it is: 30x, margin 30 %, the league's entry check (paperbot.sizing.size_position: stop at least
      1 ATR inside liquidation, loss at the stop <= 15 % of the wallet), stop 2 ATR, take-profit net +10 %.
  L1  L0 + the 추세판단 봇's gates (trendjudge.check on the last closed 4h bar, the 1h entry bar; no_chase; KST weekend,
      NYSE open 22:00-23:00 KST (pre 30 / post 30), macro releases +-30 min).
  T0  the member inside the 추세판단 봇: L1's gates, BTC 40x / others 30x, margin 40 %, the bot's exit (stop -50 % net,
      ladder 10@11, 12@15, +5 each: reached - 3, JUDGE / REV before the first lock).
  T1  L1's gates with the league's exit at the bot's size (BTC 40x / others 30x, margin 40 %).
  plus the fixes PLAN.md lists, and every arm's coin-flip twin (the same entries, the side drawn at random).

One wallet, one position, $1,000 at the start of each window (a bust in one window does not hide the next).
Run: python3 study.py --bars FIVE5M_DIR --work WORK_DIR [--arms L0,L1,...]"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import sim as S  # noqa: E402

COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
MIN, FIVE, HOUR, DAY = 60_000, 300_000, 3_600_000, 86_400_000
KST = 9 * HOUR


def ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value // 1_000_000)


WINDOWS = {"2020": (ms("2020-03-01"), ms("2021-01-01")), "2021-2023": (ms("2021-01-01"), ms("2024-01-01")),
           "2024-2026.09": (ms("2024-01-01"), ms("2026-10-01")), "2026.10": (ms("2026-10-01"), ms("2026-10-25")),
           "league": (ms("2026-10-13 12:00"), ms("2026-10-25"))}


def macro_times() -> np.ndarray:
    t = [int(e["t_ms"]) for e in json.load(open(os.path.join(REPO, "research/hunt/macro_calendar.json")))["events"]]
    from paperbot import events as EV
    evs, _ = EV.parse(open(os.path.join(REPO, "data/macro_events.csv")).read())
    t += [e.ts_ms for e in evs]
    return np.array(sorted(set(t)), dtype=np.int64)


class World:
    def __init__(self, bars_dir: str, work: str):
        self.m5, self.p = {}, {}
        for c in COINS:
            z = np.load(os.path.join(bars_dir, "5m", f"{c}.npz"))
            self.m5[c] = {k: z[k] for k in ("ts", "o", "h", "l", "c", "fund")}
            self.p[c] = dict(np.load(os.path.join(work, "prep", f"{c}.npz")))
        self.macro = macro_times()
        from paperbot import combo as C
        self.C = C

    # ------------------------------------------------------------------ candidates (every signal with what was read)
    def candidates(self, key: str = "sig_c") -> pd.DataFrame:
        from paperbot import trendjudge as TJ
        rules = TJ.TrendRules.from_dict(json.load(open(os.path.join(REPO, "deploy/combo.trend.json")))["trend"])
        rows = []
        for ci, c in enumerate(COINS):
            p, m = self.p[c], self.m5[c]
            t_close = p["h1_ts"] + HOUR
            j4c = p["j4_ts"] + 4 * HOUR
            jdc = p["jd_ts"] + DAY
            hh, hl = p["h1_h"], p["h1_l"]
            idx = np.flatnonzero(p[key] != 0)
            for i in idx:
                t = int(t_close[i])
                side = int(p[key][i])
                k = int(np.searchsorted(j4c, t, side="right")) - 1          # last 4h bar closed at or before t
                kd = int(np.searchsorted(jdc, t, side="right")) - 1
                e5 = int(np.searchsorted(m["ts"], t))                       # the 5m bar opening at (or after) the close
                if k < 1 or i < 200 or e5 >= len(m["ts"]) or m["ts"][e5] - t > 30 * MIN:
                    continue
                ref = float(p["h1_c"][i])
                votes = {v: int(p[f"j4_{v}"][k]) for v in TJ.JUDGES}
                raw = int(p["j4_raw3"][k])
                j = TJ.Judgment(symbol=c, tf="4h", bar_close=int(j4c[k]), votes=votes, raw=raw, dir=raw, held=(raw,),
                                adx=float(p["j4_adx"][k]), adx_prev=float(p["j4_adx"][k - 1]), close=float(p["j4_close"][k]),
                                ema20=float(p["j4_ema20"][k]), atr=float(p["j4_atr"][k]))
                s = TJ.Spot(tf="1h", bar_close=t, close=ref, ema20=float(p["s_ema20"][i]), atr=float(p["s_atr"][i]),
                            rsi=float(p["s_rsi"][i]), range=float(p["s_range"][i]))
                ok = all(math.isfinite(x) for x in (j.adx, j.adx_prev, j.ema20, j.atr, s.ema20, s.atr, s.rsi)) and s.atr > 0
                why = TJ.check(rules, "F7_RF_TRIPLE", "1h", side, ref, j, s)[0] if ok else "값 없음"
                # chase: the coin's hourly highs / lows of the 24 h and 7 days ending with the signal bar
                lo24, lo7 = max(0, i - 23), max(0, i - 167)
                p24 = (ref - hl[lo24:i + 1].min()) / max(hh[lo24:i + 1].max() - hl[lo24:i + 1].min(), 1e-12)
                p7 = (ref - hl[lo7:i + 1].min()) / max(hh[lo7:i + 1].max() - hl[lo7:i + 1].min(), 1e-12)
                chase = (side > 0 and (p24 >= 0.9 or p7 >= 0.8)) or (side < 0 and (p24 <= 0.1 or p7 <= 0.2))
                weekend = bool(self.C.kst_weekend(t))
                us = bool(self.C.us_open_pause(t, 30, 30))
                a = np.searchsorted(self.macro, t - 30 * MIN, side="left")
                b = np.searchsorted(self.macro, t + 30 * MIN, side="right")
                rows.append(dict(t=t, coin=c, ci=ci, side=side, ref=ref, i1=int(i), e5=e5, atr=s.atr, atr_pct=s.atr / ref,
                                 rsi=s.rsi, far_e=(ref - s.ema20) / s.atr, far_h=side * (ref - j.ema20) / j.atr,
                                 j4_raw=raw, j4_up=j.up, j4_down=j.down, adx=j.adx, adx_prev=j.adx_prev,
                                 jd_raw=int(p["jd_raw3"][kd]) if kd >= 0 else 0, why=why, p24=p24, p7=p7, chase=chase,
                                 weekend=weekend, us_open=us, macro=bool(b > a), j4k=k,
                                 range_atr=s.range / s.atr, hour_kst=int(((t + KST) // HOUR) % 24)))
        d = pd.DataFrame(rows).sort_values(["t", "ci"]).reset_index(drop=True)
        btc = d[d.coin == "BTCUSDT"]
        # BTC's own 4h judgment at each signal (for every coin)
        pb = self.p["BTCUSDT"]
        j4b = pb["j4_ts"] + 4 * HOUR
        kb = np.searchsorted(j4b, d["t"].to_numpy(), side="right") - 1
        d["btc_j4"] = pb["j4_raw3"][np.clip(kb, 0, None)]
        del btc
        return d

    # ------------------------------------------------------------------ supervisor times (trend exit)
    def sup_at(self, coin: str, side: int, t_entry: int, e5: int, key: str = "sig_c", judge: bool = True,
               rev: bool = True) -> int | None:
        p, m = self.p[coin], self.m5[coin]
        best = None
        if judge:
            j4c = p["j4_ts"] + 4 * HOUR
            k0 = int(np.searchsorted(j4c, t_entry, side="right"))       # 4h bars closing after the entry
            bad = np.flatnonzero(p["j4_raw3"][k0:k0 + 400] == -side)
            if len(bad):
                best = int(j4c[k0 + bad[0]])
        if rev:
            t1 = p["h1_ts"] + HOUR
            i0 = int(np.searchsorted(t1, t_entry, side="right"))
            opp = np.flatnonzero(p[key][i0:i0 + 2000] == -side)
            if len(opp):
                tr = int(t1[i0 + opp[0]])
                best = tr if best is None else min(best, tr)
        if best is None:
            return None
        return int(np.searchsorted(m["ts"], best))


_LEAGUE = {}


def league_size_ok(entry: float, side: int, stop: float, atr: float, equity: float) -> bool:
    """The league's own sizing check at 30x (the floor CANDLEAGUE_MIN_LEV=30; every trade of the account was 30x)."""
    if not _LEAGUE:
        from candleague import exits as X
        from paperbot.margin import Brackets
        os.environ.setdefault("CANDLEAGUE_MIN_LEV", "30")
        _LEAGUE["st"] = X.settings_for("roe10|2", initial_equity=1000.0)
        _LEAGUE["br"] = Brackets.example()
    from paperbot.sizing import size_position
    d = size_position(_LEAGUE["st"], equity, side, entry, stop, "normal", _LEAGUE["br"], atr=atr)
    return bool(d.ok and d.leverage == 30)


def run_arm(W: World, cand: pd.DataFrame, arm: dict, a: int, b: int, flip_rng=None) -> pd.DataFrame:
    """One wallet, one position over [a, b). Returns the trades."""
    eq, busy_until = 1000.0, -1
    out = []
    c = cand[(cand.t >= a) & (cand.t < b)]
    for t, grp in c.groupby("t", sort=True):
        if t < busy_until or eq < 10:
            continue
        g = grp
        if arm.get("gate"):
            g = g[(g.why == "") & ~g.chase & ~g.weekend & ~g.us_open & ~g.macro]
        for f in arm.get("filters", ()):
            g = g[f(g)]
        if not len(g):
            continue
        if arm.get("rank") == "score":
            sc = (np.where(np.where(g.side > 0, g.j4_up, g.j4_down) >= 4, 1.0, 0.0)
                  + np.clip(1 - np.abs(g.far_e) / 1.5, 0, None))
            g = g.assign(_sc=sc).sort_values(["_sc", "ci"], ascending=[False, True])
        took = None
        for r in g.itertuples():
            lev = arm["lev"](r.coin)
            side = int(r.side)
            if flip_rng is not None:
                side = int(flip_rng.choice((-1, 1)))
            stop_dist = arm.get("stop_atr", 2.0) * r.atr
            if arm["exit"] in ("tp10", "lad", "trendlad") and arm.get("league_check", False):
                fill = W.m5[r.coin]["o"][r.e5] * (1 + side * S.SLIP)
                if not league_size_ok(fill, side, r.ref - side * stop_dist, r.atr, eq):
                    continue
            sup = None
            if arm["exit"] == "trend":
                sup = W.sup_at(r.coin, int(r.side), int(r.t), int(r.e5), judge=arm.get("judge", True),
                               rev=arm.get("rev", True))
            if arm.get("liq_check"):                  # the stop at least 1 ATR inside liquidation (first bracket, mmr 0.5 %)
                fill = W.m5[r.coin]["o"][r.e5] * (1 + side * S.SLIP)
                dist = (arm["stop_roe"] / lev - S.RT) * fill if arm.get("stop_roe") else stop_dist
                if dist + r.atr > (1.0 / lev - 0.005) * fill:
                    continue
            res = S.run_position(W.m5[r.coin], int(r.e5), side, lev, float(r.ref), arm["exit"], stop_dist, sup,
                                 tp_roe=arm.get("tp_roe", 0.10), lad=arm.get("lad"), stop_roe=arm.get("stop_roe"))
            took = (r, side, lev, res)
            break
        if took is None:
            continue
        r, side, lev, res = took
        mfrac = arm["margin"](r.coin)
        roe = max(res["roe"], -1.0)
        before = eq
        eq = eq * (1 + mfrac * roe)
        m = W.m5[r.coin]
        busy_until = int(m["ts"][res["exit_i"]]) + FIVE
        out.append(dict(r._asdict(), side=side, lev=lev, margin=mfrac, roe=roe, mfe=res["mfe"], reason=res["reason"],
                        exit_t=int(m["ts"][res["exit_i"]]), fill=res["fill"], exit_px=res["exit_px"], eq_before=before,
                        eq_after=eq))
    return pd.DataFrame(out)


def summary(T: pd.DataFrame) -> dict:
    if not len(T):
        return {"n": 0}
    r = T.roe.to_numpy()
    eq = np.r_[1000.0, T.eq_after.to_numpy()]
    dd = float(np.max(1 - eq / np.maximum.accumulate(eq)))
    g = np.log(np.maximum(T.eq_after.to_numpy(), 1e-9) / T.eq_before.to_numpy())
    return {"n": int(len(T)), "win": float((r > 0).mean()), "mean_roe": float(r.mean()), "avg_win": float(r[r > 0].mean()) if (r > 0).any() else None,
            "avg_loss": float(r[r <= 0].mean()) if (r <= 0).any() else None, "end": float(eq[-1]), "mdd": dd,
            "bust": bool(eq[-1] < 10), "mean_log": float(g.mean()), "sl": int((T.reason == "SL").sum())}


LEV30 = lambda c: 30.0  # noqa: E731
LEVT = lambda c: 40.0 if c == "BTCUSDT" else 30.0  # noqa: E731
M30 = lambda c: 0.30  # noqa: E731
M40 = lambda c: 0.40  # noqa: E731

NO_FLUSH = lambda g: g.range_atr <= 2.0  # noqa: E731   A: the trend bot's big_bar_atr
J4_SIDE = lambda g: g.j4_raw == g.side  # noqa: E731     B: the 4h judge on the trade's side (보류 refused)
CHECKS = lambda g: (g.why == "") & ~g.chase  # noqa: E731  C: trendjudge.check + no chase

ARMS = {
    "L0": dict(exit="tp10", lev=LEV30, margin=M30, league_check=True),
    "A": dict(exit="tp10", lev=LEV30, margin=M30, league_check=True, filters=(NO_FLUSH,)),
    "B": dict(exit="tp10", lev=LEV30, margin=M30, league_check=True, filters=(J4_SIDE,)),
    "C": dict(exit="tp10", lev=LEV30, margin=M30, league_check=True, filters=(CHECKS,)),
    "D": dict(exit="tp10", lev=LEV30, margin=M30, league_check=True, filters=(NO_FLUSH, J4_SIDE, CHECKS)),
    "E": dict(exit="tp10", lev=LEV30, margin=M30, league_check=True, stop_atr=3.0),
    "L1": dict(exit="tp10", lev=LEV30, margin=M30, league_check=True, gate=True),
    "T0": dict(exit="trend", lev=LEVT, margin=M40, gate=True, rank="score"),
    "T1": dict(exit="tp10", lev=LEVT, margin=M40, gate=True, rank="score"),
    "TD": dict(exit="trend", lev=LEVT, margin=M40, gate=True, rank="score", filters=(NO_FLUSH, J4_SIDE)),
}
FLIP_ARMS = ("L0", "D", "T0", "TD")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--flips", type=int, default=0)
    ap.add_argument("--windows", default=",".join(WINDOWS))
    a = ap.parse_args(argv)
    S.check_ladder()
    t0 = time.time()
    W = World(a.bars, a.work)
    cp = os.path.join(a.work, "cand.pkl")
    if os.path.exists(cp):
        cand = pd.read_pickle(cp)
    else:
        cand = W.candidates()
        cand.to_pickle(cp)
    print(f"candidates {len(cand):,} ({time.time() - t0:.0f}s)", flush=True)
    res = {}
    for name in a.arms.split(","):
        arm = ARMS[name]
        res[name] = {}
        for wn in a.windows.split(","):
            wa, wb = WINDOWS[wn]
            T = run_arm(W, cand, arm, wa, wb)
            T.to_pickle(os.path.join(a.work, f"T_{name}_{wn}.pkl"))
            res[name][wn] = summary(T)
            print(name, wn, json.dumps(res[name][wn]), f"({time.time() - t0:.0f}s)", flush=True)
    if a.flips:
        for name in [x for x in a.arms.split(",") if x in FLIP_ARMS]:
            for wn in a.windows.split(","):
                wa, wb = WINDOWS[wn]
                ends, means = [], []
                for seed in range(a.flips):
                    T = run_arm(W, cand, ARMS[name], wa, wb, flip_rng=np.random.default_rng(20261026 + seed))
                    s_ = summary(T)
                    ends.append(s_.get("end", 1000.0))
                    means.append(s_.get("mean_roe", 0.0))
                ends, means = np.array(ends), np.array(means)
                own = res[name][wn]
                res[name][wn]["flip"] = {"n": a.flips, "end_p5": float(np.percentile(ends, 5)),
                                         "end_p50": float(np.median(ends)), "end_p95": float(np.percentile(ends, 95)),
                                         "mean_roe_p50": float(np.median(means)), "mean_roe_p95": float(np.percentile(means, 95)),
                                         "beat_share": float((ends < own.get("end", 1000.0)).mean())}
                print(name, wn, "flip", json.dumps(res[name][wn]["flip"]), f"({time.time() - t0:.0f}s)", flush=True)
    json.dump(res, open(os.path.join(a.work, "study.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
