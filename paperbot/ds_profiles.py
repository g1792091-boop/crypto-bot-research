"""5-year research cards of the paper-v4 strategies outside the 36: the 44 DeepSeek-200 definitions and the reel.

The 36 have their card in research/strategy_profiles (agents/packets3.profile_card). The v4 strategies get the same
kind of table here, per timeframe and per research period: trades per day, net per trade, win rate, hold. It is read
from the research output files only and never recomputed:

    DeepSeek  research/deepseek200/out/results.csv   one row per (timeframe, definition, exit); 342 rows
              research/deepseek200/out/summary.json  the run's gauntlet counts and lib_c.py sha256
    reel      research/reel5m/out/h1.json            H1 (5m / BB_SMA200_CLOSE_LONG / SWING_BAND), its three periods
              research/reel5m/out/per_variant.csv    the same idea's variants (moving average, breach, sides),
                                                     each averaged over its 20 configurations of the grid
              research/reel5m/out/h1_by_year.csv     H1 per calendar year (all three periods together)

EXITS ARE NOT THE LIVE ONES FOR DEEPSEEK. The DeepSeek research measured each definition with two ATR exits
(X5_TRAIL2: 2 ATR stop + 2 ATR trailing stop; X2_SL15_TP3: 1.5 ATR stop, 3 ATR target; at most 48 bars). The live
DeepSeek paper accounts use the house exits (2 ATR stop + the profit-lock ladder, "normal" leverage), which the
research engine cannot run (PREREG_DEEPSEEK200.md section 7). The reel was measured with its own exits (stop under
the swing low, target at the previous bar's upper band, 96 bars) and its live account uses those same exits
(paperbot/reel_engine.py; checked on 1m bars live, see its docstring for the documented differences).

Units. ``net_pct`` / ``gross_pct`` / ``cost_pct``: per trade, price % of the entry, no leverage; net is after the
research costs (taker fee and slippage both sides, funding), but the split differs per group (``cost_note_ko``):
DeepSeek's gross is already after slippage (lib_c fills at the slipped price), so its cost is fee + funding only;
the reel's gross is before slippage, so its cost is fee + slippage + funding. Compare ``net_pct`` across groups, not
``gross_pct`` / ``cost_pct``. ``per_day``: TRADES (not signals) per calendar day of the period's signal window, the
six coins together (F14_SMT: five, BTC is its reference); each coin holds one research position at a time. A live
paper account holds one position across all six coins (reel_engine.py difference 4; the house engine the same), so
live trades per day are lower than these. ``hold_bars`` / ``hold_hours``: the mean hold (DeepSeek) or the median
hold (reel) in bars of the timeframe. ``win_pct``: share of trades with net > 0. ``small``: fewer than 20 trades.

Periods (signal-bar times, UTC; the research code's PERIODS): "is" 1기 2021-08-01..2024-07-01 (고르기), "cf" 2기
2024-07-01..2026-09-30 (확인; the reel files call it "oos"), "pre" 3기 2020-01-01..2021-08-01 (최종). A window
starts after the warm-up (max(300 bars, 30 days) from the series' first bar) and ends max-hold + 1 bars before its
end, as the research's window_idx does; ``window_days`` repeats that arithmetic for the per-day rate. Some coins'
period-3 series start later (data/pre2021: LTC 2020-01-09, DOGE 2020-07-10, SOL 2020-09-14), so period 3 has
fewer coin-days than six times its length: its per-day rate counts the trades that were there.

Descriptive only: what the rule did on five years of the same data, not evidence of skill. The DeepSeek run found no
candidate among its 342 configurations and the reel's H1 failed its pre-registered test (both reports in research/).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
from typing import Optional

from .config import DS200_DEFS, DS200_FAMILY, REEL_NAME, REEL_TF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS_OUT = os.path.join(ROOT, "research", "deepseek200", "out")
DS_RESULTS = os.path.join(DS_OUT, "results.csv")
DS_SUMMARY = os.path.join(DS_OUT, "summary.json")
REEL_OUT = os.path.join(ROOT, "research", "reel5m", "out")

TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
SMALL_N = 20

# (key, Korean label, role, start, end); the research's PERIODS, signal-bar times UTC
PERIODS = (
    ("is", "1기", "고르기", "2021-08-01", "2024-07-01"),
    ("cf", "2기", "확인", "2024-07-01", "2026-09-30"),
    ("pre", "3기", "최종", "2020-01-01", "2021-08-01"),
)
SERIES_START = {"is": "2021-01-01", "cf": "2021-01-01", "pre": "2020-01-01"}   # first bar of the series it lives in
DS_MAX_HOLD = 48            # lib_c.MAX_HOLD
REEL_MAX_HOLD = 96          # lib_reel5m.MAX_HOLD
REEL_H1 = ("5m", "BB_SMA200_CLOSE_LONG", "SWING_BAND")

DS_EXITS = (
    {"id": "X5_TRAIL2", "ko": "2 ATR 손절 + 고점에서 2 ATR 되돌리면 청산(추적 손절), 최대 48봉",
     "note_ko": "연구에서 라이브 청산에 가장 가까운 방식으로 쓴 것"},
    {"id": "X2_SL15_TP3", "ko": "1.5 ATR 손절 · 3 ATR 익절, 최대 48봉", "note_ko": "단순 손절·익절 한 쌍"},
)
HOUSE_EXIT_KO = "하우스 청산: 2 ATR 손절 + 계단식 이익 잠금(+12%에서 +10% 잠금, 이후 5%씩), 레버리지는 늘 '보통' 단계"
REEL_EXIT = {"id": "SWING_BAND",
             "ko": "릴스 자체 청산: 손절 = 하단 이탈 뒤 최저점 − ATR 0.05배, 익절 = 직전 봉 볼린저 상단(지정가), 최대 96봉"}

LIVE_PER_DAY_KO = "라이브 계좌는 6개 코인을 합쳐 한 번에 1개 포지션이라 하루 거래 수가 연구보다 적습니다."
DS_NOTE_KO = ("과거 5년 연구는 ATR 청산 두 가지(X5_TRAIL2, X2_SL15_TP3)로 쟀습니다. 라이브 딥시크 계좌는 하우스 청산"
              "(2 ATR 손절 + 계단식 이익 잠금)이라 같은 신호라도 숫자가 다르게 나옵니다. 연구 엔진은 하우스 계단을 돌릴 수 "
              "없어서 가장 가까운 추적 손절(X5_TRAIL2)을 대신 썼습니다. " + LIVE_PER_DAY_KO)
REEL_NOTE_KO = ("과거 5년 연구와 라이브 계좌 모두 릴스 자체 청산(손절 = 하단 이탈 뒤 최저점 − ATR 0.05배, 익절 = 직전 봉 "
                "볼린저 상단, 최대 96봉)을 씁니다. 라이브는 청산을 1분봉으로 확인하고, 진입가가 다음 봉 시가가 아니라 "
                "기준 가격이며, 수수료·펀딩은 하우스 계산을 써서 숫자가 조금 다를 수 있습니다(paperbot/reel_engine.py). "
                + LIVE_PER_DAY_KO)
COST_NOTE_KO = {
    "ds200": "딥시크 연구의 총손익은 슬리피지를 이미 뺀 값이라 비용 칸은 수수료·펀딩만입니다.",
    "reel": "릴스 연구의 총손익은 슬리피지 빼기 전 값이라 비용 칸은 수수료·슬리피지·펀딩입니다.",
}
UNITS_KO = {
    "per_day": "하루 거래 수: 6개 코인 합계(코인마다 한 번에 1개 포지션, 연구 백테스트 기준)",
    "net_pct": "거래당 순손익: 진입가 대비 가격 %, 레버리지 없음, 수수료·슬리피지·펀딩 뺀 뒤",
    "win_pct": "승률: 순손익이 0보다 큰 거래 비율",
    "hold": "보유: 봉 수와 시간(딥시크 평균, 릴스 중앙값)",
    "pre": "3기는 일부 코인 자료가 늦게 시작해서(LTC 2020-01-09, DOGE 2020-07-10, SOL 2020-09-14) 하루 거래 수가 "
           "다른 기간보다 낮게 나옵니다",
}
DESCRIPTIVE_KO = "과거 5년 같은 규칙의 성격 설명이지 실력 증거가 아닙니다."

_CACHE: dict = {}


# ------------------------------------------------------------------ small helpers
def _num(x) -> Optional[float]:
    """float, or None for '', NaN, inf and anything unreadable."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _int(x) -> int:
    v = _num(x)
    return int(v) if v is not None else 0


