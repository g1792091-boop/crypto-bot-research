#!/usr/bin/env python3
"""Build example AI-trader screens from real export data and measure their size (no API calls).

    python3 -P screens.py <export_dir> <repo_dir> <out_dir>

Screens follow AIBOT_DESIGN_KO_v2.md 6-3..6-6 (order fixed for caching: [common instructions] -> [market bundle +
analyst] -> [strategy card] -> [recent decisions] -> [this wake]) and PLAN_ATTACH_KO.md 1-2 (15m/30m/1h/4h bar
summaries, indicator values, chart context, S/R and volume-profile levels, funding / OI / long-short / liquidation
placeholders, upcoming releases, strategy card, own journal).

Real data used: 1m live_bars (v3b + v4) aggregated to 15m/30m/1h/4h bars for the 6 coins, signal_log + signal_ctx
(the wake's signals and their chart context), trades.csv (journal lines), research/strategy_profiles cards.json and
docs/aibot/STRATEGY_CATALOG_KO.md (card text), data/macro_events.csv (releases). Placeholders (marked in the
output JSON): funding / OI / long-short / liquidations, daily-bar block (the export has no daily history), analyst
labels, 5-year weakness numbers, latency curve, custom-value search counts.

Token estimates (no tokenizer offline): low = ASCII chars / 3.6 + other chars x 0.7; mid = ASCII / 3.2 + other x 0.95;
high = ASCII / 2.8 + other x 1.0 (the repo's own conservative estimator, paperbot/agents/debate_packet.py).
"""
from __future__ import annotations

import os
import re
import sys
import json
import numpy as np
import pandas as pd

COINS = ["BTC", "ETH", "SOL", "BCH", "LTC", "DOGE"]
TFS = [("15m", 15), ("30m", 30), ("1h", 60), ("4h", 240)]
KO_TF = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
HERE = os.path.dirname(os.path.abspath(__file__))


def est(text):
    a = sum(1 for ch in text if ord(ch) < 128)
    o = len(text) - a
    return {"chars": len(text), "ascii": a, "non_ascii": o,
            "tok_low": int(a / 3.6 + o * 0.7), "tok_mid": int(a / 3.2 + o * 0.95), "tok_high": int(a / 2.8 + o * 1.0)}


def load_bars(exp):
    frames = []
    for run in ["run-20261005T183457Z", "current"]:
        p = os.path.join(exp, run, "live_bars.csv")
        frames.append(pd.read_csv(p, usecols=["ts", "symbol", "open", "high", "low", "close", "volume"]))
    b = pd.concat(frames).drop_duplicates(["ts", "symbol"]).sort_values(["symbol", "ts"])
    return b


def agg(b1, minutes, t_end):
    d = b1[b1.ts < t_end].copy()
    d["k"] = d.ts // (minutes * 60000)
    g = d.groupby("k").agg(ts=("ts", "first"), o=("open", "first"), h=("high", "max"), l=("low", "min"),
                           c=("close", "last"), v=("volume", "sum"), n=("ts", "size"))
    g = g[g.n >= minutes * 0.8]  # closed, mostly complete bars
    return g.reset_index(drop=True)


