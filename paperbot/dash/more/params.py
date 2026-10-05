"""숫자(파라미터) 시험 결과 (매매법 상세 #/strategies/<id>): what the five-year research already said about each
strategy's numbers. Read-only over committed research files; nothing is recomputed and no bot database is opened.

    GET /api/v4/params/<strategy>

Sources (read as they are, cached per file mtime; a missing file is "no data", never a 500):

    the 36    paperbot/agents/research_prior.json  "strategies"[S]["parameters"]: the pre-registered parameter study
              (research/entry_study, RESULTS_ENTRY_BC.md part C). Each parameter x0.5 / x0.75 / x1.25 / x1.5 on 15m, 1h
              and 4h; per timeframe x parameter: the shape (평평 / 완만 / 뾰족 / 표본 부족) and the variants positive in
              all three periods. "conclusion_ko": 1,680 variants, no sharp peak, the all-3 count is chance level.
    reel      research/reel5m/out/per_variant.csv  the reel grid by choice (moving average, breach, sides), each over
              its 20 configurations: configurations positive per period, all three; per_tf.csv the same by timeframe;
              summary.json the grid's totals (40 configurations, candidates, H1 pass).
    DeepSeek  paperbot/agents/ds_prior.json  "strategies"[D]["tests"]: the definition's timeframe x research-exit
              rows. No parameter variants were tested; the answer says so and gives counts only (trades per period,
              which periods were positive), never the per-trade money numbers (owners D10 / D11: DeepSeek is counted).

Everything is "5년 과거 시험 (참고)": a description of the past, not a rule and not evidence of skill. The answer
carries its own plain-Korean texts (shape meanings, the trap of the best past number, how new numbers are tested), so
the page and the agents' packets say the same thing.
"""
from __future__ import annotations

import csv
import json
import os
import threading
from typing import Callable, Optional

from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RESEARCH_PRIOR = os.path.join(ROOT, "paperbot", "agents", "research_prior.json")
DS_PRIOR = os.path.join(ROOT, "paperbot", "agents", "ds_prior.json")
REEL_OUT = os.path.join(ROOT, "research", "reel5m", "out")
REEL_VARIANTS = os.path.join(REEL_OUT, "per_variant.csv")
REEL_TFS = os.path.join(REEL_OUT, "per_tf.csv")
REEL_SUMMARY = os.path.join(REEL_OUT, "summary.json")
REEL_NAME = "REEL_H1"
REEL_LIVE = {"ma": "SMA200", "breach": "CLOSE", "sides": "LONG", "tf": "5m"}     # H1 = the live account's choices

LABEL_KO = "5년 과거 시험 (참고)"
PERIODS = (("is", "1기", "2021-08 ~ 2024-06"), ("cf", "2기", "2024-07 ~ 2026-09"), ("pre", "3기", "2020-01 ~ 2021-07"))
MULTS_KO = "0.5배 · 0.75배 · 1.25배 · 1.5배"

SHAPE_KEY = {"평평": "flat", "완만": "smooth", "뾰족": "sharp", "표본 부족": "thin",
             "flat": "flat", "smooth": "smooth", "sharp": "sharp", "peak": "sharp", "spiky": "sharp",
             "insufficient": "thin", "thin": "thin"}
SHAPE_KO = {"flat": "평평", "smooth": "완만", "sharp": "뾰족", "thin": "표본 부족"}
SHAPE_NOTE_KO = {
    "flat": "숫자를 바꿔도 결과가 거의 같음 (손실이면 바꿔도 비슷하게 손실)",
    "smooth": "숫자를 바꾸면 결과가 좀 움직이지만 지금 숫자만 튀지는 않음",
    "sharp": "지금 숫자만 양옆 숫자보다 좋음 = 위험 신호 (운일 가능성)",
    "thin": "거래가 적어서 모양을 매기지 않음",
}
SHAPE_ORDER = ("flat", "smooth", "sharp", "thin")

