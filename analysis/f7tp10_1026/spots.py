"""Owners 10/26: "신호등 추가하지 말고 ... 익절 10%랑 손절 -50%로 갈껀데 최대한 추세맞고 좋은자리에서 진입하게 하고싶은데 방법이
없을까?" Entry-quality checks on top of the chosen set-up (custom 80 / 9.0, the 1h V3.9 supertrend on the trade's side, the 0.25 ATR /
2 h pullback entered at market, TP net +10 %, stop net ROE -50 %, BTC 40x / others 30x, margin 40 %, NYSE-open and macro +-30 min,
weekend off), every one known when the signal bar closes:
  trend   BTC's own 1h supertrend, the 1h EMA200, the 1h 3-of-4 vote, the 4h vote not against, the supertrend's age, the 24 h move
  place   distance from the 1h EMA20, RSI not stretched, no chase, a modest signal bar, the signal bar's volume
  regime  the coin's 1h efficiency ratio (24 / 48 h), supertrend flips in 72 h, range-filter signals in 7 days, the 4h ADX, BTC's
          7-day efficiency, ATR % against the coin's own 30-day median
  entry   after the pullback touch, wait for a 5-minute bar closing back the trade's way (or past the previous 5-minute high / low)
Owners' second photo (10/26, the league account ds-F7_RF_TRIPLE-1h-1-ldt): "이사진 매매법 조건은 어땠어?" = the league's g1 gate (the last
closed BTC 4h bar's close above its EMA50 = up, below = down; a long needs up, a short down: candleague/rulex.gate_g1_arrays) with
the owners' ladder (net ROE 13 -> lock 10, 20 -> 15, 25 -> 20, 30 -> 25, then every 5 %), no take-profit, the stop 2 ATR from the
signal close, 30x, margin 30 %, every signal (no weekend / NYSE / macro block). Replayed as the league runs it (study.run_arm, its
sizing check), next to the same account without the gate and the first photo's account (TP +10 %), and the gate and the ladder
each put on the chosen set-up.
Chosen on the two live windows (owners' rule); each is also read on 2026-06 .. 09 (a fresh wallet each KST month), where every
variant lost: a check that really finds better places should help there too. Thresholds of the regime checks are medians of all
signals (no outcome used).
Run: python3 spots.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import final as FN  # noqa: E402
import pick as PK  # noqa: E402
import structure as SR  # noqa: E402
import study as ST  # noqa: E402
import timing as TM  # noqa: E402

MONTHS = ("2026-06", "2026-07", "2026-08", "2026-09")
OCT = (ST.ms("2026-09-30 15:00"), PK.END)


def eff(close: np.ndarray, n: int) -> np.ndarray:
    """Kaufman's efficiency ratio over n bars: the net move over the sum of the bar-to-bar moves (1 = straight, 0 = chop)."""
    d = np.abs(np.diff(close, prepend=close[0]))
    cs = np.cumsum(d)
    out = np.full(len(close), np.nan)
    out[n:] = np.abs(close[n:] - close[:-n]) / np.maximum(cs[n:] - cs[:-n], 1e-12)
    return out