def indicators(g):
    c, h, l, v = g.c.to_numpy(), g.h.to_numpy(), g.l.to_numpy(), g.v.to_numpy()
    n = len(c)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    ema20 = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()
    ema50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
    dlt = np.diff(c, prepend=c[0])
    up = pd.Series(np.clip(dlt, 0, None)).ewm(alpha=1 / 14, adjust=False).mean()
    dn = pd.Series(np.clip(-dlt, 0, None)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).to_numpy()
    upm = np.r_[0, h[1:] - h[:-1]]
    dnm = np.r_[0, l[:-1] - l[1:]]
    pdm = np.where((upm > dnm) & (upm > 0), upm, 0)
    mdm = np.where((dnm > upm) & (dnm > 0), dnm, 0)
    atr_s = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pd.Series(pdm).ewm(alpha=1 / 14, adjust=False).mean() / atr_s
    mdi = 100 * pd.Series(mdm).ewm(alpha=1 / 14, adjust=False).mean() / atr_s
    dx = 100 * abs(pdi - mdi) / (pdi + mdi).replace(0, np.nan)
    adx = dx.fillna(0).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    lb = min(20, n)
    hi, lo = h[-lb:].max(), l[-lb:].min()
    box = (c[-1] - lo) / (hi - lo) if hi > lo else 0.5
    # volume profile over the last 48 bars (24 bins): POC and 70 % value area
    m = min(48, n)
    hh, ll, cc, vv = h[-m:], l[-m:], c[-m:], v[-m:]
    edges = np.linspace(ll.min(), hh.max(), 25)
    mids = (hh + ll + cc) / 3
    hist, _ = np.histogram(mids, bins=edges, weights=vv)
    poc_i = int(hist.argmax())
    order = np.argsort(-hist)
    keep, tot = [], 0.0
    for i in order:
        keep.append(i)
        tot += hist[i]
        if tot >= 0.7 * hist.sum():
            break
    vah, val = edges[max(keep) + 1], edges[min(keep)]
    poc = (edges[poc_i] + edges[poc_i + 1]) / 2
    regime = "trend" if adx[-1] >= 25 else ("box" if abs(box - 0.5) < 0.35 else "chop")
    return {"atr": atr[-1], "atr_pct": 100 * atr[-1] / c[-1], "ema20_atr": (c[-1] - ema20[-1]) / atr[-1],
            "ema50_atr": (c[-1] - ema50[-1]) / atr[-1], "rsi": rsi[-1], "adx": adx[-1], "pdi": pdi.iloc[-1],
            "mdi": mdi.iloc[-1], "box": box, "vah": vah, "val": val, "poc": poc, "regime": regime,
            "chg": 100 * (c[-8:] / np.r_[c[-9:-1]] - 1) if n >= 9 else 100 * (c[1:] / c[:-1] - 1),
            "rng": ((h - l) / atr)[-8:], "vol": (v / pd.Series(v).rolling(20, min_periods=1).mean().to_numpy())[-8:],
            "close": c[-1], "nbars": n}


def fp(x, coin):
    if coin in ("DOGE",):
        return f"{x:.5f}"
    if coin in ("BTC",):
        return f"{x:,.1f}"
    if coin in ("ETH", "BCH", "SOL", "LTC"):
        return f"{x:,.2f}"
    return f"{x:.4f}"