# plain words where the name is obvious; anything else keeps its code name (the page shows it as is)
PARAM_KO = {
    "ema_fast": "빠른 EMA 길이", "ema_slow": "느린 EMA 길이", "ema_len": "EMA 길이",
    "rsi_len": "RSI 길이", "rsi_level": "RSI 기준선", "rsi_oversold": "RSI 과매도선",
    "adx_len": "ADX 길이", "adx_level": "ADX 기준선", "adx_thr": "ADX 기준선", "adx_min": "ADX 하한",
    "adx_long_min": "롱 ADX 하한", "adx_short_max": "숏 ADX 상한",
    "di_len": "DI 길이", "dmi_len": "DMI 길이", "dmi_gap": "DI 차이 기준",
    "st_mult": "슈퍼트렌드 배수", "st_atr_len": "슈퍼트렌드 ATR 길이", "st_fast_mult": "빠른 슈퍼트렌드 배수",
    "st_slow_mult": "느린 슈퍼트렌드 배수", "st_mult_main": "슈퍼트렌드 배수 (기본)",
    "st_mult_strict": "슈퍼트렌드 배수 (엄격)", "htf_st_mult": "상위 봉 슈퍼트렌드 배수",
    "macd_fast": "MACD 빠른 길이", "macd_slow": "MACD 느린 길이", "macd_signal": "MACD 시그널 길이",
    "stoch_len": "스토캐스틱 길이", "stoch_k_smooth": "스토캐스틱 K 다듬기",
    "tenkan_len": "일목 전환선 길이", "kijun_len": "일목 기준선 길이", "senkou_b_len": "일목 선행스팬 B 길이",
    "cmo_len": "CMO 길이", "cci_len": "CCI 길이", "cci_level": "CCI 기준선",
    "kc_len": "켈트너 길이", "kc_mult": "켈트너 배수", "bb_len": "볼린저 길이", "bb_mult": "볼린저 배수",
    "dc_len": "돈치안 길이", "mfi_len": "MFI 길이", "mfi_level": "MFI 기준선",
    "wr_len": "윌리엄스 %R 길이", "wr_oversold": "윌리엄스 %R 과매도선",
    "aroon_len": "아룬 길이", "atr_len": "ATR 길이", "roc_len": "ROC 길이", "vi_len": "볼텍스 길이",
    "obv_ma_len": "OBV 이평 길이", "vwma_len": "VWMA 길이", "chop_len": "CHOP 길이", "chop_max": "CHOP 상한",
    "lips_len": "앨리게이터 입술 길이", "teeth_len": "앨리게이터 이빨 길이", "jaw_len": "앨리게이터 턱 길이",
    "sar_af": "파라볼릭 SAR 가속", "sar_af_start": "파라볼릭 SAR 시작 가속", "sar_af_step": "파라볼릭 SAR 가속 단계",
    "sar_af_max": "파라볼릭 SAR 최대 가속", "psar_start": "파라볼릭 SAR 시작 가속",
    "psar_step": "파라볼릭 SAR 가속 단계", "psar_max": "파라볼릭 SAR 최대 가속",
    "ao_fast": "AO 빠른 길이", "ao_slow": "AO 느린 길이", "ao_fast_len": "AO 빠른 길이", "ao_slow_len": "AO 느린 길이",
    "kst_roc_lens": "KST ROC 길이들", "kst_signal_len": "KST 시그널 길이",
    "kvo_lens": "클링거 길이들", "kvo_signal_len": "클링거 시그널 길이",
    "poc_lookback": "POC 볼 봉 수", "poc_tol": "POC 허용 폭", "pivot_len": "피벗 길이", "range_len": "박스 길이",
    "break_len": "돌파 기준 봉 수", "prior_n": "앞 봉 수", "fib_level": "피보나치 비율",
    "sq_lookback": "스퀴즈 볼 봉 수", "sq_pct": "스퀴즈 기준 %",
    "big_body": "큰 몸통 기준", "small_body": "작은 몸통 기준", "body_min": "최소 몸통", "engulf_min": "장악형 최소 크기",
    "wick_tol": "꼬리 허용 폭", "gap_tol": "갭 허용 폭", "touch_atr": "닿음 판정 폭 (ATR)", "slope_thr": "기울기 기준",
    "stc_level": "STC 기준선",
    "spread_min": "EMA 간격 최소 %", "pierce_frac": "POC 관통 비율", "ac_len": "AC 다듬기 길이",
    "ext_cap": "돌파 뒤 최대 거리 (ATR 배수)", "map_scale": "RSI 겹침 배율", "match_tol": "저점 맞춤 허용 폭 (ATR)",
    "sync": "신호 맞춤 봉 수",
}

