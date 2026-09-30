"""AI 봇 — AI 진입 시그널을 그대로 따라 모의(페이퍼) 매매하는 봇.

- 시그널(진입가·손절·익절)이 나오면 진입가에 닿을 때 들어가고(12봉 안에 안 닿으면 미체결), 손절·익절에 닿으면 나온다.
  한 봉에서 둘 다 닿으면 손절로 본다(보수적). 같은 코인에 포지션이 있으면 새 시그널은 건너뛴다.
- 거래마다 증거금 = 시작 자산 × position_pct%, 레버리지 leverage 배, 수수료 fee_pct% × 2 (진입·청산).
- 기록은 시그널과 봉에서 매번 다시 계산한다 → 앱을 다시 켜도 같은 결과. 새 진입·청산은 알림으로.
- 실제 주문은 하지 않는다.
"""
from __future__ import annotations

import json
import threading
import time

from . import config
from .data import market

SETTINGS = {
    "enabled": True,
    "initial": 10_000.0,
    "leverage": 3.0,
    "position_pct": 20.0,
    "fee_pct": 0.04,
    "include_rules": True,      # AI 키가 없거나 AI 가 실패해 규칙 분석이 낸 시그널도 따라감
    "min_confidence": 0,        # 이 확신(%) 미만 시그널은 건너뜀
}
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}
_seen: dict = {"entries": set(), "exits": set(), "loaded": False, "init": False}


def _path():
    return config.STATE_DIR / "aibot.json"


def _load() -> None:
    if _seen["loaded"]:
        return
    _seen["loaded"] = True
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    SETTINGS.update({k: v for k, v in (d.get("settings") or {}).items() if k in SETTINGS})
    _seen["entries"] = set(d.get("entries") or [])
    _seen["exits"] = set(d.get("exits") or [])
    _seen["init"] = bool(d.get("init"))


