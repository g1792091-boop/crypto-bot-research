"""만약 실험실 (ana7b, #/whatif): "규칙 하나를 바꿨다면?" for the 36 locked strategies (one of them, or all), read from
what was really tested. Read-only; descriptive, not a verdict; the locked rules do not change.

    GET /api/v4/whatif[?strategy=<one of the 36>][&tf=15m|30m|1h|4h]          5-year side + the controls (cheap)
    GET /api/v4/whatif/paper[?strategy=...][&tf=...]                           the nightly shadows (background, cached)

The controls (손절 폭 · 익절 방식 · 첫 잠금 · 시간 청산 · 레버리지·비중) only take values that were tested somewhere, and only
the combinations in ``settings()`` exist: each names its 5-year arm and its nightly shadow (either may be None).

- 5년 (committed research outputs, never recomputed, never written):
  research/levstop/out/levstop.json (PREREG_LEVSTOP.md): 36 strategies x 5 timeframes x 24 arms (leverage mode
  tiers / 10 / 20 / 30 / 40 / 50x x initial stop 1.5 / 2 / 2.5 / 3 ATR, the ladder lock, no time exit);
  research/exitstyle/out/exitstyle.json (PREREG_EXITSTYLE.md): the same signals with fixed take-profits 1R / 1.5R / 2R /
  3R and the ladder capped at 2R, against the ladder (``ladder`` = levstop ``tiers|2.0`` exactly).
  Only the live timeframes (15m-4h) are read. Pooled over the scope's cells: trades, win rate, mean P&L per trade on
  equity (ROE x margin share; ``mean_eq``), liquidation share, accounts busted (one $5,000 account per cell and period),
  cells with a positive mean (all, period 1, period 2). One cell (a strategy on one timeframe): its own period means.
  The 5-year reference of today's rule is ``tiers|2.0`` (v3's tier table 50 -> 20x, 2 ATR, ladder): the nearest tested
  setting; rule B (좋은 자리 50x·50%, else 30x·30% -> 20x·20%) was never run for five years (the page says so).
  Coin flips over five years: research/paper_rules/out_binance/accounts.csv, RANDOM_1..3 with the same house rules at
  stops 1.0 / 1.5 / 2.0 ATR (mean R = net per trade on margin), next to the 36 from the same file.
- 모의 그림자 (daily3.db ``shadows``, opened read-only): the nightly check re-runs every closed trade of the run alone with
  ONE rule changed (paperbot/obsshadows.py; docs/observation-shadows*.md); per variant against the same trades' ``base``
  (P&L on equity, paired): trades, means, difference, better / worse shares, liquidations, not entered, open. For the
  36's accounts (the scope) and, as the comparison, the coin-flip accounts on 15m-4h (the same variant on random
  entries: what the rule change does without any entry skill). DeepSeek accounts are never read here (D10 / D11).
  The whole run is aggregated in ONE pass per daily3 report (every scope at once, ``Heavy``: a first request may answer
  ``pending``); a request reads its scope from that.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sqlite3
import time
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LEVSTOP_JSON = os.path.join(ROOT, "research", "levstop", "out", "levstop.json")
EXITSTYLE_JSON = os.path.join(ROOT, "research", "exitstyle", "out", "exitstyle.json")
COIN5Y_CSV = os.path.join(ROOT, "research", "paper_rules", "out_binance", "accounts.csv")

LIVE_TFS = ("15m", "30m", "1h", "4h")
TTL_S = 3 * 3600                 # per daily3 report: a new nightly report is a new key
WAIT_S = 3.0
SMALL_N = 10                     # riskreward.SMALL_N: fewer paired trades are marked small
LABEL = "설명용, 판정 아님"
STRATEGY_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
CURRENT = {"stop": 2.0, "tp": "ladder", "lock": 0.10, "time": "none", "lev": "rule"}
REF_ARM = "tiers|2.0"
TIME_BARS = {"15m": 12, "30m": 10, "1h": 8, "4h": 6}         # obsshadows.TIME_STOP_BARS (the live timeframes)

# ---------------------------------------------------------------- the controls: tested values only
STOPS = ((1.5, "1.5 ATR"), (2.0, "2 ATR"), (2.5, "2.5 ATR"), (3.0, "3 ATR"))
TPS = (("ladder", "사다리", "계단 잠금: 최고 ROE +12%에서 +10% 잠금, 그 뒤 5%씩"),
       ("tp1R", "고정 1R", "R = 처음 손절 거리. 1R 오르면 익절, 잠금 없음"),
       ("tp1.5R", "고정 1.5R", "1.5R에서 익절, 잠금 없음"),
       ("tp2R", "고정 2R", "2R에서 익절, 잠금 없음"),
       ("tp3R", "고정 3R", "3R에서 익절, 잠금 없음"),
       ("ladder_tp2R", "사다리 + 2R", "계단 잠금은 그대로, 2R에 닿으면 익절"))
LOCKS = ((0.10, "+10%", "+12%에서 +10% 잠금"), (0.15, "+15%", "+17%에서 +15% 잠금"),
         (0.20, "+20%", "+22%에서 +20% 잠금"), (0.30, "+30%", "+32%에서 +30% 잠금"))
TIMES = (("none", "없음", "시간으로는 나가지 않음"),
         ("bars", "N봉 뒤", "잠금이 안 걸린 채 15분 12봉 · 30분 10봉 · 1시간 8봉 · 4시간 6봉이 지나면 시장가"))
LEVS = (("rule", "지금 규칙", "좋은 자리 50배·50% → 40배·40%, 보통 30배·30% → 20배·20%"),
        ("10", "10배·20%", "모든 거래 10배, 증거금 자금의 20%"),
        ("20", "20배·20%", "모든 거래 20배, 증거금 20%"),
        ("30", "30배·30%", "모든 거래 30배, 증거금 30%"),
        ("40", "40배·40%", "모든 거래 40배, 증거금 40%"),
        ("50", "50배·40%", "모든 거래 50배, 증거금 40%"),
        ("50m50", "50배·50%", "모든 거래 50배, 증거금 50%"))
RULE_KO = ("지금 규칙(30일 동안 고정): 처음 손절 2 ATR · 사다리(계단 잠금, 최고 ROE +12%에서 +10% 잠금, 그 뒤 5%씩) · "
           "고정 익절 없음 · 시간 청산 없음 · 레버리지 규칙 B(좋은 자리 50배·50% → 40배·40%, 보통 30배·30% → 20배·20%)")
REF_KO = ("5년 기준 = 지금과 가장 가까운 시험 설정: 손절 2 ATR · 사다리 · v3 단계 레버리지(50배·40% → 40배 → 30배·30% → "
          "20배·20%). 규칙 B(좋은 자리 50배·50%)는 5년으로 따로 돌린 적이 없습니다")
CAVEAT_KO = ("지나고 나서 가장 좋아 보이는 설정을 고르면 과거에 맞춘 것(과최적화)일 뿐입니다. 5년 표만 해도 24가지 × 180칸을 "
             "함께 본 것이라 몇 칸은 우연히 좋아 보입니다. 규칙을 바꾸려면 5년 실험실 관문을 새로 "
             "통과하고, 두 분이 결정하고, 규칙 버전을 올려(v5) 새 계좌로 시작해야 합니다")


def _lev_ko(v: str) -> str:
    return next((ko for k, ko, _d in LEVS if k == v), v)


def settings() -> list[dict]:
    """Every combination that was tested somewhere: {id, stop, tp, lock, time, lev, five, paper, ko}. ``five``:
    "levstop:<arm>" | "exitstyle:<arm>" | None; ``paper``: the nightly shadow variant | None. ``lock`` is None for a
    fixed take-profit (no ladder, so no lock step)."""
    out = []

    def add(stop, tp, lock, tm, lev, five, paper, ko):
        out.append({"id": f"{stop}|{tp}|{lock}|{tm}|{lev}", "stop": stop, "tp": tp, "lock": lock, "time": tm,
                    "lev": lev, "five": five, "paper": paper, "ko": ko})
    add(2.0, "ladder", 0.10, "none", "rule", f"levstop:{REF_ARM}", "base", "지금 규칙")
    for s, sko in STOPS:
        for lev, lko, _d in LEVS:
            if (s, lev) == (2.0, "rule") or lev == "50m50":
                continue
            five = f"levstop:{'tiers' if lev == 'rule' else lev}|{s}"
            paper = (None if s != 2.0 and lev != "rule" else
                     {1.5: "stopw1.5", 2.5: "stopw2.5", 3.0: "stopw3"}.get(s) if lev == "rule" else f"lev{lev}")
            what = [f"손절 {sko}"] if s != 2.0 else []
            what += [f"레버리지 {lko}"] if lev != "rule" else []
            add(s, "ladder", 0.10, "none", lev, five, paper, " · ".join(what))
    add(2.0, "ladder", 0.10, "none", "50m50", None, "lev50m50", "레버리지 50배·50%")
    for tp, tko, _d in TPS[1:5]:
        add(2.0, tp, None, "none", "rule", f"exitstyle:{tp}", tp, f"익절 {tko}")
    add(2.0, "ladder_tp2R", 0.10, "none", "rule", "exitstyle:ladder_tp2R", "ladder_cap2R", "사다리 + 2R 익절")
    for lk, lko, _d in LOCKS[1:]:
        add(2.0, "ladder", lk, "none", "rule", None, f"lock{int(round(lk * 100))}", f"첫 잠금 {lko}")
    add(2.0, "ladder", 0.10, "bars", "rule", None, "timestop", "시간 청산 N봉")
    return out


def controls() -> dict:
    return {"stop": [{"v": v, "ko": ko, "now": v == CURRENT["stop"]} for v, ko in STOPS],
            "tp": [{"v": v, "ko": ko, "d": d, "now": v == CURRENT["tp"]} for v, ko, d in TPS],
            "lock": [{"v": v, "ko": ko, "d": d, "now": v == CURRENT["lock"]} for v, ko, d in LOCKS],
            "time": [{"v": v, "ko": ko, "d": d, "now": v == CURRENT["time"]} for v, ko, d in TIMES],
            "lev": [{"v": v, "ko": ko, "d": d, "now": v == CURRENT["lev"]} for v, ko, d in LEVS]}


# ---------------------------------------------------------------- the scope
def strategies_ko() -> dict:
    from ...agents.roster3 import STRATEGY_KO
    return dict(STRATEGY_KO)


def scope(strategy: Optional[str], tf: Optional[str]) -> dict:
    """The checked scope: strategy one of the 36 or None (all), tf one of LIVE_TFS or None (all). Anything else is a
    400 (never silently the whole group under a strategy's name)."""
    from fastapi import HTTPException
    names = strategies_ko()
    s = (strategy or "").strip() or None
    t = (tf or "").strip() or None
    if s is not None and (not STRATEGY_RE.match(s) or s not in names):
        raise HTTPException(400, "strategy는 잠긴 36개 매매법 이름 중 하나입니다")
    if t is not None and t not in LIVE_TFS:
        raise HTTPException(400, "tf는 15m · 30m · 1h · 4h 중 하나입니다")
    return {"strategy": s, "tf": t, "name_ko": names.get(s) if s else "기존 36 전체",
            "tfs": [t] if t else list(LIVE_TFS)}


def _cells(sc: dict) -> list[str]:
    names = [sc["strategy"]] if sc["strategy"] else sorted(strategies_ko())
    return [f"{s}|{tf}" for s in names for tf in sc["tfs"]]


# ---------------------------------------------------------------- 5 years
_CACHE: dict = {}


def _load_json(path: str) -> Optional[dict]:
    try:
        m = os.path.getmtime(path)
    except OSError:
        return None
    hit = _CACHE.get(path)
    if hit and hit[0] == m:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        doc = None
    doc = doc if isinstance(doc, dict) and doc.get("version") == 1 and isinstance(doc.get("cells"), dict) else None
    _CACHE[path] = (m, doc)
    return doc


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _r(x: Optional[float], n: int = 6) -> Optional[float]:
    return None if x is None else round(float(x), n)


def _median(xs: list) -> Optional[float]:
    v = sorted(x for x in xs if x is not None)
    if not v:
        return None
    k = len(v) // 2
    return v[k] if len(v) % 2 else (v[k - 1] + v[k]) / 2


def _wmean(pairs: list) -> Optional[float]:
    """Trade-weighted mean of (n, mean) pairs (pairs with n = 0 or a missing mean are left out)."""
    n = sum(w for w, m in pairs if w and m is not None)
    return sum(w * m for w, m in pairs if w and m is not None) / n if n else None


def pool_levstop(doc: dict, keys: list, arm: str) -> dict:
    """One levstop arm pooled over ``keys`` (cells "<strategy>|<tf>"): see the module docstring."""
    cols = list(doc.get("columns") or [])
    ix = {c: i for i, c in enumerate(cols)}
    rows = []
    for k in keys:
        v = ((doc.get("cells") or {}).get(k) or {}).get(arm)
        if isinstance(v, list):
            rows.append({c: (v[i] if i < len(v) else None) for c, i in ix.items()})
    traded = [r for r in rows if (r.get("trades") or 0) > 0]
    n = sum(int(r["trades"]) for r in traded)
    busts = [r.get(b) for r in rows for b in ("bust_p1", "bust_p2") if r.get(b) is not None]
    mults = [r.get(m) for r in rows for m in ("mult_p1", "mult_p2") if r.get(m) is not None]
    out = {"cells": len(rows), "cells_traded": len(traded), "trades": n,
           "signals": sum(int(r.get("signals") or 0) for r in rows),
           "win_rate": _r(_wmean([(r["trades"], r.get("win_rate")) for r in traded]), 4),
           "mean_eq": _r(_wmean([(r["trades"], r.get("mean_eq")) for r in traded])),
           "mean_roe": _r(_wmean([(r["trades"], r.get("mean_roe")) for r in traded])),
           "liq_share": _r(_wmean([(r["trades"], r.get("liq_share")) for r in traded]), 5),
           "busts": sum(1 for b in busts if b), "accounts": len(busts),
           "mult_median": _r(_median(mults), 4),
           "cells_pos": sum(1 for r in traded if (r.get("mean_eq") or 0) > 0),
           "cells_pos_p1": sum(1 for r in traded if (r.get("mean_eq_p1") or 0) > 0),
           "cells_pos_p2": sum(1 for r in traded if (r.get("mean_eq_p2") or 0) > 0),
           "cells_both": sum(1 for r in traded if (r.get("mean_eq_p1") or 0) > 0 and (r.get("mean_eq_p2") or 0) > 0)}
    if len(rows) == 1:
        r = rows[0]
        out.update(mean_eq_p1=_r(r.get("mean_eq_p1")), mean_eq_p2=_r(r.get("mean_eq_p2")))
    return out


def pool_exitstyle(doc: dict, keys: list, arm: str) -> dict:
    """One exitstyle arm pooled over ``keys``; period means weighted by each cell's paired trades of that period, the
    paired difference against the ladder (same signals, both closed) weighted by the paired trades."""
    cols = list(doc.get("columns") or [])
    ix = {c: i for i, c in enumerate(cols)}
    rows = []
    for k in keys:
        v = ((doc.get("cells") or {}).get(k) or {}).get(arm)
        if isinstance(v, list):
            rows.append({c: (v[i] if i < len(v) else None) for c, i in ix.items()})
    traded = [r for r in rows if (r.get("trades") or 0) > 0]
    busts = [r.get(b) for r in rows for b in ("bust_p1", "bust_p2") if r.get(b) is not None]
    out = {"cells": len(rows), "cells_traded": len(traded), "trades": sum(int(r["trades"]) for r in traded),
           "win_rate": _r(_wmean([(r["trades"], r.get("win_rate")) for r in traded]), 4),
           "mean_eq": _r(_wmean([(r["trades"], r.get("mean_eq")) for r in traded])),
           "mean_eq_p1": _r(_wmean([(r.get("paired_n_p1"), r.get("mean_eq_p1")) for r in traded])),
           "mean_eq_p2": _r(_wmean([(r.get("paired_n_p2"), r.get("mean_eq_p2")) for r in traded])),
           "liq_share": _r(_wmean([(r["trades"], r.get("liq_share")) for r in traded]), 5),
           "tp_share": _r(_wmean([(r["trades"], r.get("tp_share")) for r in traded]), 4),
           "mean_held": _r(_wmean([(r["trades"], r.get("mean_held")) for r in traded]), 2),
           "paired": sum(int(r.get("paired_n") or 0) for r in traded),
           "diff": _r(_wmean([(r.get("paired_n"), r.get("diff")) for r in traded])),
           "diff_p1": _r(_wmean([(r.get("paired_n_p1"), r.get("diff_p1")) for r in traded])),
           "diff_p2": _r(_wmean([(r.get("paired_n_p2"), r.get("diff_p2")) for r in traded])),
           "cells_better": sum(1 for r in traded if (r.get("diff") or 0) > 0),
           "busts": sum(1 for b in busts if b), "accounts": len(busts),
           "cells_pos": sum(1 for r in traded if (r.get("mean_eq") or 0) > 0),
           "cells_pos_p1": sum(1 for r in traded if (r.get("mean_eq_p1") or 0) > 0),
           "cells_pos_p2": sum(1 for r in traded if (r.get("mean_eq_p2") or 0) > 0),
           "cells_both": sum(1 for r in traded if (r.get("mean_eq_p1") or 0) > 0 and (r.get("mean_eq_p2") or 0) > 0)}
    return out


_COIN: dict = {}


def _coin_rows(path: str) -> Optional[list]:
    try:
        m = os.path.getmtime(path)
    except OSError:
        return None
    hit = _COIN.get(path)
    if hit and hit[0] == m:
        return hit[1]
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, ValueError, csv.Error):
        rows = None
    _COIN[path] = (m, rows)
    return rows


