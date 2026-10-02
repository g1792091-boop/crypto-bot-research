// GH Coin 조직: 코인 전문 AI 에이전트 회사. 팀마다 팀장 1명 + 팀원 10명.
// 파이프라인: 보조지표 분석 → 매매법 개발 → 백테스트 → 데모거래 → 실거래  (커스텀 지표 라인도 같은 단계를 따로 밟는다)
// 분석 팀: 추세 · 진입 타점 · 지지·저항 · 익절·손절 · 차트·캔들 패턴 · 뉴스·경제지표 · 코인 상황판 · 머신러닝·딥러닝 · 코인별 팀 · 실시간 종합 지표
// 오픈소스 분석으로 추가: 투자위원회 · 퀀트 리스크 · 데이터 플랫폼 · 전략 최적화 · 선물 자동매매봇 (tech.js 참고)
export const COINS = [
  {id: "btc", sym: "BTCUSDT", ko: "비트코인", up: "KRW-BTC", color: "#f7931a"},
  {id: "eth", sym: "ETHUSDT", ko: "이더리움", up: "KRW-ETH", color: "#627eea"},
  {id: "sol", sym: "SOLUSDT", ko: "솔라나", up: "KRW-SOL", color: "#14b8a6"},
  {id: "xrp", sym: "XRPUSDT", ko: "리플", up: "KRW-XRP", color: "#7a8699"},
  {id: "doge", sym: "DOGEUSDT", ko: "도지코인", up: "KRW-DOGE", color: "#c2a633"},
  {id: "bnb", sym: "BNBUSDT", ko: "바이낸스코인", up: "", color: "#f0b90b"}
];
export const coinById = id => COINS.find(c => c.id === id);