REEL_DIM_KO = {"ma": "이평 종류", "breach": "이탈 기준", "sides": "방향", "tf": "봉"}
REEL_VARIANT_KO = {"SMA200": "SMA 200 (단순 이평)", "EMA200": "EMA 200 (지수 이평)", "CLOSE": "종가가 밴드 밖",
                   "WICK": "꼬리가 밴드 밖", "LONG": "롱만", "BOTH": "롱·숏 둘 다"}
DS_EXIT_KO = {"X5_TRAIL2": "2 ATR 손절 + 추적 손절", "X2_SL15_TP3": "1.5 ATR 손절 · 3 ATR 익절"}

TRAP_KO = ("지난 5년에서 가장 좋았던 숫자를 골라 쓰는 것은 함정입니다. 숫자를 많이 바꿔 볼수록 운으로 좋아 보이는 숫자가 "
           "반드시 나오고, 그 숫자가 앞으로도 좋다는 보장은 없습니다. 같은 5년 자료로 숫자를 다시 바꿔 봐도 새 정보가 "
           "아닙니다 (이미 본 자료).")
# docs/newlab-prereg.md 2장·6장, docs/extra-accounts.md: the lab builds NEW strategies in its own grammar (30 entry
# triggers, numbers from fixed choices); a pass only makes a proposal, and both owners' OK starts the account
LAB_KO = ("새 아이디어는 AI 연구실(새 매매법 실험실)이 정해진 틀(진입 신호 30종, 숫자는 정해진 몇 가지 중 선택)로 "
          "새 매매법을 만들어 세 기간 시험으로 따로 시험하고, 통과하면 새 모의 계좌를 제안합니다. 두 분이 OK해야 따로 "
          "돌기 시작합니다. 지금 돌고 있는 계좌의 숫자는 바꾸지 않습니다 (규칙이 바뀌면 새 계좌).")
PERIODS_KO = ("세 기간 = 1기 2021-08 ~ 2024-06 (고르기), 2기 2024-07 ~ 2026-09 (확인), 3기 2020-01 ~ 2021-07 (최종). "
              "세 기간 모두 플러스여야 '우연이 아닐 수도' 있는 후보입니다.")

_CACHE: dict = {}
_LOCK = threading.Lock()


def _mtime(path: str) -> Optional[int]:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _cached(key: str, paths: tuple, build: Callable):
    """build() once per set of file mtimes; None while any file is missing or unreadable (tried again next call)."""
    stamp = tuple(_mtime(p) for p in paths)
    if any(s is None for s in stamp):
        return None
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    try:
        val = build()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    with _LOCK:
        _CACHE[key] = (stamp, val)
    return val


def _json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _csv(path: str) -> list:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _int(x) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _periods() -> list:
    return [{"key": k, "ko": ko, "span": span} for k, ko, span in PERIODS]


def _shape(row: dict) -> str:
    return SHAPE_KEY.get(str(row.get("shape_ko") or "").strip()) or SHAPE_KEY.get(str(row.get("shape") or "").strip(), "thin")


# ------------------------------------------------------------------ the 36: research_prior.json parameters
def _core_doc() -> Optional[dict]:
    return _cached("core", (RESEARCH_PRIOR,), lambda: _json(RESEARCH_PRIOR))


def _core_study(doc: dict) -> dict:
    """The whole study over the 36 (counted from the file, never typed in)."""
    shapes = {k: 0 for k in SHAPE_ORDER}
    params = variants = pos = adopted = 0
    names = 0
    for s in (doc.get("strategies") or {}).values():
        p = (s or {}).get("parameters") or {}
        if not p:
            continue
        names += 1
        variants += _int(p.get("variants"))
        adopted += _int(p.get("adopted"))
        for r in p.get("params") or []:
            params += 1
            shapes[_shape(r)] += 1
            pos += len(r.get("positive_all3") or [])
    return {"strategies": names, "params": params, "variants": variants, "positive_all3": pos, "adopted": adopted,
            "shapes": shapes,
            "total_tests": (doc.get("totals") or {}).get("parameters")}