def market_bundle(bars, t, lang, fmt="rows"):
    ko = lang == "ko"
    out = []
    when = pd.to_datetime(t, unit="ms")
    kst = when + pd.Timedelta(hours=9)
    if fmt == "json":
        data = {"market": {"utc": str(when)[:16], "kst": str(kst)[:16], "version": 412, "coins": {}}}
    else:
        out.append(f"[시장 묶음 · {str(when)[:16]} UTC / {str(kst)[:16]} KST · 판 #412]" if ko else
                   f"[market bundle · {str(when)[:16]} UTC / {str(kst)[:16]} KST · v412]")
    for coin in COINS:
        b1 = bars[bars.symbol == coin + "USDT"]
        last = b1[b1.ts < t].close.iloc[-1]
        cj = {"price": round(float(last), 6), "tf": {}}
        if fmt != "json":
            out.append(f"{coin} {fp(last, coin)}")
        for tf, mins in TFS:
            g = agg(b1, mins, t)
            ind = indicators(g)
            chg = " ".join(f"{x:+.2f}" for x in ind["chg"])
            rng = " ".join(f"{x:.1f}" for x in ind["rng"])
            vol = " ".join(f"{x:.1f}" for x in ind["vol"])
            if fmt == "json":
                cj["tf"][tf] = {"chg_pct_8": [round(float(x), 2) for x in ind["chg"]],
                                "range_atr_8": [round(float(x), 1) for x in ind["rng"]],
                                "vol_x_8": [round(float(x), 1) for x in ind["vol"]],
                                "atr_pct": round(ind["atr_pct"], 2), "ema20_atr": round(ind["ema20_atr"], 1),
                                "ema50_atr": round(ind["ema50_atr"], 1), "rsi": round(ind["rsi"]),
                                "adx": round(ind["adx"]), "di_plus": round(ind["pdi"]), "di_minus": round(ind["mdi"]),
                                "regime": ind["regime"], "box_pos": round(ind["box"], 2),
                                "vp": {"vah": float(fp(ind["vah"], coin).replace(",", "")),
                                       "val": float(fp(ind["val"], coin).replace(",", "")),
                                       "poc": float(fp(ind["poc"], coin).replace(",", ""))}}
            elif ko:
                rg = {"trend": "추세", "box": "박스", "chop": "횡보"}[ind["regime"]]
                out.append(f" {KO_TF[tf]}: 변화% {chg} | 폭/ATR {rng} | 거래량배 {vol}")
                out.append(f"  ATR {ind['atr_pct']:.2f}% · EMA20 {ind['ema20_atr']:+.1f}ATR · EMA50 {ind['ema50_atr']:+.1f}ATR"
                           f" · RSI {ind['rsi']:.0f} · ADX {ind['adx']:.0f} (+DI {ind['pdi']:.0f} / -DI {ind['mdi']:.0f})"
                           f" · 장 {rg} · 박스 위치 {ind['box']:.2f} · 매물대 위 {fp(ind['vah'], coin)} / 아래 {fp(ind['val'], coin)}"
                           f" / 최다 {fp(ind['poc'], coin)}")
            else:
                out.append(f" {tf}: chg% {chg} | rng/atr {rng} | volx {vol}")
                out.append(f"  atr {ind['atr_pct']:.2f}% · ema20 {ind['ema20_atr']:+.1f}atr · ema50 {ind['ema50_atr']:+.1f}atr"
                           f" · rsi {ind['rsi']:.0f} · adx {ind['adx']:.0f} (+di {ind['pdi']:.0f} / -di {ind['mdi']:.0f})"
                           f" · regime {ind['regime']} · box {ind['box']:.2f} · vp hi {fp(ind['vah'], coin)} / lo {fp(ind['val'], coin)}"
                           f" / poc {fp(ind['poc'], coin)}")
        # daily block and market data: placeholders with realistic digit counts
        dprev_h, dprev_l = last * 1.012, last * 0.981
        if fmt == "json":
            cj["daily"] = {"trend20_pct": 3.1, "vs_ema50_pct": 1.2, "vs_ema200_pct": 6.5, "atr_pct": 2.4,
                           "prev_hi": float(fp(dprev_h, coin).replace(",", "")), "prev_lo": float(fp(dprev_l, coin).replace(",", "")),
                           "week_open": float(fp(last * 0.996, coin).replace(",", "")), "lw_hi": float(fp(last * 1.03, coin).replace(",", "")),
                           "lw_lo": float(fp(last * 0.955, coin).replace(",", "")), "range_vs14": 0.7, "lvl_dist_atr": 0.9}
            cj["mkt"] = {"funding_pct": 0.0081, "next_funding_min": 130, "oi_24h_pct": 1.8, "ls_ratio": 1.12,
                         "liq_1h_long_musd": 1.2, "liq_1h_short_musd": 0.4, "note": "5y: no standalone edge"}
            cj["analyst"] = {"bias": "up_weak", "regime": "chop", "vol": "normal", "conf": 2, "valid_h": 2}
            data["market"]["coins"][coin] = cj
        elif ko:
            out.append(f" 일봉: 20일 흐름 +3.1% · 종가 vs EMA50 +1.2% / EMA200 +6.5% · 일ATR 2.4% · 전일 고 {fp(dprev_h, coin)}"
                       f" 저 {fp(dprev_l, coin)} · 주 시가 {fp(last * 0.996, coin)} · 지난주 고 {fp(last * 1.03, coin)} 저 {fp(last * 0.955, coin)}"
                       f" · 오늘 폭/14일 0.7 · 전일고까지 +0.9ATR")
            out.append(" 시장: 펀딩 +0.0081% (정산 2시간 10분 뒤) · 미결제 24h +1.8% · 롱숏 1.12 · 강제청산 1h 롱 $1.2M / 숏 $0.4M"
                       " ※5년 시험: 단독 예측력 없음")
            out.append(" 분석가: 기울기 약상승 · 장 횡보 · 변동성 보통 · 확신 2 · 유효 2시간")
        else:
            out.append(f" 1d: trend20 +3.1% · vs ema50 +1.2% / ema200 +6.5% · atr 2.4% · prev hi {fp(dprev_h, coin)}"
                       f" lo {fp(dprev_l, coin)} · week open {fp(last * 0.996, coin)} · last wk hi {fp(last * 1.03, coin)} lo {fp(last * 0.955, coin)}"
                       f" · today rng/14d 0.7 · to prev hi +0.9atr")
            out.append(" mkt: funding +0.0081% (next 2h10m) · OI 24h +1.8% · L/S 1.12 · liq 1h long $1.2M / short $0.4M"
                       " *5y test: no standalone edge")
            out.append(" analyst: bias up_weak · regime chop · vol normal · conf 2 · valid 2h")
    ev = pd.read_csv(os.path.join(REPO, "data", "macro_events.csv"), comment="#")
    ev["t"] = pd.to_datetime(ev.ts_utc).astype("int64") // 10**6
    nxt = ev[ev.t > t].head(2)
    if fmt == "json":
        data["market"]["analyst_text"] = ("BTC holds the 4h box middle; alts follow with lower volume. "
                                          "Volatility below the 14-day average. No coin shows a clear break.")
        data["market"]["events"] = [{"kind": r.kind, "in_h": round((r.t - t) / 3.6e6, 1)} for r in nxt.itertuples()]
        data["market"]["shock"] = False
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if ko:
        out.append("분석가 글: BTC는 4시간 박스 가운데에서 버팀. 알트는 거래량이 줄며 따라감.")
        out.append("변동성은 14일 평균보다 낮음. 뚜렷한 돌파를 보이는 코인은 없음. (판 작성 06:05 UTC, 그 뒤 BTC +0.1%, 0.2ATR)")
        out.append("다가오는 발표: " + " · ".join(f"{r.kind} {((r.t - t) / 3.6e6):.0f}시간 뒤" for r in nxt.itertuples())
                   + " · 충격 표시 없음")
    else:
        out.append("analyst text: BTC holds the 4h box middle. Alts follow on lower volume.")
        out.append("Volatility below the 14-day average. No coin shows a clear break. (version 06:05 UTC, since then BTC +0.1%, 0.2atr)")
        out.append("upcoming: " + " · ".join(f"{r.kind} in {((r.t - t) / 3.6e6):.0f}h" for r in nxt.itertuples())
                   + " · shock flag off")
    return "\n".join(out)