// [팀 id, 이름, 설명, 색, 팀장 id, 팀장 직함, 팀원 직함 10개, 스킬, 팀장·고참의 고정 id(기존 엔진이 쓰는 이름)]
const T = [
  ["hq", "CEO실", "CEO · 비서실 · CTO · QA · 데이터 엔지니어 — 전사 회의와 시간별 발표, 앱 오류 고치기", "#7c6cf0", "lead", "CEO",
    ["비서실장", "CTO", "QA 엔지니어", "데이터 엔지니어"], [], {1: "aide", 2: "dev", 3: "qae", 4: "eng"}],
  ["ind", "보조지표 분석팀", "29종 기본 지표 + 차트 지표 136종을 매 시간 계산하고 해석", "#2f8fd8", "ind_lead", "보조지표 분석팀장",
    ["RSI·스토캐스틱 담당", "MACD 담당", "볼린저·켈트너 담당", "이동평균 담당", "ADX·DMI 담당", "거래량·OBV 담당", "일목균형표 담당", "VWAP 담당", "CCI·MFI 담당", "신규 지표 리서처"], ["crypto_futures", "backtest"], {}],
  ["dev", "매매법 개발팀", "모든 보조지표를 조합해 매매법(전략 JSON)을 만든다", "#2e9e6b", "qa", "매매법 개발팀장",
    ["추세추종 개발자", "역추세 개발자", "변동성 돌파 개발자", "평균회귀 개발자", "스캘핑 개발자", "스윙 개발자", "멀티 타임프레임 개발자", "필터·조건 설계자", "포지션 사이징 설계자", "전략 문서 담당"], ["backtest", "crypto_futures"], {1: "qb"}],
  ["bt", "백테스트팀", "만들어진 매매법을 가장 오래된 과거부터 백테스트·과최적화 검증", "#16a39a", "val", "백테스트팀장 · 검증관",
    ["워크포워드 검증관", "시나리오 분석가", "레버리지 스트레스 테스터", "수수료·슬리피지 담당", "데이터 품질 담당", "통계 검정 담당", "낙폭 분석가", "장세별 분석가", "결과 리포터", "검증 자동화 엔지니어"], ["backtest"], {}],
  ["demo", "데모거래팀", "백테스트 통과 매매법을 실제 시세로 데모(모의) 운용", "#f57c00", "trader", "데모거래팀장",
    ["데모 트레이더 A", "데모 트레이더 B", "체결 시뮬레이션 담당", "포지션 모니터", "손익 회계 담당", "성과 분석가", "승격 심사 준비", "시장 상황 기록", "데모 리스크 담당", "일일 보고 담당"], ["crypto_futures", "backtest"], {}],
  ["live", "실거래팀", "데모 관문을 통과한 매매법만, 안전 한도·대표 승인 안에서 실거래", "#d0465a", "live_lead", "실거래팀장",
    ["실거래 심사역(반론)", "주문 실행 담당", "API·계정 보안 담당", "한도 관리 담당", "체결 품질 분석가", "실거래 손익 회계", "긴급 정지 담당", "거래소 공지 확인", "세금·기록 담당", "운영 보고 담당"], ["crypto_futures"], {1: "devil"}],
  ["trend", "추세 분석팀", "15분·1시간·4시간·일봉 다중 시간대 추세 판정", "#1e88e5", "trend_lead", "추세 분석팀장",
    ["단기 추세 담당", "중기 추세 담당", "장기 추세 담당", "추세 강도(ADX) 담당", "이평 배열 담당", "슈퍼트렌드 담당", "추세 전환 감시", "추세선 작도", "시장 국면 분류", "추세 리포터"], ["crypto_futures"], {}],
  ["entry", "진입 타점팀", "지금 들어갈 자리인지: 진입가·조건·대기 구간", "#8e24aa", "strat", "진입 타점팀장 · 전략가",
    ["돌파 타점 담당", "눌림목 타점 담당", "다이버전스 타점 담당", "호가·체결 타점 담당", "펀딩·청산 타점 담당", "분할 진입 설계", "리스크 대비 보상 계산", "타점 백테스트 담당", "알림 조건 설계", "타점 리포터"], ["crypto_futures"], {}],
  ["sr", "지지·저항팀", "피봇·스윙 고저·매물대·라운드 넘버·호가 벽으로 지지·저항", "#6d4c41", "sr_lead", "지지·저항팀장",
    ["피봇 담당", "스윙 고저 담당", "매물대(볼륨 프로파일) 담당", "피보나치 담당", "라운드 넘버 담당", "호가 벽 담당", "전일·전주 고저 담당", "추세선 담당", "돌파·이탈 감시", "레벨 리포터"], ["crypto_futures"], {}],
  ["tpsl", "익절·손절 관리팀", "열린 포지션의 손절·익절·추적손절 관리, 리스크 책임", "#c62828", "risk", "익절·손절 관리팀장 · 리스크 책임자",
    ["ATR 손절 담당", "추적 손절 담당", "분할 익절 담당", "본전 이동 담당", "청산가 관리", "레버리지 조정 담당", "포지션 크기 담당", "최대 손실 한도 감시", "변동성 경보 담당", "리스크 리포터"], ["crypto_futures"], {}],
  ["news", "뉴스·경제지표팀", "코인 뉴스·기사·규제·경제지표·일정을 찾아 시장 영향 해설", "#00897b", "macro", "뉴스·경제지표팀장",
    ["경제지표 예측 담당", "SNS 여론 분석가", "리서처", "규제·정책 담당", "거래소 공지 담당", "해킹·보안 사고 담당", "ETF·기관 자금 담당", "미국 증시 연동 담당", "금리·달러 담당", "뉴스 리포터"], ["news", "macro"], {1: "econfc", 2: "sns", 3: "research"}],
  ["situ", "코인 상황판팀", "모든 코인의 가격·변동·펀딩·미결제약정·흐름 점수를 한 판으로", "#5e35b1", "situ_lead", "코인 상황판팀장",
    ["시세 담당", "펀딩비 담당", "미결제약정 담당", "롱숏 비율 담당", "고래 체결 담당", "호가 불균형 담당", "김치 프리미엄 담당", "도미넌스 담당", "상관관계 담당", "상황판 리포터"], ["crypto_futures", "crypto_spot"], {}],
  ["pattern", "차트·캔들 패턴팀", "캔들 패턴·차트 패턴·시장 구조(BOS·CHoCH)·FVG", "#ef6c00", "pat_lead", "차트·캔들 패턴팀장",
    ["캔들 패턴 담당", "헤드앤숄더 담당", "삼각수렴·쐐기 담당", "쌍바닥·쌍봉 담당", "깃발·페넌트 담당", "시장 구조 담당", "FVG·오더블록 담당", "유동성 스윕 담당", "TD 시퀀셜 담당", "패턴 리포터"], ["crypto_futures"], {}],
  ["cdev", "커스텀 지표 개발팀", "기존 지표를 넘어 수식으로 새 지표를 발명", "#43a047", "cind", "커스텀 지표 개발팀장",
    ["모멘텀 지표 설계", "변동성 지표 설계", "거래량 지표 설계", "합성 점수 설계", "레짐 판별 설계", "펀딩·미결제 지표 설계", "머신러닝 확률 지표 설계", "노이즈 필터 설계", "지표 검증 담당", "지표 문서 담당"], ["backtest"], {}],
  ["cbt", "커스텀 백테스트팀", "커스텀 지표로 만든 매매법만 따로 백테스트·검증", "#00acc1", "cbt_lead", "커스텀 백테스트팀장",
    ["워크포워드 검증관", "시나리오 분석가", "레버리지 스트레스 테스터", "수수료·슬리피지 담당", "통계 검정 담당", "낙폭 분석가", "장세별 분석가", "지표 안정성 검사", "결과 리포터", "검증 자동화 엔지니어"], ["backtest"], {}],
  ["cdemo", "커스텀 데모거래팀", "커스텀 지표 백테스트 승인 매매법을 데모 운용", "#fb8c00", "cdemo_lead", "커스텀 데모거래팀장",
    ["데모 트레이더 A", "데모 트레이더 B", "체결 시뮬레이션 담당", "포지션 모니터", "손익 회계 담당", "성과 분석가", "승격 심사 준비", "지표 신호 기록", "데모 리스크 담당", "일일 보고 담당"], ["crypto_futures"], {}],
  ["clive", "커스텀 실거래팀", "커스텀 데모 관문 통과분만 안전 한도·대표 승인 안에서 실거래", "#e53935", "clive_lead", "커스텀 실거래팀장",
    ["실거래 심사역", "주문 실행 담당", "API·계정 보안 담당", "한도 관리 담당", "체결 품질 분석가", "실거래 손익 회계", "긴급 정지 담당", "거래소 공지 확인", "세금·기록 담당", "운영 보고 담당"], ["crypto_futures"], {}],
  ["ml", "머신러닝·딥러닝팀", "로지스틱 회귀·신경망·부스팅으로 방향 예측, 우위가 있으면 지표화", "#3949ab", "ml", "머신러닝·딥러닝팀장",
    ["특징 공학 담당", "신경망 담당", "부스팅 담당", "로지스틱 회귀 담당", "워크포워드 검증", "과적합 감시", "데이터 파이프라인", "모델 해석 담당", "확률 보정 담당", "ML 리포터"], ["backtest"], {}],
  ...COINS.map(c => [c.id, `${c.ko}팀`, `${c.ko}(${c.sym.replace("USDT", "")}) 전담: 현물·선물·온체인·뉴스·타점`, c.color, c.id === "btc" ? "coin_fut" : c.id === "eth" ? "coin_spot" : c.id + "_lead", `${c.ko}팀장`,
    ["현물 애널리스트", "선물·펀딩 애널리스트", "온체인·고래 애널리스트", "뉴스 애널리스트", "추세 애널리스트", "타점 애널리스트", "지지·저항 애널리스트", "패턴 애널리스트", "리스크 매니저", "데이터 담당"], ["crypto_futures", "crypto_spot"], {}]),
  ["combo", "실시간 종합 지표 타점팀", "차트 터미널의 모든 보조지표(136종)를 5분·15분·1시간·4시간에 실시간으로 계산·조합해 추세를 보고 타점(진입·손절·익절)을 잡는다", "#00b8d4", "combo_lead", "실시간 종합 지표 타점팀장",
    ["추세 지표 표 담당", "오실레이터 표 담당", "거래량·자금 흐름 담당", "신호·패턴 지표 담당", "스마트머니(SMC) 담당", "레벨·프로파일 담당", "장세(추세장·횡보장) 판별", "다중 시간대 조합 담당", "타점·손익비 계산", "타점 기록장(적중률) 담당"], ["crypto_futures", "backtest"], {}],
  // ↓ 오픈소스 분석으로 새로 만든 부서 (TradingAgents · gs-quant · nautilus · vnpy · jdmn · ccxt · OpenBB · Legend · obevo · reladomo · freqtrade · backtrader)
  ["ic", "투자위원회", "애널리스트 4명 보고 → 강세·약세 토론 → 리서치 매니저 → 트레이더 제안 → 공격·중립·보수 리스크 토론 → 위원장 최종 결정(매수·매도·관망), 결과를 채점해 교훈으로 기억 (TradingAgents 방식)", "#6a1b9a", "ic_lead", "투자위원장 · 포트폴리오 매니저",
    ["시장·기술 애널리스트", "여론·소셜 애널리스트", "뉴스·펀더멘털 애널리스트", "강세 리서처", "약세 리서처", "리서치 매니저", "트레이더", "공격형 리스크 토론자", "중립형 리스크 토론자", "보수형 리스크 토론자"], ["crypto_futures", "news"], {}],
  ["qrisk", "퀀트 리스크팀", "변동성·VaR·CVaR·상관·베타·낙폭(gs-quant 방식), 주문 전 점검(nautilus·vnpy 리스크 엔진), 결정표(DMN)로 리스크 판정", "#455a64", "qrisk_lead", "퀀트 리스크팀장",
    ["변동성 담당", "VaR·CVaR 담당", "상관·베타 담당", "낙폭 분석가", "스트레스 시나리오 담당", "주문 전 점검(리스크 엔진)", "결정표(DMN) 관리", "포지션 한도 담당", "유동성·체결 리스크 담당", "리스크 리포터"], ["crypto_futures", "backtest"], {}],
  ["data", "데이터 플랫폼팀", "여러 거래소 시세·펀딩 비교(ccxt 방식), 경제 데이터(OpenBB 방식), 데이터 모델·제약 검사와 전략 버전 관리(Legend), 저장소 이전(obevo), 이중 시간 감사 기록(reladomo)", "#00796b", "data_lead", "데이터 플랫폼팀장",
    ["멀티 거래소 연결 담당", "시세 정합성 검사", "경제 데이터 수집", "데이터 모델·제약 검사", "전략 버전 관리(SDLC)", "저장소 이전(마이그레이션)", "감사 기록(이중 시간)", "데이터 품질 모니터", "백업·복구 담당", "데이터 리포터"], ["crypto_spot", "macro"], {}],
  ["opt", "전략 최적화팀", "하이퍼옵트(손실함수)·ROI 표·추적손절·보호장치(freqtrade), 성과 분석기 SQN·VWR·칼마(backtrader), 체결 현실성(nautilus)으로 통과 전략을 다듬는다", "#ad1457", "opt_lead", "전략 최적화팀장",
    ["하이퍼옵트 설계", "손실함수 담당", "ROI 표 설계", "추적손절 튜닝", "보호장치(프로텍션) 설계", "체결 모델(현실성) 담당", "성과 분석기(SQN·VWR)", "포지션 사이징", "과최적화 감시", "최적화 리포터"], ["backtest"], {}],
  ["bot", "선물 자동매매봇팀", "오픈소스 트레이딩 봇(passivbot·jesse·OctoBot·freqtrade·Binance 선물봇)의 봇 전략을 우리 전략으로 만들어 백테스트→데모→실거래 파이프라인에 올리고, 봇 조종판에서 켜고 끈다. 주문은 코드가 한도·사용자 승인 안에서만 낸다", "#00bfa5", "bot_lead", "선물 자동매매봇팀장",
    ["추세추종 봇 담당", "돌파 봇 담당", "평균회귀 봇 담당", "슈퍼트렌드 플립 봇 담당", "펀딩 캐리 봇 담당", "그리드 봇(연구) 담당", "DCA(한도형) 봇 담당", "봇 리스크·한도 담당", "봇 성과 모니터", "봇 조종판 담당"], ["crypto_futures", "backtest"], {}],
  ["selfai", "자체 AI 데스크", "GH Coin 자체 AI(외부 키 없이 앱 안에서 도는 앙상블: 기술 평점·멀티 시간대·ML 확률·알파 팩터를 합쳐 방향과 확신도를 낸다). 코인 순위를 내고, 선물 자동매매봇의 진입 확신도로 쓴다. 자체 AI 는 판단만 하고 주문은 live.js 만 낸다", "#0ea5e9", "selfai_lead", "자체 AI 데스크장",
    ["앙상블 설계", "기술 평점 담당", "멀티 시간대 담당", "ML 확률 담당", "알파 팩터 담당", "확신도 보정 담당", "장세 판별 담당", "봇 진입 확신도 담당", "성과 피드백 담당", "자체 AI 리포터"], ["crypto_futures", "backtest"], {}]
];

