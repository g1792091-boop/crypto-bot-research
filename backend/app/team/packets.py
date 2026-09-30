"""에이전트 팀이 읽는 데이터 패킷 — 모든 숫자는 코드가 계산한다 (에이전트는 해석만).

- market: 코인별 가격·변동·ATR·여러 봉 시장 판단·지지저항·종합 진입 판단
- flow: 펀딩·OI·롱숏·호가 불균형·호가벽·고수 포지션·바이낸스 상위 트레이더 비율
- macro: 도미넌스·공포탐욕·BTC 상관·베타·7일 상대강도 순위
- news: 헤드라인 · 48시간 안 경제지표
- analog: 과거 유사 패턴 이후 분포 (4시간봉)
- book: 내 모의 계좌 (포지션·오늘/7일/누적 성적·최근 거래 원인 태그·요일/시간대·가정 실험실)
- bots: 페이퍼 봇 성적 · synergy: 봇끼리 상관 · ops: 운영 상태
"""
from __future__ import annotations

import math
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .. import analysis, config, orderflow
from .. import indicators as ind
from ..data import market
from ..quant import entry as entry_mod
from ..quant import forecast, toptraders

KST = timezone(timedelta(hours=9))
MIN_N = 30


def _r(x, n=6):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return float(f"{x:.{n}g}")


def kst(ts: float) -> str:
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- 시장
def _coin(sym: str) -> dict:
    out: dict = {}
    try:
        an = analysis.analyze(sym, "1h")
        reg = an["regime"]
        c, _ = market.candles(sym, "1h", 60)
        hi24, lo24 = max(b["high"] for b in c[-24:]), min(b["low"] for b in c[-24:])
        out.update({"price": _r(reg["price"]), "change_24h_pct": _r((c[-1]["close"] / c[-25]["close"] - 1) * 100, 3),
                    "range_24h_pct": _r((hi24 / lo24 - 1) * 100, 3), "atr_1h_pct": _r(reg["atr"] / reg["price"] * 100, 3),
                    "rsi_1h": _r(reg["rsi"], 3), "adx_1h": _r(reg["adx"], 3),
                    "regime": {m["interval"]: {"label": m["label"], "score": m["score"]} for m in an["mtf"]},
                    "regime_reasons_1h": reg["reasons"][:3],
                    "support": [{"price": _r(x["price"]), "kind": x["kind"]} for x in an["support"][:3]],
                    "resistance": [{"price": _r(x["price"]), "kind": x["kind"]} for x in an["resistance"][:3]]})
    except Exception as e:
        out["error"] = str(e)[:120]
    try:
        e = entry_mod.entry(sym, "1h")
        out["verdict"] = {"label": e["label"], "score": e["score"], "agree": f"{e['agree']}/{e['total']}"}
    except Exception:
        pass
    return out


def market_section(coins: list[str]) -> dict:
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(zip(coins, ex.map(_coin, coins)))


def flow_section(coins: list[str]) -> dict:
    from ..quant.copilot import _deriv

    def one(sym):
        d = {k: v for k, v in _deriv(sym).items() if k not in ("symbol", "source")}
        try:
            ob = orderflow.orderbook(sym)
            px = ob["mid"]
            d["ob_imbalance_0_5pct"] = _r(ob["depth"][1]["imbalance"], 3)
            d["walls"] = [{"price": _r(w["price"]), "side": "bid" if w["side"] == "bid" else "ask", "usd_m": _r(w["usd"] / 1e6, 3)}
                          for w in ob["walls"] if abs(w["price"] / px - 1) < 0.03][:4]
        except Exception:
            pass
        try:
            br = toptraders.binance_ratios(sym, "1h")
            d["binance_top_long_pct"] = {"position": _r(br["position"][-1]["long"] * 100, 3), "account": _r(br["account"][-1]["long"] * 100, 3)}
        except Exception:
            pass
        tt = toptraders.last_result
        row = next((x for x in (tt or {}).get("by_coin", []) if x["symbol"] == sym), None) if tt and time.time() - tt["time"] < 6 * 3600 else None
        if row:
            d["hyperliquid_top"] = {"long_traders": row["long"]["traders"], "short_traders": row["short"]["traders"], "long_share_pct": row["long_share"],
                                    "avg_lev_long": row["long"]["avg_leverage"], "avg_lev_short": row["short"]["avg_leverage"]}
        return d
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(zip(coins, ex.map(one, coins)))