def catalog_section(sid):
    txt = open(os.path.join(REPO, "docs", "aibot", "STRATEGY_CATALOG_KO.md"), encoding="utf-8").read()
    m = re.search(r"^#{3,4} [AB]-\d+\. [^\n]*`" + re.escape(sid) + r"`\n(.*?)(?=^#{2,4} )", txt, re.S | re.M)
    return m.group(1).strip() if m else ""


EN_RULES = {
    "S2_ST_ROC": "long: supertrend (ATR10 x 6 band) up and ROC9 > 0, and this bar supertrend flipped up or ROC crossed above 0.\n"
                 "short (mirror): supertrend down, ROC < 0, this bar flip down or ROC crossed below 0.",
    "N24_DMI": "long: ADX14 >= 25 and +DI crossed above -DI this bar.\nshort: ADX14 <= 25 and -DI crossed above +DI this bar (as coded).",
    "F9_FVG": "long: bullish FVG (low > high 2 bars ago, gap >= 0.5 ATR) as zone; first touch within 50 bars closing >= gap middle.\n"
              "short: bearish FVG (high < low 2 bars ago); first touch closing <= middle.",
}
EN_PARAMS = {
    "S2_ST_ROC": "st_atr_len 10 (5 8 10 13 15) · st_mult 6 (3 4.5 6 7.5 9) · roc_len 9 (5 7 9 11 14)",
    "N24_DMI": "di_len 14 (7 11 14 18 21) · adx_len 14 (7 11 14 18 21) · adx_long_min 25 (12.5 18.75 25 31.25 37.5) · adx_short_max 25 (same)",
    "F9_FVG": "fvg_min 0.5 (0.25 0.375 0.5 0.625 0.75) · zone_valid 50 (25 38 50 63 75) · confirm_frac 0.5 (0.25 .. 0.75)",
}