export const TEAMS = T.map(([id, name, desc, color]) => ({id, name, desc, color}));
export const TEAM_COLOR = Object.fromEntries(T.map(([id, , , color]) => [id, color]));
export const TEAM_LEAD = Object.fromEntries(T.map(([id, , , , lead]) => [id, lead]));

// 한국어 이름 (겹치지 않게)
const SUR = "김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허유남심노하곽성차주우구민진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경";
const GIV = ["민준", "서준", "도윤", "예준", "시우", "하준", "주원", "지호", "지후", "준우", "준서", "건우", "현우", "도현", "우진", "선우", "서진", "연우", "유준", "정우", "승우", "승현", "시윤", "지훈", "민재",
  "서연", "서윤", "지우", "서현", "민서", "하은", "하윤", "윤서", "지유", "지민", "채원", "수아", "지아", "다은", "은서", "예은", "수빈", "소율", "예린", "지원", "하린", "가은", "유나", "아린", "다인",
  "태윤", "은우", "이안", "로운", "하람", "도하", "윤슬", "새봄", "누리", "한결", "다온", "라온", "가온", "보람", "슬기", "나래", "바다", "하늘", "별하", "솔비"];
const FIXED_NAME = {lead: "한결", aide: "하루", dev: "코디", qae: "보라", eng: "태민", qa: "준호", qb: "세라", val: "다온", trader: "현우", strat: "민재", devil: "수아", risk: "태오",
  macro: "노바", econfc: "지우", sns: "유나", research: "리아", coin_fut: "레오", coin_spot: "코코", ml: "이안", cind: "보미"};