def macro_section(coins: list[str]) -> dict:
    out: dict = {}
    try:
        dom = market.global_dominance()
        out["dominance"] = {k: _r(v, 4) for k, v in dom.items() if isinstance(v, (int, float))}
    except Exception:
        pass
    try:
        from ..data import sentiment
        fg = sentiment.fear_greed(2)
        cur = (fg.get("items") or fg.get("series") or [{}])[-1] if isinstance(fg, dict) else {}
        out["fear_greed"] = {"value": cur.get("value"), "label": cur.get("label") or cur.get("classification")}
    except Exception:
        pass
    try:
        btc = [b["close"] for b in market.candles("BTCUSDT", "1d", 61)[0]]
        rb = [btc[i] / btc[i - 1] - 1 for i in range(1, len(btc))]
        corr, beta, rs = {}, {}, {}
        for s in coins:
            cl = [b["close"] for b in market.candles(s, "1d", 61)[0]]
            r = [cl[i] / cl[i - 1] - 1 for i in range(1, len(cl))]
            n = min(len(r), len(rb))
            a, b = r[-n:], rb[-n:]
            ma, mb = sum(a) / n, sum(b) / n
            cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / n
            va, vb = sum((x - ma) ** 2 for x in a) / n, sum((y - mb) ** 2 for y in b) / n
            if s != "BTCUSDT":
                corr[s] = _r(cov / math.sqrt(va * vb), 3) if va and vb else None
                beta[s] = _r(cov / vb, 3) if vb else None
            rs[s] = _r((cl[-1] / cl[-8] - 1) * 100, 3)
        out.update({"corr_btc_60d": corr, "beta_btc_60d": beta, "return_7d_pct": rs,
                    "rank_7d": [s for s, _ in sorted(rs.items(), key=lambda kv: -(kv[1] or -1e9))]})
    except Exception:
        pass
    return out


def news_section() -> dict:
    out: dict = {"headlines": [], "events": []}
    try:
        from ..data import news
        out["headlines"] = [f"[{h['source']}] {h['title']}" for h in news.headlines(15)["items"]]
        if config.DATA_SOURCE != "synthetic":
            now = time.time()
            for e in news.economic_calendar()["items"]:
                try:
                    t = datetime.fromisoformat(e["date"]).timestamp()
                except (TypeError, ValueError):
                    continue
                if -3600 <= t - now <= 48 * 3600:
                    out["events"].append({"title": e["title"], "in_hours": _r((t - now) / 3600, 3), "forecast": e.get("forecast"), "previous": e.get("previous")})
    except Exception:
        pass
    return out


def analog_section(coins: list[str]) -> dict:
    def one(sym):
        try:
            a = forecast.forecast(sym, "4h").get("analog") or {}
            return {"prob_up": a.get("prob_up"), "median_ret_pct": a.get("median_ret_pct"), "p10_ret_pct": a.get("p10_ret_pct"),
                    "p90_ret_pct": a.get("p90_ret_pct"), "reliability": a.get("reliability"), "horizon_bars": a.get("horizon"), "interval": "4h"}
        except Exception as e:
            return {"error": str(e)[:80]}
    with ThreadPoolExecutor(max_workers=4) as ex:
        return dict(zip(coins, ex.map(one, coins)))


# ---------------------------------------------------------------- 거래 · 성적
def _stats(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0}
    wins = [t for t in trades if t["pnl"] > 0]
    gw, gl = sum(t["pnl"] for t in wins), -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    streak = best = 0
    for t in trades:
        streak = streak + 1 if t["pnl"] <= 0 else 0
        best = max(best, streak)
    fees = sum(t.get("fees", 0) for t in trades)
    return {"trades": n, "net_pnl": _r(sum(t["pnl"] for t in trades), 6), "win_rate_pct": _r(len(wins) / n * 100, 3),
            "profit_factor": _r(gw / gl, 3) if gl > 0 else None, "avg_roe_pct": _r(sum(t.get("pnl_pct_on_margin", 0) for t in trades) / n, 4),
            "max_losing_streak": best, "fees": _r(fees, 5), "fee_share_of_gross_win_pct": _r(fees / gw * 100, 3) if gw > 0 else None,
            "liquidations": sum(1 for t in trades if t.get("exit_reason") == "liquidation"),
            "status": "ok" if n >= MIN_N else "insufficient"}


SESS = [("dawn", 4, 9), ("asia", 9, 16), ("europe", 16, 22), ("us", 22, 28)]   # 한국 시간 (미국 = 22~다음날 04)


