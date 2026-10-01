"""코인팀 도구 — 호가 벽·불균형, 고래 체결, 선물 수급, 예상 청산 구간, 흐름 점수 (바이낸스 USDT-M 공개 API).

모든 숫자는 코드가 계산하고, AI 는 text(해설용 요약)만 받는다. 실패하면 {"error"} 로 돌려준다(도구가 회의를 멈추지 않게).
"""
from __future__ import annotations

import math
import time

from .. import config
from ..data import binance

_cache: dict = {}


def _ttl(key, sec, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < sec:
        return hit[1]
    v = fn()
    _cache[key] = (time.time(), v)
    return v


def usd(x: float) -> str:
    """한국식 달러 표기 (억/만 달러)."""
    a = abs(x)
    s = "-" if x < 0 else ""
    if a >= 1e8:
        return f"{s}{a / 1e8:.2f}억 달러"
    if a >= 1e4:
        return f"{s}{a / 1e4:,.0f}만 달러"
    return f"{s}{a:,.0f} 달러"


def _px(p: float) -> str:
    return f"{p:,.2f}" if p >= 100 else f"{p:.4g}"


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _guard(fn):
    def w(*a, **k):
        if config.DATA_SOURCE == "synthetic":
            return {"error": "가상 데이터 모드라 실시간 호가·체결이 없습니다", "text": "실시간 데이터 없음 (테스트 모드)", "summary": "데이터 없음"}
        try:
            return fn(*a, **k)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:160], "text": f"데이터를 가져오지 못했습니다: {str(e)[:120]}", "summary": "가져오기 실패"}
    w.__name__ = fn.__name__
    return w


# ------------------------------------------------------------------ 1. 호가
@_guard
def order_book(symbol: str = "BTCUSDT", depth: int = 500) -> dict:
    lim = next((x for x in (5, 10, 20, 50, 100, 500, 1000) if x >= depth), 1000)
    b = binance.depth(symbol, lim)
    bids, asks = b["bids"], b["asks"]
    if not bids or not asks:
        raise ValueError("호가가 비어 있습니다")
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2
    spread_bps = (ba - bb) / mid * 1e4
    cover_bid = (mid - bids[-1][0]) / mid * 100
    cover_ask = (asks[-1][0] - mid) / mid * 100
    bands = {}
    for pct in (0.5, 1, 2):
        bn = sum(p * q for p, q in bids if p >= mid * (1 - pct / 100))
        an = sum(p * q for p, q in asks if p <= mid * (1 + pct / 100))
        bands[pct] = {"bid": bn, "ask": an, "ratio": bn / an if an else None,
                      "imbalance": (bn - an) / (bn + an) if bn + an else 0.0,
                      "complete": cover_bid >= pct and cover_ask >= pct}
    step = mid * 0.001

    def walls(levels):
        bk: dict = {}
        for p, q in levels:
            k = math.floor(p / step)
            a = bk.setdefault(k, [0.0, 0.0])
            a[0] += p * q
            a[1] += q
        avg = sum(v[0] for v in bk.values()) / max(1, len(bk))
        top = sorted(bk.values(), key=lambda v: -v[0])[:5]
        return [{"price": v[0] / v[1], "usd": v[0], "dist_pct": (v[0] / v[1] / mid - 1) * 100, "x_avg": v[0] / avg if avg else None} for v in top]
    bw, aw = walls(bids), walls(asks)
    notes = []
    if bw:
        notes.append(f"최대 매수벽 {_px(bw[0]['price'])} ({usd(bw[0]['usd'])}, {bw[0]['dist_pct']:+.2f}%)")
    if aw:
        notes.append(f"최대 매도벽 {_px(aw[0]['price'])} ({usd(aw[0]['usd'])}, {aw[0]['dist_pct']:+.2f}%)")
    i1, i2 = bands[1]["imbalance"], bands[2]["imbalance"]
    notes.append("±1% 안 매도 쪽이 얇음(매수 우위)" if i1 > 0.2 else "±1% 안 매수 쪽이 얇음(매도 우위)" if i1 < -0.2 else "±1% 안 양쪽이 비슷함")
    if abs(i2) > 0.3 and (i2 > 0) != (i1 > 0):
        notes.append(f"±2%까지는 {'매수' if i2 > 0 else '매도'} 쪽이 두꺼움")
    if spread_bps > 5:
        notes.append(f"스프레드 {spread_bps:.1f}bp로 넓음(유동성 약함)")
    text = (f"[호가 {symbol}] 중간가 {_px(mid)} · 스프레드 {spread_bps:.2f}bp\n"
            + "\n".join(f"±{k}%: 매수 {usd(v['bid'])} / 매도 {usd(v['ask'])} · 불균형 {v['imbalance'] * 100:+.0f}%{'' if v['complete'] else ' (호가 범위 부족)'}" for k, v in bands.items())
            + "\n매수벽: " + ", ".join(f"{_px(w['price'])} {usd(w['usd'])}" for w in bw[:3])
            + "\n매도벽: " + ", ".join(f"{_px(w['price'])} {usd(w['usd'])}" for w in aw[:3])
            + "\n해석: " + " · ".join(notes))
    return {"symbol": symbol, "mid": mid, "spread_bps": spread_bps, "bands": bands, "bid_walls": bw, "ask_walls": aw,
            "imbalance_1": i1, "text": text[:1790],
            "summary": f"호가 {symbol}: ±1% 불균형 {i1 * 100:+.0f}% · 최대 매수벽 {_px(bw[0]['price']) if bw else '-'} · 최대 매도벽 {_px(aw[0]['price']) if aw else '-'}"}


