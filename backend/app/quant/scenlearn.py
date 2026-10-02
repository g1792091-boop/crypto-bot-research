"""시나리오 진입 봇의 학습 엔진 — 화면의 시나리오(확률·진입·손절·목표)를 실제 결과로 배운다.

1. 과거 재생: 과거 차트의 봉마다 같은 시나리오 엔진(analysis.scenarios)을 그때까지의 봉만으로 다시 돌리고,
   그 뒤 봉으로 진입 체결 → 손절/1차 목표/시간 청산 중 무엇이 먼저였는지(삼중 장벽 라벨) 채점한다. 미래 봉은 판단에 쓰지 않는다.
2. 보정: 시나리오 종류 × 장세 × 봉마다 실제 적중률·평균 R (표본이 적으면 전체 평균 쪽으로 당기는 베이즈 축소).
3. 메타 라벨: '이 시나리오를 할까 말까'를 판단하는 2차 모델(로지스틱 회귀). 시간 순서로 나눈 검증에서 AUC 가 의미 있을 때만 쓴다.
4. 정책 자동 개선: 최소 확률·최소 손익비·순위 방식(화면 % / 배운 기대값)·메타 필터 조합을 앞 70% 로 고르고
   뒤 30% 에서 지금 정책보다 나을 때만 바꾼다 (walk-forward). 표본이 모자라면 바꾸지 않는다.

열린 소스 참고(코드 복사 없이 개념만 재구현): López de Prado 의 삼중 장벽·메타 라벨, freqtrade 하이퍼옵트+walk-forward,
qlib 의 기간 굴림 재학습, 베이즈 축소 보정.
"""
from __future__ import annotations

import math
import random
import time

import numpy as np

from .. import analysis
from .. import indicators as ind

WINDOW = 400          # 시나리오 판단에 쓰는 과거 봉 수
EXPIRE = 12           # 진입 대기 봉 수 (안 닿으면 취소)
MAX_HOLD = 48         # 진입 뒤 최대 보유 봉 수 (시간 장벽)
FEE_PCT = 0.05        # 편도 수수료+슬리피지 % (왕복 두 번 뺀다)
SHRINK = 20           # 베이즈 축소 강도 (표본 20건이면 절반은 전체 평균)
KINDS = {"눌림목 롱": "pullback", "반등 숏": "pullback", "저항 돌파 롱": "breakout", "지지 이탈 숏": "breakout", "박스권 양방향": "range"}
FEATS = ["prob", "rr", "score_al", "adx", "er", "rsi_al", "squeeze", "dist_atr", "breakout", "pullback", "range", "state_match", "vol_z"]
FEAT_KO = {"prob": "화면 확률", "rr": "손익비", "score_al": "추세 점수(진입 방향)", "adx": "ADX", "er": "효율비", "rsi_al": "RSI(진입 방향)",
           "squeeze": "밴드 수축 순위", "dist_atr": "진입가 거리(ATR)", "breakout": "돌파형", "pullback": "눌림형", "range": "박스형",
           "state_match": "장세와 방향 일치", "vol_z": "거래량 충격"}