def _bool(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "1.0", "yes")


def _r(x, k: int = 4) -> Optional[float]:
    return None if x is None else round(x, k)


def _mtime(path: str) -> Optional[int]:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _cached(key: str, paths: tuple, build):
    """build() once per set of file mtimes; a missing file gives None (not cached, tried again next call)."""
    stamp = tuple(_mtime(p) for p in paths)
    if any(s is None for s in stamp):
        return None
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    val = build()
    _CACHE[key] = (stamp, val)
    return val


def window_days(tf: str, period: str, max_hold: int) -> float:
    """Calendar days of a research period's signal window on ``tf`` (the research's window_idx): from max(period
    start, series start + warm-up) to the period end less max_hold + 1 bars. Warm-up = max(300 bars, 30 days)."""
    m = TF_MIN[tf]
    _k, _ko, _role, start, end = next(p for p in PERIODS if p[0] == period)
    warm_bars = max(300, math.ceil(30 * 1440 / m))
    t0 = max(dt.datetime.fromisoformat(start), dt.datetime.fromisoformat(SERIES_START[period])
             + dt.timedelta(minutes=warm_bars * m))
    t1 = dt.datetime.fromisoformat(end) - dt.timedelta(minutes=(max_hold + 1) * m)
    return max(0.0, (t1 - t0).total_seconds() / 86400.0)


