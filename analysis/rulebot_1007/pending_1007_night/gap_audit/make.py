"""Write gap_audit.json and gap_audit.md from rows.py + the delay results.  python3 -I make.py <gap_dir>"""
import json
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from rows import R  # noqa: E402

out = sys.argv[1]
D = json.load(open(os.path.join(here, "delay_results.json")))
C = json.load(open(os.path.join(here, "commit_timing.json")))
tw = {(r["run"], r["tf"]): r for r in D["twins"]}
dl = {(r["run"], r["tf"], r["group"]): r for r in D["delay_by_tf_group"]}

must = [r for r in R if r["blocks_1017"].startswith(("예", "결정"))]
later = [r for r in R if not r["blocks_1017"].startswith(("예", "결정"))]
cnt = {s: sum(1 for r in R if r["status"] == s) for s in ("있음", "일부", "없음")}
must_days = sum(r["days"] for r in must)
later_days = sum(r["days"] for r in later)

js = {"title": "AI 트레이더 붙이기 빈틈 점검 (10/8)", "repo_commit": "3494fd8", "counts": cnt,
      "must_have_days": must_days, "later_days": later_days, "rows": R,
      "delay": {"rule_fill_check": D["rule_fill_check"], "feed_lag_1m": D["feed_lag_1m"],
                "signal_delay": D["delay_by_tf_group"], "commit_timing_v4": C["v4"],
                "twins_pooled": [tw[("ALL", t)] for t in ("15m", "30m", "1h", "4h")]}}
json.dump(js, open(os.path.join(out, "gap_audit.json"), "w"), ensure_ascii=False, indent=1)


def f(x, n=3):
    return f"{x:+.{n}f}" if isinstance(x, float) else str(x)


L = []
a = L.append
a("# AI 트레이더 붙이기: 지금 규칙 봇에 없는 것 (빈틈 점검, 10/8)")
a("")
a("대상: 저장소 커밋 3494fd8의 `paperbot/`·`deploy/`·`data/`·`docs/aibot/`, 내보낸 자료 export_1007(v3b·v4). "
  "저장소는 읽기만 했습니다. 지연 숫자는 `gap/work/delay.py`(저장소 엔진 `daily3._alone`로 재생)에서 나왔습니다.")
a("")
a("## 0. 한눈에")
a("")
a(f"- 필요한 기능 {len(R)}개 중 **있음 {cnt['있음']} · 일부 {cnt['일부']} · 없음 {cnt['없음']}**.")
a(f"- 10/17 전에 꼭 있어야 하는 것 {len(must)}개, 대략 **{must_days:.1f}일 분량**(시험 포함, 한 명이 순서대로 할 때의 거친 추정; 나눠 만들면 달력 일수는 줄지만 통합·시험 시간은 남음). "
  f"나중에 해도 되는 것 {len(later)}개 약 {later_days:.1f}일. PLAN 3장의 '만들기 3~5일'로는 모자랍니다. "
  "10/17을 지키려면 아래 2장의 줄인 범위(보유 중 깨움 없이 코드 청산만, 4h 끄기 등)를 **D0 전에 사전 등록**하거나, 하루씩 미뤄야 합니다.")
a("- **구조 권장:** AI 계좌를 paper3.db에 새 kind로 넣지 말고, 별도 프로세스 + 별도 `aibot.db`(같은 `engine.PaperEngine` 코드)로. "
  "이유: kind로 나누는 모듈이 17개 이상이고, `checkpoint.account_family`는 모르는 kind를 규칙 봇 'core' 판정 묶음에 넣으며(572행), "
  "`resetrun`은 paper3.db를 통째로 옮기고, `extras.post_boundary` 훅은 러너 루프 안에서 동기 실행이라 AI 호출을 거기서 하면 331계좌의 손절 처리가 멈춥니다. "
  "신호는 paper3.db `signal_log`를 읽기 전용으로 따라 읽고, 1분봉도 같은 DB의 `live_bars`를 읽으면 규칙 계좌와 똑같은 봉으로 체결·청산됩니다.")
a("- **지연:** 규칙 계좌는 '다음 1분봉 시가'가 아니라 **계산 직후 bookTicker 가격**에 들어갑니다(진입 1,430건 전부 확인). "
  "AI 답은 평균 봉 마감 뒤 47초(15m)~59초(4h)에 옵니다. 평균 지연 비용은 0과 구별되지 않지만(15m −0.037R ± 0.029), "
  "결정 하나당 흔들림이 15m sd 0.57R로 큽니다. 그래서 **신호 시각 쌍둥이와 AI 체결 시각 쌍둥이를 둘 다** 두고, 판단 효과는 AI − AI 체결 시각 쌍둥이로 잽니다(3장).")