const HAIR = ["#2b2b3a", "#3a2a1a", "#6d4c41", "#1b1b1b", "#8d6e63", "#d4a017", "#5d4037", "#212121", "#795548", "#c0a060", "#4e342e", "#a1887f"];
let ni = 0;
const used = new Set(Object.values(FIXED_NAME));
// 성과 이름을 서로 다른 보폭으로 섞어 고른다 (결정적: 매번 같은 사람이 같은 이름)
const nextName = () => { for (;;){ const k = ni++, full = SUR[(k * 7 + 3) % SUR.length] + GIV[(k * 11 + 5) % GIV.length]; if (!used.has(full)){ used.add(full); return full; } } };

const DUTY = {
  ind: "맡은 보조지표를 실제 차트로 계산(indicator_all)해 지금 값이 무엇을 뜻하는지 쉬운 말로 해석한다.",
  dev: "보조지표 29종과 차트 지표(tv_*)를 조합해 매매법 JSON을 만든다(조건·손절·익절·레버리지). 근거를 짧게 설명한다.",
  bt: "매매법을 가장 오래된 과거부터 백테스트(history_backtest)하고 앞 70%/뒤 30% 검증 결과로 과최적화를 따진다. 코드 판정을 뒤집지 않는다.",
  demo: "백테스트 통과 매매법의 데모(모의) 운용 장부(paper_status)를 보고 손익·승률·낙폭을 보고한다. 실제 주문은 하지 않는다.",
  live: "데모 관문(14일·20거래·손익비 1.2·수익+·낙폭 25% 미만)을 통과한 매매법만 실거래 후보로 심사한다. 주문은 코드가 안전 한도와 대표 승인 안에서만 낸다.",
  trend: "여러 시간대(15분·1시간·4시간·일봉) 추세를 지표로 판정하고 서로 맞는지 해설한다.",
  entry: "지금이 진입 자리인지, 기다릴 가격대와 조건, 손익비를 제시한다(확인된 숫자만).",
  ic: "투자위원회 절차(애널리스트 보고 → 강세·약세 토론 → 리서치 매니저 → 트레이더 → 리스크 3인 토론 → 위원장 결정)에서 맡은 역할만 한다. 숫자는 코드가 준 자료만 쓰고, 지난 결정의 교훈을 참고한다.",
  qrisk: "변동성·VaR·CVaR·상관·베타·낙폭을 코드로 계산한 표를 보고 위험이 어디에 몰렸는지, 주문 전 점검·결정표 판정이 무엇인지 설명한다. 판정을 뒤집지 않는다.",
  data: "여러 거래소 시세·펀딩·김치 프리미엄 차이와 데이터 품질(빈 봉·이상값·지연), 전략 버전·감사 기록을 점검하고 문제를 보고한다.",
  opt: "통과 전략의 파라미터를 하이퍼옵트로 다듬되, 학습 구간 최적값이 검증 구간에서도 통하는지(과최적화)를 가장 먼저 본다. 코드 판정을 뒤집지 않는다.",
  bot: "유명 트레이딩 봇의 전략(추세추종·돌파·평균회귀·슈퍼트렌드·펀딩 캐리·그리드·DCA)을 우리 전략 JSON으로 만들어 백테스트·데모로 검증하고, 통과분만 봇 조종판에 올린다. 실거래는 사용자가 직접 켜고 연결해야 하며 주문은 코드가 안전 한도 안에서만 낸다. 그리드·DCA의 무한 물타기 위험을 늘 경고한다.",
  combo: "차트 터미널의 모든 보조지표를 실시간으로 계산한 표(상승·하락·중립)와 시간대별 점수를 보고, 큰 추세와 작은 봉 타이밍이 맞는 자리에서만 타점(진입·손절·익절)을 잡는다. 숫자는 코드가 낸 것만 쓴다.",
  sr: "지지·저항 가격대를 근거(피봇·스윙 고저·매물대·호가 벽)와 함께 제시한다.",
  tpsl: "열린 포지션과 전략의 손절·익절·추적손절을 점검하고 위험을 줄이는 조정을 제안한다.",
  news: "코인 뉴스·기사·규제·경제지표 일정을 찾아(web_search, market_news) 시장 영향으로 해설한다. 출처를 단다.",
  situ: "모든 코인의 가격·변동·펀딩·미결제약정·흐름을 한눈에 정리하고 이상 신호를 짚는다.",
  pattern: "캔들·차트 패턴과 시장 구조를 찾아 신뢰도와 함께 설명한다(패턴은 확률일 뿐임을 밝힌다).",
  cdev: "기존 지표로 안 보이는 것을 수식 지표({type:'custom', expr})로 발명하고 이유를 설명한다.",
  cbt: "커스텀 지표 매매법을 따로 백테스트·검증한다. 코드 판정을 뒤집지 않는다.",
  cdemo: "커스텀 지표 매매법의 데모 운용 성과를 보고한다.",
  clive: "커스텀 지표 매매법 중 데모 관문 통과분만 실거래 후보로 심사한다.",
  ml: "머신러닝·딥러닝 모델로 다음 봉 방향을 예측하고, 기준선보다 나은지 냉정하게 판단한다.",
  selfai: "GH Coin 자체 AI(앙상블)가 낸 방향·확신도 표를 보고, 어떤 신호(기술 평점·멀티 시간대·ML·알파)가 합의했는지, 확신도가 높은 코인은 무엇인지 해설한다. 확신도는 참고일 뿐이며 주문은 사용자 승인·한도 안에서만 나간다는 점을 늘 밝힌다.",
  coin: "맡은 코인의 현물·선물·펀딩·고래·뉴스·차트를 실제 도구로 확인해 해설한다.",
  hq: "전사 업무를 조율한다."
};
export const AGENTS = [];
for (const [team, , , , leadId, leadTitle, titles, skills, fixed] of T){
  const coin = coinById(team), kind = coin ? "coin" : team;
  const mk = (id, title, k) => {
    const name = FIXED_NAME[id] || nextName();
    const h = [...id].reduce((s, c) => s + c.charCodeAt(0), 0);
    const a = {id, name, team, title, role: /엔지니어|CTO|개발자/.test(title) && team === "hq" ? "code" : "general", skills: coin ? ["crypto_futures", "crypto_spot"] : skills,
      look: [HAIR[h % HAIR.length], TEAM_COLOR[team]], duty: (coin ? `${coin.ko} 담당 · ` : "") + (DUTY[kind] || DUTY.hq), coin: coin?.id || "", lead: k === 0};
    if (id === "eng") a.computer = true;
    if (id === "lead") a.duty = "대표(사용자)의 질문을 받아 팀원 발언을 종합해 최종 답을 준다. 결론 → 근거 → 위험 → 다음 할 일 순서로 짧게.";
    AGENTS.push(a);
  };
  mk(leadId, leadTitle, 0);
  titles.forEach((title, i) => mk(fixed[i + 1] || `${team}_${i + 1}`, title, i + 1));
}
export const agentById = id => AGENTS.find(a => a.id === id);
export const teamById = id => TEAMS.find(t => t.id === id);

