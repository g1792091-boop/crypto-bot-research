"""Build the role map (ROLES_KO.md + roles.json) from the hand classification (roles_table.py), the measured shape of
every strategy (roles_measured.csv from measure_roles.py), the forward sample sizes (forward_counts.csv from
forward_counts.py) and the bot configurations (deploy/*.json, the league's candidates.json passed as an argument).

    python3 build_roles.py <league candidates.json>
"""
import csv
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
import roles_table as RT  # noqa: E402

TFS = ("15m", "30m", "1h", "4h")
KIND_KO = {"range": "횡보 자리", "pullback": "눌림", "breakout": "돌파", "reversal": "반전", "other": "기타"}
ROLE_KO = {"trend": "추세 소스(판단만)", "entry": "진입", "timing": "타이밍 오실레이터"}
SET_KO = {"core": "규칙봇 36", "ds": "딥시크 44", "lib": "라이브러리", "reel": "릴스 5분", "friend": "친구"}
TREND_1021 = [("N08_ICHI_WR", "30m"), ("N05_PSAR_POC", "30m"), ("F3_BOS", "30m"), ("F15_ORB", "30m"),
              ("N06_MACD_ORB", "30m"), ("S3_CMO_SANDWICH", "30m"), ("N20_EMA9_CHOP", "30m"), ("F9_FVG", "1h"),
              ("F9_IFVG", "1h"), ("S3_CMO_SANDWICH", "1h")]          # git 0fafca9:deploy/combo.trend.json


def items():
    out = []
    for r in RT.CORE:
        d = dict(r)
        d.setdefault("dual", [])
        d.setdefault("kind", "")
        d.setdefault("judge", "")
        d["set"] = "core"
        out.append(d)
    for (i, ko, fn, role, kind, dual, judge, why) in RT.DSL:
        out.append(dict(id=i, ko=ko, set="ds", code=f"{RT.DS}:{fn} (규칙 원본 research/deepseek200/lib_c.py)", role=role,
                        kind=kind, dual=list(dual), judge=judge, why=why))
    for (i, role, kind, dual, judge, why) in RT.LIBL:
        out.append(dict(id=i, ko=i, set="lib", code=f"{RT.LIB}['{i}'] (+F200 쌍둥이 = EMA200 같은 쪽만)", role=role,
                        kind=kind, dual=list(dual), judge=judge, why=why))
    for r in RT.OTHER:
        d = dict(r)
        d.setdefault("dual", [])
        d.setdefault("judge", "")
        out.append(d)
    return out


def load_measured():
    M = defaultdict(dict)
    p = os.path.join(HERE, "roles_measured.csv")
    for r in csv.DictReader(open(p)):
        rec = {k: (float(v) if v not in ("", "nan") and k not in ("set", "name", "tf") else (None if v in ("", "nan") else v))
               for k, v in r.items()}
        rec["n"] = int(float(r["n"]))
        M[r["name"]][r["tf"]] = rec
    return M


def shape(meas):
    """Weighted (by signal count) prior20 / htf_agree and the signal-weighted mean of the per-tf EMA20 medians over the
    entry timeframes measured; a plain description, no profit."""
    n = sum(v["n"] for v in meas.values())
    if not n:
        return None
    w = lambda k: sum((v[k] or 0) * v["n"] for v in meas.values() if v[k] is not None) / max(1, sum(v["n"] for v in meas.values() if v[k] is not None))
    s = {"n": n, "prior20": round(w("prior20"), 3), "htf_agree": round(w("htf_agree"), 3),
         "htf_against": round(w("htf_against"), 3), "htf_hold": round(w("htf_hold"), 3), "ema_med": round(w("ema_med"), 3)}
    e = s["ema_med"]
    s["place_ko"] = ("EMA20 위로 뻗은 뒤(추격)" if e >= 0.8 else "EMA20 조금 위" if e >= 0.25 else
                     "EMA20 근처(눌림 자리)" if e >= -0.4 else "EMA20 반대편(되돌림·역행)")
    a = s["htf_agree"]
    s["htf_ko"] = "상위 추세 쪽" if a >= 0.62 else "상위 추세와 거의 무관" if a >= 0.45 else "상위 추세 반대 쪽이 많음"
    return s


def fwd_counts():
    acc = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(HERE, "forward_counts.csv"))):
        acc[r["strategy"]].append((r["account_id"], int(r["fwd_signals"]), int(r["fwd_trades"])))
    tb = json.load(open(os.path.join(HERE, "forward_counts_trendbot.json")))
    return acc, tb


def bots(byid):
    def cfg(name):
        return json.load(open(os.path.join(REPO, "deploy", name)))
    out = {}
    tr = cfg("combo.trend.json")
    out["trend_1022"] = [{"strategy": m["strategy"], "tf": m["tf"]} for m in tr["members"]]
    out["trend_1021"] = [{"strategy": s, "tf": t} for s, t in TREND_1021]
    ac = cfg("combo.live-ac.json")
    out["ac95"] = [{"strategy": m["strategy"], "tf": m["tf"], "invert": bool(m.get("invert")), "numbers": m.get("numbers"),
                    "cell": m.get("cell")} for m in ac["members"]]
    out["live15"] = [{"strategy": m["strategy"], "tf": m["tf"]} for m in cfg("combo.live15.json")["members"]]
    out["vwap"] = [{"strategy": m["strategy"], "tf": m["tf"]} for m in cfg("combo.vwap.json")["members"]]
    out["friend"] = [{"strategy": m["strategy"], "tf": m["tf"]} for m in cfg("combo.friend.json")["members"]]
    for k, lst in out.items():
        for m in lst:
            it = byid.get(m["strategy"])
            m["role"] = it["role"] if it else "?"
            m["kind"] = it.get("kind", "") if it else ""
    return out