a("- **결정이 먼저 필요한 것:** 크기 규칙 하나(OwnerPolicy / RecommendedPolicy / 새 '1% + 가장 높은 가능 레버리지'), "
  "진입 봉 범위(PLAN·설계 v2·종합안이 서로 다름), 보유 중 AI 개입을 1판에 넣을지.")
a("")
a("## 1. 기능별 표")
a("")
a("상태: 있음 / 일부 / 없음. 크기: S ≤1일, M 1.5~2.5일, L ≥3일(일 = 시험 포함 대략). '10/17 막음?': 예 = 없으면 시작 불가, 결정 = 두 분 결정이 먼저.")
a("")
a("| # | 묶음 | 기능 | 상태 | 어디에 (파일·함수) | 만들 것 | 크기(일) | 10/17 막음? | 위험 |")
a("|---|---|---|---|---|---|---|---|---|")
for i, r in enumerate(R, 1):
    a(f"| {i} | {r['area'][0]} | {r['capability']} | {r['status']} | {r['where']} | {r['build']} | {r['effort']} ({r['days']:g}) | "
      f"{r['blocks_1017']} | {r['risk']} |")
a("")
a("## 2. 10/17 전에 꼭 vs 나중에")
a("")
a(f"### 꼭 있어야 함 ({len(must)}개, 약 {must_days:.1f}일)")
for r in must:
    a(f"- {r['capability']} — {r['effort']} {r['days']:g}일 ({r['status']})")
a("")
a(f"### 나중에 해도 됨 ({len(later)}개, 약 {later_days:.1f}일; 기록만 빠짐없으면 1일차부터 소급 계산)")
for r in later:
    a(f"- {r['capability']} — {r['effort']} {r['days']:g}일")
a("")
a("### 10/17을 지키려면 줄일 수 있는 것 (모두 D0 전에 사전 등록해야 함)")
a("- 보유 중 AI 깨움을 1판에서 빼고 코드 청산만(−1.5일). 대신 'AI 청산 실력'은 1판에서 재지 않음.")
a("- 4h 진입 끄기(20배 검사 관문 −0.5일). 4h는 하루 0.12번 수준이라 잃는 표본이 작음.")
a("- 체결은 AI·쌍둥이·동전 모두 지금 규칙 봇과 같은 고정 2bp(호가 함수 없음).")
a("- 시장 자료는 펀딩(정산값)·flow.db(늦음 표시)·liq.db만, 5분 poll은 2주 안에.")
a("- 판정 코드·보고서·대시보드 탭은 기록에서 소급 계산(단 판정식과 동전 범위는 문서로 D0 전에 잠금).")
a("")
a("## 3. 지연(타이밍) 분석")
a("")
a("### 3-1. 규칙 계좌의 진입 가격과 시각 (코드)")
a("- `sigservice.SignalService.compute`: 그 봉의 신호 계산이 끝난 순간 `ready_at = now_ms()`, 곧바로 `book()`(REST bookTicker)로 "
  "롱은 ask, 숏은 bid를 `ref_price`로 둡니다. `delay_ms = ready_at − 봉 마감`.")
a("- `engine._try_enter`: 체결가 = `ref_price × (1 ± 0.0002)`, 진입 시각 기록 = 다음 1분봉의 `open_time`(= 봉 마감 시각). 손절 = ref − side × 2 ATR.")
fc = {x["run"]: x for x in D["rule_fill_check"]}
a(f"- 확인: 진입 v3b {fc['v3b']['fill_eq_ref_x_slip']}/{fc['v3b']['entered']}, v4 {fc['v4']['fill_eq_ref_x_slip']}/{fc['v4']['entered']}건이 정확히 ref×(1±2bp), "
  "진입 시각은 모두 봉 마감 시각. **규칙 계좌는 1분봉 시가에 들어간 적이 없습니다.**")