// 질문 → 담당자 (코드가 정함)
export const SKILL_AGENT = {crypto_spot: "coin_spot", crypto_futures: "coin_fut", macro: "macro", news: "macro", backtest: "val", research: "research", coding: "dev"};
export const MARKET = new Set(["combo_lead", "bot_lead", "coin_spot", "coin_fut", "strat", "qa", "qb", "trader", "trend_lead", "sr_lead", "risk", ...COINS.map(c => TEAM_LEAD[c.id])]);
// 질문 단어 → 팀장 (planMeeting 에서 먼저 부른다)
export const TOPIC_LEAD = [
  [/투자위원회|강세.*약세|불.*베어|bull|bear|최종 결정/i, "ic_lead"], [/var|cvar|변동성|상관|베타|리스크 엔진|결정표|dmn/i, "qrisk_lead"], [/거래소 (비교|차이)|김치 ?프리미엄|데이터 (품질|모델)|감사 기록|버전 관리|ccxt|openbb/i, "data_lead"], [/하이퍼옵트|최적화|hyperopt|roi 표|보호장치|sqn|vwr/i, "opt_lead"], [/자동매매\s*봇|선물\s*봇|트레이딩\s*봇|그리드\s*봇|dca\s*봇|봇\s*(만들|돌려|켜|전략)|passivbot|jesse|octobot/i, "bot_lead"],
  [/종합 지표|모든 (보조)?지표|전체 지표|실시간 (타점|추세)|지표 (조합|종합)/, "combo_lead"], [/보조지표|지표 (해석|분석)|rsi|macd|볼린저|이평/i, "ind_lead"], [/매매법|전략 (개발|만들)/, "qa"], [/백테스트|검증/, "val"], [/데모|모의/, "trader"], [/실거래|실전/, "live_lead"],
  [/추세|방향/, "trend_lead"], [/타점|진입|들어가/, "strat"], [/지지|저항|매물대/, "sr_lead"], [/손절|익절|청산가|리스크/, "risk"], [/뉴스|기사|경제|지표 발표|cpi|fomc|금리/i, "macro"],
  [/상황판|전체 코인|시장 전체/, "situ_lead"], [/패턴|캔들|쌍바닥|헤드앤숄더/, "pat_lead"], [/커스텀/, "cind"], [/머신러닝|딥러닝|ai 예측/i, "ml"],
  ...COINS.map(c => [new RegExp(`${c.ko}|${c.sym.replace("USDT", "")}\\b`, "i"), TEAM_LEAD[c.id]])
];