def _core(strategy: str, doc: dict) -> dict:
    p = ((doc.get("strategies") or {}).get(strategy) or {}).get("parameters") or {}
    rows = []
    shapes = {k: 0 for k in SHAPE_ORDER}
    for r in p.get("params") or []:
        sh = _shape(r)
        shapes[sh] += 1
        hits = [{"value": str(x.get("value")), "mult": _num(x.get("mult"))} for x in (r.get("positive_all3") or [])]
        rows.append({"tf": r.get("tf"), "param": r.get("param"), "param_ko": PARAM_KO.get(r.get("param")),
                     "shape": sh, "shape_ko": SHAPE_KO[sh], "variants": _int(r.get("variants")),
                     "positive_all3": len(hits), "positive_values": hits})
    order = {"15m": 0, "30m": 1, "1h": 2, "4h": 3}
    rows.sort(key=lambda x: order.get(x["tf"], 9))          # stable: the study's parameter order inside a timeframe
    tfs = [t for t in order if any(r["tf"] == t for r in rows)]
    study = _core_study(doc)
    pos = sum(r["positive_all3"] for r in rows)
    return {
        "variants": _int(p.get("variants")), "adopted": _int(p.get("adopted")), "rows": rows, "shapes": shapes,
        "positive_all3": pos, "tested_tfs": tfs,
        "untested_ko": "30분봉은 이 시험에 없었습니다 (15분·1시간·4시간만)." if "30m" not in tfs else None,
        "how_ko": (f"숫자(길이·배수·기준선) 하나씩 기본값의 {MULTS_KO}로 바꿔 봉마다 시험했습니다. "
                   "한 줄 = 봉 하나 × 숫자 하나, 변형 4개."),
        "study": study,
        "conclusion_ko": doc.get("conclusion_ko"),
        "summary_ko": (f"이 매매법: 숫자 변형 {_int(p.get('variants')):,}개 시험 → 세 기간 모두 플러스 {pos}개, "
                       f"채택 {_int(p.get('adopted'))}개."),
        "meaning_ko": ((f"돈을 버는 '마법의 숫자'는 찾지 못했습니다 (채택 {study['adopted']}개). " if not study["adopted"]
                        else f"36개 전체로 채택된 변형 {study['adopted']}개. ")
                       + f"36개 매매법 전체로 변형 {study['variants']:,}개 중 세 기간 모두 플러스는 "
                       f"{study['positive_all3']}개였고, 이 수는 '숫자는 결과와 상관없다'고 가정해도 우연히 나오는 만큼입니다. "
                       f"지금 숫자만 우연히 좋은 '뾰족' 모양은 {study['shapes']['sharp']}개였습니다."),
        "positive_note_ko": ("36개 전체로 보면 세 기간 모두 플러스였던 변형은 대부분 거래가 적은 칸에서 나왔고, 대부분 이웃 "
                             "숫자가 플러스가 아닌 외딴 점이었습니다. 그 수도 우연 수준이라 사전 등록 규칙대로 어느 변형도 "
                             "채택하지 않았습니다."),
        "source": "paperbot/agents/research_prior.json (research/entry_study, RESULTS_ENTRY_BC.md C)",
    }


# ------------------------------------------------------------------ the reel: per_variant.csv / per_tf.csv
def _reel_doc() -> Optional[dict]:
    def build():
        variants = []
        for r in _csv(REEL_VARIANTS):
            name = (r.get("") or r.get("Unnamed: 0") or r.get("variant") or "").strip()
            dim = (r.get("dimension") or "").strip()
            variants.append({
                "variant": name, "variant_ko": REEL_VARIANT_KO.get(name), "dimension": dim,
                "dimension_ko": REEL_DIM_KO.get(dim, dim), "configs": _int(r.get("configs")),
                "positive": {k: _int(r.get(f"{k}_pos")) for k, _ko, _s in PERIODS},
                "all3_positive": _int(r.get("all3_positive")), "candidates": _int(r.get("candidate")),
                "trades": {k: _int(r.get(f"{k}_n")) for k, _ko, _s in PERIODS},
                "per_trade_pct": {k: (None if _num(r.get(f"{k}_mean_pct")) is None else round(_num(r.get(f"{k}_mean_pct")), 3))
                                  for k, _ko, _s in PERIODS},
                "live": REEL_LIVE.get(dim) == name})
        dim_order = list(REEL_DIM_KO)
        variants.sort(key=lambda v: (dim_order.index(v["dimension"]) if v["dimension"] in dim_order else 9, not v["live"]))
        by_tf = []
        if os.path.exists(REEL_TFS):
            for r in _csv(REEL_TFS):
                tf = (r.get("tf") or "").strip()
                by_tf.append({"tf": tf, "configs": _int(r.get("configs")),
                              "positive": {k: _int(r.get(f"{k}_pos")) for k, _ko, _s in PERIODS},
                              "all3_positive": _int(r.get("all3_positive")), "candidates": _int(r.get("candidate")),
                              "live": tf == REEL_LIVE["tf"]})
            tf_order = ["5m", "15m", "30m", "1h", "4h"]
            by_tf.sort(key=lambda x: tf_order.index(x["tf"]) if x["tf"] in tf_order else 9)
        summ = {}
        if os.path.exists(REEL_SUMMARY):
            s = _json(REEL_SUMMARY)
            summ = {"configs": s.get("configs"), "candidates": s.get("candidate"), "h1_pass": s.get("h1_pass"),
                    "all3_positive": s.get("all_three_periods_positive")}
        return {"variants": variants, "by_tf": by_tf, "grid": summ}
    return _cached("reel", (REEL_VARIANTS,), build)