a("- 엔진 버릇: 진입한 1분봉의 고가·저가 전체로 손절을 검사합니다(체결 전 약 20~40초 구간 포함). 쌍둥이를 같은 엔진 경로로 돌리면 서로 상쇄됩니다.")
a("")
a("### 3-2. 지연은 어디서 생기나 (v4, 초)")
lag = {x["run"]: x for x in D["feed_lag_1m"]}
a(f"- 1분봉을 받는 데: 마감 뒤 평균 {lag['v4']['mean_s']:.1f}초(90% {lag['v4']['p90_s']:.1f}초) — feed가 마감 8초 뒤부터 읽고 5초마다 poll.")
a("- 신호 준비(delay_ms 평균): 우리 36 " + ", ".join(f"{t} {dl[('v4', t, 'core')]['mean_s']:.1f}" for t in ("15m", "30m", "1h", "4h")) +
  "; 딥시크 " + ", ".join(f"{t} {dl[('v4', t, 'ds200')]['mean_s']:.1f}" for t in ("15m", "30m", "1h", "4h")) +
  f". 모든 SUBMITTED 평균 {dl[('v4', 'ALL', 'ALL')]['mean_s']:.1f}초(대시보드 26.7초와 같은 크기; 경계당 첫 신호 기준 {dl[('v4', 'ALL', 'ALL')]['mean_s_per_boundary']:.1f}초). 봉을 15m→30m→1h→4h 순서로, 딥시크는 그 뒤에 계산해서 긴 봉일수록 늦습니다.")
a("- 다른 프로세스가 신호를 볼 수 있는 때(경계의 커밋 = 딥시크 계산 뒤): " +
  ", ".join(f"{t} 평균 {C['v4'][t]['commit_mean_s']}초(95% {C['v4'][t]['commit_p95_s']})" for t in ("15m", "30m", "1h", "4h")) + ", 최대 46.3초.")
a("- 20초 마감이면 AI 답은 평균 " + ", ".join(f"{t} {C['v4'][t]['ans_mean_s_L20']}초" for t in ("15m", "30m", "1h", "4h")) +
  ". 그 봉 다음 1분봉이 처리되는 때(약 72초)보다 늦는 답은 0%.")
a("")
a("### 3-3. AI 진입이 받을 가격과 차이 (재생, v3b+v4 합침, AI 지연 20초)")
a("설계 5-3 7번대로 '답 받은 분의 다음 분 시가'에 들어간다고 놓고, 같은 신호를 같은 엔진·같은 2 ATR 손절로 두 번 돌렸습니다: "
  "신호 시각 쌍둥이(규칙 계좌가 받은 ref) vs AI 체결 시각 쌍둥이.")
a("")
a("| 봉 | 짝 수 (둘 다 진입) | 체결이 T+120초 이후 (커밋+20초 기준) | 가격 차 평균 \\|R\\| | 가격 차 중앙 \\|bp\\| | 부호 있는 가격 차 R | ΔR 평균 (AI 시각 − 신호 시각) | 묶음 SE | ΔR sd (결정당) | \\|ΔR\\|>0.5R 비율 |")
a("|---|---|---|---|---|---|---|---|---|---|")
big = {"15m": 0.054, "30m": 0.047, "1h": 0.037, "4h": 0.009}
for t in ("15m", "30m", "1h", "4h"):
    r = tw[("ALL", t)]
    a(f"| {t} | {r['L20_dR_n']} | {C['v4'][t]['share_fill_ge_120s_L20']:.1%} (v4) | {r['L20_absgapR_mean']:.3f} | {r['L20_absgapbp_median']:.1f} | "
      f"{r['L20_gapR_mean']:+.3f} | {r['L20_dR_mean']:+.3f} | {r['L20_dR_se']:.3f} | {r['L20_dR_sd']:.2f} | {big[t]:.1%} |")
a("")
a(f"- 실행별로 부호가 뒤집힙니다: 15m ΔR v3b {tw[('v3b','15m')]['L20_dR_mean']:+.3f}, v4 {tw[('v4','15m')]['L20_dR_mean']:+.3f}. **평균 지연 비용은 0과 구별되지 않습니다.**"
  " (4h +0.031R은 n 112, 묶음 11개뿐.) AI 지연을 5·10·40초로 바꿔도 평균은 같은 수준이었습니다(delay_summary.csv).")
a("- 그러나 **결정 하나의 흔들림은 큽니다:** 15m sd 0.57R(같은 신호의 R끼리 상관 0.90), 신호의 약 20%가 0.05R 넘게, 5%가 0.5R 넘게 바뀝니다 "
  "(손절·계단에 닿느냐가 갈림). 15m 거래 R의 sd가 1.30R이므로, 지연만으로 분산의 약 19%만큼의 잡음이 짝 차이에 들어갑니다.")