def card(sid, lang, cards):
    ko = lang == "ko"
    rows = next((c["rows"] for c in cards if c["strategy"] == sid), None)
    o = []
    if ko:
        o.append(f"[매매법 카드 · {sid} · 맞춤 값 판본 w41 · 확인일까지 고정]")
        sec = catalog_section(sid)
        o.append(sec)
    else:
        o.append(f"[strategy card · {sid} · custom-value version w41 · fixed until review]")
        o.append("entry: " + EN_RULES[sid])
        o.append("params (default, candidates): " + EN_PARAMS[sid])
        if rows:
            o.append("5y (6 coins): tf | signals/day | mean ROE | win | median hold")
            for r in rows:
                if r["tf"] == "5m":
                    continue
                o.append(f" {r['tf']} | {r['signals_per_day']:.2f} | {100 * r['mean_roe']:+.1f}% | {100 * r['win_rate']:.0f}% | {r['median_hold_hours']:.1f}h")
    # 6-1 extras (placeholders: computed by the 5-year engine before launch)
    if ko:
        o += ["5년 R(20배 고정, ① 정의): 15분 -0.21R (n 94,460) · 30분 -0.17R (n 47,670) · 1시간 -0.12R (n 23,210) · 4시간 -0.05R (n 5,670)",
              "맞춤 값: 시도 45번 중 고른 값 st_mult 7.5 · 칸별 거절 비율 15분 62% / 30분 58% / 1시간 71% / 4시간 80%",
              "체결 지연별 R: 0분 -0.21 · 1분 -0.22 · 3분 -0.24 · 5분 -0.25 · 15분 -0.29 · 60분 -0.33",
              "이긴 거래 80%가 견딘 최대 불리 폭 0.62R · 보유 봉 수 중앙값 6",
              "5년 약점: 손실 원인 손절 71% / 시간 29% · 손절 털림(손절 뒤 1R 회복) 38% · 코인별 R BTC -0.15 ETH -0.19 SOL -0.24 BCH -0.27 LTC -0.22 DOGE -0.20",
              "해마다 R 2021 -0.18 · 2022 -0.20 · 2023 -0.24 · 2024 -0.19 · 2025 -0.23 · 2026 -0.22 · 이긴 거래 모양: 1봉 안 +0.5R 도달 64%",
              "표본 표시: 모두 30건 이상(믿을 만함)",
              "조건판(이번 신호): 조건1 맞음 · 조건2 맞음 · 조건3 맞음"]
    else:
        o += ["5y R (20x fixed, def 1): 15m -0.21R (n 94,460) · 30m -0.17R (n 47,670) · 1h -0.12R (n 23,210) · 4h -0.05R (n 5,670)",
              "custom values: chosen st_mult 7.5 of 45 tries · cell rejection 15m 62% / 30m 58% / 1h 71% / 4h 80%",
              "R by fill delay: 0m -0.21 · 1m -0.22 · 3m -0.24 · 5m -0.25 · 15m -0.29 · 60m -0.33",
              "80% of winners max adverse 0.62R · median hold 6 bars",
              "5y weak spots: losses stop 71% / time 29% · stop-then-recover-1R 38% · coin R BTC -0.15 ETH -0.19 SOL -0.24 BCH -0.27 LTC -0.22 DOGE -0.20",
              "R by year 2021 -0.18 · 2022 -0.20 · 2023 -0.24 · 2024 -0.19 · 2025 -0.23 · 2026 -0.22 · winner shape: +0.5R within 1 bar 64%",
              "sample flag: all >= 30 (reliable)",
              "condition board (this signal): cond1 met · cond2 met · cond3 met"]
    return "\n".join(o)