def add_spots(W, cand: pd.DataFrame, work: str) -> pd.DataFrame:
    names = ("btc4", "btc_st1h", "st_age", "st_flips72", "rf7d", "er24", "er48", "btc_er168", "vol_x", "mv24", "atr_rel")
    cols = {k: np.full(len(cand), np.nan) for k in names}
    pb = W.p["BTCUSDT"]
    yb = np.load(os.path.join(work, "prep", "BTCUSDT_trend.npz"))
    btc_er = eff(pb["h1_c"], 168)
    c4 = pb["j4_close"].astype(float)                                       # candleague/rulex.gate_g1_arrays: EMA50 of the 4h closes
    sign4 = np.sign(c4 - pd.Series(c4).ewm(span=50, adjust=False).mean().to_numpy())
    sign4[:50] = 0
    k4 = np.searchsorted(pb["j4_ts"] + 4 * 3_600_000, cand.t.to_numpy(), side="right") - 1
    cols["btc4"] = np.where(k4 >= 0, sign4[np.clip(k4, 0, None)], 0)
    for c in ST.COINS:
        m = (cand.coin == c).to_numpy()
        i = cand.loc[m, "i1"].to_numpy()
        p = W.p[c]
        st = np.load(os.path.join(work, "prep", f"{c}_trend.npz"))["st1h"]
        close, atr, vol = p["h1_c"], p["s_atr"], p["h1_v"].astype(float)
        change = np.r_[True, st[1:] != st[:-1]]
        start = np.maximum.accumulate(np.where(change, np.arange(len(st)), 0))
        flips = np.cumsum(np.r_[0, (st[1:] != st[:-1]).astype(int)])
        sig = np.cumsum(p["sig_c"] != 0)
        cv = np.r_[0.0, np.cumsum(vol)]
        atrp = pd.Series(atr / close).rolling(720, min_periods=240).median().to_numpy()
        kb = np.searchsorted(pb["h1_ts"], p["h1_ts"][i], side="right") - 1
        cols["btc_st1h"][m] = yb["st1h"][kb]
        cols["st_age"][m] = i - start[i] + 1
        cols["st_flips72"][m] = flips[i] - flips[i - 72]
        cols["rf7d"][m] = sig[i] - sig[i - 168]
        cols["er24"][m] = eff(close, 24)[i]
        cols["er48"][m] = eff(close, 48)[i]
        cols["btc_er168"][m] = btc_er[kb]
        cols["vol_x"][m] = vol[i] / np.maximum((cv[i] - cv[i - 24]) / 24, 1e-12)        # the signal bar against the 24 before
        cols["mv24"][m] = (close[i] - close[i - 24]) / atr[i]
        cols["atr_rel"][m] = (atr[i] / close[i]) / atrp[i]
    return cand.assign(**cols)


def checks(cand: pd.DataFrame) -> dict:
    """name -> (group, mask function). The regime thresholds are medians of every signal (no outcome)."""
    q = {k: float(cand[k].median()) for k in ("rf7d", "er24", "er48", "btc_er168")}
    s = lambda g: g.side  # noqa: E731
    return {
        "기준(1시간 슈퍼트렌드만)": ("기준", lambda g: g.side == g.side),
        "BTC 4시간 종가 EMA50 위/아래 같은 방향(사진 필터)": ("추세", lambda g: g.btc4 == s(g)),
        "BTC 1시간 슈퍼트렌드도 같은 방향": ("추세", lambda g: g.btc_st1h == s(g)),
        "1시간 EMA200도 같은 쪽": ("추세", lambda g: g.ema200 == s(g)),
        "1시간 4개 중 3개도 같은 방향": ("추세", lambda g: g.j1_raw3 == s(g)),
        "4시간 4개 중 3개가 반대만 아니면": ("추세", lambda g: g.j4_raw3 != -s(g)),
        "슈퍼트렌드 이어진 지 6시간 이상": ("추세", lambda g: g.st_age >= 6),
        "슈퍼트렌드 이어진 지 24시간 이상": ("추세", lambda g: g.st_age >= 24),
        "슈퍼트렌드 바뀐 지 12시간 안": ("추세", lambda g: g.st_age <= 12),
        "24시간 움직임도 같은 방향": ("추세", lambda g: s(g) * g.mv24 > 0),
        "EMA20에서 1.5 ATR 안": ("자리", lambda g: s(g) * g.far_e <= 1.5),
        "EMA20에서 1 ATR 안": ("자리", lambda g: s(g) * g.far_e <= 1.0),
        "RSI 과열 아님(롱 70↓ · 숏 30↑)": ("자리", lambda g: np.where(g.side > 0, g.rsi <= 70, g.rsi >= 30)),
        "RSI 과열 아님(롱 65↓ · 숏 35↑)": ("자리", lambda g: np.where(g.side > 0, g.rsi <= 65, g.rsi >= 35)),
        "추격 아님(24시간 · 7일 끝자락 아님)": ("자리", lambda g: ~g.chase),
        "신호 봉이 크지 않음(1.5 ATR 이하)": ("자리", lambda g: g.range_atr <= 1.5),
        "신호 봉 거래량 24시간 평균 이상": ("자리", lambda g: g.vol_x >= 1.0),
        "신호 봉 거래량 평균 1.5배 이상": ("자리", lambda g: g.vol_x >= 1.5),
        "신호 봉 거래량 평균 1.5배 이하": ("자리", lambda g: g.vol_x <= 1.5),
        f"24시간 효율 {q['er24']:.2f} 이상(횡보 아님)": ("장세", lambda g: g.er24 >= q["er24"]),
        f"48시간 효율 {q['er48']:.2f} 이상": ("장세", lambda g: g.er48 >= q["er48"]),
        "슈퍼트렌드 72시간 안 뒤집힘 2번 이하": ("장세", lambda g: g.st_flips72 <= 2),
        f"레인지 신호 7일 안 {q['rf7d']:.0f}번 이하": ("장세", lambda g: g.rf7d <= q["rf7d"]),
        "4시간 ADX 20 이상": ("장세", lambda g: g.adx >= 20),
        "4시간 ADX 25 이상": ("장세", lambda g: g.adx >= 25),
        f"BTC 7일 효율 {q['btc_er168']:.2f} 이상": ("장세", lambda g: g.btc_er168 >= q["btc_er168"]),
        "변동성(ATR%) 평소 이상": ("장세", lambda g: g.atr_rel >= 1.0),
        "변동성(ATR%) 평소 이하": ("장세", lambda g: g.atr_rel <= 1.0),
    }


