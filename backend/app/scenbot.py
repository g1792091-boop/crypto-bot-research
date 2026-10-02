"""시나리오 진입 봇 — 트레이드 화면의 시나리오 중 정책이 고른 것(기본: 확률이 가장 높은 것)으로 계속 진입하고, 결과로 배우고, 스스로 고친다.

- 진입: 코인 × 봉마다 새 봉이 나오면 시나리오를 다시 계산 → 정책(최소 확률·손익비·종류·메타 필터)으로 하나를 고른다
  → 보조지표 확인(파이썬 핵심 지표 · 터미널 147종 합의 · 내 차트에 켜 둔 지표) → 가상 주문(돌파는 역지정가, 눌림·박스는 지정가)
- 체결·청산: 손절 / 1차 목표 / 시간(48봉) — 과거 학습과 똑같은 규칙(삼중 장벽)
- 학습: 처음엔 과거 차트를 봉마다 다시 돌려 모든 시나리오를 채점(그림자 채점) → 실제 적중률 · 메타 모델.
  이후 새 봉도 계속 그림자 채점에 더하고, 6시간마다(또는 버튼) 정책을 walk-forward 로 다시 고른다. 나아질 때만 바꾸고 기록을 남긴다.
- 안전: freqtrade 식 보호 장치(연속 손절·낙폭·쿨다운)로 새 진입을 멈추고, 성적 급변(Page-Hinkley)이면 바로 다시 배운다.
  실거래는 기본 연결 안 됨 — 가상 성적이 기준을 넘으면 '실거래' 탭에 승인 대기로 올라가고, 사람이 승인해야 실거래 한도 안에서 따라 주문한다.
"""
from __future__ import annotations

import json
import threading
import time
import traceback

from . import config
from .data import market
from .quant import protect
from .quant import scenlearn as L

DEFAULT = {"enabled": True, "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"], "intervals": ["15m", "1h"], "follow_chart": True,
           "leverage": 5.0, "margin_pct": 10.0, "start_equity": 10_000.0, "max_open": 6, "learn_hours": 6, "history_bars": 3000,
           "use_termind": True, "use_chart": True}
INTERVALS = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d")
MAINT = 0.5               # 유지 증거금 % (청산가 계산)
PROMOTE = {"trades": 30, "pf": 1.2, "exp_r": 0.05, "max_dd_r": 15}
S: dict = {}
ST: dict = {"policy": dict(L.DEFAULT_POLICY), "history": [], "orders": [], "trades": [], "equity": None, "last_bar": {}, "replayed": {},
            "last_learn": 0.0, "last_report": None, "cal": None, "meta": None, "events": [], "skips": {}, "last_drift": 0.0, "status": {}}
SAMPLES: list[dict] = []
_lock = threading.RLock()
_th = {"t": None, "busy": False, "progress": "", "learn_t": None, "want": False}
MAX_SAMPLES = 40_000


def _p(name: str):
    return config.STATE_DIR / name