def _reel(doc: dict) -> dict:
    g = doc.get("grid") or {}
    configs = g.get("configs")
    return {
        "rows": doc["variants"], "by_tf": doc["by_tf"], "configs": configs, "candidates": g.get("candidates"),
        "h1_pass": g.get("h1_pass"), "all3_positive": g.get("all3_positive"),
        "how_ko": ("릴스는 볼린저(20, 2)와 200봉 이평의 숫자는 그대로 두고, 고를 수 있는 것(이평 종류 · 이탈 기준 · 방향 · 봉)을 "
                   f"바꿔 설정 {configs if configs is not None else '—'}개를 시험했습니다. 한 줄 = 그 선택이 들어간 설정들."),
        "summary_ko": (f"설정 {configs}개 시험 → 세 기간 모두 플러스 {g.get('all3_positive')}개, 통과 {g.get('candidates')}개."
                       if configs is not None else None),
        "meaning_ko": (" ".join(x for x in (
            "어느 조합도 시험을 통과하지 못했습니다 (돈을 버는 조합 없음)." if g.get("candidates") == 0 else None,
            {False: "지금 계좌의 설정(SMA 200 · 종가 이탈 · 롱만 · 5분봉, H1)도 사전 등록 시험을 통과하지 못했습니다.",
             True: "지금 계좌의 설정(H1)은 사전 등록 시험을 통과했습니다. 그래도 과거 결과입니다."}.get(g.get("h1_pass")),
        ) if x) or None),
        "unit_ko": "거래당 % = 진입가 대비 가격 %, 레버리지 없음, 수수료·슬리피지·펀딩 뺀 뒤 (그 선택이 들어간 설정들의 평균).",
        "source": "research/reel5m/out/per_variant.csv, per_tf.csv, summary.json",
    }


# ------------------------------------------------------------------ DeepSeek: ds_prior.json tests (counts only)
def _ds_doc() -> Optional[dict]:
    return _cached("ds", (DS_PRIOR,), lambda: _json(DS_PRIOR))