# ------------------------------------------------------------------ 시나리오 → 실제 주문
def setups(c: list[dict], reg: dict | None = None, liq: dict | None = None) -> list[dict]:
    """시나리오 엔진 결과를 체결 가능한 주문(방향·진입·손절·1차 목표)으로. 박스권은 지금 가격에 가까운 쪽 한 방향만."""
    reg = reg or analysis.regime(c)
    sc = analysis.scenarios(c, reg, liq)["scenarios"]
    px, atr = reg["price"], reg["atr"]
    out = []
    for s in sc:
        if s["key"] == "range":
            mid = (s["targets"][0])
            leg = s if px <= mid else {**s["alt"]}
            side = 1 if px <= mid else -1
            entry, stop, tps = leg["entry"], leg["stop"], leg["targets"]
            # 박스형 1차 목표는 박스 반대편(2차) — 중간값은 손익비가 너무 작다
            tp = tps[1] if abs(tps[1] - entry) > abs(tps[0] - entry) else tps[0]
        else:
            side = 1 if s["bias"] == "long" else -1
            entry, stop, tp = s["entry"], s["stop"], s["targets"][0]
        risk = abs(entry - stop)
        if risk <= 0 or side * (tp - entry) <= 0:
            continue
        out.append({"key": s["key"], "title": s["title"], "kind": KINDS.get(s["title"], s["key"]), "side": side, "prob": s["probability"],
                    "entry": entry, "stop": stop, "tp": tp, "rr": round(abs(tp - entry) / risk, 2), "trigger": s.get("trigger", ""),
                    "order": "stop" if side * (entry - px) > 0 else "limit", "state": reg["state"]})
    return out


def features(st: dict, reg: dict, c: list[dict]) -> dict:
    side, atr, px = st["side"], reg["atr"] or 1e-9, reg["price"]
    vols = [b["volume"] for b in c[-60:]]
    m = sum(vols) / len(vols) if vols else 0
    sd = (sum((v - m) ** 2 for v in vols) / len(vols)) ** 0.5 if vols else 0
    return {"prob": st["prob"] / 100, "rr": min(st["rr"], 6) / 6, "score_al": side * reg["score"] / 100, "adx": min(reg["adx"], 60) / 60,
            "er": reg["er"], "rsi_al": side * (reg["rsi"] - 50) / 50, "squeeze": reg["squeeze_rank"] / 100,
            "dist_atr": min(abs(st["entry"] - px) / atr, 6) / 6, "breakout": float(st["kind"] == "breakout"),
            "pullback": float(st["kind"] == "pullback"), "range": float(st["kind"] == "range"),
            "state_match": float((reg["state"] == "long" and side > 0) or (reg["state"] == "short" and side < 0) or reg["state"] == "range" and st["kind"] == "range"),
            "vol_z": max(-3, min(3, (vols[-1] - m) / sd)) / 3 if sd else 0.0}


def simulate(st: dict, future: list[dict], expire: int = EXPIRE, max_hold: int = MAX_HOLD, fee_pct: float = FEE_PCT) -> dict:
    """삼중 장벽 채점: 진입 대기(expire 봉) → 체결되면 손절 / 1차 목표 / 시간(max_hold 봉) 중 먼저 닿는 것.
    같은 봉에 손절·목표가 다 닿으면 손절로 본다(보수적). 갭으로 손절가를 넘으면 시가에 손절."""
    side, entry, stop, tp = st["side"], st["entry"], st["stop"], st["tp"]
    risk = abs(entry - stop)
    cost_r = 2 * fee_pct / 100 * entry / risk if risk else 0
    fill_i = None
    for i, b in enumerate(future[:expire]):
        hit = (b["high"] >= entry) if (st["order"] == "stop") == (side > 0) else (b["low"] <= entry)
        if hit:
            fill_i = i
            break
    if fill_i is None:
        return {"filled": False, "r": 0.0, "exit": "expired", "won": None}
    for j, b in enumerate(future[fill_i: fill_i + max_hold]):
        o = b["open"] if j else entry
        stop_hit = b["low"] <= stop if side > 0 else b["high"] >= stop
        tp_hit = b["high"] >= tp if side > 0 else b["low"] <= tp
        if stop_hit:
            px = min(o, stop) if side > 0 else max(o, stop)
            if j == 0:
                px = stop
            r = side * (px - entry) / risk - cost_r
            return {"filled": True, "r": round(r, 3), "exit": "stop", "won": False, "bars": j + 1, "fill_bar": fill_i, "px": px}
        if tp_hit:
            r = side * (tp - entry) / risk - cost_r
            return {"filled": True, "r": round(r, 3), "exit": "target", "won": True, "bars": j + 1, "fill_bar": fill_i, "px": tp}
    seg = future[fill_i: fill_i + max_hold]
    if not seg or len(seg) < max_hold and fill_i + max_hold > len(future):
        return {"filled": True, "r": 0.0, "exit": "open", "won": None, "fill_bar": fill_i}
    px = seg[-1]["close"]
    r = side * (px - entry) / risk - cost_r
    return {"filled": True, "r": round(r, 3), "exit": "time", "won": r > 0, "bars": len(seg), "fill_bar": fill_i, "px": px}