ENTRIES = {"되돌림 0.25 ATR · 2시간": ("pull", 0.25, 2),
           "되돌림 닿은 뒤 5분봉이 같은 방향으로 마감": ("pull", 0.25, 2, "turn"),
           "되돌림 닿은 뒤 5분봉이 직전 5분봉 고가(숏은 저가)를 넘음": ("pull", 0.25, 2, "pass")}
_entry = TM.entry_index


def entry_index(W, r, mode):
    """timing.entry_index plus the turn after the touch (mode[3]): the first 5-minute bar from the touch, inside the wait, that
    closes the trade's way ("turn") or past the previous bar's high / low ("pass"); the entry at the next 5-minute open."""
    if len(mode) < 4:
        return _entry(W, r, mode)
    j = _entry(W, r, mode[:3])
    if j is None:
        return None
    m = W.m5[r.coin]
    side, end = int(r.side), int(r.e5) + int(mode[2] * 12)
    for k in range(j - 1, min(end, len(m["o"]))):
        if mode[3] == "turn" and side * (m["c"][k] - m["o"][k]) > 0:
            return k + 1
        if mode[3] == "pass" and k > 0 and side * (m["c"][k] - (m["h"][k - 1] if side > 0 else m["l"][k - 1])) > 0:
            return k + 1
    return None


TM.entry_index = entry_index


def photo_lock(best: float):
    """The owners' ladder of the photo's account: net ROE 13 -> 10, 20 -> 15, 25 -> 20, 30 -> 25, then every 5 %."""
    if best < 0.13 - 1e-12:
        return None
    if best < 0.20 - 1e-12:
        return 0.10
    return 0.15 + 0.05 * int((best - 0.20) / 0.05 + 1e-9)


G1 = lambda g: g.btc4 == g.side  # noqa: E731
LEAGUE = dict(lev=ST.LEV30, margin=ST.M30, league_check=True, stop_atr=2.0)
PHOTOS = {"사진2 계좌 그대로(BTC 4시간 EMA50 필터 + 계단 13→10·20→15·25→20)": dict(LEAGUE, exit="lad", lad=photo_lock, filters=(G1,)),
          "사진2에서 필터만 뺌(계단 13→10…)": dict(LEAGUE, exit="lad", lad=photo_lock),
          "사진1 계좌(필터 없음 + 고정 +10%)": dict(LEAGUE, exit="tp10", tp_roe=0.10),
          "사진1 + BTC 4시간 EMA50 필터": dict(LEAGUE, exit="tp10", tp_roe=0.10, filters=(G1,))}


def read_league(W, cand, arm) -> dict:
    r = {wn: PK.read(ST.run_arm(W, cand, arm, wa, wb)) for wn, (wa, wb) in PK.LIVE.items()}
    for mo in MONTHS:
        r[mo] = PK.read(ST.run_arm(W, cand, arm, *FN.kst_month(mo)))
    r["2026-10"] = PK.read(ST.run_arm(W, cand, arm, *OCT))
    return r