def _session(ts: int) -> str:
    d = datetime.fromtimestamp(ts, KST)
    h = d.hour + (24 if d.hour < 4 else 0)
    name = next(n for n, a, b in SESS if a <= h < b)
    return ("weekend" if d.weekday() >= 5 else "weekday") + "_" + name


def _sessions(trades: list[dict]) -> dict:
    out = {}
    for t in trades:
        k = _session(t["entry_time"])
        out.setdefault(k, []).append(t)
    return {k: {"n": len(v), "net_pnl": _r(sum(t["pnl"] for t in v), 5), "win_rate_pct": _r(sum(t["pnl"] > 0 for t in v) / len(v) * 100, 3),
                "status": "ok" if len(v) >= 10 else "insufficient"} for k, v in sorted(out.items())}


def _tags(t: dict, c1h: list[dict], c4h: list[dict]) -> dict:
    """진입 태그(진입 순간 정보만)와 결과 태그."""
    side = 1 if t["side"] == "long" else -1
    pre, post = [], []
    i = max((k for k, b in enumerate(c1h) if b["time"] <= t["entry_time"]), default=None)
    if i is not None and i >= 60:
        w = c1h[:i + 1]
        cl = [b["close"] for b in w]
        e20, a = ind.ema(cl, 20)[-1], ind.atr(w, 14)[-1]
        if e20 and a and (cl[-1] - e20) * side / a >= 2.5:
            pre.append("E1 추세 막판 진입 (EMA20 에서 2.5 ATR 이상)")
        reg = analysis.regime(w[-300:])
        if reg["state"] == "range":
            hi, lo = max(b["high"] for b in w[-50:]), min(b["low"] for b in w[-50:])
            pos = (cl[-1] - lo) / (hi - lo) if hi > lo else 0.5
            if 0.3 <= pos <= 0.7:
                pre.append("B1 박스 한가운데 진입")
            elif (side == 1 and pos > 0.8) or (side == -1 and pos < 0.2):
                pre.append("B2 박스 천장 롱 / 바닥 숏")
    j = max((k for k, b in enumerate(c4h) if b["time"] <= t["entry_time"]), default=None)
    if j is not None and j >= 55:
        e50 = ind.ema([b["close"] for b in c4h[:j + 1]], 50)
        if e50[-1] and e50[-6] and (e50[-1] - e50[-6]) * side < 0:
            pre.append("H0 4시간봉 추세 반대 진입")
    after = [b for b in c1h if t["exit_time"] < b["time"] <= t["exit_time"] + 24 * 3600]
    move = abs(t["exit_price"] - t["entry_price"])
    if t.get("exit_reason") == "liquidation":
        post.append("LIQ 강제청산")
    elif t["pnl"] <= 0 and t.get("exit_reason") == "stop_loss" and after and move and \
            any((b["high"] - t["entry_price"]) * side >= move if side == 1 else (t["entry_price"] - b["low"]) >= move for b in after):
        post.append("T1 손절 뒤 반대로 1R 이상 감 (손절이 좁았을 수)")
    elif t["pnl"] > 0 and t.get("exit_reason") == "take_profit" and after and move and \
            any(((b["high"] - t["exit_price"]) if side == 1 else (t["exit_price"] - b["low"])) >= move for b in after):
        post.append("W1 익절 뒤 1R 더 감 (이른 익절)")
    gross = (t["exit_price"] - t["entry_price"]) * side * t["qty"]
    if gross > 0 and t.get("fees", 0) >= gross:
        post.append("W5 수수료가 이익을 먹음")
    if not post:
        post.append("W3 특이사항 없는 이익" if t["pnl"] > 0 else "N0 특이사항 없는 손실 (정상 손실)")
    return {"pre": pre, "post": post}


# ---------------------------------------------------------------- 가정 실험실
POLICIES = ["C0", "SL_ROE10", "SL_ROE20", "SL_ROE30", "SL_ROE50", "TP_ROE10", "TP_ROE20", "TP_ROE30", "TP_ROE50", "BE_ROE10", "TIME_240m"]