// 자동 회의 안건
export const AGENDA = [
  {id: "btc", room: "btc", title: "비트코인-브리핑", topic: "지금 비트코인 현물·선물·펀딩·고래 흐름과 추세를 점검하고 오늘의 대응을 정해 주세요.", agents: ["coin_fut", "btc_2", "btc_5"]},
  {id: "trend", room: "trend", title: "다중-시간대-추세", topic: "주요 코인의 15분·1시간·4시간·일봉 추세가 서로 맞는지 점검해 주세요.", agents: ["trend_lead", "trend_1", "trend_3"]},
  {id: "combo", room: "combo", title: "실시간-종합지표-타점", topic: "실시간 종합 지표 타점판(모든 보조지표의 시간대별 점수·타점)을 보고 지금 들어갈 코인과 자리, 기다릴 코인을 정해 주세요.", agents: ["combo_lead", "combo_8", "combo_9"]},
  {id: "ic", room: "ic", title: "투자위원회", topic: "강세·약세 리서처와 리스크 토론자가 지금 비트코인을 살지·팔지·관망할지 토론하고 위원장이 결정해 주세요.", agents: ["ic_4", "ic_5", "ic_lead"]},
  {id: "bot", room: "bot", title: "자동매매봇-점검", topic: "지금 데모·실거래 중인 선물 자동매매봇들의 성과와 한도·위험을 점검하고, 새로 올릴 봇 전략을 정해 주세요.", agents: ["bot_lead", "bot_8", "risk"]},
  {id: "entry", room: "entry", title: "진입-타점-회의", topic: "지금 진입할 만한 코인과 자리(가격·조건·손익비)를 정해 주세요.", agents: ["strat", "sr_lead", "risk"]},
  {id: "news", room: "news", title: "뉴스·경제지표", topic: "오늘 코인 뉴스와 경제지표 일정을 찾아 시장 영향을 해설해 주세요.", agents: ["macro", "research", "econfc"]},
  {id: "pattern", room: "pattern", title: "차트·캔들-패턴", topic: "주요 코인 차트에서 보이는 캔들·차트 패턴과 시장 구조를 점검해 주세요.", agents: ["pat_lead", "pattern_1", "pattern_6"]},
  {id: "eth", room: "eth", title: "이더리움-브리핑", topic: "이더리움 흐름과 비트코인 대비 강약, 오늘 대응을 이야기해 주세요.", agents: ["coin_spot", "eth_2", "eth_6"]},
  {id: "alt", room: "situ", title: "알트코인-상황판", topic: "솔라나·리플·도지·BNB 상황을 한 판으로 점검하고 이상 신호를 짚어 주세요.", agents: ["situ_lead", "sol_lead", "doge_lead"]}
];
// 급변동 감시 (코드만)
export const WATCH = COINS.slice(0, 3).map(c => ({q: c.sym, ex: "binancef", label: c.ko, room: c.id, agents: [TEAM_LEAD[c.id], "risk"], th: c.id === "btc" ? 4 : 6}));