def replay(c: list[dict], symbol: str, interval: str, stride: int = 2, start: int | None = None) -> list[dict]:
    """과거 봉마다 시나리오를 다시 만들고 채점한 표본들. 판단은 그 봉까지의 데이터만 쓴다."""
    out = []
    first = max(WINDOW, start or 0)
    for t in range(first, len(c) - 2, stride):
        w = c[t - WINDOW: t]
        try:
            reg = analysis.regime(w)
            sts = setups(w, reg)
        except Exception:  # noqa: BLE001
            continue
        if not sts:
            continue
        top = max(sts, key=lambda s: s["prob"])
        for s in sts:
            res = simulate(s, c[t:])
            if res["exit"] in ("open",):
                continue
            out.append({"t": w[-1]["time"], "symbol": symbol, "interval": interval, "key": s["key"], "title": s["title"], "kind": s["kind"],
                        "side": s["side"], "prob": s["prob"], "rr": s["rr"], "state": s["state"], "top": s is top,
                        "f": features(s, reg, w), **res, "src": "history"})
    return out


# ------------------------------------------------------------------ 보정 (실제 적중률)
def calibration(samples: list[dict]) -> dict:
    """(시나리오 종류, 장세, 봉) → 체결된 것 중 적중률 · 평균 R · 표본. 표본이 적으면 같은 종류 전체 평균으로 당긴다."""
    filled = [s for s in samples if s.get("filled") and s.get("won") is not None]
    by_key: dict = {}
    for s in filled:
        by_key.setdefault(s["key"], []).append(s)
    out = {}
    glob_r = sum(s["r"] for s in filled) / len(filled) if filled else 0.0
    for key, xs in by_key.items():
        kw = sum(s["won"] for s in xs) / len(xs)
        kr = sum(s["r"] for s in xs) / len(xs)
        groups: dict = {}
        for s in xs:
            groups.setdefault((s["state"], s["interval"]), []).append(s)
        out[key] = {"n": len(xs), "win": round(kw * 100, 1), "avg_r": round(kr, 3), "groups": {}}
        for (state, iv), g in groups.items():
            n = len(g)
            w = (sum(s["won"] for s in g) + SHRINK * kw) / (n + SHRINK)
            r = (sum(s["r"] for s in g) + SHRINK * kr) / (n + SHRINK)
            out[key]["groups"][f"{state}|{iv}"] = {"n": n, "win": round(w * 100, 1), "avg_r": round(r, 3),
                                                  "raw_win": round(sum(s["won"] for s in g) / n * 100, 1)}
    return {"keys": out, "n": len(filled), "avg_r": round(glob_r, 3),
            "fill_rate": round(len([s for s in samples if s.get("filled")]) / len(samples) * 100, 1) if samples else None}


def learned(cal: dict, key: str, state: str, interval: str) -> dict | None:
    k = cal.get("keys", {}).get(key)
    if not k:
        return None
    return k["groups"].get(f"{state}|{interval}") or {"n": 0, "win": k["win"], "avg_r": k["avg_r"]}


# ------------------------------------------------------------------ 메타 라벨 (할까 말까)
def _xy(samples):
    xs = [s for s in samples if s.get("filled") and s.get("won") is not None]
    X = np.array([[s["f"].get(k, 0.0) for k in FEATS] for s in xs], dtype=float)
    y = np.array([1.0 if s["won"] else 0.0 for s in xs])
    return xs, X, y