def coin_five_year(sc: dict, path: str = COIN5Y_CSV) -> dict:
    """The 5-year coin flips under the same house rules (research/paper_rules, Binance signal cache): per stop width
    k (1.5 / 2.0 ATR), the three RANDOM accounts per timeframe and period next to the 36 (or the scope's strategy)
    from the same file: accounts, trades, pooled mean R (net per trade on margin), win rate, busts."""
    rows = _coin_rows(path)
    if not rows:
        return {"ready": False, "why": "5년 동전 봇 결과 파일 없음 (research/paper_rules/out_binance/accounts.csv)"}
    names = {sc["strategy"]} if sc["strategy"] else set(strategies_ko())
    out: dict = {"ready": True, "by_k": {}, "source": "research/paper_rules (PREREG_RULES.md, out_binance)",
                 "note": ("같은 하우스 규칙(v3 단계 레버리지, 사다리)을 5년 신호에 계좌마다 한 번에 한 포지션으로 돌린 결과. "
                          "평균 R = 거래당 증거금 대비 순손익. 동전 봇은 봉마다 무작위로 들어감 (봉마다 3개, 기간 2개)")}
    for k in ("1.5", "2.0"):
        part = {}
        for who, pick in (("flips", lambda r: r["strategy"].startswith("RANDOM")),
                          ("core", lambda r: r["strategy"] in names)):
            rs = [r for r in rows if r.get("k") == k and r.get("tf") in sc["tfs"] and pick(r)]
            n = sum(int(_num(r.get("trades")) or 0) for r in rs)
            part[who] = {"accounts": len(rs), "trades": n,
                         "mean_r": _r(_wmean([(_num(r.get("trades")) or 0, _num(r.get("mean_R"))) for r in rs])),
                         "win_rate": _r(_wmean([(_num(r.get("trades")) or 0, _num(r.get("win"))) for r in rs]), 4),
                         "busts": sum(1 for r in rs if str(r.get("bust")).strip().lower() == "true")}
        out["by_k"][k] = part
    return out