def label(it):
    if it["role"] == "entry":
        return f"진입·{KIND_KO.get(it['kind'], it['kind'])}"
    return ROLE_KO[it["role"]]


def fmt_m(meas, tfs=TFS):
    """'15m 2.1/0.71/+0.4 · 1h ...' : signals per day / HTF agree / EMA20 distance median."""
    parts = []
    for tf in tfs:
        v = meas.get(tf)
        if not v or not v["n"]:
            continue
        ag = "–" if v["htf_agree"] is None else f"{v['htf_agree']:.2f}"
        em = "–" if v["ema_med"] is None else f"{v['ema_med']:+.1f}"
        pdv = v["per_day"] or 0
        pd_s = f"{pdv:.1f}" if pdv >= 0.1 else f"{pdv:.2f}"
        parts.append(f"{tf} {pd_s}/{ag}/{em}")
    return " · ".join(parts) if parts else "신호 없음"


def fmt_with(meas, tfs=("30m", "1h", "4h")):
    """signals per day left when only the higher-bar judge's side is kept (6 coins): per_day x htf_with."""
    parts = []
    for tf in tfs:
        v = meas.get(tf)
        if not v or not v["n"] or v["htf_with"] is None:
            continue
        x = (v["per_day"] or 0) * v["htf_with"]
        parts.append(f"{tf} {x:.1f}" if x >= 0.1 else f"{tf} {x:.2f}")
    return " · ".join(parts) if parts else "–"


def acc_text(accs):
    if not accs:
        return "규칙봇 계좌 없음"
    return ", ".join(f"{a}({s}/{t})" for a, s, t in sorted(accs, key=lambda x: TFS.index(x[0].split("@")[1]) if x[0].split("@")[1] in TFS else 9))