def load() -> None:
    S.clear()
    S.update(json.loads(json.dumps(DEFAULT)))
    try:
        d = json.loads(_p("scenbot.json").read_text(encoding="utf-8"))
        S.update({k: v for k, v in d.get("settings", {}).items() if k in DEFAULT})
        ST.update({k: v for k, v in d.get("state", {}).items() if k in ST})
    except (OSError, ValueError):
        pass
    try:
        SAMPLES[:] = json.loads(_p("scenbot_samples.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        SAMPLES[:] = []
    if ST.get("equity") is None:
        ST["equity"] = S["start_equity"]


def save(samples: bool = False) -> None:
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        st = {k: v for k, v in ST.items() if k not in ("cal",)}
        st["trades"] = ST["trades"][-3000:]
        st["events"] = ST["events"][-200:]
        _p("scenbot.json").write_text(json.dumps({"settings": S, "state": st}, ensure_ascii=False, default=float), encoding="utf-8")
        if samples:
            _p("scenbot_samples.json").write_text(json.dumps(SAMPLES[-MAX_SAMPLES:], ensure_ascii=False, default=float), encoding="utf-8")
    except OSError:
        pass


def event(text: str, kind: str = "info", **kw) -> None:
    ST["events"].append({"t": time.time(), "text": text, "kind": kind, **kw})
    del ST["events"][:-300]
    if kind in ("order", "close", "improve", "warn"):    # AI 사무실 진입 에이전트팀 방에도 남긴다
        try:
            from .office import engine as E
            from .office import roster
            if "entry_bot" in roster.TEAM_BY:
                E.post("entry_bot", "work", agent="entry_bot_0", icon="🤖", text=text[:300], src="시나리오 진입 봇")
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ 지표 확인
def _termind_check(sym: str, iv: str, c: list[dict], side: int, chart_keys: list[str]) -> dict:
    out = {}
    if not (S.get("use_termind") or (S.get("use_chart") and chart_keys)):
        return out
    try:
        from .quant import termind
        ok, _ = termind.available()
        if not ok:
            return out
        a = termind.analyze(c[-500:], termind.ext_for(sym, iv))
    except Exception:  # noqa: BLE001
        return out
    if S.get("use_termind"):
        out["termind"] = {"score": a["score"] * side, "label": a["label"], "voters": a["voters"]}
    if S.get("use_chart") and chart_keys:
        vs = [(k, a["votes"][k]) for k in chart_keys if k in a.get("votes", {})]
        if vs:
            sc = sum(v for _, v in vs) / len(vs) * side
            out["chart"] = {"score": round(sc * 100), "n": len(vs),
                            "detail": [{"name": a["names"].get(k, k), "vote": round(v * side, 2)} for k, v in vs][:12]}
    return out


def _chart_keys(sym: str) -> list[str]:
    try:
        from . import autopilot
        ctx = autopilot.context
        if ctx.get("symbol") == sym or not ctx.get("symbol"):
            return [x["key"] for x in ctx.get("indicators", []) if x.get("key")]
        return [x["key"] for x in ctx.get("indicators", []) if x.get("key")]
    except Exception:  # noqa: BLE001
        return []


# 종류별 막는 기준 — 박스권·눌림목은 원래 '지금 추세와 반대쪽'에서 들어가므로 추세 지표 합의가 아주 강하게 반대일 때만 막는다
BLOCK = {"breakout": {"py": -3, "py_n": 4, "termind": -35, "chart": -40},
         "pullback": {"py": -2, "py_n": 2, "termind": -50, "chart": -55},
         "range": {"py": -2, "py_n": 2, "termind": -75, "chart": -85}}


def checks(sym: str, iv: str, c: list[dict], st: dict) -> dict:
    """진입 전에 보조지표가 진입 방향과 크게 엇갈리면 막는다 (시나리오 종류별 기준). 결과는 주문 기록에 남는다."""
    kind = st.get("kind") if st.get("kind") in BLOCK else "breakout"
    lim = BLOCK[kind]
    py = L.indicator_votes(c, st["side"], kind)
    out = {"python": py, **_termind_check(sym, iv, c, st["side"], _chart_keys(sym))}
    why = []
    if py["n"] >= lim["py_n"] and py["score"] <= lim["py"]:
        why.append(f"핵심 지표 {py['n']}개 중 대부분이 반대 ({', '.join(k for k, v in py['votes'].items() if v < 0)})")
    t = out.get("termind")
    if t and t["score"] <= lim["termind"]:
        why.append(f"터미널 지표 147종 합의가 강하게 반대 ({t['score']:+d} · 기준 {lim['termind']})")
    ch = out.get("chart")
    if ch and ch["n"] >= 2 and ch["score"] <= lim["chart"]:
        why.append(f"내 차트 지표 {ch['n']}개 합의가 강하게 반대 ({ch['score']:+d} · 기준 {lim['chart']})")
    out["block"] = " · ".join(why) or None
    return out


# ------------------------------------------------------------------ 주문 · 체결 · 청산
def _bars_after(c: list[dict], t: int) -> list[dict]:
    return [b for b in c if b["time"] > t]


def liq_price(side: int, entry: float, lev: float) -> float:
    """격리 증거금 청산가 (대략): 레버리지 L 이면 1/L 에서 유지 증거금만큼 덜 움직이면 청산."""
    d = 1 / lev - MAINT / 100
    return entry * (1 - d) if side > 0 else entry * (1 + d)


def size(entry: float) -> dict:
    """내가 정한 레버리지 × 증거금 비율로 주문 크기 (가상 자산 기준)."""
    lev = max(1.0, min(20.0, float(S["leverage"])))
    margin = max(0.0, ST["equity"]) * S["margin_pct"] / 100
    notional = margin * lev
    return {"lev": lev, "margin": round(margin, 2), "notional": round(notional, 2), "qty": notional / entry if entry else 0.0}


def pairs() -> list[tuple[str, str]]:
    """봇이 판단할 (코인, 봉). '내 차트 따라가기' 면 지금 보고 있는 차트의 분봉으로 (그 코인도 포함)."""
    syms, ivs = list(S["symbols"]), list(S["intervals"])
    if S.get("follow_chart"):
        try:
            from . import autopilot
            ctx = autopilot.context
            if ctx.get("interval") in INTERVALS:
                ivs = [ctx["interval"]]
            if ctx.get("symbol") and ctx["symbol"] not in syms:
                syms.append(ctx["symbol"])
        except Exception:  # noqa: BLE001
            pass
    return [(s_, i_) for s_ in syms for i_ in ivs]


def _chart_pair() -> tuple[str, str] | None:
    try:
        from . import autopilot
        ctx = autopilot.context
        return (ctx["symbol"], ctx["interval"]) if ctx.get("symbol") and ctx.get("interval") else None
    except Exception:  # noqa: BLE001
        return None


def _status(sym: str, iv: str, text: str, c: list[dict] | None = None) -> None:
    last = c[-1]["time"] if c else ST["last_bar"].get(f"{sym}|{iv}")
    nxt = last + 2 * L._bar_sec(iv) if last else None      # 진행 중 봉이 마감되면 다음 판단
    ST["status"][f"{sym}|{iv}"] = {"t": time.time(), "text": text, "next": nxt}


def update_orders(sym: str, iv: str, c: list[dict]) -> None:
    keep = []
    for o in ST["orders"]:
        if o["symbol"] != sym or o["interval"] != iv:
            keep.append(o)
            continue
        fut = _bars_after(c, o["bar_time"])
        res = L.simulate(o, fut)
        if not res["filled"] and res["exit"] == "expired" and len(fut) < L.EXPIRE:
            keep.append(o)                            # 아직 대기 중
            continue
        if res["exit"] == "open":
            if o["status"] != "open":
                o["status"] = "open"
                o["filled_at"] = fut[res.get("fill_bar", 0)]["time"] if fut else int(time.time())
                event(f"✅ 체결 {sym} {iv} {'롱' if o['side'] > 0 else '숏'} {o['title']} @ {o['entry']:.6g} · {o['lev']:g}배 · 증거금 {o['margin']:,.2f} "
                      f"(손절 {o['stop']:.6g} · 목표 {o['tp']:.6g} · 청산가 {o['liq']:.6g})", "fill", oid=o["id"])
            mark(o, c[-1]["close"])
            keep.append(o)
            continue
        _close(o, res, fut)
    ST["orders"] = keep


def mark(o: dict, px: float) -> None:
    """보유 중 포지션의 실시간 손익 (수수료 반영 · 증거금 대비 수익률 ROE)."""
    if o.get("status") != "open" or not px:
        return
    gross = o["side"] * (px - o["entry"]) * o["qty"]
    fee = L.FEE_PCT / 100 * o["notional"] * 2
    o["mark"], o["upnl"] = px, round(gross - fee, 2)
    o["roe_pct"] = round(o["upnl"] / o["margin"] * 100, 2) if o["margin"] else 0.0
    o["r_now"] = round(o["side"] * (px - o["entry"]) / abs(o["entry"] - o["stop"]), 2) if o["entry"] != o["stop"] else 0.0
    o["mark_t"] = time.time()


def _close(o: dict, res: dict, fut: list[dict]) -> None:
    pnl = 0.0
    if res["filled"]:
        px = res.get("px", o["entry"])
        pnl = o["side"] * (px - o["entry"]) * o["qty"] - L.FEE_PCT / 100 * o["notional"] * 2
    ST["equity"] += pnl
    fb = res.get("fill_bar")
    t_in = fut[fb]["time"] if res["filled"] and fb is not None and fb < len(fut) else None
    xi = (fb or 0) + res.get("bars", 1) - 1
    t_out = fut[xi]["time"] if res["filled"] and xi < len(fut) else int(time.time())
    tr = {**{k: o[k] for k in ("id", "symbol", "interval", "key", "title", "kind", "side", "prob", "rr", "entry", "stop", "tp", "state",
                              "policy_v", "meta_p", "learned", "checks_brief", "bar_time", "lev", "margin", "notional", "liq")},
          "filled": res["filled"], "exit": res["exit"], "r": res["r"], "pnl": round(pnl, 2), "won": res.get("won"), "closed": int(time.time()),
          "entry_time": t_in, "exit_time": t_out, "exit_px": res.get("px"), "roe_pct": round(pnl / o["margin"] * 100, 2) if o["margin"] and res["filled"] else 0.0,
          "equity_after": round(ST["equity"], 2)}
    ST["trades"].append(tr)
    # 실제 진입 결과도 학습 표본으로 (그림자 채점과 겹치지 않게 src=live)
    SAMPLES.append({"t": o["bar_time"], "symbol": o["symbol"], "interval": o["interval"], "key": o["key"], "title": o["title"], "kind": o["kind"],
                    "side": o["side"], "prob": o["prob"], "rr": o["rr"], "state": o["state"], "top": True, "f": o["f"], **res, "src": "live"})
    if res["filled"]:
        icon = "🎯" if res["exit"] == "target" else "🛑" if res["exit"] == "stop" else "⏱"
        event(f"{icon} {o['symbol']} {o['interval']} {o['title']} {('익절' if res['exit'] == 'target' else '손절' if res['exit'] == 'stop' else '시간 청산')} "
              f"{res['r']:+.2f}R · {tr['roe_pct']:+.2f}% ({pnl:+.2f}) · {o['lev']:g}배 · 가상 자산 {ST['equity']:,.2f}", "close", oid=o["id"])
    else:
        event(f"⌛ {o['symbol']} {o['interval']} {o['title']} 미체결 취소 ({L.EXPIRE}봉)", "expire", oid=o["id"])


def _protected(sym: str) -> str | None:
    class T:  # protect.check 는 pnl · exit_time 만 본다
        def __init__(self, d):
            self.pnl, self.exit_time = d["pnl"], d["exit_time"]
    trs = [T(t) for t in ST["trades"] if t["symbol"] == sym and t["filled"]]
    g = protect.check(trs, S["start_equity"])
    return g["reason"] if g["blocked"] else None


def decide(sym: str, iv: str, c: list[dict]) -> dict | None:
    """새 봉에서 정책대로 시나리오 하나를 골라 가상 주문을 낸다."""
    if any(o["symbol"] == sym and o["interval"] == iv for o in ST["orders"]):
        _status(sym, iv, "이미 주문·포지션이 있어 끝날 때까지 기다림", c)
        return None
    if len(ST["orders"]) >= S["max_open"] and (sym, iv) != _chart_pair():      # 지금 보고 있는 차트는 한도와 별도로 한 자리
        _status(sym, iv, f"동시 주문 한도({S['max_open']}개) — 다른 주문이 끝나면 다시 판단", c)
        return None
    w = c[-L.WINDOW:]
    from . import analysis
    reg = analysis.regime(w)
    sts = L.setups(w, reg)
    if not sts:
        _status(sym, iv, "지금 봉에서는 시나리오가 만들어지지 않음", c)
        return None
    for s in sts:
        s["f"] = L.features(s, reg, w)
        s["interval"] = iv
    pol, cal, meta = ST["policy"], ST.get("cal"), ST.get("meta")
    ranked = L.rank(sts, pol, cal, meta)
    if not ranked:
        _status(sym, iv, "정책 조건에 맞는 시나리오 없음 — " + L.why_not(sts, pol), c)
        return None
    guard = _protected(sym)
    if guard:
        _note_skip(sym, iv, ranked[0], f"보호 장치: {guard}")
        return None
    skipped, s, ck, sz, liq = [], None, None, None, None
    for i, cand in enumerate(ranked, 1):
        odd = L.unfamiliar(meta, cand["f"])
        if odd:
            skipped.append((i, cand, f"낯선 상황: {odd}"))
            continue
        k_ = checks(sym, iv, c, cand) if pol.get("indicator_check", True) else {"block": None}
        if k_.get("block"):
            skipped.append((i, cand, f"지표 반대: {k_['block']}"))
            continue
        z_ = size(cand["entry"])
        lq = liq_price(cand["side"], cand["entry"], z_["lev"])
        if (cand["side"] > 0 and lq >= cand["stop"]) or (cand["side"] < 0 and lq <= cand["stop"]):
            skipped.append((i, cand, f"레버리지 {z_['lev']:g}배면 청산가 {lq:.6g} 가 손절가 {cand['stop']:.6g} 보다 먼저 닿음 — 레버리지를 낮추세요"))
            continue
        s, ck, sz, liq = cand, k_, z_, lq
        break
    skip_txt = " → ".join(f"{i}순위 {x['title']}({x['prob']}%) 건너뜀: {w}" for i, x, w in skipped)
    if s is None:
        _note_skip(sym, iv, ranked[0], skip_txt + (" · 정책 통과 시나리오가 모두 막힘" if len(ranked) > 1 else ""))
        return None
    lv = L.learned(cal or {}, s["key"], s["state"], iv)
    o = {**{k: s[k] for k in ("key", "title", "kind", "side", "prob", "rr", "entry", "stop", "tp", "order", "state", "trigger", "f")},
         "id": f"sb{int(time.time() * 1000)}{len(ST['trades']) % 97}", "symbol": sym, "interval": iv, "bar_time": w[-1]["time"], "placed": int(time.time()),
         "status": "pending", **sz, "liq": liq, "policy_v": pol.get("version", 1), "meta_p": L.meta_prob(meta, s["f"]),
         "learned": lv, "checks": {k: v for k, v in ck.items() if k != "block"},
         "checks_brief": _brief(ck), "rank_i": ranked.index(s) + 1, "skipped": skip_txt or None}
    ST["orders"].append(o)
    stop_pct = abs(o["entry"] - o["stop"]) / o["entry"] * 100
    event(f"📝 {sym} {iv} {'롱' if o['side'] > 0 else '숏'} {o['title']} 주문 ({'역지정가' if o['order'] == 'stop' else '지정가'} {o['entry']:.6g} · 손절 {o['stop']:.6g} · "
          f"목표 {o['tp']:.6g} · {sz['lev']:g}배 · 증거금 {sz['margin']:,.2f} · 손절 시 증거금의 -{stop_pct * sz['lev']:.1f}% · 화면 {o['prob']}% · "
          f"배운 적중률 {lv['win'] if lv else '-'}% · 손익비 {o['rr']}) {o['checks_brief']}" + (f" · ({skip_txt})" if skip_txt else ""), "order", oid=o["id"])
    _status(sym, iv, (skip_txt + " → " if skip_txt else "") + f"📝 {o['rank_i']}순위 주문: {'롱' if o['side'] > 0 else '숏'} {o['title']}({o['prob']}%) "
            f"{'역지정가' if o['order'] == 'stop' else '지정가'} {o['entry']:.6g} · {sz['lev']:g}배", c)
    return o


def _brief(ck: dict) -> str:
    parts = []
    if ck.get("python"):
        parts.append(f"핵심지표 {ck['python']['score']:+d}/{ck['python']['n']}")
    if ck.get("termind"):
        parts.append(f"147종 {ck['termind']['score']:+d}")
    if ck.get("chart"):
        parts.append(f"내 차트 {ck['chart']['score']:+d}({ck['chart']['n']}개)")
    return "· 지표 " + " · ".join(parts) if parts else ""


def _note_skip(sym, iv, s, why):
    k = f"{sym}|{iv}"
    _status(sym, iv, f"⏸ {s['title']}({s['prob']}%) 건너뜀 — {why}" if not why.startswith("1순위") else f"⏸ {why}")
    last = ST.setdefault("skips", {}).get(k)
    if last != why:
        ST["skips"][k] = why
        event(f"⏸ {sym} {iv} " + (why if why.startswith("1순위") else f"{s['title']}({s['prob']}%) 건너뜀 — {why}"), "skip")


# ------------------------------------------------------------------ 학습
def _replay(sym: str, iv: str, c: list[dict]) -> int:
    key = f"{sym}|{iv}"
    last_t = ST["replayed"].get(key, 0)
    idx = next((i for i, b in enumerate(c) if b["time"] > last_t), len(c)) if last_t else 0
    # 끝난 표본만: 마지막 EXPIRE+MAX_HOLD 봉은 결과가 안 나왔을 수 있으니 replay 가 알아서 뺀다
    new = L.replay(c, sym, iv, stride=2, start=max(L.WINDOW, idx))
    done = [s for s in new if s["exit"] != "open"]
    horizon = c[-1]["time"] - (L.EXPIRE + L.MAX_HOLD) * L._bar_sec(iv)
    done = [s for s in done if s["t"] <= horizon]
    if done:
        SAMPLES.extend(done)
        ST["replayed"][key] = max(s["t"] for s in done)
    del SAMPLES[:-MAX_SAMPLES]
    return len(done)


def learn(force: bool = False) -> dict:
    """그림자 채점 표본을 늘리고, 보정·메타 모델을 다시 만들고, 정책을 walk-forward 로 다시 고른다."""
    if _th["busy"]:
        return {"busy": True}
    _th["busy"] = True
    try:
        added = 0
        ch = _chart_pair()
        ps = sorted(pairs(), key=lambda p: p != ch)          # 지금 보고 있는 차트부터 배운다
        for i, (sym, iv) in enumerate(ps, 1):
            _th["progress"] = f"과거 차트 그림자 채점 {i}/{len(ps)} ({sym.removesuffix('USDT')} {iv})"
            try:
                c, _ = market.candles(sym, iv, S["history_bars"])
                added += _replay(sym, iv, c)
                with _lock:
                    ST["cal"] = L.calibration(SAMPLES)       # 코인 하나 끝날 때마다 '배운 실제 적중률' 을 바로 화면에
            except Exception as e:  # noqa: BLE001
                event(f"⚠ {sym} {iv} 과거 데이터 실패: {str(e)[:80]}", "warn")
        _th["progress"] = "실제 적중률 보정 · 메타 모델 · 정책 재선정 중"
        snap = list(SAMPLES)                              # 무거운 계산은 잠금 밖에서 (그동안에도 봇은 판단·체결 관리)
        cal = L.calibration(snap)
        meta = L.meta_fit(snap)
        old = dict(ST["policy"])
        rep = L.optimize(snap, old)
        with _lock:
            ST["cal"] = cal
            ST["meta"] = meta if meta.get("ok") else None
            ST["last_report"] = {k: v for k, v in rep.items() if k not in ("policy",)}
            if rep.get("adopt"):
                ST["policy"] = rep["policy"]
                ST["history"].append({"t": time.time(), "from": old, "to": rep["policy"], "why": rep["why"], "test": rep.get("test")})
                event(f"🔧 정책 개선 v{old.get('version', 1)} → v{rep['policy']['version']}: {rep['why']}", "improve")
            else:
                event(f"🔍 학습 완료 (표본 {len(SAMPLES):,} · 새로 {added:,}) — {rep['why']}", "learn")
            ST["last_learn"] = time.time()
            save(samples=True)
        return {"added": added, "samples": len(SAMPLES), **ST["last_report"]}
    finally:
        _th["busy"] = False
        _th["progress"] = ""


def learn_bg() -> bool:
    """학습은 뒤에서 — 그동안에도 봇은 지금 정책으로 계속 판단·진입한다."""
    if _th["busy"] or (_th["learn_t"] and _th["learn_t"].is_alive()):
        return False
    _th["learn_t"] = threading.Thread(target=lambda: _safe(learn), daemon=True, name="scenbot-learn")
    _th["learn_t"].start()
    return True


def _safe(fn):
    try:
        fn()
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def revert(version: int) -> dict:
    h = next((x for x in reversed(ST["history"]) if x["from"].get("version") == version or x["to"].get("version") == version), None)
    pol = (h["from"] if h and h["from"].get("version") == version else h["to"]) if h else (dict(L.DEFAULT_POLICY) if version == 1 else None)
    if not pol:
        raise ValueError("그 버전 기록이 없습니다")
    old = ST["policy"]
    ST["policy"] = {**pol}
    ST["history"].append({"t": time.time(), "from": old, "to": ST["policy"], "why": f"사람이 v{version} 으로 되돌림", "test": None})
    event(f"↩ 정책을 v{version} 으로 되돌렸습니다", "improve")
    save()
    return ST["policy"]


# ------------------------------------------------------------------ 반복
def tick() -> None:
    ch = _chart_pair()
    active = sorted(pairs(), key=lambda p: p != ch)       # 보고 있는 차트부터
    held = {(o["symbol"], o["interval"]) for o in ST["orders"]}
    for sym, iv in list(dict.fromkeys(active + sorted(held))):
        try:
            c, _ = market.candles(sym, iv, 600)
        except Exception as e:  # noqa: BLE001
            _status(sym, iv, f"⚠ 시세를 받지 못함: {str(e)[:60]}")
            continue
        if len(c) < L.WINDOW + 5:
            _status(sym, iv, f"봉이 부족함 ({len(c)}개 · {L.WINDOW + 5}개 필요)")
            continue
        with _lock:
            update_orders(sym, iv, c)                     # 차트 분봉을 바꿔도 이미 낸 주문은 끝까지 관리
            if not S.get("enabled") or (sym, iv) not in active:
                continue
            closed = c[:-1]                              # 판단은 마감된 봉으로
            k = f"{sym}|{iv}"
            if ST["last_bar"].get(k) != closed[-1]["time"]:
                ST["last_bar"][k] = closed[-1]["time"]
                decide(sym, iv, closed)
    _drift_check()
    save()


def _drift_check() -> None:
    rs = [t["r"] for t in ST["trades"][-60:] if t["filled"]]
    d = L.page_hinkley(rs)
    if d["drift"] and time.time() - ST.get("last_drift", 0) > 6 * 3600:
        ST["last_drift"] = time.time()
        event("📉 최근 성적이 갑자기 나빠졌습니다 (급변 감지) → 바로 다시 학습합니다", "warn")
        learn_bg()


def _loop() -> None:
    time.sleep(5)
    seen_pairs = set()
    while True:
        try:
            tick()                                      # 학습을 기다리지 않고 바로 판단·진입
            ps = set(pairs())
            if seen_pairs and not ps <= seen_pairs:       # 차트 분봉을 바꾸면 그 분봉도 바로 배운다 (학습 중이면 끝나고 이어서)
                _th["want"] = True
            seen_pairs |= ps
            if not SAMPLES or _th.get("want") or time.time() - ST.get("last_learn", 0) > S["learn_hours"] * 3600:
                if learn_bg():
                    _th["want"] = False
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        time.sleep(15)


def start() -> None:
    load()
    if _th["t"] is None:
        _th["t"] = threading.Thread(target=_loop, daemon=True, name="scenbot")
        _th["t"].start()


def set_settings(body: dict) -> dict:
    for k, v in body.items():
        if k not in DEFAULT or v is None:
            continue
        if k in ("symbols", "intervals"):
            v = [str(x).upper() if k == "symbols" else str(x) for x in v][:12]
            if k == "intervals":
                v = [x for x in v if x in INTERVALS] or ["1h"]
        elif isinstance(DEFAULT[k], bool):
            v = bool(v)
        else:
            v = type(DEFAULT[k])(v)
        S[k] = v
    S["leverage"] = max(1.0, min(20.0, float(S["leverage"])))
    S["margin_pct"] = max(1.0, min(100.0, float(S["margin_pct"])))
    if "leverage" in body or "margin_pct" in body:
        event(f"⚙ 레버리지 {S['leverage']:g}배 · 주문당 증거금 가상 자산의 {S['margin_pct']:g}% (다음 주문부터)", "info")
    save()
    return dict(S)


# ------------------------------------------------------------------ 성적 · 실거래 후보 · 화면
def stats() -> dict:
    tr = [t for t in ST["trades"] if t["filled"]]
    s = L.stats([t["r"] for t in tr])
    s["equity"] = round(ST["equity"], 2)
    s["return_pct"] = round((ST["equity"] / S["start_equity"] - 1) * 100, 2)
    up = sum(o.get("upnl") or 0 for o in ST["orders"] if o.get("status") == "open")
    s["upnl"] = round(up, 2)
    s["equity_live"] = round(ST["equity"] + up, 2)
    s["return_live_pct"] = round(((ST["equity"] + up) / S["start_equity"] - 1) * 100, 2)
    s["pnl"] = round(sum(t["pnl"] for t in tr), 2)
    s["expired"] = sum(1 for t in ST["trades"] if not t["filled"])
    by = {}
    for t in tr:
        by.setdefault(t["title"], []).append(t["r"])
    s["by_title"] = {k: L.stats(v) for k, v in by.items()}
    return s


def candidate() -> dict:
    s = stats()
    ok = (s["n"] >= PROMOTE["trades"] and (s["pf"] or 0) >= PROMOTE["pf"] and (s["exp_r"] or -1) >= PROMOTE["exp_r"] and s["max_dd_r"] <= PROMOTE["max_dd_r"])
    need = (f"가상 거래 {PROMOTE['trades']}건 이상 · 손익비 {PROMOTE['pf']} 이상 · 거래당 기대값 +{PROMOTE['exp_r']}R 이상 · 최대 낙폭 {PROMOTE['max_dd_r']}R 이하 "
            f"(지금 {s['n']}건 · 손익비 {s['pf'] if s['pf'] is not None else '-'} · 기대값 {s['exp_r'] if s['exp_r'] is not None else '-'} · 낙폭 {s['max_dd_r']}R)")
    return {"ok": ok, "need": need}


def live_items() -> list[dict]:
    """실거래 탭에 올릴 항목 (코인마다 하나) — 가상 성적이 기준을 넘었을 때만."""
    if not candidate()["ok"]:
        return []
    from . import live as livex
    out = []
    for sym in S["symbols"]:
        pos = [o for o in ST["orders"] if o["symbol"] == sym and o["status"] == "open"]
        sides = {o["side"] for o in pos}
        side = sides.pop() if len(sides) == 1 else 0
        price = None
        try:
            price = market.candles(sym, "1m", 2)[0][-1]["close"]
        except Exception:  # noqa: BLE001
            pass
        lev = max(1, min(int(livex.S.get("max_leverage", 5)), int(S["leverage"])))       # 내가 정한 레버리지 · 실거래 한도가 우선
        pid = f"sb:{sym}"
        out.append({"id": pid, "name": f"시나리오 진입 봇 · {sym.removesuffix('USDT')}", "symbol": sym, "side": side, "price": price, "leverage": lev,
                    "custom": False, "stage": "live" if pid in livex.S.get("approved", {}) else "candidate", "demo": None,
                    "approved": pid in livex.S.get("approved", {}), "blocked": _protected(sym), "bot": True})
    return out


def annotate(a: dict) -> dict:
    """트레이드 화면 시나리오 패널에: 각 시나리오의 '배운 실제 적중률·평균 R' 과 봇 주문 상태."""
    cal = ST.get("cal") or {}
    st = a.get("regime", {}).get("state")
    for s in a.get("scenarios", []):
        lv = L.learned(cal, s["key"], st, a.get("interval", "1h"))
        s["learned"] = lv
    a["bot"] = {**_brain(a.get("symbol"), a.get("interval", "1h")), "policy_v": ST["policy"].get("version", 1),
                "orders": [{k: o.get(k) for k in ("title", "side", "entry", "stop", "tp", "status", "interval", "prob", "lev", "roe_pct", "upnl")}
                           for o in ST["orders"] if o["symbol"] == a.get("symbol")]}
    return a


def refresh_marks() -> None:
    """화면을 볼 때마다 보유 포지션 손익을 최신 가격으로 (봇 반복 주기 15초를 기다리지 않게)."""
    syms = sorted({o["symbol"] for o in ST["orders"] if o.get("status") == "open"})
    if not syms:
        return
    try:
        px = {r["symbol"]: r["price"] for r in market.tickers(syms)[0]}
    except Exception:  # noqa: BLE001
        return
    for o in ST["orders"]:
        if o.get("status") == "open" and px.get(o["symbol"]):
            mark(o, px[o["symbol"]])


def chart(symbol: str, interval: str) -> dict:
    """트레이드 차트용: 이 코인의 봇 주문·포지션(실시간 손익)과 지난 진입·청산."""
    refresh_marks()
    keys = ("id", "interval", "title", "side", "entry", "stop", "tp", "status", "prob", "lev", "margin", "liq", "order", "bar_time", "filled_at",
            "mark", "upnl", "roe_pct", "r_now")
    orders = [{k: o.get(k) for k in keys} for o in ST["orders"] if o["symbol"] == symbol]
    trades = [{k: t.get(k) for k in ("interval", "title", "side", "entry", "exit_px", "entry_time", "exit_time", "exit", "r", "pnl", "roe_pct", "lev", "prob")}
              for t in ST["trades"][-400:] if t["symbol"] == symbol and t["filled"] and t.get("entry_time")]
    return {"symbol": symbol, "interval": interval, "orders": orders, "trades": trades[-80:], **_brain(symbol, interval), "stats": stats()}


def _brain(symbol: str, interval: str) -> dict:
    """화면에 늘 보여 줄 봇 상태: 켜짐 · 이 차트를 보고 있는지 · 마지막 판단 · 다음 판단 · 학습 진행."""
    cal = ST.get("cal") or {}
    return {"enabled": S.get("enabled"), "active": (symbol, interval) in pairs(), "status": ST["status"].get(f"{symbol}|{interval}"),
            "learning": _th["busy"], "progress": _th["progress"], "last_learn": ST.get("last_learn"), "samples": len(SAMPLES),
            "cal_n": cal.get("n", 0), "lev": S["leverage"], "running": bool(_th["t"] and _th["t"].is_alive()),
            "pairs": [f"{a.removesuffix('USDT')} {b}" for a, b in pairs()]}


def view() -> dict:
    refresh_marks()
    cal = ST.get("cal") or {}
    meta = ST.get("meta") or {}
    hist = sum(1 for s in SAMPLES if s.get("src") == "history")
    return {"settings": S, "policy": ST["policy"], "history": ST["history"][-20:][::-1], "orders": ST["orders"], "trades": ST["trades"][-60:][::-1],
            "stats": stats(), "candidate": candidate(), "events": ST["events"][-80:][::-1], "report": ST.get("last_report"),
            "calibration": cal, "meta": {k: meta.get(k) for k in ("ok", "useful", "auc", "se", "n", "test_n", "weights")} if meta else None,
            "samples": {"total": len(SAMPLES), "history": hist, "live": len(SAMPLES) - hist}, "last_learn": ST.get("last_learn"),
            "next_learn": (ST.get("last_learn") or 0) + S["learn_hours"] * 3600, "busy": _th["busy"], "progress": _th["progress"],
            "pairs": [{"symbol": a, "interval": b, **(ST["status"].get(f"{a}|{b}") or {})} for a, b in pairs()]}


def text() -> str:
    v = view()
    s, p, cal = v["stats"], v["policy"], v["calibration"] or {}
    f = lambda x, suf="": "-" if x is None else f"{x}{suf}"  # noqa: E731
    lines = [f"[시나리오 진입 봇] 정책 v{p.get('version', 1)}: {p.get('why', '')}",
             f"- 가상 성적: 거래 {s['n']}건 · 승률 {f(s['win'], '%')} · 거래당 {f(s['exp_r'], 'R')} · 손익비 {f(s['pf'])} · 최대 낙폭 {s['max_dd_r']}R · "
             f"가상 자산 {s['equity']:,} ({s['return_pct']:+.2f}%)",
             f"- 학습 표본 {v['samples']['total']:,}건 (과거 그림자 채점 {v['samples']['history']:,} · 실시간 {v['samples']['live']:,}) · 체결률 {cal.get('fill_rate')}%"]
    for k, x in (cal.get("keys") or {}).items():
        lines.append(f"  · {k}: 실제 적중 {x['win']}% · 평균 {x['avg_r']:+.3f}R ({x['n']}건)")
    m = v["meta"]
    if m:
        lines.append(f"- 메타 모델(할까 말까): 검증 AUC {m['auc']} (±{m['se']}) → {'쓸 만함' if m['useful'] else '아직 우연과 구분 안 됨'}")
    if v["report"]:
        lines.append(f"- 마지막 개선 판단: {v['report'].get('why', '')}")
    lines.append(f"- 실거래 후보: {'예 (실거래 탭에서 사람 승인 필요)' if v['candidate']['ok'] else '아니오 — ' + v['candidate']['need']}")
    lines.append(f"- 열린 주문/포지션 {len(v['orders'])}개")
    return "\n".join(lines)


load()