def five_year(sc: dict, levstop_path: str = LEVSTOP_JSON, exitstyle_path: str = EXITSTYLE_JSON,
              coin_path: str = COIN5Y_CSV) -> dict:
    keys = _cells(sc)
    out: dict = {"label": LABEL, "ref": f"levstop:{REF_ARM}", "ref_ko": REF_KO}
    ls = _load_json(levstop_path)
    if ls is None:
        out["levstop"] = {"ready": False, "why": "5년 레버리지·손절 결과 파일 없음 (research/levstop/out/levstop.json)"}
    else:
        arms = [f"{m}|{s}" for m in ls.get("lev_modes") or [] for s in ls.get("stops_atr") or []]
        out["levstop"] = {"ready": True, "generated": ls.get("generated"), "periods": ls.get("periods"),
                          "margin_frac": ls.get("margin_frac"), "source": "research/levstop (PREREG_LEVSTOP.md)",
                          "arms": {a: pool_levstop(ls, keys, a) for a in arms}}
    ex = _load_json(exitstyle_path)
    if ex is None:
        out["exitstyle"] = {"ready": False, "why": "5년 익절 방식 결과 파일 없음 (research/exitstyle/out/exitstyle.json)"}
    else:
        dec = ((ex.get("summary") or {}).get("decision") or {})
        out["exitstyle"] = {"ready": True, "generated": ex.get("generated"), "periods": ex.get("periods"),
                            "source": "research/exitstyle (PREREG_EXITSTYLE.md)",
                            "recommend": dec.get("recommend") if isinstance(dec, dict) else None,
                            "arms": {a: pool_exitstyle(ex, keys, a) for a in (ex.get("arms") or {})}}
    out["coin"] = coin_five_year(sc, coin_path)
    out["cells_ko"] = (f"{sc['name_ko']} · {'·'.join(sc['tfs'])} · {len(keys)}칸"
                       if sc["strategy"] or sc["tf"] else f"기존 36 × 15분·30분·1시간·4시간 · {len(keys)}칸")
    return out


