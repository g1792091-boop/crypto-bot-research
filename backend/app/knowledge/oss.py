"""오픈소스 연구팀이 조사한 깃허브 프로젝트 목록과, 이 앱에 옮긴 기법.

원칙: 다른 프로젝트의 코드를 복사하지 않는다(GPL 등 라이선스 충돌). 공개된 '아이디어·기법'만 이 앱 구조에 맞게 새로 구현한다.
'applied' 는 이 앱에서 그 기법이 들어간 곳, 'todo' 는 아직 옮기지 않은 것.
"""
from __future__ import annotations

PROJECTS = [
    {"repo": "freqtrade/freqtrade", "stars": "약 5.5만", "license": "GPL-3.0", "kind": "자동매매 봇",
     "what": "파이썬 코인 자동매매 봇 — 백테스트·하이퍼옵트(파라미터 탐색)·보호 장치·FreqAI(머신러닝)·텔레그램 제어",
     "applied": ["보호 장치(연속 손절·낙폭·쿨다운·성적 부진 시 새 진입 멈춤) → quant/protect.py · 실거래 동기화",
                 "거래 몬테카를로 → quant/risk.montecarlo · 1억 챌린지 검증", "파라미터 스윕 → quant/risk.sweep",
                 "머신러닝 신호(FreqAI 개념) → quant/ml.py 로지스틱·신경망·CNN + 70/30 관문"],
     "todo": ["ROI 표(시간이 지날수록 낮아지는 목표 수익)", "Edge 포지셔닝(전략별 기대값으로 비중)"]},
    {"repo": "jesse-ai/jesse", "stars": "약 8.6천", "license": "MIT", "kind": "백테스트·자동매매",
     "what": "다중 시간 프레임 라우트, 위험 기반 수량 계산(risk_to_qty), 몬테카를로, 최적화",
     "applied": ["손절 거리로 수량 계산(1R = 자본 %) → 1억 챌린지 검증의 베팅 크기", "다중 시간 프레임 정렬 → 터미널 지표 추세·타점팀"],
     "todo": ["유전 알고리즘 최적화"]},
    {"repo": "hummingbot/hummingbot", "stars": "약 2.0만", "license": "Apache-2.0", "kind": "마켓메이킹·차익",
     "what": "마켓메이킹, 거래소 간 차익, 무기한 선물 펀딩비 차익(현물 롱 + 선물 숏)",
     "applied": ["펀딩비 차익 점검(연 환산·양수 비율·수수료 본전 일수) → quant/carry.py · 그리드·펀딩 차익팀",
                 "거래소 간 펀딩 차이(바이낸스 vs 바이빗, v2_funding_rate_arb 개념) → quant/carry.py"],
     "todo": ["호가 스프레드 마켓메이킹 시뮬레이션"]},
    {"repo": "Drakkar-Software/OctoBot", "stars": "-", "license": "GPL-3.0", "kind": "그리드·DCA 봇",
     "what": "그리드·DCA·트레이딩뷰 신호 연동, 웹 UI",
     "applied": ["박스권 그리드 백테스트(앞 절반으로 박스, 뒤 절반으로 검증 · 박스 이탈 손절 · 청산 계산) → quant/grid.py"],
     "todo": ["DCA(분할 매수) 전략 백테스트"]},
    {"repo": "enarjord/passivbot", "stars": "약 2.1천", "license": "Unlicense", "kind": "선물 그리드",
     "what": "무기한 선물 그리드·마틴게일 계열 — 승률은 높지만 꼬리 위험(한 번에 큰 손실)이 큼",
     "applied": ["그리드 백테스트에 청산·박스 이탈 손절 계산, 1억 챌린지 검증의 꼬리 위험(급변 갭) 가정"],
     "todo": []},
    {"repo": "polakowo/vectorbt", "stars": "약 9.3천", "license": "Apache-2.0 + Commons Clause", "kind": "대량 백테스트",
     "what": "넘파이 벡터 연산으로 수천 개 파라미터 조합을 한 번에 백테스트",
     "applied": ["넘파이 기반 머신러닝·커스텀 수식 지표 계산 → quant/ml.py · quant/customind.py"],
     "todo": ["전 파라미터 격자 벡터 백테스트"]},
    {"repo": "mementum/backtrader", "stars": "-", "license": "GPL-3.0 (2024년 이후 관리 중단)", "kind": "백테스트 엔진",
     "what": "이벤트 기반 백테스트, 브로커·수수료·슬리피지 모델",
     "applied": ["봉 단위 시뮬레이터의 수수료·슬리피지·펀딩·청산 계산 → engine.Simulator"], "todo": []},
    {"repo": "nautechsystems/nautilus_trader", "stars": "약 3.0만", "license": "LGPL-3.0", "kind": "고성능 거래 플랫폼",
     "what": "백테스트와 실거래가 같은 코드로 도는 이벤트 엔진",
     "applied": ["데모 봇과 실거래가 같은 매매법 사양(JSON)을 쓰는 구조 → 파이프라인 · live.py"], "todo": []},
    {"repo": "ccxt/ccxt", "stars": "약 4.4만", "license": "MIT", "kind": "거래소 연결",
     "what": "100여 개 거래소 API 통합 라이브러리",
     "applied": ["바이낸스 → 바이빗 → OKX 공개 데이터 대체 경로 → data/market.py"], "todo": ["ccxt 로 거래소 추가"]},
    {"repo": "AI4Finance-Foundation/FinRL", "stars": "약 1.7만", "license": "MIT", "kind": "강화학습 트레이딩",
     "what": "강화학습(PPO·DQN 등) 거래 환경과 에이전트",
     "applied": [], "todo": ["강화학습 에이전트 — 과최적화 위험이 커서 70/30 관문과 데모를 통과해야만 쓰도록"]},
    {"repo": "TauricResearch/TradingAgents", "stars": "약 11만", "license": "Apache-2.0", "kind": "LLM 다중 에이전트",
     "what": "분석가(기본·심리·뉴스·기술) → 강세/약세 연구원 토론 → 트레이더 → 위험 관리팀(공격·중립·보수) → 펀드 매니저",
     "applied": ["담당 분석가 → 전략 총괄 → 반론 검토관 → 리스크 책임자 → CSO 정리 회의 순서 → office/engine.py",
                 "반론 검토관(약세 연구원 역할)과 리스크 승인", "팀 회고 '배운 것'을 다음 회의 지시문에 넣는 기억 → office notes"],
     "todo": ["공격·중립·보수 3인 위험 토론", "강세·약세 대칭 토론"]},
    {"repo": "virattt/ai-hedge-fund", "stars": "약 6.4만", "license": "MIT", "kind": "LLM 투자자 페르소나",
     "what": "유명 투자자 관점의 에이전트들이 각자 판단하고 위험 관리자가 비중을 정함",
     "applied": ["팀원마다 전공(관점)을 나눠 같은 자료를 다르게 해석 → 확장 조직 277명"], "todo": []},
    {"repo": "microsoft/qlib", "stars": "약 4.9만", "license": "MIT", "kind": "AI 퀀트 연구 플랫폼",
     "what": "특징·예측을 정보계수(IC·순위 IC)와 분위 수익으로 평가, 기간을 굴리며 재학습",
     "applied": ["머신러닝 실험에 순위 IC(예측 확률과 다음 수익의 순위 상관) 추가 → quant/ml.py"], "todo": ["분위별 수익 표"]},
    {"repo": "NoFxAiOS/nofx", "stars": "약 1.3만", "license": "AGPL-3.0", "kind": "LLM 무기한 선물 봇",
     "what": "LLM 이 판단해도 코드가 레버리지 한도·손절·재진입 쿨다운·연속 실패 시 안전 모드로 강제",
     "applied": ["AI 는 주문하지 않고 코드 한도(레버리지 20배·하루 손실 한도·사람 승인)가 우선 → live.py · 보호 장치"], "todo": []},
    {"repo": "López de Prado 『Advances in Financial ML』 (mlfinlab 은 비공개 라이선스라 책의 방법만)", "stars": "-", "license": "책 · 방법론", "kind": "금융 머신러닝 방법론",
     "what": "삼중 장벽 라벨링, 메타 라벨링, 정화·엠바고 교차검증",
     "applied": [], "todo": ["머신러닝 라벨을 '다음 봉 방향' 대신 삼중 장벽(익절·손절·시간)으로", "정화 교차검증"]},
    {"repo": "online-ml/river", "stars": "약 6.1천", "license": "BSD-3", "kind": "온라인(실시간) 머신러닝",
     "what": "데이터가 하나씩 들어올 때마다 배우는 모델, ADWIN·PageHinkley 급변 감지, 톰슨 샘플링 밴딧",
     "applied": ["진입 봇 성적 급변 감지(Page-Hinkley) → 바로 다시 학습 → quant/scenlearn.page_hinkley"], "todo": ["메타 모델을 한 건씩 갱신하는 온라인 학습"]},
    {"repo": "skfolio/skfolio", "stars": "약 2.5천", "license": "BSD-3", "kind": "검증 방법",
     "what": "정화·엠바고 교차검증, 워크포워드",
     "applied": ["진입 봇 정책은 시간 순 앞 70% 로 고르고 뒤 30% 에서만 판정 + 검증 구간 앞뒤 절반 모두 우세해야 채택"], "todo": ["정화·엠바고 교차검증"]},
    {"repo": "BlackArbsCEO/Adv_Fin_ML_Exercises · jjakimoto/finance_ml", "stars": "약 2.0천", "license": "MIT", "kind": "금융 머신러닝 예제",
     "what": "삼중 장벽 라벨, CUSUM 이벤트 필터, 메타 라벨링",
     "applied": ["시나리오를 손절·1차 목표·시간(48봉) 중 먼저 닿는 것으로 채점(삼중 장벽) → quant/scenlearn.simulate",
                 "메타 라벨: 1차 모델(시나리오 엔진)이 방향을 내면 2차 로지스틱 회귀가 '할까 말까' → 검증 AUC 가 2σ 넘을 때만 사용"], "todo": ["CUSUM 이벤트 필터"]},
    {"repo": "david-cortes/contextualbandits", "stars": "약 840", "license": "BSD-2", "kind": "맥락 밴딧",
     "what": "장세·봉 같은 맥락에 따라 어떤 선택지(시나리오 종류)가 좋은지 탐색·활용",
     "applied": ["모든 시나리오를 그림자 채점해 선택 편향 없이 배움 (탐색 대신)"], "todo": ["할인 톰슨 샘플링으로 옛 장세를 서서히 잊기"]},
    {"repo": "ip200/venn-abers", "stars": "약 200", "license": "MIT", "kind": "확률 보정",
     "what": "예측 확률을 실제 빈도에 맞추고 불확실 구간까지",
     "applied": ["화면 확률 대신 '배운 실제 적중률'(베이즈 축소 · 표본 적으면 전체 평균 쪽) → 시나리오 패널에 표시"], "todo": ["구간이 넓으면 건너뛰기"]},
    {"repo": "asavinov/intelligent-trading-bot", "stars": "약 1.9천", "license": "MIT", "kind": "코인 신호 점수 봇",
     "what": "여러 점수를 합친 신호 · 시뮬레이션으로 문턱값 조정 · 주기적 재학습",
     "applied": ["진입 봇 정책 문턱값(최소 확률·손익비·메타 문턱)을 과거 재생 시뮬레이션으로 고르고 6시간마다 재선정"], "todo": []},
    {"repo": "Superalgos/Superalgos", "stars": "-", "license": "Apache-2.0", "kind": "시각적 전략 설계",
     "what": "노드 기반 전략 설계·데이터 마이닝·시각화",
     "applied": ["코드 없이 매매법을 JSON 으로 만들고 차트에 표시 → 전략·백테스트 화면"], "todo": []},
]


def summary() -> str:
    lines = []
    for p in PROJECTS:
        lines.append(f"- {p['repo']} (★{p.get('stars', '-')} · {p['license']}) · {p['kind']}: {p['what']}")
        for a in p["applied"]:
            lines.append(f"    적용: {a}")
        for t in p["todo"]:
            lines.append(f"    다음: {t}")
    return "\n".join(lines)