def journal(sid, trades, t, lang, n=10):
    ko = lang == "ko"
    d = trades[(trades.strategy_id == sid) & (trades.exit_time < t)].sort_values("exit_time").tail(n)
    o = ["[최근 판단 10개 · 5년 평균 -0.19R · 10개로는 운 범위 ±0.55R]" if ko else
         "[last 10 decisions · 5y mean -0.19R · luck range for 10: +-0.55R]"]
    basis_ko = ["추세", "조건", "매물대", "기타", "추세"]
    basis_en = ["trend", "conditions", "levels", "other", "trend"]
    for i, r in enumerate(d.itertuples()):
        tt = str(pd.to_datetime(r.entry_time, unit="ms") + pd.Timedelta(hours=9))[5:16]
        rdist = abs(r.entry_price - r.stop_initial) * r.qty
        R = r.pnl / rdist if rdist else 0
        side = ("롱" if r.side == 1 else "숏") if ko else ("long" if r.side == 1 else "short")
        if ko:
            o.append(f"{tt} {r.symbol[:-4]} {r.timeframe} {side} 진입 확신{2 + i % 3} 근거 {basis_ko[i % 5]} → {r.exit_reason} {R:+.2f}R")
        else:
            o.append(f"{tt} {r.symbol[:-4]} {r.timeframe} {side} enter conf{2 + i % 3} basis {basis_en[i % 5]} -> {r.exit_reason} {R:+.2f}R")
    return "\n".join(o)


def wake_signal(sigs, ctxs, lang):
    ko = lang == "ko"
    o = []
    when = pd.to_datetime(int(sigs.bar_close.iloc[0]), unit="ms")
    o.append(f"[이번 깨움: 신호 {len(sigs)}개 · 봉 마감 {str(when)[11:16]} UTC · 답 마감 3분 · 포지션 없음]" if ko else
             f"[this wake: {len(sigs)} signal(s) · bar close {str(when)[11:16]} UTC · answer deadline 3m · flat]")
    for r in sigs.itertuples():
        cx = ctxs.get(int(r.id), {})
        sr = cx.get("sr", {})
        stopf = 2 * r.atr / r.ref_price
        cost = 0.0012 / stopf
        coin = r.symbol[:-4]
        if ko:
            side = "롱" if r.side == 1 else "숏"
            o.append(f"- {coin} {KO_TF[r.timeframe]} {side} · 기준가 {fp(r.ref_price, coin)} · 손절 거리 {100 * stopf:.2f}% (2ATR) · [비용] 1R의 {100 * cost:.0f}%")
            o.append(f"  장 {cx.get('regime')} / 상위봉 {cx.get('htf_regime')} · 박스 위치 {cx.get('box_pos', 0):.2f} · ADX {cx.get('adx', 0):.0f}"
                     f" (+DI {cx.get('di_plus', 0):.0f} / -DI {cx.get('di_minus', 0):.0f}) · EMA20 {cx.get('ema20_dist_atr', 0):+.2f}ATR · 추세 나이 {cx.get('trend_age')}봉")
            o.append(f"  목표 쪽 가장 가까운 레벨: {sr.get('room_ko')} {fp(sr.get('room_px', 0), coin)} ({sr.get('room', 0):.2f}R) · "
                     f"손절 쪽: {sr.get('floor_ko')} {fp(sr.get('floor_px', 0), coin)} ({sr.get('floor', 0):.2f}R) · 돌파 {sr.get('breakout')}")
        else:
            side = "long" if r.side == 1 else "short"
            o.append(f"- {coin} {r.timeframe} {side} · ref {fp(r.ref_price, coin)} · stop dist {100 * stopf:.2f}% (2atr) · [cost] {100 * cost:.0f}% of 1R")
            o.append(f"  regime {cx.get('regime')} / htf {cx.get('htf_regime')} · box {cx.get('box_pos', 0):.2f} · adx {cx.get('adx', 0):.0f}"
                     f" (+di {cx.get('di_plus', 0):.0f} / -di {cx.get('di_minus', 0):.0f}) · ema20 {cx.get('ema20_dist_atr', 0):+.2f}atr · trend age {cx.get('trend_age')} bars")
            o.append(f"  nearest level target side: {sr.get('room_kind')} {fp(sr.get('room_px', 0), coin)} ({sr.get('room', 0):.2f}R) · "
                     f"stop side: {sr.get('floor_kind')} {fp(sr.get('floor_px', 0), coin)} ({sr.get('floor', 0):.2f}R) · breakout {sr.get('breakout')}")
    o.append("답: 진입 판단 형식" if ko else "answer: entry schema")
    return "\n".join(o)