def view(strategy: Optional[str], tf: Optional[str], **paths) -> dict:
    sc = scope(strategy, tf)
    names = strategies_ko()
    return {"label": LABEL, "scope": sc, "current": CURRENT, "rule_ko": RULE_KO, "caveat_ko": CAVEAT_KO,
            "controls": controls(), "settings": settings(), "time_bars": TIME_BARS,
            "strategies": [{"id": s, "ko": names[s]} for s in sorted(names)],
            "five_year": five_year(sc, **paths)}


# ---------------------------------------------------------------- the nightly shadows (paper, forward)
VARIANTS = ("lock15", "lock20", "lock30", "timestop", "lev10", "lev20", "lev30", "lev40", "lev50", "stopw1.5",
            "stopw2.5", "stopw3", "tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_cap2R", "lev20m20", "lev30m30",
            "lev40m40", "lev50m50")      # riskreward.ALL_SHADOWS


def _utc_day(ms: int) -> str:
    return dt.datetime.fromtimestamp(max(0, int(ms)) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def _acc() -> list:
    # n, sum variant, sum base, better, worse, liq, base liq, not entered, open, tp
    return [0, 0.0, 0.0, 0, 0, 0, 0, 0, 0, 0]


def _cell(a: list) -> dict:
    n = a[0]
    out = {"trades": n}
    for k, v in (("not_entered", a[7]), ("open", a[8]), ("tp", a[9])):
        if v:
            out[k] = v
    if n:
        out.update(mean_eq=round(a[1] / n, 6), base_mean_eq=round(a[2] / n, 6), vs_base_eq=round((a[1] - a[2]) / n, 6),
                   better_share=round(a[3] / n, 4), worse_share=round(a[4] / n, 4), liq=a[5], base_liq=a[6])
    if n < SMALL_N:
        out["small"] = True
    return out


def _pe(data: Any) -> Optional[float]:
    try:
        d = json.loads(data or "{}")
    except (TypeError, ValueError):
        return None
    return _num(d.get("pnl_equity")) if isinstance(d, dict) else None


def report_info(daily_ro: Optional[sqlite3.Connection]) -> Optional[dict]:
    if daily_ro is None:
        return None
    try:
        r = daily_ro.execute("SELECT day, ts FROM reports ORDER BY ts DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        return None
    return {"day": r[0], "ts": int(r[1])} if r else None


def paper_all(paper_db: str, daily_db: Optional[str], now_ms: int) -> dict:
    """Every scope at once: {"ready", "since", "days", "report", "scopes": {key: {"base": {...}, "variants": {...}}}}.
    Keys: "core", "core|<tf>", "core|<strategy>", "core|<strategy>|<tf>", "coin", "coin|<tf>" (coin = the 15m-4h coin
    flips). DeepSeek, the reel, its 5m flips, copies and new-strategy accounts are not read: the queries name the
    scope's own account ids, so their rows never leave the database file, and the rows are streamed (two passes: the
    base shadows, then the variants), never all held at once."""
    from ..analysis import _close, ro_connect
    c = ro_connect(paper_db)
    d = ro_connect(daily_db)
    out: dict = {"label": LABEL, "ready": False, "since": 0, "scopes": {}, "small_n": SMALL_N}
    try:
        if c is None:
            out["why"] = "봇 기록(paper3.db)을 찾지 못했습니다"
            return out
        try:
            from ...checkpoint import run_facts
            start = int(run_facts(c).get("start_ts") or 0)
            accts = c.execute("SELECT account_id, strategy, timeframe, kind FROM accounts "
                              "WHERE kind IN ('strategy', 'random')").fetchall()
        except sqlite3.Error as exc:
            out["why"] = f"봇 기록(paper3.db)을 읽지 못했습니다 ({type(exc).__name__})"
            return out
        out["since"] = start
        who = {}
        for aid, s, tf, kind in accts:
            if tf not in LIVE_TFS:
                continue                       # the three 5m coin flips run the reel's exits: no house shadows
            who[aid] = ("core", s, tf) if kind == "strategy" else ("coin", None, tf)
        out["accounts"] = {"core": sum(1 for v in who.values() if v[0] == "core"),
                           "coin": sum(1 for v in who.values() if v[0] == "coin")}
        if d is None:
            out["why"] = "밤 점검 기록이 아직 없습니다 (첫 점검은 시작 다음 날 09:20, 전날 끝난 거래로 채움)"
            return out
        out["report"] = report_info(d)
        lo, hi = _utc_day(start) if start else "0000-00-00", _utc_day(max(int(now_ms) - 1, 0))
        out["days"] = [lo, hi]

        def keys_of(aid: str) -> list:
            g, s, tf = who[aid]
            return [g, f"{g}|{tf}"] + ([f"{g}|{s}", f"{g}|{s}|{tf}"] if s else [])

        ids = sorted(who)
        ids_sql = ",".join("?" * len(ids))
        base: dict = {}                        # trade tail -> (pnl on equity, reason)
        scopes: dict = {}
        bases: dict = {}
        n_rows = 0
        try:
            if ids:
                for key, aid, reason, data in d.execute(
                        f"SELECT key, account_id, exit_reason, data FROM shadows WHERE day >= ? AND day <= ? "
                        f"AND kind = 'base' AND resolved != 0 AND roe IS NOT NULL AND account_id IN ({ids_sql})",
                        (lo, hi, *ids)):
                    n_rows += 1
                    pe = _pe(data)
                    if pe is None or aid not in who:
                        continue
                    base[str(key).split("|", 1)[-1]] = (pe, reason)
                    for k in keys_of(aid):
                        b = bases.setdefault(k, [0, 0.0])
                        b[0] += 1
                        b[1] += pe
                for key, kind, aid, roe, reason, resolved, data in d.execute(
                        f"SELECT key, kind, account_id, roe, exit_reason, resolved, data FROM shadows "
                        f"WHERE day >= ? AND day <= ? AND kind IN ({','.join('?' * len(VARIANTS))}) "
                        f"AND account_id IN ({ids_sql})", (lo, hi, *VARIANTS, *ids)):
                    n_rows += 1
                    if aid not in who:
                        continue
                    accs = [scopes.setdefault(k, {}).setdefault(kind, _acc()) for k in keys_of(aid)]
                    if not resolved:
                        for a in accs:
                            a[8] += 1
                        continue
                    if roe is None:
                        for a in accs:
                            a[7] += 1
                        continue
                    b = base.get(str(key).split("|", 1)[-1])
                    pe = _pe(data) if b is not None else None
                    if b is None or pe is None:
                        continue
                    better, worse = pe > b[0] + 1e-12, pe < b[0] - 1e-12
                    for a in accs:
                        a[0] += 1
                        a[1] += pe
                        a[2] += b[0]
                        a[3] += better
                        a[4] += worse
                        a[5] += reason == "LIQ"
                        a[6] += b[1] == "LIQ"
                        a[9] += reason == "TP"
        except sqlite3.Error as exc:
            out["why"] = f"밤 점검 그림자 기록을 읽지 못했습니다 ({type(exc).__name__})"
            return out
    finally:
        _close(c, d)

    out["scopes"] = {k: {"base": {"trades": bases.get(k, [0, 0.0])[0],
                                  "mean_eq": (round(bases[k][1] / bases[k][0], 6) if bases.get(k, [0])[0] else None)},
                         "variants": {v: _cell(a) for v, a in scopes.get(k, {}).items()}}
                     for k in set(scopes) | set(bases)}
    out["ready"] = True
    out["rows"] = n_rows
    return out


def paper_job(paper_db: str, daily_db: Optional[str], now_ms: int) -> dict:
    """``paper_all`` for the background cache: a not-ready answer (no daily3.db yet, an unreadable file) carries
    ``error`` so ``Heavy`` keeps it 60 s only (dash/analysis.ERROR_TTL_S) instead of the report's 3 hours: the first
    nightly report shows up on the page within a minute."""
    out = paper_all(paper_db, daily_db, now_ms)
    if not out.get("ready"):
        out["error"] = out.get("why") or "그림자 기록 없음"
    return out


def paper_scope(allp: dict, sc: dict) -> dict:
    """The scope's part of ``paper_all`` (+ the coin flips of the scope's timeframe(s))."""
    if not allp.get("ready"):
        return {k: v for k, v in allp.items() if k != "scopes"}
    s, tf = sc["strategy"], sc["tf"]
    key = "core" + (f"|{s}" if s else "") + (f"|{tf}" if tf else "")
    ckey = "coin" + (f"|{tf}" if tf else "")
    empty = {"base": {"trades": 0, "mean_eq": None}, "variants": {}}
    sp = allp["scopes"].get(key) or empty
    cp = allp["scopes"].get(ckey) or empty
    return {"label": LABEL, "ready": True, "since": allp.get("since"), "days": allp.get("days"),
            "report": allp.get("report"), "small_n": SMALL_N, "accounts": allp.get("accounts"),
            "scope": sc, "base": sp["base"], "variants": sp["variants"], "coin": cp,
            "computed_at": allp.get("computed_at"), "stale": allp.get("stale"),
            "note": ("밤 점검(매일 09:20)이 전날 끝난 실제 거래를 규칙 하나만 바꿔 혼자 다시 돌린 기록. 차이 = 그 그림자 평균 − 같은 "
                     "거래를 지금 규칙 그대로 다시 돌린 평균, 거래당 자금 대비. 10건 미만은 표본 적음. 동전 봇 = 15분~4시간 동전 "
                     "계좌의 같은 그림자. " + LABEL)}


def register(app, ctx) -> dict:
    from ..analysis import Heavy, report_key
    heavy = getattr(app.state, "analysis", None)
    if not isinstance(heavy, Heavy):         # registered without the analysis routes (tests): its own one-at-a-time
        heavy = Heavy()

    @app.get("/api/v4/whatif")
    def get_whatif(strategy: Optional[str] = None, tf: Optional[str] = None):
        """만약 실험실: the controls, the tested settings and the 5-year side for the scope (files only, cached)."""
        return view(strategy, tf)

    @app.get("/api/v4/whatif/paper")
    def get_whatif_paper(strategy: Optional[str] = None, tf: Optional[str] = None):
        """만약 실험실: the nightly shadows of the scope and of the coin flips; background + cached per daily3 report."""
        sc = scope(strategy, tf)
        rk = report_key(ctx.daily_db)
        got = heavy.get(f"whatif-paper:{rk}", TTL_S,
                        lambda: paper_job(ctx.db, ctx.daily_db, int(time.time() * 1000)), wait_s=WAIT_S)
        if got.get("pending"):
            return got
        return paper_scope(got, sc)

    return {"routes": ["/api/v4/whatif", "/api/v4/whatif/paper"]}
