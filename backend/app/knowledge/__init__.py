"""연구 지식 + 시그널 성적 학습 메모리.

- cards.json: 다른 연구 세션(코인 자동매매봇 에이전트팀)이 약 3,500개 셋업을 백테스트해서 얻은 규칙 카드
  (validated 검증 / rejected 기각 / hypothesis 가설). 출처는 research-summary.md.
- lessons(): 이 앱의 AI 시그널이 실제 차트에서 익절·손절된 결과를 코인·봉·방향·엔진별로 모은 '경험'.
두 가지를 모든 AI 호출(코파일럿·에이전트 팀·자동 분석·오토파일럿·전략 만들기)의 시스템 프롬프트에 붙인다.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from .. import config

_DIR = Path(__file__).parent
_cards: list[dict] | None = None
STATUS_KO = {"validated": "검증", "rejected": "기각", "hypothesis": "가설"}
SKIP_FEATURES = {"news"}          # 뉴스 번역 등 매매 판단이 아닌 호출에는 붙이지 않는다

HEADLINE = ("연구 결과 요약: 5분~1일봉에서 약 3,500개 셋업(지표·주문흐름·호가·펀딩·시간대·유명 매매법)을 백테스트했지만 "
            "확인 구간(out-of-sample)을 통과한 것은 0개였다. 단기봉은 왕복 비용 약 0.14% 가 기대값을 지배하고, "
            "고레버리지는 수학적으로 불리하다. 그러니 확신을 과장하지 말고, 비용·레버리지·표본 수를 먼저 따진다.")


def cards() -> list[dict]:
    global _cards
    if _cards is None:
        _cards = []
        for d in (_DIR, config.ROOT_DIR / "app" / "knowledge"):      # 설치판(PyInstaller)에서는 압축 해제 폴더
            try:
                _cards = json.loads((d / "cards.json").read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                continue
    return _cards


def _base(symbol: str | None) -> str | None:
    return symbol.upper().removesuffix("USDT").removesuffix("USDC") if symbol else None


def _applies(c: dict, symbol: str | None, interval: str | None) -> bool:
    a = c.get("applies") or {}
    tf, sy = a.get("timeframes"), a.get("symbols")
    if interval and isinstance(tf, list) and interval not in tf:
        return False
    if symbol and isinstance(sy, list) and _base(symbol) not in sy:
        return False
    return True


def relevant(symbol: str | None = None, interval: str | None = None, limit: int = 14) -> list[dict]:
    """해당 코인·봉에 맞는 카드부터 (검증 → 기각 → 가설), 모자라면 전체 공통 카드로 채운다."""
    order = {"validated": 0, "rejected": 1, "hypothesis": 2}
    cs = sorted(cards(), key=lambda c: (order.get(c["status"], 3), c["id"]))
    hit = [c for c in cs if _applies(c, symbol, interval)]
    hit += [c for c in cs if c not in hit and (c.get("applies") or {}).get("timeframes") == "all"]
    quota = {"validated": round(limit * .62), "rejected": round(limit * .28), "hypothesis": 1}
    out = []
    for st, q in quota.items():
        out += [c for c in hit if c["status"] == st][:q]
    out += [c for c in hit if c not in out]           # 남는 자리는 나머지 관련 카드로
    return sorted(out[:limit], key=lambda c: (order.get(c["status"], 3), c["id"]))


def brief(symbol: str | None = None, interval: str | None = None, limit: int = 14) -> str:
    rows = [f"- [{c['id']}·{STATUS_KO.get(c['status'], c['status'])}·{c['topic']}] {c['rule']}" for c in relevant(symbol, interval, limit)]
    return HEADLINE + "\n" + "\n".join(rows) if rows else ""


# ------------------------------------------------------------------ 시그널 성적 학습
_lessons: dict = {"at": 0.0, "data": None, "busy": False}
MIN_N = 30           # k23: 30건 미만은 패턴이라 부르지 않는다


def _group(rows: list[dict], key) -> list[dict]:
    g: dict = {}
    for r in rows:
        k = key(r)
        b = g.setdefault(k, {"key": k, "n": 0, "wins": 0, "r": 0.0})
        b["n"] += 1
        b["wins"] += r["outcome"]["status"] == "take"
        b["r"] += float(r["outcome"].get("r") or 0)
    out = []
    for b in g.values():
        out.append({"key": b["key"], "n": b["n"], "win_rate": round(b["wins"] / b["n"] * 100, 1),
                    "avg_r": round(b["r"] / b["n"], 2), "pattern": b["n"] >= MIN_N})
    return sorted(out, key=lambda x: -x["n"])


def _compute() -> dict:
    from .. import aibot
    rows = [r for r in aibot.compute()["signals"] if (r.get("outcome") or {}).get("status") in ("take", "stop")]
    conf = lambda r: "확신 70+" if (r.get("confidence") or 0) >= 70 else "확신 55~69" if (r.get("confidence") or 0) >= 55 else "확신 <55"
    eng = lambda r: "규칙" if r.get("engine") in (None, "rules") else "AI"
    return {"total": len(rows), "updated": int(time.time()),
            "overall": _group(rows, lambda r: "전체"),
            "by_engine": _group(rows, eng),
            "by_side": _group(rows, lambda r: "롱" if r["side"] == "long" else "숏"),
            "by_interval": _group(rows, lambda r: r["interval"]),
            "by_symbol": _group(rows, lambda r: r["symbol"]),
            "by_confidence": _group(rows, conf),
            "by_symbol_interval_side": _group(rows, lambda r: f"{r['symbol']} {r['interval']} {'롱' if r['side'] == 'long' else '숏'}")}


def _refresh() -> None:
    try:
        _lessons["data"] = _compute()
    except Exception:  # noqa: BLE001 — 학습 메모리는 없어도 분석은 돌아간다
        pass
    finally:
        _lessons["at"] = time.time()
        _lessons["busy"] = False


def lessons(wait: bool = False) -> dict | None:
    """10분마다 백그라운드에서 다시 계산 (AI 호출을 막지 않는다)."""
    if time.time() - _lessons["at"] > 600 and not _lessons["busy"]:
        _lessons["busy"] = True
        if wait:
            _refresh()
        else:
            threading.Thread(target=_refresh, daemon=True).start()
    return _lessons["data"]


def lessons_text(symbol: str | None = None, interval: str | None = None) -> str:
    d = lessons()
    if not d or not d["total"]:
        return ""
    def line(x):
        tag = "" if x["pattern"] else " (표본 부족 — 패턴 아님)"
        return f"{x['key']}: {x['n']}건 적중 {x['win_rate']}% 평균 {x['avg_r']:+}R{tag}"
    o = d["overall"][0]
    out = [f"이 앱 AI 시그널의 실제 결과 (익절·손절 확정 {d['total']}건, 비용 전 R): {line(o)}"]
    for name, k in (("엔진", "by_engine"), ("방향", "by_side"), ("봉", "by_interval"), ("확신도", "by_confidence")):
        if d[k]:
            out.append(f"- {name}별: " + " / ".join(line(x) for x in d[k][:4]))
    if symbol:
        mine = [x for x in d["by_symbol_interval_side"] if x["key"].startswith(symbol + " ") and (not interval or f" {interval} " in x["key"])]
        if mine:
            out.append("- 이 코인: " + " / ".join(line(x) for x in mine[:4]))
    bad = [x for x in d["by_symbol_interval_side"] if x["pattern"] and x["avg_r"] < 0][:3]
    if bad:
        out.append("- 30건 이상 쌓였는데 손실인 조합 (같은 시그널 반복 금지): " + " / ".join(line(x) for x in bad))
    out.append("이 성적을 근거로 확신도를 조정하라: 손실 조합은 확신을 낮추거나 관망, 30건 미만은 우연일 수 있다.")
    return "\n".join(out)


# ------------------------------------------------------------------ 프롬프트 주입 · 경고
_SYM = re.compile(r"\b([A-Z0-9]{2,15}USDT)\b")
_IV = re.compile(r"[\"'\s(]((?:1|3|5|15|30)m|(?:1|2|4|6|8|12)h|1d|1w)\b")


def enabled() -> bool:
    return getattr(config, "KNOWLEDGE", True)


def block(symbol: str | None = None, interval: str | None = None) -> str:
    parts = [brief(symbol, interval)]
    t = lessons_text(symbol, interval)
    if t:
        parts.append(t)
    return "\n\n".join(p for p in parts if p)


def inject(system: str, user: str = "", feature: str | None = None) -> str:
    """시스템 프롬프트 끝에 연구 카드 + 성적 메모리를 붙인다 (사용자 입력에서 코인·봉을 찾아 관련 카드 우선)."""
    if not enabled() or feature in SKIP_FEATURES or "[연구 지식]" in system:
        return system
    m, iv = _SYM.search(user or ""), _IV.search(user or "")
    b = block(m.group(1) if m else None, iv.group(1) if iv else None)
    if not b:
        return system
    return (system + "\n\n[연구 지식] 아래는 실제 백테스트·실거래 결과로 얻은 규칙이다. 판단할 때 반드시 반영하고, "
            "카드와 반대되는 주장을 할 때는 근거를 대라. 기각된 근거만으로 진입을 권하지 마라.\n" + b)


def warnings(interval: str | None, leverage: float | None = None, rr: float | None = None) -> list[str]:
    """카드 기반 규칙 경고 (AI 없이도 표시)."""
    w = []
    if interval in ("1m", "3m", "5m"):
        w.append("k13·k14: 5분 이하 봉은 비용이 가장 크게 작용 — 연구에서 가장 빨리 손실이 났습니다.")
    elif interval in ("15m", "30m", "1h"):
        w.append("k01: 15분~1시간 봉은 왕복 비용 약 0.14% 를 넘는 근거가 필요합니다.")
    if leverage and leverage >= 10:
        w.append(f"k06·k10: {leverage:g}배 — 고레버리지는 본전 승률이 70~88% 까지 올라갑니다. 3배 이하 권장.")
    if rr is not None and rr < 1:
        w.append("k04·k05: 손익비 1 미만 — 승률이 높아 보여도 평균 R 이 음수일 수 있습니다.")
    return w