def main(cand_path):
    its = items()
    byid = {i["id"]: i for i in its}
    M = load_measured()
    acc, tb = fwd_counts()
    for it in its:
        it["note"] = RT.MEASURED_NOTES.get(it["id"], "")
        it["measured"] = M.get(it["id"], {})
        it["shape"] = shape({k: v for k, v in it["measured"].items()})
        accs = acc.get(it["id"], [])
        if it["id"] == "REEL5M_BB_MA200":
            accs = acc.get("REEL_H1", [])
        order = {t: k for k, t in enumerate(("5m",) + TFS)}
        accs = sorted(accs, key=lambda x: order.get(x[0].split("@")[-1], 9))
        it["accounts"] = [a for a, _s, _t in accs] or it.get("accounts", [])
        it["forward"] = {a: {"signals": s, "trades": t} for a, s, t in accs}
        it["_accs"] = accs
    B = bots(byid)
    cands = json.load(open(cand_path))["candidates"]
    league = []
    for c in cands:
        it = byid.get(c["name"])
        league.append({"id": c["id"], "strategy": c["name"], "tf": c["tf"], "kind_src": c["kind"], "exit": c["exit"],
                       "numbers": c.get("combo"), "role": it["role"] if it else "?", "kind": it.get("kind", "") if it else "",
                       "watch": c["source"].get("watch"), "tier": c["source"].get("tier", "watch" if c["source"].get("watch") else "")})
    for it in its:
        it["league"] = [l["id"] for l in league if l["strategy"] == it["id"]]
        tags = []
        for k, lst in B.items():
            tfs = sorted({m["tf"] for m in lst if m["strategy"] == it["id"]})
            if tfs:
                n = sum(1 for m in lst if m["strategy"] == it["id"])
                inv = sum(1 for m in lst if m["strategy"] == it["id"] and m.get("invert"))
                tags.append({"bot": k, "tfs": tfs, "members": n, "inverted": inv})
        it["bots"] = tags
        it["judge_in_trendbot"] = next((j["id"] for j in RT.JUDGES if j["strategy"] == it["id"]), None)

    # ---------------- roles.json
    def clean(it):
        d = {k: v for k, v in it.items() if not k.startswith("_")}
        return d
    roles = {
        "trend": [i["id"] for i in its if i["role"] == "trend"],
        "entry": {k: [i["id"] for i in its if i["role"] == "entry" and i["kind"] == k] for k in KIND_KO},
        "timing": [i["id"] for i in its if i["role"] == "timing"],
        "trend_incl_dual": [i["id"] for i in its if i["role"] == "trend" or "trend" in i["dual"]],
        "timing_incl_dual": [i["id"] for i in its if i["role"] == "timing" or "timing" in i["dual"]],
        "dual": {i["id"]: i["dual"] for i in its if i["dual"]},
    }
    meta = {
        "made": "2026-10-24", "by": "analysis/review1024/roles/map/build_roles.py",
        "principle_ko": "추세형은 상위 봉에서 방향만 판단하고 진입하지 않는다. 횡보 자리·눌림·돌파 매매법은 그 추세와 같은 쪽 신호만 진입한다(30분 진입 = 1시간 추세, 1시간 = 4시간, 4시간 = 일봉). 타이밍 오실레이터(스토캐스틱 RSI 등)는 추세 안에서 진입 타점으로 쓴다.",
        "how_ko": "역할은 각 매매법의 실제 코드(잠긴 규칙)를 읽고 정했습니다. 신호가 '추세 지표 상태의 변화'(이평 교차, 슈퍼트렌드 전환, DI 교차, 구름, PSAR, 레인지 필터 등)면 추세 소스, 가격이 자리·구간·선으로 되돌아오는 것이면 눌림, 박스·밴드 끝·평균회귀면 횡보 자리, 범위·구조 고점을 깨면 돌파, 다이버전스·스윕·구조 전환·반전 캔들이면 반전, 오실레이터 구역 교차만이면 타이밍입니다.",
        "measured_ko": "실측(roles_measured.csv): 2021-01-01 ~ 2026-10-23, 코인 6개, 신호가 난 봉의 위치만 셈(손익 아님). per_day = 하루 신호(6코인 합), htf_agree = 상위 봉 판단(4개 중 3개, 추세판단 봇과 같은 함수)이 방향을 낼 때 그 방향과 같은 비율(동전 던지기 0.5), ema_med = 방향 × (종가 − EMA20) / ATR14 중앙값.",
        "forward_ko": "forward = 규칙봇 v4 실시간(10/05~10/24) 계좌별 신호 수 / 닫힌 거래 수.",
        "counts": {"items": len(its), "trend": len(roles["trend"]),
                   "entry": {k: len(v) for k, v in roles["entry"].items()}, "timing": len(roles["timing"])},
    }
    J = {"meta": meta, "roles": roles, "judges": RT.JUDGES, "items": [clean(i) for i in its],
         "inner_timing": [{"strategy": s, "trigger": t, "code": c} for s, t, c in RT.INNER_TIMING],
         "bots": B, "league": league,
         "trendbot_forward_status": tb,
         "dlist": [{"id": i, "role": r, "kind": k, "why": w} for i, r, k, w in RT.DLIST]}
    json.dump(J, open(os.path.join(HERE, "roles.json"), "w"), ensure_ascii=False, indent=1)

    # ---------------- ROLES_KO.md
    L = []
    w = L.append
    w("# 역할 지도: 추세 소스 · 진입 매매법 · 타이밍 (친구 원칙)")
    w("")
    w("작성 2026-10-24 · `analysis/review1024/roles/map/` · 기계용 같은 내용: `roles.json`")
    w("")
    w("## 0. 이 지도가 무엇인가")
    w("")
    w("친구분 원칙: **추세형 매매법은 진입하지 않고 상위 봉에서 방향만 본다. 횡보 자리·눌림·돌파 매매법이 그 추세와 같은 쪽 신호를 낼 때만 진입한다** "
      "(30분 진입 = 1시간 추세, 1시간 진입 = 4시간 추세, 4시간 진입 = 일봉 추세). \"OBV 추세에 스톡 RSI로 타점\"처럼 오실레이터는 추세 안에서 진입 타이밍으로 쓴다.")
    w("규칙봇은 매매법마다 따로 돌고, 각 매매법이 **자기 안의 추세 판단으로** 진입합니다. 그래서 이 지도는 우리가 가진 매매법 전부를 세 역할로 나눠, "
      "다음 단계(역할끼리 조합 시험)에 바로 쓸 수 있게 만든 것입니다.")
    w("")
    w(f"- 다룬 것 {len(its)}개: 규칙봇 36 · 딥시크 44 · 라이브러리 40 · 릴스 5분 1 · 친구 매매법 1, 그리고 추세판단 봇 판단 4개, "
      f"추세판단 봇 진입 18개(10/22)·10개(10/21), A+C 합본 95개, 규칙봇 15, VWAP 봇, 후보 리그 49개, 제안만 있는 D 10개.")
    w(f"- 결과: 추세 소스 {meta['counts']['trend']}개 · 진입 " + ", ".join(f"{KIND_KO[k]} {v}개" for k, v in meta['counts']['entry'].items())
      + f" · 타이밍 {meta['counts']['timing']}개(라이브러리) + 매매법 안에 들어 있는 타이밍 {len(RT.INNER_TIMING)}개.")
    w("")
    w("### 역할을 정한 방법 (이름이 아니라 코드)")
    w("")
    w("- " + meta["how_ko"])
    w("- 두 역할을 겸하는 것은 '겸함'에 적었습니다(예: V3.9 = 슈퍼트렌드(10·3)는 판단, 진입은 눌림).")
    w("")
    w("### 실측 칸 읽는 법")
    w("")
    w("- " + meta["measured_ko"])
    w("- 표의 `15m 2.1/0.71/+0.4` = 15분봉에서 하루 2.1번 / 상위 추세와 같은 쪽 71% / EMA20에서 진입 방향으로 0.4 ATR(중앙값).")
    w("- **주의:** 추세형은 같은 가격 흐름을 보므로 상위 판단과 같은 쪽이 많은 게 당연합니다(실력 아님). 이 칸은 '어디서 진입하는 매매법인가'를 확인하는 용도이고 돈을 버는지와는 무관합니다.")
    w("- `규칙봇 계좌(신호/거래)` = 실시간 v4(10/05~10/24) 그 계좌의 신호 수 / 닫힌 거래 수. 계좌 하나에 거래 20번 안팎은 **표본이 작습니다**.")
    w("")

    def table(rows, cols):
        w("| " + " | ".join(c[0] for c in cols) + " |")
        w("|" + "---|" * len(cols))
        for r in rows:
            w("| " + " | ".join(str(c[1](r)).replace("|", "/") for c in cols) + " |")
        w("")

    # 0-1. key findings (numbers from the measurement)
    def sh(i, k):
        x = byid.get(i, {}).get("shape")
        return x[k] if x else float("nan")
    fast = ["S6_EMA_DMI_ADX", "S1_EMA_RSI_CHOP", "N24_DMI", "N22_VORTEX_PSAR", "N10_HA_PSAR", "N09_ALLIG_AROON",
            "T5_ST10_3", "T1_EMA9_21", "T3_MACD12_26_9", "T8_PSAR", "T12_HMA21", "F7_RF_ONLY"]
    slow = ["N03_ADX_GC", "T1_EMA50_200", "T2_SMA50_200", "N01_ST_EMA", "N02_ST_KST", "N04_ST_KLINGER", "N23_HA_ST",
            "S2_ST_ROC", "F4_FAN", "N12_ICHI_AO", "N18_VWMA_MACD"]
    wpull = ["F4_PULL", "F4_PULL_RSI", "FRIEND_ROC", "V39_ALL", "F3_BOS_ZONE", "REEL5M_BB_MA200", "N25_DST_CCI"]
    zpull = ["F16_FIB382", "F16_FIB500", "F16_FIB618", "F16_FIB764", "F10_OTE", "F9_OB", "F9_FVG", "F9_IFVG", "F8_VWICK", "F6_VWAP_FAIL", "N05_PSAR_POC"]
    fade = ["N17_KC_RSI", "O1_RSI14_REV30", "F5_BOX_RSI", "F5_BOX_HTF", "F5_BOX", "F2_DEMARK", "F17_Z", "N16_BBRSI", "F1_RSI_DIV", "N11_BREAKAWAY", "F11_TSOUP"]
    brk = ["F3_BOS", "N06_MACD_ORB", "S4_BB_BBP", "F15_ASIA_BRK", "F15_LON_BRK", "F15_ORB", "T6_DON55"]
    lst = lambda ids: ", ".join(f"`{i}` {sh(i, 'htf_agree'):.2f}" for i in ids)
    n95 = sum(1 for m in B["ac95"] if m["role"] == "trend")
    w("## 0-1. 핵심 발견 (먼저 읽을 것)")
    w("")
    w("숫자 = 상위 봉 판단(4개 중 3개)이 방향을 낼 때 그 매매법 진입 신호가 같은 쪽인 비율(동전 던지기 0.50). 2021~2026, 6코인, 손익 아님.")
    w("")
    w(f"1. **친구 말이 데이터에도 보입니다.** 진입 봉에서 '추세가 막 시작됐다'고 들어가는 빠른 추세형은 상위 추세와 동전 수준이거나 더 자주 반대입니다: {lst(fast)}. "
      f"S6(EMA·DMI·ADX)은 진입 신호의 절반 넘게가 상위 판단과 반대입니다. 반면 느린 추세형은 큰 추세와 거의 같습니다: {lst(slow)}. "
      "→ 추세형은 진입이 아니라 **상위 봉의 상태(판단)** 로 쓰는 게 맞다는 친구 원칙과 맞는 그림입니다. (방향 일치일 뿐 돈을 번다는 뜻은 아님)")
    w(f"2. **진입 매매법은 종류에 따라 상위 추세와의 관계가 크게 다릅니다.** 자체 추세 거르개가 있는 눌림형은 이미 대부분 같은 쪽: {lst(wpull)}. "
      f"자리(피보·OTE·OB·FVG·VWAP 재시험)형은 반반: {lst(zpull)} → 상위 판단이 반대인 신호 {min(sh(i, 'htf_against') for i in zpull):.0%}~{max(sh(i, 'htf_against') for i in zpull):.0%}가 빠지고(보류 허용), "
      f"보류까지 막으면 {min(1 - sh(i, 'htf_against') - sh(i, 'htf_hold') for i in zpull):.0%}~{max(1 - sh(i, 'htf_against') - sh(i, 'htf_hold') for i in zpull):.0%}만 남습니다. "
      f"횡보·평균회귀·반전형은 대부분 반대 쪽: {lst(fade)} → 추세 판단으로 거르면 신호가 거의 남지 않으므로, 이들은 '추세 없음(보류·ADX 낮음)' 판단과 짝지어야 합니다. "
      f"돌파형: {lst(brk)}.")
    w("3. **코드 이름과 실제 진입 자리가 다른 것**이 있습니다: `N19_FIB_CHOP`(50% 눌림인데 실제 진입은 EMA20 위 1.2 ATR), `DOGE`(EMA20 위 0.9 ATR의 얕은 눌림), "
      "`F12_MSS`·`F12_MSS_DISP`(전환이지만 돌파 봉에서 진입), `OBV_B`(이름은 돌파, 실제는 단기 반전). 조합 시험에서는 '실측 모양'을 같이 봐야 합니다.")
    w(f"4. **지금까지 봇들은 친구 원칙과 반대로 짜인 부분이 있습니다.** A+C 합본 95개 중 {n95}개가 추세형 매매법을 진입으로 썼고(뒤집어 쓴 것 포함), "
      "추세판단 봇도 10/21 설계에 `N08_ICHI_WR`(추세형) 30분, 10/22 설계에 `F7_RF_TRIPLE`(추세형) 4시간이 진입 멤버로 들어 있습니다. "
      f"후보 리그 49개 중에서도 {sum(1 for l in league if l['role'] == 'trend')}개가 추세형입니다.")
    w("5. **친구 말 그대로의 'OBV 추세 + 스토캐스틱 RSI 타점'은 어느 봇에도 없습니다.** 규칙봇 `OBV_S`는 OBV 추세와 스토캐스틱 교차를 **같은 봉 안에서**, "
      f"과매도 구역 조건 없이 합니다. `O4_STOCHRSI_ZONE`(스토캐스틱 RSI 구역 교차) 신호는 상위 판단과 {sh('O4_STOCHRSI_ZONE', 'htf_agree'):.2f}(동전 수준)이라, "
      "상위 봉 추세로 거르면 1시간봉 기준 하루 약 5번(6코인)이 남습니다. 이것이 7-2의 첫 번째 시험 후보입니다.")
    w("")

    # 1. trend sources
    w("## 1. 추세 소스 (판단만, 진입 안 함)")
    w("")
    w("신호가 '추세 지표 상태가 바뀌는 순간'인 매매법들입니다. 친구 원칙대로라면 이들은 **상위 봉에서 '판단 상태' 칸의 상태만 읽고** 진입에는 쓰지 않습니다.")
    w("")
    w("### 1-1. 지금 추세판단 봇이 쓰는 판단 4개 (`paperbot/trendjudge.py:vote_arrays`)")
    w("")
    table(RT.JUDGES, [("판단", lambda r: f"{r['id']} ({r['ko']})"), ("읽는 상태", lambda r: r["state"]),
                      ("원래 매매법(규칙봇 계좌)", lambda r: f"`{r['strategy']}` " + ", ".join(byid[r['strategy']]["accounts"])),
                      ("코드", lambda r: f"`{r['code']}`")])
    w("4개 중 3개가 같은 쪽이면 상승/하락, 아니면 보류. ADX 20 이상, 40 넘고 꺾이면 끝물. (판단 계산은 진입 신호와 별개: V3.9는 판단에서는 슈퍼트렌드(10·3) 방향만 씁니다.)")
    w("")
    for st in ("core", "ds", "lib", "friend"):
        rows = [i for i in its if i["set"] == st and (i["role"] == "trend" or "trend" in i["dual"])]
        if not rows:
            continue
        w(f"### 1-{['core', 'ds', 'lib', 'friend'].index(st) + 2}. {SET_KO[st]}")
        w("")
        table(rows, [("이름", lambda r: f"`{r['id']}` {r['ko'] if r['ko'] != r['id'] else ''}".strip()),
                     ("역할", lambda r: label(r) + (" (겸함: 추세)" if r["role"] != "trend" else "")),
                     ("판단 상태(상위 봉에서 읽을 것)", lambda r: r["judge"] or "–"),
                     ("왜(코드)", lambda r: r["why"]),
                     ("코드 위치", lambda r: f"`{r['code']}`"),
                     ("규칙봇 계좌(신호/거래)", lambda r: acc_text(r["_accs"]) if st != "lib" else "없음(연구 전용)"),
                     ("실측 하루/상위일치/EMA20", lambda r: fmt_m(r["measured"])),
                     ("실측 메모", lambda r: r["note"] or "–")])

    # 2. entries
    w("## 2. 진입 매매법 (추세 소스가 정한 방향과 같은 쪽 신호만 진입)")
    w("")
    for k in ("range", "pullback", "breakout", "reversal", "other"):
        rows = [i for i in its if i["role"] == "entry" and i["kind"] == k]
        w(f"### 2-{list(KIND_KO).index(k) + 1}. {KIND_KO[k]} ({len(rows)}개)")
        w("")
        table(rows, [("이름", lambda r: f"`{r['id']}` {r['ko'] if r['ko'] != r['id'] else ''}".strip()),
                     ("묶음", lambda r: SET_KO[r["set"]]),
                     ("왜(코드)", lambda r: r["why"] + (f" · 겸함: {', '.join(r['dual'])}" if r["dual"] else "")),
                     ("코드 위치", lambda r: f"`{r['code']}`"),
                     ("규칙봇 계좌(신호/거래)", lambda r: acc_text(r["_accs"]) if r["set"] != "lib" else "없음(연구 전용)"),
                     ("실측 하루/상위일치/EMA20", lambda r: fmt_m(r["measured"], TFS if r["set"] != "reel" else ("5m",))),
                     ("실측 모양", lambda r: (f"{r['shape']['place_ko']}, {r['shape']['htf_ko']}" if r["shape"] else "–")),
                     ("판단 같은 쪽만 남으면 하루", lambda r: fmt_with(r["measured"], ("30m", "1h", "4h") if r["set"] != "reel" else ("5m",))),
                     ("실측 메모", lambda r: r["note"] or "–")])

    # 3. timing
    w("## 3. 타이밍 오실레이터 (추세 안에서 진입 방아쇠)")
    w("")
    rows = [i for i in its if i["role"] == "timing" or ("timing" in i["dual"] and i["set"] == "lib")]
    table(rows, [("이름", lambda r: f"`{r['id']}`"), ("역할", lambda r: label(r) + (" (겸함: 타이밍)" if r["role"] != "timing" else "")),
                 ("방아쇠(코드)", lambda r: r["why"]), ("코드 위치", lambda r: f"`{r['code']}`"),
                 ("실측 하루/상위일치/EMA20", lambda r: fmt_m(r["measured"])),
                 ("판단 같은 쪽만 남으면 하루", lambda r: fmt_with(r["measured"])),
                 ("실측 메모", lambda r: r["note"] or "–")])
    w("### 3-1. 이미 매매법 안에 들어 있는 타이밍 (따로 떼어 쓸 수 있는 방아쇠)")
    w("")
    table([{"s": s, "t": t, "c": c} for s, t, c in RT.INNER_TIMING],
          [("매매법", lambda r: f"`{r['s']}`"), ("방아쇠", lambda r: r["t"]), ("코드", lambda r: f"`{r['c']}`")])

    # 4. bots
    w("## 4. 지금·예전 봇의 멤버는 어느 역할인가")
    w("")
    def bot_rows(lst, show_inv=False):
        c = Counter()
        for m in lst:
            c[(m["strategy"], m["tf"], m["role"], m["kind"], m.get("invert", False))] += 1
        return [{"s": s, "tf": tf, "role": ro, "kind": ki, "inv": iv, "n": n} for (s, tf, ro, ki, iv), n in c.items()]
    def mtf(r, key):
        v = byid.get(r["s"], {}).get("measured", {}).get(r["tf"])
        if not v or not v["n"] or v.get(key) is None:
            return "–"
        return f"{v[key]:.2f}" if key != "per_day" else f"{v[key]:.1f}"
    w("### 4-1. 추세판단 봇 10/22 설계 (지금 페이퍼, `deploy/combo.trend.json`, 진입 18개)")
    w("")
    w("5년 실측(2021~2026, 6코인): 그 봉에서 하루 신호 / 상위 판단과 같은 쪽 / 반대 쪽 / 보류. 반대 쪽 신호는 이 봇이 막는 몫입니다(보류 허용).")
    w("")
    table(bot_rows(B["trend_1022"]), [("진입 봉", lambda r: r["tf"]), ("매매법", lambda r: f"`{r['s']}`"),
                                       ("코드로 본 역할", lambda r: ROLE_KO[r["role"]] if r["role"] != "entry" else f"진입·{KIND_KO[r['kind']]}"),
                                       ("친구 원칙과 맞나", lambda r: "맞음(진입형)" if r["role"] == "entry" else "**아님: 추세형을 진입에 씀**"),
                                       ("하루", lambda r: mtf(r, "per_day")), ("같은 쪽", lambda r: mtf(r, "htf_with")),
                                       ("반대", lambda r: mtf(r, "htf_against")), ("보류", lambda r: mtf(r, "htf_hold"))])
    w("### 4-2. 추세판단 봇 10/21 설계 (진입 10개, git `0fafca9`)")
    w("")
    table(bot_rows(B["trend_1021"]), [("진입 봉", lambda r: r["tf"]), ("매매법", lambda r: f"`{r['s']}`"),
                                       ("코드로 본 역할", lambda r: ROLE_KO[r["role"]] if r["role"] != "entry" else f"진입·{KIND_KO[r['kind']]}"),
                                       ("친구 원칙과 맞나", lambda r: "맞음(진입형)" if r["role"] == "entry" else "**아님: 추세형을 진입에 씀**")])
    ac = B["ac95"]
    by = Counter((m["strategy"], m["role"], m["kind"]) for m in ac)
    inv = Counter(m["strategy"] for m in ac if m["invert"])
    tfs = defaultdict(Counter)
    for m in ac:
        tfs[m["strategy"]][m["tf"]] += 1
    n_tr = sum(n for (s, ro, k), n in by.items() if ro == "trend")
    w(f"### 4-3. A+C 합본 95개 (`deploy/combo.live-ac.json`, 10/19~10/21 페이퍼, 커스텀 숫자·자체 손절)")
    w("")
    w(f"95개 중 **{n_tr}개가 추세형 매매법을 진입으로 쓴 멤버**입니다(그중 {sum(inv[s] for (s, ro, k) in by if ro == 'trend')}개는 신호를 뒤집어(invert) 씀). 친구 원칙과 정반대 구조입니다.")
    w("한 가지 우연: A+C가 뒤집어 쓴 `S6_EMA_DMI_ADX`(1시간 3개)는 원래 진입 신호의 56%가 상위 판단과 반대였으므로, 뒤집으면 오히려 큰 추세 쪽 진입이 됩니다. "
      "반대로 뒤집은 `N08_ICHI_WR`(9개)는 원래 신호가 상위 판단과 75% 같은 쪽이라 뒤집으면 큰 추세 반대 쪽 진입이 됩니다.")
    w("")
    table(sorted([{"s": s, "role": ro, "kind": k, "n": n, "inv": inv[s], "tfs": tfs[s]} for (s, ro, k), n in by.items()], key=lambda r: -r["n"]),
          [("매매법", lambda r: f"`{r['s']}`"), ("멤버 수", lambda r: r["n"]), ("뒤집음", lambda r: r["inv"]),
           ("봉", lambda r: ", ".join(f"{t}×{c}" for t, c in sorted(r['tfs'].items()))),
           ("코드로 본 역할", lambda r: ROLE_KO[r["role"]] if r["role"] != "entry" else f"진입·{KIND_KO[r['kind']]}")])
    for key, title in (("live15", "규칙봇 15 (`deploy/combo.live15.json`, 10/20 실거래 후보)"),
                       ("vwap", "VWAP 개선판 봇 (`deploy/combo.vwap.json`)"), ("friend", "친구 매매법 봇 (`deploy/combo.friend.json`, 설치 보류)")):
        w(f"### 4-{['live15', 'vwap', 'friend'].index(key) + 4}. {title}")
        w("")
        table(bot_rows(B[key]), [("진입 봉", lambda r: r["tf"]), ("매매법", lambda r: f"`{r['s']}`"),
                                 ("코드로 본 역할", lambda r: ROLE_KO[r["role"]] if r["role"] != "entry" else f"진입·{KIND_KO[r['kind']]}")])
    w("### 4-7. 추세판단 봇 기록의 매매법별 신호 상태 (live-ac.db, 10/19~10/24, 세 설계가 섞임)")
    w("")
    w("멤버 이름 뒤 `#번호~해시`(95개 시절)는 떼고 합쳤습니다. SUBMITTED = 진입 신청, FILTERED = 검사·시간 막기로 걸러짐, BROKE = 돌파 대기 실패.")
    w("")
    table(sorted([{"k": k, **v} for k, v in tb.items()], key=lambda r: r["k"]),
          [("멤버", lambda r: f"`{r['k']}`"), ("SUBMITTED", lambda r: r.get("SUBMITTED", 0)), ("FILTERED", lambda r: r.get("FILTERED", 0)),
           ("BROKE", lambda r: r.get("BROKE", 0)),
           ("역할", lambda r: label(byid[r['k'].split('@')[0]]) if r['k'].split('@')[0] in byid else "?")])

    # 5. league
    w("## 5. 후보 리그 49개의 역할 (`etc/candidates.json`)")
    w("")
    w("리그 계좌 이름 = 후보 id + 청산 꼬리표(예: `core-OBV_S-1h-3-ld`, `-fq`, `-nv`, `-sw` …).")
    w("")
    lc = Counter((l["role"], l["kind"]) for l in league)
    w("요약: " + ", ".join(f"{ROLE_KO[ro] if ro != 'entry' else '진입·' + KIND_KO[k]} {n}개" for (ro, k), n in lc.most_common()))
    w("")
    table(league, [("후보 id", lambda r: f"`{r['id']}`"), ("매매법", lambda r: f"`{r['strategy']}`"), ("봉", lambda r: r["tf"]),
                   ("커스텀 숫자", lambda r: json.dumps(r["numbers"], ensure_ascii=False) if r["numbers"] else "기본값"),
                   ("청산", lambda r: r["exit"]), ("등급", lambda r: r["tier"]),
                   ("코드로 본 역할", lambda r: ROLE_KO[r["role"]] if r["role"] != "entry" else f"진입·{KIND_KO[r['kind']]}")])

    # 6. D list
    w("## 6. 제안만 있는 D 목록 (카탈로그 D-1~D-10, 규칙봇에 없음, 그 형태로는 시험 전)")
    w("")
    table([{"i": i, "r": r, "k": k, "w": wy} for i, r, k, wy in RT.DLIST],
          [("이름", lambda r: f"`{r['i']}`"), ("역할", lambda r: ROLE_KO.get(r["r"], "기타") if r["r"] != "entry" else f"진입·{KIND_KO[r['k']]}"),
           ("왜", lambda r: r["w"])])
    # 7. hand-over to the combination study
    fam = RT.FAMILIES
    w("## 7. 다음 단계(역할 조합 시험)에 넘기는 재료")
    w("")
    w("### 7-1. 추세 소스를 계열로 묶기 (같은 계열은 거의 같은 판단을 냄)")
    w("")
    table([{"f": f, "m": m, "s": s} for f, m, s in fam],
          [("계열", lambda r: r["f"]), ("멤버", lambda r: ", ".join(f"`{x}`" for x in r["m"])), ("상위 봉에서 읽을 상태", lambda r: r["s"])])
    n_tr_all = sum(1 for i in its if i["role"] == "trend" or "trend" in i["dual"])
    w(f"계열이 서로 비슷해서 '추세 소스 {n_tr_all}개(겸함 포함)'는 실제로는 독립된 판단 {len(fam)}개 남짓입니다. 조합 시험은 **계열 대표 하나씩**으로 시작해야 "
      "시도 횟수(다중 비교)가 덜 부풀어요.")
    w("")
    w("### 7-2. 친구 말 그대로의 조합 (먼저 시험할 것)")
    w("")
    for line in RT.FRIEND_COMBOS:
        w(f"- {line}")
    w("")
    w("### 7-3. 진입 쪽 후보 묶음")
    w("")
    for k in ("pullback", "range", "breakout", "reversal", "other"):
        ids = [i["id"] for i in its if i["role"] == "entry" and i["kind"] == k]
        w(f"- **{KIND_KO[k]}** ({len(ids)}): " + ", ".join(f"`{x}`" for x in ids))
    w("- **타이밍(방아쇠)**: " + ", ".join(f"`{i['id']}`" for i in its if i["role"] == "timing")
      + " + 3-1의 매매법 안 방아쇠")
    w("")
    # 8. honesty
    core_tr = sorted(t for i in its if i["set"] == "core" for _a, _s, t in i["_accs"])
    ds_tr = sorted(t for i in its if i["set"] == "ds" for _a, _s, t in i["_accs"])
    med = lambda x: x[len(x) // 2] if x else 0
    w("## 8. 솔직하게")
    w("")
    w("- 역할은 코드를 읽고 정한 **분류**입니다. 성적으로 고른 것이 아니라서 여기에는 고르기 편향이 없지만, 아래 매매법은 두 역할이 섞여 있어 "
      "분류가 갈릴 수 있습니다: " + ", ".join(f"`{x}`" for x in RT.AMBIGUOUS) + ".")
    w("- 실측 칸은 '신호가 어디서 나는가'만 보여줍니다. **돈을 버는지는 전혀 말하지 않습니다.** 조합 시험은 고르는 기간과 확인 기간을 나누고, "
      "같은 신호에 동전 방향을 붙인 대조군과 비교하고, 시도한 조합 수만큼 보정(BH 또는 전체 섞기 시험)해야 합니다.")
    w(f"- 실시간(10/05~10/24) 규칙봇 계좌 하나의 닫힌 거래는 중앙값으로 규칙봇 36 {med(core_tr)}번, 딥시크 {med(ds_tr)}번뿐입니다. "
      "이 정도 표본으로는 매매법 하나의 실력을 말할 수 없습니다. 게다가 이 기간은 대부분 하락장이라 숏 신호가 많은 매매법이 운으로 좋아 보일 수 있습니다.")
    w("- **30분 진입 + 1시간 판단은 봉 길이 차이가 2배뿐**입니다(15분→1시간, 1시간→4시간은 4배, 4시간→일봉은 6배). 깊게 되돌림을 사는 매매법은 1시간 판단이 그 되돌림 자체를 보고 "
      "반대로 돌아서기 쉬워서, 30분에서만 일치가 크게 떨어집니다(`V45_AMB` 15분 0.77 · 30분 0.09 · 1시간 0.80, `N25_DST_CCI` 0.84 · 0.55 · 0.83; V4.5는 30분에서 자기 상위 봉으로 2시간을 봄). "
      "30분 정각 신호는 방금 닫힌 1시간봉(그 30분봉을 포함)을 읽지만, 이것이 원인은 아니었습니다(정각·30분 신호를 나눠 봐도 같음, `check_30m.py`). "
      "깊은 눌림형은 4배 이상 차이에서 시험하는 게 맞습니다.")
    w("- 추세형의 '상위 추세 일치'가 높은 것은 같은 가격을 보기 때문에 생기는 기계적인 일치입니다. 판단이 맞는다는 증거가 아닙니다.")
    w("- 실측은 2021-01-01 ~ 2026-10-23(오르는 해·내리는 해 모두 포함), 상위 판단은 지금 추세판단 봇과 같은 함수(보류 유지 조건 없이 그 봉의 4개 중 3개)입니다. "
      "15분 진입은 1시간 판단을 봤습니다(추세판단 봇에는 15분 진입이 없음).")
    w("")
    w("## 9. 파일")
    w("")
    w("- `roles.json`: 이 문서와 같은 내용(기계용). `items[]`마다 id, set, code, role, kind, dual, judge, why, accounts, forward, league, bots, measured(봉별), shape.")
    w("- `roles_measured.csv`: 실측 표(매매법 × 봉). `roles_table.py`: 손으로 정한 분류(코드 위치·이유). `measure_roles.py`: 실측 계산. "
      "`forward_counts.py`: 실시간 표본 수. `check_30m.py`: 30분 정각/30분 신호 나눠 보기. `build_roles.py`: 이 문서와 JSON 만들기.")
    open(os.path.join(HERE, "ROLES_KO.md"), "w").write("\n".join(L) + "\n")
    print("items", len(its), json.dumps(meta["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