def read(W, cand, mask, mode, weekend_off=True, exit_kind="tp10", lad=None) -> dict:
    kw = dict(trend=lambda g: (g.st1h == g.side) & np.asarray(mask(g), bool), mode=mode, tp_roe=0.10, stop=("roe", 0.50),
              weekend_off=weekend_off, exit_kind=exit_kind, lad=lad)
    r = {wn: TM.run(W, cand, a=wa, b=wb, **kw)[1] for wn, (wa, wb) in PK.LIVE.items()}
    r["live"] = min(r["rulebot"]["x"], r["league"]["x"])
    w = l_ = 0
    x = 1.0
    for mo in MONTHS:
        s = TM.run(W, cand, a=FN.kst_month(mo)[0], b=FN.kst_month(mo)[1], **kw)[1]
        r[mo] = s
        w, l_, x = w + s["w"], l_ + s["l"], x * s["x"]
    r["2026-10"] = TM.run(W, cand, a=OCT[0], b=OCT[1], **kw)[1]
    r["jun_sep"] = {"w": w, "l": l_, "win": w / max(w + l_, 1), "x_product": x}
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = add_spots(W, SR.add_trend(W, pd.read_pickle(os.path.join(a.work, "cand.pkl")), a.work), a.work)
    out = {"photo": {}, "photo_on_ours": [], "single": [], "entry": [], "pairs": [], "weekend_on": []}
    for name, arm in PHOTOS.items():
        out["photo"][name] = read_league(W, cand, arm)
        print("photo", name, json.dumps(out["photo"][name], ensure_ascii=False), flush=True)
    C = checks(cand)
    pull = ENTRIES["되돌림 0.25 ATR · 2시간"]
    for name, mask, ek, lad in (("우리 구조(고정 +10%)", lambda g: g.side == g.side, "tp10", None),
                                ("우리 구조 + BTC 4시간 EMA50 필터", G1, "tp10", None),
                                ("우리 구조, 익절만 사진2 계단 13→10…", lambda g: g.side == g.side, "lad", photo_lock),
                                ("우리 구조 + 필터 + 사진2 계단", G1, "lad", photo_lock)):
        r = {"name": name, **read(W, cand, mask, pull, exit_kind=ek, lad=lad)}
        out["photo_on_ours"].append(r)
        print("photo_on_ours", json.dumps(r, ensure_ascii=False), flush=True)
    for name, (grp, f) in C.items():
        r = {"check": name, "group": grp, **read(W, cand, f, pull)}
        out["single"].append(r)
        print("single", json.dumps(r, ensure_ascii=False), flush=True)
    for en, mo in ENTRIES.items():
        r = {"entry": en, **read(W, cand, C["기준(1시간 슈퍼트렌드만)"][1], mo)}
        out["entry"].append(r)
        print("entry", json.dumps(r, ensure_ascii=False), flush=True)
    # pairs among the singles that helped both the live windows and June .. September (no other selection)
    base = out["single"][0]
    good = [r["check"] for r in out["single"][1:]
            if r["live"] >= base["live"] and r["jun_sep"]["x_product"] > base["jun_sep"]["x_product"]]
    out["helped_both"] = good
    for i, x in enumerate(good):
        for y in good[i + 1:]:
            f = lambda g, x=x, y=y: np.asarray(C[x][1](g), bool) & np.asarray(C[y][1](g), bool)  # noqa: E731
            r = {"check": f"{x} + {y}", **read(W, cand, f, ENTRIES["되돌림 0.25 ATR · 2시간"])}
            out["pairs"].append(r)
            print("pair", json.dumps(r, ensure_ascii=False), flush=True)
    for name in ["기준(1시간 슈퍼트렌드만)"] + good:
        r = {"check": name, **read(W, cand, C[name][1], ENTRIES["되돌림 0.25 ATR · 2시간"], weekend_off=False)}
        out["weekend_on"].append(r)
        print("weekend_on", json.dumps(r, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(a.work, "spots.json"), "w"), indent=1, ensure_ascii=False, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