// 직원이 자리에서 보는 것 (코드만 씀, AI 호출 없음): 코인팀은 자기 코인, 나머지는 팀 성격대로
const W = {};
for (const a of AGENTS){
  const c = coinById(a.coin) || COINS[[...a.id].reduce((s, ch) => s + ch.charCodeAt(0), 0) % 3];
  const q = {q: c.sym, ex: "binancef"};
  W[a.id] = a.team === "news" ? [{news: "crypto"}, {news: "macro"}, {news: "futures"}] :
    a.team === "situ" ? [q, {flow: "flow", sym: c.sym}, {flow: "whale", sym: c.sym}] :
    a.team === "sr" || a.team === "entry" || a.team === "combo" ? [q, {flow: "book", sym: c.sym}] :
    a.team === "hq" ? [q, {news: "crypto"}] :
    [q, {flow: "whale", sym: c.sym}, {flow: "book", sym: c.sym}, {news: "crypto"}];
}
export const WATCH_OF = W;
// 수다 상대: 같은 팀 동료 2명 + 같은 코인 팀장/관련 팀장
const LINK = {ind: ["qa", "trend_lead"], dev: ["val", "ind_lead"], bt: ["qa", "trader"], demo: ["val", "live_lead"], live: ["trader", "risk"], trend: ["strat", "ind_lead"], combo: ["trend_lead", "strat"], ic: ["combo_lead", "risk"], qrisk: ["risk", "live_lead"], data: ["eng", "situ_lead"], opt: ["val", "qa"], bot: ["live_lead", "opt_lead"], entry: ["sr_lead", "risk"],
  sr: ["strat", "pat_lead"], tpsl: ["trader", "strat"], news: ["situ_lead", "coin_fut"], situ: ["macro", "coin_fut"], pattern: ["sr_lead", "trend_lead"], cdev: ["cbt_lead", "ml"], cbt: ["cind", "cdemo_lead"],
  cdemo: ["cbt_lead", "clive_lead"], clive: ["cdemo_lead", "risk"], ml: ["cind", "val"], hq: ["dev", "aide"]};