a("- 답 받은 순간 bookTicker로 들어가면(규칙 계좌와 같은 방식) AI 쪽 추가 지연은 LLM 지연(약 5~20초)과 커밋 대기뿐이라 가격 차가 더 작을 것입니다. "
  "1분봉만으로는 이 경우를 잴 수 없습니다(시간 제곱근으로 거칠게 보면 15m 평균 |차이| 약 0.05R).")
a("")
a("### 3-4. 필요한 짝 비교 설계 (AI가 엔진 탓 지연 비용을 떠안지 않게)")
a("1. **AI 체결 함수 = 규칙 계좌 체결 함수.** 답을 받은 순간 bookTicker(롱 ask/숏 bid) + 2bp, 다음 1분 step에서 처리. "
  "설계 5-3 7번 '다음 분 시가'를 쓰면 규칙 계좌(bookTicker)와 다른 가격 규칙이 섞입니다. 쓰더라도 쌍둥이도 같은 규칙으로.")
a("2. **보여 준 신호마다 쌍둥이 둘:** S(신호 시각: 규칙이 받은 ref·ref_time) / A(AI 체결 시각·가격; 건너뜀이면 답 받은 시각, 무응답이면 마감 시각). "
  "둘 다 AI와 **같은 크기 규칙·같은 R 청산·같은 1분봉(live_bars)·같은 구간표·같은 펀딩**으로, 고정 기준 잔고에서.")
a("3. **분해:** AI − S = (AI − A) [판단 효과] + (A − S) [지연 비용]. 건너뜀은 0 − A. 판정의 주 숫자는 판단 효과(AI − A), "
  "지연 비용은 따로 보고하고 실전 가능성 확인(합계 AI − S)에 씁니다. 어느 쪽을 판정에 쓸지 **D0 전에 사전 등록**.")
