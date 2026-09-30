"""시그널 스캐너 — 관심 코인 × 여러 봉을 백그라운드에서 계속 분석하고, 조건이 맞으면 신호를 쌓는다.

- 막 끝난 봉(확정 봉)만 보고 판단한다. 진행 중인 봉으로 판단하면 봉이 끝날 때 신호가 사라질 수 있기 때문.
- 같은 코인·봉·종류·봉시간 조합은 한 번만 낸다 (중복 알림 없음).
- 같은 봉에서 같은 방향 신호가 여러 개 겹치면 강도(1~3)를 올린다.
- 화면은 /api/scanner/signals 를 주기적으로 읽어 새 신호를 알림으로 띄운다.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque

from .. import analysis, config
from .. import indicators as ind
from ..data import market
from . import forecast

SIGNALS = {
    "rsi": "RSI 과매도·과매수 탈출",
    "macd": "MACD 교차",
    "ema": "EMA 20/50 골든·데드 크로스",
    "supertrend": "슈퍼트렌드 전환",
    "breakout": "20봉 고점 돌파 · 저점 이탈",
    "volume": "거래량 급증 (평소 3배 이상)",
    "squeeze": "볼린저 압축 후 돌파",
    "divergence": "RSI 다이버전스",
    "sweep": "유동성 스윕 (고점·저점 찍고 복귀)",
    "regime": "시장 판단 전환 (롱·숏·횡보)",
    "pattern": "과거 유사 패턴 강한 예측",
    "footprint": "풋프린트 진입 신호 (흡수 · 델타 반전 · 스윕)",
    "rotation": "순환매 자리 (개선→주도 진입 · 주도→약화)",
}
DEFAULT = {"enabled": True, "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT"],
           "intervals": ["15m", "1h", "4h"], "signals": {k: True for k in SIGNALS}, "every_sec": 30}
_lock = threading.Lock()


def _pivots(x: list[float], left: int, right: int, high: bool) -> list[int]:
    out = []
    for i in range(left, len(x) - right):
        w = x[i - left:i + right + 1]
        if (high and x[i] == max(w) and w.count(x[i]) == 1) or (not high and x[i] == min(w) and w.count(x[i]) == 1):
            out.append(i)
    return out


def evaluate(symbol: str, interval: str, c: list[dict], enabled: dict[str, bool] | None = None) -> list[dict]:
    """c = 확정 봉들 (마지막 원소가 방금 끝난 봉). 그 봉에서 난 신호 목록."""
    on = enabled or {k: True for k in SIGNALS}
    L = len(c) - 1
    if L < 60:
        return []
    cl = [b["close"] for b in c]
    hi = [b["high"] for b in c]
    lo = [b["low"] for b in c]
    vol = [b["volume"] for b in c]
    px = cl[L]
    out: list[dict] = []

    def sig(kind, d, text, strength=1):
        out.append({"type": kind, "label": SIGNALS[kind], "dir": d, "text": text, "strength": strength})

    r = ind.rsi(cl, 14)
    if on.get("rsi") and r[L] is not None and r[L - 1] is not None:
        if r[L - 1] < 30 <= r[L]:
            sig("rsi", "long", f"RSI {r[L]:.0f} — 과매도(30) 위로 복귀")
        elif r[L - 1] > 70 >= r[L]:
            sig("rsi", "short", f"RSI {r[L]:.0f} — 과매수(70) 아래로 복귀")
    if on.get("macd"):
        m = ind.macd(cl)
        h = m["hist"]
        if h[L] is not None and h[L - 1] is not None and (h[L] > 0) != (h[L - 1] > 0):
            up = h[L] > 0
            below = m["line"][L] < 0 if up else m["line"][L] > 0
            sig("macd", "long" if up else "short", f"MACD {'골든' if up else '데드'}크로스"
                + (" (0선 아래에서 — 바닥권)" if up and below else " (0선 위에서 — 고점권)" if below else ""), 2 if below else 1)
    if on.get("ema"):
        e20, e50 = ind.ema(cl, 20), ind.ema(cl, 50)
        if None not in (e20[L], e50[L], e20[L - 1], e50[L - 1]):
            if e20[L - 1] <= e50[L - 1] and e20[L] > e50[L]:
                sig("ema", "long", "EMA20 이 EMA50 을 위로 돌파 (골든크로스)", 2)
            elif e20[L - 1] >= e50[L - 1] and e20[L] < e50[L]:
                sig("ema", "short", "EMA20 이 EMA50 을 아래로 돌파 (데드크로스)", 2)
    if on.get("supertrend"):
        tr = ind.supertrend(c, 10, 3)["trend"]
        if tr[L] is not None and tr[L - 1] is not None and tr[L] != tr[L - 1]:
            sig("supertrend", "long" if tr[L] > 0 else "short", f"슈퍼트렌드 {'상승' if tr[L] > 0 else '하락'} 전환", 2)
    if on.get("breakout"):
        hh, ll = max(hi[L - 20:L]), min(lo[L - 20:L])
        phh, pll = max(hi[L - 21:L - 1]), min(lo[L - 21:L - 1])   # 직전 봉이 이미 돌파한 상태면 새 신호 아님
        if cl[L] > hh and cl[L - 1] <= phh:
            sig("breakout", "long", f"20봉 고점 {hh:.6g} 돌파 마감")
        elif cl[L] < ll and cl[L - 1] >= pll:
            sig("breakout", "short", f"20봉 저점 {ll:.6g} 이탈 마감")
    if on.get("volume"):
        avg = sum(vol[L - 20:L]) / 20
        if avg and vol[L] >= 3 * avg:
            up = cl[L] >= c[L]["open"]
            sig("volume", "long" if up else "short", f"거래량 평소의 {vol[L] / avg:.1f}배 · {'양봉' if up else '음봉'}",
                2 if vol[L] >= 5 * avg else 1)
    if on.get("squeeze"):
        bb = ind.bbands(cl, 20, 2)
        wid = [None if bb["upper"][i] is None else (bb["upper"][i] - bb["lower"][i]) / bb["middle"][i] for i in range(L + 1)]
        hist = [w for w in wid[max(0, L - 121):L] if w is not None]
        if hist and wid[L - 1] is not None and sorted(hist).index(min(hist, key=lambda w: abs(w - wid[L - 1]))) <= len(hist) * 0.1:
            if cl[L] > bb["upper"][L]:
                sig("squeeze", "long", "볼린저 밴드가 좁게 눌린 뒤 상단 돌파 — 변동성 확대 시작", 2)
            elif cl[L] < bb["lower"][L]:
                sig("squeeze", "short", "볼린저 밴드가 좁게 눌린 뒤 하단 이탈 — 변동성 확대 시작", 2)
    if on.get("divergence") and r[L] is not None:
        right = 3
        rr = [v if v is not None else 50.0 for v in r]
        lows = [i for i in _pivots(lo, 5, right, False) if i >= L - 80]
        highs = [i for i in _pivots(hi, 5, right, True) if i >= L - 80]
        if len(lows) >= 2 and lows[-1] == L - right and 5 <= lows[-1] - lows[-2] <= 60:
            a, b = lows[-2], lows[-1]
            if lo[b] < lo[a] and rr[b] > rr[a]:
                sig("divergence", "long", f"강세 다이버전스 — 가격은 저점을 낮췄는데 RSI 는 높임 ({rr[a]:.0f}→{rr[b]:.0f})", 2)
        if len(highs) >= 2 and highs[-1] == L - right and 5 <= highs[-1] - highs[-2] <= 60:
            a, b = highs[-2], highs[-1]
            if hi[b] > hi[a] and rr[b] < rr[a]:
                sig("divergence", "short", f"약세 다이버전스 — 가격은 고점을 높였는데 RSI 는 낮춤 ({rr[a]:.0f}→{rr[b]:.0f})", 2)
    if on.get("sweep"):
        ph = [i for i in _pivots(hi, 5, 5, True) if L - 60 <= i < L - 5]
        pl = [i for i in _pivots(lo, 5, 5, False) if L - 60 <= i < L - 5]
        if ph:
            lv = hi[ph[-1]]
            if hi[L] > lv and cl[L] < lv and max(hi[ph[-1] + 1:L]) <= lv:
                sig("sweep", "short", f"직전 고점 {lv:.6g} 위 유동성만 쓸고 아래로 마감 — 가짜 돌파", 2)
        if pl:
            lv = lo[pl[-1]]
            if lo[L] < lv and cl[L] > lv and min(lo[pl[-1] + 1:L]) >= lv:
                sig("sweep", "long", f"직전 저점 {lv:.6g} 아래 유동성만 쓸고 위로 마감 — 가짜 이탈", 2)
    if on.get("regime") and L > 220:
        now, prev = analysis.regime(c[-300:]), analysis.regime(c[-301:-1])
        if now["state"] != prev["state"]:
            d = {"long": "long", "short": "short"}.get(now["state"], "neutral")
            sig("regime", d, f"시장 판단 {prev['label']} → {now['label']} (점수 {now['score']:+d})", 2 if now["state"] != "range" else 1)
    if on.get("pattern") and len(c) >= 400:
        try:
            a = forecast.analogs(c, 48, 24)
        except ValueError:
            a = None
        if a and a["avg_corr"] >= 0.8 and a["n"] >= 15 and (a["prob_up"] >= 75 or a["prob_up"] <= 25):
            up = a["prob_up"] >= 75
            sig("pattern", "long" if up else "short",
                f"비슷했던 과거 {a['n']}번 중 {a['prob_up'] if up else 100 - a['prob_up']}%가 24봉 뒤 {'상승' if up else '하락'} "
                f"(중간값 {a['median_ret_pct']:+.2f}%)", 2 if a["reliability"] == "높음" else 1)
    # 같은 방향 신호가 겹치면 강도 올림
    for d in ("long", "short"):
        same = [s for s in out if s["dir"] == d]
        if len(same) >= 2:
            for s in same:
                s["strength"] = min(3, max(s["strength"], len(same)))
                s["confluence"] = len(same)
    t = c[L]["time"]
    for s in out:
        s.update({"id": f"{symbol}:{interval}:{s['type']}:{t}", "symbol": symbol, "interval": interval,
                  "price": px, "bar_time": t})
    return out


def board_row(symbol: str, interval: str, c: list[dict]) -> dict:
    reg = analysis.regime(c[-300:])
    L = len(c) - 1
    return {"symbol": symbol, "interval": interval, "price": c[L]["close"],
            "change_pct": round((c[L]["close"] / c[L - 1]["close"] - 1) * 100, 2),
            "state": reg["state"], "label": reg["label"], "score": reg["score"], "rsi": reg["rsi"], "adx": reg["adx"],
            "bar_time": c[L]["time"]}


class Scanner:
    def __init__(self):
        self.cfg = dict(DEFAULT)
        self.signals: deque[dict] = deque(maxlen=400)
        self.seen: set[str] = set()
        self.board: dict[str, dict] = {}
        self.last_bar: dict[str, int] = {}
        self.last_run = 0.0
        self.errors: dict[str, str] = {}
        self._task: asyncio.Task | None = None
        self._load()

    # ---- 설정
    @property
    def path(self):
        return config.STATE_DIR / "scanner.json"

    def _load(self):
        try:
            self.cfg.update(json.loads(self.path.read_text(encoding="utf-8")))
            self.cfg["signals"] = {**DEFAULT["signals"], **self.cfg.get("signals", {})}
        except (OSError, ValueError):
            pass

    def set_config(self, **kw) -> dict:
        from ..data.symbols import resolve
        from ..strategy import INTERVALS
        with _lock:
            if kw.get("symbols") is not None:
                self.cfg["symbols"] = list(dict.fromkeys(resolve(s) for s in kw["symbols"] if s.strip()))[:40]
            if kw.get("intervals") is not None:
                self.cfg["intervals"] = [i for i in dict.fromkeys(kw["intervals"]) if i in INTERVALS][:6]
            if kw.get("signals") is not None:
                self.cfg["signals"] = {k: bool(kw["signals"].get(k, v)) for k, v in self.cfg["signals"].items()}
            if kw.get("enabled") is not None:
                self.cfg["enabled"] = bool(kw["enabled"])
            try:
                config.STATE_DIR.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self.cfg, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            return dict(self.cfg)

    # ---- 스캔
    def scan_one(self, symbol: str, interval: str) -> list[dict]:
        c, _ = market.candles(symbol, interval, 600 if self.cfg["signals"].get("pattern") else 320)
        closed = c[:-1]                                   # 마지막 봉은 진행 중
        key = f"{symbol}:{interval}"
        self.board[key] = board_row(symbol, interval, c)
        if self.last_bar.get(key) == closed[-1]["time"]:
            return []
        self.last_bar[key] = closed[-1]["time"]
        new = []
        extra = self._extra(symbol, interval, closed[-1]["time"], closed[-1]["close"])
        for s in evaluate(symbol, interval, closed, self.cfg["signals"]) + extra:
            if s["id"] not in self.seen:
                self.seen.add(s["id"])
                s["created"] = int(time.time())
                new.append(s)
        with _lock:
            self.signals.extend(new)
        return new

    def _extra(self, symbol: str, interval: str, bar_time: int, price: float) -> list[dict]:
        """풋프린트 · 순환매 신호 (다른 데이터가 필요해서 따로)."""
        out = []
        on = self.cfg["signals"]
        if on.get("footprint") and interval != "1m":
            try:
                from . import footprint
                from .. import indicators as ind
                fp = footprint.footprint(symbol, interval, 40)
                bars = fp["bars"]
                for sg in footprint.bar_signals(bars, ind.atr(bars, 14), fp["tick"]):
                    if sg["time"] == bar_time:
                        out.append({"type": "footprint", "label": SIGNALS["footprint"], "dir": sg["dir"], "strength": 1 + sg["strength"] // 2,
                                    "text": " / ".join(sg["reasons"]) + f" · 진입 {sg['entry']:.6g} 손절 {sg['stop']:.6g}"})
            except Exception:
                pass
        if on.get("rotation"):
            try:
                from . import rotation
                rs = rotation.series(symbol, interval, 300)
                for mk in rs["marks"]:
                    if mk["time"] == bar_time and mk["kind"] in ("entry", "exit"):
                        out.append({"type": "rotation", "label": SIGNALS["rotation"], "dir": "long" if mk["kind"] == "entry" else "short",
                                    "strength": 2, "text": f"{rs['bench']} 대비 {mk['text']} — 지금 {rs['now_name']} 구역"})
            except Exception:
                pass
        for sg in out:
            sg.update({"id": f"{symbol}:{interval}:{sg['type']}:{bar_time}", "symbol": symbol, "interval": interval, "price": price, "bar_time": bar_time})
        return out

    def scan(self) -> int:
        n = 0
        for s in list(self.cfg["symbols"]):
            for iv in list(self.cfg["intervals"]):
                try:
                    n += len(self.scan_one(s, iv))
                    self.errors.pop(f"{s}:{iv}", None)
                except Exception as e:   # 한 코인 오류가 전체를 멈추지 않게
                    self.errors[f"{s}:{iv}"] = str(e)[:200]
        self.last_run = time.time()
        if len(self.seen) > 5000:
            self.seen = {s["id"] for s in self.signals}
        return n

    def recent(self, since: int = 0, limit: int = 100) -> list[dict]:
        with _lock:
            return [s for s in reversed(self.signals) if s["created"] > since][:limit]

    def status(self) -> dict:
        keys = [f"{s}:{i}" for s in self.cfg["symbols"] for i in self.cfg["intervals"]]
        return {"config": self.cfg, "labels": SIGNALS, "last_run": int(self.last_run), "errors": self.errors,
                "board": [self.board[k] for k in keys if k in self.board]}

    async def run_forever(self):
        while True:
            if self.cfg.get("enabled"):
                await asyncio.to_thread(self.scan)
            await asyncio.sleep(max(10, int(self.cfg.get("every_sec", 30))))

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self.run_forever())


scanner = Scanner()