def meta_fit(samples: list[dict]) -> dict:
    """시간 순 70/30 으로 로지스틱 회귀를 학습·검증. 검증 AUC 가 0.5 보다 2σ 이상 높아야 '쓸 만함'."""
    from .ml import LogisticRegression, Scaler, auc
    xs, X, y = _xy(sorted(samples, key=lambda s: s["t"]))
    if len(xs) < 150 or y.min() == y.max():
        return {"ok": False, "why": f"표본 부족 ({len(xs)}건 · 150건 이상 필요)", "n": len(xs)}
    cut = int(len(xs) * 0.7)
    sc = Scaler(X[:cut])
    m = LogisticRegression(epochs=40).fit(sc(X[:cut]), y[:cut])
    p = m.predict(sc(X[cut:]))
    a = auc(p, y[cut:])
    n1, n0 = y[cut:].sum(), len(y[cut:]) - y[cut:].sum()
    se = math.sqrt((a * (1 - a) + 1e-9) / max(1, min(n1, n0))) if a is not None else None
    useful = a is not None and se is not None and a - 0.5 >= 2 * se
    sc_all = Scaler(X)
    m_all = LogisticRegression(epochs=40).fit(sc_all(X), y)
    weights = sorted(zip(FEATS, m_all.w.tolist()), key=lambda kv: -abs(kv[1]))
    return {"ok": True, "useful": bool(useful), "auc": round(a, 4) if a is not None else None, "se": round(se, 4) if se else None, "n": len(xs),
            "test_n": len(xs) - cut, "w": m_all.w.tolist(), "b": float(m_all.b[0]), "mean": sc_all.m.tolist(), "std": sc_all.s.tolist(),
            "weights": [{"key": k, "ko": FEAT_KO[k], "w": round(v, 3)} for k, v in weights[:8]], "t": time.time()}


def meta_prob(meta: dict | None, f: dict) -> float | None:
    if not meta or not meta.get("ok"):
        return None
    x = np.array([f.get(k, 0.0) for k in FEATS])
    z = np.clip((x - np.array(meta["mean"])) / np.array(meta["std"]), -8, 8)
    v = float(z @ np.array(meta["w"]) + meta["b"])
    return 1 / (1 + math.exp(-max(-30, min(30, v))))


# ------------------------------------------------------------------ 정책 (어떤 시나리오를 언제 탈까)
DEFAULT_POLICY = {"min_prob": 40, "min_rr": 1.5, "rank": "prob", "use_meta": False, "meta_thr": 0.5, "kinds": ["breakout", "pullback", "range"],
                  "indicator_check": True, "version": 1, "why": "기본: 화면 확률이 가장 높은 시나리오 · 확률 40% 이상 · 손익비 1.5 이상"}


def score_of(s: dict, policy: dict, cal: dict | None, meta: dict | None) -> float | None:
    """정책이 이 시나리오에 매기는 점수 (높을수록 먼저). None 이면 탈 수 없음."""
    if s["prob"] < policy["min_prob"] or s["rr"] < policy["min_rr"] or s["kind"] not in policy["kinds"]:
        return None
    if policy.get("use_meta"):
        p = s["_mp"] if "_mp" in s else meta_prob(meta, s["f"])
        if p is not None and p < policy["meta_thr"]:
            return None
    if policy["rank"] == "learned" and cal:
        if "_lr" in s:
            return s["_lr"] if s["_lr"] is not None else s["prob"]
        lv = learned(cal, s["key"], s["state"], s["interval"])
        if lv:
            return lv["avg_r"]
    return s["prob"]