def _whatif_trade(t: dict, bars: list[dict]) -> dict:
    """같은 진입에 청산 규칙만 바꿨을 때 증거금 대비 수익률(ROE %). 규칙에 안 걸리면 실제 청산가로 끝난 것으로 본다."""
    side, e, L = (1 if t["side"] == "long" else -1), t["entry_price"], max(1.0, t["leverage"])
    roe = lambda px: (px / e - 1) * side * L * 100
    actual = roe(t["exit_price"])
    liq_roe = -100 + 0.4 * L                      # 유지증거금 근사
    out = {"C0": actual}
    path = [b for b in bars if t["entry_time"] <= b["time"] < t["exit_time"]]
    cap = {}
    for p in POLICIES[1:]:
        res, over = actual, False
        if p.startswith("SL_") or p.startswith("TP_") or p.startswith("BE_"):
            lvl = int(p.split("ROE")[1])
            if p.startswith("SL_") and -lvl <= liq_roe:
                over = True
            armed = False
            for b in path:
                hi, lo = roe(b["high"] if side == 1 else b["low"]), roe(b["low"] if side == 1 else b["high"])
                if p.startswith("SL_") and lo <= -lvl:
                    res = -lvl
                    break
                if p.startswith("TP_") and hi >= lvl:
                    res = lvl
                    break
                if p.startswith("BE_"):
                    if armed and lo <= 0:
                        res = 0.0
                        break
                    if hi >= lvl:
                        armed = True
        elif p == "TIME_240m":
            late = [b for b in path if b["time"] >= t["entry_time"] + 240 * 60]
            if late:
                res = roe(late[0]["open"])
        out[p] = res
        cap[p] = over
    return {"roe": out, "over_cap": cap}


def whatif_lab(trades: list[dict]) -> dict:
    rows, n_sim = [], 0
    for t in trades[-60:]:
        if not t.get("exit_time") or t["exit_time"] - t["entry_time"] > 14 * 86400:
            continue
        try:
            span = t["exit_time"] - t["entry_time"]
            iv = "1m" if span <= 20 * 3600 else "5m" if span <= 4 * 86400 else "15m"
            bars, _ = market.candles_range(t["symbol"], iv, t["entry_time"] - 60, t["exit_time"] + 60)
        except Exception:
            continue
        if not bars:
            continue
        r = _whatif_trade(t, bars)
        # 재현 검사: 규칙을 안 바꾼 C0 가 장부의 증거금 대비 수익률(수수료만큼 차이 허용)과 맞는지
        fee_allow = 0.25 * max(1.0, t["leverage"]) + 1.5
        r["repro"] = t.get("exit_reason") == "liquidation" or abs(r["roe"]["C0"] - (t.get("pnl_pct_on_margin") or 0)) <= fee_allow
        rows.append(r)
        n_sim += 1
    repro = [r["repro"] for r in rows]
    n = len(rows)
    pol = {}
    alpha = 0.05 / max(1, len(POLICIES) - 1)          # 여러 규칙을 동시에 비교 → 본페로니 보정
    rng = random.Random(7)
    for p in POLICIES:
        d = [r["roe"][p] - r["roe"]["C0"] for r in rows]
        tot = sum(r["roe"][p] for r in rows)
        item = {"n": n, "mean_roe_pct": _r(tot / n, 4) if n else None, "over_cap": sum(r["over_cap"].get(p, False) for r in rows)}
        if p != "C0" and n:
            m = sum(d) / n
            boots = sorted(sum(rng.choice(d) for _ in range(n)) / n for _ in range(600))
            lo, hi = boots[int(alpha / 2 * 600)], boots[min(599, int((1 - alpha / 2) * 600))]
            verdict = "insufficient" if n < MIN_N else "better" if lo > 0 else "worse" if hi < 0 else "no_difference"
            item.update({"delta_mean_roe_pct": _r(m, 4), "delta_ci": [_r(lo, 4), _r(hi, 4)], "verdict": verdict})
        pol[p] = item
    return {"n": n, "policies": pol, "reproduction_ok": all(repro) if repro else None, "comparisons": len(POLICIES) - 1,
            "method": "같은 진입에 청산 규칙만 바꿈 (ROE = 증거금 대비 %, 수수료·펀딩 제외, 규칙에 안 걸리면 실제 청산가). 신뢰구간은 본페로니 보정",
            "note": "C0=실제, SL=손절 ROE -N%, TP=익절 ROE N%, BE_ROE10=ROE +10% 뒤 본전 손절, TIME_240m=4시간 뒤 청산"}