export const RELATED = Object.fromEntries(AGENTS.map(a => {
  const mates = AGENTS.filter(x => x.team === a.team && x.id !== a.id).map(x => x.id);
  const pick = mates.length ? [mates[(a.id.length) % mates.length], mates[(a.id.length + 3) % mates.length]] : [];
  return [a.id, [...new Set([...pick, ...(LINK[a.team] || (a.coin ? ["situ_lead", "strat"] : []))])].filter(id => id !== a.id)];
}));
export const CLAUDE_TIER = {strat: "opus", combo_lead: "opus", ic_lead: "opus", qrisk_lead: "opus", opt_lead: "opus", bot_lead: "opus", risk: "opus", val: "opus", qa: "opus", cind: "opus", live_lead: "opus", clive_lead: "opus", lead: "sonnet", devil: "sonnet", aide: "haiku", dev: "sonnet", eng: "sonnet"};
export const IDLE_T = {hq: ["🗂 팀별 보고 모으는 중", "📝 발표 자료 정리 중"], ind: ["📊 지표 다시 계산하는 중"], dev: ["🧪 전략 조건 다듬는 중"], bt: ["⏳ 백테스트 돌리는 중"], demo: ["🧾 데모 장부 맞추는 중"],
  live: ["🔐 실거래 한도 점검 중"], trend: ["📈 다중 시간대 보는 중"], entry: ["🎯 타점 계산 중"], combo: ["⚡ 136개 지표 실시간 계산 중", "🎯 타점 기록장 채점 중"], ic: ["🏛 위원회 안건 준비 중", "📚 지난 결정 교훈 정리 중"], qrisk: ["📐 VaR 계산 중", "🧮 상관행렬 갱신 중"], data: ["🔌 거래소 시세 맞춰 보는 중", "🗄 감사 기록 정리 중"], opt: ["🎛 하이퍼옵트 돌리는 중", "📈 SQN 계산 중"], bot: ["🤖 봇 전략 백테스트 중", "🎚 봇 한도 점검 중", "📟 봇 조종판 보는 중"], sr: ["📏 지지·저항 긋는 중"], tpsl: ["🛑 손절선 점검 중"], news: ["📰 기사 읽는 중"],
  situ: ["🖥 상황판 갱신 중"], pattern: ["🕯 캔들 패턴 찾는 중"], cdev: ["🧮 수식 지표 짜는 중"], cbt: ["⏳ 커스텀 백테스트 중"], cdemo: ["🧾 커스텀 데모 장부 보는 중"], clive: ["🔐 커스텀 실거래 심사 중"],
  ml: ["🧠 모델 학습 중"], btc: ["₿ 비트코인 차트 보는 중"], eth: ["Ξ 이더리움 차트 보는 중"], sol: ["◎ 솔라나 보는 중"], xrp: ["✕ 리플 보는 중"], doge: ["🐕 도지 보는 중"], bnb: ["🟡 BNB 보는 중"]};