a("4. 동전(뒤집기, 같은 방향 무작위 시각)도 AI의 실제 지연 분포를 그대로 씁니다(설계 7장 ④ 7번).")
a("5. 마감(20초)을 넘긴 답은 체결하지 않고 '늦음'으로 기록, A 쌍둥이는 계산해 둡니다(무응답 분석용).")
a("6. 규칙 계좌 손익과 직접 빼지 않습니다(한 번에 하나라 다른 신호를 들고 있음; 보고서 15-8).")
a("")
a("## 4. 설계 문서가 코드 현실과 다른 곳")
for s in [
    "PLAN 1-2 6번·설계 v2 5-3 7번·7장 ⑤ '규칙 계좌와 같은 다음 1분봉 시가': 코드는 계산 직후 bookTicker ×(1±2bp), 1,430/1,430건. 신호 시각 쌍둥이는 ref_price로 계산해야 규칙과 같아집니다.",
    "PLAN 1-2 5번·2-3 '규칙 봇은 20초 안에 온 답만 읽고 절대 기다리지 않음': 러너에는 답을 받는 길이 없고, 유일한 훅(extras.post_boundary)은 동기 실행이라 그 안에서 기다리면 러너가 멈춥니다. 별도 프로세스가 맞습니다.",
    "마감: PLAN·종합안 20초 vs 설계 v2 6-6 '봉 마감부터 15m 3분 · 30m 5분 · 1h 10분 · 4h 30분'. 또 신호가 보이는 시각이 이미 마감 뒤 27~39초라 '20초'의 시작점(커밋? 신호 계산?)을 정해야 합니다.",
    "진입 봉: PLAN 1-2 'AI는 15m/30m만, 1h/4h는 참고' vs 설계 v2 14-2·D15 'AI는 15m/30m을 판단하지 않음(1h/4h)' vs 종합안 '설정 B: 15m/30m/1h + 20배 되는 4h'. 셋이 서로 다릅니다.",
    "크기: 설계 v2 4-3(확신별 위험 2~5%, 최저 3배) vs PLAN 4번(20~50배) vs 종합안(1% 고정). 코드: OwnerPolicy는 Settings가 20배 미만·증거금 20% 미만을 거부해 설계 4-3을 표현할 수 없고, RecommendedPolicy는 '가장 낮은' 레버리지(≤10배, 3 ATR)라 분석 권장(가장 높은 가능 레버리지, 1 ATR)과 반대입니다.",
    "보고서 7-2 '설계 v2는 이미 계단을 20배 모양의 R 단위로, 봉 마감 때만': 코드 ladder.py는 순 ROE(레버리지 곱) 기준이고 매 1분봉마다 올립니다. R 모드·봉 마감 모드·+1R 본전은 그림자에만 있습니다.",
    "설계 v2 13-4 '저장소에 실제 구간표 없음, 키 없는 AI 봇은 못 읽음': 규칙 봇은 시작마다 읽기 전용 키로 Binance leverageBracket을 받습니다(runs 기록 'Binance leverageBracket (live)'). 같은 서버에 붙이면 이미 있음; 별도 서버일 때만 문제입니다.",
    "설계 v2 1장·15-3 'AI 봇이 웹소켓으로 직접 받고 규칙 봇 DB는 하루 1번 복사본만, paper3.db는 AI 경로에서 열지 않음': 붙이는 방식에서는 신호를 몇 초 안에 받아야 하므로 paper3.db signal_log를 실시간 읽기 전용으로 읽거나 훅이 필요합니다. 초기화 거부와의 충돌을 풀어야 합니다.",
    "설계 v2 5-3 11번(depth20@500ms 스냅숏 + slip() 하나): 코드에는 원래 계좌 체결 때의 REST depth 기록뿐이고 엔진은 고정 2bp. AI만 새 체결 모델을 쓰면 AI − 규칙 비교가 깨집니다.",
    "설계 v2 15-3 '미결제약정·롱숏 5분마다': flow.db는 매시 :07 동기화라 최대 약 67분 늦습니다. 강제청산 기록은 10/06 경로 수정 전까지 조용했을 수 있습니다(ab1c387).",
    "PLAN 1-2 화면 '조건을 겨우/확실히 맞췄는지' vs 설계 v2 6-1 '맞음/안 맞음만'(연구 B 0/410). strength 값은 우리 36에만 있고 딥시크에는 없습니다.",
    "경제 일정: 파일은 4줄이 아니라 11줄(NFP·CPI·FOMC·PCE 4종, 10/02~12/23; 10월분이 4줄: 10/02 NFP, 10/14 CPI, 10/28 FOMC, 10/29 PCE). events.KINDS가 4종으로 고정돼 PPI·실업수당·ISM·GDP·FOMC 의사록 등은 코드 수정 없이 넣을 수 없습니다. 파일 주석대로 날짜는 공식 페이지로 아직 확인되지 않았습니다.",
    "PLAN 2-4 'AI 계좌는 11/04 판정에서 뺌'·2-5 'AI 계좌는 빼고 초기화': checkpoint.account_family는 모르는 kind를 'core' 묶음에 넣고, resetrun은 paper3.db를 통째로 옮깁니다. 같은 DB에 넣으면 둘 다 거꾸로 됩니다.",
    "하루의 뜻: 설계 v2 '09:00 KST(= UTC 하루)'와 RiskGuards(UTC)는 같지만, 재사용하려는 토론방 비용 계산은 KST 00:00 하루입니다.",
    "보유 중 깨움: PLAN 1-3(30분마다 + 손절 폭 절반 움직임 + 다른 봉 신호) vs 종합안·보고서 15-9(자기 봉 마감 + 1.0R + 반대 신호 + 발표) vs 설계 v2 6-2(1 ATR·70% 지점은 작은 모델, 펀딩 10분 전 등).",
    "파산선: 설계 v2 5-2·10-6은 1,000 USDT, 규칙 봇 설정은 bust_below 10 USDT.",
]:
    a(f"- {s}")
a("")
a("## 5. 이 점검이 알 수 없는 것")
a("- 서버의 실제 상태(flow.db·liq.db·market.db에 무엇이 언제부터 들어 있는지, record 서비스가 도는지)는 저장소에서 보이지 않습니다. 날짜는 커밋과 설치 문서 기준입니다.")
a("- 일 수는 거친 추정입니다. AI 호출은 한 번도 하지 않아 실제 지연·20초 안 응답 비율은 모릅니다(0차 시험에서 잼).")
a("- 지연 재생은 v3b 0.7일 + v4 1.5일, 조용히 떨어지는 장 하나입니다. 빠른 장에서는 가격 차와 흔들림이 더 클 것입니다.")
a("")
a("## 6. 파일")
a("- `gap/gap_audit.json`: 같은 표(행마다 필드: area, capability, status, where, build, effort, days, blocks_1017, risk) + 지연 숫자.")
a("- `gap/work/delay.py`(재생), `delay_summary.csv`, `delay_results.json`, `delay_twins.csv.gz`(신호별), `commit_timing.json`, `rows.py`·`make.py`(이 문서 생성).")
open(os.path.join(out, "gap_audit.md"), "w").write("\n".join(L) + "\n")
print(len(R), cnt, must_days, later_days, len(must), len(later))