def book_section(paper, whatif: bool = True) -> dict:
    acct = paper.manual
    snap = acct.snapshot()
    now = time.time()
    trades = [dict(t.__dict__) if hasattr(t, "__dict__") else dict(t) for t in acct.trades]
    for t in trades:
        t["who"] = "내 계좌"
    for b in paper.bots.values():
        for t in b.sim.trades:
            d = dict(t.__dict__)
            d["symbol"] = d.get("symbol") or b.spec.symbol
            d["who"] = f"봇 {b.spec.name}"
            trades.append(d)
    trades.sort(key=lambda t: t["exit_time"])
    day0 = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    today = [t for t in trades if t["exit_time"] >= day0]
    week = [t for t in trades if t["exit_time"] >= now - 7 * 86400]
    recent = trades[-12:]
    cache: dict = {}

    def cs(sym, iv):
        if (sym, iv) not in cache:
            try:
                cache[(sym, iv)] = market.candles(sym, iv, 1000)[0]
            except Exception:
                cache[(sym, iv)] = []
        return cache[(sym, iv)]
    rows = []
    for t in recent:
        tg = _tags(t, cs(t["symbol"], "1h"), cs(t["symbol"], "4h"))
        rows.append({"who": t["who"], "symbol": t["symbol"], "side": t["side"], "leverage": t["leverage"], "entry": _r(t["entry_price"]),
                     "exit": _r(t["exit_price"]), "pnl": _r(t["pnl"], 5), "roe_pct": _r(t.get("pnl_pct_on_margin"), 4),
                     "exit_reason": t.get("exit_reason"), "held_min": round((t["exit_time"] - t["entry_time"]) / 60),
                     "exit_kst": kst(t["exit_time"]), "pre": tg["pre"], "cause": tg["post"][0]})
    causes: dict = {}
    for r in rows:
        causes[r["cause"].split(" ")[0]] = causes.get(r["cause"].split(" ")[0], 0) + 1
    eq0 = acct.initial_equity
    peak = cur = eq0
    mdd = 0.0
    for t in [t for t in trades if t["who"] == "내 계좌"]:
        cur += t["pnl"]
        peak = max(peak, cur)
        mdd = max(mdd, (peak - cur) / peak * 100 if peak > 0 else 0)
    out = {"equity": _r(snap["equity"], 7), "initial_equity": eq0, "return_pct": _r((snap["equity"] / eq0 - 1) * 100, 4),
           "max_drawdown_pct": _r(mdd, 4), "free_margin": _r(snap["free_margin"], 7),
           "positions": [{"symbol": p["symbol"], "side": p["side"], "leverage": p["leverage"], "entry": _r(p["entry_price"]), "mark": _r(p["mark_price"]),
                          "roe_pct": _r(p["roe_pct"], 4), "stop": _r(p["stop"]), "take": _r(p["take"]), "liq": _r(p["liq_price"])} for p in snap["positions"]],
           "today": _stats(today), "week": _stats(week), "cumulative": _stats(trades), "trades_recent": rows, "causes": causes,
           "sessions": _sessions(trades), "last_trade_exit_kst": kst(trades[-1]["exit_time"]) if trades else None}
    if whatif:
        out["whatif"] = whatif_lab(trades)
    return out


def bots_section(paper) -> dict:
    out = {}
    for b in paper.bots.values():
        tr = [dict(t.__dict__) for t in b.sim.trades]
        eq = [p["value"] for p in b.sim.equity_curve]
        peak, mdd = (eq[0] if eq else b.initial_equity), 0.0
        for v in eq:
            peak = max(peak, v)
            mdd = max(mdd, (peak - v) / peak * 100 if peak > 0 else 0)
        cur = b.sim.equity(b.last_price) if b.last_price else b.sim.cash
        name = b.spec.name if b.spec.name not in out else f"{b.spec.name}#{b.id[:4]}"
        st = _stats(tr)
        out[name] = {"id": b.id, "symbol": b.spec.symbol, "interval": b.spec.interval, "running": b.running,
                     "equity": _r(cur, 7), "return_pct": _r((cur / b.initial_equity - 1) * 100, 4), "max_drawdown_pct": _r(mdd, 4),
                     "trades": st["trades"], "win_rate_pct": st.get("win_rate_pct"), "profit_factor": st.get("profit_factor"),
                     "status": st.get("status", "insufficient"), "position": (b.sim.position and ("long" if b.sim.position.side == 1 else "short")) or None,
                     "versions": len(b.versions), "auto_improve": b.auto_improve,
                     "last_log": [x["msg"][:100] for x in b.log[-3:]]}
    return out