def prepare(samples: list[dict], cal: dict | None, meta: dict | None) -> list[tuple]:
    """정책 후보를 많이 평가할 때 한 번만: 메타 확률(벡터 계산) · 배운 기대값 · 시점별 묶음."""
    if meta and meta.get("ok") and samples:
        X = np.array([[x["f"].get(k, 0.0) for k in FEATS] for x in samples])
        z = np.clip((X - np.array(meta["mean"])) / np.array(meta["std"]), -8, 8)
        ps = 1 / (1 + np.exp(-np.clip(z @ np.array(meta["w"]) + meta["b"], -30, 30)))
        for x, p in zip(samples, ps):
            x["_mp"] = float(p)
    else:
        for x in samples:
            x["_mp"] = None
    for x in samples:
        lv = learned(cal or {}, x["key"], x["state"], x["interval"])
        x["_lr"] = lv["avg_r"] if lv else None
    groups: dict = {}
    for x in samples:
        groups.setdefault((x["symbol"], x["interval"], x["t"]), []).append(x)
    return sorted(((k, g) for k, g in groups.items()), key=lambda kg: kg[0][2])


def unprepare(samples: list[dict]) -> None:
    for x in samples:
        x.pop("_mp", None)
        x.pop("_lr", None)


def why_not(group: list[dict], policy: dict) -> str:
    """정책이 아무것도 고르지 않은 이유 (가장 확률 높은 시나리오 기준)."""
    s = max(group, key=lambda x: x["prob"])
    why = []
    if s["prob"] < policy["min_prob"]:
        why.append(f"최고 화면 확률 {s['prob']}% < 기준 {policy['min_prob']}%")
    if s["rr"] < policy["min_rr"]:
        why.append(f"손익비 {s['rr']} < 기준 {policy['min_rr']}")
    if s["kind"] not in policy["kinds"]:
        why.append(f"'{s['title']}' 종류는 정책에서 뺌")
    if not why and policy.get("use_meta"):
        why.append("메타 모델이 이길 확률을 낮게 봄")
    if not why and policy["rank"] == "learned":
        why.append("배운 기대값이 0 이하")
    return f"{s['title']}({s['prob']}% · RR {s['rr']}): " + (" · ".join(why) or "조건 미달")


def pick(group: list[dict], policy: dict, cal: dict | None, meta: dict | None) -> dict | None:
    scored = [(score_of(s, policy, cal, meta), s) for s in group]
    scored = [(v, s) for v, s in scored if v is not None]
    if not scored:
        return None
    v, s = max(scored, key=lambda x: x[0])
    if policy["rank"] == "learned" and v <= 0:            # 배운 기대값이 0 이하면 안 탄다
        return None
    return s


def rank(group: list[dict], policy: dict, cal: dict | None, meta: dict | None) -> list[dict]:
    """정책을 통과한 시나리오를 점수 높은 순서로 (1순위가 지표 확인 등으로 막히면 다음 순위를 본다)."""
    scored = [(score_of(s, policy, cal, meta), s) for s in group]
    scored = sorted([(v, s) for v, s in scored if v is not None], key=lambda x: -x[0])
    if policy["rank"] == "learned":
        scored = [(v, s) for v, s in scored if v > 0]
    return [s for _, s in scored]


def evaluate(samples: list[dict], policy: dict, cal: dict | None = None, meta: dict | None = None, groups: list | None = None) -> dict:
    """정책대로 시간 순으로 골라 탔다면 — 같은 코인·봉에서는 앞 거래가 끝나기 전에 새로 타지 않는다."""
    if groups is None:
        g: dict = {}
        for s in samples:
            g.setdefault((s["symbol"], s["interval"], s["t"]), []).append(s)
        groups = sorted(g.items(), key=lambda kg: kg[0][2])
    busy_until: dict = {}
    rs = []
    for (sym, iv, t), grp in groups:
        if busy_until.get((sym, iv), 0) > t:
            continue
        s = pick(grp, policy, cal, meta)
        if not s or not s.get("filled"):
            continue
        rs.append(s["r"])
        bar = _bar_sec(iv)
        busy_until[(sym, iv)] = t + bar * (s.get("fill_bar", 0) + s.get("bars", 1))
    return {**stats(rs), "rs": rs}