def _ds(strategy: str, doc: dict) -> Optional[dict]:
    s = (doc.get("strategies") or {}).get(strategy)
    if not s:
        return None
    rows = []
    for t in s.get("tests") or []:
        pos = {k: (_num(t.get(f"{k}_mean_pct")) or 0) > 0 for k, _ko, _s in PERIODS}
        rows.append({"tf": t.get("tf"), "exit": t.get("exit"), "exit_ko": DS_EXIT_KO.get(t.get("exit"), t.get("exit")),
                     "trades": {k: _int(t.get(f"{k}_n")) for k, _ko, _s in PERIODS},
                     "positive": pos, "positive_periods": sum(pos.values()),
                     "all3_positive": bool(t.get("all3_positive"))})
    tot = (doc.get("totals") or {}).get("ds200") or {}
    fg = s.get("family_gauntlet") or {}
    return {
        "family": s.get("family"), "family_ko": s.get("family_ko"), "configs": _int(s.get("configs")) or len(rows),
        "all3_positive": _int(s.get("all3_positive")), "candidates": _int(s.get("candidates")), "rows": rows,
        "family_gauntlet": {"configs": _int(fg.get("configs")), "all3_positive": _int(fg.get("all3_positive")),
                            "candidates": _int(fg.get("candidate"))} if fg else None,
        "study": {"definitions": sum(1 for k, v in (doc.get("strategies") or {}).items() if (v or {}).get("group") == "ds200"),
                  "configs": tot.get("configs"), "all3_positive": tot.get("all3_positive"),
                  "candidates": tot.get("candidates")},
        "none_ko": "이 매매법은 숫자 변형 시험 없음",
        "how_ko": ("딥시크 정의는 정해진 숫자 그대로 두고, 봉과 연구 청산 2가지만 바꿔 시험했습니다. 숫자를 바꾼 시험은 하지 "
                   "않았습니다. 아래는 그 시험의 거래 수와 플러스였던 기간 수입니다 (돈 숫자 없음)."),
        "summary_ko": (f"이 정의: 설정 {_int(s.get('configs')) or len(rows)}개 → 세 기간 모두 플러스 "
                       f"{_int(s.get('all3_positive'))}개, 후보 {_int(s.get('candidates'))}개."),
        "meaning_ko": (f"딥시크 정의 44개 전체로 설정 {tot.get('configs')}개 중 세 기간 모두 플러스 {tot.get('all3_positive')}개는 "
                       f"우연 수준이고, 후보는 {tot.get('candidates')}개였습니다." if tot else None),
        "exit_note_ko": s.get("exit_note_ko"),
        "source": "paperbot/agents/ds_prior.json (research/deepseek200/out)",
    }


# ------------------------------------------------------------------ one answer
def answer(strategy: str) -> Optional[dict]:
    """The panel's answer for one strategy id; None for an id that is none of the 36, the reel or a DeepSeek
    definition (the route answers 404)."""
    base = {"strategy": strategy, "label_ko": LABEL_KO, "periods": _periods(), "periods_ko": PERIODS_KO,
            "trap_ko": TRAP_KO, "lab_ko": LAB_KO,
            "shapes_ko": [{"shape": k, "ko": SHAPE_KO[k], "note_ko": SHAPE_NOTE_KO[k]} for k in SHAPE_ORDER]}
    core = _core_doc()
    if core is not None and strategy in (core.get("strategies") or {}):
        has = bool(((core["strategies"][strategy] or {}).get("parameters") or {}).get("params"))
        return {**base, "group": "core", "available": True, "has_param_test": has,
                "core": _core(strategy, core) if has else None, "reel": None, "ds": None,
                "none_ko": None if has else "이 매매법은 숫자 변형 시험 없음"}
    if strategy == REEL_NAME:
        reel = _reel_doc()
        return {**base, "group": "reel", "available": reel is not None, "has_param_test": reel is not None,
                "core": None, "reel": _reel(reel) if reel is not None else None, "ds": None,
                "none_ko": None if reel is not None else "5년 시험 파일을 찾지 못했습니다"}
    ds_doc = _ds_doc()
    ds = _ds(strategy, ds_doc) if ds_doc is not None else None
    if ds is not None:
        return {**base, "group": "ds200", "available": True, "has_param_test": False, "core": None, "reel": None,
                "ds": ds, "none_ko": ds["none_ko"]}
    if ds_doc is None:                         # the file is missing: a known DeepSeek id still gets a plain answer
        try:
            from ...config import DS200_FAMILY as known
        except Exception:  # noqa: BLE001  (a name table only)
            known = {}
        if strategy in known:
            return {**base, "group": "ds200", "available": False, "has_param_test": False, "core": None,
                    "reel": None, "ds": None, "none_ko": "이 매매법은 숫자 변형 시험 없음"}
    if core is None and "@" not in strategy and strategy.replace("_", "").isalnum():
        # research_prior.json is missing (an install fault): the 36 cannot be told from an unknown id, so a plain
        # "file not found" answer instead of a 404 that would read as "no such strategy"
        return {**base, "group": "core", "available": False, "has_param_test": False, "core": None, "reel": None,
                "ds": None, "none_ko": "5년 시험 파일을 찾지 못했습니다"}
    return None


def register(app, ctx) -> Callable:
    @app.get("/api/v4/params/{strategy}")
    def get_params(strategy: str):
        """숫자(파라미터) 시험 결과: the five-year research on one strategy's numbers (read-only files, mtime cache)."""
        out = answer(strategy)
        if out is None:
            raise HTTPException(404, "그런 매매법이 없습니다")
        return out

    return answer