def synergy_section(paper) -> dict:
    series = {}
    for b in paper.bots.values():
        eq = b.sim.equity_curve
        daily = {}
        for p in eq:
            daily[int(p["time"] // 86400)] = p["value"]
        ds = sorted(daily)
        series[b.spec.name] = {d: daily[d] / daily[ds[i - 1]] - 1 for i, d in enumerate(ds) if i and daily[ds[i - 1]]}
    names = list(series)
    corr = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            days = sorted(set(series[a]) & set(series[b]))
            if len(days) < 5:
                corr[f"{a} × {b}"] = {"n_days": len(days), "corr": None, "status": "insufficient"}
                continue
            x, y = [series[a][d] for d in days], [series[b][d] for d in days]
            mx, my = sum(x) / len(x), sum(y) / len(y)
            cv = sum((p - mx) * (q - my) for p, q in zip(x, y))
            vx, vy = sum((p - mx) ** 2 for p in x), sum((q - my) ** 2 for q in y)
            both_loss = sum(1 for p, q in zip(x, y) if p < 0 and q < 0)
            corr[f"{a} × {b}"] = {"n_days": len(days), "corr": _r(cv / math.sqrt(vx * vy), 3) if vx and vy else None,
                                 "both_loss_days": both_loss, "status": "ok" if len(days) >= 20 else "insufficient"}
    same_coin_opposite = []
    pos = [(b.spec.name, b.spec.symbol, b.sim.position.side) for b in paper.bots.values() if b.sim.position]
    for i, (n1, s1, d1) in enumerate(pos):
        for n2, s2, d2 in pos[i + 1:]:
            if s1 == s2 and d1 != d2:
                same_coin_opposite.append(f"{n1} ↔ {n2} ({s1})")
    return {"bots": len(names), "corr": corr, "same_coin_opposite_positions": same_coin_opposite}


def ops_section(paper) -> dict:
    from ..llm import provider
    from ..quant import copilot
    from ..quant.scanner import scanner
    src = None
    try:
        src = market.candles("BTCUSDT", "1m", 2)[1]
    except Exception as e:
        src = f"오류: {str(e)[:60]}"
    now = time.time()
    al = [a for a in copilot.alerts_feed if now - a["created"] < 86400]
    bot_err = {b.spec.name: [x["msg"][:100] for x in b.log[-30:] if "오류" in x["msg"]][-3:] for b in paper.bots.values()}
    return {"data_source": src, "data_source_note": "synthetic = 가상 데이터 (실제 시장이 아님)" if src == "synthetic" else "",
            "ai": provider() or "none", "scanner": {"enabled": scanner.cfg.get("enabled"), "last_run_min_ago": _r((now - scanner.last_run) / 60, 3) if scanner.last_run else None,
                                                     "errors": len(scanner.errors), "error_samples": list(scanner.errors.values())[:3]},
            "watcher_alerts_24h": {"high": sum(a["level"] == "high" for a in al), "medium": sum(a["level"] == "medium" for a in al)},
            "bot_errors": {k: v for k, v in bot_err.items() if v}, "bots_running": sum(b.running for b in paper.bots.values()),
            "bots_total": len(paper.bots)}


def signals_section(coins: list[str]) -> dict:
    try:
        from ..quant.scanner import scanner
        rec = scanner.recent(int(time.time()) - 86400, 200)
    except Exception:
        rec = []
    by = {}
    for s in rec:
        if s["symbol"] in coins:
            d = by.setdefault(s["symbol"], {"long": 0, "short": 0})
            if s.get("dir") in d:
                d[s["dir"]] += 1
    return {"by_coin_24h": by, "recent": [{"symbol": s["symbol"], "interval": s["interval"], "dir": s.get("dir"), "label": s["label"],
                                            "minutes_ago": round((time.time() - s["created"]) / 60)} for s in rec[:10]]}


def slice_for(packet: dict, paths: tuple[str, ...]) -> dict:
    """역할에 필요한 부분만 잘라 준다. 'market.*.price' 처럼 * 는 모든 키."""
    out: dict = {}

    def put(dst, parts, src):
        if not parts:
            return src
        k, rest = parts[0], parts[1:]
        if k == "*" and isinstance(src, dict):
            d = dst if isinstance(dst, dict) else {}
            for kk, vv in src.items():
                v = put(d.get(kk), rest, vv)
                if v is not None:
                    d[kk] = v
            return d
        if isinstance(src, dict) and k in src:
            d = dst if isinstance(dst, dict) else {}
            v = put(d.get(k), rest, src[k])
            if v is not None:
                d[k] = v
            return d
        return dst
    for p in paths:
        out = put(out, p.split("."), packet) or out
    return out
