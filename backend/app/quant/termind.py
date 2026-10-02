"""터미널 보조지표 전부(147종)로 추세·타점 — 차트 화면의 지표 코드(frontend/js/ind.js)를 서버에서 그대로 돌린다.

- QuickJS(작은 자바스크립트 엔진)로 ind.js 를 실행 → 화면에서 보는 값과 똑같다. 브라우저를 닫아도 24시간 계산된다.
- 지표마다 방향 표(+1 상승 ~ -1 하락)와 과열·침체(타이밍)를 뽑는다:
  · 가격 위 선(이평·채널·스톱선 등) → 가격이 선 위/아래 · 화살표 신호(크로스·UT Bot·구조 전환 등) → 최근 신호 방향
  · 오실레이터 → 기준선(레벨의 가운데) 위/아래 + 위/아래 레벨 밖이면 과열·침체 · 누적 거래량 지표 → 기울기
  · 변동성·통계(ATR·밴드폭·허스트 등)는 방향이 아니라 장세 정보로만 쓴다.
- 그룹(추세·신호·SMC·오실레이터·거래량·파생·통계)별 평균 → 가중 합 = 추세 점수(-100~+100), 여러 봉(15분·1시간·4시간·일)로 정렬 확인.
- 타점: 큰 봉 추세 방향으로만. 작은 봉이 침체(롱)·과열(숏)로 되돌린 곳 = 눌림 진입, 구조 돌파 신호 = 돌파 진입.
  손절은 ATR·스윙, 목표는 지표가 그린 지지·저항 레벨(피봇·피보나치·VWAP·전일 고저 등). 손익비 1.5 미만이면 관망.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time

from .. import config

POLY = """
if (!Array.prototype.at) Object.defineProperty(Array.prototype, "at", {value: function(i){ i = Math.trunc(i)||0; if (i<0) i += this.length; return this[i]; }});
if (!String.prototype.at) Object.defineProperty(String.prototype, "at", {value: function(i){ i = Math.trunc(i)||0; if (i<0) i += this.length; return this[i]; }});
if (!Array.prototype.findLast) Object.defineProperty(Array.prototype, "findLast", {value: function(f){ for (let i=this.length-1;i>=0;i--) if (f(this[i],i,this)) return this[i]; }});
if (!Array.prototype.findLastIndex) Object.defineProperty(Array.prototype, "findLastIndex", {value: function(f){ for (let i=this.length-1;i>=0;i--) if (f(this[i],i,this)) return i; return -1; }});
if (!Array.prototype.toSorted) Object.defineProperty(Array.prototype, "toSorted", {value: function(f){ return this.slice().sort(f); }});
if (typeof structuredClone === "undefined") globalThis.structuredClone = (x) => JSON.parse(JSON.stringify(x));
"""

# 지표마다 값을 요약해서 돌려준다 (전체 시리즈는 너무 크다)
RUNNER = """
function __lastIdx(a){ for (let i=a.length-1;i>=0;i--) if (a[i]!=null && !(typeof a[i]==="number" && isNaN(a[i]))) return i; return -1; }
function __summ(pl, n){
  const o = {name: pl.name, type: pl.type};
  if (pl.type === "signals" || pl.type === "patterns") {
    const d = pl.data || []; let k = -1;
    for (let i=d.length-1;i>=0 && i>=d.length-60;i--) if (d[i] && (d[i].dir===1 || d[i].dir===-1)) { k = i; break; }
    if (k >= 0) { o.dir = d[k].dir; o.ago = n-1-k; o.text = d[k].text || ""; }
    return o;
  }
  if (pl.type === "boxes") {
    const L = (pl.data && pl.data.list) || pl.list || [];
    o.boxes = L.slice(-8).map(b => ({top: b.top, bottom: b.bottom, bull: b.bull, open: b.i1 == null}));
    return o;
  }
  const d = pl.data || []; const k = __lastIdx(d);
  if (k < 0) return o;
  o.last = d[k]; o.ago = n-1-k;
  const p1 = d[k-1], p5 = d[k-5];
  if (p1 != null) o.prev = p1; if (p5 != null) o.prev5 = p5;
  const w = d.slice(Math.max(0, k-199), k+1).filter(v => v!=null);
  if (w.length > 20) { let c=0; for (const v of w) if (v <= o.last) c++; o.rank = Math.round(c / w.length * 100); }
  return o;
}
function __run(cj, extj){
  const c = JSON.parse(cj), ext = JSON.parse(extj), out = {}, n = c.length;
  for (const k of Object.keys(INDICATORS)) {
    const d = INDICATORS[k];
    if (d.pane === "volume") continue;
    try {
      const r = d.compute(c, {...(d.params||{})}, ext) || {};
      out[k] = {name: d.name, group: d.group, pane: d.pane, levels: r.levels || [], note: r.note || "",
                plots: (r.plots||[]).map(pl => __summ(pl, n)),
                lines: (r.lines||[]).slice(0, 12).map(l => ({price: l.price ?? l.value, title: l.title || l.name || ""}))};
    } catch (e) { out[k] = {name: d.name, group: d.group, pane: d.pane, error: String(e).slice(0, 120)}; }
  }
  return JSON.stringify(out);
}
"""

_lock = threading.Lock()
_ctx = {"c": None, "err": None}


def _context():
    """ind.js 를 한 번 읽어 둔다 (스레드 하나만 쓰도록 잠금)."""
    if _ctx["c"] is not None or _ctx["err"]:
        return _ctx["c"]
    try:
        import quickjs
        src = (config.FRONTEND_DIR / "js" / "ind.js").read_text(encoding="utf-8")
        src = re.sub(r"^export\s+", "", src, flags=re.M)
        c = quickjs.Context()
        c.eval(POLY)
        c.eval(src)
        c.eval(RUNNER)
        _ctx["c"] = c
    except Exception as e:  # noqa: BLE001
        _ctx["err"] = str(e)
    return _ctx["c"]


def available() -> tuple[bool, str]:
    return (_context() is not None, _ctx.get("err") or "")


def compute_all(candles: list[dict], ext: dict | None = None) -> dict:
    ctx = _context()
    if ctx is None:
        raise RuntimeError(f"터미널 지표 엔진을 열지 못했습니다: {_ctx['err']}")
    c = [{"time": b["time"], "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": b.get("volume", 0),
          "taker_buy": b.get("taker_buy")} for b in candles]
    with _lock:
        out = ctx.eval(f"__run({json.dumps(json.dumps(c))}, {json.dumps(json.dumps(ext or {}))})")
    return json.loads(out)


# ------------------------------------------------------------------ 방향 표 · 타이밍
GROUP_W = {"추세": 1.5, "신호 · 패턴": 1.2, "스마트머니 (SMC)": 1.0, "오실레이터": 0.8, "거래량": 0.8, "파생 · 코인글라스": 0.4,
           "통계 · 퀀트": 0.5, "레벨 · 프로파일": 0.4, "변동성": 0.0}
NON_DIR = {"adx", "atr", "bbw", "chop", "hv", "mass", "stdev", "vol_est", "vol_rank", "skew_kurt", "autocorr", "hurst", "fdi", "r2", "corr_btc",
           "rvol", "vol_osc", "oi", "oi_delta", "liq", "funding", "long_short", "ulcer", "rvix", "chaikin_vol", "vhf", "vix_fix", "gator",
           "vp", "session_vp", "fib", "pivots", "pdhl", "camarilla", "fib_pivots", "pmhl", "round_numbers", "sessions_hl", "adr", "fractals"}
CUMULATIVE = {"obv", "cvd", "adl", "pvt", "nvi_pvi"}
PAIR = {"aroon", "vortex", "elder"}               # 앞 두 선(상승/하락)의 차이로 판단
REGIME = {"adx": "추세 강도", "chop": "횡보 지수", "hurst": "허스트", "r2": "추세 신뢰도 R²", "vhf": "VHF", "bbw": "밴드폭", "vol_rank": "변동성 백분위",
          "autocorr": "자기상관"}


def _clamp(x, a=-1.0, b=1.0):
    return max(a, min(b, x))


def _num(v):
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


def vote(key: str, r: dict, close: float, atr: float) -> tuple[float | None, str | None]:
    """(방향 -1~1 또는 None, 'ob'/'os' 과열·침체 또는 None)"""
    if r.get("error") or key in NON_DIR:
        return None, None
    plots = r.get("plots") or []
    sigs = [p for p in plots if p.get("type") in ("signals", "patterns") and p.get("dir")]
    if sigs:
        s = min(sigs, key=lambda p: p["ago"])
        if s["ago"] <= 3:
            return float(s["dir"]), None
        if s["ago"] <= 12:
            return 0.5 * s["dir"], None
    boxes = [b for p in plots if p.get("type") == "boxes" for b in (p.get("boxes") or []) if b.get("open")]
    if boxes:                                            # 가격 아래 상승 박스(지지)·위 하락 박스(저항)
        sc = sum((1 if b.get("bull") and b["top"] <= close * 1.01 else -1 if (not b.get("bull")) and b["bottom"] >= close * 0.99 else 0) for b in boxes)
        return (_clamp(sc / 3), None) if sc else (None, None)
    vals = [p for p in plots if p.get("type") in ("line", "hist", "dots") and _num(p.get("last")) is not None and p.get("ago", 99) <= 2]
    if not vals:
        return None, None
    if r["pane"] == "main":                              # 가격 위 선: 가격이 선 위면 +
        sc = [_clamp((close - p["last"]) / (atr or close * 0.01)) for p in vals]
        return sum(sc) / len(sc), None
    p = vals[0]
    lv = [x for x in (r.get("levels") or []) if _num(x) is not None]
    if key in PAIR and len(vals) >= 2:
        a, b = vals[0]["last"], vals[1]["last"]
        return (_clamp((a - b) / (abs(a) + abs(b) + 1e-12) * 3), None)
    if key in CUMULATIVE:
        p5 = _num(p.get("prev5"))
        return (None if p5 is None else (1.0 if p["last"] > p5 else -1.0)), None
    last = p["last"]
    if len(lv) >= 2:
        hi, lo = max(lv), min(lv)
        mid = sorted(lv)[len(lv) // 2] if len(lv) % 2 else (hi + lo) / 2
        span = (hi - lo) / 2 or 1
        timing = "ob" if last > hi else "os" if last < lo else None
        return _clamp((last - mid) / span), timing
    mid = lv[0] if lv else 0.0
    if p.get("type") == "hist" or not lv:
        pv = _num(p.get("prev"))
        sc = 0.6 * (1 if last > mid else -1 if last < mid else 0) + (0.4 * (1 if last > pv else -1) if pv is not None and last != pv else 0)
        rank = p.get("rank")
        timing = "ob" if rank is not None and rank >= 95 else "os" if rank is not None and rank <= 5 else None
        return sc, timing
    return (1.0 if last > mid else -1.0 if last < mid else 0.0), None


def levels_from(res: dict, close: float) -> list[dict]:
    """지표들이 그린 수평 레벨(피봇·피보나치·VWAP·전일 고저·밴드 등) → 지지·저항 후보."""
    out = []
    for k, r in res.items():
        if r.get("error"):
            continue
        for l in r.get("lines") or []:
            if _num(l.get("price")):
                out.append({"price": l["price"], "src": f"{r['name']} {l.get('title') or ''}".strip()})
        if r["pane"] == "main" and r["group"] in ("레벨 · 프로파일", "변동성", "추세"):
            for p in r.get("plots") or []:
                if p.get("type") == "line" and _num(p.get("last")) and p.get("ago", 9) <= 1 and abs(p["last"] / close - 1) < 0.15:
                    out.append({"price": p["last"], "src": f"{r['name']} {p.get('name') or ''}".strip()})
    return out


def analyze(candles: list[dict], ext: dict | None = None) -> dict:
    """한 봉 간격의 전체 지표 합의."""
    from .. import indicators as pind
    res = compute_all(candles, ext)
    close = candles[-1]["close"]
    atr = next((v for v in reversed(pind.atr(candles, 14)) if v), close * 0.01)
    groups: dict = {}
    rows, ob, os_ = [], [], []
    for k, r in res.items():
        v, t = vote(k, r, close, atr)
        if t == "ob":
            ob.append(r["name"])
        elif t == "os":
            os_.append(r["name"])
        if v is None:
            continue
        g = groups.setdefault(r["group"], [])
        g.append(v)
        rows.append({"key": k, "name": r["name"], "group": r["group"], "vote": round(v, 2)})
    gsc = {g: round(sum(v) / len(v), 3) for g, v in groups.items()}
    wsum = sum(GROUP_W.get(g, 0.5) for g in gsc) or 1
    score = round(sum(GROUP_W.get(g, 0.5) * s for g, s in gsc.items()) / wsum * 100)
    up = sum(1 for r in rows if r["vote"] > 0.15)
    dn = sum(1 for r in rows if r["vote"] < -0.15)
    regime = {}
    for k, name in REGIME.items():
        r = res.get(k) or {}
        p = next((p for p in r.get("plots") or [] if _num(p.get("last")) is not None), None)
        if p:
            regime[name] = round(p["last"], 3)
    errors = [r["name"] for r in res.values() if r.get("error")]
    return {"score": score, "label": label(score), "groups": gsc, "up": up, "down": dn, "voters": len(rows), "total": len(res),
            "overbought": ob, "oversold": os_, "regime": regime, "errors": errors, "atr": atr, "close": close,
            "top": sorted(rows, key=lambda r: -abs(r["vote"]))[:12], "levels": levels_from(res, close),
            "votes": {r["key"]: r["vote"] for r in rows}, "names": {r["key"]: r["name"] for r in rows}}


def label(score: int) -> str:
    return "강한 상승" if score >= 45 else "상승 우위" if score >= 15 else "중립" if score > -15 else "하락 우위" if score > -45 else "강한 하락"


# ------------------------------------------------------------------ 여러 봉 + 타점
TFS = ["15m", "1h", "4h", "1d"]


def ext_for(symbol: str, interval: str) -> dict:
    """원격 지표(파생·BTC 대비)에 쓸 데이터 — 실패해도 빈 값 (그 지표만 비게 됨)."""
    from ..data import market
    ext: dict = {}
    try:
        d = market.derivatives(symbol, interval, 500)
        ext.update({k: d.get(k) for k in ("open_interest", "funding", "long_short", "liquidations", "taker") if d.get(k)})
    except Exception:  # noqa: BLE001
        pass
    if symbol != "BTCUSDT":
        try:
            ext["btc"] = market.candles("BTCUSDT", interval, 500)[0]
        except Exception:  # noqa: BLE001
            pass
    return ext


def plan(symbol: str, tfs: list[str] | None = None, bars: int = 500) -> dict:
    """여러 봉 합의 → 추세 · 타점(진입·손절·목표·손익비) 또는 관망."""
    from ..analysis import pivots
    from ..data import market
    tfs = tfs or TFS
    per = {}
    candles = {}
    for iv in tfs:
        c, _ = market.candles(symbol, iv, bars)
        candles[iv] = c
        per[iv] = analyze(c, ext_for(symbol, iv))
    w = {"15m": 0.5, "1h": 1.0, "4h": 1.5, "1d": 1.2}
    tot = sum(w.get(iv, 1) for iv in tfs)
    trend = round(sum(per[iv]["score"] * w.get(iv, 1) for iv in tfs) / tot)
    big = [iv for iv in tfs if iv in ("4h", "1d")] or tfs[-1:]
    small = [iv for iv in tfs if iv in ("15m", "1h")] or tfs[:1]
    big_sc = sum(per[iv]["score"] for iv in big) / len(big)
    side = "long" if big_sc >= 15 and trend >= 10 else "short" if big_sc <= -15 and trend <= -10 else None
    ex = small[-1]
    a = per[ex]
    c = candles[ex]
    px, atr = c[-1]["close"], a["atr"]
    out = {"symbol": symbol, "time": int(time.time()), "price": px, "trend": trend, "trend_label": label(trend), "per_tf": {iv: {k: per[iv][k] for k in
           ("score", "label", "groups", "up", "down", "voters", "overbought", "oversold", "regime", "top")} for iv in tfs},
           "aligned": all(per[iv]["score"] > 0 for iv in tfs) or all(per[iv]["score"] < 0 for iv in tfs), "side": side, "entry": None}
    if not side:
        out["verdict"] = "관망 — 큰 봉(4시간·일) 추세가 뚜렷하지 않음"
        return out
    lv = sorted({round(x["price"], 8): x for x in a["levels"]}.values(), key=lambda x: x["price"])
    ph, pl = pivots(c[-200:], 4, 4)
    sgn = 1 if side == "long" else -1
    pull = (a["oversold"] if side == "long" else a["overbought"])
    small_sc = a["score"]
    kind = None
    if pull and small_sc * sgn < 30:
        kind = "눌림" if side == "long" else "반등 매도"
    elif small_sc * sgn >= 30:
        kind = "추세 추종"
    if not kind:
        out["verdict"] = f"{'롱' if side == 'long' else '숏'} 추세지만 {ex} 타이밍 신호 없음 — 기다림"
        return out
    if side == "long":
        sup = [x for x in lv if x["price"] < px][-3:]
        entry = max(px - 0.3 * atr, sup[-1]["price"]) if (kind == "눌림" and sup) else px
        swing = pl[-1][1] if pl else entry - 2 * atr
        stop = min(swing - 0.2 * atr, entry - 1.0 * atr)
        tgts = [x for x in lv if x["price"] > entry + 0.5 * atr][:3] or [{"price": entry + 3 * atr, "src": "ATR×3"}]
    else:
        res_ = [x for x in lv if x["price"] > px][:3]
        entry = min(px + 0.3 * atr, res_[0]["price"]) if (kind == "반등 매도" and res_) else px
        swing = ph[-1][1] if ph else entry + 2 * atr
        stop = max(swing + 0.2 * atr, entry + 1.0 * atr)
        tgts = list(reversed([x for x in lv if x["price"] < entry - 0.5 * atr]))[:3] or [{"price": entry - 3 * atr, "src": "ATR×3"}]
    risk = abs(entry - stop)
    tp = tgts[0]["price"]
    rr = abs(tp - entry) / risk if risk else 0
    if rr < 1.5 and len(tgts) > 1:
        tp = tgts[1]["price"]
        rr = abs(tp - entry) / risk if risk else 0
    conf = int(min(90, 40 + abs(trend) * 0.4 + (10 if out["aligned"] else 0) + (5 if pull else 0)))
    out["entry"] = {"action": side, "kind": kind, "tf": ex, "entry": round(entry, 8), "stop": round(stop, 8), "take": round(tp, 8),
                    "targets": tgts, "rr": round(rr, 2), "confidence": conf,
                    "trigger": f"{ex} {'침체' if side == 'long' else '과열'}({', '.join(pull[:3])}) 뒤 {'반등' if side == 'long' else '꺾임'} 확인" if pull else f"{ex} 지표 합의 {small_sc:+d} 유지",
                    "reason": f"{'/'.join(big)} 추세 {big_sc:+.0f} · 전체 {trend:+d} · {ex} {small_sc:+d} · 상승 {a['up']} / 하락 {a['down']}표"}
    out["verdict"] = (f"{'롱' if side == 'long' else '숏'} {kind} 타점 · 진입 {entry:,.6g} · 손절 {stop:,.6g} · 목표 {tp:,.6g} · 손익비 {rr:.2f}"
                      if rr >= 1.5 else f"{'롱' if side == 'long' else '숏'} 추세지만 손익비 {rr:.2f} < 1.5 — 관망")
    if rr < 1.5:
        out["entry"] = None
    return out


def text(p: dict) -> str:
    """AI 해설용 요약."""
    lines = [f"[{p['symbol']}] 터미널 보조지표 합의 · 현재가 {p['price']:,.6g}", f"전체 추세 {p['trend']:+d} ({p['trend_label']}) · 모든 봉 같은 방향: {'예' if p['aligned'] else '아니오'}"]
    for iv, a in p["per_tf"].items():
        g = " · ".join(f"{k} {v:+.2f}" for k, v in a["groups"].items())
        lines.append(f"- {iv}: {a['score']:+d} {a['label']} (상승 {a['up']} / 하락 {a['down']} / 투표 {a['voters']}개) | {g}")
        if a["overbought"] or a["oversold"]:
            lines.append(f"  과열: {', '.join(a['overbought'][:6]) or '-'} · 침체: {', '.join(a['oversold'][:6]) or '-'}")
        if a["regime"]:
            lines.append("  장세: " + ", ".join(f"{k} {v}" for k, v in a["regime"].items()))
        lines.append("  강한 표: " + ", ".join(f"{t['name']} {t['vote']:+.1f}" for t in a["top"][:6]))
    e = p.get("entry")
    lines.append("판정: " + p.get("verdict", ""))
    if e:
        lines.append(f"타점: {e['kind']} {('롱' if e['action'] == 'long' else '숏')} · 진입 {e['entry']:,.6g} · 손절 {e['stop']:,.6g} · 목표 " +
                     " / ".join(f"{t['price']:,.6g}({t['src'][:20]})" for t in e["targets"]) + f" · 손익비 {e['rr']} · 확신 {e['confidence']}% · 조건: {e['trigger']}")
    return "\n".join(lines)