# ------------------------------------------------------------------ 2. 고래 체결
@_guard
def whale_trades(symbol: str = "BTCUSDT", min_usd: float = 500_000, pages: int = 1) -> dict:
    rows = binance._get("/fapi/v1/aggTrades", {"symbol": symbol, "limit": 1000})
    for _ in range(max(0, min(9, pages - 1))):
        if not rows:
            break
        older = binance._get("/fapi/v1/aggTrades", {"symbol": symbol, "limit": 1000, "fromId": max(0, int(rows[0]["a"]) - 1000)})
        rows = [r for r in older if int(r["a"]) < int(rows[0]["a"])] + rows
    tr = [{"t": int(r["T"]) / 1000, "p": float(r["p"]), "usd": float(r["p"]) * float(r["q"]), "side": "sell" if r["m"] else "buy"} for r in rows]
    if not tr:
        raise ValueError("체결이 없습니다")
    span_min = max(0.01, (tr[-1]["t"] - tr[0]["t"]) / 60)
    buy = sum(x["usd"] for x in tr if x["side"] == "buy")
    sell = sum(x["usd"] for x in tr if x["side"] == "sell")
    ratio = buy / sell if sell else None
    wh = [x for x in tr if x["usd"] >= min_usd]
    wb = sum(x["usd"] for x in wh if x["side"] == "buy")
    ws = sum(x["usd"] for x in wh if x["side"] == "sell")
    net = wb - ws
    net_pct = net / (wb + ws) * 100 if wh else 0.0
    notes = []
    if wh:
        notes.append(f"고래 순{'매수' if net >= 0 else '매도'} {usd(abs(net))} ({len(wh)}건)")
    else:
        notes.append(f"{span_min:.0f}분 동안 {usd(min_usd)} 이상 체결 없음")
    if ratio and ratio > 1.15:
        notes.append("시장가 매수 우세")
    elif ratio and ratio < 0.87:
        notes.append("시장가 매도 우세")
    if span_min < 3:
        notes.append("관찰 시간이 짧아 참고용")
    top = sorted(wh, key=lambda x: -x["usd"])[:10]
    text = (f"[고래 체결 {symbol}] 최근 {span_min:.0f}분 · 체결 {len(tr)}건 · 시장가 매수 {usd(buy)} / 매도 {usd(sell)} (비율 {ratio:.2f})\n" if ratio else f"[고래 체결 {symbol}] 최근 {span_min:.0f}분\n")
    text += f"{usd(min_usd)} 이상 고래: {len(wh)}건 · 매수 {usd(wb)} / 매도 {usd(ws)} · 순 {usd(net)} ({net_pct:+.0f}%) · 거래대금 비중 {(wb + ws) / (buy + sell) * 100 if buy + sell else 0:.0f}%\n"
    text += "\n".join(f"- {time.strftime('%H:%M:%S', time.localtime(x['t']))} {'매수' if x['side'] == 'buy' else '매도'} {usd(x['usd'])} @ {_px(x['p'])}" for x in top[:6])
    text += "\n해석: " + " · ".join(notes)
    return {"symbol": symbol, "minutes": span_min, "buy": buy, "sell": sell, "ratio": ratio, "whales": len(wh), "whale_buy": wb,
            "whale_sell": ws, "net": net, "net_pct": net_pct, "top": top, "text": text[:1790],
            "summary": f"고래 {symbol}: {len(wh)}건 · 순 {usd(net)} · 시장가 매수/매도 {ratio:.2f} ({span_min:.0f}분)" if ratio else f"고래 {symbol}: {len(wh)}건"}