def periods_meta() -> list[dict]:
    """The three periods in display order: key, Korean label, first and last calendar day (signal-bar times, UTC;
    each row's own window, after the warm-up and before the last hold, is its block's ``days``)."""
    out = []
    for k, ko, role, start, end in PERIODS:
        last = dt.date.fromisoformat(end) - dt.timedelta(days=1)
        out.append({"key": k, "ko": f"{ko} ({role})", "start": start, "end": last.isoformat()})
    return out


def _block(n: int, days: float, tf: str, net=None, gross=None, cost=None, win=None, pf=None, hold=None,
           extra: Optional[dict] = None) -> dict:
    hold_h = None if hold is None else hold * TF_MIN[tf] / 60.0
    d = {"n": n, "days": _r(days, 1), "per_day": _r(n / days, 3) if days > 0 else None, "net_pct": _r(net),
         "gross_pct": _r(gross),
         "cost_pct": _r(cost), "win_pct": _r(win, 2), "pf": _r(pf, 3), "hold_bars": _r(hold, 2),
         "hold_hours": _r(hold_h, 2), "small": n < SMALL_N}
    if n == 0:
        d.update(net_pct=None, gross_pct=None, cost_pct=None, win_pct=None, pf=None, hold_bars=None, hold_hours=None)
    if extra:
        d.update(extra)
    return d


# ------------------------------------------------------------------ DeepSeek
def _family_ko() -> dict:
    try:
        from .groups import DS_FAMILY_KO
        return dict(DS_FAMILY_KO)
    except Exception:  # noqa: BLE001  (a name table only; the card works without it)
        return {}


