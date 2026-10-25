"""Build the owners' page from out/roles45.json: one card per strategy (all timeframes), what it does alone, the market
states where it made money on 2021-24 and whether that held on 2025-26, the judge that helps it most, and the summary
(regime-matched bot vs shuffled-state control, judge ranking)."""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
R = json.load(open(os.path.join(OUTD, "roles45.json")))
KO = {k: v["name_ko"] for k, v in json.load(open("/home/user/crypto-bot-research/research/newlive/classify.json")).items()}
KO.update({
    "T1_EMA9_21": "EMA 9·21 교차", "T1_EMA20_50": "EMA 20·50 교차", "T1_EMA50_200": "EMA 50·200 교차", "T2_SMA10_30": "SMA 10·30 교차",
    "T2_SMA50_200": "SMA 50·200 교차", "T3_MACD12_26_9": "MACD 12·26·9", "T3_MACD8_21_5": "MACD 8·21·5", "T4_MACDHIST0": "MACD 히스토그램 0선",
    "T5_ST10_2": "슈퍼트렌드 10·2", "T5_ST10_3": "슈퍼트렌드 10·3", "T5_ST14_4": "슈퍼트렌드 14·4", "T6_DON20": "돈치안 20 돌파",
    "T6_DON55": "돈치안 55 돌파", "T7_KELT20_2": "켈트너 20·2 돌파", "T8_PSAR": "PSAR 전환", "T9_DMI14_ADX25": "DMI 14·ADX 25",
    "T10_ICHI_TK": "일목 전환·기준선", "T11_AROON25": "아룬 25", "T12_HMA21": "HMA 21", "T12_HMA55": "HMA 55",
    "O1_RSI14_REV30": "RSI 14 과매도 반전", "O1_RSI7_REV20": "RSI 7 과매도 반전", "O2_RSI14_X50": "RSI 14 50선 교차",
    "O3_STOCH_ZONE": "스토캐스틱 구간", "O4_STOCHRSI_ZONE": "스토캐스틱RSI 구간", "O5_CCI20": "CCI 20", "O6_WR14": "윌리엄스 %R 14",
    "O7_MFI14": "MFI 14", "O8_ROC9": "ROC 9", "O8_ROC21": "ROC 21", "O9_CMO14": "CMO 14", "V1_BB_BREAK": "볼린저 돌파",
    "V2_BB_REVERT": "볼린저 되돌림", "V3_SQUEEZE": "스퀴즈 돌파", "VO1_OBV_X_MA20": "OBV·20평균 교차", "VO2_VOL_SPIKE": "거래량 급증",
    "C1_ENGULF": "장악형 캔들", "C2_HAMMER_STAR": "망치·유성 캔들", "C3_INSIDE_BREAK": "인사이드바 돌파", "C4_THREE_SAME": "같은 색 3연속",
    "FRIEND_ROC": "친구분 EMA·RSI·ROC"})
SETN = {"core": "규칙봇", "ds": "딥시크", "lib": "라이브러리", "friend": "친구분"}
ROLEN = {"trend": "추세", "pullback": "눌림", "reversal": "반전", "breakout": "돌파", "range": "횡보", "timing": "타이밍", "other": "기타"}
TFS = ["15m", "30m", "1h", "4h"]
TFN = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
strat = {}
for cellname, cd in R["카드"].items():
    if "매매법" not in cd:
        continue
    nm, tf = cd["매매법"], cd["봉"]
    s = strat.setdefault(nm, {"id": nm, "ko": KO.get(nm, nm), "set": SETN.get(cd["세트"], cd["세트"]), "role": ROLEN.get(cd["유형"], cd["유형"]), "tf": {}})
    fits = cd.get("맞는 장 (고르기 기간 플러스)", [])
    both = sorted([f for f in fits if f["확인 신호당"] is not None and f["확인 신호당"] > 0], key=lambda f: -min(f["고르기 신호당"], f["확인 신호당"]))
    pick_only = sorted([f for f in fits if not (f["확인 신호당"] is not None and f["확인 신호당"] > 0)], key=lambda f: -f["고르기 신호당"])
    pr = R["매매법별 가장 좋은 판단 짝"].get(cellname)
    s["tf"][tf] = {"L": cd["단독 롱"], "S": cd["단독 숏"], "both": [[f["기준"], f["값"], f["방향"], f["고르기 신호당"], f["확인 신호당"], f["고르기 신호"], f["확인 신호"]] for f in both[:8]],
                   "nboth": len(both), "npick": len(pick_only),
                   "pick": [[f["기준"], f["값"], f["방향"], f["고르기 신호당"], f["확인 신호당"], f["고르기 신호"], f["확인 신호"]] for f in pick_only[:4]],
                   "judge": None if not pr else [pr["가장 좋은 판단 (고르기)"], pr["고르기 신호당"], pr["확인 신호당"], pr["그대로 확인 신호당"], pr["무작위 판단 확인 신호당"]]}


def best_alone(s):
    vals = []
    for tf, d in s["tf"].items():
        for k in ("L", "S"):
            a = d[k]
            if a["고르기 신호당"] is not None and a["확인 신호당"] is not None and a["고르기 신호"] >= 100:
                vals.append(min(a["고르기 신호당"], a["확인 신호당"]))
    return max(vals) if vals else -9


strats = sorted(strat.values(), key=lambda s: -best_alone(s))
for s in strats:
    s["best"] = round(best_alone(s), 4)
    s["nboth"] = sum(d["nboth"] for d in s["tf"].values())
J = [[k, v["고르기"]["차이"], v["확인"]["차이"], v["고르기"]["같은 방향 신호당"], v["확인"]["같은 방향 신호당"], v["고르기"]["반대 방향 신호당"], v["확인"]["반대 방향 신호당"]]
     for k, v in R["판단용 순위 (고르기 기간 차이 순)"].items()]
BOT = {k: {kk: vv for kk, vv in v.items() if kk != "고른 칸 목록 (앞 60)"} for k, v in R["봇"].items()}
DATA = {"strats": strats, "judges": J, "bot": BOT, "fit_rate": R["맞는 장이 확인 기간에도 플러스로 남은 비율"], "nfits": R["맞는 장 수"],
        "ko": {k: KO.get(k.split(" @")[0], k.split(" @")[0]) for k in R["판단용 순위 (고르기 기간 차이 순)"]}}
tpl = open(os.path.join(HERE, "roles_page.tpl.html")).read()
html = tpl.replace("/*__DATA__*/null", json.dumps(DATA, ensure_ascii=False, separators=(",", ":")))
open(os.path.join(HERE, "roles_page.html"), "w").write(html)
print("strategies", len(strats), "bytes", len(html))