def stats(rs: list[float]) -> dict:
    if not rs:
        return {"n": 0, "win": None, "exp_r": None, "pf": None, "total_r": 0.0, "max_dd_r": 0.0}
    wins = [r for r in rs if r > 0]
    gl = -sum(r for r in rs if r <= 0)
    eq, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"n": len(rs), "win": round(len(wins) / len(rs) * 100, 1), "exp_r": round(sum(rs) / len(rs), 3),
            "pf": round(sum(wins) / gl, 2) if gl > 0 else None, "total_r": round(sum(rs), 2), "max_dd_r": round(dd, 2)}


def _bar_sec(iv: str) -> int:
    return {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}.get(iv, 3600)


def candidates_grid() -> list[dict]:
    out = []
    for mp in (0, 35, 45, 55):
        for rr in (1.2, 1.5, 2.0):
            for rank in ("prob", "learned"):
                for um, thr in ((False, 0.5), (True, 0.5), (True, 0.55)):
                    for kinds in (["breakout", "pullback", "range"], ["breakout", "pullback"], ["pullback", "range"]):
                        out.append({"min_prob": mp, "min_rr": rr, "rank": rank, "use_meta": um, "meta_thr": thr, "kinds": kinds})
    return out


def optimize(samples: list[dict], current: dict, min_test: int = 20, margin: float = 0.02) -> dict:
    """앞 70% 로 정책 후보를 고르고, 뒤 30% 에서 지금 정책보다 기대값이 margin R 이상 좋을 때만 채택."""
    xs = sorted(samples, key=lambda s: s["t"])
    if len(xs) < 300:
        return {"adopt": False, "why": f"표본이 부족합니다 ({len(xs)}건 · 300건 이상 필요)"}
    cut_t = xs[int(len(xs) * 0.7)]["t"]
    train, test = [s for s in xs if s["t"] < cut_t], [s for s in xs if s["t"] >= cut_t]
    cal_tr = calibration(train)
    meta_tr = meta_fit(train)
    meta_tr = meta_tr if meta_tr.get("useful") else None
    try:
        return _optimize(xs, train, test, cal_tr, meta_tr, current, min_test, margin)
    finally:
        unprepare(xs)