def _ds_rows() -> dict:
    with open(DS_RESULTS, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out: dict = {}
    for r in rows:
        out.setdefault(r["entry"], []).append(r)
    return out


def _ds_summary() -> dict:
    with open(DS_SUMMARY, encoding="utf-8") as fh:
        return json.load(fh)


def _ds_row(r: dict) -> dict:
    tf = r["tf"]
    per = {}
    for k, _ko, _role, _s, _e in PERIODS:
        n = _int(r.get(f"{k}_n"))
        per[k] = _block(n, window_days(tf, k, DS_MAX_HOLD), tf, net=_num(r.get(f"{k}_mean_pct")),
                        gross=_num(r.get(f"{k}_gross_mean_pct")), cost=_num(r.get(f"{k}_cost_mean_pct")),
                        win=_num(r.get(f"{k}_win_pct")), pf=_num(r.get(f"{k}_pf")),
                        hold=_num(r.get(f"{k}_hold_mean")),
                        extra={"long_net_pct": _r(_num(r.get(f"{k}_long_mean_pct"))) if n else None,
                               "short_net_pct": _r(_num(r.get(f"{k}_short_mean_pct"))) if n else None,
                               "coins_pos": _int(r.get(f"{k}_coins_pos")), "coins_n": _int(r.get(f"{k}_coins_n"))})
    n12 = _int(r.get("n12"))
    return {"tf": tf, "exit": r["exit"], "periods": per,
            "net12_pct": _r(_num(r.get("mean12_pct"))) if n12 else None, "n12": n12,
            "all3_positive": _bool(r.get("all3_positive")),
            "gauntlet": {"stage1": _bool(r.get("stage1")), "stage2": _bool(r.get("stage2")),
                         "stage3": _bool(r.get("stage3")), "candidate": _bool(r.get("candidate"))}}


def _build_ds() -> dict:
    by_def = _ds_rows()
    summ = _ds_summary()
    fam_ko = _family_ko()
    tf_order = list(TF_MIN)
    ex_order = [e["id"] for e in DS_EXITS]
    research = {"configs": summ.get("configs"), "stage1": summ.get("stage1"), "stage2": summ.get("stage2"),
                "stage3": summ.get("stage3"), "candidates": summ.get("candidate"),
                "lib_c_sha256": (summ.get("code_sha256") or {}).get("lib_c.py"),
                "source": "research/deepseek200/out/results.csv",
                "conclusion_ko": (f"5년 연구 결론: 설정 {summ.get('configs')}개(정의 44 × 봉 × 청산 2) 중 후보 "
                                  f"{summ.get('candidate')}개. 이 목록의 새 계열에서 우위를 못 찾았습니다.")}
    out = {}
    for d, fam, tfs in DS200_DEFS:
        rows = sorted((_ds_row(r) for r in by_def.get(d, []) if r["tf"] in tfs),
                      key=lambda x: (tf_order.index(x["tf"]), ex_order.index(x["exit"])
                                     if x["exit"] in ex_order else 9))
        ranked = sorted((x for x in rows if x["exit"] == DS_EXITS[0]["id"] and x["net12_pct"] is not None
                         and x["n12"] >= 100), key=lambda x: -x["net12_pct"])
        out[d] = {
            "strategy": d, "group": "ds200", "family": fam, "family_ko": fam_ko.get(fam),
            "timeframes": list(tfs), "data_source": "binance_futures",
            "exits": {"research": [dict(e) for e in DS_EXITS], "live": {"id": "house", "ko": HOUSE_EXIT_KO},
                      "same_as_live": False},
            "note_ko": DS_NOTE_KO, "descriptive_ko": DESCRIPTIVE_KO, "cost_note_ko": COST_NOTE_KO["ds200"],
            "units_ko": {**UNITS_KO, **({"per_day": UNITS_KO["per_day"].replace("6개 코인", "BTC 뺀 5개 코인")}
                                        if d == "F14_SMT" else {})},      # BTC is F14's reference, never traded
            "periods": periods_meta(),
            "rows": rows,
            "least_bad": ({"tf": ranked[0]["tf"], "exit": ranked[0]["exit"], "net12_pct": ranked[0]["net12_pct"]}
                          if ranked else None),
            "any_positive_net": any((x["periods"][k]["net_pct"] or 0) > 0 for x in rows for k in ("is", "cf", "pre")),
            "research": research,
        }
    return out


def ds_profile(definition: str) -> Optional[dict]:
    """The 5-year card of one DeepSeek definition; None when it is no definition or the research files are missing."""
    if definition not in DS200_FAMILY:
        return None
    built = _cached("ds", (DS_RESULTS, DS_SUMMARY), _build_ds)
    return None if built is None else built.get(definition)


# ------------------------------------------------------------------ reel
def _read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _build_reel() -> dict:
    with open(os.path.join(REEL_OUT, "h1.json"), encoding="utf-8") as fh:
        h1 = json.load(fh)
    tf = REEL_TF
    per = {}
    for k, _ko, _role, _s, _e in PERIODS:
        b = (h1.get("periods") or {}).get("oos" if k == "cf" else k) or {}
        n = _int(b.get("n"))
        per[k] = _block(n, window_days(tf, k, REEL_MAX_HOLD), tf, net=_num(b.get("mean_net_pct")),
                        gross=_num(b.get("mean_gross_pct")), cost=_num(b.get("mean_cost_pct")),
                        win=_num(b.get("win_pct")), pf=_num(b.get("pf")), hold=_num(b.get("hold_median")),
                        extra={"exit_reason_pct": {r: _r(_num(v), 2) for r, v in (b.get("exit_reason_pct") or {}).items()},
                               "stop_dist_median_pct": _r(_num(b.get("sl_med_pct")))})
    row = {"tf": tf, "exit": REEL_EXIT["id"], "periods": per, "n12": _int(h1.get("n12")),
           "net12_pct": _r(_num(h1.get("mean12_pct")))}
    variants = []
    pv = os.path.join(REEL_OUT, "per_variant.csv")
    for r in _read_csv(pv) if os.path.exists(pv) else []:
        name = r.get("") or r.get("Unnamed: 0") or ""
        variants.append({"variant": name, "dimension": r.get("dimension"), "configs": _int(r.get("configs")),
                         "net_pct": {k: _r(_num(r.get(f"{k}_mean_pct"))) for k in ("is", "cf", "pre")},
                         "n": {k: _int(r.get(f"{k}_n")) for k in ("is", "cf", "pre")},
                         "win_pct_is": _r(_num(r.get("is_win_pct")), 2), "hold_bars_is": _r(_num(r.get("is_hold")), 2)})
    by_year = []
    py = os.path.join(REEL_OUT, "h1_by_year.csv")
    for r in _read_csv(py) if os.path.exists(py) else []:
        by_year.append({"year": _int(r.get("year")), "n": _int(r.get("n")),
                        "net_pct": _r(_num(r.get("mean_net_pct"))), "win_pct": _r(_num(r.get("win_pct")), 2)})
    lg = h1.get("library_gauntlet") or {}
    return {
        "strategy": REEL_NAME, "group": "reel", "family": None, "family_ko": None, "timeframes": [tf],
        "data_source": "binance_futures", "config": list(h1.get("config") or REEL_H1),
        "exits": {"research": [dict(REEL_EXIT)], "live": dict(REEL_EXIT), "same_as_live": True},
        "note_ko": REEL_NOTE_KO, "descriptive_ko": DESCRIPTIVE_KO, "cost_note_ko": COST_NOTE_KO["reel"],
        "units_ko": dict(UNITS_KO),
        "periods": periods_meta(),
        "rows": [row],
        "variants": variants, "variants_note_ko": ("같은 아이디어의 변형(이평 종류·이탈 기준·방향)별 평균: 각 변형이 들어간 "
                                                   "설정 20개(5개 봉 × 나머지 선택)의 거래당 순손익 평균. 참고용."),
        "by_year": by_year,
        "least_bad": None,
        "any_positive_net": any((per[k]["net_pct"] or 0) > 0 for k in per),
        "research": {"pass": bool(h1.get("pass")), "rule": h1.get("rule"),
                     "stage1": bool(lg.get("stage1")), "stage2": bool(lg.get("stage2")),
                     "stage3": bool(lg.get("stage3")), "candidates": int(bool(h1.get("pass"))),
                     "source": "research/reel5m/out/h1.json",
                     "conclusion_ko": ("5년 연구 결론: 사전 등록한 H1 시험을 통과하지 못했습니다(1·2기 합친 거래당 순손익 "
                                       f"{_r(_num(h1.get('mean12_pct')), 3)}%, 3기 {_r(_num(h1.get('pre_mean_pct')), 3)}%)."
                                       if not h1.get("pass") else "5년 연구 결론: 사전 등록한 H1 시험을 통과했습니다.")},
    }


def reel_profile() -> Optional[dict]:
    """The reel's 5-year card (H1 on 5m); None when research/reel5m/out/h1.json is missing."""
    return _cached("reel", (os.path.join(REEL_OUT, "h1.json"),), _build_reel)


# ------------------------------------------------------------------ one entry point
def profile(strategy: str) -> Optional[dict]:
    """The 5-year card of a v4 strategy (a DeepSeek definition id or REEL_H1); None for any other name (the 36 have
    theirs in agents/packets3.profile_card) or when the research files are missing."""
    if strategy == REEL_NAME:
        return reel_profile()
    return ds_profile(strategy)


RARE_PER_DAY = 0.3      # research/strategy_profiles/report.py: fewer than this on every timeframe = rare


def _reel_grid() -> Optional[dict]:
    """research/reel5m/out/summary.json: the whole 40-config grid's gauntlet counts (None when missing)."""
    p = os.path.join(REEL_OUT, "summary.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return {"configs": d.get("configs"), "candidates": d.get("candidate"), "h1_pass": d.get("h1_pass"),
            "prereg_sha256": d.get("prereg_sha256")}


def _card_row(r: dict) -> dict:
    """One timeframe of a research card in a profile_card-like row (the exit closest to the live one)."""
    p = r["periods"]
    win = p["is"]["win_pct"]
    return {"tf": r["tf"], "exit": r["exit"],
            "trades_per_day": p["is"]["per_day"], "signals_per_day": p["is"]["per_day"],   # trades (research)
            "net_pct_is": p["is"]["net_pct"], "net_pct_cf": p["cf"]["net_pct"], "net_pct_pre": p["pre"]["net_pct"],
            "net12_pct": r.get("net12_pct"), "n_is": p["is"]["n"], "n_cf": p["cf"]["n"], "n_pre": p["pre"]["n"],
            "win_rate": None if win is None else round(win / 100.0, 4), "hold_hours": p["is"]["hold_hours"],
            "small": bool(p["is"]["small"])}


def card(strategy: str) -> Optional[dict]:
    """The research card of a DeepSeek definition or the reel in agents/packets3.profile_card's shape (strategy,
    name_ko, style, trend_share, hold, least_bad_tf, rare, rows, data_source, note, note_5m), for packets and the
    dashboard: ``profile_card(s) or ds_profiles.card(s)``. One row per timeframe with the research exit closest to the
    live one (DeepSeek X5_TRAIL2; the reel its own exits, the same as live). Row numbers are price % per trade with no
    leverage (``net_pct_*``), NOT the 36's leveraged ROE, and ``signals_per_day`` is the research's TRADES per day (the
    same number as ``trades_per_day``; a live account trades less, one position across six coins). None for any other
    name or when the research files are missing."""
    p = profile(strategy)
    if p is None:
        return None
    reel = p["group"] == "reel"
    main = p["exits"]["research"][0]["id"]
    rows = [_card_row(r) for r in p["rows"] if r["exit"] == main]
    try:
        from .groups import label_ko
        name_ko = label_ko(strategy)
    except Exception:  # noqa: BLE001  (a name table only)
        name_ko = strategy
    lb = p.get("least_bad")
    research = dict(p.get("research") or {})
    if reel:
        grid = _reel_grid()
        if grid:
            research["grid"] = grid
            research["conclusion_ko"] = (research.get("conclusion_ko", "") +
                                         f" 같은 아이디어 설정 {grid.get('configs')}개 중 통과 {grid.get('candidates')}개.")
    exits_ko = (f"연구·라이브 같은 청산: {p['exits']['live']['ko']}" if p["exits"]["same_as_live"] else
                f"연구 청산 {'/'.join(e['id'] for e in p['exits']['research'])} ≠ 실계좌 사다리. 표는 {main}: "
                f"{p['exits']['research'][0]['ko']} / 실계좌: "
                f"{p['exits']['live']['ko']}")
    return {
        "strategy": strategy, "name_ko": name_ko, "group": p["group"], "family": p.get("family"),
        "family_ko": p.get("family_ko"), "style": None, "trend_share": None,
        "hold": None, "least_bad_tf": (lb or {}).get("tf") if not reel else (rows[0]["tf"] if rows else None),
        "rare": bool(rows) and all((r["trades_per_day"] or 0) < RARE_PER_DAY for r in rows),
        "rows": rows, "data_source": p.get("data_source", "binance_futures"),
        "exit": main, "exits_ko": exits_ko, "same_exits_as_live": bool(p["exits"]["same_as_live"]),
        "note": ("5-year research character of the same entry rule; numbers are price % per trade without leverage "
                 "after research costs, research exit " + main + (" = the live exit" if reel else
                 " (NOT the live house ladder)") + "; trades per day are the research's (one position per coin), "
                 "live accounts trade less (one position across six coins); describes style, not proven skill"),
        "note_ko": p["note_ko"], "cost_note_ko": p.get("cost_note_ko"),
        "note_5m": ("릴스는 5분봉 전용(5분봉 계좌 1개, 같은 청산의 5분봉 동전 3개와 비교)" if reel else
                    "딥시크는 5분봉 계좌 없음(15분·30분·1시간·4시간만)"),
        "research": research,
    }


def all_profiles() -> dict:
    """{strategy: card} of every v4 strategy whose card can be built now (44 DeepSeek + the reel)."""
    out = {}
    for d, _f, _t in DS200_DEFS:
        p = ds_profile(d)
        if p is not None:
            out[d] = p
    p = reel_profile()
    if p is not None:
        out[REEL_NAME] = p
    return out


def table_ko(card: dict, exit_id: Optional[str] = None) -> list[dict]:
    """Flat rows for a plain table (one per timeframe x exit x period), in display order: {tf, exit, period,
    period_ko, n, per_day, net_pct, win_pct, hold_hours, small}. ``exit_id`` keeps one exit only."""
    ko = {p["key"]: p["ko"] for p in card.get("periods", [])}
    out = []
    for r in card.get("rows", []):
        if exit_id is not None and r["exit"] != exit_id:
            continue
        for k, _ko, _role, _s, _e in PERIODS:
            b = r["periods"][k]
            out.append({"tf": r["tf"], "exit": r["exit"], "period": k, "period_ko": ko.get(k), "n": b["n"],
                        "per_day": b["per_day"], "net_pct": b["net_pct"], "win_pct": b["win_pct"],
                        "hold_hours": b["hold_hours"], "small": b["small"]})
    return out


if __name__ == "__main__":
    import sys
    names = sys.argv[1:] or ["F9_FVG", REEL_NAME]
    for nm in names:
        c = profile(nm)
        if c is None:
            print(nm, "no card")
            continue
        print(f"{nm}  ({c['group']}, exits research {[e['id'] for e in c['exits']['research']]} / live "
              f"{c['exits']['live']['id']})")
        for t in table_ko(c):
            print(f"  {t['tf']:>3} {t['exit']:<11} {t['period']:<3} n={t['n']:>6} /day={t['per_day']}"
                  f" net={t['net_pct']}% win={t['win_pct']}% hold={t['hold_hours']}h{' (small)' if t['small'] else ''}")