def wake_hold(tr, t, price, lang):
    ko = lang == "ko"
    coin = tr.symbol[:-4]
    rd = abs(tr.entry_price - tr.stop_initial)
    Rnow = tr.side * (price - tr.entry_price) / rd
    bars = int((t - tr.entry_time) / (60000 * {"15m": 15, "30m": 30, "1h": 60, "4h": 240}[tr.timeframe]))
    if ko:
        side = "롱" if tr.side == 1 else "숏"
        return "\n".join([
            "[이번 깨움: 보유 중 · 이유 가격이 마지막 확인 뒤 0.5R 움직임 · 답 마감 60초]",
            f"포지션: {coin} {KO_TF[tr.timeframe]} {side} · 진입 {fp(tr.entry_price, coin)} · 지금 {fp(price, coin)} ({Rnow:+.2f}R) · 보유 {bars}봉",
            f"손절 {fp(tr.stop_initial, coin)} (지금가에서 {100 * abs(price - tr.stop_initial) / price:.2f}%) · 잠근 수익 없음 · 시간 청산 없음",
            f"진입 때 무효 조건: '4시간 박스 아래 끝 종가 이탈' · 진입 확신 3 · 근거 추세",
            "답: 보유 판단 형식"])
    side = "long" if tr.side == 1 else "short"
    return "\n".join([
        "[this wake: holding · reason price moved 0.5R since last check · deadline 60s]",
        f"position: {coin} {tr.timeframe} {side} · entry {fp(tr.entry_price, coin)} · now {fp(price, coin)} ({Rnow:+.2f}R) · held {bars} bars",
        f"stop {fp(tr.stop_initial, coin)} ({100 * abs(price - tr.stop_initial) / price:.2f}% away) · no locked profit · no time stop",
        "invalidation at entry: '4h box low closed below' · entry conf 3 · basis trend",
        "answer: holding schema"])