def _optimize(xs, train, test, cal_tr, meta_tr, current, min_test, margin) -> dict:
    g_tr = prepare(train, cal_tr, meta_tr)
    g_te = prepare(test, cal_tr, meta_tr)
    ranked = []
    for pol in candidates_grid():
        if pol["use_meta"] and not meta_tr:
            continue
        r = evaluate(train, pol, cal_tr, meta_tr, g_tr)
        if r["n"] >= 40 and r["exp_r"] is not None:
            # 기대값 × √거래수 (t-통계처럼: 몇 번만 크게 맞힌 정책보다 꾸준한 정책) − 낙폭 벌점
            ranked.append((r["exp_r"] * math.sqrt(r["n"]) - 0.02 * r["max_dd_r"], pol, r))
    ranked.sort(key=lambda x: -x[0])
    cur_test = evaluate(test, current, cal_tr, meta_tr, g_te)
    mid_t = test[len(test) // 2]["t"] if test else 0
    halves = ([x for x in test if x["t"] < mid_t], [x for x in test if x["t"] >= mid_t])
    best = None
    for _, pol, tr in ranked[:8]:                         # 앞 70% 상위 8개만 검증 구간에 (후보를 많이 볼수록 우연히 좋은 게 나온다)
        te = evaluate(test, pol, cal_tr, meta_tr, g_te)
        if te["n"] >= min_test and te["exp_r"] is not None and (best is None or te["exp_r"] > best[2]["exp_r"]):
            best = (pol, tr, te)
    report = {"train_n": len(train), "test_n": len(test), "current_test": {k: v for k, v in cur_test.items() if k != "rs"},
              "meta_auc": (meta_tr or {}).get("auc"), "candidates": len(ranked)}
    if not best:
        return {**report, "adopt": False, "why": "검증 구간에서 거래 수가 충분한 후보가 없습니다"}
    pol, tr, te = best
    cur_exp = cur_test["exp_r"] if cur_test["exp_r"] is not None else -9
    p_better = boot_better(te["rs"], cur_test["rs"])
    both = all((evaluate(h, pol, cal_tr, meta_tr)["exp_r"] or -9) >= (evaluate(h, current, cal_tr, meta_tr)["exp_r"] or -9) for h in halves)
    lcb = boot_lcb(te["rs"])
    report.update(p_better=p_better, both_halves=both, test_lcb=lcb)
    tr = {k: v for k, v in tr.items() if k != "rs"}
    te = {k: v for k, v in te.items() if k != "rs"}
    if te["exp_r"] > cur_exp + margin and p_better >= 80 and both:
        why = (f"검증 30% 에서 기대값 {cur_exp:+.3f}R → {te['exp_r']:+.3f}R (거래 {te['n']}건 · 승률 {te['win']}% · 더 나을 확률 {p_better}% · "
               f"검증 앞뒤 절반 모두 우세{' · 기대값 하한 ' + format(lcb, '+.3f') + 'R' if lcb is not None else ''}) — "
               f"최소 확률 {pol['min_prob']}% · 손익비 {pol['min_rr']} · 순위 {'배운 기대값' if pol['rank'] == 'learned' else '화면 확률'}"
               f"{' · 메타 필터 ' + str(pol['meta_thr']) if pol['use_meta'] else ''} · 종류 {', '.join(pol['kinds'])}")
        return {**report, "adopt": True, "policy": {**current, **pol, "version": current.get("version", 1) + 1, "why": why}, "train": tr, "test": te, "why": why}
    return {**report, "adopt": False, "best_test": te,
            "why": f"가장 나은 후보(검증 기대값 {te['exp_r']:+.3f}R · 더 나을 확률 {p_better}% · 앞뒤 절반 {'모두 우세' if both else '엇갈림'})도 "
                   f"지금 정책({cur_exp:+.3f}R)보다 확실히 낫다고 할 수 없어 유지"}


def boot_better(a: list[float], b: list[float], n: int = 400, seed: int = 5) -> float:
    """부트스트랩: 후보(a)의 평균 R 이 지금(b)보다 클 확률 %."""
    if not a:
        return 0.0
    if not b:
        return 100.0 if sum(a) > 0 else 0.0
    rng = random.Random(seed)
    k = sum(1 for _ in range(n) if sum(rng.choice(a) for _ in a) / len(a) > sum(rng.choice(b) for _ in b) / len(b))
    return round(k / n * 100, 1)


def boot_lcb(a: list[float], n: int = 400, q: float = 0.05, seed: int = 6) -> float | None:
    """평균 R 의 부트스트랩 하위 5% — 0 보다 크면 '이익이 우연이 아닐' 가능성이 높다."""
    if len(a) < 10:
        return None
    rng = random.Random(seed)
    ms = sorted(sum(rng.choice(a) for _ in a) / len(a) for _ in range(n))
    return round(ms[int(q * n)], 3)


def page_hinkley(rs: list[float], delta: float = 0.05, lam: float = 4.0) -> dict:
    """성적 급변 감지 (river 의 PageHinkley 개념): 최근 R 의 평균이 이전보다 떨어지기 시작하면 경보."""
    if len(rs) < 15:
        return {"drift": False, "at": None}
    mean, m, mn = 0.0, 0.0, 0.0
    for i, x in enumerate(rs, 1):
        mean += (x - mean) / i
        m += mean - x - delta              # 떨어지는 쪽 감지
        mn = min(mn, m)
        if m - mn > lam:
            return {"drift": True, "at": i}
    return {"drift": False, "at": None}


def unfamiliar(meta: dict | None, f: dict, z_max: float = 4.0) -> str | None:
    """학습 때 못 본 낯선 상황인가 (FreqAI 의 DI 개념): 특징 하나라도 학습 분포에서 4σ 넘게 벗어나면."""
    if not meta or not meta.get("ok"):
        return None
    x = np.array([f.get(k, 0.0) for k in FEATS])
    z = np.abs((x - np.array(meta["mean"])) / np.array(meta["std"]))
    i = int(z.argmax())
    return f"{FEAT_KO[FEATS[i]]} 가 학습 때와 너무 다름 ({z[i]:.1f}σ)" if z[i] > z_max else None


def shuffle_check(samples: list[dict], policy: dict, cal=None, meta=None, n: int = 200, seed: int = 3) -> dict:
    """운인지 확인: 같은 거래들의 순서를 섞어 '이 기대값이 0보다 클 확률'을 부트스트랩으로."""
    r = evaluate(samples, policy, cal, meta)
    if not r["n"]:
        return {"p_positive": None}
    rng = random.Random(seed)
    rs = [s["r"] for s in samples if s.get("filled") and s.get("won") is not None]
    pos = sum(1 for _ in range(n) if sum(rng.choice(rs) for _ in range(r["n"])) > 0)
    return {"p_positive": round(pos / n * 100, 1)}


def indicator_votes(c: list[dict], side: int, kind: str = "breakout") -> dict:
    """빠른 보조지표 확인 (파이썬) — 시나리오 종류마다 '같은 편' 의 뜻이 다르다.
    - 돌파: RSI·MACD·슈퍼트렌드·EMA20/50·볼린저 위치가 모두 진입 방향으로 힘이 있어야 좋다 (추세 추종).
    - 눌림목: 큰 추세(슈퍼트렌드·EMA20/50)만 본다. 눌림 중이라 RSI·볼린저가 잠깐 반대인 건 정상.
    - 박스권: 역추세 — 박스 아래에서 롱이면 RSI 낮음·볼린저 아래쪽이 '같은 편'. 강한 추세(슈퍼트렌드+EMA)만 반대로 센다.
    """
    close = [b["close"] for b in c]
    v = {}
    r = ind.rsi(close)[-1]
    e20, e50 = ind.ema(close, 20)[-1], ind.ema(close, 50)[-1]
    st = ind.supertrend(c)["trend"][-1]
    bb = ind.bbands(close)
    up, lo = bb["upper"][-1], bb["lower"][-1]
    pos = (close[-1] - lo) / (up - lo) if up and lo and up > lo else None
    if kind == "range":
        if r is not None:
            v["RSI(역추세)"] = side * (1 if r < 45 else -1 if r > 60 else 0)
        if pos is not None:
            v["볼린저 위치(역추세)"] = side * (1 if pos < 0.35 else -1 if pos > 0.75 else 0)
        if st and e20 and e50 and st == (1 if e20 > e50 else -1):
            v["강한 추세"] = side * st                    # 슈퍼트렌드·EMA 가 같은 방향일 때만 한 표
    else:
        if kind != "pullback":
            if r is not None:
                v["RSI"] = side * (1 if r > 55 else -1 if r < 45 else 0)
            m = ind.macd(close)["hist"]
            if m[-1] is not None and m[-2] is not None:
                v["MACD"] = side * (1 if m[-1] > 0 and m[-1] > m[-2] else -1 if m[-1] < 0 and m[-1] < m[-2] else 0)
            if pos is not None:
                v["볼린저 위치"] = side * (1 if pos > 0.6 else -1 if pos < 0.4 else 0)
        if st:
            v["슈퍼트렌드"] = side * st
        if e20 and e50:
            v["EMA20/50"] = side * (1 if e20 > e50 else -1)
    score = sum(v.values())
    return {"votes": v, "score": score, "n": len(v), "kind": kind}