def _save() -> None:
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps({"settings": SETTINGS, "entries": sorted(_seen["entries"])[-2000:], "exits": sorted(_seen["exits"])[-2000:], "init": _seen["init"]},
                                      ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def set_settings(body: dict) -> dict:
    _load()
    for k, v in body.items():
        if k not in SETTINGS or v is None:
            continue
        if isinstance(SETTINGS[k], bool):
            SETTINGS[k] = bool(v)
        else:
            SETTINGS[k] = float(v)
    SETTINGS["leverage"] = max(1.0, min(SETTINGS["leverage"], 50.0))
    SETTINGS["position_pct"] = max(1.0, min(SETTINGS["position_pct"], 100.0))
    SETTINGS["initial"] = max(100.0, SETTINGS["initial"])
    SETTINGS["fee_pct"] = max(0.0, min(SETTINGS["fee_pct"], 1.0))
    _cache["at"] = 0
    _save()
    return dict(SETTINGS)


def _pnl(side: str, entry: float, exit_: float) -> tuple[float, float, float]:
    """(순손익, 증거금 대비 %, 수수료)."""
    margin = SETTINGS["initial"] * SETTINGS["position_pct"] / 100
    notional = margin * SETTINGS["leverage"]
    ret = (exit_ / entry - 1) * (1 if side == "long" else -1)
    fees = notional * SETTINGS["fee_pct"] / 100 * 2
    pnl = notional * ret - fees
    return pnl, pnl / margin * 100, fees


def compute(force: bool = False) -> dict:
    """모든 AI 시그널 → AI 봇 거래·포지션·통계. 20초 캐시."""
    _load()
    with _lock:
        if not force and _cache["data"] is not None and time.time() - _cache["at"] < 20:
            return _cache["data"]
        from .quant import copilot
        copilot._load_signals()
        sigs = sorted(copilot.ai_signals, key=lambda x: x["created"])
        candles: dict = {}
        rows, trades, open_, busy_until = [], [], [], {}
        for s in sigs:
            k = (s["symbol"], s["interval"])
            if k not in candles:
                try:
                    candles[k] = market.candles(s["symbol"], s["interval"], 1000)[0]
                except Exception:
                    candles[k] = []
            c = candles[k]
            out = copilot.grade(s, c) if c else {"status": "unknown", "label": "-"}
            row = {**s, "outcome": out, "taken": False, "skip": None, "trade": None}
            if not SETTINGS["enabled"]:
                row["skip"] = "AI 봇 꺼짐"
            elif s.get("engine") in (None, "rules") and not SETTINGS["include_rules"]:
                row["skip"] = "규칙 분석 시그널 (설정에서 제외)"
            elif (s.get("confidence") or 0) < SETTINGS["min_confidence"]:
                row["skip"] = f"확신 {s.get('confidence')}% < {SETTINGS['min_confidence']:.0f}%"
            elif out.get("entered_at") and out["entered_at"] < busy_until.get(s["symbol"], 0):
                row["skip"] = "같은 코인 포지션 보유 중"
            elif out.get("entered_at"):
                row["taken"] = True
                last = c[-1]["close"] if c else s["entry"]
                closed = out["status"] in ("take", "stop")
                exit_px = (s["take"] if out["status"] == "take" else s["stop"]) if closed else last
                pnl, roe, fees = _pnl(s["side"], s["entry"], exit_px)
                risk = abs(s["entry"] - s["stop"]) or 1
                t = {"id": s["id"], "symbol": s["symbol"], "interval": s["interval"], "side": s["side"], "entry": s["entry"], "stop": s["stop"],
                     "take": s["take"], "exit": exit_px if closed else None, "mark": None if closed else last,
                     "entry_time": out["entered_at"], "exit_time": out.get("closed_at"), "signal_time": s["created"],
                     "status": out["status"], "label": out["label"], "pnl": round(pnl, 2), "roe_pct": round(roe, 2), "fees": round(fees, 2),
                     "r": round((exit_px - s["entry"]) * (1 if s["side"] == "long" else -1) / risk, 2),
                     "held_min": round(((out.get("closed_at") or c[-1]["time"]) - out["entered_at"]) / 60) if c else None,
                     "confidence": s.get("confidence"), "engine": s.get("engine"), "model": s.get("model"), "reason": s.get("trigger") or s.get("reason", "")}
                row["trade"] = t
                if closed:
                    trades.append(t)
                    busy_until[s["symbol"]] = out["closed_at"] + 1
                else:
                    open_.append(t)
                    busy_until[s["symbol"]] = float("inf")
            rows.append(row)
        data = {"settings": dict(SETTINGS), "signals": rows, "trades": sorted(trades, key=lambda t: t["exit_time"]), "open": open_,
                "stats": stats(trades, open_), "now": int(time.time())}
        _cache.update(at=time.time(), data=data)
        return data


def stats(trades: list[dict], open_: list[dict]) -> dict:
    init = SETTINGS["initial"]
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    gw, gl = sum(t["pnl"] for t in wins), -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    eq = peak = init
    mdd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_time"]):
        eq += t["pnl"]
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100 if peak > 0 else 0)
    unreal = sum(t["pnl"] for t in open_)
    by: dict = {}
    for t in trades:
        b = by.setdefault(t["symbol"], {"trades": 0, "wins": 0, "pnl": 0.0})
        b["trades"] += 1
        b["wins"] += t["pnl"] > 0
        b["pnl"] = round(b["pnl"] + t["pnl"], 2)
    ai = [t for t in trades if t.get("engine") not in (None, "rules")]
    return {"trades": n, "wins": len(wins), "losses": n - len(wins), "win_rate": round(len(wins) / n * 100, 1) if n else None,
            "net_pnl": round(eq - init, 2), "return_pct": round((eq / init - 1) * 100, 2), "equity": round(eq + unreal, 2),
            "realized_equity": round(eq, 2), "unrealized": round(unreal, 2), "profit_factor": round(gw / gl, 2) if gl > 0 else None,
            "avg_roe_pct": round(sum(t["roe_pct"] for t in trades) / n, 2) if n else None,
            "avg_r": round(sum(t["r"] for t in trades) / n, 2) if n else None, "max_drawdown_pct": round(mdd, 2),
            "best": max((t["roe_pct"] for t in trades), default=None), "worst": min((t["roe_pct"] for t in trades), default=None),
            "avg_hold_min": round(sum(t["held_min"] or 0 for t in trades) / n) if n else None, "fees": round(sum(t["fees"] for t in trades), 2),
            "open": len(open_), "by_symbol": by,
            "ai_only": {"trades": len(ai), "win_rate": round(sum(t["pnl"] > 0 for t in ai) / len(ai) * 100, 1) if ai else None}}


def view(symbol: str | None = None, interval: str | None = None) -> dict:
    d = compute()
    if not symbol:
        return d
    keep = lambda x: x["symbol"] == symbol and (not interval or x["interval"] == interval)
    return {**d, "signals": [x for x in d["signals"] if keep(x)][-60:], "trades": [t for t in d["trades"] if keep(t)],
            "open": [t for t in d["open"] if keep(t)]}


def events() -> list[dict]:
    """처음 보는 AI 봇 진입·청산 (알림용). 앱을 켠 직후 예전 거래가 한꺼번에 알림으로 오지 않게, 처음엔 모두 본 것으로."""
    d = compute(force=True)
    first = not _seen["init"]
    _seen["init"] = True
    out = []
    for t in d["open"] + d["trades"]:
        if t["id"] not in _seen["entries"]:
            _seen["entries"].add(t["id"])
            if not first and time.time() - t["entry_time"] < 6 * 3600:
                out.append({"kind": "entry", **t})
        if t["status"] in ("take", "stop") and t["id"] not in _seen["exits"]:
            _seen["exits"].add(t["id"])
            if not first and time.time() - (t["exit_time"] or 0) < 6 * 3600:
                out.append({"kind": "exit", **t})
    if out or first:
        _save()
    return out