# ------------------------------------------------------------------ 3. 선물 수급
def _ratio_rows(path, symbol, period, limit):
    try:
        return binance._get(path, {"symbol": symbol, "period": period, "limit": limit})
    except Exception:  # noqa: BLE001
        return []


@_guard
def futures_flow(symbol: str = "BTCUSDT", period: str = "1h", limit: int = 48) -> dict:
    hours = {"5m": 5 / 60, "15m": .25, "30m": .5, "1h": 1, "2h": 2, "4h": 4, "6h": 6, "12h": 12, "1d": 24}.get(period, 1) * limit
    top_pos = _ratio_rows("/futures/data/topLongShortPositionRatio", symbol, period, limit)
    top_acc = _ratio_rows("/futures/data/topLongShortAccountRatio", symbol, period, limit)
    glob = _ratio_rows("/futures/data/globalLongShortAccountRatio", symbol, period, limit)
    taker = _ratio_rows("/futures/data/takerlongshortRatio", symbol, period, limit)
    oi = _ratio_rows("/futures/data/openInterestHist", symbol, period, limit)
    try:
        fr = binance._get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": int(math.ceil(hours / 8)) + 1})
    except Exception:  # noqa: BLE001
        fr = []
    try:
        prem = binance._get("/fapi/v1/premiumIndex", {"symbol": symbol})
    except Exception:  # noqa: BLE001
        prem = {}
    out, lines = {"symbol": symbol, "period": period}, [f"[선물 수급 {symbol}] {period} × {limit}"]

    def ratio(rows, name):
        if not rows:
            return None
        a, b = rows[0], rows[-1]
        lp = float(b["longAccount"] if "longAccount" in b else b.get("longPosition", 0)) * 100
        lp0 = float(a["longAccount"] if "longAccount" in a else a.get("longPosition", 0)) * 100
        r = {"ratio": float(b["longShortRatio"]), "long_pct": lp, "change_pp": lp - lp0}
        lines.append(f"{name}: 롱/숏 {r['ratio']:.2f} · 롱 {lp:.1f}% ({r['change_pp']:+.1f}%p)")
        return r
    out["top_position"] = ratio(top_pos, "상위 트레이더(포지션)")
    out["top_account"] = ratio(top_acc, "상위 트레이더(계정)")
    out["global"] = ratio(glob, "전체 계정")
    if taker:
        rs = [float(x["buySellRatio"]) for x in taker]
        bv = sum(float(x["buyVol"]) for x in taker)
        sv = sum(float(x["sellVol"]) for x in taker)
        out["taker"] = {"last": rs[-1], "avg6": sum(rs[-6:]) / len(rs[-6:]), "window": bv / sv if sv else None}
        lines.append(f"테이커 매수/매도: 최근 {rs[-1]:.2f} · 최근6 평균 {out['taker']['avg6']:.2f}")
    if oi:
        v0, v1 = float(oi[0]["sumOpenInterestValue"]), float(oi[-1]["sumOpenInterestValue"])
        q0, q1 = float(oi[0]["sumOpenInterest"]), float(oi[-1]["sumOpenInterest"])
        p0, p1 = (v0 / q0 if q0 else 0), (v1 / q1 if q1 else 0)
        out["oi"] = {"value": v1, "change_pct": (v1 / v0 - 1) * 100 if v0 else 0, "qty_change_pct": (q1 / q0 - 1) * 100 if q0 else 0,
                     "price_change_pct": (p1 / p0 - 1) * 100 if p0 else 0}
        lines.append(f"미결제약정: {usd(v1)} ({out['oi']['change_pct']:+.1f}%, 수량 {out['oi']['qty_change_pct']:+.1f}%) · 가격 {out['oi']['price_change_pct']:+.1f}%")
    if fr:
        rates = [float(x["fundingRate"]) for x in fr]
        iv = (int(fr[-1]["fundingTime"]) - int(fr[-2]["fundingTime"])) / 3_600_000 if len(fr) > 1 else 8
        iv = iv if iv > 0 else 8
        ann = lambda r: r * 24 / iv * 365 * 100
        out["funding"] = {"last_pct": rates[-1] * 100, "avg_pct": sum(rates) / len(rates) * 100, "interval_h": iv,
                          "annual_last": ann(rates[-1]), "annual_avg": ann(sum(rates) / len(rates))}
        lines.append(f"펀딩: 최근 {rates[-1] * 100:.4f}% ({iv:.0f}시간) · 평균 {out['funding']['avg_pct']:.4f}% · 연환산 {out['funding']['annual_avg']:.1f}%")
    if prem:
        mk, ix = float(prem.get("markPrice", 0)), float(prem.get("indexPrice", 0))
        nf = float(prem.get("lastFundingRate", 0))
        out["premium"] = {"mark": mk, "index": ix, "basis_bps": (mk / ix - 1) * 1e4 if ix else 0, "next_funding_pct": nf * 100,
                          "next_time": int(prem.get("nextFundingTime", 0)) // 1000}
        lines.append(f"마크 {_px(mk)} · 인덱스 {_px(ix)} · 베이시스 {out['premium']['basis_bps']:+.1f}bp · 다음 펀딩 {nf * 100:.4f}%")
    notes = []
    o = out.get("oi")
    if o:
        up_oi, dn_oi = o["change_pct"] > 2, o["change_pct"] < -2
        up_p, dn_p = o["price_change_pct"] > 0, o["price_change_pct"] < 0
        notes.append("OI 증가+가격 상승 → 신규 롱 유입" if up_oi and up_p else "OI 증가+가격 하락 → 신규 숏 유입" if up_oi and dn_p
                     else "OI 감소+가격 상승 → 숏 커버링" if dn_oi and up_p else "OI 감소+가격 하락 → 롱 청산·디레버리징" if dn_oi and dn_p else "OI 큰 변화 없음")
    fa = (out.get("funding") or {}).get("annual_avg")
    gl = (out.get("global") or {}).get("long_pct")
    crowd = 0.0
    if fa is not None and gl is not None:
        if fa > 30 and gl > 60:
            c, crowd = "롱 스퀴즈(급락) 위험 높음", 1
        elif fa > 15 and gl > 55:
            c, crowd = "롱 쏠림 — 하락 시 연쇄 청산 주의", .5
        elif fa < 0 and gl < 45:
            c, crowd = "숏 스퀴즈(급등) 위험 높음", -1
        elif fa < 3 and gl < 50:
            c, crowd = "숏 쏠림 — 상승 시 숏 커버링 주의", -.5
        else:
            c = "낮음"
        if crowd and o and o["change_pct"] > 5:
            c += " (OI 급증으로 연료 증가)"
        notes.append("쏠림: " + c)
    tp = (out.get("top_position") or {}).get("long_pct")
    if tp is not None and gl is not None and abs(tp - gl) >= 5:
        notes.append(f"상위 트레이더가 군중보다 {'롱' if tp > gl else '숏'} ({tp - gl:+.1f}%p)")
    tk = (out.get("taker") or {}).get("avg6")
    if tk and tk > 1.1:
        notes.append("최근 시장가 매수 공격적")
    elif tk and tk < .9:
        notes.append("최근 시장가 매도 공격적")
    out["crowding"] = crowd
    out["notes"] = notes
    out["text"] = ("\n".join(lines) + "\n해석: " + " · ".join(notes))[:1790]
    out["summary"] = f"선물 {symbol}: " + (" · ".join(notes[:2]) or "데이터 일부만")
    return out


# ------------------------------------------------------------------ 4. 예상 청산 구간 (추정)
@_guard
def liquidation_estimate(symbol: str = "BTCUSDT") -> dict:
    prem = binance._get("/fapi/v1/premiumIndex", {"symbol": symbol})
    price = float(prem["markPrice"])
    hist = binance._get("/futures/data/openInterestHist", {"symbol": symbol, "period": "1h", "limit": 72})
    kl = binance.klines(symbol, "1h", 80)
    glob = _ratio_rows("/futures/data/globalLongShortAccountRatio", symbol, "1h", 1)
    long_share = _clamp(float(glob[-1]["longAccount"]) if glob else 0.5, .05, .95)
    by_t = {b["time"]: b for b in kl}
    lev_mix = [(10, .35), (25, .30), (50, .20), (100, .15)]
    mmr, step = 0.004, price * 0.005
    buckets = {"long": {}, "short": {}}
    for a, b in zip(hist, hist[1:]):
        dq = float(b["sumOpenInterest"]) - float(a["sumOpenInterest"])
        if dq <= 0:
            continue
        p = float(b["sumOpenInterestValue"]) / float(b["sumOpenInterest"])
        t = int(b["timestamp"]) // 1000
        later = [x for x in kl if x["time"] >= t]
        lo = min((x["low"] for x in later), default=p)
        hi = max((x["high"] for x in later), default=p)
        amt = dq * p
        for L, w in lev_mix:
            ll = p * (1 - 1 / L + mmr)
            sl = p * (1 + 1 / L - mmr)
            if lo > ll:                              # 아직 안 닿은 롱 청산가
                k = round(ll / step)
                buckets["long"][k] = buckets["long"].get(k, 0) + amt * w * long_share
            if hi < sl:
                k = round(sl / step)
                buckets["short"][k] = buckets["short"].get(k, 0) + amt * w * (1 - long_share)
    _ = by_t
    try:
        book = order_book(symbol, 1000)
    except Exception:  # noqa: BLE001
        book = {}

    def top(side):
        rows = sorted(({"price": k * step, "usd": v, "dist_pct": (k * step / price - 1) * 100} for k, v in buckets[side].items()), key=lambda x: -x["usd"])[:5]
        walls = book.get("bid_walls" if side == "long" else "ask_walls") or []
        for r in rows:
            r["wall"] = any(abs(w["price"] / r["price"] - 1) < 0.003 for w in walls)
        return sorted(rows, key=lambda x: abs(x["dist_pct"]))
    lg, sh = top("long"), top("short")
    tl, ts = sum(buckets["long"].values()), sum(buckets["short"].values())
    notes = []
    if lg:
        notes.append(f"가장 가까운 롱 청산대 {_px(lg[0]['price'])} ({lg[0]['dist_pct']:+.1f}%){' — 매수벽과 겹침(지지 가능)' if lg[0]['wall'] else ''}")
    if sh:
        notes.append(f"가장 가까운 숏 청산대 {_px(sh[0]['price'])} ({sh[0]['dist_pct']:+.1f}%){' — 매도벽과 겹침(저항 가능)' if sh[0]['wall'] else ''}")
    if tl > ts * 1.3:
        notes.append("아래쪽 롱 청산 물량이 더 많음 → 급락 시 연쇄 위험")
    elif ts > tl * 1.3:
        notes.append("위쪽 숏 청산 물량이 더 많음 → 급등 시 숏 스퀴즈 위험")
    text = (f"[예상 청산 구간 {symbol}] (추정 — 실제 청산 데이터 아님: 72시간 OI 증가분 × 레버리지 10/25/50/100배 가정)\n현재가 {_px(price)}\n"
            + "롱 청산대: " + ", ".join(f"{_px(r['price'])}({r['dist_pct']:+.1f}%) {usd(r['usd'])}" for r in lg) + "\n"
            + "숏 청산대: " + ", ".join(f"{_px(r['price'])}({r['dist_pct']:+.1f}%) {usd(r['usd'])}" for r in sh) + "\n해석: " + " · ".join(notes))
    return {"symbol": symbol, "price": price, "long": lg, "short": sh, "long_total": tl, "short_total": ts, "text": text[:1790],
            "summary": " · ".join(notes[:2]) or "청산대 추정 없음"}


# ------------------------------------------------------------------ 5. 흐름 점수
@_guard
def flow_snapshot(symbol: str = "BTCUSDT") -> dict:
    ob, wt, ff = order_book(symbol), whale_trades(symbol), futures_flow(symbol)
    pts, mx, parts = 0.0, 0.0, []

    def add(name, w, v, note):
        nonlocal pts, mx
        if v is None:
            return
        pts += w * v
        mx += w
        parts.append(f"{name} {w * v:+.0f}/{w} ({note})")
    if "error" not in ob:
        add("호가", 25, _clamp(ob["imbalance_1"] / .5), f"±1% 불균형 {ob['imbalance_1'] * 100:+.0f}%")
    if "error" not in wt:
        add("고래", 25, (wt["net_pct"] / 100) if wt["whales"] else 0.0, f"순 {usd(wt['net'])}")
        if wt.get("ratio"):
            add("체결", 15, _clamp((wt["ratio"] - 1) / .3), f"시장가 비율 {wt['ratio']:.2f}")
    if "error" not in ff:
        tk = (ff.get("taker") or {}).get("avg6")
        if tk:
            add("선물 테이커", 15, _clamp((tk - 1) / .3), f"{tk:.2f}")
        tp = (ff.get("top_position") or {}).get("long_pct")
        if tp is not None:
            add("상위 트레이더", 10, _clamp((tp - 50) / 15), f"롱 {tp:.0f}%")
        fa = (ff.get("funding") or {}).get("annual_avg")
        if fa is not None:
            add("펀딩(역발상)", 10, -_clamp((fa - 10.95) / 30), f"연 {fa:.1f}%")
    score = round(pts / mx * 100) if mx else 0
    label = "강한 매수 압력" if score >= 50 else "매수 우위" if score >= 20 else "중립" if score > -20 else "매도 우위" if score > -50 else "강한 매도 압력"
    head = f"[흐름 점수] {score:+d} ({label}) — " + " · ".join(parts)
    body = "\n\n".join(x["text"][:560] for x in (ob, wt, ff) if x.get("text"))
    return {"symbol": symbol, "score": score, "label": label, "parts": parts, "book": ob, "whales": wt, "futures": ff,
            "text": (head + "\n\n" + body)[:1790], "summary": f"흐름 {symbol}: {score:+d} {label}"}