def main():
    global REPO
    exp, REPO, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    bars = load_bars(exp)
    bars["symbol"] = bars.symbol.astype(str)
    sl = pd.read_csv(os.path.join(exp, "current", "signal_log.csv"))
    sl = sl[sl.status == "SUBMITTED"]
    ctxs = {}
    with open(os.path.join(exp, "current", "signal_ctx.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            j = json.loads(line)
            ctxs[int(j["id"])] = j.get("ctx", {})
    trades = pd.read_csv(os.path.join(exp, "current", "trades.csv"))
    cards = json.load(open(os.path.join(REPO, "research", "strategy_profiles", "out", "cards.json")))["cards"]
    instr = {l: open(os.path.join(HERE, "screen_parts", f"instr_{l}.txt"), encoding="utf-8").read() for l in ("ko", "en")}

    t_late = int(sl.bar_close.max())
    # screen 1: S2_ST_ROC 15m single-signal entry wake (latest)
    s1 = sl[(sl.strategy == "S2_ST_ROC") & (sl.timeframe == "15m")]
    s1 = s1[s1.bar_close == s1.bar_close.iloc[-1]]
    # screen 2: a DeepSeek strategy with a multi-coin bundle at one bar close (latest such bundle)
    cnt = sl[sl.strategy.str.startswith("F")].groupby(["strategy", "bar_close"]).size()
    cnt = cnt[cnt >= 3]
    key2 = cnt.reset_index().sort_values("bar_close").iloc[-1]
    s2 = sl[(sl.strategy == key2.strategy) & (sl.bar_close == key2.bar_close)]
    # screen 3: holding check of an N24_DMI trade (latest closed trade, check at mid-hold)
    tr = trades[(trades.strategy_id == "N24_DMI")].sort_values("entry_time").iloc[-1]
    t3 = int(tr.entry_time + (tr.exit_time - tr.entry_time) / 2)
    b3 = bars[(bars.symbol == tr.symbol) & (bars.ts < t3)]
    price3 = float(b3.close.iloc[-1])

    specs = [("S1_entry_S2_ST_ROC_15m", "S2_ST_ROC", int(s1.bar_close.iloc[0]), ("sig", s1)),
             ("S2_entry_bundle_" + key2.strategy, key2.strategy, int(key2.bar_close), ("sig", s2)),
             ("S3_hold_N24_DMI", "N24_DMI", t3, ("hold", tr))]
    result = {"screens": {}, "notes": {}}
    for name, sid, t, (kind, payload) in specs:
        card_sid = sid if sid in EN_RULES else "F9_FVG"  # EN card text only written for 3 strategies
        for lang in ("ko", "en"):
            parts = {
                "instructions": instr[lang],
                "market": market_bundle(bars, t, lang),
                "card": card(card_sid if lang == "en" else sid, lang, cards),
                "journal": journal(sid, trades, t, lang),
                "wake": wake_signal(payload, ctxs, lang) if kind == "sig" else wake_hold(payload, t, price3, lang),
            }
            if lang == "en":
                parts["market_json"] = market_bundle(bars, t, lang, fmt="json")
            full = "\n\n".join(parts[k] for k in ["instructions", "market", "card", "journal", "wake"])
            with open(os.path.join(out, f"{name}_{lang}.txt"), "w", encoding="utf-8") as fh:
                fh.write(full)
            if lang == "en":
                with open(os.path.join(out, f"{name}_market_en.json"), "w", encoding="utf-8") as fh:
                    fh.write(parts["market_json"])
            result["screens"][f"{name}|{lang}"] = {k: est(v) for k, v in parts.items()} | {"total": est(full)}
        result["notes"][name] = {"strategy": sid, "time_utc": str(pd.to_datetime(t, unit="ms")),
                                 "signals_in_wake": int(len(payload)) if kind == "sig" else 0}
    # output samples (structured answers) -------------------------------------------------------
    ans = {
        "entry_ko": json.dumps({"action": "진입", "coin": "BTC", "side": "long", "confidence": 3, "p_1r_first": 46,
                                "basis": "추세", "invalidation": "15분 종가가 슈퍼트렌드 아래로 마감",
                                "exp_hold_bars": 6, "reason": "4시간 박스 중간, 매물대 위 끝까지 1.2R 여유. 비용 22%라 확신은 3에 둠."},
                               ensure_ascii=False),
        "skip_ko": json.dumps({"action": "거르기", "coin": "SOL", "side": "short", "confidence": 1, "p_1r_first": 35,
                               "basis": "매물대", "invalidation": "-", "exp_hold_bars": 0,
                               "reason": "손절 쪽 0.27R에 스윙 저점, 목표 쪽 0.16R에 상위 봉 고점. 비용 25%."}, ensure_ascii=False),
        "hold_ko": json.dumps({"action": "유지", "basis": "기타", "reason": "무효 조건 아직 아님. 0.5R 움직임은 15분 ATR 1개 안."},
                              ensure_ascii=False),
    }
    result["answers"] = {k: est(v) | {"text": v} for k, v in ans.items()}
    with open(os.path.join(out, "screens_measure.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    for k, v in result["screens"].items():
        print(k, {p: (m["chars"], m["tok_low"], m["tok_mid"], m["tok_high"]) for p, m in v.items()})
    for k, v in result["answers"].items():
        print(k, v["chars"], v["tok_low"], v["tok_mid"], v["tok_high"])
    print(result["notes"])


if __name__ == "__main__":
    main()
